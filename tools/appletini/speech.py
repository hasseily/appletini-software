# SPDX-License-Identifier: GPL-2.0-only
"""Persistent IPC client for the separate GPL3 Appletini speech reference.

The core links no reference synthesis code. All audio is 48kHz signed little
endian stereo; event timestamps are absolute guest ticks. See speech/README.md.
"""
import math
import os
from pathlib import Path
import queue
import shlex
import struct
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / 'speech'


def build_worker():
    """Build the self-contained C++17 executable only when source has changed."""
    binary = ROOT / 'build' / ('ssi263-speech.exe' if os.name == 'nt' else 'ssi263-speech')
    inputs = list(SOURCES.rglob('*.cpp')) + list(SOURCES.rglob('*.h')) + list(SOURCES.rglob('*.inc'))
    if binary.exists() and binary.stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in inputs):
        return binary
    binary.parent.mkdir(parents=True, exist_ok=True)
    compiler = shlex.split(os.environ.get('CXX', 'c++'))
    with tempfile.TemporaryDirectory(prefix='speech-', dir=binary.parent) as temporary:
        output = Path(temporary) / binary.name
        command = compiler + ['-std=c++17', '-O2', str(SOURCES / 'worker.cpp')]
        command += [str(SOURCES / 'reference' / name) for name in
                    ('native_control.cpp', 'native_source.cpp', 'prototype_tract.cpp')]
        command += ['-o', str(output)]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            raise OSError('speech build failed: ' + exc.stderr.decode('utf-8', 'replace')) from exc
        except subprocess.TimeoutExpired as exc:
            raise OSError('speech build timed out') from exc
        output.replace(binary)
    return binary


class SpeechWorker:
    """Mix deterministic SSI audio into native PCM without restarting per block."""
    def __init__(self, *, rate=48000, guest_hz=13_333_333, origin=0, xck_hz=1_015_625):
        if rate != 48000:
            raise ValueError('Appletini speech requires 48000 Hz PCM')
        if not math.isfinite(guest_hz):
            raise ValueError('guest_hz must be finite')
        self.guest_hz = math.floor(guest_hz + 0.5)
        if not 48000 <= self.guest_hz <= 1_000_000_000 or not 1 <= xck_hz <= 10_000_000:
            raise ValueError('speech clock out of range')
        if not isinstance(origin, int) or not 0 <= origin < 2**64:
            raise ValueError('origin must be a uint64 guest tick')
        self.origin, self.frames = origin, 0
        self.pending = []
        self.last_event_tick = origin
        binary = build_worker()
        self.errors = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen([str(binary), '--stream', str(self.guest_hz),
                                             str(xck_hz), str(origin)], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=self.errors)
        except BaseException:
            self.errors.close()
            raise
        self.requests, self.responses = queue.Queue(), queue.Queue()
        self.io_thread = threading.Thread(target=self._io, name='Appletini speech IPC', daemon=True)
        self.io_thread.start()

    def _error(self):
        self.errors.seek(0)
        return self.errors.read(16384).decode('utf-8', 'replace').strip()

    def _read(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            data = self.process.stdout.read(size - len(chunks))
            if not data:
                raise OSError('speech worker stopped: ' + self._error())
            chunks.extend(data)
        return bytes(chunks)

    def _io(self):
        """One persistent I/O thread makes pipe writes and reads timeout-safe."""
        while True:
            request = self.requests.get()
            if request is None:
                return
            payload, expected = request
            try:
                self.process.stdin.write(payload); self.process.stdin.flush()
                magic, length = struct.unpack('<4sI', self._read(8))
                if magic != b'SSO1' or length != expected:
                    raise OSError('invalid speech response')
                self.responses.put(self._read(length))
            except BaseException as exc:
                self.responses.put(exc)

    def render(self, pcm_s16le, events):
        if self.process is None:
            raise ValueError('speech worker is closed')
        if len(pcm_s16le) % 4:
            raise ValueError('PCM must contain whole stereo frames')
        frames = len(pcm_s16le) // 4
        if frames > 480000:
            raise ValueError('speech block exceeds ten seconds')
        incoming = []
        last = self.last_event_tick
        for event in events:
            if len(event) != 4 or any(not isinstance(v, int) for v in event):
                raise ValueError('speech event must be (tick, chip, register, byte)')
            tick, chip, reg, value = event
            if not last <= tick < 2**64 or chip not in (0, 1) or not 0 <= reg <= 9 or not 0 <= value <= 255:
                raise ValueError('invalid or out-of-order speech event')
            # A past event cannot be retroactively applied to PCM already returned.
            boundary = self.origin + (self.frames * self.guest_hz + 47999) // 48000
            if self.frames and tick < boundary:
                raise ValueError('speech event arrived after its PCM sample')
            if len(self.pending) + len(incoming) >= 65536:
                raise ValueError('speech queue exceeds 65536 pending events')
            incoming.append(event); last = tick
        self.pending.extend(incoming)
        self.last_event_tick = last
        if not frames:
            return b''
        boundary = self.origin + ((self.frames + frames) * self.guest_hz + 47999) // 48000
        count = 0
        while count < len(self.pending) and self.pending[count][0] <= boundary:
            count += 1
        if count > 1_000_000:
            raise ValueError('speech block has too many events')
        payload = bytearray(struct.pack('<4sII', b'SSI1', frames, count))
        for event in self.pending[:count]:
            payload.extend(struct.pack('<QBBB5x', *event))
        payload.extend(pcm_s16le)
        self.requests.put((payload, len(pcm_s16le)))
        try:
            result = self.responses.get(timeout=max(10, frames / 48000 * 4))
        except queue.Empty as exc:
            self.close()
            raise OSError('speech worker timed out') from exc
        if isinstance(result, BaseException):
            self.close()
            raise OSError('speech worker failed: ' + str(result)) from result
        del self.pending[:count]
        self.frames += frames
        return result

    def close(self):
        if self.process is None:
            return
        process = self.process
        self.requests.put(None)
        # Terminate before closing the pipes if I/O is stuck: closing a buffered
        # pipe from another thread can otherwise wait forever on its lock.
        self.io_thread.join(timeout=0.1)
        if self.io_thread.is_alive():
            process.terminate()
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        self.io_thread.join(timeout=1)
        process.stdout.close(); self.errors.close()
        self.process = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
