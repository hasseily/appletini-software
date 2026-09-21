#!/usr/bin/env python3
"""Run the unmodified game in the test machine and save HGR frames.

This validates the LISA-to-ca65 conversion and measures the original cost
of one frame (CPU cycles between two calls of SWITCH).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a2sim  # noqa: E402
import shapedata  # noqa: E402


def labels_from(path):
    table = {}
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "al":
            table[parts[2].lstrip(".")] = int(parts[1], 16)
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream")
    parser.add_argument("--build", default="build/baseline")
    parser.add_argument("--rom", required=True)
    parser.add_argument("--keys", default="")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--max-cycles", type=int, default=40_000_000)
    args = parser.parse_args()
    build = Path(args.build)
    labels = labels_from(build / "game.lbl")
    machine = a2sim.Machine(args.rom, speed=1)
    machine.load(0x0800, (build / "seg0.bin").read_bytes())
    machine.load(0x9100, (build / "seg1.bin").read_bytes())
    memory, _ = shapedata.assemble(args.upstream)
    delta = shapedata.RELOC_DELTA
    machine.load(0x2C00 + delta, memory[0x2C00:0x5C00])
    mpu = machine.mpu
    mpu.pc = 0x0800
    mpu.sp = 0xFF
    machine.press(args.keys, at_cycle=200_000, gap=400_000)
    reloc, switch = labels["RELOC"], labels["SWITCH"]
    note = labels["NOTE"]
    frames, last = 0, None
    limit = mpu.processorCycles + args.max_cycles
    while mpu.processorCycles < limit and frames < args.frames:
        if mpu.pc == reloc:
            # The image is already at its run-time address: do RELOC's
            # variable setup only, then return to the caller.
            machine.main[0xFC] = 0
            machine.main[0xE9], machine.main[0xEA] = note & 0xFF, note >> 8
            low = machine[0x100 + ((mpu.sp + 1) & 0xFF)]
            high = machine[0x100 + ((mpu.sp + 2) & 0xFF)]
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = ((high << 8) | low) + 1
            continue
        if mpu.pc == switch:
            now = mpu.processorCycles
            if last is not None:
                print("frame %2d: %7d cycles, %d speaker toggles" %
                      (frames, now - last, machine.speaker_toggles))
            last = now
            machine.speaker_toggles = 0
            machine.hgr_image().resize((560, 384)).save(
                build / ("frame%02d.png" % frames))
            frames += 1
        mpu.step()
    print("pc=$%04X text=%s" % (mpu.pc, machine.sw["text"]))
    print(machine.text_screen())


if __name__ == "__main__":
    main()
