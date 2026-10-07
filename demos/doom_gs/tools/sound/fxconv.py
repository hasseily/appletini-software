#!/usr/bin/env python3
"""The effects converter (S4): DOOM's sound effects to AY scripts for
chip 3 of the Phasor, and the bank file SFX.1 (RamWorks bank 103).

Usage:  python3 tools/sound/fxconv.py [--wad FILE] [--tune FILE]
                                      [--out DIR]

Writes DIR/SFX.1 (the bank file, the tuned scripts in place of the
automatic ones) and DIR/SFX.lst (the listing: each effect's lengths,
quantization stage, bytes and worst 42-tick window). DIR is
build/native/m11/fxconv by default.

The design is tools/sound/README.md, "Effects (S4)". Written from the
published WAD and DMX lump layouts; no code of upstream's.

Sources (all numbers little endian):

  DS lump  u16 3, u16 sample rate, u32 count, count unsigned 8-bit
           samples; the first and the last 16 are padding that DMX skips
           (Chocolate Doom, src/i_sdlsound.c, CacheSFX), so are they here
  DP lump  u16 0, u16 count, count tone bytes, one a 140 Hz tick: 0 (or
           128 and up) silent, else an index into the PC speaker's PIT
           divisor table (DIVISORS below)

One script a game sound, sfxenum_t order (CONST_SFX_PISTOL .. GETPOW):

  per 140 Hz tick t, the DS samples [t*rate//140, (t+1)*rate//140):
  tone   the DP byte's divisor D: AY period round(PSG * D / (16 * PIT)),
         PSG = 2,031,250 Hz (PAL native), PIT = 1,193,181 Hz; 0 none
  level  the samples' RMS r (sample - 128): attenuation
         round(-40 log10(r / sqrt(8192))) half-dB units (a full-scale
         sine is 0), clamped 0-80; 80 when r is 0 or the DS has ended
  noise  c zero crossings (a crossing: two neighbouring samples of the
         tick on either side of 128) in n samples: the tick hisses when
         c * rate > 2500 * n (2,500 a second); its noise period is
         round(PSG * n / (32 * c * rate)) clamped 1-31, 31 if c is 0. The
         noise is on in a tick that hisses or has no tone (after the
         quantization below): the DS's sound past the DP's tones (the
         decay of a shot, an explosion) is heard as noise
  length the longer of the two lumps in ticks, then the tail after the
         last tick within 40 units (20 dB) of the effect's loudest tick
         cut off

  quantized for the ring (stage k of STAGES = (L, H, N), the first that
  holds the budget): tick by tick from the state (tone 0, att 80, noise
  0), an attenuation change under L half-dB units is dropped unless it is
  from or to 80; a tone change is dropped while the current tone has been
  held under H ticks; a noise period change under N is dropped unless it
  turns the noise on or off. A tick left at attenuation 80, or with
  neither tone nor noise, is (0, 80, 0) (a channel with both off would
  hold its level as a constant, a click, not a sound); the rules go on
  from the state before that. The silent ticks at the end are dropped. The budget: the bytes read in any 42
  consecutive ticks (300 ms) at most 128 (the ring), the header counted at
  tick 0 and the end at the tick after the last.

The script (version 1):

  header   4 B: 1; flags (bit 0 tuned, bit 1 uses noise); u16 the length
           of the steps that follow
  $00-$3F  wait 1-64 ticks
  $40-$4F  set: bit 0 a u16 tone period follows (0 tone off), bit 1 the
           attenuation (1 B, 0-80), bit 2 the noise period (1 B, 0 off),
           in that order; bit 3: one wait byte follows the fields and the
           script ends when it expires (no $FF)
  $FF      end: the voice falls silent

  A voice starts in the state (tone 0, attenuation 80, noise 0). Each
  run of equal states is one set (of the fields that changed) and its
  waits; a run whose state equals the one before has no set.

The bank file SFX.1, loaded at $0200 of bank 103 ($0200-$BFFF, 48,640 B):
the directory, 52 entries of (u16 bank address, u16 length of the script
with its header) in sfxenum_t order from $0200; VATT, 128 B, the
attenuation of upstream's volume 0-127 (the music's law, tables.py
ATTENUATION_OF_VALUE); then the scripts.
"""

import argparse
import math
import sys
from fractions import Fraction
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import mus, tables  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'build' / 'native' / 'm11' / 'fxconv'
TUNE_PATH = Path(__file__).resolve().parent / 'fxtune.txt'

# sfxenum_t from 1 [R build/upstream/src/iigs/offsets.inc:448-499].
NAMES = (
    'PISTOL', 'SHOTGN', 'SGCOCK', 'SAWUP', 'SAWIDL', 'SAWFUL', 'SAWHIT',
    'RLAUNC', 'RXPLOD', 'FIRSHT', 'FIRXPL', 'PSTART', 'PSTOP', 'DOROPN',
    'DORCLS', 'STNMOV', 'SWTCHN', 'SWTCHX', 'PLPAIN', 'DMPAIN', 'POPAIN',
    'SLOP', 'ITEMUP', 'WPNUP', 'OOF', 'TELEPT', 'POSIT1', 'POSIT2',
    'POSIT3', 'BGSIT1', 'BGSIT2', 'SGTSIT', 'BRSSIT', 'SGTATK', 'CLAW',
    'PLDETH', 'PDIEHI', 'PODTH1', 'PODTH2', 'PODTH3', 'BGDTH1', 'BGDTH2',
    'SGTDTH', 'BRSDTH', 'POSACT', 'BGACT', 'DMACT', 'NOWAY', 'BAREXP',
    'PUNCH', 'TINK', 'GETPOW')

TICK_HZ = 140
PSG = tables.psg_clock(tables.PAL_NATIVE)          # 2,031,250 Hz
PIT = 1193181                                      # the PC's 8253 input
ATT_SILENT = tables.ATT_MAX                        # 80
TRIM_ATT = 40
NOISE_CROSSINGS = 2500                             # a second
PAD = 16                                           # DMX's padding a side
WINDOW_TICKS = 42                                  # 300 ms
RING = 128
VERSION = 1
FLAG_TUNED = 1
FLAG_NOISE = 2
BANK_BASE = 0x0200
BANK_SIZE = 0xC000 - BANK_BASE                     # 48,640
SFX_BANK = 103

# The PC speaker's divisor of each DP tone byte, as Chocolate Doom's
# src/i_pcsound.c `divisors[]` publishes it (GPL-2+, Simon Howard; its
# comment cites pcspkr10.zip): 0 is silence.
DIVISORS = (
    0,
    6818, 6628, 6449, 6279, 6087, 5906, 5736, 5575,
    5423, 5279, 5120, 4971, 4830, 4697, 4554, 4435,
    4307, 4186, 4058, 3950, 3836, 3728, 3615, 3519,
    3418, 3323, 3224, 3131, 3043, 2960, 2875, 2794,
    2711, 2633, 2560, 2485, 2415, 2348, 2281, 2213,
    2153, 2089, 2032, 1975, 1918, 1864, 1810, 1757,
    1709, 1659, 1612, 1565, 1521, 1478, 1435, 1395,
    1355, 1316, 1280, 1242, 1207, 1173, 1140, 1107,
    1075, 1045, 1015, 986, 959, 931, 905, 879,
    854, 829, 806, 783, 760, 739, 718, 697,
    677, 658, 640, 621, 604, 586, 570, 553,
    538, 522, 507, 493, 479, 465, 452, 439,
    427, 415, 403, 391, 380, 369, 359, 348,
    339, 329, 319, 310, 302, 293, 285, 276,
    269, 261, 253, 246, 239, 232, 226, 219,
    213, 207, 201, 195, 190, 184, 179)

# The quantization stages (L, H, N): the attenuation change dropped under
# L half-dB units, the tone held at least H ticks, the noise period change
# dropped under N. The first is no quantization; then L grows from the
# AY's finest step (1.5 dB at the top of its table, 3 units), H from 2
# (a PC speaker warble, a tone every other tick, becomes a held sweep) and
# N with them. Measured on DOOM1.WAD: every
# effect fits by stage 9, 10,995 B of scripts in all.
STAGES = (
    (0, 1, 0), (3, 1, 1), (3, 2, 2), (6, 2, 2), (6, 2, 4), (10, 2, 4),
    (10, 3, 6), (16, 3, 8), (16, 4, 12), (24, 4, 16), (24, 6, 31))


class FxError(ValueError):
    pass


# ---------------------------------------------------------------------------
# The wanted state of each tick
# ---------------------------------------------------------------------------

def ds_samples(lump, name):
    """(rate, samples) of a DS lump, DMX's padding dropped."""
    if len(lump) < 8 or lump[0] != 3 or lump[1] != 0:
        raise FxError('%s: not a DMX digital sound' % name)
    rate = lump[2] | lump[3] << 8
    count = lump[4] | lump[5] << 8 | lump[6] << 16 | lump[7] << 24
    if count > len(lump) - 8 or count <= 2 * PAD:
        raise FxError('%s: sample count %d out of range' % (name, count))
    return rate, lump[8 + PAD:8 + count - PAD]


def dp_tones(lump, name):
    if len(lump) < 4 or lump[0] or lump[1]:
        raise FxError('%s: not a PC speaker sound' % name)
    count = lump[2] | lump[3] << 8
    if count > len(lump) - 4:
        raise FxError('%s: tone count %d out of range' % (name, count))
    return lump[4:4 + count]


def tone_period(tone):
    """The AY period of a DP tone byte; 0 for silence."""
    if tone >= len(DIVISORS) or DIVISORS[tone] == 0:
        return 0
    d = DIVISORS[tone]
    return min(4095, max(1, (2 * PSG * d + 16 * PIT) // (32 * PIT)))


def attenuation_of_rms(rms):
    if rms <= 0:
        return ATT_SILENT
    att = math.floor(-40.0 * math.log10(rms / math.sqrt(8192.0)) + 0.5)
    return min(ATT_SILENT, max(0, att))


def tick_level(seg):
    """The attenuation of one tick's samples (their RMS)."""
    if not seg:
        return ATT_SILENT
    total = 0
    for s in seg:
        total += (s - 128) * (s - 128)
    return attenuation_of_rms(math.sqrt(total / len(seg)))


def crossings(seg):
    c = 0
    for a, b in zip(seg, seg[1:]):
        if (a >= 128) != (b >= 128):
            c += 1
    return c


def noise_period(c, n, rate):
    if c == 0:
        return 31
    return min(31, max(1, (2 * PSG * n + 32 * c * rate) // (64 * c * rate)))


def wanted(ds, dp, name='?'):
    """The per-tick (tone period, attenuation, noise period, hiss) of an
    effect, trimmed, before the quantization: the noise period is the
    crossing rate's, hiss whether the rate passes 2,500 a second."""
    rate, pcm = ds_samples(ds, 'DS' + name)
    tones = dp_tones(dp, 'DP' + name)
    ds_ticks = -(-len(pcm) * TICK_HZ // rate)
    length = max(ds_ticks, len(tones))
    states = []
    for t in range(length):
        seg = pcm[t * rate // TICK_HZ:(t + 1) * rate // TICK_HZ]
        period = tone_period(tones[t]) if t < len(tones) else 0
        att = tick_level(seg)
        n = len(seg)
        c = crossings(seg)
        states.append((period, att, noise_period(c, n, rate),
                       c * rate > NOISE_CROSSINGS * n))
    loudest = min(s[1] for s in states) if states else ATT_SILENT
    if loudest >= ATT_SILENT:
        raise FxError('%s: silent' % name)
    last = 0
    for t, s in enumerate(states):
        if s[1] < loudest + TRIM_ATT:
            last = t
    return states[:last + 1]


def quantize(states, stage):
    """The per-tick (tone period, attenuation, noise period) after one
    stage of the ring's rules, the silent tail dropped."""
    lmin, hold, nmin = stage
    p, a, z = 0, ATT_SILENT, 0
    held = hold                     # the start state counts as held long
    out = []
    for period, att, colour, hiss in states:
        if period != p and held >= hold:
            p = period
            held = 0
        held += 1
        if att != a and (abs(att - a) >= lmin or att == ATT_SILENT
                         or a == ATT_SILENT):
            a = att
        noise = colour if hiss or p == 0 else 0
        if noise != z and (abs(noise - z) >= nmin or noise == 0 or z == 0):
            z = noise
        if a == ATT_SILENT or (p == 0 and z == 0):
            out.append((0, ATT_SILENT, 0))
        else:
            out.append((p, a, z))
    while out and out[-1] == (0, ATT_SILENT, 0):
        out.pop()
    return out


# ---------------------------------------------------------------------------
# The script
# ---------------------------------------------------------------------------

def encode(states, flags):
    """(script bytes, per-tick bytes read): ticks 0..len(states), the
    header in tick 0's count, the end in the last."""
    if not states:
        raise FxError('an empty script')
    if any(s[2] for s in states):
        flags |= FLAG_NOISE
    runs = []
    for s in states:
        if runs and runs[-1][0] == s:
            runs[-1][1] += 1
        else:
            runs.append([s, 1])
    steps = bytearray()
    per_tick = [0] * (len(states) + 1)
    per_tick[0] = 4
    prev = (0, ATT_SILENT, 0)
    tick = 0
    for i, (s, n) in enumerate(runs):
        last = i == len(runs) - 1
        start = len(steps)
        if s != prev:
            mask = ((s[0] != prev[0]) | (s[1] != prev[1]) << 1
                    | (s[2] != prev[2]) << 2)
            if last and n <= 64:
                mask |= 8
            steps.append(0x40 | mask)
            if mask & 1:
                steps += bytes((s[0] & 0xFF, s[0] >> 8))
            if mask & 2:
                steps.append(s[1])
            if mask & 4:
                steps.append(s[2])
            ended = bool(mask & 8)
        else:
            ended = False
        left = n
        t = tick
        while left:
            k = min(64, left)
            steps.append(k - 1)
            per_tick[t] += len(steps) - start
            start = len(steps)
            t += k
            left -= k
        tick += n
        prev = s
    if not ended:
        steps.append(0xFF)
        per_tick[tick] += 1
    if len(steps) > 0xFFFF:
        raise FxError('a script of %d bytes' % len(steps))
    head = bytes((VERSION, flags, len(steps) & 0xFF, len(steps) >> 8))
    return head + bytes(steps), per_tick


def worst_window(per_tick):
    best = 0
    for w in range(len(per_tick)):
        best = max(best, sum(per_tick[w:w + WINDOW_TICKS]))
    return best


# ---------------------------------------------------------------------------
# The tuned scripts (tools/sound/fxtune.txt)
# ---------------------------------------------------------------------------

def parse_tune(text, where='fxtune.txt'):
    """{name: per-tick states} of the tuned scripts. A block: the
    effect's name alone on a line, then steps "TICKS field=value ...",
    then "end". Fields: tone=HZ or period=N (0 off), att=DB (0-40, in
    0.5 dB steps), noise=N (0-31, 0 off); a field not given keeps its
    value; the state starts at (tone 0, att 40 dB, noise 0). '#' starts
    a comment."""
    out = {}
    name = None
    states = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0].split()
        if not line:
            continue

        def bad(why):
            return FxError('%s:%d: %s' % (where, number, why))
        if name is None:
            if len(line) != 1 or line[0] not in NAMES:
                raise bad('an effect name expected, not %r' % raw.strip())
            if line[0] in out:
                raise bad('%s twice' % line[0])
            name = line[0]
            states = []
            cur = [0, ATT_SILENT, 0]
            continue
        if line == ['end']:
            if not states:
                raise bad('%s has no steps' % name)
            out[name] = states
            name = None
            continue
        try:
            ticks = int(line[0])
        except ValueError:
            raise bad('a tick count expected, not %r' % line[0])
        if ticks < 1:
            raise bad('a step of %d ticks' % ticks)
        for field in line[1:]:
            key, _, value = field.partition('=')
            try:
                v = Fraction(value)
            except (ValueError, ZeroDivisionError):
                raise bad('bad value in %r' % field)
            if key == 'tone':
                if v < 0:
                    raise bad('negative tone')
                cur[0] = 0 if v == 0 else int(Fraction(PSG) / (16 * v)
                                              + Fraction(1, 2))
                if not 0 <= cur[0] <= 4095 or (v and cur[0] == 0):
                    raise bad('tone %s out of the AY range' % value)
            elif key == 'period':
                if v.denominator != 1 or not 0 <= v <= 4095:
                    raise bad('period %s out of range' % value)
                cur[0] = int(v)
            elif key == 'att':
                a = 2 * v
                if a.denominator != 1 or not 0 <= a <= ATT_SILENT:
                    raise bad('att %s: 0-40 dB in 0.5 dB steps' % value)
                cur[1] = int(a)
            elif key == 'noise':
                if v.denominator != 1 or not 0 <= v <= 31:
                    raise bad('noise %s out of range' % value)
                cur[2] = int(v)
            else:
                raise bad('unknown field %r' % key)
        states.extend([tuple(cur)] * ticks)
    if name is not None:
        raise FxError('%s: %s has no end' % (where, name))
    return out


# ---------------------------------------------------------------------------
# All the effects and the bank file
# ---------------------------------------------------------------------------

class Effect:
    def __init__(self, number, name, script, per_tick, ticks, stage, tuned):
        self.number = number            # sfxenum_t
        self.name = name
        self.script = script
        self.per_tick = per_tick
        self.ticks = ticks
        self.stage = stage              # index into STAGES; None if tuned
        self.tuned = tuned
        self.window = worst_window(per_tick)


def convert(wad, name, number, tune=None):
    """One Effect: the tuned script if `tune` has the effect, else the
    automatic one at the first stage that holds the budget."""
    if tune is not None and name in tune:
        states = tune[name]
        script, per_tick = encode(states, FLAG_TUNED)
        effect = Effect(number, name, script, per_tick, len(states), None,
                        True)
        if effect.window > RING:
            raise FxError('%s: the tuned script reads %d bytes in 42 ticks'
                          ' (the ring holds %d)' % (name, effect.window,
                                                    RING))
        return effect
    raw = wanted(wad.lump('DS' + name), wad.lump('DP' + name), name)
    for k, stage in enumerate(STAGES):
        states = quantize(raw, stage)
        script, per_tick = encode(states, 0)
        if worst_window(per_tick) <= RING:
            return Effect(number, name, script, per_tick, len(states), k,
                          False)
    raise FxError('%s: no quantization stage keeps 42 ticks within %d bytes'
                  % (name, RING))


def convert_all(wad, tune=None):
    return [convert(wad, name, i + 1, tune) for i, name in enumerate(NAMES)]


def vatt():
    return bytes(tables.ATTENUATION_OF_VALUE)


def bank_file(effects):
    """SFX.1's bytes (loaded at $0200 of bank 103)."""
    directory = bytearray()
    body = bytearray()
    address = BANK_BASE + 4 * len(effects) + 128
    for e in effects:
        directory += bytes((address & 0xFF, address >> 8,
                            len(e.script) & 0xFF, len(e.script) >> 8))
        body += e.script
        address += len(e.script)
    data = bytes(directory) + vatt() + bytes(body)
    if len(data) > BANK_SIZE:
        raise FxError('SFX.1 is %d bytes; a bank holds %d'
                      % (len(data), BANK_SIZE))
    return data


def listing(effects, data):
    lines = ['# SFX.1: %d effects, %d bytes of %d (bank %d at $%04X)'
             % (len(effects), len(data), BANK_SIZE, SFX_BANK, BANK_BASE),
             '# id name    kind  stage ticks bytes window  address']
    address = BANK_BASE + 4 * len(effects) + 128
    for e in effects:
        lines.append('%4d %-7s %-5s %5s %5d %5d %6d  $%04X'
                     % (e.number, e.name, 'tuned' if e.tuned else 'auto',
                        '-' if e.stage is None else e.stage, e.ticks,
                        len(e.script), e.window, address))
        address += len(e.script)
    return '\n'.join(lines) + '\n'


def load_tune(path=TUNE_PATH):
    return parse_tune(Path(path).read_text(), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wad', default=str(mus.WAD_PATH))
    parser.add_argument('--tune', default=str(TUNE_PATH))
    parser.add_argument('--out', default=str(OUT_DIR))
    args = parser.parse_args(argv)
    wad = mus.Wad.open(args.wad)
    tune = load_tune(args.tune)
    try:
        effects = convert_all(wad, tune)
        data = bank_file(effects)
    except FxError as e:
        print('fxconv: %s' % e, file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'SFX.1').write_bytes(data)
    text = listing(effects, data)
    (out / 'SFX.lst').write_text(text)
    print('%s: %d effects (%d tuned), %d bytes of %d; worst 42-tick window'
          ' %d of %d bytes'
          % (out / 'SFX.1', len(effects), sum(e.tuned for e in effects),
             len(data), BANK_SIZE, max(e.window for e in effects), RING))
    return 0


if __name__ == '__main__':
    sys.exit(main())
