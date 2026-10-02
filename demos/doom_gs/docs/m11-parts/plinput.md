# Milestone 11, part `plinput`: input

Part `plinput` of wave 5 ([`docs/SCREENS.md`](../SCREENS.md) 1.5.3, 2.1,
2.4, 4.2, 6.5, 7.3), 2026-10-01. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `src/native/pl_input.s` | The shared object `pl_poll` (every frame image, 2.1): the policy of 2.4 (one //e key held, the auto-repeat ignored, a tap held for one poll, the Apple keys and the buttons as the pseudo-keys `$72`, `$73`, `$71`, `$70`), codes folded to upper case, the Doom keys' counts recomputed each poll from the at most five sources (a 23-bit mask before and after; the changes posted from Doom key 22 to 0, upstream `recount`'s order), the press's character, upstream's menu repeat (11 tics, then every 4, from `pl_time`), the key setup's capture (`PL_BIND`), the 15-entry queue with a poll that posts nothing when fewer than 7 entries are free (`$C000`'s strobe kept), the mouse card's X between two reads of its sequence byte, `PL_MDX`, the re-centring. Helpers `pl_bold`, `pl_mask`, `pl_diff` exported for `pl_keys.s`. 554 B [M] |
| `src/native/pl_keys.s` | What the boot and the menus call, apart from the poll: `pl_init` (`I_InitKeyboard`: the block cleared, `PL_BIND` idle, the mouse card's X window 0-`$FFFF` and X at `$8000`, the defaults), `pl_defaults` (`I_DefaultKeys`), `pl_bind` (`I_BindKey`: A = Doom key, X = //e code), `pl_action` (`I_ActionKeys`: A = Doom key, returns A, X, upstream's range order `$30`, `$20`, `$00`, `$40`), recount's events. 228 B [M] (request PLINPUT-5) |
| `src/native/pl_input.inc` | The two files' constants and the **STANDIN**s of requests PLINPUT-1 to -4 (`PL_KEYTAB` `$1F80`, `PL_MLX` = `PL_MSEQ`'s word, `PL_BIND` = the spare `$03ED`, `PLZ` = `S2_W`, 16 B) |
| `src/native/pl_it.s` | Test only: `plt_run` (snd_init, the clock, the mouse card on, `pl_init`, then a schedule of polls at given tics with the consumer's actions after each: drain, take `PL_MDX`, `pl_bind`, `pl_defaults`, the key setup's wait and take, `pl_action`); the boundary `plt_polled`; the phase 31 around `pl_poll` |
| `tools/native/plkeys.py` | The //e key table (128 entries of a Doom key and a character, upstream's `keyTable` format) and the names (at most 7 characters and a 0); `--inc` writes `build/native/m11/plinput/gen/plkeys.inc` (constants and the macros `plk_names`, `plk_keys`, `plk_chars`) for the menus |
| `tools/native/plmodel.py` | The host model (the devices as a2vm has them, the poll's rules, `pl_keys.s`'s routines), written from the design, and the 55 scripted sequences |
| `tools/native/plinput.py` | The a2vm runs (one sequence at 6, 10 or 35 polls a second under a profile, `--cost-timed`), their checks against the model at every poll, the write log's owners, the timing, the sizes, the planted bugs; `--checkpoint`, `--planted`, `--one` |
| `src/native/m11/plinput.mk` | `make -f m11.mk part P=plinput`: `plit` (P2DW's room, `s2_drv` with `-D PL_VBL`, `pl_irq.o`, the effect stand-ins, S2's `player.o` from `build/sound65`, read only) and `gen/plkeys.inc` |
| `tests/wip_test_m11_plinput.py` | 19 tests: the key table, the model on hand-written cases, the build, the sizes, `s2layout`'s check, the checkpoint, the eight planted bugs |

Build output: `build/native/m11/plinput/` (about 0.5 MB, `report.json`
the checkpoint's). Every run's directory is a `tempfile` directory under
`build/` (`tmp-m11-plinput-*`) that the caller deletes.

### 1.1 The interface (for the frame images, the menus, the boot)

| Item | As built |
| --- | --- |
| `pl_poll` | A = nonzero while a menu is up (upstream's `_g_menuactive` test in `repeat` [R `i_iigs65.s:818-855`]; `MENUW` passes its own, `P2DW`, `WIW`, `FINW` 0). Clobbers A, X, Y, `PLZ` (`$5A-$69`). Stack 14 B [M, with the glue's call]. Calls `pl_time` |
| An event | 3 bytes: the type (`EV_KEYDOWN` 0, `EV_KEYUP` 1), then data1 as upstream's `event_t`, a word: a Doom key 0-22 or a character ≥ 23 [R `keys.inc:1-3`], its high byte 0 |
| The queue | A ring of 15 entries at `PL_QUEUE`; `PL_QTAIL` the next in (the poll's), `PL_QHEAD` the next out (the consumer's: `D_PostEvent` takes events from `PL_QHEAD` and advances it by 3, mod 45); empty when equal, so 14 hold events |
| `PL_MDX` | The X motion since the consumer took it (upstream's `iigs_mousedx`, right positive); the consumer zeroes it |
| The key setup | The menu writes `PL_BIND` = `$FF` (upstream's `iigs_bindwait`); the poll writes the first new press there (a //e code, or `$70-$73`) and makes no event for it; the menu reads a code below `$80`, calls `pl_bind` and writes `$80` |
| `PL_KEYTAB` | The Doom key of each //e code, 128 B (PLINPUT-1); written only by `pl_keys.s` |
| The table for the menus | `plkeys.inc`: `plk_names` (128 × 8 B), `plk_keys`, `plk_chars`; `pl_action` answers from `PL_KEYTAB` |
| `pl_init` | At boot, after the mouse card's mode (`$09`) is set (the boot's, 2.5) |

### 1.2 Choices the design left open, and why

| Choice | Why |
| --- | --- |
| A poll with fewer than 7 free entries posts **nothing** (no key, no Apple key or button change, no repeat), not only "no new key" | Each of those is an event the poll could not be sure to post; all of them are state the next poll reads again (the strobe stays set, the buttons and Apple keys are levels, the repeat's time stays due). The mouse is still read (no event). Nothing is ever lost or dropped |
| Characters as upstream's: letters (lower case), digits, the arrows, RETURN, DELETE only | 2.4: "as upstream's" [R `i_iigs65.s:109-246`]; `s2state.apple2e_keys()`'s stand-in gave every printable code a character and ESC `$1B` (PLINPUT-6) |
| A code pressed again after its release between two polls (`$C010` clear, the strobe set) is a press: its character again, held one poll; its Doom key does not go up and down | The counts are recomputed from the sources before and after the poll (2.4), which both hold the key; upstream's ADB ring would post the up and the down |
| The key setup's capture stays held (its auto-repeat ignored) but out of that poll's masks | Its later release posts an up of a Doom key that never went down (`gamekeydown` only cleared); a capture made not held would come back as a press at its first auto-repeat |
| The menu repeat posts at most one character a poll | As upstream's, at most one a call [R `i_iigs65.s:818-855`] |
| `pl_init`'s mouse window (0-`$FFFF`) and centre | As the kernel's `input_init` [R `demos/doom/src/kernel/input.s:118-130`]; the card's default window is 0-1023 [R `tools/a2vm/a2vm.c:80-85`] |

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
make -C src/native -f m11.mk part P=plinput        # no warning
python3 tools/native/s2layout.py --check           # passes with the new sources
python3 tools/native/plinput.py --checkpoint --jobs 2   # 6 s
python3 tools/native/plinput.py --no-build --planted --jobs 2   # 27 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_plinput.py  # 19 tests, 37 s
python3 tools/testpar.py --jobs 2 tests/test_sound_*.py          # 7 modules, 152 tests
```

Results [M, 2026-10-01; 69 GB free before the runs]:

| Item | Result |
| --- | --- |
| SCREENS.md 6.5's input row | **55 sequences** (`plmodel.sequences()`: 49 scripted and 6 random ones) at 6, 10 and 35 polls a second on `f121` and at 35 on `fastpath`, `--cost-timed`, PAL: **220 runs, 3,988 polls, 3,690 events; 0 problems**. At every poll the input block `$03B3-$03ED` (the queue's 45 bytes, head, tail, held key, buttons, `PL_MDX`, the last X, the repeat, the deferral count, `PL_BIND`) and the key table equal to `plmodel.py`'s, the clock's tics the poll's; every `pl_action` answer equal; the runs alternate the fills `$A5` and `$5A` |
| What the sequences cover | taps, holds, the //e's auto-repeat (of a letter, of an arrow, in the menu), two keys overlapping (other Doom keys, the same Doom key), taps between polls, two taps between polls, a key pressed again after its release, Open Apple, Solid Apple, both, fire shared by Open Apple and MOUSE 1, use shared by SPACE, Solid Apple and RETURN, both buttons, everything down then up, the mouse moving (slow, fast, both ways), re-centring both ways, the window's ends, `PL_MDX` kept across polls, a report between the two reads of X (twice, once re-centring), the menu's repeat (with and without the menu, the menu closing, another key stopping it, a tapped arrow), rebindings (a free key, the held key, while fire is held), the defaults back, `I_ActionKeys` for all 23 Doom keys and `NOKEY`, the key setup taking a key, a held arrow, a button and Open Apple, lower-case keys, typing `p`, every lower-case letter, every code 0-127, the control keys, a nearly full queue deferring keys, a deferred poll with the Apple keys and the mouse, a full queue in the menu's repeat, Ctrl-@ and the folded codes |
| The state only in `$03B3-$03ED` | The write log of every run judged by the code that made it (`plinput.owners`): `pl_input.o` writes only the input block, `PLZ` and the mouse's X (`$C0A1`, `$C0A2`); `pl_keys.o` also `PL_KEYTAB` and the mouse's window; 0 stray writes in the 220 runs |
| The IRQ bounds | `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF` held in every run (`pl_vbl` with S2's player idle) |
| The stack | 14 B at most below the driver's in the image's code (the glue's call of `pl_poll` and its nested calls), of the 2D phases' 64 |
| `s2layout.py --check` | passes (the phase scan reads `pl_it.s`'s phase 31: a platform source) |
| `tests/test_sound_*` | unchanged (no file of S2 edited) and green: 7 modules, 152 tests |
| Python 3.9.6 | `wip_test_m11_plinput` OK with `-W error::ResourceWarning` |
| `gen/plkeys.inc` | assembles with ca65; its three macros emit 1,024 + 128 + 128 bytes |

## 3. Planted bugs (each in a scratch copy) and the check that caught it

Each is built from a copy of `m11.mk`, `m11/s2lay.mk`, `m11/plinput.mk`
and the part's sources with one change (`plinput.PLANTED`), into its own
directory, then every sequence at 10 and 35 polls a second on `f121`.

| Bug | Caught by (the first problem) |
| --- | --- |
| The auto-repeat posting a key down (the held-key test removed) | 12 problems; "the //e auto-repeat @10: poll 3: `PL_QTAIL` 09, the model 06 (the queue [(0, 119)], the model [])": the repeat posted `w` again |
| The held key not going up when another comes (the new key held only when none is) | 42 problems; "two keys overlapping @10: poll 3: the queue [(0, 119)], the model [(1, 5), (0, 4), (0, 100)]; `PL_HELD` 57, the model 44" |
| The tap's up in the same poll (a tap not held) | 40 problems; "tap @10: poll 1: the queue [], the model [(0, 5), (0, 119)]; `PL_HELD` 00, the model 57" |
| The mouse's sequence byte not re-read | 12 problems; "a report between the reads @10: poll 4: `PL_MDX` 0001, the model 2c01; `PL_MLX` 1981, the model 4581" (the torn X) |
| The counts not shared by two keys of one Doom key (the mask's bit toggled, not set) | 22 problems; "fire shared: Open Apple and mouse 1 @10: poll 2: the queue [(1, 2)], the model []": fire went up while Open Apple was down |
| A lower-case code not folded | 18 problems; on "typing p (not MOUSE 2)" alone: "poll 1: the queue [(0, 15)], the model [(0, 112)]; `PL_HELD` 70, the model 50": `p` fired MOUSE 2's strafe |
| A full queue dropping a key instead of deferring it (the room test removed) | 5 problems; "a nearly full queue defers a key @10: poll 4: `PL_HELD` 53, the model 41; `PL_DEFER` 00, the model 01": the poll read `S` and lost an event |
| (Not one of 7.3's: the write log's check) the poll writing the byte below the block | 108 problems; "tap @10: 5 stray writes: pc $66CE (pl_input) wrote main 0 $03B2" |

## 4. Sizes against the budget

| Object | Bytes [M] | Budget |
| --- | ---: | ---: |
| `pl_input.o` (`pl_poll`; code 540, data 14), the row `pl_poll` of 4.1's size table in every frame image | **554** | 600 |
| `pl_keys.o` (code 164, data 64: the 28 defaults, the ranges) | 228 | none yet (PLINPUT-5 asks 300, `MENUW` and the boot) |
| `pl_input.o` and `pl_keys.o` together (the first build) | 782 | (600: over, hence the split) |
| `PL_KEYTAB` | 128 | (PLINPUT-1) |
| The test image `plit` | 989 of 7,424 in P2DW's room | |

## 5. Timing (SCREENS.md 6.4)

The poll alone, phase 31 (`pl_it.s` marks it around `pl_poll`), from the
cost report's line at each boundary; every poll of the checkpoint's runs
(an interrupt that lands in a poll counts in it):

| Profile | Polls | Median | p99 | Worst |
| --- | ---: | ---: | ---: | ---: |
| `f121` (6, 10, 35 polls a second) | 2,991 | 0.0435 ms | 0.0514 ms | 0.0554 ms |
| `fastpath` (35 a second) | 997 | 0.0434 ms | 0.0514 ms | 0.0553 ms |

No image load and no publish belong to the poll (it is linked into each
frame image). In the frame it runs first after the replay (2.1): its first
`$Cxxx` access waits for the replay's SHR bytes to drain on F1.2.1, which
the test image (no SHR write) does not have; that wait is the replay's
drain, reported by the frame's runs, not the poll's. A poll makes 9
`$Cxxx` accesses (`$C000`, `$C010`, `$C062`, `$C061`, `$C0A5`, `$C0A6`,
`$C0A1`, `$C0A2`, `$C0A6`), 2 more to re-centre, 3 more for a second read
of X.

## 6. Requests

Each with its evidence and the marked stand-in meanwhile. None touches a
milestone 10 file.

### PLINPUT-1. The key table's place: main `$1F80-$1FFF`

**Why.** The bindings persist across frames and images: each frame image
is loaded from its bank every frame (4.1), so a table linked into an image
would lose a rebinding; the input block has no room (59 B, 4.2); the card's
blocks are full (4.4: the tic-side block 61 of 61 B, the channel block 14
spare, `$F505-$F8FF` 36 B); main `$0880-$08FF` is free but rule 3 allows no
CPU store in `$0400-$0BFF` [R `MEMORY_MAP.md` 1 rule 3]. Main `$1EF9-$1FFF`
is in no layout's place (`glayout.regions()`' main rows end with the game
globals at `$1C80-$1EF8` [M]; `rlayout`, `llayout` have none there), in
`MEMORY_MAP.md` 3.3's persistent row `$1A80-$1FFF`; `$1F80` leaves the game
globals 135 B to grow. Written only by `pl_keys.s` (the boot, the key
setup); read by every poll.

**Stand-in.** `PL_KEYTAB = $1F80` in `src/native/pl_input.inc`, marked;
`plmodel.KEYTAB`.

**The change.** `tools/native/s2layout.py`, after `INPUT`:

```python
# the //e key table's Doom keys, 128 B (part plinput, request PLINPUT-1):
# persistent, written by pl_keys.s only (the boot, the key setup)
KEYTAB_PLACE = (0x1F80, 0x2000)
```

and in the `--inc` list beside the input block's names
`out += [('PL_KEYTAB', KEYTAB_PLACE[0])]`; in `problems_of()`, the place
checked against `glayout.regions()`' main rows (as the input block is) and
`rlayout`'s and `llayout`'s main places. Then `pl_input.inc`'s stand-in
line is deleted. `docs/SCREENS.md` 4.2, a row: "`$1F80-$1FFF` (128 B) |
`PL_KEYTAB`: the Doom key of each //e code (2.4), written by `pl_keys.s`
only | yes |". For the final integrator: `MEMORY_MAP.md` 3.3's row
`$1A80-$1FFF` names it (with R3's input block, `design.md` R2/R3).

### PLINPUT-2. `PL_MSEQ` and `PL_MX` become one word `PL_MLX`

**Why.** One byte of the last X cannot hold a motion of more than 127
counts between two polls (a poll every 167 ms at 6 a second); the kernel
keeps `last_x` a word and the sequence byte in a register for one poll's
two reads [R `demos/doom/src/kernel/input.s:186-234`]. The sequence byte
needs no persistent byte.

**Stand-in.** `PL_MLX = PL_MSEQ` (a word at `$03E6-$03E7`) in
`pl_input.inc`. No address moves.

**The change.** `s2layout.INPUT_FIELDS`:
`('PL_MSEQ', 1), ('PL_MX', 1),   # the mouse's sequence byte, last X` →
`('PL_MLX', 2),                  # the mouse's last X (low, high)`.
`docs/SCREENS.md` 4.2: "the mouse's sequence byte and last X `PL_MSEQ`
`$03E6`, `PL_MX` `$03E7`" → "the mouse's last X `PL_MLX` `$03E6-$03E7`".

### PLINPUT-3. The spare byte `$03ED` becomes `PL_BIND`

**Why.** Upstream's key setup takes the next key through `iigs_bindwait`
and `iigs_bindcode` [R `i_iigs65.s:50-52`, `:750-753`; `m_menu65.s:972-975` `bindAction`]; one byte holds both (`$FF` waiting, a code 0-`$7F` taken,
`$80` idle).

**Stand-in.** `PL_BIND = PL_DEFER + 1` in `pl_input.inc`.

**The change.** `s2layout.INPUT_FIELDS`, after `('PL_DEFER', 1)`:
`('PL_BIND', 1),               # the key setup: $FF waits, a code, $80`;
the comment "58 bytes used, 1 spare" → "59 bytes used". `docs/SCREENS.md`
4.2: "1 spare `$03ED`" → "the key setup's byte `PL_BIND` `$03ED` (`$FF`
waiting, the code taken, `$80` idle)".

### PLINPUT-4. The poll's zero page `PLZ`, `$5A-$69`

**Why.** The poll needs 16 bytes (two 3-byte masks, the new held key and
buttons, the character, the menu flag, the capture, the mouse's X). It
runs first after the replay, before any drawer (2.1), so the drawers'
temporaries `S2_W`..`S2_O` (`$5A-$69`, "free between calls" in `S2_ZP`)
are free then; `S2_BAND`..`S2_DRY1` (`$48-$59`, kept between calls) are not
touched.

**Stand-in.** `PLZ = S2_W` in `pl_input.inc`.

**The change.** `s2layout.py`: `PL_ZP = (0x5A, 0x6A)   # pl_poll's
temporaries (part plinput, PLINPUT-4): the drawers' S2_W .. S2_O, never
live across a drawer's call` and `('PLZ', PL_ZP[0])` in `s2.inc`, checked
inside `ZP_S2` and only over `S2_ZP`'s temporaries. `docs/SCREENS.md` 4.3,
the `$48-$7F` row: add "`$5A-$69` `pl_poll`'s temporaries `PLZ` (over the
drawers' temporaries; part `plinput`, PLINPUT-4)".

### PLINPUT-5. `pl_keys` in the size table

**Why.** The first build of all the routines in one object was 782 B
against `pl_poll`'s 600 [M]. `I_InitKeyboard` is the boot's and
`I_DefaultKeys`, `I_BindKey`, `I_ActionKeys` the key setup's (`MENUW`);
the poll alone is 554 B in every frame image.

**The change.** `s2layout.py`: `SHARED_BUDGETS['pl_keys'] = 300`,
`MODULE_ROW['pl_keys'] = 'pl_keys'`, `MENUW`'s shared objects
`(..., 'pl_poll', 'fx_service', 'fx_chan', 'pl_keys')`, `DESIGN_TOTALS
['MENUW']` 16,000 → 16,300 (of 16,896). `docs/SCREENS.md` 4.1's size
table, a row: "`pl_keys` `pl_init`, `pl_defaults`, `pl_bind`, `pl_action`
(`plinput`; 228 B [M]) | 300 | | x | | | | |" and the total 16,300 /
16,896; 7.3 `plinput`'s files: "`src/native/pl_keys.s` (the boot's and the
key setup's routines)". Part `plboot` links `pl_keys.o` for `pl_init`.

### PLINPUT-6. `s2state.apple2e_keys()` from `plkeys` (part `s2cap`'s file)

**Why.** It is the marked stand-in for this part's table [R
`tools/native/s2state.py:643-646`]. The names and the Doom keys are equal
to `plkeys`' (the test checks it); the characters differ at 34 codes: the
stand-in gives every printable code its own character and ESC `$1B`, where
upstream gives characters only to letters, digits and the menu keys [R
`i_iigs65.s:109-246`, `keys.inc:23-28`], as 2.4 asks.

**The change.** `s2state.apple2e_keys()`'s body: `from native import
plkeys; return plkeys.names(), plkeys.table()` (its docstring without
STAND-IN). The poked `keyTable`'s high bytes change; the key setup page's
drawing reads the names and the Doom keys only, so its cases keep their
screens, but `menus.script`'s captures dump `keyTable` (6.1 `PD0`) and
should be captured again.

### PLINPUT-7. `wip_test_m11_s2lay`'s phase test (part `s2lay`'s file)

**Why.** `test_phases` asserts that every source writes a phase 0-30 [R
`tests/wip_test_m11_s2lay.py:157`], which held only while no source wrote
31. 4.8 gives 31 to the platform's input poll; `pl_it.s` marks it around
`pl_poll` to time it (6.4), and `s2layout.problems_of()` already allows 31
only from `src/native/(pl|fx)_*.s` (it passes). **Until this is applied,
that test fails in the tree** (only it: `s2layout.py --check` passes).

**The change.** In `test_phases`:
`self.assertTrue(all(0 <= v <= 30 for _, v in found))` →
`self.assertTrue(all(0 <= v <= 31 for _, v in found))` and
`self.assertTrue(all(S.is_platform(w) for w, v in found if v == 31))`.

### PLINPUT-8. For `s2menu1`, `s2menu2`, `plboot` and the frame glue

Not a shared-file change: what they link and pass (`design.md` R7 may
carry it). Every frame image links `pl_input.o` and calls `pl_poll` with A
= its menu flag (1.1); `MENUW` and the boot link `pl_keys.o`; a makefile
that includes `plkeys.inc` adds `-I $(M11)/plinput/gen` and the rule of
`m11/plinput.mk` (`$(TOOLS)/plkeys.py --inc`). The consumer (the second
half's `D_PostEvent`) drains from `PL_QHEAD` and zeroes `PL_MDX` when it
builds a tic command.

### Text for `docs/SCREENS.md` 2.4 (the integrator's)

"a poll that finds fewer than 7 free entries reads no new key (it leaves
`$C000`'s strobe set, so the key waits for the next poll) and counts the
deferral" → "a poll that finds fewer than 7 free entries posts nothing: it
reads no new key (`$C000`'s strobe stays set), leaves the Apple keys, the
buttons and the repeat to the next poll, reads the mouse and counts the
deferral (part `plinput`)"; "(15 events of 3 bytes: type, Doom key or
character)" → "(a ring of 15 entries, 14 events, of 3 bytes: the type and
upstream's data1 as a word, a Doom key or a character)".

## 7. Open problems

1. **PLINPUT-7**: `tests/wip_test_m11_s2lay.py`'s `test_phases` fails
   until it is applied (the first source to write phase 31 is this part's
   test glue, as 4.8 allows).
2. **The menu's MOUSE option** (upstream's `iigs_mouseon` [R
   `iigs_asm.s:199-200`]: no moves and no button keys when off) is not in
   the poll; the block has no byte left. The consumer can drop `PL_MDX`;
   the buttons' events come through the key table. For `s2menu2` and the
   second half.
3. **Races on the real //e** that a2vm does not make: a key that arrives
   between the poll's `$C000` read and its `$C010` read is lost (a few
   cycles; a2vm delivers a tap only at a `$C000` read); a mouse report
   between the read of X and a re-centring loses its motion (as the
   kernel's, only when X leaves `$2000-$DFFF`).
4. **The runs place the events at the polls' boundaries** (and one inside a
   poll, between the two reads of X), not at given VBLs as 6.5 words it:
   between two polls the poll samples levels and a latch, so the VBL an
   event came at changes nothing the poll reads; a2vm's `boundary N` keeps
   the sequences the same at every rate.
5. **One key down on the //e** (risk 8): a second key's release while the
   first is still down leaves the second held until both are up (the //e's
   `$C010` is "any key"); the owner judges the feel at milestone 12.
6. A full `make -n -f m11.mk all` warns "overriding commands for target
   `build/native/m11/s2data/s2data.json`" (`m11/s2menu1.mk:50` against
   `m11/s2hud.mk:39`): another wave-5 part's fragment, not this one's;
   `part P=plinput` builds without a warning.

## 8. The wave 5 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.9, "Wave
5 as integrated"):

| Request | Outcome |
| --- | --- |
| PLINPUT-1 | Applied: `s2layout.KEYTAB_PLACE` `$1F80-$2000`, `PL_KEYTAB` in `s2.inc`, checked 128 B in `MEMORY_MAP.md` 3.3's `$1A80-$1FFF` and against every other layout's main places (rlayout, llayout, glayout); SCREENS.md 2.4, 4.2; `design.md` R3 for `MEMORY_MAP.md` 3.3. `plmodel.KEYTAB` reads it |
| PLINPUT-2 | Applied: `('PL_MLX', 2)` in `INPUT_FIELDS` (`$03E6-$03E7`, no address moved); `plmodel.OFF`'s stand-in and `describe_block`'s skip removed |
| PLINPUT-3 | Applied: `('PL_BIND', 1)` (`$03ED`; 59 of 59 B); its values `PLB_WAIT` `$FF`, `PLB_IDLE` `$80` are `s2.inc`'s (`pl_input.inc`'s `BIND_WAIT`, `BIND_IDLE` name them), because `MENUW` writes them too (S2MENU1-4 below) |
| PLINPUT-4 | Applied: `s2layout.PL_ZP` `$5A-$6A`, `PLZ` in `s2.inc`, checked equal to the drawers' temporaries `S2_W` .. `S2_O`; SCREENS.md 4.3. `pl_input.inc`'s four stand-in lines are gone; `plinput.PLZ_RANGE` reads it |
| PLINPUT-5 | Applied with a change: `SHARED_BUDGETS['pl_keys']` 300, `MODULE_ROW['pl_keys']`, `MENUW` links it. `MENUW`'s room shrank to 16,128 B in the same wave (S2MENU1-2), so 16,000 + 300 would pass it: `MENUW`'s own budget is 11,328 (names and strings 2,500 → 2,328) and its total the room, 16,128 (SCREENS.md 4.1). The test image `plit` now links in `MENUW`'s room (the image that has both `pl_poll` and `pl_keys` rows; in `P2DW`'s, `pl_keys` was a row its table does not list, which fails the build); same `$6600` start, so no address moved |
| PLINPUT-6 | Applied: `s2state.apple2e_keys()` returns `plkeys.names()`, `plkeys.table()`; the test `test_s2state_pokes_this_table` checks the whole table. No capture changes: `menus.script`'s captures are not poked (only `wip_test_m11_s2cap`'s `KeyPoke` test pokes, and part `s2menu2` will), so nothing was captured again |
| PLINPUT-7 | Applied as written to `wip_test_m11_s2lay.test_phases` (31 allowed, and only from a platform source: a stronger check, not a weaker one) |
| PLINPUT-8 | Recorded in `design.md` R7 item 10. `MENUW` (`s2_menu.s` `m_frame`: A = `G_MENUACTIVE`'s low byte) and `WIW` (`s2_wi.s` `wi_frame`: A = 0; it passed its own flags byte before) call the real `pl_poll`; both images link `pl_irq.o` for `pl_time` (in the card, `FXCODE`, as the release) under the test driver's handler |

**Fixed between the parts.** Part `s2menu1` expected the poll to write
`MENUW`'s `M_BINDCODE` and clear `M_BINDWAIT` (S2MENU1-4); the poll is
the same object in every image and cannot write one image's W state, so
the key setup uses `PL_BIND`: `r_bind` writes `PLB_WAIT`, `m_ticker` binds
a code below `$80` but Esc with `pl_bind` and writes `PLB_IDLE`. The
names `pl_bindkey`, `pl_defkeys` became `pl_bind`, `pl_defaults`.
`plinput.boot_records()` (the block as `pl_init` leaves it and the
defaults) and `plinput.image_owners()` (`pl_input`, `pl_keys`, `pl_time`'s
`CLK_TIME3` store) are what the other parts' checkpoints use. The
makefile warning of open problem 6 is fixed (one rule, inside `ifndef
M11_S2DATA_JSON_RULE`).

Still open: problems 2-5 of section 7 (the MOUSE option: `pl_mouseup`
stays a marked stand-in in `s2_menut.s`).

Results after the integration [M]: `python3 tools/native/plinput.py
--checkpoint --jobs 2`: 55 sequences, 220 runs, 3,988 polls, 3,690
events, 0 problems, stack 14 B, a poll 0.0435 / 0.0514 / 0.0554 ms
(`f121`); `--no-build --planted --jobs 2`: the eight planted bugs caught
(12-110 problems each); `wip_test_m11_plinput` 19 tests OK, also on
Python 3.9.6. In `MENUW` (`s2m1`) and `WIW` (`wiw`) `pl_input` is 554 of
600 B and `pl_keys` 228 of 300 B; the 7 menu opens run the real poll
under the write log with no stray write.

## The final integration of the first half (2026-10-02)

`plit` links part fxplay's `fx-card.o` in place of the stand-ins (`pl_it.s` calls `fx_init`; the write log's interrupt owner names `fx-card`). The checkpoint and the eight planted bugs pass again. The test is `tests/test_m11_plinput.py`. (`docs/SCREENS.md` 8.13.)
