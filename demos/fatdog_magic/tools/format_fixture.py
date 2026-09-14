"""Build a separate test disk from the demo loader's real image corpus."""
from pathlib import Path
import json

import build_fatdog_magic_disk as build
from prodos import create_folder, raw_files, verify_allocation


def image_directories(source: Path):
    """Accept a software checkout, demo project/assets, or legacy firmware checkout."""
    for assets in (source / "demos/appletini_demos/assets", source / "assets",
                   source, source / "software"):
        legacy, shr = assets / "legacy_demo_images", assets / "shr4_demo_images"
        if legacy.is_dir() and shr.is_dir():
            return legacy, shr
    raise FileNotFoundError(
        f"No Appletini demo image corpus under {source}; provide the "
        "appletini-software checkout, demos/appletini_demos project or assets "
        "directory, or a legacy appletini-one checkout")


def make_format_fixture(appletini: Path, gallery: Path, output: Path):
    legacy, shr = image_directories(appletini)
    hgr = next(iter(raw_files(build.DEMO / "assets/fgr1.po").values()))
    eye = (legacy / "eye.hgri").read_bytes()
    face = (legacy / "face.dhri").read_bytes()
    car = (shr / "cartest.shr4i").read_bytes()
    hgrp, dhrp, shrp = bytearray(eye), bytearray(face), bytearray(car)
    hgrp[0x207C] = 2
    dhrp[0x607C] = 2
    shrp[0x7DF8] = shrp[0xFDF8] = 2
    # Deliberately mix types inside one arbitrarily named folder, and put a
    # single-page SHR after a pair to catch stale MAIN-bank control metadata.
    records = [
        ("HGR", hgr, 1),
        ("HGR.INTERLACE", eye, 2),
        ("HGR.FLIP", bytes(hgrp), 2),
        ("DHGR", (legacy / "logo6.dhr").read_bytes(), 3),
        ("DHGR.INTERLACE", face, 4),
        ("DHGR.FLIP", bytes(dhrp), 4),
        ("SHR4.INTERLACE", car, 0),
        ("SHR4", (shr / "gridtest.shr4").read_bytes(), 0),
        ("RGGB", (shr / "eye320.shr4").read_bytes(), 0),
        ("PAL256", (shr / "observatory.pal256").read_bytes(), 0),
        ("COLORS.3200", (shr / "beach.3200").read_bytes(), 0),
        ("PAL256.INT", (shr / "skycity.pal256i").read_bytes(), 0),
        ("SHR.FLIP", bytes(shrp), 0),
        ("HGR.RETURN", hgr, 1),
    ]
    output.parent.mkdir(exist_ok=True)
    output.unlink(missing_ok=True)
    build.ac("-pro800", output, "FATDOG.TEST")
    disk = bytearray(output.read_bytes())
    disk[:1024] = build.MASTER.read_bytes()[:1024]
    output.write_bytes(disk)
    system = raw_files(gallery)
    for name in ("PRODOS", "MAGIC.SYSTEM", "BASIC.SYSTEM"):
        build.ac("-p", output, name, "SYS", "0x2000", data=system[name])
    create_folder(output, "Standard.HGR")
    create_folder(output, "Mixed.Images")
    create_folder(output, "DHGR.MIX")
    build.ac("-p", output, "STANDARD.HGR/ORIGINAL", "BIN", "0x4000", data=hgr)
    for name, payload, _ in records:
        build.ac("-p", output, "MIXED.IMAGES/" + name, "BIN", "0x2000", data=payload)
    build.ac("-p", output, "DHGR.MIX/FACE", "BIN", "0x2000", data=face)
    verify_allocation(output)
    files = raw_files(output)
    for name, payload, _ in records:
        assert files["MIXED.IMAGES/" + name] == payload
    (output.parent / "format-inputs.json").write_text(json.dumps([
        {"name": name, "bytes": len(payload), "sha256": build.digest(payload), "format": fmt}
        for name, payload, fmt in records], indent=2) + "\n")
    return records
