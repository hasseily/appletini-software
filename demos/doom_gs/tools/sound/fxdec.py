#!/usr/bin/env python3
"""The third, small decoder of the effect scripts (S4): a script's bytes
to its per-tick (tone period, attenuation, noise period) states, and the
bank file SFX.1 to its directory, volume table and scripts.

Usage:  python3 tools/sound/fxdec.py SFX.1 [NUMBER]

Written apart from fxconv.py (the encoder) and fxmodel.py (the model),
from the format alone (tools/sound/fxconv.py's docstring, version 1):
a 4-byte header (version, flags, u16 length of the steps), then $00-$3F
wait 1-64 ticks, $40-$4F set (bit 0 a u16 tone period, bit 1 the
attenuation, bit 2 the noise period follow in that order; bit 3: one wait
follows and then the script ends), $FF the end. A voice starts at
(0, 80, 0).
"""

import sys


class DecodeError(ValueError):
    pass


def decode(script):
    """(flags, [per-tick states]) of one script; strict."""
    if len(script) < 4:
        raise DecodeError('no header')
    version, flags, size = script[0], script[1], script[2] | script[3] << 8
    if version != 1:
        raise DecodeError('version %d' % version)
    if flags & ~3:
        raise DecodeError('flags $%02X' % flags)
    if len(script) != 4 + size:
        raise DecodeError('%d step bytes, the header says %d'
                          % (len(script) - 4, size))
    state = [0, 80, 0]
    ticks = []
    pc = 4
    last = False
    while True:
        if pc >= len(script):
            raise DecodeError('no end')
        op = script[pc]
        pc += 1
        if op <= 0x3F:
            ticks.extend([tuple(state)] * (op + 1))
            if last:
                break
        elif 0x40 <= op <= 0x4F:
            if last:
                raise DecodeError('a set after an ending set')
            if op & 1:
                state[0] = script[pc] | script[pc + 1] << 8
                pc += 2
                if state[0] > 4095:
                    raise DecodeError('period %d' % state[0])
            if op & 2:
                state[1] = script[pc]
                pc += 1
                if state[1] > 80:
                    raise DecodeError('attenuation %d' % state[1])
            if op & 4:
                state[2] = script[pc]
                pc += 1
                if state[2] > 31:
                    raise DecodeError('noise %d' % state[2])
            last = bool(op & 8)
        elif op == 0xFF:
            if last:
                raise DecodeError('$FF after an ending set')
            break
        else:
            raise DecodeError('opcode $%02X at %d' % (op, pc - 1))
    if pc != len(script):
        raise DecodeError('%d bytes after the end' % (len(script) - pc))
    if flags & 2 and not any(s[2] for s in ticks):
        raise DecodeError('the noise flag without noise')
    if not flags & 2 and any(s[2] for s in ticks):
        raise DecodeError('noise without the noise flag')
    return flags, ticks


def read_bank(data, count=52, base=0x0200):
    """(directory [(address, length)], VATT bytes, [script bytes])."""
    directory = []
    for i in range(count):
        e = data[4 * i:4 * i + 4]
        directory.append((e[0] | e[1] << 8, e[2] | e[3] << 8))
    vatt = data[4 * count:4 * count + 128]
    scripts = []
    for address, length in directory:
        off = address - base
        if off < 4 * count + 128 or off + length > len(data):
            raise DecodeError('entry at $%04X outside the file' % address)
        scripts.append(bytes(data[off:off + length]))
    return directory, bytes(vatt), scripts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0], 'rb') as f:
        data = f.read()
    directory, _, scripts = read_bank(data)
    which = [int(argv[1])] if len(argv) > 1 else range(1, len(scripts) + 1)
    for n in which:
        flags, ticks = decode(scripts[n - 1])
        print('%d: $%04X %d B flags %d, %d ticks'
              % (n, directory[n - 1][0], directory[n - 1][1], flags,
                 len(ticks)))
        if len(argv) > 1:
            for t, s in enumerate(ticks):
                print(t, *s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
