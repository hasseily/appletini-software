#!/usr/bin/env python3
"""Build and check the actual 65C02 CPU backend plus host disk tooling."""
from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path
import subprocess
import struct
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def run_target(mode=0, banks=4, switches=None, entry_status=0x20):
    from emulator import TargetRun
    run = TargetRun(ROOT / "build/test_target.system", ROOT / "build/test_target.lbl", banks)
    run.mode = mode
    run.cpu.p = entry_status
    if mode == 3:
        run.memory.display_levels = [0, 1, 1, 0, 1, 1]
    if switches:
        for name, state in switches.items():
            setattr(run.memory, name, state)
    names = ("ramrd", "ramwrt", "altzp", "store80", "page2", "hires",
             "text", "mixed", "col80", "altchar")
    initial = {name: getattr(run.memory, name) for name in names}
    for bank, memory in enumerate(run.memory.aux):
        memory[:] = bytes((i * 13 + bank * 31 + 5) & 255 for i in range(65536))
    before_aux0 = bytes(run.memory.aux[0])
    before_os = bytes(run.memory.main[0x200:0x2000])
    before_trampoline = bytes(run.memory.main[0x140:0x180])
    before_stack_os = bytes(run.memory.main[0x100:0x140])
    run.run(max_steps=160_000_000)
    assert run.quit, "target did not return to ProDOS QUIT"
    assert run.word("_test_failed") == 0, f"target check {run.word('_test_failed')} failed"
    assert run.word("_test_checks") > 0, "target tests did not run"
    assert {name: getattr(run.memory, name) for name in names} == initial, "switch restoration"
    assert run.memory.bank == 0, "RamWorks selector not restored"
    assert bytes(run.memory.main[:0x100]) == run.initial_zero_page, "zero-page restoration"
    assert bytes(run.memory.main[0x140:0x180]) == before_trampoline, "trampoline restoration"
    assert bytes(run.memory.main[0x100:0x140]) == before_stack_os, "ProDOS hardware-stack workspace"
    assert bytes(run.memory.main[0x200:0x2000]) == before_os, "main OS/video workspace modified"
    assert bytes(run.memory.aux[0]) == before_aux0, "aux0 display/OS state restoration"
    assert not any(0xC0F0 <= address <= 0xC0FF for address in run.memory.io_reads), "private/slot7 I/O"
    assert not any(0xC0F0 <= address <= 0xC0FF for address, _ in run.memory.io_writes), "private/slot7 I/O"
    assert run.mli_calls == [(0x65, run.mli_calls[0][1])], "unexpected ProDOS operation"
    assert run.cpu.p & 0xCF == entry_status & 0xCF, "entry processor status was not restored"
    if mode == 0:
        assert run.memory.video_writes >= 32768 + 256, "CPU video path not exercised"
    print(f"65C02 mode={mode}, banks={banks}: {run.word('_test_checks')} target checks; "
          f"{run.steps:,} instructions; clean ProDOS QUIT; state restored; "
          f"min SP=${run.min_hardware_sp:02X}/c_sp=${run.min_software_sp:04X}")


def run_diagnostic():
    from emulator import TargetRun
    run = TargetRun(ROOT / "build/libtini.system", ROOT / "build/libtini.lbl", 4)
    run.memory.auto_key = True
    before = bytes(run.memory.aux[0])
    run.run(max_steps=40_000_000)
    screen = run.memory.published_screen
    assert run.quit and screen is not None, "diagnostic did not show screen and QUIT"
    for row in (64, 80, 96, 112, 128):
        pixels = screen[row * 160:(row + 7) * 160]
        green = sum((byte & 15) == 3 for byte in pixels)
        green += sum((byte >> 4) == 3 for byte in pixels)
        red = sum((byte & 15) == 4 or (byte >> 4) == 4 for byte in pixels)
        assert green > 30 and red == 0, f"diagnostic memory result at y={row} failed"
    assert bytes(run.memory.aux[0]) == before, "diagnostic did not restore AUX0"
    assert bytes(run.memory.main[:0x100]) == run.initial_zero_page, "diagnostic ZP restoration"
    write_shr_png(screen, ROOT / "build/diagnostic-emulated.png")
    print(f"65C02 diagnostic: 5 PASS rows in CPU-published SHR, key exit, "
          f"{run.steps:,} instructions; AUX0/ZP restored; "
          f"min SP=${run.min_hardware_sp:02X}/c_sp=${run.min_software_sp:04X}")


def write_shr_png(screen, path):
    """Render actual sampled AUX bytes. This is not a hardware screenshot."""
    scanlines = bytearray()
    for y in range(200):
        scanlines.append(0)  # PNG filter None.
        palette = 0x7E00 + (screen[0x7D00 + y] & 15) * 32
        for x in range(320):
            packed = screen[y * 160 + x // 2]
            index = packed & 15 if x & 1 else packed >> 4
            word = int.from_bytes(screen[palette + 2 * index:palette + 2 * index + 2], "little")
            scanlines.extend((((word >> 8) & 15) * 17,
                              ((word >> 4) & 15) * 17, (word & 15) * 17))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data)))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 200, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true", help="use existing build artifacts")
    parser.add_argument("--host-only", action="store_true", help="only run Python tool tests")
    args = parser.parse_args()
    if not args.no_build:
        subprocess.run([sys.executable, str(ROOT / "tools/build.py"), "--test-target"],
                       cwd=ROOT, check=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_tools.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    if not args.host_only:
        if version("py65") != "1.2.0":
            raise RuntimeError("Install documented emulator dependency: py65==1.2.0")
        run_target(switches={"store80": True, "page2": True, "mixed": True,
                             "col80": True, "altchar": True})
        run_target(mode=1, banks=1)
        run_target(mode=2, switches={"store80": True, "hires": True, "text": False}, entry_status=0x2D)
        run_target(mode=3)
        run_diagnostic()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
