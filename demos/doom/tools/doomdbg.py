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
    def call(self, label, a=0, x=0, y=0, space="render", limit=20_000_000) -> int:
        """JSR the routine (a label or an address) with the registers set and
        interrupts off; returns the cycles from the JSR to its return."""
        addr = self.L[label] if isinstance(label, str) else label
        code = bytearray()
        if space == "game":
            code += bytes((0x20,)) + self.L["space_game"].to_bytes(2, "little")
        code += bytes((0xA9, a & 255, 0xA2, x & 255, 0xA0, y & 255, 0x20)) + addr.to_bytes(2, "little")
        if space == "game":
            code += bytes((0x20,)) + self.L["space_render"].to_bytes(2, "little")
        code += bytes((0xEA,))          # the stop
        assert len(code) <= 0x40
        m, mpu = self.m, self.mpu
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
        while mpu.pc != stop and steps < limit:
            if mpu.pc == jsr and start is None:
                start = mpu.processorCycles
            m.step()
            steps += 1
            if mpu.pc == ret and start is not None and self.cycles is None:
                self.cycles = mpu.processorCycles - start
        if steps >= limit:
            raise RuntimeError(f"{label} did not return, PC ${mpu.pc:04X}")
        cycles, self.cycles = self.cycles, None
        self.regs = (mpu.a, mpu.x, mpu.y, mpu.p)
        mpu.pc, mpu.sp, mpu.p = pc0, sp0, p0
        return cycles

    def run_frames(self, n: int) -> None:
        """Run the frame loop for n more 60 Hz frames."""
        end = self.mpu.processorCycles + n * self.m.frame_cycles
        crash = self.L["kernel_crash_stop"]
        step = self.m.step
        mpu = self.mpu
        while mpu.processorCycles < end:
            step()
            if mpu.pc == crash:
                raise RuntimeError(f"kernel crash ${self.d.byte('kcrash'):02X}")
