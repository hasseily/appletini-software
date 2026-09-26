# Doom for the Appletini: design

This is the contract every part of the port is written against. Where a
section says "the implementer decides", the decision is recorded here when
it is made.

## 1. Goal and scope

A playable Doom on an enhanced Apple //e with the Appletini ONE: the vTW in
**TURBO**, **8 MB RamWorks** (128 banks; episode 1 data uses banks 2–95), the
mouse card in slot 2, the Phasor in slot 4, SHR4 **PAL256** video, booted
from a ProDOS hard-disk image on the Appletini's SmartPort.

Content: **Freedoom Phase 1** (`freedoom1.wad`, BSD licence), episode 1
(all nine maps E1M1..E1M9, see section 6). The WAD is not in the
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

## 2. Hardware mapping and timing assumptions

The address mapping was checked against the sibling `appletini-one` checkout.
That establishes the layout used by the banked build, not the timing of the
user's current target firmware.

- **TURBO batches video writes.** A pixel write must not be treated as a
  synchronous 1 MHz motherboard transaction. Actual batching, synchronization,
  I/O, RamWorks/PSRAM and cache behavior need measurement on the target.
- **Python test model**: `tools/a2sim.py` counts 65C02 instructions and supports
  a nominal 1,250,000-cycle budget per 60 Hz interval, corresponding to 75 MHz,
  plus a configurable fixed I/O surcharge (73 cycles by default in its mode
  named `turbo`). This is a correctness harness with timing assumptions,
  **not an implementation of hardware TURBO timing**. Its historical rates
  must not be reported as measured FPS. A conventional 33 MHz emulator run
  is also separate from hardware TURBO validation.
- **RamWorks execution**: non-base auxiliary code, zero page and stacks use
  the selected RamWorks bank. The local hardware checkout routes this through
  PSRAM/cache logic; its delay is not represented by ordinary py65 instruction
  cycles. Do not infer target bandwidth from an older checkout's mirror rules.
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
  (a missing bank aliases a lower one). The banked game requires all 128 banks;
  the legacy platform stand-in accepts 64.
- **SmartPort**: 32 MB ProDOS volumes work (the AD8088 image is 32 MB).
- **Keyboard**: the //e reports only the last key (`$C000`) and "any key
  down" (`$C010` bit 7). Open Apple (`$C061`) and Closed Apple (`$C062`)
  are independent buttons; so are the mouse buttons.
- **Mouse card** slot 2 (`$C0A0-$C0AF`, `appletini-one/hdl/apple/mouse_card.sv`,
  see `demos/pinball_construction_set/src/input.s`), used here for
  turning, and as the **50/60 Hz clock**: mode bit 3 raises an IRQ at the
  start of every vertical blanking, also with the mouse otherwise off;
  writing 3 to the ACK register (`$C0AF`) releases the IRQ (bit 1) and
  clears its cause (bit 0). The sequence byte `$C0A6` counts the PS's
  reports (a torn two-byte X read is detected by reading it before and
  after). Positions are 16 bits, clamped to a window the program sets.
- **Phasor** slot 4: two AY chips (see the PCS/Bosconian `sound.s`). One
  burst of slot 4 accesses per frame is the planned audio backend; playback
  is not implemented in this port yet.

## 3. Screen

PAL256, 320x100. Rows 0-83: the 3D view; rows 84-99 are reserved for the
status bar (Doom's 320x32 `STBAR`, halved vertically), which is not drawn yet.

The view is rendered at **160x84 game pixels** ("low detail", every game
pixel two screen pixels wide) into a buffer in main memory, **column
major** (column `x` at `VIEWBUF + 84*x`, 84 bytes), then copied to the SHR
rows with each byte written twice. On the 640x400 output a game pixel is a
4x4 square. The palette is Doom's `PLAYPAL` 0 reduced to RGB444; the
damage/pickup tints are other `PLAYPAL` entries written to the palette
(512 bytes, once per change).

Frame publishing: the copy performs 13,440 reads and 26,880 writes, about
236K model cycles. The kernel uses a line-0 policy (section 8), whose guarantee
depends on actual copy timing. A 33 MHz model run has shown a blit spanning
line 0; this must not be presented as a proven tear-free hardware path.

## 4. Memory

### Default banked game (`BANKED=1`)

`tools/bank_game.py` partitions executable code into seven permanently loaded
auxiliary language-card banks. During game code execution, RAMRD/RAMWRT are
OFF and ALTZP is ON. Ordinary pointers continue to address main RAM while
`$C073` selects the code bank's LC, zero page and hardware stack. Each LC image
occupies `$D000-$FFFF`: 12 KiB including its interrupt vectors. The other
physical `$D000` half is not additional simultaneously visible address space.

| Bank | Code group |
| --- | --- |
| 96 | Collision and map traversal |
| 97 | Actors |
| 98 | AI and sight |
| 99 | Specials and movers |
| 0 (base auxiliary LC) | Game control, packet construction, damage and pickups |
| 101 | Setup and spawning |
| 102 | Player and weapons |

`gamebanks.s` runs from invariant main memory. Generated public entry gates
have stable addresses for direct calls, thinker functions and action tables.
Calls within a bank can bypass the gates. Selected small helpers and immutable
state tables are duplicated into code banks; their mutable caches remain shared.
The gateway supports A→B→A reentry with a saved stack pointer per context,
transfers 54 logical ZP bytes (8 game, 26 cc65, 12 far arguments and 8 kernel
scratch), and preserves A/X/Y/P and the updated C software-stack pointer.
Each bank has IRQ vectors; its handler borrows the main stack/context for the
VBL service. NMI sources must be disabled across mapping transitions.

Control code defaults to base auxiliary bank 0. The local TURBO HDL keeps its
code, zero page and hardware stack in internal BRAM; extended banks use the
PSRAM cache. Bank 0's lower RAM still owns the display, so its code image is
staged in bank 100 and installed into LC only after the final ProDOS call.
Generated `code_staging` metadata and loader source/destination tables make
this explicit. `CONTROL_BANK=100` retains the previous placement for comparison.

The hot `P_RunStatics` loop occupies 275 bytes of main game `CODE`, reached
through a three-byte jump in actor LC bank 97. It still runs with bank 97's
zero page, stack, state tables and local helpers selected. The partitioner
keeps that logical actor context while moving only the instruction bytes;
public gates and same-bank calls still target the LC wrapper. Four tiny cursor
refreshes are inlined to avoid repeated auxiliary-stack traffic. The main
body is immutable and restored with the ordinary game code at each handoff.

Both game and renderer need main lower memory. `space_game` and `space_render`
save and restore their phase contents using backing banks. Renderer ZP is saved
separately; kernel ZP and main LC stay live. All due game tics and packet
construction run in one game phase per rendered frame. The persistent renderer
map selection is updated before its phase resumes. Only mutable regions are saved each time, including renderer self-modified
code. Read-only regions are restored from their initial backing images. The
view is cleared before rendering, and the inactive C stack is not copied.
After initialization, game saves and restores end at the allocator cursor,
rounded upward to a page. A resident main-LC byte retains that endpoint while
the renderer replaces ordinary game memory. New allocations are initialized
before the next handoff; unallocated memory and dead path/view scratch need
not persist. The first game load still uses the full initial window. The
common copy loop moves eight bytes per iteration.
Exact copy ranges and their assertions live in `space.s`.

| Storage | Use |
| --- | --- |
| Main RAM, game phase | Common helpers/gates, game and level data, statics, 160 actors |
| Main `$B380-$B7FF`, game phase | Shared path/view/debug scratch, outside posted video windows |
| Main `$B800-$BFFF`, game phase | Full 2 KiB cc65 software stack, growing down from `$C000` |
| Main RAM, render phase | Renderer code/tables/state and the 160×84 view buffer |
| Main language card | Kernel, renderer inner loops and permanent interrupt service |
| Bank 0 lower RAM | SHR screen, palette, display metadata and profiling mailbox |
| Bank 0 ZP/stack/LC | Control-bank execution context, code and render packet |
| Bank 1 `$0200-$1FFF` | Far blockmap thing-chain heads |
| Bank 1 from `$6000` | 3,060-byte immutable mobj metadata table |
| Banks 2–95 | Converted episode 1 data |
| Bank `DD_LAST_BANK+1` | Renderer far cache/workspace (lower RAM) |
| Bank 122 | Renderer phase backing storage |
| Bank 124 from `$0200` | Published 2,600-byte render packet, including up to 128 things |
| Bank 125 | Game phase backing storage |
| Bank 126 | Specials journal and initial sector snapshots |
| Bank 127 from `$0200` | Math tables and far game workspace |

The packet is built in spare LC RAM of the control bank, then copied through
main scratch into bank 124 with the header published last. The renderer reads
its header and individual records there. Packet construction reuses path
intercept scratch after game tics; it does not overlap an active path traversal.
That 1,152-byte scratch lives immediately below the C stack at `$B380-$B7FF`,
outside main's posted video windows. The arena ends at `$B380`; removing the
scratch from ordinary BSS lowers its start by the same amount, preserving
capacity. Scratch users initialize the bytes they read, so this separate
segment does not require the ordinary BSS clearing pass. Steady phase copies
stop at the live arena endpoint and do not preserve this dead scratch; page
rounding can include a partial scratch page when the arena is completely full.
Line/node/subsector/blockmap-cell cache capacities are 16/32/16/8 in this build.
The existing 160-actor limit, 128 packet things and 2 KiB C stack are retained.

`tools/build_banked.py` generates `doom-banked.cfg` from `src/doom.cfg` plus the
bank fragments and links the complete program. Outputs are `DOOM.SYSTEM`,
`RENDER.BIN`, `LC.BIN`, `GAME.BIN`, seven `GBANK*.BIN` images, `GAME.TABLES`,
`GAME.INFO`, and the loader package `DOOM.BANKS`. The disk needs the latter
package, not separate entries for every code image. `banked.json`, `doom.map`
and `link-report.json` record the actual layout. `check_link.py` verifies bank
capacity, stack/arena limits, vectors, images and preload consistency.

### Legacy stand-in and flat reference

`make STANDIN=1` keeps the original two-space platform test: renderer in main
RAM, the small GAME skeleton in auxiliary bank 1 with RAMRD/RAMWRT on, common
main ZP/stack/LC, and a 2 KiB C stack. `BANKED=0` selects this old layout for
reference; the full game exceeds its 46,592-byte GAME region. The separate flat
65C02 harness uses synthetic instruction windows and is a gameplay reference,
not evidence that the original hardware layout fits.

### Far data and boot

A far address is `{lo, hi, bank}` (C `far_t` stores the bank in bits 16–23).
An array descriptor is `{first bank u8, base u16, element size u16, log2 u8}`.
Element `i` is at bank `first + (i >> log2)`, address
`base + (i & (2^log2-1)) * size`; no transfer crosses `$BFFF`.

For the banked game, the main-context bridge lets `far_read`/`far_write` copy
between shared main RAM and the chosen bank directly. `far_copy` between two
auxiliary banks still uses a bounce buffer in main LC. Renderer inner loops
select a texture bank for RAMRD while continuing to write main RAM.

ProDOS is used only at boot. Code LC images are staged in their banks' lower
RAM, then installed after the last MLI call. The loader subsequently overwrites
its own main-memory space with the renderer and enters the kernel. Quit reboots.

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

The whole frame, byte for byte the reference's `Renderer.render`: walls,
planes and sky here, the masked phase (sprites, two-sided middles, the
weapon) in 7.2. Files:

| File | Holds |
|---|---|
| `rdefs.inc` | shared equates (`ROWBIAS`, `RENDER_BANK`, the `RENDER_BANK` layout, queue size), the renderer's zero page and routine names |
| `rmain.s` | `render_frame`, the packet, `map_load`, `frame_setup`, the far-array element address, record fetches and the per-frame caches, `point_on_side`, the BSP walk, `check_bbox`, `subsector`, `add_line`, the solid-seg list |
| `rsegs.s` | `store_wall_range`: scales, pegging, silhouettes, marks, the seg loop, the texture column, the column pieces, the visplane marks and the drawseg |
| `rplane.s` | visplanes (`find_plane` hashed, `check_plane`), texture/flat animation and records (cached), the sky column, `draw_planes`, `make_spans`, `map_plane` |
| `rmath.s`, `rfmul.s`, `rmul.inc` | multiplies (quarter squares), divisions, sines, `point_to_angle`, the tangent; the byte tables of the seg loop |
| `rlc.s` | everything that runs with RAMRD on (language card bank 1): bank reads, the column-piece queue and its drawer, the span drawer, the visplane check |
| `rthings.s` | the vissprites: `r_things` (R_AddSprites, R_ProjectSprite), the weapon's light (7.2) |
| `rmasked.s`, `rmask.inc` | the masked phase `r_masked`: sprites, two-sided middles, the weapon (7.2) |

**Interfaces.** `render_frame` (called by the frame loop, RENDER space)
switches the language card's `$D000` to bank 1 for itself and back to bank
2 (the blit) before it returns; interrupts may stay on (the VBL handler
touches neither `$C073` nor RAMRD/RAMWRT). Three bytes in the language
card, seen by both spaces:

- `render_map` (C `extern unsigned char render_map;`): the MAPDIR slot to
  draw, 9 x (episode - 1) + map - 1; `$FF` (the initial value) draws
  nothing and leaves the view buffer alone. The banked phase handoff publishes
  `gamemap-1` before restoring the renderer; a change loads the MAP record (array descriptors, sky)
  and the animation list on the next frame.
- `render_shaded` (C `render_shaded`): 0 textured floors and ceilings, else
  flat-shaded; its initial value is the build option `RENDER_SHADED`
  (default 0; use `make RENDER_SHADED=1`, including for the banked hardware
  build, or `tools/build_banked.py --render-shaded`). Walls, sky and sprites
  remain textured.
- The packet: `render_frame` reads the 40-byte packet header (bank 124 in the
  banked build; `_rview` in bank 1 in the legacy renderer harness);
  the things are **not copied** (2,560 bytes of main memory, and 42K cycles
  a frame, for data only the masked phase reads): `rv_thing` (A = index)
  reads one into `rv_tbuf` with one bank read. The game does not run while
  the frame is drawn, so this is the packet as the game left it.

What the walk leaves for the masked phase (7.2): the sectors in the order
of their first visit in `vs_list_lo/hi` (`vs_count`; 256 kept, and sectors
from `MAXSECTORS` = 1,024 on are not listed: E1's largest map has 699),
the sector of the first subsector it entered (`eye_sec`, valid when
`eye_state` = 1: the eye's own, since every node sends the walk to the
eye's side first, unless the node stack overflowed before), and the
drawsegs (`ds_n`) with their openings in `RENDER_BANK`:

| Drawseg (30 bytes at `DS_BASE + 30n`, `ds_addr`) | |
|---|---|
| +0 x1, +1 x2 | columns |
| +2 scale1, +5 scale2, +8 scalestep | 3 bytes each (16.16; the step signed) |
| +11 silhouette | `SIL_BOTTOM` 1, `SIL_TOP` 2 |
| +12 bsilheight, +14 tsilheight | 2 bytes signed map units (the reference's are always a height << 4, so the comparisons are exact in map units); `$7FFF` = MAXINT, `$8000` = MININT |
| +16 sprtopclip, +18 sprbottomclip | the `RENDER_BANK` address of column x1's byte in the openings, or 0 none, 1 "screenheight" (84), 2 "negone" (-1) |
| +20 maskedtexturecol | the address of column x1's 2 bytes (texture column & 255, then the masked phase's "drawn" mark, 0 at first), or 0 |
| +22 seg | the seg's index |
| +24 texture, +26 texturemid, +29 light | a masked middle only: this frame's texture, texturemid (3 bytes, sub-units) and the light level index before clamping, which the wall range knows already (so the masked phase reads no seg, sector, sidedef or vertex for it) |

Clip values in the openings are rows + `ROWBIAS` (64), saturated to
0..255 (see below; -2, Doom's sprite-clip sentinel, is exact). The
openings are allocated exactly as the reference counts them (`MAXOPENINGS`
bytes: 2 per masked column first, then 1 per clip column), so the same
drawsegs lose their clips on overflow.

**Historical standalone renderer memory** (before banked integration): these
addresses and spare-byte totals describe that renderer link. Section 4 and the
current generated link report describe the integrated build.

| Area | Use |
|---|---|
| zero page `$02-$D8` | the kernel's 41 bytes and the renderer's 174 (multiply/divide operands, the seg loop's accumulators, pointers, the eye); 7 bytes free. The masked phase reuses the seg loop's 41 |
| main `$0200-$03FF` (`RLOWDATA`) | the visited-sector list (512) |
| main `$0400-$0BCF` (`RTEXTDATA`, read-only) | the text-page tables of section 7, then 113 bytes of read-only code (`mul_row`); 48 free |
| main `$0C00-$1D5B` (`RLOBSS`, rw in the file) | packet header, BSP node stack (64 x 11; at load time the MAP record and the animation list), the vertex cache (128 slots: angle and coordinates), a visplane's columns copied back, span starts, the range's plane marks and masked columns, the texture-record cache (32), the per-column sines (161), the per-column sin/cos cache of the spans (160). Most of it is dead in the masked phase, which keeps its data there (7.2) |
| main `$1D5C-$1FBA` (`RLOCODE`) | masked-phase code (607 bytes) |
| main `$1FBC-$52FF` (`RRODATA`) | the generated tables (13,124 bytes; the start puts the quarter-square tables on page boundaries, asserted at link time) |
| main `$5300-$5F2A` (`RCODE`, read-only window) | code that is never modified: math, planes, `r_iscale`, `sprite_lump` (3,115 bytes; 213 free) |
| main `$6000-$82DA` (`RHICODE`) | code with self-modified operands and the rest: BSP, segs, seg loop, spans, part of the masked phase (8,923) |
| main `$82DB-$8B64` (`RBSS`) | frame state, caches (sectors 64 slots), clip arrays (the masked phase's variables afterwards), solid segs (2,186); 27 bytes free |
| LC bank 1 `$D000-$DF87` (`RLC1`) | the RAMRD code, the span tables, the piece queue (32 x 12 bytes), `subsector`/`add_line`/clipping, the projection (`rthings.s`) (3,976; 120 free) |
| LC bank 2 `$D626-$DFAD` (`RLC2`, after the kernel's blit) | the masked phase: its RAMRD sessions and most of its code (2,440; 82 free) |
| LC `$E6F4-$FFE3` (`RLCHI`, `RLCBSS`) | `render_frame` and the frame setup, the unrolled multiplies and divisions, the shift tables (shr4/shl4/sar4/bitlen), `render_map`, `render_shaded`, part of the masked phase; visplane headers (7 x 128) and the span row cache (84 rows), the masked phase's tables afterwards; 22 bytes free |
| RamWorks `RENDER_BANK` = `DD_LAST_BANK` + 1 | visplane columns `$0200-$A3FF` (128 x 324: top and bottom rows of columns -1..160), drawsegs `$A400-$B6BF` (160 x 30), openings `$B6C0-$BEBF` |

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
  32-entry queue in the language card (bank, address, count, texture
  column, 8.8 fraction, step, colormap page, hmask); `q_flush` draws a whole
  wall range (or a plane's sky, or a full queue) in one RAMRD session,
  `$C073` rewritten only between banks. The drawer preserves Doom's
  R_DrawColumn stepping with self-modified operands. It first gathers a
  piece's raw texels into the existing 256-byte main-LC `kbuf`, then reads
  them in reverse order, applies the colormap and writes their destination
  offsets. This separates texture and colormap PSRAM reads to reduce cache
  replacement. Main BRAM writes do not invalidate that cache in the local
  HDL. The buffer is idle during rendering and untouched by the IRQ handler;
  every byte read is initialized by the first pass. No RAM is added. The
  extra CPU work trades against target-dependent memory stalls; hardware
  measurements, rather than instruction counts, determine whether it wins.
  One-colour fills retain their direct loop, and queue order is unchanged.
- *Planes*: visplanes in `RENDER_BANK` (the recommendation), found through
  a 64-bucket hash that keeps creation order (the reference returns the
  first match). A plane's columns are initialised as its range grows (the
  reference only ever reads within minx-1..maxx+1), and a plane's columns
  are copied back to main memory once, before its spans; a column equal to
  the previous one starts and ends no span and is skipped. `map_plane`
  caches the row's distance and steps (per row and plane height, as the
  reference) and each column's sine and cosine (per frame). The span loop
  runs in the language card with RAMRD on. Its first pass advances the two
  16-bit 5.11 coordinates and gathers raw flat texels into `kbuf`; the second
  applies the colormap and writes with the original 84-byte stride. This
  separates the flat and colormap PSRAM read streams, adding CPU work in
  exchange for potential cache reuse. It preserves the final coordinates,
  destination cursor and zero count, including the legacy 256-pixel case.
  The immutable 28-byte `span_setrow` helper lives in `RTEXTDATA` and is
  called with RAMRD off; its stores patch the LC loop's operands only.
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

**Measured** (`tests/test_render_core.py -v`, historical synthetic py65 cycle
accounting, not hardware TURBO timing): 109 views (the 36 deliverables, the 6 golden eyes, 9
flat-shaded, 40 random views of `--sweep`'s generator, 15 animation tics,
3 fixed-colormap/extralight), every one byte-identical to the reference.
No things and no weapon here, but the two-sided middles are drawn (so these
are a little above the first version's, which left them out: all 3.36M,
deliverables 3.29M, random 2.86M); 7.2 has the frames with things:

| Set | mean | p90 | max |
|---|---|---|---|
| all 109 | 3.42M | 6.04M | 7.15M |
| deliverables (36) | 3.35M | 6.12M | 7.15M |
| random (40) | 2.93M | 5.29M | 5.55M |
| flat-shaded (9, the starts) | 3.54M | 5.39M | 5.39M |

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

**Tests** (`tests/test_render_core.py`): the 109 views above (against
`Renderer.render` with no things: walls, planes, sky, two-sided middles); the four
limits forced low in both the program (its immediate operands patched in
memory) and the reference (MAXVISPLANES 20, MAXDRAWSEGS 40, MAXOPENINGS
200, MAXBSPDEPTH 8: the degraded views are identical); `sin_bam`,
`point_to_angle`, `div_scale` and `div_step` against the reference's
arithmetic on sampled and edge inputs. `--view MAP X Y Z ANGLE` renders
one view (diff, cycles, PNGs), `--profile` gives the phase and routine
breakdown above. The tests build `make BUILD=build/rtrack/` (with
`RENDER_GAMESRC` naming a snapshot of the GAME sources when they are in
flux) and use `build/data`.

### 7.2 The masked phase (src/render/rthings.s, rmasked.s)

Sprites, two-sided middle textures and the weapon, byte for byte the
reference's `draw_masked` and `draw_psprite` (Doom's R_AddSprites,
R_ProjectSprite, R_DrawMasked, R_DrawSprite, R_DrawVisSprite,
R_DrawMaskedColumn, R_RenderMaskedSegRange, R_DrawPSprite). After the
planes, `render_frame` calls `r_things` (LC bank 1 in), switches the
`$D000` bank to 2 and ends in `r_masked` (the bank the blit wants anyway).

**The vissprites** (`rthings.s`). The reference projects a sector's things
when the walk first enters the sector, in packet order. Nothing the walls
draw depends on them, so the 6502 projects after the walk: `th_gather`
reads the sector of each packet thing (one RAMRD session on the packet bank, a byte
pair every 20), the things are hashed by sector (64 buckets, each chain in
packet order), and the walk's list of sectors (7.1) is replayed: the same
vissprites in the same order. A thing is read (`rv_thing`, 20 bytes) only
if its sector was reached. R_ProjectSprite as the reference: tr = thing -
eye (24 bits), the four `>> 14` products (24x16), `tz < MINZ` out, xscale
= (80 << 20) / tz by a dedicated 21-step division (the dividend's top six
bits, 40, are below any tz: 1,000 cycles rather than udiv's 1,800), `|tx| >
4 tz` out, the rotation by `point_to_angle`, the frame's lump and flip
(`sprite_lump`: SPRDEF, SPRFRAME, SPRLUMP records), x1 and x2 from 40-bit
products, the colormap (shadow, fixed, full bright, else the sector's
`scalelight` row at `min(xscale >> 11, 47)`), iscale by the reciprocal
table (`r_iscale`), texturemid. A vissprite keeps (structure of arrays,
17 bytes each): its thing, scale, clipped columns, the columns clipped off
the left (startfrac is made from them when drawn), iscale, lump and flip,
colormap, texturemid. `cpx #MAXVISSPRITES` in `project` is the limit.

The weapon's light: the eye's sector is the walk's first subsector's
(7.1); if the node stack overflowed first (`eye_state` 2), `eye_light`
descends the nodes as R_PointInSubsector.

**Drawing** (`rmasked.s`). Everything that runs with RAMRD on is in LC bank
2 (there is no room in bank 1); it never calls bank-1 code: bank reads go
through `rb2_read`, bank 2's copy of `rb_read`, records through
`elem_addr`.

1. *Sort*: an insertion sort by scale, stable (the reference's key: scale,
   then the order made).
2. *R_DrawSprite*: the clip rows (`mc_top`, `mc_bot`, one byte a column,
   biased rows) start at -2 (62); `ds_scan`, one RAMRD session on
   RENDER_BANK, walks the drawsegs last first and lists those overlapping
   the sprite with a silhouette or a masked middle, flagging those entirely
   behind it (both scales below the sprite's): for these only the masked
   middle matters and no record is read. For the others the record is read
   (30 bytes): behind by R_PointOnSegSide (the seg's vertexes, the thing's
   x, y read again from the packet, `point_on_side` exact), the masked
   middle is drawn over the overlap; in front, the silhouette less what the
   thing's z is clear of (`gz >> 4 >= bsil`, `(gzt + 15) >> 4 <= tsil`, in
   map units: exact) fills the clip rows still at -2 (`clip_fill`: a
   session reading the openings, or a constant row). Rows left at -2 become
   84 and -1.
3. *R_DrawVisSprite* (`draw_vis`, also the weapon's): two tables per
   sprite make the column loop product-free: `rowt[k]` = ceil((sprtopscreen
   + k * spryscale) / 65536) biased and saturated to 1..255 for the post
   offsets k = 0..height (additions from a 48-bit sprtopscreen, clamped to
   32 bits where the rows saturate alike), and `yf[y]` = the 8.8 fraction of
   screen row y (texturemid + (y - 42) * iscale), for the rows the patch can
   cover. A post then is rows `max(rowt[top], cliptop + 1) ..
   min(rowt[top + length], clipbot) - 1`, its fraction `yf[yl] - (top <<
   8)`. `dv_cols` draws all the sprite's columns in one RAMRD session on
   the patch's bank (posts, texels and colormaps all there; clip rows and
   tables in the language card's $E000 area): the column fraction steps by
   xiscale, the posts are walked, each drawn by an 8.8 loop through the
   colormap: 40 cycles a pixel, about 90 a post and 90 a column. A post
   whose pixels start in page `$BF` goes through a slower loop: Doom's
   unmasked index can reach 255 bytes on, past `$BFFF`, which the 6502
   would read from the I/O space, and the reference's bank image reads 0
   there.
4. *The shadow* (fuzz): the session lists the posts' rows (in main memory:
   RAMRD does not move writes, 128 entries, flushed between columns when
   half full); `fz_flush` then draws them with RAMRD off, since the fuzz
   reads the view buffer: colormap 3 (copied once a frame) of the pixel one
   row off, rows 1..82, `fuzzpos` from 0 each frame.
5. *R_RenderMaskedSegRange* (`msr_setup`, `msr_range`): the wall phase
   stored the texture, texturemid and light level in the drawseg (7.1), so
   the setup reads only the drawseg and the texture's record (kept for the
   last drawseg set up). Per call a session on RENDER_BANK with RAMRD and
   RAMWRT on (`ms_gather`) reads each column's texture column, drawn mark
   and clip rows into the language card and marks it drawn; then per
   column, RAMRD off: sprtopscreen = (42 << 16) - (texturemid * scale >>
   4) and bottomscreen = that + scale * height, with texturemid * scale
   and scale * height exact in 48 bits and stepped by additions across the
   range (no product per column but the fraction's 8x24), the rows, iscale,
   colormap; then one session on the texture's bank (`ms_draw`) draws
   them, texel 247 a hole. The drawsegs' masked middles left are drawn last
   first after the sprites.
6. *R_DrawPSprite*: x1 = 80 + ((sx - (160 << 16)) >> 17) - left, one texel
   per pixel (spryscale = iscale = 1.0), texturemid = ((100 << 16) + $8000
   - sy) / 2 + (top << 16), clip rows -1 and 84; colormap: fixed, else 0 if
   full bright, else the eye's (`ps_cm`). Both layers, in order.

**Memory**: none of its own besides code. It takes over what is dead by
then (`rmask.inc` has the layout; `rmasked.s` asserts the regions at link
time): the vissprites in the BSP node stack and the vertex cache (1,632 of
1,728 bytes); the thing hash, the sort order, a drawseg record in the wall
range's marks (798 of 800); the fuzz list in the plane copy-back; the
candidate list, its flags and the fuzz colormap in the span column cache;
the variables in the clip arrays (`cclip`, `fclip`); the clip rows, the
sprite tables and a masked middle's columns in the visplane headers and the
span row cache ($E000 area, readable in a session); the seg loop's zero
page. Code: LC bank 2 2,440 bytes, `RLOCODE` 607, `RHICODE` 625, `RLCHI`
275, `RCODE` 101 + 417, `RTEXTDATA` 113, LC bank 1 1,332. To find that
room: the piece queue went from 64 to 32 entries, the MAP record buffer
lives in the node stack, the drawseg address table became `ds_addr` (30n
computed), the visited-sector bitmap covers 1,024 sectors, `rb_read` copies
four bytes a loop.

**Decisions and limits** (beyond the reference's): things farther than
20,480 units (a scale under 1/256, whose reciprocal would not fit 24 bits)
are not drawn, E1's largest map is 7,642 units corner to corner; a thing
whose sector is not in the walk's list (more than 256 sectors reached, the
sweep's most is 181 subsectors, or a sector index from 1,024) is not drawn;
the patch height is at most 255 and posts lie within it (the converter's).

**Measured** (`tests/test_render_masked.py -v`): with the map's things
(`spawn_things`, the 128 nearest in the packet) and the pistol, every view
byte-identical to the reference:

| Set | mean | p90 | max |
|---|---|---|---|
| deliverables (36) | 3.73M | 6.88M | 7.71M |
| random (40, `--sweep`'s generator) | 3.32M | 6.27M | 6.81M |

The same views without things cost 3.35M and 2.93M (7.1): the masked
phase adds about 0.38M a frame (some 19 things projected, 10 vissprites,
1,000 sprite pixels, the weapon's 447). Where it goes (12 views,
`--profile`): the sprites' clipping 155K (the drawseg scan 55K, record
reads 37K), the projection 134K (the division 27K, record reads 28K,
products), the sprite columns 76K, the sprite tables 31K, setup and fuzz
20K, the hash and replay 18K, two-sided middles 23K, sort 5K, the weapon's
setup 3K.

**The target (a whole frame at 1.8M on average) is not met**: 3.5M with
things. The masked phase is 11% of it; the rest is the core of 7.1
(walls 1.25M, planes and spans 0.9M, wall pixels 0.43M, the walk 0.66M).
For the masked phase itself, what would still help: the drawseg scan from
a per-frame compact copy in main memory (~30K), a cache of SPRFRAME records
by sprite and frame (~10K). Memory, not cycles, limits the next steps: the
renderer now has 241 bytes of main memory, 120 in LC bank 1, 82 in LC bank
2 and 22 in the $E000 area left.

**Tests** (`tests/test_render_masked.py`, through `tools/doomdbg.py`): the
36 deliverables and the 40 random views with things and the pistol;
things under the fixed colormap, extralight and flat-shaded mode;
animation tics; synthetic scenes (a thing seen from the eight rotations and
flipped, very close including inside MINZ, very far, at the screen edges,
floating above and below the eye, full bright, the spectre alone and in
front of a lit thing, things behind and straddling two-sided middles in
five maps, the weapon at nine sx/sy and with its flash on the second layer
under extralight and the fixed colormap, the shotgun, a crowd of 120
things); limits forced low in both the program and the reference
(MAXVISSPRITES 1 and 20, MAXBSPDEPTH 2 and 8 with the weapon's light from
the node descent, MAXDRAWSEGS 40, MAXOPENINGS at a quarter and three
quarters of the openings used). `--view MAP X Y Z ANGLE` renders one view,
`--profile` gives the breakdown above. `tools/show_view.py` renders a view
in the simulator and writes a side-by-side PNG (6502, reference, the
differing pixels).

## 8. The kernel (src/kernel/)

The kernel provides boot/loading, bank checks, PAL256 video, far access, phase
switching, input, VBL timing, presentation and reboot. Audio remains a planned
backend. The banked architecture is specified in section 4; historical
stand-in cycle counts do not describe its gateways or phase copies.

**Boot** (`loader.s`, `DOOM.SYSTEM` at `$2000`): disconnect `/RAM`, probe all
RamWorks banks (128 required by the banked build), determine the ProDOS prefix,
and load BIN files with aux type `$0000`. `DOOM.BANKS` uses the same `A2DM`
segment format as the converted data and includes LC images, tables and object
metadata. Each segment is checked against its bank/address limits. Reads use a
main staging buffer and RAMWRT copies; ALTZP remains off during MLI calls.
`GAME.BIN` goes to bank 125; `RENDER.BIN` is staged in bank 0; `LC.BIN` is staged
in main RAM. After the final MLI call, interrupts are disabled and the staged
auxiliary LC code is installed. A page-1 installer copies the renderer over the
loader, installs main LC and enters `kernel_start`. Loader errors report a code
and return to ProDOS before the destructive install phase.

**Start** (`kstart.s`): initialize main stack/ZP, kernel and renderer BSS, video
and input; enter the game phase, initialize banking contexts, and run the C
startup (`sp=$C000`, `zerobss`, `game_init`). Return to the renderer, enable IRQs
and enter `frame_loop`. The mouse card is required for the VBL clock. A BRK or
explicit crash prints `DOOM CRASH $cc` and stops; quit/reset restarts the machine.

**Kernel calls**: main LC retains the physical jump table at `$E000` for far
read/write/copy/element, palette, reboot and crash. Banked game-facing entries
are gates in shared main RAM that select the main context before calling it.
The input block and bank count are copied into game-visible main storage before
each game entry. Far addresses/lengths and scratch results cross the bridge as
part of its ZP context. The main kernel can select data banks without replacing
its executing code; the return gateway restores the suspended game bank.

**Clock and frame loop**: the mouse card VBL IRQ increments 16-bit `vbl_count`.
An atomic snapshot gives the elapsed interval, including low-byte and full
counter wrap. Every VBL adds 7 accumulator units; a tic takes 10 units on PAL
or 12 on NTSC, scheduling 35 TPS on either standard. `VIDEO_HZ=50|60` selects the
boot default; V changes the game clock and readout together. Rate changes
discard the old fractional remainder. Up to **four tics** run per rendered
frame; excess due tics increment 16-bit `kdropped` and are discarded, with no
whole-tic backlog carried to later frames. This deliberately slows simulation
below 8.75 rendered FPS; 35 TPS is reached when the frame rate allows it.
The v9 trial allowed 16 tics, but hardware testing found worse controls and
lower FPS, so v10 restores four while keeping the corrected PAL clock.
Whole 10/12-VBL groups are processed
together before the remaining VBLs, so long pauses need less accounting work.
The clock routines execute from read-only RENDER memory below $6000.
After input, `space_game` runs once, all due tics use `call_game_active`, and
`game_frame` constructs/publishes the packet. `space_render` runs once, followed
by `render_frame` and `present`. Input events are consumed after the first tic.
Counters include `ktics`, `kframes`, `kdropped`, `kblits` and `kwaits`.

**Video**: `video_init` configures SHR4 PAL256 and the initial palette.
`blit_view` copies the 13,440-byte column-major view to 26,880 SHR pixels,
doubling each pixel horizontally. Its existing unrolled loop costs about
236,000 model cycles; this is not a hardware TURBO duration. `present` starts
outside VBL or waits for the next line 0 when already in VBL. The model checks
line-0 crossings, while actual publication timing still requires target tests.
TURBO video writes are batched.

**Input**: `kin` has mouse X delta, fire/use/run buttons, movement, held/new key,
weapon selection and flags. Keyboard arrows/W/S move or turn; A/D or comma/
period strafe; mouse X turns, mouse/Open/Closed Apple buttons fire/use. Tab
changes the run toggle. Esc sets the menu flag, currently without a menu
consumer. Motion, transient keys and button presses accumulate until the first
tic consumes them; held states remain current.

The `STANDIN=1` platform build uses the original bank-1 GAME skeleton and test
pattern, retaining separate boot/input/far-access regression coverage.

## 9. The game (src/game/)

Gameplay behavior below applies to the integrated game. Some per-module segment
sizes and overlay descriptions record the older flat/legacy build; the Memory
subsection and section 4 describe the current permanent LC-bank layout.

Doom's play simulation for episode 1, in three parts: the **core**
(this section: things, movement and collision, the blockmap, hitscan and
use, the player and his weapons, the thinkers, level loading and flow,
the render packet), the **monsters** (`p_enemy`, `p_inter`, `p_sight`)
and the **specials** (`p_spec` and doors, floors, plats, ceilings,
lights, switches, teleporters; "Interfaces" below). The monsters part is
described in "The monsters" below, the specials part and the level flow
in "The specials". The kernel calls three
entry points in GAME space (`g_game.c`): `game_init` once at boot (the
far tables, E1M1 at "hurt me plenty"), `game_tic` per 35 Hz tic (a
pending level change, the tic command from `kin`, `P_Ticker`) and
`game_frame` once per rendered frame after the tics (`frame.s`, before
`render_frame`: the render packet `rview`, `rview.h`).

**Two builds of one source.** Every module exists as vanilla-shaped C
(`p_*.c`, `g_game.c`, `m_misc.c`), which is the reference: gcc compiles
all of it for the host (`tests/host/`: far memory served from the
converter's banks, the kernel stubbed), where the logic is tested in
microseconds. On the 6502 the hot modules are 65C02 assembly instead
(`a_*.s`, cc65 compiles their C twins to nothing:
`#if defined(GAME_REAL) && !defined(__CC65__)`), because cc65's code for
the core was 52-58 KB, more than the GAME space, and slow (16-bit int,
32-bit fixed_t through runtime calls). The assembly is checked against
the C: module by module (`tests/test_game_asm.py`) and as a whole game,
tic by tic (`tests/test_game_sim.py`: identical random index, player,
every thing, sounds and render packet over a 290-tic scripted session).

| Module | C reference | 6502 |
|---|---|---|
| fixed point, trig | `m_misc.c` (host: `tests/host`) | `fixed.s`: FixedMul (quarter squares, unrolled), FixedDiv (32 steps), fine sine/cosine and tantoangle from the far bank |
| level data | `p_levdata.c` | `a_levdata.s`: level arrays, line/node/subsector/blockmap-cell caches, R_PointInSector, REJECT |
| map utilities | `p_maputl.c` | `a_maputl.s` |
| movement, attacks | `p_map.c` | `a_map.s` |
| things, thinkers | `p_mobj.c`, `p_tick.c` | `a_mobj.s` |
| player, weapons | `p_user.c`, `p_pspr.c` | `a_user.s` (the weapon tables stay in `p_pspr.c`) |
| tic command, packet | `g_game.c` | `a_view.s` (level flow and entry points stay C) |
| level set-up | `p_setup.c`, `p_spawn.c` | C, an overlay (below) |
| sight | `p_sight.c` | `a_sight.s` |
| monsters' minds, attacks | `p_enemy.c` | `a_enemy.s` |
| damage, death, pickups | `p_inter.c` | `a_inter.s` |
| line and sector specials, lights, switches, level set-up and undo | `p_spec.c`, `p_lights.c`, `p_switch.c` | `a_spec.s` (the set-up and undo in the overlay) |
| doors, floors, stairs, plats, ceilings, teleporters | `p_doors.c`, `p_floor.c`, `p_plats.c`, `p_ceilng.c`, `p_telept.c` | `a_movers.s` |

**Things.** Actors (`mobj_t`, 64 bytes: everything that moves, fights or
thinks) and statics (`sobj_t`, 16 bytes: pickups, decorations, corpses,
barrels and dormant monsters) share the blockmap chains (`IS_STATIC` by
pool address). Every map thing is spawned as a static (E1M7 on
ultra-violence places 730 things: as actors 46 KB); a static becomes an
actor when something acts on it (`P_WakeStatic`: damage, telefrag,
crushing, a dormant monster's look that may succeed) and an actor that
has settled into a static's life goes back (`P_MobjThinker` →
`try_sleep`: not shootable, no missile, no momentum, on its floor or
hanging, in a quiet state: `gen_info.py` marks a state whose chain has no
action with bit 7 of `st_action`). A dormant monster's `A_Look` runs only
when it can succeed (its sector heard a noise, or REJECT lets it see the
living player's sector). Read-only looks at a static (aim, pickup,
collision) use `P_StaticView`, a scratch actor. When the actor pool is
full, a spawn takes the slot of a puff, blood or fog.

**Level data.** The map arrays stay in the converter's far banks
(section 6). Near: the sector heights and specials (written through to
far memory for the renderer: `P_SetSector*`), the blockmap chains, the
line-mark bitset (vanilla's validcount: one bit per line and the list of
bytes set), the REJECT row cache. Caches (`a_levdata.s`, direct mapped):
64 lines (27-byte `line_t` copies), 128 BSP nodes, 64 subsectors, 16
blockmap cells. A `line_t *` is valid until the next `P_Line`; code that
calls out keeps line indices (spechit, intercepts, the specials' API).

**Level memory** (the arena, `p_setup.c`) is reset at each level start:
the space from the end of BSS to the C stack, the bytes of the far
tables (`GFAR`, copied to the game's far bank, the machine's last, at
boot) and those of the set-up overlay (`GOVL`). The set-up code
(`P_SetupLevel`, the arena, the map thing spawner: 4 KB) is linked right
after `GFAR`, copied to the far bank with it at boot and read back before
each level's set-up (`P_LoadOverlay`); the actor pool is placed at the top
of the `GFAR` hole, right below the overlay, and grows over the overlay
once the set-up is done (`P_ExtendPool`). `ARENA_RESERVE` (2 KB) is kept
for the other parts' set-up (`P_SpawnSpecials`, `P_MonstersSetupLevel`);
the pool holds at most `MAXACTORS` (160).

**Render packet** (`rview.h`, built by `game_frame`): the eye (the
player's position, `viewz` with the bob, sub-units), angle, extralight,
colormap, tic, the weapon layers, and up to 128 things with a sprite (not
the player), nearest first: all actors and statics are filed in 32
distance bands of 128 units (vanilla's `P_AproxDistance`); past 255
candidates a second pass keeps the nearest bands; past 128, things more
than 64 units behind the eye are left out.

**Input** (`G_BuildTiccmd`): vanilla's for one player: forward/side
moves 0x19/0x32 and 0x18/0x28 (walk/run, Tab), turns 640/1280 with 320
for the first 6 tics of a turn, the mouse turns `-dx * 8` (sensitivity
5), fire, use, weapon keys 1-7 as `BT_CHANGE`.

**Level flow** (`g_game.c`, "The specials" below): an exit ends the
level at the next tic with its tally (`wminfo`) and the intermission
(`gamestate` `GS_INTERMISSION`), a new press of fire or use loads the next
map: E1M1..E1M8 in order, E1M3's secret exit to E1M9, E1M9 back to E1M4
(maps the converter did not keep are skipped); E1M8's exit ends the
episode (`GS_FINALE`), and a press there starts a new game at E1M1. The
dead player's use key restarts the level with a new player (vanilla's
single player `G_DoReborn`). Every load first puts the far map records
back as the converter made them (`P_ResetLevelData`).

### The assembly's conventions

- C entry points use cc65's `__fastcall__` (last argument in A/X/sreg,
  the others on the C stack, popped by the callee) and keep the names of
  `p_local.h`; internal entries take their arguments in the game's zero
  page and in variables, documented at each.
- The game's zero page (segment `GZP`, 8 bytes): `gmo` (the current
  actor), `gth` (a thing in a callback), `gli` (the current line, as
  `line_get` leaves it), `gpt` (another pointer). Caller-saved, like
  cc65's `ptr1-4`/`tmp1-4`: whatever calls out reloads them.
- 32-bit values live in `W` (`gwork.inc`/`gwork.s`): 64 four-byte slots
  named by owner (the trace, the line opening, the tm* state of
  P_CheckPosition, the attack slopes, ...: the C globals of those names
  are these slots) and operated on by subroutines taking slot offsets in
  X and Y (`w_mov`, `w_add`, `w_cmp`, `w_mul`, ...: 7 bytes a call). T0-T4
  are scratch for leaf routines.
- Reentrancy is vanilla's: the tm*, trace and attack state is global,
  and a callback that calls out (a missile's `P_DamageMobj` waking a
  monster whose `A_Chase` runs `P_TryMove`) may run the same code again,
  after which the outer call sees what the inner one left, as in
  vanilla. What must survive such calls is on the 6502 stack: the moving
  thing, the blockmap cell loop, the thing chain being walked,
  `P_SetMobjState`'s thing and next state.
- Differences from vanilla, all deliberate: statics (above); no sector
  thing lists (the renderer gets the things in the packet); a singly
  linked blockmap chain; at most 128 intercepts per trace (vanilla
  overran its array); a static's angle is kept to 8 bits;
  `P_ChangeSector` skips the things whose box lies outside the box of
  the moving sector's lines (`sec_bbox`, kept by `P_SectorBlockBox`):
  their heights cannot depend on that sector, and vanilla's height clip
  of every thing of the block box is a whole `P_CheckPosition` here
  (35 K cycles a static; the one case that differs is a thing already
  crushed by another sector, which vanilla would crush again). The tests
  compare against the C, which has the same differences.
- cc65 2.18 drops a member's offset from `((uint8_t *)&p->member)[n]`
  (it reads `p + n`): `FLAG()` (`doomtype.h`) is written `*(p + n)`, and
  `tests/test_game_core.py` checks the code cc65 makes of it.

### Interfaces for the monsters and specials parts

Their functions are declared in `p_local.h` and `p_spec.h`: `P_DamageMobj`, `P_KillMobj`,
`P_TouchSpecialThing`, `P_CheckSight`, `P_NoiseAlert`,
`P_MonstersSetupLevel` and the monster `A_*` actions (`info.h`);
`P_CrossSpecialLine(line, side, thing)`, `P_ShootSpecialLine(thing,
line)`, `P_UseSpecialLine(thing, line, side)`, `P_PlayerInSpecialSector`,
`P_SpawnSpecials`, `P_UpdateSpecials` and the `EV_*` (lines are indices).
The rules the core relies on:

- `P_DamageMobj`/`P_KillMobj` get actors only (the core wakes a static
  first); `P_TouchSpecialThing` may get a static's view: read it and
  remove it with `P_RemoveMobj(special)`, never keep the pointer.
- vanilla's `mobj->player` is `MO_PLAYER(mo)`, `mobj->info` is
  `&mobjinfo[mo->type]`, `mobj->subsector->sector` is `mo->sector`,
  `sector->soundtarget` is `sec_soundtarget[sector]`, floorz/ceilingz
  are map units, a monster's `A_Look` on a dormant static is called only
  when it can succeed and must do nothing otherwise, as vanilla's.
- Sectors: `sec_floorh/sec_ceilh/sec_special` (read), the setters
  `P_SetSectorFloor/Ceiling/Special`, `P_SectorTag`, `P_SectorLight`,
  `P_SetSectorLight`, `P_SectorFloorPic/CeilingPic`, `P_SectorLines` +
  `P_SecLine`, `P_ChangeSector`; lines: `P_Line`, `P_SetLineSpecial`,
  `P_LineSide`, `P_LevRead/P_LevWrite` for sidedefs; thinkers:
  `P_AllocThinker(size <= 32)` + `P_AddThinker`, freed after
  `P_RemoveThinker`; teleports: `P_FindTeleportDest`, `P_TeleportMove`;
  level memory: `P_ArenaAlloc` during set-up only.
- Assembly in those parts follows the conventions above; the W slots
  belong to their owners (a part adds its own slots only when it has
  room, there are 64).

### The monsters (p_sight, p_enemy, p_inter)

Vanilla's code for episode 1 (zombieman, sergeant, imp, demon and
spectre, lost soul, baron, the barrel; the player's pickups), in C for
the host and in assembly for the 6502 like the core: `P_CheckSight`,
`P_NoiseAlert`, `A_Look`/`A_Chase` with `P_Move`, `P_TryWalk`,
`P_NewChaseDir`, the range checks, `A_FaceTarget`, the attacks
(`A_PosAttack`, `A_SPosAttack`, `A_TroopAttack`, `A_SargAttack`,
`A_HeadAttack`, `A_SkullAttack`, `A_BruisAttack`), `A_Pain`, `A_Scream`,
`A_XScream`, `A_Fall`, `A_Explode`, `A_BossDeath` (E1M8: the last baron
lowers the tag 666 floors, `EV_DoFloorTag(666, lowerFloorToLowest)`, the
specials part's), `P_DamageMobj` (armour, thrust, pain chance,
infighting and its threshold, the sector 11 rule, god mode),
`P_KillMobj` (the drops, the kill count, the gibs), and
`P_TouchSpecialThing` for every E1 pickup with vanilla's limits (a
dropped clip or weapon is half, skill 1 doubles ammo). Results are
vanilla's at every tic: the random numbers are drawn in vanilla's order
(also when the answer is already known, as in `P_CheckMissileRange`).
Monsters open doors only through `P_UseSpecialLine` from `P_Move`, as
vanilla (the specials part's doors do the rest).

Decisions:

- **lastlook** (`mobj_t` byte 63): vanilla's `P_LookForPlayers` starts at
  player `lastlook` (a random 0-3 at spawn) and gives up when it comes
  round to it again: with one player a monster whose lastlook is 1 fails
  its first look and then always looks. A static keeps the bit
  (`SF_LOOK1`, drawn in the spawner, vanilla's order of random numbers)
  and passes it to the actor it becomes.
- **The behind-the-back question first.** Vanilla walks the sight line
  and then asks whether the player is more than 90 degrees off the
  monster's angle and farther than melee range; the answer is the same
  the other way round, and the angle is ~2 K cycles where the sight walk
  is ~100 K.
- **player.message is a number** (`MSG_*`, vanilla's d_englsh.h order),
  the status bar has the strings; `g_game.c` queues it after each tic.
- **The sound flood** is `P_RecursiveSound` as a queue (64 entries and a
  pending bit per sector; the recursion would not fit the 6502 stack),
  with the same result. Each sector's two-sided neighbours (sector,
  sound-blocking bit) are gathered once per level into a table in the
  game's far bank after GFAR and GOVL (so a flood reads one short far
  block per sector, not its lines), and an alert from a sector already
  flooded since the last height change (`sec_changes`, counted by
  `P_SetSectorFloor/Ceiling`) is skipped: the flood depends only on the
  start and the openings. `P_MonstersSetupLevel` takes the per-sector
  arrays (numsectors + 3 bitsets) from the arena and stops the game with
  `CRASH_ARENA` if the table does not fit the bank.
- **Sight** is vanilla's BSP walk (REJECT first) with an explicit stack
  (64 nodes; the deepest E1 tree needs 43). Side tests are done in whole
  map units where vanilla's are fixed (the node and line coordinates are
  whole units; 16x16 products by the 8x8 multiply) and give the same
  sides; a subsector's line list is cached (32 subsectors of up to 8
  lines). The sight slopes are the attack slopes' W slots
  (`W_TOPSLOPE`/`W_BOTTOMSLOPE`), as vanilla shares its globals. The
  C (`p_sight.c`) agrees with a floating-point ray caster on 400 random
  E1M1 pairs.
- **The node cache** is shared with `R_PointInSector` (`node_get`,
  exported from `a_levdata.s`).
- `movecount` is a signed byte that saturates (vanilla's int only goes
  below zero while a monster waits).

Assembly: `a_sight.s` 3,002 bytes of code + 856 BSS, `a_enemy.s` 4,568 +
37 RODATA + 319 BSS, `a_inter.s` 2,563 + 172 RODATA + 24 BSS: 10.1 KB of
code, 1.4 KB of data (cc65 made 16.5 KB of the C). Level memory
(arena): numsectors bytes and three bitsets of numsectors bits (E1M1:
about 130 bytes); the neighbour table is in far memory.

The py65 harness no longer fits the whole game in 64 KB with full
caches: it gives the monsters' assembly (segment `MCODE`, macro
`MONCODE` in `gmacros.inc`, with `-D MCODE_WINDOW`) and the C modules
(`--code-name MCODE2`) code-only windows at `$0300` and `$D000` that
overlay data (`tests/host/flat.cfg`; `gamesim.py`'s `HarvardMPU` fetches
instructions from the window images). This is a harness device, not the
Apple's memory map; code in a window reads no inline data. The specials
part's assembly shares the C modules' window (`SPECCODE` in
`aspec.inc`), which now runs from `$BE00` (just above CODE, which ends
at `$BBD6`) to the C stack, and its set-up code, in `GOVL` on the Apple,
goes to that window too: the harness has no room left to grow `GOVL` (it
holds E1M1's and E1M8's level memory with GAME.BIN's caches only).

Measured in the harness (full caches, E1M1, skill 2; `SimMonstersTest`:
four pistol volleys from four places wake 29 monsters, then 300 tics):

| | cycles |
|---|---|
| tic with 29 monsters awake | mean 716,847, p90 1,422,841, max 2,808,878 |
| of which per tic: `P_CheckSight` | 2.8 calls (1.4 walk the BSP), ~280 K |
| `P_TryMove` from `P_Move` (core) | 7.6 calls, ~48 K each, ~370 K |
| `A_Look` of the dormant | ~130 K |

A sight walk visits about 33 nodes, 15 subsectors, 37 segs and 21 lines
(E1M1 means). The budget (1.25 M cycles a frame) is not met at the
worst tics with many monsters awake: the cost is `P_TryMove` (its two
`R_PointInSector` and the blockmap) and the sight walks. Next steps:
a monster's `P_TryMove` in the core faster (the sector from the
subsector of the start, a cell cache per mover) and a monster's
last sight result kept until it, its target or a sector height changes
(exact: sight depends on nothing else).

### The specials (p_spec, p_doors, p_floor, p_plats, p_ceilng, p_lights, p_switch, p_telept)

Vanilla's line and sector specials, in C for the host and in assembly
for the 6502 like the core: `a_spec.s` (the table and the three entry
points, the sector tools, `T_MovePlane`, the player's special sectors,
lights, switches, the tic's part, the level set-up and its undoing) and
`a_movers.s` (doors, floors, stairs, the donut, plats, ceilings,
teleporters); `aspec.inc` has their records. Every vanilla line special
(1-141) is there, not only those E1 uses. Freedoom's E1 uses lines 1, 2,
7, 11, 19, 20, 22, 23, 26-28, 31-33, 36, 38, 46, 48, 51-53, 58, 61-63,
71, 75, 88, 97, 102, 103, 105, 107, 109, 112, 114, 117, 120, 123, 125,
126, 133 and 138, and sectors 1, 2, 3, 5, 7, 8, 9, 12, 16 and 17.

Decisions:

- **One table instead of vanilla's three switch statements**
  (`spec_tab`, 142 x 3 bytes): per special the trigger (walk over,
  switch, gun, manual door), once or repeatable, whether monsters trigger
  it, whether the switch texture changes whatever the action did (the
  exits, the lights, the gun lines), the action and its argument.
  `P_CrossSpecialLine`, `P_UseSpecialLine` and `P_ShootSpecialLine` check
  the trigger and run the action as vanilla's switches do (the texture
  changes only if the action started something, as `if (EV_...)`).
  Projectiles trigger nothing (vanilla's list of types is E1's
  `MF_MISSILE` things). A once-only line is cleared after its action,
  exits excepted (vanilla leaves them).
- **Heights are whole map units** (the far records are). A mover's speed
  is in eighths of a unit per tic, every vanilla speed being a multiple
  of `FRACUNIT/8` (stairs 1/4, the change-texture plats and the donut
  1/2, a blocked crusher 1/8); the eighths not yet moved are carried, so
  a slow plane moves a unit every 2, 4 or 8 tics and is where vanilla's
  is at every whole unit, and reaches its destination at vanilla's tic.
  A tic that moves nothing asks `P_ChangeSector` only for a crusher (its
  things still take damage every fourth tic).
- **`sector->specialdata` is a bit** per sector (`sec_busy`); the places
  that need the mover (a manual door turned around) find it in the
  thinker list, and never take a lift for a door (vanilla's bug).
  `activeplats`/`activeceilings` are the thinker list searched by tag; a
  plat or ceiling in stasis stays a thinker that does nothing.
- **Lights are not thinkers**: 8-byte records in level memory (the
  sector, kind, count, min, max, the level now, darktime or direction)
  run by `P_UpdateSpecials`, which writes a sector's far record only when
  its level changes; `SPARE_LIGHTS` (8) more for `EV_StartLightStrobing`.
  vanilla's quirks are kept: the flicker's `& 64` (bright 1 or 65 tics),
  the fire flicker's minimum above its maximum when its neighbour is
  brighter, `EV_LightTurnOn`'s level found once for all its sectors.
- **Switches**: the converter gives each `TEX` record its SW1/SW2 partner
  (`TEX_SWITCHTEX`); the front sidedef's top, middle, then bottom texture
  is swapped in its far record (vanilla searches its switch list: the
  same unless a sidedef has two switch textures). A repeatable switch is
  a button (16 slots) that comes back after `BUTTONTIME` (35) tics,
  counting the tic of the press. vanilla's exit switch sound
  (`sfx_swtchx`) never plays, as in vanilla (the special is cleared
  first).
- **Scrolling walls** (48): the front sidedef's x offset is its first
  value + `leveltime` + 1, written every tic.
- **Messages**: "you need a ... key" are `MSG_PD_*` in `player.message`
  (vanilla's `PD_BLUEK` etc.); `game_tic` clears `player.message` before
  the tic and queues what the tic left (`G_Message`, 4 entries, the
  oldest dropped) for the status bar (`G_NextMessage`), as vanilla's
  `HU_Ticker` takes and clears it.
- **Sounds of sectors have no origin** (`S_StartSound(NULL, ...)`) until
  the sound part wants sector positions.
- Guards where vanilla would crash: a door line without a back sector, a
  donut without a neighbour. `raiseToTexture` does not count texture 0
  ("-"; vanilla took texture 0's height).

**Undoing a level.** The renderer reads sectors and sidedefs from the
converter's far records, and the game has no WAD to reload them from, so
what the specials change stays changed; a restarted level (the player's
death) or a revisited one must look as the converter made it.
`P_ResetLevelData`, called by every level load after `P_LoadOverlay`:

- sectors change all the time (heights, light, special, floor flat):
  each map's `SECTORS` array is copied whole to a snapshot the first time
  the map is loaded, and back at every later load (E1's nine: 45,888
  bytes);
- lines and sidedefs change a few times a level (a once-only line's
  special, a once-only switch's texture): the bytes are journalled before
  the change (far address, length, old bytes: 6-byte entries, at most
  `JOURNAL_MAX` 341) and the journal is played back, newest first;
- pressed buttons are put back up and scrolled walls back to their first
  offsets from the part's near lists, which a level end leaves intact.

Both start in the specials' bank, `kbanks - 2` (126 in the banked build):
the journal at `$0200-$09FF`, snapshots from `$0A00`. Snapshot overflow descends
to another available bank. The banked allocator skips game backing 125, packet
124 and renderer backing 122, and refuses to cross into converted data or the
renderer cache (`DD_LAST_BANK+1`). Lower RAM in LC code banks is available once
the loader has installed their code.

**Level flow** (`g_game.c`): an exit sets `gameaction`; the next tic
makes the tally (`wminfo`, vanilla's `wbstartstruct_t` for one player:
episode, the map left and the next, secret exit, kills, items and
secrets of the level against its totals, the time in tics (`leveltics`,
32 bits: `leveltime` wraps after 31 minutes), Doom's par time) and goes
to `GS_INTERMISSION`, where the tic builds only the tic command and a new
press of fire or use (vanilla's `WI_checkForAccelerate`: the press on the
exit switch is still held) loads the next map (`ga_worlddone`). E1M8's
exit goes to `GS_FINALE` instead (vanilla's `ga_victory`: Doom 1 has no
tally after E1M8), where a press starts a new game at E1M1 with a new
player (`ga_newgame`). The player's counts are reset at every load
(vanilla's `P_SetupLevel`). The intermission and finale screens (the
status bar part) read `gamestate`, `wminfo` and `wi_tics`; meanwhile
`game_frame` goes on building the last view.

Memory: `a_spec.s` 3,697 bytes of code, 471 RODATA (the table 426), 309
BSS (the buttons 128), and 1,245 bytes of set-up and undo code in the
overlay (`GOVL`; in the py65 harness, with `-D MCODE_WINDOW`, in the code
window instead); `a_movers.s` 4,720 bytes of code, 74 BSS. Resident
9.3 KB (cc65 made 18.7 KB of the C). Level memory: the busy bits
(numsectors / 8), the tagged-sector list (4 bytes a tagged sector: 57 in
E1M7), the lights (8 bytes each, 9 in E1M1, 27 in E1M3, plus 8), the
scrolling walls (128 bytes): E1M1 about 330 bytes, E1M7 about 550; the
movers take thinker blocks.

Measured in the py65 harness (full caches, E1M1, skill 2;
`tests/test_game_specials.py`, `--profile` for the routines): with six
sectors moving at once (a door, three floors, the lift, a blazing door)
a tic costs 235 K on average against 42 K standing still, the rest being
the monsters' looks every tenth tic (1.1 M). Per moving sector and tic
about 9.7 K: `P_ChangeSector` 8.3 K (of which `P_SectorBlockBox` 1.4 K
and the `sec_bbox` test of each thing of the block box 0.4 K), the height
written near and far 1.0 K. Before the `sec_bbox` filter
`P_ChangeSector` cost 153 K (a whole `P_CheckPosition` for each static
of the block box) and the same six movers 848 K a tic. Lights: 1.2 K a
tic for E1M1's nine, 5.6 K for E1M2's eighteen (a level change costs
1.2 K, a far write); E1M2's two scrolling walls 2.1 K. Level loads: boot
and E1M1 8.78 M (the set-up scans every line's special for the
scrolling walls, one far byte each, and the snapshot is made), E1M8
loaded by `game_tic` 3.09 M (E1M1's journal played back, E1M8's
snapshot), a new game back on E1M1 7.98 M.

### Memory

The default banked build now fits the complete game and all nine converted
maps. Section 4 describes the implemented layout. Its actor pool retains
160 entries × 64 bytes; the shared C stack retains 2,048 bytes. No gameplay
ordering change or actor-cap reduction was needed.

The former overflowing layout required 71,297 resident bytes including linked
cc65 support, plus 8,194 bytes of math tables and a 5,347-byte setup overlay,
before dynamic level data. Those totals explain why simply enlarging bank 1
was insufficient; they are historical pre-partition measurements, not current
segment addresses. `BANKED=0` retains that legacy layout as a reference; capacity tests now
check the actual banked build.

The implemented savings are far blocklink heads and mobj metadata, smaller
16/32/16/8 line/node/subsector/cell caches, private/duplicated LC constants and
level accessors, the LC-built/far-published packet, and reused path-intercept
scratch. Statics, active actors and mutable level structures remain in shared
main RAM. Setup code is permanently banked instead of copied over actor slots.
The generated link report checks a conservative largest-level budget plus all
160 actors and the full stack; banked execution tests load every map at
Nightmare and verify stack guards. With the debug readout, the link has a
32,055-byte main arena, with a 1,451-byte conservative margin after level data
and the full actor pool.
The control LC bank occupies 11,963 of 12,282 non-vector bytes including the
packet. Generated `link-report.json` is the authority after further changes.
The observed sample used at most 64 bytes
of C-stack writes and 41 bytes of hardware stack; these are not exhaustive
bounds on every possible call chain.

### Measurements

The following measurements are historical flat-harness results. Its synthetic
code windows and old far-access surcharge differ from the banked runtime.
Use them to compare routines, not as hardware TURBO FPS. The first integrated
banked profile was about 12 M model cycles/frame before copy/packet optimization;
current optimization work and timing limitations are recorded in STATUS.md.

The whole game in the py65 harness (`tests/test_game_sim.py`; far
accesses charged what the kernel's cost in GAME space, 360 + 37 cycles
a byte; GAME.BIN's cache sizes, the code in the harness's windows, "The
monsters" above), E1M1 at "hurt me plenty", with the monsters (the
session's shots wake them: the standing tics include their thinking):

| | cycles |
|---|---|
| boot and E1M1 set-up (`game_init`) | 6,933,838 |
| tic, standing | mean 301,166, max 1,466,604 |
| tic, walking | mean 69,597, max 152,731 |
| tic, firing the pistol | mean 365,139, max 2,340,748 |
| `game_frame` (the render packet, 231 statics) | mean 370,670, max 410,905 |

(Before the monsters, with the harness's half-size caches: standing
57,392, walking 64,031, firing 163,583.)

A pistol shot with no target in front costs four traces (three autoaim
tries of 1,024 units, the shot of 2,048): about 2.2 M cycles, two
frames. Most of it is `P_PointOnDivlineSide` on every line of every
blockmap cell crossed (two FixedMuls per end point), the intercept
vector (four FixedMuls and a FixedDiv per crossed line) and line-cache
misses. The target is 150 K a tic; the next steps are a vertex side cache
per trace, traversing the intercepts cell by cell (the first one-sided
wall ends an aim), and a faster FixedDiv. The render packet is the other
cost: every thing is visited each frame; it should keep its candidates
between frames.

Primitives (`tests/test_game_asm.py`, GAME.BIN's cache sizes): FixedMul
877 mean / 1,649 max (random 32-bit operands), FixedDiv 4,491 / 4,982,
`fine_sine` 618 (a far read), `R_PointInSector` 15,952 at random points /
3,431 again at the same one, `P_Line` 212 cached / 2,275 fetched,
`P_BoxOnLineSide` about 415, `P_InterceptVector` about 9,800,
`P_PathTraverse` (lines only, random traces of 64-2,048 units) 154,625
mean / 887,983 max.

### Tests

The banked suites now add actual memory mapping, nested calls and interrupt
boundaries, all nine map loads with the full actor pool, differential gameplay,
far-data equivalence, snapshot allocation, and complete loader/game/renderer
frames. See STATUS.md for the scope of each suite. These complement the
historical host and flat-reference tests below.

- `tests/test_game_info.py`: `gen_info.py` and `gen_offsets.py` are
  current; every kept state and type equals vanilla's info.c
  (chocolate-doom, `DOOM_VANILLA_SRC`); the E1 monsters', projectiles',
  barrel's and weapons' frame sequences and properties equal ZDoom's
  actor definitions (`DOOM_ZDOOM_ACTORS`, its `zscript/doom`; ZDoom's own
  additions and the three places it changed vanilla are listed).
- `tests/test_game_core.py` (host): spawn counts per type and skill,
  every map loads, walking into walls, sliding, steps up and not too
  high, falling, the pistol's puff and a barrel woken and hurt, the
  render packet; cc65's code for `FLAG()`; the GAME-space link and its
  budget.
- `tests/test_game_asm.py` (py65, module by module against the host C):
  FixedMul/FixedDiv against vanilla's 64-bit definitions, the sine
  tables, the level arrays, every E1M1 line and blockmap cell,
  R_PointInSector, REJECT, the sector setters, line/box/divline sides,
  intercept vectors, line openings, block coordinates, path traversal,
  thing links and iterators, line marks.
- `tests/test_game_sim.py` (py65, the whole game against the host tic by
  tic: a 290-tic session on E1M1, a barrel shot until it explodes, E1M8
  loaded by `game_tic` and played; with the measurements above; the
  monsters: 29 awake over 300 tics, E1M8's barons, the pickups of 14
  kinds, all against the host tic by tic).
- `tests/test_game_monsters.py` (host): sight against a ray caster and
  REJECT, the BSP depth; a zombieman wakes, sees, sounds, shoots and
  hits; the pistol kills one (death states, corpse, kill count, the
  clip dropped and picked up for half); an imp's fireball; a monster
  uses a door line; every pickup with its limits and messages; armour,
  thrust, pain and infighting; a barrel chain; the sound flood against a
  Python transcription of vanilla's recursion and a shot waking the
  map; a lost soul's charge; E1M8's boss death.
- `tests/test_game_specials.py`: on the host, through `game_init` and
  `game_tic` (its own library, with `tests/host/host_spec.c`): E1M1's
  first door opens with use (2 a tic, 4 below the lowest neighbouring
  ceiling), waits `VDOORWAIT`, closes, is free again, the far record
  following the near heights every tic; a door turned around; a lift by
  its switch and by walking over its line (down, 3 s, up); a button
  (E1M3's switch 928: the other texture for a second); a once-only
  switch (its texture for good, its special cleared, its three floors
  lowered); the exit switch, the intermission and its tally, E1M2
  loaded on a new press and E1M1's lines and sidedefs back as they were;
  E1M3's secret exit to E1M9; E1M8's exit, the finale and a new game;
  a restart after the player's death with every bank as the converter
  made it (but for the new level's lights); the blue door refused (the
  message queued, "oof") and opened with the blue skull key; nukage (5
  every 32 tics, none with the suit); a secret counted once; strobes,
  flickers, glows and fire flickers; scrolling walls; E1M4's teleporter;
  E1M3's stairs. On the 6502 against the host, tic by tic (the sectors,
  the specials' lines and sidedefs, the level flow, and all of
  `test_game_sim.py`'s comparisons): E1M1's door, switch, floors, lift,
  blazing door, blue door, nukage and secret, then E1M8's exit, the
  finale and a new game on E1M1 (whose banks must then equal the
  host's); E1M1's exit to E1M2 and E1M2's glows, fire flickers,
  scrolling walls, lifts, floors, doors and teleporter (the half-size
  caches: E1M2 does not fit the harness with GAME.BIN's); and 23 rounds
  that rewrite two E1M1 lines' specials to cover the EV_ routines E1
  does not use (stairs, donut, crushers, every plat and floor type,
  lights, locked blazing doors, teleport search), plus sector specials
  10, 14 and lights spawned at run time. `--profile` gives the routine
  costs above.

## 10. Input

Mouse X turns (Doom's mouse sensitivity), mouse button fires. The held
key (`$C000` while `$C010` bit 7 is set) moves: up/down arrows or W/S
forward and back, left/right arrows turn, A/D (or `,`/`.`) strafe. Open
Apple fires, Closed Apple uses (doors, switches); both work while a
movement key is held. `1`-`7` select weapons; Tab toggles run. Esc sets
an input flag, but menu UI and its consumer are not implemented.

## 11. Sound

`S_StartSound` currently records effect IDs in an eight-entry history and
increments `snd_count`; tests compare those events. There is no audible Phasor
backend yet. AY tone/noise/envelope recipes and priorities, followed by MUS
music, remain planned work.

## 12. Build and test

See [../README.md](../README.md) for dependencies and commands. `make` defaults
to `BANKED=1` with the real converted data. It fetches/converts Freedoom if
necessary, invokes `tools/build_banked.py`, and runs `tools/check_link.py` on
the completed banked images. `make disk` packages the five program files
(`DOOM.SYSTEM`, `RENDER.BIN`, `LC.BIN`, `GAME.BIN`, `DOOM.BANKS`) and converted
data into a verified ProDOS volume at `dist/Appletini-DOOM.hdv`. The generated
link report, not an old snapshot of object sizes, is the current memory budget.

```sh
make
make disk
python3 tools/run_doom.py --build build --data build/data --speed 33 --frames 180 --out build/run
make test
```

`make STANDIN=1` uses the small platform skeleton and test pattern under
`build/standin`, with its own generated data. `BANKED=0` selects the old memory
layout; the full game is too large for it. The flat game harness's synthetic
instruction windows serve differential testing only.

`tools/a2sim.py` now maps auxiliary LC, ZP and hardware stack to the selected
RamWorks bank. `tools/run_doom.py` boots the assembled loader through FakeProDOS
(or installs its images directly with `--fast`), drives scripted input, saves
PAL256 screenshots and reports model cycles. `--frames` counts model 60 Hz
intervals. Kernel PC events and idle hooks are qualified by the main LC context,
since auxiliary game code deliberately reuses those addresses.

`test_doom_banked_platform.py` covers complete loading and live game/render
frames with real kernel far copies; `test_game_banked.py` covers the mapped
game with trapped far transport. `test_game_banks.py` checks nested bank calls
and IRQ injection. Existing platform/disk and renderer/reference suites remain
separate regression tests. None constitutes a physical Appletini TURBO timing
measurement; the Python harness's mode named `turbo` is a nominal cycle model,
and a conventional emulator at 33 MHz is a different execution environment.
