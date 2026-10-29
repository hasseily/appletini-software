#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Feed recorded real GitHub HTML through the compiled HTTP/browser path.

This validates the Apple client and renderer after the native HTTP service
accepts the response headers. Real TLS/header parsing needs its own tests.
The current 65535-byte raw-body cap covers navigation, not the full site.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from mono_verify import ROOT, Runner, framebuffer
from mono_features import white_url_row


def body_text(target, first_row=1, last_row=44):
    font=bytes(int(value,16) for value in re.findall(
        r'0x([0-9a-fA-F]{2})',(ROOT/'mono_font.h').read_text()))
    glyphs={}
    for code in range(32,128):
        glyphs.setdefault(tuple(font[(code-32)*8:(code-32)*8+7]),chr(code).upper())
    pixels=framebuffer(target.memory)
    lines=[]
    for row in range(first_row,last_row):
        line=[]
        for col in range(80):
            sample=[]
            for gy in range(7):
                value=0
                for bit in range(7):
                    x=col*7+bit;y=row*8+gy
                    value|=((pixels[y*70+x//8]>>(7-(x&7)))&1)<<bit
                sample.append(value)
            value=glyphs.get(tuple(sample))
            if value is None:value=glyphs.get(tuple(x^0x7F for x in sample),'?')
            line.append(value)
        lines.append(''.join(line).rstrip())
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build'/'mono-netfix')
    parser.add_argument('--github-body',type=Path,required=True)
    args=parser.parse_args();out=args.build.resolve()
    body=args.github_body.read_bytes()
    target=Runner(out,'https://github.com/',251)
    target.memory.aux=target.memory.aux[:6]
    target.memory.fixtures={'https://github.com/':('text/html; charset=utf-8',body)}
    target.input=list(b'ghttps://github.com/\rq')
    target.capture_at={0:'github-before',len(target.input)-1:'github-navigation'}
    target.run(150_000_000)
    assert target.memory.requests==['https://github.com/'],target.memory.requests
    assert not target.opened
    length_at=target.symbols['_mono_document_length']
    stored=int.from_bytes(target.memory.main[length_at:length_at+2],'little')
    assert stored==min(len(body),65535),stored
    white_url_row(target,'https://github.com/')
    text=body_text(target)
    assert any(phrase in text for phrase in ('SKIP TO CONTENT','NAVIGATION MENU','SIGN IN')),text
    (out/'github-navigation.txt').write_text(text+'\n')
    report={'model':'actual NMOS6502 HTTP client and renderer; mocked HTTP service',
            'board_evidence':False,'fixture_bytes':len(body),'stored_bytes':stored,
            'fixture_sha256':hashlib.sha256(body).hexdigest(),
            'program_sha256':hashlib.sha256((out/'A2MONO.bin').read_bytes()).hexdigest(),
            'requests':target.memory.requests,'instructions':target.steps,
            'captures':target.captures,'visible_text':text}
    (out/'github-browser.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
