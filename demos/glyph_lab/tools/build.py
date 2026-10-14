#!/usr/bin/env python3
"""Build original fonts, 6502 SYS, previews and an 800 KiB ProDOS image."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import assets
import prodos

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APPLETINI = ROOT.parents[1].parent / 'appletini-one'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(appletini: Path, acme: str, master: Path | None = None) -> dict:
    output = ROOT/'build'
    dist = ROOT/'dist'
    dist.mkdir(parents=True, exist_ok=True)
    metadata = assets.generate(output)
    assembler = shutil.which(acme) or acme
    subprocess.run([assembler, '--strict', '-I', str(output), '-f', 'plain',
                    '-o', str(output/'GLYPH.SYSTEM'), '-l', str(output/'labels.txt'),
                    str(ROOT/'glyph_lab.a65')], cwd=ROOT, check=True)
    system = (output/'GLYPH.SYSTEM').read_bytes()
    if len(system)>0x9000 or system[:2]!=bytes((0xA2,0xFF)):
        raise ValueError('SYS payload does not fit $2000-$AFFF')
    master = master or appletini/'software/ProDOS_2_4_3.po'
    kernel = prodos.read_file(master, 'PRODOS')
    disk = dist/'Glyph-Lab.hdv'
    prodos.build_image(disk, 'GLYPHLAB', master,
                       [('PRODOS',0xFF,0,kernel),('GLYPH.SYSTEM',0xFF,0x2000,system)])
    assert prodos.read_file(disk,'GLYPH.SYSTEM')==system
    assert prodos.read_file(disk,'PRODOS')==kernel
    assert disk.stat().st_size==800*1024
    metadata['inputs'] = {
        'prodos_master':{'path':str(master),'sha256':sha(master.read_bytes())},
        'PRODOS':{'sha256':sha(kernel),'bytes':len(kernel)},
        'glyph_lab.a65':{'sha256':sha((ROOT/'glyph_lab.a65').read_bytes())},
        'assets.py':{'sha256':sha((ROOT/'tools/assets.py').read_bytes())},
    }
    metadata['outputs'] = {
        'GLYPH.SYSTEM':{'sha256':sha(system),'bytes':len(system),'load_address':'2000'},
        'Glyph-Lab.hdv':{'sha256':sha(disk.read_bytes()),'bytes':disk.stat().st_size},
    }
    (dist/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf8')
    # Keep the runnable disk and its provenance beside the source, as other
    # demos do. build/ and dist/ stay disposable.
    shutil.copyfile(disk,ROOT/'Glyph-Lab.hdv')
    shutil.copyfile(dist/'manifest.json',ROOT/'manifest.json')
    previews=ROOT/'previews'
    previews.mkdir(exist_ok=True)
    for n in range(3):
        for extension in ('png','gif'):
            shutil.copyfile(output/f'preview{n}.{extension}',previews/f'scene{n+1}.{extension}')
    print(f'Built {disk}: {len(system)}-byte SYS, three original 4096-byte fonts.')
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appletini-root',type=Path,
                        default=Path(os.environ.get('APPLETINI_ROOT',DEFAULT_APPLETINI)))
    parser.add_argument('--master',type=Path)
    parser.add_argument('--acme',default=os.environ.get('ACME_EXE','acme'))
    args=parser.parse_args()
    build(args.appletini_root.resolve(),args.acme,args.master)
