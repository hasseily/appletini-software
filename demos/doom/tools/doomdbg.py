"""Debug helpers: boot the port in the py65 test machine and call its routines.

    import doomdbg
    d = doomdbg.Dbg(frames=2)                 # boot (fast), run two 60 Hz frames
    d.far(3, 0x0200)[:4]                      # bytes of a RamWorks bank
    d.zp('far_src', [0x00, 0x02, 3])          # set zero-page parameters
    cycles = d.call('far_read')               # JSR a labelled routine (RENDER space)
    d.call('_game_tic', space='game')         # a GAME-space routine
    d.run_frames(10)                          # more frames of the frame loop
    d.m.shr_image().save('x.png')

Dbg(frames, build=..., prodos=False) boots through tools/run_doom.py's Doom
(--fast unless prodos=True) and runs `frames` 60 Hz frames of the frame
loop. `call` runs one routine with interrupts off and returns the cycles
it took (from the JSR to the return, $Cxxx accesses charged as the model
does): a driver in page 1 at DRIVER ($0140-$017F, the stub area the
kernel leaves free) does JSR label (with space_game / space_render around
it for space='game') and stops at its last byte. The program's PC, stack
pointer and flags are restored, so run_frames can carry on.
If a banked frame was paused in progress, call first finishes that frame
to reach the next main renderer boundary before injecting its driver.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_doom  # noqa: E402

DRIVER = 0x0140


class Dbg:
    def __init__(self, frames=2, build=None, data=None, prodos=False, speed="turbo",
                 banks=128, io_cycles=None):
        self.d = run_doom.Doom(build, data, speed=speed, banks=banks, fast=not prodos,
                               io_cycles=io_cycles)
        self.m = self.d.machine
        self.mpu = self.m.mpu
        self.L = self.d.labels
        self.cycles = None
        self.regs = None
        self.boot_cycles = self.d.boot()
        self.d.start_cycle = self.mpu.processorCycles
        if frames:
            self.run_frames(frames)

    # -- memory ------------------------------------------------------------
    def far(self, bank: int, address: int, length: int = 16) -> bytes:
        return bytes(self.m.bank_memory(bank)[address:address + length])

    def put_far(self, bank: int, address: int, data: bytes) -> None:
        self.m.bank_memory(bank)[address:address + len(data)] = data

    def zp(self, name: str, values) -> None:
        """Write bytes (or one int) at a zero-page (or any main) label."""
        address = self.L[name]
        values = [values] if isinstance(values, int) else list(values)
        for i, v in enumerate(values):
            self.m.main[address + i] = v & 0xFF

    def get(self, name: str, width: int = 1, space: str = "auto") -> int:
        if width == 1:
            return self.d.byte(name, space)
        return self.d.word(name, space)

    # -- running -------------------------------------------------------------
    def _main_pc(self, address: int) -> bool:
        """The injected driver and kernel hooks execute in main context."""
        return self.mpu.pc == address and (not self.d.banked or not self.m.sw["altzp"])

    def _check_crash(self) -> None:
        if self._main_pc(self.L["kernel_crash_stop"]):
            raise RuntimeError(f"kernel crash ${self.d.byte('kcrash'):02X}")

    def call(self, label, a=0, x=0, y=0, space="render", limit=20_000_000) -> int:
        """JSR the routine (a label or an address) with the registers set and
        interrupts off; returns the cycles from the JSR to its return.

        A paused banked frame must finish before the main page-one driver
        can safely replace execution, including any partial phase copy.
        This does not initialize a
        frames=0 debugger stopped at kernel_start.
        """
        m, mpu = self.m, self.mpu
        self._check_crash()
        if self.d.banked and not any(self._main_pc(self.L[name])
                                     for name in ("kernel_start", "frame_top")):
            steps = 0
            while not self._main_pc(self.L["frame_top"]):
                if steps >= limit:
                    raise RuntimeError(f"no main frame boundary before {label}, PC ${mpu.pc:04X}")
                m.step()
                steps += 1
                self._check_crash()
        addr = self.L[label] if isinstance(label, str) else label
        code = bytearray()
        if space == "game":
            code += bytes((0x20,)) + self.L["space_game"].to_bytes(2, "little")
        code += bytes((0xA9, a & 255, 0xA2, x & 255, 0xA0, y & 255, 0x20)) + addr.to_bytes(2, "little")
        if space == "game":
            code += bytes((0x20,)) + self.L["space_render"].to_bytes(2, "little")
        code += bytes((0xEA,))          # the stop
        assert len(code) <= 0x40
        m.main[DRIVER:DRIVER + len(code)] = code
        pc0, sp0, p0 = mpu.pc, mpu.sp, mpu.p
        mpu.pc = DRIVER
        mpu.sp = (sp0 - 8) & 0xFF       # below whatever the program had pushed
        mpu.p |= mpu.INTERRUPT
        stop = DRIVER + len(code) - 1
        jsr = DRIVER + (3 if space == "game" else 0) + 6
        start = None
        ret = jsr + 3
        steps = 0
        self.cycles = None
        while not self._main_pc(stop) and steps < limit:
            if self._main_pc(jsr) and start is None:
                start = mpu.processorCycles
            m.step()
            steps += 1
            self._check_crash()
            if self._main_pc(ret) and start is not None and self.cycles is None:
                self.cycles = mpu.processorCycles - start
        if not self._main_pc(stop):
            raise RuntimeError(f"{label} did not return, PC ${mpu.pc:04X}")
        cycles, self.cycles = self.cycles, None
        self.regs = (mpu.a, mpu.x, mpu.y, mpu.p)
        mpu.pc, mpu.sp, mpu.p = pc0, sp0, p0
        return cycles

    def run_frames(self, n: int) -> None:
        """Run the frame loop for n more 60 Hz frames."""
        end = self.mpu.processorCycles + n * self.m.frame_cycles
        step = self.m.step
        mpu = self.mpu
        self._check_crash()
        while mpu.processorCycles < end:
            step()
            self._check_crash()
