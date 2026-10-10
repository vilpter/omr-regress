"""Small MusicXML scores and runs written on the fly."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <identification><encoding><software>test 1</software>
  <encoding-date>2026-01-01</encoding-date></encoding></identification>
  <part-list>{parts}</part-list>
"""


def note(pitch: str | None, duration: int, *, voice: int = 1, staff: int = 1, chord=False,
         tie=False, slur=None, dots=0, measure_rest=False) -> str:
    """A <note>; pitch like "C5", "F#4", "Bb3", or None for a rest."""
    if pitch is None:
        body = '<rest measure="yes"/>' if measure_rest else "<rest/>"
    else:
        step, rest = pitch[0], pitch[1:]
        alter = rest.count("#") - rest.count("b")
        octave = rest.strip("#b")
        body = f"<pitch><step>{step}</step>{f'<alter>{alter}</alter>' if alter else ''}<octave>{octave}</octave></pitch>"
    notations = ""
    if tie or slur:
        notations = "<notations>"
        if tie:
            notations += '<tied type="start"/>'
        if slur:
            notations += f'<slur type="{slur}"/>'
        notations += "</notations>"
    tie_xml = '<tie type="start"/>' if tie else ""
    return (
        f"<note>{'<chord/>' if chord else ''}{body}<duration>{duration}</duration>"
        f"{tie_xml}<voice>{voice}</voice>{'<dot/>' * dots}"
        f"<staff>{staff}</staff>{notations}</note>"
    )


def attributes(divisions=2, clef="G2", key=0, time="4/4", staves=1, clefs=None) -> str:
    beats, beat_type = time.split("/")
    clef_xml = ""
    for number, c in (clefs or {1: clef}).items():
        clef_xml += f'<clef number="{number}"><sign>{c[0]}</sign><line>{c[1]}</line></clef>'
    return (
        f"<attributes><divisions>{divisions}</divisions><key><fifths>{key}</fifths></key>"
        f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
        f"<staves>{staves}</staves>{clef_xml}</attributes>"
    )


def score(parts: list[tuple[str, list[str]]]) -> str:
    """parts: (name, [measure body, ...])."""
    plist = "".join(
        f'<score-part id="P{i}"><part-name>{name}</part-name></score-part>'
        for i, (name, _) in enumerate(parts, 1)
    )
    out = HEAD.format(parts=plist)
    for i, (_, measures) in enumerate(parts, 1):
        out += f'<part id="P{i}">'
        for n, body in enumerate(measures, 1):
            out += f'<measure number="{n}">{body}</measure>'
        out += "</part>"
    return out + "</score-partwise>\n"


def write_mxl(path: Path, xml: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>',
        )
        z.writestr("score.xml", xml)
    return path


def make_run(folder: Path, label: str, exports: dict[str, str | None]) -> Path:
    """A run folder: input id -> MusicXML text (None for an input without export)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps({"label": label}))
    for input_id, xml in exports.items():
        out = folder / input_id
        out.mkdir(parents=True, exist_ok=True)
        if xml is not None:
            write_mxl(out / "score.mxl", xml)
        status = "ok" if xml is not None else "no export"
        (out / "status.json").write_text(json.dumps({"status": status}))
    return folder
