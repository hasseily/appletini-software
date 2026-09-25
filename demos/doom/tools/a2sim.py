#!/usr/bin/env python3
"""A small Apple //e model for headless tests (py65 65C02 core).

Copied from the Pinball Construction Set port (demos/pinball_construction_set/
tools/a2sim.py, itself from the Bilestoad and Bosconian ports) and extended
for Doom (docs/DESIGN.md sections 2, 8 and 12):

- **Synthetic timing presets**: the historical name `speed="turbo"`
  selects 1,250,000 CPU cycles per frame. Numeric speeds use 17030 * speed
  cycles per frame. The 1 MHz peripheral clock (Phasor timers, paddles)
  is derived from the frame length. The historical preset also charges
  `io_cycles` extra cycles for each $C000-$CFFF access (default 73), while
  numeric presets default to zero extra cycles. These are test budgets,
  not a faithful hardware TURBO model: batched video writes, publication
  synchronization, PSRAM latency and cache behavior are not simulated.
- **Video timing**: a frame starts at line 0 (cycle 0 of the frame, the
  Appletini's frame marker where the SHR shadow is published); vertical
  blanking ($C019 bit 7 low) is lines 192-261, the last 70/262 of it.
- **RamWorks**: `ramworks_banks` banks of 64 KB (default 128 = 8 MB);
  a $C073 value past the last bank aliases modulo the bank count.
  ALTZP maps zero page, the CPU stack and both language-card halves into
  that selected bank, independently of RAMRD/RAMWRT.
- **VBL interrupt**: the mouse card's VBL interrupt (mode bit 3) is
  raised at the start of vertical blanking and delivered to the CPU (IRQ
  vector at $FFFE) while the I flag is clear, until the program's ACK
  write releases it, as mouse_card.sv does.
- **Idle skip**: `idle_pcs` maps program addresses of idle loops to what
  they wait for ("vbl": the next VBL interrupt, "line0": the next frame
  start), or to (kind, predicate) where predicate() says whether the loop
  would really wait. When the CPU reaches one, the model moves the clock
  forward to that event instead of executing the loop; `idle_cycles` adds
  up what was skipped. The skipped time is real time, not work.
- **PAL256 screenshots**: `shr_image()` renders the SHR screen as
  appletini-one/ps_sources/frontend/apple_cycle_renderer.c does: with the
  SHR4 magic at aux $9DFC and a palette entry whose selector nibble is 2,
  the progressive (paging byte $9DF8 = 0) PAL256 frame is 320x100 bytes
  from aux $2000, each pixel 2x4 on the 640x400 output
  (render_shr4_pal256_frame); interlace (1) and page-flip merge (2) are
  rendered too. Otherwise standard SHR (320 and 640 modes by SCB) with
  the SHR4 per-pixel selectors 0 and 2 in 320 mode. Channels are
  scaled by 16 (shr_pack_bgra), $C029 bit 5 forces luminance.

It models what the programs touch: main and auxiliary memory with the //e
bank switches, RamWorks banks through $C073, the language card, the
keyboard, VBL at $C019, the speaker, NEWVIDEO at $C029, the game buttons
and paddles ($C061-$C067, $C070), a Phasor in slot 4 that follows the
select rules of appletini-one/hdl/apple/mockingboard.sv, and the Appletini
mouse card in slot 2 that follows appletini-one/hdl/apple/mouse_card.sv.
It renders HGR, SHR and text to images or strings.

Keyboard: `press(text)` queues taps (the strobe of $C000, no key held);
`hold(key)` latches a key and keeps the "any key down" bit of $C010 set
until `release()`. Mouse: `mouse_move(x, y)`, `mouse_delta(dx, dy)` and
`mouse_buttons(left, right)` do what the PS does on a USB report: publish
a position and the buttons and commit them to the card, which clamps the
position and sets its "moved" status.

ProDOS: `Machine(..., prodos=FakeProDOS(files))` puts a JMP at $BF00 (so a
program sees the MLI) and services `JSR $BF00` calls itself, with the
MLI convention (the call number and the parameter block address follow
the JSR; the CPU continues after them with A = the error and the carry
set on failure). The files are a dict of name -> bytes (BIN, aux 0) or
(file type, aux type, bytes) on one volume; files of any size up to
ProDOS's 16 MB (24-bit marks), any number of them; the volume directory
reads as real ProDOS directory blocks (tools/build_disk.py's layout), so a
catalog reader sees the same bytes as on the disk image. QUIT stops the
machine (`prodos.quit`). Without `prodos` nothing changes.
"""

import re
from pathlib import Path

from py65.devices.mpu65c02 import MPU

FRAME_CYCLES_1MHZ = 17030          # 262 lines * 65 cycles (NTSC)
VBL_START_CYCLE = 192 * 65         # first cycle of vertical blanking
LINES = 262
VBL_START_LINE = 192
TURBO_FRAME_CYCLES = 1_250_000     # historical synthetic budget, not measured hardware timing
DEFAULT_RAMWORKS_BANKS = 128       # 8 MB

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


class ProDOSError(Exception):
    def __init__(self, code):
        super().__init__(f"ProDOS error ${code:02X}")
        self.code = code


class FakeProDOS:
    """A ProDOS 8 MLI stand-in for the test machine (see the module doc).

    `files`: name -> bytes or (file_type, aux_type, bytes); every file
    lives in the volume directory, the prefix is "/VOLUME/". `directory`
    (a Path) mirrors the files of a directory on the host and receives
    the files a program writes (on CLOSE). `calls` logs every MLI call
    as (number, error).
    """

    NAME = re.compile(r"^[A-Z][A-Z0-9.]{0,14}$")
    E_BADCALL, E_BADPATH, E_TOOMANY, E_BADREF, E_NOPATH = 0x01, 0x40, 0x42, 0x43, 0x44
    E_NOVOL, E_NOFILE, E_DUP, E_EOF, E_POSITION = 0x45, 0x46, 0x47, 0x4C, 0x4D
    MAX_OPEN = 8

    def __init__(self, files=None, volume="DOOM", directory=None, launched="DOOM.SYSTEM"):
        self.volume = volume.upper()
        self.prefix = f"/{self.volume}/"
        self.launched = launched        # the system program's name, put at $0280
        self.files = {}                 # NAME -> [file_type, aux_type, bytearray]
        for name, value in (files or {}).items():
            self.add(name, value)
        self.directory = Path(directory) if directory is not None else None
        self.open_files = {}            # ref -> dict(name, pos, data, dirty)
        self.quit = False
        self.calls = []
        self.machine = None

    def add(self, name, value):
        if isinstance(value, (bytes, bytearray)):
            value = (0x06, 0x0000, value)
        file_type, aux, data = value
        name = name.upper()
        if not self.NAME.match(name):
            raise ValueError(f"not a ProDOS file name: {name!r}")
        self.files[name] = [file_type, aux, bytearray(data)]

    @classmethod
    def from_directory(cls, path, volume="DOOM"):
        """The files of a host directory (those with ProDOS names, as BIN
        aux 0); files written by the program are stored back there."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        fake = cls(volume=volume, directory=path)
        for entry in sorted(path.iterdir()):
            if entry.is_file() and cls.NAME.match(entry.name.upper()):
                fake.add(entry.name, entry.read_bytes())
        return fake

    # -- the machine side --------------------------------------------------
    def attach(self, machine):
        self.machine = machine
        machine.main[0xBF00:0xBF03] = b"\x4C\x00\xBF"     # JMP $BF00: QUIT spins here
        path = (self.prefix + self.launched).encode("ascii")  # as ProDOS's loader does
        machine.main[0x0280] = len(path)
        machine.main[0x0281:0x0281 + len(path)] = path

    def intercept(self, machine, operand):
        """Called from the operand fetch of `JSR $BF00` at operand-1: the
        return address is already pushed. Services the call, drops the
        pushed return address and returns the low byte of the address the
        CPU continues at (the high byte is handed back on the next read),
        or None to let the JSR land at $BF00 (QUIT)."""
        mpu = machine.mpu
        mem = machine.main
        jsr = operand - 1
        number = mem[jsr + 3]
        parms = mem[jsr + 4] | (mem[jsr + 5] << 8)
        if number == 0x65:
            self.calls.append((number, 0))
            self.quit = True
            return None
        error = self.service(machine, number, parms)
        self.calls.append((number, error))
        mpu.a = error
        if error:
            mpu.p |= mpu.CARRY
        else:
            mpu.p &= ~mpu.CARRY & 0xFF
        mpu.sp = (mpu.sp + 2) & 0xFF
        target = jsr + 6
        machine._mli_hi = (operand + 1, target >> 8)
        return target & 0xFF

    # -- the calls -------------------------------------------------------
    def service(self, machine, number, parms):
        mem = machine.main
        handler = {0xC8: self.mli_open, 0xCA: self.mli_read, 0xCB: self.mli_write,
                   0xCC: self.mli_close, 0xC0: self.mli_create, 0xC1: self.mli_destroy,
                   0xC4: self.mli_get_file_info, 0xC3: self.mli_set_file_info,
                   0xC7: self.mli_get_prefix, 0xC6: self.mli_set_prefix,
                   0xC5: self.mli_on_line, 0xCE: self.mli_set_mark, 0xCF: self.mli_get_mark,
                   0xD0: self.mli_set_eof, 0xD1: self.mli_get_eof}.get(number)
        if handler is None:
            return self.E_BADCALL
        try:
            handler(mem, parms)
        except ProDOSError as error:
            return error.code
        return 0

    @staticmethod
    def _u16(mem, address):
        return mem[address] | (mem[address + 1] << 8)

    @staticmethod
    def _put16(mem, address, value):
        mem[address] = value & 0xFF
        mem[address + 1] = (value >> 8) & 0xFF

    @staticmethod
    def _put24(mem, address, value):
        mem[address] = value & 0xFF
        mem[address + 1] = (value >> 8) & 0xFF
        mem[address + 2] = (value >> 16) & 0xFF

    def _pathname(self, mem, address):
        length = mem[address]
        return bytes(b & 0x7F for b in mem[address + 1:address + 1 + length]).decode("ascii")

    def resolve(self, path):
        """The file name a pathname refers to, None for the volume directory."""
        text = path.upper()
        if not text:
            raise ProDOSError(self.E_BADPATH)
        if text.startswith("/"):
            parts = [p for p in text.split("/") if p]
            if not parts or parts[0] != self.volume:
                raise ProDOSError(self.E_NOVOL if parts else self.E_BADPATH)
            parts = parts[1:]
        else:
            parts = [p for p in self.prefix.upper().split("/") if p][1:]
            parts += [p for p in text.split("/") if p]
        for part in parts:
            if not self.NAME.match(part):
                raise ProDOSError(self.E_BADPATH)
        if not parts:
            return None
        if len(parts) > 1:
            raise ProDOSError(self.E_NOPATH)
        return parts[0]

    def _file(self, mem, parms):
        name = self.resolve(self._pathname(mem, self._u16(mem, parms + 1)))
        if name is None or name not in self.files:
            raise ProDOSError(self.E_NOFILE)
        return name, self.files[name]

    def directory_blocks(self):
        """The volume directory blocks, in chain order, as build_disk
        writes them for these files."""
        import build_disk
        contents = {name: bytes(data) or b"\0" for name, (_t, _a, data) in self.files.items()}
        total = build_disk.volume_size(contents.values())
        writer = build_disk.VolumeWriter(self.volume, total)
        for name, (file_type, aux, _data) in self.files.items():
            writer.add_file(name, contents[name], file_type, aux)
        image = build_disk.Image(writer.finish())
        _header, _entries, chain = build_disk.list_volume(image)
        return b"".join(image.read(number) for number in chain)

    def _open(self, mem, ref):
        entry = self.open_files.get(ref)
        if entry is None:
            raise ProDOSError(self.E_BADREF)
        return entry

    def mli_open(self, mem, parms):
        name = self.resolve(self._pathname(mem, self._u16(mem, parms + 1)))
        if len(self.open_files) >= self.MAX_OPEN:
            raise ProDOSError(self.E_TOOMANY)
        if name is None:
            entry = dict(name=None, pos=0, data=bytearray(self.directory_blocks()), dirty=False)
        else:
            if name not in self.files:
                raise ProDOSError(self.E_NOFILE)
            entry = dict(name=name, pos=0, data=self.files[name][2], dirty=False)
        ref = next(r for r in range(1, self.MAX_OPEN + 1) if r not in self.open_files)
        self.open_files[ref] = entry
        mem[parms + 5] = ref

    def mli_read(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        buffer = self._u16(mem, parms + 2)
        request = self._u16(mem, parms + 4)
        data, pos = entry["data"], entry["pos"]
        chunk = bytes(data[pos:pos + request])
        self._put16(mem, parms + 6, len(chunk))
        if request and not chunk:
            raise ProDOSError(self.E_EOF)
        mem[buffer:buffer + len(chunk)] = chunk
        entry["pos"] = pos + len(chunk)

    def mli_write(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        if entry["name"] is None:
            raise ProDOSError(0x4E)                 # a directory: access error
        buffer = self._u16(mem, parms + 2)
        request = self._u16(mem, parms + 4)
        data, pos = entry["data"], entry["pos"]
        if len(data) < pos:
            data.extend(bytes(pos - len(data)))
        data[pos:pos + request] = bytes(mem[buffer:buffer + request])
        entry["pos"] = pos + request
        entry["dirty"] = True
        self._put16(mem, parms + 6, request)

    def mli_close(self, mem, parms):
        ref = mem[parms + 1]
        refs = list(self.open_files) if ref == 0 else [ref]
        for r in refs:
            entry = self._open(mem, r)
            del self.open_files[r]
            if entry["dirty"] and self.directory is not None:
                (self.directory / entry["name"]).write_bytes(bytes(entry["data"]))

    def mli_create(self, mem, parms):
        name = self.resolve(self._pathname(mem, self._u16(mem, parms + 1)))
        if name is None or name in self.files:
            raise ProDOSError(self.E_DUP)
        self.files[name] = [mem[parms + 4], self._u16(mem, parms + 5), bytearray()]

    def mli_destroy(self, mem, parms):
        name, _ = self._file(mem, parms)
        del self.files[name]

    def mli_get_file_info(self, mem, parms):
        _, (file_type, aux, data) = self._file(mem, parms)
        mem[parms + 3] = 0xC3
        mem[parms + 4] = file_type
        self._put16(mem, parms + 5, aux)
        blocks = max(1, (len(data) + 511) // 512)
        storage = 1 if blocks == 1 else 2 if blocks <= 256 else 3
        index = 0 if storage == 1 else 1 if storage == 2 else 1 + (blocks + 255) // 256
        mem[parms + 7] = storage
        self._put16(mem, parms + 8, blocks + index)
        for offset in range(10, 18):
            mem[parms + offset] = 0

    def mli_set_file_info(self, mem, parms):
        _, info = self._file(mem, parms)
        info[0] = mem[parms + 4]
        info[1] = self._u16(mem, parms + 5)

    def mli_get_prefix(self, mem, parms):
        buffer = self._u16(mem, parms + 1)
        text = self.prefix.encode("ascii")
        mem[buffer] = len(text)
        mem[buffer + 1:buffer + 1 + len(text)] = text

    def mli_set_prefix(self, mem, parms):
        path = self._pathname(mem, self._u16(mem, parms + 1))
        if self.resolve(path) is not None:
            raise ProDOSError(self.E_NOPATH)         # only the volume directory exists
        self.prefix = f"/{self.volume}/"

    def mli_on_line(self, mem, parms):
        unit = mem[parms + 1]
        buffer = self._u16(mem, parms + 2)
        name = self.volume.encode("ascii")
        entries = 1 if unit else 14
        mem[buffer:buffer + 16 * entries] = bytes(16 * entries)
        mem[buffer] = 0x70 | len(name)              # slot 7, drive 1
        mem[buffer + 1:buffer + 1 + len(name)] = name

    def mli_set_mark(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        position = mem[parms + 2] | (mem[parms + 3] << 8) | (mem[parms + 4] << 16)
        if position > len(entry["data"]):
            raise ProDOSError(self.E_POSITION)
        entry["pos"] = position

    def mli_get_mark(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        self._put24(mem, parms + 2, entry["pos"])

    def mli_set_eof(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        eof = mem[parms + 2] | (mem[parms + 3] << 8) | (mem[parms + 4] << 16)
        data = entry["data"]
        if eof < len(data):
            del data[eof:]
        else:
            data.extend(bytes(eof - len(data)))
        entry["pos"] = min(entry["pos"], eof)
        entry["dirty"] = True

    def mli_get_eof(self, mem, parms):
        entry = self._open(mem, mem[parms + 1])
        self._put24(mem, parms + 2, len(entry["data"]))


class FakeSmartPortMemory:
    """Opt-in byte-FIFO model of the Appletini AMEM extension.

    This checks the assembled caller's transport and memory effects. It does
    not estimate ARM/DMA latency or model physical video mirroring. Without
    this explicit object Machine retains its historical ROM-only slot 7.
    """

    def __init__(self, *, supported=True, available=True, private_port=True,
                 fail_before=0, fail_after=None, partial_bytes=0, error=0x67):
        self.supported, self.available = supported, available
        self.private_port = private_port
        self.fail_before, self.fail_after, self.error = fail_before, fail_after, error
        self.partial_bytes = partial_bytes
        self.selected = False
        self.input = bytearray()
        self.output = bytearray()
        self.requests = []
        self.completed = []
        self.partial_writes = []
        self.ready = False
        self.never_ready = False
        self.rom = bytearray(256)
        for offset, value in ((1, 0x20), (3, 0), (5, 3), (7, 0), (0xff, 0x0a)):
            self.rom[offset] = value
        self.caps = bytearray(b"AMEM\1\0\20\20\7\0\0\2\0\xc0\x7e\1" + bytes(16))
        self.caps[20:22] = (512).to_bytes(2, "little")

    def read(self, machine, address):
        if address == 0xCFFF:
            self.selected = False
            return None
        if machine.sw["intcxrom"]:
            return None
        if address < 0xC800:
            self.selected = 0xC700 <= address < 0xC800
            return self.rom[address & 255] if self.selected else None
        if not self.selected:
            return None
        if address == 0xCFF0:
            return self.output[0] if self.output else 0
        if address == 0xCFF1:
            return (0x20 if self.private_port else 0) | (0x80 if self.ready else 0)
        return None

    def write(self, machine, address, value):
        if address == 0xCFFF:
            self.selected = False
            return True
        if machine.sw["intcxrom"] or not self.selected:
            return False
        if address == 0xCFF0:
            self.input.append(value)
        elif address == 0xCFF2:
            if not self.output:
                raise AssertionError("SmartPort caller popped an empty reply")
            del self.output[0]
        elif address == 0xCFF1:
            request = bytes(self.input)
            self.input.clear()
            self.requests.append((value, request))
            self.output = bytearray(self._execute(machine, value, request))
            self.ready = not self.never_ready
        else:
            return False
        return True

    def _execute(self, machine, family, request):
        if family != 2 or len(request) < 10 or request[1:3] != b"\3\0":
            raise AssertionError(f"Malformed SmartPort request: {family=} {request.hex()}")
        if request[6:10] != bytes(4):
            raise AssertionError("SmartPort parameter padding was not zero")
        command, selector = request[0], request[5]
        if command == 0:
            if len(request) != 10:
                raise AssertionError("STATUS request contains trailing bytes")
            if selector != 0x80 or not self.supported:
                return b"\x21"
            self.caps[15] = int(self.available)
            return b"\0\x20\0" + self.caps
        if command != 4 or selector != 0x80 or len(request) < 12:
            return b"\x21"
        length = int.from_bytes(request[10:12], "little")
        if len(request) != 12 + length:
            raise AssertionError("CONTROL payload length differs from transmitted bytes")
        if not self.supported or not self.available:
            return b"\x60"
        if self.fail_before:
            return bytes([self.fail_before])
        data = request[12:]
        if len(data) < 8 or data[:5] != b"AMEM\1" or data[6:8] != b"\0\0" or \
                not 1 <= data[5] <= 16 or len(data) != 8 + 16 * data[5]:
            return b"\x61"
        descriptors = []
        for position in range(8, len(data), 16):
            d = data[position:position + 16]
            op, flags = d[:2]
            size = int.from_bytes(d[10:12], "little")
            if op not in (1, 2) or flags & ~1 or any(d[13:]) or \
                    (op == 1 and d[12]) or (op == 2 and any(d[2:6])):
                return b"\x62"
            source, destination = None, None
            for offset in ((2, 6) if op == 1 else (6,)):
                space, bank = d[offset:offset + 2]
                address = int.from_bytes(d[offset + 2:offset + 4], "little")
                if space not in (0, 1) or (space == 0 and bank) or bank > 126 or \
                        not size or address < 0x200 or address + size > 0xC000:
                    return b"\x63"
                endpoint = (space, bank, address)
                if offset == 2:
                    source = endpoint
                else:
                    destination = endpoint
            if source and source[:2] == destination[:2] and \
                    source[2] < destination[2] + size and destination[2] < source[2] + size:
                return b"\x64"
            if not flags & 1 and (destination[0] == 0 or destination[1] == 0):
                return b"\x65"
            descriptors.append((op, source, destination, size, d[12]))

        def storage(endpoint):
            space, bank, address = endpoint
            memory = machine.main if space == 0 else machine.aux_banks.setdefault(bank, bytearray(65536))
            return memory, address

        for index, (op, source, destination, size, fill) in enumerate(descriptors):
            target, offset = storage(destination)
            if source:
                origin, start = storage(source)
                value = origin[start:start + size]
            else:
                value = bytes([fill]) * size
            if self.fail_after is not None and index >= self.fail_after:
                partial = min(size, self.partial_bytes)
                target[offset:offset + partial] = value[:partial]
                self.partial_writes.append((destination, partial))
                return bytes([self.error])
            target[offset:offset + size] = value
            self.completed.append((op, source, destination, size))
        return b"\0"


class Machine:
    def __init__(self, rom_path, speed=1, phasor_slot=4, mouse_slot=2, mouse=True,
                 prodos=None, ramworks_banks=DEFAULT_RAMWORKS_BANKS, io_cycles=None,
                 smartport=None):
        self.rom = Path(rom_path).read_bytes()      # $C000-$FFFF
        assert len(self.rom) == 0x4000
        self.prodos = None
        self.smartport = smartport
        self._mli_hi = None         # (address, value): the pending operand byte
        self.mouse_slot = mouse_slot
        self.mouse = MouseCard() if mouse else None
        self.speed = speed
        if speed == "turbo":
            self.frame_cycles = TURBO_FRAME_CYCLES
        else:
            self.frame_cycles = FRAME_CYCLES_1MHZ * speed
        self.vbl_start = VBL_START_LINE * self.frame_cycles // LINES
        if io_cycles is None:
            io_cycles = self.frame_cycles // FRAME_CYCLES_1MHZ if speed == "turbo" else 0
        self.io_cycles = io_cycles
        if not 1 <= ramworks_banks <= 128:
            raise ValueError("ramworks_banks must be 1..128")
        self.ramworks_banks = ramworks_banks
        self.main = bytearray(0x10000)
        self.aux_banks = {0: bytearray(0x10000)}
        self.bank = 0
        self.aux = self.aux_banks[0]
        # ALTZP selects the current RamWorks bank for page 0, page 1 and
        # the language card, matching apple_decode_private_access in
        # hdl/globals.sv. The alternate $D000 half occupies physical
        # $C000-$CFFF in that bank. Keep the historical main/base-aux
        # views for callers that install images directly.
        self.lc = {False: bytearray(0x4000),
                   True: memoryview(self.aux_banks[0])[0xC000:0x10000]}
        self.lc_bank1 = {False: bytearray(0x1000),
                         True: memoryview(self.aux_banks[0])[0xC000:0xD000]}
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
        self.phasor = Phasor(self.bus_clock)
        self.phasor_slot = phasor_slot
        self.video_writes = 0       # video-region writes counted; no per-write bus timing implied
        self.shr_writes = 0         # writes to aux bank 0 $2000-$9FFF (the SHR area)
        self.io_accesses = 0
        self.idle_pcs = {}          # pc -> "vbl" | "line0" (see the module doc)
        self.idle_cycles = 0
        self.irqs = 0               # interrupts delivered
        self.mpu = MPU(memory=self)
        self.next_vbl = self.vbl_start
        self.booted_zero_page()
        if prodos is not None:
            self.prodos = prodos
            prodos.attach(self)

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

    def bus_clock(self):
        """Elapsed time in 1 MHz bus cycles."""
        return self.cycles * FRAME_CYCLES_1MHZ // self.frame_cycles

    def in_vbl(self):
        return (self.cycles % self.frame_cycles) >= self.vbl_start

    def frame_number(self):
        """60 Hz frames since power-up (a frame starts at line 0)."""
        return self.cycles // self.frame_cycles

    def scanline(self):
        return (self.cycles % self.frame_cycles) * LINES // self.frame_cycles

    def _vbl_event(self):
        """Start of vertical blanking: the mouse card's VBL interrupt."""
        self.next_vbl += self.frame_cycles
        if self.mouse is not None:
            self.mouse.vblank()

    # -- memory ----------------------------------------------------------
    def _aux_selected(self, address, flag):
        sw = self.sw
        if sw["store80"]:
            if 0x0400 <= address < 0x0800:
                return sw["page2"]
            if sw["hires"] and 0x2000 <= address < 0x4000:
                return sw["page2"]
        return sw[flag]

    def _mli_fetch(self, address):
        """The operand fetch of `JSR $BF00` (the CPU's pc is at the operand,
        the byte before is the JSR opcode): the fake ProDOS takes over."""
        main = self.main
        if address < 0x0201 or main[address - 1] != 0x20 or main[address] != 0x00 \
                or main[address + 1] != 0xBF:
            return None
        return self.prodos.intercept(self, address)

    def __getitem__(self, address):
        if self.prodos is not None:
            if address == self.mpu.pc:
                value = self._mli_fetch(address)
                if value is not None:
                    return value
            elif self._mli_hi is not None and address == self._mli_hi[0]:
                value = self._mli_hi[1]
                self._mli_hi = None
                return value
        if address < 0x0200:
            return (self.aux if self.sw["altzp"] else self.main)[address]
        if address < 0xC000:
            if self._aux_selected(address, "ramrd"):
                return self.aux[address]
            return self.main[address]
        if address < 0xC100:
            return self._io_read(address)
        if address < 0xD000:
            self.mpu.processorCycles += self.io_cycles
            if self.smartport is not None:
                value = self.smartport.read(self, address)
                if value is not None:
                    return value
            slot = (address >> 8) & 7
            if (not self.sw["intcxrom"] and slot == self.phasor_slot):
                return self.phasor.read(address)
            if (self.mouse and not self.sw["intcxrom"] and address < 0xC800
                    and slot == self.mouse_slot):
                return self.mouse.rom[address & 0xFF]
            return self.rom[address - 0xC000]
        if self.lc_read:
            if self.sw["altzp"]:
                physical = address - 0x1000 if address < 0xE000 and not self.lc_bank2 else address
                return self.aux[physical]
            if address < 0xE000 and not self.lc_bank2:
                return self.lc_bank1[False][address - 0xD000]
            return self.lc[False][address - 0xC000]
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
                    if address >= 0x2000:
                        self.shr_writes += 1
            else:
                self.main[address] = value
                if 0x0400 <= address < 0x0C00 or 0x2000 <= address < 0x6000:
                    self.video_writes += 1
            return
        if address < 0xC100:
            self._io_write(address, value)
            return
        if address < 0xD000:
            self.mpu.processorCycles += self.io_cycles
            if self.smartport is not None and self.smartport.write(self, address, value):
                return
            if ((address >> 8) & 7) == self.phasor_slot:
                self.phasor.write(address, value)
            return
        if self.lc_write:
            if self.sw["altzp"]:
                physical = address - 0x1000 if address < 0xE000 and not self.lc_bank2 else address
                self.aux[physical] = value
            elif address < 0xE000 and not self.lc_bank2:
                self.lc_bank1[False][address - 0xD000] = value
            else:
                self.lc[False][address - 0xC000] = value

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

    def select_bank(self, value):
        """$C071/$C073: the RamWorks bank (aliased past the last bank)."""
        bank = (value & 0x7F) % self.ramworks_banks
        self.bank = bank
        self.aux = self.aux_banks.get(bank)
        if self.aux is None:
            self.aux = self.aux_banks[bank] = bytearray(0x10000)

    def _io_read(self, address):
        self.io_accesses += 1
        self.mpu.processorCycles += self.io_cycles
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
            elapsed = self.bus_clock() - self.paddle_trigger
            return 0x80 if elapsed < self.paddles[low - 0x64] else 0x00
        elif low == 0x70:
            self.paddle_trigger = self.bus_clock()
        elif 0x80 <= low <= 0x8F:
            self._lc_switch(low, True)
        elif (low >> 4) == 8 + self.phasor_slot:
            self.phasor.mode_switch(low)
        elif self.mouse and (low >> 4) == 8 + self.mouse_slot:
            return self.mouse.read(low & 0x0F)
        return 0x00

    def _io_write(self, address, value):
        self.io_accesses += 1
        self.mpu.processorCycles += self.io_cycles
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
            self.paddle_trigger = self.bus_clock()
        elif low in (0x71, 0x73):
            self.select_bank(value)
        elif 0x80 <= low <= 0x8F:
            self._lc_switch(low, False)
        elif (low >> 4) == 8 + self.phasor_slot:
            self.phasor.mode_switch(low)
        elif self.mouse and (low >> 4) == 8 + self.mouse_slot:
            self.mouse.write(low & 0x0F, value)

    # -- control ---------------------------------------------------------
    def load(self, address, data, aux_bank=None):
        if aux_bank is None:
            target = self.main
        else:
            target = self.aux_banks.get(aux_bank)
            if target is None:
                target = self.aux_banks[aux_bank] = bytearray(0x10000)
        target[address:address + len(data)] = data

    def bank_memory(self, bank):
        """The 64 KB of a RamWorks bank (created on first use)."""
        target = self.aux_banks.get(bank)
        if target is None:
            target = self.aux_banks[bank] = bytearray(0x10000)
        return target

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

    def step(self):
        """One instruction, with the VBL event, interrupt delivery and the
        idle skip in front of it."""
        mpu = self.mpu
        if mpu.processorCycles >= self.next_vbl:
            self._vbl_event()
        mouse = self.mouse
        if mouse is not None and mouse.irq and not mpu.p & mpu.INTERRUPT:
            self._interrupt()
        idle = self.idle_pcs.get(mpu.pc)
        if idle is not None:
            self._skip_idle(idle)
        mpu.step()

    def _interrupt(self):
        mpu = self.mpu
        mpu.waiting = False
        mpu.irq()
        mpu.p &= ~mpu.DECIMAL & 0xFF       # the 65C02 clears D on interrupts
        self.irqs += 1

    def _skip_idle(self, idle):
        if isinstance(idle, tuple):
            kind, waiting = idle
            if not waiting():
                return
        else:
            kind = idle
        mpu = self.mpu
        now = mpu.processorCycles
        if kind == "vbl":
            target = self.next_vbl
        else:                               # "line0": the next frame start
            target = (now // self.frame_cycles + 1) * self.frame_cycles
        if target > now:
            self.idle_cycles += target - now
            mpu.processorCycles = target
            if target >= self.next_vbl:
                self._vbl_event()

    def run(self, max_cycles, stop_pc=None):
        """Run for max_cycles; return True when stop_pc was reached (or the
        program quit through the fake ProDOS)."""
        mpu = self.mpu
        end = mpu.processorCycles + max_cycles
        stops = () if stop_pc is None else (
            stop_pc if isinstance(stop_pc, (set, tuple, list, dict)) else (stop_pc,))
        prodos = self.prodos
        step = self.step
        while mpu.processorCycles < end:
            step()
            if mpu.pc in stops:
                return True
            if prodos is not None and prodos.quit:
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

    # -- SHR (apple_cycle_renderer.c) ------------------------------------
    SHR4_MAGIC = bytes((0xD3, 0xC8, 0xD2, 0xB4))

    def _rgb(self, raw):
        """A 12-bit $0RGB value -> RGB888 as shr_pack_bgra (channel * 16),
        with the $C029 bit 5 luminance of shr_apply_c029_bw."""
        r, g, b = ((raw >> 8) & 15) * 16, ((raw >> 4) & 15) * 16, (raw & 15) * 16
        if self.newvideo & 0x20:
            y = (r * 77 + g * 150 + b * 29) >> 8
            return (y, y, y)
        return (r, g, b)

    def pal256_palette(self, bank=None):
        """The 256 PAL256 colours of aux $9E00-$9FFF as RGB888 triples."""
        mem = self.aux_banks[0] if bank is None else bank
        return [self._rgb(mem[0x9E00 + 2 * i] | (mem[0x9E01 + 2 * i] << 8))
                for i in range(256)]

    def pal256_active(self):
        """True when the renderer would show the PAL256 frame."""
        aux = self.aux_banks[0]
        return (bytes(aux[0x9DFC:0x9E00]) == self.SHR4_MAGIC and
                any((aux[a] >> 4) == 2 for a in range(0x9E01, 0xA000, 2)))

    def pal256_pixels(self, bank=None):
        """The 320x100 index bytes of a PAL256 field (aux $2000 + 320*y)."""
        mem = self.aux_banks[0] if bank is None else bank
        return bytes(mem[0x2000:0x2000 + 320 * 100])

    def _pal256_field(self, bank):
        from PIL import Image
        field = Image.frombytes("P", (320, 100), self.pal256_pixels(bank))
        palette = []
        for rgb in self.pal256_palette(bank):
            palette.extend(rgb)
        field.putpalette(palette)
        return field.convert("RGB")

    def shr_image(self):
        """The 640x400 output of the SHR screen (the module doc)."""
        from PIL import Image
        aux = self.aux_banks[0]
        if self.pal256_active():
            paged = aux[0x9DF8]
            if paged == 1:              # interlace: aux rows 0-99, main 100-199
                image = Image.new("RGB", (320, 200))
                image.paste(self._pal256_field(aux), (0, 0))
                image.paste(self._pal256_field(self.main), (0, 100))
                return image.resize((640, 400), Image.NEAREST)
            field = self._pal256_field(aux)
            if paged == 2:              # page flip: both fields merged 50/50
                other = self._pal256_field(self.main)
                a, b = field.tobytes(), other.tobytes()
                merged = bytes((x & y) + ((x ^ y) >> 1) for x, y in zip(a, b))
                field = Image.frombytes("RGB", (320, 100), merged)
            return field.resize((640, 400), Image.NEAREST)
        return self._standard_shr(aux)

    def _standard_shr(self, aux):
        from PIL import Image
        shr4 = bytes(aux[0x9DFC:0x9E00]) == self.SHR4_MAGIC
        pal256 = self.pal256_palette(aux) if shr4 else None
        image = Image.new("RGB", (640, 400))
        pixels = image.load()
        for row in range(200):
            scb = aux[0x9D00 + row]
            pal = 0x9E00 + (scb & 15) * 32
            table, selectors = [], []
            for index in range(16):
                lo, hi = aux[pal + index * 2], aux[pal + index * 2 + 1]
                table.append(self._rgb(lo | (hi << 8)))
                selectors.append(hi >> 4 if shr4 else 0)
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
                        # SHR4 selector 2 shows the whole byte through PAL256;
                        # RGGB (1) and direct colour (3) are not modelled
                        color = pal256[byte] if selectors[dot] == 2 else table[dot]
                        for dx in (0, 1):
                            x = (column * 2 + k) * 2 + dx
                            pixels[x, row * 2] = color
                            pixels[x, row * 2 + 1] = color
        return image
