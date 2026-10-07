# Speech registers: why the song uses the physical profile

Every build of this song now uses the song framework's `physical-ssi263`
compiler profile: the standalone disk, the Appletini demo disk and the
framework's own `make streams`. It writes the SSI-263's pitch and filter
registers by the chip's datasheet equations.

Appletini firmware **F1.2.5** replaced the SC-01-derived speech of F1.2.4 with
a native SSI-263 model built from the same datasheet (appletini-one
`docs/SSI263_NATIVE.md`). Appletini and a real Phasor now read these registers
the same way, so one stream serves both. The old `appletini-f1.2.4` profile
matched F1.2.4 only; its streams sound wrong on F1.2.5 and on a real card.

This file records how the old mapping was found to be wrong and how the
physical profile translates the score.

## Recording evidence

The first recording of the song from a real card came from a **PAL enhanced
Apple //e at 1 MHz, with a Phasor and two SSI speech chips**, playing the
F1.2.4-profile stream. It was compared with the F1.2.4 RTL preview mix,
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
comparison. The physical profile therefore keeps the score's amplitude and
AY volume settings and changes only how registers are written; another
recording is needed before choosing a new mix.

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

The [Appletini F1.2.4 filter implementation](https://github.com/hasseily/appletini-one/blob/96fd466076abfbac52d62d47446f67946913e58f/docs/SSI263_FILTER_FREQUENCY.md)
explicitly describes its provisional mapping as a **linear relative tract rate**
of `(128 + FF) / 256`, with 128 preserving its existing digital response. It
uses SC-01-derived coefficients and is not a calibrated SSI-263 analog model.
The same filter byte therefore meant different things on F1.2.4 and on the chip.
F1.2.5 follows the datasheet equation above.

For example, the original verse's FF=116 meant a near-neutral 0.953× tract rate
on F1.2.4. At the assumed PAL effective clock, that byte selects only about
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

The F1.2.4 profile instead quantized against that firmware's 20 kHz glottal
counter. Its inflection values are slightly out of tune on the chip and on F1.2.5.

The physical profile assumes an effective SSI clock equal to the regional AY
clock divided by two: **1,015,625 Hz for PAL**, or **1,020,484 Hz for NTSC**.
“Effective” means after any clock division. F1.2.5's Phasor path divides Q3 by
two the same way. Inverting the pitch equation using the recording and the original
register words gives a median estimate of approximately 1,015,529 Hz, closely
supporting the PAL assumption. The mixed recording does not replace a direct
clock measurement. A known different clock can be supplied to the compiler
with `--ssi-effective-clock-hz`.

## Listening and validation

appletini-one's `scripts/render_ssi263_song.py` renders this song through the
F1.2.5 native SSI model with the framework's AY RTL (see its
`docs/SSI263_SONG_PREVIEW.md`). That preview is a model, not the card's analog
output, and its voice-to-AY balance is not calibrated. Rendering the stream
through the framework's own F1.2.4 RTL would apply the old filter meaning
again, so the framework refuses to do it.

Player and stream checks are in the [validation summary](VALIDATION.md). A
recording from F1.2.5 hardware or a real Phasor is still the test of the sound.
