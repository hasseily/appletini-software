#!/usr/bin/env python3
"""Compiled storage tests: native MLI success plus focused fault/OS-loan model."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build as build_tools
import native_emulator
import assets
from apple2_model import Apple2Memory,read_labels
from py65.devices.mpu65c02 import MPU

def build_target(stem,cc65_home,c_sources,asm_sources,private=False):
    sdk,tools,_=build_tools.installed_tools(cc65_home)
    out=ROOT/'build'/stem;out.mkdir(parents=True,exist_ok=True)
    build_tools.BUILD=out
    objects=[]
    for source in c_sources:
        obj=out/(stem+'_'+Path(source).stem+'.o')
        build_tools.compile_c(ROOT/source,obj,sdk,tools,private);objects.append(obj)
    for source in asm_sources:
        obj=out/(stem+'_asm_'+Path(source).stem+'.o')
        build_tools.assemble(ROOT/source,obj,sdk,tools);objects.append(obj)
    startup=out/(stem+'_startup.o')
    build_tools.assemble(ROOT/'src/target/startup.s',startup,sdk,tools)
    program,labels=out/(stem+'.system'),out/(stem+'.lbl')
    build_tools.run([tools['ld65'],'-C','cfg/libtini.cfg','-o',program,'-Ln',labels,'-m',out/(stem+'.map'),startup,*objects,tools['runtime']])
    return out,program,labels

def fixtures():
    good=assets.pack([('A_DATA',bytes((i*7+3)&255 for i in range(600))),('ZED',bytes(range(32)))])
    result={'HELLO':bytes((i*13+9)&255 for i in range(300)),'GOOD.TPK':good}
    bad=bytearray(good);bad[0]=ord('X');result['BADSIG.TPK']=bytes(bad)
    bad=bytearray(good);bad[32:48]=bad[8:24];result['DUP.TPK']=bytes(bad)
    bad=bytearray(good);struct.pack_into('<I',bad,48,56);result['OVERLAP.TPK']=bytes(bad)
    bad=bytearray(good);bad[9]=ord('!');result['BADNAME.TPK']=bytes(bad)
    bad=bytearray(good);bad[10]=0;result['TAIL.TPK']=bytes(bad)
    bad=bytearray(good);struct.pack_into('<I',bad,28,0);result['ZERO.TPK']=bytes(bad)
    result['DIRSHORT.TPK']=b'TPK1'+struct.pack('<HH',2,0)+bytes(8)
    return result

class CpuRun:
    def __init__(self,program,labels,memory=None):
        self.labels=read_labels(labels);self.memory=memory or Apple2Memory(8)
        self.memory.main[0x2000:0x2000+program.stat().st_size]=program.read_bytes()
        self.cpu=MPU(memory=self.memory,pc=0x2000);self.memory.cpu=self.cpu
        self.cpu.sp=0xF7;self.cpu.p=0x20;self.steps=0;self.quit=False
        self.mode=0;self.started=False;self.mli_calls=[]
    def value(self,name,width=2):
        p=self.labels[name];return int.from_bytes(self.memory.main[p:p+width],'little')
    def mli(self,command,params):raise AssertionError(('unexpected MLI',command))
    def observe(self):pass
    def run(self,limit=30_000_000):
        while self.steps<limit:
            pc=self.cpu.pc
            if not self.started and pc==self.labels['_main']:
                self.started=True
                for symbol in ('_storage_mode','_amem_mode'):
                    if symbol in self.labels:self.memory.main[self.labels[symbol]]=self.mode
            self.observe()
            assert self.cpu.sp>=0x80,('hardware stack',self.cpu.sp)
            if self.memory.ramrd:assert 0x140<=pc<0x180,('AUX fetch',hex(pc))
            if self.memory.ramrd or self.memory.ramwrt or self.memory.bank:assert self.cpu.p&4,'IRQ enabled under AUX mapping'
            if pc==0xBF00:
                sp=self.cpu.sp
                ret=self.memory.main[0x100+((sp+1)&255)]|self.memory.main[0x100+((sp+2)&255)]<<8
                command=self.memory[ret+1];params=self.memory[ret+2]|self.memory[ret+3]<<8
                self.mli_calls.append(command)
                if command==0x65:self.quit=True;return
                error=self.mli(command,params)
                self.cpu.a=error;self.cpu.p=(self.cpu.p|1) if error else (self.cpu.p&~1)
                self.cpu.pc=(self.cpu.stPopWord()+4)&65535
            else:
                assert self.memory[pc]!=0,('BRK',hex(pc))
                self.cpu.step()
            self.steps+=1
        raise AssertionError(('instruction budget',self.mode,hex(self.cpu.pc)))

class FilesRun(CpuRun):
    def __init__(self,program,labels,mode):
        super().__init__(program,labels);self.mode=mode;self.files={k:bytearray(v) for k,v in fixtures().items()}
        self.opened={};self.next_ref=1;self.injected=False;self.phase_seen=0
        self.original=bytes((i*19+7)&255 for i in range(65536));self.memory.aux[0][:]=self.original
        self.expected_os=bytearray(self.original)
        self.memory.main[0x4E:0x50]=bytes([0x17,0x28])
    def observe(self):
        phase=self.value('_storage_phase',1) if self.started else 0
        if self.mode==4 and phase>=2 and self.phase_seen<2:
            expected=bytearray(self.original);expected[0x2000:0x2080]=bytes([0x77])*128
            assert self.memory.aux[0]==expected,'picture was not republished after OS loan'
            assert self.memory.shr==0xC1
            self.phase_seen=phase
    def mli(self,cmd,p):
        m=self.memory.main
        def w(i):return m[p+i]|m[p+i+1]<<8
        def put(i,n,size=2):m[p+i:p+i+size]=n.to_bytes(size,'little')
        assert m[p]=={0xC0:7,0xC8:3,0xD1:2,0xCA:4,0xCB:4,0xCC:1,0xCE:2,0xD0:2}[cmd],('parameter count',cmd,m[p])
        m[0x4E:0x50]=bytes([0xAA,0xBB]) # ProDOS may use its random-number bytes.
        if self.mode==4:
            assert self.memory.aux[0]==self.expected_os,'MLI did not receive the latest restored OS AUX image'
            assert self.memory.shr==1,'SHR must be off while OS owns AUX0'
            self.expected_os[0x2234]=0xD1;self.expected_os[0x9FE0]=0xC2
            self.memory.aux[0][:]=self.expected_os
        assert not self.memory.ramrd and not self.memory.ramwrt and self.memory.bank==0
        if cmd in (0xC0,0xC8):
            path=w(1);name=bytes(m[path+1:path+1+m[path]]).decode()
            if cmd==0xC0:
                if name in self.files:return 0x47
                self.files[name]=bytearray();return 0
            if name not in self.files:return 0x46
            assert w(3)==0xB000,'ProDOS I/O buffer is not the reserved aligned window'
            ref=self.next_ref;self.next_ref+=1;self.opened[ref]=[name,0];m[p+5]=ref;return 0
        ref=m[p+1]
        if ref not in self.opened:return 0x43
        name,pos=self.opened[ref];data=self.files[name]
        if cmd==0xD1:put(2,len(data),3)
        elif cmd==0xCE:self.opened[ref][1]=int.from_bytes(m[p+2:p+5],'little')
        elif cmd==0xCA:
            if self.mode==6 and name=='GOOD.TPK' and not self.injected:self.injected=True;return 0x27
            if self.mode==2 and name=='GOOD.TPK' and pos>=184 and not self.injected:self.injected=True;return 0x27
            count=min(w(4),len(data)-pos)
            if self.mode==1 and not self.injected:count=min(count,128);self.injected=True
            dest=w(2);m[dest:dest+count]=data[pos:pos+count];put(6,count);self.opened[ref][1]+=count
            if not count and w(4):return 0x4C
        elif cmd==0xCB:
            count=w(4);src=w(2)
            if self.mode in (8,9):count//=2
            if pos+count>len(data):data.extend(bytes(pos+count-len(data)))
            data[pos:pos+count]=m[src:src+count];put(6,count);self.opened[ref][1]+=count
            if self.mode==8:return 0x27
        elif cmd==0xD0:
            if self.mode==10:return 0x27
            size=int.from_bytes(m[p+2:p+5],'little')
            if size<len(data):del data[size:]
            else:data.extend(bytes(size-len(data)))
        elif cmd==0xCC:
            del self.opened[ref]
            if self.mode in (3,11) and not self.injected:self.injected=True;return 0x27
        else:raise AssertionError(('unsupported MLI',hex(cmd)))
        return 0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cc65-home',required=True);p.add_argument('--cc',required=True);a=p.parse_args()
    out,program,labels=build_target('storage',a.cc65_home,['src/memory.c','src/timing.c','src/timing_gap.c','src/storage.c','tests/storage_target.c'],['src/target/memory.s','src/target/hardware.s','src/target/storage.s'])
    evidence={'cpu_model':[],'native':[]}
    for mode in range(12):
        run=FilesRun(program,labels,mode);run.run()
        assert run.quit and not run.value('_storage_failed'),(mode,run.value('_storage_failed'))
        assert not run.opened,('leaked file ref',mode,run.opened)
        assert run.memory.aux[0]==run.expected_os,('OS image lost',mode)
        assert run.memory.main[0x4E:0x50]==bytes([0x17,0x28]),'MLI random-number bytes were not restored'
        if mode==5:assert run.mli_calls==[0x65],'allocation failure submitted an MLI call'
        evidence['cpu_model'].append({'mode':mode,'checks':run.value('_storage_checks'),'instructions':run.steps,'mli_calls':run.mli_calls})
        print('storage model mode',mode,'passed',run.value('_storage_checks'),'checks')
    image=out/'storage.po'
    files=[(name,data,6,0) for name,data in fixtures().items()]
    image.write_bytes(build_tools.build_image((ROOT/'build-inputs/prodos/ProDOS_2_4_3.po').read_bytes(),program.read_bytes(),files=files,total=1600))
    library=native_emulator.build(a.cc);sys.modules.pop('disk',None);sys.path.insert(0,str(native_emulator.FRONT));import cli
    cli.build_library=lambda:library
    syms=read_labels(labels)
    for profile in ('vtw33','turbo-f122'):
        machine=cli.Machine(cli.parser().parse_args(['debug','--disk',str(image),'--system','LIBTINI.SYSTEM','--profile',profile]))
        try:
            result=machine.run(steps=10_000_000,timeout=30)
            failure=int.from_bytes(machine.read('main',syms['_storage_failed'],2),'little')
            checks=int.from_bytes(machine.read('main',syms['_storage_checks'],2),'little')
            assert result['reason']=='quit' and failure==0,(profile,result,failure)
            evidence['native'].append({'profile':profile,'checks':checks,'run':result})
            print(profile,'native storage passed',checks,'checks')
        finally:machine.close()
    (out/'validation.json').write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':main()
