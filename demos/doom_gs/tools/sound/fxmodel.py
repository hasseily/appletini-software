#!/usr/bin/env python3
"""The second model of the effects (S4): what each 140 Hz tick of each
effect script must hold, computed apart from tools/sound/fxconv.py.

Usage:  python3 tools/sound/fxmodel.py [--wad FILE] [--tune FILE]
                                       [--states NAME] [--render DIR]

--states NAME prints the per-tick (tone period, attenuation, noise
period) of one effect (NAME.tuned for its tuned script); --render DIR
writes, for every effect, the model's AY register log of its script on
chip 3, voice A, at full volume on PAL (DIR/NAME.ay), and its WAV render
by tools/sound/ayrender.py with the Doom profile's pans (DIR/NAME.wav:
voice A is pan 5, left 16/16, right 10/16; the ten tuned ones also
DIR/NAME.tuned.ay and .wav). DIR is normally build/sound/fx.

This file shares no code with fxconv.py or mus.py: it reads the WAD
directory, the DS and DP lumps, the list of game sounds (upstream's
offsets.inc, CONST_SFX_*) and tools/sound/fxtune.txt with readers of its
own, and applies the rules of tools/sound/README.md "Effects (S4)", as
docs/m11-parts/fxconv.md settles them, by code of its own: the level by
comparing each tick's mean square with a threshold table rather than by
a logarithm, the rounding with exact fractions, the ring budget by
counting the bytes a script would take rather than by building it. The
test (tests/test_m11_fxconv.py) requires fxdec.py's decoding of every
script fxconv.py writes to equal these states, tick by tick.

The rules, briefly: a tick is 11,025 / 140 samples (the DS rate over
140), the DS without DMX's 16 padding bytes a side; the tone is the DP
byte's PC speaker divisor (Chocolate Doom's published table) as an AY
period at 2,031,250 Hz; the attenuation the RMS in half dB below a
full-scale sine, 0-80; the noise on above 2,500 zero crossings a second,
its period from the crossing rate; the length the longer lump trimmed
after the last tick within 20 dB of the loudest; then the first of the
quantization stages that keeps every 300 ms within 128 bytes, with
the noise also on in a tick left without a tone (the DS's sound past the
DP's tones); a tick at attenuation 80 or with neither tone nor noise is
(0, 80, 0), and the silent ticks at the end dropped.

The AY log (for the renders) is the player's composition as the README
describes it, simplified to one voice: the interrupt runs the music's
tempo (2 + 52,135/65,536 ticks a PAL interrupt), and writes R0-R1, R6,
R7 and R8 of chip 3 when they change, R8 = LEVEL[attenuation] (the
music's level table, tools/sound/tables.py; it is the player's table, not
part of the model's states).
"""

import argparse
import struct
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WAD_FILE = ROOT / 'build' / 'upstream' / 'data' / 'DOOM1.WAD'
OFFSETS_INC = ROOT / 'build' / 'upstream' / 'src' / 'iigs' / 'offsets.inc'
TUNE_FILE = HERE / 'fxtune.txt'

SILENT = 80
TICKS_A_SECOND = 140
CLOCK = 1015625 * 2              # the PAL //e bus clock, doubled in native
TIMER = 1193181                  # the PC's PIT input clock
STEPS_RING = 128
STEPS_WINDOW = 42
TUNED_TEN = frozenset(('BGACT', 'PISTOL', 'POSACT', 'SHOTGN', 'PLPAIN',
                       'FIRSHT', 'FIRXPL', 'STNMOV', 'POPAIN', 'BGSIT2'))

# PC speaker divisors by tone byte (src/i_pcsound.c of Chocolate Doom,
# its `divisors[]`), written here as rows of eight from tone 1.
_PC_ROWS = """
6818 6628 6449 6279 6087 5906 5736 5575 5423 5279 5120 4971 4830 4697
4554 4435 4307 4186 4058 3950 3836 3728 3615 3519 3418 3323 3224 3131
3043 2960 2875 2794 2711 2633 2560 2485 2415 2348 2281 2213 2153 2089
2032 1975 1918 1864 1810 1757 1709 1659 1612 1565 1521 1478 1435 1395
1355 1316 1280 1242 1207 1173 1140 1107 1075 1045 1015 986 959 931 905
879 854 829 806 783 760 739 718 697 677 658 640 621 604 586 570 553 538
522 507 493 479 465 452 439 427 415 403 391 380 369 359 348 339 329 319
310 302 293 285 276 269 261 253 246 239 232 226 219 213 207 201 195 190
184 179
"""
PC_DIVISOR = {i + 1: int(w) for i, w in enumerate(_PC_ROWS.split())}

# (attenuation step under which a change is ignored, the least ticks a
# tone is held, noise period step under which a change is ignored).
QUANT = ((0, 1, 0), (3, 1, 1), (3, 2, 2), (6, 2, 2), (6, 2, 4), (10, 2, 4),
         (10, 3, 6), (16, 3, 8), (16, 4, 12), (24, 4, 16), (24, 6, 31))

# A tick of mean square ms has attenuation a when it lies between
# LEVEL_EDGE[a - 1] and LEVEL_EDGE[a]: the edges are the half-way points
# a + 1/2 half-dB units below 8,192 (a full-scale sine's mean square).
LEVEL_EDGE = tuple(8192.0 * 10.0 ** (-(a + 0.5) / 20.0) for a in range(80))


class ModelError(ValueError):
    pass


def read_wad(path=WAD_FILE):
    """{lump name: bytes}, the first of each name."""
    blob = Path(path).read_bytes()
    magic, count, where = struct.unpack('<4sll', blob[:12])
    if magic not in (b'IWAD', b'PWAD'):
        raise ModelError('%s is not a WAD' % path)
    lumps = {}
    for k in range(count):
        pos, size, raw = struct.unpack('<ll8s',
                                       blob[where + 16 * k:where + 16 * k + 16])
        key = raw.rstrip(b'\0').split(b'\0')[0].decode('latin-1')
        lumps.setdefault(key, blob[pos:pos + size])
    return lumps


def game_sounds(path=OFFSETS_INC):
    """[(number, name)] of CONST_SFX_* but NONE, by number."""
    out = []
    for line in Path(path).read_text().splitlines():
        words = line.split()
        if (len(words) == 3 and words[0].startswith('CONST_SFX_')
                and words[1] == '.equ'):
            name = words[0][len('CONST_SFX_'):]
            if name != 'NONE':
                out.append((int(words[2], 0), name))
    out.sort()
    if [n for n, _ in out] != list(range(1, len(out) + 1)):
        raise ModelError('the CONST_SFX_ numbers are not 1..%d' % len(out))
    return out


def digital(lump):
    fmt, rate, count = struct.unpack('<HHL', lump[:8])
    if fmt != 3 or count > len(lump) - 8 or count < 33:
        raise ModelError('a bad DS lump')
    body = lump[8:8 + count]
    return rate, body[16:len(body) - 16]


def speaker(lump):
    zero, count = struct.unpack('<HH', lump[:4])
    if zero != 0 or count > len(lump) - 4:
        raise ModelError('a bad DP lump')
    return list(lump[4:4 + count])


def half_up(q):
    """round(q) for a Fraction q >= 0, halves up."""
    return int((q * 2 + 1) // 2)


def period_of(tone):
    div = PC_DIVISOR.get(tone, 0)
    if not div:
        return 0
    hz = Fraction(TIMER, div)
    return max(1, min(4095, half_up(Fraction(CLOCK) / (16 * hz))))


def attenuation_of(sq_sum, n):
    if n == 0:
        return SILENT
    ms = sq_sum / n
    return sum(1 for edge in LEVEL_EDGE if ms <= edge)


def tick_bounds(t, rate):
    lo = Fraction(t * rate, TICKS_A_SECOND)
    hi = Fraction((t + 1) * rate, TICKS_A_SECOND)
    return int(lo), int(hi)          # floors, both >= 0


def wanted_states(ds, dp):
    rate, pcm = digital(ds)
    tones = speaker(dp)
    n_ds = len(pcm) * TICKS_A_SECOND
    ds_ticks = n_ds // rate + (1 if n_ds % rate else 0)
    ticks = max(ds_ticks, len(tones))
    out = []
    for t in range(ticks):
        lo, hi = tick_bounds(t, rate)
        seg = [v - 128 for v in pcm[lo:hi]]
        n = len(seg)
        att = attenuation_of(sum(v * v for v in seg), n)
        flips = sum(1 for k in range(1, n) if (seg[k] < 0) != (seg[k - 1] < 0))
        hiss = n > 0 and Fraction(flips * rate, n) > 2500
        colour = 31
        if flips:
            colour = max(1, min(31, half_up(Fraction(CLOCK * n,
                                                     32 * flips * rate))))
        out.append((period_of(tones[t]) if t < len(tones) else 0, att,
                    colour, hiss))
    top = min(r[1] for r in out)
    if top == SILENT:
        raise ModelError('a silent effect')
    keep = [t for t, r in enumerate(out) if r[1] - top < 40]
    return out[:keep[-1] + 1]


def apply_stage(raw, stage):
    att_step, hold, noise_step = stage
    tone, att, noise = 0, SILENT, 0
    since = hold
    out = []
    for p, a, colour, hiss in raw:
        if p != tone and since >= hold:
            tone, since = p, 0
        since += 1
        if a != att:
            if SILENT in (a, att) or abs(a - att) >= att_step:
                att = a
        z = colour if (hiss or not tone) else 0
        if z != noise:
            if 0 in (z, noise) or abs(z - noise) >= noise_step:
                noise = z
        silent = att == SILENT or (tone, noise) == (0, 0)
        out.append((0, SILENT, 0) if silent else (tone, att, noise))
    end = len(out)
    while end and out[end - 1] == (0, SILENT, 0):
        end -= 1
    return out[:end]


def bytes_by_tick(states):
    """The bytes the player reads at each tick 0..len(states) of a script
    of these states (README's format, fxconv.py's encoding rules)."""
    cost = [0] * (len(states) + 1)
    cost[0] += 4                                 # the header
    before = (0, SILENT, 0)
    t = 0
    flagged_end = False
    while t < len(states):
        here = states[t]
        run = 1
        while t + run < len(states) and states[t + run] == here:
            run += 1
        if here != before:
            cost[t] += (1 + (2 if here[0] != before[0] else 0)
                        + (here[1] != before[1]) + (here[2] != before[2]))
            flagged_end = t + run == len(states) and run <= 64
        for k in range(0, run, 64):
            cost[t + k] += 1                     # a wait byte
        before = here
        t += run
    if not flagged_end:
        cost[len(states)] += 1                   # $FF
    return cost


def budget_ok(states):
    cost = bytes_by_tick(states)
    run = sum(cost[:STEPS_WINDOW])
    if run > STEPS_RING:
        return False
    for w in range(1, len(cost)):
        run += (cost[w + STEPS_WINDOW - 1] if w + STEPS_WINDOW - 1 < len(cost)
                else 0) - cost[w - 1]
        if run > STEPS_RING:
            return False
    return True


def auto_states(ds, dp):
    """(stage index, per-tick states) of an automatic script."""
    raw = wanted_states(ds, dp)
    for k, stage in enumerate(QUANT):
        got = apply_stage(raw, stage)
        if budget_ok(got):
            return k, got
    raise ModelError('no stage fits the ring')


def tune_states(path=TUNE_FILE):
    """{name: per-tick states} from fxtune.txt, read here apart."""
    out = {}
    current = None
    for raw in Path(path).read_text().splitlines():
        text = raw.partition('#')[0].strip()
        if not text:
            continue
        if current is None:
            current = text
            ticks = []
            p, a, z = 0, SILENT, 0
        elif text == 'end':
            out[current] = ticks
            current = None
        else:
            parts = text.split()
            for item in parts[1:]:
                key, value = item.split('=')
                q = Fraction(value)
                if key == 'tone':
                    p = 0 if q == 0 else half_up(Fraction(CLOCK) / (16 * q))
                elif key == 'period':
                    p = int(q)
                elif key == 'att':
                    a = int(q * 2)
                elif key == 'noise':
                    z = int(q)
                else:
                    raise ModelError('unknown field %s' % key)
            ticks += [(p, a, z)] * int(parts[0])
    return out


class Model:
    """Every game sound's states: .auto[name] = (stage, states),
    .tuned[name] = states, .names = [names by number]."""

    def __init__(self, wad=WAD_FILE, offsets=OFFSETS_INC, tune=TUNE_FILE):
        lumps = read_wad(wad)
        self.names = [name for _, name in game_sounds(offsets)]
        self.auto = {n: auto_states(lumps['DS' + n], lumps['DP' + n])
                     for n in self.names}
        self.tuned = tune_states(tune) if tune else {}


# ---------------------------------------------------------------------------
# The AY log of one script, for the renders
# ---------------------------------------------------------------------------

PAL_VBL = 312 * 65
TEMPO_WHOLE, TEMPO_FRAC = 2, 52135            # 140 Hz over PAL's 50.08 Hz


def ay_log(states, level_table, tail_interrupts=10):
    """[(bus cycle, chip, register, value)] of the states on chip 3,
    voice A: the voice starts at interrupt 0 with tick 0; each interrupt
    after runs TEMPO_WHOLE ticks plus the carry of the fraction."""
    writes = [(0, 3, 7, 0x3F), (0, 3, 8, 0), (0, 3, 9, 0), (0, 3, 10, 0)]
    shadow = {7: 0x3F, 8: 0}
    tick = 0
    frac = 0
    irq = 0
    while True:
        if tick < len(states):
            p, a, z = states[tick]
            regs = {0: p & 0xFF, 1: p >> 8,
                    7: 0x3F & ~((1 if p else 0) | (8 if z else 0)),
                    8: level_table[a]}
            if z:
                regs[6] = z
        else:
            regs = {8: 0, 7: 0x3F}
        cycle = irq * PAL_VBL + 100
        for reg in sorted(regs):
            if shadow.get(reg) != regs[reg]:
                writes.append((cycle, 3, reg, regs[reg]))
                shadow[reg] = regs[reg]
        if tick >= len(states):
            tail_interrupts -= 1
            if tail_interrupts < 0:
                return writes
        frac += TEMPO_FRAC
        tick += TEMPO_WHOLE + (frac >> 16)
        frac &= 0xFFFF
        irq += 1


def render(states, ay_path, wav_path):
    sys.path.insert(0, str(HERE.parent))
    from sound import ayrender, tables
    writes = ay_log(states, tables.LEVEL)
    with open(ay_path, 'w') as f:
        f.write('# bus_hz %d psg_multiplier 2\n' % tables.PAL_NATIVE.bus_hz)
        for w in writes:
            f.write('%d %d %d %d\n' % w)
    seconds = writes[-1][0] / tables.PAL_NATIVE.bus_hz + 0.05
    result = ayrender.render(writes, tables.PAL_NATIVE.bus_hz, 2, seconds,
                             pans=ayrender.DOOM_PANS)
    return ayrender.write_wav(wav_path, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wad', default=str(WAD_FILE))
    parser.add_argument('--tune', default=str(TUNE_FILE))
    parser.add_argument('--states')
    parser.add_argument('--render')
    parser.add_argument('--manifest',
                        help='with --render: write the paths made, a line '
                             'each')
    args = parser.parse_args(argv)
    model = Model(args.wad, OFFSETS_INC, args.tune)
    if args.states:
        name, _, kind = args.states.partition('.')
        states = model.tuned[name] if kind else model.auto[name][1]
        for t, s in enumerate(states):
            print(t, *s)
    if args.render:
        out = Path(args.render)
        out.mkdir(parents=True, exist_ok=True)
        made = []
        for name in model.names:
            jobs = [(name, model.auto[name][1])]
            if name in model.tuned:
                jobs.append((name + '.tuned', model.tuned[name]))
            for stem, states in jobs:
                peak = render(states, out / (stem + '.ay'),
                              out / (stem + '.wav'))
                made += [out / (stem + '.ay'), out / (stem + '.wav')]
                print('%s: %d ticks, peak %d' % (stem, len(states), peak))
        if args.manifest:
            Path(args.manifest).write_text(
                ''.join('%s\n' % p.resolve() for p in made))
    return 0


if __name__ == '__main__':
    sys.exit(main())
