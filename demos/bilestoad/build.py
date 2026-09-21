#!/usr/bin/env python3
"""Build the Bilestoad SHR port: dist/Bilestoad.po.

Usage:  python build.py [--upstream DIR] [--master PRODOS_IMAGE]

The upstream game (source and shape data) is not part of this repository.
The build reads it from a local clone of
https://github.com/historicalsource/bilestoad-apple2 and converts it. If no
clone is given, the script makes one in build/upstream at a pinned commit.

Needs: Python 3 with Pillow, ca65 and ld65 (cc65), git for the first clone.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
UPSTREAM_URL = "https://github.com/historicalsource/bilestoad-apple2"
UPSTREAM_COMMIT = ""            # empty = default branch head
DEFAULT_MASTER = ROOT.parents[2] / "appletini-one/software/ProDOS_2_4_3.po"

sys.path.insert(0, str(ROOT / "tools"))
import prodos  # noqa: E402


def run(*command, cwd=ROOT):
    printable = " ".join(str(part) for part in command)
    print("+", printable)
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def tool(name):
    prefix = os.environ.get("CC65_PREFIX", "")
    found = shutil.which(prefix + name)
    if not found:
        raise SystemExit("%s not found; install cc65 or set CC65_PREFIX" % name)
    return found


def upstream_dir(given):
    if given:
        return Path(given).resolve()
    if os.environ.get("BILESTOAD_UPSTREAM"):
        return Path(os.environ["BILESTOAD_UPSTREAM"]).resolve()
    target = BUILD / "upstream"
    if not target.exists():
        run("git", "clone", UPSTREAM_URL, target)
        if UPSTREAM_COMMIT:
            run("git", "checkout", UPSTREAM_COMMIT, cwd=target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--upstream", help="clone of the upstream repository")
    parser.add_argument("--master", default=str(DEFAULT_MASTER),
                        help="ProDOS image that supplies PRODOS and the "
                             "boot blocks")
    args = parser.parse_args()
    python = sys.executable
    upstream = upstream_dir(args.upstream)
    port, art = BUILD / "port", BUILD / "art"
    port.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)

    run(python, "tools/lisa.py", upstream, "--self-test")
    run(python, "tools/lisa2ca65.py", upstream, "--drops", "src/drops.json",
        "--output", port / "game.s")
    run(python, "tools/convert_sprites.py", upstream, "--output-dir", art)
    run(python, "tools/make_music.py", "--output", port / "music.inc")
    run(python, "tools/shapedata.py", upstream, "--joint-tables",
        port / "joint_tables.inc")

    run(tool("ca65"), "-g", "--cpu", "65C02", "-I", port, "-I", art,
        "-I", "src", "-o", port / "main.o", "-l", port / "main.lst",
        "src/main.s")
    system = port / "BILESTOAD.SYSTEM"
    run(tool("ld65"), "-C", "src/bilestoad.cfg", "-m", port / "main.map",
        "-Ln", port / "main.lbl", "-o", system, port / "main.o")

    master = Path(args.master)
    if not master.exists():
        raise SystemExit("ProDOS master image not found: %s" % master)
    files = [
        ("PRODOS", prodos.TYPE_SYS, 0x0000,
         prodos.read_file(master, "PRODOS")),
        # A ProDOS name holds 15 characters at most.
        ("TOAD.SYSTEM", prodos.TYPE_SYS, 0x2000, system.read_bytes()),
        ("BILESTOAD.SPR", prodos.TYPE_BIN, 0x1000,
         (art / "sprites.bin").read_bytes()),
    ]
    image = DIST / "Bilestoad.po"
    used = prodos.build_image(image, "BILESTOAD", master, files)
    print("%s: %d bytes, %d blocks used; system file %d bytes" %
          (image, image.stat().st_size, used, system.stat().st_size))


if __name__ == "__main__":
    main()
