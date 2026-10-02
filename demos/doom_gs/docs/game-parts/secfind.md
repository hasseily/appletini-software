# Part `secfind` (wave 1)

The record of milestone 10's part `secfind` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 1; upstream 1363 B, native budget 1800 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 1's `secfind` (2026-10-01).
- Files: `src/native/game/secfind/*.s`, `src/native/game/secfind/part.mk`, `src/native/game/secfind/args.json`, `tests/test_native_game_secfind.py`, this file; tools (if any) `tools/native/gparts/secfind*.py`; build output `build/native/game/secfind/` (`make -s -C src/native -f game.mk part P=secfind ROOT=$PWD`).
- Its scratch block: `SB_SECFIND` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_spec65.s`: `getNextSector:66`, `P_FindLowestFloorSurrounding:123`, `P_FindHighestFloorSurrounding:134`, `P_FindLowestCeilingSurrounding:141`, `P_FindSectorFromLineTag:250`, `P_CheckTag:287`, `P_UpdateSpecials:308` (animated textures into `TEXTRANS`, `P_UpdateAnimatedFlat`'s `NUKAGE` [R `r_data65.s:681-688`], the buttons), `T_Scroll:559`; `p_floor65.s`: `P_FindNextHighestFloor:694`; `p_lights65.s`: `T_LightFlash:58`, `T_StrobeFlash:95`, `T_Glow:130`, `EV_LightTurnOn:439`; helpers `sideSector`, `secArg`, `lineOf`, `buttonDone`, `mod3`, `nextOther`, `aboveCurrent`, `ltSector`, `nextSector`

Its checkpoint (GAME.md 2.4): Every thinker call of the light and scroll kinds; `P_UpdateSpecials` once a tic (with `TEXTRANS` and `NUKAGE` compared); the finders through `--call` on every sector of the nine maps; synthetic: leveltime 32,768 and above (upstream's unsigned shift [R `r_data65.s:682-686`]), a button's timer ending

Its planted bugs (each must fail the named check): the tag search restarting at 0 (finders); `T_Glow` turning one step late (thinker calls); `NUKAGE` with a signed shift (the synthetic leveltime); the button restoring the other texture

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_spec65.s:getNextSector` | `getNextSector` | demo3 209, demo1 1576, demo2 200, newgame 34, tour 879 |
| `p_spec65.s:P_FindLowestFloorSurrounding` | `P_FindLowestFloorSurrounding` | demo3 6, demo1 0, demo2 4, newgame 0, tour 0 |
| `p_spec65.s:P_FindHighestFloorSurrounding` | `P_FindHighestFloorSurrounding` | demo3 1, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_spec65.s:P_FindLowestCeilingSurrounding` | `P_FindLowestCeilingSurrounding` | demo3 6, demo1 8, demo2 4, newgame 1, tour 0 |
| `p_spec65.s:P_FindSectorFromLineTag` | `P_FindSectorFromLineTag` | demo3 22, demo1 2, demo2 9, newgame 0, tour 0 |
| `p_spec65.s:P_CheckTag` | `P_CheckTag` | demo3 586, demo1 80, demo2 11, newgame 3, tour 0 |
| `p_spec65.s:P_UpdateSpecials` | `P_UpdateSpecials` | demo3 2135, demo1 5026, demo2 3836, newgame 513, tour 428 |
| `p_spec65.s:T_Scroll` | `T_Scroll` | demo3 8540, demo1 0, demo2 0, newgame 4104, tour 564 |
| `p_floor65.s:P_FindNextHighestFloor` | `P_FindNextHighestFloor` | demo3 0, demo1 1, demo2 0, newgame 0, tour 0 |
| `p_lights65.s:T_LightFlash` | `T_LightFlash` | demo3 4270, demo1 10052, demo2 30688, newgame 513, tour 1360 |
| `p_lights65.s:T_StrobeFlash` | `T_StrobeFlash` | demo3 14945, demo1 20104, demo2 0, newgame 513, tour 1378 |
| `p_lights65.s:T_Glow` | `T_Glow` | demo3 14945, demo1 40208, demo2 15344, newgame 1026, tour 2214 |
| `p_lights65.s:EV_LightTurnOn` | `EV_LightTurnOn` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_lights65.s:secArg`, `p_lights65.s:ltSector`, `p_lights65.s:nextSector`, `p_spec65.s:sideSector`, `p_spec65.s:secArg`, `p_spec65.s:lineOf`, `p_spec65.s:buttonDone`, `p_spec65.s:mod3`, `p_floor65.s:nextOther`, `p_floor65.s:aboveCurrent`, `p_switch65.s:lnLight`, `?:P_UpdateAnimatedFlat`.

### 1.1 What the part built (2026-10-01)

| File | What |
| --- | --- |
| `src/native/game/secfind/secfind.s` | The part's routines (below), a GPL-2 derivative of upstream's `p_spec65.s`, `p_lights65.s`, `p_floor65.s` (`P_FindNextHighestFloor`), `r_data65.s` (`P_UpdateAnimatedFlat`) and `p_switch65.s` (`lnLight`); the stand-ins of requests 1-3 and 5, marked `STAND-IN` |
| `src/native/game/secfind/sftest.s` | Test builds only (`TESTBUILD`): `sf_t_mod3`, mod3 of 16,384 words into main `$2000-$5FFF` (the exhaustive check of the arithmetic helper); empty in the release |
| `src/native/game/secfind/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (request 6 for `as` kinds and `zp:` outputs) |
| `tools/native/gparts/secfind.py` | The part's checkpoint: the thinker logs (`--log`), the captures (`--capture`), the synthetic calls (`--synthetic`), the routine-mode runs (`--check`), `--mod3`, `--plants`, `report.json` |
| `tests/test_native_game_secfind.py` | A sample of the checkpoint, the stand-ins' constants, mod3 on every input, the five planted bugs |

The native interfaces (`secfind.s`'s header; other parts call them so):

| Routine | Group (placement) | In | Out |
| --- | ---: | --- | --- |
| `getNextSector` | 5 | A:X a line, Y a sector | A the other sector, `$FF` none |
| `nextSector` (`p_lights65.s:nextSector`) | 15 | A a sector, X:Y i | X 1 past its lines; else X 0, A = getNextSector(its line i) (request 11: not the carry) |
| `P_FindLowestFloorSurrounding`, `P_FindHighestFloorSurrounding`, `P_FindLowestCeilingSurrounding`, `P_FindNextHighestFloor` | 15, 5, 6, 15 | A a sector | `GA_0-3` the height (fixed_t) |
| `around` (`p_spec65.s:around`, request 4) | 15 (`nextSector`'s) | `SB_SEC`, `SB_MODE`, `SB_BEST` | `GA_0-3` |
| `P_FindSectorFromLineTag` | 13 | A:X a line, Y start (`$FF` -1) | A the sector, `$FF` none |
| `P_CheckTag` | 4 | A:X a line | A 1 or 0 |
| `P_UpdateSpecials` | 24 | | `NUKAGE`, `TEXTRANS`, the switch timers |
| `P_UpdateAnimatedFlat`, `mod3`, `buttonDone` | 3 | -; A:X a word -> A % 3; A a button's offset | |
| `T_Scroll`, `T_LightFlash`, `T_StrobeFlash`, `T_Glow` (THTAB) | core, 10, 22, 16 | `GA_0-1` the thinker (request 8) | |
| `EV_LightTurnOn` | 20 | A:X a line, Y bright | |
| `lnLight` (LSTAB) | 15 | `GA_0-1` the line, `GA_2` the argument (request 8) | A = 1 |

The helpers, keyed `file:label` with their upstream lines:
`p_spec65.s:sideSector:88`, `p_spec65.s:secArg:216`, `p_spec65.s:lineOf:224`
(done in place: `nextSector`), `p_spec65.s:around:151` (a routine of its
own, request 4), `p_spec65.s:buttonDone:372`, `p_spec65.s:mod3:417`
(routines); `p_lights65.s:ltSector:183`, `p_lights65.s:secArg:230` (in
place: the macro `LT_SEC`), `p_lights65.s:nextSector:238` (a routine);
`p_floor65.s:nextOther:751`, `p_floor65.s:aboveCurrent:796` (in place:
`P_FindNextHighestFloor`); `p_switch65.s:lnLight:512` (LSTAB's entry);
`r_data65.s:P_UpdateAnimatedFlat:681` (keyed `?:P_UpdateAnimatedFlat` in
the part table). `p_floor65.s:secArg:319` is `planes`', not this part's.

Arithmetic: upstream's `mod3` (`p_spec65.s:417`, through `umul16`) is
mirrored by a native `mod3` of its own (the bytes add, 256 being 1 mod 3,
then the nibbles); `P_UpdateAnimatedFlat`'s `% 3` (upstream's `_Mod16` of
the runtime, on 0-8,191) goes through the same `mod3`, which gives the
same result for every word. No other product or divide.

Light levels are the sectors' render records' bytes: upstream's 16-bit
signed compares of a light with another light are unsigned byte compares,
those with a special's word (`minlight`, `maxlight`) stay 16-bit signed
(T_Glow computes `light ± GLOWSPEED` in 16 bits and stores the byte only
when it keeps it, as upstream's final value).

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The
part goes on with a local stand-in, marked `STAND-IN` in
`src/native/game/secfind/secfind.s`, where it can.

### Request 1: the sides in the object API (`sd_get`, `sd_put`)

**What.** Two calls of `gobj.s` and their two places:

    ; sd_get: SD_BUF = the record of side A:X (LVMAP SIDEBASE + 8 n)
    ; sd_put: SD_BUF back to the side last got (sides are written rarely:
    ; the switches' textures, the scrollers; no cache)
    sd_get:
            sta SD_AT
            txa
            asl SD_AT
            rol a
            asl SD_AT
            rol a
            asl SD_AT
            rol a
            clc
            adc #>SIDEBASE
            sta SD_AT+1
            sta FA_SRC+1
            lda SD_AT
            sta FA_SRC
            ldx #<SD_BUF
            ldy #>SD_BUF
            lda #SIDE_SIZE
            sta FA_N
            lda #LVMAP
            jmp fetch_to
            .assert <SIDEBASE = 0 && SIDE_SIZE = 8, error, "a side"
    sd_put:
            lda SD_AT
            sta FA_DST
            lda SD_AT+1
            sta FA_DST+1
            lda #<SD_BUF
            sta FA_SRC
            lda #>SD_BUF
            sta FA_SRC+1
            lda #SIDE_SIZE
            sta FA_N
            lda #LVMAP
            sta FA_BANK
            jmp far_put

with `.export sd_get, sd_put` in `gobj.s`, and in `tools/native/llayout.py`
`GW_FIELDS` the two places `('SD_BUF', R.SIDE_SIZE), ('SD_AT', 2)` (exported
to `lgame.inc` as the other `GW_FIELDS` are: `('SD_BUF', GWA['SD_BUF']),
('SD_AT', GWA['SD_AT'])` in the list beside `('SG_BUF', ...)`).

**Why.** `buttonDone` writes a texture of a side [R `p_spec65.s:384-397`]
and `T_Scroll` a side's texture offset [R `p_spec65.s:559-575`]; the API
has no call that reaches a side (`gobj.s`: mobjs, sectors, lines,
specials, nodes, segs, subsectors, block lists), and the sides are in
`LVMAP`, a cached kind's bank for `gameroutine.grep_check`.

**Stand-in.** The macros `SF_SD_GET`, `SF_SD_PUT` of `secfind.s`, the same
interface with `SB_SD`, `SB_SDAT` of the part's scratch block for
`SD_BUF`, `SD_AT`, through `g_get` and `g_put`. With the request applied:
`SF_SD_GET` becomes `jsr sd_get`, `SF_SD_PUT` `jsr sd_put`, `SB_SD`
`SD_BUF`, and the scratch block's last 10 bytes are free.

**Effect on other parts.** None needed; `lines` (`P_ChangeSwitchTexture`
writes the switch's texture [R `p_switch65.s:209`]) and `attack`
(`sideAddr`, `sideSectors`) can use it too.

### Request 2: a sector's line table in the object API (`lt_get`)

**What.** One call of `gobj.s`:

    ; lt_get: A:X = an entry of the line tables (LTAB: a sector's
    ; SG_LFIRST + i) -> A:X = its line (LVG1 G_LTABAT + 2 n)
    lt_get:
            sta FA_SRC
            txa
            asl FA_SRC
            rol a
            sta FA_SRC+1
            clc
            lda FA_SRC
            adc G_LTABAT
            sta FA_SRC
            lda FA_SRC+1
            adc G_LTABAT+1
            sta FA_SRC+1
            ldx #<GO_T
            ldy #>GO_T
            lda #2
            sta FA_N
            lda #LVG1
            jsr fetch_to
            lda GO_T
            ldx GO_T+1
            rts

with `.export lt_get`.

**Why.** `around` (the three `P_Find*Surrounding`), `P_FindNextHighestFloor`
and `EV_LightTurnOn` walk `sec->lines[i]` [R `p_spec65.s:224-240`
`lineOf`, `p_floor65.s:751-794` `nextOther`, `p_lights65.s:238-262`
`nextSector`]; LTAB is a level table no cache holds, which only the game
core reaches (`gspec.s` `minlight`, `g_get` of `LVG1` beside `G_LTABAT`).

**Stand-in.** The macro `SF_LT_GET` (the same interface, through
`g_get`), used once, in `nextSector`. With the request applied it
becomes `jsr lt_get`.

**Effect on other parts.** None needed; `evfloor` (the stairs and the
donut walk a sector's lines [R `p_floor65.s:1057`, `:1233`]) and
`planes` can use it.

### Request 3: `animated_texture_basepic` without a far access

**What.** In `tools/native/llayout.py`, beside `('GT_STATES', ...)`
(`:1576`): `('GT_BASEPIC', GT['BASEPIC'][0])`, so that `lgame.inc`
carries it. (Better still for the tic: a copy `G_BASEPIC` (2) in the
globals block, set by the setup's `GTABS` or `SPECIALS` step; then
`P_UpdateSpecials` reads it with no far access at all. The integrator
chooses; the manifest's `p_spec65.s:animated_texture_basepic` stays at
GTAB's place either way.)

**Why.** `P_UpdateSpecials` writes `TEXTRANS[basepic .. basepic + 2]`
once a tic [R `p_spec65.s:310-341`]; `basepic` is GTAB's
(`llayout.GT['BASEPIC']`, `gtab_at` in the manifest), whose address
`lgame.inc` does not export.

**Stand-in.** `SF_GT_BASEPIC = $456C` in `secfind.s`, read with `g_get`
of `GTAB`; `tests/test_native_game_secfind.py` (`test_stand_ins`) checks
it equals `llayout.GT['BASEPIC'][0]`. With the request: `GT_BASEPIC`
(or `G_BASEPIC` and no `g_get`).

**Effect on other parts.** None.

### Request 4: the part table's helpers (`glayout.PARTS`, secfind)

**What.** In `tools/native/glayout.py`, secfind's `helpers`: add
`'p_spec65.s:around'`; key `'?:P_UpdateAnimatedFlat'` (EXTRA_LABELS) as
`'r_data65.s:P_UpdateAnimatedFlat'` if the call graph is extended to read
`r_data65.s` (else leave it).

**Why.** Natively `around` (upstream's label `p_spec65.s:151`, a part of
`P_FindLowestCeilingSurrounding`'s head that the two other finders branch
to) is a routine of its own that the three finders `FCALL`, and they sit
in three groups (5, 6, 15 in the current placement). Until the table
names it, `secfind.s` defines `GP_around_G/_B/_N` itself (guarded by
`.ifndef GP_around_G`) with `nextSector`'s group, which it calls.

The helpers that have **no native routine** (their work is done in place,
in the routine that calls them): `p_spec65.s:sideSector`,
`p_spec65.s:secArg`, `p_spec65.s:lineOf` (in `nextSector`),
`p_lights65.s:secArg`, `p_lights65.s:ltSector` (the macro `LT_SEC`),
`p_floor65.s:nextOther`, `p_floor65.s:aboveCurrent` (in
`P_FindNextHighestFloor`). The ones that have: `p_lights65.s:nextSector`
(`nextSector`: a sector's line i's other sector, `around`,
`P_FindNextHighestFloor` and `EV_LightTurnOn` call it),
`p_spec65.s:buttonDone`, `p_spec65.s:mod3`, `p_switch65.s:lnLight`,
`?:P_UpdateAnimatedFlat`. The placement may leave the others empty.

**Effect on other parts.** None.

### Request 5: `p_lights65.s`'s equates in `ggame.inc`

**What.** In `tools/native/glayout.py` `upstream_constants()`, the loop
over the source files' own equates: add
`('p_lights65.s', ('GLOWSPEED', 'STROBEBRIGHT'))` beside
`('g_game65.s', (...))`, giving `UGLOWSPEED` and `USTROBEBRIGHT`.

**Why.** "Upstream's constants ... never typed in" (GAME.md 3.2); T_Glow
steps by GLOWSPEED and T_StrobeFlash's bright count is STROBEBRIGHT [R
`p_lights65.s:19-20`].

**Stand-in.** `U_GLOWSPEED = 8`, `U_STROBEBRIGHT = 5` in `secfind.s`,
checked against the link map by the part's test (`test_stand_ins`).

**Effect on other parts.** None.

### Request 6: the routine harness: kinds, zero-page outputs, thinkers, writes

**What** (`tools/native/gameroutine.py`, `gamecap.py`), each done locally in
`tools/native/gparts/secfind.py` (which the integrator can take as the
reference text):

1. `args.json`'s `as` for any kind the bridge classifies, not only
   `mobj`: `sector` and `line` (the native value is the canonical id),
   a special's kind (`lightflash`, `strobe`, `glow`, `scroll`, ...: the
   thinker handle through `handle_of`); NULL as all ones. Inputs and
   outputs (secfind's `native_value`, `Prep.inputs`, `outputs`).
2. An output's `native` may be `zp:NAME` (the finders return a fixed_t in
   `GA_0-3`).
3. The thinkers' calls: upstream's walk enters a thinker by `JML [FN_P]`
   from `callFn` [R `p_tick65.s:533`], which `ref816 --capture` does not
   count as a call of the thinker (only `--call-log` has `jumps=1`). The
   cases are captures of `callFn`'s hits; which hits are which thinker
   comes from a call log of `callFn` (entry and return) with the thinkers
   (entry only, `jumps=1`): each thinker's entry line names its `callFn`
   call as its parent (`secfind.py` `thinker_log`; 300 of each of the four thinkers'
   170,768 calls in the five runs).
4. The write log in routine mode: `run_case` runs a2vm with no write log,
   so "no stray write" is not checked. `secfind.py` logs `main:0000-5FFF`
   and every aux bank, and counts as stray any write after the routine's
   entry that is neither R1 (zero page, stack, W: not logged, the tic
   phase's main ranges, the stop codes, the test globals `GT_DIV0` ..
   `GT_FLAGS`, GTEST), nor a canonical byte (the bytes the native
   manifest's reader reads), nor a same-value write into a record bank (a
   write-back). The writes that change a canonical byte also tell whether
   the native state must be decoded again (if none, it is the pre-state's,
   read once a case and fill).
5. The cycles of the routine alone: snapshots at the entry's address
   (`pc ENTRY@1`) and at the driver's return from `call_entry`, under
   `--cost-timed` (fabric clocks; the run's total includes the driver's
   image load and flush).
6. The sound events (R6): `secfind.py` compares the native sound log
   (GTEST `GT_SOUNDS`, `GT_SNDLOG`) with the events upstream's call makes
   (for `P_UpdateSpecials`: one `S_StartSound2(soundorg, sfx_swtchn)` a
   switch whose timer ends, in the buttons' order).

**Why.** Without 1-3 the part's checkpoint cannot run through the shared
harness (`gameroutine.run_case` would pass a special's raw pointer bytes
as its handle); 4-6 are GAME.md 2.5's "stray writes 0", "cycles", and
3.5's R6.

**Effect on other parts.** Every dispatch target's part (`tic`,
`mobjstate`, `planes`, `movers`: THTAB; the actions of ACTTAB entered by
`JML [ACT_JMP]`) has the same capture problem as 3.

### Request 7: `grun.run`'s group of a paged entry

**What.** In `tools/native/grun.py` `run()`, the entry's group from the
placement, not from its address:

        if entry is not None:
            addr = lab[entry]
            grp = entry_group(img.b, entry)
            img.poke_word('dg_entry', addr)
            img.poke_label('dg_grp', bytes([grp]))

    def entry_group(b: RC.Build, name: str) -> int:
        """The group of a routine (its build's gen/gplace.inc)."""
        for line in (b.obj / 'gen' / 'gplace.inc').read_text().splitlines():
            f = line.split()
            if f[:2] == ['GP_%s_G' % name, '=']:
                return int(f[2])
        raise RunError('no group of %s' % name)

**Why.** `_group_has` takes the first group whose segment holds the
address, and every group of a slot starts at the slot's address: secfind's
`P_FindLowestCeilingSurrounding` (group 6) ran with group 3 in slot 1 and
returned `$0000A000` for upstream's `$00480000` (demo1's hit 1) until the
part's tool poked the right group. The skeleton's entries are in the core,
so S2 never met it.

**Effect on other parts.** Every part with a paged entry.

### Request 8: the dispatch tables' calling conventions

**What.** In `src/native/game/README.md`, "Calls: FCALL and DCALL":

> * A `THTAB` target gets the thinker's handle in `GA_0-1` (upstream's
>   `_Dp[0-3]`): `dc_call` keeps no register for it.
> * An `LSTAB` target gets the line in `GA_0-1` and spectab's argument in
>   `GA_2-3` (upstream's `_Dp[0-3]` and C); it returns its result in A
>   (upstream's C: 1 started, 0 not).

**Why.** `dc_call` clobbers A, X and Y (the number, the table), so a
target's arguments must be in memory; secfind's `T_LightFlash`,
`T_StrobeFlash`, `T_Glow`, `T_Scroll` (THTAB) and `lnLight` (LSTAB) take
them so (`args.json`).

**Effect on other parts.** `tic` (`P_RunThinkers` writes `GA_0-1` before
`DCALL THTAB`), `lines` (`findSpecial`'s callers write `GA_0-3`), and every
other target's part (`mobjstate`, `planes`, `movers`; `evworld`,
`evfloor`, `teleport`) takes the same.

### Request 9: the core's routines a part calls with `jsr`

**What.** In `src/native/game/README.md`, after "The core's routines in
play": "`g_random` (P_Random: A, changes X) and the hooks of `ghook.s`
(`S_StartSound`, `S_StartSound2`, ...) are in the core and not in the
part table: a part calls them with `jsr`."

**Why.** `FCALL` needs a routine of the table (`GP_<name>_*`); secfind
calls `g_random` (T_LightFlash's counts [R `p_lights65.s:79`, `:86`]) and
`S_StartSound2` (`buttonDone` [R `p_spec65.s:399-404`]).

**Effect on other parts.** Every part that draws a random number or makes
a sound.

### Request 10: the placement of `nextSector`, `around` and the tag search

**What.** A placement hint for `gplace.py`: `nextSector` and `around` in
one group with their callers (`P_FindLowestFloorSurrounding`,
`P_FindHighestFloorSurrounding`, `P_FindLowestCeilingSurrounding`,
`P_FindNextHighestFloor`, `EV_LightTurnOn`) and `P_FindSectorFromLineTag`,
or in the core.

**Why.** Each line of a sector is an `FCALL nextSector`; from another group
of the same slot it is two group loads a line. Measured (routine mode, the
current placement, groups of this part's sizes only): `EV_LightTurnOn`
8.7 ms at the median and 20.0 ms at worst on `f121` (5.9 and 14.3 ms on
`fastpath`), where upstream's call runs about 3,000 instructions; the
finders 0.3-0.6 ms at the median, 4.8-5.1 ms at worst. With groups of 2.5
KB the loads cost more. The finders and `EV_LightTurnOn` run only when a
line is used or crossed, so this is time, not correctness. (The other
half is the tag search: `P_FindSectorFromLineTag` reads every sector's
records through `sec_get` to compare one tag, 9.4 ms at worst on `f121`
on E1M6's 250 sectors; a table of the sectors' tags, made by the load, or
a call of the API that reads only `SG_TAG`, would cut it. Not asked: a
measurement for the integrator's timing report.)

**Effect on other parts.** The placement's (the integrator's).

### Request 11: `fc_call` loses the flags of a return that restores a group

**What.** In `src/native/gcall.s`, `fc_ret`: keep the saved P across the
restore's `gr_load`, which counts its pages in `FC_PS`:

            cmp SLOT_GRP,y
            beq @back
            ldy FC_PS               ; (gr_load counts its pages in FC_PS)
            phy
            jsr gr_load
            pla
            sta FC_PS
    @back:  lda FC_PS

(in place of `cmp SLOT_GRP,y` / `beq @back` / `jsr gr_load` / `@back: lda
FC_PS`), and a case in `gselftest.py`'s `FCALL` check: a callee returning
with C set through a restore.

**Why.** `fc_ret` saves the callee's P in `FC_PS`, then, when the target's
slot must get its group back, calls `gr_load`, whose page count is
`FC_PS` (`sta FC_PS ; (the pages left)` ... `dec FC_PS`): the caller gets
P = 0. Found by secfind: `EV_LightTurnOn` (group 20, slot 2) `FCALL`s
`P_FindSectorFromLineTag` (group 13, slot 1), then `nextSector` (group 15,
slot 1), whose return restored group 13 and lost the carry that said "past
the sector's lines": E1M2's line 313 with bright 0 looped until the run's
cycle limit (193,683,300 steps; upstream's call: 3,071 instructions), 8
synthetic calls of the first full run. GAME.md 3.4 says "P comes back (a
carry result)".

**Stand-in.** `nextSector` returns its end in X (1 past the lines, 0 else)
and its callers test X, not C; its C is still set for a caller in its own
group. After the fix, either works.

**Effect on other parts.** Every part whose routine returns a flag through
an `FCALL` that may cross slots (the block iterators' callbacks, `P_CheckPosition`,
`P_TryMove`, the traversers ... all return booleans); until it is fixed,
results in A or X only.

## 3. Results

All on a2vm and `ref816`, 2026-10-01; `build/native/game/secfind/report.json`
holds every number below (per entry: cases, runs, failures, paths, cycles,
the lowest S; sizes; mod3; the planted bugs).

**The checkpoint** (`python3 tools/native/gparts/secfind.py --check --jobs
2`, 2,775 s): 11,815 cases (2,206 captured, 9,609 synthetic), each from
both poisoned machines (`$A5`, `$5A`) under `f121` and under `fastpath`:
**47,260 runs, 0 failures, 0 stray writes**; the canonical state after
each call equal to `ref816`'s with the exclusions R1-R6 only, every
declared output equal, the sound events equal (R6). Eligible: every case
(no entry of the part dispatches), none waiting.

| Entry | Cases captured + synthetic | Runs | Paths (captured; synthetic) | `f121` median / worst | `fastpath` median / worst | Lowest S |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| `getNextSector` | 300 + 0 | 1,200 | front 59, back 64, none (one-sided) 175, none (both sides) 2 | 39.9 / 39.9 us | 23.3 / 23.3 us | `$E6` |
| `P_FindLowestFloorSurrounding` | 10 + 1,385 | 5,580 | every sector of the nine maps | 318 / 4,821 us | 196 / 2,739 us | `$E2` |
| `P_FindHighestFloorSurrounding` | 1 + 1,385 | 5,544 | the same | 521 / 5,025 us | 349 / 2,889 us | `$DF` |
| `P_FindLowestCeilingSurrounding` | 19 + 1,385 | 5,616 | the same | 622 / 5,125 us | 425 / 2,965 us | `$DF` |
| `P_FindNextHighestFloor` | 1 + 1,385 | 5,544 | the same | 318 / 4,822 us | 195 / 2,731 us | `$E4` |
| `P_FindSectorFromLineTag` | 33 + 3,120 | 12,612 | first/next found or none; synthetic: every tagged line's chain from -1 | 78 / 9,371 us | 49 / 6,229 us | `$E6` |
| `P_CheckTag` | 300 + 465 | 3,060 | tag 11, no tag needed 289; synthetic: tag 247, no tag needed 182, none 36 | 40.6 / 42.6 us | 24.0 / 26.1 us | `$E6` |
| `P_UpdateSpecials` | 342 + 207 | 2,196 | plain 342; synthetic: leveltime 32,767 .. 2^31-1 and negative (bit 15 set: 126), switch timers ending on top, middle, bottom, none (36), plain 45 | 122 / 282 us | 93 / 196 us | `$E1` |
| `EV_LightTurnOn` | 0 + 268 | 1,072 | synthetic: bright 0 on every tagged line (247), 35 on every line of special 35, 255 | 8,733 / 20,039 us | 5,958 / 14,295 us | `$DC` |
| `lnLight` | 0 + 3 | 12 | synthetic: the three lines of special 35 | 8,230 us | 5,604 us | `$DA` |
| `T_LightFlash` | 300 + 2 | 1,208 | count 275, to min 16, to max 9; synthetic: both ends | 26.4 / 66.0 us | 19.3 / 46.5 us | `$E4` |
| `T_StrobeFlash` | 300 + 2 | 1,208 | count 269, to max 16, to min 15; synthetic: both ends | 26.4 / 65.6 us | 19.3 / 46.1 us | `$E4` |
| `T_Glow` | 300 + 2 | 1,208 | down 131, up 128, turns 41 (15 + 14 at the limit exactly); synthetic: both limits exactly | 64.9 / 65.1 us | 45.1 / 45.3 us | `$E4` |
| `T_Scroll` | 300 + 0 | 1,200 | scroll | 42.7 / 42.7 us | 29.3 / 29.3 us | `$E7` |

Cycles are a2vm's cost model (fabric clocks at 133.33 MHz, not the card),
from the routine's entry to the driver's return, the group loads of its
`FCALL`s included; the lowest S is the run's (the driver starts at
`$EF`: 21 bytes at the deepest, `lnLight`). The captured calls: 300
evenly spread over the five survey runs for each entry with more (the
thinkers through `callFn`, request 6), all for the others; plus the tour's
`P_UpdateSpecials` every 10th call (42), the in-play states of the nine
maps. The paths no captured call takes (a switch's timer ending,
leveltime past 32,767, `EV_LightTurnOn` and `lnLight`, the finders on
most sectors) are the synthetic calls'; the light thinkers' limits are
taken by captured calls too and by synthetic ones exactly.

**The arithmetic helper** (`--mod3`): upstream's `mod3` on every 16-bit
input (65,536, a 65816 loop run by `ref816 --call`) is `v % 3`, and the
native `mod3` (`sf_t_mod3`) equals it on every input; the 100,000 seeded
random inputs (seed 10) with 0, 1, 2, 3, `$FFFF` (-1), `$FFFE`, `$FFFD`,
`$7FFF`, `$8000`, `$8001`, `$FF`, `$100`: 0 different.

**The planted bugs** (`--plants`, each built from a scratch copy in a
temporary directory, deleted), each caught by its named check:

| Bug | Check | Failed runs |
| --- | --- | --- |
| the tag search restarting at 0 (`P_FindSectorFromLineTag` from sector 0 whatever the start) | finders (the chains' calls from a start of E1M1 and E1M3) | 507 of 507 |
| `T_Glow` turning one step late (no turn at minlight exactly) | thinker calls (the captured glows and the synthetic limits) | 16 of 302 |
| `NUKAGE` with a signed shift | the synthetic leveltime (E1M1) | 14 of 19 |
| the button restoring the other texture (top and bottom swapped) | the synthetic switch timers (E1M1) | 4 of 4 |
| `mod3` leaving 3 | mod3 on every input | 21,845 of 65,536 |

**Sizes** (`secfind.o`; `sftest.o`, 37 B, is test builds only): **1,570 of
1,800 B** (upstream 1,363), with the stand-ins (about 150 B: `SF_LT_GET`,
two `SF_SD_GET`/`SF_SD_PUT`, the basepic fetch). By routine: `buttonDone` 174,
`P_UpdateSpecials` 168, `P_FindNextHighestFloor` 167, `around` 133,
`T_Glow` 130, `EV_LightTurnOn` 121, `nextSector` 104, `T_LightFlash` 100,
`T_StrobeFlash` 100, `T_Scroll` 89 (the core), `P_FindSectorFromLineTag`
64, `P_CheckTag` 42 (its table 13), `mod3` 31, `P_FindHighestFloorSurrounding`
and `P_FindLowestCeilingSurrounding` 29 each, `P_UpdateAnimatedFlat` 26,
`P_FindLowestFloorSurrounding` 25, `getNextSector` 23, `lnLight` 15
(`secfind.py --report`; `make -f game.mk sizes` reports the skeleton's
image only).

**The test** (`tests/test_native_game_secfind.py`, 13 tests, about 400 s
at 2 jobs): the build and its budget, the stand-ins' constants against
llayout and the link map (and `notags` against the release's memory), a
sample of the checkpoint (every case of the entries with at most 40,
every 10th of the others; the synthetic leveltime and switch timers of
E1M1 and E1M3; the thinkers at their limits; every 20th synthetic call
of each finder, tag and light entry on the nine maps), mod3 on every
input, the five planted bugs.

**Commands** (from `demos/doom_gs`; the shared outputs read only):

    make -s -C src/native -f game.mk part P=secfind ROOT=$PWD
    python3 tools/native/gparts/secfind.py --log          # 5 ref816 runs, 40 s
    python3 tools/native/gparts/secfind.py --capture      # 2,206 cases, about 45 min at 1 job
    python3 tools/native/gparts/secfind.py --synthetic --jobs 1   # 9,615 calls, 5 min
    python3 tools/native/gparts/secfind.py --check --jobs 2       # 47 min
    python3 tools/native/gparts/secfind.py --mod3
    python3 tools/native/gparts/secfind.py --plants               # 2 min
    python3 -m unittest tests.test_native_game_secfind

**`build/` growth**: `build/native/game/secfind/` 76 MB (77,764 KB: the
cases 71 MB with each run's `base.ram.z`, the test image, the thinker logs,
the synthetic calls 0.4 MB, report.json); every temporary directory
deleted (the check's 28 MB of per-run results too).

## 4. Open points

- Requests 1-3 and 5 are stand-ins in `secfind.s` (marked `STAND-IN`):
  `gameroutine.grep_check` run on the part would flag its `g_get`/`g_put`
  of `LVMAP` (sides) until request 1 is applied; LTAB (`LVG1`, named with
  `G_LTABAT`) and GTAB pass it.
- Requests 6 and 7 are the shared harness's: until they are applied,
  `gameroutine.py --routine` cannot run this part's entries (the special
  handles of `as`, the paged entries' group, the thinkers' cases at
  `callFn`); `tools/native/gparts/secfind.py` is the part's harness.
- Request 11 is a bug of `gcall.s` that every part returning a flag across
  slots meets; `secfind` returns its own flags in registers meanwhile.
- `lnLight` is checked through `ref816 --call` of upstream's `lnLight`
  (`_Dp` the line, C 35) against the native one with `GA_0-2` (request 8);
  `findSpecial`'s own dispatch is part `lines`'.
- Timing: the finders and `EV_LightTurnOn` are dominated by the group loads
  of `FCALL nextSector` across groups of one slot and by the tag search's
  `sec_get` of every sector (request 10); a matter for the integrator's
  placement and timing report, not for correctness.
- The first full `--check` run lost a worker of its process pool at job
  120 (`BrokenProcessPool`, no Python error, the memory of each worker
  about 0.7 GB); the run after it went through. The second run found
  request 11's bug (8 runs), fixed by the stand-in; the third run is the
  result above.
- `T_Glow` with a direction other than -1 and 1 ("nothing", upstream's
  third branch) is in the code but no state has it (the spawn sets -1 and
  the thinker only 1 or -1): no case takes it.

## 5. The integration of wave 1 (2026-10-01)

| Request | Decision |
| --- | --- |
| 1 `sd_get`, `sd_put` | **Accepted**: `gobj.s`, `SD_BUF` and `SD_AT` in `glayout.TIC_GW_FIELDS` (`ggame.inc`, not `lgame.inc`: the load image needs neither); `SF_SD_*` are gone, `SB_SD = SD_BUF`, the scratch block's last 10 bytes free |
| 2 `lt_get` | **Accepted** (A:X and `API_W`); `SF_LT_GET` is gone |
| 3 `animated_texture_basepic` | **Accepted** as `ggame.inc`'s `GT_BASEPIC` (GTAB's place, read with `g_get`: GTAB is no cached kind); the part's test checks it against llayout |
| 4 the helpers | **Accepted**: `p_spec65.s:around` is in the part table; the `.ifndef GP_around_G` stand-in is gone; the in-place helpers are `glayout.INLINED` |
| 5 `p_lights65.s`'s equates | **Accepted**: `UGLOWSPEED`, `USTROBEBRIGHT` |
| 6 the routine harness | **Accepted in part** (as geom's R5) |
| 7 `grun.run`'s group | **Accepted** (`grun.entry_group`) |
| 8 the dispatch conventions | **Accepted**: README |
| 9 `jsr` to the core | **Accepted**: README |
| 10 placement | **Accepted**: `gplace.AFFINITY` keeps `nextSector`, `around`, the four finders, `EV_LightTurnOn` and `P_FindSectorFromLineTag` in one group |
| 11 `fc_ret`'s flags | **Accepted**: `gcall.s` keeps P across the restore's `gr_load`; `gselftest.py`'s FCALL check has a carry returned through a restore (`gt_fd`), and a plant `fcall-flags-lost` it catches; `nextSector`'s X result stays (either works) |

Rerun at the integration (`secfind.py --check --jobs 2`, `--mod3`, `--plants`): 47,260 runs, 0 failed, 0 stray writes; `mod3` all 65,536 equal; 5 plants caught; `EV_LightTurnOn` 6.6 ms at the median on `f121` (8.7 before), `P_UpdateSpecials` 0.42 ms (0.12: `mod3` and `buttonDone` in another group of its slot under the new placement); the test module 13 tests OK. Size 1,403 B.
