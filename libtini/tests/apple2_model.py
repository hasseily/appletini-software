"""Focused Apple //e memory model for compiled 65C02 tests.

This is a switch and memory model, not a video or Appletini timing emulator.
The target is the code under test; this model supplies independent main/aux
storage and observable CPU writes. No private SmartPort service exists here.
"""
from __future__ import annotations


class Apple2Memory:
    def __init__(self, banks: int = 4):
        self.main = bytearray(65536)
        self.aux = [bytearray([0xA5]) * 65536 for _ in range(banks)]
        self.bank = 0
        self.ramrd = False
        self.ramwrt = False
        self.altzp = False
        self.store80 = False
        self.page2 = False
        self.hires = False
        self.text = True
        self.mixed = False
        self.col80 = False
        self.altchar = False
        self.shr = 0
        self.keyboard = 0
        self.output = bytearray()
        self.io_writes: list[tuple[int, int]] = []
        self.io_reads: set[int] = set()
        self.video_writes = 0
        self.cpu = None
        self.auto_key = False
        self.published_screen = None
        self.display_levels = []

    def __len__(self):
        return 65536

    def _auxiliary(self, address: int, write: bool) -> bool:
        if address < 0x200:
            return self.altzp
        if self.store80:
            if 0x400 <= address < 0x800:
                return self.page2
            if self.hires and 0x2000 <= address < 0x4000:
                return self.page2
        return self.ramwrt if write else self.ramrd

    def __getitem__(self, address):
        if isinstance(address, slice):
            return [self[i] for i in range(*address.indices(65536))]
        address &= 0xFFFF
        if 0xC000 <= address < 0xC100:
            return self._read_io(address)
        if address >= 0xC100:
            return self.main[address]
        store = self.aux[self.bank] if self._auxiliary(address, False) else self.main
        return store[address]

    def __setitem__(self, address, value):
        if isinstance(address, slice):
            for i, byte in zip(range(*address.indices(65536)), value):
                self[i] = byte
            return
        address &= 0xFFFF
        value &= 0xFF
        if 0xC000 <= address < 0xC100:
            self.io_writes.append((address, value))
            self._write_io(address, value)
            return
        if address >= 0xC100:
            return
        store = self.aux[self.bank] if self._auxiliary(address, True) else self.main
        store[address] = value
        if store is not self.main and self.bank == 0 and 0x2000 <= address < 0xA000:
            self.video_writes += 1

    def _read_io(self, address: int) -> int:
        self.io_reads.add(address)
        status = {
            0xC013: self.ramrd, 0xC014: self.ramwrt,
            0xC016: self.altzp, 0xC018: self.store80,
            0xC01A: self.text, 0xC01B: self.mixed,
            0xC01C: self.page2, 0xC01D: self.hires,
            0xC01E: self.altchar,
            0xC01F: self.col80,
        }
        if address in status:
            return 0x80 if status[address] else 0
        if address == 0xC000:
            if self.auto_key and self.video_writes and self.shr == 0xC1:
                self.published_screen = bytes(self.aux[0][0x2000:0xA000])
                self.keyboard = 0xC1
            return self.keyboard
        if address == 0xC010:
            self.keyboard &= 0x7F
            return self.keyboard
        if address == 0xC019:
            if self.display_levels:
                return 0x80 if self.display_levels.pop(0) else 0
            # 60 Hz synthetic cadence, only to terminate display-edge polling.
            cycles = self.cpu.processorCycles if self.cpu else 0
            return 0x80 if (cycles // 12000) % 2 else 0
        if address == 0xC029:
            return self.shr
        # Standard video switches react to reads and writes.
        if 0xC050 <= address <= 0xC057:
            self._video_switch(address)
        return 0

    def _video_switch(self, address: int):
        names = {0xC050: ("text", False), 0xC051: ("text", True),
                 0xC052: ("mixed", False), 0xC053: ("mixed", True),
                 0xC054: ("page2", False), 0xC055: ("page2", True),
                 0xC056: ("hires", False), 0xC057: ("hires", True)}
        name, value = names[address]
        setattr(self, name, value)

    def _write_io(self, address: int, value: int):
        switches = {0xC000: ("store80", False), 0xC001: ("store80", True),
                    0xC002: ("ramrd", False), 0xC003: ("ramrd", True),
                    0xC004: ("ramwrt", False), 0xC005: ("ramwrt", True),
                    0xC008: ("altzp", False), 0xC009: ("altzp", True),
                    0xC00C: ("col80", False), 0xC00D: ("col80", True),
                    0xC00E: ("altchar", False), 0xC00F: ("altchar", True)}
        if address in switches:
            name, state = switches[address]
            setattr(self, name, state)
        elif address == 0xC073:
            self.bank = value % len(self.aux)
        elif address == 0xC029:
            self.shr = value
        elif 0xC050 <= address <= 0xC057:
            self._video_switch(address)


def read_labels(path):
    """Read ld65 -Ln VICE labels without relying on fixed linked addresses."""
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "al":
            result[fields[2].lstrip(".")] = int(fields[1], 16)
    return result
