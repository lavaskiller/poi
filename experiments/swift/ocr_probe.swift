import Foundation
import Vision
import ImageIO
func ocr(_ path: String) -> String {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return "<load fail>" }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    try? VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
    let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    return lines.joined(separator: " | ")
}
let sem = DispatchSemaphore(value: 0)
for (label,p) in CommandLine.arguments.dropFirst().map({ ($0 as NSString).lastPathComponent }).enumerated().map({ (String($0.0), CommandLine.arguments[$0.0+1]) }) {
    print("[\(label)] \((p as NSString).lastPathComponent)\n   OCR: \(ocr(p))")
}
sem.signal()
