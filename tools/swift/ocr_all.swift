import Foundation
import Vision
import ImageIO
func ocr(_ path: String) -> String {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return "" }
    let req = VNRecognizeTextRequest(); req.recognitionLevel = .accurate; req.usesLanguageCorrection = true
    try? VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
    let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    var s = lines.joined(separator: " | ").replacingOccurrences(of: "\t", with: " ").replacingOccurrences(of: "\n", with: " ")
    if s.count > 600 { s = String(s.prefix(600)) }
    return s
}
let raw = (try? String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8)) ?? ""
print("photo\tocr_text")
let inputLines = raw.split(separator: "\n")
let total = inputLines.count
for (i, line) in inputLines.enumerated() {
    let c = line.components(separatedBy: "\t"); if c.count < 2 { continue }
    print("\(c[0])\t\(ocr(c[1]))")
    FileHandle.standardError.write("PROGRESS {\"done\":\(i + 1),\"total\":\(total),\"step\":\"recognizing text\"}\n".data(using: .utf8)!)
}
