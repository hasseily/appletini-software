# src/native: the game in 65C02 assembly

The whole game for the Apple //e with the Appletini card: the renderer,
the level load, the game logic, the 2D screens, the effects' channel
logic, the platform (interrupts, clock, input), the main loop and the
boot. Assembled with ca65 and linked with ld65 (cc65 2.18). Most of it
is a GPL-2 derivative of upstream's 65816 sources (Doom8088: Apple IIgs
Edition); each file's header names the upstream routines it follows,
with line references into `build/upstream/src/iigs/`.

The design documents, which this README does not repeat:

| Document | What it covers |
| --- | --- |
| [`docs/PLAY.md`](../../docs/PLAY.md) | The main loop, the kernel and its step lists, the images and their loads, the boot disk |
| [`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md) | Every region of main, aux, the language cards and RamWorks |
| [`docs/RENDER.md`](../../docs/RENDER.md) | The renderer's front end: the native level, the BSP walk, the walls, the seg loops, the records |
| [`docs/RENDER-MASKED.md`](../../docs/RENDER-MASKED.md) | The masked phase: sprites, masked walls, the weapon, the bucket pass |
| [`docs/LEVELS.md`](../../docs/LEVELS.md) | The level store, the load program, the native `P_SetupLevel`, the zone |
| [`docs/GAME.md`](../../docs/GAME.md) | The game logic: the object API, the parts, code paging |
| [`docs/SCREENS.md`](../../docs/SCREENS.md) | The 2D screens, the platform and the effects |
| [`docs/SPEED.md`](../../docs/SPEED.md) | The speed work: the frame slots, the copy engine |
| [`MATH.md`](MATH.md) | The math routines (`math.s`) |

## How the game is built

`build.sh` in `demos/doom_gs` builds `build/native/DOOM.hdv` from
nothing. The steps for this directory, from `demos/doom_gs`, after
`tools/native/rendercap.py` and `tools/native/rtables.py` have made the
render tables:

```
make -C src/native -f render.mk         # the renderer: rcard (release)
python3 tools/native/wadconv.py --store # the level store
make -C src/native -f level.mk          # the load image: lcard
make -C src/native -f m11.mk            # the 2D images and their data
python3 tools/native/playdisk.py        # play.mk's links, then DOOM.hdv
```

`playdisk.py` runs `make -f play.mk` itself (the tic image, `P2DW`,
`DLINIT`, `DOOM.SYSTEM` and the card), and `play.mk` runs `level.mk`
first, so a layout change never leaves the load image stale.

| Makefile | Into | Targets |
| --- | --- | --- |
| `render.mk` | `build/native/render/obj`; `stops`: `build/native/render/stops` | `all` = `release` (`rcard`, `-D RELEASE`: the disk's), `stops` (the same `rcard` without it: every limit a `BRK`), `clean` |
| `level.mk` | `build/native/levels/obj` | `all` (`lcard`), `clean` |
| `m11.mk` with `m11/*.mk` | `build/native/m11/<part>/` | `all`, `images`, `sizes`, `check`, `gen`, `part P=NAME`, `clean-part P=NAME` |
| `play.mk` | `build/native/play` | `all` (= `card`), `gen`, `p2dw`, `init`, `tic`, `card`, `lcode`, `sizes`, `clean` |

Each makefile's header lists what it writes. The ld65 maps
(`render.cfg`, `level.cfg`, and the maps `tools/native/s2layout.py`,
`glayout.py` and `playlink.py` write) give each region of MEMORY_MAP its
own MEMORY area, so an overflow fails the link.

Where the disk takes each piece from (`tools/native/playdisk.py`):

| Piece | Built by |
| --- | --- |
| The render images (`RENDERW`, `MASKW`), the card's math, far layer, phase loader and replay, the static main and aux 0 tables | `render.mk`, link `rcard` |
| The load image (`LCODE`) | `level.mk`, link `lcard` (its `.lw` part) |
| The 2D images `MENUW`, `AMAPW`, `WIW`, `FINW`, `PALW`, `OVLW`, and the 2D store, effects and HUD text files (`GFX.1`, `SFX.1`, `HUDTXT.1`) | `m11.mk` |
| The tic image (`GCODE0`, `GCODE1`), `P2DW` with the frame glue, `DLINIT`, `DOOM.SYSTEM` with the kernel | `play.mk` |
| The music player | `src/sound` |

`rcard` and `lcard` also link the standalone card runners `rrunner.s`
(`RENDER.SYSTEM`) and `lboot.s` (`LEVELS.SYSTEM`) into their boot and
`$E000` parts; the game disk does not use those parts. Likewise the 2D
parts' links in `m11/*.mk` carry an a2vm driver in the card (`s2_drv.s`,
or `s2_ovd.s` for `OVLW`), which the disk does not take; `s2_stt.s` and
`s2_menut.s` are the `s2stbar` and `s2menu2` links' glue (the disk's
`P2DW` is `play.mk`'s link instead).

## The pieces

### The record replay (`replay.s`)

Upstream's column records in, the 3D view's SHR bytes out. The row
blocks and tables come from our own generator, `tools/native/rowgen.py`
(from `tools/native/layout.py`, which holds every address of the
replay), not from upstream's `gendraw.py`. The addresses are
MEMORY_MAP section 9.

`nat_replay` (A = the batch's first column, X = the column after its
last) draws one batch of records from W `$6000-$7FFF`, in strips of
whole columns:

1. **Gather: walk.** RAMRD off. Each texture record (`K_TEX`, `K_TEXC`)
   of the strip gets its place in the texel stage (W `$8000-$BFFF`) and
   a 12-byte copy descriptor in page 1; the stage pointer the draw will
   use goes on a list at the stage's top. A column that does not fit
   the stage ends the strip before it.
2. **Gather: copies.** Every 12 descriptors (`MAXDESC`) and at the
   strip's end: RAMRD on; for each RamWorks bank one `$C073` write and
   all its copies; `$C073` 0, RAMRD off. A record whose chain's whole
   step is 2 or more and has at most 128 rows is copied one texel a row
   (the draw then steps by 1); otherwise the span of texels its rows can
   reach is copied (a span that wraps past texel 127 as its two runs).
3. **Draw.** RAMWRT on. For each column, its covered-range cut, then
   each record by kind: a texture record runs the row blocks from its
   first row's entry to its exit row (patched to `RTS` and restored); a
   `K_FILL` runs the even and odd fill chains; a `K_OVL` runs its drawer
   from aux 0 `$0200` with RAMRD on; a `K_FUZZ` goes into the fuzz queue;
   a `K_FUZZNOW` (and a `K_FUZZ` the full queue has no room for) is drawn
   in place. After the strip: the queued fuzz records in one RAMRD
   window, RAMWRT off, the strip's covered ranges zeroed.

The texture row pair (36 bytes) advances the texel position exactly
twice the step, the even row taking the rounded half-way texel, as
upstream's pair image does; each row reads its texel from the stage,
looks it up through the colormap pointer and stores it at
`$2000 + 160 × row, X`: 31.5 cycles a row. The replay enters with
`$D000` bank 1 selected and selects bank 2 (the row blocks and the draw
pass) for its run.

**The fuzz queue.** A fuzz record reads the screen, so it runs with
RAMRD on, and on F1.2.1 each RAMRD switch waits for the firmware to send
every screen byte written so far to the motherboard; scattered bytes
drain slower than whole pages. So the draw queues fuzz records (four
arrays of 80 bytes at aux 0 `$02C0-$03FF`) and draws them after the
strip's columns in one window. A fuzz record must be drawn in place
when a later record of its column paints a row it reads or writes
(`R_ROW - 1` to `R_ROW + R_COUNT`); the bucket pass marks those as the
port's own kind `K_FUZZNOW` (4), which upstream never uses.

What differs from upstream: the replay never writes into records (it
keeps `texStart` and `fillStart` in zero page) and does not reset the
lists; the covered ranges are zeroed per strip, not per column; the fill
blocks are two chains (even and odd rows, `$DC00` and `$DD00`), since
the 65C02 has no `STY abs,X`; page 1 `$0100-$01B4` holds the
descriptors and the per-row copy loop, so the stack stays at or above
`$01C0`. A column that needs more than the 16 KB stage is cut in the
release build (the disk's): `bucket.s`'s `rp_cut` draws it with the
records gathered so far, without its covered range, `STATUS` =
`ST_RECORDS`; the `stops` build stops at a `BRK`.

### The renderer's front end

From `R_FillStamps` to `drawMasked` ([`docs/RENDER.md`](../../docs/RENDER.md)).

| File | What it is |
| --- | --- |
| `rframe.s` | `nr_frame`: the plane stamps (`nr_fillstamps`), the frame setup (`nr_setup`: the view, the light numbers, `validcount`), the clears (`nr_clear`), the weapon's clip pass, the weapon skip (`nr_wskip`), the walk, the last batch |
| `rbsp.s` | `nr_bsp`: the recursion over node frames in W, `nr_side`, `nr_checkbox`, the subsectors, the seg loop and `clipwall`, the vertex-angle cache; `nr_addsprites` lists each sector for the masked phase |
| `rlight.s` | `nr_planes` (the sector's plane colours and worldbottom), `nr_walllight` |
| `rwall.s` | `nr_storewall`: `R_StoreWallRange` (the drawseg, the scales, the heights, marks and textures, the edges, the silhouettes, the clips saved for the sprites) |
| `rseg.s`, `rseg.inc` | `nr_segloop`: `R_RenderSegLoop`'s prologue and loop choice, genColumn, the masked-only loop, texCol with its exact texture u, the tiers' `K_TEX` records, the fills' `K_FILL` records and spans; the loops' macros |
| `gen/segloops.s` | The 13 loops of upstream's `segvar.inc`, written by `tools/native/seggen.py` (build output) |
| `rsky.s` | `sky_col` (the sky as a `K_TEX` of its slot) and `tier_flat` (a column without a patch as a `K_FILL`) |
| `rrec.s` | The 256-byte record batch in W and its staging (aux 0 `$A000`, then the spill banks); `rec_room`, the model of upstream's list pages; assembled again with `-D MREC` for the masked image |
| `wclip.s` | `nw_clip`: the weapon's clip pass into `FLOORCLIP` and `FRVIS` |
| `wpsp.s` | The weapon code both images share (`ps_vis`, `wp_find`, `wp_start`, `wp_list`), assembled twice (`-D MPSP` for the masked image, its names with an `m` before them) |
| `auxlc.s` | The aux card's table reads in `ALTZP` windows: `ax_vtox`, `ax_tanto`, `ax_tan3`, `ax_tan4` |
| `far.s` | Card bank 1 from `$DC43`: `far_get`, `far_put`, the vertex-angle gather and write-back, the `FSTEP` gather, the phase loader `far_pload` and `far_wload` |

A frame starts with the phase loader: one RAMRD window copies the render
window's image (the code from `$6000` and the level's tables) from
RamWorks into W. The walk fetches each node whole into a node frame of
W, recurses into the front child and continues into the back child when
its box is visible. A subsector's sector comes into the sector frame
with its plane colours; its segs come five at a time into a bounce
buffer at `$0200`, are clipped to the view's columns, and `clipwall`
calls `nr_storewall` for each open run, as upstream calls
`R_StoreWallRange`. Records go into the batch in W with their column
byte and are flushed to the staging in one RAMWRT window an area.

The results equal upstream's, bit for bit, with upstream's shortcuts
kept (`qmulh`'s "+ 0 or 1", scaleFast's 1.001 step, rowMod). Where
upstream reads past its tables (a wall seen from behind at a grazing
angle), the native code takes a rule of its own (RENDER.md, "Rules of
our own, and the stops": the scale 256, the tangent table's nearer end) and
sets its bit in the frame block's `RULES`. A texture without slots
(`ST_TEXTURE`) and full node frames (`ST_DEPTH`) set the status and
stop at a `BRK`. A full staging (`ST_RECORDS`) does too in the `stops`
build; the shipped build (`-D RELEASE`, render.mk's default) drops the
batches that do not fit, sets `ST_RECORDS` and completes the frame
(`docs/RENDER-MASKED.md` 10).

### The masked phase and the bucket pass

[`docs/RENDER-MASKED.md`](../../docs/RENDER-MASKED.md); the regions:
its section 3.

| File | What it is |
| --- | --- |
| `mmain.s` | `nm_masked`: the drawsegs copied into W's `DSW`, `SPRBOUND` into W, the projection and sort, then `drawMasked`'s loops (the sprites back to front, then the drawsegs' masked columns) and the last batch |
| `mproj.s` | `nm_project`: each listed sector's things projected as upstream's `R_AddSprites` and `R_ProjectSprite`; `nm_sort`, the stable sort into `FRORD`, and `sortSkip` |
| `msprite.s` | `nm_drawsprite` (`R_DrawSprite`: the clips from the drawsegs and silhouettes, the masked ranges behind the sprite drawn at once) |
| `mvis.s` | `nm_vis` (`R_DrawVisSprite`: the posts as records, the magnified runs, the shadows) |
| `mwall.s` | `nm_mwall` (`R_RenderMaskedSegRange`: the masked mid textures' posts as `K_TEX` and `K_TEXC` records) |
| `mpsp.s` | `nm_psp`: the weapon (from its profile, or `R_DrawVisSprite`) and the flash |
| `mfar.s` | Card bank 1 (`MFAR`): `far_mload` (the masked image into W), `far_dscopy`, `far_posts`, `far_postsc` |
| `bucket.s` | The bucket pass: `nm_bkload`, then `nb_frame` cuts the staged records into batches of whole columns (at most 8,192 bytes), scatters them into W, turns each covered range's record into its W address, marks `K_FUZZNOW`, and calls `nat_replay` for each batch. With `-D RELEASE` (the disk's) it counts the columns again from the staging after a dropped batch or with a column past 8,192 bytes (walk 1: such a column is cut and alone in its batch), and holds the replay's cut `rp_cut` |
| `rdriver.s` | `drv_fframe`, assembled with `-D MASKED -D FRAME8` (`rdriver-f.o`): the frame image `m11/s2ovl.mk` links `OVLW` against |

The walk lists sectors instead of projecting; the masked phase projects
them in the same order, so the vissprites and their order are
upstream's. The overlay of the automap (`OVLW`, below) runs between the
masked phase and the bucket pass.

### The level load

[`docs/LEVELS.md`](../../docs/LEVELS.md); the regions: MEMORY_MAP
sections 4 and 8. Built by `level.mk` into the load image `lcard`, which
runs in W during a level's load.

| File | What it is |
| --- | --- |
| `lload.s` | `nl_load(A = the map)`: the store's directory, the map's header and load program, its steps in order (`VARIANTS`, `COPYREQ`/`PRIVREQ` through the memory API, the static steps, `SPAWN`, `SPECIALS`); a stop stores its code in `LV_STATUS` |
| `lgeom.s` | The static steps: `LINES`, `GROUP`, `FLOOD`, `CMAPS` |
| `lsetup.s` | `nl_setup(A = the map)`: `P_SetupLevel`: the totals, the thinker list and zone empty, then `nl_load` with the game's steps |
| `gspawn.s` | `SPAWN`: the level's globals, `P_SpawnMapThing` for each map thing |
| `gweap.s` | `P_SetupPsprites`, `P_SetPsprite`, `A_Raise` |
| `gspec.s` | `SPECIALS`: `P_SpawnSpecials` (the load image's only) |
| `lboot.s` | `LEVELS.SYSTEM`'s boot and runner (see above: not on the game disk) |

### The game core and the tic image

[`docs/GAME.md`](../../docs/GAME.md). The game core, shared by the load
image and the tic image:

| File | What it is |
| --- | --- |
| `gobj.s` | The object API: the mobj cache and the game objects' groups; the parts read and write objects only through it |
| `gthink.s` | The thinker list, the mobj slots, the thing pool, the zone's slots, the sector nodes, the game globals' far access, `P_Random` and `M_Random` (`g_random`, `g_mrandom`) with their table |
| `gpos.s` | `R_PointInSubsector`, `P_SetThingPosition`, `P_CreateSecNodeList`, the block lists |
| `gvalid.s` | `validcount`; on a wrap every sector's and line's stamp is cleared and the count restarts at 1 (upstream's wrap is not kept): in the game through `go_stamps0`, which flushes the line and sector caches first; in the renderer (`-D GV_RENDER`) by its own `gv_clear` |
| `gcall.s` | The code paging of the tic image: `fc_call` (`FCALL` to a routine in another group), the group loads into the slots, the dispatch tables |
| `game/<part>/` | The 29 parts of the game logic, each a `part.mk` (its sources, entries and wave) and its sources |

The parts: `attack`, `chase`, `chasemove`, `checkpos`, `damage`,
`evfloor`, `evworld`, `flow`, `geom`, `lines`, `look`, `missile`,
`mobjstate`, `movers`, `path`, `pickup`, `planes`, `player`, `pspr`,
`secfind`, `sight`, `spawn`, `teleport`, `tic`, `tracel`, `tracet`,
`trymove`, `wfire`, `xymove`. `play.mk` links every part whose wave is at
most the number in `game/integrated.txt` (6: all of them).
`tools/native/glayout.py` makes the tic image's layout and link map, and
the placement of its routines in the core and the groups comes from
`build/native/game/shared/placement.json` (`build.sh` copies
`tools/native/gplace-f122.json` there; docs/SPEED.md 6).

### The main loop and the glue

[`docs/PLAY.md`](../../docs/PLAY.md). Linked by `play.mk`.

| File | What it is |
| --- | --- |
| `dl_kern.s` | The resident kernel in the main card at `$FF00` (and its menu loop in main `$0880-$08FF`, `$0B94-$0BFF`): runs the step list the brain writes into `DLBUF` each frame |
| `dl_brain.s` | The main loop's brain in the tic image: `D_DoomLoop`'s tic running, the event routing, `G_Responder`, the cheats' key matching |
| `dl_cmd.s` | `G_BuildTiccmd` and the weapon switch |
| `dl_disp.s` | `D_Display` as the kernel's steps; the other step lists (boot, load, menu, quit); the render inputs of the player's view |
| `dl_hook.s` | The tic phase's hooks into the status bar, HUD, finale and sound |
| `dl_snd.s` | The songs and the title loop |
| `dl_init.s` | `DLINIT`, the one-shot image: the static tables by one memory-API request of PRIVATE copies; the settings of `DOOM.SETTINGS` applied at the boot and SAVE SETTINGS's block write by the boot device's driver (docs/PLAY.md, "The settings file") |
| `dl_p2d.s` | `s2_frame`, the level frame's 2D in `P2DW` |
| `dl_sym.s`, `dl.inc` | The card routines the tic image calls; the glue's groups and calls |

### The 2D screens, the platform and the effects

[`docs/SCREENS.md`](../../docs/SCREENS.md); the regions: MEMORY_MAP
sections 4 and 8. One fragment a part in `m11/`:
`make -C src/native -f m11.mk part P=NAME`.

| File | What it is | Part |
| --- | --- | --- |
| `s2_draw.s`, `s2_pub.s` | The patch drawer into a band of W, raw rows, rectangles, the marks; `s2_publish`, the marked bytes to aux 0 | shared |
| `s2_pal.s`, `s2_nib.s`, `s2_palw.s` | Palettes, tints, gamma, SCBs, the finish and the wipe; the nibble tables; `PALW` builds a level's tints and nibble tables | `s2pal` |
| `s2_st.s`, `s2t_st.s` | The status bar and face in `P2DW`; `ST_Ticker` in the tic image | `s2stbar` |
| `s2_hu.s`, `s2t_hu.s` | The HUD's drawer in `P2DW`; `HU_Ticker` in the tic image | `s2hud` (`HUDTXT.1`; the drawer is linked by `play.mk`) |
| `s2_menu.s`, `s2_mvid.s`, `s2_menu2.s` | `MENUW`: the menu engine and pages, the gray view, the settings, the key setup, the save slots | `s2menu2` |
| `s2_am.s`, `s2_amline.s`, `s2_am.inc` | `AMAPW`, the full automap; the window, transform, clip and line loops shared with `OVLW` | `s2amap` |
| `s2_ovl.s` | `OVLW`, the automap overlay's `K_OVL` records | `s2ovl` |
| `s2_wi.s` | `WIW`, the intermission | `s2wi` |
| `s2_fin.s`, `s2t_fin.s` | `FINW`: the finale, the pages, the loading screen, the busy sign; `F_Ticker` in the tic image | `s2fin` |
| `pl_irq.s` | `pl_vbl`, the IRQ entry: the tic clock, the effects' step, the music's tick; `pl_time`, the PAL or NTSC detection | `plboot` |
| `pl_input.s`, `pl_keys.s`, `pl_input.inc` | `pl_poll` (keyboard, Apple keys, mouse card) in every frame image; the key table's routines | `plboot` |
| `fx_chan.s`, `fx_pcache.s` | Upstream's sound channel logic, one mailbox a channel (the player is `src/sound/fx.s`); `MENUW`'s position callback | `s2menu2`, tic image |
| `pl_boot.s` | `DOOM.SYSTEM`: the probes, `DOOM.SETTINGS` and the boot device's block driver, every bank file into RamWorks with its CRC, the card images, the ready state | `plboot` |

Other fragments: `s2data` (the 2D store `GFX.1`, `tools/native/s2data.py`)
and `fxconv` (the effects `SFX.1`, `tools/sound/fxconv.py`).

### The math

`math.s`, `math.inc`, `mathgame.inc`: see [`MATH.md`](MATH.md).

## The host tools

In [`tools/native`](../../tools/native); each module's docstring gives its
usage.

| Tool | What it does |
| --- | --- |
| `layout.py`, `rowgen.py` | The replay's addresses; its row blocks, fill chains and tables (`layout.inc`, `rows.s`) |
| `rlayout.py`, `seggen.py` | The renderer's addresses, banks, records and zero page (`rlayout.inc`); the 13 seg loops |
| `rendercap.py`, `rtables.py`, `mathtables.py`, `mathdefs.py` | The release run on ref816; the renderer's and the math's constant tables taken from its memory and checked |
| `levelconv.py`, `wadconv.py`, `maplumps.py`, `lstore.py`, `lderive.py`, `umodel.py` | The WAD's levels, textures and sprites into the native level and the level store |
| `llayout.py`, `lrun.py` | The load's and the game state's layouts (`llayout.inc`, `lgame.inc`); the `lcard` link read back |
| `glayout.py`, `gcallgraph.py`, `gplacerec.py`, `grun.py`, `gplace-f122.json` | The tic image's layouts, dispatch tables and group placement |
| `s2layout.py`, `s2run.py`, `s2cap.py` and the parts' `s2*.py` | The 2D images' places and links, and each part's generated include |
| `playlayout.py`, `playlink.py`, `plkeys.py` | The glue's places; the links that join the images; the key table |
| `playdisk.py`, `pldisk.py`, `prodosvol.py` | `DOOM.hdv`: the images into bank files, the card images, the ProDOS volume; `playdisk.py --run SCRIPT` plays it on a2vm |
| `amcpu.py`, `nomouse.py`, `vidhd.py` | The patches `DOOM.SYSTEM` applies without the memory API, without the Appletini's mouse card, or with a VidHD (PLAY.md 8.1, 8.2, 8.3) |
| `render_check.py` | A native link's labels and segments, and a render build's image records (used by the disk builder) |
