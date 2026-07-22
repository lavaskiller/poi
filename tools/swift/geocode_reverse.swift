// geocode_reverse.swift
//
// Reverse-geocode capture coordinates via MapKit (MKReverseGeocodingRequest).
// Input TSV (with header): rid \t lat \t lon
// Output TSV (stdout):     rid \t city \t country \t address
//
// Progress lines go to stderr as: PROGRESS {"done":N,"total":M}
//
// Empty fields mean "no result" — never invent a country. Python owns CSV merge.
//
// Entry model: Task.detached + dispatchMain() so `swift file.swift` does not
// deadlock (blocking the main thread on a semaphore starves the cooperative
// pool that runs async MapKit work).

import Foundation
import CoreLocation
import MapKit
import Contacts

func tsvEscape(_ s: String) -> String {
    s.replacingOccurrences(of: "\t", with: " ")
     .replacingOccurrences(of: "\r", with: " ")
     .replacingOccurrences(of: "\n", with: " ")
}

func progress(done: Int, total: Int) {
    let payload = "{\"done\":\(done),\"total\":\(total)}"
    FileHandle.standardError.write("PROGRESS \(payload)\n".data(using: .utf8)!)
}

struct PlaceParts {
    var city: String = ""
    var country: String = ""
    var address: String = ""
}

func parts(from item: MKMapItem) -> PlaceParts {
    var p = PlaceParts()
    let placemark = item.placemark
    p.city = placemark.locality
        ?? placemark.subAdministrativeArea
        ?? item.name
        ?? placemark.name
        ?? ""
    p.country = placemark.country
        ?? placemark.isoCountryCode
        ?? ""
    if let postal = placemark.postalAddress {
        let formatter = CNPostalAddressFormatter()
        let formatted = formatter.string(from: postal)
            .replacingOccurrences(of: "\n", with: ", ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if !formatted.isEmpty {
            p.address = formatted
            return p
        }
    }
    let bits = [
        item.name,
        placemark.thoroughfare,
        placemark.locality,
        placemark.administrativeArea,
        placemark.postalCode,
        placemark.country,
    ].compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
     .filter { !$0.isEmpty }
    var out: [String] = []
    for b in bits {
        if out.last != b { out.append(b) }
    }
    p.address = out.joined(separator: ", ")
    return p
}

func reverseGeocode(lat: Double, lon: Double) async -> PlaceParts {
    let location = CLLocation(latitude: lat, longitude: lon)
    let retries = 3
    for attempt in 0..<retries {
        guard let request = MKReverseGeocodingRequest(location: location) else {
            return PlaceParts()
        }
        do {
            let items = try await request.mapItems
            if let first = items.first {
                return parts(from: first)
            }
            return PlaceParts()
        } catch {
            if attempt + 1 >= retries {
                return PlaceParts()
            }
            try? await Task.sleep(nanoseconds: UInt64(1_500_000_000 * (attempt + 1)))
        }
    }
    return PlaceParts()
}

struct Row { let rid: String; let lat: Double; let lon: Double }

let args = CommandLine.arguments
guard args.count >= 2,
      let raw = try? String(contentsOfFile: args[1], encoding: .utf8) else {
    FileHandle.standardError.write(
        "usage: swift geocode_reverse.swift <input.tsv>\n".data(using: .utf8)!)
    exit(1)
}

var rows: [Row] = []
for (i, line) in raw.split(whereSeparator: \.isNewline).enumerated() {
    if i == 0 { continue }
    let cols = line.split(separator: "\t", maxSplits: 2, omittingEmptySubsequences: false)
    guard cols.count >= 3 else { continue }
    let rid = String(cols[0])
    guard let lat = Double(cols[1].trimmingCharacters(in: .whitespaces)),
          let lon = Double(cols[2].trimmingCharacters(in: .whitespaces)),
          lat.isFinite, lon.isFinite,
          abs(lat) <= 90, abs(lon) <= 180 else {
        continue
    }
    rows.append(Row(rid: rid, lat: lat, lon: lon))
}

Task.detached {
    print("rid\tcity\tcountry\taddress")
    let total = rows.count
    progress(done: 0, total: total)
    // Pace reverse-geocode calls to avoid rate limits on mid-size datasets.
    let paceNs: UInt64 = 600_000_000
    for (i, row) in rows.enumerated() {
        let p = await reverseGeocode(lat: row.lat, lon: row.lon)
        print("\(row.rid)\t\(tsvEscape(p.city))\t\(tsvEscape(p.country))\t\(tsvEscape(p.address))")
        fflush(stdout)
        progress(done: i + 1, total: total)
        if i + 1 < total {
            try? await Task.sleep(nanoseconds: paceNs)
        }
    }
    exit(0)
}
dispatchMain()
