# Initial validation

Checked on 2026-10-05 against F1.2.4 source profile `96fd466076abfbac52d62d47446f67946913e58f`.
The firmware checkout then advanced to `24f13df`, which only corrected a filter
calibration note; all ten pinned contract-file hashes still matched.

## Automated checks

- 79 Python tests passed with real RTL and model-fitting checks enabled, with
  no skips. After adding measured candidate selection, its seven comparison
  tests and the CLI selection integration test also passed. The latter checks
  that the chosen score, binary stream, WAV and report all agree for both
  acceptance and rejection.
- The RTL checks cover live pitch without phoneme restart, live tract-filter
  changes without pitch drift, stereo routing, CTL muting, regional Q3 timing,
  and bit-identical independently reset A/B/A reference templates.
- The assembled 65C02 player passed py65 MMIO/timing checks, including truncated
  streams, invalid opcodes, ordered speech edges, bounded reads and songs over
  64 KiB. It links to 760 code/data bytes; a representative three-write tick
  with the supplied memory reader took 1,650 CPU cycles in the emulator. That
  excludes Appletini's hardware slot-access slowdown.
- Editable installation and the `song-to-phasor` console entry point passed.

Reproduce the Python checks with audio dependencies, Verilator, make and a C++
compiler installed:

```sh
PHASOR_FIT_RTL=1 PHASOR_FIRMWARE_ROOT=../../../appletini-one \
  PHASOR_RTL_CACHE=.cache python3 -m unittest discover -s tests -v
make -C player check
```

The player check additionally requires ca65, ld65 and py65. A cold model-fitting
check builds its reference bank; this takes minutes rather than unit-test time.

## End-to-end results

The original synthetic source from `examples/make_fixture.py` contains three
vowels, vibrato, silence, a backing tone, and known phone boundaries. The full
`convert --fit --listen` command in the README produced:

| Measurement | Observed result |
|---|---:|
| Source / rendered vocal duration | 2.0 s / 2.0 s |
| Selected vocal mean absolute pitch error | 4.09 cents |
| Voiced-frame recall | 94.64% |
| Selected spectral-envelope RMSE | 6.731 dB |
| Phasor stream | 744 bytes, 280 register writes |
| Redundant register writes removed | 860 |
| Cached analysis + dictionary fit + compile, without final RTL renders | 1.26 s |
| Cold 189-template bank + fitting + two final renders | 243.7 s |

These are observations from this workspace CPU, not speed guarantees or a
real-singer benchmark. The cached timing includes Python startup and imports.
Full RTL rendering is deliberately separate from the normal fast compilation
path. Generated files and banks are ignored build/cache artifacts.

The fitted proposal reduced dictionary loss from 0.57125 to 0.56986, but its
full-vocal spectral error rose from 6.73099 to 6.73689 dB. The comparison gate
correctly kept the baseline; it did not mistake a lower search proxy for a
better final render. Candidate audio and score remain available for review.

An independent synthesis/inversion test used a known RTL vowel at 200 Hz and
FF=96, then fitted a draft starting at FF=128. The fitter recovered the target
tract setting; the full rendered spectral error fell from 5.73837 to 0.0 dB.
That establishes model self-consistency, not a perfect match to a human voice.

## Still unmeasured

No real song, lyric intelligibility, singer similarity, physical SSI-263 analog
response, or Appletini board playback was evaluated. Source separation and lyric
recognition/alignment remain external inputs. The included player is an
integration module, not a bootable ProDOS song application.
