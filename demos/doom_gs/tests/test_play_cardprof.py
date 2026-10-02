"""The benchmark's phase timing on a2vm (docs/PLAY.md 15): while OPTIONS,
BENCHMARK plays demo3, the Phasor's VIA-A timer 1 is read at the frame's
phase boundaries (the kernel's bt_mark, dl_disp.s's bt_close at the
brain's end) and the result page shows each phase's mean a frame in its
three rows X2 left black (MENUW's m2_bench, from M_BROWS).

One run of the menu's benchmark on DOOM.hdv with demo3 cut after
DEMO_TICS tics (test_play_bench's disk), with a2vm's PC log of the
kernel's steps:
  - the machine's five sums against the same span's kernel steps, read
    from the PC log as tools/native/playtime.py names them (TIC: K_TIC;
    3D: K_WLOAD, nr_frame; MASK: K_MLOAD, nm_masked, nm_bkload, nb_frame
    but its replays; DRAW: nat_replay's calls; REST: the rest), each
    within the timing's own cost (its reads: the K_CALLs of bt_mark and
    the replay's two marks a batch);
  - their total against the realtics (the same clock: a VBL is 20,280
    bus cycles on PAL);
  - the rows' text as the host formats the sums, and drawn on the page
    (a screen shot); the FPS row as test_play_bench's; no overflow; the
    timing stopped and nat_replay's entry back as built.
Escape while it runs: the timing stops, nat_replay's entry is back, no
rows are written. Every run is bounded (playdisk.run) in a directory
under build/ deleted after it (about 30 s in all).
"""

import shutil
import struct
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from support import BUILD, ROOT

sys.path.insert(0, str(ROOT / 'tools'))

from a2vm import costs  # noqa: E402
from native import playdisk as P, playlink as PK, playtime as T  # noqa: E402
from native import render_check as RC  # noqa: E402
import test_play_bench as B  # noqa: E402

GONE = P.missing()
WHY = 'build/ lacks: %s' % '; '.join(GONE) if GONE else ''
needs_build = unittest.skipUnless(not GONE, WHY)

PHASES = ['TIC', '3D', 'MASK', 'DRAW', 'REST']
CYCLES_VBL = 20280              # 312 lines of 65
TIC_FRAC = 45743                # pl_irq.s: a tic each 65,536 / 45,743 VBLs
ROW = 32                        # M_BROWS: three rows of 32 bytes
X2_ROWS = (92, 108, 124)        # m2_bench's rows X2 left black (SHR y)
PCLOG_LIMIT = 100000


def tenths(cycles, frames):
    """bt_rows' mean: (cycles / frames) x 64 / 6,500 rounded, at most
    99,999 tenths of a ms (PAL)."""
    q = cycles // max(frames, 1)
    return min((q * 64 + 3250) // 6500, 99999)


def ms_text(t):
    return '%d.%d' % (t // 10, t % 10)


def rows_text(sums, frames, overflows):
    """The page's rows as dl_disp.s's bt_rows writes them."""
    m = [ms_text(tenths(s, frames)) for s in sums]
    third = 'REST %s  N %d' % (m[4], frames)
    if overflows:
        third += '  OVF %d' % overflows
    return ['TIC %s  3D %s' % (m[0], m[1]),
            'MASK %s  DRAW %s' % (m[2], m[3]), third]


def reference(lines, pr, t0, t1):
    """The PC log's kernel steps between t0 and t1 (fabric clocks) by the
    page's phases, and the timing's own steps apart (MARKS): playtime.py's
    names on a time line cut at t0 and t1."""
    out = defaultdict(int)
    phase, since, image = None, None, None

    def to(new, t):
        nonlocal phase, since
        if phase is not None:
            lo, hi = max(since, t0), min(t, t1)
            if hi > lo:
                out[phase] += hi - lo
        phase, since = new, t

    for ln in lines:
        if ln.name in T.DISPATCH:
            kind = T.DISPATCH[ln.name]
            if kind in ('K_WLOAD', 'K_MLOAD', 'K_TIC', 'K_LOAD'):
                image = {'K_WLOAD': 'WCODE', 'K_MLOAD': 'MCODE',
                         'K_TIC': 'TIC'}.get(kind)
            to({'K_TIC': 'TIC', 'K_WLOAD': '3D', 'K_MLOAD': 'MASK'}.get(
                kind, 'REST'), ln.t)
        elif ln.name == 'k_jsr' and phase is not None:
            name = T.call_name(pr, ln.target, image)
            to(T.PHASE_OF.get(name, 'REST'), ln.t)
        elif ln.name == 'far_pload' and phase == 'REST' and image is None:
            image = pr.banks.get(ln.y)
            if image == 'OVLW':
                to('MASK', ln.t)
        elif ln.name == 'nat_replay':
            to('DRAW', ln.t)
        elif ln.name == 'nb_rret':
            to('MASK', ln.t)
    to(None, t1)
    return out


@needs_build
class CardProf(unittest.TestCase):
    """The short benchmark's disk, made once for the class."""

    @classmethod
    def setUpClass(cls):
        if GONE:
            raise unittest.SkipTest(WHY)
        cls.play = P.make()
        cls.tmp = Path(tempfile.mkdtemp(prefix='tmp-cardprof-test-',
                                        dir=str(BUILD)))
        original = P.demob_segments
        P.demob_segments = B.short_demob(original, B.DEMO_TICS)
        try:
            cls.disk = P.build(cls.play, cls.tmp / 'DOOM.hdv')
        finally:
            P.demob_segments = original
        cls.sym = P.symbols(cls.play)
        cls.lab = P.labels(cls.disk)
        cls.tic = PK.tic_build(cls.play).labels
        cls.replay_at = RC.load_build(RC.OBJ, 'rcard').labels['nat_replay']
        cls.slot = cls.sym['DLG_D_SLOT']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def run_bench(self, script, seconds, extra=()):
        work = Path(tempfile.mkdtemp(prefix='run-', dir=str(self.tmp)))
        self.addCleanup(shutil.rmtree, str(work), True)
        return P.run(self.disk, script, work, 'f121', seconds, timeout=900,
                     extra=list(extra)), work

    def u(self, mem, name, size):
        fmt = {1: '<B', 2: '<H', 4: '<I'}[size]
        return struct.unpack_from(fmt, mem, self.sym[name])[0]

    def sums(self, mem):
        return [struct.unpack_from('<I', mem, self.sym['BT_S'] + 4 * i)[0]
                for i in range(5)]

    def rows(self, mem):
        at = self.sym['M_BROWS']
        return [bytes(mem[at + ROW * i:at + ROW * (i + 1)]).split(b'\0')[0]
                .decode('ascii') for i in range(3)]

    def test_rows_against_the_kernel_steps(self):
        pr = T.probe(self.disk, 'f121')
        pr.pcs[self.tic['bt_start']] = 'bt_start'
        pr.pcs[self.tic['bt_stop']] = 'bt_stop'
        pr.bytes.append('%X' % (self.sym['SLOT_GRP'] + self.slot))
        script, go = B.to_benchmark(7)
        script += '%s snapshot result\n%s shot page\n' % (B.at(go + 40),
                                                         B.at(go + 40.2))
        log = self.tmp / 'pc.log'
        extra = ['--pclog', str(log),
                 '--pclog-pcs', ','.join('%X' % pc for pc in sorted(pr.pcs)),
                 '--pclog-bytes', ','.join(pr.bytes),
                 '--pclog-limit', str(PCLOG_LIMIT)]
        run, _ = self.run_bench(script, go + 40.5, extra)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        mem = run.images['result'][(0, 0)]
        card = run.images['result'][(2, 0)]
        # the result page: the timing stopped, the replay's entry back
        self.assertEqual(self.u(mem, 'M_MSGKIND', 1), B.MSG_BENCH)
        self.assertEqual(self.u(mem, 'BT_PH', 1), 0)
        self.assertEqual(self.u(mem, 'BT_OVF', 1), 0)
        self.assertEqual(card[self.replay_at], 0x8D)     # sta gcol, as built
        self.assertNotEqual(card[self.replay_at], 0x4C)
        frames = self.u(mem, 'DL_BVIEW', 2)
        realtics = self.u(mem, 'DL_BRT', 4)
        sums = self.sums(mem)
        self.assertGreater(frames, 5)
        for name, s in zip(PHASES, sums):
            self.assertGreater(s, 0, name)
        self.assertEqual(self.rows(mem), rows_text(sums, frames, 0))
        # drawn: m2_bench's X2 rows (8 screen rows from y 92, 108, 124,
        # black before the timing) hold the rows' glyphs
        shot = run.shots['page']
        self.assertEqual(shot[:8], b'A2VMSHR1')
        for y in X2_ROWS:
            band = shot[9 + 160 * y:9 + 160 * (y + 8)]
            self.assertGreater(sum(1 for v in band if v), 20, y)
        fps = bytes(mem[self.sym['M_BFPS']:self.sym['M_BFPS'] + 8])
        self.assertEqual(fps.split(b'\0')[0].decode('ascii'),
                         B.fps_text(frames, realtics))
        # the same clock as the realtics (bt_start is at the load's end,
        # starttime a little after it; the realtics count whole tics)
        tic = CYCLES_VBL * 65536 / TIC_FRAC
        self.assertLess(abs(sum(sums) - realtics * tic), 2 * tic,
                        (sum(sums), realtics))
        # the PC log's kernel steps over the same span
        lines = T.read_log(log, pr)
        t0, t1 = self.window(log, pr)
        ref = reference(lines, pr, t0, t1)
        prm = costs.parameters(P.PROFILES['f121'])
        clocks = prm['fabric_mhz'] * prm['line_us'] / 65.0  # a bus cycle
        hz = pr.hz
        replays = sum(1 for ln in lines if ln.name == 'nat_replay' and
                      t0 <= ln.t <= t1)
        marks = 3 * frames                  # the list's: MASK, REST, TIC
        mark = ref['MARKS'] / max(marks, 1)
        cost = ref['MARKS'] + 2 * replays * mark     # every read's
        report = ['%-5s machine %9.2f ms, kernel steps %9.2f ms' % (
            p, s * clocks / hz * 1000, ref[p] / hz * 1000)
            for p, s in zip(PHASES, sums)]
        report.append('the reads: %d list marks, %d replays, %.1f us a '
                      'mark, %.2f ms in all (%.3f ms a frame)' % (
                          marks, replays, mark / hz * 1e6, cost / hz * 1000,
                          cost / hz * 1000 / frames))
        print('\n' + '\n'.join(report))
        for p, s in zip(PHASES, sums):
            self.assertLess(abs(s * clocks - ref[p]), cost,
                            '%s: %s' % (p, '; '.join(report)))
        self.assertLess(abs(sum(sums) * clocks - sum(ref.values())),
                        cost / 4 + 100 * clocks)

    def window(self, log, pr):
        """The timing's span in the PC log: bt_start's and bt_stop's first
        visits with their group (dl_disp.s's) in its slot (another group's
        code may sit at their addresses)."""
        group = self.sym['GROUPS'] + self.sym['DLG_D']
        at = {}
        with open(str(log)) as handle:
            for text in handle:
                f = text.split()
                if text.startswith('#') or int(f[-1], 16) != group:
                    continue
                name = pr.pcs.get(int(f[1], 16))
                if name in ('bt_start', 'bt_stop') and name not in at:
                    at[name] = int(f[0])
        self.assertEqual(sorted(at), ['bt_start', 'bt_stop'])
        return at['bt_start'], at['bt_stop']

    def test_escape_stops_the_timing(self):
        """ESC while the benchmark runs: bmStop, the timing stopped and
        nat_replay's entry back; no rows."""
        script, go = B.to_benchmark(7)
        script += '%s snapshot run\n%s key %d\n%s snapshot esc\n' % (
            B.at(go + 2.8), B.at(go + 3), B.KEY_ESCAPE, B.at(go + 4))
        run, _ = self.run_bench(script, go + 4.5)
        self.assertEqual(run.state['end'], 'cycles', run.out)
        mid, esc = run.images['run'], run.images['esc']
        self.assertEqual(self.u(mid[(0, 0)], 'DL_BENCH', 1), 1)
        self.assertNotEqual(self.u(mid[(0, 0)], 'BT_PH', 1), 0)
        self.assertEqual(mid[(2, 0)][self.replay_at], 0x4C)  # jmp bt_replay
        self.assertEqual(self.u(esc[(0, 0)], 'BT_PH', 1), 0)
        self.assertEqual(esc[(2, 0)][self.replay_at], 0x8D)
        self.assertEqual(self.u(esc[(0, 0)], 'DL_BENCH', 1), 0)
        self.assertEqual(self.rows(esc[(0, 0)]), ['', '', ''])


if __name__ == '__main__':
    unittest.main()
