"""Where each measure is on the page, read from the book Audiveris saves (``.omr``).

A book is a zip with ``book.xml`` and, for each sheet, ``sheet#N/sheet#N.xml`` and the
binarized image ``sheet#N/BINARY.png``. A sheet's systems hold *stacks*, the measure
columns, each with its left and right x, and staves whose lines give the system's
height. The exported measures follow the stacks in sheet and system order; a
multi-measure rest is one stack and one exported measure.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Box:
    sheet: int  # sheet number, from 1
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Sheet:
    number: int
    width: int
    height: int
    image: str | None  # the binary image's name in the book, if saved


@dataclass
class Book:
    path: Path
    sheets: list[Sheet]
    columns: list[Box]  # each stack across its whole system, in reading order

    def image(self, sheet: int) -> bytes | None:
        s = next((s for s in self.sheets if s.number == sheet), None)
        if s is None or s.image is None:
            return None
        with zipfile.ZipFile(self.path) as z:
            return z.read(s.image)


@lru_cache(maxsize=32)
def read_book(path: Path) -> Book | None:
    """The book's sheets and measure columns; None if it cannot be read."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return None
    with z:
        names = set(z.namelist())
        if "book.xml" not in names:
            return None
        book = ET.fromstring(z.read("book.xml"))
        sheets, columns = [], []
        for sheet_el in book.findall("sheet"):
            number = int(sheet_el.get("number", "0"))
            xml = f"sheet#{number}/sheet#{number}.xml"
            if xml not in names:
                continue  # sheet not transcribed: its measures are not exported
            width, height, systems = _read_sheet(z.read(xml))
            binary = f"sheet#{number}/BINARY.png"
            sheets.append(Sheet(number, width, height, binary if binary in names else None))
            for stacks, ys in systems:
                top, bottom = (min(ys), max(ys)) if ys else (0.0, 0.0)
                for left, right in stacks:
                    columns.append(Box(number, left, top, right - left, bottom - top))
    return Book(path, sheets, columns)


# The few tags read from a sheet file, in document order.
_TAGS = re.compile(rb"<(picture|system|stack|lines|/lines|point)\b([^>]*)>")
_ATTR = re.compile(rb'([\w-]+)="([^"]*)"')


def _read_sheet(
    data: bytes,
) -> tuple[int, int, list[tuple[list[tuple[float, float]], list[float]]]]:
    """The picture's size, and each system's stacks (left, right) and staff line ys.

    A sheet file holds every symbol Audiveris found, megabytes of them. Building it into
    a tree takes about a second; the tags needed here are found by a scan of its text.
    Staff lines (``system/part/staff/lines/line/point``) are the only points it has."""
    width = height = 0
    systems: list[tuple[list[tuple[float, float]], list[float]]] = []
    in_lines = False
    for m in _TAGS.finditer(data):
        tag = m.group(1)
        if tag == b"lines":
            in_lines = True
        elif tag == b"/lines":
            in_lines = False
        elif tag == b"point":
            if in_lines and systems:
                y = re.search(rb'\by="([^"]*)"', m.group(2))
                systems[-1][1].append(float(y.group(1)) if y else 0.0)
        else:
            attrs = {k.decode(): v.decode() for k, v in _ATTR.findall(m.group(2))}
            if tag == b"picture":
                width, height = int(attrs.get("width", "0")), int(attrs.get("height", "0"))
            elif tag == b"system":
                systems.append(([], []))
            elif systems:  # a stack
                left = float(attrs.get("left", "0"))
                systems[-1][0].append((left, float(attrs.get("right", left))))
    return width, height, systems


def measure_boxes(book: Book, added: list[bool]) -> list[Box | None]:
    """The column of each exported measure, given which measures the reader added for a
    multi-measure rest (they share the column of the measure holding the rest)."""
    out: list[Box | None] = []
    column = 0
    for extra in added:
        if extra and out:
            out.append(out[-1])
            continue
        out.append(book.columns[column] if column < len(book.columns) else None)
        column += 1
    return out
