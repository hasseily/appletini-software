"""The state bridge (tools/bridge): its parts on hand-made data, and its
schema against upstream's include files and our link map.

The first tests need nothing from build/. The schema tests need
build/linkmap.json and the upstream clone (tools/fetch_upstream.py,
tools/v816/imgmatch.py) and skip without them. The tests on real dumps
are in test_bridge_dumps.py.
"""

import json
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts tools/ on the path)

from bridge import canonical, incfile, layout, port, schema  # noqa: E402
from bridge.layout import Manifest  # noqa: E402
from bridge.memory import MAIN, Memory, PortMemory, port_address, \
    port_text  # noqa: E402
from bridge.port import PortError, PortReader, PortWriter  # noqa: E402
from bridge.fields import Array, Field, R, Struct, StructError, I16, U8, \
    spec  # noqa: E402
from bridge.upstream import Coverage  # noqa: E402

ROOT = support.ROOT
BRIDGE = ROOT / 'tools' / 'bridge'
LINKMAP = ROOT / 'build' / 'linkmap.json'
OFFSETS = ROOT / 'build' / 'upstream' / 'src' / 'iigs' / 'offsets.inc'
needs_build = unittest.skipUnless(
    LINKMAP.exists() and OFFSETS.exists(),
    'build/linkmap.json or the upstream clone is missing: run python3 '
    'tools/fetch_upstream.py and python3 tools/v816/imgmatch.py')


class ScriptTest(unittest.TestCase):
    """bridge.py and dumps.py run as scripts put tools/bridge first on
    sys.path, so a module there named like a standard-library one (types,
    which re and enum import) breaks the interpreter's own imports."""

    def test_no_module_shadows_the_standard_library(self):
        stdlib = Path(sysconfig.get_paths()['stdlib'])
        for path in sorted(BRIDGE.glob('*.py')):
            name = path.stem
            if name == '__init__':
                continue
            with self.subTest(name):
                self.assertNotIn(name, sys.builtin_module_names)
                self.assertFalse((stdlib / (name + '.py')).exists() or
                                 (stdlib / name).is_dir(),
                                 '%s shadows the standard library' % path)

    def test_scripts_start(self):
        for script in ('bridge.py', 'dumps.py'):
            with self.subTest(script):
                result = subprocess.run(
                    [sys.executable, str(BRIDGE / script), '--help'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage', result.stdout)


class IncFileTest(unittest.TestCase):
    def test_expressions(self):
        names = {'A': 0x210000, 'B': 3}
        self.assertEqual(incfile.evaluate('(A + 0xf400)', names), 0x21f400)
        self.assertEqual(incfile.evaluate('B * 4 + 1', names), 13)
        self.assertEqual(incfile.evaluate('-32768', names), -32768)
        self.assertEqual(incfile.evaluate('(A >> 16) | 1', names), 0x21)
        self.assertEqual(incfile.evaluate("'M'", names), 77)
        self.assertEqual(incfile.evaluate('(1 << 3) - 1', names), 7)
        with self.assertRaises(incfile.IncError):
            incfile.evaluate('C + 1', names)
        with self.assertRaises(incfile.IncError):
            incfile.evaluate('1 +', names)

    def test_parse(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'x.inc'
            path.write_text(';;; a comment\n#if !defined X\n'
                            'OFS_A_X  .equ  0\nOFS_A_Y .equ 4 ; y\n'
                            'SIZEOF_A .equ (OFS_A_Y + 4)\n#endif\n')
            got = incfile.parse(path)
        self.assertEqual([(c.name, c.value) for c in got],
                         [('OFS_A_X', 0), ('OFS_A_Y', 4), ('SIZEOF_A', 8)])
        self.assertEqual(got[2].line, 5)


class TypesTest(unittest.TestCase):
    def test_struct_must_tile(self):
        Struct('T', 3, [Field('a', 0, I16), Field('b', 2, U8)])
        with self.assertRaises(StructError):
            Struct('T', 4, [Field('a', 0, I16), Field('b', 2, U8)])
        with self.assertRaises(StructError):
            Struct('T', 3, [Field('a', 0, I16), Field('b', 1, U8)])

    def test_spec(self):
        self.assertEqual(spec('i16*6'), Array(I16, 6))
        self.assertEqual(spec('ref:mobj|zmobj').targets, ('mobj', 'zmobj'))
        self.assertEqual(spec('fixed').size, 4)
        self.assertEqual(spec('raw:3').length, 3)


class CoverageTest(unittest.TestCase):
    def test_claims(self):
        cov = Coverage([schema.Region('r', 0x100, 0x110, ''),
                        schema.Region('s', 0x200, 0x204, '')])
        cov.claim(0x0f0, 0x20, 'field:a')      # the part in r only
        cov.claim(0x108, 4, 'excl:b')          # twice
        self.assertTrue(cov.double)
        cov.claim(0x201, 2, 'field:c')
        self.assertEqual(cov.unclaimed(), [(0x200, 0x201, 's'),
                                           (0x203, 0x204, 's')])
        self.assertEqual(cov.claimed(0x10f), 'field:a')
        self.assertEqual(cov.claimed(0x200), '')
        self.assertEqual(cov.spans(lambda o: o == 'field:c'),
                         [(0x201, 0x203)])


class CanonicalTest(unittest.TestCase):
    def state(self):
        return {'format': canonical.FORMAT,
                'globals': {'u:a': 3, 'u:l': [R('k', 0), R('k', 1)]},
                'objects': {'k': {0: {'x': 1, 'p': R('k', 1, 'y')},
                                  1: {'x': 2, 'p': None}}}}

    def test_json_round_trip(self):
        a = self.state()
        b = canonical.roundtrip_json(a)
        self.assertEqual(a, b)
        self.assertIsInstance(b['objects']['k'][1]['x'], int)
        self.assertEqual(b['globals']['u:l'][1], R('k', 1))
        with tempfile.TemporaryDirectory() as d:
            canonical.save(a, Path(d) / 's.json')
            self.assertEqual(canonical.load(Path(d) / 's.json'), a)

    def test_diff(self):
        a, b = self.state(), self.state()
        self.assertEqual(canonical.diff(a, b), [])
        b['objects']['k'][1]['x'] = 5
        b['globals']['u:l'] = [R('k', 1), R('k', 0)]     # order is state
        found = canonical.diff(a, b)
        self.assertEqual(len(found), 2)
        self.assertEqual(canonical.diff(a, b, skip=['k.x', 'u:l']), [])
        del b['objects']['k'][1]
        self.assertTrue(any('identities' in x for x in canonical.diff(a, b)))

    def test_dangling(self):
        a = self.state()
        a['objects']['k'][0]['p'] = R('k', 7)
        self.assertEqual(len(canonical.dangling(a, set())), 1)


class MemoryTest(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(port_address('main:1A80'), MAIN | 0x1a80)
        self.assertEqual(port_address('aux:40:0200'), 0x400200)
        self.assertEqual(port_text(0x7f0200), 'aux:7F:0200')
        with self.assertRaises(ValueError):
            port_address('aux:80:0000')

    def test_upstream_memory(self):
        m = Memory()
        m.put(0x02fffe, 0x11223344, 4)          # across banks
        self.assertEqual(m.u32(0x02fffe), 0x11223344)
        self.assertEqual(m.sint(0x030000, 2), 0x1122)
        self.assertEqual(m.u8(0x7f0000), 0)

    def test_port_image(self):
        m = PortMemory()
        m.put(0x41abcd, 0x5a, 1)
        m.put(MAIN | 0x1a80, 0x33, 1)
        data = m.image_bytes()
        self.assertEqual(data[:8], b'A2VMIMG1')
        at, found = 8, {}
        while at < len(data):
            kind, bank, address, length = (data[at], data[at + 1],
                                           int.from_bytes(data[at + 2:at + 4],
                                                          'little'),
                                           int.from_bytes(data[at + 4:at + 8],
                                                          'little'))
            body = data[at + 8:at + 8 + length]
            found[(kind, bank, address)] = body
            at += 8 + length
            self.assertLess(address + length, 0xc001)   # never I/O
        self.assertEqual(found[(1, 0x41, 0)][0xabcd], 0x5a)
        self.assertEqual(found[(0, 0, 0)][0x1a80], 0x33)


def tiny_manifest():
    """A hand-made layout: kind "a" with an int, a ref, an enum, raw bytes,
    a sequence and the links of list L; kind "b" with a blob; globals with
    the head of L."""
    at = [0x400200]

    def planes(n, cap):
        out = []
        for _ in range(n):
            out.append(port_text(at[0]))
            at[0] += cap
        return out

    ref_a = {'enc': 'ref', 'codes': [['a', None], ['state', None]],
             'offset': False}
    a_leaves = [
        {'path': ['x'], 'enc': {'enc': 'int', 'bytes': 2, 'signed': True},
         'planes': planes(2, 4)},
        {'path': ['p'], 'enc': ref_a, 'planes': planes(3, 4)},
        {'path': ['fn'], 'enc': {'enc': 'enum', 'values': [None, 'u:f']},
         'planes': planes(1, 4)},
        {'path': ['r'], 'enc': {'enc': 'raw', 'bytes': 2},
         'planes': planes(2, 4)},
        {'path': ['s'], 'enc': {'enc': 'seq', 'pool': 'P'},
         'planes': planes(4, 4)},
        {'path': ['sub', 'y', 1], 'enc': {'enc': 'int', 'bytes': 1,
                                          'signed': False},
         'planes': planes(1, 4)},
        {'path': ['@L.next'], 'enc': {'enc': 'ref', 'codes': [['a', None]],
                                      'offset': False},
         'planes': planes(3, 4)},
        {'path': ['@L.prev'], 'enc': {'enc': 'ref', 'codes': [['a', None]],
                                      'offset': False},
         'planes': planes(3, 4)},
    ]
    data = {
        'format': layout.FORMAT, 'name': 'tiny', 'symbols': [],
        'tables': [], 'lists': {'L': {'elements': ['a'], 'prev': True}},
        'pools': {'P': {'capacity': 8, 'codes': [['a', None]],
                        'count': planes(2, 1), 'planes': planes(3, 8)}},
        'kinds': {
            'a': {'capacity': 4, 'count': planes(2, 1), 'leaves': a_leaves},
            'b': {'capacity': 1, 'count': planes(2, 1), 'leaves': [
                {'path': ['bytes'], 'enc': {'enc': 'blob', 'max': 16},
                 'planes': planes(2, 1) + planes(1, 16)}]}},
        'globals': {'leaves': [
            {'path': ['u:head'], 'enc': {'enc': 'list', 'list': 'L',
                                         'codes': [['a', None]]},
             'planes': ['main:1A80', 'main:1A81', 'main:1A82']}]},
    }
    return Manifest(json.loads(json.dumps(data)))


def tiny_state():
    a = {0: {'x': -2, 'p': R('a', 2), 'fn': 'u:f', 'r': '0102',
             's': [R('a', 1), R('a', 1)], 'sub': {'y': [None, 7]}},
         1: {'x': 300, 'p': R('state', 9), 'fn': None, 'r': 'ffee',
             's': [], 'sub': {'y': [None, 0]}},
         2: {'x': 0, 'p': None, 'fn': None, 'r': '0000',
             's': [R('a', 0)], 'sub': {'y': [None, 255]}}}
    return {'format': canonical.FORMAT,
            'globals': {'u:head': [R('a', 2), R('a', 0)]},
            'objects': {'a': a, 'b': {0: {'bytes': 'deadbeef'}}}}


class PortTest(unittest.TestCase):
    def test_round_trip(self):
        mf = tiny_manifest()
        state = tiny_state()
        memory = PortWriter(mf).write(state)
        back = PortReader(mf).read(memory)
        # the reader makes lists of indexed paths: element 0 of sub.y is
        # not in the layout
        for o in back['objects']['a'].values():
            self.assertIsNone(o['sub']['y'][0])
        self.assertEqual(canonical.diff(state, back), [])

    def test_refusals(self):
        mf = tiny_manifest()
        state = tiny_state()
        state['objects']['a'][3] = dict(state['objects']['a'][2])
        state['objects']['a'][4] = dict(state['objects']['a'][2])
        with self.assertRaises(PortError):           # capacity 4
            PortWriter(mf).write(state)
        state = tiny_state()
        state['objects']['a'][0]['p'] = R('b', 0)    # not a code of p
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)
        state = tiny_state()
        state['objects']['a'][0]['x'] = 40000        # 2 bytes, signed
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)
        state = tiny_state()
        del state['objects']['a'][1]                 # not 0 to n - 1
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)
        # values no leaf holds: refused, not dropped
        for what, change in (
                ('a[0].bogus', lambda s: s['objects']['a'][0].update(
                    bogus=1)),
                ('a[1].sub.y.0', lambda s: s['objects']['a'][1]['sub'][
                    'y'].__setitem__(0, 5)),
                ('a[2].sub.z', lambda s: s['objects']['a'][2][
                    'sub'].update(z=[1])),
                ('c: a kind the layout lacks', lambda s: s['objects'].update(
                    c={0: {'x': 1}})),
                ('globals.u:other', lambda s: s['globals'].update(
                    {'u:other': 3}))):
            with self.subTest(what):
                state = tiny_state()
                change(state)
                with self.assertRaises(PortError) as caught:
                    PortWriter(mf).write(state)
                self.assertIn(what, str(caught.exception))
        # a missing field is refused too
        state = tiny_state()
        del state['objects']['a'][0]['r']
        with self.assertRaises(PortError):
            PortWriter(mf).write(state)
        # an empty kind the layout lacks holds nothing
        state = tiny_state()
        state['objects']['c'] = {}
        PortWriter(mf).write(state)

    def test_a2vm_runs_under_nice(self):
        """check --a2vm runs a2vm once a dump: a batch run, so under
        nice -n 10 (the ground rules)."""
        seen = []

        def fake_run(command, **kwargs):
            seen.append(list(command))
            self.assertTrue(kwargs.get('timeout'))    # and bounded
            return subprocess.CompletedProcess(command, 1, '', 'stopped')

        memory = PortWriter(tiny_manifest()).write(tiny_state())
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(port.subprocess, 'run', fake_run):
            with self.assertRaises(PortError):
                port.through_a2vm(memory, Path('a2vm'), Path('rom'),
                                  Path(d) / 'work')
            self.assertFalse((Path(d) / 'work').exists())   # cleaned up
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:4], ['nice', '-n', '10', 'a2vm'])

    def test_reader_checks_links(self):
        mf = tiny_manifest()
        memory = PortWriter(mf).write(tiny_state())
        prev = [lf for lf in mf.kinds['a']['leaves']
                if lf.path == ('@L.prev',)][0]
        memory.put(prev.planes[1] + 0, 1, 1)         # a[0].prev = a[1]
        with self.assertRaises(PortError):
            PortReader(mf).read(memory)
        memory = PortWriter(mf).write(tiny_state())
        nxt = [lf for lf in mf.kinds['a']['leaves']
               if lf.path == ('@L.next',)][0]
        memory.put(nxt.planes[0] + 0, 1, 1)          # a[0].next = a[2]
        memory.put(nxt.planes[1] + 0, 2, 1)          # (a loop)
        with self.assertRaises(PortError):
            PortReader(mf).read(memory)


@needs_build
class SchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bridge.upstream import Schema
        cls.sch = Schema()

    def test_include_values_equal_the_link_map(self):
        """Every constant of offsets.inc and memmap.inc, read by the
        bridge's own parser, equals our assembler's value in the link
        map."""
        units = self.sch.symbols.units
        for name in ('offsets.inc', 'memmap.inc', 'info.inc'):
            constants = incfile.parse(OFFSETS.parent / name)
            self.assertTrue(constants)
            for c in constants:
                values = {u[c.name] for u in units.values()
                          if isinstance(u.get(c.name), int)}
                self.assertEqual(values, {c.value}, (name, c.name))

    def test_every_offset_has_a_type(self):
        c = self.sch.c
        for prefix in ('MO', 'SEC', 'LINE', 'SIDE', 'SUB', 'SEG', 'NODE',
                       'SN', 'PL', 'PLAT', 'DOOR', 'BTN', 'TC', 'PSP'):
            st = self.sch.structs[prefix]
            self.assertEqual(st.size, c['SIZEOF_' + prefix])
            for k in c.offsets_list:
                if k.name.startswith('OFS_%s_' % prefix):
                    f = st.field_at(k.value)
                    self.assertIsNotNone(f, k.name)
                    self.assertEqual(f.offset, k.value, k.name)

    def test_thinker_functions_are_labels(self):
        for ref, kind in schema.THINKER_FUNCTIONS.items():
            label = self.sch.symbols.label(ref)
            self.assertEqual(label.kind, 'text', ref)
            self.assertTrue(kind in schema.KINDS)

    def test_regions_do_not_overlap(self):
        regions = sorted(self.sch.regions, key=lambda r: r.start)
        for a, b in zip(regions, regions[1:]):
            self.assertLessEqual(a.end, b.start, (a.name, b.name))
        names = {r.name for r in regions}
        for name in ('zone', 'pool map', 'GSTAMP', 'flood index',
                     'flood entries'):
            self.assertIn(name, names)

    def test_every_exclusion_has_a_reason(self):
        used = set(schema.DEAD_EXCLUSIONS)
        for excluded in schema.UNIT_EXCLUSIONS.values():
            used |= set(excluded)
        for name in used:
            self.assertIn(name, schema.EXCLUSIONS)
            self.assertGreater(len(schema.EXCLUSIONS[name]), 40)

    def test_globals_are_labels_of_game_units(self):
        for unit, labels in schema.GLOBALS.items():
            self.assertTrue(schema.is_game_unit(unit))
            for name in labels:
                self.sch.symbols.label('%s:%s' % (unit, name))

    def test_native_v1_layout(self):
        from bridge import checks
        mf = checks.manifest_for(self.sch)
        again = Manifest(json.loads(json.dumps(mf.data)))
        used = []
        for kind, spec_ in again.kinds.items():
            cap = spec_['capacity']
            used += [(p, p + 1) for p in spec_['count']]
            for leaf in spec_['leaves']:
                self.assertEqual(len(leaf.planes), leaf.width, leaf.path)
                for i, p in enumerate(leaf.planes):
                    n = leaf.enc['max'] if leaf.enc['enc'] == 'blob' and \
                        i == 2 else cap
                    used.append((p, p + n))
        for leaf in again.globals:
            used += [(p, p + 1) for p in leaf.planes]
        used.sort()
        for a, b in zip(used, used[1:]):
            self.assertLessEqual(a[1], b[0], (port_text(a[0]),
                                              port_text(b[0])))
        for start, end in used:
            self.assertEqual(start >> 16, (end - 1) >> 16)
            offset, bank = start & 0xffff, start >> 16
            if start & MAIN:
                self.assertTrue(0x1a80 <= offset and (end & 0xffff) <= 0x2000
                                or bank >= 0x40)
            else:
                self.assertGreaterEqual(bank, layout.AUX_FIRST_BANK)
                self.assertGreaterEqual(offset, 0x0200)
                self.assertLessEqual(end & 0xffff or 0x10000, 0xc000)


if __name__ == '__main__':
    unittest.main()
