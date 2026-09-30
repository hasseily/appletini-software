"""The state bridge (tools/bridge) on real states of the reference.

Its acceptance (NATIVE.md section 13, milestone 6 item 2) on every dump of
tools/bridge/dumps.py (the coverage scripts and demo3 to its end): 0 raw
pointers, every byte of the game-state regions a field or a named
exclusion, dead exclusions never read first by the tic, upstream ->
canonical -> upstream byte-exact, upstream -> canonical -> port ->
canonical equal; the level tables constant over a level load; the
liveness check over the sweep's footprints. Then the cases the dumps do
not meet, made from a dump the way upstream would make them (synthetic.py:
zone mobjs with and without a thinker, a special waiting for its removal),
and that the checks do fail on broken states.

Needs build/linkmap.json, the upstream clone and the dumps (python3
tools/bridge/dumps.py; the sweep: --sweep 80); the a2vm test also needs
build/a2vm/a2vm and appletini-one's ROM. Each part skips without them.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts tools/ on the path)

from bridge import canonical, checks, dumps, identity, schema, \
    synthetic  # noqa: E402
from bridge.memory import Memory  # noqa: E402
from bridge.port import PortReader, PortWriter  # noqa: E402
from bridge.fields import R, U32  # noqa: E402
from bridge.upstream import Problem, Reader, Schema, Writer  # noqa: E402

ROOT = support.ROOT
LINKMAP = ROOT / 'build' / 'linkmap.json'
DUMPS = dumps.dump_directories()
SWEEP = dumps.sweep_directories()
A2VM = ROOT / 'build' / 'a2vm' / 'a2vm'
ROM = Path(os.environ.get('APPLETINI_ROOT', str(
    ROOT.parents[2] / 'appletini-one'))) / 'docs' / 'Apple2e_Enhanced.rom'

needs_dumps = unittest.skipUnless(
    LINKMAP.exists() and DUMPS,
    'no bridge dumps: run python3 tools/fetch_upstream.py, python3 '
    'tools/v816/imgmatch.py, then python3 tools/bridge/dumps.py')
needs_sweep = unittest.skipUnless(
    LINKMAP.exists() and SWEEP,
    'no footprint sweep: run python3 tools/bridge/dumps.py --sweep 80')
needs_a2vm = unittest.skipUnless(
    A2VM.exists() and ROM.exists(),
    'build/a2vm/a2vm or the //e ROM of appletini-one is missing')

# The dump the single-dump tests use: E1M1 after a door opened (a door
# special on the thinker list), else the first dump.
SAMPLE = next((d for d in DUMPS if d.name == 'newgame-07'),
              DUMPS[0] if DUMPS else None)


def read(memory, sch):
    reader = Reader(memory, sch)
    state = reader.read()
    return reader, state


@needs_dumps
class AcceptanceTest(unittest.TestCase):
    """Every check of checks.py on every dump."""

    @classmethod
    def setUpClass(cls):
        cls.sch = Schema()
        cls.manifest = checks.manifest_for(cls.sch)
        cls.results = [checks.check_dump(d, cls.sch, cls.manifest)
                       for d in DUMPS]

    def test_every_coverage_script_and_the_demo(self):
        sets = {r['info']['set'] for r in self.results}
        self.assertEqual(sets, {s.key for s in dumps.SETS})
        # demo3 to its end marker: the last dump is its last tic
        demo = [r for r in self.results if r['info']['set'] == 'demo']
        self.assertEqual(max(r['info']['leveltime'] for r in demo), 2134)
        maps = {r['info']['gamemap'] for r in self.results
                if r['info']['set'] == 'tour'}
        self.assertEqual(maps, set(range(1, 10)))

    def test_no_raw_pointer_and_no_problem(self):
        for r in self.results:
            self.assertEqual(r['raw_pointers'], [], r['name'])
            self.assertEqual(r['problems'], [], r['name'])

    def test_every_byte_is_a_field_or_an_exclusion(self):
        for r in self.results:
            self.assertEqual(r['unclaimed'], 0, r['name'])
            self.assertEqual(r['claimed_twice'], 0, r['name'])
            for owner in r['by_owner']:
                if owner.startswith('excl:'):
                    self.assertIn(owner[5:], schema.EXCLUSIONS, owner)
            # the pool map, GSTAMP and the flood tables are in
            for owner in ('derived:TP_BITS', 'derived:TP_MASK',
                          'excl:no line', 'derived:flood index',
                          'derived:flood entries', 'excl:no sector'):
                self.assertIn(owner, r['by_owner'], r['name'])

    def test_dead_bytes_are_not_read(self):
        for r in self.results:
            self.assertEqual(r['liveness'], [], r['name'])

    def test_writes_outside_the_regions_are_not_game_state(self):
        for r in self.results:
            self.assertEqual(r['outside_unknown'], [], r['name'])

    def test_upstream_round_trip_is_byte_exact(self):
        for r in self.results:
            rt = r['upstream_roundtrip']
            self.assertEqual((rt['differing'], rt['outside']), (0, 0),
                             (r['name'], rt['first']))

    def test_port_round_trip_is_equal(self):
        for r in self.results:
            self.assertEqual(r['port_roundtrip'], [], r['name'])

    def test_level_tables_constant_over_a_load(self):
        problems, pairs = checks.constancy(self.results)
        self.assertEqual(problems, [])
        self.assertGreater(pairs, 10)

    def test_object_kinds(self):
        kinds = set()
        for r in self.results:
            kinds |= set(r['counts'])
        for kind in ('sector', 'line', 'side', 'subsector', 'seg', 'node',
                     'blocklink', 'blockmap', 'reject', 'linebuf', 'mobj',
                     'secnode', 'player', 'button', 'plat', 'door', 'floor',
                     'lightflash', 'strobe', 'glow', 'scroll'):
            self.assertIn(kind, kinds)


@needs_dumps
class IdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sch = Schema()
        cls.memory = Memory.from_image(SAMPLE / 'entry.img')
        cls.reader, cls.state = read(cls.memory, cls.sch)

    def test_mobj_identity_is_the_pool_slot(self):
        pool = self.reader.placement.tables['mobj']
        mobjs = self.state['objects']['mobj']
        self.assertEqual(sorted(mobjs), list(range(pool.count)))
        for slot in mobjs:
            self.assertEqual(self.reader.placement.address('mobj', slot),
                             pool.base + slot * pool.stride)
        player = self.state['objects']['player'][0]
        mo = player['mo']
        self.assertEqual(mo.kind, 'mobj')
        self.assertEqual(mobjs[mo.id]['type'],
                         self.sch.c['CONST_MT_PLAYER'])
        # free slots keep their slot and say so; TP_BITS agrees
        free = self.reader.free_slots()
        self.assertTrue(free)
        for slot, o in mobjs.items():
            self.assertEqual(o['free'], int(slot in free))

    def test_thinker_list_is_a_sequence_of_identities(self):
        seq = self.state['globals']['p_think65.s:_g_thinkerclasscap']
        self.assertTrue(all(isinstance(r, R) and r.field is None
                            for r in seq))
        self.assertEqual(len(seq), len(set(seq)))
        kinds = {r.kind for r in seq}
        self.assertIn('mobj', kinds)
        self.assertIn('door', kinds)
        for r in seq:
            fn = self.state['objects'][r.kind][r.id]['function']
            self.assertIn(fn, schema.THINKER_FUNCTIONS)

    def test_identities_follow_the_rules(self):
        """The reader numbers as identity.py does; a state numbered
        otherwise comes back to the rules' numbers."""
        self.assertEqual(canonical.diff(self.state,
                                        identity.renumber(self.state)), [])
        nodes = self.state['objects']['secnode']
        perm = {('secnode', i): (i * 7919) % len(nodes) for i in nodes}
        shuffled = identity.rewrite(self.state, perm)
        shuffled['objects']['secnode'] = {
            perm[('secnode', i)]: o
            for i, o in shuffled['objects']['secnode'].items()}
        self.assertNotEqual(canonical.diff(self.state, shuffled), [])
        self.assertEqual(canonical.diff(self.state,
                                        identity.renumber(shuffled)), [])

    def test_port_slots_need_not_follow_the_rules(self):
        """A port that keeps its specials and nodes in other slots reads
        back to the same canonical state."""
        manifest = checks.manifest_for(self.sch)
        perm = {}
        for kind in ('secnode', 'scroll'):
            ids = sorted(self.state['objects'].get(kind, {}))
            perm.update({(kind, i): ids[-1 - n] for n, i in enumerate(ids)})
        other = identity.rewrite(self.state, perm)
        for kind in ('secnode', 'scroll'):
            other['objects'][kind] = {perm[(kind, i)]: o for i, o in
                                      other['objects'][kind].items()}
        back = PortReader(manifest).read(PortWriter(manifest).write(other))
        self.assertEqual(canonical.diff(self.state, back), [])

    def test_references_name_objects(self):
        constants = {'state', 'lump', 'symbol', 'table'}
        self.assertEqual(canonical.dangling(self.state, constants), [])

    def test_a_wrong_thinker_function_is_refused(self):
        """A function one byte past a declared one is not matched to the
        nearest label."""
        memory = self.memory.copy()
        a = self.reader.placement.objects[('door', 0)]
        fn = memory.uint(a + self.sch.c['OFS_TH_FUNCTION'], 3)
        memory.put(a + self.sch.c['OFS_TH_FUNCTION'], fn + 1, 3)
        reader, _ = read(memory, self.sch)
        self.assertTrue(any('not a declared thinker function' in p
                            for p in reader.problems))

    def test_a_pointer_to_nothing_is_a_raw_pointer(self):
        memory = self.memory.copy()
        a = self.reader.placement.address('mobj', self.state['objects'][
            'player'][0]['mo'].id)
        free, size = synthetic.free_block(self.reader, 64)
        memory.put(a + self.sch.c['OFS_MO_TARGET'], free + 32, 4)
        reader, _ = read(memory, self.sch)
        self.assertEqual(len(reader.raw_pointers), 1)
        self.assertIn('names no object', reader.raw_pointers[0])

    def test_a_special_off_the_list_is_an_unowned_block(self):
        memory = self.memory.copy()
        door = self.reader.placement.objects[('door', 0)]
        prev = memory.u32(door) & 0xffffff
        nxt = memory.u32(door + 4) & 0xffffff
        memory.put(prev + 4, nxt, 4)
        memory.put(nxt, prev, 4)
        reader, _ = read(memory, self.sch)
        self.assertTrue(any('has no owner' in p for p in reader.problems))

    def test_a_broken_list_link_is_found(self):
        memory = self.memory.copy()
        for r in self.state['objects']['sector'].values():
            if len(r['thinglist']) >= 2:
                second = r['thinglist'][1]
                break
        a = self.reader.placement.address(second.kind, second.id)
        memory.put(a + self.sch.c['OFS_MO_SPREV'], 0, 4)
        reader, _ = read(memory, self.sch)
        self.assertTrue(any('sprev' in p for p in reader.problems))

    def test_a_dead_byte_read_fails_liveness(self):
        label = self.sch.symbols.label('p_map65.s:tmthing')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'reads.img'
            path.write_bytes(b'REF816I1' + bytes(24) +
                             label.address.to_bytes(4, 'little') +
                             (1).to_bytes(4, 'little') + b'\0')
            found = checks.liveness(self.reader.coverage.claimed, path,
                                    self.sch, {})
        self.assertEqual(len(found), 1)
        self.assertIn('tmthing', found[0])

    def test_the_writer_writes_what_the_state_says(self):
        """A changed value changes exactly its bytes; a poisoned byte the
        writer does not produce would show."""
        state = canonical.roundtrip_json(self.state)
        slot = state['globals']['p_think65.s:_g_thinkerclasscap'][0]
        state['objects']['mobj'][slot.id]['x'] += 0x10000
        out = Writer(self.reader).write(state, self.memory)
        a = self.reader.placement.address('mobj', slot.id)
        x = a + self.sch.c['OFS_MO_X']
        changed = [i for i in range(a, a + 120)
                   if out.u8(i) != self.memory.u8(i)]
        self.assertEqual(changed, [x + 2])
        # the thinker list in another order: the mobjs (whose identity is
        # their slot) reversed among the specials
        state = canonical.roundtrip_json(self.state)
        seq = state['globals']['p_think65.s:_g_thinkerclasscap']
        mobjs = [r for r in seq if r.kind == 'mobj'][::-1]
        seq[:] = [mobjs.pop(0) if r.kind == 'mobj' else r for r in seq]
        out = Writer(self.reader).write(state, self.memory)
        again = Reader(out, self.sch).read()
        self.assertEqual(canonical.diff(state, again), [])

    def test_the_writer_refuses_what_the_placement_cannot_hold(self):
        """A state the writer cannot represent raises Problem before
        anything is written, with or without poison: a missing or an
        unknown field, an object the placement lacks or has more of, a
        missing global, a value out of its type."""
        mobjs = self.state['objects']['mobj']
        live = next(i for i, o in sorted(mobjs.items()) if not o['free'])
        seq_name = 'p_think65.s:_g_thinkerclasscap'
        door = R('door', 0, None)

        def without_door(s):
            del s['objects']['door'][0]
            s['globals'][seq_name] = [r for r in s['globals'][seq_name]
                                      if r != door]

        def extra_door(s):
            s['objects']['door'][99] = dict(s['objects']['door'][0])

        cases = {
            'missing momz': lambda s: s['objects']['mobj'][live].pop('momz'),
            'missing health': lambda s: s['objects']['mobj'][live].pop(
                'health'),
            'missing lightlevel': lambda s: s['objects']['sector'][0].pop(
                'lightlevel'),
            'unknown field': lambda s: s['objects']['sector'][0].update(
                bogus=1),
            'missing object': without_door,
            'object the placement lacks': extra_door,
            'missing global': lambda s: s['globals'].pop(
                'g_game65.s:_g_gametic'),
            'unknown global': lambda s: s['globals'].update(
                {'g_game65.s:nothing': 0}),
            'out of range': lambda s: s['objects']['sector'][0].update(
                lightlevel=1 << 20),
            'short array': lambda s: s['globals'][
                'p_map65.s:LR_LINES'].pop(),
            'undeclared function': lambda s: s['objects']['door'][0].update(
                function='p_think65.s:nothing'),
            'reference to nothing': lambda s: s['objects']['mobj'][
                live].update(target=R('mobj', 100000, None)),
        }
        for name, change in cases.items():
            for poison in (False, True):
                with self.subTest(name, poison=poison):
                    state = canonical.roundtrip_json(self.state)
                    change(state)
                    with self.assertRaises(Problem):
                        Writer(self.reader).write(state, self.memory,
                                                  poison=poison)
        # the unchanged state passes the check
        Writer(self.reader).check(canonical.roundtrip_json(self.state))

    def test_comparison_modes(self):
        state = canonical.roundtrip_json(self.state)
        state['objects']['line'][0]['validcount'] += 1
        state['objects']['mobj'][0]['sightline'] += 1
        free = schema.compare_skips(self.sch.structs, 'free')
        lockstep = schema.compare_skips(self.sch.structs, 'lockstep')
        self.assertEqual(canonical.diff(self.state, state, skip=free), [])
        self.assertEqual(len(canonical.diff(self.state, state,
                                            skip=lockstep)), 1)
        self.assertEqual(len(canonical.diff(self.state, state)), 2)


@needs_dumps
class SyntheticTest(unittest.TestCase):
    """Zone mobjs and a removed special, made from a dump."""

    @classmethod
    def setUpClass(cls):
        cls.sch = Schema()
        cls.manifest = checks.manifest_for(cls.sch)
        cls.base = Memory.from_image(SAMPLE / 'entry.img')

    def made(self):
        memory = self.base.copy()
        reader = Reader(memory, self.sch)
        reader.locate()
        return memory, reader

    def check(self, memory):
        reader, state = read(memory, self.sch)
        self.assertEqual(reader.problems, [])
        self.assertEqual(reader.raw_pointers, [])
        diff, outside, first = checks.upstream_roundtrip(reader, state,
                                                         memory)
        self.assertEqual((diff, outside), (0, 0), first)
        back = PortReader(self.manifest).read(
            PortWriter(self.manifest).write(state))
        self.assertEqual(canonical.diff(canonical.roundtrip_json(state),
                                        canonical.roundtrip_json(back)), [])
        return reader, state

    def test_zone_mobj_on_the_thinker_list(self):
        memory, reader = self.made()
        slot = synthetic.live_slot(memory, reader, 3)
        a = synthetic.zone_mobj(memory, reader, slot,
                                'p_tick65.s:P_MobjThinker')
        reader, state = self.check(memory)
        self.assertEqual(reader.placement.objects[('zmobj', 0)], a)
        seq = state['globals']['p_think65.s:_g_thinkerclasscap']
        self.assertEqual(seq[-1], R('zmobj', 0))
        self.assertEqual(state['objects']['zmobj'][0]['x'],
                         state['objects']['mobj'][slot]['x'])

    def test_zone_mobjs_with_no_thinker_have_an_identity(self):
        """Ranked after the thinker list's, in the order of the sectors'
        thing lists: sector 3's then sector 1's."""
        memory, reader = self.made()
        s = synthetic.live_slot(memory, reader, 3)
        a1 = synthetic.zone_mobj(memory, reader, s, None, nosector=False)
        synthetic.push_sector_thing(memory, reader, 3, a1)
        reader2 = Reader(memory, self.sch)
        reader2.locate()
        a2 = synthetic.zone_mobj(memory, reader2, s, None, nosector=False)
        synthetic.push_sector_thing(memory, reader2, 1, a2)
        reader, state = self.check(memory)
        self.assertEqual(reader.placement.objects[('zmobj', 0)], a2)
        self.assertEqual(reader.placement.objects[('zmobj', 1)], a1)
        self.assertEqual(state['objects']['sector'][1]['thinglist'][0],
                         R('zmobj', 0))
        self.assertEqual(state['objects']['sector'][3]['thinglist'][0],
                         R('zmobj', 1))
        self.assertIsNone(state['objects']['zmobj'][0]['function'])
        self.assertEqual(reader.zone_orphans, 0)

    def test_unreachable_zone_mobj(self):
        """No thinker, no sector, no block: an identity by address, and
        counted (its identity rests on the layout)."""
        memory, reader = self.made()
        synthetic.zone_mobj(memory, reader,
                            synthetic.live_slot(memory, reader, 3), None)
        reader, state = self.check(memory)
        self.assertEqual(reader.zone_orphans, 1)
        self.assertIn(0, state['objects']['zmobj'])

    def test_special_waiting_for_its_removal(self):
        memory, reader = self.made()
        glows = sum(1 for (k, _) in reader.placement.objects if k == 'glow')
        synthetic.remove_thinker(memory, reader,
                                 reader.placement.objects[('glow', 0)])
        reader, state = self.check(memory)
        self.assertEqual(len(state['objects']['removed']), 1)
        self.assertEqual(len(state['objects'].get('glow', {})), glows - 1)
        self.assertIn('excl:removed thinker', reader.coverage.totals())


@needs_sweep
class SweepTest(unittest.TestCase):
    def test_scratch_is_never_read_first(self):
        n, violations = checks.check_sweep(SWEEP, Schema())
        self.assertGreaterEqual(n, 100)
        self.assertEqual(violations, [])


@needs_dumps
@needs_a2vm
class A2vmTest(unittest.TestCase):
    def test_through_a2vm(self):
        sch = Schema()
        with tempfile.TemporaryDirectory() as d:
            r = checks.check_dump(SAMPLE, sch, checks.manifest_for(sch),
                                  (A2VM, ROM, Path(d)))
        self.assertEqual(r['a2vm_roundtrip'], [])


@needs_dumps
class CommandLineTest(unittest.TestCase):
    def run_bridge(self, *args, status=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'tools' / 'bridge' / 'bridge.py')] +
            [str(a) for a in args], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(result.returncode, status, result.stderr)
        return result.stdout + result.stderr

    def test_decode_then_write_both_layouts(self):
        """The upstream writer through the command line: changed values
        change exactly their bytes over the base; a state it cannot hold is
        refused with a message, not a traceback."""
        sch = Schema()
        base = Memory.from_image(SAMPLE / 'entry.img')
        reader, state = read(base, sch)
        live = next(i for i, o in sorted(state['objects']['mobj'].items())
                    if not o['free'])
        st = sch.structs
        # (the state's entry, its address, its type): momz, lightlevel and
        # a global, each changed in every byte
        mo, sec = st['MO'].by_name, st['SEC'].by_name
        changes = [
            (('mobj', live, 'momz'), reader.placement.address('mobj', live) +
             mo['momz'].offset, mo['momz'].type),
            (('sector', 1, 'lightlevel'), reader.placement.address(
                'sector', 1) + sec['lightlevel'].offset,
             sec['lightlevel'].type),
            (('global', 'g_game65.s:_g_basetic'), sch.symbols.address(
                'g_game65.s:_g_basetic'), U32)]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.run_bridge('decode', SAMPLE, '-o', d / 'state.json')
            state = canonical.load(d / 'state.json')
            expected = {}
            for key, address, t in changes:
                if key[0] == 'global':
                    holder, name = state['globals'], key[1]
                else:
                    holder, name = state['objects'][key[0]][key[1]], key[2]
                mask = (1 << (8 * t.size)) - 1
                # every bit flipped, in the type's range
                holder[name] = ~holder[name] if t.signed else \
                    holder[name] ^ mask
                raw = (holder[name] & mask).to_bytes(t.size, 'little')
                for i in range(t.size):
                    expected[address + i] = raw[i]
            canonical.save(state, d / 'changed.json')
            self.run_bridge('upstream', d / 'changed.json', '--base', SAMPLE,
                            '-o', d / 'again.img')
            again = Memory.from_image(d / 'again.img')
            changed = {}
            self.assertEqual(sorted(again.banks), sorted(base.banks))
            for bank, data in base.banks.items():
                other = again.banks[bank]
                if other != data:
                    changed.update(((bank << 16) | i, other[i])
                                   for i in range(len(data))
                                   if other[i] != data[i])
            self.assertEqual(changed, expected)
            # a state without an object the base has, without a field,
            # or without a global
            for what, change in (
                    ('missing 0', lambda s: s['objects']['door'].pop(0)),
                    ('missing momz', lambda s: s['objects']['mobj'][
                        live].pop('momz')),
                    ('missing g_game65.s:_g_gametic',
                     lambda s: s['globals'].pop('g_game65.s:_g_gametic'))):
                bad = canonical.load(d / 'state.json')
                change(bad)
                canonical.save(bad, d / 'bad.json')
                out = self.run_bridge('upstream', d / 'bad.json', '--base',
                                      SAMPLE, '-o', d / 'bad.img', status=1)
                self.assertIn(what, out)
                self.assertNotIn('Traceback', out)
                self.assertFalse((d / 'bad.img').exists())
            self.run_bridge('layout', '-o', d / 'layout.json')
            self.run_bridge('port', d / 'state.json', '--manifest',
                            d / 'layout.json', '-o', d / 'port.a2vmimg')
            self.assertEqual((d / 'port.a2vmimg').read_bytes()[:8],
                             b'A2VMIMG1')
            self.assertTrue(json.loads((d / 'layout.json').read_text())[
                'kinds'])


@unittest.skipUnless(
    LINKMAP.exists() and (ROOT / 'build' / 'release' / 'doom-hd.hdv').exists()
    and (ROOT / 'build' / 'ref816' / 'ref816').exists(),
    'dumps.py needs build/linkmap.json, the release image and '
    'build/ref816/ref816: run python3 tools/fetch_upstream.py, python3 '
    'tools/v816/imgmatch.py and make -C tools/ref816')
class DumpsCommandTest(unittest.TestCase):
    def test_runs_leave_only_the_dumps(self):
        """dumps.py --out D leaves the dumps in D and nothing else there
        or in build/bridge (its runs' files go in a directory under D,
        deleted after)."""
        runs = ROOT / 'build' / 'bridge' / 'runs'   # where they once went
        existed = runs.exists()
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run(
                ['nice', '-n', '10', sys.executable,
                 str(ROOT / 'tools' / 'bridge' / 'dumps.py'), '--sets',
                 'title', '--out', d], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()),
                             ['title-01', 'title-02', 'title-03'])
            for p in Path(d).iterdir():
                self.assertTrue((p / 'dump.json').exists())
        if not existed:
            self.assertFalse(runs.exists())


if __name__ == '__main__':
    unittest.main()
