# Byte-level memory map of the native port

Where every part of the shipped game (`build/native/DOOM.hdv`) lives:
zero page, main memory, W, the two language cards, aux bank 0 and the
RamWorks banks. The main loop and the images it loads are in
[`PLAY.md`](PLAY.md); the time each copy costs is in
[`SPEED.md`](SPEED.md).

## 0. Conventions and where the map is held

**Addresses.** "aux N" is RamWorks bank N as `$C073` selects it. Aux 0 is
the base aux 64 KB, which holds the SHR screen. The game uses banks 1-126;
127 is never named. A bank's room is `$0200-$BFFF`: what a `RAMRD` or
`RAMWRT` window reaches. "W" is main `$6000-$BFFF`, which holds one image
at a time. "The card" is the main language card unless said otherwise.

**Who holds the addresses.** Each address below comes from one Python
layout module in `tools/native`, which the builds import and which
generates the includes the 65C02 sources assemble with. Each module's
`check()` fails on two regions sharing a byte:

| Module | Holds |
| --- | --- |
| `layout.py` | The replay: row blocks, entry tables, colormap page tables, column arrays, the replay's zero page |
| `rlayout.py` | The renderer: its zero-page overlays, main's render rows, the front end's and masked phase's W maps, the far layer's card bytes, the aux card's tables, the render banks |
| `llayout.py` | The level store and load window, the game state's banks and records, the game globals, `bank_map()` (every bank 1-126) |
| `glayout.py` | The tic phase: W's map, the frame slots, the runtime's state, the tic zero page, the memory-API transport's card bytes |
| `s2layout.py` | The 2D images' W maps and banks, their zero page, the card's clock, effects and channel blocks, `S2STATE` |
| `playlayout.py` | The main loop: the kernel, `DLBUF`, `KVARS`, `DLM`, `DLBANK`, the benchmark timing's bytes |

The ld65 configurations (`src/native/render.cfg`, `level.cfg` and the maps `glayout.py`, `s2layout.py` and `playlink.py`
write) give each region its own MEMORY area, so an overflow fails the
link. `tools/native/playdisk.py` then checks the links against each other
when it writes the disk (section 11).

## 1. Rules

| # | Rule | Why |
| --: | --- | --- |
| 1 | The language card is RAM for reading and writing at all times. `$D000` bank 1 is selected in every phase but the replay; the replay selects bank 2 on entry and bank 1 on exit. | The two 4 KB banks at `$D000` serve two sets of phases: bank 2 holds the replay's row blocks, bank 1 the math, the far layer and the transport. |
| 2 | The IRQ handler touches only zero page `$D8-$FF`, the stack page, `$E000-$FFFF` and I/O (`$C0A0-$C0AF`, `$C400-$C4FF`). Never `$D000-$DFFF` (its bank depends on the phase) and never `$0200-$BFFF` (RAMRD, RAMWRT and `$C073` may be set). With an AppleMouse II (section 10) it also reads `$C013`, `$C014`, `$C018`, turns 80STORE, RAMRD and RAMWRT off and back as it found them, calls the mouse firmware in `$C200-$C2FF` (which borrows zero page `$06`, and `$07` through the 65C02's RTS, and about 8 bytes of stack), and exchanges slot 2's eight screen holes (main `$047A + $80k`, k = 0-7) with the card's `ap_hb` around the firmware, so every byte of `$0200-$BFFF` holds at the RTI what it held at the interrupt. | The music player's IRQ contract (`src/sound/README.md`), with `$D000-$DFFF` taken out. |
| 3 | Main `$0400-$0BFF` and `$2000-$5FFF`, and aux 0 `$0400-$0BFF`, hold read-only data written by memory-API PRIVATE copies. No CPU store targets them after the boot. During the tic phase `$2000-$5FFF` also holds the frame slots' code (section 3.4), copied in and back by PRIVATE and never stored into. Without the memory API (section 10) the same copies are CPU stores at the same points. With an AppleMouse II the interrupt exchanges slot 2's eight holes in `$0400-$07FF` and puts them back before the RTI; SAVE SETTINGS stores back the holes its block driver changed (rule 9). | On the Appletini a CPU store there is a video write, about 1 µs a byte. PRIVATE writes are not captured as video. |
| 4 | Aux 0 `$2000-$9FFF` is written only by CPU stores with RAMWRT on. PRIVATE never targets it. | It is the screen. PRIVATE writes are never shown. |
| 5 | Inside a far window only zero page, the stack page and the card are near. Code in a read window runs from the card, zero page or page 1. | With RAMRD on, every fetch of `$0200-$BFFF` comes from the selected bank. |
| 6 | During the replay's draw pass (RAMWRT on, `$C073` = 0) the replay writes only zero page `$48-$6F`, the stack, the row-block patch bytes in card bank 2 and aux 0 `$2000-$88FF`. | With RAMWRT on, every store to `$0200-$BFFF` goes to aux 0. |
| 7 | ALTZP is on only inside straight-line code bracketed by SEI and CLI, which keeps its results in registers or main `$0200-$BFFF`. | The aux card is full of tables and has no vectors (section 6). |
| 8 | The CPU never writes main `$0878-$087F` or `$4078-$407F`. Without the memory API the frame slot at page `$40` and colormap B's level 0 come there by CPU stores: `playdisk.py` checks that no group pinned there holds `A2Li` at `$4078`. | The Appletini firmware reads an `A2Li` signature and a load-hold byte there from its shadow of main memory. PRIVATE writes never reach that shadow. |
| 9 | The slot holes of main `$0400-$07FF` (`$x78-$x7F`, `$xF8-$xFF`) are written by slot firmware and SmartPort calls. Those pages (colormap levels 32 and 33) are reloaded after any firmware call; the AppleMouse II's interrupt instead swaps its own bytes in and out (rule 2), and SAVE SETTINGS's block-driver call (DLINIT's `blk_write`) keeps the 64 holes and stores back, after the call, only those the driver changed (the Appletini's firmware writes MSLOT, `$07F8`). | Colormap levels 32 and 33 are rare (invulnerability and the last map), so they sit in the pages firmware can touch. |
| 10 | Aux 0 `$9DC8-$9DFF` stays zero. | Standard SHR. The bytes `"SHR4"`\|`$80` at `$9DFC-$9DFF` would switch the card to its PAL256 mode. |
| 11 | With a VidHD (section 10): the SHR shadowing (`$C035`) is off (`$18`) except in shadow windows. A screen window's start turns it on (`$00`); the end of the kernel step, the replay's next scatter, or the routines listed in section 10 turn it off. Inside a shadow window no CPU store reaches aux `$2000-$9FFF` of a bank other than 0, and every store to aux 0's `$2000-$9FFF` comes inside one. Each value is written to `$C035` twice in a row with interrupts masked, and only when it differs from the last one written. | A VidHD copies every write it sees to aux `$2000-$9FFF` into its own SHR, whatever `$C073` selects, unless `$C035` inhibits it. Any `$C030-$C03F` access toggles a //e's speaker; the second write puts it back. |

## 2. Zero page and stack

Main zero page. Overlays 1 and 2 are reused by every phase; nothing
persistent lives in them.

| Range | Owner | Content |
| --- | --- | --- |
| `$00-$05` | far layer, all phases | `FA_DST`, `FA_SRC`, `FA_BANK`, `FA_N`: the far layer's and the memory API's copy arguments |
| `$06-$07` | reserved | No symbol. An AppleMouse II's SERVEMOUSE borrows `$06` (rule 2) |
| `$08-$17` | platform | Reserved, cleared by the boot; no symbol |
| `$18-$41` | overlay 1 | Front end: the BSP walk's state `$18-$38`, the corner cache `$39-$3E`. Masked phase: the projection, then the draw phase `$18-$3B`. Bucket pass: `$18-$2D`, `BK_MODE` `$34-$36`. Load: `GC_*` `$18-$36`, `LP_*` `$38-$41`. Tics: `GC_*`, the object API's pointers `GC_MP`, `GC_SP`, `GC_LP`, `GC_XP` `$38-$3F`, `FC_GRP`, `FC_SLOT` `$40-$41` |
| `$42-$47` | none | No symbol: never live across a SmartPort call. The ProDOS block driver's parameters (command, unit, buffer, block): `DOOM.SYSTEM`'s reads of the settings' blocks, and SAVE SETTINGS's write, which keeps the six bytes and puts them back |
| `$48-$AF` | overlay 2 | Replay `$48-$6F` (39 B). Front end: the seg page `$48-$AE`. Masked: `$48-$AC`, draw phase `$48-$9E`. Bucket pass: `BK_NB` `$70`, `BK_FIRST` `$71-$9E`, `ZLOOP` `$A0-$A9`. Load: `AM_*`, `LG_*` `$48-$74`, `GS_*` `$75-$AE`. Tics: `GA_0-19` `$48-$5B`, `GT_0-24` `$5C-$74` (the API's own at `$63-$74`). 2D: the drawers' `S2_*` `$48-$77`, `S2P_*` `$78-$7F`, `pl_poll`'s `PLZ` over `$5A-$69`, each mode image's own `$80-$AF`. `DLINIT`: `dli_send`'s `$80-$84`, the settings' `SZ_*` `$86-$A0` |
| `$B0-$D7` | math | The math's block (`src/native/math.inc`) |
| `$D8-$F6` | IRQ | The music player's 31 B (`SNDZP`) |
| `$F7-$FC` | IRQ | The effect player's `FXZ_*`; with an AppleMouse II `$F9-$FB` also hold the switches' states in `ap_irq` |
| `$FD-$FF` | IRQ | Free on the Appletini. With an AppleMouse II: its X for the poll (`AP_X`, `$FD-$FE`) and its button and count (`AP_SB`, `$FF`) |

The aux zero page and aux stack are unused (rule 7).

**The stack** is main page 1. Budgets (with 24 B for the IRQ on top):

| Phase | Stack |
| --- | --- |
| Tics | 160 B from the drivers' S `$01EF` (`glayout.TIC_STACK`); the play kernel's S is higher |
| Render | 112 B (`rlayout.RENDER_STACK`) |
| Replay | 14 B below the caller's S; S stays at or above `$01C0` |
| IRQ | 24 B on top of any phase |

**Page 1 below the stack**, by phase:

| Range | Phase | Content |
| --- | --- | --- |
| `$0100-$018F`, `$0190-$01B4` | replay | The gather's 12 copy descriptors of 12 B; its per-row copy loop (37 B, copied from `p1_image` in card bank 2 at each call) |
| `$0100-$01B3` | bucket pass | The chunk of the staging (180 B), between gathers |
| `$0100-$017F` | 2D | `newColors`' bounce (`s2_begin`) |
| `$0100-$014F` | tics, load | The object API's window: `gobj.s` `pw_go` (55 B) and 4 descriptors of 6 B (`glayout.TIC_PAGE1`), copied there by `go_reset` at each tic phase's and load's start |

## 3. Main memory `$0200-$BFFF`

### 3.1 `$0200-$03FF`

| Range | Content |
| --- | --- |
| `$0200-$0277` | Render: the far bounce buffer, five segs of 24 B. After the masked phase: `BKFAR2` (233 B to `$02E8`), the bucket pass's second RAMRD-off part. Tics: `BL_BUF`, `bl_get`'s block list (to `$02FF`) |
| `$0280-$02FF` | Render: the zero-page spill (the walk `$0280-$028F`, the seg descriptor's cold part `$0290-$02BE`, the corner cache's `CC_ST` `$02BF-$02C3`) |
| `$0300` | The cost phase (profiling builds only) |
| `$0310-$036F` | The render frame block (95 of 96 B); `$0332-$0333` is `validcount`, shared with the game (`G_VALID`) |
| `$0370-$039F` | The render inputs: the view, extralight, the fixed colormap, gamma, the psprites, the player's sector light, invisibility |
| `$03A0-$03A3` | The level's counts of sectors and sides |
| `$03A4` | `LV_VARMAP`: the map whose variant columns are in the shared stores |
| `$03A6-$03AD` | The level's counts of lines, subsectors, segs, nodes |
| `$03AE` | `PL_STATUS` / `LV_STATUS`: the boot's, the load's and the 2D stops' code |
| `$03AF` | `LV_AMEM`: the memory API's result of a refused request |
| `$03B0-$03B1` | `GS_STATUS`, `GS_ARG`: the tic phase's stop code and its argument |
| `$03B3-$03ED` | The input block: the event queue (15 × 3 B), its head and tail, the held key, the Apple keys and buttons, mouse motion and last X, repeat, deferrals, `PL_BIND` |
| `$03EE-$03EF` | `PRND`, `MRND`: `P_Random`'s and `M_Random`'s indexes |
| `$03F0-$03FF` | The //e ROM's soft vectors, set once at the boot. The game's IRQ vector is `$FFFE` in the card |

The boot clears `$0200-$02FF`, `$0C00-$1FFF` and `$BF00-$BFFF`.

### 3.2 `$0400-$0BFF`: read-only (rule 3)

| Range | Content | Loaded |
| --- | --- | --- |
| `$0400-$04FF`, `$0500-$05FF` | Colormap A, light levels 32 and 33 | Each level, PRIVATE from `LVC`; again after any firmware call (rule 9) |
| `$0600-$06FF`, `$0700-$07FF` | Colormap B, levels 32 and 33 | Same |
| `$0800-$0821` | `CMPA`: the page of colormap A by light level | Boot, PRIVATE (DLINIT) |
| `$0822-$0843` | `CMPB` | Same |
| `$0844-$0867` | The benchmark timing's `bt_ext` (part of `bt_mark`), written by the brain's `bt_start` at each benchmark's start | CPU, the benchmark only |
| `$0868-$0874` | With a VidHD only: `vh_sc` (section 10) | The boot |
| `$0878-$087F` | **Never written** (rule 8) | |
| `$0880-$08F2` | The kernel's menu loop and `bt_mark` (`BT_MARK` `$08CA`), segment `DLKMAIN` | Boot, PRIVATE (DLINIT) |
| `$0900-$09A8` | `TEXLO`: the texture row block's low byte for rows 0-168 | Boot, PRIVATE |
| `$09A9-$0A49` | `XTVLO`: `xtoviewangle`'s low bytes, x = 0-160 | Boot, PRIVATE |
| `$0A4A-$0AF2` | `TEXHI` | Boot, PRIVATE |
| `$0AF3-$0B93` | `XTVHI` | Boot, PRIVATE |
| `$0B94-$0BFF` | The menu loop's second part and `bt_mark`'s last (`BT_MARK2` `$0BE1`), segment `DLKMAIN2` | Boot, PRIVATE |

The replay reads `CMPA` and `CMPB` indexed by upstream's own `R_CMP`
byte (`$46` + level), as `CMPA-$46,Y`, so records keep upstream's value
and no page is crossed.

### 3.3 `$0C00-$1FFF`: renderer state and game globals

Arrays are a byte a column, x = 0-159. "Persistent" rows live across
frames; the tic phase may overlay only the others (`glayout.py` checks
it).

| Range | Content | Persistent |
| --- | --- | --- |
| `$0C00-$0C9F` | `FLOORCLIP` | no |
| `$0CA0-$0CFF` | Render scratch | no |
| `$0D00-$0D9F` | `CEILCLIP` | no |
| `$0DA0-$0DFF` | The wall setup's variables, render scratch | no |
| `$0E00-$0E9F` | `SOLIDCOL`; in the masked phase `MCCLIP` | no |
| `$0EA0-$0EFF` | Render scratch | no |
| `$0C00-$0E6C` | After the masked phase: `BKFAR`, the bucket pass's RAMRD-off code (621 B, with the release build's replay cut `rp_cut`), copied there by `nm_bkload`. Tics: `MOC`, the mobj cache (8 lines of 96 B, to `$0EFF`) | no |
| `$0F00-$13FF` | The fill spans: `FSTOP`, `FSBOT`, `FSEVT`, `FSEVB`, `FSODT`, `FSODB`, `FSSTT`, `FSSTB`, 160 B each | **yes** |
| `$1400-$167F` | The covered ranges: `CVFIRST` (0 none, 255 a shadow), `CVEND`, `CVRECLO`, `CVRECHI`, 160 B each. `CVFIRST` and `CVEND` are zero between frames | **yes** |
| `$1680-$1720`, `$1721-$17C1` | `COLLO`, `COLHI`: column c's first record in the batch, 161 entries. In the masked phase `UPOFS` (`$1680-$171F`) and `FRORD` (`$1720-$176F`). Tics: `SCC`, the sector cache (8 lines of 48 B, `$1680-$17FF`) | no |
| `$17C2-$17FF` | Replay scratch (gather and bucket pass, never in the draw pass) | no |
| `$1800-$189F` | `WCLIP`: the weapon skip | **yes** |
| `$18A0-$18AB` | `WPREV`: the weapon vissprite of the frame before (12 B) | **yes** |
| `$18B0-$18BB` | `FRVIS`: this frame's weapon vissprite (12 B) | **yes** |
| `$18E0-$197F` | `WTMP`: a sprite's floor clip in a frame that skips the weapon rows | **yes** |
| `$1980-$1A7F` | Render: `DSX1`, `DSX2`. After the masked phase: `CVDONE` `$1980-$1A1F`, the batch sizes `BK_SZLO`, `BK_SZHI` `$1A20-$1A79`. Tics: the runtime's state (163 of 256 B: the caches' tags, dirty bits and orders; `SLOT_GRP` 19 B, `SLOT_NEED` 18 B, `FS_DIRTY`, which `K_TIC` sets to `$FF`; the walk's thinker; the counters) | no |
| `$1A80-$1B7F` | `TEXTRANS`: `texturetranslation` as bytes | **yes** |
| `$1B80-$1C7F` | `LNMAP`: `ML_MAPPED` of 2,048 lines, a bit each | **yes** |
| `$1C80-$1EF8` | The game globals block (`GBLOCK`): the player (148 B), the buttons, the thing pool's bitmap, the thinker list, the sector nodes' free list, the specials' counts and free lists, the zone's mobj count, the blockmap's and reject's places, the level time, the game's state, `G_MOHWM`, the intermission's counters | **yes** |
| `$1EF9-$1EFB` | `G_WSET` (the map the level window holds), `G_FPSSHOW`, `G_ONGROUND` | **yes** |
| `$1EFC-$1EFF` | free | |
| `$1F00-$1F7F` | `DLM`: the main loop's state `DL_*` (122 of 128 B), with the benchmark's `DL_BENCH`, `DL_BVIEW`, `DL_BRT` and its timing's `BT_*` | **yes** |
| `$1F80-$1FFF` | `PL_KEYTAB`: the //e key table's Doom keys, written by `pl_keys.s` (the boot's defaults, the key setup) and, once at the boot, by `DLINIT`'s `dli_apply` (the keys of `DOOM.SETTINGS`) | **yes** |

### 3.4 `$2000-$5FFF`: colormaps and the frame slots

| Range | Content | Loaded |
| --- | --- | --- |
| `$2000-$3FFF` | Colormap A, light levels 0-31: level L at page `$20+L` | Each level: one PRIVATE COPY from `LVC` with `$0400-$07FF` |
| `$4000-$5FFF` | Colormap B, levels 0-31: level L at page `$40+L`. Page `$40` covers `$4078-$407F` (rule 8) | Same |

**The frame slots.** Only the replay reads these pages, so during the tic
phase they hold the placement's pinned groups (`glayout.frame_slots`).
Each pinned group (slot 3 and up in `tools/native/gplace-f122.json`) has a
place of its own: its bytes plus 96 B, rounded up to pages, packed
largest first, none across `$4000`, 64 pages in all, at most 15 slots.
The shipped placement pins 11 groups into `$2000-$5F57`.

- `gcall.s`'s `gr_load` copies a pinned group in by one PRIVATE request
  (`am_one`) at its first call in a frame.
- `fs_restore` puts back every loaded slot's colormap bytes from `LVC`
  (`LVC_CMAPA` `$0200` for `$2000-$3FFF`, `LVC_CMAPB` `$2400` for
  `$4000-$5FFF`) in one request, a descriptor a slot. It is the brain's
  last step (`dl_brain.s`), which every path from the tic phase to a
  replay passes.
- Rule 3 holds: `playdisk.py` checks that no absolute store of the tic
  code targets `$2000-$5FFF`, and the placement keeps out of the frame
  slots every routine the tic code stores into.

## 4. W, `$6000-$BFFF`, by phase

W holds one image at a time. Every image comes from its RamWorks bank at
W's addresses by one memory-API PRIVATE request a load (W is never shown),
or by the CPU without the API. The tic image, `P2DW` and the front end
link `MATHW` (1,281 B) and `AUXW` (146 B) at `$6000-$6592` with the same
bytes, so `K_TIC` after `P2DW` loads from page `$66` and the front end
from page `$65` (`playdisk.shared_w_problems` asserts it).

**The tic phase** (`glayout.W_MAP`):

| Range | Content |
| --- | --- |
| `$6000-$65FF` | `MATHW`, `AUXW` |
| `$6600-$99FF` | The core (13,312 B room; `$6600-$992E` used): the runtime (`gcall.s`, `gobj.s`), the game core of the level setup, the game's math, `weaponinfo`, the glue's resident parts, and the routines the placement puts there |
| `$9A00-$9DFF` | The parts' scratch blocks `SB_<PART>` |
| `$9E00-$A5FF` | Slot 1: one paged group (2,048 B) |
| `$A600-$ADFF` | Slot 2: one paged group (2,048 B; the brain's group `DLG_B` runs here) |
| `$AE00-$B3FF` | `GW`: the line cache (8 × 34), the special cache (5 × 32), the intercepts (64 × 6) and their chain, the core's buffers, then the tic phase's near scratch `GM_*`, `SD_BUF`, `SN_BUF`, `API_W` (`$AE00-$B357` used) |
| `$B400-$BFFF` | The thinker walk's planes, 768 slots each: `TNL` `$B400`, `TNH` `$B700`, `KIND` `$BA00`, `TICS` `$BD00` |

**The front end** (`WCODE`, bank 112; `rlayout.regions()`):

| Range | Content |
| --- | --- |
| `$6000-$A596` | `MATHW`, `AUXW`, then the front end's code `RENDERW` (room to `$ACFF`) |
| `$AD00-$AD9F`, `$AE00-$AE9F` | `FCNTLO`, `FCNTHI`: each column's count of W bytes of the front end's records |
| `$AFC0-$B3FF` | `FLATCM`, per level |
| `$B400-$B8FF` | `TXBANK`, `TXLO`, `TXHI`, `TXWM`, `TXHT`, per level; kept by the masked phase |
| `$B900-$B9FF` | The record batch buffer; kept by the masked phase |
| `$BA00-$BC7F` | The walk's node frames, 20 × 32 B. Before the walk, the weapon clip pass's profile (`WPENT`, `WPLST`, `WPHB`, `WSFR`, `WPHD`) |
| `$BC80-$BDBF` | `FSTEP` of the seg's columns |
| `$BDC0-$BEFF` | The seg's masked texture columns |
| `$BF00-$BF27` | The wall's front sector, side and back sector |
| `$BF28-$BFC7` | `DLW`: each column's light distance |
| `$BFC8-$BFE7` | `DSBUF`: the drawseg being built |

The front end's load takes the code's pages and the table pages
`$AF00-$B8FF`.

**The masked phase** (`MCODE`, bank 113; loaded over the front end, which
leaves `MATHW` and the tables in place):

| Range | Content |
| --- | --- |
| `$6600-$669F`, `$6700-$679F` | `MCNTLO`, `MCNTHI`: the masked phase's column counts, from which the bucket pass makes its batches |
| `$6800-$8BA4` | `MASKW`: the masked code, `nm_bkload`, the bucket pass's `nb_bucket` (and the release build's recount, walk 1), and `BKFAR`/`BKFAR2` as data after it (room to `$9BFF`) |
| `$9C00-$A3FF` | `DSW`: the drawsegs whose `DSX1` is not 255, 32 B each, at most 64 |
| `$A400-$B07F` | The vissprites, 80 of 40 B |
| `$B080-$B15B` | `SPRBOUND` for the frame (from `SPRT`) |
| `$B160-$B1FF` | Fetch buffers: the sprite frame, the listed sector, the patch header, a seg, a side, the sectors, a drawseg; `WVIS` |
| `$B200-$B3FF` | `TXMP`, per level |
| `$B400-$B9FF` | The front end's tables and batch buffer, kept |
| `$BA00-$BE01` | `SECLIST` during the projection, then `YHTAB` (two planes of 512); the weapon draw's profile entries |
| `$BE02-$BEA1` | `CLIPBUF`: a drawseg's clip run |
| `$BEA2-$BFE1` | `MTCLO`, `MTCHI`: a masked range's texture columns |

**The automap overlay** (`OVLW`, bank 93): stored `$6800-$7C63` in the
masked code's room, run time `$9400-$9BFF` (its nibble pages, caches,
`s2_amline`'s variables at `$9A00`, its state at `$9B00`). It runs after
the masked phase, before the bucket pass, when the overlay is on.

**The replay** (W free of code; section 9): the record buffer
`$6000-$7FFF` (one batch) and the texel stage `$8000-$BFFF`.

**The load image** (`LCODE`, bank 98; `llayout.LW_*`):

| Range | Content |
| --- | --- |
| `$6000-$6592` | `MATHW`, `AUXW` |
| `$6600-$8FFD` | The load code `LOADW` (room to `$9FFF`) |
| `$A000-$A113` | A memory-API request: 20 B of header, 16 descriptors |
| `$A000-$B3FF` | During the `GROUP` and `FLOOD` steps: each line's front and back sector, each sector's line count, first entry and two running positions |
| `$AC00-$AD97`, `$AE00-$AEFF` | During the setup: the mobj being made, its `mobjinfo` record, a state, a node, a line, a map thing, a sector's records, a special, a sector node, a block's line list |
| `$B400-$B7FF` | `CMAPS`: GSVIEWn's tables A and B, a page of `COLORMAP`, the page made; `FLOOD`'s page of zeros |
| `$BC80-$BED5` | The map's header, the store's directory, the program's head and steps, the requests' places, a few records |

**The 2D images** (`s2layout.IMAGE`; one at a time, each with `MATHW` and
`AUXW` at `$6000-$6592`):

| Image | Bank | Stored room (used) | Run-time room |
| --- | --: | --- | --- |
| `P2DW`: status bar, HUD, palettes, input poll, effect service, the frame glue | 107 | `$6600-$82FF` (`$6600-$7E51`) | `$8300-$BFFF`: the band, marks, eight nibble slots, fetch buffer, state block `$BC00` |
| `MENUW`: the menus, the channel logic | 108 | `$6600-$A4FF` (`$6600-$94CC`) | `$A500-$BFFF`: `PALST`, band, `UI_GRAY`, marks, nibble slot, fetch buffer, state `$BF00` (`M_SETCHG` `$BF5F`: SAVE SETTINGS lit; `M_SAVERES` `$BFDB`: `dli_save`'s answer) |
| `AMAPW`: the full automap | 94 | `$6600-$8DFF` (`$6600-$8128`) | `$8E00-$BFFF`: band, marks, state `$AC00`, the new byte list |
| `WIW`: the intermission | 95 | `$6600-$7FFF` (`$6600-$79FD`) | `$8000-$BFFF`: band, marks, nibble units, fetch buffer, state `$BC00` |
| `FINW`: the finale, pages, signs | 96 | `$6600-$7FFF` (`$6600-$7B1E`) | Same as `WIW` |
| `PALW`: tints and nibble tables | 97 | `$6600-$7FFF` (`$6600-$6940`) | `$8000-$BFFF`: its buffers |
| `DLINIT`: the boot's static copies and settings, the quit's screen, SAVE SETTINGS's write | 1 | `$6600-$6A31` | `$6E00-$6EFF`: the static tables' request; `$7000-$743F`: the settings file being made, the settings as the disk has them, the 64 slot holes (`dli_apply`, `dli_save`) |

## 5. The main language card

Installed at the boot by CPU copy from `LC.BIN`; the memory API cannot
write the card. The CPU-copy transport and the AppleMouse II's and
VidHD's code are written over free bytes only on machines that need them
(section 10).

**Bank 2, `$D000-$DFFF`: the replay** (selected only while it runs):

| Range | Bytes | Content |
| --- | ---: | --- |
| `$D000-$DBCF` | 3,024 | Texture row blocks: row pair p at `$D000 + 36p` (`rowgen.py`) |
| `$DBD0` | 1 | Row 168's landing: `RTS` |
| `$DBD1-$DBF8` | 40 | `p1_image` (the per-row copy loop, 37 B, copied to page 1 `$0190`) and `jtent` (3 B) |
| `$DBF9-$DBFF` | 7 | free |
| `$DC00-$DCFB`, `$DCFC` | 253 | Fill row blocks of the even rows: row r at `$DC00 + 3 × (r >> 1)`, `STA $2000+160r,X`; landing `RTS` |
| `$DD00-$DDFB`, `$DDFC` | 253 | The odd rows, at `$DD00`; landing `RTS` |
| `$DE00-$DFFC` | 509 | The dispatcher's hot part (`RHOT`): column loop, record fetch, kind dispatch, covered-range cut, texture and fill set-up |

**Bank 1, `$D000-$DFFF`: compute** (selected in all other phases):

| Range | Bytes | Content |
| --- | ---: | --- |
| `$D000-$D7FF` | 2,048 | Quarter squares: four 512 B tables (`SQL` `$D000`, `SQH` `$D200`, ...) |
| `$D800-$DB5B` | 860 | `MATHLC`: the multiplies, `FixedMul` family, divides, helpers |
| `$DB5C-$DBFF` | 164 | `AMEMLC`: the memory-API transport, from the tic image's link. `am_req` (`$DB5C-$DB7F`: the request's head and one descriptor, a template the callers patch), then `am_begin`, `am_push`, `am_fin` and the kernel's `am_runs` |
| `$DC00-$DC42` | 67 | `MATHFAR` |
| `$DC43-$DE4C` | 522 | `far.s` (`RFAR`): `far_get`, `far_put`, the vertex-angle gather, the stamp clear, the `FSTEP` gather; `vg_n`..`vg_d` (`$DE10-$DE4C`) are the only bytes render code writes |
| `$DE4D-$DE97` | 75 | `RLOAD`: the phase loaders `far_wload`, `far_wloadt`, `far_pload` |
| `$DE98-$DFE5` | 334 | `MFAR`: `far_mload`, `far_dscopy`, `far_posts`, `far_postsc` and their 16-post buffer |
| `$DFE6-$DFFF` | 26 | free; without the memory API `AMEMCPUD` (`$DFE6-$DFFB`) |

The play kernel loads every image by memory-API request. `far_wloadt`,
`far_mload` and `far_pload` stay for the load image and the CPU version.

**`$E000-$FFFF`** (always visible):

| Range | Bytes | Content |
| --- | ---: | --- |
| `$E000-$E402` | 1,027 | The song ring (page aligned) and its mirror |
| `$E403-$E412` | 16 | The clock: `CLK_STEP` (the fraction a VBL), `CLK_FRAC`, `CLK_TICS`, `CLK_STD` (PAL or NTSC), `CLK_TIME3` (10 B used). The VBL count is `vbl_count` in the player's zero page |
| `$E413-$E442` | 48 | The effect voices, 3 × 16 B |
| `$E443-$E47F` | 61 | The tic-side 2D state: the status bar's, the HUD's, the finale's, `S2_MAIL`, the fake mobj `FM`, the listener |
| `$E480-$E4FF` | 128 | The player's write lists (one page) |
| `$E500-$E736` | 567 | The player's state: voices, shadows, song tables |
| `$E737-$E73F` | 9 | `FX_ON`, `FX_HOLD`, `FX_INVAL`, the effects' tempo, `fx_service`'s temporaries |
| `$E740-$E8BF` | 384 | The effect rings, 3 × 128 |
| `$E8C0-$E8FF` | 64 | The channel table (3 × 12 B), the mailboxes (3 × 4 B), `LS_ON`, `SND_SFXVOL` (50 B); with a VidHD `vh_kr` at `$E8F2-$E8F9` |
| `$E900-$F10F` | 2,064 | The music player's code (`SNDCODE`) |
| `$F110-$F4DC` | 973 | Its tables (`SNDRODATA`) |
| `$F4DD-$F504` | 40 | free; with an AppleMouse II `ap_swap` and `ap_hb` |
| `$F505-$F8DB` | 983 | `FXCODE`: the effects' card part (`fx_step`, `fx_burst`, `fx_song`, ...), `pl_vbl` (`$F7E8`, the IRQ entry), `pl_crash` (`$F83E`), the clock and `pl_time`, then the boot-time `pl_detect` (`$F88E`) and `pl_wait` (`$F8D5`); with an AppleMouse II `ap_irq` replaces `$F88E-$F8FD` |
| `$F8DC-$F8FF` | 36 | free |
| `$F900-$FD89` | 1,162 | `RCODE`: the replay's `$E000` part: batches and strips, the gather, the texture cut, the fill chains' set-up, the aux-0 drawers' calls, the covered-range clear |
| `$FD8A-$FE40` | 183 | `BKNEAR`: the bucket pass's window part, parking and bring-back |
| `$FE41-$FE7A` | 58 | free; without the memory API `AMEMCPUF` (`$FE45-$FE6F`); with a VidHD `vh_wa` (`$FE70-$FE78`) |
| `$FE7B-$FE7F` | 5 | `KVARS`: the kernel's bytes |
| `$FE80-$FEFF` | 128 | `DLBUF`: the step list |
| `$FF00-$FFA6` | 167 | The kernel (`dl_kern.s`, `pl_ready`'s place): `run`, the steps, `dl_halt` (`$FFA4`) |
| `$FFA7-$FFB7` | 17 | Padding; with a VidHD `vh_go` |
| `$FFB8-$FFC3` | 12 | `KLISTS`: `K_TIC`'s two load lists `k_core` and `k_planes`, rewritten by the tic image's `dl_disp.s` each frame |
| `$FFC4-$FFD4` | 17 | `bt_replay` (`BT_REPLAY`): the benchmark timing's replay entry |
| `$FFD5-$FFF7` | 35 | `far_gcopy` (`KERN_GCOPY`): a group's copy in one RAMRD window; no game code calls it |
| `$FFF8-$FFF9` | 2 | free |
| `$FFFA-$FFFF` | 6 | Vectors: NMI, reset (unused), IRQ/BRK → `pl_vbl` |

## 6. Aux card: read-only trig tables

Loaded at the boot with `LC.BIN`'s aux half. Read by main code in SEI
windows (rule 7): ALTZP on, one to three loads into registers or main
memory, ALTZP off. No vectors.

| Range | Bytes | Content |
| --- | ---: | --- |
| Bank 1 `$D000-$D7FF` | 2,048 | `finetangent` part 3: 1,024 words as low and high planes |
| Bank 1 `$D800-$DFF9` | 2,042 | `viewangletox`, one plane of bytes (values 0-160) |
| Bank 1 `$DFFA-$DFFF` | 6 | free |
| Bank 2 `$D000-$DFFF` | 4,096 | `finetangent` part 4: 1,024 longs as four planes (needs bank 2 selected) |
| `$E000-$FFFF` | 8,192 | `tantoangle` 0-2047 as four planes of 2,048. Entry 2048 is the constant `ANG45` in code |

`finesine` and the other math tables live in RamWorks (banks 120-122);
`xtoviewangle` lives in main `$09A9` and `$0AF3`.

## 7. Aux bank 0

| Range | Bytes | Content | Loaded |
| --- | ---: | --- | --- |
| `$0000-$01FF` | 512 | unused (rule 7) | |
| `$0200-$0270` | 113 | The screen-reading drawers as loops: fuzz and the automap overlay. They run with RAMRD and RAMWRT on | Boot, PRIVATE |
| `$0271-$02BF` | 79 | free (read-only data only) | |
| `$02C0-$03FF` | 320 | The replay's fuzz queue: 80 records as `FQCOL`, `FQROW`, `FQCNT`, `FQPOS` | Scratch |
| `$0400-$07FF` | 1,024 | free (read-only data only) | |
| `$0800-$08FF` | 256 | `FUZZDARK`: the darker colour of each colour | Each level, PRIVATE |
| `$0900-$09C7` | 200 | `ROWLO`: the SHR row address, rows 0-199 | Boot, PRIVATE |
| `$09C8-$09F9` | 50 | `FZDIR`: the fuzz direction by position | Boot, PRIVATE |
| `$0A00-$0AC7` | 200 | `ROWHI` | Boot, PRIVATE |
| `$0AC8-$0BFF` | 312 | free (read-only data only) | |
| `$0C00-$15FF` | 2,560 | `OPENLO`: the openings' low bytes | Scratch |
| `$1600-$16FF` | 256 | `SPRSEC`: the listed sectors (the walk writes a byte a sector) | Scratch |
| `$1700-$1FFF` | 2,304 | free | |
| `$2000-$88FF` | 26,880 | The 3D view: rows 0-167 × 160 B; the only range the replay writes | CPU stores |
| `$8900-$9CFF` | 5,120 | Status bar rows 168-199 | CPU stores |
| `$9D00-$9DC7` | 200 | SCBs | CPU stores |
| `$9DC8-$9DFF` | 56 | zero (rule 10) | |
| `$9E00-$9FFF` | 512 | 16 palettes | CPU stores |
| `$A000-$BFFF` | 8,192 | The record staging: the producers append records with their column byte; beyond 8 KB they spill to `RECSP` | Scratch |

## 8. RamWorks banks

`llayout.bank_map()` names every bank and fails on one named twice;
`s2layout.py` adds the 2D banks. The disk's bank files are written by
`playdisk.py`: the level store's files, `CODE.1`, `CODE.2`, `PLAY.1`,
`RTABLES.1`, `SONGS.1`, `SFX.1`, `GFX.1`, `HUDTXT.1`.

| Bank | Name | Content |
| --- | --- | --- |
| 1 | `DLBANK` | The static tables' PRIVATE request (`$0200`), their sources (`$1000-$1FFF`), the settings (`SET_FILE` `$3000-$31FF`: `DOOM.SETTINGS` as `DOOM.SYSTEM` read it, then the settings as the disk has them, `DLINIT`'s; `SET_INFO` `$3200-$3205`: the flags, the boot unit, its block driver's entry, the file's block; `docs/PLAY.md`, "The settings file"), `DLINIT`'s image (`$6600`) |
| 2-5 | | spare |
| 6 | `LVSEG` | The level's segs, 24 B |
| 7 | `LVMAP` | Nodes (32 B, `$0200`; bytes 28-29 the corner cache's tag), subsectors (`$6200`), the vertex cache (three planes, `$6E00`), sectors (16 B, `$8000`; offset 13 the thing list's head), sides (8 B, `$9000`; byte 7 the sector), patchless bitmaps `TXFLAT` (`$B000`) |
| 8 | `RENDB` | 128 drawsegs of 32 B (`$0200`), `OPENHI` (`$1200`), the corner cache's state (`$1C00`) and angles (`$2040`) |
| 9-31, 56-63 | `TEX` | The texel store: 128 B a column, every texture any map shows, and the sky |
| 32-47, 64 | `SPR` | The patch store: each lump whole, then its 128-byte tail |
| 48 | `SPRT` | Scale records (`$0200`), `SPRBOUND` (`$5400`, written at the disk's build), `PHDR` (`$5600`), each map's `SPRFR` (`$7E00`) |
| 49 | `WPRO` | The weapons' profiles: `WPIDX` (`$0200`), the profiles from `$0700` |
| 50 | `RTH` | The render things: 2,026 slots of 24 B from `$0200` |
| 51-54 | `RECSP` | The record spill beyond aux 0's staging |
| 55 | `RECW` | A group's batches 2 and 3, parked by the bucket pass |
| 65 | `LVG0` | The lines, 32 B (`$0200`, at most 1,520) |
| 66 | `LVG1` | The sectors' game part (32 B), the line tables, the flood index and entries, the blocklinks |
| 67 | `LVG2` | The blockmap, then the reject matrix |
| 68 | `LVC` | Colormap A (`$0200`), B (`$2400`), 8,704 B each; the `GSVIEWn` record (`$4600`); `FUZZDARK` (`$4AC0`) |
| 69-71 | `MOBJA`-`MOBJC` | Each mobj's game part in three groups of 24 B, at its `RTH` slot's address |
| 72 | `GCODE0` | The tic image: W and the core at W's addresses, and groups packed from `$0200` |
| 73 | `GCODE1` | More groups |
| 74 | `MOBJP` | The thinker planes out of W (`TNL` `$B400`, `TNH` `$B700`, `KIND` `$BA00`, `TICS` `$BD00`) and the sight hint by pool slot (`HINTL` `$0200`, `HINTH` `$0A00`) |
| 75 | `ZONE0` | The specials: 32 B records from `$0200`, a range of slots a kind; a thinker handle is `$0800` + slot |
| 76 | `ZONE1` | The sector nodes, 16 B each, in pools of 32 |
| 77-90 | `STORE` | The level store: its directory at bank 77 `$0200`, the nine level parts |
| 91 | `DEMOB` | The demo lumps for the title loop |
| 92 | | spare (test builds' `GTEST`) |
| 93 | `S2OVLW` | `OVLW` |
| 94-97 | `S2CODE2`-`S2CODE5` | `AMAPW`, `WIW`, `FINW`, `PALW`, one image a bank |
| 98 | `LCODE` | The load image at W's addresses |
| 99 | `GTAB` | `states`, `mobjinfo`, `COLORMAP`, `switchlist`, `SW_IDX`, the slime's first texture |
| 100-102 | `SONGS` | The songs' directory (bank 100 `$0200`), the 13 songs |
| 103 | `SFX` | `SFX.1` (`$0200-$3FFF`), the 2D store `$4000-$BFFF` |
| 104 | `S2STATE` | The 2D state between frames: `PALST`, each image's state block, the settings, `STCACHE`, the HUD's texts, the automap's old list and lines, the busy sign's rows, `STBUF` |
| 105 | `S2VIEW` | The menu's saved screen `$2000-$9FFF`; the 2D store around it |
| 106 | `S2PAL` | `TINTPAL` (`$0200`), the 16 nibble tables (`$1800`), `GSSTAT` (`$5800`), `GSOVL` (`$6E20`), `GRAYMAP` (`$7700`) |
| 107 | `S2CODE0` | `P2DW`; 2D store at `$0200-$5FFF`, `$8300-$BFFF` |
| 108 | `S2CODE1` | `MENUW`; 2D store at `$0200-$5FFF` |
| 109, 110, 114, 115 | `GFX0`-`GFX3` | The 2D store (`GFX.1`; its handles table at 109 `$0200`) |
| 111 | `LVS` | `LNSECF` (`$0200`), `LNSECB` (`$0800`): each line's front and back sector; `RJROW` (`$0E00`) |
| 112 | `WCODE` | The front end's image at W's addresses, with the level's W tables |
| 113 | `MCODE` | The masked phase's image (`MASKW`, `TXMP` at `$B200`) |
| 116-119 | `FSTEP` | `FSTEP_TABLE`: low plane `$2000-$5FFF`, high plane `$6000-$9FFF` |
| 120 | `MT_TBANK` | Sine (`SINELO` `$2000`, `SINEHI` `$4000`), tangent to angle, quarter sine |
| 121, 122 | `MT_RLO`, `MT_RHI` | The reciprocal table's low and high bytes |
| 123, 124 | `LOGTAB` | Reserved by `llayout.py`; unused |
| 125, 126 | | spare |

## 9. The replay's addresses

| Part | Where | Bytes | Notes |
| --- | --- | ---: | --- |
| Texture row blocks | Card bank 2 `$D000-$DBCF`, landing `$DBD0` | 3,025 | Row r enters at `TEXHI[r]:TEXLO[r]`; the exit is the first byte of row e, patched to `RTS` and restored |
| Fill row blocks | Bank 2 `$DC00-$DCFC`, `$DD00-$DDFC` | 506 | A fill record runs both chains, each with its parity's byte |
| Dispatcher, hot | Bank 2 `$DE00-$DFFC` | 509 | Entered from `RCODE`, which selects bank 2 before and bank 1 after |
| Dispatcher, rest; gather | Card `$F900-$FD89` | 1,162 | The gather's copies run with RAMRD on |
| Gather descriptors, copy loop | Page 1 `$0100-$018F`, `$0190-$01B4` | 181 | S at or above `$01C0` |
| Fuzz and overlay drawers | Aux 0 `$0200-$0270`; tables aux 0 `$0800-$0AC7` | 113; 706 | Entered with RAMRD on |
| Fuzz queue | Aux 0 `$02C0-$03FF` | 320 | Written in the draw (RAMWRT on), read with RAMRD on after the strip's columns |
| Entry tables | `TEXLO` `$0900`, `TEXHI` `$0A4A` | 2 × 169 | |
| Colormap page tables | `CMPA` `$0800`, `CMPB` `$0822` | 2 × 34 | Indexed `CMPA-$46,Y` by `R_CMP` |
| Colormaps | A: pages `$20-$3F`, `$04`, `$05`. B: `$40-$5F`, `$06`, `$07` | 17,408 | |
| Record buffer | W `$6000-$7FFF` | 8,192 | Column c's records from `COL[c]` to `COL[c+1]` |
| Column starts | `COLLO` `$1680`, `COLHI` `$1721` | 2 × 161 | |
| Texel stage | W `$8000-$BFFF` | 16,384 | |
| Covered ranges | `CVFIRST` `$1400`, `CVEND` `$14A0`, `CVRECLO` `$1540`, `CVRECHI` `$15E0` | 4 × 160 | The replay zeroes `CVFIRST` and `CVEND` of a strip's columns after its draw pass |
| Zero page | `$48-$6F` | 40 | 39 B used |
| Scratch | Main `$17C2-$17FF` | 62 | Gather and bucket pass only |
| Screen | Aux 0 `$2000-$88FF` | 26,880 | The only screen bytes it writes |

**The fuzz queue.** The draw queues each `K_FUZZ` record and draws the
queue after the strip's columns, in one RAMRD window. On the Appletini a
RAMRD switch waits for the screen bytes written so far to be sent, so a
fuzz record drawn in place would wait twice. A fuzz record that a later
record of its column paints over or next to (rows `R_ROW - 1` to
`R_ROW + R_COUNT`) is drawn in place: the producer writes it as
`K_FUZZNOW` (kind 4, not an upstream kind). So is one the full queue has
no room for.

**Batches and strips.** A frame whose packed records pass 8,192 B is cut
by column range into batches, whole columns each (at most 45:
`rlayout.MAXB`). Each column's records keep their order and the
covered-range cut depends only on the column, so the pixels are
upstream's. Within a batch, when the stage is full the replay draws the
columns gathered so far (a strip).

**The stage.** For each `K_TEX` or `K_TEXC` record the gather copies one
texel a row (when the chain's step is 2 or more and the record has at
most 128 rows) or the span the record steps over. A span that wraps past
texel 127 copies its two used runs. The records in W are never written:
each texture record's stage pointer goes on a list at the stage's top.

**The copies in groups.** The gather queues a descriptor a texture record
in page 1 and runs the queue when it holds 12 and at each strip's end:
RAMRD on, one `$C073` write for each texel bank in the group, `$C073`
back to 0, RAMRD off.

## 10. Machine variants

Each variant is written by `DOOM.SYSTEM` after the install, with
interrupts masked, from tables `playdisk.py` fills: a record is a length,
a bank (0: main memory or the card), an address, the bytes. On the
Appletini with its mouse card and the memory API, none of them is written
and the card and every bank file are as linked.

### Without the memory API

`probe_amem` writes nothing to slot 7 until its ROM reads as the
Appletini's (the SmartPort ID bytes `$C701`, `$C703`, `$C705`, `$C707`,
`$C7FF`, then `$CFF1`). Without an API, `am_patch` writes `bt_patch`'s
records (512 B in `DOOM.SYSTEM`, built by `tools/native/amcpu.py`): every
request is then made by the CPU, byte for byte, at the same point.

| Space | Range | Without the memory API |
| --- | --- | --- |
| Card bank 1 | `$DB5C-$DB6F` | `am_req`'s head: `cq`, the descriptor the CPU makes, and `cj` |
| Card bank 1 | `$DB70-$DB7F` | The template's descriptor, kept |
| Card bank 1 | `$DB80-$DBFD` | `AMEMCPU`, with `AMEMLC`'s entries: `am_begin` an RTS, `am_push` (`cli`, the descriptor into `cq`, `cx_exec`), `am_runs` a JMP to `far_pload`, `am_fin` (`plp`, `rts`). `cx_exec` sets RAMRD for the source, RAMWRT for the destination, `$C073` to their bank, and copies a part page at a time |
| Card bank 1 | `$DFE6-$DFFB` | `AMEMCPUD`: `cx_chunk` |
| Card `$E000` part | `$FE45-$FE6F` | `AMEMCPUF`: the inner loops `cx_fast`, `cx_fill`, `cx_tog` (bank to bank: `$C073` switched at each byte, as RAMRD and RAMWRT share it) |
| `LCODE` | `am_send` | A 53-byte walker of the request at `LW_REQ` through `cx_exec` |
| `DLBANK` | DLINIT's `dli_send` | The walker of the request at `$6E02`, then `dli_screen` |
| `MENUW` | `mv_amem` | The walker of the screen save (aux 0 `$2000-$9FFF` to `S2VIEW`) |
| `FINW` | `sgsave` | The walker of the busy sign's save (aux 0 `$5700`, 3,840 B, to `S2STATE`) |

The CPU copies run with interrupts enabled (rule 2 keeps the IRQ out of
`$0200-$BFFF` and `$C073`), change `FA_DST`, `FA_SRC` and `FA_N`, and
leave RAMRD, RAMWRT and `$C073` off. Rule 3's regions and rule 8's
`$4078-$407F` then get CPU stores.

### Without the Appletini mouse card: the Phasor's clock

The mouse card is taken only when slot 2's ROM has the AppleMouse ID
bytes and the Appletini's own (`$C200-$C201`, `$C20D-$C20F`). Otherwise
the interrupt is the Phasor's VIA-B timer 1, free-running at a frame's
period, and `bt_init` writes `mo_recs` and `bt_mpatch`'s records (52 B,
`tools/native/nomouse.py`):

| Space | Range | Without the Appletini's mouse card |
| --- | --- | --- |
| Card | `pl_vbody` (13 B) | `LDA $C48D`, `AND #$40`, `BEQ pl_vnone`, `STA $C48D`, 3 NOPs: the cause is VIA-B's timer 1, its flag cleared by writing it back |
| Card | `pl_crash` + 1 (8 B) | VIA-B's interrupts off |
| Main (the boot) | `pl_init`'s `pl_iwin` | `BRA pl_defaults`: nothing written to slot 2 |
| `P2DW`, `MENUW`, `WIW`, `FINW` | `pl_poll`'s read of `$C0A5`, `pl_mouse` | `LDA #0`, `NOP`; `RTS`: no button, no X |

The handler then touches only VIA-B's IFR in `$C400-$C4FF`.

### With an AppleMouse II

Slot 2 is an AppleMouse II when its ROM has the AppleMouse ID bytes but
not the Appletini's, and the firmware entries DOOM uses. Its VBL
interrupt is the clock. `bt_init` writes the records above, then
`ap_recs` and `ap_mpatch`'s (176 B, `nomouse.apple_patches`):

| Space | Range | With an AppleMouse II |
| --- | --- | --- |
| Card | `pl_vbody` (13 B) | `JSR ap_irq`, `BCS pl_vnone`, `BRA` to the clock |
| Card | `$F88E-$F8FD` | `ap_irq`, over `pl_detect` and `pl_wait` (boot-only code) |
| Card | `$F4DD-$F503` | `ap_swap` and `ap_hb` (the firmware's eight hole bytes between calls) |
| `P2DW`, `MENUW`, `WIW`, `FINW` | `pl_poll`, `pl_mouse`, `pl_centre` | The card's registers become zero page: buttons and sequence `$00FF` (`AP_SB`), X `$00FD-$00FE` (`AP_X`) |

At each interrupt `ap_irq` turns 80STORE, RAMRD and RAMWRT off (their
states in `$F9-$FB`), swaps the holes, calls SERVEMOUSE, READMOUSE (X less
512 added to `AP_X`, button 0 into `AP_SB`) and POSMOUSE back to X 512,
swaps the holes again and restores the switches. The stack use is about
18 B, within the IRQ's 24.

**No VBL from the mouse.** When `ap_clock` sees no VBL within 20 changes
of `$C019`'s bit 7, `ap_novbl` sends SETMOUSE `$01` (no interrupt) and
writes `ap_frecs`: `pl_vbody` becomes the VIA-B head with a `JSR ap_irq`,
and `ap_irq`'s SERVEMOUSE call becomes `CLC`, `NOP`, `NOP`. The mouse is
then read once a VIA-B tick.

### With a VidHD

`vh_boot` looks for a VidHD only when it found nothing of the Appletini's
(the memory API, its mouse card, its slot-7 ROM): slots 7 to 1 but 4, the
ID bytes `$24 $EA $4C` at `$Cn00-$Cn02`. With one it writes `vh_patch`'s
records (448 B, `tools/native/vidhd.py`), copies aux 0's `$2000-$9FFF`
onto itself with the shadowing on, and turns it off. Rule 11 holds from
then on.

| Space | Range | With a VidHD |
| --- | --- | --- |
| Card | `$FFA7-$FFB7` | `vh_go`: A the value; when it differs from the last (its own `CMP` operand at `$FFA8`), written twice to `$C035` between `PHP`, `SEI` and `PLP`; A, X, Y kept |
| Card | `$E8F2-$E8F9` | `vh_kr`: `STA DL_RES`, `LDA #$18`, `JMP vh_go` |
| Card | `$FE70-$FE78` | `vh_wa`: `LDA #$00`, `JSR vh_go`, `STA RAMWRTON` |
| Card | `k_call`'s `STA DL_RES` (`$FF9C`) | `JSR vh_kr`: every `K_CALL` ends with the shadowing off |
| Main | `$0868-$0874` | `vh_sc`: off, `JSR nb_scatter`, on (the replay's group) |
| `MCODE`, `OVLW` | `nb_frame`'s `JSR nb_scatter` | `JSR vh_sc` |
| `P2DW`, `MENUW`, `WIW`, `FINW` | `s2_publish`'s, `s2_begin`'s three and `s2_finish`'s `STA RAMWRTON` | `JSR vh_wa` |
| `AMAPW` | `s2_publish`'s and `pubents`' | `JSR vh_wa` |
| `OVLW`, `DLINIT` | `titleband`'s, `dli_screen`'s | `JSR vh_wa` |
| `P2DW` `$7E52`, `MENUW` `$94CD`, `AMAPW` `$8129` (8 B each, past the stored bytes in the last loaded page) | `record`'s `far_put` to `SS_HUDTXT`, `mv_open`'s `mv_amem`, `am_frame`'s `listsave` | Each call goes through `LDA #$18`, `JSR vh_go`, `JMP` the routine |
| `OVLW` `$8008` | `am_ovl`'s `JSR titleband` | `JSR titleband`, then off before its records spill to `RECSP` |
| `DLINIT` `$6A32` | `dli_quit`'s `JSR snd_stop` | `$00` written twice to `$C035` first: the quit leaves the shadowing on |

The other writes to aux `$2000-$9FFF` of other banks come with the
shadowing off: before any screen window of their step, or in steps that
write no screen (the tic phase, the loads, the front end, the masked
phase, `PALW`).

## 11. What the build checks

Besides each layout module's `check()` and the links' MEMORY areas,
`playdisk.py` and `pldisk.py` check the disk when they write it:

- every segment lies in a bank 1-126 at `$0200-$BFFF`, and no two
  segments of the disk share a byte (`pldisk.layout_problems`);
- every image links the same card parts the boot installs: the far
  layer, the math, the phase loader, the player and effects
  (`pldisk.image_problems`, `area_problems`);
- the tic image, `P2DW` and the front end share `MATHW` and `AUXW` byte
  for byte (`shared_w_problems`);
- each group's bytes against its file (`group_problems`);
- no absolute store of tic code into `$2000-$5FFF`, and each pinned group
  inside its frame slot (`frame_slot_problems`); no pinned group with
  `A2Li` at `$4078` (`a2li_problems`);
- the rooms the CPU-copy transport, the AppleMouse II handler and the
  VidHD code take are free in every link and zero in `LC.BIN`
  (`amem_cpu_problems`, `apple_card_problems`, `vidhd.card_problems`).
