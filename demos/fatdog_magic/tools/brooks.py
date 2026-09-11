"""Import SDD Brooks exports without changing pixels or line palettes.

MemoryLoader.cpp in SuperDuperDisplay defines the layout: AUX SHR, 6400
palette bytes, MAIN SHR, and optionally another 6400 palette bytes.
Use matching AUX/MAIN $0400 palette tables, uploaded through temporary capture.
"""
from pathlib import Path
import hashlib
import json
import random
import re
import shutil

ASSETS = Path(__file__).resolve().parents[1] / "assets/brooks_shr"
MAGIC = bytes.fromhex("b3 b2 b0 b0")


def normalize(data: bytes) -> bytes:
    if len(data) not in (71936, 78336):
        raise ValueError(f"Unsupported or incomplete Brooks export: {len(data)} bytes")
    for base in (0, 39168):
        if data[base + 0x7DFC:base + 0x7E00] != MAGIC:
            raise ValueError("Missing Brooks magic in a field")
        if data[base + 0x7DF8] not in (0, 1, 2):
            raise ValueError("Unknown Brooks display mode")
    result = bytearray(data)
    result[0x7DF9:0x7DFC] = bytes((1, 0, 4))  # first field: AUX $0400
    second = 39168 + 0x7DF9
    result[second:second + 3] = bytes((0, 0, 4))  # second field: MAIN $0400
    return bytes(result)


def import_random(source: Path, count: int = 20) -> None:
    """Choose once; bundle originals and selection metadata for stable rebuilds."""
    candidates = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix.lower() == ".shr":
            try:
                normalize(path.read_bytes())
            except ValueError:
                continue
            candidates.append(path)
    selected = random.SystemRandom().sample(candidates, count)
    ASSETS.mkdir(parents=True, exist_ok=True)
    records, names = [], set()
    for path in selected:
        name = re.sub(r"[^A-Z0-9.]", "", path.stem.upper())[:15]
        if not name or not name[0].isalpha():
            name = "I" + name[:14]
        base, suffix = name, 1
        while name in names:
            tail = f".{suffix}"
            name = base[:15 - len(tail)] + tail
            suffix += 1
        names.add(name)
        original = path.read_bytes()
        shutil.copyfile(path, ASSETS / path.name)
        records.append({"source": path.name, "name": name,
                        "source_sha256": hashlib.sha256(original).hexdigest(),
                        "bytes": len(original)})
    (ASSETS / "selection.json").write_text(json.dumps({
        "source_directory": str(source.resolve()), "eligible_images": len(candidates),
        "selection": "20 distinct images sampled using SystemRandom; fixed for rebuilds",
        "images": records}, indent=2) + "\n")


def images():
    selection = json.loads((ASSETS / "selection.json").read_text())
    for record in selection["images"]:
        path = ASSETS / record["source"]
        original = path.read_bytes()
        assert hashlib.sha256(original).hexdigest() == record["source_sha256"]
        yield path, record["name"], normalize(original)
