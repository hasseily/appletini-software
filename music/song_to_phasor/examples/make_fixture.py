#!/usr/bin/env python3
"""Make a two-second synthetic vowel song for smoke tests, not a human benchmark."""

import argparse
import json
from pathlib import Path
import wave

import numpy as np


def write_wav(path, values, rate):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((np.clip(values, -1, 1) * 32767).astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rate = 16000
    t = np.arange(rate * 2) / rate
    vocal = np.zeros(len(t))
    backing = np.zeros(len(t))
    intervals = [(0.10, 0.65, 14, 164.81, (730, 1090)),
                 (0.70, 1.15, 1, 196.00, (270, 2290)),
                 (1.20, 1.80, 19, 220.00, (300, 870))]
    for start, end, phone, base_pitch, formants in intervals:
        active = (t >= start) & (t < end)
        local_t = t[active] - start
        pitch = base_pitch * 2 ** ((14 * np.sin(2 * np.pi * 5 * local_t)) / 1200)
        phase = np.cumsum(pitch) * 2 * np.pi / rate
        voice = np.zeros(len(phase))
        for harmonic in range(1, 25):
            frequency = base_pitch * harmonic
            shape = .2 + sum(np.exp(-.5 * ((frequency - center) / 140) ** 2) for center in formants)
            voice += (shape / harmonic) * np.sin(phase * harmonic)
        envelope = np.minimum(1, np.minimum(local_t / .02, (end - start - local_t) / .03))
        vocal[active] = .38 * voice / np.max(np.abs(voice)) * envelope
        backing[active] = .10 * np.sin(2 * np.pi * base_pitch / 2 * local_t) * envelope
    write_wav(args.output / "vocals.wav", vocal, rate)
    write_wav(args.output / "backing.wav", backing, rate)
    write_wav(args.output / "song.wav", vocal + backing, rate)
    annotations = [dict(start=start, end=end, phoneme=phone)
                   for start, end, phone, _, _ in intervals]
    (args.output / "phonemes.json").write_text(json.dumps(annotations, indent=2) + "\n")


if __name__ == "__main__":
    main()
