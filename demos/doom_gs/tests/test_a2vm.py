"""Tests of tools/a2vm, stage 3.1a: the W65C02S core, its vector harness,
its self test, its bench and the script that fetches the vectors.

The core is built with make into a temporary directory under build/.
Hand-made vector files test the harness without the network; the
SingleStepTests WDC 65C02 vectors themselves are sampled when
tools/a2vm/fetch_vectors.py has put them in build/vectors/wdc65c02.
"""

import json
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import support
from a2vm import fetch_vectors

VECTOR_BIN = fetch_vectors.BIN_DIR
SAMPLE = 20         # cases run from each vector file
POPULATED = 254     # the files of WAI ($CB) and STP ($DB) are empty

have_tools = unittest.skipUnless(
    shutil.which('cc') and shutil.which('make'), 'cc or make is missing')
needs_vectors = unittest.skipUnless(
    (VECTOR_BIN / 'SOURCE').exists(),
    '%s is missing: run python3 tools/a2vm/fetch_vectors.py first'
    % VECTOR_BIN.relative_to(support.ROOT))


def state(pc, s=0xfd, a=0, x=0, y=0, p=0x24, ram=()):
    return {'pc': pc, 's': s, 'a': a, 'x': x, 'y': y, 'p': p,
            'ram': [list(item) for item in ram]}


def lda_immediate(result=0x12):
    """A case of LDA #$12, expecting A = `result`."""
    code = [(0x1000, 0xa9), (0x1001, 0x12)]
    return {
        'name': 'a9 1',
        'initial': state(0x1000, a=0x34, ram=code),
        'final': state(0x1002, a=result, ram=code),
        'cycles': [[0x1000, 0xa9, 'read'], [0x1001, 0x12, 'read']],
    }


def sta_absolute_x(dummy_address, x=0x01):
    """A case of STA $2010,X with the dummy read of the fourth cycle at
    `dummy_address`."""
    code = [(0x1000, 0x9d), (0x1001, 0x10), (0x1002, 0x20)]
    target = 0x2010 + x
    return {
        'name': '9d 1',
        'initial': state(0x1000, a=0x77, x=x, ram=code + [(target, 0)]),
        'final': state(0x1003, a=0x77, x=x, ram=code + [(target, 0x77)]),
        'cycles': [[0x1000, 0x9d, 'read'], [0x1001, 0x10, 'read'],
                   [0x1002, 0x20, 'read'],
                   [dummy_address, 0x20 if dummy_address == 0x1002 else 0,
                    'read'],
                   [target, 0x77, 'write']],
    }


def run(program, *arguments):
    return subprocess.run([str(program)] + [str(a) for a in arguments],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


@have_tools
class Build(unittest.TestCase):
    def test_builds_without_warnings(self):
        _, output = support.a2vm_build()
        self.assertNotRegex(output, re.compile('warning|error', re.I))

    def test_selftest_passes(self):
        out, _ = support.a2vm_build()
        result = run(out / 'selftest')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('all checks passed', result.stdout)
        # The one opcode where the core leaves the datasheet is named.
        self.assertIn('opcode 5c takes 4 cycles', result.stdout)

    def test_bench_runs_agree(self):
        out, _ = support.a2vm_build()
        result = run(out / 'bench', 5)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('the three runs end in the same state', result.stdout)
        self.assertRegex(result.stdout, r'inline +\d+ instructions')


@have_tools
class Harness(unittest.TestCase):
    """The harness on hand-made vector files."""

    def setUp(self):
        self.out, _ = support.a2vm_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory))

    def harness(self, cases, name='a9'):
        path = self.directory / (name + '.bin')
        path.write_bytes(fetch_vectors.encode_file(json.dumps(cases)))
        return run(self.out / 'vectors', path)

    def test_passing_case(self):
        result = self.harness([lda_immediate()])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('1 cases: 0 state failures, 0 cycle-count failures, '
                      '0 bus failures', result.stdout)

    def test_wrong_register_fails(self):
        result = self.harness([lda_immediate(result=0x13)])
        self.assertEqual(result.returncode, 1)
        self.assertIn('a is 12, expected 13', result.stdout)

    def test_extra_cycle_fails(self):
        case = lda_immediate()
        case['cycles'].append([0x1002, 0, 'read'])
        result = self.harness([case])
        self.assertEqual(result.returncode, 1)
        self.assertIn('2 cycles, expected 3', result.stdout)

    def test_bus_direction_fails(self):
        case = lda_immediate()
        case['cycles'][1][2] = 'write'
        result = self.harness([case])
        self.assertEqual(result.returncode, 1)
        self.assertIn('1 bus failures', result.stdout)

    def test_unlisted_write_fails(self):
        case = sta_absolute_x(0x2011)
        case['final']['ram'] = case['initial']['ram'][:3]
        result = self.harness([case], '9d')
        self.assertEqual(result.returncode, 1)
        self.assertIn('write to 2011, which the case does not list',
                      result.stdout)

    def test_known_issue_is_counted_not_failed(self):
        # The set reads the last instruction byte; the core its target.
        result = self.harness([sta_absolute_x(0x1002)], '9d')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('1 known issues', result.stdout)
        self.assertIn('known issue, opcode 9d: 1 cases match its rule, '
                      '1 differ from the set', result.stdout)

    def test_known_issue_rule_cannot_hide_agreement(self):
        # A case the rule picks but that agrees with the core fails the
        # run: the rule would be wider than the issue.
        result = self.harness([sta_absolute_x(0x2011)], '9d')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('the rule is wider than the issue', result.stdout)

    def test_known_issue_does_not_excuse_state(self):
        case = sta_absolute_x(0x1002)
        case['final']['a'] = 0x78
        result = self.harness([case], '9d')
        self.assertEqual(result.returncode, 1)
        self.assertIn('1 state failures', result.stdout)

    def test_page_crossing_store_is_not_a_known_issue(self):
        # X = $F0 crosses a page: the core reads the last instruction
        # byte, as the set does.
        case = sta_absolute_x(0x1002, x=0xf0)
        result = self.harness([case], '9d')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('0 known issues', result.stdout)

    def test_empty_file(self):
        result = self.harness([], 'cb')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('cb.bin: no cases in the set', result.stdout)


class Encoding(unittest.TestCase):
    def test_case_layout(self):
        data = fetch_vectors.encode_case(lda_immediate())
        self.assertEqual(struct.unpack_from('<H5B', data, 0),
                         (0x1000, 0xfd, 0x34, 0, 0, 0x24))
        self.assertEqual(struct.unpack_from('<3H', data, 14), (2, 2, 2))
        ram = struct.unpack_from('<I', data, 20)[0]
        self.assertEqual(ram, 0x1000 | 0xa9 << 24)
        cycle = struct.unpack_from('<I', data, 20 + 16)[0]
        self.assertEqual(cycle, 0x1000 | 0xa9 << 16)
        self.assertEqual(len(data), 20 + 16 + 8)

    def test_write_cycle(self):
        self.assertEqual(fetch_vectors.encode_cycle([0x1234, 0x56, 'write']),
                         struct.pack('<I', 0x1234 | 0x56 << 16 | 1 << 24))

    def test_unknown_cycle_kind(self):
        with self.assertRaises(ValueError):
            fetch_vectors.encode_cycle([0x1234, 0x56, 'fetch'])

    def test_file_header(self):
        data = fetch_vectors.encode_file(json.dumps([lda_immediate()] * 3))
        self.assertEqual(data[:8], b'SSTC02V1')
        self.assertEqual(struct.unpack_from('<I', data, 8)[0], 3)

    def test_empty_file(self):
        self.assertEqual(fetch_vectors.encode_file(b''),
                         b'SSTC02V1' + struct.pack('<I', 0))


@unittest.skipUnless(shutil.which('git'), 'git is not installed')
class FetchRepo(unittest.TestCase):
    """fetch_repo on a local repository, never the network."""

    def setUp(self):
        support.BUILD.mkdir(exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='test-vectors-',
                                               dir=str(support.BUILD)))
        self.addCleanup(shutil.rmtree, str(self.directory))
        source = self.directory / 'source'
        source.mkdir()

        def git(*arguments):
            return subprocess.run(
                ['git', '-C', str(source), '-c', 'user.name=Test',
                 '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false'] + list(arguments),
                check=True, stdout=subprocess.PIPE,
                universal_newlines=True).stdout.strip()
        git('init', '--quiet')
        git('config', 'uploadpack.allowFilter', 'true')
        git('config', 'uploadpack.allowAnySHA1InWant', 'true')
        # Different contents, so the two files are different blobs.
        for directory, result in (('wdc65c02/v1', 0x12),
                                  ('rockwell65c02/v1', 0x13)):
            (source / directory).mkdir(parents=True)
            (source / directory / 'a9.json').write_text(
                json.dumps([lda_immediate(result)]))
        (source / 'wdc65c02' / 'v1' / 'cb.json').write_text('')
        git('add', '.')
        git('commit', '--quiet', '-m', 'first')
        self.first = git('rev-parse', 'HEAD')
        (source / 'wdc65c02' / 'v1' / 'a9.json').write_text('[]')
        git('commit', '--quiet', '-am', 'second')
        self.url = source.as_uri()
        self.repo = self.directory / 'vectors.git'

    def test_fetches_the_pinned_commit_and_only_its_blobs(self):
        self.assertTrue(fetch_vectors.fetch_repo(
            self.repo, self.url, self.first))
        blobs = fetch_vectors.tree_blobs(self.repo, self.first)
        self.assertEqual(sorted(blobs), ['a9.json', 'cb.json'])
        self.assertTrue(all(fetch_vectors.has_object(self.repo, blob)
                            for blob in blobs.values()))
        other = fetch_vectors.tree_blobs(self.repo, self.first,
                                         'rockwell65c02/v1')
        self.assertFalse(fetch_vectors.has_object(self.repo,
                                                  other['a9.json']))
        self.assertFalse(fetch_vectors.fetch_repo(
            self.repo, self.url, self.first))

    def test_converts_every_file(self):
        fetch_vectors.fetch_repo(self.repo, self.url, self.first)
        out = self.directory / 'bin'
        self.assertEqual(fetch_vectors.convert_all(
            self.repo, self.first, out, 1), 2)
        self.assertEqual((out / 'a9.bin').read_bytes()[:12],
                         b'SSTC02V1' + struct.pack('<I', 1))
        self.assertEqual((out / 'cb.bin').read_bytes(),
                         b'SSTC02V1' + struct.pack('<I', 0))
        self.assertEqual(fetch_vectors.convert_all(
            self.repo, self.first, out, 1), 0)

    def test_missing_commit_is_an_error(self):
        with self.assertRaises(fetch_vectors.FetchError):
            fetch_vectors.fetch_repo(self.repo, self.url, '0' * 40)


@have_tools
@needs_vectors
class Vectors(unittest.TestCase):
    """The first cases of every SingleStepTests file."""

    def test_sample_passes(self):
        out, _ = support.a2vm_build()
        files = sorted(VECTOR_BIN.glob('*.bin'))
        self.assertEqual(len(files), 256)
        result = run(out / 'vectors', '--limit', SAMPLE, *files)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('256 files (2 empty), %d cases: 0 state failures, '
                      '0 cycle-count failures, 0 bus failures'
                      % (POPULATED * SAMPLE), result.stdout)

    def test_vectors_are_from_the_pinned_commit(self):
        self.assertEqual((VECTOR_BIN / 'SOURCE').read_text(),
                         fetch_vectors.stamp_text(
                             fetch_vectors.VECTORS_COMMIT))


if __name__ == '__main__':
    unittest.main()
