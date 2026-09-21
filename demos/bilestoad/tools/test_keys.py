#!/usr/bin/env python3
"""Check the port's key handler in the test machine.

python3 tools/test_keys.py --rom ROM

Runs the port to the first fight, then presses the player 1 command keys
in lower case and in upper case and checks that both set the command
bits in PDL0 ($16): Q -> 1, then E -> 2 (torso), A -> +4 (shield arm),
Z -> +$10 (axe arm). Upstream PDL took upper case only; a //e sends lower
case unless Caps Lock is down.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a2sim  # noqa: E402
from run_baseline import labels_from  # noqa: E402

PDL0 = 0x16


def command_bits_after(keys, build, rom, speed=33):
    labels = labels_from(build / "port/main.lbl")
    machine = a2sim.Machine(rom, speed=speed)
    machine.load(0x2000, (build / "port/BILESTOAD.SYSTEM").read_bytes())
    banks = (build / "art/sprites.bin").read_bytes()
    size = 0xB000
    for index in range(len(banks) // size):
        machine.load(0x1000, banks[index * size:(index + 1) * size],
                     aux_bank=1 + index)
    mpu = machine.mpu
    mpu.pc = labels["GAME_ENTRY"]
    mpu.sp = 0xFF
    machine.press("A\r\r\r\r\r", at_cycle=machine.frame_cycles * 20,
                  gap=machine.frame_cycles * 30)
    wait, switch = labels["wait_frame_start"], labels["SWITCH"]
    ticks = frames = 0
    sent = False
    seen = []
    limit = mpu.processorCycles + 3_000_000_000
    while mpu.processorCycles < limit and ticks < 14:
        pc = mpu.pc
        if pc == switch:
            ticks += 1
        elif pc == wait:
            frames += 1
            if ticks >= 6 and not sent:
                machine.press(keys, at_cycle=mpu.processorCycles,
                              gap=machine.frame_cycles * 2)
                sent = True
            if sent and frames % 4 == 0:
                seen.append(machine.main[PDL0])
            cycles = mpu.processorCycles
            mpu.processorCycles = (cycles // machine.frame_cycles + 1) * \
                machine.frame_cycles
            low = machine[0x100 + ((mpu.sp + 1) & 0xFF)]
            high = machine[0x100 + ((mpu.sp + 2) & 0xFF)]
            mpu.sp = (mpu.sp + 2) & 0xFF
            mpu.pc = ((high << 8) | low) + 1
            continue
        mpu.step()
    if not machine.newvideo & 0x80:
        raise SystemExit("the game did not reach SHR mode")
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--build", default="build")
    parser.add_argument("--rom", required=True)
    args = parser.parse_args()
    build = Path(args.build)
    failed = 0
    for keys in ("qeaz", "QEAZ"):
        seen = command_bits_after(keys, build, args.rom)
        distinct = []
        for value in seen:
            if not distinct or distinct[-1] != value:
                distinct.append(value)
        # Q sets torso bit 1, E replaces it with 2, A adds 4, Z adds $10:
        # the value ends at 22 and passed through 1 (a sample every fourth
        # frame can miss the short-lived 2 and 6)
        ok = bool(distinct) and distinct[-1] == 22 and 1 in distinct
        print("%-9s PDL0 values %s -> %s" % (repr(keys), distinct,
                                             "ok" if ok else "FAIL"))
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
