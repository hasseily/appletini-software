# Part `flow` (wave 1)

The record of milestone 10's part `flow` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 1; upstream 1800 B, native budget 2300 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 1's `flow` (2026-10-01). Built: `src/native/game/flow/gflow.s` (g_game65.s's routines, `g_resume`, and the test-only harness entries under `TESTBUILD`), `gwi.s` (wi_stuff65.s, `st_tick`, `hu_tick`), `part.mk`, `args.json`; `tools/native/gparts/flowcheck.py`; `tests/test_native_game_flow.py`.
- Files: `src/native/game/flow/*.s`, `src/native/game/flow/part.mk`, `src/native/game/flow/args.json`, `tests/test_native_game_flow.py`, this file; tools (if any) `tools/native/gparts/flow*.py`; build output `build/native/game/flow/` (`make -s -C src/native -f game.mk part P=flow ROOT=$PWD`).
- Its scratch block: `SB_FLOW` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`g_game65.s`: the action table's targets `loadLevel:635`, `victory:640` (a stop: the finale), `doNewGame:1100`, `doWorldDone:877`, `doPlayDemo:1205`, `doCompleted:737` (review 9); `doLoadLevel:645` split at `bmLoad` into its part before the load (`P_SetSecnodeFirstpoolToNull`, the game state, the reborn) and its tail after it (3.4); `G_ExitLevel:724`, `G_SecretExitLevel:728`, `G_WorldDone:863`, `G_DeferedInitNew:1089`, `G_ReloadDefaults:1094`, `initNew:1111` (with `M_ClearRandom`), `readDemoTiccmd:1144`, `G_DeferedPlayDemo:1194`, `readDemoHeader:1277`, `checkOverrun:1316`, `G_CheckDemoStatus:1332`; the continuations of the load protocol, one an action (3.4: `GA_LOADLEVEL`, `GA_NEWGAME`, `GA_PLAYDEMO`, `GA_WORLDDONE`); `wi_stuff65.s`: `WI_Start:206`, `WI_End:235`, `WI_checkForAccelerate:246`, `WI_Ticker:274` and the counts to `:585` without drawing; `st_stuff65.s`: `ST_Ticker:432`'s game effect (`M_Random`) as `st_tick`; `hu_stuff65.s`: `HU_Ticker:244`'s game effect (the message clear, through `G_SHOWMSG`, `G_MSGKEEP`) as `hu_tick`; helpers (`wi_stuff65.s`) `signLong`, `div1000`

Its checkpoint (GAME.md 2.4): `readDemoTiccmd` (every tic of the three demos), `G_CheckDemoStatus`, `doCompleted` (the tour's 8 exits), `WI_Ticker` (every intermission tic of the tour, with `wi` compared), `st_tick` and `hu_tick` (every tic of demo3: `M_Random`'s index and `player.message` compared), `G_DeferedInitNew`, `G_DeferedPlayDemo`; the load-containing actions (`doNewGame`, `doPlayDemo`, `loadLevel`, `doWorldDone`) through the driver's load protocol (3.4) from the reference's state at the action's call, compared after the continuation (the starts of the demos, newgame, the tour's world-done loads) (review 3)

Its planted bugs (each must fail the named check): `angleturn` not shifted back from the demo's byte (`readDemoTiccmd`); the secret exit's next map (`doCompleted`); the counts' step of 2 for kills (`WI_Ticker`); `M_Random` not called (`st_tick`); `demoplayback` not set in `GA_PLAYDEMO`'s continuation (the load runs); the message cleared with messages off (`hu_tick`, a synthetic case with `G_SHOWMSG` 0)

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `g_game65.s:loadLevel` | `loadLevel` | demo3 0, demo1 7, demo2 2, newgame 0, tour 0 |
| `g_game65.s:victory` | `victory` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `g_game65.s:doNewGame` | `doNewGame` | demo3 0, demo1 0, demo2 0, newgame 1, tour 1 |
| `g_game65.s:doWorldDone` | `doWorldDone` | demo3 0, demo1 0, demo2 0, newgame 0, tour 8 |
| `g_game65.s:doPlayDemo` | `doPlayDemo` | demo3 1, demo1 1, demo2 1, newgame 0, tour 0 |
| `g_game65.s:doCompleted` | `doCompleted` | demo3 0, demo1 0, demo2 0, newgame 0, tour 8 |
| `g_game65.s:doLoadLevel` | `doLoadLevel` | demo3 0, demo1 0, demo2 0, newgame 0, tour 8 |
| `g_game65.s:G_ExitLevel` | `G_ExitLevel` | demo3 0, demo1 0, demo2 0, newgame 0, tour 8 |
| `g_game65.s:G_SecretExitLevel` | `G_SecretExitLevel` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `g_game65.s:G_WorldDone` | `G_WorldDone` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `g_game65.s:G_DeferedInitNew` | `G_DeferedInitNew` | demo3 0, demo1 0, demo2 0, newgame 1, tour 1 |
| `g_game65.s:G_ReloadDefaults` | `G_ReloadDefaults` | demo3 2, demo1 2, demo2 2, newgame 2, tour 2 |
| `g_game65.s:initNew` | `initNew` | demo3 1, demo1 1, demo2 1, newgame 1, tour 1 |
| `g_game65.s:readDemoTiccmd` | `readDemoTiccmd` | demo3 2135, demo1 5027, demo2 3837, newgame 0, tour 0 |
| `g_game65.s:G_DeferedPlayDemo` | `G_DeferedPlayDemo` | demo3 1, demo1 1, demo2 1, newgame 0, tour 0 |
| `g_game65.s:readDemoHeader` | `readDemoHeader` | demo3 1, demo1 1, demo2 1, newgame 0, tour 0 |
| `g_game65.s:checkOverrun` | `checkOverrun` | demo3 3, demo1 3, demo2 3, newgame 0, tour 0 |
| `g_game65.s:G_CheckDemoStatus` | `G_CheckDemoStatus` | demo3 1, demo1 1, demo2 1, newgame 0, tour 0 |
| `wi_stuff65.s:WI_Start` | `WI_Start` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `wi_stuff65.s:WI_End` | `WI_End` | demo3 0, demo1 0, demo2 0, newgame 0, tour 8 |
| `wi_stuff65.s:WI_checkForAccelerate` | `WI_checkForAccelerate` | demo3 0, demo1 0, demo2 0, newgame 0, tour 880 |
| `wi_stuff65.s:WI_Ticker` | `WI_Ticker` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `st_stuff65.s:ST_Ticker` | `ST_Ticker` | demo3 2135, demo1 5026, demo2 3836, newgame 513, tour 428 |
| `hu_stuff65.s:HU_Ticker` | `HU_Ticker` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `g_game65.s:signLong`, `g_game65.s:div1000`.

## 2. Requests

Each with what, why (evidence) and its effect on other parts. The part
goes on with a local stand-in where one exists (marked in the source).

1. **The demo bank's layout (`DEMOB`, bank 91) into `glayout.py`.**
   What: a directory at `DEMOB:$0200`: a count byte, then 10 bytes an
   entry: the name (the manifest's symbol number and the offset of the
   reference `defdemoname` holds, 2 + 2), the lump's number in the WAD
   directory (2), its length (2), its address in `DEMOB` (2); the lumps
   from `$0300`. Constants `DM_DIR`, `DM_ESIZE`, `DME_NAME`, `DME_LUMP`,
   `DME_LEN`, `DME_ADDR` in `ggame.inc`. Why: GAME.md 1.10 gives `DEMOB`
   no layout, and upstream's `W_GetNumForName` [R `g_game65.s:1252-1260`]
   needs a name-to-lump table: `doPlayDemo` finds `defdemoname` there,
   `readDemoHeader` and `readDemoTiccmd` find `demo_p`'s lump. Stand-in:
   the constants at the top of `gflow.s`; the harness fills the bank from
   the reference's own WAD directory (`flowcheck.demob_records`: the lump
   that the name's base, upper case, names, as `W_GetNumForName` finds it).
   Effect: `ticrun.py` (lockstep) must fill `DEMOB` the same way for the
   demos and the generated streams; milestone 11 stores the game's demos
   in that form.
2. **`ghook.s`: `.import WI_Start`.** What: one line. Why: its
   `W_StartInter` hook does `FCALL WI_Start`, which names `WI_Start` once
   `flow` is built; without the import `make -f game.mk part P=flow` (and
   every `wave`, `game`, `gprof`, `release` build) stops with "ghook.s(238):
   Error: Symbol 'WI_Start' is undefined". Stand-in: the part's builds run
   ca65 with `--auto-import` (`flowcheck.CA65`, `make ... CA65="ca65
   --auto-import"`); ld65 still refuses any symbol nobody exports. Effect:
   none on other parts (every later part that `FCALL`s a routine of
   another part needs its own `.import`s, as `flow` has them).
3. **`g_resume`: in the core, and its caller.** What: `g_resume` lives in
   `GCORE` (the driver calls it with `jmp (FC_T)`, no paging: a group
   routine there would run in whatever its slot holds); the placement
   should count its 64 B and name it core. It runs the continuation of
   `G_LOADACT`'s action (GAME.md 3.4: `doLoadLevel`'s tail, then the
   action's: new game `gameaction` 0 and `ST_Start`; demo `player.cheats`
   0, `gameaction` 0, `usergame` 0, `demoplayback` 1, `starttime` from
   `I_GetTime`; world done `gameaction` 0) and returns A = 0; an action
   other than the four is a stop `GS_ACTION`. Re-entering `G_Ticker`'s
   action loop at its test of `gameaction` is part `tic`'s: its resume
   entry calls `g_resume` (`jsr g_resume`, core) and goes on at the loop;
   `ticrun.py` points `dg_resume` at that entry (the routine-with-load mode
   points it at `g_resume`, through `fl_tresume`). The four load actions
   (`loadLevel`, `doNewGame`, `doPlayDemo`, `doWorldDone`, and `initNew`,
   `readDemoHeader`, `doLoadLevel` inside them) run up to the load, set
   `G_LOADACT` from `gameaction` and return A = `GT_LOAD`; `tic`'s action
   loop returns `GT_LOAD` when an action does. `victory` stops
   (`GS_FINALE`), the others return A = 0.
4. **`M_Random` and `M_ClearRandom` in the tic image.** What: the tic
   images link `math-r.o` (the RENDER build: no `mrandom`,
   `mclearrandom`); export them (math.s's, or beside `gthink.s`'s
   `g_random`). Why: `ST_Ticker`'s `M_Random` [R `st_stuff65.s:432`],
   `initNew`'s `M_ClearRandom` [R `g_game65.s:1124`]. Stand-in: both in
   place in `gwi.s`/`gflow.s` (`rndtable` from `gthink.s`, `MT_MRND`,
   `MT_PRND`), marked "request 4". Effect: none on other parts.
5. **`gameroutine.py` and `grun.py`.** What: (a) `grun.run` picks a group
   routine's group by its address (`_group_has`), but every group of a
   slot starts at the slot's first byte: `G_ReloadDefaults` at `$9C00` is
   in group 15 and `grun.run` takes group 14 (its segment also covers
   `$9C00`), so the routine never runs (the driver jumps into the wrong
   group); use `gen/gplace.inc`'s `GP_name_G` (`flowcheck.group_of`).
   (b) `args.json` extensions this part uses: `"as": "symbol"` (an upstream
   pointer to a labelled constant as the native reference: tag 1, the
   manifest's symbol number, the offset), `"load": true` (the
   routine-with-load mode: the load image, a pre-state of the globals and
   the player, the re-key record, the `I_GetTime` values, `DEMOB`,
   `dg_resume`), native outputs `zp:NAME`. (c) A routine's own time: cost
   phases are `PHASE / 2` (a2vm), a harness wrapper (`fl_timed`) with the
   routine's group loaded first. (d) The routine harness on a state with
   no level (the title loop: `G_DeferedPlayDemo`, `G_DeferedInitNew`,
   `checkOverrun`, some `G_ReloadDefaults`): the bridge reads no level
   there, so only the globals and the player are written and compared
   (`flowcheck.load_prestate(setup=False)`, `read_plain`); the level's
   lists and tables (empty or partial there) neither. Stand-in: all of it
   in `flowcheck.py`. Effect: the integrator's reruns of this part's
   checkpoint with `gameroutine.py` need (a)-(d); (a) affects every part
   whose entries are in a group.
6. **The load: `texturetranslation` of the map's textures to identity.**
   What: upstream's load sets `texturetranslation[n] = n` for each texture
   it makes [R `r_data65.s:458`]; the native load (`lsetup.s`, `lgeom.s`)
   leaves `TEXTRANS` as the last level left it. Evidence: the tour's
   `doWorldDone` hit 1 (E1M1 to E1M2: `texturetranslation[62]` 63 at the
   call, 62 after upstream's load, 63 natively) and hit 4 (E1M9 to E1M4:
   [62] 61 to 62, [63] 61 to 63); the only differences of those cases.
   Effect: milestone 9's load (the store knows each map's textures);
   every lockstep run that changes level with an animated texture
   mid-cycle. Not this part's code: no stand-in.
7. **ticcap.py's re-key records of a run's later setups are empty** (map
   byte 0, no hints, no `CS_PREV`): their state "at the setup's end" does
   not decode (`setups[k]['problems']`: "blockmap: no lump starts at
   $000000", ...). Evidence: tour setups 2-9, demo1 setups 2-8. Stand-in:
   this part's load runs make the re-key record from the reference's
   state at the action's return (`flowcheck.rekey_of_state`: its
   `sighthint` and `CS_PREV1/2`, the same injected state with the same
   reason, GAME.md 3.6). Effect: `ticrun.py` at every setup but a run's
   first.
8. **Size: 2,946 B against 2,300 (+28%).** `gflow.s` 1,651 B (without
   its 639 B of test-only harness, `TESTBUILD`), `gwi.s` 1,295 B. Why:
   16-bit upstream arithmetic on a 65C02 (the wi counters, the times, the
   32-bit signed compares), the demo directory's three lookups (a macro:
   each caller's group must hold its own copy; a shared helper would have
   to be core), explicit stops for milestone 11's paths; no table or code
   is upstream's beyond the par times. Effect: the placement's sizes.

## 3. Results

All on a2vm against ref816, 2026-10-01 (`tools/native/gparts/flowcheck.py`;
`build/native/game/flow/report.json`). Cases are this part's own
(`build/native/game/flow/cases/`, gamecap's format), chosen by GAME.md
2.4's minimums: every call of an entry with fewer than 300 calls, else
300 spread evenly plus each call whose path (signature from this part's
call logs) no chosen call takes, plus the synthetic cases.

**Checkpoint (routine mode, GAME.md 3.5)**: every case from `$A5` and
`$5A`, each under `f121` and `fastpath`; the canonical state after the
call equal to ref816's (gcanon routine mode, R1-R6 only), the declared
outputs, no stray CPU write (the write log against the places the part,
the runtime and the driver may write; in a load run, between the action's
return and the load's end, also the setup's places); time = the routine
alone (cost phase 30, its group loaded first; the continuation phase 31),
CPU cycles and microseconds.

| Entry | Cases | Runs | Failed | Strays | Cycles median / worst | f121 us median / worst | fastpath us | Stack B |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| readDemoTiccmd (demo3, DEMO1, DEMO2) | 300 | 1,200 | 0 | 0 | 832 / 50,531 | 28.8 / 1,032.5 | 14.5 / 774.6 | 19 |
| G_CheckDemoStatus | 3 | 12 | 0 | 0 | 5,412 | 107.3 | 83.3 | 14 |
| doCompleted (the tour's 8 exits; 1 set aside, see below; its twin, 2 secret exits) | 10 | 40 | 0 | 0 | 7,443 / 7,451 | 136.4 | 112.3 / 112.5 | 16 |
| WI_Ticker (tour; 17 synthetic stages) | 317 | 1,268 | 0 | 0 | 15,286 / 23,186 | 307.5 / 422.2 | 234.4 / 345.8 | 14 |
| WI_checkForAccelerate | 300 | 1,200 | 0 | 0 | 199 / 219 | 3.3 / 3.8 | 3.3 / 3.7 | 7 |
| WI_End | 8 | 32 | 0 | 0 | 190 | 3.2 | 3.2 | 7 |
| ST_Ticker (st_tick, demo3) | 300 | 1,200 | 0 | 0 | 179 | 3.0 | 3.0 | 7 |
| HU_Ticker (hu_tick, demo3; 2 synthetic: messages off, kept) | 302 | 1,208 | 0 | 0 | 189 / 247 | 3.2 / 4.0 | 3.1 / 3.9 | 7 |
| G_DeferedInitNew | 2 | 8 | 0 | 0 | 182 | 3.1 | 3.0 | 7 |
| G_DeferedPlayDemo | 3 | 12 | 0 | 0 | 245 | 3.8 | 3.8 | 7 |
| G_ExitLevel | 8 | 32 | 0 | 0 | 182 | 3.1 | 3.0 | 7 |
| G_SecretExitLevel (synthetic) | 1 | 4 | 0 | 0 | 184 | 3.2 | 3.1 | 7 |
| G_WorldDone (synthetic: next, after map 8, secret) | 3 | 12 | 0 | 0 | 203 / 205 | 3.5 | 3.5 | 7 |
| G_ReloadDefaults | 10 | 40 | 0 | 0 | 180 | 3.0 | 3.0 | 7 |
| checkOverrun | 9 | 36 | 0 | 0 | 186 | 3.2 | 3.1 | 7 |
| doNewGame (load) | 2 | 8 | 0 | 0 | 25,745; continuation 1.4 us | 517.4 | 395.2 | 43 |
| doPlayDemo (load) | 3 | 12 | 0 | 0 | 155,767; continuation 11.5 us | 3,165.8 | 2,386.0 | 45 |
| loadLevel (load: DEMO1's 7 and DEMO2's 2 reborns) | 9 | 36 | 0 | 0 | 15,207; continuation 1.1 us | 306.1 | 233.0 | 40 |
| doWorldDone (load: the tour's 8) | 8 | 32 | **8** | 0 | 15,239; continuation 1.5 us | 306.1 | 233.5 | 40 |

The 8 failed runs are 2 cases, each from both fills and both profiles,
and differ only in `texturetranslation` after the load: request 6, the
load's, not this part's code. Every other field of those states is equal.
Times include about 170 cycles of the harness wrapper (`fl_timed`), and
the paging of every group a routine `FCALL`s under the skeleton's initial
placement (`doPlayDemo`'s 3.2 ms is mostly six group loads: `doPlayDemo`,
`readDemoHeader`, `checkOverrun`, `initNew`, `doLoadLevel` are in four
groups of two slots). The lowest S of all runs: `$01C2` (45 B below the
driver's `$EF`, a load action's; the IRQ's 24 B more).

**Set aside**: the tour's `doCompleted` hit 3 (E1M3's exit): the tour
script's poke of `_g_wminfo.next` (the stand-in for E1M3's secret exit,
`coverage/tour.script`) lands inside the call, so the capture's return
state is not upstream's code alone; every capture of an entry with few
cases in a run whose script pokes memory is run again alone on ref816
(`flowcheck.recall_poked`): only this one differs, its `--call` twin is
checked in its place (`cases/tour/doCompleted/poked.json`).

**Every tic (the sweeps: `fl_sweep` calls the routine with the reference's
inputs of each call and keeps its outputs)**, from `$A5` under `f121` and
`$5A` under `fastpath`, 0 failed, 0 stray writes:
readDemoTiccmd every tic of demo3 (2,135 calls), DEMO1 (5,027) and DEMO2
(3,837): the command, `demo_p`, `demoplayback`, the demo's end;
ST_Ticker every tic of demo3 (2,135): M_Random's index and value;
HU_Ticker every tic of demo3 (2,135): `player.message`, `G_MSGKEEP`;
WI_Ticker every intermission tic of the tour (880): the 13 wi counters,
attackdown, usedown, gameaction, didsecret, the sounds started.

**Random (the helpers against upstream's on ref816, mathref batch)**:
`times100` 100,000 inputs (0, +-1, the extremes, random), `div1000`
100,000, `signLong` every one of the 65,536 values: 0 failed. A planted
`times100` without its `* 64` term fails 498 of 500.

**Planted bugs (GAME.md 2.4), each in a scratch copy, each caught**:
`angleturn` not shifted (readDemoTiccmd: 2 of 12 cases fail); the secret
exit's next map (doCompleted: the 2 synthetic secret exits fail); the
counts' step (WI_Ticker: 3 of 317 fail; the tour's use key shows its
counts at once, so the synthetic stages with counts to count catch it);
`M_Random` not called (ST_Ticker: 12 of 12); `demoplayback` not set in
`GA_PLAYDEMO`'s continuation (doPlayDemo's load runs: 3 of 3); the message
cleared with messages off (HU_Ticker: the synthetic case with
`G_SHOWMSG` 0 fails).

**Other checks**: `victory` stops with `GS_FINALE`; the far-access grep
check (`gameroutine.grep_check`) on both sources: clean (the far reads
are of `DEMOB` only); `gcallgraph.py --check --built flow`: 0 failures;
`--stack --built flow`: 56 + 24 = 80 of 160 B.

**Sizes** (`flowcheck.py --build`): 2,946 B of 2,300 (request 8): gflow
1,651, gwi 1,295; 639 B of test-only harness besides (TESTBUILD).

**Test** `tests/test_native_game_flow.py`: the same checks on fewer cases
(6 an entry and every synthetic one, two fill and profile pairs; the
sweeps from `$A5` under `f121`; random 3,000; the six plants; the stop).

**`build/` growth**: `build/native/game/flow/` 163 MB (cases 141 MB, of
which AM_Ticker's 21 MB are only the source of HU_Ticker's; logs 0.3 MB;
the image and results the rest). Every temporary directory deleted.

**Commands**:

    python3 tools/native/gparts/flowcheck.py --build
    python3 tools/native/gparts/flowcheck.py --logs
    python3 tools/native/gparts/flowcheck.py --capture
    python3 tools/native/gparts/flowcheck.py --checkpoint --jobs 2
    python3 tools/native/gparts/flowcheck.py --sweeps
    python3 tools/native/gparts/flowcheck.py --random --count 100000
    python3 tools/native/gparts/flowcheck.py --plants --jobs 2
    python3 tools/native/gparts/flowcheck.py --report
    python3 -m unittest discover -s tests -p test_native_game_flow.py

## 4. Open points

- Request 6 (the load's `texturetranslation`): 2 of the 8 world-done
  loads fail on it until the load is fixed.
- `readDemoTiccmd` advances `demo_p`'s 16-bit offset; upstream adds 4 to
  its address's low word only (no bank carry) [R `g_game65.s:1179-1182`],
  which differs only for a demo lump across a 64 KB bank of upstream's
  memory. None is: DEMO3 is resident at `$10:8984` (8,550 B), DEMO1 and
  DEMO2 are placed at `$7E:0000`.
- Not native, by design (none is canonical state): `wipegamestate`,
  `automapmode` and `AM_Stop` (doCompleted, initNew), the keys' state,
  `HU_Ticker`'s message line and counter, `ST_Ticker`'s face and widgets,
  `G_CheckDemoStatus`'s timed-demo report and a single demo's quit (stops
  `GS_DEMOEND`), a loaded game (`GS_SAVEGAME`).
- `initShowNextLoc` after map 8 (`G_WorldDone` from the intermission) has
  no case: no run leaves E1M8 by its exit (its finale is out of scope), and
  a poked `gamemap` 8 on another map's level cannot be written through the
  manifest of map 8; `G_WorldDone` itself is checked after map 8 (its
  synthetic case from E1M8's state).
- The sweeps check every tic's declared fields; the routine-mode cases
  check the whole canonical state on 300 calls an entry and the paths.

## 5. The integration of wave 1 (2026-10-01)

| Request | Decision |
| --- | --- |
| 1 `DEMOB`'s layout | **Accepted**: `glayout.DEMOB_LAYOUT` (`ggame.inc` `DM_DIR`, `DM_ESIZE`, `DME_*`, `DM_LUMPS`); `gflow.s` and `flowcheck.py` use it; `ticrun.py` fills `DEMOB` this way when part `tic` exists (open item) |
| 2 `.import WI_Start` | **Accepted**, generally: `FCALL` makes a built target `.global`; no `--auto-import` |
| 3 `g_resume` in the core | Accepted as built (`GCORE`); part `tic`'s resume entry calls it |
| 4 `M_Random`, `M_ClearRandom` | **Accepted**: `gthink.s` `g_mrandom`, `g_mclearrandom` (tic images only: the load image is unchanged byte for byte); `st_tick` and `initNew` call them |
| 5 (a) the group | **Accepted** (`grun.entry_group`); (b)-(d) **in part** (as geom's R5) |
| 6 `texturetranslation` at a load | **Accepted, done in `g_resume`**: upstream's `R_GetTexture` sets `texturetranslation[n] = n` for each texture it makes; at every `P_SetupLevel` the PU_LEVEL textures are freed (`Z_FreeTags`, `p_setup65.s:122`) and each side's textures and a switch's partner made again (`P_LoadTexture`, `:684-688`), and for another map than the window's `W_SET` (`bmLoad`, `m_menu65.s:1780-1789`) `W_LevelDone`'s `moreColumns` makes more. Only `P_UpdateSpecials` writes another value, into `basepic .. basepic + 2`, so only those three entries can differ: `glayout.txr_compute` takes, from the upstream model of the load (`umodel.py`), each map's mask of them for the setup (`TXR_Ln`) and for `W_LevelDone` (`TXR_Mn`): E1M2 {62}, E1M4 {63} and {61, 62}, the others none; on the 57 setup dumps every entry a mask resets equals its texture in the R (setup) or W (`W_LevelDone`) state (30 entries, 0 different). `g_resume` applies them, with `G_WSET` (the map the window holds, a byte after the globals block, upstream's `W_SET`); a run that starts with a load takes `G_WSET` from the reference's (`gameroutine.wset_records`). The load image is unchanged. |
| 7 the re-key records | **Accepted**: `ticcap.py` matched the i-th `P_MapEnd` return to the i-th setup, but `P_MapEnd` also returns outside the setups; it now takes each setup's first return after its entry (by the machine's cycles): the 22 setups of the five fixed runs decode with 0 problems (all 22 had problems before); the tic references are remade, every tic's digests and every stream unchanged |
| 8 size | Accepted: 2,992 B against 2,300 (the reasons above; `g_resume`'s textures 66 B more) |

Rerun at the integration (`flowcheck.py --checkpoint`, `--sweeps`, `--random --count 100000`, `--plants`): 6,392 runs, 0 failed, 0 stray writes, the tour's 8 world-done loads included; the sweeps 0 failed; the helpers 0 failed; 6 plants caught (`m-random-not-called` on `st_tick`'s new `jmp g_mrandom`); the test module 17 tests OK. Size 2,992 B (test-only 0 in W: in the driver's area).

## 7. The final integration (2026-10-02)

Milestone 11's assembly applied its requests R4 and R5 to `gwi.s`
(`docs/play-requests.md`: `st_tick` now `jsr g_mrandom` then
`ST_TickerHook`, `hu_tick` calls `HU_TickerHook` first). The planted bug
`m-random-not-called` of `flowcheck.py` no longer applied to the new text;
the integrator moved it to the new `jsr g_mrandom` line (the same bug: no
`M_Random` call), so that it is planted again. The final acceptance runs
were made on the changed `gwi.s`.

The tour's lockstep run found that upstream's display writes one canonical
global of this part's: `WI_Drawer` sets `snl_pointeron` in the
intermission's NoState (`wi_stuff65.s:589-591`). The lockstep has no
display (milestone 11's), so the test driver sets it after a tic that
leaves the intermission in NoState, as a display would (`gdriver.s`
`wi_disp`, `TICLEVEL`); this part's code is unchanged. Milestone 11's
`WI_Drawer` must keep that write.
