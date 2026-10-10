from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import attributes, make_run, note, score, write_mxl  # noqa: E402

from omr_regress.align import align  # noqa: E402
from omr_regress.book import measure_boxes, read_book  # noqa: E402
from omr_regress.cli import main  # noqa: E402
from omr_regress.compare import compare_input, compare_runs  # noqa: E402
from omr_regress.inputs import find_inputs, find_reference, open_run  # noqa: E402
from omr_regress.measures import duration_text, staff_measures, staves, tokens  # noqa: E402
from omr_regress.musicxml import normalized_text, read_movements, read_score  # noqa: E402
from omr_regress.report import write_html  # noqa: E402

# Two measures of 4/4 at 2 divisions per quarter.
M1 = attributes() + note("C5", 2) + note("D5", 2) + note("E5", 4, tie=True)
M2 = note("E5", 4) + note(None, 4)


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, xml: str) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8")
        return path


class MusicXmlTest(Temp):
    def test_notes_onsets_and_durations_in_whole_notes(self) -> None:
        s = read_score(self.write("a.musicxml", score([("Flute", [M1, M2])])))
        notes = s.parts[0].measures[0].notes
        self.assertEqual([n.pitch for n in notes], ["C5", "D5", "E5"])
        self.assertEqual([n.onset for n in notes], [0, Fraction(1, 4), Fraction(1, 2)])
        self.assertEqual(notes[2].duration, Fraction(1, 2))
        self.assertTrue(notes[2].tie)
        self.assertEqual(s.parts[0].measures[0].clefs, {1: "G2"})
        self.assertEqual(s.parts[0].measures[0].time, "4/4")

    def test_chords_backup_and_two_staves(self) -> None:
        body = (
            attributes(staves=2, clefs={1: "G2", 2: "F4"})
            + note("C5", 8)
            + note("E5", 8, chord=True)
            + "<backup><duration>8</duration></backup>"
            + note("C3", 4, voice=2, staff=2)
            + note("G2", 4, voice=2, staff=2)
        )
        s = read_score(self.write("p.musicxml", score([("Piano", [body])])))
        self.assertEqual(s.parts[0].staves, 2)
        m = staff_measures(s)
        self.assertEqual(tokens(m[0][0]), ["[clef G2]", "[key 0]", "[time 4/4]", "<C5 E5>:1"])
        self.assertEqual(tokens(m[1][0]), ["[clef F4]", "[key 0]", "[time 4/4]", "C3:2", "G2:2"])
        self.assertEqual([s.label for s in staves(s)], ["Piano/1", "Piano/2"])

    def test_clef_after_the_last_note_belongs_to_the_next_measure(self) -> None:
        clef = '<attributes><clef><sign>F</sign><line>4</line></clef></attributes>'
        s = read_score(self.write("c.musicxml", score([("Cello", [M1 + clef, M2])])))
        first, second = s.parts[0].measures
        self.assertEqual(first.clefs, {1: "G2"})
        self.assertEqual(second.clefs, {1: "F4"})

    def test_multi_measure_rest_written_as_one_measure(self) -> None:
        rest = (
            attributes()
            + "<attributes><measure-style><multiple-rest>3</multiple-rest></measure-style></attributes>"
            + note(None, 8, measure_rest=True)
        )
        s = read_score(self.write("r.musicxml", score([("Horn", [rest, M2])])))
        self.assertEqual([m.number for m in s.parts[0].measures], ["1", "2", "3", "2"])
        self.assertEqual([m.added for m in s.parts[0].measures], [False, True, True, False])

    def test_movements_are_read_in_order(self) -> None:
        one = write_mxl(self.tmp / "b.mvt1.mxl", score([("Flute", [M1])]))
        two = write_mxl(self.tmp / "b.mvt2.mxl", score([("Flute", [M2])]))
        s = read_movements([two, one])
        self.assertEqual(len(s.parts[0].measures), 2)
        self.assertEqual(s.parts[0].measures[0].notes[0].pitch, "C5")

    def test_normalized_text_ignores_date_and_software(self) -> None:
        a = self.write("a.xml", score([("Flute", [M1])]))
        b = self.write("b.xml", score([("Flute", [M1])]).replace("2026-01-01", "2026-02-02"))
        self.assertEqual(normalized_text(a), normalized_text(b))


class MeasuresTest(unittest.TestCase):
    def test_duration_text(self) -> None:
        self.assertEqual(duration_text(Fraction(1, 4)), "4")
        self.assertEqual(duration_text(Fraction(3, 8)), "4.")
        self.assertEqual(duration_text(Fraction(7, 16)), "4..")
        self.assertEqual(duration_text(Fraction(1, 12)), "8*2/3")

    def test_voices_are_ignored_for_equality_but_reported(self) -> None:
        one = read_score_text(score([("Fl", [attributes() + note("C5", 4) + note("D5", 4)])]))
        two = read_score_text(
            score([("Fl", [attributes() + note("C5", 4, voice=2) + note("D5", 4, voice=2)])])
        )
        a, b = staff_measures(one)[0][0], staff_measures(two)[0][0]
        self.assertEqual(a, b)
        self.assertFalse(a.same_voices(b))

    def test_partial_tie_in_a_chord_and_gaps(self) -> None:
        body = (
            attributes()
            + "<forward><duration>2</duration></forward>"
            + note("C5", 2, tie=True)
            + note("E5", 2, chord=True)
            + note("D5", 4)
        )
        m = staff_measures(read_score_text(score([("Fl", [body])])))[0][0]
        self.assertEqual(tokens(m)[3:], ["s:4", "<C5~ E5>:4", "D5:2"])


def read_score_text(xml: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.musicxml"
        path.write_text(xml, encoding="utf-8")
        return read_score(path)


class AlignTest(unittest.TestCase):
    def test_a_missing_measure_costs_one_measure(self) -> None:
        bodies = [attributes() + note(p, 8) for p in ("C5", "D5", "E5", "F5")]
        full = staff_measures(read_score_text(score([("Fl", bodies)])))[0]
        short = staff_measures(read_score_text(score([("Fl", bodies[:1] + bodies[2:])])))[0]
        self.assertEqual(align(full, short), [(0, 0), (1, None), (2, 1), (3, 2)])


class CompareTest(Temp):
    def test_identical_changed_failed(self) -> None:
        changed = score([("Flute", [M1, note("E5", 4) + note("F5", 4)])])
        a = open_run(make_run(self.tmp / "a", "base", {"x.png": score([("Flute", [M1, M2])]),
                                                        "y.png": changed, "z.png": changed}))
        b = open_run(make_run(self.tmp / "b", "fix", {"x.png": score([("Flute", [M1, M2])]),
                                                       "y.png": score([("Flute", [M1, M2])]),
                                                       "z.png": None}))
        c = compare_runs(a, b)
        verdicts = {r.id: r.verdict for r in c.results}
        self.assertEqual(verdicts, {"x.png": "identical", "y.png": "changed", "z.png": "failed"})
        y = next(r for r in c.results if r.id == "y.png")
        self.assertEqual([(ch.a, ch.b) for ch in y.changes], [(1, 1)])

    def test_with_a_reference_changes_are_judged(self) -> None:
        good = score([("Flute", [M1, M2])])
        bad = score([("Flute", [M1, note("E5", 4) + note("F5", 4)])])
        inputs = self.tmp / "set"
        (inputs / "piece").mkdir(parents=True)
        (inputs / "piece" / "scan.png").write_bytes(b"")
        (inputs / "piece" / "ground_truth.musicxml").write_text(good, encoding="utf-8")
        a = open_run(make_run(self.tmp / "a", "base", {"piece/scan.png": bad}))
        b = open_run(make_run(self.tmp / "b", "fix", {"piece/scan.png": good}))
        r = compare_input(a, b, "piece/scan.png", inputs=inputs)
        self.assertTrue(r.has_reference)
        self.assertEqual(r.verdict, "better")
        self.assertEqual([ch.verdict for ch in r.changes], ["fixed"])
        self.assertEqual(r.metrics_b.exact, 1.0)
        self.assertEqual(r.metrics_a.exact, 0.5)
        back = compare_input(b, a, "piece/scan.png", inputs=inputs)
        self.assertEqual(back.verdict, "worse")
        self.assertEqual([ch.verdict for ch in back.changes], ["broken"])

    def test_split_part_shows_extra_staves(self) -> None:
        one = score([("Violin I", [M1, M2])])
        two = score([("Vln. I", [M1, M2]), ("Violin I", [M1, M2])])
        a = open_run(make_run(self.tmp / "a", "base", {"x.png": two}))
        b = open_run(make_run(self.tmp / "b", "fix", {"x.png": one}))
        r = compare_input(a, b, "x.png")
        self.assertEqual(r.verdict, "changed")
        self.assertEqual(r.staves_only_a, ["Violin I"])
        self.assertEqual(r.parts_a, ["Vln. I", "Violin I"])


class InputsTest(Temp):
    def test_inputs_and_references(self) -> None:
        root = self.tmp / "set"
        for name in ("a/score.pdf", "a/scan.png", "b/page.png", "b/page.musicxml", "a/notes.txt"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
        (root / "a" / "ground_truth.mxl").write_text("x")
        self.assertEqual(find_inputs(root), ["a/scan.png", "a/score.pdf", "b/page.png"])
        self.assertEqual(find_reference("a/scan.png", root, None), [root / "a" / "ground_truth.mxl"])
        self.assertEqual(find_reference("b/page.png", root, None), [root / "b" / "page.musicxml"])
        accepted = self.tmp / "refs" / "b/page.png"
        accepted.mkdir(parents=True)
        (accepted / "page.mxl").write_text("x")
        self.assertEqual(find_reference("b/page.png", root, self.tmp / "refs"), [accepted / "page.mxl"])


class BookTest(Temp):
    def test_columns_and_multi_measure_rests(self) -> None:
        sheet = """<sheet><picture width="1000" height="800"/><page>
          <system><stack left="100" right="400"/><stack left="400" right="900"/>
            <part><staff><lines><line><point x="100" y="100"/></line>
            <line><point x="100" y="140"/></line></lines></staff></part></system>
          <system><stack left="80" right="900"/>
            <part><staff><lines><line><point x="80" y="300"/></line>
            <line><point x="80" y="340"/></line></lines></staff></part></system>
        </page></sheet>"""
        path = self.tmp / "book.omr"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("book.xml", '<book><sheet number="1"/></book>')
            z.writestr("sheet#1/sheet#1.xml", sheet)
            z.writestr("sheet#1/BINARY.png", b"png")
        book = read_book(path)
        self.assertEqual(len(book.columns), 3)
        self.assertEqual(book.columns[2].y, 300)
        self.assertEqual(book.image(1), b"png")
        boxes = measure_boxes(book, [False, True, False, False])
        self.assertIs(boxes[0], boxes[1])
        self.assertEqual(boxes[2].x, 400)
        self.assertEqual(boxes[3].x, 80)


class CliTest(Temp):
    def test_compare_writes_reports_and_fails_on_worse(self) -> None:
        good = score([("Flute", [M1, M2])])
        bad = score([("Flute", [M1, note("E5", 4) + note("F5", 4)])])
        make_run(self.tmp / "a", "base", {"x.png": good})
        make_run(self.tmp / "b", "fix", {"x.png": bad})
        refs = self.tmp / "refs"
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["accept", str(self.tmp / "a"), "--references", str(refs)]), 0)
            code = main([
                "compare", str(self.tmp / "a"), str(self.tmp / "b"), "--references", str(refs),
                "--html", str(self.tmp / "r" / "report.html"), "--json", str(self.tmp / "r.json"),
            ])
        self.assertEqual(code, 1)
        self.assertIn("worse", out.getvalue())
        data = json.loads((self.tmp / "r.json").read_text())
        self.assertEqual(data["inputs"][0]["verdict"], "worse")
        page = (self.tmp / "r" / "report.html").read_text(encoding="utf-8")
        self.assertIn("broken", page)
        self.assertIn("<mark>F5:2</mark>", page)


FAKE = """import sys, time, zipfile
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("-output") + 1])
source = Path(args[args.index("--") + 1])
if "slow" in source.name:
    time.sleep(60)
out.mkdir(parents=True, exist_ok=True)
if "bad" not in source.name:
    with zipfile.ZipFile(out / (source.stem + ".mxl"), "w") as z:
        z.writestr("score.xml", Path(__file__).with_name("score.xml").read_text())
print("transcribed", source.name)
"""


class RunTest(Temp):
    def launcher(self) -> Path:
        (self.tmp / "fake.py").write_text(FAKE)
        (self.tmp / "score.xml").write_text(score([("Flute", [M1, M2])]))
        if sys.platform == "win32":
            path = self.tmp / "fake.bat"
            path.write_text(f'@"{sys.executable}" "%~dp0fake.py" %*\n')
        else:
            path = self.tmp / "fake.sh"
            path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake.py" "$@"\n')
            path.chmod(0o755)
        return path

    def test_run_writes_exports_status_and_resumes(self) -> None:
        inputs = self.tmp / "set"
        for name in ("one/score.png", "two/bad.png", "three/slow.png"):
            (inputs / name).parent.mkdir(parents=True, exist_ok=True)
            (inputs / name).write_bytes(b"")
        run = self.tmp / "run"
        args = ["run", "--audiveris", str(self.launcher()), "--inputs", str(inputs),
                "--out", str(run), "--timeout", "8", "--jobs", "3"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        r = open_run(run)
        self.assertEqual(r.ids(), ["one/score.png", "three/slow.png", "two/bad.png"])
        self.assertEqual(r.status("one/score.png")["status"], "ok")
        self.assertEqual(r.status("two/bad.png")["status"], "no export")
        self.assertEqual(r.status("three/slow.png")["status"], "timeout")
        self.assertIn("transcribed", (run / "one/score.png/run.log").read_text())
        self.assertEqual(json.loads((run / "run.json").read_text())["label"], "run")
        out = io.StringIO()
        with redirect_stdout(out):
            main(args)
        self.assertIn("0 inputs run, 3 already done", out.getvalue())


class ReportTest(Temp):
    def test_report_without_changes(self) -> None:
        make_run(self.tmp / "a", "base", {"x.png": score([("Flute", [M1])])})
        make_run(self.tmp / "b", "fix", {"x.png": score([("Flute", [M1])])})
        c = compare_runs(open_run(self.tmp / "a"), open_run(self.tmp / "b"))
        write_html(c, self.tmp / "report.html")
        self.assertIn("1 identical", (self.tmp / "report.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
