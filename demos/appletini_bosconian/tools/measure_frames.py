#!/usr/bin/env python3
"""Measure CPU cycles and 1 MHz-bus bytes per frame in the py65 test machine.

Usage: python3 tools/measure_frames.py [--rom ROM] [--speed 33] [--frames 900]
                                       [--out build/frames] [--turbo]
                                       [--profile] [--labels build/BOSCO.lbl]

The machine (tools/a2sim.py, from the Bilestoad port) runs BOSCO.SYSTEM at a
modelled vTW speed. The ProDOS loader is skipped: the file is placed at
$2000 and the CPU starts there. The idle time in video_wait_vbl is skipped,
so the script sees the work of every frame: CPU cycles between two waits,
bytes that would use the 1 MHz bus (main $0400-$0BFF and $2000-$5FFF, aux
$2000-$9FFF) and $Cxxx accesses. Play is scripted like tools/cheat_test.py:
start a game, leave one base alive, put the ship on its axis and shoot the
cannon and the core; keys and fire are pressed through the model's keyboard.

It prints the median, 99th percentile and maximum of the CPU work and the
bus bytes over the play frames, the number of frames over the 60 Hz budget,
and saves SHR frames at each event to OUT. --turbo makes bus bytes free
(TURBO sends video writes to the renderer at fabric speed) and reports only
the CPU budget. --profile charges every instruction's cycles to the nearest
label at or below its address (build with -g to get labels for static C
functions: see the Makefile's `profile` target) and prints the top routines
by their own cycles over the play frames.
"""
import argparse
import bisect
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = HERE.parent
sys.path.insert(0, str(HERE))
import a2sim  # noqa: E402

FRAME_1MHZ = 17030
BUS_BUDGET = 16000
ST = {0: "BOOT", 1: "TITLE", 2: "PLAY", 3: "DYING", 4: "GAME_OVER",
      5: "ROUND_CLEAR", 6: "PAUSED"}
KEY_FOR_HEADING = {0: "i", 2: "l", 4: "k", 6: "j", 1: "o", 3: ",", 5: "m", 7: "u"}


def labels_from(path):
    labels = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "al":
            labels[parts[2].lstrip(".")] = int(parts[1], 16)
    return labels


def word(machine, address):
    return machine.main[address] | (machine.main[address + 1] << 8)


def wrap(delta, size):
    delta %= size
    return delta - size if delta >= size // 2 else delta


def load_sprite_file(machine, path):
    """Put the regions of build/BOSCO.SPR where loader.s would: the machine has
    no ProDOS, so the game's loader does nothing and the test fills the
    language card itself (gen_assets.py describes the file)."""
    sys.path.insert(0, str(GAME / "tools"))
    import gen_assets
    for addr, length, bank, blob in gen_assets.parse_spr_file(path.read_bytes()):
        altzp = bool(bank & gen_assets.BANK_AUX)
        for i, value in enumerate(blob):
            a = addr + i
            if a < 0xE000 and bank & gen_assets.BANK_1:
                machine.lc_bank1[altzp][a - 0xD000] = value
            else:
                machine.lc[altzp][a - 0xC000] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rom", default=str(GAME.parents[2] / "appletini-one/docs/Apple2e_Enhanced.rom"))
    parser.add_argument("--speed", type=int, default=33)
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--out", default=str(GAME / "build/frames"))
    parser.add_argument("--turbo", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--labels", default=str(GAME / "build/BOSCO.lbl"))
    args = parser.parse_args()

    labels = labels_from(args.labels)
    code_labels = sorted((a, n) for n, a in labels.items()
                         if 0x2000 <= a < 0xC000 and not re.match(r"^L[0-9A-F]{3,}$", n))
    code_addrs = [a for a, _ in code_labels]
    profile = {}

    def routine(pc):
        i = bisect.bisect_right(code_addrs, pc) - 1
        return code_labels[i][1] if i >= 0 else "?"
    L = lambda name: labels["_" + name]        # noqa: E731
    machine = a2sim.Machine(args.rom, speed=args.speed)
    machine.load(0x2000, (GAME / "build/BOSCO.SYSTEM").read_bytes())
    load_sprite_file(machine, GAME / "build/BOSCO.SPR")
    mpu = machine.mpu
    mpu.pc = 0x2000
    mpu.sp = 0xFF
    wait = L("video_wait_vbl")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    budget = machine.frame_cycles

    frames = 0
    work_start = mpu.processorCycles
    stats = []                       # (work, bus, io, state) for play frames
    seen_events = set()
    last_state = None
    started = False
    cheated = False
    placed = False
    heading = None
    fire_due = 0
    dodge = []                       # headings to fly for the next frames (sidestep)
    pending_keys = []                # keys to press at the next frame

    def mailbox():
        return bytes(machine.main[0x300:0x329])

    def press(key):
        machine.press(key, at_cycle=mpu.processorCycles)

    def shot_closing_in():
        """An enemy shot (SPR_SHOT_ENEMY, id 80) within 56 px of the ship, from
        the display list (screen positions, the ship sits at 128,100)."""
        n = machine.main[L("dl_count")]
        base = L("dl_items")
        for i in range(n):
            item = machine.main[base + i * 6:base + i * 6 + 6]
            if item[0] != 80:
                continue
            x = item[1] | (item[2] << 8)
            y = item[3] | (item[4] << 8)
            x = x - 0x10000 if x >= 0x8000 else x
            y = y - 0x10000 if y >= 0x8000 else y
            if abs(x + 2 - 128) <= 56 and abs(y + 2 - 100) <= 56:
                return True
        return False

    while frames < args.frames:
        if args.profile and last_state == 2:
            pc = mpu.pc
            before = mpu.processorCycles
            mpu.step()
            name = routine(pc)
            profile[name] = profile.get(name, 0) + mpu.processorCycles - before
        else:
            mpu.step()
        if mpu.pc != wait:
            continue
        # ---- one frame of work is done ----
        work = mpu.processorCycles - work_start
        bus, machine.video_writes = machine.video_writes, 0
        io, machine.io_accesses = machine.io_accesses, 0
        m = mailbox()
        state = m[4] if m[:4] == b"A13B" else -1
        if state == 2:
            stats.append((work, bus, io))
        if state != last_state:
            print("frame %5d: %-11s work %7d cycles bus %5d io %4d score %d lives %d "
                  "bases %d chips %d" % (
                      frames, ST.get(state, state), work, bus, io,
                      int.from_bytes(m[7:11], "little"), m[12], m[19], m[40]))
            last_state = state
            if state == 2:
                placed = False
                heading = None
        event = m[35] if state >= 0 else 0
        if event and event not in seen_events:
            seen_events.add(event)
            print("frame %5d: event %d" % (frames, event))
            if machine.newvideo & 0x80:
                machine.shr_image().save(out / ("event%d_%05d.png" % (event, frames)))
        # ---- scripted play ----
        if state == 1 and not started and frames > 30:
            press("\r")
            started = True
        if state == 2:
            n = machine.main[L("base_count")]
            base_state = L("base_state")
            alive = [b for b in range(n) if machine.main[base_state + b] == 1]
            if len(alive) > 1:
                for b in range(1, n):
                    machine.main[base_state + b] = 0
                alive = [0]
                cheated = True
                print("frame %5d: cheat, only base 0 alive" % frames)
            if alive:
                b = alive[0]
                bx, by = word(machine, L("base_x") + 2 * b), word(machine, L("base_y") + 2 * b)
                hz = machine.main[L("base_hz") + b]
                # along the base's axis: east of a horizontal base (heading 6
                # attacks, 2 retreats), south of a vertical one (0 and 4)
                toward, away = (6, 2) if hz else (0, 4)
                if not placed:
                    px, py = ((bx + 160) % 1024, by) if hz else (bx, (by + 160) % 1792)
                    machine.main[L("player_x")] = px & 0xFF
                    machine.main[L("player_x") + 1] = px >> 8
                    machine.main[L("player_y")] = py & 0xFF
                    machine.main[L("player_y") + 1] = py >> 8
                    machine.main[L("player_h")] = toward
                    placed = True
                    heading = toward
                else:
                    if hz:
                        d = wrap(word(machine, L("player_x")) - bx, 1024)
                    else:
                        d = wrap(word(machine, L("player_y")) - by, 1792)
                    # run in firing (the axis cannon goes first, then the
                    # core), back out before touching the cannons; a cannon
                    # shot that comes close is dodged with a diagonal
                    # sidestep of 10 frames (15 px), held for 10 frames while
                    # the shot passes, then 10 frames back onto the axis
                    want = heading
                    if dodge:
                        want = dodge.pop(0)
                    elif d < 60:
                        want = away
                    elif shot_closing_in() and heading == toward:
                        dodge = [(toward + 1) & 7] * 10 + [toward] * 10 + [(toward - 1) & 7] * 10
                        want = dodge.pop(0)
                    elif d > 126 or heading != toward:
                        want = toward
                    if want != heading:
                        press(KEY_FOR_HEADING[want])
                        heading = want
                    if heading == toward and d <= 130 and frames >= fire_due:
                        press(" ")
                        fire_due = frames + 8
        if frames % 300 == 0 and machine.newvideo & 0x80:
            machine.shr_image().save(out / ("play_%05d.png" % frames))
        frames += 1
        # ---- skip the idle wait: continue at the next line 0 ----
        cycles = mpu.processorCycles
        mpu.processorCycles = (cycles // machine.frame_cycles + 1) * machine.frame_cycles
        low = machine[0x100 + ((mpu.sp + 1) & 0xFF)]
        high = machine[0x100 + ((mpu.sp + 2) & 0xFF)]
        mpu.sp = (mpu.sp + 2) & 0xFF
        mpu.pc = ((high << 8) | low) + 1
        work_start = mpu.processorCycles

    m = mailbox()
    print("stopped after %d frames: state %s score %d round %d events %s" % (
        frames, ST.get(m[4], m[4]), int.from_bytes(m[7:11], "little"), m[11],
        sorted(seen_events)))
    if not stats:
        print("no play frames measured")
        return 1
    works = sorted(w for w, _, _ in stats)
    buses = sorted(b for _, b, _ in stats)
    ios = sorted(i for _, _, i in stats)
    pct = lambda xs, p: xs[min(len(xs) - 1, len(xs) * p // 100)]  # noqa: E731
    print("play frames %d at a modelled %d MHz (frame = %d CPU cycles, bus budget %d bytes)" % (
        len(stats), args.speed, budget, BUS_BUDGET))
    print("CPU work per frame (cycles): median %d, 99%% %d, max %d" % (
        works[len(works) // 2], pct(works, 99), works[-1]))
    print("bytes on the 1 MHz bus per frame: median %d, 99%% %d, max %d" % (
        buses[len(buses) // 2], pct(buses, 99), buses[-1]))
    print("$Cxxx accesses per frame: median %d, 99%% %d, max %d" % (
        ios[len(ios) // 2], pct(ios, 99), ios[-1]))
    if args.profile and profile:
        total = sum(profile.values())
        print("profile over %d play frames (own cycles, top 30):" % len(stats))
        for name, cycles in sorted(profile.items(), key=lambda kv: -kv[1])[:30]:
            print("  %-28s %10d  %5.1f%%  %8d/frame" % (
                name, cycles, 100.0 * cycles / total, cycles // max(1, len(stats))))
    if args.turbo:
        late = sum(1 for w, _, _ in stats if w > budget)
        print("frames over the 60 Hz budget (CPU only, TURBO): %d of %d" % (late, len(stats)))
    else:
        late = sum(1 for w, b, _ in stats if w > budget or b > BUS_BUDGET)
        print("frames over the 60 Hz budget (CPU or bus): %d of %d" % (late, len(stats)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
