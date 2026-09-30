"""Tests of tools/sound/mus2ay.py (the converter) and genmidi.py: rules on
hand-made songs, then invariants and the design's figures on the WAD's
13 songs (skipped without build/)."""

import struct
import unittest

import support  # noqa: F401  (puts tools/ on the path)
from sound import genmidi, mus, mus2ay, player, report, tables
from test_sound_mus import make_mus, needs_wad


def genmidi_lump(overrides):
    """A GENMIDI lump; overrides: {program: dict(ar, dr, sl, rr,
    sustained, offset, fixed, fixed_note, level)}."""
    records = b''
    for i in range(genmidi.RECORDS):
        o = dict(ar=15, dr=0, sl=0, rr=15, sustained=True, offset=0,
                 fixed=False, fixed_note=0, level=0)
        o.update(overrides.get(i, {}))
        carrier = bytes([0x20 if o['sustained'] else 0,
                         (o['ar'] << 4) | o['dr'], (o['sl'] << 4) | o['rr'],
                         0, 0, o['level']])
        voice = bytes(6) + b'\x00' + carrier + b'\x00' + struct.pack(
            '<h', o['offset'])
        records += struct.pack('<HBB', 1 if o['fixed'] else 0, 0,
                               o['fixed_note']) + voice + bytes(16)
    names = b''.join(('P%d' % i).encode().ljust(32, b'\0')
                     for i in range(genmidi.RECORDS))
    return b'#OPL_II#' + records + names


INSTRUMENTS = genmidi.read(genmidi_lump({
    1: dict(ar=5, dr=1, sl=15, rr=6, sustained=True),
    2: dict(offset=-12),
    3: dict(fixed=True, fixed_note=50),
    4: dict(level=10),
}))


def delay(ticks):
    """A MUS delay (base 128, most significant group first)."""
    groups = [ticks & 0x7f]
    ticks >>= 7
    while ticks:
        groups.append(0x80 | (ticks & 0x7f))
        ticks >>= 7
    return list(reversed(groups))


def score(*events):
    """MUS bytes from (delay_after, event bytes) pairs; ends the score."""
    out = []
    for wait, data in events:
        data = list(data)
        if wait:
            data[0] |= 0x80
            data += delay(wait)
        out += data
    return make_mus(out + [0x60])


def convert(lump, layout='native12'):
    return mus2ay.convert(mus.parse(lump), INSTRUMENTS, layout)


def commands(song_file):
    return [(t, c, v, ops) for t, c, v, ops in
            player.decode_stream(song_file.stream)]


class Genmidi(unittest.TestCase):
    def test_fields(self):
        ins = INSTRUMENTS[1]
        self.assertEqual((ins.attack_rate, ins.decay_rate,
                          ins.sustain_level, ins.release_rate), (5, 1, 15, 6))
        self.assertTrue(ins.sustained)
        self.assertEqual(INSTRUMENTS[2].note_offset, -12)
        self.assertTrue(INSTRUMENTS[3].fixed)
        self.assertEqual(INSTRUMENTS[3].fixed_note, 50)
        self.assertEqual(INSTRUMENTS[4].level, 10)
        self.assertEqual(INSTRUMENTS[7].name, 'P7')

    def test_not_genmidi(self):
        with self.assertRaises(genmidi.GenmidiError):
            genmidi.read(b'#OPL_I#' + bytes(20000))
        with self.assertRaises(genmidi.GenmidiError):
            genmidi.read(b'#OPL_II#' + bytes(100))


class Envelopes(unittest.TestCase):
    def test_by_hand(self):
        # attack rate 5: 176.64 ms = 24.73 ticks; 80 x 256 / 24.73 = 828
        # decay rate 1: 39280.64 ms over 96 dB = 192 units: 49152 / 5499 = 9
        # sustain level 15: 45 dB, capped at 80 units (40 dB)
        # release rate 6: 1227.52 ms = 171.85 ticks; 49152 / 171.85 = 286
        self.assertEqual(mus2ay.envelope_of(INSTRUMENTS[1]),
                         (828, 9, 286, 80, player.ENV_SUSTAINED))
        # attack 15 and release 15 take one tick; decay 0 never moves
        self.assertEqual(mus2ay.envelope_of(INSTRUMENTS[0]),
                         (65535, 0, 65535, 0, player.ENV_SUSTAINED))

    def test_drum_recipe(self):
        # bass drum: tone 33, no noise, 160 ms: EP = 0.16 x 2031250 / 256
        # = 1269.5 -> 1270; soft step 80 x 256 / 22.4 ticks = 914
        self.assertEqual(mus2ay.drum_recipe(36, tables.PAL_NATIVE),
                         (33, 0, 1270, 914))
        self.assertEqual(mus2ay.drum_recipe(36, tables.PAL_MOCKINGBOARD),
                         (33, 0, 635, 914))
        self.assertEqual(mus2ay.drum_recipe(99, tables.PAL_NATIVE)[:2],
                         (0, 3))


class Stream(unittest.TestCase):
    def test_note_forms_and_waits(self):
        lump = score((300, [0x10, 0x80 | 60, 127]),   # program 0
                     (10, [0x00, 60]),
                     (0, [0x10, 60]))
        song_file, stats = convert(lump)
        self.assertEqual(song_file.stream, bytes([
            0x20, 60, 0, 0, 0x50, 128,        # first note: all of it
            0xfe, 0xfe, 0x80 + 48,            # 300 = 126 + 126 + 48
            0x30,                             # release
            0x8a,                             # 10 ticks
            0x00, 60,                         # same voice, same note: short
            0x30, 0xff]))                     # released at the end
        self.assertEqual(stats['offs at the end'], 1)

    def test_empty_song_still_waits(self):
        song_file, _ = convert(make_mus([0x60]))
        self.assertEqual(song_file.stream, bytes([0x81, 0xff]))

    def test_note_mapping(self):
        lump = score((0, [0x40, 0, 2]), (0, [0x10, 60]),     # offset -12
                     (0, [0x41, 0, 3]), (0, [0x11, 60]),     # fixed 50
                     (0, [0x42, 0, 4]), (1, [0x12, 60]))     # level 10
        cmds = commands(convert(lump)[0])
        notes = [(ops[0], ops[1]) for _, c, _, ops in cmds if c <= 2]
        # level 10 x 0.75 dB = 7.5 dB = 15 units
        self.assertEqual(notes, [(48, 0), (50, 0), (60, 15)])

    def test_velocity_volume_and_expression(self):
        # velocity 64 = 24 units; volume 64 adds 24; expression 64 adds 24
        lump = score((0, [0x40, 3, 64]), (0, [0x40, 5, 64]),
                     (1, [0x10, 0x80 | 60, 64]))
        cmds = commands(convert(lump)[0])
        self.assertEqual(cmds[0][3], (60, 72, 0))


class Allocation(unittest.TestCase):
    def test_same_channel_and_note_takes_its_voice_again(self):
        lump = score((1, [0x10, 60]), (1, [0x10, 60]))
        cmds = commands(convert(lump)[0])
        self.assertEqual([v for _, c, v, _ in cmds if c <= 2], [0, 0])

    def test_steal_keeps_the_bass_and_takes_the_busiest_channel(self):
        # channel 0 holds 4 notes, channel 1 three with the lowest note;
        # the 8th note steals the oldest note of channel 0
        events = [(1, [0x10, n]) for n in (60, 62, 64, 67)]
        events += [(1, [0x11, n]) for n in (30, 70, 72)]
        events += [(1, [0x12, 80])]
        song_file, stats = convert(score(*events))
        ons = [(v, ops[0]) for _, c, v, ops in commands(song_file) if c <= 2]
        self.assertEqual(stats['steals'], 1)
        self.assertEqual(ons[-1], (0, 80))      # voice 0 held note 60
        self.assertEqual(stats['max voices'], 7)
        # the stolen note's release is lost
        _, stats = convert(score(*events, (1, [0x00, 60])))
        self.assertEqual(stats['lost offs'], 1)

    def test_release_cut_takes_the_release_that_ends_first(self):
        # program 1 releases over about 72 ticks; 7 notes released in
        # order, then an 8th note: every voice is still releasing, and the
        # one released first ends first
        events = [(0, [0x40, 0, 1])]
        events += [(0, [0x10, 60 + i]) for i in range(7)]
        events += [(1, [0x00, 60 + i]) for i in (3, 1, 0, 2, 4, 5, 6)]
        events += [(1, [0x10, 40])]
        song_file, stats = convert(score(*events))
        self.assertEqual(stats['release cuts'], 1)
        self.assertEqual(stats['steals'], 0)
        ons = [v for _, c, v, _ in commands(song_file) if c <= 2]
        self.assertEqual(ons[-1], 3)

    def test_idle_voice_holding_the_pitch_is_preferred(self):
        # notes 60 then 62, both released and silent; a new 62 goes back
        # to voice 1, which needs no tone write
        events = [(0, [0x10, 60]), (5, [0x10, 62]), (0, [0x00, 60]),
                  (10, [0x00, 62]), (1, [0x10, 62])]
        ons = [v for _, c, v, _ in commands(convert(score(*events))[0])
               if c <= 2]
        self.assertEqual(ons, [0, 1, 1])

    def test_mb6_takes_the_voice_idle_the_longest(self):
        # the case above in mb6: the design's rule, so the new 62 goes to
        # voice 2, never used, not to voice 1 that holds its pitch
        events = [(0, [0x10, 60]), (5, [0x10, 62]), (0, [0x00, 60]),
                  (10, [0x00, 62]), (1, [0x10, 62])]
        ons = [v for _, c, v, _ in commands(convert(score(*events),
                                                    'mb6')[0]) if c <= 2]
        self.assertEqual(ons, [0, 1, 2])

    def test_steal_keeps_the_bass_on_the_lowest_voice(self):
        # mb6: channel 1 plays 40 on voice 1 at tick 0; voice 0 is freed
        # and channel 0 plays 40 on it at tick 6; channel 2 holds 50 on
        # voice 2. A fourth note steals: of the two basses the one on
        # voice 0 is kept, and each channel holds one voice, so the
        # oldest other note goes: 40 of channel 1, voice 1.
        events = [(0, [0x10, 60]), (1, [0x11, 40]), (1, [0x00, 60]),
                  (4, [0x12, 50]), (0, [0x10, 40]), (1, [0x13, 70])]
        song_file, stats = convert(score(*events), 'mb6')
        ons = [(v, ops[0]) for _, c, v, ops in commands(song_file) if c <= 2]
        self.assertEqual(ons, [(0, 60), (1, 40), (2, 50), (0, 40), (1, 70)])
        self.assertEqual(stats['steals'], 1)

    def test_drums(self):
        # three hits at one tick on two drum voices: the third steals the
        # oldest hit
        events = [(0, [0x1f, 36]), (0, [0x1f, 42]), (1, [0x1f, 38])]
        song_file, stats = convert(score(*events))
        hits = [(v, ops) for _, c, v, ops in commands(song_file) if c == 6]
        self.assertEqual(hits, [(7, (0, 0)), (8, (1, 0)), (7, (2, 0))])
        self.assertEqual(stats['drum steals'], 1)
        self.assertEqual([d[:2] for d in song_file.drums],
                         [(33, 0), (0, 1), (50, 6)])
        song_file, _ = convert(score(*events), 'mb6')
        self.assertEqual({v for _, c, v, _ in commands(song_file)
                          if c == 6}, {3})

    def test_idle_drum_voice_with_the_same_recipe_is_preferred(self):
        # bass drum on voice 7, closed hi-hat on voice 8; 20 ticks later
        # both are idle and a hi-hat goes back to voice 8, which needs no
        # tone, noise, mixer or envelope writes; then a bass drum to 7
        events = [(0, [0x1f, 36]), (20, [0x1f, 42]), (20, [0x1f, 42]),
                  (0, [0x1f, 36])]
        hits = [(v, ops[0]) for _, c, v, ops in
                commands(convert(score(*events))[0]) if c == 6]
        self.assertEqual(hits, [(7, 0), (8, 1), (8, 1), (7, 0)])


class Updates(unittest.TestCase):
    def test_volume_change_sent_only_when_the_level_changes(self):
        # velocity 127: natt 0, level 15. Volume 125 (0.3 units) keeps
        # level 15; volume 100 (8 units, -4 dB) gives level 12.
        lump = score((1, [0x10, 60]), (1, [0x40, 3, 125]),
                     (1, [0x40, 3, 100]), (1, [0x40, 3, 100]))
        song_file, stats = convert(lump)
        att = [(t, v, ops) for t, c, v, ops in commands(song_file) if c == 4]
        self.assertEqual(att, [(2, 0, (8,))])
        self.assertEqual(stats['volume events'], 3)

    def test_bend_goes_to_the_held_notes_of_its_channel(self):
        lump = score((0, [0x10, 60]), (0, [0x10, 64]), (0, [0x11, 50]),
                     (1, [0x20, 100]), (1, [0x00, 60]), (1, [0x20, 90]),
                     (1, [0x10, 67]))
        cmds = commands(convert(lump)[0])
        bends = [(t, v, ops[0]) for t, c, v, ops in cmds if c == 5]
        # tick 0: three first notes (their voices' bend is unknown, so it
        # is sent), then the bend of channel 0 to its two notes; tick 1:
        # note 60 released; tick 2: the bend reaches the one note left;
        # tick 3: a new note of channel 0 on a fresh voice gets it too
        self.assertEqual(bends, [(0, 0, 128), (0, 1, 128), (0, 2, 128),
                                 (0, 0, 100), (0, 1, 100),
                                 (2, 1, 90), (3, 3, 90)])

    def test_all_notes_off(self):
        lump = score((0, [0x10, 60]), (1, [0x10, 64]), (1, [0x30, 11]))
        song_file, _ = convert(lump)
        offs = [(t, v) for t, c, v, _ in commands(song_file) if c == 3]
        self.assertEqual(offs, [(1, 0), (1, 1)])

    def test_all_sounds_off_cuts_at_once(self):
        # (A pair of score() is an event and the delay after it.) Program
        # 1 releases over about 72 ticks. Channel 0: 60 held on voice 0,
        # 62 on voice 1 released at tick 1 and still sounding; channel 1:
        # 64 on voice 2. Event 10 on channel 0 at tick 2 cuts voices 0
        # and 1 and leaves channel 1 alone; both are idle at once, so 67
        # at tick 3 takes voice 0 without a release cut.
        lump = score((0, [0x40, 0, 1]), (0, [0x40, 1, 1]),
                     (0, [0x10, 60]), (0, [0x10, 62]), (1, [0x11, 64]),
                     (1, [0x00, 62]), (1, [0x30, 10]), (1, [0x10, 67]))
        song_file, stats = convert(lump)
        cmds = commands(song_file)
        self.assertEqual([(t, v) for t, c, v, _ in cmds
                          if c == player.CUT], [(2, 0), (2, 1)])
        self.assertEqual([(t, v, ops[0]) for t, c, v, ops in cmds if c <= 2],
                         [(0, 0, 60), (0, 1, 62), (0, 2, 64), (3, 0, 67)])
        self.assertEqual([(t, v) for t, c, v, _ in cmds if c == 3],
                         [(1, 1), (4, 0), (4, 2)])   # the end releases
        self.assertEqual(stats['cuts'], 2)
        self.assertEqual(stats['release cuts'], 0)
        self.assertEqual(stats['lost offs'], 0)

    def test_all_sounds_off_on_the_drum_channel(self):
        # a bass drum (160 ms, 23 ticks) and a hi-hat (50 ms, 7 ticks) at
        # tick 0; event 10 on channel 15 at tick 10 cuts only the drum
        # still decaying (a pair of score() is an event and the delay
        # after it)
        lump = score((0, [0x1f, 36]), (10, [0x1f, 42]), (1, [0x3f, 10]))
        cmds = commands(convert(lump)[0])
        self.assertEqual([(t, v) for t, c, v, _ in cmds
                          if c == player.CUT], [(10, 7)])

    def test_reset_all_controllers(self):
        # expression 64 (24 units) and bend 100 on a held note, then event
        # 14 at tick 1: its attenuation goes back to 0 and its bend to 128
        lump = score((0, [0x40, 5, 64]), (0, [0x10, 60]), (1, [0x20, 100]),
                     (1, [0x30, 14]), (1, [0x00, 60]))
        cmds = commands(convert(lump)[0])
        self.assertEqual(cmds[0][3], (60, 24, 0))
        self.assertEqual([(t, c, v, ops) for t, c, v, ops in cmds
                          if t == 1], [(1, 4, 0, (0,)), (1, 5, 0, (128,))])

    def test_a_note_of_volume_0_is_a_note_off(self):
        # 60 held, then "play 60 at volume 0": released, no second voice;
        # then 62 at volume 0 (nothing held): a lost off, no note; a drum
        # hit at volume 0 plays nothing
        lump = score((1, [0x10, 60]), (1, [0x10, 0x80 | 60, 0]),
                     (1, [0x10, 0x80 | 62, 0]), (1, [0x1f, 0x80 | 36, 0]))
        song_file, stats = convert(lump)
        cmds = commands(song_file)
        self.assertEqual([(t, c, v) for t, c, v, _ in cmds
                          if c != player.END], [(0, 2, 0), (0, 5, 0),
                                                (1, 3, 0)])
        self.assertEqual((stats['notes'], stats['lost offs'],
                          stats['drum hits'], stats['silent notes']),
                         (1, 1, 0, 0))


# The design's figures (build/native-design/sound/summary50.md, the
# tables of docs/research/native-sound.md 3.3 and 4.2), native12 then mb6:
# steals, drum steals, writes/s, p99 writes of a burst.
DESIGN = {
    'native12': {
        'D_E1M1': (0, 133, 134, 18), 'D_E1M2': (8, 276, 91, 12),
        'D_E1M3': (0, 5, 97, 11), 'D_E1M4': (0, 92, 124, 20),
        'D_E1M5': (0, 0, 47, 10), 'D_E1M6': (0, 33, 143, 15),
        'D_E1M7': (0, 4, 49, 7), 'D_E1M8': (0, 43, 47, 11),
        'D_E1M9': (2, 272, 125, 22), 'D_INTER': (52, 216, 132, 22),
        'D_INTRO': (7, 4, 64, 12), 'D_VICTOR': (3, 60, 77, 13),
        'D_INTROA': (0, 0, 59, 6)},
    'mb6': {
        'D_E1M1': (290, 447, 81, 12), 'D_E1M2': (76, 699, 37, 8),
        'D_E1M3': (33, 324, 40, 8), 'D_E1M4': (326, 598, 72, 14),
        'D_E1M5': (494, 0, 23, 6), 'D_E1M6': (389, 296, 94, 12),
        'D_E1M7': (422, 6, 35, 7), 'D_E1M8': (148, 203, 24, 7),
        'D_E1M9': (1426, 756, 60, 14), 'D_INTER': (899, 887, 88, 15),
        'D_INTRO': (13, 27, 38, 8), 'D_VICTOR': (795, 299, 48, 11),
        'D_INTROA': (4, 24, 35, 5)},
}
METRICS = ('steals', 'drum steals', 'writes/s', 'p99')
DESIGN_STREAM_BYTES = {'native12': 141293, 'mb6': 126506}


@needs_wad
class AllSongs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wad = mus.Wad.open()
        instruments = mus2ay.load_instruments(wad)
        cls.results = {}
        for layout in ('native12', 'mb6'):
            machine = tables.LAYOUT_MACHINES[layout][0]
            for name in mus.UPSTREAM_SONGS:
                song = wad.song(name)
                song_file, stats = mus2ay.convert(song, instruments, layout)
                init, bursts = player.run(song_file, machine)
                cls.results[layout, name] = (song, song_file, stats, init,
                                             bursts)

    def test_stream_is_well_formed(self):
        for (layout, name), (song, song_file, stats, _, _) in \
                self.results.items():
            with self.subTest(layout=layout, song=name):
                lay = tables.LAYOUTS[layout]
                nm = len(lay.melodic)
                data = song_file.to_bytes()
                self.assertEqual(player.SongFile.from_bytes(data).stream,
                                 song_file.stream)
                cmds = player.decode_stream(song_file.stream)
                self.assertEqual(cmds[-1][0], song.length_ticks)
                for _, c, v, ops in cmds[:-1]:
                    if c <= 2:
                        self.assertLess(v, nm)
                        self.assertLessEqual(ops[0], 127)
                    if c in (1, 2):
                        self.assertLessEqual(ops[1], tables.ATT_MAX)
                    if c == 2:
                        self.assertLess(ops[2], len(song_file.envelopes))
                    if c == 4:
                        self.assertLessEqual(ops[0], tables.ATT_MAX)
                    if c == 6:
                        self.assertGreaterEqual(v, nm)
                        self.assertLess(v, nm + len(lay.drums))
                        self.assertLess(ops[0], len(song_file.drums))
                        self.assertLessEqual(ops[1], tables.ATT_MAX)
                self.assertLessEqual(stats['max voices'], nm)
                self.assertEqual(stats['notes'] + stats['drum hits'],
                                 song.counts()['on'])

    def test_register_writes_are_in_range(self):
        for (layout, name), (_, _, _, init, bursts) in self.results.items():
            with self.subTest(layout=layout, song=name):
                lay = tables.LAYOUTS[layout]
                owned = tables.owned_registers(lay)
                for chip, reg, value in init:
                    self.assertIn(chip, lay.chips)
                    self.assertLess(reg, 13)
                for burst in bursts:
                    for chip, reg, value in burst:
                        self.assertIn(reg, owned[chip])
                        self.assertLessEqual(value, 255)
                        if reg in (1, 3, 5):             # periods: 12 bits
                            self.assertLessEqual(value, 15)
                        elif reg == 6:
                            self.assertLessEqual(value, 31)
                        elif reg in (8, 9, 10):          # 4-bit levels
                            self.assertTrue(value <= 15 or value == 0x10)
                        elif reg == 13:
                            self.assertEqual(value, 0)

    def test_at_most_the_layout_voices_sound(self):
        for (layout, name), (_, song_file, _, _, _) in self.results.items():
            with self.subTest(layout=layout, song=name):
                machine = tables.LAYOUT_MACHINES[layout][0]
                p = player.Player(song_file, machine)
                p.reset()
                lay = tables.LAYOUTS[layout]
                music = set(tables.voices(lay))
                for _ in range(int(60 * tables.vbl_hz(machine))):
                    p.interrupt()
                    sounding = [(c, ch) for c in lay.chips for ch in range(3)
                                if p.want[c][8 + ch]]
                    self.assertTrue(set(sounding) <= music)

    def test_against_the_design(self):
        for (layout, name), (_, _, stats, _, bursts) in self.results.items():
            machine = tables.LAYOUT_MACHINES[layout][0]
            b = report.burst_stats(bursts, machine)
            got = dict(zip(METRICS, (stats['steals'], stats['drum steals'],
                                     round(b['writes_s']), b['p99_busy'])))
            for metric, design in zip(METRICS, DESIGN[layout][name]):
                with self.subTest(layout=layout, song=name, metric=metric):
                    self.assertLessEqual(got[metric], design)
        for layout, total in DESIGN_STREAM_BYTES.items():
            got = sum(len(r[1].stream) for (lay, _), r in
                      self.results.items() if lay == layout)
            self.assertLessEqual(got, total)


if __name__ == '__main__':
    unittest.main()
