#!/usr/bin/env python3
"""Collect the Software 1.3.8 release files from fresh builds; publish nothing.

Build first:
  python demos/appletini_demos/appletini_webserver/build_tinibrowser.py
  python demos/appletini_demos/tools/build_appletini_demo_disk.py
Disks that did not change come from the Software 1.3.4 folder, with a hash check.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'demos/appletini_demos/appletini_webserver'
DEMO = WEB.parent
SDK = ROOT / 'libtini'
# Gone or replaced since Software 1.3.4.
REPLACED = ('A2LYNX.po', 'A2MONO.po', 'A2MONO.zip', 'A2MONO-MANIFEST.json', 'Appletini-Demos.po',
            'Appletini-Demos.zip', 'Appletini-Network-Apps.po', 'Appletini-Network-Apps.zip',
            'RELEASE_NOTES.md', 'VALIDATION.zip')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def data_fork(data):
    """The program bytes of a cc65 AppleSingle file."""
    count = struct.unpack_from('>H', data, 24)[0]
    for kind, at, n in (struct.unpack_from('>III', data, 26 + i * 12) for i in range(count)):
        if kind == 1:
            return data[at:at + n]
    raise ValueError('no data fork')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', type=Path, required=True, help='the matching FIRMWARE.BIN')
    parser.add_argument('--output', type=Path, default=ROOT / 'releases/1.3.8')
    parser.add_argument('--previous', type=Path, default=ROOT / 'releases/1.3.4')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    browser = WEB / 'build/tinibrowser'
    shutil.copyfile(browser / 'TINIBROWSER.po', out / 'TINIBROWSER.po')
    shutil.copyfile(browser / 'TINIBROWSER.zip', out / 'TINIBROWSER.zip')
    shutil.copyfile(DEMO / 'build/Appletini_Demos.po', out / 'Appletini-Demos.po')
    with zipfile.ZipFile(out / 'Appletini-Demos.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(out / 'Appletini-Demos.po', 'Appletini_Demos.po')

    # The two IP65 programs that remain: web server and SHR image viewer.
    spec = importlib.util.spec_from_file_location('release_disk', SDK / 'tools/disk.py')
    disk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disk)
    lock = json.loads((SDK / 'tools/prodos-input.json').read_text())
    template = SDK / lock['path']
    assert sha(template) == lock['sha256']
    programs = {name: (WEB / 'build' / (name + '.SYSTEM')).read_bytes() for name in ('A2WEBSRV', 'A2IMG')}
    image = disk.build_image(template.read_bytes(), data_fork(programs['A2WEBSRV']), 'A2WEBSRV.SYSTEM',
                             files=[('A2IMG.SYSTEM', data_fork(programs['A2IMG']), 0xFF, 0x2000)],
                             volume='NETWORK', max_program_bytes=0x9F00)
    (out / 'Appletini-Network-Apps.po').write_bytes(image)

    previous = json.loads((args.previous / 'RELEASE_MANIFEST.json').read_text())
    retained = []
    for name, record in previous['assets'].items():
        if name in REPLACED:
            continue
        assert sha(args.previous / name) == record['sha256'], name
        shutil.copyfile(args.previous / name, out / name)
        retained.append(name)
    shutil.copyfile(ROOT / 'RELEASE_NOTES_1.3.8.md', out / 'RELEASE_NOTES.md')

    records = {}
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name not in ('SHA256SUMS.txt', 'RELEASE_MANIFEST.json'):
            records[path.name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
            if path.name in retained:
                records[path.name]['unchanged_from'] = 'software1.3.4'
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--short'], cwd=ROOT, check=True, capture_output=True,
                                text=True).stdout.strip())
    manifest = {'release': 'Software 1.3.8 for firmware F1.3.8', 'firmware_sha256': sha(args.firmware),
                'head_commit': head, 'working_tree_modified': dirty,
                'new_full_release_board_test': False, 'published': False, 'assets': records}
    (out / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS.txt').write_text(
        ''.join(record['sha256'] + '  ' + name + '\n' for name, record in records.items()), newline='\n')
    print(json.dumps({'release': str(out), 'assets': len(records), 'retained': len(retained),
                      'head_commit': head, 'working_tree_modified': dirty}, indent=2))


if __name__ == '__main__':
    main()
