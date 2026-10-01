# Milestone 8: the whole renderer

Status: design, 2026-09-30, for the three builders of milestone 8
(stages A, B and C, section 5), revised after one adversarial review
("Review", at the end). Stages A and B are built ("Stage A as built" and
"Stage B as built", at the end; where they found the design wrong it is
corrected in place and says so); stage C is not. It follows
[`RENDER.md`](RENDER.md), milestone 7's design as built and verified,
and takes over its "milestone 8" items. It is a file of its own rather
than a new part of `RENDER.md`, which is already 1,710 lines of a
finished milestone: this file cites `RENDER.md` by section where it
builds on it, and changes it only where section 0.3 says so.

The milestone is `NATIVE.md` section 13, row 8, as the task that
ordered this design states it:

> The whole renderer natively: sprites (`R_AddSprites` in the walk,
> projection, the vissprite list and its sort), the masked phase
> (`R_DrawMasked`: sprites clipped against drawsegs, masked mid
> textures, the fuzz/shadow records with the fuzz queue after each strip
> as milestone 5 does), the player weapon (psprites and the weapon clip
> pass that milestone 7 injects), the per-column bucket of the records,
> and the whole frame from `R_FillStamps` to the replay's last SHR write.
> Acceptance: (1) the record stream and all of aux `$2000-$9FFF` equal
> `ref816`'s on every frame of demo3 (about 534 frames), state injected
> per frame (plus milestone 7's frame sets and synthetic frames, which
> must stay equal); (2) the card test: a disk image that plays 100 demo3
> frames from injected states and prints a CRC per frame, the CRCs equal
> to a2vm's on the same image (the owner runs it at milestone 12; here
> a2vm runs the image end to end). Report: time per phase and FPS by VBL
> count on a2vm (f121 and fastpath) against `NATIVE.md` 1.2 and the
> owner's 6 FPS minimum on F1.2.1.

Binding decisions (`NATIVE.md` 15.1): renderer arithmetic stays exact,
`qmulh` included (row 3); the release is gated on lockstep-schedule mode
(row 4); 6 FPS minimum on F1.2.1 (row 7); 8 MB of RamWorks (row 8); full
view only (row 10); a column seen from behind is a known difference
(row 13, answered 2026-09-30): milestone 7's rules for it stay, flagged
in `RULES` (`RENDER.md` 3.9), and every comparison of this milestone
skips a frame whose `RULES` is not 0 and reports it by name as a known
divergence, never as a pass (sections 4.3, 5.3).

**Labels**, as in `NATIVE.md` and `RENDER.md`:

- **[M: source]** measured. `survey` is the read-only surveys made for
  this design (appendix B); `M7` is `RENDER.md` "Stage C as built" and
  `src/native/README.md` "The front end"; `M5` is `src/native/README.md`
  on the replay; `PROFILE`, `MATH`, `MEMORY_MAP` are those files.
- **[R file:line]** read there. Upstream files are in
  `build/upstream/src/iigs/`.
- **[A]** assumed, or arithmetic on labelled numbers.

## 0. Summary

| Question | Answer |
| --- | --- |
| Where the milestone starts and stops | From `R_FillStamps` entry (`d_main65.s:485`) to the replay's last SHR write: milestone 7's front end with the weapon's clip pass made native, then a second render window (the masked phase), then the bucket pass and milestone 5's replay, batch by batch. Section 0.1 lists what is in and out. |
| Sprite data | Upstream's patch lumps **verbatim** in a per-level patch store in RamWorks (header, `columnofs`, posts), each followed by the 128 bytes that follow it in the reference's memory, so a record's `R_SRC` is the store address of post + 3 and the replay reads what upstream's does; small native tables for sprite frames (`SPRFR`), patch headers (`PHDR`), the sprite scale tables (one 16-byte record per distance), and the weapons' profiles made by the converter. Section 1. |
| Vissprites | A native 40-byte record in W; the weapon's is 11 bytes (`FRVIS`, `WPREV`). Section 1.7. |
| Things | A render part of each mobj (`RTHING`, 24 bytes, RamWorks) and a sector's thing list head in the pad of milestone 7's sector record. The contract milestone 10's game logic keeps. Section 1.8. |
| Projection | **Deferred**: the walk lists the sectors where upstream calls `R_AddSprites` (in walk order) and the masked phase projects their things first. Nothing the walk does reads what the projection makes, so the vissprites and their order are upstream's. Section 0.3. |
| Masked phase | Its own code image loaded into W over the BSP code by the phase loader, keeping the per-level texture tables and the record batch buffer; `YHTAB` at `$BA00`. Sprites back to front with upstream's clipping, the masked ranges they uncover, then the remaining masked drawsegs, then the weapon. Section 3. |
| Records | Milestone 7's staging (aux 0 `$A000`, then spill banks) with a **model of upstream's list pages** (`UPOFS`) because upstream's choice of `K_TEXC` or `K_TEX` for a masked post depends on the room left in its page; covered ranges name their record by its sequence number until the bucket pass turns it into a W address. Section 3.4. |
| Bucket pass | Card code, after the masked phase: the staging read in chunks of up to 180 bytes into page 1 (one `RAMRD` window a chunk: inside it only zero page, the stack page and the card are near), then, with `RAMRD` off, a sizes walk and one scatter walk that packs up to three batches of records by column into W `$6000-$BFFF` (milestone 5's format, batch 1 at `$6000`), its cursors in main arrays the masked phase leaves dead, and turns each covered range's sequence number into a W address; batches 2 and 3 parked in a RamWorks bank during batch 1's replay; the shadows that must be drawn in place marked `K_FUZZNOW`; then milestone 5's replay for each batch. Its size and time come from a prototype in stage A. Section 3.4. |
| `ST_RECORDS` | Staging and spill sized with a large margin (4 spill banks); if they fill in the game, the frame completes without the rest of its records, is flagged in `STATUS`, and the next frame repaints everything; test and lockstep builds stop with `BRK` as today. Section 6.1. |
| Harness | Every frame of demo3 captured (533 frames [M: M7's `title` run holds frame indexes 0-532]), six new dump points (after the sort, at the weapon's draw, at `stripEarly`, at `R_DrawLists` entry and return, and the clip log of each sprite), frame mode to the SHR, routine mode for `R_DrawSprite`, `R_DrawVisSprite` and `R_RenderMaskedSegRange` on milestone 7's 188 frames, a disk image `RENDER.SYSTEM` of 100 consecutive demo3 frames, chained or fully injected, run end to end on a2vm. About 1 hour of compute at 2 jobs and under 0.6 GB of `build/` [A]. Section 4. |
| Speed | On a2vm's F1.2.1 model, render only (no tics): 58-62 ms standing still, 61-64 ms at demo3's median frame, 113-128 ms for the sum of every phase's worst demo3 figure [A on M]; with stage A's measurements 63-64, 66-67 and 120-127 ms. With `NATIVE.md` 6's tic estimates: 14.6-16.5 FPS still, 9.5-12.6 at the demo median, 5.9-6.5 in the heaviest fight (with stage A's measurements 14.1-15.2, 9.2-11.8 and 5.9-6.2): above the 6 FPS minimum but at the heavy end's upper estimate, where the bucket pass (measured first, in stage A) is the least certain figure. Section 6.2. **Stage C measured** the whole frame on all 533 `demo3` frames [M: M8 C]: 64.3 ms still, 72.5 at the median, 164.5 at the worst frame; with the tics 14.1-14.9, 8.8-11.0 and 4.9 FPS: 3 to 10 of 533 frames under 6 FPS ("Stage C as built"). |
| Stages | A: sprite data, projection, vissprites, sort. B: the masked phase (clipping, sprites, shadows, masked walls, the page model). C: the weapon and its clip pass, the bucket pass, the replay after the renderer, the whole frame (acceptance 1), the disk image (acceptance 2), the report. Section 5. |

### 0.1 Scope

In milestone 8, full view only:

| Upstream | Where | Native | Stage |
| --- | --- | --- | --- |
| `R_AddSprites`, `R_ProjectSprite` (`thing`, `whole`, `txDone`, `gTZ`, `gTZcalc`, `gTX`, `gGZcheck`, `gGZ`, `gGX`, `wHi`, `labsTZ`, `k1Wide`) | `r_thing65.s:155-707`, `:713-821`, `:1008-1086`, `:1193-1245` | `nm_project` | A |
| `R_WallFrame`'s sprite part (`PR_GZ`, `PR_GX`, `prFrame`), `R_InitSpriteIScales`, `fqInit`, `boundInit`, `frameInit` | `r_wall65.s:1873-1917`; `r_thing65.s:837-997`, `:1096-1189` | `nm_project`'s setup; the tables by `rtables.py`; `SPRBOUND` as the level set's state (0.3) | A |
| `R_SpriteColorMap`, `CMO` | `r_bsp65.s:1009-1020`, `:1061-1097` | `CMOP` (a page a light index) | A |
| `sortSprites`, `scaleLess`, `sortSkip`, `drawMasked` | `r_frame65.s:180-212`, `:288-347`, `:995-1015` | `nm_sort`, `nm_masked` | A (sort), B (the loop) |
| `R_DrawSprite`, `dsVisible`, `clipPtr`, `ltScale2`, `dsaInit` | `r_sprite65.s:481-561`, `:1460-1716`, `:1796-1805` | `nm_drawsprite` | B |
| `R_PointOnSegSide` | `r_data65.s:768-` | `nm_ptseg` | B |
| `R_DrawVisSprite`, `visCol`, `visNext`, `visPost`, `visFill` (and the clip pass at `visPost` 30$) | `r_seg65.s:2698-3145` | `nm_vis` (masked image), `nw_clip` (front-end image) | B, C |
| `visColD`, `vrCol`, `vrPost`, `vrFill`, `vrNext` (magnified sprites) | `r_frame65.s:1696-2038` | `nm_vismag` | B |
| `visColF` (shadows: `K_FUZZ`), `FZ_POS` | `r_sprite65.s:568-719`, `:1727-1728` | `nm_fuzz` | B |
| `wclipSprite` | `r_frame65.s:966-990` | `nm_vis` | B |
| `R_RenderMaskedSegRange`, `maskedSeg`, `maskedRange`, `lineFlags`, `higher`, `lower`, `smul48`, `smAdd16`, `mwCols`, `mwNextCol` | `r_frame65.s:357-637`, `:1060-1118`, `:1249-1648` | `nm_mwall` | B |
| `weaponClip`, `psSetup`, `pspSprite`, `wcDraw3`, `wpCheck`, `wpStart`, `wcProf` (the clip pass) | `r_frame65.s:647-654`, `:669-854`; `r_sprite65.s:799-821`, `:860-880`, `:1186-1301` | `nw_clip` in the front-end image, replacing milestone 7's seam | C |
| `playerSkip`, `playerSprites`, `pspDraw0`, `wdDraw`, `wdProf` (the weapon's draw) | `r_frame65.s:660-665`, `:947-958`, `:1035-1048`; `r_sprite65.s:829-856`, `:1303-1448` | `nm_psp` | C |
| `wpFind`, `wpFlush`, `wpBuild`, `wbMake` (the profile cache) | `r_sprite65.s:884-1178` | none at run time: the converter makes every weapon lump's profile (1.5) | C |
| The per-column bucket of the records, `K_FUZZNOW` marks, the covered ranges' W addresses | `NATIVE.md` 5.1; `MEMORY_MAP.md` 8 | `nb_bucket`, `nb_batch` (card) | A (prototype), C |
| The replay after the renderer | `R_DrawLists`, `d_main65.s:502` | milestone 5's `nat_replay` per batch | C |

Not ported, with the reason:

| Upstream | Why |
| --- | --- |
| `R_DrawMaskedColumn`, `maskedColumn`, `columnSetup`, `postLoop`, `fastPost`, `mulScale`, `scaleTable`, `SC_TAB` | Dead: nothing calls `R_DrawMaskedColumn` [R `r_sprite65.s:197-198`; its only other mention is a `.word` kept for layout, `:723`]; `mwCols` replaced it for masked walls [R `r_frame65.s:1121-1133`] |
| `hvPatch`, `hvSet`, `vcHalf`, `vc3`, `mwHalf`, `mw3`, `qApply` and the other small-view variants | Full view only (`NATIVE.md` 15.1 row 10); `hvSet` leaves the full view "as assembled" [R `r_thing65.s:2140-2143`] |
| `fuzzColumn`, `fuzzBlock` | Drawing, not producing: milestone 5's replay draws `K_FUZZ` records |
| `dvInit` | Sets bank bytes of 65816 pointers [R `r_frame65.s:1017-1033`]; natively there are none |
| `R_FreeSkyPatch`, `Z_ChangeTagToCache` in `maskedRange` | Cache tags [R `r_frame65.s:559-563`]; nothing natively (as `RENDER.md` 0.1) |
| Automap overlay records (`AM_Drawer` between the render and the replay, `d_main65.s:491-496`) | Milestone 11. A frame with `automapmode` 3 renders natively (the weapon skip reads it) but gets no `K_OVL` records; demo3 has no automap |

### 0.2 Ground rules for this milestone

From `MILESTONES.md` "Ground rules" and the task that ordered this
design: the directory is GPL-2 and code rewritten from upstream is
committed here, but no upstream file is copied and nothing is read from
or derived from upstream's `src/iigs/cal_integer.s`; C11 and
standard-library Python only; no build warnings; tests in `tests/` run
by `python3 -m unittest discover -s tests` and skip with a clear message
when `build/` lacks what they need; no test is weakened and no address,
frame or file is special-cased. **Resources:** at most 2 parallel jobs,
every run under `nice -n 10`, every run with a time limit and every
output with a size limit (`tools/ref816/bounded.py` or
`tests/support.run`), temporary output deleted after the run, `df -h
/System/Volumes/Data` before any run that writes more than 100 MB, stop
below 20 GB free, and `build/` growth for this milestone under 5 GB,
reported by each stage. No `git add`, commit or push by the builders.
`tools/sound`, `src/sound` and `tests/test_sound_*` are not touched. The
owner tests on the card at milestone 12: the disk image of acceptance 2
waits for that.

### 0.3 What the sources change in the task's plan

Six facts of upstream's code change what the task sketched. Each is
reproduced, not fixed.

| # | Fact | Consequence |
| --: | --- | --- |
| 1 | **The walk reads nothing the projection makes.** `bspSub` stamps the sector and calls `R_AddSprites` [R `r_bsp65.s:730-742`]; the projection's direct-page bytes are `BSPDP+21` up and `+48..71`, which "the BSP walk leaves alone" [R `r_thing65.s:46-65`], and it writes only `vissprites`, `num_vissprite` and its own scratch. | The native walk appends the sector's number to a list `SPRSEC` where upstream calls `R_AddSprites`, and the masked phase projects the listed sectors' things in that order before it sorts. The vissprites, their order and the `MAXVISSPRITES` cut are upstream's. The projection's ~2 KB of code then lives in the masked image, not in the front end's tight W, and its far reads are batched (section 3.5). Checkpoint A compares the vissprites at the end of the deferred projection with `ref816`'s at `drawMasked` entry. |
| 2 | **A masked post's record kind depends on upstream's list pages.** `mwCols` makes a `K_TEXC` only "when it fits the page" of the column's list, else a `K_TEX` (with a new page) [R `r_frame65.s:1526-1552`; `lists.inc:29`, `:59-60`]; a page holds records to offset 254, then a `K_NEXT` continues it in one of 50 extra pages, and when those run out every list is drawn early (`flush`) and starts again at offset 0 [R `r_list65.s:256-323`; `lists.inc:17`]. | Every native producer, milestone 7's included, updates a model of upstream's page offset of each column (`UPOFS`) and of the extra pages used (section 3.4). Stage B adds it to `rrec.s`'s `rec_room`, which every producer already calls, and milestone 7's frame mode is run again. `UPOFS` is compared with the low byte of upstream's `COLW` on every frame, so the model is checked where no masked wall shows. |
| 3 | **`SPRBOUND` is state of the level set.** It is made at the first frame the game renders after a level set is loaded (corrected in stage A: the first version said once a session; loading another set clears `PR_IOK` [R `w_level65.s:305-309`], so `SPRISCALE`, `FQ` and `SPRBOUND` are made again), from the patches of the frames the states use, through the lump directory of that level: a sprite whose lumps are not resident then gets E = 0 until the next set [R `r_wall65.s:1873-1877`; `r_thing65.s:827-834`, `:886-997`; the placeholder of width 0, `build/upstream/tools/levelimg.py:13-15`]. It decides the early "off the side" rejection [R `r_thing65.s:278-317`]. | Not a converter constant: the harness injects `ref816`'s `SPRBOUND` (bank `$22` [R `memmap.inc` `MM_SPRBOUND`]) with each frame, and the game (milestone 11) computes it at its first rendered frame exactly as upstream, from that level's patch store. |
| 4 | **The weapon's records come in the profile's order.** When the profile path runs, `wdProf` makes a column's records "from the lowest up" [R `r_sprite65.s:1303-1308`; the list is written from the last post, `:1128-1160`], the reverse of `visPost`'s order. Which path runs depends on the lump (its profile can be made or not) and on the frame (`wpCheck`, `W_WSK`, `wpStart`'s tests) [R `r_sprite65.s:799-880`, `:1186-1257`]. | The converter makes each weapon lump's profile, or records that none can be made, by `wbMake`'s rules; the native draw takes the same path upstream takes and so makes the same records in the same order. The profile arenas (a cache) go (1.5). |
| 5 | **`R_DrawSprite` draws masked ranges in the middle of the sprites.** A drawseg behind the sprite with masked columns gets `R_RenderMaskedSegRange(ds, r1, r2)` at once [R `r_sprite65.s:1598-1618`]; the drawseg loop after the sprites draws only the columns not yet drawn (`maskedtexturecol[x]` set to `SHRT_MAX`) [R `r_frame65.s:1325-1340`]. | Masked walls are built with the sprites in stage B, not after them; the "drawn" marks persist for the frame (3.5). |
| 6 | **`FZ_POS` is persistent.** The fuzz position carries from one shadow to the next and from frame to frame [R `r_sprite65.s:1727-1728`, `:568-570`, `:618-620`]. | A byte of the frame block, injected from `ref816`'s state and compared at the frame's end. |

Two smaller ones: `R_DrawVisSprite` walks a sprite's columns while the
texture column (`frac >> 16`) stays inside the patch, not from `x1` to
`x2`, so it can draw a column past `x2` [R `r_seg65.s:2923-2943`;
`r_frame65.s:960-963`]; and `R_DrawSprite`'s "clip not set yet" test
compares with the view bottom + 1 (upstream's sentinel, not the C
code's -2) [R `r_sprite65.s:1637-1642`, `:1665-1670`]. Both are
reproduced.

## 1. The native layout of the sprite data

### 1.1 Principles

`RENDER.md` 1.1 holds: records the renderer reads from RamWorks are
fetched whole by one `FAR_GET` (a PSRAM line is 8 bytes), arrays indexed
by column are byte planes in fast memory, indexes are bytes where the
counts allow, values are upstream's bit for bit. Two more for sprites:

1. **Texels stay where the replay can read them as upstream does.** A
   record's texel source is post + 3, and the replay reads up to 127
   bytes past it [R `RENDER.md` 1.4; `lists.inc:37-51`]. So the store
   keeps each patch lump's bytes whole and in order, and the 128 bytes
   that follow the lump in the reference's memory after it.
2. **Anything that depends on the session or the frame is state, not
   level data** (`SPRBOUND`, `FZ_POS`, the weapon skip).

### 1.2 Sizes

| Quantity | Value | Label |
| --- | --- | --- |
| Sprite lumps in the game's WAD directory | 452 of 1,015 lumps | M: survey (the directory in RAM, `fileinfo`) |
| Sprite lumps resident per level, their bytes | 242 (426,440 B, E1M1) to 323 (563,028 B, E1M6); 320 lumps, 626,136 B in E1M8; E1M7 (demo3) 322, 563,344 B | M: survey, the 12 level sources of the tour, `newgame` and `title` |
| Lumps whose end + 128 passes their bank's end | 2-9 a level; no lump crosses a bank | M: survey |
| Widest sprite patch | 154 columns | M: survey (the game's WAD); DOOM1.WAD's 483 sprite lumps: 825,576 B, 20,931 columns, 34,578 posts, 1.65 posts a column |
| Vissprites a frame | median 7 (demo, `m5`), 10 (`title`), 4-7 (others); at most 28 (`title`) | M: survey, the 188 frames of `RENDER.md` acceptance 1 at `drawMasked` |
| Sprite columns a frame (sum of x2 - x1 + 1) | median 69.5, at most 334 (`title`); 37 standing still | M: survey |
| Shadows a frame | at most 1 in every set; 5 of 50 `title` frames | M: survey |
| Magnified vissprites (\|xiscale\| < 0.75) | 24 in 50 `title` frames, at most 7 in one; 13 in `newgame` | M: survey |
| Flipped vissprites | 49 in `title`, at most 6 in one frame | M: survey |
| Equal scales among a frame's vissprites (the sort's ties) | 16 in `title`, at most 5 in one frame; 40 in `tour` | M: survey |
| Drawsegs that clip sprites or hold masked columns (`dsX1` not 255) | median 13 (`title`) to 28 (`still`), at most 35 (`tour`) | M: survey |
| Drawsegs with masked columns | 0 in every `title`, `newgame`, `m5` frame; 25 in 50 `tour` frames, at most 3 in one | M: survey |
| Upstream's sprite projection, masked drawing | 17,880 and 55,465 cycles standing still; demo median 12,034 (1,581-74,181) and 51,410 (805-363,023) | M: `PROFILE.md:101-102`, `:145-146` |

So demo3 exercises sprites heavily and masked walls not at all; the
`tour` frames and synthetic frames carry the masked walls (4.1).

### 1.3 The patch store

One per level conversion (as the texel slots, `RENDER.md` 1.4), in
RamWorks banks `SPR0`.. (numbers in 1.10), each filled from `$0200`
inside `$0200-$BFFF`:

| Content | Layout |
| --- | --- |
| Each patch lump the level's sprites use and is resident in the reference | Upstream's `patch_t` bytes verbatim: width, height, leftoffset, topoffset (2 each), `columnofs[width]` (4 each), the posts (topdelta, length, pad, texels, pad), each column ending with `$FF`; then the 128 bytes that follow the lump at its upstream address, read linearly (for the lumps whose tail passes their bank, from the next bank's start) |
| The first patch of each texture a masked mid texture can show | The same. "Can show": `maskedRange` draws `texturetranslation[midtexture]` [R `r_frame65.s:455-468`], so the set is the mid textures of the level's two-sided lines, their switch partners (`switchlist`, `p_switch65.s`: a switch changes a side's mid texture too), and, when one of those is a slime frame, all three frames `animated_texture_basepic` to `+2`, the only textures upstream animates through `texturetranslation` [R `p_spec65.s:318-338`] |
| Index 0 | Upstream's placeholder: a patch of width 0 [R `levelimg.py:13-15`], so a sprite whose lump is not resident is rejected as "too small" exactly where upstream rejects it [R `r_thing65.s:436-443`] |

A lump never crosses a bank of the store (first-fit packing), so a post's
low word and its lump's bank make its address, as upstream assumes
[R `r_seg65.s:2906-2917` adds `columnofs` to the patch's low word only;
`r_frame65.s:1531-1533` "no lump crosses a bank"]. A record's `R_SRC`
is (low, high, bank) of post + 3 in the store; a `K_TEXC`'s `R_TCSRC` is
its low word [R `lists.inc:52-60`].

**Why verbatim, not a native post directory.** The replay needs the
bytes after post + 3 exactly as upstream's memory has them; walking a
column costs one read window whether it reads upstream's post headers
or a native list (3.5); and milestone 9's WAD loader can make the store
by copying lumps. The weapons alone get a directory, their profile
(1.5), because upstream's draw follows one.

**The tail and milestone 9.** The 128 bytes after a lump come from
upstream's level image (its units, `levelimg.py:18-27`). A record shows
texels from post + 3 onward only as far as its rows reach; how far past
a post's last texel any captured record reaches is measured by stage A
(`levelconv.py --overrun`, over every sprite and masked record of every
captured frame) and written into `level.json`. The contract of 1.11
keeps the lump bytes exact and the tail bytes up to that measured reach
plus a margin; the rest of the tail must exist (readable) but may hold
anything.

### 1.4 Sprite frames and patch headers

| Table | Size | Content | Where |
| --- | ---: | --- | --- |
| `SFIRST` | 2 × 55 | Index of sprite s's frame 0 in `SPRFR` (`CONST_NUMSPRITES` 55 [R `offsets.inc:1019`]) | masked image constants (game data, from the WAD) |
| `SPRFR` | 24 per frame | rotate (1), flipmask (1), the patch store index of each of the 8 rotations (2 each), pad; upstream's `spriteframe_t` is 19 bytes: 8 lump words, flipmask, rotate [R `offsets.inc:130-133`] | bank `SPRT` |
| `PHDR` | 16 per patch | width, leftoffset, topoffset (2 each), the store bank (1) and address (2), upstream's lump number (2, for the comparison), pad | bank `SPRT` |
| `TXMP` | 2 × 256 | The patch store index of each texture's first patch, for masked walls (`R_GetTexture` then `patches[0].patchnum` [R `r_frame65.s:528-539`]) | W, per level, in the masked image's table pages |

The frame index is `frame & $7FFF` (bit 15 is `FF_FULLBRIGHT`) [R
`r_thing65.s:319-335`].

### 1.5 The weapons' profiles

For each lump a psprite state names, the converter runs `wbMake`'s rules
[R `r_sprite65.s:1009-1178`]: width 1-320; per column the posts of
non-zero length with `a = topdelta + 1`, `b = a + length` at most 254,
each `a` at least the `b` of the post before (touching posts form a
run, whose first `a` each post keeps), at most 14 posts a column; the
whole profile must fit an empty arena of 5,120 bytes (`$D000-$E3FF`
[R `:755-758`]), which is what makes the three tries of `wpBuild` fail
[R `:946-1007`]. If a rule fails, the lump has **no profile** and the
native draw takes `R_DrawVisSprite` as upstream does (`WP_NONE`).

Native profile (bank `WPRO`), per lump: width (2), the minimum `a` (2),
the columns of each parity and their tables as upstream (the posts of a
column from the lowest up, 5 bytes each: `a + 1`, `b + 1`, the run's
`a`, the texels' offset in the lump (2)), so `wcProf` and `wdProf`
[R `:1261-1448`] translate line by line. A table `WPIDX` (2 bytes a
patch store index, `$FFFF`: none) in bank `WPRO` finds them.

**Check:** where the reference's arenas hold a profile (tags
`WP_TAGL`/`WP_TAGB` at `$0A:C800` [R `:737-745`]), the converter's
equals it byte for byte, the addresses rebased.

### 1.6 The sprite tables

| Table | Upstream | Native | Label |
| --- | --- | --- | --- |
| `SPRXSCALE`, `SPRYSCALE`, `SPRISCALE`, `FQ` | Four tables of 4 bytes for d = tz >> 16 = 0..1280 at `$22:0000`, `:2000`, `:4000`, `:6000` [R `memmap.inc` bank 22; `r_thing65.s:33-37`] | One 16-byte record per d in bank `SPRT`: xscale (4), yscale (4), iscale (4), q (2), r (1), pad: one `FAR_GET` a thing, after the distance tests | R |
| `SPRBOUND` | (E, E / 2 + 2) of each sprite, `$22:7800` [R `memmap.inc`] | 4 × 55 bytes of the level set's state (0.3 row 3), injected per frame into bank `SPRT` and copied into W at the masked phase's start | R |
| `CMO` | 85 words, multiples of 256 [R `r_bsp65.s:1009-1020`] (corrected in stage A: the first version said 69; `rtables.py` reads all 85 and checks them) | `CMOP`: 85 bytes, the record page `$46 + CMO[i] / 256` (the page of colormap A as `R_CMP` holds it [R `MEMORY_MAP.md` 3.4]) | R |
| `SMAP`, `PGT` | `r_bsp65.s:1000-1008`; `r_seg65.s:3151-3173` | As milestone 7 (`RENDER.md` 1.5), in the masked image too | R |
| `bitOf` | 8 words [R `r_thing65.s:810`] | 8 bytes | R |

`rtables.py` copies the first four from the reference's RAM and checks
them: `SPRXSCALE[d]` and `SPRYSCALE[d]` against the C expressions
upstream names (`PROJECTION / d`, `(PROJECTIONY × FRACUNIT) / d`
[R `r_thing65.s:3-6`]), `SPRISCALE[d]` against `MATH.md`'s `recip` of
`SPRXSCALE[d]` [R `r_thing65.s:837-857`], `FQ[d]` against `(16 d / 5,
16 d % 5)` [R `:827-830`, `:863-884`], for d = 4..1280. A failed check
stops the conversion (a table is never "corrected").

### 1.7 The vissprite and the weapon's vissprite

Upstream's `vissprite_t` is 42 bytes with 4-byte pointers [R
`offsets.inc:10-23`]. The native one, 40 bytes, in W (1.10):

| Offset | Bytes | Field | Upstream |
| ---: | ---: | --- | --- |
| 0 | 1 | x1 | `x1` (0..159) |
| 1 | 1 | x2 | `x2` |
| 2 | 4 | scale | `scale` |
| 6 | 4 | gz | `gz` (the thing's z) |
| 10 | 2 | gzt high word | `gz >> 16` + the patch's topoffset (`R_DrawSprite` uses only this word [R `r_sprite65.s:1464-1469`, `:1654`]) |
| 12 | 4 | tx | the thing's x (`gx` is the thing's pointer; `R_DrawSprite` reads x and y through it [R `r_sprite65.s:1567-1593`]) |
| 16 | 4 | ty | the thing's y |
| 20 | 4 | startfrac | `startfrac` |
| 24 | 4 | xiscale | `xiscale` |
| 28 | 4 | texturemid | `texturemid` |
| 32 | 2 | fracstep | `fracstep` |
| 34 | 2 | patch | the patch store index (`gy`, the patch's pointer; `lump_num` and `patch_topoffset` follow from it through `PHDR`) |
| 36 | 1 | page | the record page of the colormap; 0: a shadow (`colormap` NULL) |
| 37 | 2 | slot | the thing's mobj slot (for the comparison: `gx` as an identity) |
| 39 | 1 | pad | |

The colormap pointer maps to one page: `fullcolormap + CMO[i]`
[R `r_thing65.s:663-706`], `fixedcolormap` (a whole colormap page), or
`fullcolormap` for `FF_FULLBRIGHT`; the page is `$46 +` its offset /
256, as `R_DrawVisSprite` makes `W_CMP` [R `r_seg65.s:2706-2712`].

(Corrected in stage C: both are 12 bytes, x2 taking two, as `pspSprite`
stores it unclamped before its off-screen test, and `FRVIS` is at
`$18B0` and persistent: upstream's `FR_VIS` keeps the fields a frame
does not write, an off-screen or absent weapon writing some or none,
and `weaponClipSame` compares them; `framestate.py` injects it like
`WPREV`. "Stage C as built".)

**The weapon's** (`FRVIS` `$0CA0`, `WPREV` `$18A0`, both 11 bytes):
patch index (2; `$FFFF` in `WPREV`: none, upstream's lump `$FFFF`
[R `r_frame65.s:938-939`]), texturemid (4), x1, x2 (1 each), the high
word of startfrac (2), page (1). `pspSprite` sets only these and
constants (scale 1.0, fracstep 512, xiscale 2.0, the low word of
startfrac 0) [R `r_frame65.s:739-840`]; the other upstream fields of
`FR_VIS` are never written (bss) and so equal in every comparison. So
`weaponClipSame`'s byte-for-byte compare of 42 bytes [R `:913-921`]
equals a compare of the 11 native bytes. `framestate.py` converts
upstream's `WPREV` when it injects it; milestone 7's `WPREV_USED` (42)
becomes 11 (`rlayout.py`).

### 1.8 Things and the sector's thing list

`R_AddSprites` walks `sector.thinglist` through `mobj.snext` and reads
each thing's x, y, z, angle, sprite, frame and `MF_SHADOW`
[R `r_thing65.s:155-192`, `:203-707`]. Native:

| Record | Bytes | Fields | Where |
| --- | ---: | --- | --- |
| `RTHING` (by mobj pool slot, upstream's policy [R `NATIVE.md` 6]) | 24 | x, y, z (4 each), the angle's high word (2), sprite (1), frame (2, bit 15 `FF_FULLBRIGHT`), flags (1: bit 0 `MF_SHADOW`), snext (2: slot, `$FFFF` none), pad | bank `RTH`, `$0200` + 24 × slot |
| Sector render part (`RENDER.md` 1.3) | 16 | milestone 7's fields; **new**: the thing list's head at offset 13 (2: slot, `$FFFF` none) in the record's pad | `LVMAP` |

This is the render part of a mobj that milestone 10's game logic keeps,
as milestone 7's sector render part is (`RENDER.md` 1.3): the owner of
milestone 10 keeps this layout or changes it here and in the harness
together. A thing at whole map units (x and y low words 0) takes
upstream's frame-constant G parts; any other takes the `qmulh` products
[R `r_thing65.s:195-275`, `:999-1074`]: both are reproduced.

### 1.9 `YHTAB`

`YHTAB[t] = (E - 1) >> 16` of texel row t, E = sprtopscreen + spryscale
× t, filled lazily up to the rows a post needs, with the word before row
0 in `YHTABM` [R `r_seg65.s:69-72`, `:2771-2791`, `:3118-3145`]: 513
signed words. Native: two planes of 513 bytes (low, high) at W
`$BA00-$BE01`, where `MEMORY_MAP.md` 3.5 reserved `YHTAB` for the masked
phase over milestone 7's wall scratch. (As built in stage B: two planes
of 512, `YHL` `$BA00` and `YHH` `$BC00`, rows 0-511; no `YHTABM`: the
running E - 1 of the last row filled is kept in zero page, `V_E`.) Unit scale uses `V_YH0 + t` and
no table [R `r_seg65.s:2778-2791`, `:2984-2985`], as the weapon always
does (its scale is 1.0 [R `r_frame65.s:54-56`, `:801-808`]).

### 1.10 Placement, F1.2.1

Main memory (new against `MEMORY_MAP.md` 12 in **bold**):

| Range | Content | Live | Label |
| --- | --- | --- | --- |
| `$0310-$036F` | Frame block (87 of 96 B [M: `rlayout.frame_block_used()`]); **new** 8 B: `SPRN` (sectors listed, 1), `FZPOS` (1), `NVIS` (1), `XPUSED` (the extra pages used, 1), `UPFLUSH` (upstream flushes modelled, 1), `RECSEQ` (records staged, 2), `RECDROP` (6.1's sticky drop flag, 1): 95 of 96. Stage A adds every field to `rlayout.FRAME_BLOCK` (whose check fails the build past 96); a further field goes to the spill `$0280-$02FF` or, if masked-phase only, to its zero page | frame, persistent | M, A |
| `$0370-$039F` | Render inputs (22 of 48 B [M: `rlayout.RENDER_INPUTS`]); **new** 21 B: each psprite's sprite (1), frame (2), sx (2: upstream's `OFS_PSP_SX` is a word), sy (4: `OFS_PSP_SY` is 32-bit and `pspSprite` subtracts both words into texturemid [R `offsets.inc:311-313`; `r_frame65.s:784-787`], so the weapon's bob reaches texturemid's fraction, `R_TF` and `WPREV`), the player's sector light (1), `powers[pw_invisibility]` (2): 43 of 48 | frame | R, A |
| **`$0CA0-$0CAA`** | `FRVIS`, 11 B (1.7; milestone 7 had 42) | frame | A |
| **`$1680-$171F`** | `UPOFS`: upstream's page offset of each column's list (3.4). Milestone 5's `COLLO` area: the bucket pass writes `COLLO`/`COLHI` only after the masked phase | frame | A |
| **`$1720-$176F`** | `FRORD`: the sort's order, 80 bytes (vissprite indexes) | masked phase | A |
| `$18A0-$18AA` | `WPREV`, 11 B (1.7) | persistent | A |
| `$18E0-$197F` | `WTMP` (`wclipSprite`) | masked phase | R `MEMORY_MAP.md` 3.3 |

W in the masked phase (the front end's image is dead after the walk but
for the rows marked "kept"):

| Range | Bytes | Content | Label |
| --- | ---: | --- | --- |
| `$6000-$67FF` | 2,048 | As built in stage A: the part both images share, `MATHW` then `auxlc.s` (1,427 B to `$6592`), loaded with the front end's image and left in place | M: M8 A |
| `$6800-$9BFF` | 13,312 | Masked-phase code and its constants (3.7); stage A's part 2,683 B to `$727A` (the first version: all of `$6000-$9BFF`, 15,360 B, with its own subset of the math) | A, M: M8 A |
| `$9C00-$A3FF` | 2,048 | `DSW`: a copy of up to 64 drawsegs that clip sprites or hold masked columns (32 B each; more are read from `RENDB` when used: at most 35 measured [M: survey]) | A |
| `$A400-$B07F` | 3,200 | The vissprites, 80 × 40 B (`MAXVISSPRITES` 80 [R `offsets.inc:1011`]) | A |
| `$B080-$B15B` | 220 | `SPRBOUND` for the frame | A |
| `$B160-$B1FF` | 160 | Fetch buffers (a thing, a frame, a patch header, a scale record; as built: the projection's sprite frame and listed sector, then stage B's patch header `PHB`, seg `SEGB`, side `SIDEB`, front and back sectors `MSEC_F`, `MSEC_B`, a drawseg past `DSW` `DSB`) | A |
| `$B200-$B3FF` | 512 | `TXMP`, per level (the masked image's table pages) | A |
| `$B400-$B8FF` | 1,280 | `TXBANK` ... `TXHT` (**kept** from the front end's image) | R `RENDER.md` 3.4 |
| `$B900-$B9FF` | 256 | Record batch buffer (**kept**) | R `RENDER.md` 3.4 |
| `$BA00-$BE01` | 1,026 | `YHTAB`, two planes of 513 (as built: 512 each, `$BA00-$BDFF`, 1.9) | R `MEMORY_MAP.md` 3.5 |
| `$BE02-$BEA1` | 160 | `CLIPBUF`: a drawseg's clip run from the openings (a sprite's clip; a masked range's `mfloorclip`, `sprbottomclip`) | A |
| `$BEA2-$BFE1` | 320 | `MTCLO`, `MTCHI`: a masked range's texture columns | A |

W is full to `$BFE1`, and a masked range needs both of its drawseg's
clip runs for every column (`maskedRange` and `mwCols` read
`mfloorclip` and `mceilingclip` [R `r_frame65.s:413-420`,
`:1253-1260`]). The second run, `mceilingclip` (`sprtopclip`), goes to
main `SOLIDCOL` `$0E00-$0E9F` (`MCCLIP`), dead once the walk ends
(`MEMORY_MAP.md` 3.3: not persistent; milestone 7's comparison of
`solidcol` is taken at the walk's end, before the masked phase).

Aux 0: **`$1600-$16FF`** `SPRSEC`, the listed sectors (256 bytes, one
`RAMWRT` window an entry from the walk). `MEMORY_MAP.md` 5 gave
`$1600-$19FF` to `SC_TAB`, upstream's product table of the dead
`R_DrawMaskedColumn` path (0.1), and `$1A00-$1FFF` to drawseg planes the
design did not take (milestone 7 put drawsegs in `RENDB`); both are free
natively [A: `MEMORY_MAP.md` 5, `RENDER.md` 3.6].

Card: bank 1 `$DE82-$DFFF` (382 B free [M: 642 of 1,024 used, M7]):
the masked phase's read-window loops, about 200 B [A] (3.5). (As built:
stage A's `mfar.s` 163 B, stage B's `far_posts` 171 B with its buffer of
16 posts; the clip runs and masked columns go through the far layer's
`far_get`, whose `FA_BANK` 0 reads aux 0: no `far_open` or aux-0 copy is
needed. Bank 1 holds 989 of 1,024 B.) `$F900-$FEFF`
(1,165 of 1,536 used [M: M5], 371 free): the bucket pass (3.4), whose
size is not claimed here: stage A's prototype measures it (5.1), and if
it does not fit, risk 2's fallbacks apply.

After the masked phase (the bucket pass and the replay), when the
masked image is dead:

| Where | Content | Live |
| --- | --- | --- |
| Page 1 `$0100-$01B3` | The bucket pass's bounce buffer, a chunk of the staging (180 B) | between gathers (the gather's descriptors and copy loop hold it only during a batch's replay; the stack stays at or above `$01C0`) |
| Main `$0C00-$0C9F`, `$0D00-$0D9F` | `CUR` (each column's cursor, low and high planes), over `FLOORCLIP`, `CEILCLIP` | the scatter walk (dead after the masked phase: not persistent, excluded from 2.4, the replay does not read them) |
| Main `$0E00-$0E9F`, `$18E0-$197F` | `CVW` (each covered column's record as a W address, two planes), over `SOLIDCOL`/`MCCLIP` and `WTMP` | the scatter walk, likewise |
| Main `$1680-$17C1` | `COLLO`/`COLHI`: first each column's byte count (walk 1), then its start (milestone 5's format), over `UPOFS` and `FRORD` (compared at the masked phase's end, 2.4) | to the last batch's replay |
| W `$6000-$BFFF` | Up to three batches of records after the scatter walk (batch 1 at `$6000`, 2 at `$8000`, 3 at `$A000`); from batch 1's gather on, milestone 5's records `$6000-$7FFF` and stage `$8000-$BFFF` | frame |
| Zero page `$18-$41`, `$70-$AF` | The batch list: each batch's first column (1 B) and size (2 B), at most 26 batches with 4 spill banks; the walks' pointers (as built after the verification of stage C: at most 45 batches, their first columns at `$71-$9E`, their sizes over `DSX2`) | from walk 1 to the last batch (the replay uses `$48-$6F` only [R `MEMORY_MAP.md` 8]) |
| Main `$1540-$167F` | `CVRECLO`/`HI` (sequence numbers from the producers, then W addresses) | as milestone 5's |

RamWorks banks of the harness (`rlayout.py` names them; the game's
allocation is milestone 11's):

| Bank | Name | Content | Label |
| --- | --- | --- | --- |
| 6-8 | `LVSEG`, `LVMAP`, `RENDB` | Milestone 7's; `LVMAP`'s sectors get the thing list head | R `RENDER.md` 1.8 |
| 9, 10 | `RECSP` → moved | The spill moves to four consecutive banks, 51-54 (6.1); 9 and 10 become free | A |
| 11-30 | `TEX0`.. | Milestone 7's texel slots | R |
| 31 | `SEAM` | Harness only: milestone 7's seam and lockstep data; **new**: the clip log (4.2) at `$1400`, where the walk's lockstep build keeps `SEAM_SOLID` (the two builds are exclusive) | R `rlayout.py:50-60`, A |
| 32-47 | `SPR0`.. | The patch store: 426-626 KB of lumps and 31-41 KB of tails a level [M: survey; A: 128 B × 242-323 lumps], so 10-14 banks of 48,640 B [A] | M, A |
| 48 | `SPRT` | Scale records (1,281 × 16 = 20,496 B), `SPRFR`, `PHDR`, `SPRBOUND` | A |
| 49 | `WPRO` | Weapon profiles and `WPIDX` | A |
| 50 | `RTH` | `RTHING` (768 slots × 24 = 18,432 B [A: the pool's size is milestone 10's to confirm]) | A |
| 51-54 | `RECSP` | Record spill | A |
| 55 | `RECW` | Batches 2 and 3 parked by the bucket pass during batch 1's replay (3.4), 16 KB | A |
| 112, 113 | `CODE` | The front end's image (112, milestone 7) and the masked phase's (113) | R, A |
| 116-122 | | `FSTEP`, `MATH.md`'s tables, `RECIP_TABLE` | R |

In the game: `NATIVE.md` 4.4 counted 76-82 of 126 banks; its "level
window, 22-24" is upstream's, which holds the level's sprite units too
[R `levelimg.py:5-27`]; the native level (segs and map 2, texels 7-19
[M: M7], patch store 10-14, sprite data 2) comes to 21-37 banks [A], so
the total stays within 126.

### 1.11 The converter and the contract with milestone 9

`levelconv.py` gains the sprite part; its output format becomes
`render-level 2` (milestone 7's `render-level 1` plus):

| File | Content |
| --- | --- |
| `level.img` | Also the `SPR0`.. banks, `SPRT`'s `SPRFR` and `PHDR`, `WPRO`, and the masked image's per-level pages (`TXMP`) |
| `level.json` | Also: each patch store entry (upstream lump, upstream address and size, store bank and address), the placeholder, the sprite frame count per sprite, each weapon lump's profile or "none" with the rule that failed, the measured overrun (1.3) |
| `patchmap.json` | Each store byte range to its upstream address, for `rcanon.py` (as `texmap.json` for slots) |

It reads upstream's objects by symbol: `fileinfo` and `numlumps` (the
lump directory: the placeholder is the one `filepos` several lumps share
[R `tools/bridge/upstream.py:361-381`]), `sprites` and their
`spriteframes`, the states that name psprite lumps, `texturetranslation`,
`animated_texture_basepic`, `switchlist` and each masked texture's
`patches[0]`.

**Checks** (each a failure): every sprite frame's lumps resolve to a
store index or the placeholder; each stored lump's bytes and tail equal
the reference's RAM at its address; no lump crosses a store bank; the
first patch of every texture a masked mid texture can show (1.3: the
closure through the switches and `texturetranslation`, not only the
level's own mid textures) is stored, or, when its lump is not resident
in the reference, listed in `level.json` with `TXMP` = `$FFFF`, which
stops a frame that draws it with `ST_TEXTURE` as milestone 7 does for a
texture without slots; every profile equals the
reference's arenas where they hold one (1.5); the counts fit (patch
store indexes below 65,535, slots within `RTH`).

**The contract with milestone 9:** `render-level 2` is the layout. The
lump bytes are the WAD's lumps (which lumps: those of the level's
sprites and masked textures, as upstream's level set chooses them
[R `levelimg.py:5-27`]); the tail bytes as far as 1.3's measured reach;
the profiles by 1.5's rules. `SPRBOUND` is not the loader's: the game
makes it at its first rendered frame (0.3 row 3).

## 2. Per-frame state and its injection

### 2.1 What the masked phase reads

| Input | Upstream | Native | Written in the game by |
| --- | --- | --- | --- |
| The listed sectors | `R_AddSprites(sector, lightlevel)` calls, walk order [R `r_bsp65.s:730-742`] | `SPRSEC` (aux 0), `SPRN` | the walk |
| The things in each sector | `sector.thinglist`, `mobj.snext`, x, y, z, angle, sprite, frame, flags [R `r_thing65.s:155-707`] | the sector's head (1.8), `RTHING` | game logic (milestone 10) |
| The sectors' light | `lightlevel` | the sector record (milestone 7) | game logic |
| The player's psprites | `_g_player.psprites[0..1]`: state (→ sprite, frame), sx (16 bits), sy (32 bits) [R `offsets.inc:308-313`; `r_frame65.s:651`, `:662-665`, `:702-800`] | render inputs | game logic |
| `validcount` and every sector's stamp | `validcount` (raised about 23 a tic by game logic's line checks [M: `NATIVE.md` 14 risk 10] and once a frame by `setupFrame`), `sector.validcount` | frame block `VALIDCOUNT`, the sector record (milestone 7) | game logic and the renderer |
| The player's invisibility | `powers[pw_invisibility]` [R `r_frame65.s:818-822`] | render inputs | game logic |
| The player's sector light | `player.mo.subsector.sector.lightlevel` [R `r_frame65.s:669-689`] | render inputs | game logic |
| Extra light, gamma, the fixed colormap | `LT_BASE`, `LT_FIXED`, `fixedcolormap` | frame block, render inputs (milestone 7) | game logic, menu |
| The view window | `viewtop`, `viewbottom` → `SPR_TOPINIT`, `SPR_BOTINIT`, `screenheightarray` [R `r_frame65.s:137-154`] | frame block (milestone 7) | display |
| The automap mode | `automapmode` [R `r_frame65.s:903-906`] | frame block | automap |
| Drawsegs, openings, clips, `dsX1`/`dsX2`, `dsCount` | milestone 7's outputs | `RENDB`, aux 0 `openings`, `OPENHI`, main | the front end |
| Texture translation and heights | `texturetranslation`, `textureheight` [R `r_frame65.s:457-493`] | `TEXTRANS`, `TXHT` (milestone 7) | game logic |
| `SPRBOUND` | bank `$22` | `SPRT`, then W | the first rendered frame (0.3) |
| `FZ_POS` | near variable | frame block `FZPOS` | the masked phase |
| `WPREV`, `WCLIP`, `FR_SKIP`, `W_WSK` | `lists.inc:123-131`, `r_frame65.s:106` | milestone 7's, `WPREV` native (1.7) | the renderer |
| `WTMP` (added in stage B) | `lists.inc:127-128`: `wclipSprite`'s floor clip of a sprite, written for the columns x1 .. min(x2 + 1, 159) only | main `WTMP` `$18E0` | the masked phase: a sprite whose texture reaches a column past x2 + 1 in a frame that skips the weapon rows reads the value an earlier sprite, maybe of an earlier frame, left there [R `r_frame65.s:966-990`; `r_seg65.s:2923-2943`], so `WTMP` is persistent state; `framestate.py` injects it from P0 |
| The SHR screen (the replay reuses fill rows; shadows read it) | `$E1:2000-$9FFF` | aux 0 | the frame before, the 2D code, `I_ApplyColors` |

### 2.2 The renderer's state across frames

(Corrected in stage B: `WTMP` is persistent too, 2.1; 1.10's "after the
masked phase" puts the bucket pass's `CVW` over it, which stage C must
move or the game's frames would read the bucket pass's bytes there.) (Stage C: the bucket pass no longer writes
`WTMP`: `CVW` became `CVDONE` over `DSX1`/`DSX2`, 3.4; and `FRVIS` is
persistent, 1.7.)

Milestone 7's persistent state (`RENDER.md` 2.2) plus `FZPOS` and
`WPREV` in its native form. Per frame, not persistent: `UPOFS` and
`XPUSED` start at 0 with the staging (upstream's lists are empty at the
frame's start [R `RENDER.md` 2.2]), `MM_WPOK` is 0 at every frame's
start (every frame's draw clears it: `wdDraw` stores 0, and `wcDraw3`
without the clip pass stores 0 [R `r_sprite65.s:820`, `:829-830`]), so
a flag of the frame block replaces it and is not injected.

### 2.3 How the harness injects it

`framestate.py` (milestone 7's, `RENDER.md` 2.3) adds:

1. the render things: every mobj reachable from a sector's
   `thinglist` in the frame's P0 dump (zone banks `$06-$09`), by pool
   slot, into `RTH`; each sector's head into its record's pad;
2. the psprites, the invisibility power and the player's sector light
   into the render inputs;
3. `SPRBOUND` from bank `$22:7800` (P0 gains that range), `FZ_POS`
   into `FZPOS`, `WPREV` converted (1.7);
4. the screen, all of aux 0 `$2000-$9FFF`, composed from three dumps
   (4.1). Between `R_FillStamps` and `R_DrawLists` upstream writes the
   screen in three places: an early flush (`flush` → `drawAllL` →
   `drawAll`, with SHR shadowing on [R `r_list65.s:304-323`,
   `:566-580`]), then, after the render, `stripEarly` and
   `I_ApplyColors` [R `d_main65.s:485-502`]. The native frame has no
   early flush (6.1), so its replay must start from the screen before
   any flush with the colours and strip of after the render. Rule:
   start from P4's screen (`R_DrawLists` entry); where the screen at
   the first early flush (the first P2) differs from the screen at
   `stripEarly` entry (PS), those bytes, which only the flushes wrote,
   take the first P2's value. A frame with no P2 takes P4 whole. The
   tool fails the frame, naming it, if a byte a flush wrote is also
   changed between PS and P4 (the strip over a row a flush drew: the
   native order could not give upstream's pixels there without a
   decision). So a pre-flush record, a `K_FUZZ` included, is replayed
   once, on the bytes upstream's flush read;
5. `VALIDCOUNT` and every sector's stamp from P0, together, on every
   frame (as milestone 7's injection does [R `framestate.py:216`,
   `:319`]): `validcount` is game state as much as the renderer's;
6. no seam: from stage C the clip pass is native (stages A and B keep
   milestone 7's seam).

Every byte it does not define is filled with `$A5` or `$5A`, as
milestone 7 does.

**The card runner** (acceptance 2) chains frames by default and injects
each frame whole in its second mode: section 4.6.

### 2.4 What is compared, and what is not

At the frame's end (**acceptance 1**):

| Output | Upstream | Compared as |
| --- | --- | --- |
| The record stream | Each column's records: every early flush's (P2) in flush order, then the lists at `R_DrawLists` entry (P4), `K_NEXT` dropped (`NATIVE.md` 11) | The native staging by column in production order; each record's fields; `R_SRC` through `texmap.json` and `patchmap.json` to upstream's address; `K_TEXC`'s `R_TCSRC` likewise with its chain's bank |
| The SHR | `$E1:2000-$9FFF` at `R_DrawLists`' return (P5) | All of aux 0 `$2000-$9FFF` after the last batch's replay, byte for byte; no write outside the replay's allowed set (`MEMORY_MAP.md` 1 rule 6) |
| Covered ranges | `CV_ROW`, `CV_REC` at P4 | `CVFIRST`, `CVEND`, and the covering record as its index in its column's list (upstream: `CV_REC`'s record walked from `COLPAGE(c)`; native: the sequence number's record), on frames with no flush (below) |
| Fill spans | `FS_*` at P4 (the masked producers' `FSCUT`) | 8 planes of 160 |
| Page model | `COLW`'s low byte (the offset in the page), `XPNEXT` at P4 | `UPOFS`, `XPUSED` at the masked phase's end (a snapshot event: the bucket pass writes `COLLO` over `UPOFS`) |
| Weapon skip | `FR_SKIP`, `W_WSK`, `WPREV`, `WCLIP` at P4 | values; `WPREV` through 1.7 |
| `FZ_POS` | at P4 | `FZPOS` |
| Milestone 7's outputs | at `drawMasked` (P3) | as `RENDER.md` 2.4, at the native walk's end (an a2vm snapshot event) |

At the checkpoints: the vissprites (count, order, each field of 1.7
canonical: x1, x2, the thing's slot, the lump, gz, startfrac, scale,
xiscale, texturemid, fracstep, topoffset, the colormap as page, fixed or
shadow) at P3 against the end of the native projection; the sort's
order `FR_ORDER`, `FR_SKIP` and `W_WSK` after `sortSkip` (P3s); each
sprite's clips (the clip log, 4.2); the records at the weapon's draw
(P3w); `floorclip` and `FR_VIS` after the clip pass (P1, milestone 7's
seam point).

**Excluded, with the reason:**

| Excluded | Why |
| --- | --- |
| `floorclip`, `ceilingclip` after the masked phase | Scratch: `R_DrawSprite` rewrites them per sprite [R `r_sprite65.s:1490-1499`] and the next frame clears them [R `r_frame65.s:125-162`]; each sprite's clips are compared by the clip log |
| `maskedtexturecol` entries set to `SHRT_MAX` | Per-frame marks [R `r_frame65.s:1333-1340`]; their effect (each column once) shows in the records |
| The weapon profile arenas and tags (`WP_*`), `MM_WPOK` | A cache and an internal flag; their effect (the path, the order) shows in the records |
| `SC_TAB`, `MC_*`, `PR_GBI`, `PR_GCI`, `PR_HVS`, the patched `K3FIX`/`K2FIX` | Dead code or caches of code patches [R `r_thing65.s:83-89`, `:1096-1189`] |
| `spryscale`, `sprtopscreen`, `curline`, `FR_*` scratch, `WTMP`, `DS_*`, `V_*` | Scratch |
| `CV_ROW`/`CV_REC` on a frame with an early flush | Upstream's flush resets the ranges [R `r_list65.s:545-557`; `lists.inc:108-117`]; the native model keeps whole-frame ranges, which give the same pixels (3.4). No captured frame flushes before `drawMasked` [M: M7]; one that flushes in the masked phase is reported with its flush count, its records and SHR still compared, from the screen composed by 2.3 item 4 |
| `SOLIDCOL` after the walk's end | `nm_mwall`'s `MCCLIP` (1.10); compared at the walk's end as milestone 7's output |
| The SCBs, palettes, strip and status bar rows | Not the renderer's: injected from P4 (2.3); equal by construction, still inside the compared range |

## 3. Modules, code placement, memory, budgets

### 3.1 Files

| File | Stage | Content |
| --- | --- | --- |
| `tools/native/levelconv.py` | A (C adds profiles) | 1.3-1.5, 1.11 |
| `tools/native/rtables.py` | A | 1.6 |
| `tools/native/rlayout.py` | A (B, C add) | 1.10: the masked W map, `VIS`, `RTHING`, the new banks, `UPOFS`, `SPRSEC`, the new frame block and input fields, the allowed writes |
| `tools/native/framestate.py` | A (C adds the chain) | 2.3 |
| `tools/native/rendercap.py`, `routinecap.py` | A (B adds routine captures) | 4.1 |
| `tools/native/rcanon.py` | A, B, C | 2.4, 4.3 |
| `tools/native/render_check.py` | A, B, C | 4.2-4.5 |
| `tools/native/framesynth.py` | A, B, C | the synthetic frames of 4.1 |
| `tools/native/rdisk.py` | C | the disk image of acceptance 2 and its a2vm run (4.6) |
| `src/native/rbsp.s` | A | `nr_addsprites` becomes the `SPRSEC` append |
| `src/native/mproj.s` | A | `nm_project`, `nm_sort` |
| `src/native/mmain.s` | A (B, C complete) | `nm_masked`: the phase's driver, the drawseg copy, `drawMasked`'s loops |
| `src/native/msprite.s` | B | `nm_drawsprite`, `nm_ptseg` |
| `src/native/mvis.s` | B | `nm_vis`, `nm_vismag`, `nm_fuzz`, `YHTAB` |
| `src/native/mwall.s` | B | `nm_mwall` |
| `src/native/rrec.s` | B | `rec_room` gains the page model; assembled into both images |
| `src/native/wclip.s` | C | `nw_clip` (front-end image): `psSetup`, `pspSprite`, the clip pass |
| `src/native/mpsp.s` | C | `nm_psp` (masked image): the weapon's draw |
| `src/native/far.s` | A, B, C | the phase loader takes a bank and page list; the masked phase's read loops (3.5) |
| `src/native/bucket.s` | A (prototype), C | `nb_bucket` (card `$F900` part, 3.4) |
| `src/native/mask.cfg`, `render.mk` | A | the masked image's link map and builds (`mtest`, `mprof`); `rframe.s` gets the whole-frame driver |
| `src/native/rrunner.s`, `rrunner.cfg` | C | `RENDER.SYSTEM` (4.6) |
| `tests/test_native_masked.py`, `tests/test_native_frame8.py` | A, B, C | 4.7 |

`math.s` is assembled again for the masked image (`-D RENDER`: `pta16`
reads `tantoangle` through `auxlc.s`), with the subset the phase calls:
`pta16` (rotations), `recip` (`mwCols` for a scale of 1.0 or more
[R `r_frame65.s:1401-1412`]); the products are `MATHLC`'s, always in
card bank 1 [R `MATH.md`].

### 3.2 The frame, phase by phase

| # | Phase | Code | W holds | Upstream |
| --: | --- | --- | --- | --- |
| 1 | Front end's window | `far_wload(112)` (card) | its code and tables | |
| 2 | Plane stamps, setup, clears | `nr_frame` | front end | `R_FillStamps`, `r_frame65.s:117-169` |
| 3 | **Weapon clip pass** (C; A and B: the seam) | `nw_clip` | front end | `weaponClip` |
| 4 | Weapon skip, `rec_start`, the walk (with `SPRSEC`), wall setup, seg loops, last batch | milestone 7 | front end | to `jsl R_FreeSkyPatch` |
| 5 | **Masked phase's window** | `far_wload(113)`: the code pages and `TXMP`'s, not `$B400-$BFFF` | masked | |
| 6 | **Drawseg copy, `SPRBOUND`** | `nm_masked` | masked | (`dsaInit`) |
| 7 | **Projection** | `nm_project` | masked | `R_AddSprites` × `SPRN` |
| 8 | **Sort** | `nm_sort` | masked | `sortSkip` |
| 9 | **Sprites back to front, the masked ranges they uncover** | `nm_drawsprite`, `nm_vis*`, `nm_fuzz`, `nm_mwall` | masked | `drawMasked`'s first loop |
| 10 | **The masked drawsegs, last first** | `nm_mwall` | masked | its second loop |
| 11 | **The weapon, the flash** | `nm_psp` | masked | `playerSkip` |
| 12 | **Last batch; the bucket pass** | `rec_flush`, `nb_bucket` (card) | batches 1-3 of records | |
| 13 | **Each batch: back from `RECW`, fuzz marks, replay** | `nb_batch`, `nat_replay` (milestone 5) | records, stage | `R_DrawLists` |

Phases 5-13 are new. On F1.2.1 the tics run in W before phase 1
(`MEMORY_MAP.md` 3.5), so both images are loaded every frame.

### 3.3 Entry points and conventions

As `RENDER.md` 3.2: near calls, card bank 1 selected, `RAMRD`,
`RAMWRT`, `ALTZP` off and `$C073` 0 between windows, decimal off,
interrupts on, arguments in registers and zero page.

| Routine | In | Out | Upstream |
| --- | --- | --- | --- |
| `nm_masked` | frame block, W | records, spans, ranges, `FZPOS`, weapon skip | `drawMasked` |
| `nm_project` | `SPRSEC`, `SPRN`, things, view | vissprites, `NVIS` | `R_AddSprites` |
| `nm_sort` | vissprites | `FRORD`, `FR_SKIP`, `W_WSK` | `sortSkip` |
| `nm_drawsprite` | X = vissprite index | clips, then `nm_vis`; masked ranges | `R_DrawSprite` |
| `nm_vis` | a vissprite (or `FRVIS`), the clip arrays' pointers | records | `R_DrawVisSprite` |
| `nm_mwall` | A = drawseg (its `DSW` copy or `RENDB` index), X = x1, Y = x2 | records; the range's columns marked drawn | `R_RenderMaskedSegRange` |
| `nm_ptseg` | the seg's number, x, y | C = side | `R_PointOnSegSide` |
| `nw_clip` | render inputs | `FLOORCLIP`, `FRVIS`, the frame block's `WPOK` flag | `weaponClip` |
| `nm_psp` | render inputs, `FRVIS`, `FR_SKIP` | records | `playerSkip` |
| `rec_room` | A = the record's native size, X = its column | Y = the batch's free byte; `UPOFS`, `XPUSED` updated (3.4) | `recAlloc`, `newPage` |
| `nb_bucket` | once, after the masked phase: the staging (aux 0, `RECSP`), `STG_BANK`/`STG_PTR`, `CVRECLO`/`HI` as sequence numbers; card bank 1 selected, `RAMRD` off | the batch list (zero page), `COLLO`/`COLHI`, `CVRECLO`/`HI` as W addresses, batches 1-3 in W (2 and 3 parked in `RECW`) | (milestone 5's loader) |
| `nb_batch` | X = the batch, before its replay | its records in W `$6000`, its end entry in `COLLO`/`COLHI`, `K_FUZZNOW`; then `nat_replay` | (milestone 5's loader) |

### 3.4 Records: the page model, covered ranges, the bucket pass

**Staged records** keep milestone 7's form, upstream's record with the
column byte after the kind (`RENDER.md` 3.6): `K_TEX` 12 bytes,
`K_TEXC` 8, `K_FILL` 6, `K_FUZZ` 5. Every producer appends through
`rec_room`, which becomes the one place that models upstream's list
pages:

- `UPOFS[c]` (0..254) is the offset upstream's next record of column c
  would take in its page, `XPUSED` the extra pages taken (0..50). A
  record of upstream size s (native size - 1) that fits (`UPOFS[c] + s
  ≤ 254`) adds s; else, with an extra page left, `XPUSED` + 1 and
  `UPOFS[c] = s` (a `K_NEXT` ends the old page); else upstream flushes:
  every `UPOFS` = 0, `XPUSED` = 0, `UPFLUSH` + 1, and the record takes
  offset 0 of its column's home page [R `r_list65.s:256-323`;
  `lists.inc:17`, `:29`].
- `nm_mwall` makes a post a `K_TEXC` exactly when upstream does: the
  post before in this column of this range made the column's last
  record (`MW_CONT`) and `UPOFS[c] + 7 ≤ 254` [R `r_frame65.s:1530-1535`];
  else a `K_TEX`.
- The model never draws early (6.1): at a modelled flush the native
  staging keeps every record, and the per-column stream is the one
  `NATIVE.md` 11 compares ("flushed batches concatenated per column").

**Covered ranges.** Producers of opaque masked records (`visPost`,
`vrCol`, `mwCols`, `wdProf`) apply `CVSET` [R `lists.inc:137-156`;
`r_seg65.s:2867-2885`; `r_frame65.s:1226-1244`] to `CVFIRST`/`CVEND`
(main, milestone 5's) and write the record's `RECSEQ` into
`CVRECLO`/`CVRECHI`; a shadow sets the range to 255, 254, none for the
frame [R `r_sprite65.s:694-698`], which also flags the column as holding
a shadow. The ranges are never reset at a modelled flush: upstream's
reset after a flush [R `lists.inc:108-117`] only changes which rows are
skipped among records already drawn, while resetting natively could let
a later covering record cut rows a pre-flush shadow must read. Pixels
are equal either way; the SHR comparison checks them.

**`FSCUT`** [R `lists.inc:92-107`] is applied by every masked producer
to `FSTOP`/`FSBOT` (milestone 5's planes), as upstream's are
[R `r_seg65.s:3030-3031`; `r_frame65.s:1525`, `:1844`, `:1927`;
`r_sprite65.s:694`, `:1388`].

**The bucket pass** (`nb_bucket`, card code, after the masked phase).
Rule 5 of `MEMORY_MAP.md` shapes it: inside a `RAMRD` window only zero
page, the stack page and the card are near, and what the pass must read
per record, the column cursors and `CVRECLO`/`HI` (main
`$1540-$17C1`), is not (with `RAMRD` on those addresses read aux 0,
where `$1600-$16FF` is `SPRSEC`). About 640 bytes of cursors and
covering records have no room in zero page (about 186 B of overlays
free), page 1 (181 B before the gather) or the card (about 40 B once
the masked loops are in). Toggling `RAMRD` per record is too slow:
every mapping change costs a window (3.0-4.7 µs [M: `NATIVE.md` 1.2])
and empties the TURBO caches, for about 700 records a median demo3
frame [A: 5.1 KB, 6.2], two walks. So it **bounces**, and keeps its
per-column arrays in main arrays the masked phase leaves dead (1.10):

1. **Chunk copy** (used by both walks). One `RAMRD` window a chunk
   (the `$C073` bank set for a spill bank): up to 180 bytes of the
   staging, in production order, into page 1 `$0100-$01B3`, by a card
   loop. A record cut by the chunk's end (at most 11 bytes) is moved to
   page 1's start before the next copy. The staging's end is
   `STG_BANK`/`STG_PTR`.
2. **Walk 1, sizes** (`RAMRD` off, over the chunks): each record's kind
   gives its native size; its column byte adds size - 1 to column c's
   count in `COLLO`/`COLHI`. Then the batches: runs of whole columns of
   at most 8,192 bytes (`MEMORY_MAP.md` 8), each batch's first column
   and size into the batch list in zero page; a column whose records
   alone pass 8,192 bytes gets 6.1's column limit. The counts become
   starts in place, each batch's columns from `$6000` (milestone 5's
   format; the entry at a batch boundary holds the next batch's start,
   and the batch's end, `$6000` + its size, is written there before its
   replay). `rlayout.py` asserts the batch list holds the staging's
   capacity / 8,192 + 1 batches. (Corrected by the verification of stage
   C, 2026-10-01: that bound is wrong, since whole columns only promise
   that two adjacent batches together pass 8,192 bytes; `rlayout.py`
   now proves MAXB = 45, "Verification of stage C".)
3. **Walk 2, scatter** (`RAMRD` off, over the chunks again), for batches
   1-3 at once: batch b's region is W `$6000` + `$2000` × (b - 1), all
   free now (the masked image is dead and no gather has run). `CUR[c]`
   starts at column c's start moved into its batch's region; each record
   of a column in batches 1-3 is copied from page 1, without its column
   byte, to `CUR[c]`, which advances. A running sequence number counts
   every record of every column in production order, as `RECSEQ` did
   when the producers stored it into `CVRECLO`/`HI`; when it equals
   `CVREC[c]` of the record's column (main, readable now), the record's
   final address (in `$6000-$7FFF`, where its batch will be replayed)
   goes to `CVW[c]`, never over `CVREC` itself (an address could equal
   a later sequence number); after the walk `CVW` of the covered columns
   is copied into `CVRECLO`/`HI`. (As built in stage C: the address goes into
   `CVRECLO`/`HI` at once and a flag `CVDONE[c]` stops the compare for
   that column, so no second array or copy.) A column is always whole in one batch,
   so its covering record is in its batch. With more than one batch,
   W `$8000-$BFFF`'s used bytes are then parked in `RECW` (1.10), one
   `RAMWRT` window a page run, before batch 1's gather overwrites them.
   A frame with more than 3 batches (over 24 KB staged, none measured)
   scatters batches 4 onward by further walks, three at a time.
4. **For each batch**: batch 2 or 3 brought back from `RECW` to W
   `$6000` (one `RAMRD` window a page run); its end entry in
   `COLLO`/`COLHI`; the **fuzz marks**: for each of its columns flagged
   with a shadow, a walk of its records in W, last first, marking a
   `K_FUZZ` `K_FUZZNOW` when a later record of the column paints rows
   `R_ROW - 1` to `R_ROW + R_COUNT`, as `loader.mark_fuzz` does
   (`src/native/README.md`, "The fuzz queue"); then `nat_replay(first
   column, end column)`.

Windows: two a chunk a walk, about 60 for a 5 KB staging [A], and a
few a page run to park and bring back a later batch (its bytes twice
at the phase loader's 0.25 µs a byte [M: M7]). **Code and time are
estimates** (3.7, 6.2): stage A prototypes the chunk copy, both walks,
the parking and the fuzz marks on milestone 7's staged records (5.1),
and its measurements replace them before stage B starts.

A covering record that was never staged (6.1) leaves its column's range
cleared, so the replay never cuts rows for a record that will not paint
them. The replay itself is milestone 5's, unchanged, with its fuzz queue
after each strip.

### 3.5 Far access in the masked phase, F1.2.1

| Work | Window | Per frame [A on M counts, 1.2] |
| --- | --- | --- |
| Drawseg copy | one `RAMRD` window on `RENDB` for the drawsegs with `dsX1` ≠ 255, ≤ 64 × 32 B | 13-35 drawsegs: 0.1-0.3 ms |
| `SPRSEC` | one `RAMRD` window, ≤ 256 B aux 0 → W (card loop) | < 0.05 ms |
| `SPRBOUND` | one `FAR_GET`, 220 B | < 0.1 ms |
| A thing | `FAR_GET` its `RTHING` (24 B); after the distance tests `FAR_GET` its frame (`SPRFR`), its patch header (`PHDR`) and its scale record, all in `SPRT`; `pta16`'s `tantoangle` windows for a rotated frame | about 20-40 µs a visible thing, 7-28 a frame: 0.2-1.1 ms |
| A sprite column | `far_posts` (card): `columnofs[c]`'s low word, then the column's posts (topdelta, length, the post's offset) into a card buffer of 16 posts (more in a second call), one window | median 70, at most 334 columns: 0.3-1.7 ms |
| A clip against a drawseg | `far_open` (card; as built `far_get`): the run r1..r2 of the drawseg's `sprtopclip` or `sprbottomclip` from aux 0 `openings` into `CLIPBUF`, one window (the markers `$7FFF`, `$7FFE` are constants: no window; as built, no window either when no column of the run is still unclipped) | a few µs a pair |
| A side test | `FAR_GET` the seg's two vertices from `LVSEG` (8 of 24 B) | a few a sprite |
| A masked range | its columns' openings, low bytes (aux 0) and high (`OPENHI`), into `MTCLO`/`MTCHI`, two windows; its two clip runs, `sprbottomclip` into `CLIPBUF` and `sprtopclip` into `MCCLIP` (`SOLIDCOL`), by `far_open`, two windows (none for a marker run); the drawn marks written back the same way; each column's step from `FSTEP` (2 B, one window; as built two, a byte from each plane) or `recip` | rare: 0-3 drawsegs a frame |

The loops that run inside a read window are card code (`MEMORY_MAP.md`
rule 5): `far_posts`, `far_open` and a generic aux-0-to-main copy, about
200 B together [A], in card bank 1's 382 free bytes. (As built: only
`far_posts`; the far layer's `far_get` reads aux 0 and `RENDB` runs.)

### 3.6 Zero page and stack

The masked phase owns overlay 1 (`$18-$41`) and overlay 2 (`$48-$AF`),
free once the walk ends (`RENDER.md` 3.3). About 90 bytes are needed
[A]: `R_DrawSprite`'s state (about 20, live across `nm_vis` and
`nm_mwall`), the larger of `R_DrawVisSprite`'s (about 60: upstream's
`V_*` names on WPAGE [R `wpage.inc:103-137`]) and `mwCols`' (about 40
[R `r_frame65.s:1134-1164`]), the batch's pointer and count. (As built:
the draw phase's own allocation over the projection's, `rlayout.OVD1`
36 B of overlay 1 and `OVD2` 87 B of overlay 2, `$18-$3B` and
`$48-$9E`; nothing in the spill.) `rlayout.py`
assigns them and fails past `$AF`; the spill `$0280-$02FF` takes the
cold rest. After the masked phase the bucket pass takes overlay 1 and
`$70-$AF` for its batch list and pointers (1.10), which the replay
(`$48-$6F`) leaves alone. The math block `$B0-$D7` and the IRQ's `$D8-$FF` are as
before.

Stack: `nm_masked` → `nm_drawsprite` → `nm_mwall` → math: five levels,
about 30 bytes [A], within the render budget of 112 with the IRQ's 24
(`RENDER.md` 3.3); `--lowest-s-in` measures it on every frame.

### 3.7 Size budgets

Native bytes from upstream's executed full-view bytes times the
measured expansion (1.8 for 16-bit code [M: `memory` 2.2]) [A]:

| Part | Budget | Image |
| --- | ---: | --- |
| `nm_project` (with the G parts, `labsTZ`, `k1Wide`, the colormap) | 2,000 | masked |
| `nm_sort`, `drawMasked`'s loops, the drawseg copy | 450 | masked |
| `nm_drawsprite`, `nm_ptseg` | 1,600 | masked |
| `nm_vis` (setup, `visCol`, `visPost`, `visFill`, `wclipSprite`) | 1,500 | masked |
| `nm_vismag` | 1,200 | masked |
| `nm_fuzz` | 600 | masked |
| `nm_mwall` (with `smul48`, `lineFlags`, `higher`, `lower`) | 2,300 | masked |
| `nm_psp` (`psSetup`, `pspSprite`, `wdDraw`, `wpStart`, `wdProf`, the fallback to `nm_vis`) | 1,400 | masked |
| `rrec.s`, `nr_walllight`'s copy | 600 | masked |
| `MATHW` subset and `auxlc.s` subset (as built: none, the whole of both shared with the front end at `$6000`, 1.10) | 900 | masked |
| Constants (`SFIRST`, `CMOP`, `SMAP`, `PGT`, `bitOf`) | 350 | masked |
| **Masked image** | **12,900** of 15,360 (`$6000-$9BFF`); as built, 12,000 without the math of 13,312 (`$6800-$9BFF`) | |
| `nw_clip` (`psSetup`, `pspSprite`, `wpCheck`, `wpStart`, `wcProf`, the unit-scale clip loop with `wclipSprite`) | 1,300 | front end |
| `SPRSEC` append, `rec_room`'s page model, `nr_wskip` on the 11-byte `FRVIS` | 250 | front end |
| **Front-end image** | **17,160** of 20,416: 15,612 [M: M7] + 1,550 | |
| Card bank 1: `far_posts`, `far_open`, the aux-0 copy, the loader's bank argument | 200 of 382 free | card |
| Card `$F900-$FEFF`: `nb_bucket` (chunk copy, two walks, fuzz marks) | not estimated: stage A's prototype measures it (5.1) against the 371 B free | card |
| Frame block, render inputs | 95 of 96, 43 of 48 | main |

`render.cfg` (the masked image is its `WM` area, `%O.wm`; stage A kept one link configuration, so no `mask.cfg`) fails the link on any overflow. What gives
first is risk 1 (section 7).

### 3.8 Self-modifying code

None is planned in the masked image: upstream's patches there are
65816-specific (`K3FIX`, `K2FIX`, the sign branches of `prFrame`
[R `r_thing65.s:1096-1189`, `:1304-1319`]; `mwS2a`/`mwS2b` skip a
product when s2 = 0 [R `r_frame65.s:1451-1468`]; the `R_DrawSprite`
compare operands [R `r_sprite65.s:1484-1525`]). Natively they are
branches or zero-page operands. If a builder adds a patch, `RENDER.md`
3.7's rule holds: set before each use, listed, allowed by the write log.

## 4. The harness

### 4.1 Captures

`rendercap.py` gains points; each is a ref816 `--dump-at` point, bounded
as milestone 7's (`--dump-limit`, `--dump-max`, a cycle limit, `nice -n
10`, at most two runs):

| Point | Where | Ranges | Use |
| --- | --- | --- | --- |
| P0 (extended) | `R_FillStamps` | milestone 7's, and `$22:7800-$78DB` (`SPRBOUND`), the player | input |
| P1 | `weaponClipSame + 3` | milestone 7's (`floorclip`, `FR_VIS`, `MM_WPOK`) | input (A, B), truth of the clip pass (C) |
| P3 | `drawMasked` | milestone 7's, and `vissprites`, `num_vissprite` (bank `$02`) | truth: front end, vissprites |
| **P3s** | `drawMasked + 3` (after `jsr sortSkip` [R `r_frame65.s:182`]) | `FR_ORDER`, `FR_SKIP`, `$00:0AB0` (`W_WSK`) | truth: the sort |
| **P3w** | `playerSkip` [R `r_frame65.s:947`] | bank `$1D`, `COLW`, `XPNEXT`, `$23:EF00-$FAFF` | truth of checkpoint B (the records before the weapon's) |
| P2 | `drawAllL` | milestone 7's, and `$E1:2000-$9FFF` | early flushes, now over the whole frame; the first one's screen: input (2.3 item 4) |
| **PS** | `stripEarly` (`d_main65.s:499`, the render's end) | `$E1:2000-$9FFF` | input: which screen bytes the flushes wrote (2.3 item 4) |
| **P4** | `R_DrawLists` (`d_main65.s:502`) | bank `$1D`, `COLW`, `XPNEXT`, `$23:EF00-$FAFF`, `$0A:C500-$C8FF`, `FZ_POS`, `$E1:2000-$9FFF` | truth: records, ranges, spans, weapon skip; input: the screen |
| **P5** | `R_DrawLists`' return (`d_main65.s:502` + 4) | `$E1:2000-$9FFF` | truth: the SHR |
| Call log | `R_DrawVisSprite` (in: `_Dp`, `VS_CLIP`, `mfloorclip`, `mceilingclip`, `floorclip:320`, `ceilingclip:320`), `R_AddSprites` (in: `_Dp+4` the sector, C the light), `R_RenderMaskedSegRange` (in: `FR_DS`, C, `_Dp+4`), `wdProf`, `wcProf`, `R_DrawVisSprite` from `wcDraw3`/`wdDraw` (the weapon's path), and the path labels of the coverage report | truth of the clip log; the listed sectors; the paths |

**Frame sets.** Milestone 7's 188 frames (`m5`, `newgame`, `title`,
`tour`, `lights`, 11 synthetic), captured again with the new points,
and **`demo3`**: every frame of the title loop's demo3, from the note
`demo` to `demo-end` of `lumps.py demo_script(7)` (`RENDER.md` 4.1),
533 frames [M: M7's evenly chosen `title` frames have indexes 0-532].
ref816 takes at most 64 points, and every frame of a consecutive run is
one range per point, so one capture run holds them.

**Coverage.** `rendercap.py`'s report lists, per set, what the frames
reach (from the call log's paths and the dumps): fractional things
(`gGZ`), close things (`labsTZ`), `wHi` (xscale ≥ 1.0), the `FixedMul`
fallbacks of `x1`/`x2` [R `r_thing65.s:449-485`], flips, `x1 < 0`,
rotations, full bright, fixed colormaps, shadows, the `MAXVISSPRITES`
cut, ties in the sort, magnified runs, `wclipSprite`, `dsVisible`'s
three exits [R `r_sprite65.s:481-561`], each silhouette clip, side
tests, masked ranges from `R_DrawSprite` and from the drawseg loop, one
and two lights, `K_TEXC`, `FSTEP` and `recip` steps, the weapon's four
paths (profile clip and draw, `R_DrawVisSprite` clip and draw), the
weapon skip with `wclipSprite`, a flash, the shadow weapon, `UPOFS`
wrapping to an extra page before a masked post. A path with no frame
gets a synthetic frame (`framesynth.py`, milestone 7's method: a
captured frame's `R_FillStamps` recorded whole, pokes, `--call` to each
point):

| Synthetic | Pokes | Reaches |
| --- | --- | --- |
| `spectre` | a thing on a `tour` frame given `MF_SHADOW` (a spectre in E1M7 is legal) | shadows over walls and sprites, `FZ_POS`, `sortSkip` with a skip |
| `invis` | `powers[pw_invisibility]` set | the shadow weapon (no clip pass) |
| `close` | the player moved next to a monster | magnified sprites, `labsTZ`, `wHi`, `x1 < 0` |
| `crowd` | 90 things placed in the view's sectors | the `MAXVISSPRITES` cut, the sort with many ties |
| `mwlong` | a `tour` frame with a masked wall, its column lists lengthened by walls behind (moved sectors) | `K_TEXC` / `K_TEX` at a page's end, an extra page |
| `mwclose` | a masked wall at a scale of 1.0 or more | `recip` steps, two lights |
| `flash` | psprite 1 given a flash state | the flash, no weapon skip |
| `skipwall` | two frames: the weapon unchanged, then a sprite crossing its rows | `W_WSK`, `wclipSprite` |
| `pagefull` | enough records to exhaust the 50 extra pages, with a thing given `MF_SHADOW` whose records come before the flush | a modelled flush (`UPFLUSH`) against `ref816`'s P2; the input screen's composition (2.3 item 4) with a pre-flush shadow |

**Routine captures** (stage B, `routinecap.py`'s method): for
`R_DrawSprite`, `R_DrawVisSprite` and `R_RenderMaskedSegRange`, a dump
at entry and at return of each call of **milestone 7's 188 frames**
(every call there: about 7-10 vissprites a frame [M: survey, 1.2], each
an `R_DrawSprite` and an `R_DrawVisSprite` call, and every masked
range), the frame's P0 for the level, and the synthetic cases. About 20
KB a case compressed [A], about 3,000 cases: 60 MB [A]. demo3's 533
frames are not routine-captured (every call of 721 frames would be
about 14,000 cases, 4 to 5 times the time and disk); frame mode checks
them whole, and the clip log checks each of their sprite calls (4.2).

### 4.2 Native runs

As milestone 7 (`RENDER.md` 4.2): two runs a frame with every
undefined byte `$A5`, then `$5A`; `--core w65c02s`; the write log of
every storage but the stack page, and of the soft switches, filtered by
the writing PC against `rlayout.py`'s allowed set (now also the masked
image, the card loops, the bucket pass, the replay's set of
`MEMORY_MAP.md` rule 6); `--lowest-s-in`; the mouse card's VBL interrupt
with the stub handler and `--speed 1` (a frame with no interrupt taken
fails); snapshot events at the walk's end (milestone 7's outputs), at
the projection's end, after the sort, before the weapon, after the
masked phase, after each bucket pass, at the end.

**The clip log** (test builds, `-D CLIPLOG`): each `nm_vis` call writes
the vissprite's index (2 bytes; `$FFxx` for the weapon's draw, psprite
xx) and all of `FLOORCLIP` and `CEILCLIP` (the columns past `x2`
included: `R_DrawVisSprite` can draw there, 0.3) into the `SEAM` bank
from `$1400` (`SEAM_CLIPLOG`), 322 bytes a call: at most 80 sprites and
the weapon's draw of psprites 0 and 1 by `R_DrawVisSprite`, 82 calls,
26,404 B to `$7B24`. `rlayout.py` asserts `SEAM_CLIPLOG + 322 ×
(MAXVISSPRITES + 2) ≤ BANK_ROOM`'s end; `$1400` is `SEAM_SOLID`, the
walk's lockstep data (`rlayout.py:59`), so `render.mk` refuses a build
with both `CLIPLOG` and `LOCKSTEP`.

**Pairing.** ref816 also calls `R_DrawVisSprite` for the weapon's clip
pass, from `wcDraw3` when the lump has no profile
[R `r_sprite65.s:799-826`]; natively that pass is `nw_clip` in the
front-end image (stage C) or the seam (A, B), not `nm_vis`. The call
log records `VS_CLIP` at entry; `rcanon.py` drops the calls with
`VS_CLIP` ≠ 0 (the clip pass: checked instead by `floorclip` and
`FR_VIS` at P1) and pairs the rest in order with the clip log's
entries, checking for each pair the vissprite's identity (thing slot
and lump, or the psprite) and both clip arrays; a count that differs
names the first call without a partner.

**The poisoned screen.** On a subset, the 15 `m5` frames and every tenth
`demo3` frame (69 frames), a third run starts from a screen whose view
rows are a pattern, with the truth from `ref816 --call R_DrawLists` on
the P4 state with the same screen (milestone 5's `replay_check.py`
method). The captured screen already holds most of the answer (fill
rows skipped because the frame before painted them); the pattern shows
that every byte upstream writes is written.

### 4.3 Comparisons (`rcanon.py`)

Section 2.4's outputs in one canonical form; the diff is exact. A frame
whose `RULES` is not 0 is skipped and reported as `rules N: a known
divergence (NATIVE.md 15.1 row 13)`, listed by name in every report and
never counted as equal. The bucket pass is also checked on its own: its W
batches, walked by `COLLO`/`COLHI`, must give each column's staged
records in order, each covered range's W address must name the record
whose `RECSEQ` was set, and its `K_FUZZNOW` marks must equal
`loader.mark_fuzz` on the same records.

### 4.4 Timing and FPS

The profiling builds mark each phase of 3.2 (`$0300`, 2 × n as
milestone 7 does), new numbers for the new phases: 13 the masked
window, 14 the drawseg copy, 11 the projection (upstream's number), 15
the sort, 4 the sprites and masked walls (upstream's), 16 the weapon, 17
the clip pass, 18 the bucket pass, 12 the replay (upstream's). For every
frame of acceptance 1, `f121` and `fastpath`: ms per phase, 65C02
cycles, soft-switch accesses, windows, records and bytes staged, batches
and strips, lowest S. `build/native/render/report8.md`: per set the
median and range beside section 6.2's estimates and `NATIVE.md` 1.2.

**FPS by VBL count.** `rdisk.py --check` runs the disk image (4.6) on
a2vm on the model's clock (`--cost-timed`) under `f121` and under
`fastpath`; the runner counts the mouse card's VBL interrupts over the
100 frames' rendering (phases 1-13, not the loads between frames), and
prints the VBLs, the frames and the FPS (50 Hz; NTSC × 60 / 50). It is
render-only: the report adds `NATIVE.md` 6's tic estimate, labelled
[A], for the comparison with the 6 FPS minimum, until milestone 10
measures the tics.

### 4.5 Resources for 534+ frames

Before each run the tool prints its estimate (frames × the seconds a
frame of its first five), checks `df -h /System/Volumes/Data` (stops
below 20 GB), and runs at most two processes, each under `nice -n 10`
with a time limit and every output with a size limit; temporary
directories `build/tmp-m8-*` are deleted at the end.

| Run | Volume | Time, estimated | Output kept |
| --- | --- | --- | --- |
| Capture, `demo3` | one choose run and one capture run of the title loop to demo3's end | 2 × 8 min [A: 446 s for that run with a call log, M: `build/ref816/divscan/report.json`] | 533 frames × about 315 KB compressed (P0 76, P0b 30, P1 29, P3 80 [M: M7 frame directories], P3s 5, P3w 60, PS 15, P4 60, P5 15 [A]): 170 MB |
| Capture again, milestone 7's 188 frames with the new points | five runs as milestone 7's | 5 min [A: M7 "~1 min" for 177 frames, with more points] | 188 × 220 KB [A]: 40 MB more |
| Routine captures | milestone 7's 188 frames: a survey and a dump run a script | 10 min [A] | 60 MB [A] |
| Level conversions with the patch store | 17 level sources | 2 min [A] | 17 × about 0.7 MB [A: 1.2]: 12 MB |
| Frame mode, both fills | 721 frames × 2 = 1,442 a2vm runs; write logs up to 2,000,000 lines each, deleted once filtered | about 0.6 s a run [A: milestone 7's 0.24 s for the front end, M7 "~90 s" for 376 runs, × 2.5 for the masked phase and the replay]: 15 min, 7-8 min at 2 jobs | reports |
| Poisoned screen | 69 frames: a `ref816 --call` and an a2vm run each | about 15 s a frame [A]: 9 min at 2 jobs | reports |
| Timing | 721 frames, one run each, the model's clock | about 1 s a run [A]: 6 min at 2 jobs | `report8.md` |
| Routine mode | about 3,000 cases (the 188 frames and the synthetic ones) × 2 fills | 10 min [A] | reports |
| The bucket prototype (stage A) | milestone 7's 188 frames' staging, one a2vm run each on the model's clock | 3 min [A] | a table in the stage's results |
| The disk image and its a2vm runs | 100 frames, two modes, two profiles | 6 min [A] | `build/native/RENDER.hdv`, about 7 MB with the full files [A] |
| **All** | | **about 1 hour at 2 jobs** | **under 0.6 GB** of `build/` |

The poisoned fills: every frame twice ($A5 and $5A for every undefined
byte), 1,442 runs; the poisoned screen: 69 frames once more each.

### 4.6 The disk image (acceptance 2)

`rdisk.py` builds `build/native/RENDER.hdv`, a ProDOS volume made as
milestone 5's `disk.py` makes `REPLAY.hdv`:

(As built in stage C: not one file a frame read between frames, since
the runner gives ProDOS up to own the language card. `RENDER.SYSTEM`
reads three data files at boot, `CATALOG`, `LEVEL` and `FRAMES`, into
RamWorks, then runs from the card; each frame's chained and full data
are run-length coded records in 69 store banks (3.35 MB for 100
frames), applied from there. The chained data hold the game's bytes
that changed since the frame before plus every game byte the renderer
may write (rlayout's allowed sets: the sectors' validcount stamps).
The static tables go in by one PRIVATE request. "Stage C as built".)

- `RENDER.SYSTEM` (`src/native/rrunner.s`): under ProDOS it loads the
  level (E1M7's conversion of the demo's last texture conversion in the
  window: `LVSEG`, `LVMAP`, texels, sky, patch store, `SPRT`, `WPRO`,
  `FSTEP`, `RECIP_TABLE`, `MATH.md`'s tables), both W images, the aux
  card's tables, the colormaps and the card code into RamWorks, main,
  the aux card and the language card, then gives ProDOS up (as
  `runner.s`);
- `CATALOG` and one file a frame for 100 **consecutive** demo3 frames:
  the window of 100 with the most sprite columns and shadows, with no
  frame whose `RULES` is not 0 and no frame with an early flush (P2)
  (chosen by `rdisk.py` from the captures, reported);
- a frame's **chained** file: the game state that changed since the
  frame before (render inputs, the sectors' and sides' dynamic fields,
  `VALIDCOUNT` with every sector's stamp on every frame (2.3 item 5: the
  tics raise `validcount` about 23 a tic, so a counter left to the
  renderer's + 1 a frame could equal a stale stamp and skip that
  sector's things), `TEXTRANS`, `RTHING` records, `SPRBOUND` once), the
  display's `W_FSG`/`W_FSW`, and the **screen patch**: the bytes where
  the frame's input screen (2.3 item 4, composed from P2, PS and P4)
  differs from `ref816`'s screen at the frame before's P5 (the status
  bar, the message strip, the colours), and the expected CRC-32 of aux 0
  `$2000-$9FFF`: `ref816`'s at P5;
- a frame's **full** file: everything `framestate.py` injects for that
  frame (2.3), the renderer's persistent state and the whole input
  screen included, so the frame does not depend on the one before.

**Two modes.** Chained (the default, and acceptance 2 as this design
reads it): the renderer's own persistent state (spans and stamps, the
weapon skip, the vertex cache, `rw_scalestep`, `FZPOS`) is **not**
injected after the first frame; it carries from frame to frame as it
will in the game, so the chain tests it too, but one wrong frame spoils
every later CRC. Full (a key selects it): each frame from its full file,
as acceptance 2's words "from injected states" say, which tells a frame
that is itself wrong from one that inherits a wrong state. The owner is
told of the difference (section 7); both modes must pass. For each
frame the runner applies the file (main by CPU, RamWorks through
windows, aux 0 by CPU with `RAMWRT` on, then waits for the drain), runs
phases 1-13 counting VBLs, takes the CRC and shows the frame; at the end
a table (each frame's CRC, OK or not, VBLs) and the total FPS; a key
runs it again. The memory API is used only as milestone 5's runner does
(PRIVATE copies into write-expensive pages; `MEMORY_MAP.md` rules 3, 4,
8).

`rdisk.py --check` runs the image end to end on a2vm (its MLI trap and
memory API) under `f121` and `fastpath`, in both modes, and fails unless every CRC
equals `ref816`'s, the first load passes milestone 5's checks (no video
write outside the screen, `$0878-$087F` untouched), every interrupt
keeps the IRQ contract (`--irq-bounds`), and the VBL counts are printed.
The owner runs the same image on the card at milestone 12; its CRCs
must equal a2vm's.

### 4.7 Unit tests and planted bugs

`tests/test_native_masked.py` (A, B) and `tests/test_native_frame8.py`
(C) skip, naming what to run, when `build/` lacks the captures, a2vm,
ref816 or cc65, and run a sample within `tests/support.run`'s bounds
(300 s, 256 MB): the converter on E1M7, the vissprites on 3 frames,
records on 3 frames and 20 routine cases, the whole frame on `still-1`,
`demo-10`, one `demo3` frame with a shadow, `synth-mwlong` and
`synth-pagefull`, and the disk image's a2vm run on its first 3 frames in
both modes. Each stage plants bugs in a
scratch copy and shows a check fails:

| Stage | Planted bug | Caught by |
| --- | --- | --- |
| A | a fractional thing's G parts by `FixedMul` for `qmulh` | vissprites (x1, x2, scale) |
| A | the rotation's `+ $9000` as `+ $8000` | vissprites (lump) |
| A | a flip ignored | vissprites (startfrac, xiscale) |
| A | `nm_project`'s early rejection reading E / 2 + 2 for E (milestone 8 injects `SPRBOUND` and builds nothing that computes it: the planted bug of its computation, "made by the converter for a sprite the first level lacked", is milestone 11's) | vissprites of `synth-close` and of a `tour` frame with a thing just off the side |
| A | the sort's ties swapped | the order (P3s) |
| A | `MAXVISSPRITES` 79 | `synth-crowd`'s vissprites |
| A | `CMOP` one page off | vissprites (colormap) |
| A | `sortSkip` blind to shadows | `FR_SKIP`, `W_WSK` (`synth-spectre`) |
| A | a sector listed twice in `SPRSEC` | vissprites (count) |
| B | drawsegs scanned first to last | records, clip log |
| B | the C code's -2 for "clip not set" | clip log |
| B | the side test's sign flipped | clip log, records |
| B | `visCol` stopping at `x2` | records (the column past `x2`) |
| B | `YHTAB` from E for E - 1 | records' rows |
| B | a magnified run ignoring its clips | records |
| B | `FZ_POS` not kept | `FZPOS`, `K_FUZZ` positions |
| B | `UPOFS` one byte off | `UPOFS` against `COLW`; `synth-mwlong`'s kinds |
| B | the modelled flush not resetting `UPOFS` and `XPUSED` | `synth-pagefull`'s `UPOFS`, `XPUSED` and kinds after the flush |
| B | a masked range clipped by `sprbottomclip` alone (`MCCLIP` not read) | records of `synth-mwclose` and the `tour` masked ranges |
| B | `CVSET`'s test `≥` for `>` | covered ranges |
| B | `FSCUT` missing for sprites | spans |
| B | a masked column drawn twice | records |
| B | one light for a two-light masked range | records' pages |
| C | `wdProf`'s order as `visPost`'s | records' order |
| C | `wclipSprite` missing | records (`synth-skipwall`) |
| C | the flash not drawn | records (`synth-flash`) |
| C | the clip pass's run start one row low | `floorclip` at P1, records |
| C | the bucket pass: a covered range's W address one record off | the bucket check, SHR writes against the model |
| C | the bucket pass: `K_FUZZNOW` marks missing | the marks against `mark_fuzz`, SHR |
| C | a batch split inside a column | the bucket check |
| C | the bucket pass dropping the record cut by a chunk's end | the bucket check (every frame over 180 B staged has one) |
| C | the psprite's `sy` as 16 bits | records' `R_TF` and `WPREV` on demo3's bobbing frames |
| C | the input screen taken from P4 whole on a flush frame | SHR of `synth-pagefull` (a pre-flush shadow applied twice) |
| C | the runner's screen patch one byte off | the disk image's CRC |
| C | a store into the masked image's code | the write log |

## 5. Build stages

Three builders, in order; each stage ends with its checkpoint passing,
no build warning, the whole test suite green, milestone 7's acceptance
still passing, a results section in `src/native/README.md`, the `build/`
growth reported, and the stage's regions recorded in `MEMORY_MAP.md` (a
new section 13). The split is the task's with the changes of section 0.3:
the projection moves into the masked image, and the page model joins
stage B.

### 5.1 Stage A: sprite data, projection, vissprites, sort

**Owns:** 1.3-1.8 and 1.10-1.11 in `levelconv.py`, `rtables.py`,
`rlayout.py`, `framestate.py`; `rendercap.py`'s new points and the
`demo3` set (captured now: B and C need them); vissprites and the order
in `rcanon.py`; `rbsp.s`'s `SPRSEC` append; `mproj.s`; `mmain.s`'s
skeleton (window load, drawseg copy, projection, sort, then return);
`far.s`'s loader with a bank argument; `mask.cfg`; the `synth-spectre`,
`crowd`, `close` frames; **the bucket pass's prototype** (3.4): the
chunk copy, both walks and the fuzz marks, run on a2vm over the
staging of milestone 7's 188 frames (the front end's records, which
exist now), checked against `loader.py`'s bucketing and `mark_fuzz` on
the same records, its code size and its time per staged byte measured
under `f121` and `fastpath`. The measurements replace 3.7's and 6.2's
bucket figures in this file before stage B starts; if the code does not
fit the card's 371 bytes, risk 2's fallbacks are chosen then.

**Delivers to B:** the masked image and its loader call, the vissprites
and `FRORD` in W, the drawseg copy, the render things, the `demo3`
captures, the patch store.

**Checkpoint A:**

1. `levelconv.py` on the 17 level sources: every check of 1.11;
   `rtables.py`: every check of 1.6; the overrun of 1.3 measured.
2. On milestone 7's 188 frames and the 533 `demo3` frames, both fills:
   the vissprites at the projection's end equal P3's (count, order,
   every field of 2.4), the order, `FR_SKIP` and `W_WSK` after the sort
   equal P3s's, the listed sectors equal the call log's `R_AddSprites`
   calls, milestone 7's outputs at the walk's end still equal P3's, no
   stray write.
3. The bucket prototype: on the 188 frames, W's records by column,
   `COLLO`/`COLHI` and the `K_FUZZNOW` marks equal `loader.py`'s; its
   size and ms per frame reported, 6.2's row updated.

### 5.2 Stage B: the masked phase

**Owns:** `msprite.s`, `mvis.s`, `mwall.s`, `mmain.s`'s loops, the page
model in `rrec.s` (both images), the card's `far_posts` and `far_open`,
the covered ranges and `FSCUT` of the masked producers, routine mode for
the three routines, the clip log, the synthetic frames `mwlong`,
`mwclose`, `pagefull`.

**Delivers to C:** every masked record but the weapon's, the staging
with `RECSEQ` and `CVREC`, `UPOFS`.

**Checkpoint B:**

1. Routine mode: every captured call of `R_DrawSprite`,
   `R_DrawVisSprite` and `R_RenderMaskedSegRange` and the synthetic
   cases equal (records appended, clips, clip log, `FZ_POS`, spans,
   ranges), both fills.
2. On the 188 and 533 frames, both fills: the records to the weapon's
   draw equal P3w's by column, `UPOFS` and `XPUSED` equal P3w's `COLW`
   and `XPNEXT`, the covered ranges and spans equal P3w's, the clip log
   pairs with the call log (4.2), no stray write; milestone 7's frame
   mode passes again with the page model.
3. **The page model on frames that use it**, required: no captured
   list passes 139 of 254 bytes [M: `RENDER.md` "What stage C changed, and why"],
   so on the captured frames `UPOFS` against `COLW` checks only sums.
   `synth-mwlong` (a `K_TEXC` refused at a page's end, an extra page
   taken) and `synth-pagefull` (every extra page taken, a modelled
   flush) equal `ref816`'s records, kinds, `COLW`, `XPNEXT` and the
   P2 flushes, both fills; the planted bug "the flush does not reset
   `UPOFS`/`XPUSED`" (4.7) fails `synth-pagefull`.

### 5.3 Stage C: the weapon, the bucket, the replay, the whole frame

**Owns:** `wclip.s`, `mpsp.s`, the converter's profiles (1.5),
`FRVIS`/`WPREV` native, `nr_wskip` on them (the seam goes), `bucket.s`
(finished from stage A's prototype),
the whole-frame driver, the `ST_RECORDS` policy (6.1), frame mode to the
SHR, the poisoned screen, `rdisk.py` and `rrunner.s`, the timing report,
the synthetic frames `invis`, `flash`, `skipwall`.

**Checkpoint C = acceptance 1 and 2, and the report:**

1. On milestone 7's 188 frames and the 533 `demo3` frames, both fills:
   every output of 2.4 equal (the record stream, all of aux
   `$2000-$9FFF`, ranges, spans, the page model, weapon skip, `FZPOS`),
   `floorclip` and `FRVIS` after the clip pass equal P1's, the bucket
   check of 4.3, 0 stray writes, stack within budget; the 69 poisoned
   screens equal their `--call` truth. Every frame whose `RULES` is not
   0 skipped and listed by name (none is expected: no captured frame
   takes a rule [M: M7]); every frame whose input screen needed 2.3
   item 4's composition listed with its flush count.
2. `rdisk.py --check`: every CRC of the 100 frames equal to `ref816`'s
   on a2vm, chained and fully injected, under `f121` and `fastpath`, the
   VBL counts printed.
3. `report8.md` (4.4): time per phase and FPS by VBL count under both
   profiles against section 6.2, `NATIVE.md` 1.2 and 6 FPS.

## 6. Decisions

### 6.1 When the record staging and spill are full (`ST_RECORDS`)

**Decision.**

1. **Size.** The spill grows from 2 to 4 banks (51-54): aux 0's 8 KB
   and 194,560 B. The largest measured frame staged 11,052 B for the
   front end [M: M7]; with sprites, the heaviest `title` frame's 334
   sprite columns at 1.65 posts a column and 12 bytes a record add
   about 6.6 KB [A on M]. `rlayout.py` asserts the capacity is at least
   8 times the largest frame measured in acceptance 1, which reports
   that figure. *Restated 2026-10-01 (verification of stage C, defect
   4):* at least 8 times the largest staging of acceptance 1's
   **captured** frames, which `frame8.py` measures on every run and
   fails under (`rlayout.STAGING_MARGIN`, no hand-entered figure); the
   synthetic frames are extremes made to take every extra page and a
   flush of upstream's lists (`synth-pagefull` 26,089 B, 7.8 times) and
   must only fit. The owner may prefer a fifth spill bank instead (it
   would also raise the batch bound, 3.4).
2. **Test and lockstep builds** keep today's stop: `STATUS` =
   `ST_RECORDS` and `BRK`, so the harness fails the frame.
3. **The game (release build)** never stops: when a batch finds the
   staging full, `rec_flush` drops it and every later one (the sticky
   flag `RECDROP`, 1.10), producers stop setting covered ranges, the
   bucket pass clears the ranges whose sequence number is at or past
   the last record staged (3.4), the frame completes and
   is replayed with what was staged, `STATUS` = `ST_RECORDS`, and the
   display (milestone 11) treats the frame as not shown (`W_FSG` = 0),
   so the next frame reuses no fill row (with `W_FSW` = 0, `W_FSP` takes
   the frame's own stamp and no span of the frame before counts
   [R `r_list65.s:153-194`; `src/native/README.md` "Verification
   (checkpoint C)": `W_FSP` = `W_FSC`]) and no weapon rows
   (`weaponClipSame` needs `W_FSW` [R `r_frame65.s:910-912`]): the
   glitch lasts one frame. The flag is `STATUS` only, never `RULES`:
   no lockstep comparison meets such a frame, because lockstep builds
   stop at it (item 2).

**Why not upstream's early replay.** Upstream draws all lists when its
pages run out and goes on [R `r_list65.s:272-323`]. On F1.2.1 the
replay's record buffer and texel stage are W `$6000-$BFFF`
(`MEMORY_MAP.md` 8), which holds the running phase's code and, in the
front end, the BSP's node frames and wall scratch (`RENDER.md` 3.4) and,
in the masked phase, the vissprites and `YHTAB`: an early replay would
have to save that state, reload the image afterwards and resume only at
points where no code patch or recursion is live. That is a lot of
machinery for a case no frame reaches, where 194 KB of spill is about
10 times the heaviest frame estimated. If the owner prefers upstream's
behaviour, the phase boundary (after the walk, before the masked
image's load, when W holds nothing live) is the one cheap place to add
an early replay later: it draws the front end's records, and the pixels
equal (per-column order is kept; `NATIVE.md` 5.1).

The replay has a limit of its own: one column needing more than its 16
KB stage (over 125 texture records) stops it (`src/native/README.md`,
"Departures"). The bucket pass counts each column's texture records; in
the game a column past the limit keeps its first 125 and flags the frame
the same way; test and lockstep builds stop there as in item 2.

*As built (verification of stage C, 2026-10-01).* Both column limits
are in the game build, each where it is met: the bucket pass's (a
column's records past a batch's 8,192 bytes: walk 1 counts a column's
records until the first that would pass them and none after, marks the
column cut in `CVDONE` bit 7, and ends its batch with it; walk 2 leaves
out the records past the batch's end; a covered range whose record was
cut is cleared), and the replay's (a column alone past its stage: the
strip of that column is drawn with the records gathered before the
first that did not fit, at least its first 125 texture records, its
covered range cleared). Each sets `STATUS` = `ST_RECORDS`. The bucket
pass does not count texture records: the replay finds the cut itself.
Test and lockstep builds stop at both (`ST_BUCKET`, the replay's `BRK`).

### 6.2 Milestone 7's measured costs and the whole frame against 6 FPS

Milestone 7 measured its phases above the estimates in the demo: the
walk 3.82 ms (estimate 0.8-1.6), wall setup 2.98 (0.7-1.5), seg loops
7.18 (3.1-6.2), 19.97 ms with the window load against 10.8-18.3, up to
43.04; 3.1, 2.4 and 1.9 times upstream's cycles where `NATIVE.md` 1.2
assumed 1.37 [M: M7]. The new phases, on a2vm's F1.2.1 model, estimated
from upstream's cycles at milestone 7's measured rates (0.052-0.072 ms
per 1,000 upstream cycles for 16- and 32-bit code, the walk's and wall
setup's; 0.032-0.052 for per-column record making, the seg loops' and
wall setup's [A on M: 7.21 ms / 99,575, 5.99 / 115,381, 11.92 / 367,549
cycles, M7 and `RENDER.md` 4.4]):

| Phase, ms a frame | Still (E1M1) | Demo3 median | Demo3, each phase's worst | Label |
| --- | ---: | ---: | ---: | --- |
| Front end's window and front end | 29.82 | 19.97 | 43.04 | M: M7 |
| Masked window (about 13.4 KB at 0.25 µs/B) | 3.4 | 3.4 | 3.4 | A on M: 4.54 ms for 18,176 B, M7; stage A's image (13 pages) loads in 0.83 ms, the same rate [M: M8 A]; stage B's (29 pages, 7,425 B) in 1.96 ms [M: M8 B], so the whole image with stage C's weapon about 2.4 |
| Drawseg copy, `SPRSEC`, `SPRBOUND` (estimate 0.2, 0.2, 0.4) | 0.36 | 0.22 | 0.53 | M: M8 A (all 533 `demo3` frames) |
| Projection and sort (estimate 0.9-1.3, 0.6-0.9, 3.9-5.3 from upstream's 17,880 / 12,034 / 74,181 cycles) | 1.33 | 2.44 | 6.19 | M: M8 A (all 533 `demo3` frames; the `title` set's 50: 2.38, 5.35) |
| Sprites, masked walls, weapon (upstream 55,465 / 51,410 / 363,023) | 1.8-2.9 | 1.6-2.7 | 11.6-18.9 | A on M: PROFILE; stage B measures the sprites and masked walls without the weapon at 1.59, 2.55 and 17.34 (`still`, `demo3` median and worst) [M: M8 B] |
| Their column windows (3.5) | 0.2 | 0.35 | 1.7 | A on M: survey |
| Bucket pass (3.4), measured on stage A's prototype over each frame's whole staging (the front end's records and upstream's masked records): 1.37 µs a staged byte (1.26-1.77), batches 2 and 3 parked included; estimate 4.3-7.1, 3.1-5.1, 14.4-21.1 | 8.88 | 6.54 | 19.25 | M: M8 A (`bucketcheck.py --timing`: `still` 6,690 B; `title` median 4,818 B, worst 11,960 B, 2 batches). The estimate's basis, kept for the record: 0.6-1.0 µs a staged byte, and 0.5 µs a byte of each batch after the first; staged: 7.1, 5.1 and 16.8 KB (3 batches); A on M: the staging 6,342, 3,747 and 10,236 B (M7 `report.md`, `still` and `title`) plus 37, 70 and 334 sprite columns × 1.65 posts × 12 B; two bounce walks at `far_get`'s 13-15 cycles a byte, the scatter's copy and about 100 cycles a record, at 1.9-2.6 fabric clocks of 133.3 MHz a cycle; milestone 5's replay walk, 2-4 ms for 2.8-8.6 KB; parking at the phase loader's 0.25 µs a byte. Not the staging, which milestone 7's measured front end already pays |
| Replay | 17.09 | 31.65 | 34.06 | M: M5, the 11 `m5` demo frames (median, maximum) |
| **Render, from `R_FillStamps` to the last SHR write** | **63-64** | **66-67** | **120-127** | A on M (the first version: 58-62, 61-64, 113-128) |
| Render-only FPS | 15.6-15.9 | 14.9-15.1 | 7.9-8.3 | A |
| Tics at 4 a frame | 3.0-6.7 | 18.4-41.3 | 41.3 | A: `NATIVE.md` 6 |
| **Whole frame** (status bar, input and sound not counted: about 1-4% more [A: `NATIVE.md` 1.2]) | 66-71 ms, 14.1-15.2 FPS | 85-109 ms, 9.2-11.8 FPS | 161-168 ms, 5.9-6.2 FPS | A (the first version: 61-69, 79-106, 154-169 ms) |

Stage A (2026-09-30) replaced three rows with measurements on a2vm's
`f121` model ("Stage A as built" below). The bucket pass costs 1.3-2.1
times its estimate at the still and median frames and lies inside it in
the heavy column; the projection 1.0-4.0 times, more in demo3 than
standing still: each thing costs 0.19 ms (median a vissprite), most of
it the windows of 3.5 (a thing, its sector, its frame, its patch header
and its scale record, each fetched through the card). The heavy column
moves from 5.9-6.5 to 5.9-6.2 FPS: the bucket pass's heavy figure came
in under the estimate's top, the projection's over it. The still and median frames lose up to
1.4 FPS and stay well above 6. So the measurements do not by themselves
bring optimisations 4 and 10 before milestone 12, but the heaviest fight
now sits at 5.9-6.2 FPS, its margin over 6 at most 0.2: stage C's timing report over all 533
`demo3` frames decides (section 7).

Stage B (2026-09-30) measured two more rows ("Stage B as built"): the
masked window is 1.4 ms under its estimate; the sprites and masked
walls without the weapon lie inside their row's range at the still and
median frames, but `demo3`'s worst (17.34 ms, `demo3-114`) is already
near the top of 11.6-18.9 before the weapon is added, so the heavy
column may fall under 5.9 FPS. Stage C's weapon and whole-frame timing
over all 533 `demo3` frames decide; optimisations 4 and 10 stay the
candidates, with the magnified runs' windows (each run's posts are
fetched through the card) as a new one.

The first version of this table took the bucket pass from
`MEMORY_MAP.md` 9's row, which also counts the staging, and its heavy
column's total (102-115) was above its own rows' sum (102.1-110.8); both
are corrected here ("Review", finding 1).

`NATIVE.md` 1.1 estimated 36-75 ms still and 61-127 ms in the demo on
F1.2.1; the still and median figures fall inside, the heavy column just
past its slow end. The heavy column adds every phase's worst, which no
single frame need reach (the largest front-end staging and the most
sprite columns are not the same frame), and the demo frames milestone 5
timed are not demo3's heaviest (its last frames are a close fight [R
`research/native-modules.md` 3.4]): stage C measures every demo3 frame.
**Against 6 FPS:** above it at the still and median frames; in the
heaviest fight 5.9-6.2 FPS with stage A's measurements (5.9-6.5 by
the first estimate), below the minimum at the upper estimate.
The bucket pass was the least certain row (7 ms of the heavy column's
width), so stage A measured it first (5.1, and the rows above); if the heavy frames then
sit near 6 FPS, optimisations 4 and 10 below, which touch the bucket
pass and the replay, come before milestone 12 (an open point for
the owner, section 7).

**Optimisations that keep exactness, for a later pass (not now):**

| # | Where | What | Saves, F1.2.1 [A] |
| --: | --- | --- | --- |
| 1 | Window loads | Reload only the pages the tic window overwrote (both images are the same bytes each frame); share the two images' common pages (`MATHW`, `rrec.s`, constants) at one address | 2-5 ms |
| 2 | Walk | Cache the box corners' angles as the vertex angles are (`RENDER.md` "Stage A as built": `pta16` of the corners 1.3-2.8 ms of the walk) | 1-2.5 ms |
| 3 | Walk, wall setup | Node records trimmed to the 24 bytes read; side and back sector fetched with the seg batch; drawsegs written in one window per batch of walls | 1-2 ms |
| 4 | Bucket pass and replay | The bucket pass already walks every record: let it make the replay's stage plan (the gather's walk, 2-4 ms, `src/native/README.md` "Results"), and copy texel groups a strip at a time | 2-4 ms |
| 5 | Replay | Draw the fill records' rows in page order within a strip (the coalescer's page scan, `docs/results/fuzz-timing-2026-09-30.md`) | not estimated |
| 6 | Projection | One window a sector chain for its things (a card gather) | 0.1-0.5 ms |
| 7 | Masked phase | Keep each drawseg's seg vertices in the drawseg copy (its spare byte is not enough: a 40-byte copy) | side tests' windows |
| 8 | Weapon | The profile's records made once per lump and position, reused while `FRVIS` is unchanged (the weapon skip frames already skip most rows) | 0.5-1 ms |
| 9 | Seg loops | `RENDER.md` risk 2's fallbacks: `FSTEP` gathered by bank | 0.5-1 ms |
| 10 | Bucket pass | The producers keep each column's byte count (`rec_room` knows both), so walk 1 goes; it needs 320 B of main during the render, which the map has not found | about a third of the pass: 1-2 ms median, 3-5 ms heavy |

Faster, inexact arithmetic stays out (`NATIVE.md` 15.1 row 3).

## 7. Risks and open points

| # | Risk | Effect | What the builders do |
| --: | --- | --- | --- |
| 1 | **W fit in the masked phase**: 12.9 KB of code estimated in 15.4 KB, data 6.1 KB (the vissprites alone 3.2 KB) [A] | The link fails | In order: the rare paths (`nm_vismag`, `nm_fuzz`, `nm_mwall`: 4.1 KB) into an overlay slot loaded on first use in a frame (about 1 ms when used [A]); the drawseg copy down to 32; the vissprite to 32 bytes (the thing's x and y fetched from `RTHING` for a side test). The front end keeps about 3.2 KB spare [A] |
| 2 | **Card room**: 200 B of new loops in 382 B of bank 1; the bucket pass in the `$F900` part's 371 B, size unknown until stage A's prototype [A] | The link fails | `MATHLC`'s 164 spare bytes (`RENDER.md` 3.4); the bucket pass's fuzz marking and parking into bank 1; only the chunk copy must be near in its window (page 1 is its buffer), so the walks, which run with `RAMRD` off, may go to main memory the masked phase leaves dead, loaded with the masked image |
| 3 | **Sprite data in RamWorks**: 10-14 banks a level for the patch store [M, A], 2 more for tables and profiles, 1 for things | The game's allocation (`NATIVE.md` 4.4) | Within 126 banks (1.10); milestone 11 allocates |
| 4 | **Far access on F1.2.1**: a window a sprite column, 3-5 windows a visible thing, clip runs, masked columns: 1-3 ms in heavy frames [A] | The frame rate's low end | 3.5's batching; the timing report counts windows per phase; optimisations 6-7 of 6.2 |
| 5 | **Fuzz timing on the card**: the masked phase adds no screen reads, but the `K_FUZZNOW` marks move from the host's loader to the bucket pass | A missing mark shows as wrong pixels, a spurious one as time | The bucket check against `mark_fuzz` on every frame (4.3); the card's fuzz frames stay within the queue's measured cost (0.1-0.6 ms with the scan [M: `MEMORY_MAP.md` 9]); a2vm models the coalescer's scan (`MILESTONES.md` row 5) |
| 6 | **A column seen from behind** takes milestone 7's rules, a known difference (`NATIVE.md` 15.1 row 13) | A frame differs from `ref816` in lockstep | Skipped and reported by name (4.3); the disk image's 100 frames avoid such frames |
| 7 | **The page model** (`UPOFS`, the modelled flush) must follow upstream's allocation exactly | A masked post's kind (`K_TEXC`/`K_TEX`) differs | Compared on every frame against `COLW` and `XPNEXT`, where no masked wall shows too; `synth-mwlong`, `synth-pagefull` |
| 8 | **Masked walls are rare in the captures** (0 in demo3, 25 drawsegs in 50 `tour` frames [M: survey]) | A path untested | The coverage report and synthetic frames (4.1); routine mode on every captured masked range |
| 9 | **`SPRBOUND`'s dependence on the level set's load** (0.3) | A wrong early rejection after one load and not another | Injected from `ref816`; its use checked by a planted bug (4.7); the game computes it at its first frame as upstream, milestone 11 with its own planted bug |
| 10 | **The weapon's paths** (profile or not, and the order) | Records in another order | The converter's profiles checked against the reference's arenas; the call log names the path of every captured frame |
| 11 | **Tails of the patch store** for milestone 9 | Milestone 9's frames differ where a record reads past its post | The overrun measured (1.3) and written into the contract |
| 12 | **a2vm's costs are the model's**; one hardware frame and milestone 5's card runs anchor them | The report's ms move | The report says so; the owner's card test is milestone 12 |
| 13 | **Things' layout** (`RTHING`) is chosen before milestone 10 designs mobjs | A layout change later | The contract of 1.8; the bridge's manifest gets `RTHING`'s fields, as milestone 7 did for sectors and sides |
| 14 | **`MEMORY_MAP.md` changes proposed here**: `FRVIS` and `WPREV` at 11 B; `UPOFS` and `FRORD` in the `COLLO` area during the render; `SPRSEC` in aux 0 `$1600`; the masked phase's W map (1.10); `MCCLIP` in `SOLIDCOL`; the bucket pass's arrays over `FLOORCLIP`, `CEILCLIP`, `SOLIDCOL`, `WTMP`, its bounce buffer in page 1 and its batch list in zero page; card bank 1's and `$F900`'s new code; `RECSP` moved to 51-54, `RECW`; section 9's "Records: staging, bucket pass" row split, the bucket pass getting 6.2's own row | The map's owner must accept them | Stage A records them in a new `MEMORY_MAP.md` section 13 |
| 15 | **`ST_RECORDS` in the game** (6.1) drops records on an overflowing frame | One wrong frame, not a crash | Never reached in any measured frame; the owner may prefer an early replay at the phase boundary |
| 16 | **The bucket pass's cost** (3.4, 6.2): two bounce walks of the staging, a new design with no measurement | 3-21 ms a frame; the heaviest fight near or below 6 FPS | Prototyped and measured in stage A before B starts; optimisations 4 and 10 of 6.2 |
| 17 | **An early flush in the reference** (2.3 item 4): the injected screen is composed from P2, PS and P4 | A wrong input screen on a flush frame | The composition rule fails a frame where a strip write meets a flushed byte; `synth-pagefull` with a pre-flush shadow; the disk image's window has no flush frame |

**Open points for the owner:** 6.1's policy for a full staging in the
release build; whether the whole frame's thin margin over 6 FPS in heavy
fights (6.2: 5.9-6.5 FPS by the first estimate, 5.9-6.2 with stage A's
measurements, to be replaced by stage C's) calls for the optimisations of 6.2 before
milestone 12 rather than after; and acceptance 2's reading (4.6): the
task says "100 frames from injected states", while this design's
default chains the frames (the game state injected each frame, the
renderer's own state carried), which tests more but lets one wrong
frame spoil the later CRCs, so the image also has a mode that injects
each frame whole, and both must pass. (Question 13, the grazing-view
rules, was answered on 2026-09-30: `NATIVE.md` 15.1 row 13.)

## Appendix A: upstream to native, by routine

| Upstream | Lines | Native | Stage |
| --- | --- | --- | --- |
| `bspSub`'s `R_AddSprites` call | `r_bsp65.s:730-742` | `SPRSEC` append in `rbsp.s` | A |
| `R_AddSprites`, `nextThing`, `thing`, `whole`, `txDone` | `r_thing65.s:155-707` | `nm_project` | A |
| `gTZ`, `gTZcalc`, `gTX`, `gGZcheck`, `gGZ`, `gGX`, `wHi`, `k1Wide`, `labsTZ` | `r_thing65.s:713-821`, `:1008-1086`, `:1193-1245` | `nm_project` | A |
| `R_WallFrame`'s G parts, `prFrame` | `r_wall65.s:1873-1917`; `r_thing65.s:1096-1189` | `nm_project`'s setup | A |
| `R_InitSpriteIScales`, `fqInit`, `boundInit`, `frameInit` | `r_thing65.s:837-997` | `rtables.py` (tables); the game's first frame (`SPRBOUND`) | A |
| `R_SpriteColorMap`, `CMO` | `r_bsp65.s:1009-1020`, `:1061-1097` | `CMOP` | A |
| `sortSprites`, `scaleLess`, `sortSkip` | `r_frame65.s:288-347`, `:995-1015` | `nm_sort` | A |
| `drawMasked` | `r_frame65.s:180-212` | `nm_masked` | B |
| `R_DrawSprite`, `dsLoop`, `side`, `behind`, `clipIt`, `dsVisible`, `clipPtr`, `ltScale2` | `r_sprite65.s:481-561`, `:1460-1716` | `nm_drawsprite` | B |
| `R_PointOnSegSide` | `r_data65.s:768-` | `nm_ptseg` | B |
| `R_DrawVisSprite`, `visCol`, `visNext`, `visPost`, `visFill` | `r_seg65.s:2698-3145` | `nm_vis` | B |
| `visColD`, `vrCol`, `vrPost`, `vrFill`, `vrNext` | `r_frame65.s:1696-2038` | `nm_vismag` | B |
| `visColF` | `r_sprite65.s:568-719` | `nm_fuzz` | B |
| `wclipSprite` | `r_frame65.s:966-990` | `nm_vis` | B |
| `R_RenderMaskedSegRange`, `maskedRange`, `lineFlags`, `higher`, `lower`, `smul48`, `mwCols` | `r_frame65.s:357-637`, `:1060-1118`, `:1249-1648` | `nm_mwall` | B |
| `recAlloc`, `newPage`, `flush` (allocation only) | `r_list65.s:256-323` | `rec_room`'s page model | B |
| `weaponClip`, `psSetup`, `pspSprite`, `wcDraw3`, `wpCheck`, `wpStart`, `wcProf`, `visPost` 30$ | `r_frame65.s:647-854`; `r_sprite65.s:799-880`, `:1186-1301`; `r_seg65.s:3093-3116` | `nw_clip` | C |
| `weaponClipSame` | `r_frame65.s:892-943` | `nr_wskip` (milestone 7) on the native `FRVIS`/`WPREV` | C |
| `playerSkip`, `playerSprites`, `pspDraw0`, `wdDraw`, `wdProf` | `r_frame65.s:660-665`, `:947-958`, `:1039-1048`; `r_sprite65.s:829-856`, `:1303-1448` | `nm_psp` | C |
| `wpFind`, `wpFlush`, `wpBuild`, `wbMake` | `r_sprite65.s:884-1178` | `levelconv.py`'s profiles | C |
| `R_DrawLists` (the replay) | `r_list65.s:545-` | milestone 5's `nat_replay` after `nb_bucket` | C |

## Appendix B: the measurements made for this design

All read-only, 2026-09-30, under `nice -n 10` with
`tools/ref816/bounded.py` limits (300 s, 20 MB of output); the scripts
are in the session's scratch directory, not in the repository, and
wrote nothing into `build/` (0 bytes added).

**Vissprites and drawsegs** ([M: survey], 1.2): for each of milestone
7's 188 captured frames, `build/native/render/frames/*/p3.dump.z`
(`rendercap.load_dump`) read at `drawMasked` entry by the link map's
`num_vissprite`, `vissprites` (42-byte records, `offsets.inc:10-23`),
`ds_p`, `_s_drawsegs` (42-byte records, `offsets.inc:26-38`), `dsX1`
and `dsCount` (`$0A:B500`, `$0A:B600`, `dscols.inc`), `_g_player`'s
psprites (`offsets.inc:280`, `:309`): per set the vissprites, shadows
(colormap 0), columns (x2 - x1 + 1), magnified (\|xiscale\| < $C000),
flipped (xiscale < 0), equal scales, drawsegs with `dsX1` ≠ 255, and
with masked columns. About 30 s. (A count of full-bright vissprites was
attempted and dropped: its comparison with the `fullcolormap` pointer
was not reliable.)

**Sprite lumps per level** ([M: survey], 1.2): for the 12 level sources
of the tour, `newgame` and `title` (`build/native/render/levels/src/
*.ram.z`, whole RAM), the game's lump directory in RAM (`fileinfo`,
`numlumps`: 1,015 entries of 16 bytes, filepos, size, name) between
`S_START` and `S_END`; a lump is resident when no other entry shares
its `filepos` (upstream's placeholder, as `tools/bridge/upstream.py`
`read_wad` decides); its address `$10:0000` + filepos
(`r_thing65.s:383-397`). Sizes, banks, lumps whose end + 128 passes
their bank. A first version used DOOM1.WAD's own lump numbers, which are
not the game's (1,264 lumps against 1,015), and was discarded; DOOM1.WAD
itself was read only for its sprite totals (483 lumps, 825,576 B,
20,931 columns, 34,578 posts, the widest 154). About 60 s.

**Frames in demo3**: the frame indexes of milestone 7's `title` set,
chosen evenly from the whole demo, run from 0 to 532
(`frames/title-*/frame.json`).

## Review

One adversarial review of the first version (2026-09-30), 14 findings.
Each was checked against the sources before it was applied; none was
rejected, and three were applied in another form than the review
proposed (1, 4, 14a), for the reasons given. Checking them read only
sources, `rlayout.py`'s values and `build/native/render/report.md`:
`build/` grew by 0 bytes.

| # | Finding | Checked against | Outcome |
| --: | --- | --- | --- |
| 1 | The bucket pass read main arrays with `RAMRD` on; its 330 B and 2-4 ms were unfounded | `MEMORY_MAP.md` rule 5 and 3.3 (`CVRECLO` `$1540`, `COLLO` `$1680`); `NATIVE.md` 1.2 (a window 3.0-4.7 µs); `MEMORY_MAP.md` 9 (the row counts the staging) | **Applied, in another form.** The bounce through page 1 and the scatter with `RAMRD` off as proposed, the covered ranges translated in the scatter (3.4). The per-column arrays go to main arrays the masked phase leaves dead (`FLOORCLIP`, `CEILCLIP`, `SOLIDCOL`, `WTMP`) rather than W `$8000+`, so that one scatter walk fills three batches into W `$6000-$BFFF` and batches 2 and 3 are parked in `RECW` instead of each costing another walk of the whole staging. No code size is claimed; stage A prototypes and measures the pass (5.1). 6.2 gives it its own row from its own work: 3.1-5.1 ms at the demo median and 14.4-21.1 ms in the heavy column, which puts the heaviest fight at 5.9-6.5 FPS, and the check also found the first version's heavy total (102-115) above its own rows' sum (102.1-110.8) |
| 2 | The clip log from `$6000` passed `$BFFF` | 322 × 80 = 25,760 B; `rlayout.py:59-66` (`SEAM_SOLID` = `$1400`, `BANK_ROOM`) | **Applied**: from `$1400`, 82 calls (the weapon's draw added; the clip pass is not `nm_vis`), 26,404 B to `$7B24`, asserted in `rlayout.py`; `CLIPLOG` and `LOCKSTEP` builds exclusive (4.2) |
| 3 | psprite `sy` is 32 bits | `offsets.inc:311-313`; `r_frame65.s:784-787` | **Applied**: render inputs 43 of 48 (1.10, 2.1); a planted bug (4.7) |
| 4 | P4's screen already holds the pre-flush records | `r_list65.s:304-323`, `:564-580`; `d_main65.s:485-502` | **Applied, in another form.** Taking every view row from the first P2 would drop what `stripEarly` writes after the render (its `I_MessageStrip` clears the strip's rows 0-9, inside `$2000-$88FF`, when a message turns on [R `d_main65.s:764-780`; `i_viigs65.s:504-545`]). A new point PS at `stripEarly` tells the flushes' bytes (first P2 ≠ PS), which take the first P2's value, from the rest, which P4 gives; a byte both changed fails the frame by name (2.3 item 4). Flush frames stay out of the disk window as proposed (4.6), and the screen patch uses the same composition |
| 5 | The chain did not say where `validcount` comes from | `framestate.py:216`, `:319`; `NATIVE.md` 14 risk 10 | **Applied**: `VALIDCOUNT` and every sector's stamp injected together on every frame, in frame mode and in the chained files (2.1, 2.3, 4.6) |
| 6 | `nm_mwall` has room for one clip run | `r_frame65.s:413-420`, `:1253-1260`; `MEMORY_MAP.md` 3.3 (`SOLIDCOL` not persistent) | **Applied**: `mceilingclip` in `MCCLIP` over `SOLIDCOL`, two `far_open` windows (1.10, 3.5), excluded from the frame-end comparison (2.4), a planted bug (4.7) |
| 7 | The clip log and the call log do not pair | `r_sprite65.s:799-826`; `VS_CLIP` (`r_seg65.s:83-84`) | **Applied**: the call log records `VS_CLIP`, the clip pass's calls are dropped (P1 checks that pass), the rest pair in order with an identity check (4.2) |
| 8 | Checkpoint B does not exercise the page model | `RENDER.md` "What stage C changed, and why" (139 of 254 B) | **Applied**: `synth-mwlong` and `synth-pagefull` required, the planted flush bug (5.2 item 3, 4.7) |
| 9 | Routine cases were counted for 188 frames but specified for all | about 10 calls × 721 frames × 2 | **Applied**: routine mode limited to the 188 frames and the synthetic cases; demo3 by frame mode and the clip log (4.1, 4.5) |
| 10 | 6.1 said both `BRK` and "reported as a `RULES` frame" | 6.1 items 2 and 3 | **Applied**: test and lockstep builds stop with `BRK`; the release flags `STATUS` only |
| 11 | Question 13 is answered | `NATIVE.md` 15 item 13 and 15.1 row 13 | **Applied**: cited as answered; dropped from the open points; the handling unchanged |
| 12 | The frame block holds 87 B, not 86 | `rlayout.frame_block_used()` = 87 | **Applied**: 95 of 96 with `RECDROP`, every field to be listed in `rlayout.FRAME_BLOCK` (1.10) |
| 13 | The chained card test is not "from injected states" | the task's acceptance 2; `NATIVE.md` 13 row 8 | **Applied**: a full-injection mode beside the chained one, both must pass; named for the owner (4.6, section 7) |
| 14 | The `SPRBOUND` planted bug tests code not built; the masked-texture check misses translated textures | 0.3 row 3; `r_frame65.s:455-468`; `p_spec65.s:318-338` (the slime frames are the only `texturetranslation` animation) | **Applied**: 14a in another form, a planted bug in `nm_project`'s use of `SPRBOUND` now, the computation's bug moved to milestone 11; 14b, the closure through `switchlist` and `animated_texture_basepic`, a non-resident one listed and stopping a frame that draws it (1.3, 1.11) |

## Stage A as built (2026-09-30)

Stage A of section 5.1 is built. Native code: `src/native/mproj.s`
(`nm_project`, `nm_sort`), `mmain.s` (`nm_masked`'s skeleton), `mfar.s`
(`far_mload`, `far_dscopy`), `rbsp.s`'s `SPRSEC` append
(`nr_addsprites`), `rframe.s` (`SPRN` cleared), `far.s`'s loader with a
bank argument (`far_pload`), `rdriver.s`'s masked driver (`-D MASKED`),
`auxlc.s` in its own segment `AUXW`, `render.cfg` and `render.mk` (the
builds `mtest`, `mprof` and `btest`); the bucket pass's prototype
`bucket.s` with `bdriver.s` and `bucket.cfg`. Host tools: `rlayout.py`,
`levelconv.py` (format `render-level 2`: the patch store, `PHDR`,
`SPRFR`, `TXMP`, the thing list heads, `--overrun`), `rtables.py` (the
scale records, `CMOP`, `SFIRST`), `framestate.py` (the render things,
psprites, the sector light, `SPRBOUND`, `FZ_POS`), `rendercap.py` (points
P3s, P3w, PS, P4, P5; the call logs; the `demo3` set), `rcanon.py`
(vissprites, order, skip), `render_check.py --masked`, `framesynth.py`
(`synth-spectre`, `crowd`, `close`, `edge`, `qmulh`), and two new ones:
`projmodel.py` (a host model of upstream's projection and sort, with its
coverage of every path) and `bucketcheck.py` (the prototype on a2vm
against `loader.py`). a2vm counts 32 cost phases (`tools/a2vm/cost.h`,
16 before). Tests: `tests/test_native_masked.py` (13 tests), and
milestone 7's three render tests given the new files. `MEMORY_MAP.md`
section 13 records the regions; `src/native/README.md`, "The masked
phase (milestone 8)", describes the code and gives the commands.

### Checkpoint A

| Item | Result |
| --- | --- |
| 1. `levelconv.py --all`, 17 level sources (18 since stage B's `synth-mwclose-tour-e1m6-t321`; all 18 pass again on 2026-10-01) | Every check of 1.11 on all 17 (12 levels): the patch store 245-327 lumps in 10-14 banks (457,024-659,776 B with tails), its lumps and tails equal to the reference's memory; every sprite frame resolves to a store index or the placeholder (one is not a frame: sprite 1 frame 4, past its sprite's frames, flagged `SPRFR_BAD`; the native projection stops with `ST_SPRFRAME` if it meets one, which no frame does); `TXMP` 0-6 textures a level; the bridge reads the render fields back. `rtables.py`: every check of 1.6 (`SPRXSCALE`, `SPRYSCALE`, `SPRISCALE`, `FQ` for d = 4..1,280 against the reference's arrays and their formulas; `CMOP` against `CMO`), from the one source whose frame had made them (`PR_IOK` = 1: `lights-e1m1-t33`) |
| 1. The overrun of 1.3 | Measured on 725 frames' 70,446 masked records reading the store (`levelconv.py --overrun`, `levels/overrun.json`): a record reads up to 127 texels past its post (a first row just under 0, masked to 127) and up to 124 bytes past its lump's end (E1M7). So 1.3's rule holds exactly: each lump keeps the reference's 128 following bytes whole, and milestone 9 must keep them too |
| 2. The frames | `render_check.py --masked`: milestone 7's 188 frames and the 5 new synthetic ones, both fills: 386 runs equal, 3,376 vissprites; `--masked --sets demo3`: 533 frames, 1,066 runs equal, 12,554 vissprites. On each run the vissprites at the projection's end equal P3's (count, order, every field of 2.4 with the colormap page), the order, `FR_SKIP` and `W_WSK` after the sort equal P3s's, the listed sectors equal the `R_AddSprites` call log (captured frames; a synthetic frame has no call log, its list is its base frame's), milestone 7's outputs at the walk's end still equal P3's, no stray write, at most 82 bytes of stack. 0 frames with `RULES` ≠ 0 (none skipped as a known divergence) |
| 3. The bucket prototype | `bucketcheck.py --timing`: 192 frames (the 188 and the synthetic ones then made), 384 runs: the records by column in W, `COLLO`/`COLHI`, the covered ranges' W addresses and the 133 `K_FUZZNOW` marks (3 in `demo-09`, 61 in `title-05`, 69 in `title-06`) equal `loader.py`'s bucketing and `mark_fuzz` on the same staging; 172 frames in one batch, 19 in two, 1 in three (`synth-crowd`). Size: 1,073 B (below). Time: 1.37 µs a staged byte on `f121` (1.26-1.77), 1.31 on `fastpath`, about 96 65C02 cycles a byte; ms by set in `src/native/README.md`; 6.2's row is updated |

`projmodel.py` (the host model of 4.3's projection and sort, written from
upstream's routines) equals P3 and P3s on all 725 frames and reaches
every path, including the `FixedMul` fallbacks for `xl` and `xr`, the
`labsTZ` rejection and the `MAXVISSPRITES` cut; the synthetic frames
`edge` (the fallbacks) and `qmulh` (a thing whose G part shows
`qmulh`'s +1) were found with it.

Planted bugs (4.7), each in a scratch copy and caught: in the projection
and sort, a fractional thing's G parts exact instead of `qmulh`
(`synth-qmulh`), the rotation's + `$9000` as + `$8000`, a flip ignored,
`CMOP` one page off (`demo3-371`), the early rejection reading E / 2 + 2
for E (`newgame-40`, `demo3-049`), the sort's ties swapped and
`MAXVISSPRITES` 79 (`synth-crowd`), `sortSkip` blind to shadows
(`synth-spectre`), a sector listed twice in `SPRSEC` and a store into the
masked image's code (`still-1`); in the bucket pass, the `K_FUZZNOW`
marks missing (`title-05`), the record cut by a chunk's end dropped
(`demo-09`), a covered range's W address one record off (`title-05`);
in the converter, a wrong byte in the store and frame addresses by an
18-byte stride.

### What stage A changed, and why

| Design | As built | Why |
| --- | --- | --- |
| `CMO` 69 words, `CMOP` 69 B | 85 of each (1.6 corrected) | `r_bsp65.s:1009-1020` has 85 |
| `SPRBOUND` made once a session | Made at the first frame after each level set's load (0.3 row 3, 1.6, risk 9 corrected); still injected per frame | `w_level65.s:305-309` clears `PR_IOK` with the old set; only one of the 17 sources had `SPRISCALE` and `FQ` made, and `rtables.py` takes them from it |
| The masked image all of W `$6000-$9BFF`, with its own math subset | `MATHW` and `auxlc.s` (1,427 B at `$6000`) shared by both images and loaded once with the front end's; the masked image from `MCODE` = `$6800` to `$9BFF` (13,312 B, 1.10 and 3.7 corrected) | No second copy of the math; the budget without the math (12,000) still fits with 1.3 KB to spare, against 2.5 KB in the first version |
| `mask.cfg` | `render.cfg`'s `WM` area (`%O.wm`, segment `MASKW`), with `MFAR` in the card | One link for both images, so the masked code calls the front end's math and the card's routines by name; the lockstep builds without the masked image link unchanged (`MASKW` and `MFAR` optional) |
| `far.s` loader "with a bank argument" | `far_pload` (A:X a list of page runs, Y the bank); `far_wload` and `far_mload` pass their lists | The masked image and `TXMP` are two runs |
| The listed sectors in `YHTAB`'s place | `SECLIST` at `$BA00` (stage B's `YHTAB` comes after the projection) | As designed; recorded |
| The render things' slots | The pool's objects in index order, then the zone's mobjs in first-reach order (`framestate.slot_map`); 768 slots | The reference has no slot numbers; any fixed rule gives the same vissprites. The pool's size is milestone 10's to confirm |
| No fixed state for the sprite frames' status | `ST_SPRFRAME` (8): a frame the converter flagged not a frame, `ST_BUCKET` (9) for the bucket pass's stops | The reference reads such a frame's bytes; no capture reaches one |
| The bucket pass in the card's `$F900` part (371 B), cursors `CUR` over `FLOORCLIP`/`CEILCLIP`, `CVW` over `SOLIDCOL` and `WTMP` | 1,073 B: `BKNEAR` (230 B, the chunk copy, the parking and bring-back) and `BKCARD` (136 B) in the card at `$FD8D-$FEFA`; `BKFAR` (707 B, both walks, the conversion, the marks) in main `$0C00-$0EFF`; no `CUR` (the counts become cursors in `COLLO`/`COLHI` and are shifted back to starts); `CVW` over `DSX1`/`DSX2` and `WTMP` | Risk 2's third fallback: the walks run with `RAMRD` off, so they need not be near; `$0C00-$0EFF` is dead after the masked phase and is filled from the masked image (stage C adds the copy) |
| The bucket pass 0.6-1.0 µs a staged byte | 1.37 µs (1.26-1.77) on `f121` | 6.2 updated: the heavy column 5.9-6.2 FPS |
| a2vm's 16 cost phases | 32 (`COST_PHASES`) | The masked phases 11, 13-15 and the bucket's 18 |
| `rendercap.py`'s P5 "at `R_DrawLists`' return" | Found by its bytes after `d_main65.s`'s `JSL R_DrawLists` (`$03862A` in the release) | No label there |
| `demo3` 533 frames | Captured once more by frame index (`demo3-000` .. `demo3-532`), opt-in (`--sets demo3`), not in milestone 7's default sets | Milestone 7's `title` set keeps its names; routine captures skip `demo3` |

### Sizes (3.7)

| Part | Built | Budget |
| --- | ---: | ---: |
| `nm_project`, `nm_sort` with their constants (`mproj.s`) | 2,615 (427 of constants) | 2,000 + 350 + part of 450 |
| `nm_masked`'s skeleton, the drawseg copy's index list (`mmain.s`) | 68 | part of 450 |
| Masked image so far (`$6800-$727A`) | 2,683 of 13,312 | 12,000 for the whole image |
| Card bank 1: `far_pload` (+13 B) and `mfar.s` (163 B) | 818 of 1,024 used, **206 left** | stage B's 200 B |
| Card `$F900` part: `BKNEAR` + `BKCARD` | 366 of 371 | 371 |
| Main `$0C00-$0EFF`: `BKFAR` | 707 of 768 | |
| Front end (W): `MATHW` 1,281, `AUXW` 146, `RENDERW` 14,205 | 15,632 to `$9D0F` | 17,160 with stage C's 1,550 |
| Frame block, render inputs | 95 of 96, 43 of 48 | 95, 43 |

### Timing (a2vm `f121`, not the card)

`render_check.py --masked --timing` (the profiling build `mprof`),
milliseconds, median (worst): the masked image's window 0.83 (13 pages);
the drawseg copy with `SPRBOUND` 0.36 still, 0.22 (0.40) in `title`;
the projection and sort 1.33 still, 2.38 (5.35) in `title`, 2.44 (6.19)
over all 533 `demo3` frames, 5.93 in `tour-12`, 12.7 in `synth-crowd`
(80 vissprites). The
projection costs 0.19 ms a vissprite (median), most of it windows: the
thing, its sector, its frame, its patch header and its scale record are
each fetched through the card. The bucket pass: `still` 8.88, `title`
6.54 (2.68-19.25), `newgame` 8.58, `tour` 7.20, `demo` 4.86 ms;
`synth-crowd`'s 23,748 staged bytes in three batches 41.9 ms.

### Open points of stage A

- **The bucket pass is slower than estimated** (1.37 against 0.6-1.0 µs
  a byte) and needs `$0C00-$0EFF` for its walks: stage C must copy
  `BKFAR` there from the masked image at the phase's end, and extend the
  prototype's three batches (`MAXB`) to the spill's 26. Optimisations 4
  and 10 of 6.2 are where time comes back.
- **The projection is 2.6-4 times its estimate in demo3** (the median
  frame); optimisation 6 of 6.2 (one window a sector chain for its
  things) is the candidate.
- **Card bank 1 has 206 bytes left** for stage B's `far_posts`,
  `far_open` and the aux-0 copy (about 200 B estimated): if they do not
  fit, `MATHLC`'s spare bytes are next (risk 2).
- A synthetic frame has no call log, so its listed sectors are compared
  with its base frame's walk only through the vissprites.
- `TXMP` is `$FFFF` for a texture a masked mid texture can show when
  upstream has not loaded it or its lump is not resident (none in the 17
  sources); stage B's `nm_mwall` must stop on one rather than read a
  wrong patch.
- The render things' pool size (768) is milestone 10's to confirm.

`build/` grew by about 273 MB in this stage (2,765,640 KB before, 3,045,208 KB after; the
frames' new points, call logs and `demo3` captures most of it),
temporary output deleted after each run.

## Stage B as built (2026-09-30)

Stage B of section 5.2 is built, on a2vm, not yet reviewed. Native
code: `src/native/msprite.s` (`nm_drawsprite` with `nm_ptseg`,
`md_dsptr`, `md_cliprun`, `md_phdr`), `mvis.s` (`nm_vis`: `wclipSprite`,
`visCol`/`visPost`, the magnified runs, the shadows' `visColF`, `YHTAB`,
`FSCUT`, `CVSET`, the clip log), `mwall.s` (`nm_mwall` with `smul48`, the
peg rules, `R_WallLight` and the two-light pages, `K_TEX`/`K_TEXC` by the
page model, the drawn marks), `mmain.s`'s two loops and routine mode's
entries, `mfar.s`'s `far_posts`/`far_postsc`, `rrec.s`'s page model
(`UPOFS`, `XPUSED`, `UPFLUSH`, `RECSEQ`; assembled a second time with
`-D MREC` into the masked image), `rdriver.s`'s `drv_mroutine`,
`render.mk` (the masked objects of `mtest` built with `-D CLIPLOG`).
Host tools: `maskmodel.py` (the host model of upstream's masked phase,
P3s to P3w, with its path coverage), `maskcap.py` (the routine captures),
`maskroutine.py` (routine mode), `rcanon.py`'s stage B canon,
`render_check.py --masked`'s stage B comparison, `framesynth.py`
(`synth-mwlong`, `pagefull`, `mwclose`, `mwlight`), `framestate.py`
(`WTMP`), `levelconv.py` (`TXWM`; the peg flags in the level key),
`rlayout.py`. Tests: `tests/test_native_masked_b.py` (model, frames,
native fallbacks, timing, routine mode, 15 planted bugs), and the M7
render tests and `test_native_masked.py` given the new files.

### Checkpoint B

| Item | Command | Result |
| --- | --- | --- |
| 1. Routine mode | `python3 tools/native/maskcap.py` then `python3 tools/native/maskroutine.py --jobs 2` | Every captured call of milestone 7's captured frames: 2,145 cases (`R_DrawSprite` 1,391, `R_DrawVisSprite` 719, `R_RenderMaskedSegRange` from a sprite 10, `maskedSeg`, the drawseg loop's ranges, 25), 4,290 runs from both fills, all equal: the records appended with their kinds by column, the clips, the clip log, `FZ_POS`, spans, covered ranges and their records, `UPOFS`, `XPUSED`, the drawn marks, `floorclip`/`ceilingclip`; 27,834 records compared, no stray write |
| 2. The frames | `python3 tools/native/render_check.py --masked` | 197 frames (milestone 7's 188, stage A's 5 synthetic frames and stage B's 4), both fills: 394 runs equal, 3,598 vissprites, 245,734 records and 2,014 clip-log calls compared: the records to the weapon's draw equal P3w's by column (kinds, every byte with the patch map), `UPOFS`/`XPUSED` equal P3w's `COLW` low bytes and `XPNEXT`, the covered ranges with their `CVREC` records and the spans equal P3w's, `FZ_POS`, `W_WSK`, the clip log pairs with the `R_DrawVisSprite` call log by vissprite (captured frames), no stray write, at most 79 B of stack. 0 frames with `RULES` ≠ 0 |
| 2. `demo3` | `python3 tools/native/render_check.py --masked --sets demo3` | 533 frames, both fills: 1,066 runs equal, 12,554 vissprites, 589,770 records and 6,358 clip-log calls compared, the same outputs, no stray write, at most 82 B of stack, 0 frames with `RULES` ≠ 0 |
| 2. Milestone 7 again | `python3 tools/native/render_check.py --frame-mode` | 197 frames, 394 runs, 0 failed, with the page model in every producer |
| 3. The page model | `render_check.py --masked --frames synth-mwlong,synth-pagefull` (in the 197) | `synth-mwlong`: a `K_TEXC` refused at a page's end and an extra page taken; records, kinds, `COLW`, `XPNEXT` equal; `synth-pagefull`: all 50 extra pages taken and one modelled flush (`UPFLUSH` = 1, `XPNEXT` `$CE` after it), the records staged before and after it equal `ref816`'s P2 flush dumps and P3w, both fills. The planted bug "the flush does not reset `UPOFS`/`XPUSED`" fails `synth-pagefull` (`upofs`, `flushes`, `xpnext`) |

`maskmodel.py` equals P3w on all 730 frames (the 197 of the default sets
and the 533 of `demo3`) and reaches 26 named paths, every one it names; the synthetic frames were made with it
(`tools/native/framesynth.py`'s docstring): `synth-mwlong` reaches "K_TEXC
refused (the page's end)", `pagefull` the flush, `mwclose` the `recip`
step and the lower ceiling's texturemid, `mwlight` the two-light range.
`tests/test_native_masked_b.py`'s model test also plants a wrong rule in
the model and sees it fail.

Planted bugs (4.7), each in a scratch copy under `build/`, each caught
(`tests/test_native_masked_b.py`, the frame each is caught on): the
drawsegs scanned first to last (`title-05`, `demo3-344`), the C code's
-2 for "clip not set" (`title-05`, clip log), the side test's sign
flipped (`demo3-344`), `visCol` stopping at x2 (`demo3-048`), `YHTAB`
from E for E - 1 (`title-50`), a magnified run ignoring its clips
(`demo3-114`), `FZ_POS` not kept (`title-05`), `UPOFS` one byte off
(`still-1`, `synth-mwlong`), the modelled flush not resetting `UPOFS` and
`XPUSED` (`synth-pagefull`), `MCCLIP` not read (`tour-46`, and in
routine mode), `CVSET`'s > as >= (`title-47`), `FSCUT` missing for
sprites (`demo-01`), a masked column drawn twice (`tour-31`), one light
for a two-light range (`synth-mwlight`). The native fallbacks no capture
reaches are run by shrinking them in a scratch copy: `DSW` to 4 slots (the
drawsegs past it fetched into `DSB`) and `far_posts`' buffer to 2 posts
(`far_postsc`'s continuation), on `title-05`, `tour-31` and
`synth-mwclose`, all equal.

Stage A's bucket prototype still equals `loader.py` on the new staging
(`bucketcheck.py`: 196 frames, 392 runs; `synth-pagefull` skipped, its
early flush is stage C's).

### What stage B changed, and why

| Design | As built | Why |
| --- | --- | --- |
| `YHTAB` two planes of 513 with `YHTABM` (1.9) | Two planes of 512, `YHL` `$BA00`, `YHH` `$BC00`; the running E - 1 in zero page | The word before row 0 is the running value; 1.9 corrected |
| `far_open` and an aux-0 copy in the card (1.10, 3.5) | Not built: clip runs and masked columns go through `far_get` with `FA_BANK` 0 (aux 0); `far_posts`/`far_postsc` 171 B with a 16-post buffer | The far layer already reads aux 0; card bank 1 holds 989 of 1,024 B |
| `FSTEP` one window a column (3.5) | Two, a byte from each plane | The table is two planes (`RENDER.md`); the posts are fetched after the step so `far_postsc` keeps its source |
| `WTMP` not state (2.1, 2.2) | Persistent: `wclipSprite` writes x1 .. min(x2 + 1, 159) only and a later sprite can read a column past that; `framestate.py` injects it from P0 | Upstream's code reads what it did not write this frame; 2.1 and 2.2 corrected. Stage C's bucket pass puts `CVW` over it (open point below) |
| Zero page "about 90 bytes" (3.6) | `OVD1` 36 B (`$18-$3B`), `OVD2` 87 B (`$48-$9E`) | 3.6 corrected |
| `mwclose` gives the `recip` step and two lights (4.1) | `mwclose` (ceilings raised, `DONTPEGBOTTOM` cleared) gives the `recip` step and the lower ceiling's texturemid; `synth-mwlight` (a dark sector at `tour-46`'s masked range) gives two lights | No single poke reached all three; `maskmodel.py` chose the pokes |
| Routine mode with the synthetic cases (5.2 item 1) | The captured calls only; the synthetic frames' paths are checked in frame mode (item 2) and by the planted bugs | A synthetic frame has no call log to capture from; `maskcap.py` skips them |
| A frame with a flush compares covered ranges | Not on a flush frame: upstream's flush draws and resets the ranges, so P3w's are the post-flush ones; the records, `COLW` and `XPNEXT` are compared | As 2.4 says for the replay's input; recorded |
| `ST_TALL` not planned | `ST_TALL` (10): a masked post past texture row 255 (upstream's `mwTall`, an `I_Error`) stops the frame | No texture of the game has one |
| — | `levelconv.py`'s level key hashes the lines' peg flags | A milestone 7 bug: two sources differing only in those flags shared one conversion, so `synth-mwclose` read the wrong peg; all levels reconverted |
| — | `tests/test_native_render_frame.py`'s timing test compares the phases' sum of cycles under `f121` and `fastpath`, each phase within 100 cycles an interrupt | The VBL interrupt comes at a time, not a cycle: with `rec_room`'s page model its handler (51 cycles) fell in wall setup under `fastpath` and in the seg loops under `f121` on `still-1`; the sum stays equal, so the test's point (the same code, the same cycles) is kept |

### Sizes (3.7)

`render_check.py --sizes` gives the front end; the masked image from the
`mtest` map (`mprof` without the clip log in parentheses):

| Part | Built | Budget |
| --- | ---: | ---: |
| `nm_drawsprite`, `nm_ptseg` and helpers (`msprite.s`) | 1,157 | 1,600 |
| `nm_vis`, the magnified runs, the shadows (`mvis.s`) | 1,417 (1,333) | 1,500 + 1,200 + 600 |
| `nm_mwall` with `smul48` and `PGT` (`mwall.s`) | 1,778 | 2,300 |
| `drawMasked`'s loops, routine entries (`mmain.s`) | 260 (295 with the phase marks) | part of 450 |
| `rrec.s` in the masked image | 198 | 600 |
| Masked image (`$6800-$8500`) | 7,425 of 13,312 (7,376 in `mprof`) | 12,000; stage C's `nm_psp` 1,400 to come |
| Front end `RENDERW` (the page model in `rec_room`: +77 B) | 14,282 to `$9D5C` | 17,160 with stage C's 1,550 |
| Card bank 1: `mfar.s` 334 B (stage B +171) | 989 of 1,024, **35 left** | stage B's 200 |

### Timing (a2vm `f121`, not the card)

`render_check.py --masked --timing` (`mprof`), ms, median (worst), fill
`$A5`: the sprites and masked walls (phase 4) with the last batch's
flush:

| Set | Frames | Masked window | Sprites and masked walls |
| --- | ---: | ---: | ---: |
| still (E1M1) | 3 | 1.97 | 1.59 |
| newgame | 50 | 1.96 | 1.56 (2.42) |
| m5 demo | 11 | 1.96 | 1.84 (7.18) |
| title (demo3) | 50 | 1.96 | 2.01 (12.61, `title-06`) |
| tour | 50 | 1.96 | 1.77 (5.74) |
| lights | 12 | 1.96 | 1.79 (2.35) |
| demo3 | 533 | 1.96 | 2.55 (17.34, `demo3-114`) |

The window grew with the image (29 pages, 1.96 ms, against the 3.4 ms
6.2 assumed for the whole image). Synthetic extremes: `synth-crowd` (80
vissprites) 55.5 ms, `synth-pagefull` (every extra page and a flush)
64.7 ms. 6.2's row "Sprites, masked walls, weapon" estimated 1.8-2.9,
1.6-2.7 and 11.6-18.9 with the weapon; without it stage B measures 1.59
still, 2.55 at `demo3`'s median and 17.34 at its worst (`demo3-114`: 14
vissprites, magnified runs, 26 drawsegs copied, an extra page). The still and median
figures leave room for the weapon; the worst is near the top of the
row before the weapon, so the heavy column of 6.2 may fall under 5.9
FPS: stage C's whole-frame timing decides.

### Open points of stage B

- **`WTMP` is persistent state** and stage A's bucket pass puts `CVW`
  over it (`MEMORY_MAP.md` 13): stage C must move `CVW` or the next
  frame's sprites read the bucket pass's bytes.
- **Card bank 1 has 35 bytes left.** Stage C's card needs, if any, go to
  `MATHLC`'s spare bytes (risk 2).
- Routine mode has no synthetic cases (above); the synthetic frames are
  compared whole.
- `mtest` and `mprof` differ by the clip log (`-D CLIPLOG`): the timing
  build writes none, the checked one does; both run the same frames
  equal.
- `maskcap.py`'s `index.json` lists only the last run captured (the cases
  are complete; the index is informational).
- **Masked walls are rare in the captures**: 15 of the 197 default frames
  draw a masked drawseg, no `demo3` frame does; the `recip` step and the
  lower ceiling's texturemid come only from `synth-mwclose`, the page's
  end from `synth-mwlong`, the flush from `synth-pagefull`. The sprites'
  paths are common (magnified 27 and 150 frames, shadows 12 and 45,
  default sets and `demo3`).

`build/` grew by about 80 MB in this stage (3,046,380 KB before,
3,128,072 KB after; the routine captures 72 MB, the new synthetic
frames and reconverted levels most of the rest), temporary output
deleted after each run.

## Stage C as built (2026-10-01)

Stage C of section 5.3 is built, on a2vm, not yet reviewed and not yet
run on the card (the owner runs `RENDER.hdv` at milestone 12). Native
code: `src/native/wclip.s` (`nw_clip`, the weapon's clip pass in the
front end, replacing milestone 7's seam), `wpsp.s` (the weapon code both
phases share, assembled twice), `mpsp.s` (`nm_psp`: `playerSkip`,
`playerSprites`, `wdDraw`/`wdProf` or `R_DrawVisSprite`, the flash),
`bucket.s` finished (`nm_bkload`, `BKNEAR`, `BKFAR`, `BKFAR2`, the group
scatter, `CVDONE`, the marks, the replay's calls), `rrec.s`'s release
policy (`-D RELEASE`, 6.1), `rdriver.s`'s `drv_fframe` (the whole frame),
`rrunner.s` (`RENDER.SYSTEM`), `render.cfg`/`render.mk` (builds `ftest`
with the clip log, `fprof` with the phase marks, `rcard`, milestone 5's
replay linked in). Host tools: `levelconv.py` (the weapons' profiles in
`WPRO`, revision 3; `fuzzdark.bin`), `framestate.py` (`FRVIS`, `WPREV`
native), `rcanon.py` (the clip pass's and the frame end's canon),
`bucketcheck.py` (the batches against `loader.py`, `BATCH_BYTES`),
`frame8.py` (the whole frame, the poisoned screen, the timing report),
`framesynth.py` (`invis`, `flash`, `skipwall`, `wphigh`), `rdisk.py`
(the disk image and its a2vm run). Tests: `tests/test_native_frame8.py`.

### Checkpoint C

| Item | Command | Result |
| --- | --- | --- |
| 1. Acceptance 1 | `python3 tools/native/frame8.py --sets m7,demo3 --timing --poisoned --report build/native/render/report8.md --json build/native/render/frame8-all.json` | 734 frames: milestone 7's 188, the 13 synthetic frames (stages A and B's 9, stage C's 4) and all 533 `demo3` frames, both fills: **1,468 runs equal**. In each: `FLOORCLIP`, `FRVIS` and `MM_WPOK` after the clip pass equal P1's; the front end's outputs at the walk's end; the vissprites, order and skip; the records to the weapon's draw (P3w); at the masked phase's end every record of the frame by column (926,390 records in all), the covered ranges and their records, spans, the page model, `FZPOS`, the clips, the weapon skip (`FR_SKIP`, `W_WSK`, `WPREV`, `WCLIP`), `FRVIS`, `MM_WPOK` and the clip log against the call log (9,137 calls) equal P4's; each batch (1 to 3; 2 in 93 frames) against `loader.py`'s packing and `mark_fuzz` (922 `K_FUZZNOW` marks); **all of aux 0 `$2000-$9FFF` equal to P5**, byte for byte; the SHR writes equal the model's screen stores (15,707,060 in the `$A5` runs); no other video page written; 0 stray writes by phase; at most 83 B of stack (+24 B of IRQ, within 112). **0 frames with `RULES` ≠ 0.** Composed input screen: `synth-pagefull` only (1 flush, 4,654 bytes from P2). The **69 poisoned screens** (the 15 `m5` frames, every tenth `demo3` frame) equal their `--call` truth (each changed at least 8,415 pixel bytes of the poison) |
| 2. Acceptance 2 | `python3 tools/native/rdisk.py --check` | `build/native/RENDER.hdv` (4,953,088 B): `demo3-020` .. `demo3-119` (the window with the most shadows, 47, then sprite columns, 14,497; no flush, no `RULES`). On a2vm through its MLI trap and memory API: **every one of the 100 CRCs equal to `ref816`'s, chained and full, under `f121` and `fastpath`** (400 of 400); the static load makes no video write outside the screen, leaves `$0878-$087F` alone, 2 memory-API requests (STATUS, one PRIVATE list); VBLs for the 100 frames: `f121` 477 chained, 473 full (10.5 FPS), `fastpath` 414 and 415 (12.1 FPS). The CRCs, for the owner's card run: `build/native/render/rdisk.json` |
| 3. The report | the command of item 1; `frame8.py --report-from build/native/render/frame8-all.json` writes it again with the disk's VBLs | `build/native/render/report8.md`; the figures below |
| Milestone 7 again | `python3 tools/native/render_check.py --frame-mode` | 201 frames, 402 runs, 0 failed (the front end with the native clip pass in place of the seam) |
| Tests | `python3 -m unittest discover -s tests` | 1,284 tests, OK (`test_native_frame8.py` 11 of them, 7 minutes for the whole suite) |

`frame8.py --sets demo3` alone (1,066 runs) was run first and is kept as
`build/native/render/frame8-demo3.json` (the disk's `--results`).

### What stage C changed, and why

| Design | As built | Why |
| --- | --- | --- |
| `FRVIS` 11 B at `$0CA0`, per frame (1.7) | 12 B at `$18B0`, persistent; `WPREV` 12 B | x2 is stored unclamped as two bytes before `pspSprite`'s off-screen test; upstream's `FR_VIS` keeps the fields a frame does not write (an absent or off-screen weapon writes some or none) and `weaponClipSame` compares them. 1.7 and 2.2 corrected |
| `CVW` over `SOLIDCOL`/`MCCLIP` and `WTMP`, copied into `CVREC` after the walk (3.4, 1.10) | `CVDONE` (160 B over `DSX1`): the W address goes straight into `CVRECLO`/`HI` and the flag stops the compare for that column | Stage B's open point: `WTMP` is persistent, so nothing may go over it; and no copy pass |
| The batch list in zero page (1.10) | `BK_FIRST`/`BK_SZLO`/`BK_SZHI` at `$1A20`, up to 26 batches (`MAXB`: the staging's 202,752 B / 8 KB + 1) | Zero page had no room for more than a few; the design's "batches 4 onward by further walks" needs the list. (The bound was wrong: corrected to 45 by the verification, below) |
| The bucket pass's main part in `$0C00-$0EFF` | `BKFAR` 709 B there and `BKFAR2` 253 B in main `$0200-$02FF`, both copied from the masked image by `nm_bkload` | 768 B were not enough once the groups, `CVDONE` and the 24-bit staging count were in |
| The staging's count 16 bits | 24 bits (`BK_REM`) | aux 0's 8 KB and four spill banks pass 64 KB |
| One file a frame read by the runner (4.6) | Three files loaded at boot, then ProDOS given up; each frame's chained and full data as run-length coded records in 69 store banks | The runner owns the language card; 4.6 corrected |
| The chained file: "the game state that changed" | The changed game bytes and every game byte the renderer's code may write (rlayout's allowed sets: the sectors' validcount stamps) | A byte the renderer wrote would otherwise keep the renderer's value |
| The runner waits for the drain | SHR left and entered, then a `$Cxxx` read, before each frame's count | The fast path's lazy mirror holds a full frame's screen until SHR is left: without it the next frame paid 27 ms (`fastpath` full 508 VBLs, now 415) |
| `wddraw` reads the patch header the clip pass fetched | `mwp_head` again in the masked phase | The front end's W copy is gone by then (the node frames overwrite it): 5 frames (`synth-qmulh`, `title-29`, `-34`, `-36`, `-37`) drew from a wrong bank until fixed; kept as a planted bug |
| The masked comparisons at `nm_psp` | A card hook `m_hook` (test builds) | W's addresses are shared by both images, so a PC event at a W address fires in the front end too |
| The poisoned truth from `base-entry.img` (4.2) | `m5` frames from their own capture's context (`build/captures/NAME`), `demo3` frames from the base image with P4's ranges | The base image is a `demo3` state: an E1M1 frame's texels are not in it (`still-1`'s check "--call gives P5" failed) |
| — | `frame8.py` keeps one snapshot a batch (`BK_B` distinct) | An interrupt returning to `nat_replay`'s first instruction fires a2vm's every-visit event again (`demo3-429`) |
| — | `framestate.py` requires `W_WSK` = 0 at `R_FillStamps` | Upstream clears it at every frame's end (`playerSkip`); a capture that does not fails by name |

4.7's planted bugs as they turned out: `wdProf`'s order shows only
where a column has two posts above `V_HI` (`newgame-20`, column 80);
`wclipSprite` missing only where a sprite reaches the weapon rows
(`demo3-372`; `synth-skipwall` has none); a covered range's W address
one byte off and a batch starting a column late stop the replay (a
record of a wrong kind: `BRK`) before the bucket check reads them; and
"the input screen taken from P4 whole" is **not observable** on
`synth-pagefull`, the only flush frame: the 4,654 bytes the flush wrote
are all drawn again by the frame's records (no pre-flush shadow reads
them), so the test checks the composition itself and that both inputs
give P5.

### Sizes (3.7)

| Part | Built | Budget |
| --- | ---: | ---: |
| Front end: `wclip.s` 420 B, `wpsp.s` 1,097 B | 1,517 | 1,550 |
| `RENDERW` (`ftest`; `fprof` with the marks to `$A37E`) | 15,793 to `$A343` | 17,160 |
| Masked: `mpsp.s` 421 B, `wpsp.s` again 902 B | 1,323 | 1,400 |
| Masked image `MASKW` (`ftest`) with `nm_bkload` 48 B | 8,810 to `$8A69`, 9,772 with `BKFAR`/`BKFAR2` as data | 13,312 |
| Bucket pass: `BKNEAR` (card `$FD8D`), `BKFAR` (`$0C00`), `BKFAR2` (`$0200`) | 238, 709, 253 | 371, 768, 256 |
| `RENDER.SYSTEM`: boot 719 B at `$2000`; runner 1,993 B and its data 4,007 B from `$E000` (catalog 1,664, results 800, CRC tables 1,024) | `$E000-$F76F` | `$E000-$F8FF` |
| Weapon profiles (`WPRO`, E1M7) | 26,793 B, 28 lumps | one bank |

### Timing (a2vm, not the card)

`report8.md` (`fprof`, fill `$A5`), ms a frame from the front end's
window to the replay's last SHR write, median (worst):

| Set | Frames | `f121` | `fastpath` | Clip pass | Weapon | Bucket | Replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| still | 3 | 64.26 | 57.66 | 0.46 | 0.63 | 9.42 | 17.11 |
| newgame | 50 | 64.26 (110.08) | 57.66 (100.32) | 0.46 | 0.69 | 9.12 | 30.10 |
| m5 demo | 11 | 58.84 (102.86) | 54.84 (92.19) | 0.61 | 0.91 | 5.21 | 31.66 |
| tour | 50 | 57.15 (112.64) | 52.91 (101.44) | 0.46 | 0.65 | 7.69 | 26.13 |
| demo3 | 533 | 72.54 (164.53) | 66.71 (139.58) | 0.61 | 0.97 | 7.39 (30.27) | 33.80 (80.90) |

Against 6.2's table: standing still 64.3 ms (estimate 63-64), the
`demo3` median 72.5 ms (66-67: the bucket pass and replay heavier than
their rows at the median), the worst frame 164.5 ms (`demo3-036`: 39.5
front end, 24.0 masked, 30.3 bucket, 70.8 replay), above 6.2's heavy
column of 120-127 ms, which added each phase's worst from different
frames: one frame reaches all of them at once. With `NATIVE.md` 6's
tics: **still 14.1-14.9 FPS, the `demo3` median 8.8-11.0 FPS, the worst
frame 4.9 FPS**; 3 of 533 `demo3` frames fall under 6 FPS with 18.4 ms
of tics, 10 with 41.3 ms (`demo3-036`, `-052`, `-114`, `-343`, `-344`
and neighbours: the close fight). `NATIVE.md` 1.1's 36-75 ms still and
61-127 ms demo hold for the median, not for the heaviest frames. By
VBL count on the disk's 100 frames: 10.5 FPS (`f121`) and 12.1
(`fastpath`), render only. `fastpath` saves 8-15%.

The heaviest frames are the section 7 open point: optimisations 4 and 10
(the bucket pass and the replay: 30 + 71 ms of `demo3-036`'s 165) are
the candidates before milestone 12; the owner decides (section 7).

### Open points of stage C

- **The heaviest `demo3` frames are under 6 FPS** by the tic estimate
  (3 to 10 of 533 frames, the worst 4.9 FPS): section 6.2's
  optimisations 4 and 10 (bucket pass and replay) are the candidates.
- **6.1's column limit in the game build is not built**: a column with
  more than 125 texture records (the replay's 16 KB stage) stops the
  frame in every build, the release build too, where 6.1 says it keeps
  its first 125 and flags `ST_RECORDS`; no frame comes near (`BKFAR`
  has 59 B left). The staging's `RECDROP` policy is built and tested.
  *(Built by the verification of stage C, below, with the batch list's
  bound and the last area's end.)*
- The runner's CRCs are a2vm's; the card run is milestone 12's.
- `rcard` uses `fprof`'s objects (their phase marks store to `$0300`,
  the frame block's page): the card's frames carry one store a phase
  mark, a few dozen cycles a frame, which the timing builds measure too.
- `RENDER.hdv`'s frames need 69 of the 74 free store banks: a window of
  heavier screens (more run-length bytes) could need more.

`build/` grew by about 12 MB in this stage (3,128,112 KB before,
3,139,896 KB after: `RENDER.hdv` 4.8 MB, the four new synthetic frames,
the reconverted levels' profiles and `fuzzdark.bin`, the results' JSON),
temporary output deleted after each run.

## Verification of stage C (2026-10-01)

An independent verifier reproduced acceptance 1, acceptance 2 and the
timing report (its `report8.md` byte-identical to the builder's) and
reported 7 defects. Each was checked against the code and the evidence;
none is rejected. Items 1, 3, 4, 5 and 6 are fixed with tests; 2 and 7
are for the owner.

| # | Defect | Checked | What was done |
| --: | --- | --- | --- |
| 1a | The game build (`-D RELEASE`) took a batch ending exactly at `STAGE_END` in the last area; the copy's step at `$C000` then looked for an area after the last and stopped the frame (`ST_RECORDS`, `BRK`). The test could not see it (its last area was aux 0, after which the copy steps to the spill) | Confirmed: `rec_flush` called alone on such a batch ends the run at the `BRK` | `rrec.s`: a batch whose end reaches `STAGE_END` in the last area is dropped like one past it (the last area's last byte is never used). Test `ReleasePolicy.test_the_last_area_s_end`: `rec_flush` alone (`drv_bulk`) on 9 batches before, at and past the last area's end and across the areas before it; it fails on the old code |
| 1b | `MAXB` = 26 (capacity / 8,192 + 1) is the wrong bound: whole columns only promise that two adjacent batches pass 8,192 bytes together; a frame of more batches stopped the pass in every build | Confirmed: 45 columns of 4,097 W bytes (201,150 B staged) stop a 26-entry pass | `rlayout.py` proves the bound: W holds at most 11/12 of the staging (185,856 B), n batches hold at least (n // 2) × 8,182 B (8,193 for two adjacent batches; 8,182 for a batch ended by a cut column, below), so MAXB = 45. The list moved: `BK_FIRST` (46 B) to zero page `$71-$9E` after `BK_NB`, `BK_SZLO`/`HI` (45 B each) over `DSX2` (`MEMORY_MAP.md` 13). Test `BucketLimits.test_the_most_batches`: that staging takes 45 batches, each equal to the loader's |
| 1c | 6.1's per-column limit was not built: a column past 8,192 W bytes stopped the bucket pass, one past the replay's stage stopped the replay, in the game build too | Confirmed (the builder had disclosed it) | Built in the game build (6.1 "As built"): the bucket pass cuts such a column at its first record past 8,192 bytes (`CVDONE` bit 7, its batch ends with it, walk 2 leaves the rest out, a covered range whose record was cut is cleared); the replay draws a column alone past its stage with the records gathered before the first that did not fit; both set `ST_RECORDS` (`bk_cut`). Test builds still stop. Tests: `BucketLimits.test_a_column_past_a_batch` (a 760-record column: the test build's `BRK`, the game build's batches against `bucketcheck.expected(release=True)`, `ST_RECORDS`); `ReleasePolicy.test_a_column_past_the_replay_s_stage` (the stage shrunk to 96 B on `still-1`: the game build completes with `ST_RECORDS` and no stray write, the test build stops) |
| 2 | The heaviest `demo3` frames are under the owner's 6 FPS | Confirmed: `demo3-036` 164.4 ms render only (4.9 FPS with 41.3 ms of tics); 3 of 533 frames under 6 FPS with 18.4 ms of tics, 10 with 41.3 | For the owner (section 7): optimisations 4 and 10 of 6.2 (the bucket pass and the replay, 30 + 71 ms of `demo3-036`'s 164) |
| 3 | A bucket pass that broke the batches was reported only as the replay's `BRK` | Confirmed: `check8` returned at the stop | `frame8.py`: after a stop it still runs the bucket check on the native staging (`mend`) against the batches handed to the replay before it, and names the problems beside the `BRK`. The planted bugs now require the bucket check's words: "a covered range's W address one byte off" (`covering record`), "a batch starting one column late" and the verifier's "a record lost at the bucket" (walk 2 skipping column 80's fills, on `still-1` and `demo3-053`) (`batch`) |
| 4 | `rlayout.py`'s capacity assertion used a hand-entered `LARGEST_STAGED` = 17,003 and left out the synthetic frames (`synth-pagefull` 26,089 B: 7.8 times) | Confirmed | 6.1 item 1 restated for the captured frames (the synthetic ones are made to fill upstream's pages and must only fit); `frame8.py` measures it on every run (`staging_margin`, in the report) and fails under it; the constant is gone. Test `StagingMargin` |
| 5 | `W_WSK` at `R_DrawLists` was derived (`0 if FR_SKIP else P3s's`), not captured | Confirmed | `rendercap.py` captures `$00:0AB0` at P4 and `rcanon.py` compares that value. All frames captured and synthesised again: every file byte-identical but the 734 `p4` dumps; `W_WSK` is 0 at P4 in all 734, as the derivation said |
| 6 | Counts stale: `tables.json` said 17 level sources, `rtables.py` reads 18 | Confirmed | `rtables.py` run again (the tables byte-identical, "the same tables in 18 level sources"); `levelconv.py --all`: all 18 pass every check; the counts corrected here and in `MILESTONES.md` |
| 7 | Stage B relaxed milestone 7's `test_native_render_frame.py` timing assertion (equal seg-loop cycles under both profiles became equal phase sums, equal interrupt counts, each phase within 100 cycles an interrupt) | Confirmed; the reason (the VBL interrupt lands by time, so in a neighbouring phase under the other profile) is sound | Left as it is, for explicit acceptance (the ground rules say never weaken a test). Accepted 2026-10-01 for the reason given: the old assertion was wrong, not the code (`MILESTONES.md` row 8). |

**Sizes after the fixes.** Test and timing builds: `BKFAR` 714 B (`fprof`
724) of 768, `BKFAR2` 233 of 256 (`covered` moved to `BKFAR`), `BKNEAR`
238; the replay unchanged. The game build adds the cut: `BKFAR` 755 (765
with the phase marks), `BKFAR2` 246, `BKNEAR` 301 B and the replay's
`RCODE` 62 B: the card's `$F900-$FEF7`, 1,528 of 1,536 B. Every build
links with no warning.

**Results after the fixes.**

| Item | Command | Result |
| --- | --- | --- |
| Acceptance 1 | `frame8.py --sets m7,demo3 --timing --poisoned --report build/native/render/report8.md --json build/native/render/frame8-all.json` | 734 frames, 1,537 runs (1,468 and the 69 poisoned screens): **all equal**, 0 known divergences (0 frames with `RULES` ≠ 0); 926,390 records, 9,137 clip-log calls; `W_WSK` against P4's capture. The staging: 202,752 B, 11.9 times the largest captured staging (`demo3-036`, 17,003 B); `synth-pagefull` 26,089 B, 7.8 times |
| Acceptance 2 | `rdisk.py --check` (window from `frame8-demo3.json`, the `demo3` runs of the run above) | `RENDER.hdv` rebuilt: 100 of 100 CRCs equal, chained and full, `f121` and `fastpath`; VBLs `f121` 467 chained, 472 full (10.7, 10.6 FPS), `fastpath` 417, 414 (12.0, 12.1) |
| Timing | `report8.md` (`f121`, render only) | still 64.14 ms, `demo3` median 72.40, worst 164.38 (`demo3-036`: 39.5 front end, 23.9 masked, 30.1 bucket, 70.9 replay); with the tics 14.1-14.9, 8.8-11.0 and 4.9 FPS; 3 (18.4 ms of tics) to 10 (41.3 ms) of 533 `demo3` frames under 6 FPS |
| Tests | `python3 -m unittest discover -s tests` | 1,289 tests, OK (7 minutes; `test_native_frame8.py` 16) |

`build/` grew by about 1.3 MB in this verification (3,139,972 KB before,
3,141,320 KB after: the results and logs; the frames, levels and tables
were rewritten at the same size), temporary output deleted after each
run.
