# Verifying a native 65C02 rewrite against the reference

Status: design and feasibility study, 2026-09-30. Nothing here is built
into `tools/`, `src/` or `tests/`. The prototype helpers are in
`build/native-design/` (ignored by git; they read upstream's GPL-2
sources, so they stay there).

Every claim is marked **measured** (I ran it), **read** (`file:line`, in
upstream's `src/iigs/` unless another path is given) or **assumed**.

## 0. Summary

- **The state bridge works on real states.** From ref816 RAM dumps of
  E1M1, E1M3 and the title demo, a 545-line standard-library Python
  prototype found and decoded every mobj, the player, the thinker list,
  the level arrays, the drawsegs, the vissprites and the column records
  of bank `$1D`. Eight consistency checks passed on all six dumps. A
  conversion of every mobj to a structure-of-arrays layout and back gave
  0 differing bytes (measured, section 3).
- **Existing ref816 options are enough to capture any state at an exact
  routine entry.** One run logs the entries (`--mark`); a second run
  stops at the logged cycle count (`--cycles`) and dumps RAM
  (`--dump-ram`). All 6 captures stopped exactly at the entry (measured).
  But each dump costs a rerun from power-on (0.7 to 1.6 s): fine for a
  few states, too slow for every tic of a demo (about 1.8 hours for
  demo3, assumed from the measured rate of about 300 million cycles a
  second and runs of up to 1,000 million cycles). Section 5 lists what
  ref816 must add.
- **Instruction samples give complete routine footprints today.** With
  `--trace-samples` and `--trace-sample-every 1`, every instruction's
  reads and writes are recorded: 1,486,484 instructions over 4 frames in
  3.8 s, 301 MB of text (measured). Good for short windows; a compact
  per-call log is needed for long runs.
- **Finding: the title demo is E1M7, not E1M3.** The demo in RAM has
  header `6d 02 01 07` (version 1.9, skill 2, episode 1, map 7), the
  same as DEMO3 of `DOOM1.WAD`; `_g_gamemap` is 7; the decoded level has
  exactly E1M7's 170 sectors, 958 lines, 1,371 segs, 467 subsectors and
  466 nodes (measured). `docs/MILESTONES.md:140`, `docs/PROFILE.md:28,157`
  and `coverage/title.script:7` say E1M3. The E1M3 figures below come
  from `coverage/tour.script` instead.
- **Demo sync needs only game-logic arithmetic to be bit-exact**, but
  that includes upstream's own approximations (`FixedApproxDiv` and its
  reciprocal table, `FixedMulAngle`, Doom8088's sine tables, the sight
  side tests) and the integer division of the vendor runtime (18 call
  sites in game code). Frame equality adds every renderer approximation,
  `qmulh` first (section 8).
- **Some state is not comparable tic by tic.** `validcount` and the
  sector and line stamps advance once per rendered frame as well as in
  game logic; the mobj kind cache (byte 11), `SIGHTLINE` and `SIGHTHINT`
  are upstream-private caches. The bridge must exclude or re-derive them
  (section 4.4).

## 1. What must be compared, and why a bridge

The rewrite changes data layouts: 24-bit far pointers with a pad byte
become indices or 16-bit addresses, 120-byte mobj records may become
arrays of fields, bank placement changes. So memory cannot be compared
byte for byte. The **state bridge** is a host tool that:

1. reads the reference's memory (a ref816 dump) and extracts upstream's
   structures by symbol (`build/linkmap.json`, from our own assembler)
   and field offset (`src/iigs/offsets.inc`, `lists.inc`, `memmap.inc`);
2. turns them into a **canonical model**: objects with an identity,
   fields with values, pointers as references to identities, and lists
   as ordered identity lists;
3. reads the port's memory (an a2vm snapshot) through the port's layout
   manifest into the same canonical model;
4. compares the two, with an explicit list of excluded fields;
5. writes a canonical model back into either layout, so that a reference
   state can be injected into the port (and a port state into the
   reference, for bisection).

## 2. Upstream's core runtime structures

Definitions are read; addresses and counts are measured from the dumps
of section 3, at `G_Ticker` entry. "E1M1" is standing still after the
new game (gametic 104, leveltime 69). "E1M3" is the tour after its
level start, god mode (gametic 447, leveltime 41). "Demo" is the title
demo, E1M7 (gametic 1124, leveltime 73).

### 2.1 Level and game state

| Structure | Definition | Where | Record | E1M1 | E1M3 | Demo (E1M7) |
| --- | --- | --- | ---: | --- | --- | --- |
| `mobj_t` | `offsets.inc:135-171` | pool `_g_thingPool` (`p_setup65.s:82`), a zone block: E1M1 `$06:2590`, E1M3 `$08:0010`; zone mobjs when the pool is full (`p_spawn65.s:275-297`) | 120 B | pool 116 (13,920 B), live 92 | pool 368 (44,160 B), live 310 | pool 337 (40,440 B), live 264 |
| pool free map `TP_BITS` | `p_spawn65.s:30-33`, `memmap.inc:23` | `$0A:8000` | 96 B | | | |
| `player_t` | `offsets.inc:246-282` | `_g_player` `$02:C614` (`g_game65.s:123`) | 155 B | 1 | 1 | 1 |
| `thinker_t` list | `offsets.inc:207-211`; head `_g_thinkerclasscap` (`p_think65.s:327`) | head `$02:F146`; thinkers are mobjs and zone blocks | 12 B head | 64 thinkers (52 mobjs, 12 specials) | 216 (204, 12) | 212 (191, 21) |
| mobjs with no thinker | `p_spawn65.s:241-262`, `addIfFunc` (`r_list65.s:919-932`) | in the pool | | 40 | 106 | 73 |
| `sector_t` | `offsets.inc:108-127` | `_g_sectors` (`p_setup65.s:67`): `$06:ABE0` / `$09:9DD0` | 58 B | 85 (4,930 B) | 177 (10,266 B) | 170 (9,860 B) |
| `line_t` | `offsets.inc:92-106` | `_g_lines` (`:71`): `$06:5C00` / `$09:0010` | 36 B | 475 (17,100 B) | 1,026 (36,936 B) | 958 (34,488 B) |
| `side_t` | `offsets.inc:83-90` | `_g_sides` (`:73`): `$06:BF40` / `$09:C600` | 14 B | 273 (3,822 B) | 604 (8,456 B) | 609 (8,526 B) |
| `subsector_t` | `offsets.inc:201-205` | `_g_subsectors` (`:69`): `$06:D6E0` / `$06:2590` | 8 B | 237 (1,896 B) | 461 (3,688 B) | 467 (3,736 B) |
| `seg_t` | `offsets.inc:72-81` | `_g_segs` (`:65`), in place in the level window: `$33:26EC` / `$35:0000` | 18 B | 732 (13,176 B) | 1,445 (26,010 B) | 1,371 (24,678 B) |
| `node_t` | `offsets.inc:192-199` | `nodes` (`p_setup65.s:1467`), in place: `$33:5B51` / `$35:6767` | 28 B | 236 (6,608 B) | 460 (12,880 B) | 466 (13,048 B) |
| blockmap, reject | `p_setup65.s:432-463`, `:143-145` | in place: blockmap `$33:7CA5` / `$35:B150`, reject `$33:791D` / `$35:A203` | | | | |
| block thing chains | `_g_blocklinks` (`p_setup65.s:80`) | `$06:9EE0` / `$09:9070` | 4 B | 828 (3,312 B) | 850 (3,400 B) | 864 (3,456 B) |
| `msecnode_t` (touching lists) | `offsets.inc:284-295`; pools of 32 from the zone (`p_map65.s:2126-2131`, `:3164`) | zone | 26 B | 100 live (2,600 B) | 324 (8,424 B) | 296 (7,696 B) |
| specials (`plat_t`, `vldoor_t`, lights, scrollers) | `offsets.inc:331-363` and their files | zone blocks on the thinker list | 35-42 B | 12 | 12 | 21 |
| `states[]`, `mobjinfo[]` | `info65.s:49`, `:367`; `info.inc:4-5` | `$02:00DC`, `$02:147C` | 16 B, 64 B | 314 (5,024 B), 50 (3,200 B) | same | same |
| random | `m_random65.s:9-46` | `prndindex` `$02:F154`, `rndindex` next to it, `rndtable` `$04:51E7` (256 B) | 1 B index | 145 | 239 | 239 |
| tic commands | `ticcmd_t` `offsets.inc:324-329`; `netcmd`, `cmds`, `GT_CMD` `g_game65.s:146-149`; `CMDS` 8 (`g_game65.s:39`) | ring `$02:C748`, 8 slots of 8 bytes (5 used) | 5 B | | | |
| game clocks | `_g_gametic`, `_g_basetic` `g_game65.s:124-125`; `_g_leveltime` `p_think65.s:326` | `$02:C6AF`, `$02:C6B3`, `$02:F142` | 4 B each | | | |
| demo | `demobuffer`, `demolength`, `demo_p` `g_game65.s:136-138`; `readDemoTiccmd` `:1144` | DEMO3 lump at `$10:8984`, 8,550 B, 4 B a tic | | | | 2,134 tics (assumed: one end marker) |
| `validcount` | `p_map65.s:303` | `$02:75F8`, 16 bits | 2 B | 125 | 1,015 | 742 |

Totals of the per-level structures above (sectors to secnodes): E1M1
67,364 B, E1M3 154,220 B, E1M7 145,928 B (measured sums). In all three
dumps every live mobj came from the pool; none was a zone mobj.

### 2.2 Frame structures

Measured at `R_DrawLists` entry. E1M1 standing still gave the same
counts on 3 consecutive frames; the demo range is over 11 frames, every
6th frame from its 1st second.

| Structure | Definition | Where | Capacity | E1M1 | E1M3 | Demo (11 frames) |
| --- | --- | --- | --- | --- | --- | --- |
| `vissprite_t` | `offsets.inc:9-23`; `vissprites`, `num_vissprite` `r_state65.s:100-101` | `$02:AEEC` | 80 x 42 B = 3,360 B | 7 | 3 | 0-28 |
| `drawseg_t` | `offsets.inc:25-38`; `_s_drawsegs`, `ds_p` `r_state65.s:33`, `:55` | `$02:8214` | 128 x 42 B = 5,376 B | 34 | 7 | 2-41 |
| openings | `r_state65.s:34-35` | `$02:9714` | 2,560 x 2 B | 452 | 142 | 58-305 |
| column records | `lists.inc:1-185`; `COLW`, `XPNEXT`, `colOrder` `r_list65.s:89-92` | bank `$1D` (`memmap.inc:52`): home page per column (`COLPAGE`, `lists.inc:20`), extra pages `$CE-$FF` | 53,760 B | 721 records, 5,969 B (327 FILL, 394 TEX) | 520, 3,806 B | 189-1,348 records, 2,079-10,524 B, with FUZZ |
| fill spans, covered ranges | `lists.inc:82-117` | `$23:EF00-$23:FAFF` | 3 KB | | | |
| weapon skip | `lists.inc:129` | `$0A:C500` | | | | |
| vertex angles and stamps | `memmap.inc:85-86` | `$23:0000`, `$23:4000` | | | | |
| screen | `i_viigs65.s:26-31` | `$01:2000-$9CFF`, mirrored in `$E1` | 32,000 B + SCB + palettes | | | |

The record decoder walked all 160 column lists of every dump with no
record of unknown kind (measured), which also checks the `COLPAGE`
mapping.

### 2.3 The level store and its tables

| Item | Definition | Where (measured) |
| --- | --- | --- |
| Store, 8 MB mode | `STORE_BASE` `w_level65.s:67` | `$40:0000` |
| Loader variables | `W_NEXTBANK`, `W_COLSTART`, `LV_*` `w_level65.s:98-126` | bank 0 `$8A00-$8C8F` |
| Window banks | `LV_WIN`, `LV_NWIN` `w_level65.s:103-104` | 38 banks: `$2A-$3F`, `$0E-$0F`, `$5C-$69` |
| Set image end, column memory top | `W_COLSTART`; `colmem` (`r_data65.s:78`) | E1M1 `$36:DFD4`, `$39:0880`; E1M3 `$3B:9640`, `$0E:F800`; E1M7 `$39:BBA0`, `$3C:9AB8` |
| Window used | | E1M1 about 15.0 banks (985 KB), E1M3 23.0 (1,505 KB), E1M7 18.6 (1,219 KB) (assumed: filled in `LV_WIN` order from `$2A:0000`) |
| Resident WAD | `w_wad65.s:1-10`, `fileinfo`/`numlumps` `:29-30` | `$10:0000`, directory at `$10:000C`, 1,015 lumps |
| Texture column directory | `memmap.inc:103` | `$25:0000` |
| Per-map sight and move tables | `memmap.inc:59`; `p_sight65.s:76-86` | bank `$21` |

The level constants (segs, nodes, blockmap, reject, the tables of bank
`$21`, texture columns) do not change during a level. The bridge
compares them once per level load, not per tic.

## 3. Feasibility run

Helpers in `build/native-design/` (measured unless noted):

| File | What it does |
| --- | --- |
| `capture.py` | Cuts a coverage script after a point, runs ref816 once with `--mark G_Ticker --mark R_DrawLists`, then reruns to the cycle count of the first entry after the point with `--cycles` and `--dump-ram` |
| `bridge.py` | Parses `offsets.inc`, reads `linkmap.json`, decodes a dump: level arrays, thinker list, pool, mobjs, player, secnodes, drawsegs, vissprites, column records; runs the checks and a round trip |
| `series.py` | The same over a series of frames, deleting each dump after decoding |
| `a2vm_load.py` | Puts decoded mobj fields into an `A2VMIMG1` image as byte planes in RamWorks bank 5, loads it in a2vm, dumps a2vm's RAM with a bus script, reads the planes back |
| `footprint.py` | Per-call read and write footprints from instruction samples |

### 3.1 Captures

| Capture | Cycles | Instructions | Stopped at |
| --- | ---: | ---: | --- |
| E1M1 `G_Ticker` | 172,980,261 | 44,914,503 | `$03:CEB7`, the entry |
| E1M1 `R_DrawLists` | 172,583,162 | 44,800,005 | `$05:9AE8`, the entry |
| E1M3 `G_Ticker` | 404,818,326 | 103,451,783 | entry |
| E1M3 `R_DrawLists` | 405,384,889 | 103,617,035 | entry |
| Demo `G_Ticker` | 261,613,133 | 67,015,950 | entry |
| Demo `R_DrawLists` | 262,188,510 | 67,177,147 | entry |

Host time: 2.7 s for the three runs of E1M1, 3.6 s for E1M3 and the
demo together (Apple M3 Pro). Each dump is 8,519,680 bytes (130 banks).

### 3.2 Checks on the decoded state

All passed on all six dumps and on the 14 series dumps.

| Check | What it proves |
| --- | --- |
| Thinker list: `next->prev` is the thinker before, from the head | the list and its far pointers decode |
| `player.mo` is a mobj of the list, of type `MT_PLAYER` | the player decodes and points into the pool |
| `mobj.state` is a record of `states[]` and its sprite and frame are the state's (`P_SetMobjState`) | the near state pointer (low word) decodes |
| `mobj.subsector` is a subsector record | pointers into zone arrays classify |
| The sector thing lists hold exactly the mobjs without `MF_NOSECTOR` | the mobj set is complete (it failed until mobjs with no thinker were included) |
| `mobj.radius` equals `mobjinfo[type].radius` | the 64-byte `mobjinfo` stride |
| Pad bytes of mobj pointers are 0 | a pointer is 24 bits plus a zero byte |
| Round trip upstream to structure of arrays to upstream: 0 differing bytes over 92, 310 and 264 mobjs | the handle scheme is lossless |

Pointer kinds found (measured): null, mobj (including pointers to a
field inside a mobj: `sprev` points at the previous mobj's `snext`),
sector field (`sprev` of the first mobj points at `sector.thinglist`,
offset 22), subsector, block link cell, state, secnode. After adding
the secnode pools, no pointer was left unclassified.

Decoded player, E1M1 (measured): health 100, ready weapon 1 (pistol),
ammo 50/0/0/0, `viewz` 41.0, `mo` the pool's mobj 91 at x 1056, y
-3616, angle 90 degrees. Demo: ready weapon 2 (shotgun), ammo 60/12,
cmd forward -2, turn -1024, buttons 2 (use); `demo_p - demobuffer` is
305 = 13 + 4 x 73, which matches leveltime 73.

### 3.3 Into a2vm

`a2vm_load.py` wrote the X, Y, Z, momenta, angle and flags of the 92
E1M1 mobjs as 32 byte planes (2,944 bytes) into RamWorks bank 5 at
`$4000`. a2vm loaded the image, its bus script dumped RAM (8,474,624
bytes: main, the language card, 128 aux banks), and the planes read
back with 0 mismatches (measured). The load path for injected state
exists today: `--image` records, `--reg`, `--stop-pc`,
`--final-snapshot` (read: `tools/a2vm/README.md`).

### 3.4 Footprints from instruction samples

Four frames of E1M1 standing still, every instruction sampled, phases on
`callFn` (the thinker call, `p_tick65.s:533`) and `R_RenderSegLoop`
(measured):

| Routine | Calls | Instructions a call, median / max | Input bytes a call, median / max | Output bytes a call, median / max |
| --- | ---: | --- | --- | --- |
| thinker functions (via `callFn`) | 201 | 12 / 695 | 12 / 133 | 6 / 101 |
| `R_RenderSegLoop` | 167 | 2,519 / 13,302 | 213 / 910 | 198 / 1,213 |

Inputs exclude program, stack and I/O accesses. The seg loop reads the
square tables (banks `$13-$18`), `FSTEP` (`$1B-$1C`), fill spans and
angles (`$23`), the texture directory (`$25`) and texture columns
(`$36-$37`); it writes 27,949 bytes of records in bank `$1D` and 382
bytes into its own code bank `$03` (self-modifying patches), which a
footprint must drop. Thinker functions are entered by `JML [dp]`
(`p_tick65.s:58-61`), not by a call, so a phase on `P_MobjThinker`
itself saw 0 calls: a call log must key on the call to the trampoline,
or on "entry reached with a fresh return address".

## 4. The bridge

### 4.1 Layers

| Layer | Source | Owner |
| --- | --- | --- |
| Symbols | `build/linkmap.json` (units and labels, `.equ` constants included) | generated |
| Upstream layouts | `offsets.inc`, `lists.inc`, `memmap.inc`, `info.inc` | parsed at run time |
| Schema | field types (fixed, int16, byte, far pointer, state pointer, thinker function), pointer target kinds, excluded fields with a reason each | hand-written, reviewed; about 300 lines for the game state (assumed) |
| Object tables | bases and counts from the level globals (`_g_numsectors`, `_g_sectors`, ...), the pool, secnode pools found by walking the touching lists | derived per dump |
| Canonical model | objects by identity, pointers as `(kind, identity, field offset)`, lists as identity sequences | bridge |
| Port layout | a manifest from the port's build | the port |

### 4.2 Identity

| Object | Identity |
| --- | --- |
| Sector, line, side, subsector, seg, node, block cell | array index |
| Pooled mobj | pool slot. The port should keep upstream's policy, the free slot with the highest index (`p_spawn65.s:275-297`, `:1250-1262`), so slots match; it costs one bitmap scan, as upstream. |
| Zone mobj, special thinker | its position in the thinker list among objects of its kind |
| Secnode | the order of first reach from the mobjs' touching lists, then the sectors' (address order works on the reference alone) |
| State, mobj type, sprite | number |
| Thinker function | a symbolic kind (`P_MobjThinker`, `T_Glow`, remover, none) |

**Order is state.** The thinker order decides the order of `P_Random`
calls; the sector thing lists and block chains decide which thing a
search meets first. The bridge compares these lists as sequences, not
sets.

### 4.3 The port's layout manifest (proposed)

The port's build writes a JSON manifest next to its ca65 debug file:
for each structure, its storage (array of records or one array per
field, with byte planes allowed), its bank and address (main, aux, a
RamWorks bank), the encoding of each field (width, signedness, split
bytes), and the encoding of each handle (index width, null value, the
table it indexes). The bridge's port reader and writer are driven by it,
so a layout change in the port needs no bridge change. `a2vm_load.py`
is a hand-coded instance of one entry.

### 4.4 Excluded or re-derived state

| Field | Why | Rule |
| --- | --- | --- |
| `validcount` (`p_map65.s:303`), `sector.validcount`, `line.validcount` | Epoch stamps. The renderer also increments `validcount` once a frame (`r_frame65.s:285`) and stamps sectors (`r_bsp65.s:734-736`). | Compare only in lockstep-schedule mode (section 6.3). Otherwise compare "equals the current `validcount`" |
| `line.r_validcount`, `line.r_flags` (`ML_MAPPED`, `RF_*`) | Written by the renderer (`r_wall65.s:360-364`) | Frame level only |
| mobj byte 11, the high byte of the thinker function | Upstream's kind cache (`p_tick65.s:106-117`) | Excluded |
| `mobj.sightline`, `SIGHTHINT` (`$0A:0000`) | Sight caches that upstream says do not change results (`p_sight65.s:88-93`) | Excluded; the claim is checked by routine tests of `P_CheckSight` |
| Pointer values, pad bytes | Layout | Compared as handles |
| Tables of bank `$21`, `$0A-$0C`, the respawn copy | Derived at level load | Compared once per level if the port keeps them |
| Code banks | Self-modified code | Never compared |
| Interrupt state (music `$00:BD00`, DOC, ADB queues) | Asynchronous | Excluded; inputs enter through the tic command stream |

`validcount` is 16 bits. It rose by 31 over 4 tics and 1 frame of the
demo (measured). Corrected after review: over the demo it rises about
23.3 a tic (742 at leveltime 73, 40,157 at leveltime 1,765; measured by
the review's `late.py`), so it wraps about every 2,800 tics (80 s of
play). Line stamps are 0 after level load (`p_setup65.s:386-388`), so
when `validcount` wraps to 0 every line not stamped since the load counts
as checked for that search; other stale stamps can also match. Upstream's results therefore depend, very rarely, on
the number of frames drawn. A port that counts exactly as upstream
reproduces this in lockstep-schedule mode; in free-running mode it is a
known source of legitimate divergence.

## 5. Level 1: routine tests

### 5.1 Protocol

1. **Capture on the reference.** For routine R, for chosen calls (the
   Nth, every Kth, those inside a note window), record the full memory
   at entry and the call's footprint: entry registers, each byte read
   before it is written (first value), each byte written (last value),
   exit registers. Entry memory plus the written bytes is exactly the
   exit memory, so one dump per call is enough.
2. **Convert.** The bridge turns the entry state into the port's layout
   (whole objects, not only the footprint) and the arguments from
   upstream's convention (C or X:C, `_Dp[0-7]` at `$00:0900`,
   `iigs-platform.md` section 3) into the port's.
3. **Run the port routine on a2vm**: `--image` with the port code and
   the converted state, registers by `--reg`, a return address on the
   stack pointing at a `--stop-pc` trap, `--final-snapshot`. Run under
   both cost profiles; the cycle count of each call is a per-routine
   budget number for free.
4. **Compare.** The canonical objects and fields covered by the
   reference's write footprint must be equal. Everything else must be
   unchanged, except scratch areas the manifest declares ("no stray
   writes").

Pure functions (fixed-point, angles, tables) need no state: they are run
on the reference with chosen inputs and compared on millions of random
and edge inputs (section 8).

### 5.2 What ref816 must add

| Addition | Why | Size (assumed) |
| --- | --- | --- |
| `--dump-at ADDR[:N\|all]` with `--dump-banks LIST` and a stream output (file or pipe), each dump with its hit number, cycles and gametic | One run gives every tic or frame state; the two-run method costs a rerun per state (0.7-1.6 s measured; about 1.8 h for the 2,134 tics of demo3, assumed) | 100 lines of C |
| `--call-log ENTRY[:FIRST:COUNT]`: per call, entry and exit registers, first-read and last-written bytes aggregated in the machine (program, stack below the entry S, I/O and code-bank writes apart), nested calls to listed entries as sub-events; calls through `callFn` and other `JML [dp]` sites counted as calls | Samples are 202 bytes an instruction (measured): 75 MB a frame | 200 lines, reusing the trace's call detection |
| `--call ENTRY` with a list of register and memory settings, from a stopped state, each call run to its return | Pure-function tests on the reference's own routines, tables built at boot | 100 lines |
| `--poke-file ADDR:FILE` at a frame of the input program | Inject demo lumps (section 6.2) | 30 lines |
| `--serve` (later): commands on stdin (run to an entry, peek, dump, poke) | Interactive lockstep with a2vm without reruns | 150 lines |

What exists and is enough for now: `--mark`, `--marks`, `--cycles`,
`--stop-pc`, `--dump-ram`, `--peek`, `--trace-phase` with
`--trace-samples` and `--trace-sample-every 1` (the latter two are in
the working tree of `tools/ref816/main.c`; the built binary accepts
them, measured).

### 5.3 What a2vm must add

| Addition | Why |
| --- | --- |
| Snapshots of chosen ranges at each boundary (`--snapshot-ranges`) | A full snapshot is 8.4 MB; per tic the game state is a few hundred KB |
| A write log option on the command line (the harness hook `write_hook` exists, `tools/a2vm/README.md`) | Stray-write detection in routine tests |
| An AY register write log for the Phasor | Sound tests (section 9) |

### 5.4 First routines to test

| Group | Routines | Why first |
| --- | --- | --- |
| Arithmetic | `FixedMul`, `FixedMul3216`, `FixedMulAngle`, `FixedDiv`, `FixedApproxDiv`, `FixedReciprocal*`, `P_AproxDistance`, `R_PointToAngle3`, `finesine`, `finecosine`, the 16- and 32-bit division and modulo | Pure; every later test depends on them |
| Game | `P_Random`, `P_SetMobjState`, `P_MobjThinker`, `P_XYMovement`, `P_ZMovement`, `P_TryMove`, `P_CheckPosition`, `P_CheckSight`, `P_LineAttack`, `A_Chase`, specials | Each tic is made of them |
| Renderer | `R_RenderBSPNode` sub-walks, `R_StoreWallRange`, `R_RenderSegLoop`, `R_ProjectSprite`, `R_DrawSprite`, `recAlloc`/`newPage`/`flush` | Their outputs are the records |
| Replay | the column drawers of `R_DrawLists` | Fed with reference records (section 7.2) |

## 6. Level 2: game state after each tic

### 6.1 The boundary

The state is compared at each entry of `G_Ticker` (`g_game65.s:563`):
the tic before is complete and the next has not begun. `P_Ticker` is
not a good boundary, because it is skipped while the menu pauses the
game (`p_think65.s:185-192`). The release is built with `TICSTEP` 1 and
`MAXTICS` 4 (measured: no `worldAt`, `ticRun` or `P_WorldRuns` in the
link map; read: `tics.inc:9-12`, upstream `Makefile:23`), so every tic
runs the whole world, as in Doom.

### 6.2 Inputs

The port's input layer (an //e keyboard) differs from the IIgs's ADB, so
the tic harness bypasses it:

| Input | From the reference | Into the port |
| --- | --- | --- |
| Demo | the DEMO3 lump (`readDemoTiccmd`) | the same lump, through the port's demo playback |
| Scripted play | `player.cmd` at each `P_Ticker` entry (after `G_Ticker` copied it from the ring, `g_game65.s:591-601`) | a synthetic demo, or written into the port's command slot by the harness |
| Events between tics (cheats, menu actions, the tour's `poke`) | a call log of the event handlers (`G_Responder`, the cheat and menu routines) and the script's pokes, each with the tic it preceded | the same calls or pokes at the same tic |
| Other demos | DEMO1 (E1M5) and DEMO2 (E1M3) of `DOOM1.WAD` (measured headers), or generated tic streams, poked over the DEMO3 lump (8,550 B, so up to about 2,130 tics) | the same lump |

The reference is the truth: whether a stock demo stays in sync with
vanilla Doom on upstream does not matter, only that the port does what
upstream does with the same tic stream. Random and generated tic streams
are therefore valid tests.

### 6.3 Schedule modes

| Mode | Tics per frame | What is compared |
| --- | --- | --- |
| Lockstep schedule | the reference's (from the marks: `_g_gametic` at each `R_RenderPlayerView`) | everything in section 4, stamps included |
| Free-running | the port's own | game state without stamps and render fields |

The coverage runs use the first; the soak runs the second.

### 6.4 Volume and time

- Per tic: bank `$02` plus the zone banks `$06-$09`, 320 KB. Demo3:
  2,134 tics, about 683 MB streamed, not stored (assumed from the
  sizes).
- Decoding: 16-83 ms a dump in Python, 35 ms typical (measured; mostly
  reading 8.5 MB), so about 150 s for both sides of demo3 (assumed
  from the rate). The reference itself runs the demo in a few seconds (measured: 262
  million cycles in 0.84 s).
- On a divergence at tic t: inject the reference state of tic t-1 into
  the port, run one tic, compare (this confirms the tic); then call-log
  the thinker calls, `P_PlayerThink` and `P_UpdateSpecials` of that tic
  on the reference and run each in routine mode to find the first
  routine that differs.

### 6.5 Coverage

| Source | Tics (assumed) | Covers |
| --- | ---: | --- |
| `title.script`, demo3 | 2,134 | E1M7, monsters, shotgun pickup, doors |
| `newgame.script` | a few hundred | E1M1 start, moves, fire, door |
| `tour.script` | about 175 a map | every map's load and start, cheats, secret exit |
| Stock DEMO1 and DEMO2 injected | about 1,000-2,000 each (not measured) | E1M5, E1M3 |
| Generated streams | any | fuzzing of movement and combat |

## 7. Level 3: each frame

### 7.1 Inputs and outputs of a frame

Inputs, at `R_RenderPlayerView` entry (`r_frame65.s:117`): the game
state, the view size and detail, `extralight` and the fixed colormap,
and the renderer's own persistent state: fill spans and their stamps,
covered ranges, the weapon skip, the vertex angle cache and its stamps,
the fuzz position, `rndindex` (the status bar face calls `M_Random`,
`st_stuff65.s:432`) and the screen itself (the fill spans reuse what the
frame before drew; the fuzz drawer reads the screen).

Outputs, at three points:

| Point | Compared |
| --- | --- |
| `R_DrawLists` entry (`r_list65.s:550`) | the records of each column in list order, decoded: kind, rows, fill bytes, texture position and step, texel source as (texture or sprite lump, column, offset), colormap as a light index, fuzz count and position, overlay pixels; also drawsegs, vissprites, fill spans, covered ranges, weapon skip. `K_NEXT` records are layout and dropped. Early flushes (`flush`, `r_list65.s:272-323`) are captured by a call log. |
| After `R_DrawLists` | the SHR bytes of the view |
| `I_FinishUpdate` return (`i_viigs65.s:329`) | the whole screen: `$E1:2000-$9CFF`, the SCBs and the palettes, against a2vm's aux bank 0 `$2000-$9FFF` |

### 7.2 Isolating the replay

The replay is hand-written and is 34% to 42% of the reference's cycles
(`docs/PROFILE.md`), so it gets its own test: the reference's records,
converted, are loaded into the port's record area with the reference's
screen and span state, the port replay runs, and its SHR bytes must
equal the reference's after `R_DrawLists`. A record-level difference
and a replay difference are then never confused.

### 7.3 Volume

Per frame: bank `$1D` (64 KB), `$02` (64 KB), the screen (32 KB), the
span tables (3 KB): about 160 KB at 3 points, 480 KB a frame. Demo3
at 4 tics a frame (measured in the series: 24 tics every 6 frames) is
about 534 frames, 256 MB streamed (assumed).

Default tolerance is none. A deliberate change in renderer arithmetic
(section 8.2) needs a written waiver that names the routine and the
allowed pixel difference, and the frame check then reports the
differing bytes per frame instead of failing.

## 8. Arithmetic to reproduce bit for bit

### 8.1 Game logic: needed for demo sync

| Item | Where (read) | What exactly |
| --- | --- | --- |
| `P_Random`: 256-byte table, byte index | `m_random65.s:9-46` | Doom's table; index wraps at 256. `M_Random` has its own index. `P_Random` is called only from `p_*.s` (measured by grep), so it never depends on frames |
| `FixedMul` | `m_fixed65.s:425-437` | Exact: the floor of a x b / 65536, modulo 2^32, built from quarter-square tables. Any exact 65C02 method is acceptable |
| `FixedMul3216`, `FixedMulAngle` | `m_fixed65.s:517-518`; `p_mobj65.s:1205-1213` | Defined on the low word of b (minus a when b < 0): equal to `FixedMul` only when b is in -65536..65535. Reproduce the truncation, not `FixedMul` |
| `FixedDiv` of `P_PathTraverse` | `p_trace65.s:237`, `:398-404` | C's `FixedDiv` of `p_maputl.c` with its guards |
| `FixedApproxDiv`, `FixedReciprocal`, `FixedReciprocalSmall`, `FixedReciprocalBig` | `r_iigs65.s:546-560`; `m_recip65.s:1-10`, `:270-312` | 16 significant bits: normalise, index `RECIP_TABLE` (32,768 words, floor((2^31 - 1) / (32768 + i)), `tools/gentables.py`), shift. Used by `p_doors65.s`, `p_attack65.s`, `p_map65.s`, `p_path65.s`, `p_sight65.s`, `p_trace65.s` (measured by grep). The whole approximation, table included |
| `P_AproxDistance` | `p_path65.s:105-113` | dx + dy - min / 2 with its rounding (`m - (m >> 1)`) |
| `R_PointToAngle3` (the game's `R_PointToAngle2`) | `r_iigs65.s:914-925` | `SlopeDiv` and `tantoangleTable` (2,049 longs, `r_iigs65.s:1144`); slow path through the 32-bit division |
| `finesine`, `finecosine` | `tables65.s:1-23`; upstream `tools/gensine.py` | Two full 8,192-entry tables of Doom8088's values with their corrections; `finecosine` is not `finesine` shifted. Test all 16,384 entries |
| Sight side tests | `p_sight65.s:1-6`, `:699-700`, `:1448`; `LOGTAB` (`tools/gentables.py`) | Products of whole parts of coordinates; a log-table fast path that upstream says decides only when safe. Reproduce the whole-part semantics; check the fast path by routine tests |
| 16- and 32-bit division and modulo | vendor runtime `cal_integer.s`: `_UDivMod16` (5 call sites in game code), `_UDivMod32` (4), `_Mod16` (4), `_Div32` (3), `_Div16` (2) (measured by grep of `long:` calls in `p_*.s` and `g_game65.s`) | Written from C semantics only (ground rule): truncation toward zero, remainder with the dividend's sign (assumed standard C). Division by zero: see question 3 |
| 16-bit products `IIGS_MulLo16`, `umul16` | `m_fixed65.s` | Exact |
| Two's complement wrap of fixed and angle values; arithmetic right shifts of negative values | everywhere | Exact |
| List orders, pool policy, `validcount` counting | sections 4.2, 4.4 | Behaviour, not arithmetic, but just as binding |

### 8.2 Renderer: needed for frame equality only

| Item | Where (read) |
| --- | --- |
| `qmulh`: the high word from the high words of the quarter squares, "+0 or 1 in the last bit" | `r_wall65.s:1781-1786`; used at `r_wall65.s:267-297`, `:1068-1075`, `r_thing65.s:450-459`, `:1002-1058` |
| Scales without division through `RECIP_TABLE` (`scaleFast`) | `r_wall65.s:1035-1047` (per `research/iigs-renderer.md` section 5) |
| `FSTEP_TABLE`, texture step below scale 1.0 | `m_recip65.s:355-396`; `r_seg65.s:1926-1943` |
| Log-table BSP side tests | `r_bsp65.s:1237-1311` |
| `R_PointToAngle16` and the vertex angle cache | `r_iigs65.s:10-20`; `r_bsp65.s:12-15`, `:114-134` |
| Sprite scale tables | `r_thing65.s:32-38` |
| `finesineapprox` (quarter table; also stereo in `s_sound65.s`) | `tables65.s:40-53` |
| Light: `DLIGHT`, `SMAP`, `CMO`, `PCMO`, `PGT`, `PLANE_D` | `r_seg65.s:98-111`; `r_bsp65.s:41-43`, `:960-1040` |
| Colormaps built per level, 7.8 texture positions in records | `i_viigs65.s:1068-1080`; `lists.inc:40-52` |
| `M_Random` for the status bar face | `st_stuff65.s:432` |

Replacing one of these with a faster or more exact method is allowed
by the owner's direction but breaks frame equality; do it only with a
waiver (section 7.3), after the exact version has passed.

## 9. Sound and music

- **Sound effects.** Upstream's `S_StartSound` calls (sound, origin,
  tic) are observable behaviour. Compare the event stream per tic by a
  call log on the reference against the port's calls; the Phasor
  rendering itself has no reference.
- **Music.** The owner's direction is MUS lumps played on the Phasor,
  not upstream's Ensoniq song units, so the reference has nothing to
  compare with. Verify the MUS parser against a host decoder (standard
  library Python) as an event list in MUS ticks (140 a second, assumed
  from the MUS format), and the AY register writes (a2vm log, section
  5.3) against a host model of the port's instrument mapping.

## 10. Work breakdown

| Step | Deliverable | Test |
| --- | --- | --- |
| 1 | ref816: `--dump-at` with bank lists and a stream | two runs give the same stream; a dump equals the two-run method's |
| 2 | Bridge: schema for all of section 2, canonical model, upstream reader and writer | reader-writer round trip is byte-exact except the excluded fields, on all coverage dumps |
| 3 | ref816: `--call-log`, `--call`, `--poke-file` | footprints equal those from full samples on a window |
| 4 | Port manifest format and the bridge's port reader and writer; a2vm range snapshots | round trip reference to port to reference |
| 5 | Level 1 harness and the arithmetic tests | the port's arithmetic routines equal the reference on random and edge inputs |
| 6 | Level 2 harness: demo3 in lockstep-schedule mode | stops at the first differing tic with a diff report |
| 7 | Level 3 harness: records, isolated replay, SHR | demo3 frames |

## 11. Questions for the owner

1. Should the tic harness also run in free-running mode as a release
   gate, accepting the rare `validcount` wrap differences, or only in
   lockstep-schedule mode?
2. Must renderer arithmetic stay exact (frame equality), or may the
   port trade `qmulh`-style exactness for speed with a pixel budget?
3. The ground rules forbid reading `cal_integer.s`. May the port's
   division be checked against the vendor routine as a black box on
   the reference (its outputs only), for example for division by zero,
   which the C standard leaves undefined?
4. Should `docs/PROFILE.md`, `docs/MILESTONES.md` and
   `coverage/title.script` be corrected from E1M3 to E1M7 for the title
   demo? I did not edit them.
