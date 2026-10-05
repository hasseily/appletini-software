# Bootable SmartPort demo

`build/RISING.SUN.hdv` is a bootable ProDOS block image for an Appletini
SmartPort hard-disk drive. It contains ProDOS 2.4.3 (from the existing
`music/doom/assets/ProDOS_2_4_3.po` master), `SUN.SYSTEM`, and separately
compiled NTSC/PAL versions of the complete House of the Rising Sun score.
It targets the native Phasor in **slot 4, firmware F1.2.4**, with four AY
chips and both SSI-263s. A 65C02 is required.

An unenhanced //e with its original 6502 cannot run this build. An original
physical Phasor needs the separate physical profile described below: this
default stream's vocal controls target Appletini's F1.2.4 model. The same vocal is sent to both SSI-263s
without waiting for speech-chip replies, so one fitted SSI-263 should provide
the complete vocal through its output; that configuration still needs a
hardware audition. Two chips center the voice across both speech outputs.

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

## Physical Phasor test disk

The first real Phasor recording exposed a mismatch between Appletini's
provisional filter-frequency mapping and the SSI-263 datasheet. Use this
separate build for a physical card; see the
[diagnosis and remaining calibration work](../PHYSICAL_PHASOR.md).

```sh
make physical check-physical
# Without make:
python3 build_physical.py
python3 check.py --physical
```

The output is `build/physical/RISING.SUN.hdv`, a standalone ProDOS block image
for a bootable SmartPort-compatible device. It targets a **Phasor in slot 4**
on an **enhanced //e with a 65C02 at normal 1 MHz** and starts in **PAL**.
Both regional streams are included: **N** selects NTSC and **P** selects PAL;
replay, stop and quit retain the controls above. The vocal is duplicated on
both SSI sockets. A single fitted chip should provide the complete vocal from
that chip's output, but still needs its own hardware test.

This builder reads the current `../score.json` without regenerating it. Use
`--score PATH` for another score, `CA65`/`LD65` for toolchain paths, or
`--ssi-effective-clock-hz HZ` for a measured effective SSI clock (applied to
both regional exports). Defaults are 1,015,625 Hz PAL / 1,020,484 Hz NTSC.
The builder also creates `build/physical/RISING.SUN-Physical-SSI263.zip` with
the disk, instructions, compiler reports and SHA-256 checksums.
`build/physical/compile.json` records both profiles, clocks and theoretical
quantization statistics; `validation.json` records assembled-player checks.
No firmware render represents the corrected physical sound.

The physical disk keeps the arrangement, amplitude controls and timing.
Only speech pitch and filter mapping change; redundant register writes are
removed after quantization. It leaves the Appletini disk and demo-disk variant
unchanged. The same RAM preload and 100 Hz player are used, with no disk I/O
during playback. Corrected real-hardware audio remains to be recorded.

## Appletini demo-disk variant

`make showcase` (or `python3 build_showcase.py` without make) regenerates the
score and both streams, then builds `build/showcase/SUN.SYSTEM`. Set `CA65`
and `LD65` to explicit assembler/linker paths if needed. The Appletini demo
disk builder runs this helper and installs the SYS program and the existing
`build/SUN.NTSC` / `build/SUN.PAL` files into `/MSDOS/MUSIC`.

The showcase variant uses those absolute song paths. **Q/Escape** silences
all Phasor channels, stops the timer, restores Mockingboard mode, and reloads
`/MSDOS/BASIC.SYSTEM` so its `STARTUP` program returns to the demo menu.
The loader requires the demo master's 10,240-byte BASIC.SYSTEM, checks its
full read and successful close, and sets the ProDOS prefix to `/MSDOS`.
Any failed OPEN, GET_EOF, length, READ, CLOSE, or SET_PREFIX check falls back
to ProDOS QUIT without executing a partial BASIC image. If the master is
updated to a differently sized BASIC.SYSTEM, update `BASIC_SIZE` in `demo.s`.

The return routine and all of its MLI parameter blocks relocate to
`$1400..$14A0` before loading BASIC at `$2000..$47FF`, so the load cannot
overwrite code it is still executing. The showcase SYS file initially
occupies `$2000..$28A8`; its song buffer and ProDOS I/O buffer match the
standalone version below. The linker reserves `$1400..$17FF` for return
code and limits player state to `$1000..$13FF` to prevent overlap.

Run `make check-showcase` with `py65` available to verify both complete
regional streams plus Q/Escape menu returns, short/failed reads, each MLI
failure, invalid BASIC lengths, and safe fallback after the SYS program has
been overwritten. Its report is `build/showcase/validation.json`. The
showcase peak is 5,192 nominal cycles at tick 9,933; the different code
placement changes instruction page crossings. As with the standalone
check, ROM boot, BASIC execution, physical disk I/O and slot wait states
are not emulated.

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
