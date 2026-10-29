#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reproduce persistent descriptor faults in the actual compiled 6502 browser.

Faults are injected at the FIFO boundary; this does not reproduce a board or
TLS-service fault. It distinguishes a poisoned transport from clean generation
desynchronization and records diagnostics before CANCEL clears ti_net_rc.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from mono_verify import ROOT, Memory
from mono_integration import warm
from mono_github import body_text

FIRST = b'ghttps://fixture.test/fault\r'
KEYS = FIRST + b'ghttps://fixture.test/later\rq'


class FaultMemory(Memory):
    def __getitem__(self, address):
        if address == 0xCFF1 and self.delay:
            self.guard_fifo()
            return 0
        return super().__getitem__(address)

    def submit(self, packet):
        fault = (packet[0] == 0 and packet[5] == 0x82 and
                 self.requests and not self.faulted)
        if fault and self.mode == 'generation':
            # Model an ARM session reset followed by generation one. The
            # live failure had an old client generation and server value 1.
            self.generation = 1
        super().submit(packet)
        if fault:
            self.faulted = True
            if self.mode == 'timeout':
                self.delay = True
            elif self.mode == 'oversize':
                self.response[1:3] = [65, 0]  # Descriptor destination holds 64.


def run_case(base, mode, legacy=False):
    target = deepcopy(base)
    target.memory.__class__ = FaultMemory
    target.memory.mode = mode
    target.memory.faulted = target.memory.delay = False
    target.memory.fixtures = {
        'https://fixture.test/fault': ('text/html', b'<p>FIRST OK</p>'),
        'https://fixture.test/later': ('text/html', b'<p>LATER OK</p>')}
    keys = KEYS if mode != 'normal' else FIRST + KEYS[:-1] + b'ghttps://fixture.test/later\rq'
    target.input = list(keys)
    target.keyboard_calls = 0
    target.captures = []
    target.capture_at = {}
    snapshots, polls, cancellations = [], [], []
    pending_return = None

    def hook(run):
        nonlocal pending_return
        pc, main, symbols = run.cpu.pc, run.memory.main, run.symbols
        # NET and WEB share addresses; a symbol match alone is insufficient.
        net_active=legacy or 'MONO.NET' not in run.files or bytes(main[0x8B00:0x8B10])==run.files['MONO.NET'][:16]
        if pc == symbols['_ti_net_poll'] and net_active:
            sp = run.cpu.sp
            pending_return = ((main[0x100 + ((sp + 1) & 255)] |
                               main[0x100 + ((sp + 2) & 255)] << 8) + 1) & 65535
        elif pc == pending_return:
            polls.append({'ti_error': run.cpu.a,
                          'raw_rc': main[symbols['_ti_net_rc']],
                          'poisoned': main[symbols['_ti_net_poisoned']]})
            pending_return = None
        if pc == symbols['_ti_net_cancel'] and net_active:
            cancellations.append({'raw_rc': main[symbols['_ti_net_rc']],
                                  'poisoned': main[symbols['_ti_net_poisoned']]})
        if pc == symbols['_cgetc'] and run.keyboard_calls in (len(FIRST), len(keys)-1):
            snapshots.append({'at': run.keyboard_calls, 'text': (body_text(run)+'\n'+body_text(run,47,48)).strip(),
                              'poisoned': main[symbols['_ti_net_poisoned']],
                              'raw_rc_after_cancel': main[symbols['_ti_net_rc']],
                              'saved_api_error': main[symbols['_mono_http_transport_error']]
                                  if '_mono_http_transport_error' in symbols else None,
                              'saved_card_error': main[symbols['_mono_http_card_error']]
                                  if '_mono_http_card_error' in symbols else None})
            # The modeled ARM is healthy again before the next user request.
            run.memory.delay = False
        return False

    target.ui_hook = hook
    target.run(target.steps + 45_000_000)
    assert len(snapshots) == 2, snapshots
    if mode == 'normal':
        assert 'FIRST OK' in snapshots[0]['text'] and 'LATER OK' in snapshots[1]['text'], snapshots
        assert len(target.memory.requests) == 4 and not snapshots[1]['poisoned']
        assert all(p['ti_error'] == 0 for p in polls), polls
        assert target.memory.controls == [1, 2]*4
    elif mode == 'generation':
        assert ('HTTP DESCRIPTOR FAILED' if legacy else 'HTTP DESCRIPTOR E5') in snapshots[0]['text'], snapshots
        assert ('HTTP DESCRIPTOR FAILED' if legacy else 'LATER OK') in snapshots[1]['text'], snapshots
        assert not snapshots[1]['poisoned']
        assert len(target.memory.requests) == 2
        assert [p['ti_error'] for p in polls if p['ti_error']] == ([5, 5] if legacy else [5]), polls
        assert target.memory.controls == [1, 2, 1, 2]
        if not legacy:
            assert snapshots[0]['saved_api_error'] == 5 and snapshots[0]['saved_card_error'] == 0
            assert snapshots[1]['saved_api_error'] == 0 and snapshots[1]['saved_card_error'] == 0
    else:
        assert ('HTTP DESCRIPTOR FAILED' if legacy else 'HTTP DESCRIPTOR E9') in snapshots[0]['text'], snapshots
        assert ('CANNOT START HTTP/S' if legacy else 'HTTP FAULT: RESTART BROWSER') in snapshots[1]['text'], snapshots
        assert snapshots[1]['poisoned'] == 1
        assert len(target.memory.requests) == 1
        assert polls == [{'ti_error': 9, 'raw_rc': 0x67, 'poisoned': 1}], polls
        assert target.memory.controls == [1]  # No CANCEL or new START replay.
        if not legacy:
            assert snapshots[0]['saved_api_error'] == 9 and snapshots[0]['saved_card_error'] == 0x67
            assert snapshots[1]['saved_api_error'] == 9
    assert all(s['raw_rc_after_cancel'] == 0 for s in snapshots), snapshots
    return {'case': mode, 'requests': target.memory.requests,
            'controls': target.memory.controls, 'poll_returns': polls,
            'before_cancel': cancellations, 'snapshots': snapshots,
            'instructions': target.steps-base.steps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT/'build/mono-sessionfix')
    parser.add_argument('--expect-legacy', action='store_true',
                        help='prove the persistent failure on the previous binary')
    args = parser.parse_args()
    out = args.build.resolve()
    base = warm(out)
    cases = []
    for mode in ('timeout', 'oversize', 'generation', 'normal'):
        result = run_case(base, mode, args.expect_legacy)
        cases.append(result)
        print(json.dumps(result), flush=True)
    report = {'board_evidence': False, 'actual_6502': True,
              'program_sha256': hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
              'cases': cases}
    (out/'descriptor-investigation.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PASS descriptor fault safety, generation session handling, repeated pages')


if __name__ == '__main__':
    main()
