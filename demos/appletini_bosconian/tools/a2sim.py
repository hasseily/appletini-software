#!/usr/bin/env python3
"""A small Apple //e model for headless tests (py65 65C02 core).

Copied from the Bilestoad SHR port (demos/bilestoad/tools/a2sim.py on the
bilestoad-shr-port branch) with paddles and buttons added for Bosconian.

It models what the game touches: main and auxiliary memory with the //e
bank switches, RamWorks banks through $C073, the language card, the
keyboard, VBL at $C019, the speaker, NEWVIDEO at $C029, the game buttons
and paddles ($C061-$C067, $C070), and a Phasor in slot 4 that follows the
select rules of appletini-one/hdl/apple/mockingboard.sv. It renders HGR,
SHR and text to images or strings.

Time is counted in CPU cycles. `speed` is the accelerator factor: one video
frame lasts 17030 * speed CPU cycles, as under the Appletini vTW.
"""

from pathlib import Path

from py65.devices.mpu65c02 import MPU

FRAME_CYCLES_1MHZ = 17030          # 262 lines * 65 cycles (NTSC)
VBL_START_CYCLE = 192 * 65         # first cycle of vertical blanking


class Via:
    def __init__(self):
        self.orb = self.ora = self.ddrb = self.ddra = 0


class Phasor:
    """Two VIAs, four AY chips, native and Mockingboard decode."""

    MOCKINGBOARD, NATIVE = 0, 5

    def __init__(self, bus_clock=lambda: 0):
        self.bus_clock = bus_clock                  # 1 MHz bus cycles
        self.t1_start = [0, 0]
        self.mode = self.MOCKINGBOARD
        self.via = [Via(), Via()]
        self.ay = [[0] * 16 for _ in range(4)]      # via*2 + chip
        self.latched = [0, 0, 0, 0]
        self.selected = [[False, False], [False, False]]
        self.log = []                               # (chip, reg, value)
        # SSI-263 at $C44x in native mode: DUR/RATE registers and the time
        # of the last phoneme, for the D7 (phoneme done) status
        self.ssi_dur = 0xC0
        self.ssi_rate = 0
        self.ssi_started = None
        self.ssi_phonemes = 0

    def mode_switch(self, address):
        if address & 8:
            self.mode = self.MOCKINGBOARD
        self.mode |= address & 7

    def _vias_for(self, address):
        if self.mode == self.NATIVE:
            hit = []
            if address & 0x10:
                hit.append(0)
            if address & 0x80:
                hit.append(1)
            return hit
        return [1 if address & 0x80 else 0]

    def _ssi_hit(self, address):
        return self.mode == self.NATIVE and (address & 0xF8) == 0x40

    def ssi_write(self, reg, value):
        if reg == 0:
            self.ssi_dur = value
            self.ssi_started = self.bus_clock()
            self.ssi_phonemes += 1
        elif reg == 2:
            self.ssi_rate = value
        elif reg == 3 and value & 0x80:             # power down
            self.ssi_started = None

    def ssi_read(self):
        # phoneme length: (4 - DR) * (16 - R) * 4096 XCK/2 edges, ~1 MHz
        if self.ssi_started is None:
            return 0x00
        ticks = (4 - (self.ssi_dur >> 6)) * (16 - (self.ssi_rate >> 4)) * 4096
        return 0x80 if self.bus_clock() - self.ssi_started >= ticks else 0x00

    def write(self, address, value):
        if self._ssi_hit(address):
            self.ssi_write(address & 7, value)
            return
        for index in self._vias_for(address):
            via = self.via[index]
            reg = address & 0x0F
            if reg == 0:
                via.orb = value
                self._port_b(index)
            elif reg == 1:
                via.ora = value
            elif reg == 2:
                via.ddrb = value
            elif reg == 3:
                via.ddra = value
            elif reg == 5:                          # T1C-H: start timer 1
                self.t1_start[index] = self.bus_clock()

    def _t1(self, index):
        # Free-running from $FFFF; the reload detail is not modelled.
        return (0xFFFF - (self.bus_clock() - self.t1_start[index])) & 0xFFFF

    def read(self, address):
        if self._ssi_hit(address):
            return self.ssi_read()
        for index in self._vias_for(address):
            via = self.via[index]
            reg = address & 0x0F
            if reg == 0:
                return via.orb
            if reg == 1:
                return self._read_port_a(index)
            if reg == 2:
                return via.ddrb
            if reg == 3:
                return via.ddra
            if reg == 4:
                return self._t1(index) & 0xFF
            if reg == 5:
                return self._t1(index) >> 8
        return 0xFF

    def _chip_selects(self, index):
        bus = self.via[index].orb & self.via[index].ddrb
        if self.mode == self.NATIVE:
            return not bus & 0x10, not bus & 0x08
        return True, False

    def _read_port_a(self, index):
        via = self.via[index]
        bus = via.orb & via.ddrb
        if via.ddra == 0 and (bus & 7) == 5:
            cs0, cs1 = self._chip_selects(index)
            chip = index * 2 + (0 if cs0 else 1)
            return self.ay[chip][self.latched[chip] & 15]
        return via.ora

    def _port_b(self, index):
        via = self.via[index]
        bus = via.orb & via.ddrb
        cs0, cs1 = self._chip_selects(index)
        function = bus & 7
        native = self.mode == self.NATIVE
        if not bus & 4:                             # reset
            for chip in (index * 2, index * 2 + 1):
                self.ay[chip] = [0] * 16
            self.selected[index] = [False, False]
        elif function == 7:                         # latch address
            if not native:
                self.latched[index * 2] = via.ora
                return
            if cs0 or cs1:
                self.latched[index * 2] = via.ora
            if cs1:
                self.latched[index * 2 + 1] = via.ora
                self.selected[index] = [True, True]
            elif cs0:
                self.selected[index] = [True, False]
        elif function == 6:                         # write data
            targets = []
            if not native:
                targets.append(index * 2)
            else:
                if cs0 and self.selected[index][0]:
                    targets.append(index * 2)
                if (cs0 or cs1) and self.selected[index][1]:
                    targets.append(index * 2 + 1)
            for chip in targets:
                reg = self.latched[chip] & 15
                self.ay[chip][reg] = via.ora
                self.log.append((chip, reg, via.ora))


class Machine:
    def __init__(self, rom_path, speed=1, phasor_slot=4):
        self.rom = Path(rom_path).read_bytes()      # $C000-$FFFF
        assert len(self.rom) == 0x4000
        self.speed = speed
        self.frame_cycles = FRAME_CYCLES_1MHZ * speed
        self.main = bytearray(0x10000)
        self.aux_banks = {0: bytearray(0x10000)}
        self.bank = 0
        self.aux = self.aux_banks[0]
        self.lc = {False: bytearray(0x4000), True: bytearray(0x4000)}
        self.lc_bank1 = {False: bytearray(0x1000), True: bytearray(0x1000)}
        self.lc_read = False
        self.lc_write = False
        self.lc_prewrite = False
        self.lc_bank2 = True
        self.sw = dict(store80=False, ramrd=False, ramwrt=False,
                       intcxrom=False, altzp=False, slotc3rom=False,
                       col80=False, altchar=False, text=True, mixed=False,
                       page2=False, hires=False)
        self.newvideo = 0
        self.keys = []
        self.key_latch = 0
        self.buttons = [0, 0, 0]
        self.paddles = [1400, 1400, 1400, 1400]   # 558 timer, 1 MHz cycles
        self.paddle_trigger = -100000
        self.speaker_toggles = 0
        self.phasor = Phasor(lambda: self.cycles // self.speed)
        self.phasor_slot = phasor_slot
        self.video_writes = 0       # writes that would use the 1 MHz bus
        self.io_accesses = 0
        self.mpu = MPU(memory=self)
        self.booted_zero_page()

    def booted_zero_page(self):
        """Set the monitor's text window and I/O hooks as the boot ROM does."""
        for address, value in ((0x20, 0), (0x21, 40), (0x22, 0), (0x23, 24),
                               (0x32, 0xFF), (0x36, 0xF0), (0x37, 0xFD),
                               (0x38, 0x1B), (0x39, 0xFD)):
            self.main[address] = value

    # -- time ------------------------------------------------------------
    @property
    def cycles(self):
        return self.mpu.processorCycles

    def in_vbl(self):
        return (self.cycles % self.frame_cycles) >= VBL_START_CYCLE * self.speed

    def frame_number(self):
        return self.cycles // self.frame_cycles

    # -- memory ----------------------------------------------------------
    def _aux_selected(self, address, flag):
        sw = self.sw
        if sw["store80"]:
            if 0x0400 <= address < 0x0800:
                return sw["page2"]
            if sw["hires"] and 0x2000 <= address < 0x4000:
                return sw["page2"]
        return sw[flag]

    def __getitem__(self, address):
        if address < 0x0200:
            return (self.aux if self.sw["altzp"] else self.main)[address]
        if address < 0xC000:
            if self._aux_selected(address, "ramrd"):
                return self.aux[address]
            return self.main[address]
        if address < 0xC100:
            return self._io_read(address)
        if address < 0xD000:
            slot = (address >> 8) & 7
            if (not self.sw["intcxrom"] and slot == self.phasor_slot):
                return self.phasor.read(address)
            return self.rom[address - 0xC000]
        if self.lc_read:
            if address < 0xE000 and not self.lc_bank2:
                return self.lc_bank1[self.sw["altzp"]][address - 0xD000]
            return self.lc[self.sw["altzp"]][address - 0xC000]
        return self.rom[address - 0xC000]

    def __setitem__(self, address, value):
        value &= 0xFF
        if address < 0x0200:
            (self.aux if self.sw["altzp"] else self.main)[address] = value
            return
        if address < 0xC000:
            to_aux = self._aux_selected(address, "ramwrt")
            if to_aux:
                self.aux[address] = value
                if self.bank == 0 and (0x0400 <= address < 0x0C00 or
                                       0x2000 <= address < 0xA000):
                    self.video_writes += 1
            else:
                self.main[address] = value
                if 0x0400 <= address < 0x0C00 or 0x2000 <= address < 0x6000:
                    self.video_writes += 1
            return
        if address < 0xC100:
            self._io_write(address, value)
            return
        if address < 0xD000:
            if ((address >> 8) & 7) == self.phasor_slot:
                self.phasor.write(address, value)
            return
        if self.lc_write:
            if address < 0xE000 and not self.lc_bank2:
                self.lc_bank1[self.sw["altzp"]][address - 0xD000] = value
            else:
                self.lc[self.sw["altzp"]][address - 0xC000] = value

    # -- I/O -------------------------------------------------------------
    SWITCH_PAIRS = ("store80", "ramrd", "ramwrt", "intcxrom", "altzp",
                    "slotc3rom", "col80", "altchar")
    STATUS = {0x13: "ramrd", 0x14: "ramwrt", 0x15: "intcxrom",
              0x16: "altzp", 0x17: "slotc3rom", 0x18: "store80",
              0x1A: "text", 0x1B: "mixed", 0x1C: "page2", 0x1D: "hires",
              0x1E: "altchar", 0x1F: "col80"}

    def _keyboard(self):
        if not self.key_latch & 0x80 and self.keys:
            when, key = self.keys[0]
            if self.cycles >= when:
                self.keys.pop(0)
                self.key_latch = key | 0x80
        return self.key_latch

    def _video_switch(self, low):
        name = ("text", "mixed", "page2", "hires")[(low - 0x50) >> 1]
        self.sw[name] = bool(low & 1)

    def _lc_switch(self, low, is_read):
        self.lc_bank2 = not low & 8
        self.lc_read = (low & 3) in (0, 3)
        if low & 1:
            if is_read:
                if self.lc_prewrite:
                    self.lc_write = True
                self.lc_prewrite = True
            else:
                self.lc_prewrite = False
        else:
            self.lc_write = False
            self.lc_prewrite = False

    def _io_read(self, address):
        self.io_accesses += 1
        low = address & 0xFF
        if low == 0x00:
            return self._keyboard()
        if low == 0x10:
            value = self.key_latch
            self.key_latch &= 0x7F
            return value
        if low == 0x19:
            return 0x00 if self.in_vbl() else 0x80
        if low in self.STATUS:
            return (0x80 if self.sw[self.STATUS[low]] else 0) | \
                (self.key_latch & 0x7F)
        if low == 0x29:
            return self.newvideo
        if low == 0x30:
            self.speaker_toggles += 1
        elif 0x50 <= low <= 0x57:
            self._video_switch(low)
        elif 0x61 <= low <= 0x63:
            return self.buttons[low - 0x61]
        elif 0x64 <= low <= 0x67:
            elapsed = self.cycles // self.speed - self.paddle_trigger
            return 0x80 if elapsed < self.paddles[low - 0x64] else 0x00
        elif low == 0x70:
            self.paddle_trigger = self.cycles // self.speed
        elif 0x80 <= low <= 0x8F:
            self._lc_switch(low, True)
        elif (low >> 4) == 8 + self.phasor_slot:
            self.phasor.mode_switch(low)
        return 0x00

    def _io_write(self, address, value):
        self.io_accesses += 1
        low = address & 0xFF
        if low <= 0x0F:
            self.sw[self.SWITCH_PAIRS[low >> 1]] = bool(low & 1)
        elif low == 0x10:
            self.key_latch &= 0x7F
        elif low == 0x29:
            self.newvideo = value
        elif low == 0x30:
            self.speaker_toggles += 1
        elif 0x50 <= low <= 0x57:
            self._video_switch(low)
        elif low == 0x70:
            self.paddle_trigger = self.cycles // self.speed
        elif low in (0x71, 0x73):
            bank = value & 0x7F
            self.bank = bank
            self.aux = self.aux_banks.setdefault(bank, bytearray(0x10000))
        elif 0x80 <= low <= 0x8F:
            self._lc_switch(low, False)
        elif (low >> 4) == 8 + self.phasor_slot:
            self.phasor.mode_switch(low)

    # -- control ---------------------------------------------------------
    def load(self, address, data, aux_bank=None):
        target = self.main if aux_bank is None else \
            self.aux_banks.setdefault(aux_bank, bytearray(0x10000))
        target[address:address + len(data)] = data

    def press(self, text, at_cycle=None, gap=None):
        when = self.cycles if at_cycle is None else at_cycle
        gap = self.frame_cycles * 3 if gap is None else gap
        for char in text:
            self.keys.append((when, ord(char) & 0x7F))
            when += gap

    def run(self, max_cycles, stop_pc=None):
        """Run for max_cycles; return True when stop_pc was reached."""
        mpu = self.mpu
        end = mpu.processorCycles + max_cycles
        stops = () if stop_pc is None else (
            stop_pc if isinstance(stop_pc, (set, tuple, list)) else (stop_pc,))
        while mpu.processorCycles < end:
            mpu.step()
            if mpu.pc in stops:
                return True
        return False

    # -- output ----------------------------------------------------------
    def text_screen(self):
        rows = []
        for row in range(24):
            base = 0x400 + (((row & 7) << 7) | ((row >> 3) * 0x28))
            chars = self.main[base:base + 40]
            rows.append("".join(
                " " if c == 0 else
                chr((c & 0x3F) + 0x40 if (c & 0x3F) < 0x20 else (c & 0x3F))
                for c in chars))
        return "\n".join(rows)

    @staticmethod
    def hgr_base(row):
        return (((row >> 3) & 7) << 7) | (((row >> 6) & 3) * 0x28) | \
            ((row & 7) << 10)

    def hgr_image(self, page=None):
        from PIL import Image
        page = (0x4000 if self.sw["page2"] else 0x2000) if page is None \
            else page
        colors = {0: (0, 0, 0), 1: (255, 255, 255), "v": (200, 60, 255),
                  "g": (30, 220, 40), "b": (20, 150, 255),
                  "o": (255, 110, 20)}
        image = Image.new("RGB", (280, 192))
        pixels = image.load()
        for row in range(192):
            base = page + self.hgr_base(row)
            bits, high = [], []
            for column in range(40):
                byte = self.main[base + column]
                for bit in range(7):
                    bits.append((byte >> bit) & 1)
                    high.append(byte >> 7)
            for x in range(280):
                if not bits[x]:
                    left = bits[x - 1] if x else 0
                    right = bits[x + 1] if x < 279 else 0
                    if left and right:
                        key = ("b" if x % 2 else "o") if high[x] else \
                            ("v" if x % 2 else "g")
                        pixels[x, row] = colors[key]
                    continue
                if (x and bits[x - 1]) or (x < 279 and bits[x + 1]):
                    pixels[x, row] = colors[1]
                else:
                    key = ("o" if x % 2 else "b") if high[x] else \
                        ("g" if x % 2 else "v")
                    pixels[x, row] = colors[key]
        return image

    def shr_image(self):
        from PIL import Image
        aux = self.aux_banks[0]
        image = Image.new("RGB", (640, 400))
        pixels = image.load()
        for row in range(200):
            scb = aux[0x9D00 + row]
            pal = 0x9E00 + (scb & 15) * 32
            table = []
            for index in range(16):
                lo, hi = aux[pal + index * 2], aux[pal + index * 2 + 1]
                table.append((((hi & 15) * 17), ((lo >> 4) * 17),
                              ((lo & 15) * 17)))
            line = aux[0x2000 + row * 160:0x2000 + row * 160 + 160]
            for column, byte in enumerate(line):
                if scb & 0x80:
                    dots = [(byte >> 6) & 3, (byte >> 4) & 3,
                            (byte >> 2) & 3, byte & 3]
                    for k, dot in enumerate(dots):
                        color = table[dot + (8, 12, 0, 4)[k]]
                        x = column * 4 + k
                        pixels[x, row * 2] = pixels[x, row * 2 + 1] = color
                else:
                    for k, dot in enumerate((byte >> 4, byte & 15)):
                        color = table[dot]
                        for dx in (0, 1):
                            x = (column * 2 + k) * 2 + dx
                            pixels[x, row * 2] = color
                            pixels[x, row * 2 + 1] = color
        return image
