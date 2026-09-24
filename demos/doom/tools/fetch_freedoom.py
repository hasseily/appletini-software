#!/usr/bin/env python3
"""Fetch freedoom1.wad (Freedoom Phase 1, BSD licence) for the Doom port.

    python3 tools/fetch_freedoom.py [--out build/wad]

The WAD is not kept in the repository. The npm package kaboom.claude
1.5.3 ships the Freedoom Phase 1 IWAD with its licence, and the npm
registry is reachable from the build machines where GitHub is not, so the
tarball is downloaded from there and two members are extracted:

    package/engine/freedoom1.wad          -> OUT/freedoom1.wad
    package/engine/FREEDOOM-COPYING.txt   -> OUT/FREEDOOM-COPYING.txt

The WAD's SHA-256 must be the one below (the converter's output and the
tests are only known good for that file). If OUT/freedoom1.wad already
has that hash nothing is downloaded. The download honours HTTPS_PROXY and
SSL_CERT_FILE like any urllib client.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

URL = "https://registry.npmjs.org/kaboom.claude/-/kaboom.claude-1.5.3.tgz"
WAD_MEMBER = "package/engine/freedoom1.wad"
LICENCE_MEMBER = "package/engine/FREEDOOM-COPYING.txt"
WAD_SHA256 = "7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d"
PROJECT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(out: Path, url: str = URL, quiet: bool = False) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    wad = out / "freedoom1.wad"
    if wad.exists() and sha256(wad) == WAD_SHA256:
        if not quiet:
            print(f"fetch_freedoom: {wad} is up to date")
        return wad
    if not quiet:
        print(f"fetch_freedoom: downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        blob = resp.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        for name in (WAD_MEMBER, LICENCE_MEMBER):
            if name not in members:
                raise SystemExit(f"fetch_freedoom: {name} is not in the package")
        data = tar.extractfile(members[WAD_MEMBER]).read()
        licence = tar.extractfile(members[LICENCE_MEMBER]).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != WAD_SHA256:
        raise SystemExit(f"fetch_freedoom: freedoom1.wad has SHA-256 {digest}, "
                         f"expected {WAD_SHA256}")
    tmp = wad.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(wad)
    (out / "FREEDOOM-COPYING.txt").write_bytes(licence)
    if not quiet:
        print(f"fetch_freedoom: wrote {wad} ({len(data)} bytes) and FREEDOOM-COPYING.txt")
    return wad


def main(argv=None):
    ap = argparse.ArgumentParser(description="Download and verify freedoom1.wad.")
    ap.add_argument("--out", default=str(PROJECT / "build/wad"), help="directory (default build/wad)")
    ap.add_argument("--url", default=URL)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)
    fetch(Path(args.out), args.url, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
