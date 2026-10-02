# Part `lines` (wave 2)

The record of milestone 10's part `lines` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 2; upstream 1042 B, native budget 1400 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 2's `lines` (2026-10-02).
- Files: `src/native/game/lines/*.s`, `src/native/game/lines/part.mk`, `src/native/game/lines/args.json`, `tests/test_native_game_lines.py`, this file; tools (if any) `tools/native/gparts/lines*.py`; build output `build/native/game/lines/` (`make -s -C src/native -f game.mk part P=lines ROOT=$PWD`).
- Its scratch block: `SB_LINES` (32 B, `ggame.inc`; 25 used).

The routines (GAME.md 2.4's row):

`p_switch65.s`: `P_CrossSpecialLine:420`, `P_UseSpecialLine:364`, `findSpecial:473` with the `LSTAB` dispatch and `lnExit`, `P_ChangeSwitchTexture:209` (the button list), the tables `usetab:565`, `crosstab:585`; helpers `swLine`, `swSide`, `isPlayer`

Its checkpoint (GAME.md 2.4): Captured calls (eligible: those with no handler, or a light or an exit, until waves 3 and 4 fill `LSTAB`); `P_ChangeSwitchTexture` on every switch texture of the nine maps by `--call`

Its planted bugs (each must fail the named check): a walk-once special not cleared; a monster allowed on a player-only special; the button's timer one tic short

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_switch65.s:P_CrossSpecialLine` | `P_CrossSpecialLine` | demo3 58, demo1 40, demo2 7, newgame 2, tour 0 |
| `p_switch65.s:P_UseSpecialLine` | `P_UseSpecialLine` | demo3 1543, demo1 81, demo2 391, newgame 1, tour 0 |
| `p_switch65.s:findSpecial` | `findSpecial` | demo3 586, demo1 80, demo2 11, newgame 3, tour 0 |
| `p_switch65.s:P_ChangeSwitchTexture` | `P_ChangeSwitchTexture` | demo3 0, demo1 0, demo2 1, newgame 0, tour 0 |
| `p_switch65.s:usetab` | `usetab` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_switch65.s:crosstab` | `crosstab` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_switch65.s:swLine`, `p_switch65.s:swSide`, `p_switch65.s:isPlayer`, `p_switch65.s:lnExit`, `p_switch65.s:spectab`, `p_switch65.s:usetab_end`, `p_switch65.s:crosstab_end`.

### 1.1 What the part built (2026-10-02)

| File | What |
| --- | --- |
| `src/native/game/lines/lines.s` | The part's routines, a GPL-2 derivative of upstream's `p_switch65.s`: `P_UseSpecialLine`, `P_CrossSpecialLine`, `findSpecial` with `spectab` (`usetab`, `crosstab`: data in `findSpecial`'s bytes), `lnExit` (LSTAB 9), `P_ChangeSwitchTexture` with upstream's `startButton`; `swLine`, `swSide` and `isPlayer` are done in place (the macros `SW_LINE` and `IS_PLAYER`; `swSide` is `sd_get`). The stand-ins of requests 1 and 2 are under "Stand-ins" at the file's head |
| `src/native/game/lines/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (secfind's forms, and three of this part's: an output `c`, `"when": "c"`, `"div"`: the note in `args.json`) |
| `tools/native/gparts/lines.py` | The checkpoint: eligibility from the survey, the captures (`--capture`: every eligible call, so that each call's path is known, and the tour's in-play states), the paths (`--paths`, kept in `paths.json`), the choice (2.4's minimums), the synthetic calls on the nine maps (`--synthetic`), the routine-mode runs (`--check`), `--plants`, `report.json`. It imports part `secfind`'s machinery (`Ref`, `Prep`, `Native`, `check_writes`, `ref_call`, `MapBase`, `Shared`), as wave 1's integration asked, and adds its own outputs (the carry), sound events, paths and the I_Error case |
| `tests/test_native_game_lines.py` | A sample of the checkpoint, the tables against the release's, the stand-ins' constants, the far-access grep, the three planted bugs |

### 1.2 The native interfaces (what the later parts call)

| Routine | Group (test placement) | In | Out |
| --- | ---: | --- | --- |
| `P_UseSpecialLine` | 24 | `GA_0-1` the thing (a mobj handle), `GA_2-3` the line (upstream's `_Dp[0-3]`, `_Dp[4-7]`) | A = 1 or 0 (upstream's C) |
| `P_CrossSpecialLine` | 18 | `GA_0-1` the line, `GA_2-3` the thing (upstream's `_Dp[0-3]`, `_Dp[4-7]`), A the side (0 front, 1 back: upstream's C) | none |
| `findSpecial` | 24 | A:X the line, Y 0 usetab, else crosstab | C clear: no tag where one is needed, or not in the table; C set: A the argument, X the handler's LSTAB number, Y the mode, `GT_0` the entry's index in spectab (upstream's `SW_I` / 8) |
| `P_ChangeSwitchTexture` | 21 | A:X the line, Y useAgain (0 or 1: upstream's callers pass `mode - 1`, 0 or true) | none |
| `lnExit` (LSTAB 9) | 26 | `GA_0-1` the line, `GA_2-3` 0 the exit, 1 the secret exit, `GA_4-5` the thing | A = 1 started, 0 not |

Every `LSTAB` handler is called by `P_UseSpecialLine` and
`P_CrossSpecialLine` with `GA_0-1` the line and `GA_2-3` the entry's
argument (README's convention, secfind's request 8), and also `GA_4-5` the
thing and, from `P_CrossSpecialLine` only, `GA_6` the side (request 3:
upstream's `lnVDoor` and `lnTele` take them from `p_switch65.s`'s near
scratch, `SW_THING` and `SW_CSIDE` [R `p_switch65.s:515-528`]). Upstream's
`lnExit` takes the line of its switch from `SW_LINE` (`swLine` [R
`p_switch65.s:547`]), which `P_UseSpecialLine` set to the line: natively
`GA_0-1`, the same line.

Upstream's 16-bit fields are native bytes here, each with every E1 value
below 256: a line's special, tag and flags (`LN_SPECIAL`, `LN_TAG`,
`LN_FLAGS`), a mobj's type, a side's textures (below 256: `COLDIR` [R
`p_switch65.s:168-169`]), spectab's arguments (the assembler refuses a
`.byte` over 255) and the handlers' results.

**The switch texture through `SW_IDX`.** Upstream's
`P_ChangeSwitchTexture` scans `switchlist` from its first entry, testing
the top, middle and bottom texture at each [R `p_switch65.s:240-261`].
Natively the three textures are looked up in GTAB's `SW_IDX` (`2 i + 1`
for the first `switchlist[i]` of a texture, 0 none: `P_InitSwitchList`'s
own table [R `p_switch65.s:135-157`], which milestone 9's store writes
from `umodel.game_data` and its setup checks compare as a boot global):
the least `i` wins, and at one `i` the top before the middle before the
bottom (a strict less-than in that order), which is the scan's answer for
every side. Four far reads of one or two bytes, instead of up to 38
compares of three words through a far table.

Arithmetic: none (upstream's `IIGS_MulLo16` of the side's address is the
side's number natively: `sd_get`). No helper of 2.4's "Arithmetic" list.

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The
part goes on with a local stand-in where it can.

### Request 1: GTAB's `switchlist` and `SW_IDX` in `ggame.inc`

**What.** In `tools/native/glayout.py`, after
`out.append(('GT_BASEPIC', LL.GT['BASEPIC'][0]))` (`globals()`'s end):

    # GTAB's switchlist and SW_IDX (lines.md request 1)
    out.append(('GT_SWLIST', LL.GT['SWITCHLIST'][0]))
    out.append(('GT_SWIDX', LL.GT['SW_IDX'][0]))

**Why.** `P_ChangeSwitchTexture` reads `SW_IDX` (the switch of a texture)
and `switchlist[i ^ 1]` (its other texture) from GTAB [R
`p_switch65.s:240-268`]; `ggame.inc` has only `GT_BASEPIC`.

**Stand-in.** `LN_GT_SWIDX = GT_BASEPIC - 256`, `LN_GT_SWLIST =
LN_GT_SWIDX - 2 * LN_NUMSW2` in `lines.s` (llayout's `_gtab` order: ...
`SWITCHLIST`, `SW_IDX`, `BASEPIC`); `tests/test_native_game_lines.py`
checks both against `llayout.GT`. With the request applied, the three
stand-in lines go and `GT_SWIDX`, `GT_SWLIST` replace them.

**Effect on other parts.** None (new names).

### Request 2: `LSTAB`'s entry numbers by name in `ggame.inc`

**What.** In `tools/native/glayout.py`, `globals()`, after request 1's
lines:

    # LSTAB's entry numbers by handler (lines.md request 2): spectab names
    # its handlers by number
    for i, key in enumerate(DISPATCH['LSTAB']['targets'], 1):
        out.append(('LSTAB_' + key.split(':', 1)[1], i))

**Why.** `findSpecial`'s table gives each special its handler as an
`LSTAB` number (upstream gives the address [R `p_switch65.s:564-600`]);
the numbers are `LSTAB_OWNERS`' order (`gdisp.inc`), which no include
names, so a reordering would change handlers silently.

**Stand-in.** `LSN_DOOR = 1` .. `LSN_EXIT = 9` in `lines.s`;
`tests/test_native_game_lines.py` (`Build.test_tables`) checks each
against `glayout.dispatch_entries()['LSTAB']`. With the request applied,
`LSN_DOOR` becomes `LSTAB_lnDoor`, and so on.

**Effect on other parts.** None (new names).

### Request 3: the `LSTAB` handlers' thing and side (README)

**What.** In `src/native/game/README.md`, "Calls: FCALL and DCALL", the
`LSTAB` item becomes:

> * an `LSTAB` handler takes the line in `GA_0-1` and spectab's argument
>   in `GA_2-3` (upstream's `_Dp[0-3]` and C), the thing in `GA_4-5` (a
>   mobj handle: upstream's `SW_THING`) and, when `P_CrossSpecialLine`
>   calls it, the side in `GA_6` (0 front, 1 back: upstream's `SW_CSIDE`),
>   and returns its result in A (1 started, 0 not). `P_UseSpecialLine` and
>   `P_CrossSpecialLine` (part `lines`) write them before `DCALL LSTAB`.

**Why.** Upstream's `lnVDoor` passes `SW_THING` to `EV_VerticalDoor` as
`_Dp[4-7]`, and `lnTele` passes `SW_THING` and `SW_CSIDE` to `EV_Teleport`
[R `p_switch65.s:515-528`]; those are `p_switch65.s`'s near scratch,
natively part `lines`' scratch block, which no other part reads. `lnExit`
takes its thing so too.

**Effect on other parts.** `evworld` (`lnVDoor` reads `GA_4-5`),
`teleport` (`lnTele` reads `GA_4-5` and `GA_6`); `lnDoor`, `lnPlat`,
`lnFloor`, `lnStairs`, `lnDonut`, `lnLight` need neither (the line and
the argument as before).

### Request 4: the placement of the part's routines and tables

**What.** In `tools/native/glayout.py`, `INLINED`:

    'lines': ('p_switch65.s:swLine', 'p_switch65.s:swSide',
              'p_switch65.s:isPlayer', 'p_switch65.s:usetab',
              'p_switch65.s:crosstab', 'p_switch65.s:spectab',
              'p_switch65.s:usetab_end', 'p_switch65.s:crosstab_end'),

and in `tools/native/gplace.py`, `AFFINITY`:

    ('p_switch65.s:findSpecial', 'p_spec65.s:P_CheckTag',
     'p_switch65.s:P_UseSpecialLine', 'p_switch65.s:P_CrossSpecialLine'),

**Why.** The helpers have no code of their own (done in place). The
tables are data that only `findSpecial` reads; the placement gave
`usetab` group 15 and `crosstab` group 22 while `findSpecial` is in 24, so
a table placed by its own entry would be read from a slot holding another
group: `lines.s` assembles them inside `findSpecial`'s bytes (220 B, the
tables' 136 among them), and their placement entries are dead.
`findSpecial` calls `P_CheckTag` (secfind, group 26 in the test
placement) on every call, and both entries call it: section 3 gives the
cycles of the paths with the group loads (routine mode, every slot empty
at the call). The rate is low (`P_UseSpecialLine` 0.7 a tic in demo3,
`P_CrossSpecialLine` 0.03 [M: the survey]): a lever for the integrator's
placement, not a matter of results.

**Effect on other parts.** `secfind`'s `P_CheckTag`, whose only other
caller is `attack`'s `shootSpecial` [R `p_attack65.s:944`], moves with
them.

### Request 5: the reference's sound events in a case (for waves 3-4)

**What.** `tools/native/gamecap.py`'s capture logs the calls of
`S_StartSound`, `S_StartSound2` and `S_StopSound` made inside the captured
call (entry only: the sound in A, the origin in `_Dp[0-3]`) and keeps them
in the case's header (`"sounds"`), so that a part compares the native
events with upstream's own instead of a model.

**Why.** R6 compares the sound events, and each part models them (secfind
the switch's, this part the switch's and `lnExit`'s noway). When waves 3
and 4 fill `LSTAB`, the calls of `P_UseSpecialLine` and
`P_CrossSpecialLine` that reach `lnDoor`, `lnPlat`, `lnVDoor`, `lnFloor`,
`lnStairs`, `lnDonut` or `lnTele` become eligible (646 wait for `lnVDoor`
alone), and their sounds are the handlers' (doors, plats, teleports) and
then the switch's when the handler started (`P_UseSpecialLine`'s modes 1
and 2 [R `p_switch65.s:396-410`]). `lines.py`'s `expected_sounds` raises
an error on such a case rather than compare it against no event.

**Effect on other parts.** Every part whose routines make sounds could
drop its model; the captures would be remade.

## 3. Results

The checkpoint (2026-10-02, the part's image: waves 1 integrated and
`lines`, the test placement; both fills `$A5` and `$5A`, both profiles
`f121` and `fastpath`, routine mode with R1-R6 only, the declared outputs
and the sound events compared, the write log checked):

    python3 tools/native/gparts/lines.py --capture     # every eligible call, the tour's states
    python3 tools/native/gparts/lines.py --paths --jobs 2
    python3 tools/native/gparts/lines.py --synthetic --jobs 2
    python3 tools/native/gparts/lines.py --check --jobs 2
    python3 tools/native/gparts/lines.py --plants
    python3 -m unittest tests.test_native_game_lines

**5,112 runs, 0 failures, 0 stray writes, the lowest S `$D8` (216).**

| Entry | Eligible calls (waiting) | Cases run: captured + synthetic | Runs | Failed | f121 median / worst | fastpath median / worst | Lowest S |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| `P_UseSpecialLine` | 1,368 (646 `lnVDoor`, 1 `lnPlat`, 1 `lnDoor`) | 300 + 90 | 1,560 | 0 | 40.6 / 830.1 us | 24.0 / 616.2 us | 220 |
| `P_CrossSpecialLine` | 93 (11 `lnPlat`, 3 `lnFloor`) | 93 + 87 | 720 | 0 | 108.3 / 11,144.5 us | 67.4 / 7,676.0 us | 216 |
| `findSpecial` | 680 (none) | 302 + 216 | 2,072 | 0 | 148.6 / 151.4 us | 108.4 / 111.2 us | 225 |
| `P_ChangeSwitchTexture` | 1 (none) | 1 + 162 | 652 | 0 | 101.5 / 105.1 us | 56.7 / 59.3 us | 230 |
| `lnExit` (through LSTAB) | (synthetic only) | 0 + 27 | 108 | 0 | 16.1 / 713.7 us | 13.0 / 521.9 us | 225 |

Every eligible call was captured (2,142 cases, so that each call's path is
known: `paths.json`); the choice is 2.4's: every one of an entry with
fewer than 300 eligible calls, else 300 spread evenly and the first call
of each path the 300 miss (`findSpecial`: 2 more). The times are routine
mode with every slot empty at the call (group loads included: an upper
bound); `P_CrossSpecialLine`'s worst is a light line crossed
(`EV_LightTurnOn` over the tagged sectors), `P_UseSpecialLine`'s an exit.

The paths (fill `$A5`, f121; "syn." the synthetic calls):

- `P_UseSpecialLine`: monster on a line that is not a door 299, on a
  secret line 1; syn.: the exits by the player alive 9 (the eight `11`
  lines and E1M3's `51`) and dead (health 0 and -5) 18, by a monster 36,
  the player on lines with no special of usetab 27.
- `P_CrossSpecialLine`: monsters on lines other than 97 and 88 73, the
  player on lines whose special is not in crosstab 18, an imp's shot 2;
  syn.: a light line crossed by the player from each side 42 (walk once:
  the special cleared; E1M3's own three lines of special 35, and on each
  map two tagged lines given special 35), by a monster 18, the rocket,
  imp and baron shots on 97 27.
- `findSpecial`: usetab found (`lnVDoor` 284, `lnPlat` 1, `lnDoor` 1),
  crosstab found (`lnPlat` 6, `lnFloor` 3), crosstab none 7; syn. on 12
  special lines a map, each table: every handler found, none, `lnExit`.
- `P_ChangeSwitchTexture`: demo2's one call (once, middle); syn. on every
  line of the nine maps whose front side shows a switch texture (45:
  top 11, middle 28, bottom 6), once and again (a button in slot 0), on two plain lines a map, and the button list: the line
  pressed already, slot 0 taken (slot 1), slot 0 pressed with slot 2
  taken, full (upstream ends in `I_Error`, "P_StartButton: no button slots
  left!" on its text page, checked; the native stops with `GS_ERROR`).
- `lnExit`: syn. the exit and the secret exit by the player alive and
  dead.

Planted bugs (`lines.py --plants`, each from a scratch copy in a deleted
temporary directory, fill `$A5`, f121):

| Bug | Check | Caught |
| --- | --- | --- |
| a walk-once special not cleared (`P_CrossSpecialLine` never clears) | the light lines of E1M1, E1M3 | 14 of 18 runs fail (`line[195].special: 0 != 35`) |
| a monster allowed on a player-only special (`P_UseSpecialLine` takes every thing as the player) | every 10th captured use and E1M1's monster calls | 34 of 34 runs fail (`output a: 1, upstream 0`) |
| the button's timer one tic short (`BUTTONTIME = TICRATE - 1`) | E1M1's `P_ChangeSwitchTexture` calls again | 2 of 7 runs fail (`button[0].btimer: 35 != 34`; the others take no new button) |

Sizes (`lines.py`'s `sizes()`; the part's image, `make -f game.mk part
P=lines`): **934 B of 1,400** (upstream 1,042): `P_UseSpecialLine` 148,
`findSpecial` 220 (spectab's 136 among them), `P_CrossSpecialLine` 171,
`lnExit` 88, `P_ChangeSwitchTexture` 307. Groups (test placement):
18 (slot 2) 460 of 2,048 B, 21 (slot 2) 437, 24 (slot 1) 559 of 2,560, 26
(slot 2) 130; the core 12,377 of 12,800 B (unchanged: nothing of the
part in it). `make -f game.mk sizes` was not run: its `skel` prerequisite
rebuilds the skeleton's shared image, which other parts of the wave read.

Other checks: `gcallgraph.py --check --built geom,mobjstate,secfind,flow,sight,lines`
0 failures; `gameroutine.grep_check` on `lines.s`: clean; the build has
no warning.

`build/` growth: `build/native/game/lines/` 55 MB (the cases 54 MB: 2,142
captures, five bases of the runs and the tour's 22 in-play states; the
synthetic calls, `paths.json`, the image); every temporary directory
deleted.

## 4. Open points

- **Waves 3 and 4 fill `LSTAB`.** Every call that reaches `lnDoor`,
  `lnPlat`, `lnVDoor`, `lnFloor`, `lnStairs`, `lnDonut` or `lnTele` waits
  (648 uses, 14 crossings): `P_UseSpecialLine`'s modes 1 and 2 (the
  switch changed after a handler that started) and a walk-once crossing
  of anything but a light are not yet run, nor `GA_4-6` as the handlers
  read them (request 3). The integrator's rerun: `lines.py --capture`
  (the newly eligible calls; the made ones are kept), `--paths`,
  `--check`; their sound events need request 5 (or a model of each
  handler's), until then `lines.py` fails such a case loudly.
- **The placement**: request 4 (the tables in `findSpecial`'s bytes, its
  dead entries; `P_CheckTag` beside `findSpecial`).
- `P_ChangeSwitchTexture` takes useAgain as a byte (Y): upstream's callers
  pass 0 or 1 (`P_UseSpecialLine`'s `mode - 1`, `lnExit`'s 0, `attack`'s
  `shootSpecial` true [R `p_attack65.s:953-958`]); `attack` passes 1.
- No survey run crosses a light line (E1M3's three lines of special 35)
  or uses an exit, so those are synthetic (E1M3's own lines, and two tagged
  lines a map given special 35); no run takes a full button list, so the
  `I_Error` case is synthetic too. E1M8 has no exit line (its exit is the
  boss death).

## 5. The integration of wave 2 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 2 as integrated").

| Request | Decision |
| --- | --- |
| 1 `GT_SWLIST`, `GT_SWIDX` | **Accepted**: `ggame.inc`; `lines.s`'s stand-ins are gone, the test checks the names against `llayout.GT` |
| 2 `LSTAB_<label>` | **Accepted**, and for `ITTAB` and `TRVTAB` too; spectab names `LSTAB_lnVDoor` ...; the test checks each against the table's order |
| 3 the handlers' thing and side | **Accepted**: README's `LSTAB` convention (`GA_4-5`, `GA_6`); `evworld.md`, `teleport.md`, `evfloor.md` say so |
| 4 the placement | **Accepted**: `INLINED['lines']`, and `findSpecial`, `P_CheckTag`, `P_UseSpecialLine`, `P_CrossSpecialLine` in one group (10, slot 2) |
| 5 the reference's sound events in a case | **Deferred to wave 3's integration**: no case of wave 2 needs it (every case that reaches a handler other than `lnExit` and `lnLight` waits for `evworld`, `evfloor`, `teleport`); it changes `gamecap.py`'s captures, which every part reads, so it is made with the first part that makes such cases eligible |

`tests/test_native_game_lines.py` (and `secfind`'s) sets `gamecap.CASES`
in `setUpModule`: under `unittest discover` (one process) another part's
harness may have changed that global, and `Build.test_tables` found no
case.
