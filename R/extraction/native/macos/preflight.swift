// R/extraction/native/macos/preflight.swift
// Verificação de ambiente macOS, PDFKit e suporte a OCR Apple Vision (pt-BR fast/accurate)
// Conforme docs/CONTRATOS_DADOS.md e Frente 03

import Foundation
import PDFKit
import Vision

struct VisionPreflightResult: Codable {
    let host_os: String
    let os_version: String
    let os_build: String
    let arch: String
    let swift_target: String
    let vision_available: Bool
    let vision_default_revision: Int
    let fast_languages_count: Int
    let fast_supports_pt_br: Bool
    let fast_languages: [String]
    let accurate_languages_count: Int
    let accurate_supports_pt_br: Bool
    let accurate_languages: [String]
    let preflight_passed: Bool
    let error_message: String?
}

func getOsBuild() -> String {
    var size: Int = 0
    sysctlbyname("kern.osversion", nil, &size, nil, 0)
    var machine = [CChar](repeating: 0, count: size)
    sysctlbyname("kern.osversion", &machine, &size, nil, 0)
    return String(cString: machine)
}

func getArch() -> String {
    var size: Int = 0
    sysctlbyname("hw.machine", nil, &size, nil, 0)
    var machine = [CChar](repeating: 0, count: size)
    sysctlbyname("hw.machine", &machine, &size, nil, 0)
    return String(cString: machine)
}

func runPreflight() -> VisionPreflightResult {
    let osVersion = ProcessInfo.processInfo.operatingSystemVersionString
    let osBuild = getOsBuild()
    let arch = getArch()

    let defaultRev = VNRecognizeTextRequest.defaultRevision

    var fastLangs: [String] = []
    var accLangs: [String] = []

    let fastRequest = VNRecognizeTextRequest()
    fastRequest.recognitionLevel = .fast
    if let langs = try? fastRequest.supportedRecognitionLanguages() {
        fastLangs = langs
    } else if let langs = try? VNRecognizeTextRequest.supportedRecognitionLanguages(for: .fast, revision: defaultRev) {
        fastLangs = langs
    }

    let accRequest = VNRecognizeTextRequest()
    accRequest.recognitionLevel = .accurate
    if let langs = try? accRequest.supportedRecognitionLanguages() {
        accLangs = langs
    } else if let langs = try? VNRecognizeTextRequest.supportedRecognitionLanguages(for: .accurate, revision: defaultRev) {
        accLangs = langs
    }

    let fastPtBr = fastLangs.contains("pt-BR") || fastLangs.contains("pt_BR")
    let accPtBr = accLangs.contains("pt-BR") || accLangs.contains("pt_BR")

    let passed = accPtBr // accurate pt-BR is required; fast is checked
    let errorMsg = passed ? nil : "Apple Vision não possui suporte confirmado a pt-BR neste host"

    return VisionPreflightResult(
        host_os: "macOS",
        os_version: osVersion,
        os_build: osBuild,
        arch: arch,
        swift_target: "arm64-apple-macos",
        vision_available: true,
        vision_default_revision: defaultRev,
        fast_languages_count: fastLangs.count,
        fast_supports_pt_br: fastPtBr,
        fast_languages: fastLangs,
        accurate_languages_count: accLangs.count,
        accurate_supports_pt_br: accPtBr,
        accurate_languages: accLangs,
        preflight_passed: passed,
        error_message: errorMsg
    )
}

let result = runPreflight()
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
if let data = try? encoder.encode(result), let jsonStr = String(data: data, encoding: .utf8) {
    print(jsonStr)
} else {
    print("{\"preflight_passed\": false, \"error_message\": \"JSON serialization failed\"}")
    exit(1)
}
