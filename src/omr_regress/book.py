"""Where each measure is on the page, read from the book Audiveris saves (``.omr``).

A book is a zip with ``book.xml`` and, for each sheet, ``sheet#N/sheet#N.xml`` and the
binarized image ``sheet#N/BINARY.png``. A sheet's systems hold *stacks*, the measure
columns, each with its left and right x, and staves whose lines give the system's
height. The exported measures follow the stacks in sheet and system order; a
multi-measure rest is one stack and one exported measure.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
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
            sheet = ET.fromstring(z.read(xml))
            picture = sheet.find("picture")
            binary = f"sheet#{number}/BINARY.png"
            sheets.append(
                Sheet(
                    number,
                    int(picture.get("width", "0")) if picture is not None else 0,
                    int(picture.get("height", "0")) if picture is not None else 0,
                    binary if binary in names else None,
                )
            )
            for system in sheet.findall("page/system"):
                ys = [
                    float(pt.get("y", "0"))
                    for pt in system.findall("part/staff/lines/line/point")
                ]
                top, bottom = (min(ys), max(ys)) if ys else (0.0, 0.0)
                for stack in system.findall("stack"):
                    left = float(stack.get("left", "0"))
                    right = float(stack.get("right", str(left)))
                    columns.append(Box(number, left, top, right - left, bottom - top))
    return Book(path, sheets, columns)


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
