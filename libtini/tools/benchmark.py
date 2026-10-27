#!/usr/bin/env python3
"""Benchmark actual libtini routines using native emulator guest counters.

Default: CPU-only ROM/ProDOS boot with bundled inputs. --private also builds
and runs the optional binary. --boot-roms DIR overrides the ROM directory;
--direct-launch uses the ProDOS MLI stand-in without ROM boot.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build as build_tools
import native_emulator
import boot_roms

OPERATIONS={0:('marker_reference',0),1:('resource_write_cross_bank',512),
            2:('resource_read_cross_bank',512),3:('resource_fill_cross_bank',1024),
            4:('resource_copy_cross_bank',1024),5:('publish_full_shr',32000),
            6:('draw_dirty_rectangle',561),7:('publish_dirty_shr',561)}

def symbols(path):
    result={}
    for line in path.read_text().splitlines():
        p=line.split()
        if len(p)>=3 and p[0]=='al':result[p[2].lstrip('.')]=int(p[1],16)
    return result

def build(home,private):
    sdk,tools,versions=build_tools.installed_tools(home)
    out=ROOT/'build/benchmark'/('private' if private else 'cpu');out.mkdir(parents=True,exist_ok=True)
    build_tools.BUILD=out;objects=[]
    sources=['src/memory.c','src/memory_copy.c','src/timing.c','src/timing_gap.c','src/graphics.c','src/graphics_video.c','examples/benchmark.c']
    if private:sources.append('src/amem.c')
    for name in sources:
        obj=out/('benchmark_'+Path(name).stem+'.o')
        build_tools.compile_c(ROOT/name,obj,sdk,tools,private);objects.append(obj)
    assembly=['src/target/memory.s','src/target/hardware.s','src/target/surface.s','src/target/publish.s']
    if private:assembly.append('src/optional/amem_transport.s')
    for name in assembly:
        obj=out/('benchmark_asm_'+Path(name).stem+'.o')
        build_tools.assemble(ROOT/name,obj,sdk,tools);objects.append(obj)
    startup=out/'benchmark_startup.o'
    build_tools.assemble(ROOT/'src/target/startup.s',startup,sdk,tools)
    program,labels=out/'benchmark.system',out/'benchmark.lbl'
    build_tools.run([tools['ld65'],'-C','cfg/libtini.cfg','-o',program,'-Ln',labels,'-m',out/'benchmark.map',startup,*objects,tools['runtime']])
    image=out/'benchmark.po'
    template=ROOT/'build-inputs/prodos/ProDOS_2_4_3.po'
    image.write_bytes(build_tools.build_image(template.read_bytes(),program.read_bytes(),'BENCH.SYSTEM',total=1600))
    inputs=sources+assembly+['src/target/startup.s','cfg/libtini.cfg','tools/build.py','tools/benchmark.py']
    inputs+=sorted(p.relative_to(ROOT).as_posix() for folder in ('include','src') for p in (ROOT/folder).rglob('*.h'))
    (out/'build.json').write_text(json.dumps({'private':private,'tools':{name:{'version':versions.get(name),'sha256':native_emulator.digest(path)} for name,path in tools.items()},
        'input_sha256':{p:native_emulator.digest(ROOT/p) for p in sorted(set(inputs))},
        'program_sha256':native_emulator.digest(program),'disk_sha256':native_emulator.digest(image)},indent=2)+'\n')
    return out,image,symbols(labels)

def counters(state):
    return {key:state[key] for key in ('cycles','ticks','steps','io_reads','io_writes','shr_writes')}

def banked(machine,position,length):
    data=bytearray()
    while length:
        bank,within=divmod(position,48640);piece=min(length,48640-within)
        data+=machine.read('aux'+str(1+bank),512+within,piece)
        position+=piece;length-=piece
    return bytes(data)

def measure(cli,out,image,labels,profile,roms):
    options=['debug','--disk',str(image),'--profile',profile]
    if roms:
        options+=['--boot','--rom',str(roms/'Apple2e_Enhanced.rom'),
                  '--slot7-rom',str(roms/'smartport_a2retronet_style_c700.mem'),
                  '--slot7-c8-rom',str(roms/'smartport_a2retronet_style_c800.mem')]
    else:options+=['--system','BENCH.SYSTEM']
    machine=cli.Machine(cli.parser().parse_args(options))
    def value(name,n=1):return int.from_bytes(machine.read('main',labels[name],n),'little')
    try:
        first=machine.run(steps=50_000_000,breakpoints=[labels['_bench_mark']],timeout=30)
        assert first['reason']=='breakpoint',(profile,first)
        assert value('_bench_phase')==0,('benchmark setup failed',value('_bench_phase'),value('_bench_last_error'))
        record={'machine':machine.metadata(),'private_enable_error':value('_bench_accel_status'),
                'private_active':bool(value('_bench_accel_active')),'operations':[]}
        before=counters(machine.state())
        for phase in range(8):
            assert value('_bench_phase')==phase
            machine.run(steps=1)
            finished=machine.run(steps=20_000_000,breakpoints=[labels['_bench_mark']],timeout=30)
            assert finished['reason']=='breakpoint' and value('_bench_phase')==phase+1,(profile,phase,finished)
            assert value('_bench_last_error')==0,(profile,phase,value('_bench_last_error'))
            after=counters(machine.state());delta={key:after[key]-before[key] for key in before}
            operation,bytes_=OPERATIONS[phase]
            record['operations'].append({'operation':operation,'bytes':bytes_,**delta,
                'modeled_seconds':delta['ticks']/machine.clock_hz})
            # Independent raw-storage checks happen while execution is paused.
            pattern=bytes((i*5+17)&255 for i in range(512))
            if phase==1:assert banked(machine,48640-256,512)==pattern
            elif phase==2:assert machine.read('main',labels['_bench_result'],512)==pattern
            elif phase==3:assert banked(machine,48640-256,1024)==bytes([0xA6])*1024
            elif phase==4:assert banked(machine,2*48640-256,1024)==bytes([0xA6])*1024
            elif phase in (5,7):
                assert delta['shr_writes']==bytes_,('publication byte count',delta,bytes_)
                assert value('_bench_stats',4)==bytes_
                if phase==5:assert machine.read('aux0',0x2000,32000)==bytes([0x44])*32000
                else:
                    line=machine.read('aux0',0x2000+9*160+5,33)
                    assert line==bytes([0x45])+bytes([0x55])*32,line.hex()
            before=after
        if profile=='turbo-f122':
            costs=out/(profile+'-costs.json')
            machine.check(machine.lib.ap_cost_report(machine.handle,str(costs.resolve()).encode()))
            record['cost_report']=str(costs.relative_to(ROOT))
            report=json.loads(costs.read_text())
            record['cost_counters']=report.get('cost',report.get('counters',report))
            expected_requests=8 if record['private_active'] else 0
            assert record['cost_counters']['amem_requests']==expected_requests,'unexpected AMEM/video transport selection'
            assert record['cost_counters']['amem_bytes']==(3072 if record['private_active'] else 0)
        # Resume cleanup, then inspect the actual QUIT submission in both modes.
        machine.run(steps=1)
        done=machine.run(steps=10_000_000,breakpoints=[0xBF00],timeout=30)
        state=machine.state();sp=state['registers']['s']
        if done['reason']=='quit':
            assert not roms,'real ROM boot unexpectedly used a QUIT trap'
        else:
            assert done['reason']=='breakpoint',done
            stack=machine.read('main',0x100,256);ret=stack[(sp+1)&255]|stack[(sp+2)&255]<<8
            assert machine.read('main',ret+1,1)==b'\x65','benchmark did not submit QUIT'
        record['quit_submitted']=True
        record['final_bank']=state['bank']
        assert state['bank']==0 and state['newvideo']==1,'benchmark cleanup failed'
        return record
    finally:machine.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc65-home',required=True);p.add_argument('--cc',required=True)
    p.add_argument('--private',action='store_true',help='also benchmark the separately compiled optional binary')
    boot_roms.add_arguments(p)
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--output',type=Path,default=ROOT/'build/benchmark/results.json')
    a=p.parse_args()
    if not 1<=a.repeat<=10:raise SystemExit('--repeat must be 1..10')
    a.output=a.output.resolve()
    if not a.output.is_relative_to(ROOT):raise SystemExit('Benchmark output must remain inside the project')
    if a.boot_roms:
        a.boot_roms=a.boot_roms.resolve()
        if not a.boot_roms.is_relative_to(ROOT):raise SystemExit('Install benchmark boot inputs inside build-inputs first')
        for name in ('Apple2e_Enhanced.rom','smartport_a2retronet_style_c700.mem','smartport_a2retronet_style_c800.mem'):
            if not (a.boot_roms/name).is_file():raise SystemExit('Missing installed boot input: '+name)
    builds=[(private,*build(a.cc65_home,private)) for private in ([False,True] if a.private else [False])]
    library=native_emulator.build(a.cc)
    sys.modules.pop('disk',None);sys.path.insert(0,str(native_emulator.FRONT));import cli
    cli.build_library=lambda:library
    evidence={'physical_board_tested':False,'native_source_revision':native_emulator.source_revision(),
              'dll_sha256':native_emulator.digest(library),
              'measurement':'Guest-counter differences between exported phase markers; includes marker/result-store overhead. No automatic overhead subtraction.',
              'profile_limits':'vtw33 functional CPU cycles omit hardware waits; turbo-f122 uses historical F1.2.2 costs. Neither predicts current board performance.',
              'runs':[]}
    for private,out,image,labels in builds:
        for profile in ('vtw33','turbo-f122'):
            samples=[measure(cli,out,image,labels,profile,a.boot_roms) for _ in range(a.repeat)]
            stable=all(sample['operations']==samples[0]['operations'] for sample in samples[1:])
            assert stable,'repeated guest-counter measurements differ'
            record={'private_compiled':private,'profile':profile,'repeat_counters_identical':stable,'samples':samples}
            evidence['runs'].append(record)
            active=samples[0]['private_active']
            print(('optional' if private else 'CPU')+' '+profile+'; AMEM active='+str(active))
            for index,(name,bytes_) in OPERATIONS.items():
                costs=[sample['operations'][index]['ticks'] for sample in samples]
                seconds=[sample['operations'][index]['modeled_seconds'] for sample in samples]
                cycles=[sample['operations'][index]['cycles'] for sample in samples]
                print('  %-27s %5d bytes %10.0f CPU cycles %10.0f guest ticks %10.6f modeled seconds'%(name,bytes_,statistics.median(cycles),statistics.median(costs),statistics.median(seconds)))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(evidence,indent=2)+'\n')
    print(a.output)

if __name__=='__main__':main()
