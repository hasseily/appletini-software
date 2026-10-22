#!/usr/bin/env python3
"""Run the actual band renderer on the 65C02 model and check every draw.

After each ti_scene_draw the screen area must equal an independent rendering
of the current sprite list over the background, and every SHR byte outside
the areas used so far must keep the pattern written before the first scene.
A repeated list must publish nothing. This is instruction-level evidence, not
a display or timing test.
"""
from pathlib import Path
import argparse
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build
from emulator import TargetRun
from scene_reference import mismatch, render


def compile_target(home):
    sdk, tools, _ = build.installed_tools(home)
    source = ROOT / "tests/scene_target.c"
    obj = ROOT / "build/obj/scene_target.o"
    build.compile_c(source, obj, sdk, tools)
    build.run([tools["ld65"], "-C", "cfg/libtini.cfg", "-o", "build/scene_target.system",
               "-Ln", "build/scene_target.lbl", "-m", "build/scene_target.map",
               "build/obj/target/startup.o", build.rel(obj), "build/libtini.lib", tools["runtime"]])


def pattern(address):
    return (address * 7 + (address >> 8) * 3) & 255


class Scene:
    def __init__(self, target):
        self.t = target
        self.main = target.memory.main
        self.aux = target.memory.aux[0]
        self.areas = set()
        self.shown = 0
        self.writes = 0
        self.pixels_checked = 0

    def read(self, address, length):
        return bytes(self.main[address:address + length])

    def read_aux(self, address, length):
        return bytes(self.aux[address:address + length])

    def ready(self):
        for address in range(0x2000, 0x9D00):
            self.aux[address] = pattern(address)
        self.writes = self.t.memory.video_writes

    def inside(self, address):
        for start, row_bytes, lines in self.areas:
            offset = address - start
            if 0 <= offset < lines * 160 and offset % 160 < row_bytes:
                return True
        return False

    def shown_check(self):
        self.shown += 1
        problem = mismatch(self.read, self.read_aux, self.t.labels)
        assert problem is None, f"draw {self.shown}: {problem}"
        start, row_bytes, rows = render(self.read, self.t.labels)
        self.areas.add((start, row_bytes, len(rows)))
        self.pixels_checked += row_bytes * 2 * len(rows)
        for address in range(0x2000, 0x9D00):
            if not self.inside(address):
                assert self.aux[address] == pattern(address), (
                    f"draw {self.shown}: byte outside the area changed at ${address:04X}")
        written = self.t.memory.video_writes - self.writes
        if self.main[self.t.labels["_test_expect_quiet"]]:
            assert written == 0, f"draw {self.shown}: an unchanged list published {written} bytes"
        self.writes = self.t.memory.video_writes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc65-home", default=os.environ.get("CC65_HOME"))
    compile_target(parser.parse_args().cc65_home)
    target = TargetRun(ROOT / "build/scene_target.system", ROOT / "build/scene_target.lbl")
    scene = Scene(target)
    hooks = {target.labels["_test_ready"]: scene.ready, target.labels["_test_shown"]: scene.shown_check}
    step = target.cpu.step

    def hooked():
        hook = hooks.get(target.cpu.pc)
        if hook:
            hook()
        step()
    target.cpu.step = hooked
    target.run(80_000_000)
    assert target.quit, "scene target did not return to ProDOS"
    failed = target.word("_test_failed")
    assert failed == 0, f"scene target check {failed} failed"
    print(f"scene: {target.word('_test_checks')} target checks, {scene.shown} draws compared with the "
          f"reference ({scene.pixels_checked:,} pixels), {target.steps:,} instructions PASS")


if __name__ == "__main__":
    main()
