#!/usr/bin/env python3
"""Run the port in the py65 test machine, drive it, save screenshots and
per-frame costs.

Usage: python3 tools/run_doom.py [--build DIR] [--data DIR] [--frames 120]
                                 [--speed turbo] [--banks 128] [--fast]
                                 [--do ACTION ...] [--shot FRAME ...]
                                 [--out DIR] [--stats FILE] [--trace LABEL]
                                 [--quiet]

The machine (tools/a2sim.py) is an enhanced //e with the mouse card in
slot 2, the Phasor in slot 4, `--banks` RamWorks banks and the TURBO frame
budget (1,250,000 cycles per 60 Hz frame; --speed N for a fixed N MHz
preset). By default it boots like the real machine: a2sim's fake ProDOS
holds DOOM.SYSTEM, the three images and every data file of --data, the
CPU starts DOOM.SYSTEM at $2000, and the loader (src/kernel/loader.s)
catalogs the volume, loads everything through the MLI and installs the
kernel. --fast puts the data and the images in place from Python and
starts at kernel_start (the same state, without the loader's cycles).

Time: FRAME in the actions and in --frames counts 60 Hz frames since the
kernel started. The frame loop's idle wait (idle_wait, for the next VBL)
and present's wait for line 0 (present_wait) are skipped by the model
(a2sim's idle skip): a run costs the work only.

Actions (`--do FRAME:ACTION`, applied at the first pass of the frame loop
at or after FRAME):
  key K            tap a key (a character, or a code such as 27 or 0x8B)
  hold K           hold a key down            release     release it
  mouse DX         move the mouse by DX (the PS's delta path)
  down / up        left mouse button          rdown / rup  right button
  oa 1|0           Open Apple down/up         ca 1|0       Closed Apple
  shot NAME        save NAME.png now
--shot FRAME saves frame_FRAME.png; the last screen is always saved as
OUT/final.png. --trace LABEL prints the registers each time LABEL runs.

Every rendered frame prints (unless --quiet): the frame, the 60 Hz frame
number at its blit, tics run, work cycles (since the previous rendered
frame, idle skipped), blit cycles, whether the blit waited for line 0,
$Cxxx accesses and SHR writes. --stats FILE writes them as JSON with a
summary (median/p99/max of work and blit, budget, frames over budget,
tics per 60 frames) and the boot cost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = HERE.parent
sys.path.insert(0, str(HERE))
import a2sim  # noqa: E402
import build_disk  # noqa: E402

DEFAULT_ROM = Path(os.environ.get("APPLETINI_ROOT", str(GAME.parents[2] / "appletini-one"))) \
    / "docs/Apple2e_Enhanced.rom"
IMAGES = {"RENDER.BIN": 0x0200, "LC.BIN": 0xD000, "GAME.BIN": 0x0200}


def default_build() -> Path:
    """build/ when it has a linked program, else the stand-in build."""
    if (GAME / "build/DOOM.SYSTEM").is_file():
        return GAME / "build"
    return GAME / "build/standin"


def labels_from(path: Path) -> dict[str, int]:
    labels = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            labels.setdefault(parts[2].lstrip("."), int(parts[1], 16))
    return labels


def parse_data_file(data: bytes) -> list[tuple[int, int, bytes]]:
    """The (bank, address, bytes) segments of an A2DM data file."""
    if data[:4] != b"A2DM" or data[4] != 1:
        raise ValueError("not a data file")
    count = data[5]
    out, offset = [], 256
    for i in range(count):
        base = 8 + 5 * i
        bank, address = data[base], data[base + 1] | (data[base + 2] << 8)
        length = data[base + 3] | (data[base + 4] << 8)
        out.append((bank, address, data[offset:offset + length]))
        offset += length
    return out


def parse_action(text: str) -> tuple[int, list[str]]:
    frame, _, rest = text.partition(":")
    words = rest.split()
    if not words:
        raise SystemExit(f"bad action: {text}")
    return int(frame), words


def key_code(word: str) -> int:
    return ord(word) if len(word) == 1 else int(word, 0)


class Doom:
    """A booted machine with the program's labels and the model hooks."""

    def __init__(self, build: Path | None = None, data: Path | None = None,
                 rom: Path = DEFAULT_ROM, speed="turbo", banks: int = 128,
                 fast: bool = False, io_cycles=None):
        self.build = Path(build) if build else default_build()
        self.data = Path(data) if data else self.build / "data"
        self.labels = labels_from(self.build / "doom.lbl")
        self.files = {name: (self.build / name).read_bytes()
                      for name in ("DOOM.SYSTEM", *IMAGES)}
        self.data_files = build_disk.data_files(self.data)
        self.fast = fast
        prodos = None
        if not fast:
            prodos = a2sim.FakeProDOS(volume="DOOM", launched="DOOM.SYSTEM")
            prodos.add("DOOM.SYSTEM", (0xFF, 0x2000, self.files["DOOM.SYSTEM"]))
            for name, address in IMAGES.items():
                prodos.add(name, (0x06, address, self.files[name]))
            for name, contents in self.data_files.items():
                prodos.add(name, (0x06, 0x0000, contents))
        self.machine = a2sim.Machine(rom, speed=speed, prodos=prodos,
                                     ramworks_banks=banks, io_cycles=io_cycles)
        self.mpu = self.machine.mpu
        L = self.labels
        m = self.machine
        # the model's idle skip: only while the loop would really wait
        m.idle_pcs[L["idle_wait"]] = ("vbl", lambda: m.main[L["vbl_count"]] == m.main[L["clk_last"]])
        m.idle_pcs[L["present_wait"]] = ("line0", m.in_vbl)
        self.boot_cycles = None
        self.start_cycle = None

    def label(self, name: str) -> int:
        return self.labels[name]

    # -- boot ---------------------------------------------------------------
    def boot(self, limit: int = 400_000_000) -> int:
        """Run until kernel_start; return the cycles the boot took."""
        m, mpu = self.machine, self.mpu
        start = self.label("kernel_start")
        if self.fast:
            self.install_fast()
        else:
            m.load(0x2000, self.files["DOOM.SYSTEM"])
            mpu.pc = 0x2000
            mpu.sp = 0xFF
            if not m.run(limit, stop_pc=start):
                raise RuntimeError(f"no kernel_start after {limit} cycles, PC ${mpu.pc:04X}:\n"
                                   + m.text_screen())
        self.boot_cycles = mpu.processorCycles
        return self.boot_cycles

    def install_fast(self) -> None:
        """What the loader leaves: data in the banks, the images in place,
        the language card on bank 2 read/write, A = the bank count."""
        m, mpu = self.machine, self.mpu
        for contents in self.data_files.values():
            for bank, address, blob in parse_data_file(contents):
                m.load(address, blob, aux_bank=bank)
        m.load(0x0200, self.files["GAME.BIN"], aux_bank=1)
        m.load(0x0200, self.files["RENDER.BIN"])
        lc = self.files["LC.BIN"]
        m.lc[False][0x1000:0x4000] = lc[:0x3000]           # bank 2 $D000-$FFFF
        m.lc_bank1[False][:] = lc[0x3000:0x4000]           # bank 1 $D000-$DFFF
        m.lc_read = m.lc_write = m.lc_bank2 = True
        mpu.pc = self.label("kernel_start")
        mpu.sp = 0xFF
        mpu.a = m.ramworks_banks
        mpu.p |= mpu.INTERRUPT

    # -- running -----------------------------------------------------------
    def run_to(self, label: str, limit: int = 50_000_000) -> bool:
        return self.machine.run(limit, stop_pc=self.label(label))

    def vbl_frame(self) -> int:
        """60 Hz frames since the kernel started."""
        return (self.mpu.processorCycles - self.start_cycle) // self.machine.frame_cycles \
            if self.start_cycle is not None else 0

    # -- reading -------------------------------------------------------------
    def lc_byte(self, address: int) -> int:
        m = self.machine
        if address < 0xE000 and not m.lc_bank2:
            return m.lc_bank1[False][address - 0xD000]
        return m.lc[False][address - 0xC000]

    def word(self, name: str, space: str = "auto") -> int:
        return self.byte(name, space) | (self.byte(name, space, 1) << 8)

    def byte(self, name: str, space: str = "auto", offset: int = 0) -> int:
        """A variable by label: zero page, the language card, main memory
        (RENDER) or bank 1 (GAME: space="game")."""
        address = self.label(name) + offset
        m = self.machine
        if address < 0x0200:
            return m.main[address]
        if address >= 0xD000:
            return self.lc_byte(address)
        if space == "game":
            return m.bank_memory(1)[address]
        return m.main[address]

    def view_buffer(self) -> bytes:
        v = self.label("VIEWBUF")
        return bytes(self.machine.main[v:v + 160 * 84])


class Runner:
    def __init__(self, args):
        self.args = args
        self.doom = Doom(args.build, args.data, args.rom, args.speed, args.banks, args.fast)
        self.machine = self.doom.machine
        self.mpu = self.machine.mpu
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.actions = sorted((parse_action(a) for a in args.do), key=lambda a: a[0])
        self.shots = sorted(set(args.shot))
        self.rows = []
        self.log = []

    def say(self, text: str) -> None:
        self.log.append(text)
        if not self.args.quiet:
            print(text)

    def save(self, name: str) -> None:
        path = self.out / f"{name}.png"
        self.machine.shr_image().save(path)
        self.say(f"saved {path}")

    def apply(self, words: list[str]) -> None:
        m = self.machine
        op = words[0]
        if op == "key":
            m.press(chr(key_code(words[1]) & 0x7F), at_cycle=self.mpu.processorCycles)
        elif op == "hold":
            m.hold(key_code(words[1]))
        elif op == "release":
            m.release()
        elif op == "mouse":
            m.mouse_delta(int(words[1]), 0)
        elif op in ("down", "up", "rdown", "rup"):
            card = m.mouse
            left, right = card.ps_buttons & 1, card.ps_buttons & 2
            if op == "down":
                left = 1
            elif op == "up":
                left = 0
            elif op == "rdown":
                right = 2
            else:
                right = 0
            m.mouse_buttons(bool(left), bool(right))
        elif op in ("oa", "ca"):
            m.buttons[0 if op == "oa" else 1] = 0x80 if words[1] != "0" else 0
        elif op == "shot":
            self.save(words[1])
        else:
            raise SystemExit(f"unknown action {op}")

    def run(self) -> int:
        d, m, mpu = self.doom, self.machine, self.mpu
        boot = d.boot()
        self.say(f"boot: {boot} cycles ({'fast' if d.fast else 'ProDOS'}), "
                 f"{len(d.data_files)} data files")
        d.start_cycle = mpu.processorCycles
        L = d.labels
        frame_top, blit, done = L["frame_top"], L["present_blit"], L["present_done"]
        wait, crash = L["present_wait"], L["kernel_crash_stop"]
        traces = {L[name]: name for name in self.args.trace}
        traced = 0
        end = d.start_cycle + self.args.frames * m.frame_cycles
        last_end = mpu.processorCycles
        last_idle = m.idle_cycles
        last_io = m.io_accesses
        last_shr = m.shr_writes
        last_tics = 0
        blit_start = None
        waited = False
        step = m.step
        while mpu.processorCycles < end:
            step()
            pc = mpu.pc
            if pc == frame_top:
                now = d.vbl_frame()
                while self.actions and self.actions[0][0] <= now:
                    _f, words = self.actions.pop(0)
                    self.say(f"frame {now}: {' '.join(words)}")
                    self.apply(words)
                while self.shots and self.shots[0] <= now:
                    self.save(f"frame_{self.shots.pop(0)}")
            elif pc == wait:
                waited = True
            elif pc == blit:
                blit_start = mpu.processorCycles
                blit_frame = m.frame_number()
                blit_idle = m.idle_cycles
            elif pc == done:
                tics = d.word("ktics")
                row = dict(frame=len(self.rows), vbl=d.vbl_frame(), tics=tics - last_tics,
                           work=mpu.processorCycles - last_end - (m.idle_cycles - last_idle),
                           blit=mpu.processorCycles - blit_start - (m.idle_cycles - blit_idle),
                           waited=waited, torn=m.frame_number() != blit_frame,
                           io=m.io_accesses - last_io, shr=m.shr_writes - last_shr)
                self.rows.append(row)
                if not self.args.quiet:
                    print("frame %4d vbl %5d tics %d work %8d blit %7d %s io %5d shr %6d"
                          % (row["frame"], row["vbl"], row["tics"], row["work"], row["blit"],
                             "waited" if waited else "      ", row["io"], row["shr"]))
                last_end, last_idle = mpu.processorCycles, m.idle_cycles
                last_io, last_shr, last_tics = m.io_accesses, m.shr_writes, tics
                waited = False
            elif pc == crash:
                self.say(f"frame {d.vbl_frame()}: kernel crash ${d.byte('kcrash'):02X}")
                break
            if pc in traces and traced < self.args.trace_limit:
                traced += 1
                print(f"frame {d.vbl_frame()}: {traces[pc]} A={mpu.a:02X} X={mpu.x:02X} "
                      f"Y={mpu.y:02X} P={mpu.p:02X} SP={mpu.sp:02X}")
        self.save("final")
        summary = self.summary()
        if summary:
            s = summary
            self.say(f"{s['frames']} frames rendered in {s['vbl_frames']} VBLs, {s['tics']} tics; "
                     f"work median {s['work']['median']} max {s['work']['max']}, blit median "
                     f"{s['blit']['median']} (budget {s['budget']}); {s['waited']} waited for "
                     f"line 0, {s['torn']} torn")
        if self.args.stats:
            path = Path(self.args.stats)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(boot_cycles=d.boot_cycles, fast=d.fast,
                                            speed=m.speed, frame_cycles=m.frame_cycles,
                                            frames=self.rows, summary=summary, log=self.log),
                                       indent=1) + "\n")
            self.say(f"saved {path}")
        return 0

    def summary(self) -> dict | None:
        rows = self.rows
        if not rows:
            return None
        n = len(rows)

        def quantiles(key):
            values = sorted(r[key] for r in rows)
            return dict(median=values[n // 2], p99=values[min(n - 1, n * 99 // 100)],
                        max=values[-1])

        budget = self.machine.frame_cycles
        return dict(frames=n, vbl_frames=self.doom.vbl_frame(), tics=sum(r["tics"] for r in rows),
                    budget=budget, over_budget=sum(1 for r in rows if r["work"] > budget),
                    work=quantiles("work"), blit=quantiles("blit"), io=quantiles("io"),
                    waited=sum(1 for r in rows if r["waited"]),
                    torn=sum(1 for r in rows if r["torn"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, default=None,
                    help="the linked program (default build/, else build/standin)")
    ap.add_argument("--data", type=Path, default=None, help="the data files (default BUILD/data)")
    ap.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    ap.add_argument("--speed", default="turbo", help="'turbo' or a fixed MHz preset")
    ap.add_argument("--banks", type=int, default=128, help="RamWorks banks (64 KB each)")
    ap.add_argument("--fast", action="store_true", help="skip the loader: place everything from Python")
    ap.add_argument("--frames", type=int, default=120, help="60 Hz frames to run")
    ap.add_argument("--out", default=str(GAME / "build/run"))
    ap.add_argument("--do", action="append", default=[], metavar="FRAME:ACTION")
    ap.add_argument("--shot", action="append", type=int, default=[], metavar="FRAME")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--trace", action="append", default=[], metavar="LABEL")
    ap.add_argument("--trace-limit", type=int, default=200)
    ap.add_argument("--stats", metavar="FILE")
    args = ap.parse_args()
    if args.speed != "turbo":
        args.speed = int(args.speed)
    return Runner(args).run()


if __name__ == "__main__":
    sys.exit(main())
