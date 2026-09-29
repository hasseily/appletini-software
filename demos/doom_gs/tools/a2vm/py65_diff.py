#!/usr/bin/env python3
"""Compare a2vm's compatibility core (py65core.h) with py65 itself.

Usage (with the Python of build/venv, which has py65):

    build/venv/bin/python tools/a2vm/py65_diff.py [--py65check PATH]
        [--cases N] [--runs N] [--steps N] [--seed N]

Random cases run on py65's 65C02 (the core of the existing port's model,
demos/doom/tools/a2sim.py) and on build/a2vm/py65check, the same core as
a2vm's, on a flat 64 KB memory. Each case compares the registers, the
cycle count, the waiting flag and every memory access, in order, with its
address and value.

  - `--cases` single steps of each of the 256 opcodes, from random
    registers and memory;
  - `--runs` runs of `--steps` steps through random memory, a third of
    them with an IRQ pending (delivered with I clear, then D cleared, as
    a2sim.Machine does).

Memory is filled from one of a few seeds by a formula both sides compute
(xorshift32), then changed where the case says. A case
where py65 would index past $FFFF (py65 does not wrap its word reads) is
left out and counted. This is a comparison tool: it needs py65, which the
port's own tools never import.
"""

import argparse
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECK = ROOT / 'build' / 'a2vm' / 'py65check'


class Beyond(Exception):
    """py65 indexed past the end of memory."""


class Memory:
    """A flat memory that logs every access as py65check does."""

    def __init__(self, fill):
        self.ram = fill
        self.log = []

    def __getitem__(self, address):
        if not 0 <= address <= 0xffff:
            raise Beyond(address)
        value = self.ram[address]
        self.log.append('r%04X:%02X' % (address, value))
        return value

    def __setitem__(self, address, value):
        if not 0 <= address <= 0xffff:
            raise Beyond(address)
        value &= 0xff
        self.log.append('w%04X:%02X' % (address, value))
        self.ram[address] = value


_fills = {}


def fill(seed):
    """The memory of a seed, as py65check's fill: xorshift32, one step a
    byte."""
    if seed not in _fills:
        state = seed or 1
        out = bytearray(0x10000)
        for i in range(0x10000):
            state ^= (state << 13) & 0xffffffff
            state ^= state >> 17
            state ^= (state << 5) & 0xffffffff
            out[i] = state & 0xff
        _fills[seed] = bytes(out)
    return _fills[seed]


def memory_of(case):
    ram = bytearray(fill(case[8]))
    for address, value in case[9].items():
        ram[address] = value
    return ram


def run_py65(case):
    from py65.devices.mpu65c02 import MPU
    pc, a, x, y, sp, p, steps, irq = case[:8]
    memory = Memory(memory_of(case))
    mpu = MPU(memory=memory, pc=0)
    memory.log.clear()
    mpu.pc, mpu.a, mpu.x, mpu.y, mpu.sp, mpu.p = pc, a, x, y, sp, p
    mpu.processorCycles = 0
    for _ in range(steps):
        if irq and not mpu.p & mpu.INTERRUPT:
            mpu.waiting = False
            mpu.irq()
            mpu.p &= ~mpu.DECIMAL & 0xff
        mpu.step()
    head = '%04X %02X %02X %02X %02X %02X %d %d' % (
        mpu.pc, mpu.a, mpu.x, mpu.y, mpu.sp, mpu.p, mpu.processorCycles,
        int(mpu.waiting))
    return ' '.join([head] + memory.log)


def encode(case):
    head = '%X %X %X %X %X %X %X %X %X' % case[:9]
    body = ' '.join('%X=%X' % item for item in sorted(case[9].items()))
    return head + ' ' + body


SEEDS = 8           # memory fills, shared by the cases


def cases(rng, singles, runs, steps):
    seeds = [rng.getrandbits(32) | 1 for _ in range(SEEDS)]
    for opcode in range(256):
        for _ in range(singles):
            seed = rng.choice(seeds)
            pc = rng.randrange(0x0200, 0xfff0)
            # a random zero page, so pointers differ from case to case
            changes = {address: rng.getrandbits(8) for address in range(256)}
            changes[pc] = opcode
            changes[pc + 1] = rng.getrandbits(8)
            changes[pc + 2] = rng.getrandbits(8)
            yield (pc, rng.getrandbits(8), rng.getrandbits(8),
                   rng.getrandbits(8), rng.getrandbits(8), rng.getrandbits(8),
                   1, 0, seed, changes)
    for number in range(runs):
        yield (rng.randrange(0x0200, 0xff00), rng.getrandbits(8),
               rng.getrandbits(8), rng.getrandbits(8), rng.getrandbits(8),
               rng.getrandbits(8), steps, int(number % 3 == 0),
               rng.choice(seeds), {})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--py65check', type=Path, default=DEFAULT_CHECK)
    parser.add_argument('--cases', type=int, default=20)
    parser.add_argument('--runs', type=int, default=60)
    parser.add_argument('--steps', type=int, default=200)
    parser.add_argument('--seed', type=int, default=6502)
    arguments = parser.parse_args(argv)
    try:
        import py65  # noqa: F401
    except ImportError:
        print('py65 is not installed: run this with build/venv/bin/python')
        return 2
    rng = random.Random(arguments.seed)
    kept, expected, skipped = [], [], 0
    for case in cases(rng, arguments.cases, arguments.runs, arguments.steps):
        try:
            expected.append(run_py65(case))
        except Beyond:
            skipped += 1
            continue
        kept.append(case)
    text = '\n'.join(encode(case) for case in kept) + '\n'
    result = subprocess.run([str(arguments.py65check)], input=text,
                            stdout=subprocess.PIPE, universal_newlines=True,
                            check=True)
    actual = result.stdout.splitlines()
    failures = 0
    for case, want, got in zip(kept, expected, actual):
        if want != got:
            failures += 1
            if failures <= 5:
                print('case at PC %04X, opcode %02X, %d steps:'
                      % (case[0], memory_of(case)[case[0]], case[6]))
                w, g = want.split(), got.split()
                for i, (a, b) in enumerate(zip(w, g)):
                    if a != b:
                        print('  item %d: py65 %s, a2vm %s' % (i, a, b))
                        break
                else:
                    print('  lengths differ: %d and %d' % (len(w), len(g)))
    if len(actual) != len(kept):
        print('py65check answered %d cases of %d' % (len(actual), len(kept)))
        failures += 1
    accesses = sum(len(line.split()) - 8 for line in expected)
    print('%d cases (%d single steps, %d runs), %d accesses compared: '
          '%d failures; %d cases left out (py65 indexes past $FFFF)'
          % (len(kept), 256 * arguments.cases, arguments.runs, accesses,
             failures, skipped))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
