# The native renderer: the front end

The renderer is a 65C02 rewrite of the renderer of Webifi's IIgs DOOM
(upstream, fetched into `build/upstream/src/iigs/`). Its output equals
upstream's bit for bit: the same records, clips, drawsegs and pixels.
Upstream's arithmetic shortcuts are reproduced, not fixed (`qmulh`'s
"+ 0 or 1", scaleFast's 1.001 step, `STEP8E`'s 8-bit edge fractions).

Two documents describe it:

- this one, the **front end**: from `R_FillStamps` to `drawMasked`'s
  entry. The plane stamps, the frame setup, the BSP walk, wall setup,
  the seg loops, the fills and the sky. Its output is a stream of
  records, the drawsegs, the openings and the clips.
- [`RENDER-MASKED.md`](RENDER-MASKED.md), the **masked phase and the
  whole frame**: the weapon's clip pass, sprites, masked walls, the
  weapon, the bucket pass and the replay that draws the records.

Where the game calls the renderer, and what else runs in a frame, is in
[`PLAY.md`](PLAY.md). Every address of the renderer is in
`tools/native/rlayout.py`; [`MEMORY_MAP.md`](MEMORY_MAP.md) places it
among the rest of the game. Citations like `r_bsp65.s:730` are
upstream's files.

## 1. Files and build

| File | What it is |
| --- | --- |
| `src/native/rframe.s` | `nr_frame`: the plane stamps, setup, clears, the weapon skip, the walk, the last batch |
| `src/native/rbsp.s` | `nr_bsp`: the BSP walk, `nr_side`, `nr_checkbox`, subsectors, `clipwall`, the vertex-angle and box-corner caches, `nr_addsprites` |
| `src/native/rlight.s` | `nr_planes` (a sector's plane colours, worldbottom), `nr_walllight` |
| `src/native/rwall.s` | `nr_storewall`: `R_StoreWallRange` |
| `src/native/rseg.s`, `rseg.inc` | `nr_segloop`: `R_RenderSegLoop`, genColumn, the masked-only loop, texCol, the tiers, the fills; the loops' macros |
| `gen/segloops.s` | The 13 seg loops, written by `tools/native/seggen.py` |
| `src/native/rsky.s` | `sky_col` (sky columns), `tier_flat` (columns with no patch) |
| `src/native/rrec.s` | The record batch, the staging, the model of upstream's list pages |
| `src/native/wclip.s`, `wpsp.s` | The weapon's clip pass (described in `RENDER-MASKED.md`) |
| `src/native/far.s` | Card bank 1: `far_get`, `far_put`, the vertex-angle gather, the `FSTEP` gather, the image loaders |
| `src/native/auxlc.s` | The aux card's table reads: `ax_vtox`, `ax_tanto`, `ax_tan3`, `ax_tan4` |
| `src/native/gvalid.s` | `gv_inc`, the one `validcount` the game and the renderer share; at a wrap every stamp cleared (`gv_clear`) |
| `src/native/math.s` | The products and divides ([`src/native/MATH.md`](../src/native/MATH.md)), assembled with `-D RENDER` |
| `src/native/render.mk`, `render.cfg` | The build and the ld65 map |
| `tools/native/rlayout.py` | Every address, bank, record layout and zero-page byte; writes `gen/rlayout.inc` and checks overlaps |
| `tools/native/rendercap.py`, `rtables.py` | The constant tables, taken from the reference machine's RAM (section 4) |

`render.mk` builds two things into `build/native/render/obj`, both the
release build (`RELEASE = 1`, the default: `rrec.s`, `bucket.s` and
`replay.s` assembled with `-D RELEASE`, so a frame whose records pass a
limit is cut and completes, `RENDER-MASKED.md` 10):

- **`rcard`**, the link the disk takes its render images from. It holds
  the front end's W image (`%O.w`), the masked phase's W image
  (`%O.wm`), the card parts (`.lc1`, `.far`, `.lc2`, `.rc`) and the
  replay's main and aux tables (`.m08`, `.a02`, `.a08`). Its objects are
  the `-D RPROF` ones: each phase start stores its number times 2 at
  `$0300`, a few dozen cycles a frame. The link also holds a card runner
  (`rrunner.s`) at `$E000`, which the disk does not take.
- **the frame's objects** that `m11/s2ovl.mk` links into the frame image
  `ovf`. The automap overlay `OVLW` is linked against `ovf`'s labels
  ([`SCREENS.md`](SCREENS.md)); `s2ovl.py --check-frame` checks that
  what OVLW takes from `ovf`, and its own `BKFAR`, `BKFAR2` and `BKNEAR`,
  are at `rcard`'s places.

`make -f render.mk stops` links the same `rcard` without `-D RELEASE`
into `build/native/render/stops`: there each limit stops the frame
(`STATUS`, `BRK`). No disk takes it.

Generated sources: `gen/rlayout.inc` (`rlayout.py`), `gen/segloops.s`
(`seggen.py`), `gen/layout.inc` and `gen/rows.s` (`rowgen.py`, the
replay's), `gen/llayout.inc` and `gen/lgame.inc` (`llayout.py`, for
`gvalid.s`'s clear). The tables come from `build/native/render/tables`
(`rtables.py`); `render.mk` stops with a message when they are missing.

`gvalid.s` is linked into the render images with `-D GV_RENDER`:
`nr_setup` adds 1 to `validcount`, and when that wraps it to 0 the
renderer's own `gv_clear` zeroes every sector's stamp (`LVMAP`) and each
line's two stamps (`LVG0`), one `RAMWRT` window a bank with the far
layer's zero page, and the count becomes 1, as the game's increments do
([`GAME.md`](GAME.md), [`LEVELS.md`](LEVELS.md) 6). Nothing needs a
flush: the game's caches are written back and emptied at the end of
every tic phase, and `nr_setup` runs before the walk fetches a sector.

## 2. Principles

1. **Records the renderer reads from RamWorks are arrays of records.**
   Each has a power-of-two stride, or 24 for segs. One `far_get` fetches
   a record whole into zero page or main memory. A PSRAM line is 8 bytes
   and a miss costs about 131 clocks on F1.2.1; byte planes would cost a
   miss per field.
2. **Arrays indexed by column live in main memory as byte planes**, X =
   column 0-159.
3. **Indexes are bytes where the counts allow**: sectors (`$FF`: none),
   textures, drawsegs. Nodes, segs, sides, lines, subsectors and
   vertices are 16-bit.
4. **Values are upstream's, bit for bit.** A field is narrowed only when
   the converter proves every value fits; the reader widens it exactly.
5. **No derived address tables.** Upstream's `CORE_LN36`, `CORE_SEC58`
   and `CORE_NODEADR` become an index times a power of two.
6. **No per-column pointer table.** A wall column's texel address is
   computed from the texture directory (section 3.2).

## 3. Level data the renderer reads

The level converter makes these records ([`LEVELS.md`](LEVELS.md):
`tools/native/wadconv.py`, with `levelconv.py`'s record code). The level
load copies them into the banks below.

### 3.1 Geometry

| Array | Bank, base | Stride | Fields | Capacity |
| --- | --- | ---: | --- | ---: |
| Segs | `LVSEG` (6), `$0200` | 24 | v1.x, v1.y, v2.x, v2.y, offset, angle, side, line (2 each); front sector, back sector (1 each, `$FF`: one-sided); v1 and v2 vertex numbers (2 each); the line's peg flags (1); pad | 2,026 |
| Nodes | `LVMAP` (7), `$0200` | 32 | x, y, dx, dy (2 each); bbox[0], bbox[1] (8 each); children[2] (2 each, bit 15: a subsector); the box-corner cache's tag (2); 2 bytes the walk's node frame uses | 768 |
| Subsectors | `LVMAP`, `$6200` | 4 | sector (1), seg count (1), first seg (2) | 768 |
| Vertex-angle cache | `LVMAP`, `$6E00` | planes | angle low, angle high, stamp: one byte each by vertex number | 1,536 |
| Sectors, render part | `LVMAP`, `$8000` | 16 | floorheight, ceilingheight (4 each); floorpic, ceilingpic, lightlevel (1 each); validcount (2); the thing list's head (2, a render-thing slot, `$FFFF`: none); pad | 255 |
| Sides, render part | `LVMAP`, `$9000` | 8 | textureoffset, rowoffset (2 each); top, bottom, mid texture (1 each); the side's sector (1, read by the level load, not the renderer) | 1,024 |
| Patchless columns | `LVMAP`, `$B000-$BFFF` | | `TXFLAT`: an index of 256, then a bitmap of 32 bytes for each texture that has columns with no patch | |
| Lines mapped | main `LNMAP` `$1B80` | 1 bit | `ML_MAPPED`, the only line field the front end writes | 2,048 |
| `texturetranslation` | main `TEXTRANS` `$1A80` | 1 | by texture number | 256 |

The largest E1 maps stay well inside: E1M6 has 250 sectors, 805 sides,
606 subsectors, 605 nodes, 1,862 segs and 1,207 seg vertices. The
longest node chain from the root is 19.

Pics are signed bytes: 0-127, and `$FE` for a sky ceiling (upstream's
-2, `skyflatnum`'s "the sky is a flat colour"). Segs, nodes, subsectors
and the peg flags are constant for a level. Sector heights, pics and
lights, side textures and offsets change in play and are written by the
game logic. `validcount` stamps are written by both the game and the
renderer.

**The vertex-angle cache.** Upstream caches `R_PointToAngle16` of each
seg vertex while the view stays at one map unit (`r_bsp65.s:106-128`).
`pointAngle` reads only the map units of the point and of the view, so
the cache never changes a result, only the time: about 19 µs for each
angle computed. The native cache follows upstream's rule. At `nr_bsp`
entry, when the view's map unit (`viewx`, `viewy` bits 16-31) differs
from `VA_VX`, `VA_VY`, or the stamp is 0, it stores the map unit and
advances the one-byte stamp `VA_STAMP`. When the stamp wraps from 255,
`far_vclear` clears every vertex stamp and the stamp starts at 1. An
entry is valid when its stamp equals the current one. The level's
converter numbers the distinct seg end points itself.

**The box-corner cache.** A box corner's angle also depends only on the
corner and the view's map unit. While the view stays at one unit, the
angles of the two corners a node last checked are kept in `RENDB`'s
`CCANG` (4 bytes a node, at `$2000` + the node's address / 8). The
node's tag (the unit's stamp, the box and the case) is in its record's
pad, so the walk gets it with the node. `CCSTATE` (`RENDB` `$1C00`, 5
bytes) holds the unit and its stamp, read once a frame (`cc_frame`). A
frame at a new unit neither reads nor writes entries. Later frames at
the unit read them (one `RAMRD` window a box) and write the ones they
miss (one `RAMWRT` window). The level load writes tags of 0, which no
stamp takes.

### 3.2 Textures and texels

**One 128-byte slot per texture column.** Upstream's record carries a
24-bit texel pointer, and the replay reads up to 127 bytes past it,
wrapping the texel index with `and #$7f`. So the texels a record can
show are exactly the 128 bytes that follow its pointer in upstream's
memory. The converter copies, for each column c of each texture t,
those 128 bytes into a slot:

    slot(t, c) = TXLO/TXHI[t] + 128 * (c & TXWM[t])    in bank TXBANK[t]

A texture is at most 256 columns wide, so its slots take at most 32 KB
and never cross a bank. A record's `R_SRC` is the slot's (low, high,
bank): a 16-bit add per tier record replaces upstream's column-table
read. The slots live in the level store's texel banks, shared by the
maps; the level load applies a map's own column bytes where they differ
([`LEVELS.md`](LEVELS.md)).

| Table | Where | Content |
| --- | --- | --- |
| `TXBANK`, `TXLO`, `TXHI` | W `$B400`, `$B500`, `$B600` | Bank and address of each texture's slot 0. Bit 7 of `TXBANK` flags a texture with patchless columns |
| `TXWM` | W `$B700` | Widthmask; 0 with `TXBANK` 0: no slots |
| `TXHT` | W `$B800` | `textureheight` in map units, every texture's, for `rowMod` and the masked walls |
| `TXFLAT` | `LVMAP` `$B000` | The patchless columns' bitmaps (section 3.1) |
| Sky slots | the frame block's `SKYBANK`, `SKYLO`, `SKYHI` | 256 slots of 128 bytes: the bytes after `skypatch + columnofs[c] + 3` for c = 0-255 |

The W tables are per level. They sit in the front end's W image with
`FLATCM` and are loaded with the code each frame.

### 3.3 Light, colour and colormap tables

| Table | Native | Where |
| --- | --- | --- |
| `SMAP` | 64 bytes: `SMAP[lightnum + 16]` = startmap + 24, clamped (`r_bsp65.s:1000-1008`) | W code (`smap.bin`) |
| `PCMO` | Two byte planes of 69: the row of `FLATCM` for startmap + 24 - d (`r_bsp65.s:1021-1032`) | W code |
| `PGT` | 88 bytes: the record page `$46 + L` of colormap A for a light distance (`r_seg65.s:3149-3171`). A record's page is `PGT[W_LV - d]` | W code (and the masked image) |
| `FLATCM` | 34 × 32 bytes per level: each colormap's flat colours | W `$AFC0-$B3FF` |
| Colormaps A and B | light levels 0-31 at pages `$20-$3F` (A) and `$40-$5F` (B) | main `$2000-$5FFF`, per level |

The light of a sector, as upstream (`rlight.s`): lightnum = (lightlevel
>> 4) + extralight + gamma gives startmap = (15 - lightnum) × 4, and a
plane takes startmap - 10. The planes leave extralight out
(`r_bsp65.s:678-680`). A fixed colormap replaces all: `LT_FIXED` = n ×
256. The frame block holds `LT_BASE` (extralight + gamma + 16),
`LT_FIXED` and `LT_I`.

## 4. Constant tables from the reference machine

The constant tables are taken from upstream's own RAM, not computed by
formula, then checked against a formula where one exists. The build
(`build.sh`) does it in two steps:

1. `tools/native/rendercap.py` runs upstream's release image on the
   reference machine `ref816` through scripted runs (a new game, the
   title demos, a tour of E1, a run with the fixed colormaps). At chosen
   frames it dumps all RAM at `R_FillStamps`: the **level sources**
   (`build/native/render/levels/src/*.ram.z`). It also writes per-frame
   dumps under `build/native/render/frames`, which the disk does not
   use. Every run is bounded in time and size and checks free disk
   space first.
2. `tools/native/rtables.py` reads the tables from a level source by
   symbol, checks that every other source holds the same, and writes
   `build/native/render/tables`: `tables.img` (records for the aux card
   and RamWorks), the `.bin` files the W code includes, and `math/`
   (`mathtables.py`'s tables of `src/native/math.inc`). The release
   builds `FSTEP_TABLE` and the square tables at boot
   (`m_recip65.s:355-396`), so they too are read from the running
   game's RAM. The sprite tables come from a source whose frame had
   made them (`PR_IOK` set).

Checks, each a failure: every table equal to the reference's RAM;
`FSTEP` entries for L ≥ 512 equal 33,554,431 / L; `SMAP`, `PCMO`, `CMO`
and `PGT` equal their formulas; the derived `c26Reverse` equal
upstream's copy; `tantoangle` entry 2,048 is ANG45; the sprite scale
tables equal their C expressions (see `RENDER-MASKED.md`).

| Table | Size | Used by | Placement | Read by |
| --- | --- | --- | --- | --- |
| `xtoviewangle` | 161 words | `scaleFast`, `tcExact`, sky, `R_ScaleFromGlobalAngle` | main `$09A9` (low), `$0AF3` (high), in the replay's table pages | `abs,X` |
| `viewangletox` | 2,042 bytes (values 0-160) | `boxAngles`, the seg clip | aux card bank 1 `$D800`, one plane | `ax_vtox` |
| `finetangent` part 3 | 1,024 words | `tcExact` | aux card bank 1 `$D000` (low), `$D400` (high) | `ax_tan3` |
| `finetangent` part 4 | 1,024 longs | `tcExact` | aux card bank 2 `$D000`, four planes | `ax_tan4` |
| `tantoangle` | 2,049 longs | `pta16` (the walk, the projection) | aux card `$E000`, four planes of 2,048; entry 2,048 a constant in `math.s` | `ax_tanto` |
| `finesine` part 1, the sine of `finesineapprox` | | `sinA`, `nr_setup`, `R_ScaleFromGlobalAngle` | the math's tables bank `MT_TBANK` (120) | `mt_far` |
| `RECIP_TABLE` | 32,768 words | `normD`, `fsGeneral`, `approxdiv` | banks 121 (low), 122 (high) | `mt_far` |
| `FSTEP_TABLE` | 65,536 words | the seg's `FSTEP` gather | banks 116-119: entries 16,384 k to 16,384 k + 16,383 in bank 116 + k, low plane `$2000`, high plane `$6000` | `far_fstep` |
| `KS` | 161 words | `scaleFast` | W code | `abs,X` |
| `BXR0`, `BXLIM` | 9 words each | `checkBox`'s arcs | W code | `abs,X` |
| Quarter squares | 2 KB | every product | main card bank 1 `$D000-$D7FF` | direct |

Upstream's product tables (`SQL`, `SQH`, `iigs_mulT`) are not used: the
products of `math.s` are exact. `viewangletox` is one byte plane because
upstream reads it as a word masked to its low byte
(`r_bsp65.s:524-534`).

## 5. Per-frame state

### 5.1 The frame block and the render inputs

**The render inputs** (`$0370-$039F`, 43 of 48 bytes) are the game
state the renderer reads: the player's x, y, angle, viewz, extralight,
fixed colormap, gamma; each psprite's sprite, frame, sx and sy; the
player's sector light and invisibility. The game writes them before the
frame ([`GAME.md`](GAME.md)).

**The frame block** (`$0310-$036F`, 95 of 96 bytes; `rlayout.py` fails
the build past 96) is what the frame computes plus the renderer's
persistent state:

| Fields | What |
| --- | --- |
| `VIEWX`, `VIEWY`, `VIEWZ`, `VIEWANGLE`, `VIEWA16`, `VIEWSIN`, `VIEWCOS` | The view, from `nr_setup` |
| `EXTRALIGHT`, `LT_BASE`, `LT_FIXED`, `LT_I` | Light numbers |
| `VALIDCOUNT`, `NUMNODES`, `SKYFLAT`, `NUKAGE` | Game and level state |
| `VIEWTOP`, `VIEWBOT`, `AUTOMAP`, `PSPF` | The view window, the automap mode, the psprite flags |
| `W_FSC`, `W_FSP`, `W_TOPR`, `W_BOTR`, `W_FSG`, `W_FSW` | The fill spans' frame stamps (persistent) |
| `FR_SKIP`, `W_WSK`, `MM_WPOK` | The weapon skip |
| `VA_VX`, `VA_VY`, `VA_STAMP`, `NVERT`, `VA_COUNT` | The vertex-angle cache |
| `STG_PTR`, `STG_BANK`, `DSCOUNT`, `LASTOPEN` | Where the next staged byte goes; drawsegs and openings used |
| `STATUS`, `RULES` | The stop code; the rules of our own the frame took (section 9) |
| `W_LCC`, `W_LFC`, `W_CEILW`, `W_FLOORW` | The fill bytes and their plane colours, kept from wall to wall |
| `DIDSOLID`, `RW_STEP` | didsolidcol; rw_scalestep (persistent: section 7.3) |
| `SKYBANK`, `SKYLO`, `SKYHI` | The sky's slot 0 |
| `SPRN`, `FZPOS`, `NVIS`, `XPUSED`, `UPFLUSH`, `RECSEQ`, `RECDROP` | The masked phase's (`RENDER-MASKED.md`) |

### 5.2 State kept across frames

| State | Where |
| --- | --- |
| Fill spans and their stamps | main `$0F00-$13FF`, 8 planes; the stamps in the frame block |
| Weapon skip: `WCLIP`, `WPREV`, `FRVIS`, `WTMP` | main `$1800`, `$18A0`, `$18B0`, `$18E0` |
| `RW_STEP`, `FZPOS` | frame block |
| Vertex-angle cache, box-corner cache | `LVMAP` planes and the frame block; `RENDB` `CCSTATE`, `CCANG` |
| `validcount` and every sector's stamp | frame block, sector records |

Upstream's lists are empty when a frame starts (the replay of the frame
before emptied them), so `rec_start` empties the staging.

## 6. Memory

### 6.1 Zero page and stack

| Range | Owner | Content |
| --- | --- | --- |
| `$00-$05` | far layer | `FA_DST`, `FA_SRC`, `FA_BANK`, `FA_N` |
| `$06-$07` | | reserved |
| `$08-$17` | platform | |
| `$18-$41` | overlay 1 | The walk and wall setup: the node frame pointer, the clip state, the seg, the sector, the plane colours, the box-corner cache's bytes |
| `$42-$47` | | no symbol |
| `$48-$AF` | overlay 2 | The seg page, the hot part of the seg descriptor: the four edges and their steps, the column's rows, texCol's state, the seg's flags and light, the tiers' texturemids, the batch count, the gather's scale and step |
| `$B0-$D7` | math | `math.inc`'s block |
| `$D8-$FF` | IRQ | |

What does not fit goes to the spill `$0280-$02FF` (worldbottom, the
plane colormap row, the seg descriptor's cold part: rw_x, rw_scale,
scale2, rw_distance, the light, the normal angle, rw_offset,
rw_centerangle, the three texturemids, the masked columns' index;
genColumn's words) and to main `$0DA0-$0DFF` (wall setup's own
variables). Overlay 2's `$48-$6F` is also the replay's; the phases never
overlap. The masked phase reuses both overlays (`RENDER-MASKED.md`).

**Stack.** The walk recurses with `JSR` and keeps each level's node in a
node frame of W, so a level costs 2 bytes. The render phase's stack
budget is 112 bytes plus 24 for an interrupt (`rlayout.RENDER_STACK`,
`IRQ_STACK`); the deepest measured render frame used 83 bytes.

### 6.2 Main memory

| Range | Content |
| --- | --- |
| `$0200-$0277` | Bounce buffer: a subsector's segs, 5 at a time (24 bytes each) |
| `$0280-$02FF` | Zero-page spill |
| `$0300` | Phase mark byte |
| `$0310-$036F` | Frame block |
| `$0370-$039F` | Render inputs |
| `$03A0-$03A3` | The level's counts of sectors and sides |
| `$0800-$0BFF` | The replay's tables, `xtoviewangle` at `$09A9`, `$0AF3` |
| `$0C00`, `$0D00`, `$0E00` | `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL`: 160 bytes each. The clips are held + 1, as bytes 0-169 |
| `$0DA0-$0DFF` | Wall setup's variables |
| `$0F00-$13FF` | Fill spans (persistent) |
| `$1400-$167F` | Covered ranges (`CVFIRST`, `CVEND`, `CVRECLO/HI` from `$1540`) |
| `$1680-$17C1` | The replay's `COLLO`/`COLHI`; during the render `UPOFS` (`$1680`) and `FRORD` (`$1720`) |
| `$1800-$197F` | `WCLIP`, `WPREV`, `FRVIS`, `WTMP` |
| `$1980`, `$1A00` | `DSX1`, `DSX2`: x1 (255: the drawseg clips no sprite and has no masked columns) and x2 of each drawseg |
| `$1A80` | `TEXTRANS` |
| `$1B80` | `LNMAP` |
| `$2000-$5FFF` | Colormaps |
| `$6000-$BFFF` | W: the render window (section 6.3) |

### 6.3 W in the front end

W holds the front end's image while the walk runs. The game loads the
image each frame, because the tic phase uses W before it
([`PLAY.md`](PLAY.md)). Self-modified bytes therefore start from the
image every frame.

| Range | Content |
| --- | --- |
| `$6000-$6592` | `MATHW` (the math's render subset, 1,281 B) and `AUXW` (the aux card's reads, 146 B). The masked image leaves them in place |
| `$6593-$ACFF` | The front end's code `RENDERW` (16,388 B in the current link, to `$A596`) with its small constant tables |
| `$AD00-$AE9F` | `FCNTLO`, `FCNTHI`: each column's bytes of records, kept by `rec_room` for the bucket pass |
| `$AFC0-$B3FF` | `FLATCM` (per level) |
| `$B400-$B8FF` | `TXBANK`, `TXLO`, `TXHI`, `TXWM`, `TXHT` (per level; kept by the masked phase) |
| `$B900-$B9FF` | The record batch buffer (kept by the masked phase) |
| `$BA00-$BC7F` | Node frames: 20 levels × 32 bytes. Before the walk, the weapon's clip pass uses the same bytes |
| `$BC80-$BDBF` | Each column's `FSTEP` for the current seg, low and high planes |
| `$BDC0-$BEFF` | Each column's masked texture column for the current seg, low and high |
| `$BF00-$BF27` | The wall's sector frame: front sector (16), side (8), back sector (16) |
| `$BF28-$BFC7` | `DLW`: each column's light distance d, for a seg whose light varies |
| `$BFC8-$BFE7` | The drawseg being built |

The image loaded each frame is the code pages and the per-level table
pages `$AF00-$B8FF`. The game loads it from `$6500`, because the tic
image leaves the same bytes in `$6000-$64FF` (74 pages,
`far_wloadt`'s list; the kernel copies the same runs through the memory
API when it is present).

### 6.4 The language cards

Main card bank 1, `$D000-$DFFF`, selected during the render:

| Range | Content |
| --- | --- |
| `$D000-$D7FF` | Quarter squares |
| `$D800-$DB5B` | `MATHLC`: the products |
| `$DC00-$DC42` | `MATHFAR` |
| `$DC43-$DE4C` | `RFAR` (`far.s`): `far_get`, `far_put`, the vertex-angle gather and write-back, `far_vclear`, the `FSTEP` gather |
| `$DE4D-$DE97` | `RLOAD`: the image loaders (`far_pload`, `far_wload`, `far_wloadt`) |
| `$DE98-$DFE5` | `MFAR`: the masked phase's card code |

Main card bank 2 `$D000-$DFFF` and `$F900-$FEFF` hold the replay and the
bucket pass's card part (`RENDER-MASKED.md`).

Card code is needed for any loop that runs inside a `RAMRD` window:
there only zero page, the stack and the card are readable, and `RAMRD`
also moves opcode fetches from `$0200-$BFFF`. Inputs come from zero page
or the card; outputs go to W, since `RAMWRT` stays off. `RAMWRT` windows
(record flushes, `saveClip`, `far_put`) and `ALTZP` windows run from W.

**The aux card** holds the four read-only tables of section 4.
`auxlc.s` reads them in windows of straight-line code in W: `SEI`,
`ALTZP` on, the loads (for part 4, two `$C083` reads select bank 2 and
two `$C08B` reads bank 1 again), `ALTZP` off, `CLI`. Nothing inside touches zero page
or the stack. The operand's high byte is patched before each window.

### 6.5 RamWorks banks

The renderer's own banks are `rlayout.py`'s; the level store's are
[`LEVELS.md`](LEVELS.md)'s.

| Bank | Name | Content | Written in the frame |
| --- | --- | --- | --- |
| 6 | `LVSEG` | Segs | no |
| 7 | `LVMAP` | Nodes (with their corner tags), subsectors, vertex-angle cache, sectors, sides, `TXFLAT` | the caches, `validcount` stamps |
| 8 | `RENDB` | Drawsegs (128 × 32 B at `$0200`), `OPENHI` (`$1200`), `CCSTATE`, `CCANG` | yes |
| 9-31, 56-63 | | The level store's texel slots and sky slots | no |
| 48-50 | `SPRT`, `WPRO`, `RTH` | Sprite data (`RENDER-MASKED.md`) | `RTH` by the game |
| 51-54 | `RECSP` | Record spill after aux 0's staging | yes |
| 55 | `RECW` | Parked batches (`RENDER-MASKED.md`) | yes |
| 112 | `WCODE_BANK` | The front end's W image at its own addresses, with the level's W tables | no |
| 113 | `MCODE_BANK` | The masked phase's W image | no |
| 116-119 | `FSTEP0-3` | `FSTEP_TABLE` | no |
| 120-122 | `MT_TBANK`, `MT_RLO`, `MT_RHI` | The math's tables, `RECIP_TABLE` | no |

Aux bank 0: `$0C00-$15FF` the openings' low bytes (2,560); `$A000-$BFFF`
the record staging (8 KB).

## 7. The frame

### 7.1 `nr_frame`

`nr_frame` runs, in upstream's order:

1. A `STATUS` left by the frame before (the release build's cut,
   `ST_RECORDS`) is cleared, and `W_FSW` with it (the cut frame counts
   as not shown). `nr_fillstamps`: `R_FillStamps` (`r_list65.s:153-194`).
   `W_FSC` + 1.
   `W_FSP` = `W_FSC` - 1 when the view of the frame before was shown
   (`W_FSW`) with the same first row and row after it (`W_TOPR`,
   `W_BOTR`), else `W_FSC`. Every 128 frames every span stamp becomes
   `W_FSC` ^ `$80` (`fsFill`). The fill bytes' plane colours are reset.
2. `nr_setup`: `setupFrame` (`r_frame65.s:216-286`). The view from the
   render inputs; `LT_BASE`, `LT_FIXED`; `VIEWSIN`, `VIEWCOS` =
   `finesineapprox` and `finecosineapprox` of viewangle >> 19;
   `validcount` + 1.
3. `nr_clear`: `SOLIDCOL` 0; `CEILCLIP` = viewtop + 1, `FLOORCLIP` =
   viewbottom + 1; no drawseg, no opening, no listed sector.
4. `nw_clip`: the weapon's clip pass into `FLOORCLIP` and `FRVIS`
   (`RENDER-MASKED.md`).
5. `nr_wskip`: `weaponClipSame`'s bookkeeping (`r_frame65.s:892-943`).
   `FR_SKIP` = `W_FSW` when there is a weapon and no flash, no automap
   overlay, the weapon is not the shadow one, and `FRVIS` equals
   `WPREV` (the frame before's); else 0. `WCLIP` = `FLOORCLIP` at the
   first frame that skips. `W_WSK` = `FR_SKIP`. `WPREV` becomes `FRVIS`.
6. `rec_start`: an empty batch and staging, `UPOFS` 0, no extra page.
7. `nr_bsp(numnodes - 1)`: the walk, which calls `nr_storewall` for each
   wall range.
8. `rec_flush`: the last batch into the staging.

All routines are near (`JSR`/`RTS`). They run with card bank 1 selected,
`RAMRD`, `RAMWRT`, `ALTZP` off and `$C073` 0 between windows, decimal
mode off, interrupts enabled. Arguments are in registers and zero page.

### 7.2 The BSP walk (`rbsp.s`)

`nr_bsp` fetches each node whole (one `far_get` from `LVMAP`) into a node
frame of W and recurses into the front child. The back side is a tail
call that reuses the frame, as upstream's `brl`. More than 20 levels
stops the frame (`ST_DEPTH`); no E1 map comes near.

- **`nr_side`** (`viewSide`): bspNode's tests for dx or dy 0, else the two
  `shiftMul` products. Upstream first tries `c14Bounds`, a log-table test
  it claims exact (`r_bsp65.s:1237-1311`). The native code always takes
  the products. A check of `nr_side` against upstream's `viewSide`, on
  random views and dense edge cases near the log thresholds of all nine
  maps, found no difference in 4,994,932 cases.
- **`nr_checkbox`**: `R_CheckBBox` with `boxPre` (false before any corner
  angle), the corners' angles through the box-corner cache, `boxAngles`
  through `ax_vtox`.
- **A subsector**: its 4-byte record, its sector into the sector frame
  with `nr_planes` (plane colours as upstream, kept while the sector
  repeats: `CN_LSEC`), its sector stamped with `validcount` and listed
  for the masked phase (`nr_addsprites`). Its segs come into the bounce
  buffer five at a time.
- **The vertex angles** of a batch of segs: the walk puts their vertex
  numbers in the card, `far_vgather` reads their angles and stamps in one
  `LVMAP` window, the walk computes the missing ones (`pta16`), and
  `far_vput` writes those back in one window.
- **`clipwall`** clips each seg to the open columns (`SOLIDCOL`) and calls
  `nr_storewall` with A = start, X = stop (inclusive), `BS_SEG`, `SEGR`
  (the seg's 24 bytes), `FSEC`, `FPC`, `CPC` (plane colours: a `FLATCM`
  byte, `$FFFF` none, `$FFFE` sky) and `WBOT` (worldbottom), as upstream
  calls `R_StoreWallRange`.

### 7.3 Wall setup (`rwall.s`)

`nr_storewall` is `R_StoreWallRange` and its helpers: the drawseg, the
scales, the heights, the marks and textures, the texture edges, the seg
descriptor for the seg loop, then the silhouettes and the clips saved
for the sprites (`saveClip`: one `RAMWRT` window into the openings). It
fetches the side and the back sector into the W sector frame (a
`far_get` each) and sets the line's bit in `LNMAP`.

Upstream's shortcuts are reproduced: `qmulh`'s "+ 0 or 1" in scaleFast
and `FIXAL`; `FIXAL` taking `qmulh` for a high word of 0 or -1 and
`FixedMul3216` otherwise; scaleFast's 1.001 step and its bail-outs to
scaleSlow; distAny's 8-bit view fractions; the edges from the heights'
shared low word. The divides are `math.s`'s own: `rowMod`'s remainder by
`sdiv16`, scaleSlow's step by `udiv32`.

scaleSlow leaves `rw_scalestep` unchanged for a wall of one column
(`r_wall65.s:1975-1982`), and that wall's edges use the old step. So
`RW_STEP` is kept from wall to wall and from frame to frame, as upstream's
`rw_scalestep` is.

**The seg descriptor** is the native WPAGE: what `R_StoreWallRange` sets
for `R_RenderSegLoop`. Its hot part is overlay 2, its cold part the
spill. The edges keep upstream's forms: `TF` holds FRACUNIT - 1 more and
starts one step early, `BF` and `PH` FRACUNIT more, `PL` FRACUNIT - 1
more (`r_seg65.s:15-17`).

**Drawsegs** (`RENDB`, 32 bytes): seg (2), x1, x2 (1 each), scale1,
scale2, scalestep (4 each), silhouette (1), bsilheight, tsilheight (4
each), sprtopclip, sprbottomclip (2 each), maskedtexturecol (2). A clip
field holds the opening index minus x1, or `$7FFF`
(`screenheightarray`), `$7FFE` (`negonearray`); maskedtexturecol the
same or `$8000` (null). An index minus x1 lies in -160 to 2,560, so the
markers cannot be one. `DSX1`, `DSX2` and the count are in main.

**Openings** keep upstream's index space: 2,560 entries, `LASTOPEN` an
index. Low bytes in aux 0 `$0C00`; high bytes, needed only by masked
texture columns (clips are below 256), in `RENDB`'s `OPENHI`, written by
one `far_put` after the seg.

### 7.4 The seg loops (`rseg.s`, `segloops.s`)

`nr_segloop` is `R_RenderSegLoop`: the prologue, the choice of loop,
genColumn, the masked-only loop (`vMask`), texCol, the tiers, the fills.

**The 13 loops.** Upstream gives a loop of its own to the 13 kinds of
seg it draws most (`r_seg65.s:565-575`, `segvar.inc:27-247`). A kind is
TOP 1 | BOT 2 | MC 4 (the ceiling fill) | MF 8 (the floor fill), or ONE
16 (a one-sided wall) | the marks. `seggen.py` writes v02, v04, v05,
v06, v07, v08, v10, v12, v13, v14, v15, v20 and v28 from one template;
every other kind takes genColumn. The loops step the edges with
`STEP8E` (bytes 1-3: an edge keeps its byte 0, as upstream's). A closed
column (floor clip + 1 of 0) goes to genColumn, which steps with
`STEP32` on all 32 bits, so the seg continues with a different low byte,
as upstream's does.

**The scale is not stepped in the loops.** `far_fstep` (card) steps the
24-bit scale once for the seg's columns, in one `RAMRD` window that
switches `FSTEP` banks with `$C073` as needed. For each column it writes
`FSTEPLO`/`FSTEPHI`: `FSTEP_TABLE[scale]` below 1.0, else `fstepHigh`
(the entry of the scale / 256, rounded; 7 at 64.0). A column past 64.0
is flagged for `fsgeneral` in W (`RECIP_TABLE`). For a seg whose light
varies it also writes each column's light distance d =
min(scale >> 13, 23) into `DLW`.

**texCol.** The texture u is exact every 8 columns (`tcExact`: the
tangent through `ax_tan3`/`ax_tan4`, `xtoviewangle`) and linear between,
as upstream (`r_seg65.s:1807-1818`).

**The tiers.** A tier record (`K_TEX`) takes the slot of
`texturetranslation[tex]`'s column; a texture with no slots stops the
frame (`ST_TEXTURE`), which the converter rules out. The C16
constant-row products become one product, frac = (row - 85) × fstep +
texturemid >> 7, the low 16 bits (two `mul8`), exact. Upstream's C17
and C26 self-modifications are not needed: a loop calls its one tier,
and the record's page is `PGT[W_LV - d]`.

**The fills.** `ceilFill`, `floorFill`, `PLANEFILL`: a `K_FILL` record
of the plane colour, its first-row parity bytes swapped for an odd first
row (`r_seg65.s:1668-1685`), and the fill spans reused as upstream.

**The sky** (`rsky.s` `sky_col`, from ceilFill for a sky ceiling and from
genColumn): a `K_TEX` of the sky's texel column ((viewangle >> 16) +
xtoviewangle[x]) >> 6, its slot from `SKYBANK:SKYHI:SKYLO` + 128 c, one
texel a row (step 512), texturemid 100 << 16, the page of the fixed
colormap or of colormap A at full light. Upstream's `skyFlat` path (no
sky patch) is not ported: `skypatch` is never null when a sky column is
drawn (`r_seg65.s:1403-1406`, `r_bsp65.s:743-746`).

**Patchless columns** (`tier_flat`): when bit 7 of `TXBANK` says the
texture has some, `TXFLAT` decides per column. A column with no patch
becomes a `K_FILL` of the texture's colour after `R_DrawColumnFlat`'s span
cut. Upstream runs `R_DrawColumnFlat` on the C code's direct page, so
it leaves WPAGE's `DC_ROW` alone; the native code does the same, because
loops 6 and 14 read the ceiling clip from it after the tier. E1 has no
patchless column.

**Masked columns** go to `MASKLO`/`MASKHI` by column and into the
openings after the seg.

### 7.5 Records

The producers write upstream's record with a **column byte after the
kind** into the 256-byte batch buffer in W:

| Kind | Native size | Fields |
| --- | ---: | --- |
| `K_TEX` | 12 | rows, `R_TF`, `R_TI`, `R_SF`, `R_SI` (the position one row before the first, and the step, both halved), `R_CMP` (upstream's page byte), `R_SRC` (the native slot) |
| `K_FILL` | 6 | rows, `R_B1`, `R_B2` (the first row's parity bytes) |
| `K_TEXC` | 8 | a texture record continuing the one before (masked walls) |
| `K_FUZZ` | 5 | a shadow (sprites) |

`rec_room` reserves room for a record, keeps the page model and the
column counts (`RENDER-MASKED.md`), and flushes the batch when it is
full. `rec_flush` copies the batch into the staging in one `RAMWRT`
window an area: aux 0 `$A000-$BFFF`, then the spill banks 51-54
(`$0200-$BFFF` each), 202,752 bytes in all. `STG_BANK` and `STG_PTR`
say where the next byte goes.

The native front end never draws early. Upstream draws all its lists
when it runs out of list pages (`flush`, `r_list65.s:272-323`); the
native renderer stages the whole frame, and the bucket pass sorts it by
column for the replay.

When the staging is full, the release build (the disk's) drops the
batch that does not fit and every later one (the sticky `RECDROP`),
sets `STATUS` = `ST_RECORDS` and completes the frame with the records
staged (`RENDER-MASKED.md` 10); the `stops` build stops the frame there
(`STATUS` = `ST_RECORDS`, `BRK`). The largest staging measured in demo3
is 17,003 bytes, under a tenth of the capacity.

## 8. Far access per frame

Batching rules the code follows: fetch a record whole; keep a window
open across a loop over one bank; never interleave two banks in one loop
when the work can be split (a subsector's segs, then their vertices).

| Work | Window |
| --- | --- |
| A node | one `far_get` from `LVMAP` into its node frame (32 bytes) |
| A subsector | `far_get` of its record (4), then its segs from `LVSEG`, 5 at a time |
| Its vertex angles | one `LVMAP` read window for all, one write window for new ones |
| A box's corner angles | one read window, one write window for a miss (frames at a known map unit) |
| A wall | a `far_get` of its side and one of its back sector |
| The wall's scale | the math's tables-bank window for the sines; one `RECIP_TABLE` window |
| Its `FSTEP` | one window for all the seg's columns |
| Its drawseg, `OPENHI` | `far_put` into `RENDB` |
| Its clips (`saveClip`) | one `RAMWRT` window into aux 0's openings |
| Exact texture u | one aux-card window (`finetangent`) |
| Records | one `RAMWRT` window per batch of 256 bytes |
| `LNMAP` | none: it is in main |

## 9. Rules of our own, and the stops

A column seen from behind happens in a legal view: when a wall is seen
at a grazing angle, the centre angle of its first or last column can lie
just past the seg's end. Upstream then reads outside its tables:
`R_ScaleFromGlobalAngle`'s `sineLow` reads with a negative index into
its own code in bank 3 (`r_iigs65.s:535-542`), and `tcExact`'s long read
passes `finetangent` part 4 into live data (`r_seg65.s:2017-2077`). The
native code cannot reproduce either. It takes a defined value and sets a
bit in the frame block's `RULES`:

| Rule | Where | The value |
| --- | --- | --- |
| `RULE_SINE` (1) | `rwall.s` `rsga`: `angleb` ≥ ANG180 | The scale 256, vanilla DOOM's result for a negative sine |
| `RULE_TANGENT` (2) | `rseg.s` `tcexact`: a texture angle ≥ 4096 | The table's end: 4095 below 6144, 0 from 6144 |

The other sine's angle, ANG90 + `xtoviewangle[x]`, lies in
`$2000-$6000` for every column, so it needs no rule (`rtables.py`
checks the table). On such a frame the native game differs from
upstream; this is a known difference, accepted by the owner. No captured
frame reached either rule.

**The stops** (`STATUS` and `BRK`, every build): `ST_DEPTH` (1, the node
frames are full), `ST_TEXTURE` (5, a texture with no slots); and in the
`stops` build `ST_RECORDS` (2, the staging is full), which the release
build cuts instead (the frame goes on with `STATUS` 2, which the next
frame's `nr_frame` clears, with `W_FSW`: the cut frame counts as not
shown). The masked
phase adds its own (`RENDER-MASKED.md`). In the game a `BRK` lands in
the platform's crash stop ([`PLAY.md`](PLAY.md)).

## 10. Upstream's caches and shortcuts

| Upstream | Native | Why |
| --- | --- | --- |
| Vertex-angle cache | Kept, native form (3.1) | Speed only |
| Box corners' angles | Cached (3.1) | Speed only: the same values |
| `CN_LSEC`: plane colours kept while the sector repeats | Kept | Saves a sector fetch |
| `boxPre` | Kept | Upstream's answer by construction; saves `pointAngle` calls |
| `c14Bounds` | Dropped: always the two products | Same side in every case checked; the products cost less than two `LOGTAB` windows |
| `skyFlat` | Dropped | Dead code |
| `CORE_LN36`, `CORE_SEC58`, `CORE_NODEADR` | Dropped | Index arithmetic |
| `COLDIR`, column tables, `tierMake` | Replaced by slots (3.2) | No per-column table read |
| C16/C19 constant-row products | Replaced | One exact product |
| C17 continuation patch | Static | Each loop knows its one tier |
| C26 light lookup base | `PGT[W_LV - d]` | The same byte |
| `SQL`/`SQH`, `iigs_mulT` | `math.s` | Exact products |
| `STEP8E`, `TC_N` = 8, `fstepHigh`'s rounding, `qmulh`'s "+ 0 or 1" | Reproduced | Exactness |
| View-size patches (`SEGPATCH`, `ssPatch`) | None | Full view only |
| `R_WallFrame`'s pointer banks | Dropped | No long pointers |

## 11. Timing

On the owner's card (F1.2.2, 2026-10-03, the benchmark's demo3), the
front end takes 18.1 ms a frame on average: the `3D` row of the
BENCHMARK page, which counts the W image load and `nr_frame`
([`SPEED.md`](SPEED.md), [`PLAY.md`](PLAY.md)). The a2vm model gives
18.0 ms for the same row.

## Appendix: upstream to native, by routine

| Upstream | Lines | Native |
| --- | --- | --- |
| `R_FillStamps`, `fsFill` | `r_list65.s:153-194` | `nr_fillstamps` |
| `R_RenderPlayerView` to `drawMasked` | `r_frame65.s:117-178` | `nr_frame` |
| `setupFrame` | `r_frame65.s:216-286` | `nr_setup` |
| the clears | `r_frame65.s:125-169` | `nr_clear` |
| `weaponClipSame` | `r_frame65.s:892-943` | `nr_wskip` |
| `R_RenderBSPNode`, `bspNode` | `r_bsp65.s:103-241` | `nr_bsp` |
| `viewSide`, `shiftMul` | `r_bsp65.s:244-289`; `r_iigs65.s:630-660` | `nr_side` |
| `checkBox`, `boxPre`, the corners, `boxAngles` | `r_bsp65.s:304-564` | `nr_checkbox` |
| `scan0`, `scan1` | `r_bsp65.s:570-621` | `nr_scan0`, `nr_scan1` |
| `bspSub`, `c21Floor`, `flatColor` | `r_bsp65.s:627-763`; `r_wall65.s:1446-1463` | `nr_planes`, the subsector code |
| `segLoop`, `clipWall`, `vtxAngle`, `pointAngle` | `r_bsp65.s:771-956`; `r_iigs65.s:45-` | the seg code, `clipwall`; `pta16` |
| `R_WallLight` | `r_bsp65.s:1036-1058` | `nr_walllight` |
| `R_StoreWallRange` and helpers | `r_wall65.s:340-2081`; `r_iigs65.s:448-` | `nr_storewall` |
| `R_RenderSegLoop`, `segDone` | `r_seg65.s:340-575` | `nr_segloop` |
| the loops of `segvar.inc` | `segvar.inc:27-247` | `seggen.py` |
| `genLoop`, `genColumn`, `vMask`, `clip8`, `solidColumn` | `r_seg65.s:580-599`, `:1161-1395` | `rseg.s` |
| tiers, `tierDraw`, `texRec` | `r_seg65.s:1495-1650` | `rseg.s` |
| `ceilFill`, `floorFill`, `PLANEFILL`, `fillBytes` | `r_seg65.s:1653-1805` | `rseg.s` |
| `texCol`, `tcExact`, `fstepHigh`, `fsGeneral` | `r_seg65.s:1903-2077`, `:2591-2681` | `rseg.s`, `far_fstep` |
| `skyColumn`, `ceilSky`, `tierFlat` | `r_seg65.s:1403-1474`, `:1525-1543`, `:1696-1706` | `rsky.s` |
| `recAlloc`, `newPage` | `r_list65.s:256-323` | `rec_room` |
