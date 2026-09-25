"""The game's cc65 build on a bare 65C02 (py65), for measurements and
differential tests (docs/DESIGN.md section 9).

    import gamesim
    g = gamesim.FlatGame()          # builds build/host/flat/GAME.FLAT if needed
    g.boot()                        # C start-up, game_init: E1M1 loaded
    cycles = g.tic(move=1)          # one game_tic with the input block set
    g.word("_leveltime")

The GAME code (the same src/game/*.c and *.s as GAME.BIN, compiled with
the Makefile's flags) is linked by tests/host/flat.cfg into one flat
64 KB memory: code and data at $0200-$FAFF (more than the GAME space, so
that code which does not fit it yet can be measured), the C stack below
$FF00, and a stand-in kernel (flatkern.s) at $FF00 whose far-access
entries stop on traps that this module services from the converter's
bank images. A far access is charged what the kernel's takes in GAME
space (DESIGN.md section 8: about 360 cycles plus 37 a byte), so the
cycle counts are those of the Apple less nothing but the kernel's own
bookkeeping around call_game.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import wad2a2  # noqa: E402

from py65.devices.mpu65c02 import MPU  # noqa: E402

DATA = PROJECT / "build/data"
OUT = PROJECT / ("build/host/flat" if "DOOM_GAMESRC" not in os.environ else "build/host/flat-snap")
CFLAGS = ["-t", "none", "--cpu", "65c02", "--standard", "c99", "-Oirs", "-g"]
FAR_BASE, FAR_PER_BYTE = 360, 37
# the whole game: the monsters part's code in the code-only window
# (flat.cfg, HarvardMPU), which leaves room for GAME.BIN's level-data
# caches (a_levdata.s) and E1M1's level memory
ASMDEFS = ["-D", "MCODE_WINDOW"]
# and the C modules' code in the other window (flat.cfg: MWIN2)
CWINDOW = ["--code-name", "MCODE2"]


def build(out: Path = OUT, only: list[str] | None = None, cfg: Path = HERE / "flat.cfg",
          asmdefs: list[str] | None = None, cwindow: list[str] | None = None) -> Path:
    """cc65/ca65/ld65 the game (or only the named src/game modules, e.g.
    ["fixed.s", "gtables.s"] for a unit test) into out/GAME.FLAT (+ .lbl)
    with the linker configuration cfg; ld65's failure raises
    subprocess.CalledProcessError with its messages in .stderr."""
    if asmdefs is None:                 # the whole game: the smaller caches
        asmdefs = ASMDEFS if only is None else []
    cwin = cwindow if cwindow is not None else CWINDOW if only is None else []
    out.mkdir(parents=True, exist_ok=True)
    src = Path(os.environ.get("DOOM_GAMESRC", PROJECT / "src/game"))
    cs = sorted(src.glob("*.c"))
    ss = [p for p in sorted(src.glob("*.s")) if p.name not in ("crt0.s",)]
    if only is not None:
        cs = [p for p in cs if p.name in only] + [HERE / n for n in only if (HERE / n).is_file()
                                                  and n.endswith(".c")]
        ss = [p for p in ss if p.name in only] + [HERE / n for n in only if n.endswith(".s")
                                                  and (HERE / n).is_file()]
    ss += [HERE / "flatkern.s", HERE / "flatcrt0.s"]
    deps = cs + ss + sorted(src.glob("*.h")) + sorted(src.glob("*.inc")) \
        + [PROJECT / "src/kernel/rview.inc"] \
        + [cfg, DATA / "doomdata.h", Path(__file__)]
    image = out / "GAME.FLAT"
    if image.is_file() and image.stat().st_mtime >= max(p.stat().st_mtime for p in deps):
        return image
    objs = []
    inc = ["-I", str(src), "-I", str(DATA)]
    for c in cs:
        s = out / (c.stem + ".s")
        subprocess.run(["cc65", *CFLAGS, *cwin, *inc, "-o", str(s), str(c)], check=True)
        o = out / (c.stem + ".o")
        subprocess.run(["ca65", "--cpu", "65c02", "-g", "-o", str(o), str(s)], check=True)
        objs.append(o)
    for s in ss:
        o = out / (s.stem + ".o")
        subprocess.run(["ca65", "--cpu", "65c02", "-g", "-I", str(src), "-I", str(DATA),
                        "-I", str(PROJECT / "src/kernel"), *asmdefs, "-o", str(o), str(s)],
                       check=True)
        objs.append(o)
    image.unlink(missing_ok=True)       # (a failed link leaves no image to reuse)
    subprocess.run(["ld65", "-C", str(cfg), "-m", str(out / "flat.map"),
                    "-Ln", str(out / "flat.lbl"), "-o", str(image)] + [str(o) for o in objs]
                   + ["none.lib"], check=True, capture_output=True, text=True)
    segs = segments(out / "flat.map")
    # the code windows must lie over data only: MCODE over RODATA .. GFAR,
    # MCODE2 above all the bank's own code
    bad = None
    if "MCODE" in segs and "GOVL" in segs:
        lo, hi = segs["MCODE"]
        if lo < segs["RODATA"][0] or hi > segs["GOVL"][0]:
            bad = f"MCODE ${lo:04X}-${hi:04X} (GOVL at ${segs['GOVL'][0]:04X})"
    if "MCODE2" in segs:
        lo, hi = segs["MCODE2"]
        if lo < segs["CODE"][1]:
            bad = f"MCODE2 ${lo:04X}-${hi:04X} (CODE ends at ${segs['CODE'][1]:04X})"
    if bad:
        image.unlink()
        raise subprocess.CalledProcessError(1, "ld65", stderr=f"{bad} is not over data only")
    return image


def segments(mapfile: Path) -> dict[str, tuple[int, int]]:
    """The segment list of an ld65 map: name -> (start, end + 1)."""
    out = {}
    text = mapfile.read_text()
    body = text[text.index("Segment list:"):]
    for line in body.splitlines()[4:]:
        p = line.split()
        if len(p) < 4 or not p[0].isidentifier():
            break
        out[p[0]] = (int(p[1], 16), int(p[2], 16) + 1)
    return out


class HarvardView:
    """The memory the CPU sees while it executes an instruction in a code
    window: each opcode/operand fetch comes from the windows' image;
    subsequent accesses to those same addresses read ordinary data.

    A data pointer can equal the current PC in this artificial memory map.
    Returning code solely by address silently made those reads fetch an
    opcode, which hid until a changed game layout put a sector there.
    """

    __slots__ = ("mem", "code", "pc0", "fetch_mask")

    def __init__(self, mem, code):
        self.mem, self.code, self.pc0, self.fetch_mask = mem, code, 0, 0

    def __getitem__(self, a):
        offset = a - self.pc0
        if 0 <= offset <= 2 and self.fetch_mask & (1 << offset):
            self.fetch_mask &= ~(1 << offset)
            return self.code[a]
        return self.mem[a]

    def __setitem__(self, a, v):
        self.mem[a] = v


class HarvardMPU(MPU):
    """py65's 65C02 with the code windows (flat.cfg): a step at a PC in a
    window runs with HarvardView as its memory. Cycles are the same; the
    windows are the harness's, not the Apple's."""

    _operand_bytes = {mode: 2 for mode in ("abs", "abx", "aby", "iax", "ind")}
    _operand_bytes.update({mode: 1 for mode in
                           ("imm", "inx", "iny", "rel", "zpg", "zpi", "zpx", "zpy")})

    def setup_windows(self, windows):
        """windows: [(start, image bytes)]"""
        self.raw = self.memory
        self.inwin = bytearray(65536)
        code = bytearray(65536 + 4)
        for lo, img in windows:
            code[lo:lo + len(img)] = img
            self.inwin[lo:lo + len(img)] = b"\x01" * len(img)
        self.view = HarvardView(self.memory, code)

    def step(self):
        pc = self.pc
        if self.inwin[pc]:
            v = self.view
            v.pc0 = pc
            size = 1 + self._operand_bytes.get(self.disassemble[v.code[pc]][1], 0)
            v.fetch_mask = (1 << size) - 1
            self.memory = v
            MPU.step(self)
            self.memory = self.raw
            return self
        return MPU.step(self)


def labels(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) >= 3 and p[0] == "al":
            out.setdefault(p[2].lstrip("."), int(p[1], 16))
    return out


class Crash(Exception):
    pass


class FlatGame:
    _banks = None

    def __init__(self, out: Path = OUT, only: list[str] | None = None):
        image = build(out, only)
        self.L = labels(out / "flat.lbl")
        self.mem = bytearray(65536)
        data = image.read_bytes()
        self.mem[0x0200:0x0200 + len(data)] = data
        kern = Path(str(image) + ".kern").read_bytes()
        self.mem[0xFF00:0xFF00 + len(kern)] = kern
        self.mpu = HarvardMPU(memory=self.mem)
        segs = segments(out / "flat.map")
        windows = []
        for seg, ext in (("MCODE", ".mcode"), ("MCODE2", ".mcode2")):
            f = Path(str(image) + ext)
            if seg in segs and f.is_file():
                windows.append((segs[seg][0], f.read_bytes()))
        self.mpu.setup_windows(windows)
        if FlatGame._banks is None:
            FlatGame._banks = {b: bytearray(img) for b, img in wad2a2.load_banks(DATA).items()}
        self.banks = {b: bytearray(img) for b, img in FlatGame._banks.items()}
        L = self.L
        self.traps = {L["trap_far_read"]: self._far_read, L["trap_far_write"]: self._far_write,
                      L["trap_far_copy"]: self._far_copy, L["trap_far_elem"]: self._far_elem,
                      L["trap_crash"]: self._crash}
        self.mem[L["kbanks"]] = 128
        self.far_calls = 0
        self.far_bytes = 0

    # --- memory -----------------------------------------------------------
    def bank(self, b):
        if b not in self.banks:
            self.banks[b] = bytearray(65536)
        return self.banks[b]

    def byte(self, name, off=0):
        return self.mem[self.L[name] + off]

    def word(self, name, off=0):
        a = self.L[name] + off
        return self.mem[a] | self.mem[a + 1] << 8

    def long(self, name, off=0):
        a = self.L[name] + off
        v = int.from_bytes(self.mem[a:a + 4], "little")
        return v - (1 << 32) if v & 0x80000000 else v

    def zp(self, name, n):
        a = self.L[name]
        return int.from_bytes(self.mem[a:a + n], "little")

    # --- the traps ----------------------------------------------------------
    def _far_read(self):
        src, ptr, n = self.zp("far_src", 3), self.zp("far_ptr", 2), self.zp("far_len", 2)
        b = self.bank(src >> 16)
        self.mem[ptr:ptr + n] = b[src & 0xFFFF:(src & 0xFFFF) + n]
        return FAR_BASE + FAR_PER_BYTE * n, n

    def _far_write(self):
        dst, ptr, n = self.zp("far_dst", 3), self.zp("far_ptr", 2), self.zp("far_len", 2)
        b = self.bank(dst >> 16)
        b[dst & 0xFFFF:(dst & 0xFFFF) + n] = self.mem[ptr:ptr + n]
        return FAR_BASE + FAR_PER_BYTE * n, n

    def _far_copy(self):
        src, dst, n = self.zp("far_src", 3), self.zp("far_dst", 3), self.zp("far_len", 2)
        data = bytes(self.bank(src >> 16)[src & 0xFFFF:(src & 0xFFFF) + n])
        self.bank(dst >> 16)[dst & 0xFFFF:(dst & 0xFFFF) + n] = data
        return FAR_BASE + 2 * FAR_PER_BYTE * n, n

    def _far_elem(self):
        m = self.mpu
        desc = m.a | m.x << 8
        idx = self.zp("far_idx", 2)
        bank, base = self.mem[desc], self.mem[desc + 1] | self.mem[desc + 2] << 8
        size = self.mem[desc + 3] | self.mem[desc + 4] << 8
        log2 = self.mem[desc + 5]
        addr = base + (idx & ((1 << log2) - 1)) * size
        a = self.L["far_src"]
        self.mem[a] = addr & 0xFF
        self.mem[a + 1] = (addr >> 8) & 0xFF
        self.mem[a + 2] = (bank + (idx >> log2)) & 0xFF
        return 600, 0

    def _crash(self):
        raise Crash(f"kernel_crash ${self.mpu.a:02X}")

    # --- running -------------------------------------------------------------
    def call(self, label, a=0, x=0, limit=200_000_000) -> int:
        """JSR a routine (label or address) through host_call; returns the
        cycles it took, far accesses charged as the kernel's."""
        m, L = self.mpu, self.L
        addr = L[label] if isinstance(label, str) else label
        h = L["hcall"]
        self.mem[h], self.mem[h + 1] = addr & 0xFF, addr >> 8
        m.pc = L["host_call"]
        m.sp = 0xFF
        m.a, m.x = a, x
        stop, traps = L["host_stop"], self.traps
        start = m.processorCycles
        extra = 0
        step = m.step
        while True:
            pc = m.pc
            if pc == stop:
                break
            t = traps.get(pc)
            if t is not None:
                cyc, n = t()
                extra += cyc
                self.far_calls += 1
                self.far_bytes += n
            step()
            if m.processorCycles - start > limit:
                raise RuntimeError(f"{label} runs past {limit} cycles, PC ${m.pc:04X}")
        return m.processorCycles - start + extra

    def ccall(self, label, *args) -> int:
        """Call a C function (cc65 __fastcall__): args are (value, size)
        pairs, size 1, 2 or 4; all but the last go on the C stack in order,
        the last in A/X/sreg. Returns A/X/sreg as an unsigned 32-bit value
        (the cycles in self.cycles)."""
        m, mem = self.mpu, self.mem
        spa = self.L["sp"]
        sp = mem[spa] | mem[spa + 1] << 8
        for value, size in args[:-1]:
            sp -= size
            mem[sp:sp + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
        mem[spa], mem[spa + 1] = sp & 0xFF, sp >> 8
        a = x = 0
        if args:
            value, size = args[-1]
            value &= (1 << (8 * size)) - 1
            a, x = value & 0xFF, (value >> 8) & 0xFF
            sr = self.L["sreg"]
            mem[sr] = (value >> 16) & 0xFF
            mem[sr + 1] = (value >> 24) & 0xFF
        self.cycles = self.call(label, a, x)
        sr = self.L["sreg"]
        return m.a | m.x << 8 | mem[sr] << 16 | mem[sr + 1] << 24

    def boot(self) -> int:
        self.call("game_boot")
        return self.call("_game_init")

    def set_input(self, move=0, buttons=0, mouse=0, weapon=0):
        k = self.L["kin"]
        self.mem[k] = mouse & 0xFF
        self.mem[k + 1] = (mouse >> 8) & 0xFF
        self.mem[k + 2] = buttons
        self.mem[k + 3] = move
        self.mem[k + 6] = weapon

    def tic(self, move=0, buttons=0, mouse=0, weapon=0) -> int:
        self.set_input(move, buttons, mouse, weapon)
        return self.call("_game_tic")

    def frame(self) -> int:
        return self.call("_game_frame")
