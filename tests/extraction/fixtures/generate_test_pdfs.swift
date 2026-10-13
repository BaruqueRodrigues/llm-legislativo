// tests/extraction/fixtures/generate_test_pdfs.swift
// Gera fixtures sintéticas para teste de extração: digital, escaneado, misto, colunas e corrompido

import Foundation
import CoreGraphics
import CoreText
import PDFKit

func drawTextInPDF(
    context: CGContext,
    text: String,
    rect: CGRect,
    fontSize: CGFloat = 14.0
) {
    let font = CTFontCreateWithName("Helvetica" as CFString, fontSize, nil)
    let attributes: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(red: 0, green: 0, blue: 0, alpha: 1)
    ]

    let attrStr = CFAttributedStringCreate(nil, text as CFString, attributes as CFDictionary)!
    let framesetter = CTFramesetterCreateWithAttributedString(attrStr)
    let path = CGPath(rect: rect, transform: nil)
    let frame = CTFramesetterCreateFrame(framesetter, CFRangeMake(0, 0), path, nil)

    context.saveGState()
    context.textMatrix = .identity
    CTFrameDraw(frame, context)
    context.restoreGState()
}

func renderTextToBitmap(
    text: String,
    width: Int,
    height: Int,
    fontSize: CGFloat = 28.0
) -> CGImage? {
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return nil
    }

    // Fundo branco
    context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))

    let rect = CGRect(x: 80, y: 80, width: width - 160, height: height - 160)
    drawTextInPDF(context: context, text: text, rect: rect, fontSize: fontSize)

    return context.makeImage()
}

let outputDir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "tests/extraction/fixtures"
try? FileManager.default.createDirectory(atPath: outputDir, withIntermediateDirectories: true)

var pageRect = CGRect(x: 0, y: 0, width: 595, height: 842) // A4

// 1. native_digital.pdf (Texto digital nativo completo com Articulado e Justificação)
let nativePath = "\(outputDir)/native_digital.pdf"
let nativeURL = URL(fileURLWithPath: nativePath) as CFURL
if let ctx = CGContext(nativeURL, mediaBox: &pageRect, nil) {
    var box = pageRect
    ctx.beginPage(mediaBox: &box)
    let textP1 = """
    PROJETO DE LEI Nº 4.567, DE 2024
    (Do Sr. Deputado Carlos Silva)

    Dispõe sobre as diretrizes nacionais para governança de dados legislativos e transparência pública.

    O Congresso Nacional decreta:

    Art. 1º Esta Lei estabelece as diretrizes e normas gerais para a catalogação, preservação e difusão de dados legislativos oficiais no âmbito do Congresso Nacional.

    Art. 2º São princípios fundamentais da transparência legislativa:
    I - a autenticidade e a rastreabilidade dos documentos oficiais;
    II - a publicidade como preceito geral e o sigilo como exceção;
    III - a integridade histórica dos registros parlamentares.

    Art. 3º Esta Lei entra em vigor na data de sua publicação.
    """
    drawTextInPDF(context: ctx, text: textP1, rect: CGRect(x: 50, y: 100, width: 495, height: 650))
    ctx.endPage()

    ctx.beginPage(mediaBox: &box)
    let textP2 = """
    JUSTIFICAÇÃO

    O presente projeto de lei tem por objetivo modernizar o ecossistema de informações parlamentares, garantindo que cidadãos, pesquisadores e instituições tenham acesso irrestrito e reprodutível aos atos do Poder Legislativo.

    A disponibilização dos dados em formatos abertos e estruturados potencializa a cidadania fiscalizadora e fomenta o desenvolvimento tecnológico nacional com soberania.

    Diante da relevância da matéria para o fortalecimento da democracia brasileira, contamos com o apoio dos nobres pares para sua célere aprovação.

    Sala das Sessões, 15 de março de 2024.

    Deputado Carlos Silva
    """
    drawTextInPDF(context: ctx, text: textP2, rect: CGRect(x: 50, y: 100, width: 495, height: 650))
    ctx.endPage()
    ctx.closePDF()
    print("Gerado: \(nativePath)")
}

// 2. scanned_image.pdf (Apenas imagem rasterizada, zero camada de texto nativo)
let scannedPath = "\(outputDir)/scanned_image.pdf"
let scannedURL = URL(fileURLWithPath: scannedPath) as CFURL
let scannedText = """
PARECER Nº 123, DE 2024

DA COMISSÃO DE CONSTITUIÇÃO E JUSTIÇA E DE CIDADANIA

Sobre o Projeto de Lei nº 4.567, de 2024.

I - RELATÓRIO
Trata-se de proposição de autoria do ilustre Deputado Carlos Silva que visa regular as diretrizes de governança de dados legislativos. No prazo regimental, não foram apresentadas emendas.

II - VOTO DO RELATOR
A proposição atende a todos os requisitos constitucionais e regimentais de técnica legislativa. Quanto ao mérito, a iniciativa é meritória e fortalece as instituições democráticas.
Voto, portanto, pela constitucionalidade, juridicidade e aprovação do Projeto de Lei nº 4.567, de 2024.

Sala da Comissão, em 20 de abril de 2024.
Deputada Mariana Souza - Relatora
"""

if let cgImg = renderTextToBitmap(text: scannedText, width: 1190, height: 1684, fontSize: 26.0) {
    if let ctx = CGContext(scannedURL, mediaBox: &pageRect, nil) {
        var box = pageRect
        ctx.beginPage(mediaBox: &box)
        ctx.draw(cgImg, in: pageRect) // Desenha apenas o bitmap! Zero operadores de fonte/texto no PDF.
        ctx.endPage()
        ctx.closePDF()
        print("Gerado: \(scannedPath)")
    }
}

// 3. mixed_document.pdf (Página 1 nativa digital, Página 2 escaneada)
let mixedPath = "\(outputDir)/mixed_document.pdf"
let mixedURL = URL(fileURLWithPath: mixedPath) as CFURL
if let ctx = CGContext(mixedURL, mediaBox: &pageRect, nil) {
    var box = pageRect
    // P1: nativa
    ctx.beginPage(mediaBox: &box)
    let textMixedP1 = """
    EMENDA MODIFICATIVA Nº 1

    Dê-se ao Art. 1º do Projeto de Lei nº 4.567, de 2024, a seguinte redação:

    Art. 1º Esta Lei estabelece as diretrizes nacionais para a preservação histórica e a difusão digital integral do acervo legislativo da Câmara dos Deputados e do Senado Federal.

    Brasília, 2 de maio de 2024.
    Deputado Roberto Lima
    """
    drawTextInPDF(context: ctx, text: textMixedP1, rect: CGRect(x: 50, y: 100, width: 495, height: 650))
    ctx.endPage()

    // P2: escaneada (bitmap)
    if let cgImgP2 = renderTextToBitmap(text: "ANEXO ÚNICO\nTABELA COMPARATIVA DE IMPACTO REGULATÓRIO\nDispositivo alterado pelo substitutivo com vigência imediata.", width: 1190, height: 1684, fontSize: 30.0) {
        ctx.beginPage(mediaBox: &box)
        ctx.draw(cgImgP2, in: pageRect)
        ctx.endPage()
    }
    ctx.closePDF()
    print("Gerado: \(mixedPath)")
}

// 4. two_columns.pdf (Documento em duas colunas, estilo Anais/Diário da Câmara)
let columnsPath = "\(outputDir)/two_columns.pdf"
let columnsURL = URL(fileURLWithPath: columnsPath) as CFURL
let col1Text = "DIÁRIO DO CONGRESSO\nColuna 1 Linha 1\nColuna 1 Linha 2\nColuna 1 Linha 3\nO SR. PRESIDENTE: Declaro aberta a sessão deliberativa extraordinária."
let col2Text = "SUMÁRIO DA SESSÃO\nColuna 2 Linha 1\nColuna 2 Linha 2\nColuna 2 Linha 3\nA SRA. RELATORA: Solicito a leitura do relatório oficial da comissão."

let widthCol = 1200
let heightCol = 800
let colorSpace = CGColorSpaceCreateDeviceRGB()
if let bitmapContext = CGContext(data: nil, width: widthCol, height: heightCol, bitsPerComponent: 8, bytesPerRow: 0, space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) {
    bitmapContext.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    bitmapContext.fill(CGRect(x: 0, y: 0, width: widthCol, height: heightCol))

    // Coluna esquerda
    drawTextInPDF(context: bitmapContext, text: col1Text, rect: CGRect(x: 50, y: 50, width: 500, height: 700), fontSize: 24.0)
    // Coluna direita
    drawTextInPDF(context: bitmapContext, text: col2Text, rect: CGRect(x: 650, y: 50, width: 500, height: 700), fontSize: 24.0)

    if let colImg = bitmapContext.makeImage(), let ctx = CGContext(columnsURL, mediaBox: &pageRect, nil) {
        var box = pageRect
        ctx.beginPage(mediaBox: &box)
        ctx.draw(colImg, in: pageRect)
        ctx.endPage()
        ctx.closePDF()
        print("Gerado: \(columnsPath)")
    }
}

// 5. corrupt.pdf (Arquivo inválido / corrompido para teste de resiliência e tratamento de erro)
let corruptPath = "\(outputDir)/corrupt.pdf"
let corruptBytes: [UInt8] = [0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, 0x00, 0xFF, 0xFE, 0xFD, 0x0A]
let corruptData = Data(corruptBytes)
try? corruptData.write(to: URL(fileURLWithPath: corruptPath))
print("Gerado: \(corruptPath)")

print("Todas as fixtures de teste foram geradas com sucesso!")
