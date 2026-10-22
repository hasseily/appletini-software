#!/usr/bin/env python3
"""Compare the browser player with the native machine on the same game run.

The WebAssembly player runs under the emsdk's Node; the native DLL runs with
the separate native SSI-263 speech worker, as the runner does. Both get the
same files and input script at vtw33 and turbo-f122. Every checkpoint (ticks,
PC, AUX $2000-$9FFF, decoded frame) and the mixed PCM digest must match. The
native frame comes from the runner's own SHR preview decoder. Speech is
compared at the reference gain; the page doubles it.

With --boot-roms, both boot the game disk through the installed //e ROM and
slot-7 firmware, as the runner's --boot does; otherwise both use the ProDOS
MLI stand-in.

These are emulator checks. Profile clocks/costs do not establish board timing.

Example: python tests/web_validate.py --emsdk D:/Repos/emsdk --cc C:/msys64/ucrt64/bin/gcc.exe
         --boot-roms build-inputs/native-roms
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import native_emulator
import web

# Boot, launch with Mockingboard, move, drop a bomb and use the joystick.
SCRIPT = [
    {"frames": 300},
    {"input": ["hold", 13, 0]}, {"frames": 3}, {"input": ["release", 0, 0]},
    {"frames": 240},
    {"input": ["hold", ord("D"), 0]}, {"frames": 45}, {"input": ["release", 0, 0]},
    {"input": ["hold", ord(" "), 0]}, {"frames": 2}, {"input": ["release", 0, 0]},
    {"frames": 120},
    {"input": ["paddle", 0, 0]}, {"input": ["paddle", 1, 40]}, {"frames": 60},
    {"input": ["paddle", 0, 128]}, {"input": ["paddle", 1, 128]},
    {"input": ["button", 0, 1]}, {"frames": 30}, {"input": ["button", 0, 0]},
    {"frames": 300},
]
PROFILES = {"vtw33": 0, "turbo-f122": 1}
CPU_HZ = {"vtw33": 133333333.333333 / 4, "turbo-f122": 133333333.333333 / 10}
LINE_US, LINES, BANKS = 63.695246, 262, 128


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def speech_worker(cc):
    """Build the unchanged native speech worker into build/native."""
    compiler = Path(cc).resolve().with_name("g++.exe" if Path(cc).suffix == ".exe" else "g++")
    sources = [web.SPEECH / "worker.cpp"] + [web.SPEECH / "reference" / name for name in
                                             ("native_control.cpp", "native_source.cpp",
                                              "prototype_tract.cpp")]
    binary = native_emulator.OUT / "ssi263-speech.exe"
    native_emulator.OUT.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
    env["PATH"] = str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")
    subprocess.run([str(compiler), "-std=c++17", "-O2", "-static", *map(str, sources),
                    "-o", str(binary)], check=True, cwd=ROOT, env=env)
    return binary


def frame_rgba(video, aux, newvideo):
    """The runner's SHR preview as 640x200 RGBA, 320-pixel rows doubled."""
    width, rows = video.decode_shr(aux)
    out = bytearray()
    for row in rows:
        if newvideo & 0x20:
            row = bytes(v for i in range(0, len(row), 3)
                        for v in [(77 * row[i] + 150 * row[i + 1] + 29 * row[i + 2]) >> 8] * 3)
        for i in range(0, len(row), 3):
            out += (row[i:i + 3] + b"\xff") * (2 if width == 320 else 1)
    return bytes(out)


def native_run(lib, video, speech, worker, target, game, files, profile):
    error = C.create_string_buffer(1024)
    cost = str(web.OUT / "obj/turbo-f122.cost").encode() if profile == "turbo-f122" else None
    boot = {name: target / entry["path"] for name, entry in game.get("boot", {}).items()
            if isinstance(entry, dict)}
    rom = str(boot["apple2e.rom"]).encode() if boot else None
    h = lib.ap_new(rom, cost, CPU_HZ[profile], LINE_US, LINES, BANKS, error, len(error))
    if not h:
        raise SystemExit(error.value.decode())

    def check(result):
        if not result:
            raise SystemExit(lib.ap_error(h).decode())

    try:
        check(lib.ap_slot2(h, b"mouse"))
        if boot:
            slot, c8 = boot["c700.bin"].read_bytes(), boot["c800.bin"].read_bytes()
            check(lib.ap_mount_disk(h, str(boot["disk.po"]).encode()))
            check(lib.ap_boot(h, slot, len(slot), c8, len(c8)))
        else:
            check(lib.ap_prodos(h, game["volume"].encode(), game["system"].encode()))
            for entry in game["files"]:
                data = files[entry["offset"]:entry["offset"] + entry["length"]]
                check(lib.ap_file(h, entry["name"].encode(), entry["type"], entry["aux"], data,
                                  len(data)))
            system = next(e for e in game["files"] if e["name"] == game["system"])
            program = files[system["offset"]:system["offset"] + system["length"]]
            check(lib.ap_write(h, 0, 0, 0x2000, program, len(program)))
            check(lib.ap_set_reg(h, b"pc", 0x2000))
            check(lib.ap_set_reg(h, b"s", 0xff))
        check(lib.ap_slot7(h, b"smartport"))
        check(lib.ap_audio_enable(h, 48000))
        get = lambda name: lib.ap_get(h, name.encode())
        speech.build_worker = lambda: worker
        mixer = speech.SpeechWorker(rate=48000, guest_hz=get("clock_hz"),
                                    origin=get("audio_origin"), xck_hz=get("speech_xck_hz"))
        pcm, pcm_frames, frames, checkpoints = hashlib.sha256(), 0, 0, []
        event_buffer = (SpeechEvent * 4096)()
        frame_ticks = get("frame_ticks")
        started = time.perf_counter()
        try:
            for step in SCRIPT:
                if "input" in step:
                    kind, x, y = step["input"]
                    check(lib.ap_input(h, kind.encode(), x, y))
                    continue
                for _ in range(step["frames"]):
                    now = get("ticks")
                    target = (now // frame_ticks + 1) * frame_ticks
                    while now < target:
                        result = lib.ap_run(h, 0, target - now, None, 0)
                        if result < 0 or result in (3, 4, 5):
                            raise SystemExit(f"native run stopped: {result}")
                        # The runner's AudioOutput.drain: one speech block per run.
                        events = []
                        while True:
                            count = lib.ap_audio_event_read(h, event_buffer, len(event_buffer))
                            events += [(e.tick, e.chip, e.reg, e.value) for e in event_buffer[:count]]
                            if count < len(event_buffer):
                                break
                        available = lib.ap_audio_available(h)
                        samples = (C.c_int16 * (available * 2))()
                        count = lib.ap_audio_read(h, samples, available)
                        if count or events:
                            mixed = mixer.render(bytes(samples)[:count * 4], events)
                            pcm.update(mixed)
                            pcm_frames += count
                        now = get("ticks")
                    frames += 1
                aux = C.create_string_buffer(0x8000)
                check(lib.ap_read(h, 1, 0, 0x2000, aux, 0x8000))
                shr = (get("newvideo") & 0xc0) == 0xc0
                checkpoints.append({
                    "frames": frames, "ticks": get("ticks"), "pc": get("pc"),
                    "aux_sha256": sha(aux.raw),
                    "screen_sha256": sha(frame_rgba(video, aux.raw, get("newvideo"))) if shr else None})
        finally:
            mixer.close()
        host = time.perf_counter() - started
        seconds = frames * frame_ticks / get("clock_hz")
        return {"checkpoints": checkpoints, "pcm_sha256": pcm.hexdigest(), "pcm_frames": pcm_frames,
                "guest_seconds": seconds, "host_seconds": host, "speed": seconds / host}
    finally:
        lib.ap_free(h)


class SpeechEvent(C.Structure):
    _fields_ = [("tick", C.c_uint64), ("chip", C.c_uint8), ("reg", C.c_uint8),
                ("value", C.c_uint8), ("reserved", C.c_uint8 * 5)]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--emsdk", required=True, help="installed emsdk directory")
    parser.add_argument("--cc", required=True, help="installed MSYS2 UCRT64 GCC executable")
    parser.add_argument("--game", default="starfall")
    parser.add_argument("--boot-roms", type=Path, metavar="DIR",
                        help="boot through the installed //e ROM and slot-7 firmware in DIR")
    args = parser.parse_args()
    command = [sys.executable, str(ROOT / "tools/web.py"), "--emsdk", args.emsdk, "--game", args.game]
    if args.boot_roms:
        command += ["--boot-roms", str(args.boot_roms)]
    target = Path(subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip())
    game = json.loads((target / "game.json").read_text())
    files = (target / "game.bin").read_bytes()
    node = next((Path(args.emsdk) / "node").glob("*/node.exe"), None) or \
        next((Path(args.emsdk) / "node").glob("*/bin/node"))
    script = web.OUT / "validate-script.json"
    script.write_text(json.dumps(SCRIPT) + "\n")
    library = native_emulator.build(args.cc)
    sys.path.insert(0, str(native_emulator.FRONT))
    import cli
    lib = cli.library_api(library)
    video = module("appletini_video", native_emulator.FRONT / "video.py")
    speech = module("appletini_speech", native_emulator.FRONT / "speech.py")
    worker = speech_worker(args.cc)
    evidence = {"board_evidence": False, "game": args.game, "game_files": game["files"],
                "source_revision": native_emulator.source_revision(),
                "launch": "rom-boot" if "boot" in game else "prodos-mli-stand-in",
                "boot_inputs_sha256": {name: entry["sha256"] for name, entry in
                                       game.get("boot", {}).items() if isinstance(entry, dict)},
                "emscripten": json.loads((web.OUT / "player/build.json").read_text())["emscripten"],
                "node": subprocess.run([str(node), "--version"], capture_output=True, text=True,
                                       check=True).stdout.strip(),
                "player_wasm_sha256": web.digest(target / "player.wasm"),
                "native_dll_sha256": web.digest(library),
                "native_speech_worker_sha256": web.digest(worker),
                "script": SCRIPT, "profiles": []}
    failed = False
    for profile, number in PROFILES.items():
        browser = json.loads(subprocess.run([str(node), str(web.WEB / "check.mjs"), str(target),
                                             str(number), str(script)], check=True,
                                            capture_output=True, text=True).stdout)
        native = native_run(lib, video, speech, worker, target, game, files, profile)
        same = (browser["checkpoints"] == native["checkpoints"] and
                browser["pcm_sha256"] == native["pcm_sha256"] and
                browser["pcm_frames"] == native["pcm_frames"] and browser["stopped"] is None)
        failed |= not same
        evidence["profiles"].append({"profile": profile, "matched": same, "browser": browser,
                                     "native": native})
        print(f"{profile}: {'matched' if same else 'MISMATCH'}; "
              f"{len(native['checkpoints'])} checkpoints, {native['pcm_frames']} PCM frames; "
              f"Node {browser['speed']:.2f}x real time "
              f"(machine {browser['machine_speed']:.2f}x), native {native['speed']:.2f}x")
    output = web.OUT / "validation.json"
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(output)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
