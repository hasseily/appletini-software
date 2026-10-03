"""Speed wave 2, part objapi (docs/speed-parts/objapi.md): the object
API's page-1 window. Without a machine run: glayout.py's rule that the
window's bytes stay below the tic stack, and gobj.s assembled alone with
and without TESTBUILD (its own asserts: the window's code and its
descriptors inside PW_AT-PW_END, the descriptors' lengths). The API's
behaviour is gselftest.py's (test_native_game_skeleton S5) and the
lockstep run's.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT  # noqa: F401

sys.path.insert(0, str(ROOT / 'tools'))

from native import glayout as GL  # noqa: E402

GEN = ROOT / 'build' / 'native' / 'game' / 'skel' / 'gen'
HAVE_CA65 = bool(shutil.which('ca65'))


class Page1Window(unittest.TestCase):

    def test_window_below_the_tic_stack(self):
        lo, hi = GL.TIC_PAGE1
        self.assertEqual(lo, 0x0100)
        self.assertLessEqual(hi, 0x0100 + GL.DRIVER_S + 1 - GL.TIC_STACK)
        GL.check()

    def test_a_larger_stack_budget_is_refused(self):
        old = GL.TIC_STACK
        try:
            GL.TIC_STACK = old + 1
            with self.assertRaisesRegex(ValueError, 'page-1 window'):
                GL.check()
        finally:
            GL.TIC_STACK = old

    @unittest.skipUnless(HAVE_CA65 and (GEN / 'ggame.inc').exists(),
                         'needs ca65 and the skeleton\'s generated includes: '
                         'make -s -C src/native -f game.mk shared skel '
                         'ROOT=$PWD')
    def test_gobj_assembles_with_its_asserts(self):
        work = Path(tempfile.mkdtemp(prefix='tmp-objapi-'))
        try:
            for flags in ([], ['-D', 'TESTBUILD'], ['-D', 'LOADIMG']):
                r = subprocess.run(
                    ['ca65', '--cpu', '65C02', '-I', str(GEN), '-I',
                     str(ROOT / 'src' / 'native')] + flags +
                    ['-o', str(work / 'gobj.o'),
                     str(ROOT / 'src' / 'native' / 'gobj.s')],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(r.stdout.strip(), '', 'a warning: %s'
                                 % r.stdout)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
