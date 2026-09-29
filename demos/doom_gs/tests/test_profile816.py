"""Tests of the profile report (tools/ref816/profile816.py) and its parts,
the code map (codemap.py) and the measures (measures.py), on a small
synthetic trace and link map.

The synthetic trace has three frames whose numbers grow frame by frame,
so that medians and ranges are known; the link map has a fragment of the
vendor runtime, whose label, rows and figures must never reach the
report. A variant of the trace adds game tics and a firmware trap.
"""

import re
import unittest

import support  # noqa: F401  (puts tools/ on the path)
from ref816 import codemap, measures, profile816, script, tracefile

VENDOR_LABEL = 'vendorSecretLabel'
ENTRIES = {'P_Ticker': 0x04b000, 'vwFrame': 0x04d000,
           'R_FillStamps': 0x05d000, 'R_RenderPlayerView': 0x03e800,
           'R_RenderBSPNode': 0x034800, 'R_StoreWallRange': 0x034900,
           'R_RenderSegLoop': 0x032000, 'R_AddSprites': 0x035000,
           'R_DrawLists': 0x059000, 'ST_doPaletteStuff': 0x03e700,
           'ST_Drawer': 0x03e500, 'HU_Drawer': 0x044000,
           'M_Ticker': 0x040a00, 'M_Drawer': 0x040d00,
           'I_FinishUpdate': 0x036700}

LINKMAP = {'game': {
    'fragments': [
        {'unit': 'r_seg65.s', 'section': 'segcode', 'kind': 'text',
         'address': 0x032000, 'size': 0x100,
         'labels': {'R_RenderSegLoop': 0x032000, 'segInner': 0x032040}},
        {'unit': 'cal_integer.s', 'section': 'bspcode', 'kind': 'text',
         'address': 0x034000, 'size': 0x40,
         'labels': {VENDOR_LABEL: 0x034000}},
        {'unit': 'r_list65.s', 'section': 'hotlist', 'kind': 'text',
         'address': 0x059000, 'size': 0x100,
         'labels': {'R_DrawLists': 0x059000, 'patchSite': 0x059010}},
        {'unit': 'g.s', 'section': 'near', 'kind': 'data',
         'address': 0x020000, 'size': 0x100, 'labels': {}},
        {'unit': 'g.s', 'section': 'dropped', 'kind': 'text',
         'address': None, 'size': 0, 'labels': {}},
    ],
    'sections': {'segcode': {'first': 0x032000, 'last': 0x0320ff},
                 'bspcode': {'first': 0x034000, 'last': 0x03403f},
                 'hotlist': {'first': 0x059000, 'last': 0x0590ff},
                 'near': {'first': 0x020000, 'last': 0x0200ff},
                 'stack': {'first': 0x000b00, 'last': 0x003fff}},
    'units': {
        'g.s': dict(ENTRIES, MM_SQL=0x130000, MM_WINDOW=0x2a,
                    MM_WINDOW_END=0x40, MM_X=0x02c000),
        'r_seg65.s': {'MM_SQL': 0x130000, 'MM_WINDOW': 0x2a,
                      'MM_WINDOW_END': 0x40, 'segInner': 0x032040},
        'r_frame65.s': {'drawMasked': 0x03e900},
        'p_think65.s': {'LOGIC_SP': 0x1b6f},
        'cal_integer.s': {VENDOR_LABEL: 0x034000},
    },
}}
PHASE_NAMES = ['other', 'interrupt'] + [p.key for p in profile816.PHASES
                                        if p.key not in ('other',
                                                         'interrupt')]


def frame_lines(index, k, start, tics=False):
    """Frame `index` of the synthetic trace, whose numbers grow with k;
    `start` is (clock, cycles, instructions). With `tics`, the frame also
    runs two game tics of 4 instructions and a firmware trap of 2,000
    cycles. Returns (lines, end)."""
    ph = {name: i for i, name in enumerate(PHASE_NAMES)}
    cost = {ph['seg']: (100 * k, 300 * k), ph['replay']: (50, 200),
            ph['other']: (10, 40)}
    firmware = 2000 if tics else 0
    if tics:
        cost[ph['tics']] = (8, 24)
    instructions = sum(c[0] for c in cost.values())
    cycles = sum(c[1] for c in cost.values()) + firmware
    end = (start[0] + 5 * cycles, start[1] + cycles,
           start[2] + instructions)
    lines = ['frame %d %d %d %d %d %d %d' % ((index,) + start + end)]
    lines += ['cost %d %d %d' % (p, i, c) for p, (i, c) in cost.items()]
    if tics:
        lines += ['enters %d 2' % ph['tics'], 'firmware 1 %d' % firmware]
    lines += ['access %d data 7F %d 0' % (ph['seg'], 10 * k),
              'access %d direct 00 30 4' % ph['seg'],
              'access %d data 02 7 1' % ph['seg'],
              'access %d data 01 0 20' % ph['replay'],
              'access %d data 1D 5 0' % ph['replay'],
              'lines 7F 2 1 1 0 0 0', 'lines 01 4 2 1 4 2 1',
              'lines 02 1 1 1 1 1 1', 'lines 1D 1 1 1 0 0 0',
              'switches %d 8' % ph['replay'], 'switches %d 2' % ph['seg'],
              'stack %d 3FF0 -' % ph['seg'],
              'stack %d 3FF8 1B60' % ph['tics'],
              'screen %d 0 20 5' % ph['replay'],
              'heat %d 032000 %d 3' % (ph['seg'], 90 * k),
              'heat %d 032040 %d 2' % (ph['seg'], 10 * k),
              'heat %d 059000 45 4' % ph['replay'],
              'heat %d 059010 5 1' % ph['replay'],
              # "Everything else": the vendor runtime (9) and a label of
              # the game (1)
              'heat %d 034000 9 3' % ph['other'],
              'heat %d 059080 1 1' % ph['other'],
              'unclosed 0']
    return lines, end


def synthetic_trace(tics=False):
    lines = ['ref816-trace 1']
    lines += ['phase %d %s' % (i, n) for i, n in enumerate(PHASE_NAMES)]
    lines += ['near 02', 'split 1B6F', 'note start 0 0 0']
    start = (1000, 200, 50)
    for index, k in enumerate((1, 2, 3)):
        more, start = frame_lines(index, k, start, tics)
        lines += more
    lines += ['smc %d 059010 032041 2' % i for i in range(3)]
    lines += ['smc-mixed 0',
              'width 032000 mx 0', 'width 032000 mx 2',
              'width 032000 d 0', 'width 032000 dbr 2',
              'width 032040 mx 2', 'width 032040 d 0',
              'width 032040 d 900', 'width 032040 dbr 2',
              'width 034000 mx 2', 'width 034000 d 0',
              'width 034000 dbr 2', 'end 99999 9999 999', '']
    return tracefile.parse('\n'.join(lines))


def cell(text, row, column):
    """The cell of the Markdown table row whose first cell is `row`."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells[0] == row:
            return cells[column]
    raise KeyError(row)


def tables(text):
    """The Markdown tables of `text`, each a list of rows of cells, the
    header and its rule left out."""
    found, rows = [], None
    for line in text.splitlines() + ['']:
        if line.startswith('|'):
            if rows is None:
                rows = []
            rows.append([c.strip() for c in line.strip().strip('|')
                         .split('|')])
        elif rows is not None:
            found.append(rows[2:])
            rows = None
    return found


def figure(text):
    return int(text.split()[0].replace(',', ''))


class CodeMap(unittest.TestCase):
    def setUp(self):
        self.code = codemap.CodeMap(LINKMAP)

    def test_places(self):
        place = self.code.place(0x032043)
        self.assertEqual((place.section, place.unit, place.label,
                          place.offset), ('segcode', 'r_seg65.s',
                                          'segInner', 3))
        self.assertEqual(str(place), 'r_seg65.s:segInner+3')
        self.assertEqual(place.function, 'r_seg65.s:segInner')
        self.assertEqual(str(self.code.place(0x7f0000)),
                         '$7F0000 (outside the image)')

    def test_the_vendor_runtime_is_anonymous(self):
        place = self.code.place(0x034010)
        self.assertEqual((place.section, place.unit, place.label),
                         (codemap.VENDOR, codemap.VENDOR, None))
        self.assertEqual(str(place), codemap.VENDOR)
        self.assertNotIn(VENDOR_LABEL, str(place) + place.function)

    def test_banks(self):
        self.assertEqual(self.code.bank(0x02), 'near')
        self.assertEqual(self.code.bank(0x13), 'MM_SQL')
        self.assertEqual(self.code.bank(0x2b), 'level window')
        self.assertEqual(self.code.bank(0x40), '')
        # MM_X is a label of one unit, not an equate of the memory map
        self.assertNotIn('MM_X', self.code.bank(0x02))


class Measures(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(measures.spread([3, 1, 2]), (2, 1, 3))
        self.assertEqual(measures.spread([]), (0, 0, 0))

    def test_hot_sets(self):
        heat = {0x100: (90, 3), 0x200: (9, 2), 0x300: (1, 4)}
        self.assertEqual(measures.hot_set(heat, 0.9), [(0x100, 3)])
        self.assertEqual(measures.hot_set(heat, 0.99),
                         [(0x100, 3), (0x200, 2)])
        self.assertEqual(measures.byte_count(measures.executed(heat)), 9)
        # overlapping instructions count their bytes once
        self.assertEqual(measures.byte_count([(0, 3), (2, 3)]), 5)
        self.assertAlmostEqual(measures.coverage(heat, 2), 0.99)
        self.assertEqual(measures.bytes_by(
            measures.executed(heat), lambda a: 'low' if a < 0x250 else
            'high'), {'low': 5, 'high': 4})

    def test_the_trace(self):
        trace = synthetic_trace()
        measures.check(trace)
        seg = trace.phase('seg')
        self.assertEqual(measures.phase_cost(trace, [seg], 0),
                         [100, 200, 300])
        self.assertEqual(measures.accesses(
            trace, lambda p, s, b: measures.access_class(trace, s, b) ==
            'far'), ([15, 25, 35], [20, 20, 20]))
        self.assertEqual(measures.far_banks(trace), [0x01, 0x1d, 0x7f])
        self.assertEqual(measures.switches(trace), [10, 10, 10])
        self.assertEqual(measures.stack_lows(trace, True), [0x1b60] * 3)
        self.assertEqual(measures.screen(trace, 3), [20] * 3)
        groups = measures.smc_groups(trace, lambda a: 'target')
        self.assertEqual(groups, [measures.SmcGroup(0x059010, 'target',
                                                    [2, 2, 2], 1)])

    def test_check_finds_lost_counts(self):
        trace = synthetic_trace()
        trace.frames[1].cost[0] = (0, 0)
        with self.assertRaisesRegex(ValueError, 'frame 1'):
            measures.check(trace)


class Document(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = codemap.CodeMap(LINKMAP)
        cls.symbols = script.Symbols(LINKMAP)
        trace = synthetic_trace()
        cls.traces = {s.key: trace for s in profile816.SCENARIOS}
        cls.template = profile816.TEMPLATE.read_text()
        cls.withheld = {}
        cls.text = profile816.document(cls.traces, cls.code, cls.symbols,
                                       cls.template, cls.withheld)

    def section(self, title):
        """The text of section `title` (a ## heading) of the report."""
        start = self.text.index('## ' + title)
        end = self.text.find('\n## ', start + 1)
        return self.text[start:end if end >= 0 else None]

    def test_every_placeholder_is_filled(self):
        self.assertNotRegex(self.text, r'\{[a-z0-9_]+\}')

    def test_the_same_trace_gives_the_same_text(self):
        again = profile816.document(self.traces, self.code, self.symbols,
                                    self.template)
        self.assertEqual(again, self.text)

    def test_the_vendor_runtime_is_not_named(self):
        self.assertNotIn(VENDOR_LABEL, self.text)
        self.assertNotIn('cal_integer', self.text)
        self.assertNotIn(codemap.VENDOR, self.text)
        # "vendor" only in the paragraph that says it is folded, which
        # has no figure
        paragraphs = [p for p in self.text.split('\n\n')
                      if 'vendor' in p.lower()]
        self.assertEqual(len(paragraphs), 1)
        self.assertIn('folded into the other rows', paragraphs[0])
        self.assertNotRegex(paragraphs[0], r'[0-9]')

    def test_the_vendor_runtime_has_no_row_or_figure(self):
        rows = [row for t in tables(self.text) for row in t]
        self.assertFalse([row for row in rows if 'vendor' in row[0].lower()])
        # Its rows are kept for build/ only: 9 of the 30 instructions of
        # "Everything else", 3 bytes of code in the 99% set, none in the
        # 90% set.
        still = self.withheld['still']
        self.assertEqual(still['other'], [[codemap.VENDOR, '9', '90.0%']])
        self.assertEqual(still['heat_sections'],
                         [[codemap.VENDOR, '3', '0', '3', '3']])
        self.assertEqual(still['heat_files'], still['heat_sections'])
        self.assertEqual(still['smc'], [])
        # and none of their figures is a row of the report
        for scenario in profile816.SCENARIOS:
            for name, hidden in self.withheld[scenario.key].items():
                for row in hidden:
                    self.assertNotIn(row[1:], [r[1:] for r in rows], name)
        # It is in the others row with code of the game: "Everything
        # else" has only it and one label of the game, which joins it.
        other = tables(self.section('1. Instructions'))[1]
        self.assertEqual(other, [['2 others', '10', '100.0%']])
        # In the tables of code heat the rows add up to the total, so that
        # no difference gives its figures.
        heat = tables(self.section('3. Code heat'))
        for table in heat[1:3]:
            self.assertEqual(table[-1][0], '**All**')
            for column in range(1, 5):
                self.assertEqual(sum(figure(r[column]) for r in table[:-1]),
                                 figure(table[-1][column]))
        self.assertEqual([r[0] for r in heat[1]],
                         ['hotlist', '2 others', '**All**'])

    def test_fold(self):
        vendor = profile816.is_vendor
        names = ['a', codemap.VENDOR, 'b', 'c', 'd']
        # the withheld go with the rest, which a limit leaves
        self.assertEqual(profile816.fold(names, 2, vendor),
                         (['a', 'b'], ['c', 'd'], [codemap.VENDOR]))
        # never alone: the last shown joins them
        self.assertEqual(profile816.fold(names, None, vendor),
                         (['a', 'b', 'c'], ['d'], [codemap.VENDOR]))
        self.assertEqual(profile816.fold([codemap.VENDOR], None, vendor),
                         ([], [], [codemap.VENDOR]))
        self.assertEqual(profile816.fold(['a', 'b'], None, vendor),
                         (['a', 'b'], [], []))

    def test_phases(self):
        phases = self.section('1. Instructions')
        self.assertEqual(cell(phases, 'Seg loops', 1), '200 (100-300)')
        self.assertEqual(cell(phases, 'Seg loops', 2), '600 (300-900)')
        self.assertEqual(cell(phases, 'Record replay', 1), '50')
        self.assertEqual(cell(phases, '**Frame**', 1), '260 (160-360)')
        # the seg loops' share of all the cycles: 1,800 of 2,520
        self.assertEqual(cell(phases, 'Seg loops', 3), '71.4%')

    def test_accesses(self):
        accesses = self.section('2. Memory')
        self.assertEqual(cell(accesses, 'Far data, all other banks', 1),
                         '25 (15-35)')
        self.assertEqual(cell(accesses, 'Direct page', 2), '4')
        self.assertEqual(cell(accesses, '$7F', 2), '20 (10-30)')
        self.assertEqual(cell(accesses, '$02', 1), 'near data (near)')
        self.assertEqual(cell(accesses, '**Far**', 4), '7')
        self.assertEqual(cell(accesses, 'Record replay', 3), '8')

    def test_heat(self):
        heat = self.section('3. Code heat')
        self.assertEqual(cell(heat, 'Executed at least once', 1), '14')
        # frame 1 runs 90, 45, 10, 9, 5 and 1 instructions at 032000,
        # 059000, 032040, 034000, 059010 and 059080 (3, 4, 2, 3, 1 and 1
        # bytes). 90% of its 160 are the first three, 9 bytes; 99% (158.4)
        # needs the first five, 13 bytes. The other frames come out the
        # same.
        self.assertEqual(cell(heat, '90% of the instructions', 1), '9')
        self.assertEqual(cell(heat, '99% of the instructions', 1), '13')
        # hotlist has 059000, 059010 and 059080; segcode, the smallest,
        # joins the vendor runtime in the others row
        self.assertEqual(cell(heat, 'hotlist', 1), '6')
        self.assertEqual(cell(heat, '2 others', 1), '8')

    def test_widths_stack_screen_and_smc(self):
        self.assertEqual(cell(self.section('4. Register'), '(M, X)', 2), '1')
        self.assertEqual(cell(self.section('4. Register'), 'D', 2), '1')
        stack = self.section('6. Stack')
        self.assertEqual(cell(stack, 'Tic stack (top $1B6F)', 4), '15')
        self.assertEqual(cell(stack, 'Frame stack (top $3FFF)', 4), '15')
        screen = self.section('7. Screen')
        self.assertEqual(cell(screen, 'All', 1), '20')
        self.assertEqual(cell(screen, 'All', 2), '5')
        smc = self.section('5. Self')
        self.assertEqual(cell(smc, 'r_list65.s:patchSite+0 ($059010)', 1),
                         'r_seg65.s:segInner')
        self.assertEqual(cell(smc, 'r_list65.s:patchSite+0 ($059010)', 2),
                         '2')

    def test_assumptions(self):
        table = self.section('8. The assumptions')
        # P2: the frame without the replay
        self.assertEqual(cell(table, 'P2', 3), '210 (110-310)')
        self.assertEqual(cell(table, 'P8', 3), '20 written, 5 changed')
        self.assertTrue(re.search(r'\| P4 \|.*\| 100\.0% \|', table))

    def test_tics_and_firmware(self):
        trace = synthetic_trace(tics=True)
        text = profile816.document(
            {s.key: trace for s in profile816.SCENARIOS}, self.code,
            self.symbols, self.template)
        phases = text[text.index('## 1.'):text.index('## 2.')]
        # 2,000 cycles a frame in no phase: 6,000 of 8,592
        self.assertEqual(cell(phases, "Firmware traps (the machine's)", 1),
                         '0')
        self.assertEqual(cell(phases, "Firmware traps (the machine's)", 2),
                         '2,000')
        self.assertEqual(cell(phases, "Firmware traps (the machine's)", 3),
                         '69.8%')
        self.assertEqual(cell(phases, 'Game tics', 2), '24')
        self.assertEqual(cell(phases, '**Frame**', 2),
                         '2,864 (2,564-3,164)')
        self.assertIn('6,000\ncycles in the frames standing still', text)
        table = text[text.index('## 8.'):]
        # P2 has the tics, P2' not; one tic is 8 instructions over 2 calls
        self.assertEqual(cell(table, 'P2', 3), '218 (118-318)')
        self.assertEqual(cell(table, "P2'", 3), '210 (110-310)')
        self.assertEqual(cell(table, "P2''", 3), '4')
        self.assertIn('tics the frame runs: 2 standing still', table)

    def test_widths_json(self):
        data = profile816.widths_json(list(self.traces.values()), self.code)
        self.assertEqual(data['summary']['executed'], 3)
        self.assertEqual(data['summary']['more_than_one_mx'], 1)
        entry = data['addresses']['032000']
        self.assertEqual(entry['place'], 'r_seg65.s:R_RenderSegLoop+0')
        self.assertEqual(entry['flags'], [{'e': 0, 'm': 0, 'x': 0},
                                          {'e': 0, 'm': 1, 'x': 0}])
        self.assertEqual(data['addresses']['034000']['place'],
                         codemap.VENDOR)


class TraceOptions(unittest.TestCase):
    def test_options(self):
        symbols = script.Symbols(LINKMAP)
        options = profile816.trace_options(
            symbols, profile816.SCENARIOS[0], 'x.trace')
        text = ' '.join(options)
        self.assertIn('--trace x.trace --trace-frame 03E800', text)
        self.assertIn('--trace-from still --trace-to still-10s', text)
        self.assertIn('--trace-stack-split 1B6F', text)
        self.assertIn('--trace-near 02', text)
        self.assertIn('--trace-phase masked=03E900', text)
        self.assertEqual(options.count('--trace-phase'),
                         sum(len(p.entries) for p in profile816.PHASES))


if __name__ == '__main__':
    unittest.main()
