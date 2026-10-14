"""Run the assembled 6502 app and real slot ROM against an AGLY FIFO model.

This models the ARM reply/application boundary, not the physical card or HDMI.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import struct
import sys
import unittest
import zlib
from pathlib import Path

from py65.devices.mpu6502 import MPU

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import assets
import build
import prodos

APPLETINI=Path(__file__).resolve().parents[4]/'appletini-one'


def load_mem(path: Path) -> bytes:
    return bytes(int(token,16) for token in path.read_text().split())


class MachineMemory:
    def __init__(self, *, missing=False, old=False, busy=False, unavailable=False,
                 fail_write=0, stuck=False, fail_restore=False, bad_status=False):
        self.ram=bytearray(65536)
        self.ram[0xC700:0xC800]=load_mem(APPLETINI/'hdl/apple/smartport_a2retronet_style_c700.mem')
        self.ram[0xC800:0xD000]=load_mem(APPLETINI/'hdl/apple/smartport_a2retronet_style_c800.mem')
        program=(ROOT/'build/GLYPH.SYSTEM').read_bytes()
        self.ram[0x2000:0x2000+len(program)]=program
        self.ram[0xFF58]=0x60             # ROM's known RTS entry
        if missing:
            self.ram[0xC70B]^=1
        self.old,self.busy,self.unavailable=old,busy,unavailable
        self.fail_write,self.stuck,self.fail_restore=fail_write,stuck,fail_restore
        self.bad_status=bad_status
        self.input=bytearray()
        self.output=bytearray()
        self.requests=[]
        self.controls=[]
        self.status_calls=0
        self.txid=0
        self.upload=bytearray(4096)
        self.coverage=set()
        self.active=None
        self.pending=None
        self.pending_restore=False
        self.countdown=0
        self.generation=0
        self.last_error=0
        self.last_operation=0
        self.keyboard=0
        self.vbl_reads=0
        self.fifo_reads=0
        self.quit_at_chunk=0

    def __getitem__(self,address):
        if isinstance(address,slice):
            return self.ram[address]
        if address==0xC000:
            return self.keyboard
        if address==0xC010:
            self.keyboard=0
            return 0
        if address==0xC019:
            self.vbl_reads+=1
            return 0x80 if self.vbl_reads%2 else 0
        if address==0xCFF1:
            return 0x80                  # response READY
        if address==0xCFF0:
            self.fifo_reads+=1
            if not self.output:
                raise AssertionError('slot ROM read an empty response FIFO')
            return self.output[0]
        return self.ram[address]

    def __setitem__(self,address,value):
        if address==0xC010:
            self.keyboard=0
        elif address==0xCFF0:
            self.input.append(value)
        elif address==0xCFF1:
            assert value==2, f'not a SmartPort command: {value}'
            self.dispatch()
        elif address==0xCFF2:
            assert self.output, 'slot ROM popped an empty response FIFO'
            del self.output[0]
        elif 0xC000<=address<0xD000:
            pass                        # softswitch/ROM banks have no RAM
        else:
            self.ram[address]=value

    def apply_pending(self):
        if self.pending is not None or self.pending_restore:
            if self.stuck:
                return
            self.countdown-=1
            if self.countdown<=0:
                self.active=self.pending
                self.pending=None
                self.pending_restore=False
                self.generation+=1

    def status(self):
        self.status_calls+=1
        self.apply_pending()
        flags=(0 if self.unavailable else 1) | (2 if self.active is not None else 0)
        flags |= 4 if self.pending is not None or self.pending_restore else 0
        flags |= 8 if self.txid or self.busy else 0
        packet=bytearray(32)
        packet[:4]=b'AGLX' if self.bad_status else b'AGLY'
        struct.pack_into('<BBBBHHHBBIHHII',packet,4,
                         1,0,16,0,flags,4096,512,self.last_error,self.last_operation,
                         self.txid,len(self.coverage),0,self.generation,0)
        return bytes(packet)

    def dispatch(self):
        request=bytes(self.input)
        self.input.clear()
        self.requests.append(request)
        assert len(request)>=10
        command,params=request[0],request[1:10]
        assert params[0]==3 and params[1]==0 and params[4]==0x81
        if command==0:
            assert len(request)==10
            if self.old:
                self.output=bytearray([0x21])
            else:
                payload=self.status()
                self.output=bytearray(b'\0'+struct.pack('<H',len(payload))+payload)
            return
        assert command==4
        payload_length=struct.unpack_from('<H',request,10)[0]
        assert payload_length+12==len(request), 'CONTROL length excludes its u16'
        payload=request[12:]
        self.controls.append(payload)
        self.output=bytearray([self.control(payload)])

    def control(self,payload):
        assert len(payload)>=16
        magic,major,op,flags,reserved,txid,offset,count=struct.unpack_from('<4sBBBBIHH',payload)
        assert magic==b'AGLY' and major==1 and flags==reserved==0
        self.last_operation=op
        code=0
        if op==1:
            assert len(payload)==16 and txid and offset==count==0
            assert self.txid==0
            self.txid=txid
            self.coverage.clear()
        elif op==2:
            assert self.txid==txid and count==512 and count+16==len(payload)
            assert offset%512==0 and offset+count<=4096
            if self.fail_write and offset//512+1==self.fail_write:
                code=0x63
            else:
                self.upload[offset:offset+count]=payload[16:]
                self.coverage.update(range(offset,offset+count))
            if self.quit_at_chunk and offset//512+1==self.quit_at_chunk:
                self.keyboard=ord('Q')|128
        elif op==3:
            assert len(payload)==20 and offset==count==0 and txid==self.txid
            assert len(self.coverage)==4096
            assert struct.unpack_from('<I',payload,16)[0]==zlib.crc32(self.upload)
            self.pending=bytes(self.upload)
            self.txid=0
            self.countdown=3
        elif op==4:
            assert len(payload)==16 and txid==self.txid and offset==count==0
            self.txid=0
            self.coverage.clear()
        elif op==5:
            assert len(payload)==16 and txid==offset==count==0 and self.txid==0
            if self.fail_restore:
                code=0x66
            else:
                self.pending_restore=True
                self.countdown=3
        else:
            raise AssertionError(f'unknown operation {op}')
        self.last_error=code
        return code


def labels():
    text=(ROOT/'build/labels.txt').read_text()
    return {name:int(address,16) for name,address in
            re.findall(r'^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)',text,re.MULTILINE)}


class Runner:
    def __init__(self,**options):
        self.memory=MachineMemory(**options)
        self.cpu=MPU(memory=self.memory,pc=0x2000)
        self.symbols=labels()

    def until(self,label,limit=2_000_000):
        target=self.symbols[label] if isinstance(label,str) else label
        for _ in range(limit):
            if self.cpu.pc==target:
                return
            if self.cpu.pc==0xBF00:
                raise AssertionError('program quit before expected state')
            self.cpu.step()
        raise AssertionError(f'6502 timed out at ${self.cpu.pc:04X}, waiting {label}')

    def key(self,key):
        self.memory.keyboard=ord(key)|128
        self.cpu.step()                    # leave main_loop before awaiting it
        self.until('main_loop')

    def screen(self):
        return bytes(self.memory.ram[0x400+(y&7)*128+(y//8)*40+x]
                     for y in range(24) for x in range(40))


class DemoTests(unittest.TestCase):
    def test_real_rom_upload_and_scene_keys(self):
        run=Runner()
        run.until('main_loop')
        self.assertEqual(run.memory.active,assets.make_rom(0))
        self.assertEqual(run.screen()[120:840],assets.frame(0,0))
        self.assertEqual([p[5] for p in run.memory.controls], [1]+[2]*8+[3])
        self.assertGreaterEqual(run.memory.status_calls,5)
        self.assertGreater(run.memory.fifo_reads,0)
        for scene,key in ((1,'2'),(2,'3'),(0,'1')):
            run.key(key)
            self.assertEqual(run.memory.active,assets.make_rom(scene))
            self.assertEqual(run.screen()[120:840],assets.frame(scene,0))
            assets.render(run.memory.active,run.screen(),3).save(ROOT/'build'/f'cpu-scene{scene}.png')
        self.assertEqual(run.memory.generation,4)
        run.memory.keyboard=ord('Q')|128
        run.cpu.step()
        run.until(0xBF00)
        self.assertIsNone(run.memory.active)
        self.assertEqual(run.memory.controls[-1][5],5)
        self.assertEqual(run.memory.generation,5)

    def test_pause_resume_and_auto_scene(self):
        run=Runner()
        run.until('main_loop')
        before=run.screen()[120:840]
        run.key(' ')
        for _ in range(3):
            run.cpu.step(); run.until('main_loop')
        self.assertEqual(run.screen()[120:840],before)
        self.assertEqual(run.memory.ram[run.symbols['paused']],1)
        run.key(' ')
        run.cpu.step(); run.until('main_loop')
        self.assertEqual(run.screen()[120:840],assets.frame(0,1))
        run.memory.ram[run.symbols['dwell']]=179
        run.cpu.step(); run.until('main_loop')
        self.assertEqual(run.memory.active,assets.make_rom(1))
        self.assertEqual(run.memory.ram[run.symbols['scene']],1)

    def test_old_firmware_and_missing_card_have_no_controls(self):
        for option in ('old','missing','unavailable','busy','bad_status'):
            with self.subTest(option=option):
                run=Runner(**{option:True})
                run.until('wait_exit')
                self.assertFalse(run.memory.controls)
                if option=='missing':
                    self.assertFalse(run.memory.requests)
                if option=='old':
                    self.assertIn(b'FIRMWARE NEEDS THE AGLY',bytes(v&127 for v in run.screen()))

    def test_chunk_failure_aborts_only_own_transaction(self):
        run=Runner(fail_write=3)
        run.until('wait_exit')
        self.assertEqual([p[5] for p in run.memory.controls],[1,2,2,2,4])
        self.assertEqual(run.memory.txid,0)
        self.assertIsNone(run.memory.active)
        self.assertEqual(run.memory.ram[run.symbols['last_error']],0x63)

    def test_restore_error_is_visible(self):
        run=Runner(fail_restore=True)
        run.until('main_loop')
        run.memory.keyboard=ord('Q')|128
        run.cpu.step(); run.until('wait_exit')
        message=bytes(v&127 for v in run.screen())
        self.assertIn(b'ROM RESTORE FAILED. USE VIDEO MENU.',message)
        self.assertEqual(run.memory.ram[run.symbols['last_error']],0x66)

    def test_pending_timeout_reports_restore_failure(self):
        run=Runner(stuck=True,fail_restore=True)
        run.until('wait_exit',limit=6_000_000)
        self.assertGreaterEqual(run.memory.status_calls,4096)
        self.assertEqual(run.memory.controls[-1][5],5)
        self.assertIn(b'ROM RESTORE FAILED',bytes(v&127 for v in run.screen()))

    def test_quit_received_during_upload_completes_then_restores(self):
        run=Runner()
        run.memory.quit_at_chunk=3
        run.until(0xBF00)
        self.assertEqual([p[5] for p in run.memory.controls],[1]+[2]*8+[3,5])
        self.assertIsNone(run.memory.active)
        self.assertIsNone(run.memory.pending)
        self.assertEqual(run.memory.generation,2)

    def test_rom_layout_crc_and_original_font(self):
        for scene in range(3):
            rom=assets.make_rom(scene)
            self.assertEqual(len(rom),4096)
            self.assertEqual(rom[:2048],rom[2048:])
            self.assertEqual(bytes(b^255 for b in rom[0xC1*8:0xC2*8]),
                             bytes(assets.font_rows('A',scene)))
            self.assertEqual(bytes(b^255 for b in rom[0x80*8:0x81*8]),
                             bytes(assets.tiles(scene)[0]))
            self.assertEqual((ROOT/'build'/f'font{scene}.rom').read_bytes(),rom)
            frames=[assets.frame(scene,tick) for tick in range(8)]
            self.assertGreater(len(set(frames)),1)
            self.assertTrue(all(len(frame)==720 for frame in frames))

    def test_disk_boot_kernel_and_payload(self):
        disk=ROOT/'dist/Glyph-Lab.hdv'
        manifest=json.loads((ROOT/'dist/manifest.json').read_text())
        master=Path(manifest['inputs']['prodos_master']['path'])
        self.assertEqual(disk.stat().st_size,800*1024)
        self.assertEqual(disk.read_bytes()[:1024],master.read_bytes()[:1024])
        self.assertEqual(prodos.read_file(disk,'PRODOS'),prodos.read_file(master,'PRODOS'))
        self.assertEqual(prodos.read_file(disk,'GLYPH.SYSTEM'),(ROOT/'build/GLYPH.SYSTEM').read_bytes())
        self.assertEqual(build.sha(disk.read_bytes()),manifest['outputs']['Glyph-Lab.hdv']['sha256'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--appletini-root',type=Path,default=APPLETINI)
    parser.add_argument('--skip-build',action='store_true')
    args,rest=parser.parse_known_args()
    APPLETINI=args.appletini_root.resolve()
    if not args.skip_build:
        build.build(APPLETINI,'acme')
    unittest.main(argv=[sys.argv[0]]+rest)
