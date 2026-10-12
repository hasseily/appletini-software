#!/usr/bin/env python3
"""Read back the native ProDOS release and check provenance and load safety.

This verifier never calls the builder. Filesystem parsing uses the repository's
independent ProDOS reader; comparison is against the original DOS disk, the
runtime master, the emitted driver and the recorded manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from disk_formats import (DEFAULT_MASTER, TYPE_BAS, TYPE_BIN, TYPE_SYS,
                          detokenize_body, parse_basic, read_dos_disk,
                          read_prodos_disk)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "5745a87e1c6dfb9948ce9fa759d27504a22883c2ff0349e195c9370bbd6e238c"
ORIGINAL_NAMES = {
    "DEMO", "PRIMARY ROUTINES", "DEMO1.OBJ", "SPTABLE.OBJ", "PSGTABLE.OBJ",
    "PROCLOOP.OBJ", "SHPTABLE1.OBJ", "SHPTABLE2.OBJ", "DEMO1", "DEMO2",
    "DEMO3", "DEMO4", "THE WORM", "THE LASER", "MULTIPLE TONES",
    "MULTIPLE NOISE1", "MULTIPLE NOISE2", "TITLE PAGE",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def filename(original: str) -> str:
    return "PRIMARY" if original == "PRIMARY ROUTINES" else original.replace(" ", ".")


def verify(image_path: Path, source_path: Path, master_path: Path,
           manifest_path: Path, driver_path: Path) -> dict:
    source_bytes, image = source_path.read_bytes(), image_path.read_bytes()
    require(digest(source_bytes) == SOURCE_SHA256, "original DOS disk hash changed")
    original = {f.name: f for f in read_dos_disk(source_path)}
    require(set(original) == ORIGINAL_NAMES, "original 18-file catalog changed")
    volume, entries = read_prodos_disk(image_path)
    files = {f["name"]: f for f in entries}
    wanted = {filename(n) for n in ORIGINAL_NAMES} | {"PRODOS", "BASIC.SYSTEM", "STARTUP"}
    require(volume == "MOCKINGBOARD", "unexpected ProDOS volume name")
    require(set(files) == wanted and len(entries) == 21, "release must contain all 18 originals plus runtime and STARTUP")
    require(len(image) == 280 * 512, "release is not a 140KB Disk II .po")
    checks = ["source hash and all 18 original files; 21 native ProDOS files"]

    manifest = json.loads(manifest_path.read_text())
    require(manifest["source_sha256"] == digest(source_bytes), "manifest source hash mismatch")
    require(manifest["output_sha256"] == digest(image), "manifest output hash mismatch")
    require(manifest["output"] == image_path.name, "manifest output filename mismatch")
    records = {r["original"]: r for r in manifest["files"]}
    require(set(records) == ORIGINAL_NAMES and len(manifest["files"]) == 18,
            "manifest must cover each original exactly once")
    for old_name, source in original.items():
        name, record = filename(old_name), records[old_name]
        f = files[name]
        require(record["prodos"] == name, f"{name}: manifest rename mismatch")
        require(record["source_sha256"] == digest(source.data), f"{name}: original file hash mismatch")
        require(record["sha256"] == digest(f["data"]), f"{name}: output file hash mismatch")
        require((record["type"], record["aux"], record["length"]) ==
                (f["type"], f["aux"], len(f["data"])), f"{name}: manifest metadata mismatch")

    master_bytes = master_path.read_bytes()
    require(manifest["master_sha256"] == digest(master_bytes), "runtime master hash mismatch")
    _, master_entries = read_prodos_disk(master_path)
    master = {f["name"]: f for f in master_entries}
    for name in ("PRODOS", "BASIC.SYSTEM"):
        require(files[name] == master[name] and files[name]["type"] == TYPE_SYS,
                f"{name}: runtime differs from original master")
    require(image[:1024] == master_bytes[:1024], "native ProDOS boot blocks changed")
    require(files["STARTUP"]["data"] == files["DEMO"]["data"], "STARTUP differs from DEMO")
    require((files["STARTUP"]["type"], files["STARTUP"]["aux"]) == (TYPE_BAS, 0x0801),
            "STARTUP is not an Applesoft program at $0801")
    require([f["name"] for f in entries if f["type"] == TYPE_SYS] == ["PRODOS", "BASIC.SYSTEM"],
            "BASIC.SYSTEM is not the first bootable .SYSTEM program")
    header = 2 * 512 + 4
    total = int.from_bytes(image[header + 37:header + 39], "little")
    bitmap = int.from_bytes(image[header + 35:header + 37], "little") * 512
    used = sum(not bool(image[bitmap + n // 8] & (0x80 >> (n % 8))) for n in range(total))
    require(used == manifest["blocks_used"], "manifest allocation count mismatch")
    checks.append("manifest hashes, original runtime/boot blocks and STARTUP validated")

    sources: dict[str, dict[int, str]] = {}
    for name, f in files.items():
        if f["type"] != TYPE_BAS:
            continue
        require(f["aux"] == 0x0801 and 0x0801 + len(f["data"]) < 0x2000,
                f"{name}: BASIC program overlaps HGR memory")
        lines = parse_basic(f["data"])
        require(f["data"].endswith(b"\0\0"), f"{name}: invalid BASIC end marker")
        decoded = {n: detokenize_body(body) for n, body in lines}
        sources[name] = decoded
        require(re.sub(r"\s+", "", decoded.get(0, "")) == "HIMEM:8192",
                f"{name}: missing HGR-safe BASIC memory limit")
        for number, text in decoded.items():
            for command, target in re.findall(r'"(RUN|BLOAD)\s+([^",]+)(?:[^\"]*)"', text):
                target = target.strip()
                require(target in files, f"{name}:{number}: missing {command} target {target}")
                require(files[target]["type"] == (TYPE_BAS if command == "RUN" else TYPE_BIN),
                        f"{name}:{number}: wrong file type for {command} {target}")
            code = re.sub(r'"[^"]*"', '""', text)
            code = code.split(" REM ", 1)[0]
            for target in re.findall(r"\b(?:GOTO|GOSUB|THEN)\s+(\d+)\b", code):
                require(int(target) in decoded, f"{name}:{number}: nonexistent line {target}")
        # Music and other original DATA statements must retain their contents.
        old_name = next((n for n in original if filename(n) == name), None)
        if old_name and original[old_name].type == 2:
            old_data = [b for _, b in parse_basic(original[old_name].data) if b[:1] == b"\x83"]
            new_data = [b for _, b in lines if b[:1] == b"\x83"]
            require(old_data == new_data, f"{name}: original DATA content changed")
    checks.append("all BASIC links, numeric branches, file targets and $2000 memory limits validated")

    ranges = []
    for old_name, old in original.items():
        if old.type != 4:
            continue
        name, f = filename(old_name), files[filename(old_name)]
        require(f["type"] == TYPE_BIN, f"{name}: binary file type changed")
        wanted_aux = {"SHPTABLE1.OBJ": 0x6000, "SHPTABLE2.OBJ": 0x6100}.get(name, old.load_address)
        require(f["aux"] == wanted_aux, f"{name}: load address changed unexpectedly")
        data = f["data"]
        if name == "PRIMARY":
            require(data[:3] == bytes.fromhex("4C0091"), "PRIMARY init vector is not $9100")
            require(data[3:0x13] == old.data[3:0x13], "PRIMARY changed outside init patch")
            require(data[0x13:0x23] == b"\x60" + b"\xea" * 15, "obsolete speech wait was not removed")
            require(data[0x23:0x50] == old.data[0x23:0x50], "original AY routines changed")
            require(data[0x50:0x100] == bytes(0xB0), "PRIMARY workspace padding is not zeroed")
            require(data[0x100:] == driver_path.read_bytes(), "embedded speech driver differs from assembled binary")
            require(0x9000 + len(data) <= 0x9600, "PRIMARY overlaps BASIC.SYSTEM workspace")
            for offset in (0x100, 0x103):
                require(data[offset] == 0x4C, "driver entry is not a JMP")
                target = int.from_bytes(data[offset + 1:offset + 3], "little")
                require(0x9106 <= target < 0x9000 + len(data), "driver vector points outside its code")
        elif name == "DEMO1.OBJ":
            require(data[:3] == bytes.fromhex("4C0391"), "speech entry does not jump to $9103")
            require(data[3:] == old.data[3:], "DEMO1.OBJ changed outside speech entry patch")
        else:
            require(data == old.data, f"{name}: original binary/table/title bytes changed")
        ranges.append((f["aux"], f["aux"] + len(data), name))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        require(previous[1] <= current[0], f"RAM overlap: {previous[2]} and {current[2]}")
    for low, high, name in ranges:
        require(low >= 0x6000 or (name == "TITLE.PAGE" and (low, high) == (0x4000, 0x6000)),
                f"{name}: loaded over BASIC or HGR page1")
    for name, expected in (("THE.LASER", [96]), ("THE.WORM", [97, 96])):
        values = [int(v) for text in sources[name].values()
                  for v in re.findall(r"\bPOKE\s+233\s*,\s*(\d+)", text)]
        require(values == expected, f"{name}: shape-table high-byte pointers are wrong")
    checks.append("original sound/speech tables, AY code, shapes and title bytes preserved")
    checks.append("patched entry vectors, shape relocation and resident memory ranges validated")
    return {"image": image_path.name, "sha256": digest(image), "files": len(files),
            "blocks_used": used, "checks": checks,
            "resident_ranges": [{"name": n, "start": f"${a:04X}", "end_exclusive": f"${b:04X}"}
                                for a, b, n in ranges]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=ROOT / "Mockingboard_IIplus_IIe.po")
    parser.add_argument("--source", type=Path, default=ROOT / "Sound_and_Speech_I_Demo_Disk__1982.dsk")
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--manifest", type=Path, default=ROOT / "build-manifest.json")
    parser.add_argument("--driver", type=Path, default=ROOT / "build/speech.bin")
    parser.add_argument("--report", type=Path, default=ROOT / "build/verify_disk.json")
    args = parser.parse_args()
    report = verify(args.image, args.source, args.master, args.manifest, args.driver)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    for check in report["checks"]:
        print("PASS " + check)
    print(f"Verified {report['files']} files; SHA256 {report['sha256']}")


if __name__ == "__main__":
    main()
