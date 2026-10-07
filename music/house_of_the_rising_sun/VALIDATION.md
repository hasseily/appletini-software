# Validation — F1.2.5 build, 2026-10-07

The blues-rock revision (102.32 seconds) is now compiled with the song
framework's `physical-ssi263` profile for every build: the standalone disk and
the Appletini demo disk. Appletini F1.2.5's native SSI-263 model and a real
Phasor both follow the SSI-263 datasheet, which this profile writes for. The
score itself did not change. [Register notes](SSI263_MAPPING.md).

## Streams

| | PAL | NTSC |
| --- | ---: | ---: |
| Stream bytes | 27,956 | 28,159 |
| Timestamped records | 3,052 | 3,053 |
| Register writes | 9,392 | 9,492 |
| Redundant writes removed | 5,388 | 5,288 |
| Effective SSI clock | 1,015,625 Hz | 1,020,484 Hz |
| SSI filter registers (FF) | 229–231 | 229–230 |
| Filter clock range | 18.81–20.31 kHz | 18.90–19.62 kHz |
| Mean / maximum pitch quantization error | 0.62 / 1.72 cents | 0.57 / 1.58 cents |

No vocal frame is outside the SSI pitch register range. The 86-write peak
occurs during initialization. The score includes 363 native AY percussion
hits. Pitch errors are against the datasheet equation; they exclude the real
clock's tolerance and analog effects.

| Stream | SHA-256 |
| --- | --- |
| PAL | `7abf6a7863eb0e7198f3dfee3d144a22f982a28273b178b16a4ceaf9273fdef1` |
| NTSC | `8361c3649c541c38c96f0e27cee16426ff649abe4f648c6fcc2237d1373f4092` |

## Player

The assembled 65C02 ProDOS player executed both complete streams in py65,
matching every scheduled register write. It starts in PAL and switches to NTSC
on **N**. The worst complete polling iteration took 5,309 nominal CPU cycles
(NTSC; PAL 4,879), below both regional 100 Hz periods; the check fails if an
iteration reaches its period. Slot wait states are not modeled. The check also
covers bounded loading, load errors, region selection, replay, stop, quit,
overrun muting, and no disk reads during playback.

The demo-disk variant passed the same checks plus its menu-return paths; its
peak is 5,268 cycles (NTSC; PAL 4,838).

The SmartPort image's boot blocks, embedded ProDOS, directory and all files
were read back and compared with their sources. `player/build/RISING.SUN.hdv`
is 143,360 bytes with SHA-256
`80137f3a58a5ccc95ad2b5a62c803d8bfb4511eced4c8c77f25a69cc86a8c339`.

The framework suite ran 114 tests: 105 passed and 9 optional F1.2.4 RTL tests
were skipped.

## Not checked

No audio was rendered here. The earlier listening preview and its pitch
measurements came from the F1.2.4 speech RTL and no longer describe what the
song sounds like. appletini-one's `scripts/render_ssi263_song.py` renders the
song through the F1.2.5 model; a recording from F1.2.5 hardware or a real
Phasor is still the real test.

No physical playback, slot-wait-state measurement or complete Apple II ROM
boot was performed. The player emulator stubs ProDOS and VIA timer flags.
