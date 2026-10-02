"""The bridge's additions for milestone 10 (docs/GAME.md 1.11, 3.5, 3.6;
S6): the manifest's "select", "removed", "stale" and "mask"; the routine
and tic comparison modes; the upstream reader's tic decoding (the
external globals of the tic, texturetranslation, the derived kind
"sighthint", CS_PREV as "stale"). The first tests are on hand-made data;
the reader's need build/ (milestone 9's setup dumps) and skip without
it.
"""

import json
import unittest

import support  # noqa: F401  (puts tools/ on the path)

from bridge import canonical, layout, schema  # noqa: E402
from bridge.fields import R  # noqa: E402
from bridge.layout import Manifest  # noqa: E402
from bridge.memory import port_text  # noqa: E402
from bridge.port import STALE, PortError, PortReader, PortWriter, \
    handle_decode, handle_encode  # noqa: E402

ROOT = support.ROOT
SETUPS = ROOT / 'build' / 'native' / 'levels' / 'setups'
HAVE_SETUPS = (SETUPS / 'demo3-01' / 'r.ram.z').exists() and \
    (ROOT / 'build' / 'linkmap.json').exists()
WHY_SETUPS = ('needs milestone 9\'s setup dumps: python3 tools/native/'
              'setupcap.py')


def game_manifest():
    """A hand-made layout with milestone 10's features: kind "plat" (a
    special kind: its function selects its slots, as the game manifest's
    specials do: "(free)" a free one, its removal function a "removed"
    special); a "thing" kind whose function
    byte keeps a flag of the port's own in bit 7 (enum "mask"); a global
    handle that can hold "stale"."""
    at = [0x400200]

    def planes(n, cap):
        out = []
        for _ in range(n):
            out.append(port_text(at[0]))
            at[0] += cap
        return out

    fn = {'enc': 'enum', 'values': ['(free)', 'u:T_Plat', 'u:remove']}
    data = {
        'format': layout.FORMAT, 'name': 'game-tiny', 'symbols': [],
        'tables': [], 'lists': {}, 'pools': {},
        'removed': {'function': 'u:remove', 'kinds': ['plat'],
                    'home': 'plat'},
        'kinds': {
            'plat': {'capacity': 6, 'count': planes(1, 1),
                     'select': {'path': ['function'], 'in': ['u:T_Plat']},
                     'leaves': [
                         {'path': ['function'], 'enc': fn,
                          'planes': planes(1, 6)},
                         {'path': ['speed'], 'enc': {'enc': 'int', 'bytes': 1,
                                                     'signed': False},
                          'planes': planes(1, 6)}]},
            'thing': {'capacity': 4, 'count': planes(1, 1), 'leaves': [
                {'path': ['function'],
                 'enc': {'enc': 'enum', 'values': [None, 'u:Think'],
                         'mask': 0x7F},
                 'planes': planes(1, 4)}]}},
        'globals': {'leaves': [
            {'path': ['u:prev'],
             'enc': {'enc': 'handle', 'bytes': 2, 'stale': 0xFFFE,
                     'ranges': [{'lo': 0, 'n': 4, 'kind': 'thing'}]},
             'planes': ['main:1A80', 'main:1A81']}]},
    }
    return Manifest(json.loads(json.dumps(data)))


def game_state():
    return {'format': canonical.FORMAT,
            'globals': {'u:prev': R('thing', 1)},
            'objects': {
                'plat': {0: {'function': 'u:T_Plat', 'speed': 3},
                         1: {'function': 'u:T_Plat', 'speed': 9}},
                'thing': {0: {'function': 'u:Think'}, 1: {'function': None}}}}


class ManifestFeatures(unittest.TestCase):
    def test_round_trip(self):
        mf = game_manifest()
        state = game_state()
        back = PortReader(mf).read(PortWriter(mf).write(state))
        self.assertEqual(canonical.diff(state, back), [])

    def test_select_skips_a_free_slot(self):
        mf = game_manifest()
        m = PortWriter(mf).write(game_state())
        # plat slot 0 freed in place: the reader skips it (a free list's
        # slot), so plat 1 comes back as the only plat
        fn_leaf = next(lf for lf in mf.kinds['plat']['leaves']
                       if lf.path == ('function',) or
                       list(lf.path) == ['function'])
        m.put(fn_leaf.planes[0] + 0, 0, 1)
        back = PortReader(mf).read(m)
        self.assertEqual(list(back['objects']['plat'].values()),
                         [{'function': 'u:T_Plat', 'speed': 9}])

    def test_select_refuses_an_unselected_object(self):
        mf = game_manifest()
        state = game_state()
        state['objects']['plat'][1]['function'] = '(free)'
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)

    def test_removed_specials(self):
        mf = game_manifest()
        state = game_state()
        state['objects']['removed'] = {0: {'function': 'u:remove'}}
        m = PortWriter(mf).write(state)
        back = PortReader(mf).read(m)
        self.assertEqual(back['objects']['removed'],
                         {0: {'function': 'u:remove'}})
        self.assertEqual(len(back['objects']['plat']), 2)
        # a "removed" object is only a function: anything else is refused
        state['objects']['removed'] = {0: {'function': 'u:remove',
                                           'speed': 1}}
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)

    def test_enum_mask(self):
        mf = game_manifest()
        m = PortWriter(mf).write(game_state())
        leaf = mf.kinds['thing']['leaves'][0]
        m.put(leaf.planes[0], 0x81, 1)          # the port's flag in bit 7
        back = PortReader(mf).read(m)
        self.assertEqual(back['objects']['thing'][0]['function'], 'u:Think')

    def test_stale(self):
        mf = game_manifest()
        state = game_state()
        state['globals']['u:prev'] = STALE
        back = PortReader(mf).read(PortWriter(mf).write(state))
        self.assertEqual(back['globals']['u:prev'], STALE)
        enc = {'enc': 'handle', 'bytes': 2, 'ranges': [
            {'lo': 0, 'n': 4, 'kind': 'thing'}]}
        with self.assertRaises(PortError):      # no "stale" in the layout
            handle_encode(enc, STALE, 'x')
        self.assertEqual(handle_decode(dict(enc, stale=0xFFFE), 0xFFFE,
                                       'x'), STALE)

    def test_select_needs_in_or_not(self):
        d = json.loads(json.dumps(game_manifest().data)) \
            if hasattr(game_manifest(), 'data') else None
        if d is None:
            self.skipTest('the manifest keeps no data')
        d['kinds']['plat']['select'] = {'path': ['function']}
        with self.assertRaises(ValueError):
            Manifest(d)


class CompareModes(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(schema.compare_skips(None, 'routine'),
                         schema.ROUTINE_SKIPS)
        tic = schema.compare_skips(None, 'tic')
        for name in schema.ROUTINE_SKIPS + ['line.r_validcount',
                                            'g_game65.s:cmds']:
            self.assertIn(name, tic)
        # CS_PREV, the sight line and the line record are compared
        for name in ('p_sight65.s:CS_PREV1', 'mobj.sightline',
                     'p_map65.s:LR_USE'):
            self.assertNotIn(name, tic)

    def test_lockstep_mode_is_unchanged(self):
        from bridge.upstream import Schema
        try:
            sch = Schema()
        except (OSError, KeyError, ValueError):
            self.skipTest('needs build/linkmap.json')
        self.assertEqual(schema.compare_skips(sch.structs, 'lockstep'),
                         schema.cache_fields(sch.structs))


@unittest.skipUnless(HAVE_SETUPS, WHY_SETUPS)
class TicDecoding(unittest.TestCase):
    def test_tic_mode_adds_its_globals_and_the_hint(self):
        from bridge import upstream
        from native import levelconv as LC
        m = LC.load_memory(SETUPS / 'demo3-01' / 'r.ram.z')
        plain = upstream.Reader(m).read()
        tic = upstream.Reader(m, tic=True).read()
        self.assertNotIn('sighthint', plain['objects'])
        self.assertIn('sighthint', tic['objects'])
        n = m.u16(upstream.Reader(m).sym.address(
            'p_setup65.s:_g_thingPoolSize'))
        self.assertEqual(len(tic['objects']['sighthint']), n)
        for name in ['%s:%s' % (u, label) for u, labels in
                     schema.TIC_GLOBALS.items() for label in labels]:
            self.assertNotIn(name, plain['globals'])
            self.assertIn(name, tic['globals'])
        self.assertIn('r_data65.s:texturetranslation', tic['globals'])
        # the plain decoding is the tic decoding without its additions
        rest = {k: v for k, v in tic['globals'].items()
                if k in plain['globals']}
        self.assertEqual(rest, plain['globals'])

    def test_cs_prev_naming_nothing_is_stale(self):
        from bridge import upstream
        from native import levelconv as LC
        m = LC.load_memory(SETUPS / 'demo3-01' / 'r.ram.z')
        r = upstream.Reader(m, tic=True)
        a = r.sym.address('p_sight65.s:CS_PREV1')
        m.put(a, 0x7F0001, 3)       # a pointer into nothing the bridge knows
        st = upstream.Reader(m, tic=True).read()
        self.assertEqual(st['globals']['p_sight65.s:CS_PREV1'], STALE)


if __name__ == '__main__':
    unittest.main()
