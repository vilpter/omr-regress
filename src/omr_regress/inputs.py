"""Test inputs, the runs that hold a build's output for each, and their references.

A *test set* is a folder of input images and PDFs, searched recursively; an input's
*id* is its path relative to that folder (``quartets/haydn/score.pdf``).

A *run* is a folder with a ``run.json`` (the build and test set it ran) and, for each
input, a folder named by its id holding what the build wrote: the MusicXML export
(one ``.mxl`` per movement), the book (``.omr``), a ``run.log`` and a ``status.json``.

A *reference* is the correct transcription of an input, looked up in this order:

1. ``<references>/<id>/``: a folder of MusicXML files, as :command:`accept` writes it;
2. a MusicXML file next to the input, with the same name and another extension
   (``score.musicxml`` for ``score.pdf``);
3. ``ground_truth.musicxml`` or ``reference.musicxml`` (or ``.mxl``, ``.xml``) in the
   input's folder, shared by every input there (a scan and a photo of the same page).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

INPUT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
MUSICXML_SUFFIXES = (".mxl", ".musicxml", ".xml")
SHARED_REFERENCES = ("ground_truth", "reference")


def find_inputs(root: Path) -> list[str]:
    """The ids of the inputs under ``root``, sorted."""
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in INPUT_SUFFIXES
    )


def read_list(path: Path) -> list[str]:
    """Input ids listed in a file, one per line (blank lines and ``#`` comments skipped)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def musicxml_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in MUSICXML_SUFFIXES)


def find_reference(input_id: str, inputs: Path | None, references: Path | None) -> list[Path]:
    """The reference files of an input (several for a book of movements), or []."""
    if references is not None:
        files = musicxml_files(references / input_id)
        if files:
            return files
    if inputs is None:
        return []
    source = inputs / input_id
    for suffix in MUSICXML_SUFFIXES:
        candidate = source.with_suffix(suffix)
        if candidate.is_file() and candidate != source:
            return [candidate]
    for stem in SHARED_REFERENCES:
        for suffix in MUSICXML_SUFFIXES:
            candidate = source.parent / f"{stem}{suffix}"
            if candidate.is_file():
                return [candidate]
    return []


@dataclass
class Run:
    """A build's output on a test set."""

    folder: Path
    manifest: dict

    @property
    def label(self) -> str:
        return self.manifest.get("label") or self.folder.name

    @property
    def inputs(self) -> Path | None:
        root = self.manifest.get("inputs")
        return Path(root) if root else None

    def ids(self) -> list[str]:
        """Inputs the run has a result for (finished, with or without an export)."""
        return sorted(
            p.parent.relative_to(self.folder).as_posix() for p in self.folder.rglob("status.json")
        )

    def output(self, input_id: str) -> Path:
        return self.folder / input_id

    def status(self, input_id: str) -> dict:
        path = self.output(input_id) / "status.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "missing"}

    def exports(self, input_id: str) -> list[Path]:
        return musicxml_files(self.output(input_id))

    def book(self, input_id: str) -> Path | None:
        books = sorted(self.output(input_id).glob("*.omr"))
        return books[0] if books else None


def open_run(folder: Path) -> Run:
    path = folder / "run.json"
    manifest = {}
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    return Run(folder, manifest)
