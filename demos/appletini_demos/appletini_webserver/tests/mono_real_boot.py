#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Boot the shipped disk through Apple ROM, SmartPort ROM and real ProDOS.

Uses the repository's maintained tools/appletini machine and an explicitly
supplied native library/ROM inputs. No MLI call is trapped or mocked. The
negative test changes only the OPEN io_buffer parameter in emulated RAM to
$0400, reproducing the original failure without an archived executable.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from mono_verify import ROOT, labels, save_capture


def mli_site(payload, command, start):
    at=payload.index(bytes((0x20,0,0xBF,command)),start-0x6000)
    return 0x6000+at+6,int.from_bytes(payload[at+4:at+6],'little')


def c_string(machine, address):
    raw=machine.read('main',address,64)
    return raw.split(b'\0',1)[0].decode('ascii')


def stopped(machine,breakpoints,steps=100_000_000):
    result=machine.run(steps=steps,breakpoints=breakpoints,timeout=30)
    assert result['reason']=='breakpoint',result
    return result


def boot(args,cli,negative=False):
    out=args.build.resolve()
    syms=labels(out/'A2MONO.lbl')
    payload=(out/'A2MONO.payload.bin').read_bytes()
    entry=syms['_mono_overlay_load']
    open_return,open_params=mli_site(payload,0xC8,entry)
    read_return,read_params=mli_site(payload,0xCA,open_return)
    settings=cli.parser().parse_args([
        'debug','--boot','--disk',str(out/'A2MONO.po'),
        '--rom',str(args.rom.resolve()),'--slot7-rom',str(args.slot7_rom.resolve()),
        '--slot7-c8-rom',str(args.slot7_c8_rom.resolve()),
        '--profile',args.profile,'--slot2','off','--banks',str(args.banks)])
    machine=cli.Machine(settings)
    try:
        metadata=machine.metadata()
        assert metadata['program']['roms']['firmware_execution']
        assert not metadata['program']['roms']['prodos_mli_traps']
        stopped(machine,[entry])
        address=machine.get('a')|(machine.get('x')<<8)
        assert c_string(machine,address)=='MONO.WEB'
        if negative:
            machine.write('main',open_params+3,b'\0\x04')
        io_buffer=int.from_bytes(machine.read('main',open_params+3,2),'little')
        stopped(machine,[open_return])
        result={'negative_old_io_policy':negative,'io_buffer':hex(io_buffer),
                'open_accumulator':machine.get('a'),'open_carry':machine.get('p')&1,
                'machine':metadata}
        if negative:
            assert machine.get('a')==0x56 and machine.get('p')&1,result
            stopped(machine,[syms['_cgetc']])
            error=machine.read('main',syms['_mono_overlay_error'],1)[0]
            stage=machine.read('main',syms['_mono_overlay_stage'],1)[0]
            assert (stage,error)==(ord('O'),0x56),(stage,error)
            result['reported_error']='O$56'
            return result
        assert io_buffer==0x1C00
        assert machine.get('a')==0 and not machine.get('p')&1,result
        stopped(machine,[read_return])
        assert machine.get('a')==0 and not machine.get('p')&1
        count=int.from_bytes(machine.read('main',read_params+6,2),'little')
        assert count==len((out/'MONO.WEB').read_bytes())
        assert machine.read('main',0x8B00,count)==(out/'MONO.WEB').read_bytes()
        result['web_bytes_read']=count
        sequence=['MONO.WEB']
        web_window=machine.read('main',0x8B00,0x2C00)
        net_overlay=(out/'MONO.NET').exists()
        reads=[{'name':'MONO.WEB','bytes':count}]
        def reach_idle():
            for _ in range(8):
                stopped(machine,[entry,syms['_cgetc']])
                if machine.get('pc')==syms['_cgetc']:
                    return
                address=machine.get('a')|(machine.get('x')<<8)
                name=c_string(machine,address)
                sequence.append(name)
                machine.run(steps=1)
                stopped(machine,[read_return])
                assert machine.get('a')==0 and not machine.get('p')&1
                loaded=int.from_bytes(machine.read('main',read_params+6,2),'little')
                overlay=(out/name).read_bytes()
                assert loaded==len(overlay),(name,loaded,len(overlay))
                assert machine.read('main',0x8B00,loaded)==overlay,name
                reads.append({'name':name,'bytes':loaded})
                machine.run(steps=1)
            raise AssertionError('overlay loop never reached browser input')
        reach_idle()
        result['initial_overlay_sequence']=list(sequence)
        initial=['MONO.WEB','MONO.NET'] if net_overlay else ['MONO.WEB']
        if not args.automatic_images:
            assert sequence==initial,sequence
            if net_overlay:
                assert machine.read('main',0x8B00,0x2C00)==web_window,'RAM restore changed WEB'
                assert machine.read('aux',0x6000,0x2C00)==web_window,'WEB backup changed'
                result['net_restored_web_without_mli']=True
            before=SimpleNamespace(main=bytearray(machine.read('main',0,65536)),
                                   aux=[bytearray(machine.read('aux',0,65536))])
            result['initial_screen_sha256']=save_capture(out/'real-boot-initial.png',before)
            machine.check(machine.lib.ap_input(machine.handle,b'key',ord('i'),0))
            machine.run(steps=1)
            reach_idle()
        home_image=args.home_image or args.automatic_images
        expected=initial+['MONO.GIF','MONO.WEB'] if home_image and args.banks>=4 else initial
        assert sequence==expected,sequence
        if args.banks<4:
            if home_image:
                assert c_string(machine,syms['_mono_media_message']).startswith('Images need ')
            capacity=int.from_bytes(machine.read('main',syms['_mono_document_capacity'],2),'little')
            assert capacity==8192,capacity
            result['small_memory_document_fallback']=True
        result['text_only_home']=not home_image
        result['overlay_sequence']=sequence
        result['overlay_reads']=reads
        snapshot=SimpleNamespace(main=bytearray(machine.read('main',0,65536)),
                                 aux=[bytearray(machine.read('aux',0,65536))])
        result['screen_sha256']=save_capture(out/'real-boot-demo.png',snapshot)
        result['state_at_browser_input']=machine.state()
        # Observe normal program exit reaching the real ProDOS QUIT call.
        quit_return,_=mli_site(payload,0x65,0x6000)
        machine.check(machine.lib.ap_input(machine.handle,b'key',ord('q'),0))
        machine.run(steps=1)
        stopped(machine,[quit_return-6])
        assert machine.read('main',0x407C,1)==b'\0'
        result['quit_call_reached']=True
        return result
    finally:
        machine.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build'/'mono')
    parser.add_argument('--native-library',type=Path,required=True)
    parser.add_argument('--rom',type=Path,required=True)
    parser.add_argument('--slot7-rom',type=Path,required=True)
    parser.add_argument('--slot7-c8-rom',type=Path,required=True)
    parser.add_argument('--profile',choices=('vtw33','turbo-f122'),default='vtw33')
    parser.add_argument('--banks',type=int,default=6)
    parser.add_argument('--automatic-images',action='store_true',help='test an older build that loads images on entry')
    parser.add_argument('--home-image',action='store_true',help='test an older home page containing a sample image')
    args=parser.parse_args()
    front=ROOT.parents[2]/'tools'/'appletini'
    sys.path.insert(0,str(front))
    import cli
    cli.build_library=lambda:args.native_library.resolve()
    result={'real_prodos_kernel':True,'mocked_mli':False,'board_evidence':False,
            'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [args.build/'A2MONO.SYSTEM',args.build/'A2MONO.payload.bin',
                          *sorted(args.build.glob('MONO.*'))] if p.is_file()},
            'disk_sha256':hashlib.sha256((args.build/'A2MONO.po').read_bytes()).hexdigest(),
            'cases':[boot(args,cli,negative=True),boot(args,cli)]}
    (args.build/'real-boot.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
