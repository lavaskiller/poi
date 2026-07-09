import http.server, socketserver, functools, json, csv, os, sys, tempfile
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
from validate_upload_package import validate_zip, ValidationError
from match_score import evaluate as evaluate_matchrate

DIRECTORY = "/Users/massis/Desktop/fastblog/poi-test-data"
PORT = 8420
CSV_PATH = os.path.join(DIRECTORY, "eval_set_reconciled.csv")
CONFIG_PATH = os.path.join(DIRECTORY, "dashboard_config.json")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def nonempty(rows, col):
    return sum(1 for r in rows if (r.get(col) or "").strip())


def tsv_counts(path, textcol=1):
    """(rows_with_text_in_col, total_data_rows) for a TSV with a header."""
    if not os.path.exists(path):
        return 0, 0
    total = withtext = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        next(f, None)
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            total += 1
            if len(parts) > textcol and parts[textcol].strip():
                withtext += 1
    return withtext, total


def tsv_datarows(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8", errors="replace") as f:
        return max(0, sum(1 for _ in f) - 1)


def build_overview():
    cfg = load_config()
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    n = len(rows)
    cols = list(rows[0].keys()) if rows else []
    warnings = []

    # ---- helpers driven by config ----
    def norm_country(r):
        ds = r.get("dataset")
        if ds in cfg["country_by_dataset"]:
            return cfg["country_by_dataset"][ds]
        c = (r.get("country") or "").strip()
        return cfg["country_normalize"].get(c, c or "Unknown")

    # ---- sources (structure from data, labels from config; unknown -> flagged) ----
    src_counts = Counter((r.get("dataset") or "").strip() for r in rows)
    sources = []
    for i, (k, v) in enumerate(src_counts.most_common()):
        c = cfg["sources"].get(k)
        if c is None:
            warnings.append(f"source '{k}' — config 없음 (dashboard_config.json > sources 에 추가)")
        sources.append({"key": k, "count": v,
                        "label": (c or {}).get("label", ""),
                        "color": (c or {}).get("color", cfg["palette"][i % len(cfg["palette"])]),
                        "owner": (c or {}).get("owner", ""),
                        "source_type": (c or {}).get("source_type", ""),
                        "desc": (c or {}).get("desc", ""),
                        "known": c is not None})

    # ---- confidence: roll raw gt_confidence up into canonical tiers (config-driven) ----
    raw_counts = Counter((r.get("gt_confidence") or "").strip() for r in rows)
    tier_counts, tier_members = Counter(), {}
    for raw, cnt in raw_counts.items():
        canon = cfg["confidence_rollup"].get(raw)
        if canon is None:
            warnings.append(f"gt_confidence '{raw}' — confidence_rollup 없음 (매핑 추가)")
            canon = raw  # surface as its own tier rather than dropping
        tier_counts[canon] += cnt
        tier_members.setdefault(canon, []).append([raw, cnt])
    tiers_cfg = cfg["confidence_tiers"]
    confidence = []
    for canon in sorted(tier_counts, key=lambda k: (tiers_cfg.get(k, {}).get("order", 99), -tier_counts[k])):
        meta = tiers_cfg.get(canon)
        if meta is None:
            warnings.append(f"canonical tier '{canon}' — confidence_tiers 에 정의 없음")
        members = sorted(tier_members[canon], key=lambda m: -m[1])
        confidence.append({"key": canon, "count": tier_counts[canon],
                           "color": (meta or {}).get("color", "ink3"),
                           "desc": (meta or {}).get("desc", ""),
                           "members": members, "known": meta is not None})

    # ---- countries ----
    country_counts = Counter(norm_country(r) for r in rows)
    countries = [{"key": k, "count": v, "flag": cfg["country_flags"].get(k, "·")}
                 for k, v in country_counts.most_common()]

    # ---- categories (pure data) ----
    cat_counts = Counter((r.get("category") or "").strip() for r in rows if (r.get("category") or "").strip())

    # ---- per-column fill ----
    fill = {c: nonempty(rows, c) for c in cols}

    # ---- schema: driven by REAL columns. Config supplies grouping/role/desc.
    #      Any real column not covered by a config group is surfaced, not dropped. ----
    covered = set()
    schema = []
    for g in cfg["schema_groups"]:
        present = [c for c in g["cols"] if c in fill]
        covered.update(g["cols"])
        if not present:
            continue  # group's columns don't exist in this CSV — skip silently (config ahead of data)
        rep = present[0]
        role = cfg["roles"].get(g["role"], {"label": g["role"], "tag": "t-mt"})
        schema.append({"group": g["group"], "role_key": g["role"], "role_label": role["label"],
                       "role_tag": role["tag"], "fill": fill[rep], "cols": present,
                       "desc": g["desc"], "known": True})
    uncovered = [c for c in cols if c not in covered]
    for c in uncovered:
        warnings.append(f"column '{c}' — schema_groups 에 없음 (역할/설명 추가 필요)")
        schema.append({"group": c, "role_key": "?", "role_label": "미분류", "role_tag": "t-mt",
                       "fill": fill[c], "cols": [c], "desc": "⚠ config에 설명 없음 — dashboard_config.json > schema_groups 에 추가하세요.", "known": False})

    # ---- sample rows (one per dataset) ----
    samples = {}
    for r in rows:
        d = r.get("dataset")
        if d and d not in samples:
            samples[d] = {k: (r.get(k) or "") for k in
                          ("gt_place_name", "gt_confidence", "category",
                           "capture_lat", "capture_lon", "city", "country", "photo", "photo_url")}

    # ---- pipeline: labels from config, counts from real files/columns ----
    def tsv_photoset(path):
        s = set()
        p = os.path.join(DIRECTORY, path)
        if not os.path.exists(p):
            return s
        with open(p, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                k = line.split("\t", 1)[0].strip()
                if k:
                    s.add(k)
        return s

    ls_ocr_text, _ = tsv_counts(os.path.join(DIRECTORY, "ls_ocr_text.tsv"))
    our_ocr_text, _ = tsv_counts(os.path.join(DIRECTORY, "ocr_text.tsv"))
    ocr_photos = tsv_photoset("ls_ocr_text.tsv") | tsv_photoset("ocr_text.tsv")   # 처리된 사진 (텍스트 유무 무관)
    base_photos = tsv_photoset("ls_nearby_results.tsv")                            # 베이스라인 계산된 사진
    csv_photos = [(r.get("photo") or "").strip() for r in rows]
    ocr_cov = sum(1 for p in csv_photos if p and p in ocr_photos)                  # OCR 커버된 CSV 행
    base_avail = sum(1 for r in rows if (r.get("photo") or "").strip() in base_photos
                     or (r.get("app_poi_rank") or "").strip())                     # 베이스라인 있는 행(파일∪CSV)

    # Status rule (single source of truth, shown in UI):
    #   extracted = 신호가 존재하는(계산된) 행수  ·  merged = 그게 CSV에 실제 반영된 행수
    #   wait : extracted==0        (미착수)
    #   done : merged >= extracted (추출된 게 전부 CSV에 들어감; scope 밖 행은 애초에 extracted에 없음)
    #   run  : 그 외              (추출됐지만 아직 CSV 미머지)
    def mk(p, extracted, merged, note=""):
        st = "wait" if extracted == 0 else ("done" if merged >= extracted else "run")
        return {"label": p["label"], "extracted": extracted, "merged": merged,
                "total": n, "status": st, "note": note}

    def step(p):
        kind = p["kind"]
        if kind == "column":
            f = fill.get(p["column"], 0)
            return mk(p, f, f)  # 컬럼 데이터는 추출=머지
        if kind == "ocr":
            txt = ls_ocr_text + our_ocr_text
            return mk(p, ocr_cov, ocr_cov, f"{txt} 텍스트 검출 · {ocr_cov-txt} 텍스트 없음")
        if kind == "baseline":
            merged = fill.get("app_poi_rank", 0)
            deferred = n - base_avail
            return mk(p, base_avail, merged, f"{deferred}행 제외(한국·무사진, kr_deferred)")
        if kind == "tsv":
            return mk(p, tsv_datarows(os.path.join(DIRECTORY, p["file"])), 0, "CSV 미머지")
        if kind == "file_exists":
            ok = os.path.exists(os.path.join(DIRECTORY, p["file"]))
            r = mk(p, n if ok else 0, n if ok else 0)
            if not ok:
                r["note"] = p.get("detail_wait", "")
            return r
        return mk(p, 0, 0)

    pipeline = [step(p) for p in cfg["pipeline"]]

    return {
        "generated_from": "eval_set_reconciled.csv + dashboard_config.json (live)",
        "total": n,
        "n_columns": len(cols),
        "palette": cfg["palette"],
        "sources": sources,
        "confidence": confidence,
        "countries": countries,
        "categories": cat_counts.most_common(12),
        "category_total_kinds": len(cat_counts),
        "fill": fill,
        "photo_present": fill.get("photo", 0),
        "gt_present": fill.get("gt_place_name", 0),
        "schema": schema,
        "samples": samples,
        "pipeline": pipeline,
        "config_warnings": warnings,
    }


def _photo_url(dataset, photo):
    if dataset == "linkedspaces":
        return "/linkedspaces-photos/" + photo
    if dataset == "vancouver":
        return "/photos/" + photo
    return ""  # union-city photos not served locally


def _parse_candidates(top3):
    out = []
    for part in (top3 or "").split(" | "):
        part = part.strip()
        if not part:
            continue
        name, _, dist = part.rpartition("@")
        out.append({"name": (name or part).strip(), "dist": dist.strip()})
    return out


def build_records(dataset_filter):
    cfg = load_config()
    roll = cfg["confidence_rollup"]
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # candidate lists from the MapKit probe
    cand = {}
    p = os.path.join(DIRECTORY, "ls_nearby_results.tsv")
    if os.path.exists(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 9 and c[0]:
                    cand[c[0]] = {"n": c[4], "rank": c[5], "dist": c[6], "top3": _parse_candidates(c[8])}

    def outcome(r):
        gt = (r.get("gt_place_name") or "").strip()
        conf = roll.get((r.get("gt_confidence") or "").strip(), "")
        rk = (r.get("app_poi_rank") or "").strip()
        if conf == "non_poi":
            return ("non_poi", "non_poi")
        if not gt:
            return ("no_gt", "no_gt")
        if not rk:
            return ("deferred", "deferred")
        if rk == "MISS":
            return ("retrieval", "검색실패")
        if rk == "1":
            return ("correct", "정답")
        if rk.isdigit():
            return ("selection", "식별실패")
        return ("other", rk)

    recs = []
    for r in rows:
        ds = r.get("dataset", "")
        if dataset_filter and dataset_filter != "all" and ds != dataset_filter:
            continue
        oc, ocl = outcome(r)
        photo = (r.get("photo") or "").strip()
        cd = cand.get(photo, {})
        ocr = (r.get("caption_ondevice") or "").strip()
        recs.append({
            "dataset": ds, "photo": photo, "photo_url": _photo_url(ds, photo),
            "gt": (r.get("gt_place_name") or "").strip(),
            "gt_confidence": (r.get("gt_confidence") or "").strip(),
            "category": (r.get("category") or "").strip(),
            "lat": (r.get("capture_lat") or "").strip()[:9],
            "lon": (r.get("capture_lon") or "").strip()[:9],
            "ocr_text": ocr[:240],
            "baseline_pick": (r.get("app_nearby_top1") or "").strip(),
            "rank": (r.get("app_poi_rank") or "").strip(),
            "n_wide": (r.get("app_nearby_n_wide") or "").strip() or cd.get("n", ""),
            "dist": (r.get("app_poi_dist_m") or "").strip() or cd.get("dist", ""),
            "candidates": cd.get("top3", []),
            "outcome": oc, "oc_label": ocl,
        })
    return recs


def build_matchrate(dataset_filter="all", mode="exact"):
    """Live MVP match-rate API.

    Scoring is intentionally provider-aware and exact by default:
    South Korea is currently held out until Kakao Local data is available;
    all other countries use MapKit.
    provider_place_id is optional/nullable and not required for matching.
    """
    return evaluate_matchrate(dataset=dataset_filter or "all", mode=mode or "exact")


class Handler(http.server.SimpleHTTPRequestHandler):
    def _send_json(self, payload_obj, code=200):
        payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/api/records":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ds = (q.get("dataset", ["all"])[0])
            try:
                self._send_json(build_records(ds))
            except Exception as e:
                self._send_json({"error": str(e)}, code=500)
            return
        if route == "/api/matchrate":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ds = (q.get("dataset", ["all"])[0])
            mode = (q.get("mode", ["exact"])[0])
            try:
                self._send_json(build_matchrate(ds, mode))
            except Exception as e:
                self._send_json({"error": str(e)}, code=500)
            return
        if route == "/api/overview":
            try:
                self._send_json(build_overview())
            except Exception as e:
                self._send_json({"error": str(e)}, code=500)
            return
        super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route != "/api/validate-upload-package":
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"ok": False, "error": "invalid Content-Length"}, code=400)
            return

        if content_length <= 0:
            self._send_json({"ok": False, "error": "empty upload"}, code=400)
            return

        max_bytes = 500 * 1024 * 1024
        if content_length > max_bytes:
            self._send_json({"ok": False, "error": "upload package is too large", "max_bytes": max_bytes}, code=413)
            return

        upload = self.rfile.read(content_length)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(upload)
                tmp_path = tmp.name
            result = validate_zip(tmp_path)
            self._send_json(result, code=200 if result.get("ok") else 422)
        except ValidationError as e:
            self._send_json({"ok": False, "errors": [{"code": "invalid_zip", "message": str(e)}], "warnings": [], "row_flags": []}, code=400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, code=500)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    os.chdir(DIRECTORY)
    handler = functools.partial(Handler, directory=DIRECTORY)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"serving {DIRECTORY} at http://127.0.0.1:{PORT}  (+ /api/overview live, config-driven)")
        httpd.serve_forever()
