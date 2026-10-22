"""Compile the library's calibrated stick and fixed-step clock for the host."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPILER = os.environ.get('NATIVE_CC', 'C:/msys64/ucrt64/bin/gcc.exe')


class InputTests(unittest.TestCase):
    def test_stick_and_steps(self):
        output = ROOT / 'build' / 'input-host'
        output.mkdir(parents=True, exist_ok=True)
        executable = output / ('input-host.exe' if os.name == 'nt' else 'input-host')
        command = [COMPILER, '-std=c99', '-Wall', '-Wextra', '-Werror', '-O2',
                   '-I', str(ROOT / 'include'), '-I', str(ROOT / 'src'),
                   *(str(ROOT / 'src' / name) for name in ('input_stick.c', 'timing_steps.c', 'timing_gap.c')),
                   str(ROOT / 'tests' / 'input_host.c'), '-o', str(executable)]
        env = {k: v for k, v in os.environ.items() if k.upper() != 'PATH'}
        path = next((v for k, v in os.environ.items() if k.upper() == 'PATH'), '')
        env['PATH'] = str(Path(COMPILER).parent) + os.pathsep + path
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        result = subprocess.run([str(executable)], cwd=ROOT, env=env, capture_output=True, text=True)
        print(result.stdout, end='')
        self.assertEqual(result.returncode, 0)
        self.assertIn('libtini stick and steps: all host checks passed', result.stdout)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cc', default=os.environ.get('NATIVE_CC', 'C:/msys64/ucrt64/bin/gcc.exe'))
    args, remaining = parser.parse_known_args()
    COMPILER = args.cc
    unittest.main(argv=[sys.argv[0], *remaining])
