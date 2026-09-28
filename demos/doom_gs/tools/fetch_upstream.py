#!/usr/bin/env python3
"""Fetch upstream's source and release image into build/.

Usage:  python3 tools/fetch_upstream.py
            [--from-local-clone DIR] [--from-local-image FILE]

Upstream (Webifi's Apple IIgs DOOM, GPL-2) is not part of this repository
and must never be committed to it. This script puts

  build/upstream/               a clone at the pinned commit
  build/release/doom-hd.hdv     the hard disk image of release v1.0

and checks the commit hash and the SHA-256 of the image. It is the only
tool that uses the network. Running it again does nothing when both are
in place and correct.

--from-local-clone and --from-local-image take the data from a clone and
an image that are on this machine already. The same checks apply.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build'
UPSTREAM_DIR = BUILD / 'upstream'
RELEASE_IMAGE = BUILD / 'release' / 'doom-hd.hdv'

UPSTREAM_URL = 'https://github.com/Webifi/iigs-doom'
UPSTREAM_COMMIT = '8ea2eac8b650daf2cf66127c4be6d3f8654dd335'
RELEASE_URL = UPSTREAM_URL + '/releases/download/v1.0/doom-hd.hdv'
RELEASE_SHA256 = \
    '2716166dda1d87faf3bdec572ddcf652379a54da78f1dcccdd0897e00b23bd0d'


class FetchError(Exception):
    """The fetched data is not what the port is pinned to."""


def git(directory, *arguments):
    """The output of a git command run in `directory`.

    A failure is a FetchError with what git said.
    """
    result = subprocess.run(
        ['git', '-C', str(directory)] + list(arguments),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)
    if result.returncode:
        raise FetchError('git %s: %s' % (' '.join(arguments),
                                         result.stderr.strip()))
    return result.stdout.strip()


def clone_state(directory):
    """The commit that the clone in `directory` has checked out, or None
    when its tracked files differ from that commit."""
    if git(directory, 'status', '--porcelain', '--untracked-files=no'):
        return None
    return git(directory, 'rev-parse', 'HEAD')


def fetch_clone(target, source=UPSTREAM_URL, commit=UPSTREAM_COMMIT,
                origin=UPSTREAM_URL):
    """Make `target` a clone of `source` at `commit`.

    Returns True when it had to do something. `source` is a URL or the
    path of a local clone; only what git tracks is taken from it. The
    remote of the new clone is set to `origin` in both cases.
    """
    target = Path(target)
    if (target / '.git').exists():
        if clone_state(target) == commit:
            return False
        raise FetchError(
            '%s is not a clean checkout of %s; remove it and run again'
            % (target, commit))
    if target.exists():
        raise FetchError('%s exists and is not a git clone' % target)
    target.parent.mkdir(parents=True, exist_ok=True)
    git(target.parent, 'clone', '--quiet', '--no-hardlinks',
        '--no-checkout', str(source), str(target))
    git(target, '-c', 'advice.detachedHead=false',
        'checkout', '--quiet', '--detach', commit)
    git(target, 'remote', 'set-url', 'origin', origin)
    found = clone_state(target)
    if found != commit:
        raise FetchError('%s is at %s, expected %s' % (target, found, commit))
    return True


def sha256(path):
    """The SHA-256 of the file `path`, in hexadecimal."""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_release(target, source=RELEASE_URL, expected=RELEASE_SHA256):
    """Make `target` the release image with SHA-256 `expected`.

    Returns True when it had to do something. `source` is a URL or the
    path of a local file. The data goes to a temporary file first, so
    `target` never holds an image that failed the check.
    """
    target = Path(target)
    if target.exists() and sha256(target) == expected:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial')
    try:
        if '://' in str(source):
            with urllib.request.urlopen(source) as response, \
                    open(partial, 'wb') as handle:
                shutil.copyfileobj(response, handle)
        else:
            shutil.copyfile(str(source), str(partial))
        found = sha256(partial)
        if found != expected:
            raise FetchError('%s has SHA-256 %s, expected %s'
                             % (source, found, expected))
        os.replace(str(partial), str(target))
    finally:
        if partial.exists():
            partial.unlink()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--from-local-clone', metavar='DIR',
                        help='clone from this local clone, not the network')
    parser.add_argument('--from-local-image', metavar='FILE',
                        help='copy this image, do not download it')
    args = parser.parse_args(argv)
    try:
        changed = fetch_clone(UPSTREAM_DIR,
                              args.from_local_clone or UPSTREAM_URL)
        print('%s: %s at %s' % (UPSTREAM_DIR,
                                'cloned' if changed else 'in place',
                                UPSTREAM_COMMIT))
        changed = fetch_release(RELEASE_IMAGE,
                                args.from_local_image or RELEASE_URL)
        print('%s: %s, SHA-256 verified' % (
            RELEASE_IMAGE, 'fetched' if changed else 'in place'))
    except (FetchError, OSError) as error:
        sys.exit('fetch_upstream: %s' % error)


if __name__ == '__main__':
    main()
