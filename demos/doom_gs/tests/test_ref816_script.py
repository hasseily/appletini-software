"""Tests of the script side of the reference machine: key names
(tools/ref816/keys.py), the script compiler (script.py), the log of
marks (marks.py), the view statistics of shot.py and the checks of
run_script.py, on synthetic data.
"""

import json
import re
import struct
import unittest

import support
from ref816 import keys, make_image, marks, run_script, script, shot

LINKMAP = {'game': {'units': {
    'g_game65.s': {'_g_gametic': 0x02c6af, '_g_gamestate': 0x02c60e,
                   'shared': 0x001000},
    'm_menu65.s': {'itemOn': 0x02c3ee, 'shared': 0x001000,
                   'twice': 0x002000, 'unplaced': None},
    'd_main65.s': {'twice': 0x003000},
}}}
SYMBOLS = script.Symbols(LINKMAP)


def compiled(text):
    """The program lines of `text`, without their source comments."""
    return [line.split('  #')[0] for line in
            script.compile_script(text, SYMBOLS, 't.script').splitlines()]


class Keys(unittest.TestCase):
    def test_names(self):
        self.assertEqual(keys.code('a'), 0x00)
        self.assertEqual(keys.code('Escape'), 0x35)
        self.assertEqual(keys.code('esc'), 0x35)
        self.assertEqual(keys.code('ctrl'), 0x36)
        self.assertEqual(keys.code('1'), 0x12)
        self.assertEqual(keys.code('keypad8'), 0x5b)
        self.assertEqual(keys.code('0x7e'), 0x7e)

    def test_errors(self):
        for name in ('nokey', '0x80', '-1'):
            with self.assertRaises(KeyError):
                keys.code(name)

    def test_codes_are_distinct(self):
        self.assertEqual(len(set(keys.KEYS.values())), len(keys.KEYS))
        self.assertEqual(sorted(keys.CHARACTERS),
                         sorted('abcdefghijklmnopqrstuvwxyz0123456789'))


class Symbols(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(SYMBOLS.address('itemOn'), 0x02c3ee)
        self.assertEqual(SYMBOLS.address('itemOn+4'), 0x02c3f2)
        self.assertEqual(SYMBOLS.address('shared'), 0x001000)
        self.assertEqual(SYMBOLS.address('d_main65.s:twice'), 0x003000)
        self.assertEqual(SYMBOLS.address('0x7f0000+0x10'), 0x7f0010)

    def test_errors(self):
        for reference, message in [
                ('nothing', 'no label is called nothing'),
                ('twice', 'twice is in more than one unit'),
                ('m_menu65.s:none', 'm_menu65.s has no label none'),
                ('unplaced', 'no label is called unplaced'),
                ('itemOn+x', 'the offset is not a number')]:
            with self.assertRaisesRegex(script.ScriptError, message):
                SYMBOLS.address(reference)


class Compile(unittest.TestCase):
    def test_times(self):
        self.assertEqual(compiled(
            'at 100 key down a\n'
            'key up a\n'
            'at +2s mouse 3 -4\n'
            'at 10s button down\n'
            'at +1.5s button up 1\n'), [
            '100 key 0 down', '+0 key 0 up', '+120 mouse 3 -4',
            '599 button 0 down', '+90 button 1 up'])

    def test_tics_are_waits_on_the_game_clock(self):
        self.assertEqual(compiled('at 70t shot a\nat +35t shot b\n'
                                  'at +100t stop\n'), [
            '+0 wait 0x02C6AF 4 ge 70 2100', '+0 shot a',
            '+0 wait 0x02C6AF 4 gain 35 1050', '+0 shot b',
            '+0 wait 0x02C6AF 4 gain 100 3000', '+0 stop'])
        self.assertEqual(compiled('at +1t note n\n')[0],
                         '+0 wait 0x02C6AF 4 gain 1 600')

    def test_press_and_type(self):
        self.assertEqual(compiled('press escape\npress up 30\n'
                                  'type iD1\nshot s\n'), [
            '+0 key 53 down', '+6 key 53 up',
            '+0 key 62 down', '+30 key 62 up',
            '+0 key 34 down', '+4 key 34 up',
            '+4 key 2 down', '+4 key 2 up',
            '+4 key 18 down', '+4 key 18 up',
            '+4 shot s'])

    def test_waits_and_pokes(self):
        self.assertEqual(compiled(
            'wait _g_gamestate == 3\n'
            'wait byte itemOn != 2 within 90\n'
            'wait long _g_gametic grows 1 within 2s\n'
            'wait itemOn+2 < 0x10\n'
            'wait itemOn >= 1\n'
            'poke long itemOn 0x12345678\n'
            'note done\nstop\n'), [
            '+0 wait 0x02C60E 2 eq 3 7191',
            '+0 wait 0x02C3EE 1 ne 2 90',
            '+0 wait 0x02C6AF 4 gain 1 120',
            '+0 wait 0x02C3F0 2 lt 16 7191',
            '+0 wait 0x02C3EE 2 ge 1 7191',
            '+0 poke 0x02C3EE 4 305419896',
            '+0 note done', '+0 stop'])

    def test_comments_and_blank_lines(self):
        self.assertEqual(compiled('# nothing\n\n   \nstop # the end\n'),
                         ['+0 stop'])
        text = script.compile_script('\n\nstop\n', SYMBOLS, 'x.script')
        self.assertEqual(text, '+0 stop  # x.script:3\n')

    def test_errors(self):
        for text, message in [
                ('jump', 'unknown action jump'),
                ('at 5', 'expected at WHEN ACTION'),
                ('at 1.5 stop', '1.5: frames and tics are whole'),
                ('at 5x stop', 'a time is N, Nf, Ns or Nt'),
                ('key down', 'expected key down|up NAME'),
                ('key sideways a', 'expected key down|up NAME'),
                ('key down nokey', "no key is called 'nokey'"),
                ('press a b', 'expected a number of frames'),
                ('type i-d', "type takes letters and digits, not '-'"),
                ('mouse 1', 'expected mouse DX DY'),
                ('mouse 1 x', 'mouse takes two whole numbers'),
                ('button down 2', r'expected button down\|up \[0\|1\]'),
                ('shot a/b', 'expected shot NAME'),
                ('note', 'expected note NAME'),
                ('wait itemOn = 1', 'expected wait'),
                ('wait itemOn == 1 within +2s', 'within takes frames'),
                ('wait byte itemOn == 256', '256 does not fit in 1 bytes'),
                ('wait itemOn == x', 'not a number: x'),
                ('poke itemOn', 'expected poke'),
                ('stop now', 'stop takes nothing')]:
            with self.assertRaisesRegex(script.ScriptError,
                                        't.script:2: ' + message):
                script.compile_script('# first\n' + text + '\n', SYMBOLS,
                                      't.script')


def log_text(*lines):
    return ''.join(' '.join(str(word) for word in line) + '\n'
                   for line in lines)


RENDER = 0x03e8be
LOOP = 0x0383d5
SECOND = marks.MASTER_HZ


class Marks(unittest.TestCase):
    def setUp(self):
        # A frame every half second, 1000 instructions and 3000 cycles
        # apart, then one twice as costly; notes at 0.2 s and 2.2 s.
        lines = [('note', 'a', SECOND // 5, 10, 1)]
        for i, (clock, cost) in enumerate(
                [(0.5, 0), (1.0, 1), (1.5, 2), (2.0, 4)]):
            lines.append(('mark', '%06X' % RENDER, int(clock * SECOND),
                          3000 * cost, 1000 * cost))
            lines.append(('mark', '%06X' % LOOP, int(clock * SECOND) + 5,
                          3000 * cost + 5, 1000 * cost + 1))
        lines.append(('note', 'b', int(2.2 * SECOND), 20000, 5000))
        lines.append(('end', '-', int(9 * SECOND), 900000000, 90000))
        self.entries = marks.parse(log_text(*lines))

    def test_parse(self):
        self.assertEqual(self.entries[0], marks.Entry('note', 'a',
                                                      SECOND // 5, 10, 1))
        self.assertAlmostEqual(self.entries[-1].seconds, 9.0)
        with self.assertRaisesRegex(ValueError, 'line 2 of the marks'):
            marks.parse('note a 1 2 3\nmark 1 2\n')

    def test_intervals(self):
        (interval,) = marks.intervals(self.entries, RENDER)
        self.assertEqual((interval.start, interval.end), ('a', 'b'))
        self.assertAlmostEqual(interval.seconds, 2.0, places=5)
        self.assertEqual(interval.rendered, 4)
        self.assertAlmostEqual(interval.frames_per_second, 2.0, places=5)
        self.assertEqual(interval.frames_measured, 3)
        self.assertEqual(interval.median_instructions, 1000)
        self.assertEqual(interval.median_cycles, 3000)

    def test_no_frames(self):
        entries = marks.parse(log_text(('note', 'a', 0, 0, 0),
                                       ('note', 'b', SECOND, 5, 5)))
        (interval,) = marks.intervals(entries, RENDER)
        self.assertEqual(interval.rendered, 0)
        self.assertIsNone(interval.median_cycles)

    def test_longest_gap_runs_to_the_end(self):
        gap = marks.longest_gap(self.entries, LOOP)
        self.assertEqual(gap['cycles'], 900000000 - (12000 + 5))
        self.assertAlmostEqual(gap['from'], 2.0, places=5)
        self.assertIsNone(marks.longest_gap(self.entries, 0x123456))


def dump(view_palette=0, status_palette=1, view_rows=True):
    """A screen dump: in the view (rows 0-167) row r has pixels of
    colours r % 16 and (r // 16) % 16 at the two ends when `view_rows`,
    else colour 0; the status bar has colour 5; the palettes are all
    different."""
    data = bytearray(shot.SCREEN + 2)
    for row in range(shot.ROWS):
        base = row * shot.ROW_BYTES
        if row < shot.STATUS_ROW:
            if view_rows:
                data[base] = (row % 16) << 4 | (row // 16) % 16
                data[base + 1] = 0x12
            data[shot.SCB + row] = view_palette
        else:
            data[base:base + shot.ROW_BYTES] = b'\x55' * shot.ROW_BYTES
            data[shot.SCB + row] = status_palette
    for number in range(16):
        for colour in range(16):
            struct.pack_into('<H', data, shot.PALETTES + 32 * number +
                             2 * colour, number << 8 | colour << 4 | 1)
    return bytes(data)


class ViewStats(unittest.TestCase):
    def test_a_view(self):
        stats = shot.view_stats(dump())
        self.assertEqual(stats.view_colours, 16)
        self.assertEqual(stats.distinct_rows, 168)
        # two colours of its own, 1 and 2, and 0 for the rest
        self.assertEqual(stats.row_colours, 5)
        self.assertTrue(stats.status_palettes_apart)
        self.assertEqual(stats.status_rows_in_view, 0)
        self.assertEqual(stats.window, (0, 0, 320, 168))
        self.assertTrue(shot.full_3d_view(stats))

    def test_flat_and_shared(self):
        stats = shot.view_stats(dump(status_palette=0, view_rows=False))
        self.assertEqual(stats.view_colours, 1)
        self.assertEqual(stats.distinct_rows, 1)
        self.assertFalse(stats.status_palettes_apart)
        self.assertFalse(shot.full_3d_view(stats))

    def test_window(self):
        # Colour 0 of palette 0 black: the view is the box of the other
        # pixels, rows 10-20 and pixels 8-11 (bytes 4 and 5).
        data = bytearray(dump(view_rows=False))
        struct.pack_into('<H', data, shot.PALETTES, 0)
        for row in range(10, 21):
            data[row * shot.ROW_BYTES + 4] = 0x11
            data[row * shot.ROW_BYTES + 5] = 0x11
        stats = shot.view_stats(bytes(data))
        self.assertEqual(stats.window, (8, 10, 4, 11))
        self.assertFalse(shot.full_3d_view(stats))
        blank = bytearray(dump(view_rows=False))
        struct.pack_into('<H', blank, shot.PALETTES, 0)
        self.assertEqual(shot.view_stats(bytes(blank)).window, (0, 0, 0, 0))

    def test_640_mode(self):
        with self.assertRaisesRegex(ValueError, '320-mode'):
            shot.view_stats(dump(view_palette=0x80))


def state(**changes):
    """A final state of the machine with nothing wrong."""
    base = {
        'end': {'reason': 'stop', 'pc': 0, 'line': 9}, 'seconds': 10.0,
        'text_page': ['  '] * 24,
        'unmodelled': {'io_reads': {'C039': 1}, 'io_writes': {},
                       'rom_reads': 0, 'rom_writes': 0, 'slot_rom_reads': 0,
                       'unmapped_reads': 0, 'unmapped_writes': 0,
                       'rom_read_sites': [], 'unmapped_read_sites': [],
                       'read_sites_lost': 0, 'adb_unknown_commands': 0},
        'firmware': {'errors': 0}}
    base.update(changes)
    return base


class Problems(unittest.TestCase):
    # The functions of KNOWN_READS and the symbols of what they read, at
    # made-up addresses.
    SYMBOLS = script.Symbols({'game': {'units': {
        'd_main65.s': {'displayCall': LOOP},
        'i_iigs65.s': {'I_Error': 0x046082, 'I_Quit': 0x04606a},
        'irq65.s': {'IIGS_StartInterrupts': 0x045600,
                    'IIGS_StopInterrupts': 0x045680, 'VECTORS': 0x00ffe0},
        'm_menu65.s': {'bmAccelOff': 0x04cc00, 'bmAccelBack': 0x04cc80,
                       'TW_ID': 0xbcff00}}}})

    def check(self, final, entries=None):
        if entries is None:
            entries = marks.parse(log_text(
                ('mark', '%06X' % LOOP, 100, 100, 10),
                ('end', '-', 200, 200, 20)))
        return run_script.problems(final, entries, self.SYMBOLS)

    def test_a_good_run(self):
        self.assertEqual(self.check(state()), [])

    def test_endings(self):
        text = ['I_Error: something'] + ['  '] * 23
        for end, message in [
                ({'reason': 'stop-pc', 'pc': 0x046082, 'line': 0},
                 r'reached i_iigs65.s:I_Error\+0 .* says: I_Error: something'),
                ({'reason': 'spin', 'pc': 0x046090, 'line': 0},
                 r'spins at i_iigs65.s:I_Error\+14'),
                ({'reason': 'opcode', 'pc': 0x0383d6, 'line': 0},
                 r'WDM or STP at d_main65.s:displayCall\+1'),
                ({'reason': 'timeout', 'pc': 0, 'line': 7},
                 'the wait of line 7 of the program timed out'),
                ({'reason': 'late', 'pc': 0, 'line': 3},
                 'line 3 of the program came after its frame'),
                ({'reason': 'frames', 'pc': 0, 'line': 0},
                 'hit its frames limit')]:
            (problem,) = self.check(state(end=end, text_page=text))
            self.assertRegex(problem, message)

    def test_script_lines(self):
        program = script.compile_script('at 5 stop\nwait itemOn == 1\n',
                                        SYMBOLS, 'x.script')
        final = state(end={'reason': 'timeout', 'pc': 0, 'line': 2})
        self.assertEqual(
            run_script.problems(final, marks.parse(log_text(
                ('mark', '%06X' % LOOP, 1, 1, 1), ('end', '-', 2, 2, 2))),
                self.SYMBOLS, program),
            ['the wait of x.script:2 timed out at 10.0 s'])

    def test_machine_gaps(self):
        final = state()
        final['unmodelled']['io_writes'] = {'C068': 2}
        final['unmodelled']['rom_writes'] = 1
        final['firmware']['errors'] = 3
        self.assertEqual(self.check(final), [
            'I/O registers not modelled: C068', 'rom_writes: 1',
            '3 firmware errors'])

    def reads(self, rom=(), unmapped=(), lost=0):
        """The problems of a run with these read sites, as (pc, first,
        last, count)."""
        final = state()
        missing = final['unmodelled']
        for kind, sites in (('rom', rom), ('unmapped', unmapped)):
            missing[kind + '_read_sites'] = [
                {'pc': pc, 'first': first, 'last': last, 'count': count}
                for pc, first, last, count in sites]
            missing[kind + '_reads'] = sum(s[3] for s in sites) + lost
        missing['read_sites_lost'] = lost
        return self.check(final)

    def test_known_reads(self):
        vectors = (0x045620, 0x00ffe0, 0x00ffff, 32)
        probe = (0x04cc1a, 0xbcff00, 0xbcff00, 1)
        self.assertEqual(self.reads([vectors], [probe]), [])
        # the count of each is part of what is known
        (problem,) = self.reads([vectors[:3] + (34,)], [probe])
        self.assertEqual(problem, 'rom reads of irq65.s:IIGS_StartInterrupts'
                                  ' from VECTORS: 34, not 32')
        # and so are the addresses and the function that reads
        (problem,) = self.reads([vectors], [(0x04cc1a, 0xbcff00, 0xbcff01,
                                             1)])
        self.assertEqual(problem, 'unmapped reads: 1 at $BCFF00-$BCFF01 by '
                                  'm_menu65.s:bmAccelOff+26 ($04CC1A)')
        (problem,) = self.reads([(0x045690, 0x00ffe0, 0x00ffff, 32)],
                                [probe])
        self.assertRegex(problem, r'^rom reads: 32 at \$00FFE0-\$00FFFF by '
                                  r'irq65.s:IIGS_StopInterrupts\+16')
        (problem,) = self.reads([], [(0x04cc1a, 0xe00000, 0xe00000, 1)])
        self.assertRegex(problem, r'^unmapped reads: 1 at \$E00000')
        (problem,) = self.reads([vectors], [probe], lost=3)
        self.assertIn('3 reads not placed', problem)

    def test_stuck_loop(self):
        stuck = marks.parse(log_text(
            ('mark', '%06X' % LOOP, 100, 100, 10),
            ('end', '-', 200, run_script.STUCK_CYCLES + 101, 20)))
        (problem,) = self.check(state(), stuck)
        self.assertIn('did not come round', problem)
        never = marks.parse(log_text(('end', '-', 200, 200, 20)))
        self.assertEqual(self.check(state(), never),
                         ['the main loop never ran'])


@unittest.skipUnless(make_image.LINKMAP.exists(),
                     '%s is missing: run python3 tools/v816/imgmatch.py '
                     'first' % make_image.LINKMAP.relative_to(support.ROOT))
class RealScripts(unittest.TestCase):
    """The coverage scripts and the example of the README compile
    against the game's link map."""

    @classmethod
    def setUpClass(cls):
        with open(str(make_image.LINKMAP)) as handle:
            cls.symbols = script.Symbols(json.load(handle))

    def test_coverage_scripts(self):
        paths = sorted((support.ROOT / 'coverage').glob('*.script'))
        self.assertEqual([p.stem for p in paths],
                         ['newgame', 'title', 'tour', 'viewsize'])
        for path in paths:
            program = script.compile_script(path.read_text(), self.symbols,
                                            path.name)
            self.assertEqual(program.splitlines()[-1].split()[1], 'stop',
                             path.name)

    def test_readme_example(self):
        readme = (support.ROOT / 'tools' / 'ref816' / 'README.md').read_text()
        example = re.search(r'shortened from .*:\n\n((?:    .*\n)+)',
                            readme).group(1)
        program = script.compile_script(
            ''.join(line[4:] + '\n' for line in example.splitlines()),
            self.symbols, 'README.md')
        self.assertIn('wait 0x02C3EC 2 eq 2 599', program)


if __name__ == '__main__':
    unittest.main()
