import Foundation
import Vision
import ImageIO

/// On-device scene labels via VNClassifyImageRequest (a-priori, no GT).
/// Input TSV: each line `photo_key<TAB>/abs/path.jpg` (no header), same as ocr_all.swift.
/// Output TSV header: photo, scene_top1, scene_top1_conf, scene_labels
///   scene_labels = id:conf|id:conf|... (top-k, tab-safe)
func classify(_ path: String, topK: Int = 8) -> [(String, Float)] {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return [] }
    let req = VNClassifyImageRequest()
    do {
        try VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
    } catch {
        return []
    }
    let obs = (req.results ?? []).prefix(topK)
    return obs.map { ($0.identifier, $0.confidence) }
}

func sanitize(_ s: String) -> String {
    s.replacingOccurrences(of: "\t", with: " ")
        .replacingOccurrences(of: "\n", with: " ")
        .replacingOccurrences(of: "|", with: "/")
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("usage: scene_classify.swift <input.tsv>\n", stderr)
    exit(2)
}
let raw = (try? String(contentsOfFile: args[1], encoding: .utf8)) ?? ""
print("photo\tscene_top1\tscene_top1_conf\tscene_labels")
let inputLines = raw.split(separator: "\n", omittingEmptySubsequences: false)
let total = inputLines.count
for (i, line) in inputLines.enumerated() {
    let c = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
    if c.count < 2 { continue }
    let key = c[0]
    let path = c[1]
    let pairs = classify(path)
    let top1 = pairs.first.map { sanitize($0.0) } ?? ""
    let top1c = pairs.first.map { String(format: "%.4f", $0.1) } ?? ""
    let joined = pairs.map { "\(sanitize($0.0)):\(String(format: "%.4f", $0.1))" }.joined(separator: "|")
    print("\(key)\t\(top1)\t\(top1c)\t\(joined)")
    FileHandle.standardError.write(
        "PROGRESS {\"done\":\(i + 1),\"total\":\(total),\"step\":\"classifying scene\"}\n"
            .data(using: .utf8)!
    )
}
