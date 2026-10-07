# Level loading

How a map gets from `DOOM1.WAD` into the 65C02's memory: the host
converter that builds the level store, the store's place in RamWorks,
the load program that copies a map into the level window, and the
native `P_SetupLevel` with its zone. The renderer's level layout is
[`RENDER.md`](RENDER.md) 3 and [`RENDER-MASKED.md`](RENDER-MASKED.md);
the game logic that runs on the loaded level is [`GAME.md`](GAME.md);
every address is in [`MEMORY_MAP.md`](MEMORY_MAP.md).

Upstream file citations (`p_setup65.s:100` and so on) are to
`build/upstream/src/iigs/`; upstream's host tools are in
`build/upstream/tools/` and are read to learn formats, never run.

## 1. Overview

| Piece | What it does | Where |
| --- | --- | --- |
| The converter | `DOOM1.WAD` and the release image into the level store: nine level parts, a shared texel store, a shared patch store, the game's constant tables | Host: `tools/native/wadconv.py --store` |
| The store | Four bank files on the boot disk, loaded whole into RamWorks at boot; no disk read happens in play | `build/native/levels/store/` |
| The load image | `LCODE`: the load program's runner, the static steps, `P_SetupLevel`, the game core, the object API | `src/native/level.mk` → `build/native/levels/obj/lcard.lw` |
| The load | Run by the kernel when a tic asks for a level: the image into W, `nl_setup(map)`, back to the tic image | [`PLAY.md`](PLAY.md), `dl_disp.s` `c_loadlist` |

`build.sh` runs the converter, then `level.mk`; `play.mk` runs `level.mk`
again before its own links, so a layout change never leaves the load
image stale. `tools/native/playdisk.py` puts the store's bank files and
`LCODE` (in `CODE.1`) on `DOOM.hdv`.

Ground facts the design rests on: 8 MB of RamWorks (banks 1-126; bank
127 is never used), any load time is acceptable, and the level data in
RamWorks must reproduce what upstream's renderer reads byte for byte,
including the bytes it reads past the end of a lump or column (the
"tails", 2.2).

## 2. The converter

### 2.1 Tools

All in `tools/native/`, standard-library Python, no reference run:

| File | Role |
| --- | --- |
| `wadconv.py` | The entry point (`--store`). Reads the inputs, converts each map through `umodel.py`'s model, hands the result to `lstore.py` |
| `maplumps.py` | Our transforms of `DOOM1.WAD`'s map lumps, `TEXTURE1` and `PNAMES` into the form upstream's `P_SetupLevel` reads (its docstring lists each lump's form); the flat numbering paired with the release's `SECTORS` |
| `umodel.py` | The model of upstream's memory at the end of a load: the level window after `W_LoadSet`, the column memory after `R_MakeLevelColumns` and `W_LevelDone`, and the banks around them |
| `levelconv.py` | The renderer's level format (`render-level 3`): sector and side records, sprite frames, weapon profiles, the W and masked tables |
| `lderive.py` | The line tables and flood lists on the host (`groupLines`, `P_InitFlood`): their sizes go into each map's header; the 65C02 computes the bytes at load |
| `lstore.py` | The store's format and builder: blocks, the directory, the load programs, the memory-API requests, the variant lists, the bank files, `store.json` |
| `llayout.py` | The bank map, the level window's records, the store's constants, the load's W and zero page; writes `gen/llayout.inc` and `gen/lgame.inc` (the game state's places and upstream's constants) |

The release is read with our own readers, `tools/v816/hdv.py` (the disk
image) and `tools/v816/b1.py` (the store's B1 units).

### 2.2 Inputs

| Data | Source |
| --- | --- |
| Patches, sprites, `COLORMAP` | `DOOM1.WAD`, verbatim |
| Map lumps, `TEXTURE1`, `PNAMES` | `DOOM1.WAD` through `maplumps.py`: `THINGS` filtered (other players' starts, deathmatch starts and multiplayer things dropped), `LINEDEFS` with vertex coordinates in place of numbers, `SIDEDEFS` packed, the blockmap packed by shared suffixes, as upstream's `wadtool.py` documents. Each result equals the release's game lump byte for byte |
| Each map's placement of its lumps in upstream's level window | The release's level store (set records and entries). Upstream's layout comes from a seeded search (`levelimg.py`) that no WAD determines |
| `GSVIEWn` (tints, pairs, colormap tables A and B), `GSFLATn`, the flat numbering, the lump directory's order, `CM_COLD` | The release: upstream's build invented them (k-means palettes, per-map lists) |
| `states`, `mobjinfo`, `weaponinfo`, `sprnames` | The release's memory, by symbol |
| The render tables (`FSTEP`, `RECIP_TABLE`, the math's) | `tools/native/rtables.py`, as for the renderer |

**The tails.** A record's rows can read up to 127 bytes past its texel
pointer ([`RENDER.md`](RENDER.md) 3.2), and the first row of a post
usually reads texel 127. So sprite and masked columns read into
whatever follows their lump in upstream's window, and wall columns read
past their composed column into the next bytes of the column memory.
Those bytes reach pixels. The converter reproduces them exactly: it
rebuilds each map's upstream window from the release's store entries
(the common set first, as `W_LoadSet` does), models
`R_MakeLevelColumns` (the hot textures' columns kept off `$0900-$1FFF` of
their bank half, the holes, the two passes, `W_NEXTBANK`) and
`W_LevelDone`'s `moreColumns` (each made switch texture's partner, then
the slime frames, only while the column memory is below window bank 22,
`MORE_BANKS`), then zeroes the bank after the column memory. The tail
bytes stored are computed from that model on the host, never resolved
on the 65C02. A read the model does not cover fails the conversion,
naming the lump.

**Textures made in play.** Upstream makes a texture past `MORE_BANKS`
the first time a wall shows it. In E1 that is E1M2 (`SW2PIPE`,
`SW2SLAD`, `SW2STON1`, `SLADRIP1`, `SLADRIP3`) and E1M3 (`SW2BRCOM`,
`SW2BRNGN`, `SW2COMP`, `SW2DIRT`, `SW2STONE`). All ten are 128 high, so
their own columns have no tail. Natively every texture a level can show
is resident; no stored slot's bytes reach a byte such a run-time
allocation could change.

**History the load does not determine.** Upstream's `textureheight` is
never cleared, `levelFlats` writes only the map's flats into `FLATCM`,
and a sprite frame no thing uses reads its rotate and flip bytes from
memory past the sprite's frames. The converter writes each texture's
own height, 0 past the map's flats, and 0 for those two bytes. No
renderer reads any of them.

## 3. The store

### 3.1 Contents

**Shared, loaded once at boot:**

| Part | Content | Size |
| --- | --- | ---: |
| Texel store | One slot block per texture any map can show, made at load or in play, and the sky (256 columns): 128 bytes a column ([`RENDER.md`](RENDER.md) 3.2), the most common bytes of each column over the nine maps | 116 blocks, 1,302,528 B, 31 banks |
| Patch store | Every sprite lump and masked first patch a map stores, whole, then its 128-byte tail (the most common over the maps) | 410 lumps, 813,968 B, 17 banks |
| `PHDR`, `WPRO` | One header per stored lump (global index from 1, 0 the placeholder) in `SPRT`; the weapon profiles in `WPRO` | |
| `GTAB` | `states`, `mobjinfo`, `COLORMAP`, `switchlist`, `SW_IDX`, `animated_texture_basepic` | 17,262 B, one bank |

**Per map, a level part** in the `STORE` banks (the texel banks' slack
first): the blocks of `lstore.BLOCK_KINDS` (segs, nodes, subsectors,
sectors, sides, patchless bitmaps, the compact lines, the sectors'
special and tag, blockmap, reject, map things, the W tables, `TXMP`,
`SPRFR`, the whole `GSVIEWn` record, `FUZZDARK`), the variant lists and
their requests, a header and the load program. The nine parts total
870,047 B; the largest, E1M6, 145,679 B.

**Variants.** The maps share almost every slot and tail: 223 texel
columns and 131 patch tails differ from the canonical bytes. Each map's
part holds an apply list (its bytes) and an undo list (the canonical
bytes at the same places), each as 128-byte memory-API copies. Which
map's variants are in place is `LV_VARMAP` (main `$03A4`, a persistent
global: 0 for canonical, which is what the boot loads). Every load
undoes `LV_VARMAP`'s variants, applies its own, and sets `LV_VARMAP`,
even when the map is the same.

A map thing is 8 bytes: x, y, angle / 45, options, and its mobj type,
which the converter resolves as `P_FindDoomedNum` would (`$FE` the
player's start, `$FF` a thing no skill spawns). A compact line is the
game lump's 15 bytes.

Nothing is compressed; each block header keeps a codec byte, always 0.

### 3.2 Bank files and the boot

| File | Content | Bytes |
| --- | --- | ---: |
| `TEXELS.1` | The texel store | 1,302,784 |
| `PATCHES.1` | The patch store, `PHDR`, `WPRO` | 848,873 |
| `MAPS.1` | The nine level parts, their directory | 870,355 |
| `TABLES.1` | `GTAB` | 17,518 |

A bank file is "A2DM", version 1, a segment count, five bytes a segment
(bank, address, length), zero padding to 256 bytes, then the bytes.
Every segment lies inside `$0200-$BFFF` of a bank 1-126.
`DOOM.SYSTEM` (`pl_boot.s`) reads each file named in `CATALOG` through
the MLI, 8 KB at a time, copies each segment into its bank, then checks
every segment's CRC-32 against `CRCLIST` before it leaves ProDOS
([`SCREENS.md`](SCREENS.md) and [`PLAY.md`](PLAY.md) cover the boot). The load image travels the
same way, in `CODE.1`.

### 3.3 Banks

The level's banks (the full map, with the other phases', is
[`MEMORY_MAP.md`](MEMORY_MAP.md); `llayout.bank_map()` is the source):

| Banks | Name | Content |
| --- | --- | --- |
| 6, 7 | `LVSEG`, `LVMAP` | Level window: segs; nodes, subsectors, sectors and sides (render records), the vertex cache, patchless bitmaps |
| 9-31, 56-63 | `TEX` | Texel store |
| 32-47, 64 | `SPR` | Patch store |
| 48, 49 | `SPRT`, `WPRO` | `PHDR`, the map's `SPRFR`, `SPRBOUND`; weapon profiles |
| 50 | `RTH` | Render things, 2,026 slots of 24 B (the mobjs' render part) |
| 65 | `LVG0` | Lines, 32 B each |
| 66 | `LVG1` | Sectors' game records (32 B), line tables, flood index and entries, blocklinks |
| 67 | `LVG2` | Blockmap, reject |
| 68 | `LVC` | Colormaps A and B, the `GSVIEWn` record, `FUZZDARK` |
| 69-71 | `MOBJA-C` | The mobjs' game parts ([`GAME.md`](GAME.md) 3.1) |
| 75, 76 | `ZONE0`, `ZONE1` | Specials; sector nodes |
| 77-90 | `STORE` | The level parts, their directory at bank 77 `$0200`, the variant lists |
| 98 | `LCODE` | The load image |
| 99 | `GTAB` | The game's constant tables |
| 111 | `LVS` | Each line's front and back sector (`LNSECF`, `LNSECB`), each sector's reject row (`RJROW`): made by the `GTABS` step |

## 4. The load

### 4.1 The load program

Each map's program (`lstore.program`) is a list of steps, three bytes
each (a step number and an argument), and a set of memory-API requests:

| Step | Does |
| --- | --- |
| `VARIANTS m` | The undo requests of the map `LV_VARMAP` names, then map m's apply requests, then `LV_VARMAP` = m |
| `COPYREQ n` | Request n: COPY and FILL descriptors from the store into the level window: segs into `LVSEG`; nodes, subsectors (their sector byte `$FF`, computed later), sectors, sides and the patchless bitmaps into `LVMAP`, with FILLs for the vertex cache's three planes; blockmap and reject into `LVG2`; the blocklinks FILLed with `$FF`; `SPRFR` into `SPRT`; `FLATCM`, `TXBANK`, `TXLO`, `TXHI`, `TXWM`, `TXHT` and `TXMP` into the render images' banks; `GSVIEWn` and `FUZZDARK` into `LVC` |
| `LINES`, `GROUP`, `FLOOD`, `CMAPS` | The static steps (4.2) |
| `PRIVREQ n` | PRIVATE requests into main and aux 0: the level's counts (main `$03A0`, `$03A6`), the colormaps from `LVC` into main `$2000-$5FFF` and `$0400-$07FF`, `FUZZDARK` into aux 0 `$0800` |
| `GTABS`, `SPAWN`, `SPECIALS` | The game's steps (4.3), run only under `nl_setup` |
| `END` | |

A program is `VARIANTS`, two or three `COPYREQ`, the four static steps,
one `PRIVREQ`, the three game steps: 12 or 13 steps. A request carries at
most 16 descriptors and 45 KB of data; each endpoint lies inside
`$0200-$BFFF`. A map's requests move 66 KB (E1M1) to 131 KB (E1M6), plus
its variants (8 to 53 columns and tails, each undone and applied).

`lload.s` runs it. `nl_load(m)` finds map m through the store's
directory (bank 77 `$0200`, `llayout.STORE_DIR`), reads its header and
steps into W, and dispatches each step. A request's descriptors are
fetched from the store into W at `$A000` behind the 20-byte SmartPort
and memory-API head and sent through slot 7's FIFO with interrupts
masked. Without the memory API, `DOOM.SYSTEM` patches that transport
with a CPU copy (`tools/native/amcpu.py`). Every read of the store and
every write to a RamWorks bank goes through the far layer's `far_get`
and `far_put`.

A malformed store or program, a request the API refuses, or a limit of
the load's scratch stores a code in `LV_STATUS` (main `$03AE`;
`llayout.LS` names them) and executes `BRK`, as the renderer's stops do.

### 4.2 The static steps (`lgeom.s`)

Each is static level data made exactly as upstream makes it:

| Step | Upstream | What, and the rules that matter |
| --- | --- | --- |
| `LINES` | `loadLineDefs` (`p_setup65.s:259-404`) | Each compact line into its `LVG0` record: v1, v2, dx, dy, the sides, the box (upstream's `v1.y - v2.y` with the overflow flip, `:311-353`), tag and special sign-extended, flags, slope type (dx 0 vertical, dy 0 horizontal, else the sign of dy ^ dx), stamps 0 |
| `GROUP` | `groupLines`, `soundOrigins`, `halfSum`, `addToBox` (`:742-1102`) | Each subsector's sector (the sector of its first seg with a side) into `LVMAP`; the line tables in `LVG1` (each line in its front sector's table, then its back sector's when that exists and differs; tables in sector order); each sector's game record: line count, first entry, special, old special, tag, handles `$FFFF`, and the sound origin (`M_AddToBox` over its lines' vertices in table order with upstream's else-if; `halfSum` an arithmetic shift of each 32-bit side, then the sum) |
| `FLOOD` | `P_InitFlood` (`p_pspr65.s:1253-1380`) | The lines from last to first; for each two-sided line with two different sectors, the back into the front's list, then the front into the back's. Entries without `ML_SOUNDBLOCK` fill up from a sector's first entry, those with it down from its end, so the first read in reverse line order and the second in forward order |
| `CMAPS` | `I_SetLevelPalette` (`i_viigs65.s:1063-1077`) | Colormaps A and B in `LVC`: `A[i] = GSVIEW_A[COLORMAP[i]]`, the same with B |
| `GTABS` | `P_InitSightTables` (`p_sight65.s:1555-1605`), in part | `LVS`: each line's front and back sector (the front twice for a one-sided line, upstream's `LNSEC`) and each sector's reject row offset (sector × numsectors, upstream's `SS_ROW`) |

The converter does the rest of upstream's load-time computation:
`FLATCM` (from `GSFLATn` and `COLORMAP`), `FUZZDARK` (a nearest-colour
search), the vertex numbers (`I_InitSegVertices` numbers points in order
of first appearance; the converter numbers them the same way). The
composed columns are the resident texel store.

### 4.3 The native `P_SetupLevel`

`lsetup.s` `nl_setup(map)` keeps upstream's order wherever it is
observable (the `P_Random` calls, the thinker list, the sector and block
lists, `validcount`, the pool's slots); copies and static computations
move freely:

1. The object API's caches emptied (`go_reset`), `LR_OK` 0, the totals 0,
   `wminfo.partime` 180, the player's kill, item and secret counts 0,
   `viewz` 1 (`p_setup65.s:104-120`).
2. `gt_init`: the thinker list empty, the sector-node pools freed, every
   special kind's free list empty, no zone mobjs, the planes' high-water
   0 (`Z_FreeTags`, `P_InitThinkers`); `leveltime` 0.
3. The map's load program with the game's steps on: `VARIANTS`, the
   copies, `LINES`, `GROUP`, `FLOOD`, `CMAPS`, the PRIVATE copies, then
   `GTABS`, `SPAWN` and `SPECIALS`.
4. `go_flush`: every dirty cache line back to RamWorks.

`SPAWN` (`gspawn.s` `gs_spawn`) sets the level's game globals from the
map's header (pool size, blockmap origin and size, the `BLOCKMAP` and
`REJECT` lump numbers, the places of the line tables, flood lists,
blocklinks and reject that the tic phase needs), clears `LNMAP`, makes
the mobj pool, then spawns each map thing in the lump's order:

| Upstream | Native | Notes |
| --- | --- | --- |
| `P_SpawnMapThing` (`p_spawn65.s:913-1037`) | `gs_mapthing` | Type `$FE` spawns the player. Else the skill's flag (easy for skills 0-1, normal for 2, hard for 3-4); `P_SpawnMobj` on the floor; `tics = 1 + P_Random() % tics` when tics > 0; kills and items counted; angle `ANG45 × angle`; `MF_AMBUSH` |
| `spawnPlayer`, `G_PlayerReborn` (`p_spawn65.s:1058-1118`, `g_game65.s:674-707`) | `gs_player`, `gs_reborn` | Reborn when the player's state says so; then the player's mobj and `P_SetupPsprites` |
| `P_SpawnMobj`, `newMobj` (`p_spawn65.s:72-262`) | `gs_mobj` | The pool's free slot with the highest index, else a zone slot; `mobjinfo`'s fields; one `P_Random` call; the spawn state without its action; `P_SetThingPosition`; floor, ceiling, drop-off; z (`ONFLOORZ`, `ONCEILINGZ`, or given); a full thinker below `MT_MISC0`, a brainless one for tics other than -1, else no thinker (`addIfFunc`); `totallive` |
| `P_SetThingPosition` (`p_map65.s:748-755`) | `gpos.s` `gp_setpos` | The subsector; unless `MF_NOSECTOR` the head of its sector's thing list, then `P_CreateSecNodeList`; unless `MF_NOBLOCKMAP` the head of its block's list (none off the map) |
| `R_PointInSubsector` (`r_iigs65.s:668-700`) | `gp_pointsub` | The descent from the root through `LVMAP`'s nodes with upstream's side test (whole parts when dx or dy is 0; the signs; else the low 32 bits of `(y' >> 8) dx` against `(x' >> 8) dy`). No `SGRIDn` grid and no last-point cache: neither changes a result |
| `P_CreateSecNodeList` (`p_map65.s:1684-1880`, `:2560-2583`) | `gp_secnodes` | `validcount + 1`; the block walk below; then the thing's own sector |
| `P_SetupPsprites`, `setPsprite`, `A_Raise` (`p_pspr65.s:1181-1193`) | `gweap.s` | In the load image the only action an up state reaches is `A_Raise`; any other is the stop `LS_ACTION` |

**The block walk** (`lineBlocks` with `PIT_GetSectors`), each rule
visible in the sector nodes' order or in the line stamps:

- the blocks of the box, x outer and y inner;
- each block's list read after its first entry (with the shared-suffix
  blockmap that entry may be another list's last line);
- a line already stamped with `validcount` is skipped; every line tested
  is stamped;
- the box test in whole map units: right and top edges as
  `(edge >> 16) - (low word == 0)`, left and bottom as `edge >> 16`; a
  horizontal or vertical line that passes crosses the box, a slanted one
  takes `P_BoxOnLineSide`.

`SPECIALS` (`gspec.s` `gx_specials`, `p_spec65.s:433-574`): for each
sector in order, special 1 a light flash, 2 and 3 strobes, 8 a glow, 9 a
secret (`totalsecret`), 12 and 13 synchronised strobes; each light
spawner sets the sector's special to 0 (a secret keeps it); then a
`T_Scroll` thinker for each line of special 48, in line order. Each is a
special appended to the thinker list.

**`P_Random` order**: one call in `P_SpawnMobj` for each spawned thing,
then one for its tics when its spawn state's tics are above 0; the
player's mobj one call; then, in `P_SpawnSpecials`, one for each light
flash and each unsynchronised strobe, in sector order. The index is main
`$03EE` ([`MATH.md`](../src/native/MATH.md)).

There is no player start or deathmatch start array: the converter drops
the other starts, and a death reloads the level.

**One path.** Upstream's reload of the same map (`RL_ON`) skips
`W_LoadSet`, copies `groupLines`' results back and keeps the textures it
made in play. The native load always runs whole: play changed the
sectors and sides in `LVMAP`, so the level part must be copied again
anyway.

### 4.4 The zone

Upstream's zone (linked blocks, a rover, purgeable cache blocks) becomes
fixed pools by kind. Nothing is cached (everything is resident), and the
level's tables have fixed places.

| Pool | Policy | Capacity |
| --- | --- | ---: |
| The mobj pool | Upstream's: the free slot with the highest index, a bitmap (`G_TPBITS`) as `TP_BITS`. Its size is the map's `THINGS` count, at most 512 | `poolsize` |
| Zone mobjs | The zone's free list, else the next slot after the pool's and the zone's used ones | 2,026 - `poolsize` in RamWorks; the tic phase's planes stop at slot 767 ([`GAME.md`](GAME.md) 3.2) |
| Specials | One range of slots per kind, each with a free list | 1,280 (plat, door, floor 256 each; light flash, strobe, glow, scroll 128 each) |
| Sector nodes | Upstream's pools of 32 nodes and its free list, so the free list's length is upstream's | 2,048 |
| Line tables, blocklinks, flood lists | Fixed by the map's header | |

A mobj is its `RTHING` slot plus three game groups at the same address
in `MOBJA-C`: one bank holds `$0200-$BFFF` / 24 = 2,026 slots. A special's
handle is `$0800` + its slot. A full pool is a stop (`LS_ZONE`,
`LS_SPECIALS`, `LS_NODES`), never a silent failure. The capacities hold
every E1 map: at most one floor mover, one ceiling mover and one light
per sector, one scroller per special-48 line.

## 5. The load image

`level.mk` assembles with `-D LOADIMG` and links `lcard` with
`level.cfg`:

| Source | Content |
| --- | --- |
| `lload.s` | `nl_load`, `nl_game`: the program's runner, `VARIANTS`, the requests and the memory-API transport, the stops |
| `lgeom.s` | `LINES`, `GROUP`, `FLOOD`, `CMAPS`, `GTABS` |
| `lsetup.s` | `nl_setup` |
| `gthink.s`, `gpos.s`, `gspawn.s`, `gweap.s`, `gspec.s`, `gvalid.s`, `gobj.s` | The game core and the object API, from the same sources as the tic image ([`GAME.md`](GAME.md) 1); with `LOADIMG` the object API reaches the walk's planes far in `MOBJP` and leaves out the tic image's uncached calls |
| `far.s`, `math.s` (`-D RENDER`), `auxlc.s` | The far layer and phase loader, the math's render subset, `MATHW` and `AUXW` |
| `lboot.s` | `LEVELS.SYSTEM`, a standalone boot and runner for the card's `$E000` part and `$2000`; `DOOM.hdv` takes only `lcard.lw` |

W in the load phase:

| Range | Content |
| --- | --- |
| `$6000-$65FF` | `MATHW`, `AUXW`, the render images' bytes |
| `$6600-$9FFF` | The load code (`LOADW`: about 10.7 KB used) |
| `$A000-$BED5` | The current request, the static steps' scratch (each line's front and back sector, each sector's counts and positions), `mobjinfo` and the mobj and map thing being made, the header, directory and steps. The object API's caches at `$AE00-$B3FF` share this range once `GTABS` has run |

Main zero page: `$18-$37` the game core (`GC_*`, the same bytes in the
tic phase), `$38-$41` the program's pointers (the object API's `$38-$3F`
in the tic phase: `lload.s` keeps them on the stack around each game
step), `$48-$74` the static steps, `$75-$AF` the spawn (`GS_*`),
`$B0-$D7` the math. The deepest stack is `gs_mapthing` → `gs_mobj` →
`gp_setpos` → `gp_secnodes` → the block walk → `P_BoxOnLineSide` → a
product: a few dozen bytes. The node descent never backtracks, so it
keeps no stack.

## 6. `validcount`

The game core's `gv_inc` (`gvalid.s`) raises `validcount`, which is the
frame block's `VALIDCOUNT`: one count shared with the renderer
([`GAME.md`](GAME.md) 6). Upstream lets it wrap from `$FFFF` to 0, so a
stamp written 65,536 increments earlier can match again. Every
increment fixes that: when the count wraps, every sector's stamp in
`LVMAP` and each line's `validcount` and `r_validcount` in `LVG0` are
cleared, and the count becomes 1. In the load and tic images
`go_stamps0` does it, after it flushes and empties the object API's
line and sector caches. The renderer's increment (`nr_setup` in
`rframe.s`, linked from `gvalid.s` with `-D GV_RENDER`) has its own
clear, `gv_clear`: the same zeros, written in one `RAMWRT` window a bank
from W with the far layer's zero page (`FA_*`), and no flush, because
the game's caches are written back and emptied at the end of every tic
phase (`go_flush`) and `nr_setup` runs before the walk fetches any
sector (the renderer stamps only sectors: `rbsp.s`'s `R_AddSprites`
test). On a2vm a wrap forced at a frame of the demo clears every stamp,
and that frame and the rest of the demo are drawn as without it.

## 7. Sound flood depths

The tic phase's `P_RecursiveSound` is iterative with a work stack of
512 entries ([`GAME.md`](GAME.md) 4, part `pspr`). A sector is entered at
most twice (once with a sound block, once without), so a flood is at
most twice the sector count deep: 500 on E1M6, the largest map. With
every two-sided line open and upstream's list order, the worst depths
are:

| Map | Sectors | Worst depth | Bound |
| --- | ---: | ---: | ---: |
| E1M1 | 85 | 52 | 170 |
| E1M2 | 200 | 93 | 400 |
| E1M3 | 177 | 93 | 354 |
| E1M4 | 139 | 23 | 278 |
| E1M5 | 143 | 85 | 286 |
| E1M6 | 250 | 87 | 500 |
| E1M7 | 170 | 61 | 340 |
| E1M8 | 74 | 52 | 148 |
| E1M9 | 147 | 72 | 294 |

A closed door can make a flood deeper than the all-open walk, which is
why the stack holds the bound. A deeper flood is a stop (`GS_FLOOD`).

## 8. Differences from upstream

| Upstream | Native |
| --- | --- |
| `W_LoadSet` loads a set of compressed units into a 22-plus-bank window; `R_MakeLevelColumns` and `W_LevelDone` compose wall columns at each load; textures past `MORE_BANKS` are made in play | Texels and patches resident from boot; the load copies 66-131 KB and patches the map's variants |
| The level palette's colormaps computed at load from `GSVIEWn`; `FLATCM` and `FUZZ_DARKEN` too | Colormaps computed at load (`CMAPS`); `FLATCM` and `FUZZDARK` stored per map |
| `RL_ON`: a reload of the same map skips work | One path: every load runs whole |
| `SGRIDn` start nodes and `R_PointInSubsector`'s last-point cache | A plain descent from the root; same results |
| Bank `$21`'s sight and move tables (`SIGHTLOG`, `LINELOG`, `SS_SEGT`, `SS_ROW`, `SS_SEC`, `LNSEC`, `SEC58`); `BMROW`, `LN36` | `LVS`'s `LNSECF`, `LNSECB`, `RJROW`; the subsector records hold the sector; the address tables are index arithmetic |
| A zone of linked blocks | Fixed pools (4.4) |
| `validcount` wraps | Every stamp cleared at the wrap, in the game's increments and the renderer's (6) |

## Appendix: upstream routines and their native place

| Upstream | Native |
| --- | --- |
| `W_LoadSet`, the level store (`w_level65.s`; `levelimg.py` documents the format) | `umodel.py` on the host; the boot; the load program's copies |
| `I_SetLevelPalette`, `levelFlats`, the fuzz table (`i_viigs65.s:955-1100`) | `CMAPS`; `wadconv.py` |
| `P_SetupLevel` (`p_setup65.s:100-160`) | `nl_setup` |
| `loadThings`, `poolInit` (`p_setup65.s:217-231`; `p_spawn65.s:1369-1375`) | `gs_spawn`, `gthink.s` `gt_poolinit` |
| `loadLineDefs` (`p_setup65.s:259-404`) | `LINES` |
| `loadSegs`, `I_InitSegVertices` | `wadconv.py` |
| `loadBlockMap`, `P_InitBlockRows` | The copies; `gs_spawn`'s globals |
| `loadNodes`, `loadSectors`, `loadSideDefs`, `loadSubsectors`, reject | `wadconv.py`, the copies |
| `loadGrid`, `newPoint` | None |
| `R_MakeLevelColumns`, `R_MakeTextureColumns` (`r_data65.s:863-1197`, `:1732-1860`); `W_LevelDone`, `moreColumns`, `W_ZeroBank` (`w_level65.s:507-610`, `:1456-1480`) | `umodel.py` |
| `groupLines`, `soundOrigins`, `halfSum`, `addToBox` (`p_setup65.s:742-1102`) | `GROUP` |
| `rlSave`, `rlGroup` and the other `rl*` routines (`p_setup65.s:1145-1462`) | None (one path) |
| `P_InitSightLogs`, `P_InitSightTables` (`p_sight65.s:1446-1712`) | `GTABS` (the two tables the game reads) |
| `P_InitFlood` (`p_pspr65.s:1253-1380`) | `FLOOD` |
| `P_SpawnMapThing`, `spawnPlayer` (`p_spawn65.s:913-1118`) | `gs_mapthing`, `gs_player` |
| `G_PlayerReborn` (`g_game65.s:674-707`) | `gs_reborn` |
| `P_SpawnMobj`, `newMobj`, `clearMo` (`p_spawn65.s:72-331`) | `gs_mobj` |
| `poolTake`, `poolFree` (`p_spawn65.s:1249-1366`) | `gthink.s` `gt_pooltake`; part `mobjstate` |
| `P_SetThingPosition`, `P_CreateSecNodeList` (`p_map65.s`) | `gp_setpos`, `gp_secnodes` |
| `R_PointInSubsector` (`r_iigs65.s:668`) | `gp_pointsub` |
| `P_InitThinkers`, `P_AddThinker` (`p_think65.s:29-44`) | `gthink.s` `gt_init`, `gt_add` |
| `P_SetupPsprites`, `bringUpWeapon`, `setPsprite`, `A_Raise` | `gweap.s` |
| `P_SpawnSpecials` and the light spawners (`p_spec65.s:433-574`; `p_lights65.s:274-326`) | `gspec.s` |
| `P_MapEnd` (`p_map65.s:3293-3298`) | Nothing at load: `tmthing` is written before anything reads it |
| `Z_Init`, `Z_Malloc*`, `Z_FreeTags` (`z_zone65.s`) | The pools (4.4) |
