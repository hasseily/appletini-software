#!/usr/bin/env python3
"""Verify the gallery disk against its bundled sources and build manifest."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_fatdog_magic_disk as build
from prodos import entries, entry_name, word

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
    parser.add_argument('--image', type=Path, default=DEMO / 'dist/FATDOG_MAGIC.po')
    args = parser.parse_args()
    path = args.image.resolve()
    manifest = json.loads((path.parent / 'manifest.json').read_text())
    disk = path.read_bytes()
    assert len(disk) == 32 * 1024 * 1024
    assert struct.unpack_from('<H', disk, 0x429)[0] == 65535
    assert disk[0x405:0x405 + (disk[0x404] & 15)] == b'FATDOG.MAGIC'
    assert sha(disk) == manifest['sha256']
    build.verify_allocation(path)
    files = build.raw_files(path)
    root = {entry_name(e): e for _, e in entries(disk)}
    assert set(root) == {'PRODOS', 'MAGIC.SYSTEM', 'BASIC.SYSTEM', 'STANDARD.HGR', 'BROOKS.SHR.3200', 'README'}
    folder = root['STANDARD.HGR']
    assert folder[0] >> 4 == 13 and folder[16] == 15
    # GS/OS lowercase bits spell Standard.HGR, rendered as Standard HGR.
    assert word(folder, 28) == 0xBF80
    image_entries = {entry_name(e): e for _, e in entries(disk, word(folder, 17))}
    assert first_system_file(disk) == 'MAGIC.SYSTEM'
    assert sha(files['MAGIC.SYSTEM']) == manifest['viewer_sha256']

    expected = []
    for source in (DEMO / 'assets/fgr1.po', DEMO / 'assets/fgr2.po'):
        for name, payload in build.raw_files(source).items():
            assert len(payload) == 8192, name
            assert files["STANDARD.HGR/" + name] == payload, name
            assert image_entries[name][16] == 6 and word(image_entries[name], 31) == 0x4000, name
            expected.append({'source': source.name, 'name': name, 'path': 'STANDARD.HGR/' + name,
                             'bytes': len(payload), 'sha256': sha(payload)})
    brooks_folder = root['BROOKS.SHR.3200']
    brooks_entries = {entry_name(e): e for _, e in entries(disk, word(brooks_folder, 17))}
    originals = list(build.brooks.images())
    assert len(originals) == len(brooks_entries) == 20
    for source, name, payload in originals:
        path_in_disk = 'BROOKS.SHR.3200/' + name
        assert files[path_in_disk] == payload
        assert brooks_entries[name][16] == 6 and word(brooks_entries[name], 31) == 0x2000
        # The only import changes are the bank/address bytes of each palette pointer.
        original = source.read_bytes()
        changed = {i for i, (a, b) in enumerate(zip(original, payload)) if a != b}
        assert changed <= {0x7DF9, 0x7DFA, 0x7DFB, 39168 + 0x7DF9, 39168 + 0x7DFA, 39168 + 0x7DFB}
        expected.append({'source': source.name, 'name': name, 'path': path_in_disk,
                         'bytes': len(payload), 'sha256': sha(payload)})
    assert manifest['folders'] == [{'path': 'STANDARD.HGR', 'label': 'Standard HGR'},
                                  {'path': 'BROOKS.SHR.3200', 'label': 'Brooks SHR-3200'}]
    assert manifest['images'] == expected
    assert manifest['image_count'] == len(expected) == 52
    assert set(files) == {image['path'] for image in expected} | {
        'PRODOS', 'MAGIC.SYSTEM', 'BASIC.SYSTEM', 'README'}
    master = DEMO / 'assets/ProDOS_2_4_3.po'
    system_files = build.raw_files(master)
    assert disk[:1024] == master.read_bytes()[:1024]
    for name in ('PRODOS', 'BASIC.SYSTEM'):
        assert files[name] == system_files[name]

    report = {
        'result': 'PASS', 'image': path.name, 'bytes': len(disk), 'blocks': 65535,
        'format': '32 MB ProDOS block-order disk image (.po)',
        'sha256': manifest['sha256'], 'viewer_sha256': manifest['viewer_sha256'],
        'images_verified_against_bundled_sources': len(expected),
        'boot_system': 'MAGIC.SYSTEM',
        'folders': manifest['folders'],
        'filesystem': 'Boot blocks, boot order, system files, image payloads/metadata, directory tree and allocation verified',
        'runtime_test_performed': False,
    }
    (path.parent / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: 33554432-byte ProDOS disk, all 52 images and system files match bundled sources')
    print('PASS: boot ordering, boot blocks and complete filesystem allocation')
    print('SHA-256:', manifest['sha256'])


if __name__ == '__main__':
    main()
