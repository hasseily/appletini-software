"""Compile and exercise the same bounded STARFALL simulation as the 65C02 game."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPILER = os.environ.get('NATIVE_CC', 'C:/msys64/ucrt64/bin/gcc.exe')


class StarfallTests(unittest.TestCase):
    def test_portable_game_core(self):
        output = ROOT / 'build' / 'starfall-host'
        output.mkdir(parents=True, exist_ok=True)
        executable = output / ('starfall-host.exe' if os.name == 'nt' else 'starfall-host')
        # The boss records come from the same converter as the game's art.
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'starfall_bosses.py'),
                        '--header', str(output / 'starfall_bosses.h'), '--art', str(output)],
                       cwd=ROOT, check=True, capture_output=True)
        command = [COMPILER, '-std=c99', '-Wall', '-Wextra', '-Werror', '-O2',
                   '-I', str(ROOT / 'examples' / 'starfall'), '-I', str(output),
                   str(ROOT / 'examples' / 'starfall' / 'game.c'),
                   str(ROOT / 'examples' / 'starfall' / 'boss.c'),
                   str(ROOT / 'tests' / 'starfall_host.c'), '-o', str(executable)]
        env = {k: v for k, v in os.environ.items() if k.upper() != 'PATH'}
        path = next((v for k, v in os.environ.items() if k.upper() == 'PATH'), '')
        env['PATH'] = str(Path(COMPILER).parent) + os.pathsep + path
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        result = subprocess.run([str(executable)], cwd=ROOT, env=env, check=True,
                                capture_output=True, text=True)
        self.assertIn('STARFALL portable core: all checks passed', result.stdout)
        print(result.stdout, end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cc', default=os.environ.get('NATIVE_CC', 'C:/msys64/ucrt64/bin/gcc.exe'))
    args, remaining = parser.parse_known_args()
    COMPILER = args.cc
    unittest.main(argv=[sys.argv[0], *remaining])
