#!/usr/bin/env python3
"""Run the port in the test machine and save SHR frames.

The loader is skipped: the system file and the sprite banks are placed in
memory and the game starts at GAME_ENTRY. Idle time in the VBL wait is
skipped. For each video frame the script reports the CPU cycles of work and
the number of bytes that would use the 1 MHz bus.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a2sim  # noqa: E402
from run_baseline import labels_from  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    parser.add_argument("--rom", required=True)
    parser.add_argument("--keys", default="A\r\r\r\r\r")
    parser.add_argument("--ticks", type=int, default=30)
    parser.add_argument("--save-every", type=int, default=16)
    parser.add_argument("--max-cycles", type=int, default=3_000_000_000)
    parser.add_argument("--speed", type=int, default=33)
    args = parser.parse_args()
    build = Path(args.build)
    labels = labels_from(build / "port/main.lbl")
    machine = a2sim.Machine(args.rom, speed=args.speed)
    machine.load(0x2000, (build / "port/BILESTOAD.SYSTEM").read_bytes())
    banks = (build / "art/sprites.bin").read_bytes()
    size = 0xB000
    for index in range(len(banks) // size):
        machine.load(0x1000, banks[index * size:(index + 1) * size],
                     aux_bank=1 + index)
    mpu = machine.mpu
    mpu.pc = labels["GAME_ENTRY"]
    mpu.sp = 0xFF
    machine.press(args.keys, at_cycle=machine.frame_cycles * 20,
                  gap=machine.frame_cycles * 30)
    wait, switch = labels["wait_frame_start"], labels["SWITCH"]
    out = build / "frames"
    out.mkdir(exist_ok=True)
    ticks = frames = 0
    work_start = mpu.processorCycles
    worst = (0, 0)
    stats = []                  # (work cycles, bus bytes) while SHR is on
    limit = mpu.processorCycles + args.max_cycles
    while mpu.processorCycles < limit and ticks < args.ticks:
        pc = mpu.pc
        if pc == switch:
            ticks += 1
        elif pc == wait:
            work = mpu.processorCycles - work_start
            writes, machine.video_writes = machine.video_writes, 0
            io, machine.io_accesses = machine.io_accesses, 0
            worst = max(worst, (work, writes))
            if machine.newvideo & 0x80 and ticks > 1:
                stats.append((work, writes))
            if frames % args.save_every == 0:
                print("frame %4d tick %3d: work %7d cycles (%.1f ms at %d "
                      "MHz), bus bytes %5d, io %3d" % (
                          frames, ticks, work, work / (1020.5 * args.speed),
                          args.speed, writes, io))
                if machine.newvideo & 0x80:
                    machine.shr_image().save(out / ("shr%04d.png" % frames))
            frames += 1
            # Skip to the next frame start, then return from the wait.
            cycles = mpu.processorCycles
            mpu.processorCycles = (cycles // machine.frame_cycles + 1) * \
                machine.frame_cycles
            low = machine[0x100 + ((mpu.sp + 1) & 0xFF)]
            high = machine[0x100 + ((mpu.sp + 2) & 0xFF)]
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = ((high << 8) | low) + 1
            work_start = mpu.processorCycles
            continue
        mpu.step()
    print("stopped: pc=$%04X ticks=%d frames=%d shr=%s worst work=%d "
          "bus=%d" % (mpu.pc, ticks, frames, bool(machine.newvideo & 0x80),
                      worst[0], worst[1]))
    if stats:
        budget = machine.frame_cycles
        bus_budget = 16000      # posted writes that fit in one 60 Hz frame
        works = sorted(w for w, _ in stats)
        buses = sorted(b for _, b in stats)
        print("SHR frames %d: work median %d, 99%% %d, max %d cycles "
              "(frame = %d); bus median %d, 99%% %d, max %d bytes" % (
                  len(stats), works[len(works) // 2],
                  works[len(works) * 99 // 100], works[-1], budget,
                  buses[len(buses) // 2], buses[len(buses) * 99 // 100],
                  buses[-1]))
        late = sum(1 for w, b in stats if w > budget or b > bus_budget)
        print("frames over the 60 Hz budget (CPU or bus): %d of %d" %
              (late, len(stats)))
    print("phasor mode=%d, AY writes=%d" %
          (machine.phasor.mode, len(machine.phasor.log)))
    if not machine.newvideo & 0x80:
        print(machine.text_screen())


if __name__ == "__main__":
    main()
