"""Tests of milestone S2: the 65C02 music player (src/sound) on a2vm,
against the player model tools/sound/player.py, and the a2vm additions it
needs (the AY log, the slot-4 slowdown).

  - the player's tables, read back from the assembled player, equal
    tools/sound/tables.py;
  - every song of the WAD (the layout native12, the only one): the AY
    writes after every interrupt equal player.py's, 60 s on a PAL //e and
    20 s on NTSC;
  - random streams that use every command, voice and edge (bends at both
    ends, attenuations past 80, envelopes that carry, a loop offset inside
    the stream), against player.py;
  - the ring: a refill across the end of a looping song longer than the
    ring, an underrun and its recovery, a stop, a song started while
    another plays, a song that ends, a refused start; against RingPlayer
    (player.Player through the ring, tools/sound/run65.py);
  - every run also checks the chips' registers at its end against the
    model's shadow, that the chips are reset only by snd_init, and that
    the interrupt reads and writes only the zero page, the stack, the
    mouse card, the Phasor and the language card (a2vm --irq-bounds);
  - the probe answers SND_MUSIC on the Phasor, and the songs play after
    it; on a card locked to Mockingboard mode it answers SND_NO_MUSIC and
    the driver runs on without starting the player (no 6-voice fallback,
    NATIVE.md 15.1, row 11);
  - a stream whose envelope or drum index is outside its tables stops the
    player with ERR_STREAM at that command;
  - the build prints no warning;
  - the comparison can fail: bugs planted in copies of the player are
    each caught;
  - a2vm's AY log format, its interrupt bounds, and the slot-4 slowdown
    window at its edges (512 and 32 cycles, FW-S1, the RTL's regions),
    through bus scripts.

The song tests skip without DOOM1.WAD (tools/fetch_upstream.py); the
player's tests skip without cc65 (ca65 and ld65).
"""

import json
import random
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from a2vm import costs
from sound import mus, mus2ay, player, run65, tables
from test_a2vm_machine import have_tools
from test_sound_mus import needs_wad

needs_cc65 = unittest.skipUnless(
    run65.have_cc65() and shutil.which('make'),
    'ca65 or ld65 (cc65 2.18) is missing: the 65C02 player cannot be built')

PAL, NTSC = False, True
_built = {}


def player_build():
    """Assemble src/sound once, into a directory of its own under build/,
    and build a2vm; returns (sound65 directory, a2vm binary)."""
    if not _built:
        a2vm_dir, _ = support.a2vm_build()
        out = Path(tempfile.mkdtemp(prefix='test-sound65-',
                                    dir=str(support.BUILD)))
        import atexit
        atexit.register(shutil.rmtree, str(out), True)
        run65.build(out=out)
        _built.update(out=out, a2vm=a2vm_dir / 'a2vm')
    return _built['out'], _built['a2vm']


_songs = {}


def wad_songs():
    """{name: song file bytes} of the WAD's 13 songs, converted now."""
    if not _songs:
        wad = mus.Wad.open(mus.WAD_PATH)
        instruments = mus2ay.load_instruments(wad)
        _songs.update(
            (name, mus2ay.convert(wad.song(name), instruments)[0].to_bytes())
            for name in wad.songs())
    return _songs


class Workspace(unittest.TestCase):
    def setUp(self):
        self.out, self.a2vm = player_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.p65 = run65.Player65(self.out)

    def compare_file(self, data, seconds, ntsc=PAL, loop=True, name='song',
                     probe=False):
        path = self.directory / ('%s.native12.ay' % name)
        path.write_bytes(data)
        return run65.compare_song(
            self.p65, path, seconds,
            self.directory / ('%s-%d-%d' % (name, ntsc, probe)),
            ntsc=ntsc, loop=loop, a2vm=self.a2vm, probe=probe)

    def scripted(self, songs, actions, seconds, ntsc=PAL):
        """Run the driver with `actions`; (the run, the expected main and
        bursts, the model's last player)."""
        result = run65.run(self.p65, songs, actions, seconds,
                           self.directory / 'scripted', ntsc=ntsc,
                           a2vm=self.a2vm)
        songs_by_index = [player.SongFile.from_bytes(s) for s in songs]
        main, bursts, last = run65.expected(songs_by_index, actions,
                                            len(result.bursts))
        return result, main, bursts, last

    def assert_scripted_equal(self, result, main, bursts, model):
        self.assertIsNone(run65.compare(result.main, result.bursts, main,
                                        bursts))
        self.assertIsNone(run65.final_difference(result, model))


# ---- the tables ------------------------------------------------------------

@needs_cc65
class Tables(Workspace):
    def test_tables_equal_tables_py(self):
        p65 = self.p65
        for label, machine in (('period_pal', tables.PAL_NATIVE),
                               ('period_ntsc', tables.NTSC_NATIVE)):
            data = p65.lc_bytes(label, 256)
            self.assertEqual([data[n] | data[128 + n] << 8
                              for n in range(128)],
                             tables.period_table(machine), label)
        self.assertEqual(tuple(p65.lc_bytes('bend_magnitude', 256)),
                         tables.BEND_MAGNITUDE)
        self.assertEqual(tuple(p65.lc_bytes('level_of_att', 81)),
                         tables.LEVEL)
        owned = list(p65.lc_bytes('owned_list', 64))
        owned = owned[:owned.index(0xFF) + 1]
        chips = {}
        for byte in owned[:-1]:
            if byte & 0x80:
                chip = byte & 3
                chips[chip] = []
            else:
                self.assertEqual(byte >> 4, chip)
                chips[chip].append(byte & 15)
        self.assertEqual({c: tuple(sorted(r)) for c, r in chips.items()},
                         tables.owned_registers(tables.NATIVE12))
        self.assertEqual(list(chips), sorted(chips, reverse=True))

    def test_the_card_holds_what_the_interrupt_uses(self):
        """The IRQ contract: code, data and vector in the language card,
        the rest in the zero page; the ring page aligned and the write
        lists in one page; nothing of the player in main $0200-$BFFF."""
        seg = self.p65.segments
        for name in ('SNDCODE', 'SNDRODATA', 'SNDBSS', 'SNDLIST',
                     'SNDRING'):
            start, size = seg[name]
            self.assertGreaterEqual(start, 0xD000, name)
            self.assertLessEqual(start + size, 0x10000, name)
        self.assertEqual(seg['VECTORS'][0], 0xFFFA)
        self.assertLess(seg['SNDZP'][0] + seg['SNDZP'][1], 0x100)
        self.assertEqual(seg['SNDRING'][0] & 0xFF, 0)
        labels = self.p65.labels
        # the burst's lda wreg+c*16-1,x and wval+c*16-1,x (X = 1-16)
        # never cross a page: wreg-1 to wval+63 in one page
        self.assertEqual(labels['wval'], labels['wreg'] + 64)
        self.assertEqual((labels['wreg'] - 1) >> 8,
                         (labels['wval'] + 63) >> 8)
        self.assertGreaterEqual(labels['wreg'] - 1, 0xD000)
        self.assertEqual(self.p65.lc[0x1FFE:0x2000],
                         struct.pack('<H', labels['snd_vbl']))


# ---- the build -------------------------------------------------------------

@needs_cc65
class Build(Workspace):
    def test_the_build_prints_no_warning(self):
        out = self.directory / 'fresh'
        text = run65.build(out=out)         # raises when ca65 or ld65 warns
        self.assertIn('ld65', text)
        self.assertNotIn('warning', text.lower())

    def test_a_warning_fails_the_build(self):
        """The address-size mismatch S2 first shipped with."""
        source = self.directory / 'src'
        shutil.copytree(str(run65.SRC), str(source))
        driver = source / 'driver.s'
        text = driver.read_text()
        self.assertEqual(text.count('.importzp vbl_count'), 1)
        driver.write_text(text.replace('.importzp vbl_count',
                                       '.import vbl_count'))
        with self.assertRaisesRegex(RuntimeError,
                                    'Address size mismatch.*vbl_count'):
            run65.build(out=self.directory / 'out', source=source)


# ---- the WAD's songs -------------------------------------------------------

@needs_cc65
@needs_wad
class Songs(Workspace):
    def check_all(self, ntsc, seconds):
        machine = run65.machine_of(ntsc)
        songs = wad_songs()
        self.assertEqual(len(songs), 13)
        for name, data in songs.items():
            with self.subTest(song=name, ntsc=ntsc):
                difference, count = self.compare_file(
                    data, seconds, ntsc=ntsc, name=name)
                self.assertIsNone(difference)
                self.assertLessEqual(
                    abs(count - int(seconds * tables.vbl_hz(machine))), 1)

    def test_60_seconds_of_every_song_on_pal(self):
        self.check_all(PAL, 60.0)

    def test_20_seconds_of_every_song_on_ntsc(self):
        self.check_all(NTSC, 20.0)

    def test_a_song_that_ends(self):
        """No loop: after the $FF the releases run out and nothing more is
        written (D_INTROA lasts 6.9 s)."""
        data = wad_songs()['D_INTROA']
        difference, count = self.compare_file(data, 12.0, loop=False,
                                              name='D_INTROA')
        self.assertIsNone(difference)


# ---- random streams --------------------------------------------------------

def random_song(rng, seconds, loop_inside=False,
                waits=(1, 1, 2, 3, 7, 30, 126)):
    """A valid song file that uses every command on every voice, with the
    edges player.py's arithmetic has: 16-bit envelope sums that carry,
    attenuations past 80, bends 0 and 255, drums loud and quiet."""
    nv = len(tables.voices(tables.NATIVE12))
    envelopes = [(rng.choice((0, 1, 300, 5000, 20480, 65535)),
                  rng.choice((0, 7, 900, 65535)),
                  rng.choice((1, 64, 3000, 65535)),
                  rng.choice((0, 12, 40, 80)), rng.randrange(2))
                 for _ in range(rng.randint(1, 5))]
    drums = [(rng.choice((0, 24, 33, 60, 96)), rng.choice((0, 1, 6, 31)),
              rng.randrange(65536), rng.choice((1, 914, 20480, 65535)))
             for _ in range(rng.randint(1, 5))]
    stream = []
    starts = []
    ticks = 0
    while ticks < seconds * tables.TICK_HZ:
        starts.append(len(stream))
        v = rng.randrange(nv)
        r = rng.random()
        note = rng.choice((0, 5, 23, 24, 60, 69, 96, 127, rng.randrange(128)))
        att = rng.choice((0, 3, 12, 13, 40, 79, 80, 81, 200, 255))
        if r < 0.12:
            stream += [0x00 | v, note]
        elif r < 0.24:
            stream += [0x10 | v, note, att]
        elif r < 0.36:
            stream += [0x20 | v, note, att, rng.randrange(len(envelopes))]
        elif r < 0.50:
            stream += [0x30 | v]
        elif r < 0.56:
            stream += [0x40 | v, att]
        elif r < 0.66:
            stream += [0x50 | v, rng.choice((0, 1, 64, 127, 128, 129, 200,
                                             255, rng.randrange(256)))]
        elif r < 0.78:
            stream += [0x60 | v, rng.randrange(len(drums)), att]
        elif r < 0.80:
            stream += [0x70 | v]
        else:
            wait = rng.choice(waits)
            stream.append(0x80 | wait)
            ticks += wait
    stream.append(0xFF)
    loop = rng.choice(starts[1:]) if loop_inside and len(starts) > 1 else 0
    if loop and not any(b & 0x80 and b != 0xFF for b in stream[loop:]):
        loop = 0
    song = player.SongFile(tables.NATIVE12, envelopes, drums, stream, loop)
    return song.to_bytes()


def dense_song(seed):
    """A dense song whose stream is 2 to 3 times the ring."""
    rng = random.Random(seed)
    for _ in range(100):
        data = random_song(rng, 6, waits=(1, 2, 3, 5, 8))
        song = player.SongFile.from_bytes(data)
        if 2048 < len(song.stream) < 3200:
            return data
    raise AssertionError('no random song of 2 to 3 KB')


@needs_cc65
class RandomStreams(Workspace):
    def test_random_streams(self):
        # 16 songs; the first 8 are the native12 songs of the two-layout
        # version of this test (the same seed and draws)
        rng = random.Random(20260930)
        for i in range(16):
            data = random_song(rng, rng.choice((4, 12, 30)),
                               loop_inside=i % 2 == 1)
            ntsc = i % 3 == 2
            with self.subTest(song=i, ntsc=ntsc):
                difference, _ = self.compare_file(
                    data, 20.0, ntsc=ntsc, name='random%d' % i)
                self.assertIsNone(difference)

    def test_music_attenuation(self):
        """The volume setting: loud drums become quiet ones and levels
        drop, as in player.py with music_attenuation."""
        rng = random.Random(7)
        data = random_song(rng, 10)
        song = player.SongFile.from_bytes(data)
        for matt in (0, 6, 30, 80):
            actions = [run65.start_action(0, 0, matt=matt)]
            result, main, bursts, model = self.scripted([data], actions, 8.0)
            self.assert_scripted_equal(result, main, bursts, model)
            init, direct = run65.player_py(song, tables.PAL_NATIVE,
                                           len(bursts), matt=matt)
            self.assertEqual(bursts, direct)


# ---- the ring, start, stop, loop ------------------------------------------

@needs_cc65
class Ring(Workspace):
    def long_loop_song(self, seed=3):
        return dense_song(seed)

    def test_refill_across_the_end_of_a_looping_song(self):
        data = self.long_loop_song()
        song = player.SongFile.from_bytes(data)
        actions = [run65.start_action(0, 0, loop=True)]
        result, main, bursts, model = self.scripted([data], actions, 30.0)
        self.assert_scripted_equal(result, main, bursts, model)
        # the stream went round several times through the ring, and
        # player.py (the whole stream in memory) agrees
        self.assertGreater(model.rpos, 3 * len(song.stream))
        self.assertEqual(model.underruns, 0)
        init, direct = run65.player_py(song, run65.machine_of(PAL),
                                       len(bursts))
        self.assertEqual([init] + [[]] * len(bursts), main)
        self.assertEqual(direct, bursts)
        # the 65C02 player's own count of the bytes it consumed
        self.assertEqual(self.final_word(data, actions, 30.0, 'rpos'),
                         model.rpos & 0xFFFF)

    def final_word(self, data, actions, seconds, label, size=2):
        result = run65.run(self.p65, [data], actions, seconds,
                           self.directory / 'snap', a2vm=self.a2vm,
                           snapshot=True)
        return result.word(label, size)

    def test_underrun_silences_and_holds_the_position(self):
        """The main loop stops refilling (a level load) for 6 s: the ring
        runs dry, every music voice goes quiet, and the song goes on from
        where it stopped once the refills come back."""
        data = self.long_loop_song(seed=11)
        actions = [run65.start_action(0, 0, loop=True),
                   run65.other_action(run65.GATE_OFF, 50),
                   run65.other_action(run65.GATE_ON, 350)]
        result, main, bursts, model = self.scripted([data], actions, 12.0)
        self.assert_scripted_equal(result, main, bursts, model)
        self.assertGreater(model.underruns, 10)
        # while starved, only level registers are written, to 0
        owned = tables.owned_registers(tables.NATIVE12)
        levels = [(c, r) for c in owned for r in owned[c] if 8 <= r <= 10]
        starved = [w for k in range(250, 350) for w in bursts[k]]
        self.assertTrue(all((c, r) in levels and v == 0
                            for c, r, v in starved), starved[:5])
        # and afterwards the song plays again
        self.assertGreater(sum(len(b) for b in bursts[360:]), 20)

    def test_start_stop_and_a_new_song_while_one_plays(self):
        songs = [wad_songs()['D_E1M1'], wad_songs()['D_INTRO'],
                 self.long_loop_song()] \
            if mus.WAD_PATH.exists() else \
            [self.long_loop_song(s) for s in (3, 4, 5)]
        actions = [run65.start_action(0, 0, loop=True),
                   run65.other_action(run65.STOP, 100),
                   run65.start_action(150, 1, loop=False, matt=6),
                   run65.start_action(300, 2, loop=True, ntsc=True),
                   run65.start_action(400, 0, loop=True),
                   run65.other_action(run65.STOP, 500),
                   run65.other_action(run65.STOP, 501)]
        result, main, bursts, model = self.scripted(songs, actions, 12.0)
        self.assert_scripted_equal(result, main, bursts, model)
        # the stop's burst, then nothing until the next start
        self.assertTrue(bursts[100])
        self.assertEqual(bursts[101:150], [[]] * 49)
        # every start wrote its first burst from the main loop: R0-R12 of
        # the four chips
        for k in (0, 150, 300, 400):
            self.assertEqual(len(main[k]), 52)
        self.assertEqual(bursts[501:], [[]] * len(bursts[501:]))
        self.assertFalse(model.playing)

    def test_a_refused_start(self):
        data = bytearray(wad_songs()['D_E1M1'] if mus.WAD_PATH.exists()
                         else self.long_loop_song())
        # a version 2, a layout 1 (the 6-voice layout that was removed:
        # no song file has it now), 21 envelopes; and player.py refuses
        # each one too
        for offset, value, error in ((0, 2, 1), (1, 1, 2), (2, 21, 3)):
            bad = bytearray(data)
            bad[offset] = value
            with self.assertRaisesRegex(RuntimeError, 'stop-pc.*A=\\$%02X'
                                        % error):
                run65.run(self.p65, [bytes(bad)],
                          [run65.start_action(0, 0)], 1.0,
                          self.directory / 'refused', a2vm=self.a2vm)
            if offset < 2:
                with self.assertRaises(player.SongFileError):
                    player.SongFile.from_bytes(bytes(bad))

    def test_the_ring_model_is_player_py_without_underrun(self):
        """RingPlayer, the oracle of the tests above, equals player.Player
        on every song when the ring is refilled after each interrupt."""
        rng = random.Random(5)
        for i in range(8):
            song = player.SongFile.from_bytes(
                random_song(rng, 20, loop_inside=i % 2 == 1))
            main, bursts, model = run65.expected(
                [song], [run65.start_action(0, 0)], 3000)
            init, direct = run65.player_py(song, run65.machine_of(PAL), 3000)
            self.assertEqual(main[0], init)
            self.assertEqual(bursts, direct)
            self.assertEqual(model.underruns, 0)


# ---- the comparison can fail -----------------------------------------------

BURST0 = ('        BURST_CHIP 0, VIA_A_ORA_NH, VIA_A_ORB, ORB_LATCH0, '
          'ORB_WRITE0, ORB_IDLE0\n')
BURST2 = ('        BURST_CHIP 2, VIA_B_ORA_NH, VIA_B_ORB, ORB_LATCH0, '
          'ORB_WRITE0, ORB_IDLE0\n')

# (what the bug does, the text replaced in src/sound/player.s, the new text)
MUTATIONS = (
    ('the bend rounds down', 'adc     #4', 'adc     #3'),
    ('R13 is not written again after a retrigger', 'eor     #1',
     'eor     #0'),
    ('the release adds the decay step',
     'adc     envtab+5,y', 'adc     envtab+3,y'),
    ('chip 2 goes out before chip 0', BURST0, BURST2 + BURST0),
    ('the ring mirror is not written',
     'bne     :+\n        lda     ring                    ; page 0',
     'bra     :+\n        lda     ring                    ; page 0'),
    ('an off after an on in the same interrupt releases at once',
     'ora     #OFF_PENDING', 'ora     #0'),
    ('the tempo drops the carry of the fraction',
     'adc     #0\n        beq     @compose',
     'lda     tint\n        beq     @compose'),
    ('the burst pulses the reset of its VIA\'s chips after each write',
     'sty     orb\n        dex',
     'sty     orb\n        stz     orb\n        sty     orb\n        dex'),
)


@needs_cc65
class PlantedBugs(Workspace):
    def test_each_planted_bug_is_caught(self):
        """30 s of a dense looping song that goes round the ring about
        25 times. The last bug writes every register player.py writes, in
        its order, but clears both chips of the VIA after each one."""
        data = dense_song(99)
        path = self.directory / 'planted.native12.ay'
        path.write_bytes(data)
        caught = []
        for index, (name, old, new) in enumerate(MUTATIONS):
            source = self.directory / ('src-%d' % index)
            shutil.copytree(str(run65.SRC), str(source))
            text = (source / 'player.s').read_text()
            self.assertEqual(text.count(old), 1, name)
            text = text.replace(old, new)
            if old == BURST0:           # and chip 2's own line goes
                at = text.rindex(BURST2)
                text = text[:at] + text[at + len(BURST2):]
            (source / 'player.s').write_text(text)
            out = self.directory / ('out-%d' % index)
            run65.build(out=out, source=source)
            difference, _ = run65.compare_song(
                run65.Player65(out), path, 30.0,
                self.directory / ('run-%d' % index), a2vm=self.a2vm)
            caught.append((name, difference))
        for name, difference in caught:
            self.assertIsNotNone(difference, name)

    def test_an_interrupt_outside_the_card_is_caught(self):
        """The IRQ contract: the tables the interrupt reads moved to main
        memory ($08xx, the driver's segment) end the run at the first
        interrupt that reads them, whenever the interrupt comes."""
        data = dense_song(99)
        source = self.directory / 'src'
        shutil.copytree(str(run65.SRC), str(source))
        text = (source / 'player.s').read_text()
        self.assertEqual(text.count('\ncmd_length:'), 1)
        (source / 'player.s').write_text(text.replace(
            '\ncmd_length:', '\n        .segment "DRVDATA"\ncmd_length:'))
        out = self.directory / 'out'
        run65.build(out=out, source=source)
        p65 = run65.Player65(out)
        self.assertLess(p65.labels['cmd_length'], 0xC000)
        path = self.directory / 'moved.native12.ay'
        path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError,
                                    'irq-bounds: read \\$0[0-9A-F]{3} in '
                                    'an interrupt'):
            run65.compare_song(p65, path, 5.0, self.directory / 'run',
                               a2vm=self.a2vm)

    def test_the_registers_at_the_end_are_checked(self):
        """final_difference: the chips' registers of state.json against
        the model's shadow, and the card's mode."""
        data = random_song(random.Random(12), 4)
        song = player.SongFile.from_bytes(data)
        result = run65.run(self.p65, [data],
                           [run65.start_action(0, 0)], 3.0,
                           self.directory / 'end', a2vm=self.a2vm)
        _, _, model = run65.player_model(song, tables.PAL_NATIVE,
                                         len(result.bursts))
        self.assertIsNone(run65.final_difference(result, model))
        ay = result.state['phasor']['ay']
        self.assertEqual(ay[0][:14], model.shadow[0])
        ay[2][9] ^= 1
        self.assertRegex(run65.final_difference(result, model),
                         'chip 2 holds')
        ay[2][9] ^= 1
        result.state['phasor']['mode'] = 0
        self.assertRegex(run65.final_difference(result, model), 'mode 0')
        # a run that ends inside an interrupt, after two writes of its
        # burst: they must begin the model's next burst, and count
        clock = None
        number, writes = 0, None
        for event in result.events:
            if event[0] == 'irq':
                number, writes = event[1], 0
            elif event[0] == 'rti':
                writes = None
            elif event[0] == 'w' and writes is not None:
                writes += 1
                if writes == 2 and number > 20:
                    clock = event[5]
                    break
        self.assertIsNotNone(clock)
        fabric = costs.parameters('f121')['fabric_mhz'] * 1e6
        cut = run65.run(self.p65, [data],
                        [run65.start_action(0, 0)], (clock + 2) / fabric,
                        self.directory / 'cut', a2vm=self.a2vm)
        self.assertEqual(len(cut.bursts), number - 1)
        self.assertEqual(len(cut.partial), 2)
        _, _, model = run65.player_model(song, tables.PAL_NATIVE,
                                         len(cut.bursts))
        self.assertIsNone(run65.final_difference(cut, model))
        chip, reg, value = cut.partial[1]
        cut.partial[1] = (chip, reg, value ^ 1)
        self.assertRegex(run65.final_difference(cut, model),
                         'the interrupt the run cut')

    def test_an_unchanged_copy_passes(self):
        data = dense_song(99)
        source = self.directory / 'src'
        shutil.copytree(str(run65.SRC), str(source))
        out = self.directory / 'out'
        run65.build(out=out, source=source)
        path = self.directory / 'same.native12.ay'
        path.write_bytes(data)
        difference, _ = run65.compare_song(
            run65.Player65(out), path, 30.0,
            self.directory / 'run', a2vm=self.a2vm)
        self.assertIsNone(difference)


# ---- the probe -------------------------------------------------------------

@needs_cc65
class Probe(Workspace):
    """snd_probe (probe.s): SND_MUSIC on the Phasor, which switches to
    native mode; SND_NO_MUSIC on a card that cannot, where the game runs
    without music (NATIVE.md 15.1, row 11: no 6-voice fallback). a2vm's
    card is the Phasor, or with --phasor-mb-only the Phasor locked to
    Mockingboard mode (the card's audio_control bit 26), which ignores
    $C0C0-$C0CF, as a real Mockingboard does."""

    def test_the_probe_finds_native_mode_on_the_phasor(self):
        result = run65.run(self.p65, [], [], 0.2, self.directory / 'phasor',
                           a2vm=self.a2vm, probe=True, snapshot=True)
        self.assertEqual(result.word('drv_found', 1), run65.SND_MUSIC)
        self.assertEqual(result.word('drv_music', 1), 1)
        self.assertEqual(result.main[0], list(run65.init_events(True)))
        self.assertIsNone(run65.final_difference(result, None))

    def test_songs_play_after_the_probe(self):
        """The probe, then 20 s of songs on the Phasor, compared with
        player.py; the card is in native mode at the end."""
        rng = random.Random(41)
        songs = [random_song(rng, 12, loop_inside=True)]
        if mus.WAD_PATH.exists():
            songs.append(wad_songs()['D_E1M1'])
        for i, data in enumerate(songs):
            with self.subTest(song=i):
                difference, count = self.compare_file(
                    data, 20.0, name='probed%d' % i, probe=True)
                self.assertIsNone(difference)
                self.assertGreater(count, 990)

    def test_no_music_on_a_card_locked_to_mockingboard_mode(self):
        """The probe answers SND_NO_MUSIC, the driver keeps that answer
        and calls snd_init; then 5 s of the game without music: a song's
        start and stop and a second start are ignored, nothing is ever
        written to a chip after snd_init's resets, the player is never
        playing, and the VBL interrupt still runs and counts every VBL.
        The card never leaves Mockingboard mode.

        The player's RAM in the card's $D000 bank starts as garbage, as
        on a real machine at power-on (a2vm would start it at zero): no
        byte is 0, so snd_playing reads as playing until snd_init clears
        it. The driver never calls snd_start, snd_stop or snd_refill: the
        run ends early at any of them."""
        data = random_song(random.Random(43), 12, loop_inside=True)
        if mus.WAD_PATH.exists():
            data = wad_songs()['D_E1M1']
        actions = [run65.start_action(0, 0),
                   run65.other_action(run65.STOP, 100),
                   run65.start_action(150, 0, ntsc=True)]
        garbage = bytes((i * 151 + 7) % 255 + 1 for i in range(0x1000))
        playing = self.p65.labels['snd_playing'] - run65.LC_BSS_BASE
        self.assertIn(playing, range(len(garbage)))
        self.assertNotEqual(garbage[playing], 0)
        try:
            result = run65.run(self.p65, [data], actions, 5.0,
                               self.directory / 'mbonly', a2vm=self.a2vm,
                               probe=True, mb_only=True, snapshot=True,
                               card=garbage,
                               stop_at=('snd_start', 'snd_stop',
                                        'snd_refill'))
        except RuntimeError as error:
            self.fail('the no-music run did not run to its end: %s' % error)
        self.assertEqual(result.state['end'], 'cycles')
        self.assertEqual(result.word('drv_found', 1), run65.SND_NO_MUSIC)
        self.assertEqual(result.word('drv_music', 1), 0)
        self.assertEqual(result.word('snd_playing', 1), 0)
        # the probe's writes (the second one landed on chip 0: two chips),
        # then snd_init's resets, and nothing else
        self.assertEqual(result.main[0],
                         list(run65.init_events(True, mb_only=True)))
        self.assertEqual(result.main[1:], [[]] * len(result.bursts))
        self.assertEqual(result.bursts, [[]] * len(result.bursts))
        self.assertIsNone(result.partial)
        nominal = int(5.0 * tables.vbl_hz(tables.PAL_NATIVE))
        self.assertLessEqual(abs(len(result.bursts) - nominal), 1)
        self.assertEqual(result.word('vbl_count'), len(result.bursts))
        # every chip at 0, the card in Mockingboard mode
        self.assertIsNone(run65.final_difference(
            result, None, mode=run65.MOCKINGBOARD_MODE))
        self.assertRegex(run65.final_difference(result, None), 'mode 0')
        # the same run on the Phasor plays: the driver's actions are the
        # ones a card in native mode obeys
        played = run65.run(self.p65, [data], actions, 5.0,
                           self.directory / 'phasor', a2vm=self.a2vm,
                           probe=True)
        self.assertTrue(any(played.bursts[:100]))
        self.assertEqual(len(played.main[150]), 52)


# ---- invalid streams ---------------------------------------------------------

@needs_cc65
class InvalidStreams(Workspace):
    """An envelope or drum index outside the song's tables: player.py
    fails (IndexError) in the interrupt that uses it; the 65C02 player
    stops reading at that command with snd_error = ERR_STREAM, having
    written the same registers until then."""

    ERR_STREAM = 5

    def check(self, command):
        envelopes = [(300, 900, 3000, 12, 1), (5000, 7, 64, 40, 0)]
        drums = [(33, 6, 914, 20480), (0, 31, 400, 914)]
        head = [0x10, 60, 0, 0x81, 0x61, 1, 20, 0x82, 0x21, 64, 6, 1, 0x83]
        stream = head + command + [0x81, 0x31, 0x90, 0xFF]
        song = player.SongFile(tables.NATIVE12, envelopes, drums, stream)
        data = song.to_bytes()
        model = player.Player(song, tables.PAL_NATIVE, loop=True)
        model.reset()
        bursts = []
        with self.assertRaises((IndexError, player.SongFileError)):
            for _ in range(100):
                bursts.append(model.interrupt())
        result = run65.run(self.p65, [data],
                           [run65.start_action(0, 0, loop=True)], 3.0,
                           self.directory / 'bad', a2vm=self.a2vm,
                           snapshot=True)
        self.assertEqual(result.bursts[:len(bursts)], bursts)
        self.assertEqual(result.word('snd_error', 1), self.ERR_STREAM)
        self.assertEqual(result.word('rpos'), len(head))
        self.assertEqual(result.word('ended', 1), 1)

    def test_an_envelope_past_the_table(self):
        for index in (2, 20, 255):
            with self.subTest(envelope=index):
                self.check([0x22, 60, 0, index])

    def test_a_drum_recipe_past_the_table(self):
        for index in (2, 23, 255):
            with self.subTest(drum=index):
                self.check([0x67, index, 0])


# ---- a2vm: the AY log ------------------------------------------------------

LOG_LINE = {
    'w': re.compile(r'^w (\d+) (\d+) (\d+|-) ([0-3]) (\d+) (\d+)$'),
    'reset': re.compile(r'^reset (\d+) (\d+) (\d+|-) ([0-3])$'),
    'irq': re.compile(r'^irq (\d+) (\d+) (\d+) (\d+|-)$'),
    'rti': re.compile(r'^rti (\d+) (\d+) (\d+|-)$'),
}


def ay_write(via_orb, via_ora, latch, write, idle, reg, value):
    return ['write %04X %02X' % (via_ora, reg), 'write %04X %02X' %
            (via_orb, latch), 'write %04X %02X' % (via_orb, idle),
            'write %04X %02X' % (via_ora, value), 'write %04X %02X' %
            (via_orb, write), 'write %04X %02X' % (via_orb, idle)]


@have_tools
class AyLog(unittest.TestCase):
    def setUp(self):
        self.out, _ = support.a2vm_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.rom = self.directory / 'rom.bin'
        self.rom.write_bytes(bytes(0x4000))

    def a2vm(self, *arguments):
        result = subprocess.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom)] +
            [str(a) for a in arguments], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_writes_resets_and_the_header(self):
        script = self.directory / 'bus.txt'
        lines = ['write C0C8 00', 'read C0C5',
                 'write C413 FF', 'write C412 1F', 'write C410 00',
                 'write C410 0C']
        lines += ay_write(0xC410, 0xC41F, 0x0F, 0x0E, 0x0C, 7, 0x38)
        lines += ay_write(0xC410, 0xC41F, 0x17, 0x16, 0x14, 2, 0x9A)
        lines += ay_write(0xC410, 0xC411, 0x0F, 0x0E, 0x0C, 3, 0x05)
        script.write_text('\n'.join(lines) + '\n')
        log = self.directory / 'ay.log'
        self.a2vm('--core', 'w65c02s', '--via-ora-nh', '--ay-log', log,
                  '--bus-script', script)
        text = log.read_text().splitlines()
        self.assertTrue(text[0].startswith('# a2vm ay-log 1'))
        self.assertIn('# clock - (no cost model)', text)
        body = [line for line in text if not line.startswith('#')]
        kinds = [line.split()[0] for line in body]
        self.assertEqual(kinds, ['reset', 'reset', 'w', 'w', 'w'])
        for line in body:
            self.assertRegex(line, LOG_LINE[line.split()[0]])
        writes = [tuple(int(x) for x in line.split()[4:]) for line in body
                  if line.startswith('w')]
        self.assertEqual(writes, [(0, 7, 0x38), (1, 2, 0x9A), (0, 3, 0x05)])
        self.assertEqual([line.split()[4] for line in body[:2]], ['0', '1'])
        # without --via-ora-nh the model keeps a2sim.py's rule: a write
        # to register 15 does not reach ORA
        self.a2vm('--core', 'w65c02s', '--ay-log', log,
                  '--bus-script', script)
        writes = [tuple(int(x) for x in line.split()[4:])
                  for line in log.read_text().splitlines()
                  if line.startswith('w ')]
        self.assertEqual(writes[-1], (0, 3, 0x05))
        self.assertNotIn((0, 7, 0x38), writes)

    def test_interrupts_and_the_model_clock(self):
        """A program that takes the mouse card's VBL interrupt: each is
        logged with its number, then its RTI; with the cost model the
        clock field is the model's, a PAL frame apart."""
        # $0800: VBL interrupts on, CLI, loop. $0900: the handler reads
        # the status, acknowledges and returns. Vectors in the card.
        program = bytes([0xA9, 0x09, 0x8D, 0xAE, 0xC0, 0x58,
                         0x4C, 0x06, 0x08])
        handler = bytes([0x48, 0xAD, 0xA0, 0xC0, 0xA9, 0x03, 0x8D, 0xAF,
                         0xC0, 0x68, 0x40])
        vectors = struct.pack('<HHH', 0x0900, 0x0800, 0x0900)
        image = self.directory / 'irq.img'
        image.write_bytes(
            b'A2VMIMG1' +
            struct.pack('<BBHI', 0, 0, 0x0800, len(program)) + program +
            struct.pack('<BBHI', 0, 0, 0x0900, len(handler)) + handler +
            struct.pack('<BBHI', 2, 0, 0xFFFA, 6) + vectors)
        cost = self.directory / 'cost.txt'
        cost.write_text(costs.text('f121'))
        log = self.directory / 'ay.log'
        frame = costs.parameters('f121')
        clocks = int(frame['fabric_mhz'] * 1e6 * 0.1)      # 100 ms
        self.a2vm('--core', 'w65c02s', '--image', image, '--switch',
                  'lc_read=1', '--reg', 'pc=0800', '--reg', 'p=34',
                  '--cost', cost, '--cost-timed', '--cycles', clocks,
                  '--ay-log', log, '--state', self.directory / 's.json')
        text = log.read_text().splitlines()
        self.assertTrue(any(line.startswith('# clock fabric 133.333333')
                            for line in text))
        body = [line for line in text if not line.startswith('#')]
        for line in body:
            self.assertRegex(line, LOG_LINE[line.split()[0]])
        # 100 ms of a PAL //e: 5 VBLs, each an interrupt and its RTI
        self.assertEqual([line.split()[0] for line in body],
                         ['irq', 'rti'] * 5)
        irqs = [line.split() for line in body if line.startswith('irq')]
        self.assertEqual([int(f[1]) for f in irqs], [1, 2, 3, 4, 5])
        clocks_at = [int(line.split()[-1]) for line in body]
        self.assertEqual(clocks_at, sorted(clocks_at))
        entries = [int(f[4]) for f in irqs]
        frame_clocks = frame['fabric_mhz'] * frame['line_us'] * frame['lines']
        for a, b in zip(entries, entries[1:]):
            self.assertLess(abs(b - a - frame_clocks), 400)
        # the Apple cycle field: 20,280 cycles a PAL frame
        apple = [int(f[3]) for f in irqs]
        for a, b in zip(apple, apple[1:]):
            self.assertLess(abs(b - a - 312 * 65), 4)


    def test_irq_bounds(self):
        """--irq-bounds: the handler's accesses from its first instruction
        to its RTI; the interrupted program's (and the entry's dummy
        reads of its PC) are not checked."""
        program = bytes([0xA9, 0x09, 0x8D, 0xAE, 0xC0, 0x58,
                         0xAD, 0x00, 0x03, 0x4C, 0x06, 0x08])
        handler = [0x48, 0xAD, 0xA0, 0xC0, 0xA9, 0x03, 0x8D, 0xAF, 0xC0]
        tail = [0x68, 0x40]
        cost = self.directory / 'cost.txt'
        cost.write_text(costs.text('f121'))
        clocks = int(costs.parameters('f121')['fabric_mhz'] * 1e6 * 0.1)
        bounds = '0000-01FF,C0A0-C0AF,D000-FFFF'

        def run(extra):
            code = bytes(handler + extra + tail)
            image = self.directory / 'bounds.img'
            image.write_bytes(
                b'A2VMIMG1' +
                struct.pack('<BBHI', 0, 0, 0x0800, len(program)) + program +
                struct.pack('<BBHI', 2, 0, 0xE100, len(code)) + code +
                struct.pack('<BBHI', 2, 0, 0xFFFA, 6) +
                struct.pack('<HHH', 0xE100, 0x0800, 0xE100))
            state = self.directory / 's.json'
            result = subprocess.run(
                [str(self.out / 'a2vm'), '--rom', str(self.rom),
                 '--core', 'w65c02s', '--image', str(image), '--switch',
                 'lc_read=1', '--reg', 'pc=0800', '--reg', 'p=34',
                 '--cost', str(cost), '--cost-timed', '--cycles',
                 str(clocks), '--irq-bounds', bounds, '--state',
                 str(state)], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True)
            return result.returncode, json.loads(state.read_text())

        # the handler stays inside: the run goes to its end, 5 interrupts
        status, state = run([0xA5, 0x80, 0xAD, 0x00, 0xE0])
        self.assertEqual((status, state['end'], state['halt']),
                         (0, 'cycles', ''))
        # a read of main memory, a write to it, a soft switch outside the
        # mouse card's: each halts at the first interrupt
        for extra, halt in (([0xAD, 0x00, 0x03], 'read $0300'),
                            ([0x8D, 0x00, 0x20], 'write $2000'),
                            ([0x8D, 0x03, 0xC0], 'write $C003')):
            with self.subTest(halt=halt):
                status, state = run(extra)
                self.assertEqual(status, 1)
                self.assertEqual(state['end'], 'halt')
                self.assertIn('irq-bounds: %s in an interrupt' % halt,
                              state['halt'])
                self.assertEqual(state['irqs'], 1)


# ---- a2vm: the slot-4 slowdown ---------------------------------------------

@have_tools
class Slowdown(unittest.TestCase):
    """The window of config_menu.c:4660-4692 and vtw_core_top.sv:1119-1171,
    1884-1898, through bus scripts: each bus-script access is one CPU
    cycle."""

    def setUp(self):
        self.out, _ = support.a2vm_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)
        self.rom = self.directory / 'rom.bin'
        self.rom.write_bytes(bytes(0x4000))
        self.period = costs.parameters('f121')['fabric_mhz'] * \
            costs.parameters('f121')['line_us'] / 65.0

    def deltas(self, lines, profile):
        cost = self.directory / 'cost.txt'
        cost.write_text(costs.text(profile))
        script = self.directory / 'bus.txt'
        body = ['cost']
        for line in lines:
            body += [line, 'cost']
        script.write_text('\n'.join(body) + '\n')
        result = subprocess.run(
            [str(self.out / 'a2vm'), '--rom', str(self.rom), '--no-mouse',
             '--cost', str(cost), '--bus-script', str(script)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        points = [dict(item.split('=') for item in line.split()[1:])
                  for line in result.stdout.splitlines()
                  if line.startswith('cost ')]
        return ([int(b['t']) - int(a['t']) for a, b in zip(points,
                                                          points[1:])],
                points)

    def slow(self, delta):
        """One access at 1 MHz: about an Apple cycle (131.28 clocks)."""
        return abs(delta - self.period) <= 1.5

    def test_the_window_at_its_edges(self):
        for variants, window in (('phasor', 512), ('phasor+window32', 32)):
            reads = ['read 1000'] * (window + 3)
            d, points = self.deltas(['write C410 0C'] + reads,
                                    'f121+' + variants)
            after = d[1:]
            # exactly `window` cycles at 1 MHz after the hit, then TURBO
            self.assertTrue(all(self.slow(x) for x in after[:window]),
                            after[:window])
            self.assertTrue(all(x <= 4 for x in after[window:]),
                            after[window:])
            self.assertEqual(int(points[-1]['slow_cycles']), window)
            self.assertEqual(int(points[1]['slow_left']), window)
            self.assertEqual(int(points[-1]['slow_left']), 0)

    def test_a_hit_inside_the_window_reloads_it(self):
        lines = ['write C410 0C'] + ['read 1000'] * 100 + \
            ['read C404'] + ['read 1000'] * 515
        d, points = self.deltas(lines, 'f121+phasor')
        after = d[102:]
        self.assertTrue(all(self.slow(x) for x in after[:512]))
        self.assertTrue(all(x <= 4 for x in after[512:]))
        self.assertEqual(int(points[-1]['slow_cycles']), 100 + 1 + 512)
        self.assertEqual(int(points[-1]['slow_hits']), 2)

    def test_the_regions(self):
        """$C400-$C4FF and $C0C0-$C0CF, reads and writes, and only
        those."""
        hits = ['read C400', 'read C4FF', 'write C480 0C', 'read C0C0',
                'read C0CF', 'write C0C5 00']
        misses = ['read C3FF', 'read C500', 'read C0BF', 'read C0D0',
                  'read C800', 'read CC00', 'read C019', 'read 4400']
        for line in hits + misses:
            with self.subTest(access=line):
                _, points = self.deltas([line], 'f121+phasor')
                self.assertEqual(int(points[-1]['slow_left']),
                                 512 if line in hits else 0)

    def test_fw_s1_exempts_via_port_writes(self):
        # Registers 0 (ORB) and F (ORA without handshake) only: exempt
        # IFR, IER and ORA writes release the IRQ and cause a second
        # interrupt (docs/firmware/fws1-review.md, finding 1).
        exempt = ['write C410 0C', 'write C41F 07', 'write C48F 07',
                  'write C480 0E', 'write C400 0C', 'write C40F 07',
                  'write C490 0C', 'write C49F 07']
        hits = ['read C410', 'read C41F', 'write C411 00', 'write C412 1F',
                'write C413 FF', 'write C41D 7F', 'write C41E 7F',
                'write C414 00', 'write C415 00', 'write C41B 00',
                'write C41C 00', 'write C440 00', 'write C420 00',
                'write C45F 07', 'write C0C5 00', 'read C0C8']
        for line in exempt + hits:
            with self.subTest(access=line):
                _, points = self.deltas([line], 'f121+phasor+fws1')
                self.assertEqual(int(points[-1]['slow_left']),
                                 0 if line in exempt else 512)

    def test_off_unless_the_phasor_is_enabled(self):
        """f121 and fastpath as they were: no window, no new counters, the
        same clocks as before this milestone."""
        for profile in ('f121', 'fastpath'):
            d, points = self.deltas(['write C410 0C', 'read 1000',
                                     'read 1000'], profile)
            self.assertNotIn('slow_left', points[-1])
            self.assertTrue(all(x <= 4 for x in d[1:]))
            self.assertFalse(costs.parameters(profile)['slowdown_slot4'])

    def test_every_variant_value_has_a_source(self):
        data = costs.load()
        # (nod2 and precal since the card's calibration, 2026-10-03)
        self.assertEqual(costs.variants(),
                         ['fws1', 'nod2', 'ntsc', 'phasor', 'precal',
                          'window32'])
        for name in costs.variants():
            for key, entry in data['variants'][name]['params'].items():
                self.assertIn(key, data['common'])
                self.assertTrue(entry.get('source', '').strip(), key)
        for key in ('slowdown_cycles', 'slowdown_slot4',
                    'slowdown_via_exempt', 'slow_done'):
            self.assertIn('source', data['common'][key])
        self.assertEqual(costs.parameters('f121+phasor+window32')
                         ['slowdown_cycles'], 32)
        with self.assertRaises(KeyError):
            costs.parameters('f121+nosuch')


if __name__ == '__main__':
    unittest.main()
