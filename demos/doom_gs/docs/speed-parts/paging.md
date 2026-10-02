# Speed plan, wave 1, part `paging`: the one-window group copy and the lazy restore

Written 2026-10-02 for the integrator (SPEED.md section 7). This part covers SPEED.md section 4, items 2 and 14. It changes only time: the game's state, its frames and the demo's sync are the same.

## What it does

### 1. The one-window group copy (`far_gcopy`)

- **gr_load** (`gcall.s`) used to call `far_get` once per page. Each call opened its own RAMRD window and ran a `cpy` loop: 100.3 µs a page. Now it sets `FA_BANK`, `FA_SRC`, `FA_DST` and `FA_N` (the group's pages) once and makes one `jsr far_gcopy` per group.
- **far_gcopy** in the play build is the kernel's (`dl_kern.s`). It runs in the main card at `$FFD5-$FFF9`, `KERN_GCOPY` in `glayout.py`.
  - It opens one RAMRD window per group.
  - It copies with `lda (FA_SRC),y / sta (FA_DST),y / iny`, twice per loop, then `bne`, then `inc` both page bytes, `dec FA_N`, `bne`.
  - It ends with `RAMRDOFF` and `RWBANK` 0, as `far_pload` does.
  - It must run in the card because, with RAMRD on, opcode fetches from `$0200-$BFFF` come from the bank.
- **How each image finds it.** `glayout.py`'s `game.cfg` defines `far_gcopy` as a **weak** linker symbol at `KERN_GCOPY`.
  - The play tic image links no `far_gcopy` of its own, so its `jsr` goes to the kernel's routine. `playlink.py --tic-cfg` keeps the `SYMBOLS` block.
  - Every `game.mk` image (lockstep, gprof, release, skel and the parts' test images) links `gdriver.s`. `gdriver.s` exports its own `far_gcopy`, which overrides the weak symbol.
  - `dl_kern.s` asserts that its routine is at `KERN_GCOPY` (`lderror`) and that it ends before the vectors.
- **The test driver's far_gcopy** (`gdriver.s`) is gr_load's old loop: `far_get` one page at a time, with the pages counted in `FC_PS`. The test images therefore behave and time as before, for two reasons:
  - The parts' write checks (`gparts/*.py` `stray`) allow stores into the slots only from `far_get`'s PCs (RFAR).
  - `gselftest.py`'s three `fcall` plants still apply verbatim and are still caught (`fcall-flags-lost` depends on `gr_load` changing `FC_PS`).
- **Why not the FAR-area home ((a) in the task).** `far.o` is linked by about 15 images whose cfgs this part does not own (`level.cfg`, `s2layout.py`, the m11 builds and others). A new segment after MFAR would also need `grun.CARD_SEGMENTS`, `lrun.card_records`, `pldisk.card_images` and the parts' `stray` checks to accept it. Home (b) needs none of that, and no address in the far layer or in any render image moves.

### 2. The lazy restore (`gcall.s` `fc_go`, `fc_ret`)

- **SLOT_NEED** (2 B, `RT_FIELDS` after `SLOT_GRP`, at `$19EF-$19F0`) holds, for each slot, the group that the slot's innermost active FCALL frame needs, or `$FF` for none. It is indexed `SLOT_NEED - 1 + slot`.
- **fc_go** pushes `SLOT_NEED[slot]`, or `$80 | slot` when it is `$FF`, then sets `SLOT_NEED[slot]` to the target's group. It loads the group only when `SLOT_GRP[slot]` differs.
- **fc_ret** pops the saved value:
  - `$80 | slot`: it sets `SLOT_NEED[slot]` back to `$FF` and loads nothing.
  - A group: it makes that group the slot's need again and reloads it only when the slot now holds another.
- The stack cost is unchanged: 1 B a call, 5 B an FCALL (`FCALL_STACK`).
- **Why this is safe.** Only a frame entered through `fc_go` runs in a slot. `gflow.s`'s `fl_timed` preloads with `gr_load` and then enters through `fc_go`. So every frame that returns into a slot finds its group there, as with today's rule (review 1's nested cases still hold). `gtest.s`'s S5 marker sequence is unchanged; I traced it by hand.
- **The resets.** `SLOT_NEED` is reset with `SLOT_GRP`:
  - in `dl_kern.s` `k_tic`;
  - in `gdriver.s` `drv_game` and `core_in`. The renderer's scratch overlays the runtime's state, and no FCALL frame is active at those points.

## The check (the owner's rule: one lockstep run)

The run was in a scratch APFS clone of HEAD plus these four files. Other parts' uncommitted edits were left out.

```
python3 tools/native/ticrun.py --run demo3 --frames front --fills a5 --jobs 2
```

Result: `ok`. Gametics 1051-3185, 2,134 tics compared, 0 failures, `same_pair_hits` 1009/1009 with no tic differing. The run took 175 s.

The lockstep image runs the lazy restore and the new `gr_load`, but its `far_gcopy` is the test driver's. The kernel's one-window copy runs only in the play build, so I also checked it there (a kernel change: a scripted run of that feature):

- **What I compared.** The demo3 timing runs below took an SHR shot at every `K_END` from frame 1040 on, in both the base build and this one. I compared the shots at equal gametics.
- **Result.** All 198 frames that both builds drew, gametics 1041-1796, have identical screens: the header plus aux `$2000-$9FFF`.
  - Every base frame falls on a gametic that this build also drew, because both run 4 tics a frame.
  - The main-memory half of a shot differs on the title frames, because W then holds the tic image, whose core grew by 10 B. That half is code, not the screen.

No frame8 run was needed: no render image and no far-layer byte changed. Only the kernel's part of the card changed.

## Measured gain (a2vm f121)

**How it was measured.** The scratch profiler a2vm (`frameprof/keep/a2vm-main.patch` + `pcprof.inc`) and the SPEED.md commands, with the driver copied to `scratchpad/paging/prun.py`. The base is HEAD's play link, rebuilt byte-identical to the owner's `build/native/play` (`cmp` of `tic.core`, `plboot.plat`, `plboot.boot`). "Card-eq." means `NOIDLE=1` (SPEED.md 1).

**The labels.** In this build, the kernel's `run` dispatch (`tax`) moves from `FF3B` to `FF41` because of `k_tic`'s two new stores. `gr_load` moves from `823A` to `824E`.

| Scene | Base | This part | Gain |
| --- | ---: | ---: | ---: |
| E1M1 standing still, 15-25 s, card-eq. | 180.7 ms, 5.53 FPS; K_TIC 112.1; 38.8 loads a tic | **143.7 ms, 6.96 FPS**; K_TIC 75.3; 36.6 loads a tic | −37.0 ms a frame |
| The same with the idle artifact | 190.6 ms, 5.25 FPS | 155.3 ms, 6.44 FPS | −35.3 ms (prototypes: copy 157.6, then −2.6 lazy) |
| demo3, gametics 1052-1796, card-eq. | 873.3 ms mean, 877.2 median, 1,656 max, 1.15 FPS; 240.9 loads a tic | **626.4 ms mean, 631.2 median, 1,180 max, 1.60 FPS**; 238.7 loads a tic | −246.9 ms a frame |

The demo3 frame count is the same in both builds (186 frames, 4 tics each), so the same game frames are compared. On the K_TIC step's own time, kern.py's 37-200 s window gives 785.3 ms base against 561.3 ms here, but that window covers more gametics in the faster build.

Commands (from `scratchpad/paging`, with `APPLETINI_ROOT=/Users/henri/Documents/Repos/appletini-one`):

```
NOIDLE=1 PCS=FF3B,DE53,823A,F7E8 python3 prun.py still-base play-base f121 26 15 25 still.txt
NOIDLE=1 PCS=FF41,DE53,824E,F7E8 python3 prun.py still-mine play-mine f121 26 15 25 still.txt
KR=FF3B GRL=823A python3 kern.py still-base 15 25
KR=FF41 GRL=824E python3 kern.py still-mine 15 25
SHOTS=1040-1400 LIM=900000 NOIDLE=1 PCS=FF3B,DE53,823A,F7E8 python3 prun.py demo3-base play-base f121 200 37 200 demo.txt
SHOTS=1040-1400 LIM=900000 NOIDLE=1 PCS=FF41,DE53,824E,F7E8 python3 prun.py demo3-mine play-mine f121 200 37 200 demo.txt
KR=FF3B python3 gtic.py demo3-base 1052 1796
KR=FF41 python3 gtic.py demo3-mine 1052 1796
```

The demo3 gain is close to SPEED.md's "−274 today": about 240 loads a tic, each of a group's pages (up to 8), at about 36 µs saved a page.

The lazy restore saves only about 2 loads a tic (38.8 → 36.6 still, 240.9 → 238.7 demo3), as the prototype found.

## For the integrator

1. **The core grows by 10 B.** The play tic image's `LOADW` went from `$77F1-$98DB` to `$77F1-$98E5` (13,030 of 13,312 B). Part `place`'s core budget, `gplace.py`, which counts dl_hook, must include these 10 B.
2. **The kernel.** `far_gcopy` takes `$FFD5-$FFF9`, and the kernel's free bytes are now `$FFBE-$FFD4` (23 B). `playlink.py --sizes` reports "250 of 250 B" because `dl_kern.s` pads up to `KERN_GCOPY`.
   - If the kernel's code grows past `$FFD4`, the `.res` goes negative and the assembler stops.
   - The fix is then to move `KERN_GCOPY` in `glayout.py`. The tic image and the card are linked from the same `ggame.inc`.
3. **Measurement scripts.** Anything that hard-codes `FF3B` (the kernel's `run` dispatch) or `823A` (`gr_load`) must take them from `plboot.lbl` and `tic.lbl`; in this build they are `FF41` and `824E`.
   - In the SPEED.md scratch tools, these are the `KR=` and `GRL=` variables and `PCS=`.
   - Part `measure`'s `playtime.py` should read the labels.
   - The context PC `DE53` (far_pload) and the slot tags `$19ED/$19EE` (`SLOT_GRP` + 1, + 2) did not move.
4. **The runtime's state.** `SLOT_NEED` sits after `SLOT_GRP`, so `RT_TH` through `GO_LAST` move up by 2 B: `FC_LOADS` from `$19FA` to `$19FC`. Every user I found reads them through `glayout.RT` or the generated includes. The runtime's state now uses 130 of 256 B.
5. **ticrun `--timing`** (the gprof build) does not show the copy's gain. Its `far_gcopy` is the test driver's per-page `far_get` loop, kept for the parts' write checks. The play build is the measure of item 2.
   - To time the one-window copy in the lockstep build, the driver's `far_gcopy` would have to be the same loop as the kernel's. Then, together:
     - every `gparts/*.py` `stray` would need to allow slot stores from the driver's `far_gcopy` PCs;
     - `gselftest.py`'s `fcall-flags-lost` plant would no longer bite, because nothing would change `FC_PS`. It would need a new form, for example a planted `lda #0` in place of `@back:  lda FC_PS`.
6. **Docs to update.**
   - GAME.md 4.3's paragraph "on return restores the saved group …; a lazy restore … is an integrator lever" and the `gcall.s` row of the files table: the restore is now the lazy one described above.
   - PLAY.md 3 line 126: "slot cache tags (`SLOT_GRP`) are reset at each `K_TIC`" should add `SLOT_NEED`.
   - PLAY.md 4 and SPEED.md: the kernel holds `far_gcopy` at `$FFD5`.
   - SPEED.md section 5: these measurements.
7. **Unchanged.** No file of the far layer, the render images, the cfgs or `playlink.py` changed. `glayout.check()` passes. The game, skel and release builds and the play link build with no warnings.
