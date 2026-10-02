# Part `geom` (wave 1)

The record of milestone 10's part `geom` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 1; upstream 1707 B, native budget 2200 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 1's `geom` (built 2026-10-01, not yet reviewed or integrated).
- Files: `src/native/game/geom/geom.s` (side tests, openings, the point's sector, `blockRange`), `giter.s` (the two iterators and `ITTAB`'s mechanism), `geomt.s` (the test driver of the random checks, `TESTBUILD` only), `geom.inc` (the scratch block's names), `part.mk`, `args.json`; `tests/test_native_game_geom.py`; this file; the tool `tools/native/gparts/geom_check.py`; build output `build/native/game/geom/` (`make -s -C src/native -f game.mk part P=geom ROOT=$PWD`).
- Its scratch block: `SB_GEOM` (32 B, `ggame.inc`), all 32 bytes used (`geom.inc`).

The routines (GAME.md 2.4's row):

`p_map65.s`: `P_PointOnLineSide:2458`, `P_BoxOnLineSide:2483` (every case; milestone 9 built the slanted one inside its walk), `P_LineOpening:2367`, `P_LineOpeningXY:2451`, `pointSector:2094` with `posMul:2265` (a point's sector through `R_PointInSubsector`), `sectorFloor:2064`, `baseFloor:2062`, `baseFloorL:2060` (review 9), `baseLite:2083`, `P_BlockLinesIterator:2680`, `P_BlockThingsIterator:2791`, `blockRange:3353`; helpers `argLine4`, `box1`, `box2`, `posPub`, `walk1`, `walk2`, `callLN`, `callLN2`

Its checkpoint (GAME.md 2.4): Captured calls of every entry; the two iterators with the recording callback (3.5) on every captured call's block range; 100,000 random point-line and box-line pairs per map through `--call` of upstream's routine

Its planted bugs (each must fail the named check): an on-the-line point given side 1 (pairs); `P_BoxOnLineSide`'s horizontal case on the wrong edge (pairs); a block list read from its first entry (iterators: milestone 9's rule [R `LEVELS.md` 2.4]); `P_LineOpening`'s lowfloor as the higher floor (captured: `_g_lowfloor` is a declared output)

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_map65.s:P_PointOnLineSide` | `P_PointOnLineSide` | demo3 6866, demo1 32732, demo2 41115, newgame 617, tour 0 |
| `p_map65.s:P_BoxOnLineSide` | `P_BoxOnLineSide` | demo3 0, demo1 0, demo2 41, newgame 0, tour 0 |
| `p_map65.s:P_LineOpening` | `P_LineOpening` | demo3 348, demo1 1964, demo2 339, newgame 18, tour 0 |
| `p_map65.s:P_LineOpeningXY` | `P_LineOpeningXY` | demo3 1342, demo1 4154, demo2 460, newgame 154, tour 0 |
| `p_map65.s:pointSector` | `pointSector` | demo3 22993, demo1 19715, demo2 9191, newgame 592, tour 71 |
| `p_map65.s:posMul` | `posMul` | demo3 43994, demo1 27798, demo2 20534, newgame 2932, tour 2288 |
| `p_map65.s:sectorFloor` | `sectorFloor` | demo3 22904, demo1 19496, demo2 8981, newgame 592, tour 70 |
| `p_map65.s:baseFloor` | `baseFloor` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_map65.s:baseFloorL` | `baseFloorL` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_map65.s:baseLite` | `baseLite` | demo3 26245, demo1 21665, demo2 9102, newgame 592, tour 70 |
| `p_map65.s:P_BlockLinesIterator` | `P_BlockLinesIterator` | demo3 794, demo1 4900, demo2 5478, newgame 147, tour 0 |
| `p_map65.s:P_BlockThingsIterator` | `P_BlockThingsIterator` | demo3 0, demo1 9, demo2 27, newgame 0, tour 0 |
| `p_map65.s:blockRange` | `blockRange` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_map65.s:argLine4`, `p_map65.s:box1`, `p_map65.s:box2`, `p_map65.s:posPub`, `p_map65.s:walk1`, `p_map65.s:walk2`, `p_map65.s:callLN`, `p_map65.s:callLN2`.

### The native interfaces (what the later parts call)

Every entry is `FCALL`ed by its name; `GA_*` are never written by a `geom` routine (a caller's arguments survive the call); the results upstream leaves in `p_map65.s`'s near scratch are in `SB_GEOM` under the names of `geom.inc`, exported by `geom.s` (`.import GEO_OPENTOP` ...), and stay until the next call that writes them, as upstream's globals do.

| Routine | In | Out |
| --- | --- | --- |
| `P_PointOnLineSide` | `GA_X`, `GA_Y` (fixed_t), the line in A:X | A = 0 or 1 |
| `posMul` | V in `M_A`..`M_A+2` (signed 24 bits), F in `M_B`..`M_B+1` (signed) | `M_R` = the low 32 bits of V F |
| `P_BoxOnLineSide` | the box in `GA_0`..`GA_15` (top, bottom, left, right: upstream's order), the line in A:X | A = 0, 1, or `$FF` (crosses) |
| `P_LineOpening` | the line in A:X | `GEO_OPENTOP`, `GEO_OPENBOT`, `GEO_OPENRANGE` (one-sided: `GEO_OPENRANGE` 0 only, as upstream) |
| `P_LineOpeningXY` | sector A (upstream's X), sector X (upstream's Y) | the same |
| `pointSector` | `GA_X`, `GA_Y` (upstream's `tmx`, `tmy`) | A = `GEO_SEC` (upstream's `MV_SEC`), `GEO_SS` (`MV_SS`) |
| `sectorFloor` | the same | the same, and `GEO_TMFLOORZ` = `GEO_TMDROPZ` = the floor, `GEO_TMCEILZ` the ceiling |
| `baseLite` | none | `GEO_NSPEC` 0 (`numspechit`), `validcount` + 1 (`gv_inc`), `G_CEILLINE` none |
| `baseFloor`, `baseFloorL` | as `sectorFloor` | `sectorFloor`'s, then `baseLite`'s |
| `blockRange` | the box in `GA_0`..`GA_15`, the growth (whole units) in `GA_16`..`GA_17` | C set: no block; else `GEO_BXL`, `GEO_BXH`, `GEO_BYL`, `GEO_BYH` (bytes) |
| `P_BlockLinesIterator`, `P_BlockThingsIterator` | the block x in `GA_0`..`GA_1`, y in `GA_2`..`GA_3` (signed words), the callback's `ITTAB` number in `GA_4` | A = 1 (all done, or off the map), 0 (the callback said stop) |

**`ITTAB`'s callback convention** (this part's mechanism, GAME.md 2.2): the callback gets the line's or the mobj's handle in `GA_0`..`GA_1` and returns C set to go on, clear to stop (upstream's non-zero and zero). It may run any game logic (this iterator included): the walk keeps its state on the stack across it, as upstream keeps `LS`, `LN` and the list position there [R `p_map65.s:2691-2694`], and fetches the block list's window again after it. `PIT_AddLineIntercepts` (`tracel`), `PIT_AvoidDropoff` (`chasemove`), `PIT_RadiusAttack` (`look`), `stompThing` (`teleport`) follow it.

## 2. Requests

Each: what, why (the evidence), what it changes for other parts. All are for the integrator; none is applied by the part.

**R1. `grec.s`: the recording callback takes its handle from `GA_0`..`GA_1`.** `gt_record_it` takes A:X [R `src/native/game/grec.s:7`, `:28-30`], but a `DCALL` cannot pass A:X: `dc_call` jumps to a core entry with A = the entry's group and X the table's low byte, and `fc_go` loads A with the entry's number [R `src/native/gcall.s:147-172`, `:84-102`]. Exact change in `src/native/game/grec.s`, replacing the two lines after `gt_record_it:`:

```
gt_record_it:
        lda GA_0                ; the handle (ITTAB's convention: GA_0..1)
        sta rec_v
        lda GA_1
        sta rec_v+1
```

and the header line `;   gt_record_it    an iterator's callback: A:X the line or mobj handle;` becomes `;   gt_record_it    an iterator's callback: GA_0..1 the line or mobj handle;`. Effect: only the harness; `geom`'s local stand-in (the `TESTBUILD` branch of `giter.s`'s `ITCALL` and `GEO_ITHARNESS = 5`, which call `gt_record_it` directly with A:X for `ITTAB`'s harness entry) is then removed and every callback goes through `DCALL`. Also add to `src/native/game/README.md` after the `DCALL` paragraph: "`ITTAB`'s callbacks get the line or mobj handle in `GA_0`..`GA_1` and return C set to go on, clear to stop (part `geom`)."

**R2. `gobj.s`: a fetch of a block's blocklink, `bk_get`.** `P_BlockThingsIterator` needs the head of a block's mobj list (LVG1's blocklinks at `G_BLINKSAT` [R `src/native/gpos.s:318-336`]), which no API call gives (`bl_get` reads LVG2's blockmap). Until then `giter.s` reads it with `g_get` in one marked place (`@head`, the grep check accepts it: LVG1 with `G_BLINKSAT` named). Exact addition to `src/native/gobj.s` (export `bk_get`), after `bl_get`:

```
; bk_get: A:X = the first mobj of block A:X's list (LVG1's blocklink at
; G_BLINKSAT + 2 n; $FFFF none)
bk_get:
        sta GO_P
        txa
        asl GO_P
        rol a
        tax
        clc
        lda GO_P
        adc G_BLINKSAT
        sta FA_SRC
        txa
        adc G_BLINKSAT+1
        sta FA_SRC+1
        lda #2
        sta FA_N
        ldx #<GO_P
        ldy #>GO_P
        lda #LVG1
        jsr fetch_to
        lda GO_P
        ldx GO_P+1
        rts
```

Effect: `giter.s` calls `bk_get` and drops its `g_get`; `mobjstate` (`mvBlock`, the block list's head on removal) can use it too.

**R3. Shared names for `p_map65.s`'s near scratch read across parts.** `tmfloorz`, `tmceilingz`, `tmdropoffz` (written by `sectorFloor`, changed by `checkpos`'s walk, read by `trymove`), `MV_SS`, `MV_SEC` (written by `pointSector`, read by `P_TryMove` after `checkPos`'s walks [R `p_map65.s:475-512`]), `numspechit` (`baseLite`, `checkpos`), `opentop`, `openbottom`, `openrange` (`geom`, read by `attack`, `xymove`, `player`, `pspr`), `blockRange`'s bounds (`teleport`). They are upstream's tic scratch, shared by several parts, not one part's private bytes. Request: a block of tic scratch in `glayout.py`, never overlaid, e.g. in `GW`'s 457 free bytes (4.1): add to `glayout.py` after `SCRATCH_REQUESTS`:

```
# p_map65.s's near scratch that several parts read (docs/game-parts/geom.md
# R3): one place each, never overlaid
MAP_SCRATCH = [('GM_OPENTOP', 4), ('GM_OPENBOT', 4), ('GM_OPENRANGE', 4),
               ('GM_TMFLOORZ', 4), ('GM_TMCEILZ', 4), ('GM_TMDROPZ', 4),
               ('GM_SS', 2), ('GM_SEC', 1), ('GM_NSPEC', 1),
               ('GM_BXL', 1), ('GM_BXH', 1), ('GM_BYL', 1), ('GM_BYH', 1)]
```

with the allocation in `GW` and the names in `ggame.inc`. Until then `geom.inc` defines them in `SB_GEOM` as `GEO_*` (local stand-in, marked), exported by `geom.s`; with R3 `geom.inc` becomes `GEO_OPENTOP = GM_OPENTOP` and so on, and `SB_GEOM` is free.

**R4 (the minimum if R3 is refused). `SB_GEOM` never shared.** Its bytes are results read by callers after the return, while other parts' routines run (`MV_SS` across `checkPos`'s walks, which reach `damage`, `pickup`, `spawn`): an overlay chosen by "no routine of one active while one of the other is" (4.4) would let a part that is not active with `geom` overwrite them. Exact change in `glayout.py`'s `scratch_blocks`: before `def scratch_blocks` add `SCRATCH_NO_SHARE = {'geom'}  # (geom.md R4)`, and the clash condition becomes `(conflicts is None or name in SCRATCH_NO_SHARE or q in SCRATCH_NO_SHARE or (name, q) in conflicts or (q, name) in conflicts)`.

**R5. `gameroutine.py`: the forms `geom`'s `args.json` needs, the stray-write check and the timing.** `gameroutine.run_case` reads registers, `dp:`, `abs:`, `s:` sources, `as: mobj`, and `a`/`x`/`y`/`ax`/`main:` outputs [R `tools/native/gameroutine.py:333-406`]. `geom`'s entries take lines, sectors, subsectors and a callback by pointer, a box by pointer, `posMul`'s factor through `[WK_LN],Y`, and return in the scratch block and in C. `geom_check.py` (`run_native`, `convert_in`, `compare_outputs`) implements: sources `deref:dp:SYM:LEN`, `derefy:dp:SYM:LEN`, `c`; conversions `line`, `sector`, `subsector`, `sector_dbr`, `ittab`, `sbyte`, `zbyte`; places `geo:NAME`, `math:NAME[+N]`, `c`; `when: c_clear`; `check: unchanged`; each `geo:` output seeded with upstream's value at the entry; and in routine mode, which `gameroutine.py` has neither of: the stray-write check (a2vm's write log from the driver's `call_entry` to its end, the flush included; allowed: zero page, stack, `BL_BUF`, the caches, the runtime's state, the globals, `G_VALID`, the stops, W's scratch, slots, `GW` and planes, the manifest's banks, `MOBJP`, `GTEST`, the far layer's switches) and the call's time (the write log's clock from `call_entry` to the store of `dg_ra`). Request: fold them into `gameroutine.run_case` so the integrator's reruns use one harness. Effect: other parts can declare such entries; existing `args.json` files are unchanged.

**R6. `grun.run`: the entry's group by its placement, not by its address.** `grun.run` takes the first group whose segment holds the entry's address [R `tools/native/grun.py:299-306`], but every group of a slot starts at the slot's address: `P_LineOpening` (group 16, `$9C00`) ran group 14's `baseFloor`, which happens to sit at `$9C00` too (found by this part's first run: `validcount` + 1 and `tmfloorz` written by `P_LineOpening`). Every part whose entry is paged is hit. Exact change: replace lines 302-304 by

```
        if GL.WR['SLOT1'][0] <= addr < GL.WR['SLOT2'][1]:
            m = re.search(r'^GP_%s_G = (\d+)$' % re.escape(entry),
                          (img.b.obj / 'gen' / 'gplace.inc').read_text(),
                          re.M)
            grp = int(m.group(1)) if m else 0
```

(with `import re`). Until then `geom_check.run_entry` pokes `dg_entry` and `dg_grp` itself and calls `grun.run` with no entry.

**R7. `jsr` to the core's helpers and the math.** `pointSector` calls `gp_pointsub` (`R_PointInSubsector`, milestone 9) and `baseLite` calls `gv_inc` (`validcount`), both core routines without an `FCALL` name (no `GP_*_G` symbol: `FCALL gp_pointsub` does not assemble), and `posMul` and the iterators call the math (`mul32`, `mul8`). `geom` calls them with `jsr` (the core and the math are always resident), as `gpos.s` does. Request: say so in `src/native/game/README.md`'s "Calls: FCALL and DCALL", e.g. "The game core's helpers that have no part name (`gp_pointsub`, `gv_inc`, `mo_get` and the API) and milestone 6's math (`mul32`, `mul8`, ...) are always resident: call them with `jsr`." — or give `gp_pointsub` a play name `R_PointInSubsector` in `glayout.CORE` for `FCALL`.

**R8. Placement: keep `geom`'s callers and callees together.** In the skeleton's placement `P_LineOpening` (group 16) and `P_LineOpeningXY` (group 6) share slot 1, as `sectorFloor`/`posMul`/`baseLite` (group 24) and `pointSector` (group 19) and `baseFloor` (14) share slots, and `posMul` (24) is apart from `P_PointOnLineSide` (core): each such call reloads a slot twice (the measured cycles of section 3 include these loads: `P_LineOpening` about 20,000 cycles, of which the loads are most). Request for `gplace.py --write` with the measured sizes (section 3): `P_LineOpening` with `P_LineOpeningXY`; `sectorFloor`, `pointSector`, `baseLite`, `baseFloor`, `baseFloorL` in one group; `posMul` with `P_PointOnLineSide` (the core: 27 B).

**R9. GAME.md 2.4: `_g_lowfloor` is not an output.** Upstream never stores it: "`_g_lowfloor: .space 4 ; (not stored: no code reads it)`" [R `p_map65.s:298`], and `openXY` keeps no lower floor [R `p_map65.s:2410-2449`]. The native keeps none; `args.json` checks that upstream leaves it unchanged (`check: unchanged`, true in every case run). The planted bug "lowfloor as the higher floor" is planted as the floors' order turned round (`bmi` for `bpl`: openbottom the lower floor), and the captured `P_LineOpening` calls catch it through `openbottom`/`openrange`. Request: GAME.md 2.4's "Inputs and outputs" and row `geom` say so.

**R10. The survey misses `PIT_RadiusAttack` under `P_BlockThingsIterator`.** The survey's reached targets of `P_BlockThingsIterator` are empty in demo1 and demo2, while `PIT_RadiusAttack` is called 5 and 21 times there (`target_calls`): every one of those calls looks eligible though its callback (`look`'s, wave 3) is not built. `geom_check.py` classifies such a call as "waiting" only when the native stops at that `ITTAB` entry (`GS_UNBUILTD`, the entry's number) and the reference ran a callback (a block with things or unstamped lines); it never counts as equal. Request: the integrator's survey attributes `JML [LN]` dispatches of `callLN2` to their iterator call (`gamecap.py`'s passes), so eligibility is right for `look`'s rerun.

**R11 (optional, timing). `bl_get`'s window known.** `P_BlockLinesIterator` reads its list in `bl_get`'s 256-byte window and must fetch it again after every callback (a callback may fetch). A byte `BL_AT` (the word `bl_get` last fetched, `$FFFF` after anything else writes `BL_BUF`) would let the walk keep the window; a gain of one 256-byte far read per line given to a callback. For the integrator's timing report.

**R12. `tools/testpar.py`: a time limit for this part's test module.** `tests/test_native_game_geom.py` runs every case (2,893) from both fills, the iterators' 434 cases with the recording callback, 1.8 million random pairs and the four plants: 2,164 s at its default of 2 processes (`GEOM_JOBS`), past the runner's 1,200 s. Exact change: `MODULE_TIMEOUTS: Dict[str, float] = {'test_native_game_skeleton': 3600.0, 'test_native_game_geom': 3600.0}` with the reason "every case of part geom, 2,164 s at 2 processes"; or the integrator sets `GEOM_JOBS` higher (its runs are spread over them; measured only at 2). Effect: none on other modules.

## 3. Results

Built and checked 2026-10-01 on a2vm and ref816; nothing committed. The full run: `python3 tools/native/gparts/geom_check.py --run --iter --rand --report` (1 h 32 min at 2 jobs), after `--select --capture --synth`; `build/native/game/geom/report.json`: **0 failures**.

**The cases.** The selection (`select.json`): for each entry 300 calls spread evenly over the survey's calls of demo3, demo1, demo2, newgame and tour (every call when there are fewer: `P_BoxOnLineSide` 40, `P_BlockThingsIterator` 34; the last call of a run left out), eligible ones only (`P_BlockLinesIterator`: 323 of 11,315 calls reached no callback, so 300 of those, and 100 of the others for the recording runs); captured into the part's own case directory (2,577 cases, `gamecap.capture`, 13 min). The synthetic cases (`--synth`, 336, each a real case's state with pokes run alone on ref816 by `--call`): every path of `PATHS` no chosen call takes (the side test's three line kinds with the point on, below and above the axis or line; each slope type of `P_BoxOnLineSide` with a box on each side, across, and with an edge on the line's whole unit; the floors' and ceilings' orders and a one-sided line of the openings; the operand classes of `posMul`; `ceilingline` set and not; the iterators off each edge of the map), and all the cases of the three entries no run calls (`baseFloor`, `baseFloorL`: 16 each from `sectorFloor`'s cases of every run, some with `ceilingline` set; `blockRange`: 96, boxes inside, off each side, across each edge, the whole map, fractions, growth 0 and 32). Every declared path is taken by a run case (the iterators' "lines" and "stop" by their recording runs).

**Each case four times**: from `$A5` and `$5A`, each under f121 and fastpath; the canonical state after the call equal to ref816's (routine mode, R1-R6 only), every declared output equal, no stray write, the time and the lowest S recorded.

| Entry | Survey calls | Cases (synthetic) | Runs | Failed | Cycles median / worst | f121 µs median / worst | fastpath µs median / worst | Lowest S | Bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `P_PointOnLineSide` | 81,326 | 315 (15) | 1,260 | 0 | 1,537 / 8,763 | 40.0 / 176.9 | 24.2 / 136.8 | $E6 | 249 |
| `P_BoxOnLineSide` | 40 | 80 (40) | 320 | 0 | 16,523 / 25,697 | 342.8 / 510.7 | 253.5 / 397.4 | $DA | 257 |
| `P_LineOpening` | 2,665 | 307 (7) | 1,228 | 0 | 20,407 / 20,441 | 427.2 / 428.2 | 313.1 / 313.7 | $E1 | 44 |
| `P_LineOpeningXY` | 6,106 | 306 (6) | 1,224 | 0 | 8,797 / 8,820 | 184.1 / 184.4 | 134.7 / 135.0 | $E6 | 150 |
| `pointSector` | 52,557 | 300 | 1,200 | 0 | 13,628 / 20,718 | 305.5 / 455.2 | 213.1 / 325.8 | $E4 | 36 |
| `posMul` | 97,541 | 426 (126) | 1,704 | 0 (64 undecodable) | 5,723 / 5,995 | 112.8 / 117.2 | 88.4 / 92.8 | $E8 | 27 |
| `sectorFloor` | 52,038 | 300 | 1,200 | 0 | 20,605 / 28,776 | 454.2 / 632.4 | 319.5 / 449.8 | $DF | 42 |
| `baseFloor` | 0 | 16 (16) | 64 | 0 | 31,273 / 37,170 | 663.4 / 801.2 | 484.0 / 576.7 | $DA | 13 |
| `baseFloorL` | 0 | 16 (16) | 64 | 0 | 51,423 / 57,320 | 1,071.0 / 1,208.8 | 793.1 / 885.7 | $D5 | 7 |
| `baseLite` | 57,669 | 302 (2) | 1,208 | 0 | 5,173 / 5,178 | 104.0 / 104.1 | 79.6 / 79.6 | $E8 | 15 |
| `P_BlockLinesIterator` | 11,315 | 306 (6) | 1,224 | 0 | 25,500 / 28,230 | 506.7 / 585.4 | 385.5 / 432.2 | $E6 | 258 |
| `P_BlockThingsIterator` | 34 | 40 (6) | 160 | 0 (72 waiting) | 10,321 / 10,321 | 212.0 / 213.0 | 159.0 / 159.3 | $E0 | 181 |
| `blockRange` | 0 | 96 (96) | 384 | 0 | 10,614 / 10,652 | 211.5 / 212.2 | 162.8 / 163.4 | $E8 | 224 |

Stray writes: 0 in every run. "Lowest S" is the run's (the driver starts at `$EF`): 26 B at most with the driver's frame, `baseFloorL`'s chain of three cross-group `FCALL`s. The times are from the driver's call to the routine's return, and **include the code paging the routine mode starts with**: every slot is empty at a call's start, so each paged entry loads its own group and every cross-group `FCALL` of it loads another (the skeleton's placement splits `geom` into 8 groups; request R8): `P_PointOnLineSide` (in the core) costs 1,537 cycles on an axis-aligned line and about 8,700 when it first pages `posMul` in; `P_LineOpening` is two group loads and 44 B of work. They are upper bounds for the integrator's timing report, not the cost in play.

`posMul`'s 64 undecodable runs: 16 calls made inside a setup's spawn (`P_SetThingPosition`'s walk: the mobj half spawned, as the skeleton's S2 counts them); `posMul` itself is also checked by the 100,000 random inputs. `P_BlockThingsIterator`'s 72 waiting runs: 18 calls whose reference ran `PIT_RadiusAttack` (`look`, wave 3), which the survey does not record (R10); the native stops at that `ITTAB` entry (`GS_UNBUILTD`, entry 3), as it must; their blocks are checked by the recording runs.

**The iterators with the recording callback** (`--iter`): every captured call of both iterators (400 and 34 cases), with the reference's callback replaced by a recorder poked into bank `$7C` and the native's by `ITTAB`'s harness entry, both fills and both profiles; one in five also stopped at its first and its second callback: 2,432 runs, 0 failed, the 407 callbacks of a pass (375 lines, 32 mobjs; 1,628 over the four combinations) recorded in the same order with the same lines and mobjs, the line stamps and `validcount` equal, 696 stopped runs.

**The random checks** (`--rand`, 100,000 each, upstream's routines run by `mathref batch` on the map's setup RAM, the native in `geomt.s` on the map's level base): point-line pairs (30% anywhere near the map, 25% near the segment, 15% exactly on the line, 12% a vertex's neighbours, 10% the extremes, 8% any 32 bits; every path of the side test; 13-16% of them exactly on an axis or a line: `dx0-eq`, `dy0-eq`, `gen-eq`) and box-line pairs (a thing's box near the line, edges on v1's whole units, boxes in the map, the extremes, any 32 bits; every slope type and answer), on each of E1M1-E1M9: 900,000 point-line and 900,000 box-line pairs, 0 failed. `posMul`: 100,000 inputs (the 70 pairs of edge values first: 0, ±1, the extremes of 24 and 16 bits), 0 failed, each also equal to the low 32 bits of the signed product.

**The planted bugs** (`tests/test_native_game_geom.py`, each in a scratch copy, the image built from it): an on-the-line point given the other side (pairs on E1M1: caught); `P_BoxOnLineSide`'s horizontal case on the top edge (pairs on E1M1: caught); a block list read from its first entry (the recording runs: caught); `P_LineOpening`'s lowfloor as the higher floor (captured `P_LineOpening` calls: caught on `_g_openbottom`).

**Sizes** (the part's image's map): `geom.s` 1,064 B, `giter.s` 439 B: **1,503 of 2,200 B** (upstream 1,707 B), under budget; the test driver `geomt.s` 252 B (test builds only). The scratch block: 32 of 32 B.

**The test module** (`python3 -m unittest tests.test_native_game_geom`): 10 tests, all passing (the build, the checkpoint at two runs a case, the recording runs, the random pairs and `posMul`, the four plants); 2,164 s at 2 processes. Its first run found two of its own assertion errors (case names repeat across runs; a callback count fixed for four runs a case) and a third on the next (an undecodable case has no stray count); each fixed and its test rerun passing.

**`build/` growth**: `build/native/game/geom/` 86 MB (the cases 77 MB with the five runs' bases, the part's image 9 MB); every temporary directory (`build/tmp-geom-*`) deleted.

## 4. Open points

1. The requests R1-R11 above wait for the integrator; until then the local stand-ins are marked in `giter.s` (R1, R2) and `geom.inc` (R3).
2. The survey's eligibility of `P_BlockThingsIterator` (R10): the 18 calls that ran `PIT_RadiusAttack` are checked as "waiting" only; they become checkpoint cases when `look` is built and the survey is fixed.
3. The timing includes the code paging of the skeleton's placement (R8); the routine-mode numbers are not the cost in play.
4. `P_BlockLinesIterator` and `P_BlockThingsIterator` assume a blockmap under 256 blocks wide and high (`mul8` on the bytes of `G_BMW`, `GA_2`), true of every E1 map (52 x 56 blocks at most, E1M8 [M: the tour's setup RAMs]); `P_BlockLinesIterator` reads `G_BMW`'s two bytes for the range test; a wider map would need a 16-bit product.
5. The test module runs every case from both fills under one profile each (A5 under f121, 5A under fastpath); the tool's `--run` makes the four runs a case of `report.json`. It takes 2,164 s at 2 processes (R12).

## 5. The integration of wave 1 (2026-10-01)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 1 as integrated").

| Request | Decision |
| --- | --- |
| R1 `grec.s` from `GA_0`..`GA_1` | **Accepted**: `gt_record_it` takes `GA_0`..`GA_1`; `giter.s`'s `ITCALL` stand-in is gone (every callback through `DCALL ITTAB`); the README states `ITTAB`'s convention |
| R2 `bk_get` | **Accepted** (with `mobjstate`'s R2): `gobj.s` `bk_get` (A:X and `API_W`), `bk_put`; `giter.s`'s `g_get` is gone |
| R3 shared map scratch | **Accepted**: `glayout.TIC_GW_FIELDS` `GM_OPENTOP` .. `GM_BYH` in GW after llayout's fields (never overlaid; `ggame.inc`); `geom.inc`'s `GEO_*` are those names; `SB_GEOM` is unused |
| R4 `SB_GEOM` never shared | Not needed: R3 moves the results out of the scratch block |
| R5 the harness forms in `gameroutine.py` | **Accepted in part**: shared now are the entry's group from the placement (R6), the math tables in every image, `grun.routine_sizes`/`module_bytes`; the `args.json` forms (`deref:`, `geo:`, `sbyte` ...), the stray-write check and the call's time stay in `geom_check.py`, the part's harness, which the integration reruns (folding the five wave-1 harnesses into one is an open item of GAME.md "Wave 1 as integrated") |
| R6 `grun.run`'s group | **Accepted**: `grun.entry_group` (the build's `gplace.inc`); a slot address with no group is an error |
| R7 `jsr` to the core's helpers | **Accepted**: the README names them (`gp_pointsub`, `gv_inc`, the API, `g_random`, the hooks, the math) |
| R8 placement | **Accepted**: `gplace.AFFINITY` keeps `P_LineOpening`+`P_LineOpeningXY`, `sectorFloor`+`pointSector`+`baseLite`+`baseFloor`+`baseFloorL`, and `P_PointOnLineSide`+`posMul` each in one group (or the core) |
| R9 `_g_lowfloor` | **Accepted**: GAME.md 2.4's "Inputs and outputs" and row `geom` say so |
| R10 the survey's `callLN2` targets | **Accepted**: `gamecap.passes` never puts an entry in the pass of an entry that reaches it (a JML-entered target logged with its return named its dispatcher's caller); the survey is remade |
| R11 `bl_get`'s window | Not now: a timing lever for the timing report (GAME.md 5.4) |
| R12 the module's time limit | **Accepted**: `tools/testpar.py` `MODULE_TIMEOUTS['test_native_game_geom'] = 3600` |

Rerun at the integration (`geom_check.py --run --iter --rand --report --jobs 2`, the five parts linked, the new placement): 11,240 runs, 0 failed, 0 stray writes (64 `posMul` undecodable, 72 `P_BlockThingsIterator` runs waiting for `PIT_RadiusAttack`, which the remade survey now attributes: 3 calls in DEMO1, 16 in DEMO2); the recording callback 2,432 runs, 0 failed; the random pairs and `posMul` 0 failed; the test module 10 tests OK (2,377 s). Size 1,441 B.

## 6. The integration of wave 3 (2026-10-02)

`PIT_RadiusAttack` (part `look`) is built, so `P_BlockThingsIterator`'s calls with it run it whole: `geom_check.CALLBACK_CONTEXT` seeds the callback's context that its caller leaves in scratch (bombspot, bombsource, bombdamage: upstream's `AT_BSPOT`, `AT_BSOURCE`, `AT_BDAMAGE` into look's `LK_BSPOT`, `LK_BSRC`, `LK_BDMG`, offsets read from `look.inc`), and the stray rule allows P_Random's index (`P_DamageMobj`). The 80 `P_BlockThingsIterator` runs are equal.
