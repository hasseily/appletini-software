#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the welcome page, its links and image-free I key on actual 6502 code."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from mono_verify import ROOT,save_capture
from mono_integration import warm
from mono_github import body_text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build/mono')
    args=parser.parse_args();out=args.build.resolve()
    base=warm(out)
    text=body_text(base).strip()
    for wanted in ('A2MONO','THE WEB, THROUGH AN APPLE II','GRAPHICAL HTTPS BROWSER',
                   '560X384','DHGRI','PRESS G','VISIT APPLETINI','TRY EXAMPLE',
                   'GIF, PNG AND BASELINE JPEG','SD CARD','MOUSE IS OPTIONAL'):
        assert wanted in text,(wanted,text)
    assert '[IMAGE' not in text
    assert len(text.splitlines())<=30,text
    assert not base.memory.requests
    save_capture(out/'welcome.png',base.memory)
    (out/'welcome.txt').write_text(text+'\n')
    length_at=base.symbols['_mono_document_length']
    length=int.from_bytes(base.memory.main[length_at:length_at+2],'little')
    document=bytes(base.memory.aux[4][0x2000:0x2000+length])
    assert b'<img' not in document.lower()
    cases=[]
    for name,keys,url in (('home-I',b'i',None),
                          ('appletini-link',b'\r','https://appletini.org/'),
                          ('example-link',b'\t\r','https://example.com/')):
        run=deepcopy(base);run.input=list(keys+b'q')
        run.keyboard_calls=0;run.capture_at={};run.captures=[]
        if url:run.memory.fixtures[url]=('text/html',b'<h1>WELCOME LINK WORKED</h1>')
        first=run.steps;before=len(run.mli_calls);after=[]
        def hook(target):
            if target.cpu.pc==target.symbols['_cgetc'] and target.keyboard_calls==len(keys):
                after.append(body_text(target).strip())
            return False
        run.ui_hook=hook;run.run(first+25_000_000)
        assert len(after)==1,(name,after)
        if url:
            assert run.memory.requests==[url],run.memory.requests
            assert 'WELCOME LINK WORKED' in after[0]
        else:
            assert run.memory.requests==[]
            assert after[0]==text
            assert not any(op in (0xC8,0xCA,0xCC) for op in run.mli_calls[before:])
        cases.append({'case':name,'instructions':run.steps-first,
                      'requests':run.memory.requests,'mli_calls':run.mli_calls[before:]})
    report={'actual_6502':True,'mocked_prodos_and_http':True,'board_evidence':False,
            'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
            'visible_rows':len(text.splitlines()),'text':text,'cases':cases}
    (out/'welcome-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS text-only welcome, one-page rendering, HTTPS links and no image I/O on I')


if __name__=='__main__':main()
