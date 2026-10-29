#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile and execute the real DHGRi backend, AUX helpers and SYS loader."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_mono import run,tool,data_fork
from mono_verify import Runner,framebuffer


def main():
    out=ROOT/'build'/'mono-gfx-test'
    out.mkdir(parents=True,exist_ok=True)
    config=(ROOT/'mono-system.cfg').read_text()
    for name in ('MONO.WEB','MONO.GIF','MONO.PNG','MONO.JPG'):
        config=config.replace('@'+name+'@',(out/name).as_posix())
    config=config.replace('BROWSER: load = WEBMEM, type = ro, define = yes;',
                          'BROWSER: load = WEBMEM, type = ro, define = yes, optional = yes;')
    (out/'mono-system.cfg').write_text(config)
    run([tool('cl65'),'-t','apple2','--cpu','6502','-Os','--warnings-as-errors',
         '-I',str(ROOT),'-C',str(out/'mono-system.cfg'),'-o',str(out/'A2MONO.payload.as'),
         '-m',str(out/'A2MONO.map'),'-Ln',str(out/'A2MONO.lbl'),
         'tests/mono_gfx_target.c','mono_gfx.c','mono_gfx.s'])
    payload,address=data_fork((out/'A2MONO.payload.as').read_bytes())
    assert address==0x6000
    (out/'A2MONO.payload.bin').write_bytes(payload)
    (out/'loader.cfg').write_text('MEMORY { MAIN: start=$2000, size=$9F00, file=%O; }\n'
                                'SEGMENTS { CODE: load=MAIN, type=rw; }\n')
    run([tool('ca65'),'-D',f'PAYLOAD_SIZE={len(payload)}','--bin-include-dir',str(out),'-o',str(out/'loader.o'),'mono_loader.s'])
    run([tool('ld65'),'-C',str(out/'loader.cfg'),'-o',str(out/'A2MONO.bin'),str(out/'loader.o')])
    target=Runner(out,'https://fixture.test/page',97)
    target.input=[ord('q')]
    target.capture_at={0:'https'}
    target.run(8_000_000)
    symbols=target.symbols
    assert target.memory.main[symbols['_mono_fixture_failed']]==0,'AUX bank helper mismatch'
    assert target.memory.main[symbols['_mono_fixture_checks']]==3
    assert target.memory.bank==0 and not target.memory.ramrd and not target.memory.ramwrt
    assert target.memory.text and not target.memory.hires and target.memory.main[0x407C]==0
    pixels=framebuffer(target.memory)
    for x,y in ((0,0),(559,0),(0,383),(559,383)):
        assert not (pixels[y*70+x//8]&(0x80>>(x&7))),('corner pixel',x,y)
    row=22
    address=0x4000+(row&7)*1024+((row>>3)&7)*128+(row>>6)*40
    assert target.memory.main[address]==0x55
    assert target.memory.aux[0][address+1]==0x2A
    assert target.memory.main[address+1]==0x33
    assert target.memory.aux[0][address+2]==0x4C
    report={'model':'py65 NMOS6502, MAIN/AUX/LC switch model','board_evidence':False,
            'checks':3,'instructions':target.steps,'cycles':target.cpu.processorCycles,
            'capture':'https.png','screen_sha256':target.captures[0]['sha256']}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
