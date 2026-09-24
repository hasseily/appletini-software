#!/usr/bin/env python3
"""Run the port in the py65 test machine, drive it with the mouse and
keyboard, and save screenshots and per-frame statistics.

Usage: python3 tools/run_editor.py [--rom ROM] [--speed 33] [--frames 300]
                                   [--out build/run] [--do ACTION ...]
                                   [--shot FRAME ...] [--quiet]

The machine (tools/a2sim.py) runs build/PCS.SYSTEM at the modelled vTW
speed with the mouse card in slot 2 and the Phasor in slot 4. There is no
ProDOS: the file is placed at $2000, the CPU starts there and the test
fills the auxiliary language card and RamWorks bank 1 from build/PCS.SPR
itself (the loader sees no MLI and does nothing). The idle wait for line 0
(video_wait_vbl) is skipped, so a run costs the frames' work only.

Actions (`--do`, applied when the frame counter reaches FRAME):
  FRAME:move X Y      the mouse is published at (X, Y)
  FRAME:down          left button down     FRAME:up      button up
  FRAME:click X Y     move, then down for 3 frames, then up
  FRAME:drag X Y      move with the button held (down stays down)
  FRAME:key K         tap a key (a character, or a code such as 27 or 0x8B)
  FRAME:hold K        hold a key down       FRAME:release  release it
  FRAME:shot NAME     save NAME.png now
--trace LABEL prints A, X, Y, SCANLINE and the caller each time the
routine LABEL is entered (at most --trace-limit times).

Every frame prints (unless --quiet): state, work cycles, bytes that would
use the 1 MHz bus, $Cxxx accesses, rectangles rendered, the cursor. The
last screen is always saved as OUT/final.png; a screen is also saved
whenever the mailbox state changes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = HERE.parent
sys.path.insert(0, str(HERE))
import a2sim  # noqa: E402
import gen_assets  # noqa: E402

import os
DEFAULT_ROM = Path(os.environ.get("APPLETINI_ROOT", str(GAME.parents[2] / "appletini-one"))) \
    / "docs/Apple2e_Enhanced.rom"
MAILBOX = 0x0300
STATES = {0: "boot", 1: "edit", 2: "wire", 3: "magnify", 4: "disk", 5: "play", 6: "game",
          7: "title", 8: "quit"}


def labels_from(path: Path) -> dict[str, int]:
    labels = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            labels[parts[2].lstrip(".")] = int(parts[1], 16)
    return labels


def load_sprite_file(machine: a2sim.Machine, path: Path) -> None:
    """Put PCS.SPR's regions where loader.s would: the auxiliary language
    card (ALTZP) and RamWorks bank 1 for the raw-row region."""
    for addr, _length, bank, blob in gen_assets.parse_spr_file(path.read_bytes()):
        if bank & gen_assets.BANK_RW1:
            machine.load(addr, blob, aux_bank=1)
            continue
        altzp = bool(bank & gen_assets.BANK_AUX)
        for i, value in enumerate(blob):
            a = addr + i
            if a < 0xE000 and bank & gen_assets.BANK_1:
                machine.lc_bank1[altzp][a - 0xD000] = value
            else:
                machine.lc[altzp][a - 0xC000] = value


def parse_action(text: str) -> tuple[int, list[str]]:
    frame, _, rest = text.partition(":")
    words = rest.split()
    if not words:
        raise SystemExit(f"bad action: {text}")
    return int(frame), words


def key_code(word: str) -> int:
    if len(word) == 1:
        return ord(word)
    return int(word, 0)


class Runner:
    def __init__(self, args):
        self.args = args
        self.labels = labels_from(GAME / "build/PCS.lbl")
        self.machine = a2sim.Machine(args.rom, speed=args.speed)
        self.machine.load(0x2000, (GAME / "build/PCS.SYSTEM").read_bytes())
        load_sprite_file(self.machine, GAME / "build/PCS.SPR")
        self.mpu = self.machine.mpu
        self.mpu.pc = 0x2000
        self.mpu.sp = 0xFF
        self.wait = self.labels["video_wait_vbl"]
        # the rts that ends the wait loop
        pc = self.wait
        while self.machine.main[pc] != 0x60:
            pc += 1
        self.wait_rts = pc
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.frames = 0
        self.stats = []
        self.last_state = None
        self.actions = sorted((parse_action(a) for a in args.do), key=lambda a: a[0])
        self.shots = set(args.shot)
        self.pending_up = None
        self.log = []

    def mailbox(self) -> bytes:
        return bytes(self.machine.main[MAILBOX:MAILBOX + 20])

    def save(self, name: str) -> None:
        path = self.out / f"{name}.png"
        self.machine.shr_image().save(path)
        self.say(f"saved {path}")

    def say(self, text: str) -> None:
        self.log.append(text)
        if not self.args.quiet:
            print(text)

    def apply(self, words: list[str]) -> None:
        m = self.machine
        op = words[0]
        if op == "move":
            m.mouse_move(int(words[1]), int(words[2]))
        elif op == "down":
            m.mouse_buttons(True, False)
        elif op == "up":
            m.mouse_buttons(False, False)
        elif op == "click":
            m.mouse_move(int(words[1]), int(words[2]))
            m.mouse_buttons(True, False)
            self.pending_up = self.frames + 3
        elif op == "drag":
            m.mouse_move(int(words[1]), int(words[2]))
        elif op == "key":
            m.press(chr(key_code(words[1]) & 0x7F), at_cycle=self.mpu.processorCycles)
        elif op == "hold":
            m.hold(key_code(words[1]))
        elif op == "release":
            m.release()
        elif op == "shot":
            self.save(words[1])
        else:
            raise SystemExit(f"unknown action {op}")

    def frame_done(self) -> None:
        """Called at video_wait_vbl: one frame of work is complete."""
        m = self.machine
        mb = self.mailbox()
        ok = mb[:4] == b"PCS1"
        state = mb[4] if ok else -1
        work = self.mpu.processorCycles - self.work_start
        bus, m.video_writes = m.video_writes, 0
        io, m.io_accesses = m.io_accesses, 0
        writes = mb[7] | (mb[8] << 8)
        rects = mb[11]
        mx = mb[12] | (mb[13] << 8)
        my = mb[14]
        self.stats.append((state, work, bus, io, writes, rects))
        if not self.args.quiet:
            print("frame %4d %-8s work %7d bus %5d io %4d writes %5d rects %2d cursor %3d,%3d input %02X ticks %d"
                  % (self.frames, STATES.get(state, state), work, bus, io, writes, rects, mx, my,
                     mb[15], mb[16]))
        if state != self.last_state:
            self.say(f"frame {self.frames}: state {STATES.get(state, state)}")
            if self.last_state is not None:
                self.save(f"state_{STATES.get(state, state)}_{self.frames}")
            self.last_state = state
        if self.frames in self.shots:
            self.save(f"frame_{self.frames}")
        while self.actions and self.actions[0][0] <= self.frames:
            _f, words = self.actions.pop(0)
            self.say(f"frame {self.frames}: {' '.join(words)}")
            self.apply(words)
        if self.pending_up is not None and self.frames >= self.pending_up:
            m.mouse_buttons(False, False)
            self.pending_up = None

    def run(self) -> int:
        m = self.machine
        mpu = self.mpu
        self.work_start = mpu.processorCycles
        limit = 4_000_000 * m.speed         # cycles of one frame's work before giving up
        traces = {self.labels[name]: name for name in self.args.trace}
        traced = 0
        while self.frames < self.args.frames:
            mpu.step()
            if mpu.pc in traces and traced < self.args.trace_limit:
                traced += 1
                print(f"frame {self.frames}: {traces[mpu.pc]} A={mpu.a:02X} X={mpu.x:02X} "
                      f"Y={mpu.y:02X} SCANLINE={m.main[0x1F]} from {self.nearest(self.return_pc())}")
            if mpu.pc == self.wait:
                self.frame_done()
                self.frames += 1
                # skip the idle wait: jump to the next frame's line 0
                cycles = mpu.processorCycles
                mpu.processorCycles = (cycles // m.frame_cycles + 1) * m.frame_cycles
                mpu.pc = self.wait_rts
                self.work_start = mpu.processorCycles
                continue
            if (mpu.pc < 0x0C00 and not 0x0110 <= mpu.pc < 0x0180) or 0xBF00 <= mpu.pc < 0xC000:
                self.say(f"frame {self.frames}: PC left the program at ${mpu.pc:04X} "
                         f"(quit or crash); sp ${mpu.sp:02X}")
                break
            if mpu.processorCycles - self.work_start > limit:
                self.say(f"frame {self.frames}: no frame end after {limit} cycles, "
                         f"PC ${mpu.pc:04X} ({self.nearest(mpu.pc)})")
                break
        self.save("final")
        self.summary()
        return 0

    def return_pc(self) -> int:
        """The caller of the routine just entered (the return address on the stack)."""
        sp = self.mpu.sp
        lo = self.machine.main[0x100 + ((sp + 1) & 0xFF)]
        hi = self.machine.main[0x100 + ((sp + 2) & 0xFF)]
        return ((hi << 8) | lo) - 2

    def nearest(self, pc: int) -> str:
        best = ("?", -1)
        for name, addr in self.labels.items():
            if best[1] < addr <= pc:
                best = (name, addr)
        return f"{best[0]}+{pc - best[1]}" if best[1] >= 0 else "?"

    def summary(self) -> None:
        if not self.stats:
            return
        works = sorted(s[1] for s in self.stats)
        buses = sorted(s[2] for s in self.stats)
        n = len(works)
        budget = self.machine.frame_cycles
        over = sum(1 for w in works if w > budget)
        print(f"{n} frames: work median {works[n // 2]} p99 {works[min(n - 1, n * 99 // 100)]} "
              f"max {works[-1]} cycles (budget {budget}); bus median {buses[n // 2]} "
              f"max {buses[-1]} bytes; {over} frames over budget")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    ap.add_argument("--speed", type=int, default=33)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--out", default=str(GAME / "build/run"))
    ap.add_argument("--do", action="append", default=[], metavar="ACTION")
    ap.add_argument("--shot", action="append", type=int, default=[], metavar="FRAME")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--trace", action="append", default=[], metavar="LABEL",
                    help="print the registers whenever this routine is entered")
    ap.add_argument("--trace-limit", type=int, default=200)
    args = ap.parse_args()
    return Runner(args).run()


if __name__ == "__main__":
    sys.exit(main())
