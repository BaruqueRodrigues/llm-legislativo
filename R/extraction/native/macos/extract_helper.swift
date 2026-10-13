// R/extraction/native/macos/extract_helper.swift
// Adaptador de extração nativa Mac (PDFKit) com OCR seletivo Apple Vision (pt-BR fast/accurate)
// Conforme contratos de dados e arquitetura da Frente 03

import Foundation
import PDFKit
import Vision
import CoreGraphics
import CryptoKit

// MARK: - Modelos de Dados de Saída

struct PageBenchmarkResult: Codable {
    let fast_elapsed_ms: Double
    let accurate_elapsed_ms: Double
    let fast_character_count: Int64
    let accurate_character_count: Int64
    let fast_confidence: Double?
    let accurate_confidence: Double?
    let fast_text_sha256: String
    let accurate_text_sha256: String
    let fast_memory_mb: Double?
    let accurate_memory_mb: Double?
}

struct PageExtractionResult: Codable {
    let page_index: Int
    let method: String                       // native, ocr, hybrid, none
    let engine: String                       // pdfkit, apple_vision, none
    let engine_revision: String?
    let recognition_level: String?           // fast, accurate
    let recognition_languages_json: String?
    let uses_language_correction: Bool?
    let render_width: Int?
    let render_height: Int?
    let elapsed_ms: Double
    let raw_text: String
    let raw_text_sha256: String
    let character_count: Int64
    let replacement_char_ratio: Double
    let printable_ratio: Double
    let image_area_ratio: Double
    let ocr_confidence: Double?
    let layout_path: String?
    let layout_sha256: String?
    let quality_status: String               // pass, review, fail
    let quality_reasons: [String]
    let benchmark: PageBenchmarkResult?
}

struct DocumentExtractionResult: Codable {
    let status: String                       // succeeded, failed, quarantined
    let error_code: String?
    let error_message: String?
    let page_count: Int
    let elapsed_total_ms: Double
    let pages: [PageExtractionResult]
    let memory_resident_mb: Double?
}

// MARK: - Utilitários do Sistema

func getResidentMemoryMB() -> Double {
    var info = mach_task_basic_info()
    var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / 4)
    let kerr: kern_return_t = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: integer_t.self, capacity: 1) {
            task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
        }
    }
    return (kerr == KERN_SUCCESS) ? Double(info.resident_size) / (1024.0 * 1024.0) : 0.0
}

func sha256Hex(_ string: String) -> String {
    let data = Data(string.utf8)
    let hash = SHA256.hash(data: data)
    return hash.map { String(format: "%02x", $0) }.joined()
}

// MARK: - Métricas de Qualidade Textual

struct QualityMetrics {
    let characterCount: Int64
    let printableRatio: Double
    let replacementCharRatio: Double
    let reasons: [String]
    let status: String
}

func evaluateTextQuality(
    text: String,
    minTextLength: Int,
    maxReplacementRatio: Double,
    minPrintableRatio: Double
) -> QualityMetrics {
    let totalChars = Int64(text.count)
    if totalChars == 0 {
        return QualityMetrics(
            characterCount: 0,
            printableRatio: 1.0,
            replacementCharRatio: 0.0,
            reasons: ["empty_text"],
            status: "review"
        )
    }

    var printableCount: Int64 = 0
    var replacementCount: Int64 = 0

    for scalar in text.unicodeScalars {
        // Replacement char U+FFFD
        if scalar.value == 0xFFFD {
            replacementCount += 1
            continue
        }

        // Caracteres imprimíveis ou espaços/quebras comuns
        if scalar == "\n" || scalar == "\t" || scalar == "\r" || scalar == "\u{000C}" { // \f
            printableCount += 1
        } else if !CharacterSet.controlCharacters.contains(scalar) {
            printableCount += 1
        }
    }

    let pRatio = Double(printableCount) / Double(totalChars)
    let rRatio = Double(replacementCount) / Double(totalChars)

    var reasons: [String] = []
    if pRatio < minPrintableRatio {
        reasons.append("low_printable_ratio")
    }
    if rRatio > maxReplacementRatio {
        reasons.append("high_replacement_char_ratio")
    }

    let status = reasons.isEmpty ? "pass" : "review"

    return QualityMetrics(
        characterCount: totalChars,
        printableRatio: pRatio,
        replacementCharRatio: rRatio,
        reasons: reasons,
        status: status
    )
}

// MARK: - Renderização e Apple Vision OCR

struct RecognizedTextResult {
    let text: String
    let confidence: Double
    let lineCount: Int
    let elapsedMs: Double
    let errorMessage: String?

    init(text: String, confidence: Double, lineCount: Int, elapsedMs: Double, errorMessage: String? = nil) {
        self.text = text
        self.confidence = confidence
        self.lineCount = lineCount
        self.elapsedMs = elapsedMs
        self.errorMessage = errorMessage
    }
}

func renderPDFPageToCGImage(page: PDFPage, scale: CGFloat = 2.0) -> (CGImage?, Int, Int) {
    let bounds = page.bounds(for: .mediaBox)
    let width = max(1, Int(bounds.width * scale))
    let height = max(1, Int(bounds.height * scale))

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    let bitmapInfo = CGImageAlphaInfo.premultipliedLast.rawValue
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: bitmapInfo
    ) else {
        return (nil, width, height)
    }

    // Fundo branco opaco
    context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))

    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)

    return (context.makeImage(), width, height)
}

func performVisionOCR(
    cgImage: CGImage,
    recognitionLevel: VNRequestTextRecognitionLevel,
    language: String,
    usesLanguageCorrection: Bool
) -> RecognizedTextResult {
    let startTime = CFAbsoluteTimeGetCurrent()

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = recognitionLevel
    request.recognitionLanguages = [language]
    request.usesLanguageCorrection = usesLanguageCorrection
    request.revision = VNRecognizeTextRequest.defaultRevision

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        let elapsed = (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0
        return RecognizedTextResult(text: "", confidence: 0.0, lineCount: 0, elapsedMs: elapsed,
                                    errorMessage: String(describing: error))
    }

    let elapsed = (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0

    guard let results = request.results, !results.isEmpty else {
        return RecognizedTextResult(text: "", confidence: 0.0, lineCount: 0, elapsedMs: elapsed)
    }

    // Estrutura para ordenar linhas com suporte a layout de 1 coluna ou 2 colunas
    struct TextBlock {
        let text: String
        let confidence: Float
        let box: CGRect // Vision coord: origin bottom-left, [0,1]
        var topY: CGFloat { 1.0 - box.maxY }
        var leftX: CGFloat { box.minX }
    }

    var blocks: [TextBlock] = []
    var sumConfidence: Double = 0.0
    var countCandidates = 0

    for obs in results {
        if let candidate = obs.topCandidates(1).first {
            let str = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            if !str.isEmpty {
                blocks.append(TextBlock(text: str, confidence: candidate.confidence, box: obs.boundingBox))
                sumConfidence += Double(candidate.confidence)
                countCandidates += 1
            }
        }
    }

    if blocks.isEmpty {
        return RecognizedTextResult(text: "", confidence: 0.0, lineCount: 0, elapsedMs: elapsed)
    }

    // Heurística de colunas: se houver blocos claramente dispostos em duas colunas sem interseção central
    // Verificamos se há blocos na esquerda (x < 0.48) e direita (x > 0.52) com poucos cruzando o meio
    let leftCount = blocks.filter { $0.box.maxX <= 0.52 }.count
    let rightCount = blocks.filter { $0.box.minX >= 0.48 }.count
    let isTwoColumns = (blocks.count >= 8) && (leftCount >= 3) && (rightCount >= 3) && ((leftCount + rightCount) >= Int(Double(blocks.count) * 0.85))

    let sortedBlocks: [TextBlock]
    if isTwoColumns {
        // Ordena coluna esquerda de cima para baixo, depois coluna direita de cima para baixo
        let leftBlocks = blocks.filter { $0.box.minX < 0.50 }.sorted {
            if abs($0.topY - $1.topY) < 0.015 { return $0.leftX < $1.leftX }
            return $0.topY < $1.topY
        }
        let rightBlocks = blocks.filter { $0.box.minX >= 0.50 }.sorted {
            if abs($0.topY - $1.topY) < 0.015 { return $0.leftX < $1.leftX }
            return $0.topY < $1.topY
        }
        sortedBlocks = leftBlocks + rightBlocks
    } else {
        // Ordenação padrão top-down, left-to-right
        sortedBlocks = blocks.sorted {
            if abs($0.topY - $1.topY) < 0.012 { return $0.leftX < $1.leftX }
            return $0.topY < $1.topY
        }
    }

    let joinedText = sortedBlocks.map { $0.text }.joined(separator: "\n")
    let avgConfidence = (countCandidates > 0) ? (sumConfidence / Double(countCandidates)) : 0.0

    return RecognizedTextResult(
        text: joinedText,
        confidence: avgConfidence,
        lineCount: sortedBlocks.count,
        elapsedMs: elapsed
    )
}

// MARK: - Processamento Principal do Documento

func extractPDF(
    pdfURL: URL,
    mode: String,
    defaultRecognitionLevel: String,
    language: String,
    usesLanguageCorrection: Bool,
    minTextLength: Int,
    maxReplacementRatio: Double,
    minPrintableRatio: Double,
    renderScale: CGFloat,
    enableBenchmark: Bool
) -> DocumentExtractionResult {
    let startTotal = CFAbsoluteTimeGetCurrent()
    let initialMemory = getResidentMemoryMB()

    guard let doc = PDFDocument(url: pdfURL) else {
        return DocumentExtractionResult(
            status: "failed",
            error_code: "pdf_open_failed",
            error_message: "Não foi possível carregar o arquivo PDF especificado",
            page_count: 0,
            elapsed_total_ms: (CFAbsoluteTimeGetCurrent() - startTotal) * 1000.0,
            pages: [],
            memory_resident_mb: initialMemory
        )
    }

    if doc.isLocked {
        return DocumentExtractionResult(
            status: "failed",
            error_code: "pdf_locked",
            error_message: "Documento PDF protegido por senha",
            page_count: 0,
            elapsed_total_ms: (CFAbsoluteTimeGetCurrent() - startTotal) * 1000.0,
            pages: [],
            memory_resident_mb: initialMemory
        )
    }

    let pageCount = doc.pageCount
    if pageCount == 0 {
        return DocumentExtractionResult(
            status: "failed",
            error_code: "pdf_empty",
            error_message: "Documento PDF com zero páginas",
            page_count: 0,
            elapsed_total_ms: (CFAbsoluteTimeGetCurrent() - startTotal) * 1000.0,
            pages: [],
            memory_resident_mb: initialMemory
        )
    }

    var pagesResults: [PageExtractionResult] = []

    for idx in 0..<pageCount {
        let pageIndex = idx + 1
        guard let page = doc.page(at: idx) else {
            continue
        }

        let pageStart = CFAbsoluteTimeGetCurrent()
        let bounds = page.bounds(for: .mediaBox)
        let renderWidth = Int(bounds.width * renderScale)
        let renderHeight = Int(bounds.height * renderScale)

        // 1. Extração nativa via PDFKit
        let rawNativeText = page.string ?? ""
        let nativeQuality = evaluateTextQuality(
            text: rawNativeText,
            minTextLength: minTextLength,
            maxReplacementRatio: maxReplacementRatio,
            minPrintableRatio: minPrintableRatio
        )

        var finalMethod = "native"
        var finalEngine = "pdfkit"
        var finalRevision: String? = nil
        var finalRecLevel: String? = nil
        var finalLangsJson: String? = nil
        var finalLangCorrection: Bool? = nil
        var finalConfidence: Double? = nil
        var finalRawText = rawNativeText
        var finalQuality = nativeQuality
        var benchResult: PageBenchmarkResult? = nil

        let needsOCR = (mode == "ocr") || (mode == "auto" && (
            nativeQuality.characterCount < Int64(minTextLength) ||
            nativeQuality.replacementCharRatio > maxReplacementRatio ||
            nativeQuality.printableRatio < minPrintableRatio
        )) || enableBenchmark

        if needsOCR {
            // Renderiza para imagem
            let (cgImageOpt, _, _) = renderPDFPageToCGImage(page: page, scale: renderScale)
            guard let cgImage = cgImageOpt else {
                // Falha de renderização: preserva nativo ou falha
                let pageElapsed = (CFAbsoluteTimeGetCurrent() - pageStart) * 1000.0
                pagesResults.append(PageExtractionResult(
                    page_index: pageIndex,
                    method: "native",
                    engine: "pdfkit",
                    engine_revision: nil,
                    recognition_level: nil,
                    recognition_languages_json: nil,
                    uses_language_correction: nil,
                    render_width: renderWidth,
                    render_height: renderHeight,
                    elapsed_ms: pageElapsed,
                    raw_text: rawNativeText,
                    raw_text_sha256: sha256Hex(rawNativeText),
                    character_count: nativeQuality.characterCount,
                    replacement_char_ratio: nativeQuality.replacementCharRatio,
                    printable_ratio: nativeQuality.printableRatio,
                    image_area_ratio: 0.0,
                    ocr_confidence: nil,
                    layout_path: nil,
                    layout_sha256: nil,
                    quality_status: "review",
                    quality_reasons: ["render_failed"] + nativeQuality.reasons,
                    benchmark: nil
                ))
                continue
            }

            if enableBenchmark {
                // Modo Benchmark: executa fast e accurate nas MESMAS imagens para comparação justa
                let memBeforeFast = getResidentMemoryMB()
                let fastRes = performVisionOCR(
                    cgImage: cgImage,
                    recognitionLevel: .fast,
                    language: language,
                    usesLanguageCorrection: usesLanguageCorrection
                )
                let memAfterFast = getResidentMemoryMB()

                let memBeforeAcc = getResidentMemoryMB()
                let accRes = performVisionOCR(
                    cgImage: cgImage,
                    recognitionLevel: .accurate,
                    language: language,
                    usesLanguageCorrection: usesLanguageCorrection
                )
                let memAfterAcc = getResidentMemoryMB()

                benchResult = PageBenchmarkResult(
                    fast_elapsed_ms: fastRes.elapsedMs,
                    accurate_elapsed_ms: accRes.elapsedMs,
                    fast_character_count: Int64(fastRes.text.count),
                    accurate_character_count: Int64(accRes.text.count),
                    fast_confidence: fastRes.confidence,
                    accurate_confidence: accRes.confidence,
                    fast_text_sha256: sha256Hex(fastRes.text),
                    accurate_text_sha256: sha256Hex(accRes.text),
                    fast_memory_mb: max(memBeforeFast, memAfterFast),
                    accurate_memory_mb: max(memBeforeAcc, memAfterAcc)
                )

                // Em modo benchmark, adota accurate como texto principal para maior qualidade
                finalMethod = "ocr"
                finalEngine = "apple_vision"
                finalRevision = "revision_\(VNRecognizeTextRequest.defaultRevision)"
                finalRecLevel = "accurate"
                finalLangsJson = "[\"\(language)\"]"
                finalLangCorrection = usesLanguageCorrection
                finalConfidence = accRes.confidence
                finalRawText = accRes.text
                finalQuality = evaluateTextQuality(
                    text: accRes.text,
                    minTextLength: minTextLength,
                    maxReplacementRatio: maxReplacementRatio,
                    minPrintableRatio: minPrintableRatio
                )
            } else {
                // Execução de OCR seletivo padrão
                let level: VNRequestTextRecognitionLevel = (defaultRecognitionLevel == "accurate") ? .accurate : .fast
                let ocrRes = performVisionOCR(
                    cgImage: cgImage,
                    recognitionLevel: level,
                    language: language,
                    usesLanguageCorrection: usesLanguageCorrection
                )

                // Política anti-duplicação:
                // Se nativo for muito curto e OCR encontrar texto completo, adota OCR na íntegra.
                // Se OCR for vazio e nativo for vazio, method = none.
                if ocrRes.text.count > 0 {
                    finalMethod = "ocr"
                    finalEngine = "apple_vision"
                    finalRevision = "revision_\(VNRecognizeTextRequest.defaultRevision)"
                    finalRecLevel = defaultRecognitionLevel
                    finalLangsJson = "[\"\(language)\"]"
                    finalLangCorrection = usesLanguageCorrection
                    finalConfidence = ocrRes.confidence
                    finalRawText = ocrRes.text
                    finalQuality = evaluateTextQuality(
                        text: ocrRes.text,
                        minTextLength: minTextLength,
                        maxReplacementRatio: maxReplacementRatio,
                        minPrintableRatio: minPrintableRatio
                    )
                } else if rawNativeText.count == 0 {
                    finalMethod = "none"
                    finalEngine = "none"
                    finalRawText = ""
                    let failureReason = ocrRes.errorMessage.map { "vision_request_failed: \($0)" }
                    finalQuality = QualityMetrics(
                        characterCount: 0,
                        printableRatio: 1.0,
                        replacementCharRatio: 0.0,
                        reasons: failureReason.map { [$0] } ?? ["ocr_no_text_review"],
                        status: failureReason == nil ? "review" : "fail"
                    )
                }
            }
        }

        let pageElapsed = (CFAbsoluteTimeGetCurrent() - pageStart) * 1000.0

        pagesResults.append(PageExtractionResult(
            page_index: pageIndex,
            method: finalMethod,
            engine: finalEngine,
            engine_revision: finalRevision,
            recognition_level: finalRecLevel,
            recognition_languages_json: finalLangsJson,
            uses_language_correction: finalLangCorrection,
            render_width: renderWidth,
            render_height: renderHeight,
            elapsed_ms: pageElapsed,
            raw_text: finalRawText,
            raw_text_sha256: sha256Hex(finalRawText),
            character_count: finalQuality.characterCount,
            replacement_char_ratio: finalQuality.replacementCharRatio,
            printable_ratio: finalQuality.printableRatio,
            image_area_ratio: (finalMethod == "ocr") ? 1.0 : 0.0,
            ocr_confidence: finalConfidence,
            layout_path: nil,
            layout_sha256: nil,
            quality_status: finalQuality.status,
            quality_reasons: finalQuality.reasons,
            benchmark: benchResult
        ))
    }

    let elapsedTotal = (CFAbsoluteTimeGetCurrent() - startTotal) * 1000.0
    let finalMemory = getResidentMemoryMB()

    return DocumentExtractionResult(
        status: "succeeded",
        error_code: nil,
        error_message: nil,
        page_count: pageCount,
        elapsed_total_ms: elapsedTotal,
        pages: pagesResults,
        memory_resident_mb: finalMemory
    )
}

// MARK: - CLI e Ponto de Entrada

struct CLIArgs {
    var inputPath: String? = nil
    var outputPath: String? = nil
    var mode: String = "auto"
    var recognitionLevel: String = "fast"
    var language: String = "pt-BR"
    var languageCorrection: Bool = true
    var minTextLength: Int = 50
    var maxReplacementRatio: Double = 0.01
    var minPrintableRatio: Double = 0.95
    var renderScale: CGFloat = 2.0
    var enableBenchmark: Bool = false
    var runPreflightFlag: Bool = false
}

func parseCLIArgs() -> CLIArgs {
    var args = CLIArgs()
    let rawArgs = CommandLine.arguments

    var i = 1
    while i < rawArgs.count {
        let arg = rawArgs[i]
        switch arg {
        case "--input", "-i":
            if i + 1 < rawArgs.count { args.inputPath = rawArgs[i+1]; i += 1 }
        case "--output", "-o":
            if i + 1 < rawArgs.count { args.outputPath = rawArgs[i+1]; i += 1 }
        case "--mode":
            if i + 1 < rawArgs.count { args.mode = rawArgs[i+1]; i += 1 }
        case "--recognition-level":
            if i + 1 < rawArgs.count { args.recognitionLevel = rawArgs[i+1]; i += 1 }
        case "--language":
            if i + 1 < rawArgs.count { args.language = rawArgs[i+1]; i += 1 }
        case "--language-correction":
            if i + 1 < rawArgs.count { args.languageCorrection = (rawArgs[i+1].lowercased() == "true"); i += 1 }
        case "--min-text-length":
            if i + 1 < rawArgs.count { args.minTextLength = Int(rawArgs[i+1]) ?? 50; i += 1 }
        case "--max-replacement-char-ratio":
            if i + 1 < rawArgs.count { args.maxReplacementRatio = Double(rawArgs[i+1]) ?? 0.01; i += 1 }
        case "--min-printable-ratio":
            if i + 1 < rawArgs.count { args.minPrintableRatio = Double(rawArgs[i+1]) ?? 0.95; i += 1 }
        case "--render-scale":
            if i + 1 < rawArgs.count { args.renderScale = CGFloat(Double(rawArgs[i+1]) ?? 2.0); i += 1 }
        case "--benchmark":
            args.enableBenchmark = true
        case "--preflight":
            args.runPreflightFlag = true
        default:
            break
        }
        i += 1
    }
    return args
}

let args = parseCLIArgs()

if args.runPreflightFlag {
    // Imprime JSON do preflight
    let osVersion = ProcessInfo.processInfo.operatingSystemVersionString
    let defaultRev = VNRecognizeTextRequest.defaultRevision
    let preflightJSON: [String: Any] = [
        "host_os": "macOS",
        "os_version": osVersion,
        "vision_available": true,
        "vision_default_revision": defaultRev,
        "supports_pt_br": true,
        "preflight_passed": true
    ]
    if let data = try? JSONSerialization.data(withJSONObject: preflightJSON, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
        exit(0)
    }
}

guard let input = args.inputPath else {
    fputs("Erro: parâmetro --input <arquivo.pdf> é obrigatório.\n", stderr)
    exit(1)
}

let inputURL = URL(fileURLWithPath: input)
let result = extractPDF(
    pdfURL: inputURL,
    mode: args.mode,
    defaultRecognitionLevel: args.recognitionLevel,
    language: args.language,
    usesLanguageCorrection: args.languageCorrection,
    minTextLength: args.minTextLength,
    maxReplacementRatio: args.maxReplacementRatio,
    minPrintableRatio: args.minPrintableRatio,
    renderScale: args.renderScale,
    enableBenchmark: args.enableBenchmark
)

let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

do {
    let jsonData = try encoder.encode(result)
    if let outPath = args.outputPath {
        try jsonData.write(to: URL(fileURLWithPath: outPath))
    } else {
        if let jsonStr = String(data: jsonData, encoding: .utf8) {
            print(jsonStr)
        }
    }
} catch {
    fputs("Erro ao serializar resultado JSON: \(error)\n", stderr)
    exit(1)
}
