# The playable game: the main loop, the kernel and the boot disk

`build/native/DOOM.hdv` is the whole game: the title loop with its music
and demo, the menus, episode 1, the status bar, the HUD, the automap, the
intermission, the finale, the music and the effects. This document
describes the main loop that ties the parts together, the kernel that runs
it, the images and their loads, the boot disk and the machines it runs on.
The last section is the owner's guide.

The parts it ties together: [`GAME.md`](GAME.md) (the tic image, the
groups, the load protocol, the hooks), [`SCREENS.md`](SCREENS.md) (the 2D
images, the platform, `DOOM.SYSTEM`), [`RENDER.md`](RENDER.md) and
[`RENDER-MASKED.md`](RENDER-MASKED.md) (the renderer),
[`LEVELS.md`](LEVELS.md) (the store and the load),
[`MEMORY_MAP.md`](MEMORY_MAP.md) (every place) and
[`SPEED.md`](SPEED.md) (where the time goes).

## 1. The pieces

| Piece | Files | Where it runs |
| --- | --- | --- |
| The kernel: a resident loop that runs step lists | `src/native/dl_kern.s` | Main card `$FF00-$FFF9` (`pl_ready`'s place); its menu loop in main `$0880-$08FF` and `$0B94-$0BFF` |
| The brain: D_DoomLoop's logic, tryRunTics, the events, the menu's requests | `src/native/dl_brain.s` | The tic image's group `DLG_B` (slot 2) |
| G_BuildTiccmd, buildNewTiccmds, P_SwitchWeapon, the weapon cycle, the benchmark's rows | `src/native/dl_cmd.s` | Group `DLG_C` (slot 1) |
| D_Display: the frame's step list, the other lists, the benchmark's timing | `src/native/dl_disp.s` | Group `DLG_D` (slot 1) |
| The hooks the game parts call (sounds, I_GetTime, AM_*, ST_*, HU_*, WI_*, F_*, D_PageTicker, D_AdvanceDemo) | `src/native/dl_hook.s` | The tic image's core and group `DLG_H` (slot 1); the HUD's ticker `s2t_hu.s` in the core |
| The songs, the title loop's D_DoAdvanceDemo, the renderer's boot and level state | `src/native/dl_snd.s` | Group `DLG_S` (slot 1), with `s2t_st.s` |
| P2DW's frame glue (poll, palettes, status bar, HUD) | `src/native/dl_p2d.s` | The `P2DW` image |
| DLINIT: the boot's PRIVATE copies and settings, SAVE SETTINGS's write, the quit's last screen | `src/native/dl_init.s` | W `$6600`, loaded from `DLBANK` |
| Layout, links, disk | `tools/native/playlayout.py`, `playlink.py`, `playdisk.py`, `src/native/play.mk`, `src/native/dl.inc` | host |

`play.mk` links the game parts' objects and generated layouts as their own
makefiles build them. How the whole disk is built is in
[`src/native/README.md`](../src/native/README.md).

## 2. A frame

Upstream's `D_DoomLoop` (`d_main65.s`) runs, each frame: the input, the
tics the clock gives (tryRunTics: `buildNewTiccmds`, then `G_Ticker` once
per tic), the sounds, and the display. Natively W (`$6000-$BFFF`) holds
one image at a time, so the frame is a sequence of phases, each with its
image in W:

| Phase | What | Image in W | Code |
| --- | --- | --- | --- |
| Input | `pl_poll` (keys, Apple keys, mouse) into the event queue; the effects' service and the music's ring | `P2DW` (`s2_poll`, and in each `s2_frame`) | `pl_input.s` |
| Events | `D_PostEvent`'s routing: ESC to the menu, the cheats, the automap's keys (`AMAPW`'s `am_responder`), `G_Responder` (title: any key opens the menu; in a level `gamekeydown`) | the tic image; `AMAPW` or `MENUW` for their responders | `dl_brain.s` (`b_events`) |
| Tics by the clock | `buildNewTiccmds` (a command per new tic, at most `MAXTICS` (4) ahead), then `G_Ticker` per command; the load protocol when a tic loads a level | the tic image (W, core, two group slots, the frame slots) | `dl_brain.s`, `dl_cmd.s`, the game parts |
| Sound | `S_UpdateSounds` (the positional effects), the songs | the tic image; the player in the card | `dl_hook.s`, `dl_snd.s` |
| Render: front end | BSP walk, walls, planes, records (`nr_frame`) | `WCODE` (bank 112) and the level's W tables | [`RENDER.md`](RENDER.md) |
| Render: masked | sprites, masked walls, the weapon (`nm_masked`, `nm_bkload`) | `MCODE` (bank 113) | [`RENDER-MASKED.md`](RENDER-MASKED.md) |
| Replay | the records onto the screen (`nb_frame`; the automap overlay `OVLW` first when it is on) | card and main `$0C00` (W free) | [`RENDER-MASKED.md`](RENDER-MASKED.md) |
| Full automap, intermission, finale, title page | `am_frame`, `wi_frame`, `fin_frame` | `AMAPW`, `WIW`, `FINW` | [`SCREENS.md`](SCREENS.md) |
| Palettes | the level's tints at its first frame, gamma | `PALW` | [`SCREENS.md`](SCREENS.md) |
| Status bar, HUD, wipe, palette show | `s2_frame` | `P2DW` | [`SCREENS.md`](SCREENS.md), `dl_p2d.s` |
| Menu | while a menu is up: only `M_Ticker` per new tic and `m_frame` (upstream's paused display) | `MENUW` | the kernel's menu loop |

A level frame's list: `K_TIC` (the tic image back, the brain: events,
commands, tics, sounds, the list), `K_LOAD` of the front end, `nr_frame`,
`K_LOAD` of the masked image, `nm_masked`, `nm_bkload`, `nb_frame`,
`K_LOAD` of `P2DW`, `s2_frame`, `K_END` (the next frame).

## 3. The kernel and its step lists

The brain cannot stay in W while the frame's images run, so at every
frame it writes a step list into `DLBUF` (card `$FE80-$FEFF`) and returns
to the kernel, which runs it:

| Step | Bytes | Does |
| --- | --- | --- |
| `K_END` | 0 | the list's end: `K_TIC E_FRAME` |
| `K_LOAD` | 1, bank, runs..., 0 | the bank's page runs (first page, count) into the same addresses of main: one memory-API PRIVATE request, a descriptor a run (`gcall.s`'s `am_runs` in the card). The front end's image and the masked image come this way (`img_wload`, `img_mload`) |
| `K_CALL` | 2, address, A, X | `jsr` with A, X (Y 0); its A into `DL_RES` |
| `K_WLOAD`, `K_MLOAD` | 3, 4 | unused: a stop |
| `K_TIC` | 5, code | the tic image's core from `GCODE0` (from page `$66` when the list's last image was `P2DW`, which left the same bytes in `$6000-$65FF`; else from `$60`) and each plane's pages below `G_MOHWM` from `MOBJP`, a request each; the slots marked empty; then `dl_brain` through `gcall.s`'s `fc_go` with `DL_CODE` = code |
| `K_MENU` | 6 | the menu's paused frames with `MENUW` in W, until the menu closes or makes a request |
| `K_HALT` | 7 | interrupts off, the end (the quit) |

Each list ends the tic phase: the object API's caches go back
(`go_flush`), the walk's planes go back to `MOBJP` in one request
(`planes_out`), and the brain writes the next `K_TIC`'s two load lists
(`k_core`, `k_planes` at `KLISTS`, a fixed place in the kernel). Before
it returns, the brain puts the frame slots' colormap bytes back
(`fs_restore`; [`SPEED.md`](SPEED.md), the frame slots).

The brain's entries (`DL_CODE`): `E_BOOT` (the boot's inits, the title),
`E_FRAME` (a frame), `E_RESUME` (after a load: `g_resume`, the level's
frame-block fields, `S_Start`, `G_Ticker` again), `E_EVENT` (the
automap's answer for the queue's head), `E_MENU` (the menu's request: new
game, end game, quit, SAVE SETTINGS, the benchmark).

**The load protocol** ([`GAME.md`](GAME.md)): a tic whose action loads a
level returns `GT_LOAD`. The brain writes the load list: `fin_load` when
`F_LoadScreen` asked for it, the busy sign, `LCODE`'s `nl_setup` of
`G_GAMEMAP`, the sign off, `K_TIC E_RESUME`. At `E_RESUME` the brain calls
`g_resume`, clears the keys, sets the level's frame-block fields and
`S_Start`, then enters `G_Ticker` again at its action loop (`gt_loop`,
through `dl.inc`'s `GTRESUME`), as upstream goes on after the action
returns.

The kernel keeps nothing in zero page between steps: its state is `KV_*`
(card `$FE7B-$FE7F`) and the brain's `DL_*` (main `DLM`, `$1F00-$1F7F`,
122 of 128 B, with the benchmark's `DL_BENCH`, `DL_BVIEW`, `DL_BRT` and
its timing's `BT_*`).

## 4. Memory

The main loop's places (all of them: [`MEMORY_MAP.md`](MEMORY_MAP.md)):

| Space | Range | Holds |
| --- | --- | --- |
| Main card | `$FF00-$FFF9` | the kernel's code; `KLISTS` `$FFB8-$FFC3` (`k_core`, `k_planes`); the benchmark timing's `bt_replay` at `BT_REPLAY` `$FFC4` (17 B); `far_gcopy` at `KERN_GCOPY` `$FFD5` (35 B, called by no game code). The padding `$FFA7-$FFB7` holds `vh_go` with a VidHD (section 8) |
| Main card | `$FE80-$FEFF`, `$FE7B-$FE7F` | `DLBUF` (the step list), `KV_*` |
| Main card bank 1 | `$DB5C-$DBFF` | the memory API's transport `AMEMLC` (`gcall.s`, 164 B), from the tic image's link |
| Main | `$0880-$08FF`, `$0B94-$0BFF` | the kernel's menu loop and the benchmark timing's `bt_mark` (`BT_MARK` `$08CA`, `BT_MARK2` `$0BE1`): read-only code, copied by DLINIT's PRIVATE request with the static tables |
| Main | `$0844-$0867` | `bt_mark`'s middle part `bt_ext`, which `bt_start` writes there at each benchmark's start |
| Main | `$1F00-$1F7F` | `DLM`: the brain's state (`DL_*`) |
| Main | `$2000-$5FFF` | during the tic phase the frame slots' pinned groups, over colormaps A and B, which the brain puts back |
| W | `$6000-$BFFF` | one image at a time (section 5) |
| RamWorks 1 (`DLBANK`) | `$0200` request, `$1000` sources, `$3000-$3205` the settings, `$6600` DLINIT | the boot's PRIVATE request and what it copies; `DOOM.SETTINGS` and what its save needs (section 7.1) |
| RamWorks 48 (`SPRT`) | `$5400-$54DB` | `SPRBOUND`, written by `playdisk.py` |
| RamWorks 72-73 (`GCODE0-1`) | | the tic image: its W and core at W's addresses in `GCODE0`, its groups packed after them |
| RamWorks 74 (`MOBJP`) | `$B400-$BFFF` | the walk's planes out of W (and the sight hints from `$0200`) |
| RamWorks 91 (`DEMOB`) | | demo3 (DOOM1.WAD's `DEMO3`) for the title loop and the benchmark |
| RamWorks 104 (`S2STATE`) | `$0200-` | the 2D state's first values (the palette state, the automap's, the HUD's, the menu's save slots' text, the settings' defaults) |

**The tic image** (`glayout.py`'s game layout, linked by `play.mk` with
`playlink.py --tic-cfg`): W `$6000-$65FF` (`MATHW`, `AUXW`), the core
`$6600-$99FF` (13,312 B), the parts' scratch blocks `$9A00-$9DFF`, slot 1
`$9E00-$A5FF`, slot 2 `$A600-$ADFF`, `GW` `$AE00-$B3FF`, the planes
`$B400-$BFFF`; the frame slots in main `$2000-$5FFF`. The placement
(`tools/native/gplace-f122.json`) makes 42 groups, 11 of them in frame
slots; the glue's five groups follow (`DLG_B` alone in slot 2, so a call
of the brain's never evicts it). The group directory holds each group's
bank, first page, whole pages and the bytes of its last page; `gr_load`
copies only the group's length. `gcall.s`'s slot tags (`SLOT_GRP`), the
lazy restore's `SLOT_NEED` and `FS_DIRTY` are reset at each `K_TIC`,
because every other image overwrites the slots.

**Zero page.** Each image uses its own ([`MEMORY_MAP.md`](MEMORY_MAP.md)).
The glue in the tic image uses the game's temporaries `GT_0-6` (`$5C-$62`)
and `GA_0-10` (`$48-$52`), `FA_*` for `far_get`, `FC_*` for `fc_call`,
`GC_MP` for `mo_get`; none is live across a step. The kernel uses none.

## 5. The images and their loads

| Image | Bank | Pages |
| --- | --- | --- |
| Tic image: core (and W), planes | 72, 74 | 52 from `$66` (58 from `$60`); the planes' pages below `G_MOHWM` (4-12) |
| A group (W slot or frame slot) | 72-73 | up to 8 |
| `WCODE` and the level's W tables (`img_wload`) | 112 | 64 from `$65`, 10 from `$AF` |
| `MCODE` (`img_mload`) | 113 | 39 from `$68`, 2 from `$B2` |
| `P2DW` | 107 | 31 from `$60` |
| `MENUW` | 108 | 53 from `$60` |
| `AMAPW` | 94 | 34 from `$60` |
| `WIW` | 95 | 26 from `$60` |
| `FINW` | 96 | 28 from `$60` |
| `PALW` | 97 | 10 from `$60` |
| `OVLW` | 93 | 25 from `$68` |
| `LCODE` (the level load) | 98 | 48 from `$60` |
| `DLINIT` | 1 | 5 from `$66` (the boot, SAVE SETTINGS and the quit only) |

Every load is one memory-API request: on F1.2.2 about 46 µs plus 9.8 µs a
page (the front end 0.79 ms, the masked image 0.46 ms, `P2DW` 0.36 ms).
Without the API the CPU makes the same copies, slower (section 8). The
runs come from the links: `playlink.py` writes them into `playimg.inc`.

## 6. No stubs

Every routine the game calls is built: the play link's `gplace.inc` has no
routine with `_B = 0`, and `dl.inc`'s `GTICKER` and `GTRESUME` call the
game's `G_Ticker` (and refuse to assemble if it were not built). What
still stops a run loudly are upstream's own error paths and the guards:
`I_Error` (`GS_ERROR`), the `Z_*` zone calls (`GS_ZONE`: the native pools
are `gthink.s`'s), the saved games' actions (`GS_SAVEGAME`: the menu never
asks for them), an action past `ga_worlddone` (`GS_ACTION`) and `FCALL`'s
`GS_UNBUILT` (none reachable). Each is a `BRK` that stops at `pl_crash`.

## 7. The boot: one disk

`playdisk.py` writes a ProDOS volume `DOOM` (`pldisk.py`'s writer),
4,033,024 bytes: `DOOM.SYSTEM` (`pl_boot.s`, with the kernel in
`pl_ready`'s place), `PRODOS`, `CATALOG`, `CRCLIST`, `LC.BIN` (the card
images: the music player, the effects' card part, `pl_vbl`, the kernel,
the renderer's math, far layer, phase loader and replay), and the bank
files: the level store (`TEXELS.n`, `PATCHES.n`, `MAPS.n`, `TABLES.n`),
`CODE.1` (`LCODE`, the render images, the 2D images, `OVLW`), `CODE.2`
(the tic image, its group directory written into the core), `PLAY.1`
(`DLBANK`, `DEMOB`, `S2STATE`'s first values, `SPRBOUND`), `RTABLES.1`,
`SONGS.1`, `SFX.1`, `GFX.1`, `HUDTXT.1`, and `DOOM.SETTINGS` (section
7.1).

`DOOM.SYSTEM` (`$2000-$37FF`) checks the RamWorks banks, probes the
mouse card, the memory API and the Phasor's native mode, reads
`DOOM.SETTINGS` and finds what its save needs (section 7.1), loads every bank
file into RamWorks and the card images into the card, checks every CRC,
writes the patches its probes call for (section 8, a VidHD's among them),
starts the clock and jumps to `pl_ready`: the kernel. Its first
`K_TIC E_BOOT` runs `b_boot` (ST_Init's state, `G_ReloadDefaults`, the
renderer's statics, the title's start) and the boot list: `DLINIT` (the
settings of `DOOM.SETTINGS`, section 7.1; the PRIVATE copy of the static
tables and the menu loop; black palettes),
`MENUW`'s `m_init`, `WIW`'s `wi_init`, `FINW`'s `fin_init`, then the first
frame. On a2vm the title page shows about 6 s after the start of
`DOOM.SYSTEM`.

The loading screen's rows (counted from 0) say what the boot found: row
0 `DOOM: LOADING`, row 2 no native mode on the Phasor (`NO MUSIC OR
EFFECTS: NO NATIVE MODE`), row 3 no memory API, row 4 `READY`, row 5 the
clock when it is not the Appletini's mouse card, row 7 a VidHD.

### 7.1 The settings file

`DOOM.SETTINGS` is one block of the volume, written by `playdisk.py` with
the game's defaults (`pldisk.settings_file`). Its layout is upstream's
(`m_config65.s`) with the //e's key codes in place of the ADB codes:

| Bytes | Content |
| --- | --- |
| 0-6 | `DOOMSET` |
| 7 | the version, 1 |
| 8-9 | the sum of bytes 12-511, 16 bits |
| 12-21 | a byte each: gamma (0-4), always run, messages, the effects' volume (0-15), the music's volume (0-15), the mouse, the mouse speed (0-9), mouse move, the detail (0, high), the view size (10, the full view) |
| 32-159 | the Doom key of each //e key code 0-127 (`$FF` none) |
| the rest | 0 (upstream's saved games: not in this version) |

**The boot** (`pl_boot.s` `set_boot`, while ProDOS lives, before the
bank files): the file is read through the MLI. Then what the save needs
once ProDOS is gone: ProDOS's last unit `DEVNUM` (`$BF30`, the boot
volume's, which every read so far came from) and its driver's entry in
`DEVADR` (`$BF10` + unit / 8). The entry is kept only when it is in that
unit's slot ROM (`$Cnxx`, with a ProDOS block device's ID bytes `$Cn01`
`$20`, `$Cn03` `$00`, `$Cn05` `$03` and `$CnFF` its offset): an entry in
ProDOS's own memory (the Disk II's driver, a SmartPort unit ProDOS
remapped to another slot) is gone with ProDOS's card. That driver then
reads the volume directory (block 2 and the blocks it links, at most 16)
for `DOOM.SETTINGS`: a seedling of one block and 512 bytes whose access
allows writing; its block is read back by the driver and must equal the
bytes the MLI read. Only then is the save possible (`SIF_SAVE`). The
file and `SET_INFO` (the flags, the unit, the entry, the block) go to
`DLBANK` at `$3000` and `$3200`; nothing here stops the boot.

**Load** (`DLINIT`'s `dli_apply`, the boot list's first step, after
`b_boot`'s defaults): a file that was read and has the magic, the version
and the sum is applied, each value clamped as upstream's (`inRange`,
`flag`): `GAMMA`, `showMessages`, the effects' volume, `SS_SETTINGS`'
always run, mouse, speed, mouse move and music volume, `PL_KEYTAB` (a
code whose key is `NUMKEYS` or more gets none). A missing or bad file
keeps the defaults. Then the settings as they are, in the file's layout
(`collect`), replace the file at `$3000`: the settings as the disk has
them (upstream's `settingsKnown`).

**The menu**: SAVE SETTINGS is dim while the settings equal those
(`MENUW`'s `setchg`, SCREENS.md 3.3). Changed, its `REQ_SAVESET` makes
the brain's list `DLINIT` `dli_save`, then the menu again.

**The save** (`dli_save`): the settings collected again; unchanged, no
write. Else, with `SIF_SAVE`, `blk_write` calls the driver with command 2
(WRITE), the unit, the buffer `$7000` (main W, written by the CPU just
before) and the block, in the state a slot driver expects: interrupts
masked (`php`, `sei`) and decimal mode off; ALTZP, RAMRD, RAMWRT and
80STORE off (RAMWRT and 80STORE put back as they were), `$C073` 0,
INTCXROM off, `$CFFF` read before and after (no card's `$C800` space
left selected; the memory API's FIFO idles between requests); zero page
`$42-$47` and the 64 slot screen holes of `$0400-$07FF` (colormap
levels 32 and 33) kept and, after the call, put back where the driver
changed them (the Appletini's firmware writes MSLOT, `$07F8`); then the
card's `$D000` bank 1 RAM read and write again and `plp`. Only that block
is written. On success `$3000` takes the new settings; on an error, or
with no driver or block from the boot, the menu shows upstream's "Not
saved: the disk is write protected or cannot be written. Press a key."
and stays with the item lit; the game goes on. The interrupts are masked
for the driver's whole call (on the card a SmartPort write through its
firmware, an SD write): the music and the clock wait for it, and no
interrupt handler runs during it, so the interrupt bounds are unchanged.

On the card the boot device is the Appletini's SmartPort in slot 7 (its
ProDOS entry `$C70A`, the slot ROM `pl_boot.s` probes for the memory API:
`$C7FF` `$0A`); an emulator may boot from another slot, and any slot's
ProDOS block driver in its ROM works the same way. On a2vm,
`playdisk.py --disk IMAGE` runs an image's files with the image as a
block device in slot 7 (a2vm `--blockdev`, `tools/a2vm/README.md`),
written in place; `--disk-ro` write-protects it.

## 8. The machine variants

The Appletini's memory API, its mouse card and a Phasor make the
reference machine. Each is optional. `DOOM.SYSTEM` decides at the boot
and patches the card and the images; on the reference machine none of the
patches is written and every byte is as linked.

### 8.1 Without the memory API

`probe_amem` writes nothing into slot 7 until the slot's ROM reads as the
Appletini's, twice over: the SmartPort ID bytes `$C701`, `$C703`, `$C705`,
`$C707` (`$20 $00 $03 $00`), the ProDOS entry offset `$C7FF` (`$0A`),
then its FIFO's control register `$CFF1`. Only then does it send the
STATUS request; its reply is waited for 4 × 64 K turns (about 0.5 s).
A refusal, an error, no reply, or a missing capability or available bit
leaves the game without the API: the boot shows `NO MEMORY API: COPIES
BY THE CPU $xx` on row 3 (`$FF` not an Appletini ROM, `$FE` a capability
missing or unavailable, `$6F` no reply, else the API's error) and goes on.

Then `am_patch` writes the CPU's version (records built by
`tools/native/amcpu.py`, written into `DOOM.SYSTEM`'s `bt_patch` by
`playdisk.py`):

- over the card's transport (`AMEMCPU` over `AMEMLC`, the entries kept):
  `am_push` does the template's descriptor (`cx_exec`, interrupts
  enabled), `am_runs` becomes the far layer's `far_pload`. `cx_exec`
  sets RAMRD for the source's space, RAMWRT for the destination's and
  `$C073` to their bank, and copies or fills a part page at a time; from
  one RamWorks bank to another it switches `$C073` at each byte
  (`cx_tog`). Its inner loops go into two card ranges no link uses
  (`$DFE6-$DFFF`, `$FE45-$FE7A`), which `playdisk.py` checks at every
  build;
- over each W image's own transport (the load image's `am_send`, DLINIT's
  static tables, the menu's screen save, the busy sign's save): a 53-byte
  walker of its request through `cx_exec`.

So `gr_load`, `fs_restore`, `planes_out`, `K_TIC` and `K_LOAD` are
unchanged, and the game plays the same, byte for byte, only slower: the
benchmark reads 4.794 FPS on a2vm against 6.519 ([`SPEED.md`](SPEED.md)).
Copies from one RamWorks bank to another cost about 3.9 µs a byte this way
(a2vm): the level load, the menu's screen save (aux 0 to `S2VIEW`, 32 KB,
about 0.2 s on a card at each opening of the menu) and the busy sign's
save (3,840 B).

### 8.2 The clock and the mouse

Clock priority: the Appletini's mouse card, then an AppleMouse II's VBL,
then the Phasor's VIA-B timer, else the boot stops with `NO CLOCK: NO
MOUSE CARD OR PHASOR`. Row 5 names the choice. The clock runs about 35
tics a second (34.955) on PAL or NTSC.

| Slot 2 | Clock | Mouse | Row 5 |
| --- | --- | --- | --- |
| The Appletini's mouse card | its VBL interrupt | its registers | none (the card's path, as linked) |
| An AppleMouse II | its VBL interrupt, through its firmware | its firmware's X and button 0 | `APPLEMOUSE VBL CLOCK, PAL` (or `NTSC`) |
| An AppleMouse II that never interrupts | the Phasor's VIA-B timer 1 | read once a tick through its firmware | `APPLEMOUSE NO VBL: PHASOR CLOCK, PAL` |
| Nothing, or a ROM with the ID bytes and no firmware | the Phasor's VIA-B timer 1 | none: the keyboard and the Apple keys | `NO APPLETINI MOUSE: PHASOR CLOCK, PAL` |

- **Which card.** `probe_mouse` reads the AppleMouse ID bytes (`$C205`
  `$38`, `$C207` `$18`, `$C20B` `$01`, `$C20C` `$20`), then five bytes
  only the Appletini's ROM has (`$C200-$C201` `LDX #2`, `$C20D-$C20F`
  `STA $C0AC`). It reads only. With the ID bytes alone and the five
  firmware entries DOOM uses in its table (`$C212-$C219`), slot 2 is an
  AppleMouse II.
- **The AppleMouse II.** The boot calls INITMOUSE, POSMOUSE (X 512), then
  SETMOUSE `$09` (the mouse on, its VBL interrupt on). Each interrupt
  (`ap_irq`, in the card) turns 80STORE, RAMRD and RAMWRT off, exchanges
  slot 2's eight screen holes (main `$047A + $80k`) with eight card bytes
  that keep the firmware's own, calls SERVEMOUSE, READMOUSE and POSMOUSE
  (back to 512), and puts everything back. The frame images' poll reads
  the mouse's X and button from zero page `$FD-$FF` instead of the
  card's registers (records of `tools/native/nomouse.py`). If no VBL
  interrupt comes within 20 changes of `$C019`'s bit 7 (10 frames, at any
  CPU speed), `ap_novbl` sets SETMOUSE `$01` (no interrupt) and the clock
  moves to VIA-B's timer, whose handler still reads the mouse.
- **The Phasor's VIA-B timer.** The boot checks that timer 1's latch holds
  what is written (`$55AA`, then `$AA55`), then times two frames between
  starts of the blanking at `$C019` with it. Two frames within 512 counts
  of a standard and 256 of each other choose it: the timer then times out
  every 20,280 (PAL) or 17,030 (NTSC) bus cycles. A frame near no
  standard (a VIA counting faster than the bus) sets the latch to the
  frame measured, shown with a `?`; no blanking, or frames that differ,
  give NTSC and a `?`. Without a mouse card the poll reads no mouse
  (`nomouse.py`'s records: the button read `LDA #0`, `pl_mouse` an
  `RTS`).
- **PAL or NTSC with an AppleMouse** comes from one VBL counted by VIA-A's
  timer 1 when slot 4 has a 6522. With none it is NTSC with a `?`, and a
  PAL machine then runs 17% slow.

### 8.3 With a VidHD

A VidHD keeps its own copy of the SHR screen, fed by every write it sees
to aux `$2000-$9FFF`, whatever the RamWorks bank, and DOOM keeps 4 MB of
data there in banks 1-126. A VidHD honours the IIgs SHADOW register
`$C035`.

`vh_boot` looks for one only when nothing of the Appletini's answered
(the memory API, its mouse card, its slot-7 ROM): slots 7 to 1 but 4, the
ID bytes `$24 $EA $4C` at `$Cn00-$Cn02`, each read twice, slot 3 with
SLOTC3ROM on. With one, it writes `vh_patch`'s records
(`tools/native/vidhd.py`, written by `playdisk.py`, which checks every
place at each build), turns the shadowing on, copies aux 0's `$2000-$9FFF`
onto itself so the VidHD's copy equals it, turns it off, and shows `VIDHD
IN SLOT n: SHR SHADOW IN WINDOWS` on row 7.

From then on the shadowing is off (`$C035` = `$18`: bit 3 the SHR, bit 4
the aux hi-res pages) except while the game writes the screen with bank 0
selected: each screen window's start (`vh_wa`) turns it on, and every
`K_CALL`'s end (`vh_kr`), the replay's scatter (`vh_sc`) and the writes
to other banks after a window turn it off. `vh_go` writes a new value
only when it differs from the last, twice in a row with interrupts masked:
a //e's speaker toggles at any `$C030-$C03F` access, so the second write
puts it back before it can pop. The quit leaves `$C035` at `$00`. Where
each record goes: [`MEMORY_MAP.md`](MEMORY_MAP.md), rule 11 and the VidHD.

## 9. The benchmark and its rows

OPTIONS, BENCHMARK sends `REQ_BENCH`: the brain sets `timingdemo` and
plays demo3 at the normal tic rate, then shows "BENCHMARK: DEMO3" with the
view size and FPS = 35000 × frames / realtics, as upstream's does. ESC
while it runs stops it with no result. Under the FPS, three rows show
each phase's mean time a frame, in ms, over the whole benchmark; N is the
frames drawn. The card's page:

    BENCHMARK: DEMO3
    VIEW                     FULL
    FPS:                    6.343
    TIC 93.1  3D 18.1
    MASK 11.7  DRAW 31.3
    REST 3.5  N 547

The five phases are the whole frame: their sum is about 1000 / FPS.

| Row | The phase | What runs in it |
| --- | --- | --- |
| TIC | the tic phase | `K_TIC`: the tic image and its planes back into W, the brain, the frame's tics, the next step list, the caches written back |
| 3D | the front end | the front end's load and `nr_frame` |
| MASK | the masked phase and the bucket pass | the masked image's load, `nm_masked`, `nm_bkload`, and `nb_frame` but its replays |
| DRAW | the replay | `nb_frame`'s calls of `nat_replay`, the SHR drain included |
| REST | the rest | `PALW` at the level's first frame, the `P2DW` load, `s2_frame` |

`OVF n` after N means the timing lost n turns of its timer that it could
not place in a phase; the totals and the FPS are unaffected.

**How it is measured.** The timer is the Phasor's VIA-A timer 1, loaded
with `$FFFF` at the boot (`pl_detect`, or the VIA-B clock's set-up) and
free-running: it counts the Apple bus cycles down, 1,015,625 a second on
PAL, 1,020,484 on NTSC. It is read low byte then high byte, both again
when the low byte was near its borrow, at each boundary:

- three steps the frame's list adds while the benchmark runs: `K_CALL`s
  of the kernel's `bt_mark` before the masked image's load, after
  `nb_frame` and before `K_END`;
- around each batch's replay: `bt_start` writes `jmp bt_replay` over
  `nat_replay`'s first instruction (kept in DLM with a `jmp` back), and
  `bt_stop` puts it back;
- at the brain's end (`bt_close`): the end of the tic phase.

A short phase's interval is the difference of two readings (mod 65,536).
The tic phase is longer than the timer's turn (64.5 ms), so `bt_close`
counts its turns from the VBL count kept with each reading, and checks the
short phases' sums over the same span: the turns an interval of 3 VBLs or
more lost go back to its phase. The sums are 32-bit counts in DLM
(`BT_S`). The timing runs from the end of demo3's load (`E_RESUME`) to
`G_TimeDemoEnd` (or Escape); `bt_rows` (`dl_cmd.s`) writes the rows into
MENUW's state (`M_BROWS`), and MENUW's `m2_bench` draws them. The rows
need a 6522 in slot 4.

**What it costs.** Each reading is 2 to 4 reads of slot 4, each held to
1 MHz for the Doom profile's slowdown window, about 40 µs a boundary, 6 to
8 boundaries a frame. The timing makes the frame under 1% longer.

**Where the code is.** `bt_mark` in the kernel's menu-loop bytes of main,
its middle part `bt_ext` (36 B) at `$0844`, `bt_replay` in the kernel at
`$FFC4`, `bt_start`, `bt_stop`, `bt_close` in `DLG_D`, `bt_rows` in
`DLG_C` (not the brain's group, which is loaded again after each tic),
`BT_*` in DLM.

## 10. Differences from upstream

- Saved games: the load and save slots say "NOT IN / THIS / VERSION";
  saving answers through `m_savedone` with C set (`k_sdfail`). SAVE
  SETTINGS saves the settings (section 7.1); the file has no saved
  games and no view size or detail but the full view's.
- `SPRBOUND` is computed from the whole WAD: larger than upstream's for
  sprites a level set does not hold (less early rejection, never a
  missing sprite).
- `idrate` sets its flag and its message, but no frame counter is drawn.
- The quit ends on a text screen ("DOOM HAS ENDED. TURN THE COMPUTER
  OFF.") after the sounds stop.
- No gray boot title (`titleWipe`).
- `validcount` wraps as upstream's after 65,535 increments: a frame and
  every trace each add one, so after a few hours of play a stale stamp
  can make a line or sector be skipped for one walk, as on the IIgs.
- `idclev` is upstream's IIgs version: it ends the level (`G_ExitLevel`)
  and takes no map number.

## 11. For the owner: playing DOOM.hdv on the card

### 11.1 The disk and the machine

1. Build it: `./build.sh` writes `build/native/DOOM.hdv`, a 4 MB ProDOS
   volume `DOOM` whose first file is `DOOM.SYSTEM`.
2. Copy `DOOM.hdv` to the Appletini's SD volume (the card in a computer,
   or the menu's USB or FTP SD sharing).
3. The machine: the //e (PAL or NTSC) with 8 MB of RamWorks, the
   Appletini in TURBO mode, the mouse card in slot 2, the Phasor in slot 4
   in native mode (not "Mockingboard only"), and the Doom profile of
   [`tools/sound/README.md`](../tools/sound/README.md) ("The Doom
   configuration profile": `vtw.slowdown.cycles=32`,
   `phasor.slot4.enabled=ON`, `phasor.mockingboard.only=OFF`,
   `slot2.card=MOUSE`, `vtw.turbo.enabled=ON`) loaded. For speed, add
   `vtw.disk2.acceleration.disabled=on` (only `on` reads as true; the menu
   shows "DISK II ACCELERATION DISABLED"): with the virtual Disk II
   active, every TURBO cycle is replayed to it and the CPU runs at about
   67 MHz instead of 110. The figures below are firmware F1.2.2 with this
   key.
4. Boot `DOOM.hdv` from the menu's file browser as the boot volume.
   `DOOM.SYSTEM` loads the 4 MB into RamWorks and the card, checks every
   CRC and starts the title loop: the title page with the intro music,
   then after 30 s the demo (demo3, on E1M7), then the title again.

**Other machines.** The memory API, the mouse card and the Phasor are
each optional (section 8), so the game also runs on an emulator. It
needs:

- an enhanced //e (65C02) with 8 MB of RamWorks: 127 banks of 64 KB, bank
  0 the base aux 64 KB and banks 1-126 at `$C073` (the boot writes each
  bank's number at its `$0200` and reads them back; a missing bank stops
  it, "8 MB OF RAMWORKS NEEDED"), and the //e's language card;
- Super Hi-Res on the //e: `NEWVIDEO` (`$C029`) bit 7 shows aux bank 0's
  `$2000-$9FFF` (the pixels, the SCBs at `$9D00`, the 16 palettes at
  `$9E00`), always bank 0's whatever `$C073` selects (the game pages
  other banks in while the picture shows). A VidHD works (section 8.3);
- for the music and the effects, a Phasor in slot 4 in native mode.
  Without native mode, or with a Mockingboard, the game says so and plays
  silent. Its two 6522s must be real ones at the //e's bus clock:
  register 15 (ORA without handshake) writes port A as register 1 does;
  VIA-A's timer 1 (`$C414-$C417`) counts the bus cycles (PAL or NTSC with
  an AppleMouse, the benchmark's rows); VIA-B's timer 1 (`$C484-$C487`,
  ACR `$C48B`, IFR `$C48D`, IER `$C48E`) free-runs and interrupts at each
  time-out: the clock without a mouse card;
- in slot 2 the Appletini's mouse card, a standard AppleMouse II (with
  Apple's ROM 342-0270), or nothing;
- the timers and the vertical blanking at the real machine's rate (about
  1.02 MHz and 50 or 60 Hz) even when the CPU runs faster: the game's
  tics and the music's tempo come from them;
- a ProDOS block device that boots `DOOM.hdv`; to save the settings, one
  whose ProDOS driver is in its slot's ROM (section 7.1), else SAVE
  SETTINGS says "Not saved";
- nothing in slot 7, or any card: the probe writes nothing there unless
  the slot reads as the Appletini's;
- a fast CPU: the benchmark's frame takes the card about 158 ms with the
  API (a2vm: 154 ms with it, 209 ms without), some 17 to 23 million 65C02
  cycles. A 1 MHz //e would show a frame every 20 s.

### 11.2 Playing

- **A new game**: any key on the title page opens the menu (or ESC);
  NEW GAME, the episode (Knee-Deep in the Dead), the skill. RETURN,
  RETURN takes "Hurt me plenty" on E1M1.
- **Run**: OPTIONS, CONTROLS, ALWAYS RUN (the //e cannot see Shift
  alone). MOUSE, MOUSE SPEED, MOUSE MOVE and KEY SETUP are on the same
  page; DISPLAY & SOUND has the view size, the gamma, the effects' and the
  music's volumes. OPTIONS, SAVE SETTINGS (lit when a setting changed)
  writes them all, the keys included, to `DOOM.SETTINGS` on the disk; the
  next boot starts with them (section 7.1).
- **The automap**: TAB opens the full map, TAB again lays it over the
  view, TAB again closes it; `-` and `=` zoom.
- **Dying**: the view drops; USE restarts the level with a new player
  (pistol, 50 bullets), as upstream's single player.
- **Cheats** are upstream's IIgs set: `iddqd`, `idkfa`, `idfa`,
  `idspispopd`, `idchoppers`, `idbehold` + v, s, i, r, a, l, `idrocket`,
  `idrate`; `idclev` ends the level; `idend` goes to the episode's end.
- **Benchmark**: OPTIONS, BENCHMARK (section 9). It takes about 1.5
  minutes on the card.
- **Quit**: QUIT GAME, Y.

| Key | Does |
| --- | --- |
| Up, down arrows, `W` `S` | forward, back |
| Left, right arrows | turn |
| `A` `D`, `,` `.` | strafe |
| Open Apple, the mouse button | fire |
| `E`, `SPACE`, `RETURN`, Solid Apple | use: doors, switches, lifts (`RETURN` also selects in the menus) |
| the mouse, left and right | turn |
| `1`-`7` | weapons (`1` the fist, or the chainsaw) |
| `TAB`, `-`, `=` | the automap, zoom |
| `ESC` | the menu |

### 11.3 What is missing

- **Saving and loading games**: the menu's LOAD GAME and SAVE GAME slots
  say "NOT IN / THIS / VERSION"; nothing is written. (SAVE SETTINGS
  works: section 7.1.)
- `idrate`'s frame counter is not drawn.
- The episode is DOOM1.WAD's only one (the shareware).

### 11.4 Known problems

1. **Fights run below real time.** The benchmark reads 6.3 frames a
   second on the card; standing still runs at about 17 (a2vm). A frame
   runs at most 4 tics (upstream's rule), so when a frame takes longer
   than 114 ms the game itself slows down: standing still runs at real
   time (35 tics a second), demo3's fights at about 25. The title loop's
   demo plays slower than real time for the same reason (it stays in
   step: it is played by tics).
2. Turning with the mouse takes effect a frame or two later (the mouse is
   read once a frame), which feels laggy at these frame rates.
3. After hours of play `validcount` wraps as upstream's does (section
   10): a wall or sector may be skipped for one frame.
4. With an AppleMouse II only button 0 is read, so MOUSE 2 (strafe) has
   no source; with no 6522 in slot 4 the standard is a guess (NTSC with
   a `?`).
5. A VIA counting 3.85 times the bus clock or more (3.2 on a PAL machine)
   has frames longer than timer 1's 16 bits: the boot falls back to
   NTSC's latch and the game runs that many times too fast.
6. With a VidHD, a //e reset or a crash stop (`pl_crash`) leaves `$C035`
   at `$18`: software started afterwards that expects the SHR shadowed
   shows a stale picture until `$00` is written or the machine is power
   cycled.
7. On an Appletini without the memory API, the CPU's stores reach main
   `$4078-$407F` (the frame slot at page `$40`, colormap B's level 0),
   where the firmware looks for its `A2Li` signature: `playdisk.py`
   checks the pinned groups there, not the level palettes' colormap bytes
   ([`MEMORY_MAP.md`](MEMORY_MAP.md), rule 8).
