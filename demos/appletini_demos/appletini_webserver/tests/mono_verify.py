#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute the packaged A2MONO SYS with py65 and mock ProDOS/HTTP services.

The CPU executes the actual browser, overlay loader, graphics routines and
native HTTP FIFO client. The model supplies separate MAIN/AUX banks, files,
keyboard input and deterministic HTTP bodies. It does not model the board's
capture stream, display cadence, TLS implementation or TURBO timing.
"""
from __future__ import annotations
import argparse
import binascii
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mono_disk import extract


def labels(path):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "al":
            result[fields[2].lstrip(".")] = int(fields[1], 16)
    return result


def identity_rom():
    rom = bytearray(256)
    rom[0], rom[1], rom[5] = 0xC9, 0x20, 3
    prefix = binascii.crc_hqx(rom[:254], 0xFFFF)
    for value in range(65536):
        tail = value.to_bytes(2, "little")
        if binascii.crc_hqx(tail, prefix) == 0x95D9:
            rom[254:] = tail
            return bytes(rom)
    raise AssertionError("cannot make controller identity fixture")


def fixture_gif(width=112, height=48):
    """A real two-colour GIF with frequent clears, no external image library."""
    codes = []
    for y in range(height):
        for x in range(width):
            black = x in (0, width - 1) or y in (0, height - 1)
            black |= (x // 7 + y // 6) % 2 == 0
            codes.extend((4, int(not black)))
    codes.append(5)
    data = bytearray()
    bits = value = 0
    for code in codes:
        value |= code << bits
        bits += 3
        while bits >= 8:
            data.append(value & 255)
            value >>= 8
            bits -= 8
    if bits:
        data.append(value)
    result = bytearray(b"GIF89a" + struct.pack("<HH", width, height) +
                       b"\x80\0\0\0\0\0\xff\xff\xff,\0\0\0\0" +
                       struct.pack("<HH", width, height) + b"\0\x02")
    for at in range(0, len(data), 255):
        block = data[at:at + 255]
        result.append(len(block))
        result.extend(block)
    return bytes(result + b"\0;")


class Memory:
    def __init__(self, fixtures, fragment=97):
        self.main = bytearray(65536)
        self.aux = [bytearray([0xA5]) * 65536 for _ in range(8)]
        self.bank = 0
        self.ramrd = self.ramwrt = self.altzp = self.store80 = self.page2 = False
        self.text = True
        self.hires = self.col80 = self.mixed = False
        self.intcxrom, self.selected = True, False
        self.rom = identity_rom()
        self.incoming, self.response, self.at = [], [], 0
        self.generation, self.vbl_reads = 17, 0
        self.body, self.url, self.content_type = b"", "", "text/html"
        self.requests, self.controls = [], []
        self.redirect_pending = []
        self.redirect_active = False
        self.fixtures, self.fragment = fixtures, fragment
        self.cpu = None
        self.hold_commits = 0
        self.lc = bytearray(0x3000)
        self.lc_read = self.lc_write = False

    def __len__(self):
        return 65536

    def auxiliary(self, address, write):
        if address < 0x200:
            return self.altzp
        if self.store80 and (0x400 <= address < 0x800 or
                            self.hires and 0x2000 <= address < 0x4000):
            return self.page2
        return self.ramwrt if write else self.ramrd

    def __getitem__(self, address):
        if isinstance(address, slice):
            return [self[i] for i in range(*address.indices(65536))]
        address &= 65535
        if address == 0xCFFF:
            self.selected = False
            return 0
        if 0xC700 <= address < 0xC800:
            if self.intcxrom:
                return 0xAA
            self.selected = True
            return self.rom[address - 0xC700]
        if address in (0xCFF0, 0xCFF1):
            self.guard_fifo()
            if address == 0xCFF1:
                return 0x80
            assert self.at < len(self.response), "FIFO underrun"
            return self.response[self.at]
        if 0xC000 <= address < 0xC100:
            if address == 0xC015:
                return 0x80 if self.intcxrom else 0
            if address == 0xC019:
                self.vbl_reads += 1
                return ((self.vbl_reads // 16) & 1) * 128
            status = {0xC013: self.ramrd, 0xC014: self.ramwrt,
                      0xC016: self.altzp, 0xC018: self.store80,
                      0xC01A: self.text, 0xC01B: self.mixed,
                      0xC01C: self.page2, 0xC01D: self.hires,
                      0xC01F: self.col80}
            if address in status:
                return int(status[address]) * 128
            self.switch(address)
            return 0
        if address >= 0xD000 and self.lc_read:
            return self.lc[address - 0xD000]
        if address >= 0xC000:
            return self.main[address]
        bank = self.aux[self.bank] if self.auxiliary(address, False) else self.main
        return bank[address]

    def __setitem__(self, address, value):
        if isinstance(address, slice):
            for i, byte in zip(range(*address.indices(65536)), value):
                self[i] = byte
            return
        address, value = address & 65535, value & 255
        if address in (0xCFF0, 0xCFF1, 0xCFF2):
            self.guard_fifo()
            if address == 0xCFF0:
                self.incoming.append(value)
            elif address == 0xCFF2:
                assert self.at < len(self.response), "FIFO pop underrun"
                self.at += 1
            else:
                assert value == 2
                self.submit(bytes(self.incoming))
                self.incoming.clear()
            return
        if 0xC000 <= address < 0xC100:
            self.switch(address, value)
            return
        if address >= 0xD000 and self.lc_write:
            self.lc[address - 0xD000] = value
            return
        if address >= 0xC000:
            return
        bank = self.aux[self.bank] if self.auxiliary(address, True) else self.main
        bank[address] = value
        if bank is self.main and address == 0x407C and value == 1:
            self.hold_commits += 1

    def switch(self, address, value=0):
        changes = {0xC000: ("store80", False), 0xC001: ("store80", True),
                   0xC002: ("ramrd", False), 0xC003: ("ramrd", True),
                   0xC004: ("ramwrt", False), 0xC005: ("ramwrt", True),
                   0xC006: ("intcxrom", False), 0xC007: ("intcxrom", True),
                   0xC008: ("altzp", False), 0xC009: ("altzp", True),
                   0xC00C: ("col80", False), 0xC00D: ("col80", True),
                   0xC050: ("text", False), 0xC051: ("text", True),
                   0xC052: ("mixed", False), 0xC053: ("mixed", True),
                   0xC054: ("page2", False), 0xC055: ("page2", True),
                   0xC056: ("hires", False), 0xC057: ("hires", True)}
        if address in changes:
            name, state = changes[address]
            setattr(self, name, state)
        if address == 0xC073:
            self.bank = value % len(self.aux)
        if 0xC080 <= address <= 0xC08F:
            self.lc_read = address & 3 in (0, 3)
            self.lc_write = address & 3 in (1, 3)

    def guard_fifo(self):
        assert not self.intcxrom and self.selected, "FIFO without C8 ownership"
        assert self.cpu.p & 4, "FIFO request with IRQ enabled"

    def answer(self, payload):
        self.response = [0, len(payload) & 255, len(payload) >> 8, *payload]
        self.at = 0

    def submit(self, packet):
        assert packet[1:5] == bytes((3, 0, 0, 0))
        self.at = 0
        if packet[0] == 4:
            size = int.from_bytes(packet[10:12], "little")
            payload = packet[12:]
            assert len(payload) == size and payload[0] == 1
            self.controls.append(payload[1])
            if payload[1] == 1:
                m = payload[3]
                u = int.from_bytes(payload[4:6], "little")
                method = payload[12:12 + m].decode()
                request_url = payload[12 + m:12 + m + u].decode()
                assert method == "GET", method
                self.requests.append(request_url)
                assert request_url in self.fixtures, "unexpected URL: " + request_url
                fixture = self.fixtures[request_url]
                self.content_type, self.body = fixture[:2]
                self.url = fixture[2] if len(fixture) > 2 else request_url
                self.redirect_pending=list(fixture[3]) if len(fixture)>3 else []
                self.redirect_active=False
                self.generation = (self.generation + 1) & 255 or 1
            else:
                assert payload[1] == 2, payload[1]
            self.response = [0]
            return
        assert packet[0] == 0 and len(packet) == 10
        selector = packet[5]
        if selector == 0x82:
            code=self.redirect_pending.pop(0) if self.redirect_pending else 200
            self.redirect_active=300<=code<400
            reply = bytearray(64)
            reply[:10] = b"ATNH" + bytes((1, 64, 31, self.generation,
                                         2 if self.redirect_active else 3, 0))
            reply[12:14] = code.to_bytes(2, "little")
            reply[16:20] = len(self.body).to_bytes(4, "little")
            reply[20:24] = len(self.body).to_bytes(4, "little")
            reply[28:30] = len(self.url).to_bytes(2, "little")
            reply[30:32] = len(self.content_type).to_bytes(2, "little")
            reply[44:48] = (1017812).to_bytes(4, "little")
            self.answer(reply)
            return
        data = {0x83: self.body, 0x85: self.url.encode(),
                0x86: self.content_type.encode()}[selector]
        if selector==0x83:assert not self.redirect_active,'body read during an intermediate redirect'
        offset = int.from_bytes(packet[6:8], "little")
        capacity = int.from_bytes(packet[8:10], "little")
        chunk = data[offset:offset + min(capacity - 8, self.fragment)]
        end = offset + len(chunk) == len(data)
        reply = (bytes((self.generation, 2 if end else 1)) +
                 offset.to_bytes(4, "little") + len(chunk).to_bytes(2, "little") + chunk)
        self.answer(reply)


def framebuffer(memory):
    """Decode both AUX/MAIN page pairs, seven LSB-first pixels per byte."""
    packed = bytearray()
    for y in range(384):
        row = y // 2
        address = (0x4000 if y & 1 else 0x2000) + (row & 7) * 1024 + ((row >> 3) & 7) * 128 + (row >> 6) * 40
        scanline = []
        for column in range(80):
            bank = memory.main if column & 1 else memory.aux[0]
            value = bank[address + column // 2]
            scanline.extend((value >> bit) & 1 for bit in range(7))
        for x in range(0, 560, 8):
            packed.append(sum(scanline[x + bit] << (7 - bit) for bit in range(8)))
    return bytes(packed)


def save_capture(path, memory):
    pixels = framebuffer(memory)
    rows = b"".join(b"\0" + pixels[y * 70:(y + 1) * 70] for y in range(384))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 560, 384, 1, 0, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)
    assert len(set(pixels)) > 2, "capture has no text or graphics detail"
    return hashlib.sha256(pixels).hexdigest()


class Runner:
    def __init__(self, out, fixture_url, fragment):
        from py65.devices.mpu6502 import MPU
        self.symbols = labels(out / "A2MONO.lbl")
        self.files = {name: (out / name).read_bytes() for name in ("MONO.WEB", "MONO.GIF", "MONO.PNG", "MONO.JPG", "MONO.NET") if (out / name).is_file()}
        page = (b"<html><title>Native HTTPS fixture</title><h1>HTTPS + INLINE IMAGE</h1>"
                b"<p>This page passes through the real 6502 native HTTP client.</p>"
                b"<img src='https://fixture.test/checker.gif' width='112' height='48'>"
                b"<p><a href='about:demo'>Return to the demo</a></p></html>")
        self.memory = Memory({fixture_url: ("text/html", page),
                              "https://fixture.test/checker.gif": ("image/gif", fixture_gif())}, fragment)
        program = (out / "A2MONO.bin").read_bytes()
        self.memory.main[0x2000:0x2000 + len(program)] = program
        self.memory.main[0xBF00] = 0x4C
        self.memory.main[0xBF58] = 0xC0
        self.memory.main[0xBF6F] = 1
        self.cpu = MPU(memory=self.memory, pc=0x2000)
        self.memory.cpu = self.cpu
        self.cpu.p, self.cpu.sp = 0x20, 0xFF
        self.steps, self.opened, self.ref = 0, {}, 1
        self.prefix=b'/A2MONO'
        self.mli_calls=[]
        self.memory.main[0xBF30]=0x70
        self.input = list(("g" + fixture_url + "\r" + "iq").encode())
        self.capture_at = {0: "demo", len(self.input) - 1: "https"}
        self.keyboard_calls = 0
        self.captures = []
        self.out = out
        self.ui_hook = None
        self.io_poison_calls = 0

    def valid_mli_buffer(self,address,length,io=False):
        # Real ProDOS rejects OPEN file buffers below $0800, even when the
        # bitmap only marks pages 0/1. GET_PREFIX may use text-screen RAM.
        if address<(0x0800 if io else 0x0200) or address+length>0xBF00:
            return False
        for page in range(address>>8,((address+max(1,length)-1)>>8)+1):
            if self.memory.main[0xBF58+(page>>3)] & (0x80>>(page&7)):
                return False
        return True

    def poison_iobuf(self,address):
        # OPEN and READ own all 1024 bytes, including the index half.
        # Poison it so codec/loader lifetime tests cannot rely on zero RAM.
        self.io_poison_calls+=1
        seed=self.io_poison_calls*37
        self.memory.main[address:address+1024]=bytes((seed+i*13)&255 for i in range(1024))

    def rts(self):
        self.cpu.pc = (self.cpu.stPopWord() + 1) & 65535

    def mli(self):
        cpu, main = self.cpu, self.memory.main
        ret = main[0x100 + ((cpu.sp + 1) & 255)] | main[0x100 + ((cpu.sp + 2) & 255)] << 8
        cmd = main[ret + 1]
        self.mli_calls.append(cmd)
        p = main[ret + 2] | main[ret + 3] << 8
        def w(i): return main[p + i] | main[p + i + 1] << 8
        def put(i, n): main[p + i:p + i + 2] = n.to_bytes(2, "little")
        if cmd == 0x65:
            return True
        error = 0
        if cmd == 0xC7:
            at = w(1)
            path = self.prefix
            if not self.valid_mli_buffer(at,65):error=0x56
            else:main[at:at + len(path) + 1] = bytes((len(path),)) + path
        elif cmd == 0xC6:
            at=w(1)
            self.prefix=bytes(main[at+1:at+1+main[at]])
        elif cmd == 0xC5:
            assert main[p+1]==0x70,'ON_LINE must select the boot device'
            at=w(2)
            if not self.valid_mli_buffer(at,16):error=0x56
            else:main[at:at+7]=b'\x06A2MONO'
        elif cmd == 0xC8:
            at = w(1)
            name = bytes(main[at + 1:at + 1 + main[at]]).decode().split("/")[-1].upper()
            buffer=w(3)
            if buffer&255 or not self.valid_mli_buffer(buffer,1024,io=True):
                error=0x56
            elif name not in self.files:
                error = 0x46
            else:
                self.poison_iobuf(buffer)
                self.opened[self.ref] = [self.files[name], 0, name, buffer]
                main[p + 5] = self.ref
                self.ref += 1
        elif cmd == 0xCA:
            data, pos, name, buffer = self.opened[main[p + 1]]
            dest = w(2)
            if not self.valid_mli_buffer(dest,w(4)):error=0x56
            else:
                self.poison_iobuf(buffer)
                count = min(w(4), len(data) - pos)
                main[dest:dest + count] = data[pos:pos + count]
                self.opened[main[p + 1]][1] += count
                put(6, count)
                if not count:error = 0x4C
        elif cmd == 0xCC:
            if main[p + 1]:
                self.opened.pop(main[p + 1], None)
            else:
                self.opened.clear()
        elif cmd == 0xD1:
            main[p + 2:p + 5] = len(self.opened[main[p + 1]][0]).to_bytes(3, "little")
        elif cmd == 0xCE:
            self.opened[main[p + 1]][1] = int.from_bytes(main[p + 2:p + 5], "little")
        else:
            raise AssertionError(("unexpected MLI", hex(cmd)))
        cpu.a = error
        cpu.p = (cpu.p | 1) if error else (cpu.p & ~1)
        cpu.pc = (cpu.stPopWord() + 4) & 65535
        return False

    def run(self, limit):
        while self.steps < limit:
            pc = self.cpu.pc
            if self.ui_hook is not None and self.ui_hook(self):
                pass
            elif pc == self.symbols.get("_cgetc"):
                assert self.input, "browser requested unexpected extra input"
                key = self.input.pop(0)
                if self.keyboard_calls in self.capture_at:
                    name = self.capture_at[self.keyboard_calls]
                    digest = save_capture(self.out / (name + ".png"), self.memory)
                    self.captures.append({"name": name, "sha256": digest,
                                          "instructions": self.steps, "cycles": self.cpu.processorCycles,
                                          "requests":list(self.memory.requests)})
                self.cpu.a, self.cpu.x = key, 0
                self.rts()
                self.keyboard_calls += 1
            elif pc == 0xBF00:
                if self.mli():
                    return
            elif pc == 0xD39A and not self.memory.lc_read:
                # Applesoft BLTU2: source [$9B,$96), destination ends at $94.
                m = self.memory.main
                source = m[0x9B] | m[0x9C] << 8
                end = m[0x96] | m[0x97] << 8
                dest = m[0x94] | m[0x95] << 8
                size = end - source
                assert 0 <= size <= 0xC00
                assert 0xD000 <= dest - size <= dest <= 0x10000
                self.memory.lc[dest - size - 0xD000:dest - 0xD000] = m[source:end]
                self.rts()
            elif pc >= 0xD000 and not self.memory.lc_read:
                # Other startup ROM calls are outside this focused model.
                self.rts()
            else:
                assert self.memory[pc] != 0, ("BRK", hex(pc), self.steps)
                self.cpu.step()
            self.steps += 1
            if self.steps % 5_000_000 == 0:
                print("CPU", self.steps, "instructions; PC", hex(self.cpu.pc),
                      "HTTP requests", len(self.memory.requests), flush=True)
        raise AssertionError(("instruction budget", self.steps, hex(self.cpu.pc)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build" / "mono")
    parser.add_argument("--steps", type=int, default=50_000_000)
    parser.add_argument("--fragment", type=int, default=97)
    parser.add_argument("--url", default="https://fixture.test/page")
    args = parser.parse_args()
    out = args.build.resolve()
    runner = Runner(out, args.url, args.fragment)
    runner.run(args.steps)
    assert not runner.opened, "overlay file leaked"
    assert runner.memory.requests == [args.url, "https://fixture.test/checker.gif"], runner.memory.requests
    assert len(runner.captures) == 2
    assert runner.captures[0]["sha256"] != runner.captures[1]["sha256"], "navigation did not change the screen"
    assert runner.memory.intcxrom and not runner.memory.selected, "C8 mapping leaked"
    assert not runner.memory.ramrd and not runner.memory.ramwrt and runner.memory.bank == 0, "AUX mapping leaked"
    disk = (out / "A2MONO.po").read_bytes()
    assert extract(disk, "A2MONO.SYSTEM") == (out / "A2MONO.bin").read_bytes()
    report = {"model": "py65 NMOS6502 + mocked ProDOS/native HTTP FIFO",
              "board_evidence": False, "instructions": runner.steps,
              "cpu_cycles": runner.cpu.processorCycles,
              "nominal_33mhz_seconds": runner.cpu.processorCycles / (100_000_000 / 3),
              "requests": runner.memory.requests, "captures": runner.captures,
              "http_fragment": args.fragment}
    (out / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
