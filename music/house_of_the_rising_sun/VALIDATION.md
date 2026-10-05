# Blues-rock revision — 2026-10-05

The complete 102.32-second arrangement was compiled and rendered against the
verified Appletini One F1.2.4 source profile. Firmware checkout `24f13df` has
the same pinned audio implementation as profile commit `96fd466`.

## Audio

The preview uses the actual four AY cores and both SSI bus wrappers. SSI is
mirrored for a centered singer; the AY mix uses the default pan, AY8913 levels
and neutral tone controls. Its 48 kHz stereo PCM has 4,911,360 sample frames.

| Measurement | Result |
| --- | ---: |
| Sustained-vowel intervals eligible for pitch analysis | 50.90 s |
| Intervals with detected voiced output | 50.81 s / 99.82% |
| Median absolute pitch error against the score | 4.27 cents |
| 90th percentile absolute pitch error | 12.40 cents |
| Mean absolute pitch error, including outliers | 127.98 cents |
| Median error against the quantized firmware pitch | 0.54 cents |
| Maximum mixed PCM magnitude | 17,695 / 32,768 |
| Samples at either clipping rail | 0 |
| Maximum magnitude in the final 200 ms | 2 / 32,768 |

`verify_render.py` uses unconstrained normalized autocorrelation on the score's
absolute timeline. It measures vowel interiors, excludes consonants and short
transition margins, and reports coverage alongside conditional pitch error.
It checks at least 95% coverage, median error below 20 cents and 90th percentile
below 50 cents, as well as duration, clipping and vocal release. All checks
passed. The high mean includes a small set of large pitch-estimation outliers;
passing the median and percentile thresholds does not validate every frame.

Investigation found 328 of 5,081 detected frames above 100 cents; 323 use `UH1`.
The detector usually selects that vowel's strong third harmonic. At 19.00 s,
the SSI registers encode 198.02 Hz and raw PCM autocorrelation is 0.997 near
198 Hz, versus 0.936 near the selected 594 Hz harmonic. Spectral peaks retain
the expected 198 Hz spacing. No pitch-register mismatch was found across the
5,090 eligible ticks. Several isolated onset frames remain ambiguous. The
reported statistics are unchanged; `build/vocal-pitch-outliers.json` records
the independent evidence and this limitation of the comparison estimator.

The requested stronger accompaniment is encoded as one extra native AY volume
step for every nonzero melodic note and drum hit. The rendered backing's AC RMS
rose by 2.12 dB relative to this revision's initial balance; the
SSI PCM is unchanged. No post-render gain, normalization, reverb or external
audio was added. The final mix is the native saturating sum of both stems.
The AY stem was rerendered after this adjustment; all 3,860 timestamped SSI
writes and the stream timing were verified identical before reusing the full
speech render. The render report records stream and final audio hashes.

These measurements establish output coverage and measured pitch statistics,
not musical quality, lyric intelligibility or resemblance to a human singer.
No human recording was used as a reference. Hardware EQ, warmth and the final
DAC path are outside this preview; set warmth to 0 when comparing with it.

## Stream and playback

Both NTSC and PAL versions are **28,333 bytes** with **9,654 register writes**
in 3,003 timestamped records. Register shadowing suppresses 5,126 redundant
writes. The 86-write peak occurs during initialization. No requested vocal
frame clips the pitch range or shortens the modeled excitation pulse.
The score includes 363 native AY percussion hits.

The assembled 65C02 ProDOS player executed both complete streams in py65,
matching every scheduled register write. The worst complete polling iteration
took 5,275 nominal CPU cycles, below both regional 100 Hz periods. The check
now fails if an iteration reaches its regional period; slot wait states are
not modeled. It also covers bounded loading, load errors, region selection,
replay, stop, quit, overrun muting, and no disk reads during playback.

The SmartPort image's boot blocks, embedded ProDOS, directory and all files
were read back and compared with their sources. Its final SHA-256 is
`e3318d452029e33fce3ee65139f5384d4cabcaa0cf53bf6f3c9496c7d2c28a4d`.

| Stream | SHA-256 |
| --- | --- |
| NTSC | `0dd6af750cc83a5df618ee823909a9155bac40629883490930a31713ff70a895` |
| PAL | `ab4e6ba2a8699f4e59e661d6f0dc2e9fb78ec7856852ff77b7aa456a813944b6` |

The general framework suite ran 101 checks: 92 passed and nine optional model
tests were skipped. The full-render suite separately passed all six checks,
including all four AY targets, pitch, pan, clock cadence, exact stem mixing,
and sample-for-sample equivalence of sparse AY simulation to dense fabric
simulation. The new SSI C++ clock driver also passed exact PCM and model-stat
comparison against the original timed SV driver in both regions, including
live register changes, silence and resets. It evaluates every one of the same
384 fabric cycles per audio sample; only host scheduling and file I/O change.
The existing standalone SSI renderer and fitting API are preserved.

The score regenerates deterministically. Unchanged generated content preserves
file timestamps, avoiding an unnecessary audio render.

No physical Appletini playback, slot-wait-state measurement or complete Apple II
ROM boot was performed. The player emulator stubs ProDOS and VIA timer flags.
The disk is prepared for SmartPort boot; a physical audition is the next check.
