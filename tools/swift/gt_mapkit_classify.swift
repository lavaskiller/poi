// gt_mapkit_classify.swift
//
// Dump MapKit candidate place NAMES for each ground-truth row, so the caller can
// decide whether the user's raw `input_place_name` is written the MapKit way.
//
// This is NOT a canonical-name resolver. It performs a name search
// (MKLocalSearch.Request.naturalLanguageQuery, region-biased to the capture
// coordinate) and emits the top candidate names verbatim. The exact/normalized
// string comparison against the input — and the KOR/verbatim/SIM/NON decision —
// happens in Python (tools/gt_classify_mapkit.py) so it reuses match_score's
// equality functions. No distance cutoff is applied here: the classification is
// about NAME form, not proximity; the region bias already scopes results locally.
//
// Usage:  swift gt_mapkit_classify.swift <input.tsv> > <out.tsv>
//   input.tsv  header + rows: rid \t lat \t lon \t query   (rid = opaque unique row id)
//   out.tsv    header + rows: rid \t n \t candidates
//     candidates = up to TOP_N MapKit names in relevance order, joined by " ||| "
//                  (empty when MapKit returns nothing). "|" in a name -> "/".
//
// Pacing/short retry mirrors ls_mapkit_probe.swift to survive Apple Maps
// throttling, but retries are shortened: an empty result usually means the place
// simply is not in MapKit (-> the row will classify as NON_MAPKIT), so we do not
// pay the long cooldown the nearby-POI probe needs.

import Foundation
import MapKit
import CoreLocation

let REGION_M   = 30_000.0                       // region span biasing the search (~30km)
let TOP_N      = 8                               // candidate names emitted per row
let PACE_S: UInt64 = 1_200_000_000               // 1.2s between fresh (query,coord) lookups
let RETRY_WAITS: [UInt64] = [3_000_000_000, 6_000_000_000] // short cooldowns on empty (throttle blip)

func search(_ query: String, _ coord: CLLocationCoordinate2D) async -> [String] {
    let req = MKLocalSearch.Request()
    req.naturalLanguageQuery = query
    req.region = MKCoordinateRegion(center: coord,
                                    latitudinalMeters: REGION_M,
                                    longitudinalMeters: REGION_M)
    let s = MKLocalSearch(request: req)
    guard let resp = try? await s.start() else { return [] }
    // Preserve MapKit's relevance order.
    return resp.mapItems.compactMap {
        let n = ($0.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return n.isEmpty ? nil : n
    }
}

func esc(_ s: String) -> String {
    return s.replacingOccurrences(of: "\t", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "|", with: "/")
}

let args = CommandLine.arguments
guard args.count >= 2, let raw = try? String(contentsOfFile: args[1], encoding: .utf8) else {
    FileHandle.standardError.write("usage: swift gt_mapkit_classify.swift <input.tsv>\n".data(using: .utf8)!)
    exit(1)
}
var lines = raw.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
if !lines.isEmpty { lines.removeFirst() } // header

struct Row { let rid: String; let lat: Double; let lon: Double; let query: String }
let rows: [Row] = lines.compactMap { line in
    if line.trimmingCharacters(in: .whitespaces).isEmpty { return nil }
    let c = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
    guard c.count >= 4, let la = Double(c[1]), let lo = Double(c[2]) else { return nil }
    let q = c[3].trimmingCharacters(in: .whitespacesAndNewlines)
    guard !q.isEmpty else { return nil }
    return Row(rid: c[0], lat: la, lon: lo, query: q)
}

setbuf(stdout, nil)
Task {
    print("rid\tn\tcandidates")
    var cache = [String: [String]]()
    for r in rows {
        let key = String(format: "%@|%.4f,%.4f", r.query, r.lat, r.lon)
        let coord = CLLocationCoordinate2D(latitude: r.lat, longitude: r.lon)
        if cache[key] == nil {
            var names = await search(r.query, coord)
            var used = 0
            while names.isEmpty && used < RETRY_WAITS.count {
                FileHandle.standardError.write("  empty \"\(r.query)\" @\(r.lat),\(r.lon) retry \(used+1)\n".data(using: .utf8)!)
                try? await Task.sleep(nanoseconds: RETRY_WAITS[used])
                names = await search(r.query, coord)
                used += 1
            }
            cache[key] = names
            try? await Task.sleep(nanoseconds: PACE_S)
        }
        let names = cache[key]!
        let joined = names.prefix(TOP_N).map(esc).joined(separator: " ||| ")
        print("\(r.rid)\t\(names.count)\t\(joined)")
    }
    exit(0)
}
RunLoop.main.run()
