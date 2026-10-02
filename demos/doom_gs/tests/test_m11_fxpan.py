"""Chip 3's pans and sides (milestone 11, the effects; tools/sound/README.md
"Stereo by voice"): the one table of chip 3's voices (tools/sound/
tables.py FX_VOICES: A left, B right, C centre), its pans against the
Phasor's pan law, the voice choice's bands, the 65C02 player's equates
generated from the table, the renders' mix with the Doom profile's pans
(the music's chips keeping the menu's), and the profile's keys.

The voice choice itself is tested in tests/test_m11_fxplay.py: on the
model (each band, the fallbacks, every separation with every set of busy
voices against the nearest voice in pan) and on a2vm (fxrun65.py's
stereo scenario and its planted bugs). Host only, no build/ needed.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts tools/ on the path)
from sound import ayrender, fxmodel, musicdisk, tables, tables65

BUS = tables.PAL_NATIVE.bus_hz


def level_of(chip, channel, pans):
    """(left, right) of chip's channel at level 15, tone and noise off."""
    writes = [(0, chip, 7, 0x3F), (0, chip, 8 + channel, 15)]
    r = ayrender.render(writes, BUS, 2, 0.001, pans=pans)
    return r.left[0], r.right[0]


class Table(unittest.TestCase):

    def test_the_voices(self):
        self.assertEqual([tuple(v) for v in tables.FX_VOICES],
                         [('A', 'left', 5), ('B', 'right', 11),
                          ('C', 'centre', 8)])
        self.assertEqual([tables.fx_voice(s)
                          for s in ('left', 'right', 'centre')], [0, 1, 2])

    def test_8_is_the_only_centred_pan(self):
        # the HDL's gains (mockingboard.sv:316-343), as ayrender has them
        both = [p for p in range(16) if ayrender.pan_gain_left(p) ==
                ayrender.pan_gain_right(p) == 16]
        self.assertEqual(both, [tables.PAN_CENTRE])
        self.assertEqual(tables.PAN_CENTRE, 8)
        for v in tables.FX_VOICES:
            left = ayrender.pan_gain_left(v.pan)
            right = ayrender.pan_gain_right(v.pan)
            side = 'centre' if left == right else \
                'left' if left > right else 'right'
            self.assertEqual(side, v.side, v)

    def test_the_bands(self):
        a, b, c = 0, 1, 2
        for sep, first in ((0, a), (95, a), (96, c), (128, c), (160, c),
                           (161, b), (255, b)):
            self.assertEqual(tables.fx_voice_order(sep)[0], first, sep)
        self.assertEqual(tables.fx_voice_order(128), (c, a, b))
        self.assertEqual(tables.fx_voice_order(129), (c, b, a))
        self.assertEqual(tables.fx_voice_order(95), (a, c, b))
        self.assertEqual(tables.fx_voice_order(161), (b, c, a))

    def test_the_65c02_equates(self):
        text = tables65.generate()
        for line in ('FX_VOICE_LEFT   = 0', 'FX_VOICE_RIGHT  = 1',
                     'FX_VOICE_CENTRE = 2', 'FX_SEP_LEFT     = 96',
                     'FX_SEP_CENTRE   = 128', 'FX_SEP_RIGHT    = 160'):
            self.assertIn(line + '\n', text)


class Mix(unittest.TestCase):

    def test_the_music_keeps_the_menu_pans(self):
        for chip in range(3):
            for ch in range(3):
                self.assertEqual(ayrender.DOOM_PANS[chip, ch],
                                 ayrender.DEFAULT_PANS[chip, ch])
        self.assertEqual([ayrender.DOOM_PANS[3, ch] for ch in range(3)],
                         [5, 11, 8])
        self.assertEqual([ayrender.DEFAULT_PANS[3, ch] for ch in range(3)],
                         [5, 11, 5])

    def test_chip3_sides(self):
        full = tables.AY_TABLE[2 * 15 + 1] * 16
        doom = ayrender.DOOM_PANS
        self.assertEqual(level_of(3, 2, doom), (full, full))   # C: centre
        left, right = level_of(3, 0, doom)                      # A: left
        self.assertEqual(left, full)
        self.assertLess(right, left)
        left, right = level_of(3, 1, doom)                      # B: right
        self.assertEqual(right, full)
        self.assertLess(left, right)
        left, right = level_of(3, 2, ayrender.DEFAULT_PANS)     # the menu's
        self.assertLess(right, left)                            # C leans left
        # the music's chips: the same with either pans
        for chip in range(3):
            for ch in range(3):
                self.assertEqual(level_of(chip, ch, doom),
                                 level_of(chip, ch, ayrender.DEFAULT_PANS))

    def test_the_effect_renders_take_the_doom_pans(self):
        seen = []
        real = ayrender.render

        def spy(*args, **kw):
            seen.append(kw.get('pans'))
            return real(*args, **kw)
        tmp = Path(tempfile.mkdtemp(prefix='fxpan-'))
        try:
            with mock.patch.object(ayrender, 'render', spy):
                fxmodel.render([(0, 0, 0)] * 4, tmp / 'x.ay', tmp / 'x.wav')
        finally:
            for p in (tmp / 'x.ay', tmp / 'x.wav'):
                if p.exists():
                    p.unlink()
            tmp.rmdir()
        self.assertEqual(seen, [ayrender.DOOM_PANS])


class Profile(unittest.TestCase):

    def test_the_pan_keys(self):
        self.assertEqual(musicdisk.PROFILE_PANS,
                         ('phasor.pan.10=5', 'phasor.pan.11=11',
                          'phasor.pan.12=8'))
        for key in musicdisk.PROFILE_PANS + (musicdisk.PROFILE_KEY,):
            self.assertIn('\n    %s\n' % key, musicdisk.PROFILE_TEXT)
        self.assertTrue(all(ord(ch) < 128 for ch in musicdisk.PROFILE_TEXT))


if __name__ == '__main__':
    unittest.main()
