# Appletini Bosconian — design and interface contract

An original, from-scratch Bosconian (Namco, 1981) recreation for an enhanced
Apple //e with an Appletini ONE card. No Namco code, ROM data, or art is used.

Targets:

- Enhanced //e, 65C02 code from cc65 (`cl65 -t none --cpu 65c02`).
- Appletini virtual TransWarp at the 33 MHz preset **or** TURBO. Both must run
  the game at a locked 60 frames per second (one full logic+render pass per
  VBL).
- Video: Appletini "VidHD-style" Super Hi-Res, 320x200, 16 colors per line,
  framebuffer in **AUX $2000-$9FFF**, enabled by writing `$C1` to `$C029`.
- Sound: Appletini virtual Phasor in its default Mockingboard-compatible mode
  in slot 4: AY-A behind VIA-A (`$C400`), AY-B behind VIA-B (`$C480`),
  SSI-263 speech at `$C440-$C447`.
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
7. **VBL**: `$C019` bit 7 = 1 during active display, 0 during vertical blank
   (Invasion's convention, synthesized by the vTW without a bus cycle).
   `video_wait_vbl()` returns at the *start* of VBL so rendering begins about
   4.5 ms before the beam reaches row 0.
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
| `$2000-$AFFF` | `STARTUP`, `CODE`, `RODATA`, `DATA` load image. Never written at runtime. |
| `$B000-$B7FF` | cc65 software stack (`__STACKSTART__ = $B800`, size `$0800`) |
| `$BF00-$BFFF` | ProDOS global page (untouched) |

The SYS file loads at `$2000` (ProDOS) and starts executing at `$2000`
(crt0 in `STARTUP`). No `JMP $6000` padding is needed because the SHR
framebuffer is in AUX, not main hires memory.

AUX memory: `$2000-$9FFF` SHR framebuffer only. Nothing else in AUX.

RamWorks: probed like Invasion (`ramworks_probe`), bank count reported. The
probe writes `$1000/$1001` in each bank and restores bank 0.

## 3. Screen layout (320x200)

- Playfield: x `0..255`, y `0..199` (128 bytes per row). All moving objects
  are clipped to this box by the asm blitter.
- Side panel: x `256..319` (32 bytes per row), drawn by `panel_*` routines.
  Layout (rows): `HI-SCORE` label + 7 digits (y 2/10), `1UP` + score (y 22/30),
  condition lamp box 56x10 at y 44 with text GREEN/YELLOW/RED, radar 48x48 box
  at x 264..311, y 60..107 (world/32), `ROUND nn` at y 116, lives icons at
  y 128, remaining-base icons at y 140, `MHZ nn` / `RW nnn` diagnostics at
  y 184/192 (small text).
- Palette 0 (all rows, SCB = 0):

| idx | color | RGB (4-bit) | use |
|---|---|---|---|
| 0 | black | 000 | background / transparent |
| 1 | white | FFF | ship, stars, text |
| 2 | light gray | AAA | ship shading, far stars |
| 3 | dark gray | 555 | asteroids, dim stars |
| 4 | red | F00 | RED lamp, spy ship, explosions |
| 5 | orange | F80 | explosions, core open |
| 6 | yellow | FF0 | YELLOW lamp, shots |
| 7 | green | 0C0 | GREEN lamp, base dots, pods |
| 8 | cyan | 0FF | I-type, HUD values |
| 9 | blue | 00F | P-type |
| 10 | dark blue | 008 | radar box, panel frames |
| 11 | magenta | F0F | E-type / mines |
| 12 | pink | F8B | player shots |
| 13 | brown | 840 | asteroid detail |
| 14 | dark green | 060 | pod detail |
| 15 | light blue | 8BF | missiles, blue stars |

## 4. Sprite format (produced by `tools/gen_assets.py`, consumed by `video.s`)

Every sprite exists in two pre-shifted variants: **even** (drawn at even x)
and **odd** (x&1 = 1, the image shifted right one pixel, so the odd variant
is one byte wider when the width is even). The blitter picks the variant
from the x parity. Rows are stored as a single horizontal *run* covering the
opaque pixels; transparent pixels inside the run are black (0). Rows with no
opaque pixels have `run_off = $FF`.

```
sprite variant:
  byte 0      : height H (1..48)
  byte 1      : width in bytes W (of this variant, 1..32)
  H row records:
    byte      : run_off  (first byte of the run inside [0,W); $FF = empty row)
    byte      : run_len  (bytes in the run, 1..W; 0 for an empty row)
    run_len bytes of pixel pairs (high nibble = left pixel)
```

Every row record starts with the fixed two-byte header, so an empty row is
exactly `$FF, $00` with no pixel data (the generator and the blitter both
follow this).

`build/assets.s` exports (all in `RODATA`):

```
_spr_even_lo, _spr_even_hi   ; byte tables indexed by sprite id -> variant address
_spr_odd_lo,  _spr_odd_hi
_spr_width,  _spr_height     ; pixel width/height per id (for C hit boxes)
_font8                        ; 64 glyphs * 8 bytes, ASCII 32..95, bit 7 = left pixel
_palette0                     ; 32 bytes, SHR palette entries
```

and `build/assets.h` defines `SPR_*` ids and `SPR_COUNT`. The id list is
fixed by this document (section 9) so C and the converter agree.

The blitter draws a run with `STA` only (no read-modify-write; AUX cannot be
read while code runs from main). So sprites are **opaque within their
run**; art is designed so that transparent pixels inside a run are rare
(convex shapes). Because the background is black, this looks right.

## 5. Video API (`video.s`, C-callable, all `__fastcall__` or void)

Coordinates: playfield x/y are signed 16-bit (objects may be partially off
screen; the blitter clips to 0..255 x 0..199). Panel routines take unsigned
panel coordinates relative to x=256.

```c
void video_init(void);              /* 80STORE off, clear AUX $2000-$9FFF, SCBs=0,
                                       palette0, then $C029=$C1 */
void video_shutdown(void);          /* $C029=$01, text mode restored */
void video_wait_vbl(void);          /* returns at start of vertical blank */
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
      overlaps an earlier item's new box. At the 33 MHz preset the erase
      pass runs at bus speed inside the vertical blank; the game therefore
      sorts dl_items by y (ascending, bucketed by y>>3) before calling
      video_render so the draw pass stays ahead of the beam. */
extern u16 video_frame_writes;      /* AUX bytes written by the last render */

void video_clear_playfield(void);   /* black the 256x200 box AND forget all
                                       previous positions (used on state change;
                                       costs 25,600 writes: only outside play) */
void video_clear_all(void);         /* whole screen, also forgets panel state */

/* panel (x 256..319): px is a byte column 0..31, py a row 0..199 */
void panel_text(u8 px, u8 py, u8 color, const char *s);  /* 8x8 font, ASCII 32..95,
                                       32 writes per char, bg black */
void panel_text_small(u8 px, u8 py, u8 color, const char *s); /* same font, but
                                       every other row (8x4) for diagnostics */
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
                                 SAY_BATTLE, SAY_GAME_OVER; queued, one at a time */
u8   speech_busy(void);
```

Channel plan: AY-B (VIA-B `$C480`, ORA `$C481`/`$C48F`, ORB `$C480`) owns
music (3 tone channels). AY-A (VIA-A `$C400`) owns SFX with priorities.
SSI-263 writes (`$C440-$C447`) also alias VIA-A registers, so after any SSI
write the driver re-writes VIA-A DDRA/DDRB and marks all AY-A registers dirty
(they are resent on the next `sound_update`). AY register writes go through
a shadow so unchanged registers cost no bus cycles. AY write sequence (per
Invasion): `ORA=reg; ORB=7; ORB=4; ORA=val; ORB=6; ORB=4`.

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
void input_joy_calibrate(void);   /* at title: sample both axes (stick centered) */
u8 input_joy(void);       /* alternates axes each call (X even frames, Y odd):
                             one $C070 trigger + polled $C064/$C065 reads with a
                             ~40-cycle CPU delay between reads, capped at 400
                             reads; returns the same IN_* mask */
```

Keys: arrows and `I J K L` for the four directions, `U O M ,` (and `. `)
for diagonals (the classic `UIO/JKL/M,.` cluster), `Space` = fire, `Return`
= start, `Esc` = pause / quit at title. Open-Apple, Closed-Apple and the game
buttons = fire. The ship never stops: a direction key sets the new heading;
the last heading persists. Joystick beyond the calibrated 35% dead zone sets
the heading.

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
36-37 dropped-frame counter (u16)  38 star_count  39-40 reserved
```

## 9. Sprite id list (`SPR_*`, fixed order)

```
0..7   SPR_SHIP_0..7      16x16  player, heading 0=up clockwise (N,NE,E,SE,S,SW,W,NW)
8..15  SPR_ITYPE_0..7     12x12  I-type interceptor, 8 headings
16..23 SPR_PTYPE_0..7     12x12  P-type, 8 headings
24..27 SPR_ETYPE_0..3     12x12  E-type spy ship, 4-frame spin
28..29 SPR_MINE_0..1      12x12  cosmo-mine blink
30..31 SPR_ASTEROID_0..1  16x16  two rock shapes
32     SPR_POD            16x16  base cannon pod
33     SPR_CORE_CLOSED    16x16
34     SPR_CORE_OPEN      16x16
35..38 SPR_EXPL_0..3      16x16  explosion, 4 frames
39     SPR_SHOT_PLAYER     2x6   vertical bar (drawn for all headings)
40     SPR_SHOT_ENEMY      4x4
41..42 SPR_MISSILE_0..1    6x8
43     SPR_ICON_SHIP       8x8   lives icon
44     SPR_ICON_BASE       8x8   remaining-base icon
45     SPR_BOSS_HIT        16x16 pod destroyed flash (single frame)
46..49 SPR_BIGEXPL_0..3   32x32 base core explosion
SPR_COUNT = 50
```

Rows are single runs; art must be convex per row (no holes).

## 10. Game rules (implemented in `main.c` / `game.c`)

- World 1536x1536, wrapping (torus). Camera = player − (128,100). Screen
  position = wrap(obj − cam) into −768..767.
- Player fixed at screen (128,100), always moving at 1.5 px/frame in the
  current heading (alternate 1/2 px, both axes on diagonals). Fires two
  shots at once (forward and backward), speed 5 px/frame, range 120 px, max
  two volleys in flight. Autofire when the fire input is held (every 8 frames).
- Bases: 6 (rounds 1-2), 7 (3-4), 8 (5+). Each: core at (bx,by), pods at
  (0,−28), (±24,−14), (±24,+14), (0,+28). Pod hit = destroyed (score 200 when
  the 6th pod dies... the *base* score is awarded when the base dies).
  Core closed/open cycle: closed 180 frames, open 90 frames; while open it
  fires a homing missile (speed 1 px/frame so the 1.5 px/frame ship can
  outrun it, homing turn every 8 frames, lifetime 300 frames) if the player
  is within 200 px. A player shot destroys a missile (50 points). A shot
  into the open core destroys the base. Base score 1500 + 500*(min(round,4)−1). A dead base
  shows big explosions for 60 frames. Pods fire enemy shots (speed 3, straight
  toward the player's current position, cooldown 90 frames) when the player is
  within 140 px and the pod is on screen.
- Field objects per round: 24 asteroids (10 pts, 1 hit) and 16 mines
  (20 pts; when shot they explode into a 32x32 blast that destroys enemies and
  the player within 14 px for 20 frames). Placed randomly, at least 96 px from
  any base and 160 px from the start position.
- Enemies (I-type 50, P-type 60, E-type 70): spawn just outside the screen
  edge nearest a random side, at most `2 + condition*2 + round/2` alive
  (cap 12). I-type homes on the player (turns one heading step per 12
  frames), speed 1.5. P-type, from round 2, speed 2, homes with a 90-frame
  zigzag. E-type spins and flies straight across.
- Formation: every 20 s (green) / 14 s (yellow) / 10 s (red), a V of 5
  I-types plus a leader spawns off screen and homes as a group: "ALERT!
  ALERT!" (yellow/red also SFX_ALERT siren). Shooting the leader destroys the
  whole formation: bonus 500/1000/1500 by condition; a follower is worth 50.
- Spy ship: every 25 s while none is active, an E-type "SPY SHIP SIGHTED!"
  flies past at speed 1; if it leaves the 320 px radius alive the condition
  escalates one step ("CONDITION RED" when reaching red, then "BATTLE
  STATIONS!" and an immediate formation). Shot: 200 pts.
- Condition timer: green→yellow at 45 s, yellow→red at 90 s of round time.
- Player death: contact with any enemy, shot, missile, pod, core, asteroid,
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
- Radar: bases (green 2x2 dots), player (white, blinks every 8 frames),
  spy/formation leader (red) at world/32.
- Stars: 24 far (color 3, moves at half the camera delta) and 24 near
  (colors 1/2/15, full delta); wrap on screen; re-randomized on state change.

## 11. Build and test

- `make` → `build/BOSCO.SYSTEM` (cc65, cfg above; `-Oirs`, `--standard c99`).
- `make disk` → `dist/Appletini-Bosconian.hdv`: an 800 KB ProDOS SmartPort
  image built by `tools/build_disk.py` in pure Python (no Java): boot blocks
  and `PRODOS` come from `appletini-one/software/ProDOS_2_4_3.po`
  (`APPLETINI_ROOT`, default `../../../appletini-one`), then `BOSCO.SYSTEM`
  (SYS, aux `$2000`). The volume name is `A13BOSCO`. The builder verifies its
  own image by re-reading the directory.
- `make test` → `tests/test_video.py` (py65 unit tests of `video.s` blit,
  erase, clip, text, budget counter) and `tests/test_disk.py`.
- `make smoke` → `tools/smoke_test.py --disk dist/Appletini-Bosconian.hdv`
  boots GSSquared (`GSSQUARED_ROOT`, default `../../../gssquared`, executable
  `build/GSSquared`; the `codex/appletini-108-postprocessing` branch has the
  Appletini card) with `appletini-bosconian.gs2`, `-ds7d1=<hdv>`, `--debug`,
  waits for the mailbox magic, checks 60 Hz frame progress at 33 MHz, presses
  Return, verifies state transitions, keys, score, the write budget, and dumps
  the AUX framebuffer to PNG via `tools/shr2png.py` (pure Python). On Linux run
  under `xvfb-run -a` with `SDL_AUDIODRIVER=dummy`.
