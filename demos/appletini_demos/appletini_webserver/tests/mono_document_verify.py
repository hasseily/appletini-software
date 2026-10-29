#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute document storage and real bank-transfer code on NMOS6502.

The model exposes either six distinct AUX banks or four banks with selector
aliasing. It checks the probe restores every byte before the first append.
"""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_mono import run,tool,data_fork
from mono_verify import Runner


def main():
    out=ROOT/'build'/'mono-document-test'
    out.mkdir(parents=True,exist_ok=True)
    config=(ROOT/'mono-system.cfg').read_text()
    for name in ('MONO.WEB','MONO.GIF','MONO.PNG','MONO.JPG'):
        config=config.replace('@'+name+'@',(out/name).as_posix())
    (out/'mono-system.cfg').write_text(config)
    run([tool('cl65'),'-t','apple2','--cpu','6502','-Os','--warnings-as-errors',
         '-I',str(ROOT),'-C',str(out/'mono-system.cfg'),
         '-o',str(out/'A2MONO.payload.as'),'-m',str(out/'A2MONO.map'),
         '-Ln',str(out/'A2MONO.lbl'),'tests/mono_document_target.c',
         'mono_document.c','mono_gfx.c','mono_gfx.s'])
    payload,address=data_fork((out/'A2MONO.payload.as').read_bytes())
    assert address==0x6000
    (out/'A2MONO.payload.bin').write_bytes(payload)
    (out/'loader.cfg').write_text('MEMORY { MAIN:start=$2000,size=$9F00,file=%O; }\n'
                                'SEGMENTS { CODE:load=MAIN,type=rw; }\n')
    run([tool('ca65'),'-D',f'PAYLOAD_SIZE={len(payload)}','--bin-include-dir',str(out),
         '-o',str(out/'loader.o'),'mono_loader.s'])
    run([tool('ld65'),'-C',str(out/'loader.cfg'),'-o',str(out/'A2MONO.bin'),str(out/'loader.o')])
    reports=[]
    for banks,capacity in ((6,65535),(4,8192)):
        runner=Runner(out,'https://fixture.test/page',97)
        runner.capture_at={};runner.input=[]
        overlay=runner.symbols['__BROWSER_RUN__']
        data=(out/'MONO.WEB').read_bytes()
        runner.memory.main[overlay:overlay+len(data)]=data
        runner.memory.aux=[bytearray((at*3+(at>>8)+bank*17)&255
                                    for at in range(65536)) for bank in range(banks)]
        before=[bytes(bank) for bank in runner.memory.aux]
        probed=[False]
        original_step=runner.cpu.step
        def step():
            if not probed[0] and runner.cpu.pc==runner.symbols['_mono_document_reset']:
                assert [bytes(bank) for bank in runner.memory.aux]==before,'bank probe damaged aliased RAM'
                probed[0]=True
            return original_step()
        runner.cpu.step=step
        runner.run(40_000_000)
        assert probed[0],'probe restoration was not observed'
        value=lambda name:runner.memory.main[runner.symbols['_mono_document_'+name]]
        word=lambda name:value(name)|(runner.memory.main[runner.symbols['_mono_document_'+name]+1]<<8)
        assert value('failed')==0,(banks,value('failed'))
        assert value('checks')==5
        assert word('observed_capacity')==capacity and word('length')==capacity
        assert not runner.memory.ramrd and not runner.memory.ramwrt and runner.memory.bank==0
        golden=bytes((at^(at>>8)^0x5A)&255 for at in range(capacity-1))+b'K'
        if banks==6:
            actual=bytes(runner.memory.aux[4][0x2000:0xC000])+bytes(runner.memory.aux[5][0x2000:0x7FFF])
            assert actual==golden,'bank-4/bank-5 document content mismatch'
            for bank in range(4):assert bytes(runner.memory.aux[bank])==before[bank]
            assert bytes(runner.memory.aux[4][:0x2000])==before[4][:0x2000]
            assert bytes(runner.memory.aux[4][0xC000:])==before[4][0xC000:]
            assert bytes(runner.memory.aux[5][0x7FFF:])==before[5][0x7FFF:]
        else:
            assert bytes(runner.memory.aux[0][0xA000:0xC000])==golden
            assert bytes(runner.memory.aux[0][:0xA000])==before[0][:0xA000]
            for bank in range(1,4):assert bytes(runner.memory.aux[bank])==before[bank]
        reports.append({'physical_aux_banks':banks,'capacity':capacity,
                        'checks':value('checks'),'instructions':runner.steps,
                        'cycles':runner.cpu.processorCycles,
                        'content_sha256':hashlib.sha256(golden).hexdigest()})
    report={'model':'py65 NMOS6502 + real MAIN/AUX/LC transfer code',
            'board_evidence':False,'cases':reports,'browser_bytes':len(data)}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
