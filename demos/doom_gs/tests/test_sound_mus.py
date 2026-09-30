"""Tests of tools/sound/mus.py: the MUS parser on hand-made bytes, its
errors, and the WAD's songs (skipped without build/)."""

import os
import struct
import unittest

import support  # noqa: F401  (puts tools/ on the path)
from sound import mus

WAD_MISSING = '%s is missing: run python3 tools/fetch_upstream.py first' \
    % os.path.relpath(mus.WAD_PATH, support.ROOT)
needs_wad = unittest.skipUnless(mus.WAD_PATH.exists(), WAD_MISSING)


def make_mus(score, instruments=(), primary=1, secondary=0, extra=b''):
    """A MUS lump with the given score bytes."""
    start = 16 + 2 * len(instruments)
    head = b'MUS\x1a' + struct.pack('<HHHHHH', len(score), start, primary,
                                    secondary, len(instruments), 0)
    head += b''.join(struct.pack('<H', i) for i in instruments)
    return head + bytes(score) + extra


# Every event type once, with delays of 1, 2 and 3 bytes and the volume
# memory of a channel. Ticks: 0, 0, 5, 5, 5+130, ...
EVERY_EVENT = bytes([
    0x10, 0x80 | 60, 100,          # ch 0 play 60, volume 100
    0x91, 0x80 | 64, 90, 5,        # ch 1 play 64, volume 90; delay 5
    0x10, 62,                      # ch 0 play 62 (volume 100 again)
    0x00, 60,                      # ch 0 release 60
    0xa0, 0x40, 0x81, 0x02,        # ch 0 bend 64; delay 130 (2 bytes)
    0x3f, 11,                      # ch 15 all notes off
    0x42, 3, 77,                   # ch 2 volume 77
    0x42, 0, 30,                   # ch 2 program 30
    0xd3, 0x81, 0x80, 0x01,        # ch 3 end of measure; delay 16385
    0x6e,                          # ch 14 score end
])


class HandMade(unittest.TestCase):
    def test_every_event_type(self):
        song = mus.parse(make_mus(EVERY_EVENT, instruments=(30, 135)),
                         'TEST')
        got = [(e.tick, e.kind, e.chan, e.a, e.b, e.volume)
               for e in song.events]
        self.assertEqual(got, [
            (0, 'on', 0, 60, 100, 100),
            (0, 'on', 1, 64, 90, 90),
            (5, 'on', 0, 62, 100, None),
            (5, 'off', 0, 60, 0, None),
            (5, 'bend', 0, 64, 0, None),
            (135, 'sys', 15, 11, 0, None),
            (135, 'ctrl', 2, 3, 77, None),
            (135, 'ctrl', 2, 0, 30, None),
            (135, 'measure', 3, 0, 0, None),
            (135 + 16385, 'end', 14, 0, 0, None),
        ])
        self.assertEqual(song.instruments, [30, 135])
        self.assertEqual(song.length_ticks, 16520)
        self.assertEqual(song.events[3].offset, 16 + 4 + 9)
        counts = song.counts()
        self.assertEqual(counts['on'], 3)
        self.assertEqual(counts['ctrl 3'], 1)
        self.assertEqual(counts['sys 11'], 1)

    def test_first_volume_is_127(self):
        song = mus.parse(make_mus([0x15, 40, 0x60]))
        self.assertEqual(song.events[0].b, 127)
        self.assertIsNone(song.events[0].volume)

    def test_every_controller_and_system_event(self):
        score = []
        for number in range(10):
            score += [0x40, number, 5]
        for number in range(10, 15):
            score += [0x30, number]
        score += [0x60]
        song = mus.parse(make_mus(score))
        self.assertEqual([(e.kind, e.a) for e in song.events[:-1]],
                         [('ctrl', n) for n in range(10)]
                         + [('sys', n) for n in range(10, 15)])

    def test_bytes_after_the_end_are_ignored(self):
        song = mus.parse(make_mus([0x60, 0x10, 60]))
        self.assertEqual(len(song.events), 1)


class Errors(unittest.TestCase):
    def check(self, data, words, offset=None):
        with self.assertRaises(mus.MusError) as caught:
            mus.parse(data)
        self.assertIn(words, str(caught.exception))
        if offset is not None:
            self.assertEqual(caught.exception.offset, offset)

    def test_short_header(self):
        self.check(b'MUS\x1a\x00', 'header truncated')

    def test_bad_magic(self):
        self.check(b'MID\x1a' + bytes(20), 'not a MUS lump', 0)

    def test_instrument_list_past_the_end(self):
        data = b'MUS\x1a' + struct.pack('<HHHHHH', 1, 16, 1, 0, 50, 0)
        self.check(data + b'\x60', 'instrument list')

    def test_score_inside_the_header(self):
        data = b'MUS\x1a' + struct.pack('<HHHHHH', 1, 10, 1, 0, 0, 0)
        self.check(data + bytes(10), 'inside the header')

    def test_score_past_the_end(self):
        data = make_mus([0x60])
        data = data[:4] + struct.pack('<H', 5) + data[6:]
        self.check(data, 'runs past the end')

    def test_no_score_end(self):
        self.check(make_mus([0x10, 60]), 'no score end')

    def test_truncated_events(self):
        for score, what in (([0x00], 'note'), ([0x10], 'note'),
                            ([0x10, 0x80 | 60], 'volume'),
                            ([0x20], 'bend'), ([0x30], 'system event'),
                            ([0x40], 'controller number'),
                            ([0x40, 3], 'controller value'),
                            ([0x80 | 0x50], 'delay'),
                            ([0x80 | 0x50, 0x81], 'delay')):
            with self.subTest(score=score):
                self.check(make_mus(score), 'truncated: %s missing' % what,
                           16)

    def test_event_type_7(self):
        self.check(make_mus([0x10, 60, 0x70, 0x60]), 'type 7', 18)

    def test_unknown_controller(self):
        self.check(make_mus([0x40, 10, 0, 0x60]), 'unknown controller', 17)

    def test_controller_value_above_127(self):
        self.check(make_mus([0x40, 3, 200, 0x60]), 'value above 127', 18)

    def test_unknown_system_event(self):
        self.check(make_mus([0x30, 9, 0x60]), 'unknown system event', 17)

    def test_release_with_bit_7(self):
        self.check(make_mus([0x00, 0x80 | 60, 0x60]), 'bit 7', 17)

    def test_volume_above_127(self):
        self.check(make_mus([0x10, 0x80 | 60, 0x80, 0x60]),
                   'volume above 127', 18)

    def test_delay_too_long(self):
        self.check(make_mus([0xd0, 0x81, 0x81, 0x81, 0x81, 0x01, 0x60]),
                   'delay longer')


class WadErrors(unittest.TestCase):
    def test_not_a_wad(self):
        with self.assertRaises(mus.WadError):
            mus.Wad(b'JUNK' + bytes(8))

    def test_directory_past_the_end(self):
        with self.assertRaises(mus.WadError):
            mus.Wad(b'PWAD' + struct.pack('<II', 3, 12))

    def test_small_wad(self):
        lump = make_mus([0x60])
        data = b'PWAD' + struct.pack('<II', 1, 12 + len(lump)) + lump
        data += struct.pack('<II8s', 12, len(lump), b'D_TEST')
        wad = mus.Wad(data)
        self.assertEqual(wad.songs(), ['D_TEST'])
        self.assertEqual(wad.song('D_TEST').length_ticks, 0)
        with self.assertRaises(KeyError):
            wad.lump('D_NONE')


@needs_wad
class SharewareSongs(unittest.TestCase):
    # Events, notes and seconds of each song (native-sound.md section 1).
    EXPECTED = {
        'D_E1M1': (5826, 2332, 96.0), 'D_E1M2': (10847, 2036, 155.4),
        'D_E1M3': (7507, 3749, 272.0), 'D_E1M4': (6270, 3105, 170.7),
        'D_E1M5': (3270, 1464, 164.0), 'D_E1M6': (3332, 1625, 84.0),
        'D_E1M7': (2835, 1336, 150.9), 'D_E1M8': (18113, 877, 152.0),
        'D_E1M9': (7766, 3805, 137.4), 'D_INTER': (9884, 4932, 201.4),
        'D_INTRO': (498, 110, 6.9), 'D_VICTOR': (4532, 2254, 192.0),
        'D_INTROA': (214, 58, 6.9),
    }

    @classmethod
    def setUpClass(cls):
        cls.wad = mus.Wad.open()

    def test_song_list(self):
        self.assertEqual(self.wad.kind, 'IWAD')
        self.assertEqual(len(self.wad.lumps), 1264)
        self.assertEqual(sorted(self.wad.songs()),
                         sorted(mus.UPSTREAM_SONGS))
        self.assertEqual(sum(len(self.wad.lump(n)) for n in
                             self.wad.songs()), 245179)

    def test_every_song_parses_to_its_end(self):
        for name in mus.UPSTREAM_SONGS:
            with self.subTest(song=name):
                song = self.wad.song(name)
                events, notes, seconds = self.EXPECTED[name]
                self.assertEqual(len(song.events), events)
                self.assertEqual(song.counts()['on'], notes)
                self.assertEqual(round(song.seconds, 1), seconds)
                self.assertEqual(song.events[-1].kind, 'end')
                self.assertEqual(song.score_start + song.score_length,
                                 song.size)


if __name__ == '__main__':
    unittest.main()
