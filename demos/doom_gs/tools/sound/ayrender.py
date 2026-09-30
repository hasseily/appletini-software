#!/usr/bin/env python3
"""AY register writes to a WAV file, after the Phasor's HDL.

Usage:  python3 tools/sound/ayrender.py LOG OUT.wav [--seconds S] [--mono]

LOG is a register log (player.py --log writes one): a header line
"# bus_hz N psg_multiplier M", then "bus_cycle chip reg value" lines,
the tuple a2vm's planned --ay-log will write (native-sound.md 5.2).

The model follows the YM2149 core of the Appletini (FW/hdl/apple/
YM2149.sv) and the Phasor's mixer (FW/hdl/apple/mockingboard.sv), at the
PSG clock (the bus clock, twice it in native mode):

- tone: a /8 prescaler; the output toggles every P prescaled ticks, so
  f = clock / (16 P). P = 0 holds the output at the mixer's tone bit,
  which silences a channel whose tone is on;
- noise: a 17-bit LFSR, loaded with 1, shifting in bit0 ^ bit2 every NP
  ticks of clock / 16 (NP = 0 counts as 1); the output toggles when
  bit0 ^ bit1 is set; a write to R6 restarts the step counter. These
  taps repeat after 114,681 steps, where a real AY's (bit0 ^ bit3) give
  the maximal 131,071: the card, not the datasheet, is modelled;
- envelope: one step every EP prescaled ticks (EP = 0 counts as 1), 32
  levels, the 16 shapes of R13 with the core's hold and alternate rules;
  a write to R13 restarts it;
- a channel sounds when (tone or tone off) and (noise or noise off); its
  8-bit value is the AY-3-8913 table at its fixed level or envelope level;
- Phasor native mode: each channel is scaled by its pan gain (the menu's
  defaults: 11 and 5 alternating, as config_menu_phasor.c:9-14) for left
  and right, the 12 channels summed, a sum of 2048 or more saturates,
  times 16 to 16 bits; Mockingboard mode sums chips 0 and 2 only.

Rendering: the tone is averaged over each output sample (a box filter:
the fraction of the sample's prescaled ticks the tone is high), noise and
envelope are sampled. A DC blocker at about 3 Hz takes out the card's
unipolar offset. The output is 16-bit PCM at 44,100 Hz, stereo by
default, with a gain of 2 over the card's scale (--gain). Standard
library only.
"""

import argparse
import array
import sys
import wave
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import tables  # noqa: E402

SAMPLE_RATE = 44100
DC_POLE = 0.9995
LISTENING_GAIN = 2.0       # +6 dB over the card's own scale, so that the
                           # renders are not too quiet; one gain for all
                           # songs keeps their relative loudness

# Pan of each (chip, channel), chips numbered as tables.py does. The
# HDL's pan word runs psg0 (VIA-A first AY), psg1 (VIA-B first AY), psg2
# (VIA-A second AY), psg3 (VIA-B second AY); the defaults are 11, 5, 11,
# 5, 11, 5, ... in that order.
_PSG_OF_CHIP = {0: 0, 1: 2, 2: 1, 3: 3}
_DEFAULT_PAN_WORD = (11, 5, 11, 5, 11, 5, 11, 5, 11, 5, 11, 5)
DEFAULT_PANS = {(chip, channel): _DEFAULT_PAN_WORD[3 * psg + channel]
                for chip, psg in _PSG_OF_CHIP.items()
                for channel in range(3)}


def pan_gain_left(pan):
    return {9: 14, 10: 11, 11: 9, 12: 7, 13: 5, 14: 2, 15: 0}.get(pan, 16)


def pan_gain_right(pan):
    return 2 * pan if pan < 8 else 16


def apply_pan_gain(sample, gain):
    """The HDL's shift-and-add scaling of an 8-bit sample by gain / 16."""
    s = sample
    parts = {0: (), 2: (3,), 4: (2,), 5: (2, 4), 6: (2, 3), 7: (2, 3, 4),
             8: (1,), 9: (1, 4), 10: (1, 3), 11: (1, 3, 4), 12: (1, 2),
             14: (1, 2, 3)}
    if gain not in parts:
        return s
    return sum(s >> k for k in parts[gain])


# ---------------------------------------------------------------------------
# Envelope and noise sequences
# ---------------------------------------------------------------------------

def _envelope_sequence(shape, count=128):
    """env_vol after 0, 1, ... steps from a write of `shape` to R13, by the
    core's rules (YM2149.sv:257-342): every step moves the level by one
    unless holding, and the shape bits set or clear the hold from the
    level before the step."""
    cont, attack, alternate, hold = (shape >> 3) & 1, (shape >> 2) & 1, \
        (shape >> 1) & 1, shape & 1
    vol, inc, held = (0, 1, 0) if attack else (31, 0, 0)
    out = [vol]
    for _ in range(count - 1):
        new_vol, new_inc, new_held = vol, inc, held
        if not held:
            new_vol = (vol + (1 if inc else -1)) & 31
        if not cont:
            if not inc:
                if vol == 1:
                    new_held = 1
            elif vol == 31:
                new_held = 1
        elif hold:
            if not inc:
                if alternate:
                    if vol == 0:
                        new_held = 1
                elif vol == 1:
                    new_held = 1
            elif alternate:
                if vol == 31:
                    new_held = 1
            elif vol == 30:
                new_held = 1
        elif alternate:
            if not inc:
                if vol == 1:
                    new_held = 1
                if vol == 0:
                    new_held, new_inc = 0, 1
            else:
                if vol == 30:
                    new_held = 1
                if vol == 31:
                    new_held, new_inc = 0, 0
        vol, inc, held = new_vol, new_inc, new_held
        out.append(vol)
    return out


ENVELOPES = tuple(tuple(_envelope_sequence(s)) for s in range(16))


def envelope_level(shape, step):
    """env_vol `step` steps after the write of R13. Every shape repeats
    with a period of 64 steps (or 32) from step 0, or holds from step 33;
    steps 64-127 of the table cover both cases."""
    if step >= 128:
        step = 64 + (step - 64) % 64
    return ENVELOPES[shape][step]


CORE_TAP = 2       # YM2149.sv:187 shifts in bit0 ^ bit2
AY_TAP = 3         # the AY-3-8910 datasheet's generator: bit0 ^ bit3


def lfsr_step(poly, tap=CORE_TAP):
    return (poly >> 1) | (((poly ^ (poly >> tap)) & 1) << 16)


def _noise_sequence(tap=CORE_TAP):
    """The noise output (~noise_toggle) after 0, 1, ... LFSR steps, over
    its whole period."""
    poly = 1
    toggle = 0
    out = bytearray()
    while True:
        out.append(1 - toggle)
        if (poly ^ (poly >> 1)) & 1:
            toggle ^= 1
        poly = lfsr_step(poly, tap)
        if poly == 1 and toggle == 0:
            return bytes(out)


def lfsr_period(tap=CORE_TAP):
    """Steps until the 17-bit LFSR comes back to 1: 114,681 with the
    core's taps (not a maximal sequence), 131,071 = 2^17 - 1 with the
    AY's."""
    poly = 1
    n = 0
    while True:
        poly = lfsr_step(poly, tap)
        n += 1
        if poly == 1:
            return n


NOISE = _noise_sequence()


# ---------------------------------------------------------------------------
# One AY
# ---------------------------------------------------------------------------

def _g(x, p):
    """Ticks y in [0, x) with (y // p) even."""
    q, r = divmod(x, 2 * p)
    return p * q + (r if r < p else p)


class Chip:
    """Registers and counters of one YM2149 core, advanced in prescaled
    ticks (clock / 8) and noise ticks (clock / 16)."""

    def __init__(self):
        self.regs = [0] * 16
        self.tone_count = [0, 0, 0]
        self.tone_out = [0, 0, 0]
        self.noise_count = 0
        self.noise_index = 0
        self.env_count = 0
        self.env_step = 0

    def period(self, channel):
        return self.regs[2 * channel] | ((self.regs[2 * channel + 1] & 15)
                                         << 8)

    def noise_period(self):
        return (self.regs[6] & 31) or 1

    def env_period(self):
        return (self.regs[11] | (self.regs[12] << 8)) or 1

    def write(self, reg, value):
        self.regs[reg] = value
        if reg < 6:
            channel = reg >> 1
            p = self.period(channel)
            if p:
                self.tone_count[channel] = min(self.tone_count[channel],
                                               p - 1)
        elif reg == 6:
            self.noise_count = 0
        elif reg in (11, 12):
            self.env_count = min(self.env_count, self.env_period() - 1)
        elif reg == 13:
            self.env_count = 0
            self.env_step = 0

    def advance(self, ticks, noise_ticks):
        for c in range(3):
            p = self.period(c)
            if p:
                total = self.tone_count[c] + ticks
                self.tone_out[c] ^= (total // p) & 1
                self.tone_count[c] = total % p
            else:
                self.tone_count[c] = 0
                self.tone_out[c] = (self.regs[7] >> c) & 1
        total = self.noise_count + noise_ticks
        np_ = self.noise_period()
        self.noise_index = (self.noise_index + total // np_) % len(NOISE)
        self.noise_count = total % np_
        total = self.env_count + ticks
        ep = self.env_period()
        self.env_step += total // ep
        self.env_count = total % ep
        if self.env_step >= 1 << 20:
            self.env_step = 64 + (self.env_step - 64) % 64


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def read_log(path):
    """(bus_hz, psg_multiplier, [(cycle, chip, reg, value)])."""
    bus_hz, multiplier = tables.PAL_NATIVE.bus_hz, 2
    writes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                words = line[1:].split()
                if 'bus_hz' in words:
                    bus_hz = int(words[words.index('bus_hz') + 1])
                if 'psg_multiplier' in words:
                    multiplier = int(words[words.index('psg_multiplier')
                                           + 1])
                continue
            cycle, chip, reg, value = (int(x) for x in line.split())
            writes.append((cycle, chip, reg, value))
    return bus_hz, multiplier, writes


class Result:
    def __init__(self, left, right, clipped):
        self.left = left
        self.right = right
        self.clipped = clipped


def render(writes, bus_hz, psg_multiplier, seconds, rate=SAMPLE_RATE,
           pans=None):
    """Render register writes [(bus cycle, chip, reg, value)] in cycle
    order for `seconds`. Returns a Result with the left and right Phasor
    outputs (0-32767 before the DC blocker, as floats) and the count of
    samples whose sum saturated."""
    pans = DEFAULT_PANS if pans is None else pans
    clock = bus_hz * psg_multiplier
    native = psg_multiplier == 2
    chips = {c: Chip() for c in range(4)}
    audible_chips = (0, 1, 2, 3) if native else (0, 2)
    gains = {key: (pan_gain_left(p), pan_gain_right(p))
             for key, p in pans.items()}
    total = int(seconds * rate)
    left = [0.0] * total
    right = [0.0] * total
    ay = tables.AY_TABLE
    pan_value = {key: ([apply_pan_gain(v, g[0]) for v in range(256)],
                       [apply_pan_gain(v, g[1]) for v in range(256)])
                 for key, g in gains.items()}

    def ce(i):
        return i * clock // rate

    # Group the writes by the sample at which they land.
    events = []
    for cycle, chip, reg, value in writes:
        sample = cycle * rate // bus_hz
        if sample >= total:
            break
        events.append((sample, chip, reg, value))
    events.append((total, None, None, None))
    start = 0
    k = 0
    while start < total:
        while k < len(events) and events[k][0] <= start:
            _, chip, reg, value = events[k]
            if chip is not None:
                chips[chip].write(reg, value)
            k += 1
        end = events[k][0] if k < len(events) else total
        end = min(end, total)
        if end <= start:
            continue
        ce_list = [ce(i) for i in range(start, end + 1)]
        ticks = [x // 8 for x in ce_list]
        t0 = ticks[0]
        rel = [t - t0 for t in ticks]
        n0 = ce_list[0] // 16
        nrel = [x // 16 - n0 for x in ce_list]
        n = end - start
        for chip_number in audible_chips:
            chip = chips[chip_number]
            regs = chip.regs
            mixer = regs[7]
            env_levels = None
            noise_bits = None
            for c in range(3):
                volume = regs[8 + c]
                env_mode = volume & 16
                if not env_mode and not volume & 15:
                    continue
                tone_off = (mixer >> c) & 1
                noise_off = (mixer >> (c + 3)) & 1
                p = chip.period(c)
                if not tone_off and p == 0:
                    continue
                if tone_off:
                    tone = None
                else:
                    c0 = chip.tone_count[c]
                    g = [_g(c0 + r, p) for r in rel]
                    if chip.tone_out[c]:
                        tone = [(g[i + 1] - g[i]) / (rel[i + 1] - rel[i])
                                for i in range(n)]
                    else:
                        tone = [1.0 - (g[i + 1] - g[i]) / (rel[i + 1] - rel[i])
                                for i in range(n)]
                if not noise_off:
                    if noise_bits is None:
                        np_ = chip.noise_period()
                        nc = chip.noise_count
                        ni = chip.noise_index
                        size = len(NOISE)
                        noise_bits = [NOISE[(ni + (nc + r) // np_) % size]
                                      for r in nrel[:n]]
                    gate = noise_bits if tone is None else \
                        [a * b for a, b in zip(tone, noise_bits)]
                else:
                    gate = tone
                pl, pr = pan_value[(chip_number, c)]
                if env_mode:
                    if env_levels is None:
                        ep = chip.env_period()
                        ec = chip.env_count
                        es = chip.env_step
                        shape = regs[13] & 15
                        env_levels = [ay[envelope_level(
                            shape, es + (ec + r) // ep)] for r in rel[:n]]
                    lv = [pl[v] for v in env_levels]
                    rv = [pr[v] for v in env_levels]
                    if gate is None:
                        gl, gr = lv, rv
                    else:
                        gl = [a * b for a, b in zip(lv, gate)]
                        gr = [a * b for a, b in zip(rv, gate)]
                else:
                    value = ay[2 * (volume & 15) + ((volume >> 3) & 1)]
                    a, b = pl[value], pr[value]
                    if gate is None:
                        gl = [a] * n
                        gr = [b] * n
                    else:
                        gl = [a * x for x in gate]
                        gr = [b * x for x in gate]
                left[start:end] = [x + y for x, y in zip(left[start:end], gl)]
                right[start:end] = [x + y for x, y in
                                    zip(right[start:end], gr)]
        for chip in chips.values():
            chip.advance(rel[-1], nrel[-1])
        start = end
    clipped = 0
    if native:
        for side in (left, right):
            for i, v in enumerate(side):
                if v >= 2048:
                    side[i] = 32767.0
                    clipped += 1
                else:
                    side[i] = v * 16
    else:
        for side in (left, right):
            for i, v in enumerate(side):
                side[i] = v * 16
    return Result(left, right, clipped)


def dc_block(samples, pole=DC_POLE):
    out = [0.0] * len(samples)
    x_prev = samples[0] if samples else 0.0
    y = 0.0
    for i, x in enumerate(samples):
        y = x - x_prev + pole * y
        x_prev = x
        out[i] = y
    return out


def to_pcm(samples):
    return array.array('h', (32767 if v > 32767 else -32768 if v < -32768
                             else int(v) for v in samples))


def write_wav(path, result, stereo=True, rate=SAMPLE_RATE,
              gain=LISTENING_GAIN):
    """Write the render as 16-bit PCM after the DC blocker and `gain`;
    returns the peak of the output."""
    left = [gain * v for v in dc_block(result.left)]
    right = [gain * v for v in dc_block(result.right)]
    if stereo:
        frames = array.array('h', [0]) * (2 * len(left))
        frames[0::2] = to_pcm(left)
        frames[1::2] = to_pcm(right)
    else:
        frames = to_pcm([(a + b) / 2 for a, b in zip(left, right)])
    if sys.byteorder == 'big':
        frames.byteswap()
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2 if stereo else 1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())
    return max((abs(v) for v in frames), default=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('log')
    parser.add_argument('out')
    parser.add_argument('--seconds', type=float, default=60.0)
    parser.add_argument('--mono', action='store_true')
    parser.add_argument('--gain', type=float, default=LISTENING_GAIN)
    args = parser.parse_args(argv)
    bus_hz, multiplier, writes = read_log(args.log)
    result = render(writes, bus_hz, multiplier, args.seconds)
    peak = write_wav(args.out, result, stereo=not args.mono, gain=args.gain)
    print('%s: %.1f s, peak %d, %d saturated samples'
          % (args.out, args.seconds, peak, result.clipped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
