# Bootable SmartPort demo

`build/RISING.SUN.hdv` is a bootable ProDOS block image for an Appletini
SmartPort hard-disk drive. It contains ProDOS 2.4.3 (from the existing
`music/doom/assets/ProDOS_2_4_3.po` master), `SUN.SYSTEM`, and separately
compiled NTSC/PAL versions of the complete House of the Rising Sun score.
It targets the native Phasor in **slot 4, firmware F1.2.4**, with four AY
chips and both SSI-263s. A 65C02 is required.

Mount the image in a bootable SmartPort drive and boot it. NTSC playback
starts automatically. Press **P** for PAL, **N** for NTSC, **R** to replay,
**Space** to stop, or **Q/Escape** to quit through ProDOS. Changing region
reloads the corresponding stream and starts from the beginning. Set the
firmware's warmth control to **0** for comparison with the neutral preview;
the default warmth value of +8 produces a different sound.

## Build and verify

From this directory, with cc65's `ca65`/`ld65` and Python 3 available:

```sh
make
python3 -m pip install py65
make check
```

The score defaults to `../score.json`; override it with `make SCORE=...`.
The preparation step compiles both regional streams through the shared
framework and refuses any score whose rate is not 100 Hz or whose encoded
size exceeds the demo's 34,816-byte buffer. `check.py` verifies the assembled
SYS program, not a Python reimplementation of the player. Results are written
to `build/validation.json`.

## Loading and timing

The SYS program preloads the complete 28,333-byte regional stream using
ProDOS OPEN, GET_EOF, READ and CLOSE. SmartPort disk speed affects startup
only. Playback and replay read RAM; there is no disk access in a timer
callback and no refill deadline. Oversized, undersized, truncated or
incompatible streams fail with silence.

The program polls VIA1 Timer 1, free-running, with CPU interrupts masked.
It preserves ProDOS's language-card image and IRQ vectors. The 100 Hz timer
latches are 10,203 NTSC / 10,154 PAL: each period is the latch plus two bus
cycles. Integer rounding introduces approximately +16 ppm / -25 ppm period
error, respectively (less than 3 ms over this song). Timer speed is independent
of the accelerated CPU speed. An additional timer expiry while processing a
tick stops playback with error `$F2` instead of silently dropping time.

| Main memory | Use |
| --- | --- |
| `$0080..$0085` | Text and bounded song-reader pointers |
| `$0400..$07FF` | Text page 1 |
| `$1000..$122A` | Player state and one complete staged PHS1 record |
| `$1C00..$1FFF` | ProDOS file buffer |
| `$2000..$27DD` | SYS code and initialized data |
| `$3000..$B7FF` | Bounded song buffer; current song ends at `$9EAD` exclusive |

The end address of the current song is `$3000 + 28333 = $9EAD`. ProDOS's
global page at `$BF00` is never part of the song buffer. The disk paths are
absolute (`/RISING.SUN/SUN.NTSC` and `/RISING.SUN/SUN.PAL`), so keep the
volume name when copying or recreating this image.

## Validation and limits

Both full 102.32-second regional streams passed the 65C02 emulator check:
**9,654 expected register writes each**, in exact order and at their scheduled
ticks, with the expected final silence. The check also covers loader length
bounds, MLI open/short-read errors, invalid headers/rates, timer latch selection,
no disk I/O during playback, replay, stop, quit, and forced overrun muting.
The image's directory, boot blocks, embedded ProDOS and all files were read
back and compared byte for byte.

The worst complete polling iteration is **5,275 nominal 65C02 cycles**,
including the bounded reader and following-record prefetch, at tick 9,933.
That uses 51.9% of the shorter PAL period (10,156 cycles), leaving 4,881
cycles of nominal headroom. It is below either regional 100 Hz period even
at nominal 1 MHz. The check fails if a polling iteration reaches or exceeds
its regional timer period. This uses emulator instruction counts; Appletini
slot wait states are not modeled.
The emulator stubs ProDOS calls and timer flags; it does not boot an Apple II
ROM or model VIA electrical timing. **The image has not been tested on a
physical Appletini.**

Error codes `$01..$06` come from the shared PHS1 player; other ProDOS errors
retain their MLI code. Demo-specific codes are `$F0` invalid file length or
short read, `$F1` rate other than 100 Hz, `$F2` timer processing overrun, and
`$F3` VIA timer latch probe failure.
