#!/usr/bin/env python3
"""Build/run the repository's Appletini machine without modifying its sources.

The machine is appletini-software's development runner (tools/appletini) and
a2vm (demos/doom_gs/tools/a2vm), one directory above libtini.

Example: python tools/native_emulator.py --cc C:/msys64/ucrt64/bin/gcc.exe
         run --disk build/libtini.po --system LIBTINI.SYSTEM --profile vtw33
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FRONT = REPO / "tools/appletini"
CORE = REPO / "demos/doom_gs/tools/a2vm"
OUT = ROOT / "build/native"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_revision():
    """The repository commit of the machine sources, marked if they have local changes."""
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode:
        return None
    changed = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", str(FRONT), str(CORE)],
                             capture_output=True, text=True, check=True).stdout.strip()
    return head.stdout.strip() + ("+local-changes" if changed else "")


def build(compiler, rebuild=False):
    compiler = Path(compiler).resolve()
    sources = [FRONT / name for name in
               ("native.c", "cards.c", "audio.c", "speech_state.c")]
    sources += [CORE / name for name in ("a2vm.c", "cost.c", "prodos.c", "cpu65c02.c")]
    inputs = sources + sorted(FRONT.glob("*.h")) + sorted(CORE.glob("*.h"))
    hashes = {p.relative_to(REPO).as_posix(): digest(p) for p in inputs}
    hashes["compiler"] = digest(compiler)
    OUT.mkdir(parents=True, exist_ok=True)
    library = OUT / ("libappletini.dll" if os.name == "nt" else "libappletini.so")
    manifest = OUT / "build.json"
    if not rebuild and library.is_file() and manifest.is_file():
        previous = json.loads(manifest.read_text())
        if previous["input_sha256"] == hashes and previous["output_sha256"] == digest(library):
            return library
    command = [str(compiler), "-O2", "-std=c11", "-shared", "-static-libgcc"]
    if os.name != "nt":
        command.append("-fPIC")
    command += ["-I", str(CORE), *map(str, sources), "-lm", "-o", str(library)]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")
    subprocess.run(command, check=True, cwd=ROOT, env=env)
    version = subprocess.run([str(compiler), "--version"], capture_output=True,
                             text=True, check=True, env=env).stdout.splitlines()[0]
    manifest.write_text(json.dumps({"input_sha256": hashes, "compiler_version": version,
                                   "command": command, "output_sha256": digest(library)},
                                  indent=2) + "\n")
    return library


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cc", default=os.environ.get("NATIVE_CC") or shutil.which("gcc"))
    parser.add_argument("--rebuild", action="store_true")
    args, remainder = parser.parse_known_args()
    if not args.cc:
        raise SystemExit("Pass --cc <installed GCC executable> or set NATIVE_CC")
    # The runner's speech client builds its worker inside tools/appletini, so
    # this wrapper keeps audio off. tests/web_validate.py builds the worker in
    # build/native. The C machine still models sound/speech registers and IRQs.
    if "--audio" in remainder or "--wav" in remainder:
        raise SystemExit("This wrapper runs the machine without audio synthesis")
    if "play" in remainder and "--no-audio" not in remainder:
        remainder.append("--no-audio")
    if "--boot" in remainder:
        for flag in ("--rom", "--slot7-rom", "--slot7-c8-rom"):
            if flag not in remainder:
                raise SystemExit("Boot requires explicit repo-local ROM inputs: " + flag)
            value = Path(remainder[remainder.index(flag) + 1]).resolve()
            if not value.is_relative_to(ROOT):
                raise SystemExit("Copy required boot ROMs into build-inputs before use: " + flag)
    library = build(args.cc, args.rebuild)
    if remainder == ["build"]:
        print(library)
        return 0
    sys.path.insert(0, str(FRONT))
    import cli
    # Build integration only: the original Unix makefile cannot produce a
    # native Windows DLL. No CPU, device, timing or rendering code is patched.
    cli.build_library = lambda: library
    return cli.main(remainder)


if __name__ == "__main__":
    raise SystemExit(main())
