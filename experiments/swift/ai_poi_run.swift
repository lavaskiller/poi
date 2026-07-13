// ai_poi_run.swift — on-device Foundation Models runner with selectable PROMPT VARIANTS + retries.
// Usage: swift ai_poi_run.swift <input.tsv> <arm> <variant> [limit]
//   arm     : coords_only | caption_only | coords_caption
//   variant : v0 (plain) | v1 (strict refusal + venue definition) | v2 (v1 + few-shot)
// Output TSV: photo <tab> arm <tab> variant <tab> status <tab> raw

import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

let RULES_V0 = """
Rules:
- Prefer the venue named or clearly implied by the CONTENT (receipts, signage, screens, storefronts). Content outranks coordinates when they conflict.
- The GPS coordinate is only a prior. Do NOT name a nearby business just because the coordinate is near it. A coordinate alone is never enough to name a venue.
- If the content shows NO real ground venue — an in-flight entertainment screen, the interior of a moving vehicle, a blurry/dark shot with no place, or a private residence not in any public directory — set isNonPOI true and return the general AREA only. Never invent a venue to fill the gap.
- Area-or-category answers are acceptable when you cannot identify an exact venue.
"""

// v1: sharpen the definition of a "venue" and enumerate the non-venue triggers that failed in v0
// (in-flight screens -> airport, cable-car interior -> "cable car", street scene -> naming a vehicle).
let RULES_V1 = """
Definition: a VENUE is a specific named establishment or landmark that the photographer is physically AT as a customer/visitor — provable from signage, a receipt, interior branding, a menu/check, or being a recognizable landmark in frame.
Decide isNonPOI=true (return only the AREA, never a venue name) when ANY of these hold:
- The photo is a SCREEN, a photo-of-a-photo, a boarding pass, or an in-flight/entertainment display. A flight number or "CITY -> CITY" means you are IN TRANSIT (in the air / en route), NOT at either airport.
- The photo is the INTERIOR or exterior of a moving vehicle (car, cable car, tram, bus, train, plane). Riding a cable car is transit — do NOT return "cable car" as the venue.
- The subject is a vehicle, product, sign, or object on a street (e.g. a passing robotaxi). Never name an object in the scene; only name the establishment the photographer is inside/at.
- It is a private residence / lodging not in a public directory, or a blurry/dark frame with no identifiable place.
Only output a venue when the content PROVES the photographer is at that establishment. When unsure, prefer isNonPOI=true and the area. The GPS coordinate is a weak prior and is never sufficient on its own.
"""

let FEWSHOT_V2 = """

Examples:
Content: "Airplane seatback screen, flight ICN->SFO." GPS near SFO.
-> {"placeName":"near San Francisco (in transit)","granularity":"none","isNonPOI":true,"confidence":0.9}
Content: "Interior of an SF cable car, Municipal Railway emblem." GPS on California St.
-> {"placeName":"California St, San Francisco","granularity":"area","isNonPOI":true,"confidence":0.8}
Content: "A Zoox robotaxi at a downtown intersection, 'Sutter St' sign."
-> {"placeName":"Financial District, San Francisco","granularity":"area","isNonPOI":true,"confidence":0.8}
Content: "Safeway receipt, 1790 Decoto Rd, Union City."
-> {"placeName":"Safeway","granularity":"venue","isNonPOI":false,"confidence":0.95}
Content: "Person in front of the Palace of Fine Arts rotunda."
-> {"placeName":"Palace of Fine Arts","granularity":"venue","isNonPOI":false,"confidence":0.9}
"""

// v3: keep v2's refusal few-shot (which killed hallucination) but add a POSITIVE clause + venue
// examples so strong on-image evidence still yields the exact venue (recover the exact-rate v2 lost).
let POSITIVE_V3 = """
Balance: the refusal rules above apply ONLY to screens, vehicle interiors, street objects, private homes, and blurry frames. When the content contains explicit evidence of an establishment — a business name, signage, a receipt/menu/check, interior branding, a wifi/login card, or a recognizable landmark in frame — you MUST return that establishment as the venue (isNonPOI=false, granularity="venue"). Do not hide behind the area when the venue is proven by the content.
"""
let FEWSHOT_V3_POS = """
Content: "Gym signup screen: 24 Hour Fitness, 1200 Van Ness Ave, San Francisco."
-> {"placeName":"24 Hour Fitness","granularity":"venue","isNonPOI":false,"confidence":0.95}
Content: "Cafe wifi card reading 'CORGI CAFE PATRONS'."
-> {"placeName":"Corgi Cafe","granularity":"venue","isNonPOI":false,"confidence":0.9}
Content: "Entrance sign 'CAPILANO SUSPENSION BRIDGE'."
-> {"placeName":"Capilano Suspension Bridge","granularity":"venue","isNonPOI":false,"confidence":0.95}
"""

func systemPrompt(_ variant: String) -> String {
    let head = "You resolve the real-world place shown in a travel photo. You may be given a GPS coordinate, a general area name, and a one-line description of the photo's content.\n"
    let tail = "\nOutput ONLY one JSON object, no prose:\n{\"placeName\": string, \"granularity\": \"venue\"|\"area\"|\"none\", \"isNonPOI\": true|false, \"confidence\": 0.0-1.0}"
    switch variant {
    case "v1": return head + RULES_V1 + tail
    case "v2": return head + RULES_V1 + FEWSHOT_V2 + tail
    case "v3": return head + RULES_V1 + POSITIVE_V3 + FEWSHOT_V2 + FEWSHOT_V3_POS + tail
    default:   return head + RULES_V0 + tail
    }
}

func userPrompt(arm: String, lat: String, lon: String, area: String, caption: String) -> String {
    var lines: [String] = []
    if arm != "caption_only" {
        lines.append("GPS: \(lat), \(lon)")
        if !area.isEmpty { lines.append("Area: \(area)") }
    }
    if arm != "coords_only" { lines.append("Photo content: \(caption)") }
    if lines.isEmpty { lines.append("(no information provided)") }
    return lines.joined(separator: "\n")
}

let args = CommandLine.arguments
guard args.count >= 4 else { FileHandle.standardError.write("usage: ai_poi_run.swift <input.tsv> <arm> <variant> [limit]\n".data(using:.utf8)!); exit(1) }
let arm = args[2]; let variant = args[3]
let limit = args.count >= 5 ? Int(args[4]) : nil
let SYSTEM = systemPrompt(variant)
let raw = (try? String(contentsOfFile: args[1], encoding: .utf8)) ?? ""
var lines = raw.split(whereSeparator: { $0 == "\n" || $0 == "\r\n" }).map(String.init).filter { !$0.isEmpty }
if !lines.isEmpty { lines.removeFirst() }
struct Row { let photo,lat,lon,area,caption,kw,cls: String }
let rows: [Row] = lines.compactMap { l in
    let c = l.components(separatedBy: "\t"); guard c.count >= 7 else { return nil }
    return Row(photo:c[0],lat:c[1],lon:c[2],area:c[3],caption:c[4],kw:c[5],cls:c[6])
}
let work = limit != nil ? Array(rows.prefix(limit!)) : rows

setbuf(stdout, nil)
Task {
    print("photo\tarm\tvariant\tstatus\traw")
    #if canImport(FoundationModels)
    let opts = GenerationOptions(temperature: 0.0)
    for r in work {
        let prompt = userPrompt(arm: arm, lat: r.lat, lon: r.lon, area: r.area, caption: r.caption)
        var printed = false
        for attempt in 1...4 {   // the on-device model throws transient errors; retry a few times
            do {
                let session = LanguageModelSession(instructions: SYSTEM)
                let resp = try await session.respond(to: prompt, options: opts)
                let out = resp.content.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\t", with: " ")
                print("\(r.photo)\t\(arm)\t\(variant)\tok\t\(out)")
                printed = true; break
            } catch {
                if attempt == 4 { print("\(r.photo)\t\(arm)\t\(variant)\terror\t\(error)") }
                else { try? await Task.sleep(nanoseconds: 300_000_000) }
            }
        }
        _ = printed
    }
    #else
    for r in work { print("\(r.photo)\t\(arm)\t\(variant)\tNO_FM\t-") }
    #endif
    exit(0)
}
RunLoop.main.run()
