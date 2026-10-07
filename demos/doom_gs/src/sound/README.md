# src/sound: the 65C02 music and effects players for the Phasor

The music player and the sound-effects player of DOOM GS, in 65C02
assembly for ca65 (cc65 2.18). All the code is original; no upstream
source was used. The song file, the music player's steps ("The player"),
the effect scripts and the effects player are described in
[`tools/sound/README.md`](../../tools/sound/README.md). The comments in
`player.s` still name `Player` methods of a host model of the player
that is no longer in the tree.

| File | What it is |
| --- | --- |
| `player.s` | The music player: the interrupt's work (`snd_tick`), the stream interpreter, the envelopes, the levels, the register shadows and the burst to the chips, song start and stop, the ring and its refill |
| `probe.s` | `snd_probe`: music (the card switched to native mode: 4 chips) or no music (a Mockingboard, or the Phasor locked to Mockingboard mode: 2 chips); boot code, not in the card |
| `fx.s` | The effects player on chip 3 (`fx_step`, `fx_burst`, `fx_service`, `fx_song`, `fx_init`, ...); linked by `src/native/play.mk` and the `m11` fragments, not by this Makefile |
| `sound.inc` | Addresses, the player's state constants, the song file's |
| `Makefile` | Builds `player.o`, `probe.o` and `tables.inc` into `build/sound65` |

```
make -C src/sound          # build/sound65/player.o, probe.o, tables.inc
make -C src/sound clean
```

`build/sound65/tables.inc` is generated from
[`tools/sound/tables.py`](../../tools/sound/tables.py) by
[`tools/sound/tables65.py`](../../tools/sound/tables65.py): the voices of
the layout, the registers the music owns, the period tables of native
mode for PAL and NTSC, the bend magnitudes, the level table, and chip 3's
voices and separations for `fx.s`.

There is one voice layout, native12: 7 melodic and 2 drum voices on the 4
AY chips of the card in native mode, chip 3's 3 voices for the effects
(`tools/sound/README.md`, "Voice layout"). A card that cannot switch to
native mode gets no music (below, "No music").

## How it runs

| Entry | Where it runs | What it does |
| --- | --- | --- |
| `snd_probe` (`probe.s`) | once, at boot, before `snd_init` | Asks for native mode (`$C0C8`, `$C0C5`), resets VIA-A's chips, writes R0 of chip 0 ($55) then of chip 1 ($AA), reads chip 0's R0 back: $55 is 4 chips, carry clear and A = `SND_MUSIC` (0); $AA is 2 chips, carry set and A = `SND_NO_MUSIC` (1), the second write having reached chip 0 on a card that ignores the mode switch and the chip selects (The Bilestoad's method). Leaves VIA-A's chips reset |
| `snd_init` | once, after `snd_probe`, whatever it answered | The card's native mode (`$C0C8`, `$C0C5`), VIA interrupts off, ports as outputs, both AYs of each VIA reset (ORB 0, then idle), the player stopped (so `snd_tick` returns at once until a `snd_start`) |
| `snd_start` | main loop (in the game through `fx_song`) | Plays the song file at `snd_song_bank:snd_song_addr` (a RamWorks bank, `$0200-$BFFF`) with `snd_song_flags` (bit 0 loop, bit 7 NTSC) and `snd_song_matt` (music attenuation, 0.5 dB steps). Reads the header through a read window, refuses a file of another version or layout, too many envelopes (20) or drums (23), or a loop offset outside the stream (carry set, `snd_error` 1-4); copies the envelope and drum tables into the card; selects the PAL or NTSC period table and tempo; resets the voices; fills the ring; writes the first burst (R0-R12 of every chip). The interrupt ignores the player until it is done |
| `snd_tick` | the VBL interrupt (`pl_vbl`, `src/native/pl_irq.s`), between `fx_step` and `fx_burst` | The pending releases, the ticks due (the 16-bit tempo fraction), each tick's commands and envelopes, then the levels (`compose`), the registers that changed (`flush`) and one burst |
| `snd_refill` | main loop, as often as it likes | When half the ring or more is free, copies the stream into it, 512 bytes at a time |
| `snd_stop` | main loop | The next interrupt silences every music voice, writes that burst, and the player stops |

**The routines.** `snd_tick` runs `commands` (with `note_on`,
`set_tone`, `drum_start`), `envelopes`, `compose` and `flush`;
`bend_period` is a 12 x 8 bit shift-and-add multiply into 3 bytes, 1024
added, a shift by 11. `burst` writes each chip's list
with a 41-cycle loop a register (ORA without handshake, latch, idle,
value, write, idle). `flush` walks the owned registers of the chips in
descending order into per-chip lists that the burst walks backwards, so
the chips, and each chip's registers, go out in ascending order. R13
goes out again after a drum's retrigger even when equal.

**The IRQ contract.** The interrupt reads and writes only its zero page,
the stack, the main language card and I/O: the player's code, tables,
state, ring and write lists are all in the card. It makes no mapping
switch and no RamWorks access, so RAMRD, RAMWRT and `$C073` may be
anything when it comes, including in the middle of a refill's read
window. The game's form of the contract (zero page `$D8-$FF`,
`$E000-$FFFF`, `$C0A0-$C0AF`, `$C400-$C4FF`, ALTZP off) is
`docs/MEMORY_MAP.md` rule 2.

**The ring.** 1,024 bytes in the card, page aligned, and a 3-byte mirror
of its first bytes after its end, so that a command that wraps reads its
operands with one `(rp),y`. The main loop fills it a page at a time: a
page is published by incrementing one byte (`wpos_hi`) once all its bytes
are in, so the interrupt never sees half of a page, and the main loop
reads the interrupt's 16-bit position with interrupts masked for three
instructions. It copies through a read window (`$C073` = the song's bank,
RAMRD on), with the copy loop in the card, since RAMRD moves the
main-memory code it would otherwise run. At the end of a looping song the
refill goes on with the loop's bytes, so the interrupt reads straight on
after the `$FF`. A song that does not loop stops the refills at its end.

**A stream that breaks a rule.** An envelope index at or past the song's
envelope count (header byte 2) or a drum recipe at or past its drum
count (byte 3), a voice outside the layout, a wait of 0, or a looping
stream without a wait: the player stops reading at that command, with
`snd_error` = 5 (`ERR_STREAM`) and its position on the command; the
voices keep what they had. The converter never writes such a stream.

**Underrun.** When the bytes of the next command are not all in the
ring (the main loop did not refill, during a disk access or a level
load), the player silences every music voice (idle, silent, flags and
latched hits cleared, as a `$7v` cut does) and returns; the next tick
tries the same command again.

**No music.** The music needs the card's native mode. `snd_probe`'s
answer is the flag the game acts on, defined in `sound.inc`:

| A (carry) | Name | The card | What the game does |
| --- | --- | --- | --- |
| `$00` (clear) | `SND_MUSIC` | Switched to native mode: 4 AY chips (the Appletini's Phasor) | `snd_init`, then `snd_start`, `snd_refill`, `snd_stop` as it likes; the effects on |
| `$01` (set) | `SND_NO_MUSIC` | Cannot switch: 2 AY chips (a Mockingboard, or the Phasor with "Mockingboard only" set, its `audio_control` bit 26) | `snd_init` once, then nothing else of the player, and the effects off (`fx_init`). The VBL interrupt still runs and `snd_tick` returns at once |

A song file of another layout (header byte 1 not 0) is refused by
`snd_start` with `ERR_LAYOUT`.

**Machines.** PAL or NTSC is chosen at each `snd_start`: two period
tables of native mode (128 notes each), and the tempo fraction (2 +
52,135/65,536 ticks an interrupt on PAL, 2 + 22,043/65,536 on NTSC).

## Sizes and places

From the game's link map (`build/native/m11/plboot/plboot.map`); the
places are `docs/MEMORY_MAP.md` section 5's:

| Segment | Bytes | Place in the game |
| --- | ---: | --- |
| `SNDZP`: player zero page | 31 | `$D8-$F6` |
| `SNDRING`: the song ring and its 3-byte mirror | 1,027 | `$E000-$E402` |
| `SNDLIST`: write lists (in one page) | 128 | `$E480-$E4FF` |
| `SNDBSS`: voices, shadows, song tables | 567 | `$E500-$E736` |
| `SNDCODE`: music, bursts, refill | 2,064 | `$E900-$F10F` |
| `SNDRODATA`: periods PAL and NTSC, bend, levels, layout | 973 | `$F110-$F4DC` |
| `SNDBOOT`: `snd_probe` | 117 | boot code |

- The write lists must not cross a page: the burst's `lda
  wreg+c*16-1,x` keeps the 41-cycle loop, so `wreg-1` to `wval+63` stay
  in one page. They follow the ring (which ends 3 bytes into a page) with
  no padding; `player.s` has the linker check it.
- The song tables take their maximum (20 envelopes, 23 drum recipes: 298
  bytes; the WAD's songs use at most 9 and 17), and the voice arrays are
  11 x 9 bytes.
- The period tables cover all 128 notes the stream format allows (2 x
  256 bytes); notes below 24 repeat an octave higher, so folding them
  would save 96 bytes.

## Cost

With the default slot-4 slowdown window (512 cycles) most of the music's
time is the 504 us tail the main loop runs at 1 MHz after each burst:
measured on a2vm, 13 to 30 ms a second depending on the song (1.3% to
3.0% of the machine). With the Doom profile's window 32
(`tools/sound/README.md`, "The Doom configuration profile") it is 4.4 to
9.8 ms a second, of which about 2.1 to 2.9 ms is the player's own
computing (3,000 to 3,700 cycles an interrupt on average without the
writes; a bend costs a 125-byte multiply).
