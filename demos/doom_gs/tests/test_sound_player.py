"""Tests of tools/sound/player.py (the model of the 65C02 player) and of
tools/sound/tables.py (the tables the player shares with the host).

The synthetic songs' register writes are worked out by hand in the
comments; they are the kind of case S2's 65C02 player is checked on.
"""

import math
import unittest

import support  # noqa: F401  (puts tools/ on the path)
from sound import player, tables

PAL = tables.PAL_NATIVE
NTSC = tables.NTSC_NATIVE
# attack reaches full level in one tick, no decay, sustain at full,
# release from full to silent (80 x 256) in two ticks, level held
PIANO = (65535, 0, 10240, 0, player.ENV_SUSTAINED)
KICK = (33, 6, 1270, 914)       # tone note 33, noise 6, EP 1270, step 914


def song(stream, envelopes=(PIANO,), drums=(KICK,), layout=tables.NATIVE12):
    return player.SongFile(layout, envelopes, drums, bytes(stream))


def bursts(song_file, count, machine=PAL, **options):
    p = player.Player(song_file, machine, **options)
    init = p.reset()
    return p, init, [p.interrupt() for _ in range(count)]


class Tables(unittest.TestCase):
    def test_psg_clock_doubles_in_native_mode(self):
        self.assertEqual(tables.psg_clock(PAL), 2031250)
        self.assertEqual(tables.psg_clock(NTSC), 2040968)
        self.assertEqual(tables.psg_clock(tables.PAL_MOCKINGBOARD), 1015625)

    def test_period_table_formula(self):
        for machine in tables.MACHINES.values():
            clock = tables.psg_clock(machine)
            table = tables.period_table(machine)
            for note in range(128):
                raised = note
                while clock / (16 * 440 * 2 ** ((raised - 69) / 12)) >= 4095.5:
                    raised += 12
                f = 440 * 2 ** ((raised - 69) / 12)
                self.assertEqual(table[note], max(1, round(clock / (16 * f))))
                self.assertLessEqual(table[note], 4095)

    def test_a4_and_the_lowest_notes(self):
        table = tables.period_table(PAL)
        self.assertEqual(table[69], 289)       # 2031250 / 7040 = 288.5
        self.assertEqual(table[24], 3882)      # C1, the lowest that fits
        self.assertEqual(table[23], table[35])  # raised by an octave
        self.assertEqual(tables.period_table(tables.PAL_MOCKINGBOARD)[69],
                         144)

    def test_pitch_error_of_the_melodic_range(self):
        clock = tables.psg_clock(PAL)
        table = tables.period_table(PAL)
        worst = max(abs(1200 * math.log2(clock / (16 * table[n])
                                         / (440 * 2 ** ((n - 69) / 12))))
                    for n in range(24, 85))
        self.assertLess(worst, 6.5)             # native-sound.md 2.2

    def test_bend_magnitudes_by_hand(self):
        m = tables.BEND_MAGNITUDE
        self.assertEqual(m[128], 0)
        self.assertEqual(m[0], 251)     # 2^(2/12) - 1 = 0.12246 x 2048
        self.assertEqual(m[64], 122)    # 2^(1/12) - 1 = 0.05946 x 2048
        self.assertEqual(m[192], 115)   # 1 - 2^(-1/12) = 0.05613 x 2048
        self.assertEqual(m[255], 222)   # 1 - 2^(-127/768) = 0.10825 x 2048
        self.assertEqual(max(m), 251)   # a byte

    def test_bent_period_against_the_exact_ratio(self):
        for period in (30, 289, 1000, 3000):
            for bend in range(256):
                exact = period * 2 ** (-(bend - 128) / 768)
                got = tables.bent_period(period, bend)
                if exact <= 4095:
                    self.assertLessEqual(abs(got - exact),
                                         1 + period / 4096)
        self.assertEqual(tables.bent_period(289, 0), 324)
        self.assertEqual(tables.bent_period(4000, 0), 4095)

    def test_bent_period_rounds(self):
        # The change is period x magnitude / 2048 rounded to the nearest,
        # so the bent period is within half a period step, plus the
        # magnitude's own rounding (half of 1/2048), of the exact one.
        for period in range(1, 4096):
            for bend in range(256):
                exact = period * 2 ** (-(bend - 128) / 768)
                if exact > 4095:
                    continue
                m = tables.BEND_MAGNITUDE[bend]
                delta = math.floor(period * m / 2048 + 0.5)
                want = period + delta if bend < 128 else period - delta
                got = tables.bent_period(period, bend)
                self.assertEqual(got, min(4095, max(1, want)))
                self.assertLessEqual(abs(got - exact),
                                     0.5 + period / 4096 + 1e-9)
        # A4 in Mockingboard mode (period 144) two semitones down: 144 x
        # 251 / 2048 = 17.65 -> 18, period 162, 391.8 Hz for G4's 392.0
        # (truncating gave 161, 394.3 Hz, 10 cents sharp)
        self.assertEqual(tables.bent_period(144, 0), 162)

    def test_ay_levels_from_the_hdl_table(self):
        self.assertEqual(list(tables.AY_OUT),
                         [0, 3, 4, 6, 10, 15, 21, 34, 40, 65, 91, 114, 144,
                          181, 215, 255])
        self.assertAlmostEqual(tables.AY_DB[14], -1.48, places=2)
        self.assertAlmostEqual(tables.AY_DB[1], -38.59, places=2)

    def test_level_table_is_the_nearest_level(self):
        for att in range(tables.ATT_MAX + 1):
            want = -att / 2
            level = tables.LEVEL[att]
            if att == tables.ATT_MAX:
                self.assertEqual(level, 0)
                continue
            for other in range(1, 16):
                self.assertLessEqual(abs(tables.AY_DB[level] - want),
                                     abs(tables.AY_DB[other] - want) + 1e-9)
        self.assertEqual(tables.LEVEL[0], 15)
        self.assertEqual(tables.LEVEL[20], 10)  # -10 dB: -8.9 is nearest
        self.assertEqual(tables.LEVEL[30], 8)   # -15 dB: -16.1
        self.assertEqual(tables.LEVEL[40], 6)   # -20 dB: -21.7

    def test_volume_law(self):
        a = tables.ATTENUATION_OF_VALUE
        self.assertEqual(a[127], 0)
        self.assertEqual(a[64], 24)             # 40 log10(64/127) = -11.9
        self.assertEqual(a[0], tables.ATT_MAX)
        self.assertEqual(a[1], tables.ATT_MAX)  # -84 dB, capped
        self.assertEqual(list(a), sorted(a, reverse=True))

    def test_tempo(self):
        self.assertEqual(tables.tempo(PAL), (2, 52135))    # 52135.20
        self.assertEqual(tables.tempo(NTSC), (2, 22043))   # 22042.53
        for machine in (PAL, NTSC):
            whole, frac = tables.tempo(machine)
            per = tables.TICK_HZ * machine.vbl_cycles / machine.bus_hz
            self.assertLess(abs(whole + frac / 65536 - per), 1 / 65536)

    def test_ticks_over_a_minute(self):
        p = player.Player(song([0xfe] * 60 + [0xff]), PAL)
        p.reset()
        count = [0]
        tick = p.tick

        def counted():
            count[0] += 1
            tick()
        p.tick = counted
        interrupts = round(60 * tables.vbl_hz(PAL))
        for _ in range(interrupts):
            p.interrupt()
        self.assertLessEqual(abs(count[0] - 140 * interrupts
                                 / tables.vbl_hz(PAL)), 1)

    def test_owned_registers(self):
        owned = tables.owned_registers(tables.NATIVE12)
        self.assertEqual(owned[0], (0, 1, 2, 3, 4, 5, 7, 8, 9, 10))
        self.assertEqual(owned[1], tuple(range(14)))
        self.assertNotIn(3, owned)
        owned = tables.owned_registers(tables.MB6)
        self.assertEqual(owned[2], (0, 1, 7, 8))


class SongFiles(unittest.TestCase):
    def test_round_trip(self):
        s = song([0x20, 69, 0, 0, 0x81, 0xff])
        data = s.to_bytes()
        self.assertEqual(len(data), 8 + 8 + 6 + 6)
        back = player.SongFile.from_bytes(data)
        self.assertEqual(back.stream, s.stream)
        self.assertEqual(back.envelopes, s.envelopes)
        self.assertEqual(back.drums, s.drums)
        self.assertIs(back.layout, tables.NATIVE12)

    def test_bad_files(self):
        data = song([0x81, 0xff]).to_bytes()
        for bad in (data[:5], bytes([2]) + data[1:], data[:1] + b'\x07'
                    + data[2:], data[:-1], data + b'\x00'):
            with self.assertRaises(player.SongFileError):
                player.SongFile.from_bytes(bad)

    def test_decode_stream(self):
        stream = bytes([0x20, 69, 0, 0, 0x83, 0x31, 0x44, 9, 0x52, 0,
                        0x67, 0, 5, 0x10, 60, 3, 0x02, 61, 0xfe, 0xff])
        self.assertEqual(player.decode_stream(stream), [
            (0, 2, 0, (69, 0, 0)), (3, 3, 1, ()), (3, 4, 4, (9,)),
            (3, 5, 2, (0,)), (3, 6, 7, (0, 5)), (3, 1, 0, (60, 3)),
            (3, 0, 2, (61,)), (129, player.END, None, ())])
        self.assertEqual(player.decode_stream(b'\x73\x81\xff'),
                         [(0, player.CUT, 3, ()), (1, player.END, None, ())])
        for bad in (b'\x80\xff', b'\x20\x45', b'\x81'):
            with self.assertRaises(player.SongFileError):
                player.decode_stream(bad)


class HandComputed(unittest.TestCase):
    def test_reset_burst(self):
        _, init, _ = bursts(song([0x81, 0xff]), 0)
        self.assertEqual(init, [(chip, reg, 0x38 if reg == 7 else 0)
                                for chip in range(4) for reg in range(13)])
        _, init, _ = bursts(song([0x81, 0xff], layout=tables.MB6), 0,
                            machine=tables.PAL_MOCKINGBOARD)
        self.assertEqual([w[0] for w in init], [0] * 13 + [2] * 13)

    def test_note_then_release(self):
        # tick 0: A4 (period 289 = $121) at full level; tick 3: note off;
        # tick 4: end. Interrupt 1 runs ticks 0-1 (2 ticks), interrupt 2
        # ticks 2-4 (the fraction carries): release 10240 a tick reaches
        # silence at tick 4.
        p, _, out = bursts(song([0x20, 69, 0, 0, 0x83, 0x30, 0x81, 0xff]), 3)
        self.assertEqual(out, [[(0, 0, 0x21), (0, 1, 0x01), (0, 8, 15)],
                               [(0, 8, 0)],
                               []])
        self.assertTrue(p.ended)
        self.assertEqual(p.phase[0], player.IDLE)

    def test_a_note_shows_for_one_interrupt(self):
        # The note off at tick 1 comes in the interrupt of the note on, so
        # its release waits: interrupt 1 shows level 15, not LEVEL[40] = 6
        # (half the release done by the end of tick 1).
        _, _, out = bursts(song([0x20, 69, 0, 0, 0x81, 0x30, 0x81, 0xff]),
                           2)
        self.assertEqual(out, [[(0, 0, 0x21), (0, 1, 0x01), (0, 8, 15)],
                               [(0, 8, 0)]])

    def test_attenuation_and_the_music_volume(self):
        # natt 20 (-10 dB) -> level 10; with music attenuation 10, 30 -> 8
        s = song([0x20, 69, 20, 0, 0xfe, 0xff])
        _, _, out = bursts(s, 1)
        self.assertEqual(out[0][-1], (0, 8, 10))
        _, _, out = bursts(s, 1, music_attenuation=10)
        self.assertEqual(out[0][-1], (0, 8, 8))

    def test_pitch_bend(self):
        # bend 0: 289 + (289 x 251 >> 11) = 289 + 35 = 324 = $144
        _, _, out = bursts(song([0x20, 69, 0, 0, 0x50, 0, 0x81, 0xff]), 1)
        self.assertEqual(out[0], [(0, 0, 0x44), (0, 1, 0x01), (0, 8, 15)])

    def test_second_voice_on_chip_1(self):
        # voice 4 is chip 1 channel B: registers 2, 3 and 9 of chip 1
        _, _, out = bursts(song([0x24, 69, 0, 0, 0xfe, 0xff]), 1)
        self.assertEqual(out[0], [(1, 2, 0x21), (1, 3, 0x01), (1, 9, 15)])

    def test_drums(self):
        # Voice 7 is chip 1 channel C. Hit 1 (tick 0, natt 0): tone note
        # 33 (period 2308 = $904), noise 6, mixer $38 with C's tone and
        # noise on = $18, envelope period 1270 = $4F6, shape 0, level $10.
        # Hit 2 (tick 3, same recipe): only R13, to restart the envelope.
        # Hit 3 (tick 6, natt 20 > 12): software decay from full: level
        # LEVEL[20] = 10. Interrupt 4 (ticks 8-10): 3 x 914 = 2742, >> 8
        # = 10, LEVEL[30] = 8.
        s = song([0x67, 0, 0, 0x83, 0x67, 0, 0, 0x83, 0x67, 0, 20, 0x83,
                  0xff])
        _, _, out = bursts(s, 5)
        self.assertEqual(out[0], [(1, 4, 0x04), (1, 5, 0x09), (1, 6, 6),
                                  (1, 7, 0x18), (1, 10, 0x10),
                                  (1, 11, 0xf6), (1, 12, 0x04),
                                  (1, 13, 0)])
        self.assertEqual(out[1], [(1, 13, 0)])
        self.assertEqual(out[2], [(1, 10, 10)])
        self.assertEqual(out[3], [(1, 10, 8)])

    def test_last_drum_hit_of_an_interrupt_wins(self):
        # a loud hit and a quiet one in the same interrupt: only the quiet
        # one sounds, so the envelope registers are never written
        s = song([0x67, 0, 0, 0x81, 0x67, 0, 20, 0x81, 0xff])
        _, _, out = bursts(s, 1)
        self.assertEqual(out[0], [(1, 4, 0x04), (1, 5, 0x09), (1, 6, 6),
                                  (1, 7, 0x18), (1, 10, 10)])

    def test_cut(self):
        # A4 at full level, cut at tick 3 (interrupt 2, ticks 2-4): level
        # 0 at once, where a note off would take the release's two ticks
        # (and PIANO's release is fast). The voice stays idle.
        p, _, out = bursts(song([0x20, 69, 0, 0, 0x83, 0x70, 0x83, 0xff]),
                           2)
        self.assertEqual(out[1], [(0, 8, 0)])
        self.assertEqual((p.phase[0], p.eatt[0]),
                         (player.IDLE, player.SILENT))
        # a slow release (1 unit a tick): after a note off at tick 3, two
        # ticks of release give 1 dB, LEVEL[2] = 14; a cut silences it
        slow = (65535, 0, 256, 0, player.ENV_SUSTAINED)
        _, _, out = bursts(song([0x20, 69, 0, 0, 0x83, 0x30, 0x83, 0xff],
                                envelopes=(slow,)), 2)
        self.assertEqual(out[1], [(0, 8, 14)])
        _, _, out = bursts(song([0x20, 69, 0, 0, 0x83, 0x70, 0x83, 0xff],
                                envelopes=(slow,)), 2)
        self.assertEqual(out[1], [(0, 8, 0)])

    def test_cut_of_a_drum_on_the_chips_envelope(self):
        # a loud hit on voice 7 (chip 1 C) holds level $10 (the envelope);
        # a cut writes level 0; a hit and a cut in the same interrupt
        # write nothing: the latched hit is dropped
        _, _, out = bursts(song([0x67, 0, 0, 0x83, 0x77, 0x83, 0xff]), 2)
        self.assertEqual(out[0][4], (1, 10, 0x10))
        self.assertEqual(out[1], [(1, 10, 0)])
        _, _, out = bursts(song([0x67, 0, 0, 0x77, 0x83, 0xff]), 1)
        self.assertEqual(out[0], [])

    def test_loop(self):
        s = song([0x20, 69, 0, 0, 0x81, 0x30, 0x81, 0xff])
        p, _, out = bursts(s, 3, loop=True)
        self.assertFalse(p.ended)
        self.assertEqual(out[1:], [[], []])
        with self.assertRaises(player.SongFileError):
            bursts(song([0xff]), 1, loop=True)

    def test_bad_voice(self):
        with self.assertRaises(player.SongFileError):
            bursts(song([0x09, 60, 0x81, 0xff]), 1)


if __name__ == '__main__':
    unittest.main()
