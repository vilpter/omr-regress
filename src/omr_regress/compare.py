"""Compare two runs of the same test set, input by input and measure by measure.

For each input the exports are first compared as text (apart from the encoding date
and software version): equal exports are *identical*. Otherwise each staff of run A is
paired with the staff of run B in the same position, the two staves' measures are
aligned, and every pair of measures that differ is a *change*.

When the input has a reference, both runs are scored against it (the share of the
reference's staff measures read exactly, and precision and recall of its notes), and
each change is judged: *fixed* when B now reads the measure as the reference does,
*broken* when A did and B no longer does, *changed* otherwise. An input is *better*
or *worse* when both scores move the same way, *mixed* when they disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from omr_regress.align import Pair, align
from omr_regress.book import Box, measure_boxes, read_book
from omr_regress.inputs import Run, find_reference
from omr_regress.measures import Staff, StaffMeasure, staff_measures, staves
from omr_regress.musicxml import MusicXmlError, Score, normalized_text, read_movements

# Order in which inputs are listed: what needs a look first.
VERDICTS = [
    "worse",
    "failed",
    "mixed",
    "changed",
    "better",
    "recovered",
    "same",
    "identical",
    "no export",
]


@dataclass
class Metrics:
    parts: int
    staves: int
    measures: int
    exact: float | None = None  # share of the reference's staff measures read exactly
    precision: float | None = None  # of the notes, against the reference
    recall: float | None = None

    @property
    def f1(self) -> float | None:
        if self.precision is None or self.recall is None:
            return None
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)


@dataclass
class Change:
    staff: int  # position of the staff, from 0
    label: str
    a: int | None  # measure index in A, None for a measure only B has
    b: int | None
    a_measure: StaffMeasure | None
    b_measure: StaffMeasure | None
    reference: StaffMeasure | None = None
    verdict: str = "changed"  # fixed, broken, changed, voices


@dataclass
class InputResult:
    id: str
    status_a: str
    status_b: str
    verdict: str = "identical"
    metrics_a: Metrics | None = None
    metrics_b: Metrics | None = None
    has_reference: bool = False
    parts_a: list[str] = field(default_factory=list)
    parts_b: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    staves_only_a: list[str] = field(default_factory=list)
    staves_only_b: list[str] = field(default_factory=list)
    error: str | None = None
    # Per side ("a", "b"): the book, and for each staff which measures the reader added
    # for a multi-measure rest. Page boxes are read from the book when first asked for.
    layouts: dict[str, tuple[Path | None, list[list[bool]]]] = field(default_factory=dict)
    _boxes: dict[str, list[list[Box | None]]] = field(default_factory=dict, repr=False)

    def box(self, side: str, staff: int, index: int) -> Box | None:
        """Where measure ``index`` of ``staff`` is on the page, in run ``side``'s book."""
        if side not in self._boxes:
            path, added = self.layouts.get(side, (None, []))
            book = read_book(path) if path else None
            self._boxes[side] = [measure_boxes(book, a) if book else [] for a in added]
        boxes = self._boxes[side]
        if staff < len(boxes) and index < len(boxes[staff]):
            return boxes[staff][index]
        return None

    @property
    def fixed(self) -> int:
        return sum(c.verdict == "fixed" for c in self.changes)

    @property
    def broken(self) -> int:
        return sum(c.verdict == "broken" for c in self.changes)


@dataclass
class Comparison:
    run_a: Run
    run_b: Run
    results: list[InputResult]

    def count(self, verdict: str) -> int:
        return sum(r.verdict == verdict for r in self.results)


def _part_names(score: Score) -> list[str]:
    return [p.name or p.abbreviation or p.id for p in score.parts]


def _metrics(
    score: Score, measures: list[list[StaffMeasure]], ref: list[list[StaffMeasure]] | None
) -> Metrics:
    m = Metrics(len(score.parts), score.staff_count, score.measure_count)
    if ref is None:
        return m
    exact = total = 0
    matched = 0
    ref_notes = sum(sum(x.pitched.values()) for staff in ref for x in staff)
    run_notes = sum(sum(x.pitched.values()) for staff in measures for x in staff)
    for k, ref_staff in enumerate(ref):
        total += len(ref_staff)
        if k >= len(measures):
            continue
        for i, j in align(ref_staff, measures[k]):
            if i is None or j is None:
                continue
            r, x = ref_staff[i], measures[k][j]
            exact += r == x
            matched += sum((r.pitched & x.pitched).values())
    m.exact = exact / total if total else None
    m.precision = matched / run_notes if run_notes else (1.0 if not ref_notes else 0.0)
    m.recall = matched / ref_notes if ref_notes else 1.0
    return m


def _reference_index(pairs: list[Pair]) -> dict[int, int]:
    """Run measure index -> reference measure index, from an alignment of the two."""
    return {j: i for i, j in pairs if i is not None and j is not None}


def _layout(
    run: Run, input_id: str, score: Score, layout: list[Staff]
) -> tuple[Path | None, list[list[bool]]]:
    added = [[m.added for m in score.parts[s.part].measures] for s in layout]
    return run.book(input_id), added


def _judge(a: Metrics, b: Metrics) -> str:
    da = (b.exact or 0) - (a.exact or 0)
    df = (b.f1 or 0) - (a.f1 or 0)
    eps = 1e-9
    if da > eps and df > -eps or df > eps and da > -eps:
        return "better"
    if da < -eps and df < eps or df < -eps and da < eps:
        return "worse"
    if abs(da) > eps or abs(df) > eps:
        return "mixed"
    return "changed"


def compare_input(
    run_a: Run, run_b: Run, input_id: str, references=None, inputs=None
) -> InputResult:
    status_a = run_a.status(input_id).get("status", "missing")
    status_b = run_b.status(input_id).get("status", "missing")
    result = InputResult(input_id, status_a, status_b)
    files_a, files_b = run_a.exports(input_id), run_b.exports(input_id)
    if not files_a and not files_b:
        result.verdict = "no export"
        return result
    if files_a and not files_b:
        result.verdict = "failed"
        return result
    if files_b and not files_a:
        result.verdict = "recovered"
        return result
    if [p.name for p in files_a] == [p.name for p in files_b] and all(
        normalized_text(x) == normalized_text(y) for x, y in zip(files_a, files_b)
    ):
        result.verdict = "identical"
        return result
    try:
        score_a, score_b = read_movements(files_a), read_movements(files_b)
        ref_files = find_reference(input_id, inputs or run_b.inputs or run_a.inputs, references)
        score_ref = read_movements(ref_files) if ref_files else None
    except MusicXmlError as exc:
        result.verdict = "changed"
        result.error = str(exc)
        return result
    layout_a, layout_b = staves(score_a), staves(score_b)
    ma, mb = staff_measures(score_a), staff_measures(score_b)
    mref = staff_measures(score_ref) if score_ref is not None else None
    result.has_reference = mref is not None
    result.parts_a, result.parts_b = _part_names(score_a), _part_names(score_b)
    result.metrics_a = _metrics(score_a, ma, mref)
    result.metrics_b = _metrics(score_b, mb, mref)
    result.staves_only_a = [s.label for s in layout_a[len(layout_b) :]]
    result.staves_only_b = [s.label for s in layout_b[len(layout_a) :]]
    for k in range(min(len(ma), len(mb))):
        ref_a = ref_b = {}
        if mref is not None and k < len(mref):
            ref_a = _reference_index(align(mref[k], ma[k]))
            ref_b = _reference_index(align(mref[k], mb[k]))
        for i, j in align(ma[k], mb[k]):
            x = ma[k][i] if i is not None else None
            y = mb[k][j] if j is not None else None
            if x is not None and y is not None and x == y:
                if not x.same_voices(y):
                    result.changes.append(
                        Change(k, layout_b[k].label, i, j, x, y, verdict="voices")
                    )
                continue
            change = Change(k, layout_b[k].label, i, j, x, y)
            if mref is not None and k < len(mref):
                ri = ref_b.get(j) if j is not None else None
                if ri is None and i is not None:
                    ri = ref_a.get(i)
                change.reference = mref[k][ri] if ri is not None else None
                a_ok = i is not None and i in ref_a and mref[k][ref_a[i]] == x
                b_ok = j is not None and j in ref_b and mref[k][ref_b[j]] == y
                change.verdict = (
                    "fixed" if b_ok and not a_ok else "broken" if a_ok and not b_ok else "changed"
                )
            result.changes.append(change)
    if not (result.changes or result.staves_only_a or result.staves_only_b):
        result.verdict = "same"  # the exports differ in what is not compared (text, layout)
    elif result.has_reference:
        result.verdict = _judge(result.metrics_a, result.metrics_b)
    else:
        result.verdict = "changed"
    result.layouts = {
        "a": _layout(run_a, input_id, score_a, layout_a),
        "b": _layout(run_b, input_id, score_b, layout_b),
    }
    return result


def compare_runs(
    run_a: Run, run_b: Run, ids: list[str] | None = None, references=None, inputs=None
) -> Comparison:
    if ids is None:
        ids = sorted(set(run_a.ids()) & set(run_b.ids()))
    results = [compare_input(run_a, run_b, i, references, inputs) for i in ids]
    results.sort(key=lambda r: (VERDICTS.index(r.verdict), -r.broken, r.id))
    return Comparison(run_a, run_b, results)
