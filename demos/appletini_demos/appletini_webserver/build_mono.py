#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the mono DHGRi browser, relocation SYS and standalone ProDOS disk."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

from mono_disk import build_disk

ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = ROOT.parent / "assets" / "AD8088 MSDOS.hdv"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, check=True)


def data_fork(container: bytes) -> tuple[bytes, int]:
    if container[:8] != bytes.fromhex("0005160000020000"):
        raise ValueError("expected cc65 AppleSingle v2 output")
    count = int.from_bytes(container[24:26], "big")
    payload, address = None, None
    for i in range(count):
        kind, offset, length = struct.unpack_from(">III", container, 26 + i * 12)
        if offset + length > len(container):
            raise ValueError("AppleSingle entry exceeds file")
        if kind == 1:
            payload = container[offset:offset + length]
        elif kind == 11:
            access, filetype, address = struct.unpack_from(">HHI", container, offset)
            if filetype != 0xFF:
                raise ValueError("expected ProDOS SYS payload")
    if payload is None or address is None:
        raise ValueError("missing AppleSingle data fork or ProDOS metadata")
    return payload, address


def applesingle(payload: bytes, address: int) -> bytes:
    return (bytes.fromhex("0005160000020000") + bytes(16) +
            struct.pack(">HIIIIIIHHI", 2, 1, 58, len(payload),
                        11, 50, 8, 0xC3, 0xFF, address) + payload)


def tool(name: str) -> str:
    override = os.environ.get(name.upper())
    path = override or shutil.which(name)
    if not path:
        raise SystemExit("Install cc65 and put " + name + " on PATH")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "mono")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--no-disk", action="store_true")
    parser.add_argument("--define", action="append", default=[])
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = ["mono_entry.c", "mono_browser.c", "mono_document.c", "mono_http.c", "mono_net.c", "mono_net_buffer.s", "mono_mobile.c", "mono_media.c",
               "mono_image.c", "mono_png.c", "mono_jpeg.c", "third_party/picojpeg/picojpeg.c", "mono_gfx.c",
               "mono_gfx.s", "mono_overlay.s", "mono_mouse.s", "http_client/net.c", "http_client/net.s"]
    config = (ROOT / "mono-system.cfg").read_text(encoding="ascii")
    overlays = ["MONO.WEB", "MONO.GIF", "MONO.PNG", "MONO.JPG", "MONO.NET"]
    for name in overlays:
        config = config.replace("@" + name + "@", (out / name).as_posix())
    generated_cfg = out / "mono-system.cfg"
    generated_cfg.write_text(config, encoding="ascii")
    payload_file = out / "A2MONO.payload.as"
    objects = []
    for source in sources:
        path = Path(source)
        obj = out / (source.replace("/", "_").replace(".", "_") + ".o")
        command = [tool("cl65"), "-t", "apple2", "--cpu", "6502", "-c",
                   "-Os", "--warnings-as-errors", "-I", "http_client", "-o", str(obj)]
        # Browser functions never recurse or run from interrupts/callbacks.
        # Static locals trade spare base BSS for the constrained WEB overlay.
        if source == "mono_browser.c":
            command.append("--static-locals")
        if source == "http_client/net.c":
            command += ["-D", "MONO_NET_OVERLAY"]
        elif source == "http_client/net.s":
            command += ["--asm-define", "MONO_NET_OVERLAY"]
        for define in args.define:
            command += ["-D", define]
        run(command + [source])
        objects.append(str(obj))
    run([tool("cl65"), "-t", "apple2", "--cpu", "6502", "-C", str(generated_cfg),
         "-m", str(out / "A2MONO.map"), "-Ln", str(out / "A2MONO.lbl"),
         "-o", str(payload_file), *objects])
    payload, address = data_fork(payload_file.read_bytes())
    if address != 0x6000 or not payload or len(payload) > 0x5700:
        raise SystemExit("initial payload does not fit the checked $6000-$B6FF staging region")
    symbols = {}
    for line in (out / "A2MONO.lbl").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "al":
            symbols[fields[2].lstrip(".")] = int(fields[1], 16)
    if symbols["__ONCE_RUN__"] > 0x8B00:
        raise SystemExit("permanent resident code/data overlaps the $8B00 overlay")
    (out / "A2MONO.payload.bin").write_bytes(payload)
    loader_cfg = out / "loader.cfg"
    loader_cfg.write_text('MEMORY { MAIN: start=$2000, size=$9F00, file=%O; }\n'
                          'SEGMENTS { CODE: load=MAIN, type=rw; }\n', encoding="ascii")
    run([tool("ca65"), "--cpu", "6502", "-D", f"PAYLOAD_SIZE={len(payload)}",
         "--bin-include-dir", str(out), "-o", str(out / "loader.o"), "mono_loader.s"])
    raw_file = out / "A2MONO.bin"
    run([tool("ld65"), "-C", str(loader_cfg), "-o", str(raw_file),
         "-Ln", str(out / "loader.lbl"), str(out / "loader.o")])
    raw = raw_file.read_bytes()
    if len(raw) > 0x9F00:
        raise SystemExit("relocation SYS exceeds the ProDOS load region")
    (out / "A2MONO.SYSTEM").write_bytes(applesingle(raw, 0x2000))
    overlay_files = []
    for name in overlays:
        path = out / name
        if path.is_file() and path.stat().st_size:
            if path.stat().st_size > 0x2C00:
                raise SystemExit(name + " exceeds its $8B00-$B6FF overlay window")
            overlay_files.append((name, path.read_bytes()))
    names = ["A2MONO.SYSTEM", *(name for name, data in overlay_files)]
    https_out=out/'HTTPS'
    https_out.mkdir(exist_ok=True)
    for name in ('ATNETCA.PEM','roots.json','LICENSE-roots.txt','README.md'):
        shutil.copyfile(ROOT/'https'/name,https_out/name)
        names.append('HTTPS/'+name)
    if not args.no_disk:
        disk = build_disk(args.template.read_bytes(), raw, overlay_files)
        (out / "A2MONO.po").write_bytes(disk)
        names.append("A2MONO.po")
    manifest = {"entry": "0x2000", "payload_entry": "0x6000",
                "payload_bytes": len(payload), "sys_bytes": len(raw),
                "resident_end": hex(symbols["__ONCE_RUN__"]),
                "overlay_address": "0x8b00",
                "files": {name: {"bytes": (out / name).stat().st_size,
                                  "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest()}
                          for name in names}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(out / "A2MONO.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names + ["manifest.json"]:
            info = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (out / name).read_bytes())
        for name in ("README_MONO.md", "LICENSE_MONO.txt",
                     "evidence/board-session-recovery.json",
                     "third_party/picojpeg/SOURCE.txt", "third_party/picojpeg/picojpeg.c",
                     "third_party/picojpeg/picojpeg.h"):
            info = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / name).read_bytes())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
