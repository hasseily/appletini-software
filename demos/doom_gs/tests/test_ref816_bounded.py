"""Tests of tools/ref816/bounded.py, the bounded runs of the tests and
tools (the ground rules of docs/MILESTONES.md: every run that writes
files has a bound, and a test fails rather than grows).

  - a timeout kills the child's whole process group, grandchildren
    included (a plain subprocess timeout kills the direct child only,
    which on 2026-09-30 left ref816 and a2vm running at 100% CPU after
    their test runs were stopped);
  - a file past max_bytes stops its writer (RLIMIT_FSIZE);
  - the child gets a CPU-time limit a little above the timeout, which
    stops it even when nobody is left to kill it;
  - a bounded run inside another keeps the outer, tighter bounds.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from ref816 import bounded

needs_posix = unittest.skipUnless(bounded.resource is not None and
                                  hasattr(os, 'killpg'), 'not POSIX')


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@needs_posix
class Bounded(unittest.TestCase):
    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='test-bounded-',
                                               dir=str(support.BUILD)))
        self.addCleanup(shutil.rmtree, str(self.directory), True)

    def test_a_timeout_kills_the_grandchildren(self):
        pid_file = self.directory / 'pid'
        script = 'sleep 60 & echo $! > %s; wait' % pid_file
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run(['sh', '-c', script], timeout=1)
        self.assertLess(time.monotonic() - started, 10)
        grandchild = int(pid_file.read_text())
        for _ in range(100):
            if not alive(grandchild):
                break
            time.sleep(0.05)
        self.assertFalse(alive(grandchild), 'the sleep kept running')

    def test_a_file_past_the_limit_stops_its_writer(self):
        path = self.directory / 'big.bin'
        result = bounded.run(
            [sys.executable, '-c',
             'import sys\n'
             'with open(sys.argv[1], "wb") as f:\n'
             '    for i in range(100): f.write(bytes(100000))\n',
             str(path)], timeout=60, max_bytes=1000000,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(path.stat().st_size, 1000000)

    def test_the_cpu_limit_is_above_the_timeout(self):
        code = ('import resource; '
                'print(resource.getrlimit(resource.RLIMIT_CPU)[0], '
                'resource.getrlimit(resource.RLIMIT_FSIZE)[0])')
        result = bounded.run([sys.executable, '-c', code], timeout=10,
                             max_bytes=5 << 20, stdout=subprocess.PIPE,
                             universal_newlines=True, check=True)
        cpu, size = map(int, result.stdout.split())
        self.assertLessEqual(cpu, 10 + bounded.CPU_SLACK)
        self.assertGreaterEqual(cpu, 10)
        self.assertEqual(size, 5 << 20)

    def test_an_inner_run_keeps_the_outer_bounds(self):
        tools = str(support.ROOT / 'tools')
        code = ('import sys, subprocess; sys.path.insert(0, %r)\n'
                'from ref816 import bounded\n'
                'r = bounded.run([sys.executable, "-c", "import resource; '
                'print(resource.getrlimit(resource.RLIMIT_FSIZE)[0])"], '
                'timeout=10, max_bytes=1 << 30, stdout=subprocess.PIPE, '
                'universal_newlines=True, check=True)\n'
                'print(r.stdout.strip())\n' % tools)
        result = bounded.run([sys.executable, '-c', code], timeout=60,
                             max_bytes=3 << 20, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(int(result.stdout), 3 << 20)

    def test_a_timeout_is_required(self):
        with self.assertRaises(ValueError):
            bounded.run(['true'], timeout=0)


if __name__ == '__main__':
    unittest.main()
