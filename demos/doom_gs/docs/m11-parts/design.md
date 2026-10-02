# Milestone 11, first half: the design's requests

Owner: the design of [`docs/SCREENS.md`](../SCREENS.md) (2026-10-01,
revised the same day after the review in its section 10: R2-R7 changed).
These are changes to files this half does not own. The integrator applies
each only if it does not collide with milestone 10's edits; milestone
10's files (`docs/GAME.md`, `src/native/g*.s`, `tools/native/llayout.py`,
`glayout.py`, `game.mk`, `tools/bridge/*`) are changed only by milestone
10's integrator, to whom R4-R7 go. Each part of this half keeps its own
requests in `docs/m11-parts/<part>.md` with the same headings.

**Status at the first half's final integration (2026-10-02,
`docs/SCREENS.md` 8.13):** R1 applied to `NATIVE.md` 10 and R2 (items
1-6) and R3 to `MEMORY_MAP.md` (sections 2, 3.1, 3.3, 3.5, 4.2, 5, 11 and
a new section 18): milestone 10 had not edited those lines. R4, R5, R6
and R8 wait for milestone 10's integrator; R7 for the second half's frame
driver; R9 for the final integrator (`LEVELS.md`); lever L5 (SCREENS.md
8.3) for milestone 8's integrator if the owner takes it. R2 item 7 (the
effect voices and rings as built, from the review of 2026-10-02) waits
for the integrator.

## R1. `docs/NATIVE.md` section 10, row "Clock"

**What.** Replace the row's text

> Mouse-card VBL: 7 tics per 10 VBLs on PAL, per 12 on NTSC [R
> `demos/doom/src/kernel/frame.s:4-5`]. Upstream's clock is 34.955 tics a
> second [M: MILESTONES].

with

> Mouse-card VBL: a 16-bit fraction a VBL, 45,743/65,536 on PAL and
> 38,229/65,536 on NTSC, so 34.955 tics a second on both, upstream's rate
> [M: MILESTONES]. (7 per 10 VBLs on PAL, the existing port's rule [R
> `demos/doom/src/kernel/frame.s:4-5`], gives 35.056, outside milestone
> 11's 34.9-35.0: `docs/SCREENS.md` 0.1 F2.)

**Why.** The PAL //e's VBL is 1,015,625 / 20,280 = 50.080 Hz [R
`tools/sound/README.md:63-73`; M: the card's timer count 20,281,
`docs/results/music-card-2026-09-30.md`]; 50.080 × 0.7 = 35.056 [A].
**Effect on others:** none; the clock is `plclock`'s.

## R2. `docs/MEMORY_MAP.md`

1. Section 4.2, row `$FFFA-$FFFF`: "IRQ/BRK → `snd_vbl`" becomes "IRQ/BRK
   → `pl_vbl` (milestone 11: acknowledge, clock, `fx_step`, `snd_tick`,
   `fx_burst`; `src/native/pl_irq.s`)". Row `$E900-$F8FF`: add "`pl_vbl`,
   the clock and `pl_time` (116 B), `pl_clkset` and `pl_detect` (128 B,
   boot-time; PLCLOCK-2), `fx.s`'s card part (`fx_step`, `fx_burst`,
   `fx_song`, `fx_init`, `fx_stopall`, `fx_isplaying`, `fx_copy`,
   `fx_volume`, chip 3's state: 739 B) from `$F505`, 983 of 1,019 B"
   (wave 3, FXPLAY-2). Row `$E403-$E412`: "IRQ
   state: VBL count, tic accumulator, tic counter" becomes "IRQ state
   (milestone 11, `pl_irq.s`): the fraction a VBL, the fraction, the tic
   counter, PAL or NTSC, `pl_time`'s fourth byte (10 of 16 B); the VBL
   count is `vbl_count` in the player's zero page" (wave 2, PLCLOCK-1).
   Row `$FF00-$FFF9`: "IRQ bridge landing (pair build)" becomes "the aux
   card's IRQ bridge, the same 30 B in both cards (`pl_bridge.s`; pair
   build only)" (wave 2, PLCLOCK-1). Row `$E443-$E47F` (spare):
   "milestone 11: the tic-side 2D state (the status bar's 26 B with
   `ST_READY` and `ST_RUNNING`, the HUD's, the finale's, `S2_MAIL`), `FM`,
   the listener (61 of 61 B, as integrated in wave 4: S2STBAR-1)". Row
   `$E737-$E73F` (spare): "milestone 11: `FX_ON`, `FX_HOLD`, `FX_INVAL`,
   the effects' tempo fraction, `fx_service`'s 4 temporaries (9 B)"
   (wave 3, FXPLAY-1). Row `$E8C0-$E8FF` (spare):
   "milestone 11: the channel table (3 × 12 B), the channels' mailboxes
   (3 × 4 B), `LS_ON` and `SND_SFXVOL` (50 of 64 B; wave 4, FXCHAN-1,
   FXCHAN-2)".
2. Section 5, row `$0200-$02BF`: replace "the status bar's read-mask-or
   ... the 79 B left" with "the status bar composes in W and never reads
   the screen (milestone 11, `docs/SCREENS.md` 1.2): the 79 B
   `$0271-$02BF` stay free".
3. Section 11, "Forbidden ranges", the memory-API line: "endpoints in
   `$0200-$BFFF` only, never the card, zero page, stack or aux 0
   `$2000-$9FFF`" becomes "endpoints in `$0200-$BFFF` only, never the
   card, zero page or stack; never a **destination** in aux 0
   `$2000-$9FFF` (a source there is allowed: the memory API copies the
   CPU's memory, `README_MEMORY_API.md` sections 3-4; milestone 11's menu
   saves the screen that way)".
4. A new section 18, "Milestone 11, first half: the 2D screens, the
   platform, the effects", with `docs/SCREENS.md` section 4's tables
   (4.1-4.5) as built, and section 3.5's W table gaining the rows of
   `P2DW`, `MENUW`, `AMAPW`, `WIW`, `FINW`, and the RamWorks banks of
   SCREENS.md 4.5 as integrated in wave 3 (S2DATA-5): 109, 110, 114,
   115 `GFX0`-`GFX3`, the 2D store (`GFX.1`; the handles table at 109
   `$0200`), bank 104 `S2STATE` `$0200-$B11F` (the state blocks, `STCACHE`,
   the HUD's records, the automap's old list, the sign's rows, `STBUF`
   and the HUD's texts `SS_HUDMSG`: wave 4, S2STBAR-2, S2HUD-3; the
   automap's clipped lines `SS_AMSEG`: wave 6, S2AMAP-2) with `$B200-$BFFF`
   free, and the store's parts of 103 (`$4000-$BFFF`), 105
   (`$0200-$1FFF`, `$A000-$BFFF`), 107 (`$0200-$5FFF`, `$8300-$BFFF`),
   108 (`$0200-$5FFF`) and 106 (`GSSTAT` `$5800`, `GSOVL` `$6E20`,
   beside `TINTPAL` `$0200`, `S2NIB` `$1800`, `GRAYMAP` `$7700`). As
   built in wave 1 (requests
   S2LAY-1 to -3 and -5 applied to SCREENS.md 4): the tables are `python3
   tools/native/s2layout.py --report` and the generated `s2.inc`; the
   code banks are 107, 108, 94, 95, 96, 97 (one image a bank), the input
   block `$03B3-$03ED`, the state blocks moved by `far_get`/`far_put`
   (SCREENS.md 4.6).

5. Section 2, page 1 (wave 3, S2PAL-4): after the replay's gather
   `$0100-$01B4`, "2D phases: `$0100-$017F` is `newColors`' bounce
   (`s2_begin`, milestone 11), outside the replay; the stack stays at or
   above `$01C0`".
6. The boot (wave 8, PLBOOT-6). Section 4.2, row `$FF00-$FFF9`: after
   "Platform: phase switch (card bank, RAMWRT, `$C073` 0), BRK and crash
   stub, IRQ bridge landing (pair build)" (as item 1 changes it) add "; the
   ready loop `pl_ready` at `$FF00` (8 B, milestone 11 part `plboot`)".
   Section 3.1, row `$0300-$03EF`: "zeroed at start" becomes "zeroed at
   start (`DOOM.SYSTEM`, with `$0200-$02FF`, `$0C00-$1FFF` and
   `$BF00-$BFFF`)".
7. The effect voices and rings as built (the review of 2026-10-02).
   Section 4.2, row `$E413-$E442`: "Effect voice state (3 voices) | A"
   becomes "Milestone 11: the effect voices, 3 × 16 B (`fx.s`;
   `s2layout.py` `VOICE_FIELDS`: `V_FLAGS`, `V_HEAD`, `V_LEFT`, `V_WPOS`,
   `V_RUN`, `V_PER`, `V_LEVEL`, `V_NOISE`, `V_RPOS`, `V_CHAN`, `V_ATT`,
   `V_SOUND`, 15 of 16 B each) | M: milestone 11". Row `$E740-$E8BF`:
   "Effect rings, 3 × 128 | A" becomes "Milestone 11: the effect rings, 3
   × 128 B (`fx.s`; `s2layout.py` `FX_RING`, `RING_SIZE`) | M: milestone
   11". Section 18, the card row: the ranges become "`$E403-$E442`,
   `$E443-$E47F`, `$E737-$E8FF`, `$F505-$F8FF`, `$FF00-$FF07`, `$FFFE`"
   (or `$E403-$E47F` in one) and the content "The clock, the effect
   voices, the tic-side 2D state, the effects' state, rings, channel
   table and mailboxes, the IRQ and effect code, `pl_ready`, the IRQ
   vector (section 4.2)".

**Why.** `docs/SCREENS.md` 1.2, 2.3, 1.5.3. **Effect on others:** none
on milestone 10's regions; the IRQ contract (rule 2) is unchanged.

## R3. `docs/MEMORY_MAP.md` section 3.1

**What.** Row `$0300-$03EF`: add "milestone 11: `$03B3-$03ED` the input
(event queue 15 × 3 B, its head and tail, held key, the Apple keys' and
buttons' state, mouse motion, the mouse's last X, repeat, deferrals, the
key setup's byte `PL_BIND`; 59 of 59 B); `$03AE` also the boot's status
(`PL_STATUS`)". Section 3.3, row `$1A80-$1FFF`: add "milestone 11:
`$1F80-$1FFF` the //e key table's Doom keys `PL_KEYTAB` (128 B, written
by `pl_keys.s` only)". (Wave 1, request S2LAY-3: the first text said
`$03B2`, which meets `GS_ARG`'s second byte. Wave 5, PLINPUT-1 to -3: the
mouse's sequence byte and last X became the word `PL_MLX`, the spare byte
`PL_BIND`, and the key table went to `$1F80`, above milestone 10's game
globals `$1C80-$1EF8`, which leaves them 135 B to grow.)
**Why.** The input poll runs in every frame image and its queue must
persist across frames and phases; the bytes are free since milestone 9
[R `MEMORY_MAP.md` 14-16] but `$03B0-$03B2`, milestone 10's `GS_STATUS`
(a byte) and `GS_ARG` (a word) [R `tools/native/glayout.py:147`, `:778`],
and `$03EE-$03EF`,
`PRND` and `MRND` [R `tools/native/llayout.py:467`]. **Effect:**
milestone 10 must not allocate `$03B3-$03ED` (it places its new globals
in `$1E6F-$1FFF` [R GAME.md 1.5]); `s2layout.check()` imports `glayout`
and fails on an overlap.

## R4. Milestone 10: the tic-side modules (GAME.md 3.1, 4.3, 4.4)

**What.**
1. `src/native/ghook.s`, in the release build and in a test build option
   `M11` (the lockstep and test builds keep today's event log):
   - `S_StartSound` hook: `GA+0-1` the sound id (with upstream's
     `PICKUP_SOUND` bit), `GA+2` the origin's kind (`ORG_NONE` for none,
     with `GA+3-4` = $FFFF; `ORG_PLAYER` when it is the player's mobj;
     else `ORG_MOBJ`), `GA+3-4` its handle, `GA+5-12` its x, y (fixed, 4 B
     each, from `mo_get`; `ORG_MOBJ`), then `FCALL sc_start` (the
     listener is not an argument: `sc_start` asks `s2t_pos` for it; wave
     4, FXCHAN-3);
   - `S_StartSound2` hook: `GA+0-1` the sound, `GA+5-12` the degenmobj's
     x, y (the sector's sound origin), then `FCALL sc_start2`;
   - `S_StopSound` hook: `GA+2-4` the origin's kind and handle as above,
     `FCALL sc_stop`;
   - after the frame's tics, in the driver's tic phase: `FCALL sc_update`
     once a frame (upstream's `S_UpdateSounds` from `musFrame` [R
     `s_sound65.s:1911-1922`]; it tests the player's mobj itself);
   - every song start (the level's, `W_StartInter`'s, the finale's, the
     title's) calls `fx_song` (card) in place of S2's `snd_start`;
   - `ST_Ticker` hook: after `flow`'s `st_tick` has called `M_Random`,
     `FCALL st_ticker` with A = its value (`st_tick` returns it in A [R
     `src/native/game/flow/gwi.s:623-630`]); `ST_Start` hook: `FCALL
     st_start`; the boot calls `st_init` once (wave 4, S2STBAR-4);
   - `W_StartFinale` and `F_Ticker` (today the stops `GS_FINALE`):
     `FCALL f_start`, `FCALL f_ticker`. As built (wave 6, S2FIN-4):
     `W_StartFinale` calls `f_start` (`src/native/s2t_fin.s`,
     `F_StartFinale`'s state: `G_GAMEACTION` 0, `G_GAMESTATE` `GS_FINALE`,
     `AUTOMAP`'s bit 0 cleared, `WI_ACCEL` and the card's `F_STAGE`,
     `F_COUNT`, `F_MID` 0); `F_Ticker` does `FCALL WI_checkForAccelerate`
     (flow's `gwi.s`), then `f_ticker`, as `st_tick` passes `M_Random`'s
     value. `s2t_fin.s` is 175 B [M], uses no zero page and no scratch
     block, changes A, X, Y, and reads `WI_ACCEL`, `G_GAMEACTION`,
     `G_GAMESTATE` by `lgame.inc`'s names; its tests link it in this
     half's test image (`s2ft`).
2. The callback `s2t_pos` in the tic image: A:X a mobj handle (A the high
   byte) → its x, y (fixed) and angle in `GT+0-11` (4 B each,
   little-endian), carry clear, through `mo_get`; the handle $FFFE is the
   listener, the player's mobj, carry set when the player has none. It
   may change A, X, Y and any `GT_*`; the modules keep what they need in
   their scratch blocks (wave 4, FXCHAN-3, S2STBAR-4).
3. In `glayout.py`: a 32-byte scratch block for each of `s2t_st`
   (`st_sb`), `s2t_hu`, `s2t_fin`, `fx_chan` (`fxc_scr`, 23 B used)
   (GAME.md 4.4's overlay rule: none of them is active while another is),
   and the four modules in `gplace.py`'s input with their sizes and call
   rates (about 900, 150, 250 and 1,100 B [M, wave 4: `s2t_st` 886,
   `s2t_hu` 100, `fx_chan` 1,085: FXCHAN-5]; 1 a tic, 1 a tic, 1 a
   finale tic, at most 4 starts a tic [M: `docs/SCREENS.md` appendix A]
   and `sc_update` once a frame). The segments `S2TCODE` and `S2TRODATA`
   (`s2t_st`'s `st_wammo`, 11 B), in the core or a group.
4. The tic image's math: `s2t_st` (`turnHead`) and `fx_chan` (the
   separation) call `pta3` (`R_PointToAngle3`), `sineapprox`, `mul32`,
   `sdiv32`, `sdiv16`; the tic image links `math.s` with `-D RENDER`
   (`math-r.o`), which has no `pta3`; the game's own `P_DamageMobj`
   thrust (GAME.md 2.4's `damage`) needs it too. `fx_chan` also needs
   the card's `fx_isplaying` (`fx-card.o`) and the far layer's
   `far_get`, `far_put` (wave 4, S2STBAR-4, FXCHAN-3).
5. In the `M11` test build (its `gdriver.s` at card `$E000-$EDFF`): the
   card's `$EE00-$EE7F` left free; this half's tic-side state and channel
   blocks go there in that build (`S2T_BASE`, `SC_BASE` in the generated
   `s2.inc`; `docs/SCREENS.md` 4.4 "Test builds").

**Why.** `docs/SCREENS.md` 0.1 F3, F7, F8, F11, F12; 4.7. These
routines change state every tic at upstream's place in the tic, so they
cannot run at frame time; the song start must hold the effect player
while S2's main-loop reset burst runs. **Effect:** about 2 KB in the tic
images; the modules use only `GA_*`, `GT_*`, their scratch block, the
card's `$E443-$E47F` and `$E8C0-$E8FF` (release) or `$EE00-$EE7F`
(`M11`), and `MATHW`.

## R5. Milestone 10: `flow`'s `hu_tick` and the `HU_Start` hook

**What.** `hu_tick` calls `FCALL hu_ticker` (`src/native/s2t_hu.s`) at its
start, then makes its own clears as today (`player.message`, and
`G_MSGKEEP` when it takes a message [R `hu_stuff65.s:249-274`]). The
`HU_Start` hook calls `FCALL hu_start` and clears `G_MSGKEEP` [R
`hu_stuff65.s:94-95`]. The list of message ids (the symbols
`player.message` names [R GAME.md 1.5]) is generated into the shared
include, so the HUD's text table and the game agree. (Replaces the first
design's mailbox `HU_MAIL`, dropped.)
As built (wave 4, S2HUD-7): `hu_ticker` and `hu_start` read
`player.message` at `G_PLAYER` + 111 (the tag, 0 for NULL, then the id;
the reference's offset is ignored: every message the runs take is a
symbol at offset 0), `G_SHOWMSG`, `G_MSGKEEP`, `G_GAMEMAP`, and write
only the card's `HU_*`; X and Y kept, no zero page. The message ids are
`llayout.symbol_list()`'s indexes (51 of 228 labels today, the largest
`$A2`); `s2msgs.py` fails if a message's id reaches `$E6`. The test
glue's `hutick` (`src/native/s2_hut.s`) is a marked stand-in of
`gwi.s:638-653` with this order; part `s2hud`'s planted bug "`hu_ticker`
after `hu_tick`'s clear" (7,523 failures) shows what the order decides.
**Why.** `docs/SCREENS.md` 0.1 F8, 1.5.2: the render needs `message_on`
before it draws (`display` sets `viewtop` from it before
`R_RenderPlayerView` [R `d_main65.s:467-474`]), so `HU_Ticker`'s display
half runs in the tic, its state in the card. `hu_ticker` reads
`G_SHOWMSG`, `G_MSGKEEP` and `player.message` before `hu_tick` clears
them, which is upstream's order [R `hu_stuff65.s:244-276`]. **Effect:**
one `FCALL` in `hu_tick` and one in the hook.

## R6. Milestone 10: `ghook.s`'s `AM_Stop`

**What.** `AM_Stop`: clear bit 0 (`AM_ACTIVE`) of the frame block's
`AUTOMAP` byte [R `rlayout.py:533-534`] and set bit 1 of `S2_MAIL` (card
`$E443` block, `docs/SCREENS.md` 4.4). (`HU_Start` is R5's.)
**Why.** The automap's state is the display's; the renderer reads
`AUTOMAP` (the weapon skip [R `RENDER-MASKED.md` 2.1]), so `AM_Stop`'s
effect on it must be at the tic. **Effect:** a few bytes in `ghook.s`.

## R7. The game's frame driver (the second half)

**What.**
1. Before the render: `VIEWTOP` = 9 when the HUD's `message_on` (card) is
   set and the menu does not pause the view, else `$FFFF`, as `display`
   [R `d_main65.s:467-474`]; and `VIEWBOT` = 160 (`AM_TITLEY`) when the
   overlay is on, else 168, as `display` [R `d_main65.s:475-482`]: the
   replay leaves the title band's rows to `OVLW` and `P2DW` (wave 7,
   S2OVL-4).
2. With the automap's overlay on (`AUTOMAP` has `AM_ACTIVE` and
   `AM_OVERLAY`): after `nm_masked` (its last batch staged), `far_pload`
   of `OVLW`'s page runs (`$68`, 24 pages, from bank 93, `OVLW_BANK`) in
   `MASKW`'s place, then `jsr OVLW_LO` (`$6800`: `jmp am_ovl`) with A =
   the frame's tics: `am_ovl` runs `AM_Ticker` once a tic, the overlay's
   records, `titleBand` (rows 160-167 black on the screen when `am_band`
   was 0, and `MAIL_AMTITLE`), `am_valid` 0, then `OVLW`'s own
   `nm_bkload` (in place of `MASKW`'s); then `nb_frame`. `OVLW` reads the
   HUD's `message_on` (`HU_ON`), so `hu_ticker` has run (the tic phase).
   (Wave 7, S2OVL-4; part `s2ovl`'s test driver `s2_ovd.s` does exactly
   this.)
3. After the replay of each level frame, or after `AMAPW` (`jsr am_frame`)
   in a full-automap frame: `far_pload` of `P2DW` (its bank from
   `s2layout`), then `jsr s2_frame` (input poll, effect service, S2's
   `snd_refill`, the palettes, the status bar, the HUD, publish, the state
   written back).
4. A level's first frame and a gamma change: `PALW` (`jsr s2_palettes`)
   before the frame's 2D.
5. A frame where the menu pauses the game: no tic phase; `MENUW`'s frame
   (`jsr m_frame`: `sc_update`, input poll, effect service, `snd_refill`,
   the menu).
6. Intermission, finale and page frames: `WIW`'s or `FINW`'s frame after
   the tic phase.

7. `P2DW`'s level frame (wave 4, S2STBAR-6, S2HUD-2): `s2_palget` (and
   P2DW's own 256 B, `SS_P2DW` ↔ W `$BF00`, fetched with PALST), then
   `s2_viewpal`, `s2_stripearly`, `st_palette`, `st_drawer`, `hu_drawer`,
   `s2_finish`, `s2_palput` (P2DW's own block written back with PALST;
   `src/native/s2_stt.s` does it as the frame should). `st_drawer` leaves
   `S2_BAND`, `S2_Y0`, `S2_Y1` at the bar's band and the marks clear;
   `hu_drawer` sets its own band and takes nibble slots from the last one
   down. `hu_drawer`'s A: bit 0 when `s2_stripearly` returned C = 1 (the
   strip turns on, or a new message); bit 1 in a view frame with
   `VIEWTOP` `$FF` (the view drew rows 0-9) and in a full-map frame whose
   `AMAPW` ran `clearStrip` or `clearView` (`S2_MAIL`'s `MAIL_AMSTRIP`,
   which `P2DW` clears; wave 6, S2AMAP-3); bit 2 in a view frame without the overlay
   and in a frame whose map ran `clearView`, `titleBand` with `am_band`
   0 or `AM_Clean` (`AMAPW`, `OVLW`: `AMAPW`'s `MAIL_AMTITLE`, which
   `P2DW` clears); those images publish their own
   black rows (0-9, 160-167). Part `s2hud`'s checkpoint derives the flags
   from the reference's calls of these routines, so these rules are the
   ones to implement. `P_FPSRATE` (the frame rate the fps cheat shows) is
   the frame driver's to compute.
8. Intermission frames (wave 5, S2WI-5): in an intermission frame
   (`G_GAMESTATE` 1), after the tics, `far_pload` of `WIW` (bank
   `S2CODE3`, 95), then `jsr wi_frame` with A = 1 when display's
   `oldgamestate` was a level (the frame that leaves it: `I_SetPalette(0)`
   [R `d_main65.s:389-393`]), else 0. A menu over the intermission
   (`_g_menuactive`) runs `MENUW`'s frame instead, as display's
   `uiDisplay` does. `wi_init` runs once at the boot with `WIW` loaded (it
   writes `SS_WIW`: the 33 lumps' handles), like upstream's `WI_Init` in
   `D_DoomMain`. `wi_drawer` writes `WI_SNLPTR` = 1 in NoState as
   upstream's `WI_Drawer` [R `wi_stuff65.s:586-592`] (S2WI-4): a run of
   tics without frames (`flowcheck`) leaves it as the tickers leave it,
   and a comparison of `WI_SNLPTR` after a NoState tic against the
   reference includes display's write.
9. The menus (wave 5, S2MENU1-6): the paused frame is `far_pload` of
   `MENUW` when the menu opens (2.7 ms [M]), `m_load`, `m_ticker` once a
   new tic, `m_responder` for each event (A the type, X data1), `m_frame`,
   `m_save`; when `G_MENUACTIVE` and `M_MSGPRINT` are both 0 after it, the
   menu has closed and the game's frames resume. An Escape with the menu
   closed: `MENUW` loaded and `m_responder` (its `vwKeys` opens the menu;
   upstream's `uiOpen` and `singletics`, which switch `displayCall`, are
   the driver's). `M_REQ`/`M_REQARG` acted on and cleared (`REQ_NEWGAME`
   1 the skill, `REQ_QUIT` 2, `REQ_ENDGAME` 3, `REQ_LOAD` 4 the slot,
   `REQ_SAVE` 5 the slot, `REQ_BENCH` 6, `REQ_SAVESET` 7: `s2.inc`);
   `M_RELOAD` 1: `PALW` before the next level frame; `m_savedone` after a
   save (`REQ_SAVE`) with C set on a failure; `M_SETCHG` kept as
   `G_SettingsChanged`'s answer (the settings against the saved file);
   `M_SAVESTR` from `G_UpdateSaveGameStrings`; `m_init` at the boot.
   `REQ_BENCH`'s end writes `MENUW`'s `M_BFPS` (the FPS text, x.xxx,
   0-terminated, at most 7 characters) as `bmDone` writes `VW_BTXT`'s
   second line, and starts the message `MSG_BENCH` [R
   `m_menu65.s:2457-2533`] (wave 6, S2MENU2-1).
10. The input (wave 5, PLINPUT-8): every frame image calls `pl_poll`
   first with A = its menu flag (`MENUW` `G_MENUACTIVE`'s low byte;
   `P2DW`, `WIW`, `FINW` 0); the boot calls `pl_init` (`pl_keys.o`) once
   the mouse card's mode is set; the consumer (the second half's
   `D_PostEvent`) takes events from `PL_QHEAD` (3 B each: the type, data1
   a word) and advances it by 3 mod 45, and zeroes `PL_MDX` when it builds
   a tic command. The key setup: `MENUW` writes `PL_BIND` = `$FF`, the
   poll writes the //e code it takes there, `m_ticker` binds it
   (`pl_bind`) unless it is Esc and writes `$80`.
11. Finale and title-page frames (wave 6, S2FIN-5): in a finale frame
   (`G_GAMESTATE` `GS_FINALE`) and a title-page frame that draws,
   `far_pload` of `FINW` (bank `S2CODE4`, 96), then `jsr fin_frame` with A
   bit 0 when display's `oldgamestate` was a level, bit 1 for the title
   page (`D_PageDrawer`); the page's static turns (display's
   `staticUpToDate`, then `onlyTics`) do not call it. A menu over either
   runs `MENUW`'s frame, as display's `uiDisplay` does. `F_LoadScreen`
   (milestone 10's hook in `doWorldDone`): `FINW` loaded, `jsr fin_load`.
   The busy sign (`bmLoad` around the level load, `bmSave`/`bmSaved`
   around a save, `bmDiskAsk`): `FINW` loaded, `jsr fin_signon` with A = 0
   "LOADING...", 1 "SAVING...", 2 "INSERT DISK n" (X the digit's
   character) before the disk work, `FINW` loaded again, `jsr
   fin_signoff` after it; a menu's save reloads `MENUW` after. `fin_init`
   once at the boot with `FINW` loaded (it writes `SS_FINW`: `F_HELP2`,
   `F_BACKGROUND`, no sign), like upstream's `F_Init` in `D_DoomMain`.
12. The automap (wave 6, S2AMAP-6): an event a level's menu and cheats
   did not take goes to `AMAPW`'s `am_responder` (A the type, X and Y the
   key) when `automapmode` is on, or when it is the map key's key down
   (upstream's `AM_Responder` takes nothing else while the map is off [R
   `am_map65.s:244-261`]), `far_pload` of `AMAPW` (bank 94) first; the
   game's responder when A is 0 after it. In a full-map frame (`AUTOMAP`
   active without the overlay), after the tics: `far_pload` of `AMAPW`,
   `jsr am_frame` with A = the frame's tics, then `P2DW` (item 3). In an
   overlay frame the tics' `AM_Ticker` is `OVLW`'s (`am_ovl`'s A, item 2;
   wave 7, S2OVL-4). The first full-map frame's `AMAPW` load is 2.1 ms [A]; the
   responder's load at each event while the map is on is this driver's
   cost (`s2amap.md` open problem 3).
13. The view's mail (wave 6, S2AMAP-3): in every level frame that draws
   the view without the automap's overlay, and when a paused frame puts
   the view back (`I_RestoreView` [R `d_main65.s:459-462`]), set
   `S2_MAIL`'s `MAIL_AMVIEW`; the automap (`AMAPW`, `OVLW`) zeroes
   `am_valid` and `am_band` at its next entry. An overlay frame zeroes
   `am_valid` itself (part `s2ovl`).
14. The code library's release images (wave 8, PLBOOT-3): the release's
   2D images (the frame glue, `P2DW` with both the status bar and the HUD)
   replace `pldisk.IMAGE_BUILDS` (the parts' test images, marked
   stand-ins: `P2DW` is `s2stbar`'s `s2sb`, the status bar without the
   HUD); the tic images join `CODE.1` (`pldisk.code_segments`).
   `pldisk.py`'s build checks each against the card (`image_problems`)
   and the disk's layout. The main card's bank 1, bank 2 and
   `$F900-$FEFF` are milestone 8's `rcard` link's bytes: a relinked
   release card replaces them in `pldisk.py` the same way.
15. The static tables (wave 8, PLBOOT-7; a design gap): `MEMORY_MAP.md`
   3.2 and 5 give main `$0800-$0BFF` (`CMPA`, `CMPB`, `TEXLO`, `XTVLO`,
   `TEXHI`, `XTVHI`) and aux 0 `$0200-$02BF` (the drawers) and
   `$0900-$0AC7` (`ROWLO`, `FZDIR`, `ROWHI`) to "boot, PRIVATE", but
   `DOOM.SYSTEM` does not load them (its boot code has 6 B of its 2 KB
   budget left) and milestone 9's level load loads only the per-level
   colormaps and `FUZZDARK` [R `docs/LEVELS.md` "Checkpoint B"].
   `RENDER.SYSTEM` stages them in two banks and copies them by PRIVATE [R
   `tools/native/rdisk.py:458-477`]. Before the first level frame, the
   second half (the boot's next step or the first level load) stages them
   in a bank of `DOOM.hdv` (`RTABLES.1` has room) and sends the PRIVATE
   requests through `lload.s`'s transport in W, after the last MLI call
   (`MEMORY_MAP.md` rule 9). Until then the renderer cannot draw from
   `DOOM.hdv`'s booted state alone.

**Why.** `docs/SCREENS.md` 1.5.2, 1.5.4, 2.1, 3, 4.1. **Effect:** the
frame order of milestone 8's driver; nothing in milestone 8's code.

## R8. Milestone 10: cost phases 30 and 31 in the test-build harness

`src/native/game/flow/gflow.s`'s `fl_timed` and `fl_tresume` (inside
`.ifdef TESTBUILD`) time one routine alone in phases 30 and 31, this
half's 2D and platform phases (SCREENS.md 4.8). Since wave 4,
`s2layout.check()` accepts stores inside milestone 10's test-build
branches as long as they are 0-31 and readable (their runs time that
routine and nothing of this half), and keeps 4.8's owners for every
other store. **Ask:** keep phases 30 and 31 out of the game's own code
(the release and the `M11` build's game code: GAME.md 5.4's 18-29), and
keep the harness's stores inside `.ifdef TESTBUILD`; if the harness
later shares a run with this half's 2D frame, it should move to a free
phase. (Wave 4, S2HUD-4, s2stbar's and fxchan's open problems.)

## R9. `docs/LEVELS.md` 1.7, row `TABLES.n` (for the final integrator)

**What.** At the end of the row's content (wave 8, PLBOOT-8): "(as
built: bank 99's tables, 17,518 B; milestone 8's constant tables are
`DOOM.hdv`'s `RTABLES.1` and the aux card's are in `LC.BIN`, milestone 11
part `plboot`)".

**Why.** `LEVELS.md` 1.7 planned `TABLES.n` with "the constant tables,
`GTAB`, the aux card's tables (about 320 KB)"; the store's `TABLES.1` is
bank 99's 17,518 B [M: part `plboot`]. `DOOM.hdv` carries milestone 8's
constant tables in RamWorks as `RTABLES.1` (246,036 B, banks 48 and
116-122, laid out by `render_check.base_records`) and the aux card's in
`LC.BIN`. **Effect:** none on milestone 9's or 10's code; the text only.
