"""Staff measures: what one staff holds in one measure, how it compares, and how it reads.

A score's staves are numbered across its parts, top to bottom, the way a reader counts
them on the page. Two staff measures are *equal* when they set the same clef, key, time
and repeats, and hold the same notes and rests (onset, duration, pitch, grace, tie, slur
marks), whatever the voices they are written in. Voices are compared on their own, as a
lesser difference.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from itertools import groupby

from omr_regress.musicxml import Measure, Note, Score


@dataclass(frozen=True)
class Staff:
    part: int  # index of the part in the score
    number: int  # staff number within the part, from 1
    label: str  # "Violin I" or "Piano/2"


@dataclass(frozen=True)
class StaffMeasure:
    number: str  # the measure number as written
    header: tuple[str, ...]  # clef, key, time and repeats set in this measure
    events: tuple[tuple, ...]  # sorted, voice-agnostic
    voiced: tuple[tuple, ...]  # the same with voices
    notes: tuple[Note, ...]
    multiple_rest: int

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, StaffMeasure)
            and self.header == other.header
            and self.events == other.events
        )

    def __hash__(self) -> int:
        return hash((self.header, self.events))

    def same_voices(self, other: StaffMeasure) -> bool:
        return self.voiced == other.voiced

    @cached_property
    def counts(self) -> Counter:
        """The events, counted, for aligning measures that differ."""
        return Counter(self.events)

    @cached_property
    def pitched(self) -> Counter:
        """The notes as (onset, pitch, duration), for precision and recall."""
        return Counter((n.onset, n.pitch, n.duration) for n in self.notes if n.pitch)


def staves(score: Score) -> list[Staff]:
    out = []
    for i, part in enumerate(score.parts):
        name = part.name or part.abbreviation or part.id
        for n in range(1, part.staves + 1):
            out.append(Staff(i, n, name if part.staves == 1 else f"{name}/{n}"))
    return out


def _event(n: Note) -> tuple:
    return (n.onset, n.grace, n.pitch or "", n.duration, n.tie, n.slur_start, n.slur_stop)


def staff_measure(m: Measure, staff: int) -> StaffMeasure:
    notes = tuple(n for n in m.notes if n.staff == staff)
    header = []
    if staff in m.clefs:
        header.append(f"clef {m.clefs[staff]}")
    header += [f"clef {clef} at {onset}" for s, onset, clef in m.inner_clefs if s == staff]
    if m.key is not None:
        header.append(f"key {m.key:+d}" if m.key else "key 0")
    if m.time is not None:
        header.append(f"time {m.time}")
    if m.left_repeat:
        header.append("|:")
    if m.endings:
        header.append(f"ending {','.join(m.endings)}")
    if m.right_repeat:
        header.append(":|")
    events = tuple(sorted(_event(n) for n in notes))
    voiced = tuple(sorted((n.voice, *_event(n)) for n in notes))
    return StaffMeasure(m.number, tuple(header), events, voiced, notes, m.multiple_rest)


def staff_measures(score: Score) -> list[list[StaffMeasure]]:
    """For each staff of :func:`staves`, its measures."""
    return [
        [staff_measure(m, s.number) for m in score.parts[s.part].measures] for s in staves(score)
    ]


# --- reading ---------------------------------------------------------------------

_VALUES = [Fraction(1, 2**k) for k in range(8)]  # whole note to 128th


def duration_text(d: Fraction) -> str:
    """A duration as a note value: 4 for a quarter, 8. for a dotted eighth, 8*2/3 in a
    triplet."""
    if d == 0:
        return "0"
    for base in _VALUES:
        for dots in range(4):
            if base * (2 - Fraction(1, 2**dots)) == d:
                return f"{base.denominator}{'.' * dots}"
    for ratio in (Fraction(2, 3), Fraction(4, 3), Fraction(4, 5), Fraction(4, 6), Fraction(8, 7)):
        plain = d / ratio
        for base in _VALUES:
            for dots in range(3):
                if base * (2 - Fraction(1, 2**dots)) == plain:
                    return f"{base.denominator}{'.' * dots}*{ratio}"
    return str(d)


def _note_text(group: list[Note]) -> str:
    first = group[0]
    pitched = [n for n in group if n.pitch]
    tie = ""
    if not pitched:
        body = "R" if first.measure_rest else "r"
    elif len(pitched) == 1:
        body = pitched[0].pitch
        tie = "~" if pitched[0].tie else ""
    elif all(n.tie for n in pitched):
        body = "<" + " ".join(n.pitch for n in pitched) + ">"
        tie = "~"
    else:  # some notes of the chord tied: mark each
        body = "<" + " ".join(n.pitch + ("~" if n.tie else "") for n in pitched) + ">"
    text = f"{'g' if first.grace else ''}{body}:{duration_text(first.duration)}{tie}"
    text += "(" * sum(n.slur_start for n in group) + ")" * sum(n.slur_stop for n in group)
    return text


def _voice_order(notes: list[Note]) -> tuple:
    """Upper voices first (the mean pitch of their notes), voices of rests only last."""
    pitches = [n.midi for n in notes if n.midi is not None]
    if not pitches:
        return (1, 0.0, notes[0].onset)
    return (0, -sum(pitches) / len(pitches), notes[0].onset)


def tokens(sm: StaffMeasure) -> list[str]:
    """The measure as words: its header, then each voice's notes in time order, upper
    voices first. Time a voice leaves out reads as a spacer (``s:8``), a voice that goes
    back in time as ``@onset``."""
    out = [f"[{h}]" for h in sm.header]
    if sm.multiple_rest:
        out.append(f"[rest x{sm.multiple_rest}]")
    by_voice = sorted(sm.notes, key=lambda n: (n.voice, n.onset, n.grace is False))
    voices = [list(notes) for _, notes in groupby(by_voice, key=lambda n: n.voice)]
    for k, notes in enumerate(sorted(voices, key=_voice_order)):
        if k:
            out.append("//")
        time = Fraction(0)
        chords = groupby(notes, key=lambda n: (n.onset, n.grace, n.duration, n.pitch is None))
        for (onset, _, duration, _), group in chords:
            if onset > time:
                out.append(f"s:{duration_text(onset - time)}")
            elif onset < time:
                out.append(f"@{onset}")
            out.append(_note_text(list(group)))
            time = onset + duration
    return out
