# The 2D screens, the platform and the effects

This document describes everything the game draws outside the 3D view, the
machine layer under it, and the sound effects:

- the status bar, the HUD, the menus, the full automap and its overlay,
  the intermission, the finale, the title page, the loading screen and
  the busy sign, and the palettes and gamma they share;
- the platform: the boot `DOOM.SYSTEM`, the interrupt handler and the
  tic clock, the input;
- the 2D data store (`GFX.1`, `HUDTXT.1`) and the effects (`SFX.1`, the
  player, the channel logic).

The code is a 65C02 rewrite of upstream's 65816 routines (Doom8088: Apple
IIgs Edition, in `build/upstream/src/iigs/`). Each source file's header
names the upstream routines it follows. Related documents:
[`PLAY.md`](PLAY.md) (the main loop, the kernel and its step lists, the
image loads, the disk), [`MEMORY_MAP.md`](MEMORY_MAP.md),
[`RENDER.md`](RENDER.md) and [`RENDER-MASKED.md`](RENDER-MASKED.md) (the
replay, `K_OVL` records), [`GAME.md`](GAME.md) (the tic image and its
hooks), [`tools/sound/README.md`](../tools/sound/README.md) (the music and
the effects in detail) and [`src/native/README.md`](../src/native/README.md)
(the file list and the makefiles).

## 1. How the 2D screens are drawn

### 1.1 Upstream and the native model

Upstream draws all 2D into a back buffer in bank `$01`, marks the rows and
byte ranges it wrote (`DRB`, `DRE`, `DRY0`, `DRY1`), and `I_FinishUpdate`
copies the marked bytes to the screen. A patch pixel goes through
`NIBTAB[page << 8 | colour]`, the page given by the row's palette, the
row's parity and the pixel's side (`patch65.s`).

The native drawers **compose in W and publish by CPU stores**:

1. A drawer has a **band** in W: whole rows of 160 bytes, with upstream's
   marks for each row.
2. Before it draws, it fetches the band's background from RamWorks with
   `far_get` (the status bar cache, the menu's saved screen, a picture's
   rows) or starts from zeros.
3. It draws patches into the band with upstream's nibble rule and marks
   the bytes.
4. `s2_publish` (`s2_pub.s`) copies each row's marked bytes to aux bank 0
   with `RAMWRT` on, one `RAMWRT` window a band, then clears the marks.

No 2D drawer reads the screen, so no 2D code needs a `RAMRD` window on
aux 0. On the Appletini each `RAMRD` switch waits until the SHR bytes
written before it have left the card, so this keeps the drawers' reads
cheap. Every shown byte is a CPU store. The only memory-API requests that
touch aux 0 `$2000-$9FFF` are two COPYs that **read** it: the menu's
screen save and the busy sign's save (sections 3.3 and 3.7).

The drawers (`s2_draw.s`) are upstream's: `s2_patch` (`IIGS_DrawPatch`,
clipped to 320 × 200 and to the band's rows), `s2_vpatch`
(`V_DrawPatchNotScaled`), `s2_raw` (`drawRawData` of whole rows, the
`STBAR` lump through `pairByte`), `s2_rect` (`copyToBuffer` by rows: a
picture's pixels, a status bar restore), `s2_back` (`V_DrawBackground`, a
64 × 64 flat tiled). A patch's columns come through a fetch buffer in W,
refilled a column at a time. Each band row has a left and a right nibble
table page (`ROWL`, `ROWR`) from its SCB.

### 1.2 The images

W (`$6000-$BFFF`) holds one image at a time (PLAY.md). Each 2D image is
linked at W's addresses with the render images' shared `MATHW`/`AUXW`
bytes at `$6000-$6592`, and is stored as page runs in its own RamWorks
bank:

| Image | Runs | Bank | Room (code and data) | Run-time W |
| --- | --- | ---: | --- | --- |
| `P2DW` | every level frame, after the replay or after `AMAPW`: palettes, status bar, HUD, input poll, effect service (`dl_p2d.s` `s2_frame`); alone as `s2_poll` in a frame with nothing to draw | 107 | `$6600-$82FF` | band `$8300-$96FF` (status bar rows 168-199, then strip rows 0-9), marks `$9700`, eight 1 KB nibble slots `$9800-$B7FF`, fetch buffer `$B800-$BBFF`, state `$BC00-$BFFF` |
| `MENUW` | while a menu is up; it stays in W through the kernel's `K_MENU` frames | 108 | `$6600-$A4FF` | `PALST` `$A500-$A7FF`, a 24-row band `$A800-$B6FF`, `UI_GRAY` `$B700`, marks `$B800`, the menu palette's nibble slot `$B900-$BCFF`, fetch buffer `$BD00-$BEFF`, state `$BF00` |
| `AMAPW` | full-automap frames, before `P2DW`; automap events | 94 | `$6600-$8DFF` | a 42-row band `$8E00-$A83F`, marks `$A900`, state `$AC00-$AFFF`, the new byte list `$B000-$BFFF` |
| `WIW` | intermission frames | 95 | `$6600-$7FFF` | a 40-row band `$8000-$98FF`, marks `$9900`, 16 nibble units of 2 pages `$9A00-$B9FF`, fetch buffer `$BA00`, state `$BC00-$BFFF` |
| `FINW` | finale, title page, loading screen, busy sign | 96 | `$6600-$7FFF` | as `WIW` |
| `PALW` | a level's first frame and a gamma change, after the view, before `P2DW` | 97 | `$6600-$7FFF` | the build's buffers `$8000-$BFFF` |
| `OVLW` | with the automap's overlay on: after `nm_masked`, before the bucket pass | 93 | `$6800-$93FF`, in `MASKW`'s code room `$6800-$9BFF` | `$9400-$9BFF` (the masked phase's other W ranges untouched) |

`MENUW`, `AMAPW`, `WIW`, `FINW`, `PALW` and `OVLW` are linked by
`src/native/m11.mk` (one fragment per image or data file in `src/native/m11/`), `P2DW`
by `src/native/play.mk` with the frame glue `dl_p2d.s`.
`tools/native/s2layout.py` holds every place in this document, writes the
generated `s2.inc` and the images' ld65 maps (each room a MEMORY area),
and `--check-map` fails a build whose image passes its room. Its size
table also budgets the shared objects (`s2_draw` with `s2_pub`, `s2_pal`,
`s2_nib`, `pl_poll`, `fx_service`, `fx_chan`, `pl_keys`) in each image
that links them.

The input poll and the effect service are linked into every **frame
image**: `P2DW`, `MENUW`, `WIW`, `FINW`. `AMAPW` is always followed by
`P2DW`; `PALW` and `OVLW` are not frame images.

### 1.3 State between frames

W is overwritten every frame, so each image keeps its state in RamWorks
bank `S2STATE` (104) and moves it with `far_get` and `far_put`, 256 bytes
a call. The palette state `PALST` (768 B) is shared by every image that
publishes; `P2DW`, `WIW` and `FINW` hold it at W `$BC00-$BEFF` and their
own 256 B at `$BF00-$BFFF`; `MENUW` its own at `$BF00` (and `PALST` at
`$A500`); `AMAPW` 1 KB at `$AC00-$AFFF`.

What the tic phase writes and a frame image reads lives in the main
card, never in a state block: the tic-side 2D state (`$E443-$E47F`: the
status bar's ticker state, the HUD's message state, the finale's
counters, the mail byte `S2_MAIL`, the fake mobj `FM`, the listener's
last position) and the channel table and mailboxes (`$E8C0-$E8F1`).

`S2_MAIL` carries flags between images: bit 1 `MAIL_AMSTOP` (the
automap was stopped, `AM_Stop`), bit 2 `MAIL_AMSTRIP` and bit 3
`MAIL_AMTITLE` (`AMAPW` or `OVLW` blacked the strip's or the title's
rows, so `P2DW`'s HUD redraws them), bit 4 `MAIL_AMVIEW` (a view was drawn
since the automap last ran).

### 1.4 Tic-side modules

Four pieces must run inside the tic, where upstream runs them. They are
linked into the tic image (`play.mk`'s `M11T`) and use GAME.md's calling
conventions (`GA_*` arguments, `GT_*` temporaries, a 32-byte scratch
block):

| Module | Entries | Called by | Where in the tic image |
| --- | --- | --- | --- |
| `s2t_st.s` | `st_ticker` (A = `M_Random`'s value), `st_start`, `st_init` | the game's `st_tick` (`game/flow`) (`ST_TickerHook`), the `ST_Start` hook, the boot | group `DLG_S` |
| `s2t_hu.s` | `hu_ticker`, `hu_start` | the game's `hu_tick` (`HU_TickerHook`, first), the `HU_Start` hook | the core |
| `s2t_fin.s` | `f_start`, `f_ticker` | the `W_StartFinale` hook; the `F_Ticker` hook after `WI_checkForAccelerate` | group `DLG_H` |
| `fx_chan.s` | `sc_start`, `sc_start2`, `sc_stop`, `sc_update` | the sound hooks; `sc_update` once a frame after the tics | group `DLG_H`; also linked into `MENUW` |

The callback `s2t_pos` (a mobj handle in A:X to its x, y and angle) is
`dl_hook.s`'s. `MENUW` links `fx_pcache.s` instead, which answers from
the channel table's last positions: the game is paused while a menu is
up, so those are the positions upstream's `S_UpdateSounds` would read.

## 2. Palettes, SCBs and nibble tables

`s2_pal.s`, `s2_nib.s` and `s2_palw.s` (`PALW`) are upstream's
`i_viigs65.s` palette code:

| Upstream | Native |
| --- | --- |
| `TINTPAL`: the level's 12 palettes in each of 14 tints (384 B a tint) | bank `S2PAL` (106) `$0200`, built by `PALW`'s `palw_level` from the level's `GSVIEWn` record, `GSSTAT`'s 8 records and `GSOVL`'s 3, with gamma; again by `palw_gamma` when the menu changes gamma in a level |
| `NIBTAB`: 16 tables of 1 KB, one a palette | `S2NIB`, bank `S2PAL` `$1800`; a drawer fetches the tables its rows need into slots in W, once a frame at most |
| `scb`, `palette`, `newpal`, `curtint`, `palettecount`, `picturenum`, `viewpal`, `strippal` and the rest | `PALST` in `S2STATE` |
| `GRAYMAP`, `UI_GRAY`, the menu font's reds | built by `MENUW` when the menu opens; `GRAYMAP` at `S2PAL` `$7700` |

`GSSTAT` (`$5800`) and `GSOVL` (`$6E20`) sit in `S2PAL` at fixed places;
`GFX.1` writes them there. The status bar's rows use 8 palettes, so
`P2DW` has 8 nibble slots. `WIW` and `FINW` hold 16 units of 2 pages (a
palette and a parity), because a 22-row patch on `WIMAP0` can cross 10
palettes.

**The order of the screen's stores is upstream's** (`I_FinishUpdate`):
when a new picture is up (`palettecount` not 0), the 512 palette bytes
black first; then `newColors` (the new tint, the changed SCBs); then the
marked bytes; then the picture's colours (`pictureColors`). Natively the
drawers publish their bands during the frame, so two entries keep the
order: `s2_begin`, which `s2_publish` calls before the frame's first band
(the black palettes when a picture is new, then `newColors`), and
`s2_finish` at the frame's end (`s2_begin` if no band was published, then
the picture's colours). All are CPU stores to aux 0 `$9D00-$9FFF`;
`TINTPAL`'s row goes through page 1 (`$0100-$017F`), 128 bytes at a time.
Aux 0 `$9DC8-$9DFF` stays zero.

**The wipe.** Upstream has no melt wipe: `D_Wipe` and `I_FinishUpdate` are
one label, and a new picture comes with its palettes written black first,
then its bytes, then its colours. The native wipe is that sequence through
`s2_begin` and `s2_finish`. A picture is new when `s2_picpal` sees another
`picturenum`; `F_Ticker` therefore needs no `wipegamestate` write.

**Full-screen pictures** (`TITLEPIC`, `HELP2`, `WIMAP0`) are upstream's
SHR pictures: 32,000 pixel bytes, 200 SCBs, 16 palettes, 16 × 256 pair
bytes. `s2_picpal` sets the picture's rows and palettes (with gamma) in
`PALST` and builds its 16 nibble tables into `S2NIB`; the pixels go out
in five bands of 40 rows, every byte marked.

## 3. The screens

### 3.1 The status bar and the face

`s2_st.s` in `P2DW` is `ST_Drawer` (`refresh`, `diffDraw`, the number,
icon and multi-icon widgets, `restoreRect`, `stHide`). `s2t_st.s` in the
tic image is `ST_Ticker` without its `M_Random` call (the game's `st_tick` makes
the call and passes the value): the ready number's source, the key boxes, the
face (`updateFace`, `painOffset`, `turnHead`), `st_oldhealth`. `ST_Start`
sets `ST_REFRESHED` 0 and the next frame redraws the whole bar.

Upstream redraws only the widgets whose value changed, each over its
background from `STCACHE`, and relies on its back buffer keeping the
bar's rows between frames. W does not keep them, so `S2STATE` holds
`STBUF`, the bar's rows as published (5,120 B). A frame with changes runs
the widgets twice: first marking only, then each marked row's bytes are
fetched from `STBUF`, the widgets restore from `STCACHE` and draw in
upstream's order, the marked bytes go back to `STBUF` and the band is
published. `STCACHE` is the `STBAR` lump with `STARMS`, drawn once
(`I_SaveStatusBackground`). The widgets' old values are in `P2DW`'s
state block; the face, the key boxes, `ST_READY` and `ST_REFRESHED` in
the card. `st_palette` (`ST_doPaletteStuff`: damage, berserk, bonus,
radiation suit) sets the tint.

### 3.2 The HUD

`s2_hu.s` in `P2DW` is `HU_Drawer`: the map's title over the automap
(rows 160-167) and the message line (rows 0-9). It uses `P2DW`'s band
after the status bar is published.

Upstream's `IIGS_TextCode` generates 65816 code for each line it shows.
Natively the line is **recorded** instead: while a line is drawn the
patch drawer also writes, for each byte, the nibbles it set (`CAPMSK`)
and their value (`CAPVAL`). Each of the two text slots keeps its record
in `S2STATE` (`SS_HUDTXT`, 4 KB a slot). Drawing the same text again
replays it: `byte & ~mask | value`. A line starts from black (the strip
is cleared when it turns on and for each new message; the title's rows
are black under the title), so a replay gives upstream's bytes. A change
of a row's palette or nibble table empties both slots (upstream's
`textInvalidate`, `PS_TXTINV`).

A line's text comes from its message id. The tic image's
`player.message` is a reference to a message symbol; `tools/native/s2msgs.py`
gives each id and each map title its text in `HUDTXT.1`, loaded into
`S2STATE` at `SS_HUDMSG` (an index of 256 words, then 36-byte entries).
`P2DW` fetches a text when the line's id changes.

`s2t_hu.s` is the display half of `HU_Ticker` (the counter, `message_on`,
`message_new`, the line's id; the game's `hu_tick` clears
`player.message` itself) and `HU_Start`'s state. It runs in the tic
because the render needs `message_on` before it draws: the frame's list
(`dl_disp.s`) sets `VIEWTOP` from it before the front end, as upstream's
`display` does, and `stripEarly`'s palette follows in `P2DW`.

### 3.3 The menus

`MENUW` holds the menu engine and its pages (`s2_menu.s`, upstream's
`m_menu65.s`), the menu's video (`s2_mvid.s`: `I_MenuPalette`,
`uiDimRect`, `I_MenuPaletteBack`, and `d_main65.s`'s static screen) and
the settings values, key setup, save slots and benchmark result
(`s2_menu2.s`). While a menu is up the game is paused: the kernel's menu
loop keeps `MENUW` in W, runs `m_ticker` for each new tic and
`m_responder` for each event, then `m_frame` (the input poll,
`sc_update`, `fx_service`, the music's ring refill, `m_display`). The
state block and `PALST` move to and from `S2STATE` with `m_load` and
`m_save`.

| Step | Native |
| --- | --- |
| Open (`mv_open`) | One memory-API COPY of aux 0 `$2000-$9FFF` (32 KB: pixels, SCBs, palettes) to bank `S2VIEW` (105) `$2000`; a failed request stops with `PL_STATUS` `$C5`. Then the gray tables from the saved palettes, the menu palette's nibble table (from `GSOVL`'s first record) in its slot, the font's reds, and the menu's palette state (black first, the SCBs, the colours after) |
| Each frame | Upstream's static screen: nothing unless the menu or the skull changed; a moved or blinking skull is put back from the saved screen and drawn again. A new page or message redraws the whole screen: in 24-row bands, each row of the saved screen through the gray map of its saved palette, the page drawn over it, the band published |
| Close (`mv_close`) | The saved screen published band by band by CPU stores, with the saved SCBs and palettes; a changed gamma asks for `PALW` (`M_RELOAD`) or makes the picture new |

Without the memory API, `DOOM.SYSTEM` patches the save to CPU copies
(section 5.3).

**Requests.** The menu's game actions become a request in `MENUW`'s
state block (`M_REQ`, `M_REQARG`) that the brain (`dl_brain.s`) carries
out: `REQ_NEWGAME` (`G_DeferedInitNew`, the skill), `REQ_QUIT`,
`REQ_ENDGAME`, `REQ_LOAD`, `REQ_SAVE`, `REQ_BENCH`, `REQ_SAVESET`.
Saving and loading games are not in this version: the load and save
slots read "NOT IN / THIS / VERSION" and a save answers as failed
(`m_savedone` with C set). The menu's sounds call `sc_start` with no
origin.

**SAVE SETTINGS** (OPTIONS' last item; upstream's `bmItem`,
`G_SettingsChanged`, `G_SaveSettings`, `M_SaveFailed`). Before every full
drawing of a page and before the item's routine, `setchg` compares the
settings now (gamma, messages, the effects' and the music's volumes,
always run, the mouse, its speed and mouse move, the 128 keys) with the
settings as the disk has them, which `DLINIT` keeps in `DLBANK`
(`SET_FILE`, PLAY.md "The settings file"), into `M_SETCHG`: while they
are equal the item is drawn dim (`mv_shade`, the font's reds darkened)
and its RETURN does nothing. Changed, RETURN sends `REQ_SAVESET`; the
brain's list loads `DLINIT`, whose `dli_save` writes `DOOM.SETTINGS`'s
block and answers in `M_SAVERES`, then `MENUW` again with its state.
The next paused frame takes the answer (`savedone`): the gray map and
the font's tables built again from the saved screen (`mv_tables`: they
live in W outside the state block), the page drawn again (the item dim
once saved), and after a failed write upstream's message "Not saved: the
disk is write protected or cannot be written. Press a key."; its key
goes back to OPTIONS with the item lit, for another try. A success shows
no message, as upstream's.

**The //e's keys.** The key setup names the //e's keys (`tools/native/plkeys.py`):
letters, digits, punctuation, `LEFT`, `RIGHT`, `UP`, `DOWN`, `RETURN`,
`ESC`, `TAB`, `SPACE`, `DELETE`, `CTRL-A`..., `O-APPLE`, `S-APPLE`,
`MOUSE 1`, `MOUSE 2`; 8 bytes a name as upstream's table, at most 7
characters. Binding goes through the input block's `PL_BIND` (section
5.2).

**Settings.** The settings that persist are `SS_SETTINGS` in `S2STATE`,
their defaults written by `playdisk.py`; nothing is written to disk. The
view size is the full view only. The music's volume row is drawn and
kept but changes no AY write. The effects' volume is `SND_SFXVOL` in the
card. The accelerator settings (ZipGS, TransWarp) are gone. The
benchmark plays demo3 timed (PLAY.md); its page shows VIEW and FPS
(`M_BFPS`), and in place of upstream's CPU, CACHE and ROM rows the play
build's phase rows (`M_BROWS`).

### 3.4 The full automap

`AMAPW` (`s2_am.s` with `s2_amline.s`) is `AM_Responder`, `AM_Start`,
`AM_Stop`, `AM_Ticker` and `AM_Drawer`'s full mode. `am_frame` (A = the
frame's tics) runs `AM_Ticker` once a tic at frame time, then draws.
`am_responder` takes the automap's keys when the brain routes an event to
it.

Upstream draws the map into the back buffer with a list of the bytes it
wrote, and the next frame blacks the old list's bytes, draws again and
shows both lists. Natively the frame's lines are clipped once into
`S2STATE`'s `SS_AMSEG`, then the map is composed in four bands of 42
rows, each from zeros, each line that crosses it drawn with upstream's
Bresenham. Each band publishes upstream's bytes: the old list's (kept in
`SS_AMOLD`) and the new list's, all rows when upstream redraws all, and
the strip's rows when upstream clears it. The list holds 2,048 entries
(upstream's 3,000); a full list redraws all, as upstream's overflow does.
`AMAPW` sets `S2_MAIL`'s strip and title bits for `P2DW`, which follows it
and draws the palettes, the status bar and the HUD with the map's title.

### 3.5 The automap overlay

Upstream's overlay adds a `K_OVL` record for each pixel of the map's
lines after the view's records, and cuts the column's fill spans at that
row (`FSCUTE`). Natively `OVLW` (`s2_ovl.s`, with `s2_amline.s`
assembled with `-D AM_FASTLINE` for the rotation's fast path) runs in the
render's frame between the masked phase and the bucket pass. It is
loaded into `MASKW`'s code room; `am_ovl` (A = the frame's tics) runs the
ticker, makes the records through the masked copy of `rrec.s`
(`mrec_room`), cuts `FSTOP`/`FSBOT`, and ends with its own copy of
`bucket.s`'s `nm_bkload` (`BKFAR`/`BKFAR2` as data) and keeps its own
`nb_bucket` (with the release build's recount), so `MASKW` is not loaded
again. The replay draws the records. `OVLW` links render.mk's release
objects, as the disk's `rcard` does: `s2ovl.py --check-frame` checks that
the symbols it takes from the frame image `ovf`, and its `BKFAR`,
`BKFAR2` and `BKNEAR`, are at `rcard`'s places (the card, and the main
code the card's replay calls, are `rcard`'s in every frame).

`titleBand`: when the view drew rows 160-167 since the map last showed,
`OVLW` blacks them on the screen at once (one `RAMWRT` window) and sets
`MAIL_AMTITLE`. With the overlay on, the frame's list sets `VIEWBOT` to
the title's row so the view keeps those rows.

### 3.6 The intermission

`WIW` (`s2_wi.s`) is `WI_Drawer` with `drawStats`, `drawShowNextLoc`,
`drawAtNode`, `slamBackground`, `drawPercent`, `drawNum`, `drawTime`, and
`WI_Init`'s lumps. Each of five 40-row bands gets `WIMAP0`'s rows, then
every patch that crosses it, then is published. The intermission's state
is the tic image's (`lgame.inc`'s `WI_*`), read only but `WI_SNLPTR`,
which `WI_Drawer` sets as upstream's does. The intermission's sounds come
from `WI_Ticker` in the tic.

### 3.7 The finale, the title page, the loading screen, the busy sign

`FINW` (`s2_fin.s`):

| Screen | Upstream | Native |
| --- | --- | --- |
| The finale | `F_Drawer`, `F_TextWrite`, `textSpeed` | the `FLOOR4_8` background and the text in 16-row bands, then `HELP2`; `F_StartFinale` and `F_Ticker` are `s2t_fin.s` in the tic, their state (`F_STAGE`, `F_COUNT`, `F_MID`) in the card |
| The title page | `D_PageDrawer`: `TITLEPIC` | `fin_frame` with A bit 1; drawn only when new |
| The loading screen | `F_LoadScreen` | `fin_load`, in a level's load list |
| The busy sign | `bmSignOn`, `bmSignOff` ("LOADING...", "SAVING...", "INSERT DISK n") | the first `fin_signon` saves rows 88-111 by one memory-API COPY to `S2STATE`'s `SS_SIGN` (a failure stops with `$C6`); the sign drawn by columns with `FINW`'s own font over those rows; `fin_signoff` publishes them back |

### 3.8 Named differences from upstream

- **Colours after the view.** Upstream sends the new tint and the strip's
  palette before `R_DrawLists`. Natively they go out with `P2DW`, after
  the replay: in the frame a message appears or expires, rows 0-9 show
  the view's new pixels in the strip's palette (or the reverse) until
  `P2DW` publishes, and a new tint reaches the view as late. The frame's
  final screen is upstream's.
- **The first full-map frame.** `AMAPW` publishes before `P2DW`'s
  `s2_begin`, so in the frame where the view's rows take the map's
  palette the map's bytes reach the screen before their SCBs. The final
  screen is upstream's.
- **No gray boot title.** Upstream's `titleWipe` fades from the loader's
  gray title; the native boot shows none, so the first title page gets
  the black step too.
- **Menus:** the //e's key names, full view only, no accelerator rows, no
  saved games, the music volume kept but not applied (section 3.3).
  SAVE SETTINGS saves the settings (section 3.3), the detail and the view
  size this version's only ones.
- **The automap's byte list** is 2,048 entries (upstream's 3,000).

## 4. The frame and the `$Cxxx` accesses

PLAY.md gives the whole frame. For the 2D and platform code: on the
Appletini every `$Cxxx` access waits for the SHR bytes written before it
to drain, so the frame images order their work to keep those waits
short. A level frame runs the tic phase (the tic-side modules, then
`sc_update` once), the front end, the masked phase, `OVLW` when the
overlay is on, the bucket pass and replay, `AMAPW` instead of the view in
a full-map frame, `PALW` when due, then `P2DW`'s `s2_frame`:

1. the input poll (`pl_poll`): `$C000`, `$C010`, `$C061`, `$C062` and
   the mouse card's registers;
2. the effect service (`fx_service`) and the music's ring refill
   (`snd_refill`), before any 2D store;
3. `PALST` and `P2DW`'s state from `S2STATE`; `I_ViewPalette`,
   `stripEarly`'s palette, `ST_doPaletteStuff`, `ST_Drawer`,
   `HU_Drawer`, `s2_finish`; the state back.

The publishes come last, so the next frame's tic phase starts with the
screen drained. Intermission, finale and title frames (`WIW`, `FINW`) and
the menu's frames (`MENUW`) start with the same poll, service and refill.
The VBL interrupt touches `$C0A0-$C0AF` and `$C400-$C4FF` wherever it
lands; the music and the clock tolerate that jitter.

## 5. The platform

### 5.1 The interrupt and the clock

`pl_irq.s` replaces the music player's own interrupt entry as the main
card's IRQ vector (`$FFFE`). `pl_vbl`:

1. saves A, X, Y; a `BRK` (the B bit of the pushed P) goes to `pl_crash`,
   which masks interrupts, turns the clock's interrupt off and loops. Code
   that stops writes its code to `PL_STATUS` (`$03AE`) first;
2. reads the interrupt's cause and acknowledges it; only a VBL counts;
3. the clock;
4. `fx_step` (the effects' steps, no I/O);
5. `snd_tick` (the music player, `src/sound/player.s`, unchanged: its
   burst to chips 0-2);
6. `fx_burst` (chip 3's registers, right after the music's burst);
7. restores and returns.

**The clock** is a 16-bit fraction a VBL: `TIC_FRAC` 45,743 on PAL and
38,229 on NTSC (out of 65,536); a carry is a tic. 50.0801 Hz × 45,743 /
65,536 = 34.955 and 59.9227 Hz × 38,229 / 65,536 = 34.955 tics a second,
upstream's rate. (A plain 7 tics per 10 VBLs on PAL would give 35.056.)
`pl_time` is `I_GetTime`: the 32-bit tic count, read with interrupts
masked (A, X, Y bits 0-23, bits 24-31 in `CLK_TIME3`). The clock's state
is in the card at `$E403-$E412`; the VBL count is the music player's
`vbl_count` in the interrupt's zero page.

**The VBL source**, chosen by `DOOM.SYSTEM`:

| Slot 2 | The interrupt | PAL or NTSC |
| --- | --- | --- |
| The Appletini's mouse card | its VBL interrupt (mode `$09`); `pl_vbody` reads `$C0A0` and writes `$C0AF` | `pl_detect`: the Phasor's VIA-A timer 1 counts the bus cycles of one VBL, 20,280 PAL or 17,030 NTSC, the nearer wins |
| An AppleMouse II (the ID bytes without the Appletini's registers) | its VBL through its firmware: `pl_vbody`'s head calls `ap_irq` (`SERVEMOUSE`, `READMOUSE`, `POSMOUSE`, slot 2's screen holes swapped in and out); if it gives no VBL, the Phasor's VIA-B timer as below | one of its VBLs timed by VIA-A's timer when slot 4 has one, else NTSC, marked `?` |
| No mouse card | the Phasor's VIA-B timer 1, free-running at a frame's period; `pl_vbody`'s head tests and clears its interrupt flag | the VBL flag (`$C019`) timed by VIA-B's timer |

With neither a mouse card nor VIA-B's timer the boot stops: "NO CLOCK: NO
MOUSE CARD OR PHASOR" (`$C1`). The boot's text screen shows PAL or NTSC
and, without the Appletini's mouse card, which clock it took (`tools/native/nomouse.py` writes the patches for the two
non-Appletini cases; PLAY.md describes them).

**The interrupt's contract.** It touches zero page `$D8-$FF`, the stack,
`$E000-$FFFF`, `$C0A0-$C0AF` and `$C400-$C4FF`, nothing else, so
`RAMRD`, `RAMWRT` and `$C073` may be anything when it comes. With an
AppleMouse II the firmware also uses zero page `$06-$07`, slot 2's eight
screen holes in main `$047A-$07FA`, `$C000-$C01F` and `$C200-$C2FF`
(MEMORY_MAP.md).

### 5.2 Input

`pl_poll` (`pl_input.s`) runs once in every frame image, A nonzero while
a menu is up. `pl_keys.s` holds what the boot and the menus call:
`pl_init` (`I_InitKeyboard`), `pl_defaults` (`I_DefaultKeys`), `pl_bind`
(`I_BindKey`), `pl_action` (`I_ActionKeys`).

| Source | Read | Becomes |
| --- | --- | --- |
| `$C000` | a new key (strobe set); folded to upper case (`$61-$7A` to `$41-$5A`) | a //e code 1-127 |
| `$C010` | bit 7: a key is down; the access clears the strobe | the held key goes up when it clears |
| `$C061`, `$C062` | Open Apple, Solid Apple | pseudo-keys `$72`, `$73` |
| Mouse card | X between two reads of the sequence byte, re-centred when outside `$2000-$DFFF`; buttons at `$C0A5` | `PL_MDX` (upstream's `iigs_mousedx`); pseudo-keys `$71` (button 0, `MOUSE 1`) and `$70` (button 1, `MOUSE 2`) |

Since the //e never delivers a code in `$61-$7A` after the fold, four of
those codes carry the pseudo-keys.

**The policy.** The //e knows one key down at a time. A new key that is
not the held key: the held key goes up, the new one down. The same key
again while `$C010` says down is the //e's auto-repeat and is ignored. A
key that goes down and up between two polls stays down for that poll and
goes up at the next. The Apple keys and the buttons are independent keys,
read each poll. A menu arrow still held repeats after 11 tics, then every
4 (upstream's `REP_DELAY`, `REP_RATE`), from `pl_time`.

**Events** are upstream's: a //e code goes through the key table
(`PL_KEYTAB`, 128 Doom keys, upstream's `keyTable` format), a Doom key is
down while any of its sources is (the counts recomputed each poll), and
the changes go into the event queue `PL_QUEUE` (15 entries of 3 bytes,
14 usable: the type, then upstream's `data1` word, a Doom key 0-22 or a
character). The brain's `D_PostEvent` routing drains it. A poll makes at
most 7 events; with fewer than 7 free entries it posts nothing (the key
stays in `$C000`, the Apple keys, buttons and repeat wait) and counts the
deferral in `PL_DEFER`; the mouse is still read.

**Default keys** (`plkeys.py`, written by hand into `pl_keys.s`): the
arrows, `W`/`S` move, `A`/`D` and `,`/`.` strafe, `1`-`7` weapons, `E`,
`SPACE` and `RETURN` use, `ESC` menu, `TAB` map, `-`/`=` zoom, Open Apple
fire, Solid Apple use, mouse 1 fire, mouse 2 strafe. The //e cannot see
Shift alone; the menu's ALWAYS RUN gives running.

**The key setup.** The menu writes `$FF` to `PL_BIND`; the next poll's
first new press (a keyboard key, else one of the four pseudo-keys) goes
into `PL_BIND` instead of an event, and the menu binds it with
`pl_bind`, then writes `$80` (idle).

Without the Appletini's mouse card the frame images' poll is patched at
boot: with no card the buttons read as up and the mouse is not read;
with an AppleMouse II the poll reads the X and button that `ap_irq` keeps
in zero page `$FD-$FF`.

### 5.3 The boot (`DOOM.SYSTEM`)

`pl_boot.s`, loaded by ProDOS at `$2000` (`$2000-$37FF`; discarded after
the boot). It follows `LEVELS.SYSTEM`'s boot (`lboot.s`) and the A2DM
bank-file loader:

1. Text screen, "DOOM: LOADING". The probes, each a stop with its
   message and its code in `PL_STATUS`:
   - RamWorks banks 1-126: each bank's number written to its `$0200`
     from 126 down, read back from 1 up; a missing bank stops ("8 MB OF
     RAMWORKS NEEDED", `$C2`);
   - slot 2: the Appletini's mouse card, an AppleMouse II
     (`INITMOUSE`d), or none (section 5.1);
   - the memory API in slot 7: without it a message, and the game goes
     on with CPU copies;
   - `snd_probe`: without the Phasor's native mode a message ("NO MUSIC
     OR EFFECTS"), and the game goes on without music or effects.

   Then `set_boot` (segment `PLSET`): `DOOM.SETTINGS` read through the
   MLI into `$6000`, and what SAVE SETTINGS needs once ProDOS is gone:
   the boot device's block driver (ProDOS's `DEVNUM` `$BF30` and its
   entry in `DEVADR` `$BF10`, kept only when it is in that slot's ROM),
   the file's block from the volume directory (read by that driver), and
   that block read back equal to the file. Both into `DLBANK`
   (`SET_FILE`, `SET_INFO`), before any bank file; nothing here stops the
   boot (PLAY.md, "The settings file").
2. `CATALOG` (the bank files' names), then every bank file through the
   MLI into its banks, 8 KB at a time. A ProDOS error, a file that is not
   a bank file, a bank outside 1-126 or a segment outside `$0200-$BFFF`
   stops (`$C7`).
3. `CRCLIST`: a count, then bank, address, length and CRC-32 for each
   segment and for `LC.BIN`'s two halves. Every segment's CRC is checked
   in its bank; a mismatch, or a count other than the segments loaded,
   stops with the bank and address (`$C4`).
4. `LC.BIN`, the card images (16 KB each: bank 1 `$D000`, bank 2
   `$D000`, `$E000-$FFFF`): the aux card's, then the main card's, each
   read into `$6000`, checked and installed by CPU copy. Then main
   `$0200-$03EF`, `$0C00-$1FFF` and ProDOS's global page `$BF00-$BFFF`
   are cleared, and zero page `$00-$17`. ProDOS is gone.
5. `bt_init`: the clock's interrupt on; the patch tables for what the
   probes found (`mo_recs` and `bt_mpatch` without the Appletini's mouse
   card, `ap_recs` and `ap_mpatch` with an AppleMouse II, `am_patch`
   without the memory API, `vh_patch` with a VidHD); `pl_init`,
   `snd_init`, `fx_init` with `snd_probe`'s answer, `pl_clkset`, `CLI`;
   PAL or NTSC detected and shown; `PL_STATUS` = `$C0`; `jmp pl_ready`.

`pl_ready`'s place (`$FF00`) holds the kernel (`dl_kern.s`, linked there
by `play.mk`), so the boot's last jump starts the game (PLAY.md).

The patch tables are records (a length, a bank, an address, the bytes)
that `playdisk.py` writes into `DOOM.SYSTEM` from `tools/native/amcpu.py`
(the memory API's requests done by the CPU, in the card and in each W
image that sends one: `MENUW`'s screen save, `FINW`'s sign save, the
load image, `DLINIT`), `nomouse.py` and `vidhd.py`.

**The disk.** `tools/native/playdisk.py` writes `build/native/DOOM.hdv`
with `pldisk.py`'s functions: a ProDOS 2.4.3 volume with `DOOM.SYSTEM`,
`PRODOS`, `CATALOG`, `CRCLIST`, `LC.BIN`, the bank files (PLAY.md
lists them) and `DOOM.SETTINGS` (one block, the defaults). The 2D and sound files are `SONGS.1` (the 13 songs in banks
100-102, a directory at bank 100 `$0200`, 3 bytes a song), `SFX.1`,
`GFX.1` and `HUDTXT.1`.

### 5.4 The VidHD

A VidHD keeps its own copy of the SHR screen, fed by every write it sees
to aux `$2000-$9FFF`. It follows `RAMWRT`, but not RamWorks' `$C073`, so
the game's data in aux `$2000-$9FFF` of banks 1-126 would land on its
picture. It honours the IIgs `SHADOW` register `$C035`. When the boot
finds a VidHD and nothing of the Appletini's (no memory API, no
Appletini mouse card, no Appletini slot-7 ROM), it writes `vidhd.py`'s
records: the shadowing stays off (`$18`) and is turned on (`$00`) only
while a screen window is open with bank 0 selected. Each screen window's
`STA RAMWRTON` in the 2D images (`s2_publish`, `s2_begin`, `s2_finish`,
`AMAPW`'s publishes, `OVLW`'s title band) becomes a call of `vh_wa`;
the kernel turns the shadowing off after every step; and the writes to
other banks that follow a screen window inside one step (the HUD's
record, the menu's screen save, the automap's old list, `OVLW`'s record
spill) are preceded by the shadowing off. Each `$C035` value is written
twice in a row with interrupts masked, because on a //e the access also
toggles the speaker. PLAY.md and MEMORY_MAP.md give the places.

## 6. The effects

The design of the converter, the script format, the player and the
stereo rule is in [`tools/sound/README.md`](../tools/sound/README.md),
"Effects (S4)". In short:

| Piece | Where it runs | Where it lives |
| --- | --- | --- |
| The scripts: one per game sound (52), from the WAD's `DS*` and `DP*` lumps by `tools/sound/fxconv.py`, the 10 most frequent hand-tuned in `tools/sound/fxtune.txt` | | `SFX.1` in bank `SFX` (103) at `$0200`: the directory, the volume table `VATT` at `$02D0`, the scripts from `$0350` |
| `sc_start`, `sc_start2`, `sc_stop`, `sc_update` (`fx_chan.s`): upstream's channel logic (`s_sound65.s`) with `NUM_CHANNELS` 3 | the tic (the sound hooks; `sc_update` once a frame after the tics); in a paused menu frame `MENUW`'s copy | the channel table and the mailboxes in the card `$E8C0-$E8EF`, `LS_ON` and `SND_SFXVOL` after them |
| `fx_service`: the mailboxes to voices, the stereo choice, the ring refills | every frame image, once a frame | W, a shared object (`src/sound/fx.s` assembled with `-D FX_SERVICE`) |
| `fx_step`, `fx_burst`: the voices' steps and chip 3's burst | the VBL interrupt, before and after `snd_tick` | the card `$F505-$F8FF` with `pl_vbl`; voices `$E413-$E442`, flags `$E737-$E73F`, rings `$E740-$E8BF` |
| `fx_song` | wherever the game starts a song | the card: `FX_HOLD` set, the music's `snd_start`, `FX_INVAL` set, `FX_HOLD` cleared |

**One mailbox a channel** (flags, sound, volume, separation). The channel
logic never queues: every decision lands in its channel's mailbox, the
latest wins, so a frame's requests are bounded by the channel count. A
stop sets *stop* and clears *start* and *volume*; a start sets *start*
with its sound, volume and separation; `I_UpdateSoundParams` sets
*volume*. `fx_service` empties the mailboxes once a frame.

**`isPlaying`** (`fx_isplaying`) is "the channel's voice is active, or
its mailbox holds a start": `sc_update` runs after the frame's tics and
before `fx_service`, so without the pending start it would stop every
sound the frame's tics just started.

**Chip 3 and the music.** `fx_burst` follows the music's burst with no
computation between, so both share one slot-4 slowdown tail. With no
effect playing chips 0-2 get exactly the music's writes and chip 3 none.
The music's `snd_start` rewrites all four chips from the main loop with
interrupts on, so `fx_song` holds the effect player during it and marks
chip 3's shadow invalid after it (and at boot).

**No native mode.** Without the Phasor's native mode (`snd_probe`'s
`SND_NO_MUSIC`) `fx_init` leaves `FX_ON` 0: the interrupt's parts return
at once, `fx_service` empties the mailboxes and starts nothing, and the
channel logic runs unchanged.

**Latency.** A sound decided in a tic starts at that frame's
`fx_service`, after the render and the replay, so it is heard when the
frame that shows its tic appears. Upstream's DOC started it at the call.

## 7. The 2D data store and its host tools

**`GFX.1`** (`tools/native/s2data.py`, `src/native/m11/s2data.mk`) holds
every lump the 2D screens draw: 216 lumps, 295,585 bytes, and the
handles table `GFXDIR` (1,080 B) at bank 109 `$0200`.

| Lumps | Source |
| --- | --- |
| Doom patches `ST*`, `M_*`, `WI*` | `DOOM1.WAD`, parsed and written again by `s2data.py`'s own code, each checked equal to the release's lump; the six menu patches upstream drew itself (`M_ARUN`, `M_GAMMA`, `M_MOUSE`, `M_MSPEED`, `M_MMOVE`, `M_CTRLS`) and the recoloured `WIURH0` from the release |
| `STBAR` | `DOOM1.WAD`'s patch drawn into upstream's raw form (320 × 32 bytes), checked equal |
| `FLOOR4_8` | `DOOM1.WAD`'s flat, checked equal |
| `TITLEPIC`, `HELP2`, `WIMAP0` (36,864-byte SHR pictures), `GSSTAT`, `GSOVL` (palette records) | upstream's build artifacts, read from the release image through `umodel.Release`, in `build/` only |

A lump's handle is its rank among the 2D lumps in the release's
directory, so runs such as `STTNUM0`-`STTNUM9` stay consecutive.
`GFXDIR` holds five arrays indexed by the handle: the bank, the address's
low and high bytes, the length's low and high bytes. The generated
`s2data.inc` gives each lump's handle and place as constants.

The drawers' contracts, which `s2data.py` checks: every lump in its
bank's `$0200-$BFFF` (a `RAMRD` window reaches nothing else), every patch
column at most 256 bytes and starting at least a fetch buffer before
`$C000`, every raw lump whole rows of 320 bytes. The store fills banks
109, 110, 114 and 115 (`GFX0`-`GFX3`) first, then the free parts of
banks 103 (after `SFX.1`), 105 (around the menu's saved screen), 107 and
108 (below `MATHW` and above the images); `GSSTAT` and `GSOVL` go to
their fixed places in `S2PAL`. `s2data.py --check --report` prints each
bank's use.

**`HUDTXT.1`** (`tools/native/s2msgs.py`, `src/native/m11/s2hud.mk`): the
texts of the HUD's message ids and map titles, a bank file for
`S2STATE`'s `SS_HUDMSG`.

**`SFX.1`** (`tools/sound/fxconv.py`, `src/native/m11/fxconv.mk`): the 52
effect scripts, 11,385 bytes; `SFX.lst` lists each one.
`tools/sound/fxchan.py` writes `fxchan.inc` (upstream's priority table
and the channel constants) and is the host model of the channel logic.

**The generated includes.** The images' fragments in `src/native/m11/`
and `play.mk` run the parts' tools for their includes: `s2layout.py`
(`s2.inc`), `s2stbar.py`, `s2msgs.py`, `s2pal.py`, `s2fin.py`,
`s2menu1.py`, `s2menu2.py`, `s2wi.py`, `s2amap.py`, `s2ovl.py`,
`plkeys.py`, `fxchan.py`.

**Building.** `build.sh` runs everything. For these pieces alone, from
`demos/doom_gs`: `make -C src/native -f m11.mk` builds the 2D images,
`GFX.1`, `SFX.1` and `HUDTXT.1` (`part P=NAME` builds one fragment, e.g.
`P=fxconv` after editing `fxtune.txt`); `python3 tools/native/playdisk.py`
links `P2DW`, the tic image and the card with `play.mk` and writes
`DOOM.hdv`.

## 8. Memory

MEMORY_MAP.md is the full map; these are the 2D and platform regions.

**Main memory.**

| Range | Use |
| --- | --- |
| `$0100-$017F` | `TINTPAL`'s bounce in `s2_begin`, outside the replay (the stack stays at or above `$01C0`) |
| `$03AE` | `PL_STATUS`: the boot's state and every stop's code (shared with the load's status byte) |
| `$03B3-$03ED` | the input block: `PL_QUEUE` (`$03B3-$03DF`), `PL_QHEAD`, `PL_QTAIL`, `PL_HELD`, `PL_BUTTONS`, `PL_MDX`, `PL_MLX`, the repeat's key, character and tic, `PL_DEFER`, `PL_BIND` (`$03B0-$03B2` are the tic image's `GS_STATUS` and `GS_ARG`, `$03EE-$03EF` the random indexes) |
| `$1F80-$1FFF` | `PL_KEYTAB`: the Doom key of each //e code, written by `pl_keys.s` and, once at the boot, by `DLINIT`'s `dli_apply` (`DOOM.SETTINGS`'s keys) |
| `$2000-$37FF` | `DOOM.SYSTEM` during the boot only |

**Stop codes in `PL_STATUS`:** `$C0` ready; `$C1` no clock; `$C2` too few
RamWorks banks; `$C4` a CRC; `$C5` the menu's screen save failed; `$C6`
the busy sign's save failed; `$C7` the disk; `$D1` a full-map frame whose
lines' rows use more than 4 palettes and `$D2` more clipped lines than
`SS_AMSEG` holds (both impossible with upstream's data).

**Zero page.**

| Range | Use |
| --- | --- |
| `$48-$77` | the drawers' `S2_*` (the band, the patch, the publish) |
| `$5A-$69` | `pl_poll`'s `PLZ`, over the drawers' temporaries (the poll runs before any drawer) |
| `$78-$7F` | `s2_pal`'s and `s2_nib`'s `S2P_*` |
| `$80-$AF` | each image's own: `MENUW`'s `S2M_*`, the automap's `$80-$AE` (`AMAPW`, and `OVLW` between the masked phase and the bucket pass), `WIW`'s `$80-$AD`, `FINW`'s `FZ_*` |
| `$B0-$D7` | the math block ([`src/native/MATH.md`](../src/native/MATH.md)) |
| `$D8-$F6` | the music player (interrupt) |
| `$F7-$FC` | the effect player's interrupt temporaries |
| `$FD-$FF` | spare; with an AppleMouse II the mouse's X (`AP_X`) and button (`AP_SB`) |

The tic-side modules use the tic image's `GA_*` and `GT_*`.

**The main card.**

| Range | Use |
| --- | --- |
| `$E403-$E412` | the clock: `CLK_STEP`, `CLK_FRAC`, `CLK_TICS`, `CLK_STD`, `CLK_TIME3` |
| `$E413-$E442` | the three effect voices, 16 B each |
| `$E443-$E47F` | the tic-side 2D state (61 B): status bar, HUD, finale, `S2_MAIL`, `FM`, the listener's last position, `ST_READY`, `ST_RUNNING` |
| `$E737-$E73F` | `FX_ON`, `FX_HOLD`, `FX_INVAL`, the effects' tempo fraction, `fx_service`'s temporaries |
| `$E740-$E8BF` | the effect rings, 3 × 128 B |
| `$E8C0-$E8F1` | the channel table (3 × 12 B), the mailboxes (3 × 4 B), `LS_ON`, `SND_SFXVOL`; then `vh_kr` (VidHD) at `$E8F2` |
| `$F505-$F8FF` | `pl_vbl`, `pl_time`, `pl_clkset`, `pl_detect`, and `fx.s`'s card part; with an AppleMouse II `ap_irq` over `pl_detect` from `$F88E`, and `ap_swap` at `$F4DD-$F504` |
| `$FF00-` | the kernel, in `pl_ready`'s place (PLAY.md) |
| `$FFFE` | the IRQ vector: `pl_vbl` |

The music player owns `$E000-$E402` (the song ring), `$E480-$E736` and
`$E900-$F504` (src/sound/README.md).

**RamWorks banks.**

| Bank | Name | Content |
| ---: | --- | --- |
| 93 | `OVLW` | the overlay's image |
| 94, 95, 96, 97 | `S2CODE2`-`S2CODE5` | `AMAPW`, `WIW`, `FINW`, `PALW` |
| 100-102 | `SONGS` | `SONGS.1`: the song directory, then the 13 songs |
| 103 | `SFX` | `SFX.1` at `$0200-$3FFF`; the 2D store at `$4000-$BFFF` |
| 104 | `S2STATE` | `PALST`, each image's state block, `SS_SETTINGS`, `STCACHE`, the HUD's text records (`SS_HUDTXT`), the automap's old list (`SS_AMOLD`), the sign's saved rows (`SS_SIGN`), `STBUF`, the HUD texts (`SS_HUDMSG`), the full map's clipped lines (`SS_AMSEG`): `$0200-$B11F` |
| 105 | `S2VIEW` | the menu's saved screen at `$2000-$9FFF`; the 2D store around it |
| 106 | `S2PAL` | `TINTPAL` `$0200`, `S2NIB` `$1800`, `GSSTAT` `$5800`, `GSOVL` `$6E20`, `GRAYMAP` `$7700` |
| 107, 108 | `S2CODE0`, `S2CODE1` | `P2DW` and `MENUW`; the 2D store in their free parts |
| 109, 110, 114, 115 | `GFX0`-`GFX3` | the 2D store and its handles table |

## 9. Costs

Measured on a2vm's `f121` profile (the Doom configuration) when the 2D
code was built, the image loads not included (PLAY.md and SPEED.md give
the loads and whole frames):

| What | ms |
| --- | --- |
| Status bar: nothing changed / the face / a full refresh | 0.06 / 6.5 / 44.1 |
| HUD: nothing / a cached line replayed / a line drawn afresh | 0.02 / 3.8 / 15-22 |
| Palettes with nothing new (`PALST`'s fetch and write-back) | 0.7 |
| Input poll | 0.04-0.06 |
| `fx_service`, median / worst | 0.02 / 0.19 |
| Menu open (the 32 KB save and the gray screen) / a page redrawn / a skull frame / close | 137 / 93-137 / 3.2 / 47 |
| Full automap, median / worst | 13 / 63 |
| Overlay `am_ovl` with the computer map | 55 |
| Intermission frame, median | 81 |
| Finale text frame, median / worst | 68 / 174 |
| `PALW`: a level's tints | 22 |

The interrupt: the clock alone about 6 µs; the music through `pl_vbl`
1,548 µs at worst (`D_INTRO`); three effects starting on `D_INTRO`'s
first chord 2,048 µs; stack 16 bytes. On `D_E1M1` the interrupt takes about
6 ms a second from the main loop with the music alone and about 16 ms
with effects at demo3's rate (window 32).
