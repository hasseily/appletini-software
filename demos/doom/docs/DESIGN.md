# Doom for the Appletini: design

This is the contract every part of the port is written against. Where a
section says "the implementer decides", the decision is recorded here when
it is made.

## 1. Goal and scope

A playable Doom on an enhanced Apple //e with the Appletini ONE: the vTW in
**TURBO** (about 75 MHz on average), RamWorks memory (at least 6 MB: episode 1 loads into banks 2-95 at boot; the vTW serves 8 MB), the
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
  pending motherboard mirror first. The test machine charges each `$Cxxx`
  access one 1 MHz bus cycle, **73 CPU cycles** in TURBO (1,250,000 /
  17,030), on top of the instruction.
- **SHR4 PAL256** (`appletini-one/ps_sources/frontend/apple_cycle_renderer.c`,
  `shr4_pal256_color`, `render_shr4_pal256_frame`): with the magic
  `"SHR4"|$80` = `$D3 $C8 $D2 $B4` at aux `$9DFC-$9DFF`, the paging byte
  aux `$9DF8` = 0 (progressive), and at least one palette entry's high
  byte having selector nibble 2 (bits 7-4 of the odd bytes `$9E01..$9FFF`;
  we set it in all 256), the SHR screen is **320x100, one byte per pixel**,
  row `y` at aux `$2000 + 320*y` (`$2000-$9CFF`), each byte an index into a
  **256-entry RGB444 palette** at aux `$9E00-$9FFF` (entry `i`: byte `2i` =
  `G<<4|B`, byte `2i+1` = `$20|R`). Each pixel shows as 2x4 on the 640x400
  output; a channel value `v` shows as `16v` (`shr_pack_bgra`), and
  `$C029` bit 5 turns everything to luminance. SHR must be on (`$C029` =
  `$C1`). The shadow is published at the frame marker (line 0): a frame
  is only complete on screen if nothing writes the SHR area while line 0
  passes.
- **Video timing**: 262 lines of 65 bus cycles; `$C019` bit 7 is 0 during
  vertical blanking, lines 192-261 (70 lines, 4.45 ms, 27% of a frame),
  so line 0 comes right after blanking ends.
- **RamWorks**: `$C073` selects the auxiliary 64 KB bank (0 = the base aux
  bank that holds the SHR screen; up to 127). RAMRD (`$C002/$C003`)
  and RAMWRT (`$C004/$C005`) route `$0200-$BFFF` reads and writes to the
  selected aux bank; ALTZP (`$C008/$C009`) routes page 0, page 1 and the
  language card. Code that runs while RAMRD is on must be in page 0/1 or
  the language card. `$C073` is write-only: the size is found by writing
  each bank's number into it (127 down to 0) and reading back from 0 up
  (a missing bank aliases a lower one). At least 4 MB (64 banks) required.
- **SmartPort**: 32 MB ProDOS volumes work (the AD8088 image is 32 MB).
- **Keyboard**: the //e reports only the last key (`$C000`) and "any key
  down" (`$C010` bit 7). Open Apple (`$C061`) and Closed Apple (`$C062`)
  are independent buttons; so are the mouse buttons.
- **Mouse card** slot 2 (`$C0A0-$C0AF`, `appletini-one/hdl/apple/mouse_card.sv`,
  see `demos/pinball_construction_set/src/input.s`), used here for
  turning, and as the **60 Hz clock**: mode bit 3 raises an IRQ at the
  start of every vertical blanking, also with the mouse otherwise off;
  writing 3 to the ACK register (`$C0AF`) releases the IRQ (bit 1) and
  clears its cause (bit 0). The sequence byte `$C0A6` counts the PS's
  reports (a torn two-byte X read is detected by reading it before and
  after). Positions are 16 bits, clamped to a window the program sets.
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

Frame publishing: the copy (13,440 reads, 26,880 writes, 236K cycles
measured) starts right after line 0 so that it finishes before the next
one. The kernel decides how to wait (section 8).

## 4. Memory

Two address spaces share page 0, page 1 and the main language card:

| Space | `$0200-$BFFF` is | Holds |
|---|---|---|
| RENDER | main memory (RAMRD and RAMWRT off) | the renderer (BSP walk, segs, planes, sprites), its tables and buffers, the view buffer |
| GAME | RamWorks bank 1 (RAMRD and RAMWRT on, `$C073` = 1) | the game logic (C, cc65) with its data: mobjs, thinkers, player, level state; the C stack |

| Range | Use |
|---|---|
| page 0 | `$02-$DF` kernel and renderer (segment `KZP`), `$E0-$FF` cc65 runtime (its `ZEROPAGE`: `sp`, `sreg`, `regsave`, `ptr1-4`, `tmp1-4`, `regbank`, 26 bytes, 6 free) |
| page 1 | the 6502 stack, shared by both spaces. `$0100-$013F` holds the loader's installer and bank probe during boot only; `$0140-$017F` the debugger's call driver (`tools/doomdbg.py`). The space switch and far access need no page-1 stubs: they run in the language card, which RAMRD does not move |
| main `$0200-$03FF` | renderer tables (`RLOWDATA`) |
| main `$0400-$0BFF` | text/80-column pages: writes are mirrored to the motherboard, so read-only code and tables only (`RTEXTDATA`), loaded once |
| main `$0C00-$8B7F` | renderer code, tables, data and BSS (`RCODE`, `RRODATA`, `RDATA`, `RBSS`); nothing written may live in `$2000-$5FFF` (mirrored) |
| main `$8B80-$BFFF` | `VIEWBUF`, the 13,440-byte view buffer (column `x` at `$8B80 + 84*x`) |
| main LC bank 2 `$D000-$DFFF` | the blit (`KLC2`, 1,574 bytes); later the column/span/sprite inner loops |
| main LC `$E000-$FFF9` | the kernel jump table at `$E000` (`KJT`), then kernel code, data, BSS (`KCODE`, `KRODATA`, `KDATA`, `KBSS`: input block, counters, `kbuf`); `$FFFA-$FFFF` the vectors (NMI, RESET, IRQ) |
| main LC bank 1 `$D000-$DFFF` | free (`KLC1`); only code outside `$D000-$DFFF` may switch the `$D000` bank |
| aux bank 0 `$2000-$9FFF` | the SHR screen, palette, magic |
| aux bank 0 `$0200-$1FFF`, `$A000-$BFFF`, aux LC | spare fast memory (status bar graphics, font, hot tables); aux LC and ALTZP only with interrupts off (the vectors and the stack are the main ones) |
| RamWorks bank 1 `$0200-$B7FF` | GAME space: `GAME.BIN` (cc65's `STARTUP`, `CODE`, `RODATA`, `DATA`, `BSS`) |
| RamWorks bank 1 `$B800-$BFFF` | the cc65 software stack (2 KB, from `$C000` down) |
| RamWorks banks 2.. | the converted data (section 6: `DD_FIRST_BANK`..`DD_LAST_BANK`), then anything else |

Segments and files (`src/doom.cfg`, one ld65 run, symbols resolve across
all areas): the loader `LDRCODE` at `$2000` -> `DOOM.SYSTEM`; the RENDER
areas -> `RENDER.BIN` (an image of main memory from `$0200`, filled up to
`$0C00`, then up to its last byte); the language card -> `LC.BIN` (always
16,384 bytes: bank 2 `$D000-$DFFF`, `$E000-$FFFF`, bank 1 `$D000-$DFFF`);
bank 1 -> `GAME.BIN` (from `$0200`). cc65's standard segment names belong
to GAME; kernel and renderer assembly always names its segments (`K*`,
`R*`).

Memory used by the platform skeleton (`tools/check_link.py`, stand-in
build): zero page 44 of 222 bytes (kernel), 26 of 32 (cc65); RENDER 142
bytes (the test pattern) of 32,640 in `$0C00-$8B7F`, `$0200-$0BFF` free;
LC bank 2 `$D000` 1,574 of 4,096; LC `$E000-$FFF9` 1,769 of 8,186 (of
which BSS 283: the 256-byte `kbuf`, the input block, counters); LC bank 1
0 of 4,096; GAME 918 of 46,592 (the skeleton and the parts of none.lib it
pulls in); `DOOM.SYSTEM` 1,979 bytes.

ProDOS is used only at boot: the loader reads every data file into
RamWorks, then installs the RENDER image, the LC image and the GAME image
and takes the whole machine (the ProDOS global page and the language card
are overwritten). Quit restarts the machine.

**Far memory** (`bank:address`, 3 bytes: lo, hi, bank; in C a `far_t`,
an `unsigned long` with the bank in bits 16-23). Arrays larger than a
bank are split in chunks of `2^k` elements, one chunk per bank; a far
array descriptor is 6 bytes, `{first bank u8, base address u16, element
size u16, log2 elements per chunk u8}` (C: `struct far_array`), element
`i` at bank `first + (i >> k)`, address `base + (i & (2^k-1)) * size`. The
kernel provides `far_read` (far -> near), `far_write` (near -> far),
`far_copy` (far -> far), `far_elem` (descriptor + index -> far address)
and, for C, `far_peek` (one byte), usable from both spaces (section 8); a
transfer never crosses the end of a bank. The renderer's inner loops
select a texture bank once per column and read with RAMRD on.

## 5. Numbers

- Map units are Doom's (16-bit signed). The game uses Doom's `fixed_t`
  16.16 (C `long`) with assembly `FixedMul`/`FixedDiv`; hot geometry in the
  game uses 16-bit map units where Doom's precision is not needed.
- Angles: 16-bit BAM (Doom's 32-bit angle >> 16). **Fine angles: 4096 per
  turn** (BAM16 >> 4, `FINESHIFT` 4). Sines are **Q14** (1.0 = 16384)
  from a quarter-wave table of 1,025 entries; where an angle has its full
  16 bits (the view angle, a seg's angle, a plane span's start) the sine is
  the table interpolated with the angle's low 4 bits (`sin_bam`:
  `s0 + ((s1 - s0) * f >> 4)`, one small multiply), which keeps a seg's
  distance within a fraction of a unit at 2,000 units; per-column angles
  (`xtoviewangle`) are multiples of 16 and need no interpolation.
- The renderer's positions are **sub-units**, 1/16 map unit: the game's
  16.16 `fixed_t` >> 12 (x, y, z of the eye), relative vectors 24-bit
  signed. Scales (pixels per map unit) are 16.16, rows carry 12 fraction
  bits (`HEIGHTBITS`), texture rows are stepped in 8.8, flat coordinates in
  5.11 per axis.
- Arithmetic semantics (what "bit-exact" means): right shifts of signed
  values are arithmetic (floor); multiplies are exact; divisions are exact,
  unsigned or truncating toward zero when signed (`div_trunc`); the
  accumulators of `topfrac`/`bottomfrac`/`pixhigh`/`pixlow` wrap at 32
  bits, texel and flat steppers at 16 bits.
- The renderer is integer-only and is specified exactly by the Python
  reference `tools/refrender.py` (section 7).

## 6. Data (tools/wad2a2.py)

`tools/fetch_freedoom.py` downloads the npm tarball of `kaboom.claude`
1.5.3 and extracts `freedoom1.wad` (SHA-256 `7323bcc1..9f703d`, checked)
and `FREEDOOM-COPYING.txt` to `build/wad/`. `tools/wad2a2.py --wad WAD
--out build/data [--maps E1M1,..]` (default all of E1, about 6 s) writes
the data files, `manifest.json` (files, banks, directory addresses,
per-map array descriptors, names, statistics), `doomdata.inc` (ca65) and
`doomdata.h` (cc65: the same constants plus a struct per record), and
`preview/` (PNGs decoded back from the bank images, contact sheet).
`tools/wadlib.py` is the shared WAD reader. The converter's docstring is
the full specification; the decisions:

**Pixels.** Graphics are in Doom's palette indices at **half resolution**
(the view is 160x84, half of Doom's 320x168). Halving takes each 2x2
block: if more than half of its texels are transparent the result is
transparent, otherwise the palette index nearest (squared RGB distance,
lowest index on ties) to the average of its opaque texels; a block whose
opaque texels are all one index keeps it. Index **247 is never produced
as a colour** (PLAYPAL 247 is black like index 0), so 247 means
"transparent" wherever a picture is stored unpacked (masked textures, UI
pictures). UI pictures (status bar, faces, digits, font `STCFN*`, menus,
`TITLEPIC`, the episode 1 intermission) are halved **vertically only**
(1x2 blocks) since the SHR screen keeps 320 columns (section 3).

- **Textures** are composited as `R_GenerateComposite` (later patches
  overwrite, clipped to the texture), halved, then padded to a power of
  two in both axes **by wrapping** (stored column x = halved column
  x mod w, row y = row y mod h), stored **column major**: texel (u, v) at
  `addr + ((u & wmask) << log2h) + (v & hmask)`. Width ≤ 256 half-res
  texels (E1's widest is 128), height ≤ 128 (E1's tallest is 64). A
  texture with a transparent texel after halving is flagged masked.
  Texture 0 = none (`-`). Textures kept: those of the kept maps' sidedefs,
  the episode's sky (`SKY1`, flagged sky, 128x64), switch partners
  (`SW1xxx`/`SW2xxx`, paired in `SWITCHES` and in each record) and whole
  animation sequences (Doom's `animdefs`), numbered in `TEXTURE1/2` order
  so that animation frames are consecutive.
- **Flats**: 32x32 row major, 1,024 bytes, texel (x, y) at
  `addr + 32y + x`; numbered in WAD order; `F_SKY1` always kept and
  flagged (`DD_SKYFLAT`); each record carries the nearest index to the
  flat's average colour for the shaded-flat fallback.
- **Sprites**: Doom's post format halved, at `addr`: width u8, height u8,
  leftoffset s16, topoffset s16 (both halved, floor), `colofs[width]` u16
  (offset of each column's posts from `addr`), posts `top u8, length u8,
  pixels` with `top = $FF` ending a column. `SPRLUMP` copies width and
  offsets into the directory. `SPRDEF` per sprite (`spritedef_t`) points
  at `numframes` consecutive `SPRFRAME` records of eight u16: bits 0-13
  the `SPRLUMP` index (`$3FFF` if the WAD lacks it), bit 14 "frame
  rotates", bit 15 flipped; a frame without rotations has the same lump
  in all eight. Sprites kept: the E1 monsters (POSS SPOS TROO SARG SKUL
  HEAD BOSS) and the player, every weapon, projectile, effect and pickup,
  the barrel, plus the sprites of every thing placed in the kept maps.
  `SPR_xxxx` constants number them in Doom's `sprnames` order.
- **Level data** (records below): WAD arrays re-laid, names resolved to
  texture/flat indices, 16-bit indices with `$FFFF` = none, plus derived
  fields: segs carry their sidedef and front/back sectors, subsectors
  their sector, linedefs dx/dy/bbox/slopetype/sectors and a zero scratch
  word, sectors a range of the `SECLINES` array (Doom's `P_GroupLines`
  order). Seg angle and offset are the WAD's (BAM16, map units).
  `BLOCKMAP` is the lump as is (u16 words), `REJECT` the lump padded with
  zeros to ceil(sectors²/8) bytes, `THINGS` as in the WAD.

**Banks.** The converter uses banks 2 and up (`DD_FIRST_BANK` ..
`DD_LAST_BANK`), contiguously: the **directory bank** (2), the
**graphics banks**, then the **map banks** (`DD_MAP_FIRST_BANK`). Other
parts allocate banks after `DD_LAST_BANK`.

- Graphics bank: the **16 colormaps** (Doom's `COLORMAP` 0, 2, .. 30;
  map k at `$0200 + 256k`) at `$0200-$11FF`, so the inner loops read
  texel and colormap from the same selected bank; objects (textures,
  flats, sprite patches, UI pictures) from `$1200`, first-fit decreasing
  by size; no object crosses a bank.
- Map banks: arrays from `$0200`. A far array is described by `DESC`
  (bank, base, element size, log2 k of elements per chunk, count,
  chunks): element i is at bank `bank + (i >> k)`, address
  `base + (i & (2^k - 1)) * size`. An array larger than a bank has its
  chunks in consecutive banks at one common base (the converter tries
  k from the largest that fits a bank down by three and keeps the
  combination using the fewest banks); an array that fits one bank is a
  single chunk with 2^k ≥ its count, so the formula holds unchanged.
- Directory bank, from `$0200` in this order (addresses in
  `doomdata.inc` as `DD_<name>`): `PLAYPAL` (14 x 512 bytes, PAL256
  RGB444: byte 2i = `G<<4|B`, byte 2i+1 = `$20|R`, each channel
  round(v·15/255)), `INVULMAP` (`COLORMAP` 32), `MAPDIR` (one `MAP`
  record per slot 9·(episode-1) + map-1; a zero name = not converted),
  `TEXDIR`, `FLATDIR`, `SPRDEF`, `SPRFRAME`, `SPRLUMP`, `UIDIR`, `ANIMS`
  (sequences, 8 tics per frame), `SWITCHES`, `ENDOOM` (4,000 bytes).

**Memory used by E1 (Freedoom 0.13):** 370 textures (1,058 KB), 162 flats
(166 KB), 95 sprites in 632 lumps (336 KB), 259 UI pictures (137 KB): 39
graphics banks. Level data 2.26 MB: E1M1 4 banks, E1M2 6, E1M3 5, E1M4 6,
E1M5 3, E1M6 8, E1M7 14, E1M8 3, E1M9 5. Total **94 banks (2..95), about
6 MB**: more than the 4 MB minimum of section 4, within the Appletini's
8 MB. With `--shared-map-banks` every map is placed at the same banks
(`DD_MAP_BANKS_SHARED` = 1) and the whole of E1 needs 54 banks (2..55),
which fits 4 MB, provided the kernel loads a map's files at level start.

**Data files.** One or more files per region (`DIR.1`, `GFX.1`..`GFX.n`,
`E1M1.1`..), each at most 128 KB: a 256-byte header (+0 `"A2DM"`, +4
version 1, +5 segment count n ≤ 49, +6 two zero bytes, from +8 n entries
of bank u8, address u16, length u16, zero padding), then the segments'
bytes in order; the loader copies each to bank:address. A bank's used
range is one run from `$0200` (it may continue in the next file).
`doomdata.inc` has the load list as the macro `DD_FILE_TABLE`
(length-prefixed names, 0 ends).

**Limits.** A map is skipped, and listed with the reason in the manifest's
`skipped` and on the console, if a reference is broken or a count exceeds
`LIMITS` (vertexes, linedefs, sidedefs, sectors, segs, things, sector
lines ≤ `$FFFE`; subsectors and nodes ≤ `$7FFF`; blockmap ≤ one bank);
`--limit segs=N` etc. tighten them for the renderer (section 7). All nine
E1 maps pass the default limits.

**Record layouts** (little endian; s16/u16 16-bit; `c8` 8 chars, `b88`
88 raw bytes; the same names as `<TAG>_<FIELD>` offsets and `<TAG>_SIZE`
in both include files, and as `<tag>_t` structs in `doomdata.h`):

| Record | Bytes | Fields (offset, name, type) |
|---|---|---|
| `VERTEX` | 4 | +0 `x` s16, +2 `y` s16 |
| `SEG` | 16 | +0 `v1` u16, +2 `v2` u16, +4 `angle` u16 (BAM16, from the WAD), +6 `linedef` u16, +8 `sidedef` u16 (the seg's side of its linedef), +10 `offset` s16 (map units along the linedef, from the WAD), +12 `frontsector` u16, +14 `backsector` u16 ($FFFF unless the linedef is two-sided) |
| `SSECTOR` | 8 | +0 `numsegs` u16, +2 `firstseg` u16, +4 `sector` u16 (sector of the first seg's sidedef); 2 bytes padding |
| `NODE` | 32 | +0 `x` s16, +2 `y` s16, +4 `dx` s16, +6 `dy` s16, +8 `bbox0_top` s16 (right child's box), +10 `bbox0_bottom` s16, +12 `bbox0_left` s16, +14 `bbox0_right` s16, +16 `bbox1_top` s16 (left child's box), +18 `bbox1_bottom` s16, +20 `bbox1_left` s16, +22 `bbox1_right` s16, +24 `child0` u16 (right (front); bit 15 = subsector), +26 `child1` u16 (left (back); bit 15 = subsector); 4 bytes padding |
| `SIDEDEF` | 12 | +0 `xoffset` s16, +2 `yoffset` s16, +4 `toptexture` u16 (TEXDIR index, 0 = none), +6 `bottomtexture` u16, +8 `midtexture` u16, +10 `sector` u16 |
| `LINEDEF` | 32 | +0 `v1` u16, +2 `v2` u16, +4 `flags` u16, +6 `special` u8, +7 `slopetype` u8 (0 horizontal, 1 vertical, 2 positive, 3 negative), +8 `tag` u16, +10 `side0` u16, +12 `side1` u16 ($FFFF = one-sided), +14 `dx` s16, +16 `dy` s16, +18 `bbox_top` s16, +20 `bbox_bottom` s16, +22 `bbox_left` s16, +24 `bbox_right` s16, +26 `frontsector` u16, +28 `backsector` u16 ($FFFF = none), +30 `scratch` u16 (zero; free for the game (validcount)) |
| `SECTOR` | 16 | +0 `floorheight` s16, +2 `ceilingheight` s16, +4 `floorpic` u16 (FLATDIR index), +6 `ceilingpic` u16, +8 `lightlevel` u8, +9 `special` u8, +10 `tag` u16, +12 `linecount` u16, +14 `firstline` u16 (index into SECLINES) |
| `SECLINE` | 2 | +0 `line` u16 |
| `THING` | 10 | +0 `x` s16, +2 `y` s16, +4 `angle` s16 (degrees), +6 `type` u16 (doomednum), +8 `flags` u16 |
| `DESC` | 8 | +0 `bank` u8 (bank of chunk 0), +1 `addr` u16 (base address), +3 `elsize` u8 (element size), +4 `log2` u8 (log2 elements per chunk), +5 `count` u16 (elements), +7 `chunks` u8 (banks used) |
| `MAP` | 128 | +0 `name` c8 ("E1M1", NUL padded; zero = absent), +8 `arrays` b88 (11 DESC records, index MAPARR_*), +96 `sky` u16 (TEXDIR index of the sky texture), +98 `firstbank` u8, +99 `numbanks` u8; 28 bytes padding |
| `TEX` | 16 | +0 `bank` u8, +1 `addr` u16, +3 `log2w` u8 (log2 stored width), +4 `wmask` u8 (stored width - 1), +5 `hmask` u8 (stored height - 1), +6 `flags` u8 (1 masked, 2 sky, 4 animated, 8 switch), +7 `log2h` u8 (log2 stored height), +8 `width` u16 (Doom width, map units), +10 `height` u16 (Doom height, map units), +12 `anim_next` u16 (next frame (self if not animated)), +14 `switchtex` u16 (SW1/SW2 partner, 0 = none) |
| `FLAT` | 8 | +0 `bank` u8, +1 `addr` u16, +3 `flags` u8 (1 sky, 2 animated), +4 `anim_next` u16 (next frame (self if not animated)), +6 `color` u8 (nearest index to the average colour); 1 bytes padding |
| `SPRDEF` | 4 | +0 `firstframe` u16 (SPRFRAME index), +2 `numframes` u8; 1 bytes padding |
| `SPRFRAME` | 16 | +0 `rot0` u16, +2 `rot1` u16, +4 `rot2` u16, +6 `rot3` u16, +8 `rot4` u16, +10 `rot5` u16, +12 `rot6` u16, +14 `rot7` u16 |
| `SPRLUMP` | 8 | +0 `bank` u8, +1 `addr` u16, +3 `width` u8, +4 `left` s16 (halved leftoffset), +6 `top` s16 (halved topoffset) |
| `UIPIC` | 12 | +0 `bank` u8, +1 `addr` u16, +3 `height` u8, +4 `width` u16, +6 `left` s16, +8 `top` s16 (halved), +10 `flags` u8 (1 = has transparent pixels); 1 bytes padding |
| `ANIM` | 4 | +0 `kind` u8 (0 flat, 1 texture), +1 `count` u8, +2 `first` u16 (first frame index) |
| `SWITCH` | 4 | +0 `off` u16 (SW1 texture), +2 `on` u16 (SW2 texture) |
| `FILESEG` | 5 | +0 `bank` u8, +1 `addr` u16, +3 `length` u16 |

## 7. The renderer (src/render/, tools/refrender.py)

Doom's renderer (`r_bsp`, `r_segs`, `r_plane`, `r_things`, `r_draw`), in
Doom's order and with Doom's clipping, in integer arithmetic sized for the
65C02. **`tools/refrender.py` is the bit-exact specification**: it reads
only the converted data (the bank images and the directory addresses of
section 6), renders a view into the 160x84 column-major view buffer and
writes a PNG as the Appletini shows it (each game pixel 4x4 of the 640x400
output, `PLAYPAL` 0 in RGB444). The 6502 renderer is tested frame by
frame against it: the view buffer must match byte for byte.
`tools/gen_tables.py` writes every table from the reference's own code,
so both sides read the same numbers.

    python3 tools/refrender.py --map E1M1 --start --out view.png --stats
    python3 tools/refrender.py --map E1M1 --view X Y Z ANGLE [--tic N] [--extralight N] [--shaded]
    python3 tools/refrender.py --deliverables      # every map: start + 3 views -> build/refrender/
    python3 tools/refrender.py --sweep 40          # work statistics over random views
    python3 tools/gen_tables.py --out build        # build/render/tables.inc, tables.s

**Inputs of a frame**: the eye x, y, z in sub-units (section 5), the angle
(BAM16), the map, the game tic (texture and flat animation: frame
`first + (tic/8 + i - first) mod count`), `extralight` (0-2, added to
light levels), an optional fixed colormap (0-15), the things to draw (x, y,
z sub-units, angle, `SPR_` number, frame with bit 15 = full bright, shadow
flag; the renderer files each under its sector and projects a sector's
things when the BSP walk first enters it, as `R_AddSprites`) and the
weapon layers (sprite, frame, sx, sy in Doom's 320x200 16.16).
`spawn_things` places a map's THINGS as spawned (skill, spawn-state frames
and full-bright flags of the common Doom 1 types, hanging things from the
ceiling, spectres as shadows), `player_start` gives player 1's eye.

**Projection.** Doom's 320x168 low-detail view halved in both directions:
`centerx` 80, `centery` 42, one focal length (`PROJ`) of 80 pixels for
columns and rows, so a row stands for two of Doom's rows and Doom's aspect
is kept without a correction factor; field of view 90 degrees
(`clipangle` = `$2010`, Doom's `R_InitTextureMapping` at 4096 fine
angles). Light levels follow Doom's scales exactly (wall/sprite light
index = scale >> 11, Doom's >> 12 of its twice-larger scale; plane light
index = distance >> 8 sub-units = Doom's distance >> 20); a Doom colormap
number c is the stored colormap c >> 1.

**The frame**, step by step (names are the reference's):

1. *BSP walk* (`render_bsp`, `check_bbox`, `point_on_side`): front to
   back; the side test is exact (`dy*ndx >= ndy*dx`, 40-bit products,
   Doom's sign shortcut first); a node's back child is visited if its box
   passes `R_CheckBBox` (two `point_to_angle`, clip to +-`clipangle`,
   `viewangletox`, the solid-seg list). The 6502 keeps an explicit node
   stack (`MAXBSPDEPTH`).
2. *Segs* (`add_line`): the angles of both vertexes by `point_to_angle`
   (Doom's octants; slope = (small << 10) / big, exact, into
   `tantoangle`; cached per vertex per frame: one division per vertex),
   back-face and field-of-view clipping in BAM16, columns by
   `viewangletox`, then `R_ClipSolidWallSegment` / `R_ClipPassWallSegment`
   and Doom's closed-door / window / invisible-line cases.
3. *Wall range* (`store_wall_range`): `rw_distance` = (v1 - eye) . n and
   `rw_offset` = (eye - v1) . d + (xoffset + seg offset) << 4, dot products
   with the unit normal n (seg angle + 90) and direction d (`sin_bam`, two
   24x16 multiplies each), exact where Doom's `R_PointToDist` is not. The
   scale at both ends is Doom's `R_ScaleFromGlobalAngle`: num = 80 *
   sin(b), den = rw_distance * sin(a) >> 14, scale = (num << 6) / den,
   clamped to [256, 64 << 16] (`den <= 0` or overflow: the maximum;
   `num <= 0`: the minimum); `scalestep` = (scale2 - scale1) / (x2 - x1)
   truncated. `topfrac` = (42 << 12) - (worldtop * scale >> 8) and its step
   -(scalestep * worldtop >> 8), likewise bottom, `pixhigh`, `pixlow`
   (32-bit). Pegging, silhouettes, `markfloor`/`markceiling` and the
   sky hack are Doom's. Light: sector light >> 4 + extralight, -1 on
   horizontal and +1 on vertical lines, `scalelight[light][min(scale >> 11,
   47)]`.
4. *Columns* (the seg loop): `yl` = ceil(topfrac), `yh` = floor(bottomfrac),
   clipped; plane marks as Doom (one addition: when a sky-hack ceiling edge
   lies below the floor edge, the ceiling mark stops at `yh`, so no pixel
   is marked twice); texture column = (rw_offset - (tan(a) * rw_distance
   >> 12)) >> 5 with a = (rw_centerangle + xtoviewangle[x]) >> 4 (clamped
   to 0..2047); `iscale` (texels per pixel, 16.16) = the reciprocal table
   at the scale's 9-bit mantissa, shifted; the column piece: frac =
   (texturemid << 11) + (yl - 42) * iscale, then 8.8 stepping (start frac >>
   8, step (iscale + 128) >> 8), texel row `(f >> 8) & hmask`, pixel =
   colormap[texel]. Upper and lower pieces share the column's texture
   column, scale and colormap. Masked columns store their texture column.
5. *Planes* (`draw_planes`): Doom's visplanes (`R_FindPlane`,
   `R_CheckPlane`; columns of a plane are rows `top..bottom`, `$FF` =
   unused, bottom 0), drawn with `R_MakeSpans`. A span (`map_plane`):
   distance = |height - eye| * yslope[y] >> 8 (cached per row and height),
   steps = distance * base >> 15 with base = cos/sin(angle - 90) * 8/5,
   length = distance * distscale[x1] >> 14, start = (eye << 6) +
   (cos/sin(angle) * length >> 8) (angle interpolated), each 16-bit 5.11
   (x, and -y as Doom); texel = flat[(yfrac >> 11) * 32 + (xfrac >> 11)];
   colormap `zlight[light][min(distance >> 8, 127)]`. Sky planes are drawn
   as columns: texture column (angle >> 7) & 127 (512 per turn, SKY1
   repeats 4 times as in Doom), row (y + 8) & 63, colormap 0.
   **Flat-shaded mode** (`--shaded`, `Renderer(shaded=True)`): no
   visplanes; each plane piece is filled at once in the seg loop with the
   flat's average colour through `scalelight[light][min(scale >> 11, 47)]`
   of the wall at that column (the sky stays textured). A visplane
   overflow uses the same fill for the pieces that find no plane.
6. *Masked* (`draw_masked`): vissprites sorted by scale (ties in order of
   projection), each clipped by the drawsegs as `R_DrawSprite` (with
   `R_PointOnSegSide`, exact) and drawn post by post (`R_DrawMaskedColumn`:
   post rows ceil(top)..floor(bottom - 1/65536), 8.8 stepping, the post
   index not masked: rounding may read the byte after a post, as in Doom);
   then the remaining two-sided middles (`R_RenderMaskedSegRange`: rows
   where the texture exists, 247 skipped); then the weapon (one texel per
   pixel, x = 80 + (sx - 160)/2 - left, texturemid = (100.5 - sy)/2 + top,
   lit by the eye's sector at the brightest scale unless full bright).
   Shadows use Doom's fuzz (the pixel one row above or below through
   colormap 3, rows 1..82, `fuzzpos` reset each frame).

Sprite projection: `tz` = tr_x cos - (-tr_y sin), in sub-units, not drawn
under `MINZ` (4 units) or outside `|tx| > 4 tz`; `xscale` = (80 << 20) / tz;
rotation ((angle to thing - thing angle + $9000) >> 13); x1/x2 from the
halved offsets and width (one texel = 2 units); `iscale` from the same
reciprocal table; light index xscale >> 11 into the thing's sector's
`scalelight` row.

**Tables** (built by `Tables` in the reference, written by
`gen_tables.py`; multi-byte tables as one byte plane each, `NAME_lo`,
`NAME_mid`, `NAME_hi`):

| Table | Entries x bytes | Bytes | Segment | Use |
|---|---|---|---|---|
| `viewangletox` | 1,027 x 1 | 1,027 | `RTEXTDATA` | column of a clipped fine angle (from `VATX_FIRST` = `$1FF`) |
| `xtoviewangle` | 161 x 2 | 322 | `RTEXTDATA` | BAM16 angle of each column |
| `yslope` | 84 x 2 | 168 | `RTEXTDATA` | 80 / abs(y - 41.5), 8.8 |
| `coladdr` | 160 x 2 | 320 | `RTEXTDATA` | `VIEWBUF + 84x` |
| `fuzzoffset` | 50 x 1 | 50 | `RTEXTDATA` | +-1 row |
| `finesine` | 1,025 x 2 | 2,050 | `RRODATA` | quarter-wave sine, Q14 |
| `tantoangle` | 1,025 x 2 | 2,050 | `RRODATA` | BAM16 of atan(i / 1024) |
| `finetangent` | 1,024 x 3 | 3,072 | `RRODATA` | tan, 12 fraction bits, positive half (tan[2047 - a] = -tan[a]) |
| `recip` | 256 x 3 | 768 | `RRODATA` | 2^31 / (m + 0.5), m = 256..511 |
| `distscale` | 160 x 2 | 320 | `RRODATA` | 1 / cos(column angle), Q14 |
| `scalelight` | 16 x 48 | 768 | `RRODATA` | colormap by light and scale |
| `zlight` | 16 x 128 | 2,048 | `RRODATA` | colormap by light and distance |
| `mul_sqr`, `mul_nsqr` | 2 x 512 x 2 | 2,048 | `RRODATA` | quarter-square 8x8 multiply |

Total 1,887 bytes in `RTEXTDATA` (of 2,048) and 13,124 in `RRODATA`.
`tables.inc` also has the constants (view, angles, widths, lighting,
limits).

**Limits** (named constants in both files). Measured by `--sweep 40`: 360
random views inside the nine maps, things spawned, limits lifted:

| Limit | Value | p90 / max seen | On overflow |
|---|---|---|---|
| `MAXSOLIDSEGS` | 82 | - | cannot overflow (80 ranges + 2 sentinels over 160 columns) |
| `MAXDRAWSEGS` | 160 | 91 / 197 | the wall is drawn but not recorded: it clips no sprite, has no masked middle |
| `MAXVISPLANES` | 128 | 36 / 76 | the pieces that find no plane are filled flat-shaded at once |
| `MAXOPENINGS` | 2,048 bytes | 878 / 1,603 | the drawseg keeps no clip arrays and no masked middle (1 byte per clip column, 2 per masked column) |
| `MAXVISSPRITES` | 96 | 26 / 83 | further things are not drawn |
| `MAXBSPDEPTH` | 64 | - / 43 | the deeper subtree is not visited |

Nothing overflows in the deliverable views; the tests force every
overflow and check that the view is still complete.

**Memory for the 6502 renderer** (recommended; the implementer records
the final map in section 4): the tables as above; drawsegs (about 26 bytes
each: x1, x2, 3-byte scales and step, silhouette, 3-byte silhouette
heights, three opening pointers, seg: 4.2 KB for 160), openings (2 KB), vissprites
(about 24 bytes: 2.3 KB) and the clip arrays in main memory; the
visplanes (128 x 324 bytes = 41.5 KB) in a RamWorks bank of the renderer's
own after `DD_LAST_BANK`, with a seg's plane marks gathered in main memory
and copied at the end of the wall range, and a plane's columns copied back
before its spans (the copies cost a few bytes per marked column; a used
bitmap per plane in main memory serves `R_CheckPlane`).

**Work per frame** (the `--stats` counters; `build/refrender/stats.json`
has them for every deliverable view). Over the 360 random views:

| Counter | mean | p90 | max |
|---|---|---|---|
| BSP nodes visited (= bbox checks) | 55 | 127 | 280 |
| subsectors | 32 | 81 | 181 |
| segs considered / facing / wall ranges | 102 / 45 / 38 | 255 / 117 / 91 | 550 / 223 / 197 |
| wall columns (seg loop iterations) | 538 | 1,008 | 1,630 |
| wall pieces / wall pixels | 285 / 9,427 | 499 / 13,311 | 978 / 13,440 |
| sky pixels | 622 | 1,897 | 13,440 |
| span rows (distance computed) / spans / span pixels | 62 / 120 / 3,391 | 122 / 277 / 6,662 | 261 / 606 / 9,241 |
| sprite columns / posts / pixels | 105 / 142 / 869 | 204 / 293 / 1,529 | 347 / 576 / 12,362 |
| masked-middle pixels | 259 | 765 | 8,388 |
| weapon pixels (pistol) | 447 | 447 | 447 |
| divisions: slope / scale / step / thing | 199 / 70 / 32 / 14 | 470 / 166 / 74 / 37 | 1,025 / 367 / 170 / 91 |
| multiplies: side / seg / column / piece / span / thing / post | 111 / 455 / 365 / 428 / 545 / 90 / 284 | 254 / 1,090 / 654 / 791 / 1,197 / 212 / 586 | 560 / 2,286 / 1,132 / 1,554 / 2,178 / 538 / 1,152 |

A "column" multiply is the 24x24 tangent product (only its low 25 bits
matter: the texel column is bits 17-24); "seg" multiplies are 24x16
(distances, offsets) or 24x24 (heights x scale); "piece"/"post" ones are
8x24 or 8x16.

**Deviations from Doom**, all deliberate: positions at 1/16 unit; the
dot-product distance and offset; 4096 fine angles with interpolated
sines; Doom's overflow errors replaced by the degradations above; the
sky-hack double mark removed; the fuzz position reset per frame;
animations relative to their first frame; two-sided middles from unpacked
textures (247 = hole) drawn only over the texture's height.

**Tests**: `tests/test_refrender.py`: determinism and golden SHA-256 of
six view buffers (fixed eyes, one at an odd sub-unit position and angle) (a change of the specification must update them, and
the 6502 renderer with them); every pixel written exactly once by walls,
planes and sky in 36 views, textured and flat-shaded; forced overflow of
every limit; agreement with an independent floating-point raycaster
(walls, pegging, texture columns, planes, sky: about 90% of pixels equal,
the rest at edges and texel boundaries); the generated tables equal the
reference's and assemble with ca65.

### 7.1 The 6502 renderer (src/render/)

Walls, planes and sky, byte for byte the reference's `Renderer(masked=
False)` (the masked phase, sprites, two-sided middles and the weapon, is
the next part; see the hooks below). Seven files:

| File | Holds |
|---|---|
| `rdefs.inc` | shared equates (`ROWBIAS`, `RENDER_BANK`, the `RENDER_BANK` layout, queue size), the renderer's zero page and routine names |
| `rmain.s` | `render_frame`, the packet, `map_load`, `frame_setup`, the far-array element address, record fetches and the per-frame caches, `point_on_side`, the BSP walk, `check_bbox`, `subsector`, `add_line`, the solid-seg list |
| `rsegs.s` | `store_wall_range`: scales, pegging, silhouettes, marks, the seg loop, the texture column, the column pieces, the visplane marks and the drawseg |
| `rplane.s` | visplanes (`find_plane` hashed, `check_plane`), texture/flat animation and records (cached), the sky column, `draw_planes`, `make_spans`, `map_plane` |
| `rmath.s`, `rfmul.s`, `rmul.inc` | multiplies (quarter squares), divisions, sines, `point_to_angle`, the tangent; the byte tables of the seg loop |
| `rlc.s` | everything that runs with RAMRD on (language card bank 1): bank reads, the column-piece queue and its drawer, the span drawer, the visplane check |
| `rhooks.s` | `r_add_sprites` and `r_masked`, empty until the masked phase |

**Interfaces.** `render_frame` (called by the frame loop, RENDER space)
switches the language card's `$D000` to bank 1 for itself and back to bank
2 (the blit) before it returns; interrupts may stay on (the VBL handler
touches neither `$C073` nor RAMRD/RAMWRT). Three bytes in the language
card, seen by both spaces:

- `render_map` (C `extern unsigned char render_map;`): the MAPDIR slot to
  draw, 9 x (episode - 1) + map - 1; `$FF` (the initial value) draws
  nothing and leaves the view buffer alone. **The game sets it when a
  level starts**; a change loads the MAP record (array descriptors, sky)
  and the animation list on the next frame.
- `render_shaded` (C `render_shaded`): 0 textured floors and ceilings, else
  flat-shaded; its initial value is the build option `RENDER_SHADED`
  (`make AFLAGS+=-DRENDER_SHADED=1`, default 0).
- The packet: `render_frame` reads the 40-byte header of `_rview` (bank 1);
  the things are **not copied** (2,560 bytes of main memory, and 42K cycles
  a frame, for data only the masked phase reads): `rv_thing` (A = index)
  reads one into `rv_tbuf` with one bank read. The game does not run while
  the frame is drawn, so this is the packet as the game left it.

Hooks for the masked phase (Doom's order is kept exactly): `r_add_sprites`
is called with A/X = the sector at its first visit in the frame, before its
segs (R_AddSprites), and the visit order is also listed in `vs_list_lo/hi`
(`vs_count`, 256 kept); `r_masked` is called after the planes. The drawsegs
(`ds_n`) and their openings are in `RENDER_BANK`:

| Drawseg (26 bytes at `DS_BASE + 26n`) | |
|---|---|
| +0 x1, +1 x2 | columns |
| +2 scale1, +5 scale2, +8 scalestep | 3 bytes each (16.16; the step signed) |
| +11 silhouette | `SIL_BOTTOM` 1, `SIL_TOP` 2 |
| +12 bsilheight, +15 tsilheight | 3 bytes signed sub-units; `$7FFFFF` = MAXINT, `$800000` = MININT |
| +18 sprtopclip, +20 sprbottomclip | the `RENDER_BANK` address of column x1's byte in the openings, or 0 none, 1 "screenheight" (84), 2 "negone" (-1) |
| +22 maskedtexturecol | the address of column x1's 2 bytes (texture column & 255, then 0: the masked phase's "drawn" mark), or 0 |
| +24 seg | the seg's index |

Clip values in the openings are rows + `ROWBIAS` (64), saturated to
0..255 (see below; -2, Doom's sprite-clip sentinel, is exact). The
openings are allocated exactly as the reference counts them (`MAXOPENINGS`
bytes: 2 per masked column first, then 1 per clip column), so the same
drawsegs lose their clips on overflow.

**Memory** (the final map; section 4's table is the platform's):

| Area | Use |
|---|---|
| zero page `$02-$D8` | the kernel's 41 bytes and the renderer's 174 (multiply/divide operands, the seg loop's accumulators, pointers, the eye); 7 bytes free |
| main `$0200-$03FF` (`RLOWDATA`) | the visited-sector list (512) |
| main `$0C00-$1DDB` (`RLOBSS`, rw in the file) | packet header, BSP node stack (64 x 11), MAP record, the vertex cache (128 slots: angle and coordinates), a visplane's columns copied back, span starts, the range's plane marks and masked columns, the texture-record cache (32), the per-column sines (161), the per-column sin/cos cache of the spans (160); 480 bytes free below the tables |
| main `$1FBC-$52FF` (`RRODATA`) | the generated tables (13,124 bytes; the start puts the quarter-square tables on page boundaries, asserted at link time) |
| main `$5300-$5D26` (`RCODE`, read-only window) | code that is never modified: math, planes (2,599 bytes; 729 free) |
| main `$6000-$80E1` (`RHICODE`) | code with self-modified operands and the rest: BSP, segs, seg loop, spans (8,418) |
| main `$80E2-$89E0` (`RBSS`) | frame state, caches (sectors 64 slots), clip arrays, solid segs (2,303); 415 bytes free |
| LC bank 1 `$D000-$DB9E` (`RLC1`) | the RAMRD code, the span tables, the piece queue (64 x 12 bytes), `subsector`/`add_line`/clipping (2,975; 1,121 free) |
| LC `$E6F4-$FEC4` (`RLCHI`, `RLCBSS`) | `render_frame` and the frame setup, the unrolled multiplies and divisions, the shift tables (shr4/shl4/sar4/bitlen), `render_map`, `render_shaded`; visplane headers (7 x 128) and the span row cache (84 rows); 309 bytes free |
| LC bank 2 | not used by the renderer |
| RamWorks `RENDER_BANK` = `DD_LAST_BANK` + 1 | visplane columns `$0200-$A4FF` (128 x 324: top and bottom rows of columns -1..160), drawsegs `$A500-$B53F`, openings `$B540-$BD3F` |

**How it runs** (the decisions):

- *Bank access.* Map records are read with `rb_read` (language card, RAMRD
  on for the copy only): `elem_addr` turns an index into bank:address by
  the MAP record's descriptors (chunk = index >> log2, offset by shift
  tables). `$C073` is written only when the bank changes (`cur_bank`).
  Sectors (64 slots) and vertexes (128 slots, with their angle from the
  eye) are cached per frame, texture records until the map changes, a
  seg's sidedef, flags, normal, distance, offset and light for all the
  wall ranges of the seg. All `RENDER_BANK` writes of a wall range (new
  visplane columns, the range's marks, the drawseg and its openings) go in
  one RAMWRT session at the end of the range; code runs from main memory
  meanwhile, so the session writes nothing but the bank and the zero page.
  About 1,900 `$Cxxx` accesses a frame (140K cycles).
- *Rows* are bytes, row + `ROWBIAS` saturated to 0..255: a row the
  reference would carry past -64..191 only ever meets values in -2..85
  (the clip arrays keep their extremes' order), so marks, pieces, clips and
  the sprite clipper's comparisons are unchanged. The seg loop's 32-bit
  accumulators are kept biased (+$40FFF ceil, +$40000 floor) so a row is
  bits 12..19 of the sum by two table lookups; a sum the bias carried past
  2^31 is recognised and saturates high (the reference's s32 wrap).
- *The texture column*: (rw_offset - (tan(a) x rw_distance >> 12)) >> 5 is
  computed as ((rw_offset << 12) + 4095 - tan x rw_distance) >> 17 (the
  same floor, one subtraction), with |tan| x |rw_distance| mod 2^32 and the
  sign applied by adding or subtracting; only the low 8 bits are kept
  (every texture is at most 256 wide). It is computed only for columns that
  draw a piece (or keep a masked column).
- *Pieces*: every wall, sky and flat-shaded column piece goes into a
  64-entry queue in the language card (bank, address, count, texture
  column, 8.8 fraction, step, colormap page, hmask); `q_flush` draws a whole
  wall range (or a plane's sky, or a full queue) in one RAMRD session,
  `$C073` rewritten only between banks. The drawer is Doom's
  R_DrawColumn (self-modified operands, texel through the colormap by a
  patched `lda $cm00`): 40 cycles a pixel.
- *Planes*: visplanes in `RENDER_BANK` (the recommendation), found through
  a 64-bucket hash that keeps creation order (the reference returns the
  first match). A plane's columns are initialised as its range grows (the
  reference only ever reads within minx-1..maxx+1), and a plane's columns
  are copied back to main memory once, before its spans; a column equal to
  the previous one starts and ends no span and is skipped. `map_plane`
  caches the row's distance and steps (per row and plane height, as the
  reference) and each column's sine and cosine (per frame); the span loop
  (language card, RAMRD on for the span) is about 100 cycles a pixel: two
  16-bit fraction adds, the 5.11 texel address through two tables, the
  colormap, the 84-byte stride.
- *Arithmetic*: 8x8 products by quarter squares through four zero-page
  pointers, unrolled per operand shape and result width (`MULU`/`MULUB`),
  zero bytes skipped: about 50 cycles a product. R_ScaleFromGlobalAngle
  divides 22 quotient bits (whole zero bytes skipped, a 16-bit remainder
  when the denominator allows): about 1,000 cycles; its den <= 0 and
  num <= 0 cases are decided from the signs before any product
  (sin(anglea), a column constant, comes from a table). point_to_angle's
  slope is a 10-bit division (16-bit when the denominator allows). The
  sines are table loads with the interpolation product by quarter squares.
- *Flat-shaded mode* has no visplanes: `find_plane` returns
  `PL_OVERFLOW`, and every plane piece is queued at once as a fill (or a
  sky column) by the seg loop, as the reference's overflow path.

**Measured** (`tests/test_render_core.py -v`, the py65 test machine, TURBO
accounting): 109 views (the 36 deliverables, the 6 golden eyes, 9
flat-shaded, 40 random views of `--sweep`'s generator, 15 animation tics,
3 fixed-colormap/extralight), every one byte-identical to the reference:

| Set | mean | p90 | max |
|---|---|---|---|
| all 109 | 3.36M | 5.77M | 7.15M |
| deliverables (36) | 3.29M | 5.86M | 7.15M |
| random (40) | 2.86M | 5.03M | 5.55M |
| flat-shaded (9, the starts) | 3.47M | 5.12M | 5.12M |

**The target (mean 1.5M, p90 2.5M) is not met**: about 2.2x over. Where a
frame goes (20 views, 3.48M on average; `--profile`):

| Phase | per frame | work |
|---|---|---|
| wall ranges: setup | 748K (21%) | 51 ranges: two scale divisions, ~10 products, marks, drawseg: ~14K each |
| wall columns: the seg loop | 592K (17%) | 600 columns: accumulators, rows, marks, clips (~250); texture column, iscale, colormap (~600, when a piece is drawn); pieces (~400 each) |
| pixels: wall and sky columns | 433K (12%) | 9,400 pixels at 40, plus ~170 per piece |
| pixels: spans | 432K (12%) | 4,000 pixels at ~100 |
| planes: span setup | 346K (10%) | 160 spans: length and two trigonometric products (~2K each), row cache |
| segs: add_line, clipping | 266K (8%) | 145 segs: fetch, vertex angles (divisions), clipping |
| BSP: bbox checks / subsectors / walk | 199K / 173K / 124K | 70 nodes, 45 subsectors: record fetches (~500-850 each), two point_to_angle per box |
| planes: visplanes, make_spans | 127K (4%) | copy-back, R_MakeSpans |

By kind: bookkeeping code 41%, pixel loops 26%, multiplies 14%, divisions
9%, bank access 7%, sines 2%. What would still help, roughly in order: a
tighter store_wall_range and seg loop (hand scheduling; the bookkeeping
share); reading a subsector's segs in one bank read and fixed-size
unrolled record copies (~50K); a two-way row cache for spans (~50K);
spans queued per plane (one RAMRD session per plane, ~25K). Beyond that the
specification itself sets the floor: every wall range needs two
22-bit divisions and ~10 wide products, every textured column a 24x24
product, every span three; at ~50 cycles an 8x8 product the arithmetic
alone is ~800K a frame. A cheaper specification (e.g. 16-bit accumulators
where the ranges allow, texture columns stepped per range) or the
flat-shaded mode on busy frames are the lead's call.

**Tests** (`tests/test_render_core.py`): the 109 views above; the four
limits forced low in both the program (its immediate operands patched in
memory) and the reference (MAXVISPLANES 20, MAXDRAWSEGS 40, MAXOPENINGS
200, MAXBSPDEPTH 8: the degraded views are identical); `sin_bam`,
`point_to_angle`, `div_scale` and `div_step` against the reference's
arithmetic on sampled and edge inputs. `--view MAP X Y Z ANGLE` renders
one view (diff, cycles, PNGs), `--profile` gives the phase and routine
breakdown above. The tests build `make BUILD=build/rtrack/` (with
`RENDER_GAMESRC` naming a snapshot of the GAME sources when they are in
flux) and use `build/data`.

## 8. The kernel (src/kernel/)

Boot and load, bank check, video set-up (PAL256), space switching, far
access, the frame loop, timing, the blit, input, sound, reboot. Every
routine lives in the main language card except the loader; the numbers
below are from the test machine in TURBO (73 cycles per `$Cxxx` access).

**Boot** (`loader.s`, `DOOM.SYSTEM` at `$2000`): 40-column text with a
"LOADING" line and the file being read; `/RAM` disconnected (it lives in
aux bank 0); the RamWorks size (section 2; fewer than 64 banks: error
`$F2`); the prefix (`GET_PREFIX`, else the directory of `$0280`); the
volume directory is read (4 blocks) and **every BIN file with aux type
$0000 is loaded**, in directory order: nothing about the data set is
built into the loader. Each is a data file of section 6 (256-byte header
`"A2DM"`, version 1, up to 49 segments `bank u8, address u16, length
u16`): each segment must lie in `$0200-$BFFF` of a bank `2..banks-1`
(errors `$F3`, `$F2`); it is read through the MLI into a 7.5 KB staging
buffer (`$A000`) and copied to its bank with RAMWRT on (only the zero
page is written meanwhile). Then `GAME.BIN` (aux type `$0200`) into bank
1 at `$0200`, `RENDER.BIN` (`$0200`) into aux bank 0 at `$0200` (its own
addresses; the SHR area is not in use yet), `LC.BIN` (`$D000`) into main
`$6000-$9FFF`. Install, interrupts off: the language card from
`$6000-$9FFF`; then a routine copied to `$0100` (it runs with RAMRD on)
copies aux bank 0 over main memory page by page, over the loader and the
ProDOS global page, and jumps to `kernel_start` with A = the bank count.
On an error before the install: a message with the code (`$F0` bad
header, `$F1` short file, `$F2` memory, `$F3` segment, `$F4` image too
large, `$F6` no path, or a ProDOS code), a key, ProDOS QUIT. The full
Freedoom data set (39 files, 4.23 MB) boots in 68.6 M cycles in the test
machine (0.9 s at 75 MHz plus the disk).

**Start** (`kstart.s`): stack, zero page, kernel and renderer BSS, view
buffer cleared; `kbanks` = the bank count; `video_init`; `input_init`
(no mouse card: `kernel_crash` code 2, there is no clock without it);
the GAME space's C start-up (`game_boot`: `sp` = `$C000`, `zerobss`,
`game_init()`) through `call_game`; interrupts on; the frame loop.
`kernel_crash` (A = code; a BRK is code 1) shows "DOOM CRASH $cc" on the
text screen and stops at `kernel_crash_stop`; `kernel_reboot` goes to
the ROM's cold start (the RESET vector of the card points there too).

**Spaces** (`space.s`): `space_game` (`$C073` = 1, RAMRD and RAMWRT on,
`kspace` = 1) and `space_render` keep A, X, Y and P: 262 and 185 cycles
(3 and 2 `$Cxxx` accesses). `call_game` runs the GAME routine at `kcall`
with A, X, Y in and A, X, Y, P out, from and back to RENDER space: 474
cycles for an empty routine.

**Jump table** at `$E000` (entries are only appended; parameters in the
kernel's zero page): `$E000 far_read`, `$E003 far_write`, `$E006
far_copy`, `$E009 far_elem` (A/X = descriptor), `$E00C set_palette` (A),
`$E00F kernel_reboot`, `$E012 kernel_crash` (A). GAME code calls them
through `src/game/kglue.s`, which turns cc65's `__fastcall__` arguments
into the zero-page parameters (`src/game/kernel.h`); the input block
`kin`, `ktics` and `kbanks` are read directly.

**Far access** (`far.s`; parameters `far_src`/`far_dst` 3 bytes, `far_ptr`
2, `far_len` 2, `far_idx` 2): in RENDER space a read sets `$C073` and
RAMRD and copies directly (lda/sta indirect, 16-17 cycles a byte); in
GAME space RAMRD and RAMWRT both follow `$C073`, so data between bank 1
and another bank goes through `kbuf` (256 bytes in the card), two
`$C073` writes per 256-byte piece and about 37 cycles a byte. Measured:
a 4-byte read 371 cycles (RENDER) / 495 (GAME); 256 bytes 4,409 / 9,761;
4 KB 66,059 / 154,661; `far_copy` of 700 bytes 26,883; `far_elem` at most
1,097 (size 4, log2 12: a shift per log2 bit, then shift-and-add). Game
code should read whole records at once, and hot data belongs in bank 1.

**Clock and frame loop** (`kstart.s`, `frame.s`): the mouse card's VBL
interrupt (mode `$09`) increments `vbl_count`; the handler (121 cycles,
one `$Cxxx` write) touches only the zero page, the stack and the card, so
it runs in either space. Every VBL adds 7 to an accumulator and every 12
make a tic: exactly 35 tics per 60 VBLs, in the pattern 0,1,0,1,0,1,1,
0,1,0,1,1. At most 4 tics per rendered frame (`MAX_TICS`); the excess is
dropped (`kdropped`) so the game slows down rather than jump. The loop:
`input_frame`; `clock_tics`; no tic due: wait for the next VBL
(`idle_wait`) and start over, an idle pass costing 1,030 cycles per VBL
(9 `$Cxxx` accesses, most of it input); else `game_tic()` per tic through
`call_game` (after the first, `input_consume`), `render_frame` (RENDER
space, `src/render/`), `present`. Counters: `ktics`, `kframes`,
`kdropped`, `kblits`, `kwaits`.

**Video and blit** (`video.s`): `video_init` clears aux `$2000-$9DFF`,
sets the paging byte, the magic and PLAYPAL 0, then `$C029` = `$C1`.
`set_palette` (A = 0..13, both spaces) copies `PLAYPAL` n from
`DD_DIR_BANK:DD_PLAYPAL` + 512n to `$9E00`, forcing the selector nibble
2. `blit_view` copies `VIEWBUF` to SHR rows 0-83, each byte twice, per
column with an unrolled 84-row block (`lda (p),y / sta row,x /
sta row+1,x / iny`, X = 2x in two halves): **236,029 cycles** (19% of the
frame; 3 `$Cxxx` accesses; 26,880 SHR writes), 1,574 bytes in LC bank 2.

**Line-0 policy** (`present`): outside vertical blanking (`$C019` bit 7
set, lines 0-191) the next line 0 is at least 70 lines (4.45 ms) away and
the blit starts at once; it takes 3.1 ms at 75 MHz and needs at least 53
MHz on average to fit. During blanking, line 0 may come before the blit
ends, so `present` waits for the end of blanking (`present_wait`) and
blits right after line 0; the wait costs up to 70 lines (27% of a frame).
With the test pattern the tics and the render take about 220,000 cycles
after the VBL interrupt, less than blanking, so every frame waits (51 of
51 in the test) and no frame is torn (`tools/run_doom.py` checks that a
blit never spans a line 0); with the real renderer the render will end in
the displayed part of the frame and the blit will start at once. A
finer policy (the Phasor's 1 MHz timer, to know the line) can shorten the
wait if it matters.

**Input** (`input.s`, section 10): per pass, the keyboard (`$C000`, else
`$C010` for "still held"), Open and Closed Apple, the mouse (X between
two reads of the sequence byte, the buttons; X is put back to `$8000`
when it leaves `$2000-$DFFF`): 973 cycles, 9 `$Cxxx` accesses. The block
`kin` (C `struct kinput`): `+0 mouse_dx` s16, `+2 buttons` (fire = Open
Apple or left button, use = Closed Apple or right button, bit 7 the Tab
run toggle), `+3 move` from the held key (forward: up arrow/W; back: down
arrow/S; turn: left/right arrows; strafe: A or `,`, D or `.`), `+4 key`
(held, upper case), `+5 newkey`, `+6 weapon` (1-7), `+7 flags` (Esc).
Motion, new keys, weapon, flags and fire/use presses between tics
accumulate until `input_consume`, after the first tic of each rendered
frame; held states are current.

**The GAME skeleton** (`src/game/game.c`): `game_init`, `game_tic` (counts
tics, copies `kin`, reads one far array element through `far_elem` and
`far_read`: the stand-in data's probe array across chunk boundaries, or
a `PLAYPAL` entry of the converter's data). A tic of it costs about
7,200 cycles (mostly cc65's 32-bit arithmetic).

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

`make` converts the data (`tools/wad2a2.py`, `FREEDOOM ?=
build/freedoom1.wad`, fetched by `tools/fetch_freedoom.py`) into
`build/data`, runs `tools/gen_tables.py` when it exists, assembles
(ca65), compiles (cc65 `-t none`, linked with `none.lib`: the runtime and
C library without ROM or OS calls), links `src/doom.cfg` into
`build/DOOM.SYSTEM`, `RENDER.BIN`, `LC.BIN`, `GAME.BIN`, and checks them
(`tools/check_link.py`: sizes, the jump table, the vectors, memory per
area). `make STANDIN=1` (also the default without the converter) builds
the same program against the platform's stand-in data set
(`tools/make_standin.py`: `PLAYPAL` and a probe array chunked over banks
3-6) in `build/standin`. `make disk` writes `dist/Appletini-DOOM.hdv`:
a ProDOS volume sized to its contents plus 64 free blocks (up to 65,535
blocks), `DOOM.SYSTEM` first, `PRODOS` from the master image, the images
with their load addresses as aux types, the data files as BIN aux `$0000`;
seedling, sapling and tree files, so no file needs splitting, but the
volume directory holds 51 entries (46 data files); the builder re-reads
and verifies its image. The full Freedoom data makes an 8,469-block
(4.3 MB) volume. `make test` runs `tests/test_*.py`.

`tools/a2sim.py` (from the PCS port) runs everything: TURBO frames of
1,250,000 cycles, `$Cxxx` accesses charged, 128 RamWorks banks (a
parameter), the mouse card's VBL interrupt, the idle skip of `idle_wait`
and `present_wait`, PAL256 screenshots as the Appletini renders them, the
fake ProDOS with large files. `tools/run_doom.py` boots `DOOM.SYSTEM`
through the fake ProDOS with the data mounted (or `--fast`), drives a
scripted session (keys, held keys, mouse motion and buttons, Apple keys
at 60 Hz frame numbers), saves screenshots and per-rendered-frame costs
(work, blit, line-0 waits, torn frames, `$Cxxx` accesses; `--stats`
JSON). `tools/doomdbg.py` boots and calls labelled routines from Python
with their cycle counts. `tests/test_platform.py` (boot, PAL256, pattern
screenshot, far access, space switch, blit, tic clock, input, the GAME
skeleton, loader errors, the model) and `tests/test_disk.py` cover the
platform.
