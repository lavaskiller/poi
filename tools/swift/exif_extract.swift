import Foundation
import ImageIO

// Input: rid<TAB>absolute photo path. Output is TSV so the Python worker owns
// CSV locking and atomic replacement.
func text(_ value: Any?) -> String { return value.map { "\($0)" } ?? "" }
func number(_ value: Any?) -> Double? {
    if let n = value as? NSNumber { return n.doubleValue }
    return Double(text(value))
}
func coordinate(_ values: [CFString: Any], _ ref: CFString) -> Double? {
    guard let raw = number(values[kCGImagePropertyGPSLatitude]), let hemisphere = values[ref] as? String else { return nil }
    return (hemisphere.uppercased() == "S" || hemisphere.uppercased() == "W") ? -raw : raw
}

let lines = (try? String(contentsOfFile: CommandLine.arguments.dropFirst().first ?? "", encoding: .utf8))?.split(whereSeparator: \.isNewline) ?? []
print("rid\tcapture_lat\tcapture_lon\ttimestamp")
for (index, line) in lines.enumerated() {
    if index == 0 { continue }
    let parts = line.split(separator: "\t", maxSplits: 1, omittingEmptySubsequences: false)
    guard parts.count == 2 else { continue }
    let rid = String(parts[0]), path = String(parts[1])
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] else {
        print("\(rid)\t\t\t")
        continue
    }
    let gps = properties[kCGImagePropertyGPSDictionary] as? [CFString: Any] ?? [:]
    let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
    let tiff = properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
    let lat = coordinate(gps, kCGImagePropertyGPSLatitudeRef).map { String(format: "%.8f", $0) } ?? ""
    let lon = coordinate(gps, kCGImagePropertyGPSLongitudeRef).map { String(format: "%.8f", $0) } ?? ""
    // EXIF DateTimeOriginal has no timezone. Preserve it verbatim rather than
    // manufacturing a misleading UTC offset.
    let timestamp = text(exif[kCGImagePropertyExifDateTimeOriginal]).isEmpty
        ? text(tiff[kCGImagePropertyTIFFDateTime]) : text(exif[kCGImagePropertyExifDateTimeOriginal])
    print("\(rid)\t\(lat)\t\(lon)\t\(timestamp.replacingOccurrences(of: "\t", with: " "))")
}
