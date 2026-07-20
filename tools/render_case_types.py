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


def thumb_data_uri(path: str, px: int) -> str | None:
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72, optimize=True)
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

    groups: dict[str, list] = {k: [] for k in ORDER}
    for c in cases:
        groups.setdefault(c.get("match_kind", "wrong"), []).append(c)

    photo_idx = build_photo_index()

    style, script = extract_head_assets(REF_HTML)

    # supplementary CSS (uses the reused palette vars) for the galleries + bar
    extra_css = """
<style>
.dist{display:flex;height:16px;border-radius:999px;overflow:hidden;border:1px solid var(--line);margin:6px 0 10px}
.dist i{display:block;height:100%}
.dist-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--dim)}
.dist-legend span{display:inline-flex;align-items:center;gap:7px}
.dist-legend .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
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
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg)}
.card img{display:block;width:100%;height:118px;object-fit:cover;background:var(--line2)}
.card .cap{padding:8px 9px 10px;font-size:12px;line-height:1.4}
.card .gt{font-weight:700;color:var(--ink)}
.card .pr{color:var(--dim);margin-top:2px}
.card .pr.bad{color:var(--blocked)}
.card .mk{display:inline-block;margin-top:6px;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:999px;color:#fff}
.miss-note{color:var(--faint);font-size:12px;margin-top:10px}
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
    sections = []
    for k in ORDER:
        g = groups.get(k, [])
        if not g:
            continue
        label, color, desc, _ = KIND_META[k]
        cards = []
        for c in g:
            fn = c.get("photo", "")
            uri = thumb_data_uri(photo_idx.get(fn, ""), thumb_px) if fn in photo_idx else None
            imgtag = (f'<img src="{uri}" alt="" loading="lazy">' if uri
                      else '<img alt="missing" style="height:118px">')
            gt = esc(c.get("gt"))
            pred = esc(c.get("prediction") or "—")
            is_wrong = k in ("wrong", "related")
            pr_cls = " bad" if is_wrong else ""
            pred_line = (f'<div class="pr{pr_cls}">→ {pred}</div>'
                         if (is_wrong or pred != gt) else '<div class="pr">✓ matched</div>')
            cards.append(
                f'<div class="card">{imgtag}<div class="cap">'
                f'<div class="gt">{gt}</div>{pred_line}'
                f'<span class="mk" style="background:{color}">{esc(label)}</span>'
                f'</div></div>')
        sections.append(
            f'<div class="sec"><div class="sec-head">'
            f'<h2>{esc(label)}</h2>'
            f'<span class="sec-badge" style="background:{color}">{len(g)}</span></div>'
            f'<p class="sec-desc">{esc(desc)}</p>'
            f'<div class="grid">{"".join(cards)}</div></div>')

    body = f"""
<div class="wrap">
  <div class="toolbar"><div class="meta"><b>MapKit · Bloggo · selector loop</b>
    · run <code>{esc(run_name)}</code> · snapshot <code>{esc(snapshot)}</code> · eligible {n}</div>
    <button class="theme-btn" id="themeBtn">Theme</button></div>

  <header class="hero">
    <p class="eyebrow">Selector loop · result</p>
    <h1>New algorithm — {n} photos by match type</h1>
    <p class="lede">Same eligible set as the baseline diagnostic, scored with the
      loop70 selector. A photo can be an <b>exact</b> name match, an <b>alias</b>
      of the same place, a <b>related</b> sub-POI given policy credit, plain
      <b>wrong</b>, or an <b>abstain</b> where MapKit returned nothing.</p>

    <div class="metrics">
      {tile("Eligible", n, "photos scored", "total")}
      {tile("Canonical correct", canon, f"{acc_canon}% · exact ∪ alias ∪ related", "ok")}
      {tile("Strict exact", strict, f"{acc_strict}% · exact name only", "")}
      {tile("Abstain", len(groups.get("abstain", [])), "no candidate (A·empty)", "miss")}
    </div>

    <div class="stack-wrap">
      <div class="stack-lab"><span>Where the {n} land</span>
        <span class="num">strict {strict} · canonical {canon}</span></div>
      <div class="dist">{"".join(bands)}</div>
      <div class="dist-legend">{"".join(legend)}</div>
    </div>
  </header>

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
    ap.add_argument("--thumb-px", type=int, default=180)
    args = ap.parse_args()
    if not args.run.is_file():
        ap.error(f"run not found: {args.run}")
    render(args.run, args.out, args.thumb_px)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
