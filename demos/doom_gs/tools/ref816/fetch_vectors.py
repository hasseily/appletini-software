#!/usr/bin/env python3
"""Fetch the SingleStepTests 65816 vectors into build/vectors/.

Usage:  python3 tools/ref816/fetch_vectors.py [--jobs N]

The vectors (https://github.com/SingleStepTests/65816) give, for each of
the 256 opcodes in native and in emulation mode, 10,000 single-instruction
cases: the state before, the state after and every bus cycle. They are
third-party data (the repository states no licence) and are never
committed; this script puts

  build/vectors/65816.git       a shallow bare clone of the pinned commit
  build/vectors/bin/XX.m.bin    each v1/XX.m.json file converted to the
                                binary form below (XX the opcode in hex,
                                m 'n' for native or 'e' for emulation)
  build/vectors/bin/SOURCE      the commit and format the files came from

The JSON files take 2.9 GB, so they are never written out: each is read
from git and converted in memory. Git checks every object it fetches
against its hash, so the pinned commit pins the content.

Binary form (little-endian), read by tools/ref816/vectors.c:

  file   "SST816V1", u32 case count, then the cases
  case   state before, state after (16 bytes each),
         u16 RAM entries before, u16 RAM entries after, u16 bus cycles,
         the RAM entries before, the RAM entries after, the cycles
  state  u16 pc, s, a, x, y, d; u8 p, dbr, pbr, e
  RAM    u32: address in bits 0-23, value in bits 24-31
  cycle  u32 as for RAM, u8 pins, u8 nulls
  pins   bit 7 VDA, 6 VPA, 5 VPB, 4 read (clear for a write), 3 E, 2 M,
         1 X, 0 MLB: the characters of the JSON pin string, in order
  nulls  bit 0: the address is null; bit 1: the value is null

Running it again does nothing when the files are in place.
"""

import argparse
import concurrent.futures
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VECTORS_DIR = ROOT / 'build' / 'vectors'
REPO_DIR = VECTORS_DIR / '65816.git'
BIN_DIR = VECTORS_DIR / 'bin'

VECTORS_URL = 'https://github.com/SingleStepTests/65816'
# Head of the repository on 2024-09-22, which includes the corrections
# for [d],y, PEI and PLB (pull request 2).
VECTORS_COMMIT = 'db6b10401729d5f20f2181dde5d3d7b037093a4a'

MAGIC = b'SST816V1'
STATE = struct.Struct('<6H4B')
COUNTS = struct.Struct('<3H')
ENTRY = struct.Struct('<I')
CYCLE = struct.Struct('<I2B')
PINS = 'dpvremxl'          # bit 7 first; 'r' is the only letter for reads
NULL_ADDRESS, NULL_VALUE = 1, 2
STATE_FIELDS = ('pc', 's', 'a', 'x', 'y', 'd', 'p', 'dbr', 'pbr', 'e')


class FetchError(Exception):
    """The vectors could not be fetched or are not what is pinned."""


def git(repo, *arguments, binary=False):
    """The output of git run on the repository `repo`."""
    result = subprocess.run(
        ['git', '--git-dir', str(repo)] + list(arguments),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise FetchError('git %s: %s' % (
            ' '.join(arguments), result.stderr.decode().strip()))
    return result.stdout if binary else result.stdout.decode().strip()


def has_commit(repo, commit):
    return subprocess.run(
        ['git', '--git-dir', str(repo), 'cat-file', '-e',
         commit + '^{commit}'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def fetch_repo(repo, url=VECTORS_URL, commit=VECTORS_COMMIT):
    """Make `repo` a bare repository holding `commit` of `url`, with no
    history before it. Returns True when it had to fetch."""
    repo = Path(repo)
    if repo.exists() and has_commit(repo, commit):
        return False
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, 'init', '--quiet', '--bare')
    git(repo, 'fetch', '--quiet', '--depth', '1', '--no-tags', url, commit)
    if not has_commit(repo, commit):
        raise FetchError('%s does not hold %s after the fetch' % (url, commit))
    return True


def file_names():
    """The names of the 512 vector files, as in v1/ of the repository."""
    return ['%02x.%s' % (opcode, mode)
            for opcode in range(256) for mode in 'ne']


def encode_state(state):
    return STATE.pack(*(state[field] for field in STATE_FIELDS))


def encode_entry(address, value):
    return ENTRY.pack(address | value << 24)


def encode_cycle(cycle):
    address, value, pins = cycle
    nulls = (NULL_ADDRESS if address is None else 0) | \
        (NULL_VALUE if value is None else 0)
    bits = 0
    for position, letter in enumerate(PINS):
        if pins[position] == letter:
            bits |= 0x80 >> position
    return CYCLE.pack((address or 0) | (value or 0) << 24, bits, nulls)


def encode_case(case):
    """The binary form of one case of the JSON."""
    before, after, cycles = case['initial'], case['final'], case['cycles']
    parts = [encode_state(before), encode_state(after),
             COUNTS.pack(len(before['ram']), len(after['ram']), len(cycles))]
    parts.extend(encode_entry(*entry) for entry in before['ram'])
    parts.extend(encode_entry(*entry) for entry in after['ram'])
    parts.extend(encode_cycle(cycle) for cycle in cycles)
    return b''.join(parts)


def encode_file(text):
    """The binary form of one JSON vector file."""
    cases = json.loads(text)
    return b''.join([MAGIC, struct.pack('<I', len(cases))] +
                    [encode_case(case) for case in cases])


def convert(repo, commit, name, out_dir):
    """Write out_dir/<name>.bin from v1/<name>.json of `commit`."""
    text = git(repo, 'cat-file', 'blob', '%s:v1/%s.json' % (commit, name),
               binary=True)
    target = Path(out_dir) / (name + '.bin')
    partial = target.with_name(target.name + '.partial')
    partial.write_bytes(encode_file(text))
    os.replace(str(partial), str(target))
    return name


def stamp_text(commit):
    return '%s %s\n' % (commit, MAGIC.decode())


def convert_all(repo, commit, out_dir, jobs):
    """Convert every vector file. Returns the number converted; files are
    only converted again when the stamp names another commit or format."""
    out_dir = Path(out_dir)
    stamp = out_dir / 'SOURCE'
    names = file_names()
    if stamp.exists() and stamp.read_text() == stamp_text(commit) and \
            all((out_dir / (name + '.bin')).exists() for name in names):
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    if stamp.exists():
        stamp.unlink()
    with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
        futures = [pool.submit(convert, str(repo), commit, name, str(out_dir))
                   for name in names]
        for done, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            future.result()
            if done % 64 == 0:
                print('converted %d of %d' % (done, len(names)), flush=True)
    stamp.write_text(stamp_text(commit))
    return len(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--jobs', type=int, default=os.cpu_count(),
                        help='conversions to run at once')
    args = parser.parse_args(argv)
    try:
        fetched = fetch_repo(REPO_DIR)
        print('%s: %s at %s' % (REPO_DIR, 'fetched' if fetched else 'in place',
                                VECTORS_COMMIT))
        converted = convert_all(REPO_DIR, VECTORS_COMMIT, BIN_DIR, args.jobs)
        print('%s: %s' % (BIN_DIR, 'converted %d files' % converted
                          if converted else 'in place'))
    except (FetchError, OSError) as error:
        sys.exit('fetch_vectors: %s' % error)


if __name__ == '__main__':
    main()
