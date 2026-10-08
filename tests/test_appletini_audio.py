"""Guest-bus audio tests: actual timestamps, channels, generators, and SSI IRQ."""
import ctypes as C
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/appletini"

class Event(C.Structure):
    _fields_ = [("tick", C.c_uint64), ("chip", C.c_uint8), ("reg", C.c_uint8),
                ("value", C.c_uint8), ("reserved", C.c_uint8 * 5)]

class AudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-C", str(TOOL)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(TOOL / ("build/libappletini." + ("dylib" if sys.platform == "darwin" else "so"))))
        sig = {
            "ap_new": ([C.c_char_p,C.c_char_p,C.c_double,C.c_double,C.c_uint,C.c_uint,C.c_char_p,C.c_size_t], C.c_void_p),
            "ap_free": ([C.c_void_p], None),
            "ap_get": ([C.c_void_p,C.c_char_p], C.c_uint64),
            "ap_set_reg": ([C.c_void_p,C.c_char_p,C.c_uint], C.c_int),
            "ap_bus_read": ([C.c_void_p,C.c_uint], C.c_int),
            "ap_bus_write": ([C.c_void_p,C.c_uint,C.c_uint], C.c_int),
            "ap_write": ([C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t], C.c_int),
            "ap_run": ([C.c_void_p,C.c_uint64,C.c_uint64,C.c_void_p,C.c_uint], C.c_int),
            "ap_audio_enable": ([C.c_void_p,C.c_uint], C.c_int),
            "ap_audio_available": ([C.c_void_p], C.c_size_t),
            "ap_audio_read": ([C.c_void_p,C.c_void_p,C.c_size_t], C.c_size_t),
            "ap_audio_event_read": ([C.c_void_p,C.POINTER(Event),C.c_size_t], C.c_size_t),
            "ap_slot7": ([C.c_void_p,C.c_char_p], C.c_int),
        }
        for name, (args, ret) in sig.items():
            getattr(cls.lib,name).argtypes = args
            getattr(cls.lib,name).restype = ret
    def machine(self, hz=13_000_000):
        error = C.create_string_buffer(256)
        m = self.lib.ap_new(None,None,hz,63.695246,262,1,error,256)
        self.assertTrue(m,error.value)
        self.addCleanup(self.lib.ap_free,m)
        self.assertEqual(self.lib.ap_write(m,0,0,0x200,b"\x80\xfe",2),1)
        self.assertEqual(self.lib.ap_set_reg(m,b"pc",0x200),1)
        return m
    def bw(self,m,addr,value): self.assertEqual(self.lib.ap_bus_write(m,addr,value),1)
    def br(self,m,addr): return self.lib.ap_bus_read(m,addr)
    def run_ticks(self,m,ticks): self.assertEqual(self.lib.ap_run(m,0,ticks,None,0),1)
    def ay(self,m,chip,reg,value,native=False):
        base = (0xc410 if native else 0xc400) if chip < 2 else 0xc480
        self.bw(m,base+2,255); self.bw(m,base+3,255)
        sel = (0x10 if chip & 1 else 8) if native else 0
        self.bw(m,base+1,reg); self.bw(m,base,sel|7)
        self.bw(m,base,sel|4)
        self.bw(m,base+1,value); self.bw(m,base,sel|6)
        self.bw(m,base,sel|4)
    def tone(self,m,chip=0,period=125,native=False):
        for r,v in [(0,period&255),(1,period>>8),(7,0x3e),(8,15)]: self.ay(m,chip,r,v,native)
    def pcm(self,m):
        n = self.lib.ap_audio_available(m)
        data = (C.c_int16*(2*n))()
        self.assertEqual(self.lib.ap_audio_read(m,data,n),n)
        return list(data)
    @staticmethod
    def edges(samples):
        # DC-coupled tone has clear sign changes after its short settling time.
        return sum(a <= 0 < b for a,b in zip(samples,samples[1:]))
    def test_tone_frequency_clock_mode_and_stereo(self):
        counts=[]
        for native in [False,True]:
            m=self.machine(); self.assertEqual(self.lib.ap_audio_enable(m,48000),1)
            if native: self.br(m,0xc0cd)
            self.tone(m,native=native); self.run_ticks(m,1_300_000)
            out=self.pcm(m); left,right=out[0::2],out[1::2]
            self.assertEqual(len(left),4800)
            counts.append(self.edges(left[960:]))
            self.assertGreater(max(right),max(left)*1.6)
            self.assertGreater(max(left)-min(left),2000)
        self.assertTrue(38 <= counts[0] <= 44,counts)
        self.assertTrue(78 <= counts[1] <= 85,counts)
    def test_all_four_chips_and_disabled_outputs(self):
        for chip in range(4):
            m=self.machine(); self.lib.ap_audio_enable(m,48000); self.br(m,0xc0cd)
            self.tone(m,chip,native=True); self.run_ticks(m,130_000)
            out=self.pcm(m)
            self.assertGreater(max(out)-min(out),3000,chip)
        m=self.machine(); self.lib.ap_audio_enable(m,48000)
        self.tone(m); self.ay(m,0,8,0); self.run_ticks(m,130_000)
        self.assertTrue(all(v==0 for v in self.pcm(m)))
    def test_events_inside_frame_and_sample_are_not_lost(self):
        m=self.machine(); self.lib.ap_audio_enable(m,48000)
        # Speaker pulse wholly inside a single PCM sample. Final state alone
        # is silent; integrated timestamps must preserve the narrow pulse.
        self.br(m,0xc03f); self.run_ticks(m,30); self.br(m,0xc031)
        self.run_ticks(m,300)
        out=self.pcm(m)
        self.assertGreater(abs(out[0]),1000)
        self.assertEqual(out[0],out[1])
        # Silence a tone after 1ms, well before a 16ms video frame ends.
        self.tone(m); self.run_ticks(m,13000); self.ay(m,0,8,0)
        self.run_ticks(m,13000); out=self.pcm(m)
        self.assertGreater(max(out)-min(out),1000)
    def test_noise_envelope_and_chunk_independent_replay(self):
        outputs=[]
        for chunks in [1,100]:
            m=self.machine(); self.lib.ap_audio_enable(m,48000)
            for r,v in [(6,7),(7,0x37),(8,16),(11,64),(12,0),(13,10)]: self.ay(m,0,r,v)
            for _ in range(chunks): self.run_ticks(m,390000//chunks)
            outputs.append(self.pcm(m))
        self.assertEqual(outputs[0],outputs[1])
        self.assertGreater(len(set(outputs[0])),200)
        m=self.machine(); self.lib.ap_audio_enable(m,48000)
        for r,v in [(7,63),(8,16),(11,64),(13,0)]: self.ay(m,0,r,v)
        self.run_ticks(m,390000)
        out=self.pcm(m)[0::2]
        self.assertGreater(max(out[:100]),max(out[1000:])+1000)
    def test_supersprite_psg_and_reset(self):
        m=self.machine(); self.lib.ap_slot7(m,b"supersprite")
        self.lib.ap_audio_enable(m,48000)
        for r,v in [(0,125),(1,0),(7,0x3e),(8,15)]:
            self.bw(m,0xc0fe,r); self.bw(m,0xc0fc,v)
        self.run_ticks(m,130000); out=self.pcm(m)
        self.assertEqual(out[::2],out[1::2]); self.assertGreater(max(out),3000)
        self.bw(m,0xc0f7,0); self.run_ticks(m,130000)
        out=self.pcm(m)[::2]
        self.assertEqual(self.edges(out),0)
    def test_ssi_two_sockets_events_and_audio_off_status(self):
        m=self.machine(); self.br(m,0xc0cd)
        for addr in [0xc440,0xc420]:
            self.bw(m,addr+3,0x80); self.bw(m,addr,0xc1)
            self.bw(m,addr+2,0xf0); self.bw(m,addr+3,0)
        self.assertEqual(self.br(m,0xc440)&128,0)
        self.run_ticks(m,60_000)
        self.assertEqual(self.br(m,0xc440)&128,128)
        self.assertEqual(self.br(m,0xc420)&128,128)
        self.assertEqual(self.lib.ap_get(m,b"audio_events"),0)
        self.lib.ap_audio_enable(m,48000)
        self.bw(m,0xc441,7); self.bw(m,0xc426,9)
        self.assertEqual(self.br(m,0xc440)&128,0)
        self.assertEqual(self.br(m,0xc420)&128,128)
        events=(Event*8)(); n=self.lib.ap_audio_event_read(m,events,8)
        self.assertEqual([(events[i].chip,events[i].reg,events[i].value) for i in range(n)],[(1,1,7),(0,6,9)])
        self.assertTrue(all(events[i].tick==self.lib.ap_get(m,b"ticks") for i in range(n)))
    def test_ssi_native_interrupt_and_mockingboard_ca1_latch(self):
        m=self.machine(); self.br(m,0xc0cd)
        self.br(m,0xc083); self.br(m,0xc083)
        self.assertEqual(self.lib.ap_write(m,2,0,0xfffe,b"\x00\x30",2),1)
        # IRQ handler acknowledges SSI primary, then RTI.
        code=b"\xa9\x00\x8d\x41\xc4\x40"
        self.assertEqual(self.lib.ap_write(m,0,0,0x3000,code,len(code)),1)
        self.lib.ap_set_reg(m,b"p",0x20)
        for reg,value in [(3,0x80),(0,0xc1),(2,0xf0),(3,0)]: self.bw(m,0xc440+reg,value)
        self.run_ticks(m,60000)
        self.assertEqual(self.lib.ap_get(m,b"irqs"),1)
        self.assertEqual(self.br(m,0xc440)&128,0)
        # In Mockingboard mode the primary socket drives VIA1 CA1. Its
        # latched IFR survives an SSI acknowledgement until a VIA action.
        m=self.machine(); self.bw(m,0xc48e,0x82)
        for reg,value in [(3,0x80),(0,0xc1),(2,0xf0),(3,0)]: self.bw(m,0xc440+reg,value)
        self.run_ticks(m,60000)
        self.assertEqual(self.br(m,0xc48d),0x82)
        self.bw(m,0xc441,0)
        self.assertEqual(self.br(m,0xc48d),0x82)
        self.br(m,0xc481)
        self.assertEqual(self.br(m,0xc48d),0)

    def test_queue_backpressure_and_speech_event_bounds(self):
        m=self.machine(100000); self.lib.ap_audio_enable(m,8000)
        self.assertEqual(self.lib.ap_run(m,0,500000,None,0),6)
        self.assertLessEqual(self.lib.ap_audio_available(m),8000*4)
        self.assertEqual(self.lib.ap_get(m,b"audio_overflow"),0)
        self.pcm(m); self.run_ticks(m,1000)
        self.lib.ap_audio_enable(m,8000); self.br(m,0xc0cd)
        for i in range(3072): self.bw(m,0xc441,i&255)
        self.assertEqual(self.lib.ap_bus_write(m,0xc441,1),0)
        self.assertEqual(self.lib.ap_get(m,b"audio_events"),3072)
        self.assertEqual(self.lib.ap_get(m,b"audio_overflow"),0)
        events=(Event*4096)(); self.assertEqual(self.lib.ap_audio_event_read(m,events,4096),3072)
        self.bw(m,0xc441,1)

if __name__ == "__main__": unittest.main()
