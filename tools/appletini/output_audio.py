# SPDX-License-Identifier: GPL-2.0-only
"""Stream native sound into a WAV, deterministic digest, or browser packet."""
from array import array
import ctypes as C
import hashlib
from pathlib import Path
import sys
import wave


RATE = 48000


class SpeechEvent(C.Structure):
    _fields_ = [('tick', C.c_uint64), ('chip', C.c_uint8), ('reg', C.c_uint8),
                ('value', C.c_uint8), ('reserved', C.c_uint8 * 5)]


class AudioOutput:
    def __init__(self, machine, *, wav_path=None, retain=False, speech=True):
        self.machine = machine
        self.writer = None
        self.worker = None
        self.pending = bytearray()
        self.retain = retain
        self.frames = self.peak = 0
        self.digest = hashlib.sha256()
        self.path = str(Path(wav_path).expanduser().resolve()) if wav_path else None
        machine.check(machine.lib.ap_audio_enable(machine.handle, RATE))
        self.origin = machine.get('audio_origin')
        try:
            if speech:
                from speech import SpeechWorker
                self.worker = SpeechWorker(rate=RATE, guest_hz=machine.get('clock_hz'),
                                           origin=self.origin,
                                           xck_hz=machine.get('speech_xck_hz'))
            if self.path:
                self.writer = wave.open(self.path, 'wb')
                self.writer.setparams((2, 2, RATE, 0, 'NONE', 'not compressed'))
        except BaseException:
            self.close()
            raise

    def drain(self):
        machine = self.machine
        events = []
        event_buffer = (SpeechEvent * 4096)()
        while True:
            count = machine.lib.ap_audio_event_read(machine.handle, event_buffer, len(event_buffer))
            events.extend((e.tick, e.chip, e.reg, e.value) for e in event_buffer[:count])
            if count < len(event_buffer):
                break
        available = machine.lib.ap_audio_available(machine.handle)
        pcm_buffer = (C.c_int16 * (available * 2))()
        count = machine.lib.ap_audio_read(machine.handle, pcm_buffer, available)
        pcm = bytes(pcm_buffer)[:count * 4]
        if not pcm and not events:
            return
        if sys.byteorder != 'little':
            samples = array('h', pcm)
            samples.byteswap()
            pcm = samples.tobytes()
        if self.worker:
            # The persistent worker preserves events beyond this PCM block.
            pcm = self.worker.render(pcm, events)
        if len(pcm) != count * 4:
            raise ValueError('speech worker returned the wrong number of PCM frames')
        if not pcm:
            return
        samples = array('h', pcm)
        if sys.byteorder != 'little':
            samples.byteswap()
        self.peak = max(self.peak, max(map(abs, samples)))
        self.frames += count
        self.digest.update(pcm)
        if self.writer:
            self.writer.writeframesraw(pcm)
        if self.retain:
            if len(self.pending) + len(pcm) > RATE * 4:
                raise ValueError('browser audio consumer fell more than one second behind')
            self.pending.extend(pcm)

    def take(self):
        pcm = bytes(self.pending)
        self.pending.clear()
        return pcm

    def state(self):
        return {'sample_rate': RATE, 'channels': 2, 'format': 's16le',
                'frames': self.frames, 'seconds': self.frames / RATE,
                'peak': self.peak, 'sha256': self.digest.hexdigest(),
                'speech': self.worker is not None, 'wav': self.path,
                'overflow': self.machine.get('audio_overflow')}

    def close(self):
        if self.writer:
            self.writer.close()
            self.writer = None
        if self.worker:
            self.worker.close()
            self.worker = None
