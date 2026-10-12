"""Execute the patched 6502 speech driver against a bounded hardware model.

This is driver-level validation, not Apple II emulation or an audio-quality test.
The model separates motherboard time from instruction time and supplies VIA
timer/handshake edges, including absent and stalled hardware. Requires py65.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import time

from py65.devices.mpu6502 import MPU


ROOT = Path(__file__).resolve().parents[1]
MODE, STATUS, CANCEL = 0x90F0, 0x90F1, 0x90F2
INIT, PLAY, RETURN = 0x9100, 0x9103, 0x7FFF

# Tom Charlesworth's MIT-licensed play-sc01-using-ssi263 mapping. Kept as an
# independent expectation rather than reading the driver's own table.
SC_TO_SSI = bytes.fromhex(
    "02 0a 0b 00 28 08 08 2f 0e 07 07 07 37 38 24 33 "
    "32 32 2f 10 39 0f 13 13 20 29 25 2c 26 34 25 30 "
    "08 09 03 1b 0e 27 11 07 16 05 28 1d 01 23 0c 0d "
    "10 1a 19 18 11 11 14 14 35 36 1c 0a 01 10 00 00"
)


def original_phrases() -> dict[str, bytes]:
    """Read the three real strings directly from the unchanged DOS source."""
    disk = (ROOT / "Sound_and_Speech_I_Demo_Disk__1982.dsk").read_bytes()

    def sector(track: int, number: int) -> bytes:
        offset = (track * 16 + number) * 256
        return disk[offset:offset + 256]

    track, number = sector(17, 0)[1:3]
    while track:
        catalog = sector(track, number)
        for offset in range(11, 256, 35):
            entry = catalog[offset:offset + 35]
            name = bytes(c & 127 for c in entry[3:33]).decode("ascii").rstrip()
            if entry[0] not in (0, 255) and name == "SPTABLE.OBJ":
                data = bytearray()
                track, number = entry[:2]
                while track:
                    index = sector(track, number)
                    for offset in range(12, 256, 2):
                        tr, sec = index[offset:offset + 2]
                        if tr:
                            data.extend(sector(tr, sec))
                    track, number = index[1:3]
                assert data[:2] == b"\x00\x81"
                table = data[4:4 + int.from_bytes(data[2:4], "little")]
                return {
                    label: bytes(table[start:table.index(0x3F, start) + 1])
                    for label, start in (("train", 0), ("oops", 8), ("speech", 16))
                }
        track, number = catalog[1:3]
    raise AssertionError("Source disk has no SPTABLE.OBJ")


class Hardware:
    def __init__(self, speech: str, *, rate: int = 1, latency: int = 2000, present: bool = True):
        self.ram = bytearray(65536)
        self.speech = speech
        self.present = present
        self.rate = rate
        self.latency = latency
        self.now = 0.0  # motherboard microseconds / 1 MHz ticks
        self.io_count = 0
        self.ifr = [0, 0]
        self.ier = [0, 0]
        self.timer_low = [0, 0]
        self.timer_due: list[float | None] = [None, None]
        self.timer_running = True
        self.ready_due: float | None = None
        self.ssi = [0] * 5
        self.ssi_mode = 0
        self.sc_bytes: list[int] = []
        self.ssi_bytes: list[int] = []
        self.completions = 0
        self.stall_after: int | None = None
        self.escape_at: float | None = None
        self.escape_consumed = False
        self.ay_active = False
        self.ay_resets = 0

    def tick(self) -> None:
        for bank in (0, 1):
            due = self.timer_due[bank]
            if self.timer_running and due is not None and self.now >= due:
                self.ifr[bank] |= 0x20
                self.timer_due[bank] = None
        if self.ready_due is not None and self.now >= self.ready_due:
            bank, mask = (0, 0x10) if self.speech == "sc01" else (1, 0x02)
            self.ifr[bank] |= mask
            self.ready_due = None
            self.completions += 1

    def schedule(self) -> None:
        if self.stall_after is not None and self.completions >= self.stall_after:
            self.ready_due = None
        else:
            self.ready_due = self.now + self.latency

    def __getitem__(self, address):
        if isinstance(address, slice):
            return self.ram[address]
        if 0xC000 <= address < 0xC500:
            self.io_count += 1
            self.tick()
        if 0xC400 <= address < 0xC500 and not self.present:
            return 0xFF
        if address == 0xC000:
            return 0x9B if self.escape_at is not None and self.now >= self.escape_at and not self.escape_consumed else 0
        if address == 0xC010:
            self.escape_consumed = True
            return 0
        for bank, base in enumerate((0xC400, 0xC480)):
            register = address - base
            if register == 0x0D:
                value = self.ifr[bank]
                return value | (0x80 if value & self.ier[bank] else 0)
            if register == 0x0E:
                return self.ier[bank] | 0x80
            if register == 8:
                self.ifr[bank] &= ~0x20
            if register == 1:
                self.ifr[bank] &= ~0x02
        return self.ram[address]

    def __setitem__(self, address, value):
        if isinstance(address, slice):
            self.ram[address] = bytes(value)
            return
        value &= 255
        if 0xC000 <= address < 0xC500:
            self.io_count += 1
            self.tick()
        if 0xC400 <= address < 0xC500 and not self.present:
            return
        if address == 0xC010:
            self.escape_consumed = True
        for bank, base in enumerate((0xC400, 0xC480)):
            register = address - base
            if register == 0x0D:
                self.ifr[bank] &= ~value
            elif register == 0x0E:
                if value & 0x80:
                    self.ier[bank] |= value & 0x7F
                else:
                    self.ier[bank] &= ~(value & 0x7F)
            elif register == 8:
                self.timer_low[bank] = value
            elif register == 9:
                self.ifr[bank] &= ~0x20
                self.timer_due[bank] = self.now + (value << 8 | self.timer_low[bank]) + 2
            elif register == 0:
                self.ifr[bank] &= ~0x10
            elif register == 1:
                self.ifr[bank] &= ~0x02
        if address == 0xC400 and self.speech == "sc01" and self.ram[0xC40C] & 0xE0 == 0xA0:
            self.sc_bytes.append(value & 0x3F)
            self.schedule()
        if address == 0xC480 and not value & 4:
            self.ay_active = False
            self.ay_resets += 1
        if 0xC440 <= address <= 0xC444 and self.speech == "ssi263":
            register = address - 0xC440
            old = self.ssi[register]
            self.ssi[register] = value
            if register == 3 and old & 0x80 and not value & 0x80:
                self.ssi_mode = self.ssi[0] >> 6
                if self.ssi_mode:
                    self.ssi_bytes.append(self.ssi[0] & 0x3F)
                    self.schedule()
                else:
                    self.ready_due = None
            elif register == 0 and self.ssi_mode and not self.ssi[3] & 0x80:
                self.ssi_bytes.append(value & 0x3F)
                self.schedule()
        self.ram[address] = value


def machine(binary: bytes, hardware: str, **kwargs) -> tuple[MPU, Hardware]:
    bus = Hardware(hardware, **kwargs)
    bus.ram[0x9100:0x9100 + len(binary)] = binary
    bus.ram[0x9023:0x902E] = bytes.fromhex("a9 ff 8d 83 c4 a9 07 8d 82 c4 60")
    # Original public AY reset subroutine; do not replace it with a host hook.
    bus.ram[0x9044:0x904F] = bytes.fromhex("a9 00 8d 80 c4 a9 04 8d 80 c4 60")
    return MPU(memory=bus), bus


def call(cpu: MPU, bus: Hardware, address: int, *, limit: int = 25_000_000, before_step=None) -> int:
    cpu.pc, cpu.sp = address, 0xFD
    cpu.x, cpu.y = 0x53, 0xA7
    cpu.a, cpu.p = 0x62, 0xE9
    bus.ram[0x1FE:0x200] = (RETURN - 1).to_bytes(2, "little")
    initial_pointer = bytes(bus.ram[6:8])
    initial_ier = bus.ier[:]
    for steps in range(1, limit + 1):
        if before_step is not None:
            before_step(cpu, bus)
        before, io_before = cpu.processorCycles, bus.io_count
        cpu.step()
        # I/O incurs at least one motherboard cycle. Other CPU cycles scale.
        # Rates are synthetic stress cases, not an Appletini timing model.
        bus.now += (cpu.processorCycles - before) / bus.rate
        bus.now += (bus.io_count - io_before) * (1 - 1 / bus.rate)
        if cpu.pc == RETURN:
            assert cpu.sp == 0xFF, f"unbalanced stack ${cpu.sp:02X}"
            assert (cpu.x, cpu.y) == (0x53, 0xA7), "driver clobbered X/Y"
            assert cpu.a == 0x62, "driver clobbered A"
            assert cpu.p & ~0x30 == 0xE9 & ~0x30, "driver clobbered processor flags"
            assert bus.ram[6:8] == initial_pointer, "driver clobbered phrase pointer"
            assert bus.ier == initial_ier, "driver failed to restore VIA interrupt enables"
            return steps
    raise AssertionError(f"driver did not return: PC=${cpu.pc:04X}, hardware={bus.now:.0f} ticks")


def init(binary: bytes, hardware: str, **kwargs) -> tuple[MPU, Hardware]:
    cpu, bus = machine(binary, hardware, **kwargs)
    call(cpu, bus, INIT)
    assert bus.ram[MODE] == {"none": 0, "sc01": 1, "ssi263": 2}[hardware]
    bus.sc_bytes.clear()
    bus.ssi_bytes.clear()
    return cpu, bus


def phrase(cpu: MPU, bus: Hardware, data: bytes) -> int:
    bus.ram[0x8100:0x8100 + len(data)] = data
    bus.ram[6:8] = b"\x00\x81"
    return call(cpu, bus, PLAY)


def validate(binary: bytes, labels: dict[str, int]) -> list[str]:
    results = []
    phrases = original_phrases()
    cpu, bus = init(binary, "none", present=False)
    assert bus.now < 1000 and bus.ram[STATUS] == 3
    results.append("empty/floating slot fails detection without entering speech waits")
    for rate in (1, 32):
        cpu, bus = init(binary, "none", rate=rate)
        started = bus.now
        phrase(cpu, bus, phrases["speech"])
        assert bus.ram[STATUS] == 3 and bus.now - started < 10000
        results.append(f"{rate}x CPU: missing speech detected; phrase returns unavailable")

        for hardware in ("sc01", "ssi263"):
            cpu, bus = init(binary, hardware, rate=rate)
            for label, data in phrases.items():
                bus.sc_bytes.clear()
                bus.ssi_bytes.clear()
                bus.ay_active = True
                phrase(cpu, bus, data)
                assert bus.ram[STATUS] == 0, (hardware, label, bus.ram[STATUS])
                assert bus.ay_active, "successful speech unexpectedly stopped AY"
                if hardware == "sc01":
                    assert bus.sc_bytes[0] == 0x3F and bus.sc_bytes[-1] == 0x3F
                    actual = [p for p in bus.sc_bytes if p != 0x3F]
                    expected = list(data[:-1])
                else:
                    # Kick and disable use phoneme-zero; data PA entries also
                    # map to zero. Compare the whole expected phrase as a
                    # contiguous interval, permitting only zero at its edges.
                    actual = bus.ssi_bytes
                    expected = [SC_TO_SSI[p & 63] for p in data[:-1]]
                    matches = [i for i in range(len(actual) - len(expected) + 1)
                               if actual[i:i + len(expected)] == expected]
                    assert any(not any(actual[:i]) and not any(actual[i + len(expected):]) for i in matches), (hardware, label, actual, expected)
                    continue
                assert actual == expected, (hardware, label, actual, expected)
            results.append(f"{rate}x CPU: {hardware} emits all three original phrase tables")

            # A 250ms phoneme exceeds typical CPU-count timeout assumptions.
            bus.latency = 250_000
            phrase(cpu, bus, b"\x24\x3f")
            assert bus.ram[STATUS] == 0, "normal long phoneme timed out"
            results.append(f"{rate}x CPU: {hardware} waits for delayed real-time completion")

            bus.latency = 2000
            bus.stall_after = bus.completions + 2
            bus.ay_active = True
            started = bus.now
            phrase(cpu, bus, phrases["speech"])
            assert bus.ram[STATUS] == 2, "stalled speech did not report timeout"
            assert bus.now - started < 650000, "stalled phrase exceeded one timeout period"
            assert not bus.ay_active, "stalled speech left continuous AY sound"
            results.append(f"{rate}x CPU: {hardware} mid-phrase failure stops sound and returns")

            cpu, bus = init(binary, hardware, rate=rate)
            bus.escape_at = bus.now + 500
            bus.ay_active = True
            phrase(cpu, bus, phrases["speech"])
            assert bus.ram[STATUS] == 1 and bus.ram[CANCEL] != 0
            assert bus.escape_consumed and not bus.ay_active
            results.append(f"{rate}x CPU: {hardware} Escape abort consumes key and stops AY")

    # A corrupted pointer/table must not read past one page indefinitely.
    cpu, bus = init(binary, "sc01", latency=1)
    phrase(cpu, bus, b"\x01" * 256)
    assert bus.ram[STATUS] in (2, 3), "unterminated phrase did not fail safely"
    results.append("unterminated 256-byte phrase is bounded")

    # Exercise a non-counting VIA's independent software watchdog at its
    # expiry boundary, avoiding millions of deliberately redundant loops.
    cpu, bus = init(binary, "sc01")
    bus.timer_running = False
    bus.stall_after = bus.completions
    bus.ay_active = True
    bus.ram[6:8] = b"\x00\x81"
    bus.ram[0x8100:0x8102] = b"\x01\x3f"
    seeded = False

    def seed_watchdog(cpu, bus):
        nonlocal seeded
        if not seeded and cpu.pc == labels["wait_loop"]:
            for name, value in (("poll_low", 2), ("poll_mid", 1), ("poll_high", 1)):
                bus.ram[labels[name]] = value
            seeded = True

    call(cpu, bus, PLAY, limit=10000, before_step=seed_watchdog)
    assert seeded and bus.ram[STATUS] == 2 and not bus.ay_active
    results.append("broken VIA timer: software-watchdog expiry stops sound (counter seeded near expiry)")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", nargs="?", type=Path, default=ROOT / "build" / "speech.bin")
    args = parser.parse_args()
    started = time.monotonic()
    label_path = args.binary.with_suffix(".sym")
    if not label_path.exists():
        label_path = args.binary.with_suffix(".labels")
    label_text = label_path.read_text()
    labels = {name: int(value, 16) for name, value in re.findall(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", label_text, re.M)}
    results = validate(args.binary.read_bytes(), labels)
    for result in results:
        print("PASS", result)
    print(f"{len(results)} driver checks passed in {time.monotonic() - started:.1f}s; hardware/audio remain unverified")


if __name__ == "__main__":
    main()
