# Doom for the Appletini: design

This is the contract every part of the port is written against. Where a
section says "the implementer decides", the decision is recorded here when
it is made.

## 1. Goal and scope

A playable Doom on an enhanced Apple //e with the Appletini ONE: the vTW in
**TURBO** (about 75 MHz on average), RamWorks memory (at least 4 MB), the
mouse card in slot 2, the Phasor in slot 4, SHR4 **PAL256** video, booted
from a ProDOS hard-disk image on the Appletini's SmartPort.

Content: **Freedoom Phase 1** (`freedoom1.wad`, BSD licence), episode 1
(maps E1M1..E1M9 where they fit, see section 6). The WAD is not in the
repository: `tools/fetch_freedoom.py` downloads it from the npm package
`kaboom.claude` (which ships it with its licence) and checks its SHA-256.

What "Doom" means here, in order of priority:

1. The real maps: BSP, sectors with floor and ceiling heights, the
   blockmap, doors, lifts, switches, exits, secrets, damaging floors.
2. The renderer: textured walls (upper, lower, middle, two-sided masked
   middles), sky, floors and ceilings (textured if the budget allows, else
   shaded flat colour), things as rotated sprites clipped against walls,
   the weapon sprite, lighting by sector light and distance through
   Doom's own `COLORMAP`.
3. The player: movement with momentum and friction, collision and sliding
   along walls, step-up, gravity, use, weapons (fist, pistol, shotgun,
   chaingun, rocket launcher, plasma if E1 has them), ammo, health, armour,
   keys, the status bar.
4. Monsters of episode 1: zombieman, shotgun guy, imp (fireball), demon,
   spectre, lost soul, cacodemon, baron (E1M8); barrels. Their states,
   speeds and attacks as in Doom.
5. Sound effects on the Phasor (AY-3-8913), then music (MUS to AY).

Not in scope: multiplayer, savegames, demos, the automap (maybe later),
high-detail 320-column rendering (a later option, section 4).

## 2. Hardware facts (verified in appletini-one)

- **TURBO**: no fixed rate; the user measures about 75 MHz on average.
  The test machine counts 6502 cycles; the budget is **1,250,000 cycles
  per 60 Hz frame**. Hot code should live in main or aux bank 0 memory
  (shadow BRAM, cached); RamWorks banks are PSRAM with an 8-byte line
  cache and never enter the TURBO word cache, so code running there and
  data read from there are slower (sequential access is best).
- **Video writes** go to the Appletini renderer at fabric speed in TURBO.
  Every `$Cxxx` access takes the original path; keep soft-switch and I/O
  accesses out of inner loops. RamWorks bank changes (`$C073`) drain any
  pending motherboard mirror first.
- **SHR4 PAL256** (`appletini-one/ps_sources/frontend/apple_cycle_renderer.c`,
  `shr4_pal256_color`, `render_shr4_pal256_frame`): with the magic
  `"SHR4"|$80` = `$D3 $C8 $D2 $B4` at aux `$9DFC-$9DFF`, the paging byte
  aux `$9DF8` = 0 (progressive), and at least one palette entry's high
  byte having selector nibble 2 (bits 7-4 of the odd bytes `$9E01..$9FFF`;
  we set it in all 256), the SHR screen is **320x100, one byte per pixel**,
  row `y` at aux `$2000 + 320*y` (`$2000-$9CFF`), each byte an index into a
  **256-entry RGB444 palette** at aux `$9E00-$9FFF` (entry `i`: byte `2i` =
  `G<<4|B`, byte `2i+1` = `$20|R`). Each pixel shows as 2x4 on the 640x400
  output. SHR must be on (`$C029` = `$C1`). The shadow is published at the
  frame marker (line 0): a frame is only complete on screen if nothing
  writes the SHR area while line 0 passes.
- **RamWorks**: `$C073` selects the auxiliary 64 KB bank (0 = the base aux
  bank that holds the SHR screen; up to 127). RAMRD (`$C002/$C003`)
  and RAMWRT (`$C004/$C005`) route `$0200-$BFFF` reads and writes to the
  selected aux bank; ALTZP (`$C008/$C009`) routes page 0, page 1 and the
  language card. Code that runs while RAMRD is on must be in page 0/1 or
  the language card. Bank size check at boot; at least 4 MB (64 banks)
  required.
- **SmartPort**: 32 MB ProDOS volumes work (the AD8088 image is 32 MB).
- **Keyboard**: the //e reports only the last key (`$C000`) and "any key
  down" (`$C010` bit 7). Open Apple (`$C061`) and Closed Apple (`$C062`)
  are independent buttons; so are the mouse buttons.
- **Mouse card** slot 2 (`$C0A0-$C0AF`, see
  `demos/pinball_construction_set/src/input.s`), used here for turning.
- **Phasor** slot 4: two AY chips (see the PCS/Bosconian `sound.s`). One
  burst of slot 4 accesses per frame.

## 3. Screen

PAL256, 320x100. Rows 0-83: the 3D view; rows 84-99: the status bar
(Doom's 320x32 `STBAR`, halved vertically).

The view is rendered at **160x84 game pixels** ("low detail", every game
pixel two screen pixels wide) into a buffer in main memory, **column
major** (column `x` at `VIEWBUF + 84*x`, 84 bytes), then copied to the SHR
rows with each byte written twice. On the 640x400 output a game pixel is a
4x4 square. The palette is Doom's `PLAYPAL` 0 reduced to RGB444; the
damage/pickup tints are other `PLAYPAL` entries written to the palette
(512 bytes, once per change).

Frame publishing: the copy (~13,440 reads, 26,880 writes, about 150K
cycles) starts right after line 0 so that it finishes before the next
one. The kernel decides how to wait (section 8).

## 4. Memory

Two address spaces share page 0, page 1 and the main language card:

| Space | `$0200-$BFFF` is | Holds |
|---|---|---|
| RENDER | main memory | the renderer (BSP walk, segs, planes, sprites), its tables and buffers, the view buffer, the kernel's main-memory part |
| GAME | RamWorks bank 1 (RAMRD and RAMWRT on, `$C073` = 1) | the game logic (C, cc65) with its data: mobjs, thinkers, player, level state |

| Range | Use |
|---|---|
| page 0 | `$02-$DF` kernel and renderer, `$E0-$FF` cc65 runtime (`sp`, `sreg`, `ptr1-4`, `tmp1-4`, `regbank`) |
| page 1 | the stack; `$0100-$017F` the space-switch and far-access stubs that must run with RAMRD on |
| main `$0200-$03FF` | renderer tables |
| main `$0400-$0BFF` | text/80-column pages: writes are mirrored to the motherboard, so read-only code and tables only, loaded once |
| main `$0C00-$BFFF` | renderer code, tables, BSS, the 13,440-byte view buffer (never in `$2000-$5FFF`, whose writes are mirrored) |
| main LC `$D000-$FFFF` (+ bank 1 `$D000`) | the kernel: space switches, far access, the column/span/sprite inner loops (they run with RAMRD on to read textures), math routines and their tables, the blit, input, sound |
| aux bank 0 `$2000-$9FFF` | the SHR screen, palette, magic |
| aux bank 0 `$0200-$1FFF`, `$A000-$BFFF`, aux LC | spare fast memory (status bar graphics, font, hot tables) |
| RamWorks bank 1 `$0200-$BFFF` | GAME space |
| RamWorks banks 2.. | level data, textures, flats, sprites, sounds, game tables (section 6) |

ProDOS is used only at boot: the loader reads every data file into
RamWorks, then installs the RENDER image, the LC image and the GAME image
and takes the whole machine (the ProDOS global page and the language card
are overwritten). Quit restarts the machine.

**Far memory** (`bank:address`, 3 bytes). Arrays larger than a bank are
split in chunks of `2^k` elements, one chunk per bank; a far array
descriptor is `{first bank, base address, element size, log2 elements per
chunk}`. The kernel provides far read/write/copy routines usable from both
spaces; the renderer's inner loops select a texture bank once per column
and read with RAMRD on.

## 5. Numbers

- Map units are Doom's (16-bit signed). The game uses Doom's `fixed_t`
  16.16 (C `long`) with assembly `FixedMul`/`FixedDiv`; hot geometry in the
  game uses 16-bit map units where Doom's precision is not needed.
- Angles: 16-bit BAM (Doom's 32-bit angle >> 16). Fine angles for tables:
  the renderer decides the table size (it must fit memory; 2048 or 4096
  entries), recorded in section 7.
- The renderer is integer-only and is specified exactly by the Python
  reference `tools/refrender.py` (section 7).

## 6. Data (tools/wad2a2.py)

The converter reads `freedoom1.wad` and writes `build/data/`: the data files
for the disk and `build/data/manifest.json` (every file, bank placement,
directory tables, per-map statistics), plus ca65 include files with the
table addresses. Graphics are stored at **half resolution** in both axes
(the view is 160x84, half of Doom's 320x168): textures 64x128 become 32x64,
flats 32x32, sprites halved, all in Doom's palette indices (colour 247 is
transparent in sprites as in Doom's patches; posts carry the shape).

Every graphics bank holds **16 colormaps** (Doom's `COLORMAP` 0, 2, 4, ..
30, 256 bytes each) at `$0200-$11FF`, so the inner loops read texel and
colormap from the same selected bank. Graphics data starts at `$1200`.

Directories (in a directory bank; exact record layouts are specified in
the converter's docstring and recorded here):

- **Textures**: composited offline from their patches, stored column
  major, width a power of two (≤ 128 at half resolution), height padded
  to a power of two (≤ 128). Record: bank, address, log2 width, width
  mask, height mask, flags (masked/transparent). Texture 0 = none.
  Animated textures (`SLADRIP1-3`, `BLODGR1-4`, ...) keep their frames
  consecutive; the switch textures pair `SW1xxx`/`SW2xxx` in a table.
- **Flats**: 32x32 row major, 1,024 bytes. Record: bank, address. The sky
  flat `F_SKY1` is flagged. Animated flats (`NUKAGE1-3`, `FWATER1-4`, ...)
  consecutive.
- **Sprites**: Doom patch format halved: width, height, left and top
  offsets, then per column a post list (`top, length, pixels..`, `$FF`
  end). Sprite frame table: for each sprite (`POSS`, `TROO`, ...) and frame,
  the eight rotations' lump index and flip bit, as Doom's `spritedef_t`.
- **Level data** per map, in its own banks: vertexes, segs, subsectors,
  nodes, sidedefs (texture names as texture indices), linedefs, sectors
  (flat indices), blockmap, reject, things, plus derived tables the game
  and the renderer need (sector line lists, linedef bounding boxes and
  slope types, seg angles and offsets). Arrays are chunked when larger
  than a bank. Record layouts: see the converter.
- **Other**: `PLAYPAL` (all 14 palettes as RGB444), the status bar and
  its digits and faces halved, the title picture and menus halved to
  320x100, the font, the sky texture per episode, `ENDOOM`-style text.

Maps that do not fit the renderer's limits (section 7) are reported by the
converter and left out.

## 7. The renderer (src/render/, tools/refrender.py)

Doom's renderer, integer 6502 edition:

- BSP walk front to back from the view position, bounding-box rejection
  with the view angle range, solid-seg clipping (`R_ClipSolidWallSegment`,
  `R_ClipPassWallSegment`) over 160 columns.
- Walls: per seg, projection of the two ends, per column the scale and
  texture column (`xtoviewangle`, `finetangent` or an equivalent), the
  upper/lower/middle pieces with `ceilingclip`/`floorclip`, the colormap
  from the scale and the sector light (and Doom's fake contrast on
  vertical/horizontal walls). Column inner loop in the LC with RAMRD on.
- Planes: Doom's visplanes, reduced (bounded count), drawn as spans, or as
  shaded columns when the budget requires; the sky from the sky texture by
  view angle.
- Masked: sprites (vissprites sorted by scale, clipped by the drawsegs
  like `R_DrawMasked`), two-sided masked middles, then the weapon sprite.
- `tools/refrender.py` is the bit-exact specification: it renders a view
  of the converted data with exactly the integer operations and tables the
  6502 code uses, and writes a PNG. The assembly is tested frame by frame
  against it (the view buffer must match byte for byte).

Limits (the implementer fills in): maximum segs, drawsegs, visplanes,
vissprites per frame; table sizes; fine-angle resolution.

## 8. The kernel (src/kernel/)

Boot and load, bank check, video set-up (PAL256), space switching, far
access, the frame loop, timing, the blit, input, sound, reboot.

Frame loop: read input once; run the game tics that are due (Doom's 35 Hz
tic clock, derived from the 60 Hz VBL count: 7 tics every 12 frames,
at most 4 tics per rendered frame); render; wait for line 0 if the copy
would not finish before it, then copy the view; update the status bar;
sound burst.

## 9. The game (src/game/, C)

Doom's play simulation, trimmed to episode 1: `p_tick`, `p_mobj`,
`p_map`/`p_maputl` (blockmap, line opening, try-move, slide, line attack
and aim, use, radius attack), `p_sight` (reject then BSP), `p_enemy`
(look, chase, the attacks of section 1), `p_inter`, `p_pspr`, `p_user`,
`p_spec` with doors, floors, plats, ceilings, lights, switches, exits,
teleporters; `g_game` level flow; `st_stuff` values for the status bar.
States and mobj info: Doom's tables for the kept types, in a far bank
(checked against ZDoom's DECORATE in the reference sources). The game is
compiled with cc65 for the GAME space and calls the kernel through a jump
table in the language card.

## 10. Input

Mouse X turns (Doom's mouse sensitivity), mouse button fires. The held
key (`$C000` while `$C010` bit 7 is set) moves: up/down arrows or W/S
forward and back, left/right arrows turn, A/D (or `,`/`.`) strafe. Open
Apple fires, Closed Apple uses (doors, switches); both work while a
movement key is held. `1`-`7` select weapons, Esc opens the menu, Tab
toggles run.

## 11. Sound

Doom's sound effects approximated on the AY chips (tone/noise/envelope
recipes per effect, priorities as Doom's `S_StartSound`), later MUS music
on the second chip.

## 12. Build and test

`make` builds `build/DOOM.SYSTEM` and the data; `make disk` writes
`dist/Appletini-DOOM.hdv` (a ProDOS volume sized to the data, files split
at 128 KB); `make test` runs the unit tests. `tools/a2sim.py` (from the PCS
port, extended with PAL256 screenshots and the TURBO cycle budget) runs
everything; `tools/run_doom.py` drives a scripted session and saves
screenshots and per-frame costs.
