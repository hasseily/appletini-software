# Milestone 9: level loading

Status: design, 2026-10-01, revised the same day after a review (the
"Review" section), for the three builders of milestone 9 (stages A, B
and C, section 6). **Stage A is built** (2026-10-01, on the host; the
section "Stage A as built" at the end, whose corrections are applied in
the text and marked "(stage A)"); **stage B is built** (2026-10-01, on
a2vm; "Stage B as built", corrections marked "(stage B)"); **stage C is
built** (2026-10-01, on a2vm; "Stage C as built", corrections marked
"(stage C)"), and **verified** ("Verification of stage C"). It follows
[`RENDER.md`](RENDER.md) and [`RENDER-MASKED.md`](RENDER-MASKED.md)
(milestones 7 and 8, built and verified), whose level layout
`render-level 2` is the contract this milestone meets, and
[`NATIVE.md`](NATIVE.md) sections 4.4, 7, 10, 11, 13 and 15.1.

The milestone is `NATIVE.md` section 13, row 9, as the task that ordered
this design states it:

> Level loading natively: our own host converter from DOOM1.WAD to the
> native store, the store's format and its place in RamWorks, the 65C02
> loader that brings a map from the store into the level window, the
> native P_SetupLevel and the zone. Acceptance: (1) the canonical level
> after P_SetupLevel (the bridge's canonical model: geometry, blockmap,
> reject, sectors, lines, sides, subsectors, segs, nodes, the things
> spawned with their mobjs and thinkers, the specials P_SpawnSpecials
> makes, the zone's objects, every global P_SetupLevel sets) equals
> ref816's for all 9 maps of episode 1 at each skill the coverage
> reaches (state the set); (2) milestone 8's frame check (frame8.py, the
> m7 sets and demo3) passes on natively loaded levels, that is on level
> data made by the native loader from the store instead of levelconv.py's
> from a ref816 state (prove first that the converter's output equals
> levelconv.py's on every map, byte for byte where the layout is the
> same); (3) the host's worst sound-flood depth (P_RecursiveSound) of
> each map fits the native work stack. Report: load time per map on a2vm
> (f121 and fastpath), boot time with the store, and the RamWorks banks
> used against NATIVE.md 4.4.

Binding decisions (`NATIVE.md` 15.1): any load time is acceptable, so the
level store is loaded whole at boot while ProDOS is still present and no
disk read happens in play (row 9); 8 MB of RamWorks are required, 126
banks, bank 127 excluded (row 8); renderer arithmetic stays exact (row
3); the release is gated on lockstep-schedule mode and the port fixes the
`validcount` wrap behind a build option that restores upstream's
behaviour for the lockstep tests (row 4); our own divides (row 5); a
column seen from behind is a known difference (row 13).

**Labels**, as in `NATIVE.md`:

- **[M: source]** measured. `W1`, `T1`, `S1`, `Z1`, `F1`, `R1` are the
  read-only surveys made for this design, `V1` and `F1` (redone) those of
  its revision (appendix B); `M7`, `M8` are
  `RENDER.md` and `RENDER-MASKED.md` "as built"; `levels` is
  `build/native/render/levels/*/level.json` as `levelconv.py` wrote it.
- **[R file:line]** read there. Upstream files are in
  `build/upstream/src/iigs/`, upstream's host tools in
  `build/upstream/tools/` (GPL; read to learn the formats upstream
  builds, never run or copied: `NATIVE.md` 7).
- **[A]** assumed, or arithmetic on labelled numbers.

## 0. Summary

| Question | Answer |
| --- | --- |
| Where it starts and stops | From `P_SetupLevel` entry to the end of the load: for a new map that is the end of `W_LevelDone` (`bmLoad` runs `jsl P_SetupLevel` then `jmp W_LevelDone` [R `m_menu65.s:1780-1789`], which makes the switch partners' and slime frames' columns and zeroes the next window bank [R `w_level65.s:507-610`]); for a new life on the same map, `P_SetupLevel`'s last instruction (`jmp long:P_MapEnd` [R `p_setup65.s:100-160`]). In between: the level set into memory, the palette's colormaps, the level data, the things spawned, the specials, every global it sets. The game state is final at `P_MapEnd`; `W_LevelDone` changes only the column memory and the automap cache. Section 0.1. |
| The tails (the bytes a record reads past a post, past a lump, past a composed column) | **They reach pixels** and depend on upstream's window layout: on the 734 captured frames, 3,014 sprite and masked records read past their lump's end (up to 125 bytes), 3,074 wall records read past their composed column's height (up to 112 rows), 444 cross a bank end [M: T1]. **They are reproduced exactly** by rebuilding each map's upstream level window from the release's level store (its set entries, our own `tools/v816/hdv.py` and `b1.py`): **0 differing bytes** against ref816's RAM in every image bank of the nine maps up to the composed columns [M: W1], and the composed columns by our own model of `R_MakeLevelColumns` and `W_LevelDone`'s `moreColumns`, as they stand at the end of the load. Textures upstream makes only in play (E1M2 5, E1M3 5 [M: stage A; V1 counted E1M2's switch partners only]) can change hole bytes later; the slots that reach those bytes are listed per map as known differences (1.2): none reach any (stage A). Section 1.2. |
| Converter inputs | `DOOM1.WAD` for every lump the WAD holds (patches, sprites, textures, map lumps through our own transforms, `COLORMAP`), checked equal to the release's game lumps; the release image for what upstream's build tools invented and the WAD cannot give: each map's unit placement (the tails), the per-map colour tables `GSVIEWn` and `GSFLATn` and the flat numbering; `rtables.py` for the constant tables, as today. Section 1.1. |
| What the store holds | A **resident texel store** (one canonical slot block per texture, 115 textures, 1,286,144 B [M: S1], 30 banks) and a **resident patch store** (410 lumps with their tails, 813,968 B [M: S1], 17 banks), shared by all maps: the maps' 4.65 MB of slots and 5.24 MB of patch store collapse to these because only 219 columns and 125 tails differ between maps [M: S1]; per map a small **level part** (geometry in `render-level 2` form, the game's map data, the per-map variant columns and tails, the whole `GSVIEWn` record), about 1.0 MB for the nine maps [A], 21 banks. No compression: the allocation leaves 8 banks spare (section 1.6); an optional codec byte is reserved per block. **Stage A measured**: 116 texel blocks (the in-play textures and the sky included), 1,302,528 B, 31 banks; 410 lumps, 813,968 B, 17 banks; level parts 858 KB in 14 banks after 203 KB of the texel banks' slack; 223 variant columns and 131 tails; 14 banks spare, no codec. |
| Where | A game bank map that keeps every bank milestones 7 and 8 fixed (`LVSEG` 6, `LVMAP` 7, `RENDB` 8, `SPRT` 48 ... `FSTEP` 116-119) and places the stores around them, with a bank for the game's constant tables (`GTAB`) and one for milestone 10's sight and move tables (`LVS`): 118 of 126 banks used with the later milestones' budgets [A] (**112 of 126** as stage A measured the store: 31 texel banks, 14 level-part banks; **109 of 126**, 17 spare, as stage C built the mobjs' game part in 3 banks, not 6), against `NATIVE.md` 4.4's 76-82 (which did not know the render work banks, the 30-bank texel store or the mobj bound). Section 1.6. |
| Boot | `LEVELS.SYSTEM` (the test disk) and later `DOOM.SYSTEM` read the store files with ProDOS into a main staging buffer and copy them to their banks, the format and method of `demos/doom/src/kernel/loader.s` step 3 [R `loader.s:17-24`, `:36-45`]: about 3.5 MB in five files [A], under 2 s on a2vm [A]. Section 1.7. |
| The loader and the level window | A per-map **load program** made by the converter: memory-API COPY and FILL requests (endpoints `$0200-$BFFF`, PRIVATE for main and aux 0 destinations, at most 45 KB a request), the variant step (undo the variants of the map that `LV_VARMAP` names, apply this map's), then 65C02 steps: the lines' derived fields (deltas, box, slope type), `P_GroupLines` (subsector sectors, line tables, counts, sound origins with upstream's `M_AddToBox` and `halfSum`), the flood lists, the colormaps from `GSVIEWn`. The window is six banks (`LVSEG`, `LVMAP`, `LVG0` lines, `LVG1` sectors' game part, line tables, blocklinks and flood lists, `LVG2` blockmap and reject, `LVC` colormaps and the per-map tables) besides the resident stores. Section 2. |
| Native `P_SetupLevel` | Upstream's order kept step for step (section 2.1): totals and player fields, thinkers emptied, pools reset, the pool of `THINGS`-count mobjs, the load program, the things spawned in map order (`P_SpawnMapThing`, `P_SpawnMobj` with its `P_Random` call, `P_SetThingPosition` with `R_PointInSubsector` and `P_CreateSecNodeList`, `P_AddThinker`, `P_SetupPsprites` with `A_Raise`), `P_SpawnSpecials`. These game routines are built here as a shared "game core" milestone 10 reuses. The sight and move tables of bank `$21` move to milestone 10 (their layout is their consumer's). Section 2.6. |
| The zone | Fixed pools by kind with upstream's slot policy where identity depends on it (the mobj pool: highest free slot), free lists elsewhere (the bridge renumbers by rank and reach). **`RTHING` goes from 768 slots to 2,026, one bank**: the pool's `poolsize` slots (at most 512), then the zone mobjs, so a map has room for 2,026 - `poolsize` zone mobjs (1,910 on E1M1); stage C proves each map's upstream bound against that room at its setup dumps (Z1's in-play figures, 674-1,479, are only indicative); specials 1,024 (a bound by construction); sector nodes 2,048 [A, a stop if exceeded]. Section 3. |
| Harness | ref816 dumps at `P_SetupLevel` entry, at its last instruction, and for a new map at the end of `W_LevelDone`, for 51 setups (53 as built: the reloads' first loads kept): the tour at each of the five skills (generated scripts; nightmare answered "y"; 45 setups, E1M1 by a new game, the others by the exit `idclev` makes), the three demos' starts, two reloads of the same map (upstream's `RL_ON` path); the bridge's canonical comparison with 12 named exclusions; the converter against `levelconv.py` on the end-of-load dumps, in both layouts (the game layout read back from the loaded window); the loader on a2vm from an image and from a boot disk; `frame8.py` on loaded levels; the flood depths. About 1.5-2 hours at 2 jobs, under 0.8 GB of `build/` [A]. Section 5. |
| Stages | A: the converter, the upstream memory model (with `moreColumns`), the setup captures; checkpoint: equal to `levelconv.py` on every map's end-of-load dump, and the list of textures made in play with the slots they can reach. B: the store's boot load and the loader with the static derivations and the variant step; checkpoint: the window equals the converter's for all 9 maps, read back into harness form it equals `levelconv.py`'s slot for slot, and `frame8.py` passes on it (acceptance 2). C: the game core, `P_SetupLevel`, the zone; acceptance 1 and 3, the report, the boot disk for milestone 12. Section 6. |
| Main risks | The bank budget (8 spare [A], the codec's threshold); the composed-column model (`R_MakeLevelColumns`' holes, `moreColumns`' bank limit); textures upstream makes in play (E1M2, E1M3); the mobj layout chosen before milestone 10 designs the game logic. Section 7. |

### 0.1 Scope

Upstream's `P_SetupLevel` and what it calls [R `p_setup65.s:100-160`],
then, for a new map, `W_LevelDone` [R `m_menu65.s:1780-1789`]:

| Upstream | Where | Native in |
| --- | --- | --- |
| `W_LoadSet` (the set's units into the window) | `w_level65.s:1-21` | The resident stores (boot) and the load program's copies (B) |
| `I_SetLevelPalette`: colormaps A and B, `FLATCM` (`levelFlats`), `FUZZ_DARKEN`, `TINTPAL`, `GRAYMAP` | `i_viigs65.s:1015-1080`, `:955-957`, `:874-880`; `:83-85` | Colormaps: 65C02 at load (B). `FLATCM`, `FUZZDARK`: the converter (A). The whole `GSVIEWn` record (14 tints, the pairs, A and B) is stored per map now and copied to `LVC` at load (B), so the store loaded at boot is complete; `TINTPAL`, `GRAYMAP`, the view's tints and gamma made from it: milestone 11 |
| Totals, `wminfo.partime`, player counts, `viewz`, `S_Start`, `Z_FreeTags`, `P_InitThinkers`, `leveltime` | `p_setup65.s:104-127` | C (`S_Start`'s music: a hook, milestone 11) |
| `loadThings` (the pool: one mobj a map thing, `poolInit`) | `:217-231`; `p_spawn65.s:1369-1375` | C |
| `loadLineDefs` (deltas, box, slope type, stamps 0) | `:259-404` | B (65C02) |
| `loadSegs` with `I_InitSegVertices` (the vertex hash) | `:414-428`; `i_viigs65.s:1900-1905` | A (the converter's vertex numbers, `RENDER.md` 1.3) |
| `loadBlockMap`, `P_InitBlockRows` | `:432-462`; `p_map65.s:3301-3344` | B (blockmap copied; `BMROW`, `LN36` are address tables, dropped) |
| `loadNodes`, `loadGrid` (`SGRIDn`), `newPoint` | `:465-530` | Nodes: B (copied). `SGRIDn`: not used (section 2.4) |
| `rlSightLogs`, `rlSightTables` (`P_InitSightLogs`, `P_InitSightTables`) | `:141-142`, `:155`, `:1197-1219`; `p_sight65.s:1446-1453`, `:1555-1562` | **Milestone 10** (section 2.6), except `LOGP` and `P_InitFlood` |
| `loadSectors`, `loadSideDefs` with `P_LoadTexture`, `R_MakeLevelColumns` | `:536-691`, `:146`; `p_switch65.s:164`; `r_data65.s:863-938` | Copied (B); the columns: the resident texel store (A, boot) |
| `P_LoadReject`, `loadSubsectors` | `:147-151`, `:695-735` | B (copied) |
| `groupLines`, `soundOrigins`, `halfSum`, `addToBox` | `:742-1102` | B (65C02) |
| `rlSave`, `rlGroup` (the copy for a new life on the same map) | `:1145-1462` | None: the native load always runs whole (section 2.1) |
| `P_InitFlood` | `p_pspr65.s:1253-1268` | B (65C02) |
| `loadThings2` (`P_SpawnMapThing` per map thing) | `:235-255`; `p_spawn65.s:913-1118` | C |
| `P_SpawnSpecials` | `p_spec65.s:433-574`; `p_lights65.s:274-326` | C |
| `P_MapEnd` | `p_map65.s:3293-3298` | C |
| `W_LevelDone` (new map only): `moreColumns` with `madeT` and `makeT` (each made switch texture's partner, the three slime frames when one is made, each only while the column memory is in the first `MORE_BANKS` 22 window banks), then `W_ZeroBank` of the window bank after the column memory (`LV_ZB`) | `w_level65.s:507-610`, `:1456-1480` | `umodel.py` (A); the bytes they leave are in the resident texel store |

Out, with who has it: the busy sign and `W_LevelDone`'s automap cache
(`AM_LevelCache`; `m_menu65.s:1778-1791`, `w_level65.s:507`; milestone 11); `G_DoLoadLevel`
around the call, keys, status bar, HUD (`g_game65.s:643-664`; milestones
10 and 11); the 4 MB disk path of `W_LoadSet` (no disk in play, 15.1 row
9); `SPRBOUND` (made at the first rendered frame, `RENDER-MASKED.md` 0.3
row 3: milestone 11); the load-game path (`m_menu65.s:1788`; milestone
11); the title and intermission picture sets (milestone 11).

### 0.2 Ground rules for this milestone

From `MILESTONES.md` "Ground rules" and the task that ordered this
design: the directory is GPL-2 and code rewritten from upstream is
committed here, but no upstream file is copied and nothing is read from
or derived from upstream's `src/iigs/cal_integer.s`; C11 and
standard-library Python only; no build warnings; tests in `tests/` run by
`python3 -m unittest discover -s tests` and skip with a clear message
when `build/` lacks what they need; no test is weakened and no address,
frame, map or file is special-cased. **Resources:** at most 2 parallel
jobs, every run under `nice -n 10`, every run with a time limit and every
output with a size limit (`tools/ref816/bounded.py` or
`tests/support.run`), temporary output deleted after the run, `df -h
/System/Volumes/Data` before any run that writes more than 100 MB, stop
below 20 GB free, and `build/` growth for this milestone under 5 GB,
reported by each stage. No `git add`, commit or push by the builders.
The WAD and anything made from it, the release and anything read from
it, stay in `build/`. `tools/sound`, `src/sound` and `tests/test_sound_*`
are not touched. The owner tests on the card at milestone 12: the boot
disk of stage C waits for that.

### 0.3 What the sources change in the task's plan

Ten facts of upstream's code and tools shape this design. Each is
reproduced, not fixed.

| # | Fact | Consequence |
| --: | --- | --- |
| 1 | **The tails reach pixels.** A record's rows read up to 127 bytes past its texel pointer [R `RENDER.md` 1.4], and the first row of a post often reads texel 127 (its position just under 0, masked to 7 bits). On 734 frames the rows of 3,014 sprite and masked records read past their lump's end, 2 wall records too, 3,074 wall records past their composed column, 444 across a bank end [M: T1]. | Every tail byte is reproduced exactly (1.2). |
| 2 | **Upstream's window is a pure function of the release's store.** A set is units (lumps one after the other), placed by `levelimg.py` with `levelhot.txt` and a seeded search, every other byte of the image banks zero, written once by `W_LoadSet` [R `levelimg.py:17-27`, `:293-333`, `:593-628`]; the game never writes the image (0 differing bytes at the tour's states, minutes into each map [M: W1]). | The converter rebuilds it from the store's entries rather than re-running upstream's layout search (1.1, 1.2). |
| 3 | **The game WAD is not DOOM1.WAD.** `wadtool.py` drops the player starts 2-4, the deathmatch starts and the multiplayer things, puts vertex coordinates into lines and segs, packs identical sides of lines without a special, numbers the flats by a per-map list of `gsview.py`, packs the blockmap by shared suffixes, adds `SGRIDn`, `GSVIEWn`, `GSFLATn` and the status and overlay palettes [R `wadtool.py:214-222`, `:228-235`, `:263-306`, `:320-346`, `:354-387`, `:672-705`]. | Our transforms of the map lumps are checked equal to the release's lumps; the colour tables and flat numbers come from the release (1.1). |
| 4 | **`idclev` ends the level.** In this port it calls `G_ExitLevel`; the tour enters E1M2-E1M9 through the intermission with the player kept (`PST_LIVE`) [R `coverage/tour.script:5-13`]. | The tour covers the "level after a level" path; a new game covers the reborn path (5.1). |
| 5 | **`P_SetThingPosition` builds sector nodes and raises `validcount`.** It calls `P_CreateSecNodeList` [R `p_map65.s:748-755`], whose block walk stamps lines with `validcount`. | Sector nodes, `validcount` and the line stamps are part of what setup leaves: the game core includes them (2.4). |
| 6 | **`P_SetupPsprites` runs a state action.** It brings the weapon up through `P_SetPsprite` [R `p_pspr65.s:1181-1193`], which runs the up state's action (`A_Raise`). | The native setup runs `P_SetPsprite` with the actions an up state reaches (2.4). |
| 7 | **A new life on the same map takes another path.** `RL_ON`: `W_LoadSet` loads nothing, `groupLines` comes from a copy, `R_MakeLevelColumns` keeps its tables, so the textures made in play stay; `bmLoad` skips `W_LevelDone` [R `p_setup65.s:1145-1150`; `r_data65.s:863-869`; `m_menu65.s:1782-1791`]. | The native load has one path; each reload's canonical state is compared with ref816's, and its static level kinds and window with the first load's (5.1). |
| 8 | **The mobj pool is the map's thing count.** `_g_thingPoolSize` = the `THINGS` lump's length / 8, at most `TP_MAX` 512; more mobjs go to the zone [R `p_setup65.s:217-231`; `p_spawn65.s:31-33`, `:275-278`]. The pool counts things of every skill, so it has free slots. | The pool keeps upstream's size and slot policy; zone mobjs get their own bounded pool (3.1). |
| 9 | **Composed columns avoid cache slots.** `R_MakeLevelColumns` places the hot textures' composed columns off `$0900-$1FFF` of their bank and fills the holes with the others' tables and columns, pass 1 then pass 2 [R `r_data65.s:1094-1106`, `:1732-1745`]. | The converter's model of the column memory follows these rules; the bytes after a composed column are whatever that order put there (1.2). |
| 10 | **The load does not end at `P_SetupLevel`.** For a new map `bmLoad` goes on to `W_LevelDone`, whose `moreColumns` makes the partner of each made switch texture and the slime frames through `R_MakeTextureColumns` while the column memory is below window bank `MORE_BANKS` 22: cold ones fill holes first, the rest is appended; then the next window bank is zeroed [R `m_menu65.s:1780-1789`; `w_level65.s:507-610`; `r_data65.s:1750-1775`]. So `COLDIR`, the column tables, hole bytes and the bytes after the last column change after `P_MapEnd`: E1M7's sides use `SW1COMM`, `SW1COMP`, `SW1METAL`, `SW1SLAD` and its level sources hold the four `SW2` partners (`SW2COMM` 72 high, 2 patches); E1M1, E1M4-E1M6, E1M8, E1M9 likewise [M: V1]. A texture past the limit is made at first sight in play [R `r_seg65.s:505-516`]: E1M2 5 (`SW2PIPE`, `SW2SLAD`, `SW2STON1`, and the slime frames `SLADRIP1`, `SLADRIP3`: V1 missed these two), E1M3 5 [M: stage A, `inplay.json`]. | The column memory is modelled and compared at the end of `W_LevelDone`; the game state at `P_MapEnd` (5.1, 5.3); the in-play textures are listed with the slots they can reach (1.2). |

## 1. The store

### 1.1 The converter's inputs

`tools/native/wadconv.py` (stage A). Every input is in `build/`.

| Data | Source | Why that source | Check |
| --- | --- | --- | --- |
| Patch and sprite lumps, bytes | `DOOM1.WAD` | Used verbatim by upstream (`RENDER-MASKED.md` 1.3) | Equal to the release's lumps at their window addresses (W1's rebuild) and to `levelconv.py`'s patch store |
| `TEXTURE1` (repacked), `PNAMES` (upper case) | `DOOM1.WAD` and our transform | Upstream's simple repack [R `wadtool.py:135-167`] | Equal to the release's lumps |
| Map lumps in the game's form: `THINGS` filtered and packed, `LINEDEFS` with coordinates, `SIDEDEFS` packed, `SEGS`, `SSECTORS` (counts), `NODES`, `SECTORS`, `REJECT`, `BLOCKMAP` packed | `DOOM1.WAD` and our transforms, written from the format `wadtool.py` documents | `P_SetupLevel` reads this form [R `p_setup65.s:32-56`] | **Byte for byte** equal to the release's map lumps, every map (stage A) |
| The flat numbering of each map | The release's game `SECTORS` lump, paired with `DOOM1.WAD`'s flat names | `gsview.py`'s per-map list is not in any WAD [R `wadtool.py:336-346`, `:683-686`] | The pairing is one-to-one; the game `SECTORS` check above |
| `GSVIEWn` (the whole record: 14 tints of 16 colours, the pairs, colormap tables A, B), `GSFLATn` (flat colours), the lump directory's order (1,015 lumps) | The release's store and resident WAD | Upstream's k-means palettes and lump removals: build artifacts | The record against the release's lump; colormaps, `FLATCM`, `FUZZDARK` against ref816's RAM after setup |
| The placement of every lump of each map's set (the tails) | The release's store: set records and entries [R `levelimg.py:29-41`] | `levelimg.py`'s layout depends on `levelhot.txt` and a seeded random search [R `levelimg.py:92-106`, `:293-333`] | 0 differing bytes (W1); every slot and tail against `levelconv.py` |
| The composed columns | Our model of `R_MakeLevelColumns` and `W_LevelDone`'s `moreColumns` and `W_ZeroBank` (`tools/native/umodel.py`) | Made by game code at each load | Every slot's upstream address (`texmap.json`) and bytes against `levelconv.py` on the end-of-load dumps (5.3) |
| `COLORMAP` | `DOOM1.WAD` | `fullcolormap` [R `r_data65.s:692-694`] | Against ref816's RAM; stored in `GTAB` (1.6) |
| Constant tables (`FSTEP`, `RECIP_TABLE`, the math's, the scale records, the trig tables, `states`, `mobjinfo`, `CMOP`, `SFIRST`) | `rtables.py`, as milestones 7 and 8 | Already checked against formulas and the reference | Unchanged |
| `switchlist`, `SW_IDX`, `animated_texture_basepic` (boot globals of `P_Init`) | Our code from `TEXTURE1` and Doom's switch and animation names | `P_InitSwitchList`, `P_InitPicAnims` [R `p_setup65.s:165-168`]; `moreColumns` reads them too | Canonical globals (acceptance 1); stored in `GTAB` (1.6) |

Reading the release uses our own readers from milestone 1:
`tools/v816/hdv.py` (the disk image, `level_store()`) and
`tools/v816/b1.py` (an independent B1 decoder, tested against the
reference [R `tools/v816/b1.py:1-24`]). Nothing of upstream's tools runs.
`NATIVE.md` 7 said "DOOM1.WAD to 65C02 layouts"; this design keeps
`DOOM1.WAD` as the source of every byte the WAD holds and takes from the
release only what upstream's build invented (its layout and its palettes).
Re-deriving those would mean re-implementing `levelimg.py`'s search and
`gsview.py`'s k-means bit for bit: more code, and a copy of upstream's
tools in all but name.

### 1.2 The tails: evidence, then the choice

**What reaches a pixel** [M: T1]. Upstream's records at `R_DrawLists`
entry (and every early flush) of all 734 captured frames, each texture
record's rows stepped exactly as the row blocks step (milestone 5's
`p1_image` [R `src/native/replay.s:724-756`], which gives upstream's SHR
bytes on every captured frame [M: M8]), each read address classified
against the level source's lump directory and column memory:

| Measure | Value |
| --- | ---: |
| Texture records, rows | 268,040 records, 13,430,155 rows |
| Records reading past their post inside their own lump (WAD bytes, placement-independent) | 15,314 |
| Sprite and masked records reading past their **lump's end** | 3,014, up to 125 bytes past it |
| Wall records reading past their lump's end | 2 |
| Wall records reading past their **composed column's height** (into the next column memory bytes) | 3,074, up to 112 rows past it |
| Records whose reads **cross a bank end** (into the next window bank's first bytes: banks `$2A`, `$2B`, `$2D`, `$2F`, `$38`, `$39`) | 444 |
| Records reading past the end of column memory | 0 |

The first row of a post is where most of it happens: its position one
row before is just under 0, so the row reads texel 127. Examples: E1M7's
`COLUA0` rows 110-114 reading 94 bytes past the lump into `RKEYA0`;
`TROOA2A8` 81 bytes into `TROOA3A7` (demo-09). So the tail bytes are
pixels, not padding, and the 124-byte reach `levelconv.py --overrun`
measured [M: M8 A] is real.

**Where they come from.** Three sources, each reproduced:

1. **The bytes after a lump in upstream's window**: the next lump of its
   unit, the next unit, zero fill, or the next physical bank. W1 rebuilt
   each map's window from the release's store: the set records and
   entries (unit streams decoded by our `b1.py`, FILL zeros, the common
   set's units first, as `W_LoadSet` does), the window banks in ref816's
   order (`LV_WIN` at `$00:8B58`: `$2A-$3F`, `$0E`, `$0F`, `$5C-$69`
   [M: W1]). Against the RAM of the nine tour level sources: **0
   differing bytes** in every image bank (12 to 18 a map, 9,240,576
   bytes in all) up to `W_COLSTART` [M: W1]. The rebuild is a model of
   the 8 MB machine's memory after `W_LoadSet`, so the bank after a
   window bank is modelled too: the next window bank inside `$2A-$3F`
   and `$5C-$69`, `$0F` after `$0E`, and three edges the model must
   hold: `$40` after `$3F` (the store's first bytes), `$10` after `$0F`
   (the resident WAD's header and directory, the directory as the set
   leaves it), `$6A` after `$69` (the songs' bank). No captured read
   reached those three; the converter models them and fails, naming the
   lump, if a tail would reach a byte the model does not hold.
2. **Composed columns**: the column memory after `W_COLSTART`, filled by
   `R_MakeLevelColumns` (fact 9) and then, for a new map, by
   `W_LevelDone`'s `moreColumns` (fact 10). `tools/native/umodel.py`
   reproduces it as it stands at the end of `W_LevelDone`: the directory
   `COLDIR`, each column table, each composed column (zero-filled, the
   patches' posts drawn in), the allocation with its holes and its two
   passes, across the window banks in `W_NEXTBANK` order (each new bank
   zeroed by `W_ZeroBank`); then `moreColumns` in upstream's order (the
   `switchlist` pairs from the first, the partner of a made texture made
   through `R_MakeTextureColumns`, cold ones into the holes first; then
   the three slime frames when one of them is made), each `makeT`
   skipped once the column memory's window index is 22 (`MORE_BANKS`)
   or more [R `w_level65.s:530-610`]; then the window bank after the
   column memory zeroed (`LV_ZB`). Its check is exact: every slot's
   upstream address (`texmap.json`) and every slot's 128 bytes equal
   `levelconv.py`'s on the end-of-load dumps (5.3).
3. **Single-patch wall columns**: `patch + columnofs[x] + 3` inside the
   lump in the window (source 1).

**Textures made in play.** `moreColumns` makes a switch partner or a
slime frame at load only while the column memory is below window index
`MORE_BANKS`; any other texture is made when a wall first shows it
(`needColumns` [R `r_seg65.s:505-516`]), cold, so it fills holes first
and is appended otherwise [R `r_data65.s:1750-1775`], partway through a
level and in run-time order. **This happens in E1** [M: V1]: E1M3's
column memory is at `$0E:F800` in its level source, window index 22, so
`moreColumns` made none of its five partners (`SW2BRCOM`, `SW2BRNGN`,
`SW2COMP`, `SW2DIRT`, `SW2STONE`; its sides use the `SW1` five, its level
source holds no `SW2`); E1M2 (`$0E:2780`) holds `SW2COMP` but lacks
`SW2PIPE`, `SW2SLAD`, `SW2STON1`, and of the slime's frames, which
`moreColumns` makes after the switches, `SLADRIP1` and `SLADRIP3` (its
sides show `SLADRIP2`; stage A found them, V1 looked at switches only).
All ten are 128 high, so their own
slots (texels with no tail) do not depend on the order. What the order
can change is the bytes of a hole's free part, which are the tails of the
columns ending at that hole. So:

- natively every texture a level can show is resident (the texel store),
  and every other slot holds the bytes it has at the end of the load
  (`W_LevelDone`);
- the converter writes per map `inplay.json`: the textures upstream makes
  only in play (E1M2 5, E1M3 5 as stage A found them), each one's height (a texture
  of height below 128 among them is itself a known difference), and,
  from the model, **every slot whose 128 bytes reach the free part of a
  hole at the end of the load**: the bytes a run-time allocation can
  change. If a map's list is empty the report says so with that proof
  (no slot's 128 bytes reach a free hole byte); otherwise each slot is
  named as a known difference for the owner, and a frame that differs
  only in those slots' bytes is reported under that name (5.4);
- upstream's `RL_ON` reload keeps the textures made in play (fact 7);
  the native reload restores the end-of-load bytes, which differs only
  in the same listed slots.

Risk 3.

**The choice.** The store holds the tails as bytes computed on the host
from the model (the rebuild plus the column memory), not as references to
be resolved on the 65C02. Every tail and slot is then checked once per
map against `levelconv.py`'s, which reads ref816's RAM: an exhaustive
check, since the data is finite.

### 1.3 What the store holds

**Shared and resident** (loaded at boot, never copied again):

| Part | Content | Size | Label |
| --- | --- | ---: | --- |
| Texel store | One slot block per texture (128 B a column, `RENDER.md` 1.4), the most common variant over the nine maps; the sky's 256 columns as a texture | 115 blocks, 1,286,144 B; 30 banks (first fit, 173,056 B slack: a 32 KB block and a 16 KB block do not share a 48,640 B bank) | M: S1 |
| Patch store | Each sprite lump and masked first patch any map stores, its bytes verbatim, then its 128-byte tail, the most common tail over the maps | 410 lumps, 761,488 B, plus 52,480 B of tails; 17 banks | M: S1 |
| `PHDR` | One record a stored lump (index 0 the placeholder), global | 411 × 16 B in `SPRT` | R `rlayout.py:179-181`; A |
| Scale records, `CMOP`, `SFIRST`, `WPRO` (weapon profiles) | As milestone 8 | `SPRT` 20,496 B + `WPRO` 28,072 B, the same in every map | M: S1 (28 distinct banks among the 36 banks 6, 7, 48, 49 of the nine levels: bank 49 the same in all nine) |
| Constant tables | `FSTEP`, `RECIP_TABLE`, the math's, the aux card's trig tables (banks 116-122 and the aux card) | about 300 KB | A on R `RENDER.md` 1.6 |
| Game tables, `GTAB` | `states` (314 × 16 B), `mobjinfo` (50 × 64 B), `COLORMAP` (34 × 256 B), `switchlist`, `SW_IDX`, `animated_texture_basepic` | about 17.5 KB in one bank (1.6) | A on R `offsets.inc:1017`, `r_data65.s:692-694` |

**Per map** (the level part, in the store banks, copied by the load
program):

| Part | Content | Largest map, all nine | Label |
| --- | --- | ---: | --- |
| `LVSEG` image | Segs, 24 B (`RENDER.md` 1.3) | 44,686 B (E1M6); 258 KB | M: S1 (bank 6's extent per level) |
| `LVMAP` image | Nodes 32 B, subsectors 4 B (sector byte `$FF`: the loader computes it), sectors' render part 16 B, sides' render part 8 B with **the side's sector in byte 7** (its pad until now), patchless bitmaps; the vertex cache is not stored (FILL) | about 36 KB; 183 KB | A on M: levels counts |
| Lines, compact | v1, v2 (coordinates), the two sides, flags, special, tag: 15 B, the game lump's form | 20,280 B; 112 KB | A on R `p_setup65.s:42-45` |
| Sectors' game part, compact | special, tag (the rest is in `LVMAP` or computed) | 1 KB; 6 KB | A |
| Blockmap, reject | The game lumps verbatim (bytes the canonical model compares) | 23 KB (E1M8 blockmap 19,400 B raw); 110 KB | M: R1; A |
| Map things | Each kept thing: x, y, angle (45° units), options, and the mobj type. The converter resolves `P_FindDoomedNum` only where upstream does: never for type 1 (the player), and only for a thing with an easy, normal or hard flag (one that spawns at some skill [R `p_spawn65.s:924-962`]); it fails on an unknown number only for such a thing, and stores "none" for a thing that never spawns | 3.6 KB (E1M6, 449 kept [M: Z1, `_g_thingPoolSize`]); 18 KB | A on M: R1 |
| W tables, masked tables | `TXBANK`, `TXLO`, `TXHI`, `TXWM`, `TXHT`, `FLATCM` (the render window's pages), `TXMP` | 2.9 KB; 26 KB | R `RENDER.md` 3.4; `RENDER-MASKED.md` 1.10 |
| `SPRFR` | The map's sprite frames (a lump not resident in this map's set points to the placeholder, as upstream) | 9.6 KB; 86 KB | R `rlayout.py:186-189` |
| Variant columns and tails | The texel columns and patch tails where the map differs from the canonical ones (the apply list), and the canonical bytes of the same places (the undo list) | 219 columns and 125 tails over all maps: 28,032 + 16,000 B, twice | M: S1 |
| Colour tables | The whole `GSVIEWn` record (14 tints of 16 colours, the best pairs, the A and B tables [R `i_viigs65.s:1040-1050`]), `FUZZDARK` (256 B), the sky's slot | about 1.2 KB; 11 KB | R `i_viigs65.s:1043-1077`; A |
| The load program | Memory-API request lists and the step list (2.2) | about 2 KB; 18 KB | A |
| **All** | | **about 1.0 MB, 21 banks** | A; stage A measures |

Upstream's own store is 1,821,696 bytes, B1-compressed, with 152 units
of 2,134,580 bytes for the nine maps and the common set [M: W1]. The
native store is larger in RamWorks (30 + 17 + 21 banks) because the
texels are slots (128 B a column), not patches, and nothing is
compressed.

### 1.4 Sharing across maps

The maps share almost everything [M: S1]:

| | Sum over the nine maps | Distinct | Differing from the canonical choice |
| --- | ---: | ---: | --- |
| Texel slot blocks (by texture) | 4,649,984 B | 149 blocks of 115 textures | 34 blocks, in 219 columns (28,032 B) |
| Patch store entries (lump + tail) | 5,242,836 B | 535 pairs of 410 lumps | 125 tails; no lump's bytes differ |

So the texel and patch stores keep one copy, and the load program of map
m patches the few columns and tails where m differs. Which map's
variants are in place is state: **`LV_VARMAP`**, one byte of the
persistent globals (main `$03A4`, after the level's counts [R
`MEMORY_MAP.md` 3.1]), 0 when the stores are canonical, else the map
number 1-9. The persistent globals are zeroed at start, and the boot
loads the canonical stores, so it is 0 after the boot. The load's
`VARIANTS` step (2.2) runs the undo list of the map `LV_VARMAP` names
(none for 0), then m's apply list, then sets `LV_VARMAP` = m. Both lists
are memory-API COPY requests of 128 bytes each, the undo lists in the
store indexed by map. A saved-game load (milestone 11) goes through the
same level load, so it needs nothing more. The per-level tables (`TXBANK`, `PHDR`, the
`R_SRC` addresses the renderer makes) point into the shared stores, so
nothing else moves.

The harness layout of `levelconv.py` packs each map's textures and
patches first fit into banks 11-30 and 32-47 [R `rlayout.py`;
`MEMORY_MAP.md` 13]. The converter writes that layout too
(`--layout harness`), byte for byte comparable with `levelconv.py`, and
the game layout of this section; the two are the same slots and entries
at other addresses, and `texmap.json` and `patchmap.json` map both to
upstream's addresses. That claim is checked, not assumed: checkpoint B
reads each loaded window back into harness `level.img` form through the
game layout's `texmap.json` and `patchmap.json` and compares every slot
and tail with `levelconv.py`'s (6.2).

### 1.5 Compression: none

The bank tally (1.6) leaves 8 banks spare with the level part
uncompressed. Compression would save about 12 banks [A: 2-2.5:1 on
geometry], at the cost of a decoder in the load window and a block
format. The store's block header reserves a codec byte (0: raw); if
stage A measures the allocation with fewer than 8 banks spare, stage A
adds our own LZ codec (host encoder, a 65C02 decoder in the load window
that decodes 16 KB blocks into W and copies them out), and says so.
Nothing of B1 is used: upstream's format is not ours to need.

(stage A) Measured: 14 banks spare (1.6 as corrected), so no codec; the
codec byte stays 0 in every block header.

### 1.6 Placement in RamWorks

The game's allocation is milestone 11's; this milestone proposes it,
because the store must have a place. It keeps every bank milestones 7
and 8 fixed in `rlayout.py`, so the renderer's builds and tests do not
change; the new names go into `rlayout.py` too (one source).

| Banks | Name | Content | Count | Label |
| --- | --- | --- | ---: | --- |
| 1-5 | | spare (milestone 5's harness banks) | 5 | |
| 6, 7 | `LVSEG`, `LVMAP` | Level window: segs; nodes, subsectors, sectors, sides | 2 | R `rlayout.py:43-44` |
| 8 | `RENDB` | Drawsegs, `OPENHI` | 1 | R |
| 9-31, 56-63 | `TEX0`.. | Texel store (stage A: 31 banks; the 116 blocks, S1's 115 and one texture made only in play, do not pack into 30: a 32 KB and a 16 KB block do not share a bank, and 34 of 16 KB and 51 of 8 KB need 31 at least) | 31 | M: stage A |
| 32-47, 64 | `SPR0`.. | Patch store | 17 | M: S1 |
| 48, 49 | `SPRT`, `WPRO` | Scale records, `PHDR`, the map's `SPRFR`, `SPRBOUND`; weapon profiles | 2 | R |
| 50 | `RTH` | Render things, 2,026 slots (3.1) | 1 | A |
| 51-55 | `RECSP`, `RECW` | Record spill, parked batches | 5 | R |
| 65-68 | `LVG0`, `LVG1`, `LVG2`, `LVC` | Level window: lines (E1M6 43,264 B [A on M: levels]); sectors' game part, line tables, blocklinks, flood lists (about 23 KB [A]); blockmap and reject (at most about 24 KB [A on M: R1]); colormaps (17,408 B), the `GSVIEWn` record, `FUZZDARK` (about 19 KB) | 4 | A (2.3) |
| 69-71 | `MOBJA`, `MOBJB`, `MOBJC` | Mobjs' game part, 2,026 slots: three groups of 24 B, each at its `RTH` slot's address (stage C; the design had `MOBJ0-5`, 128 B a slot, banks 69-74) | 3 | M: stage C |
| 72-74 | | spare (stage C) | 3 | |
| 75, 76 | `ZONE0`, `ZONE1` | Specials; sector nodes (the cold game globals went to main's globals block, stage C) | 2 | A (3.2) |
| 77-90 | `STORE0`.. | The level parts of the nine maps (the texel banks' slack first: 203 KB there, the rest in 14 banks) | 14 | M: stage A |
| 91-97 | | spare (the design's `STORE` estimate) | 7 | |
| 98 | `LCODE` | The load phase's image | 1 | A |
| 99 | `GTAB` | The game's constant tables: `states`, `mobjinfo`, `COLORMAP`, the switch and animation tables (about 17.5 KB, 1.3); the rest for milestone 10's constant game tables | 1 | A |
| 100-104 | | Songs and effect scripts | 5 | R `NATIVE.md` 4.4 |
| 105-110 | | 2D: status bar, fonts, menus, pictures, text; 2D caches | 6 | A (upstream's resident WAD is 3 banks of 64 KB [R `memmap.inc:43-46`]) |
| 111 | `LVS` | Level window: milestone 10's sight and move tables, one bank reserved (upstream's reach `$C000` of their bank plus 2 B a line [R `p_sight65.s:82-102`]; their native layout is milestone 10's, 2.6) | 1 | A |
| 112-115 | `CODE` | Code library: the render images (112, 113), the tic and 2D images | 4 | R `rlayout.py:75-79`; A |
| 116-122 | `FSTEP0`.., `MT_TBANK`, `MT_RLO`, `MT_RHI` | Tables | 7 | R |
| 123, 124 | `LOGTAB` | 64 KB of sight logs (milestone 10) | 2 | A |
| 125, 126 | | spare | 2 | |
| **Used** | | | **109 of 126** (stage C; stage A's 112, the design's estimate 118) | |

Spare: banks 1-5, 72-74, 91-97, 125, 126 (17 as built in stage C;
stage A's 14 before the mobjs' game part took 3 banks, not 6; the
design's estimate 8: banks 1-5, 31, 125, 126).

**Against `NATIVE.md` 4.4** (76-82 of 126 [A there]):

| `NATIVE.md` 4.4 row | Banks there | Here | Why it changed |
| --- | ---: | ---: | --- |
| Code library | 3-5 | 5 (4 + `LCODE`) | |
| Level window, current map | 22-24 | 7 (`LVSEG`, `LVMAP`, `LVG0`, `LVG1`, `LVG2`, `LVC`, `SPRT`'s map part) | Texels and sprites are resident (1.4) |
| Level store, all maps | about 28 | 21 + 30 + 17 = 68 | Slots of 128 B a column (`RENDER.md` 1.4) instead of patches; no compression |
| Zone | 4 | 6 (`RTH`, `MOBJA-C`, `ZONE0-1`; the design's 9 with `MOBJ0-5`) | Mobjs bounded by upstream's zone, not by its typical use (3.1) |
| Big tables | about 6 | 10 (with `LOGTAB`, `GTAB`) | `FSTEP` and `RECIP_TABLE` take 6 in 48,640 B banks; the game's tables get a bank of their own |
| Per-map sight and move tables | 3-4 | 1 (`LVS`) | Milestone 10 (2.6); `LVC` has no room for them beside the colormaps |
| WAD directory and resident lumps; 2D caches | 3; 1-2 | 6 | |
| Records (pair build) | 1 | 5 (`RECSP`, `RECW`) and `RENDB` | Milestone 8's spill and parking, F1.2.1 too |
| Songs and effects | 5 | 5 | |
| **Total** | **76-82** | **118** (design); **109** as built (stage C) | |

The risk is the spare: 8 banks against the later milestones' [A]
budgets (2D, tic code), exactly the codec's threshold (1.5). Section 7,
risk 1. (As built in stage C: 17 spare.)

### 1.7 Files and the boot load

Files on the boot disk, each a bank file of the format of
`demos/doom/src/kernel/loader.s` ("A2DM", a segment list of bank,
address and length, then the bytes [R `loader.s:36-45`]); a file holds
at most 49 segments in that format [R `loader.s:72` `MAX_SEGS`],
so the large ones are several files:

| Files | Content | Bytes | Label |
| --- | --- | ---: | --- |
| `TEXELS.n` | The texel store | 1,286,144 | M: S1 |
| `PATCHES.n` | The patch store, `PHDR` | 820,544 | M: S1; A |
| `MAPS.n` | The nine level parts and their directory | about 1.0 MB | A |
| `TABLES.n` | The constant tables, `GTAB`, the aux card's tables (destination code `$FE` as `RENDER.hdv` does [R `tools/native/rdisk.py:30-36`]) | about 320 KB | A |
| `CODE` | The phase images (render, masked, load), the card images | about 100 KB | A |

**The boot** (stage B, test program `LEVELS.SYSTEM`; milestone 11's
`DOOM.SYSTEM` uses the same code): ProDOS loads the system file at
`$2000`; it probes 126 banks (bank 127 excluded, `NATIVE.md` 4.4) and
stops with a message below that; it reads each bank file through the MLI
into a main staging buffer and copies each segment into its bank (CPU
copy with RAMWRT and `$C073`, 0.246 µs a byte [M: `NATIVE.md` 4.3], or a
memory-API COPY main to PSRAM); then it installs the card images and
leaves ProDOS, as `loader.s` steps 3-5 do [R `loader.s:17-35`]. Time
[A]: about 3.5 MB at 0.25-0.34 µs a byte, 0.9-1.2 s of copies on a2vm,
where the MLI trap serves the reads [R `MILESTONES.md` 3.1, "Start-up"]
at little emulated cost [A]; on the card the ProDOS read rate of the slot-7 drive is not
measured (at 100-300 KB/s, 12-35 s). Stage C reports a2vm's figure;
milestone 12 the card's.

## 2. The level window and the native P_SetupLevel

### 2.1 Upstream's order, step by step

The native setup keeps upstream's order wherever the order is
observable: `P_Random` calls, the thinker list, the sector and block
lists, `validcount`, the pool's slots. Copies and static computations can
move freely.

| # | Upstream [R `p_setup65.s`] | Native | How |
| --: | --- | --- | --- |
| 1 | `W_LoadSet` (`:101`) | The load program's copies (2.2): level part; `VARIANTS`: undo `LV_VARMAP`'s variants, apply this map's (1.4) | Memory API + 65C02 |
| 2 | `I_SetLevelPalette` (`:103`) | The `GSVIEWn` record into `LVC`; colormaps A and B from its tables and `COLORMAP` (`GTAB`) into `LVC`, then PRIVATE into main `$2000-$5FFF`, `$0400-$07FF`; `FUZZDARK` PRIVATE into aux 0 `$0800`; `FLATCM` with the W tables | 65C02 + memory API |
| 3 | `LR_OK` 0, totals 0, `partime` 180, player counts 0, `viewz` 1 (`:104-120`) | The same globals | 65C02 |
| 4 | `S_Start`, `Z_FreeTags`, `P_InitThinkers`, `leveltime` 0 (`:121-127`) | Channels stopped, a music hook (milestone 11); the pools reset (3.1); the thinker list emptied | 65C02 |
| 5 | `loadThings` (`:132`): the pool, all `MT_NOTHING` and free | The pool of `poolsize` slots: game parts cleared, type `MT_NOTHING`, all free; `I_Error` above 512 [R `p_spawn65.s:1367-1375`] | 65C02 + FILL |
| 6 | `loadLineDefs` (`:133`) | Lines expanded from the compact form into `LVG0`: deltas, box (upstream's signed compares with the overflow test [R `:311-353`]), tag and special sign-extended, slope type, flags, stamps 0 | 65C02 |
| 7 | `loadSegs`, `loadBlockMap`, `P_InitBlockRows`, `G_ID` 0, `loadNodes`, `loadGrid`, `rlSightLogs` (`:134-142`) | Segs and nodes are in the copied `LVSEG` and `LVMAP`; the blockmap copied, its origin and size into globals, blocklinks FILLed with "none"; `G_ID` 0; `LOGP` its constant | Memory API + 65C02 |
| 8 | `loadSectors`, `loadSideDefs`, `R_MakeLevelColumns`, reject, `loadSubsectors` (`:143-151`) | Copied (`LVMAP`, `LVG2`); the columns are resident | Memory API |
| 9 | `newPoint` (`:152`) | `R_PointInSubsector`'s last-point cache is not kept natively (2.4) | None |
| 10 | `groupLines` (`:153`, `:742-1036`) | Subsector sectors (its first seg with a side), line counts, the line tables (each line in its front, then its back sector if another), sound origins with `addToBox`'s else-if and `halfSum`'s rounding | 65C02 |
| 11 | `rlSave`, `rlSightTables` (`:154-155`) | No copy; `P_InitFlood` natively; the sight tables: milestone 10 (2.6) | 65C02 |
| 12 | `player.mo` NULL, `loadThings2` (`:156-158`) | Each map thing in order through `P_SpawnMapThing` (2.4) | 65C02 |
| 13 | `P_SpawnSpecials` (`:159`) | 2.5 | 65C02 |
| 14 | `P_MapEnd` (`:160`) | `tmthing` NULL | 65C02 |
| 15 | `W_LevelDone` (new map only, [R `w_level65.s:507-519`]) | Nothing at run time: the column memory it leaves is the resident texel store's (1.2); the automap cache is milestone 11's | None |

**One path.** Upstream's reload of the same map (`RL_ON`, fact 7) skips
work; the native setup always runs all of it (the level part's dynamic
fields must be restored anyway: play changed the sectors and sides in
`LVMAP`). The two setups do not leave the same canonical state
(`prndindex`, `validcount`, the line stamps and the reborn player
differ), so the harness compares each reload's native canonical state
with ref816's (acceptance 1) and its static level kinds (sectors' static
fields, lines, sides, subsectors, segs, nodes, blockmap, reject, line
tables, flood lists) and its level window outside stage C's mask with
the first load's (5.1).

**No per-map choice of path in the loader**: a map whose variant columns
are already in place (the same map again: `LV_VARMAP` = m) still undoes
and re-applies them; it costs at most 88 KB of copies [A on M: S1].

### 2.2 The load program and the memory API

The converter writes, per map, a load program into the store:

| Item | Form | Use |
| --- | --- | --- |
| Requests | Memory-API CONTROL requests, each a descriptor list of COPY (source bank and address, destination bank and address, length) and FILL (destination, length, byte); every endpoint inside `$0200-$BFFF` of its bank; PRIVATE on every descriptor whose destination is main memory or aux 0; at most 45 KB of data a request (one VBL period [R `NATIVE.md` 4.5]) | The loader fetches each request's bytes from the store into a W buffer with `FAR_GET` and hands it to the transport |
| Steps | A list of step numbers with arguments: `COPYREQ n`, `VARIANTS m`, `LINES`, `GROUP`, `FLOOD`, `CMAPS`, `PRIVREQ n`, `SPAWN`, `SPECIALS` | `nl_run` dispatches them in order; `VARIANTS m` runs the store's undo request list of map `LV_VARMAP` (none for 0), then map m's apply list, then sets `LV_VARMAP` = m (1.4). (stage B: the entry is `nl_load(m)`, which finds map m's header through the store's directory at a fixed place, STORE0 `$0200`: `llayout.STORE_DIR`) |

The copies of one load [A, largest map]:

| Destination | What | Bytes |
| --- | --- | ---: |
| `LVSEG` | segs | 44,688 |
| `LVMAP` | nodes, subsectors, sectors, sides, patchless bitmaps; FILL of the vertex cache's three planes | about 36,000 + 3,621 FILL |
| `LVG2`, `LVG1` | blockmap, reject; FILL of blocklinks (the compact lines and sectors are read in place from the store by step 6) | about 30,000 |
| `SPRT` | `SPRFR` | 9,600 |
| `CODE` 112, 113 | The W tables, `FLATCM`, `TXMP` in the render images | 2,880 |
| Texel and patch stores | undo `LV_VARMAP`'s variants, write this map's | at most 88,064 |
| `LVC` | the `GSVIEWn` record | about 1,000 |
| Main, aux 0 (PRIVATE) | colormaps (17,408), `FUZZDARK` (256), from `LVC` | 17,664 |
| **All** | | **about 234 KB** |

Rates [M: model, `NATIVE.md` 7]: PSRAM to PSRAM 0.258 µs a byte on
f121, 0.065 with the firmware design; PSRAM to main 0.343: about 60 ms of
copies on f121 [A]. The transport lives in the load window
(`MEMORY_MAP.md` 4.1 fallback 3, taken by milestone 7), not in the card.

### 2.3 What the 65C02 computes

Each of these is static level data, made the same way upstream makes it
and checked by the window comparison (checkpoint B) and by the canonical
model (acceptance 1):

| Step | Upstream | Inputs | Outputs | Exactness to keep |
| --- | --- | --- | --- | --- |
| `LINES` | `loadLineDefs` [R `p_setup65.s:259-404`] | compact lines | `LVG0` records (3.2) | `dx`, `dy` 16-bit; the box by `v1.y - v2.y` with the overflow flip (`bvc`/`eor #$8000`) [R `:311-318`, `:334-340`]; the slope type from `dy ^ dx` [R `:364-376`]; tag and special sign-extended bytes |
| `GROUP` | `groupLines`, `eachLine`, `lineToSector`, `soundOrigins`, `halfSum`, `addToBox` [R `:742-1102`] | sides' sectors (`LVMAP` byte 7), segs, lines | subsector sectors (`LVMAP`), each sector's line count and table start, the line tables (`LVG1`), sound origins | Subsector: the first seg with a side [R `:778-789`]; a line goes to its front sector, then to its back sector when that exists and differs [R `:861-895`]; tables in sector order; the box's else-if [R `:1063-1102`]; `halfSum` an arithmetic shift of each 32-bit side, then the sum [R `:1038-1061`] |
| `FLOOD` | `P_InitFlood` [R `p_pspr65.s:1253-1380`] | lines, sectors | per sector: its entries without `ML_SOUNDBLOCK` up from the first, those with it down from the end; the entries (other sectors) | One walk of the lines **from the last to the first**, as upstream [R `:1300-1303`]; for each two-sided line with two different sectors, the back into the front's list, then the front into the back's (`fbOne` [R `:1361-1374`]). So a sector's entries without `ML_SOUNDBLOCK` read in **reverse** line order and those with it (filled down from the end) in **forward** line order. The bridge reads the lists as two sequences a sector [R `tools/bridge/README.md:245-248`] |
| `CMAPS` | `I_SetLevelPalette`'s loop [R `i_viigs65.s:1063-1077`] | `COLORMAP` (34 × 256), `GSVIEWn`'s A and B | colormaps A, B (34 × 256 each) in `LVC` | `A[i] = GSVIEW_A[fullcolormap[i]]`, the same for B |

Not computed natively, with the reason: `FLATCM` (`fullcolormap[cm ×
256 + colour[f]]` [R `i_viigs65.s:955-957`], 1,088 B a map: cheaper
stored), `FUZZDARK` (a nearest-colour search [R `i_viigs65.s:1078-1100`],
256 B a map: stored), the vertex numbers (`I_InitSegVertices`' hash; the
converter's numbering is the same up to renaming [R `RENDER.md` 1.3]),
the column tables (resident).

### 2.4 Spawning the things

`SPAWN` runs `P_SpawnMapThing` on each map thing in the store's order
(the lump's order: identities and `P_Random` follow it):

| Routine | Upstream | Native, in the game core (4.1) |
| --- | --- | --- |
| `P_SpawnMapThing` | Type 1: the player. Else the skill's flag (easy for baby and easy, normal for medium, hard for hard and nightmare); `P_SpawnMobj(x << 16, y << 16, ONFLOORZ, type)`; `tics = 1 + P_Random() % tics` when tics > 0; kills and items counted; angle `ANG45 × angle`; `MF_AMBUSH` [R `p_spawn65.s:913-1037`] | `gs_mapthing`: the same, the type precomputed by the converter |
| `spawnPlayer` | `G_PlayerReborn` when reborn; `P_SpawnMobj(MT_PLAYER)`; the player's fields; `P_SetupPsprites` [R `p_spawn65.s:1058-1118`; `g_game65.s:674-707`] | `gs_player`, `gs_reborn` |
| `P_SpawnMobj` | `newMobj` (the pool's free slot with the highest index, else a zone block); fields from `mobjinfo`; one `P_Random` call "for compatibility"; the spawn state without its action; `P_SetThingPosition`; floor and ceiling; z; the thinker: `P_MobjThinker` below `MT_MISC0`, `P_MobjBrainlessThinker` for states with tics other than -1, else none; `totallive` [R `p_spawn65.s:72-262`] | `gs_mobj` |
| `P_SetThingPosition` | `R_PointInSubsector`; the sector's list head (unless `MF_NOSECTOR`), `P_CreateSecNodeList`; the block's list head (unless `MF_NOBLOCKMAP`; off the map: none) [R `p_map65.s:748-755`] | `gp_setpos` |
| `R_PointInSubsector` | The grid `SGRIDn`'s start node, then the BSP walk with `pointOnSide` (whole parts when `dx` or `dy` is 0, signs, else the low 32 bits of `(yp >> 8) × dx` against `(xp >> 8) × dy`); "the same result as a walk from the root" [R `r_iigs65.s:668-700`; `build/upstream/tools/sgrid.py:1-25`] | `gp_pointsub`: the descent from the root through `LVMAP`'s nodes, with upstream's side test; it never backtracks, so it keeps no frames; no grid, no last-point cache (both change no result) |
| `P_CreateSecNodeList` | `validcount` raised; the block walk (`lineBlocks` with `PIT_GetSectors` [R `p_map65.s:1684-1880`]) with `P_BoxOnLineSide`; then `P_AddSecnode` of the thing's own sector, taken from bank `$21`'s `SS_SEC` [R `:2560-2583`]; the node pool of 32 a zone block, `SN_FREE` | `gp_secnodes` (3.1's node pool), with the walk's rules below; the thing's own sector from its subsector's record in `LVMAP` (the sector byte `GROUP` writes), since `SS_SEC` is one of the tables that move to milestone 10 (2.6) |
| `P_AddThinker` | At the list's end [R `p_think65.s:39-44`] | `gt_add` |
| `P_SetupPsprites` | Both psprites' states NULL, pending = ready, `bringUpWeapon` → `P_SetPsprite(upstate)` with its action [R `p_pspr65.s:1181-1193`] | `gw_setup`, `gw_setpsprite` with the actions an up state and the flash's NULL state reach (`A_Raise`); any other action is a stop in this milestone, milestone 10 completes the table |

**The block walk's rules** (`lineBlocks`, [R `p_map65.s:1684-1880`]),
each one observable in the order of the sector nodes or in the line
stamps:

- the blocks of the box, **x outer and y inner**, as the C loops;
- each block's list from `_g_blockmaplump + 2 × blockmap[block]`,
  **skipping its first entry** (the 0 that starts every list: `ldy ##2`
  [R `:1798`]); with `wadtool.py`'s suffix-shared lists that entry is
  the list's own 0, and reading it would add line 0 to every block;
- a line whose stamp equals `validcount` is skipped; every line tested is
  stamped with `validcount` (the walk does not change `validcount`
  itself);
- the box test in whole map units [R `:1690-1700`, `:1727-1750`]: the
  right and top edges as `(edge >> 16) - (low word == 0)`, the left and
  bottom as `edge >> 16`; a right or top edge of exactly -32768.0
  overflows, and then the bottom bound is 32767, which takes every line
  out; a horizontal or vertical line that passes the box test crosses
  the box, a slanted one takes `P_BoxOnLineSide`.

**`P_Random` in setup order** [R as above; `p_lights65.s:75`, `:81`,
`:293`, `:326`]: for each spawned thing, one call in `P_SpawnMobj`, then
one for its tics when its spawn state's tics are above 0; the player's
mobj one call. Then, in `P_SpawnSpecials`, one call for each light flash
and each strobe that is not synchronised, in sector order. The index is
the game's state (`prndindex`, main `$03EE` [R `src/native/MATH.md`
"Where it lives"]), injected before setup and compared after.

**The player start** is the map thing of type 1; there is no player
start or deathmatch start array: `wadtool.py` removes types 2, 3, 4, 11
and the multiplayer things [R `wadtool.py:214-222`], and a death reloads
the level [R `g_game65.s:569-573`, `:634-660`]. **Totals**: `totalkills`,
`totalitems` from the spawn, `totallive` from `P_SpawnMobj`,
`totalsecret` from `P_SpawnSpecials`.

**`RTHING`** (milestone 8's render part, 24 B [R `RENDER-MASKED.md` 1.8])
is written by `gs_mobj` and `gp_setpos`: x, y, z, the angle's high word,
sprite, frame, `MF_SHADOW`, `snext`; the sector's list head in `LVMAP`'s
sector record byte 13. The game and the renderer share this list.

### 2.5 `P_SpawnSpecials`

For each sector in order [R `p_spec65.s:439-492`]: special 1 a light
flash, 2 and 3 strobes, 8 a glow, 9 a secret (`totalsecret`), 12 and 13
synchronised strobes; then no buttons [R `:493-497`], then a `T_Scroll`
thinker for each line of special 48 in line order [R `:498-545`]. Each thinker is a
special of 3.1's pool, appended to the thinker list. The light thinkers'
fields and their `P_Random` calls follow `p_lights65.s:274-326`. **Each
light spawner sets the sector's `special` to 0**: `P_SpawnLightFlash`
through `takeSector`, `P_SpawnStrobeFlash` and `P_SpawnGlowingLight`
directly [R `p_lights65.s:280-360`]; a secret (9) keeps its special.

### 2.6 What moves to milestone 10, and why

| Moves | Why | What milestone 9 still covers |
| --- | --- | --- |
| The sight and move tables of bank `$21`: `SIGHTLOG`, `LINELOG`, `SS_SEGT`, `SS_ROW`, `SS_SEC`, `LNSEC`, `SEC58` (`P_InitSightLogs`, `P_InitSightTables`) [R `p_sight65.s:82-104`] | They are accelerators of upstream's `P_CheckSight` and line checks; their native layout (or whether they exist) is the sight code's decision, and the bridge excludes them as "level tables", derived data whose results routine tests check [R `tools/bridge/README.md:205-207`, `:400-402`] | Their inputs (lines, nodes, subsectors, sectors) are in the canonical comparison; the bank `LVS` is reserved for them (1.6), and the store's 8 spare banks take their per-map form if milestone 10 stores rather than computes them; the converter has the hook to add a table per map. The one consumer milestone 9 has, `P_CreateSecNodeList`'s `SS_SEC`, reads the subsector record instead (2.4) |
| `BMROW`, `LN36` (`P_InitBlockRows`) | Address tables: natively an index times a power of two | Nothing to cover: no state |
| `P_SetPsprite`'s full action table | Weapon logic | The up states' actions, the only ones setup reaches |
| `SPRBOUND` | Made at the first rendered frame (milestone 11, `RENDER-MASKED.md` 0.3 row 3) | |

Acceptance 1 therefore covers every canonical object and global setup
leaves; the bank `$21` tables are a named exclusion (5.2), checked by
milestone 10.

## 3. The zone

### 3.1 The allocator and its capacities

Upstream's zone is four banks of linked blocks with a rover, purgeable
cache blocks and level tags [R `z_zone65.s:1-11`, `:367-373`, `:469-473`,
`:624-627`]. Natively nothing is cached (everything is resident) and the
level's tables have fixed places (2.2), so the zone becomes **fixed
pools by kind**:

| Pool | Policy | Capacity | Why that capacity |
| --- | --- | ---: | --- |
| Mobjs of the pool | Upstream's: the free slot with the highest index, a bitmap as `TP_BITS` [R `p_spawn65.s:1249-1258`] | `poolsize` = the map's `THINGS` count, at most 512 | Identity is the pool slot [R `tools/bridge/README.md:113`] |
| Zone mobjs | The lowest free slot after the pool's | 2,026 - `poolsize`: at least 1,514; 1,910 on E1M1 (pool 116), 1,912 on E1M8 (114) | Upstream's zone can hold at most (free + `PU_CACHE` + level-special bytes) / 136 more mobjs: a mobj is 120 B and a 16-byte header, rounded to 16 B, so 144 B a block and 136 a conservative divisor [R `z_zone65.s:20-33`, `:273`]. Z1's 674 (E1M6) to 1,479 (E1M1) were measured minutes into play; at the end of setup the zone has more free bytes (every sector-node pool allocated in play, 848 B each: `SN_POOL` 32 × 26 B + 16 [R `p_map65.s:2131`; `offsets.inc:295`], and the specials live then), so the bound at the R dump can pass 1,514 on E1M1 and E1M8 (1,479 and 1,477 in play), which a fixed limit of 1,514 would fail although the map fits. Stage C measures it at every R dump with the bridge's zone walk and fails a map whose bound passes **2,026 - its `poolsize`** |
| Specials (plat, door, floor, light flash, strobe, glow, scroll) | Free list | 1,024 | At most one floor mover and one ceiling mover a sector, one light a sector, one scroller a line of special 48: 3 × 255 sectors + the scroll lines < 1,024 for every E1 map [A; the converter checks] |
| Sector nodes | Free list | 2,048 | No bound by construction; the coverage's most is 448 [R `tools/bridge/README.md:317-319`]; a full pool is a stop with its name (risk 6) |
| Line tables, blocklinks, flood lists | Fixed by the map | from the load program | |

Upstream's zone mobjs are identified by rank (thinker list order, then
reach) and its specials and sector nodes by rank and reach [R
`tools/bridge/README.md:108-126`], so a native slot choice other than
upstream's addresses changes no identity. The pool keeps upstream's
policy because its identity is the slot.

**`RTHING` slots: 768 → 2,026.** Milestone 8 sized `RTH` at 768 slots
and left the pool's size to milestone 10 [R `RENDER-MASKED.md` "Stage A
as built"]. With the zone mobjs bounded as above, a render thing's slot
is its mobj's: 0 to `poolsize` - 1 for the pool, then the zone mobjs
from `poolsize`, so the zone mobjs' room is 2,026 - `poolsize`; one bank
holds 48,640 / 24 = 2,026 slots [A], all of `$0200-$BFFF`. `rlayout.RTHINGS` changes its count; nothing else in the
renderer depends on it.

### 3.2 The native game layouts (provisional for milestone 10)

**Superseded (milestone 10, 2026-10-02):** the game layouts as built are
`docs/GAME.md` section 1 (the mobj, the thinker list and the walk's
planes, the specials, the player and the globals, the sectors, lines and
bank `$21`'s tables, `validcount`, the sight state, the intercepts, the
placement), held by `tools/native/glayout.py` and the manifest
`native-game-1`. The table below is stage C's, kept for the record.

Records in RamWorks, power-of-two strides where they fit, fetched whole
by `FAR_GET` (`RENDER.md` 1.1). Milestone 10 owns the game logic's
layouts and may change these; the bridge's manifest (3.3) makes such a
change one edit in `rlayout.py` and the manifest.

| Object | Where | Fields |
| --- | --- | --- |
| Sector | `LVMAP` render record (16 B: heights, pics, light, `validcount`, thing list head [R `rlayout.py:132-134`]) and `LVG1` game record, 32 B | sound origin (8), sound target (2, a mobj handle), line count (2), line table start (2), floor and ceiling data (2 each, special handles), touching thing list (2), special, old special (1 each, sign-extended), tag (2), sound traversed (1) |
| Line | `LVG0`, 32 B, at most 1,520 lines a bank (E1M6 has 1,352 [M: levels]) | v1, v2 (4 each), dx, dy (2 each), sides (2 each), box (8), tag, special (1 each, sign-extended), flags, slope type (1 each), `validcount`, `r_validcount` (2 each); `r_flags`'s `ML_MAPPED` stays in `LNMAP` (main `$1B80`) |
| Side | `LVMAP` render record, 8 B; its sector in byte 7 | as `RENDER.md` 1.3 |
| Subsector, seg, node | `LVMAP`, `LVSEG` | as `RENDER.md` 1.3 (every canonical field is there) |
| Line tables | `LVG1`, 2 B an entry (a line number) | |
| Blocklinks | `LVG1`, 2 B a block (a mobj handle, `$FFFF` none) | |
| Mobj | `RTHING` (24 B, `RTH`) and a game part in `MOBJA`, `MOBJB`, `MOBJC`, 24 B each at the same address as its `RTH` slot (stage C; the design had 128 B in `MOBJ0-5` [A: 72 B of fields, 380 a bank]) | thinker links and function, `sprev`, `bnext`, `bprev`, subsector, floor, ceiling and drop-off z, radius, height, momenta, health, type, tics, state, flags, target, move direction, threshold, pursue and move counts, reaction time, last enemy, touching sector list, `sightline` |
| Special | `ZONE0`, 32 B (1,024 of them: 32 KB; stage C: a range of slots a kind, 1,280 in all, handles `$0800-$0CFF`) | its kind's fields (`schema.TYPES` [R `tools/bridge/schema.py:106-175`]: the largest, a plat, 23 B natively [A]), thinker links and kind (5 B) |
| Sector node | `ZONE1`, 16 B (2,048 of them: 32 KB; stage C: upstream's pools of 32 and its free list) | sector, thing, the four links, visited |
| Thinker list | Handles of 2 bytes: 0-2,025 mobjs, `$0800-$0BFF` specials (stage C: `$0800-$0CFF`), `$FFFF` the list's head (cap) | |
| Player, globals | Main `$1A80-$1FFF` (hot game globals [R `MEMORY_MAP.md` 3.3]) after `TEXTRANS` and `LNMAP`, and the rest of `ZONE1` for the cold ones (stage C: all in main's globals block `$1C80-$1E6E`, 495 B) | |

### 3.3 Identities and the bridge's manifest

`tools/native/llayout.py` (part of `rlayout.py`'s module family) writes
**`native-level 1`**, a `bridge-port-layout 1` manifest [R
`tools/bridge/README.md:263-306`] of every object of 3.2, from the same
constants the assembler uses. The format gains three encodings, added to
`tools/bridge/layout.py` with tests (existing manifests unchanged):

| Encoding | For | Rule |
| --- | --- | --- |
| `bit` | `line.r_flags` (`LNMAP`) | One bit of a plane: byte `plane + i >> 3`, bit `i & 7`; the field's other bits must be 0 |
| `handle` | Mobj, special and node references | A 16-bit handle with declared ranges to kinds (`mobj` below `poolsize`, `zmobj` from it, specials by range, `$FFFF` null) |
| `sxbyte` | `i16` fields kept as a signed byte (tag, special, sector specials) | Sign-extended; the writer refuses a value out of range |

Identity pairing: mobjs by slot (the same as upstream's pool slot by
construction); zone mobjs, specials and sector nodes by
`identity.renumber` from native slots [R `tools/bridge/README.md:124-126`];
the line tables by index (built in upstream's order, 2.3). `native-v1`
stays as the bridge's own machinery test.

### 3.4 The `validcount` wrap fix

`gv_inc` (game core, 4.1) raises `validcount`; on a wrap to 0 the release
build clears every stamp (each sector's in `LVMAP`, each line's
`validcount` and `r_validcount` in `LVG0`) and sets `validcount` to 1, as
`NATIVE.md` 15.1 row 4 decided; built with `-D VCWRAP_UPSTREAM` (every
lockstep and test build) it does nothing more than upstream. The stamps'
places are this milestone's, so the routine is built here with a unit
test (a level at `validcount` `$FFFF` before a setup whose sector nodes
raise it: the release build's stamps all 0 and `validcount` small, the
lockstep build equal to ref816); milestone 10 calls it from every game
increment. The renderer's `+1` in `nr_setup` (`rframe.s`) gets the same
wrap test and call in the release build (a stamp clear of at most about
1,600 records, about 5 ms once every 80 s of play [A on `NATIVE.md` 14
risk 10]); its lockstep and test builds are unchanged, so milestone 7
and 8's frame tests are not affected.

## 4. Modules, code placement, memory, budgets

### 4.1 Files

| File | Stage | Content |
| --- | --- | --- |
| `tools/native/wadconv.py` | A | The converter: inputs of 1.1, the store files, per map the `--layout harness` level (`levelconv.py`'s format), the game layout's expected window, and `inplay.json` (1.2) |
| `tools/native/umodel.py` | A | The model of upstream's memory at the end of the load (`W_LoadSet`, `R_MakeLevelColumns`, `W_LevelDone`'s `moreColumns` and `W_ZeroBank`): the window from the store's entries, the neighbouring banks, the column memory, the free parts of its holes |
| `tools/native/maplumps.py` | A | Our transforms of `DOOM1.WAD`'s map lumps to the game's form |
| `tools/native/lstore.py` | A | The store format: blocks, the directory, the load program, the request lists; reader and writer |
| `tools/native/setupcap.py` | A | The ref816 setup dumps (5.1) and the generated tour scripts |
| `tools/native/llayout.py` | A, C | Banks, records, zero page, the `native-level 1` manifest (in `rlayout.py`'s family; `rlayout.py` imports its bank names) |
| `tools/native/level_check.py` | A, B, C | The converter against `levelconv.py` (A); the window against the converter, and read back into harness form against `levelconv.py` (B); the canonical comparison, flood depths, timing (C) |
| `tools/native/ldisk.py` | B, C | `LEVELS.hdv` (1.7, 5.4), with the existing port's disk writer as `rdisk.py` does [R `tools/native/rdisk.py:12-16`] |
| `src/native/lload.s` | B | `nl_run`: the step list, the transport, the requests, `VARIANTS` |
| `src/native/lgeom.s` | B | `LINES`, `GROUP`, `FLOOD`, `CMAPS` |
| `src/native/lboot.s` | B | `LEVELS.SYSTEM`: the probe, the bank files, the install |
| `src/native/gspawn.s` | C | Game core: `gs_mapthing`, `gs_player`, `gs_reborn`, `gs_mobj`, the pool |
| `src/native/gpos.s` | C | Game core: `gp_setpos`, `gp_pointsub`, `gp_secnodes` (`P_CreateSecNodeList`, the block walk, `P_BoxOnLineSide`) |
| `src/native/gthink.s` | C | Game core: the thinker list, the pools |
| `src/native/gspec.s` | C | Game core: `P_SpawnSpecials`, the light spawners, the scrollers |
| `src/native/gweap.s` | C | Game core: `gw_setup`, `gw_setpsprite` (the up states' actions) |
| `src/native/gvalid.s` | C | Game core: `gv_inc` and the wrap fix |
| `src/native/lsetup.s` | C | `nl_setup`: 2.1's steps 3-5, 12-14 around the load program |
| `src/native/ldriver.s` | B, C | The a2vm test driver (card `$E000`): pre-state in, setup, snapshot |
| `src/native/level.cfg`, `level.mk` | B, C | The load image's link (an overflow fails it), builds `ltest` (harness), `lprof` (cost phases), `lgame` (the image the disk loads) |
| `tests/test_native_level_conv.py`, `test_native_level_load.py`, `test_native_level_setup.py` | A, B, C | 5.7 |

The `g*.s` modules are the **game core**: assembled into the load image
now and into the tic images by milestone 10, from the same sources, with
the same zero page.

### 4.2 Code placement

The load phase is a mode window (`MEMORY_MAP.md` 3.5: "level load
... `$6000-$BFFF` mode window"), loaded by the phase loader (`far_pload`
[R `MEMORY_MAP.md` 13]) from `LCODE`:

| Range | Content | Bytes |
| --- | --- | ---: |
| W `$6000-$6592` | `MATHW`, `AUXW` (the same bytes as the render images', loaded with this image) | 1,427 [M: M8] |
| W `$6600-$9FFF` | Load and game-core code | 14,848 room; about 9 KB [A, 4.4] |
| W `$A000-$AFFF` | The current request (up to 4 KB of descriptors; the data is not staged: COPY goes PSRAM to PSRAM) | 4,096 |
| W `$B000-$BC7F` | `mobjinfo` for the spawn, copied from `GTAB`: 50 types of 64 B, upstream's records as `rtables.py` copies them [R `info.inc:4-5`; `offsets.inc:1017`]; `states` (314 of 16 B) stay in `GTAB`, one `FAR_GET` a state | 3,200 |
| W `$BC80-$BFFF` | Buffers: a map thing, the node record being tested by `gp_pointsub` (32 B; the descent keeps no stack), the line and sector records being expanded; the rest free | 896 |

The card is unchanged: bank 1 `$DC00-$DFFF` keeps the far layer and the
phase loader (35 B free [M: M8]); nothing new goes there. The aux card's
trig tables are not used at load.

### 4.3 Zero page and stack

Main zero page [R `MEMORY_MAP.md` 2]:

| Range | Owner | Content |
| --- | --- | --- |
| `$00-$17` | platform, far layer | as today |
| `$18-$37` | **game core** (32 B) | the mobj being made, the thing's box, the block walk's position, the node walk's node, handles; the same bytes in milestone 10's tic phase |
| `$38-$41` | load | the step and request pointers |
| `$48-$AF` | load | `GROUP`'s and `FLOOD`'s working state, the box (`SU_BOX`'s 16 B), the colormap loop |
| `$B0-$D7` | math | `MATH.md`'s block |
| `$D8-$FF` | IRQ | |

Stack: the deepest chain is `gs_mapthing` → `gs_mobj` → `gp_setpos` →
`gp_secnodes` → the block walk → `P_BoxOnLineSide` → a product, about 40
B [A], within the level load's 128 B budget [R `MEMORY_MAP.md` 2]; the
node walk is a descent from the root that never backtracks, so it uses
no stack. `ldriver.s`
calls `nl_setup` with S = `$EF` and a2vm's `--lowest-s-in` measures it,
as milestone 7 did [R `RENDER.md` 3.3].

### 4.4 Size budgets

[A] from upstream's sizes and milestone 7's measured expansion (1.8 for
16-bit code [M: `memory` 2.2]):

| Module | Budget, bytes |
| --- | ---: |
| `lload.s` with the transport | 1,200 |
| `lgeom.s` | 2,000 |
| `gspawn.s`, `gweap.s` | 2,200 |
| `gpos.s` | 2,200 |
| `gthink.s`, `gvalid.s` | 700 |
| `gspec.s` | 900 |
| `lsetup.s` | 500 |
| **All** | **9,700 of 14,848** |

`level.mk sizes` prints each module's size against its budget from the
first build.

## 5. The harness

### 5.1 Setup dumps on ref816

`tools/native/setupcap.py` runs ref816 with its own bounded options, as
`rendercap.py` does: a first run `--mark`s every `P_SetupLevel` entry,
every `RTL` of `P_MapEnd`, every `W_LevelDone` entry and every
`bmSignOff` entry; the second dumps at each `P_SetupLevel` entry, at the
`P_MapEnd` `RTL` that follows it (`P_SetupLevel` ends with `jmp long:
P_MapEnd` [R `p_setup65.s:160`]; `P_MapEnd` is also called each tic [R
`g_game65.s:574`, `p_think65.s:213`, `:299`], so only the first hit after
an entry is taken; no tic runs inside `P_SetupLevel`), and, when
`W_LevelDone` follows (a new map: `bmLoad` [R `m_menu65.s:1780-1789`]),
at the first `bmSignOff` entry after it, which is `W_LevelDone`'s last
instruction (`jmp long:bmSignOff` [R `w_level65.s:519`]). A reload of the
same map has no W point (`bmLoad`'s same-map path).

| Point | Ranges | Use |
| --- | --- | --- |
| E: entry | The game units' data (banks `$00`, `$02`, `$0D`), the pool map `$0A:8000-$0A:805F` | The pre-state injected into the native run: `prndindex`, the player, skill, map, `gametic`, demo flags, `validcount` |
| R: `P_MapEnd`'s return | All RAM, compressed | The truth of the game state: canonical state (bridge), the zone bound |
| W: end of `W_LevelDone` (new maps only) | All RAM, compressed | The truth of the level: the level for `levelconv.py` (5.3); its canonical state checked equal to R's (`W_LevelDone` changes no game unit) |

**The coverage set** (51 setups; stage A keeps the first loads of the
two reloads' maps too, the comparands of their static parts: 53 setups,
51 W points):

| Set | Runs | Setups | What it covers |
| --- | --- | ---: | --- |
| `tour-sk0` .. `tour-sk4` | 5: `coverage/tour.script` with the new-game menu's skill item changed (scripts generated into `build/`, as `lumps.py` generates its demo script [R `tools/ref816/lumps.py:100-114`]; `coverage/` and its test stay as they are). Nightmare opens an "are you sure" message [R `m_menu65.s:994-998`] that only `y` answers [R `:794-807`, `:917-921`]: the generator adds `press y` after the skill's `return` for skill 4, and every generated script asserts `_g_gameskill` equals its skill after `_g_usergame == 1` | 45 | All 9 maps at each of the five skills: E1M1 by a new game (`PST_REBORN`, `G_PlayerReborn`), E1M2-E1M9 after an exit (`PST_LIVE`, the inventory kept, the cheat flags of `iddqd`); every skill flag of `P_SpawnMapThing`, nightmare's reaction time |
| `demo1`, `demo2`, `demo3` | 3: the title loop with DEMO1, DEMO2 placed by `lumps.py` and DEMO3 as it is, stopped after the setup | 3 | E1M5, E1M3, E1M7 started by `G_DoPlayDemo` (demo playback on, the random index cleared) |
| `reborn` | 2: a new game, then `_g_player.playerstate` poked to `PST_REBORN` (`--poke-file`), which `G_Ticker` turns into `GA_LOADLEVEL` [R `g_game65.s:569-573`], in E1M1, and in E1M6 after the tour's way there | 2 | `RL_ON`: the reload of the same map (fact 7); E1M6 is the largest map. Compared: each reload's native canonical state with ref816's; its static level kinds and level window outside stage C's mask with the same map's first load (the dynamic state differs between the two setups: `prndindex`, `validcount`, the line stamps, the reborn player) |
| `newgame` | 1: `coverage/newgame.script` | 1 | The same as `tour-sk2`'s first: a determinism check of the setup dumps |

**Resources** [A]: the tour is 342 s of machine time [M: `build/ref816/
runs/divscan-tour/report.json`: 980,100,501 cycles at 2.86 MHz], taken as
its host time too, as milestone 8 planned its captures [R
`RENDER-MASKED.md` 4.5]; two runs (mark, dump) of each of the 11
scripts, the demos and reloads stopped after their setup: about 95 min
of runs, about 50 min at 2 jobs. Dumps: 51
return dumps and 49 end-of-load dumps at about 4 MB compressed (the level
sources are 68 MB for 13 [M: `build/native/render/levels/src`]), 51
small entry dumps: about 410 MB. `df -h /System/Volumes/Data` first.

### 5.2 The canonical comparison (acceptance 1)

For each setup: ref816's R dump through the bridge's `Reader` → C_ref;
the native machine (5.4) after `nl_setup`, read through `native-level 1`
by the port reader and renumbered → C_nat; `canonical.diff` in `exact`
mode, with these exclusions, each named in `level_check.py`'s report:

| # | Excluded | Why |
| --: | --- | --- |
| 1 | Bank `$21`'s level tables | Milestone 10's (2.6); the bridge claims them as derived level data [R `tools/bridge/README.md:205-207`] |
| 2 | `SGRIDn`, `PI_PREV*` | The grid and the last-point cache change no result [R `build/upstream/tools/sgrid.py:1-5`]; not kept natively (2.4) |
| 3 | The respawn copy (`RL_*`, `$0B:C000-$0B:FE09`) | Upstream's own cache of the reload path [R `p_setup65.s:1145-1163`] |
| 4 | The caches the bridge lists: `mobj.sightline`, `CS_PREV1`, `CS_PREV2`, `CS_PREVR`, `LR_*`, `TP_HW`, `GW_TAG`, `G_ID`, `line.gstamp` | Caches whose claim of not changing results routine tests check [R `tools/bridge/README.md:136-143`]; the native keeps `TP_HW`'s role in its own bitmap |
| 5 | Sight hints, guard counts | Address- and block-keyed caches [R `tools/bridge/README.md:205`] |
| 6 | The zone's headers, slack and free bytes | The allocator's layout (3.1) |
| 7 | `COLDIR`, the column tables and the column memory | The renderer's; checked slot by slot (5.3) |
| 8 | `VTXHASH` and the vertex numbers | The same numbering up to renaming [R `RENDER.md` 1.3] |
| 9 | `BMROW`, `LN36`, `SEC58` | Address tables (2.6) |
| 10 | The kind cache (mobj byte 11) | Already excluded by the bridge [R `tools/bridge/README.md:198`] |
| 11 | Sound channels, the music's state | `S_Start`'s sound side: milestone S4 and 11 (outside the canonical model already) |
| 12 | The automap cache, the busy sign, the status bar | Not game units (outside the canonical model already) |

Everything else is compared: every object of every kind and every
canonical global, the free pool slots' fields, `prndindex`,
`validcount` and every stamp, the lists as sequences. The run uses the
lockstep build (`VCWRAP_UPSTREAM`); the wrap fix has its own unit test
(3.4).

### 5.3 The converter against `levelconv.py` (stage A)

`levelconv.py` converts the nine `tour-sk2` W dumps (taken at the end of
`W_LevelDone`, so the column memory is the load's and the dynamic fields
are setup's: `W_LevelDone` changes no game unit). `wadconv.py --layout
harness` converts each map from the WAD and the release. Then:

1. `level.img`: byte for byte, all banks, except one named range: each
   sector record's thing list head (byte 13), which the converter leaves
   `$FFFF` because the spawn writes it (stage C compares it). (stage A:
   the head is `$FFFF` in `levelconv.py`'s too, the bridge reads no
   head for a sector; the named range is instead the rotate and flipmask
   bytes of a sprite frame both flag as not a frame, `SPRFR_BAD`: upstream
   reads them from its memory after the sprite's frames, which the
   converter does not model and no renderer reads.)
2. `level.json`: equal but the source hashes and provenance fields.
3. `texmap.json`, `patchmap.json`, `wtables.img`, `mtables.img`,
   `fuzzdark.bin`: byte for byte. (stage A: two parts of `wtables.img`
   hold upstream's history, which no load of the map determines, and are
   named: `TXHT`, since upstream's `textureheight` is never cleared and
   holds every texture loaded since the boot, so `levelconv.py`'s entry
   must be 0 or equal, and equal for every texture the map's load loads,
   the converter writing every texture's height; and `FLATCM` past the
   map's flats, which `levelFlats` leaves as the map before left them:
   compared on the map's flats, the converter's 0 past them.)
4. Every slot's 128 bytes and every tail: equal (implied by 1, reported
   separately with the counts of variant columns and tails).
5. The game form of each map lump against the release's lump; the
   upstream window model against the W dump's window banks, 0 differing
   bytes up to `W_COLSTART`; the column memory (`COLDIR`, the tables,
   every byte to the end of the column memory, and the zeroed bank
   after it) against the W dump.
6. In the same run, every other level source of the nine maps (the
   thirteen of `build/native/render/levels/src`: the nine tour sources,
   `title-e1m7`, `newgame-e1m1`, `lights-e1m1`, `m5demo-e1m7`, all taken
   in play): their static parts and every slot and tail equal the
   converter's, except the textures `inplay.json` lists and the slots it
   lists as reaching a hole's free part (1.2), each difference reported
   by name. A difference anywhere else fails the check. The other 40 W
   dumps (the other skills, the demos, `newgame`): item 5 on each.
   (stage A: items 1-5 on all 51 W dumps.)

Planted in a scratch copy for this check: a model without `moreColumns`
(item 1 fails on E1M7's `SW2COMM`), and one without the `MORE_BANKS`
test (item 1 fails on E1M3).

`levelconv.py` gains the side's sector in `LVMAP` byte 7 (1.3) first
(its format becomes `render-level 3`); milestones 7 and 8's tests rerun
to show nothing else moved.

### 5.4 The loader on a2vm

Two ways in:

- **Image runs** (checkpoints B and C): an a2vm image of the machine
  after the boot (every bank file's segments, the card images), with
  every byte the boot does not define poisoned (`$A5` or `$5A`, as
  milestones 5-8), plus E's pre-state written by the port writer through
  `native-level 1`; `ldriver.s` runs `nl_setup(map)` and an a2vm event
  snapshots every bank of 1.6's map and main memory; the write log
  (every storage, filtered by `llayout.py`'s allowed sets, as milestone 7
  [R `RENDER.md` 4.2]) shows no stray write; the mouse card's VBL
  interrupt is on.
- **Disk runs** (stage C): `LEVELS.hdv` boots under a2vm's MLI trap,
  loads the store, then for each map 1-9 in turn injects the `tour-sk2`
  E pre-state (from a file on the disk), runs `nl_setup`, and prints the
  CRC of the level window's banks and of the canonical image of the
  setup state (the native-layout bytes the manifest names), the load's
  VBL count and the memory API's STATUS counter. Expected values: the
  host's (from C_ref through the port writer) and a2vm's. This disk is
  the owner's card run at milestone 12.

**Acceptance 2** (`frame8.py` on loaded levels): `frame8.py` gets
`--levels loaded`: for each frame, the level of its level source's map
is not `levelconv.py`'s but one made from an image run's snapshot (the
level window's banks, the shared stores, the per-level W and masked
tables, read back into `level.img` form with the game layout's
`level.json`, `texmap.json`, `patchmap.json`), then the frame runs as
today (its state injected per frame from P0, so the level's dynamic
fields are the frame's). The comparison is as exact as today's; a frame
that differs only where it reads a slot its map's `inplay.json` lists
(1.2, computed by the model for every map, no map named in the check) is
reported under that slot's name as a known difference for the owner, any
other difference fails. The sets: `m5`, `newgame`, `title`, `tour`,
`lights` and all 533 `demo3` frames, the 710 captured frames [M: M8:
177 + 533], and the 19 synthetic frames whose level is their base
frame's map; both fills, 729 frames and 1,458 runs. Not in it, by name:
the 5 synthetic frames whose level was converted again with pokes
(`synth-flat`, `synth-flatsky`, `synth-flatv06`, `synth-flatv14`,
`synth-mwclose`, which have level sources of their own [M:
`levels/by-source.json`]; their levels are not the WAD's).

### 5.5 Flood depths (acceptance 3)

`level_check.py --flood`: for each map, from the native flood lists (2.3)
read back from the loaded window, the recursion depth of
`P_RecursiveSound` from every start sector with every two-sided line
open, visiting in the lists' order, with upstream's revisit rule (a
sector is entered again only with fewer sound blocks); and the bound: a
sector is entered at most twice (once with a block, once without), so
the depth is at most twice the sector count. Measured with `DOOM1.WAD`'s
lines and upstream's list order (2.3: the entries without
`ML_SOUNDBLOCK` in reverse line order, those with it in forward line
order) [M: F1, redone]:

| Map | Sectors | Worst depth, all open | Bound |
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

(The first version of this table used the opposite order for both
lists; with that order the same script gives 43, 91, 96, 32, 82, 85, 61,
41, 69, and `NATIVE.md` 6's E1M3 figure of 96 matches it, so that figure
becomes 93. The order changes the depth, so the check uses upstream's.) The native work stack
(milestone 10's iterative `P_RecursiveSound`, `NATIVE.md` 6) is sized
here: **512 entries of 3 bytes** (sector, sound blocks and the position
in its list), 1,536 B in the tic window's scratch, which holds the bound
of every E1 map; `MEMORY_MAP.md` 3.5's "about 600 B" becomes 1,536. (As
built in milestone 10, part `pspr`: 512 entries of 2 bytes, 1,024 B in
the flood's code group, since a level's sector is recovered from the
entry below it; `docs/game-parts/pspr.md` R7.) A
closed door can make the walk deeper than all-open (a shortcut removed),
which is why the stack holds the bound, not the measured depth.
Acceptance 3 passes when every map's bound and measured depth fit 512.

### 5.6 Timing and the report

`level_check.py --timing` on image runs with the `lprof` build (cost
phases: requests, `LINES`, `GROUP`, `FLOOD`, `CMAPS`, spawn, specials),
f121 and fastpath, each map; the boot from the disk run's VBL count.
Estimates now [A]: copies 60 ms (2.2); the static steps about 1-1.5 M
cycles; the spawn about 0.5 ms a thing (a node walk of 14-19 levels with
a far fetch each, the block walk, the records), at most 0.22 s for E1M6's 449
things; in all **0.2-0.4 s a map on f121**, upstream about 30 s
[M: `NATIVE.md` 7]. `build/native/levels/report.md` gives the load time
per map and phase for both profiles, the boot time, and 1.6's table with
the measured store size.

### 5.7 Unit tests and planted bugs

`tests/test_native_level_*.py`, skipping with a message when `build/`
lacks the WAD, the release, the setup dumps or a2vm:

- the converter: the transforms on hand-made lumps and on the nine maps
  against the release's lumps; the window model against a small
  synthetic store; `lstore.py` round trips;
- the comparison of 5.3 on two maps (the rest by `level_check.py`);
- the loader: two maps' image runs, the window against the converter;
- the setup: E1M1 and E1M7 at skills 2 and 4 and one reload, canonical
  equal; the wrap fix (3.4); the flood bound;
- the variant step: `LV_VARMAP` 0 after a boot, then two maps in a row
  and the same map twice, the stores against the converter's;
- planted bugs, each in a scratch copy and each caught by the check
  named: a tail of the patch store off by one byte (5.3 item 4), a
  composed column placed after its hole instead of in it (5.3 item 1),
  a box computed without upstream's overflow flip (`LINES`, window
  check), `halfSum` rounding toward zero (sound origins, acceptance 1;
  stage B: not observable, the operands are whole map units times 2^16
  or `INT32_MAX`, on which a shift and a division toward zero agree; the
  native plant is a logical shift, the sign lost),
  a line put twice into a sector whose back is its front (`GROUP`), the
  pool's lowest free slot (mobj identities), `P_Random` called after the
  tics instead of before (prndindex and tics), a thinker for a mobj with
  tics -1, a missing secret count, a stray store into `LVSEG` (write
  log), a variant column not restored when the next map loads (the
  window check of the second of two maps loaded in a row), `LV_VARMAP`
  not set by `VARIANTS` (the same check), a model without `moreColumns`
  or without its `MORE_BANKS` test (5.3 item 1), the flood lines walked
  first to last (the flood sequences: checkpoint B and acceptance 1), the
  block walk with y outer (sector node order, acceptance 1; stage C: a
  design error, no E1 setup can see it, "Stage C as built"), a thing put
  at the tail of its block's list instead of the head (block list order,
  acceptance 1), a light spawner that leaves the sector's `special`
  (acceptance 1), `poolTake` taking the lowest free bit of the highest
  non-empty word instead of the highest (mobj identities), a `TXBANK`
  entry pointing at the wrong block in the game layout and a wrong global
  `PHDR` index (the read-back of checkpoint B).

### 5.8 Resources

| Work | Runs | Time [A] | Output [A] |
| --- | --- | --- | --- |
| Setup captures (5.1) | 11 scripts × 2 | 50 min at 2 jobs | 410 MB |
| Converter, nine maps, both layouts | host | 5 min | 40 MB of store files and levels |
| `levelconv.py` on the nine W dumps; item 5 on the other 40 | host | 8 min | 15 MB |
| The game layout read back (checkpoint B) | host, from the image runs' snapshots | 3 min | 15 MB, deleted after the comparison |
| Image runs, checkpoint B and C (51 setups, both fills, both profiles for timing) | about 230 a2vm runs | 15 min at 2 jobs | reports; snapshots deleted after reading |
| `frame8.py --levels loaded` | 1,458 runs | 15 min at 2 jobs [M: about 0.6 s a run, `RENDER-MASKED.md` 4.5] | reports |
| Disk image and its a2vm runs | 2 profiles | 5 min | `LEVELS.hdv`, about 5 MB |
| **All** | | **about 1.5-2 hours at 2 jobs** | **under 0.8 GB** of `build/` |

## 6. Build stages

The task's split holds, with two adjustments the sources call for: the
setup captures move into stage A (the converter's check needs the setup
dumps), and the static derivations (`LINES`, `GROUP`, `FLOOD`, `CMAPS`)
move into stage B (the renderer reads their results: the subsector
sectors and the colormaps; the window check needs them).

### 6.1 Stage A: the converter

**Builds:** `wadconv.py`, `umodel.py` (with `moreColumns`, `makeT`'s
`MORE_BANKS` test and `W_ZeroBank`), `maplumps.py`, `lstore.py`,
`setupcap.py` (the E, R and W points; the generated tour scripts with
nightmare's `y` and the skill assertion), `llayout.py` (banks and
records, `GTAB`, `LVS`, `LV_VARMAP`; the manifest's static kinds);
`levelconv.py`'s byte 7 (`render-level 3`); `tests/
test_native_level_conv.py`.

**Interfaces:** the store files (1.7) and their directory; per map the
harness-layout level directory (`levelconv.py`'s files), the game
layout's expected window (`window.img`: every byte the loader must leave
in every bank of 1.6, with a mask of the bytes stage C writes), the game
layout's `texmap.json` and `patchmap.json` (for the read-back), and
`inplay.json` (1.2); `store.json` (each block's bank, address, length,
codec, the load program, and the apply and undo variant lists by map).

**Checkpoint A:** 5.3 items 1-6 against the W dumps (zero differences
but the named range in 1-5; in 6 only the slots `inplay.json` lists, by
name); the store's size and 1.6's table measured; `inplay.json` for all
nine maps (expected: E1M2 3 textures, E1M3 5, the others none; found:
E1M2 5, E1M3 5), each
map's list of slots that reach a free hole byte, or the statement that it
is empty; the setup captures of 5.1 made (51 setups, 49 W points; built:
53 and 51) and
every R and W dump read by the bridge with 0 problems, each W dump's
canonical state equal to its R dump's; `build/` growth reported.

### 6.2 Stage B: the boot load and the loader

**Builds:** `lboot.s`, `lload.s`, `lgeom.s`, `ldriver.s`, `level.cfg`,
`level.mk`; `ldisk.py`'s first version (the store only); `frame8.py
--levels loaded`; the manifest's static kinds read back;
`tests/test_native_level_load.py`.

**Checkpoint B:** for all nine maps, image runs from both poisoned
machines: the window equals `window.img` byte for byte outside the
stage-C mask (static and derived parts, the colormaps in main, `FUZZDARK`
in aux 0, the W and masked tables in the code banks, the shared stores
after the variants); the static canonical kinds (sectors' static fields,
lines, sides, subsectors, segs, nodes, blockmap, reject, line tables,
flood lists) equal C_ref's for the nine `tour-sk2` setups; the nine maps
loaded in a row and in reverse (variant restore through `LV_VARMAP`);
**after every load of those runs, the map's window read back into
harness `level.img` form through the game layout's `texmap.json` and
`patchmap.json`, every slot and tail equal byte for byte to
`levelconv.py`'s from the map's W dump** (exhaustive: the data is
finite; it catches a game-layout writer or load-program bug that no
captured frame draws); no stray write; the boot from `LEVELS.hdv` on
a2vm reaches the same window. **Acceptance 2:** `frame8.py --levels
loaded` passes on the 729 frames, 1,458 runs, as it passes today (every
output, every SHR byte, 0 stray writes, frames with `RULES` ≠ 0 named as
known divergences, and frames whose only difference is in a slot
`inplay.json` lists named as in 5.4).

### 6.3 Stage C: P_SetupLevel and the zone

**Builds:** the game core (`gspawn.s`, `gpos.s`, `gthink.s`, `gspec.s`,
`gweap.s`, `gvalid.s`), `lsetup.s`, the zone pools, the manifest's
dynamic kinds and the three encodings, `RTHING`'s 2,026 slots,
`ldisk.py`'s setup disk, `level_check.py --timing --flood --report`;
`tests/test_native_level_setup.py`; the renderer's wrap call (3.4).

**Acceptance 1:** the 51 setups of 5.1, both poisoned machines, C_nat
equal to C_ref with 5.2's exclusions only, 0 stray writes, the stack
within 128 B; each map's zone-mobj bound at its R dumps within 2,026 -
its `poolsize` (3.1); for the two reloads, the static level kinds and
the level window outside stage C's mask equal their maps' first loads'
(their canonical states
are compared with ref816's like every setup's). **Acceptance 3:** 5.5's table, every map within 512. **Report:** 5.6;
`MEMORY_MAP.md` gains a section 14 with every region this milestone
adds; `NATIVE.md` 4.4's table is not edited (this file's 1.6 answers
it). **The disk:** `LEVELS.hdv` runs end to end on a2vm under `f121` and
`fastpath`, CRCs equal to the host's; the owner runs it at milestone 12.

## 7. Risks and open points

| # | Risk | Effect | What the builders do |
| --: | --- | --- | --- |
| 1 | **The bank budget**: 118 of 126 with later milestones' budgets assumed (2D 6, tic code, `LOGTAB`, `GTAB`, `LVS`, mobjs 6) [A]; 8 spare, exactly the codec's threshold (stage A measured 112 used, 14 spare: no codec; stage C 109 used, 17 spare) | A later milestone has no room | Stage A measures the store; under 8 spare banks it adds the LZ codec (1.5, about 12 banks back [A]); the texel banks' slack takes store blocks first (1.6); the mobj game part can shrink to 64 B if milestone 10 splits hot fields into planes |
| 2 | **The column memory model**: holes, two passes, `W_NEXTBANK`, then `moreColumns` with its `MORE_BANKS` limit and the zeroed next bank [R `r_data65.s:1732-1860`; `w_level65.s:507-610`] | A composed column's tail differs | Exact comparison of every slot's address and bytes against the W dumps of nine maps, item 5 on 40 more, and the thirteen level sources (5.3); planted hole, `moreColumns` and `MORE_BANKS` bugs |
| 3 | **Textures made in play** (switch partners and slime frames past `MORE_BANKS`): upstream makes them at first sight, cold, into the holes first, then appended [R `r_seg65.s:505-516`; `r_data65.s:1750-1775`] | The bytes of a hole's free part, so the tails of the slots that reach it, follow a run-time order | Expected in E1M2 (3) and E1M3 (5) [M: V1], all 128 high; natively resident; `inplay.json` lists them and every slot that reaches a free hole byte at the end of the load, each a named known difference for the owner if the list is not empty (1.2) |
| 4 | **The game layouts are chosen before milestone 10** designs the game logic (3.2) | A layout change later | The manifest makes it one edit; the game core's interfaces take records by handle, not addresses |
| 5 | **Zone mobjs past 2,026 - `poolsize`** (at least 1,514; 1,910 on E1M1) | A native stop where upstream would run | The bound is upstream's own (its zone would `I_Error` first); stage C measures it at every R dump, free, `PU_CACHE` and level-special blocks counted as reclaimable, against each map's own room (3.1) |
| 6 | **Sector nodes past 2,048** | A native stop where upstream might run | Measured maximum 448 [R `tools/bridge/README.md:317-319`]; milestone 10 measures in play and resizes; open point for the owner if exactness is wanted there (upstream's limit is its zone's free space) |
| 7 | **The tails at the window's three edges** (`$3F`/`$40`, `$0F`/`$10`, `$69`/`$6A`) | A tail the model does not hold | The converter fails naming the lump; none reached in the captures [M: T1] |
| 8 | **Inputs from the release** (1.1) | The port's build needs upstream's release image as well as the WAD | It already does (ref816, `rtables.py`); stated in `src/native/README.md` |
| 9 | **The coverage of skills** is by generated tour scripts | A path of a skill not reached | Every skill flag and nightmare's reaction time are in the 45 tour setups; each script asserts its `_g_gameskill` (nightmare needs its `y`, 5.1); the coverage report lists `P_SpawnMapThing`'s branches taken |
| 10 | **Spawn time on F1.2.1** (a far fetch a BSP level per thing) | Loads of 0.2-0.4 s [A] | Any load time is acceptable (15.1 row 9); reported |
| 11 | **a2vm's costs are the model's** | The load and boot figures move on the card | The owner's card run at milestone 12 |
| 12 | **`MEMORY_MAP.md` and earlier designs changed here**: `RTHING` 768 → 2,026 slots; the side's sector in `LVMAP` byte 7 (`render-level 3`); the game bank map (1.6); the flood work stack 600 → 1,536 B; `NATIVE.md` 6's E1M3 flood depth 96 → 93 (5.5); the game core's zero page `$18-$37`; `LV_VARMAP` at main `$03A4`; the banks `GTAB` and `LVS`; the renderer's wrap call in release builds | Their owners accept them | Stage A updates `rlayout.py` and `MEMORY_MAP.md` and says so; milestones 7 and 8's tests rerun |

Open points for the owner: whether the release image may stay an input
of the port's build (risk 8; the alternative re-implements upstream's
layout search and palettes); the sector-node capacity (risk 6); the
slots stage A lists as reachable by textures made in play, if any (risk
3).

## Appendix A: upstream to native, by routine

| Upstream | Lines | Native | Stage |
| --- | --- | --- | --- |
| `W_LoadSet`, the store | `w_level65.s`; `levelimg.py:29-56` (format) | `umodel.py` (host), the boot, the load program | A, B |
| `I_SetLevelPalette` (colormaps), `levelFlats`, the fuzz table | `i_viigs65.s:955-1100` | `CMAPS`; `wadconv.py` | B, A |
| `P_SetupLevel` | `p_setup65.s:100-160` | `nl_setup` | C |
| `loadThings`, `poolInit` | `p_setup65.s:217-231`; `p_spawn65.s:1369-1375` | `nl_setup`, `gthink.s` | C |
| `loadLineDefs` | `p_setup65.s:259-404` | `LINES` | B |
| `loadSegs`, `I_InitSegVertices` | `p_setup65.s:414-428`; `i_viigs65.s:1900-1905` | `wadconv.py` | A |
| `loadBlockMap`, `P_InitBlockRows` | `p_setup65.s:432-462`; `p_map65.s:3301-3344` | copies, globals | B |
| `loadNodes`, `loadSectors`, `loadSideDefs`, `loadSubsectors`, reject | `p_setup65.s:465-474`, `:536-735` | `wadconv.py`, copies | A, B |
| `loadGrid`, `newPoint` | `p_setup65.s:479-530` | none (2.4) | |
| `R_MakeLevelColumns`, `R_MakeTextureColumns`, `colAllocL`, `colAllocH`, `cmPass1`, `cmPass2` | `r_data65.s:863-1197`, `:1732-1860` | `umodel.py` | A |
| `W_LevelDone`, `moreColumns`, `madeT`, `makeT`, `W_ZeroBank` | `w_level65.s:507-610`, `:1456-1480` | `umodel.py`; `AM_LevelCache`: milestone 11 | A |
| `P_LoadTexture`, `R_GetTexture` | `p_switch65.s:164`; `r_data65.s:205-237` | `wadconv.py` (every texture a level can show) | A |
| `groupLines`, `eachLine`, `lineToSector`, `sideSector`, `soundOrigins`, `halfSum`, `addToBox`, `boxCoord` | `p_setup65.s:742-1102` | `GROUP` | B |
| `rlInit`, `rlName`, `rlGridName`, `rlSightLogs`, `rlSightTables`, `rlGroup`, `rlSecs`, `rlSave*` | `p_setup65.s:1145-1462` | none (one path) | |
| `P_InitSightLogs`, `P_InitSightTables` | `p_sight65.s:1446-1712` | milestone 10 | |
| `P_InitFlood`, `fbOne` | `p_pspr65.s:1253-1380` | `FLOOD` | B |
| `P_SpawnMapThing`, `spawnPlayer` | `p_spawn65.s:913-1118` | `gs_mapthing`, `gs_player` | C |
| `G_PlayerReborn` | `g_game65.s:674-707` | `gs_reborn` | C |
| `P_SpawnMobj`, `newMobj`, `clearMo` | `p_spawn65.s:72-331` | `gs_mobj` | C |
| `poolTake`, `poolFree` | `p_spawn65.s:1249-1366` | `gthink.s` | C |
| `P_SetThingPosition`, `P_CreateSecNodeList` and its walk | `p_map65.s:748-` | `gp_setpos`, `gp_secnodes` | C |
| `R_PointInSubsector` | `r_iigs65.s:668-` | `gp_pointsub` | C |
| `P_InitThinkers`, `P_AddThinker` | `p_think65.s:29-44` | `gthink.s` | C |
| `P_SetupPsprites`, `bringUpWeapon`, `setPsprite`, `A_Raise` | `p_pspr65.s:1181-1193` | `gweap.s` | C |
| `P_SpawnSpecials`, `addScroller`, `P_SpawnLightFlash`, `P_SpawnStrobeFlash`, `P_SpawnGlowingLight` | `p_spec65.s:433-574`; `p_lights65.s:274-326` | `gspec.s` | C |
| `P_MapEnd` | `p_map65.s:3293-3298` | `nl_setup` | C |
| `Z_Init`, `Z_Malloc*`, `Z_FreeTags` | `z_zone65.s` | the pools (3.1) | C |

## Appendix B: the measurements made for this design

All read-only, 2026-10-01, standard-library Python under `nice -n 10`
through `tools/ref816/bounded.py` (limits 120-1,800 s and 4 MB of
output); the scripts lived in the session's scratch directory and were
deleted; nothing was written into `build/` (0 bytes added). Disk free
before: 74 GB (`df -h /System/Volumes/Data`).

**W1, the window rebuilt from the release.** `tools/v816/hdv.load` of
`build/release/doom-hd.hdv`, `level_store()`: base `$40:0000`, 1,821,696
bytes, 13 sets (0-8 the maps, 9 the title, 10 the intermission, 11 the
boot songs, 12 the common units). Each set's entries parsed as
`levelimg.py:29-41` documents (u16 lump or kind, u8 bank, u16 offset, u24
store address, u16 length); UNIT streams decoded with `tools/v816/b1.py`
(152 units, 2,134,580 bytes), FILL as zeros, the common set first, then
the map's set; song entries skipped. Compared with the nine tour level
sources (`build/native/render/levels/src/tour-e1m*.ram.z`), the window
banks taken from `LV_WIN` (`$00:8B58`) and `LV_NWIN` (`$00:8B98`): 38
banks, `$2A-$3F`, `$0E`, `$0F`, `$5C-$69`; every image bank (13, 18, 18,
18, 16, 17, 16, 13, 12 for E1M1-E1M9) compared up to `W_COLSTART`
(`$00:8B00`): **0 differing bytes**. Without the cut at `W_COLSTART` the
first difference of E1M2-E1M9 is at `W_COLSTART` itself, the column
memory (E1M1's line of that run was not kept). About 10 s.

**T1, the tail reads.** For each of the 734 frame directories of
`build/native/render/frames` with a P4 dump (and its `p2m-*` early
flushes), each column's list walked from `COLPAGE(c)` as
`levelconv.py`'s `overrun_of_frame` does; each `K_TEX`/`K_TEXC` record's
rows stepped by `p1_image`'s rule (even rows `Y += SI2 + C`; odd rows the
fraction `+= 2 SF`, `Y += SI + C`; an odd first row one fraction step
back; 7-bit `Y`), without the covered-range cut (so an upper bound in
rows, exact in positions); each read classified against the level
source's lump directory (`levelconv.wad_directory`), the column memory
(`W_COLSTART` to `colmem`) and the textures' heights through
`texmap.json`. Results in 1.2. 241 records lay in the column memory's
part after its wrap from bank `$3F` to `$0E` (E1M2, E1M3), which the
script's range test missed; the ones printed are of textures 128 high,
which cannot read past their column; stage A's check covers them
exactly. About 4 min.

**S1, sharing across maps.** The nine tour levels' `level.img` and
`level.json`: each texture's slot block, each stored lump with its tail
(1.4); first-fit-decreasing packing into 48,640-byte banks: texel blocks
30 banks (173,056 B slack), patch store 17 banks (12,912 B slack); block
widths 8 to 256 columns. Banks 6, 7, 48, 49 per level: `LVSEG` 14,062 to
44,686 bytes of extent; `LVMAP` 44,800 (fixed bases); `SPRT` 37,244 to
37,412; `WPRO` 28,072 in every level. About 30 s.

**Z1, upstream's zone.** `tools/bridge/upstream.Reader.walk_zone` on the
nine tour level sources: free bytes 201,184 (E1M1), 141,648, 127,728,
160,720, 157,952, 91,776 (E1M6), 136,768, 200,912, 172,784 (E1M9);
blocks by tag: static 7,216, level 53,296-162,576, level-special
192-1,248; `_g_thingPoolSize` 116, 242, 368, 241, 260, 449, 337, 114,
223; free / 136 = 1,479, 1,041, 939, 1,181, 1,161, 674, 1,005, 1,477,
1,270. These are minutes into each map, not at the end of setup, so they
are indicative only: the zone has more free bytes at the end of setup
(3.1), and a mobj's block is 144 B, so / 136 overcounts; stage C
measures at the R dumps against 2,026 - `poolsize`. About 20 s.

**F1, flood depths (redone in the revision).** `DOOM1.WAD`'s `LINEDEFS`,
`SIDEDEFS`, `SECTORS` of each map; per sector the other sectors of its
two-sided lines (`ML_TWOSIDED`, a back side, front and back differ), the
back into the front's list then the front into the back's, lines walked
from the last to the first as `P_InitFlood` does, so the entries without
`ML_SOUNDBLOCK` in reverse line order and those with it in forward line
order (`p_pspr65.s:1300-1374`); a depth-first walk from every sector
with upstream's revisit rule (`recursiveSound`, `p_pspr65.s:440-535`:
entered again only with fewer blocks; the `ML_SOUNDBLOCK` part only when
the sector was entered with 0 blocks, its entries with 1), all lines
open. Results in 5.5. The first version used the opposite order for
both lists; the same script with that order reproduces its numbers
exactly (43, 91, 96, 32, 82, 85, 61, 41, 69), which checks the script.
Under 5 s.

**V1, textures in the level sources against the sides (the revision).**
For each tour level of `build/native/render/levels` (`by-source.json`):
the textures of `level.json`'s `converted` against the names on
`DOOM1.WAD`'s `SIDEDEFS` of the map, with `TEXTURE1`'s sizes, and the
window index of `colmem` in `LV_WIN`'s order. Converted but on no side
(all switch partners or slime frames): E1M1 `SW2STRTN`; E1M2 `SW2COMP`;
E1M4 `SLADRIP1`, `SLADRIP2`, `SW1BROWN`, `SW2DIRT`, `SW2METAL`,
`SW2SLAD`; E1M5 `SW2BRNGN`, `SW2COMP`, `SW2STON1`, `SW2STONE`; E1M6
`SW1BROWN`, `SW2BRN1`, `SW2BRN2`, `SW2BRNGN`, `SW2COMP`; E1M7 `SW2COMM`
(64 × 72, 2 patches), `SW2COMP`, `SW2METAL`, `SW2SLAD`; E1M8 `SW2BRCOM`,
`SW2BRNGN`, `SW2STON1`, `SW2STON2`; E1M9 `SW2BRCOM`, `SW2BRNGN`. Switches
on sides whose partner is absent: E1M2 3 (`SW1PIPE`, `SW1SLAD`,
`SW1STON1`; `colmem` `$0E:2780`, index 22), E1M3 5 (`SW1BRCOM`,
`SW1BRNGN`, `SW1COMP`, `SW1DIRT`, `SW1STONE`; `$0E:F800`, index 22); the
others none (indexes 12-21). The eight absent partners are 128 high.
Under 5 s.

The revision's two scripts ran under `nice -n 10` (F1 through
`bounded.py`, 300 s and 1 MB of output; V1 directly, a few seconds and a
dozen lines), lived in the session's scratch directory and were deleted;
0 bytes were added to `build/`.

**R1, `DOOM1.WAD`.** Map lumps per map 55,714 (E1M1), 114,474, 111,205,
87,544, 89,313, 152,021 (E1M6), 105,513, 57,241, 75,124 bytes (E1M8's
`BLOCKMAP` 19,400); sprites 483 lumps, 825,576 bytes; wall patches 165
lumps, 763,612 bytes; flats 54, 221,184 bytes; the file 4,196,020 bytes.

## Review

A review of the first version (2026-10-01) made eleven findings. Each was
checked against upstream's source, the level sources and the WAD before
it was applied. None was rejected; where the review left the fix open,
or the evidence called for more than it said, the choice made is noted.

| # | Finding | Verdict | Checked against | Applied as |
| --: | --- | --- | --- | --- |
| 1 | HIGH: the load ends at `W_LevelDone`, not `P_SetupLevel`; its `moreColumns` and `W_ZeroBank` change the column memory | Applied | `m_menu65.s:1780-1791`, `w_level65.s:507-610`, `:1456`; V1 (E1M7's four `SW2` partners, `SW2COMM` 72 high) | Fact 10; 0.1 row; `umodel.py` models `moreColumns`, `MORE_BANKS`, `W_ZeroBank` (1.2); a W dump at `W_LevelDone`'s `jmp bmSignOff` for new maps, R kept for the game state, W's canonical state checked equal to R's (5.1); 5.3 on the W dumps with item 6 in the same check (5.3); planted bugs. A same-map reload has no `W_LevelDone` (`bmLoad`'s other path), so it has no W point |
| 2 | MEDIUM: textures are made in play in E1 | Applied | V1: E1M2 3, E1M3 5 partners absent, `colmem` at window index 22; all eight 128 high; `r_data65.s:1750-1775` | 1.2 rewritten: natively resident, `inplay.json` with the slots that reach a free hole byte at the end of the load (empty with proof, or named known differences); the `RL_ON` note; risk 3; checkpoint A expects E1M2 3, E1M3 5 |
| 3 | MEDIUM: the zone-mobj limit is 2,026 - `poolsize`, and the bound must be taken at setup end | Applied | 3.1's own slot rule; `p_map65.s:2131`, `offsets.inc:295` (848 B a node pool); `z_zone65.s:273` (16-B rounding) | 3.1, risk 5, Z1's note, acceptance 1. The claim that the bound "can pass 1,514" at the R dumps is plausible, not measured; the fix does not depend on it |
| 4 | MEDIUM: the flood lists' order was reversed | Applied | `p_pspr65.s:1300-1303`, `:1361-1374`; F1 redone (52, 93, 93, 23, 85, 87, 61, 52, 72; the old script's numbers reproduced with the old order) | 2.3, 5.5's table, F1, the planted forward walk; `NATIVE.md` 6's 96 → 93 in risk 12. Every map stays far within 512 |
| 5 | MEDIUM: the game layout was never compared with `levelconv.py` | Applied | 6.2 compared only with the converter's own `window.img` | Checkpoint B reads every loaded window back into harness form and compares every slot and tail with `levelconv.py`'s from the W dump; planted `TXBANK` and `PHDR` bugs |
| 6 | MEDIUM-LOW: the variant restore had no state | Applied, the first option | `MEMORY_MAP.md` 3.1: `$0300-$03EF` persistent and zeroed at start | `LV_VARMAP` at main `$03A4` (0: canonical) and the `VARIANTS` step (1.4, 2.2); the 44 KB union restore was not chosen (it copies more for nothing) |
| 7 | MEDIUM-LOW: nightmare's confirmation would hang the tour script | Applied | `m_menu65.s:794-807`, `:917-921`, `:994-998`; `m_cheat65.s` has no skill test, so the cheats still work | The generator presses `y` for skill 4; every script asserts `_g_gameskill` |
| 8 | LOW-MEDIUM: the sector-node walk was under-specified | Applied | `p_map65.s:1684-1880`, `:2560-2583`; `p_lights65.s` (`takeSector`, the strobe and glow spawners) | The walk's rules (2.4); the thing's sector from the subsector record; `special = 0` (2.5); four planted bugs. The "lowest-bit `poolTake`" bug is kept beside the existing "lowest free slot" one: it is a different error (the bit within the highest non-empty word) |
| 9 | LOW: the reloads cannot equal the first loads' canonical state | Applied | `prndindex`, `validcount`, stamps and the reborn player differ by construction | Fact 7, 2.1, 5.1, acceptance 1: static kinds and the window outside stage C's mask are compared with the first load; the canonical state with ref816's |
| 10 | LOW: the store left out the rest of `GSVIEWn` | Applied | `i_viigs65.s:83-85`, `:874-880`, `:1040-1050` | The whole record is stored and copied to `LVC` (0.1, 1.1, 1.3, 2.1, 2.2) |
| 11 | LOW: smaller points | Applied | as listed | The node stack dropped (4.2, 4.3: the descent never backtracks); `P_FindDoomedNum` only for things that spawn, never type 1 (1.3, `p_spawn65.s:924-962`); the game tables placed in a bank `GTAB` (99); `LVC` keeps the colormaps and `GSVIEWn`, and milestone 10's sight tables get a bank `LVS` (111) since upstream's reach `$C000` plus 2 B a line (`p_sight65.s:82-102`); 118 of 126 used, 8 spare (1.6, 1.5, risk 1). The "checked and correct" items need no change |

## Stage A as built (2026-10-01)

Stage A of section 6.1 is built, on the host (no 65C02 code: the
loader's steps are stage B's). Tools, all in `tools/native/`:

| File | What it is |
| --- | --- |
| `maplumps.py` | Our transforms of `DOOM1.WAD`'s map lumps, `TEXTURE1` and `PNAMES` to the game's form (1.1), the flat numbering paired with the release's `SECTORS` (one to one, the sky -2) |
| `umodel.py` | The release's reader (its directory, the level store's sets, entries and units through `tools/v816/hdv.py` and `b1.py`), the 8 MB machine's window (`LV_WIN`, `W_NEXTBANK`, the picture sets kept at its end), each map's image from the lumps at the set's addresses (checked equal to the decoded units), the column memory (`R_MakeLevelColumns`' two passes, `R_MakeTextureColumns`, `colAlloc`'s holes, `MORE_BANKS`, `W_ZeroBank` and `LV_ZB`), with a mask of the bytes the model knows |
| `wadconv.py` | The converter: `--layout harness` (`levelconv.py`'s files, format `render-level 3`, and `inplay.json`) and `--store` (`lstore.py`) |
| `lstore.py` | The store: the shared texel and patch stores (canonical bytes, the variants), `PHDR` and `WPRO` global, each map's level part, header and load program (memory-API requests and steps), the bank files, `store.json`, each map's `window.img`, `mask.img`, game `texmap.json` and `patchmap.json`; and its reader, `HostMachine`: the bank files loaded, then a map's load as stage B must make it (the variants, every request with a2vm's validation, the static steps from the store's bytes) |
| `lderive.py` | The static steps on the host (2.3: `LINES`, `GROUP`, `FLOOD`), the bytes `window.img` holds for them, checked against ref816's canonical state |
| `llayout.py` | The game bank map (1.6 as measured), `LVG0`, `LVG1`, `LVG2`, `LVC`, `GTAB`, the map things, the store's constants, `LV_VARMAP` (main `$03A4`) and the level's other counts (main `$03A6-$03AD`), the manifest `native-level-1` of the static fields |
| `setupcap.py` | The setup captures of 5.1 and `--check` (the bridge on every R and W dump) |
| `level_check.py` | `--conv` (5.3), `--derive`, `--store` |

`levelconv.py` writes the side's sector in byte 7 of its record (format
`render-level 3`, `rlayout.SIDE['SECTOR']`); the eighteen level sources
were converted again (the same keys: the sides are not in the key) and
`--overrun` measured again (unchanged).

Tests: `tests/test_native_level_conv.py`, 39 tests: without `build/` the
transforms on hand-made lumps, the allocator on a synthetic window, the
derivations' rules, the store format and the memory-API rules, the
scripts, the bank map; with the release the nine maps' lumps and images;
with the captures items 1-6 on E1M1 and E1M7, the derivations, the store
loaded on the host and read back, and the planted bugs below.

### Commands

    python3 tools/native/setupcap.py               # 11 runs, about 40 s at 2 jobs
    python3 tools/native/setupcap.py --check       # the bridge on every R and W dump
    python3 tools/native/wadconv.py                # harness levels, build/native/levels/conv/
    python3 tools/native/wadconv.py --store        # the store, build/native/levels/store/ (5 s)
    python3 tools/native/level_check.py --conv     # 5.3 items 1-6 (26 s)
    python3 tools/native/level_check.py --derive   # the static steps against the R dumps (8 s)
    python3 tools/native/level_check.py --store    # the store loaded on the host, read back (3 s)

### Checkpoint A

| Item | Result |
| --- | --- |
| Setup captures (5.1) | 11 runs, each twice (marks, then dumps; the second run's RAM and marks equal the first's): **53 setups, 51 W points** (the design's 51 and 49, plus the first loads of the two reloads' maps, kept as their comparands): the five skill tours (45, each script checks `_g_gameskill`; nightmare's message answered `y`), the three demos (E1M5, E1M3, E1M7), `reborn-e1m1` and `reborn-e1m6` (each map's first load and its reload, no W), `newgame`. **`setupcap.py --check`: 0 bridge problems in all 104 R and W dumps, every W dump's canonical state equal to its R dump's** |
| 5.3 items 1-5 | **All 51 W dumps** (the design: items 1-4 on the nine `tour-sk2` dumps, item 5 on the others): `level.img` byte for byte in every bank (1.19-1.47 MB a map) but the named range; `level.json` equal but the provenance fields; `texmap.json`, `patchmap.json`, `mtables.img`, `fuzzdark.bin` byte for byte; `wtables.img` byte for byte but `TXHT`'s and `FLATCM`'s history (below); every slot and every stored lump with its tail (1,896-5,736 slots, 245-327 lumps a map); the window model against the dump: the image banks to `W_COLSTART` (0.77-1.15 MB), the column memory with `COLDIR` (69-353 KB), the rest of `colmem`'s bank and the zeroed bank after it; each map's nine game lumps equal the release's (umodel.py's image check: every unit byte) |
| 5.3 item 6 | **The 13 level sources** (taken in play): static parts and every slot and tail equal; the five synthetic sources (`synth-*`, levels made with pokes) by name, not compared. No source holds a texture made in play: each was taken before any (`R_MakeTextureColumns` counts) |
| `inplay.json` | E1M2: `SLADRIP1`, `SLADRIP3`, `SW2PIPE`, `SW2SLAD`, `SW2STON1` (5, not the design's 3); E1M3: `SW2BRCOM`, `SW2BRNGN`, `SW2COMP`, `SW2DIRT`, `SW2STONE` (5); the others none. All ten are 128 high. **No slot's and no stored lump's bytes reach a free byte** (a hole's free part, or `colmem` to its bank's end) on E1M2 or E1M3: their lists are empty, with that proof; E1M4, E1M5 and E1M7 have slots that reach `colmem` (1, 5, 1) but make nothing in play. So no known difference is left for the owner |
| The store and 1.6 | Measured: below. `level_check.py --store`: the nine maps in a row, in reverse and E1M5 twice (20 loads) on `HostMachine`: after every load the machine equals `window.img` outside `mask.img` (97-201 KB a map), read back into harness form it equals `levelconv.py`'s level of the map's `tour-sk2` W dump (every slot, every lump and tail, `PHDR`, `SPRFR`, `TXMP`, the TX tables), and the 16,076-56,459 static fields the manifest names, read by the bridge's port reader, equal the R dump's canonical state |
| Derivations | `level_check.py --derive`: on all 53 R dumps (the reloads too) the lines (every field but the stamps), the subsectors' sectors, every sector's line count and table (the bridge's `linebuf` entries), sound origin, tag and old special, and both flood sequences equal; no sector at an address whose low word is 0 (`levelconv.py`'s `CN_LSEC` check, which the WAD converter cannot make) |
| `build/` growth | 0.43 GB: the setup captures 399 MB (R and W dumps of 3.8 MB compressed), `conv` 12 MB, `ref` 12 MB, `store` 5.7 MB (3.4 GB after, 3.0 before) |

### The store as measured (1.3, 1.6)

| Part | Built | Design |
| --- | ---: | ---: |
| Texel store | 116 blocks (the 115 textures some map makes at its load or in play, and the sky), 1,302,528 B, **31 banks** (205,312 B slack before the level parts, 2,142 after) | 115 blocks, 1,286,144 B, 30 banks |
| Patch store | 410 lumps, 761,488 B and 52,480 B of tails: 813,968 B, 17 banks | the same |
| Variants | 223 columns and 131 tails over the nine maps (8 to 53 a map), each in the map's apply and undo lists | 219 and 125 (the in-play textures and the sky add) |
| Level parts | 869,984 B with the variant lists and their requests, the headers and the programs (E1M6 145,672 B): 203 KB in the texel banks' slack, the rest in **14** `STORE` banks | about 1.0 MB, 21 banks |
| `GTAB` | 17,518 B | about 17.5 KB |
| Bank files | `TEXELS.1` 1,302,784 B, `PATCHES.1` 848,873 (with `PHDR` and `WPRO`), `MAPS.1` 870,292, `TABLES.1` 17,518: 3.04 MB | about 3.5 MB in five files (`CODE` is stage C's) |
| Banks | **112 of 126 used, 14 spare** (1-5, 91-97, 125, 126) | 118, 8 spare |
| Load program | 11 or 12 steps; `VARIANTS` (the undo list's and the apply list's COPY requests, 16 descriptors of 128 B at most a request: 1-4 requests each), 2-3 `COPYREQ` requests (48-113 KB of data with the fills) and one `PRIVREQ` (the counts, the colormaps in four parts, `FUZZDARK`: 17,932 B) | about 234 KB of copies a map |
| Level window | `LVG0` up to 43,264 B (E1M6), `LVG1` to `$4ADD`, `LVG2` up to 18,775 B, `LVC` 18,880 B | within a bank each |

### What stage A changed, and why

| Design | As built | Why |
| --- | --- | --- |
| E1M2 makes 3 textures in play (V1) | 5: the three switch partners and the slime frames `SLADRIP1`, `SLADRIP3` | `moreColumns` makes the slime after the switches and stops at `MORE_BANKS` too; V1 looked at switches only (0, 1.2, fact 10 and checkpoint A corrected) |
| Item 1's named range: the sector thing list heads | The rotate and flipmask bytes of a frame both sides flag as not a frame (`SPRFR_BAD`: sprite 1 frame 4) | `levelconv.py` writes `$FFFF` heads too; the flagged frame's two bytes are upstream's memory after the sprite's frames (its zone), which no renderer reads (`ST_SPRFRAME`); the converter writes 0 |
| Item 3: `wtables.img` byte for byte | `TXHT` and `FLATCM` hold upstream's history, named | `textureheight` is never cleared (every texture since the boot: on the tour's E1M8, 117 entries for 27 textures) and `levelFlats` writes only the map's flats; the converter writes every texture's height (`TEXTURE1`'s) and 0 past the flats; the rule (5.3 item 3) holds on every dump. No renderer reads a texture's height outside the map's textures and their translations, nor a flat past the map's |
| Items 1-4 on nine dumps, item 5 on 40 | Items 1-5 on all 51 | Each comparison takes under a second |
| 51 setups, 49 W points | 53 and 51 | The reborn runs keep their map's first load: the comparand of the reload's static kinds (2.1) |
| W at `bmSignOff`'s entry | At W_LevelDone's `JML bmSignOff` (found by its bytes) | The same state, and it fires once a W_LevelDone; `bmSignOff` is called from elsewhere too |
| 30 texel banks, 8 spare (1.6) | 31 texel banks (9-31, 56-63), 14 level-part banks (77-90), 14 spare | Measured: the blocks need 31 banks (a 32 KB block leaves 15,872 B, a 16 KB pair the same, and 51 blocks of 8 KB need six more banks; S1's 115 blocks had 50 of 8 KB: the 116th is the one texture no map makes at its load, made only in play, which natively must be resident); the level parts are smaller than estimated and fill the texel banks' slack first. No codec (1.5) |
| `upstream_vertex` from `I_InitSegVertices`' hash | Identity | The hash only finds a point; its numbers are given in order of first appearance (`i_viigs65.s:1975-2025`), as `native_vertices` numbers |
| No host model of the static steps | `lderive.py` and `HostMachine` | `window.img` needs their bytes; checking them against the R dumps now, and the store's load and read-back on the host, leaves stage B the 65C02 to match a known-good reference |
| The manifest's static kinds (`llayout.py`) | `native-level-1`: the int fields of segs, nodes, subsectors, lines, sides and sectors with strides, the counts at main `$03A0-$03A3` and `$03A6-$03AD` (the load copies them from the header) | The references (a byte sector, the line tables, the flood pool) need the encodings 3.3 gives stage C; `lderive.py` and `HostMachine` check them meanwhile |
| The level part's map things | 8 bytes: x, y, angle / 45, options, the mobj type (`P_FindDoomedNum`'s; `$FE` the player's start, `$FF` a thing no skill spawns) | 1.3's record |
| `window.img`: every byte of every bank of 1.6 | The level window's banks, main's counts, colormaps and `LV_VARMAP`, aux 0's `FUZZDARK`, and the store bytes the map's variants change | The rest of the stores is the bank files' (the load changes nothing else there); a stage B check loads the bank files, then the map, then compares |

### Planted bugs (5.7), each in a scratch copy and caught

In `tests/test_native_level_conv.py` (copies of the modules in a
temporary directory): a stored lump's tail read one byte on (item 1: bank
32 differs, lump `CHGGA0`'s tail); a cold block placed after its hole
instead of in it (item 1: E1M7 texture 87's column 46); a model without
`moreColumns` (item 1 on E1M7: the textures differ); without
`MORE_BANKS` (item 1 on E1M3: a 59th texture); the flood lines walked
first to last and a line put twice into a sector that is both its sides
(the derivations against the R dump); a box without the overflow flip
and `halfSum` rounding toward zero (the rules' unit tests: no E1 line
spans more than 32,767 units, and every sound origin's halves are even,
so no dump can show these two); a blockmap without its shared suffixes
(the game lump against the release's); the variants not undone and
`LV_VARMAP` not set (the host loads E1M1, E1M7, E1M1: the second E1M1
differs); a `TXBANK` entry one column off and the global `PHDR` indexes
one off (the read-back). Also in a scratch tree, `level_check.py --derive`
with the flood walked forward (6 of 6 R dumps of E1M7 fail) and
`--conv` without `MORE_BANKS` (all 7 E1M3 comparisons fail).

### Open points of stage A

- **The renderer's frame checks were not run on the converter's levels**:
  that is acceptance 2 (stage B, `frame8.py --levels loaded`). Stage A
  shows the harness levels equal `levelconv.py`'s byte for byte but the
  named history (`TXHT`, `FLATCM`, one frame's two bytes), which no frame
  reads.
- **`window.img`'s static steps come from `lderive.py`**, checked against
  the R dumps and through `HostMachine`; stage B's 65C02 `LINES`, `GROUP`,
  `FLOOD` and `CMAPS` must leave the same bytes.
- **The manifest's references** (side and subsector sectors, line
  tables, flood lists) are not yet expressible: stage C's encodings.
- **The release stays an input** of the port's build (risk 8): the
  placement, `GSVIEWn`, `GSFLATn`, the flat numbering, the directory's
  order, `CM_COLD` and the constant tables.
Milestones 7 and 8 rerun with the `render-level 3` levels: `python3 -m
unittest discover -s tests` 1,328 tests OK (1,289 before and stage A's
39); `frame8.py` on milestone 7's 188 frames and the 13 synthetic ones,
both fills: 402 of 402 runs equal, 0 known divergences;
`levelconv.py --overrun` unchanged.

## Stage B as built (2026-10-01)

Stage B of section 6.2 is built, on a2vm (the card runs wait for
milestone 12). The 65C02 loader runs each map's load program from the
store: the variants, the memory-API requests, `LINES`, `GROUP`, `FLOOD`
and `CMAPS` (`SPAWN` and `SPECIALS` are stage C's and do nothing yet).

| File | What it is |
| --- | --- |
| `src/native/lload.s` | `nl_load(m)`: the store's directory (fixed at STORE0 `$0200`), the map's header and program, each step dispatched; `VARIANTS` (the undo list of `LV_VARMAP`'s map, this map's apply list, `LV_VARMAP`); `COPYREQ` and `PRIVREQ` (the request's descriptors fetched into W `$A000` behind the 20-byte SmartPort and `AMEM` header, sent through slot 7's FIFO with interrupts masked); the stops (`LV_STATUS`, `BRK`) |
| `src/native/lgeom.s` | `LINES`, `GROUP` (subsector sectors, line tables, sector records with the sound origins), `FLOOD`, `CMAPS`, as `lderive.py` and `HostMachine` define them, through `far_get` and `far_put` |
| `src/native/ldriver.s` | The a2vm test driver (card `$E000`): the VBL interrupt, the load image into W by `far_pload` from `LCODE`, `nl_load` of each map of a list, `drv_loaded` after each |
| `src/native/lboot.s` | `LEVELS.SYSTEM`: the 126-bank probe, `CATALOG`, each bank file's segments through the MLI into their banks, the persistent globals 0, the card image; the runner: the mouse card, the memory API's probe, the load image, the catalog's maps loaded in turn with their VBLs, a table at the end |
| `src/native/level.cfg`, `level.mk` | The link (W `$6000` `MATHW`, `AUXW`; `$6600-$9FFF` the load code; the card as the render builds'): `ltest`, `lprof` (cost phases), `lcard` (the disk). `lgame` is stage C's |
| `tools/native/lrun.py` | The image runs (the machine after the boot, poisoned `$A5` or `$5A`), the narrowed write log and the stray check, the whole-machine diff, `SnapMachine`, `harness_level` (a loaded machine read back into a levelconv.py directory's layout), `loaded_level_hook` for `frame8.py`, `--sizes` |
| `tools/native/ldisk.py` | `LEVELS.hdv` (the store's bank files, `CODE.1` with the load image, `CATALOG`, `LEVELS.SYSTEM`) and `--check` on a2vm |
| `tools/native/level_check.py` | `--load` (checkpoint B) and `--load-timing` |
| `tools/native/frame8.py`, `framestate.py` | `--levels loaded` (acceptance 2), through `framestate.LEVEL_HOOK` |
| `tools/native/llayout.py` | The load's W, zero page, stop codes, header and program offsets, `llayout.inc`, `allowed_writes_load` |
| `tools/native/lstore.py` | The directory at its fixed place (the store rebuilt: only the directory and STORE0's blocks moved) |
| `tests/test_native_level_load.py` | 21 tests, below |

### Commands

    python3 tools/native/wadconv.py --store         # the store (directory at STORE0 $0200)
    make -C src/native -f level.mk                  # ltest, lprof, lcard
    python3 tools/native/lrun.py --sizes
    python3 tools/native/level_check.py --load      # checkpoint B (about 15 s)
    python3 tools/native/level_check.py --load-timing
    python3 tools/native/ldisk.py --check           # LEVELS.hdv on a2vm, f121 and fastpath
    python3 tools/native/frame8.py --levels loaded --sets m7,demo3 --json build/native/levels/frame8-loaded.json
    python3 -m unittest discover -s tests -p 'test_native_level_load.py'

### Checkpoint B

| Item | Result |
| --- | --- |
| The window | Two image runs, from the `$A5` and the `$5A` machines, each of 20 loads: the nine maps in a row, in reverse, E1M5 twice (`LV_VARMAP` restored each time). After **every** load the machine equals the map's `window.img` outside `mask.img`: 97,073 (E1M8) to 200,974 (E1M6) bytes a map (the level window, main's counts and colormaps, aux 0's `FUZZDARK`, the W and masked tables in banks 112 and 113, the stores' variant places); `LV_VARMAP` = the map |
| Read back, against levelconv.py | `lstore.readback` against the map's `tour-sk2` W dump's level: every slot (1,896-5,736), every stored lump and its tail (245-327), `PHDR`, `SPRFR`, `TXMP`, the TX tables: equal |
| The whole level in harness form | `harness_level` against `wadconv.py`'s harness level of the map: `level.img` (925,620-1,399,011 bytes), `wtables.img`, `mtables.img`, `fuzzdark.bin` byte for byte, no named range needed (both are the converter's: the three named parts of stage A are between it and levelconv.py) |
| Canonical static kinds | The manifest `native-level-1`'s static fields (16,076-56,459 a map) equal the `tour-sk2` R dump's canonical state; the derived parts read from the machine (each subsector's sector, each sector's line count, line table, sound origin, tag, old special and both flood sequences: 507-1,719 table entries, 334-734 flood entries a map) equal it too (`derived_check`) |
| Stray writes | The write log (every storage but the stack page and the load's bulk regions, all I/O but the far layer's soft switches; 51,511 lines a run) holds no write outside the load's allowed set (`llayout.allowed_writes_load`) or the driver's; a second run of the same 20 loads ends with a whole-machine snapshot: 0 bytes of main or any of the 128 banks changed outside the loaded maps' `window.img`, the load's scratch and the driver's, and the card only in the driver's count (the memory API's copies, which the log cannot see) |
| Stack, interrupts | 13 B below the driver's S (+24 for the IRQ: 37 of 128); 6,270 VBL interrupts a run, each within the IRQ contract (`--irq-bounds`) |
| The boot | `LEVELS.hdv` (3.0 MB: `TEXELS.1`, `PATCHES.1`, `MAPS.1`, `TABLES.1`, `CODE.1`) boots on a2vm under its MLI trap with the memory API, `f121` and `fastpath`: after the first load every byte of every bank file is in its bank but those the map's window changes (3,042,858 bytes), and after each of the 20 loads the window equals `window.img`. Boot 1,139 ms (`f121`), 848 ms (`fastpath`) of model time |

**Acceptance 2** (`frame8.py --levels loaded --sets m7,demo3`): **729
frames, 1,458 runs, all equal**, 0 failed, 0 known divergences (no
frame takes a rule of our own), 877,168 records and 8,710 clip-log calls
compared, every SHR byte; the staging margin as milestone 8's (11.9
times). Excluded by name, the five synthetic frames whose level source
was made with pokes: `synth-flat`, `synth-flatsky`, `synth-flatv06`,
`synth-flatv14`, `synth-mwclose`. Each frame's level was its source's
levelconv.py layout filled from the natively loaded window (the last
load of the map in the `$A5` run: after the reverse pass's variant
undo); no frame differed in a slot `inplay.json` lists (the lists are
empty, stage A). The run used the loads of an earlier build of
`lgeom.s` (the same steps, before a size pass); the final build's loads
read back into the same ten level directories are byte for byte the
same files.

### Sizes (4.4) and timing

| Module | Bytes | Budget |
| --- | ---: | ---: |
| `lload.s` with the transport | 929 | 1,200 |
| `lgeom.s` | 2,059 | 2,000 |
| Both | 2,988 | 3,200 |

`lgeom.s` is 59 B (3%) over its estimate, the two within theirs; W's
load code ends at `$71AB`, 11,860 B of `$6600-$9FFF` left for stage C
(its estimate 6,500). The card is unchanged.

The load of each map alone, `lprof` (`level_check.py --load-timing`; the
model's figures, not the card's), ms:

| Map | `f121` | `fastpath` | of which `GROUP` (`f121`) |
| --- | ---: | ---: | ---: |
| E1M1 | 117.3 | 67.1 | 43.2 |
| E1M2 | 216.5 | 120.8 | 89.1 |
| E1M3 | 214.7 | 119.7 | 88.3 |
| E1M4 | 176.4 | 99.4 | 70.0 |
| E1M5 | 179.1 | 100.4 | 71.1 |
| E1M6 | 274.7 | 151.8 | 116.2 |
| E1M7 | 203.2 | 113.5 | 83.4 |
| E1M8 | 101.0 | 57.6 | 33.7 |
| E1M9 | 153.6 | 87.0 | 60.0 |

On `f121` the copies take 13-30 ms, `LINES` 15-59, `FLOOD` 14-43, `CMAPS`
16.8, the PRIVATE request 6.1, the variants 0.6-3.2; the static steps are
far-access bound (a `far_get` or `far_put` per record or entry). The
disk's VBL counts agree: E1M6 14 VBLs at 50 Hz on `f121`, 8 on
`fastpath`.

### What stage B changed, and why

| Design | As built | Why |
| --- | --- | --- |
| The directory "STORE0's first bytes" (`lstore.py`'s comment) | At STORE0 `$0200` (`llayout.STORE_DIR`); stage A placed it at the first free place of the texel slack (bank 9 `$BE00`) | The loader needs a fixed entry; the store rebuilt (the directory and STORE0's blocks moved), `level_check.py --store` again: 20 loads, 0 failures |
| 4.3: the load's zero page `$38-$41`, `$48-$AF` | `$38-$41` (`LP_*`), `$48-$74` (`AM_*`, `LG_*`) | As planned, 45 of 104 B of overlay 2 |
| A stop "with its name" | `LV_STATUS` main `$03AE` (and `LV_AMEM` `$03AF`, the memory API's result), then `BRK`, the renderer's rule | Codes: the directory, the map, a codec, the program, the memory API, a subsector without a side, the lines, the sectors, the requests, the steps (`llayout.LS`) |
| 4.2: W `$B000-$BC7F` `mobjinfo` | Stage B's scratch over it and the request buffer (`$A000-$B7FF`); stage C copies `mobjinfo` at `SPAWN`, after the static steps | 4,576 B of scratch (each line's two sectors, each sector's count, first entry, two positions) needed room; no request runs inside a step |
| 6.2: "no stray write" by the write log | The write log, narrowed (the bulk regions the load may write are not logged: a full log would pass 10 M lines), plus a second run's whole-machine diff | The memory API's copies are not CPU writes; the diff sees them |
| 5.7: `halfSum` rounding toward zero | A logical shift (the sign lost) planted instead | Not observable: see 5.7 (stage B) |
| 5.4: the read-back "with the game layout's level.json" | Into the layout of the frame's own levelconv.py directory (its level.json, texmap.json, patchmap.json); the game layout's texmap.json and patchmap.json give the places to read | A frame's injected state names its source's harness places (the sky's slot, the patch indexes, the sectors' zone address) |
| 1.7: `CODE` (the phase images and card images) | `CODE.1`, the load image only; the card image is in `LEVELS.SYSTEM` | Stage B's disk; milestone 11 adds the render and tic images |
| 4.4: `lgeom.s` 2,000 B | 2,059 B | Reported; the module pair is within 3,200 |

### Planted bugs, each in a scratch copy of the sources and caught

In `tests/test_native_level_load.py`: the box without the overflow flip
(the synthetic lines: E1M1's first six lines poked with coordinates whose
differences overflow, loaded by the 65C02 and by `HostMachine`: no E1
line spans 32,768 units); `halfSum` without the sign (the window); a
line put twice into a sector that is both its sides (the window); the
flood lines walked first to last (the window, LVG1); a stray store into
`LVSEG` that writes back the byte there (the write log only: the window
is equal); the variants not undone (loads 2 and 3 of E1M1, E1M7, E1M1:
each finds the other's variant columns in its slots); `LV_VARMAP` not
set; a request without its last descriptor (the window); colormap B made
through table A (`LVC`); the boot copying bank 9's segment into bank 10
(the disk check: the bank file's bytes); every subsector given sector 0
(the only byte the 65C02 computes that the renderer reads: `frame8.py
--levels loaded` fails on `tour-01`). The stops: a map the store lacks
(`LS_MAP`), a block with a codec (`LS_CODEC`).

### Open points of stage B

- **Stage C** has the game core, `SPAWN`, `SPECIALS`, the zone,
  acceptance 1 and 3, the setup's CRCs on the disk, and `lgame`.
- **The card** has not run `LEVELS.hdv`: the owner's milestone 12. The
  card's ProDOS read rate is not measured (1.7: 12-35 s at 100-300 KB/s
  for the 3.0 MB).
- **Timing** is the model's; the static steps are bound by the far
  layer's windows (one a record or entry). If milestone 12 finds loads
  slow, `GROUP`'s per-entry reads can be batched by page.
- **The text page** (main `$0400-$07FF`) holds colormap levels 32 and 33
  after a load; `LEVELS.SYSTEM`'s final table overwrites them (a test
  disk's licence, as `RENDER.SYSTEM`'s).

## Stage C as built (2026-10-01)

Stage C of section 6.3 is built, on a2vm (the card runs wait for
milestone 12). The 65C02 sets up each map as upstream's `P_SetupLevel`
does, from the map's game state at `P_SetupLevel`'s entry: the load of
stage B, then `SPAWN` (the things, the player, the weapon) and
`SPECIALS`, into the native zone.

| File | What it is |
| --- | --- |
| `src/native/lsetup.s` | `nl_setup(m)`: `G_InitNew`'s and `G_DoLoadLevel`'s part before the load (the totals, par time, the player's counts, `viewz`), the thinker list and the zone emptied, then `nl_load` with the game steps on (`GS_GAME`) |
| `src/native/gthink.s` | The thinker list (2-byte handles), the mobj slots (`RTH` and the three game groups), the pool (`poolTake`'s bitmap, the highest free slot), the zone's mobjs, the specials' ranges, the sector nodes (pools of 32, upstream's free list), the globals' far access, `P_Random` with its table |
| `src/native/gpos.s` | `R_PointInSubsector`, `P_SetThingPosition` with `P_CreateSecNodeList` (`validcount`, the box walk, `P_BoxOnLineSide`'s slanted corners, `addSecnode`, `newSecnode`), the block lists |
| `src/native/gspawn.s` | `SPAWN`: the level's globals from the header, `P_SpawnMapThing` for each thing, `P_SpawnPlayer`, `G_PlayerReborn`, `P_SpawnMobj` |
| `src/native/gweap.s` | `P_SetupPsprites`, `bringUpWeapon`, `P_SetPsprite`, `A_Raise` |
| `src/native/gspec.s` | `SPECIALS`: `P_SpawnSpecials` |
| `src/native/gvalid.s` | `gv_inc`, the release wrap fix (3.4) |
| `src/native/lload.s`, `ldriver.s`, `lboot.s`, `level.cfg`, `level.mk` | The two steps dispatched; the driver's pre-states; the disk's setups and CRCs; the builds `ltest`, `lprof`, `lfix` (the release wrap on a2vm), `lcard` |
| `tools/bridge/layout.py`, `port.py` | The encodings `handle`, `sxbyte`, `bit`; a list head as a handle, a sequence of form "end", a pool of handles, a constant count |
| `tools/native/llayout.py` | The game's places (section "stage C"), `lgame.inc` (the places and upstream's constants), the manifest `native-level-1` with every dynamic kind, `allowed_writes_setup` |
| `tools/native/setupcheck.py` | The pre-states (the E dump's game state, written through the manifest), the canonical comparison, the zone bound, the reloads' static kinds, the flood depths, the timing, the wrap check, `report.md` |
| `tools/native/setupcap.py` | The run `wrap` (`validcount` poked to `$FFE0` at `P_SetupLevel`'s entry, E1M1) |
| `tools/native/lrun.py`, `ldisk.py`, `level_check.py` | The setup runs and their stray check; the disk's pre-states and CRC lists; `--setup`, `--flood`, `--setup-timing`, `--report-md` |
| `tests/test_native_level_setup.py` | 24 tests, below |

### Commands

    python3 tools/native/setupcap.py --runs wrap       # the wrap capture (a minute)
    make -C src/native -f level.mk                     # ltest, lprof, lfix, lcard
    python3 tools/native/level_check.py --setup        # acceptance 1 and the wrap fix (3 min)
    python3 tools/native/level_check.py --flood --no-build        # acceptance 3
    python3 tools/native/level_check.py --setup-timing --no-build
    python3 tools/native/ldisk.py --check              # LEVELS.hdv, 20 setups, f121 and fastpath
    python3 tools/native/level_check.py --report-md    # build/native/levels/report.md
    python3 -m unittest discover -s tests -p 'test_native_level_setup.py'

### Acceptance 1

| Item | Result |
| --- | --- |
| The setups | **54 of 54 equal**: the 53 of stage A (45 tour setups, 3 demos, 2 reloads and their first loads, the new game) and the wrap capture, each from both poisoned machines (`$A5`, `$5A`: 24 runs, the setups of a capture run in one image run, in its order). Each native canonical state (`native-level-1` read back) equals the R dump's with only 5.2's exclusions (the caches the native layout does not keep: `sightline`, `LR_*`, `TP_HW`, `CS_PREV*`, `GW_TAG`, `G_ID`, `line.gstamp`) |
| Stray writes | 0: the write log against the setup's allowed set (the window, the game banks `RTH`, `MOBJA-C`, `ZONE0-1`, the globals block, `LNMAP`, the zero page of the game core and the math, the random indexes) and the driver's |
| Stack | 27-29 B below the driver's S, +24 for the IRQ: at most 53 of 128 (estimate 40) |
| The zone | Every R dump's zone-mobj bound within 2,026 - its pool: least margin 428 (`newgame-01`, E1M1: bound 1,482, room 1,910) |
| Reloads | `reborn-e1m1-02`, `reborn-e1m6-08`: the static level kinds equal their first loads', the window outside stage C's mask too |
| The wrap fix (3.4) | From `wrap-01`'s E (`validcount` `$FFE0`; upstream's wrap there drops a sector node of mobj 84, as its R dump shows): `ltest` equals ref816's R dump; `lfix` equals `newgame-01`'s state with the stamps renumbered (`validcount` 61) |

### Acceptance 3

`level_check.py --flood`, from the machines of the nine `tour-sk2`
setups (their flood lists as loaded): worst depths E1M1 52, E1M2 93,
E1M3 93, E1M4 23, E1M5 85, E1M6 87, E1M7 61, E1M8 52, E1M9 72; the
bounds (2 x sectors) 148-500; **all within 512**, as 5.5 measured on
the host.

### The disk

`ldisk.py --check`: `LEVELS.hdv` (3,150,336 B: the store's bank files,
`CODE.1`, `PRESTATE.1` with each map's pre-state, `CRCLIST.1` with the
CRC ranges and expected CRCs) boots under its MLI trap on a2vm, `f121`
and `fastpath`, and sets up the nine maps in a row, in reverse and E1M5
twice (20 setups); after each, the window's CRC and the game state's CRC
(both CRC-32, computed by the 65C02) equal the host's, the canonical
state equals ref816's, and the screen's last page reads "SETUPS OK:
EVERY CRC AS EXPECTED". Boot 1,144.5 ms (`f121`), 851.6 ms
(`fastpath`); setups 9-33 VBLs (`f121`), 6-20 (`fastpath`). The
expected CRCs come from `lfix`'s image run, itself compared with ref816.

### Sizes (4.4) and timing

| Module | `lcard` | Budget |
| --- | ---: | ---: |
| `lload.s` | 946 | 1,200 |
| `lgeom.s` | 2,059 | 2,000 |
| `lsetup.s` | 74 | 500 |
| `gspawn.s` + `gweap.s` | 1,497 | 2,200 |
| `gpos.s` | 1,770 | 2,200 |
| `gthink.s` + `gvalid.s` | 1,252 | 700 |
| `gspec.s` | 741 | 900 |
| **All** | **8,339** | **9,700** |

`gthink.s` + `gvalid.s` is 552 B over: `P_Random`'s 256-byte table (the
design counted it nowhere), the release wrap's clear (134 B; the test
builds' `gvalid.s` is 9 B), the far access of the globals and the three
allocators. The whole is within its budget; W's load code is
`$6600-$8692`, 6,509 B of `$6600-$9FFF` left.

Load and setup of each map alone (`lprof`; the model's figures), ms:

| Map | `f121` | of which the spawn | the specials | `fastpath` |
| --- | ---: | ---: | ---: | ---: |
| E1M1 | 216.3 | 88.2 | 10.6 | 130.8 |
| E1M2 | 430.1 | 188.0 | 25.2 | 256.0 |
| E1M3 | 524.7 | 287.6 | 22.2 | 320.3 |
| E1M4 | 374.0 | 178.7 | 18.5 | 225.8 |
| E1M5 | 397.9 | 199.0 | 19.6 | 239.8 |
| E1M6 | 654.2 | 349.5 | 29.4 | 398.8 |
| E1M7 | 478.2 | 252.3 | 22.3 | 290.6 |
| E1M8 | 191.0 | 81.7 | 8.0 | 116.4 |
| E1M9 | 336.7 | 168.3 | 14.4 | 206.2 |

The spawn is 0.6-0.8 ms a thing on `f121` (estimate 0.5): each node of
the descent, each block's line list entry and each sector record is a
far fetch. `report.md` has every phase. Banks (1.6 against `NATIVE.md`
4.4): **109 of 126 used, 17 spare** (1-5, 72-74, 91-97, 125, 126): the
mobjs' game part takes 3 banks, not 6.

### What stage C changed, and why

| Design | As built | Why |
| --- | --- | --- |
| 3.2: a mobj's game part, 128 B in `MOBJ0-5` | Three groups of 24 B in `MOBJA-C` (banks 69-71), at the same address as its `RTH` slot; 72-74 spare | 72 B of fields fit three 24-byte groups; the same address in four banks needs no index arithmetic. 3 banks back to the spare |
| 3.1, 3.2: specials, a free list of 1,024, handles `$0800-$0BFF` | A range of slots a kind (1,280 in all), handles `$0800-$0CFF` | The specials are identified by rank and reach (`identity.renumber`), so the slot policy is free; a range a kind keeps the manifest's kinds apart without a kind byte |
| 3.1: sector nodes, a free list of 2,048 | Upstream's pools of 32 and its free list (2,048 capacity) | The free sector nodes and their order are part of the canonical state: the native list must be upstream's |
| 3.2: the cold globals in `ZONE1` | All in main's globals block `$1C80-$1E6E` (495 B) | They fit; one place to inject and to read back |
| `MEMORY_MAP.md` 3.3, 12: `LNMAP` `$1B80-$1BFF` | `$1B80-$1C7F` (256 B) | 2,048 bits; `rlayout.py` always had it so; the doc corrected. The globals block starts after it |
| 4.2: `mobjinfo` copied to W `$B000` | One record a spawn from `GTAB` into `LW_MINFO` | A far fetch a thing is small against the node walk's; W's room stays free |
| 1.3: the map's header | Plus the `BLOCKMAP` and `REJECT` lump numbers (4 B; 177 B) | Upstream's globals hold them (`_g_bmlump`, `_g_rejectlump`); the store rebuilt |
| 3.4: the renderer's wrap call in release builds | Not made; **deferred to milestones 10-11 and recorded for the owner** (`NATIVE.md` 15.1 row 4, `MILESTONES.md` row 9) at the verification | The renderer's frame count is its own until milestone 10 joins the two counts; the call belongs with milestone 11's release frame |
| 3.4: the unit test "a level at `validcount` `$FFFF`" | A ref816 capture, `wrap` (`validcount` `$FFE0` poked at `P_SetupLevel`'s entry, so the setup's walks wrap) | Exact for both builds: `ltest` against upstream's own wrap, `lfix` against the plain setup renumbered |
| 4.1: build `lgame` | `lcard` (the disk) and `lfix` (the release wrap on a2vm) | `lcard` is the image `LEVELS.SYSTEM` loads; `lfix` is the release image a2vm checks |
| 5.6: `level_check.py --timing --flood --report` | `--setup-timing`, `--flood`, `--report-md` | `--report` already named the report's path; `--load-timing` is stage B's |
| 5.7: the block walk with y outer, caught by acceptance 1 | **Not observable at the captured setups**: planted, it passes all 54 (the verification); **caught since the verification by the synthetic setup `secorder`** | At setup a thing's box spans at most 2 x 2 blocks, and no E1 thing's off-diagonal blocks add two new sectors in another order; `secorder` moves three E1M1 things to block corners where they do |
| 5.1: 51 setups | 54 | Stage A's two first loads and the wrap capture |
| 4.4: `gthink.s` + `gvalid.s` 700 B | 1,252 B | Above |

### Planted bugs, each in a scratch copy of the sources and caught

In `tests/test_native_level_setup.py`, by acceptance 1's check on
`tour-sk2-01` (E1M1): the pool's lowest free slot (the thinker order and
the block lists); `poolTake` taking the lowest free bit of the highest
non-empty byte; `P_SpawnMobj`'s `P_Random` after the tics (`prndindex`
and mobjs' tics); a thinker for a mobj whose tics are -1 (the
thinker list); a missing secret count (`totalsecret` 3 != 0); a thing put
after its block's head instead of at it (13 differences, all block
lists); a strobe that
leaves its sector's `special`; a stray store into `LVSEG` that writes
back the byte there (the write log only: the state is equal); and, by
the wrap check, the release build without its clear. The flood check
fails against a stack of 80 (E1M2's 93). Without `build/`: the three
encodings' round trip and refusals, the game layout's places, the flood
depth and the wrap renumbering on hand-made data.

### Open points of stage C

- **The card** has not run the setup disk: the owner's milestone 12.
- **The block walk's order**: checked since the verification by the
  synthetic setup `secorder` (below).
- **The renderer's wrap call** (3.4) is deferred to milestones 10-11,
  recorded for the owner (`NATIVE.md` 15.1 row 4).
- **The zone's mobjs** are not created by any setup (below, defect 5):
  a named gate of milestone 10.
- **The spawn's time** (82-350 ms on `f121`) is far-fetch bound; any load
  time is acceptable (15.1 row 9), but a cache of the BSP's top levels
  would halve it if milestone 12 wants.
- **`gthink.s` + `gvalid.s`** are over their estimate (the whole is
  within).
- **Milestone 10** owns the game layouts (3.2): the manifest keeps any
  change to one edit in `llayout.py`.

## Verification of stage C (2026-10-01)

One verification round on stage C reported 7 defects. Each was checked
against the evidence: 6 confirmed and fixed (4 with tests), 2 of them by
recording an open item where the task allowed it (3 and 5), and none
rejected.

| # | Defect | Verdict | What was done |
| --: | --- | --- | --- |
| 1 | `test_zero_page_and_names` errors without `build/` (`LL.game_include_text()` needs `build/linkmap.json` and the release) | Confirmed | The zero-page assertion stays unconditional (`test_zero_page`); the `lgame.inc` name check is `test_include_names`, skipped with a message unless `build/linkmap.json` and the release are there. In a copy of `tools/`, `tests/`, `src/` and `coverage/` without `build/`: the three level test files 85 tests, OK, 47 skipped |
| 2 | `G_PlayerReborn`'s resets almost never observed: in both reloads the player at E already held the reset values | Confirmed (the E and R players of `reborn-e1m1-02` are equal in every reset field) | A capture run `reborn-kit` (`setupcap.py`: the reborn script, with the player given a kit in the frame before `PST_REBORN`: bob, `deltaviewheight`, health 57, armour 42 of type 1, two powers, two cards, the backpack, two weapons, ammunition and its maxima, `didsecret`): its E player holds every kit value and ref816's R player differs in each (checked by `test_reborn_with_a_kit`); the native setup equals ref816's from both fills. Planted, `G_PlayerReborn` without its clear (only `viewz` zeroed) fails on `reborn-kit-02` with 11 differences (ammunition, armour, backpack, bob, cards, powers, weapons ...) and not on `reborn-kit-01` (`test_player_reborn_without_its_clear`) |
| 3 | The renderer's wrap call (3.4, listed under 6.3's builds) not made and the deferral not recorded for the owner | Confirmed | Recorded, not built: `NATIVE.md` 15.1 row 4 and `MILESTONES.md` row 9 name it as open for milestones 10-11, with why (until milestone 10 makes `VALIDCOUNT` and `G_VALID` one count, as upstream's, a clear in `nr_setup` guards a count the game does not share) |
| 4 | The block walk's order is not observable at setup: planted y outer passes all 54 setups | Confirmed | A synthetic setup `secorder`: `tools/native/secorder.py` finds, on E1M1's canonical state, block corners where the two orders give different sector lists for a thing of radius 20 (robust to the box grown and shrunk by a unit), and moves map things 5, 7 and 8 there; `setupcap.py --runs secorder` pokes them into upstream's `THINGS` lump at the first `P_SpawnMapThing` (newgame.script), and `setupcheck.thing_records` puts the same coordinates into the store's `THINGS` block of the native run. ref816's sector nodes are the model's x-outer lists ([6, 7, 0], [36, 35, 24], [34, 29, 30]); the native setup equals ref816's from both fills (`test_block_walk_order`); the planted y-outer walk fails with 12 differences, all `secnode[..].m_sector` (`test_block_walk_y_outer`); the model itself on a hand-made level (`test_block_walk_model`). `secorder` is marked `synthetic` in its `setup.json`, so `level_check.py --conv` does not compare its W dump with the release's lumps (its `THINGS` lump is poked), as it does for the `synth-*` level sources |
| 5 | No setup creates a zone mobj: the zone branch of `gt_pooltake`, the `zmobj` handle range and `LS_ZONE` never run | Confirmed | Recorded for milestone 10, as a named gate of its lockstep: at setup upstream spawns at most one mobj a map thing into a pool of one slot a map thing (`p_setup65.s` `loadThings`), so no E1 setup, captured or synthetic, reaches the zone, and a pre-state cannot fill the pool in the middle of `nl_setup` without a test hook in the game core. Milestone 10 spawns mobjs in play (missiles, puffs, blood, drops): its first zone mobj, the handle range and that a zone slot is never handed out twice are to be compared with ref816 there |
| 6 | Stale texts: the status line, 1.6 and 3.2 (`MOBJ0-5`, 112 of 126), `MEMORY_MAP.md` 3.5's flood stack "about 600 B", `report.md`'s stage B timing from before stage C changed `lload.s` | Confirmed | The status line, 1.6 (banks 69-71 `MOBJA-C`, 72-74 spare, 109 used, 17 spare, the table against `NATIVE.md` 4.4), 3.2 (the mobj, special, sector node, thinker and globals rows as built), the summary and risk 1 corrected; `MEMORY_MAP.md` 3.5: 1,536 B; `--load-timing`, `ldisk.py --check` and `--report-md` rerun together (E1M1's load alone now 117.4 / 67.5 ms) |
| 7 | The stray-write and whole-machine checks allowed the union of every map's places in a run | Confirmed | `lrun.stray_by_load` cuts the write log at each `drv_loaded` (the driver's `inc dl_k`) and checks each load's or setup's writes against its own map's set only (`--load`, `--setup`); `--load` loads each map alone once more with a whole-machine snapshot, every changed byte within that map's own places (`changed_outside_alone`). Tests: `PerLoadWrites` (a write into another map's place passes the union and fails per load, on hand-made data) and the checkpoint B sample (each map alone: 0) |

After the fixes:

| Check | Result |
| --- | --- |
| Captures | 57 setups (the 54 and `reborn-kit-01`, `-02`, `secorder-01`): 0 bridge problems, every W equal to its R; `--conv` 53 of 53 W dumps and 13 of 13 level sources equal (6 synthetic not compared); `--derive` 57 R dumps, 0 failures |
| Checkpoint B (`--load`) | 2 runs of 20 loads, 0 failures, each load's writes against its own map's set; whole machine 0 bytes outside, each of the nine maps alone 0 |
| Acceptance 1 (`--setup`) | **57 of 57 setups equal ref816's**, 28 runs (both fills), 0 failures, each setup's writes against its own map's set, stack 27-29 B (+24 IRQ), least zone margin 428 (`newgame-01`); the wrap fix ok |
| Acceptance 2 (`frame8.py --levels loaded --sets m7,demo3`) | 729 frames, 1,458 runs, all equal, 0 failed, 0 known divergences; 877,168 records and 8,710 clip-log calls compared; the same five synthetic frames excluded by name; staging margin 11.9 times (`synth-pagefull` 7.8) |
| Acceptance 3 (`--flood`) | Unchanged: worst depths 23-93, all within 512 |
| The disk (`ldisk.py --check`) | 20 setups, every CRC as expected, `f121` boot 1,144.5 ms (VBLs 9-33), `fastpath` 851.6 ms (6-20) |
| Timing | `--setup-timing` unchanged (E1M1 216.3 / 130.8 ms ... E1M6 654.2 / 398.8); `--load-timing` E1M1 117.4 / 67.5 ... E1M6 275.1 / 153.0 (`report.md` now from this run) |

**The gates left to milestone 10, closed (2026-10-02, `docs/GAME.md`
"Acceptance"):**

| Gate | Evidence |
| --- | --- |
| `VALIDCOUNT` and `G_VALID` one count (defect 3's premise) | `G_VALID` is the frame block's `VALIDCOUNT`, raised by the frame through `gv_inc`; in every lockstep run (demo3, DEMO1, DEMO2, newgame, the tour, G1, G3, G5) every tic's `validcount` and every line and sector stamp equal `ref816`'s, the native front end running at each of the reference's frames. The release's clear at the wrap in the renderer stays milestone 11's |
| The first zone mobj, `LS_ZONE`, no slot handed out twice (defect 5) | Generated streams G1 (E1M1, UV) and G3 (E1M2, nightmare) make zone mobjs in play (4 and 3 at most at a tic); every tic equal to `ref816`'s, the port reader refusing two objects in one slot; the highest mobj slot of any run 449, of 768 |
| The block walk's order on every move (defect 4) | 3,539 compared tics in which the reference changed the sector nodes and 6,673 in which it changed the block lists, each compared as a sequence, all equal |
| Bank `$21`'s sight and move tables | `LNSECF`, `LNSECB`, `RJROW` against upstream's `LNSEC` and `SS_ROW` on all 57 setup dumps (`ticcap.py --tables`): 0 failures; every sight and move of the runs above equal |
