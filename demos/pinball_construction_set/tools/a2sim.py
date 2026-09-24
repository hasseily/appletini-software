#!/usr/bin/env python3
"""A small Apple //e model for headless tests (py65 65C02 core).

Copied from the Bilestoad SHR port (demos/bilestoad/tools/a2sim.py on the
bilestoad-shr-port branch) with paddles and buttons added for Bosconian.

It models what the game touches: main and auxiliary memory with the //e
bank switches, RamWorks banks through $C073, the language card, the
keyboard, VBL at $C019, the speaker, NEWVIDEO at $C029, the game buttons
and paddles ($C061-$C067, $C070), a Phasor in slot 4 that follows the
select rules of appletini-one/hdl/apple/mockingboard.sv, and (added for
the Pinball Construction Set port) the Appletini mouse card in slot 2 that
follows appletini-one/hdl/apple/mouse_card.sv. It renders HGR, SHR and
text to images or strings.

Keyboard: `press(text)` queues taps (the strobe of $C000, no key held);
`hold(key)` latches a key and keeps the "any key down" bit of $C010 set
until `release()`. Mouse: `mouse_move(x, y)`, `mouse_delta(dx, dy)` and
`mouse_buttons(left, right)` do what the PS does on a USB report: publish
a position and the buttons and commit them to the card, which clamps the
position and sets its "moved" status.

Time is counted in CPU cycles. `speed` is the accelerator factor: one video
frame lasts 17030 * speed CPU cycles, as under the Appletini vTW.
"""

from pathlib import Path

from py65.devices.mpu65c02 import MPU

FRAME_CYCLES_1MHZ = 17030          # 262 lines * 65 cycles (NTSC)
VBL_START_CYCLE = 192 * 65         # first cycle of vertical blanking

# The mouse card's slot ROM (appletini-one/hdl/apple/mouse_card_slot2.mem,
# built from software/mouse_card_slot2.a65): the AppleMouse ID bytes at
# $Cn05 $Cn07 $Cn0B $Cn0C ($38 $18 $01 $20) and the firmware entry table.
MOUSE_ROM = bytes.fromhex(
    "a20260eaea386018eaeaea01208dacc0"
    "18605e6fa6b3cd1beaef3fc902b0e68d"
    "a7c0ad78048da8c0ad78058da9c0adf8"
    "048daac0adf8058dabc0a9024c0dc2ad"
    "780438e947c908b0bc4829018da7c068"
    "29064a4901aabda8c08d78051860c910"
    "b0a3482000c2689df8078daec0186020"
    "00c2ada0c09d780748a9028dafc06829"
    "0ef00218603860ada1c09d7804ada2c0"
    "9d7805ada3c09df804ada4c09df805ad"
    "a0c09d7807602000c22087c2a9018daf"
    "c018602000c2a9009d78049df8049d78"
    "059df8059d780720d0c24cacc22000c2"
    "bd78048da1c0bd78058da2c0bdf8048d"
    "a3c0bdf8058da4c01860a9014c0dc220"
    "00c2a9038dacc04cb6c2ead6eaeaeaea")
assert len(MOUSE_ROM) == 256


class MouseCard:
    """The Appletini's AppleMouse-compatible card (mouse_card.sv).

    Sixteen I/O bytes at $C0n0-$C0nF: status, X lo/hi, Y lo/hi (read and
    write), raw buttons, sequence, clamp axis select, clamp min/max lo/hi
    of the selected axis, command, mode, ACK. Positions and clamps are 16
    bits wide. The PS publishes absolute positions through `commit`, the
    card clamps them; the Apple's position writes store raw values and the
    home command goes to the clamp minimum. `log` records every register
    access as (kind, reg, value).
    """

    CMD_HOME, CMD_CLAMP, CMD_DEFAULTS = 1, 2, 3
    MODE_ENABLE, MODE_MOVE_IRQ, MODE_BUTTON_IRQ, MODE_VBL_IRQ = 1, 2, 4, 8

    def __init__(self):
        self.rom = MOUSE_ROM
        self.x = self.y = 0
        self.buttons = 0                # bit 0 left, bit 1 right
        self.prev_buttons = 0           # latched by ACK bit 0
        self.moved = False              # status bit 5: moved since the last ACK
        self.move_irq = self.button_pending = self.vbl_pending = False
        self.irq = False
        self.mode = 0
        self.clamp_axis = 0
        self.clamp = [[0, 1023], [0, 1023]]     # per axis: [min, max]
        self.seq = 0
        self.connected = True
        self.ps_x = self.ps_y = 0       # the PS's last published position
        self.ps_buttons = 0
        self.log = []

    # -- helpers -----------------------------------------------------------
    @property
    def enabled(self):
        return bool(self.mode & self.MODE_ENABLE)

    @staticmethod
    def _clamp16(value, lo, hi):
        hi = max(hi, lo)
        return min(max(value, lo), hi)

    def _reclamp(self):
        self.x = self._clamp16(self.x, *self.clamp[0])
        self.y = self._clamp16(self.y, *self.clamp[1])

    def status(self):
        b, p = self.buttons, self.prev_buttons
        return (((b & 1) << 7) | ((p & 1) << 6) | (int(self.moved) << 5) |
                (((b >> 1) & 1) << 4) | (int(self.vbl_pending) << 3) |
                (int(self.button_pending) << 2) | (int(self.move_irq) << 1) |
                ((p >> 1) & 1))

    # -- the PS side -------------------------------------------------------
    def commit(self, x, y, buttons, connected=True):
        """AXI_REG_COMMIT after the shadows: position and buttons take
        effect only when connected and enabled; `moved` compares the raw
        published position with the card's clamped one, as the fabric does.
        The PS saturates what it publishes to 16 bits (mouse_clamp_16bit in
        usb_hid_service.c), it never wraps."""
        x = self._clamp16(x, 0, 0xFFFF)
        y = self._clamp16(y, 0, 0xFFFF)
        self.ps_x, self.ps_y, self.ps_buttons = x, y, buttons & 3
        self.connected = connected
        if connected and self.enabled:
            if (x, y) != (self.x, self.y):
                self.moved = True
                if self.mode & self.MODE_MOVE_IRQ:
                    self.move_irq = self.irq = True
            if self.ps_buttons != self.buttons and self.mode & self.MODE_BUTTON_IRQ:
                self.button_pending = self.irq = True
            self.x = self._clamp16(x, *self.clamp[0])
            self.y = self._clamp16(y, *self.clamp[1])
            self.buttons = self.ps_buttons
        elif not connected:
            self.buttons = 0
        self.seq = (self.seq + 1) & 0xFF

    def vblank(self):
        if self.mode & self.MODE_VBL_IRQ:
            self.vbl_pending = self.irq = True

    # -- the Apple side ----------------------------------------------------
    def read(self, reg):
        lo, hi = self.clamp[self.clamp_axis]
        value = {0: self.status(), 1: self.x & 0xFF, 2: self.x >> 8,
                 3: self.y & 0xFF, 4: self.y >> 8, 5: self.buttons, 6: self.seq,
                 7: self.clamp_axis, 8: lo & 0xFF, 9: lo >> 8,
                 10: hi & 0xFF, 11: hi >> 8, 14: self.mode}.get(reg, 0)
        self.log.append(("r", reg, value))
        return value

    def write(self, reg, value):
        self.log.append(("w", reg, value))
        window = self.clamp[self.clamp_axis]
        if reg == 1:
            self.x = (self.x & 0xFF00) | value
        elif reg == 2:
            self.x = (self.x & 0x00FF) | (value << 8)
        elif reg == 3:
            self.y = (self.y & 0xFF00) | value
        elif reg == 4:
            self.y = (self.y & 0x00FF) | (value << 8)
        elif reg == 7:
            self.clamp_axis = value & 1
        elif reg == 8:
            window[0] = (window[0] & 0xFF00) | value
        elif reg == 9:
            window[0] = (window[0] & 0x00FF) | (value << 8)
        elif reg == 10:
            window[1] = (window[1] & 0xFF00) | value
        elif reg == 11:
            window[1] = (window[1] & 0x00FF) | (value << 8)
        elif reg == 12:
            if value == self.CMD_HOME:
                self.x, self.y = self.clamp[0][0], self.clamp[1][0]
            elif value == self.CMD_CLAMP:
                # AppleWin-style normalisation of a min > max window
                if window[0] > window[1]:
                    window[:] = [0, (window[0] + window[1]) & 0xFFFF]
                self._reclamp()
            elif value == self.CMD_DEFAULTS:
                self.clamp = [[0, 1023], [0, 1023]]
                self._reclamp()
        elif reg == 14:
            self.mode = value & 0x0F
        elif reg == 15:
            if value & 1:
                self.moved = self.move_irq = self.button_pending = False
                self.vbl_pending = False
                self.prev_buttons = self.buttons
            if value & 2:
                self.irq = False

    def writes(self, reg=None):
        """The values written to one register (or every write) so far."""
        return [(r, v) if reg is None else v
                for k, r, v in self.log if k == "w" and (reg is None or r == reg)]


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
    def __init__(self, rom_path, speed=1, phasor_slot=4, mouse_slot=2, mouse=True):
        self.rom = Path(rom_path).read_bytes()      # $C000-$FFFF
        assert len(self.rom) == 0x4000
        self.mouse_slot = mouse_slot
        self.mouse = MouseCard() if mouse else None
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
        self.key_held = False       # "any key down", $C010 bit 7
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
            if (self.mouse and not self.sw["intcxrom"] and address < 0xC800
                    and slot == self.mouse_slot):
                return self.mouse.rom[address & 0xFF]
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
            # bit 7 = any key down, bits 6-0 = the last key; clears the strobe
            value = (0x80 if self.key_held else 0) | (self.key_latch & 0x7F)
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
        elif self.mouse and (low >> 4) == 8 + self.mouse_slot:
            return self.mouse.read(low & 0x0F)
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
        elif self.mouse and (low >> 4) == 8 + self.mouse_slot:
            self.mouse.write(low & 0x0F, value)

    # -- control ---------------------------------------------------------
    def load(self, address, data, aux_bank=None):
        target = self.main if aux_bank is None else \
            self.aux_banks.setdefault(aux_bank, bytearray(0x10000))
        target[address:address + len(data)] = data

    def press(self, text, at_cycle=None, gap=None):
        """Queue taps: each sets the strobe when its time comes, none holds
        the key down."""
        when = self.cycles if at_cycle is None else at_cycle
        gap = self.frame_cycles * 3 if gap is None else gap
        for char in text:
            self.keys.append((when, ord(char) & 0x7F))
            when += gap

    def hold(self, key):
        """Press a key (a character or its code) and keep it down: the
        strobe is set now and $C010 reports "any key down" until release."""
        code = key if isinstance(key, int) else ord(key)
        self.key_latch = (code & 0x7F) | 0x80
        self.key_held = True

    def release(self):
        self.key_held = False

    # -- mouse (what the PS does on a USB report) --------------------------
    def mouse_move(self, x, y):
        """Publish an absolute position with the buttons already held."""
        self.mouse.commit(x, y, self.mouse.ps_buttons)

    def mouse_delta(self, dx, dy):
        """The PS's motion path: the card's current position plus the
        delta, clamped to the card's windows, then committed."""
        card = self.mouse
        x = card._clamp16(card.x + dx, *card.clamp[0])
        y = card._clamp16(card.y + dy, *card.clamp[1])
        card.commit(x, y, card.ps_buttons)

    def mouse_buttons(self, left, right):
        """A button report: the card's current position is re-published
        with the new buttons."""
        card = self.mouse
        card.commit(card.x, card.y, (1 if left else 0) | (2 if right else 0))

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
