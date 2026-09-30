"""Tests of tools/sound/mus2ay.py (the converter) and genmidi.py: rules on
hand-made songs, then invariants and the design's figures on the WAD's
13 songs (skipped without build/)."""

import struct
import unittest
from collections import Counter

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


# A song with what the WAD's songs never use: a note of volume 0,
# expression, system events 10, 11 and 14 (on a melodic channel and on
# channel 15), and a carrier level (score() pairs: the delay after, the
# event). test_sound_decoders checks the converter on it too.
EDGE_CASES = (
    (0, [0x40, 0, 4]),                   # program 4: level 10
    (0, [0x40, 5, 90]),                  # expression 90
    (0, [0x10, 0x80 | 60, 100]),         # 60, velocity 100
    (0, [0x10, 64]),                     # 64, velocity 100 again
    (0, [0x11, 0x80 | 50, 70]),
    (0, [0x1f, 0x80 | 36, 110]),         # a drum
    (2, [0x20, 90]),                     # bend channel 0
    (0, [0x10, 0x80 | 64, 0]),           # 64 at volume 0: off
    (1, [0x40, 3, 60]),                  # volume of channel 0
    (1, [0x30, 14]),                     # reset: expression, bend
    (1, [0x31, 11]),                     # all notes off, channel 1
    (0, [0x11, 0x80 | 52, 127]),
    (1, [0x3f, 10]),                     # all sounds off, drums
    (1, [0x30, 10]),                     # all sounds off, channel 0
    (0, [0x10, 0x80 | 67, 80]),
    (0, [0x4f, 3, 50]),                  # drum channel volume
    (2, [0x1f, 0x80 | 42, 127]),
    (1, [0x3f, 14]))                     # reset on channel 15


def convert(lump, gain=0):
    """The converter at a song gain of 0 by default: the tests of the
    loudness law, the stream and the voices check the attenuations as
    the law gives them; the class Gain tests the song gain."""
    return mus2ay.convert(mus.parse(lump), INSTRUMENTS, gain=gain)


def note_attenuations(song_file):
    """[(tick, voice, note or drum recipe, attenuation)] of every note on
    and drum hit of a stream, the attenuation being the one the player
    holds for it (a short note on keeps the voice's)."""
    att = {}
    out = []
    for tick, c, v, ops in player.decode_stream(song_file.stream):
        if c in (player.NOTE_ATT, player.NOTE_ATT_ENV):
            att[v] = ops[1]
        elif c == player.ATTENUATION:
            att[v] = ops[0]
        if c <= player.NOTE_ATT_ENV:
            out.append((tick, v, ops[0], att.get(v, 0)))
        elif c == player.DRUM_HIT:
            out.append((tick, v, ops[0] | 0x100, ops[1]))
    return out


def check_gained(test, plain, shipped, gain):
    """note_attenuations of a song at gain 0 (`plain`) and at `gain`: the
    same notes and hits on the same voices at the same ticks, each at its
    gain-0 attenuation less the gain when that sounds; a silent one (80)
    stays silent or, when its terms add up to 80 or more without one
    being silent, sounds at 80 - gain to 79."""
    test.assertEqual([x[:3] for x in shipped], [x[:3] for x in plain])
    for (t, v, n, a), (_, _, _, b) in zip(plain, shipped):
        if a < tables.ATT_MAX:
            test.assertEqual(b, max(0, a - gain), (t, v, n))
        else:
            test.assertTrue(b == tables.ATT_MAX or
                            tables.ATT_MAX - gain <= b < tables.ATT_MAX,
                            (t, v, n, b))


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
        # on NTSC the same 160 ms: 0.16 x 2040968 / 256 = 1275.6 -> 1276
        self.assertEqual(mus2ay.drum_recipe(36, tables.NTSC_NATIVE),
                         (33, 0, 1276, 914))
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

    def test_steal_keeps_the_bass_on_the_lowest_voice(self):
        # at tick 0 channel 0 plays 60 on voice 0 and channel 1 plays 40
        # on voice 1; 60 is released at tick 1 and voice 0 is free again
        # at tick 5. Then, at tick 5, channels 2-6 (program 4, another
        # envelope, so voice 0 is not preferred) take 50-54 on voices 2-6,
        # and channel 0 plays 40 on voice 0, the last idle one. An eighth
        # note, at tick 6, steals: of the two basses the one on voice 0 is
        # kept although it is newer, and each channel holds one voice, so
        # the oldest other note goes: 40 of channel 1, voice 1.
        events = [(0, [0x40 | c, 0, 4]) for c in range(2, 7)]
        events += [(0, [0x10, 60]), (1, [0x11, 40]), (4, [0x00, 60])]
        events += [(0, [0x10 | c, 48 + c]) for c in range(2, 7)]
        events += [(1, [0x10, 40]), (0, [0x17, 70])]
        song_file, stats = convert(score(*events))
        ons = [(v, ops[0]) for _, c, v, ops in commands(song_file) if c <= 2]
        self.assertEqual(ons, [(0, 60), (1, 40), (2, 50), (3, 51), (4, 52),
                               (5, 53), (6, 54), (0, 40), (1, 70)])
        self.assertEqual(stats['steals'], 1)
        self.assertEqual(stats['release cuts'], 0)

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


class Gain(unittest.TestCase):
    """The song gain: its statistic, the boost, the cap, the clamp at 0,
    silence kept, a quiet sum gained rather than muted, drums gained in
    attenuation (not in balance: a loud hit goes to the chip's envelope),
    and the gained attenuations in the stream."""

    def probe(self, lump):
        converter = mus2ay.Converter(mus.parse(lump), INSTRUMENTS)
        converter.convert()
        return converter.loudness

    def test_attenuation(self):
        att = mus2ay.attenuation
        self.assertEqual(att((5,), 10), 0)               # clamped at 0
        self.assertEqual(att((30,), 10), 20)
        self.assertEqual(att((79,), 24), 55)
        self.assertEqual(att((12,)), 12)
        self.assertEqual(att((8, 15, 0, 24)), 47)       # the sum of terms
        # a sum of 80 or more: silent at gain 0, gained from the sum
        self.assertEqual(att((40, 40)), tables.ATT_MAX)
        self.assertEqual(att((40, 40), 21), 59)
        self.assertEqual(att((60, 50), 30), tables.ATT_MAX)
        self.assertEqual(att((60, 40), 30), 70)
        self.assertEqual(att((50, 50), 10), tables.ATT_MAX)
        # one term silent by itself (a value of 12 or less, volume 0):
        # silent whatever the gain
        self.assertEqual(tables.ATTENUATION_OF_VALUE[12], tables.ATT_MAX)
        self.assertLess(tables.ATTENUATION_OF_VALUE[13], tables.ATT_MAX)
        self.assertEqual(att((0, 0, tables.ATT_MAX, 0), 24), tables.ATT_MAX)
        self.assertEqual(att((tables.ATT_MAX,), 24), tables.ATT_MAX)

    def test_statistic(self):
        # 1% of the held time at 2, the rest at 10: the 99th percentile
        # is 2; half a percent at 2: it is 10
        loud = mus2ay.loud_attenuation
        self.assertEqual(loud(Counter({2: 1, 10: 99})), 2)
        self.assertEqual(loud(Counter({2: 1, 10: 199})), 10)
        self.assertEqual(loud(Counter({2: 1, 10: 199}), 0.995), 2)
        self.assertEqual(loud(Counter({2: 1, 10: 199}), 0.5), 10)
        # silent attenuations and empty entries do not count
        self.assertEqual(loud(Counter({0: 0, 10: 5, 80: 1000})), 10)
        self.assertIsNone(loud(Counter({80: 10})))
        self.assertIsNone(loud(Counter()))

    def test_boost_and_cap(self):
        gain = mus2ay.song_gain
        self.assertEqual((mus2ay.PERCENTILE, mus2ay.BOOST, mus2ay.CAP),
                         (0.99, 6, 24))
        self.assertEqual(gain(Counter({10: 100})), 16)          # 10 + 6
        self.assertEqual(gain(Counter({10: 100}), boost=0), 10)
        self.assertEqual(gain(Counter({30: 100})), 24)          # capped
        self.assertEqual(gain(Counter({30: 100}), cap=40), 36)
        self.assertEqual(gain(Counter({0: 100})), 6)            # boost only
        self.assertEqual(gain(Counter()), 6)                    # no notes

    def test_held_time_weights_and_one_stray_loud_note(self):
        # 60 at velocity 127 (0 units) held 2 ticks, then 62 at velocity
        # 100 (8 units) held 400: the loud note is 0.5% of the held time,
        # so the statistic is 8 and the gain 8 + 6 = 14; both notes are
        # clamped at 0
        lump = score((2, [0x10, 0x80 | 60, 127]), (0, [0x00, 60]),
                     (400, [0x10, 0x80 | 62, 100]), (0, [0x00, 62]))
        self.assertEqual(self.probe(lump), Counter({0: 2, 8: 400}))
        song_file, stats = mus2ay.convert(mus.parse(lump), INSTRUMENTS)
        self.assertEqual(stats['gain'], 14)
        self.assertEqual([a for _, _, _, a in note_attenuations(song_file)],
                         [0, 0])
        # held 10 ticks it is 2.4% of the time: the statistic is 0, the
        # gain the boost alone, and 62 is 2 units down
        lump = score((10, [0x10, 0x80 | 60, 127]), (0, [0x00, 60]),
                     (400, [0x10, 0x80 | 62, 100]), (0, [0x00, 62]))
        song_file, stats = mus2ay.convert(mus.parse(lump), INSTRUMENTS)
        self.assertEqual(stats['gain'], 6)
        self.assertEqual([a for _, _, _, a in note_attenuations(song_file)],
                         [0, 2])

    def test_volume_changes_split_the_held_time(self):
        # velocity 127 held 100 ticks, the channel volume at 64 (24 units)
        # from tick 40; a note shorter than a tick counts 1
        lump = score((40, [0x10, 0x80 | 60, 127]), (60, [0x40, 3, 64]),
                     (0, [0x00, 60]), (0, [0x10, 0x80 | 62, 127]),
                     (0, [0x00, 62]))
        self.assertEqual(self.probe(lump), Counter({0: 40, 24: 61}))

    def test_cap_and_drums_gained_in_attenuation(self):
        # melody at velocity 20 (64 units): gain 64 + 6, capped at 24; a
        # drum at velocity 64 (24 units) goes to 0, a drum at 20 to 40,
        # the melody's gain in attenuation. Not in balance: the first hit,
        # soft at gain 0 (24 > HW_DRUM_ATT), now plays on the chip's
        # envelope from full level, and a hit already there could not get
        # louder (report.peak_changes measures this by song)
        lump = score((0, [0x10, 0x80 | 60, 20]), (0, [0x1f, 0x80 | 36, 64]),
                     (100, [0x1f, 0x80 | 42, 20]), (0, [0x00, 60]))
        song_file, stats = mus2ay.convert(mus.parse(lump), INSTRUMENTS)
        self.assertEqual(stats['gain'], 24)
        self.assertEqual([(v, a) for _, v, _, a in
                          note_attenuations(song_file)],
                         [(0, 40), (7, 0), (8, 40)])
        self.assertEqual(stats['soft drum hits'], 1)
        # at gain 0 both hits are soft
        self.assertEqual(convert(lump)[1]['soft drum hits'], 2)

    def test_silence_stays_silent(self):
        # channel volume 0: 80 units whatever the gain, and no sounding
        # note, so the gain is the boost
        lump = score((0, [0x40, 3, 0]), (10, [0x10, 60]), (0, [0x00, 60]))
        song_file, stats = mus2ay.convert(mus.parse(lump), INSTRUMENTS)
        self.assertEqual(stats['gain'], mus2ay.BOOST)
        self.assertEqual(note_attenuations(song_file)[0][3], tables.ATT_MAX)
        self.assertEqual(stats['silent notes'], 1)

    def test_a_quiet_sum_is_gained_not_muted(self):
        # velocity 127 while the channel volume falls: 40 (40 units) with
        # expression 40 (40 units) sums to 80, silent at gain 0; with a
        # gain of 20 it is 60, an audible level, not muted. Volume 0 mutes
        # it whatever the gain.
        lump = score((0, [0x40, 5, 40]), (0, [0x40, 3, 40]),
                     (10, [0x10, 0x80 | 60, 127]), (10, [0x40, 3, 0]),
                     (10, [0x00, 60]))
        for gain, first, last in ((0, 80, None), (20, 60, 80)):
            song_file, stats = convert(lump, gain)
            self.assertEqual(note_attenuations(song_file)[0][3], first)
            changes = [ops[0] for _, c, _, ops in
                       player.decode_stream(song_file.stream)
                       if c == player.ATTENUATION]
            self.assertEqual(changes, [last] if last else [])
            self.assertEqual(stats['silent notes'], int(first == 80))

    def test_a_fixed_gain(self):
        lump = score((10, [0x10, 0x80 | 60, 64]), (0, [0x00, 60]))
        for gain, want in ((0, 24), (10, 14), (30, 0)):
            song_file, stats = convert(lump, gain)
            self.assertEqual(stats['gain'], gain)
            self.assertEqual(note_attenuations(song_file)[0][3], want)

    def test_the_stream_holds_the_gained_attenuations(self):
        # the edge-case song of test_sound_decoders: every note on and
        # drum hit carries its gain-0 attenuation less the gain, the same
        # voices and notes; a volume change is sent when the gained level
        # moves (test_sound_decoders checks each attenuation against its
        # terms, silent sums included)
        lump = score(*EDGE_CASES)
        plain, plain_stats = convert(lump)
        song_file, stats = mus2ay.convert(mus.parse(lump), INSTRUMENTS)
        gain = stats['gain']
        self.assertGreater(gain, 0)
        check_gained(self, note_attenuations(plain),
                     note_attenuations(song_file), gain)
        for key in ('notes', 'drum hits', 'steals', 'drum steals', 'cuts'):
            self.assertEqual(stats[key], plain_stats[key], key)


# The design's figures (build/native-design/sound/summary50.md, the
# tables of docs/research/native-sound.md 3.3 and 4.2), native12, the only
# layout since the 6-voice fallback was removed (NATIVE.md 15.1, row 11):
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
}
METRICS = ('steals', 'drum steals', 'writes/s', 'p99')
DESIGN_STREAM_BYTES = {'native12': 141293}
# Excesses over DESIGN of the songs as shipped, accepted:
# {song: {metric: (figure allowed, the reason)}}.
_LOUDER = ('the song gain (2026-09-30), for the owner\'s "Volume is a '
           'little low": louder notes cross more AY levels as they fade '
           'and more drum hits start on the envelope; the bus cost stays '
           'inside the design\'s range (test_the_song_gain)')
DESIGN_WITH_GAIN = {
    'D_E1M2': {'p99': (15, _LOUDER)},
    'D_E1M3': {'writes/s': (104, _LOUDER)},
    'D_E1M5': {'writes/s': (55, _LOUDER)},
    'D_E1M6': {'p99': (17, _LOUDER)},
    'D_E1M7': {'writes/s': (50, _LOUDER)},
    'D_E1M9': {'writes/s': (129, _LOUDER)},
    'D_VICTOR': {'p99': (15, _LOUDER)},
}
# The song gains of mus2ay.convert, attenuation units of 0.5 dB, in
# mus.UPSTREAM_SONGS order (tools/sound/README.md, "The song gain").
SONG_GAINS = dict(zip(mus.UPSTREAM_SONGS,
                      (17, 14, 21, 17, 15, 18, 14, 21, 14, 14, 6, 12, 14)))
# The design's range of the music's bus cost, ms a second (native-sound.md
# 4.2: "music costs 11.5 to 27.5 ms a second" on F1.2.1 with window 512;
# 0.39 to 1.20 with FW-S1).
DESIGN_MS_F121 = 27.5
DESIGN_MS_FWS1 = 1.20


@needs_wad
class AllSongs(unittest.TestCase):
    """The WAD's songs as shipped (each with its song gain), and at gain 0
    (`plain`), the loudness the design's figures were measured at."""

    @classmethod
    def setUpClass(cls):
        wad = mus.Wad.open()
        instruments = mus2ay.load_instruments(wad)
        cls.results = {}
        cls.plain = {}
        layout = tables.NATIVE12.name
        for name in mus.UPSTREAM_SONGS:
            song = wad.song(name)
            for results, gain in ((cls.results, None), (cls.plain, 0)):
                song_file, stats = mus2ay.convert(song, instruments, gain)
                init, bursts = player.run(song_file, tables.PAL_NATIVE)
                results[layout, name] = (song, song_file, stats, init,
                                         bursts)
            probe = mus2ay.Converter(song, instruments)
            probe.convert()
            cls.plain[layout, name] += (probe.loudness,)

    def test_stream_is_well_formed(self):
        for (layout, name), (song, song_file, stats, _, _) in \
                self.results.items():
            with self.subTest(layout=layout, song=name):
                lay = tables.NATIVE12
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
                lay = tables.NATIVE12
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
                machine = tables.PAL_NATIVE
                p = player.Player(song_file, machine)
                p.reset()
                lay = tables.NATIVE12
                music = set(tables.voices(lay))
                for _ in range(int(60 * tables.vbl_hz(machine))):
                    p.interrupt()
                    sounding = [(c, ch) for c in lay.chips for ch in range(3)
                                if p.want[c][8 + ch]]
                    self.assertTrue(set(sounding) <= music)

    def check_design(self, results, allowed):
        machine = tables.PAL_NATIVE
        for (layout, name), result in results.items():
            stats, bursts = result[2], result[4]
            b = report.burst_stats(bursts, machine)
            got = dict(zip(METRICS, (stats['steals'], stats['drum steals'],
                                     round(b['writes_s']), b['p99_busy'])))
            for metric, design in zip(METRICS, DESIGN[layout][name]):
                limit = allowed.get(name, {}).get(metric, (design,))[0]
                with self.subTest(layout=layout, song=name, metric=metric):
                    self.assertLessEqual(got[metric], limit)
        for layout, total in DESIGN_STREAM_BYTES.items():
            got = sum(len(r[1].stream) for (lay, _), r in
                      results.items() if lay == layout)
            self.assertLessEqual(got, total)

    def test_against_the_design(self):
        """The songs as shipped, each with its song gain, against the
        design's figures, with no exception but the accepted ones
        (DESIGN_WITH_GAIN): the gain raises writes a second in D_E1M3,
        D_E1M5, D_E1M7 and D_E1M9 and the p99 of bursts in D_E1M2, D_E1M6
        and D_VICTOR above the design's (tools/sound/README.md, "The song
        gain")."""
        self.check_design(self.results, DESIGN_WITH_GAIN)

    def test_against_the_design_at_gain_0(self):
        """The converter's rules at the loudness the design's figures were
        measured at: the songs at gain 0, byte for byte those of the
        converter before the gain."""
        self.check_design(self.plain, {})

    def test_the_song_gain(self):
        """Each shipped song: its gain (pinned in SONG_GAINS) is the
        statistic's plus the boost, within the cap; every note and drum
        hit holds its gain-0 attenuation less the gain (check_gained); the
        voices are the same (steals, drum steals, release cuts); and the
        bus cost stays inside the design's range."""
        machine = tables.PAL_NATIVE
        for key, (_, song_file, stats, _, bursts) in self.results.items():
            _, plain, plain_stats, _, _, loudness = self.plain[key]
            with self.subTest(song=key[1]):
                gain = stats['gain']
                self.assertEqual(gain, SONG_GAINS[key[1]])
                loud = mus2ay.loud_attenuation(loudness)
                self.assertEqual(gain, min(mus2ay.CAP, loud + mus2ay.BOOST))
                check_gained(self, note_attenuations(plain),
                             note_attenuations(song_file), gain)
                for count in ('notes', 'drum hits', 'steals', 'drum steals',
                              'release cuts', 'max voices', 'lost offs'):
                    self.assertEqual(stats[count], plain_stats[count], count)
                b = report.burst_stats(bursts, machine)
                self.assertLessEqual(b['f121_ms'], DESIGN_MS_F121)
                self.assertLessEqual(b['fws1_ms'], DESIGN_MS_FWS1)
        self.assertEqual(set(SONG_GAINS), set(mus.UPSTREAM_SONGS))

if __name__ == '__main__':
    unittest.main()
