"""Debug helpers: boot the port in the py65 test machine and call its routines.

    import pcsdbg
    d = pcsdbg.Dbg(frames=2)                  # boot, run two frames
    d.set('ps_id', 105); d.set('ps_x', 266, 2); d.set('ps_y', 2)
    d.call('panel_sprite')                    # JSR a labelled routine
    print(d.screen_pix(2, 266, 292))          # nibbles of a screen row
    d.run_frames(10)                          # more frames (actions from `do`)

Dbg(frames, do=[...]) takes the same action strings as run_editor.py's
--do. `call` runs until the routine returns (a BRK driver at $1F80).
Labels come from build/PCS.lbl (duplicates: the last definition wins, so
EDIT/WIRE-local names may need an explicit address).
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import run_editor

class Dbg:
    def __init__(self, frames=2, do=(), quiet=True):
        class A: pass
        a = A(); a.rom = run_editor.DEFAULT_ROM; a.speed = 33; a.frames = frames
        a.out = 'build/run'; a.do = list(do); a.shot = []; a.quiet = quiet; a.trace = []; a.trace_limit = 0
        self.r = run_editor.Runner(a)
        self.r.work_start = self.r.mpu.processorCycles
        if frames:
            self.r.run()
        self.m = self.r.machine; self.mem = self.m.main; self.L = self.r.labels; self.mpu = self.m.mpu
        self.aux = self.m.aux_banks[0]

    def w(self, a): return self.mem[a] | (self.mem[a + 1] << 8)
    def set(self, name, value, width=1):
        a = self.L[name]
        self.mem[a] = value & 255
        if width == 2: self.mem[a + 1] = value >> 8
    def get(self, name, width=1):
        return self.w(self.L[name]) if width == 2 else self.mem[self.L[name]]

    def call(self, label, a=0, x=0, y=0, altzp=False, limit=2_000_000):
        drv = 0x1F80
        addr = self.L[label]
        code = bytearray()
        if altzp: code += bytes([0x8D, 0x09, 0xC0])
        code += bytes([0xA9, a & 255, 0xA2, x & 255, 0xA0, y & 255, 0x20, addr & 255, addr >> 8])
        if altzp: code += bytes([0x8D, 0x08, 0xC0])
        code += bytes([0x00])
        self.mem[drv:drv + len(code)] = code
        mpu = self.mpu; mpu.pc = drv; mpu.sp = 0xF0
        n = 0
        stop = drv + len(code) - 1
        while mpu.pc != stop and n < limit:
            mpu.step(); n += 1
        return n

    def screen_row(self, y, x0, x1):
        return self.aux[0x2000 + 160 * y + x0 // 2:0x2000 + 160 * y + (x1 + 1) // 2].hex(' ')
    def screen_pix(self, y, x0, x1):
        b = self.aux[0x2000 + 160 * y + x0 // 2:0x2000 + 160 * y + (x1 + 1) // 2]
        return ''.join('%X%X' % (v >> 4, v & 15) for v in b)
    def arena_rows(self, stride, rows, width=None):
        width = width or stride
        out = []
        for y in range(rows):
            b = self.mem[0xBB00 + stride * y:0xBB00 + stride * y + width]
            out.append(''.join('%X%X' % (v >> 4, v & 15) for v in b))
        return out
    def run_frames(self, n):
        r = self.r; mpu = self.mpu; m = self.m
        target = r.frames + n
        while r.frames < target:
            mpu.step()
            if mpu.pc == r.wait:
                r.frame_done(); r.frames += 1
                mpu.processorCycles = (mpu.processorCycles // m.frame_cycles + 1) * m.frame_cycles
                mpu.pc = r.wait_rts; r.work_start = mpu.processorCycles
