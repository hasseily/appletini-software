#!/usr/bin/env python3
"""Build and byte-verify the bootable 32 MB ProDOS FATDOG MAGIC disk."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from prodos import raw_files, verify_allocation, create_folder, expand_empty_volume
import brooks

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


def build_hgr_assets() -> None:
    """Use the demo disk's bundled 7x8 font, with a FATDOG title."""
    font = (DEMO / "assets/font7x8.bin").read_bytes()
    assert len(font) == 96 * 8
    (WORK / "font7x8.bin").write_bytes(font)
    logo = bytearray(24 * 40)
    title, scale = "FATDOG MAGIC", 3
    xoff = (280 - len(title) * 7 * scale) // 2
    for ci, ch in enumerate(title):
        for y in range(8):
            glyph = font[(ord(ch) - 32) * 8 + y]
            for x in range(7):
                if glyph & (1 << x):
                    for sy in range(scale):
                        for sx in range(scale):
                            px = xoff + (ci * 7 + x) * scale + sx
                            logo[(y * scale + sy) * 40 + px // 7] |= 1 << (px % 7)
    (WORK / "logo.bin").write_bytes(logo)
    rows = [(y & 7) * 0x400 + ((y >> 3) & 7) * 0x80 + (y >> 6) * 0x28
            for y in range(192)]
    (WORK / "hgr.inc").write_text(
        "hgr_lo: !byte " + ",".join(str(a & 255) for a in rows) + "\n" +
        "hgr_hi: !byte " + ",".join(str(a >> 8) for a in rows) + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path,
                        default=[DEMO / "assets" / "fgr1.po",
                                 DEMO / "assets" / "fgr2.po"])
    parser.add_argument("--output", type=Path,
                        default=DEMO / "dist" / "FATDOG_MAGIC.po")
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
    brooks_images = list(brooks.images())
    assert len(brooks_images) == 20
    build_hgr_assets()
    for source in ("magic.a65", "directories.a65", "formats.a65", "palettes.a65", "ui.a65"):
        shutil.copyfile(DEMO / source, WORK / source)
    assembler = os.environ.get("ACME_EXE") or shutil.which("acme")
    if assembler is None:
        raise RuntimeError("ACME not found: set ACME_EXE or add acme to PATH")
    subprocess.run([assembler, "-f", "plain", "--symbollist", "magic.sym",
                    "-o", "MAGIC.SYSTEM", "magic.a65"], cwd=WORK, check=True)
    program = (WORK / "MAGIC.SYSTEM").read_bytes()
    assert len(program) <= 6912  # runtime code must end before the $BB00 MLI buffer
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".tmp" + output.suffix)
    temporary.unlink(missing_ok=True)
    ac("-pro800", temporary, "FATDOG.MAGIC")
    expand_empty_volume(temporary)
    disk = bytearray(temporary.read_bytes())
    assert len(disk) == 32 * 1024 * 1024
    assert struct.unpack_from("<H", disk, 0x429)[0] == 65535
    disk[:1024] = MASTER.read_bytes()[:1024]
    temporary.write_bytes(disk)
    expected = {}
    for name in ("PRODOS", "MAGIC.SYSTEM", "BASIC.SYSTEM"):
        data = program if name == "MAGIC.SYSTEM" else ac("-g", MASTER, name)
        ac("-p", temporary, name, "SYS", "0x2000" if name == "MAGIC.SYSTEM" else "0", data=data)
        expected[name] = data
    create_folder(temporary, "Standard.HGR")
    for _, name, payload in images:
        name = "STANDARD.HGR/" + name
        ac("-p", temporary, name, "BIN", "0x4000", data=payload)
        expected[name] = payload
    create_folder(temporary, "Brooks.SHR.3200")
    for _, name, payload in brooks_images:
        name = "BROOKS.SHR.3200/" + name
        ac("-p", temporary, name, "BIN", "0x2000", data=payload)
        expected[name] = payload
    readme = (DEMO / "README.md").read_text(encoding="utf-8")
    ac("-ptx", temporary, "README", data=readme.encode("ascii"))
    embedded = raw_files(temporary)
    for name, payload in expected.items():
        assert embedded[name] == payload, f"Output differs: {name}"
    listing = catalog(temporary)
    systems = [e["name"] for e in listing if e["type"] == "SYS" and e["name"].endswith(".SYSTEM")]
    assert systems[0] == "MAGIC.SYSTEM"
    assert temporary.stat().st_size == 32 * 1024 * 1024
    assert temporary.read_bytes()[:1024] == MASTER.read_bytes()[:1024]
    verify_allocation(temporary)
    os.replace(temporary, output)
    manifest = {
        "output": str(output), "bytes": output.stat().st_size,
        "format": "ProDOS block order (.po), 32 MB SmartPort volume",
        "blocks": 65535, "physical_blocks": 65536,
        "sha256": digest(output.read_bytes()), "image_count": len(images) + len(brooks_images),
        "credit": "Conversions by FATDOG - Code by RIKKLES. Original artwork by its creators.",
        "boot_system": systems[0], "viewer_sha256": digest(program),
        "sources": [{"path": str(p.resolve()), "sha256": digest(p.read_bytes())} for p in args.inputs],
        "folders": [{"path": "STANDARD.HGR", "label": "Standard HGR"},
                    {"path": "BROOKS.SHR.3200", "label": "Brooks SHR-3200"}],
        "images": [{"source": p.name, "name": n, "path": folder + "/" + n,
                    "bytes": len(b), "sha256": digest(b)}
                   for folder, group in (("STANDARD.HGR", images), ("BROOKS.SHR.3200", brooks_images))
                   for p, n, b in group],
        "brooks_import": {"selection": "assets/brooks_shr/selection.json",
                          "normalization": "Preserve both fields and all palettes; first palette AUX 0400, second MAIN 0400; temporary LINTXT capture only during CPU palette copies"},
        "verification": "All 52 images and system files read independently and compared byte-for-byte; allocation bitmap and boot order verified."
    }
    (output.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {output}: {len(images)} HGR + {len(brooks_images)} Brooks images, {len(program)}-byte viewer")
    print(f"SHA-256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
