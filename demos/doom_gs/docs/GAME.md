# Milestone 10: the game logic

Status: design, 2026-10-01, revised the same day after an adversarial
review (section 7 lists each finding, what was applied and what was
rejected; each correction is marked "(review N)" in the text), for the
builders of milestone 10: one skeleton stage, then 29 parts in 6 waves
built in parallel (at most 5 a wave), then the integration. The skeleton
stage is built ("Skeleton as built", before appendix A: what was built,
its sizes, its deviations from this design, checkpoint S), and wave 1's
five parts are built and integrated ("Wave 1 as integrated").
It follows
[`LEVELS.md`](LEVELS.md) (milestone 9: the level load, the native
`P_SetupLevel`, the game core and the zone, built and verified),
[`RENDER.md`](RENDER.md) and [`RENDER-MASKED.md`](RENDER-MASKED.md)
(milestones 7 and 8: the whole renderer), [`MEMORY_MAP.md`](MEMORY_MAP.md)
and [`NATIVE.md`](NATIVE.md) sections 3.2, 6, 10, 11, 13 (row 10), 14
and 15.1.

The milestone, as the task that ordered this design states it:

> Milestone 10: all game logic natively, in demo sync with ref816: the tic
> loop (G_Ticker, demo ticcmds, P_Ticker and the thinkers), mobjs
> (P_MobjThinker, states, P_XYMovement, P_ZMovement, P_SetMobjState,
> removal, missiles, puffs and blood), the map code (P_CheckPosition,
> P_TryMove, the blockmap iterators, P_SlideMove, P_ChangeSector,
> P_PathTraverse and the intercepts, P_AimLineAttack, P_LineAttack,
> P_UseLines, P_RadiusAttack, teleport moves), sight and sound
> (P_CheckSight with the sight tables, P_NoiseAlert and P_RecursiveSound),
> the monsters' AI and actions for episode 1, the player (P_PlayerThink,
> movement, view height, death), weapons and psprites, interaction
> (P_TouchSpecialThing, the gives, P_DamageMobj, P_KillMobj), the world
> (doors, platforms, floors, ceilings, stairs, lights, switches and
> buttons, line and sector specials, P_UpdateSpecials, level exits) and
> the game flow game-side (G_DoLoadLevel through milestone 9's setup,
> completion, reborn; screens are milestone 11's), lockstep-schedule
> mode, and the joined validcount.
>
> Acceptance: (1) demo3, lockstep-schedule mode, with a new script that
> runs to the demo's end: game state equal after every one of its 2,134
> tics; (2) newgame and tour as tic streams: equal every tic; (3) DEMO1
> (E1M5, 5,026 tics) and DEMO2 (E1M3, 3,836 tics) placed by ref816's lump
> option: equal every tic; (4) 10 generated tic streams of 2,000 tics
> (varied: movement, fire, use, weapon changes, strafing, running, deaths
> and reborns): equal every tic; (5) demo3 rendered natively in the same
> build: record stream and SHR equal every frame; (6) P_PathTraverse on
> long, dense traces (over 64 intercepts) by --call: equal; plus
> milestone 9's gates (one validcount; a zone mobj created, LS_ZONE, no
> slot handed out twice; the block walk's order checked on every move;
> bank $21's tables). Report: a2vm time per tic (f121 and fastpath;
> median, p99, worst) by subsystem, replacing NATIVE.md 6's estimated
> tics in the renderer's FPS figures (RENDER-MASKED.md 6.2), and the code
> and bank sizes against MEMORY_MAP.

**Binding decisions** (`NATIVE.md` 15.1): the release is gated on
lockstep-schedule mode, and the port fixes the `validcount` wrap with
upstream's behaviour behind a build option that every lockstep and test
build uses (row 4); our own divides, with our own result for a division
by zero, reported as a known divergence if a run divides by zero (row 5);
a column seen from behind is a known difference, skipped and reported by
name (row 13); renderer arithmetic stays exact (row 3); 6 FPS minimum on
F1.2.1 (row 7); 126 RamWorks banks (row 8).

**Labels**, as in `NATIVE.md`:

- **[M: source]** measured. `CG`, `HEAT`, `CALLS`, `VC`, `POOL`, `THK`
  are the read-only measurements made for this design (appendix A);
  `M7`, `M8`, `M9` are `RENDER.md`, `RENDER-MASKED.md` and `LEVELS.md`
  "as built"; `PROFILE` is `PROFILE.md`.
- **[R file:line]** read there. Upstream files are in
  `build/upstream/src/iigs/`; nothing is read from or derived from its
  `cal_integer.s` (the divides are `src/native/MATH.md`'s own).
- **[A]** assumed, or arithmetic on labelled numbers.

## 0. Summary

| Question | Answer |
| --- | --- |
| What is ported | Every routine of upstream's game units that a game tic can reach, 43,074 bytes of 65816 code in 29 parts [M: CG], on top of milestone 9's game core (`gthink.s`, `gpos.s`, `gspawn.s`, `gweap.s`, `gspec.s`, `gvalid.s`: 5,260 B native [M: M9]) and milestone 6's math. Out, by name: setup-only code (milestone 9), the main loop's display, input, saves, menus and the 2D tickers' drawing (milestone 11), and upstream's dead path guard (1,284 B, never called in the release [R `p_path65.s:612-613`]). Section 0.1 |
| How it is compared | Routine by routine (each part's checkpoint: captured calls from `ref816`, injected through the bridge into poisoned machines, compared exactly, as milestones 7-9 did), then tic by tic in lockstep-schedule mode: the native build runs the reference's tics per frame (4 in every frame of all three demos [M: CALLS]) and the native renderer's front end between them, and its canonical state at every `G_Ticker` entry equals `ref816`'s, with the exclusions of 3.6 named and reasoned |
| The layouts | Milestone 9's mobj (the render part `RTHING` and three game groups of 24 B at one address in four banks) with the thinker walk's fields moved to a plane bank that the tic phase holds in W; specials in per-kind free lists; the sight caches kept as state (upstream's `CS_PREV` skips `validcount++`: it is not a cache [R `p_sight65.s:138-147`]); the bank `$21` tables replaced by two small level tables in `LVS`; an object API with write-back caches so that no part touches the far layer directly. Section 1 |
| The parts | 29, each one engineer's 1.5 hours, sized 593 to 2,738 upstream bytes; every routine has one owner; a part's direct callees are built by an earlier wave, by milestone 9 or by the part itself; indirect calls (state actions, thinker functions, iterator callbacks, traversers, line specials) go through generated tables, as upstream's own `JML [dp]` and `jsr (spectab+2,x)` do. Six waves (5, 5, 5, 5, 5, 4 parts): the longest chain of direct calls runs through six parts (`P_MobjThinker` calls `P_XYMovement`, which calls `P_TryMove`, which calls `P_CheckPosition`, which calls `P_DamageMobj`, which calls `P_SetMobjState`) [M: CG]. Section 2 |
| The skeleton | Before the waves: the layouts module and generated includes, `game.mk` with a fragment per part, the object API, code paging, the dispatch tables, the native driver with lockstep-schedule mode and the load-phase protocol, the joined `validcount`, milestone 9's game core moved to the final layouts (and its acceptance run again), the routine-mode and tic-level harnesses, the tic streams and the stream generator, a request file per part. Section 3 |
| Code placement | F1.2.1: the tic phase loads a core image into W each frame and pages cold routine groups into two slots of W through a far-call stub; placement is data (a table from measured heat and the call graph), so moving a routine between core and a slot changes no part's source. The game's hot set is 22,092 upstream bytes for 99% of demo3's game instructions [M: HEAT], more than W's code room (about 18 KB [A], 4.2): paging in fights, and the main card's bank 2 as a measured option. Section 4 |
| Integration and acceptance | After each wave: every built part's checkpoint again (newly eligible calls included); after wave 6: the six acceptance runs and the gates, about 25-35 minutes at 9 jobs [A], the timing report by subsystem and the new FPS figures. Section 5 |
| Main risks | W fit and far access (`P_TryMove` 11 a tic median, 32 at p99, 51 at most in demo3 [M: CALLS]); upstream's state-changing shortcuts (`CS_PREV`, `mvNodes`, the early traversal) that must be reproduced; the address-keyed sight hint, which no port can key as upstream after a level change; the volume (43 KB under a bit-exact contract). Section 6 |

### 0.1 Scope

| Upstream | Bytes [M: CG] | Native in |
| --- | ---: | --- |
| The 29 parts' routines (section 2): `p_*.s` but setup, `g_game65.s`'s tic, flow and demo code, `m_cheat65.s`'s effects | 43,074 | Milestone 10 |
| `wi_stuff65.s`'s ticker logic (`WI_Start`, `WI_End`, `WI_Ticker`, `WI_checkForAccelerate`, the counts [R `wi_stuff65.s:206-585`]), `HU_Ticker`'s message clear [R `hu_stuff65.s:244-274`], `ST_Ticker`'s `M_Random` call [R `st_stuff65.s:432`] | about 450 [A] | Milestone 10 (part `flow`): they change canonical state or the gametic of a load; their drawing is milestone 11's |
| Milestone 9's game core: `P_SpawnMapThing`, `P_SpawnMobj`, `newMobj`, the pool, `P_SetThingPosition`, `P_CreateSecNodeList` and its walk, the thinker list's add, `P_SpawnSpecials` and the light spawners, `G_PlayerReborn`, `P_SetupPsprites`, `setPsprite`, `A_Raise` | 4,876 | Milestone 9, extended by the skeleton (3.1: the general z of `P_SpawnMobj`, the full action table of `setPsprite`, the final layouts) |
| `P_Random`, `M_Random`, `P_AproxDistance`, `FixedMulAngle` | 169 | Milestone 6 (`math.s`) |
| Setup-only: `p_setup65.s`, `P_InitSightTables`, `P_InitSightLogs`, `P_InitFlood`, `P_InitSwitchList`, `P_InitPicAnims`, `P_LoadTexture`, `P_InitBlockRows`, `sqmInit` | 2,962 + part of the above | Milestone 9 (or dropped there) |
| The path guard: `guardL`, `gRun`, `gBlk`, `gBlockL`, `gBlockW`, `gCheck`, `gNewId`, `gwMiss`, `gwList`, `gBlockT` | 1,284 | None: `early` branches over its only call (`bra 4$`, "no guard (decision 34)" [R `p_path65.s:612-614`]), so the release never runs it |
| `d_main65.s` but the tic (the display, `tryRunTics`, the title loop), `G_BuildTiccmd` and its helpers, `G_Responder`, the saves, `P_SwitchWeapon` and the weapon cycling (called only by `G_BuildTiccmd`) | 3,126 | Milestone 11 (input, main loop, screens, saves). Lockstep-schedule mode replaces the main loop in every test build (3.6) |
| Sound: `S_StartSound`, `S_StartSound2`, `S_StopSound` | | A hook that records the event (sound, origin) in test builds; milestones S4 and 11 |
| Zone: `Z_MallocLevel`, `Z_CallocLevel`, `Z_CallocLevSpec`, `Z_Free` | | The native pools (milestone 9's `gthink.s`, free lists by the skeleton) |
| `R_GetTexture` (textures made in play), `R_CheckTextureNumForName` | | None: every texture is resident [R `LEVELS.md` 1.2]; the switch and animation tables are in `GTAB` |
| `P_UpdateAnimatedFlat` (`r_data65.s`) | | Part `secfind`: `NUKAGE` of the frame block |
| `AM_Stop`, `ST_Start`, `HU_Start`, `AM_Ticker`, `F_Ticker`, `D_PageTicker`, `F_LoadScreen` (`doWorldDone` [R `g_game65.s:877`]), `Z_CheckHeap` (`doLoadLevel` [R `:659`]), `D_AdvanceDemo` (`G_CheckDemoStatus` [R `:1386`]), `W_StartInter`'s pictures and music (its `musInter` ends in `WI_Start` [R `w_level65.s:621-624`], which is `flow`'s), `W_StartFinale` (`victory` [R `g_game65.s:640`]), the finale | | Hooks; milestone 11 (no acceptance run reaches the finale: the generated streams start at E1M1-E1M9 and never take E1M8's exit, 3.7). `W_StartFinale` and `F_Ticker` are stops (`GS_FINALE`) (review 9) |
| `I_GetTime` (`doPlayDemo`'s `starttime` [R `g_game65.s:1270-1272`], `G_CheckDemoStatus`'s timing) | | A hook: in test builds the value comes from the tic stream (3.7), the reference's at that call; the platform clock in the release (milestone 11) (review 7) |
| `linkRemove`, `addIfFunc` (`r_list65.s:919-943`: a mobj with no function is put on the thinker list just before its removal, so the delayed free runs [R `p_spawn65.s:361`]) | 39 | `linkRemove`: part `mobjstate`; `addIfFunc`: milestone 9's spawn, which the skeleton checks (S2) (review 9) |
| `P_SetSeclist` [R `p_map65.s:3025`] | | None: no unit calls it (its two uses are inline [R `p_map65.s:729`, `:896`]) |

### 0.2 Ground rules for this milestone

From `MILESTONES.md` "Ground rules" and the task: the directory is GPL-2
and code rewritten from upstream is committed here, but no upstream file
is copied, and nothing is read from or derived from upstream's
`src/iigs/cal_integer.s`; C11 and standard-library Python only (3.9 to
3.14); no build warnings; tests in `tests/` skip with a clear message when
`build/` lacks what they need, and run with `python3 -m unittest discover
-s tests`, the reference command, or `python3 tools/testpar.py`, the fast
way with the same results that the ground rules adopted on 2026-10-01 (9
processes, shared builds made first, the modules that rewrite shared files
kept apart by the race table of `tests/README.md`); no test is weakened and no address, tic, frame or map is
special-cased; every run has a time limit and every output a size limit
(`tools/ref816/bounded.py`, `tests/support.run`); temporary output is
deleted after the run; `df -h /System/Volumes/Data` before any run that
writes more than 100 MB, stop below 20 GB free; `build/` growth for this
milestone under 8 GB, reported by each stage; no `git add`, commit or
push by the builders. The WAD, the release and anything made from them
stay in `build/`. `tools/sound`, `src/sound` and `tests/test_sound_*` are
not touched. **Resources**: up to 9 parallel jobs at normal priority (the
owner's 2026-10-01 decision). The owner tests on the card at milestone
12; milestones 7 to 12 are built and verified on a2vm and against
`ref816` only.

### 0.3 What the sources change in the task's plan

| # | Fact | Consequence |
| --: | --- | --- |
| 1 | **The direct call graph is a DAG.** Of the game units' 634 routines with code, only 4 strongly connected groups of 2-5 routines, each inside one module [M: CG]. Every cycle of the game's calls goes through a function pointer: a state's action (`callFn`, `callAction`: `JML [FN_P]`, `JML [ACT_JMP]` [R `p_tick65.s:533`, `p_pspr65.s:118`]), a thinker's function (the walk's `call` [R `p_tick65.s:303-317`]), a block iterator's callback (`callLN`, `callLN2` [R `p_map65.s:2786`, `:2869`]), a traverser (`callTrav` [R `p_path65.s:816`]) or a line special (`jsr (spectab+2,x)` [R `p_switch65.s:452-455`, `:564-600`]) | Waves are possible: those five dispatches are generated tables whose entries later parts fill (2.2); a part's direct callees are always earlier |
| 2 | **`P_CheckSight`'s "same pair" answer is state.** A call with the same `t1, t2` as the last one returns the last answer, without the walk and without `validcount++`, whatever moved since [R `p_sight65.s:138-147`, `:212`] | `CS_PREV1`, `CS_PREV2`, `CS_PREVR` are kept natively as handles and compared (milestone 9 listed them as caches not kept [R `LEVELS.md` 5.2 exclusion 4]) |
| 3 | **The sight hint is keyed by the mobj's address.** `SIGHTHINT` is a 32 KB table indexed by `(address >> 2) & $7FFE` of `t1`, never cleared, and its line is tested first, through the same seg code that stamps lines with `validcount` [R `p_sight65.s:88-94`, `:304-352`, `:610-620`]. Upstream's pool base moves with the zone's history: `$06:2590` for E1M1, `$08:0010` for E1M3, `$09:0010` and `$07:0010` for two loads of E1M6 [M: POOL] | The answer does not depend on the hint (a blocking line blocks in any order [R `p_sight65.s:88-93`]), but the line stamps and `mobj.sightline` do. Natively the hint is a plane by pool slot: exact within a map and across loads whose pool base stays, not after a load that moves it. The tic comparison names that window (3.6, exclusion T3) |
| 4 | **Upstream's shortcuts are not stamp-preserving.** `mvNodes` does "the rest that `P_CreateSecNodeList` leaves: `validcount++`, no list" without the walk [R `p_map65.s:857-892`]; the line record of the check walk is reused by the next `PIT_GetSectors` walk: with `LR_USE` set, `lineBlocks` mode 1 calls only `getSectors` on `LR_LINES`, with no block walk and no line stamped [R `p_map65.s:893-895`, `:1700-1726`]; the early traversal of `P_PathTraverse` stops collecting when `trav` says false [R `p_path65.s:178-183`] | Each is reproduced as upstream does it: the line stamps and `validcount` are compared every tic. The line record (`LR_OK`, `LR_USE`, `LR_N`, `LR_LINES`) gets a native place and is compared (1.5); `checkpos` writes it, `trymove`'s `mvNodes` sets `LR_USE`, and milestone 9's `gp_secnodes` gains the `LR_USE` path from the skeleton (3.1), which milestone 9 built without (it always walks and stamps [R `src/native/gpos.s:442-760`]) (review 5) |
| 5 | **The reference runs 4 tics a frame** in every frame of demo3 (533), DEMO1 (1,257) and DEMO2 (959) [M: CALLS] | Lockstep-schedule mode reads the schedule from a file anyway (3.6); in the three demos it is 4, 4, 4, ... |
| 6 | **The work of a tic** in demo3: `P_TryMove` 12.0 a tic on average (median 11, p99 32, most 51), `P_CheckSight` 4.8 (5, 11, 17), `P_PathTraverse` 0.5 (0, 8, 13), `A_Chase` 6.1, `A_Look` 5.3; DEMO1 `P_CheckSight` 6.3 a tic, `P_PathTraverse` 1.1 [M: CALLS, VC] | Far access per move decides the tic time on F1.2.1 (section 6, risk 1): the object API caches records in fast memory (1.1) |
| 7 | **The hot set** is 139 routines, 22,092 upstream bytes, for 99% of the game's instructions in 40 frames of demo3; 316 routines, 33,397 B, ran at all; standing still 45 routines, 6,797 B [M: HEAT]. Four parts take 79%: `sight` 40.4%, `tic` 24.0%, `checkpos` 8.8%, `look` 5.7% [M: HEAT] | W cannot hold the hot set with the tic data (4.2): placement is measured, not guessed |
| 8 | **The thinkers**: at setup 211 in demo3 (101 full, 90 brainless, 20 lights and scrollers), 335 in E1M6 at UV [M: THK] | The walk's fields live in W during the tic phase (1.3) rather than a far fetch a thinker a tic |
| 9 | **Zone mobjs come in play**: at UV the pool of E1M1 and of E1M9 has no free slot after setup (E1M5 3, E1M6 9; demo3's E1M7 at skill 2: 70) [M: POOL] | A generated stream at UV on E1M1 makes the first zone mobj (milestone 9's gate) on its first shot (3.7) |
| 10 | **`validcount` does not wrap in any acceptance demo**: demo3 273 to 50,013, DEMO1 220 to 65,201, DEMO2 318 to 38,853; 23, 13 and 10 a tic at the median, 85, 223 and 318 at most [M: VC] | The wrap fix's release path is not exercised by a demo; the lockstep build reproduces upstream's wrap (`VCWRAP_UPSTREAM`) and the harness asserts where a wrap falls (3.6) |
| 11 | **State tics fit a byte**: every state's tics is -1 or 1-12 [R `info65.s`: the `STATE` macros, 314 states], and the walk relies on it ("the low byte tells -1" [R `p_tick65.s:176-180`]) | The walk's tics plane is a byte (1.3) |
| 12 | **`G_Ticker` goes on after a load in the same tic**: the action loop calls `doLoadLevel` (`bmLoad` → `P_SetupLevel`), then checks the actions again, copies the command and runs `P_Ticker` [R `g_game65.s:563-623`, `:645-669`]. **Code runs after the load inside the action that started it**: `doLoadLevel`'s tail (`stz gameaction`, `Z_CheckHeap`, the keys up, `ST_Start`, `HU_Start` [R `:655-669`]), then for a new game `stz gameaction`, `ST_Start` [R `:1100-1108`], for a demo `readDemoHeader`'s `stz player.cheats` and `doPlayDemo`'s `stz gameaction`, `stz usergame`, `demoplayback = 1`, `starttime = I_GetTime` [R `:1265-1272`, `:1310-1311`], after the intermission `stz gameaction` [R `:877-884`] | The tic image hands the load to the driver with the action that started it, and the driver resumes with that action's continuation (3.4, the load protocol) (review 3) |
| 13 | **`M_Random` is called only by `ST_Ticker`**, once each tic in a level [R `st_stuff65.s:432`]; `HU_Ticker` clears `player.message` [R `hu_stuff65.s:252-269`] | Both effects are the game's (part `flow`); the status bar and HUD are milestone 11's |
| 14 | **The renderer writes game state**: `validcount + 1` a frame and the sector stamps of the walk [R `NATIVE.md` 3.2; `r_bsp65.s:731-736`], which the sound flood reads [R `p_pspr65.s:453-454`, `:488-489`] | Lockstep-schedule mode runs the native front end at each frame; `VALIDCOUNT` and `G_VALID` become one count (1.7) |

## 1. The native layouts

### 1.1 Principles

1. **Milestone 9's layouts are the base.** `LEVELS.md` 3.2 called them
   provisional and gave milestone 10 their ownership; this section is
   their final form for F1.2.1. Every place is a constant of the layouts
   module (`tools/native/glayout.py`, in `llayout.py`'s family, 3.2), the
   generated include carries it to ca65, and the manifest
   `native-game-1` describes it to the bridge. A layout change is one edit
   there and a rebuild: no part's source names an address.
2. **Handles, not addresses.** A mobj is its slot (0-2,025: the pool's
   `poolsize` slots, then the zone's), a special is `$0800` + its slot, a
   sector a byte (0-255), a line, side, subsector, seg, node or sector node
   a 16-bit index; `$FFFF` is none [R `LEVELS.md` 3.2-3.3].
3. **The object API.** Parts read and write game objects only through
   the skeleton's API (`gobj.s`, 3.4): `mo_get`, `sec_get`, `ln_get`,
   `sp_get` bring a record into a write-back cache line in fast memory and
   return a pointer to it; `*_dirty` marks the groups changed; the cache
   writes them back on eviction and at the phase's end (`go_flush`). One
   copy of each object exists in fast memory at a time, so a routine that
   calls another holding the same mobj sees its changes. The far layer is
   the API's business: the parts never call `far_get` or `far_put`
   themselves, **and neither does milestone 9's game core** (review 2):
   `gspawn.s`, `gthink.s` (its thinker-list links in `gt_add` and the
   pool's take and free), `gpos.s`, `gspec.s` and `gvalid.s` go onto the
   API in the skeleton (3.1), so that a spawn into a slot whose cached
   line is dirty (a removal just left it) writes the cached line, never
   the far copy under it. `g_get`/`g_put` stay as the API's own lower
   layer and for the level tables no cache holds (nodes, segs,
   subsectors, block lists: the read-only fetches of 3.4); a skeleton test
   fails the build if any routine outside `gobj.s` writes a cached kind's
   far record. The load image links the same API and empties it at its
   end. Cache sizes are layout constants the integrator tunes from the
   timing report (5.4).
4. **Fields keep upstream's widths** where the arithmetic needs them
   (fixed point 4 B, angles 4 B), shrink where a value is a handle or a
   byte by construction (a sector 1 B, a state's tics 1 B, fact 11), and
   are sign-extended (`sxbyte`) where upstream stores a byte as a word.

### 1.2 The mobj

A slot is a `RTHING` slot (milestone 8) and three game groups at the same
address in three banks [R `LEVELS.md` "Stage C as built"]; milestone 10
moves the thinker walk's fields out of group A to the plane bank (1.3)
and keeps the rest:

| Group | Bank | Bytes | Fields (bytes) | Change from milestone 9 |
| --- | --- | ---: | --- | --- |
| `RTHING` | 50 `RTH` | 24 | x, y, z (4 each), angle high (2), sprite (1), frame (2, bit 15 full bright), flags (1, bit 0 `MF_SHADOW`), snext (2), angle low (2), 2 spare [R `RENDER-MASKED.md` 1.8; `llayout.py` `TH_ANGLO`] | none |
| A | 69 `MOBJA` | 24 | thinker prev (2), type (1), sprev, bnext, bprev, subsector, touching sector list, state, health, target (2 each), 5 spare | thinker next, function and tics to the planes |
| B | 70 `MOBJB` | 24 | floorz, ceilingz, dropoffz, radius, height, flags (4 each) | none |
| C | 71 `MOBJC` | 24 | momx, momy, momz (4 each), move direction (1), threshold (1), pursue count, move count, reaction time, last enemy, `sightline` (2 each) | `sightline` compared from now on (fact 3) |
| Planes | 74 `MOBJP` | 4 a slot | thinker next (2: low and high planes), kind (1), tics (1) (1.3) | new |

`TYPE` stays a byte (50 types [R `LEVELS.md` 1.3]); upstream's kind cache
(mobj byte 11 [R `p_tick65.s:100-118`]) becomes the kind plane's bit 7
(`CLEAN`), which the bridge excludes as it does upstream's [R
`tools/bridge/README.md` "The schema"]. A field of upstream's mobj that has
no native place: none (`offsets.inc:135-171` against the table) [R].

### 1.3 The thinker list and the walk's planes

The list: `G_THFIRST`, `G_THLAST` (milestone 9's globals), each mobj's
next in the planes and prev in group A, each special's in its record
(bytes 0-3, `SP_THPREV`, `SP_THNEXT` [R `llayout.py`]). The list is a
sequence in the canonical model, so its native form is free [R
`tools/bridge/README.md` "The canonical model"].

**The planes.** Bank 74 holds four planes of 2,048 bytes: `TNL`, `TNH`
(the next handle), `KIND` (the function: milestone 9's `FN` numbers 0-11,
bit 7 `CLEAN`), `TICS` (a byte, `$FF` for -1). During the tic phase the
used part (slots 0 to the high-water `G_MOHWM`) is copied into W at the
phase's start and back at its end by the phase loader's routine (`far_pload`
[R `far.s:329-343`]): 4 × 768 = 3,072 B of W for up to 768 slots [A].
A clean mobj's visit then costs no far access: next, kind and tics are in
W, as upstream's walk keeps them in registers and `abs,X` [R
`p_tick65.s:120-140`]. A mobj above slot 767 is a stop `GS_PLANES`
(a native limit, below upstream's zone bound of 2,026 - `poolsize`
[R `LEVELS.md` 3.1]); the integrator measures the highest slot of every
acceptance run (5.3) and raises the cap if one comes near.

Why not a far fetch a visit: 211-335 thinkers [M: THK] × 4 tics × two
windows of about 4-5 µs on F1.2.1 [M: `NATIVE.md` 1.2] is 7-13 ms a
frame; the copy in and out of 3 KB at 0.246 µs a byte [M: `NATIVE.md`
4.3] is 1.5 ms [A].

### 1.4 The specials

`ZONE0` (bank 75), 32-byte records, one range of slots a kind as
milestone 9 built them [R `LEVELS.md` "Stage C as built"; `llayout.py`
`SPEC_KINDS`], each range now a **free list** (milestone 9 took the next
slot; in play specials end and their slots come back): `G_SPFREE`, a head
a kind, in the globals block. Identity is rank among the thinkers of the
kind, so the slot policy changes nothing canonical [R
`tools/bridge/README.md` "Identities"]. A special waiting for its removal
keeps its record with function `REMOVETHINKER` (kind `removed`).

| Kind | Slots | Fields, native (bytes) | Upstream |
| --- | ---: | --- | --- |
| all | | thinker prev, next (2 each), function (1), sector (1) | `OFS_*_THINKER`, `_SECTOR` [R `offsets.inc:332-355`] |
| plat | 256 | speed (4), low, high (4 each), wait, count, status, tag, type (2 each), list (2: always none) | `OFS_PLAT_*` [R `offsets.inc:331-343`]; upstream keeps no list of active plats ("Here there is no list" [R `p_plats65.s:3-6`]), so `OFS_PLAT_LIST` stays NULL from `Z_CallocLevSpec` [R `tools/bridge/schema.py` `PLAT`] and natively none (review 8) |
| door | 256 | type (2), topheight (4), speed (4), direction (1), topcountdown (2), line (2), lighttag (2) | `OFS_DOOR_*` [R `offsets.inc:345-355`] |
| floor | 256 | type (2), direction (1), texture (2), floordestheight (4), speed (4) | p_floor65.s's `.equ`s [R `tools/bridge/README.md` "The schema"] |
| lightflash, strobe, glow | 128 each | count, min, max, times (2 each, as milestone 9) | p_lights65.s |
| scroll | 128 | side (2) | p_spec65.s |

These are milestone 9's offsets (`llayout.SP_KIND` [R `llayout.py:330-340`]),
which held every field of `schema.TYPES` at setup; a part that finds a
field of its kind missing asks for it in its request file (3.8).

The button list (`G_BUTTONS`, 4 × 9 B [R `llayout.py`]) is a global.
There is no `activeplats` (review 8): upstream has none [R
`p_plats65.s:3-6`].
The capacities hold E1 by construction [A on R `LEVELS.md` 3.1: at most
one floor mover, one ceiling mover and one light a sector]; a full range
is a stop `GS_SPECIALS`.

### 1.5 The player and the globals

The player stays at main `$1C80` (148 B, milestone 9's `G_PLAYER` [R
`MEMORY_MAP.md` 16]): upstream's fields in upstream's order (`player_t`
[R `offsets.inc:247-282`]) with the mobj references (`mo`, `attacker`)
as mobj handles, the psprites' states as state numbers and `message` as
a symbol reference, generated from the bridge's schema
(`llayout.player_layout` [R `llayout.py:910-922`]); the psprites (state,
tics, sx, sy each) are its last fields but `didsecret`. New persistent globals go to main
`$1E6F-$1FFF` (401 B free [R `MEMORY_MAP.md` 16]):

| Global | Bytes | Why |
| --- | ---: | --- |
| `CS_PREV1`, `CS_PREV2`, `CS_PREVR` | 5 | Fact 2; `$FFFE` is "stale: names no object" (1.8) |
| `G_LROK`, `G_LRUSE`, `G_LRN`, `G_LRLINES` | 3 + 48 | The line record of `lineBlocks` (fact 4): `LR_OK`, `LR_USE` (a byte each), `LR_N` (a byte, `$FF` too many), `LR_LINES` (24 line numbers [R `p_map65.s:174`, `:200-204`]); cleared by the setup as upstream's [R `p_setup65.s:104`] (review 5) |
| `G_SPFREE` | 14 | 1.4 |
| `G_ZMFREE`, `G_MOHWM` | 4 | The zone mobjs' free list (through the `TNL`/`TNH` planes) and the planes' high-water |
| The demo's place | 5 | `G_DEMOP` exists (milestone 9); the demo bank (1.10) |
| `wi` state | about 40 | `wi_stuff65.s`'s game-side counters [R `wi_stuff65.s:71-93`]: they decide the tic of the next load |
| `G_SHOWMSG`, `G_MSGKEEP` | 4 | `showMessages` (the menu's [R `m_menu65.s:104`]) and `_g_message_dontfuckwithme` [R `hu_stuff65.s:44`]: `HU_Ticker` clears `player.message` only when one is set [R `hu_stuff65.s:249-251`] (review 7) |
| `NUKAGE` | (frame block) | `P_UpdateAnimatedFlat` writes it [R `r_data65.s:681-688`] |
| Lockstep and test state | about 24 | The schedule's pointer, the stream's pointer, the division-by-zero count (`GT_DIV0`), the sight-hint flag (`GT_HINT`, 3.6), the stale-`CS_PREV` flag (`GT_ZPREV`, 1.8), the sound event log's and the same-pair hit log's pointers |

Every canonical global of the bridge's schema (`schema.GLOBALS`, 73 [R
`tools/bridge/README.md` "Globals"]) has a native place or a named
reason (3.6).

### 1.6 Sectors, lines and the tables of bank `$21`

| Object | Native | Change |
| --- | --- | --- |
| Sector | `LVMAP` render record (16 B: heights, pics, light, `validcount`, thing list head) and `LVG1` game record (32 B: sound origin 8, sound target 2, line count 2, line table 2, floor and ceiling data 2 each, touching thing list 2, special 1, old special 1, tag 2, sound traversed 1) [R `LEVELS.md` 3.2] | none |
| Line | `LVG0`, 32 B, full [R `llayout.py` `LINE`] | none |
| Line's sectors | `LVS` (bank 111) `LNSECF`, `LNSECB`: front and back sector, a byte each, by line (the front twice for a one-sided line, upstream's `LNSEC` [R `p_sight65.s:86`; `LEVELS.md` 2.4]) | new, made by the load (a step `GTABS` in `lgeom.s`, 3.1) |
| Reject rows | `LVS` `RJROW`: sector × numsectors, 2 B a sector (upstream's `SS_ROW` [R `p_sight65.s:83`]) | new, the same step |
| Subsector's sector, first seg, count | `LVMAP`'s subsector record (milestone 9's `GROUP` writes the sector) | none: replaces `SS_SEC` and `SS_SEGT` |
| `SIGHTLOG`, `LINELOG` (log K values), `SEC58`, `LN36`, `BMROW` | none | Address tables, or the log fast path of the side test, which "decides when it is 18 or more away from 0" [R `p_sight65.s:695-702`], so the exact signed product gives the same answer; part `sight` checks this on every captured call and reports a difference (then `LOGTAB`, banks 123-124, is still reserved [R `LEVELS.md` 1.6]) |
| `IC_NEXT`, `IC_LAST`, `VT_*`, `IV_*` | tic scratch (1.9) | upstream's trace scratch in bank `$21` [R `p_trace65.s:29-47`; `tools/bridge/README.md` "What the bridge found"] |
| The sight hint | `MOBJP` `HINTL`, `HINTH`: a line + 1 by pool slot (fact 3) | new; never cleared but at boot, as upstream's table |

These answer milestone 9's gate "bank `$21`'s sight and move tables"
[R `LEVELS.md` 2.6]: checked by the skeleton against upstream's tables
on all 57 setup dumps (3.9, S4).

### 1.7 `validcount`: one count

Upstream has one `validcount` [R `p_map65.s:302-303`], raised by the
game's walks and once a frame by `R_RenderPlayerView`'s setup [R
`NATIVE.md` 3.2]. Natively the renderer's `VALIDCOUNT` (frame block
`$0310` + its offset [R `rlayout.py` `FRAME_BLOCK`]) and the game's
`G_VALID` (globals block [R `llayout.py`]) are two places today [R
`LEVELS.md` "Stage C as built"]. The skeleton makes `G_VALID` an alias
of the frame block's `VALIDCOUNT` (the globals block's word freed, the
manifest's `p_map65.s:validcount` moved), and `nr_setup`'s `inc
VALIDCOUNT` [R `rframe.s:237-239`] becomes `jsr gv_inc` with `gvalid.s`
linked into the render image too (9 B in test builds, 134 B with the
release's clear [M: M9]). Lockstep and test builds (`VCWRAP_UPSTREAM`)
increment as upstream; the release build clears every stamp at the wrap
in both phases. Milestone 11's release frame test (a frame at `$FFFF`)
stays milestone 11's [R `NATIVE.md` 15.1 row 4].

### 1.8 The sight state

`CS_PREV1`, `CS_PREV2` (mobj handles), `CS_PREVR` (the answer), each
mobj's `sightline` (1.2), the hint planes (1.6), and `sightblocker` and
`TWOBLOCKER` as scratch of the call [R `p_sight65.s:70-73`]. All but the
scratch are canonical and compared (3.6), the hint by pool slot through
upstream's pool base.

**`CS_PREV` across loads and zone reuse** (review 4). Upstream writes
`CS_PREV1/2` only in `P_CheckSight` [R `p_sight65.s:138-150`], so they
keep the last map's pointers across a load. When the pool base stays,
a stale pointer names the same slot upstream and natively, and a
same-pair hit after a reborn reload is the same on both sides. When the
base moves, upstream's pointer names a new slot only if it lands on one;
otherwise it names nothing and can never hit, which the bridge records as
a raw pointer [R `tools/bridge/upstream.py:821-830`]. So:

1. The bridge decodes a `CS_PREV` pointer that names no object as the
   canonical value `stale` (1.11), and the native `$FFFE` decodes to the
   same value.
2. In test builds the harness re-keys `CS_PREV1/2` at every setup, as it
   re-keys the hint (3.6): from the reference's `_g_thingPool` and
   pointer at the setup's end, the slot the pointer lands on, or `$FFFE`.
   The release keeps its handles (it cannot know upstream's base); this is
   T3's reasoning, named in 6, risk 7.
3. A zone mobj's slot is not its `Z_Malloc` address: when a mobj that
   `CS_PREV` names is a zone mobj and is removed, the native sets that
   handle to `$FFFE` and raises `GT_ZPREV` when the walk frees it (part
   `mobjstate`); upstream's pointer may later
   name a new zone mobj at the same address. The canonical comparison
   then shows it (`stale` against an identity) and the tic comparison
   names it (3.6, T3's zone clause).
4. Both sides log every same-pair hit (a return without `validcount++`):
   the reference by `--call-log` of the hit's return [R
   `p_sight65.s:145-147`], the native in `GTEST`; the logs are compared
   every tic, in and out of every window, so a hit that differs is never
   hidden by an exclusion.

### 1.9 The intercepts and the trace

| Item | Native | Upstream |
| --- | --- | --- |
| An intercept | frac (4), what (2: a line number, or `$8000` + a mobj handle): 6 B | `intercept_t`, 10 B [R `offsets.inc:298-301`] |
| The list | 64 entries (`MAXINTERCEPTS` [R `p_path65.s:23`]) and the by-frac chain (a byte a link): 448 B of tic scratch | `intercepts` (640 B), `IC_NEXT`, `IC_LAST` [R `p_trace65.s:42-47`] |
| The trace | `_g_trace` (a divline, 16 B), the path's walk state, `TR_LONG`, `VT_RR` | near globals of `p_path65.s`, `p_trace65.s` [R `p_path65.s:36-102`] |

All of it is scratch of a traversal: nothing lives from one tic to the
next [R `tools/bridge/README.md`: "trace scratch"].

### 1.10 Placement

RamWorks (against `LEVELS.md` 1.6, 109 of 126 used, spare 1-5, 72-74,
91-97, 125, 126 [M: M9]):

| Bank | Name | Content | Label |
| ---: | --- | --- | --- |
| 72, 73 | `GCODE0`, `GCODE1` | The tic phase's images: the core and every paged group, at their W addresses (4.1) | A: about 65 KB of native game code (4.7) |
| 74 | `MOBJP` | The walk's planes (4 × 2,048) and the hint planes (2 × 2,048): 12 KB | A (1.3, 1.6) |
| 111 | `LVS` | `LNSECF`, `LNSECB` (1,536 each), `RJROW` (512) | A (1.6) |
| 91 | `DEMOB` | The demo lump that plays (test builds: placed by the harness; milestone 11 stores the game's) | A |
| 92 | `GTEST` | Test builds only: the lockstep schedule, the tic stream, the sound event log, pre-states | A |
| 123, 124 | `LOGTAB` | Stays reserved until part `sight` shows the exact side test equal (1.6); then spare | R `LEVELS.md` 1.6 |
| 4, 5 | | Test data of milestone 9 (CRC list, pre-states) [R `MEMORY_MAP.md` 16] | |

**Test builds: 116 of 126 used** (109 + 72, 73, 74, 91, 92 + 4, 5; spare
1-3, 93-97, 125, 126: 10), 114 when `LOGTAB` (123, 124, already among the
109) is freed. **Release: 113** (no `GTEST`, no test data in 4 and 5),
111 without `LOGTAB` [A]. (Review 11: this line said 113 used with the
spare list of a 116 count.) Main memory, zero page and W: section 4.

### 1.11 The manifest and the bridge

`glayout.py` writes `native-game-1`, a `bridge-port-layout 1` manifest
that extends milestone 9's `native-level-1` [R `LEVELS.md` 3.3] with
every kind of 1.2-1.9, with the encodings milestone 9 added (`handle`,
`sxbyte`, `bit`); the planes need nothing new, a leaf's byte planes
being the format's default [R `tools/bridge/README.md` "The port's
layout"]. Identity pairing: mobjs by slot (upstream's pool slot by
construction), zone mobjs, specials and sector nodes renumbered by
`identity.renumber` [R `tools/bridge/README.md` "Identities"], the line
tables by index. The bridge gains, with tests and with every existing
manifest unchanged:

| Addition | Why |
| --- | --- |
| `EXTERNAL_GLOBALS` for `wi_stuff65.s`'s counters, `texturetranslation`, `nukage`, `hu_stuff65.s:_g_message_dontfuckwithme`, `m_menu65.s:showMessages` | They decide the tic of a load (`wi`), what the renderer draws, or whether `HU_Ticker` clears `player.message` (review 7); compared every tic |
| A derived kind `sighthint`: upstream's `SIGHTHINT` entry of each pool slot of the level, through `_g_thingPool` | Fact 3; the hint comparison (3.6) |
| `CS_PREV1`, `CS_PREV2`, `CS_PREVR`, `mobj.sightline` compared in the `lockstep` mode; a `CS_PREV` pointer that names no object decodes as `stale`, not as a raw pointer | Fact 2; they were `cache` fields [R `tools/bridge/README.md` "Field classes"]; 1.8 (review 4) |
| `LR_OK`, `LR_USE`, `LR_N`, `LR_LINES` compared in the `lockstep` and `routine` modes (they leave `llayout.NOT_KEPT` [R `llayout.py:429-432`]) | Fact 4 (review 5) |
| A `tic` comparison mode: `lockstep` with 3.6's named exclusions | 3.6 |

## 2. The call graph, the parts and the waves

### 2.1 The graph

Made for this design by a read of the game units with the release's
conditionals (`TICSTEP` 1, `MAXTICS` 4 [R `tics.inc:9-23`; upstream
`Makefile:23`]) and the link map's code labels [M: CG, appendix A]. A
**routine** is a head: an exported label, the target of a `jsr`, `jsl` or
`jml`, or a label another routine names as a function pointer; every
other code label belongs to the head before it. An **edge** is a call
(`jsr`, `jsl`, `jml`, or a `jmp` to another head: a tail call); a
function pointer named in an operand is a reference, not an edge.

| Measure | Value |
| --- | ---: |
| Code of the game units (`p_*.s`, `g_game65.s`, `d_main65.s`, `m_cheat65.s`, `m_random65.s`) | 55,491 B, 634 routines |
| Strongly connected groups of direct calls | 4: `gRun`/`gBlockW` (dead), `PIT_AddLineIntercepts`/`interceptVector3`/`ivProd`/`lineCross`/`lineCrossL`, `calcHeight`/`fixedSquare`, `giveBody`/`givePower` |
| Milestone 10's routines | 43,074 B in 29 parts |
| Built elsewhere or out | milestone 9 4,876 B, milestone 6 169 B, setup-only 2,962 B, milestone 11 3,126 B, dead 1,284 B |

The skeleton keeps this reading as a tool (`tools/native/gcallgraph.py`,
3.1): it checks the part table's rule at every build (2.2), gives the
routine-mode harness each call's reachable dispatch targets (3.5), and
feeds the placement (4.3).

### 2.2 The rule, and the dispatch tables

**Rule.** Every routine of 2.4 has exactly one owning part. A part's
direct callees are built by an earlier wave, by milestone 9 (with the
skeleton's extensions) or by the part itself. `gcallgraph.py --check`
fails the build otherwise. **Routines are keyed by `file:label`**
(review 9): ten helper names exist in two or three files (`sectorArg`,
`thingArg`, `startSound`, `argMo`, `randMod`, `setDir`, `blockOf`,
`isPlayer`, `opening`, `secArg` [M: grep of `^label:`]), and 2.4's
helper lists name each helper of the file its routines are in. The
graph also follows calls out of the game units into the units the tic
reaches (`r_list65.s`'s `linkRemove`, `w_level65.s`'s `W_StartInter`,
`hu_stuff65.s`, `st_stuff65.s`, `wi_stuff65.s`) and fails `--check` on
any reachable routine that is neither owned, a hook of `ghook.s`, nor
named out in 0.1.

**Dispatch tables.** Upstream calls five families of routines through
pointers (fact 1). Natively each is a table generated by the layouts
module from the part table: the dispatcher's owner builds the table's
mechanism and calls through it; each target's owner fills its entry when
its wave is integrated; an entry not yet built is a stop (`GS_UNBUILT`
and the target's number, then `BRK`), never a silent return.

| Table | Dispatcher (owner) | Entries (owners) | Upstream |
| --- | --- | --- | --- |
| `ACTTAB`: a state's action, by action number (the 29 actions of the states [R `info65.s:16-20`], and `A_CyberAttack` through the rocket cheat [R `p_tick65.s:863`]) | `P_SetMobjState` (`mobjstate`), `setPsprite` (milestone 9's `gweap.s`, the skeleton) | `look`, `chase`, `pspr`, `wfire`, milestone 9 (`A_Raise`) | `JML [FN_P]`, `JML [ACT_JMP]` [R `p_tick65.s:533`; `p_pspr65.s:118`] |
| `THTAB`: a thinker's function (milestone 9's `FN` numbers) | `P_RunThinkers` (`tic`) | `tic` (mobj), `mobjstate` (the brainless thinker, the two removals; wave 1 as integrated: `glayout.PARTS` gives `P_MobjBrainlessThinker` to `mobjstate`), `secfind` (lights, scroll), `planes` (floor), `movers` (door, plat) | the walk's `call` [R `p_tick65.s:303-317`] |
| `ITTAB`: a block iterator's callback | `P_BlockLinesIterator`, `P_BlockThingsIterator` (`geom`) | `tracel` (`PIT_AddLineIntercepts`), `chasemove` (`PIT_AvoidDropoff`), `look` (`PIT_RadiusAttack`), `teleport` (`stompThing`) | `callLN`, `callLN2` [R `p_map65.s:2786`, `:2869`] |
| `TRVTAB`: a traverser | `P_PathTraverse` (`path`) | `attack` (`PTR_AimTraverse`, `PTR_ShootTraverse`), `xymove` (`PTR_SlideTraverse`), `player` (`PTR_UseTraverse`, `PTR_NoWayTraverse`), the harness's recording traverser (3.5) | `callTrav` [R `p_path65.s:816`] |
| `LSTAB`: a line special's handler (`lnDoor` ... `lnExit` [R `p_switch65.s:502-563`]) | `findSpecial`'s callers (`lines`) | `evworld` (doors, plats), `evfloor` (floors, stairs, donut), `secfind` (lights), `teleport`, `lines` (exits) | `jsr (spectab+2,x)` [R `p_switch65.s:452-455`] |

A dispatcher's checkpoint uses only captured calls whose dispatched
targets are all built at its wave (3.5, eligibility); the integrator
reruns every checkpoint after each wave, so a dispatcher of wave 1 is
checked on all its calls by the end of wave 6. Three smaller tables stay
inside their parts: `pickTab`, the pickups by sprite [R
`p_inter65.s:1144-1169`] (`pickup`), `bfTab`, `behindFast`'s cases
[R `p_enemy65.s:2209`] (`look`), and `G_Ticker`'s action table
`jsr (actions-2,x)` [R `g_game65.s:581`, `:630-632`] (`tic`), whose
targets (`loadLevel`, `doNewGame`, `doPlayDemo`, `doCompleted`,
`victory`, `doWorldDone`; the save and load game are milestone 11's and
stops here) are all `flow`'s, built in wave 1 (review 9). Upstream's
`callFn` and `callAction` [R `p_tick65.s:533`, `p_pspr65.s:118`] become
the skeleton's `DCALL` on `ACTTAB`.

### 2.3 The waves

| Wave | Parts (upstream bytes) | Their direct callees outside the part [M: CG] |
| ---: | --- | --- |
| 1 | `geom` (1,707), `mobjstate` (1,397), `secfind` (1,363), `flow` (1,115 + `wi`, the tickers' effects and the action targets about 700 [A]), `sight` (2,738) | milestone 9, math |
| 2 | `tracel` (2,136), `damage` (1,363), `pickup` (1,611), `lines` (1,042), `spawn` (842) | `geom`; `mobjstate`; `mobjstate`, `flow`; `flow`, `secfind`; `mobjstate` |
| 3 | `tracet` (2,189), `checkpos` (2,019), `pspr` (894), `evworld` (1,223), `look` (1,729) | `tracel`; `damage`, `geom`, `pickup`; `damage`, `geom`, `mobjstate`; `secfind`; `damage`, `geom`, `mobjstate`, `sight` |
| 4 | `path` (1,239), `trymove` (1,164), `planes` (1,222), `evfloor` (1,159), `teleport` (1,130) | `geom`, `tracel`, `tracet`; `checkpos`, `geom`, `lines`, `mobjstate`, `spawn`; `checkpos`, `mobjstate`; `secfind`; `damage`, `geom`, `mobjstate`, `secfind` |
| 5 | `attack` (1,877), `player` (2,131), `xymove` (2,367), `missile` (593), `chasemove` (2,211) | `damage`, `evworld`, `geom`, `lines`, `path`, `secfind`, `spawn`; `damage`, `flow`, `geom`, `lines`, `mobjstate`, `path`, `pspr`; `geom`, `mobjstate`, `path`, `spawn`, `trymove`; `mobjstate`, `spawn`, `trymove`; `geom`, `lines`, `look`, `trymove` |
| 6 | `movers` (1,094), `wfire` (964), `tic` (1,155), `chase` (1,400) | `evworld`, `mobjstate`, `planes`, `secfind`; `attack`, `damage`, `missile`, `pspr`, `spawn`; `flow`, `mobjstate`, `player`, `secfind`, `spawn`, `trymove`, `xymove`; `attack`, `chasemove`, `damage`, `evfloor`, `look`, `missile`, `mobjstate`, `sight` |

**Why six.** The chain `mobjstate` (`P_RemoveMobj`, `P_SetMobjState`) →
`damage` (`P_KillMobj` sets states) → `checkpos` (`PIT_CheckThing`
damages and picks up) → `trymove` → `xymove` (`P_XYMovement` calls
`P_TryMove`) → `tic` (`P_MobjThinker` calls `P_XYMovement`) is six parts
long, and merging two of them would make a part of more than 3 KB of
upstream code (`checkpos` and `trymove` 3,183 B; `xymove` and `tic`
3,522 B) [M: CG]. The trace chain `geom` → `tracel` → `tracet` → `path`
→ `attack` → `wfire` is six parts too. `teleport` needs only waves 1-2
and is reached only through `LSTAB`, so it takes wave 4's fifth place;
wave 6 has a free one, which no part can take earlier.

### 2.4 The parts

For every part: sources `src/native/game/<part>/*.s` with the fragment
`src/native/game/<part>/part.mk` (3.3), its tools (if any) in
`tools/native/gparts/<part>*.py`, build output in
`build/native/game/<part>/`, tests in `tests/test_native_game_<part>.py`,
requests and results in `docs/game-parts/<part>.md`. The part owns those
files alone. "Up." is the upstream bytes of its routines [M: CG];
"native B" is its size budget: upstream × 1.3, rounded [A on
M: milestone 9's game core came out at about upstream's size, 5,260 B
for about 5,300 B of upstream's routines; milestone 7's `rwall.s` 1.24
times `r_wall65.s`]. "Helpers" are the part's non-exported labels of the
same modules, each of the file of the routines named just before it in
the row (keyed `file:label`, 2.2); a helper two parts need is owned by
the earlier one (the table lists it there).

**Arithmetic** (review 13). Every product and divide that upstream makes
through its runtime or `m_fixed65.s` is milestone 6's (`math.s`); no
part writes its own of those. Upstream's own arithmetic helpers are
mirrored exactly by the part that owns them, and each gets a check of
100,000 random inputs (edge values included: 0, ±1, the extremes) by
`--call` of upstream's helper against the native one, in the part's
test: `friction` [R `p_mobj65.s:1180-1188`] and `bestMul` (`xymove`),
`shr3` (`spawn`), `posMul` (`geom`), `ivProd`, `smul` (`tracel`),
`smul48`, `half` and the side test's log fast path [R
`p_sight65.s:695-702`] (`sight`), `mulSpeed`, `umul16x`, `times32`
(`chasemove`), `rangeMul`, `mul3` (`attack`), `times20` (`teleport`),
`thrustMul`, `hurt32`, `fixedSquare`, `times64` (`player`), `mulExt`
(`movers`). A helper whose arguments are not registers or `_Dp` gets
its `in=`/`out=` ranges from the part's `args.json` (3.5).

**Inputs and outputs** (review 6). Every entry of a checkpoint has
declared inputs and outputs in the part's `args.json`: registers, direct
page symbols (`dp:SYMBOL`, beyond `_Dp`: `TP`, `AP`, ...) and near
symbols (`tmx`, `tmy`, `MP_MODE`, ...), each with its native counterpart
named (a `GA_*`, `GT_*` or scratch-block symbol of `ggame.inc`).
Outputs that upstream leaves in its scratch are compared exactly against
their counterparts: `opentop`, `openbottom`, `openrange`
(`P_LineOpening`; `_g_lowfloor` is never stored by upstream, "not stored:
no code reads it" [R `p_map65.s:298`], so `geom` checks that it stays
unchanged: wave 1 as integrated, `docs/game-parts/geom.md` R9), `tmfloorz`, `tmceilingz`, `tmdropoffz`, `_g_spechit`
and `_g_numspechit` (`P_CheckPosition`), `_g_linetarget`
(`P_AimLineAttack`), and every result an entry's callers read.

The **checkpoint** of each part is routine mode (3.5): captured calls of
its entry routines from the reference, each run from both poisoned
machines (`$A5`, `$5A`), the canonical state after the call equal to
`ref816`'s with the routine exclusions of 3.5, the return values equal,
no stray write, and cycles recorded on `f121` and `fastpath`. Minimums:
every captured call of an entry with fewer than 300 calls in the capture
runs, else 300 spread evenly plus every call that takes a path no other
chosen call takes (the coverage report of 3.5), plus the synthetic cases
named below for paths no run takes. The **planted bugs** are each made in
a scratch copy of the part's sources and must fail the named check; the
test file plants them.

#### Wave 1

| Part | Routines [R file:line] | Up. / native B | Checkpoint: entries, cases | Planted bugs (each caught by) |
| --- | --- | --- | --- | --- |
| `geom` | `p_map65.s`: `P_PointOnLineSide:2458`, `P_BoxOnLineSide:2483` (every case; milestone 9 built the slanted one inside its walk), `P_LineOpening:2367`, `P_LineOpeningXY:2451`, `pointSector:2094` with `posMul:2265` (a point's sector through `R_PointInSubsector`), `sectorFloor:2064`, `baseFloor:2062`, `baseFloorL:2060` (review 9), `baseLite:2083`, `P_BlockLinesIterator:2680`, `P_BlockThingsIterator:2791`, `blockRange:3353`; helpers `argLine4`, `box1`, `box2`, `posPub`, `walk1`, `walk2`, `callLN`, `callLN2` | 1,707 / 2,200 | Captured calls of every entry; the two iterators with the recording callback (3.5) on every captured call's block range; 100,000 random point-line and box-line pairs per map through `--call` of upstream's routine | an on-the-line point given side 1 (pairs); `P_BoxOnLineSide`'s horizontal case on the wrong edge (pairs); a block list read from its first entry (iterators: milestone 9's rule [R `LEVELS.md` 2.4]); `P_LineOpening`'s lowfloor as the higher floor (captured: `openbottom` and `openrange` are declared outputs; `_g_lowfloor` is never stored, geom.md R9) |
| `mobjstate` | `p_map65.s`: `P_UnsetThingPosition:717`, `P_DelSeclist:3033`, `P_DelSecnode:3058`; `p_think65.s`: `P_RemoveThinker:80`, `P_RemoveThing:84`, `P_RemoveThinkerDelayed:99`, `P_RemoveThingDelayed:102`, `P_NextThinker:153`; `p_spawn65.s`: `P_RemoveMobj:339`, `poolFree:1334` (and the zone's free list, whose free of a zone mobj that `CS_PREV` names sets that handle to `$FFFE` and raises `GT_ZPREV`, 1.8); `r_list65.s`: `linkRemove:933` (review 9); `p_tick65.s`: `P_SetMobjState:749` (the `ACTTAB` dispatch, `rocketCheat:863`), `P_MobjBrainlessThinker:706`; `p_mobj65.s`: `P_ExplodeMissile:734`, `explode:741`, `P_MobjIsPlayer:716`; helpers `unlist`, `link`, `mvSector`, `mvBlock`, `blockOf`, `snLink`, `unlink`, `rmArg` | 1,397 / 1,900 | `P_SetMobjState` (eligible calls: state chains whose actions are built), `P_RemoveMobj`, `P_UnsetThingPosition`, `P_DelSeclist`, `P_ExplodeMissile`; synthetic: a zone mobj removed and its slot taken again (the gate "no slot handed out twice"), a mobj with no function removed (`linkRemove`), a chain of 0-tic states, the rocket cheat flag | the action run before the tics are set; a mobj with no function freed at once instead of linked and deferred (`linkRemove`); a freed node left off the free list (node order; wave 1 as integrated: "a freed node put at the free list's tail" is no state, the canonical model numbering the free nodes in the list's order, `tools/bridge/identity.py`, `docs/game-parts/mobjstate.md` 5); the block list's back link left (lists); removal at once instead of deferred (the walk's next, 1.3); `poolFree` clearing the neighbour bit |
| `secfind` | `p_spec65.s`: `getNextSector:66`, `P_FindLowestFloorSurrounding:123`, `P_FindHighestFloorSurrounding:134`, `P_FindLowestCeilingSurrounding:141`, `P_FindSectorFromLineTag:250`, `P_CheckTag:287`, `P_UpdateSpecials:308` (animated textures into `TEXTRANS`, `P_UpdateAnimatedFlat`'s `NUKAGE` [R `r_data65.s:681-688`], the buttons), `T_Scroll:559`; `p_floor65.s`: `P_FindNextHighestFloor:694`; `p_lights65.s`: `T_LightFlash:58`, `T_StrobeFlash:95`, `T_Glow:130`, `EV_LightTurnOn:439`; helpers `sideSector`, `secArg`, `lineOf`, `buttonDone`, `mod3`, `nextOther`, `aboveCurrent`, `ltSector`, `nextSector` | 1,363 / 1,800 | Every thinker call of the light and scroll kinds; `P_UpdateSpecials` once a tic (with `TEXTRANS` and `NUKAGE` compared); the finders through `--call` on every sector of the nine maps; synthetic: leveltime 32,768 and above (upstream's unsigned shift [R `r_data65.s:682-686`]), a button's timer ending | the tag search restarting at 0 (finders); `T_Glow` turning one step late (thinker calls); `NUKAGE` with a signed shift (the synthetic leveltime); the button restoring the other texture |
| `flow` | `g_game65.s`: the action table's targets `loadLevel:635`, `victory:640` (a stop: the finale), `doNewGame:1100`, `doWorldDone:877`, `doPlayDemo:1205`, `doCompleted:737` (review 9); `doLoadLevel:645` split at `bmLoad` into its part before the load (`P_SetSecnodeFirstpoolToNull`, the game state, the reborn) and its tail after it (3.4); `G_ExitLevel:724`, `G_SecretExitLevel:728`, `G_WorldDone:863`, `G_DeferedInitNew:1089`, `G_ReloadDefaults:1094`, `initNew:1111` (with `M_ClearRandom`), `readDemoTiccmd:1144`, `G_DeferedPlayDemo:1194`, `readDemoHeader:1277`, `checkOverrun:1316`, `G_CheckDemoStatus:1332`; the continuations of the load protocol, one an action (3.4: `GA_LOADLEVEL`, `GA_NEWGAME`, `GA_PLAYDEMO`, `GA_WORLDDONE`); `wi_stuff65.s`: `WI_Start:206`, `WI_End:235`, `WI_checkForAccelerate:246`, `WI_Ticker:274` and the counts to `:585` without drawing; `st_stuff65.s`: `ST_Ticker:432`'s game effect (`M_Random`) as `st_tick`; `hu_stuff65.s`: `HU_Ticker:244`'s game effect (the message clear, through `G_SHOWMSG`, `G_MSGKEEP`) as `hu_tick`; helpers (`wi_stuff65.s`) `signLong`, `div1000` | 1,800 / 2,300 | `readDemoTiccmd` (every tic of the three demos), `G_CheckDemoStatus`, `doCompleted` (the tour's 8 exits), `WI_Ticker` (every intermission tic of the tour, with `wi` compared), `st_tick` and `hu_tick` (every tic of demo3: `M_Random`'s index and `player.message` compared), `G_DeferedInitNew`, `G_DeferedPlayDemo`; the load-containing actions (`doNewGame`, `doPlayDemo`, `loadLevel`, `doWorldDone`) through the driver's load protocol (3.4) from the reference's state at the action's call, compared after the continuation (the starts of the demos, newgame, the tour's world-done loads) (review 3) | `angleturn` not shifted back from the demo's byte (`readDemoTiccmd`); the secret exit's next map (`doCompleted`); the counts' step of 2 for kills (`WI_Ticker`); `M_Random` not called (`st_tick`); `demoplayback` not set in `GA_PLAYDEMO`'s continuation (the load runs); the message cleared with messages off (`hu_tick`, a synthetic case with `G_SHOWMSG` 0) |
| `sight` | `p_sight65.s`: `P_CheckSight:138` (`CS_PREV`, REJECT through `RJROW`, the same subsector, the walk of `P_CrossBSPNode` with its waiting children, the hint as a one-seg subsector, the seg and line tests with `validcount`), `zSetup:1061`, `sightSlope:1407`, `interceptFrac:1150`, `opening:985`; helpers `hintOf`, `half`, `qbd`, `nodeDone`, `lineDone`, `pick`, `sameHeight`, `st32`, `shr8V`, `smul48`, `bitTab` | 2,738 / 3,600 | 2,000 calls over the three demos and the coverage runs, by path: REJECT, same subsector, the same pair (`CS_PREV`, with the hit log of 1.8 compared), the hint hit, blocked by a one-sided line, by a two-sided opening, seen; each case also run with an empty hint plane, the answer required equal (fact 3); synthetic: a sight line along a node line (the side test's "on" case), a call whose `CS_PREV` is `$FFFE` with a pair of the same slots as before it (no hit) | `CS_PREV` not kept (`validcount`); `$FFFE` matching a slot (the hit log); the far child walked first (stamps); the side test on 32-bit differences, not the 16-bit whole parts with their wrap [R `p_sight65.s:620-650`] (synthetic); `sightSlope`'s reciprocal of the 32-bit distance; REJECT's bit order |

#### Wave 2

| Part | Routines [R file:line] | Up. / native B | Checkpoint | Planted bugs |
| --- | --- | --- | --- | --- |
| `tracel` | `p_trace65.s`: `PIT_AddLineIntercepts:985`, `interceptVector3:242` (`P_InterceptVector3` with its `FixedDiv` and guards [R `NATIVE.md` 3.2]: upstream's own long division of `p_trace65.s:405-541`, mirrored; `tracel.md` R4, R5), `divlineSide:152`, `addIntercept:744`, `icInsert:778` (the by-frac list), `ivSetup:1875`; helpers `ivTest`, `ivProd`, `ivAxis`, `lineCross`, `lineCrossL`, `vtxSlow`, `vtxSlowL`, `vtxSlowR`, `icInsertL`, `gOf`, `smul`, `vsC` | 2,136 / 2,800 | `PIT_AddLineIntercepts` through `P_BlockLinesIterator` on every captured `P_PathTraverse` block step; `interceptVector3` and `divlineSide` on 1,000,000 random inputs by `--call` plus every captured input; synthetic: two intercepts of equal frac (the list's order) | the `FixedDiv` guard one off (random inputs); an equal frac inserted before the old one (synthetic); the fast product path deciding where upstream's does not (random) |
| `damage` | `p_inter65.s`: `P_DamageMobj:541` (god mode, armour, the thrust with `P_Random`, `R_PointToAngle3` and the 32-bit divide, pain chance, threshold and target, the player's counts and attacker), `killMobj:994` (`P_KillMobj`: flags, counts, the death or extreme death state, the tics' `P_Random`, the drops through `P_SpawnMobj`); `p_pspr65.s`: `P_DropWeapon:547`, `lowerWeapon:551`, `wInfo:122`, `wInfoOf:123`; helpers `targetArg`, `setTarget`, `setState`, `lastEnemy`, `thrust`, `addThrust`, `playerDamage` | 1,363 / 1,800 | Every captured `P_DamageMobj` (demo3 132, DEMO1 186, DEMO2 52 [M: CALLS]); synthetic: a kill with a drop, the player's death, each armour type, god mode, a hit at 0 health | thrust divided before the multiply; pain chance tested before the thrust's `P_Random` (the index); the extreme death at `<=` instead of `<` (synthetic); the drop spawned before the death state (thinker order) |
| `pickup` | `p_inter65.s`: `P_TouchSpecialThing:101` (`pickTab:1144`'s cases), `P_GivePower:497`, helpers `specialArg`, `playerMo`, `giveBody`, `giveAmmo`, `giveWeapon`, `givePower`; `m_cheat65.s`: `C_Responder:73`'s effects (the cheats as event numbers: matching typed keys is milestone 11's input), `power:129`, `giveAmmo:182` | 1,611 / 2,100 | Every captured `P_TouchSpecialThing` (DEMO2 268 [M: CALLS]); synthetic: one touch of each E1 item type by the player at each skill (a state from a capture with the item moved onto the player); each cheat of the tour (`iddqd`, `idclev`) and of the generated streams | ammo doubled at the wrong skill; a weapon already owned giving no ammo; the backpack not doubling the maxima; another item's message |
| `lines` | `p_switch65.s`: `P_CrossSpecialLine:420`, `P_UseSpecialLine:364`, `findSpecial:473` with the `LSTAB` dispatch and `lnExit`, `P_ChangeSwitchTexture:209` (the button list), the tables `usetab:565`, `crosstab:585`; helpers `swLine`, `swSide`, `isPlayer` | 1,042 / 1,400 | Captured calls (eligible: those with no handler, or a light or an exit, until waves 3 and 4 fill `LSTAB`); `P_ChangeSwitchTexture` on every switch texture of the nine maps by `--call` | a walk-once special not cleared; a monster allowed on a player-only special; the button's timer one tic short |
| `spawn` | `p_spawn65.s`: `P_SpawnPuff:375`, `P_SpawnBlood:401`, helpers `moArg`, `saveXYZ`, `zNoise`, `spawnXYZ`, `ticsNoise`, `thArg`; `p_attack65.s`: `P_IsAttackRangeMeleeRange:622`; `p_mobj65.s`: `P_ZMovement:949` (gravity, the floor and ceiling hits, a missile's explosion, the player's squat), `missileHit:880`, `shr3:895`, `isPlayer:1230` | 842 / 1,100 | Every captured `P_ZMovement` (DEMO1 5,864: 300 by path), every puff and blood; synthetic: a mobj at the ceiling, a missile into the floor | gravity after the floor clamp; the puff's z `P_Random` taken after the tics' (the index); blood's state thresholds one off; the squat's `deltaviewheight` shift |

#### Wave 3

| Part | Routines [R file:line] | Up. / native B | Checkpoint | Planted bugs |
| --- | --- | --- | --- | --- |
| `tracet` | `p_trace65.s`: `traceLines:1142` (each block's lines with `validcount`, the fast vertex sides), `traceThings:1407` (a thing's diagonal), `sideSetup:860`, `longTrace:817`, the patched templates `tlP1`, `tlP2`, `thP`, `gtP1`, `gtP2`, `ptT1:1681`, `ptT2:1762`, `vsPatch:1806`, `ptPatch:1842` (natively data, not patched code); helpers `thFast`, `thFastL`, `thSide` | 2,189 / 2,800 | `traceLines` and `traceThings` on every captured block step of `P_PathTraverse` (DEMO2 5,602 traverses); synthetic: a trace through a vertex, along a line | a thing's diagonal chosen by the wrong quadrant; the stamp written after the box test; a line shared by two blocks met twice |
| `checkpos` | `p_map65.s`: `P_CheckPosition:1198`, `checkPos:1383` (the box through `setBox:1253`, `setBoxL:1251`, `above:1335` (review 9), the point's floor and ceiling, the things' walk with `checkThing:2879` = `PIT_CheckThing`: missiles' damage with `P_Random`, pickups, solid things; the lines' walk `lineBlocks:1706` with `PIT_CheckLine`: the blocking flags, openings, `spechit` in order, the line record `LR_OK`, `LR_N`, `LR_LINES` for `mvNodes` in `lCross:1899` and the walk's end [R `:1850-1856`]), `walkRange:1045`, `loadRad:1209`, `cpCopy:1230`, `ps32:2040` | 2,019 / 2,600 | `P_CheckPosition` (demo3 590) and `checkPos` as an entry inside `P_TryMove` (300 by path); synthetic: things and lines at block corners where the order shows (as milestone 9's `secorder.py`), three special lines crossed in one box, a box crossing more than 24 lines (`LR_N` `$FF`); outputs `tmfloorz`, `tmceilingz`, `tmdropoffz`, `spechit` and the line record compared (2.4 "Inputs and outputs") | the block walk with y outer (the corner cases: milestone 9's gate "the block walk's order on every move"); things before lines; `spechit` in reverse; a missile's damage `P_Random` order; the line record not kept |
| `pspr` | `p_pspr65.s`: `P_MovePsprites:1200`, `tickPsprite:1215`, `A_WeaponReady:561` (the bob, the attack, the saw's idle sound), `A_ReFire:675`, `A_Lower:694`, `A_GunFlash:756`, `A_Light0:1171`, `A_Light1:1173`, `A_Light2:1176`, `fireWeapon:530`, `checkAmmo:379` (the ammunition of a shot; upstream switches no weapon there: `P_SwitchWeapon:183`, the preferences `prefs:60`, is `G_BuildTiccmd`'s, `g_game65.s:298-302`, milestone 11's), `P_NoiseAlert` with `recursiveSound:451` made iterative with the 512-entry work stack of 2-byte entries [R `LEVELS.md` 5.5], `P_CheckAmmo:376`; helpers `startSound`, `argMo`, `setMoState`, `signExt4`, `signExt0`, `fireSomething` | 894 / 1,200 | `P_MovePsprites` (every tic), `P_NoiseAlert` (each shot), `checkAmmo`; synthetic: the deepest floods of E1M2 and E1M3 (93 [M: M9]) with every two-sided line open, an empty weapon | a closed opening (openrange 0) let through (the captured floods); a work stack of 80 (E1M2's flood stops, as milestone 9 planted); the bob's x from the sine (wave 3: the flood's order cannot change its stamps, `p_pspr65.s:445-449`, and the weapon order is `P_SwitchWeapon`'s, milestone 11's: `pspr.md` R7) |
| `evworld` | `p_doors65.s`: `EV_DoDoor:445`, `EV_VerticalDoor:622` (keys, reopen), `newDoor:520`; `p_plats65.s`: `EV_DoPlat:260` (the busy floor test, the plat's list field none), helpers `doorArg`, `setDir`, `topLowest`, `setTop`, `edLine`, `edSec`, `edSound`, `platArg`, `sectorArg`, `platSound`, `setHigh`, `setLow`, `plSec` | 1,223 / 1,600 | Every captured call (newgame's door, the demos', the tour's); synthetic: every door and plat special of `usetab`/`crosstab` on every line of the nine maps that has it, through `P_UseSpecialLine` or `P_CrossSpecialLine` by `--call` | the door's top without `- 4 × FRACUNIT`; the plat's low from the other finder; a plat started on a sector whose `floordata` is set (synthetic: the line used twice) |
| `look` | `p_enemy65.s`: `A_Look:512`, `lookForPlayers:385`, `behindFast:2154` (its `bfTab`), `A_FaceTarget:1749`, `checkMeleeRange:1023`, `checkMissileRange:1056`, `P_CheckMeleeRange:1001`, `P_CheckMissileRange:1007`, `A_Scream:2017`, `A_XScream:2040`, `A_Pain:2046`, `A_Fall:2054`, `A_PlayerScream:2070`; `p_attack65.s`: `P_RadiusAttack:876`, `PIT_RadiusAttack:799`; helpers `angleToAT`, `distanceAT`, `faceTarget`, `loadTarget`, `randMod`, `startSound`, `blockPair`, `absDelta` | 1,729 / 2,300 | `A_Look` (demo3 5.3 a tic [M: VC]: 300 by path), the range checks; synthetic: `P_RadiusAttack` from a barrel (no demo calls it [M: CALLS]) with things around it, one behind a wall | `behindFast`'s 90° edge on the other side; the missile range not halved for its type; the shadow's `P_Random` shift; the radius damage's distance not clamped at 0 |

#### Wave 4

| Part | Routines [R file:line] | Up. / native B | Checkpoint | Planted bugs |
| --- | --- | --- | --- | --- |
| `path` | `p_path65.s`: `P_PathTraverse:186`, `ptBody:226` (the block steps, `validcount++`, the early traversal with no guard and its limit `(M - 2) × K` [R `p_path65.s:594-645`]), `traverseTo:772` (`P_TraverseIntercepts`: the nearest first, ties by the list's order), `ptStuck:832` (the no-step case and its copies), `offLine:436`, `axisStep:474`, `early:594`, helpers `fromOrigin`, `a1Shr7`, `callTrav` (the `TRVTAB` dispatch) | 1,239 / 1,600 | Every captured call's endpoints and flags, from the captured state, with the recording traverser (3.5) in both machines, and with a traverser that stops at the k-th intercept (k from 1 to the count); **acceptance 6** (5.2): long dense traces of more than 64 intercepts | the early limit one block late (stamps, the k-stop runs); ties by the last; more than 64 intercepts handled as the C (none) instead of upstream (acceptance 6); the start not moved off a block line |
| `trymove` | `p_map65.s`: `P_TryMove:326` (the floor, ceiling, step and drop-off rules, the move: `overStep:440`, `mvNodes:860` with its shortcut, `spec:926` the crossed special lines through `P_CrossSpecialLine`), `lessHeight:421`, `specLine:1011`; `p_spawn65.s`: `P_NightmareRespawn:1126` (back at the place of its death, not its spawn point [R `p_spawn65.s:1121-1124`]), helpers `nmArg`, `nmXY`, `subFloor`, `fog` | 1,164 / 1,500 | `P_TryMove` (demo3 25,655 [M: CALLS]: 600 by path, the shortcut's both branches, and `mvNodes`' `LR_USE` branch, whose `P_CreateSecNodeList` takes the record without stamping lines (fact 4)); synthetic: a drop-off, a 24-unit step, two special lines crossed at once, a nightmare respawn (the generated nightmare stream) | the shortcut without `validcount++`; `LR_USE` not set (line stamps); `spechit` walked from the first; `MF_DROPOFF` ignored; floorz set before the step test |
| `planes` | `p_floor65.s`: `T_MovePlaneFloor:90`, `T_MovePlaneCeiling:142` (crush, the restore on a block), `checkSector:330` and `changeSector:395` (`P_ChangeSector` over the sector's touching things with `visited`: `heightClip:450` = `P_ThingHeightClip` through `P_CheckPosition`, corpses to gibs, dropped items removed, a shootable thing that does not fit holds the plane; upstream has no crush damage: `docs/game-parts/planes.md` 1.2), `T_MoveFloor:578`; helpers `restore`, `planeArgs`, `minusSpeed`, `plusSpeed`, `saveLast`, `setPlaneT`, `secArg`, `loadNode`, `nodeArg`, `thingArg`, `floorArg`, `floorSector`, `floorSpeed`, `sectorSound` | 1,222 / 1,600 | Every captured `T_MoveFloor` and plane move (the doors' through synthetic door states until `movers`); synthetic: a door closing on a monster, a crushing ceiling over a corpse and over an item | things visited by the sector list, not the node list; the move not undone when blocked; `visited` not reset |
| `evfloor` | `p_floor65.s`: `EV_DoFloor:815` (each type E1's lines use), `EV_BuildStairs:1057` (the steps by texture and tag), `EV_DoDonut:1233`, `newFloor:922`; helpers `lineStart`, `nextTagged`, `secOf`, `secArg2`, `floorField`, `floorDown`, `floorUp`, `floorArgFL`, `setDest`, `sameAsFloor`, `underCeiling`, `stairStep`, `nextStep`, `lineSector`, `sectorNum`, `s2Arg`, `s3Arg`, `s3Floor`, `halfSpeed` | 1,159 / 1,500 | The few captured calls; synthetic: every floor, stairs and donut special on every line of the nine maps that has it, by `--call` | stairs following the other side; the donut's outer floor height; the turbo speed; the destination from the next highest instead of the lowest |
| `teleport` | `p_telept65.s`: `EV_Teleport:51` (the destination by tag through the thinkers, the fogs, the angle, momentum and reaction time); `p_map65.s`: `P_TeleportMove:3420` (the stomp through `P_BlockThingsIterator` and `stompThing:3548`); helpers `fogSound`, `times20`, `thingArg`, `destArg`, `destination`, `tpThing`, `farFrom` | 1,130 / 1,500 | Synthetic mostly: every teleport line of the nine maps (special 97 [R `p_switch65.s:598`]) crossed by the player and by a monster, a thing at the destination; the captured ones of the generated streams | the destination found from the last thinker; the fog's z; the reaction time given to a monster; a stomp of a thing that is not shootable |

#### Wave 5

| Part | Routines [R file:line] | Up. / native B | Checkpoint | Planted bugs |
| --- | --- | --- | --- | --- |
| `attack` | `p_attack65.s`: `P_AimLineAttack:639`, `PTR_AimTraverse:668`, `P_LineAttack:78`, `PTR_ShootTraverse:227` (lines: `shootSpecial:936` for gun specials, the sky, the puff's place `puffPos:1019`; things: blood or puff, `P_DamageMobj`); helpers `traceSetup`, `endPoint`, `traceRun`, `loadIntercept`, `opening`, `rangeDist`, `rangeMul`, `lineSectors`, `sideAddr`, `sideSectors`, `sectorsDiffer`, `shootable`, `rawSlope`, `thingHead`, `thingFoot`, `thingPtr`, `mul3`, `thingTop`, `thingTopRaw`, `ceilBelowZ`, `thingBottom`, `thingBottomRaw`, `slopeTo`, `slopeOf`, `traceAt`, `puffArgs`, `spawnPuff` | 1,877 / 2,500 | `P_LineAttack` (DEMO1 295), `P_AimLineAttack` (DEMO1 296) [M: CALLS]; synthetic: a shot into the sky, at a gun-activated line, along a wall | the aim's top and bottom slopes swapped; the puff 4 units early; a gun special on a line that is not one; damage before blood |
| `player` | `p_user65.s`: `P_PlayerThink:63` (noclip, the death think `fixedSquare:548`, weapons pending, powers' counts, `specialSector:717`: damage floors with `P_Random` and the leveltime mask, secrets, the exit), `movePlayer:250`, `calcHeight:378` (`P_CalcHeight`: bob, view height), `angleToAttacker:679`; `p_use65.s`: `P_UseLines:39`, `PTR_UseTraverse:162`, `PTR_NoWayTraverse:218`; helpers `countDown`, `blink`, `argMo`, `moSector`, `onGround`, `bobAndThrust`, `addMom`, `thrustMul`, `hurt32`, `times64`, `useRun`, `useArg`, `lineArg` | 2,131 / 2,800 | `P_PlayerThink` (every tic: 600 by path), `P_UseLines` (all 56 [M: CALLS]); synthetic: a dead player turning to the attacker, nukage with and without the suit, a use on a locked door, E1M8's sector special 11 at health 11 and 10 with and without god mode (the exit: no stream takes it, review 14) | the bob's square overflowing differently (its last carry dropped); the view height clamped before adding the delta; special 11 exiting at health 11. Lean (wave 5 as integrated, `player.md` R6): the floor damage's mask `$0F` and the use range doubled are not planted; the synthetic `nukage-16` and the captured `P_UseLines` calls are the checks that would catch them |
| `xymove` | `p_mobj65.s`: `P_XYMovement:1273` (the half steps of a big move, `P_TryMove`, the slide for the player, a missile into the sky or a wall, friction and the stop), `slideMove:67` (`P_SlideMove`: the three traces, `PTR_SlideTraverse:458`, `hitSlideLine:586`); helpers `clampMove`, `isBig`, `wholeMove`, `halfMove`, `skyHit`, `quarterOut`, `slow`, `frictionAP`, `frictionNear`, `friction`, `corners`, `slideTrace`, `bestMul`, `addCoord`, `bobClip`, `labs` | 2,367 / 3,100 | `P_XYMovement` (DEMO1 7,214: 600 by path, every slide) | friction in the air; the second trace from the other corner; a missile's sky test without the ceiling pic; the half steps' y before x |
| `missile` | `p_spawn65.s`: `P_SpawnMissile:533` (the angle, a shadow target's `P_Random`, `momz` by the distance with the 32-bit divide, `checkMissile:850`: tics noise, a half step, `P_TryMove`, the explosion); helpers `srcArg`, `srcAbove`, `seeTarget`, `thSpeed`, `destDelta`, `angleMom`, `speedMom`, `halfMom` | 593 / 800 | Every captured monster missile (imps in all demos); synthetic: a missile spawned inside a wall | `momz` rounded the other way; the shadow `P_Random` taken for a visible target; the tics noise skipped |
| `chasemove` | `p_enemy65.s`: `pMove:100` (`P_Move`: the speeds table, the try, blocked doors through `P_UseSpecialLine`), `P_TryWalk:321`, `P_NewChaseDir:1118` (`doNewChaseDir:1201`: the directions with `P_Random`, the turnaround), `avoidDropoff:1402` with `PIT_AvoidDropoff:1529`, `speedStep:2278`; helpers `mulSpeed`, `umul16x`, `speedTab`, `speeds`, `tryWalk`, `newChaseDir`, `setDir`, `absGreater`, `absD`, `boxPlus`, `boxMinus`, `blockOf`, `boxAbove`, `boxBelow`, `sideFloor`, `signed`, `times32` | 2,211 / 2,900 | `P_NewChaseDir` and `pMove` as entries (inside `A_Chase`: 300 each by path) | `P_Random` before the direct test; the turnaround table; the diagonal tried after the straight ones |

#### Wave 6

| Part | Routines [R file:line] | Up. / native B | Checkpoint | Planted bugs |
| --- | --- | --- | --- | --- |
| `movers` | `p_doors65.s`: `T_VerticalDoor:55` (up, down, waiting, closing on a thing and back, the light tag `partLight:244` (no door of the demos has one: synthetic, `docs/game-parts/movers.md` 3)); `p_plats65.s`: `T_PlatRaise:39`; helpers `sectorArg`, `doorSound`, `moveCeiling`, `dlSec`, `mulExt`, `movePlat`, `stopWait`, `waitStatus`, `setStatus` | 1,094 / 1,400 | Every thinker call of the door and plat kinds (newgame's door, the demos'); synthetic: a door closing on a monster, a plat waiting with a thing on it | the door's wait not `VDOORWAIT`; the plat's status changed before the sound; the reversal without its sound |
| `wfire` | `p_spawn65.s`: `P_SpawnPlayerMissile:640` (the aim retries); `p_pspr65.s`: `A_FirePistol:1108`, `A_FireShotgun:1121`, `A_FireCGun:1139`, `A_FireMissile:1005`, `A_Punch:767`, `A_Saw:802`, `gunShot:1055`, `bulletSlope:1015`; helpers `aim`, `meleeAngle`, `spread`, `meleeAttack`, `angleToTarget`, `randMod`, `useAmmo`, `aimAt`, `notRefire` | 964 / 1,300 | Every captured weapon action (through `ACTTAB` entries); synthetic: the chainsaw beside a target, berserk punch, a rocket if E1's things give one | the shotgun's pellets in another order; the spread taken on the first shot; the aim retries' order |
| `tic` | `g_game65.s`: `G_Ticker:563` (reborn, `P_MapEnd`, the actions with the load protocol (3.4), the command, demo playback, pause, `WI_End`, the state tickers); `p_map65.s`: `P_MapEnd:3296` (review 9); `p_think65.s`: `P_Ticker:185`; `p_tick65.s`: `P_RunThinkers:134` (the walk over the planes, kinds, `CLEAN`, deferred removal, the state end's action), `P_MobjThinker:540`, helpers `mobjArg`, `stillMobjThinker` | 1,155 / 1,500 | `P_MobjThinker` (every call), `P_RunThinkers` and `G_Ticker` (one a tic), each from both fills; then the first 140 tics of demo3 at tic level (3.6's harness) | next read after the call (a removed thinker's next); `CLEAN` kept after a momentum change; leveltime raised before the specials; the command copied while paused. Lean (wave 6, `tic.md` 1): three planted (the next read after the call, leveltime before the specials, the command copied while paused); `CLEAN` kept after a momentum change is the movers' clear (the walk only sets `CLEAN`), and the load returned without `G_LOADACT` cannot be seen (flow's `doLoadLevel` sets it too) |
| `chase` | `p_enemy65.s`: `A_Chase:621`, `A_PosAttack:1885`, `A_SPosAttack:1911`, `A_TroopAttack:1945`, `A_SargAttack:1968`, `A_CyberAttack:1982`, `A_BruisAttack:1992`, `A_Explode:2060`, `A_BossDeath:2079` (E1M8: the floor of tag 666); helpers `lineAttack`, `aimLine`, `spreadAngle`, `damageTarget`, `spawnMissile` | 1,400 / 1,800 | `A_Chase` (demo3 6.1 a tic [M: VC]: 600 by path), every attack; synthetic: `A_BossDeath` on E1M8 with the last baron | `movecount` decremented after the move; the attack's `P_Random` order; `A_BossDeath`'s floor type |

### 2.5 What every part delivers

1. Its sources and fragment (3.3); every call to another routine through
   `FCALL` (4.3), every object access through the API (1.1).
2. Its checkpoint passing (2.4), with `build/native/game/<part>/report.json`
   (cases, eligible and run, per entry; failures 0; cycles median and worst
   on `f121` and `fastpath`; native bytes against its budget; stray writes
   0; the lowest S).
3. Its planted bugs caught, in its test file; the test file skips with a
   message when `build/` lacks the captures, a2vm or ref816, writes only
   under `build/native/game/<part>/` (its own `OUT` and `GEN`, as
   `level.mk` gives each image [R `src/native/level.mk:47-50`]) and
   temporary directories, and so needs no line of `tests/README.md`'s
   race table. **Shared outputs are read only** (review 12): the
   generated includes, the manifest `native-game-1.json`, `game.cfg`, the
   survey and the shared captures under `build/native/game/shared/` are
   made by the skeleton and remade only by the integrator between waves;
   a part test that finds them missing or older than their inputs skips
   with a message naming the command that makes them, and never rebuilds
   them. A part that needs a change of one asks in its request file.
   Its `args.json` declares each entry's inputs and outputs (2.4).
4. `docs/game-parts/<part>.md` (3.8): what it built, what it asks of the
   shared files, the exclusions it relies on (each must already be in 3.5
   or 3.6, or asked for there with its evidence), results, open points.
5. `build/` growth reported (at most 250 MB a part [A]: the captures
   dominate, 3.5).

## 3. The skeleton

One stage before wave 1, by one builder (or two: the 65C02 side and the
host side), so that no part ever edits a shared file. Its estimate:
about two of a part's 1.5-hour units for the runtime and the layouts, two
for the harnesses, one for milestone 9's move to the final layouts and
its re-verification [A].

### 3.1 What it builds

| File | Content |
| --- | --- |
| `tools/native/glayout.py` | The layouts of section 1 (banks, records, planes, globals, caches, zero page, tic scratch, W's map, the groups); `gen/ggame.inc` for ca65; the manifest `native-game-1`; `game.cfg` (4.1); the dispatch tables' include `gen/gdisp.inc` and the placement include `gen/gplace.inc` (each routine's image and group, 4.3); the part table (2.4) as data; `check()` (no region used twice, every part's zero page and scratch inside its allowance, every canonical field placed or excluded by name) |
| `tools/native/gcallgraph.py` | 2.1's reading as a tool; `--check` (the rule of 2.2 for the built parts), `--reach ROUTINE` (the dispatch targets a routine can reach, for eligibility), `--stack` (the static depth of every call chain in bytes, with the IRQ's 24, against the budget of 4.5) |
| `tools/native/gplace.py` | The placement (4.3): core and groups from the measured heat, the call graph and the native sizes |
| `src/native/game.mk`, `src/native/game/README.md` | The makefile (3.3) and the parts' conventions |
| `src/native/gobj.s` | The object API and its caches (3.4) |
| `src/native/gcall.s` | `FCALL`'s stub (the code paging), the five dispatchers' common call (`DCALL table, number`) and the unbuilt-entry stop (3.4) |
| `src/native/gdriver.s` | The test driver (card `$E000`, as `ldriver.s`): lockstep-schedule mode, the load protocol, a frame of the native front end (or the whole renderer) between tics, the render inputs, the phase switches, the snapshot events, routine mode (3.4) |
| `src/native/ghook.s` | The hooks: the sound event log, `AM_Stop`, `ST_Start`, `HU_Start`, `AM_Ticker`, `F_LoadScreen`, `Z_CheckHeap`, `D_AdvanceDemo`, `D_PageTicker`, `W_StartInter`'s pictures and music (then `flow`'s `WI_Start`), `I_GetTime` (the stream's value in test builds), `W_StartFinale` and `F_Ticker` (stops `GS_FINALE`), `I_Error` as stop codes `GS_*` (review 7, 9) |
| Milestone 9's game core | `gthink.s` (the planes, the zone's free list, the specials' free lists, `G_MOHWM`), `gspawn.s` (`P_SpawnMobj`'s general z: `ONFLOORZ`, `ONCEILINGZ`, a given z [R `p_spawn65.s:72-262`]; a mobj with no function kept off the thinker list, upstream's `addIfFunc` [R `r_list65.s:919-931`]), `gweap.s` (`setPsprite` through `ACTTAB`), `gvalid.s` (linked into the render image, 1.7; its release wrap clear empties the line and sector caches first), **all of `gthink.s`, `gspawn.s`, `gpos.s`, `gspec.s` and `gvalid.s` on the object API**, with no `g_get`/`g_put` of a cached kind left outside `gobj.s` (review 2), `gpos.s`'s `gp_secnodes` with upstream's `LR_USE` path (`getSectors` [R `p_map65.s:1126`] on the recorded lines, no block walk, no stamps; `MP_MODE` as its argument) (review 5), the setup's clear of `LR_OK` [R `p_setup65.s:104`], `lgeom.s` (the `GTABS` step: `LNSECF`, `LNSECB`, `RJROW` into `LVS`), `lstore.py` (the step in every map's program), `rframe.s` (`jsr gv_inc`) |
| `tools/native/gamecap.py`, `gameroutine.py` | The routine-mode harness (3.5) |
| `tools/native/ticcap.py`, `ticgen.py`, `ticrun.py`, `gcanon.py` | The tic level: the reference's per-tic dumps, schedules and streams; the stream generator; the lockstep runs and their comparison; the comparison's rules and exclusions (3.6, 3.7) |
| `tools/native/grun.py` | a2vm runs of the game images (as `lrun.py`): poisoned machines, the narrowed write log and its allowed sets, snapshots, timing |
| `tools/bridge/schema.py`, `upstream.py`, `layout.py` | 1.11's additions, with tests; every existing manifest and test unchanged |
| `tools/a2vm` | `--snapshot-stream FILE` with `--snapshot-limit BYTES`: every snapshot of the run (range snapshots, 3.6) into one bounded stream, `ref816 --dump-stream`'s format; a run that would pass the limit fails (status 2); its tests in `tests/test_a2vm_harness.py`; nothing else changes |
| `docs/game-parts/<part>.md` | One file a part, from the template of 3.8 |
| `tests/test_native_game_skeleton.py` | The skeleton's checkpoint (3.9) |
| `MEMORY_MAP.md` section 17 | Every region this milestone adds (section 4) |

### 3.2 The layouts module and the generated includes

`glayout.py` imports `llayout.py` and `rlayout.py` (one source of every
address, as milestone 9 did [R `LEVELS.md` 4.1]) and adds section 1's
places and section 4's. It writes:

| Output | Content |
| --- | --- |
| `gen/ggame.inc` | Every record's offsets, every global, every bank, the caches' geometry, the zero page (`GA_*`, `GT_*`, the API's pointers), each part's scratch base, the stop codes, upstream's constants the parts need (`CONST_*` of `offsets.inc` and `info.inc`, read through the bridge's `incfile.py`, never typed in) |
| `gen/gplace.inc` | For every routine of 2.4: its image (`CORE` or a group), its group's slot; `FCALL` reads it (4.3) |
| `gen/gdisp.inc` | The five dispatch tables: each entry the target's address and group when its part is built (the part table's `built` set), else the unbuilt stop |
| `build/native/game/shared/native-game-1.json` | The manifest (1.11) |
| `build/native/game/shared/game.cfg` | ld65's configuration: W's areas, the core, each group's area at its slot's address with its own output file, the card's segments as the render images have them |

The skeleton makes all of these once, in `build/native/game/shared/`
(the includes in its `gen/`), and the integrator remakes them between
waves; part builds and part tests only read them (2.5, review 12). A part
asks for a change of these (a field, a scratch byte, a group move) in its
request file; the integrator applies it between waves (3.8).

### 3.3 The makefile and the parts' fragments

`src/native/game.mk` builds the game images and every test image. It
includes `src/native/game/*/part.mk`; a fragment names its part, its
sources, its wave and its entry routines:

    PART := look
    WAVE := 3
    look_SRC := game/look/look.s game/look/range.s
    look_ENTRIES := A_Look lookForPlayers P_CheckMeleeRange ...

| Target | What |
| --- | --- |
| `make -f game.mk part P=look` | The part's test image: milestone 9's game core, the skeleton's runtime, every part of an earlier wave, and `look`; into `build/native/game/look/` |
| `make -f game.mk wave W=3` | Every part of waves 1-3 (the integrator) |
| `make -f game.mk game` | The lockstep build: all parts, `LOCKSTEP`, `VCWRAP_UPSTREAM` |
| `make -f game.mk gprof` | The same with cost phases by subsystem (5.4) |
| `make -f game.mk release` | No `LOCKSTEP`, the wrap fix on |
| `make -f game.mk sizes` | Each part's bytes against its budget, each image's and slot's fill |

A part's sources assemble with `ggame.inc`, `gplace.inc`, `gdisp.inc`,
`math.inc`, `rlayout.inc`, `llayout.inc`, `lgame.inc`; a link that
overflows an area fails (as `level.cfg` does [R `LEVELS.md` 4.1]). Parts
of one wave never link together before the integrator's merge: each
part's test image has the earlier waves and itself.

### 3.4 The native runtime

**The object API** (`gobj.s`, core), its sizes [A]:

| Call | Does | Cache |
| --- | --- | --- |
| `mo_get` (slot in A:X) | The mobj's `RTHING` and groups A, B, C into a line; `GC_MP` its pointer | 8 lines of 96 B, LRU, write-back by group (4 dirty bits) |
| `mo_dirty` (group mask) | Marks groups to write back | |
| `sec_get` (sector in A) | The `LVMAP` render record and the `LVG1` game record; `GC_SP` | 8 lines of 48 B |
| `ln_get` (line in A:X) | The `LVG0` record and the line's two sectors from `LVS`; `GC_LP` | 8 lines of 34 B |
| `sp_get` (special handle) | The record; `GC_XP` | 4 lines of 32 B |
| `nd_get`, `sg_get`, `ss_get`, `bl_get` | A node, a seg, a subsector, a block's list (256 B at a time): read-only fetches into fixed buffers, no cache | |
| `go_flush` | Every dirty line back, then every line empty (the render phases overwrite the caches' main memory, 4.1); called at the tic phase's end, before a load, before a frame and at a routine-mode call's end | |
| `pl_*` macros | The walk's planes in W (1.3) | none needed |

A line's pointer stays valid until the next `*_get` of the same kind
that misses (the LRU never evicts the four most recently got of each
kind); a routine that needs a record across calls keeps
its handle and gets it again. Upstream's own pointer use is the guide:
the parts hold handles where upstream holds `[dp],y` pointers across a
call.

**The code paging** (`gcall.s`, 4.3): `FCALL target` is a macro; when the
target's image is the caller's (or the core) it is `jsr target`; else
`jsr fc_call` with three inline bytes (the target's group, its address),
and the stub saves the group the target's slot holds (one byte on the
stack), loads the target's group into the slot when another group is
there (`far_pload`'s page runs from `GCODE0-1` [R `far.s:329-343`]),
calls the target, and **on return restores the saved group if the slot
now holds another, whoever the caller is** (review 1). Reloading only
the caller's group was wrong: a core routine that pages a group into a
slot can return into a paged caller of that slot further up, as
`A_TroopAttack` (slot 1) → `P_SpawnMissile`/`checkMissile` (slot 1) →
`P_TryMove`, `checkPos`, `PIT_CheckThing` (core) → `P_DamageMobj`
(slot 1) shows, and so can A (slot 1) → C (slot 2) → D (slot 1). The
restore may load a group no active frame needs; a lazy restore (only
when a frame of the evicted group is active, from a count a slot) is an
integrator lever, measured by phase 28 (5.4). The dispatch tables call
through `fc_call` too.

**The driver** (`gdriver.s`, card `$E000-$EDFF` in test builds, where
`ldriver.s` and `lboot.s` run [R `MEMORY_MAP.md` 15-16]):

| Mode | Does |
| --- | --- |
| Lockstep | From a pre-state at a `P_SetupLevel` entry (milestone 9's E point, 3.6): the load image, `nl_setup`, then the tic image and `G_Ticker`'s resumption; then forever: at each `G_Ticker` entry `go_flush` and the planes written back (test builds only: the caches are write-back, so RamWorks is whole only after a flush; a flush changes no state) and a snapshot event, the tic, `gametic + 1`, and after the tic the schedule's frame when its gametic is reached: `go_flush`, the render inputs (the player's view, its sector's light, the psprites' sprite and frame and offsets, the invisibility power, extra light, the fixed colormap, `TEXTRANS`, `NUKAGE`: what `framestate.py` injects today [R `RENDER-MASKED.md` 2.3]), then the front end (`FRONT`: milestone 7's frame, which writes `validcount` and the sector stamps) or the whole frame (`FULL`: milestone 8's, for acceptance 5), then the tic image again |
| Load protocol | The load is reached inside an action (`loadLevel`, `doNewGame` → `initNew`, `doPlayDemo` → `readDemoHeader` → `initNew`, `doWorldDone`, each ending in `doLoadLevel` → `bmLoad` [R `g_game65.s:635-669`, `:877-884`, `:1100-1142`, `:1205-1311`]). Natively `flow`'s action runs up to the load (`doLoadLevel`'s part before `bmLoad`) and `G_Ticker` (part `tic`) returns `GT_LOAD` with **the action that started it**, taken from `gameaction` before the load (`GA_LOADLEVEL`, `GA_NEWGAME`, `GA_PLAYDEMO`, `GA_WORLDDONE`; the load game is milestone 11's [R `g_game65.s:630-632`]), in a persistent byte `G_LOADACT`; the driver flushes the caches and empties them, saves the planes, loads the load image, runs `nl_setup`, reloads the tic image and the planes, and calls `g_resume`, which runs the continuation of that action (`flow`'s): `doLoadLevel`'s tail (`gameaction` 0, the `Z_CheckHeap` hook, the keys up, the `ST_Start` and `HU_Start` hooks), then the action's own tail (`GA_NEWGAME`: `gameaction` 0, `ST_Start`; `GA_PLAYDEMO`: `player.cheats` 0, `gameaction` 0, `usergame` 0, `demoplayback` 1, `starttime` from the `I_GetTime` hook; `GA_WORLDDONE`: `gameaction` 0), and then re-enters the action loop at its test of `gameaction` [R `g_game65.s:574-582`], as upstream does when the action returns. Nothing but the persistent globals lives across the load (the load image takes W and the zero page's overlays [R `MEMORY_MAP.md` 15]). A run that starts at a `P_SetupLevel` entry takes `G_LOADACT` from the reference's `gameaction` there, which upstream clears only after the load (review 3) |
| Routine | The test image, the pre-state (the bridge's port writer into the poisoned machine), the arguments into `GA_*`, the planes in, `jsr` the routine, `go_flush`, the planes out, a snapshot event |
| Stops | `GS_*` codes in main (after `LV_STATUS`), then `BRK`, as the renderer and the loader stop [R `LEVELS.md` "Stage B as built"] |

**The hooks** (`ghook.s`): `S_StartSound`, `S_StartSound2`,
`S_StopSound` append (tic, kind, sound, origin handle) to the event log
in `GTEST` in test builds and return; nothing in the release until S4.

### 3.5 The routine-mode harness

`gamecap.py` and `gameroutine.py`, the method milestones 7-9 proved
[R `RENDER.md` 4.1; `LEVELS.md` 5.4]:

1. **Survey** (once a capture run, made by the skeleton and extended by
   the integrator between waves, read only for the parts, 2.5): `ref816
   --call-log` of every entry routine of 2.4 (entry and return, with
   `G_Ticker`'s gametic) and of every dispatch target (entry only,
   `jumps=1` for the `JML [dp]` targets [R `tools/ref816/README.md`
   "--call-log"]); each call gets its tic, its parent and the dispatch
   targets it reached. Runs: demo3, DEMO1, DEMO2 (the title loop with the
   lump [R `tools/ref816/README.md` "--wad, --lump and lumps.py"]),
   newgame, tour, and from wave 2 on the ten generated streams.
2. **Selection** by part, 2.4's minimums; the coverage report lists, for
   each entry, the paths taken (`ref816 --call-log` of the part's
   declared path labels, entries only, as `routinecap.py`'s `PATHS` [R
   `tools/native/routinecap.py:17-20`, `:162`]) and the paths no call takes,
   which the part covers by synthetic cases.
3. **Capture**: `ref816 --capture` of the chosen hits [R
   `tools/ref816/README.md` "--capture"]; each raw capture is distilled at
   once into a case (the game-state ranges of the bridge's regions and the
   level window, xor'ed against the base dump of its tic, which is kept
   once a tic; the footprint; the call's registers and arguments, zlib)
   and the raw files deleted. Budget [A]: about 30 KB a case, 2 GB for
   every part's cases.
4. **Run**: `grun.py` builds the pre-state from the case (the bridge's
   `Reader`, then the port writer through `native-game-1` into a machine
   poisoned with `$A5` or `$5A`), the inputs from the part's
   `args.json` (each entry's upstream registers, direct-page symbols
   (`dp:SYMBOL`, `_Dp` and the others: `TP`, `AP`, ...) and near symbols
   (`tmx`, `tmy`, `MP_MODE`, ...) to their named native counterparts,
   and its declared outputs back [R `tools/ref816/calls.py:11-17`], review
   6), runs the routine under `f121` and `fastpath`, with the write log.
5. **Compare** (`gcanon.py`, mode `routine`): the native canonical state
   after the call against `ref816`'s (the case's entry state plus its
   writes), exact, and every declared output (step 4) against its
   counterpart, exact, whether upstream keeps it in canonical state or in
   its scratch, with these exclusions only:

| # | Excluded in routine mode | Why |
| --: | --- | --- |
| R1 | Tic scratch, zero page outside the persistent bytes, W, the stack below the caller's S | The routine's own scratch: not state between calls |
| R2 | Upstream's scratch of the game units (`scratch`, `trace scratch`) but the declared outputs of step 4 | The bridge's exclusions [R `tools/bridge/README.md` "The schema"]; a result upstream returns in scratch is an output and compared (review 6) |
| R3 | The kind cache (mobj byte 11, the `CLEAN` bit) | A cache by construction (1.2) |
| R4 | The dead guard's state: `line.gstamp`, `GW_TAG`, `G_ID`, the guard counts | Written only by the guard, which the release never calls [R `p_path65.s:612-614`]; part `tracet` shows with its captures that no release call writes them, or names the writes (they cannot change a result: only the guard reads them) (wave 3: part `tracet`'s 160 sampled calls of `traceLines`, `traceThings`, `sideSetup` and `longTrace` write none of them, and `G_IDT` is 0 at each of its 40 `traceLines` calls; the release writes them only in `P_SetupLevel`'s `stz G_ID` [R `p_setup65.s:137`], `P_InitFlood`'s `GW_TAG` and `GW_TAB` at a load [R `p_pspr65.s:1306-1318`] and `ptBody`'s `stz G_IDT` (`G_OFS`) before each walk [R `p_path65.s:271`]: `docs/game-parts/tracet.md` "The dead guard") |
| R5 | `TP_HW`, `PI_PREV*` | Upstream's caches that change no result: `poolTake`'s scan start [R `p_spawn65.s:1252-1270`] and `R_PointInSubsector`'s last point [R `r_iigs65.s:603-605`, `:671-696`]; milestone 9's setup checks covered both |
| R6 | The sound channels | Outside the canonical model [R `LEVELS.md` 5.2 exclusion 11]; the sound events are compared instead, as a report |
| R7 | The bridge's problems about the 16 link bytes (`snext`, `sprev`, `bnext`, `bprev`) of a mobj on no list of their kind (between `P_UnsetThingPosition` and its new place, or inside `P_RemoveMobj`), and NULL block links of a mobj `mvBlock` put off the map; only those problems, every canonical field still compared (wave 1 as integrated: part `mobjstate`'s named rule `stale_link_problems()`, `docs/game-parts/mobjstate.md` R7) | Upstream's `unlist` leaves a thing's own links as they were [R `p_map65.s:717`]: they name no list, so the reader reports them though no canonical field depends on them |

6. **Eligibility**: a case enters a part's checkpoint when every dispatch
   target it reached is built at that wave (`gcallgraph.py --reach` and
   the survey). The report gives, per entry, the cases eligible now and
   the cases waiting, by the target they wait for.
7. **Timing**: each call's cycles on both profiles; per entry the median,
   p99 and worst, and the far windows and paging loads it took.

Speed [A on M: about 0.6 s a run, `RENDER-MASKED.md` 4.5]: 600 cases ×
2 fills × 0.6 s = 12 minutes of CPU, under 2 minutes at 9 jobs.

### 3.6 The tic-level harness: lockstep-schedule mode

**The reference** (`ticcap.py`): each run's `ref816` script runs with
`--dump-at pc=G_Ticker,ranges=<the game state>` streamed through a pipe
(never stored [R `tools/ref816/README.md` "--dump-at and the dump
stream"]), `--mark` of `R_RenderPlayerView` with the gametic (the
schedule: the gametic at each 3D frame), and the call logs of the
stream's events (3.7). The decoded canonical state of each tic is kept
as one digest a kind (SHA-256 of the kind's canonical JSON); a failure
reruns the reference to the tics it needs and keeps those whole. The
schedule and the stream go into the test bank `GTEST` of the native
machine.

**The native run** (`ticrun.py`): `grun.py` runs the `game` build in
lockstep mode from the run's start (the pre-state at the first
`P_SetupLevel` entry of the run, written as milestone 9's setup checks
write it [R `LEVELS.md` "Stage C as built"], with the hint planes
re-keyed from upstream's table through the pool base of the coming setup
(1.8)), both fills, and **at every later setup of the run the same
re-keying** (review 4, 10): `ticcap.py` makes, from the reference's
state at each setup's end, a re-key record (the hint entry of every mobj
of the level by its native slot, through `_g_thingPool` for the pool and
by identity for zone mobjs; `CS_PREV1/2` as 1.8 gives them) and puts the
records in `GTEST`; in test builds the driver applies a setup's record
after its `nl_setup`. This is injected state with a reason, as the
renderer's `SPRBOUND` is [R `RENDER-MASKED.md` 0.3 row 3]: upstream's
values there depend on its zone addresses, which no native run can
know. The release applies nothing (risk 7). The run streams with
`--snapshot-stream` of the game-state ranges at each `G_Ticker` entry (a few hundred KB a tic [R `tools/a2vm/README.md`
"Range snapshots"]), read and digested as they come, never stored whole;
the sound event log and the same-pair hit log are part of each tic's
snapshot and the driver empties them after it, so `GTEST` holds only the
schedule, the stream and the re-key records.

**The comparison** (`gcanon.py`, mode `tic`): at every tic, every kind's
digest equal; at the first tic that differs, both states kept whole, the
canonical diff printed, and the bisection of `native-verification.md` 6.4
started: the reference's state at the tic before injected into the native
machine, one tic run, then the routine-mode cases of that tic's calls
(from a call log of that tic only) to find the first routine that
differs [R `research/native-verification.md` 6.4]. Exclusions, each in
`gcanon.py` with its reason and counted in the report:

| # | Excluded in tic mode | Why |
| --: | --- | --- |
| T1 | `line.r_validcount`; `line.r_flags` in runs with the `FRONT` frame | The renderer's fields: no game unit reads them (only `r_wall65.s`, `am_map65.s` and `p_setup65.s` name `OFS_LINE_R_*` [M: grep]); milestone 7's renderer keeps `ML_MAPPED` in `LNMAP` and has no `r_validcount` [M: grep of `src/native`]. `LNMAP` is compared against `r_flags`' `ML_MAPPED` in acceptance 5's `FULL` run, where the renderer writes it |
| T2 | R2-R5 above | As in routine mode |
| T3 | **The zone window** (narrowed by review 4 and 10): `mobj.sightline`, the hint planes, and the lines' `validcount` stamps (which then compare as "equal to `validcount`" or "older", not by value), from the first tic after one in which a zone mobj is `t1` of `P_CheckSight` (`GT_HINT`), or in which a zone mobj that `CS_PREV` names is removed (`GT_ZPREV`; `CS_PREV1/2` then also compare as "stale or not"), **to the run's next setup**, whose re-key record makes them exact again | Fact 3 and 1.8: upstream keys the hint and `CS_PREV` by the mobj's address, and a zone mobj's address is `Z_Malloc`'s, which the native slot is not. A setup that moves the pool base no longer opens a window: the re-key record covers it. The answer of every check does not depend on the hint (each sight case of part `sight` is also run with an empty hint and must answer the same), and the same-pair hit log is compared in the window too. A stamp older than `validcount` can matter only after a wrap of `validcount`: `ticgen.py` rejects a seed whose reference run wraps inside a T3 window (3.7), and for the fixed runs (demos, newgame, tour) the skeleton's S3 reports whether any wrap falls in a window (none can in the three demos: no wrap [M: VC]); a fixed run with one goes to the owner before the acceptance, never passes silently. Every other field stays exact in the window, sector stamps included |
| T4 | The tic command ring's entries other than the one `G_Ticker` reads | Input built ahead of the tic by `G_BuildTiccmd` (milestone 11); the entry read is compared as `player.cmd` after the tic |
| T5 | The zone allocator's headers, slack and free bytes | The bridge's exclusion [R `tools/bridge/README.md` "The schema"]; the native pools' free lists are compared as sequences where identity makes them state (the sector nodes [R `LEVELS.md` "Stage C as built"]) |
| T6 | Outside the canonical model: sound channels, music, the status bar, the HUD but `player.message`, the automap, menus, the title loop's page | Milestone 11 and S4 [R `LEVELS.md` 5.2 exclusions 11-12]; the sound events are compared per tic as a report |
| T7 | In the `FULL` run, a frame whose `RULES` is not 0 (a column seen from behind): its records and SHR | Owner question 13, a known difference [R `NATIVE.md` 15.1 row 13]; game state is not affected (the renderer writes no game state there) and stays compared |
| T8 | A tic in which the native divides by zero or meets the inputs `fixedDiv` of `p_trace65.s` never returns from (`docs/game-parts/tracel.md` R4) (`GT_DIV0` counts): the comparison of the run **ends** at that tic, reported by name as a known divergence, and a new run continues from the reference's state at the next `G_Ticker` entry (the bisection's injection, below), so the rest of the stream stays compared (review 10: a different quotient propagates, so excluding only that tic's fields could not pass) | Owner question 5 [R `NATIVE.md` 15.1 row 5]: our own result. No coverage run divides by zero [M: `tools/ref816/README.md` "Division by zero"]; `divscan.py` runs on every generated stream too, and the report names any such tic |

Everything else is compared exactly at every tic: every object of every
kind with its identity, the lists as sequences, every global of the
schema, `prndindex` and `M_Random`'s index, `validcount` and every sector
stamp, `CS_PREV` and the same-pair hit log, the line record `LR_*`, the `wi` counters, `TEXTRANS`, `NUKAGE`, the mobjs'
slots (no slot twice: the port reader refuses two objects in one slot [R
`tools/bridge/README.md` "The port's layout"]).

**The gates of milestone 9** [R `LEVELS.md` 2.6; "Verification of stage
C" defects 3-5]:

| Gate | Checked by |
| --- | --- |
| One `validcount` | 1.7's join; every tic's `validcount` equal with the native front end raising it |
| A zone mobj created, `LS_ZONE`, no slot twice | Generated stream G1 (E1M1 at UV: no free pool slot [M: POOL]) and `mobjstate`'s synthetic case; the report counts the zone mobjs of each run and their highest slot |
| The block walk's order on every move | Every tic's sector nodes, block lists and line stamps; `checkpos`'s corner cases |
| Bank `$21`'s tables | The skeleton's S4 (3.9) and every `sight` and `trymove` case |

### 3.7 The tic streams

| Stream | Source | Native input |
| --- | --- | --- |
| demo3 | The title loop to the demo's end (`lumps.demo_script` with DEMO3 under its own entry [R `tools/ref816/lumps.py:100-114`]): the "new script" of acceptance 1 | The lump in `DEMOB` (`DOOM1.WAD`'s DEMO3, checked equal to the release's resident one at `$10:8984` [R `tools/ref816/README.md` "--wad, --lump and lumps.py"]); demo playback reads it (part `flow`) |
| DEMO1, DEMO2 | The same with the lump placed (`--lump DEMO3:7E0000:...` [R `tools/ref816/README.md` "--wad, --lump and lumps.py"]) | The same |
| newgame, tour | `coverage/newgame.script`, `coverage/tour.script` | A stream file in `GTEST`: per tic the command `G_Ticker` will copy (from the reference's ring at the tic's `G_Ticker` entry); per tic the events since the last one: cheats (the call log of `m_cheat65.s`'s effects, as event numbers), the script's pokes (the tour's `_g_wminfo + 4` [R `coverage/tour.script:7-11`], as a canonical field and value written through the manifest), the menu's state (`menuactive`, `showMessages`), **the game actions the menu issues** (`G_DeferedInitNew` from the menu's new game and nightmare confirm [R `m_menu65.s:922`, `:1000`], by `--call-log` of `G_DeferedInitNew` with its caller and `d_skill`, applied as the call) (review 7); per run the values of `I_GetTime` the game reads (the `I_GetTime` hook, review 7). Demos and generated streams carry the same `I_GetTime` values and menu events |
| G1-G10 | `ticgen.py`: demo lumps of 2,000 tics | As demos |

**`ticgen.py`** writes a demo lump (DEMO3's header format, the chosen
skill and map) from a seeded policy: walk, run, strafe, turn, fire in
bursts, use often, change weapons through `BT_CHANGE`, and after a death
press use until the reborn. Each stream is first played on `ref816`, and
its coverage is measured there (the call log of 3.5's survey): deaths,
reborns, weapon changes, `P_UseSpecialLine` that started a special,
doors, plats, floors, teleports, zone mobjs, `P_RadiusAttack`, the
deepest flood, `P_PathTraverse` with more than 64 intercepts. Seeds are
searched on the reference only, until the ten streams together cover
every item at least once (the targets below); the reference is the truth
of any stream [R `research/native-verification.md` 6.2]. **A seed is
rejected** when its reference run lets `validcount` wrap inside a T3
window (3.6), or divides by zero (`divscan.py`), so that every
acceptance stream can be passed exactly (review 10).

| Stream | Map, skill [A] | Aimed at |
| --- | --- | --- |
| G1 | E1M1, UV | Zone mobjs from the first shot (fact 9), barrels (`P_RadiusAttack`) |
| G2 | E1M9, UV | Zone mobjs, a fight |
| G3 | E1M2, nightmare | Deaths and reborns (`RL_ON` reloads), nightmare respawn (at the place of death [R `p_spawn65.s:1121-1124`]); upstream has no fast monsters (review 14) |
| G4 | E1M3, hard | The deepest flood (93 [M: M9]), switches |
| G5 | E1M4, medium | Lifts, doors, strafing runs |
| G6 | E1M5, medium | Teleporters, slides along walls |
| G7 | E1M6, hard | The largest pool (449 [M: M9]), long traces |
| G8 | E1M7, easy | Damage floors, pickups of every kind |
| G9 | E1M8, UV | Barons, `A_BossDeath` if the policy kills both (no exit: E1M8's exit is the finale, out of scope; its sector special 11 is covered by part `player`'s synthetic cases, review 14) |
| G10 | E1M1, baby | Weapon changes and ammo, use on every reachable line |

### 3.8 Request files and the integrator

`docs/game-parts/<part>.md`, written by the skeleton with these headings
and kept by the part:

1. **Owner and wave.** The routines (2.4), the files.
2. **Requests.** Each a change to a shared file: what (a field, a scratch
   byte, a group move, a new exclusion), why (with the evidence: a case, a
   `file:line`), what it changes for other parts. The part goes on with a
   local stand-in where it can (a constant in its own source, marked) and
   never edits the shared file.
3. **Results.** The checkpoint's numbers (2.5), sizes, timing.
4. **Open points.**

The **integrator** (one builder between waves, about 1 hour [A]): merges
the wave's parts; applies the requests (each accepted or refused with its
reason in the request file); regenerates the includes and the tables
(the wave's dispatch entries filled); runs `gcallgraph.py --check`,
`make -f game.mk wave`, every built part's checkpoint (the newly eligible
cases included), `gplace.py` with the measured sizes and timing; records
in this file's "Wave N as integrated" what moved.

### 3.9 The skeleton's checkpoint S

| # | Check |
| --: | --- |
| S1 | Milestone 9's acceptance 1 on the final layouts: 57 of 57 setups equal `ref816`'s, both fills, 0 stray writes [R `LEVELS.md` "Verification of stage C"]; checkpoint B and the disk check unchanged; the frame checks of milestones 7, 8 and 9 (`frame8.py`, 1,458 runs [M: M9]) pass with `validcount` joined |
| S2 | The routine harness on milestone 9's routines in play: `P_SpawnMobj` (every z mode: puffs, blood, missiles, drops), `P_SetThingPosition` and `P_CreateSecNodeList` from demo3's captures (2,385 calls of the latter [M: CALLS]), both fills, equal; `P_CreateSecNodeList` from `mvNodes` on both branches (`LR_USE` 1: the recorded lines, no stamps; `LR_USE` 0: the walk), with `LR_*` compared (review 5); a mobj with no function spawned and removed (`addIfFunc`, review 9); a grep check that no routine of the game core outside `gobj.s` calls `g_get`/`g_put`/`far_get`/`far_put` on a cached kind (review 2) |
| S3 | The reference side of the tic level: demo3's 2,134 tics decoded with 0 bridge problems, the schedule (4 a frame [M: CALLS]), the newgame and tour streams with their events, one generated stream played on `ref816` to its end; for each fixed run (demo3, DEMO1, DEMO2, newgame, tour) the setups, the re-key records, the T3 windows (zone mobjs as `t1`, zone mobjs in `CS_PREV` removed) and whether a `validcount` wrap falls in one; the same-pair hits per tic; the `I_GetTime` values and the menu's game actions of the streams (review 4, 7, 10) |
| S4 | `LNSECF`, `LNSECB` and `RJROW` equal upstream's `LNSEC` and `SS_ROW` on all 57 setup dumps; the hint re-keying a round trip on them |
| S5 | The runtime on hand-made data: the object API (hits, misses, write-back, the LRU's guarantee), a spawn into a slot whose cached line is dirty from a removal (the spawn's record must survive the later eviction, review 2), `FCALL` across groups and back (a group calling another in its own slot; slot 1 → core → slot 1 with the return into the first group; slot 1 → slot 2 → slot 1, review 1), every dispatch table's unbuilt stop, the planes in and out, the zone's and the specials' free lists, the load protocol with a stub `G_Ticker` and a stub continuation for each of `GA_LOADLEVEL`, `GA_NEWGAME`, `GA_PLAYDEMO`, `GA_WORLDDONE` (each continuation run once and the action loop re-entered, review 3), a re-key record applied after `nl_setup` |
| S6 | `--snapshot-stream` (its tests), the bridge additions (their tests), `glayout.py check`, `gcallgraph.py --check` on the empty part set |
| S7 | Planted: a missed write-back (S2 fails), `FCALL` not reloading the caller's group (S5), `FCALL` restoring only a same-slot caller's group (S5's nested cases, review 1), `gspawn.s` writing a mobj with `g_put` past the cache (S5's dirty-line spawn, review 2), `gp_secnodes` walking and stamping with `LR_USE` set (S2, review 5), the `GA_PLAYDEMO` continuation without `demoplayback = 1` (S5, review 3), `RJROW` of the wrong sector (S4) |

## 4. Code placement, zero page, stack, the IRQ, budgets

### 4.1 Main memory and W in the tic phase, F1.2.1

The tic phase runs first in each frame and then hands W to the render
phases [R `MEMORY_MAP.md` 3.5]. Its fast memory, as the skeleton's
initial allocation [A], checked by `glayout.py`:

| Space | Range | Bytes | Content |
| --- | --- | ---: | --- |
| W | `$6000-$6592` | 1,427 | `MATHW`, `AUXW`, the same bytes as the render images [M: M8] |
| W | `$6600-$99FF` | 13,312 | The core image: the tic loop, the object API, `gcall.s`, milestone 9's game core, the game's math (wave 2 as integrated), and the routines `gplace.py` puts there (4.3). (Wave 2 as integrated: 12,800 before, `$6600-$97FF`) |
| W | `$9A00-$9DFF` | 1,024 | The parts' scratch blocks (4.4), with the core image (never paged, so never lost) |
| W | `$9E00-$A5FF` | 2,048 | Slot 1: one paged group at a time (wave 2 as integrated: 2,560 before; the placement cuts every group at 2,048 B) |
| W | `$A600-$ADFF` | 2,048 | Slot 2: one paged group at a time (a group may keep data in its slot: the sound flood's work stack, 1,536 B [R `LEVELS.md` 5.5], with its 400-500 B of code [A]) |
| W | `$AE00-$B3FF` | 1,536 | The line cache (8 × 34 = 272), the special cache (4 × 32 = 128), the intercepts (64 × 6 and the by-frac chain's 65 links with its head: 449, 1.9), a state and a `mobjinfo` record (176), the fetch buffers of `nd_get` (a node, 28), `sg_get` (a seg, 18) and `ss_get` (a subsector, 8 [A]): 1,079, 457 free. (Review 11: this row had 1,024 B for 1,024 B of caches and the intercepts, with nothing left for the fetch buffers or the chain's head; the core gave 512 B) |
| W | `$B400-$BFFF` | 3,072 | The walk's planes, 768 slots (1.3) |
| main | `$0C00-$0EFF` | 768 | The mobj cache, 8 × 96 (the clip arrays' and the bucket pass's place: dead after the replay [R `MEMORY_MAP.md` 13]) |
| main | `$1680-$17FF` | 384 | The sector cache, 8 × 48 (`COLLO`, `COLHI`, `UPOFS`, `FRORD`: the replay's and the masked phase's, dead after the replay [R `MEMORY_MAP.md` 8, 13]) |
| main | `$0200-$02FF` | 256 | `bl_get`'s block list buffer (256 [R `llayout.py` `LW_BL`]) (the bounce buffer and `BKFAR2`, dead after the replay [R `MEMORY_MAP.md` 3.1, 13]) |
| main | `$1980-$1A7F` | 256 | The runtime's state: the walk's, the object API's tags and LRU, `gcall.s`'s slots (`DSX1`, `DSX2`, `CVDONE`, the batch sizes: dead after the replay [R `MEMORY_MAP.md` 13]) |
| main | `$1C80-$1FFF` | 896 | Persistent: milestone 9's globals block, then 1.5's new globals [R `MEMORY_MAP.md` 16] |

**The language cards** are unchanged: the main card's bank 1 keeps the
math's products, the far layer and the phase loader (35 B free [M: M8]),
`$E000-$FFFF` the sound, the replay's part and the platform [R
`MEMORY_MAP.md` 4.2]; the aux card's tables serve the game's
`R_PointToAngle3` (`pta3`, `tantoangle`) in short `ALTZP` windows as they
serve the renderer [R `MEMORY_MAP.md` 4.3; `src/native/MATH.md`]. The
main card's bank 2 is 4.2's option (a). No tic code goes into the card
otherwise: it has no room.

`glayout.py` asserts that every tic-phase range is dead between the
replay's end and the next frame's front end in `rlayout.py`'s region
list, so a persistent byte of the renderer (`FS_*`, `CV*` between frames,
`WCLIP`, `WPREV`, `WTMP`, `FRVIS` [R `MEMORY_MAP.md` 3.3, 13]) is never
in one. **This amends `MEMORY_MAP.md`'s rule "Tic phases never overlay
`$0C00-$1A7F`"** [R `MEMORY_MAP.md:177`] (review 11): the main ranges
above (`$0C00-$0EFF`, `$1680-$17FF`, `$1980-$1A7F`) are in it, all in
rows whose "persistent across frames" is "no". The skeleton rewrites
the rule as "tic phases overlay only the rows of `$0C00-$1A7F` that are
not persistent across frames, as `glayout.py` checks", in the same
change as section 17.

**What the frame pays** [A]: the core image's pages each frame, 12.5 KB at
0.246 µs a byte [M: `NATIVE.md` 4.3], 3.3 ms; the planes in and out
(`G_MOHWM` + 1 slots, 4 bytes each: 1.4 KB for demo3's 337 slots), 0.7 ms;
the flush before the frame; the paging of 4.3. Milestone 8's
optimisation 1 (reload only the pages another phase overwrote [R
`RENDER-MASKED.md` 6.2]) applies to the core image too, for later.

### 4.2 The fit

| Measure | Bytes | Label |
| --- | ---: | --- |
| Upstream's routines for 90%, 95%, 99%, 99.9% of the game's instructions, demo3 (40 frames) | 11,462; 15,260; 22,092; 29,383 | M: HEAT |
| The same, standing still in E1M1 | 5,485; 5,925; 6,797; 7,023 | M: HEAT |
| Native code of the whole game logic | about 57,000 (2.4's budgets) + 5,860 (milestone 9 with the skeleton's changes) + 2,000 (runtime) | A (4.7) |
| W's code room: the core and the two slots | 17,408 | A (4.1, after review 11) |

Standing still the hot set (about 7 KB upstream) fits the core with room; in a fight the
99% set (22 KB upstream, about 22-29 KB native [A]) does not, so the
cold part of a fight's work pages. Two levers, both measured by the
integrator before the owner's choice: (a) **the card's bank 2** for tic
code: the replay's row blocks and dispatcher (4 KB [R `MEMORY_MAP.md`
4.2]) reloaded each frame before the replay, +1.0 ms a frame for +4 KB of
code room [A]; `glayout.py` has the switch `TIC_LC2`; (b) **the caches'
and the planes' sizes**, traded against code room. On the pair build
(milestone 13) the tics move to the aux card [R `MEMORY_MAP.md` 4.4] and
the placement is redone with the same tool.

### 4.3 The placement

`gplace.py` puts each routine of 2.4 and of milestone 9's game core in
the core or in a group, from three inputs: the heat (instructions a
routine runs in the acceptance demos: from `ref816`'s traces before wave
1, from the `gprof` build's own counts after), the call graph with each
edge's call count (the survey of 3.5), and the native sizes (estimates
before a part is built, `make sizes` after). The rules:

1. The core takes routines by heat until its room is full; the tic loop,
   the object API, `gcall.s` and the dispatchers always.
2. The rest form groups: a group is a set of routines that call each
   other (connected by edges outside the core), at most its slot's size;
   each group has a home slot.
3. A group calling another group of the same slot pays two loads (the
   callee's, and the caller's again on return); the home slots are chosen
   to make the counted cost of these the least, on the calls of the
   demos.
4. The cost model: a load is its bytes at 0.246 µs [M: `NATIVE.md` 4.3]
   and a window's 3-5 µs [M: `NATIVE.md` 1.2].

The output is `gen/gplace.inc` and `game.cfg`; parts only write `FCALL`,
so a placement change rebuilds every image and edits no source. The
initial placement, by part (the tool refines it by routine):

| Image | Parts [A, from fact 7's shares] |
| --- | --- |
| Core | `tic`, `mobjstate`, `sight`, `geom`, `checkpos`, `trymove`, `look` (`A_Look`, `lookForPlayers`, `behindFast`), `secfind` (the thinkers), `spawn` (`P_ZMovement`), `xymove` (`P_XYMovement` without the slide), `pspr` (`P_MovePsprites`, `A_WeaponReady`), `player` (`P_PlayerThink`, `P_CalcHeight`), milestone 9's game core, as far as 12.5 KB goes |
| Slot 1 groups | combat: `chase`'s attacks; `attack` with `damage`; `missile` and `wfire`; `path` with `tracel` and `tracet` (too large for 2.5 KB: split by `gplace.py` into two groups of slot 1 and 2) |
| Slot 2 groups | world: `lines` with `evworld`; `evfloor`; `planes`; `movers` (apart: `movers.md` request 2); `teleport`; `pickup`; `flow`'s cold part; the sound flood with its stack; the slide (`slideMove`); `chasemove` when it does not fit the core |

**`A_Chase` and its callees never share a slot** (review 11): `A_Chase`
runs 6.1 times a tic in demo3 [M: VC] and calls `P_NewChaseDir` and
`pMove` on most calls; with `chase` and `chasemove` both in slot 1 each
call would load 2.5 KB twice (about 1.3 ms [A on M: 0.246 µs a byte]),
about 30 ms a frame of 4 tics. `A_Chase`, `P_NewChaseDir`, `pMove` and
`P_TryWalk` go to the core first (they are in the 99% hot set [M:
HEAT]); what does not fit goes to a slot other than `A_Chase`'s.
`gplace.py`'s rule 3 counts the calls, and its report lists every pair of
groups of one slot with more than one call between them a tic at the
median.

### 4.4 Zero page and scratch

Main zero page in the tic phase [R `MEMORY_MAP.md` 2; `LEVELS.md` 4.3]:

| Range | Owner | Content |
| --- | --- | --- |
| `$00-$17` | platform, far layer | as today |
| `$18-$37` | milestone 9's game core (`GC_*`) | as built [R `llayout.py` `LZPG`] |
| `$38-$3F` | object API | `GC_MP`, `GC_SP`, `GC_LP`, `GC_XP` |
| `$40-$41` | `gcall.s` | the caller's group |
| `$42-$47` | reserved | [R `MEMORY_MAP.md` 2] |
| `$48-$5B` | `GA_*` (20 B) | a call's arguments: the caller writes them, the callee reads them at its start; dead after that (upstream's `_Dp[0-15]` and stack arguments [R `NATIVE.md` 6]) |
| `$5C-$74` | `GT_*` (25 B) | temporaries: any call may change them |
| `$75-$AE` | milestone 9's spawn (`GS_*`) | as built; `P_SpawnMobj` in play uses them, so they are temporaries of every caller of the spawn |
| `$B0-$D7` | math | [R `src/native/MATH.md`] |
| `$D8-$FF` | IRQ | |

A part has no zero page of its own. What it keeps across a call goes
into its **scratch block**: a few absolute bytes (32 B by default [A];
more on request) in W `$9A00-$9DFF`, which `glayout.py` allocates with
overlays: two parts' blocks share bytes only if no routine
of one can be active while a routine of the other is, by
`gcallgraph.py`'s reachability with the dispatch tables. The walk's
state (the thinker, its next) is the runtime's (main `$1980`).

### 4.5 The stack

The tic phase's budget is 160 B, plus 24 B for the IRQ [R
`MEMORY_MAP.md` 2]. Upstream's tic stack reached 228 B with 3-byte
returns and stack arguments [M: `PROFILE.md:680`]; natively the returns
are 2 bytes, the arguments are in `GA_*`, and an `FCALL` across images
adds 5 B (its return, its own return into the target, and the saved
group of the target's slot: review 1); `gcallgraph.py --stack` counts
the 5 B on every cross-image edge. The deepest chain the graph shows [M: CG]: `G_Ticker` →
`P_Ticker` → `P_RunThinkers` → `P_MobjThinker` → `P_XYMovement` →
`P_TryMove` → `spec` → `P_CrossSpecialLine` → (`LSTAB`) `EV_Teleport` →
`P_TeleportMove` → `P_BlockThingsIterator` → (`ITTAB`) `stompThing` →
`P_DamageMobj` → `killMobj` → `P_SpawnMobj` → `gp_setpos` → `gp_secnodes`
→ the block walk → `P_BoxOnLineSide` → a product: 20 levels, about 95-125
B with the pushes and four cross-image calls [A]. `gcallgraph.py --stack`
checks the static bound at every build, and every run measures the lowest
S (`--lowest-s-in`, as milestones 7-9 [R `LEVELS.md` 4.3]); the report
gives both. The sound flood is iterative (its stack in its slot, 4.1).

### 4.6 The IRQ

Unchanged: the handler touches only zero page `$D8-$FF`, the stack, the
card's `$E000-$FFFF` and I/O, so it needs no switch whatever RAMRD,
RAMWRT and `$C073` say [R `MEMORY_MAP.md` 1, rule 2]. The object API's
windows and the paging's copies (in the card, `far_pload`) run with
interrupts on; every routine-mode and tic-level run sets `--irq-bounds`
as milestones 7-9 did. No tic code reads `$Cxxx` but the far layer's soft
switches: the clock's and the input's reads are the platform's
(milestone 11).

### 4.7 Size budgets

| What | Budget, bytes | Label |
| --- | ---: | --- |
| The 29 parts | 57,000 (2.4, each part's) | A: upstream × 1.3 |
| Milestone 9's game core in the tic images | 5,260, plus the skeleton's changes (about 600) | M: M9; A |
| The runtime (`gobj.s` 1,200, `gcall.s` 300, `ghook.s` 200, the dispatch tables 300) | 2,000 | A |
| `GCODE0-1` (all images at their W addresses) | 97,280 of room | A: two banks of 48,640 |
| The test driver (card `$E000-$EDFF`, test builds) | 3,584 | A, as `lboot.s` [R `MEMORY_MAP.md` 16] |

`make -f game.mk sizes` prints every part against its budget from its
first build; a part 10% over reports it in its request file with the
reason, as milestone 9's `lgeom.s` did [R `LEVELS.md` "Stage B as
built"]; the sum is what must fit.

## 5. The integration

### 5.1 The tic loop over the parts

| Upstream | Part | Calls, in order |
| --- | --- | --- |
| `G_Ticker` [R `g_game65.s:563-623`] | `tic` | reborn check; `P_MapEnd`; the actions (`flow`: exit, completed, world done, new game, play demo; a load through the driver, 3.4); the command (or `readDemoTiccmd`, `flow`); `WI_End` on leaving the intermission (`flow`); by game state: `P_Ticker` and the hooks of `ST_Ticker` (`M_Random`), `AM_Ticker`, `HU_Ticker` (the message), or `WI_Ticker` (`flow`) |
| `P_Ticker` [R `p_think65.s:185-213`] | `tic` | paused by the menu; `P_PlayerThink` (`player`); `P_RunThinkers` (`tic`); `P_UpdateSpecials` (`secfind`); `P_MapEnd`; `leveltime + 1` |
| `P_PlayerThink` | `player` | `movePlayer` (`P_SetMobjState`: `mobjstate`), `P_CalcHeight`, the death think, `specialSector` (`P_DamageMobj`: `damage`; `G_ExitLevel`: `flow`), `P_UseLines` (`path` → `PTR_UseTraverse` → `P_UseSpecialLine`: `lines` → `LSTAB`), `P_MovePsprites` (`pspr` → `ACTTAB`: `pspr`, `wfire`) |
| `P_RunThinkers` | `tic` | each thinker by `THTAB`: `P_MobjThinker` (`tic`: `P_XYMovement` (`xymove` → `P_TryMove`: `trymove` → `checkpos`, `lines`), `P_ZMovement` (`spawn`), the state's end (`P_SetMobjState`: `mobjstate` → `ACTTAB`: `look`, `chase` → `chasemove`, `attack`, `missile`), `P_NightmareRespawn` (`trymove`)); `P_MobjBrainlessThinker` (`mobjstate`); the lights and scrollers (`secfind`); `T_MoveFloor` (`planes`); `T_VerticalDoor`, `T_PlatRaise` (`movers`); the two removals (`mobjstate`) |

The tic phase as the driver runs it: core image and planes in; the tics
of the frame; `go_flush`; planes out; the render inputs; the frame.

### 5.2 The acceptance runs

| # | Run | Tics | Checks | Estimated wall time at 9 jobs |
| --: | --- | ---: | --- | --- |
| 1 | demo3, lockstep, `FRONT` | 2,134 [M: VC] | Every tic (3.6) | 6 min a fill [A]: the reference under 2 min [M: CALLS], the native about 1 min [A on M: a2vm at 215 M instructions a second, `MILESTONES.md` 3], the two decodes about 35 ms a tic each [M: `research/native-verification.md` 6.4] |
| 2 | newgame; tour; the tour by map | about 1,000; about 2,000 with 8 intermissions [A]; the same tics in 9 runs, each from its map's E point | Every tic, the events applied. The whole tour crosses setups that move upstream's pool base (`$06:2590` for E1M1 and E1M2, `$08:0010` for E1M3 [M: POOL]); each setup's re-key record (3.6) keeps the hint and `CS_PREV` exact across them (review 4). The nine runs by map, each started at its own `P_SetupLevel` entry, run in parallel and check the same tics from the reference's state at each map's start | 3, 6 and 6 min a fill [A] |
| 3 | DEMO1, DEMO2 | 5,026; 3,836 [M: VC] | Every tic | 12 and 9 min a fill [A] |
| 4 | G1-G10 | 10 × 2,000 | Every tic; the streams' coverage (3.7) | 5 min a stream and fill [A] |
| 5 | demo3, lockstep, `FULL` | 2,134 and 533 frames | Every tic, and at every frame the record stream exactly and aux 0 `$2000-$88FF` (the view) after the replay: equal to `ref816`'s frames of milestone 8 (`demo3-001` .. `-533` [M: M8]) but the bytes `ref816`'s 2D code wrote into the view since the last replay (the message line, `stripEarly` [R `RENDER-MASKED.md` 2.3 item 4]), named per frame; a frame that differs only through those bytes is replayed from `ref816`'s composed screen (milestone 8's method) and must then be equal. `SPRBOUND`, `FZPOS` and the renderer's persistent state come from `ref816` at the run's start only, as injected state [R `RENDER-MASKED.md` 0.3 row 3] | 10 min a fill [A] |
| 6 | `P_PathTraverse`, long dense traces | about 500 traces of more than 64 intercepts over the nine maps (a host model counts each trace's intercepts on the captured states), each with the recording traverser and with stops at k = 1, 8, 32, 64, 65 | `ref816 --call` of upstream's routine on the captured state against the native's: the intercepts delivered (frac, line or thing), the return value, `validcount` and every line stamp (wave 4, `path.md` R6: E1's traces of more than 64 intercepts are rare: lines along a whole map give at most about 50, and a long diagonal walk gets stuck, its walk's steps being approximate [R `p_path65.s:516-534`], before it collects more; so the traces are chosen by the reference's own count, the host model only filtering the candidates: 2,692 candidates on the nine maps' states, 17 of more than 64 intercepts on seven maps (none found on E1M1, E1M4), most through `ptStuck`'s copies [R `p_path65.s:832-883`]; the about 500 of this row stay a full run's target) | 5 min [A] |
| | **All** | | | About 200 min of CPU, **25-35 min** at 9 jobs (DEMO1's 12 min the longest job) [A] |

The stream search of 3.7 is extra: at most 200 candidate streams on
`ref816`, about 1 minute each, 25 min at 9 jobs [A]. Disk: the reference
and native per-tic states are digested as they stream; only failing tics
are kept; the run's directory is deleted after its report [A: under 200
MB at a time]. `df -h` first, as the ground rules ask.

### 5.3 The report

`build/native/game/report.md`, from `ticrun.py --report-md`:

1. Acceptance 1-6: each run, fill, tics compared, failures 0, the T3
   windows and T8 tics by name, the frames of T7 by name.
2. The gates: `validcount` joined; zone mobjs created (count, highest slot,
   G1 and G2), no slot twice, the planes' highest slot; the block walk's
   order (the tics with sector nodes changed); the `LVS` tables (S4).
3. The sound events per tic against `ref816`'s call log (a report for S4,
   not a gate).
4. The timing (5.4) and the sizes (5.5).

### 5.4 The timing report

The `gprof` build marks cost phases (a2vm's 32 [R `MEMORY_MAP.md` 13]:
the render uses 0-17) by subsystem, each phase a stack so a nested call
counts to the innermost:

| Phase | Subsystem |
| ---: | --- |
| 18 | The tic phase's entry and exit: the core image, the planes, the flush |
| 19 | The walk (`P_RunThinkers`, `P_MobjThinker` but its calls) |
| 20 | Moves: `P_XYMovement`, `P_ZMovement`, `P_TryMove`, `P_CheckPosition`, the slide, positions |
| 21 | Sight |
| 22 | Traces: `P_PathTraverse`, the intercepts |
| 23 | Monsters: `look`, `chasemove`, `chase` |
| 24 | Combat: `attack`, `damage`, `missile`, `wfire`, `P_RadiusAttack`, `spawn`'s puffs and blood |
| 25 | The player: `player`, `pspr`, the use |
| 26 | The world: `secfind`'s thinkers, `planes`, `movers`, `EV_*`, `lines`, `teleport` |
| 27 | Flow: `G_Ticker`'s own, demo, `wi`, hooks |
| 28 | Paging (`fc_call`'s loads) |
| 29 | The object API's misses (far windows) |

Reported, on `f121` and `fastpath`, over demo3, DEMO1, DEMO2 and G1-G10:
each tic's time by phase (median, p99, worst), each frame's tic phase
(the scheduled 4 tics and the phase-18 costs), and then **the FPS figures
that replace `NATIVE.md` 6's estimate** ("Tics at 4 a frame: 3.0-6.7 ms
still, 18.4-41.3 ms demo" [R `NATIVE.md` 6]) in `RENDER-MASKED.md` 6.2's
table: for each of demo3's 533 frames, its measured tic phase plus its
measured render time from milestone 8's `report8.md` [M: M8], so the
frame time and FPS of every frame, the median and the worst, the frames
under 6 FPS by name; and the same with the tics a frame a faster native
frame would run (35 × the frame time, rounded up, 1 to 4 [R `NATIVE.md`
1.1]), solved per frame. The table goes into `RENDER-MASKED.md` 6.2 as a
new row set, marked [M].

### 5.5 Sizes and banks

`make -f game.mk sizes` and `glayout.py --report`: each part's bytes and
budget; the core's and each slot's fill; each group's size; `GCODE0-1`'s
fill; the banks against `MEMORY_MAP.md` and `LEVELS.md` 1.6 (116 of 126
in test builds, 113 in the release [A], 1.10); `MEMORY_MAP.md` section 17 with every region of 1.10 and 4.1.

### 5.7 The documents this milestone updates

| Document | Change | By |
| --- | --- | --- |
| `MEMORY_MAP.md` | Section 17: the regions of 1.10 and 4.1; section 3.5's tic row with the measured core and slots | Skeleton, then the integration |
| `LEVELS.md` | 3.2's provisional layouts replaced by a pointer to this file's section 1; the gates of "Verification of stage C" closed with their evidence | Integration |
| `NATIVE.md` | Section 6's cost estimate and 15.1 row 4's open point (the joined count) answered with the report | Integration |
| `RENDER-MASKED.md` | 6.2's table: the measured tics and the new FPS figures (5.4) | Integration |
| `src/native/README.md` | A section "The game logic (milestone 10)": commands, files, results | Integration |
| `MILESTONES.md` | Row 10 of the status table | Integration |
| This file | "Skeleton as built", "Wave N as integrated", "Acceptance" sections, each correction marked in the text, as `LEVELS.md` does | Each stage |

### 5.6 Schedule and resources

| Stage | Builders | Wall time [A] | `build/` growth [A] |
| --- | ---: | --- | --- |
| Skeleton | 1-2 | about 5 units of 1.5 h | 0.3 GB (S2's captures, the reference's streams) |
| Waves 1-6 | 5, 5, 5, 5, 5, 4 | 1.5 h each, plus the integrator's hour between waves | 2 GB of cases (3.5), 0.25 GB at most a part |
| Integration and acceptance | 1 | 3-4 h (the runs of 5.2 take 25-35 min; the failures' bisection the rest) | 0.5 GB (kept failing tics, reports) |
| **All** | | about 2.5 days of wall time | **under 3 GB** of the 8 GB allowed |

## 6. Risks

| # | Risk | Effect | What the builders do |
| --: | --- | --- | --- |
| 1 | **Far access in the moves.** `P_TryMove` runs 11 times a tic at the median of demo3 and 51 at most [M: CALLS]; each reads lines, sectors, block lists and things of RamWorks. Milestone 9 measured 0.6-0.8 ms a spawned thing on `f121`, far-fetch bound [M: M9]; a move does similar work [A] | Tics of 5-20 ms in fights, 20-80 ms a frame of 4 tics [A], against `NATIVE.md` 6's 18.4-41.3 ms | The object API's caches (1.1); the timing report names the misses (phase 29); the cache sizes, a BSP top-level cache for `R_PointInSubsector` and a block-list cache are the integrator's levers, all inside the runtime, none in a part |
| 2 | **W fit** (4.2): the 99% hot set of a fight is 22 KB of upstream code [M: HEAT], the core 12.5 KB | Paging in fights (0.6 ms a 2.5 KB group [A]) | Measured placement (4.3); the card's bank 2 option; the paging counted in phase 28 |
| 3 | **`P_Random` order and every call order.** One extra or missing call desynchronizes everything after it | A late, far-reaching difference | `prndindex` compared every tic and in every routine case; the bisection of 3.6 finds the first routine; each part's planted bugs include a `P_Random` order |
| 4 | **Upstream's state-changing shortcuts** (fact 4: `CS_PREV`, `mvNodes`, the line record, the early traversal) and its quirks (`P_UpdateAnimatedFlat`'s unsigned shift [R `r_data65.s:682-686`], the sight test's 16-bit wrap, `ptStuck`'s copies [R `p_path65.s:832-880`], the `FixedMul3216` truncation [R `NATIVE.md` 3.2]) | Stamps or answers that differ from Doom's C but must equal upstream's | Every one is listed in its part (2.4) with a case that takes it; the C is never the reference [R `NATIVE.md` 3.2 "Departures"] |
| 5 | **The order of lists**: thinkers (appended; removal deferred), sector thing lists (head insert), block lists (head insert), sector nodes and their free list, `spechit`, the line record `LR_LINES`, the button list | A different first thing found, a different node | All compared as sequences every tic [R `tools/bridge/README.md` "Lists are sequences"]; planted order bugs in `mobjstate`, `checkpos`, `trymove`, `planes` |
| 6 | **Fixed-point rounding**: divides (C semantics, our own), `FixedDiv`'s guards, arithmetic shifts of negative values, the 32-bit products' low words | One unit off, a desync many tics later | Milestone 6's products and divides for every one upstream makes through its runtime or `m_fixed65.s` (no part writes its own of those); upstream's own arithmetic helpers mirrored exactly, each with 100,000 random inputs by `--call` against upstream's (the list of 2.4 "Arithmetic", review 13); `tracel`'s `FixedDiv` [R `p_trace65.s:237`, `:398-404`] is upstream's own long division, mirrored step by step (wave 2 as integrated: `tracel.md` R5; its inputs that upstream never returns from count in `GT_DIV0`, R4); the pure routines of `tracel`, `geom` and `sight` also run on 1,000,000 random inputs by `--call` |
| 7 | **The address-keyed sight hint and `CS_PREV`** (fact 3, 1.8) | In the release, stamps, `sightline` and a same-pair hit can differ after a pool-moving setup; in every run, after a zone mobj is `t1` or a zone mobj in `CS_PREV` is removed | Test builds re-key at every setup (3.6); T3 only for the zone window, closed at the next setup, with seeds rejected when a wrap falls in one; the same-pair hit log compared every tic; the hint-free answer check in `sight` |
| 8 | **`validcount` wraps** in long play (about 80 s [R `NATIVE.md` 14 risk 10]), none in the acceptance demos [M: VC] | The lockstep build reproduces upstream's wrap; the release clears (1.7) | The release clear is milestone 9's `gvalid.s` (checked by its `wrap` capture [R `LEVELS.md` "Stage C as built"]); milestone 11's frame test |
| 9 | **The volume**: 43 KB of upstream code, 29 parts in parallel | Late integration failures | The routine checkpoints rerun after every wave; tic-level runs from wave 6 on, bisection by routine |
| 10 | **Coverage of rare paths**: no demo calls `P_RadiusAttack` [M: CALLS]; teleports, crushers, lifts, the boss death, nightmare respawn are rare | A path never compared | The generated streams' coverage targets (3.7) and each part's synthetic cases; the coverage report lists every untaken path by name |
| 11 | **Zone mobjs past the planes' 768 slots** (1.3) | A native stop (`GS_PLANES`) where upstream runs | The highest slot of every run reported; the cap is a layout constant |
| 12 | **The load protocol inside a tic** (fact 12) | A tic that loads must resume exactly | The protocol is the skeleton's (3.4) with its own test (S5); every acceptance run loads at least once |
| 13 | **Run time** of the per-tic decode (35 ms a state and side [M: `research/native-verification.md` 6.4]) | 25-35 min for the acceptance at 9 jobs [A] | Digests per kind, failing tics only kept whole; the tour by map in parallel |
| 14 | **Changes to built milestones**: the mobj group A, the planes, the specials' free lists, `validcount`'s place, `lgeom.s`'s new step, `rframe.s`'s `gv_inc`, `MEMORY_MAP.md` | Milestones 7-9's checks could break | The skeleton reruns them (S1) before wave 1 |

**Open points for the owner.** (1) Whether the card's bank 2 may hold tic
code at 1 ms a frame (4.2), decided on the integrator's measurements.
(2) The sight hint and `CS_PREV` cannot be keyed as upstream's after a
setup that moves upstream's pool base, nor for zone mobjs: test builds
re-key them from the reference at every setup and name the zone window
(T3); the release keeps its own (1.8). A same-pair hit that differs (a
zone address reused) would fail a run and come to the owner. (3) The planes'
768-slot cap below upstream's zone bound (risk 11).

## Skeleton as built (2026-10-01)

The skeleton stage of section 3, with every review change, built and
checked on a2vm and ref816. Nothing is committed (the owner's rule for
this stage); `build/` grew by 97 MB (`du -sk build`: 3,683,828 KB
before, 3,782,604 KB after, every scratch directory deleted;
`build/native/game` 56 MB of it: the captures 43 MB, the shared outputs
(the survey, the tic references, the streams, the manifests) 4 MB, the
test images 9 MB).

### What was built

| File | What |
| --- | --- |
| `tools/native/glayout.py` | The tic phase's layouts: W's map (4.1), the main ranges and the check that each is in a non-persistent row of `MEMORY_MAP.md` 3.3, the zero page of 4.4, the runtime's state, the scratch blocks, GTEST, the part table of 2.4 keyed `file:label` (29 parts, their helpers, the core, the hooks, the math, the routines named out), the dispatch tables, `check()`, the game manifest `native-game-1` (milestone 9's level manifest plus the tic's globals and the derived kind `sighthint`), and the generated `ggame.inc`, `gplace.inc` (the `ROUTINE`, `FCALL`, `DCALL` macros), `gdisp.inc`, `game.cfg`; `--out DIR`, `--built`, `--part`, `--test-place`, `--check`, `--report` |
| `tools/native/gcallgraph.py` | The call graph read by our front end (never `cal_integer.s`), followed into `r_list65.s`, `w_level65.s`, `hu_stuff65.s`, `st_stuff65.s`, `wi_stuff65.s`; `--check` (935 heads, 589 reachable from the tic, 0 failures), `--reach`, `--stack` (56 B + 24 IRQ = 80 of 160) |
| `tools/native/gplace.py` | The placement of 4.3 from the trace's heat, the survey's calls and the sizes; `--write` (the integrator's: `make -f game.mk place`) |
| `src/native/game.mk`, `src/native/game/README.md` | The targets `part P=`, `wave W=`, `game`, `gprof`, `release`, `skel`, `place`, `shared`, `sizes`; the fragments; the conventions (`FCALL`, `DCALL`, the object API, `GA_*`/`GT_*`, the scratch blocks, the load protocol, the stops), `args.json`'s schema, the stream's format |
| `src/native/gobj.s` | The object API: the mobj, sector, line and special caches with write-back and LRU, the fetches, the planes, the flush |
| `src/native/gcall.s` | `fc_call` (5 B of stack, the target slot's group saved and restored whoever the caller is), `fc_unbuilt`, `dc_call`, `act_num`, the group loads, the stops |
| `src/native/ghook.s` | The hooks: the sound events and the same-pair hits logged in test builds, `I_GetTime` from the stream, the screens' stubs, the stops |
| `src/native/gdriver.s` | The test driver in the card's `$E000` part: routine, routine-with-load, lockstep and load-test modes, the load protocol, the schedule's frames, the re-key records |
| milestone 9's core | `gthink.s`, `gpos.s`, `gspawn.s`, `gspec.s`, `gvalid.s`, `gweap.s` on the object API; the planes, the zone's and the specials' free lists, `G_MOHWM`; `P_SpawnMobj`'s three z modes; `addIfFunc`; `gp_secnodes` with the `LR_USE` path and `MP_MODE`; `setPsprite` through `ACTTAB`; `gvalid.s` linked into the render images (`rframe.s`: `jsr gv_inc`); the setup's clear of `LR_OK`; the load's `GTABS` step (`lgeom.s`, `lstore.py`); the load image links `gobj.s` and ends with `go_flush`; the play entries `P_SpawnMobj`, `P_SetThingPosition`, `P_CreateSecNodeList` (new: `gp_secnodesmo`) |
| `tools/native/gamecap.py`, `gameroutine.py`, `grun.py`, `gselftest.py` | The survey, the captures distilled into cases, the routine harness, the images and runs, S5 |
| `tools/native/ticcap.py`, `ticgen.py`, `ticrun.py`, `gcanon.py` | The tic references, the generated streams, the native lockstep runner, the comparison modes |
| `tools/bridge/layout.py`, `port.py`, `schema.py`, `upstream.py` | `select`, `removed`, `stale`, `mask`; the `routine` and `tic` modes; the reader's tic decoding (`tests/test_bridge_game.py`) |
| `tools/a2vm/main.c`, `README.md` | `--snapshot-stream FILE`, `--snapshot-limit BYTES` (`tests/test_a2vm_harness.py`'s `SnapshotStream`) |
| `docs/game-parts/*.md` (29), `docs/MEMORY_MAP.md` 17 | The parts' records (3.8 headings, each entry's calls in the survey's runs); the tic phase's map and the rewritten rule of 3.3 |
| `tests/test_native_game_skeleton.py`, `tools/testpar.py`, `tests/README.md` | Checkpoint S; the prebuild step `game.mk` (`make -s -C src/native -f game.mk shared skel ROOT=$PWD`) and the race table |

### Sizes

| What | Bytes | Budget (4.7) |
| --- | ---: | ---: |
| `gobj.s` | 1,913 (tic image), 1,961 (load image) | 1,200 |
| `gcall.s` with the dispatch tables and `ACT_ADDR` | 860 | 300 + 300 |
| `ghook.s` (with the test logs) | 322 | 200 |
| milestone 9's core in the tic image: `gthink` 1,351, `gpos` 1,895, `gspawn` 948, `gweap` 395, `gspec` 618, `gvalid` 9 | 5,216 | 5,260 + 600 |
| the skeleton's core image (no part; `gtest.s` and `grec.s` left out) | 8,311 of 12,800 | |
| the test driver | 1,183 of 3,584 | 3,584 |
| the load image's `LOADW` | `$6600-$8FCB` (`lgeom` 2,170, `gobj` 1,961) | |
| W's `GW` | 1,222 of 1,536 | |
| the runtime's state (main `$1980`) | 128 of 256 | |
| the globals block | `$1C80-$1EF8`, 633 B | |
| RamWorks | 114 of 126 banks (test builds) | |

The initial placement (`gplace.py --write`, from upstream × 1.3 and the
demo trace's heat): the core's room after the skeleton (4,489 B) takes
30 routines (`A_Chase`, `P_NewChaseDir`, `pMove`, `P_TryWalk` first),
the rest form 27 groups cut at slot 2's size; same-slot calls cost
1.05 ms a tic at the mean; no pair of one slot has more than one call a
tic at the median; `A_Chase`'s rule kept. The parts' measured sizes
replace the estimates from wave 1 on.

### Deviations from this design (each with its reason)

1. **The special cache has 5 lines, not 4**: with 4 the LRU guarantee
   ("the most recently got lines are never evicted") left a caller
   holding four specials without room for a fifth get; 5 x 32 fits `GW`.
2. **`gobj.s` is 1,913 B against 1,200**, `gcall.s` 860 against 600
   (the tables included), `ghook.s` 322 against 200 (the test logs):
   the fetches, the planes' far path for the load image and the stops;
   the parts' budgets are unchanged, the core's room is measured
   (8,311 B used).
3. **Core data is reloaded at each load**: the driver loads the core
   image from `GCODE0` again after `nl_setup`, so a variable in a core
   segment returns to its image value. State that must survive a load
   lives in the globals block (README.md); `I_GetTime`'s count is the
   driver's (`dg_tcount`, card).
4. **The load program's zero page `LZP1` overlaps the API's
   `$38-$3F`**: the load saves it on the stack around each game step
   (`lload.s` `game_step`), and `GTABS` is a game step of the load
   (step 10, before the spawn), not a separate pass.
5. **The manifest's additions are opt-in** (`select`, `removed`,
   `stale`, `mask`; the reader's tic decoding with `tic=True`, its
   `TIC_GLOBALS` and `texturetranslation` instead of new
   `EXTERNAL_GLOBALS`), so every existing manifest and the `lockstep`
   comparison mode are unchanged; `routine` and `tic` are new modes.
6. **Two milestone 9 test anchors moved with the code**:
   `tests/test_native_level_setup.py`'s planted-bug anchor (`MA_TICS`
   left group A: `LW_MOB + MO_XTICS`) and
   `tests/test_native_level_conv.py`'s bank count (109 to 114, banks
   72-74 no longer spare); the tests check the same things.
7. **Banks: 114 used**, as `llayout.bank_map` counts (banks 4 and 5,
   milestone 9's test data, stay counted spare as before); 1.10 counted
   them used (116).
8. **The routine harness's level base** is the native setup's machine of
   the map that milestone 9's acceptance keeps
   (`build/native/levels/setup/tour-sk2-NN.img`), zero page included
   (the math's state), with the case's state written over it through the
   manifest and the native-only state derived (`gameroutine.derived`).
9. **The cases**: a run's whole RAM is its base (`cases/RUN/base.ram.z`,
   3.9 MB) and each case keeps, xor'ed against it, the pages the bridge's
   reader reads at the entry and the return and the pages the call reads
   or writes (1-12 KB a case), instead of a base a tic: smaller, and
   exact for what the reader and the call touch.
10. **The survey runs in passes** (ref816 logs at most 64 routines): the
    entries packed with the dispatch targets they can reach; the caller
    of a call is the routine that holds its JSL (not the innermost
    logged call); a call's tic is the gametic of the last `G_Ticker`
    entry (the title loop's tics included: demo3's run counts 3,188).
11. **`ticcap.py` decodes the tics of a level** (`_g_gamestate` 0) from
    dumps of the banks the reader reads (`$00-$10`, `$22`, `$24`,
    `$32-$3A`, measured on the setup dumps; a read outside them is a
    problem); `P_SetupLevel` is logged with `jumps=1` (a new life enters
    it by `bmLoad`'s JML), and a zone pointer is one outside the pool at
    both ends of its tic (a load moves the pool).
12. **The stream**: a demo reads its own lump (`DEMOB`); `GT_STREAMB`
    (22 KB) holds the commands of 2,000 tics (newgame, tour, generated
    streams replayed as lumps).
13. **`ticrun.py` cannot run a tic before part `tic` builds `G_Ticker`**
    (and `flow` `g_resume`); its machinery (the snapshot stream read
    through a pipe, each tic's state through the manifest, the digests)
    is checked with the skeleton's stub ticker. The bisection is
    described, not built (it needs a native tic).
14. **S2's classes**: the reference's entry state is not a canonical
    state when the mobj is in the middle of its spawn (every
    `P_SetThingPosition` and `P_CreateSecNodeList` call at the setup, and
    the in-play `P_SetThingPosition` calls that reuse a slot with stale
    links): such a case is "undecodable" and counted apart; a
    `P_CreateSecNodeList` call whose reference frees a node needs part
    `mobjstate`'s `P_DelSecnode` and is "waiting" (the native stops at
    the unbuilt `FCALL`). Neither is counted equal.
15. **No ceiling spawn in play in the survey's runs**: S2's `ONCEILINGZ`
    cases are synthetic (in-play cases with z poked, run on ref816 by
    `--call`: `gamecap.call_case`).
16. **The removal of a mobj with no function** is part `mobjstate`'s
    (`P_RemoveMobj`, `linkRemove`, not built): S2 checks the spawn half
    (demo3's in-play drops, whose spawn state never ends).
17. **The placement is written** (`shared/placement.json`) from
    upstream × 1.3 and the heat of `demo.trace`; the groups are cut at
    slot 2's size so that either slot holds each.
18. **The core's play entries** got their parts' names (`P_SpawnMobj`,
    `P_SetThingPosition`, `P_CreateSecNodeList` as aliases) and
    `gp_secnodesmo` (`P_CreateSecNodeList` of a slot), which the design
    left unnamed.
19. **The checkpoint's module has its own time limit**: it reruns
    milestone 9's whole acceptance (1,301 s alone, 1,085 of them
    `frame8.py` on the loaded levels), past the runner's 1,200 s, so
    `tools/testpar.py`'s `MODULE_TIMEOUTS` gives it 3,600 s; S2 in the test
    takes every 10th case (`gameroutine.py --s2` runs them all: the
    numbers below).

### Checkpoint S

All of it is `tests/test_native_game_skeleton.py`; the numbers here are
the full runs.

| # | Result |
| --: | --- |
| S1 | 57 of 57 setups equal `ref816`'s from both fills, 28 runs, 0 failures (no stray write), stack 41 B, the wrap fix equal; checkpoint B: 20 loads from each fill, 0 problems; the disk (`ldisk.py --check`): 20 setups, every CRC as expected, `f121` and `fastpath`; `frame8.py --levels loaded --sets m7,demo3`: 729 frames, 1,458 runs, all equal (validcount joined: `rframe.s` raises the game's `G_VALID`) |
| S2 | demo3's captures, both fills: `P_SpawnMobj` 508 cases, 1,016 runs equal (z on the floor 277, given 231: puffs, blood, missiles, the setup's things, the drops of `playerDamage`, whose spawn state never ends: no thinker; under the ceiling 4 synthetic cases, 8 runs equal); `P_SetThingPosition` 235 cases equal (470 runs), 273 undecodable (the mobj in the middle of its spawn: 266 at the setup, 7 in play); `P_CreateSecNodeList` 1,859 cases equal (3,718 runs: from `mvNodes` 1,618, `LR_USE` 1 1,533 and 0 326; from `P_SetThingPosition` 241), 259 waiting for `mobjstate`'s `P_DelSecnode` (the reference deletes a node), 267 undecodable (the setup's); 0 failed; the grep check clean |
| S3 | demo3: 2,134 tics decoded, 0 bridge problems, 534 frames at 4 tics each (533 gaps), 1 setup (E1M7, skill 2, its re-key record), no T3 window, no wrap, 1,009 same-pair hits in 820 tics, `I_GetTime` read once by the game (`doPlayDemo`, 1,371); DEMO1: 5,026 tics, 0 problems, 8 setups (a new life each), no window, no wrap, 3,956 hits; DEMO2: 3,836 tics, 0 problems, 3 setups, no window, no wrap, 80 hits; newgame: 512 level tics, 0 problems, 1 setup, the menu's `G_DeferedInitNew` (skill 2, `chooseSkill`), 53 hits; tour: 427 level tics, 0 problems, 9 setups, the cheats (`iddqd`, `idclev` x 8), the poke of `_g_wminfo.next` (native `$1DDC`) at its tic; no fixed run has a wrap in a window. G1 (E1M1, UV, seed 1): played to its end on `ref816`, 2,000 tics, 18 zone mobjs, no window, no wrap, no division by zero: accepted. `ticrun.py --selftest`: the lockstep stream read and digested a tic at a time |
| S4 | 57 setup dumps: `LNSECF`, `LNSECB`, `RJROW` equal `LNSEC` and `SS_ROW`, the re-key record a round trip through the manifest (hints and `CS_PREV`): 0 failures |
| S5 | `gselftest.py`, both fills: the API, the dirty-line spawn, `FCALL` (own slot, slot 1 -> core -> slot 1, slot 1 -> slot 2 -> slot 1), the planes, the free lists, every table's unbuilt stop, the load protocol for the four actions with the re-key record: all ok |
| S6 | `glayout.py --check` ok; `gcallgraph.py --check` 0 failures, `--stack` 80 of 160; `tests/test_bridge_game.py` 11 tests; the snapshot stream's 3 tests |
| S7 | Caught, each: the missed write-back (8 of 12 S2 cases fail), `gp_secnodes` walking with `LR_USE` set (12 of 12), `FCALL` not reloading (a crash), `FCALL` restoring only a same-slot caller (the markers), `g_put` past the cache (the spawned type lost; the grep check also flags it), `GA_PLAYDEMO` without `demoplayback` (the check), `RJROW` of the wrong sector (S4 fails on every dump) |

### Commands

    make -s -C src/native -f game.mk shared skel ROOT=$PWD   # the prebuild
    python3 tools/native/glayout.py --check
    python3 tools/native/gcallgraph.py --check; ... --stack
    python3 tools/native/level_check.py --setup; ... --load
    python3 tools/native/ldisk.py --check
    python3 tools/native/frame8.py --levels loaded --sets m7,demo3 --jobs 4
    python3 tools/native/gamecap.py --survey
    python3 tools/native/gamecap.py --capture p_map65.s:P_CreateSecNodeList --run demo3 --all   # and the two others
    python3 tools/native/gameroutine.py --s2; ... --plants
    python3 tools/native/ticcap.py --runs demo3,demo1,demo2,newgame,tour; ... --tables; ... --tables --planted
    python3 tools/native/ticgen.py --stream G1 --seed 1
    python3 tools/native/ticrun.py --selftest; ... --run demo3
    python3 tools/native/gselftest.py; ... --plants
    python3 tools/native/gplace.py --write
    python3 tools/testpar.py

### Open points

- The tic level cannot be compared before wave 1 gives `G_Ticker`
  (`tic`) and `g_resume` (`flow`); the bisection is to be built then.
- 259 of demo3's `P_CreateSecNodeList` cases wait for `P_DelSecnode`
  (`mobjstate`, wave 1); the removal half of the no-function mobj too.
- 273 `P_SetThingPosition` and 267 `P_CreateSecNodeList` captures are
  not decodable (a mobj in the middle of its spawn): their routines are
  checked through `P_SpawnMobj`'s cases, which include them.
- The generated streams G2-G10 and the seed search for full coverage
  (3.7) are the integrator's, with `ticgen.py --search`; G1's seed 1
  covers reborn, damage, weapon changes, plats, traces, floods, pickups,
  zone mobjs, not doors, switches, teleports or `P_RadiusAttack`.
- The runtime's sizes are over 4.7's budgets (deviation 2); the core
  leaves 4,489 B to the parts, which the placement measures.
- `menu states` (menuactive, showMessages) change only outside the
  level tics in the fixed runs: the stream has none yet.

## Wave 1 as integrated (2026-10-01)

Wave 1's five parts (`geom`, `mobjstate`, `secfind`, `flow`, `sight`)
merged by the integrator (3.8), on a2vm against `ref816`; nothing
committed. `src/native/game/integrated.txt` is 1: the shared outputs
count wave 1 as built, `make -f game.mk wave W=1` links the five
together, and **a part of an integrated wave now builds with its wave's
other parts** (`make -f game.mk part P=geom` links all five: `game.mk`'s
`PEARLY`, `glayout.py --part`), so each part's own harness reran its
checkpoint on the integrated code and placement. Each request is
accepted or refused with its reason in the part's record (section 5 of
`docs/game-parts/<part>.md`); the shared changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | `FCALL` makes a built target `.global` (no `.import` of an `FCALL` target: mobjstate R1, flow 2); `GA_MO` (mobjstate R4); `SCRATCH_REQUESTS['sight'] = 106` (sight R1: the blocks take 1,002 of 1,024 B); `TIC_GW_FIELDS` in GW after llayout's (`GM_*`, `p_map65.s`'s shared near scratch: geom R3; `SD_BUF`, `SD_AT`, `SN_BUF`, `API_W`: the API's); `TIC_MAIN_FIELDS` (`G_WSET`, after the globals block, so milestone 9's pre-state records keep their size); `DEMOB_LAYOUT` (flow 1); `GT_BASEPIC`, `UGLOWSPEED`, `USTROBEBRIGHT` (secfind 3, 5); `p_spec65.s:around` in secfind's helpers (secfind 4); `INLINED`, the helpers with no code of their own (mobjstate R10, secfind 4, sight); `OWN_STACK` (sight R6); `txr_compute`, `TXR_*` (flow 6, below); `--part` counts the integrated waves; the shared outputs' times renewed when made (the part tests' freshness checks) |
| `src/native/gobj.s` | Tic images only (`.ifndef LOADIMG`: the load image is unchanged byte for byte): `sd_get`, `sd_put`, `lt_get`, `bk_get`, `bk_put`, `sn_get`, `sn_put`, `sn_putw`, `mi_get`, `hn_get`, `hn_put`, `rj_row`, `rj_byte` (geom R2, mobjstate R2, secfind 1-2, sight R2): the parts' stand-ins are gone and no part makes a far access to a game record (`gameroutine.grep_check` on all 13 part sources: clean) |
| `src/native/gcall.s` | `fc_ret` keeps the callee's P across a restore's `gr_load` (secfind 11: the carry was lost); `gtest.s`'s `gt_fd` returns a carry through a restore, `gselftest.py`'s plant `fcall-flags-lost` is caught |
| `src/native/gthink.s` | `g_mrandom`, `g_mclearrandom` (tic images only; flow 4) |
| `src/native/game/grec.s` | `gt_record_it` takes `GA_0-1` (geom R1) |
| `src/native/game.mk` | a part's image links the integrated waves' parts |
| `tools/native/grun.py` | the entry's group from the build's `gplace.inc` (`entry_group`: geom R6, mobjstate R3, secfind 7, flow 5a); the math's RamWorks tables in every image (sight R3); `routine_sizes`, `contributions`, `module_bytes`; `PLANT_COPY` with every part's fragment |
| `tools/native/gplace.py` | `--measure`: the built parts' routines and the core's fixed bytes measured in a test build; `PINNED` (sight's six routines first in the core: sight R5); `AFFINITY` (geom R8, mobjstate R8, secfind 10); the inlined helpers get no bytes |
| `tools/native/gcallgraph.py` | `--stack` counts `OWN_STACK`; `reach_targets`: a dispatcher a routine reaches delivers every target of its table |
| `tools/native/gamecap.py` | `passes`: an entry never shares a pass with an entry that reaches it (geom R10, mobjstate R6) |
| `tools/native/ticcap.py` | each setup's re-key record from its own `P_MapEnd` return (flow 7) |
| `tools/native/gameroutine.py` | `lv_set_address`, `wset_records` (`G_WSET` from the reference's `W_SET`) |
| `tools/testpar.py` | `MODULE_TIMEOUTS['test_native_game_geom'] = 3600` (geom R12) |
| `src/native/game/README.md` | the conventions: `FCALL`'s `.global` and P, the dispatch tables' calling conventions, the core's helpers called with `jsr`, the new API calls, `GM_*`, test-only code in the driver's area, `G_WSET`, `DEMOB` |
| this file | 2.2's `THTAB` row, 2.4's lowfloor (geom R9) and mobjstate's node plant, 3.5's R7 (mobjstate R7, the part's named rule), this section |

**Test-only code leaves the core.** With the API grown (`gobj.s` 2,369
B) the core had 2,779 B for routines in test builds, 928 B of it the
parts' test-only harness code (`geomt.s`, `sftest.s`, flow's
`fl_timed`/`fl_sweep`); sight's 3,195 B could not go in. Every part's
test-only code is now in segment `DRIVER`, the card's `$E000` area after
the test driver (2,387 of 3,584 B with wave 1's), with `FC_HERE .set 0`;
the harnesses read its labels from the card (`mobjstate.py`'s
`ms_t_res`; `flowcheck.py`'s allowed places), and the release is
unchanged. The core's fixed part is then 9,093 B (the runtime,
milestone 9's core, `grec.s`, `g_resume`), 3,707 B for routines.

**The placement** (`gplace.py --measure build/native/game/wave1/wtest
--write`, with the remade survey's calls): the core holds sight's six
routines (3,195 B), `ST_Ticker`, geom's `sectorFloor` unit, and three
of `chasemove`'s estimated routines (`CORE_FIRST`); 28 groups. The
same-slot cost is 5.3 ms a tic at the mean by the model, almost all
between routines of parts not built yet, placed by estimates
(`G_Ticker` and `P_Ticker`, `P_MobjThinker` and `P_ZMovement`): each
integration places again with the measured sizes, and the final
placement comes from the `gprof` build's heat (5.4).

**Findings of the integration.**

1. *The load's textures* (flow 6): upstream's `R_GetTexture` sets
   `texturetranslation[n] = n` for each texture it makes: at every
   `P_SetupLevel` each side's textures and a switch's partner (the
   PU_LEVEL textures are freed by its `Z_FreeTags` [R
   `p_setup65.s:122`, `:684-688`]), and, for another map than the
   window's `W_SET`, `W_LevelDone`'s `moreColumns` [R
   `m_menu65.s:1780-1789`]. Only `P_UpdateSpecials` writes another value,
   into `basepic .. basepic + 2` [R `p_spec65.s:328-336`], so only those
   entries can differ: E1M2's setup makes 62, E1M4's 63 and its
   `W_LevelDone` 61 and 62 (`glayout.txr_compute` from `umodel.py`; on
   the 57 setup dumps every entry a mask resets equals its texture, 30
   entries). `g_resume` applies the masks with `G_WSET` (upstream's
   `W_SET`: in the reference's 8 MB mode `LV_RES` keeps it across the
   intermission and title pictures, checked on every setup's E dump);
   no lockstep tic sees the difference (the load's tic runs
   `P_UpdateSpecials`), but a routine run of a load does, and a paused
   tic would.
2. *The survey missed every action of `P_SetMobjState` but
   `A_FaceTarget`* (mobjstate R6, geom R10): `gcallgraph.reach_targets`
   followed static references only, so a dispatcher reached its table's
   targets only when its code named them (P_SetMobjState: the rocket
   cheat's `A_CyberAttack`); the survey then never logged the actions in
   the dispatcher's pass. With the closure, and an entry never in the
   pass of an entry that reaches it (a JML-entered entry logged with its
   return names its dispatcher's caller), the survey takes 40 passes
   (was 5) and finds demo3's `P_SetMobjState` reaching `A_Chase` 53,
   `A_FaceTarget` 38, `A_Look` 32 times, and `P_BlockThingsIterator`
   `PIT_RadiusAttack` 3 (DEMO1) and 16 (DEMO2) times: every call count
   unchanged.
3. *The re-key records* (flow 7): `ticcap.py` took the i-th `P_MapEnd`
   return as the i-th setup's end; it now takes each setup's first
   return after its entry: the 22 setups of the five fixed runs decode
   with 0 problems, where all 22 had five (checkpoint S3's re-key records
   came from the wrong `P_MapEnd` return, its first setups' included);
   the tic references are remade (`shared/tic/`: every tic's digests and
   every stream unchanged, only the setups' records).
4. *A plant that no check can catch*: mobjstate's "a freed node put at
   the free list's tail". The canonical model numbers the free sector
   nodes in the free list's order (`tools/bridge/identity.py`), so a
   free list's order is not state; the plant's earlier catch came from
   its interplay with the stand-ins' temporaries, and with the API its
   254 `P_DelSeclist` cases pass. Replaced (2.4) by a freed node left off
   the free list, caught.
5. `fc_ret` lost the flags of a return through a restore (secfind 11):
   fixed for every part.

**The checkpoints, rerun together** (each part's own harness on the
integrated code: a part's image links the five parts; the new placement;
both fills, both profiles; 2026-10-01/02):

| Part | Command | Runs | Failed | Stray writes | Also |
| --- | --- | ---: | ---: | ---: | --- |
| `geom` | `geom_check.py --run --iter --rand --report --jobs 2` | 11,240 | 0 | 0 | 64 `posMul` runs undecodable (mid-setup), 72 `P_BlockThingsIterator` runs waiting for `PIT_RadiusAttack` (`look`); recording callback 2,432 runs, 0 failed; 900,000 point-line and 900,000 box-line pairs and 100,000 `posMul` inputs, 0 failed |
| `mobjstate` | `mobjstate.py --check --plants --jobs 2` | 8,816 | 0 | 0 | 7 plants caught (`node-not-freed` for the unobservable tail plant) |
| `secfind` | `secfind.py --check --jobs 2`, `--mod3`, `--plants` | 47,260 | 0 | 0 | `mod3` on all 65,536 inputs equal; 5 plants caught |
| `flow` | `flowcheck.py --checkpoint`, `--sweeps`, `--random`, `--plants` | 6,392 | 0 | 0 | the tour's 8 world-done loads now equal (the textures, finding 1); every tic's sweeps 0 failed; `times100`, `div1000` 100,000 inputs, `signLong` all 65,536, 0 failed; 6 plants caught |
| `sight` | `sight.py --check --jobs 2`, `--random`, `--paging --report` | 6,476 | 0 | 0 | the hint-free answer on all 2,028 `P_CheckSight` cases; `smul48`, the side test 100,000 inputs, the magnitude all 65,535, 0 different |

Sizes (test builds' map; test-only code in the driver's area not
counted): `geom` 1,441 of 2,200 B, `mobjstate` 2,167 of 1,900 (+14%),
`secfind` 1,403 of 1,800, `flow` 2,992 of 2,300 (+30%), `sight` 3,180 of
3,600. The core $6600-$9658 (12,377 of 12,800 B in the wave image; the
release's 11,979), the driver's area 2,387 of 3,584 B. Timing moved with
the placement: `P_RemoveMobj` 0.79 ms at the median on `f121` (1.82 ms
before), `EV_LightTurnOn` 6.6 ms (8.7), a `P_CheckSight` that sees 134,459
cycles at the median (203,071), `P_UpdateSpecials` 0.42 ms (0.12: its
helpers in another group of its slot now); every number is routine mode
with every slot empty at the call (an upper bound), in each report.

**The test suite**: `python3 tools/testpar.py`: 73 modules, 1,528 tests,
0 failures, 0 errors, 0 skipped (2,378 s of wall time at 9 jobs;
`test_native_game_geom` 2,377 s within its 3,600 s). `build/` grew by
about 5 MB (`build/native/game` 592 to 597 MB: the remade survey); every
temporary directory deleted.

**Not done in this integration** (open items):

- One routine harness. The five parts each extended the routine harness
  in their own tool (`args.json` forms, the stray-write check from
  a2vm's write log, the call's own time, `as` kinds); the shared pieces
  that change results are in `grun.py` and `gameroutine.py` now, but
  folding the five tools into `gameroutine.run_case` (and rerunning
  every checkpoint through it) is left: wave 2's parts should import the
  wave-1 tools' functions rather than write a sixth.
- `ticrun.py`: filling `DEMOB` by `DEMOB_LAYOUT`, pointing `dg_resume` at
  part `tic`'s resume entry and writing `G_WSET` at a run's start wait
  for part `tic` (wave 6).
- `LOGTAB` (banks 123-124): the native never reads it (sight's decision),
  but freeing it changes milestone 9's store and disk: left for 5.5's
  bank report.
- geom R11 (`bl_get`'s window): a timing lever for 5.4.

## Wave 2 as integrated (2026-10-02)

Wave 2's five parts (`tracel`, `damage`, `pickup`, `lines`, `spawn`)
merged by the integrator (3.8), on a2vm against `ref816`; nothing
committed. `src/native/game/integrated.txt` is 2: the shared outputs
count waves 1 and 2 as built (`ITTAB`'s `PIT_AddLineIntercepts` and
`LSTAB`'s `lnExit` filled), and every part's image links the ten parts.
Each request is accepted or refused with its reason in its part's record
(section 5 of `docs/game-parts/<part>.md`); the shared changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | **W's map**: the core `$6600-$99FF` (13,312 B, was 12,800), the scratch blocks `$9A00-$9DFF`, slot 1 `$9E00-$A5FF` (2,048 B, was 2,560: `gplace.py` cuts every group at slot 2's 2,048 B, so the 512 B were never used) (damage R1, below); `TIC_GW_FIELDS` `GM_TRACE` .. `GM_INVB` (tracel R1), `GM_ATRANGE` (spawn 1); `TIC_MAIN_FIELDS` `G_FPSSHOW` (pickup P4); `constants()` `GT_SWLIST`, `GT_SWIDX` (lines 1), `ITTAB_`/`TRVTAB_`/`LSTAB_<label>` (lines 2); `ggame.inc`'s `SYM_<unit stem>_<label>` for the manifest's 228 symbols (pickup P1); `INLINED` for the five parts (tracel R3, damage R3, pickup P2, lines 4, spawn 3) |
| `tools/native/llayout.py` | `lgame.inc`: `U_WI_AMMO/DOWN/ATK/FLASH_w` beside `U_WI_UP/READY_w` (damage R2); `U_CLIPAMMO_a`, `U_HALFCLIP_a`, `U_POWERTICS_p`, `U_BONUSADD`, `U_GOD_HEALTH`, `U_IDFA_ARMOR`, `U_IDFA_ARMOR_CLASS`, `U_NUMCHEATS` (pickup P1: the release's tables and `.equ`s; the load image's bytes unchanged) |
| `src/native/math.s`, `mathgame.inc` (new), `game.mk`, `math.mk` | **The game's math** (damage R1): `math.s -D GAMEMATH` assembles only `pta3`, `pta_oct`, `finesine`, `finecosine`, `cosexc` (one text, `mathgame.inc`, which the whole module includes too) into the core of every tic image as `math-g.o` (672 B), on `math-r.o`'s `mt_far`, `udiv32`, `pta_tab`; the render build is byte for byte unchanged (linked and compared), the whole module's `MATHW` the same size in another order (`test_native_math`, its cosine plant now in `mathgame.inc`) |
| `tools/native/gplace.py` | `AFFINITY`: tracel's crossed line (1,721 B), its long trace's vertex sides (368), SIDE1's helpers (300) (R2, in part: the whole 2,089 B passes 2,048); damage's group (R7); pickup's touch and cheats (P3); lines' finder with `P_CheckTag` (4); spawn's height move and puffs (2); `CORE_FIRST` `wInfo`, `wInfoOf` (damage R7) |
| `tools/native/gameroutine.py` | `run_case`: a NULL pointer `as: mobj` is `$FFFF` (damage R5); `tic_main_records` (`G_WSET` and `G_FPSSHOW` from the reference: pickup P4) |
| `tools/native/gparts/mobjstate.py` | the shared stray rule: the tic globals after the globals block (`G_WSET`, `G_FPSSHOW`), and `mt_far`'s two operand bytes (damage R6: every part that reaches the game's math) |
| `src/native/ghook.s` | the header: `PICKUP_SOUND` in bit 7 of the sound (pickup P5); `AM_Stop` must test the automap's state (damage R4, milestone 11's) |
| `src/native/game/README.md` | the `LSTAB` convention's thing and side (lines 3), the table numbers by name, the inlined wrappers, the game's math and `weaponinfo` in the core, `GM_*`'s new names and the other shared names, `G_FPSSHOW`, capturing a `JML`-entered routine (tracel R6), `setUpModule`'s case directory, the parts' interfaces (damage R8), the grep's scope |
| this file, `MATH.md`, `MEMORY_MAP.md` 17 | 3.6 T8 and 2.4's `tracel` row and risk 6 (tracel R4, R5); 4.1's W rows; `MATH.md`'s `fixedDiv` row and its three builds; the W, GW and globals rows |
| the parts' records | wave 2's interfaces noted in `tracet`, `path`, `attack`, `evworld`, `evfloor`, `teleport`, `pspr`, `player`, `tic` (pickup P6: the cheat events), `checkpos`, `look`, `chase`, `missile`, `xymove`, `wfire`, `trymove` |

**The parts fixed by the integration.** `tracel.s`'s three wrappers and
`tracel.inc`'s stand-ins are gone (`TL_*` = `GM_*`); `spawn`'s `sp.inc`
stand-in; `lines.s`'s `LN_GT_*` and `LSN_*` (its test checks the shared
names); `pickup`: `pickup_gen.py`, `pkgen.inc` and its fragment's rule
are gone, the sources use `SYM_*` and `lgame.inc`'s `U_*`, `giveWeapon`
reads damage's `weaponinfo` (P1's `PK_WIAMMO_*` refused: one table),
idrate uses `G_FPSSHOW`, `pickup.py` writes the reference's flag there,
its owned-weapon plant follows the new code, its test checks every
`SYM_*`; `damage`: `dmath.inc` is gone, `dinter.s` calls `pta3`,
`finecosine`, `finesine`, `weaponinfo` is written from `U_WI_*` and
checked against `UO_WI_*`, a plant's import line follows.

**Findings of the integration.**

1. *The core had no room for the game's math.* The tic images link
   `math-r.o` (the render subset), which lacks `R_PointToAngle3` and the
   sines; damage carried them in its own group (656 B), and `look`,
   `chase`, `attack`, `missile`, `player` (`movePlayer`, `P_CalcHeight`
   every tic), `pspr` (`A_WeaponReady` every tic), `xymove`, `teleport`,
   `wfire` call them too, so they must be resident. With sight's pinned
   3,172 B the core left 3,599 B for routines at 12,800; the fixed part
   with the math is 9,873 B. Slot 1's 512 B over slot 2's were never used
   (every group is cut at 2,048 B so that either slot holds it), so the
   core took them: 3,439 B for routines now, 3,434 placed (sight's six,
   `P_NewChaseDir`, `P_TryWalk`, `wInfo`, `wInfoOf`, `ST_Ticker`, geom's
   `sectorFloor` unit, two small helpers). The fit of 4.2 is unchanged in
   kind: the core is full, and its two levers (the card's bank 2,
   `TIC_LC2`; the caches' sizes) stay the owner's choice.
2. *A test module's case directory.* `lines` and `secfind` set
   `gamecap.CASES` (one global) when imported; in one process (`unittest
   discover`) another part's harness can change it before their tests
   run (`lines`' `Build.test_tables` found no case). Their test modules
   set it in `setUpModule`.
3. *The far-access grep* flags `tracelt.s` (tracel's test-only driver
   in the card's driver area, reading its own record banks 93-97): not
   game code; the README says the rule is for the parts' game sources,
   on which it is clean (23 sources).

**The placement** (`gplace.py --measure build/native/game/wave2/wtest
--write`, the core's fixed part 9,873 B measured): 27 groups, every one
at most 2,048 B; the same-slot cost 4.16 ms a tic at the mean by the
model (5.28 before); no pair of one slot with more than one call a tic at
the median; `A_Chase`'s rule kept. Wave 2's units: tracel's crossed line
with `P_PointOnLineSide` (group 9, slot 1, 2,015 B), damage (19, slot 1),
the touch (18, slot 1) and the cheats (25, slot 1), lines' finder with
`P_CheckTag` (10, slot 2), the height move (23, slot 2), the puffs (6,
slot 2).

**The checkpoints, rerun together** (each part's harness on the
integrated code: every part's image links the ten parts; the new W map
and placement; both fills, both profiles; 2026-10-02, at 3 jobs each).
On 2026-10-02, while `sight`'s rerun was going, the owner asked to
reduce the checks so that milestone 10 finishes sooner: the merge was
finished lean (the shared changes checked, every image rebuilt with
`make -B` and no warnings, the test suite once); the runs below had
already finished, and later waves' integrations do not rerun earlier
parts' checkpoints (the final integration does what is needed):

| Part | Command | Runs | Failed | Stray writes | Also |
| --- | --- | ---: | ---: | ---: | --- |
| `geom` | `geom_check.py --run --iter --rand --report --jobs 3` | 11,240 | 0 | 0 | 64 `posMul` undecodable, 72 `P_BlockThingsIterator` runs waiting for `PIT_RadiusAttack`; the recording callback 2,432 runs, 0 failed; 900,000 point-line and box-line pairs, 100,000 `posMul`, 0 failed |
| `mobjstate` | `mobjstate.py --check --plants --jobs 3` | 8,816 | 0 | 0 | 7 plants caught |
| `secfind` | `secfind.py --check --jobs 3` (with `--mod3`, the plants) | 47,260 | 0 | 0 | `mod3` all 65,536 inputs equal; 5 plants caught |
| `flow` | `flowcheck.py --checkpoint`, `--sweeps`, `--random`, `--plants` | 6,392 | 0 | 0 | every tic's sweeps 0 failed; `times100`, `div1000` 100,000, `signLong` 65,536, 0 failed; 6 plants caught |
| `sight` | `sight.py --check --jobs 3` | not rerun | - | - | stopped at 2,560 of 3,238 cases when the owner asked for a lean merge (below), with no failure reported up to then; wave 1's result stands, and `test_native_game_sight` ran in the suite |
| `tracel` | `tracel.py --run --logs --rand --report --jobs 3` | 11,300 | 0 | 0 | every logged call (10,893 `interceptVector3`, 571 `divlineSide`), 0 failed; the random checks (1,000,000 each, `ivTest` 300,000, the rest 100,000, `gOf` 65,536), 0 failed, 0 model differences; its 3 plants in its test |
| `damage` | `damage.py --check --jobs 3`, `--random`, `--plants` | 3,596 | 0 | 0 | the thrust's 100,000 inputs 0 different; 4 plants and the random one caught; still waiting: 56 `A_Lower`, 4 `A_Chase` (stop checks and variants) |
| `pickup` | `pickup.py --check --jobs 3`, `--plants` | 4,560 | 0 | 0 | 4 plants caught |
| `lines` | `lines.py --check --jobs 3`, `--plants` | 5,112 | 0 | 0 | 3 plants caught |
| `spawn` | `spawn.py --check --jobs 3`, `--random`, `--plants` | 7,592 | 0 | 0 | `shr3` 100,000 inputs 0 different; 4 plants caught |

No case became newly eligible: wave 2 fills `ITTAB`'s
`PIT_AddLineIntercepts` (whose calls through `P_BlockLinesIterator`
tracel's block steps run, 4,012 runs) and `LSTAB`'s `lnExit` (lines'
synthetic exits); every waiting case waits for a later wave's routine.

Sizes (the wave image's map; test-only code in the driver's area not
counted): `tracel` 2,350 of 2,800 B, `damage` 1,902 (the table 108; own
1,794 of 1,800), `pickup` 2,025 of 2,100, `lines` 928 of 1,400, `spawn`
913 of 1,100; wave 1's unchanged. The core `$6600-$9974`, 13,173 of
13,312 B (the game's math 672, `weaponinfo` 108); the driver's area 3,186
(+61 descriptor) of 3,584 B; `gcallgraph.py --check` 0 failures,
`--stack` 80 of 160 B; banks unchanged (114 of 126, test builds).

Timing moved with the placement (routine mode, every slot empty at the
call, CPU cycles at the median): tracel's block steps 252,776 → 95,813
(worst 940,535 → 248,752), its single routines higher (their 2 KB group
loads at each call: `PIT_AddLineIntercepts` 12,096 → 41,579);
`P_DamageMobj` 115,791 → 70,762, `wInfo` 10,382 → 130 (the core);
`C_Responder` 188,052 → 40,989 and `P_TouchSpecialThing` 305,670 →
308,031 fabric clocks (`f121`, worst 654,881 → 344,396); `findSpecial`
148.6 → 45.7 µs; `P_SpawnBlood` 75,707 → 53,122, `isPlayer` 5,147 →
19,890 (its group now 970 B); secfind's `P_UpdateSpecials` 0.42 → 0.72
ms. Every number is an upper bound in each report.

**The test suite**: `python3 tools/testpar.py`: 78 modules, 1,578 tests,
0 failures, 0 errors, 0 skipped (3,006 s of wall time at 9 jobs, with
another session's runs on the Mac; `test_native_game_geom` 3,005 s
within its 3,600 s, wave 2's modules 472-1,167 s). Before it, every
image (`shared`, `skel`, `wave W=2`, `game`, `gprof`, `release` and the
five parts' `part P=`) rebuilt with `make -B`: no warnings. `build/` grew by about 395 MB since wave 1's
integration (`build/native/game` 597 to 992 MB: the five parts' own
cases and images, 343 MB, the wave image 16 MB; 4.7 GB in all); every
temporary directory deleted.

**Not done in this integration** (open items):

- The one routine harness (wave 1's open item): the ten parts' tools
  share `mobjstate.py`'s and `secfind.py`'s machinery; folding them into
  `gameroutine.run_case` is left.
- lines' request 5 (the reference's sound events in a case): for wave
  3's integration, when `evworld` makes the handler cases eligible.
- `tracet`'s `sideSetup` joins the unit `ivSetup`, `gOf`, `smul`, `vsC`
  (tracel R2) when built.
- The core is full (finding 1); the timing report (5.4) and the owner's
  levers decide what more goes in.
- No run reaches `PIT_AddLineIntercepts`' long-trace and shot paths,
  `fixedDiv`'s non-returning inputs, a punch's melee range or a missile
  at the ceiling: synthetic and random checks only; the generated
  streams (3.7) may reach them.

## Wave 3 as integrated (2026-10-02)

Wave 3's five parts (`tracet`, `checkpos`, `pspr`, `evworld`, `look`)
merged by the integrator (3.8), on a2vm against `ref816`; nothing
committed. **Lean**, at the owner's request of 2026-10-02: the requests
applied, every image rebuilt with `make -B` and no warnings, the wave's
five test modules and the suite run once; no part's checkpoint, planted
bugs, demo, tic stream or timing rerun (the final integration does what
is needed). `src/native/game/integrated.txt` is 3: the shared outputs
count waves 1-3 as built (`ACTTAB`'s weapon actions, `A_Look`,
`A_FaceTarget`, the screams, `A_Pain`, `A_Fall`; `ITTAB`'s
`PIT_RadiusAttack`; `LSTAB`'s `lnDoor`, `lnVDoor`, `lnPlat`), and every
part's image links the fifteen parts. Each request is accepted or refused
with its reason in section 5 of its part's record; the shared changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | `TIC_GW_FIELDS` `GM_RR`, `GM_SIDE1` (15) (tracet R4); `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMBBOX`, `GM_SPECHIT`, `GM_MPTRY` (checkpos R1): GW's tic fields now end at `$B356` (170 B free); `GS['FLOOD'] = 16` (pspr R4); `OWN_STACK` `checkPos` 12 (checkpos R3), `P_RadiusAttack` 10, `A_Look` 1 (look 4); `INLINED` for the five parts (tracet R1, checkpos R4, pspr R1, evworld 1, look 1) |
| `tools/native/gplace.py` | `AFFINITY`: tracet's block steps and `thSide`; `sideSetup`, `longTrace` in tracel's `ivSetup` unit (tracet R2, wave 2's open item); checkpos's six routines but `checkThing` (R2, as two groups); pspr's weapon routines (R6); evworld's handlers and their routines (2); look's three units (3) |
| `src/native/math.s`, `mathgame.inc` | `aproxdist` moved into `mathgame.inc`, so the game build `math-g.o` has it (look 2): 826 B in the core (154 more); the full build's `MATHW` the same size in another order; the render build unchanged |
| `src/native/gweap.s` | `bringUpWeapon` exported at gw_setup's bringUpWeapon (pspr R2; no byte changed) |
| `tools/native/gparts/lines.py` | `expected_sounds`: evworld's model for `lnVDoor`, `lnDoor`, `lnPlat` (evworld 3, lines' request 5 for these handlers) |
| `src/native/game/README.md` | the new `GM_*` names, the trace's flags, the parts' interfaces of waves 2 and 3 (tracet R5, checkpos R5, pspr R8, look 5), capturing at a dispatch stub that its target can enter again (look 6) |
| this file, `MATH.md`, `LEVELS.md` 5.5, `MEMORY_MAP.md` 3.5 | 3.5 R4's evidence (tracet R3); 2.4's `pspr` row (pspr R7) and `evworld` row (evworld 4: the locked door's order cannot be seen); the game build's `aproxdist`; the flood's 1,024 B work stack of 2-byte entries |
| the later parts' records | wave 3's interfaces noted in `path`, `movers`, `trymove`, `teleport`, `chasemove`, `chase`, `xymove`, `missile`, `wfire`, `player` |

**Refused**: pspr R3 (`fl_idx`, `fl_ent` in the object API: the API is
in the core, which is full; the flood is cold and reads its lists through
`lt_get`, an API call, in its own group's bytes) and pspr R5
(`P_LineOpeningXY` in the flood's group: every line of a position check
and of the traversers would then load a 1.9 KB group with 1 KB of dead
stack; the flood keeps its own `opening` and calls only the core, so its
stack cannot be lost). checkpos R2 was applied as two groups and look 3
as units outside the core, for the same reason (the core is full).

**The parts fixed by the integration.** `tracet.inc`'s ten stand-ins
are `GM_RR`, `GM_SIDE1 + k` (the walks' bytes moved down: `TT_NEED` 13);
`checkpos.inc`'s `CPG` stand-ins at `$B3D0` are the `GM_TM*` names,
`args.json`'s places `gw:`; `pspr.s`'s `bringUp` stand-in is gone
(`A_Lower` ends with `jmp bringUpWeapon`), `pspr.inc`'s `PS_GS_FLOOD` is
`GS_FLOOD`, `pflood.s` says why its two pieces stay; `look.s`'s
`aproxdist` copy is gone (`distanceAT` is `jmp aproxdist`), and
`test_native_game_look` checks that no stand-in is left.

**The placement.** The wave-2 placement no longer fit (`LOADW`
overflowed the core by 15 B with `aproxdist`), so it was made twice: first
from wave 2's measured image (the core's fixed part + 136 B) with each
wave-3 part's own image for its routines, then, once the wave image
linked, `gplace.py --measure build/native/game/wave3/wtest --write` (the
core's fixed part 9,919 B): 27 groups, each at most 2,048 B; the core
3,390 of 3,393 B for 14 routines (sight's six, `P_NewChaseDir`,
`P_TryWalk`, `wInfo`, `wInfoOf`, `ST_Ticker`, two small ones and path's
`callTrav`); the same-slot cost 5.17 ms a tic at the mean by the model
(4.16 at wave 2); `A_Chase`'s rule kept. One pair of one slot has more
than one call a tic at the median: groups 2 and 22 (slot 2,
`P_XYMovement` calling `P_TryMove`, 2.9 calls), both of wave 5's parts
`xymove` and `trymove`, placed from estimated sizes; their wave's
placement decides. Wave 3's units: tracet's block steps (group 24, slot
1), `sideSetup` and `longTrace` with `ivSetup` (15, slot 1), the position
check (8, slot 1) and `checkThing` (18, slot 1), the weapon (26, slot 2),
the flood (21, slot 1), the doors and plats (13, slot 2), the look (14,
slot 2), the radius attack (19, slot 1).

**Checks.** `gcallgraph.py --check` 0 failures (935 heads, 589 reachable
from the tic); `--stack` 56 + 24 IRQ = 80 of 160 B. Every image (`shared`,
`skel`, `wave W=3`, `game`, `gprof`, `release`, the five parts' `part
P=`, and damage's) rebuilt with `make -B`, one at a time, after the
fixes below: no warnings (in parallel, `-B` races on the skeleton's
objects that every target rebuilds: ld65 read errors). The wave's test
modules (`python3 -m unittest discover -s tests -p
test_native_game_<part>.py`, default mode): `tracet` 8 tests (2 skipped:
`DOOM_GS_FULL`), `checkpos` 6 (2), `pspr` 9 (2), `evworld` 9 (1),
`look` 7: all OK, on the integrated images (the shared `GM_*` places,
`aproxdist`, `bringUpWeapon` and the new placement).

**The test suite**: `python3 tools/testpar.py` once (103 modules, 1,895
tests, 3,304 s of wall time at 9 jobs, with another session's milestone 11
runs on the Mac): 100 modules OK, 3 failed, each fixed in its harness or
its test (no check weakened), then the 4 changed modules rerun with
`python3 tools/testpar.py --timeout 3600 test_native_game_geom
test_native_game_damage test_native_game_mobjstate test_native_game_pspr`:
40 tests, 0 failures, 0 errors (2,038 s). So the suite stands at 103
modules, 1,905 tests, 0 failures, 0 errors, 7 skipped (the `DOOM_GS_FULL`
tests of wave 3's modules).

**Findings of the integration** (what the suite found):

1. *The driver's area.* Every part image now links `pspr`'s test-only
   `pstest.s` (132 B), and damage's image (with its own `dtest.s`)
   overflowed the driver's area by 67 B. `pstest.s` is linked only into
   pspr's own image now (`part.mk`'s `PS_TEST=1`, which `pspr.py`
   passes, as damage's `DM_TEST`); README "Test-only code" says so. The
   wave image's driver's area is 3,186 of 3,584 B.
2. *Built actions counted as unbuilt.* `mobjstate.py`'s `waiting_for`
   took every other part's action as unbuilt; with wave 3's actions in
   `ACTTAB` its stop checks of `P_SetMobjState` ran them whole ("no
   stop"). It now uses `glayout.built_set` (as `game.mk`'s part target),
   and the rocket cheat's synthetic calls whose own action is built are
   the reference's own call compared whole. `damage`'s test expected its
   player deaths to stop at `A_Lower`; they now run it whole, equal to the
   reference, and the test checks that (`test_a_lower_runs_whole`).
3. *The stray rules.* An action run whole writes its own part's scratch
   block (look's `loadTarget` under `A_FaceTarget`): the shared rule
   (`mobjstate.allowed_main`) allows the blocks of the parts built in the
   image, an unbuilt part's block staying a stray; geom's rule allows
   P_Random's index (`PIT_RadiusAttack`'s `P_DamageMobj`).
4. *A callback's context.* Geom's 72 `P_BlockThingsIterator` calls that
   waited for `PIT_RadiusAttack` became eligible; the callback reads
   bombspot, bombsource and bombdamage, which its caller leaves in
   upstream's scratch (`AT_BSPOT`, `AT_BSOURCE`, `AT_BDAMAGE`) and in
   look's scratch block natively, which a call of the iterator alone did
   not seed ($A5A5 handles). `geom_check.CALLBACK_CONTEXT` seeds them from
   the reference's entry (offsets read from `look.inc`); the 80 runs of
   the iterator's cases are equal.

Sizes (the wave image's map; test-only code in the driver's area not
counted): `tracet` 1,865 of 2,800 B, `checkpos` 2,197 of 2,600, `pspr`
2,485 (the flood's 1,024 B work stack included: 1,461 of 1,200 B of
code, +22%), `evworld` 1,310 of 1,600, `look` 2,435 of 2,300 (+5.9%);
earlier waves' parts unchanged. The core `$6600-$99A9`, 13,226 of 13,312
B (the game's math 826); the driver's area 3,186 of 3,584 B (finding 1).
A second `gplace.py --measure` on the rebuilt wave image gives the same
placement.

**Not done in this integration** (open items):

- No part's checkpoint was rerun on the integrated images (the lean
  rule); their test modules ran, each with a sample of its cases.
  `lines`' newly eligible handler cases (`lnVDoor`, `lnDoor`, `lnPlat`:
  646 `EV_VerticalDoor` calls in the survey), `damage`'s 56 cases that
  waited on `A_Lower` (its test's sample runs them whole, equal) and
  `look`'s cases that stopped at `A_Lower` are eligible now; their full
  checkpoints wait for the final integration.
- The core is full (wave 2's finding 1; `aproxdist` took 154 B more):
  pspr R3 and R5, checkpos R2's single group and GAME.md 4.3's `A_Look`
  in the core wait for the core's levers (the card's bank 2, the caches'
  sizes: the owner's choice) and the timing report (5.4).
- The parts' own open points (their records' section 4): the branches
  no sampled call reaches, the sounds not compared in routine mode (R6)
  until a capture logs `S_StartSound*`, `pspr`'s code 22% over its
  budget.

## Wave 4 as integrated (2026-10-02)

Wave 4's five parts (`path`, `trymove`, `planes`, `evfloor`, `teleport`)
merged by the integrator (3.8), on a2vm against `ref816`; nothing
committed. **Lean**, at the owner's request of 2026-10-02: the requests
applied, every image rebuilt with `make -B` and no warnings, the wave's
five test modules and the suite run once; no part's checkpoint, planted
bugs, demo, tic stream or timing rerun (the final integration does what
is needed). `src/native/game/integrated.txt` is 4: the shared outputs
count waves 1-4 as built (`THTAB`'s `T_MoveFloor`; `ITTAB`'s
`stompThing`; `LSTAB`'s `lnFloor`, `lnStairs`, `lnDonut`, `lnTele`), and
every part's image links the twenty parts. Each request is accepted or
refused with its reason in section 5 of its part's record; the shared
changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | `SCRATCH_REQUESTS['path'] = 44` (path R1: the blocks end at `$9DF6`); `INLINED` for the five parts (path R3 `callTrav`, trymove R1, planes 1, evfloor 1, teleport R1); `OWN_STACK` `P_TryMove` 2, `P_NightmareRespawn` 2 (trymove R2), `P_TeleportMove` 5 (teleport R3) |
| `tools/native/gplace.py` | `AFFINITY`: path's walk (R4); `P_XYMovement` with `P_TryMove` (trymove R3's second form: the core has no room); planes' six routines (2); evfloor's twelve (2); teleport's eight (R2) |
| `src/native/game/grec.s` | `gt_record_trv` takes `GA_0` (`TRVTAB`'s convention) and makes `ICPT + 6 × GA_0` in 16 bits (path R2: it took A, which `DCALL` cannot give, and read another entry from intercept 42 on) |
| `src/native/gpos.s` | `gp_secnodes` (`P_CreateSecNodeList`) leaves `GM_TMX`, `GM_TMY` = its thing's x, y, as upstream's (teleport R4; 11 B in the core, the tic phase only) |
| `tools/native/grun.py` | `routine_sizes` leaves the inlined names out: a local label named as an inlined helper (trymove's `overStep`) split its caller's bytes, which the placement then lost (found by this integration) |
| `tools/native/gparts/lines.py` | `expected_sounds`: evfloor's model for `lnFloor`, `lnStairs`, `lnDonut` (evfloor 3) |
| `src/native/game/README.md` | the `TRVTAB` traverser's convention (path R2); the interfaces of wave 4 and of the core's `P_CreateSecNodeList` (path R5, trymove R4, evfloor 4, teleport R5, planes 1.2); whole-machine variants (path R6) |
| this file, `MEMORY_MAP.md` 3.5 | 2.4's `planes` row and plants: upstream has no crush damage (planes 3); 5.2 row 6, acceptance 6 as found (path R6); the scratch blocks' 1,014 of 1,024 B |
| the later parts' records | wave 4's interfaces noted in `attack`, `player`, `xymove`, `chasemove`, `missile`, `tic`, `movers` |

**Refused**: trymove R3's `P_NightmareRespawn` beside `spawnXYZ` (cold,
skill 5 only: its 281 B would load with every puff and spawn of the hot
spawn unit) and its first form, `P_TryMove` in the core (no room).

**The parts fixed by the integration.** `path.inc`'s stand-in assertion
(12 B into `SB_TRYMOVE`) is `SB_PATH_SIZE >= PT_NEED`; `pttest.s`'s
`pt_rec_trv` is `jmp gt_record_trv`; teleport's `stompThing` lost its
84 B stand-in of R4 and `teleport.inc` its `TP_SSEC`, `TP_SHEAD`.

**The placement.** The wave-3 placement no longer linked (group 7 over
by 36 B), so it was made twice: first from wave 3's measured image (the
core's fixed part + 16 B for `gp_secnodes`) with each wave-4 part's own
image for its routines, then, once the wave image linked, `gplace.py
--measure build/native/game/wave4/wtest --write` (the core's fixed part
9,945 B), which gives the same placement again: 27 groups, each at most
2,048 B; the core 3,367 of 3,367 B for 11 routines (sight's six,
`P_NewChaseDir`, `P_TryWalk`, `wInfo`, `wInfoOf`, `ST_Ticker`;
`callTrav` and `P_MapEnd` left it); the same-slot cost 3.37 ms a tic at
the mean by the model (5.17 at wave 3); `A_Chase`'s rule kept. One pair of
one slot has more than one call a tic at the median: groups 24 and 26
(slot 1, `A_Chase` with `P_PlayerThink` and the player's movement, 2.9
calls), both of later waves' parts placed from estimates. A first measure
with the tmx copy as 17 B instead of 11 (the fixed part 9,951 B) left
`wInfoOf` 3 B out of the core and the model's cost went to 7.7 ms: the
core is that tight. Wave 4's units: path's walk (group 18, slot 2), `P_XYMovement`
with `P_TryMove` (8, slot 1; the position check 10, slot 2),
`P_NightmareRespawn` (14, slot 2), planes (23, slot 2), evfloor (11,
slot 1), teleport (17, slot 1). The model counts only calls between two
groups of one slot: path's walk (slot 2) calls tracet's `traceLines`
(slot 1), which calls tracel's `PIT_AddLineIntercepts` (group 9, slot 2),
so each crossed line reloads the walk's group on return, a cost the model
does not see (`path.md` 5).

**Checks.** `gcallgraph.py --check --built` (waves 1-4) 0 failures (935
heads, 589 reachable from the tic); `--stack` 56 + 24 IRQ = 80 of 160 B;
the far-access grep on the five parts' sources clean. Every image
(`shared`, `skel`, `wave W=4`, `game`, `gprof`, `release`, the five
parts' `part P=` with `PT_TEST=1` and `TP_TEST=1` too, damage's with
`DM_TEST=1`, pspr's with `PS_TEST=1`) rebuilt with `make -B`, one at a
time: no warnings. The wave's test modules (`python3 tools/testpar.py
test_native_game_path ... _teleport`, default mode): `path` 9 tests (1
skipped: `DOOM_GS_FULL`), `trymove` 6 (2), `planes` 9 (1), `evfloor` 9
(1), `teleport` 8 (1): all OK, 34 s, on the integrated images; and
`teleport` with `DOOM_GS_FULL=1` (every synthetic call on both profiles,
the dropper sequences of R4 on the core's fix): 8 tests OK.

**The test suite**: `python3 tools/testpar.py --timeout 3600` was started once on the integrated tree; its result was not in when this record was written (the integrator's report gives it, or the next integration reruns it).

Sizes (the wave image's map; test-only code in the driver's area not
counted): `path` 1,324 of 1,600 B, `trymove` 997 of 1,500, `planes`
1,216 of 1,600, `evfloor` 1,123 of 1,500, `teleport` 1,197 of 1,500;
earlier waves' parts unchanged. The core `$6600-$99C3`, 13,252 of 13,312
B (`gpos` 1,907, `grec` 153: +11 and +15); the driver's area 3,186 of
3,584 B (`pttest.s`, `tptest.s` only in their parts' own images).

**Not done in this integration** (open items):

- No part's checkpoint was rerun on the integrated images (the lean
  rule); their test modules ran, each with a sample of its cases. Newly
  eligible: `lines`' handler cases of `lnFloor`, `lnStairs`, `lnDonut`
  (their sound model now in `lines.py`); `lnTele`'s sounds have no model
  in `lines.py` (no survey run teleports, so no lines case reaches it;
  part `teleport` compares them itself); `geom`'s and `checkpos`'
  callers' cases that waited on `stompThing`, `T_MoveFloor`.
- `gp_secnodes` now writes `GM_TMX`, `GM_TMY` in every
  `P_SetThingPosition` and `P_CreateSecNodeList` of the tic phase; the
  suite's sampled checks of the earlier parts pass, their full
  checkpoints wait for the final integration.
- The core is full (3,367 of 3,367 B): `P_TryMove` in the core
  (GAME.md 4.3) waits for the core's levers, as wave 3's items.
- The placement model's blind spot above (a callee's callee in the
  caller's slot), for the timing report (5.4).
- The parts' own open points (their records' section 4): the branches
  no sampled call reaches, the `$5A` fill, the sounds not compared in
  routine mode (R6), path's acceptance 6 with 25 traces instead of about
  500, teleport's checkpoint synthetic only (no captured teleport yet).

## Wave 5 as integrated (2026-10-02)

Wave 5's five parts (`attack`, `player`, `xymove`, `missile`,
`chasemove`) merged by the integrator (3.8), on a2vm against `ref816`;
nothing committed. **Lean**, at the owner's request of 2026-10-02: the
requests applied, every image rebuilt with `make -B` and no warnings, the
wave's five test modules and the suite run once; no part's checkpoint,
planted bugs, demo, tic stream or timing rerun (the final integration does
what is needed). No earlier attempt of this merge had left changes in the
tree. `src/native/game/integrated.txt` is 5: the shared outputs count
waves 1-5 as built (`TRVTAB`'s five traversers; `ITTAB`'s
`PIT_AvoidDropoff`), and every part's image links the twenty-five parts.
Each request is accepted or refused with its reason in section 5 of its
part's record; the shared changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | `TIC_GW_FIELDS` + `GM_LINETARGET` (2 B, `$B356`; last, so that the fields before it keep their places: attack R1); `TIC_MAIN_FIELDS` + `G_ONGROUND` (`$1EFB`: player R1); `constants()` writes `SKY_PIC` (`levelconv.SKY_PIC`, `$FE`) into `ggame.inc` (attack R2, xymove R3); `INLINED` for the five parts (attack R3, player R2, xymove R2, missile R1, chasemove R1); `OWN_STACK` for fifteen routines (player R4, xymove R4, missile R3, chasemove R3) |
| `tools/native/gplace.py` | `CORE_FIRST` names `newChaseDir`, `doNewChaseDir`, `tryWalk` in place of the 7 B wrappers (chasemove R2); `AFFINITY`: attack's two units (R4), player's three (R3), xymove's two and `slideMove` with `P_XYMovement` and `P_TryMove` (R1), missile's spawners (R2), chasemove's two (R2); **new** `APART`: path's `traverseTo` and each `TRVTAB` traverser never in one slot (attack R4: the survey does not see the traverser's calls, upstream's `jml`); the slot search two-colours the forbidden pairs (A_Chase's rule and `APART`), then tries every slot of the moves when they are at most `EXHAUSTIVE` = 22 (a Gray code walk), else one move and two together: the old one-group greedy walk could not reach a legal state with two rules (it stopped at 4.1 ms a tic where 1.6 was legal); `apart_rule` in the placement and the exit status |
| `tools/native/gameroutine.py` | `tic_main_records` gives `G_ONGROUND` from `p_user65.s:PU_ONGROUND`'s low byte (player R1 (b): for part `tic`'s runs) |
| `tools/native/gparts/mobjstate.py` | the shared stray rule allows part `pspr`'s `ps_stack` (main) and the sides of `LVMAP` (aux: `P_ChangeSwitchTexture`'s `sd_put`) (player R5) |
| `tools/native/gparts/path.py`, `geom_check.py` | **found by the suite**: with `TRVTAB` built, 31 of part `path`'s 40 chosen captured calls became eligible as captured and run their own traverser, which reads what its caller set before `P_PathTraverse` (upstream's near scratch); the harness gave none of it, so demo1 h2362 (`PTR_ShootTraverse`) differed (a puff from a poisoned shootz: `validcount` one up, the sector nodes one off). `path.py`'s `TRV_CONTEXT` now writes each built traverser's context from the reference's state at the call (attack: `AT_SHOOT`, `AT_Z`, `AT_DAMAGE`, `AT_TOP`, `AT_BOT`, `AT_AIM`, `AT_RANGE`, `_g_linetarget`; player: `usething`; xymove: `SL_MO`, `SL_BEST`), places read from the part's include; then two `PTR_UseTraverse` calls wrote ghook's sound event buffer (`hk_ev`, `hk_y`), which `geom_check.allowed_main` now allows as mobjstate's shared rule does. All 40 captured calls equal (`$A5`, `f121`) |
| `src/native/game/README.md` | the `GM_*` paragraph (`GM_LINETARGET`, `SKY_PIC`, `G_ONGROUND`); "The parts' interfaces" with wave 5's rows (attack R5, player R6, missile R4, chasemove R4) |
| this file, `MEMORY_MAP.md` 3.5, `playlayout.py`'s docstring | 2.4's row `player`: the lean plants (player R6); the GW and main rows (`GM_LINETARGET`, `G_ONGROUND`; the globals end at `$1EFB`) |
| the later parts' records | wave 5's interfaces noted in `wfire`, `chase`, `tic` |

**Refused**: player R1 (c), the bridge's schema gaining `PU_ONGROUND`
(optional in the request): it changes milestone 9's canonical state and
manifests, more than a lean merge reruns; the tic-level comparison can add
it with its own acceptance runs.

**The parts fixed by the integration.** `attack.inc`: `AK_LTGT =
GM_LINETARGET`, the places after it 2 B down (`AK_NEED` 27 of 32),
`AK_SKYPIC = SKY_PIC`; `args.json`'s linetarget output `gw:GM_LINETARGET`;
`xymove.inc`'s `XY_SKYPIC = SKY_PIC`; `player.inc`'s `PY_ONG =
G_ONGROUND`, `args.json`'s four `sb:PY_ONG` now `main:G_ONGROUND`, and
`player.py` reads `main:` places from `glayout.TGM` (then `llayout.G`).

**The placement.** The wave-4 placement no longer fitted (xymove's
measured group 8 at 2,046 of 2,048 B before attack), so it was made twice
as at wave 4: from wave 4's measured image (the core's fixed part 9,945 B)
with each wave-5 part's own image for its routines, then, once the wave
image linked, `gplace.py --measure build/native/game/wave5/wtest --write`,
rebuilt, and measured again: the same placement (a fixed point). 26
groups, each at most 2,047 B; the core 3,362 of 3,367 B for 11 routines
(sight's six, `tryWalk`, `wInfo`, `wInfoOf`, `ST_Ticker`, `P_MapEnd`;
`newChaseDir`, `doNewChaseDir`, `pMove` and `A_Chase` do not fit); the
same-slot cost 1.58 ms a tic at the mean by the model (3.37 at wave 4);
`A_Chase`'s rule and `APART` kept; no pair of one slot with more than one
call a tic at the median. Wave 5's units: attack's traversers group 13
(slot 1; path's walk group 3, slot 2), its entries group 6 (slot 1); the
player's think group 10 (slot 2), its use group 15 (slot 1), its special
floors group 11 (slot 1, with `A_Chase`); `P_XYMovement`, `P_TryMove`,
`slideMove` group 2 (slot 1), the move's helpers group 3 (slot 2), the
slide group 15 (slot 1: the move's slot); the missile spawners group 8
(slot 1), `checkMissile` group 9 (slot 2, `checkPos`'s, with
`P_DamageMobj`'s group 16 in the same slot, so missile's review-1 case
still holds); the chase's move and direction group 18 (slot 2, not
`A_Chase`'s), the drop-off group 5 (slot 2). The blind spot of wave 4
stays (a callee's callee in the caller's slot): `pMove` (slot 2) reaches
`checkPos` (slot 2) through `P_TryMove` (slot 1).

**Checks.** `gcallgraph.py --check --built` (waves 1-5) 0 failures (935
heads, 589 reachable from the tic); `--stack` 64 + 24 IRQ = 88 of 160 B;
`glayout.py --check` ok. Every image (`shared`, `wave W=5`, `skel`,
`game`, `gprof`, `release`, the five parts' `part P=` with `AK_TEST=1`,
`PL_TEST=1`, `XY_TEST=1`, `MS_TEST=1`, `CM_TEST=1`) rebuilt with `make
-B`, one at a time: no warnings. The wave's test modules (`python3
tools/testpar.py test_native_game_attack ... _chasemove`, default mode):
`attack` 8 tests (1 skipped: `DOOM_GS_FULL`), `player` 8 (2), `xymove` 7
(2), `missile` 9 (2), `chasemove` 9 (2): all OK, 33 s, on the integrated
images (every skip is a `DOOM_GS_FULL` one).

**The test suite**: `python3 tools/testpar.py` once on the integrated
tree: 114 modules, 1,997 tests, 1 failure, 0 errors, 22 skipped (every
skip a `DOOM_GS_FULL` one), 2,968 s wall (the machine was loaded:
`test_native_game_geom` alone 2,967 s). The failure was
`test_native_game_path`'s checkpoint, fixed as the table says (`path.py`,
`geom_check.py`); then `python3 tools/testpar.py test_native_game_path
test_native_game_tracet` (the modules that use the changed rule, but
`geom` and `tracel`, whose passing runs a wider rule cannot fail): 17
tests OK; every chosen `path` captured call (`check_cases` kind `plain`):
40 of 40 equal.

Sizes (the wave image's map; test-only code in the driver's area not
counted): `attack` 2,149 of 2,500 B, `player` 2,725 of 2,800, `xymove`
2,749 of 3,100, `missile` 808 of 800 (1% over, under the 10% that needs
a request: the four helpers `wfire` shares are routines), `chasemove`
2,277 of 2,900; earlier waves' parts unchanged. The core `$6600-$99F1`,
13,298 of 13,312 B; the driver's area 3,186 of 3,584 B (the parts'
`*test.s` only in their own images). The scratch blocks unchanged (1,014
of 1,024 B): `attack` 27 of its 32 B, `player` 30 (byte 0 freed by
`G_ONGROUND`), `xymove` 26, `chasemove` 27.

**Not done in this integration** (open items):

- No part's checkpoint was rerun on the integrated images (the lean
  rule); their test modules ran, each with a sample of its cases. The
  earlier parts' cases that reach a wave-5 routine through a dispatch
  table (`TRVTAB`'s traversers, `ITTAB`'s `PIT_AvoidDropoff`) and are
  now eligible were not surveyed (but part `path`'s 40 chosen calls,
  all run and equal); `player`'s `P_PlayerThink` calls that
  reach a `wfire` action (184 of 11,940) wait for wave 6.
- The placement model's blind spots: a callee's callee in the caller's
  slot (`pMove` to `checkPos`), the slide in the move's slot (the model's
  best), the puffs (group 8) in the traversers' slot (each puff or blood
  reloads the traverser's group); for the timing report (5.4). With more
  than 22 moves the search falls back to the local walk.
- `G_ONGROUND` is written by `tic_main_records`, which part `tic`'s
  runs call; the bridge does not carry it (R1 (c) refused).
- The parts' own open points (their records' section 4): the branches
  no sampled call reaches, the `$5A` fill, the sounds not compared in
  routine mode (R6), the paths only synthetic calls reach.

## Wave 6 as integrated (2026-10-02)

The integrator (3.8) merged wave 6's four parts (`movers`, `wfire`, `tic`,
`chase`), on a2vm against `ref816`. Nothing is committed. The merge was
**lean**, as the owner asked on 2026-10-02:

- the requests applied;
- every image rebuilt with `make -B`, with no warnings;
- the wave's four test modules and the suite run, the suite once more
  after the fixes it called for (below).

No part's checkpoint, planted bugs, demo, tic stream or timing run was
repeated: the final integration does what is needed. No earlier attempt
of this merge had left changes in the tree.

`src/native/game/integrated.txt` is now 6, so every part of the table is
built. The shared outputs count `THTAB`'s `P_MobjThinker`, `T_PlatRaise`
and `T_VerticalDoor` as built, and `ACTTAB`'s weapon and monster actions.
Every image links the twenty-nine parts.

Section 5 of each part's record says whether each request was accepted
or refused, and why. The shared changes:

| File | Change (requests) |
| --- | --- |
| `tools/native/glayout.py` | `INLINED` for `movers` (request 1), `wfire` (R1) and `tic` (R1). `OWN_STACK`: `T_VerticalDoor` 2, `T_PlatRaise` 2 (movers 3), `P_MobjThinker` 2 (tic R3), `A_Chase` 1 (chase R3) |
| `tools/native/gplace.py` | **New** `GROUP_MARGIN` (64 B) and `CORE_MARGIN` (16 B), found by the suite (below). `AFFINITY` gains five units: the movers' (request 2); the weapons' (wfire R2), plus `A_FireMissile` in missile's unit; the attacks' (chase R2); and the walk with `P_MobjThinker` (tic R4), widened by the integrator with the thinkers the walk reaches every tic (`T_Glow`, `T_LightFlash`, `T_StrobeFlash`, `T_Scroll`, `P_MobjBrainlessThinker`). `APART` gains movers' pair (`T_VerticalDoor`, `T_MovePlaneCeiling`) |
| `tools/native/gparts/mobjstate.py` | The shared stray rule allows `TEXTRANS` and `NUKAGE` (written by `P_UpdateSpecials` every tic) and the driver's descriptor, whoever writes it (tic R2). `tic.py`'s stand-in is removed |
| `src/native/gdriver.s` | **Found by this integration** (see below): `core_in` sets every `SLOT_GRP` to `$FF` |
| `src/native/game/spawn/part.mk`, `tools/native/gparts/spawn.py` | **Found by the suite**: `sptest.s` is linked only with `SP_TEST=1`, which `spawn.py`'s build passes |
| `tools/native/gparts/mobjstate.py`, `tests/test_native_game_mobjstate.py` | **Found by the suite**: the rocket cheat's cases run whole once `A_CyberAttack` is built; the stop check asserts what holds when every action is built |
| `src/native/game/README.md` | "The parts' interfaces": wave 6's rows (wfire R3, tic R6 (b), chase R4, movers 1.2) |
| `src/native/lsetup.s` | The comment on `P_MapEnd`'s tmthing (tic R6 (c)) |
| this file | 2.4's rows `movers` (request 4) and `tic` (R6 (a)); 4.3's slot 2 row (movers request 4) |
| `src/native/game/chase/chase.s` | `bd_floors`' comment: the stand-in is accepted (chase R1 (b)) |

**Refused or deferred.**

- chase R1 (a): an `EV_DoFloorTag` entry in `evfloor` and a
  `P_FindSectorFromTag` entry in `secfind`. It would change two verified
  parts whose checkpoints a lean merge does not rerun. The stand-in (b)
  is accepted: 130 B of cold code, checked by the last-baron case. The
  final integration may still choose (a).
- tic R5 (the lockstep runner's wiring in `ticrun.py` and `ticcap.py`) is
  deferred to the final integration. Only the tic-level runs check it,
  and this merge makes none.
- wfire R2's optional `APART` pair (the weapons and `P_LineAttack`) was
  not needed: the slot search put them in opposite slots (groups 20 and
  18).

**The integrator's addition to tic R4.** The walk calls each special's
thinker by upstream's `callFn` (`jml`), which the survey does not see, as
it does not see `TRVTAB`'s traversers. In the measured placement the
lights (`T_Glow`, `T_LightFlash`) and `T_Scroll` were in other groups of
the walk's slot. Each of them, every tic, would have loaded its own group
and then the walk's again (about 1 ms a light thinker by 4.3's cost
model). An `APART` rule (the walk against every `THTAB` thinker) was
tried first. It cannot hold with movers' pair, since `T_MoveFloor` is in
the planes' unit, and without that pair it raised the model's cost to
9.4 ms a tic, because a light had been packed with `P_PlayerThink`. The
light thinkers (418 B) therefore joined the walk's unit (1,019 B, with
`P_MobjBrainlessThinker`).

A second pair was tried and dropped: `P_MobjThinker` against
`P_SetMobjState`. Upstream's state change at a state's end is inline, so
the survey does not count those calls. The pair raised the model's cost
from 0.50 to 3.53 ms a tic (before the margins below), about what it
would save.

**Found by this integration: the slots after a load.** After the wave was
built, part `tic`'s load case `load: doWorldDone` (tour h151) failed.
The run hit its cycle limit at `$4C4E`, with stray writes from `$A98F`
in slot 2. What happened:

1. `G_Ticker` returned `GT_LOAD`.
2. The driver loaded the level. The load image's code writes the slots.
3. `core_in` put the tic image back, but `SLOT_GRP` still named
   `G_Ticker`'s group (then 26) in slot 2.
4. `g_tresume`'s `fc_call` to `gt_loop` therefore loaded nothing and ran
   the load image's bytes.

In the part's own image, under wave 5's placement, a callee of
`g_resume` happened to page slot 2 first, which hid the fault. The fix is
in `gdriver.s`: `core_in` (after a load, after a frame, at the start)
marks every slot as holding no group, as milestone 11's kernel does at
its tic (`dl_kern.s`). The release image links `gdriver.s`, so it has
the fix too. After it the case passes.

**Found by the suite.** The first run of the suite, on the tight
placement, had 2 failures and 14 errors in five modules. All of them came
from the wave being built, not from its parts' code:

- **`damage`.** With every part linked, the card's driver area (`LCE`)
  had no room left for `dtest.s`: 24 B over. The cause was `gtick.s`'s
  17 B plus `gdriver.s`'s 11 B. Fix: `sptest.s` (112 B) is linked only in
  spawn's own image (`SP_TEST=1`, which `spawn.py`'s build passes), as
  the later parts' test routines already are.
- **`sight`, `spawn`, `secfind`.** Their planted bugs no longer linked:
  the margins above.
- **`mobjstate`.** Two failures:
  - The rocket cheat's synthetic calls expected a stop at the unbuilt
    `A_CyberAttack`, which part chase now builds. They are now the
    reference's own call compared whole, as wave 3 did for the cheat's
    other built actions.
  - `test_the_stop_check` asserted a stop at an unbuilt action, and none
    is left. It now asserts a stop while any `ACTTAB` action is unbuilt,
    and otherwise that no call stopped and that the cheat's calls ran.
    The skeleton's `unbuilt` self-check (`gselftest.py`) still covers the
    stop itself.

**The selection.** With the wave built, more calls became eligible:

- `tic`'s `G_Ticker`, `P_Ticker` and `P_RunThinkers` calls that reach the
  movers', weapons' and chase's routines;
- `player`'s and `pspr`'s calls that reach a weapon action (wfire R4).

`tic.py --capture` ran once more for its new selection (20 s): before
it, its checkpoint tests skipped because the selected cases were not
captured. The other parts' selections were not captured again.

**The placement.** The wave-5 placement no longer fitted the wave image,
so the placement was made again:

1. **The first pass.** The sizes came from wave 5's measured image (the
   core's fixed part, 9,945 B), with each wave-6 part's own image for its
   routines.
2. **Measured again.** `gplace.py --measure` on the linked wave image
   gave a placement that did not link (group 4 over by 13 B). An `FCALL`
   is 3 B when its target is in the caller's group or the core, and 6 B
   otherwise, so a routine measured in one placement can grow in the
   next.
3. **Monotone sizes.** From then on, each routine's size is the largest
   measured so far (`build/native/game/shared/sizes-wave6.json`), with
   the core's fixed part 9,945 B. The placement made from these sizes
   links, and measuring its image grows no routine: a fixed point. It
   gave 27 groups packed to 2,048 B, the core 3,362 of 3,367 B, and a
   model cost of 0.50 ms a tic.
4. **The margins, found by the suite.** That tight placement broke four
   parts' planted bugs, whose copies link in the same placement. Each
   plant adds a few bytes, and no group or core had them to spare:
   - sight's three plants: +3 B past the core;
   - spawn's `puff-z-random-after-tics`: +47 B in its group;
   - spawn's `squat-shift`: +2 B;
   - secfind's `nukage-signed-shift`: +2 B.

   Wave 5's placement had passed by luck: `P_MapEnd` was unbuilt, and its
   groups had a few bytes free. `gplace.py` now packs each group to its
   slot less `GROUP_MARGIN` (64 B), and the core to its room less
   `CORE_MARGIN` (16 B). An affinity unit larger than that (`P_XYMovement`
   with `P_TryMove` and `slideMove`, 2,046 B) is a group of its own, and a
   group's legality is still its slot's full size. The monotone sizes,
   placed again, reached a fixed point in two passes (`G_Ticker` and
   `P_Ticker` grew by 3 B each in the first).

The result:

- 28 groups, each at most 1,984 B, but the 2,046 B unit;
- the core 3,350 of 3,351 B (16 B of margin) for 9 routines: sight's
  six, `tryWalk`, `wInfo`, `wInfoOf`. `ST_Ticker` and `P_MapEnd` left
  it;
- the model's same-slot cost 1.57 ms a tic at the mean (0.50 without the
  margins; 1.58 at wave 5);
- `A_Chase`'s rule and `APART` kept;
- no pair of groups in one slot with more than one call a tic at the
  median.

The margins cost about 1.1 ms a tic by the model. The performance pass
(milestone 8's open item 2) may place the release build without them:
its image links no plant.

Wave 6's units:

| Unit | Group | Slot | Note |
| --- | ---: | ---: | --- |
| The walk, `P_MobjThinker` and the light thinkers | 21 | 1 | 1,458 B |
| The movers | 9 | 1 | |
| The planes | 26 | 2 | |
| The weapons | 20 | 2 | |
| Attack's entries | 18 | 1 | with `A_Explode` |
| `A_FireMissile`, `P_SpawnPlayerMissile` | 14 | 1 | with `P_SpawnMissile` |
| The attacks | 5 | 2 | |
| `A_Chase` | 10 | 2 | with `P_Ticker`, `P_MovePsprites` |
| `pMove`, `newChaseDir` | 13 | 1 | |
| `G_Ticker`, `P_MapEnd` | 24 | 1 | |
| `A_BossDeath` | 6 | 1 | |

**Checks.**

- `gcallgraph.py --check --built` (all 29 parts): 0 failures (935 heads,
  589 reachable from the tic).
- `--stack`: 64 + 24 IRQ = 88 of 160 B.
- `glayout.py --check`: ok.
- Every image rebuilt with `make -B`, one at a time, with no warnings:
  `shared`, `skel`, `wave W=6`, `game`, `gprof`, `release`, and all 29
  parts' `part P=`, each with its own test flag (`MS_TEST`, `DM_TEST`,
  `SP_TEST`, `PS_TEST`, `PT_TEST`, `TP_TEST`, `AK_TEST`, `PL_TEST`,
  `XY_TEST`, `CM_TEST`, `MV_TEST`).
- The wave's test modules (`python3 tools/testpar.py
  test_native_game_movers test_native_game_wfire test_native_game_tic
  test_native_game_chase`, default mode), on the integrated images, 32 s.
  All are OK, and every skip is a `DOOM_GS_FULL` one:

| Module | Tests | Skipped |
| --- | ---: | ---: |
| `movers` | 10 | 1 |
| `wfire` | 9 | 2 |
| `tic` | 8 | 1 |
| `chase` | 7 | 0 |

**The test suite**: two runs of `python3 tools/testpar.py`:

| Run | Tree | Modules | Tests | Failures | Errors | Skipped | Wall time |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| First | tight placement | 118 | 2,021 | 2 | 14 | 26 | 3,028 s |
| Second (`--timeout 3600`) | after the fixes above | 118 | 2,031 | 0 | 0 | 26 | 2,916 s |

The first run's failures were in five modules: `damage`, `mobjstate`,
`secfind`, `sight` and `spawn` (see "Found by the suite" above). In
both runs every skip is a `DOOM_GS_FULL` one: wave 5's 22, plus
`movers` 1, `wfire` 2 and `tic` 1. `test_native_game_geom` alone takes
2,915 s and sets the wall time.

**Sizes** (the wave image's map):

| Part | Bytes | Budget | Note |
| --- | ---: | ---: | --- |
| `movers` | 1,234 | 1,400 | |
| `wfire` | 1,338 | 1,300 | 2.9% over, under the 10% that needs a request |
| `tic` | 1,011 | 1,500 | `g_ttick` and `g_tresume` are in the driver's area |
| `chase` | 1,813 | 1,800 | 0.7% over, with the accepted 130 B stand-in |

Earlier waves' parts are unchanged. The core is 13,295 of 13,312 B
(9,945 B fixed plus 3,350 B of table routines). The driver's area is
3,102 of 3,584 B: `gdriver.s` + 11 B, `gtick.s` + 17 B, and `sptest.s`
(112 B) now only in spawn's own image.

**Not done in this integration** (open items):

- No part's checkpoint was rerun on the integrated images (the lean
  rule). Their test modules ran, each with a sample of its cases. Newly
  eligible cases were not surveyed, apart from `tic`'s new selection:
  the earlier parts' cases that reach a wave-6 routine through
  `ACTTAB` or `THTAB`, and `player`'s and `pspr`'s fire calls.
- tic R5 (`ticrun.py`'s wiring, `setup_rekey` in `ticcap.py`) and the
  tic-level acceptance runs: the final integration.
- The placement model still has blind spots, for the timing report
  (5.4):
  - `P_MobjThinker`'s calls of `P_SetMobjState` at a state's end
    (groups 21 and 19, both in slot 1);
  - `P_SetMobjState`'s actions through `ACTTAB`;
  - a callee's callee in the caller's slot;
  - the door's three loads a moving tic.
- The parts' own open points (section 4 of their records):
  - the branches that no sampled call reaches;
  - the `$5A` fill and `fastpath`;
  - the sounds not compared in routine mode (R6);
  - the paths that only synthetic calls reach;
  - `A_Explode` of a rocket at its spawn;
  - the light tag of a door (synthetic only).

## Acceptance (2026-10-02)

The final integration of section 5, on a2vm against `ref816`, with the
owner's lean rules of 2026-10-02: each acceptance run once, from one
poisoned machine (`$A5`), one planted bug a run to show it can fail, 3
generated streams instead of 10, 200 long traces instead of 500, a2vm
timing by subsystem. Nothing is committed. Wave 6's integration (the
first step of section 5) is "Wave 6 as integrated" above. The report is
`build/native/game/report.md` (`python3 tools/native/ticrun.py
--report-md`), made from the runs' JSON in `build/native/game/acceptance/`.

### Results

| # | Run | Tics compared | Failures | Same-pair hits (ref / native) | Setups | Planted bug (caught) |
| --: | --- | ---: | ---: | --- | ---: | --- |
| 1 | demo3, lockstep, `FRONT` frames, to the demo's end | 2,134 | 0 | 1,009 / 1,009 | 1 | tic's `leveltime-first` (yes) |
| 2 | newgame (the ring of commands, the menu's new game) | 512 | 0 | 53 / 53 | 1 | |
| 2 | tour (the ring, `iddqd`, 8 `idclev`, the poke, 8 intermissions) | 427 | 0 | 0 / 0 | 9 | flow's `m-random-not-called` (yes) |
| 3 | DEMO1 (E1M5, 7 reborn loads) | 5,026 | 0 | 3,956 / 3,956 | 8 | |
| 3 | DEMO2 (E1M3) | 3,836 | 0 | 80 / 80 | 3 | flow's `angleturn-not-shifted` (yes) |
| 4 | G1 (E1M1, UV, seed 1: zone mobjs, up to 4 at a tic) | 2,000 | 0 | 1,786 / 1,786 | 1 | mobjstate's `removal-at-once` (yes) |
| 4 | G3 (E1M2, nightmare, seed 1: 4 deaths and reborns, zone mobjs) | 2,000 | 0 | 882 / 882 | 5 | |
| 4 | G5 (E1M4, medium, seed 1: doors, lifts, 133 pickups) | 2,000 | 0 | 145 / 145 | 1 | |
| 5 | demo3, lockstep, `FULL` frames: every tic, and every 10th frame's records and view | 2,134; 54 of 54 frames, 31,439 records | 0 | 1,009 / 1,009 | 1 | the driver's view top ignored (yes: 8 frames) |
| 6 | `P_PathTraverse` by `--call`: 203 traces of more than 64 intercepts (29 on each of E1M2, E1M3, E1M5-E1M9, from 18,056 candidates), never stopping and stopping at k = 1, 8, 32, 64, 65 | 1,218 runs | 0 | | | path's `c-overflow` (26 of 29 runs fail) |

Every compared tic is equal in every canonical kind, under T1 in the
`FRONT` runs (`line.r_flags`) and nothing else: no T3 window (no run
has one: `ticcap.py` found no window in any run, and no
`validcount` wrap), no T8 tic (no division by zero), no T7 frame (no
frame with `RULES` set). In the `FULL` run `line.r_flags` is compared
too, and equal at every tic. The same-pair hits are compared a tic,
the run's last tic left out (the reference's run can end inside it).
The generated streams move, run, strafe, turn, fire, use and change
weapons by the policy of 3.7; G3 dies and is reborn four times.

**The gates of milestone 9** (`LEVELS.md` "Verification of stage C",
closed here):

| Gate | Evidence |
| --- | --- |
| One `validcount` | every tic's `validcount` and every line and sector stamp equal in every run, the native front end raising the joined count (`gv_inc`) at each of the reference's frames |
| A zone mobj created, `LS_ZONE`, no slot twice | G1 and G3 make zone mobjs (4 and 3 at most at a tic) and compare them every tic; the port reader refuses two objects in one slot; the highest mobj slot of any run 449 (the tour), of the planes' 768 |
| The block walk's order on every move | 3,539 compared tics in which the reference changed the sector nodes and 6,673 in which it changed the block lists, each compared as a sequence |
| Bank `$21`'s tables (S4) | `ticcap.py --tables`: 57 setup dumps, 0 failures |

### What the final integration built and changed

| File | Change, and why |
| --- | --- |
| `tools/native/ticrun.py` | **The lockstep runner** (tic R5, deferred at wave 6): the start state at the G_Ticker entry of the run's first setup's tic (a capture), the driver's entries, the demo bank, the tic globals, every setup's re-key record, the I_GetTime values, the stream, the schedule; each tic's snapshot digested in worker processes and compared; `--diff-at`, `--plant`, `--timing`, `--report-md` |
| `src/native/gdriver.s` | **Corrected, found by the runs**: (1) the lockstep loop never raised gametic after a tic (upstream's `runTic`, `d_main65.s:248-251`; the skeleton's stub ticker raised it itself, `game/gtest.s` no longer does); (2) after a frame the object API's tags (main `$1980`, the renderer's `DSX1`/`DSX2`) were taken as valid: `go_reset` now follows `core_in`, as milestone 11's `K_TIC` does. **New, `TICLEVEL`** (the lockstep builds `game` and `gprof` only, so the parts' images keep their room in the driver's area): the stream of the runs on the ring (each tic's command into `G_CMDS`, the cheats through `C_Responder`, pokes, the menu's state and new game); the frames through milestone 8's entries (`far_wload`, `nr_frame`; for `FULL` `far_mload`, `nm_masked`, `nm_bkload`, `nb_frame`; snapshot points `drv_fmend`, `drv_fend`); the frame block's level fields after each load (`GT_LEVELS`, from the store's map headers as milestone 11's `s_level`); and the display's three game-visible writes, which milestone 11 builds: the view's top (`VIEWTOP` 9 under the message strip, `d_main65.s:470-474`, from the reference's frame), the fill spans' `W_FSW`/`W_FSG` (`d_main65.s:377-381`, `:521-523`; a wipe after each load), `snl_pointeron` in the intermission's NoState (`wi_stuff65.s:589-591`); `dg_nosnap` (no snapshot a tic, the timing's); `GPROF` phase marks |
| `tools/native/glayout.py` | `GTEST`: the schedule `$1000` B (1,365 frames), the re-key records `$2C00` B (10 setups: `$1800` held 5, the tour has 9), `GT_LEVELS`; `FRAME_KIND`, `FRAME_STRIP`, `VIEW_STRIPTOP` |
| `src/native/game.mk` | `TICLEVEL` in `game` and `gprof` |
| `src/native/game/tracel/part.mk`, `tools/native/gparts/tracel.py` | `tracelt.s` linked only with `TL_TEST=1` (the game image's driver area was 38 B short; `tracel.md` 6) |
| `src/native/gcall.s` | `GPROF` only: a group load marks the paging's phase (its copy is `far_get`'s). The `GPROF` marks of both files sit inside `TESTBUILD` blocks, a test build's harness for `s2layout.py`'s phase check (phases 30 and 31 are milestone 11's 2D and platform phases in its builds; here only the `gprof` lockstep runs see them): found by the suite's `test_play_runs` |
| `tools/bridge/identity.py` | **Corrected, found by G1**: the sector nodes' identities followed the zone mobjs' present identities (the port reader's slots), not their identity order (the thinker list's), so two zone mobjs' nodes swapped; `tests/test_bridge_identity_zone.py` |
| `tools/native/gcanon.py` | A kind the state lacks digests as an empty table (`canonical.diff`'s rule): a door made and removed left the port reader's table empty where the reference's had none |
| `tools/native/ticcap.py` | Each tic's `FRONT` digest (T1); `G_Ticker`'s command ring and the poked places at every entry, whatever the game state (the tour's intermission commands; the poke at its true tic, 456, where 535 was the first level tic that saw it); each frame's view (`viewtop`, `viewbottom`, `automapmode`); the stream of every tic from the start |
| `tools/native/gamecap.py` | A generated stream `GN` runs by name (its lump placed as DEMO3) |
| `tools/a2vm/main.c`, `cost.c`, `cost.h` | `--cost-pcmap FILE`, `--cost-pcmap-when N`: while the phase written is N, each instruction's phase is its PC's in the map (a fixed range, or a slot's range under the group number main holds); the model still only observes |
| `tools/native/gparts/path.py` | `--acceptance-final`, `--run-final` (`path.md` 6) |
| `tools/native/gparts/flowcheck.py` | The plant `m-random-not-called` moved to the new text of `gwi.s`, which milestone 11's assembly changed (its requests R4, R5; `flow.md` 7) |
| `tools/native/gsizes.py` | Each part's bytes against its budget, the core, the slots, `GCODE0-1`, the banks |
| `tests/test_native_game_lockstep.py` | newgame whole, demo3's first 100 tics `FRONT` and 60 `FULL` (all with `DOOM_GS_FULL=1`), the planted bug, the timing by subsystem |
| `tools/testpar.py`, `tests/README.md` | `test_native_game_lockstep` among the writers of the steps `ref816 machine`, `ref816 image` and `game.mk` (found by the suite's `test_testpar` guard) |

**Injected state, each with its reason** (as `RENDER-MASKED.md` 0.3
row 3): the renderer's boot state (milestone 11's `s_rinit`) and, in the
`FULL` run, its persistent state from milestone 8's first capture
(`demo3-000`'s P0: spans, weapon skip, fuzz position, plane colours),
`SPRBOUND` from the second capture (upstream computes it during the
level set's first frame: the first P0 holds zeros, which rejected
sprites at the view's edges); each frame's view top from the
reference (the display's, milestone 11's); the setups' re-key records
(3.6). No game state is injected after the start.

### Timing (section 5.4, a2vm's cost model; not the card)

The `gprof` build under `f121` and `fastpath`, `FRONT` frames, no
snapshot a tic; each instruction's phase from the build's PC map (the
innermost routine by construction; the group copies marked by
`gcall.s`). ms a level tic, median / p99 / worst (the report has every
run):

| Run, profile | Tic | Paging (28) | Object API (29) | Moves | Sight | Traces | Walk | Monsters | Math | The rest |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| demo3, `f121` | 233.8 / 604.1 / 1,089.2 | 208.7 / 549.9 / 1,014.8 | 21.3 / 45.0 / 72.0 | 1.57 / 3.90 / 6.08 | 0.21 / 4.14 / 10.29 | 0.00 / 3.87 / 9.20 | 0.68 / 1.01 / 1.25 | 0.30 / 0.64 / 0.80 | 0.58 / 4.02 / 6.87 | under 0.3 |
| demo3, `fastpath` | 176.5 | 158.1 | 14.5 | 1.54 | 0.21 | 0 | 0.68 | 0.30 | 0.56 | |
| DEMO1, `f121` | 119.9 / 359.9 / 956.3 | 105.9 | 11.3 | 0.58 | 0.25 | 0 | 0.48 | 0.18 | 0.29 | |
| DEMO2, `f121` | 110.3 / 273.3 / 917.2 | 95.7 | 10.0 | 0.35 | 0.31 | 0 | 0.56 | 0.12 | 0.32 | |

**The game code is about as estimated; the runtime is not.** The parts'
own code takes 3-4 ms a tic in demo3 (`NATIVE.md` 6 estimated 4.6-10.3
ms a tic, 18.4-41.3 at 4 a frame). The paging takes 89% of the tic:
**300 group loads a tic** in demo3 (each 1-2 KB copied through
`far_get`), where 4.3's model counted 1.57 ms of same-slot calls. Its
blind spots, named at wave 6, are where it goes (loads a tic, both
ways, over the whole demo): slot 1's groups 21 (the walk,
`P_MobjThinker`) and 19 (`P_SetMobjState`, the position routines
`unlist`, `link`, `mvBlock`) 61; slot 2's 1 (`P_XYMovement`,
`P_TryMove`) and 11 (the slide, `sectorFloor`, `pointSector`) 47; slot
1's 13 (`pMove`, `newChaseDir`) and 3 (`P_CheckPosition`) 41, 13 and 19
34; slot 2's 10 (`A_Chase`, the psprites) and 1 24
(`build/native/game/acceptance/paging.json`). The object API's far
fetches are the rest (21 ms a tic: 317 misses and 307 write-backs in a
demo3 tic).

**FPS** (`RENDER-MASKED.md` 6.2's new [M] rows): demo3's 532 frames,
each its measured tic phase (its 4 tics, the tic image's exit and
entry, 11.8 ms) plus milestone 8's measured render: median 1,065 ms
(0.94 FPS), worst 2,191 ms (0.46 FPS, `demo3-474`) on `f121`; 815 ms
(1.23 FPS) and 1,674 ms (0.60 FPS) on `fastpath`; every frame under 6
FPS; the tics a faster frame would run do not change this (every frame
takes more than 86 ms, so 4 tics). Without the group loads the frame
would take 192 ms (5.2 FPS) at the median on `f121`, 155 ms (6.5 FPS) on
`fastpath`. **The performance pass** (milestone 8's open item 2, before
milestone 12) now has its first target: the placement of the tic's code
(section 4.3) from measured native transitions, not upstream's call
counts; then the object API's misses.

**Not measured (lean)**: the bank-2 option (`TIC_LC2`, 4.2): it would
add 4 KB of resident tic code, which the measured paging shows is worth
more than its 1 ms a frame.

### Sizes (5.5)

The parts' code 51,543 B against 57,300 B of budgets; over budget:
`pspr` 2,485 of 1,200 B (its flood's 1,024 B work stack is in its
group), `flow` 2,980 of 2,300, `mobjstate` 2,165 of 1,900, `look`,
`damage`, `missile`, `wfire`, `chase` within 6%. The core 13,295 of
13,312 B; 28 groups of 1,085-2,046 B in two slots of 2,048; `GCODE0`
full (94 pages of groups), `GCODE1` 107 of 190 pages; the driver's area
2,931 of 3,584 B in `game`; banks 114 of 126 in test builds (spare 1-5,
93-97, 125, 126), as wave 6. `make -f game.mk sizes`, `python3
tools/native/gsizes.py`.

### The test suite

`python3 tools/testpar.py --jobs 3` once after the runs (3,288 s): 122
modules, 2,052 tests, 1 failure, 0 errors, 26 skips (every one a
`DOOM_GS_FULL` one). The failure was `test_testpar`'s guard: the new
`test_native_game_lockstep` writes the shared builds and was not among
the race table's writers; it is now, and `test_testpar` passes alone. A
first run, stopped, had found `test_play_runs` failing: `s2layout.py`'s
phase check (the `GPROF` marks' phases 30 and 31 are milestone 11's), now
inside `TESTBUILD` blocks, and `test_play_runs` passed alone before the
full run.

### Commands

    make -s -C src/native -f game.mk game gprof ROOT=$PWD
    python3 tools/native/ticcap.py --runs demo3,demo1,demo2,newgame,tour,G1,G3,G5 --jobs 3
    python3 tools/native/ticgen.py --stream G3 --seed 1      # and G5
    python3 tools/native/ticrun.py --run demo3 --frames front --jobs 2 --json build/native/game/acceptance/A1-demo3-front.json
    python3 tools/native/ticrun.py --run demo3 --frames full ...   # acceptance 5
    python3 tools/native/ticrun.py --plant all
    python3 tools/native/gparts/path.py --acceptance-final --traces 200 --jobs 3
    python3 tools/native/gparts/path.py --run-final --jobs 3
    python3 tools/native/ticcap.py --tables
    python3 tools/native/ticrun.py --run demo3 --timing f121   # and fastpath, each run
    python3 tools/native/ticrun.py --report-md

### Left out by the lean rules, and open points

- Left out: the `$5A` fill; the tour by map in 9 runs; G2, G4, G6-G10;
  the sound events per tic against `ref816`'s call log; more than one
  planted bug a run; the bank-2 measurement. The automatic bisection of
  3.6 is still not built (the skeleton's deviation 13): each first
  differing tic was found by `ticrun.py --diff-at` (both states whole,
  the canonical diff) and its cause by hand; every cause was in the
  harness or the bridge (above), none in a part's game code.
- For the owner: (1) **the frame rate**: under 1 FPS in demo3 on
  `f121` as built, 89% of it the tic image's group loads: the
  performance pass before milestone 12 (above). (2) The T3 zone window:
  no run opened one. (3) The 768-slot cap: the highest slot of any run
  449. (4) The same-pair hits: equal in every run. (5) The bank-2
  option: not measured.
- `build/` grew 0.10 GB in this integration (6,499,540 to 6,604,712 KB,
  every temporary directory deleted; most of it acceptance 6's 1,218
  cases, 109 MB); the milestone in all 2.92 GB of the 8 GB allowed (from
  the skeleton's 3,683,828 KB; other work in the same `build/` counted
  too).

## Appendix A: the measurements made for this design

All read-only, 2026-10-01, standard-library Python and `ref816` through
`tools/ref816/calls.py`, at normal priority, each run with a CPU-time and
a file-size limit (`ulimit -t`, `-f`); the scripts and logs lived in the
session's scratch directory and were deleted; **0 bytes were added to
`build/`**. Disk free before: 68 GB, then 82 GB (`df -h
/System/Volumes/Data`).

**CG, the call graph.** The game units of `build/upstream/src/iigs/` read
with the release's conditionals (`TICSTEP` 1, `MAXTICS` 4, no
`IIGS_PHASES`), local labels and comments stripped; heads and edges as
2.1 defines them; each head's bytes from `build/linkmap.json`'s `text`
fragments (a label's extent to the next label of its fragment, summed by
head). 742 heads (634 with code in the game units), 4 strongly connected
groups of direct calls; the part table of 2.4 checked against the rule
of 2.2, with `findSpecial`'s handlers counted as `LSTAB`'s entries (its
`jsr (spectab+2,x)` [R `p_switch65.s:452-455`]). Under a minute.

**HEAT.** `build/a2vm/interp/still.trace` and `demo.trace` (the
`PROFILE.md` traces: 24 frames standing still in E1M1, 40 frames of
demo3 from its note `demo` [R `tools/ref816/README.md` "Traces and
profiles"]) read with `tools/ref816/tracefile.py`; each executed address
given to the head that owns it inside its link-map fragment; game-unit
instructions 12,167 a frame still, 96,562 in the demo (the module table's
96,442 [R `research/native-modules.md` 3.6]); the hot sets of 0.3 fact 7
and 4.2 by head size. Under a minute.

**CALLS.** `calls.py DEMO3`, `DEMO1`, `DEMO2` (the title loop to each
demo's end, DEMO1 and DEMO2 placed as DEMO3 [R `tools/ref816/lumps.py`])
with entry-only call logs of `G_Ticker` (with `_g_gametic`),
`R_RenderPlayerView` (with `_g_gametic`) and 20 game routines; counts a
tic between two `G_Ticker` entries, over the tics with game activity:

| Routine, a tic | demo3 mean (median, p99, most) | DEMO1 | DEMO2 |
| --- | --- | --- | --- |
| `P_TryMove` | 12.0 (11, 32, 51) | 4.3 (4, 15, 23) | 2.3 (2, 11, 20) |
| `P_CheckSight` | 4.8 (5, 11, 17) | 6.3 (6, 14, 20) | 5.8 (7, 10, 13) |
| `P_PathTraverse` | 0.50 (0, 8, 13) | 1.07 (0, 6, 13) | 1.46 (0, 6, 11) |
| `P_XYMovement` | 1.52 (1, 4, 5) | 1.44 (1, 4, 5) | 1.05 (1, 3, 4) |
| `P_ZMovement` | 1.45 (0, 9, 10) | 1.17 (1, 8, 9) | 0.43 (0, 7, 11) |
| `P_CreateSecNodeList` | 1.12 (1, 7, 268 at the setup) | 0.80 | 0.47 |
| `P_DamageMobj` | 0.06 (0, 2, 7) | 0.04 | 0.01 |
| `P_LineAttack`, `P_AimLineAttack` | 0.10, 0.03 | 0.06, 0.06 | 0.03, 0.03 |
| `P_TouchSpecialThing` | 0.02 (36 in all) | 0.01 (33) | 0.07 (268) |
| `P_UseLines`, `P_CrossSpecialLine` | 10, 58 in all | 25, 40 | 21, 7 |
| `P_RadiusAttack` | 0 | 0 | 0 |
| Tics a 3D frame | 4 in all 533 frames | 4 in all 1,257 | 4 in all 959 |

Machine time of the demos 364.6 s, 653.7 s and 506.6 s; the three runs
together took under 2 minutes of wall time.

**VC.** The same three runs with `G_Ticker` logged with `validcount`,
`_g_gamestate` and `_g_demoplayback`, and `A_Chase`, `A_Look` (entry
only, `jumps=1`): over the demo's tics `validcount` 273 to 50,013 (demo3,
2,134 tics), 220 to 65,201 (DEMO1, 5,026), 318 to 38,853 (DEMO2, 3,836),
no wrap; a tic's increase at the median, p99 and most 23, 49, 85 (demo3),
13, 30, 223 (DEMO1), 10, 22, 318 (DEMO2); `A_Chase` 6.1, 1.8, 0.4 a tic,
`A_Look` 5.3, 8.4, 7.1.

**POOL.** `_g_thingPool`, `_g_thingPoolSize` and `validcount` read from
the 57 R dumps of milestone 9 (`build/native/levels/setups/*/r.ram.z`):
the pool base `$06:2590` (E1M1, E1M2, E1M9 and the demos' maps E1M3,
E1M5, E1M7 when loaded first), `$08:0010` (E1M3, E1M5 in the tour),
`$07:0010` (E1M4, E1M7 in the tour; E1M6's reload), `$09:0010` (E1M6,
E1M8 in the tour; E1M6's first load in `reborn-e1m6`). And the free
pool slots after setup, from the bridge's canonical state: E1M1 at UV
0, E1M2 3, E1M3 3, E1M9 0, E1M4 12, E1M5 3, E1M6 9, E1M7 7, E1M8 1; E1M1
at skill 0 26; demo3's E1M7 at skill 2 70.

**THK.** The bridge's canonical state of six R dumps: thinkers by
function at the end of setup, demo3 (E1M7, skill 2) 101 full, 90
brainless, 20 lights and scrollers; E1M6 at UV 202, 121, 12; E1M1 at UV
36, 40, 12; sector nodes 128 (E1M1) to 512 (E1M6).

## 7. Review

An adversarial review of this design (2026-10-01, read-only) gave 14
findings. Each was checked against the sources before it was applied;
"(review N)" marks the changes in the text.

| # | Finding | Checked against | Verdict |
| --: | --- | --- | --- |
| 1 | `fc_call` returns into a paged-out group when a core routine pages the caller's slot | 3.4's old text; `A_TroopAttack` → `checkMissile` → `P_TryMove` (core) → `P_DamageMobj` | Applied: the stub saves and restores the target slot's group whoever the caller is; 5 B a cross-image call (4.5); S5 nested cases and a planted bug |
| 2 | Milestone 9's core bypasses the write-back caches | `src/native/gspawn.s:172`, `:425`, `:490`, `:561`, `gthink.s`, `gpos.s`, `gspec.s`, `gvalid.s` call `g_get`/`g_put` | Applied: all of it moves onto the API in the skeleton (1.1, 3.1); S5's dirty-line spawn; S2's grep check |
| 3 | The load protocol drops the code after the load | `g_game65.s:655-669`, `:877-884`, `:1100-1108`, `:1265-1272`, `:1311` | Applied: `G_LOADACT` and one continuation an action (3.4); `flow`'s load-containing entries through the protocol; S5 per action |
| 4 | `CS_PREV` cannot be compared as handles across base moves and zone reuse | `p_sight65.s:138-150`; `tools/bridge/upstream.py:821-830` | Applied: `stale` in the bridge, re-keying at every setup in test builds (which also closes the base-move part of T3), `$FFFE` and `GT_ZPREV` at a zone free, same-pair hit logs compared every tic (1.8, 3.6). **Rejected in part**: the claim that 1.4's "the slot policy changes nothing canonical" is false. That sentence is about the specials, which neither `CS_PREV` nor the hint names |
| 5 | Nobody owns the `LR_USE` path of `P_CreateSecNodeList` | `p_map65.s:857-913`, `:1700-1726`; `gpos.s` has no `LR_*`; `llayout.py:429` | Applied: the skeleton adds the path to `gp_secnodes` and places `LR_*`, which are compared from now on (fact 4, 1.5, 1.11); S2 on both branches |
| 6 | Routine mode cannot see results returned in scratch | `tools/bridge/schema.py:425-430`; R2 | Applied: declared inputs and outputs in `args.json`, near and direct-page symbols included, compared exactly (2.4, 3.5) |
| 7 | Uncovered tic inputs: `starttime`, the HUD flags, menu-issued actions, `automapmode` | `g_game65.s:1270-1272`; `hu_stuff65.s:249-251`; `m_menu65.s:922`, `:1000` | Applied for `I_GetTime` (a hook fed by the stream), `showMessages` and `_g_message_dontfuckwithme` (globals, external globals of the bridge), `G_DeferedInitNew` from the menu (stream events). **Rejected for `automapmode`**: it is not in the bridge's schema and the automap is outside the canonical model (T6), so no compared field depends on it; `initNew`'s clear of `AM_ACTIVE` is milestone 11's, with the rest of the automap's state |
| 8 | `activeplats` does not exist upstream | `p_plats65.s:3-6`; `schema.py` `PLAT.LIST` | Applied: removed (1.4, 1.5, `evworld`'s planted bug replaced, risk 5) |
| 9 | Unowned routines, shared helper names | `g_game65.s:581`, `:630`; `p_map65.s:1126`, `:1251-1340`, `:2060`, `:3296`; `r_list65.s:919-943`; `w_level65.s:621-624`; a grep of `^label:` | Applied: owners named (`flow`, `checkpos`, `geom`, `tic`, `mobjstate`, the skeleton), hooks added, routines keyed by `file:label`, the graph followed into other units (0.1, 2.2, 2.4). **Rejected for `P_SetSeclist`**: no unit calls it (its two uses are inline), so it is out, not unowned |
| 10 | Comparison rules some runs cannot pass (T3's wrap guard, T8) | 0.3 fact 10; 3.6 | Applied: seeds rejected when a wrap falls in a T3 window or a run divides by zero; T3 narrowed to the zone window by the re-keying; T8 ends the comparison at the tic and continues from the reference's state |
| 11 | Memory and bank figures | 4.1's W row (1,024 of 1,024); `MEMORY_MAP.md:177`; 1.10's tally; 4.3's slot 1 | Applied: W re-planned (the core gives 512 B), the `MEMORY_MAP.md` rule amended, 116/113 banks, `A_Chase` and its callees never in one slot |
| 12 | Parallel builders race on shared outputs | 2.5, 3.2, 3.5 | Applied: the skeleton and the integrator make them, parts only read them, each part has its own `OUT`/`GEN` |
| 13 | The arithmetic rule is unworkable as worded | the helpers' files (a grep of `^label:`) | Applied: the rule reworded and every helper listed with a random `--call` check (2.4, risk 6) |
| 14 | `flow`'s `M_Random` bug uncatchable; "fast monsters"; E1M8's special 11 | `st_stuff65.s:432`; `initNew` [R `g_game65.s:1111-1142`] has no fast flag; `p_user65.s:767-775` | Applied: `st_tick` and `hu_tick` are `flow` entries; G3 corrected; special 11 in `player`'s synthetic cases |
