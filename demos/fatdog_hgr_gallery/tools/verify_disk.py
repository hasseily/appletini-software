#!/usr/bin/env python3
"""Verify the gallery disk against its bundled sources and build manifest."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fatdog_hgr_disk as build

DEMO = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def first_system_file(disk):
    block = 2
    while block:
        directory = disk[block * 512:(block + 1) * 512]
        for slot in range(13):
            entry = directory[4 + slot * 39:4 + (slot + 1) * 39]
            if entry[0] >> 4 in (0, 15):
                continue
            name = entry[1:1 + (entry[0] & 15)].decode('ascii')
            if entry[16] == 0xFF and name.endswith('.SYSTEM'):
                return name
        block = int.from_bytes(directory[2:4], 'little')
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=DEMO / 'dist/FATDOG_HGR.po')
    args = parser.parse_args()
    path = args.image.resolve()
    manifest = json.loads((path.parent / 'manifest.json').read_text())
    disk = path.read_bytes()
    assert len(disk) == 819200
    assert struct.unpack_from('<H', disk, 0x429)[0] == 1600
    assert sha(disk) == manifest['sha256']
    build.verify_allocation(path)
    files = build.raw_files(path)
    assert first_system_file(disk) == 'GALLERY.SYSTEM'
    assert sha(files['GALLERY.SYSTEM']) == manifest['viewer_sha256']

    expected = []
    for source in (DEMO / 'assets/fgr1.po', DEMO / 'assets/fgr2.po'):
        for name, payload in build.raw_files(source).items():
            assert len(payload) == 8192, name
            assert files[name] == payload, name
            expected.append({'source': source.name, 'name': name,
                             'bytes': len(payload), 'sha256': sha(payload)})
    assert manifest['images'] == expected
    assert manifest['image_count'] == len(expected) == 32
    assert set(files) == {image['name'] for image in expected} | {
        'PRODOS', 'GALLERY.SYSTEM', 'BASIC.SYSTEM', 'README'}
    master = DEMO / 'assets/ProDOS_2_4_3.po'
    system_files = build.raw_files(master)
    assert disk[:1024] == master.read_bytes()[:1024]
    for name in ('PRODOS', 'BASIC.SYSTEM'):
        assert files[name] == system_files[name]

    report = {
        'result': 'PASS', 'image': path.name, 'bytes': len(disk), 'blocks': 1600,
        'format': '800K ProDOS block-order disk image (.po)',
        'sha256': manifest['sha256'], 'viewer_sha256': manifest['viewer_sha256'],
        'images_verified_against_bundled_sources': len(expected),
        'boot_system': 'GALLERY.SYSTEM',
        'filesystem': 'Boot blocks, first SYSTEM file, system files, all image payloads and block allocation verified',
        'runtime_test_performed': False,
    }
    (path.parent / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: 819200-byte ProDOS disk, all 32 images and system files match bundled sources')
    print('PASS: boot ordering, boot blocks and complete filesystem allocation')
    print('SHA-256:', manifest['sha256'])


if __name__ == '__main__':
    main()
