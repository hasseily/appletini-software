"""The placement's model (docs/speed-parts/place.md): gtrace's reading of
a2vm's write log, gsim's replay of gcall.s's paging against a Python
twin, the sizes of a placement (FCALL sites), the rules, and the
recorded scenes against the loads they recorded.

  gtrace     a synthetic write log: a jsr between two units, an FCALL
             through fc_call and fc_go into a group, a DCALL of a core
             entry, a jsr inside a unit, an interrupt's pushes, a load,
             the returns seen late, the phase's end at the kernel's jsr;
             the gametic window; a phase the run's end cuts
  gsim       random traces and placements, both restores, W slots and
             frame slots (docs/SPEED.md 9): loads, pages, fc_call calls,
             the frame slots' loads, pages and restores equal to the
             twin's; the check mode
  sizes      an FCALL site's 3 B when the placement makes it fc_call, in
             a routine's group and in a build's fixed core code; the
             sources' sites with a macro's FCALLs; the labels where a
             part's code goes to the core whatever the placement; the
             pages' packing
  rules      A_Chase's callees, the APART pairs (a frame slot is its own
             slot); no frame slot for a routine the tic code stores into;
             the frame slots' room (glayout.frame_slots)
  scenes     (build/native/game/gplace) each recorded scene replayed
             under its own build's placement gives the loads it recorded

The C tools are built by `make -C tools/gplace` (here, into build/gplace);
the scenes are `python3 tools/native/gplacerec.py SCENE` (skipped when
absent).
"""

import random
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

from native import glayout as GL, gplace as GP, gplacerec as REC, \
    gplacesim as S  # noqa: E402


def tools_built():
    try:
        REC.make_tools()
        return True
    except Exception:           # (no compiler: the C tests skip)
        return False


HAVE_TOOLS = tools_built()


def twin(events, grp, slot, pages, policy):
    """gcall.s's paging in Python (the model's reference): (loads, W
    pages, fc_call calls, frame slots' pages, their restores' pages, their
    loads, their restores, the restores' requests). A frame slot (3 and
    up) is loaded like a W slot and restored once a phase, its largest
    group's pages; a phase's restores are one request (fs_restore)."""
    loads = pg = cross = fpg = rpg = floads = restores = rreqs = 0
    cur, need, used = {}, {}, {}
    st = []

    def restore():
        nonlocal rpg, restores, rreqs
        for s, n in used.items():
            rpg += n
            restores += 1
        rreqs += 1 if used else 0
        used.clear()

    def load(s, g):
        nonlocal loads, pg, fpg, floads
        cur[s] = g
        loads += 1
        if s >= GL.FRAME_FIRST:
            floads += 1
            fpg += pages[g]
            used[s] = max(used.get(s, 0), pages[g])
        else:
            pg += pages[g]
    for op, a, b in events:
        if op == 2:
            restore()
            cur, need = {}, {}
            st = []
        elif op == 0:
            ga, gb = grp[a], grp[b]
            if gb not in (0, 254) and gb != ga:
                s = slot[gb]
                cross += 1
                st.append((s, need.get(s, 255) if policy
                           else cur.get(s, 255)))
                if policy:
                    need[s] = gb
                if cur.get(s, 255) != gb:
                    load(s, gb)
            else:
                st.append(None)
        elif op == 1 and st:
            f = st.pop()
            if f:
                s, old = f
                if policy:
                    need[s] = old
                if old != 255 and cur.get(s, 255) != old:
                    load(s, old)
    restore()
    return loads, pg, cross, fpg, rpg, floads, restores, rreqs


def write_events(path, events):
    path.write_bytes(b''.join(struct.pack('<HHH', *e) for e in events))


@unittest.skipUnless(HAVE_TOOLS, 'tools/gplace does not build here')
class GsimTest(unittest.TestCase):
    def test_random_traces_equal_the_twin(self):
        rng = random.Random(7)
        units = 12
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            traces = []
            for t in range(3):
                ev = []
                for phase in range(20):
                    ev.append((2, 0, 0))
                    stack = [rng.randrange(1, units)]
                    for _ in range(rng.randrange(5, 60)):
                        if len(stack) > 1 and rng.random() < 0.45:
                            ev.append((1, 0, 0))
                            stack.pop()
                        else:
                            callee = rng.randrange(1, units)
                            ev.append((0, stack[-1], callee))
                            stack.append(callee)
                    ev += [(1, 0, 0)] * (len(stack) - 1)
                    ev.append((4, 0, 0))
                p = d / ('t%d.ev' % t)
                write_events(p, ev)
                m = d / ('t%d.map' % t)
                m.write_text(''.join('%d %d\n' % (i, i)
                                     for i in range(units)))
                traces.append((p, m, ev))
            args = [str(REC.GSIM), str(units), '3']
            for p, m, _ in traces:
                args += [str(p), str(m)]
            proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    universal_newlines=True)
            try:
                for trial in range(12):
                    grp = [254, 0] + [rng.choice([0, 1, 2, 3, 4, 5])
                                      for _ in range(units - 2)]
                    slot = [0] * 256
                    pages = [0] * 256
                    for g in range(1, 6):
                        # (half the trials with frame slots 3 and 4)
                        slot[g] = rng.choice([1, 2] if trial < 6 else
                                             [1, 2, 3, 4])
                        pages[g] = rng.randrange(1, 9)
                    policy = trial % 2
                    proc.stdin.write('P %d %s %s %s\n' % (
                        policy, ' '.join(map(str, grp)),
                        ' '.join(map(str, slot)),
                        ' '.join(map(str, pages))))
                    proc.stdin.flush()
                    got = list(map(int, proc.stdout.readline().split()))
                    for i, (_, _, ev) in enumerate(traces):
                        want = twin(ev, grp, slot, pages, policy)
                        f = got[10 * i:10 * i + 10]
                        self.assertEqual(tuple(f[0:3] + f[5:10]), want)
                        self.assertEqual(f[3], sum(
                            1 for e in ev if e[0] == 0 and e[2] == 3))
                        self.assertEqual(f[4], 20)
                    if trial >= 6:
                        self.assertGreater(sum(got[10 * i + 7] for i in
                                               range(len(traces))), 0)
            finally:
                proc.stdin.close()
                proc.wait(timeout=30)
                proc.stdout.close()

    def test_check_mode_compares_recorded_loads(self):
        # the core (unit 1) calls unit 2 (group 1, slot 1), which calls
        # unit 3 (group 2, slot 1): group 1's load, 2's, 1's again at the
        # return; the second phase lacks the restore's load
        ev = [(2, 0, 0), (0, 1, 2), (3, 1, 1), (0, 2, 3), (3, 2, 1),
              (1, 0, 0), (3, 1, 1), (1, 0, 0), (4, 0, 0),
              (2, 0, 0), (0, 1, 2), (3, 1, 1), (0, 2, 3), (3, 2, 1),
              (1, 0, 0), (1, 0, 0), (4, 0, 0)]
        with tempfile.TemporaryDirectory() as d:
            p, m = Path(d) / 'a.ev', Path(d) / 'a.map'
            write_events(p, ev)
            m.write_text('0 0\n1 1\n2 2\n3 3\n')
            proc = subprocess.run(
                [str(REC.GSIM), '4', '0', str(p), str(m)],
                input='V 0 254 0 1 2 %s %s\n' % (
                    ' '.join(['0', '1', '1'] + ['0'] * 253),
                    ' '.join(['0', '2', '3'] + ['0'] * 253)),
                stdout=subprocess.PIPE, universal_newlines=True, timeout=30)
        bad, rec, sim, rsum, ssum = map(int, proc.stdout.split())
        self.assertEqual((bad, rec, sim, rsum, ssum), (1, 5, 6, 7, 8))


@unittest.skipUnless(HAVE_TOOLS, 'tools/gplace does not build here')
class GtraceTest(unittest.TestCase):
    """A synthetic tic image: unit A (2) at $6600 and B (3) at $6700 in
    the core, C (4) in group 2 of slot 1; fc_call $80F0, dc_call $80F8,
    act_num $80FC, fc_go $8100, fc_ret $8110, the runtime $80F0-$8120;
    the kernel's k_tic $FF05-$FF34, its steps from $FF34."""

    def run_log(self, lines, extra=''):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            core = bytearray(0x1C00)
            core[0x0000:0x0003] = b'\x20\x00\x67'          # A: jsr B
            core[0x0010:0x0016] = b'\x20\xF0\x80\x02\x00\x9E'  # FCALL C
            core[0x0020:0x0023] = b'\x20\xF8\x80'          # jsr dc_call
            (d / 'core').write_bytes(bytes(core))
            g2 = bytearray(0x40)
            g2[0x10:0x13] = b'\x20\x30\x9E'                # C: jsr C+$30
            (d / 'g2').write_bytes(bytes(g2))
            (d / 'map').write_text('\n'.join([
                'slots 9E00 A600 AE00',
                'grp 0 6600 1C00 %s 0' % (d / 'core'),
                'grp 2 9E00 40 %s 0' % (d / 'g2'),
                'pages 2 4',
                'unit 1 0 6000 9A00', 'unit 2 0 6600 6700',
                'unit 3 0 6700 6800', 'unit 4 2 9E00 9E40',
                'addr slotgrp 19EC', 'addr fct 6C', 'addr fcgrp 40',
                'addr gametic 1DC0', 'addr fc_call 80F0',
                'addr dc_call 80F8', 'addr dc_end 80FC',
                'addr fc_go 8100', 'addr fc_ret 8110', 'addr rt_lo 80F0',
                'addr rt_hi 8120', 'on FF05 FF34', 'offpc FF34 FFC0',
                'tic 3']) + '\n' + extra)
            log = ''.join('w %d 0 %s\n' % (i, x)
                          for i, x in enumerate(lines, 100))
            r = subprocess.run([str(REC.GTRACE), str(d / 'map'),
                                str(d / 'ev'), str(d / 'sum')],
                               input='# a2vm write-log 1\n' + log,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               universal_newlines=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stdout)
            data = (d / 'ev').read_bytes()
            ev = [struct.unpack_from('<HHH', data, i)
                  for i in range(0, len(data), 6)]
            return ev, (d / 'sum').read_text()

    PHASE = [
        'FF05 19ED main 0 19ED 00 FF',      # k_tic: the slots empty
        '6600 01F0 main 0 01F0 00 66',      # A: jsr B
        '6600 01EF main 0 01EF 00 02',
        '6705 01ED main 0 01ED 00 00',      # B: pha
        '6610 01F0 main 0 01F0 00 66',      # (B returned) A: FCALL C
        '6610 01EF main 0 01EF 00 12',
        '80F2 0040 main 0 0040 00 02',      # fc_call: FC_GRP, FC_T
        '80F4 006C main 0 006C 00 00',
        '80F4 006D main 0 006D 00 9E',
        '80F6 01F0 main 0 01F0 00 66',      # (fc_call's own pushes)
        '80F6 01EF main 0 01EF 00 15',
        '8105 01EE main 0 01EE 00 FF',      # fc_go: the slot's group
        '8118 19ED main 0 19ED FF 02',      # gr_load: group 2 in slot 1
        '9E10 01EB main 0 01EB 00 9E',      # C: jsr inside C
        '9E10 01EA main 0 01EA 00 12',
        '6618 01F0 main 0 01F0 00 30',      # (all returned) A: php
        '6620 01F0 main 0 01F0 00 66',      # A: jsr dc_call
        '6620 01EF main 0 01EF 00 22',
        '80F9 0040 main 0 0040 02 00',      # dc_call: a core entry, B
        '80FA 006C main 0 006C 00 00',
        '80FB 006D main 0 006D 00 67',
        '6705 01ED main 0 01ED 00 67',      # an interrupt in B
        '6705 01EC main 0 01EC 00 05',
        '6705 01EB main 0 01EB 00 30',
        'FF40 01FA main 0 01FA 00 FF',      # the kernel's next step
        'FF40 01F9 main 0 01F9 00 42',
    ]

    def test_a_frame_slots_load_and_restore(self):
        """A frame slot (fslot: slot 3 at $2000): a write of SLOT_GRP + 3
        is a load (its unit's calls are named by its group's bytes), and
        fs_restore's $FF there empties it, no load."""
        with tempfile.TemporaryDirectory() as d:
            g5 = Path(d) / 'g5'
            g5.write_bytes(bytes(0x40))
            extra = ('fslot 3 2000 2400\ngrp 5 2000 40 %s 0\npages 5 1\n'
                     'unit 5 5 2000 2040\n' % g5)
            ev, summary = self.run_log(self.PHASE[:12] + [
                '8118 19EF main 0 19EF FF 05',  # gr_load: group 5, slot 3
                '8118 19EF main 0 19EF 05 FF',  # fs_restore
            ] + self.PHASE[-2:], extra)
        self.assertIn((3, 5, 3), ev)
        self.assertEqual(sum(1 for e in ev if e[0] == 3), 1)

    def test_calls_loads_returns(self):
        ev, summary = self.run_log(self.PHASE)
        self.assertEqual(ev, [(2, 0, 0), (0, 2, 3), (1, 0, 0), (0, 2, 4),
                              (3, 2, 1), (1, 0, 0), (0, 2, 3), (1, 0, 0),
                              (4, 0, 0)])
        row = summary.splitlines()[0].split()
        # written, start, end, gametic, tics (B's calls), loads, pages
        self.assertEqual([row[0]] + row[3:], ['1', '0', '2', '1', '4'])

    def test_window_and_cut(self):
        gt = ['FF05 1DC0 main 0 1DC0 00 09']      # gametic 9: outside
        ev, summary = self.run_log(
            gt + self.PHASE + self.PHASE[:5], 'window 0 5\n')
        self.assertEqual(ev, [])
        rows = [x for x in summary.splitlines() if not x.startswith('#')]
        self.assertEqual(len(rows), 1)          # (the cut phase: none)
        self.assertEqual(rows[0].split()[0], '0')
        self.assertIn('# cut 1', summary)


class FakeBuild(types.SimpleNamespace):
    pass


class SizesTest(unittest.TestCase):
    def test_fcall_sites_change_sizes(self):
        a, b, c = 'x.s:A', 'x.s:B', 'y.s:C'
        build = FakeBuild(label='play', place={a: 1, b: 1, c: 2},
                          sizes={a: 100, b: 50, c: 40}, fixed=1000,
                          core_modules={'gthink'}, fc_sites={(a, c): 2})
        sites = {a: {b: 1, c: 2}, '@file:gthink': {a: 1, c: 1}}
        sz = GP.Sizer([build], sites)
        self.assertEqual(sz.groups({a: 1, b: 1, c: 2}), {1: 150, 2: 40})
        # B out of A's group: A's jsr B becomes fc_call (+3); C into
        # group 1: A's two FCALLs of C become jsrs (-6)
        self.assertEqual(sz.groups({a: 1, b: 2, c: 1}), {1: 137, 2: 50})
        table, fixed = sz.core({a: 1, b: 1, c: 2})
        self.assertEqual((table, fixed), (0, [1000]))
        # A and C in the core: the fixed code's two FCALLs become jsrs
        table, fixed = sz.core({a: 0, b: 1, c: 0})
        self.assertEqual(fixed, [994])
        self.assertEqual(table, 100 + 3 - 6 + 40)

    def test_sources_sites_with_macros(self):
        names = GL.native_names()
        keys = sorted(k for k in names if not GL.inlined(k))[:3]
        n = [names[k] for k in keys]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'game' / 'p').mkdir(parents=True)
            (d / 'm.inc').write_text('.macro TWICE\n        FCALL %s\n'
                                     '        FCALL %s\n.endmacro\n'
                                     % (n[2], n[2]))
            (d / 'game' / 'p' / 'p.s').write_text(
                '        FCALL %s\n'
                '        ROUTINE %s\n'
                '@x:     FCALL %s   ; a call\n'
                '        TWICE\n'
                '        ROUTINE %s\n'
                ';       FCALL %s\n' % (n[1], n[0], n[1], n[1], n[2]))
            sites = GP.fcall_sites(d)
        self.assertEqual(sites, {'@file:p': {keys[1]: 1},
                                 keys[0]: {keys[1]: 1, keys[2]: 2}})

    def test_fixed_labels(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'game' / 'p').mkdir(parents=True)
            (d / 'game' / 'p' / 'p.s').write_text(
                '        ROUTINE A\nloop:   rts\n'
                '        .segment "GCORE"\nFC_HERE .set 0\n'
                '; a comment\nresume: rts\nmore:   rts\n'
                '        .segment "DRIVER"\nentry:  rts\n')
            self.assertEqual(REC.fixed_labels(d), ['resume'])

    def test_placement_asserts(self):
        names = GL.native_names()
        keys = sorted(k for k in names if not GL.inlined(k))[:3]
        n = [names[k] for k in keys]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'game' / 'p').mkdir(parents=True)
            (d / 'game' / 'p' / 'p.s').write_text(
                '        .assert GP_%s_G = 0, error, "in the core"\n'
                '        .assert GP_%s_G = GP_%s_G, error, "one group"\n'
                ';       .assert GP_%s_G = 0\n' % (n[0], n[1], n[2], n[2]))
            self.assertEqual(GP.placement_asserts(d),
                             [('core', keys[0]), ('one', keys[1], keys[2])])

    def test_pack(self):
        # GCODE0 holds 11 groups of 8 pages ($0200-$5FFF), GCODE1 23
        self.assertTrue(GP.pack_ok([8] * 34))
        self.assertFalse(GP.pack_ok([8] * 35))
        self.assertTrue(GP.pack_ok([8] * 11 + [6] + [8] * 23))


class RulesTest(unittest.TestCase):
    def problem(self, place, slots):
        keys = [GP.CHASE, 'p_enemy65.s:lookForPlayers',
                'p_path65.s:traverseTo', 'p_attack65.s:PTR_AimTraverse',
                'z.s:other']
        build = FakeBuild(label='game', place=dict(place),
                          sizes={k: 10 for k in keys}, fixed=0,
                          core_modules=set(), fc_sites={})
        sz = GP.Sizer([build], {})
        sites = {GP.CHASE: {'p_enemy65.s:lookForPlayers': 1}}
        return GP.Problem(sz, None, sites, place, slots, {})

    def test_frame_slots(self):
        """Two groups in frame slots never share one (A_Chase's rule, the
        APART pairs); a routine the tic code stores into is never in a
        frame slot; the frame slots' room."""
        place = {GP.CHASE: 1, 'p_enemy65.s:lookForPlayers': 2,
                 'p_path65.s:traverseTo': 3,
                 'p_attack65.s:PTR_AimTraverse': 4, 'z.s:other': 0}
        ok = self.problem(place, {1: GP.FRAME, 2: GP.FRAME, 3: GP.FRAME,
                                  4: GP.FRAME})
        self.assertEqual(ok.rule_problems(ok.place()), [])
        flood, w = 'p_pspr65.s:recursiveSound', 'w.s:W'
        build = FakeBuild(label='play', place={flood: 1, w: 2},
                          sizes={flood: 10, w: 10}, fixed=0,
                          core_modules=set(), fc_sites={}, exact=True,
                          stored={w})
        sz = GP.Sizer([build], {})
        for slots, bad in (({1: 1, 2: 2}, []), ({1: GP.FRAME, 2: 2}, [flood]),
                           ({1: 1, 2: GP.FRAME}, [w])):
            prob = GP.Problem(sz, None, {}, {flood: 1, w: 2}, slots, {})
            got = prob.rule_problems(prob.place())
            self.assertEqual(len(got), len(bad), got)
            for k in bad:
                self.assertTrue(any(k in x for x in got), got)
        gb = {g: 1900 for g in range(1, 9)}
        self.assertEqual(GP.frame_problems({g: GP.FRAME for g in gb}, gb),
                         [])
        gb[9] = 1900
        self.assertTrue(GP.frame_problems({g: GP.FRAME for g in gb}, gb))
        fs = GL.frame_slots([{'slot': 3 + i, 'bytes': n} for i, n in
                             enumerate((100, 1900, 700, 1500))])
        self.assertEqual(sorted(fs), [3, 4, 5, 6])
        for lo, hi in fs.values():
            self.assertTrue(lo >= 0x2000 and hi <= 0x6000 and
                            (hi <= 0x4000 or lo >= 0x4000))

    def test_chase_and_apart(self):
        place = {GP.CHASE: 1, 'p_enemy65.s:lookForPlayers': 2,
                 'p_path65.s:traverseTo': 3,
                 'p_attack65.s:PTR_AimTraverse': 4, 'z.s:other': 0}
        ok = self.problem(place, {1: 1, 2: 2, 3: 1, 4: 2})
        self.assertEqual(ok.rule_problems(ok.place()), [])
        bad = self.problem(place, {1: 1, 2: 1, 3: 2, 4: 2})
        p = bad.rule_problems(bad.place())
        self.assertEqual(len(p), 2)
        self.assertTrue(any('A_Chase' in x for x in p))
        self.assertTrue(any('APART' in x for x in p))
        # in one group, or a callee in the core: no rule broken
        place[GP.CHASE] = 2
        same = self.problem(place, {2: 1, 3: 1, 4: 1})
        self.assertFalse(any('A_Chase' in x for x in
                             same.rule_problems(same.place())))


@unittest.skipUnless(HAVE_TOOLS, 'tools/gplace does not build here')
class ScenesTest(unittest.TestCase):
    def test_recorded_scenes_reproduce_their_loads(self):
        scenes = S.recorded()
        if not scenes:
            self.skipTest('no recorded scene (python3 tools/native/'
                          'gplacerec.py still)')
        for line in S.check_scenes(scenes):
            self.assertNotIn('MISMATCH', line)


if __name__ == '__main__':
    unittest.main()
