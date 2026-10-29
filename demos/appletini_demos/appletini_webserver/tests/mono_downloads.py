#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the actual 6502 browser/NET overlay against download descriptors.

The firmware file manager has separate native tests. This models its agreed
64-byte ABI, including cleanup after cancellation and transfers above 64KiB.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from mono_verify import ROOT, Memory, framebuffer, fixture_gif
from mono_integration import warm
from mono_github import body_text

PAGE = 'https://fixture.test/page'
HTML = (b'<h1>DOWNLOAD SOURCE PAGE</h1>'
        b'<p><a href="/force.txt" download="chosen.txt">Named file</a></p>'
        b'<p><a DOWNLOAD href="/boolean.bin">Boolean file</a></p>'
        b'<p><a href="/auto.bin">Automatic attachment</a></p>'
        b'<p><a href="/fail.bin" download>Fail file</a></p>'
        b'<p><a href="/cancel.bin" download="cancel.dat">Cancel file</a></p>'
        b'<p><a href="/normal.txt">Plain document</a></p>'
        b'<p><a href="/poison.bin" download>Poison file</a></p>'
        b'<p><a href="/long.bin" download="'+b'a'*128+b'">Long filename</a></p>'
        b'<img src="/inline.gif"><p>END OF SOURCE PAGE</p>')
FILE_BYTES = 300000
FILE_PATH = b'0:/downloads/result.bin'


class DownloadMemory(Memory):
    def __getitem__(self, address):
        if address == 0xCFF1 and self.delay:
            self.guard_fifo()
            return 0
        return super().__getitem__(address)

    def submit(self, packet):
        if packet[0] == 4:
            payload = packet[12:]
            op = payload[1]
            if op == 1:
                m = payload[3]
                u = int.from_bytes(payload[4:6], 'little')
                h = int.from_bytes(payload[6:8], 'little')
                b = int.from_bytes(payload[8:10], 'little')
                d = int.from_bytes(payload[10:12], 'little')
                hint = payload[12+m+u+h+b:]
                assert len(hint) == d
                url = payload[12+m:12+m+u].decode()
                flags = payload[2]
                self.records.append({'url': url, 'flags': flags, 'hint': hint.decode()})
                self.file_active = bool(flags & 4 or flags & 2 and url.endswith('/auto.bin'))
                self.phase = self.file_polls = 0
                self.cancel_requested = False
                self.file_url = url
            elif self.file_active:
                assert op == 2
                self.events.append('cancel')
                if self.case == 'cancel':
                    self.cancel_requested = True
                    self.cleanup_polls = 0
                else:
                    self.file_active = False
            super().submit(packet)
            if op == 2 and self.case == 'cleanup-poison':
                self.delay = True
            return
        source = packet[5]
        if source == 0x82 and self.file_active:
            self.file_polls += 1
            state, net_state, written, error = 2, 2, min(FILE_BYTES, self.phase*100000), 0
            if self.case in ('tls-untrusted','tls-generic','dns-failed'):
                state, net_state, written, error = 4, 4, 0, -106 if self.case=='dns-failed' else -9984
            elif self.cancel_requested:
                self.cleanup_polls += 1
                if self.cleanup_polls >= 3:
                    state, net_state = 5, 5
            elif self.case == 'failure' and self.phase >= 2:
                state, net_state, error = 4, 4, -12
            elif self.phase == 0:
                state = 1
            elif self.phase >= 4:
                state, net_state, written = 3, 3, FILE_BYTES
            reply = bytearray(64)
            reply[:10] = b'ATNH' + bytes((1, 64, 31, self.generation, net_state, 0))
            reply[12:14] = (200).to_bytes(2, 'little')
            if self.case in ('tls-untrusted','tls-generic','dns-failed'):
                reply[10:14]=error.to_bytes(2,'little',signed=True)+b'\0\0'
                reply[40:44]=(0x4008 if self.case=='tls-untrusted' else 0).to_bytes(4,'little')
            reply[16:20] = FILE_BYTES.to_bytes(4, 'little')
            reply[48:50] = bytes((state, 1))
            reply[50:52] = error.to_bytes(2, 'little', signed=True)
            reply[52:56] = written.to_bytes(4, 'little')
            reply[56:60] = FILE_BYTES.to_bytes(4, 'little')
            reply[60:62] = len(FILE_PATH).to_bytes(2, 'little')
            self.answer(reply)
            if self.case == 'poison' and self.phase == 1:
                self.delay = True
            self.phase += 1
            if state == 5:
                self.file_active = False
            return
        if source == 0x83 and self.file_active:
            raise AssertionError('download body was read into the 64KiB page/image sink')
        if source == 0x87:
            assert self.phase >= 5 and not self.cancel_requested
            self.events.append('path')
            offset = int.from_bytes(packet[6:8], 'little')
            data = FILE_PATH[offset:offset+97]
            self.answer(bytes((self.generation, 2)) + offset.to_bytes(4, 'little') +
                        len(data).to_bytes(2, 'little') + data)
            return
        super().submit(packet)
        if source == 0x82 and self.case == 'old-firmware':
            self.response[3+6] = 15


def loaded(out):
    run = warm(out)
    run.memory.__class__ = DownloadMemory
    m = run.memory
    m.case = 'normal'
    m.delay = m.file_active = m.cancel_requested = False
    m.records, m.events = [], []
    m.phase = m.file_polls = m.cleanup_polls = 0
    m.fixtures = {PAGE: ('text/html', HTML),
                  'https://fixture.test/normal.txt': ('text/plain', b'PLAIN DOCUMENT'),
                  'https://fixture.test/inline.gif': ('image/gif', fixture_gif(32,24))}
    for name in ('force.txt','boolean.bin','auto.bin','fail.bin','cancel.bin','poison.bin','long.bin'):
        m.fixtures['https://fixture.test/'+name] = ('application/octet-stream', b'FILE DATA')
    run.input = list(('g'+PAGE+'\r').encode())
    run.capture_at = {};run.keyboard_calls = 0
    try:
        run.run(run.steps+30_000_000)
    except AssertionError as error:
        assert str(error) == 'browser requested unexpected extra input', error
    else:
        raise AssertionError('page did not reach keyboard idle')
    assert m.records == [{'url': PAGE, 'flags': 2, 'hint': ''}], m.records
    assert bytes(m.aux[4][0x2000:0x2000+len(HTML)]) == HTML
    assert 'DOWNLOAD SOURCE PAGE' in body_text(run)
    return run


def case(base, name, link=None):
    run = deepcopy(base)
    run.memory.case = name
    run.keyboard_calls = 0;run.capture_at = {};run.captures = []
    run.escape_pending = run.escape_sent = False
    tabs = link or 0
    keys = b'i' if name == 'image' else b'\t'*tabs + b'\r'
    after = len(keys)
    if name == 'poison':
        keys += b'ghttps://fixture.test/normal.txt\r'
    run.input = list(keys+b'q')
    before = before_web = None
    snapshots = []
    poison_mli = None

    def hook(target):
        nonlocal before, before_web, poison_mli
        pc = target.cpu.pc
        poisoned = target.memory.main[target.symbols['_ti_net_poisoned']]
        if poisoned and poison_mli is None:
            poison_mli = len(target.mli_calls)
        if name == 'cancel' and target.memory.file_active:
            if pc == target.symbols['_kbhit'] and target.memory.file_polls >= 2 and not target.escape_sent:
                target.escape_pending = True
                target.cpu.a,target.cpu.x = 1,0;target.rts();return True
            if pc == target.symbols['_cgetc'] and target.escape_pending:
                target.escape_pending = False;target.escape_sent = True
                target.cpu.a,target.cpu.x = 27,0;target.rts();return True
        if pc == target.symbols['_cgetc']:
            if target.keyboard_calls == tabs and name != 'image':
                before = framebuffer(target.memory)[560:44*8*70]
                before_web = bytes(target.memory.main[0x8B00:0xB700])
            if target.keyboard_calls in (after, len(keys)):
                target.memory.delay = False
                snapshot = {'at':target.keyboard_calls,
                            'status':body_text(target,47,48).strip(),
                            'body':body_text(target).strip(),
                            'saved_card_error':target.memory.main[target.symbols['_mono_http_card_error']],
                            'document_length':int.from_bytes(target.memory.main[
                                target.symbols['_mono_document_length']:
                                target.symbols['_mono_document_length']+2],'little')}
                if name not in ('plain','image'):
                    assert framebuffer(target.memory)[560:44*8*70] == before, name
                    assert bytes(target.memory.main[0x8B00:0xB700]) == before_web, name
                    assert bytes(target.memory.aux[4][0x2000:0x2000+len(HTML)]) == HTML
                    assert snapshot['document_length'] == len(HTML)
                snapshots.append(snapshot)
        return False

    run.ui_hook = hook
    first = run.steps
    run.run(first+45_000_000)
    assert snapshots, name
    requests = run.memory.records
    expected = {'named':(4,'chosen.txt'),'boolean':(4,''),'automatic':(2,''),
                'failure':(4,''),'cancel':(4,'cancel.dat'),'poison':(4,''),
                'plain':(2,''),'image':(0,''),'long-name':(4,'a'*127),
                'tls-untrusted':(2,''),'tls-generic':(2,''),'dns-failed':(2,'')}
    if name == 'old-firmware':
        assert len(requests) == 1
        assert 'UPDATED FIRMWARE' in snapshots[-1]['status']
    else:
        flags,hint = expected[name]
        assert len(requests) == 2, requests
        assert (requests[-1]['flags'],requests[-1]['hint']) == (flags,hint), requests
    if name in ('named','boolean','automatic','long-name'):
        assert snapshots[-1]['status'].startswith('SAVED 0:/DOWNLOADS/RESULT'), snapshots
        at=run.symbols['_mono_http_message']
        assert bytes(run.memory.main[at:at+6+len(FILE_PATH)+1]) == b'Saved '+FILE_PATH+b'\0'
        assert run.memory.events == ['path','cancel'], run.memory.events
        assert run.memory.file_polls >= 5
    if name == 'failure':
        assert 'DOWNLOAD FAILED' in snapshots[-1]['status']
    if name in ('tls-untrusted','tls-generic','dns-failed'):
        expected_status={'tls-untrusted':'TLS ISSUER UNTRUSTED; UPDATE CA BUNDLE',
                         'tls-generic':'TLS CERTIFICATE VERIFICATION FAILED',
                         'dns-failed':'DNS LOOKUP FAILED'}[name]
        assert snapshots[-1]['status']==expected_status,snapshots
        assert run.memory.events==['cancel'],run.memory.events
    if name == 'cancel':
        assert run.escape_sent and run.memory.cleanup_polls == 3
        assert 'DOWNLOAD CANCELLED' in snapshots[-1]['status']
    if name == 'plain':
        assert 'PLAIN DOCUMENT' in snapshots[-1]['body']
    if name == 'image':
        assert requests[-1]['url'].endswith('/inline.gif')
    if name == 'poison':
        assert poison_mli is not None
        assert snapshots[0]['saved_card_error']==0x67,snapshots
        assert not any(op in (0xC8,0xCA,0xCC) for op in run.mli_calls[poison_mli:]), run.mli_calls[poison_mli:]
        assert 'RESTART BROWSER' in snapshots[-1]['status']
        assert run.memory.main[0x8B00:0x8B00+len(run.files['MONO.WEB'])] == run.files['MONO.WEB']
    return {'case':name,'instructions':run.steps-first,'requests':requests,
            'events':run.memory.events,'snapshots':snapshots,
            'overlay_io_after_poison':run.mli_calls[poison_mli:] if poison_mli is not None else None}


def cleanup_poison(base):
    """A timed-out final CANCEL blocks remote codecs; home I has no image."""
    run=deepcopy(base)
    run.memory.case='cleanup-poison';run.input=list(b'ihiq')
    run.keyboard_calls=0;run.capture_at={};run.captures=[]
    first=run.steps;poison_mli=None;snapshots=[]
    def hook(target):
        nonlocal poison_mli
        if target.memory.main[target.symbols['_ti_net_poisoned']] and poison_mli is None:
            poison_mli=len(target.mli_calls)
        if target.cpu.pc==target.symbols['_cgetc'] and target.keyboard_calls in (1,3):
            if target.keyboard_calls==1:
                assert target.memory.main[target.symbols['_mono_http_card_error']]==0x67
            snapshots.append(body_text(target,47,48).strip())
            target.memory.delay=False
        return False
    run.ui_hook=hook;run.run(first+45_000_000)
    assert poison_mli is not None
    assert snapshots[0]=='HTTP DESCRIPTOR E9',snapshots
    assert snapshots[-1]=='HTTPS OK',snapshots
    assert not any(op in (0xC8,0xCA,0xCC) for op in run.mli_calls[poison_mli:])
    assert [item['url'] for item in run.memory.records]==[PAGE,'https://fixture.test/inline.gif']
    return {'case':'cleanup-poison-then-text-home','instructions':run.steps-first,
            'statuses':snapshots,'overlay_io_after_poison':run.mli_calls[poison_mli:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build/mono-download')
    args = parser.parse_args();out=args.build.resolve()
    base = loaded(out)
    reports = []
    for name,link in (('named',0),('boolean',1),('automatic',2),('failure',3),
                      ('cancel',4),('plain',5),('poison',6),('image',None),('old-firmware',0),('long-name',7),
                      ('tls-untrusted',2),('tls-generic',2),('dns-failed',2)):
        result = case(base,name,link)
        reports.append(result)
        print(json.dumps(result),flush=True)
    reports.append(cleanup_poison(base))
    report = {'actual_6502':True,'mocked_download_manager':True,'board_evidence':False,
              'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
              'transfer_bytes':FILE_BYTES,'cases':reports}
    (out/'download-browser.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS browser download flags, >64KiB transfer, page retention, ESC cleanup, image isolation and poison-safe RAM restore')


if __name__ == '__main__':
    main()
