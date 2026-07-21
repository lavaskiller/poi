#!/usr/bin/env python3
"""Render a run's per-case results as a case-types HTML in the same visual
format as docs/reports/poi-case-types.html, grouped by match_kind.

The CSS/theme is reused verbatim from a reference HTML so the look matches the
original baseline diagnostic. Only the body (metrics, distribution bar, result
panel, per-kind photo galleries) is regenerated from the run JSON.

The output embeds real user photo thumbnails and must NOT be committed
(see .gitignore).

Usage:
  python3 tools/render_case_types.py \
    --run poi-data/generated/runs/selector-loop70-pass__v1.json \
    --out docs/reports/poi-case-types-loop70.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import re
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None

REPO = Path(__file__).resolve().parent.parent
REF_HTML = REPO / "docs" / "reports" / "poi-case-types.html"

# match_kind → (label, palette-var, one-line description, counts-toward-canonical)
KIND_META = {
    "exact":          ("Exact",          "var(--now)",     "Model named the GT place directly.", True),
    "alias":          ("Alias",          "var(--accent)",  "Provider naming variant of the same place (accepted_aliases).", True),
    "related_credit": ("Related credit", "var(--policy)",  "Landed on a sub-POI / amenity of the GT (policy credit).", True),
    "related":        ("Related (no credit)", "var(--k)",  "Related but not credited — not counted correct.", False),
    "wrong":          ("Wrong",          "var(--blocked)", "Different place; still a selection or coverage miss.", False),
    "abstain":        ("Abstain (A·empty)", "var(--faint)", "MapKit returned 0 candidates — no prediction possible.", False),
}
ORDER = ["exact", "alias", "related_credit", "related", "wrong", "abstain"]


def build_photo_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for root, _dirs, files in os.walk(REPO):
        if f"{os.sep}.git" in root:
            continue
        for fn in files:
            if fn.lower().endswith((".jpg", ".jpeg", ".png")):
                idx.setdefault(fn, os.path.join(root, fn))
    return idx


def thumb_data_uri(path: str, px: int, quality: int = 88) -> str | None:
    """Embed a display thumbnail. Default ~320px / q88 — small enough for a
    local HTML gallery, sharp enough to read signs (old default 180/q72 was muddy)."""
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            # Keep long edge at `px` without forcing a tiny square crop.
            resample = getattr(Image, "Resampling", Image).LANCZOS
            im.thumbnail((px, px), resample)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def extract_head_assets(ref: Path) -> tuple[str, str]:
    """Return (<style>…</style>, theme-toggle <script>…</script>) from ref HTML."""
    if not ref.is_file():
        return ("", "")
    s = ref.read_text(encoding="utf-8")
    style = re.search(r"<style[^>]*>[\s\S]*?</style>", s)
    # the small theme-toggle script (no data: payloads)
    script = ""
    for m in re.finditer(r"<script[^>]*>([\s\S]*?)</script>", s):
        if "data-theme" in m.group(1) or "themeBtn" in m.group(1):
            script = m.group(0)
            break
    return (style.group(0) if style else "", script)


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_wrong_ad(case: dict, cand_names: list[str]) -> tuple[str, str]:
    """Map a non-canonical prediction to A–D-ish bucket for the gallery badge.

    A–D was defined on *retrieval* in the original diagnostic (GT location in the
    candidate list). Selection failures where GT is already in top-K are labeled
    separately — they are not A–D coverage classes.
    """
    pred = (case.get("prediction") or "").strip()
    gt = (case.get("gt") or "").strip()
    if not pred:
        return ("A · empty", "No prediction / no candidates to pick from.")
    names = cand_names or []
    ng, norms = _norm_name(gt), [_norm_name(n) for n in names]
    top5 = norms[:5]
    if not names:
        return ("A · empty", "MapKit returned no candidates (same class as abstain).")
    if ng and ng in top5:
        return ("Selection · GT in top5", "Not A–D: GT was retrieved; selector/VLM missed.")
    if ng and ng in norms:
        rank = norms.index(ng) + 1
        return (f"Selection · GT rank {rank}", "Not A–D: GT in list beyond top5 (K experiment).")
    # name-ish presence
    for n in norms:
        if ng and n and min(len(ng), len(n)) >= 5 and (ng in n or n in ng):
            return ("C · near-alias", "Name variant / partial match in list; not exact GT string.")
    # Only one generic amenity vs park-like GT → often D/off-list or B grain
    return ("B/C/D · retrieval", "GT string not in top-20 list (container grain, off-radius, or missing node).")


def load_candidate_names() -> dict[tuple[str, str], list[str]]:
    """Best-effort map (dataset, photo) → candidate names from active snapshot."""
    try:
        import sys
        tools = str(REPO / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import match_score as ms  # type: ignore
        import run_algorithm as ra  # type: ignore

        cfg = ms.load_config()
        rows = ms.read_rows()
        cands = ms.load_candidates([ms.active_mapkit_candidate_file()])
        cases = ra.build_cases(
            rows, cfg, cands, "all", ["nearby_candidates"], 20
        )
        out: dict[tuple[str, str], list[str]] = {}
        for c in cases:
            names = [
                (x.get("name") or "")
                for x in (c["input"].get("nearby_candidates") or [])
            ]
            out[(c["_dataset"], c["_photo"])] = names
        return out
    except Exception:
        return {}


def render(run_path: Path, out_path: Path, thumb_px: int) -> None:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    cases = run["cases"]
    metrics = run.get("metrics", {})
    n = len(cases)
    strict = sum(1 for c in cases if c.get("correct"))
    canon = sum(1 for c in cases if c.get("correct_canonical"))
    acc_strict = round(100 * strict / n) if n else 0
    acc_canon = round(100 * canon / n) if n else 0
    params = run.get("params")
    params = params if isinstance(params, dict) else {}
    snapshot = params.get("snapshot") or metrics.get("snapshot") or "active snapshot"
    run_name = run.get("name", run_path.stem)
    # Friendlier display title (internal run names like loop70 were goal milestones)
    display_title = "Selector pass vs baseline diagnostic"
    if "loop70" in (run_name or "").lower() or "norestroom" in (run_name or "").lower():
        display_title = "Selector pass (post restroom-credit removal)"

    groups: dict[str, list] = {k: [] for k in ORDER}
    for c in cases:
        groups.setdefault(c.get("match_kind", "wrong"), []).append(c)

    photo_idx = build_photo_index()
    cand_map = load_candidate_names()

    style, script = extract_head_assets(REF_HTML)

    # supplementary CSS (uses the reused palette vars) for the galleries + bar
    extra_css = """
<style>
.dist{display:flex;height:14px;border-radius:999px;overflow:hidden;border:1px solid var(--line);margin:6px 0 10px}
.dist i{display:block;height:100%}
.dist-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--dim)}
.dist-legend span{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap}
.dist-legend .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
.dist-legend .dim{color:var(--faint);font-weight:500;font-size:11.5px}
.stack-gap{height:14px}
.rtab{width:100%;border-collapse:collapse;margin-top:12px;font-size:13.5px}
.rtab th,.rtab td{padding:8px 10px;border-bottom:1px solid var(--line2);text-align:left}
.rtab th{color:var(--dim);font-weight:650;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em}
.rtab td.n{text-align:right;font-variant-numeric:tabular-nums}
.rtab tr.sum td{border-top:2px solid var(--line);font-weight:750}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 20px 22px;box-shadow:var(--shadow);margin:16px 0}
.sec-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px}
.sec-head h2{margin:0;font-size:19px;letter-spacing:-.01em}
.sec-badge{font-variant-numeric:tabular-nums;font-weight:800;font-size:15px;padding:3px 11px;border-radius:999px;color:#fff}
.sec-desc{color:var(--dim);font-size:13.5px;margin:2px 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg)}
.card img{display:block;width:100%;height:148px;object-fit:cover;background:var(--line2)}
.card .cap{padding:8px 9px 10px;font-size:12px;line-height:1.4}
.card .gt{font-weight:700;color:var(--ink)}
.card .pr{color:var(--dim);margin-top:2px}
.card .pr.bad{color:var(--blocked)}
.card .mk{display:inline-block;margin-top:6px;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:999px;color:#fff}
.card .ad{display:inline-block;margin-top:5px;margin-right:4px;font-size:10px;font-weight:750;padding:1px 7px;border-radius:999px;background:var(--line2);color:var(--dim)}
.card .ad.sel{background:color-mix(in srgb, var(--k) 22%, transparent);color:var(--k)}
.card .ad.cov{background:color-mix(in srgb, var(--blocked) 18%, transparent);color:var(--blocked)}
.card .ad.alias{background:color-mix(in srgb, var(--policy) 18%, transparent);color:var(--policy)}
.miss-note{color:var(--faint);font-size:12px;margin-top:10px}
.ad-summary{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:0 0 14px}
.ad-summary .box{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg);font-size:12.5px;color:var(--dim);line-height:1.4}
.ad-summary .box b{color:var(--ink);display:block;margin-bottom:3px;font-size:13px}
.compare{margin:16px 0;background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}
.compare .ch{padding:16px 18px 0}
.compare .ch h2{margin:0 0 6px;font-size:16px}
.compare .ch p{margin:0 0 12px;color:var(--dim);font-size:13.5px;line-height:1.55;max-width:75ch}
.score-table{width:100%;border-collapse:collapse;font-size:13px}
.score-table th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--faint);padding:9px 12px;background:var(--bg);border-bottom:1px solid var(--line)}
.score-table td{padding:9px 12px;border-top:1px solid var(--line2);vertical-align:middle;color:var(--dim)}
.score-table td.n{font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink);white-space:nowrap}
.score-table tr.hl td{background:color-mix(in srgb, var(--now) 8%, transparent)}
.score-table .delta{color:var(--now);font-weight:700;font-size:12px}
.score-foot{padding:8px 14px 14px;font-size:12px;color:var(--faint);line-height:1.45}
</style>
"""

    def tile(label, val, sub, cls=""):
        return (f'<div class="m {cls}"><span class="lab">{esc(label)}</span>'
                f'<div class="val num">{esc(val)}</div><div class="sub">{esc(sub)}</div></div>')

    # distribution bar bands
    bands, legend = [], []
    for k in ORDER:
        cnt = len(groups.get(k, []))
        if not cnt:
            continue
        color = KIND_META[k][1]
        pct = 100 * cnt / n
        bands.append(f'<i style="width:{pct:.3f}%;background:{color}"></i>')
        legend.append(f'<span><i class="dot" style="background:{color}"></i>'
                      f'{esc(KIND_META[k][0])} {cnt}</span>')

    # result table
    rows = []
    for k in ORDER:
        cnt = len(groups.get(k, []))
        if not cnt:
            continue
        credit = "counts as correct" if KIND_META[k][3] else "—"
        rows.append(f'<tr><td>{esc(KIND_META[k][0])}</td><td class="n">{cnt}</td><td>{esc(credit)}</td></tr>')
    rows.append(f'<tr class="sum"><td>canonical correct</td><td class="n">{canon}</td>'
                f'<td>{acc_canon}% (strict {strict} · {acc_strict}%)</td></tr>')

    # galleries
    from collections import Counter
    ad_counts: Counter = Counter()
    sections = []
    for k in ORDER:
        g = groups.get(k, [])
        if not g:
            continue
        label, color, desc, _ = KIND_META[k]
        if k == "wrong":
            desc = (
                "Different place name. Badges map each miss onto the original A–D "
                "retrieval taxonomy (or mark pure selection misses when GT was in-list)."
            )
        cards = []
        ad_local: Counter = Counter()
        for c in g:
            fn = c.get("photo", "")
            uri = (
                thumb_data_uri(photo_idx.get(fn, ""), thumb_px)
                if fn in photo_idx
                else None
            )
            imgtag = (
                f'<img src="{uri}" alt="" loading="lazy">'
                if uri
                else '<img alt="missing" style="height:148px">'
            )
            gt = esc(c.get("gt"))
            pred = esc(c.get("prediction") or "—")
            is_wrong = k in ("wrong", "related")
            pr_cls = " bad" if is_wrong else ""
            pred_line = (
                f'<div class="pr{pr_cls}">→ {pred}</div>'
                if (is_wrong or pred != gt)
                else '<div class="pr">✓ matched</div>'
            )
            ad_html = ""
            if k in ("wrong", "related"):
                names = cand_map.get((c.get("dataset", ""), c.get("photo", "")), [])
                ad_lab, ad_tip = classify_wrong_ad(c, names)
                ad_counts[ad_lab] += 1
                ad_local[ad_lab] += 1
                cls = "sel" if ad_lab.startswith("Selection") else (
                    "alias" if ad_lab.startswith("C") else "cov"
                )
                ad_html = (
                    f'<span class="ad {cls}" title="{esc(ad_tip)}">{esc(ad_lab)}</span>'
                )
            cards.append(
                f'<div class="card">{imgtag}<div class="cap">'
                f'<div class="gt">{gt}</div>{pred_line}'
                f'{ad_html}'
                f'<span class="mk" style="background:{color}">{esc(label)}</span>'
                f"</div></div>"
            )
        ad_boxes = ""
        if k == "wrong" and ad_local:
            bits = []
            for lab, cnt in ad_local.most_common():
                bits.append(
                    f'<div class="box"><b>{esc(lab)} · {cnt}</b>'
                    f"See original case-types A–D: coverage vs selection.</div>"
                )
            ad_boxes = f'<div class="ad-summary">{"".join(bits)}</div>'
        sections.append(
            f'<div class="sec" id="sec-{k}"><div class="sec-head">'
            f"<h2>{esc(label)}</h2>"
            f'<span class="sec-badge" style="background:{color}">{len(g)}</span></div>'
            f'<p class="sec-desc">{esc(desc)}</p>'
            f"{ad_boxes}"
            f'<div class="grid">{"".join(cards)}</div></div>'
        )

    # deltas vs nearest rescored baseline (70 canonical / 42%) for the score strip
    base_canon, base_strict = 70, 63
    d_cases = canon - base_canon
    d_pp = acc_canon - 42
    rel = round(100 * d_cases / base_canon) if base_canon else 0

    body = f"""
<div class="wrap">
  <div class="toolbar"><div class="meta"><b>MapKit · selector vs baseline</b>
    · run <code>{esc(run_name)}</code> · snapshot <code>{esc(snapshot)}</code> · eligible {n}</div>
    <button class="theme-btn" id="themeBtn">Theme</button></div>

  <header class="hero">
    <p class="eyebrow">Result report · same 166 as the baseline diagnostic</p>
    <h1>{esc(display_title)}</h1>
    <p class="lede">Same eligible photos as the original case-types page. Scoring is
      dual-metric: <b>strict</b> = exact GT string; <b>canonical</b> = exact ∪
      accepted alias ∪ related_credit (restroom/washroom amenities are <b>not</b>
      credited). The run name may say “loop70” only because that was the
      <b>internal milestone label</b> while chasing ≥70% canonical — not a product
      algorithm brand.</p>

    <div class="metrics">
      {tile("Eligible", n, "photos scored", "total")}
      {tile("Canonical correct", canon, f"{acc_canon}% · exact ∪ alias ∪ related_credit", "ok")}
      {tile("Strict exact", strict, f"{acc_strict}% · exact name only", "")}
      {tile("Abstain", len(groups.get("abstain", [])), "no candidate (A·empty)", "miss")}
    </div>

    <div class="stack-wrap">
      <div class="stack-lab"><span>Where the {n} land (baseline diagnostic)</span>
        <span class="num">100 · 16 · 50</span></div>
      <div class="dist" title="From the original poi-case-types.html">
        <i style="width:60.241%;background:#5a8f7b"></i>
        <i style="width:9.639%;background:#c4a574"></i>
        <i style="width:30.120%;background:#9aa7b5"></i>
      </div>
      <div class="dist-legend">
        <span><i class="dot" style="background:#5a8f7b"></i>GT in top5 · 100
          <span class="dim">(nearest exact 63 of these)</span></span>
        <span><i class="dot" style="background:#c4a574"></i>GT rank 6–50 · 16</span>
        <span><i class="dot" style="background:#9aa7b5"></i>GT not in list · 50</span>
      </div>
      <div class="stack-gap"></div>
      <div class="stack-lab"><span>Where the {n} land (this selector)</span>
        <span class="num">strict {strict} · canonical {canon}</span></div>
      <div class="dist">{"".join(bands)}</div>
      <div class="dist-legend">{"".join(legend)}</div>
    </div>
  </header>

  <section class="compare">
    <div class="ch">
      <h2>Before vs after (scores)</h2>
      <p>Nearest = distance rank-1. Later stages add OCR/access demote, list_fit,
        cascade VLM, then structure refine. Labels frozen after restroom/washroom
        credit removal.</p>
    </div>
    <table class="score-table">
      <thead><tr><th>Stage</th><th>Strict</th><th>Canonical</th><th>Δ canon vs nearest</th></tr></thead>
      <tbody>
        <tr><td>Nearest (rescored)</td><td class="n">63 · 38%</td><td class="n">70 · 42%</td><td class="n">baseline</td></tr>
        <tr class="hl"><td><b>This run</b></td>
          <td class="n">{strict} · {acc_strict}%</td>
          <td class="n">{canon} · {acc_canon}%</td>
          <td class="n delta">+{d_cases} · +{d_pp}pp · +{rel}% rel</td></tr>
      </tbody>
    </table>
    <p class="score-foot"><b>pp</b> = percentage points on the 166-set ·
      <b>rel</b> = relative lift on canonical correct counts vs 70.</p>
  </section>

  <div class="result-block">
    <div class="rh"><h2>Result · by match kind</h2>
      <span class="note">{esc(run_name)} · {esc(snapshot)}</span></div>
    <table class="rtab"><thead><tr><th>Match kind</th><th class="n">n</th><th>Scoring</th></tr></thead>
      <tbody>{"".join(rows)}</tbody></table>
  </div>

  {"".join(sections)}
</div>
"""

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POI case types — {esc(run_name)}</title>
{style}
{extra_css}
</head><body>
{body}
{script}
</body></html>"""

    out_path.write_text(doc, encoding="utf-8")
    size_kb = out_path.stat().st_size // 1024
    print(f"wrote {out_path} ({size_kb} KB) — {n} cases, "
          f"strict {strict}/{acc_strict}%, canonical {canon}/{acc_canon}%")


def main() -> int:
    ap = argparse.ArgumentParser(description="Render run results as case-types HTML")
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--thumb-px",
        type=int,
        default=360,
        help="Long-edge thumbnail size in pixels (default 360; was 180 and looked soft)",
    )
    args = ap.parse_args()
    if not args.run.is_file():
        ap.error(f"run not found: {args.run}")
    render(args.run, args.out, args.thumb_px)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
