"""Tests of tools/ref816: the 65816 core, its vector harness and the
script that fetches the vectors.

The core is built with make into a temporary directory under build/.
Hand-made vector files test the harness without the network; the
SingleStepTests vectors themselves are sampled when
tools/ref816/fetch_vectors.py has put them in build/vectors.
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
from ref816 import fetch_vectors

REF816 = support.ROOT / 'tools' / 'ref816'
VECTOR_BIN = fetch_vectors.BIN_DIR
SAMPLE = 20         # cases run from each of the 512 vector files

have_tools = unittest.skipUnless(
    shutil.which('cc') and shutil.which('make'), 'cc or make is missing')
needs_vectors = unittest.skipUnless(
    (VECTOR_BIN / 'SOURCE').exists(),
    '%s is missing: run python3 tools/ref816/fetch_vectors.py first'
    % VECTOR_BIN.relative_to(support.ROOT))


def state(pc, e=1, p=0x34, a=0, x=0, y=0, s=0x1ff, d=0, dbr=0, pbr=0,
          ram=()):
    return {'pc': pc, 's': s, 'p': p, 'a': a, 'x': x, 'y': y, 'dbr': dbr,
            'd': d, 'pbr': pbr, 'e': e, 'ram': [list(item) for item in ram]}


def lda_immediate(result=0x12):
    """A case of LDA #$12 in emulation mode, expecting A = `result`."""
    code = [(0x001000, 0xa9), (0x001001, 0x12)]
    return {
        'name': 'a9 e 1',
        'initial': state(0x1000, a=0x3400, ram=code),
        'final': state(0x1002, a=0x3400 | result, ram=code),
        'cycles': [[0x001000, 0xa9, 'dp-remx-'], [0x001001, 0x12, '-p-remx-']],
    }


def run(program, *arguments):
    return subprocess.run([str(program)] + [str(a) for a in arguments],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)


@have_tools
class Build(unittest.TestCase):
    def test_builds_without_warnings(self):
        _, output = support.ref816_build()
        self.assertNotRegex(output, re.compile('warning|error', re.I))

    def test_selftest_passes(self):
        out, _ = support.ref816_build()
        result = run(out / 'selftest')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('all checks passed', result.stdout)

    def test_machinetest_passes(self):
        out, _ = support.ref816_build()
        result = run(out / 'machinetest')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('all checks passed', result.stdout)


@have_tools
class Harness(unittest.TestCase):
    """The harness on hand-made vector files."""

    def setUp(self):
        self.out, _ = support.ref816_build()
        self.directory = Path(tempfile.mkdtemp(dir=str(self.out)))
        self.addCleanup(shutil.rmtree, str(self.directory))

    def harness(self, cases):
        path = self.directory / 'a9.e.bin'
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
        self.assertIn('a is 3412, expected 3413', result.stdout)

    def test_extra_cycle_fails(self):
        case = lda_immediate()
        case['cycles'].append([0x001002, None, '---remx-'])
        result = self.harness([case])
        self.assertEqual(result.returncode, 1)
        self.assertIn('2 cycles, expected 3', result.stdout)

    def test_bus_difference_fails(self):
        case = lda_immediate()
        case['cycles'][1][2] = 'd--remx-'      # a data read, not a fetch
        result = self.harness([case])
        self.assertEqual(result.returncode, 1)
        self.assertIn('1 bus failures', result.stdout)

    def test_stopped_clock_marker_is_not_a_cycle(self):
        code = [(0x002000, 0xdb)]
        case = {
            'name': 'db e 1',
            'initial': state(0x2000, ram=code),
            'final': state(0x2001, ram=code),
            'cycles': [[0x002000, 0xdb, 'dp-remx-'],
                       [0x002001, None, '---remx-'],
                       [0x002001, None, '---remx-'],
                       [None, None, '--------']],
        }
        result = self.harness([case])
        self.assertEqual(result.returncode, 0, result.stdout)


class Encoding(unittest.TestCase):
    def test_file_names_cover_every_opcode_in_both_modes(self):
        names = fetch_vectors.file_names()
        self.assertEqual(len(names), 512)
        self.assertEqual(len(set(names)), 512)
        self.assertIn('00.n', names)
        self.assertIn('ff.e', names)

    def test_case_layout(self):
        data = fetch_vectors.encode_case(lda_immediate())
        before = struct.unpack_from('<6H4B', data, 0)
        self.assertEqual(before, (0x1000, 0x1ff, 0x3400, 0, 0, 0,
                                  0x34, 0, 0, 1))
        counts = struct.unpack_from('<3H', data, 32)
        self.assertEqual(counts, (2, 2, 2))
        ram = struct.unpack_from('<I', data, 38)[0]
        self.assertEqual(ram, 0x001000 | 0xa9 << 24)
        cycle = struct.unpack_from('<I2B', data, 38 + 16)
        # VDA, VPA, read, E, M and X; no nulls.
        self.assertEqual(cycle, (0x001000 | 0xa9 << 24, 0xde, 0))
        self.assertEqual(len(data), 38 + 16 + 12)

    def test_nulls(self):
        self.assertEqual(
            fetch_vectors.encode_cycle([None, None, '--------']),
            struct.pack('<I2B', 0, 0, 3))
        self.assertEqual(
            fetch_vectors.encode_cycle([0x123456, None, '---w---l']),
            struct.pack('<I2B', 0x123456, 0x01, 2))

    def test_file_header(self):
        data = fetch_vectors.encode_file(json.dumps([lda_immediate()] * 3))
        self.assertEqual(data[:8], b'SST816V1')
        self.assertEqual(struct.unpack_from('<I', data, 8)[0], 3)


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
        (source / 'v1').mkdir()
        (source / 'v1' / '00.n.json').write_text('[]')
        git('add', 'v1')
        git('commit', '--quiet', '-m', 'first')
        self.first = git('rev-parse', 'HEAD')
        (source / 'v1' / '00.n.json').write_text('[{}]')
        git('commit', '--quiet', '-am', 'second')
        self.url = source.as_uri()
        self.repo = self.directory / 'vectors.git'

    def test_fetches_the_pinned_commit_once(self):
        self.assertTrue(fetch_vectors.fetch_repo(
            self.repo, self.url, self.first))
        self.assertEqual(
            fetch_vectors.git(self.repo, 'cat-file', 'blob',
                              self.first + ':v1/00.n.json'), '[]')
        self.assertFalse(fetch_vectors.fetch_repo(
            self.repo, self.url, self.first))

    def test_missing_commit_is_an_error(self):
        with self.assertRaises(fetch_vectors.FetchError):
            fetch_vectors.fetch_repo(self.repo, self.url, '0' * 40)


@have_tools
@needs_vectors
class Vectors(unittest.TestCase):
    """The first cases of every SingleStepTests file."""

    def test_sample_passes(self):
        out, _ = support.ref816_build()
        files = sorted(VECTOR_BIN.glob('*.bin'))
        self.assertEqual(len(files), 512)
        result = run(out / 'vectors', '--limit', SAMPLE, *files)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('512 files, %d cases: 0 state failures, '
                      '0 cycle-count failures, 0 bus failures'
                      % (512 * SAMPLE), result.stdout)

    def test_vectors_are_from_the_pinned_commit(self):
        self.assertEqual((VECTOR_BIN / 'SOURCE').read_text(),
                         fetch_vectors.stamp_text(
                             fetch_vectors.VECTORS_COMMIT))


if __name__ == '__main__':
    unittest.main()
