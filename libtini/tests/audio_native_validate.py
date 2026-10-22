#!/usr/bin/env python3
"""Boot the real ProDOS audio disk on the unchanged native Appletini model.

Requires explicitly installed local ROMs. No ProDOS MLI traps or speech
synthesis worker are used; register handshakes and AY state are observable.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import native_emulator
import disk
from apple2_model import read_labels

class SpeechEvent(C.Structure):
    _fields_=[("tick",C.c_uint64),("chip",C.c_uint8),("reg",C.c_uint8),
              ("value",C.c_uint8),("reserved",C.c_uint8*5)]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc",default="C:/msys64/ucrt64/bin/gcc.exe")
    args=parser.parse_args()
    library=native_emulator.build(args.cc)
    sys.path.insert(0,str(native_emulator.FRONT))
    import cli
    from video import screenshot
    cli.build_library=lambda:library
    output=ROOT/"build/audio_native";output.mkdir(parents=True,exist_ok=True)
    image=output/"audio.po"
    image.write_bytes(disk.build_image((ROOT/"build-inputs/prodos/ProDOS_2_4_3.po").read_bytes(),
                                     (ROOT/"build/audio_demo.system").read_bytes(),"AUDIO.SYSTEM"))
    labels=read_labels(ROOT/"build/audio_demo.lbl")
    evidence={"disk_sha256":native_emulator.digest(image),"board_evidence":False,"runs":[]}
    for profile,personality,via_hz in ((p,c,h) for p in ("vtw33","turbo-f122") for c in (1,2) for h in (0,1020484)):
        rom=ROOT/"build-inputs/native-roms"
        options=cli.parser().parse_args(["debug","--boot","--disk",str(image),"--profile",profile,
                "--rom",str(rom/"Apple2e_Enhanced.rom"),"--slot7-rom",str(rom/"smartport_a2retronet_style_c700.mem"),
                "--slot7-c8-rom",str(rom/"smartport_a2retronet_style_c800.mem"),"--video-rom",str(rom/"apple2e-video.bin")])
        machine=cli.Machine(options)
        events=[]
        def drain():
            available=machine.lib.ap_audio_available(machine.handle)
            if available:
                data=C.create_string_buffer(available*4)
                machine.lib.ap_audio_read(machine.handle,data,available)
            records=(SpeechEvent*4096)()
            count=machine.lib.ap_audio_event_read(machine.handle,records,4096)
            events.extend({"tick":e.tick,"chip":e.chip,"reg":e.reg,"value":e.value} for e in records[:count])
        def run_frames(frames):
            result=None
            while frames:
                amount=min(frames,10);result=machine.run(frames=amount,timeout=30);drain();frames-=amount
                assert result["reason"]=="cycles",result
            return result
        def word32(label):return int.from_bytes(machine.read("main",labels[label],4),"little")
        try:
            program=(ROOT/"build/audio_demo.system").read_bytes()
            for _ in range(8):
                entry=machine.run(frames=600,breakpoints=[0x2000],timeout=30)
                assert entry['reason']=='breakpoint',entry
                if machine.read('main',0x2000,16)==program[:16]:
                    assert machine.read('main',0x2000,len(program))==program
                    machine.run(steps=1);break
                machine.run(steps=1)
            else:raise AssertionError('audio SYS entry was not observed')
            launch=machine.run(frames=600,breakpoints=[labels["_main"]],timeout=30)
            assert launch["reason"]=="breakpoint",launch
            machine.write("main",labels["_demo_config"],bytes((personality,1,1))+via_hz.to_bytes(4,"little"))
            machine.check(machine.lib.ap_audio_enable(machine.handle,8000))
            initialized=machine.run(frames=120,breakpoints=[labels["_ti_clock_start"]],timeout=30);drain()
            assert initialized["reason"]=="breakpoint",initialized
            assert machine.read("main",labels["_ti_audio_native"],1)==bytes((personality==2,)),"native AY probe degraded"
            run_frames(20)
            start_ticks=word32("_ti_clock_counter");start_seconds=machine.state()["modeled_seconds"]
            start_irqs=machine.get("irqs")
            run_frames(60)
            counter_delta=word32("_ti_clock_counter")-start_ticks
            elapsed=machine.state()["modeled_seconds"]-start_seconds
            divisor=int.from_bytes(machine.read("main",labels["_ti_clock_latch"],2),"little")+2
            assert divisor==(via_hz or 1000000)//100,('configured timer divisor',via_hz,divisor)
            model_via_hz=65/(63.695246/1e6)
            expected_rate=model_via_hz/divisor
            assert abs(counter_delta-elapsed*expected_rate)<1.1,(profile,personality,counter_delta,elapsed,expected_rate)
            assert machine.get("irqs")>start_irqs
            ay=machine.card_read("phasor-ay",0,64)
            assert any(ay[c*16+8:c*16+11]!=bytes(3) for c in range(4)),"music not playing"
            machine.check(machine.lib.ap_input(machine.handle,b"key",ord('2'),0))
            run_frames(180)
            machine.check(machine.lib.ap_input(machine.handle,b"key",ord('1'),0))
            run_frames(90)
            screen=output/f"audio-{profile}-{personality}-{via_hz}.png";screenshot(machine,screen)
            phonemes=[event for event in events if event["reg"]==0 and event["value"]!=0xC0]
            assert len(phonemes)>8,(profile,personality,"SSI sequence did not progress",events)
            if personality==2:
                assert sum(e["reg"]==1 for e in events)>8,"native SSI completion IRQ was not acknowledged"
            machine.check(machine.lib.ap_input(machine.handle,b"key",ord('Q'),0))
            stopped=machine.run(frames=120,breakpoints=[labels["_ti_clock_remove"]],timeout=30);drain()
            assert stopped["reason"]=="breakpoint",stopped
            assert not machine.lib.ap_bus_read(machine.handle,0xC48E)&64,"T1 IER still enabled"
            ay=machine.card_read("phasor-ay",0,64)
            assert all(ay[c*16+8:c*16+11]==bytes(3) for c in range(4)),"AY not silent"
            # Run through real DEALLOC_INTERRUPT and real MLI QUIT/Bitsy Bye.
            returned=machine.run(frames=120,timeout=30);drain()
            assert returned["reason"]=="cycles",returned
            for chip in (0,1):
                controls=[e["value"] for e in events if e["chip"]==chip and e["reg"]==3]
                assert controls and controls[-1]&128,"SSI socket not powered down"
            after_irqs=machine.get("irqs");run_frames(30)
            assert machine.get("irqs")==after_irqs,"IRQ continues after shutdown"
            launcher=output/f"return-{profile}-{personality}-{via_hz}.png";screenshot(machine,launcher)
            evidence["runs"].append({"profile":profile,"personality":personality,
                "machine":machine.metadata(),"launch":launch,"initialized":initialized,
                "configured_via_hz":via_hz,"timer_divisor":divisor,"expected_model_tick_rate":expected_rate,
                "counter_delta":counter_delta,"modeled_seconds":elapsed,"phoneme_writes":len(phonemes),
                "ssi_events":events,"shutdown":stopped,"returned":returned,"post_exit_irqs":after_irqs,
                "screen_sha256":native_emulator.digest(screen),"launcher_sha256":native_emulator.digest(launcher)})
            print(f"real ProDOS {profile} personality={personality} via_hz={via_hz}: {counter_delta} ticks/{elapsed:.6f}s, "
                  f"{len(phonemes)} phoneme writes; clean IRQ removal and Bitsy return")
        finally:machine.close()
    (output/"validation.json").write_text(json.dumps(evidence,indent=2)+"\n")

if __name__=="__main__":main()
