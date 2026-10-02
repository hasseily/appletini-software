# Part `evworld` (wave 3)

The record of milestone 10's part `evworld` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 3; upstream 1223 B, native budget 1600 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 3's `evworld` (2026-10-02), under the owner's
  lean checks of 2026-10-02 (at most 40 calls a routine, one poisoned
  machine `$A5`, at most 3 planted bugs, the test under 60 s).
- Files: `src/native/game/evworld/*.s`, `src/native/game/evworld/part.mk`, `src/native/game/evworld/args.json`, `tests/test_native_game_evworld.py`, this file; tools (if any) `tools/native/gparts/evworld*.py`; build output `build/native/game/evworld/` (`make -s -C src/native -f game.mk part P=evworld ROOT=$PWD`).
- Its scratch block: `SB_EVWORLD` (32 B, `ggame.inc`; 22 used).

The routines (GAME.md 2.4's row):

`p_doors65.s`: `EV_DoDoor:445`, `EV_VerticalDoor:622` (keys, reopen), `newDoor:520`; `p_plats65.s`: `EV_DoPlat:260` (the busy floor test, the plat's list field none), helpers `doorArg`, `setDir`, `topLowest`, `setTop`, `edLine`, `edSec`, `edSound`, `platArg`, `sectorArg`, `platSound`, `setHigh`, `setLow`, `plSec`

Its checkpoint (GAME.md 2.4): Every captured call (newgame's door, the demos', the tour's); synthetic: every door and plat special of `usetab`/`crosstab` on every line of the nine maps that has it, through `P_UseSpecialLine` or `P_CrossSpecialLine` by `--call`

Its planted bugs (each must fail the named check): the door's top without `- 4 × FRACUNIT`; a locked door's sound before its message; the plat's low from the other finder; a plat started on a sector whose `floordata` is set (synthetic: the line used twice)

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_doors65.s:EV_DoDoor` | `EV_DoDoor` | demo3 0, demo1 0, demo2 1, newgame 0, tour 0 |
| `p_doors65.s:EV_VerticalDoor` | `EV_VerticalDoor` | demo3 563, demo1 79, demo2 3, newgame 1, tour 0 |
| `p_doors65.s:newDoor` | `newDoor` | demo3 5, demo1 8, demo2 4, newgame 1, tour 0 |
| `p_plats65.s:EV_DoPlat` | `EV_DoPlat` | demo3 8, demo1 1, demo2 3, newgame 0, tour 0 |

Helpers: `p_plats65.s:platArg`, `p_plats65.s:sectorArg`, `p_plats65.s:platSound`, `p_plats65.s:setHigh`, `p_plats65.s:setLow`, `p_plats65.s:plSec`, `p_doors65.s:doorArg`, `p_doors65.s:setDir`, `p_doors65.s:topLowest`, `p_doors65.s:setTop`, `p_doors65.s:edLine`, `p_doors65.s:edSec`, `p_doors65.s:edSound`, `p_doors65.s:sectorArg`, `p_switch65.s:lnDoor`, `p_switch65.s:lnPlat`, `p_switch65.s:lnVDoor`.

### 1.1 What was built

| File | What |
| --- | --- |
| `src/native/game/evworld/evworld.s` | The part's routines, a GPL-2 derivative of upstream's `p_doors65.s` (`EV_DoDoor`, `newDoor`, `EV_VerticalDoor`), `p_plats65.s` (`EV_DoPlat`) and `p_switch65.s` (`lnDoor`, `lnPlat`, `lnVDoor`: `LSTAB`'s entries 1-3). Every helper is done in place: `doorArg` (`DOOR`), `setDir` (`SETDIR`), `topLowest` (`TOPLOWEST`), `setTop` (`SETTOP`), `edSound` and `platSound` (`SECSOUND`) are macros; `edLine`, `edSec`, `platArg`, `plSec` and both `sectorArg` are the handles kept in the scratch block (`SB_LN`, `SB_SEC`, `SB_DR`); `setHigh` and `setLow` are `EV_DoPlat`'s local `@field`; upstream's `oof` is the macro `OOF` |
| `src/native/game/evworld/part.mk`, `args.json` | The fragment; the entries' inputs and outputs (secfind's forms; `newDoor` takes `ED_SEC` and `ED_LINE` and gives `DR_DOOR` "as" a door; the synthetic calls through `P_UseSpecialLine` and `P_CrossSpecialLine` use lines' declarations) |
| `tools/native/gparts/evworld.py` | The lean checkpoint: the choice (every call of `EV_DoDoor`, `newDoor`, `EV_DoPlat`; of `EV_VerticalDoor` every call in a tic where a door starts, then calls spread evenly, 40 in all), the captures (`--capture`), the synthetic calls on the nine maps (`--synthetic`), the runs (`--check`), the planted bugs (`--plants`), `report.json`. It imports part `secfind`'s machinery (`Ref`, `Prep`, `Native`, `ref_call`, `sounds`), part `lines`' (`outputs`, `path_of`, `find_special`, `switch_place`, `Base`) and part `mobjstate`'s stray rule and thinker-list checks (`allowed_main`, `allowed_aux`, `read_log`, `native_checks`) |
| `tests/test_native_game_evworld.py` | The build within budget, `args.json` against the image, `LSTAB`'s three entries, the far-access grep, a sample of the checkpoint, the three planted bugs (21 s); `DOOM_GS_FULL=1` adds the whole checkpoint (65 s) |

### 1.2 The native interfaces (what the later parts call)

| Routine | In | Out |
| --- | --- | --- |
| `EV_DoDoor` | A:X the line, Y the door type (`UC_NORMAL`, `UC_CLOSE30THENOPEN`, `UC_DOPEN`; upstream's `_Dp[0-3]` and C) | A = 1 when a door started, else 0 |
| `EV_VerticalDoor` | `GA_0-1` the line, `GA_2-3` the thing (a mobj handle; upstream's `_Dp[0-3]`, `_Dp[4-7]`) | none (`lnVDoor` answers 1) |
| `newDoor` | A the sector, `GA_0-1` the line (upstream's `ED_SEC`, `ED_LINE`) | A:X the door's handle (upstream's `DR_DOOR`) |
| `EV_DoPlat` | A:X the line, Y the plat type (`UC_RAISETONEARESTANDCHANGE`, `UC_DOWNWAITUPSTAY`) | A = 1 when a plat started, else 0 |
| `lnDoor`, `lnPlat` (`LSTAB` 1, 2) | README's convention: `GA_0-1` the line, `GA_2` spectab's argument (the type) | A = `EV_DoDoor`'s, `EV_DoPlat`'s result |
| `lnVDoor` (`LSTAB` 3) | `GA_0-1` the line, `GA_4-5` the thing (lines' request 3) | A = 1 |

Every routine changes `GA_*`, `GT_*`, `GC_*` (the core's temporaries:
`gt_spectake`, `gt_add`, `sp_store`), the object API's lines and the
hooks' state. For part `attack`'s `shootSpecial` (gun specials 46 and 47
[R `p_attack65.s:936-958`]): `EV_DoDoor` and `EV_DoPlat` with A:X = the
line, Y = the type.

**The records as made** (llayout's `SP_KIND`, `ZONE0`). A door: function
`FN_DOOR`, its sector, the thinker links, speed `2 × FRACUNIT` (byte 2 of
`SPDO_SPEED`), its line (the activating line, also for `EV_DoDoor`, as
upstream's `newDoor` does), then the type, the direction (`$FF` down, 1
up), the top and the light tag (`EV_VerticalDoor`: the line's tag,
sign-extended, for specials 1, 26-28 and 31-34, else 0; `EV_DoDoor`: 0);
the rest 0 (upstream's `Z_CallocLevSpec`). A plat: function `FN_PLAT`, its
sector, the links, `SPPL_LIST` `$FF` (none: upstream keeps no list
[R `p_plats65.s:3-6`]), the type, low = the floor; raise: speed
`FRACUNIT / 2`, high = `P_FindNextHighestFloor`, wait, count and status 0;
lower: speed `4 × FRACUNIT`, wait 105, status `UC_DOWN`, high = the floor,
low = `P_FindLowestFloorSurrounding`; any other type (no E1 line has one):
only the type, the sector and low, as upstream. A sector's `ceilingdata` or
`floordata` is the special's handle; "a moving ceiling or floor" is a high
byte other than `$FF` (none).

**Differences in form, not in result.** Upstream's 16-bit fields are
native bytes here: a line's special and tag, a sector number, a door's or
plat's type (high byte 0 from the clear). The topheight's `- 4 ×
FRACUNIT` is a 16-bit subtract on the high word, as upstream's `sbc ##4`
[R `p_doors65.s:568-576`]. The locked door's message is the symbol
reference `SYM_p_doors_msgBlue`, `...Yellow`, `...Red` (tag 1, the number,
offset 0: pickup's form). Arithmetic: none (upstream's `IIGS_MulLo16` of a
sector's or side's address is the native number; no helper of 2.4's
"Arithmetic" list).

## 2. Requests

Each with what, why (the evidence) and its effect on other parts. The part
goes on with its own code meanwhile; none needs a stand-in.

### Request 1: the helpers have no code of their own (`INLINED`)

**What.** In `tools/native/glayout.py`, `INLINED`, after the `'spawn'`
entry:

    'evworld': ('p_plats65.s:platArg', 'p_plats65.s:sectorArg',
                'p_plats65.s:platSound', 'p_plats65.s:setHigh',
                'p_plats65.s:setLow', 'p_plats65.s:plSec',
                'p_doors65.s:doorArg', 'p_doors65.s:setDir',
                'p_doors65.s:topLowest', 'p_doors65.s:setTop',
                'p_doors65.s:edLine', 'p_doors65.s:edSec',
                'p_doors65.s:edSound', 'p_doors65.s:sectorArg'),

**Why.** They are argument loaders and two-line field stores of
upstream's direct page [R `p_doors65.s:181-204`, `:568-616`;
`p_plats65.s:157-172`, `:207-250`, `:419-423`]: `evworld.s` does each in
place (1.1), so no label of theirs exists, and the placement gives them
bytes and groups today (`gplace.inc`: `p_doors_setDir` group 21, `edLine`
21, ...).

**Effect on other parts.** `movers` (wave 6) calls `sectorArg` of both
files in `T_VerticalDoor` and `T_PlatRaise` [R `p_doors65.s:104`, `:170`;
`p_plats65.s:146`, `:174-212`]: they are owned here (the earlier part,
GAME.md 2.4) and have no code, so `movers` does them in place too (a
special's `SP_SECTOR` byte).

### Request 2: the part's routines in one group (`AFFINITY`)

**What.** In `tools/native/gplace.py`, `AFFINITY`, after the wave 2
entries:

    # the doors and plats a line starts (evworld.md request 2): each
    # handler with the routine it calls, newDoor with its two callers
    ('p_switch65.s:lnDoor', 'p_doors65.s:EV_DoDoor', 'p_doors65.s:newDoor',
     'p_switch65.s:lnVDoor', 'p_doors65.s:EV_VerticalDoor',
     'p_switch65.s:lnPlat', 'p_plats65.s:EV_DoPlat'),

**Why.** The test placement scatters them over six groups (`EV_DoDoor` 15,
`newDoor` and `lnDoor` 21, `EV_VerticalDoor` 5, `EV_DoPlat` 2, `lnPlat`
20, `lnVDoor` 11), so a use of a manual door pages `lnVDoor`'s group, then
`EV_VerticalDoor`'s, then `newDoor`'s: up to three 2 KB loads where one
does. Measured (routine mode, every slot empty at the call: section 3):
`newDoor` alone 11,145 fabric clocks on `f121`, `EV_VerticalDoor` 14,155
at the median and 187,519 at worst (a new door: its own group,
`newDoor`'s, the finders'). The seven are 1,325 B (section 3), which fits
a group. `EV_VerticalDoor` runs 0.26 a tic in demo3 (563 calls in 2,134
tics, the survey), monsters at doors mostly.

**Effect on other parts.** None on results. `lines`' group (`findSpecial`,
`P_CheckTag`, `P_UseSpecialLine`, `P_CrossSpecialLine`, 10 in the wave 2
placement) and secfind's finders' group (`P_FindSectorFromLineTag` and the
`P_Find*` finders, which these routines call once a tagged sector) are the
neighbours; `gplace.py`'s rule 3 picks the slots.

### Request 3: lines' sound events of the door and plat handlers (lines' request 5)

**What.** `tools/native/gparts/lines.py`, `expected_sounds`: in place of
the `PartError` for a handler of waves 3-4, for the handlers of this part,
use this part's model (`tools/native/gparts/evworld.py`,
`expected_sounds`, which takes a `Prep` of `P_UseSpecialLine` or
`P_CrossSpecialLine` and gives the handler's sounds and then the
switch's), before `raise PartError(...)`:

        if row[1] in ('p_switch65.s:lnVDoor', 'p_switch65.s:lnDoor',
                      'p_switch65.s:lnPlat'):
            import evworld
            GC.CASES = CASES    # (evworld's first import points it at its own)
            return evworld.expected_sounds(prep)

(`HERE` is already on `sys.path`; `evworld` imports `lines`, so the import
stays inside the function; its module sets `gamecap.CASES` when first
imported, as every part's harness does).

**Why.** `lines.md` request 5 (deferred to this wave's integration): the
calls of `P_UseSpecialLine` and `P_CrossSpecialLine` that reach `lnVDoor`
(646 in the survey), `lnDoor` and `lnPlat` become eligible with this part.
This part models the handlers' sounds from the reference's states (no
capture logs upstream's own events): `EV_VerticalDoor` oof for the player
at a locked door without its key or at a one-sided line, the open sound at
the sector before a new door; `EV_DoDoor` per new door in order, the close
sound for `close30ThenOpen`, the open sound for normal and open unless the
top is the sector's ceiling at the call; `EV_DoPlat` per new plat, the
moving sound for raise, the start sound for lower; then, for
`P_UseSpecialLine` modes 1 and 2 when the handler started, the switch's
(lines' own rule). The 240 runs of section 3 compare the native events
with it: 0 different.

**Effect on other parts.** `lines`' checkpoint can run its waiting cases
of these three handlers; `evfloor` and `teleport` have theirs to give.
Upstream's own events in a case (`gamecap.py` logging `S_StartSound*`
during a capture: lines' request 5 as written) stay the better answer for
every part.

### Request 4: GAME.md 2.4's planted bug "a locked door's sound before its message"

**What.** In `docs/GAME.md` 2.4, row `evworld`, "Planted bugs": drop "a
locked door's sound before its message", or name a check that can see it.

**Why.** The message is a field of the player (canonical) and the sound an
event of the log (R6); neither records when it was made, so a native that
plays oof first and then sets the message ends in the same state and the
same events, and no routine-mode check can catch the order (as
mobjstate's "a freed node put at the free list's tail", wave 1 as
integrated, finding 4). Under the lean rules (at most 3 plants) this part
plants the other three.

**Effect on other parts.** None.

## 3. Results

The lean checkpoint (2026-10-02, the part's image: waves 1-2 integrated
and `evworld`, the test placement; fill `$A5`, profiles `f121` and
`fastpath`, routine mode with R1-R6 only; the declared outputs, the sound
events and mobjstate's thinker-list checks compared; mobjstate's stray
rule, with the parts' scratch blocks and the sides' records, which a
switch changes):

    python3 tools/native/gparts/evworld.py --capture     # 93 cases, about 2 min
    python3 tools/native/gparts/evworld.py --synthetic   # 49 calls on ref816
    python3 tools/native/gparts/evworld.py --check --jobs 2
    python3 tools/native/gparts/evworld.py --plants
    python3 -m unittest tests.test_native_game_evworld   # 21 s (DOOM_GS_FULL=1: + 65 s)

**240 runs, 0 failures, 0 stray writes, the lowest S `$D3` (211).**

| Entry | Calls in the survey (all eligible) | Cases run: captured + synthetic | Runs | Failed | f121 median / worst | fastpath median / worst | Lowest S |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| `EV_DoDoor` | 1 | 1 + 0 | 2 | 0 | 977,471 | 664,791 | 221 |
| `EV_VerticalDoor` | 646 | 40 + 0 | 80 | 0 | 14,155 / 187,519 | 9,490 / 137,495 | 221 |
| `newDoor` | 18 | 18 + 0 | 36 | 0 | 11,145 / 11,145 | 8,577 / 8,599 | 226 |
| `EV_DoPlat` | 12 | 12 + 0 | 24 | 0 | 1,136,239 / 1,376,616 | 788,967 / 964,139 | 221 |
| `P_UseSpecialLine` (to `lnVDoor`, `lnDoor`, `lnPlat`) | (synthetic) | 0 + 38 | 76 | 0 | 296,165 / 1,426,485 | 220,067 / 994,750 | 211 |
| `P_CrossSpecialLine` (to `lnDoor`, `lnPlat`) | (synthetic) | 0 + 11 | 22 | 0 | 1,046,279 / 1,389,057 | 716,919 / 953,147 | 211 |

The times are fabric clocks from the routine's entry to its return
(`report.json` gives µs too: `EV_VerticalDoor` 106 / 1,406 µs on `f121`),
in routine mode with every slot empty at the call (group loads included:
an upper bound). `EV_DoDoor` and `EV_DoPlat` scan every sector for the tag
(`P_FindSectorFromLineTag`, a `sec_get` a sector) and page the finders'
group: 7.3 and 8.5 ms at the median on `f121`; request 2 and the
placement are the levers.

The branches taken (fill `$A5`, `f121`):

- `EV_VerticalDoor` captured: a monster at a locked door 20, a new door
  (special 1) 13, (31) 3, (27) 1, a monster at a moving door (no change) 3.
- `EV_DoPlat` captured: lower (type 0) one plat 8, two plats 1, none (the
  sector's floordata set: the busy test) 2; raise (type 1) 1.
- `EV_DoDoor` captured: demo2's one call (open, one door); `newDoor`: all
  18.
- Synthetic, through `P_UseSpecialLine` (`usetab`; the first line of each
  special over the nine maps): new manual doors 1, 26-28, 31-34 by the
  player 8 and by a monster 1; the locked ones without the key (the
  message and oof) 6, a monster at a locked door 3; a one-sided line given
  special 1, by the player (oof) and by a monster; a repeatable door used
  twice more on the state the first use left (sent down 4, back up 4); a
  used-up door (31-34) used again with its special put back (a second door
  on a sector whose ceilingdata is set: upstream's path) 4; the switches
  103 (open), 63 (normal; again: the ceiling busy), 20 (raise), 62 (lower;
  again: the floor busy).
- Synthetic, through `P_CrossSpecialLine` (`crosstab`): doors 2 (open), 16
  and 76 (close30ThenOpen), 86 (open: four doors), 90 (normal); the
  walk-again lines crossed twice (the ceiling busy 3, the floor busy 1);
  plats 22 (raise), 88 (lower).
- **Not reached**: `EV_DoDoor`'s normal or open door whose top is already
  the sector's ceiling (no open sound); a door or plat type other than
  E1's three and two (upstream's bare record; no E1 line has one);
  `EV_VerticalDoor`'s turn of a moving door by a monster on a locked line
  (a monster stops at the lock first). The lean cut leaves out the other
  lines of each special (GAME.md 2.4's "every line of the nine maps that
  has it": 49 synthetic calls instead), 606 of `EV_VerticalDoor`'s 646
  calls, and the fill `$5A`.

Planted bugs (`evworld.py --plants`, each from a scratch copy in a deleted
temporary directory, fill `$A5`, `f121`):

| Bug | Check | Caught |
| --- | --- | --- |
| the door's top without `- 4 × FRACUNIT` (`TOPLOWEST`) | doors: E1M1's and E1M2's synthetic door uses and crossings | 4 of 8 runs fail (`door[0].topheight: 4456448 != 4718592`) |
| the plat's low from the other finder (`P_FindHighestFloorSurrounding`) | plats: the synthetic plat lines (20, 22, 62, 88) | 2 of 6 runs fail (`plat[0].low: -3145728 != 6815744`) |
| a plat started on a sector whose floordata is set (the busy test dropped) | plats: the lines used again | 2 of 6 runs fail (`plat: identities [] only in a, [1] only in b`) |

Sizes (`evworld.py`'s `sizes()`, the part's image): **1,325 B of 1,600**
(upstream 1,223): `EV_DoDoor` 309, `newDoor` 129, `EV_VerticalDoor` 477
(the messages' table 6 of it), `EV_DoPlat` 367, `lnDoor` 13, `lnPlat` 13,
`lnVDoor` 17. `make -f game.mk sizes` was not run (its `skel` prerequisite
rebuilds the skeleton's shared image).

Other checks: the build has no warning; `gcallgraph.py --check --built`
(waves 1-2 and `evworld`) 0 failures, `--stack` 80 of 160 B;
`gameroutine.grep_check` on `evworld.s`: clean.

`build/` growth: `build/native/game/evworld/` 38.7 MB (93 cases with three
runs' bases, the 49 synthetic calls, the image); every temporary
directory deleted.

## 4. Open points

- (Wave 2 as integrated) An `LSTAB` handler takes the thing in `GA_4-5` (`lnVDoor`: upstream's `SW_THING`) besides the line (`GA_0-1`) and spectab's argument (`GA_2-3`): `lines.md` request 3, `src/native/game/README.md`. Done: `lnVDoor` reads `GA_4-5`.
- (Wave 2 as integrated) A locked door's message is the player's message: `ggame.inc`'s `SYM_<unit stem>_<label>` give the symbols' numbers (`pickup.md` P1). Done: `SYM_p_doors_msgBlue`, `...Yellow`, `...Red`.
- (Wave 2 as integrated) The calls of `P_UseSpecialLine` and `P_CrossSpecialLine` that reach `lnDoor`, `lnPlat`, `lnVDoor` become eligible with this part: their sound events need upstream's own in each case (`lines.md` request 5, deferred to wave 3's integration) or a model of the handlers' sounds. This part gives the model (request 3); lines' own rerun of those cases is the integrator's.
- The lean cut (section 3): the fill `$5A`, the other lines of each special and most of `EV_VerticalDoor`'s captured calls are left to the final integration if it wants them (`evworld.py`'s `LEAN` and `synthetic_plan`'s one line a special).
- The sound model (request 3) is derived from the reference's states, not from upstream's events; a capture that logs `S_StartSound*` (lines' request 5) would replace it.
- `EV_DoDoor`'s and `EV_DoPlat`'s cost is the tag scan (a `sec_get` a sector) and the finders' paging (section 3): for the timing report (5.4).

## 5. The integration of wave 3 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 3 as integrated"). The merge was lean (the owner's request of
2026-10-02): the shared changes applied, every image rebuilt with no
warnings, this part's test module and the suite run once; the part's
checkpoint was not rerun.

| Request | Decision |
| --- | --- |
| 1 the helpers inlined | **Accepted**: `glayout.INLINED['evworld']` as written; `movers.md` noted (`sectorArg` in place) |
| 2 one group | **Accepted**: `gplace.AFFINITY` as written (group 13, slot 2) |
| 3 lines' sound events of the handlers | **Accepted**: `lines.py` `expected_sounds` uses `evworld.expected_sounds` for `lnVDoor`, `lnDoor`, `lnPlat`. Under the lean rules lines' checkpoint was not rerun, so its newly eligible handler cases wait for the final integration |
| 4 the planted bug "a locked door's sound before its message" | **Accepted**: dropped from GAME.md 2.4's row (no state or event check can see the order) |
