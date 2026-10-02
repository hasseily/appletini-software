# Milestone 11, part `fxchan`: the channel logic

Part `fxchan` of wave 4 ([`docs/SCREENS.md`](../SCREENS.md) 0.1 F3, F4,
F11; 3; 4.4; 4.7; 7.3; [`tools/sound/README.md`](../../tools/sound/README.md)
"The game side"), 2026-10-01. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed. A GPL-2 derivative of upstream's
`s_sound65.s` [R `:177-670`, `:1274-1285`]; nothing of `cal_integer.s`
(the divide is milestone 6's `sdiv32`, C semantics).

## 1. What was built

| File | What |
| --- | --- |
| `src/native/fx_chan.s` | `sc_start`, `sc_start2`, `sc_stop`, `sc_update`: upstream's `S_StartSound`, `S_StartSound2` (the one fake mobj `FM`), `sameOrigin`, `getChannel`, `priority`, `stopChannel`, `S_StopSound`, `S_UpdateSounds` and `S_AdjustSoundParams` with `units`, `mulLong`, `divAtt`, `absDelta`; `NUM_CHANNELS` and the blocks from the build's `s2.inc`; every decision into its channel's mailbox (fxplay's rules, FXPLAY-4); `isPlaying` through fxplay's `fx_isplaying`; positions through the callback `s2t_pos`. `-D FXC_NOSEP`: MENUW's build, no separation (2.4); `-D FXC_TRACE`: the test machines' trace of each adjust |
| `src/native/fx_pcache.s` | `s2t_pos` for `MENUW`: the listener from `LS_X`/`LS_Y`/`LS_ANGLE` while `LS_ON`, a mobj from the first busy channel whose origin it is (`FC_X`, `FC_Y`); `-D FXC_MSCR` places the scratch block for the linkage image (a stand-in, FXCHAN-4) |
| `src/native/fx_cdrv.s` | Test only: the a2vm driver: a stream of cases in main memory (an operation, pokes, the call in cost phase 30, out ranges copied to records); `-D FCD_PLAY` an injected `fx_isplaying`, `-D FCD_POS` a table-driven `s2t_pos` with its asks logged; `fxc_trace` |
| `src/native/m11/fxchan.mk` | The include `gen/fxchan.inc`, FXCH8's `gen8/s2.inc`, the objects (c8: FXCH8, c3: the test build's 3 channels, rel: the tic image's object, menuw: MENUW's) and the machines `fxc8`, `fxc8r`, `fxc3`, `fxcm8` (map from `fxcrun.py --cfg`), the linkage image `fxcmw` in `MENUW`'s room (its size table) |
| `tools/sound/fxchan.py` | The host model (`Model`: the native state, the two callbacks `pos` and `playing`, the paths it takes); the priority table read from upstream's `sfxPriority` lines; the constants from `offsets.inc` through `bridge/incfile.py`; `--inc` writes `fxchan.inc` (the priority table as a macro, the places that are stand-ins) |
| `tools/native/fxcrun.py` | The a2vm runs: the map, the image (poisoned main and card, the math and its tables), cases into chunks (a sequence never cut), the out records decoded; `make` (2.6) |
| `tools/native/fxcap.py` | The captures, the cases, every comparison, the planted bugs, the report: `--capture`, `--evict`, `--check`, `--cost`, `--planted` |
| `tests/wip_test_m11_fxchan.py` | 3 model tests, 7 checkpoint tests, 1 planted-bugs test (7 subtests) |

Build output: `build/native/m11/fxchan/` (the machines, `cap/` with the
captures `RUN.json.z` 1.9 MB in all, `base.img` 8.5 MB, `evict.json`;
`report.json`). Temporary directories are `tmp-*`/`cap-*` there, deleted
after each run.

## 2. Decisions where the design left a choice

1. **The interface** (request FXCHAN-3). `sc_start`: `GA+0-1` the sound
   (upstream's word, `PICKUP_SOUND` included), `GA+2` the origin's kind
   (`ORG_NONE`, `ORG_MOBJ`, `ORG_PLAYER`), `GA+3-4` its handle (`$FFFF`
   for none), `GA+5-12` its x, y; `sc_start2`: the sound and the point's
   x, y (kind `ORG_FM`, handle `$FFFF`, set by the routine); `sc_stop`:
   `GA+2-4`. The listener is not an argument: design.md R4 put the origin's
   and the listener's positions in `GA_*`, 24 B of the 20 B `GA_*` has, so
   the routines ask `s2t_pos` for the handle `$FFFE` (the player's mobj;
   carry set: none), as `sc_update` must anyway.
2. **The channel record** (FXCHAN-1). 12 B: the sound, the kind with the
   pickup flag in bit 7, the handle (2), the origin's last x and y (4 B
   each). `CH_X`/`CH_Y` of 3 bytes (s2lay's open problem 2) cannot be
   exact: the low byte of a distance moves the borrow into `units`, so a
   paused frame's volume would differ. Local names `FC_*` meanwhile.
3. **The tic-side block's two spare bytes** (FXCHAN-2): `LS_ON` (whether
   the listener exists, for `fx_pcache`) and `SND_SFXVOL` (upstream's
   `snd_SfxVolume`, 0-15, read by both images; the menu and the defaults
   write it).
4. **MENUW's object, `-D FXC_NOSEP`**. A paused frame's separation reaches
   no mailbox (the side is chosen at the start: `fx_service` uses only a
   volume) and `MENUW`'s own starts have no origin (the menu's sounds),
   so its build skips the angle, `pta3` and `sineapprox`, which `MENUW`'s
   W block (`MATHW` render subset, `$6000-$65FF`) does not hold; it needs
   only `mul32` (card) and `sdiv32`. The tic image's object computes
   `SS_SEP` in an update as upstream does, compared below.
5. **No listener.** `sc_update` does nothing when `s2t_pos($FFFE)` says
   none (upstream's `musFrame` calls `S_UpdateSounds` only when the player
   has a mobj [R `s_sound65.s:1914-1922`]); a start with an origin then is
   not audible, as upstream's `adjustParams`.
6. **A bad sound id** (upstream: `I_Error`): no sound.
7. **The player's origin** is the hook's decision at the start
   (`ORG_PLAYER`); upstream compares the origin with `player.mo` at each
   update. They differ only if the player's mobj changes while a sound
   plays, which a level reload (death) precedes with every channel
   stopped.

## 3. Checkpoint

Commands, from `demos/doom_gs`:

```
df -h /System/Volumes/Data                         # 69 GB free
make -C src/native -f m11.mk part P=fxchan         # (2.6)
python3 tools/native/fxcap.py --capture            # the five runs, the base: ~1 min
python3 tools/native/fxcap.py --check              # 3 min 1 s, report.json ok
python3 tools/native/fxcap.py --planted            # 16 s
python3 tools/testpar.py tests/wip_test_m11_fxchan.py
```

### 3.1 The comparisons (FXCH8: 8 channels, the reference's isPlaying)

| Comparison | Calls | Result [M] |
| --- | ---: | --- |
| 1. Starts and stops of demo3, DEMO1, DEMO2, the tour | 1,179 `S_StartSound`, 125 `S_StartSound2` (1,304, SCREENS.md's count), 751 `S_StopSound` | all equal to the reference (the table: sound, origin, kind; every mailbox after the reference's stops and starts applied to the injected pattern; each adjust's audibility, `SS_VOL`, `SS_SEP`; `FM`) and to the model; the model equal to the reference |
| 2. `S_UpdateSounds` (`jumps=1`), the reference's `isPlaying` injected | 2,863 (demo3 534, DEMO1 1,257, DEMO2 959, the tour 113) | all equal: the stops (ended, inaudible), each `docVolume`'s channel, `SS_VOL`, `SS_SEP` |
| The menu run's unpaused calls (and the menu's own start) | 709 | all equal |
| 3. Eviction and the rare paths: `ref816 --call` of `S_StartSound`/`S_StartSound2` from synthetic states | 134 (54 directed, 80 random) | all equal; 4 failed starts (X4, injected, named) |
| 4. A start and the frame's `sc_update` with fxplay's `fx_isplaying` (FXCH8 and 3 channels) | 13 each | the channel plays and its mailbox keeps the start, for each origin kind; a start then a stop: free, stop set, start cleared; an active voice keeps it playing |
| The 3-channel build against the model: the captured call streams replayed (3.2) | 4,918 | all equal |
| The 3-channel build against the model: random call sequences | 10,000 sequences, 35,041 calls | all equal (state and trace after every call) |
| The MENUW linkage (3.3) | the last unpaused update on `fxc8`, then 7 calls on `fxcm8` (the menu's own start, 6 paused updates) | all equal: 1 paused `docVolume` at the new volume, 3 stops |

**The path coverage** (the compared calls that take each labelled path of
`S_StartSound` and `getChannel`, captured and synthetic; `report.json`):
pickup bit 5, pickup oof/noway 30, no pickup 1,633; no origin 53, the
player 331, `FM` 157, an origin audible 962, inaudible 322; kill 176, no
kill 1,170; `getChannel` free 1,333, evict equal 5, evict lower 7, none
1; started 1,345, failed 4. **`getChannel`'s same-origin stop [R
`:293-302`] is unreachable**: `S_StartSound` first stops the first busy
channel with the same origin and kind [R `:245-258`], with the same test
(an origin of none skipped by `getChannel`, matched by the kill only when
both are none); that channel is then free and every channel before it is
busy with another origin or kind, so `getChannel` takes it as free before
it can reach a second one. It is named in the report, not required; the
model never takes it either. `S_AdjustSoundParams` (reported): clip 318,
distance 1,511, full 607, less 1 1,258 / not 897, map 8 32 (clamp 20,
beyond 20), no listener 1, silent 9, zero distance 7.

### 3.2 How a reference call becomes a native case

- **Positions.** The captures do not hold the mobjs (s2cap's open problem
  1). Three dump points inside `adjustParams` give what upstream holds in
  registers: at the JSL to `R_PointToAngle3` (A, X: dx; `_Dp`: dy), and
  after the two loads of the view angle (A: its low, then high word);
  `absDelta`'s returns give |dx|, |dy| where the angle is not reached.
  Upstream's arithmetic uses only differences modulo 2^32, so the case's
  listener is (0, 0) (or `FM` less the delta when `FM` is a source of the
  call, `FM` being in the channel block), each source the listener plus
  its delta (or less |delta|).
- **Identities.** An origin's 32-bit pointer: 0 none, `&FM`, the
  player's mobj, else a mobj handle by address.
- **Mailboxes** are injected in a pattern (a busy channel: start and
  volume pending; a free one: stop), so a stop must clear a pending start.
- **The 3-channel replay** feeds each run's calls in order to the model
  and to `fxc3` from the model's state, with a host stand-in for
  `fx_service`'s voices at each update (a start's voice plays (sound mod
  7) + 2 frames, a stop silences it, the mailboxes are then empty), the
  positions last known, `isPlaying` through fxplay's `fx_isplaying`.
- **X4.** A start whose `startSound` failed expects the native decision
  (the start) without the reference's stop after it; 0 in the captured
  runs, 4 synthetic (two by `SND_PCM` zeroed).

### 3.3 The menu run

demo3 with `snd_SfxVolume` poked to 8 at gametic 2,361 (a positional
sound playing; `pick_menu_tic`) and the menu opened in the same frame:
the menu's gray conversion takes about 1.4 s of machine time, longer
than the sounds, so a poke after the menu opened found every positional
sound ended [M]; the poke stands in for the slider (injected state with
a reason). `S_UpdateSounds` with the menu up is logged (2,176 paused
calls in 150 frames).

### 3.4 The tests

`tests/wip_test_m11_fxchan.py`: the model's priority table, mailbox and
pickup rules; the checkpoint's comparisons (1-4, the replay, 10,000
random sequences, the MENUW linkage, the sizes); the planted bugs.
Without build/ every test skips naming what is missing. Python 3.9.6:
the tools compile and the model runs.

## 4. Planted bugs (each in a scratch copy, built apart)

| Planted | Caught by | Message [M] |
| --- | --- | --- |
| The separation's "less 1" not taken | comparison 3 | `separation: straight ahead, east, the view 0: mailbox 0: (3, 1, 80, 128), the reference (3, 1, 80, 129)` |
| Map 8's floor of 15 dropped | comparison 3 | `distance 1199, map 8, volume 15: channel 0: (0, 0, False, 65535), the reference (1, 1, False, 512)` |
| Priority compared with `>` | comparison 3 | `evict equal: channel 3: (46, 1, False, 531), the reference (46, 1, False, 512)` |
| The pickup flag ignored in `sameOrigin`'s kill | comparison 3 | `no kill: same origin, the pickup flag: channel 3: (0, 1, True, 512), the reference (46, 1, True, 512)` |
| `S_StartSound2` with its own origin instead of `FM` | comparison 3 | `S_StartSound2 kills FM's: channel 0: (21, 1, False, 65535), the reference (21, 3, False, 65535)` |
| `isPlaying` without the pending start (fxplay's `fx_isplaying`, a scratch copy of `fx.s`) | comparison 4 | `update 1: the start's channel was freed (0, mailbox $01)` |
| A stop that leaves the mailbox's start set | comparison 4 | `the stop of a pending start: channel 0 0, mailbox $03` |

The last one first passed: comparison 4's stop came after the mailbox
was emptied; a start then a stop in one frame was added.

## 5. Sizes against the budget

| Object | Budget | As built [M] |
| --- | ---: | ---: |
| `fx_chan`, the tic image's (code 1,032 + the priority table 53) | 700 | **1,085** |
| `fx_chan`, MENUW's (`-D FXC_NOSEP`) | 700 | **970** |
| `fx_pcache` | 60 | **85** |
| The scratch block | 32 | 23 used |
| `MENUW` with both (the linkage image `fxcmw`) | room 16,896 | 1,055 ($6600-$6A1E) |

Over budget (FXCHAN-5). The budget is upstream × 1.3 [A]; the 32-bit
arithmetic of `S_AdjustSoundParams` takes 8-bit steps on the 65C02
(`adjust` 334 B, its helpers 160 B), where upstream's 65816 takes words.
A first version was 1,218 B; shared loops, a borrow in place of the
decrement, `units` kept from the clip test brought it to 1,085.

## 6. Timing (SCREENS.md 6.4): us a call

Cost phase 30 around the call, `--cost-timed`; the stand-ins'
`s2t_pos` (a table) and, in FXCH8, `fx_isplaying` included [M]:

| Build | Calls | f121 | fastpath |
| --- | --- | ---: | ---: |
| 3 channels (random states) | `sc_start` 158 | 44.3 | 39.8 |
| | `sc_start2` 63 | 77.2 | 68.3 |
| | `sc_stop` 61 | 5.2 | 5.2 |
| | `sc_update` 118 | 80.2 | 70.6 |
| FXCH8, demo3's calls | `sc_start` 366 | 62.1 | 56.2 |
| | `sc_start2` 64 | 100.9 | 89.2 |
| | `sc_stop` 254 | 7.7 | 7.7 |
| | `sc_update` 534 | 77.4 | 69.2 |

At most 4 starts a tic and one update a frame [M: SCREENS.md F4]: about
0.3 ms a frame. An update's separation (`pta3`, `sineapprox`, `mul32`,
about 40 us a positional channel) reaches no mailbox (2.4).

## 7. Requests (for the integrator; stand-ins marked `STANDIN`)

### FXCHAN-1. `tools/native/s2layout.py`: the channel record

```
-CHAN_FIELDS = [('CH_SFX', 1), ('CH_PICKUP', 1), ('CH_KIND', 1),
-               ('CH_HANDLE', 2), ('CH_X', 3), ('CH_Y', 3), ('CH_SPARE', 1)]
+CHAN_FIELDS = [('CH_SFX', 1), ('CH_KIND', 1), ('CH_HANDLE', 2),
+               ('CH_X', 4), ('CH_Y', 4)]
+CHF_PICKUP, CHF_KIND = 0x80, 0x03      # in CH_KIND: the pickup flag, the kind
```

and in `include_text`, after `out += sorted(CHAN.items(), ...)`:
`out += [('CHF_PICKUP', CHF_PICKUP), ('CHF_KIND', CHF_KIND)]`. Then in
`fx_chan.s` and `fx_pcache.s` `FC_` becomes `CH_`, `FC_PICKUP`
`CHF_PICKUP`, `FC_KINDMASK` `CHF_KIND`, and `tools/sound/fxchan.py`'s
`FC_FIELDS` lines in `inc_text` go. Why: 2.2. SCREENS.md 4.4's row
`$E8C0-$E8FF`: "the channel table (3 × 12 B: the sound, the origin's
kind with the pickup flag, its handle, its last x and y, 4 B each)".

### FXCHAN-2. `tools/native/s2layout.py`: two bytes of the tic-side block

```
     ('LS_X', 4), ('LS_Y', 4), ('LS_ANGLE', 4),
+    ('LS_ON', 1), ('SND_SFXVOL', 1),
 ]
```

(61 of 61 B). Then `fxchan.py`'s `S2T_EXTRA` and its two lines in
`inc_text` go. SCREENS.md 4.4's row `$E443-$E47F`: "... the listener's
last x, y, angle and whether there is one (13 B), `snd_SfxVolume` (1 B)
| 61 of 61 B". `SND_SFXVOL` is upstream's `snd_SfxVolume` (0-15): the
defaults, a loaded game's settings and the sound page of the menu
(`s2menu2`) write it; `s2cap`'s field map can name it.

### FXCHAN-3. `docs/m11-parts/design.md` R4 (for milestone 10, GAME.md 3.1, 4.3, 4.4): the hooks as built

Replace R4 item 1's first three bullets and item 2:

```
   - `S_StartSound` hook: `GA+0-1` the sound id (with upstream's
     `PICKUP_SOUND` bit), `GA+2` the origin's kind (`ORG_NONE` for none,
     with `GA+3-4` = $FFFF; `ORG_PLAYER` when it is the player's mobj;
     else `ORG_MOBJ`), `GA+3-4` its handle, `GA+5-12` its x, y (fixed, 4 B
     each, from `mo_get`; `ORG_MOBJ`), then `FCALL sc_start`;
   - `S_StartSound2` hook: `GA+0-1` the sound, `GA+5-12` the degenmobj's
     x, y (the sector's sound origin), then `FCALL sc_start2`;
   - `S_StopSound` hook: `GA+2-4` the origin's kind and handle as above,
     `FCALL sc_stop`;
2. The callback `s2t_pos` in the tic image: A:X a mobj handle (A the high
   byte) → its x, y (fixed) and angle in `GT+0-11`, carry clear, through
   `mo_get`; the handle $FFFE is the listener, the player's mobj, carry
   set when the player has none. It may change A, X, Y, `GT_*`.
```

and in item 3: `fx_chan`'s scratch block is the symbol `fxc_scr` (23 of
32 B), its size about 1,100 B (FXCHAN-5); the tic image links the
game's `math.s` (`mul32`, `sdiv32`, `pta3`, `sineapprox`) and the card's
`fx_isplaying` (`fx-card.o`). `sc_update` asks nothing when there is no
listener (it is upstream's `musFrame` test).

### FXCHAN-4. For part `s2menu1` (MENUW), and `s2lay`'s map

`MENUW` links `fx_chan` assembled with `-D FXC_NOSEP` and `fx_pcache`
(its `s2t_pos`), and `fx-card.o` (it does for `fx_service`); a 32-byte
`fxc_scr` among its runtime ranges (stand-in: `$BEE0`, the last 32 B of
its fetch buffer, dead outside a patch draw; `fx_pcache.s -D FXC_MSCR`);
its `sc_start` and `sc_update` use zero page `$48-$74` (`GA_*`, `GT_*`,
over `S2_ZP`: no drawer value may live across them) and the math block.
The menu's sound volume writes `SND_SFXVOL` (FXCHAN-2).

### FXCHAN-5. The budgets: `tools/native/s2layout.py`, SCREENS.md 4.1, 4.7, 7.3

`SHARED_BUDGETS['fx_chan']` 700 → 1,100; SCREENS.md 4.1's size table
(the `fx_chan` row 1,100; `MENUW`'s total 16,000 / 16,896), 4.7's row
(`fx_chan.s` 1,100 B), 7.3's fxchan budget ("1,100 B, `fx_pcache` 90
B"); GAME.md's placement input (design.md R4 item 3: "about 900, 150,
250 and 1,100 B"). Evidence: section 5.

### FXCHAN-6. `docs/SCREENS.md` 3 and `tools/sound/README.md` "The game side", "Tests": as built

In SCREENS.md 3, comparison 3, after "a path with none fails the
checkpoint": "(`getChannel`'s same-origin stop [R `s_sound65.s:293-302`]
is unreachable after `S_StartSound`'s kill of the same origin and kind
[R `:245-258`]: named, not required; `docs/m11-parts/fxchan.md` 3.1)";
and after comparison 1's list: "The positions are the deltas upstream
holds in registers inside `adjustParams` (dump points at its JSL to
`R_PointToAngle3` and its loads of the view angle) and `absDelta`'s
|delta|, from a listener at (0, 0) or `FM`: upstream's arithmetic uses
only differences modulo 2^32 (`fxchan.md` 3.2)". In "The game side",
after its first paragraph: "The routines read their arguments in
`GA_*` and ask `s2t_pos` for every position, the listener as the handle
$FFFE; `MENUW` links them with `-D FXC_NOSEP` and `fx_pcache`
(`docs/m11-parts/fxchan.md` 2)." In "Tests", the `fxchan` row: "...; the
3-channel build equal to `fxchan.py` on the captured streams and 10,000
random sequences; the menu's paused frame".

## 8. Stand-ins (marked in the code)

| Stand-in | Where | Until |
| --- | --- | --- |
| The channel record's `FC_*` offsets, `FC_PICKUP` | `tools/sound/fxchan.py` `FC_FIELDS`, generated into `fxchan.inc` | FXCHAN-1 |
| `LS_ON`, `SND_SFXVOL` at `S2T_BASE + 59`, `+ 60` | `fxchan.py` `S2T_EXTRA` | FXCHAN-2 |
| `GA_*`, `GT_*` bases, `G_GAMEMAP` | `fxchan.inc` from `glayout.py`/`llayout.py` (read only) | milestone 10's `ggame.inc` in the tic image |
| `fxc_scr` in `MENUW` at `$BEE0` | `fx_pcache.s -D FXC_MSCR` | FXCHAN-4 |
| The test machines' `s2t_pos`, `fx_isplaying` | `fx_cdrv.s` | test only |

## 9. Open problems

1. **The sizes** are over their budgets (FXCHAN-5).
2. **The shared includes cannot be remade now**: `s2layout.py --inc`
   fails its check on milestone 10's work in progress
   (`src/native/game/flow/gflow.s:893 writes the phase 31, the
   platform's`, `FL_PH_RESUME`). `fxcrun.make` then builds with the
   existing `build/native/m11/shared/gen` (make `-o`) and says so; the
   check must pass again before the integration.
3. The positions are reconstructed from deltas (3.2), exact for upstream's
   arithmetic but not the mobjs' places; the cost of milestone 10's real
   `s2t_pos` (`mo_get`) is not in section 6.
4. The 8-channel runs never fill the table: the evictions, `gc:none` and
   the failed starts come only from synthetic cases; no captured start
   failed.
5. Only one paused `docVolume` (and 3 paused stops) is compared: the
   menu's gray conversion outlasts the sounds (3.3).
6. The 3-channel replay's voices are a host stand-in for `fx_service`
   (3.2), not fxplay's voice choice; the 3-channel build is compared
   with the model, the model with the reference in 8 channels.
7. An update's separation is computed in the tic image only to equal the
   reference's (2.4); dropping it there too (about 40 us a positional
   channel a frame) would need the comparison to drop `SS_SEP` in
   updates: the owner's or the integrator's call.
8. The part took much longer than its 1.5 hours.

## 10. The wave 4 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.8, "Wave
4 as integrated"):

| Request | Outcome |
| --- | --- |
| FXCHAN-1 | Applied as written: `CHAN_FIELDS` (`CH_SFX`, `CH_KIND`, `CH_HANDLE`, `CH_X` 4, `CH_Y` 4), `CHF_PICKUP` `$80`, `CHF_KIND` `$03` in `s2.inc` (`check()` keeps the flag off the origin kinds); `fx_chan.s`, `fx_pcache.s` renamed (`FC_*` to `CH_*`: `FC_X`, `FC_Y` also met `glayout`'s zero page `FC_X`, `FC_Y`, `FC_A`); `fxchan.py`'s `FC_FIELDS` and its lines in `inc_text` gone |
| FXCHAN-2 | Applied **at another place**: the tic-side block's two spare bytes went to S2STBAR-1 (the block cannot grow: `$E480` is S2's write lists), so `LS_ON` and `SND_SFXVOL` are `s2layout.SC_EXTRA`, after the mailboxes (release and test `$E8F0`, `$E8F1`: the channel block 50 of 64 B; `M11` `$EE70`, `$EE71`; `FXCH8` `$E080`, `$E081`, its room now `$E000-$E0FF`, the song ring's place). `fxchan.py`'s `S2T_EXTRA` gone; `fxcrun.out_ranges` reads FM and the listener (`S2T_RUN`, 20 B) and the two bytes apart and joins them in `Out.s2t` as before; `fxcap.case_of` and `state_case` poke the two runs |
| FXCHAN-3 | Applied to `design.md` R4 items 1-4 |
| FXCHAN-4 | Nothing to apply now: for `s2menu1` (the `fxc_scr` stand-in at `$BEE0` stays) |
| FXCHAN-5 | Applied: `SHARED_BUDGETS['fx_chan']` 1,100, `DESIGN_TOTALS['MENUW']` 16,000 (of 16,896), `fx_pcache` 90 (`fxcap.PCACHE_BUDGET`); SCREENS.md 4.1, 4.7, 7.3; `design.md` R4 item 3. `wip_test_m11_fxchan.test_sizes` now requires the budgets |
| FXCHAN-6 | Applied: SCREENS.md 3 (comparisons 1 and 3); `tools/sound/README.md` "The game side", "Tests" |

Also: `fxcrun.make()`'s fallback to the existing includes (`make -o`) is
removed; `fxchan.mk` and `fxplay.mk` both defined a rule for
`build/sound65/tables.inc`, which made `make -f m11.mk` warn: both now
hold the same rules for S2's objects inside `ifndef M11_SOUND65_RULES`.

Results after the integration [M]: `python3 tools/native/fxcap.py
--check --jobs 2` (1 min 43 s) ok: the five runs' calls as section 3.1
(demo3 1,218, DEMO1 2,290, DEMO2 1,273, the tour 137, the menu 709), 134
eviction cases, no path missing, the menu 6 paused and 1 volume, the
3-channel replay 0 failures, 10,000 random sequences (35,041 calls) 0
failed; `--planted` the seven caught with the same messages; sizes
`fx_chan` 1,085 B (tic image), 970 (MENUW), 1,091 (FXCH8 traced),
`fx_pcache` 85 B.
