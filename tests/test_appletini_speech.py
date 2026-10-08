"""SSI protocol and deterministic reference-worker integration, no hardware needed."""
import ctypes as C
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/appletini'))
from speech import SpeechWorker


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        binary = Path(cls.temp.name) / 'speech_state.so'
        subprocess.run(['cc', '-std=c99', '-O2', '-shared', '-fPIC',
                        str(ROOT / 'tools/appletini/speech_state.c'), '-o', str(binary)], check=True)
        cls.lib = lib = C.CDLL(str(binary))
        lib.ap_ssi_new.argtypes = [C.c_uint64, C.c_uint32, C.c_uint64]
        lib.ap_ssi_new.restype = C.c_void_p
        for name, args, result in [
            ('free', [C.c_void_p], None),
            ('write', [C.c_void_p, C.c_uint, C.c_uint, C.c_uint8, C.c_uint64], None),
            ('advance', [C.c_void_p, C.c_uint64], None),
            ('read', [C.c_void_p, C.c_uint, C.c_uint64], C.c_uint8),
            ('irq', [C.c_void_p], C.c_int),
            ('route', [C.c_void_p, C.c_uint, C.c_uint8, C.c_uint8, C.c_uint64], None),
            ('take_ca1', [C.c_void_p, C.c_uint], C.c_int),
            ('reset', [C.c_void_p, C.c_uint, C.c_int, C.c_uint64], None),
        ]:
            function = getattr(lib, 'ap_ssi_' + name)
            function.argtypes, function.restype = args, result

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.state = self.lib.ap_ssi_new(1015625, 1015625, 0)
        self.addCleanup(self.lib.ap_ssi_free, self.state)

    def write(self, reg, value, tick=0, chip=0):
        self.lib.ap_ssi_write(self.state, chip, reg, value, tick)

    def start(self, duration=0xc2, rate=0x80, chip=0):
        self.write(0, duration, chip=chip); self.write(2, rate, chip=chip)
        self.write(3, 0x1f, chip=chip)

    def read(self, tick, chip=0):
        return self.lib.ap_ssi_read(self.state, chip, tick)

    def test_ready_period_ack_and_independent_sockets(self):
        self.lib.ap_ssi_route(self.state, 5, 0, 0, 0)
        self.start()
        self.start(0x82, chip=1)  # twice the duration of socket 0
        self.assertEqual(self.read(32767), 0)
        self.assertEqual(self.read(32768), 0x80)
        self.assertEqual(self.read(32768, 1), 0)
        self.assertEqual(self.lib.ap_ssi_irq(self.state), 1)
        self.write(1, 0x60, 32768)  # acknowledge, do not restart response clock
        self.assertEqual(self.read(32768), 0)
        self.assertEqual(self.lib.ap_ssi_irq(self.state), 0)
        self.assertEqual(self.read(65536), 0x80)
        self.assertEqual(self.read(65536, 1), 0x80)

    def test_frame_mode_and_live_rate_at_slot_reload(self):
        self.start(0x42, 0)
        self.write(2, 0xf0, 2048)
        # Current 4096-tick slot finishes; the remaining 15 reloads take256.
        self.assertEqual(self.read(7935), 0)
        self.assertEqual(self.read(7936), 0x80)

    def test_mockingboard_edges_pcr_and_mode_rerouting(self):
        self.start()
        self.assertEqual(self.read(32768), 0x80)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 1)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 0)
        self.read(65536)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 0)
        self.lib.ap_ssi_route(self.state, 5, 0, 0, 65536)
        self.assertEqual(self.lib.ap_ssi_irq(self.state), 1)
        self.lib.ap_ssi_route(self.state, 0, 1, 0, 65536)
        self.assertEqual(self.lib.ap_ssi_irq(self.state), 0)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 0)
        self.lib.ap_ssi_route(self.state, 5, 0, 0, 65536)
        self.lib.ap_ssi_route(self.state, 0, 0, 0, 65536)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 1)

    def test_dr00_disables_irq_but_keeps_response_function(self):
        self.lib.ap_ssi_route(self.state, 5, 0, 0, 0)
        self.start()
        self.write(3, 0x80, 1); self.write(0, 2, 1); self.write(3, 0x1f, 1)
        self.assertEqual(self.read(131072), 0)
        self.assertEqual(self.read(131073), 0x80)
        self.assertEqual(self.lib.ap_ssi_irq(self.state), 0)

    def test_ap_warm_reset_retains_rate_and_duration(self):
        self.start()
        self.lib.ap_ssi_reset(self.state, 0, 0, 10000)
        self.assertEqual(self.read(100000), 0)
        self.write(3, 0x1f, 100000)
        self.assertEqual(self.read(132767), 0)
        self.assertEqual(self.read(132768), 0x80)

    def test_ack_wins_over_coincident_response_edge(self):
        self.start()
        self.write(1, 0x60, 32768)
        self.assertEqual(self.read(32768), 0)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 0)
        # An earlier edge remains latched for the VIA even after an SSI ACK.
        self.write(1, 0x60, 65537)
        self.assertEqual(self.lib.ap_ssi_take_ca1(self.state, 0), 1)

    def test_guest_tick_conversion_does_not_depend_on_chunking(self):
        states = [self.lib.ap_ssi_new(13333333, 1015625, 17) for _ in range(2)]
        try:
            for s in states:
                for reg, val in [(0, 0xc2), (2, 0x80), (3, 0x1f)]:
                    self.lib.ap_ssi_write(s, 0, reg, val, 17)
            boundary = 17 + (32768 * 13333333 + 1015624) // 1015625
            for tick in range(17, boundary, 71):
                self.lib.ap_ssi_advance(states[0], tick)
            for s in states:
                self.assertEqual(self.lib.ap_ssi_read(s, 0, boundary - 1), 0)
                self.assertEqual(self.lib.ap_ssi_read(s, 0, boundary), 0x80)
        finally:
            for s in states:
                self.lib.ap_ssi_free(s)


class WorkerTests(unittest.TestCase):
    @staticmethod
    def events(origin=0, chip=0):
        return [(origin, chip, reg, value) for reg, value in
                [(0, 0xc2), (1, 0x60), (2, 0x80), (3, 0x1f), (4, 0xe9)]]

    def test_silence_and_native_pcm_pass_through(self):
        pcm = struct.pack('<hhhh', -32768, 32767, -1, 1) * 100
        with SpeechWorker() as w:
            self.assertEqual(w.render(pcm, []), pcm)

    def test_frozen_native_reference_fixture(self):
        # Native host reference 1a3e8d38, PAL1015625, two C2 voices, FF=e9,
        # cold board FF=0, current pitch policy, +2dB, 48000 stereo frames.
        # This catches changes to parameters, sample order and synthesis math.
        with SpeechWorker(guest_hz=1015625) as w:
            pcm = w.render(bytes(48000 * 4), self.events() + self.events(chip=1))
        self.assertEqual(hashlib.sha256(pcm).hexdigest(),
                         '0351e27464c7a2eca80c6c0cdccb01ae03c2a3f60bc53b170808fbc6b562ab4c')

    def test_phoneme_stereo_determinism_and_chunk_independence(self):
        events = self.events(17)
        events += self.events(700017, 1)
        events += [(1800017, 0, 0, 0xc9)]
        frames = 12000
        with SpeechWorker(guest_hz=13333333, origin=17) as w:
            whole = w.render(bytes(frames * 4), events)
        with SpeechWorker(guest_hz=13333333, origin=17) as w:
            # Future events arrive before any PCM and survive arbitrary chunks.
            self.assertEqual(w.render(b'', events), b'')
            pieces = [w.render(bytes(n * 4), []) for n in (1, 137, 3999, 17, 7846)]
            self.assertEqual(whole, b''.join(pieces))
        samples = list(struct.iter_unpack('<hh', whole))
        self.assertTrue(any(left for left, _ in samples))
        self.assertTrue(any(right for _, right in samples))
        self.assertTrue(all(right == 0 for _, right in samples[:2000]))

    def test_boundary_event_can_arrive_in_following_packet(self):
        frames = 7000; tick = (frames * 13333333 + 47999) // 48000
        reset = [(tick, 0, 8, 0)]
        with SpeechWorker() as w:
            whole = w.render(bytes(9000 * 4), self.events() + reset)
        with SpeechWorker() as w:
            first = w.render(bytes(frames * 4), self.events())
            second = w.render(bytes(2000 * 4), reset)
            self.assertEqual(whole, first + second)
            self.assertEqual(second, bytes(len(second)))

    def test_cold_reset_replay_and_dead_worker_failure(self):
        with SpeechWorker(guest_hz=48000, xck_hz=1015625) as w:
            first = w.render(bytes(8000 * 4), self.events())
            # Same oscillator phase at1s gives bit-identical fresh replay.
            w.render(bytes(40000 * 4), [])
            replay = [(48000, 0, 9, 0), (48000, 1, 9, 0)] + self.events(48000)
            self.assertEqual(first, w.render(bytes(8000 * 4), replay))
            w.process.kill(); w.process.wait()
            with self.assertRaises(OSError):
                w.render(bytes(4), [])

    def test_bad_event_and_old_event_are_rejected(self):
        with SpeechWorker() as w:
            with self.assertRaises(ValueError):
                w.render(bytes(4), [(0, 2, 0, 0)])
            w.render(bytes(4), [])
            with self.assertRaises(ValueError):
                w.render(bytes(4), [(0, 0, 0, 0)])

    def test_future_event_queue_is_bounded_and_rejection_is_atomic(self):
        with SpeechWorker() as w:
            with self.assertRaises(ValueError):
                w.render(b'', [(1000, 0, 0, 0)] * 65537)
            self.assertEqual(w.pending, [])
            self.assertEqual(w.last_event_tick, 0)
            self.assertEqual(w.render(bytes(4), []), bytes(4))


if __name__ == '__main__':
    unittest.main()
