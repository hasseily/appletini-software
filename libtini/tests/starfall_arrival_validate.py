"""Force the Excalibur transition and check the real 65C02 sprite list.

This is a model test with explicit state writes, not board/video evidence.
"""
from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import native_emulator
from apple2_model import read_labels

def main():
    library=native_emulator.build('C:/msys64/ucrt64/bin/gcc.exe')
    sys.path.insert(0,str(native_emulator.FRONT));import cli
    cli.build_library=lambda:library
    labels=read_labels(ROOT/'build/starfall.lbl');rom=ROOT/'build-inputs/native-roms'
    header=(ROOT/'examples/starfall/game.h').read_text()
    defines=dict(re.findall(r'(?m)^#define (SF_\w+) (\d+)$',header))
    fields=re.sub(r'/\*.*?\*/','',header.split('typedef struct sf_game {')[1].split('} sf_game;')[0],flags=re.S)
    offsets={};offset=0
    for decl in fields.split(';'):
        if not decl.strip():continue
        kind,names=decl.strip().split(None,1);size={'uint32_t':4,'uint16_t':2,'uint8_t':1,'int8_t':1}[kind]
        for name in names.split(','):
            match=re.fullmatch(r'(\w+)(?:\[(\w+)\])?',name.strip());assert match,name
            offsets[match[1]]=offset;offset+=size*(int(defines.get(match[2],match[2])) if match[2] else 1)
    records=[]
    for profile in ('vtw33','turbo-f122'):
        args=cli.parser().parse_args(['debug','--boot','--disk',str(ROOT/'build/starfall.po'),'--profile',profile,
          '--rom',str(rom/'Apple2e_Enhanced.rom'),'--slot7-rom',str(rom/'smartport_a2retronet_style_c700.mem'),
          '--slot7-c8-rom',str(rom/'smartport_a2retronet_style_c800.mem'),'--video-rom',str(rom/'apple2e-video.bin')])
        m=cli.Machine(args)
        def number(n):return m.read('main',labels[n],1)[0]
        def run_to(n):
            address=labels[n]
            if m.get('pc')==address:m.run(steps=1)
            r=m.run(frames=600,breakpoints=[address]);assert r['reason']=='breakpoint',r
        def field(n,data):m.write('main',labels['_sf_state']+offsets[n],data)
        try:
            for _ in range(8):
                run_to('_ti_input_poll')
                if number('_sf_stage')==7 and number('_sf_mode')==0:break
            m.check(m.lib.ap_input(m.handle,b'key',ord('P'),0));run_to('_sf_step')
            field('sector',b'\x08');field('sector_clock',(719).to_bytes(2,'little'))
            field('bosses',b'\x01');field('boss',b'\x00');field('boss_phase',b'\x00')
            field('boss_x',b'\x50');field('boss_y',b'\x78');field('part_hp',b'\x14'*3)
            run_to('_ti_scene_draw')
            state=m.read('main',labels['_sf_state'],offset)
            assert state[offsets['boss']]==2 and state[offsets['boss_phase']]==0, list(state[-20:])
            count=number('_ti_scene_count');images=m.read('main',labels['_ti_scene_image'],count)
            assert all(image<38 for image in images),(profile,'uninitialized boss was drawn',list(images))
            run_to('_sf_boss_step');run_to('_ti_scene_draw')
            state=m.read('main',labels['_sf_state'],offset)
            assert state[offsets['boss_phase']]==1 and state[offsets['boss_y']]<32
            records.append({'profile':profile,'phase0_boss_images':0,'entry_y':state[offsets['boss_y']]})
            print('PASS Excalibur arrival',records[-1],flush=True)
        finally:m.close()
    out=ROOT/'build/starfall/arrival';out.mkdir(parents=True,exist_ok=True)
    (out/'validation.json').write_text(json.dumps({'board_evidence':False,'state_mutations':True,'runs':records},indent=2)+'\n')
if __name__=='__main__':main()
