#!/usr/bin/env python3
"""Build/run actual audio/input target instructions on a register fixture."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import build
import speech
import music
import json
from emulator import TargetRun
from audio_model import AudioMemory

# tests/audio_songs.json: test_song has two-tick rows. Track a plays C4, a
# rest, E4, then D4, which repeats from the loop position; b repeats G3
# decaying from 12 to its floor of 4; c holds C5. fast_song has one-tick rows.
PERIOD={"C4":239,"D4":213,"E4":190,"G3":319,"C5":119}

def song_states(writes,start):
    """Chip 0 tone periods and volumes after each write, from a start state,
    with the register written."""
    regs=bytearray(start);states=[]
    for when,chip,reg,value in writes:
        if chip!=0:continue
        regs[reg]=value
        states.append((when,reg,[regs[2*v]|(regs[2*v+1]&15)<<8 for v in range(3)],[regs[8+v] for v in range(3)]))
    return states

def check_song(states,native):
    scale=2 if native else 1
    period={name:value*scale for name,value in PERIOD.items()}
    # Voice 0 segments: (period, sounding) changes in order, with times.
    changes=[]
    for when,_,periods,volumes in states:
        sound=(periods[0],volumes[0]!=0)
        if not changes or changes[-1][1]!=sound:changes.append((when,sound))
    notes=[(when,p) for when,(p,on) in changes if on]
    names={value:name for name,value in period.items()}
    played=[names.get(p,p) for _,p in notes]
    assert played[:3]==["C4","E4","D4"],f"song voice 0 played {played[:6]}"
    assert "C4" not in played[1:],"song did not loop to its loop position"
    rest=[when for when,(p,on) in changes if not on and when>notes[0][0]]
    assert rest and rest[0]<notes[1][0],"song rest missing"
    # Rows are two ticks of 10000 device clocks. The first note waits for
    # the start and the first update, so steady intervals are measured: E4
    # two rows after the rest, D4 four rows after E4.
    assert abs((notes[1][0]-rest[0])-40000)<=10000,f"song rest lasted {notes[1][0]-rest[0]} device clocks"
    assert abs((notes[2][0]-notes[1][0])-80000)<=10000,f"song E4 lasted {notes[2][0]-notes[1][0]} device clocks"
    # Voice 1 starts each G3 at 12 and decays one level a tick to its floor
    # of 4: eight ticks. A slow CPU may catch up two steps in one update.
    levels=[(when,volumes[1]) for when,reg,periods,volumes in states if reg==9 and periods[1]==period["G3"]]
    values=[level for _,level in levels]
    assert values[0]==12 and min(values)==4,f"song decay levels {values[:16]}"
    drops=[(a,b) for a,b in zip(values,values[1:]) if a!=b]
    assert all(b<a or b==12 for a,b in drops),f"song decay steps {drops[:12]}"
    # The second note that reaches the floor, clear of the start, from its
    # first decay step to the floor: seven steps. A note's first write waits
    # for its row's update, which takes most of a tick at 1 MHz.
    runs=[i for i in range(len(values)) if values[i]==12 and (i==0 or values[i-1]!=12)]
    full=[i for n,i in enumerate(runs) if 4 in values[i:runs[n+1] if n+1<len(runs) else None]]
    assert len(full)>=2,f"song decay reached its floor {len(full)} times"
    first=next(when for when,level in levels[full[1]:] if level==11)
    floor=next(when for when,level in levels[full[1]:] if level==4)
    assert abs((floor-first)-70000)<=10000,f"song decay took {floor-first} device clocks"
    assert any(periods[2]==period["C5"] and volumes[2]==7 for _,_,periods,volumes in states),"song voice 2 missing"

def compile_target():
    sdk,tools,_=build.installed_tools(None)
    header,_=speech.compile_manifest(json.loads((ROOT/"assets/speech.json").read_text()),"ti_demo_speech")
    (ROOT/"build/audio_speech.h").write_text(header)
    songs=json.loads((ROOT/"tests/audio_songs.json").read_text())
    (ROOT/"build/audio_song.h").write_text("".join(music.compile_song(document,symbol)[0] for symbol,document in songs.items()))
    source=ROOT/"tests/audio_target.c";obj=ROOT/"build/obj/audio_target.o";assembly=obj.with_suffix(".s")
    build.run([tools["cc65"],"-t","none","--cpu","65c02","--standard","c99","-O",
               "-I",sdk/"include","-I","include","-I","src","-I","build",
               "-o",build.rel(assembly),build.rel(source)])
    build.assemble(assembly,obj,sdk,tools)
    build.run([tools["ld65"],"-C","cfg/libtini.cfg","-o","build/audio_target.system",
               "-Ln","build/audio_target.lbl","-m","build/audio_target.map",
               "build/obj/target/startup.o",build.rel(obj),"build/libtini.lib",tools["runtime"]])

def run(mode=0,speed=1,speech_present=True,t2=True):
    target=TargetRun(ROOT/"build/audio_target.system",ROOT/"build/audio_target.lbl")
    fixture=AudioMemory(speed,present=mode!=2,speech=speech_present,t2=t2)
    fixture.native_supported=mode!=3
    fixture.main[:]=target.memory.main;target.memory=fixture;target.cpu.memory=fixture;fixture.cpu=target.cpu
    fixture.keyboard_inject=mode!=6
    cpu=target.cpu;registered=False;entered=False;calls=[];steps=0;irq_count=0
    dealloc_failed=False;retry_at=None;key_sent=False
    quiet_strobes=None;quiet_checked=False;voice_mark=None;voice_checked=False
    song_marks={};song_start=None
    periods_base=0
    envelope_writes=None
    reject_writes={}
    gap_started=None;unrelated_sent=False;unrelated_check=None
    original_zp=bytes(fixture.main[:256]);original_workspace=bytes(fixture.main[0x100:0x180])
    irq=target.labels["_ti_audio_irq"]
    fixture.main[0xF000:0xF00B]=bytes((0x48,0xDA,0x5A,0x20,irq&255,irq>>8,0x7A,0xFA,0x68,0x40,0xEA))
    fixture.main[0xFFFE:]=bytes((0,0xF0))
    while steps<30_000_000:
        if unrelated_check and cpu.pc==0xF006:
            reads,counter=unrelated_check
            assert fixture.audio_reads==reads,'paused receiver accessed slot4 during another device IRQ'
            assert target.word('_ti_clock_counter')==counter,'paused receiver counted disabled T1 flag'
            assert cpu.p&1,'paused receiver claimed another device IRQ'
            unrelated_check=None
        stick=fixture.main[target.labels['_test_stick_phase']]
        fixture.paddle_open=(0,1,2,2)[stick]
        # Phase 3: a stick read inside its no-stick wait must not measure.
        if stick==3 and quiet_strobes is None:quiet_strobes=fixture.paddle_strobes
        elif stick!=3 and quiet_strobes is not None:
            assert fixture.paddle_strobes==quiet_strobes,"waiting stick read strobed the paddles"
            quiet_strobes=None;quiet_checked=True
        address=target.labels['_test_paddle'];fixture.paddle_value=list(fixture.main[address:address+2])
        key_phase=fixture.main[target.labels['_test_key_phase']]
        if key_phase!=fixture.key_phase:fixture.key_phase=key_phase;fixture.key_strobe=key_phase==2
        voice_phase=fixture.main[target.labels['_test_voice_phase']]
        if voice_phase==1 and voice_mark is None:voice_mark=len(fixture.ay_writes)
        elif voice_phase==2 and voice_mark is not None and not voice_checked:
            chips={chip for _,chip,_,_ in fixture.ay_writes[voice_mark:]}
            assert chips=={0},f"three voices updated chips {sorted(chips)}"
            voice_checked=True
        song_phase=fixture.main[target.labels['_test_song_phase']]
        if song_phase and song_phase not in song_marks:
            song_marks[song_phase]=len(fixture.ay_writes)
            if song_phase==1:song_start=bytes(fixture.ay[0])
            elif song_phase==2:check_song(song_states(fixture.ay_writes[song_marks[1]:],song_start),fixture.native)
            elif song_phase==4:
                late=fixture.ay_writes[song_marks[3]:]
                assert not any(chip==0 and reg in (2,3,4,5) for _,chip,reg,_ in late),"unreserved song tracks played"
                assert any(chip==0 and reg==0 for _,chip,reg,_ in late),"first song track silent"
                assert fixture.ay[0][8]==0,"unrepeated song did not end silent"
        gap_phase=fixture.main[target.labels['_test_gap_phase']]
        if gap_phase==1 and gap_started is None:gap_started=fixture.now()
        rejected=fixture.main[target.labels['_test_reject_phase']]
        if rejected in (1,3) and rejected not in reject_writes:
            reject_writes[rejected]=len(fixture.ay_writes)+len(fixture.ssi_writes)
        elif rejected in (2,4) and rejected not in reject_writes:
            assert len(fixture.ay_writes)+len(fixture.ssi_writes)==reject_writes[rejected-1],"rejected reservation wrote audio hardware"
            reject_writes[rejected]=True
        phase=fixture.main[target.labels['_test_envelope_phase']]
        if phase==1 and envelope_writes is None:
            envelope_writes=sum(reg==13 for _,_,reg,_ in fixture.ay_writes)
        elif phase==2 and envelope_writes is not None:
            assert sum(reg==13 for _,_,reg,_ in fixture.ay_writes)==envelope_writes,"speech retriggered AY envelope"
        if mode==6 and retry_at is not None and steps>=retry_at and not key_sent:
            fixture.keyboard=0xC1;key_sent=True
        if cpu.pc==target.labels["_main"] and not entered:
            entered=True;fixture.main[target.labels["_test_mode"]]=mode
            fixture.main[target.labels["_test_no_speech"]]=not speech_present
        if cpu.pc==0xBF00:
            sp=cpu.sp;ret=fixture.main[0x100+((sp+1)&255)]|fixture.main[0x100+((sp+2)&255)]<<8
            command=fixture[ret+1];params=fixture[ret+2]|fixture[ret+3]<<8;calls.append(command)
            if command==0x65:break
            if command==0x40:
                if mode==4:
                    cpu.stPopWord();cpu.pc=ret+4;cpu.a=0x25;cpu.p|=1
                    continue
                assert not registered;registered=True;fixture.main[params+1]=1
                # A later init restarts the device tick count.
                periods_base=fixture.enabled_periods
                assert fixture[params+2]|fixture[params+3]<<8==irq
            elif command==0x41:
                assert registered and not fixture.ier
                if mode in (5,6) and not dealloc_failed:
                    dealloc_failed=True;retry_at=steps+2000
                    cpu.stPopWord();cpu.pc=ret+4;cpu.a=0x53;cpu.p|=1
                    continue
                registered=False
            else:raise AssertionError(f"unexpected MLI ${command:02X}")
            cpu.stPopWord();cpu.pc=ret+4;cpu.a=0;cpu.p&=~1
        elif registered and gap_phase==1 and not unrelated_sent and fixture.now()-gap_started>=20000 and not cpu.p&4:
            unrelated_sent=True;unrelated_check=(fixture.audio_reads,target.word('_ti_clock_counter'))
            cpu.irq();irq_count+=1
        elif registered and fixture.pending() and not cpu.p&4:
            cpu.irq();irq_count+=1
        else:
            assert fixture[cpu.pc]!=0,f"BRK at{cpu.pc:04X}"
            cpu.step()
        steps+=1
    else:raise AssertionError("audio test instruction limit")
    assert target.word("_test_failed")==0,(f"audio target check {target.word('_test_failed')} failed; "
        f"return={target.byte('_test_return')}; joystick={list(fixture.main[target.labels['_joystick']:target.labels['_joystick']+3])}")
    assert not registered and not fixture.ier,"IRQ ownership not released"
    assert bytes(fixture.main[:256])==original_zp,"ZP not restored"
    assert bytes(fixture.main[0x100:0x180])==original_workspace,"ProDOS/trampoline workspace not restored"
    assert not fixture.native,"Phasor entry personality not restored"
    assert all(chip[8:11]==bytes(3) for chip in fixture.ay),"AY output not silent"
    if mode not in (2,4):
        assert calls==([0x40,0x41,0x41,0x65] if mode in (5,6) else
                       [0x40,0x41,0x40,0x41,0x65] if mode in (0,1) else [0x40,0x41,0x65])
        if mode!=6:assert quiet_checked,"no-stick wait was not checked"
        if mode in (0,1):assert voice_checked,"voice count was not checked"
        if mode!=6:assert 4 in song_marks,"song phases were not reached"
        assert fixture.ssi_control&128,"SSI not powered down"
        if mode==6:
            assert key_sent and dealloc_failed,"startup did not wait/retry failed cleanup"
            assert 0xC000 in fixture.io_reads,"startup did not poll for retry key"
        else:
            assert irq_count>4,"real IRQ handler was not executed"
            assert unrelated_sent and unrelated_check is None,'unrelated IRQ gap guard was not exercised'
            assert len(fixture.ay_writes)>50 and len(fixture.ssi_writes)>10
        shape_writes=[value for _,chip,reg,value in fixture.ay_writes if chip==(0 if mode==1 else 2) and reg==13]
        if mode!=6:assert shape_writes.count(9)>=3,"repeated AY envelope triggers were lost"
        address=target.labels['_ti_clock_counter']
        ticks=int.from_bytes(fixture.main[address:address+4],'little')
        expected=fixture.enabled_periods-periods_base
        assert abs(ticks-expected)<=1,f"device tick loss: {ticks} vs {expected} periods"
        if speech_present and mode!=6:
            duration=[value for _,reg,value in fixture.ssi_writes if reg==0]
            assert any(duration[i:i+2]==[10,10] for i in range(len(duration)-1)),"repeated phoneme write lost"
    print(f"audio mode={mode} CPU/devicefactor={speed} speech={speech_present} T2={t2}: "
          f"{target.word('_test_checks')} checks, {irq_count} IRQs, {steps:,} instructions, "
          f"joystick {list(fixture.main[target.labels['_joystick']:target.labels['_joystick']+2])} PASS")

if __name__=="__main__":
    compile_target()
    run();run(mode=1);run(speech_present=False);run(mode=2);run(mode=3);run(mode=4);run(mode=5);run(mode=6);run(mode=1,speed=4)
    # A VIA without a counting T2 selects the exact-window T1C-H paddle path.
    run(t2=False);run(mode=1,speed=4,t2=False)
