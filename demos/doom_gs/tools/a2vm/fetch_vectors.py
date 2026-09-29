#!/usr/bin/env python3
"""Fetch the SingleStepTests WDC 65C02 vectors into build/vectors/.

Usage:  python3 tools/a2vm/fetch_vectors.py [--jobs N]

The vectors (https://github.com/SingleStepTests/65x02, directory
wdc65c02/v1) give, for each opcode of the WDC 65C02 but WAI ($CB) and STP
($DB), whose files are empty, 10,000 single-instruction cases: the state
before, the state after and every bus cycle. They are third-party data and
are never committed; this script puts

  build/vectors/65x02.git        a shallow bare clone of the pinned
                                 commit, with only the blobs of
                                 wdc65c02/v1 (the repository holds four
                                 other chips and takes about 1 GB per chip)
  build/vectors/wdc65c02/XX.bin  each wdc65c02/v1/XX.json converted to the
                                 binary form below (XX the opcode in hex)
  build/vectors/wdc65c02/SOURCE  the commit and format the files came from

The JSON files take 1 GB, so they are never written out: each is read from
git and converted in memory. Git checks every object it fetches against
its hash, so the pinned commit pins the content. The 65816 vectors of
tools/ref816/fetch_vectors.py live beside these, in build/vectors/bin.

Binary form (little-endian), read by tools/a2vm/vectors.c:

  file   "SSTC02V1", u32 case count, then the cases
  case   state before, state after (7 bytes each),
         u16 RAM entries before, u16 RAM entries after, u16 bus cycles,
         the RAM entries before, the RAM entries after, the cycles
  state  u16 pc; u8 s, a, x, y, p
  RAM    u32: address in bits 0-15, value in bits 24-31
  cycle  u32: address in bits 0-15, value in bits 16-23, bit 24 set for
         a write ("write" in the JSON) and clear for a read ("read")

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
REPO_DIR = VECTORS_DIR / '65x02.git'
BIN_DIR = VECTORS_DIR / 'wdc65c02'

VECTORS_URL = 'https://github.com/SingleStepTests/65x02'
# Head of the repository on 2025-05-10 (pull request 17). It is also the
# revision the Appletini's own W65C02S core was verified against
# (README_W65C02_CORE.md in hasseily/appletini-one).
VECTORS_COMMIT = '2f6980a2d95757486c7bee24355c360e40e2a224'
VECTORS_PATH = 'wdc65c02/v1'

MAGIC = b'SSTC02V1'
STATE = struct.Struct('<H5B')
COUNTS = struct.Struct('<3H')
WORD = struct.Struct('<I')
STATE_FIELDS = ('pc', 's', 'a', 'x', 'y', 'p')
WRITE = 1 << 24


class FetchError(Exception):
    """The vectors could not be fetched or are not what is pinned."""


def git(repo, *arguments, binary=False, stdin=None, environment=None):
    """The output of git run on the repository `repo`."""
    env = dict(os.environ)
    env.update(environment or {})
    result = subprocess.run(
        ['git', '--git-dir', str(repo)] + list(arguments),
        input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        raise FetchError('git %s: %s' % (
            ' '.join(arguments[:3]), result.stderr.decode().strip()))
    return result.stdout if binary else result.stdout.decode().strip()


def has_object(repo, name):
    """True when `name` is in `repo`, without fetching anything."""
    return subprocess.run(
        ['git', '--git-dir', str(repo), 'cat-file', '-e', name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1')).returncode == 0


def tree_blobs(repo, commit, path=VECTORS_PATH):
    """{file name: blob id} of the files in `path` of `commit`."""
    blobs = {}
    for line in git(repo, 'ls-tree', commit, path + '/').splitlines():
        info, name = line.split('\t', 1)
        mode, kind, blob = info.split()
        if kind == 'blob':
            blobs[name.rsplit('/', 1)[-1]] = blob
    return blobs


def fetch_repo(repo, url=VECTORS_URL, commit=VECTORS_COMMIT,
               path=VECTORS_PATH):
    """Make `repo` a bare repository holding `commit` of `url` with no
    history before it and, of the blobs, only those in `path`. Returns
    True when it had to fetch."""
    repo = Path(repo)
    fetched = False
    if not (repo.exists() and has_object(repo, commit + '^{commit}')):
        repo.mkdir(parents=True, exist_ok=True)
        git(repo, 'init', '--quiet', '--bare')
        git(repo, 'fetch', '--quiet', '--depth', '1', '--no-tags',
            '--filter=blob:none', url, commit)
        fetched = True
        if not has_object(repo, commit + '^{commit}'):
            raise FetchError('%s does not hold %s after the fetch'
                             % (url, commit))
    blobs = tree_blobs(repo, commit, path)
    if not blobs:
        raise FetchError('%s has no files in %s' % (commit, path))
    missing = [blob for blob in sorted(set(blobs.values()))
               if not has_object(repo, blob)]
    if missing:
        git(repo, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head',
            '--filter=blob:none', '--stdin', url,
            stdin=('\n'.join(missing) + '\n').encode())
        fetched = True
        still = [blob for blob in missing if not has_object(repo, blob)]
        if still:
            raise FetchError('%d blobs of %s are missing after the fetch'
                             % (len(still), path))
    return fetched


def encode_state(state):
    return STATE.pack(*(state[field] for field in STATE_FIELDS))


def encode_entry(address, value):
    return WORD.pack(address | value << 24)


def encode_cycle(cycle):
    address, value, kind = cycle
    if kind not in ('read', 'write'):
        raise ValueError('cycle kind %r' % (kind,))
    return WORD.pack(address | value << 16 | (WRITE if kind == 'write'
                                               else 0))


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
    """The binary form of one JSON vector file; an empty file (WAI, STP)
    gives a file with no cases."""
    cases = json.loads(text) if text.strip() else []
    return b''.join([MAGIC, struct.pack('<I', len(cases))] +
                    [encode_case(case) for case in cases])


def convert(repo, blob, name, out_dir):
    """Write out_dir/<name>.bin from the JSON blob `blob`."""
    text = git(repo, 'cat-file', 'blob', blob, binary=True,
               environment={'GIT_NO_LAZY_FETCH': '1'})
    target = Path(out_dir) / (name + '.bin')
    partial = target.with_name(target.name + '.partial')
    partial.write_bytes(encode_file(text))
    os.replace(str(partial), str(target))
    return name


def stamp_text(commit):
    return '%s %s\n' % (commit, MAGIC.decode())


def bin_names(blobs):
    """The .bin names, without extension, for the JSON files `blobs`."""
    return sorted(name[:-len('.json')] for name in blobs
                  if name.endswith('.json'))


def converted(out_dir, commit, names):
    out_dir = Path(out_dir)
    stamp = out_dir / 'SOURCE'
    return stamp.exists() and stamp.read_text() == stamp_text(commit) and \
        all((out_dir / (name + '.bin')).exists() for name in names)


def convert_all(repo, commit, out_dir, jobs, path=VECTORS_PATH):
    """Convert every vector file. Returns the number converted; files are
    only converted again when the stamp names another commit or format."""
    out_dir = Path(out_dir)
    blobs = tree_blobs(repo, commit, path)
    names = bin_names(blobs)
    if converted(out_dir, commit, names):
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = out_dir / 'SOURCE'
    if stamp.exists():
        stamp.unlink()
    with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
        futures = [pool.submit(convert, str(repo), blobs[name + '.json'],
                               name, str(out_dir)) for name in names]
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
        count = convert_all(REPO_DIR, VECTORS_COMMIT, BIN_DIR, args.jobs)
        print('%s: %s' % (BIN_DIR, 'converted %d files' % count
                          if count else 'in place'))
    except (FetchError, OSError, ValueError) as error:
        sys.exit('fetch_vectors: %s' % error)


if __name__ == '__main__':
    main()
