# Speed plan, wave 2, part `glue`: the glue's tickers without a group load

Written 2026-10-03 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, item 7. It changes only where code and a scratch block live: no game state, frame or demo tic changes.

## What was measured first

Every tic ends the same way in the play build (a2vm f121, `playtime.py --keep`, the `gr_load` lines of `K_TIC` read by group):

```
... G31 G1 DLG_S DLG_H DLG_B
```

- `G_Ticker` (group 1, slot 2) calls `ST_Ticker` (core). Its `st_tick` jumps to `ST_TickerHook`, which loads `DLG_S` (5 pages) for `s2t_st`'s `st_ticker`.
- `HU_Ticker` (group 1) calls `HU_TickerHook`, which loads `DLG_H` (8 pages) for `s2t_hu`'s `hu_ticker`.
- The brain (`DLG_B`, slot 2) then comes back. `G_Ticker`'s group evicted it, as every slot-2 group of the tic does.

So the two glue tickers cost 13 pages and 2 loads a tic: 0.83 ms a tic at 63.8 µs a page.

**A guard that skipped `hu_ticker` was tried and dropped.** The guard skipped the call on tics where it changes nothing (no message up, none to take). It saved 1.3 ms a frame standing still but only 0.3 ms in demo3. In demo3 a HUD message is up on most tics (the fight picks up items), so `DLG_H` was still loaded 1.20 times a tic.

## What it does

1. **`hu_ticker` in the core.** `s2t_hu.s` assembled with `PLAY_TIC` puts its code (`hu_ticker` 80 B, `hu_start` 20 B) in `LOADW`, the core. `dl_hook.s`'s `HU_TickerHook` is then `jmp hu_ticker`, so no tic loads `DLG_H` for the HUD.
   - Without `PLAY_TIC`, both files assemble as before: milestone 11's test images (`s2ht`) and a play build without the define.
   - With it, `dl_hook.s` asserts at link time that `hu_ticker` is in `TW_CORE..TW_CORE_END`.
   - Milestone 11's `s2ht.img` rebuilt from the new `s2t_hu.s` is byte-identical to the old one. `s2hud.py`'s planted edits of `s2t_hu.s` still each match once.
2. **`fxc_scr` (32 B) and `hk_y` (1 B) in the core.** `dl_hook.s` used to hold them in `DLGH`.
   - Once `hu_ticker` is out of `DLG_H`, the tic ends with `DLG_S` in slot 1. The brain's `S_UpdateSounds` (`b_disp`: `DLCALL DLG_HOOK, sc_update`) therefore loads `DLG_H` once a frame.
   - `DLG_H` is now 1,775 B, which is 7 pages instead of 8.
3. **`ST_TickerHook` is unchanged.** `st_ticker` stays in `DLG_S`, the one small glue group a tic loads, in slot 1.
   - It does not contend with `G_Ticker`'s group 1 (slot 2) or with the brain.
   - The brain stays alone in slot 2.
   - Why it is not in the core: see "Not done" below.
4. **`gplace.py`'s core budget.** It already counted the play link's `dl_hook.o` (request P2, wave 1): the play build's fixed core is measured in its link (`GCORE` + `LOADW`), so `s2t_hu.o`'s `LOADW` bytes and `fxc_scr` are counted too.
   - New: `PLAY_GLUE_CORE` / `play_stale()`. When the play link's map is older than `dl_hook.s`, `s2t_hu.s` or `play.mk`, the report prints a WARNING line, because the fixed core it measured is the old link's. The result's `play_stale` lists those files.
   - `CORE_MARGIN` (16) is unchanged and applies to the largest fixed core.
   - The play build's fixed core is now 9,937 B. That is still below gprof's 10,073, so the table routines' room (3,223 B) and the placement do not change.
   - The play core is 13,139 of 13,312 B (`$6600-$9952`).
5. **`playlayout.py`**: the `DL_GROUPS` comments only (DLG_H no longer holds the HUD's ticker).
6. **`tests/test_play_glue.py`**: new class `Tickers`, test `test_hud_ticker_in_the_core`.
   - It checks that `hu_ticker`, `hu_start`, `HU_TickerHook` and `fxc_scr` are in the tic image's core and that `HU_TickerHook`'s bytes are `jmp hu_ticker`.
   - It fails on HEAD's play link (`hu_ticker $A024`): that is the plant.

## Requests for the integrator (files this part does not own)

1. **`src/native/play.mk`, line 60** (required; without it the build is HEAD's, and `test_play_glue.Tickers` fails):
   ```
   -TICFLAGS = $(ASFLAGS) -I $(TIC)/gen
   +TICFLAGS = $(ASFLAGS) -I $(TIC)/gen -D PLAY_TIC
   ```
   No other source of the tic image uses `PLAY_TIC`. The tic objects must be rebuilt after the change, because `play.mk` does not track flags. Use `rm -f build/native/play/tic/*.o`, then `python3 tools/native/playdisk.py`.
2. **The placement:** `python3 tools/native/gplace.py --write` after the play link is rebuilt with 1. Otherwise the report warns that the play link is stale.
   - This part moves no routine of the table, and the fixed core stays below gprof's.
   - With the recordings of 2026-10-02, `gplace.py` (search) returns the current placement unchanged: 3.169 ms a tic still, 21.339 demo3.
3. **`docs/PLAY.md`:**
   - Section 1, the row of `dl_hook.s`: "The tic image's core and group `DLG_HOOK` (slot 1); the HUD's ticker `s2t_hu.s` and `fxc_scr` in the core since speed wave 2".
   - Section 4: "core `$6600-$9952` (13,139 of 13,312 B)" and "`DLG_H` 1,775" (with this wave's other parts' figures).
4. **`docs/SPEED.md`** section 4, item 7: part glue built, with the figures below. Section 5 takes them with the wave.

## The checks (the owner's rule)

The checks ran in a scratch APFS clone of HEAD plus this part's six files and request 1. Other parts' uncommitted edits were left out.

- **`python3 -m unittest test_play_glue`** (from `tests/`): 9 tests, OK. The same `Tickers` test on HEAD's play link fails with "hu_ticker $A024 is not in the core".
- **One scripted DOOM.hdv run** (a2vm f121, 27 s; a scratch script, not in the tree).
  - **Script.** `test_play_runs`' new game and route to the health bonus (mouse 421 at 11 s, up arrow 11.3-13.4 s), then standing.
  - **Logging.** a2vm's `--pclog` at `HU_TickerHook` and `ST_TickerHook` (both in the core), with `HU_COUNTER`, `HU_ON`, player.message's tag, `G_GAMETIC`, `ST_FACEINDEX`, `ST_FACECOUNT` and `G_GAMESTATE`.
  - **Result:**
    - 608 level tics, with both hooks called on each.
    - The message is taken at gametic 172. At the hook's entry on gametics 173-312 the counter reads 140 down to 1 with `HU_ON` 1, one step a tic, no tic missed. At 313 it reads 0 with `HU_ON` 0. The message is up exactly 140 tics.
    - The status face changed 21 times (faces 0, 1, 2: it looks ahead, left and right).
- **One lockstep run:** `python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2`. Result: `ok`. Gametics 1051-3185, 2,134 tics compared, 0 failures, `same_pair_hits` 1009/1009 with no tic differing. The run took 108 s.
  - This checks the lockstep build only, which links `ghook.s`, not `dl_hook.s` or `s2t_hu.s`. Its image is the same as HEAD's, because this part changes no game source and no placement.

## Measured gain (a2vm f121, `playtime.py`, the exact idle)

| Scene | HEAD (the clone's play link) | This part | Gain |
| --- | ---: | ---: | ---: |
| E1M1 standing still, 15-25 s | 88.4 ms (median 87.4), 11.32 FPS; K_TIC 24.78; 11.47 loads, 52.8 pages a tic | **87.0 ms (median 86.4), 11.49 FPS**; K_TIC 23.45; 10.81 loads, 47.2 pages a tic | **−1.3 ms a frame**, +0.17 FPS (−0.32 ms a tic) |
| demo3, gametics 1052-1796, 186 frames | 272.1 ms (median 271.8, max 634.5), 3.67 FPS; K_TIC 188.90; 63.5 loads, 349.5 pages a tic | **270.5 ms (median 270.4, max 634.1), 3.70 FPS**; K_TIC 187.25; 62.75 loads, 342.9 pages a tic | **−1.65 ms a frame**, +0.02 FPS |

```
python3 tools/native/playtime.py --scene still --profile f121
python3 tools/native/playtime.py --scene demo3 --profile f121
```

- **Where the time went.** Each tic now loads `DLG_S` only (5 pages), not `DLG_S` and `DLG_H` (13). Each frame now loads `DLG_H` once for the brain's `sc_update` (7 pages). demo3 saves 6.6 pages a tic; still saves 5.6.
- **Against the plan's expectation** (−2 to −4 still, −3 to −5 demo3): short by about 1 ms still and 1.5-3 ms in demo3. Two things account for it:
  - The status bar's ticker still loads its group on every tic (5 pages, 0.32 ms a tic).
  - The brain's per-frame `sc_update` now pays for `DLG_H`.
- **On the card**, scale by about 1.14 (SPEED.md 5, the card's rows): about −1.5 ms still and −1.9 ms in demo3.

## Not done, and why (measured)

- **`st_ticker` in the core.**
  - Its module is 888 B (`S2TCODE` 877 + `S2TRODATA` 11), and its scratch block `st_sb` is `dl_snd.s`'s, in `DLGS` (`DLG_S`).
  - The core has 136 B before the play build's fixed core passes gprof's. The other ~750 B would come out of the table routines' 3,215 B, which are 8 routines.
  - `gplace.py --core-reserve 560` cannot even repair the start placement ("the core: 2701 + 10073 B").
  - A 4-page group of `st_ticker` alone (5 pages now) needs `st_sb` out of `dl_snd.s` (not this part's file), for −1 page a tic.
- **Found, for its owners: the brain's command builder swaps with group 10 in demo3.**
  - `dl_cmd.s`'s `G_BuildTiccmd` (`DLG_C`, slot 1) does `FCALL P_CheckAmmo` (group 10, slot 1) whenever attackdown is set.
  - In demo3 that is 2.17 times a frame, measured in this part's build. Each time it loads group 10 (4 pages) and then `DLG_C` again (7 pages): about 24 pages, **≈1.5 ms a frame in demo3**. Standing still it is 0.06 times a frame.
  - `DLG_C` grew from 5 to 7 pages with the benchmark's timing (SPEED.md, "two glue groups a few pages longer"), which made each swap dearer.
- **The brain's reload every tic** (`DLG_B`, 5 pages, 1.25-1.32 loads a tic): every slot-2 group of a tic evicts it.
  - Its tic loop in the core would make that once a frame: about −1 ms still and −1.3 ms in demo3, estimated from the counts.
  - That is `dl_brain.s`'s, and it needs core room the play build has only 136 B of.
