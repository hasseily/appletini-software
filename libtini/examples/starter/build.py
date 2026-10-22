#!/usr/bin/env python3
"""Build the materialized starter using only its copies and an installed SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent

def run(arguments):
    subprocess.run(list(map(str,arguments)),cwd=ROOT,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc65-home',default=os.environ.get('CC65_HOME'))
    parser.add_argument('--no-disk',action='store_true')
    args=parser.parse_args()
    if args.cc65_home:sdk=Path(args.cc65_home).resolve()
    else:
        executable=shutil.which('cc65')
        if not executable:raise SystemExit('Install cc65 2.19 and pass --cc65-home')
        sdk=Path(executable).resolve().parent.parent
    suffix='.exe' if os.name=='nt' else ''
    tools={n:sdk/'bin'/(n+suffix) for n in ('cc65','ca65','ld65','ar65')}
    for name,tool in tools.items():
        result=subprocess.run([str(tool),'V' if name=='ar65' else '--version'],capture_output=True,text=True,check=True)
        if (result.stdout+result.stderr).strip()!=name+' V2.19':raise SystemExit('cc65 SDK2.19 required')
    out=ROOT/'build';out.mkdir(exist_ok=True)
    def compile(source,stem):
        assembly=out/(stem+'.s');obj=out/(stem+'.o')
        if source.suffix=='.c':
            run([tools['cc65'],'-t','none','--cpu','65c02','--standard','c99','-O',
                 '-I',sdk/'include','-I','runtime/include','-I','runtime/src',
                 '-D','TI_PRIVATE_TRANSPORT=0','-o',assembly,source])
        else:assembly=source
        run([tools['ca65'],'-t','none','--cpu','65c02','-I',sdk/'asminc','-o',obj,assembly])
        return obj
    modules=[]
    for source in sorted((ROOT/'runtime/src').glob('*.c')):modules.append(compile(source,'sdk_'+source.stem))
    for source in sorted((ROOT/'runtime/src/target').glob('*.s')):
        if source.name!='startup.s':modules.append(compile(source,'target_'+source.stem))
    archive=out/'libtini.lib';archive.unlink(missing_ok=True)
    run([tools['ar65'],'r',archive,*modules])
    startup=compile(ROOT/'runtime/src/target/startup.s','startup')
    application=compile(ROOT/'main.c','main')
    binary=out/'APP.SYSTEM'
    run([tools['ld65'],'-C','runtime/cfg/libtini.cfg','-o',binary,'-m',out/'APP.map',
         '-Ln',out/'APP.lbl',startup,application,archive,sdk/'lib/none.lib'])
    if not args.no_disk:
        sys.path.insert(0,str(ROOT/'runtime/tools'))
        from disk import build_image
        lock=json.loads((ROOT/'runtime/tools/prodos-input.json').read_text())
        os_image=ROOT/'runtime'/lock['path']
        if not os_image.exists():raise SystemExit('Run python runtime/tools/setup_inputs.py first')
        data=os_image.read_bytes()
        if hashlib.sha256(data).hexdigest()!=lock['sha256']:raise SystemExit('ProDOS hash mismatch')
        (out/'APP.po').write_bytes(build_image(data,binary.read_bytes(),'APP.SYSTEM'))
    print('Built',binary)

if __name__=='__main__':main()
