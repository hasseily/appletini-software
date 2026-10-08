"""Public CLI sound captures retain guest timing and debugger chunk boundaries."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
SPEAKER = 'ad30c0a005a2ffcad0fd88d0f84c0020'


class RecordingTests(unittest.TestCase):
    def invoke(self, *args, commands=None):
        result = subprocess.run([str(ROOT / 'emulator' / 'appletini'), *args], cwd=ROOT,
                                input=commands, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def read_wav(self, path):
        with wave.open(str(path), 'rb') as recording:
            self.assertEqual((recording.getnchannels(), recording.getsampwidth(),
                              recording.getframerate()), (2, 2, 48000))
            frames = recording.getnframes()
            pcm = recording.readframes(frames)
        self.assertEqual(len(pcm), frames * 4)
        return frames, pcm

    def test_wav_has_timed_stereo_signal_and_matching_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speaker.wav'
            record, = self.invoke('run', '--hex', SPEAKER, '--frames', '6',
                                  '--wav', str(path), '--no-speech')
            frames, pcm = self.read_wav(path)
            sound = record['state']['audio']
            self.assertEqual(frames, sound['frames'])
            self.assertAlmostEqual(frames, record['state']['modeled_seconds'] * 48000, delta=1)
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), sound['sha256'])
            self.assertEqual(sound['overflow'], 0)
            samples = list(struct.iter_unpack('<hh', pcm))
            self.assertTrue(any(left != 0 for left, _ in samples))
            self.assertTrue(all(left == right for left, right in samples))
            self.assertGreater(max(left for left, _ in samples), min(left for left, _ in samples))

    def test_debug_chunking_does_not_change_sound(self):
        with tempfile.TemporaryDirectory() as directory:
            whole = Path(directory) / 'whole.wav'
            chunked = Path(directory) / 'chunked.wav'
            self.invoke('run', '--hex', SPEAKER, '--steps', '500000',
                        '--wav', str(whole), '--no-speech')
            commands = '\n'.join(json.dumps({'cmd': 'run', 'steps': 5000}) for _ in range(100))
            self.invoke('debug', '--hex', SPEAKER, '--wav', str(chunked), '--no-speech',
                        commands=commands + '\n{"cmd":"quit"}\n')
            self.assertEqual(self.read_wav(whole), self.read_wav(chunked))

    def test_normal_headless_runs_do_not_synthesize_audio(self):
        record, = self.invoke('run', '--hex', SPEAKER, '--steps', '100')
        self.assertNotIn('audio', record['state'])


if __name__ == '__main__':
    unittest.main()
