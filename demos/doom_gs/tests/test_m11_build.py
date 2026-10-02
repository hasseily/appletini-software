"""Milestone 11, first half: the review's build and tool fixes of
2026-10-02 (docs/MILESTONES.md row 11).

  - src/native/m11.mk's `all` from an empty build/native/m11 (the command
    of src/native/README.md): part s2data's makefile names the rule for
    its include and manifest, so the other parts' objects that read them
    wait for the store instead of stopping at the stand-in that asks for
    `make -f m11.mk part P=s2data` (a dry run into an empty M11, which
    writes nothing);
  - part s2ovl's links (ovf, ovfp, OVLW, OVLWP) run again only when one
    of their objects changed: a second make of the part into a scratch
    M11 links nothing, and a render object made again relinks the frame
    and OVLW;
  - tools/native/s2stbar.py's check modes exit 1 when they report a
    problem (the checks themselves replaced by stand-ins here).

Run by name: python3 tools/testpar.py tests/wip_test_m11_build.py
"""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import support

ROOT = support.ROOT
BUILD = ROOT / 'build'
SRC = ROOT / 'src' / 'native'
HAVE_MAKE = bool(shutil.which('make'))
HAVE_CC65 = bool(shutil.which('ca65') and shutil.which('ld65'))
WAD = BUILD / 'upstream' / 'data' / 'DOOM1.WAD'
TABLES = BUILD / 'native' / 'render' / 'tables'
MEMORY = BUILD / 'ref816' / 'memory.img'


def make(m11: Path, *args, timeout: float = 600.0):
    """make -C src/native -f m11.mk ARGS with M11 set, bounded; the
    process and its output (stdout and stderr together)."""
    res = support.run(['make', '-C', str(SRC), '-f', 'm11.mk',
                       'M11=%s' % m11] + list(args), timeout=timeout,
                      max_bytes=64 << 20, stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT,
                      universal_newlines=True)
    return res, res.stdout


class Scratch(unittest.TestCase):
    """A scratch M11 of its own under build/ (deleted after the test)."""

    def setUp(self):
        BUILD.mkdir(exist_ok=True)
        self.m11 = Path(tempfile.mkdtemp(prefix='tmp-m11-build-',
                                         dir=str(BUILD)))
        self.addCleanup(shutil.rmtree, str(self.m11), True)


@unittest.skipUnless(HAVE_MAKE and WAD.exists() and support.RELEASE_IMAGE
                     .exists(), 'needs make, the WAD and the release image '
                     '(python3 tools/fetch_upstream.py)')
class AllFromEmpty(Scratch):

    def dry_run(self, *jobs):
        res, out = make(self.m11, '-n', 'all', *jobs, timeout=300)
        self.assertNotIn('No rule to make target', out)
        self.assertNotIn('part P=s2data', out,
                         'a part asks for the store instead of waiting '
                         'for it')
        self.assertEqual(res.returncode, 0, out[-2000:])
        lines = out.splitlines()
        # the store is made (once), before the first object that reads it
        store = [k for k, s in enumerate(lines)
                 if 'tools/native/s2data.py --out' in s]
        self.assertEqual(len(store), 1, 'the store made %d times'
                         % len(store))
        readers = [k for k, s in enumerate(lines)
                   if 'ca65' in s and any(
                       '/%s/%s.o' % (part, name) in s for part, name in (
                           ('s2fin', 's2_fin'), ('s2stbar', 's2_st'),
                           ('s2wi', 's2_wi'), ('s2int', 's2_st')))]
        self.assertEqual(len(readers), 4, 'the store\'s readers: %d'
                         % len(readers))
        self.assertLess(store[0], min(readers))
        # a dry run writes nothing
        self.assertEqual(list(self.m11.iterdir()), [])

    def test_serial(self):
        self.dry_run()

    def test_parallel(self):
        self.dry_run('-j4')


@unittest.skipUnless(HAVE_MAKE and HAVE_CC65 and (TABLES / 'math' /
                     'squares.bin').exists() and MEMORY.exists(),
                     'needs make, cc65 on PATH, milestone 8\'s tables '
                     '(python3 tools/native/rtables.py) and ref816\'s '
                     'machine (build/ref816/memory.img)')
class OvlLinks(Scratch):

    LINKS = ('ovf', 'ovfp', 'ovlw', 'ovlwp')

    def objects(self):
        return {p: p.stat().st_mtime_ns
                for p in (self.m11 / 's2ovl').rglob('*.o')}

    def linked(self, out):
        """The images this make linked (ld65's -o)."""
        found = set()
        for name in self.LINKS:
            if (' -o %s ' % (self.m11 / 's2ovl' / name)) in out:
                found.add(name)
        return found

    def test_links_only_when_an_object_changed(self):
        res, out = make(self.m11, 'part', 'P=s2ovl')
        self.assertEqual(res.returncode, 0, out[-2000:])
        self.assertEqual(self.linked(out), set(self.LINKS))
        # a make with no object changed links nothing (a source of the
        # tree edited meanwhile, by another team, makes an object again:
        # then that run says nothing and the next one is taken)
        for _ in range(3):
            before = self.objects()
            res, out = make(self.m11, 'part', 'P=s2ovl')
            self.assertEqual(res.returncode, 0, out[-2000:])
            if self.objects() == before:
                self.assertEqual(self.linked(out), set(), out[-2000:])
                self.assertNotIn('--ovlw-cfg', out)
                break
        else:
            self.skipTest('the render objects changed on every make')
        # every file five seconds old, then bucket.o (in ovf and OVLW, not in
        # the profiled pair) made again: ovf and OVLW are linked again
        old = time.time() - 5
        for p in self.m11.rglob('*'):
            if p.is_file():
                os.utime(str(p), (old, old))
        (self.m11 / 's2ovl' / 'render' / 'bucket.o').unlink()
        res, out = make(self.m11, 'part', 'P=s2ovl')
        self.assertEqual(res.returncode, 0, out[-2000:])
        self.assertTrue({'ovf', 'ovlw'} <= self.linked(out), out[-2000:])
        # OVLW's map made again from the frame's labels when it is missing
        time.sleep(1.1)
        (self.m11 / 's2ovl' / 'ovlw.cfg').unlink()
        res, out = make(self.m11, 'part', 'P=s2ovl')
        self.assertEqual(res.returncode, 0, out[-2000:])
        self.assertTrue((self.m11 / 's2ovl' / 'ovlw.cfg').exists())
        self.assertIn('ovlw', self.linked(out))


class StbarExit(unittest.TestCase):
    """s2stbar.py's check modes: status 1 with a problem, 0 without."""

    def main(self, args, **stand_ins):
        from native import s2stbar as T
        with contextlib.ExitStack() as stack:
            for name, value in stand_ins.items():
                stack.enter_context(mock.patch.object(
                    T, name, lambda *a, value=value, **k: value))
            with contextlib.redirect_stdout(io.StringIO()):
                return T.main(args)

    def frames(self, problems):
        return {'cases': 1, 'runs': 1, 'writes': 0, 'stray': 0,
                'stack': 0, 'nibs': {}, 'problems': problems}

    def test_native(self):
        self.assertEqual(self.main(['--native'], native_frames=self.frames(
            ['demo3 frame 5: digit wrong'])), 1)
        self.assertEqual(self.main(['--native'],
                                   native_frames=self.frames([])), 0)

    def test_tics(self):
        self.assertEqual(self.main(['--tics'], native_tics=self.frames(
            ['tic 3: face wrong'])), 1)
        self.assertEqual(self.main(['--tics'],
                                   native_tics=self.frames([])), 0)

    def test_chain(self):
        def chain(problems):
            return {'frames': 1, 'runs': 1, 'stray': 0,
                    'problems': problems}
        self.assertEqual(self.main(['--chain'], native_chain=chain(
            ['frame 7: row 170 wrong'])), 1)
        self.assertEqual(self.main(['--chain'], native_chain=chain([])), 0)

    def test_synth(self):
        def tic(problems):
            return {'cases': 1, 'paths': {}, 'problems': problems}

        def frame(problems):
            return {'frames': 1, 'kinds': {}, 'problems': problems}
        for t, f, rc in (([], [], 0), (['x'], [], 1), ([], ['x'], 1)):
            self.assertEqual(self.main(
                ['--synth'], synth_tic_model=tic(t),
                synth_model=frame(f)), rc)

    def test_two_modes(self):
        # a problem in one of the modes asked fails the run
        self.assertEqual(self.main(
            ['--native', '--chain'], native_frames=self.frames([]),
            native_chain={'frames': 1, 'runs': 1, 'stray': 0,
                          'problems': ['frame 7: row 170 wrong']}), 1)


if __name__ == '__main__':
    unittest.main()
