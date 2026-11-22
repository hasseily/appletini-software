#!/usr/bin/env python3
"""Collect the Software 1.3.9 release files; publish nothing.

Build first:
  python demos/onewww/build_onewww.py
All other files come from the Software 1.3.8 folder, with a hash check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Not carried forward from Software 1.3.8.
REPLACED = ('RELEASE_NOTES.md', 'BODY.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', type=Path, required=True, help='the matching FIRMWARE.BIN')
    parser.add_argument('--output', type=Path, default=ROOT / 'releases/1.3.9')
    parser.add_argument('--previous', type=Path, default=ROOT / 'releases/1.3.8')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'demos/onewww/build/ONEWWW.po', out / 'ONEWWW.po')

    previous = json.loads((args.previous / 'RELEASE_MANIFEST.json').read_text())
    retained = []
    for name, record in previous['assets'].items():
        if name in REPLACED:
            continue
        assert sha(args.previous / name) == record['sha256'], name
        shutil.copyfile(args.previous / name, out / name)
        retained.append(name)
    shutil.copyfile(ROOT / 'RELEASE_NOTES_1.3.9.md', out / 'RELEASE_NOTES.md')

    records = {}
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name not in ('SHA256SUMS.txt', 'RELEASE_MANIFEST.json', 'BODY.md'):
            records[path.name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
            if path.name in retained:
                records[path.name]['unchanged_from'] = 'software1.3.8'
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--short'], cwd=ROOT, check=True, capture_output=True,
                                text=True).stdout.strip())
    manifest = {'release': 'Software 1.3.9 for firmware F1.3.9', 'firmware_sha256': sha(args.firmware),
                'head_commit': head, 'working_tree_modified': dirty,
                'new_full_release_board_test': False, 'published': False, 'assets': records}
    (out / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS.txt').write_text(
        ''.join(record['sha256'] + '  ' + name + '\n' for name, record in records.items()), newline='\n')
    print(json.dumps({'release': str(out), 'assets': len(records), 'retained': len(retained),
                      'head_commit': head, 'working_tree_modified': dirty}, indent=2))


if __name__ == '__main__':
    main()
