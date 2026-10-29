#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the real baseline JPEG decoder on NMOS6502, with real JPEG fixtures."""
from io import BytesIO
import json
from pathlib import Path
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_mono import run,tool,data_fork
from mono_verify import Runner,framebuffer


def main():
    from PIL import Image
    out = ROOT/'build'/'mono-jpeg-test'
    out.mkdir(parents=True,exist_ok=True)
    image = Image.new('RGB',(23,19))
    image.putdata([(0,0,0) if x<7 else (255,255,255) if x>15 else
                   (x*10,y*11,(x+y)*5) for y in range(19) for x in range(23)])
    fixtures = {}
    for name,mode,sampling,progressive in (
        ('gray','L',0,False),('rgb','RGB',0,False),
        ('subsampled','RGB',2,False),('progressive','RGB',2,True),
        ('vertical','RGB',1,False)):
        stream=BytesIO()
        image.convert(mode).save(stream,'JPEG',quality=90,subsampling=sampling,
                                 progressive=progressive)
        fixtures[name]=stream.getvalue()
        (out/(name+'.jpg')).write_bytes(stream.getvalue())
    bad=bytearray(fixtures['gray'])
    dht=bad.index(b'\xff\xc4')
    bad[dht+5:dht+21]=bytes([3]+[0]*15)
    fixtures['badtable']=bytes(bad)
    header=[]
    for name,data in fixtures.items():
        header.append('static const unsigned char jpeg_'+name+'[] = {'+
                      ','.join(str(x) for x in data)+'};')
    (out/'jpeg_fixtures.h').write_text('\n'.join(header)+'\n')
    config=(ROOT/'mono-system.cfg').read_text()
    for name in ('MONO.WEB','MONO.GIF','MONO.PNG','MONO.JPG'):
        config=config.replace('@'+name+'@',(out/name).as_posix())
    config=config.replace('BROWSER: load = WEBMEM, type = ro, define = yes;',
                          'BROWSER: load = WEBMEM, type = ro, define = yes, optional = yes;')
    # The codec fixture has no resident browser; reserve enough overlay room
    # independently of the production resident/overlay split.
    config=re.sub(r'(JPGMEM:[^\n]*start = )\$[0-9A-F]+, size = \$[0-9A-F]+',
                  r'\g<1>$8B00, size = $2C00',config)
    (out/'mono-system.cfg').write_text(config)
    run([tool('cl65'),'-t','apple2','--cpu','6502','-Os','--warnings-as-errors',
         '-I',str(ROOT),'-I',str(out),'-C',str(out/'mono-system.cfg'),
         '-o',str(out/'A2MONO.payload.as'),'-m',str(out/'A2MONO.map'),
         '-Ln',str(out/'A2MONO.lbl'),'tests/mono_jpeg_target.c',
         'mono_gfx.c','mono_gfx.s','mono_jpeg.c','third_party/picojpeg/picojpeg.c'])
    payload,address=data_fork((out/'A2MONO.payload.as').read_bytes())
    assert address==0x6000
    (out/'A2MONO.payload.bin').write_bytes(payload)
    (out/'loader.cfg').write_text('MEMORY { MAIN:start=$2000,size=$9F00,file=%O; }\n'
                                'SEGMENTS { CODE:load=MAIN,type=rw; }\n')
    run([tool('ca65'),'-D',f'PAYLOAD_SIZE={len(payload)}','--bin-include-dir',str(out),
         '-o',str(out/'loader.o'),'mono_loader.s'])
    run([tool('ld65'),'-C',str(out/'loader.cfg'),'-o',str(out/'A2MONO.bin'),str(out/'loader.o')])
    runner=Runner(out,'https://fixture.test/page',97)
    overlay=runner.symbols.get('__JPEG_RUN__',0x8000)
    data=(out/'MONO.JPG').read_bytes()
    runner.memory.main[overlay:overlay+len(data)]=data
    runner.input=[ord('q')]
    runner.run(30_000_000)
    at=runner.symbols['_mono_jpeg_results']
    results=list(runner.memory.main[at:at+10])
    assert results==[1,1,1,1,0,0,1,1,1,0],results
    pixels=framebuffer(runner.memory)
    def white(x,y): return bool(pixels[y*70+x//8]&(0x80>>(x&7)))
    for left in (10,60,110,300):
        assert not white(left+2,14),('dark JPEG region',left)
        assert white(left+20,14),('white JPEG region',left)
    assert white(352,10),'pixel clip overwrote toolbar'
    assert not white(352,17),'clipped JPEG body did not draw'
    assert not white(402,0),'negative JPEG y did not clip to screen'
    report={'model':'py65 NMOS6502 + MAIN/AUX/LC model','board_evidence':False,
            'results':results,'instructions':runner.steps,
            'cycles':runner.cpu.processorCycles,'jpeg_overlay_bytes':len(data),
            'capture':'https.png'}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
