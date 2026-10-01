"""Tests of tools/testpar.py, the parallel runner of these tests.

  - the summary: the counts a module's process reports, the status it is
    given (ok, failed, crashed, timeout), the totals, the output shown of
    a module that did not pass and the exit status;
  - one module run for real, in a scratch tests/ of its own: a passing
    one, a failing one, an erring one, one that cannot be imported, one
    whose process dies, one that runs out of time, one whose limits are
    read, and one that leaves processes in sessions of their own, which
    the time limit kills too;
  - the grouping and the order: a module that rewrites shared files never
    runs at the same time as another user of them, the others run
    together; longest first, new modules first;
  - the race tables name only modules and makefiles that exist, and every
    module that writes shared files (a call of testpar.WRITER_CALLS, at any
    depth) is among the writers of its entry; the scan itself, on planted
    modules.

The runs use a scratch directory in build/ and skip without it.
"""

import os
import resource
import shutil
import signal
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import support
import testpar

needs_build = unittest.skipUnless(
    support.BUILD.is_dir(), '%s is missing: run python3 '
    'tools/fetch_upstream.py first' % support.BUILD.relative_to(support.ROOT))


def result(run=3, failures=0, errors=0, skipped=0, successful=True,
           outcomes=None):
    return {'run': run, 'failures': failures, 'errors': errors,
            'skipped': skipped, 'expected_failures': 0,
            'unexpected_successes': 0, 'successful': successful,
            'outcomes': outcomes or {}}


class Judge(unittest.TestCase):
    def test_a_passing_module(self):
        o = testpar.judge('test_a', 1.5, 0, result(skipped=1), 'out')
        self.assertEqual(o.status, 'ok')
        self.assertEqual(o.counts['run'], 3)
        self.assertEqual(o.counts['skipped'], 1)

    def test_a_failing_module(self):
        o = testpar.judge('test_a', 1.5, 1,
                          result(failures=1, successful=False), 'out')
        self.assertEqual(o.status, 'failed')
        self.assertEqual(o.counts['failures'], 1)

    def test_no_result_is_a_crash(self):
        o = testpar.judge('test_a', 1.5, -9, None, 'out')
        self.assertEqual(o.status, 'crashed')
        self.assertEqual(o.counts['run'], 0)

    def test_passing_tests_in_a_failing_process_are_a_crash(self):
        o = testpar.judge('test_a', 1.5, 3, result(), 'out')
        self.assertEqual(o.status, 'crashed')

    def test_a_timeout(self):
        o = testpar.judge('test_a', 9.0, None, None, 'out', timed_out=True)
        self.assertEqual(o.status, 'timeout')


class Summary(unittest.TestCase):
    def outcomes(self):
        return [
            testpar.judge('test_b', 2.0, 0, result(run=4, skipped=2), 'B'),
            testpar.judge('test_a', 1.0, 1,
                          result(run=5, failures=1, errors=2,
                                 successful=False), 'the output of A'),
        ]

    def test_counts_and_totals(self):
        text, status = testpar.summary(self.outcomes(), [], 3.0, 9)
        lines = text.splitlines()
        a = next(line for line in lines if line.startswith('test_a '))
        self.assertEqual(a.split()[1:], ['1.0', '5', '1', '2', '0',
                                         'failed'])
        b = next(line for line in lines if line.startswith('test_b '))
        self.assertEqual(b.split()[1:], ['2.0', '4', '0', '0', '2', 'ok'])
        self.assertIn('2 modules, 9 tests: 1 failures, 2 errors, '
                      '2 skipped', text)
        self.assertIn('wall time 3.0 s with 9 jobs', text)
        self.assertEqual(status, 1)

    def test_the_output_of_failures_only(self):
        text, _ = testpar.summary(self.outcomes(), [], 3.0, 9)
        self.assertIn('test_a: FAILED (exit status 1)', text)
        self.assertIn('the output of A', text)
        self.assertNotIn('\nB\n', text)
        self.assertTrue(text.rstrip().endswith('FAILED: test_a'))

    def test_all_passing(self):
        text, status = testpar.summary(self.outcomes()[:1], [], 2.0, 1)
        self.assertEqual(status, 0)
        self.assertTrue(text.rstrip().endswith('OK'))

    def test_a_failed_prebuild_is_shown(self):
        step = testpar.Step('a build', ['make', 'x'], (), ('test_b',))
        built = [testpar.Built(step, False, 0.5, 'the make output')]
        text, status = testpar.summary(self.outcomes()[:1], built, 2.0, 1)
        self.assertIn('prebuild a build failed', text)
        self.assertIn('the make output', text)
        self.assertEqual(status, 0)     # the tests decide

    def test_long_output_is_cut(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'log'
            path.write_text('x' * 100)
            text = testpar.read_output(path, limit=10)
        self.assertTrue(text.startswith('x' * 10 + '\n'))
        self.assertIn('90 more bytes not shown', text)


MODULES = {
    'test_pass': '''
        import unittest
        class T(unittest.TestCase):
            def test_one(self):
                pass
            def test_two(self):
                for n in range(3):
                    with self.subTest(n=n):
                        self.assertLess(n, 3)
            @unittest.skip('not here')
            def test_skipped(self):
                pass
        ''',
    'test_fail': '''
        import unittest
        class T(unittest.TestCase):
            def test_good(self):
                pass
            def test_bad(self):
                print('what the failing test said')
                self.assertEqual(1, 2)
            def test_bad_subtest(self):
                for n in range(3):
                    with self.subTest(n=n):
                        self.assertNotEqual(n, 1)
        ''',
    'test_error': '''
        import unittest
        class T(unittest.TestCase):
            def test_raises(self):
                raise RuntimeError('an error, not a failure')
        ''',
    'test_import': '''
        import a_module_that_does_not_exist
        ''',
    'test_dies': '''
        import os, unittest
        class T(unittest.TestCase):
            def test_dies(self):
                os._exit(3)
        ''',
    'test_sleeps': '''
        import time, unittest
        class T(unittest.TestCase):
            def test_sleeps(self):
                time.sleep(60)
        ''',
    'test_limits': '''
        import resource, unittest
        class T(unittest.TestCase):
            def test_limits(self):
                print('limits %d %d' % (
                    resource.getrlimit(resource.RLIMIT_FSIZE)[0],
                    resource.getrlimit(resource.RLIMIT_CPU)[0]))
        ''',
    # a process in a session of its own (as bounded.run starts one), which
    # starts another, both left running: their pids in orphan-pids.txt
    'test_orphans': '''
        import subprocess, sys, time, unittest
        HELPER = """
        import os, subprocess, time
        p = subprocess.Popen(['sleep', '60'], start_new_session=True)
        with open('orphan-pids.tmp', 'w') as f:
            f.write('%d %d' % (os.getpid(), p.pid))
        os.replace('orphan-pids.tmp', 'orphan-pids.txt')
        time.sleep(60)
        """
        class T(unittest.TestCase):
            def test_orphans(self):
                subprocess.Popen([sys.executable, '-c',
                                  HELPER.replace('\\n        ', '\\n')],
                                 start_new_session=True)
                time.sleep(60)
        ''',
}


@needs_build
class RunModule(unittest.TestCase):
    """Modules of a scratch tests/, run as the runner runs them."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='tmp-testpar-',
                                         dir=str(support.BUILD)))
        tests = cls.root / 'tests'
        tests.mkdir()
        for name, text in MODULES.items():
            (tests / (name + '.py')).write_text(textwrap.dedent(text))
        (tests / 'helper.py').write_text('')    # not a test module
        cls.scratch = cls.root / 'scratch'
        cls.scratch.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.root), True)

    def run_one(self, name, timeout=120.0):
        return testpar.run_module(name, self.scratch, timeout, self.root)

    def test_discover_follows_the_pattern(self):
        self.assertEqual(testpar.discover(tests=self.root / 'tests'),
                         sorted(MODULES))
        self.assertEqual(testpar.discover(['test_fail.py', 'test_pass'],
                                          tests=self.root / 'tests'),
                         ['test_fail', 'test_pass'])
        self.assertEqual(testpar.discover(['tests/test_fail.py'],
                                          tests=self.root / 'tests'),
                         ['test_fail'])
        with self.assertRaises(SystemExit):
            testpar.discover(['test_none'], tests=self.root / 'tests')

    def test_passing(self):
        o = self.run_one('test_pass')
        self.assertEqual(o.status, 'ok', o.output)
        self.assertEqual(o.returncode, 0)
        self.assertEqual((o.counts['run'], o.counts['failures'],
                          o.counts['errors'], o.counts['skipped']),
                         (3, 0, 0, 1))
        self.assertEqual(o.outcomes, {
            'test_pass.T.test_one': 'ok', 'test_pass.T.test_two': 'ok',
            'test_pass.T.test_skipped': 'skip'})
        self.assertIn('Ran 3 tests', o.output)

    def test_failing(self):
        o = self.run_one('test_fail')
        self.assertEqual(o.status, 'failed')
        self.assertNotEqual(o.returncode, 0)
        self.assertEqual(o.counts['run'], 3)
        self.assertEqual(o.counts['failures'], 2)    # one is a subtest
        self.assertEqual(o.counts['errors'], 0)
        self.assertEqual(o.outcomes['test_fail.T.test_good'], 'ok')
        self.assertEqual(o.outcomes['test_fail.T.test_bad'], 'fail')
        self.assertEqual(o.outcomes['test_fail.T.test_bad_subtest'], 'fail')
        self.assertIn('what the failing test said', o.output)
        self.assertIn('AssertionError: 1 != 2', o.output)
        text, status = testpar.summary([o], [], o.seconds, 1)
        self.assertEqual(status, 1)
        self.assertIn('AssertionError: 1 != 2', text)

    def test_erring(self):
        o = self.run_one('test_error')
        self.assertEqual(o.status, 'failed')
        self.assertEqual((o.counts['failures'], o.counts['errors']), (0, 1))
        self.assertEqual(o.outcomes['test_error.T.test_raises'], 'error')
        self.assertIn('RuntimeError: an error, not a failure', o.output)
        self.assertEqual(testpar.summary([o], [], 1.0, 1)[1], 1)

    def test_an_import_error_is_an_error(self):
        o = self.run_one('test_import')
        self.assertEqual(o.status, 'failed')
        self.assertEqual(o.counts['errors'], 1)
        self.assertIn('a_module_that_does_not_exist', o.output)

    def test_a_dead_process_is_a_crash(self):
        o = self.run_one('test_dies')
        self.assertEqual(o.status, 'crashed')
        self.assertEqual(o.returncode, 3)
        self.assertEqual(testpar.summary([o], [], 1.0, 1)[1], 1)

    def test_the_time_limit(self):
        o = self.run_one('test_sleeps', timeout=3.0)
        self.assertEqual(o.status, 'timeout')
        self.assertLess(o.seconds, 30)
        self.assertIn('killed after 3 s', o.output)
        self.assertEqual(testpar.summary([o], [], 1.0, 1)[1], 1)

    def test_the_limits_are_set_in_the_module(self):
        o = self.run_one('test_limits', timeout=60.0)
        self.assertEqual(o.status, 'ok', o.output)
        line = next(x for x in o.output.splitlines()
                    if x.startswith('limits '))
        size, cpu = (int(x) for x in line.split()[1:])
        self.assertNotEqual(size, resource.RLIM_INFINITY)
        self.assertLessEqual(size, testpar.MAX_BYTES)
        self.assertNotEqual(cpu, resource.RLIM_INFINITY)
        self.assertLessEqual(cpu, 60 + testpar.bounded.CPU_SLACK)

    def test_the_time_limit_kills_what_the_module_started(self):
        pids_file = self.root / 'orphan-pids.txt'

        def alive(pid):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:     # the pid went to another user
                return False
            return True

        def cleanup():
            if pids_file.exists():
                for pid in map(int, pids_file.read_text().split()):
                    if alive(pid):
                        os.kill(pid, signal.SIGKILL)
                pids_file.unlink()
        self.addCleanup(cleanup)
        o = self.run_one('test_orphans', timeout=5.0)
        self.assertEqual(o.status, 'timeout')
        self.assertTrue(pids_file.exists(), o.output)
        pids = [int(x) for x in pids_file.read_text().split()]
        self.assertEqual(len(pids), 2)
        end = time.monotonic() + 10
        while any(alive(p) for p in pids) and time.monotonic() < end:
            time.sleep(0.1)
        self.assertEqual([p for p in pids if alive(p)], [])


class Grouping(unittest.TestCase):
    """Writers of shared files run alone; the rest run together, longest
    first."""

    SHARED = (testpar.Shared('gen', ('test_a', 'test_b')),
              testpar.Shared('image', ('test_c',), ('test_d', 'test_e')))

    def test_conflicts(self):
        c = testpar.conflicts(self.SHARED)
        self.assertEqual(c['test_a'], {'test_b'})
        self.assertEqual(c['test_b'], {'test_a'})
        self.assertEqual(c['test_c'], {'test_d', 'test_e'})
        self.assertEqual(c['test_d'], {'test_c'})   # readers share
        self.assertEqual(c['test_e'], {'test_c'})
        self.assertNotIn('test_f', c)

    def test_a_failed_prebuild_makes_its_writers_exclusive(self):
        step = testpar.Step('x', ['make'], (), ('test_a', 'test_f'),
                            ('test_g',))
        shared = [testpar.Shared(step.name, step.writers, step.readers)]
        c = testpar.conflicts(shared)
        self.assertEqual(c['test_f'], {'test_a', 'test_g'})
        self.assertEqual(c['test_g'], {'test_a', 'test_f'})

    def run_dispatch(self, modules, shared, jobs, seconds):
        """Dispatch with a fake run of `seconds[m]` each; the intervals."""
        lock = threading.Lock()
        spans = {}

        def run(m):
            start = time.monotonic()
            time.sleep(seconds.get(m, 0.05))
            with lock:
                spans[m] = (start, time.monotonic())
        testpar.dispatch(modules, testpar.conflicts(shared), jobs, run)
        return spans

    def test_conflicting_modules_never_overlap(self):
        modules = ['test_c', 'test_a', 'test_d', 'test_b', 'test_e',
                   'test_f', 'test_g']
        spans = self.run_dispatch(modules, self.SHARED, 4,
                                  {'test_c': 0.2, 'test_a': 0.15})
        self.assertEqual(sorted(spans), sorted(modules))
        c = testpar.conflicts(self.SHARED)
        for m, others in c.items():
            for o in others:
                with self.subTest(m=m, o=o):
                    (a0, a1), (b0, b1) = spans[m], spans[o]
                    self.assertTrue(a1 <= b0 or b1 <= a0)
        # the free modules did not wait for the writers
        self.assertLess(spans['test_f'][0], spans['test_c'][1])

    def test_readers_run_together(self):
        spans = self.run_dispatch(['test_d', 'test_e'], self.SHARED, 2,
                                  {'test_d': 0.2, 'test_e': 0.2})
        self.assertLess(spans['test_e'][0], spans['test_d'][1])

    def test_one_job_runs_in_order(self):
        modules = ['test_c', 'test_a', 'test_f']
        spans = self.run_dispatch(modules, self.SHARED, 1, {})
        self.assertEqual(sorted(modules, key=lambda m: spans[m][0]),
                         modules)

    def test_an_exception_stops_the_run(self):
        def run(m):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            testpar.dispatch(['test_a', 'test_f'], {}, 2, run)

    def test_longest_first(self):
        times = {'test_a': 5.0, 'test_b': 30.0, 'test_c': 20.0}
        self.assertEqual(testpar.order(['test_a', 'test_b', 'test_c'],
                                       times),
                         ['test_b', 'test_c', 'test_a'])

    def test_new_modules_first(self):
        times = {'test_a': 5.0, 'test_b': 30.0}
        self.assertEqual(testpar.order(['test_a', 'test_b', 'test_testpar'],
                                       times),
                         ['test_testpar', 'test_b', 'test_a'])

    def test_times_file(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'times.json'
            self.assertEqual(testpar.load_times(path), {})
            testpar.save_times({'test_a': 1.234, 'test_gone': 3.0},
                               ['test_a', 'test_b'], path)
            self.assertEqual(testpar.load_times(path), {'test_a': 1.2})
            path.write_text('not json')
            self.assertEqual(testpar.load_times(path), {})


class Tables(unittest.TestCase):
    """The race tables name modules and makefiles that exist, and every
    module that writes shared files."""

    def test_modules_exist(self):
        found = set(testpar.discover())
        for s in testpar.SHARED:
            with self.subTest(shared=s.name):
                self.assertTrue(s.writers)
                self.assertLessEqual(set(s.writers) | set(s.readers), found)
        for step in testpar.PREBUILD:
            with self.subTest(step=step.name):
                self.assertTrue(step.writers)
                self.assertLessEqual(set(step.writers) | set(step.readers),
                                     found)

    def test_makefiles_exist(self):
        for step in testpar.PREBUILD:
            command = list(step.command)
            if command[0] != 'make':
                continue
            with self.subTest(step=step.name):
                directory = Path(command[command.index('-C') + 1])
                makefile = (command[command.index('-f') + 1]
                            if '-f' in command else 'Makefile')
                self.assertTrue((directory / makefile).exists())

    def test_every_shared_writer_is_listed(self):
        """A module that writes shared files and is missing from PREBUILD
        and SHARED would race the others, and fail only now and then, with
        nothing to say why."""
        self.assertEqual(testpar.unlisted(), [])


PLANTED = {
    'test_listed_not': '''
        from ref816 import title
        title.ensure_image()
        ''',
    'test_private': '''
        from native import render_check as RC
        from ref816 import make_image
        RC.make(tmp / 'obj', src)
        make_image.main(['--banks', '64', '--out', str(scratch)])
        ''',
    'test_shared_make': '''
        from native import render_check as RC
        RC.make()
        ''',
    'test_through_a_helper': '''
        from planted_helper import results
        results()
        ''',
    'planted_helper': '''
        import support
        def results():
            return support.frontend_results()
        ''',
    'test_own_make': '''
        from native import mathrun
        def make(out, src=SRC):
            subprocess.run(['make', '-C', str(src), '-f', 'math.mk',
                            'OUT=%s' % out])
        make(mathrun.OBJ)
        make(tmp / 'obj')
        ''',
}


class Guard(unittest.TestCase):
    """The scan of testpar.unlisted, on planted modules."""

    def test_planted(self):
        with tempfile.TemporaryDirectory() as t:
            tests = Path(t)
            for name, text in PLANTED.items():
                (tests / (name + '.py')).write_text(textwrap.dedent(text))
            found = testpar.unlisted(tests)
        got = sorted((p.split()[0], p.split()[2]) for p in found)
        self.assertEqual(got, [('test_listed_not', 'ref816'),
                               ('test_own_make', 'math.mk,'),
                               ('test_shared_make', 'render.mk,'),
                               ('test_through_a_helper', 'build/gen,')],
                         found)
        helper = next(p for p in found if 'helper' in p)
        self.assertIn('planted_helper.results() '
                      '(test_through_a_helper.py:3) -> '
                      'support.frontend_results() (planted_helper.py:4)',
                      helper)


if __name__ == '__main__':
    unittest.main()
