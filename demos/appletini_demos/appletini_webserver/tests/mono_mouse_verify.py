#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the assembled polled mouse driver against standard Mousecard ROM mocks.

ROM callbacks implement the documented entry table and screen-hole protocol.
The NMOS6502 executes all detection, mapping, hole preservation, coordinate
conversion, edge detection, and cleanup instructions from mono_mouse.s.
"""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_mono import run,tool
from mono_verify import labels


class Memory:
    vectors=(0xB3,0xC4,0x9B,0xA4,0xC0,0x8A,0xDD,0xBC)
    def __init__(self,slot=None,invalid=False):
        self.main=bytearray(65536)
        self.rom=[bytearray([0xFF])*256 for _ in range(8)]
        self.slot=slot
        self.cx=True
        self.c3=False
        self.lc=True
        self.selected=False
        self.x=self.y=0
        self.down=False
        self.mode=15
        self.irq=True
        self.clamps=[(0,1023),(0,1023)]
        self.calls=[]
        for i in range(0x400,0x800):self.main[i]=(i*37+11)&255
        self.main[6:8]=b'\xA7\x5C'
        if slot:
            for at,value in ((5,0x38),(7,0x18),(11,1),(12,0x20),(251,0xD6)):
                self.rom[slot][at]=value
            self.rom[slot][0x12:0x1A]=bytes(self.vectors)
            if invalid:self.rom[slot][0x14]=0

    def switch(self,a):
        if a==0xC006:self.cx=False
        elif a==0xC007:self.cx=True
        elif a==0xC00A:self.c3=False
        elif a==0xC00B:self.c3=True
        elif a==0xCFFF:self.selected=False
        elif a==0xC080:self.lc=True
        elif a==0xC082:self.lc=False

    def __getitem__(self,a):
        a &= 65535
        self.switch(a)
        if a==0xC015:return 0x80 if self.cx else 0
        if a==0xC017:return 0x80 if self.c3 else 0
        if 0xC100<=a<0xC800:
            slot=(a>>8)-0xC0
            if not self.cx and (slot!=3 or self.c3):
                self.selected=True
                return self.rom[slot][a&255]
            # Internal slot 3 intentionally resembles three Mouse ID bytes.
            return {5:0x38,7:0x18,11:1,12:0}.get(a&255,0xFF)
        return self.main[a]

    def __setitem__(self,a,value):
        a &= 65535
        self.switch(a)
        if 0xC000<=a<=0xCFFF:return
        self.main[a]=value&255

    def firmware(self,cpu,entry):
        assert cpu.x==0xC0+self.slot and cpu.y==self.slot*16,(cpu.x,cpu.y)
        assert cpu.p&4 and not self.cx and not self.lc,'unsafe firmware environment'
        self.calls.append((entry,cpu.a))
        n=self.slot
        def put(base,value):
            self.main[base+n]=value&255
            self.main[base+0x100+n]=value>>8
        def word(lo,hi):return self.main[lo]|self.main[hi]<<8
        if entry==0: # SETMOUSE
            assert cpu.a in (0,1),'driver requested interrupts'
            self.mode=cpu.a
            self.main[0x7F8+n]=self.mode
        elif entry==1:self.irq=False # SERVEMOUSE
        elif entry==2: # READMOUSE
            put(0x478,self.x);put(0x4F8,self.y)
            self.main[0x778+n]=0x80 if self.down else 0
        elif entry==4: # POSMOUSE
            self.x=word(0x478+n,0x578+n)
            self.y=word(0x4F8+n,0x5F8+n)
        elif entry==5: # CLAMPMOUSE
            self.clamps[cpu.a]=(word(0x478,0x578),word(0x4F8,0x5F8))
        elif entry==7: # INITMOUSE
            self.x=self.y=0
            self.clamps=[(0,1023),(0,1023)]
            put(0x478,0);put(0x4F8,0)
        else:raise AssertionError(('unexpected firmware call',entry))
        # A real AppleMouse borrows these locations, and its registers are
        # not preserved. The public driver must restore the application ZP.
        self.main[6:8]=b'\x60\xEA'
        cpu.a=0;cpu.x=n;cpu.y=0x5A;cpu.p&=~1
        cpu.pc=(cpu.stPopWord()+1)&65535


class Rig:
    def __init__(self,out,slot=None,invalid=False):
        from py65.devices.mpu6502 import MPU
        self.memory=Memory(slot,invalid)
        self.code=(out/'mouse.bin').read_bytes()
        self.memory.main[0x6000:0x6000+len(self.code)]=self.code
        self.symbols=labels(out/'mouse.lbl')
        self.cpu=MPU(memory=self.memory,pc=0x6000)
        self.steps=0

    def value(self,name):return self.memory.main[self.symbols['_mono_mouse_'+name]]
    def call(self,name,irq_disabled=False):
        cpu=self.cpu
        before=bytes(self.memory.main[0x400:0x800])
        zp=bytes(self.memory.main[6:8])
        mapping=self.memory.cx,self.memory.c3
        cpu.p=0x24 if irq_disabled else 0x20
        cpu.sp=0xFF
        cpu.stPushWord(0x02FE)
        cpu.pc=self.symbols['_mono_mouse_'+name]
        local=0
        while cpu.pc!=0x02FF:
            if self.memory.slot and cpu.pc>>8==0xC0+self.memory.slot:
                entry=self.memory.vectors.index(cpu.pc&255)
                self.memory.firmware(cpu,entry)
            else:
                assert self.memory[cpu.pc]!=0,('BRK',hex(cpu.pc))
                cpu.step()
            local+=1
            assert local<100_000,('instruction budget',name,hex(cpu.pc))
        self.steps+=local
        assert bytes(self.memory.main[0x400:0x800])==before,'screen holes changed'
        assert bytes(self.memory.main[6:8])==zp,'application zero page changed'
        assert (self.memory.cx,self.memory.c3)==mapping,'slot ROM mapping changed'
        assert self.memory.lc and not self.memory.selected,'LC/C8 mapping leaked'
        assert bool(cpu.p&4)==irq_disabled,'interrupt policy changed'
        return cpu.a


def main():
    out=ROOT/'build'/'mono-mouse-test'
    out.mkdir(parents=True,exist_ok=True)
    (out/'mouse.cfg').write_text('MEMORY { ZP:start=$80,size=$1A,file=""; '
        'MAIN:start=$6000,size=$2000,file=%O; BSS:start=$0900,size=$100,file=""; }\n'
        'SEGMENTS { ZEROPAGE:load=ZP,type=zp; BROWSER:load=MAIN,type=rw; '
        'BSS:load=BSS,type=bss; }\n')
    run([tool('ca65'),'--cpu','6502','-o',str(out/'mouse.o'),'mono_mouse.s'])
    # The cc65 archive supplies only its shared ZP-register allocation.
    lib=Path(tool('cl65')).resolve().parents[1]/'lib'/'apple2.lib'
    run([tool('ld65'),'-C',str(out/'mouse.cfg'),'-o',str(out/'mouse.bin'),
         '-Ln',str(out/'mouse.lbl'),str(out/'mouse.o'),str(lib)])
    count=steps=0
    for slot in (None,2,3,7):
        rig=Rig(out,slot)
        assert rig.call('init')==bool(slot)
        if not slot:
            assert rig.call('poll')==0 and not rig.memory.calls
            rig.call('disable');count+=1;steps+=rig.steps;continue
        assert rig.memory.mode==1 and not rig.memory.irq
        assert rig.memory.clamps==[(0,559),(0,383)]
        assert (rig.value('x'),rig.value('y'))==(40,24)
        assert rig.call('poll')==0
        rig.memory.x,rig.memory.y=559,383
        assert rig.call('poll')==1
        assert (rig.value('x'),rig.value('y'))==(79,47)
        rig.memory.down=True
        assert rig.call('poll',True)==2 and rig.value('pressed')==1
        assert rig.call('poll')==0 and rig.value('pressed')==0 and rig.value('down')==1
        rig.memory.x,rig.memory.y=0,0
        assert rig.call('poll')==1
        assert (rig.value('x'),rig.value('y'))==(0,0)
        rig.memory.down=False
        assert rig.call('poll')==4
        # Image decoding replaces MONO.WEB; restoring its original code must
        # leave the selected card usable without another init call.
        rig.memory.main[0x6000:0x6000+len(rig.code)]=rig.code
        rig.memory.x,rig.memory.y=65535,65535
        assert rig.call('poll')==1
        assert (rig.value('x'),rig.value('y'))==(79,47)
        rig.call('disable')
        assert not rig.value('available') and rig.memory.mode==0 and not rig.memory.irq
        calls=len(rig.memory.calls)
        rig.call('disable',True)
        assert len(rig.memory.calls)==calls
        count+=1;steps+=rig.steps
    invalid=Rig(out,2,True)
    assert invalid.call('init')==0 and not invalid.memory.calls
    count+=1;steps+=invalid.steps
    report={'model':'assembled NMOS6502 + mocked standard AppleMouse ROM',
            'board_evidence':False,'configurations':count,'instructions':steps,
            'browser_code_bytes':len((out/'mouse.bin').read_bytes()),
            'checks':['absence','slots 2/3/7','movement and clamps','button edges',
                      'overlay reload','screen-hole and ZP preservation',
                      'ROM and IRQ mappings','disable and stale IRQ cleanup',
                      'invalid vector rejection']}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
