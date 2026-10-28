#!/usr/bin/env python3
"""Actual optional FIFO transport tests against a focused C8/controller model.

The synthetic ROM satisfies the driver's CRC identity check. It is not copied
firmware and these tests cannot establish timing or execution on real firmware.
"""
from __future__ import annotations
import argparse
import binascii
import json
from pathlib import Path
import sys

from storage_validate import ROOT,build_target,CpuRun
from apple2_model import Apple2Memory

def identity_rom():
    rom=bytearray(256);rom[0]=0xC9;rom[1]=0x20;rom[5]=3
    prefix=binascii.crc_hqx(rom[:254],0xFFFF)
    for value in range(65536):
        tail=value.to_bytes(2,'little')
        if binascii.crc_hqx(tail,prefix)==0x95D9:rom[254:]=tail;return bytes(rom)
    raise AssertionError('CRC construction')

class Controller(Apple2Memory):
    def __init__(self,mode):
        super().__init__(8);self.mode=mode;self.intcxrom=True;self.selected=None
        self.rom=bytes(256) if mode==1 else identity_rom()
        if mode==12:self.rom=self.rom[:-1]+bytes([self.rom[-1]^1])
        self.incoming=[];self.response=[];self.at=0;self.requests=[];self.controls=[];self.statuses=0;self.fifo_writes=0
        self.phase=lambda:0
    def _read_io(self,address):
        if address==0xC015:return 0x80 if self.intcxrom else 0
        return super()._read_io(address)
    def _write_io(self,address,value):
        if address in (0xC006,0xC007):self.intcxrom=address==0xC007
        else:super()._write_io(address,value)
    def __getitem__(self,address):
        if isinstance(address,slice):return super().__getitem__(address)
        if address==0xCFFF:self.selected=None;return 0
        if 0xC700<=address<0xC800:
            if self.intcxrom:return 0xAA
            self.selected=7;return self.rom[address-0xC700]
        if address in (0xCFF0,0xCFF1):
            self.guard()
            if address==0xCFF1:return 0x80 if self.at<len(self.response) else 0
            assert self.at<len(self.response),'FIFO underrun'
            return self.response[self.at]
        return super().__getitem__(address)
    def __setitem__(self,address,value):
        if isinstance(address,slice):return super().__setitem__(address,value)
        if address in (0xCFF0,0xCFF1,0xCFF2):
            self.guard()
            if address==0xCFF0:self.incoming.append(value);self.fifo_writes+=1
            elif address==0xCFF2:
                assert self.at<len(self.response),'FIFO pop underrun';self.at+=1
            else:
                assert value==2
                request=bytes(self.incoming);self.incoming=[];self.requests.append(request)
                self.submit(request)
            return
        super().__setitem__(address,value)
    def guard(self):
        assert not self.intcxrom and self.selected==7,'FIFO without slot-7 C8 ownership'
        assert self.cpu.p&4,'FIFO while IRQ enabled'
    def submit(self,data):
        assert data[1:10]==bytes([3,0,0,0,0x80,0,0,0,0]),data
        self.at=0
        if data[0]==0:
            assert len(data)==10;self.statuses+=1
            if self.mode==3 and self.phase()>=2 or self.mode==5 and self.controls:
                self.response=[0x60];return
            status=bytearray(32);status[:4]=b'AMEM';status[4]=2 if self.mode==2 else 1
            status[6]=16;status[7]=1;status[8]=7;status[11]=2;status[13]=0xC0
            status[14]=1 if self.mode==6 else 126;status[15]=1
            self.response=[0,31 if self.mode==9 else 32,0,*status];return
        assert data[0]==4 and len(data)==36,data
        packet=data[10:];assert packet[:8]==bytes([24,0])+b'AMEM'+bytes([1,1])
        assert packet[8:10]==bytes(2) and packet[11]==1 and packet[23:]==bytes(3)
        op,st,sb,sa,dt,db,da,length,value=packet[10],packet[12],packet[13],int.from_bytes(packet[14:16],'little'),packet[16],packet[17],int.from_bytes(packet[18:20],'little'),int.from_bytes(packet[20:22],'little'),packet[22]
        assert op in (1,2) and st in (0,1) and dt in (0,1) and length
        assert not dt or (db>0 and 0x200<=da and da+length<=0xC000),'non-private AUX destination'
        assert op!=1 or not st or (sb>0 and 0x200<=sa and sa+length<=0xC000),'invalid AUX source'
        self.controls.append({'phase':self.phase(),'op':op,'source':[st,sb,sa],'destination':[dt,db,da],'length':length})
        count=8 if self.mode==4 else (0 if self.mode==8 else length)
        src=self.aux[sb] if st else self.main;dst=self.aux[db] if dt else self.main
        if op==1:dst[da:da+count]=bytes(src[sa:sa+count])
        else:dst[da:da+count]=bytes([value])*count
        self.response=[] if self.mode==8 else [0x63 if self.mode==4 else 0]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cc65-home',required=True);a=p.parse_args()
    out,program,labels=build_target('amem',a.cc65_home,['src/memory.c','src/memory_copy.c','src/timing.c','src/timing_gap.c','src/amem.c','tests/amem_target.c'],['src/target/memory.s','src/target/hardware.s','src/target/private_state.s','src/optional/amem_transport.s'],True)
    evidence=[]
    for mode in (0,1,2,3,4,5,6,8,9,11,12):
        model=Controller(mode);run=CpuRun(program,labels,model);run.mode=mode
        model.phase=lambda:run.value('_amem_phase',1) if run.started else 0
        original=bytes(model.aux[0]);run.run(20_000_000)
        assert run.quit and not run.value('_amem_failed'),(mode,run.value('_amem_failed'))
        assert model.intcxrom and model.selected is None,'C8/INTCXROM ownership leaked'
        assert bytes(model.aux[0])==original,'AUX0 was touched by private memory requests'
        if mode==0:
            assert len(model.controls)==12,len(model.controls)
            assert not any(c['phase'] in (5,6) for c in model.controls),'small/overlapping/disabled transfer accelerated'
        elif mode in (1,12):assert not model.requests and not model.fifo_writes,'private command sent to unidentified controller'
        elif mode in (2,3,9,11):assert not model.controls,'unsupported/unavailable probe submitted CONTROL'
        else:assert len(model.controls)==1,'failed or partly executed request replayed'
        evidence.append({'mode':mode,'checks':run.value('_amem_checks'),'instructions':run.steps,'status_requests':model.statuses,'control_requests':model.controls,'intcxrom_restored':model.intcxrom})
        print('AMEM mode',mode,'passed',run.value('_amem_checks'),'checks;',len(model.controls),'CONTROL requests')
    (out/'validation.json').write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':main()
