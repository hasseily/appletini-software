"""Tests of tools/sound/ayrender.py against the formulas of the YM2149
core (tone frequency, noise LFSR, envelope shapes and rate, levels) and
the Phasor's pan and mix."""

import os
import tempfile
import unittest
import wave

import support  # noqa: F401  (puts tools/ on the path)
from sound import ayrender, tables

BUS = tables.PAL_NATIVE.bus_hz
CLOCK = 2 * BUS


def setup_writes(chip, regs):
    """Writes at cycle 0 for {reg: value}."""
    return [(0, chip, reg, value) for reg, value in sorted(regs.items())]


def render(regs, seconds=1.0, chip=0, multiplier=2):
    return ayrender.render(setup_writes(chip, regs), BUS, multiplier,
                           seconds)


def rising_crossings(samples):
    out = ayrender.dc_block(samples)
    skip = len(out) // 10              # let the DC blocker settle
    return sum(1 for a, b in zip(out[skip:], out[skip + 1:])
               if a < 0 <= b), (len(out) - skip) / ayrender.SAMPLE_RATE


class Envelope(unittest.TestCase):
    def seq(self, shape, n=100):
        return [ayrender.envelope_level(shape, k) for k in range(n)]

    def test_one_shot_shapes(self):
        down = list(range(31, -1, -1))
        up = list(range(32))
        for shape in (0, 1, 2, 3, 9):
            self.assertEqual(self.seq(shape), down + [0] * 68)
        for shape in (4, 5, 6, 7, 15):
            self.assertEqual(self.seq(shape), up + [0] * 68)
        self.assertEqual(self.seq(11), down + [31] * 68)
        self.assertEqual(self.seq(13), up + [31] * 68)

    def test_repeating_shapes(self):
        down = list(range(31, -1, -1))
        up = list(range(32))
        self.assertEqual(self.seq(8, 128), down * 4)
        self.assertEqual(self.seq(12, 128), up * 4)
        self.assertEqual(self.seq(10, 128), (down + up) * 2)
        self.assertEqual(self.seq(14, 128), (up + down) * 2)

    def test_far_steps(self):
        self.assertEqual(ayrender.envelope_level(10, 64 * 1000 + 5), 26)
        self.assertEqual(ayrender.envelope_level(0, 10 ** 6), 0)

    def test_sawtooth_rate(self):
        # one step every EP prescaled ticks, 32 steps: f = clock / (256 EP)
        result = render({7: 0x3f, 8: 0x10, 11: 100, 12: 0, 13: 8})
        count, seconds = rising_crossings(result.left)
        self.assertAlmostEqual(count / seconds, CLOCK / (256 * 100),
                               delta=1.5)


class Noise(unittest.TestCase):
    def test_lfsr_period(self):
        # the core's taps (bit0 ^ bit2, YM2149.sv:187) are not maximal;
        # the AY's (bit0 ^ bit3) are: 2^17 - 1
        self.assertEqual(ayrender.lfsr_period(), 114681)
        self.assertEqual(ayrender.lfsr_period(ayrender.AY_TAP), 2 ** 17 - 1)
        self.assertIn(len(ayrender.NOISE), (114681, 2 * 114681))

    def test_lfsr_steps_by_hand(self):
        # from 1: bit0 ^ bit2 = 1 goes in at bit 16
        self.assertEqual(ayrender.lfsr_step(1), 0x10000)
        self.assertEqual(ayrender.lfsr_step(0b101), 0b10)
        self.assertEqual(ayrender.lfsr_step(0b100), 0x10002)
        # the output starts high (~toggle) and toggles on bit0 ^ bit1
        self.assertEqual(ayrender.NOISE[:2], bytes([1, 0]))

    def toggle_fraction(self):
        noise = ayrender.NOISE
        return sum(1 for i in range(len(noise))
                   if noise[i] != noise[(i + 1) % len(noise)]) / len(noise)

    def test_output_toggles_on_about_half_the_steps(self):
        self.assertAlmostEqual(self.toggle_fraction(), 0.5, delta=0.01)

    def test_step_rate(self):
        # noise period 5: an LFSR step every 16 x 5 PSG clocks
        result = render({7: 0x37, 8: 15, 6: 5}, multiplier=2)
        s = result.left
        changes = sum(1 for a, b in zip(s, s[1:]) if a != b)
        expected = CLOCK / (16 * 5) * self.toggle_fraction()
        self.assertAlmostEqual(changes / expected, 1.0, delta=0.02)


class Tone(unittest.TestCase):
    def test_frequency(self):
        for period in (284, 1000, 3882):
            with self.subTest(period=period):
                result = render({0: period & 255, 1: period >> 8, 7: 0x3e,
                                 8: 15})
                count, seconds = rising_crossings(result.left)
                self.assertAlmostEqual(count / seconds,
                                       CLOCK / (16 * period),
                                       delta=CLOCK / (16 * period) * 0.005
                                       + 1)

    def test_mockingboard_mode_halves_the_clock(self):
        result = render({0: 200, 7: 0x3e, 8: 15}, multiplier=1)
        count, seconds = rising_crossings(result.left)
        self.assertAlmostEqual(count / seconds, BUS / (16 * 200), delta=2)

    def test_period_0_silences_a_tone(self):
        result = render({7: 0x3e, 8: 15}, seconds=0.01)
        self.assertEqual(max(result.left), 0)

    def test_box_average_is_half_on_a_fast_tone(self):
        # P = 1: 127 kHz, far above the sample rate: the average is half
        result = render({0: 1, 7: 0x3e, 8: 15}, seconds=0.01)
        right = result.right[10]
        self.assertAlmostEqual(right, 255 * 16 / 2, delta=255 * 16 * 0.1)


class Levels(unittest.TestCase):
    def test_fixed_levels_and_pans(self):
        # tone and noise off: the channel outputs its level all the time.
        # Chip 0 channel A has pan 11: left 9/16, right 16/16.
        for level in range(16):
            result = render({7: 0x3f, 8: level}, seconds=0.001)
            value = tables.AY_TABLE[2 * level + (level >> 3)]
            self.assertEqual(result.right[0], value * 16)
            self.assertEqual(result.left[0],
                             ((value >> 1) + (value >> 4)) * 16)
        # chip 2 (VIA-B, first AY) channel A has pan 5: left 16, right 10
        result = render({7: 0x3f, 8: 15}, seconds=0.001, chip=2)
        self.assertEqual(result.left[0], 255 * 16)
        self.assertEqual(result.right[0], (127 + 31) * 16)

    def test_default_pans(self):
        pans = ayrender.DEFAULT_PANS
        self.assertEqual([pans[0, c] for c in range(3)], [11, 5, 11])
        self.assertEqual([pans[1, c] for c in range(3)], [11, 5, 11])
        self.assertEqual([pans[2, c] for c in range(3)], [5, 11, 5])
        self.assertEqual([pans[3, c] for c in range(3)], [5, 11, 5])

    def test_the_sum_saturates(self):
        writes = []
        for chip in range(4):
            writes += setup_writes(chip, {7: 0x3f, 8: 15, 9: 15, 10: 15})
        result = ayrender.render(writes, BUS, 2, 0.001)
        self.assertEqual(result.left[0], 32767)
        self.assertGreater(result.clipped, 0)

    def test_mockingboard_mode_hears_chips_0_and_2(self):
        writes = setup_writes(1, {7: 0x3f, 8: 15}) + \
            setup_writes(3, {7: 0x3f, 8: 15})
        result = ayrender.render(writes, BUS, 1, 0.001)
        self.assertEqual(max(result.left), 0)


class Files(unittest.TestCase):
    def test_log_and_wav(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, 'x.log')
            with open(log, 'w') as f:
                f.write('# bus_hz 1020484 psg_multiplier 1\n')
                f.write('0 0 0 200\n0 0 7 62\n0 0 8 15\n')
            bus, multiplier, writes = ayrender.read_log(log)
            self.assertEqual((bus, multiplier), (1020484, 1))
            self.assertEqual(writes[2], (0, 0, 8, 15))
            result = ayrender.render(writes, bus, multiplier, 0.1)
            path = os.path.join(d, 'x.wav')
            peak = ayrender.write_wav(path, result)
            self.assertGreater(peak, 0)
            with wave.open(path) as w:
                self.assertEqual(w.getnchannels(), 2)
                self.assertEqual(w.getframerate(), 44100)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getnframes(), 4410)
            ayrender.write_wav(path, result, stereo=False)
            with wave.open(path) as w:
                self.assertEqual(w.getnchannels(), 1)


if __name__ == '__main__':
    unittest.main()
