"""Milestone 11, first half, part s2cap (docs/SCREENS.md 1.6, 6.1, 6.2,
7.3): the reference captures (tools/native/s2cap.py), the injection
(tools/native/s2state.py) and the six scripts of coverage/m11/.

Without build/ only the parts that need nothing: the //e key table
stand-in and the case codec on a hand-made case. With ref816 and the
release image (python3 tools/ref816/title.py, MILESTONES.md "Setting
up"): the points resolve where the sources put them; a capture of
signs.script made twice gives the same files; its checks (decoding, PV in
every level frame, S_UpdateSounds once a turn with isPlaying exact, the
injection of every case for every screen read back equal on the host and,
for a sample, on a2vm with part s2lay's test image, the two-run screens,
the script's goals); the //e key names and table poked into ref816 and
drawn by upstream's key setup page; the four planted bugs of 7.3, each in
a scratch copy: PD1 at I_FinishUpdate's entry (the two-run check fails),
a word field injected as a byte, the poison not covering a marked byte,
S_UpdateSounds logged without jumps=1 (its count check fails). With the
captured cases of build/native/m11/cases (python3 tools/native/s2cap.py
--capture): their size under 60 MB and every run's index clean.

Run by name: python3 tools/testpar.py tests/test_m11_s2cap.py
"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support

from native import s2cap as C, s2state as ST  # noqa: E402

ROOT = support.ROOT
TOOLS = ROOT / 'tools' / 'native'
REF = ROOT / 'build' / 'ref816'


def ready() -> bool:
    return all(p.exists() for p in (REF / 'ref816', REF / 'memory.img',
                                    REF / 'disk.hdv',
                                    ROOT / 'build' / 'linkmap.json'))


READY = ready()
WHY = ('needs build/ref816/ref816, its memory.img and disk.hdv and '
       'build/linkmap.json (python3 tools/ref816/title.py)')
needs_ref = unittest.skipUnless(READY, WHY)
HAVE_S2LAY = (C.M11 / 's2lay' / 's2lt.map').exists()

PLANTED = [0]


def scratch_module(tmp: Path, name: str, bugs):
    """tools/native/NAME.py copied into tmp with each (old, new) applied
    once, imported under its own name (its imports are the tree's)."""
    text = (TOOLS / (name + '.py')).read_text()
    for old, new in bugs:
        if text.count(old) != 1:
            raise AssertionError('the bug no longer applies to %s: %r'
                                 % (name, old))
        text = text.replace(old, new)
    PLANTED[0] += 1
    stem = 'planted_%s_%d' % (name, PLANTED[0])
    path = tmp / (stem + '.py')
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scratch_dir() -> Path:
    """A directory of this test's own: under build/native/m11/s2cap when
    build/ exists, else a tempfile one (the caller deletes it)."""
    if not (ROOT / 'build').exists():
        return Path(tempfile.mkdtemp(prefix='s2cap-test-'))
    C.WORK.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='test-', dir=str(C.WORK)))


class KeysAndCodec(unittest.TestCase):
    def test_apple2e_keys_fit_upstreams_tables(self):
        names, table = ST.apple2e_keys()
        self.assertEqual(len(names), 128)
        self.assertEqual(len(table), 128)
        self.assertTrue(all(len(n) <= 7 for n in names))
        # the four pseudo-keys in the folded lower-case codes (2.4)
        self.assertEqual(names[0x70:0x74], ['MOUSE 2', 'MOUSE 1', 'O-APPLE',
                                            'S-APPLE'])
        self.assertEqual(table[0x72][0], ST.KEY['FIRE'])
        self.assertEqual(names[0x1B], 'ESC')
        self.assertTrue(all(names[c] == '' for c in range(0x61, 0x70)))

    def test_case_codec_round_trip(self):
        tmp = scratch_dir()
        try:
            store = C.BlobStore(tmp)
            screen = bytes(range(256)) * 128
            state = bytes(range(100))
            pd0 = C.Dump('PD0:display', {'cycles': 1}, ((0x02C000, 100),),
                         state)
            cb = C.Dump('CB', {'names': ['SCREEN'], 'from': {}},
                        (C.SCREEN,), screen)
            pd1 = C.Dump('PD1', {'cycles': 2}, ((0x02C000, 100),),
                         state[:50] + bytes(50))
            blob = C.encode_case({'kind': 'frame'}, [pd0, cb, pd1], store)
            case = C.decode_case(blob, store)
            self.assertEqual(case.before.data, state)
            self.assertEqual(case.screen_before, screen)
            self.assertEqual(case.after.data, pd1.data)
            self.assertEqual(case.dumps[2].ranges, ((0x02C000, 100),))
            # the same screen again is one blob
            C.encode_case({'kind': 'frame'}, [pd0, cb, pd1], store)
            self.assertEqual(len(store.keys), 1)
        finally:
            shutil.rmtree(str(tmp))


@needs_ref
class Points(unittest.TestCase):
    def test_points_resolve_where_the_sources_put_them(self):
        p = C.places()
        code = C.code()
        # PD1 the instruction after displayCall's JSR; PW a jsr in
        # I_FinishUpdate; every writer return is just after an RTL or a
        # call
        self.assertEqual(code.get(p.display_call, 1)[0], C.JSR)
        self.assertEqual(p.frame_end, p.display_call + 3)
        screens = dict((n, ats) for n, _, ats in p.carried)['SCREEN']
        rtls = [a for a in screens if code.get(a, 1)[0] == C.RTL]
        # I_FinishUpdate's two, I_ShowDirty's, titleWipe's, and bmSignOff's
        # jsr bmSignBox that returns onto its rtl
        self.assertEqual(len(rtls), 5)
        self.assertIn(p.black_colors + 3, rtls)
        self.assertIn(p.show_dirty + 3, rtls)
        pts = C.points(p)
        self.assertLessEqual(len(pts), 64)
        self.assertTrue(all(len(x.ranges) <= 32 for x in pts))
        self.assertEqual(C.points(p, screens=False), [])
        names = [n for n, _ in C.routines()]
        self.assertIn('S_UpdateSounds', names)
        self.assertIn('jumps=1', dict(C.routines())['S_UpdateSounds'])
        self.assertNotIn('jumps=1', dict(C.routines(False))['S_UpdateSounds'])


@needs_ref
class Capture(unittest.TestCase):
    """signs.script captured twice and checked as the checkpoint does."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = scratch_dir()
        cls.index = C.capture('signs', cls.tmp / 'signs')
        cls.again = C.capture('signs', cls.tmp / 'again' / 'signs')
        cls.rc = C.RunCases(cls.tmp / 'signs')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp))

    def test_twice_the_same(self):
        self.assertEqual(C.same_capture(self.tmp / 'signs',
                                        self.tmp / 'again' / 'signs'), [])
        self.assertEqual(self.index['problems'], [])
        self.assertLessEqual(self.index['traffic'], C.PIPE_LIMIT)

    def test_frames_decode_and_pv_in_every_level_frame(self):
        f = C.check_frames(self.rc)
        self.assertEqual(f['decode_problems'], [])
        self.assertEqual(f['pv_problems'], [])
        self.assertGreater(f['level'], 0)
        self.assertEqual(f['pv'], f['level'] + f['paused'])

    def test_updatesounds_once_a_turn(self):
        s = C.check_sounds(self.rc.calls(), True)
        self.assertEqual(s['problems'], [])
        self.assertGreater(s['updates'], 0)

    def test_injection_reads_back_on_the_host(self):
        r = C.check_injection(self.rc)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['unfit'], {})
        self.assertGreater(r['injections'], 0)

    @unittest.skipUnless(HAVE_S2LAY, 'needs part s2lay\'s build '
                         '(make -C src/native -f m11.mk part P=s2lay)')
    def test_injection_reads_back_on_a2vm(self):
        r = C.a2vm_injection(self.rc, [0])
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['runs'], 2)

    def test_two_run(self):
        r = C.two_run('signs', self.rc, 3)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['checked'], 3)

    def test_goals(self):
        goals = C.goals_check('signs', self.rc)
        self.assertTrue(goals)
        self.assertEqual([g for g in goals if not g.startswith('ok ')], [])


@needs_ref
class KeyPoke(unittest.TestCase):
    def test_the_2e_names_and_table_drawn_by_the_key_setup(self):
        names, table = ST.apple2e_keys()
        tmp = scratch_dir()
        try:
            menus = (ROOT / 'coverage' / 'm11' / 'menus.script').read_text()
            cut = menus.index('wait m_menu65.s:currentMenu == 8 within 10s')
            script = tmp / 'keys.script'
            script.write_text(menus[:cut] + 'wait m_menu65.s:currentMenu == '
                              '8 within 10s\nat +3s stop\n')   # (its draw: 1.4 s)
            point = 'pc=%06X,if=%06X:2:eq:8,hits=1' % (
                C.sym('m_menu65.s:M_Drawer'), C.sym('m_menu65.s:currentMenu'))
            pokes = tmp / 'keys.poke'
            pokes.write_text(ST.keys_poke(names, table, point))
            idx = C.capture('menus', tmp / 'keys', pokes=pokes,
                            script_path=script)
            self.assertEqual(idx['problems'], [])
            rc = C.RunCases(tmp / 'keys')
            want_names = b''.join(n.encode() + bytes(8 - len(n))
                                  for n in names)
            want_table = b''.join(bytes([k, ch]) for k, ch in table)
            drawn = [d for _, c in rc.frames() for d in c.all('PDF')
                     if C.val(d, 'm_menu65.s:currentMenu') == 8]
            self.assertTrue(drawn)
            last = drawn[-1]
            self.assertEqual(last.get(C.sym('m_menu65.s:keyNames'), 1024),
                             want_names)
            self.assertEqual(last.get(C.sym('i_iigs65.s:keyTable'), 256),
                             want_table)
        finally:
            shutil.rmtree(str(tmp))


@needs_ref
class Planted(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch_dir()

    def tearDown(self):
        shutil.rmtree(str(self.tmp))

    def test_pd1_at_finish_updates_entry_fails_the_two_run_check(self):
        bad = scratch_module(self.tmp, 's2cap', [(
            "    carried = (('SCREEN', SCREEN, tuple(sorted(rtls + [show + 3] "
            "+ box +",
            "    carried = (('SCREEN', SCREEN, tuple(sorted([finish, show] + "
            "box +")])
        bad.capture('signs', self.tmp / 'signs')
        rc = C.RunCases(self.tmp / 'signs')
        r = C.two_run('signs', rc, 3)
        self.assertTrue(r['problems'], r)
        self.assertTrue(any('differ from the run to cycle' in x
                            for x in r['problems']))

    def _case(self):
        rc = C.RunCases(C.CASES / 'demo3') \
            if (C.CASES / 'demo3' / 'index.json').exists() else None
        if rc is None:
            C.capture('signs', self.tmp / 'signs')
            rc = C.RunCases(self.tmp / 'signs')
        for e, case in rc.frames():
            if case.one('PDF') is not None and ST.marked(case):
                return case
        raise AssertionError('no frame with marked bytes')

    def test_a_word_field_injected_as_a_byte(self):
        case = self._case()
        good = ST.inject(case, 'stbar', 0xA5)
        self.assertEqual(ST.read_back(ST.host_of(good).get, good), [])
        bad = scratch_module(self.tmp, 's2state', [(
            "        return (value & 0xFFFF).to_bytes(2, 'little'), True",
            "        return bytes([value & 0xFF]), True")])
        inj = bad.inject(case, 'stbar', 0xA5)
        diff = ST.read_back(bad.host_of(inj).get, inj)
        self.assertTrue(any('(word at' in x for x in diff), diff[:3])

    def test_the_poison_not_covering_a_marked_byte(self):
        case = self._case()
        good = ST.inject(case, 'stbar', 0x5A, poison=True)
        self.assertEqual(ST.poison_problems(ST.host_of(good).get, case,
                                            good), [])
        bad = scratch_module(self.tmp, 's2state', [(
            "        for o in hit:\n            data[o] = fill",
            "        for o in hit[1:]:\n            data[o] = fill")])
        inj = bad.inject(case, 'stbar', 0x5A, poison=True)
        problems = ST.poison_problems(bad.host_of(inj).get, case, inj)
        self.assertTrue(any('marked or undefined bytes are not the fill' in x
                            for x in problems), problems)

    def test_updatesounds_without_jumps_fails_its_count(self):
        bad = scratch_module(self.tmp, 's2cap', [(
            "% ('jumps=1,' if jumps_update else '', chan,",
            "% ('', chan,")])
        bad.capture('signs', self.tmp / 'signs')
        rc = C.RunCases(self.tmp / 'signs')
        s = C.check_sounds(rc.calls(), True)
        self.assertEqual(s['updates'], 0)
        self.assertTrue(any('S_UpdateSounds with mo' in x
                            for x in s['problems']), s['problems'][:3])


@unittest.skipUnless((C.CASES / 'demo3' / 'index.json').exists(),
                     'no captured cases (python3 tools/native/s2cap.py '
                     '--capture)')
class Captured(unittest.TestCase):
    def test_cases_under_60_mb_and_every_index_clean(self):
        self.assertLessEqual(C.tree_size(C.CASES), C.CASES_LIMIT)
        for run in C.RUNS:
            path = C.CASES / run / 'index.json'
            if not path.exists():
                continue
            idx = json.loads(path.read_text())
            self.assertEqual(idx['problems'], [], run)
            self.assertLessEqual(idx['traffic'], C.PIPE_LIMIT, run)


if __name__ == '__main__':
    unittest.main()
