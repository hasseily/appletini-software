#!/usr/bin/env python3
"""Build and byte-verify the bootable 800K ProDOS FATDOG HGR gallery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

DEMO = Path(__file__).resolve().parents[1]
WORK = DEMO / "build"
MASTER = DEMO / "assets" / "ProDOS_2_4_3.po"
JAR = Path(os.environ.get("APPLECOMMANDER", os.environ.get("APPLECOMMANDER_JAR",
    str(Path.home() / "tools" / "AppleCommander-ac-13.0.jar"))))


def ac(*args: object, data: bytes | None = None) -> bytes:
    return subprocess.run(["java", "-jar", str(JAR), *map(str, args)],
                          input=data, capture_output=True, check=True).stdout


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def catalog(path: Path) -> list[dict]:
    return json.loads(ac("-llj", path))["disks"][0]["files"]


def raw_files(path: Path) -> dict[str, bytes]:
    """Independent root-directory reader for seedling/sapling verification."""
    disk = path.read_bytes()
    result = {}
    block = 2
    visited = set()
    while block:
        assert block not in visited, "Directory loop"
        visited.add(block)
        directory = disk[block * 512:(block + 1) * 512]
        for slot in range(13):
            e = directory[4 + slot * 39:4 + (slot + 1) * 39]
            storage, size = e[0] >> 4, e[0] & 15
            if storage in (0, 15):
                continue
            name = e[1:1 + size].decode("ascii")
            key = int.from_bytes(e[17:19], "little")
            eof = int.from_bytes(e[21:24], "little")
            if storage == 1:
                payload = disk[key * 512:(key + 1) * 512]
            elif storage == 2:
                index = disk[key * 512:(key + 1) * 512]
                payload = bytearray()
                for i in range((eof + 511) // 512):
                    data_block = index[i] | index[256 + i] << 8
                    payload.extend(disk[data_block * 512:(data_block + 1) * 512]
                                   if data_block else bytes(512))
            else:
                raise ValueError(f"Unexpected storage type {storage}: {name}")
            result[name] = bytes(payload[:eof])
        block = int.from_bytes(directory[2:4], "little")
    return result


def verify_allocation(path: Path) -> None:
    """Check every allocated block and root entry against the volume bitmap."""
    disk = path.read_bytes()
    total = struct.unpack_from("<H", disk, 0x429)[0]
    bitmap = struct.unpack_from("<H", disk, 0x427)[0]
    assert total * 512 == len(disk)
    used = {0, 1, *range(bitmap, bitmap + (total + 4095) // 4096)}

    def claim(block: int) -> None:
        assert 0 <= block < total and block not in used, f"Invalid/shared block: {block}"
        used.add(block)

    block, previous, count = 2, 0, 0
    while block:
        claim(block)
        directory = disk[block * 512:(block + 1) * 512]
        assert int.from_bytes(directory[:2], "little") == previous
        for slot in range(13):
            e = directory[4 + slot * 39:4 + (slot + 1) * 39]
            storage = e[0] >> 4
            if storage in (0, 15):
                continue
            count += 1
            key = int.from_bytes(e[17:19], "little")
            eof = int.from_bytes(e[21:24], "little")
            claim(key)
            blocks_used = 1
            if storage == 2:
                index = disk[key * 512:(key + 1) * 512]
                for i in range((eof + 511) // 512):
                    data_block = index[i] | index[256 + i] << 8
                    if data_block:
                        claim(data_block)
                        blocks_used += 1
            else:
                assert storage == 1
            assert blocks_used == int.from_bytes(e[19:21], "little")
        previous, block = block, int.from_bytes(directory[2:4], "little")
    assert count == struct.unpack_from("<H", disk, 0x425)[0]
    for block in range(total):
        free = bool(disk[bitmap * 512 + block // 8] & (0x80 >> (block & 7)))
        assert free == (block not in used), f"Bitmap mismatch: {block}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path,
                        default=[DEMO / "assets" / "fgr1.po",
                                 DEMO / "assets" / "fgr2.po"])
    parser.add_argument("--output", type=Path,
                        default=DEMO / "dist" / "FATDOG_HGR.po")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    images = []
    names = set()
    for source in args.inputs:
        files = raw_files(source)
        for entry in catalog(source):
            name = entry["name"]
            payload = ac("-g", source, name)
            assert entry["type"] == "BIN" and len(payload) == 8192, name
            assert payload == files[name], f"Independent input read differs: {name}"
            assert name not in names, f"Duplicate filename: {name}"
            names.add(name)
            images.append((source, name, payload))
    assert 0 < len(images) < 256
    table = [f"image_count = {len(images)}", "names_lo:",
             "    !byte " + ",".join(f"<name{i}" for i in range(len(images))),
             "names_hi:",
             "    !byte " + ",".join(f">name{i}" for i in range(len(images)))]
    table += [f'name{i}: !byte {len(n)} : !text "{n}"'
              for i, (_, n, _) in enumerate(images)]
    (WORK / "images.inc").write_text("\n".join(table) + "\n", encoding="ascii")
    screen = bytearray([0xA0] * 1024)
    lines = {
        1: "          FATDOG HGR GALLERY",
        3: f"       {len(images)} APPLE II HGR IMAGES",
        5: "       HGR CONVERSIONS BY FATDOG",
        7: "  ORIGINAL ARTWORK BY ITS CREATORS.",
        11: "  LEFT / P       PREVIOUS IMAGE",
        12: "  RIGHT / N      NEXT IMAGE",
        13: "  SPACE          PAUSE / RESUME",
        14: "  R              FIRST IMAGE",
        15: "  H              HELP / IMAGE NAME",
        16: "  ESC            QUIT TO PRODOS",
        17: "NOW: ",
        19: "MODE:  AUTO    (480 FRAMES PER IMAGE)",
        21: "  PRESS ANY KEY TO VIEW THE IMAGES.",
        23: " SLIDESHOW STARTS AUTOMATICALLY SHORTLY."
    }
    for row, line in lines.items():
        assert len(line) <= 40
        offset = (row & 7) * 128 + (row >> 3) * 40
        screen[offset:offset + len(line)] = bytes(c | 128 for c in line.encode("ascii"))
    (WORK / "help.bin").write_bytes(screen)
    shutil.copyfile(DEMO / "gallery.a65", WORK / "gallery.a65")
    assembler = os.environ.get("ACME_EXE") or shutil.which("acme")
    if assembler is None:
        raise RuntimeError("ACME not found: set ACME_EXE or add acme to PATH")
    subprocess.run([assembler, "-f", "plain", "--symbollist", "gallery.sym",
                    "-o", "GALLERY.SYSTEM", "gallery.a65"], cwd=WORK, check=True)
    program = (WORK / "GALLERY.SYSTEM").read_bytes()
    assert len(program) <= 8192
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".tmp" + output.suffix)
    temporary.unlink(missing_ok=True)
    ac("-pro800", temporary, "FATDOG.HGR")
    # Keep the native 1600-block 3.5-inch geometry from AppleCommander.
    disk = bytearray(temporary.read_bytes())
    assert len(disk) == 800 * 1024
    assert struct.unpack_from("<H", disk, 0x429)[0] == 1600
    disk[:1024] = MASTER.read_bytes()[:1024]
    temporary.write_bytes(disk)
    expected = {}
    for name in ("PRODOS", "GALLERY.SYSTEM", "BASIC.SYSTEM"):
        data = program if name == "GALLERY.SYSTEM" else ac("-g", MASTER, name)
        ac("-p", temporary, name, "SYS", "0x2000" if name == "GALLERY.SYSTEM" else "0", data=data)
        expected[name] = data
    for _, name, payload in images:
        ac("-p", temporary, name, "BIN", "0x4000", data=payload)
        expected[name] = payload
    readme = (DEMO / "README.md").read_text(encoding="utf-8")
    ac("-ptx", temporary, "README", data=readme.encode("ascii"))
    embedded = raw_files(temporary)
    for name, payload in expected.items():
        assert embedded[name] == payload, f"Output differs: {name}"
    listing = catalog(temporary)
    systems = [e["name"] for e in listing if e["type"] == "SYS" and e["name"].endswith(".SYSTEM")]
    assert systems[0] == "GALLERY.SYSTEM"
    assert temporary.stat().st_size == 800 * 1024
    assert temporary.read_bytes()[:1024] == MASTER.read_bytes()[:1024]
    verify_allocation(temporary)
    os.replace(temporary, output)
    manifest = {
        "output": str(output), "bytes": output.stat().st_size,
        "format": "ProDOS block order (.po), 800K 3.5-inch disk",
        "blocks": 1600,
        "sha256": digest(output.read_bytes()), "image_count": len(images),
        "credit": "HGR conversions by FATDOG. Original artwork by its original creators.",
        "boot_system": systems[0], "viewer_sha256": digest(program),
        "sources": [{"path": str(p.resolve()), "sha256": digest(p.read_bytes())} for p in args.inputs],
        "images": [{"source": p.name, "name": n, "bytes": len(b), "sha256": digest(b)} for p, n, b in images],
        "verification": f"All {len(images)} images and system files read independently and compared byte-for-byte; allocation bitmap and boot order verified."
    }
    (output.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {output}: {len(images)} intact HGR images, {len(program)}-byte viewer")
    print(f"SHA-256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
