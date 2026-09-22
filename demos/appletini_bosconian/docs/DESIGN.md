# Appletini Bosconian — design and interface contract

An original, from-scratch Bosconian (Namco, 1981) recreation for an enhanced
Apple //e with an Appletini ONE card. No Namco code is used and the source
tree holds no ROM data or Namco art; the graphics, the base layouts and the
round order are converted from a Bosconian ROM set at build time
(`tools/bosco_rom.py`, section 11), with drawn art as the fallback.

Targets:

- Enhanced //e, 65C02 code from cc65 (`cl65 -t none --cpu 65c02`).
- Appletini virtual TransWarp at the 33 MHz preset **or** TURBO. Both must run
  the game at a locked 60 frames per second (one full logic+render pass per
  VBL).
- Video: Appletini "VidHD-style" Super Hi-Res, 320x200, 16 colors per line,
  framebuffer in **AUX $2000-$9FFF**, enabled by writing `$C1` to `$C029`.
- Sound: Appletini virtual Phasor in slot 4, switched to its native mode
  (four AY chips, 12 voices) with a Mockingboard fallback (two chips):
  VIA-A at `$C410`, VIA-B at `$C480`, SSI-263 speech at `$C440-$C447`.
- RamWorks: probed at startup (bank count shown on the title screen and in the
  mailbox). Not required for play.
- Z80 Appli-Card: not used.

The layout mirrors `demos/appletini_invasion` (Makefile, cfg, tools/, smoke
test against GSSquared). Read that project first for conventions.

## 1. Hardware facts that drive the design (verified in appletini-one)

1. **SHR framebuffer**: AUX `$2000 + y*160`, byte `x/2`, high nibble = left
   pixel. SCBs at AUX `$9D00-$9DC7` (one per row; low 4 bits = palette).
   Palettes at AUX `$9E00 + pal*32`, entry = 2 bytes little-endian `$0RGB`
   (byte 0 = `GB`, byte 1 = `0R`). `$9DF8-$9DFF` is an Appletini control area:
   leave `$9DF8` = 0 and `$9DFC-$9DFF` = 0 (no SHR4/3200 magic).
2. **Enable**: `STA $C000` (80STORE off) so RAMWRT owns `$2000+` routing,
   `STA $C029` with `$C1`. Disable with `$01`.
3. **Writing AUX**: set RAMWRT (`STA $C005`), write `$0200-$BFFF`, clear
   (`STA $C004`). While RAMWRT is on, **no code may write main RAM above
   `$01FF`**: no C code, no cc65 software stack, no absolute stores to game
   variables. Zero page and the hardware stack stay in main (ALTZP off) and
   are fine. Reads still come from main (RAMRD off), so asm can read sprite
   data, tables and the display list from main while writing AUX.
4. **vTW 33 MHz preset bus budget**: every write to AUX `$2000-$9FFF` (and
   main `$0400-$0BFF`, `$2000-$5FFF`) is a *posted* 1 MHz bus write. The
   posted queue is 512 deep and back-pressures the CPU when full. One NTSC
   frame has about 17,000 bus cycles. **Hard budget: at most 10,000 AUX
   framebuffer bytes written per frame, typical under 6,000.** Full-frame
   redraws are impossible at 33 MHz; TURBO lifts this but we design for 33.
   Consequence: erase/redraw of small sprites only, no clears during play.
5. Because of (4), also keep **all writable game data out of main
   `$0400-$0BFF` and `$2000-$5FFF`**. The linker config below places DATA/BSS
   at `$0C00-$1FFF`. Code and read-only tables may live in `$2000-$5FFF`
   (reads are free).
6. **Slot 4 (Phasor) slowdown**: any `$C4xx` access drops the vTW to 1 MHz
   for a slowdown window. Batch every AY/SSI access into one burst per frame
   (`sound_update()` is called exactly once per frame, after rendering).
7. **VBL and the SHR snapshot**: `$C019` bit 7 = 1 during active display,
   0 during vertical blank (Invasion's convention, synthesized by the vTW
   without a bus cycle). The Appletini renderer publishes the SHR shadow at
   line 0 (`apple_cycle_renderer.c`: "SHR publishes the latest shadow at the
   next frame marker"), not scanline by scanline. `video_wait_vbl()` therefore
   returns at the *end* of VBL, right after line 0, and the whole frame's
   writes (render burst, panel updates) happen before the next line 0, so a
   published frame is always complete. This is the Bilestoad port's timing
   (`demos/bilestoad`, branch `bilestoad-shr-port`).
8. `$C074`: write 0 at start to release any 1 MHz lock (RocketChip/TW
   convention; GSSquared and Appletini honor it).
9. `$C011-$C01F` status reads are free (no bus cycle). `$C000/$C010`
   keyboard, `$C061/$C062` buttons, `$C064/$C065/$C070` paddles are real
   1 MHz bus cycles: keep them to a few per frame; paddle reads are polled
   with a CPU delay between reads and capped (see input).

## 2. Memory map

Main memory (`bosconian.cfg`):

| Range | Use |
|---|---|
| `$0020-$007F` | asm scratch zero page (video `$20-$4F`, sound `$50-$5F`, input/misc `$60-$6F`, spare `$70-$7F`) |
| `$0080-$009F` | cc65 runtime ZEROPAGE segment (`sp`, `ptr1..4`, `tmp1..4`, `regsave`, `sreg`) |
| `$0100-$01FF` | 6502 stack |
| `$0300-$033F` | debug mailbox (section 8) |
| `$0C00-$1FFF` | `DATA` (run address; copied from the load image by crt0) and `BSS` |
| `$2000-$BAFF` | `STARTUP`, `CODE`, `RODATA` (with the sprites that stay in main memory), `DATA` load image. Never written at runtime. |
| `$BB00-$BEFF` | cc65 software stack (`__STACKSTART__ = $BF00`, size `$0400`: the C code has no recursion and few locals). Before `main()` runs, `loader.s` uses it as the ProDOS file buffer while it reads `BOSCO.SPR`. |
| `$BF00-$BFFF` | ProDOS global page (untouched) |
| main language card | ProDOS (untouched) |

The SYS file loads at `$2000` (ProDOS) and starts executing at `$2000`
(crt0 in `STARTUP`). No `JMP $6000` padding is needed because the SHR
framebuffer is in AUX, not main hires memory.

AUX memory: `$2000-$9FFF` SHR framebuffer, and the **auxiliary language
card** holds the sprites: `$D000-$FFEF` with bank 2 of `$D000-$DFFF`
(12,272 bytes) and `$D000-$DFFF` bank 1 (4,096 bytes), filled by `loader.s`
from `BOSCO.SPR` before `main()` runs (section 4). The blitter switches
ALTZP on while it draws a sprite that lives there. ProDOS never uses the
auxiliary card; the `/RAM` volume, which does, is disconnected at start the
way the ProDOS 8 Technical Reference describes, because the game overwrites
its memory anyway. Without ProDOS (no `JMP` at `$BF00`: the py65 test
machine) the loader does nothing and the test fills the card itself.

RamWorks: probed like Invasion (`ramworks_probe`), bank count reported. The
probe writes `$1000/$1001` in each bank and restores bank 0.

## 3. Screen layout (320x200)

- Playfield: x `0..255`, y `0..199` (128 bytes per row). All moving objects
  are clipped to this box by the asm blitter.
- Side panel: x `256..319` (32 bytes per row), drawn by `panel_*` routines.
  It is the arcade's 64-pixel panel squeezed from 224 to 200 rows (`main.c`
  `PANEL_Y_*`): `HI-SCORE` (red) at y 0 and its digits at y 8, `1UP` at 16
  and the score at 24 (white, right-aligned, 8 glyphs), the `CONDITION`
  caption at 36 (the arcade's eight tiles as one 62x8 sprite), the framed
  GREEN/YELLOW/RED label centred at y 44..59,
  the radar at y 64..175 (64x112: the whole 1024x1792 world at 1/16, purple
  background like the arcade's, the base marker tile as an 8x8 sprite, 2x2
  dots for the ship and the enemies), up to four 16x16 ship icons at y 176
  for the lives, `ROUND nn` (gray) at y 192.
- Palette 0 (all rows, SCB = 0) is the arcade's colour PROM: its 15 colours
  plus black, the 8-bit values divided by 17:

| idx | color | RGB (4-bit) | arcade | use |
|---|---|---|---|---|
| 0 | black | 000 | | background / transparent |
| 1 | white | DDD | #dedede | ship, player shots, stars, text |
| 2 | red | F00 | #ff0000 | RED lamp, ship markings, enemy shots, missiles |
| 3 | orange | F60 | #ff6800 | E-type, P-type, mine |
| 4 | yellow | FF0 | #ffff00 | YELLOW lamp, spy ship, big explosions |
| 5 | purple | 90D | #9700de | I-type, pods, radar background |
| 6 | pink | F6D | #ff68de | I-type, core |
| 7 | cyan | 0FD | #00ffde | E-type, P-type |
| 8 | blue | 06D | #0068de | P-type, mine |
| 9 | brown | 620 | #682100 | mine |
| 10 | green | 0B0 | #00b800 | GREEN lamp, base pods and core, radar marker |
| 11 | violet | 60D | #6800de | (spare) |
| 12 | dark teal | 244 | #214747 | base shading, asteroids, far stars |
| 13 | gold | D90 | #de9700 | asteroids |
| 14 | dark red | B20 | #b82100 | asteroids, rubble, big explosions |
| 15 | gray | 999 | #979797 | ship, explosions, lives icon, ROUND text |

## 4. Sprite format (produced by `tools/gen_assets.py`, consumed by `video.s`)

Every sprite exists in two pre-shifted variants: **even** (drawn at even x)
and **odd** (x&1 = 1, the image shifted right one pixel, so the odd variant
is one byte wider when the width is even). The blitter picks the variant
from the x parity. A row is stored as one or more horizontal *runs* of
bytes: a gap of two or more fully transparent bytes (four pixels on byte
boundaries) between opaque bytes starts a new run, so the inside of an
explosion or the space between wing tips stays see-through; smaller gaps
are black (0) inside the run. Rows with no opaque pixels have
`run_off = $FF`.

```
sprite variant:
  byte 0      : height H (1..56)
  byte 1      : width in bytes W (of this variant, 1..32)
  H rows, each one or more run records:
    byte      : run_off  (first byte of the run inside [0,W); bit 7 set =
                          another run of this row follows; $FF = empty row)
    byte      : run_len  (bytes in the run, 1..W; 0 for an empty row)
    run_len bytes of pixel pairs (high nibble = left pixel)
```

Every record starts with the fixed two-byte header, so an empty row is
exactly `$FF, $00` with no pixel data (the generator and the blitter both
follow this).

Where the data lives: the arcade graphics are about 20 KB of run-encoded
data, so `tools/gen_assets.py` places the sprites, in id order and both
variants together, into the auxiliary language card first (`REGIONS`:
bank 2 `$D000-$FFEF`, then bank 1 `$D000-$DFFF`) and assembles what is
left, plus the two panel icons (`MAIN_ONLY`: `panel_sprite` does not
switch banks), into `RODATA`. The card sprites go into `build/BOSCO.SPR`
(`"BSPR"`, u8 region count, per region u16 load address, u16 length, u8
bank code, then the region bytes) which `loader.s` reads through the MLI
in 1 KB pieces and copies with ALTZP on. `_spr_bank` says per id where it
is: 0 main memory, bit 2 (`SPR_BANK_AUX`) the auxiliary card, bit 1
(`SPR_BANK_1`) its bank 1 instead of bank 2. `blit_sprite` switches ALTZP
on for such a sprite (the auxiliary zero page and stack come with it, so its
inputs are the `B_*` variables in main memory, stored only with RAMWRT off,
and the byte count crosses back in registers) and off again at the end.

`build/assets.s` exports (all in `RODATA`):

```
_spr_even_lo, _spr_even_hi   ; byte tables indexed by sprite id -> variant address
_spr_odd_lo,  _spr_odd_hi    ; ($D000+ for a card sprite)
_spr_width,  _spr_height     ; pixel width/height per id (for C hit boxes)
_spr_bank                     ; bank code per id (0 = main memory)
_font8                        ; 64 glyphs * 8 bytes, ASCII 32..95, bit 7 = left pixel
_palette0                     ; 32 bytes, SHR palette entries
```

and `build/assets.h` defines `SPR_*` ids and `SPR_COUNT`. The id list is
fixed by this document (section 9) so C and the converter agree.

The blitter draws a run with `STA` only (no read-modify-write; AUX cannot be
read while code runs from main). So sprites are **opaque within a run**:
a transparent pixel inside a run comes out black. With the run splitting
above this only affects gaps under four pixels, and because the background
is black it is only visible where sprites overlap.

## 5. Video API (`video.s`, C-callable, all `__fastcall__` or void)

Coordinates: playfield x/y are signed 16-bit (objects may be partially off
screen; the blitter clips to 0..255 x 0..199). Panel routines take unsigned
panel coordinates relative to x=256.

```c
void video_init(void);              /* 80STORE off, clear AUX $2000-$9FFF, SCBs=0,
                                       palette0, then $C029=$C1 */
void video_shutdown(void);          /* $C029=$01, text mode restored */
void video_wait_vbl(void);          /* returns right after line 0 (end of VBL) */
u16  video_speed_probe(void);       /* loop iterations between two VBL starts */

/* display list: filled by C, rendered by video_render(). */
#define DL_MAX 96
struct DlItem { u8 id; s16 x; s16 y; u8 pad; };   /* 6 bytes, see bosco.h */
extern struct DlItem dl_items[DL_MAX];
extern u8 dl_count;

/* stars: two layers, screen-space u8 x (0..255) / y (0..199), color index. */
#define STAR_MAX 48
extern u8 star_x[STAR_MAX], star_y[STAR_MAX], star_color[STAR_MAX];
extern u8 star_count;

void video_render(void);
   /* RAMWRT on; erase every previous-frame item (zeros over its runs at its
      old id/x/y, remembered privately), erase the previous stars, draw the
      new stars, then draw every current item in list order; items beyond
      the previous count are only drawn, items missing this frame
      (i >= dl_count) are only erased. RAMWRT off. Then copy the current
      lists to the private previous lists (main RAM writes happen only after
      RAMWRT is off). Counts AUX bytes written into video_frame_writes.
      Erase-all-then-draw-all avoids holes where a later item's old box
      overlaps an earlier item's new box. The burst starts right after the
      line-0 snapshot (video_wait_vbl) and must end before the next one: at
      the 33 MHz preset that is about 16,000 posted bytes. The game also
      sorts dl_items by y (a stable counting sort into 25 buckets of y>>3 in
      world_build_dl, ship last); that is cheap and keeps the burst
      top-to-bottom for emulators that scan the beam. */
extern u16 video_frame_writes;      /* AUX bytes written by the last render */

void video_clear_playfield(void);   /* black the 256x200 box AND forget all
                                       previous positions (used on state change;
                                       costs 25,600 writes: only outside play) */
void video_clear_all(void);         /* whole screen, also forgets panel state */

/* panel (x 256..319): px is a byte column 0..31, py a row 0..199 */
void panel_text(u8 px, u8 py, u8 color, const char *s);  /* 8x8 font, ASCII 32..95,
                                       32 writes per char, bg black */
void panel_text_small(u8 px, u8 py, u8 color, const char *s); /* same font, but
                                       every other row (8x4); kept for
                                       diagnostics, unused by the game */
void panel_fill(u8 px, u8 py, u8 wbytes, u8 h, u8 color);   /* solid box */
void panel_dot(u8 px, u8 py, u8 color);  /* 2x2 pixel dot at byte column px */
void panel_sprite(u8 px, u8 py, u8 id);  /* icon at byte column px (even variant,
                                            no clipping, opaque runs) */
/* playfield text for title/attract/game over (x in pixels, multiple of 2) */
void field_text(u8 x, u8 y, u8 color, const char *s);
void field_text_big(u8 x, u8 y, u8 color, const char *s);  /* 16x16 (2x scale) */
```

`video_set_panel_color(c)` stores a default color; panel_text, panel_text_small,
panel_fill and panel_dot use it when their color argument is `$FF`.

All these switch RAMWRT on/off internally and never touch main RAM above
`$01FF` while it is on. They may use ZP `$20-$4F`. `video_render` must run
inside ~4 ms at 33 MHz for a 6,000-byte frame: keep the inner run copy at
`LDA (src),y / STA (dst),y` speed, table-driven row addresses, no per-byte
subroutine calls.

## 6. Sound API (`sound.c` + `sound_io.s`)

```c
void sound_init(void);        /* VIA A/B DDR/PCR, silence both AYs, SSI setup */
void sound_update(void);      /* ONE call per frame after video_render(): runs the
                                 music sequencer, the SFX engine, then the speech
                                 stream. All AY/SSI writes happen here, in one burst */
void sound_music(u8 track);   /* MUSIC_NONE, MUSIC_TITLE, MUSIC_BLASTOFF,
                                 MUSIC_AMBIENT, MUSIC_ROUND_CLEAR, MUSIC_DEATH,
                                 MUSIC_GAME_OVER */
void sound_tempo(u8 level);   /* 0 green .. 2 red: ambient pulse rate */
void sound_sfx(u8 id);        /* SFX_SHOT, SFX_HIT, SFX_EXPLODE, SFX_POD, SFX_BASE,
                                 SFX_MINE, SFX_PLAYER_DIE, SFX_ALERT, SFX_SPY,
                                 SFX_EXTRA_LIFE, SFX_MISSILE */
void speech_say(u8 phrase);   /* SAY_BLAST_OFF, SAY_ALERT, SAY_SPY, SAY_RED,
                                 SAY_BATTLE, SAY_GAME_OVER; one plays at a time,
                                 up to three wait in a FIFO (a fourth is dropped) */
u8   speech_busy(void);
```

Phasor modes (from the Bilestoad port's driver and
`appletini-one/hdl/apple/mockingboard.sv`): the card starts in Mockingboard
mode; reading `$C0C8` then `$C0C5` selects Phasor native mode. VIA-A answers
at `$C41x` and VIA-B at `$C48x` in both modes. In native mode ORB bit 4
selects the first AY behind a VIA and bit 3 the second (both active low),
and the PSG clock is doubled, so every period is doubled. `sound_init`
switches to native mode, writes register 0 of chip 0 and chip 1 and reads
chip 0 back: a plain Mockingboard (or the card locked to Mockingboard mode)
ignores the select bits, so the second write lands on the first chip and
the driver falls back to two chips. GSSquared has no native mode and takes
this path.

Channel plan: chips 2 and 3 (behind VIA-B) play music: lead, bass and
arpeggio on chip 2; a detuned lead, the chord root and a noise hit per step
on chip 3. Chips 0 and 1 (behind VIA-A) play up to six sound effects with
priorities. With two chips: chip 2 music, chip 0 three effects. In
Mockingboard mode SSI-263 writes (`$C440-$C447`) also alias VIA-A
registers, so after any SSI write the driver re-writes VIA-A DDRA/DDRB (an
AY reset pulse) and resends every register of chip 0; in native mode
nothing aliases. Every chip has a register shadow so unchanged registers
cost no bus cycles. AY write sequence: `ORA_NH=reg; ORB=latch; ORB=idle;
ORA_NH=val; ORB=write; ORB=idle` with `$0F/$0C/$0E` for the first chip of a
VIA and `$17/$14/$16` for the second. The mailbox reports `sound_chips`
(4 or 2) and the title screen names the mode.

Speech phonemes: SSI-263 codes (`00 PA, 01 E, 03 Y, 05 AY, 07 I, 08 A,
0A EH, 0C AE, 0E AH, 10 AW, 11 O, 12 OU, 13 OO, 18 UH, 1C ER, 1D R, 20 L,
23 W, 24 B, 25 D, 27 P, 28 T, 29 K, 2F Z, 30 S, 32 SCH, 33 V, 34 F, 37 M,
38 N`), duration in bits 7-6, `$FF` terminator, one phoneme per SSI-263 CA1
completion or 12-frame timeout (Invasion's `speech_tick`).

## 7. Input API (`input.s` + C glue)

```c
u8 input_keys(void);      /* bit mask: IN_UP IN_DOWN IN_LEFT IN_RIGHT IN_FIRE
                             IN_START IN_PAUSE IN_QUIT; reads $C000 once, clears
                             $C010 if a key was there, reads $C061/$C062 */
void input_joy_set_delay(u8 n);   /* dey/bne iterations between paddle polls;
                             main.c passes 2*MHz+3 so one poll takes ~11 us at
                             the measured clock (the ROM PREAD granularity) */
void input_joy_calibrate(void);   /* at title: sample both axes (stick centered);
                             an axis whose count reaches the cap is unusable */
u8 input_joy(void);       /* alternates axes each call; main.c calls it every
                             fourth frame (a poll busy-waits ~1.4 ms of CPU):
                             one $C070 trigger + polled $C064/$C065 reads with
                             the CPU delay above between reads, capped at 400
                             reads (a centered stick needs ~130, full deflection
                             ~260); remembers each axis's last direction bit and
                             returns both, so a diagonal stick gives a diagonal
                             heading */
u8 input_joy_status(void);  /* bit 0: X axis usable, bit 1: Y axis usable */
```

Keys: arrows and `I J K L` for the four directions, `U O M ,` (and `. `)
for diagonals (the classic `UIO/JKL/M,.` cluster), `Space` = fire, `Return`
= start, `Esc` = pause during play / quit at the title (`Q` also quits at
the title, `P` pauses only). Open-Apple, Closed-Apple and the game buttons
= fire. The ship never stops: a direction key sets the new heading; the last
heading persists. Joystick beyond the calibrated 35% dead zone sets the
heading. The //e keyboard latches one key and only reports "any key down",
so the driver keeps a held fire in its held bits when a direction key is
tapped: steering while holding `Space` keeps firing until every key is
released.

## 8. Debug mailbox at `$0300` (magic `A13B`)

Written once per frame by the game (`mailbox_tick`). Offsets:

```
0-3   'A','1','3','B' (magic written last at init)
4     state (0 boot,1 title,2 play,3 dying,4 game over,5 round clear,6 paused)
5     frame_lo   6 frame_hi
7-10  score (u32 le)
11    round     12 lives   13 condition (0 green,1 yellow,2 red)
14-15 player world x (u16)   16-17 player world y
18    heading (0..7, 0 = up, clockwise)
19    bases_left   20 enemies_alive   21 dl_count
22-23 video_frame_writes (u16)   24-25 max frame writes seen this session
26    ramworks_banks   27-28 speed_probe (u16)
29    sfx_now   30 music_track   31 speech_phrase (0xFF idle)   32 input_mask
33    formation_active   34 spy_active   35 last_event (see bosco.h EV_*)
36-37 budget-overrun counter (u16)  38 star_count
39    joystick status (bit 0 X axis usable, bit 1 Y axis usable)
40    sound_chips (4 Phasor native, 2 Mockingboard)
```

## 9. Sprite id list (`SPR_*`, fixed order)

The sizes are the arcade's: 16x16 sprites, 2x2-tile objects, the base
parts cut from its tile grids, the bullet dots. Every ship type has eight
headings (0 = up, clockwise), made from the ROM's three (up, up-right,
left) by mirroring like the arcade hardware does.

```
0..7   SPR_SHIP_0..7      16x16  player, heading 0=up clockwise (N,NE,E,SE,S,SW,W,NW)
8..15  SPR_ITYPE_0..7     16x16  I-type, 8 headings
16..23 SPR_PTYPE_0..7     16x16  P-type, 8 headings
24..31 SPR_ETYPE_0..7     16x16  E-type, 8 headings
32..39 SPR_SPY_0..7       16x16  spy ship, 8 headings
40     SPR_MINE           16x16  cosmo-mine
41..43 SPR_ASTEROID_0..2  16x16  three rock shapes
44..46 SPR_EXPL_0..2      16x16  explosion, 3 frames
47..49 SPR_BIGEXPL_0..2   32x32  base core / mine blast, 3 frames
50     SPR_CORE_V         32x40  vertical base core (tube open at top and bottom)
51     SPR_CORE_H         40x32  horizontal base core (tube open left and right)
52..57 SPR_POD_V0..5      16,24,24,24,24,16  vertical base pods: top, UL, UR, LL, LR, bottom
58..63 SPR_PODDEAD_V0..5  same   the same pods destroyed (rubble)
64..69 SPR_POD_H0..5      16,24,24,24,24,16  horizontal base pods: left, TL, TR, BL, BR, right
70..75 SPR_PODDEAD_H0..5  same
76     SPR_SHOT_PLAYER     2x4   bar (headings N and S)
77     SPR_SHOT_PLAYER_H   4x2   bar (headings E and W)
78     SPR_SHOT_PLAYER_D1  4x4   "/" (headings NE and SW)
79     SPR_SHOT_PLAYER_D2  4x4   "\" (headings NW and SE)
80     SPR_SHOT_ENEMY      4x4   cannon shot
81..82 SPR_MISSILE_0..1    4x4   homing missile, blinking
83     SPR_ICON_SHIP      16x16  lives icon (the arcade panel's ship)
84     SPR_ICON_BASE       8x8   radar marker for a base
85     SPR_CAPTION_COND   62x8   the panel's CONDITION caption (the arcade's eight tiles, blank edge columns cut)
SPR_COUNT = 86
```

A corner pod's 24x24 box holds the pod and its strut, because the arcade
replaces both when the cannon dies; the axis pods are plain 16x16 objects.
The base geometry (pod and core boxes) is in section 10.

## 10. Game rules (implemented in `main.c` / `game.c`)

- World 1024x1792, the arcade's, wrapping on both axes (torus). Camera =
  player − (128,100). Screen position = wrap(obj − cam) into −512..511
  horizontally and −896..895 vertically. The ship starts at (512,1668)
  heading up, like the arcade.
- Player fixed at screen (128,100), always moving at 1.5 px/frame in the
  current heading (alternate 1/2 px, both axes on diagonals). Fires two
  shots at once (forward and backward), speed 5 px/frame, range 120 px, max
  two volleys in flight. Autofire when the fire input is held (every 8 frames).
- Bases: laid out per round by the table in `rounds.c` (`RoundDef`: count,
  orientation bits, centre of every base in world pixels), which is the
  arcade's own: the sub CPU ROM's 14 layouts (radar tile and orientation
  per base, turned into centres the way the arcade's main CPU does) and its
  round list. Round 1 has 3 bases, round 2 four, rounds 3 to 17 eight, and
  rounds 18 and up play rounds 12 to 17 again. `tests/test_rounds.py` holds
  an independent copy of the tables and checks the geometry.
  Base geometry (from the arcade's tile grids): a vertical base is a 64x72
  image with its centre at (32,36): the core `SPR_CORE_V` (32x40) centred
  on it and six pods whose sprite boxes sit at (24,0), (0,8), (40,8),
  (0,40), (40,40) and (24,56) of the image, i.e. sprite centres (0,−28),
  (±20,−16), (±20,16), (0,28) from the base centre (`pod_ox/oy`). The
  cannon bodies that are hit and that shoot are 16x16 boxes at (0,−28),
  (±24,−12), (±24,12), (0,28) (`pod_hx/hy`). A horizontal base is the same
  turned by 90°: 72x64 image, centre (36,32), core `SPR_CORE_H` (40x32),
  pod sprite centres (−28,0), (−16,±20), (16,±20), (28,0), cannon bodies
  (−28,0), (−12,±24), (12,±24), (28,0).
  A cannon hit by a shot is destroyed: 200 points, a small explosion, and
  its rubble sprite (`SPR_PODDEAD_*`) stays; the sixth cannon takes the base
  with it. The core is always open along the base's axis, like the arcade's:
  a shot flying up or down into the 16 px wide tube of a vertical base
  (left or right for a horizontal one) destroys the base; every other hit on
  the 32x40 (40x32) core box bounces off (`SFX_HIT`). Ramming the core
  destroys the base and the ship; ramming a cannon destroys that cannon and
  the ship. Base score 1500 + 500*(min(round,4)−1). From round 3 on a base
  fires a homing missile (speed 1 px/frame so the 1.5 px/frame ship can
  outrun it, homing turn every 8 frames, lifetime 240 frames) every 250
  frames while the player is within 200 px; a player shot destroys a missile
  (50 points). Cannons fire enemy shots (speed 3, straight toward the
  player's current position, cooldown 90 frames per base) when the player is
  within 140 px and the cannon is on screen. A dead base shows the big
  explosion (3 frames) for 60 frames.
- Field objects per round: 24 asteroids (10 pts, 1 hit, three shapes) and
  16 mines (20 pts; when shot they explode into a 32x32 blast that destroys
  enemies and the player within 14 px for 20 frames). Placed randomly, at
  least 96 px from any base and 160 px from the start position.
- Enemies (I-type 50, P-type 60, E-type 70): spawn just outside the screen
  edge nearest a random side, at most `2 + condition*2 + round/2` alive
  (cap 12). I-type homes on the player (turns one heading step per 12
  frames), speed 1.5. P-type, from round 2, speed 2, homes with a 90-frame
  zigzag. E-type flies straight across. All are 16x16 with eight headings.
- Formation: every 20 s (green) / 14 s (yellow) / 10 s (red), a V of 5
  I-types plus a leader spawns off screen and homes as a group: "ALERT!
  ALERT!" (yellow/red also SFX_ALERT siren). Shooting the leader destroys the
  whole formation: bonus 500/1000/1500 by condition; a follower is worth 50.
- Spy ship: every 25 s while none is active, a spy ship ("SPY SHIP
  SIGHTED!") flies past at speed 1; if it leaves the 320 px radius alive the
  condition escalates one step ("CONDITION RED" when reaching red, then
  "BATTLE STATIONS!" and an immediate formation). Shot: 200 pts.
- Condition timer: green→yellow at 45 s, yellow→red at 90 s of round time.
- Player death: contact with any enemy, shot, missile, cannon, core, asteroid,
  mine or blast. 90-frame death sequence, then respawn at the round start
  position with enemies cleared, bases kept. Lives 3, extra life at 20,000
  then every 70,000 (SFX_EXTRA_LIFE).
- Round clear: all bases dead → 120-frame `ROUND CLEAR` with bonus
  `round*1000`, MUSIC_ROUND_CLEAR, then next round: "BLAST OFF!".
- Game over: 180-frame `GAME OVER` (SAY_GAME_OVER), high score kept in RAM,
  back to title. Title: starfield, `BOSCONIAN` big text, diagnostics line
  (`APPLETINI //E  SHR 320X200  60 FPS`, `nn MHZ  RAMWORKS nnn BANKS`), high
  score, `PRESS FIRE OR RETURN`. Esc at title → `video_shutdown()` and ProDOS
  QUIT (`JSR $BF00; .byte $65; .word quit_parms`).
- Radar (section 3): the world at 1/16 in a 64x112 box; live bases as the
  arcade's 8x8 marker (`SPR_ICON_BASE`, redrawn every frame), the player
  (white, blinks every 8 frames) and the spy ship / formation leader (red)
  as 2x2 dots erased in the background colour.
- Stars: 24 far (dark teal, moves at half the camera delta) and 24 near
  (white, gray, cyan, full delta); wrap on screen; re-randomized on state
  change.

## 11. Build and test

- `make` → `build/BOSCO.SYSTEM` and `build/BOSCO.SPR` (cc65, cfg above;
  `-Oirs`, `--standard c99`) from the drawn art in `assets/`.
- `make ROMS=/path/to/bosco.zip` → the same from the arcade graphics:
  `tools/bosco_rom.py` decodes the tile, sprite and dot ROMs and the colour
  PROMs of a MAME Bosconian ROM set as `galaga.cpp` / `bosco_v.cpp` do and,
  following `assets/rom_map.txt` (sprite and tile indices, the base tile
  grids as the game writes them to its video RAM, the bullet dots, the
  font), writes `build/rom/sprites.txt` and `build/rom/font8.txt` for
  `gen_assets.py`, plus `sheet.png`, `palettes.png` and `colors.txt`. The
  ROM set and `build/` stay out of git.
- `make disk` → `dist/Appletini-Bosconian.hdv`: an 800 KB ProDOS SmartPort
  image built by `tools/build_disk.py` in pure Python (no Java): boot blocks
  and `PRODOS` come from `appletini-one/software/ProDOS_2_4_3.po`
  (`APPLETINI_ROOT`, default `../../../appletini-one`), then `BOSCO.SYSTEM`
  (SYS, aux `$2000`) and `BOSCO.SPR` (BIN). The volume name is `A13BOSCO`.
  The builder verifies its own image by re-reading the directory.
- `make test` → `tests/test_video.py` (py65 unit tests of `video.s`: blit,
  multi-run rows, auxiliary-card sprites through a model of ALTZP and the
  language card, erase, clip, text, budget counter), `test_assets.py`
  (generator output, card regions, `BOSCO.SPR`), `test_rom_tool.py`
  (converter, synthetic ROM set), `test_rounds.py` (the layout table
  against the ROM data), `test_game_logic.py`, `test_sound.py`,
  `test_disk.py`.
- `make smoke` → `tools/smoke_test.py --disk dist/Appletini-Bosconian.hdv`
  boots GSSquared (`GSSQUARED_ROOT`, default `../../../gssquared`, executable
  `build/GSSquared`; the `codex/appletini-108-postprocessing` branch has the
  Appletini card) with `appletini-bosconian.gs2`, `-ds7d1=<hdv>`, `--debug`,
  waits for the mailbox magic, checks 60 Hz frame progress at 33 MHz, checks
  that both joystick axes calibrated at the title (mailbox byte 39), presses
  Return, verifies state transitions, keys, score, the write budget, and dumps
  the AUX framebuffer to PNG via `tools/shr2png.py` (pure Python). On Linux run
  under `xvfb-run -a` with `SDL_AUDIODRIVER=dummy`.
