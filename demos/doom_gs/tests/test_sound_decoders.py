"""The independent check of S1: a second decoder of MUS (mus2mid.py, a MUS
to MIDI converter, read back by midi.py, a MIDI reader) against mus.py,
and the converter's stream against the second decoder.

The second decoder shares no MUS-reading code with mus.py or mus2ay.py.
The WAD tests skip when build/ has no DOOM1.WAD.
"""

import math
import struct
import unittest
from collections import Counter, defaultdict

import support  # noqa: F401  (puts tools/ on the path)
from sound import midi, mus, mus2ay, mus2mid, player, tables
from test_sound_mus import EVERY_EVENT, make_mus, needs_wad


def mus_events(song):
    """mus.py's events as comparable tuples."""
    out = []
    for e in song.events:
        chan = 0 if e.kind == 'end' else e.chan
        out.append((e.tick, e.kind, chan, e.a, e.b))
    return out


def midi_events(lump):
    """The second decoder: MUS -> MIDI file -> MIDI reader."""
    file_format, division, events = midi.read(mus2mid.convert(lump))
    assert (file_format, division) == (0, mus2mid.TICKS_PER_QUARTER)
    return midi.as_mus_events(events)


class SecondDecoderHandMade(unittest.TestCase):
    def test_every_event_type_agrees(self):
        lump = make_mus(EVERY_EVENT)
        self.assertEqual(midi_events(lump), mus_events(mus.parse(lump)))

    def test_channels_map_both_ways(self):
        score = []
        for chan in range(16):
            score += [0x10 | chan, 0x80 | 40, 50 + chan]
        score += [0x60]
        lump = make_mus(score)
        self.assertEqual(midi_events(lump), mus_events(mus.parse(lump)))
        _, _, raw = midi.read(mus2mid.convert(lump))
        channels = [e[3] for e in raw if e[2] == 'note_on']
        self.assertEqual(channels, [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12,
                                    13, 14, 15, 9])

    def test_tempo_is_140_ticks_a_second(self):
        _, division, raw = midi.read(mus2mid.convert(make_mus([0x60])))
        tempo = [e[4][1] for e in raw if e[2] == 'meta' and e[4][0] == 0x51]
        self.assertEqual(int.from_bytes(tempo[0], 'big') / division, 1e6 / 140)


class MidiReader(unittest.TestCase):
    def smf(self, *tracks, file_format=1):
        out = b'MThd' + struct.pack('>IHHH', 6, file_format, len(tracks), 96)
        for t in tracks:
            out += b'MTrk' + struct.pack('>I', len(t)) + t
        return out

    def test_running_status_and_merge(self):
        a = bytes([0x00, 0x90, 60, 100, 0x10, 62, 100, 0x00, 0xff, 0x2f, 0])
        b = bytes([0x10, 0xb3, 7, 90, 0x00, 0xe3, 0x00, 0x40,
                   0x00, 0xff, 0x2f, 0])
        _, _, events = midi.read(self.smf(a, b))
        self.assertEqual([(e[0], e[2], e[3], e[4]) for e in events
                          if e[2] != 'meta'],
                         [(0, 'note_on', 0, (60, 100)),
                          (16, 'note_on', 0, (62, 100)),
                          (16, 'controller', 3, (7, 90)),
                          (16, 'bend', 3, (0, 64))])

    def test_note_on_with_velocity_0_is_a_note_off(self):
        t = bytes([0x00, 0x90, 60, 0, 0x00, 0xff, 0x2f, 0])
        _, _, events = midi.read(self.smf(t, file_format=0))
        self.assertEqual(midi.as_mus_events(events)[0], (0, 'off', 0, 60, 0))

    def test_errors(self):
        with self.assertRaises(midi.MidiError):
            midi.read(b'RIFF' + bytes(10))
        with self.assertRaises(midi.MidiError):     # data without status
            midi.read(self.smf(bytes([0x00, 60, 100])))
        with self.assertRaises(midi.MidiError):     # truncated message
            midi.read(self.smf(bytes([0x00, 0x90, 60])))
        with self.assertRaises(midi.MidiError):     # track count
            midi.read(self.smf(b'')[:-8])


@needs_wad
class SecondDecoderOnTheWad(unittest.TestCase):
    def test_all_songs_agree(self):
        wad = mus.Wad.open()
        for name in mus.UPSTREAM_SONGS:
            with self.subTest(song=name):
                lump = wad.lump(name)
                first = mus_events(mus.parse(lump, name))
                second = midi_events(lump)
                self.assertEqual(len(first), len(second))
                self.assertEqual(first, second)


def stream_by_tick(song_file):
    """{tick: [(command, voice, operands)]} of a song file's stream."""
    out = defaultdict(list)
    for tick, command, voice, operands in player.decode_stream(
            song_file.stream):
        out[tick].append((command, voice, operands))
    return out


def expected_note(instrument, note):
    if instrument.fixed:
        return instrument.fixed_note
    return min(127, max(0, note + instrument.note_offset))


def carrier_att(instrument):
    """GENMIDI's carrier level, 0.75 dB a step, in 0.5 dB units rounded
    half up."""
    return math.floor(instrument.level * 1.5 + 0.5)


def check_converter(test, lump, name, instruments, gain=None):
    """The converter's stream for one lump, as shipped (the song gain of
    mus2ay.convert, or `gain`), against the second decoder's events: every
    note on (tick, note, attenuation, envelope), note off, pitch bend,
    attenuation change, cut and drum hit (tick, recipe, attenuation) is
    what the MUS events ask for, at their tick. An attenuation is the sum
    of the General MIDI law's terms less the song gain the converter
    reports, 0 to 80, and 80 (silent) when one term is 80 by itself (a
    value of 12 or less, volume 0 included)."""
    A = tables.ATTENUATION_OF_VALUE
    events = midi_events(lump)
    song_file, stats = mus2ay.convert(mus.parse(lump, name), instruments,
                                      gain)
    song_gain = stats['gain']
    if gain is not None:
        test.assertEqual(song_gain, gain)
    machine = tables.PAL_NATIVE
    stream = stream_by_tick(song_file)
    n_melodic = len(tables.NATIVE12.melodic)

    def loud(chan):
        return (A[volume[chan]], A[expression[chan]])

    def att(*terms):
        """The stream's attenuation of the law's terms."""
        if max(terms) >= tables.ATT_MAX:
            return tables.ATT_MAX
        return min(tables.ATT_MAX, max(0, sum(terms) - song_gain))

    # The second decoder's view, tick by tick.
    program = [0] * 16
    bend = [128] * 16
    volume = [127] * 16
    expression = [127] * 16
    on = defaultdict(Counter)        # tick -> (note, att, envelope)
    origin = defaultdict(set)        # (tick, note, att, envelope) ->
    #                                  (channel, (velocity, carrier att))
    drums = defaultdict(Counter)     # tick -> (recipe, att)
    offs = defaultdict(Counter)      # tick -> mapped notes released
    bends = defaultdict(set)         # (tick, chan) -> values allowed
    louds = defaultdict(set)         # (tick, chan) -> channel att allowed
    loud_at_end = {}                 # (tick, chan) -> channel att after
    cuts = defaultdict(set)          # tick -> channels cut
    held = {}                        # (chan, note) -> mapped note
    end_tick = None
    melodic_offs = 0
    for tick, kind, chan, a, b in events:
        if kind == 'on' and chan == 15:
            recipe = mus2ay.drum_recipe(a, machine)
            drums[tick][recipe, att(A[b], *loud(15))] += 1
        elif kind == 'on':
            ins = instruments[program[chan]]
            n = expected_note(ins, a)
            base = (A[b], carrier_att(ins))
            key = (n, att(*base, *loud(chan)),
                   mus2ay.envelope_of(ins))
            on[tick][key] += 1
            origin[(tick,) + key].add((chan, base))
            held[chan, a] = n
            bends[tick, chan].add(bend[chan])
        elif kind == 'off' and chan != 15:
            melodic_offs += 1
            if (chan, a) in held:
                offs[tick][held.pop((chan, a))] += 1
        elif kind == 'bend' and chan != 15:
            bends[tick, chan].add(bend[chan])
            bend[chan] = a
            bends[tick, chan].add(a)
        elif kind == 'ctrl' and a == 0:
            program[chan] = b
        elif kind == 'ctrl' and a in (3, 5):
            if a == 3:
                volume[chan] = b
            else:
                expression[chan] = b
            louds[tick, chan].add(loud(chan))
            loud_at_end[tick, chan] = loud(chan)
        elif kind == 'sys' and a == 10:
            cuts[tick].add(chan)
            for key in [k for k in held if k[0] == chan]:
                del held[key]
        elif kind == 'sys' and a == 11:
            for key in [k for k in held if k[0] == chan]:
                offs[tick][held.pop(key)] += 1
        elif kind == 'sys' and a == 14:
            expression[chan] = 127
            louds[tick, chan].add(loud(chan))
            loud_at_end[tick, chan] = loud(chan)
            bends[tick, chan].update((bend[chan], 128))
            bend[chan] = 128
        elif kind == 'end':
            end_tick = tick

    # The stream, with the voice state the player keeps.
    voice_note, voice_att, voice_env = {}, {}, {}
    voice_origin = {}                # voice -> (chan, base) when known
    voice_held = set()
    stream_offs = 0
    test.assertEqual(max(stream), end_tick)
    loud_ticks = defaultdict(list)
    for tick, chan in loud_at_end:
        loud_ticks[tick].append(chan)
    for tick in sorted(set(stream) | set(on) | set(drums) | set(loud_ticks)):
        commands = stream.get(tick, [])
        got_on = Counter()
        got_drums = Counter()
        released = Counter()
        for command, v, ops in commands:
            if command == player.END:
                continue
            if command == player.DRUM_HIT:
                test.assertGreaterEqual(v, n_melodic)
                got_drums[tuple(song_file.drums[ops[0]]), ops[1]] += 1
                continue
            if command == player.CUT:
                voice_held.discard(v)
                chan = 15 if v >= n_melodic else voice_origin.get(
                    v, (None,))[0]
                test.assertTrue(cuts[tick] and (chan is None or
                                                chan in cuts[tick]),
                                '%s cut at tick %d' % (name, tick))
                continue
            test.assertLess(v, n_melodic)
            if command <= player.NOTE_ATT_ENV:
                if command >= player.NOTE_ATT:
                    voice_att[v] = ops[1]
                if command == player.NOTE_ATT_ENV:
                    voice_env[v] = tuple(song_file.envelopes[ops[2]])
                key = (ops[0], voice_att[v], voice_env[v])
                got_on[key] += 1
                voice_note[v] = ops[0]
                voice_held.add(v)
                sources = origin.get((tick,) + key, set())
                voice_origin[v] = next(iter(sources)) \
                    if len(sources) == 1 else (None, None)
            elif command == player.NOTE_OFF:
                voice_held.discard(v)
                stream_offs += 1
                released[voice_note[v]] += 1
            elif command == player.BEND:
                chan = voice_origin[v][0]
                if chan is not None:
                    test.assertIn(ops[0], bends.get((tick, chan), set()),
                                  '%s bend at tick %d' % (name, tick))
            elif command == player.ATTENUATION:
                voice_att[v] = ops[0]
                chan, base = voice_origin[v]
                if chan is None:
                    test.assertTrue(any(t == tick for t, _ in louds),
                                    '%s volume at tick %d' % (name, tick))
                else:
                    allowed = {att(*base, *x)
                               for x in louds.get((tick, chan), ())}
                    test.assertIn(ops[0], allowed, '%s attenuation at '
                                  'tick %d' % (name, tick))
        # after a volume change, every held note of the channel has the
        # AY level of its new attenuation (the converter sends a change
        # only when the level moves)
        for chan in loud_ticks.get(tick, ()):
            for v in voice_held:
                c, base = voice_origin[v]
                if c == chan:
                    want = att(*base, *loud_at_end[tick, chan])
                    test.assertEqual(tables.LEVEL[voice_att[v]],
                                     tables.LEVEL[want],
                                     '%s level of voice %d at tick %d'
                                     % (name, v, tick))
        test.assertEqual(got_on, on.get(tick, Counter()),
                         '%s note ons at tick %d' % (name, tick))
        test.assertEqual(got_drums, drums.get(tick, Counter()),
                         '%s drums at tick %d' % (name, tick))
        if tick != end_tick:
            allowed = offs.get(tick, Counter())
            test.assertTrue(all(released[n] <= allowed[n] for n in released),
                            '%s note offs at tick %d' % (name, tick))
    test.assertEqual(stream_offs, melodic_offs - stats['lost offs']
                     + stats['offs at the end'] + stats['released by 11'])
    test.assertEqual(sum(sum(c.values()) for c in on.values()),
                     stats['notes'])
    return stats


class ConverterAgainstSecondDecoderHandMade(unittest.TestCase):
    """The same check on a hand-made song with what the WAD's songs never
    use: a note of volume 0, expression, system events 10, 11 and 14
    (on a melodic channel and on channel 15), and a carrier level."""

    def test_edge_cases(self):
        from test_sound_mus2ay import EDGE_CASES, INSTRUMENTS, score
        lump = score(*EDGE_CASES)
        for gain in (None, 0, 30):
            with self.subTest(gain=gain):
                stats = check_converter(self, lump, 'hand-made',
                                        INSTRUMENTS, gain)
                self.assertEqual(stats['cuts'], 2)
                self.assertEqual(stats['released by 11'], 1)
                self.assertEqual(stats['notes'], 5)


@needs_wad
class ConverterAgainstSecondDecoder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wad = mus.Wad.open()
        cls.instruments = mus2ay.load_instruments(cls.wad)

    def check(self, name):
        check_converter(self, self.wad.lump(name), name, self.instruments)

    def test_native12(self):
        for name in mus.UPSTREAM_SONGS:
            with self.subTest(song=name):
                self.check(name)

if __name__ == '__main__':
    unittest.main()
