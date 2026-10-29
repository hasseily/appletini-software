#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Full browser/HTTP/overlay/image/navigation and overlay fault integration."""
from copy import deepcopy
from io import BytesIO
import argparse
import hashlib
import json
from pathlib import Path
from mono_verify import ROOT, Runner, fixture_gif, save_capture


def old_open_policy(out):
    """The actual loader must receive $56 for the former $0400 buffer."""
    target=Runner(out,'https://fixture.test/start',17)
    payload=(out/'A2MONO.payload.bin').read_bytes()
    entry=target.symbols['_mono_overlay_load']
    at=payload.index(bytes((0x20,0,0xBF,0xC8)),entry-0x6000)
    after=0x6000+at+6
    params=int.from_bytes(payload[at+4:at+6],'little')
    class OpenObserved(Exception):pass
    def hook(run):
        if run.cpu.pc==entry:
            run.memory.main[params+3:params+5]=b'\0\x04'
        if run.cpu.pc==after:
            assert run.cpu.a==0x56 and run.cpu.p&1
            assert not run.opened
            raise OpenObserved
        return False
    target.ui_hook=hook
    try:target.run(2_000_000)
    except OpenObserved:return {'old_open_0400_error':'0x56','instructions':target.steps}
    raise AssertionError('former OPEN policy was not rejected')


def fixtures():
    from PIL import Image
    image=Image.new('RGB',(32,24))
    image.putdata([(0,0,0) if x<8 else (255,255,255) if x>23 else
                   (x*8,y*10,(x+y)*4) for y in range(24) for x in range(32)])
    png=BytesIO(); image.save(png,'PNG')
    jpeg=BytesIO(); image.save(jpeg,'JPEG',quality=85,subsampling=2)
    page=(b"<html><title>Native mixed images</title><h1>HTTPS + THREE LOCAL DECODERS</h1>"
          b"<p><a href='next.html'>Next page</a> | <a href='other.html'>Other page</a></p>"
          b"<h2>GIF</h2><img src='checker.gif'>"
          b"<h2>PNG</h2><img src='/images/tile.png'>"
          b"<h2>JPEG</h2><img src='//fixture.test/tile.jpg'>"
          b"<p>All image requests go directly to their origin.</p></html>")
    next_page=b"<h1>Relative link worked</h1><p>Press B to return.</p>"
    return {'https://fixture.test/start':('text/html',page,'https://fixture.test/docs/index.html'),
            'https://fixture.test/docs/index.html':('text/html',page),
            'https://fixture.test/docs/checker.gif':('image/gif',fixture_gif(32,24)),
            'https://fixture.test/images/tile.png':('image/png',png.getvalue()),
            'https://fixture.test/tile.jpg':('image/jpeg',jpeg.getvalue()),
            'https://fixture.test/docs/next.html':('text/html',next_page),
            'https://fixture.test/docs/other.html':('text/html',next_page),
            'https://fixture.test/png':('text/html',b"<h1>PNG failure test</h1><img src='https://fixture.test/images/tile.png'>")}


def warm(out):
    target=Runner(out,'https://fixture.test/start',17)
    target.prefix=b''
    target.input=[]
    try:
        target.run(40_000_000)
    except AssertionError as error:
        assert str(error)=='browser requested unexpected extra input',error
        assert target.cpu.pc==target.symbols['_cgetc']
    else:
        raise AssertionError('browser exited before first keyboard input')
    assert target.prefix==b'/A2MONO'
    assert target.mli_calls[:3]==[0xC7,0xC5,0xC6]
    return target


def execute(base,keys,captures,case):
    target=deepcopy(base)
    target.input=list(keys)
    target.capture_at=captures
    target.keyboard_calls=0
    target.captures=[]
    target.memory.fixtures=fixtures()
    start_steps,start_cycles=target.steps,target.cpu.processorCycles
    target.run(start_steps+80_000_000)
    assert not target.opened,(case,'leaked overlay file')
    assert not target.memory.ramrd and not target.memory.ramwrt and target.memory.bank==0
    assert target.memory.intcxrom and not target.memory.selected
    assert target.io_poison_calls>0,'overlay buffers were not overwritten'
    assert all(url.startswith('https://fixture.test/') for url in target.memory.requests)
    return target,{'case':case,'instructions':target.steps-start_steps,
                   'cycles':target.cpu.processorCycles-start_cycles,
                   'requests':target.memory.requests,'captures':target.captures}


def mouse_cases(base):
    """Exercise C pointer/hit testing; ROM driver has a separate CPU suite."""
    idle=deepcopy(base)
    idle.memory.fixtures=fixtures()
    idle.memory.fixtures['https://fixture.test/mouse']=(
        'text/html',b"<a href='https://fixture.test/clicked'>CLICK HERE</a>")
    idle.memory.fixtures['https://fixture.test/clicked']=(
        'text/html',b"<h1>Mouse followed the link</h1><p>Keyboard Q still exits.</p>")
    idle.input=list(b'ghttps://fixture.test/mouse\r')
    idle.capture_at={};idle.keyboard_calls=0;idle.captures=[]
    try:idle.run(idle.steps+20_000_000)
    except AssertionError as error:
        assert str(error)=='browser requested unexpected extra input',error
    else:raise AssertionError('mouse fixture did not reach keyboard idle')
    results=[]
    for name,x,y in (('mouse-link',2,1),('mouse-footer-quit',32,46)):
        target=deepcopy(idle)
        target.memory.main[target.symbols['_mono_mouse_available']]=1
        target.input=[0,ord('q')] if name=='mouse-link' else [0]
        target.keyboard_calls=0
        target.capture_at={1:name} if name=='mouse-link' else {}
        target.mouse_clicked=False
        def hook(run):
            pc=run.cpu.pc
            if pc==run.symbols['_mono_mouse_poll']:
                assert not run.mouse_clicked,'unexpected repeated mouse poll'
                for field,value in (('_mono_mouse_x',x),('_mono_mouse_y',y),
                                    ('_mono_mouse_down',1),('_mono_mouse_pressed',1)):
                    run.memory.main[run.symbols[field]]=value
                run.mouse_clicked=True
                run.cpu.a,run.cpu.x=3,0;run.rts();return True
            if pc==run.symbols['_kbhit']:
                sp=run.cpu.sp;m=run.memory.main
                ret=m[0x100+((sp+1)&255)]|m[0x100+((sp+2)&255)]<<8
                # WEB and NET now share this code window. A key offered to
                # NET's cancellation poll is consumed before page input.
                web=run.files['MONO.WEB'][:32]
                ui=0x8B00<=ret<0xB700 and bytes(m[0x8B00:0x8B00+len(web)])==web
                ready=run.mouse_clicked and ui and 'https://fixture.test/clicked' in run.memory.requests
                run.cpu.a,run.cpu.x=int(ready),0;run.rts();return True
            if pc==run.symbols['_mono_mouse_disable']:
                if name=='mouse-footer-quit':
                    digest=save_capture(run.out/(name+'.png'),run.memory)
                    run.captures.append({'name':name,'sha256':digest})
                run.memory.main[run.symbols['_mono_mouse_available']]=0
                run.cpu.a,run.cpu.x=0,0;run.rts();return True
            return False
        target.ui_hook=hook
        start_steps,start_cycles=target.steps,target.cpu.processorCycles
        target.run(start_steps+20_000_000)
        assert target.mouse_clicked and not target.opened
        assert ('https://fixture.test/clicked' in target.memory.requests)==(name=='mouse-link')
        assert not target.memory.ramrd and not target.memory.ramwrt and target.memory.bank==0
        results.append({'case':name,'instructions':target.steps-start_steps,
                        'cycles':target.cpu.processorCycles-start_cycles,
                        'requests':target.memory.requests,'captures':target.captures})
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mouse-only',action='store_true')
    parser.add_argument('--build',type=Path,default=ROOT/'build'/'mono')
    args=parser.parse_args()
    out=args.build.resolve()
    policy=old_open_policy(out)
    base=warm(out)
    save_capture(out/'demo.png',base.memory)
    if args.mouse_only:
        result={'model':'actual NMOS6502 browser C mouse policy, synthesized polled events',
                'board_evidence':False,'empty_prefix_initialized':True,
                'strict_mli_policy':policy,'io_buffer_poisoned':True,
                'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
                'startup_instructions':base.steps,'startup_cycles':base.cpu.processorCycles,
                'cases':mouse_cases(base)}
        (out/'mouse-ui.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
        return
    keys=bytearray(b'ghttps://fixture.test/start\r')
    capture={0:'integration-demo'}
    capture[len(keys)]='mixed-top'
    keys.extend(b'i')
    keys.extend(b'\t\rb\rb') # second link, back, first link, back
    capture[len(keys)]='mixed-before-scroll'
    keys.extend(b'i ')
    capture[len(keys)]='mixed-scrolled'
    keys.extend(b'pr')
    capture[len(keys)]='mixed-reloaded'
    keys.extend(b'q')
    target,report=execute(base,keys,capture,'mixed-images-navigation')
    requests=target.memory.requests
    assert 'https://fixture.test/docs/other.html' in requests,requests
    assert 'https://fixture.test/docs/next.html' in requests,requests
    for url in ('https://fixture.test/docs/checker.gif','https://fixture.test/images/tile.png','https://fixture.test/tile.jpg'):
        assert url in requests,(url,requests)
    assert requests.count('https://fixture.test/docs/index.html')>=3,requests
    captures={item['name']:item['sha256'] for item in target.captures}
    assert captures['mixed-top']!=captures['mixed-scrolled']
    assert captures['mixed-top']==captures['mixed-reloaded']
    reports=[report]
    for case in ('missing-png-overlay','short-png-overlay','long-png-overlay'):
        fault=deepcopy(base)
        if case=='missing-png-overlay': fault.files.pop('MONO.PNG')
        elif case=='short-png-overlay': fault.files['MONO.PNG']=fault.files['MONO.PNG'][:-1]
        else: fault.files['MONO.PNG']+=b'\0'
        keys=b'ghttps://fixture.test/png\riq'
        _,report=execute(fault,keys,{len(keys)-1:case},case)
        reports.append(report)
    reports.extend(mouse_cases(base))
    result={'model':'actual NMOS6502 browser; mocked ProDOS and native HTTP FIFO',
            'board_evidence':False,'startup_instructions':base.steps,
            'strict_mli_policy':policy,'io_buffer_poisoned':True,
            'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
            'startup_cycles':base.cpu.processorCycles,'empty_prefix_initialized':True,
            'cases':reports}
    (out/'integration.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
