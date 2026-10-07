# Song to Phasor

A vocal-first conversion framework for Appletini One **F1.2.4**. It takes a song
or aligned stems, estimates singing and accompaniment, compiles a native Phasor
register stream, renders the SSI-263 voices through the actual firmware RTL,
and compares that result with the source vocal. A cached bank of RTL sounds
lets the fitter choose closer phonemes and filter-frequency settings.

This is an experimental framework. Automatic phoneme selection matches acoustic
shape; it does not recognize lyrics. Supply timed phonemes for intelligible
words, and review the rendered audio. The included fixture tests the machinery,
not human singing quality. No real-song quality or physical-board validation
is claimed.

## Target

- Firmware source: [`codex/turbo-paging-dma`, `96fd466`](https://github.com/hasseily/appletini-one/commit/96fd466076abfbac52d62d47446f67946913e58f).
- Native Phasor in slot 4, Mockingboard-only disabled, enhanced Apple //e.
- Four AY chips / twelve tone voices and two SSI-263 sockets. A single vocal
  is copied to both hard-panned SSI sockets by default, for a centered voice.
  Two explicit vocal tracks use the sockets independently.
- Both PAL and NTSC clock profiles. A shared **100 Hz** song clock is the
  default; it is independent of the video frame rate.

The target is pinned by hashes of the speech RTL, bus wrapper, ROM, AY, card,
and version header. `check-firmware`, fitting and rendering reject a changed
contract even if it still calls itself F1.2.4. Compilation can run from the
frozen profile without a firmware checkout and records that distinction.

F1.2.4's register 4 is a provisional digital tract-frequency control. `128` is
neutral, `0` is 0.5 times the tract rate, and `255` is about 1.496 times. It
changes the vowel's spectral shape without changing the source pitch. This is
not a calibrated analog SSI-263 model; see the firmware's
[`SSI263_FILTER_FREQUENCY.md`](https://github.com/hasseily/appletini-one/blob/96fd466076abfbac52d62d47446f67946913e58f/docs/SSI263_FILTER_FREQUENCY.md).

## Install and try

From this folder, Python 3.10+ can compile a score with only the standard library:

```sh
python3 -m phasor compile examples/phrase.json --out build/phrase
python3 -m phasor inspect build/phrase/song.phs
```

Audio analysis and comparison need NumPy and SciPy. Compressed audio also needs
`ffmpeg` on PATH. Actual speech rendering needs Verilator and a C++ build
toolchain (`make`, compiler). Install Verilator through your OS package manager;
the Python `verilator` package's `verilator-cli` entry point is also supported.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[audio]'
python3 -m phasor check-firmware ../../../appletini-one
```

The editable-score example includes a pitch slide, vibrato and three vowel
shapes. Render its SSI vocal independently of the backing:

```sh
python3 -m phasor render build/phrase/song.phs build/phrase/vocals.wav \
  --firmware-root ../../../appletini-one
```

For a complete stereo preview, add `--full`. This also renders the four real
AY cores and applies the native Phasor pan/gain mix. Keep separate stems when
checking vocal pitch; the accompaniment would confuse that measurement.
The full renderer uses a faster C++ clock driver for SSI, evaluating all 384
fabric cycles per sample. Its PCM and model statistics are checked against the
original timed SV driver, which remains available for speech fitting.

```sh
python3 -m phasor render build/phrase/song.phs build/phrase/mix.wav --full \
  --vocal-output build/phrase/vocals.wav --backing-output build/phrase/backing.wav \
  --firmware-root ../../../appletini-one
```

The first complete arranged song is
[`House of the Rising Sun`](../house_of_the_rising_sun/README.md), with an
editable score, timed SSI lyrics, audio preview instructions and a ProDOS demo.

For a full reproducible smoke test, create an original synthetic vowel song:

```sh
python3 examples/make_fixture.py build/fixture
python3 -m phasor convert build/fixture/song.wav \
  --vocals build/fixture/vocals.wav \
  --accompaniment build/fixture/backing.wav \
  --annotations build/fixture/phonemes.json \
  --fit --listen --out build/converted \
  --firmware-root ../../../appletini-one
```

Use the same command with your recording and stems. Stems must start at the
song's time zero and use the same timeline. Without stems, both draft analyses
use the mix, and the report says so. This project does not yet separate sources
or transcribe/force-align lyrics; Demucs, a singing transcription model, a forced
aligner or hand annotation can supply those inputs externally. None is called
or downloaded implicitly.

The first `--fit` run builds a reference bank; later runs reuse it. Default
filter candidates are `96 128 160`; `--filters 128` is cheaper, and any selected
byte values in `0..255` can be tested (up to eight per bank). `--annotations` automatically locks the
phonemes during fitting. `--lock-phonemes` also does that for an editable score.
`--transpose -12` lowers both voice and backing by an octave; comparisons with
the original still include that deliberate pitch difference.

The default bank contains 189 independently reset phoneme/filter combinations,
about 42 seconds of model audio. Its first build takes minutes on a CPU. Bank
matching and compilation then reuse that work; full RTL rendering remains an
optional, slower validation step. Banks use the source's rounded median pitch;
`--bank-pitch-hz 200` reuses one pitch bank across recordings, at the cost of a
less representative harmonic pattern for singers far from that pitch.
The fitter currently accepts one vocal track
and one isolated reference stem. Compile/render can handle two SSI tracks, but
fitting a duet requires separate stem work before combining the tracks.

## Convert, listen, compare, revise

1. **Analyze.** Local FFT-based pitch tracking estimates fundamental frequency,
   periodicity, loudness and broad phoneme shape. Backing analysis picks strong
   tones, suppresses harmonics and keeps stable AY voice assignments. Results
   remain editable; confidence is periodicity, not transcription certainty.
2. **Fit.** Render reference phonemes with the pinned SSI RTL, extract broad
   spectral envelopes, and compare each source frame against that bank. A
   transition penalty discourages frame-to-frame chatter. Keep measured vocal
   pitch and timing separate from phoneme/tract fitting. Expand held controls
   during the search so the whole vowel is examined, then store changes only.
3. **Compile.** Quantize pitch against the actual firmware counter, emit
   phoneme starts and live pitch/amplitude/filter changes, interleave backing,
   and remove unchanged register writes. No FFT, transcription or search runs
   on the Apple II.
4. **Render and compare.** `--listen` produces baseline and fitted vocal WAVs
   when `--fit` is also used. The renderer instantiates both real SSI bus
   wrappers, including mode initialization and live register behavior. It
   excludes the AY chips and final board mixer so the vocal comparison is
   isolated. Its compressed fabric schedule retains the audio cadence and
   regional Q3 clock; it does not model CPU bus-write latency.
   With `--fit --listen`, keep the baseline unless the candidate improves full
   rendered spectral error by at least 0.05 dB without reducing vocal coverage,
   pitch accuracy or timing beyond the small tolerances recorded in the report.
   The selected score, stream and `vocals.rtl.wav` always refer to the same choice.
5. **Review.** Listen to source, baseline and candidate. Correct phonemes or
   timing in the score, alter filter candidates or transpose, and compile
   again. Better spectral distance alone does not establish intelligible words
   or the identity of the singer.

Separate commands support iteration:

```sh
python3 -m phasor analyze song.flac --vocals vocals.wav --out build/draft
python3 -m phasor fit build/draft/analysis.score.json vocals.wav \
  --out build/fitted --filters 96 128 160
python3 -m phasor compile build/fitted/score.json --out build/final --clock pal
python3 -m phasor render build/final/song.phs build/final/vocals.wav --clock pal
python3 -m phasor compare vocals.wav build/final/vocals.wav \
  --output build/final/comparison.json
```

`comparison.json` reports pitch error in cents **with voicing coverage**, bounded
timing lag, loudness-envelope agreement, and spectral-envelope distance. Missing
or silent vocal output cannot earn a good pitch result just by avoiding notes.
Undefined measurements are JSON `null`. Alignment reports the delay rather than
silently stretching time. Comparing against a full mix is less meaningful than
comparing against an isolated stem.

## Files and interchange

`convert` writes `analysis.score.json`, editable `score.json`, `song.phs`, readable
`events.json` and `report.json`. `--fit` adds `fit.json`; `--listen` adds
`vocals.rtl.wav`, `render.json` and `comparison.json`, plus `baseline.rtl.wav`
and `candidate.rtl.wav` when fitting. `candidate.score.json` preserves the fitted
proposal even when the measured selection keeps the baseline. `--fit` without
`--listen` uses the dictionary proposal without this final comparison gate.
Reports include source verification, stream hash, size, register
write counts, quantization errors and elapsed conversion time.

The version-1 score is JSON. Times are absolute integer ticks, not cumulative
floating-point durations. See [`examples/phrase.json`](examples/phrase.json).

| Field | Meaning |
|---|---|
| `tick_hz`, `duration_ticks` | Shared song clock (25..400 Hz) and terminal tick |
| `voices[].chip` | SSI socket 0 or 1; one track per socket |
| `voices[].frames[].tick` | Strictly increasing time; values hold until replaced |
| `phoneme` | SSI code 0..63, **not** an SC-01 phone number |
| `pitch_hz`, `amplitude` | Positive finite fundamental frequency; linear SSI amplitude 0..15 |
| `filter`, `articulation` | Optional tract code 0..255 (default 128), articulation 0..7 (default 5) |
| `rate`, `duration` | Optional SSI RATE 0..15 (default 8), DR 0..3 (default 0) |
| `retrigger` | Explicitly restart a repeated phoneme for a new syllable; default false |
| `notes[]` | `start_tick`, `end_tick`, fractional MIDI `midi`, `velocity` 0..15, `voice` 0..11 |
| `percussion[]` | Optional hits: `start_tick`, `end_tick`, `kind` (`kick`, `snare`, `hat`), `velocity` 0..15 |

A voice frame is a complete control state. Amplitude zero is silence; terminal
frames at `duration_ticks` must be silent. Adjacent notes may share an AY voice,
overlapping notes may not. AY channels are grouped three per chip; chip order
is VIA0-primary, VIA1-primary, VIA0-secondary, VIA1-secondary.

When `percussion` is nonempty, AY chip 3 (voices 9–11) is reserved for drums;
pitched notes on those voices are rejected. The kick sweeps down in pitch, while
snare and hi-hat use the chip's shared noise generator at a fixed period of 8.
Each has a short software volume envelope. Different drum kinds may overlap;
overlapping hits of the same kind are rejected. Hits must end within the song.
Tone notes and drums use ordinary register writes, without recorded samples
or the AY hardware envelope generator.

Phoneme annotations are a separate ordered, nonoverlapping JSON array in seconds:

```json
[{"start": 0.10, "end": 0.65, "phoneme": 14},
 {"start": 0.70, "end": 1.15, "phoneme": 1}]
```

Annotation gaps explicitly mute the vocal. `hardware.SSI_PHONEMES` maps familiar
SSI labels to codes. Short consonants should get their own intervals; stretched
notes should mainly extend vowels. Same-phone pitch updates preserve the running
phoneme; use `retrigger` at an actual repeated syllable.

## Playback and efficiency

[`player/`](player/) contains a ca65 65C02 callback-stream player, its integration
contract and emulator tests. A caller supplies buffered bytes and the timer;
this is not yet a bootable song browser or ProDOS streaming application. The
driver initializes native mode, validates records before MMIO writes, preserves
ordered speech control edges, and silences output on stream errors.

The PHS1 format is independent of the older Doom `.AY` format:

- Header `<4sHHII`: `PHS1`, tick rate, reserved flags=0, duration ticks, record count.
- Each record `<HB`: delta ticks (0..65535), write count, followed by `(opcode,value)`
  byte pairs. Empty records extend long waits.
- Opcode high nibble selects AY 0..3 or SSI 4..5; low nibble selects register.
  AY registers 0..13 and SSI 0..4 are valid.
- Same-tick records preserve order. At most 255 writes and 64 records may occur
  at one timestamp. The final timestamp equals the declared duration.

The regional clock is in `report.json`, not in the PHS1 header. Keep the report
with the stream and pass the same `--clock` when rendering; the playback caller
must provide the header's tick rate using the regional VIA clock.

Host analysis uses bounded transform batches. The firmware build and reference
banks are cached by source/model configuration. Register shadowing and long
waits make storage and replay proportional to changes, not raw audio samples.
The generated report gives peak writes per tick; measure that burst on the
target board, including the configured slot-access slowdown. There is no
hardware realtime-performance claim from host conversion timings.

SSI pitch is quantized by the firmware's `20,000 / floor((4096-I)*5/32)` counter
(minimum period 1). The compiler searches its actual pitches, rather than the
ideal analog equation. High singing notes have coarse pitch steps and a
truncated glottal pulse; range representability does not imply useful timbre.
Each SSI has one phoneme tract, so it cannot reproduce arbitrary singer tone,
breath, chords or full mixed audio faithfully.

## Checks

See [initial validation results](VALIDATION.md) for measured behavior, performance
and the boundaries of the current evidence.

```sh
make test
make example
make firmware
make rtl-test
make fit-test
make player
```

Normal tests cover pitch/register packing, mode handshakes, contours without
phoneme restarts, malformed scores/streams, audio analysis and comparison.
RTL tests require Verilator and `APPLETINI_ROOT` (default sibling checkout).
`fit-test` recovers a known filter setting from a rendered vowel and requires
the resulting full-vocal spectral error to improve; it builds the reference
bank if absent. Set `PHASOR_RTL_CACHE` to share an existing CLI cache.
See the player README for ca65/ld65 and py65 tests. Generated banks, WAVs and
build outputs remain local and ignored.

The next quality milestones need actual vocal recordings: evaluate aligned
lyrics and sustained-vowel passages; tune consonant onset/duration and tract
search; add automatic separation/alignment adapters; then audition and measure
complete songs on F1.2.4 hardware.
