# The tic phase's parts: how to build one

Milestone 10's game logic is written as 29 parts (`docs/GAME.md` 2.4), in
six waves, by builders working at the same time. This file is the
contract the skeleton gives them: where a part's files go, how it is
built and tested, and the conventions its code follows. `docs/GAME.md` is
the design; `docs/game-parts/<part>.md` is each part's own record
(requests, results, open points).

## Where things are

| What | Where | Whose |
| --- | --- | --- |
| A part's sources | `src/native/game/<part>/*.s` | the part's |
| A part's fragment | `src/native/game/<part>/part.mk` | the part's |
| A part's arguments | `src/native/game/<part>/args.json` | the part's |
| A part's record | `docs/game-parts/<part>.md` | the part's |
| The layouts, the part table, the zero page | `tools/native/glayout.py` | the skeleton's; changed by the integrator only, on a request |
| The runtime | `src/native/gobj.s`, `gcall.s`, `ghook.s`, `gdriver.s` | the skeleton's |
| Milestone 9's game core (in play) | `src/native/gthink.s`, `gpos.s`, `gspawn.s`, `gspec.s`, `gvalid.s`, `gweap.s` | the skeleton's |
| The skeleton's test routines | `src/native/game/gtest.s`, `grec.s`; `src/native/game/skel/args.json` | the skeleton's |
| The waves integrated | `src/native/game/integrated.txt` (one number) | the integrator's |
| The shared outputs | `build/native/game/shared/` | the prebuild's and the integrator's; parts only read them |

**A part never edits a shared file** (anything outside its own directory
and record): it writes a request in its record and goes on with a local
stand-in where it can (a constant in its own source, marked). The
integrator applies the requests between waves (`GAME.md` 3.8).

## The shared outputs

    make -s -C src/native -f game.mk shared ROOT=$PWD

(the prebuild of `tools/testpar.py` runs it) writes
`build/native/game/shared/`: `callgraph.json` (`gcallgraph.py`,
checked), `gen/ggame.inc`, `gen/gplace.inc`, `gen/gdisp.inc`, `game.cfg`,
`native-game-1.json` and `manifests/native-game-1-e1mN.json` (the game
manifests of the nine maps). The integrator also makes the survey
(`python3 tools/native/gamecap.py --survey`: `shared/survey/`), the tic
references (`python3 tools/native/ticcap.py --runs ...`: `shared/tic/`),
the generated streams (`tools/native/ticgen.py`: `shared/streams/`) and
the placement (`make -f game.mk place`: `shared/placement.json`, from
`gplace.py`).

## The makefile

`src/native/game.mk`; each target builds into its own directory with its
own generated includes, so parts never race:

| Target | Builds |
| --- | --- |
| `make -f game.mk part P=look` | `build/native/game/look/ptest.*`: the runtime, milestone 9's core, every part of an earlier wave or of an integrated wave (`integrated.txt`: a part of an integrated wave is rerun with its wave's other parts), and the part, its `gplace.inc`/`gdisp.inc` counting those as built |
| `make -f game.mk wave W=3` | every part of waves 1-3 (the integrator's) |
| `make -f game.mk game` | the lockstep build: every part, `LOCKSTEP`, `TESTBUILD` |
| `make -f game.mk gprof` | the same with the cost phases (`GPROF`) |
| `make -f game.mk release` | no `LOCKSTEP`, no `TESTBUILD`, the wrap fix |
| `make -f game.mk skel` | the skeleton's own test image (`gtest.s`) |
| `make -f game.mk place` | the placement (the integrator's) |
| `make -f game.mk sizes` | each module's bytes against its budget, the core's and the groups' fill |
| `make -f game.mk shared` | the shared outputs |

Always pass `ROOT=$PWD` (the repository's `demos/doom_gs`). `ROOT` may
point at a scratch copy of the sources: a source the copy lacks comes
from the tree (vpath), which is how the planted bugs build.

### A part's fragment

`src/native/game/<part>/part.mk`:

    PART := look
    WAVE := 3
    look_SRC := game/look/look.s game/look/range.s
    look_ENTRIES := A_Look lookForPlayers P_CheckMeleeRange

`<part>_SRC` are paths under `src/native/`; `<part>_ENTRIES` the native
labels of its routines (its row of `GAME.md` 2.4, `glayout.PARTS`).

## Writing a routine

Each source includes `rlayout.inc`, `math.inc`, `llayout.inc`,
`lgame.inc`, `ggame.inc` and `gplace.inc` (and `gdisp.inc` if it names a
dispatch table's entries), and starts each routine with the `ROUTINE`
macro, which puts it in the segment its placement gives it:

        ROUTINE A_Look
        ...
        rts

A routine's native name is its upstream label, or `<unit stem>_<label>`
when two units share the label (`glayout.native_names()`).

### Calls: FCALL and DCALL

* `FCALL target` for every call of another part's or the core's routine:
  `gplace.inc` makes it a `jsr` when the target is in the core or in the
  caller's own group, a call through `fc_call` (5 bytes of stack: the
  target's slot's group saved and restored whoever the caller is) when it
  is in another group, and the unbuilt stop (`GS_UNBUILT`, the routine's
  number in `GS_ARG`) when its part is not built. Never `jsr` a routine of
  another part directly: a placement change would break it. A built
  target is `.global` in the macro (imported, or exported where it is
  defined), so no `.import` of an `FCALL` target is needed. The callee's
  A, X, Y and P (a carry result) come back through `fc_call`, a restore
  of the caller's slot included (wave 1 as integrated). A helper of
  `glayout.INLINED` has no code: upstream's long-call wrappers
  `vtxSlowL`, `lineCrossL`, `icInsertL` are `FCALL vtxSlow`, `lineCross`,
  `icInsert` (wave 2 as integrated).
* `DCALL table` with the entry's number in A: a call through a dispatch
  table (`ACTTAB` the actions, `THTAB` the thinkers, `ITTAB` the
  iterators' callbacks, `TRVTAB` the traversers, `LSTAB` the line
  specials; `gdisp.inc`); an unbuilt entry stops with `GS_UNBUILTD`.
  `act_num` gives the `ACTTAB` number of a state's action. `dc_call`
  uses A, X and Y, so a target's arguments are in memory (wave 1 as
  integrated):
  * a mobj's `ACTTAB` action and a `THTAB` thinker function take their
    object (the mobj, the thinker's handle) in `GA_MO` (`GA_0-1`,
    upstream's `_Dp`); a weapon action takes its psprite in `GS_PSP`;
  * an `ITTAB` callback takes the line's or the mobj's handle in
    `GA_0-1` and returns C set to go on, clear to stop (part `geom`);
  * an `LSTAB` handler takes the line in `GA_0-1` and spectab's argument
    in `GA_2-3` (upstream's `_Dp[0-3]` and C), the thing in `GA_4-5` (a
    mobj handle: upstream's `SW_THING`) and, when `P_CrossSpecialLine`
    calls it, the side in `GA_6` (0 front, 1 back: upstream's `SW_CSIDE`),
    and returns its result in A (1 started, 0 not). `P_UseSpecialLine`
    and `P_CrossSpecialLine` (part `lines`) write them before `DCALL
    LSTAB` (wave 2 as integrated: `lines.md` request 3);
  * a `TRVTAB` traverser takes the intercept's index in `GA_0` (`ICPT` +
    6 × it) and returns C set to go on, clear to stop (part `path`;
    `path.md` R2; wave 4 as integrated);
  * an entry's number by name: `ggame.inc`'s `ITTAB_<label>`,
    `TRVTAB_<label>`, `LSTAB_<label>` (`LSTAB_lnExit` ..., `lines.md`
    request 2).
* The game core's helpers and the runtime that have no part name are
  always resident: call them with `jsr`: `gp_pointsub`
  (`R_PointInSubsector`), `gv_inc` (`validcount`), the object API,
  `g_random` (`P_Random`: A, changes X), `g_mrandom` and
  `g_mclearrandom` (`M_Random`, `M_ClearRandom`), the hooks of
  `ghook.s` (`S_StartSound`, `S_StartSound2`, ...), and milestone 6's
  math (`mul32`, `mul8`, `umul16`, ...): the render build `math-r.o`
  (W's `MATHW`, the card's products) and the game's `math-g.o` in the core
  (`pta3` = `R_PointToAngle3`, `finesine`, `finecosine`: `math.s -D
  GAMEMATH`, `mathgame.inc`; wave 2 as integrated, `damage.md` R1).
* `weaponinfo` (upstream's table, 12 bytes a weapon, `UO_WI_*` its
  fields) is in the core, part `damage`'s (`dweap.s`): read it in any
  group at `wInfo`'s or `wInfoOf`'s X, or at 12 × the weapon.
* The core's routines in play, for the parts (`FCALL` them by these
  names): `P_SpawnMobj` (`GA_X`, `GA_Y`, `GA_Z` 4 bytes each, `GA_TYPE`;
  the slot back in A:X and `GC_MO`; z `ONFLOORZ`, `ONCEILINGZ` or given),
  `P_SetThingPosition` and `P_CreateSecNodeList` (the mobj's slot in
  A:X), `A_Raise` (`ACTTAB`). `P_CreateSecNodeList` takes `LR_USE` (the
  line record of `P_CheckPosition`'s walk) as upstream does.

### Arguments and temporaries (zero page, `GAME.md` 4.4)

| Range | Name | Use |
| --- | --- | --- |
| `$48-$5B` | `GA_0`..`GA_19` (`GA_X` = +0, `GA_Y` = +4, `GA_Z` = +8, `GA_TYPE` = +12) | a call's arguments: the caller writes them, the callee reads them at its start; dead after that |
| `$5C-$74` | `GT_0`..`GT_24` | temporaries: any call may change them (the object API's own are at the end: `PL_N`, `PL_K`, `PL_T`, `FC_*`, `GO_*`) |
| `$18-$37`, `$75-$AE` | `GC_*`, `GS_*` | milestone 9's core: temporaries of every caller of it |
| `$38-$3F` | `GC_MP`, `GC_SP`, `GC_LP`, `GC_XP` | the object API's line pointers |

A part has no zero page of its own. What it keeps across a call goes in
its **scratch block**: `SB_<PART>` (`SB_<PART>_SIZE` bytes, 32 by
default; `sight` 106) in W `$9A00-$9DFF`. Two parts share bytes only when
no routine of one can be active while one of the other is; more bytes are
a request.

`p_map65.s`'s near scratch that several parts read after a call is the
shared tic scratch `GM_*` of `ggame.inc` (in GW, never overlaid; part
`geom` writes it): `GM_OPENTOP`, `GM_OPENBOT`, `GM_OPENRANGE`
(`opentop`, `openbottom`, `openrange`), `GM_TMFLOORZ`, `GM_TMCEILZ`,
`GM_TMDROPZ` (`tmfloorz`, `tmceilingz`, `tmdropoffz`), `GM_SS`, `GM_SEC`
(`MV_SS`, `MV_SEC`), `GM_NSPEC` (`numspechit`), `GM_BXL`..`GM_BYH`
(`blockRange`'s bounds); the trace's state (`p_trace65.s` and
`p_path65.s`'s: part `path` and `tracet` write it, `tracel`, `tracet`,
`path` and the traversers read it; `tracel.md` R1): `GM_TRACE`
(`_g_trace`: x, y, dx, dy), `GM_TRLONG` (`TR_LONG`), `GM_ICN` (the
intercepts so far), `GM_ICLAST` (`IC_LAST`), `GM_IVON` (`IV_ON`),
`GM_IVM` (`IV_ML`/`IV_MH`, 8), `GM_INVB` (`VT_INVB`'s bit 15 as `$80`);
`GM_ATRANGE` (`attackrange`: part `attack` writes it, part `spawn`
reads it; `spawn.md` request 1). Wave 3 as integrated: `GM_RR` (`VT_RR`,
not 0 when the fast vertex sides are on: part `path` reads it) and
`GM_SIDE1` (15: SIDE1's constants, the axis, `VT_P1`, `VT_P2`, `VT_CV`,
`VT_CT`, `VT_OXC`, `VT_OYC`, `VT_SGN`'s and `VT_DYF`'s high bytes), which
`sideSetup` (part `tracet`) writes and live to a trace's last block step
(`tracet.md` R4); `sideSetup` takes `P_PathTraverse`'s flags in A, and
upstream's `ptPatch` and `vsPatch` have no native code: `path` tests its
flags itself (`tracet.md` R5). `GM_TMTHING` (2), `GM_TMX`, `GM_TMY` (4
each), `GM_TMBBOX` (16: top, bottom, left, right, `UC_BOX*` order),
`GM_SPECHIT` (4 line numbers; their count `GM_NSPEC`), `GM_MPTRY`
(`MP_TRY`): `p_map65.s`'s `tmthing`, `tmx`, `tmy`, `_g_tmbbox`,
`_g_spechit`, written by part `checkpos`, read by `trymove`, `teleport`,
`chasemove` (`checkpos.md` R1). Wave 5 as integrated: `GM_LINETARGET`
(2: `_g_linetarget`, a mobj handle, `$FFFF` none: part `attack`'s
`P_AimLineAttack` writes it, `wfire` and `chase` read it after the call;
`attack.md` R1); `ggame.inc`'s `SKY_PIC` (`$FE`, `levelconv.py`'s: the
native byte pic of upstream's `skyflatnum`, which parts `attack` and
`xymove` compare a sector's ceiling pic with; `attack.md` R2,
`xymove.md` R3); the tic phase's persistent global `G_ONGROUND` (main,
after `G_FPSSHOW`: upstream's `PU_ONGROUND`, which part `player`
writes and reads across tics; `player.md` R1).

Other shared names (wave 2 as integrated): `ggame.inc`'s `SYM_<unit
stem>_<label>`, each symbol's number in the game manifest's list (what a
player's message holds: `pickup.md` P1), `GT_SWLIST` and `GT_SWIDX`
(GTAB's `switchlist` and `SW_IDX`); `lgame.inc`'s `U_WI_<field>_<w>`
(`weaponinfo`), `U_CLIPAMMO_<a>`, `U_HALFCLIP_<a>`, `U_POWERTICS_<p>`,
`U_BONUSADD`, `U_GOD_HEALTH`, `U_IDFA_ARMOR`, `U_IDFA_ARMOR_CLASS`,
`U_NUMCHEATS` (the release's tables and `.equ`s).

### Test-only code

A part's test-only code (`TESTBUILD`: its harness's entries, its bulk
drivers) goes in segment `DRIVER`, the card's driver area (`$E000`), not
in the core, whose room is the game's; the module sets `FC_HERE .set 0`
after the `.segment` so that its `FCALL`s page their targets. A test
source that only the part's own harness calls is linked only into the
part's own image, under a flag of its fragment that its harness passes
(`DM_TEST=1` for damage's `dtest.s`, `PS_TEST=1` for pspr's `pstest.s`):
every later part's image links the earlier parts' sources, and the
driver's area (3,584 B) cannot hold every part's drivers (wave 3 as
integrated: damage's image overflowed by 67 B).

### The game's objects: the object API (`gobj.s`)

Every read and write of a mobj, sector, line or special goes through the
API, never `g_get`/`g_put`/`far_get`/`far_put` of their banks (a grep
check, `gameroutine.grep_check`, runs on the core; the integrator runs it
on every part's game sources; a test-only module of the driver's area that
reads its own records' banks, as `tracelt.s` does, is not game code):

| Call | Gives |
| --- | --- |
| `mo_get` (A:X a slot) | `GC_MP`: the mobj's line (RTHING, groups A, B, C: `LW_MOB`'s layout) |
| `mo_dirty` (A: groups changed, bit 0 RTHING .. 3 C) | the line written back at its eviction or the flush |
| `mo_store` | `LW_MOB` into slot `GC_MO`'s line, all dirty (a spawn) |
| `sec_get` (A a sector) / `sec_dirty` (A 1 render, 2 game) | `GC_SP` |
| `sd_get` (A:X a side) / `sd_put` | `SD_BUF` (its record, `SD_AT` its address); `sd_put` writes it back |
| `lt_get` (A:X an entry of the line tables: a sector's first + i) | A:X its line (and `API_W`) |
| `bk_get` (A:X a block's index) / `bk_put` | A:X (and `API_W`) the first mobj of its list; `bk_put` sets it to `API_W` |
| `sn_get` (A:X a sector node) / `sn_put` / `sn_putw` (Y a field) | `SN_BUF` its record; `sn_put` writes `SN_BUF`, `sn_putw` the word `API_W` at Y |
| `mi_get` (A a type, Y a field) | `API_W` and A:X: the word of its mobjinfo record |
| `hn_get` (A:X a mobj slot) / `hn_put` | A:X its sight hint (a line + 1, 0 none); `hn_put` sets it to `API_W` |
| `rj_row` (A a sector) / `rj_byte` (A:X an offset) | A:X its REJECT row (`RJROW`); A the byte of REJECT |
| `ln_get` (A:X a line) / `ln_dirty` | `GC_LP` (the record and the line's two sectors) |
| `sp_get` (A:X a special's handle) / `sp_dirty` / `sp_store` | `GC_XP` |
| `nd_get`, `sg_get`, `ss_get`, `bl_get` | a node, seg, subsector, blockmap words into their buffers |
| `pl_get`, `pl_put`, `pl_setn` (A:X a slot) | the walk's planes: next thinker, kind, tics |

A line's pointer stays valid until the next get of the same kind that
misses; the most recently got lines are never evicted. The driver
flushes every cache at the tic phase's end, before a load and before a
frame.

### The load protocol

`G_Ticker` returns `GT_LOAD` (A) with `G_LOADACT` (the action that
started the load: `GA_LOADLEVEL`, `GA_NEWGAME`, `GA_PLAYDEMO`,
`GA_WORLDDONE`); the driver flushes, loads the level (`nl_setup`), and
calls the continuation `g_resume` (part `flow`), which does the action's
tail and re-enters the action loop. **Data in the core image's own
segments is reloaded at each load**: what must survive a load lives in
the globals block (`llayout.py` `GLOBAL_FIELDS`, and the tic phase's own
`glayout.TIC_MAIN_FIELDS` after it: `G_WSET`, the map the level window
holds; `G_FPSSHOW`, idrate's frame rate flag, which the harnesses write
from the reference's `_g_fps_show`) or in a part's request for one. `g_resume` also sets
`TEXTRANS[n] = n` for the textures the load made (`glayout.txr_compute`,
`TXR_*`; upstream's `R_GetTexture`); a run that starts with a load takes
`G_WSET` from the reference's `W_SET` (`gameroutine.wset_records`).

The demo bank `DEMOB` (`glayout.DEMOB_LAYOUT`, `ggame.inc` `DM_*`,
`DME_*`): a directory at `DM_DIR` (a count, then `DM_ESIZE` bytes an
entry: the name's symbol number and offset, the lump's number, its
length, its address), the lumps from `DM_LUMPS`.

### Stops

`g_stop` with a code of `glayout.GS` (`GS_STATUS`, `GS_ARG`): the driver
ends the run there (`drv_crash`) and the harness reports the code.

## args.json: a part's entries

The routine harness (`gameroutine.py`) calls each entry natively with the
inputs of the reference's call, and compares its declared outputs. The
format (`"game-args 1"`):

    {"format": "game-args 1",
     "entries": {
      "p_spawn65.s:P_SpawnMobj": {
       "native": "P_SpawnMobj",
       "in": [{"from": "xc", "to": "zp:GA_X"},
              {"from": "dp:_Dp:4", "to": "zp:GA_Y"},
              {"from": "s:4:2", "to": "zp:GA_TYPE", "bytes": 1}],
       "out": [{"native": "ax", "upstream": "xc", "as": "mobj"}]}}}

* `native`: the routine's native label (its group comes from the build).
* `in`, each from an upstream source to a native destination:
  * sources: `a`, `x`, `y` (the upstream registers, 16 bits), `xc` (X:C,
    32 bits), `dp:SYMBOL[+N]:LEN` (the direct page: D plus SYMBOL's
    offset), `s:N:LEN` (the stack at the call: S + N), `abs:SYMBOL[+N]:LEN`
    (a near or far symbol);
  * destinations: `a`, `x`, `y` (the native registers, a byte), `ax` (A
    low, X high), `zp:NAME` (a zero-page name of `ggame.inc`: `GA_X`,
    `GT_3`, ...), `main:NAME` (a global of `llayout.GLOBAL_FIELDS`);
    `bytes` cuts or pads;
  * `as`: `mobj` turns an upstream mobj pointer into its native slot.
* `out`, each a native value against an upstream one at the return:
  `native` (`a`, `x`, `y`, `ax`, `main:NAME`), `upstream` (a source as
  above, read at the return), `bytes`, `as` (`mobj`: the two must be the
  same mobj). A result upstream returns in scratch is declared here and
  compared, whether or not the canonical state keeps it.

## Testing a part

1. Build: `make -s -C src/native -f game.mk part P=<part> ROOT=$PWD`.
2. Cases: `python3 tools/native/gamecap.py --capture FILE:LABEL --run
   demo3 [--sample K | --all | --hits ...]` (the survey gives each call's
   tic and the dispatch targets it reached;
   `python3 tools/native/gameroutine.py --eligible <part>` says which
   calls are eligible now).
3. Run: `python3 tools/native/gameroutine.py --routine FILE:LABEL --obj
   build/native/game/<part> --name ptest` (both fills, `gcanon.py`'s
   routine mode).
4. Record the results and the requests in `docs/game-parts/<part>.md`.

A routine entered by a `JML` (`ITTAB`'s callbacks through `callLN`,
`callLN2`; the `THTAB`, `ACTTAB`, `TRVTAB` targets) cannot be captured
by ref816's `--capture` (it counts `JSR`, `JSL` and `JSR (a,x)`): capture
it at the `JSL`'d stub that jumps to it, in runs where the stub serves
only that routine (part `tracel`'s `CAPTURE_AS`; `tracel.md` R6).

A part's harness that keeps its own cases sets `gamecap.CASES` (one
global): its test module sets it again in `setUpModule`, since
`unittest discover` runs every module in one process.

A variant of a captured call (the reference's routine again on the
case's machine, with pokes: another traverser, a stop) can read pages the
captured call never read, which a case holds only from its run's base,
another moment's machine (wave 4: demo1's `LN36` of an earlier life, so
upstream stamped lines at stale addresses). Such variants need the whole
machine: `tools/native/gparts/path.py`'s `capture_whole` keeps every page
that differs from the base (`path.md` R6).

ref816's `--capture` does not count a nested call of the routine it is
capturing: a capture at `p_tick65.s:callFn` whose call enters `callFn`
again before it returns (an `A_Look` that sees: `P_SetMobjState` runs the
see state's action through `callFn`) makes every later requested hit of
the same ref816 run one call late, so a case may be another action's
call. The call log's `hit` counts every call. Put such a hit last in its
capture run, and check each case (its `FN_P` and gametic at the entry:
`tools/native/gparts/look.py` `nesting_hits`, `verify`). This holds for
any dispatch stub whose target can enter it again (`callFn`, `callLN`,
`callLN2`, `callTrav`; `look.md` request 6).

## The parts' interfaces (waves 2 to 6 as integrated)

For the later waves' callers; each part's record has the rest.

| Routine (part) | In | Out |
| --- | --- | --- |
| `P_DamageMobj` (`damage`) | `GA_0-1` the target, `GA_2-3` the inflictor, `GA_4-5` the source (handles; `$FFFF` none), `GA_6-7` the damage (signed) | nothing; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `wInfo`, `wInfoOf` (`damage`) | the ready weapon; A = a weapon | X = A = the record's offset in `weaponinfo` (12 × the weapon); change Y and the math's slot 0 |
| `P_DropWeapon`, `lowerWeapon` (`damage`) | the player | the weapon's psprite to its down state |
| `P_TouchSpecialThing` (`pickup`) | `GA_0-1` the special, `GA_2-3` the toucher | nothing |
| `P_GivePower` (`pickup`) | A = the power | A = 1 and C set given, else 0 |
| `C_Responder` (`pickup`) | A = the cheat's event number (`ticcap.CHEATS`) | A = 1, or 0 for a number past the table |
| `P_UseSpecialLine` (`lines`) | `GA_0-1` the thing, `GA_2-3` the line | A = 1 or 0 |
| `P_CrossSpecialLine` (`lines`) | `GA_0-1` the line, `GA_2-3` the thing, A the side (0 front) | nothing |
| `P_ChangeSwitchTexture` (`lines`) | A:X the line, Y useAgain (0, 1) | nothing |
| `findSpecial` (`lines`) | A:X the line, Y 0 usetab, else crosstab | C set: A the argument, X the `LSTAB` number, Y the mode, `GT_0` the entry |
| `P_SpawnPuff`, `P_SpawnBlood` (`spawn`) | `GA_X`, `GA_Y`, `GA_Z`; blood's damage in `GA_12-13` | nothing |
| `spawnXYZ`, `zNoise`, `ticsNoise` (`spawn`) | A a type and `GA_X..GA_Z`; `GA_Z`; A:X a mobj | the slot in A:X; `GA_Z` noised; the tics noised |
| `P_ZMovement`, `missileHit`, `p_mobj_isPlayer` (`spawn`) | A:X a mobj | nothing; C set exploded; A 1 / 0 |
| `P_IsAttackRangeMeleeRange` (`spawn`) | `GM_ATRANGE` | A 1 / 0 |
| `shr3` (`spawn`) | `GA_0-3` | `GA_0-3` >> 3, arithmetic |
| `PIT_AddLineIntercepts` (`tracel`) | `GA_0-1` the line (`ITTAB`) | C set go on, clear full |
| `divlineSide` (`tracel`) | `GA_0-3` x, `GA_4-7` y | A = 0, 1 |
| `interceptVector3` (`tracel`) | the divline in `GA_0-15` | `GA_16-19` the frac |
| `addIntercept`, `icInsert` (`tracel`) | A:X what, `GA_16-19` the frac; A an entry | C clear when full; the chain |
| `ivSetup`, `gOf`, `smul`, `vsC` (`tracel`) | `tracel.md` "The native interfaces" | |
| `traceLines`, `traceThings` (`tracet`) | `GA_0-1` the block's x, `GA_2-3` its y (signed words); `traceLines` only when `GM_RR` is not 0 | A = 1 and C set, A = 0 and C clear when the intercepts are full |
| `sideSetup` (`tracet`) | A = the flags (`UC_PT_ADDTHINGS`); `GM_TRACE`, `GM_TRLONG` | `GM_IVON`, `GM_SIDE1`, `GM_INVB`, `GM_RR` |
| `longTrace` (`tracet`) | `GM_TRACE` | C set (A = 1): a long trace |
| `P_CheckPosition` (`checkpos`) | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y | A = 1 fits, 0 not; `GM_TMFLOORZ`, `GM_TMCEILZ`, `GM_TMDROPZ`, `GM_NSPEC` and `GM_SPECHIT`, `G_CEILLINE`, the line record (`G_LROK`, `G_LRN`, `G_LRLINES`) |
| `cpCopy` (`checkpos`) | the same | `GM_TMTHING`, `GM_TMX`, `GM_TMY` |
| `checkPos` (`checkpos`) | `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_MPTRY` (1 from `P_TryMove`: the point's floor after the things) | C set and A = 1 fits; as `P_CheckPosition`; `G_MPCLOB` 1 when PIT_CheckThing ran |
| `setBox` (`checkpos`) | `GA_0-1` the thing, `GM_TMX`, `GM_TMY` | `GM_TMBBOX`; `SB_CHECKPOS`'s `MP_TMF`, `MP_RAD` |
| `walkRange`, `lineBlocks`, `checkThing` (`checkpos`) | `checkpos.md` R5 | |
| `P_MovePsprites` (`pspr`) | (the player) | `player`'s `P_PlayerThink` and the death think, every tic |
| `tickPsprite` (`pspr`) | A = the psprite (0 weapon, 1 flash) | |
| `A_*` weapon actions (`pspr`, `ACTTAB`) | `GS_PSP` the psprite (`gw_setpsprite`'s convention) | `A_WeaponReady` keeps its psprite on the stack |
| `fireSomething` (`pspr`) | A = k | the flash psprite to the ready weapon's flash state + k (`wfire`'s actions) |
| `fireWeapon`, `checkAmmo`, `P_CheckAmmo` (`pspr`) | | checkAmmo: A = 1 enough or none needed, 0 not (no weapon switch) |
| `recursiveSound` (`pspr`) | A = a sector, Y = the blocks (0, 1), `PS_TGT` the target; `validcount` raised by the caller | a flood deeper than 512 levels stops (`GS_FLOOD`) |
| `p_pspr_startSound`, `setMoState` (`pspr`) | A = a sound; A:X = a state | `S_StartSound(player->mo, A)`; A as `P_SetMobjState` (the player's mobj) |
| `signExt4`, `signExt0` (`pspr`) | A:X a word | `M_B`, `M_A` = it sign extended |
| `bringUpWeapon` (`gweap.s`, the core) | the player | the pending weapon (the ready one when none) up from the bottom (`pspr.md` R2) |
| `A_Look`, `A_FaceTarget`, `A_Scream`, `A_XScream`, `A_Pain`, `A_Fall`, `A_PlayerScream` (`look`, `ACTTAB`) | `GA_MO` the actor | nothing |
| `lookForPlayers` (`look`) | `GA_0-1` the actor, A = allaround (0, 1) | A = 1 seen (its target the player's mobj, threshold 60), 0 not |
| `behindFast` (`look`) | `GA_0-1` the actor, `GA_2-3` the target | C set: A = 1 behind, 0 in front; C clear: it cannot tell (A = `$FF`) |
| `checkMeleeRange`, `P_CheckMeleeRange` (`look`) | `GA_0-1` the actor | A = 1, 0 |
| `checkMissileRange`, `P_CheckMissileRange` (`look`) | `GA_0-1` the actor (with a target) | A = 1, 0 |
| `faceTarget` (`look`) | `GA_0-1` the actor | A = 1 (a target: faced), 0 none |
| `loadTarget` (`look`) | `GA_0-1` the actor | `LK_AP`, `LK_AT` set; A:X the target; C set when there is one |
| `p_enemy_randMod`, `p_enemy_startSound` (`look`) | A = c; A = the sound, `GA_0-1` the origin | A = `P_Random()` % c; `S_StartSound` |
| `P_RadiusAttack` (`look`) | `GA_0-1` the spot, `GA_2-3` the source (`$FFFF` none), `GA_4-5` the damage | nothing |
| `PIT_RadiusAttack` (`look`, `ITTAB`) | `GA_0-1` the thing | C set (go on) |
| `EV_DoDoor`, `EV_VerticalDoor`, `EV_DoPlat` (`evworld`) and `LSTAB`'s `lnDoor`, `lnVDoor`, `lnPlat` | `evworld.md` 1.2 "The native interfaces" | |
| `P_LineAttack` (`attack`) | `GA_0-1` t1, `GA_2-5` the angle, `GA_6-9` the distance, `GA_10-13` the slope, `GA_14-15` the damage | nothing; `GM_ATRANGE` the distance; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `P_AimLineAttack` (`attack`) | `GA_0-1` t1, `GA_2-5` the angle, `GA_6-9` the distance | `GA_0-3` the slope when a target was found, else 0; `GM_LINETARGET` the target (`$FFFF` none); `GM_ATRANGE` |
| `PTR_AimTraverse`, `PTR_ShootTraverse` (`attack`, `TRVTAB` 1, 2) | `GA_0` the intercept | C set go on, clear stop |
| `puffPos`, `mul3`, `rangeMul` (`attack`) | `attack.md` 1.2 | |
| `P_PlayerThink` (`player`) | (the player) | part `tic`'s `P_Ticker`, every tic |
| `movePlayer`, `calcHeight`, `onGround` (`player`) | (the player); `calcHeight` reads onground (`G_ONGROUND`) | `movePlayer` and `onGround` set `G_ONGROUND` (onground = z <= floorz) |
| `fixedSquare`, `thrustMul`, `times64` (`player`) | X = 0 (momx) or 4 (momy); `M_R` the trig value and `PY_T` m; `M_R` | `M_R`: upstream's FixedSquare with its wraps; FixedMulAngle(m, value); 64 `M_R` |
| `angleToAttacker` (`player`) | (the player's attacker) | `M_R` the angle |
| `specialSector` (`player`) | A = the player's sector | may call `P_DamageMobj`, `G_ExitLevel` |
| `hurt32` (`player`) | A:X = a damage | C set and `GA_0-7` = `P_DamageMobj`'s arguments when leveltime & 31 is 0, else C clear: **differs from upstream**, whose `hurt32` makes the call; natively the caller (`specialSector`) does `FCALL P_DamageMobj` (`player.md` 1) |
| `P_UseLines` (`player`) | (the player) | |
| `PTR_UseTraverse`, `PTR_NoWayTraverse` (`player`, `TRVTAB` 4, 5) | `GA_0` the intercept | C set and A = 1 go on, C clear and A = 0 stop |
| `P_SpawnMissile` (`missile`) | `GA_0-1` the source, `GA_2-3` the destination, A the type | A:X the missile; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `checkMissile` (`missile`) | A:X the missile | nothing |
| `srcAbove`, `seeTarget`, `thSpeed`, `angleMom` (`missile`) | A:X a mobj; `seeTarget` also `GA_0-1` the source, `angleMom` `GA_0-3` the angle | `GA_X`..`GA_Z` = its x, y, z + 32.0; its see sound and target; `M_A` = its type's speed; its angle, momx, momy |
| `halfMom` (`missile`) | `GC_MP` the mobj's line, X the coordinate's offset, Y the momentum's | the coordinate += momentum >> 1 (the caller marks the line dirty) |
| `pMove` (`chasemove`) | `GA_0-1` the actor | A = 1 (C set) moved or a special line opened, 0 (C clear) not; after a refused move with special lines met movedir `DI_NODIR` and `GM_NSPEC` `$FF`; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `tryWalk`, `P_TryWalk` (`chasemove`) | `GA_0-1` the actor | A = 1 (C set): moved, movecount = `P_Random() & 15`; 0 (C clear) not |
| `newChaseDir`, `P_NewChaseDir` (`chasemove`) | `GA_0-1` the actor, which has a target (none: `GS_ERROR`) | nothing |
| `PIT_AvoidDropoff` (`chasemove`, `ITTAB`) | `GA_0-1` the line | C set (go on) |
| `P_XYMovement`, `slideMove` and the move's helpers (`xymove`) | `xymove.md` 1.1 | |
| `P_PathTraverse` (`path`) | `GA_0-3` x1, `GA_4-7` y1, `GA_8-11` x2, `GA_12-15` y2, `GA_16` the flags (`UC_PT_ADDLINES`, `UC_PT_ADDTHINGS`), `GA_17` the traverser (`TRVTAB_<label>`) | A = 1 and C set (true), A = 0 and C clear (false); `GM_TRACE` (x1, y1 moved off a block line), the intercepts (`ICPT`, `ICHAIN`, `GM_ICN`, `GM_ICLAST`) |
| a `TRVTAB` traverser (`attack`, `xymove`, `player`) | `GA_0` the intercept's index (`ICPT` + 6 × it); `GM_TRACE` | C set to go on, clear to stop |
| `P_TryMove` (`trymove`) | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y | A = 1 and C set: moved; A = 0 and C clear: not; `GM_TMFLOORZ`, `GM_TMCEILZ`, `GM_TMDROPZ`, `G_CEILLINE`, `GM_NSPEC` and `GM_SPECHIT` and the line record as `checkPos` leaves them, but `GM_NSPEC` is `$FF` when the crossed lines were walked (upstream's -1); changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `P_NightmareRespawn` (`trymove`) | A:X the dead monster | nothing |
| `T_MovePlaneFloor`, `T_MovePlaneCeiling`, `checkSector`, `changeSector`, `heightClip`, `T_MoveFloor` (`planes`, `THTAB`) | `planes.md` 1.2 "The native interfaces" (the movers: `GA_0` the sector, `GA_2-5` speed, `GA_6-9` dest, `GA_10` the direction) | the movers: A = `UC_OK`, `UC_CRUSHED`, `UC_PASTDEST` |
| `EV_DoFloor`, `EV_BuildStairs`, `EV_DoDonut`, `newFloor` (`evfloor`) and `LSTAB`'s `lnFloor`, `lnStairs`, `lnDonut` | `evfloor.md` 1.2 "The native interfaces" (the floor as made: for `planes`' `T_MoveFloor`) | |
| `EV_Teleport` (`teleport`) | `GA_0-1` the line, `GA_4-5` the thing, `GA_6` the side (0 front, 1 back) | A = 1 teleported, else 0 |
| `lnTele` (`teleport`, `LSTAB`) | `P_CrossSpecialLine`'s places (as `EV_Teleport`'s) | A = `EV_Teleport`'s result |
| `P_TeleportMove` (`teleport`) | `GA_0-1` the thing, `GA_2-5` x, `GA_6-9` y, `GA_10` boss (0, 1) | A = 1 moved, 0 blocked; `GM_TMTHING`, `GM_TMX`, `GM_TMY`, `GM_TMFLOORZ`, `GM_TMCEILZ`, `GM_TMDROPZ`, `GM_NSPEC` 0, `validcount` + 1, `G_CEILLINE` none |
| `stompThing` (`teleport`, `ITTAB`) | `GA_0-1` the mobj | C set go on, clear blocked |
| `P_CreateSecNodeList` (the core's `gp_secnodes`) | the mobj | also `GM_TMX`, `GM_TMY` = its x, y, as upstream's (wave 4 as integrated: `teleport.md` R4) |
| `T_VerticalDoor` (`movers`, `THTAB` 6), `T_PlatRaise` (`movers`, `THTAB` 5) | `GA_0-1` the thinker's handle | nothing; changes `GA_*`, `GT_*`, `GC_*`, the math block and what the plane movers change (`movers.md` 1.2) |
| `partLight` (`movers`) | A:X the door's handle | nothing |
| `mulExt` (`movers`) | `M_A` a 32-bit value, A:X a word (sign extended) | `M_R` the product's low 32 bits |
| `A_FirePistol`, `A_FireShotgun`, `A_FireCGun`, `A_FireMissile`, `A_Punch`, `A_Saw` (`wfire`, `ACTTAB`) | `GS_PSP` the psprite (only `A_FireCGun` reads it) | nothing; changes `GA_*`, `GT_*`, `GS_*`, the math block |
| `P_SpawnPlayerMissile` (`wfire`) | `GA_0-1` the source | nothing |
| `bulletSlope`, `gunShot` (`wfire`) | (the player's mobj); `gunShot` A = accurate (0 not) and `WF_SLOPE` | `bulletSlope`: `WF_SLOPE` (`SB_WFIRE` + 0, 4 B) |
| `meleeAngle`, `spread`, `meleeAttack`, `angleToTarget`, `p_pspr_randMod`, `useAmmo` (`wfire`) | `wfire.md` 1.2 | |
| `G_Ticker` (`tic`) | (the globals) | A = 0, or `GT_LOAD` with `G_LOADACT` the action (the load protocol); `GS_SAVEGAME` for a saved game's action, `GS_ACTION` past `ga_worlddone` (upstream loops for ever) |
| `g_ttick`, `g_tresume` (`tic`, the card's `DRIVER`) | | the lockstep driver's `dg_ticker`, `dg_resume`: `G_Ticker`; flow's `g_resume`, then `G_Ticker`'s action loop (`gt_loop`) |
| `P_Ticker`, `P_RunThinkers`, `P_MapEnd` (`tic`) | | the level's tic; the walk (`RT_TH`, `RT_NEXT`); `GM_TMTHING` = `$FFFF` |
| `P_MobjThinker` (`tic`, `THTAB` 1) | `GA_MO` the mobj | nothing |
| `A_Chase`, `A_PosAttack`, `A_SPosAttack`, `A_TroopAttack`, `A_SargAttack`, `A_CyberAttack`, `A_BruisAttack`, `A_Explode`, `A_BossDeath` (`chase`, `ACTTAB`) | `GA_MO` the actor | nothing; changes `GA_*`, `GT_*`, `GS_*`, the math block |

## The tic level

`ticcap.py` makes each run's reference (one digest a kind a tic, the
schedule, the setups' re-key records, the T3 windows, the stream);
`ticrun.py` runs the lockstep build against it (from wave 1 on, once
part `tic` gives `G_Ticker` and part `flow` `g_resume`). The stream file
(`shared/tic/RUN.stream`, loaded into GTEST `GT_STREAMB`): `GSTR`, a
version byte, the tic count (4 bytes); per tic its gametic's low word
(2), its command (8: forwardmove, sidemove, angleturn, buttons, the
ring's spare), its events' count (1) and each event (kind, length,
bytes: 1 a cheat by its number, 2 a poke of main (address 2, size 1,
value), 3 the menu's state (menuactive, showMessages), 4 a menu's
`G_DeferedInitNew` with its skill); then the I_GetTime values (a count,
4 bytes each). Since the final integration a record for every
`G_Ticker` of the run from its first setup's tic (the intermission's too:
their commands end it), none of the start tic's events (its state holds
them already); the lockstep driver (`gdriver.s` `stream`, `TICLEVEL`)
puts each tic's command into `G_CMDS + 8 (gametic & 7)` and applies its
events before the tic. A demo reads its own lump (DEMOB) for its
commands.
