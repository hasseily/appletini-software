# Native PHS1 player

This ca65 module plays the framework's compiled register stream on the slot 4
Phasor in Appletini One (firmware **F1.2.5** or later) or on a real Phasor card.
The player only replays register writes; the compiler profile decides what the
speech registers mean. It drives all four AY chips and both
SSI-263s, preserving the order of every write, including repeated SSI writes and
CONTROL transitions. Song analysis and phoneme fitting happen on the host;
the 65C02 only reads timestamped register commands.

Build with cc65's `ca65` and `ld65`:

```sh
make
python3 -m pip install py65  # optional emulator checks
make check
```

`build/phasor.bin` is a linked integration/test artifact loaded at `$2000`, with
entry addresses in `build/phasor.lbl`. It is **not a ProDOS application**. Link
`phasor.o` into your program using its normal CODE, RODATA and BSS segments;
optionally link `memory_reader.o`, which also needs two zero-page bytes. The
core uses no zero page and buffers a single complete record in 510 bytes.
The checks execute the assembled machine code and inspect the six-store AY
transactions and SSI writes, including malformed/truncated streams, time zero,
future events, byte-for-byte SSI ordering, and streams larger than 64 KiB.

## Calling convention

All public routines clobber A, X, Y and flags. Decimal mode must be clear.
The player is not reentrant: mask your timer interrupt while starting/stopping,
and prevent other code from using the card's sound ports while it plays.

1. Call `phs_init` once. It selects native mode with reads of `$C0C8` then
   `$C0C5`, sets both VIA data ports to outputs, resets the AYs, disables both
   VIA interrupt-enable registers and mutes both speech chips. It clears the
   reader pointer. Install/configure your timer **after** this initialization.
2. Set the two-byte `phs_reader` function pointer to your stream reader and
   position that reader at the first byte of a PHS1 file.
3. Call `phs_start`. C clear means the header was accepted; C set means failure,
   with its code in A and `phs_error`. All time-zero records are applied before
   it returns. This may also complete a zero-duration stream successfully.
4. Read the little-endian `phs_tick_hz` and call `phs_tick` exactly that many
   times per second. Its first call advances time from 0 to 1; it never repeats
   time-zero commands. Configure a real timer/divider for this rate. Calling a
   100 Hz stream once per video frame would change both duration and singing.
5. Read `phs_playing` to detect completion, or call `phs_stop` for immediate
   silence. A decode failure also mutes the four AYs and holds both SSI CONTROL
   pins high with zero amplitude, clearing speech IRQ without a mode-latch edge.
   `phs_tick` returns C set on a new failure. Inspect `phs_error` after completion;
   later idle ticks simply return C clear. A successful start clears old errors.

`phs_duration` and `phs_elapsed` are four-byte little-endian tick counts. At the
declared duration, the player applies any commands due there and then mutes the
card. Ending the record list early holds the last chip state until this point;
the compiler supplies explicit final silence. No SSI readiness polling or SSI
interrupt service is required: the compiler programs mode 2, disables SSI IRQ,
and schedules register writes itself. `phs_init` does not choose speech mode.

## Reader callback

The driver invokes `JMP (phs_reader)` via a JSR trampoline. Return with `RTS`:

| Result | Meaning |
| --- | --- |
| C clear, A = byte | One byte was read; advance your stream position |
| C set | EOF, read failure, or buffer underrun; playback stops and mutes |

The callback may clobber X/Y. Preserve the stack balance and leave decimal mode
clear. It must bound its own reads and return promptly: do not call ProDOS or
wait for disk I/O from an interrupt. For long songs, refill a separate ring
buffer in foreground code and expose only ready bytes to this callback. There
is no 64 KiB song-length limit, because the driver only holds a single record.
The driver preloads the next complete record, so budget room for up to 513 bytes
of lookahead, plus a 16-byte header at startup. Truncation or an invalid command
is detected before **any command in that record** is applied; preceding records
may already have played. Trailing bytes after the declared record count are
not read. Buffer underruns are fatal in this minimal player; refill safely and
restart rather than silently moving subsequent vocal events off the beat.

For short songs in main RAM, `memory_reader.s` provides `phs_memory_read`.
Set the zero-page word `phs_mem_pos` to the first byte and the BSS word
`phs_mem_end` to the exclusive end address. The reader refuses addresses outside
`$0200..$BFFF` and refuses reading at/after the end. Keep the song clear of the
program, its BSS, and OS workspace; make sure the expected main-memory mapping
remains active during playback.

```asm
        .import phs_init, phs_start, phs_tick, phs_reader
        .import phs_memory_read, phs_mem_end
        .importzp phs_mem_pos
        ; Call with your timer IRQ masked; then configure/enable that timer.
        cld
        jsr phs_init
        lda #<song
        sta phs_mem_pos
        lda #>song
        sta phs_mem_pos+1
        lda #<song_end
        sta phs_mem_end
        lda #>song_end
        sta phs_mem_end+1
        lda #<phs_memory_read
        sta phs_reader
        lda #>phs_memory_read
        sta phs_reader+1
        jsr phs_start
        ; Check carry, then clock phs_tick at phs_tick_hz.
```

## Hardware order and bounded work

| Stream target | Hardware |
| --- | --- |
| 0 | VIA0 primary AY, `$C410` ORB / `$C41F` ORA_NH |
| 1 | VIA1 primary AY, `$C480` ORB / `$C48F` ORA_NH |
| 2 | VIA0 secondary AY |
| 3 | VIA1 secondary AY |
| 4 | Left SSI at `$C420..$C424` |
| 5 | Right SSI at `$C440..$C444` |

Primary AY select/idle is `$0C`, secondary is `$14`. Every AY command explicitly
latches its register with `base | 3`, returns to idle, writes with `base | 2`,
and returns to idle. ORA without handshake preserves SSI CA1 state. The native
target numbering follows firmware hardware order; the older `music/doom`
player uses a different software voice layout.

The stream uses `<4sHHII` header fields: `PHS1`, nonzero tick rate, zero flags,
duration, record count; each record is `<HB` delta ticks/count and then count
opcode/value pairs. Opcode high nibble is target and low nibble is register:
AY 0–13 or SSI 0–4. Zero-count waits and zero-delta records are legal. A full
255-command record fits in the bounded staging buffer. Cumulative time is
checked against duration and 32-bit overflow.

The driver refuses more than **64 records or 255 writes at one timestamp**.
These are corruption guards, not a CPU timing guarantee. Record decoding,
callback execution and bus writes all consume timer budget, including reading
the following record. The compiler should emit only changed ordinary registers
while preserving SSI strobes; profile dense passages on the intended CPU clock.
`make check` reports a representative three-write tick cost with the supplied
bounded memory reader. This module does not install a timer, prefetch from disk,
or change CPU speed. Those remain application integration work.

| `phs_error` | Meaning |
| --- | --- |
| 0 | No error |
| 1 | Invalid magic, zero tick rate, or unsupported flags |
| 2 | Reader reported EOF/failure/underrun |
| 3 | Invalid target/register |
| 4 | Record time overflow or beyond duration |
| 5 | Per-timestamp record/write limit exceeded |
| 6 | Reader pointer was zero |
