"""Tests of the replay captures (tools/ref816/capture.py) and of the record
decoder (tools/ref816/lists.py).

The decoder is tested on synthetic records. The capture tests run
coverage/newgame.script (three frames standing still in E1M1) and
coverage/title.script (two frames of the demo, the last with interrupts
inside the replay) twice each on ref816, a few seconds of host time, and
skip without build/release/doom-hd.hdv and build/linkmap.json. They
check the manifest format, that upstream's R_DrawLists run alone by
--call on a capture's "before" state writes exactly the captured bytes
and leaves the captured "after" screen byte for byte, and what it writes
on a poisoned screen.
"""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support
from ref816 import capture, lists, make_image, refimage, script, title
from test_ref816_machine import have_tools, needs_linkmap

# The layout of lists.inc, as the link map gives it for r_list65.s.
LAYOUT = lists.Layout(
    recbase=0x1d0000, xp_first=0xce, colw=0x027b0c, xpnext=0x027c4c,
    columns=160,
    kinds={0: 'K_TEX', 2: 'K_FILL', 6: 'K_TEXC', 8: 'K_FUZZ', 10: 'K_OVL',
           12: 'K_NEXT'},
    sizes={'K_TEX': 11, 'K_FILL': 5, 'K_TEXC': 7, 'K_FUZZ': 4, 'K_OVL': 4,
           'K_NEXT': 2},
    fields={'R_KIND': 0, 'R_ROW': 1, 'R_END': 2, 'R_B1': 3, 'R_B2': 4,
            'R_TF': 3, 'R_TI': 4, 'R_SF': 5, 'R_SI': 6, 'R_SRC': 7,
            'R_CMP': 10, 'R_TCSRC': 5, 'R_COUNT': 2, 'R_POS': 3,
            'R_KEEP': 2, 'R_COLOR': 3, 'R_PAGE': 1})


class Lists(unittest.TestCase):
    def test_colpage(self):
        self.assertEqual([lists.colpage(c) for c in (0, 8, 9, 113, 114, 159)],
                         [0x00, 0x08, 0x20, 0x88, 0xa0, 0xcd])

    def test_record_pages_are_the_capacity_of_lists_inc(self):
        runs = lists.record_pages(LAYOUT)
        self.assertEqual(runs, [(0x00, 9), (0x20, 105), (0xa0, 96)])
        self.assertEqual(sum(n for _, n in runs) * 256, 53760)

    def lists_memory(self, column_records):
        """Memory with the records of each column from its COLPAGE, and
        COLW at their ends; a K_NEXT is followed into its page."""
        memory = refimage.Memory()
        for column in range(LAYOUT.columns):
            memory.put(LAYOUT.colw + 2 * column,
                       bytes([0, lists.colpage(column)]))
        for column, parts in column_records.items():
            page, offset = lists.colpage(column), 0
            for data in parts:
                memory.put(LAYOUT.recbase + (page << 8) + offset, data)
                if data[0] == 12:
                    page, offset = data[1], 0
                else:
                    offset += len(data)
            memory.put(LAYOUT.colw + 2 * column, bytes([offset, page]))
        return memory

    def test_walk(self):
        tex = bytes([0, 10, 20, 0, 5, 0x80, 0, 0x34, 0x12, 0x2b, 70])
        texc = bytes([6, 30, 40, 0, 0, 0x00, 0x20])
        fill = bytes([2, 0, 10, 0x11, 0x22])
        memory = self.lists_memory({
            0: [fill, tex, bytes([12, 0xce]), texc],
            159: [bytes([8, 5, 3, 7])]})
        records = list(lists.walk(memory.get, LAYOUT))
        self.assertEqual([(r.column, r.kind) for r in records],
                         [(0, 'K_FILL'), (0, 'K_TEX'), (0, 'K_NEXT'),
                          (0, 'K_TEXC'), (159, 'K_FUZZ')])
        self.assertEqual(records[1].texels, 0x2b1234)
        self.assertEqual(records[3].texels, 0x2b2000)
        self.assertEqual(records[3].page, 0xce)
        self.assertEqual(lists.texel_ranges(records),
                         [(0x2b1234, 128), (0x2b2000, 128)])
        counts = lists.summary(records, LAYOUT)
        self.assertEqual((counts['records'], counts['bytes']),
                         (4, 5 + 11 + 2 + 7 + 4))

    def test_walk_refuses_an_unknown_kind(self):
        memory = self.lists_memory({3: [bytes([4, 0, 0, 0, 0])]})
        with self.assertRaises(lists.DecodeError):
            list(lists.walk(memory.get, LAYOUT))

    def test_merge_splits_at_banks(self):
        self.assertEqual(lists.merge([(0x2bff80, 0x2c0080), (0x2c0000,
                                                              0x2c0010)]),
                         [(0x2bff80, 0x80), (0x2c0000, 0x80)])


SETS = (capture.SETS[0],
        capture.Selection('irq', 'title', 'demo', 'demo-25s', 2, None))
# A pattern no drawer writes by chance everywhere.
POISON = bytes(((i * 7 + 3) ^ 0x5a) & 0xff for i in range(capture.PIXELS))


@have_tools
@support.needs_release
@needs_linkmap
class Captures(unittest.TestCase):
    """The frames are captured once for the class."""

    @classmethod
    def setUpClass(cls):
        title.build_machine()
        title.ensure_image()
        with open(str(make_image.LINKMAP)) as handle:
            linkmap = json.load(handle)
        cls.units = linkmap['game']['units']
        cls.entry = script.Symbols(linkmap).address(capture.ENTRY)
        cls.out = Path(tempfile.mkdtemp(prefix='test-captures-',
                                        dir=str(make_image.BUILD)))
        cls.manifests = {}
        try:
            for selection in SETS:
                cls.manifests[selection.key] = capture.run_selection(
                    selection, script.Symbols(linkmap), cls.units, cls.out,
                    keep_raw=False, check=True)
        except BaseException:
            shutil.rmtree(str(cls.out), ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.out), ignore_errors=True)

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.scratch))

    def all_manifests(self):
        return [m for key in self.manifests for m in self.manifests[key]]

    def test_the_frames_chosen(self):
        still = self.manifests['still']
        self.assertEqual([m['name'] for m in still],
                         ['still-1', 'still-2', 'still-3'])
        self.assertEqual([m['hit'] - still[0]['hit'] for m in still],
                         [0, 1, 2])
        self.assertTrue(all(m['note'] == 'still' for m in still))
        self.assertEqual(len(self.manifests['irq']), 2)
        tics = [m['gametic'] for m in still]
        self.assertEqual(tics, sorted(set(tics)))

    def test_manifest_format(self):
        for manifest in self.all_manifests():
            directory = self.out / manifest['name']
            self.assertEqual(manifest['format'], capture.FORMAT)
            self.assertEqual(manifest['entry']['address'], self.entry)
            registers = manifest['registers']
            self.assertEqual(registers['pbr'] << 16 | registers['pc'],
                             self.entry)
            self.assertTrue(manifest['returned'])
            self.assertEqual(manifest['problems'], [])
            self.assertEqual(manifest['early_flushes'], 0)
            self.assertGreater(manifest['records']['K_TEX'], 0)
            names = [f['name'] for f in manifest['files']]
            for name in ('records-00', 'records-20', 'records-a0', 'lists',
                         'screen', 'buffer', 'spans', 'weapon', 'colormaps',
                         'texels', 'context', 'screen-after', 'buffer-after',
                         'writes'):
                self.assertIn(name, names)
            before = []
            for f in manifest['files']:
                data = (directory / f['file']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 f['sha256'])
                self.assertIn(f['when'], ('before', 'after'))
                if f['format'] == 'raw':
                    self.assertEqual(len(data), f['size'])
                    self.assertEqual(f['at'], '$%02X:%04X' % (
                        f['address'] >> 16, f['address'] & 0xffff))
                    spans = [(f['address'], f['address'] + f['size'])]
                else:
                    image = refimage.parse(data)
                    self.assertEqual([[a, len(d)] for a, d in image.records],
                                     f['ranges'])
                    self.assertEqual(f['size'], sum(n for _, n in
                                                    f['ranges']))
                    spans = [(a, a + n) for a, n in f['ranges']]
                if f['when'] == 'before':
                    before += spans
            before.sort()
            for (a0, a1), (b0, b1) in zip(before, before[1:]):
                self.assertLessEqual(a1, b0, 'the "before" files overlap')
            context = refimage.read(directory / 'context.img')
            self.assertEqual(context.registers._asdict(), registers)

    def test_call_reproduces_the_after_screen(self):
        for manifest in self.all_manifests():
            directory = self.out / manifest['name']
            self.assertTrue(manifest['verified']['ok'], manifest['name'])
            state = capture.run_call(title.MACHINE, directory, manifest,
                                     self.scratch)
            self.assertEqual(state['end']['reason'], 'return')
            self.assertEqual(state['screen'],
                             (directory / 'screen-after.bin').read_bytes())
            self.assertEqual(state['buffer'],
                             (directory / 'buffer-after.bin').read_bytes())
            self.assertEqual(refimage.parse(state['writes']).records,
                             refimage.read(directory / 'writes.img').records)
            self.assertEqual(state['call']['instructions'],
                             manifest['replay']['instructions'])

    def test_interrupts_inside_the_replay_are_left_out(self):
        last = self.manifests['irq'][-1]
        self.assertGreater(last['replay']['interrupts']['count'], 0)
        self.assertTrue(last['verified']['ok'])
        stack = last['registers']['s']
        for address in last['written_then_changed_by_interrupts']:
            self.assertLessEqual(address, stack)

    def test_poisoned_screen(self):
        manifest = self.manifests['still'][0]
        if manifest['records']['K_FUZZ']:
            self.skipTest('the frame has shadows, which read the screen')
        directory = self.out / manifest['name']
        written = []
        for number, pattern in enumerate((POISON, bytes(b ^ 0xff for b in
                                                        POISON))):
            path = self.scratch / ('poison-%d.bin' % number)
            path.write_bytes(pattern)
            state = capture.run_call(
                title.MACHINE, directory, manifest, self.scratch / str(number),
                [(capture.SCREEN, path), (capture.BUFFER, path)])
            writes = refimage.load(refimage.parse(state['writes']))
            screen = set(i for i in range(capture.PIXELS)
                         if writes.is_known(capture.SCREEN + i))
            after = (directory / 'screen-after.bin').read_bytes()
            for i in range(capture.PIXELS):
                if i in screen:
                    self.assertEqual(state['screen'][i], after[i])
                else:
                    self.assertEqual(state['screen'][i], pattern[i])
            self.assertEqual(state['buffer'][:capture.PIXELS],
                             state['screen'][:capture.PIXELS])
            self.assertEqual(len(screen),
                             manifest['screen']['written_pixels'])
            written.append(screen)
        self.assertEqual(written[0], written[1])
        # Standing still, the replay writes the walls and the fills its
        # spans of the frame before did not show: not the whole view.
        self.assertLess(len(written[0]), capture.VIEW_ROWS * capture.ROW)


if __name__ == '__main__':
    unittest.main()
