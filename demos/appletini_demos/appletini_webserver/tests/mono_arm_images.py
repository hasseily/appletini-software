#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pictures converted by the card: one request each, no decoder overlay,
and no network when the page scrolls back to a stored picture."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
from mono_verify import ROOT
from mono_integration import fixtures, warm


class RecordingFiles(dict):
    def __init__(self, files):
        super().__init__(files)
        self.read = []

    def __getitem__(self, name):
        self.read.append(name)
        return super().__getitem__(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build' / 'tinibrowser')
    args = parser.parse_args()
    out = args.build.resolve()
    target = deepcopy(warm(out))
    target.memory.fixtures = fixtures()
    target.files = RecordingFiles(target.files)
    keys = bytearray(b'ghttps://fixture.test/start\r')
    captures = {}
    captures[len(keys)] = 'arm-top'      # images are on from the start
    keys += b' '
    captures[len(keys)] = 'arm-scrolled'
    keys += b'p'
    captures[len(keys)] = 'arm-back'
    keys += b'q'
    target.input = list(keys)
    target.capture_at = captures
    target.keyboard_calls = 0
    target.captures = []
    start = target.cpu.processorCycles
    target.run(target.steps + 80_000_000)
    memory = target.memory
    pictures = ['https://fixture.test/docs/checker.gif', 'https://fixture.test/images/tile.png',
                'https://fixture.test/tile.jpg']
    # Each picture once, in page order, and none again for the two scrolls.
    assert memory.picture_requests == pictures, memory.picture_requests
    assert set(target.files.read) <= {'TINI.WEB', 'TINI.NET'}, target.files.read
    shots = {item['name']: item for item in target.captures}
    assert shots['arm-top']['sha256'] == shots['arm-back']['sha256']
    assert len(shots['arm-scrolled']['requests']) == len(shots['arm-top']['requests'])
    assert not target.opened
    assert not memory.ramrd and not memory.ramwrt and memory.bank == 0
    assert memory.intcxrom and not memory.selected
    report = {'model': 'actual NMOS6502 browser; mocked ProDOS, HTTP FIFO and card picture service',
              'board_evidence': False, 'picture_requests': memory.picture_requests,
              'cycles': target.cpu.processorCycles - start,
              'captures': target.captures}
    (out / 'arm-images.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('PASS card pictures: one request each, no decoder overlay, scroll without network')


if __name__ == '__main__':
    main()
