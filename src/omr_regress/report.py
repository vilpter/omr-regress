"""Reports of a comparison: a text summary, a JSON file, and an HTML page that shows each
changed measure as the page has it, next to how each run (and the reference) reads it."""

from __future__ import annotations

import difflib
import html
import json
from pathlib import Path

from omr_regress.book import Box, read_book
from omr_regress.compare import Change, Comparison, InputResult, Metrics
from omr_regress.measures import StaffMeasure, tokens


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def _arrow(a, b, fmt=str) -> str:
    fa, fb = ("-" if a is None else fmt(a)), ("-" if b is None else fmt(b))
    return fa if fa == fb else f"{fa} -> {fb}"


def _metric(r: InputResult, name: str, fmt=str) -> str:
    a = getattr(r.metrics_a, name) if r.metrics_a else None
    b = getattr(r.metrics_b, name) if r.metrics_b else None
    return _arrow(a, b, fmt)


def summary_lines(c: Comparison) -> list[str]:
    counts = {v: c.count(v) for v in dict.fromkeys(r.verdict for r in c.results)}
    lines = [
        f"A: {c.run_a.label}  B: {c.run_b.label}",
        f"{len(c.results)} inputs: " + ", ".join(f"{n} {v}" for v, n in counts.items()),
    ]
    for r in c.results:
        if r.verdict in ("identical", "same"):
            continue
        line = f"  {r.verdict:9s} {r.id}"
        if r.verdict in ("failed", "recovered", "no export"):
            line += f"  (A {r.status_a}, B {r.status_b})"
        elif r.metrics_a and r.metrics_b:
            line += f"  parts {_metric(r, 'parts')}  measures {_metric(r, 'measures')}"
            if r.has_reference:
                line += f"  exact {_metric(r, 'exact', _pct)}  notes F1 {_metric(r, 'f1', _pct)}"
            kinds = [c.verdict for c in r.changes]
            line += "  changed measures " + str(sum(k != "voices" for k in kinds))
            if r.has_reference:
                line += f" (fixed {kinds.count('fixed')}, broken {kinds.count('broken')})"
        lines.append(line)
    return lines


def _metrics_json(m: Metrics | None) -> dict | None:
    if m is None:
        return None
    return {
        "parts": m.parts,
        "staves": m.staves,
        "measures": m.measures,
        "exact": m.exact,
        "precision": m.precision,
        "recall": m.recall,
        "f1": m.f1,
    }


def write_json(c: Comparison, path: Path) -> None:
    data = {
        "a": {"label": c.run_a.label, "folder": str(c.run_a.folder)},
        "b": {"label": c.run_b.label, "folder": str(c.run_b.folder)},
        "inputs": [
            {
                "id": r.id,
                "verdict": r.verdict,
                "status": [r.status_a, r.status_b],
                "reference": r.has_reference,
                "a": _metrics_json(r.metrics_a),
                "b": _metrics_json(r.metrics_b),
                "parts": [r.parts_a, r.parts_b],
                "changes": [
                    {
                        "staff": ch.label,
                        "a": ch.a_measure.number if ch.a_measure else None,
                        "b": ch.b_measure.number if ch.b_measure else None,
                        "verdict": ch.verdict,
                    }
                    for ch in r.changes
                ],
                "error": r.error,
            }
            for r in c.results
        ],
    }
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


# --- HTML --------------------------------------------------------------------------

STYLE = """
:root { --fg: #1d1d1f; --bg: #fff; --muted: #6e6e73; --line: #d2d2d7; --soft: #f5f5f7;
  --bad: #b3261e; --bad-bg: #fde7e4; --good: #1b6e2f; --good-bg: #e2f4e6; --mid: #8a5a00;
  --mid-bg: #fdf0d5; --mark: #fff2a8; }
@media (prefers-color-scheme: dark) { :root { --fg: #f5f5f7; --bg: #1c1c1e; --muted: #a1a1a6;
  --line: #3a3a3c; --soft: #2c2c2e; --bad: #ff8a80; --bad-bg: #4a1f1c; --good: #8fe0a0;
  --good-bg: #1d3b24; --mid: #ffd27a; --mid-bg: #45361a; --mark: #5c4f00; } }
body { font: 14px/1.45 system-ui, sans-serif; color: var(--fg); background: var(--bg);
  margin: 0 auto; padding: 16px; max-width: 1100px; }
h1 { font-size: 20px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 32px 0 6px; }
.muted { color: var(--muted); } a { color: inherit; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; background: var(--soft); }
.v { display: inline-block; padding: 0 6px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.worse, .failed, .broken { color: var(--bad); background: var(--bad-bg); }
.better, .recovered, .fixed { color: var(--good); background: var(--good-bg); }
.mixed, .changed, .voices { color: var(--mid); background: var(--mid-bg); }
.block { border: 1px solid var(--line); border-radius: 6px; margin: 10px 0; padding: 8px; }
.crop { display: block; max-width: 100%; height: auto; background: #fff; margin-bottom: 6px; }
.reading { font: 12.5px/1.5 ui-monospace, Consolas, monospace; white-space: pre-wrap; margin: 2px 0; }
.reading b { display: inline-block; width: 7em; font-weight: 600; color: var(--muted); }
.reading mark { background: var(--mark); color: inherit; }
nav button { font: inherit; margin: 0 4px 8px 0; padding: 2px 10px; border: 1px solid var(--line);
  border-radius: 4px; background: var(--soft); color: var(--fg); cursor: pointer; }
nav button.on { border-color: var(--fg); }
@media (max-width: 640px) { .reading b { display: block; } }
"""

SCRIPT = """
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  const show = b.dataset.show;
  document.querySelectorAll('[data-verdict]').forEach(el => {
    el.hidden = show !== 'all' && !show.split(' ').includes(el.dataset.verdict);
  });
}));
"""


def _e(text: object) -> str:
    return html.escape(str(text))


class _Images:
    """Sheet images extracted next to the report, once each."""

    def __init__(self, folder: Path, prefix: str) -> None:
        self.folder = folder
        self.prefix = prefix
        self.done: dict[tuple[str, int], tuple[str, int, int] | None] = {}

    def get(self, book_path: Path | None, sheet: int) -> tuple[str, int, int] | None:
        if book_path is None:
            return None
        key = (str(book_path), sheet)
        if key not in self.done:
            self.done[key] = None
            book = read_book(book_path)
            data = book.image(sheet) if book else None
            info = next((s for s in book.sheets if s.number == sheet), None) if book else None
            if data and info:
                self.folder.mkdir(parents=True, exist_ok=True)
                name = f"{len(self.done)}.png"
                (self.folder / name).write_bytes(data)
                self.done[key] = (f"{self.prefix}/{name}", info.width, info.height)
        return self.done[key]


def _crop(images: _Images, book_path: Path | None, box: Box) -> str:
    image = images.get(book_path, box.sheet)
    if image is None:
        return ""
    src, width, height = image
    mx, my = 40, max(40.0, 0.12 * box.h)
    x, y = max(0.0, box.x - mx), max(0.0, box.y - my)
    w, h = min(width - x, box.w + 2 * mx), min(height - y, box.h + 2 * my)
    scale = min(0.6, 1000 / max(w, 1))
    return (
        f'<svg class="crop" viewBox="{x:.0f} {y:.0f} {w:.0f} {h:.0f}" '
        f'width="{w * scale:.0f}" height="{h * scale:.0f}" role="img" '
        f'aria-label="page {box.sheet}, measure on the page">'
        f'<image href="{_e(src)}" width="{width}" height="{height}"/></svg>'
    )


def _marked(words: list[str], other: list[str]) -> str:
    """The words, those not in the other reading marked."""
    out = []
    matcher = difflib.SequenceMatcher(a=other, b=words, autojunk=False)
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        chunk = " ".join(_e(w) for w in words[j1:j2])
        if not chunk:
            continue
        out.append(chunk if tag == "equal" else f"<mark>{chunk}</mark>")
    return " ".join(out) or '<span class="muted">(empty)</span>'


def _reading(label: str, m: StaffMeasure | None, other: StaffMeasure | None) -> str:
    if m is None:
        body = '<span class="muted">no measure</span>'
    elif other is None:
        body = " ".join(_e(w) for w in tokens(m)) or '<span class="muted">(empty)</span>'
    else:
        body = _marked(tokens(m), tokens(other))
    return f'<div class="reading"><b>{_e(label)}</b>{body}</div>'


def _block(r: InputResult, group: list[Change], images: _Images, c: Comparison) -> str:
    first = group[0]
    crop = ""
    if first.b is not None and (box := r.box("b", first.staff, first.b)) is not None:
        crop = _crop(images, c.run_b.book(r.id), box)
    elif first.a is not None and (box := r.box("a", first.staff, first.a)) is not None:
        crop = _crop(images, c.run_a.book(r.id), box)
    number = first.b_measure.number if first.b_measure else first.a_measure.number
    parts = [f'<div class="block"><div>Measure {_e(number)}</div>{crop}']
    for ch in group:
        parts.append(f'<div><span class="v {ch.verdict}">{ch.verdict}</span> {_e(ch.label)}</div>')
        if r.has_reference:
            # Mark what each run reads differently from the reference
            parts.append(_reading("reference", ch.reference, ch.reference))
            parts.append(_reading(f"A ({c.run_a.label})", ch.a_measure, ch.reference))
            parts.append(_reading(f"B ({c.run_b.label})", ch.b_measure, ch.reference))
        else:
            parts.append(_reading(f"A ({c.run_a.label})", ch.a_measure, ch.b_measure))
            parts.append(_reading(f"B ({c.run_b.label})", ch.b_measure, ch.a_measure))
    parts.append("</div>")
    return "".join(parts)


def _section(r: InputResult, images: _Images, c: Comparison, limit: int) -> str:
    out = [
        f'<section id="{_e(r.id)}" data-verdict="{r.verdict}">',
        f'<h2><span class="v {r.verdict}">{r.verdict}</span> {_e(r.id)}</h2>',
    ]
    if r.verdict in ("failed", "recovered", "no export"):
        out.append(f"<p>A: {_e(r.status_a)}, B: {_e(r.status_b)}</p></section>")
        return "".join(out)
    if r.error:
        out.append(f"<p>{_e(r.error)}</p>")
    if r.parts_a != r.parts_b:
        out.append(
            f"<p>Parts in A: {_e(', '.join(r.parts_a))}<br>Parts in B: {_e(', '.join(r.parts_b))}</p>"
        )
    if r.staves_only_a:
        out.append(f"<p>Staves only A has: {_e(', '.join(r.staves_only_a))}</p>")
    if r.staves_only_b:
        out.append(f"<p>Staves only B has: {_e(', '.join(r.staves_only_b))}</p>")
    groups: dict[tuple, list[Change]] = {}
    for ch in r.changes:
        key = ("b", ch.b) if ch.b is not None else ("a", ch.a)
        groups.setdefault(key, []).append(ch)
    ordered = sorted(groups.values(), key=lambda g: g[0].b if g[0].b is not None else g[0].a or 0)
    for group in ordered[:limit]:
        out.append(_block(r, group, images, c))
    if len(ordered) > limit:
        out.append(f'<p class="muted">{len(ordered) - limit} more changed measures not shown.</p>')
    out.append("</section>")
    return "".join(out)


def write_html(c: Comparison, path: Path, limit: int = 40) -> None:
    folder = path.with_name(path.stem + "_files")
    images = _Images(folder, folder.name)
    counts = {v: c.count(v) for v in dict.fromkeys(r.verdict for r in c.results)}
    rows = []
    for r in c.results:
        if r.verdict == "identical":
            continue
        ref = r.has_reference
        rows.append(
            f'<tr data-verdict="{r.verdict}"><td><a href="#{_e(r.id)}">{_e(r.id)}</a></td>'
            f'<td><span class="v {r.verdict}">{r.verdict}</span></td>'
            f"<td>{_e(_metric(r, 'parts'))}</td><td>{_e(_metric(r, 'measures'))}</td>"
            f"<td>{_e(_metric(r, 'exact', _pct)) if ref else '-'}</td>"
            f"<td>{_e(_metric(r, 'f1', _pct)) if ref else '-'}</td>"
            f"<td>{sum(ch.verdict != 'voices' for ch in r.changes)}</td>"
            f"<td>{r.fixed if ref else '-'}</td><td>{r.broken if ref else '-'}</td></tr>"
        )
    sections = [_section(r, images, c, limit) for r in c.results if r.verdict != "identical"]
    filters = [
        ("all", "All"),
        ("worse failed mixed", "Worse"),
        ("better recovered", "Better"),
        ("changed same", "Changed"),
    ]
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OMR regression report</title><style>{STYLE}</style></head><body>
<h1>{_e(c.run_a.label)} &rarr; {_e(c.run_b.label)}</h1>
<p class="muted">{len(c.results)} inputs: {_e(", ".join(f"{n} {v}" for v, n in counts.items()))}.
Exact: share of the reference's staff measures read exactly. Highlighted: what a run reads
differently from the reference (from the other run when there is no reference).</p>
<nav>{"".join(f'<button data-show="{s}"{" class=on" if s == "all" else ""}>{t}</button>' for s, t in filters)}</nav>
<table><thead><tr><th>Input</th><th>Verdict</th><th>Parts</th><th>Measures</th><th>Exact</th>
<th>Notes F1</th><th>Changed</th><th>Fixed</th><th>Broken</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
{"".join(sections)}
<script>{SCRIPT}</script></body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
