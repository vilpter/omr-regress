"""Read MusicXML (``.musicxml``, ``.xml`` or compressed ``.mxl``) into a light model.

Only what a regression check compares is kept: parts and their staves, and in each
measure the clef, key and time changes, the barline repeats and endings, and the notes
and rests with their onset, duration, pitch, voice, ties and slurs. Durations and onsets
are fractions of a whole note, so files with different ``divisions`` compare equal.

A book that Audiveris exports as several movements (``book.mvt1.mxl``, ``book.mvt2.mxl``)
is read as one score, its movements' measures one after the other (:func:`read_movements`).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class MusicXmlError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    staff: int
    voice: str
    onset: Fraction  # from the start of the measure, in whole notes
    duration: Fraction  # 0 for a grace note
    pitch: str | None  # "C#5", "Bb4"; None for a rest
    grace: bool = False
    tie: bool = False  # tied to the next note
    slur_start: int = 0
    slur_stop: int = 0
    measure_rest: bool = False

    @property
    def midi(self) -> int | None:
        if self.pitch is None:
            return None
        m = re.fullmatch(r"([A-G])(#*|b*)(-?\d+)", self.pitch)
        if m is None:
            return None
        alter = len(m[2]) if m[2].startswith("#") else -len(m[2])
        return 12 * (int(m[3]) + 1) + STEPS[m[1]] + alter


@dataclass
class Measure:
    number: str
    notes: list[Note] = field(default_factory=list)
    clefs: dict[int, str] = field(default_factory=dict)  # staff -> "G2", "F4", "G2-8"
    # Clef changes within the measure: (staff, onset in whole notes, clef). A clef written
    # after the last note is read as the next measure's clef, where it takes effect.
    inner_clefs: list[tuple[int, Fraction, str]] = field(default_factory=list)
    key: int | None = None  # fifths, when the key is set in this measure
    time: str | None = None  # "3/4", when the time is set in this measure
    left_repeat: bool = False
    right_repeat: bool = False
    endings: tuple[str, ...] = ()  # numbers of the endings that start here
    multiple_rest: int = 0  # a multi-measure rest of this many measures starts here
    added: bool = False  # added by the reader for a multi-measure rest written as one measure


@dataclass
class Part:
    id: str
    name: str
    abbreviation: str
    staves: int
    measures: list[Measure] = field(default_factory=list)


@dataclass
class Score:
    parts: list[Part]

    @property
    def staff_count(self) -> int:
        return sum(p.staves for p in self.parts)

    @property
    def measure_count(self) -> int:
        return max((len(p.measures) for p in self.parts), default=0)


def _text(path: Path) -> bytes:
    if path.suffix.lower() != ".mxl":
        return path.read_bytes()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        root = None
        if "META-INF/container.xml" in names:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            for rf in container.iter():
                if rf.tag.endswith("rootfile") and rf.get("full-path"):
                    root = rf.get("full-path")
                    break
        if root is None:
            root = next(
                (n for n in names if n.endswith(".xml") and not n.startswith("META-INF")), None
            )
        if root is None:
            raise MusicXmlError(f"{path.name}: no MusicXML inside")
        return z.read(root)


def _pitch(el: ET.Element) -> str:
    step = el.findtext("step") or el.findtext("display-step") or "C"
    octave = el.findtext("octave") or el.findtext("display-octave") or "4"
    alter = round(float(el.findtext("alter") or 0))
    return f"{step}{'#' * alter if alter > 0 else 'b' * -alter}{octave}"


def _clef(el: ET.Element) -> str:
    sign = el.findtext("sign") or "G"
    line = el.findtext("line") or ""
    octave = int(el.findtext("clef-octave-change") or 0)
    shift = f"{'+' if octave > 0 else '-'}{abs(octave) * 7 + 1}" if octave else ""
    return f"{sign}{line}{shift}"


def read_score(path: Path) -> Score:
    try:
        root = ET.fromstring(_text(path))
    except (ET.ParseError, zipfile.BadZipFile, KeyError) as exc:
        raise MusicXmlError(f"{path.name}: {exc}") from exc
    if root.tag != "score-partwise":
        raise MusicXmlError(f"{path.name}: {root.tag} is not supported (score-partwise only)")
    names = {}
    for sp in root.iter("score-part"):
        names[sp.get("id")] = (
            (sp.findtext("part-name") or "").strip(),
            (sp.findtext("part-abbreviation") or "").strip(),
        )
    parts = []
    for p in root.findall("part"):
        name, abbreviation = names.get(p.get("id"), ("", ""))
        parts.append(_part(p, name, abbreviation))
    return Score(parts)


def _part(el: ET.Element, name: str, abbreviation: str) -> Part:
    part = Part(el.get("id") or "", name, abbreviation, staves=1)
    divisions = 1
    carried: dict[int, str] = {}  # clefs written at the end of the previous measure
    for m_el in el.findall("measure"):
        m = Measure(m_el.get("number") or str(len(part.measures) + 1))
        position = Fraction(0)  # in divisions
        end = Fraction(0)
        last_onset = Fraction(0)
        clefs: list[tuple[int, Fraction, str]] = []
        for child in m_el:
            if child.tag == "attributes":
                divisions = int(child.findtext("divisions") or divisions)
                part.staves = max(part.staves, int(child.findtext("staves") or 1))
                for c in child.findall("clef"):
                    clefs.append((int(c.get("number") or 1), position / (4 * divisions), _clef(c)))
                key = child.find("key")
                if key is not None and key.findtext("fifths") is not None:
                    m.key = int(key.findtext("fifths") or 0)
                time = child.find("time")
                if time is not None:
                    beats, beat_type = time.findtext("beats"), time.findtext("beat-type")
                    m.time = f"{beats}/{beat_type}" if beats and beat_type else "free"
                rest = child.findtext("measure-style/multiple-rest")
                if rest:
                    m.multiple_rest = int(rest)
            elif child.tag == "backup":
                position -= Fraction(child.findtext("duration") or 0)
            elif child.tag == "forward":
                position += Fraction(child.findtext("duration") or 0)
            elif child.tag == "barline":
                repeat = child.find("repeat")
                if repeat is not None:
                    if repeat.get("direction") == "forward":
                        m.left_repeat = True
                    else:
                        m.right_repeat = True
                ending = child.find("ending")
                if ending is not None and ending.get("type") == "start":
                    m.endings += (ending.get("number") or "",)
            elif child.tag == "note":
                grace = child.find("grace") is not None
                chord = child.find("chord") is not None
                length = Fraction(0) if grace else Fraction(child.findtext("duration") or 0)
                onset = last_onset if chord else position
                rest = child.find("rest")
                pitch_el = child.find("pitch")
                if pitch_el is None:
                    pitch_el = child.find("unpitched")
                ties = [t.get("type") for t in child.findall("tie")]
                ties += [t.get("type") for t in child.findall("notations/tied")]
                slurs = [s.get("type") for s in child.findall("notations/slur")]
                m.notes.append(
                    Note(
                        staff=int(child.findtext("staff") or 1),
                        voice=(child.findtext("voice") or "1").strip(),
                        onset=onset / (4 * divisions),
                        duration=length / (4 * divisions),
                        pitch=None if rest is not None or pitch_el is None else _pitch(pitch_el),
                        grace=grace,
                        tie="start" in ties,
                        slur_start=slurs.count("start"),
                        slur_stop=slurs.count("stop"),
                        measure_rest=rest is not None and rest.get("measure") == "yes",
                    )
                )
                if not chord:
                    last_onset = position
                    position += length
                    end = max(end, position)
        m.clefs = dict(carried)
        carried = {}
        for staff, onset, clef in clefs:
            if onset == 0:
                m.clefs[staff] = clef
            elif onset >= end / (4 * divisions):
                carried[staff] = clef
            else:
                m.inner_clefs.append((staff, onset, clef))
        part.measures.append(m)
    part.measures = _expand_rests(part.measures)
    return part


def _rests_only(m: Measure) -> bool:
    return all(n.pitch is None for n in m.notes)


def _expand_rests(measures: list[Measure]) -> list[Measure]:
    """Write out the measures a multi-measure rest stands for, when the file writes it as
    one measure (as Audiveris does) rather than followed by the measures it covers."""
    out: list[Measure] = []
    for k, m in enumerate(measures):
        out.append(m)
        count = m.multiple_rest
        following = measures[k + 1 : k + count]
        if count < 2 or (len(following) == count - 1 and all(map(_rests_only, following))):
            continue
        for j in range(1, count):
            number = str(int(m.number) + j) if m.number.isdigit() else f"{m.number}+{j}"
            out.append(Measure(number, notes=list(m.notes), added=True))
    return out


_MOVEMENT = re.compile(r"\.mvt(\d+)$")


def read_movements(paths: list[Path]) -> Score:
    """One score from a book's exports: movements in order, parts joined by position."""

    def order(p: Path) -> tuple[int, str]:
        m = _MOVEMENT.search(p.stem)
        return (int(m[1]) if m else 0, p.name)

    scores = [read_score(p) for p in sorted(paths, key=order)]
    if not scores:
        raise MusicXmlError("no MusicXML file")
    first = scores[0]
    for s in scores[1:]:
        for i, part in enumerate(s.parts):
            if i < len(first.parts):
                first.parts[i].measures.extend(part.measures)
                first.parts[i].staves = max(first.parts[i].staves, part.staves)
            else:
                first.parts.append(part)
    return first


def normalized_text(path: Path) -> str:
    """The MusicXML text without what changes from run to run (encoding date, software)."""
    text = _text(path).decode("utf-8", errors="replace")
    return re.sub(
        r"<encoding-date>[^<]*</encoding-date>|<software>[^<]*</software>", "", text
    )
