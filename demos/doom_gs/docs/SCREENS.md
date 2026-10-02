# Milestone 11, first half: the 2D screens, the platform and the effects

> **For the playable game's assembly (2026-10-02).** This half is built
> and verified (8.13-8.15). What it still needs from others is in
> `docs/m11-parts/design.md`: R4-R6 and R8 (milestone 10's hooks:
> `st_tick`, `hu_tick`, `HU_Start`, `AM_Stop`, `fx_song` at every song
> start, phases 30-31), R7 items 1-15 (the game's frame driver, the
> release 2D and tic images on `DOOM.hdv`, the static PRIVATE tables the
> boot does not yet load), R9 (`LEVELS.md` 1.7), R2 item 7
> (`MEMORY_MAP.md`). Also: `GS_ARG` is a word (`$03B0-$03B2`; the input
> block starts at `$03B3`), and `tests/wip_test_m11_build.py` becomes
> `tests/test_m11_build.py`. `docs/play-requests.md` tracks what the
> glue has asked for.

Status: design, 2026-10-01, revised the same day after an adversarial
review (section 10 says what was taken, what was not, and why), for the
builders of the first half of milestone 11, who work in parallel with
each other and with milestone 10's builders (`docs/GAME.md`) in the same
tree. Waves 1-8 are built and integrated (sections 8.5-8.12), and the
first half's acceptance passes on a2vm (8.13; the report 8.14; the card's
runs are milestone 12's).
The effects (sound track S4) have their own section in
[`tools/sound/README.md`](../tools/sound/README.md#effects-s4); this
file places them in the machine and the waves. The changes this design
asks of shared files are written out in
[`docs/m11-parts/design.md`](m11-parts/design.md) for the integrator.

It follows [`NATIVE.md`](NATIVE.md) sections 4, 8, 9, 10, 11, 13 (row 11,
S4) and 15.1, [`MEMORY_MAP.md`](MEMORY_MAP.md),
[`RENDER.md`](RENDER.md) and [`RENDER-MASKED.md`](RENDER-MASKED.md) (the
replay, `K_OVL`, the frame's phases), [`LEVELS.md`](LEVELS.md) (the store,
`LEVELS.SYSTEM`) and [`GAME.md`](GAME.md) (milestone 10: its layouts and
hooks are this half's interface, read only).

The task, as it was ordered:

> (a) the 2D screens natively: the status bar and the face, the HUD
> messages (a cached drawer, not upstream's code generator), the menus
> (the view saved by memory API COPY into a hidden buffer, restored by CPU
> stores; ZipGS and TransWarp menus dropped; key names for the //e), the
> automap (`K_OVL` records through the replay), the intermission, the
> finale, the wipe, the title and other full-screen pictures, the loading
> sign; each drawn from injected game state and compared with ref816's
> screen; (b) the platform: the game's boot, input, the clock, the IRQ
> handler, the `$Cxxx` rule's scheduling; (c) S4, the sound effects.
>
> Acceptance of this half: (1) every 2D screen equal to ref816's, byte for
> byte in its SHR region, from injected state [...]; poisoned screens
> where the drawer leaves bytes untouched; (2) the clock 34.9-35.0 tics a
> second on PAL and NTSC timing on a2vm, and the IRQ's worst-case length;
> (3) input: scripted key and mouse sequences on a2vm produce the expected
> events; (4) the boot on a2vm from a disk image loads everything into the
> right banks (checked by CRC) and reaches a ready state; (5) effects [...];
> (6) a test disk `SOUNDS.hdv` for the owner's ear. Report: a2vm time per
> frame of each 2D part (f121 and fastpath) and the IRQ's cost a second
> with music and effects.

Out of this half, for the second: saves, `G_BuildTiccmd`'s wiring into
the tic, `G_Responder`, the title loop (`D_DoomLoop`, `D_AdvanceDemo`,
`D_PageTicker`), and the whole-game acceptance.

**Labels**, as in `NATIVE.md`:

- **[M: source]** measured. `M: this design` is a measurement made for
  this file (appendix A gives the commands); `M: modules`, `M: sound` are
  the `docs/research/` reports; `S2`, `S3` are `src/sound/README.md` and
  `tools/sound/README.md` as built; `M8`, `M9` are `RENDER-MASKED.md` and
  `LEVELS.md` "as built".
- **[R file:line]** read there. Upstream's files are in
  `build/upstream/src/iigs/`; nothing is read from or derived from its
  `cal_integer.s`.
- **[A]** assumed, or arithmetic on labelled numbers.

## 0. Summary

| Question | Answer |
| --- | --- |
| How the 2D screens are drawn | Upstream draws all 2D into a back buffer in bank `$01` and copies the marked byte ranges to the screen at `I_FinishUpdate` [R `i_viigs65.s:1-4`, `:407-498`]. Natively every 2D drawer **composes in W** (a band of rows in a main-memory buffer, its background fetched from RamWorks: the status bar cache, the saved menu view, a picture, black) and **publishes** the marked bytes to aux 0 with `RAMWRT` and CPU stores. No 2D drawer ever reads the screen, so no `RAMRD` window, no code in aux 0, and no PRIVATE write ever reaches a shown byte (`MEMORY_MAP.md` rules 3, 4). Section 1 |
| Where the code runs | A **per-frame 2D image** (`P2DW`) loaded into W in every level frame, after the replay or, in a full-automap frame, after `AMAPW` (status bar, HUD, palettes and SCBs, input poll, effect service); **mode images** (`MENUW`, `AMAPW`, `WIW`, `FINW`, `PALW`) loaded when their mode draws, each frame image with the input poll and the effect service; **tic-side modules** (the status bar's ticker, the HUD's ticker, the finale's ticker, the sound channel logic) that milestone 10's tic image links, called by GAME.md's hooks (the channel logic is linked into `MENUW` too: the menu pauses the tics but starts sounds); the automap overlay's producer in **its own image `OVLW`**, loaded between milestone 8's masked phase and the bucket pass; the IRQ, the clock and the effect player in the main card's `$E000` part. Section 4 |
| The platform | `DOOM.SYSTEM` (from `LEVELS.SYSTEM`'s boot): probes, every bank file, the card images, CRCs, ProDOS discarded; the mouse card's VBL drives a **16-bit fractional tic clock** (34.955 tics a second on PAL and NTSC); one IRQ entry: acknowledge, clock, the effects' steps, S2's music player unchanged, then chip 3's burst right after the music's; input from `$C000`/`$C010`, Open and Solid Apple and the mouse card, turned into upstream's key events by a held-key policy. Section 2 |
| The effects | Our own converter from `DS*` and `DP*` to AY scripts, a second independent model, a tuning file for the 10 most frequent effects (measured: `BGACT`, `PISTOL`, `POSACT`, `SHOTGN`, `PLPAIN`, `FIRSHT`, `FIRXPL`, `STNMOV`, `POPAIN`, `BGSIT2`), a 65C02 effect player on chip 3 in the music's interrupt (its own burst after the music's, so the music's writes are untouched; held while a song starts and chip 3 rewritten whole after), stereo by picking a left or right voice of chip 3 (a centred sound takes a left one), upstream's channel logic with `NUM_CHANNELS` 3 (8 in the comparison build) talking to the player through **one mailbox a channel**, effects off on a card without native mode, and `SOUNDS.hdv`. Section 3 and `tools/sound/README.md` "Effects (S4)" |
| How it is compared | ref816 dump streams at the display's entry and after `I_FinishUpdate`, distilled into per-frame cases (the state the drawer reads, the screen before, the screen after); the native drawer runs on the injected case from the captured screen and from a poisoned one; its SHR region (pixels, SCBs, palettes) must equal ref816's byte for byte, and every other byte must keep its value or its poison. Tic-side modules are compared per call, as milestones 7-10 compare routines. Section 6 |
| The parts | 20 parts in 8 waves of at most 3 (wave 1 is the shared layouts, makefile, driver and runner with the host-only converter beside it), each about 1.5 hours, each owning its files; then an integration stage. Section 7 |
| Main risks | The menu's view save and gray conversion cost (a 32 KB save, a 32 KB CPU restore at about 31.5 ms of drain each on F1.2.1); the effect rings' refill once a frame at 6 FPS; the 2D store's banks (about 300 KB in the 13 banks reserved for songs, effects, 2D and code, plus one spare); upstream's 2D assets that only the release holds; tic-side code room in milestone 10's W; the 2D images' code rooms (4.1's size table). Section 9 |

### 0.1 What the sources change in the task's plan

| # | Fact | Consequence |
| --: | --- | --- |
| F1 | **Upstream has no melt wipe.** `D_Wipe` and `I_FinishUpdate` are one label: a new picture comes with its 512 palette bytes written black first, then the marked bytes, then the picture's colours [R `i_viigs65.s:313-345`]; the first title page skips the black over the loader's grey title (`titleWipe` [R `w_level65.s:1400-1448`]). `M_Random`'s only caller is `ST_Ticker` [R `st_stuff65.s:432`; GAME.md fact 13]: no wipe uses it | The wipe of this half is the black-first sequence. Its steps are compared (the screen after the black palettes and the marked bytes, then after the colours: 1.5.8); no `M_Random` is involved. `titleWipe` is dropped with the gray boot title (2.5), a named difference |
| F2 | **7 tics per 10 VBLs on PAL is 35.056 tics a second**, outside the acceptance's 34.9-35.0: the PAL //e's VBL is 1,015,625 / 20,280 = 50.080 Hz [R `tools/sound/README.md:63-73`; M: S3 timer count 20,281 on the card, `docs/results/music-card-2026-09-30.md`]. NTSC's 7 per 12 gives 59.923 × 7/12 = 34.955 [A] | The clock adds a 16-bit fraction a VBL: 45,743 (PAL) and 38,229 (NTSC) / 65,536, so 34.955 tics a second on both, upstream's rate (34.955 [M: MILESTONES 2]). `NATIVE.md` 10's "7 per 10" changes (request R1, `docs/m11-parts/design.md`) |
| F3 | **Upstream has 8 channels** [R `s_sound65.s:30`], frees a channel when its DOC oscillator stops (`isPlaying` in `S_UpdateSounds` [R `:383-423`]), and stops a channel whose sound is not in the map's DOC plan (`startSound` fails [R `:265-270`]) | The native channel logic is upstream's with `NUM_CHANNELS` a build constant. The comparison build has 8 channels and takes the reference's channel table and `startSound` result at each call (injected state with a reason); the release has 3, checked against a host model that equals the reference in the 8-channel configuration (section 3) |
| F4 | **Measured sound starts** [M: this design, call logs of DEMO1-3 and the tour, 1,304 starts]: at most 4 in a tic, 7 in a frame of 4 tics, 12 starts and stops together in a frame; 36 distinct effects; the 10 most frequent are `BGACT` 169, `PISTOL` 162, `POSACT` 161, `SHOTGN` 88, `PLPAIN` 77, `FIRSHT` 76, `FIRXPL` 75, `STNMOV` 51, `POPAIN` 41, `BGSIT2` 36 | These 10 are the hand-tuned ones. The sample does not bound the requests (it leaves out the internal stops and `S_UpdateSounds`' volume updates and stops), so the channel logic talks to the player through one mailbox a channel, bounded by `NUM_CHANNELS` by construction (3, 4.4) |
| F5 | **The 2D assets are partly upstream's build artifacts.** In the release's WAD the pictures `TITLEPIC` and `HELP2` are 36,864-byte SHR pictures (pixels, SCBs, 16 palettes, pair tables [R `i_viigs65.s:60-64`]), and `GSSTAT` (5,664 B), `GSOVL` (2,112 B) and `GSVIEWn` (1,216 B each) are its palettes and pairs [M: this design, `umodel.Release`]; the rest are Doom patches and the `STBAR` raw lump (but `WIURH0`, which upstream recoloured: 290 pixel bytes differ from `DOOM1.WAD`'s [M: `docs/m11-parts/s2data.md`], and the menu patches `M_ARUN`, `M_GAMMA`, `M_MOUSE`, `M_MSPEED`, `M_MMOVE`, `M_CTRLS`, upstream's own). 151 `ST*`, 36 `M_*`, 33 `WI*` lumps: 64,756, 67,317 and 82,668 B [M: this design] | As milestone 9 did for `GSVIEWn` [R `LEVELS.md:66`, `:162`]: patches and flats from `DOOM1.WAD` by our own code, checked equal to the release's lumps; the pictures and the `GS*` records from the release image with those seven patches, in `build/` only |
| F6 | **The status bar and the HUD are drawn incrementally.** `ST_Drawer` redraws only the widgets whose value changed, each over its background restored from `STCACHE` [R `st_stuff65.s:826-993`]; the HUD redraws its line only when it is not on the screen (`iigs_textShown` [R `i_viigs65.s:1792-1897`]) | A frame's status bar depends on the frame before: the comparison injects the screen before the frame and the widgets' old values, and also runs chained over all of demo3 (6.3) |
| F7 | **`ST_Ticker` is game state per tic** (the face's priority, counters, the random number, the old health [R `st_stuff65.s:432-727`]); milestone 10 takes only its `M_Random` call (`st_tick` [R GAME.md 2.4 `flow`]) | The face logic is a tic-side module of this half (`s2t_st.s`), called by the `ST_Ticker` hook with `M_Random`'s value (4.7, request R4) |
| F8 | **`HU_Ticker` clears `player.message`**, which milestone 10 does (`hu_tick` [R GAME.md 2.4]); the counter, `message_on`, `message_new` and the line's text are the display's [R `hu_stuff65.s:244-276`], but **the render needs `message_on` before it draws**: `display` sets `viewtop` from it before `R_RenderPlayerView` [R `d_main65.s:469-476`], and `stripEarly` sets the strip's palette from it before `R_DrawLists` [R `:764-778`] | `HU_Ticker`'s display half is a tic-side module (`s2t_hu.s`: the counter, `message_on`, `message_new`, the line's message id), its state in the card; the frame driver sets `VIEWTOP` from it before the render (1.5.2, requests R5, R7) |
| F9 | **The automap's overlay is records, its full mode is not.** The overlay appends `K_OVL` records after the view's [R `am_map65.s:1461-1509`; `d_main65.s:491-496`]; the full mode draws into the back buffer with a list of the bytes it wrote, erased the next frame [R `am_map65.s:1059-1100`, `:1230-1306`] | The overlay's producer runs in its own image `OVLW` between milestone 8's masked phase and the bucket pass; the full mode composes in W (1.5.4) |
| F10 | **The menu's dimmed view** is not the saved view: `I_MenuPalette` saves the screen and redraws every byte through `UI_GRAY` into the menu palette's grays [R `i_viigs65.s:2057-2134`, `:2259-2322`]; `I_MenuPaletteBack` copies the saved bytes back and the saved palettes and SCBs [R `:2138-2203`] | Save by memory API COPY from aux 0 to a RamWorks bank (a source in aux 0 `$2000-$9FFF` is allowed, only destinations there are not [R `README_MEMORY_API.md` section 3, "Endpoint rules"; section 4]); the gray screen and the restore by CPU stores (1.5.3). `MEMORY_MAP.md` 11's checklist line on endpoints is corrected to "destination" (request R2) |
| F11 | **Sounds outside the level's tics.** `S_UpdateSounds` runs every frame from `musFrame` when the player has a mobj [R `d_main65.s:231`; `s_sound65.s:1914-1922`], also while the menu pauses every tic [R `d_main65.s:261-279`]; the menu starts sounds from `M_Responder` [R `m_menu65.s:909-912`]; the intermission from `WI_Ticker` [R `wi_stuff65.s:491-495`] (milestone 10's `flow`) | The channel logic is linked into the tic image and into `MENUW`; `sc_update` runs once a frame, in the tic phase or, in a paused menu frame, in `MENUW`; every frame image calls `fx_service` and S2's `snd_refill` (3, 4.1) |
| F12 | **S2's song start rewrites chip 3.** `snd_start` ends with `reset_chips`, which writes R0-R12 of all four chips (R7 `$38`) from the main loop with interrupts on [R `src/sound/player.s:1008`, `:1056-1101`]; before the first song the chips hold the reset's values (R7 0) [R `player.s:840-869`] | The effect player is held while a song starts (no VIA-B write can tear the main loop's burst) and treats chip 3's shadow as unknown after it and at boot (3; `tools/sound/README.md` "Effects (S4)") |

## 1. The 2D screens

### 1.1 Upstream's model

| Step | Upstream | Where |
| --- | --- | --- |
| Drawing | Every 2D drawer writes the back buffer `SHRBUF` (`$01:2000`) and marks rows and byte ranges (`DRB`, `DRE`, `DRY0`, `DRY1`) | [R `i_viigs65.s:407-457`; `patch65.s:192-230`] |
| A patch pixel | `NIBTAB[page << 8 \| colour]` with the page from `iigs_rowpageL/R[row]` (the row's palette and parity, the pixel's side), then read, mask, or, write | [R `patch65.s:1-9`, `:157-177`] |
| The 3D view | `R_DrawLists` writes `$E1` directly | [R `i_viigs65.s:2`] |
| The screen | `I_FinishUpdate`: a new tint's palettes (`TINTPAL` row), changed SCBs, the marked bytes by MVN (`showDirty`), and a picture's palettes, black first for a new picture | [R `i_viigs65.s:329-405`, `:459-498`] |
| The frame | `display`: the view (`R_RenderPlayerView`, the overlay, `stripEarly`, `I_ApplyColors`, `R_DrawLists`), or the full automap, intermission, finale or page; then `ST_doPaletteStuff`, `ST_Drawer`, `HU_Drawer`, `M_Drawer`, `I_FinishUpdate` (or `D_Wipe`) | [R `d_main65.s:377-558`] |
| The menu | Pauses the view: the screen saved once, then a "static screen" redrawn only where the skull moved | [R `d_main65.s:437-463`, `:561-624`] |

### 1.2 The native model

**Compose in W, publish by CPU.** Each 2D drawer has a **band buffer** in
W: one or more whole rows of 160 bytes, with upstream's marks (`DRB`,
`DRE` a row). Before drawing into a rectangle it fetches the
rectangle's background into the band (`far_get` from a RamWorks bank:
the status bar cache, the saved menu view converted to grays, a picture's
rows, or zeros), draws the patches into the band with upstream's nibble
rule, and marks the bytes. `s2_publish` then copies the marked bytes of
each row to aux 0 with `RAMWRT` on (`$C073` 0), CPU stores only, in one
`RAMWRT` window a band. The SCB and palette bytes (aux 0 `$9D00-$9FFF`)
are published the same way, in upstream's order (1.3): when a new picture
is up (`palettecount` not 0), the black palettes, then the new tint and
the SCBs, go out before the frame's first band; the picture's colours
after its last band.

Why not draw on the screen as upstream's view drawers do: a read of aux 0
needs `RAMRD`, so code in the card, zero page or aux 0 (`MEMORY_MAP.md`
rule 5), and on F1.2.1 every `RAMRD` switch waits for the drain of every
SHR byte written before it (`docs/results/fuzz-timing-2026-09-30.md`).
Composition reads only main memory and RamWorks, writes the screen once a
byte, and keeps upstream's dirty-range logic; the drawers stay close to
upstream's code. The 79 bytes `MEMORY_MAP.md` 5 kept in aux 0 for a
"status bar read-mask-or" are not needed (request R2).

**Bands.** A band holds the rows a drawer can touch in one pass: the
status bar's 32 rows (5,120 B; `P2DW` reuses it for the message strip's
10 rows once the status bar is published), the menu's and the pictures' bands of 40 rows (6,400 B: five bands a full
screen, each patch drawn clipped to the band it crosses). The patch
drawer takes a row window `[y0, y1)` and the band's base.

**Never shown by PRIVATE, never read from the screen.** The only
memory-API request that touches aux 0 `$2000-$9FFF` is the menu's save,
which reads it (1.5.3). Every shown byte is a CPU store with `RAMWRT` on.

### 1.3 Palettes, tints, nibble tables, SCBs

Upstream's palette state, kept natively in the 2D state block (4.6):

| Upstream | Native | Made from |
| --- | --- | --- |
| `TINTPAL`: the level's palettes in each of 14 tints (`TINT_ROW` = `LEVEL_PALS` 12 × 32 = 384 B a tint row [R `i_viigs65.s:47-57`, `:85`, `:611-704`]) | RamWorks `S2PAL` bank, 14 × 384 = 5,376 B | `GSVIEWn` (the level's record, milestone 9's `LVC` [R `LEVELS.md:85`]), `GSSTAT`, `GSOVL`, gamma (`gammaColor` [R `:565-610`]) |
| `NIBTAB`: 16 tables of 1 KB, one a palette (its pages: left even, left odd, right even, right odd rows; `rowPalette` gives a row `palette × $400 + parity × $100`, the right side 2 pages on [R `patch65.s:3-9`; `i_viigs65.s:705-787`]) | `S2NIB` in bank `S2PAL`, 16 KB; a drawer keeps the tables of the palettes its rows use in 1 KB **slots** in W, fetched the first time a frame needs them (W is overwritten every frame, so a table is fetched once a frame at best: 0.25 ms a table [A on M: `NATIVE.md` 4.3]); the status bar's rows use 8 palettes (`STAT_PALS` [R `i_viigs65.s:47-49`]), so `P2DW` has 8 slots (4.1); every image counts its fetches (6.4) | the palette record's pairs |
| `scb`, `palette`, `iigs_rowpageL/R`, `iigs_rowbase` [R `:96-100`] | the state block; row tables in W | `setRows`, `rowPalette` [R `:738-787`] |
| `newpal`, `curtint`, `levelcopy`, `palettecount`, `scbchanged`, `picturenum`, `viewpal`, `strippal` [R `:71-104`] | the state block | `I_SetPalette`, `drawPicture`, `I_ViewPalette`, `I_MessageStrip` |
| `GRAYMAP`, `UI_GRAY`, the menu's font reds [R `:877`, `:2227-2252`, `:2326-2402`] | built when the menu opens, in `MENUW` | the palettes on the screen |

**The order is upstream's** [R `i_viigs65.s:327-345`]: with
`palettecount` not 0, the 512 palette bytes black, then `newColors` (the
new tint's palettes, the changed SCBs, `TINTPAL`'s row), then the marked
bytes (`showDirty`), then `pictureColors`; with `palettecount` 0,
`newColors` then the marked bytes. The native drawers publish their own
bands during the frame, so the order is kept by two entries: `s2_begin`,
which `s2_publish` calls before the frame's first band (the black
palettes when `palettecount` is not 0, then `newColors`; once a frame),
and `s2_finish` at the frame's end (`s2_begin` if no band was published,
then `pictureColors`). All are CPU stores to aux 0 `$9D00-$9FFF`. The
write log checks the order in every run (6.3): no band store of the frame
before the last black palette store and the last SCB store, no picture
colour store before the last band store. Rule 10 of `MEMORY_MAP.md` (aux
0 `$9DC8-$9DFF` stays zero) is checked by every run.

**Colours before the view (a named difference, D1).** Upstream applies
the new colours and the strip's palette before `R_DrawLists` draws the
view [R `d_main65.s:499-502`, `:764-778`]. Natively they go out with
`P2DW`, after the replay: in the frame where a message expires, rows 0-9
show the view's new pixels in the strip's palette until `P2DW` publishes
(the replay's length, tens of ms on F1.2.1 [M: M8]), and a new tint
reaches the view the same time later. The frame's final screen is
upstream's. Reported with its time; lever L5 (8.3) moves `s2_begin`
between the bucket pass and the replay if the owner sees it.

### 1.4 The patch drawer and the cached drawers

`s2_patch` is `IIGS_DrawPatch` into a band [R `patch65.s:53-230`]: the
columns, the posts, the clip to 320 × 200 and to the band's rows, the
nibble rule, the marks; `V_DrawPatchNotScaled` and `V_DrawNumPatch*` apply
the offsets [R `i_viigs65.s:1769-1782`]. A patch comes from RamWorks by
`far_get` into a W fetch buffer (the largest status bar patch about 1.5
KB, a menu title about 7 KB [A]: the drawer fetches a column run at a time
when the patch is larger than the buffer). `s2_raw` is `drawRawData` of
whole rows (the `STBAR` raw lump through `pairByte` [R `:1311-1445`]),
`s2_rect` is `copyToBuffer` by rows (`drawPicture`'s pixels [R
`:1226-1240`] and `I_RestoreStatusRect`'s copy); `s2_vpatch` is
`V_DrawPatchNotScaled` (wave 2, S2DRAW-4); `s2_back` is `V_DrawBackground` (a 64 × 64
flat tiled [R `:1462-1521`]).

**The HUD's cached drawer** replaces `IIGS_TextCode`'s 65816 code
generator [R `patch65.s:278-382`] with data: while a line is drawn the
patch drawer also records, for each byte it writes, its offset in the
strip, the nibbles written (`CAPMSK`) and their value (`CAPVAL`); the
record of a slot (at most 40 characters of the 7-row font, about 1,000
entries [A]) is kept in the 2D state's bank with the slot's text, length
and row (upstream's `textValid`, `textLen`, `textY`, `textText`
[R `i_viigs65.s:113-116`]). Drawing the same text again replays the
record: `byte = byte & ~mask | value` into the band, the bytes marked.
Invalidation is upstream's (`textInvalidate` on a nibble-table or row
change [R `:1891-1897`]).

**Optional, measured first:** pre-rendered status bar glyphs (each digit,
face, arm and key at each of its fixed places, rendered by the host
converter with the same nibble rule) would turn a widget's draw into a
masked copy. The generic drawer comes first; part `s2stbar` reports its
cost and the integrator decides (section 8, lever L2).

### 1.5 The screens

#### 1.5.1 The status bar and the face (part `s2stbar`)

| Upstream | Native | Notes |
| --- | --- | --- |
| `ST_Init` (lump numbers, `LARGEAMMO`) [R `st_stuff65.s:127-194`] | `st_init` (`P2DW`) | lump numbers become the 2D store's patch handles |
| `ST_Start` (`ST_initData`, `ST_createWidgets`, the palette 0) [R `:216-385`] | `st_start`, **tic-side** in `s2t_st.s` (4.7), called by the `ST_Start` hook (request R4): `ST_initData` copies the player's `weaponowned` at that tic; the next frame's drawer sees `st_refreshed` 0 and redraws the whole bar | widgets as fixed tables: x, y, width, the value's place (the player's fields at `G_PLAYER` [R `llayout.py:1047`]), old value |
| `ST_Ticker` but `M_Random` (`readyNum`, `keyboxes`, `updateFace`, `painOffset`, `turnHead`, `st_oldhealth`) [R `:427-727`] | `s2t_st.s`: `st_ticker`, **tic-side** (4.7) | `turnHead` takes the attacker's x, y through a callback and `pta3` from `MATHW` |
| `ST_Drawer` (`refresh`, `diffDraw`, `diffNum`, `diffIcon`, `restoreRect`, `updateIcon`, `drawNum`, `stHide`) [R `:729-1000`, `:1173-1210`] | `st_drawer` (`P2DW`), composing in the status band | `restoreRect` is a `far_get` of the rectangle's rows from `STCACHE`; the frame's marked bytes from `STBUF` (bank `S2STATE`: the bar's rows as published, upstream's back buffer's; wave 4, S2STBAR-2) |
| `I_SaveStatusBackground`, `V_DrawRaw` of `STBAR` with `STARMS` [R `i_viigs65.s:1357-1367`; `st_stuff65.s:749-762`] | the band after the background is drawn, `far_put` into `STCACHE` (bank `S2STATE`) | |
| `ST_doPaletteStuff` [R `st_stuff65.s:1099-1171`] | `st_palette` (`P2DW`, part `s2pal`) | the tint into `newpal` |

The status bar's rows 168-199 use the palettes of `GSSTAT` (a palette a
row, then 8 records [R `i_viigs65.s:47-49`]): palettes 1-8, each its own
1 KB nibble table, hence `P2DW`'s 8 slots (1.3, 4.1).

**Coverage.** demo3, newgame and the tour may never show some widget
values (the skull keys, every arm, three-digit ammo and maxammo, armour
200, the god face, the dead face, `LARGEAMMO`). Part `s2cap` adds
synthetic frames for each value class by `ref816 --poke-file` of the
player's fields at named tics (injected state with a reason), and part
`s2stbar` reports a coverage table, each widget × each glyph and place
drawn, against the reference; a glyph never drawn fails the checkpoint
(6.1).

#### 1.5.2 The HUD (part `s2hud`)

`HU_Init`, `HU_Drawer` (the title over the automap, the message line),
`drawTextLine` [R `hu_stuff65.s:70-93`, `:124-243`], in `P2DW`; the text
cache of 1.4; `I_MessageStrip` and `stripEarly` (the strip's palette and
its clear [R `i_viigs65.s:500-560`; `d_main65.s:764-778`]).

**The HUD's ticker is tic-side** (`src/native/s2t_hu.s`, 4.7), because
the render needs `message_on` before it draws (0.1 F8): `hu_ticker` is
`HU_Ticker` but the clears milestone 10's `hu_tick` makes [R
`hu_stuff65.s:244-276`]: the counter's decrement and `message_on` 0 at
its end, then, when messages are on or kept (`G_SHOWMSG`, `G_MSGKEEP`)
and `player.message` is set, the line's message id, `message_on`,
`message_new` and the counter `HU_MSGTIMEOUT`. `hu_start` is `HU_Start`'s
state part [R `hu_stuff65.s:94-123`] (`message_on` 0, the title's
map; its clear of `G_MSGKEEP`, milestone 10's byte, stays in the hook:
request R5). Their state (counter,
`message_on`, `message_new`, the id, the title's map, about 8 B) is in
the card (4.4). Request R5: `flow`'s `hu_tick` calls `hu_ticker` first,
then makes its own clears; the `HU_Start` hook calls `hu_start`. The
frame driver sets `VIEWTOP` from `message_on` before the render, as
`display` does [R `d_main65.s:469-474`] (request R7), so milestone 8's
and 10's record streams see upstream's `viewtop`. The id's text comes
from a table in `S2STATE` (`SS_HUDMSG`, the bank file `HUDTXT.1`),
fetched when the line's id changes, generated from upstream's message
symbols by the list milestone 10 numbers them with (`s2msgs.py`; risk
12's first remedy; wave 4, S2HUD-3); `P2DW` keeps the font's places and
widths.

#### 1.5.3 The menus (parts `s2menu1`, `s2menu2`)

The menu engine and pages of `m_menu65.s` [R `m_menu65.s:518-1600`,
`:2672-3139`] in `MENUW`, and the menu's video of `i_viigs65.s`
(`I_MenuPalette`, `uiDimAll`, `uiDimRect`, `uiGrayTables`, `uiFontNibbles`,
`I_MenuPaletteBack`, `I_RestoreBackRect` [R `i_viigs65.s:1532-1710`,
`:2030-2402`]) and `d_main65.s`'s static-screen logic (`staticUpToDate`,
`staticDrawn`, the skull's rectangles [R `d_main65.s:561-624`]).

| Step | Native |
| --- | --- |
| Open (`I_MenuPalette`) | One memory-API COPY of aux 0 `$2000-$9FFF` (32,768 B: pixels, SCBs, palettes) to bank `S2VIEW` `$2000`; destination in RamWorks, flags 0, one VBL period's worth (`MEMORY_MAP.md` 11: at most about 45 KB a request) [R `README_MEMORY_API.md` sections 3-5]. Then the gray tables, the menu palette's nibbles and font reds, and the gray screen: the saved rows fetched by `far_get` a band at a time, each byte through `UI_GRAY` by its row's palette, published. As built (wave 5, S2MENU1-3): the gray tables from the **saved** palettes; palette 9's nibble table in `MENUW`'s slot only (`S2NIB` is never changed: `uiOriginalNibs` has nothing to put back, D-M2) |
| Each frame | Upstream's static screen: nothing unless the menu or the skull changed; `M_Drawer` composes the menu's rectangles over the gray background (the band's background is the saved rows through `UI_GRAY`, as `uiDimRect` does). As built: the frame redrawn whole as upstream (every row from the saved screen through a 256-byte gray map of the row's saved palette, the page drawn over it band by band, all 32,000 bytes published), or the static screen with the skull's two rectangles |
| Close (`I_MenuPaletteBack`) | The saved bytes back by CPU stores: `far_get` a band from `S2VIEW` into W, publish the whole band; the saved palettes and SCBs. About 32 KB of CPU stores, about 31.5 ms of drain on F1.2.1 [R `NATIVE.md` 8] |
| Gone | ZipGS and TransWarp: the benchmark result's `CPU`, `CACHE` and `ROM` rows [R `m_menu65.s:3012-3066`] and the accelerator code (`bmAccel*`, `bmTw*`, `IIGS_Zip*` [R `:2106-2180`]). The benchmark itself (demo3 timed) stays, with its two rows (view, FPS); the CPU, CACHE and ROM rows (y 92, 108, 124, 8 rows each) black, whole rows (X2, `s2check.x2`; wave 6, S2MENU2-5). The FPS text is `MENUW`'s `M_BFPS` (S2MENU2-1), which the second half's benchmark writes |
| The //e's keys | The key setup's names [R `m_menu65.s:252-510`] become the //e's: letters, digits, punctuation, `LEFT`, `RIGHT`, `UP`, `DOWN`, `RETURN`, `ESC`, `TAB`, `SPACE`, `DELETE`, `CTRL-A`..., `O-APPLE`, `S-APPLE`, `MOUSE 1`, `MOUSE 2` (the pseudo-keys of 2.4); 8 bytes a name as upstream's table, at most 7 characters and a 0 (upstream's `text` reads to the 0 [R `m_menu65.s:1369-1381`]; its longest names are 7). The table has 128 entries like upstream's `keyTable` [R `i_iigs65.s:83`], so it is poked 1:1 into ref816 (6.2) |
| Actions | `M_Responder`'s game actions (new game, quit, end game, load, save, the cheats are milestone 10's) become requests in a mailbox for the second half; this half only checks that the right request is made. As built (wave 5): `M_REQ` and `M_REQARG` in `MENUW`'s state block (`s2layout`'s `MENU_REQUESTS`): 1 `REQ_NEWGAME` (`G_DeferedInitNew`; the skill), 2 `REQ_QUIT`, 3 `REQ_ENDGAME` (1 with the single demo's check), 4 `REQ_LOAD` (the slot), 5 `REQ_SAVE` (the slot; then `m_savedone` with C), 6 `REQ_BENCH`, 7 `REQ_SAVESET` (`docs/m11-parts/s2menu1.md` 1.1) |
| Sounds | `M_Responder`'s sounds [R `m_menu65.s:909-912`] call `sc_start` (the channel logic linked into `MENUW`, 3); the paused frame's `S_UpdateSounds` is `MENUW`'s `sc_update` (0.1 F11). The music's volume is upstream's setting (`SS_SETTINGS+5`), drawn and saved; it changes no AY write (the release's `MUSIC_MENU` is 1: the display page has 4 rows, the sound page 2; wave 6, S2MENU2-2) |

The comparison of the key setup page pokes our //e names and bindings
into ref816's tables before its drawer runs, so upstream's own drawer is
still the truth (6.2); the benchmark page's three accelerator rows are a
named exclusion.

#### 1.5.4 The automap (parts `s2amap`, `s2ovl`)

| Mode | Upstream | Native |
| --- | --- | --- |
| Full (`AM_ACTIVE` without `AM_OVERLAY`) | The view black, the lines into the back buffer, a list of the bytes written; the next frame erases the old list's bytes and draws again; a full list redraws all [R `am_map65.s:1059-1100`, `:1230-1306`, `:1337-1389`] | `AMAPW` (`am_frame`, A = the frame's tics: `AM_Ticker` once a tic, then the map): the frame's lines clipped once into `S2STATE`'s `SS_AMSEG` (upstream's `drawWalls`, `drawPlayers`), then four bands of 42 rows, each from zeros, each line that crosses it drawn with upstream's Bresenham and only the band's rows plotted, each plotted byte into the new list (2,048 entries [A], a full list as upstream's overflow); published: all rows when upstream redraws all, else the old list's and the new list's bytes (both by band, the old in `SS_AMOLD`) and the strip's rows (`clearStrip`); upstream's count of bytes. The screen after it is upstream's in the lines' rows; the strip's and the title's rows it blacks are `P2DW`'s (`S2_MAIL`, S2AMAP-3). Part s2amap, docs/m11-parts/s2amap.md (as built in wave 6, S2AMAP-5) |
| Overlay (`AM_ACTIVE` with `AM_OVERLAY`) | `K_OVL` records appended after the view's, through the list pages, with `FSCUTE` on the fill spans [R `am_map65.s:1461-1509`; `lists.inc:65-106`] | `OVLW` (`$6800-$9BFF`, `MASKW`'s code room; bank 93): `s2_ovl.s` (`am_ovl`, A = the frame's tics: `AM_Ticker` once a tic, `titleBand`, the rows' colours, the walls and the arrow by part s2amap's `s2_amline.s` with the rotation's fast turn of upstream (`fastSetup`, `fastLine`, `fpoint`: request S2OVL-1), each pixel a `K_OVL` record through `mrec_room` with `FSCUTE` on `FSTOP`/`FSBOT`), milestone 8's `rrec.s` (`-D MREC`) and `bucket.s`'s `nm_bkload` with `BKFAR`/`BKFAR2` as data (the frame image's bytes). The frame driver loads `OVLW` (`far_pload` of its page runs) after `nm_masked`'s last batch and calls `$6800`; `am_ovl` ends with its own `nm_bkload`, so `MASKW` is not loaded again. The replay draws the records (milestone 5's `K_OVL`). Part s2ovl, `docs/m11-parts/s2ovl.md` (as built in wave 7, S2OVL-5; the design's estimate was about 4.3 KB of 65C02 for upstream's 3.3 KB of 65816 [M: `build/linkmap.json`]: `s2_ovl` is 1,214 B [M] because the line code is `s2_amline.s`'s) |
| Title band, keys, follow, zoom, pan, marks | [R `:1186-1219`, `:228-1033`] | `AMAPW` (`AM_Responder` takes upstream's events, 2.4); `am_ticker` at frame time, run once a tic of the frame (it depends only on the last player position and on per-tic constants [R `:710-830`]) |

A full-automap frame draws, as upstream's `display` [R
`d_main65.s:526-536`]: `AMAPW` (the map, published), then `P2DW` (the
palettes, the status bar, the HUD with the map's title, the input poll,
the effect service). `AMAPW` holds neither the poll nor the effect
service; its publishes end drained (`RAMWRT` off waits [R `NATIVE.md`
5.2]), so `P2DW`'s `$Cxxx` accesses after it wait for nothing.

**D-AM1** (wave 6, S2AMAP-5). `AMAPW` publishes before `P2DW`'s
`s2_begin`: in the frame where the view's rows take the map's palette
(`I_ViewPalette(AMAP_PAL)`, the first full-map frame) or the strip turns
on, the map's bytes reach the screen before their SCBs (upstream's redraw
shows the SCBs first; its lists, `showBytes` inside `AM_Drawer`, the
bytes first). The frame's final screen is upstream's. `AMAPW` never calls
`s2_begin` (its `s2_begun` is 1).

Half and two-thirds views (`halfOvl`, `AM_Clean`) are milestone 13's,
with the view sizes.

#### 1.5.5 The intermission (part `s2wi`)

`WI_Drawer`, `drawStats`, `drawShowNextLoc`, `drawAtNode`,
`slamBackground`, `drawCenteredPatch`, `drawPercent`, `drawNum`,
`drawTime`, `WI_Init`'s lumps [R `wi_stuff65.s:96-200`, `:586-903`] in
`WIW`, composing each 40-row band from the `WIMAP0` picture and the
patches. It reads milestone 10's `wi` state (GAME.md 1.5's "`wi` state,
about 40 B": `wi_stuff65.s`'s counters [R `wi_stuff65.s:71-93`])
through the generated include (`llayout.py --game`'s `lgame.inc`), by the
names that include gives, read only but `WI_SNLPTR`, which `WI_Drawer`
sets to 1 in NoState as upstream [R `wi_stuff65.s:586-592`] (wave 5,
S2WI-4). The
intermission's sounds come from `WI_Ticker`, milestone 10's (0.1 F11).

#### 1.5.6 The finale, the pages, the loading sign (part `s2fin`)

| Screen | Upstream | Native |
| --- | --- | --- |
| The finale | `F_StartFinale`, `F_Ticker`, `F_Drawer`, `F_TextWrite`, `textSpeed` [R `f_finale65.s:60-277`] | `F_Ticker` is tic-side (`s2t_fin.s`), after milestone 10's `WI_checkForAccelerate` (S2FIN-4); the drawer in `FINW`: the `FLOOR4_8` background and the text, then `HELP2` |
| The pages | `D_PageDrawer`: `V_DrawRawFullScreen` of `TITLEPIC` [R `d_main65.s:417-422`] | `FINW` (`s2_picture`); the title loop that chooses them is the second half's |
| The loading screen | `F_LoadScreen` [R `f_finale65.s:279-284`] | `FINW` |
| The busy sign | `bmSignOn`, `bmSignOff`, `bmSignBox`, `bmSignPatch` ("LOADING...", "SAVING...") [R `m_menu65.s:1799-1990`] | `FINW`: the sign drawn by columns into a band over the rows under it, which the first `bmSignOn` saves by one memory-API COPY of aux 0's rows 88-111 to `SS_SIGN` (a source in aux 0, F10) and `bmSignOff` publishes back; the sign's state `F_SIGNON` in FINW's own block (wave 6, S2FIN-1, S2FIN-7). The font is `s2_fin.s`'s own (S2FIN-8 with S2MENU2-4) |

#### 1.5.7 Full-screen pictures

A picture is 32,000 pixel bytes, 200 SCBs, 16 palettes and its pair
tables [R `i_viigs65.s:60-64`, `:1226-1295`]. `s2_picture` sets
`palettecount`, the picture's palettes and SCBs in the state, then
publishes the pixels in five bands (a band `far_get` into W, published);
the first band's `s2_begin` writes the black palettes and the SCBs
before it, and `s2_finish` the colours after the last band (1.3, 1.5.8).
Its pair tables become the 16 nibble tables for the patches drawn on it.

#### 1.5.8 The wipe

Upstream's (F1): when `palettecount` is not 0 (a new picture), the 512
palette bytes are written black, then `newColors` (the tint, the SCBs),
then the marked bytes, then the picture's colours [R
`i_viigs65.s:327-345`, `:392-405`]. Natively the same, in the same order,
through `s2_begin` and `s2_finish` (1.3): the black palettes and the
SCBs before the frame's first band, the colours after its last. Each
step's screen is compared (6.3): ref816's screen after `showDirty` inside
`D_Wipe` (a dump at `pictureColors`' entry) against the native screen
after the bands, and the screens after the colours; and the order itself
is checked on the write log (the first band store after the last black
palette store and the last SCB store; the first colour store after the
last band store), since the two snapshots alone cannot see new pixels
shown in the old palettes. The first title page after the boot gets the black too
(`titleWipe` [R `w_level65.s:1400-1448`] needs the loader's gray title,
which the native boot does not show): a named difference of the first
page's first frame.

### 1.6 What each screen reads (the injection's inputs)

| Screen | Game state (milestone 10's places, read only) | 2D state (this half's, `S2STATE`) |
| --- | --- | --- |
| Status bar | `G_PLAYER`: health, armorpoints, ammo, maxammo, readyweapon, weaponowned, cards, powers, cheats, damagecount, bonuscount, attackdown, mo, attacker; `weaponinfo`'s ammo type (`GTAB`); the menu flag; `fps_show` | the widgets' old values, `st_palette`, `STCACHE`; and in the card, because the tic-side `st_ticker` and `st_start` write them (4.4): `st_faceindex`, `st_facecount`, `st_priority`, `st_oldhealth`, `st_lastattackdown`, `st_oldhealthPO`, `st_lastcalc`, `st_randomnumber`, `keyboxes`, `oldweaponsowned`, `st_refreshed` |
| HUD | `G_SHOWMSG`, `G_MSGKEEP` [R GAME.md 1.5]; `gamemap`; `AUTOMAP` (frame block [R `rlayout.py:533-534`]) | `w_title`, `w_message`, the text cache; and in the card, because the tic-side `hu_ticker` and `hu_start` write them (4.4): `message_on`, `message_new`, `message_counter`, the line's message id, the title's map |
| Palettes | the level's `GSVIEWn` (`LVC`), gamma (render inputs [R `MEMORY_MAP.md` 12]) | 1.3's table |
| Menus | game state, usergame, demoplayback, the settings | `currentMenu`, `itemOn`, `skullAnimCounter`, `whichSkull`, `messageToPrint`, `messageKind`, the save strings, the static screen's versions |
| Automap | `LVG0` lines, `LNMAP` (`ML_MAPPED`), the player's mo, `gamemap`, the cheats | `m_x`, `m_y`, `m_w`, `m_h`, the scales, `automapmode`'s bits, the marks, `am_valid`, the byte lists |
| Intermission | the `wi` state and `wbs` (GAME.md 1.5, by the generated include's names) | the lumps' handles |
| Finale | `gameaction`, `acceleratestage` | `finalestage`, `finalecount`, `midstage` |

## 2. The platform

### 2.1 The frame and the `$Cxxx` rule

Every `$Cxxx` access is a bus cycle that waits on F1.2.1 for the SHR
bytes still to drain [R `NATIVE.md` 5.2, 10]. A level frame, in order:

| Step | `$Cxxx` | Why there |
| --- | --- | --- |
| Tic phase (milestone 10): tics, tic-side modules (the status bar's, the HUD's, the finale's tickers; the channel logic's starts and stops), then `sc_update` once | far layer only | |
| `VIEWTOP` from the HUD's `message_on` (as `display` [R `d_main65.s:469-474`]; request R7) | none | before the render reads it |
| Render phases, replay (milestones 7, 8, 5); `OVLW` after the masked phase when the overlay is on | far layer; `titleBand`'s `RAMWRT` window (1,280 B when `am_band` was 0) and the replay's: `RAMWRT` off waits for their drain | |
| `P2DW` loaded (in a full-automap frame: `AMAPW` first, which publishes the map, then `P2DW`) | `far_pload`'s switches | |
| **Input poll** (`pl_poll`) | `$C000`, `$C010`, `$C061`, `$C062`, mouse card `$C0A0-$C0AF` | first after the replay: nothing pending yet [A] |
| **Effect service** (`fx_service`): the channels' mailboxes, voices, ring copies; then S2's `snd_refill` (the music's ring) | `far_get` windows | before any 2D store, so no window waits for 2D bytes |
| 2D compose (status bar, HUD) and `far_get` of backgrounds | far windows | still nothing pending |
| **Publish** (bands, SCBs, palettes) | `RAMWRT` on, stores, `RAMWRT` off (waits for these bytes' drain) | last, so the next frame's tic phase starts drained |

The VBL interrupt reads `$C0A0` and writes `$C0AF` wherever it lands, so
its entry waits for the drain (up to several ms in a heavy replay [R
`NATIVE.md` 5.2]); the music and the clock tolerate that jitter (a note
up to one interrupt late is the design [R `tools/sound/README.md`
"What needs the owner's ear"]). Mode frames (menu, intermission, finale,
pages) put the input poll, `fx_service` and `snd_refill` first after the
tic phase, the same way: **every frame image** (`P2DW`, `MENUW`, `WIW`,
`FINW`) links `pl_poll` and `fx_service` and calls them once a frame, so
the rings are refilled and the mailboxes emptied in every frame, whatever
it shows (`AMAPW` is always followed by `P2DW`, 1.5.4; `PALW` and `OVLW`
are not frame images). A frame where the menu pauses the game has no tic
phase [R `d_main65.s:261-279`]: `MENUW` runs `sc_update` before its
`fx_service` (3).

### 2.2 The clock (part `plclock`)

| Item | Native |
| --- | --- |
| Source | The mouse card's VBL interrupt (mode `$09`), required at boot [R `NATIVE.md` 15.1 row 12; `demos/doom/src/kernel/input.s:102-136`] |
| PAL or NTSC | VIA-A's timer 1 over one VBL: 20,280 bus cycles PAL, 17,030 NTSC, the nearer wins (as `MUSIC.SYSTEM` [R `tools/sound/README.md:395-405`]); the card counted 20,281 [M: `docs/results/music-card-2026-09-30.md`] |
| Rate | A 16-bit fraction a VBL: `TIC_FRAC` 45,743 (PAL) or 38,229 (NTSC); a carry is a tic. 50.0801 × 45,743/65,536 = 34.9551 and 59.9227 × 38,229/65,536 = 34.9546 tics a second [A], against upstream's 34.955 [M: MILESTONES 2] (F2) |
| `I_GetTime` | `pl_time`: the 32-bit tic count, read with interrupts masked for its four bytes: A, X, Y bits 0-23, bits 24-31 in `CLK_TIME3`, P's I bit kept (wave 2, PLCLOCK-1) |
| State | Card `$E403-$E412` (`MEMORY_MAP.md` 4.2's IRQ state): the fraction a VBL `CLK_STEP` (2), the fraction (2), the tics (4), the standard (1: 0 PAL, `$80` NTSC, S2's `SONG_NTSC`), `pl_time`'s fourth byte (1), 6 spare; the VBL count is S2's `vbl_count` in the IRQ's zero page (part `plclock`, request PLCLOCK-1, applied in wave 2) |
| Frame limit | Upstream's `MAXTICS` 4 and `tryRunTics` are the second half's main loop; this half gives the count |

### 2.3 The IRQ handler (part `plclock`; effects `fxplay`)

One entry, `pl_vbl`, at the main card's `$FFFE`, in `$E900-$F8FF`
(`MEMORY_MAP.md` 4.2: "platform IRQ additions about 64 B"), replacing
S2's `snd_vbl` as the vector (S2's `irq.s` is not changed: `MUSIC.SYSTEM`
keeps it):

1. `pha`, `phx`, `phy`; a BRK (P's bit 4 on the stack) goes to the crash
   stop (as `kstart.s` [R `demos/doom/src/kernel/kstart.s:197-212`]).
2. Read `$C0A0`, write 3 to `$C0AF`; only the VBL cause counts [R
   `kstart.s:267-285`].
3. The clock (2.2).
4. `fx_step` (the effect player's steps: each active voice's ticks from
   its ring, then chip 3's registers composed into its own list; no I/O;
   a few cycles when no voice is active).
5. `snd_tick` (S2's music player, unchanged: its burst of chips 0-2).
6. `fx_burst` (chip 3's registers that differ from the effect player's
   shadow, straight after the music's burst, so the two bursts share one
   slot-4 slowdown tail [R `tools/sound/README.md` "The Doom configuration
   profile"]; nothing at all when no effect plays and the shadow is valid,
   so the music's AY log is S2's byte for byte). Nothing either while
   `FX_HOLD` is set (a song is starting, 3).
7. Restore and `RTI`.

The contract stays `MEMORY_MAP.md` rule 2 and S2's: zero page `$D8-$FF`,
the stack, `$E000-$FFFF`, `$C0A0-$C0AF`, `$C400-$C4FF`; every test runs
with `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`. Stack ≤ 24 B
[R `MEMORY_MAP.md` 2]; the part measures it (`--lowest-s-in` of the
handler's range).

**The aux-card copy** is the pair build's (milestone 13: tics with
`ALTZP` on [R `MEMORY_MAP.md` 4.4]). On F1.2.1 the aux card is full of
tables and `ALTZP` is on only with interrupts masked (rule 7), so it gets
no copy. The part writes the bridge anyway (`pl_bridge.s`, `$FF00-$FFF9`
and the vectors of the aux card: `ALTZP` off, the main handler, `ALTZP`
on, `RTI` from the aux stack) and tests it on a2vm in a synthetic image
whose aux card holds only the bridge and whose main loop runs with
`ALTZP` on.

**Worst-case length.** Measured from the AY log's `irq`/`rti` times on
a2vm (`--cost f121+phasor+window32`, the Doom profile): the music's worst
is 14,200 cycles of compute without the writes [M: S2 "Cost"]; the part
reports the handler's worst with music and three effects starting
together, in cycles and µs, both profiles, and the slowdown tail an
interrupt with effects pays beyond the music's alone (window 32 and 512),
since an interrupt where the music writes nothing but an effect does
pays a tail of its own. **As built** [M: 8.14]: the music alone 1,547.9
µs at worst (`D_INTRO`), three effects starting on its first chord
2,047.9 µs; the extra tail 42 µs (window 32) and 529 µs (window 512);
stack 16 B.

### 2.4 Input (part `plinput`)

| Source | Read | Becomes |
| --- | --- | --- |
| `$C000` | a new key (strobe set), its code; `$C010` written to clear it | an //e key code 1-127 |
| `$C010` | bit 7: a key is down [R `demos/doom/src/kernel/input.s:9-13`] | the held key goes up when it clears |
| `$C061`, `$C062` | Open Apple, Solid Apple | pseudo-keys `$72`, `$73` |
| Mouse card | X between two reads of the sequence byte, re-centred; buttons [R `input.s:185-235`] | `PL_MDX` accumulated (upstream's `iigs_mousedx` [R `iigs_asm.s:49-51`]); buttons as pseudo-keys `$71` (button 0) and `$70` (button 1; upstream's `ADB_MOUSE1` is `$70` too, its `ADB_MOUSE0` `$7E` [R `iigs_asm.s:32-33`]) |

**Key codes.** A key from `$C000` is folded to upper case (`$61-$7A` →
`$41-$5A`; the table's character column gives the menus and cheats their
lower-case letter, as upstream's [R `i_iigs65.s:109-246`]), so the //e never
delivers a code in `$61-$7A` and four of them carry the pseudo-keys. The
table keeps upstream's 128 entries (2.4's events, 1.5.3's names).

**The policy** (one key known down at a time, the //e's limit [R
`NATIVE.md` 14 risk 11]):

1. A new key that is not the held key: the held key goes up, the new key
   goes down.
2. The same key again while `$C010` says down: the //e's auto-repeat,
   ignored (upstream makes its own repeats, rule 5).
3. `$C010` clear: the held key goes up.
4. A key that goes down and up between two polls is down for one tic:
   its up waits for the next poll [R `i_iigs65.s:703-707`].
5. Upstream's menu repeat: a menu arrow still down repeats after
   `REP_DELAY` 11 tics, then every `REP_RATE` 4 [R `i_iigs65.s:708-713`,
   `:818-855`], from `pl_time`.
6. The Apple keys and the mouse buttons are independent keys, read each
   poll.

**Events** are upstream's: a //e code goes through the //e key table
(128 entries of a Doom key and a character, upstream's `keyTable` format
[R `i_iigs65.s:83`, `:98-108`]), with upstream's counts so a Doom key
goes down with the first of its keys and up with the last [R `:703-707`,
`:755-811`] (the counts are recomputed each poll from the at most five
sources down, as `recount` does [R `:898-944`], so they need no persistent
bytes), into an event queue (a ring of 15 entries, 14 events, of 3 bytes:
the type and upstream's data1 as a word, a Doom key or a character) that
the second half's `D_PostEvent` drains. A poll makes at
most 7 events (a key up and a key down, two Apple keys, two buttons, a
repeat); a poll that finds fewer than 7 free entries posts nothing: it
reads no new key (`$C000`'s strobe stays set), leaves the Apple keys, the
buttons and the repeat to the next poll, reads the mouse and counts the
deferral (part `plinput`; wave 5 as integrated). The defaults
for the //e: arrows, `W`/`S` move, `A`/`D`, `,`/`.` strafe, `1`-`7`
weapons, `E` and `SPACE` use, `RETURN` use and menu enter, `ESC` menu,
`TAB` map, `-`/`=` zoom, Open Apple fire, Solid Apple use, mouse 1 fire,
mouse 2 strafe. `I_BindKey`, `I_DefaultKeys`, `I_ActionKeys`
[R `i_iigs65.s:857-990`] with the //e table. Run: the menu's ALWAYS RUN
(the //e cannot see Shift alone) [A].

Where: `pl_poll` in every frame image (a shared object, 2.1; A nonzero
while a menu is up), its state and queue in main `$03B3-$03ED` (59 B, 4.2;
request R3), the key table's Doom keys in main `$1F80-$1FFF` (`PL_KEYTAB`,
written only by `pl_keys.s`: the boot's `pl_init`, the key setup's
`pl_bind` and `pl_defaults`; PLINPUT-1), its 16 bytes of zero page `PLZ`
over the drawers' temporaries (4.3). The key setup's capture is the input
block's `PL_BIND` (`$FF` the menu waits, the poll writes the //e code it
took, `$80` idle once the menu bound it), not `MENUW`'s state, since the
poll is the same object in every image (wave 5 as integrated: S2MENU1-4
with PLINPUT-3). `$03B0-$03B2`
are milestone 10's `GS_STATUS` (a byte) and `GS_ARG` (a word) [R
`tools/native/glayout.py:147`, `:778`; `src/native/gcall.s:136-139`;
corrected in wave 1, request S2LAY-3, from `$03B2-$03ED`]
and `$03EE-$03EF` the random indexes `PRND`, `MRND` [R
`tools/native/llayout.py:467`]; `s2layout.check()` imports `glayout` when
it exists and fails on any overlap.

### 2.5 The boot (part `plboot`)

`DOOM.SYSTEM`, written from `LEVELS.SYSTEM`'s boot (`src/native/lboot.s`
[R `LEVELS.md` "Stage B as built"]; a file of our own, `lboot.s`
unchanged):

1. Text screen; the probes: 126 RamWorks banks (each bank's number
   written to its `$0200`, 126 down to 0, read back from 1 up: stop with
   the first missing), the mouse card in slot 2 (required: stop with "NO
   MOUSE CARD IN SLOT 2"), the memory API (required: stop with "NO MEMORY
   API IN SLOT 7"), `snd_probe` (no music: a message, the game goes on
   without music or effects, as `src/sound/README.md` "No music"; the
   effect player stays off, 3).
2. `CATALOG`, then every bank file through the MLI into its banks (the
   `A2DM` format [R `demos/doom/src/kernel/loader.s:36-45`]): the level
   store (`TEXELS.n`, `PATCHES.n`, `MAPS.n`, `TABLES.n` [R `LEVELS.md`
   1.7]), the code library (`CODE.n`: the render images, the load image,
   milestone 10's tic images when they exist, the 2D images), `SONGS.1`,
   `SFX.1`, `GFX.n` (the 2D store), `HUDTXT.1` (the HUD's texts),
   `RTABLES.1` (milestone 8's constant tables, PLBOOT-8), and the card
   images (`LC.BIN`, 32 KB: the aux card's 16 KB, then the main card's,
   each bank 1 `$D000`, bank 2 `$D000`, `$E000-$FFFF`; read in two halves
   into main `$6000-$9FFF`). A ProDOS error, a file that is not a bank
   file or a segment outside banks 1-126 or `$0200-$BFFF` stops
   (`PL_DISK`, wave 8, PLBOOT-1).
3. A CRC-32 of every segment in its bank against the table the disk
   builder wrote (`CRCLIST`: a count, then bank, address, length, CRC-32
   an entry, `LC.BIN`'s halves last; a count other than the segments
   loaded and two stops); a mismatch stops with its bank and address.
4. The install: interrupts off, the card images by CPU copy, main
   `$0200-$03EF` and `$0C00-$1FFF` (the persistent state) and
   `$BF00-$BFFF` cleared, zero page `$00-$17`, the pair zeroed [R
   `NATIVE.md` 10], ProDOS gone (its card and `$BF00` overwritten).
5. The mouse card's VBL on (masked), `pl_init`, `snd_init`, `fx_init` with
   `snd_probe`'s answer, `pl_clkset`, `CLI`, `pl_detect` (PAL or NTSC,
   2.2: it needs `pl_vbl` and the VBL running, PLCLOCK-3), the ready
   state: `PL_STATUS` (main `$03AE`, `LV_STATUS`'s byte) = `PL_READY`, the
   tic clock running, and a loop at `pl_ready` (`$FF00`, 8 B) that the
   second half replaces with the title loop.

`tools/native/pldisk.py` writes `build/native/m11/plboot/DOOM.hdv`
(ProDOS 2.4.3 as `musicdisk.py` does; 3.9 MB, part `plboot`) and
`--check`s it on a2vm (6.5). (Wave 8, PLBOOT-5. Not loaded by the boot:
the static tables that `MEMORY_MAP.md` 3.2 and 5 give to "boot, PRIVATE";
`design.md` R7 item 15, PLBOOT-7.)

## 3. The effects (S4)

The design of the converter, the script format, the player, the voices
and the test disk is in [`tools/sound/README.md`](../tools/sound/README.md),
"Effects (S4)". In the machine:

| Piece | Where it runs | Where it lives |
| --- | --- | --- |
| The scripts | | RamWorks `SFX` (bank 103), one per effect, the 10 tuned ones from `tools/sound/fxtune.txt` |
| `sc_start`, `sc_start2`, `sc_stop`, `sc_update` (the channel logic, `fx_chan.s`) | **tic-side** (4.7): the starts and stops from GAME.md's hooks `S_StartSound`, `S_StartSound2`, `S_StopSound` (request R4), the intermission's from `WI_Ticker` through them; `sc_update` once a frame after the tics, upstream's `S_UpdateSounds` from `musFrame`, which runs only when the player has a mobj [R `s_sound65.s:1911-1922`]. In a frame where the menu pauses the game (no tic phase), `MENUW`'s copy runs `sc_update`, and `M_Responder`'s sounds call its `sc_start` (0.1 F11) | one object linked into milestone 10's tic image and into `MENUW`; the channel table (with each channel's last origin position, for the paused frames), the listener's last position, the fake mobj `FM` and the mailboxes in the card (4.4) |
| `fx_service` (the mailboxes to voices, stereo choice, script heads, ring refills) | every frame image, once a frame (2.1) | W, a shared object |
| `fx_step`, `fx_burst` (steps, levels, chip 3's burst) | the VBL interrupt, before and after `snd_tick` (2.3) | the card `$F505-$F8FF`, state `$E413-$E442` and `$E737-$E73F`, rings `$E740-$E8BF` [R `MEMORY_MAP.md` 4.2]; `VATT` in bank `SFX` (wave 3, FXPLAY-2) |
| `fx_song` (every song start) | the main loop, wherever the game starts a song: `FX_HOLD` set, S2's `snd_start`, `FX_INVAL` set, `FX_HOLD` cleared (0.1 F12) | the card, beside `fx_step` |

**The mailboxes** (one a channel, 4 B: flags, sound, volume,
separation). The channel logic never queues: every decision lands in its
channel's mailbox, "latest wins", so the requests of a frame are bounded
by `NUM_CHANNELS` by construction, whatever the frame's tics do (0.1 F4).
`stopChannel` (every cause: `S_StopSound`, the same origin's earlier
sound, `getChannel`'s eviction, a failed start, `S_UpdateSounds`' ended
and inaudible channels [R `s_sound65.s:236-254`, `:279-334`, `:383-423`])
sets *stop* and clears *start* and *volume*; a start (`startSound`) sets
*start* with its sound, volume and separation, which implies stopping
what the channel's voice plays; `I_UpdateSoundParams` (`docVolume` [R
`:698-735`]) sets *volume* with the new volume (the separation is not
used: the side is chosen at the start). `fx_service` takes each channel
in order: *stop* silences the channel's voice; *start* frees the
channel's voice, chooses one (the stereo rule, README), copies the
script's head into its ring and sets the voice active last; *volume*
sets the voice's attenuation; then the mailbox is empty.

**`isPlaying`.** Upstream's reads the DOC oscillator [R `:675-686`;
its use `:383-391`].
Natively a channel plays when its voice is active **or its mailbox holds
a start** that `fx_service` has not yet taken. Without the second half,
every sound started in a frame's tics would look ended to that frame's
`sc_update` (it runs before `fx_service`) and be stopped at once.

**No native mode.** With `SND_NO_MUSIC` (`snd_probe` [R
`src/sound/probe.s:1-30`]) the card is in Mockingboard mode, where ORB
`$17` reaches VIA-B's only AY, the music's chip 2 (the probe detects the
mode that way [R `probe.s:71`]). `fx_init` leaves `FX_ON` 0: `fx_step`
and `fx_burst` return at once, `fx_service` empties the mailboxes and
starts no voice; the channel logic runs unchanged. Effects on a plain
Mockingboard would be the owner's call (NATIVE.md 15.1 row 11 removed
the music's fallback); not built.

**The latency.** A sound decided in a tic starts at the frame's
`fx_service`, after the render and the replay: the sound starts when the
frame that shows its tic appears, about 60-165 ms after the tic on f121
[M: M8, render 64-164 ms]. Upstream's DOC started it at the call, on a
machine at 1.5-2.5 frames a second [M: MILESTONES 2]. Reported, not a
gate (section 9, risk 6).

**The channel logic's comparison** (F3). The build `FXCH8` has upstream's
8 channels.

1. **Starts and stops.** At each captured `S_StartSound` or
   `S_StartSound2` call of demo3, DEMO1, DEMO2 and the tour (1,304 calls
   [M: this design]), the native `sc_start` gets the reference's channel
   table at the call's entry (`CH_SFX`, `CH_ORIGIN` as identities,
   `CH_PICKUP` [R `s_sound65.s:78-80`]), the origin's and the listener's
   positions and angle, `snd_SfxVolume`, `gamemap`, the reference's
   `isPlaying` answers (the DOC reads) and its `startSound` result (a DOC
   plan miss stops the channel [R `:251-254`, `:265-270`]: injected,
   counted, named); it must give the reference's channel, `SS_VOL`,
   `SS_SEP`, the audibility, the channel table after, and every stop
   (`stopChannel`'s calls, by channel). `S_StopSound` (751 calls [M: this
   design]) the same. The positions are the deltas upstream holds in
   registers inside `adjustParams` (dump points at its JSL to
   `R_PointToAngle3` and its loads of the view angle) and `absDelta`'s
   |delta|, from a listener at (0, 0) or `FM`: upstream's arithmetic uses
   only differences modulo 2^32 (`docs/m11-parts/fxchan.md` 3.2; wave 4,
   FXCHAN-6).
2. **`S_UpdateSounds`** once a frame: `musFrame` reaches it by `jmp` [R
   `s_sound65.s:1921`], so it is captured with `--call-log ...,jumps=1`
   [R `tools/ref816/README.md` "--call-log"], with the reference's
   `isPlaying` answer for each channel injected; the stops (ended,
   inaudible) and each `docVolume`'s channel, `SS_VOL` and `SS_SEP`
   must equal the reference's.
3. **Eviction and the rare paths.** `ref816 --call` of `S_StartSound` from
   synthetic states with all 8 channels busy: priorities lower, equal and
   higher than the new sound's, the same origin with and without the
   pickup flag, no origin, the player's origin, a failed start. The part
   reports, for each labelled path of `S_StartSound` and `getChannel`
   [R `:236-334`], the compared calls that take it; a path with none
   fails the checkpoint (`getChannel`'s same-origin stop [R
   `s_sound65.s:293-302`] is unreachable after `S_StartSound`'s kill of
   the same origin and kind [R `:245-258`]: named, not required;
   `docs/m11-parts/fxchan.md` 3.1).
4. **A frame of tics.** A synthetic case where a start falls in a frame's
   first tic and that frame's `sc_update` follows: the channel still
   plays and its mailbox still holds the start (the case the per-call
   comparison cannot see).

The release build (3 channels) is checked against
`tools/sound/fxchan.py`, the host model of the channel logic, which
itself equals the reference on every case of 1-3 in the 8-channel
configuration, and on 10,000 random call sequences.

## 4. Layouts and placement

Every address below is [A], a starting allocation that `s2layout.py`
(part `s2lay`) holds as constants and checks against `rlayout.py`,
`llayout.py` and, once it exists, `glayout.py` (all three read only).

### 4.1 W images (F1.2.1)

Each 2D image is linked at W's addresses with the shared `MATHW` and
`AUXW` bytes at `$6000-$6592` [R `MEMORY_MAP.md` 13, 15] (the divides,
`pta3`, `M_Random` for the parts that need them). A bank stores only an
image's initialized pages (its page runs for `far_pload` [R `far.s:329-343`]),
so images whose stored runs are disjoint share a bank; the `MATHW` pages
are stored once a bank.

| Image | When it is in W | Stored (code and constants) | Runtime only (bands, caches) | Load |
| --- | --- | --- | --- | --- |
| `P2DW` | every level frame: after the replay, or after `AMAPW` in a full-automap frame | `$6600-$82FF` (7,424 B room): status bar, HUD, message texts and font widths, the shared objects below | `$8300-$96FF` the band (the status bar's rows 168-199, then the strip's rows 0-9); `$9700-$97FF` marks; `$9800-$B7FF` eight nibble slots (1.3); `$B800-$BBFF` patch fetch buffer (1 KB: larger patches a column run at a time, 1.4); `$BC00-$BFFF` the state block (1 KB, loaded and written back, 4.6) | about 8.3 KB a frame, 2.0 ms at 0.246 µs a byte [A on M: `NATIVE.md` 4.3], plus the nibble tables the frame needs (0.25 ms each) |
| `MENUW` | while a menu is up (the game is paused: no tic image) | `$6600-$A4FF` (16,128 B room; `$A7FF` until wave 5, S2MENU1-2) | `$A500-$A7FF` `PALST` (`s2_pal`'s `s2_begin` and `s2_finish` need it in W); `$A800-$B6FF` a 24-row band (3,840 B); `$B700-$B7FF` `UI_GRAY` (the font's reds are `M_FONTBUF` in the state block); `$B800-$B8FF` the drawers' marks; `$B900-$BCFF` the menu palette's nibble slot; `$BD00-$BEFF` fetch buffer (`fx_chan`'s scratch `$BEE0`, never live during a draw: FXCHAN-4); `$BF00-$BFFF` state | when the menu opens; it stays in W while the menu is up (no tic or render image runs [R `d_main65.s:261-279`]), its state block written back when it closes |
| `AMAPW` | full automap frames, after the tic phase, before `P2DW` | `$6600-$8DFF` (10,240 B room) | `$8E00-$A83F` a 42-row band (6,720 B [A]); `$A840-$AFFF` marks and state; `$B000-$BFFF` the new byte list (upstream's 3,000 entries [R `am_map65.s:68`] cut to 2,048 [A], a full list redraws all as upstream's overflow) | each automap frame, about 8.2 KB, 2.0 ms |
| `WIW` | intermission frames | `$6600-$7FFF` (6,656 B room) | `$8000-$98FF` a 40-row band; `$9900-$99FF` marks; `$9A00-$B9FF` the nibble tables: 16 units of 2 pages (a palette and a parity; part `s2wi`: a 22-row patch on `WIMAP0` can need 10 palettes; wave 5, S2WI-6); `$BA00-$BBFF` fetch buffer; `$BC00-$BFFF` state | each intermission frame |
| `FINW` | finale, pages, the loading screen, the busy sign | `$6600-$7FFF` (6,656 B room) | as `WIW` (the 16 units hold a band of 16 rows of the flat and the text; the pictures' bands are 40 rows; wave 6, S2FIN-6) | when drawn |
| `PALW` | a level's first frame and a gamma change (`I_ReloadPalette` [R `i_viigs65.s:318-328`]): `TINTPAL` and the 16 nibble tables built into `S2PAL` | `$6600-$7FFF` | `$8000-$BFFF` the build's buffers | then `P2DW` |
| `OVLW` | after `nm_masked`'s last batch in a frame with the overlay (1.5.4) | `$6800-$7FE2` (6,115 B [M] of the 13,312 B room, `MASKW`'s code room [R `MEMORY_MAP.md` 13]; milestone 8's W ranges outside it untouched): `jmp am_ovl`, `s2_ovl.s`, `s2_amline.s`, `rrec.s`, `nm_bkload` and `BKFAR`/`BKFAR2` as data | `$9400-$9BFF` (the nibble pages, `NCACHE`, `RBASE`, the variables, `AMW`, `AMST`; `s2layout`'s run time range, inside the room: its stored bytes must stay below `$9400`, wave 7); milestone 8's otherwise | `far_pload` of its page runs from bank 93: 1.52 ms `f121` [M] |
| *Packing* | | `s2layout.py` puts each image's stored page runs in a bank of its own among 107, 108, 94, 95, 96, 97 (`far_pload` copies to the same addresses [R `far.s:330-343`] and every image is stored from `$6600`, so two images never share a bank; `MATHW` once a bank), and fails when one cannot (wave 1, request S2LAY-1: the first design's 107, 108 and 94 held three of the six) | | |

**Size table.** Each image's room must hold its own code and data and the
shared objects it links; the budgets are [A] (upstream × 1.3, 7.3),
checked by `s2layout.check()` against each image's ld65 map at every
build (an image over its room fails the build):

| Object (owner) | Budget | `P2DW` | `MENUW` | `AMAPW` | `WIW` | `FINW` | `PALW` |
| --- | ---: | :-: | :-: | :-: | :-: | :-: | :-: |
| `s2_draw` patch drawer, raw, background, and `s2_pub` the publish (`s2draw`) | 1,200 | x | x | `s2_pub` only, 200 | x | x | |
| `s2_pal` `s2_begin`, `s2_finish`, `newColors`, `pictureColors`, `ST_doPaletteStuff`, `I_ViewPalette`, `I_MessageStrip` (`s2pal`) | 800 | x | x | | x | x | |
| `s2_nib` nibble tables from pairs (`s2pal`) | 400 | | x | | x | x | x |
| `pl_poll` (`plinput`; 554 B [M]) | 600 | x | x | | x | x | |
| `pl_keys` `pl_init`, `pl_defaults`, `pl_bind`, `pl_action` (`plinput`; 228 B [M]; wave 5, PLINPUT-5) | 300 | | x | | | | |
| `fx_service` (`fxplay`) | 400 | x | x | | x | x | |
| `fx_chan` (`fxchan`) | 1,100 (700 until wave 4: FXCHAN-5; in `MENUW` 1,055 B [M] with `fx_pcache`'s 85, counted here since wave 5: S2MENU1-2) | | x | | | | |
| Own code and data | | 3,900 (`s2stbar` 2,000, `s2hud` 1,700: 1,411 [M] with the font 252, its texts in `S2STATE` since wave 4 (S2HUD-3); glue 200) | 11,328 (`s2menu1` 5,000, `s2menu2` 4,000, names and strings 2,328: 2,500 until wave 5, when S2MENU1-2's room and PLINPUT-5's `pl_keys` met; as built in wave 6, both parts 7,533 [M]: `s2menu2` 1,852 in `MENUW` with the names' 1,024, S2MENU2-5) | 7,000 (`s2amap`: 6,808 [M], S2AMAP-5) | 1,950 (`s2wi` 1,400, data 550: 1,924 [M]; 1,800 until wave 5, S2WI-2) | 2,300 (`s2fin` 1,600, data 700: 2,213 [M]; 2,100 until wave 6, S2FIN-3: the end text and the font's table) | 1,500 (`s2pal`) |
| **Total / room** | | 6,900 / 7,424 (6,093 [M] linked whole: 8.13) | 16,128 / 16,128 | 7,200 / 10,240 | 5,350 / 6,656 | 5,700 / 6,656 (5,405 [M]) | 1,900 / 6,656 |

`OVLW`: `s2_ovl` 1,214 B and `s2_amline` 3,708 B [M], `rrec.s` 198 B,
`nm_bkload` 48 B and `BKFAR`/`BKFAR2` 947 B [M]: 6,115 of 13,312 B (part
s2ovl; the stored bytes below its run time places at `$9400`, 11,264 B).

### 4.2 Main memory

| Range | Use | Persistent | Note |
| --- | --- | --- | --- |
| `$03B3-$03ED` (59 B) | input: the event queue `PL_QUEUE` `$03B3-$03DF` (15 × 3 B), its head and tail `PL_QHEAD` `$03E0`, `PL_QTAIL` `$03E1`, the held key `PL_HELD` `$03E2`, the Apple keys' and buttons' state `PL_BUTTONS` `$03E3`, `PL_MDX` `$03E4-$03E5`, the mouse's last X `PL_MLX` `$03E6-$03E7` (PLINPUT-2), the repeat's key, character and next tic `PL_REPKEY` `$03E8`, `PL_REPCH` `$03E9`, `PL_REPTIC` `$03EA-$03EB`, the deferral count `PL_DEFER` `$03EC`, the key setup's byte `PL_BIND` `$03ED` (`$FF` waiting, the code taken, `$80` idle; PLINPUT-3) | yes | free since milestone 9 [R `MEMORY_MAP.md` 14-16] but `$03B0-$03B2`, milestone 10's `GS_STATUS` (a byte) and `GS_ARG` (a word) [R `glayout.py:147`, `:778`]; `$03EE-$03EF` are `PRND`, `MRND` [R `llayout.py:467`]; request R3; wave 1 (S2LAY-3) moved the block from `$03B2` |
| `$1F80-$1FFF` (128 B) | `PL_KEYTAB`: the Doom key of each //e code (2.4), written by `pl_keys.s` only | yes | in `MEMORY_MAP.md` 3.3's persistent `$1A80-$1FFF`, above milestone 10's game globals (`$1C80-$1EF8` [M: `glayout.regions()`]); wave 5, PLINPUT-1 |
| `$03AE` | `PL_STATUS`: the boot's and a stop's code, then `BRK` (`LV_STATUS`'s byte and rule [R `MEMORY_MAP.md` 15]); `$C5` the menu's save of the screen failed (`PL_MENUAMEM`, S2MENU1-2); `$C6` the busy sign's save failed (`PL_SIGNAMEM`, wave 6, S2FIN-1); `$D1` a full-map frame whose lines' rows use more than 4 palettes, `$D2` more clipped lines than `SS_AMSEG` holds (`PL_AMPALS`, `PL_AMSEGS`, both impossible upstream; wave 6, S2AMAP-4); `$C7` the boot's disk stop: a ProDOS error, a file that is not a bank file, a segment outside the game's banks (`PL_DISK`, part `plboot`; wave 8, PLBOOT-1) | | shared with the load's stop byte; `s2layout.check()` fails when two stops (`PL`, `S2S`, `llayout.LS`) share a code (wave 8) |
| `$0100-$01B4` | the publish loop's descriptors may use page 1 outside the replay [A]; the stack stays at or above `$01C0` | no | as the replay's gather [R `MEMORY_MAP.md` 2] |
| `$0100-$017F` | `newColors`' bounce: `TINTPAL`'s row from `S2PAL` to aux 0, 128 bytes at a time (`s2_begin`, part `s2pal`) | no | the stack stays at or above `$01C0`; wave 3, S2PAL-4 |
| `$0C00-$1A7F` | nothing: 2D never overlays the renderer's persistent rows (`FS*`, `CV*`, `WCLIP`, `WPREV`, `WTMP`, `FRVIS` [R `MEMORY_MAP.md` 3.3, 13]) | | |

### 4.3 Zero page and stack

| Range | Phase | Content |
| --- | --- | --- |
| `$48-$7F` | 2D images | `S2_*`: the band, the patch's column and post, the nibble slot, the publish pointers (overlay 2, as `MEMORY_MAP.md` 2 gives 2D); `$48-$77` the drawers' (`s2layout.py`'s `S2_ZP` in `s2.inc`, wave 2, S2DRAW-1), `$78-$7F` `s2_pal`'s and `s2_nib`'s temporaries (`S2P_*`, part `s2pal`; wave 3, S2PAL-3); `$5A-$69` `pl_poll`'s temporaries `PLZ` (over the drawers' temporaries `S2_W` .. `S2_O`: the poll runs first in a frame; part `plinput`, wave 5, PLINPUT-4) |
| `$80-$AF` | 2D images | `S2M_*` / `S2A_*` / `S2W_*`: the menu's (`s2menu1.inc`) and the automap's own state (the automap's `$80-$AE`, part `s2amap`; wave 6, S2AMAP-5); `WIW`'s temporaries `$80-$AD` (part `s2wi`; nothing kept between frames, and neither the menu's nor the automap's image runs in an intermission frame: wave 5, S2WI-1); `FINW`'s temporaries `$80-$A4` (`FZ_*`, part `s2fin`; nothing kept between calls; a finale, page or load frame draws no menu, and a menu's save draws its sign with `FINW` in `MENUW`'s place: wave 6, S2FIN-2); `OVLW`'s `s2_amline` places `$80-$AE` between the masked phase and the bucket pass (overlay 2 dead; part s2ovl) |
| `$B0-$D7` | all | the math block [R `src/native/MATH.md`] |
| `$D8-$F6` | IRQ | the music player (31 B [R `src/sound/README.md` "Sizes"]) |
| `$F7-$FC` | IRQ | the effect player's interrupt: the ring of the voice it runs, four temporaries (`FXZ_*`, part `fxplay`; wave 3, FXPLAY-1) |
| `$FD-$FF` | | spare |
| tic-side | tic phase | GAME.md 4.4's conventions: arguments in `GA_*`, temporaries `GT_*`, a scratch block of 32 B each module (request R4) |

Stack: 2D phases at most 64 B [R `MEMORY_MAP.md` 2] plus 24 B for the
IRQ, measured by every run (`--lowest-s-in`).

### 4.4 The main card

| Range | Content | Size |
| --- | --- | --- |
| `$E403-$E412` | the clock: the fraction a VBL, the fraction, the tics, PAL or NTSC, `pl_time`'s fourth byte (the VBL count is `vbl_count`, zero page; wave 2, PLCLOCK-1) | 10 of 16 B [R `MEMORY_MAP.md` 4.2 "IRQ state"] |
| `$E413-$E442` | the three effect voices (16 B each: the script's head and bytes left, the ring's written and read counts, step state, period, level, noise, the channel, the volume's attenuation, the sound; `VOICE_FIELDS`, wave 3) | 48 B [R same] |
| `$E443-$E47F` | the tic-side 2D state: the status bar's (about 25 B), the HUD's (`message_on`, `message_new`, `message_counter`, the line's message id, the title's map: 8 B), the finale's (6 B), `S2_MAIL` (1 B: bit 1 the automap stopped, R6; bits 2 and 3 the strip's and the title's rows black, for `P2DW`; bit 4 a view drawn, for the automap: wave 6, S2AMAP-3); the channel logic's fake mobj `FM` (x, y: 8 B) and the listener's last x, y, angle (12 B); the status bar's `ST_READY` (`W_READY`'s value pointer as `readyNum` sets it at the tic: an ammo index, `$FD` none before the first `ST_Start`, `$FE` `LARGEAMMO`, `$FF` the frame rate) and `ST_RUNNING` (`ST_Start`'s `st_running`; wave 4, S2STBAR-1): the status bar's 26 B | 61 of 61 B |
| `$E737-$E73F` | `FX_ON`, `FX_HOLD`, `FX_INVAL`, the effects' tempo fraction (2), `fx_service`'s 4 temporaries (`FX_SVC`, main loop; wave 3, FXPLAY-1) | 9 B [R `MEMORY_MAP.md` 4.2: spare] |
| `$E740-$E8BF` | the effect rings, 3 × 128 B | [R same] |
| `$E8C0-$E8FF` | the channel table (3 × 12 B: the sound, the origin's kind with the pickup flag in bit 7, its handle, its last x and y, 4 B each; wave 4, FXCHAN-1) `$E8C0-$E8E3`; the mailboxes (3 × 4 B: flags, sound, volume, separation) `$E8E4-$E8EF`; `LS_ON` (the listener exists, bit 7) `$E8F0` and `SND_SFXVOL` (upstream's `snd_SfxVolume`, 0-15) `$E8F1` (wave 4, FXCHAN-2: placed here, as the tic-side block's two spare bytes went to S2STBAR-1); 14 spare | 50 of 64 B |
| `$F505-$F8FF` | `pl_vbl`, the clock and `pl_time` (116 B [M: part `plclock`]), `pl_clkset` and `pl_detect` (128 B, boot-time; PLCLOCK-2 may move them); `fx.s`'s card part: `fx_step`, `fx_burst`, `fx_song`, `fx_init`, `fx_stopall`, `fx_isplaying`, `fx_copy`, `fx_volume` and chip 3's state, 739 B [M: part `fxplay`]. `VATT` stays in `SFX.1` (bank `SFX`, `$02D0`), read through a window by `fx_volume` (wave 3, FXPLAY-2). Every build that links both puts `fx-card.o` before `pl_irq.o` (the frame images resolve the card's routines from that order; part `plboot`'s check, PLBOOT-4), but part `fxplay`'s test image `fxpt`, which runs alone and is never a release image | 983 of the 1,019 B left after S2's code and tables [R `tools/sound/README.md` "MUSIC.SYSTEM": `$E900-$F504`]; 36 B free |
| `$FF00-$FF07` | `pl_ready`, the ready loop the second half replaces (part `plboot`; wave 8, PLBOOT-5) | 8 of 250 B |
| `$FFFE` | the IRQ vector: `pl_vbl` | |

The card's bank 1 (`$DC00-$DFFF`, 35 B left [M: M8]) and bank 2 get
nothing.

**Test builds.** The two blocks' addresses are symbols of the generated
`s2.inc` (`S2T_BASE`, `SC_BASE`), so a test image can move them:

| Build | Card `$E000` part | The blocks |
| --- | --- | --- |
| Release | S2, the effects, the replay's part at `$F900` | as above |
| This half's tests | the test driver `s2_drv` at `$F900-$FEFF` (no 2D test image has a replay; `s2ovl`'s uses milestone 8's `rdriver.s`, below); S2 and the effects where the test needs them | as above |
| Milestone 10's `M11` test build (request R4) | `gdriver.s` at `$E000-$EDFF` [R GAME.md 3.4; `glayout.game_cfg`], the replay's part at `$F900` in its whole-frame mode | `$EE00-$EE3C` and `$EE40-$EE7F` (free there) |
| `FXCH8` (8 channels: table 96 B, mailboxes 32 B, `LS_ON` and `SND_SFXVOL`) | `s2_drv` | `$E000-$E081` (the song ring's place; no music in that image) |

`s2ovl`'s test runs milestone 8's whole frame with `rdriver.s` and its
own driver `s2_ovd.s` after it in `render.cfg`'s `$E000` part (to
`$E383`); `OVLW` reads `HU_ON` and writes `S2_MAIL` at the test build's
places, free there.

### 4.5 RamWorks banks

Against LEVELS.md 1.6's reservations (100-104 songs and effects, 105-110
2D, 112-115 code [R `LEVELS.md:397-400`]) and GAME.md 1.10 (spare after
milestone 10: 1-3, 93-97, 125, 126):

| Bank | Name | Content | Label |
| ---: | --- | --- | --- |
| 100-102 | `SONGS` | `SONGS.1` (part `plboot`): the directory at 100 `$0200` (3 B a song: bank, address, in `mus.UPSTREAM_SONGS`' order; `s2layout.SONG_DIR`, `SONG_DIR_BANK` and `SONG_DIR` in `s2.inc`: wave 8, PLBOOT-2), then the 13 song files, 137,151 B [M: S1], first-fit, largest first, none across a bank (100: 48,503 B with the directory, 101: 43,790, 102: 44,897 [M]) | M |
| 48, 116-122 | (milestone 8) | its constant tables, `RTABLES.1` on `DOOM.hdv` (246,036 B as laid out by milestone 8's runs, `render_check.base_records`; part `plboot`, PLBOOT-8) | R |
| 103 | `SFX` | the effect scripts and the volume table, `SFX.1` (on `DOOM.hdv` a bank file of one segment, part `plboot`): 11,385 B [M: `docs/m11-parts/fxconv.md`] in `$0200-$3FFF` (`s2layout.SFX_ROOM`); the 2D store at `$4000-$BFFF` (31,748 B [M: `docs/m11-parts/s2data.md`; wave 3]). The test disk `SOUNDS.hdv` puts the ten tuned effects' automatic scripts after `SFX.1` in `SFX_ROOM` (`$2E79-$374A`, part `fxdisk`); the game does not | M |
| 104 | `S2STATE` | the 2D state blocks (1 KB an image), `STCACHE` (5,120 B), the HUD text records, the automap's old byte list, the sign's saved rows, `STBUF` (the bar's rows as published, 5,120 B; wave 4, S2STBAR-2), the HUD's texts (`SS_HUDMSG`, 2,672 B of 3,072 [M: part `s2hud`]; wave 4, S2HUD-3), the automap's lines of a frame (`SS_AMSEG`, 12,288 B; wave 6, S2AMAP-2): `$0200-$B11F`; the free part `$B200-$BFFF` (the 2D store places nothing there) | A |
| 105 | `S2VIEW` | the menu's saved screen at `$2000-$9FFF` (`s2layout.S2VIEW_SAVE`); the 2D store at `$0200-$1FFF` and `$A000-$BFFF` (14,839 B [M: `s2data.md`; wave 3]) | M |
| 106 | `S2PAL` | `TINTPAL` `$0200`, the 16 nibble tables `S2NIB` `$1800`, `GSSTAT` `$5800`, `GSOVL` `$6E20`, `GRAYMAP` `$7700` (`s2layout.S2PAL_PLACES`, wave 3, S2PAL-1); `GSSTAT` and `GSOVL` are the 2D store's lumps, which `GFX.1` writes at these places (their handles name them; wave 3, S2DATA-3) | M |
| 107, 108 | `S2CODE0`, `S2CODE1` | `P2DW`'s and `MENUW`'s page runs (`MATHW` once each); the 2D store at `$0200-$5FFF` and, in 107, above `P2DW`'s room at `$8300-$BFFF` (51,158 B [M: `s2data.md`; wave 3]) | M |
| 109, 110, 114, 115 | `GFX0`-`GFX3` | the 2D store: `ST*`, `M_*`, `WI*` patches, `STBAR`, `FLOOR4_8`, `TITLEPIC`, `HELP2`, `WIMAP0` (216 lumps, 295,585 B, and the handles table, 1,080 B, at `GFX0` `$0200` [M: `docs/m11-parts/s2data.md`]; 191,144 B with the table in these four banks, three of them holding one picture each). The 2D store keeps every source in its bank's `$0200-$BFFF` (a `RAMRD` window reaches nothing else), a patch's last column at least 1 KB before `$C000` (the fetch buffer is refilled from a column), every column at most 256 bytes and every raw lump whole rows of 320 bytes (`docs/m11-parts/s2draw.md` 1.1; wave 2, S2DRAW-4); a full-screen raw lump of 64,000 B would not fit one bank's `$0200-$BFFF`: the release has none (its full screens are pictures), and `s2data` checks it | M |
| 113 | `MCODE_BANK` | milestone 8's masked image, unchanged | R |
| 111 | (`LVS`, milestone 10) | | R |
| 93 | `OVLW` | the automap overlay's image (4.1) | A |
| 94 | `S2CODE2` | `AMAPW`'s page runs (4.1's packing: one image a bank) | A |
| 95, 96, 97 | `S2CODE3`-`S2CODE5` | `WIW`'s, `FINW`'s, `PALW`'s page runs (each image's pages start at `$6600`, so one image a bank; wave 1, request S2LAY-1) | A |

The 2D store is 296,665 B [M: `s2data.md`, as integrated in wave 3]:
`GFX0`-`GFX3` take 191,144 B, the free parts of 103, 105, 107 and 108
97,745 B, `GSSTAT` and `GSOVL` 7,776 B at `S2PAL`'s places; 104's free
part, 108's top and 107's top stay free (42,768 B). Banks 93-97 of the
spare are used (since wave 1: 95-97 for the code, S2LAY-1), which leaves
1-3, 125 and 126; part `s2data` measured the store: bank 125 is not
needed (risk 3).

### 4.6 The 2D state between frames

The 2D phases' W is overwritten every frame by the tic and render images,
so each 2D image has a **state block** (1 KB, `$BC00-$BFFF` in `P2DW`; 256 B in `MENUW`):
fetched with `far_get` and written back with `far_put`, 256 bytes a
call [R `far.s:63-79`], between its W block and its place in `S2STATE`
(`s2layout`'s `SS_*`: the palette state `SS_PALST`, 768 B, shared by
every image that publishes, then each image's own part; 0.25 ms a KB
[A]). `P2DW`, `WIW`, `FINW` keep `PALST` at W `$BC00-$BEFF` and their
own 256 B at `$BF00-$BFFF`; `MENUW` its own at `$BF00`; `AMAPW` its
1 KB at `$AC00-$AFFF`. (Wave 1, request S2LAY-2: the first design
loaded the blocks "with the image, a second `far_pload`" and wrote them
back "with one `far_put`", which cannot hold: `far_pload` copies to the
same addresses, and three images' blocks are all at W `$BC00`.) What
the tic phase also reads or writes (the status bar's and the HUD's
tic-side state, the channel table, the mailboxes) is in the card (4.4),
never in a state block.

### 4.7 Tic-side modules

Code that must run inside the tic, at upstream's place in it, but is this
half's: the status bar's ticker (F7), the HUD's ticker (F8), the
finale's ticker, the sound channel logic (3). Each is a module with GAME.md's calling conventions
(arguments in `GA_*`, temporaries `GT_*`, a 32-byte scratch block, and a
callback for an object's position), assembled and tested here in a
test image of our own, and linked into milestone 10's tic image by its
integrator (request R4):

| Module | Entries | Called by | Size [A] | Calls a tic |
| --- | --- | --- | --- | --- |
| `src/native/s2t_st.s` | `st_ticker` (A = `M_Random`'s value), `st_start` | the `ST_Ticker` hook after `flow`'s `st_tick`; the `ST_Start` hook | 900 B | 1 in a level |
| `src/native/s2t_hu.s` | `hu_ticker`, `hu_start` | `flow`'s `hu_tick`, first (request R5); the `HU_Start` hook | 150 B | 1 in a level |
| `src/native/s2t_fin.s` | `f_ticker`, `f_start` | the finale's `F_Ticker` and `W_StartFinale` hooks (today stops `GS_FINALE` [R GAME.md 3.1, `ghook.s`]) | 250 B | 1 in the finale |
| `src/native/fx_chan.s` | `sc_start`, `sc_start2`, `sc_stop`, `sc_update` | the three sound hooks; the driver after the tics (`sc_update`, once a frame); also linked into `MENUW` (3) | 1,100 B (1,085 [M]; 700 until wave 4, FXCHAN-5) | at most 4 starts a tic measured [M: this design]; the mailboxes bound what reaches the player |

The callback `s2t_pos` (A:X a mobj handle → its x, y and angle in
`GT_*`) is milestone 10's to provide with `mo_get` (request R4); our test
images provide a table-driven stand-in, and `MENUW` links `fx_pcache`,
which answers from the channel table's last positions (the game is paused
there, so they are the positions upstream's `S_UpdateSounds` reads).

### 4.8 Cost phases

a2vm counts 32 phases; the renderer uses 0-17 and milestone 10 18-29 [R
GAME.md 5.4]. This half takes **30** (the 2D frame side: `P2DW` and the
mode images) and **31** (the platform: input poll, effect service, boot).
a2vm also counts any value above 31 in phase 31 [R `tools/a2vm/README.md`
"The cost model"]: `s2layout.check()` reads every phase constant of
`rlayout.py`, `glayout.py` (when it exists) and `s2layout.py` and fails
unless each is 0-31 and only the platform's code writes 31, so a phase-31
count is the platform's. A store inside milestone 10's test-build
branches (`.ifdef TESTBUILD`: the routine harness's `fl_timed` and
`fl_tresume` time one routine alone in 30 and 31 [R
`src/native/game/flow/gflow.s:881-896`; `docs/game-parts/flow.md`]) is
checked in 0-31 and readable only: those entries run in milestone 10's
routine-mode runs, which time that routine and nothing of this half
(wave 4 as integrated, 8.8). The IRQ's cost comes from the AY log's
`irq`/`rti` times, not from a phase.

## 5. Interfaces

**Read only, from milestone 10** (`GAME.md`): the player at `G_PLAYER`
[R GAME.md 1.5; `llayout.player_layout`], `G_SHOWMSG`, `G_MSGKEEP`, the
`wi` state (but `WI_SNLPTR`, which `wi_drawer` sets as upstream's
`WI_Drawer`: wave 5, S2WI-4), the game state and action bytes, mobjs
through the
callback; the hooks of `ghook.s` (`S_StartSound`, `S_StartSound2`,
`S_StopSound`, `ST_Start`, `HU_Start`, `AM_Stop`, `AM_Ticker`,
`F_LoadScreen`, `W_StartInter`'s pictures and music, `W_StartFinale`,
`F_Ticker`, `I_GetTime` [R GAME.md 3.1]). **From milestones 7-9:** the
frame block's `VIEWTOP`, `VIEWBOT`, `AUTOMAP` [R `rlayout.py:528-534`],
the render inputs' gamma, `LVG0` and `LNMAP` for the automap, `LVC`'s
`GSVIEWn` record, `mrec_room`, `rrec.s`, `bucket.s`'s `nm_bkload` and
`BKFAR`/`BKFAR2` (linked into `OVLW`, read only), the staging for
`K_OVL`, `far_get`, `far_put`, `far_pload`, `far_mload`, `MATHW`.

**Requests** (each written out in `docs/m11-parts/design.md`; the
integrator applies a request only if it does not collide with milestone
10's edits):

| # | To | What |
| --: | --- | --- |
| R1 | `NATIVE.md` 10 | The clock's rate: the 16-bit fraction (F2) |
| R2 | `MEMORY_MAP.md` 4.2, 5, 11 | The IRQ vector `pl_vbl`; the 79 B of aux 0 `$0271-$02BF` stay free; the checklist's memory-API line names destinations; a section 18 for this half's regions (section 4 here) |
| R3 | `MEMORY_MAP.md` 3.1 | Main `$03B3-$03ED` for input (`$03B0-$03B2` stay milestone 10's `GS_STATUS`, a byte, and `GS_ARG`, a word) |
| R4 | milestone 10 (GAME.md 3.1, 4.3, 4.4) | The release and the `M11` test build of `ghook.s` call the tic-side modules of 4.7; `st_tick` passes `M_Random`'s value; `s2t_pos`; a 32-byte scratch block for each module; their placement in the tic image; `sc_update` once a frame after the tics; every song start through `fx_song`; in the `M11` test build the card's `$EE00-$EE7F` left free for this half's blocks |
| R5 | milestone 10 (`flow`'s `hu_tick`, `ghook.s`'s `HU_Start`) | `hu_tick` calls `hu_ticker` first, then makes its own clears; the `HU_Start` hook calls `hu_start` and clears `G_MSGKEEP`; the message ids' list shared through the generated include |
| R6 | milestone 10 (`ghook.s`) | `AM_Stop` clears `AUTOMAP`'s active bit (which the renderer reads) and sets bit 1 of `S2_MAIL`; `ST_Start` calls `st_start` (R4) |
| R7 | milestone 10's frame driver, the second half | Before the render, `VIEWTOP` from the HUD's `message_on` (`display`'s rule [R `d_main65.s:467-474`]); with the overlay on, `OVLW` (`far_pload` of its page runs, bank 93) after `nm_masked`, then `jsr $6800` (`am_ovl`, A = the frame's tics), which ends with `OVLW`'s `nm_bkload`; after the replay (or after `AMAPW` in a full-automap frame), `far_pload` of `P2DW` and `s2_frame`; a paused menu frame runs `MENUW`'s frame only; a level's first frame and a gamma change load `PALW` first |

## 6. The harness

### 6.1 Reference captures (`tools/native/s2cap.py`, part `s2cap`)

ref816 runs each script with points streamed through a pipe and
distilled as they come, never stored whole (the ground rules; `ref816
--dump-at` [R `tools/ref816/README.md` "--dump-at and the dump stream"]):

| Point | Where | Ranges |
| --- | --- | --- |
| `PD0` | `pc=displayCall` when its operand is `display`; while a menu is up (`uiDisplay`, which never enters `display` [R `i_viigs65.s:2038-2055`]) at `uiDisplay`'s `jsl M_Drawer` and `staticUpToDate`'s skull path, where the frame may first write; a static menu turn dumps nothing (wave 2, S2CAP-2) | the 2D state of 1.6 by symbol (the near and znear data of the units below), `_g_player`, `keyTable`, `keyNames`, `VW_MHID` (stHide's flag; wave 4, S2STBAR-3) |
| `PDF` | `I_FinishUpdate` and `D_Wipe` entries from `display` [R `d_main65.s:552-557`] | the marks `DRB`, `DRE`, `DRY0`, `DRY1` [R `i_viigs65.s:81-82`, `:107-108`]: the bytes the frame's 2D wrote |
| `PW` | `pictureColors` from `D_Wipe` [R `i_viigs65.s:341`] | the screen: the wipe's black step |
| `PD1` | `pc=displayCall+3` when its operand is `display`; a menu's frame ends where the next begins (wave 2, S2CAP-2) | the gametic |
| `PC` | where a write of the screen, `STCACHE`, `TINTPAL` or `AM_LISTS` is complete (`I_FinishUpdate`'s and `I_ShowDirty`'s `RTL`s, `titleWipe`'s return, `bmSignBox`'s, `I_SaveStatusBackground`'s and `V_DrawRaw`'s, `buildTints`', `AM_Drawer`'s with the map on); every 8th frame start dumps all four and checks them (wave 2, S2CAP-2) | the range written |
| `PM` | `I_MenuPalette`'s entry when the menu's palette is off (wave 2, S2CAP-2) | the screen the menu grays |
| `PU0`, `PU1` | each JSL site of `bmSignOn`, `bmSignOff`, `bmSignLoading`, `bmSignSaving`, `bmDiskAsk`, `F_LoadScreen`, `I_MenuPaletteBack` and its return (wave 2, S2CAP-2) | the 2D state and the screen: an update outside a frame |
| `PV` | `R_RenderPlayerView`'s entry from `display` [R `d_main65.s:490`] | `viewtop`, `viewbottom`, `message_on`, `DD_PAUSED`: the frame's `VIEWTOP` (1.5.2) |
| tic points | `ST_Ticker`, `HU_Ticker`, `F_Ticker` entry and return (`--call-log` with `in=`/`out=` of their state and the player's fields) | the tic-side modules' cases |
| sound | `S_StartSound`, `S_StartSound2`, `S_StopSound`, `startSound`, `isPlaying` (its return: the DOC's answer), `docVolume`, `stopChannel` (`--call-log` with the channel table, `SS_*`, `_Dp`, gametic), `S_UpdateSounds` (`--call-log` with `jumps=1`: `musFrame` reaches it by `jmp` [R `s_sound65.s:1921`]), and `--dump-at` of the player and the zone banks at each `S_StartSound` and `S_UpdateSounds` entry for the positions | section 3's cases |

The frames' screen rows of X1 are not kept (undefined, poisoned when
injected). `HU_Ticker` and `F_Ticker` are reached by `JMP` from `G_Ticker`
[R `g_game65.s:615-623`] and logged with `jumps=1` too. `S_UpdateSounds`
runs in every turn of the main loop, about 2,000 a second while a menu is
up: it and its per-turn callees are logged while no menu is up, and the
check is on those turns. The sound positions are not captured: the zone
banks at each call would pass the 200 MB bound; `adjustParams`' entry
(the two mobjs' addresses, the channel block) and return (`SS_VOL`,
`SS_SEP`, audible) are logged instead (`docs/m11-parts/s2cap.md` 1.1 and
open problem 1; wave 2, S2CAP-2).

`bmSignOff`'s screen (it is also reached by `JMP` [R `w_level65.s:519`])
and the nibble tables of the finale's and the signs' cases come from part
`s2fin`'s own capture (`s2fin.py --capture`); the full map's frames and
`AM_Responder`/`AM_Ticker` calls from part `s2amap`'s (`s2amap.py
--capture`: `automap.script` holds no level in `s2cap`'s cases, and both
`AM_Drawer`'s entry and the frame's start are needed); the key setup with
the //e names and the benchmark's result from part `s2menu2`'s runs K1, K2
and B (`s2menu2.py --capture`, 6.2) (wave 6, S2FIN-7, S2MENU2-5).

A case is one frame (or call): the bytes the native side needs, the
screen before (`PD0`), the marks, the screen after (`PD1`), zlib'd, about
10 KB [A]; the raw stream is never kept. Budget: demo3's 1,573 frames (534
level frames) 7.1 MB, the eleven runs 22.9 MB [M: part `s2cap`]; `df -h /System/Volumes/Data` before the
first capture.

**Runs.** demo3 (the title loop to the demo's end, `lumps.demo_script`
[R `tools/ref816/README.md` "--wad, --lump and lumps.py"]), newgame, tour
(its eight intermissions), DEMO1 and DEMO2 (the sound calls), and five
scripts of this half in `coverage/m11/` (part `s2cap`):

| Script | Content |
| --- | --- |
| `menus.script` | From the title: every menu page, every item reached with the arrows (the skull at each), each settings page, the key setup (a binding changed and the defaults back), the quit, end game and nightmare messages answered N; in E1M1 the menu over the view (the gray view), messages off and on (the HUD's message) |
| `automap.script` | E1M1: the map key once (full), zoom in and out, pan, follow off and on (their messages), the map key again (overlay: rotate and follow), walk with the overlay, the map key (off); the computer map (`idbehold a`, `powers[pw_allmap]`: upstream has no `iddt` [R `m_cheat65.s:116-247`, `am_map65.s:1720`]; wave 2, S2CAP-3) |
| `palette.script` | Gamma through the menu at each step, with the view and the status bar on screen; the radiation suit's and the bonus tints (pickups of E1M1, or `--poke-file` of `damagecount`, `bonuscount`, `powers` at named tics) |
| `finale.script` | E1M8 with `gameaction` poked to `ga_victory` at a named tic (`--poke-file`, injected state with a reason: no coverage run reaches the finale [R GAME.md 3.7]), the text to its end, use to accelerate, `HELP2` |
| `signs.script` | A level load from the menu's new game (the busy sign), the tour's world-done load (`F_LoadScreen`) |
| `stbar.script` | E1M1 with `--poke-file` of the player's fields at named tics, one tic a value class (injected state with a reason: demo3, newgame and the tour may never show them, 1.5.1): each skull and card key, each arm owned, ammo and maxammo at 0, 9, 10, 99, 100, 200, 400, health 0 (the dead face), 100, 200, armour 0 and 200, the god mode's face, the backpack, the pain and evil-grin faces, the ammo types' `LARGEAMMO` |

### 6.2 Injection (`tools/native/s2state.py`, part `s2cap`)

A case into a native machine: each upstream field of 1.6 by its symbol
and `offsets.inc` offset into its native place (`s2layout.py`'s field
map: size, encoding `word`/`byte`/`sxbyte`, a patch pointer as a 2D store
handle, a widget's value pointer dropped because the native widget names
its field); the player by `llayout.player_layout` (read only); `STCACHE`
into `S2STATE`; the screen into aux 0 `$2000-$9FFF`; every byte the case
does not define `$A5` in one run and `$5A` in the other (`lrun.py`'s
machines, imported). **Poisoned screens:** a second pair of runs poisons
every screen byte the reference's frame marked (`PDF`'s marks, plus the
SCBs and palettes it wrote); the native drawer must produce all of them
from state. The key setup's names and bindings for the //e are poked into
ref816's `keyNames` and `keyTable` by `--poke-file` at `uiDisplay`'s
entry the first time `currentMenu` is the key setup (8) (`M_Drawer`'s
entry comes after the case's `PD0` dump), so upstream's drawer stays the
truth (1.5.3); the menu's own keys go through `keyTable` too, so such a
run stops on that page (wave 2, S2CAP-4); and a second run with the names
alone, the bindings upstream's, each frame's `keyTable` injected 1:1 into
`PL_KEYTAB` (part `s2menu2`, runs K1 and K2; wave 6, S2MENU2-5).

### 6.3 Comparison (`tools/native/s2check.py`) and named exclusions

Each part lists its **region**: rows and byte ranges of the screen, SCBs,
palettes. In the region the native screen equals `PD1`'s byte for byte;
outside it, every byte keeps its injected value or poison, and the write
log (a2vm `--write-log` [R `tools/a2vm/README.md` "The write log"]) has no
write outside the part's allowed set (its W ranges, its bank ranges, the
card ranges of 4.4, aux 0 in its region). Exclusions, each counted and
named in the report:

| # | Excluded | Why |
| --: | --- | --- |
| X1 | The view's rows in a level frame: rows 0-167 when the reference's `viewtop` (point `PV`) is `$FFFF`, rows 10-167 when it is 9 | The renderer's; compared by milestones 8 and 10's frame tests. Rows 0-9 are never excluded when the strip is on; when it is off, the HUD part checks that it wrote none of them, and every level frame's native `VIEWTOP` (from the tic-side `message_on`) must equal the reference's `viewtop` (1.5.2), so a late `message_on` fails |
| X2 | The benchmark page's `CPU`, `CACHE`, `ROM` rows; the native rows there must be black | ZipGS and TransWarp dropped (1.5.3) |
| X3 | The first title page's first frame's palette (`titleWipe`) | No gray boot title natively (1.5.8) |
| X4 | Calls where upstream's `startSound` failed: the native decision is compared, the reference's stop of that channel is injected | F3 |

**The publish order** is checked on the write log of every frame (1.3,
1.5.8): no band store before `s2_begin`'s last black palette and SCB
stores, no picture colour store before the last band store.

**Chained runs** besides per-frame injection: the status bar and HUD over
all 533 frames of demo3 from the first frame's state only (the native
state carried by the native code), and the menus' and automap's scripts
the same way.

### 6.4 Timing

Each part's checkpoint runs its frame-side entry over its cases under
`--cost f121` and `--cost fastpath` with `--cost-timed`, and reports per
frame the median, p99 and worst in ms, with the image's load and the
publish's drain apart; tic-side modules per call. The integration
gathers them (8.3).

### 6.5 Platform tests on a2vm

| Test | Method | Pass |
| --- | --- | --- |
| Clock | The IRQ image with the music idle, 60 s of machine time, `--cost f121 --cost-timed` (PAL) and `f121+ntsc` | 34.9-35.0 tics a second; the tics equal the host model's fraction at every VBL |
| IRQ | `--irq-bounds`, `--ay-log`, `--lowest-s-in`; music alone, music and three effects, three effects started in one VBL; an effect held across `fx_song` (a song change), a tone effect started before any song (chip 3 at the reset's R7 0), `--phasor-mb-only` (no native mode) | bounds held; the worst length reported; stack ≤ 24 B; no chip-3 write while `FX_HOLD`, all of chip 3 written at the first burst after it; no write to VIA-B's second AY in Mockingboard mode |
| Input | a2vm input events (`key`, `hold`, `release`, `mouse`, `buttons`, `oa`, `ca` [R `tools/a2vm/README.md:355-369`]) at given VBLs, the test driver polling once a frame at 6, 10 and 35 frames a second | the event queue and `PL_MDX` equal `tools/native/plmodel.py`'s at every poll |
| Boot | `DOOM.hdv` under the MLI trap with `--amem`, `f121` and `fastpath` | every CRC equal, `PL_STATUS` ready, the card as the image, the clock running; boot time reported [M: part `plboot`: `f121` 5.84 s, `fastpath` 5.32 s of model time, 4.3 s of it the CRCs; the card's ProDOS read time is milestone 12's] |

## 7. Parts and waves

### 7.1 Rules

As GAME.md 2.5: a part owns its files alone; its callees are built by an
earlier wave or by itself; it never edits a shared file (it writes a
request into its own `docs/m11-parts/<part>.md`: what, why with the
evidence, and a marked local stand-in meanwhile); at most 3 parts a wave;
each about 1.5 hours [A]. Every part's sources are `src/native/s2_*.s`,
`s2t_*.s`, `pl_*.s`, `fx_*.s` or `src/sound/fx*.s` and
`src/sound/sounds.s`, its makefile fragment `src/native/m11/<part>.mk`
(included by `src/native/m11.mk`, part `s2lay`; the fragments of
`fxplay` and `fxdisk` assemble `src/sound/fx.s` and `sounds.s` into
their build directories and link S2's objects, which S2's own
`src/sound/Makefile` builds into `build/sound65/`, unchanged and read
only; `fxdisk` also owns `src/sound/sounds.cfg`), its tools
`tools/native/s2*.py`, `pl*.py`, `fx*.py` or `tools/sound/fx*.py`, its
scripts `coverage/m11/*.script` (`s2cap`), its build output `build/native/m11/<part>/`, its
test `tests/wip_test_m11_<part>.py` (run by name:
`python3 tools/testpar.py tests/wip_test_m11_<part>.py`), its notes
`docs/m11-parts/<part>.md`. Each test skips with a clear message without
`build/`, bounds its runs (`tests/support.run`, `bounded.py`) and deletes
its temporary directory. Each part delivers: its checkpoint passing, its
planted bugs caught (each in a scratch copy, as milestones 7-10 did), its
sizes against its budget, its timing (6.4).

### 7.2 Waves

| Wave | Parts | Why this order |
| ---: | --- | --- |
| 1 | `s2lay`, `fxconv` | `s2lay` is the shared infrastructure every other part builds on (the places, `s2.inc`, the makefile, the test driver, the runner and the checker); `fxconv` is host-only and needs nothing |
| 2 | `plclock`, `s2cap`, `s2draw` | each needs only `s2lay` |
| 3 | `fxplay`, `s2pal`, `s2data` | `fxplay` over `fxconv`'s scripts and `plclock`'s `pl_vbl`; `s2pal` over the drawers and the captures; `s2data` over the layouts |
| 4 | `s2stbar`, `s2hud`, `fxchan` | the per-frame screens over the drawers, palettes and store; the channel logic over `fxplay`'s mailboxes and `fx_isplaying` |
| 5 | `plinput`, `s2menu1`, `s2wi` | `plinput` over `plclock`; `s2menu1` over `fxchan` (the menu's sounds) and the drawers; `s2wi` over the drawers, palettes, store |
| 6 | `s2menu2`, `s2amap`, `s2fin` | `s2menu2` over `s2menu1` and `plinput`'s key names; `s2amap` and `s2fin` over the drawers and palettes |
| 7 | `s2ovl`, `fxdisk` | `s2ovl` over `s2amap`'s line code; `fxdisk` over `fxplay` and `fxconv` |
| 8 | `plboot` | over every image and bank file, all built by wave 7 |

Then the integration (section 8).

### 7.3 The parts

Upstream byte counts are of the routines named [M: modules §2, by file; the split between parts of one file is A]; budgets are upstream × 1.3 as GAME.md 2.4 [A] and enter 4.1's size table. Every part also follows 7.1.

#### Wave 1

**`s2lay` — the layouts, the makefile, the test driver, the runner, the checker.** Routines: none of upstream's. Files: `tools/native/s2layout.py` (every place of SCREENS.md 4.1-4.8: the images, their rooms and runtime ranges, the size table and its check against each image's ld65 map, the page-run packing into banks 107, 108, 94 and, since wave 1, 95-97; main `$03B3-$03ED`; zero page; the card blocks and their per-build addresses `S2T_BASE`, `SC_BASE` (4.4 "Test builds"), the mailbox and voice formats; the banks of 4.5; the cost phases 30 and 31; the field map of 6.2 for every screen of 1.6; `check()`), `src/native/m11.mk` and `src/native/m11/s2lay.mk` (targets `part P=`, `images`, `sizes`, the test images; each part's fragment `src/native/m11/<part>.mk` included when present), `src/native/s2_drv.s` (the test driver at card `$F900-$FEFF`, as `ldriver.s`: an image by `far_pload`, a list of routine calls, a mouse-card VBL with a counting stub handler when no `pl_vbl` is linked, the stops `S2S_*` at `PL_STATUS` `$03AE` then `BRK`), `tools/native/s2run.py` (a2vm runs built on `lrun.py`, imported: the poisoned machines `$A5`/`$5A`, the write log and its allowed sets, snapshots, `--cost f121`/`fastpath` with `--cost-timed` and phases 30/31, the AY log and `--irq-bounds` plumbing), `tools/native/s2check.py` (regions, exclusions X1-X4 counted and named, the publish-order check on the write log of 1.3, the report), the generated `build/native/m11/shared/gen/s2.inc`. Build: `build/native/m11/s2lay/` and `build/native/m11/shared/`. Test: `tests/wip_test_m11_s2lay.py`. Checkpoint: `check()` passes against `rlayout.py`, `llayout.py` and `glayout.py` (imported when it exists, read only; it does now: `GS_STATUS`, `GS_ARG` at `$03B0-$03B2` must not overlap the input block); every phase constant of the three layouts 0-31 and only the platform's 31; an empty routine list from both poisoned machines writes nothing outside the driver's set; `s2check` compares a hand-made case (region equal, every other byte its injected value or poison) and judges two hand-made write logs, one in upstream's publish order and one not; the size check rejects a synthetic map one byte over its room. Planted: two regions overlapping; a stored page run of two images overlapping in one bank; `s2check`'s region off by one row; the driver writing one byte of aux 0; the input block starting at `$03B0` (the `glayout` overlap); a phase constant 32; a write log with one band store before the last black palette store passing the order check. Budget: driver 600 B in `$F900-$FEFF`; 1.5 hours. Follows: 0, 4 (all), 6.2 (the field map), 6.3, 6.4, 7.1, 9 risk 12.

**`fxconv` — the effects converter (S4).** Routines: none of upstream's code; the `DS*` and `DP*` lumps of `DOOM1.WAD` and `sfxPriority`'s order [R `s_sound65.s:1274-1285`]. Files: `tools/sound/fxconv.py` (one script a game sound, the script format version 1, the ring quantization, the bank file `SFX.1` for bank 103 with its directory), `tools/sound/fxmodel.py` (the second, independent model: its own WAD and lump readers, no code shared with `fxconv.py` or `mus.py`), `tools/sound/fxdec.py` (the third, small script decoder), `tools/sound/fxtune.txt` (the ten tuned effects' first versions, written from the WAV renders), `src/native/m11/fxconv.mk`. Build: `build/native/m11/fxconv/` (`SFX.1`, the scripts' listing); WAV renders in `build/sound/fx/` by `ayrender.py` from the model's AY log. Test: `tests/wip_test_m11_fxconv.py`. Checkpoint: all 52 game sounds convert; every automatic script decoded by `fxdec.py` equals `fxmodel.py`'s per-tick state exactly; the ten tuned scripts equal their `fxtune.txt` rendering; every 42 ticks (300 ms) of every script within 128 bytes (the converter fails naming the effect otherwise); `SFX.1` fits one bank (48,640 B) and reads back equal; the WAV renders of all 52, tuned and automatic, for the owner; the PC speaker's divisor table checked against a published table named in the notes (if none is available offline, the reconstruction stays labelled [A] and the open problem says so). Planted: the `DP` pitch table a quarter tone off; the level from the `DS` tick's peak instead of its RMS; the noise threshold inverted; a run length counted from 0 instead of 1; a tuned entry ignored. Budget: `SFX.1` about 15 KB, at most one bank; 1.5 hours. Follows: tools/sound/README.md "Effects (S4)": "Sources", "The converter", "The ten tuned effects"; SCREENS.md 3, 4.5.

#### Wave 2

**`plclock` — the IRQ entry, the clock, the bridge.** Routines: `kstart.s`'s IRQ and crash parts [R `demos/doom/src/kernel/kstart.s:197-285`], the mouse card's VBL [R `demos/doom/src/kernel/input.s:102-136`], `I_GetTime`, `MUSIC.SYSTEM`'s PAL/NTSC detection [R `tools/sound/README.md:395-405`]. Files: `src/native/pl_irq.s` (`pl_vbl` with SCREENS.md 2.3's seven steps, the clock, `pl_time`, the PAL/NTSC detection, the crash stop), `src/native/pl_fxstub.s` (marked stand-ins `fx_step`, `fx_burst` that do nothing, test images only, until `fxplay`; replaced by `fx.s`'s card part and deleted at the final integration, 8.13), `src/native/pl_bridge.s`, `tools/native/plclock.py` (the host model of the fraction), `src/native/m11/plclock.mk`. Build: `build/native/m11/plclock/`. Test: `tests/wip_test_m11_plclock.py`. Checkpoint: SCREENS.md 6.5's clock row: 60 s of machine time PAL (`--cost f121 --cost-timed`) and NTSC (`f121+ntsc`), 34.9-35.0 tics a second, the tics equal the model at every VBL; the IRQ row with music alone: `--irq-bounds 00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`, stack at most 24 B (`--lowest-s-in`), the worst length reported; music through `pl_vbl` (S2's objects from `build/sound65/`, read only) gives S2's AY log byte for byte for 20 s of each of the 13 songs; `tests/test_sound_*` unchanged and green; the bridge on a synthetic image whose aux card holds only the bridge and whose main loop runs with `ALTZP` on. Planted: the PAL fraction 45,742; the NTSC fraction for PAL; a tic lost at the fraction's carry; the VBL cause not checked (a second entry counts twice); the handler reading main `$0300`. Budget: 150 B in the card (`pl_vbl`, the clock, `pl_time`), the bridge in `$FF00-$FFF9`; 1.5 hours. Follows: 2.2, 2.3, 4.4, 6.5.

**`s2cap` — captures, scripts, injection.** Routines: none to port: ref816 captures of upstream. Files: `tools/native/s2cap.py` (the points of 6.1, streamed through a pipe and distilled into cases as they come; the raw stream never kept), `tools/native/s2state.py` (injection of 6.2, both fills and the poisoned marked bytes; the //e key names and table poked into ref816 1:1), `coverage/m11/menus.script`, `automap.script`, `palette.script`, `finale.script`, `signs.script`, `stbar.script`, `src/native/m11/s2cap.mk`. Build: `build/native/m11/cases/` (the cases, zlib'd) and `build/native/m11/s2cap/`. Test: `tests/wip_test_m11_s2cap.py`. Checkpoint: every run of 6.1 (demo3, newgame, tour, DEMO1, DEMO2 and the six scripts) captured twice with the same cases, 0 decode problems; `PV` captured in every level frame; `S_UpdateSounds` logged once in every frame where the player has a mobj (`jumps=1`), with `isPlaying`, `docVolume` and `stopChannel`; each case injected and read back equal; a sample of `PD1` screens equal to the two-run method's (a run to the same cycle count with `--save`); the scripts reach every page, mode, message and status-bar value class they name (checked on the captured state); `df -h /System/Volumes/Data` before the first capture; all cases under 60 MB. Planted: `PD1` at `I_FinishUpdate`'s entry instead of its return (the two-run check fails); a word field injected as a byte; the poison not covering a marked byte; `S_UpdateSounds` logged without `jumps=1` (its per-frame count check fails). Budget: each capture run at most 25 minutes and 200 MB of pipe traffic under `bounded.run`, at most 4 at once; cases under 60 MB; 1.5 hours. Follows: 1.6, 6.1, 6.2, appendix A.

**`s2draw` — the drawers and the publish.** Routines: `IIGS_DrawPatch`, `markPatch`, `capPost` [R `patch65.s:46-276`], `V_DrawPatchNotScaled`, `V_DrawRaw`, `drawRawData`, `pairByte`, `drawPicture` (the pixels), `V_DrawBackground`, `markRect`, `markRows`, `showDirty`, `rectOffset`, `copyToBuffer`, `I_RestoreStatusRect`'s copy [R `i_viigs65.s:407-498`, `:1226-1521`, `:1624-1762`]. Files: `src/native/s2_draw.s` (the shared object `s2_draw`: the patch drawer into a band with a row window, raw, background, the marks), `src/native/s2_pub.s` (the shared object `s2_pub`: `s2_publish` with its call of `s2_begin` before the frame's first band; separate so `AMAPW` links it alone), `src/native/s2_beginstub.s` (a marked test-only `s2_begin` stand-in that writes a recognizable SCB pattern, until `s2pal`; at the final integration `s2sb` and `s2ht` link `s2_pal.o`, and it stays `s2dt`'s and `s2pt`'s test double, 8.13), `tools/native/s2draw.py` (the host model of the nibble rule), `src/native/m11/s2draw.mk`. Build: `build/native/m11/s2draw/`. Test: `tests/wip_test_m11_s2draw.py`. Checkpoint: truth from `ref816 --call` of `IIGS_DrawPatch`, `V_DrawRaw`, `V_DrawBackground` on the release image with the patch, the position and the tables poked (every status bar, menu, intermission and font patch at four positions with both x parities, clipped at each edge) and from captured calls (`--capture`): every call's band bytes and marks equal; publish of random marks equals a host copy with 0 stray writes and `s2_begin` before the first band; the capture record of a text equals upstream's `CAPVAL`/`CAPMSK`. Planted: the odd pixel's mask `$F0` for `$0F`; the post's row page off by one row (parity); the clip at x = 320 not taken; `pairByte`'s right table at `+$100`; publish ending a byte early; publish not calling `s2_begin` before the first band. Budget: 1.2 KB; 1.5 hours. Report µs a patch pixel and µs a published byte (f121, fastpath). Follows: 1.2, 1.4, 4.1 (size table), 6.3.

#### Wave 3

**`fxplay` — the effect player.** Routines: none of upstream's (the DOC is dropped); S2's burst loop and addressing as the model [R `src/sound/player.s`]. Files: `src/sound/fx.s` (`fx_step`, `fx_burst`, `fx_service`, `fx_init`, `fx_stopall`, `fx_song`, `fx_isplaying`: a channel plays when its voice is active or its mailbox holds a start), `tools/sound/fxplay.py` (the specification and the oracle, as `player.py` is the music's: steps, voices, mailboxes, the stereo rule, `FX_ON`, `FX_HOLD`, `FX_INVAL`), `tools/sound/fxrun65.py` (a2vm runs), `src/native/m11/fxplay.mk` (assembles `fx.s`, links S2's objects from `build/sound65/` read only and `plclock`'s `pl_irq.s`). Build: `build/native/m11/fxplay/`. Test: `tests/wip_test_m11_fxplay.py`. Checkpoint: every effect alone, PAL and NTSC, three distances, each voice: the AY log equals `fxplay.py`'s at every interrupt; each effect over each of the 13 songs (20 s, starts at demo3's measured times): chips 0-2 equal S2's log of the song alone, chip 3 the model's; no effect: the whole AY log equals S2's byte for byte; ring underrun silences the voice and holds; the IRQ bounds; an effect held across `fx_song` (no chip-3 write while `FX_HOLD`, all of chip 3 at the next burst); a tone effect before any song (chip 3 at the reset's R7 0) written whole; `--phasor-mb-only`: no chip-3 write at all; the stereo rule at separation 127, 128, 129 and with each voice busy; the mailboxes' rules (a start then a stop in one frame: no voice; a stop then a start: the new sound; a start then a volume: the new volume). Planted: chip 3's burst before the music's; the noise period of the last voice instead of the loudest; a ring refill published before its bytes; the side choice inverted; the distance attenuation added twice; `FX_INVAL` ignored (the shadow kept across a song start); separation 128 to voice B; `fx_isplaying` ignoring a pending start. Budget: 620 B and `VATT` 128 B in the card `$F505-$F8FF` (with `pl_vbl`), `fx_service` 400 B (W); 1.5 hours. Report the cost a second with 1 and 3 effects (window 512, 32, FW-S1) and the extra slowdown tail an interrupt with effects pays. Follows: 2.3, 3, 4.4; tools/sound/README.md "Effects (S4)": "The player", "Stereo by voice", "Volume", "Memory", "Cost".

**`s2pal` — palettes, tints, gamma, SCBs, the finish, the wipe, PALW.** Routines: `I_SetPalette`, `I_ReloadPalette`, `I_FinishUpdate`/`D_Wipe` without `showDirty`, `I_ApplyColors`, `newColors`, `pictureColors`, `I_ViewPalette`, `I_MessageStrip`, `gammaColor`, `buildTints`, `levelPalettes`, `tintRecords`, `tintColors`, `buildNibtab`, `setRows`, `rowPalette` [R `i_viigs65.s:303-405`, `:500-787`, `:1006-1200`], `ST_doPaletteStuff` [R `st_stuff65.s:1099-1171`], `stripEarly`'s palette [R `d_main65.s:764-778`]. Files: `src/native/s2_pal.s` (the shared object `s2_pal`: `s2_begin`, `s2_finish`, `newColors`, `pictureColors`, `ST_doPaletteStuff`, `I_ViewPalette`, `I_MessageStrip`, `setRows` and `rowPalette`'s SCB), `src/native/s2_nib.s` (the shared object `s2_nib`: the nibble tables, `gammaColor`, a picture's palettes; wave 3, S2PAL-7), `src/native/s2_palw.s` (the image `PALW`: `TINTPAL` and the 16 nibble tables built into `S2PAL`), `src/native/m11/s2pal.mk`. Build: `build/native/m11/s2pal/`. Test: `tests/wip_test_m11_s2pal.py`. Checkpoint: every frame of demo3, newgame, tour, `palette.script`: SCBs and palettes after `I_FinishUpdate` equal; the wipe's two steps (`PW`, `PD1`) on every new picture; the publish order on every frame's write log (1.3); `TINTPAL` (14 × 384 B) and the 16 nibble tables equal ref816's after each level load, gamma change and picture. Planted: gamma applied twice; the tint row of `newpal - 1`; the black step skipped; the black palettes after the first band (the order check fails though both snapshots pass); a radiation suit blink on bit 3 of the wrong byte; the strip's palette not restored; `TINT_ROW` 512 instead of 384. Budget: `s2_pal` 800 B, `s2_nib` 400 B, `PALW` 1.5 KB; 1.5 hours. Follows: 1.3, 1.5.7, 1.5.8, 4.1, 6.3.

**`s2data` — the 2D store.** Routines: none: data. Files: `tools/native/s2data.py` (patches, `STBAR`, `FLOOR4_8` from `DOOM1.WAD` by our own code, checked equal to the release's lumps; `TITLEPIC`, `HELP2`, `WIMAP0`, `GSSTAT`, `GSOVL` from the release through `umodel.Release`, read only; the handles table; the bank files `GFX.n` at `s2layout`'s places), `src/native/m11/s2data.mk`. Build: `build/native/m11/s2data/`. Test: `tests/wip_test_m11_s2data.py`. Checkpoint: every lump equal to the release's or taken from it; the store fits its banks (bytes a bank reported against 4.5); a read-back of every lump from the bank files equals its source. Planted: a patch's column offsets little-endian swapped; a lump placed across a bank end; a picture's palettes from the wrong record. Budget: the store in `GFX0`-`GFX3` and the free parts of 103-108 (bank 125 next if it does not fit, reported); 1.5 hours. Follows: 0.1 F5, 4.5, 9 risks 3-4.

#### Wave 4

**`s2stbar` — the status bar and the face.** Routines: SCREENS.md 1.5.1's table but `ST_doPaletteStuff`: `ST_Init`, `ST_Start` (`ST_initData`, `ST_createWidgets`), `ST_Ticker` but `M_Random` (`readyNum`, `keyboxes`, `updateFace`, `painOffset`, `turnHead`, `st_oldhealth`), `ST_Drawer` (`refresh`, `diffDraw`, `diffNum`, `diffIcon`, `restoreRect`, `updateIcon`, `drawNum`, `stHide`), `I_SaveStatusBackground` [R `st_stuff65.s:127-1000`, `:1173-1210`; `i_viigs65.s:1357-1367`]. Files: `src/native/s2_st.s` (in `P2DW`), `src/native/s2t_st.s` (tic-side: `st_ticker` with A = `M_Random`'s value, `st_start`), `src/native/m11/s2stbar.mk`. Build: `build/native/m11/s2stbar/`. Test: `tests/wip_test_m11_s2stbar.py`. Checkpoint: every frame of demo3, newgame, tour and `stbar.script` injected (both fills and the poisoned marked bytes), rows 168-199 equal; chained over demo3's 533 frames; the coverage table, each widget × each glyph and place drawn at least once and equal (a glyph never drawn fails); `st_ticker` on every tic of demo3 and newgame equal to `ST_Ticker`'s state after it (the random value given); the menu's `stHide`; the nibble-table fetches a frame reported. Planted: `painOffset`'s cache not refreshed; the evil grin on any weapon change; the turned head's sides swapped; `diffNum` restoring the old width; `drawNum` of `LARGEAMMO`; the ammo rows in `ammoRows`' wrong order. Budget: 2.9 KB (`P2DW` 2 KB, tic-side 900 B); 1.5 hours. Report ms a frame with nothing changed, the face changed, a full refresh. Follows: 1.4, 1.5.1, 1.6, 4.1, 4.4, 4.7, 6.

**`s2hud` — the HUD, its ticker and its cached drawer.** Routines: `HU_Init`, `HU_Start`, `HU_Drawer`, `drawTextLine`, `HU_Ticker` but `player.message`'s and `G_MSGKEEP`'s clears [R `hu_stuff65.s:70-276`]; the text cache (`I_DrawCachedText`, `I_EndTextCapture`, `textInvalidate` [R `i_viigs65.s:1784-1897`]) as data; `I_MessageStrip`'s clear. Files: `src/native/s2_hu.s` (in `P2DW`), `src/native/s2t_hu.s` (tic-side: `hu_ticker`, `hu_start`, their state in the card), the message-id text table's generator `tools/native/s2msgs.py`, `src/native/m11/s2hud.mk`. Build: `build/native/m11/s2hud/`. Test: `tests/wip_test_m11_s2hud.py`. Checkpoint: every frame of demo3, newgame, `menus.script` (messages), `automap.script` (the title): strip rows and title rows equal; the cache replay equal to a fresh draw on every cached frame; `hu_ticker` on every tic equal to `HU_Ticker`'s counter, `message_on`, `message_new` and the line; in every level frame, `message_on` after the frame's tics equal to the reference's at point `PV`, and request R7's rule (`VIEWTOP` 9 when `message_on` is set and the menu does not pause the view, else `$FFFF`) applied to it equal to the reference's `viewtop`; rows 0-9 never written when the strip is off. Planted: the replay not marking its rows; lower case not mapped; the space width 3; the line cut at 319; `message_on` cleared a tic late; the counter tested after the take instead of before (a new message dies at once when the old counter reaches 1); `hu_ticker` reading `player.message` after `hu_tick`'s clear. Budget: 850 B (`P2DW` 700 B, tic-side 150 B); 1.5 hours. Follows: 0.1 F8, 1.4, 1.5.2, 1.6, 4.4, 4.7, 6.3 X1.

**`fxchan` — the channel logic.** Routines: `S_StartSound`, `S_StartSound2`, `sameOrigin`, `getChannel`, `priority`, `stopChannel`, `S_StopSound`, `S_UpdateSounds`, `adjustParams`, `units`, `mulLong`, `divAtt`, `absDelta` [R `s_sound65.s:177-670`], `sfxPriority` [R `:1274-1285`]. Files: `src/native/fx_chan.s` (`sc_start`, `sc_start2`, `sc_stop`, `sc_update`; every decision into its channel's mailbox; `isPlaying` through `fxplay`'s `fx_isplaying`), `src/native/fx_pcache.s` (`MENUW`'s position callback from the channel table's last positions), `tools/native/fxcap.py` (the cases from `s2cap`'s sound points and the `ref816 --call` eviction cases), `tools/sound/fxchan.py` (the host model, with its own priority table read from upstream's `sfxPriority`), `src/native/m11/fxchan.mk` (the builds: 3 channels, `FXCH8`, the `MENUW` linkage). Build: `build/native/m11/fxchan/`. Test: `tests/wip_test_m11_fxchan.py`. Checkpoint: SCREENS.md 3's comparison 1-4 in `FXCH8`: every captured start and stop, every `S_UpdateSounds` with the reference's `isPlaying` injected, the synthetic eviction cases with a path-coverage report (a path of `S_StartSound` or `getChannel` with no compared call fails), the two-tic case (a start and the frame's `sc_update`); the 3-channel build equal to `fxchan.py` on the same cases and on 10,000 random call sequences; the `MENUW` linkage: a paused frame's `sc_update` after the menu changes `snd_SfxVolume` equal to the reference's. Planted: the separation's "less 1" not taken; map 8's floor of 15 dropped; priority compared with `>`; the pickup flag ignored in `sameOrigin`'s kill; `S_StartSound2` with its own origin instead of `FM`; `isPlaying` without the pending start; a stop that leaves the mailbox's start set. Budget: 700 B, `fx_pcache` 60 B (since wave 4, FXCHAN-5: 1,100 B, `fx_pcache` 90 B); 1.5 hours. Report µs a call. Follows: 0.1 F3, F4, F11; 3; 4.4; 4.7; tools/sound/README.md "The game side".

#### Wave 5

**`plinput` — input.** Routines: `I_InitKeyboard`, `I_StartTic`, `repeatStart`, `repeat`, `I_BindKey`, `I_DefaultKeys`, `recount`, `I_ActionKeys`, `postKey` [R `i_iigs65.s:676-1000`]; the mouse of `iigs_asm.s` [R `:64-160`] replaced by the mouse card [R `demos/doom/src/kernel/input.s:102-256`]. Files: `src/native/pl_input.s` (the shared object `pl_poll`), `src/native/pl_keys.s` (the boot's and the key setup's routines: `pl_init`, `pl_defaults`, `pl_bind`, `pl_action`; wave 5, PLINPUT-5), `tools/native/plmodel.py`, `tools/native/plkeys.py` (generates the //e key table, 128 entries, and the names, at most 7 characters and a 0, as `build/native/m11/plinput/gen/plkeys.inc` for the menus), `src/native/m11/plinput.mk`. Build: `build/native/m11/plinput/`. Test: `tests/wip_test_m11_plinput.py`. Checkpoint: 6.5's input row over at least 40 scripted sequences (taps, holds, the //e's auto-repeat, two keys overlapping, a tap between polls, the Apple keys, the mouse moving, re-centring, both buttons, the menu's arrow repeat, a rebinding, lower-case keys, a nearly full queue deferring a key), polling at 6, 10 and 35 frames a second: the queue and `PL_MDX` equal `plmodel.py`'s at every poll; the state only in `$03B3-$03ED`. Planted: the auto-repeat posting a key down; the held key not going up when another comes; the tap's up in the same poll; the mouse's sequence byte not re-read; the counts not shared by two keys of one Doom key; a lower-case code not folded (typing `p` fires mouse 2); a full queue dropping a key instead of deferring it. Budget: 600 B; 1.5 hours. Follows: 1.5.3 (the //e keys), 2.1, 2.4, 4.2, 6.5.

**`s2menu1` — the menu engine and the main pages.** Routines: `M_Init`, `M_StartControlPanel`, `M_DrawVersion`, `M_SkullVersion`, `M_Ticker`, `M_Responder` and its handlers (its sounds through `sc_start`), `clearMenus`, `setupMenu`, `startMessage`, the main, new game, skill and options pages, `M_Drawer`, `menu`, `M_DrawSkull`, `skullPlace`, `M_SkullRect`, `drawMessage`, `lineWidth`, `writeLine` [R `m_menu65.s:518-1593`]; the settings pages' frame (`uiSettings`, `uiAlign`, `uiCenter`, `bmWrite`, `bmBox`, `bmFontShade`), which every page's skull goes through (as built, wave 5: S2MENU1-3); the menu's video (`I_MenuPalette`, `uiGrayTables`, `grayMap`, `uiDimAll`, `uiDimRect`, `uiFontNibbles`, `I_MenuPaletteBack`, `I_RestoreBackRect` [R `i_viigs65.s:877-957`, `:1556-1622`, `:2030-2402`]); the static screen [R `d_main65.s:561-624`]; the paused frame's `sc_update` call. Files: `src/native/s2_menu.s`, `src/native/s2_mvid.s`, `src/native/m11/s2menu1.mk` (the `MENUW` image with the shared objects of 4.1's size table). Build: `build/native/m11/s2menu1/`. Test: `tests/wip_test_m11_s2menu1.py`. Checkpoint: every frame of `menus.script`'s main, new game, skill, options pages and messages, from the title and over the view: the whole screen (pixels, SCBs, palettes) equal; the close restores the screen byte for byte; the action requests made; the menu's sounds' `sc_start` calls equal the reference's `S_StartSound` calls; `MENUW` within its room. Planted: the gray of the right nibble from the left; the skull's old rectangle not restored; the save request with a wrong length; the menu palette's reds from the wrong colours; a menu sound not started. Budget: 5 KB; 1.5 hours. Report the open and close times (the 32 KB save, gray conversion and restore). Follows: 1.2, 1.5.3, 2.1, 3, 4.1, 6.

**`s2wi` — the intermission.** Routines: `WI_Drawer`, `drawStats`, `drawShowNextLoc`, `drawAtNode`, `slamBackground`, `drawCenteredPatch`, `drawPercent`, `drawNum`, `drawTime`, `WI_Init`'s lumps [R `wi_stuff65.s:96-200`, `:586-903`]. Files: `src/native/s2_wi.s`, `src/native/m11/s2wi.mk` (the `WIW` image). Build: `build/native/m11/s2wi/`. Test: `tests/wip_test_m11_s2wi.py`. Checkpoint: every intermission frame of the tour (eight intermissions, both states: the stats with every count step, the next location with the blinking pointer) equal over the whole screen; the `wi` state read through milestone 10's generated include, or a marked local stand-in listed in the notes until it exists; `WIW` within its room. Planted: `drawTime` without the first colon; the splats drawn to `last` instead of `next - 1` after the secret level [R `wi_stuff65.s:598-605`]; the "you are here" node not lowered to 45; the percent sign of a negative count. Budget: 1.4 KB; 1.5 hours. Follows: 1.5.5, 1.5.7, 4.1, 6.

#### Wave 6

**`s2menu2` — the settings pages, the key setup, the slots, the signs' font.** Routines: the display and sound, controls, input, key setup pages (`drawControls`, `keyName`, `thermo`, `onOff`, `uiVolume`, `uiViewIndex` with the full view only: the values past ON/OFF; `uiSettings`, `uiCenter`, `uiAlign` are `s2menu1`'s since wave 5, S2MENU1-3), drawn through `s2menu1`'s hooks `m2_page`, `m2_value`, `m2_bench` (S2MENU1-5), the load and save pages (`drawSlots`, without the I/O), the benchmark's two rows, the busy sign's text font (`bmGlyph`, `bmPut`) [R `m_menu65.s:1192-1600`, `:1959-2100`, `:2672-3139`]. As built (wave 6, S2MENU2-5): `m2_page` (`drawLoad`, `drawSave` with their slots, `drawControls` with `keyName` over `plinput`'s `pl_action` and `plk_names`), `m2_value` (VIEW's "FULL", the thermometers of gamma, the effects' and the music's volume and the mouse speed), `m2_bench` (the result's title, VIEW and FPS rows; X2 black); the sign's font it also built went at the integration (part `s2fin` draws the sign by columns with its own: S2MENU2-4 with S2FIN-8). Files: `src/native/s2_menu2.s`, `src/native/m11/s2menu2.mk`, `tools/native/s2menu2.py` (the test glue is `s2menu1`'s `s2_menut.s`, one `MENUW`: S2MENU2-3). Build: `build/native/m11/s2menu2/`. Test: `tests/wip_test_m11_s2menu2.py`. Checkpoint: every remaining page and cursor of `menus.script` equal (the //e names and table from `plinput`'s `plkeys.inc` poked 1:1 into ref816's `keyNames` and `keyTable`, 6.2); X2; `MENUW` with both menu parts within its room. Planted: a thermometer's dot one step off; the key setup's second key from the wrong range order; the view size not limited to full; a key name written without its 0. Budget: 4 KB; 1.5 hours. Follows: 1.5.3, 4.1, 6.2, 6.3.

**`s2amap` — the automap, full mode.** Routines: 1.5.4's full mode, `AM_Start`, `AM_Stop`, `AM_Responder`, `AM_Ticker`, the window, scale and follow routines, the walls, the players' arrows, the clipping and the line loops [R `am_map65.s:228-1100`, `:1180-1219`, `:1639-2980`]. Files: `src/native/s2_am.s`, `src/native/s2_amline.s` (the transform, the clip and the line loops, shared with `s2ovl`), `src/native/m11/s2amap.mk` (the `AMAPW` image). Build: `build/native/m11/s2amap/`. Test: `tests/wip_test_m11_s2amap.py`. Checkpoint: every full-map frame of `automap.script` equal (the view rows); chained over the script; `AM_Responder`'s state after each key equal; `AMAPW` within its room and without `pl_poll` or `fx_service` (`P2DW` follows it, 1.5.4). Planted: the y-major loop's step on the wrong axis; the clip's outcode bits swapped; the follow mode not recentring; the zoom applied once a frame instead of once a tic. Budget: 7 KB; 1.5 hours. Follows: 1.5.4, 4.1, 6.

**`s2fin` — the finale, the pages, the loading screen, the busy sign.** Routines: `F_StartFinale`, `F_Ticker`, `F_Drawer`, `F_TextWrite`, `textSpeed` [R `f_finale65.s:60-277`], `F_LoadScreen` [R `:279-284`], `D_PageDrawer`'s `V_DrawRawFullScreen` [R `d_main65.s:417-422`], `bmSignOn`, `bmSignOff`, `bmSignBox`, `bmSignPatch` [R `m_menu65.s:1799-1990`]. Files: `src/native/s2_fin.s` (`FINW`), `src/native/s2t_fin.s` (tic-side `f_ticker`, `f_start`), `src/native/m11/s2fin.mk`. Build: `build/native/m11/s2fin/`. Test: `tests/wip_test_m11_s2fin.py`. Checkpoint: every frame of `finale.script` and `signs.script` and the title page of demo3's run equal, with the wipe's order on the write log; X3 counted; `f_ticker` on every finale tic equal; `FINW` within its room. Planted: the text speed's mid stage ignored; the new line 11 rows down off by one; the sign's rows not put back. Budget: 1.6 KB, tic-side 250 B; 1.5 hours. Follows: 1.5.6, 1.5.7, 1.5.8, 4.1, 4.7, 6.

#### Wave 7

**`s2ovl` — the automap's overlay records and OVLW.** Routines: 1.5.4's overlay: `ovl` with `FSCUTE` [R `am_map65.s:1461-1509`; `lists.inc:90-106`], `titleBand`, `drawLines` in overlay mode. Files: `src/native/s2_ovl.s`, `src/native/s2_ovd.s` (the test driver), `tools/native/s2ovl.py`, `src/native/m11/s2ovl.mk` (links `OVLW` from `s2_ovl.o`, `s2_amline.o` and milestone 8's `rrec.s` and `bucket.s` objects with `BKFAR`/`BKFAR2` as data, read only, in `$6800-$9BFF`; the test image runs milestone 8's whole frame with `rdriver.s`). Build: `build/native/m11/s2ovl/`. Test: `tests/wip_test_m11_s2ovl.py`. Checkpoint: every overlay frame of `automap.script`: the record stream (the view's records then the `K_OVL` ones, by column, milestone 8's comparison) equal, the fill spans' ends equal, and the screen after the replay equal to `R_DrawLists`' return (P5: `PD1`'s view rows, which part s2cap's cases do not keep, X1), the title band black when `titleBand` runs; frames without the overlay unchanged; `OVLW` within `$6800-$9BFF` and milestone 8's other W ranges untouched. Planted: the kept nibble `$F0` for an even x; `FSCUTE`'s end row not `+ 1`; the records before the view's last batch; `nm_bkload` copying `BKFAR` from `MASKW`'s address instead of `OVLW`'s. Budget: `s2_ovl` 4.5 KB, `OVLW` at most 13,312 B; 1.5 hours. Report the replay's ms with the overlay's records and `OVLW`'s load. Follows: 0.1 F9, 1.5.4, 4.1, 4.5.

**`fxdisk` — SOUNDS.hdv.** Routines: none of upstream's. Files: `src/sound/sounds.s` (`SOUNDS.SYSTEM`), `src/sound/sounds.cfg`, `tools/sound/fxdisk.py`, `src/native/m11/fxdisk.mk` (assembles `sounds.s`, links S2's objects and `fx.s`, `pl_irq.s`). Build: `build/native/m11/fxdisk/`; the disk `build/sound/SOUNDS.hdv`. Test: `tests/wip_test_m11_fxdisk.py`. Checkpoint: the disk boots on a2vm (MLI trap); each effect by key gives `fxplay.py`'s AY log, left and right voices, tuned and automatic versions, with and without music; with `--phasor-mb-only` it says there are no effects and writes no AY register; quit as `MUSIC.SYSTEM`. Planted: a key playing the next effect; the side keys swapped; the tuned version not loaded; effects played without native mode. Budget: 1.5 hours. Follows: tools/sound/README.md "The test disk SOUNDS.hdv", "Tests"; SCREENS.md 3.

#### Wave 8

**`plboot` — DOOM.SYSTEM and DOOM.hdv.** Routines: `demos/doom/src/kernel/loader.s`'s bank files [R `:36-45`] and `LEVELS.SYSTEM`'s boot as the model (`src/native/lboot.s`, read only). Files: `src/native/pl_boot.s`, `tools/native/pldisk.py`, `src/native/m11/plboot.mk`. Build: `build/native/m11/plboot/`; `DOOM.hdv` there. Test: `tests/wip_test_m11_plboot.py`. Checkpoint: 6.5's boot row (`DOOM.hdv` under the MLI trap with `--amem`, `f121` and `fastpath`: every CRC equal, `PL_STATUS` ready, the card as the image, the clock running, boot time reported); no mouse card, too few banks, no memory API each stop with its message; no music goes on with its message and the effects off. Planted: a segment into the next bank; the CRC table one entry short; ProDOS's card not overwritten (the ready check fails); the pair not zeroed; `fx_init` called before `snd_probe`'s answer. Budget: 2 KB (boot code, discarded); 1.5 hours. Follows: 2.5, 4.5, 6.5.


## 8. Integration and acceptance

### 8.1 The integrator

After each wave (about 30 minutes [A]): applies the wave's requests to
`s2layout.py` and the makefile (never to milestone 10's files: those go
to its integrator through `docs/m11-parts/design.md`), rebuilds the
images, checks 4.1's size table on the linked images, reruns every
built part's checkpoint, and records "Wave N as integrated" here. After
wave 8 it runs the acceptance (8.2).

### 8.2 The acceptance runs (this half)

| # | Run | Checks |
| --: | --- | --- |
| 1 | Every 2D part's checkpoint, both fills and the poisoned marked bytes; the chained runs of 6.3 | Every region equal, every exclusion named and counted; the publish order on every write log; the native `VIEWTOP` equal to the reference's `viewtop` in every level frame |
| 2 | 6.5's clock and IRQ rows | 34.9-35.0 tics a second PAL and NTSC; the IRQ's worst length reported |
| 3 | 6.5's input row | every sequence's events equal |
| 4 | `DOOM.hdv` on a2vm, `f121` and `fastpath` | every CRC, the ready state |
| 5 | `fxconv`, `fxplay`, `fxchan`'s checkpoints | as there, including the effect held across a song start, `--phasor-mb-only`, `S_UpdateSounds` and the eviction paths |
| 6 | `SOUNDS.hdv` on a2vm | `fxdisk`'s checkpoint; the disk is in `build/sound/` for the owner |

Then the wip tests are renamed `tests/test_m11_<part>.py`, and the full
suite runs: `python3 tools/testpar.py` with every module but milestone
10's `test_native_game_*`, plus the renamed ones.

### 8.3 The report (`build/native/m11/report.md`)

1. For each 2D part, a2vm time a frame (median, p99, worst; `f121` and
   `fastpath`), the image's load and the publish's drain apart; for the
   tic-side modules, µs a call.
2. The IRQ: ms a second for music alone, music with effects at demo3's
   measured start rate, and the worst case of three effects; with the
   default window 512, the Doom profile's 32 and FW-S1 (as S2's table);
   the worst interrupt's length.
3. Sizes against the budgets, the card's fill, the banks against 4.5.
4. The exclusions by name and count.

**Levers, measured before any is taken:** L1, `P2DW`'s load (2.0 ms a
frame [A]): load only the pages a frame uses; L2, pre-rendered status
bar glyphs (1.4); L3, the overlay's `K_OVL` records queued as the fuzz
records are [R `src/native/README.md:400-405`] (measured by part s2ovl:
the replay of an overlay frame with the computer map, 1,689-2,489 `K_OVL`
records, is 93.8 ms `f121` median against 40.0 ms without the overlay,
41.3 against 37.7 `fastpath`: each record's `RAMRD` window waits for the
drain); L4, the effect rings
refilled at the tic phase's start too (request to milestone 10); L5,
`s2_begin`'s colours between the bucket pass and the replay, as upstream
applies them before `R_DrawLists` (D1, 1.3; a request to milestone 8's
integrator), if the owner sees the strip's colours late.

### 8.4 The documents this half updates

| Document | Change | By |
| --- | --- | --- |
| This file | "Wave N as integrated", "Acceptance", corrections marked in the text | integrator |
| `tools/sound/README.md` | "Effects (S4)": results, sizes, the owner's tuning notes later | `fxconv`, `fxplay`, `fxdisk`, integrator |
| `MEMORY_MAP.md` | requests R2, R3 (section 18) | milestone 10's or the final integrator |
| `NATIVE.md` | request R1 | same |
| `LEVELS.md` | request R9 (1.7's `TABLES.n` as built; wave 8, PLBOOT-8) | the final integrator |
| `src/native/README.md` | "The 2D screens and the platform (milestone 11, first half)": commands, files, results | integrator |
| `MILESTONES.md` | row 11's first half, S4 | integrator |

### 8.5 Wave 1 as integrated (2026-10-01)

Parts `s2lay` and `fxconv` (their notes: `docs/m11-parts/s2lay.md`,
`fxconv.md`, each with a section on the integration). The requests:

| Request | Outcome |
| --- | --- |
| S2LAY-1 (code banks) | Applied, the part's option (a): `WIW`, `FINW`, `PALW` in banks 95, 96, 97 (`S2CODE3`-`S2CODE5`), one image a bank; 4.1 *Packing*, 4.5, risk 3 changed. Option (b), linking three images at the top of W, was not taken: it moves three rooms and their runtime ranges and `FINW` still needs a bank of its own. The spare left after milestones 9-11: 1-3, 125, 126 |
| S2LAY-2 (state blocks) | Applied: 4.6 |
| S2LAY-3 (input block) | Applied: `$03B3-$03ED`, `GS_ARG` a word (2.4, 4.2, 5, 7.3, `design.md` R3) |
| S2LAY-4, R-FX3 (`testpar.py`) | Applied: a named `tests/wip_test_*.py` runs (`tools/testpar.py`, `tests/README.md`, a test in `test_testpar.py`); the canonical command and a run without names still leave it out |
| S2LAY-5 (`MEMORY_MAP.md` 18) | Recorded in `design.md` R2 item 4; `MEMORY_MAP.md` and `NATIVE.md` (R1-R3) stay for milestone 10's or the final integrator (8.4) |
| R-FX1 | Applied: `tools/sound/README.md` "Effects (S4)" |
| R-FX2 | Applied: 4.5 row 103 |
| R-FX4 | Applied: `make -f m11.mk` also makes `SFX.1` (`M11_HOST`); `part P=fxconv` builds the part |

The checkpoints, rerun together after the changes (from `demos/doom_gs`):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check` (also `make -C src/native -f m11.mk check`) | passes, against `rlayout`, `llayout` and `glayout` as they stand today |
| `make -C src/native -f m11.mk` (images and `SFX.1`), `part P=s2lay`, `part P=fxconv` | no warning, no error |
| `make -C src/native -f m11.mk sizes` | `s2lt` 24 of 7,424 B in `P2DW`'s room |
| `python3 tools/native/s2layout.py --report` | packing P2DW 107, MENUW 108, AMAPW 94, WIW 95, FINW 96, PALW 97, OVLW 93; card block 59 of 61 B, channels 48 of 64 B; phases written 0-18 and 30, none unread |
| `python3 tools/native/s2run.py --profile f121` / `fastpath` / `--fill 5a` | stop `$81`, 0 stray writes; the load 0.459 ms `f121`, 0.425 ms `fastpath` |
| `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | up to date: `SFX.1` 11,385 B, 62 renders in `build/sound/fx/` |
| `python3 tools/testpar.py --jobs 2 tests/wip_test_m11_s2lay.py tests/wip_test_m11_fxconv.py test_testpar` | 25 + 15 + 32 tests OK; the three also OK on Python 3.9.6 with `-W error::ResourceWarning` |
| `python3 tools/testpar.py --jobs 4` with every `tests/test_*.py` (no `test_native_game_*` exists yet) and both wip modules | 68 modules, 1,455 tests, 0 failures, 0 errors, 0 skipped, 206.5 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |

Nothing broke between the two parts. `build/native/m11` is 524 KB.

**Open after wave 1.** `MENUW` has no room for `PALST` (768 B) beside its
256 B state block (`s2pal`, `s2menu1`); the channel record's `CH_X`,
`CH_Y` are 3 bytes [A] (`fxchan`); a build linking `pl_vbl` must name its
crash stop `pl_crash` (`plclock`); milestone 8's bucket pass marks phase
18 [R `rdriver.s:163`, `bdriver.s:24`], which GAME.md 5.4 gives
milestone 10 (for milestone 10's integrator); the effects are unheard,
the divisor table was read over the network with no offline copy, and
`DMACT`'s automatic script keeps the gated warble (`fxconv`'s notes 9).

### 8.6 Wave 2 as integrated (2026-10-01)

Parts `plclock`, `s2cap` and `s2draw` (their notes:
`docs/m11-parts/plclock.md`, `s2cap.md`, `s2draw.md`, each with a section
on the integration). The requests:

| Request | Outcome |
| --- | --- |
| PLCLOCK-1 (the clock's bytes) | Applied: `s2layout.py` `CLOCK_FIELDS` is `CLK_STEP` 2, `CLK_FRAC` 2, `CLK_TICS` 4, `CLK_STD` 1, `CLK_TIME3` 1, `CLK_SPARE` 6 (the addresses the stand-ins used, so the images are unchanged); the `STANDIN` aliases are gone from `pl_irq.s`; 2.2 (state, `I_GetTime`), 4.4 (`$E403-$E412`, and `$F505-$F8FF` as measured) and `design.md` R2 item 1 (rows `$E403-$E412`, `$E900-$F8FF`, `$FF00-$FFF9`) changed |
| PLCLOCK-2 (a boot segment) | Not applied (optional): no image has a boot before `plboot`. Open for `fxplay`: `FXCODE` keeps 26 B with `fxplay`'s 620 B and `VATT`'s 128 B, and PLCLOCK-2 frees 128 B if it needs them |
| PLCLOCK-3 (notes for `plboot`) | Nothing to apply; kept for `plboot` (mode `$09`, the boot's order, `pl_irq.o` or S2's `irq.o`, never both) |
| S2CAP-1 (`st_palette` a signed byte) | Applied in the field map; `s2state.ENC_STANDIN` removed |
| S2CAP-2 (6.1's points as built) | Applied: 6.1's `PD0`, `PD1` rows replaced, `PC`, `PM`, `PU0`/`PU1` added, the paragraph after the table, the budget as measured |
| S2CAP-3 (no `iddt`) | Applied: 6.1, `automap.script`'s row |
| S2CAP-4 (where the key table is poked) | Applied: 6.2 |
| S2CAP-5 (sound positions, for `fxchan`) | Nothing to apply; recorded in 6.1 and below |
| S2DRAW-1 (the drawers' places) | Applied: `s2layout.py` `S2_ZP` (`S2_BAND` `$48` to `S2_MB1` `$77`, the four aliases checked inside `S2_X`, `S2_Y`) and `DRAW_PLACES` (`P2DW_MARKS` `$9700`, `P2DW_FBUF` `$B800`, 4 pages; `WIW`, `FINW` `$9900`, `$BA00`, 2; `AMAPW_MARKS` `$A900`, no buffer) in `s2.inc`, each checked by `check()` against its image's runtime ranges; `src/native/s2_draw.inc` deleted, its interface text moved to `s2_draw.s`; the test images use the new names. `MENUW` gets no places: its runtime ranges are full and its marks page has no room (for `s2menu1`, below); 4.3 says `$48-$77` is the drawers' |
| S2DRAW-2 (`AMAPW`'s `s2_pub` row) | Applied in `size_rows`; `s2pt` links `s2_pub.o` (the `s2pubalone.o` rule gone); `wip_test_m11_s2draw` checks `AMAPW`'s `s2_pub` row (145 of 200 B) |
| S2DRAW-3 (one snapshot a call) | Applied: `s2_drv.s` masks the interrupt over `s2d_called`; `s2drawcase.call_snapshots` now fails on a repeated snapshot instead of dropping it |
| S2DRAW-4 (the store's contracts) | Applied: 1.4 and 4.5 |
| S2DRAW-5 (`s2_begun`) | The place applied: `PS_BEGUN`, `PALST` offset `$02D1` (`s2layout.PALST_NATIVE`, in `s2.inc`), which `s2_publish` sets and `s2_finish` clears; `P2DW`, `WIW`, `FINW` export `s2_begun = PALST_W + PS_BEGUN`. `AMAPW`'s `s2_begin` (link `s2_pal` and give `AMAPW` a `PALST` of its own, or have the frame driver run `s2_begin` before `AMAPW` in a full-automap frame) is left to part `s2pal`, which builds `s2_begin` and knows its size; the test images keep their own `s2_begun` until then |

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 77 GB free):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check` (also under Python 3.9.6), `--report` | passes; the report as after wave 1 (card block 59 of 61 B, channels 48 of 64 B, phases 0-18 and 30) |
| `make -C src/native -f m11.mk`, and `part P=` each of `s2lay`, `plclock`, `s2draw`, `s2cap`, `fxconv` | no warning, no error |
| `make -C src/native -f m11.mk sizes` | `s2lt` 24 B, `plct` 155 B, `s2dt` 1,842 B (`s2_draw+s2_pub` 1,172 of 1,200) of 7,424 in `P2DW`'s room; `s2pt` 171 of 10,240 in `AMAPW`'s (`s2_pub` 145 of 200) |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2` (6 s) | 0 problems: PAL 3,004 VBLs, 2,096 tics, 34.954 tics/s; NTSC 3,595 VBLs, 2,097 tics, 34.963 tics/s, every VBL equal to the model; the second entry unchanged; 13 songs × 20 s through `pl_vbl`, the AY log equal to S2's; worst interrupt 1,546.9 µs (`D_INTRO`, window 32), 1,558.5 µs at window 512; stack 16 B; the bridge's 100 interrupts and the BRK with `ALTZP` on; `FXCODE` 245 of 1,019 B |
| `python3 tools/native/s2cap.py --check --twice --two-run 3 --jobs 2` (2 min 31 s) | `report.json` `ok`, 0 problems in all eleven runs, each captured twice the same; 85,736 host injections and 36 a2vm runs read back equal with the field map's `sxbyte` (no unfit value, no stand-in); 1,525 carried checks; 72 goals; cases 22.9 MB |
| `python3 tools/native/s2drawcase.py` (1 min 19 s: the truth recaptured, since its cache key holds the tool) | 2,483 synthetic and 65 captured cases: the model and the native drawers 0 problems against ref816, with one snapshot a call checked strictly |
| `python3 tools/native/s2drawcase.py --timing` | 4.174 µs a patch pixel `f121`, 3.265 `fastpath`; 0.991 µs a published byte |
| `python3 tools/testpar.py --jobs 4` the five wip modules and `test_testpar` | 121 tests OK; `s2lay`, `s2draw`, `plclock`, `s2cap` also OK on Python 3.9.6 with `-W error::ResourceWarning` (74 tests) |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the five wip modules | 72 modules, 1,515 tests, 0 failures, 0 errors, 0 skipped, 158 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |

Nothing broke between the three parts. `build/native/m11` is 52 MB (the
cases 22.9 MB, `s2draw`'s truth and images 26 MB).

**Open after wave 2.** `fx_step` and `fx_burst` are still the stand-ins
(`pl_fxstub.s`) until `fxplay`, whose `FXCODE` room is tight (26 B left;
PLCLOCK-2); `AMAPW`'s `s2_begin` and `MENUW`'s `s2_begun` (no `PALST`
there) are `s2pal`'s and `s2menu1`'s (S2DRAW-5), and `MENUW`'s marks page
has no room among its runtime ranges (`s2menu1`); the injection leaves
`PS_BEGUN` poisoned, so a part injecting a frame start sets it 0
(`s2pal`); the sound positions are not in the cases and `S_UpdateSounds`
under a menu is not logged (`fxchan`, `s2menu1`); `s2_drv` turns the VBL
on with mode `$08`, the design and `MUSIC.SYSTEM` with `$09` (`plboot`
uses `$09`); the bridge is tested on a2vm at `--speed 1` only; the worst
interrupt with music alone, 1.55 ms in the Doom profile, is S2's burst;
the patch pixel's 4.2 µs (`s2stbar`, lever L2); bands of 40 and 42 rows
are run first by `s2wi`, `s2fin`, `s2amap`.

### 8.7 Wave 3 as integrated (2026-10-01)

Parts `fxplay`, `s2pal` and `s2data` (their notes:
`docs/m11-parts/fxplay.md`, `s2pal.md`, `s2data.md`, each with a section
on the integration). The requests:

| Request | Outcome |
| --- | --- |
| FXPLAY-1 (the effects' names) | Applied: `s2layout.py` `V_RPOS` (in `V_SIDE`'s place), `FX_SVC` (in `FX_SPARE`'s), `FX_ZP` (`FXZ_RING` `$F7`, `FXZ_N` `$F9`, `FXZ_T` `$FA`, `FXZ_AV` `$FB`, `FXZ_OP` `$FC`) in place of `FX_RP`, in `s2.inc` and `check()`; `fx.s`'s `STANDIN` lines gone (its compose names are aliases of these). No address moved |
| FXPLAY-2 (the player as built) | Applied: 3, 4.3, 4.4; `tools/sound/README.md` "The player", "Memory", "Cost", "Tests"; `design.md` R2 item 1 |
| FXPLAY-3 (the builds that link the player) | Nothing to apply before waves 4-8 build the frame images and `plboot` the card image; `plclock`'s test images keep `pl_fxstub.o` (optional) |
| FXPLAY-4 | For `fxchan`; nothing to apply |
| S2PAL-1 (`S2PAL`'s places) | Applied: `s2layout.S2PAL_PLACES` (`S2P_TINTPAL` `$0200`, `S2P_NIB` `$1800`, `S2P_GSSTAT` `$5800`, `S2P_GSOVL` `$6E20`, `S2P_GRAYMAP` `$7700`, each with `_SIZE`) in `s2.inc`, checked; `s2pal.inc` keeps only the part's own values |
| S2PAL-2 (`PS_TXTINV`) | Applied: `PALST_NATIVE`, offset `$02D2` |
| S2PAL-3 (`$78-$7F`) | Applied: `S2P_A`-`S2P_F` in `S2_ZP`; 4.3 |
| S2PAL-4 (page 1) | Applied: 4.2; `MEMORY_MAP.md` section 2 in `design.md` R2 item 5 for the final integrator |
| S2PAL-5 (`palettecount` a flag) | Applied: the field map's encoding `flag`, in `s2state.encode`/`decode` and `check()` |
| S2PAL-6 (`NO_PALETTE_CHANGE` 100) | Applied in `s2state.py` [R `i_viigs65.s:66`]; `marked()` no longer poisons palettes 0-11 in every frame |
| S2PAL-7 (where `setRows` is) | Applied: 7.3 |
| S2PAL-8 (`AMAPW`'s `s2_begin`, `MENUW`'s PALST) | Not applied: left to `s2menu1` (wave 5) and `s2amap` (wave 6), below |
| S2PAL-9 | For `s2stbar` and `s2menu1`; nothing to apply |
| S2DATA-1 (the store's neighbours) | Applied: `s2layout.SFX_ROOM`, `S2VIEW_SAVE`, `GFXDIR_PLACE`; `s2data.py` uses them |
| S2DATA-3 (`GSSTAT`, `GSOVL`) | **Decided: in `S2PAL`**, as this design's 4.5 and part `s2pal` have them (S2PAL-1 asked the store to put them there; `PALW` reads them there). They stay lumps of the store with their handles, written by `GFX.1` at `S2P_GSSTAT` and `S2P_GSOVL` outside the packing (`s2data.FIXED`); `check_places` fails a record elsewhere and `wip_test_m11_s2data` checks that only these two lumps are in `S2PAL` |
| S2DATA-2 (the store as built) | Applied with S2DATA-3's numbers: 0.1 F5, 4.5, risks 3-4 |
| S2DATA-4 (lump numbers as handles) | Applied: encoding `gfx` (a handle a byte, `$FFFF` as `$FF`) for `W_LUMPS` (now 33 B), `F_HELP2`, `F_BACKGROUND`; every value of the three fields in every case of the eleven runs is a 2D lump [M: a scan before the change], and `s2cap`'s rerun has no unfit value |
| S2DATA-5 | Recorded in `design.md` R2 item 4 for the final integrator |
| S2DATA-6 | For `plboot`; nothing to apply (`GFX.1` now also writes bank 106 `$5800-$765F`) |

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 70 GB free; at most 4 jobs at once):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check`, `--report` | passes; the report as after wave 2 |
| `make -C src/native -f m11.mk all`, and `part P=` each of `s2lay`, `fxconv`, `plclock`, `s2cap`, `s2draw`, `fxplay`, `s2pal`, `s2data` | no warning, no error |
| `make -C src/native -f m11.mk sizes` | unchanged: `fxpt` `fx_service` 396 of 400 B; `palw` `s2_nib` 390 of 400, own 443 of 1,500 (833 of 6,656 in `PALW`'s room); `s2pp` `s2_pal` 680 of 800; `s2pf` 1,751 of 6,656 in `WIW`'s room; `s2dt`, `s2pt`, `plct`, `s2lt` as after wave 2 |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2` (35 s), `--planted --jobs 2`, `--timing` | 0 problems; every scenario of `fxplay.md` 3 as there (13 songs with and without effects equal to S2's and the model; the hold, 5 VBLs inside; worst interrupt 2,047.9 µs, music alone 1,548.9 µs; stack 16 B); the 8 planted bugs caught with the same failures; `fx_service` 19.0 / 89.7 / 130.2 µs at 50 frames a second (`f121`); the card part 739 B, `FXCODE` 983 of 1,019 B |
| `python3 tools/native/s2pal.py --all --jobs 2` (4 min 31 s) | `checkpoint passes: 0 problems`: the 9 runs, 1,652 finishes; the 7 planted bugs caught; the timing as `s2pal.md` 5 (0.71 ms with nothing to write, `f121`) |
| `python3 tools/native/s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check` | sources, places, read-back, include OK; the budget met without bank 125 (the table in `s2data.md` 7) |
| `python3 tools/native/s2cap.py --check --twice --two-run 3 --jobs 2` (2 min 44 s) | 0 problems in all eleven runs, each captured twice the same; 85,736 host injections and 36 a2vm runs read back equal with the encodings `flag` and `gfx`, no unfit value; 1,525 carried checks; 72 goals; cases 22.9 MB |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2` | 0 problems: as after wave 2 (PAL 34.954, NTSC 34.963 tics/s; 13 songs equal to S2's; worst 1,546.9 µs; `FXCODE` 245 B with the stand-ins) |
| `python3 tools/native/s2drawcase.py`, `--timing` | 2,483 synthetic and 65 captured cases, 0 problems; 4.174 µs a patch pixel `f121`, 3.265 `fastpath`; 0.991 µs a published byte |
| `make -f src/native/m11/fxconv.mk fxconv fxconv-renders`; `python3 tools/native/s2run.py --profile f121` | up to date; stop `$81`, 0 stray writes |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the eight wip modules | 75 modules, 1,561 tests, 0 failures, 0 errors, 0 skipped, 215 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests); the wip modules 135 tests |
| the five wip modules this wave changed (`s2lay`, `s2cap`, `s2pal`, `s2data`, `fxplay`) on Python 3.9.6 with `-W error::ResourceWarning`; `s2lay`, `fxconv`, `plclock`, `s2draw`, `s2data`, `test_testpar` again after the fix below | 87 and 122 tests OK |

**Fixed between the parts and milestone 10.** During the integration
milestone 10's work in progress `src/native/game/flow/gflow.s` began
storing `lda #FL_PH_ENTRY` / `lda #FL_PH_RESUME` to `PHASE`, names the
file defines itself (`= 30`, `= 31`); `s2layout`'s phase scanner could
not read them, so `check()`, and with it every generated `s2.inc` and
every build of this half, failed. The scanner now resolves the constants
a file defines (`NAME = expression`, `_local`), which is what it lacked;
nothing is excused: those two stores read as phase 15 (the values / 2),
inside 0-31 and not the platform's 31.

Nothing else broke between the three parts. `build/native/m11` is 55 MB.

**Open after wave 3.** For milestone 10's integrator: `gflow.s` writes
`PHASE` values 30 and 31, i.e. phase 15 by a2vm's rule (value / 2); if
phases 30 and 31 were meant, they are this half's `PHASE_2D` and
`PHASE_PLATFORM` (4.8), and the values would be 60 and 62. `AMAPW`'s
`s2_begin` and `MENUW`'s PALST (S2PAL-8) are `s2amap`'s and `s2menu1`'s:
`s2pal` proposes that `AMAPW` link `s2_pal` with PALST at W
`$8B00-$8DFF` (its room ending at `$8B00`); `MENUW` has no room yet.
Each band's row nibble pages (the rest of `rowPalette`) are built by no
shared code yet (`s2stbar` and the drawing images, or about 120 B left in
`s2_pal`). PALST's write-back costs 0.71 ms a frame even with nothing to
write (lever for the performance pass). `FXCODE` keeps 36 B
(PLCLOCK-2 would free 128 B and `fx_init`'s 52 B could join it);
`fx_burst`'s lists must stay in one page in the release link (asserted);
`plclock`'s test images still link `pl_fxstub.o`. The effects are
unheard (milestone 12). The 2D store leaves 456-1,036 B in
`GFX0`-`GFX3` and 2 B in 107 below `MATHW`; 42,768 B remain in 104,
107's and 108's tops before bank 125. Tints past TINTPAL's 14 and
`st_palette` outside -128..127 (counts past 32,000) are compared on the
model only.

### 8.8 Wave 4 as integrated (2026-10-01)

Parts `s2stbar`, `s2hud` and `fxchan` (their notes:
`docs/m11-parts/s2stbar.md`, `s2hud.md`, `fxchan.md`, each with a section
on the integration). The requests:

| Request | Outcome |
| --- | --- |
| S2STBAR-1 (`ST_READY`, `ST_RUNNING`) | Applied: the tic-side block's last two bytes (61 of 61 B); the field map's `W_READY+8` (encoding `readysrc` in `s2state`) and `st_running`. `W_READY`'s NULL before the first `ST_Start`, which every capture has in its frames before a level, is `$FD`, which `st_init` now writes (4.4) |
| S2STBAR-2 (`SS_STBUF`) | Applied: `S2STATE` `$6120` (1.5.1, 4.5) |
| S2STBAR-3 (`P_MHID`, `P_FPSRATE`) | Applied in `_stbar()`'s state fields (`$BF2C`, `$BF2D`); `VW_MHID` is outside the units' near data, so `s2cap` dumps it at `PD0` (6.1) and the cases were captured again |
| S2STBAR-4 (the tic side's linkage) | Recorded in `design.md` R4 items 1-4 (`pta3` in the tic image's math is item 4) |
| S2STBAR-5 (`markpatch`) | Applied: `s2_draw.s` exports `s2_markp`; `s2_st`'s copy gone (1,974 to 1,860 B) |
| S2STBAR-6 (the frame's order) | Recorded in `design.md` R7 item 7 |
| S2STBAR-7 (`stbar.script`'s ready weapon 10) | Not applied: X-ST1 stays named and counted (37 frames); changing the script moves its dead-face frames and `s2cap`'s goals |
| S2HUD-1 (`P_TXTTEXT`, `P_MSGFILL`, `P_MAPFILL`) | Applied: `textText` a `state` field and `s2layout.P2DW_NATIVE` (`$BF89`, `$BFDD`, `$BFDF`; the block ends at `$BFE0`) |
| S2HUD-2 (`hu_drawer`'s flags) | Recorded in `design.md` R7 item 7 for the frame driver, `s2amap`, `s2ovl` |
| S2HUD-3 (`SS_HUDMSG`) | Applied after `SS_STBUF`, at `$7520` (both parts' stand-ins assumed the room after `SS_SIGN`: `$6120` and `$6200`, which overlap); 1.5.2, 4.1, 4.5. Loading `HUDTXT.1` is `plboot`'s |
| S2HUD-4, s2stbar's and fxchan's open problem (the phase check against `gflow.s`) | Settled in `s2layout.py`: a `PHASE` store inside milestone 10's test-build branches (`.ifdef TESTBUILD` and its forms) is checked in 0-31 and readable, not against 4.8's owners (4.8); every other store as before (`gflow.s`'s `fl_timed` 30 and `fl_tresume` 31 are listed by `--report`). `design.md` R8 for milestone 10. The parts' fallbacks that built with `make -o` (one bypassed `check()`) are removed |
| S2HUD-5 (the title's rows, `resolve_game`) | Applied: region `title` rows 160-167; `resolve_game` without the second `FB`; `s2cap`'s title rows 160-167 |
| S2HUD-6 (`HU_MSGID`, `player.message`) | Applied: `HU_MSGID` from `w_message`, encoding `msgid`; `player.message` a deferred `player` field; `textText` injected |
| S2HUD-7 | Recorded in `design.md` R5 |
| FXCHAN-1 (the channel record) | Applied as written (`CH_*`, `CHF_PICKUP`, `CHF_KIND`; `fx_chan.s`, `fx_pcache.s` renamed from `FC_*`, which also met `glayout`'s zero page `FC_X`, `FC_Y`) |
| FXCHAN-2 (`LS_ON`, `SND_SFXVOL`) | Applied **after the mailboxes** (`s2layout.SC_EXTRA`: `$E8F0`, `$E8F1`; the channel block 50 of 64 B), not in the tic-side block, whose two spare bytes S2STBAR-1 took and which cannot grow; `FXCH8`'s room `$E000-$E0FF`; `fxcrun`, `fxcap` read and poke the two runs |
| FXCHAN-3 | Applied to `design.md` R4 |
| FXCHAN-4 | For `s2menu1`; nothing to apply |
| FXCHAN-5 (budgets) | Applied: `fx_chan` 1,100 B, `fx_pcache` 90 B, `MENUW`'s total 16,000 of 16,896 (4.1, 4.7, 7.3); the fxchan test now requires them |
| FXCHAN-6 | Applied: 3; `tools/sound/README.md` |

**Fixed between the parts.** `fxchan.mk` and `fxplay.mk` both had a rule
for `build/sound65/tables.inc`, so `make -f m11.mk` warned ("overriding
commands"): both now hold the same rules for S2's objects inside `ifndef
M11_SOUND65_RULES`. S2STBAR-1 and FXCHAN-2 asked for the same two card
bytes, and S2STBAR-2 and S2HUD-3 for overlapping places in `S2STATE`
(above). With the field map's new encodings, `s2cap`'s planted bug "a word
field injected as a byte" no longer applied (the `msgid` encoder repeated
the word encoder's text; it is written apart now). A scratch link of
`P2DW` with what the waves built (`s2_st`, `s2_hu`, `s2_draw`, `s2_pub`,
`s2_pal`, `fx.s`'s `fx_service`, a frame glue in 2.1's order) resolves
every symbol: 5,545 of 7,424 B (own 3,297 of 3,900 with a 26 B glue;
`pl_poll`, 600 B, to come).

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 69 GB free; at most 4 jobs at once):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check` (also Python 3.9.6), `--report` | passes; card block 61 of 61 B, channels 50 of 64 B; `S2STATE` `$0200-$811F`; phases written 0-18 and 30; the test-build harness's `gflow.s:882` 30 and `:893` 31 listed |
| `make -C src/native -f m11.mk all`, and `part P=` each of the eleven parts | no warning, no error |
| `make -C src/native -f m11.mk sizes` | `s2sb` (`s2_st` 1,860 of 2,000), `s2st` (`s2t_st` 888 of 900), `s2ht` (`s2_hu` 1,411 of 1,700; 3,626 of 7,424 in `P2DW`'s room), `fxcmw` (`fx_chan` 970 of 1,100 in `MENUW`); the others as after wave 3 |
| `python3 tools/native/s2cap.py --capture --jobs 2` then `--check --twice --two-run 3 --jobs 2` (30 s, 2 min 30 s) | `report.json` ok: 0 problems in all eleven runs, each captured twice the same; 85,736 host injections and 36 a2vm runs read back equal with `readysrc` and `msgid`, no unfit value; 1,525 carried checks; 72 goals; cases 22.9 MB |
| `python3 tools/native/s2stbar.py --capture --jobs 2`, `--all --jobs 2` (16 min) | `report.json` ok, 0 problems: the native tic side 9,978 cases, 0 stray, stack 19 B; the drawer 5,204 cases (400 runs), 0 stray, stack 21 B; demo3's 534 frames chained; coverage 380 of 380; X-ST1 37 frames; the six planted bugs caught; a face 6.52 ms, a refresh 44.09 ms, nothing 0.06 ms (`f121`) |
| `python3 tools/native/s2hud.py --all --jobs 2` (1 min 31 s) | `report.json` ok on `f121` and `fastpath`: 3,188 tics, 734 PV, 794 frames (3 excluded by name), 64 synthetic tics and 12 lines; the seven planted bugs caught; a fresh line 15.17 ms median, 22.02 worst (`f121`) |
| `python3 tools/native/fxcap.py --check --jobs 2` (1 min 43 s), `--planted --jobs 2` | ok: every captured call equal (demo3 1,218, DEMO1 2,290, DEMO2 1,273, the tour 137, the menu 709), 134 eviction cases, no path missing, the 3-channel replay and 10,000 random sequences (35,041 calls) 0 failed; the seven planted bugs caught; `fx_chan` 1,085 B, `fx_pcache` 85 B |
| `python3 tools/native/s2pal.py --all --jobs 2` (5 min 34 s) | `checkpoint passes: 0 problems` |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2` | 0 problems, as after wave 3 (PAL 34.954, NTSC 34.963 tics/s) |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2`, `--planted --jobs 2`, `--timing` | 0 problems, as after wave 3 (worst interrupt 2,047.9 µs at window 32, 2,050.8 µs at 512); the 8 planted bugs caught; `FXCODE` 983 of 1,019 B; `fx_service` 19.0 / 89.7 / 130.2 µs |
| `python3 tools/native/s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check` | OK; the store's packing unchanged, 104's free part now `$8200-$BFFF` (15,872 B) |
| `python3 tools/native/s2drawcase.py`, `--timing`; `python3 tools/native/s2run.py --profile f121` / `fastpath` / `--fill 5a`; `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | 0 problems; 4.174 µs a patch pixel; stop `$81`, 0 stray writes; up to date |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the eleven wip modules | 78 modules, 1,597 tests, 0 failures, 0 errors, 0 skipped, 302 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |
| the five wip modules this wave changed (`s2lay`, `s2cap`, `s2stbar`, `s2hud`, `fxchan`) on Python 3.9.6 with `-W error::ResourceWarning` | 77 tests OK |

`build/native/m11` is 79 MB.

**Open after wave 4.** For milestone 10's integrator (`design.md` R4,
R5, R7, R8): the hooks and `s2t_pos` as built, `pta3` in the tic image's
math, the modules' scratch blocks and sizes, `GT_POS` still a stand-in in
`s2stbar.inc`, `hu_tick`'s order (the test glue's `hutick` a stand-in),
the phases 30 and 31 kept inside `.ifdef TESTBUILD`. For the frame driver
(the second half): `P2DW`'s order, `hu_drawer`'s three flags (injected
from the reference in the checkpoint; nothing native computes them yet),
`P_FPSRATE`. `HUDTXT.1` is loaded by nothing before `plboot`. X-ST1 (37
frames of `stbar.script`). The timing levers: a status bar refresh 44 ms
and a fresh HUD line 15-22 ms on `f121` (L2; `s2_draw`'s refill of its
fetch buffer at every glyph; the refresh's `STCACHE` path), and the tic
image's update computes `SS_SEP` though it reaches no mailbox (about 40
µs a positional channel). `fx_chan`'s sizes are over the first budget
(raised, FXCHAN-5). The effects are unheard (milestone 12).

### 8.9 Wave 5 as integrated (2026-10-01)

Parts `plinput`, `s2menu1` and `s2wi` (their notes:
`docs/m11-parts/plinput.md`, `s2menu1.md`, `s2wi.md`, each with a section
on the integration). The requests:

| Request | Outcome |
| --- | --- |
| PLINPUT-1 (`PL_KEYTAB`) | Applied: main `$1F80-$1FFF` (`s2layout.KEYTAB_PLACE`, checked in `MEMORY_MAP.md` 3.3's `$1A80-$1FFF` and against every layout's main places); 2.4, 4.2; `design.md` R3 |
| PLINPUT-2 (`PL_MLX`), PLINPUT-3 (`PL_BIND`) | Applied: the block 59 of 59 B; `PL_BIND`'s values `PLB_WAIT` `$FF`, `PLB_IDLE` `$80` in `s2.inc` (the menu writes them too); 2.4, 4.2 |
| PLINPUT-4 (`PLZ`) | Applied: `s2layout.PL_ZP` `$5A-$69`, checked equal to the drawers' temporaries; 4.3 |
| PLINPUT-5 (`pl_keys`) | Applied with S2MENU1-2 (they met): `pl_keys` 300 B in `MENUW`; `MENUW`'s room is now 16,128 B, so its own budget is 11,328 (names and strings 2,500 → 2,328) and its total the room (4.1). `plit`, part `plinput`'s test image, links in `MENUW`'s room (in `P2DW`'s, `pl_keys` was a row its table does not list) |
| PLINPUT-6 (`s2state.apple2e_keys`) | Applied: it returns `plkeys`' table. Nothing captured again: `menus.script`'s captures are not poked (only `s2cap`'s `KeyPoke` test pokes; part `s2menu2` will) |
| PLINPUT-7 (`test_phases`) | Applied: 31 allowed, only from a platform source |
| PLINPUT-8 | Recorded in `design.md` R7 item 10 |
| S2MENU1-1 (`MENUW`'s native fields, `REQ_*`) | Applied **without `M_BINDWAIT`, `M_BINDCODE`** (`s2layout.MENUW_NATIVE`, `MENU_REQUESTS`; in `s2.inc`) |
| S2MENU1-2 (`MENUW`'s places) | Applied: room `$6600-$A4FF`, `PALST` `$A500`, the marks `$B800` (`DRAW_PLACES`), `UI_GRAY` 256 B, `PL_MENUAMEM` `$C5`, `fx_pcache` in `fx_chan`'s row (1,055 of 1,100 B); 4.1, 4.2 |
| S2MENU1-3 | Applied: 1.5.3, 4.3, 7.3 |
| S2MENU1-4 (the menu's input) | Applied through `PL_BIND` (2.4): the poll is one object in every image and cannot write `MENUW`'s W state, so `M_BINDWAIT` and `M_BINDCODE` went; `pl_bindkey`, `pl_defkeys` are `pl_bind`, `pl_defaults`; `m_frame` passes `pl_poll` `G_MENUACTIVE`. `pl_mouseup` stays a marked stand-in (the MOUSE option: `plinput` open problem 2) |
| S2MENU1-5 | Nothing to apply (`s2menu2`'s hooks; 7.3) |
| S2MENU1-6, S2WI-5 | Recorded in `design.md` R7 items 9 and 8 |
| S2WI-1, S2WI-6 | Applied: 4.3; 4.1 and `s2layout`'s `WIW` runtime text |
| S2WI-2 | Applied: `WIW` own 1,950, total 5,350 (4.1) |
| S2WI-3 | Applied: `WIW` links `pl_input.o`; `s2_wipl.s` deleted |
| S2WI-4 | Applied: 1.5.5, 5; `design.md` R7 item 8 for milestone 10 |
| S2WI-7 | Applied: `s2state.inject(..., 'palettes')` writes `PS_BEGUN` 0; `DEFERRED` names `NIBTAB` |

**Fixed between the parts.** The bind interface above (S2MENU1-4 against
PLINPUT-3). `wi_frame` passed `pl_poll` its own flags byte (bit 0, a level
was left), which the real poll reads as "a menu is up": it passes 0.
`MENUW` and `WIW` link `pl_irq.o` for `pl_time` (in the card's `FXCODE`,
as the release; the test driver's handler stays), and the checkpoints of
`s2menu1` and `s2wi` start their runs with the input block as `pl_init`
leaves it and the default key table (`plinput.boot_records`) and judge
the poll's writes (`plinput.image_owners`). `s2menu1`'s checkpoint maps
the reference's bind state to `PL_BIND` (the ADB Esc `$35` as the //e's
`$1B`, other codes 1:1 as 6.2's poke) and compares it after every
`M_Responder` and, new, every `M_Ticker` call. `m11/s2menu1.mk` and
`m11/s2hud.mk` both had a rule for `s2data.json` ("overriding commands"):
one rule now, inside `ifndef M11_S2DATA_JSON_RULE`. The 7 opens' paused
frames run the real `pl_poll` under the write log (63 of its writes in the
first, all owned).

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 69 GB free at the start; at most 4 jobs at
once):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check`, `--report` | passes; `MENUW` 16,128 of 16,128 B, `WIW` 5,350 of 6,656; phases written 0-18, 30, 31; the test-build harness's `gflow.s:914` 30 and `:925` 31 listed |
| `make -C src/native -f m11.mk all`, and `part P=` each of the fourteen parts | no warning, no error |
| `make -C src/native -f m11.mk sizes` | `s2m1` (`MENUW`): `pl_poll` 554 of 600, `pl_keys` 228 of 300, `fx_chan` 1,055 of 1,100, own 5,653 of 11,328, room 9,738 of 16,128; `wiw`: `pl_poll` 554, own 1,924 of 1,950, room 5,116 of 6,656 (`s2wt` own 2,192 with its 268 B glue: `OVER BUDGET`, a test image); `plit` 989 B in `MENUW`'s room; the others as after wave 4 |
| `python3 tools/native/plinput.py --checkpoint --jobs 2`, `--no-build --planted --jobs 2` | 55 sequences, 220 runs, 3,988 polls, 3,690 events, 0 problems, stack 14 B; a poll 0.0435 / 0.0514 / 0.0554 ms (`f121`); the eight planted bugs caught |
| `python3 tools/native/s2menu1.py --all --jobs 2` (3 min 22 s) | ok: 157 frame jobs (314 runs, 10,271,568 bytes), 283 `M_Responder` (102 sounds, 1 request), 863 `M_Ticker` in 155 chains (1 bind), the 7 sessions chained (159 frames, 268 events, 652 tics; 71 frames X-M2), 0 problems, stack 21 B; the five planted bugs caught; own 5,475 B (code 3,728, data 1,747); a full frame 93.3 ms, a skull 3.0 ms, the open 136.4 ms, the close 46.9 ms (`f121`) |
| `python3 tools/native/s2wi.py --all --jobs 2` (4 min 40 s) | `report.json` ok: the 214 frames injected (both fills) and chained, 0 problems, 0 stray writes; the four planted bugs caught as in `s2wi.md` 3; load 1.26 ms, drain 32.2 ms |
| `python3 tools/native/s2cap.py --capture --jobs 2`, then `--check --twice --two-run 3 --jobs 2` (49 s, 5 min 21 s) | 0 problems in all eleven runs (with S2WI-7's `PS_BEGUN` record) |
| `python3 tools/native/s2stbar.py --capture --jobs 2`, `--all --jobs 2` (22 min) | `report.json` ok: the tic side 9,978 cases, the drawer 5,204 cases, demo3's 534 frames chained, 0 stray; coverage 380 of 380; the six planted bugs caught |
| `python3 tools/native/s2hud.py --all --jobs 2` | `report.json` ok on `f121` and `fastpath`, as after wave 4; the seven planted bugs caught |
| `python3 tools/native/fxcap.py --check --jobs 2`, `--planted --jobs 2` | ok, as after wave 4 (134 eviction cases, 10,000 random sequences, 35,041 calls, 0 failed); the seven planted bugs caught |
| `python3 tools/native/s2pal.py --all --jobs 2` (5 min 47 s) | `checkpoint passes: 0 problems` |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2` | 0 problems (PAL 34.9544, NTSC 34.9633 tics/s) |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2`, `--planted --jobs 2`, `--timing` | 0 problems (worst interrupt 2,047.9 µs at window 32, 2,050.8 µs at 512); the 8 planted bugs caught; `FXCODE` 983 of 1,019 B; `fx_service` 19.0 / 89.7 / 130.2 µs |
| `python3 tools/native/s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check` | OK; bank 108's free part is now `$A500-$BFFF` (`MENUW`'s smaller room) |
| `python3 tools/native/s2drawcase.py`, `--timing`; `python3 tools/native/s2run.py --profile f121` / `fastpath` / `--fill 5a`; `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | 0 problems; 4.174 µs a patch pixel; stop `$81`, 0 stray writes; up to date |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the fourteen wip modules | 81 modules, 1,637 tests, 708.6 s: 2 failures, both `wip_test_m11_s2menu1`'s hand-made checks of the stand-ins (the native fields outside `state_places`, `PALST` inside the old room), rewritten for the applied requests (the fields after the field map's and equal to `state_places`; the room's end `$A500` and `PALST` a runtime range); then the module 12 tests OK. `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |
| the five wip modules this wave changed (`s2lay`, `plinput`, `s2menu1`, `s2wi`, `s2cap`) on Python 3.9.6 with `PYTHONWARNINGS=error::ResourceWarning` | 82 tests OK |

`build/native/m11` is 84 MB.

**Open after wave 5.** For the frame driver and the boot (the second
half; `design.md` R7 items 8-10): `wi_frame`'s flag and `wi_init` at the
boot, the menu's paused frame and its requests, `pl_init` and the
consumer of the queue; nothing native loads `W_LUMPS` or calls `pl_init`
yet. The menu's MOUSE option (`pl_mouseup`, a marked stand-in; `pl_poll`
has no byte for upstream's `iigs_mouseon`). Part `s2menu2`'s hooks
(`m2_page`, `m2_value`, `m2_bench`: stand-ins) and its names: with
`plk_names` (1,024 B) the names-and-strings row would pass its 2,328 B by
about 440 B, inside `MENUW`'s own 11,328 B (`s2m1` 9,738 of 16,128 B);
the levers of `s2menu1.md` open problem 1 (the patches' places from the
handles table, about 400 B). `M_SETCHG` is the second half's input. The
timing: a menu page change 93 ms and an intermission frame 70-100 ms
(`f121`), each republishing 32 KB as upstream (levers in `s2menu1.md` 9, open problem 2,
and `s2wi.md` L-WI). The tour reaches few intermission values (2-5 digit
counts, hours, "sucks", a negative par: no compared frame). The poll's
real-//e races and its one-key limit (`plinput.md` 7, 3-5). The MEMORY_MAP
rows of `design.md` R2/R3 (now with `PL_BIND` and `PL_KEYTAB`) stay for
milestone 10's or the final integrator.

### 8.10 Wave 6 as integrated (2026-10-02)

Parts `s2menu2`, `s2amap` and `s2fin` (their notes:
`docs/m11-parts/s2menu2.md`, `s2amap.md`, `s2fin.md`, each with a section
on the integration; `s2menu1.md` 11 for the changes to that part's files).
The requests:

| Request | Outcome |
| --- | --- |
| S2MENU2-1 (`M_BFPS`) | Applied: the last of `s2layout.MENUW_NATIVE` (`$BF73`, 8 B), in `s2.inc`; `design.md` R7 item 9 (the benchmark's write) |
| S2MENU2-2 (the music's row) | Applied: `s2_menu.s`'s `t_num` the release's (`MUSIC_MENU` 1: the display page 4 rows, the sound page 2), `r_musvol` `uiVolume` on `SS_SETTINGS+5`, the field map's `snd_MusicVolume` (1.5.3; `s2menu1.md`'s D-M8 corrected); the music's volume changes no AY write |
| S2MENU2-3 (one `MENUW`) | Applied **but for `s2menu1.py`'s X-M2**: `s2_menut.s` is the one glue without the hooks' stand-ins, both parts' images link `s2_menu2.o` (`s2m1t` and `s2m2t` are the same bytes), `s2_menu2t.s` is deleted, `s2menu1`'s owners name `s2_menu2`. X-M2 stays in `s2menu1`'s own checkpoint, whose injection lacks `s2menu2`'s records (the key table, the effects' volume, the FPS text); `s2menu2`'s run A compares every page of the one `MENUW` but the key setup's 4 whole frames (X-K), so no page goes uncompared |
| S2MENU2-4, S2FIN-8 (the sign's font) | Option (a): `FINW` keeps `s2_fin.s`'s column drawer (no patch in W; the one compared on the release's signs); `s2menu2`'s `-D M2_SIGNFONT` half, `s2sgt`, `check_signs` and its plant went (1.5.6, 7.3) |
| S2MENU2-5 | Applied: 1.5.3, 4.1, 6.1, 6.2, 7.3 |
| S2AMAP-1 (`AMAPW`'s own fields) | Applied as written (`AMAPW_NATIVE`, `$AC62-$AC6D`; `s2state.DEFERRED`'s `AM_LISTS`) |
| S2AMAP-2 (`SS_AMSEG`) | Applied: `S2STATE` `$8120-$B11F` (4.5); `s2layout.check()` tests the last field; the 2D store unchanged (nothing in 104) |
| S2AMAP-3 (`S2_MAIL`'s bits) | Applied: `MAIL_AMSTRIP`, `MAIL_AMTITLE`, `MAIL_AMVIEW` (4.4); `design.md` R7 item 7's text and item 13 |
| S2AMAP-4 (the full map's stops) | Applied: `PL_AMPALS` `$D1`, `PL_AMSEGS` `$D2` (4.2) |
| S2AMAP-5 | Applied: 1.5.4 (the full row, D-AM1), 4.1, 4.3 |
| S2AMAP-6 | Recorded in `design.md` R7 item 12 |
| S2FIN-1 (`F_SIGNON`, `PL_SIGNAMEM`) | Applied as written (`FINW_NATIVE`, `$BF02`; `$C6`, 4.2) |
| S2FIN-2 | Applied: 4.3 |
| S2FIN-3 (`FINW`'s own budget) | Applied: own 2,300 (data 700), total 5,700 (4.1); `finw.sizes` no longer over; part `s2fin`'s test requires every row within budget |
| S2FIN-4 | Recorded in `design.md` R4 item 1 for milestone 10's integrator |
| S2FIN-5 | Recorded in `design.md` R7 item 11 |
| S2FIN-6, S2FIN-7 | Applied: 4.1 and `s2layout`'s runtime text; 1.5.6, 6.1 |

**Fixed between the parts.** The field map's new `snd_MusicVolume`
stopped `s2menu1`'s call checks (`KeyError: '$0275F6+2 is not in PD0'`):
the call log did not dump it; its ranges now do, and both menu parts' call
logs were captured again. Every part's stand-in of an applied place went
(`s2_fin.s`'s `F_SIGNON`, `FIN_AMEMSTOP`; `s2_am.s`'s `AMS_*`,
`AM_SS_AMSEG`; `s2amap.py`'s and `s2menu2.py`'s fallbacks; the generated
includes no longer define what `s2.inc` does). Part `s2fin`'s open problem
2 (the automap at a finale) is answered by reading: `G_DoCompleted` stops
the map before any intermission or finale [R `g_game65.s:754-758`], and
R6's `MAIL_AMSTOP` stops `AMAPW`'s state at its next entry.

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 59 GB free; at most 4 jobs at once):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check`, `--report` | passes; `MENUW` 16,128, `AMAPW` 7,200 of 10,240, `FINW` 5,700 of 6,656 B; `S2STATE` `$0200-$B11F` |
| `make -C src/native -f m11.mk all`, `sizes` | no warning, no error; `s2m1` (`MENUW`, both menu parts) 11,618 of 16,128 B, own 7,533 of 11,328; `amw` 6,953 of 10,240, own 6,808 of 7,000; `finw` 5,405 of 6,656, own 2,213 of 2,300 |
| `python3 tools/native/s2cap.py --capture --jobs 2`, then `--check --twice --two-run 3 --jobs 2` (27 s, 2 min 38 s) | 0 problems in all eleven runs |
| `python3 tools/native/s2menu1.py --all --jobs 2` (2 min 48 s) | ok: 157 frame jobs (10,271,568 bytes), 283 `M_Responder`, 863 `M_Ticker` (155 chains), the 7 sessions chained (71 frames X-M2), 0 problems, stack 21 B; the five planted bugs caught; own 5,503 B |
| `python3 tools/native/s2menu2.py --all --jobs 2` (2 min 53 s) | ok: K1, K2, B captured again; 204 frame jobs, 408 runs, 13,346,496 bytes, 0 differ; X-K 4; 7 sessions chained (24 frames X-K); 283 and 863 calls; stack 23 B; the four planted bugs caught; `s2_menu2` 1,852 of 4,000 B |
| `python3 tools/native/s2amap.py --capture`, `--all --jobs 2` (3 s, 2 min 31 s) | `report.json` ok, 0 problems: 63 frames and 415 calls injected (both fills) and chained, the host model equal, 0 stray; the four planted bugs caught |
| `python3 tools/native/s2fin.py --capture`, `--all --jobs 2` (9 s, 1 min 36 s) | `report.json` ok, 0 problems: 75 cases, 254 tics, X3 3; the three planted bugs caught |
| `python3 tools/native/s2stbar.py --capture --jobs 2`, `--all --jobs 2` (16 min) | `report.json` ok: the tic side 9,978 cases, the drawer 5,204 cases, demo3's 534 frames chained, 0 stray; coverage 380 of 380; the six planted bugs caught |
| `python3 tools/native/s2hud.py --all --jobs 2` | `report.json` ok on `f121` and `fastpath`; the seven planted bugs caught |
| `python3 tools/native/s2wi.py --all --jobs 2` (4 min) | `report.json` ok: 214 frames injected (both fills) and chained, 0 stray; the four planted bugs caught. Its first run in this integration failed one injected `f121` batch (`tour/f003479..tour/f003801`: "the run ended stop, status $80"), and so did a rerun of `--check --profile f121 --mode injected`; three later full runs, 8 runs of that batch in one process and 6 under different hash seeds all ended `$81` at the same cycle (162,213,541). Not explained (open below) |
| `python3 tools/native/s2pal.py --all --jobs 2` (4 min 44 s) | `checkpoint passes: 0 problems` |
| `python3 tools/native/plinput.py --checkpoint --jobs 2`, `--no-build --planted --jobs 2` | 55 sequences, 220 runs, 3,988 polls, 0 problems; the eight planted bugs caught |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2` | 0 problems (PAL 34.9544, NTSC 34.9633 tics/s); the 13 songs' AY logs equal |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2`, `--planted --jobs 2`, `--timing` | 0 problems; the 8 planted bugs caught; `FXCODE` 983 of 1,019 B; `fx_service` 19.0 / 89.7 / 130.2 µs |
| `python3 tools/native/fxcap.py --check --jobs 2`, `--planted --jobs 2` | ok (134 eviction cases, 10,000 random sequences, 35,041 calls, 0 failed); the seven planted bugs caught |
| `python3 tools/native/s2data.py --check --report`, `make -C src/native -f m11/s2data.mk s2data-check` | OK; 104's free part `$B200-$BFFF`, 0 B of the store there |
| `python3 tools/native/s2drawcase.py`, `--timing`; `python3 tools/native/s2run.py --profile f121` / `fastpath` / `--fill 5a`; `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | 0 problems; 4.174 µs a patch pixel; stop `$81`, 0 stray writes; up to date |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the seventeen wip modules | 84 modules, 1,675 tests, 0 failures, 0 errors, 0 skipped, 680.7 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |
| the six wip modules this wave changed (`s2lay`, `s2cap`, `s2menu1`, `s2menu2`, `s2amap`, `s2fin`) on Python 3.9.6 with `PYTHONWARNINGS=error::ResourceWarning` | 92 tests OK |

`build/native/m11` is 97 MB.

**Open after wave 6.** The `s2wi` batch failure above (twice, while
other checkpoints ran at once; not reproduced since). For the frame
driver and the boot (`design.md` R7 items 9, 11-13): `REQ_BENCH` and
`M_BFPS`, `fin_frame`'s flags, `fin_load`, the busy sign's calls and
`fin_init`, `am_responder`'s and `am_frame`'s calls and `AMAPW`'s load at
each automap event (2.1 ms), `MAIL_AMVIEW`; for milestone 10 (R4 item 1):
`f_start`, `f_ticker` after `WI_checkForAccelerate`. Untested by any
compared case: the sign's "SAVING...", "INSERT DISK n" (the only odd
width), a new text over a sign that is up, the failed save's stop
(`s2fin.md` 8, 1); the full map's maximum scale clamp, a full list, a
clip at the bottom edge, keyed doors', teleporters' and secret sectors'
colours, a second level (`s2amap.md` 8, 4); `AM_Ticker` at frame time
with a move and a zoom in one frame (8, 1); the key setup's binding with
the //e table (`s2menu2.md` 9, 3). D-AM1. The costs: a menu page redrawn
whole 107-163 ms, a finale text frame up to 174 ms, the computer map's
frame 63 ms (`f121`; the levers in the parts' notes). `pl_mouseup` is
still a stand-in. The MEMORY_MAP rows of `design.md` R2/R3 (now
`S2STATE` to `$B11F`) stay for milestone 10's or the final integrator.

### 8.11 Wave 7 as integrated (2026-10-02)

Parts `s2ovl` and `fxdisk` (their notes: `docs/m11-parts/s2ovl.md`,
`fxdisk.md`, each with a section on the integration; `s2amap.md` 10 for
the change to that part's `s2_amline.s`). The requests:

| Request | Outcome |
| --- | --- |
| S2OVL-1 (the fast path's hook) | Applied as written to `src/native/s2_amline.s` (inside `.ifdef AM_FASTLINE`; `AMAPW`'s `s2_amline` is the same 3,700 B, checked by assembling the source with and without the hook); `s2ovl.mk` assembles the source itself with `-D AM_FASTLINE`; the stand-in `gen/s2_amline-ovl.s` and its tool code went |
| S2OVL-2 (`K_OVL` in `rcanon.py`) | Applied as written (milestone 8's `rcanon.py`, unchanged since its commit and not milestone 10's); `s2ovl.py`'s stand-in went |
| S2OVL-3 (`OVLW`'s entry) | Applied **with a change**: the run time range `$9400-$9BFF` and the `own_parts` text as asked, but a run time range inside the room failed `s2layout.check()`; `OVLW`'s run time ranges must now be inside its room (every other image's stay outside it), and `--check-map` keeps an image's stored bytes below such a range (`ovlw.sizes`: 4,922 of 11,264 B). `OVLW_RT0`, `OVLW_RT0_END` in `s2.inc`; the optional `OVLW_AMW`, `OVLW_AMST`, `OVLW_ENTRY` not added (`s2_ovd.s` defines `OVLW_ENTRY`) |
| S2OVL-4 | Applied: `design.md` R7 items 1, 2, 12 (and section 5's R7 row) |
| S2OVL-5 | Applied: 1.5.4, 2.1, 4.1, 4.3, 4.4, 7.3, 8.3 (L3) |
| FXDISK-1 | Applied as written: `tools/sound/README.md` "The test disk `SOUNDS.hdv`", "Tests", and the "Effects (S4)" status line |
| FXDISK-2 | Applied: `make -f m11.mk` (all) builds `SOUNDS.SYSTEM` (`M11_HOST`); `all` already needed S2's objects |
| FXDISK-3 | Applied: 4.5's row 103 |

**Fixed between the parts.** Nothing broke between them: `fxdisk` uses
`s2-release.inc`, whose new `OVLW_RT0` constants change no byte of
`SOUNDS.SYSTEM` (the disk's SHA-1 is still `225f7d59`).

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 58 GB free; two lanes of `--jobs 2`, at most
4 jobs at once):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check`, `--report` | passes; `OVLW` `$6800-$9BFF`, 5,500 of 13,312 B budgeted, bank 93 |
| `make -C src/native -f m11.mk all`, `sizes` | no warning, no error; `ovlw` 6,115 B stored (`$6800-$7FE2`), own 4,919 of 5,500, the S2 segments 4,922 of 11,264 below `$9400`; the other images as in 8.10 |
| `python3 tools/sound/fxdisk.py --check`, `--planted` (2 s, 3 s) | every check ok (places, left, right, tuned, music, ntsc, quit, nonative); the four planted bugs caught; `build/sound/SOUNDS.hdv` 143,360 B, SHA-1 `225f7d59` |
| `python3 tools/native/s2ovl.py --capture`, `--all --jobs 2` (3 s, 4 min 2 s) | `report.json` ok: 102 runs (51 frames and variants), 0 with problems, 180,896 `K_OVL` records compared in 86 overlay runs; the five planted bugs caught (7 of 8 runs each); `s2_ovl` 1,214 of 4,500 B, `s2_amline` 3,708 B, `OVLW` 6,115 of 13,312 B; timing `f121` median: the whole overlay frame 233.3 ms, `OVLW`'s load 1.52 ms and `am_ovl` 55.0 ms, the bucket pass 37.4, the replay 93.8 |
| `python3 tools/native/s2amap.py --capture`, `--all --jobs 2` (3 s, 2 min 28 s) | 63 frames, 415 calls, 0 problems; `report.json` ok; the four planted bugs caught |
| `python3 tools/native/s2cap.py --capture --jobs 2`, `--check --twice --two-run 3 --jobs 2` (27 s, 2 min 35 s) | 0 problems in every run |
| `python3 tools/native/s2menu1.py --all --jobs 2`, `s2menu2.py --all --jobs 2` (2 min 42 s, 2 min 50 s) | ok: 157 and 204 frame jobs, the 7 sessions chained, 0 problems; the planted bugs caught; `s2menu1` own 5,503 B |
| `python3 tools/native/s2stbar.py --capture --jobs 2`, `--all --jobs 2` (13 s, 16 min 23 s) | 0 problems: 9,978 tic cases, 5,204 drawer cases; the planted bugs caught |
| `python3 tools/native/s2hud.py --all --jobs 2`, `s2wi.py --all --jobs 2`, `s2pal.py --all --jobs 2`, `s2fin.py --capture`, `--all --jobs 2` | `report.json` ok for each, `s2pal` "checkpoint passes: 0 problems"; the planted bugs caught. `s2wi`'s batch failure of 8.10 did not recur |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2`; `plinput.py --checkpoint --jobs 2`, `--no-build --planted --jobs 2` | 0 problems (PAL 34.9544, NTSC 34.9633 tics/s); the planted bugs caught |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2`, `--planted --jobs 2`, `--timing`; `python3 tools/native/fxcap.py --check --jobs 2`, `--planted --jobs 2` | 0 problems; `FXCODE` 983 of 1,019 B, `fx_service` 396 of 400 B; 134 eviction cases, 10,000 random sequences (35,041 calls), 0 failed; the planted bugs caught |
| `python3 tools/native/s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check`, `python3 tools/native/s2drawcase.py` (and `--timing`), `s2run.py --profile f121` / `fastpath` / `--fill 5a`, `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | OK; 0 problems; 0 stray writes; up to date |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the nineteen wip modules | 86 modules, 1,699 tests, 0 failures, 0 errors, 0 skipped, 557.2 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |
| `wip_test_m11_s2ovl`'s 7 tests without a build, `wip_test_m11_s2lay` and `wip_test_m11_fxdisk` on Python 3.9.6 with `PYTHONWARNINGS=error::ResourceWarning` | 45 tests OK |

`build/native/m11` is 121 MB.

**Open after wave 7.** `s2ovl`'s open problems (`s2ovl.md` 8): the
overlay's cost with the computer map (233 ms a frame `f121` against 98
without it; levers: the vertex cache, a cheaper `am_plot`, L3 in the
replay), no frame measured with the seen lines only, `titleBand` reached
by injected state only, no modelled or early flush, no `PL_AMPALS` stop,
no int16 fallback of the fast path in E1M1. `fxdisk`'s (`fxdisk.md` 7):
nothing heard on the card yet (milestone 12), ProDOS's restart after the
quit untested, one effect at a time on the disk. For the frame driver
(`design.md` R7 item 2): `OVLW`'s load and call, and `VIEWBOT` 160 in an
overlay frame. Wave 6's open items stand. `MILESTONES.md` row 11 is not
updated here (milestone 10's team edits that file now; the final
integrator).

### 8.12 Wave 8 as integrated (2026-10-02)

Part `plboot` (its notes: `docs/m11-parts/plboot.md`, with a section on
the integration). The requests:

| Request | Outcome |
| --- | --- |
| PLBOOT-1 (`PL_DISK`) | Applied as written: `s2layout.PL['DISK']` `$C7`, `PL_DISK` in `s2.inc` (4.2); the stand-ins in `pl_boot.s` and `pldisk.py` went. `s2layout.check()` now fails when two stops of `PL`, `S2S` and `llayout.LS` share a code |
| PLBOOT-2 (the songs' directory) | Applied: `s2layout.SONG_DIR` (100 `$0200`), `SONG_DIR_ENTRY` 3 and `SONG_COUNT` 13; `SONG_DIR_BANK`, `SONG_DIR`, `SONG_DIR_ENTRY` in `s2.inc`; `check()` keeps the directory in a song bank's room; `pldisk.py` reads them (4.5) |
| PLBOOT-3 | Recorded in `design.md` R7 item 14 (the release's 2D and tic images replace `pldisk.IMAGE_BUILDS`; a relinked release card replaces `rcard`'s parts) |
| PLBOOT-4 | Applied: 4.4's row `$F505-$F8FF` (`fxpt` named as the one image linked the other way, never a release image) |
| PLBOOT-5 | Applied: 2.5, 4.4 (`$FF00-$FF07`), 4.5 (rows 100-102, 103 and 48, 116-122), 6.5 |
| PLBOOT-6 | Recorded in `design.md` R2 item 6 for the final integrator (`MEMORY_MAP.md` is milestone 10's to edit now) |
| PLBOOT-7 (the static PRIVATE tables) | Open, a design gap: `design.md` R7 item 15 for the second half; the boot does not load them (2.5) |
| PLBOOT-8 | Recorded in `design.md` R9 for the final integrator (`LEVELS.md` 1.7); 4.5, 8.4 |

`plboot.mk` adds `DOOM.SYSTEM`'s link to `IMAGES`, so `make -f m11.mk`
links it with the rest. Every image of `build/native/m11` (176 maps,
labels, size tables and binaries) relinked to the same bytes after the new
constants, and `DOOM.hdv` is the same disk (SHA-1 `990174f8`).

**Fixed between the parts.** `s2fin.py --all` failed once in this
integration (`injected A5 finale/f001950: the run ended stop, status
$80`), and a rerun of its `fastpath` injected check ended with a file over
the 64 MB bound; a rerun alone passed. The cause is in the harness, not
the 6502 code: `s2fin.py`'s and `s2wi.py`'s `store_records` published the
2D store's cache as an empty list and then filled it, so a job thread that
came second while the first was still reading `GFX.n` ran with part of the
store (a race measured on the real files: 172 of 200 trials of two threads
saw a partial store). That is also wave 6's unexplained `s2wi` batch
failure (8.10), which had the same stop. Both build the list whole now and
publish it in one assignment, as do `s2state.py`'s `offsets`,
`gfx_handles` and `msgid_of` caches; a test in each part
(`test_the_store_is_never_seen_half_read`, three threads with a slowed
reader) fails on the old code and passes on the new.

The checkpoints, rerun together after the changes (from `demos/doom_gs`;
`df -h /System/Volumes/Data` 57 GB free; two lanes of `--jobs 2`, at most
4 jobs at once; milestone 10's team ran jobs at the same time, so the
times are about 1.5 times wave 7's):

| Command | Result [M] |
| --- | --- |
| `python3 tools/native/s2layout.py --check`, `--report` | passes; the images as in 8.11 |
| `make -C src/native -f m11.mk all -j4`, `sizes` | no warning, no error; every image the same bytes as before (the test images' glue rows `OVER BUDGET` as in 8.9-8.11) |
| `make -C src/native -f m11.mk part P=plboot`; `python3 tools/native/pldisk.py --check --planted --jobs 2` (29 s) | `DOOM.hdv` 3,939,840 B, 10 bank files, 160 segments, 3,819,356 B, `CRCLIST` 162 entries; `pl_boot.s` 2,042 of 2,048 B, the boot 2,941 of 4,096, `FXCODE` 983 of 1,019, `pl_ready` 8 of 250; `boot-f121` 5,843.0 ms, `boot-fastpath` 5,323.8, `boot-ntsc` 5,819.8, `nomusic`, `nomouse`, `banks`, `noamem`: 0 problems each; the five planted bugs caught |
| `python3 tools/native/s2ovl.py --capture`, `--all --jobs 2` (5 s, 6 min 37 s) | `report.json` ok: 102 runs, 0 with problems, 180,896 `K_OVL` records; the planted bugs caught |
| `python3 tools/native/s2amap.py --capture`, `--all --jobs 2` (5 s, 3 min 58 s) | 63 frames, 415 calls, 0 problems; `report.json` ok |
| `python3 tools/native/s2cap.py --capture --jobs 2`, `--check --twice --two-run 3 --jobs 2` (44 s, 5 min 4 s) | 0 problems in every run |
| `python3 tools/native/s2menu1.py --all --jobs 2`, `s2menu2.py --all --jobs 2` (4 min 25 s, 4 min 43 s) | 0 problems; the planted bugs caught |
| `python3 tools/native/s2stbar.py --capture --jobs 2`, `--all --jobs 2` (24 s, 27 min) | 0 problems: 9,978 tic cases, 5,204 drawer cases; the planted bugs caught |
| `python3 tools/native/s2hud.py --all --jobs 2`, `s2wi.py --all --jobs 2`, `s2pal.py --all --jobs 2` | `report.json` ok for `s2hud` and `s2wi`, `s2pal` "checkpoint passes: 0 problems"; the planted bugs caught |
| `python3 tools/native/s2fin.py --capture`, `--all --jobs 2` (11 s, 2 min 35 s) | after the fix above: `report.json` ok; the three planted bugs caught |
| `python3 tools/native/plclock.py --model`, `--checkpoint --jobs 2`; `plinput.py --checkpoint --jobs 2`, `--no-build --planted --jobs 2` | 0 problems (PAL 34.9544, NTSC 34.9633 tics/s); the planted bugs caught |
| `python3 tools/sound/fxrun65.py --checkpoint --jobs 2`, `--planted --jobs 2`, `--timing`; `python3 tools/native/fxcap.py --check --jobs 2`, `--planted --jobs 2` | 0 problems; the planted bugs caught; `fx_service` 19.0 / 89.7 / 130.2 µs; 134 eviction cases, 10,000 random sequences, 0 failed |
| `python3 tools/sound/fxdisk.py --check`, `--planted` | every check ok; the four planted bugs caught |
| `python3 tools/native/s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check`, `python3 tools/native/s2drawcase.py` (and `--timing`), `s2run.py --profile f121` / `fastpath` / `--fill 5a`, `make -f src/native/m11/fxconv.mk fxconv fxconv-renders` | OK; 0 problems; 0 stray writes; up to date |
| `python3 tools/testpar.py --jobs 4` every `tests/test_*.py` but milestone 10's `test_native_game_*`, and the twenty wip modules | 87 modules, 1,713 tests, 0 failures, 0 errors, 0 skipped, 809.9 s; `tests/test_sound_*` unchanged and green (7 modules, 152 tests) |
| `wip_test_m11_plboot`'s 8 tests without a build, `wip_test_m11_s2fin`'s and `wip_test_m11_s2wi`'s hand-made tests on Python 3.9.6 with `PYTHONWARNINGS=error::ResourceWarning` | 20 tests OK |

`build/native/m11` is 127 MB.

**Open after wave 8.** PLBOOT-7: the static tables of `MEMORY_MAP.md`
3.2 and 5 are not loaded by anything in the game yet, so the renderer
cannot draw from `DOOM.hdv`'s booted state alone (`design.md` R7 item
15). The code library's 2D images are the parts' test images (`P2DW`
without the HUD) and milestone 10's tic images are not on the disk
(PLBOOT-3, R7 item 14). The card's bank 1, bank 2 and `$F900-$FEFF` are
milestone 8's `rcard` link's. `DOOM.hdv` has not run on the card: the
ProDOS read of 3.9 MB (12-35 s [A]) is milestone 12's; the model's boot is
5.8 s `f121`, 4.3 s of it the CRCs. `fxpt` must not become a release
image (PLBOOT-4). The acceptance (8.2), the renaming of the wip tests and
the report (8.3) are the final integration's. Wave 6's and 7's open items
stand.

### 8.13 The first half as integrated: acceptance (2026-10-02)

The final integration of waves 1-8: the stand-ins replaced, every image
linked, the acceptance of 8.2 run, the wip tests renamed, the documents
of 8.4 updated. No milestone 10 file was edited; milestone 10's team ran
jobs at the same time (at most 4 of ours, niced).

**Stand-ins.**

| Stand-in | Outcome |
| --- | --- |
| `src/native/pl_fxstub.s` (`fx_step`, `fx_burst` doing nothing) | **Replaced and deleted.** `plclock`'s images (`plct`, `music/`, `bridge/`) and `plinput`'s `plit` link part fxplay's `fx-card.o` before `pl_irq.o` (PLBOOT-4's order); the test glue (`pl_ct.s`, `pl_bt.s`, `pl_it.s`) calls `fx_init` with the native answer, and `plclock.py`'s music run starts with the effects on and none playing (`FX_ON` 1, `FX_INVAL` 1), the release's state. The 13 songs' AY logs stay S2's byte for byte through the real `fx_step`/`fx_burst` |
| `src/native/s2_beginstub.s` (`s2_begin` writing an SCB pattern) | **Replaced** in `s2stbar`'s `s2sb` (the `P2DW` of `DOOM.hdv`) and `s2hud`'s `s2ht` by part s2pal's `s2_pal.o`; in both the frame's `s2_begun` is set, so `s2_begin` never runs there, and their write logs now give it an empty allowed set (0 stray writes: it wrote nothing). **Kept** in part s2draw's `s2dt` and `s2pt` as `s2_publish`'s unit-test double (relabelled: its stores are what that test predicts); `s2_publish` with the real `s2_begin` is part s2pal's `s2pp` checkpoint, on every frame's write log |
| s2wi's `wi` state | None existed: `s2_wi.s` reads milestone 10's `lgame.inc` (s2wi.md 1.1) |
| `s2t_pos` (table-driven), `hutick` (`s2_hut.s`), `IIGS_MouseUp` (`s2_menut.s`), `fxc_scr` at `$BEE0` (FXCHAN-4), `pldisk.IMAGE_BUILDS` | **Stay**: milestone 10's interfaces (R4, R5) and the second half's (R7 items 14, PLINPUT open problem 2) |
| Stale `STANDIN` comments (`s2_mvid.s`, `s2menu1.py`) | Corrected: those places have been `s2layout`'s since wave 5 |

**`P2DW` linked whole.** No part linked 4.1's `P2DW` column together
(`s2sb` has no HUD, `s2ht` no status bar). The new fragment
`src/native/m11/s2int.mk` links `build/native/m11/s2int/p2dwl` from
`s2_st`, `s2_hu`, `s2_draw`, `s2_pub`, `s2_pal`, `pl_poll`, `fx_service`
and a link-only glue `src/native/s2_p2dwl.s` (`P2DW`'s places and the
table of R7 item 7's calls; the frame glue `s2_frame` stays the second
half's): **6,093 of 7,424 B**, own 3,291 of 3,900 (`s2_st` 1,860,
`s2_hu` 1,411), every row within its budget; 1,331 B left for the frame
glue. Risk 12's fallbacks were not needed for any image.

**Requests.** R1 (`NATIVE.md` 10's clock row) applied: milestone 10 has
not edited `NATIVE.md`. R2 items 1-6 and R3 applied to `MEMORY_MAP.md`
(sections 2, 3.1, 3.3, 3.5, 4.2, 5, 11 and a new section 18 after
milestone 10's 17): `git diff` shows milestone 10's edits only in 3.3's
note under the table and its section 17, none on these lines. R4-R8 stay
with milestone 10 and its frame driver (`design.md`); R9 (`LEVELS.md`
1.7) with the final integrator; lever L5 with milestone 8's integrator.

**The acceptance (8.2)**, rerun together from `demos/doom_gs`
(`df -h /System/Volumes/Data` 57-73 GB free; at most 4 jobs):

| # | Command | Result [M] |
| --: | --- | --- |
| 1 | `s2stbar.py --all --jobs 2` (21 min) | 0 problems: 5,204 drawer cases and 9,978 tic cases from both fills, 400 runs, stack 21 B, 0 stray; chained over demo3's 534 frames (34 runs, 0 stray); the coverage table complete; the six planted bugs caught |
| 1 | `s2hud.py --all --jobs 2` | 794 frames of demo3, newgame, menus, automap and 64 synthetic tics, 0 problems; every level frame's `message_on` and `VIEWTOP` equal at `PV` (534, 129, 41, 30); the seven planted bugs caught |
| 1 | `s2pal.py --all --jobs 2` | "checkpoint passes: 0 problems": 1,652 frames' SCBs and palettes, the wipe's two steps on 63 new pictures, the publish order on every write log, `TINTPAL` and the nibble tables; the planted bugs caught |
| 1 | `s2cap.py --capture`, `--check --twice --two-run 3` | the eleven runs captured twice the same, 0 problems, 0 unfit values |
| 1 | `s2menu1.py --all`, `s2menu2.py --all` | ok: 157 and 204 frame jobs (13,346,496 bytes compared in s2menu2's), the 7 sessions chained, 283 responder and 863 ticker calls, 0 problems; the five and four planted bugs caught |
| 1 | `s2amap.py --capture`, `--all` | 63 frames, 415 calls chained and injected, 0 problems, 0 stray; the four planted bugs caught |
| 1 | `s2ovl.py --capture`, `--all` | 102 runs, 0 with problems, 180,896 `K_OVL` records; the five planted bugs caught |
| 1 | `s2wi.py --all`, `s2fin.py --capture`, `--all` | `report.json` ok: 214 intermission frames; the finale's, pages', signs' cases, X3 3 frames; the planted bugs caught |
| 1 | `s2drawcase.py` (and `--timing`), `s2data.py --check --report`, `make -f src/native/m11/s2data.mk s2data-check`, `s2run.py --profile f121`/`fastpath`/`--fill 5a` | 2,483 synthetic and 65 captured cases, model and native 0 problems; the store OK (sources, places, read-back, include); 0 stray writes |
| 2 | `plclock.py --model`, `--checkpoint --jobs 2` | PAL 34.9544, NTSC 34.9633 tics a second (the model's tics at every VBL); idle interrupt 6.09 µs worst; music through `pl_vbl` with the real effect player: 13 songs equal to S2's, worst 1,547.9 µs; the bridge ok; stack 16 B |
| 3 | `plinput.py --checkpoint --jobs 2`, `--no-build --planted` | 55 sequences, 220 runs, 3,988 polls, 3,690 events equal to `plmodel.py`'s; the eight planted bugs caught |
| 4 | `make ... part P=plboot`; `pldisk.py --check --planted --jobs 2` | `DOOM.hdv` 3,940,864 B (SHA-1 `7382b170`: `s2sb` now carries the real `s2_pal`), every CRC equal, ready, `boot-f121` 5,843.0 ms, `boot-fastpath` 5,323.8, `boot-ntsc` 5,819.8, the four stops' messages; the five planted bugs caught |
| 5 | `fxrun65.py --checkpoint`, `--planted`, `--timing`, `--cost`; `fxconv` (`make ... fxconv fxconv-renders` up to date) | every effect alone and over each song equal to the models; no effect: S2's log byte for byte (13 songs); the hold across `fx_song` (5 VBLs landed in it); `--phasor-mb-only` no chip-3 write; worst interrupt 2,047.9 µs; the eight planted bugs caught |
| 5 | `fxcap.py --check`, `--planted` | demo3 1,218, DEMO1 2,290, DEMO2 1,273, tour 137 calls and the menu's 709 equal, `S_UpdateSounds` included; 134 eviction cases, every path covered; 10,000 random sequences (35,041 calls) equal to the model; the seven planted bugs caught |
| 6 | `fxdisk.py --check`, `--planted` | `build/sound/SOUNDS.hdv` (SHA-1 `225f7d59`, unchanged): places, left, right, tuned, music, ntsc, quit, nonative ok; the four planted bugs caught |
| | `s2layout.py --check`, `make -C src/native -f m11.mk all sizes` | passes against `rlayout.py`, `llayout.py`, `glayout.py`; no warning; every release image within its room (4.1) |

Every part's notes record each planted bug caught, and every rerun above
caught them again.

**The wip tests renamed** `tests/test_m11_<part>.py` (20 modules) with
`mv`, their own references and the makefiles' comments updated. The first
full run then failed one test, `test_testpar`'s guard
`test_every_shared_writer_is_listed`: `test_m11_s2menu1`, `s2menu2` and
`s2ovl` call `title.build_machine()` and `title.ensure_image()` and were
not among the writers of the prebuild steps `ref816 machine` and `ref816
image` (a wip module is never scheduled with the others, so it had not
applied). `tools/testpar.py`'s `REF816_USERS` now names them (a line of
its own: milestone 10's edits there are on the steps' lines), and the
full suite, `python3 tools/testpar.py --jobs 4` with every
`tests/test_*.py` but milestone 10's `test_native_game_*`: **87 modules,
1,713 tests, 0 failures, 0 errors, 0 skipped**, 612.2 s;
`tests/test_sound_*` unchanged and green (7 modules, 152 tests); the 20
`test_m11_*` modules 287 tests.

**Timing** is 8.14's, the report of 8.3 (it was to be
`build/native/m11/report.md`; this integration's session could not write
that file, so the report is kept here and each figure's source is its
part's `build/native/m11/<part>/report.json`); in short, `f121`:
a level frame's `P2DW` with nothing changed about 2.8 ms (its load 1.90),
a status bar refresh 44.1 ms, a fresh HUD line 15-22 ms, a menu open 137
ms, a full-map frame 13.2 ms median and 62.7 worst, an intermission frame
81 ms median, a finale text frame 68 ms median; the IRQ's cost on D_E1M1
in the Doom profile 5.99 ms a second alone, 16.24 with effects at demo3's
start rate, worst interrupt 2,047.9 µs. **Levers** L1-L5 measured, none
taken (8.14).

### 8.14 The report (8.3), 2026-10-02

a2vm's cost model under `--cost-timed` (the card's runs are milestone
12's); ms median / p99 / worst over each part's cases, each alone in cost
phase 30; "[A]" is arithmetic on part s2draw's measured 0.991 µs a
published byte. Sources: the parts' `report.json` of the reruns above.

**The images' loads** (`far_pload` of the stored pages with `MATHW`, 0.245
µs a byte; `f121` / `fastpath` ms): `P2DW` (all of 4.1's objects, 30
pages) 1.90 / 1.78; `MENUW` (52) 3.29 / 3.09; `AMAPW` (34) 2.16 / 2.02;
`WIW` (26) 1.66 / 1.55; `FINW` (28) 1.78 / 1.67; `PALW` (10) 0.65 / 0.60;
`OVLW` (24) 1.52 / 1.42.

**`P2DW`'s parts:**

| Frame | n | `f121` | `fastpath` | Nibble tables |
| --- | ---: | --- | --- | ---: |
| Status bar: nothing changed | 6 | 0.06 | 0.06 | 0 |
| Status bar: the face changed | 6 | 6.52 / 6.54 | 5.05 / 5.06 | 8 |
| Status bar: other widgets | 6 | 8.00 / 11.21 | 6.08 / 8.69 | 5-8 |
| Status bar: a full refresh | 6 | 44.10 | 35.10 | 8 |
| HUD: nothing to draw | 764 | 0.022 / 0.036 / 0.036 | 0.022 / 0.036 / 0.036 | 0 |
| HUD: a cached line replayed (1,600 B: 1.6 ms of drain [A]) | 6 | 3.84 / 3.84 / 3.84 | 3.51 / 3.52 / 3.52 | 0 |
| HUD: a line drawn afresh | 24 | 15.17 / 22.02 / 22.02 | 12.08 / 17.42 / 17.42 | 1 |
| Palettes: nothing (`PALST`'s fetch and write-back) | 1,458 | 0.71 | 0.49 / 0.50 / 0.50 | |
| Palettes: the SCBs; a `TINTPAL` row | 8; 123 | 0.92 / 0.95; 1.27 / 1.48 | 0.70 / 0.73; 1.02 / 1.22 | |
| Palettes: a wipe | 63 | 1.93 / 16.43 / 16.43 | 1.71 / 12.71 / 12.71 | 16 when new |
| Input poll (part plinput) | 3,988 | 0.043 / 0.052 / 0.055 | 0.043 / 0.052 / 0.055 | |
| `fx_service` at 50 frames a second; at 6.3 (part fxplay, µs) | 1,001; 126 | 19.0 / 89.7 / 130.2; 58.2 / 189.7 / 191.1 | 13.1 / 59.2 / 87.2; 42.8 / 125.6 / 129.0 | |

A level frame with nothing changed: about 2.8 ms of `P2DW` on `f121`
(the load 1.90, the palettes 0.71, the rest 0.2).

**The mode images:**

| Frame | n | `f121` | `fastpath` |
| --- | ---: | --- | --- |
| Menu open (the 32 KB save 17.6 / 14.3 in a2vm's model of the memory API, the gray tables 1.2) | 7 | 137.0 / 137.7 / 137.7 | 117.9 / 118.4 / 118.4 |
| Menu page redrawn whole (about 31.7 ms of drain [A]) | 18 | 93.2 / 137.3 / 137.3 | 82.4 / 115.4 / 115.4 |
| Menu skull frame | 125 | 3.19 / 4.36 / 4.37 | 2.64 / 3.75 / 3.76 |
| Menu close (the restore) | 7 | 46.9 | 43.5 |
| Load, save page whole; key setup whole | 1, 1; 4 | 163.7, 160.8; 124.6 / 127.2 | 137.6, 134.6; 108.0 / 109.9 |
| Full map, the lists (drain 0.58 median, 3.09 worst) | 60 | 13.23 / 62.65 / 62.65 | 11.76 / 56.72 / 56.72 |
| Full map, a redraw (drain 26.64) | 2 | 38.67 | 37.24 |
| Overlay: `am_ovl` with the computer map | 21 | 55.0 / 59.7 / 59.7 | 49.6 / 54.2 / 54.2 |
| Overlay: the whole frame; its replay against a plain frame's | 21 | 233.3 / 258.9; 93.8 against 40.0 | 164.9 / 185.0; 41.3 against 37.7 |
| Intermission (32,512 B a frame: 32.2 ms of drain [A]) | 214 | 81.10 / 102.85 / 104.12 | 69.65 / 86.68 / 87.69 |
| Finale text frame | 35 | 67.87 / 174.02 / 174.02 | 62.27 / 143.70 / 143.70 |
| `HELP2`; the title page's first frame; `F_LoadScreen` | 27; 3; 1 | 46.28; 62.01; 68.32 | 42.66; 54.90; 62.68 |
| `bmSignOn`; `bmSignOff` | 4; 4 | 17.11 / 18.71; 5.49 | 14.05 / 15.26; 5.08 |
| `PALW`: a level, a gamma change, a picture (worst) | 27, 8, 19 | 22.2, 12.4, 14.7 | 18.0, 10.7, 11.0 |

**Tic-side modules** (µs a call, `f121` / `fastpath`): `st_ticker` 16.7 /
10.3 (61.0 / 48.1 with the turned head); `hu_ticker`, `hu_start` 1 / 1
(worst 2); `f_ticker`, `f_start` 2.36 / 2.34 (worst 2.95); `sc_start`
44.3 / 39.8 (3 channels; `FXCH8` on demo3 62.0 / 56.2), `sc_start2` 77.3
/ 68.3, `sc_stop` 5.2 / 5.2, `sc_update` 80.3 / 70.6; `am_tick` 128.2 /
86.1 (worst 210.9 / 165.9), `am_responder` 109.6 / 72.1 (worst, `AM_Start`,
8,943.5 / 7,421.2).

**The IRQ.** The clock's idle interrupt 5.88 µs (worst 6.09); the music
through `pl_vbl` with the effect player on and idle, worst 1,547.9 µs
(`D_INTRO`; S2 alone 1,543.8). On D_E1M1, ms a second taken from the
main loop (in the interrupts, tail), and the worst interrupt
(`tools/sound/fxrun65.py --cost`, 20 s):

| Setting | Music alone | Effects at demo3's start rate (132 starts) | Three started together every 45 VBLs | Worst interrupt: alone, demo3's rate, three |
| --- | --- | --- | --- | --- |
| window 512 | 17.73 (6.39, 11.34) | 38.56 (15.03, 23.53) | 35.91 (13.96, 21.95) | 1,035.7, 1,114.5, 1,519.2 µs |
| window 32 (the Doom profile) | 5.99 (5.76, 0.22) | 16.24 (14.75, 1.49) | 14.80 (13.66, 1.14) | 1,017.2, 1,111.5, 1,516.2 µs |
| FW-S1 | 3.17 (3.04, 0.14) | 7.49 (6.08, 1.41) | 6.80 (5.74, 1.06) | 293.1, 339.0, 424.7 µs |

A burst where only the effects write pays an **extra tail of 529 µs
(window 512), 42 µs (window 32 and FW-S1)**; one that shares the music's
pays none (24.2 of the 48.6 a second with three effects). The worst
interrupt of all: three effects starting on `D_INTRO`'s first chord,
**2,047.9 µs** (window 512: 2,050.8); stack 16 B of 24.

**Sizes.** Every release image within its room and its rows (4.1;
`P2DW` 6,093 of 7,424 B as linked whole); only the parts' test images'
glue passes an own budget (`s2at`, `s2ft`, `s2wt`). Tic side: `s2t_st`
888 of 900, `s2t_hu` 100 of 150, `s2t_fin` 175 of 250, `fx_chan` 1,085 of
1,100. The card: `$F505-$F8FF` 983 of 1,019 B; the tic-side block 61 of
61; the channels 50 of 64; `pl_ready` 8 of 250. The banks as 4.5 (the
store 296,665 B, budget met; spare 1-3, 125, 126).

**Exclusions and differences:** X1 the view's rows in every level frame
of the status bar's (5,204 cases) and the HUD's (794 frames) checks, with
`VIEWTOP` equal at all 734 `PV` points; X2 9 result frames, 34,560 bytes
(22,248 not black in the reference); X3 9 frames (s2pal), 3 (s2fin); X4 0
of the captured calls, 4 of the 134 eviction cases; D1 40 frames with
`I_ApplyColors` stores, final screens equal; also X-M2 (9 frames in
s2menu1, every page compared in s2menu2's run A), X-K (4 frames) and 3
HUD frames under the menu.

**Levers, measured, none taken:** L1 the whole `P2DW` load is 1.90 ms
(0.063 a page), under 3% of a 64-164 ms frame; L2 a status bar refresh
44.1 ms once a level, a face 6.5 ms, a pixel 4.17 µs: for the performance
pass; L3 the overlay's replay 93.8 against 40.0 ms `f121`: milestone 5/8's
replay, for the performance pass; L4 a ring holds 300 ms and every 300 ms
of every script fits, demo3's worst render frame is 164 ms: no frame runs
dry; L5 D1's 40 frames show the strip's colours at most one replay late:
the owner's call at milestone 12, a request to milestone 8's integrator
if taken.

### 8.15 The review's defects, applied (2026-10-02)

A verification of the first half gave five defects. Each was checked
against the tree and a scratch copy before it was fixed; none was
rejected.

| # | Defect | Verdict | What changed |
| --: | --- | --- | --- |
| 1 | `make -C src/native -f m11.mk all -j4` (the command of `src/native/README.md`) stops from an empty `build/native/m11`: `s2data.json` and `s2data.inc` had no rule, so s2fin's stand-in asked for `part P=s2data` and s2stbar's, s2wi's and s2int's objects had no rule for the include | Confirmed in a scratch copy, with and without `-j` [M] | `m11/s2data.mk` names both files as made by the store's run (`GFX.1`; the tool writes them after the bank files) and sets `M11_S2DATA_JSON_RULE`, so the stand-ins of s2fin, s2hud, s2menu1 and s2menu2 (read after it in sorted order) stay out of `all`; they still answer in `part P=NAME`. `S2DATA_OUT` follows `M11` when it is set, the directory the other parts read. The objects of s2stbar, s2wi and s2int already listed `s2data.inc`. From an empty `M11`: `all` with and without `-j4` and `sizes` pass with no warning, a second `all` makes nothing, and the 283 images, includes, size tables and store files equal the shared build's byte for byte [M] |
| 2 | About 0.2 GB of abandoned `tmp-*` directories of a stopped milestone 11 run in `build/` (dated 06:07) | Confirmed: 12 directories, none changed since 06:07 and none open by a process [M] | Deleted by name; `build/native/m11` 323 MB to 122 MB. Not changed: `tools/testpar.py` (see the open item below) |
| 3 | Every make relinks `ovf`, `ovfp`, `OVLW` and `OVLWP` (their maps depended on the phony `s2ovl_render`) | Confirmed [M] | The maps depend on milestone 8's object files, which depend on `s2ovl_render` with an empty recipe (make reads their times again after render.mk's make); OVLW's link map is made through a stamp, since `s2ovl.py --ovlw-cfg` writes only a changed map. A second make links nothing; a render object made again relinks the frame and, for `rrec-m.o` or `bucket.o`, OVLW; a missing `ovlw.cfg` is made again [M]. `s2ovl.py`'s planted link map (bug 4) still relinks: it is newer than the stamp |
| 4 | `s2stbar.py --native` and `--chain` exit 0 when they report problems | Confirmed by reading `main()` (`return 0` after every mode but `--all`) | Every check mode (`--capture`, `--model`, `--native`, `--tics`, `--synth`, `--chain`, `--plants`) now exits 1 when it reports a problem or a planted bug is not caught; `--all` unchanged |
| 5 | `MEMORY_MAP.md` 4.2 marks the effect voices `$E413-$E442` [A] though built, section 18's card row leaves them out; row 3 of section 10 gives the input block as `$03B2-$03ED` | Confirmed; also the rings `$E740-$E8BF` are still [A] | `docs/m11-parts/design.md` R2 item 7 for the integrator (MEMORY_MAP.md is shared with milestone 10); section 10's row 3 notes wave 1's `$03B3-$03ED` |

Tests: `tests/wip_test_m11_build.py` (8 tests, about 6 s): a dry run of
`all` into an empty `M11`, serial and `-j4` (the store made once, before
its four readers; nothing written); part s2ovl built twice into a
scratch `M11` (the second links nothing), a render object and
`ovlw.cfg` made again (relinked); `s2stbar.py`'s modes with stand-in
checks (1 with a problem, 0 without). All 8 fail on the files before the
fixes [M]. After them: `make -f m11.mk all -j4` and `sizes` in the tree
with no warning (`WIW`'s test image `s2wt` still prints its documented
`OVER BUDGET` glue row), `s2layout.py --check` passes, and the suite
without milestone 10's `test_native_game_*` modules (in progress) plus
the new module: 88 modules, 1,721 tests, 0 failures, 0 skipped (763.6 s
with 4 jobs), the 20 `test_m11_*` acceptance modules among them.

**Open:** `tools/testpar.py` kills a module that passes its time with
`SIGKILL`, so a tool's `finally` cleanup of its `tmp-*` directory does
not run; removing a module's directories afterwards needs to know which
are its own (modules run in parallel in one `build/`), so it is left to
the owner of `testpar.py`. The m11 makefile's generated includes are
written only when they change (`s2layout.write_if_changed`), so after an
edit of a layout (milestone 10's `glayout.py`) every make runs the
generators again (about 56 short runs, nothing assembled or linked)
until an include changes.

## 9. Risks

| # | Risk | Effect | What the builders do |
| --: | --- | --- | --- |
| 1 | **Drain on F1.2.1 for full screens**: a menu's open and close, a picture, a wipe each publish about 32 KB, about 31.5 ms of drain [R `NATIVE.md` 8] | Slow menu and page changes | Measured (8.3); the static screen and the marks keep the menu's frames small, as upstream's |
| 2 | **`P2DW`'s load every level frame** (about 2.0 ms [A]) and its nibble tables (up to 8 × 0.25 ms when the whole status bar redraws) on top of the render | 1-3% of the frame | Lever L1, L2; the size and the fetches reported |
| 3 | **The 2D store's banks**: about 300 KB [M] in the free parts of the reserved banks plus one spare | A bank more (125) | Measured in wave 3: 296,665 B, no bank 125, 42,768 B of the free parts left (`s2data.md` 4, as integrated: SCREENS.md 8.7); the store can drop the `M_*` lumps the native menus never draw (benchmark, accelerators) |
| 4 | **Upstream's 2D assets from the release** (F5): the pictures and the `GS*` records are build artifacts | A release with other palettes would need its own | As milestone 9 did; the source is named in `s2data`; `s2data.py` names each lump's source (`s2data.json`), and `RELEASE_PATCHES` the patches the release changed |
| 5 | **Tic-side code in milestone 10's W** (4.7: about 1.9 KB) | Paging or a core too full | Request R4 with the measured sizes and call rates; the modules are small and called at most a few times a tic |
| 6 | **The effects' start latency and ring refills** at low frame rates (3) | A sound late by the render time; a long effect cut when a frame takes more than a ring's 300 ms | Reported; lever L4; the converter keeps every 300 ms within 128 B |
| 7 | **The channel logic's comparison needs injected state** (F3): 8 channels and the reference's DOC results | The release's 3-channel decisions are compared only with the model | The model equals the reference in the 8-channel build on every captured call |
| 8 | **The //e's one-key input** [R `NATIVE.md` 14 risk 11] | Movement stops when another key is pressed | The Apple keys and the mouse carry fire, use and strafe; ALWAYS RUN; the owner judges at milestone 12 |
| 9 | **State the tic changes and the frame draws** (the status bar's and the HUD's tickers, the channels): an order between a tic's events and the frame's drawing | A message, a face or a sound a tic off | The tickers are tic-side and run at upstream's place in the tic (4.7); the channels' mailboxes keep the latest decision and `isPlaying` sees a pending start (3); `VIEWTOP` compared every frame; the two-tic sound case |
| 10 | **The menu's gray conversion cost**: 32 KB through `UI_GRAY` at the open | A slow open | Once an open, as upstream; measured |
| 11 | **Milestone 10's names change** while this half builds | Stand-ins out of date | Every interface through the generated includes; local stand-ins marked and listed in each part's notes |
| 12 | **The 2D images' code rooms** (4.1's size table, all [A]): `MENUW` 15.6 of 16.9 KB, `P2DW` 6.9 of 7.4 KB | An image over its room | The size check fails the build at once; then, in order: `P2DW`'s glue and texts to its state block's bank, the menu's strings fetched per page, a band row less, `S2CODE2` |

## Appendix A: the measurements made for this design

| What | Command (from `demos/doom_gs`) | Result |
| --- | --- | --- |
| Sound calls | `python3 tools/ref816/calls.py RUN "S_StartSound,entry=1,in=dp:_Dp:4+_g_gametic:4" "S_StartSound2,entry=1,in=dp:_Dp:4+_g_gametic:4" "S_StopSound,entry=1,in=dp:_Dp:4" "S_UpdateSounds,entry=1"` for RUN = DEMO3, DEMO1, DEMO2, tour, under `bounded.run` (25 min limit, 200 MB), 4 jobs | `S_StartSound`/`S_StartSound2`/`S_StopSound`: DEMO3 366/64/254, DEMO1 632/39/362, DEMO2 158/22/134, tour 23/0/1; starts in a tic at most 4; in 4 tics at most 7 (DEMO3), 6, 3; starts and stops in 4 tics at most 11, 12, 12. `S_UpdateSounds` shows 0: `musFrame` reaches it by `jmp` [R `s_sound65.s:1921`], which an entry log without `jumps=1` does not see |
| The effects by count | the logs above, `A` & `$7FFF` of each start | 36 distinct of 1,304: 0.1 F4's list |
| The release's 2D lumps | `umodel.Release()`'s directory, by name prefix | 0.1 F5 |
| The WAD's effect lumps | `tools/sound/mus.py`'s `Wad` on `DOOM1.WAD`; the game's sounds from `offsets.inc`'s `CONST_SFX_*` | 55 `DS*`, 55 `DP*`; all 52 game sounds have both; `DSBDOPN`, `DSBDCLS`, `DSITMBK` are not game sounds; the 52 `DS` lumps hold 515,136 samples, the longest 1.69 s; `DPPISTOL` 27 ticks |

The logs were in the session's scratch directory and are not kept.

## 10. Review

An adversarial review of this design (2026-10-01) gave 16 findings. Each
was checked against the sources before it was applied; the table says
what changed and, where a finding was not taken as written, why.

| # | Finding | Verdict | What changed |
| --: | --- | --- | --- |
| 1 | `sc_update` sees every start of the frame's tics as ended (the voice starts only at `fx_service`) | Taken: `S_UpdateSounds` frees channels whose `isPlaying` is false [R `s_sound65.s:383-391`] | `isPlaying` is "voice active or a start pending" (3); the two-tic case |
| 2 | `message_on` is needed before the render | Taken [R `d_main65.s:467-474`, `:499-502`] | The HUD's ticker is tic-side (`s2t_hu.s`), the driver sets `VIEWTOP` (R5, R7); `HU_MAIL` dropped; X1 narrowed and `VIEWTOP` compared. **Not taken in full:** "compare rows 0-9 in every frame" cannot hold in a 2D test where the view drew those rows; they are compared whenever the strip is on, the HUD must leave them alone otherwise, and the `viewtop` comparison catches a late `message_on`. The colours' timing before the replay (`stripEarly`, `I_ApplyColors`), which the review did not raise, is a named difference D1 with lever L5 |
| 3 | The input block overlaps `GS_STATUS`, `GS_ARG` | Taken [R `glayout.py:147`] | `$03B2-$03ED` (since wave 1 `$03B3-$03ED`: `GS_ARG` is a word and ends at `$03B2`, request S2LAY-3), 15 events; a poll defers a key rather than drop one; `s2layout.check()` imports `glayout` |
| 4 | No sound path outside level frames | Taken [R `m_menu65.s:909-912`; `d_main65.s:231`, `:261-279`; `wi_stuff65.s:491-495`] | `fx_service` and `snd_refill` in every frame image, `fx_chan` in `MENUW` with cached positions. **Not taken:** linking them into `AMAPW`; a full-automap frame runs `P2DW` after `AMAPW`, as upstream draws the status bar and HUD there [R `d_main65.s:526-536`] |
| 5 | S2's song start rewrites chip 3; R7 unknown before the first song | Taken [R `player.s:1008`, `:1056-1101`] | `FX_INVAL`, set by `fx_song` and at boot. Also found: `reset_chips` bursts from the main loop with interrupts on, so an effect burst could tear its VIA-B sequence: `FX_HOLD` |
| 6 | The centre (separation 128) has no voice | Taken [R `s_sound65.s:221-235`, `:698-712`] | 128 and below took a left voice first. **Not taken:** alternating A and B for centred sounds (the player's weapon would jump sides). **The owner's answer (2026-10-02):** "I'll have one or 2 channels centered. No problem. How many should we center?", the Phasor assumed: one. Chip 3's pans in the Doom profile are A left 5, B right 11, C centre 8 (the menu's AY3 C, `phasor.pan.12=8`; 8 is the menu's one centred pan, both sides full [R `mockingboard.sv:316-343`, `config_menu_phasor.c:398-409`]); the music's chips keep the menu's pans. The voice choice: below 96 A first, 96 to 160 C, above 160 B, a busy voice to the nearest free one in pan (128 to the left) (`tools/sound/README.md` "Stereo by voice", one table `tables.FX_VOICES`). Two centred voices would leave one side without a voice |
| 7 | 12 requests have no margin | Taken | One mailbox a channel |
| 8 | Four images too small | Taken; the overlay producer measured at about 3.3 KB of 65816 [M: `build/linkmap.json`] | 4.1's size table; `OVLW` replaces `MASKW_AM`. **Not taken:** reloading `MASKW` for `nm_bkload`; `OVLW` carries `nm_bkload` and `BKFAR`/`BKFAR2` itself |
| 9 | The wipe's order contradicts upstream | Taken [R `i_viigs65.s:327-345`] | `s2_begin`, `s2_finish`; the order checked on the write log |
| 10 | Test drivers overlap the card blocks | Taken [R GAME.md 3.4; `glayout.game_cfg`] | `s2_drv` at `$F900-$FEFF`; per-build block addresses; `$EE00-$EE7F` in milestone 10's `M11` build (R4) |
| 11 | Acceptance gaps | Taken for the status bar, `S_UpdateSounds` and the eviction paths; the menu cursor, automap pixel and finale glyph need nothing, as the review says | `stbar.script` and the coverage table; `S_UpdateSounds` with `jumps=1`; `ref816 --call` eviction cases with path coverage |
| 12 | Palette table sizes | Taken [R `i_viigs65.s:47-57`, `:766-787`] | 8 slots in `P2DW`; `TINT_ROW` 384 B |
| 13 | Key names and table do not fit upstream's | Taken [R `m_menu65.s:252-253`, `:1369-1381`; `i_iigs65.s:83`] | Names of at most 7; 128 entries, pseudo-keys in the folded lower-case codes |
| 14 | Effects without native mode unspecified | Taken [R `probe.s:71`] | Off |
| 15 | The "no second tail" claim | Taken | `fx_step` before `snd_tick`, `fx_burst` right after the music's; the extra tail reported |
| 16 | Wrong citations | Taken | `wi` state; phase 31's overflow made checkable; the makefile fragments for `src/sound/fx.s` and `sounds.s` named (7.1) |
