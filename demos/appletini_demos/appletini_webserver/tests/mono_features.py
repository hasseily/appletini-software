#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reader policy: manual/lazy images, redirect URLs and expanded HTML RAM."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import re

from mono_verify import ROOT, Runner, framebuffer, save_capture, fixture_gif
from mono_integration import old_open_policy


def run(base,keys,captures,name):
    target=deepcopy(base)
    target.input=list(keys);target.keyboard_calls=0;target.capture_at=captures
    target.captures=[]
    target.run(target.steps+100_000_000)
    assert not target.opened and target.memory.bank==0
    assert not target.memory.ramrd and not target.memory.ramwrt
    assert target.memory.intcxrom and not target.memory.selected
    assert target.io_poison_calls>0
    return target,{'case':name,'requests':target.memory.requests,
                   'captures':target.captures,'instructions':target.steps,
                   'cycles':target.cpu.processorCycles}


def white_url_row(target,url):
    pixels=framebuffer(target.memory)
    first=pixels[:8*70]
    assert sum(byte.bit_count() for byte in first)/(560*8)>0.80,'top row has a dark banner'
    for row in (45,46,47):
        footer=pixels[row*8*70:(row+1)*8*70]
        assert sum(byte.bit_count() for byte in footer)/(560*8)>0.60,('footer/status is not mostly white',row)
    for y in range(8,352):
        assert not pixels[y*70+69]&1,('body right margin is not black',y)
    # The exact URL glyphs occupy row 0, without an A2MONO banner before it.
    source=(ROOT/'mono_font.h').read_text()
    font=bytes(int(value,16) for value in re.findall(r'0x([0-9a-fA-F]{2})',source))
    assert len(font)==768
    for y in range(8):
        for column,char in enumerate(url):
            expected=font[(ord(char)-32)*8+y]^0x7F
            for bit in range(7):
                x=column*7+bit
                actual=(pixels[y*70+x//8]>>(7-(x&7)))&1
                assert actual==((expected>>bit)&1),('URL row',column,char,y,bit)


def idle(out,banks=6):
    target=Runner(out,'https://fixture.test/start',23)
    target.memory.aux=target.memory.aux[:banks]
    target.input=[];target.capture_at={}
    try:target.run(10_000_000)
    except AssertionError as error:
        assert str(error)=='browser requested unexpected extra input',error
    else:raise AssertionError('reader did not reach its first input')
    assert target.memory.requests==[],'home page fetched an image automatically'
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build'/'mono-reader')
    args=parser.parse_args();out=args.build.resolve()
    base=idle(out)
    page=(b"<h1>Manual images</h1><p>Images start OFF.</p>"
          b"<h2>One</h2><img src='one.gif'><h2>Two</h2><img src='/two.gif'>"
          b"<h2>Three</h2><img src='//fixture.test/three.gif'>"
          b"<p><a href='next.html'>Next page</a></p>")
    first='https://fixture.test/start';final='https://fixture.test/docs/index.html'
    images=['https://fixture.test/docs/one.gif','https://fixture.test/two.gif','https://fixture.test/three.gif']
    base.memory.fixtures={first:('text/html',page,final,[301,302,307,308]),
                          final:('text/html',page),
                          'https://fixture.test/docs/next.html':('text/html',b"<h1>Next page</h1><img src='child.gif'>")}
    for image in images:base.memory.fixtures[image]=('image/gif',fixture_gif(16,8))
    base.memory.fixtures['https://fixture.test/docs/child.gif']=('image/gif',fixture_gif(16,8))
    keys=bytearray(b'ghttps://fixture.test/start\r')
    captures={len(keys):'reader-images-off'}
    keys.extend(b' ')
    captures[len(keys)]='reader-scroll-off'
    keys.extend(b'i')
    captures[len(keys)]='reader-images-on'
    keys.extend(b' ')
    captures[len(keys)]='reader-lazy-scroll'
    keys.extend(b'p\r') # scroll up and follow the only link
    captures[len(keys)]='reader-next-off'
    keys.extend(b'q')
    target,report=run(base,keys,captures,'manual-lazy-images-and-redirects')
    shots={item['name']:item for item in target.captures}
    assert shots['reader-images-off']['requests']==[first]
    assert shots['reader-scroll-off']['requests']==[first]
    assert any(image in shots['reader-images-on']['requests'] for image in images)
    assert any(image not in shots['reader-images-on']['requests'] for image in images),'fixture has no offscreen image'
    assert all(image in shots['reader-lazy-scroll']['requests'] for image in images)
    assert 'https://fixture.test/docs/child.gif' not in target.memory.requests
    assert target.memory.requests[-1]=='https://fixture.test/docs/next.html'
    assert not any('wsrv' in request or 'frogfind' in request for request in target.memory.requests)
    white_url_row(target,'https://fixture.test/docs/next.html')
    reports=[report]

    theme=deepcopy(base)
    theme.memory.fixtures={'https://fixture.test/theme':('text/plain',b'Body')}
    keys=b'ghttps://fixture.test/theme\rq'
    target,report=run(theme,keys,{len(keys)-1:'reader-body-theme'},'white-body-glyphs-on-black')
    white_url_row(target,'https://fixture.test/theme')
    font=bytes(int(value,16) for value in re.findall(
        r'0x([0-9a-fA-F]{2})',(ROOT/'mono_font.h').read_text()))
    pixels=framebuffer(target.memory)
    for column,char in enumerate('Body',1):
        for gy in range(8):
            expected=font[(ord(char)-32)*8+gy]
            for bit in range(7):
                x=column*7+bit;y=8+gy
                assert ((pixels[y*70+x//8]>>(7-(x&7)))&1)==((expected>>bit)&1),('body glyph polarity',char,gy,bit)
    reports.append(report)

    large=(b"<h1>Large HTML</h1>"+b' '*9000+
           b"<p>AFTER8K</p><a href='after8k.html'>AFTER8K</a>"+b' '*32000+
           b"<p>AFTER40K</p><a href='after40k.html'>AFTER40K</a><img src='after40k.gif'>")
    for banks in (6,4):
        target=idle(out,banks)
        target.memory.fixtures={'https://fixture.test/large':('text/html',large,'https://fixture.test/large/index.html'),
             'https://fixture.test/large/after40k.gif':('image/gif',fixture_gif(16,8)),
             'https://fixture.test/large/after40k.html':('text/html',b"<h1>Followed link beyond 40KB</h1>")}
        keys=bytearray(b'ghttps://fixture.test/large\r')
        capture={len(keys):'large-html' if banks==6 else 'fallback-html'}
        if banks==6:keys.extend(b'i\t\r')
        keys.extend(b'q')
        target,report=run(target,keys,capture,'large-html' if banks==6 else '8k-fallback')
        capacity=int.from_bytes(target.memory.main[target.symbols['_mono_document_capacity']:target.symbols['_mono_document_capacity']+2],'little')
        assert capacity==(65535 if banks==6 else 8192),capacity
        if banks==6:
            assert 'https://fixture.test/large/after40k.gif' in target.memory.requests
            assert target.memory.requests[-1]=='https://fixture.test/large/after40k.html'
        else:assert target.memory.requests==['https://fixture.test/large']
        report['html_input_bytes']=len(large);report['document_capacity']=capacity
        reports.append(report)
    result={'model':'actual NMOS6502 + mocked ProDOS/native HTTP FIFO',
            'board_evidence':False,'old_open_policy':old_open_policy(out),
            'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
            'cases':reports}
    (out/'reader-features.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
