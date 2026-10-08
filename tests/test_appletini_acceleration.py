"""Live CPU rate changes preserve the guest device timeline and machine state."""
import ctypes as C
from fractions import Fraction
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/appletini'
RATES = {'mhz1': 3, 'ultrawarp': 40, 'vtw26': 80, 'vtw33': 100}

class AccelerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['make', '-C', str(TOOL)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(TOOL / ('build/libappletini.' + ('dylib' if sys.platform == 'darwin' else 'so'))))
        signatures = {
            'ap_new': ([C.c_char_p,C.c_char_p,C.c_double,C.c_double,C.c_uint,C.c_uint,C.c_char_p,C.c_size_t],C.c_void_p),
            'ap_free': ([C.c_void_p],None),
            'ap_acceleration': ([C.c_void_p,C.c_char_p],C.c_int),
            'ap_error': ([C.c_void_p],C.c_char_p),
            'ap_get': ([C.c_void_p,C.c_char_p],C.c_uint64),
            'ap_set_reg': ([C.c_void_p,C.c_char_p,C.c_uint],C.c_int),
            'ap_write': ([C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t],C.c_int),
            'ap_read': ([C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t],C.c_int),
            'ap_bus_read': ([C.c_void_p,C.c_uint],C.c_int),
            'ap_bus_write': ([C.c_void_p,C.c_uint,C.c_uint],C.c_int),
            'ap_run': ([C.c_void_p,C.c_uint64,C.c_uint64,C.c_void_p,C.c_uint],C.c_int),
            'ap_audio_enable': ([C.c_void_p,C.c_uint],C.c_int),
            'ap_audio_available': ([C.c_void_p],C.c_size_t),
            'ap_audio_read': ([C.c_void_p,C.c_void_p,C.c_size_t],C.c_size_t),
        }
        for name,(args,result) in signatures.items():
            getattr(cls.lib,name).argtypes=args
            getattr(cls.lib,name).restype=result

    def machine(self, hz=40_000_000/3, cost=None):
        error=C.create_string_buffer(256)
        m=self.lib.ap_new(None, str(cost).encode() if cost else None,hz,64,312,1,error,256)
        self.assertTrue(m,error.value)
        self.addCleanup(self.lib.ap_free,m)
        self.assertEqual(self.lib.ap_write(m,0,0,0x200,b'\x80\xfe',2),1)
        self.assertEqual(self.lib.ap_set_reg(m,b'pc',0x200),1)
        return m
    def get(self,m,key): return self.lib.ap_get(m,key.encode())
    def speed(self,m,profile):
        self.assertEqual(self.lib.ap_acceleration(m,profile.encode()),1,self.lib.ap_error(m))
    def bw(self,m,address,value): self.assertEqual(self.lib.ap_bus_write(m,address,value),1)
    def br(self,m,address): return self.lib.ap_bus_read(m,address)
    def steps(self,m,count): self.assertEqual(self.lib.ap_run(m,count,0,None,0),0)
    def ticks(self,m,count): self.assertEqual(self.lib.ap_run(m,0,count,None,0),1)
    def pcm(self,m):
        frames=self.lib.ap_audio_available(m)
        pcm=(C.c_int16*(frames*2))()
        self.assertEqual(self.lib.ap_audio_read(m,pcm,frames),frames)
        return bytes(pcm)

    def test_change_preserves_ram_registers_clock_and_fraction(self):
        m=self.machine(); self.steps(m,3)
        self.assertEqual(self.lib.ap_write(m,0,0,0x500,b'PERSIST',7),1)
        self.lib.ap_set_reg(m,b'a',0x42)
        before={key:self.get(m,key) for key in ('pc','a','x','y','s','p','cycles','ticks','frame_ticks','clock_hz','speech_xck_hz')}
        self.speed(m,'vtw26')
        self.assertEqual({key:self.get(m,key) for key in before},before)
        self.steps(m,3)
        self.assertEqual(self.get(m,'cycles'),18)
        self.assertEqual(self.get(m,'ticks'),13)  # 9 + 4.5, half tick retained.
        self.speed(m,'vtw33'); self.steps(m,5)
        self.assertEqual(self.get(m,'ticks'),19)
        self.speed(m,'mhz1'); self.steps(m,1)
        self.assertEqual(self.get(m,'ticks'),59)
        self.assertEqual(self.get(m,'nominal_cpu_hz'),1_000_000)
        output=C.create_string_buffer(7)
        self.assertEqual(self.lib.ap_read(m,0,0,0x500,output,7),1)
        self.assertEqual(output.raw,b'PERSIST')
        self.assertEqual(self.get(m,'a'),0x42)

    def test_every_launch_preset_switches_with_exact_rational_elapsed_time(self):
        for initial,units in RATES.items():
            m=self.machine(units*1_000_000/3)
            elapsed=Fraction(0)
            for i in range(200):
                selected=list(RATES)[i%4]
                now=self.get(m,'ticks')
                self.speed(m,selected)
                self.assertEqual(self.get(m,'ticks'),now)
                self.steps(m,1)
                elapsed+=Fraction(3*units,RATES[selected])
                self.assertEqual(self.get(m,'ticks'),int(elapsed),(initial,selected,i))
                self.assertEqual(self.get(m,'cycles'),(i+1)*3)

    def test_custom_launch_clock_is_monotonic_and_live_speed_is_bounded(self):
        m=self.machine(13_000_000)
        self.steps(m,7); origin=self.get(m,'ticks')
        self.speed(m,'vtw26'); self.steps(m,1000)
        expected=Fraction(3000*13_000_000*3,80_000_000)
        self.assertLessEqual(abs((self.get(m,'ticks')-origin)-float(expected)),1)
        now=self.get(m,'ticks'); self.speed(m,'mhz1')
        self.assertEqual(self.get(m,'ticks'),now)
        self.steps(m,100)
        self.assertEqual(self.get(m,'ticks')-now,3900)

    def test_cpu_work_changes_but_frame_clock_and_video_phase_do_not(self):
        m=self.machine()
        for profile,units in RATES.items():
            self.speed(m,profile)
            before=self.get(m,'cycles')
            self.ticks(m,360000)
            self.assertEqual(self.get(m,'cycles')-before,360000*units//40)
            self.assertEqual(self.get(m,'ticks')%360000,0)
            self.assertEqual(self.get(m,'frame_ticks'),266240)

    def test_live_speed_keeps_psg_pitch_phase_and_pcm_identical(self):
        captures=[]
        for change in (False,True):
            m=self.machine(); self.lib.ap_audio_enable(m,48000)
            self.bw(m,0xc402,255); self.bw(m,0xc403,255)
            for reg,value in [(0,125),(1,0),(7,0x3e),(8,15)]:
                self.bw(m,0xc401,reg); self.bw(m,0xc400,7); self.bw(m,0xc400,4)
                self.bw(m,0xc401,value); self.bw(m,0xc400,6); self.bw(m,0xc400,4)
            for profile in ('ultrawarp','vtw26','vtw33','mhz1'):
                if change:self.speed(m,profile)
                self.ticks(m,180000)
            captures.append(self.pcm(m))
            self.assertEqual(self.get(m,'audio_origin'),0)
        self.assertEqual(captures[0],captures[1])
        self.assertGreater(len(set(captures[0])),100)

    def test_via_and_ssi_deadlines_survive_change_mid_timer(self):
        machines=[self.machine(),self.machine()]
        for m in machines:
            # VIA0 T1 one-shot: 10000 Apple bus cycles.
            self.bw(m,0xc404,0x10); self.bw(m,0xc405,0x27)
            # Start primary SSI in native mode; duration deadline about4ms.
            self.br(m,0xc0cd)
            for reg,value in [(3,0x80),(0,0xc1),(2,0xf0),(3,0)]:self.bw(m,0xc440+reg,value)
            self.ticks(m,24000)
        self.speed(machines[1],'vtw26')
        for interval in (36000,72000):
            for m in machines:self.ticks(m,interval)
            for address in (0xc440,0xc41d,0xc019):
                self.assertEqual(self.br(machines[0],address),self.br(machines[1],address),hex(address))
        self.assertEqual(self.br(machines[1],0xc440)&128,128)
        self.assertEqual(self.br(machines[1],0xc41d)&64,64)

    def test_rejected_names_and_turbo_switch_leave_machine_unchanged(self):
        m=self.machine(); self.steps(m,7)
        original=[self.get(m,key) for key in ('ticks','cycles','nominal_cpu_hz','clock_scaled')]
        for profile in (None,b'garbage',b'turbo-f122'):
            self.assertEqual(self.lib.ap_acceleration(m,profile),0)
            self.assertTrue(self.lib.ap_error(m))
            self.assertEqual([self.get(m,key) for key in ('ticks','cycles','nominal_cpu_hz','clock_scaled')],original)
        spec=importlib.util.spec_from_file_location('acceleration_costs',ROOT/'demos/doom_gs/tools/a2vm/costs.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            cost=Path(directory)/'cost.txt'; cost.write_text(module.text('f122+nod2+phasor'))
            m=self.machine(cost=cost)
            self.assertEqual(self.lib.ap_acceleration(m,b'ultrawarp'),0)
            self.assertIn(b'restart',self.lib.ap_error(m))
            self.assertEqual(self.get(m,'clock_scaled'),0)

if __name__=='__main__':unittest.main()
