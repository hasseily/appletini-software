#!/usr/bin/env python3
"""Time chosen functions of a built program on the native emulator.

Each function's time includes everything it calls, interrupt handlers too,
and is reported for each call path: _hud/_field/_ti_gfx_text is ti_gfx_text
called by field called by hud. Exported names come from the label file.
Static C functions and other assembler labels come from listings of the
sources the build staged in build/asm; name one that several modules share
as module:name. A function already running when the window opens counts
only from its next call. These are emulator model figures, not board timing.

Example, 20 seconds of STARFALL on a Mockingboard after its title screen:
  python tools/profiler.py --game starfall --cc65-home D:/Repos/cc65 \\
      --cc C:/msys64/ucrt64/bin/gcc.exe --key 13 --skip 360 --frames 1200 \\
      --count _sf_frames:4 _render _hud _field _ti_gfx_text
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build as build_tools
import native_emulator

ROMS = ROOT / "build-inputs/native-roms"
MODULE = re.compile(r"^(?:.*\()?([^()\\/]+)\.o\)?:$")
PLACED = re.compile(r"^\s+(\w+)\s+Offs=([0-9A-F]+)\s+Size=([0-9A-F]+)")
SEGMENT = re.compile(r"^(\w+)\s+([0-9A-F]{6})\s+[0-9A-F]{6}\s+[0-9A-F]{6}\s+[0-9A-F]{5}$")
LABEL = re.compile(r"^(?:\.proc\s+)?([A-Za-z_]\w*):")
SEGMENT_DIRECTIVE = re.compile(r'^\.segment\s+"(\w+)"')


def read_map(text):
    """Segment run addresses and each module's offset within each segment."""
    starts, offsets, section, module = {}, {}, None, None
    for line in text.splitlines():
        if line in ("Modules list:", "Segment list:"):
            section = line
            continue
        if line.endswith("list:") or line.startswith("Exports list"):
            section = None
        if section == "Modules list:":
            found = MODULE.match(line)
            if found:
                module = found[1]
                offsets.setdefault(module, {})
            elif module and (placed := PLACED.match(line)) and int(placed[3], 16):
                offsets[module][placed[1]] = int(placed[2], 16)
        elif section == "Segment list:" and (row := SEGMENT.match(line)):
            starts.setdefault(row[1], int(row[2], 16))
    return starts, offsets


def read_listing(text):
    """(segment, offset, name) for each label a ca65 listing defines."""
    labels, segment = [], "CODE"
    for line in text.splitlines():
        if len(line) < 25 or line[6] != "r":
            continue
        try:
            offset = int(line[:6], 16)
        except ValueError:
            continue
        source = line[24:]
        if directive := SEGMENT_DIRECTIVE.match(source):
            segment = directive[1]
        elif label := LABEL.match(source):
            labels.append((segment, offset, label[1]))
    return labels


def locate(listings, starts, offsets, exported):
    """name -> [(module, address)], checked against the exported addresses."""
    found = {}
    for module, labels in listings.items():
        for segment, offset, name in labels:
            if segment not in offsets.get(module, {}):
                continue
            address = starts[segment] + offsets[module][segment] + offset
            if name in exported and exported[name] != address:
                raise SystemExit(f"build/asm/{module}.s does not match the linked program "
                                 f"({name}); rebuild first")
            found.setdefault(name, []).append((module, address))
    return found


def resolve(requested, found, exported):
    """Entry addresses for names such as _hud, hud or graphics_text:_draw."""
    entries = {}
    for name in requested:
        module, _, bare = name.rpartition(":")
        choices = []
        for candidate in (bare, "_" + bare):
            if not module and candidate in exported:
                choices = [(None, exported[candidate])]
                break
            choices = [hit for hit in found.get(candidate, []) if not module or hit[0] == module]
            if choices:
                break
        if not choices:
            raise SystemExit("unknown function: " + name)
        if len(choices) > 1:
            raise SystemExit(name + " is in several modules; name one as " +
                             ", ".join(f"{hit[0]}:{bare}" for hit in choices))
        entries[choices[0][1]] = name
    return entries


class Paths:
    """Inclusive ticks per call path from entry and return events.

    Each entry keeps the hardware stack pointer just after its call. A loop
    back to a function's first instruction at that depth is not a new call,
    and a return counts only two bytes above it, so recursion and code that
    reaches a return address another way are not mistaken for returns."""
    def __init__(self):
        self.stack, self.totals = [], {}

    def enter(self, name, ticks, return_address, sp):
        if self.stack and self.stack[-1][0] == name and self.stack[-1][3] == sp:
            return False
        self.stack.append((name, ticks, return_address, sp))
        return True

    def leave(self, return_address, ticks, sp):
        # A jump into another function leaves both with one return; any
        # entry above the outermost one returning here is left with it.
        outer = next((index for index, entry in enumerate(self.stack)
                      if entry[2] == return_address and (entry[3] + 2) & 255 == sp), None)
        if outer is None:
            return False
        while len(self.stack) > outer:
            name, began, _, _ = self.stack.pop()
            self.record(name, ticks - began)
        return True

    def record(self, name, ticks):
        key = "/".join([entry[0] for entry in self.stack] + [name])
        total = self.totals.setdefault(key, {"ticks": 0, "calls": 0})
        total["ticks"] += ticks
        total["calls"] += 1

    def close(self, ticks):
        while self.stack:
            name, began, _, _ = self.stack.pop()
            self.record(name, ticks - began)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("functions", nargs="+")
    parser.add_argument("--game", required=True, help="a program built under build/, such as starfall")
    parser.add_argument("--cc65-home")
    parser.add_argument("--cc", required=True, help="host C compiler for the native emulator")
    parser.add_argument("--profile", default="vtw33", choices=("vtw33", "turbo-f122"))
    parser.add_argument("--wait", type=int, default=600, help="model frames after main starts")
    parser.add_argument("--key", action="append", default=[], help="a key code or character, sent in order")
    parser.add_argument("--key-frames", type=int, default=30, help="model frames after each key")
    parser.add_argument("--skip", type=int, default=0, help="model frames before the window")
    parser.add_argument("--frames", type=int, default=600, help="model frames in the window")
    parser.add_argument("--count", action="append", default=[], help="LABEL[:BYTES] to report the change of")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _, tools, _ = build_tools.installed_tools(args.cc65_home)
    build_dir = ROOT / "build"
    out = build_dir / "profile"
    out.mkdir(parents=True, exist_ok=True)
    # Local assembler labels in the label file can share names across
    # modules; C-visible names start with an underscore.
    exported = {name: address for name, address in build_tools.read_labels(build_dir / (args.game + ".lbl")).items()
                if name.startswith("_")}
    starts, offsets = read_map((build_dir / (args.game + ".map")).read_text())
    listings = {}
    for module in offsets:
        source = build_dir / "asm" / (module + ".s")
        if not source.is_file():
            continue
        listing = out / (module + ".lst")
        subprocess.run([str(tools["ca65"]), "--cpu", "65c02", "-t", "none",
                        "-I", str(Path(tools["ca65"]).parents[1] / "asminc"), "-I", str(ROOT / "src/target"),
                        "-l", str(listing), "-o", str(out / (module + ".o")), str(source)], check=True)
        listings[module] = read_listing(listing.read_text())
    entries = resolve(args.functions, locate(listings, starts, offsets, exported), exported)
    counters = []
    for item in args.count:
        name, _, size = item.partition(":")
        if name not in exported:
            raise SystemExit("unknown label: " + name)
        counters.append((name, int(size or 1)))

    library = native_emulator.build(args.cc)
    sys.path.insert(0, str(native_emulator.FRONT))
    import cli
    cli.build_library = lambda: library
    for name in ("Apple2e_Enhanced.rom", "smartport_a2retronet_style_c700.mem",
                 "smartport_a2retronet_style_c800.mem", "apple2e-video.bin"):
        if not (ROMS / name).is_file():
            raise SystemExit("Install the native boot inputs first: missing " + str(ROMS / name))
    machine = cli.Machine(cli.parser().parse_args([
        "debug", "--boot", "--disk", str(build_dir / (args.game + ".po")), "--profile", args.profile,
        "--rom", str(ROMS / "Apple2e_Enhanced.rom"),
        "--slot7-rom", str(ROMS / "smartport_a2retronet_style_c700.mem"),
        "--slot7-c8-rom", str(ROMS / "smartport_a2retronet_style_c800.mem"),
        "--video-rom", str(ROMS / "apple2e-video.bin")]))

    def value(name, size):
        return int.from_bytes(machine.read("main", exported[name], size), "little")

    def frames(count):
        while count > 0:
            machine.run(frames=min(count, 6), timeout=60)
            count -= 6

    try:
        result = machine.run(frames=3600, breakpoints=[exported["_main"]], timeout=60)
        if result["reason"] != "breakpoint":
            raise SystemExit("the program did not reach main")
        frames(args.wait)
        for key in args.key:
            code = int(key) if key.isdigit() else ord(key)
            machine.check(machine.lib.ap_input(machine.handle, b"key", code, 0))
            frames(args.key_frames)
        frames(args.skip)
        frame_ticks = machine.get("frame_ticks")
        start = machine.get("ticks")
        end = start + args.frames * frame_ticks
        before = {name: value(name, size) for name, size in counters}
        paths = Paths()
        # Events count where a breakpoint stopped the machine, or one
        # instruction after another event; a run that ends on its frame
        # budget can stop anywhere.
        event = False
        while True:
            pc = machine.get("pc")
            now = machine.get("ticks")
            if now >= end:
                paths.close(now)
                break
            handled = False
            if event:
                sp = machine.get("s")
                handled = paths.leave(pc, now, sp) if paths.stack else False
                if not handled and pc in entries:
                    ret = int.from_bytes(machine.read("main", 0x100 + ((sp + 1) & 255), 1) +
                                         machine.read("main", 0x100 + ((sp + 2) & 255), 1), "little") + 1
                    handled = paths.enter(entries[pc], now, ret, sp)
            breaks = list(entries) + [entry[2] for entry in paths.stack]
            # Step past a breakpoint even when it was not a call or return.
            if handled or (event and pc in breaks):
                machine.run(steps=1)
                continue
            event = machine.run(frames=4, breakpoints=breaks, timeout=60)["reason"] == "breakpoint"
        elapsed = now - start
        report = {
            "model": args.profile, "board_evidence": False, "clock_hz": machine.clock_hz,
            "window_ticks": elapsed, "window_seconds": elapsed / machine.clock_hz,
            "counts": {name: value(name, size) - before[name] for name, size in counters},
            "paths": {key: {**total, "percent": total["ticks"] * 100 / elapsed,
                            "ms_per_call": total["ticks"] * 1000 / machine.clock_hz / total["calls"]}
                      for key, total in sorted(paths.totals.items(), key=lambda item: -item[1]["ticks"])},
        }
    finally:
        machine.close()
    output = args.output or out / f"{args.game}-{args.profile}.json"
    output.write_text(json.dumps(report, indent=1) + "\n")
    print(f"{args.profile}: {report['window_seconds']:.2f} model seconds" +
          "".join(f", {name} +{change}" for name, change in report["counts"].items()))
    for key, total in report["paths"].items():
        print(f"{total['percent']:6.2f}% {total['calls']:7d} calls {total['ms_per_call']:9.3f} ms/call  {key}")
    print(output)


if __name__ == "__main__":
    main()
