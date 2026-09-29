"""Tests of src/vm, the 65816 interpreter in 65C02 assembly (milestone 3.2).

The interpreter is assembled and linked with cc65 into a temporary
directory under build/ and run on a2vm by tools/a2vm/vm816 (its vector
harness, lockstep and self test). A sample of the SingleStepTests 65816
vectors runs when tools/ref816/fetch_vectors.py has put them in
build/vectors/bin; `make -C src/vm vectors` runs all of them.
"""

import atexit
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support

SOURCE = support.ROOT / 'src' / 'vm'
VECTOR_BIN = support.BUILD / 'vectors' / 'bin'
SAMPLE = 5          # cases run from each vector file

# The budget of ARCHITECTURE.md section 3.2 (vm.cfg enforces it too).
BUDGET = {'vm.bin.e000': 4096, 'vm.bin.d000': 4096, 'vm.bin.f000': 1228}

have_tools = unittest.skipUnless(
    all(shutil.which(tool) for tool in ('ca65', 'ld65', 'cc', 'make')),
    'ca65, ld65, cc or make is missing')
needs_vectors = unittest.skipUnless(
    (VECTOR_BIN / 'SOURCE').exists(),
    '%s is missing: run python3 tools/ref816/fetch_vectors.py first'
    % VECTOR_BIN.relative_to(support.ROOT))

_built = {}


def build(source=SOURCE, key='main'):
    """Build the interpreter from `source` into a directory of its own
    under build/, once per key. Returns (directory, what make said)."""
    if key not in _built:
        support.BUILD.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='test-vm-', dir=str(support.BUILD)))
        atexit.register(shutil.rmtree, str(out), True)
        result = subprocess.run(
            ['make', '-B', '-f', str(SOURCE / 'Makefile'),
             'HERE=%s/' % source, 'ROOT=%s' % support.ROOT, 'OUT=%s' % out,
             'all'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        _built[key] = (out, result)
    out, result = _built[key]
    if result.returncode:
        raise AssertionError('make failed:\n' + result.stdout)
    return out, result.stdout


def mutant(name, file, old, new):
    """Build a copy of the interpreter with `old` replaced by `new` in
    `file`: a deliberate bug the tests must see."""
    if name not in _built:
        directory = Path(tempfile.mkdtemp(prefix='test-vm-src-',
                                          dir=str(support.BUILD)))
        atexit.register(shutil.rmtree, str(directory), True)
        for path in SOURCE.iterdir():
            if path.is_file():
                shutil.copy(str(path), str(directory / path.name))
        text = (directory / file).read_text()
        assert old in text, (file, old)
        (directory / file).write_text(text.replace(old, new, 1))
        build(directory, name)
    return build(key=name)[0]


def vm816(vm, *arguments):
    out, _ = support.a2vm_build()
    return subprocess.run(
        [str(out / 'vm816'), '--vm', str(vm)] + [str(a) for a in arguments],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)


@have_tools
class Build(unittest.TestCase):
    def test_builds_without_warnings(self):
        _, output = build()
        self.assertNotRegex(output, re.compile('warning|error', re.I))

    def test_parts_fit_the_budget(self):
        out, _ = build()
        for name, budget in BUDGET.items():
            size = (out / name).stat().st_size
            self.assertGreater(size, 0, name)
            self.assertLessEqual(size, budget, name)

    def test_build_is_reproducible(self):
        first, _ = build()
        second, _ = build(key='again')
        for name in BUDGET:
            self.assertEqual((first / name).read_bytes(),
                             (second / name).read_bytes(), name)

    def test_entry_points_are_fixed(self):
        out, _ = build()
        labels = {}
        for line in (out / 'vm.lbl').read_text().splitlines():
            _, value, name = line.split()
            labels[name.lstrip('.')] = int(value, 16)
        order = ['vm_init', 'vm_flush', 'vm_import', 'vm_export', 'vm_run',
                 'vm_step', 'vm_abort']
        self.assertEqual([labels[name] for name in order],
                         [0xe000 + 3 * i for i in range(len(order))])

    def test_every_opcode_has_a_handler(self):
        out, _ = build()
        names = set()
        for line in (out / 'vm.lbl').read_text().splitlines():
            names.add(line.split()[2].lstrip('.'))
        missing = [op for op in range(256) if 'h%02X' % op not in names]
        self.assertEqual(missing, [])


@have_tools
class SelfTest(unittest.TestCase):
    def test_traps_and_run(self):
        out, _ = build()
        result = vm816(out, '--selftest')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('self test: 0 failures', result.stdout)

    def test_sees_a_fetch_trap_one_page_on(self):
        """A fetch that crosses into an unmapped page must not leave the
        program counter in that page: without the undo, the PC exported
        after a jump to its first byte is 256 bytes too far."""
        vm = mutant('trap-vpch', 'core.s',
                    '        dec vpch\n:       stz cpg_ok\n',
                    '        nop\n:       stz cpg_ok\n')
        result = vm816(vm, '--selftest')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('the PC exported: 3500, expected 3400', result.stdout)

    def test_sees_a_stale_code_page_after_a_trap(self):
        """Without EV_PAGE on the fetch trap, a vm_run after it (no
        vm_import) runs the code page of before the jump."""
        vm = mutant('trap-page', 'core.s',
                    'trap_page:\n        tsb vm_event\n',
                    'trap_page:\n')
        result = vm816(vm, '--selftest')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stdout, r'self test: [1-9]\d* failures')


@have_tools
class Lockstep(unittest.TestCase):
    """Random programs on the interpreter and on tools/ref816's core."""

    def run_lockstep(self, vm, banks):
        return vm816(vm, '--lockstep', 1, 60, 2000, banks)

    def test_matches_the_reference(self):
        out, _ = build()
        for banks in (2, 124):
            result = self.run_lockstep(out, banks)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertRegex(result.stdout,
                             r'60 programs, \d+ steps .*: 0 failures')

    def test_is_deterministic(self):
        out, _ = build()
        first = self.run_lockstep(out, 3).stdout.splitlines()[:2]
        second = self.run_lockstep(out, 3).stdout.splitlines()[:2]
        self.assertEqual(first, second)

    def test_sees_a_wrong_operation(self):
        vm = mutant('ora', 'alu.s', 'op_ora: lda vA\n        ora dat',
                    'op_ora: lda vA\n        and dat')
        result = self.run_lockstep(vm, 124)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stdout, r': [1-9]\d* failures')

    def test_sees_stale_code_after_a_write(self):
        """Without the write-through to cached code pages, code that
        changes itself runs stale bytes."""
        vm = mutant('writethrough', 'far.s',
                    '@watched:\n        ldx #NSLOT - 1',
                    '@watched:\n        rts\n        ldx #NSLOT - 1')
        result = vm816(vm, '--lockstep', 7, 300, 3000, 1)
        self.assertEqual(result.returncode, 1, result.stdout)


@have_tools
@needs_vectors
class Vectors(unittest.TestCase):
    def test_sample_passes(self):
        out, _ = build()
        files = sorted(VECTOR_BIN.glob('*.bin'))
        self.assertEqual(len(files), 512)
        result = vm816(out, '--limit', SAMPLE, *files)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('512 files, %d cases: 0 failures' % (512 * SAMPLE),
                      result.stdout)

    def test_harness_sees_a_wrong_operation(self):
        vm = mutant('ora', 'alu.s', 'op_ora: lda vA\n        ora dat',
                    'op_ora: lda vA\n        and dat')
        result = vm816(vm, '--limit', SAMPLE, VECTOR_BIN / '09.n.bin')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('%d failures' % SAMPLE, result.stdout)

    def test_harness_sees_a_stray_write(self):
        """A write the case does not list fails it, even when every
        listed byte is right."""
        vm = mutant('stray', 'handlers.s',
                    'hEA:    sty vpcl                ; NOP\n',
                    'hEA:    sty vpcl                ; NOP\n'
                    '        lda #0\n        sta $1400\n')
        result = vm816(vm, '--limit', SAMPLE, VECTOR_BIN / 'ea.n.bin')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('which the case does not list', result.stdout)


if __name__ == '__main__':
    unittest.main()
