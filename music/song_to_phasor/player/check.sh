#!/bin/sh
# Run assembled machine code in py65; no Appletini hardware is needed.
set -eu
"${PYTHON:-python3}" - <<'PY'
from pathlib import Path
import struct
from py65.devices.mpu65c02 import MPU

symbols = {}
for line in Path("build/phasor.lbl").read_text().splitlines():
    _, address, name = line.split()
    symbols[name.lstrip(".")] = int(address, 16)
binary = Path("build/phasor.bin").read_bytes()

def stream(records, duration=3, rate=100, flags=0):
    body = b"".join(struct.pack("<HB", delta, len(commands)) + bytes(
        value for pair in commands for value in pair) for delta, commands in records)
    return struct.pack("<4sHHII", b"PHS1", rate, flags, duration, len(records)) + body

class Memory(list):
    def __init__(self):
        super().__init__([0] * 65536)
        self.events = []
        self.io_reads = []
        self.io_writes = []
        self.register = [0] * 4
    def __getitem__(self, key):
        if isinstance(key, int) and 0xC000 <= key < 0xD000:
            self.io_reads.append(key)
        return super().__getitem__(key)
    def __setitem__(self, key, value):
        if isinstance(key, int) and 0xC000 <= key < 0xD000:
            self.io_writes.append((key, value))
            for voice, base in enumerate((0xC420, 0xC440)):
                if base <= key <= base + 4:
                    self.events.append(("ssi", voice, key - base, value))
            if key in (0xC410, 0xC480) and value & 4:
                via = int(key == 0xC480)
                for chip, mask in ((via, 0x10), (via + 2, 0x08)):
                    if not value & mask:
                        data = super().__getitem__(key + 15)
                        if value & 3 == 3:
                            self.register[chip] = data
                        elif value & 3 == 2:
                            self.events.append(("ay", chip, self.register[chip], data))
        super().__setitem__(key, value)

class Player:
    def __init__(self, data):
        self.memory = Memory()
        self.memory[0x2000:0x2000 + len(binary)] = binary
        self.memory[0x1000] = 0x60  # callback RTS, fed by host with arbitrary length
        self.cpu = MPU(memory=self.memory)
        self.data, self.position = data, 0
        self.call("phs_init")
        assert self.memory.io_reads == [0xC0C8, 0xC0C5]
        self.memory[symbols["phs_reader"]:symbols["phs_reader"] + 2] = [0, 0x10]
        self.memory.events.clear()
    def get(self, name, width=1):
        start = symbols[name]
        return int.from_bytes(bytes(self.memory[start:start + width]), "little")
    def put(self, name, value, width=1):
        start = symbols[name]
        self.memory[start:start + width] = value.to_bytes(width, "little")
    def call(self, name):
        self.cpu.stPushWord(0x0FFE)
        self.cpu.pc = symbols[name]
        before = self.cpu.processorCycles
        for _ in range(200000):
            if self.cpu.pc == 0x0FFF:
                assert self.cpu.sp == 0xFF
                return bool(self.cpu.p & self.cpu.CARRY), self.cpu.processorCycles - before
            if self.cpu.pc == 0x1000:
                # Deliberately clobber X/Y: the ABI allows this.
                self.cpu.x, self.cpu.y = 0xD3, 0xA5
                if self.position == len(self.data):
                    self.cpu.p |= self.cpu.CARRY
                else:
                    self.cpu.a = self.data[self.position]
                    self.position += 1
                    self.cpu.p &= ~self.cpu.CARRY
            self.cpu.step()
        raise AssertionError("player failed to return within instruction bound")

def failed(data, error):
    p = Player(data)
    carry, _ = p.call("phs_start")
    assert carry and p.get("phs_error") == error, (p.get("phs_error"), error)
    assert not p.get("phs_playing")
    assert p.memory.events[-18:-16] == [("ssi", 0, 3, 0x80), ("ssi", 1, 3, 0x80)]
    assert p.memory.events[-16:] == [
        ("ay", chip, reg, 0x3F if reg == 7 else 0)
        for chip in range(4) for reg in (7, 8, 9, 10)]
    return p

# First record is synchronous; later records are at exact absolute ticks.
# Both voices' CONTROL transitions and duplicate phoneme writes survive.
initial = [(0x00, 0x21), (0x43, 0x80), (0x40, 0x80), (0x43, 0),
           (0x40, 2), (0x40, 2), (0x53, 0x8F), (0x53, 0x0F)]
later = [(0x10, 0x31), (0x20, 0x42), (0x30, 0x53), (0x54, 0x6A)]
p = Player(stream([(0, initial), (2, later), (1, [])]))
assert not p.call("phs_start")[0]
expected = [("ay" if op < 0x40 else "ssi", op >> 4 if op < 0x40 else (op >> 4) - 4,
             op & 15, value) for op, value in initial]
assert p.memory.events[-len(initial):] == expected
p.memory.events.clear()
assert not p.call("phs_tick")[0] and not p.memory.events
assert not p.call("phs_tick")[0]
assert p.memory.events == [("ay", 1, 0, 0x31), ("ay", 2, 0, 0x42),
                           ("ay", 3, 0, 0x53), ("ssi", 1, 4, 0x6A)]
assert p.get("phs_elapsed", 4) == 2
assert not p.call("phs_tick")[0] and not p.get("phs_playing")
assert p.get("phs_elapsed", 4) == 3 and not p.get("phs_error")
assert 0xC411 not in p.memory.io_reads and 0xC481 not in p.memory.io_reads

# Every truncated header/record fails before that record can touch hardware.
data = stream([(0, [(0x40, 0x55), (0x41, 0x66), (0x00, 0x77)])])
for end in range(len(data)):
    p = failed(data[:end], 2)
    assert ("ssi", 0, 0, 0x55) not in p.memory.events
for opcode in (0x0E, 0x1F, 0x2E, 0x3F, 0x45, 0x5F, 0x60, 0xFF):
    p = failed(stream([(0, [(0x40, 0x55), (opcode, 1)])]), 3)
    assert ("ssi", 0, 0, 0x55) not in p.memory.events
failed(b"BAD!" + stream([])[4:], 1)
failed(stream([], rate=0), 1)
failed(stream([], flags=1), 1)
failed(stream([(4, [])]), 4)
failed(stream([(0, [])] * 65), 5)
failed(stream([(0, [(0x40, 2)] * 255), (0, [(0x40, 2)])]), 5)

# Legal maxima (255 writes; 64 empty records) and same-tick record ordering.
p = Player(stream([(0, [(0x40, 2)] * 255)]))
assert not p.call("phs_start")[0]
assert p.memory.events.count(("ssi", 0, 0, 2)) == 255
p = Player(stream([(0, [])] * 64))
assert not p.call("phs_start")[0]
p = Player(stream([(0, [(0x40, 1)]), (0, [(0x40, 2)])]))
assert not p.call("phs_start")[0]
assert p.memory.events[-2:] == [("ssi", 0, 0, 1), ("ssi", 0, 0, 2)]

# A reader can supply >64 KiB with fixed player RAM usage.
p = Player(stream([(1, [(0x40, 2)] * 200)] * 180, duration=181))
assert len(p.data) > 65536 and not p.call("phs_start")[0]
for _ in range(181):
    assert not p.call("phs_tick")[0]
assert not p.get("phs_playing") and p.position == len(p.data)
assert p.memory.events.count(("ssi", 0, 0, 2)) == 36000

# Cross 16-bit absolute time without iterating 65,000 idle callbacks.
p = Player(stream([(65535, [(0x40, 3)]), (1, [(0x40, 4)])], duration=65537))
assert not p.call("phs_start")[0]
p.put("phs_elapsed", 65534, 4)
assert not p.call("phs_tick")[0]
assert p.memory.events[-1] == ("ssi", 0, 0, 3)
assert not p.call("phs_tick")[0]
assert p.memory.events[-1] == ("ssi", 0, 0, 4)
assert p.get("phs_elapsed", 4) == 65536

# Exhausting records holds silence/state until declared duration; zero length ends now.
p = Player(stream([], duration=0))
assert not p.call("phs_start")[0] and not p.get("phs_playing")
p = Player(stream([(0, [])]))
p.put("phs_reader", 0, 2)
assert p.call("phs_start")[0] and p.get("phs_error") == 6

# Exercise the supplied machine-code memory callback, including its I/O guard.
data = stream([(0, [(0x40, 5)]), (1, [(0x40, 6)])], duration=2)
p = Player(b"")
p.memory[0x7000:0x7000 + len(data)] = data
p.put("phs_mem_pos", 0x7000, 2)
p.put("phs_mem_end", 0x7000 + len(data), 2)
p.put("phs_reader", symbols["phs_memory_read"], 2)
assert not p.call("phs_start")[0]
assert p.memory.events[-1] == ("ssi", 0, 0, 5)
assert not p.call("phs_tick")[0]
assert p.memory.events[-1] == ("ssi", 0, 0, 6)
assert p.get("phs_mem_pos", 2) == 0x7000 + len(data)
for start, end in ((0xC000, 0xC100), (0x0100, 0x0200), (0x7000, 0x7000)):
    p = Player(b"")
    p.put("phs_mem_pos", start, 2)
    p.put("phs_mem_end", end, 2)
    p.put("phs_reader", symbols["phs_memory_read"], 2)
    assert p.call("phs_start")[0] and p.get("phs_error") == 2
    assert p.memory.io_reads == [0xC0C8, 0xC0C5]

# Representative tick cost includes reading/validating the next record.
data = stream([(1, [(0x00, 1), (0x08, 12), (0x41, 70)])] * 2)
p = Player(b"")
p.memory[0x7000:0x7000 + len(data)] = data
p.put("phs_mem_pos", 0x7000, 2)
p.put("phs_mem_end", 0x7000 + len(data), 2)
p.put("phs_reader", symbols["phs_memory_read"], 2)
assert not p.call("phs_start")[0]
_, cycles = p.call("phs_tick")
print(f"PHS1 65C02 checks passed: {len(binary)} code/data bytes; "
      "timing, four AYs, both SSIs, ordered strobes, bounds, >64 KiB stream, budgets")
print(f"Representative 3-write tick with bounded memory reader: {cycles} CPU cycles")
PY
