#!/usr/bin/env python3
"""Build a game's browser player: the repository's Appletini machine in WebAssembly.

Example: python tools/web.py --emsdk D:/Repos/emsdk --game starfall

Build the game's disk first with tools/build.py. By default the player loads
the disk's files through the machine's ProDOS MLI stand-in, and the ProDOS
image is not copied. With --boot-roms it boots the whole disk through the
installed //e ROM and slot-7 firmware. Output: build/web/<game>/, a static
page with source.zip, the player's GPL-3.0 source. See docs/reference/browser.html.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FRONT = REPO / "tools/appletini"
CORE = REPO / "demos/doom_gs/tools/a2vm"
SPEECH = FRONT / "speech"
WEB = ROOT / "tools/web"
OUT = ROOT / "build/web"
EMSCRIPTEN_VERSION = "6.0.13"
COST_PROFILE = "f122+nod2+phasor"
C_SOURCES = [FRONT / name for name in ("native.c", "cards.c", "audio.c", "speech_state.c")]
C_SOURCES += [CORE / name for name in ("a2vm.c", "cost.c", "prodos.c", "cpu65c02.c")]
CXX_SOURCES = [WEB / "player.cpp"]
CXX_SOURCES += [SPEECH / "reference" / name for name in
                ("native_control.cpp", "native_source.cpp", "prototype_tract.cpp")]
PAGE = ("index.html", "main.js", "speech.js", "worklet.js")
EXPORTS = ("tw_create", "tw_volume", "tw_file", "tw_launch", "tw_boot", "tw_run", "tw_result",
           "tw_error",
           "tw_halt", "tw_get", "tw_input", "tw_read", "tw_audio_frames", "tw_audio_data",
           "tw_event_count", "tw_event_data", "tw_audio_take", "tw_speech_start",
           "tw_speech_render", "tw_screen", "malloc", "free")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def tools(emsdk):
    root = Path(emsdk).resolve() / "upstream/emscripten"
    suffix = ".exe" if os.name == "nt" else ""
    emcc, empp = root / ("emcc" + suffix), root / ("em++" + suffix)
    if not emcc.is_file() or not empp.is_file():
        raise SystemExit(f"No emcc under {root}; install Emscripten {EMSCRIPTEN_VERSION} with emsdk")
    version = subprocess.run([str(emcc), "--version"], capture_output=True, text=True,
                             check=True).stdout.splitlines()[0]
    if f" {EMSCRIPTEN_VERSION} " not in version:
        raise SystemExit(f"Emscripten {EMSCRIPTEN_VERSION} is required; found: {version}")
    return emcc, empp, version


def build_player(emsdk, rebuild=False):
    """Compile the game-independent player into build/web/player/."""
    emcc, empp, version = tools(emsdk)
    player = OUT / "player"
    objects = OUT / "obj"
    cost = objects / "turbo-f122.cost"
    costs = module("appletini_costs", CORE / "costs.py")
    inputs = C_SOURCES + CXX_SOURCES + sorted(FRONT.glob("*.h")) + sorted(CORE.glob("*.h"))
    inputs += sorted(SPEECH.glob("**/*.h")) + [SPEECH / "worker.cpp", SPEECH / "reference/rom.inc",
                                               CORE / "costs.py", CORE / "costs/appletini.json"]
    hashes = {p.relative_to(REPO).as_posix(): digest(p) for p in inputs}
    manifest = player / "build.json"
    outputs = [player / "player.js", player / "player.wasm"]
    if not rebuild and manifest.is_file() and all(p.is_file() for p in outputs):
        previous = json.loads(manifest.read_text())
        if (previous["input_sha256"] == hashes and previous["emscripten"] == version and
                previous["output_sha256"] == {p.name: digest(p) for p in outputs}):
            return player
    objects.mkdir(parents=True, exist_ok=True)
    player.mkdir(parents=True, exist_ok=True)
    cost.write_text(costs.text(COST_PROFILE), encoding="ascii", newline="\n")
    commands = []
    linked = []
    for source in C_SOURCES + CXX_SOURCES:
        target = objects / (source.stem + ".o")
        if source.suffix == ".c":
            command = [str(emcc), "-O3", "-std=c11", "-I", str(CORE), "-I", str(FRONT)]
        else:
            command = [str(empp), "-O3", "-std=c++17", "-I", str(FRONT), "-I", str(CORE),
                       "-I", str(SPEECH)]
        command += ["-c", str(source), "-o", str(target)]
        commands.append(command)
        subprocess.run(command, check=True, cwd=ROOT)
        linked.append(str(target))
    command = [str(empp), "-O3", *linked, "-o", str(player / "player.js"), "--no-entry",
               "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sEXPORT_NAME=createPlayer",
               "-sENVIRONMENT=web,worker,node","-sALLOW_MEMORY_GROWTH=1", "-sINITIAL_MEMORY=33554432",
               "-sEXPORTED_FUNCTIONS=" + ",".join("_" + name for name in EXPORTS),
               "-sEXPORTED_RUNTIME_METHODS=cwrap,HEAPU8,HEAP16,FS", "-sFORCE_FILESYSTEM=1",
               "--embed-file", f"{cost}@/turbo-f122.cost"]
    commands.append(command)
    subprocess.run(command, check=True, cwd=ROOT)
    manifest.write_text(json.dumps({
        "emscripten": version, "cost_profile": COST_PROFILE, "input_sha256": hashes,
        # Paths relative to the project and the emsdk, so the record can be published.
        "commands": [[part.replace(str(Path(emsdk).resolve()), "<emsdk>").replace(str(REPO), ".")
                      for part in command] for command in commands],
        "output_sha256": {p.name: digest(p) for p in outputs}},
        indent=2) + "\n")
    return player


def pack_game(game, target, boot_roms=None, download=False):
    """Write the game's ProDOS files, except PRODOS itself, as game.json and game.bin.

    With boot_roms, also copy the whole disk and the installed //e ROM and
    slot-7 firmware into boot/, and boot through them. The output then holds
    the Apple ROM and the disk's ProDOS. With download, the whole disk is also
    offered as <game>.po, and a boot uses that same file.
    """
    found = [d / game / "game.json" for d in (ROOT / "games", ROOT / "examples")
             if (d / game / "game.json").is_file()]
    if len(found) != 1:
        raise SystemExit(f"No single games/{game} or examples/{game} manifest")
    manifest = json.loads(found[0].read_text())
    disk = ROOT / "build" / (game + ".po")
    if not disk.is_file():
        raise SystemExit(f"Build {disk.relative_to(ROOT)} first with tools/build.py")
    volume, files = module("appletini_disk", FRONT / "disk.py").read_disk(disk)
    system = manifest["disk"]["system"]
    records, blob = [], bytearray()
    for entry in files:
        if entry["name"] == "PRODOS":
            continue
        records.append({"name": entry["name"], "type": entry["type"], "aux": entry["aux"],
                        "offset": len(blob), "length": len(entry["data"]),
                        "sha256": hashlib.sha256(entry["data"]).hexdigest()})
        blob += entry["data"]
    if system not in {r["name"] for r in records}:
        raise SystemExit(f"{disk.name} has no {system}")
    (target / "game.bin").write_bytes(blob)
    record = {"title": manifest.get("title", game.upper()), "volume": volume, "system": system,
              "disk_sha256": digest(disk), "files": records}
    boot = target / "boot"
    if boot.exists():
        shutil.rmtree(boot)
    for stale in target.glob("*.po"):
        stale.unlink()
    disk_path = "boot/disk.po"
    if download:
        disk_path = game + ".po"
        shutil.copy2(disk, target / disk_path)
        record["download"] = {"path": disk_path, "bytes": disk.stat().st_size,
                              "sha256": digest(target / disk_path)}
    if boot_roms:
        roms = Path(boot_roms).resolve()
        if not roms.is_relative_to(ROOT):
            raise SystemExit("Install the boot ROMs inside the project first, e.g. build-inputs/native-roms")
        loader = module("appletini_boot", FRONT / "boot.py")
        slot, c8, _ = loader.load_roms(roms / "smartport_a2retronet_style_c700.mem",
                                       roms / "smartport_a2retronet_style_c800.mem")
        apple = (roms / "Apple2e_Enhanced.rom").read_bytes()
        if len(apple) != 16384:
            raise SystemExit("Apple2e_Enhanced.rom must be the 16 KiB enhanced //e ROM")
        boot.mkdir()
        for name, data in (("apple2e.rom", apple), ("c700.bin", slot), ("c800.bin", c8)):
            (boot / name).write_bytes(data)
        if not download:
            shutil.copy2(disk, target / disk_path)
        record["boot"] = {name: {"path": "boot/" + name, "sha256": digest(boot / name)}
                          for name in ("apple2e.rom", "c700.bin", "c800.bin")}
        record["boot"]["disk.po"] = {"path": disk_path, "sha256": digest(target / disk_path)}
    (target / "game.json").write_text(json.dumps(record, indent=2) + "\n")


def source_archive(player, target):
    """Write source.zip: the Corresponding Source of player.js and player.wasm."""
    files = [ROOT / "tools/web.py", ROOT / "LICENSE"] + sorted(p for p in WEB.iterdir() if p.is_file())
    files += [REPO / "demos/doom_gs/README.md"]
    files += sorted(p for directory in (FRONT, CORE) for p in directory.rglob("*")
                    if p.is_file() and not {"__pycache__", "build"} & set(p.relative_to(directory).parts)
                    and p.suffix != ".pyc")
    readme = (
        "libtini browser player source\n\n"
        "This archive is the Corresponding Source of player.js and player.wasm beside\n"
        "it, licensed GPL-3.0 (COPYING.txt). libtini/tools/web.py builds them with\n"
        f"Emscripten {EMSCRIPTEN_VERSION}: python libtini/tools/web.py --emsdk <emsdk> --game <game>.\n"
        "BUILD.json records the exact commands and input hashes.\n"
        "Paths are those of the appletini-software repository: libtini/tools/web.py\n"
        "and libtini/tools/web/ hold the player; tools/appletini and\n"
        "demos/doom_gs/tools/a2vm hold the machine and speech sources.\n")
    with zipfile.ZipFile(target / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        def add(name, data):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
        add("README.txt", readme)
        add("BUILD.json", (player / "build.json").read_bytes())
        for path in files:
            add(path.relative_to(REPO).as_posix(), path.read_bytes())


def serve(directory, port):
    """Serve a built player on this computer only, with the browser's MIME types."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {".html": "text/html", ".js": "text/javascript", ".wasm": "application/wasm",
                          ".json": "application/json", ".bin": "application/octet-stream",
                          ".po": "application/octet-stream", ".rom": "application/octet-stream",
                          "": "text/plain"}

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    with ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(directory))) as server:
        print(f"http://localhost:{server.server_address[1]}/", flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--emsdk", default=os.environ.get("EMSDK"),
                        help="installed emsdk directory (or set EMSDK)")
    parser.add_argument("--game", default="starfall", help="game under examples/")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--boot-roms", type=Path, metavar="DIR",
                        help="boot through the installed //e ROM and slot-7 firmware in DIR "
                             "(the output then holds the Apple ROM and the disk's ProDOS)")
    parser.add_argument("--download-disk", action="store_true",
                        help="also offer the whole game disk, with its ProDOS, as <game>.po")
    parser.add_argument("--serve", type=int, metavar="PORT",
                        help="after building, serve the page on http://localhost:PORT/")
    args = parser.parse_args()
    if not args.emsdk:
        raise SystemExit("Pass --emsdk <installed emsdk directory> or set EMSDK")
    player = build_player(args.emsdk, args.rebuild)
    target = OUT / args.game
    target.mkdir(parents=True, exist_ok=True)
    for name in ("player.js", "player.wasm"):
        shutil.copy2(player / name, target / name)
    for name in PAGE:
        shutil.copy2(WEB / name, target / name)
    shutil.copy2(FRONT / "LICENSE", target / "COPYING.txt")
    source_archive(player, target)
    pack_game(args.game, target, args.boot_roms, args.download_disk)
    print(target, flush=True)
    if args.serve is not None:
        serve(target, args.serve)


if __name__ == "__main__":
    main()
