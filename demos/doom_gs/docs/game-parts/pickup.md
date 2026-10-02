# Part `pickup` (wave 2)

The record of milestone 10's part `pickup` (docs/GAME.md 2.4, 3.8): written
by the skeleton with these headings, kept by the part from then on.

## 1. Owner and wave

- Wave 2; upstream 1611 B, native budget 2100 B (GAME.md 2.4: upstream x 1.3).
- Owner: the builder of wave 2's `pickup` (2026-10-02). Built: `src/native/game/pickup/pickup.s` (p_inter65.s: `P_TouchSpecialThing` with pickTab's cases, `P_GivePower` and the give functions), `cheat.s` (m_cheat65.s: `C_Responder` with the cheat as an event number, `power`, `m_cheat_giveAmmo`), `pk.inc` (the scratch block, the conventions), `part.mk`, `args.json`; `tools/native/gparts/pickup.py` (the checkpoint), `tools/native/gparts/pickup_gen.py` (the generated `pkgen.inc`, request P1); `tests/test_native_game_pickup.py`.
- Files: `src/native/game/pickup/*.s`, `src/native/game/pickup/part.mk`, `src/native/game/pickup/args.json`, `tests/test_native_game_pickup.py`, this file; tools (if any) `tools/native/gparts/pickup*.py`; build output `build/native/game/pickup/` (`make -s -C src/native -f game.mk part P=pickup ROOT=$PWD`).
- Its scratch block: `SB_PICKUP` (32 B, `ggame.inc`).

The routines (GAME.md 2.4's row):

`p_inter65.s`: `P_TouchSpecialThing:101` (`pickTab:1144`'s cases), `P_GivePower:497`, helpers `specialArg`, `playerMo`, `giveBody`, `giveAmmo`, `giveWeapon`, `givePower`; `m_cheat65.s`: `C_Responder:73`'s effects (the cheats as event numbers: matching typed keys is milestone 11's input), `power:129`, `giveAmmo:182`

Its checkpoint (GAME.md 2.4): Every captured `P_TouchSpecialThing` (DEMO2 268 [M: CALLS]); synthetic: one touch of each E1 item type by the player at each skill (a state from a capture with the item moved onto the player); each cheat of the tour (`iddqd`, `idclev`) and of the generated streams

Its planted bugs (each must fail the named check): ammo doubled at the wrong skill; a weapon already owned giving no ammo; the backpack not doubling the maxima; another item's message

The entries (`glayout.PARTS`), their native names and their calls in the survey's runs (`build/native/game/shared/survey/`, the skeleton's survey):

| Entry | Native | Calls |
| --- | --- | --- |
| `p_inter65.s:P_TouchSpecialThing` | `P_TouchSpecialThing` | demo3 36, demo1 33, demo2 268, newgame 0, tour 1 |
| `p_inter65.s:pickTab` | `pickTab` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `p_inter65.s:P_GivePower` | `P_GivePower` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `m_cheat65.s:C_Responder` | `C_Responder` | demo3 0, demo1 0, demo2 0, newgame 20, tour 91 |
| `m_cheat65.s:power` | `power` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |
| `m_cheat65.s:giveAmmo` | `m_cheat_giveAmmo` | demo3 0, demo1 0, demo2 0, newgame 0, tour 0 |

Helpers: `p_inter65.s:specialArg`, `p_inter65.s:playerMo`, `p_inter65.s:giveBody`, `p_inter65.s:giveAmmo`, `p_inter65.s:giveWeapon`, `p_inter65.s:givePower`, `p_inter65.s:pickTab_end`, `p_inter65.s:pkAmmo`, `p_inter65.s:pkArmor`, `p_inter65.s:pkArmorBonus`, `p_inter65.s:pkBackpack`, `p_inter65.s:pkBody`, `p_inter65.s:pkCard`, `p_inter65.s:pkClip`, `p_inter65.s:pkHealthBonus`, `p_inter65.s:pkPower`, `p_inter65.s:pkSoul`, `p_inter65.s:pkWeapon`, `m_cheat65.s:cheats`.


## What was built

| File | What |
| --- | --- |
| `src/native/game/pickup/pickup.s` | `P_TouchSpecialThing` (the reach: the toucher's height against the thing's z over its own and the -8 unit floor, as upstream's 32-bit signed compares; a dead toucher; pickTab by sprite, its case through `FCALL`, the message, the item count, `P_RemoveMobj`, `bonuscount += BONUSADD`, the pickup sound), pickTab's eleven cases `pkArmor` ... `pkWeapon` (each a `ROUTINE` of the placement), `giveBody`, `p_inter_giveAmmo` (the clips through milestone 6's `umul16lo`, doubled at baby and nightmare, the better weapon when there was none), `giveWeapon`, `givePower` (invisibility sets `MF_SHADOW` and the renderer's copy, RTHING's flags bit 0), `P_GivePower` |
| `src/native/game/pickup/cheat.s` | `C_Responder` (A = the cheat's event number: its effect, A = 1), the fifteen cheats' effects in upstream's table order, `power`, `m_cheat_giveAmmo` |
| `src/native/game/pickup/pk.inc` | the scratch block's bytes, the conventions, `PICKUP_SOUND` |
| `src/native/game/pickup/part.mk` | the fragment; its rule makes `pkgen.inc` in each image's `gen/` (request P1) |
| `src/native/game/pickup/args.json` | the three entries' inputs and outputs |
| `tools/native/gparts/pickup_gen.py` | `pkgen.inc`: the messages' symbol numbers and four small tables of upstream, read at build time from the link map and the release (P1) |
| `tools/native/gparts/pickup.py` | `--build`, `--capture`, `--check`, `--plants`; `report.json` |
| `tests/test_native_game_pickup.py` | Build (the image, no far access, the symbols), Checkpoint (every 6th case of each group), Plants |

**The native calls.** `P_TouchSpecialThing`: `GA_0-1` the special, `GA_2-3`
the toucher (mobj slots: upstream's `_Dp[0-3]`, `_Dp[4-7]`); the caller
is `checkpos`'s `PIT_CheckThing` (wave 3). `P_GivePower`: A = the power,
A = 1 (C set) given, else 0. `C_Responder`: A = the cheat's number
(`ticcap.CHEATS`, m_cheat65.s's table: 0 idchoppers, 1 iddqd, 2 idkfa,
3 idfa, 4 idspispopd, 5-10 idbehold v s i r a l, 11 idclev, 12 idend,
13 idrocket, 14 idrate), A = 1; a number of 15 or more does nothing, A
= 0. Matching typed keys to the sequences (upstream's `CHT_P`, the
event) is milestone 11's input. `power`: A = the power.
`m_cheat_giveAmmo`: none.

**Upstream's behaviour kept** (each checked by the cases): the health,
armour and ammo limits test the sign of a 16-bit difference with no
overflow correction ("signed, small values"), as upstream's `bmi` after a
`cmp` (the random group's edge values 32767, 32768, 65535 take it); a new
card sets `bonuscount` to 6 and the touch adds 6 more; iddqd and
idrocket set the player's health only, not the mobj's; idclev is
`G_ExitLevel` (upstream's simplified cheat, no level number); the
idbehold cheats set no message; the backpack doubles the maxima once
and then gives a clip of each ammo; every E1 thing with `MF_SPECIAL` is
one of pickTab's 25 sprites (DOOM1.WAD's THINGS, types 15-39), so no E1
touch reaches `I_Error`.

## 2. Requests

Each: what, why (with the evidence), what it changes for the other parts;
the integrator accepts or refuses it with its reason. The part's
stand-ins are marked in its sources.

**P1. The messages' symbol numbers and upstream's small tables in
`ggame.inc`.** What: `glayout.py` writes into `gen/ggame.inc` the
constants that `tools/native/gparts/pickup_gen.py`'s `constants()` makes,
with the same names: `SYM_<unit stem>_<label> = n` (n the label's index in
`llayout.symbol_list()`, the manifest's "symbols") for the rodata labels
the parts name (pickup's: every `msg*` of `p_inter65.s` and
`m_cheat65.s`; better: every symbol of the list, 228 lines), and
`PK_WIAMMO_0-8` (`p_pspr65.s:weaponinfo`'s ammo, the release),
`PK_CLIP_0-3`, `PK_HALF_0-3`, `PK_PTICS_0-5` (`p_inter65.s`'s `clipAmmo`,
`halfClip`, `powerTics`, the release), `PK_BONUSADD` (`p_inter65.s`
`BONUSADD`), `CH_GOD_HEALTH`, `CH_IDFA_ARMOR`, `CH_IDFA_CLASS`,
`CH_NUMCHEATS` (`m_cheat65.s`'s `.equ`s, `schema.Constants.local`); the
simplest form is `from gparts import pickup_gen` (or a copy of its
`constants()`) in the writer of `ggame.inc`. Why: a player's message is
the bridge's "ref" of a symbol (`llayout.player_layout`: codes
`[['symbol', None]]`, 5 bytes: tag 1, the number, the offset), so writing
one needs the symbol's number, which no shared include gives; the tables
are upstream's data (`p_inter65.s:57-90`, `p_pspr65.s:1231-1249`) that must
not be typed in. Stand-in: the part's fragment runs `pickup_gen.py` into
each image's `gen/pkgen.inc` (the images `game`, `gprof`, `release`,
`part P=`, `wave W=`), and the sources `.include "pkgen.inc"`. Then the
fragment loses its `pickup_gen` rule and the sources their `.include`.
Other parts: every part that sets `player.message` (`evworld`'s locked
doors, `player`) needs the symbols too.

**P2. `INLINED` for the part's tables and argument loaders.** What: in
`glayout.py` `INLINED`, add

        'pickup': ('p_inter65.s:specialArg', 'p_inter65.s:playerMo',
                   'p_inter65.s:pickTab', 'p_inter65.s:pickTab_end',
                   'm_cheat65.s:cheats'),

Why: `pickTab` and `cheats` are tables, which must be in their reader's
segment (`pk_spr` ... in `P_TouchSpecialThing`'s, `ch_table` in
`C_Responder`'s: a table in another group of the same slot cannot be read
while the reader runs); `specialArg` and `playerMo` load upstream's
`_Dp` and have no native code. The placement gives them estimated bytes
and groups of their own (`GP_pickTab_G` 9, `GP_pickTab_end_G` 22) that
hold nothing. Other parts: none.

**P3. `AFFINITY` for the part's two units.** What: in `gplace.py`
`AFFINITY`, add

        ('p_inter65.s:P_TouchSpecialThing', 'p_inter65.s:pkArmor',
         'p_inter65.s:pkHealthBonus', 'p_inter65.s:pkSoul',
         'p_inter65.s:pkArmorBonus', 'p_inter65.s:pkCard',
         'p_inter65.s:pkBody', 'p_inter65.s:pkPower', 'p_inter65.s:pkClip',
         'p_inter65.s:pkAmmo', 'p_inter65.s:pkBackpack',
         'p_inter65.s:pkWeapon', 'p_inter65.s:giveBody',
         'p_inter65.s:giveAmmo', 'p_inter65.s:giveWeapon',
         'p_inter65.s:givePower', 'p_inter65.s:P_GivePower'),
        ('m_cheat65.s:C_Responder', 'm_cheat65.s:power',
         'm_cheat65.s:giveAmmo'),

(1,655 B and 442 B measured: either fits a slot). Why: the current
placement spreads the part over 9 groups (3, 8, 11, 14, 15, 17, 19, 20,
27), so a touch pages 5 groups at the median and 12 at worst
(`report.json` `fc_loads`): `P_TouchSpecialThing` takes 305,670 fabric
clocks at the median on `f121` for 110,192 CPU cycles. In one group each
`FCALL` inside the part is a `jsr`. Other parts: none (the cheats are
rare; a touch calls only `P_RemoveMobj` outside the part).

**P4. A persistent byte for idrate's flag.** What: `G_FPSSHOW` (1 B) in
`glayout.TIC_MAIN_FIELDS`, and the harnesses write it, as `G_WSET`, from
the reference's `d_main65.s:_g_fps_show` (low byte) at a run's start.
Why: idrate's message depends on `_g_fps_show`, which is no canonical
state (the frame counter is milestone 11's) but lives across tics and
loads; the scratch block is neither persistent nor private across tics.
Stand-in: `PK_FPS`, byte 21 of `SB_PICKUP` (`pk.inc`), which the part's
harness writes from the reference's value at each cheat case. Other
parts: `ticrun.py` (the start of a run).

**P5. The sound hook's PICKUP_SOUND.** What: `ghook.s`'s header says that
bit 7 of `S_StartSound`'s sound byte is upstream's `PICKUP_SOUND` (bit 15
of its word, `p_inter65.s:35`), which the part sets on the pickup sound
(every sound number is below `$40`). Why: the hook takes a byte; the
sound event report and milestone S4 must know the flag. Other parts:
none.

**P6. The cheat events of the tic level.** What: where a stream's event
of kind 1 (`EV_CHEAT`, `ticcap.py`) is applied (the driver's lockstep
mode, or part `tic`), `lda #number`, `FCALL C_Responder`, at the place of
the tic where upstream's `D_ProcessEvents` calls it (before `G_Ticker`).
Why: GAME.md 3.7 gives the cheats as event numbers; the native entry is
this part's. Other parts: `tic`, `ticrun.py`.

**P7. A part's scratch build with the fragments it needs only** (a
proposal for `grun.planted` and `game.mk part`). What: copy only the
fragments of the integrated waves' parts and of the part itself
(`pickup.py` `_fragments()`). Why: `game.mk` includes every
`game/*/part.mk`, so a fragment another builder of the same wave is
editing can break every part's build. Other parts: none.

## 3. Results

All on a2vm against `ref816`, 2026-10-02, `make -s -C src/native -f
game.mk part P=pickup` (the integrated wave 1 and the part), both fills
(`$A5`, `$5A`), both profiles (`f121`, `fastpath`): 4 runs a case.

`python3 tools/native/gparts/pickup.py --check --jobs 2` (1,242 jobs,
1,007 s): **4,560 runs, 0 failed, 0 stray writes**.

| Entry | Cases | Runs | Groups | Clock `f121` median / worst | `fastpath` | CPU cycles median / worst | Lowest S |
| --- | ---: | ---: | --- | --- | --- | --- | ---: |
| `P_TouchSpecialThing` | 802 | 3,492 | captured 338 (demo3 36, DEMO1 33, DEMO2 268, tour 1: all), touch 375, random 160 | 305,670 / 654,881 | 227,708 / 492,897 | 110,192 / 240,009 | `$DA` (21 B) |
| `C_Responder` | 212 | 996 | the 9 completing captured calls (tour: iddqd, idclev x 8), 240 synthetic (each of 15 cheats on two captured states x 8 player states), 102 captured calls completing no cheat (reference only: no canonical change) | 188,052 / 290,777 | 142,704 / 219,278 | 69,980 / 107,396 | `$D2` (29 B) |
| `P_GivePower` | 18 | 72 | each power from the three player states | 120,608 / 130,552 | 91,389 / 97,970 | 44,777 / 47,964 | `$D9` (22 B) |

Lowest S: the driver starts at `$EF` (bytes used in brackets, against
4.5's 160). Clocks are fabric clocks of the call (a2vm `--cost-timed`) with every
slot empty at the call, an upper bound: the group loads (5 at the
median a touch, request P3) dominate. Every routine and helper of the
part ran: the eleven cases and the give functions inside the touches,
`power` and `m_cheat_giveAmmo` inside the cheats.

The touches' paths (runs): taken 1,836, not taken 1,236, a dead toucher
224, out of reach below 112, above 84. The synthetic touches: each of
the 25 E1 item types (every E1 `MF_SPECIAL` thing) at each of the 5
skills from three player states (as captured, needy, stocked), the item
a thing of the captured level of its type moved onto the player (its z
the toucher's), or, where the base's level has none, the captured
special made one (type, sprite, frame, state, flags): 340 cases moved,
35 made (the red key, the visor, the suit, the map, a rocket on some of
the three bases' levels). The random group: 160 player states of edge and random
values (health, armour, ammo and maxima, weapons, cards, powers, the
ready weapon, the skill, a dropped flag, the reach at the edges of the
height and of -8 units).

The cheats of the generated streams: G1 (the only stream made) is a demo
lump, which carries no key events, so no cheat; every one of the 15 is
in the synthetic group.

**Planted bugs** (`--plants`, each in a scratch copy, built in a
temporary directory, deleted; the check: the synthetic touches of its
items, every skill and player state, one fill):

| Plant | Check | Runs | Failed | First difference |
| --- | --- | ---: | ---: | --- |
| ammo doubled at hard, not nightmare | ammo items | 90 | 36 | `player[0].ammo: [60, 0, 0, 0] != [70, ...]` (a clip, skill 3) |
| a weapon already owned giving no ammo | weapons | 45 | 15 | the chaingun not taken (stocked) |
| the backpack not doubling the maxima | backpack | 15 | 10 | `player[0].maxammo: [400, 100, 100, 600] != [200, 50, 50, 300]` |
| the stimpack's message the medikit's | stimpack | 15 | 5 | `player[0].message: msgStim != msgMedikit` |

**Sizes** (`pickup.py --build`, the part's modules in the test image):
2,097 of 2,100 B (-0.1%): `pickup.s` 1,655, `cheat.s` 442. By routine:
`P_TouchSpecialThing` 557 (with pickTab, 150 B, and the cases' `FCALL`
stubs), `giveAmmo` 295, `C_Responder` 338 (the cheats), `giveBody` 104,
`givePower` 103, `m_cheat_giveAmmo` 97, the rest 7-86 each. With P3 each
`FCALL` inside the part that now goes through `fc_call` (6 B) becomes a
`jsr` (3 B).

**Test**: `python3 -m unittest discover -s tests -p
test_native_game_pickup.py`: 8 tests OK in 301 s (every 6th case of each
group, the four plants).

**build/**: `build/native/game/pickup/` is 57 MB (the cases 53 MB, five
runs' bases of 3.9 MB each; the image); every temporary directory
deleted.

## 4. Open points

- The timing is placement-bound until P3 is applied.
- No generated stream has a cheat (G1 is a demo lump); the integrator's
  streams G2-G10 are demo lumps too, so the tour's iddqd and idclev stay
  the only captured cheats.
- `C_Responder`'s key matching (`CHT_P`, NUMKEYS, the event) is milestone
  11's; the native entry takes the number (P6).
- The pickup sound's flag (P5) is not compared: the sound events are a
  report (R6).
- idrate's flag is a stand-in until P4.

## 5. The integration of wave 2 (2026-10-02)

Each request, accepted or refused, with what was done (docs/GAME.md
"Wave 2 as integrated").

| Request | Decision |
| --- | --- |
| P1 the symbols and upstream's tables | **Accepted, in shared names**: `ggame.inc` has `SYM_<unit stem>_<label>` for every symbol of the manifest's list (228: `glayout.symbol_constants`); `lgame.inc` (`llayout.game_constants`, beside `U_MAXAMMO_*`) has `U_CLIPAMMO_a`, `U_HALFCLIP_a`, `U_POWERTICS_p` (the release's tables), `U_BONUSADD`, `U_GOD_HEALTH`, `U_IDFA_ARMOR`, `U_IDFA_ARMOR_CLASS`, `U_NUMCHEATS`. `PK_WIAMMO_*` **refused**: `giveWeapon` reads damage's `weaponinfo` (`damage.md` R2), one table. `pickup_gen.py`, `pkgen.inc` and the fragment's rule are gone; the sources use the shared names |
| P2 `INLINED` | **Accepted** |
| P3 `AFFINITY` | **Accepted**: the touch and its cases (group 18, slot 1) and the cheats (group 25, slot 1) |
| P4 a persistent byte for idrate | **Accepted**: `G_FPSSHOW` (main `$1EFA`, `glayout.TIC_MAIN_FIELDS`); `pickup.py` writes the reference's `_g_fps_show` there; `gameroutine.tic_main_records` gives every harness `G_WSET` and `G_FPSSHOW`; the shared stray rule allows the tic globals |
| P5 `PICKUP_SOUND` | **Accepted**: `ghook.s`'s header |
| P6 the cheat events | **Accepted, for part `tic`** (wave 6): its record's open points |
| P7 a scratch build with the needed fragments | **Not taken into `game.mk`**: `game.mk` needs every fragment for the wave table; once a wave is integrated its fragments are stable, and `pickup.py` already copies only the integrated waves' and its own |
