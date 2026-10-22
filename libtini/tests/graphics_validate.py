#!/usr/bin/env python3
"""Build and execute focused graphics tests on the native Appletini machine."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build as build_tools
import native_emulator

LIBRARY_C=('memory','timing','timing_gap','error','font','graphics','graphics_dot','graphics_text',
           'graphics_line','graphics_blit','graphics_font','graphics_video','graphics_rows')
LIBRARY_ASM=('startup','memory','hardware','rows','surface','publish','text','digits')
# The drawing suite and the text suite are separate programs: together they
# do not fit the program area.
PROGRAMS=(('tests','tests/graphics_target.c'),('text','tests/text_target.c'))

def build_program(stem,test_source,library,sdk,tools,out):
    obj=out/('gfx_'+stem+'.o')
    build_tools.compile_c(ROOT/test_source,obj,sdk,tools)
    program=out/(stem+'.system');labels=out/(stem+'.lbl')
    # Startup must be first, irrespective of the source grouping above.
    startup=out/'gfx_target_startup.o'
    build_tools.run([tools['ld65'],'-C','cfg/libtini.cfg','-o',program,'-Ln',labels,
                     '-m',out/(stem+'.map'),startup,*[x for x in library if x!=startup],obj,tools['runtime']])
    symbol={}
    for line in labels.read_text().splitlines():
        f=line.split()
        if len(f)>=3 and f[0]=='al':symbol[f[2].lstrip('.')]=int(f[1],16)
    spec=importlib.util.spec_from_file_location('graphics_packager',ROOT/'tools/disk.py')
    disk=importlib.util.module_from_spec(spec);spec.loader.exec_module(disk)
    image=out/(stem+'.po')
    image.write_bytes(disk.build_image((ROOT/'build/libtini.po').read_bytes(),program.read_bytes()))
    return image,symbol

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc65-home',required=True);p.add_argument('--cc',required=True)
    a=p.parse_args()
    sdk,tools,versions=build_tools.installed_tools(a.cc65_home)
    out=ROOT/'build/graphics';out.mkdir(exist_ok=True)
    library=[]
    for name in LIBRARY_C:
        obj=out/('gfx_'+name+'.o')
        build_tools.compile_c(ROOT/'src'/(name+'.c'),obj,sdk,tools);library.append(obj)
    for name in LIBRARY_ASM:
        obj=out/('gfx_target_'+name+'.o')
        build_tools.assemble(ROOT/'src/target'/(name+'.s'),obj,sdk,tools);library.append(obj)
    programs=[(stem,*build_program(stem,source,library,sdk,tools,out)) for stem,source in PROGRAMS]
    dll=native_emulator.build(a.cc)
    sys.modules.pop('disk',None) # build.py and the frontend use distinct disk modules.
    sys.path.insert(0,str(native_emulator.FRONT));import cli
    cli.build_library=lambda:dll
    evidence=[]
    for stem,image,symbol in programs:
        for profile in ('vtw33','turbo-f122'):
            machine=cli.Machine(cli.parser().parse_args(['debug','--disk',str(image),'--system','LIBTINI.SYSTEM','--profile',profile]))
            try:
                original=bytes((i*7+23)&255 for i in range(65536));machine.write('aux0',0,original)
                result=machine.run(steps=200_000_000,timeout=300)
                checks=int.from_bytes(machine.read('main',symbol['_gfx_checks'],2),'little')
                failed=int.from_bytes(machine.read('main',symbol['_gfx_failed'],2),'little')
                assert result['reason']=='quit',(stem,profile,result)
                assert not failed,(stem,profile,checks,failed)
                assert checks>100,(stem,checks)
                assert machine.read('aux0',0,65536)==original,'AUX restoration'
                assert result['state']['bank']==0 and not result['state']['switches']['ramrd'] and not result['state']['switches']['ramwrt']
                evidence.append({'program':stem,'profile':profile,'checks':checks,'failed':failed,'run':result,'machine':machine.metadata()})
                print(stem+' '+profile+': '+str(checks)+' graphics checks passed')
            finally:machine.close()
    (out/'validation.json').write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':main()
