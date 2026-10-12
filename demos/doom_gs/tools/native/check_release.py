#!/usr/bin/env python3
"""Check a built disk's menus, gameplay, music and attract loop in a2vm.

Run after build.sh: python3 tools/native/check_release.py
This uses the F1.2.2 TURBO model with virtual Disk II acceleration disabled;
it is not a ROM-level ProDOS boot or a physical-hardware test.
"""
import hashlib
import json
import re
from pathlib import Path

import playdisk


SCENARIOS = {
    'play': '''cycle 1800000000 key 0x1b
cycle 2200000000 shot menu
cycle 2200000000 key 0x0d
cycle 2600000000 key 0x0d
cycle 4500000000 shot level
cycle 4500000000 snapshot level
cycle 4500000000 hold w
cycle 4800000000 release
cycle 5500000000 shot moved
cycle 5500000000 snapshot moved
cycle 5500000000 stop
''',
    'attract': '''cycle 6000000000 shot demo
cycle 6000000000 snapshot demo
cycle 8000000000 shot later
cycle 8000000000 snapshot later
cycle 8000000000 stop
''',
}


def main():
    root = playdisk.ROOT
    work = root / 'build/validation-v15'
    work.mkdir(parents=True, exist_ok=True)
    disk = playdisk.build(playdisk.PLAY, playdisk.OUT)
    layout = (playdisk.PLAY / 'gen/lgame.inc').read_text()
    symbols = {n: int(v, 16) for n, v in
               re.findall(r'^(G_\w+)\s*=\s*\$([0-9A-Fa-f]+)', layout,
                          re.MULTILINE)}
    report = {'disk_sha256': hashlib.sha256(playdisk.OUT.read_bytes()).hexdigest(),
              'profile': 'f122-nod2', 'runs': {}}
    for name, events in SCENARIOS.items():
        out = work / name
        out.mkdir(exist_ok=True)
        (out / 'scenario.events').write_text(events)
        run = playdisk.run(disk, events, out, profile='f122-nod2', seconds=65,
                           blockdev=playdisk.OUT, blockdev_ro=True)
        assert run.state['end'] == 'stop', run.state['end']
        assert not run.state['halt'], run.state['halt']
        assert run.ay_writes > 0, 'no Phasor music writes'
        names = ('level', 'moved') if name == 'play' else ('demo', 'later')
        states = []
        for snap in names:
            mem = run.images[snap][(0, 0)]
            def word(symbol):
                a = symbols[symbol]
                return int.from_bytes(mem[a:a + 2], 'little')
            a = symbols['G_GAMETIC']
            state = {'map': word('G_GAMEMAP'),
                     'tic': int.from_bytes(mem[a:a + 4], 'little')}
            assert word('G_GAMESTATE') == 0, 'not in a level'
            assert state['map'] == (1 if name == 'play' else 7), state
            assert mem[symbols['G_DEMOPLAY']] == (name == 'attract')
            assert not mem[symbols['G_MENUACTIVE']], 'menu still open'
            states.append(state)
        assert states[1]['tic'] > states[0]['tic'], 'game tics did not advance'
        assert run.shots[names[0]] != run.shots[names[1]], 'view did not change'
        report['runs'][name] = {'states': states, 'ay_writes': run.ay_writes,
                                'end': run.state['end']}
        print('PASS:', name, states)
    (work / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: disk boot, menus, E1M1 movement, E1M7 demo and Phasor output')


if __name__ == '__main__':
    main()
