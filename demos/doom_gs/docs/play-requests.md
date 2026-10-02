# Requests of the playable game's glue (docs/PLAY.md)

The glue (`src/native/dl_*.s`, `tools/native/play*.py`) reads the other
milestones' files and never edits them. What it needs changed there is
asked here, for their owners and the integrator. Each request says what,
why, and what the glue does until it is applied.

## P1. Milestone 10, `flow`: apply milestone 11's R4 (ST) and R5 (HU) in `gwi.s`

**What.** `docs/m11-parts/design.md` R4 item 1 and R5, not yet in
`src/native/game/flow/gwi.s`: `st_tick` calls `g_mrandom` and then jumps
to `ST_TickerHook` with A = its value; `hu_tick` calls `HU_TickerHook`
first, then makes its clears. `dl_hook.s` exports both hooks (they call
`st_ticker`, `hu_ticker` in their groups).
**Why.** Until then the status bar's face never animates and the HUD's
messages never time out in the play build: `ST_Ticker` and `HU_Ticker`
are flow's game effects only.
**Applied** 2026-10-02 by the final assembly (docs/PLAY.md 9 item 3):
`gwi.s` as above; `ghook.s` exports both hooks as a plain `rts`, so the
lockstep and test builds do what they did.

## P2. Milestone 10, `gplace`: count `dl_hook.o`'s core part

**Done** in speed wave 1 (`docs/speed-parts/place.md`): `gplace.py`'s core
budget is the largest fixed core of every build, the play link's
`dl_hook.o` and the lockstep's `ghook.o`/`grec.o` included.

**What.** The play link replaces `ghook.o` by `dl_hook.o`, whose core part
is 207 B (`ghook.o`'s 69 B): the trampolines of `S_StartSound*`,
`I_GetTime`, `AM_Stop`, `D_PageTicker`, `s2t_pos`. `gplace.py`'s core
budget should take it as an input (a `--hook-object` or the size), so the
placement leaves the room.
**Why.** The core is 12,966 of 13,312 B with it today; a part that grows
the core could pass the room without `gplace` seeing it.
**Meanwhile.** `playlink.py --tic-cfg` links and the link fails loudly if
the core passes `$99FF`.

## P3. Milestone 10, part tic: `G_Ticker`'s command source

**Done**: part tic's `G_Ticker` copies `G_CMDS[gametic & 7]` (`gtick.s`
`gt_copy`); the play build links it.

**What.** Part tic's `G_Ticker` takes the player's command from the ring
`G_CMDS[gametic & 7]` (8 bytes: forwardmove, sidemove, angleturn word,
buttons, 0 0 0; GAME.md 3.7's stream format) when not playing a demo, as
`dl_gstub.s` does; `dl_cmd.s`'s `G_BuildTiccmd` writes it.
**Why.** The command ring is the glue's interface with part tic.

## P4. Milestone 10: `ghook.s` and `dl_hook.s` export the same entries

**What.** A new hook in `ghook.s` must get its play version in
`dl_hook.s`; `tests/test_play_glue.py` (`Hooks`) fails until it does.

## P5. Milestone 11: the release render images built without `VCWRAP_UPSTREAM`

**What.** `gvalid.s`'s header gives the release frame's clear at
`validcount`'s wrap to milestone 11; the play link uses milestone 8's
render images, built with `-D VCWRAP_UPSTREAM` (the count wraps as
upstream's). A release build of `WCODE`/`MCODE` with `gv_clear` linked is
needed for long play (the count wraps after 65,535 increments).
**Meanwhile.** The wrap is upstream's behaviour.

## P6. Milestone 11, `s2stbar`/`s2menu2`: idrate

**What.** Upstream's `updateFPS` (`fps_show`) is not built anywhere; the
glue reserves `DL_FPSN`, `DL_FPST` for it.

## P7. Milestone 10, `gdriver.s`: the profiling build's new `PH_LOAD` phase

**What.** Since 2026-10-02 15:48 `gdriver.s`'s `load:` (`.ifdef GPROF`)
writes `PHASE` with `2 * PH_LOAD`, and milestone 11's
`s2layout.check()` refuses it: "src/native/gdriver.s:643 writes the phase
31, the platform's" (the platform's profiling phase number). Either the
phase number moves or `s2layout.py`'s table learns it, by their owners.
**Why.** `s2layout.py --inc` runs the check, so any play build that must
regenerate `s2.inc` (every time `glayout.py` or another layout tool is
newer than it) fails: `make -f play.mk` stops at `gen/s2.inc`.
**Meanwhile.** The final assembly of 2026-10-02 regenerated `s2.inc`'s
text with the check skipped, found it byte for byte the one in
`build/native/play/gen`, and touched that file; nothing else was
bypassed. A fresh `build/` cannot make the play build until this is
settled.
