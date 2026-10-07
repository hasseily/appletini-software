#!/usr/bin/env python3
"""Execute assembled SYS code with simulated ProDOS calls and Phasor ports.

This validates the loader/player integration; it is not a ProDOS boot ROM,
cycle-accurate VIA emulator, or substitute for an Appletini board test.
"""
from collections import defaultdict
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from py65.devices.mpu65c02 import MPU

HERE = Path(__file__).resolve().parent
SHOWCASE = "--showcase" in sys.argv
BUILD = HERE / ("build/showcase" if SHOWCASE else "build")
SONG_PREFIX = "/MSDOS/MUSIC" if SHOWCASE else "/RISING.SUN"
sys.path.insert(0, str(HERE / "../../song_to_phasor"))
from phasor.stream import decode, encode

SYMBOLS = {}
for line in (BUILD / "sun.lbl").read_text().splitlines():
    _, address, name = line.split()
    SYMBOLS[name.lstrip(".")] = int(address, 16)
BINARY = (BUILD / "SUN.SYSTEM").read_bytes()


class Memory(list):
    def __init__(self):
        super().__init__([0] * 65536)
        self.events = []
        self.ay_register = [0] * 4
        self.timer_latch = None
        self.native_reads = []
        self.key = 0
        self.overrun = False

    def __getitem__(self, address):
        if address == 0xC000:
            return self.key
        if address in (0xC0C8, 0xC0C5):
            self.native_reads.append(address)
        return super().__getitem__(address)

    def __setitem__(self, address, value):
        if isinstance(address, int):
            if address == 0xC010:
                self.key = 0
            if address == 0xC48D:
                value = 0x40 if self.overrun else super().__getitem__(address) & ~value
            if address == 0xC485:
                self.timer_latch = super().__getitem__(0xC484) | value << 8
            for chip, base in ((4, 0xC420), (5, 0xC440)):
                if base <= address <= base + 4:
                    self.events.append((chip, address - base, value))
            if address in (0xC410, 0xC480) and value & 4:
                via = int(address == 0xC480)
                for chip, mask in ((via, 0x10), (via + 2, 0x08)):
                    if not value & mask:
                        data = super().__getitem__(address + 15)
                        if value & 3 == 3:
                            self.ay_register[chip] = data
                        elif value & 3 == 2:
                            self.events.append((chip, self.ay_register[chip], data))
        super().__setitem__(address, value)


class Demo:
    def __init__(self, data, *, reported_size=None, short_read=False, open_error=0,
                 basic_size=0x2800, basic_short_read=False, basic_errors=None):
        self.memory = Memory()
        self.memory[0x2000:0x2000 + len(BINARY)] = BINARY
        self.cpu = MPU(memory=self.memory, pc=0x2000)
        self.data = data
        self.reported_size = len(data) if reported_size is None else reported_size
        self.short_read = short_read
        self.open_error = open_error
        self.mli_calls = []
        self.paths = []
        self.basic_size = basic_size
        self.basic_short_read = basic_short_read
        self.basic_errors = basic_errors or {}
        # Replace every byte of the SYS program on READ, including all old
        # routines and data, to catch accidental references after overwrite.
        self.basic_data = bytes((i * 17 + 3) & 255 for i in range(0x2800))
        self.loading_basic = False
        self.prefix = ""

    def get(self, name, size=1):
        start = SYMBOLS[name]
        return int.from_bytes(bytes(self.memory[start:start + size]), "little")

    def word(self, address):
        return self.memory[address] | self.memory[address + 1] << 8

    def mli(self):
        ret = self.cpu.stPopWord()
        command = self.memory[ret + 1]
        params = self.word(ret + 2)
        self.mli_calls.append(command)
        code = 0
        if command == 0xC8:
            path = self.word(params + 1)
            self.paths.append(bytes(self.memory[path + 1:path + 1 + self.memory[path]]).decode())
            self.loading_basic = self.paths[-1] == "/MSDOS/BASIC.SYSTEM"
            assert self.word(params + 3) == 0x1C00
            self.memory[params + 5] = 1
            code = self.basic_errors.get(command, 0) if self.loading_basic else self.open_error
        elif command == 0xD1:
            size = self.basic_size if self.loading_basic else self.reported_size
            self.memory[params + 2:params + 5] = size.to_bytes(3, "little")
        elif command == 0xCA:
            address, count = self.word(params + 2), self.word(params + 4)
            if self.loading_basic:
                assert address == 0x2000 and count == 0x2800
                data, short_read = self.basic_data, self.basic_short_read
            else:
                assert address == 0x3000 and 16 <= count <= 0x8800
                data, short_read = self.data, self.short_read
            got = min(count, len(data)) - int(short_read)
            self.memory[address:address + got] = data[:got]
            self.memory[params + 6:params + 8] = got.to_bytes(2, "little")
        elif command == 0xCC:
            pass
        elif command == 0xC6:
            assert self.loading_basic
            path = self.word(params + 1)
            self.prefix = bytes(self.memory[path + 1:path + 1 + self.memory[path]]).decode()
        elif command == 0x65:
            self.cpu.pc = 0x0FFF
            return
        else:
            raise AssertionError(f"unknown MLI call ${command:02X}")
        if self.loading_basic:
            assert 0x1400 <= ret < 0x1800, "reload code was not relocated"
            assert 0x1400 <= params < 0x1800, "reload parameters were not relocated"
            code = self.basic_errors.get(command, 0)
        self.cpu.a = code
        self.cpu.p = (self.cpu.p | self.cpu.CARRY) if code else (self.cpu.p & ~self.cpu.CARRY)
        self.cpu.pc = ret + 4

    def run_to(self, address, max_steps=300000):
        before = self.cpu.processorCycles
        for _ in range(max_steps):
            if self.cpu.pc == 0xBF00:
                self.mli()
            else:
                self.cpu.step()
            if self.cpu.pc == address:
                return self.cpu.processorCycles - before
        raise AssertionError(f"did not reach ${address:04X}; at ${self.cpu.pc:04X}")

    def boot(self):
        self.run_to(SYMBOLS["poll"])

    def loop(self):
        return self.run_to(SYMBOLS["poll"])

    def tick(self):
        list.__setitem__(self.memory, 0xC48D, 0x40)
        return self.loop()

    def key(self, char):
        self.memory.key = ord(char) | 0x80
        return self.loop()


def exercise_song(data, region):
    expected, header = decode(data)
    by_tick = defaultdict(list)
    for tick, chip, reg, value in expected:
        by_tick[tick].append((chip, reg, value))
    demo = Demo(data)
    demo.boot()
    assert demo.get("loaded") and demo.get("phs_playing") and not demo.get("error")
    assert demo.paths == [SONG_PREFIX + "/SUN.NTSC"]
    assert demo.memory.native_reads[:2] == [0xC0C8, 0xC0C5]
    assert demo.memory.events[-len(by_tick[0]):] == by_tick[0]
    if region == "pal":
        demo.key("P")
        assert demo.paths[-1] == SONG_PREFIX + "/SUN.PAL"
    assert demo.memory.timer_latch == (10203 if region == "ntsc" else 10154)
    assert demo.memory[0xC48E] == 0x7F  # timer IRQ intentionally disabled
    demo.memory.events.clear()
    calls_before = len(demo.mli_calls)
    peak = 0
    peak_tick = 0
    for tick in range(1, header["duration_ticks"] + 1):
        cycles = demo.tick()
        if cycles > peak:
            peak, peak_tick = cycles, tick
        events = demo.memory.events
        if tick == header["duration_ticks"]:
            # phs_stop adds 18 explicit silence writes after the final record.
            assert events[-18:] == [(4, 3, 0x80), (5, 3, 0x80)] + [
                (chip, reg, 0x3F if reg == 7 else 0)
                for chip in range(4) for reg in (7, 8, 9, 10)]
            events = events[:-18]
        assert events == by_tick[tick], (region, tick, events, by_tick[tick])
        demo.memory.events.clear()
    # Nominal 65C02 instruction cycles only: slot wait states are not modeled.
    # VIA Timer 1's free-running period is its latch value plus two bus cycles.
    period_cycles = demo.memory.timer_latch + 2
    assert peak < period_cycles, (
        f"{region}: tick {peak_tick} needs {peak} nominal CPU cycles, "
        f"not below the {period_cycles}-cycle timer budget")
    assert len(demo.mli_calls) == calls_before, "disk I/O during playback"
    assert demo.get("status") == 2 and not demo.get("phs_error")
    assert demo.get("phs_elapsed", 4) == header["duration_ticks"]
    assert demo.get("phs_mem_pos", 2) == 0x3000 + len(data)
    demo.key("R")
    assert demo.get("phs_playing") and demo.get("phs_elapsed", 4) == 0
    demo.key(" ")
    assert not demo.get("phs_playing") and not demo.get("status")
    return {"file_bytes": len(data), "duration_ticks": header["duration_ticks"],
            "verified_register_writes": len(expected), "peak_poll_cpu_cycles": peak,
            "peak_tick": peak_tick, "timer_latch": demo.memory.timer_latch}


def exercise_return(tiny):
    scenarios = []
    for key in ("Q", "\x1b"):
        demo = Demo(tiny)
        demo.boot()
        demo.memory.events.clear()
        demo.memory.key = ord(key) | 0x80
        demo.run_to(0x2000)
        assert demo.paths[-1] == "/MSDOS/BASIC.SYSTEM"
        assert demo.mli_calls[-5:] == [0xC8, 0xD1, 0xCA, 0xCC, 0xC6]
        assert demo.prefix == "/MSDOS"
        assert bytes(demo.memory[0x2000:0x4800]) == demo.basic_data
        assert not demo.get("phs_playing") and demo.memory[0xC48B] == 0
        assert demo.memory.native_reads[-1] == 0xC0C8
        assert demo.memory.events == [(4, 3, 0x80), (5, 3, 0x80)] + [
            (chip, reg, 0x3F if reg == 7 else 0)
            for chip in range(4) for reg in (7, 8, 9, 10)]
        scenarios.append("success " + ("Escape" if key == "\x1b" else key))
    failures = [
        ("OPEN error", {"basic_errors": {0xC8: 0x46}}, [0xC8, 0x65]),
        ("GET_EOF error", {"basic_errors": {0xD1: 0x27}}, [0xC8, 0xD1, 0xCC, 0x65]),
        ("READ error", {"basic_errors": {0xCA: 0x27}}, [0xC8, 0xD1, 0xCA, 0xCC, 0x65]),
        ("short READ", {"basic_short_read": True}, [0xC8, 0xD1, 0xCA, 0xCC, 0x65]),
        ("CLOSE error", {"basic_errors": {0xCC: 0x27}}, [0xC8, 0xD1, 0xCA, 0xCC, 0x65]),
        ("SET_PREFIX error", {"basic_errors": {0xC6: 0x44}},
         [0xC8, 0xD1, 0xCA, 0xCC, 0xC6, 0x65]),
    ]
    failures.extend((f"bad length ${size:X}", {"basic_size": size},
                     [0xC8, 0xD1, 0xCC, 0x65])
                    for size in (0, 1, 0x27FF, 0x2801, 0x10000, 0x12800))
    for name, options, calls in failures:
        demo = Demo(tiny, **options)
        demo.boot()
        before = len(demo.mli_calls)
        demo.memory.key = ord("Q") | 0x80
        demo.run_to(0x0FFF)
        assert demo.mli_calls[before:] == calls, name
        assert not demo.get("phs_playing"), name
        assert demo.memory[0xC48B] == 0 and demo.memory.native_reads[-1] == 0xC0C8, name
        scenarios.append(name)
    return scenarios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showcase", action="store_true", help="check the /MSDOS demo-disk variant")
    parser.parse_args()
    tiny = encode([(0, 4, 0, 2), (1, 4, 3, 15), (3, 4, 3, 0)], 100, 3)
    for size in (0, 15, 0x8801, 0x10000):
        demo = Demo(tiny, reported_size=size)
        demo.boot()
        assert demo.get("error") == 0xF0 and not demo.get("loaded")
        assert 0xCA not in demo.mli_calls and demo.mli_calls[-1] == 0xCC
    demo = Demo(tiny, short_read=True)
    demo.boot()
    assert demo.get("error") == 0xF0 and demo.mli_calls[-1] == 0xCC
    demo = Demo(tiny, open_error=0x46)
    demo.boot()
    assert demo.get("error") == 0x46 and demo.mli_calls == [0xC8]
    wrong_rate = bytearray(tiny)
    wrong_rate[4] = 60
    demo = Demo(wrong_rate)
    demo.boot()
    assert demo.get("error") == 0xF1 and not demo.get("phs_playing")
    demo = Demo(b"BAD!" + tiny[4:])
    demo.boot()
    assert demo.get("error") == 1 and not demo.get("phs_playing")
    demo = Demo(tiny)
    demo.boot()
    demo.memory.overrun = True
    demo.tick()
    assert demo.get("error") == 0xF2 and not demo.get("phs_playing")
    demo.memory.overrun = False
    if not SHOWCASE:
        demo.memory.key = ord("Q") | 0x80
        demo.run_to(0x0FFF)
        assert demo.mli_calls[-1] == 0x65 and demo.memory.native_reads[-1] == 0xC0C8

    # Directory, boot blocks and each file are checked against the disk source.
    spec = importlib.util.spec_from_file_location("mkdisk", HERE / "../../doom/tools/mkdisk.py")
    disk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disk)
    if not SHOWCASE:
        image = (HERE / "build/RISING.SUN.hdv").read_bytes()
        volume, _, entries = disk.list_volume(image)
        assert volume == "RISING.SUN" and entries[0]["name"] == "SUN.SYSTEM"
        assert entries[0]["type"] == 0xFF and entries[0]["aux"] == 0x2000
        boot, prodos = disk.extract_prodos(HERE / "../../doom/assets/ProDOS_2_4_3.po")
        assert image[:1024] == boot
        for entry in entries:
            expected = prodos if entry["name"] == "PRODOS" else (HERE / "build" / entry["name"]).read_bytes()
            assert disk.read_file(image, entry) == expected
    report = {region: exercise_song((HERE / f"build/SUN.{region.upper()}").read_bytes(), region)
              for region in ("ntsc", "pal")}
    if SHOWCASE:
        report["menu_return"] = exercise_return(tiny)
    (BUILD / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("SYS loader bounds, MLI errors, both regional streams, all MMIO writes, "
          "100 Hz latch, replay/stop/quit and overrun mute passed; " +
          ("relocated BASIC reload success/failure checks passed." if SHOWCASE else
           "standalone disk contents passed."))


if __name__ == "__main__":
    main()
