"""Run an Audiveris build on every input of a test set.

Each input is transcribed in batch mode into its own folder of the run, exporting
MusicXML and saving the book: ``Audiveris -batch -transcribe -export -save -output
<run>/<id> [options] -- <input>``. Inputs already done are skipped, so an interrupted
run resumes where it stopped.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from omr_regress.inputs import musicxml_files


def audiveris_command(audiveris: Path, output: Path, source: Path, options: list[str]) -> list[str]:
    return [
        str(audiveris),
        "-batch",
        "-transcribe",
        "-export",
        "-save",
        "-output",
        str(output),
        *options,
        "--",
        str(source),
    ]


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop the launcher and the Java process it started."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    proc.wait()


def run_one(
    audiveris: Path, source: Path, output: Path, options: list[str], timeout: float
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    status = "ok"
    code = None
    with (output / "run.log").open("wb") as log:
        try:
            proc = subprocess.Popen(
                audiveris_command(audiveris, output, source, options),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            log.write(f"cannot start Audiveris: {exc}\n".encode())
            status = "error"
        else:
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                status = "timeout"
    if status == "ok" and not musicxml_files(output):
        status = "no export"
    result = {"status": status, "returncode": code, "seconds": round(time.monotonic() - started, 1)}
    (output / "status.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
    return result


def run_set(
    audiveris: Path,
    inputs: Path,
    ids: list[str],
    run: Path,
    *,
    label: str | None = None,
    options: list[str] | None = None,
    jobs: int = 2,
    timeout: float = 900.0,
    force: bool = False,
) -> dict[str, dict]:
    """Transcribe each input; returns the status of those run now."""
    run.mkdir(parents=True, exist_ok=True)
    manifest_path = run / "run.json"
    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "label": label or manifest.get("label") or run.name,
            "audiveris": str(audiveris),
            "inputs": str(inputs.resolve()),
            "options": options or [],
            "started": manifest.get("started")
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    todo = [i for i in ids if force or not (run / i / "status.json").is_file()]
    results: dict[str, dict] = {}
    if not todo:
        return results
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(run_one, audiveris, inputs / i, run / i, options or [], timeout): i
            for i in todo
        }
        for done, future in enumerate(as_completed(futures), 1):
            input_id = futures[future]
            results[input_id] = future.result()
            r = results[input_id]
            print(
                f"[{done}/{len(todo)}] {input_id}: {r['status']} ({r['seconds']} s)",
                file=sys.stderr,
                flush=True,
            )
    return results
