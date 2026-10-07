# The native renderer: the masked phase and the whole frame

This document describes the renderer after the front end: the weapon's
clip pass, the sprites, the masked walls, the weapon, the bucket pass
and the replay. [`RENDER.md`](RENDER.md) describes the front end (the
walk, walls, seg loops, records) and the principles, tables and memory
both share. As there, the output equals upstream's bit for bit, and
citations like `r_thing65.s:155` are upstream's files.

## 1. The frame

| # | Phase | Code | W holds | Upstream |
| --: | --- | --- | --- | --- |
| 1 | Front end's image load | the kernel (`far_wloadt`'s pages) | the front end | |
| 2 | Plane stamps, setup, clears | `nr_frame` | front end | `R_FillStamps`, `r_frame65.s:117-169` |
| 3 | The weapon's clip pass | `nw_clip` (`wclip.s`) | front end | `weaponClip` |
| 4 | Weapon skip, the walk (listing sectors), wall setup, seg loops, last batch | `nr_frame` | front end | to `drawMasked` |
| 5 | Masked image load | the kernel (`far_mload`'s pages: the code and `TXMP`) | masked | |
| 6 | The column counts, the drawseg copy, `SPRBOUND` | `nm_masked` | masked | (`dsaInit`) |
| 7 | Projection of the listed sectors' things | `nm_project` | masked | `R_AddSprites` |
| 8 | Sort | `nm_sort` | masked | `sortSprites`, `sortSkip` |
| 9 | Sprites back to front, with the masked ranges behind them | `nm_drawsprite`, `nm_vis`, `nm_mwall` | masked | `drawMasked`'s first loop |
| 10 | The drawsegs' remaining masked columns, last drawseg first | `nm_mwall` | masked | its second loop |
| 11 | The weapon and the flash | `nm_psp` | masked | `playerSkip` |
| 12 | Last batch; the bucket pass's main code into main memory | `mrec_flush`, `nm_bkload` | masked | |
| 13 | The automap overlay, when on | `OVLW` ([`SCREENS.md`](SCREENS.md)) | `OVLW` | `AM_Drawer` |
| 14 | Bucket pass, then each batch's replay | `nb_frame`, `nat_replay` | records and the texel stage | `R_DrawLists` |

The game's kernel runs these steps ([`PLAY.md`](PLAY.md)): the tic image
uses W before the render, so both images are loaded every frame.

| File | What it is |
| --- | --- |
| `src/native/wclip.s` | `nw_clip`: the weapon's clip pass, in the front end's image |
| `src/native/wpsp.s` | The weapon code both images share (`ps_vis`, `wp_find`, `wp_start`, `wp_list`), assembled twice (`-D MPSP` for the masked image) |
| `src/native/mmain.s` | `nm_masked`: the phase's driver and `drawMasked`'s loops |
| `src/native/mproj.s` | `nm_project`, `nm_sort` |
| `src/native/msprite.s` | `nm_drawsprite` (`R_DrawSprite`), `nm_ptseg` (`R_PointOnSegSide`) |
| `src/native/mvis.s` | `nm_vis` (`R_DrawVisSprite`), the magnified runs, the shadows, `YHTAB`, `FSCUT`, `CVSET` |
| `src/native/mwall.s` | `nm_mwall` (`R_RenderMaskedSegRange`) |
| `src/native/mpsp.s` | `nm_psp`: the weapon's draw and the flash |
| `src/native/mfar.s` | Card: `far_mload`, `far_dscopy`, `far_posts`, `far_postsc` |
| `src/native/rrec.s` | Assembled again with `-D MREC`: `mrec_room`, `mrec_flush` |
| `src/native/bucket.s` | `nm_bkload`, `nb_frame`, `nb_bucket`, `nb_scatter`, `nb_batch` |
| `src/native/replay.s` | `nat_replay` ([`src/native/README.md`](../src/native/README.md)) |
| `src/native/rdriver.s` | `drv_fframe` (`-D MASKED -D FRAME8`), the frame image's driver that `OVLW` links against |

## 2. Sprite data

### 2.1 Principles

On top of `RENDER.md`'s:

1. **Texels stay where the replay can read them as upstream does.** A
   sprite record's texel source is post + 3, and the replay reads up to
   127 bytes past it. So the patch store keeps each patch lump's bytes
   whole and in order, followed by the 128 bytes that follow the lump in
   upstream's memory.
2. **What depends on the frame is state, not level data**: `FZPOS`, the
   weapon skip, `WTMP`.

### 2.2 The patch store

The level store's patch banks (32-47 and 64, [`LEVELS.md`](LEVELS.md))
hold every patch lump a map stores, shared by the maps. The level load
applies a map's own tail bytes where they differ from the shared ones.
Each lump is stored as:

- upstream's `patch_t` bytes verbatim: width, height, leftoffset,
  topoffset, `columnofs[width]`, the posts (topdelta, length, pad,
  texels, pad), each column ending with `$FF`;
- then its tail, the 128 bytes after the lump. A record reads up to 127
  texels past its post and up to 124 bytes past its lump's end
  (measured over 725 captured frames), so the tail is needed whole.

Index 0 is upstream's placeholder, a patch of width 0. A sprite whose
lump is not resident is rejected as "too small" where upstream rejects it
(`r_thing65.s:436-443`).

A lump never crosses a bank, so a post's address is the lump's bank and
the low word of patch + `columnofs[c]`, as upstream assumes
(`r_seg65.s:2906-2917`). A record's `R_SRC` is post + 3 in the store; a
`K_TEXC`'s `R_TCSRC` is its low word.

### 2.3 Tables

| Table | Where | Content |
| --- | --- | --- |
| `SFIRST` | masked image constants | Index of each sprite's frame 0 in `SPRFR` (55 sprites) |
| `SPRFR` | `SPRT` (48) | 24 bytes a sprite frame: rotate, flipmask, the store index of each of the 8 rotations (2 each), flags (bit 0: not a real frame) |
| `PHDR` | `SPRT` `$5600` | 16 bytes a patch: width, leftoffset, topoffset (2 each), the store bank (1) and address (2), upstream's lump number (2) |
| Scale records | `SPRT` `$0200` | 16 bytes a distance d = tz >> 16, 0-1,280: xscale, yscale, iscale (4 each), `FQ`'s q (2) and r (1) |
| `SPRBOUND` | `SPRT` `$5400` | 4 × 55 bytes: E and E / 2 + 2 of each sprite |
| `TXMP` | masked image, W `$B200` | The store index of each texture's first patch, for masked walls (`$FFFF`: not in the store) |
| `CMOP` | masked image | 85 bytes: the record page `$46 + CMO[i] / 256` of each sprite light (`r_bsp65.s:1009-1020`) |
| `SMAP`, `PGT` | masked image | As the front end's |
| `WPIDX`, profiles | `WPRO` (49) | The weapons' profiles (section 6) |

`rtables.py` takes the scale records from the reference's RAM
(`$22:0000` and up) and checks them: xscale = `PROJECTION / d`, yscale =
`PROJECTIONY × FRACUNIT / d`, iscale = `math.s`'s `recip` of xscale, `FQ`
= (16 d / 5, 16 d % 5), for d = 4-1,280. The frame index is `frame &
$7FFF`; bit 15 is `FF_FULLBRIGHT`.

**`SPRBOUND`** decides the early "off the side" rejection
(`r_thing65.s:278-317`). Upstream makes it at the first frame after a
level set's load, from the lumps resident then. The game's disk build
computes it once from all of DOOM1.WAD's patches (`playdisk.py`
`sprbound()`), so a sprite a level set does not hold is rejected less
early than upstream's. This is a named difference ([`PLAY.md`](PLAY.md));
it never drops a sprite.

### 2.4 Things

The projection reads each thing through its render part, which the game
logic keeps ([`GAME.md`](GAME.md)):

| Record | Bytes | Fields | Where |
| --- | ---: | --- | --- |
| `RTHING`, by the mobj's slot | 24 | x, y, z (4 each), the angle's high word (2), sprite (1), frame (2, bit 15 `FF_FULLBRIGHT`), flags (1, bit 0 `MF_SHADOW`), snext (2: a slot, `$FFFF` none) | `RTH` (50), `$0200` + 24 × slot, 2,026 slots |
| Sector's thing list head | 2 | a slot, `$FFFF` none | the sector record's offset 13 (`LVMAP`) |

### 2.5 The vissprite

Upstream's `vissprite_t` is 42 bytes with 4-byte pointers. The native
one is 40 bytes, 80 of them in W from `$A400` (`MAXVISSPRITES`):

| Offset | Bytes | Field |
| ---: | ---: | --- |
| 0 | 1 | x1 (0-159) |
| 1 | 1 | x2 |
| 2 | 4 | scale |
| 6 | 4 | gz |
| 10 | 2 | gzt's high word: gz >> 16 + the patch's topoffset (the only word `R_DrawSprite` reads) |
| 12 | 4 | tx: the thing's x (upstream's `gx` is the thing's pointer) |
| 16 | 4 | ty: the thing's y |
| 20 | 4 | startfrac |
| 24 | 4 | xiscale |
| 28 | 4 | texturemid |
| 32 | 2 | fracstep |
| 34 | 2 | the patch store index |
| 36 | 1 | the colormap's record page; 0: a shadow |
| 37 | 2 | the thing's slot |

The colormap maps to one page: `fullcolormap + CMO[i]`, the fixed
colormap, or `fullcolormap` for `FF_FULLBRIGHT`; the page is `$46` + its
offset / 256, as `R_DrawVisSprite` makes `W_CMP` (`r_seg65.s:2706-2712`).

### 2.6 `YHTAB`

`YHTAB[t]` = (E - 1) >> 16 of texel row t, E = sprtopscreen + spryscale
× t, filled lazily up to the rows a post needs (`r_seg65.s:69-72`,
`:2771-2791`). Natively two planes of 512 bytes, `YHL` `$BA00` and `YHH`
`$BC00`, rows 0-511. The running E - 1 of the last row filled is kept in
zero page (`V_E`), so upstream's word before row 0 (`YHTABM`) is not
needed. At unit scale the row is `V_YH0` + t and no table is used, as
for the weapon (its scale is 1.0).

## 3. Memory in the masked phase

### 3.1 W

The front end's image is dead after the walk, but for what the masked
load leaves in place:

| Range | Bytes | Content |
| --- | ---: | --- |
| `$6000-$6592` | 1,427 | `MATHW` and `AUXW`, shared with the front end's image (kept) |
| `$6600-$679F` | 320 | `MCNTLO`, `MCNTHI`: each column's bytes of records (section 7.1) |
| `$6800-$9BFF` | 13,312 | The masked code `MASKW` (9,125 B in the current link, to `$8BA4`; with the bucket pass's `nb_bucket` and its recount) and its constants, then the load images of `BKFAR` and `BKFAR2` |
| `$9C00-$A3FF` | 2,048 | `DSW`: up to 64 drawsegs that clip sprites or hold masked columns, 32 bytes each. Others are fetched from `RENDB` into `DSB` when used |
| `$A400-$B07F` | 3,200 | The vissprites, 80 × 40 bytes |
| `$B080-$B15B` | 220 | `SPRBOUND` for the frame |
| `$B160-$B1FF` | 160 | Fetch buffers: the projection's sprite frame and listed sector, then a patch header `PHB`, a seg `SEGB`, a side `SIDEB`, front and back sectors `MSEC_F`, `MSEC_B`, a drawseg `DSB` |
| `$B200-$B3FF` | 512 | `TXMP` (per level) |
| `$B400-$B8FF` | 1,280 | `TXBANK` ... `TXHT` (kept from the front end) |
| `$B900-$B9FF` | 256 | The record batch buffer (kept) |
| `$BA00-$BDFF` | 1,024 | The listed sectors during the projection (`SECLIST`), then `YHTAB`; during the weapon's draw its profile buffers |
| `$BE02-$BEA1` | 160 | `CLIPBUF`: a clip run from the openings |
| `$BEA2-$BFE1` | 320 | `MTCLO`, `MTCHI`: a masked range's texture columns |

A masked range needs both of its drawseg's clip runs for every column.
The second, `mceilingclip` (`sprtopclip`), goes to main `SOLIDCOL`
`$0E00` (`MCCLIP`), dead once the walk ends.

The masked load copies the code pages from `$6800` to the end of the
area's image and `TXMP`'s two pages, not `$B400-$BFFF`.

### 3.2 Main memory, aux 0, the card

| Where | Content | Live |
| --- | --- | --- |
| Main `$1680-$171F` | `UPOFS`: upstream's page offset of each column's list | the render; the bucket pass writes `COLLO` over it after |
| Main `$1720-$176F` | `FRORD`: the sort's order | the masked phase |
| Main `$18A0`, `$18B0` | `WPREV`, `FRVIS`: 12 bytes each (section 6.1) | persistent |
| Main `$18E0-$197F` | `WTMP`: `wclipSprite`'s floor clip | persistent |
| Main `$0E00-$0E9F` | `MCCLIP` | a masked range |
| Aux 0 `$1600-$16FF` | `SPRSEC`: the sectors the walk listed, one `RAMWRT` window an entry | the frame |
| Card bank 1 `$DE98-$DFE5` | `MFAR` (334 B): `far_mload`, `far_dscopy`, `far_posts` with a buffer of 16 posts, `far_postsc` | |

`WTMP` is persistent because `wclipSprite` writes only the columns x1
to min(x2 + 1, 159), and a later sprite, maybe in a later frame, can
read a column past that (`r_frame65.s:966-990`; `r_seg65.s:2923-2943`).

Clip runs and masked columns go through `far_get` with `FA_BANK` 0,
which reads aux 0.

### 3.3 Zero page and stack

The masked phase owns overlay 1 (`$18-$41`) and overlay 2 (`$48-$AF`),
free once the walk ends. The projection and the draw phase have their
own allocations over the same bytes (`rlayout.py` `OVM1`, `OVM2`, then
`OVD1` and `OVD2`); the weapon's (`OVW`) starts inside overlay 2 after
the masked range's state. The math block `$B0-$D7` and the IRQ's
`$D8-$FF` are as in the front end. The stack stays within the render
budget of 112 bytes plus 24 for an interrupt; the deepest measured frame
used 83.

## 4. Projection and sort

### 4.1 Deferred projection

The walk reads nothing the projection makes: the projection's
direct-page bytes are ones the walk leaves alone, and it writes only the
vissprites, their count and its own scratch (`r_thing65.s:46-65`). So
the native walk does not project. Where upstream calls `R_AddSprites`
(`r_bsp65.s:730-742`), `nr_addsprites` appends the sector to `SPRSEC` (at
most 254 sectors, each once a frame by its `validcount` stamp). The
masked phase then projects the listed sectors' things in that order.
The vissprites, their order and the `MAXVISSPRITES` cut are upstream's,
and the projection's code lives in the masked image, not in the front
end's tight W.

### 4.2 `nm_project`

For each listed sector, its things through the thing list (`RTHING`
fetched whole), then for a thing in front of the view and inside the
bounds: its scale record, its sprite frame (`SPRFR`), its patch header
(`PHDR`), each with one `far_get` from `SPRT`. `pta16` (with
`tantoangle` in the aux card) gives the rotation of a rotated frame.

The arithmetic is upstream's, bit for bit: tz = TXH c + TYH s + G and
tx = TXH s - TYH c + G, each product of a signed 16-bit high word and the
view's sine or cosine, modulo 2^32. A thing at whole map units takes
the frame's G parts, exact (`R_WallFrame`'s). Any other thing takes
upstream's `qmulh` products, "+ 0 or 1" in the last bit (`gGZ`, `gGX`).
xl is by `qmulh` and the signed product of tx's high word, or `FixedMul`
when the low word of xl or xr would be 0 or when xscale is 1.0 or more.

A frame flagged not a real frame (upstream reads past its sprite's
frames) stops the frame (`ST_SPRFRAME`); no map thing takes one.

### 4.3 `nm_sort`

`R_SortVisSprites`: `FRORD` = the vissprite indexes by scale, the
largest first, equal scales in their order (an insertion sort, as the C
code's). The draw takes `FRORD` from its end, so sprites go back to
front. `sortSkip`: a frame that skips the weapon rows (`FR_SKIP`) but has
a shadow among its vissprites does not skip (`FR_SKIP` = 0, `W_WSK` =
0).

## 5. Sprites and masked walls

### 5.1 `nm_masked`

1. Copies the front end's column counts (`FCNT`) into `MCNT`.
2. Copies the drawsegs whose `DSX1` is not 255 (they clip sprites or
   hold masked columns), the first 64 in index order, into `DSW` (one
   `RAMRD` window, `far_dscopy`), and `SPRBOUND` into W.
3. Projects, sorts.
4. Draws each sprite back to front (`nm_drawsprite`).
5. Draws the drawsegs' masked columns not drawn yet, the last drawseg
   first (`nm_mwall`).
6. Draws the weapon and the flash (`nm_psp`), then flushes the last batch.

### 5.2 `nm_drawsprite` (`R_DrawSprite`)

The clips of the sprite's columns start at the view's (viewbottom + 1,
viewtop + 1: the arrays hold the clips + 1). The drawsegs are scanned
from the last to the first, those whose columns meet the sprite's:

- **Behind the sprite** (both scales less than its scale, or one of them
  and the sprite on the front side of the seg: `nm_ptseg`, the seg's
  vertices fetched from `LVSEG`), a drawseg with masked columns draws
  them now, for the sprite's columns (`R_RenderMaskedSegRange(ds, r1,
  r2)`, `r_sprite65.s:1598-1618`). The "drawn" marks persist for the
  frame, so the later drawseg loop draws only the columns left.
- **In front**, its silhouettes clip the columns not clipped yet. Its
  clip runs come from the openings into `CLIPBUF` (one window; none for
  the markers, none when no column of the run is still unclipped).

"Not clipped yet" compares with the view bottom + 1 and top + 1,
upstream's sentinel, not the C code's -2 (`r_sprite65.s:1637-1642`).
Then `dsVisible`: an open column in x1 to x2 + 1, or the column x2 + 2
when the texture can reach it. Then `nm_vis` with the clips.

### 5.3 `nm_vis` (`R_DrawVisSprite`)

The setup: the patch, sprtopscreen = CENTERY << 16 - FixedMul(texturemid,
spryscale), texturemid >> 7, the step, K = texturemid >> 7 - 85 ×
fracstep. Then one of:

- **A shadow** (page 0): `K_FUZZ` records (`visColF`), with the fuzz
  position `FZPOS`. `FZPOS` carries from shadow to shadow and from frame
  to frame (`r_sprite65.s:1727-1728`). A shadow sets its column's
  covered range to none for the frame (255, 254), which also flags the
  column for the bucket pass's fuzz marks.
- **A magnified sprite** (|xiscale| < 0.75, not unit scale): a post is
  recorded once for the run of columns that show the same texture
  column with the same clips (`vrCol`).
- **The others**: each column's posts (`far_posts`: one window for up to
  16 posts, `far_postsc` for more) as `K_TEX` records.

In a frame that skips the weapon rows, the floor clip becomes
`WTMP` = min(`WCLIP`, the clip) first (`wclipSprite`). The columns go on
while the texture column (frac >> 16) stays inside the patch, not to x2,
so a sprite can draw a column past x2 (`r_seg65.s:2923-2943`).

Every opaque post applies `CVSET` (its record becomes the column's
covered range when it has more rows than the range before) and `FSCUT`
(the fill spans end at its rows), as upstream's.

### 5.4 `nm_mwall` (`R_RenderMaskedSegRange`)

For a drawseg and its columns x1 to x2:

- `RW_STEP` = its scalestep (kept for the next frame's walls, as
  upstream's `rw_scalestep`); spryscale = scale1 + (x1 - ds->x1) ×
  rw_scalestep.
- texturemid: with `ML_DONTPEGBOTTOM` the higher floor + the texture's
  height, else the lower ceiling, - viewz, + rowoffset << 16.
- The light (`R_WallLight`, a fixed colormap's page). The page of the
  records is `PGT[startmap + 24 - d]`, d = min(23, spryscale >> 13):
  one page for the range when d is the same at both ends of the
  drawseg, else each column's.
- The patch: `TXMP` of `texturetranslation[midtexture]`. `$FFFF` stops
  the frame (`ST_TEXTURE`).
- P = texturemid × spryscale and its step B = texturemid ×
  rw_scalestep, bits 0-47 of the signed products (`smul48`).
- Its masked texture columns (the openings' low and high bytes) into
  `MTCLO`/`MTCHI`, `mfloorclip` into `CLIPBUF`, `mceilingclip` into
  `MCCLIP`.

Each column not drawn yet (texture column `$7FFF`: drawn) is marked
drawn. When it has rows, its posts become records: yl = max(H(topdelta),
the first row), the row after the last = min(H(topdelta + length), the
clip), with H(b) = (sprtopscreen + `$FFFF` + spryscale × b) >> 16. The
step is `FSTEP_TABLE[spryscale]` below 1.0, else FixedReciprocal >> 7.
A post past texture row 255 stops the frame (`ST_TALL`); no texture of
the game has one. After the range the marks go back into the openings.

**`K_TEXC` or `K_TEX`.** Upstream makes a masked post a `K_TEXC` (a
continuation of the column's last record) only when it fits the page of
the column's list, else a `K_TEX` with a new page (`r_frame65.s:1526-1552`).
`nm_mwall` makes a `K_TEXC` exactly when the post before in this column
made the column's last record and the page model says it fits
(section 7.1).

## 6. The weapon

### 6.1 The weapon's vissprite

`FRVIS` (`$18B0`) and `WPREV` (`$18A0`) are 12 bytes each: the patch
store index (2; `$FFFF` in `WPREV`: none), texturemid (4), x1 (1), x2 (2,
stored unclamped before the off-screen test, as `pspSprite` does), the
high word of startfrac (2), the record page (1, 0: the shadow weapon).
`pspSprite` sets only these and constants (scale 1.0, fracstep 512,
xiscale 2.0, the low word of startfrac 0; `r_frame65.s:739-840`); the
other upstream fields of `FR_VIS` are never written. So `weaponClipSame`'s
compare of 42 bytes equals a compare of these 12. `FRVIS` is persistent:
an absent or off-screen weapon writes some fields or none, and the
compare reads them all.

`ps_vis` (`wpsp.s`) makes it from the render inputs: the sprite frame
`SFIRST[sprite] + (frame & $7FFF)` and its rotation 0's patch; x1 = 80 +
(sx - 160 - leftoffset) / 2 and x2 = 79 + (the same + width) / 2
(arithmetic halves); texturemid = 100 << 16 - sy + topoffset << 16; x1
and x2 clipped to the view; startfrac's high word 2 (x1' - x1); the page
(the shadow weapon's 0, the fixed colormap's, full bright, else
`CMOP[SMAP[(light >> 4) + LT_BASE] - 23]`). sy is 32 bits, so the
weapon's bob reaches texturemid's fraction.

### 6.2 The profiles

Upstream draws the weapon from a profile of its patch when it can make
one (`wpBuild`, `wbMake`: `r_sprite65.s:884-1178`) and caches profiles
in arenas. Natively the converter makes every weapon lump's profile by
`wbMake`'s rules, or records that none can be made: width 1-320; per
column the posts of non-zero length with a = topdelta + 1, b = a +
length at most 254, each a at least the b of the post before (touching
posts form a run), at most 14 posts a column; the whole profile within
upstream's empty arena of 5,120 bytes. A lump without a profile takes
`R_DrawVisSprite`, as upstream's `WP_NONE`.

`WPRO` holds `WPIDX` (2 bytes a patch store index: the profile's
address, `$FFFF` none), then each profile in upstream's layout: width,
the minimum a, the columns of each parity and their tables, then each
column's posts from the lowest up, 5 bytes each (a + 1, b + 1, the a of
its run, the texels' offset in the patch), then a 0.

### 6.3 The clip pass (`nw_clip`, front end)

`weaponClip`, before the walk: `ps_vis` of psprite 0 with the view's
clips. Unless it has no state, is off the side or is the shadow weapon,
`MM_WPOK` is set and the clip pass runs:

- from its profile (`wcProf`): in each column, the lowest post whose
  rows reach the view's last row gives its run's first row + 1 to
  `FLOORCLIP`;
- else, when the lump has no profile or `wpStart` refuses it,
  `R_DrawVisSprite`'s clip pass (`visPost` 30$): a run of touching posts
  reaching the view's last row makes the column's floor clip its first
  row + 1, when that is lower.

In a run of frames that skip the weapon rows with the same `FRVIS` and
view bottom, `WCLIP` already holds `FLOORCLIP` after the same clip pass,
so `wp_start` copies it and the pass is skipped.

### 6.4 The draw (`nm_psp`, masked)

`playerSkip`: in a frame that skips the weapon rows, `W_WSK` = 0 and the
weapon is drawn with mfloorclip = `WCLIP`; else `playerSprites`: the
weapon, then the flash (psprite 1). The weapon:

- when the clip pass made this frame's weapon (`MM_WPOK`) and the profile
  path is open, `wdDraw`: each column's posts that start above `V_HI`,
  **from the lowest up** (`r_sprite65.s:1303-1308`), rows `V_YH0` + a to
  min(`V_YH0` + b, `V_HI`), one texture position for all, a step of 1.0.
  This order is the reverse of `visPost`'s, and it is upstream's;
- otherwise `pspSprite` and `R_DrawVisSprite` (`nm_vis` on `FRVIS` with
  `pspSprite`'s constants), with the clips `WCLIP` or the view's bottom +
  1, and 0.

The weapon's records go through the page model, `FSCUT` and the covered
ranges like any other.

## 7. Records, the page model and covered ranges

### 7.1 The page model and the column counts

Staged records keep the front end's form: upstream's record with the
column byte after the kind (`K_TEX` 12 bytes, `K_TEXC` 8, `K_FILL` 6,
`K_FUZZ` 5). Every producer of both images appends through `rec_room`
(`mrec_room` in the masked image), which also:

- **models upstream's list pages.** `UPOFS[c]` (0-254) is the offset
  upstream's next record of column c would take in its page; `XPUSED`
  the extra pages taken (0-50). A record of upstream size s (the native
  size less 1) that fits (`UPOFS[c]` + s ≤ 254) adds s. Else, with an
  extra page left, `XPUSED` + 1 and `UPOFS[c]` = s (a `K_NEXT` ends the
  old page). Else upstream would flush: every `UPOFS` 0, `XPUSED` 0,
  `UPFLUSH` + 1, and the record takes offset 0 of its home page
  (`r_list65.s:256-323`). The model never draws early: the staging
  keeps every record.
- **counts each column's bytes in W** (the native size less the column
  byte) in `FCNTLO/HI` (front end) and `MCNTLO/HI` (masked phase, which
  starts from the front end's). The bucket pass makes its batches from
  these counts without a walk of the staging. A count that would pass
  `$FFFF` stays at `$FFxx`.
- **numbers the records** (`RECSEQ`, from 0), so a covered range can
  name its record before it has an address.

### 7.2 Covered ranges and spans

Producers of opaque masked records (`visPost`, `vrCol`, `mwCols`,
`wdProf`) apply `CVSET` to `CVFIRST`/`CVEND` and write the record's
sequence number into `CVRECLO`/`CVRECHI`; the bucket pass turns it into
a W address. The ranges are never reset at a modelled flush: upstream's
reset there only changes which rows are skipped among records already
drawn, and the pixels are the same either way. `FSCUT` is applied to the
fill spans by every masked producer, as upstream's.

## 8. The bucket pass (`bucket.s`)

The replay reads its records packed by column in W, each column's start
in `COLLO`/`COLHI`, at most 8,192 bytes a batch. The bucket pass turns
the frame's staging (aux 0, then the spill banks, in production order)
into that, batch by batch, and calls the replay for each batch.

**Where its code runs.** Inside a `RAMRD` window only zero page, the
stack page and the card are near, and the per-column arrays the pass
needs are in main memory. So:

- the code that runs inside a window (`BKNEAR`, 183 B: the chunk copy,
  the parking and bring-back) is card code, at `$FD8A-$FE40` after the
  replay's `RCODE` (`$F900-$FD89`);
- `nb_bucket`, which runs once before any scatter writes W, and the
  release build's recount (`bk_recount`, walk 1) stay in the masked
  image (`MASKW`; in an overlay frame `OVLW`, which links `bucket.s`
  too);
- the rest runs with `RAMRD` off, in main memory the masked phase leaves
  dead: `BKFAR` (621 B, with the stop `bstop` and the replay's cut
  `rp_cut`) at `$0C00` over `FLOORCLIP`, `CEILCLIP` and `SOLIDCOL`, and
  `BKFAR2` (233 B) at `$0200` over the bounce buffer and the spill.
  `nm_bkload` copies both there from the masked image after
  `nm_masked`.

Its zero page: overlay 1, `BK_NB` at `$70` and the batch list's first
columns after it, the chunk loop `ZLOOP` at `$A0-$A9`. The replay keeps
to `$48-$6F`.

**`nb_frame`**:

1. **`nb_bucket`**: the batches from the producers' counts. A batch is a
   run of whole columns of at most 8,192 bytes; the list holds each
   batch's first column (zero page from `$71`) and size (`BK_SZLO/HI`
   over `DSX2`). Two adjacent batches together pass 8,192 bytes, and W
   gets at most 11/12 of the staging, so a frame takes at most 45
   batches (`MAXB`, proved by `rlayout.py`). Each column's cursor starts
   at its place in its batch's region, W `$6000` + `$2000` × (b mod 3).
2. For each **group** of up to three batches, **`nb_scatter`**: the
   staging is read in chunks of up to 180 bytes into page 1
   (`$0100-$01B3`), one `RAMRD` window a chunk; a record cut by a
   chunk's end moves to page 1's start before the next chunk. Each
   record of the group's batches is copied, without its column byte, to
   its column's cursor. When a running sequence number reaches a covered
   column's `CVREC`, the record's final address (in `$6000-$7FFF`, where
   its batch will be replayed) goes into `CVRECLO/HI` and `CVDONE[c]`
   (over `DSX1`) stops the compare for that column. The group's second
   and third batches are then parked in `RECW` (bank 55), since the
   replay's texel stage takes W `$8000-$BFFF`.
3. For each batch, **`nb_batch`**: brought back from `RECW` into W
   `$6000` when it is not its group's first; its end entry in
   `COLLO`/`COLHI`; the **fuzz marks**: in each of its columns that holds
   a shadow, a `K_FUZZ` becomes `K_FUZZNOW` when a later record of the
   column paints a row from `R_ROW - 1` to `R_ROW + R_COUNT`. Then
   `nat_replay(first column, column after the last)`.

A column is always whole in one batch, so its covering record is in its
batch. A chunk's runs are copied by `ZLOOP`, ten bytes of code in zero
page (zero page reads main inside the window), patched per run.

A column over 8,192 bytes is cut in the release build (section 10); in
the `stops` build it stops the frame (`ST_BUCKET`), as a broken staging
does in both.

## 9. The replay

`nat_replay` draws one batch onto the screen, in strips of whole
columns: a gather of each texture record's texels into the stage (W
`$8000-$BFFF`, one `$C073` write per bank), then the draw through the
row blocks in card bank 2, the fill chains, the overlay drawer and the
fuzz queue. [`src/native/README.md`](../src/native/README.md) describes
it; its addresses are in [`MEMORY_MAP.md`](MEMORY_MAP.md).

`K_FUZZ` records are queued and drawn after the strip in one `RAMRD`
window, because each `RAMRD` switch waits for the firmware to send every
screen byte written so far. A `K_FUZZNOW` record is drawn in place. The
replay zeroes the covered ranges after each strip.

A column that needs more than the 16 KB stage (over 125 texture
records) is cut in the release build (section 10); in the `stops` build
it stops the frame with `BRK`.

## 10. When the records do not fit

| Limit | Capacity | Largest measured | Release build (the disk) | `stops` build |
| --- | --- | --- | --- | --- |
| Staging | aux 0's 8 KB and four spill banks: 202,752 B | 17,003 B (demo3) | the batch dropped, and every later one | `ST_RECORDS`, `BRK` |
| A column in one batch | 8,192 B | far below | the column cut | `ST_BUCKET`, `BRK` |
| A column in the replay's stage | 16 KB (about 125 texture records) | far below | the column cut | `BRK` |

The disk's render build (`rcard`, `render.mk`'s default `RELEASE = 1`)
assembles `rrec.s`, `bucket.s` and `replay.s` with `-D RELEASE`: a frame
that passes a limit is cut, completes and is shown, `STATUS` =
`ST_RECORDS` (2) is set, and the game goes on. The next frame's
`nr_frame` clears `STATUS` and, when it was set, `W_FSW`: a cut frame
counts as not shown, so the next frame neither reuses its fill spans nor
skips the weapon's rows, and what the cut left out is drawn again. No
measured frame comes near any limit. `make -f render.mk stops` builds
the same image without `-D RELEASE`, in which each limit stops the
frame (in the game a `BRK` lands in the platform's crash stop).

The release build's cuts:

- **The staging.** `rec_flush` drops the batch that would end past the
  last spill bank's room, and every later one (the sticky `RECDROP`), so
  the staged records keep the sequence numbers from 0: a covered range
  whose record was dropped is never found, and the scatter clears it.
  The producers' counts include the dropped records, so `nb_bucket`
  counts again (below).
- **A column past a batch.** When `RECDROP` is set, or a column alone
  passes 8,192 bytes, `nb_bucket` counts every column again from the
  staging (`bk_recount`: walk 1, a scan of the staging). A record that
  would take its column's count to 8,192 bytes is left out of the count
  and the column is cut (`CVDONE` bit 7); a later record that fits still
  counts. A cut column is alone in its batch, so its cursor starts at
  its region's start, and the scatter (walk 2) keeps exactly the
  records walk 1 counted: those that end inside the region. A covered
  range whose record was left out is cleared. A cut column keeps at
  least 8,181 bytes, so two adjacent batches still hold 8,181 bytes or
  more and `MAXB` (45, `rlayout.py`) holds.
- **A column past the replay's stage.** `nat_replay` jumps to
  `bucket.s`'s `rp_cut` (in `BKFAR`, the same place in the masked image
  and in `OVLW`): the column's end becomes the record that did not fit,
  and the strip of that column alone is drawn with what was gathered,
  without its covered range (its covering record may be past the cut);
  then the next strip.

A cut costs the frame the records left out: what they would have drawn
is missing (on a2vm, a 2 KB staging drops the frame's last records, the
weapon among them). On a2vm a frame of the title loop's demo (demo3)
takes about 0.4 % longer in the release build than in the build before
it (the scan's test of each staged record, and the code's new places in
TURBO's caches); its pictures are the same.

Why there is no early replay like upstream's `flush`: on F1.2.1 the
replay's record buffer and texel stage are W `$6000-$BFFF`, which holds
the running phase's code, the walk's node frames, the vissprites and
`YHTAB`. An early replay would have to save that state and reload the
image. The one cheap place to add one is the phase boundary after the
walk, before the masked image's load.

## 11. Stops

The masked phase adds these to the front end's stops (`RENDER.md`): all
`STATUS` and `BRK`.

| Code | Name | When |
| ---: | --- | --- |
| 5 | `ST_TEXTURE` | A masked texture whose first patch is not in the store (`TXMP` `$FFFF`) |
| 8 | `ST_SPRFRAME` | A thing on a frame past its sprite's frames |
| 9 | `ST_BUCKET` | A broken staging; in the `stops` build also a column past a batch |
| 10 | `ST_TALL` | A masked post past texture row 255 |

The rules of our own for a column seen from behind (`RENDER.md`) apply
to the whole frame through `RULES`.

## 12. Timing

On the owner's card (F1.2.2, 2026-10-03, the benchmark's demo3, means a
frame), from the BENCHMARK page's rows ([`SPEED.md`](SPEED.md),
[`PLAY.md`](PLAY.md)):

| Row | What | Card | a2vm |
| --- | --- | ---: | ---: |
| `3D` | the front end's image load and `nr_frame` | 18.1 ms | 18.0 ms |
| `MASK` | the masked image's load, `nm_masked`, `nm_bkload`, the bucket pass | 11.7 ms | 11.6 ms |
| `DRAW` | the replays, their SHR drain included | 31.3 ms | 31.3 ms |

On a2vm, by step: `nr_frame` 17.15 ms, `nm_masked` 6.71, `nm_bkload`
0.21, `nb_frame` (bucket pass and replays) 35.52.

## Appendix: upstream to native, by routine

| Upstream | Lines | Native |
| --- | --- | --- |
| `bspSub`'s `R_AddSprites` call | `r_bsp65.s:730-742` | `nr_addsprites` (`rbsp.s`) |
| `R_AddSprites`, `R_ProjectSprite`, `thing`, `whole`, `txDone` | `r_thing65.s:155-707` | `nm_project` |
| `gTZ`, `gTX`, `gGZ`, `gGX`, `wHi`, `k1Wide`, `labsTZ` | `r_thing65.s:713-821`, `:1008-1086`, `:1193-1245` | `nm_project` |
| `R_WallFrame`'s G parts, `prFrame` | `r_wall65.s:1873-1917`; `r_thing65.s:1096-1189` | `nm_project`'s setup |
| `R_InitSpriteIScales`, `fqInit` | `r_thing65.s:837-884` | `rtables.py` (scale records) |
| `boundInit`, `frameInit` | `r_thing65.s:886-997` | `playdisk.py` `sprbound()` |
| `R_SpriteColorMap`, `CMO` | `r_bsp65.s:1009-1020`, `:1061-1097` | `CMOP` |
| `sortSprites`, `scaleLess`, `sortSkip` | `r_frame65.s:288-347`, `:995-1015` | `nm_sort` |
| `drawMasked` | `r_frame65.s:180-212` | `nm_masked` |
| `R_DrawSprite`, `dsVisible`, `clipPtr`, `ltScale2` | `r_sprite65.s:481-561`, `:1460-1716` | `nm_drawsprite` |
| `R_PointOnSegSide` | `r_data65.s:768-` | `nm_ptseg` |
| `R_DrawVisSprite`, `visCol`, `visNext`, `visPost`, `visFill` | `r_seg65.s:2698-3145` | `nm_vis` |
| `visColD`, `vrCol`, `vrPost`, `vrFill`, `vrNext` | `r_frame65.s:1696-2038` | `nm_vis` (magnified runs) |
| `visColF`, `FZ_POS` | `r_sprite65.s:568-719`, `:1727-1728` | `nm_vis` (shadows) |
| `wclipSprite` | `r_frame65.s:966-990` | `nm_vis` |
| `R_RenderMaskedSegRange`, `maskedRange`, `lineFlags`, `smul48`, `mwCols` | `r_frame65.s:357-637`, `:1060-1118`, `:1249-1648` | `nm_mwall` |
| `recAlloc`, `newPage`, `flush` (allocation only) | `r_list65.s:256-323` | `rec_room`'s page model |
| `weaponClip`, `psSetup`, `pspSprite`, `wcDraw3`, `wpCheck`, `wpStart`, `wcProf` | `r_frame65.s:647-854`; `r_sprite65.s:799-880`, `:1186-1301` | `nw_clip`, `wpsp.s` |
| `weaponClipSame` | `r_frame65.s:892-943` | `nr_wskip` |
| `playerSkip`, `playerSprites`, `pspDraw0`, `wdDraw`, `wdProf` | `r_frame65.s:660-665`, `:947-958`, `:1035-1048`; `r_sprite65.s:829-856`, `:1303-1448` | `nm_psp` |
| `wpFind`, `wpFlush`, `wpBuild`, `wbMake` | `r_sprite65.s:884-1178` | the converter's profiles; `wp_find` |
| `R_DrawLists` | `r_list65.s:545-` | `nb_frame`, `nat_replay` |

Not ported: `R_DrawMaskedColumn` and its helpers (dead: nothing calls
it, `r_sprite65.s:197-198`); the small-view variants (`hvPatch`, `vc3`,
`mw3` and others: full view only); `dvInit` (bank bytes of 65816
pointers); the cache tags of `R_FreeSkyPatch` and `maskedRange`.
