#!/usr/bin/env python3
"""Compile both regional streams and enforce the demo's RAM/timing contract."""
import json
from pathlib import Path
import sys

from phasor.compiler import compile_score
from phasor.stream import encode


def prepare(score_path, output):
    score = json.loads(Path(score_path).read_text())
    if score["tick_hz"] != 100:
        raise ValueError("the boot demo requires a 100 Hz score")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    reports = {}
    for region in ("ntsc", "pal"):
        events, report = compile_score(score, clock=region)
        data = encode(events, score["tick_hz"], score["duration_ticks"])
        if not 16 <= len(data) <= 0x8800:
            raise ValueError(f"{region}: {len(data)} bytes exceeds the $8800-byte song buffer")
        (output / f"SUN.{region.upper()}").write_bytes(data)
        reports[region] = dict(report, file_bytes=len(data))
    (output / "compile.json").write_text(json.dumps(reports, indent=2) + "\n")


if __name__ == "__main__":
    prepare(*sys.argv[1:])
