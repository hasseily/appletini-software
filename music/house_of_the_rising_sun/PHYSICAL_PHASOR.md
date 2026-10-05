# House of the Rising Sun on a physical Phasor

The first recording from a real Phasor exposed a speech-register mismatch in
the Appletini-targeted song. The voice has much stronger low-frequency energy
and weaker upper speech formants than the RTL preview. Its fundamental pitch
is only slightly flat; an octave error or slow song playback does not explain
the difference.

There is now a separate `physical-ssi263` compiler profile and standalone disk.
It translates pitch and filter controls using the SSI-263 datasheet equations.
The corrected disk still needs a hardware audition. The existing Appletini
preview is not a prediction of how this physical-chip version will sound.

## Recording evidence

The supplied recording came from a **PAL enhanced Apple //e at 1 MHz, with a
Phasor and two SSI speech chips**. It was compared with the existing V2 mix,
isolated RTL speech, accompaniment, and authored score. The original MP3 is not
committed to the repository.

The decoded recording lasts 102.528 seconds; the reference lasts 102.320 seconds.
After allowing for approximately 89 ms of recording lead-in, instrumental
attacks align throughout the song. Local alignment offsets range from 84 to
91 ms, without a substantial accumulating drift. AY bass notes agree with the
reference within the frequency resolution of the measurements.

Across 64 stable voiced windows, the measured fundamental is about **31 cents
flat** relative to the RTL speech, with the middle 80% approximately 24–41 cents
flat. Harmonic spacing supports this interpretation. The more conspicuous
difference is the distribution of energy: for the held AH in “house,” the
recording emphasizes a roughly 153 Hz fundamental, while the RTL voice has
strong upper harmonics around 620, 776, and 1241 Hz.

Measurements across those windows also show substantially less upper-frequency
speech energy in the recording. These compare a mixed recording with an
isolated reference stem, so they are diagnostic evidence, not a calibrated
speech-chip frequency response. The difference appears in both stereo channels
and in sparse musical passages. Instrumental bass harmonics retain much closer
relative levels, making a simple low-pass filter on the entire recording an
insufficient explanation.

The backing is also quieter relative to the voice than in the preview. Absolute
capture gain is unknown, and phoneme-dependent energy changes affect that
comparison. The physical profile therefore retains the score's amplitude and
AY volume settings while correcting register interpretation; another recording
is needed before choosing a new hardware-specific mix.

Decoded peaks are below digital full scale. That rules out full-scale clipping
in the delivered PCM, but does not rule out distortion within the speech chip,
the analog output, or an earlier recording stage. No intelligibility score or
human listening result is inferred from these measurements.

## Why the filter register matters

The [SSI-263A datasheet](https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Data%20Sheet%20v2.pdf)
defines the switched-capacitor filter clock as:

```text
filter_clock = effective_XCK / (2 × (256 − FF))
```

The [SSI-263A Programming Guide](https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Programming%20Guide.pdf),
page 4, uses `$E9` (233) as the default filter value in its example. That is
materially different from treating `$80` (128) as a physical neutral setting.

The pinned [Appletini F1.2.4 filter implementation](https://github.com/hasseily/appletini-one/blob/96fd466076abfbac52d62d47446f67946913e58f/docs/SSI263_FILTER_FREQUENCY.md)
explicitly describes its provisional mapping as a **linear relative tract rate**
of `(128 + FF) / 256`, with 128 preserving its existing digital response. It
uses SC-01-derived coefficients and is not a calibrated SSI-263 analog model.
Consequently, the same filter byte has different meanings in the two targets.

For example, the original verse's FF=116 means a near-neutral 0.953× tract rate
in Appletini. At the assumed PAL effective clock, that byte selects only about
3.63 kHz of filter clock on the physical chip. Copying it directly does not
preserve the intended vocal tract response.

The physical profile treats the score's existing filter field as an authored
brightness control. It requests `20,000 × (128 + authored_filter) / 256` Hz and
chooses the closest available physical divider. This song's PAL stream uses
FF=229–231, including initialization, corresponding to approximately
18.81–20.31 kHz. This is an explicit translation anchored at a nominal 20 kHz
filter clock, **not a measured equivalence between the two synthesizers**.
The programming guide's example is supporting context, not proof that one
fixed FF byte suits every clock and voice.

## Pitch and clock assumption

Physical pitch is compiled from the datasheet relationship:

```text
fundamental = effective_XCK / (8 × (4096 − inflection))
```

The Appletini profile instead quantizes against its modeled 20 kHz glottal
counter. Reusing those words on a physical chip introduces a small tuning
difference even when musical event timing is correct.

The physical profile assumes an effective SSI clock equal to the regional bus
clock: **1,015,625 Hz for PAL**, or **1,020,484 Hz for NTSC**. “Effective” means
after any clock division; this does not assert the board's raw oscillator rate
or wiring. Inverting the pitch equation using the recording and the original
register words gives a median estimate of approximately 1,015,529 Hz, closely
supporting the PAL assumption. The mixed recording does not replace a direct
clock measurement. A known different clock can be supplied to the compiler
with `--ssi-effective-clock-hz`.

## Build and use the physical disk

The ready-to-use [physical test ZIP](RISING.SUN-Physical-SSI263.zip) contains
`RISING.SUN.hdv`, these instructions, compiler reports and SHA-256 checksums.
Extract it, mount the HDV as a bootable SmartPort hard disk, and boot it.

From this song's directory, with the normal player build dependencies installed:

```sh
cd player
make physical check-physical
```

The result is **`player/build/physical/RISING.SUN.hdv`**, relative to the song
directory. It is a separate standalone disk; the existing Appletini build and
demo disk retain their original profile. The builder also writes
`RISING.SUN-Physical-SSI263.zip` beside the HDV. The checked-in ZIP is the
hardware test snapshot; rebuilding does not overwrite it automatically.

The physical disk defaults to **PAL** and includes both regional song streams.
Use **P** for PAL or **N** for NTSC. The player targets a 65C02/enhanced //e with
the Phasor in slot 4, preloads the song into RAM, and performs no disk reads
during playback. SmartPort hard-disk loading assumptions are unchanged.

The composition, event timing, phonemes, vocal amplitudes, and AY arrangement
remain the same. Both SSI outputs receive the complete duplicated vocal. The
disk does not require distinct singers or divide syllables between chips.
A single populated SSI socket should therefore receive the complete line on
its output, but single-chip physical playback has not been verified.

Software checks cover the compiled streams and 65C02 player behavior. They do
not verify physical speech quality, analog levels, or actual card bus timing.
An updated capture from the same hardware is the next validation step. Rendering
the translated stream through the unchanged Appletini RTL would apply the wrong
filter interpretation again, so it cannot provide an honest physical-hardware
audio preview.

## Validation of the corrected export

The framework suite passed 104 tests; 9 optional Appletini RTL tests were
skipped. Those RTL tests cannot establish physical-chip behavior. All 12 new
profile tests passed, including independent pitch/filter arithmetic, unchanged
default stream bytes, control-event preservation and rejection of physical
streams by the firmware preview path when profile metadata is present.

Both complete physical streams passed execution of the assembled 65C02 player:

| Check | PAL | NTSC |
| --- | ---: | ---: |
| Stream bytes | 27,956 | 28,159 |
| Verified register writes | 9,392 | 9,492 |
| Maximum theoretical pitch error | 1.72 cents | 1.58 cents |
| Busiest polling iteration, nominal CPU cycles | 4,879 | 5,309 |
| Available cycles per tick | 10,156 | 10,205 |

Checks cover all scheduled writes, PAL autostart, regional selection, loader
bounds and failures, replay, stop, quit, overrun muting, no playback disk reads,
and byte-for-byte extraction of the disk's boot blocks and files. CPU cycle
counts exclude physical slot wait states. The existing Appletini standalone
and showcase variants also passed; the standalone disk remains byte-identical.

Physical disk SHA-256:
`a2c937afb905d158fca0abf64cfe4114404f401bcd69946db8f4835ecdca062c`.
