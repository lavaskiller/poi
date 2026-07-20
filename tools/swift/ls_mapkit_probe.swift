// ls_mapkit_probe.swift
//
// Throttle-resistant version of union-city-trip/mapkit_nearby_probe.swift.
// Same app path (MKLocalPointsOfInterestRequest strict 80m -> wide 250m, distance-only ranking),
// but paced to survive Apple Maps rate limiting over ~119 unique coords:
//   - base delay PACE_S between unique-coordinate lookups
//   - if a WIDE query returns 0 named POIs, retry after an exponential cooldown (RETRY_WAITS).
//     A genuinely-empty coord stays empty after the cooldown; a throttled one recovers.
//   - a coord is only accepted (and cached) once it's non-empty OR has exhausted retries.
//
// Usage:  swift ls_mapkit_probe.swift ls_probe_input.tsv > ls_nearby_results.tsv
//
// Column layout matches the original probe so downstream parsing is unchanged.

import Foundation
import MapKit
import CoreLocation

let STRICT_RADIUS = 80.0
let WIDE_RADIUS   = 250.0
let PACE_S: UInt64   = 1_500_000_000            // 1.5s between fresh unique-coord lookups
let RETRY_WAITS: [UInt64] = [4_000_000_000, 9_000_000_000, 15_000_000_000] // cooldowns on empty wide

struct Ranked {
    let name: String
    let category: String
    let dist: Double
    let providerPlaceID: String?
    let lat: Double
    let lon: Double
}

func nearby(_ coord: CLLocationCoordinate2D, radius: Double) async -> [Ranked] {
    let center = CLLocation(latitude: coord.latitude, longitude: coord.longitude)
    let req = MKLocalPointsOfInterestRequest(center: coord, radius: radius)
    let search = MKLocalSearch(request: req)
    guard let resp = try? await search.start() else { return [] }
    return resp.mapItems.compactMap { item -> Ranked? in
        let name = (item.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return nil }
        let loc = item.placemark.location
            ?? CLLocation(latitude: item.placemark.coordinate.latitude, longitude: item.placemark.coordinate.longitude)
        let d = center.distance(from: loc)
        guard d <= radius else { return nil }
        let coordinate = item.placemark.coordinate
        let identifier: String?
        if #available(macOS 15.0, *) {
            identifier = item.identifier?.rawValue
        } else {
            identifier = nil
        }
        return Ranked(name: name,
                      category: item.pointOfInterestCategory?.rawValue ?? "",
                      dist: d,
                      providerPlaceID: identifier,
                      lat: coordinate.latitude,
                      lon: coordinate.longitude)
    }.sorted { $0.dist < $1.dist }
}

func rankOf(_ keyword: String, in list: [Ranked]) -> Int? {
    guard !keyword.isEmpty else { return nil }
    let k = keyword.lowercased()
    for (i, r) in list.enumerated() where r.name.lowercased().contains(k) { return i + 1 }
    return nil
}

let args = CommandLine.arguments
guard args.count >= 2, let raw = try? String(contentsOfFile: args[1], encoding: .utf8) else {
    FileHandle.standardError.write("usage: swift ls_mapkit_probe.swift <input.tsv>\n".data(using: .utf8)!)
    exit(1)
}
var lines = raw.split(separator: "\n").map(String.init)
lines.removeFirst()

struct Row { let photo: String; let lat: Double; let lon: Double; let kw: String }
let rows: [Row] = lines.compactMap { line in
    let c = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
    guard c.count >= 4, let la = Double(c[1]), let lo = Double(c[2]) else { return nil }
    return Row(photo: c[0], lat: la, lon: lo, kw: c[3])
}

setbuf(stdout, nil)
Task {
    print("photo\tstrict_n\tstrict_rank\tstrict_dist\twide_n\twide_rank\twide_dist\tretries\ttop3_wide\twide_candidates_json")
    var cacheStrict = [String: [Ranked]](), cacheWide = [String: [Ranked]](), cacheRetries = [String: Int]()
    for (rowIndex, r) in rows.enumerated() {
        let key = String(format: "%.5f,%.5f", r.lat, r.lon)
        let coord = CLLocationCoordinate2D(latitude: r.lat, longitude: r.lon)
        if cacheWide[key] == nil {
            var s = await nearby(coord, radius: STRICT_RADIUS)
            var w = await nearby(coord, radius: WIDE_RADIUS)
            var used = 0
            // Empty wide result is suspect under throttling: cool down and retry.
            while w.isEmpty && used < RETRY_WAITS.count {
                FileHandle.standardError.write("PROGRESS {\"done\":\(rowIndex),\"total\":\(rows.count),\"step\":\"cooldown\",\"retries\":\(used+1),\"retry_reason\":\"empty MapKit nearby result\"}\n".data(using: .utf8)!)
                try? await Task.sleep(nanoseconds: RETRY_WAITS[used])
                w = await nearby(coord, radius: WIDE_RADIUS)
                if s.isEmpty { s = await nearby(coord, radius: STRICT_RADIUS) }
                used += 1
            }
            cacheStrict[key] = s; cacheWide[key] = w; cacheRetries[key] = used
            try? await Task.sleep(nanoseconds: PACE_S)
        }
        let s = cacheStrict[key]!, w = cacheWide[key]!
        let sr = rankOf(r.kw, in: s), wr = rankOf(r.kw, in: w)
        let srDist = sr != nil ? String(format: "%.0f", s[sr!-1].dist) : "-"
        let wrDist = wr != nil ? String(format: "%.0f", w[wr!-1].dist) : "-"
        let top3 = w.prefix(3).map { "\($0.name)@\(Int($0.dist))m" }.joined(separator: " | ")
        let fullCandidates: [[String: Any]] = w.enumerated().map { index, item in
            var value: [String: Any] = [
                "name": item.name,
                "category": item.category,
                "rank": index + 1,
                "distance_m": item.dist,
                "lat": item.lat,
                "lon": item.lon,
            ]
            if let placeID = item.providerPlaceID { value["provider_place_id"] = placeID }
            return value
        }
        let jsonData = try! JSONSerialization.data(withJSONObject: fullCandidates)
        let fullJSON = String(data: jsonData, encoding: .utf8)!
        print("\(r.photo)\t\(s.count)\t\(sr.map(String.init) ?? "MISS")\t\(srDist)\t\(w.count)\t\(wr.map(String.init) ?? "MISS")\t\(wrDist)\t\(cacheRetries[key]!)\t\(top3)\t\(fullJSON)")
        FileHandle.standardError.write("PROGRESS {\"done\":\(rowIndex + 1),\"total\":\(rows.count),\"step\":\"searching nearby POIs\",\"retries\":\(cacheRetries[key]!)}\n".data(using: .utf8)!)
    }
    exit(0)
}
RunLoop.main.run()
