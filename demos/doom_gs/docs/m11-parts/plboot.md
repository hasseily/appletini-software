# Milestone 11, part `plboot`: `DOOM.SYSTEM` and `DOOM.hdv`

Part `plboot` of wave 8 ([`docs/SCREENS.md`](../SCREENS.md) 2.5, 4.5,
6.5, 7.3, 8.2 row 4), 2026-10-02. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed. Nothing of upstream's is used: the part
has no upstream routine. Its models are our own `LEVELS.SYSTEM` boot
(`src/native/lboot.s`, read only: its bank-file loader, RamWorks probe,
memory-API probe, mouse-card probe and CRC-32), the //e kernel's loader's
`A2DM` bank files [R `demos/doom/src/kernel/loader.s:36-45`] and
`SOUNDS.SYSTEM`'s boot order (`src/sound/sounds.s`).

## 1. What was built

| File | What |
| --- | --- |
| `src/native/pl_boot.s` | `DOOM.SYSTEM`: the probes, every bank file through the MLI, the CRCs, the card images, the install, `pl_init`, `snd_init`, `fx_init` with `snd_probe`'s answer, the VBL on, `pl_detect`, the ready state; and the card's ready loop `pl_ready` (segment `PLRES`, `$FF00`). Its header is the boot's specification |
| `src/native/m11/plboot.mk` | `make -f m11.mk part P=plboot`: `inc/s2.inc` (a copy of the release's `s2-release.inc`), `plboot.cfg` (`pldisk.py --cfg`, from `s2layout.py`'s places), `pl_boot.o` (from `PLBOOT_SRC`, a scratch copy for the planted bugs), `fx-card.o`, `pl_irq.o`, `pl_input.o`, `pl_keys.o`, S2's `player.o` and `probe.o` from `build/sound65` read only; links `plboot.boot` (`$2000-$2FFF`), `.snd` (`$E900`), `.fxc` (`$F505`), `.plat` (`$FF00`), `.vec` |
| `tools/native/pldisk.py` | The link's map, the card images (`LC.BIN`), the bank files, `CRCLIST`, `CATALOG`, `DOOM.hdv` (the existing port's disk writer, as `ldisk.py` and `musicdisk.py`), the images' agreement with the card, the a2vm runs, the checks, the planted bugs. Its docstring is the disk's and the checks' specification |
| `tests/wip_test_m11_plboot.py` | 12 tests: 8 without `build/` (the places of `pl_boot.s` against `pldisk.py`'s and the stop code against every other, the link's map against `s2layout.py`, the catalog, `CRCLIST`, the disk's layout check, the songs' packing, the card's offsets, the poison), and with it the files and sizes, the images against the card, the checkpoint, the planted bugs |

Build output: `build/native/m11/plboot/` (4.3 MB: the link and
`DOOM.hdv`, `pldisk.json`). Every a2vm run is in a `build/tmp-plboot-*`
directory deleted after it.

### 1.1 The disk

`build/native/m11/plboot/DOOM.hdv`: 3,939,840 B (7,695 blocks), volume
`DOOM`, SHA-1 `990174f8` [M]:

| File | Bytes | Banks | What |
| --- | ---: | --- | --- |
| `DOOM.SYSTEM` | 4,096 | | `plboot.boot`, `$2000-$2FFF` |
| `PRODOS` | 17,128 | | ProDOS 2.4.3 (`ProDOS_2_4_3.po`) |
| `CATALOG` | 256 | | the bank files: +0 their count, +16 a 16-byte name each (length, name) |
| `CRCLIST` | 1,460 | | the count (a word), then 9 B an entry: bank, address, length, zlib's CRC-32 (bank 0: main memory); every segment of the bank files in the catalog's order (160), then `LC.BIN`'s two halves as the boot stages them (main `$6000`, 16 KB): 162 entries |
| `LC.BIN` | 32,768 | | the aux card (bank 1 `$D000-$DFFF`, bank 2 `$D000-$DFFF`, `$E000-$FFFF`: milestone 8's trig tables, `rtables.py`'s `tables.img`), then the main card in the same order: bank 1 (the quarter squares, the math, the far layer, the phase loader, the masked phase's loops), bank 2 (the row blocks and the dispatcher) and `$F900-$FEFF` (the replay's and the bucket pass's card parts) from milestone 8's `rcard` link, read only; `$E900-$F8FF` (S2's player, `fx.s`'s card part, `pl_vbl`) and `$FF00-$FFFF` (`pl_ready`, the vectors) from this part's link; `$E000-$E8FF` zero (written at run time) |
| `MAPS.1`, `PATCHES.1`, `TABLES.1`, `TEXELS.1` | 3,039,530 | 9-64, 77-90, 99 | the level store (`wadconv.py --store`, read only), 97 segments |
| `CODE.1` | 87,414 | 93-98, 107, 108, 112, 113 | the load image (milestone 9's `lcard`, bank `LCODE` 98), the render images (milestone 8's `rcard`: W in 112, the masked image in 113), the 2D images in their code banks (`s2layout.image_banks()`: `P2DW` 107, `MENUW` 108, `AMAPW` 94, `WIW` 95, `FINW` 96, `PALW` 97) and `OVLW` (93); 17 segments |
| `RTABLES.1` | 246,036 | 48, 116-122 | milestone 8's constant tables in RamWorks, as its own runs lay them out (`render_check.base_records`): `tables.img`'s banks 48 and 116-119, the math's tables in `MT_TBANK`, `MT_RLO`, `MT_RHI` (120-122); 19 segments (PLBOOT-8) |
| `SONGS.1` | 137,446 | 100-102 | the songs' directory at 100 `$0200` (PLBOOT-2), then the 13 songs converted from the WAD now (`musicdisk.songs`), packed first-fit, largest first, never across a bank |
| `SFX.1` | 11,641 | 103 | part `fxconv`'s `SFX.1` (11,385 B) as a bank file of one segment at `$0200` (`s2layout.SFX_ROOM`) |
| `GFX.1` | 296,921 | 103, 105-110, 114, 115 | part `s2data`'s 2D store |
| `HUDTXT.1` | 2,928 | 104 | part `s2hud`'s message texts at `SS_HUDMSG` |

Ten bank files, 160 segments, 3,819,356 B [M]; no two segments share a
byte, every one is in banks 1-126 at `$0200-$BFFF` (`layout_problems`,
run at every build).

## 2. The boot as built

`pl_boot.s`'s header gives every step; in short (SCREENS.md 2.5):

1. The text screen. The probes, each a stop with its message on row 6
   and its code in `PL_STATUS`: RamWorks banks 1-126 (each bank's number
   written to its `$0200` from 126 down to 0, then read back from 1 up:
   the first that does not hold its number is the first missing, so a
   64-bank card says "NO BANK $40"; `PL_BANKS`), the mouse card's ROM ID
   bytes in slot 2 (`PL_NOMOUSE`), the memory API in slot 7 with COPY,
   FILL and PRIVATE (`PL_NOAMEM`, with its answer), `snd_probe` (no native
   mode: "NO MUSIC OR EFFECTS: NO NATIVE MODE" on row 2, and on).
2. `CATALOG`, then every bank file: each segment 8 KB at a time into
   `DATABUF` and copied into its bank (`RAMWRT`, `$C073`); a bank outside
   1-126, a segment outside `$0200-$BFFF` or a file that is not `A2DM`
   version 1 stops (`PL_DISK`, PLBOOT-1); a ProDOS error stops with its
   code (`PL_DISK`).
3. `CRCLIST`: its count must be the segments loaded and two (`LC.BIN`'s
   halves), and its length 2 + 9 × the count, else "CRCLIST BAD:
   SEGMENTS $nnnn" (`PL_CRC`); then every segment's CRC-32 in its bank,
   read back a page at a time by a page-1 routine (`RAMRD` on: page 1 is
   near in every window) into a bounce page: a mismatch stops with "CRC
   BAD: BANK $bb AT $aaaa" (`PL_CRC`).
4. `LC.BIN`: the aux card's half into `STAGE` (`$6000-$9FFF`), its CRC,
   installed by CPU copy with `ALTZP` on (interrupts masked, no zero page
   or stack used while it is on; RamWorks bank 0's card); the main card's
   half into `STAGE`, its CRC; the file closed, the last MLI call. The
   install: the main card by CPU copy (ProDOS's card overwritten, the
   vector `pl_vbl`), bank 1 selected (MEMORY_MAP.md rule 1); main
   `$0200-$03EF`, `$0C00-$1FFF` and ProDOS's global page `$BF00-$BFFF`
   cleared; zero page `$00-$05` and `$08-$17` cleared and the pair
   `$06-$07` zeroed on its own line [R `NATIVE.md` 10].
5. The mouse card's VBL on (mode `$09`, still masked), `pl_init` (the
   input block, the key table, the mouse's window), `snd_init`, `fx_init`
   with `snd_probe`'s answer, `pl_clkset` (PAL), `CLI`, `pl_detect` (PAL or
   NTSC, the clock from 0), `PL_STATUS` = `PL_READY`, "READY" on row 4, S
   = `$FF`, `jmp pl_ready`.

`pl_ready` (8 B at `$FF00`, the platform's `$FF00-$FFF9`) waits for each
VBL (`pl_ridle`, the loop a2vm skips) and visits `pl_rvbl` once a VBL; the
second half replaces it with the title loop.

**Main memory while booting.** `DOOM.SYSTEM` `$2000-$2FFF`; `STAGE` and
`DATABUF` `$6000-$9FFF`; ProDOS's file buffer `$A000`; `CATALOG` `$A400`;
a header `$A500`; the bounce page `$A600` (also the memory API's
capability block); the CRC tables `$A700-$AAFF`; `CRCLIST` `$AB00-$BEFF`
(at most 568 entries); the page-1 routine at `$0100-$0118` (25 B). The boot's
zero page is `$18-$3F` (overlay 1). Nothing of the boot is called after
`pl_ready`.

## 3. Checkpoint

Commands, from `demos/doom_gs` (`df -h /System/Volumes/Data`: 57 GB
free; at most 3 jobs, `nice -n 10`):

    make -C src/native -f m11.mk part P=plboot
    python3 tools/native/pldisk.py --check --planted --jobs 3
    python3 tools/testpar.py tests/wip_test_m11_plboot.py

The runs (`pldisk.py` docstring): a2vm with the MLI trap, `--amem`, the
mouse card's VBL, `--cost-timed`, `--irq-bounds
00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`, from a machine whose card holds
a pattern (ProDOS's card, as `musicdisk.py`'s), whose aux card holds
another, and whose zero page `$00-$17`, main `$0300-$03EF`, `$0C00-$1FFF`
and `$BF03-$BFFF` hold `$A5`; snapshots at `check_files` (loaded),
`load_card` (checked), `bt_installed`, `pl_ready` and the 50th VBL after
it (later).

| Check | Result [M] |
| --- | --- |
| `boot-f121` (`f121+phasor+window32`, the Doom profile) | ready; 0 problems: at `bt_installed` the main and aux cards equal `LC.BIN` byte for byte, zero page `$00-$17` (the pair with it), `$0200-$03EF`, `$0C00-$1FFF`, `$BF00-$BFFF` all 0; at ready and 50 VBLs later `PL_STATUS` `$C0`, the cards `LC.BIN` but at their run-time places (`$E000-$E8FF`, `fx.s`'s chip-3 lists `$F7BB-$F7E7`), ProDOS's page and the pair 0, `PL_KEYTAB` equal to `plkeys.doom_keys()`, `FX_ON` 1, `FX_HOLD` 0, `FX_INVAL` 1, the clock PAL (step 45,743, `CLK_STD` 0) with the tics equal to the VBL count × the step >> 16 and the fraction its low 16 bits (`plclock`'s model), every byte of the 10 bank files in its bank, "READY" on the screen, the AY log holding `snd_probe`'s two writes and nothing else |
| `boot-fastpath` | the same; 0 problems |
| `boot-ntsc` (`f121`, NTSC) | the same with `pl_detect`'s NTSC: step 38,229, `CLK_STD` `$80`; 0 problems |
| `nomusic` (`--phasor-mb-only`) | ready, "NO MUSIC OR EFFECTS: NO NATIVE MODE" on row 2, `FX_ON` 0, the AY writes `snd_probe`'s two (both on chip 0 in Mockingboard mode) and none after; 0 problems |
| `nomouse` (`--no-mouse`) | stops at `bt_halt`, `PL_STATUS` `$C1`, "NO MOUSE CARD IN SLOT 2"; 0 problems |
| `banks` (`--banks 64`) | stops, `$C2`, "8 MB OF RAMWORKS NEEDED: NO BANK $40"; 0 problems |
| `noamem` (no `--amem`) | stops, `$C3`, "NO MEMORY API IN SLOT 7 $FF"; 0 problems |
| The images against the card (`image_problems`, every build) | none: `lcard`'s and every 2D image's bank-1 code (`MATHLC`, `MATHFAR`, `RFAR`, `RLOAD` to `wl_front`) equal the card's, their S2 and `FXCODE` areas equal it, every label they have in bank 1 or `$E900-$F8FF` is at the card's address; `OVLW`'s imported addresses are `rcard`'s |
| `tests/wip_test_m11_plboot.py` | 12 tests OK, 32.5 s; also on Python 3.9.6 with `PYTHONWARNINGS=error::ResourceWarning` (30.4 s) |
| `tests/test_sound_*` | unchanged (`git diff` empty) and green: 7 modules, 152 tests, 24.1 s with 4 jobs |
| `make -C src/native -f m11.mk all -j4`, `python3 tools/native/s2layout.py --check` | no warning; passes |

The seven runs take 12 s of host time with 3 jobs, the build included.

## 4. Planted bugs (each in a scratch copy, built apart)

`pldisk.py --planted`, 19 s with 3 jobs [M]:

| Bug | Where | Caught by |
| --- | --- | --- |
| A segment into the next bank (`inc a` before `sta RWBANK` in `segment`) | `pl_boot.s` | `boot-f121`: the boot stops, `PL_STATUS` `$C4`, "CRC BAD: BANK $09 AT $BE00" |
| The CRC table one entry short (`crc_entries` drops one) | `pldisk.py` | `boot-f121`: the boot stops, `$C4`, "CRCLIST BAD: SEGMENTS $00A0" |
| ProDOS's card not overwritten (the main card's `lc_put` left out) | `pl_boot.s` | `boot-f121`: the ready check fails (the boot never reaches `pl_ready`: the IRQ vector is ProDOS's; at `bt_installed` the card differs from `LC.BIN`) |
| The pair not zeroed (its two `stz` left out) | `pl_boot.s` | `boot-f121`: "at bt_installed: zero page $00-$17 not cleared: 2 bytes, first $0006 = $A5" |
| `fx_init` called before `snd_probe`'s answer (the answer stored after `fx_init`, which takes the stale byte) | `pl_boot.s` | `boot-f121`: "ready: FX_ON 0, FX_HOLD 0, FX_INVAL 1 (music True)"; `nomusic`: the AY writes are the probe's twice |

## 5. Sizes against the budget

| Piece | Bytes [M] | Budget |
| --- | ---: | ---: |
| `pl_boot.s` (`PLBOOT`, the boot's own code and data; discarded) | 2,042 | 2,048 |
| with `pl_init` and the poll's routines it calls (`pl_keys`, `pl_input`: `S2CODE` 704, `S2RODATA` 78) and `snd_probe` (117) | 2,941 | 4,096 (`$2000-$2FFF`) |
| `pl_ready` in the card (`PLRES`) | 8 | 250 (`$FF00-$FFF9`) |
| The card's `FXCODE` (`fx.s` 739 + `pl_irq.s` 244) | 983 | 1,019 |
| S2's code and tables at `$E900` | 3,037 | 3,077 (`$E900-$F504`) |

`pl_boot.s` was 2,166 B at first; the messages were shortened, the
capability block moved to the bounce page and the text rows computed.

## 6. Timing (SCREENS.md 6.4)

The model's time from `$2000` (the MLI trap serves the reads at no
emulated disk time; the card's ProDOS read rate is milestone 12's):

| Profile | Bank files read (`loaded`) | CRCs (`checked`) | Card installed | Ready |
| --- | ---: | ---: | ---: | ---: |
| `f121` | 1,424.2 ms | 5,762.8 | 5,807.6 | **5,843.0** |
| `fastpath` | 1,058.0 | 5,253.3 | 5,298.1 | **5,323.8** |
| `f121` NTSC | 1,417.3 | 5,751.0 | 5,795.8 | **5,819.8** |

The CRCs take 4.3 s of `f121`'s 5.8 (1.13 µs a byte of the 3,852,124
checked: the page-1 bounce and the table loop); their first version, with
a 16-bit count a byte, took 5.1 s for 3.6 MB. From the card to the ready
state, 35 ms, is mostly `pl_detect`'s one to two VBLs.

## 7. Requests (for the integrator; stand-ins marked `STAND-IN`)

### PLBOOT-1. `tools/native/s2layout.py` `PL`: the disk's stop

**Why.** A ProDOS error, a file that is not a bank file and a segment
outside the game's banks have no code in `PL` [R
`tools/native/s2layout.py:340-347`]; the boot needs one. `$C7` is no other
stop's (`PL`, `S2S`, `llayout.LS`: the test checks). **Stand-ins.**
`pl_boot.s` `PL_DISK = $C7` and `pldisk.py` `PL_DISK = 0xC7`, both marked.

**The change.** In `PL`, after `'SIGNAMEM': 0xC6, ...`:

    'DISK': 0xC7,             # DOOM.SYSTEM: a ProDOS error, not a bank
                              #   file, a segment outside banks 1-126 or
                              #   $0200-$BFFF (part plboot, PLBOOT-1)

(`s2.inc` then has `PL_DISK`); then `pl_boot.s` drops its `PL_DISK` line
and `pldisk.py` reads `S.PL['DISK']`. SCREENS.md 4.2, row `$03AE`, after
"(`PL_AMPALS`, `PL_AMSEGS`, both impossible upstream; wave 6, S2AMAP-4)":
"; `$C7` the boot's disk stop: a ProDOS error, a file that is not a bank
file, a segment outside the game's banks (`PL_DISK`, part `plboot`)".

### PLBOOT-2. The songs' directory (`s2layout.py`, SCREENS.md 4.5)

**Why.** `SONGS.1` must say where each song is for the second half's
`S_ChangeMusic` (`snd_start` takes a bank and an address [R
`src/sound/README.md` "snd_start"]); nothing defined the place.
**Stand-in.** `pldisk.py` `SONG_DIR`, marked.

**The change.** `s2layout.py`, after `SONGS`:

    # the songs' directory (part plboot, PLBOOT-2): at bank SONGS[0] $0200,
    # 3 bytes a song in tools/sound/mus.py UPSTREAM_SONGS' order (D_E1M1
    # .. D_E1M9, D_INTER, D_INTRO, D_VICTOR, D_INTROA): its bank, its
    # address; the songs after it, first-fit, largest first, never across
    # a bank
    SONG_DIR = (SONGS[0], 0x0200)
    SONG_DIR_ENTRY = 3

with `SONG_DIR_BANK` and `SONG_DIR` in `s2.inc`'s constants; `pldisk.py`
then reads them. SCREENS.md 4.5, row 100-102: "the 13 song files, 137,151
B [M: S1]" → "`SONGS.1` (part `plboot`): the directory at 100 `$0200` (3
B a song: bank, address, in `mus.UPSTREAM_SONGS`' order), then the 13
song files, 137,151 B [M: S1], first-fit, largest first, none across a
bank (100: 48,503 B, 101: 43,790, 102: 44,897 [M])".

### PLBOOT-3. The code library's 2D images (for the integrator and the second half)

**Why.** No release image of `P2DW`, `MENUW`, `WIW`, `FINW`, `AMAPW`,
`PALW` exists: each part built its image with its own glue for the test
driver, and `P2DW`'s two parts built two (`s2stbar`'s `s2sb`, `s2hud`'s
`s2ht`). **Stand-in.** `pldisk.py` `IMAGE_BUILDS` (marked): `P2DW`
`s2stbar/s2sb` (the status bar, no HUD), `MENUW` `s2menu2/s2m2`, `AMAPW`
`s2amap/amw`, `WIW` `s2wi/wiw`, `FINW` `s2fin/finw`, `PALW` `s2pal/palw`;
`OVLW` `s2ovl/ovlw` is the image itself. Milestone 10's tic images are
not on the disk (none is released). **The change.** `docs/m11-parts/
design.md` R7, a new item: "The release's 2D images (the frame glue, `P2DW`
with both the status bar and the HUD) replace `pldisk.IMAGE_BUILDS`; the
tic images join `CODE.1` (`pldisk.code_segments`). `pldisk.py`'s build
checks each against the card (`image_problems`) and the disk's layout."

### PLBOOT-4. The card's `FXCODE` order (SCREENS.md 4.4; `design.md` R7)

**Why.** A frame image resolves `fx_copy`, `fxc_ld`, `fxc_st`,
`fx_volume` and `pl_time` by linking `fx-card.o` and `pl_irq.o` (FXPLAY-3),
so their addresses are the link order's. `MENUW`, `WIW`, `FINW` and
`SOUNDS.SYSTEM` put `fx.s`'s card part first (`fx_step` at `$F505`,
`pl_vbl` at `$F7E8`); `fxplay`'s test image `fxpt` puts `pl_irq.s` first
[M: their `.lbl`]. `DOOM.SYSTEM`'s card follows the frame images
(`plboot.mk`); `pldisk.image_problems` compares every image's `FXCODE`
bytes and card labels with the card at every build, and failed on the
first link. **The change.** SCREENS.md 4.4, row `$F505-$F8FF`, at the end:
"Every build that links both puts `fx-card.o` before `pl_irq.o` (the
frame images resolve the card's routines from that order; part
`plboot`'s check, PLBOOT-4)". `fxpt` keeps its order (its own runs only).

### PLBOOT-5. SCREENS.md 2.5, 4.4, 4.5, 6.5: the boot as built

- 2.5 step 1: "the memory API (required)" → "the memory API (required:
  stop with "NO MEMORY API IN SLOT 7")"; "126 RamWorks banks (stop
  below)" → "126 RamWorks banks (each bank's number written to its
  `$0200`, 126 down to 0, read back from 1 up: stop with the first
  missing)"; "PAL or NTSC (2.2)" moves to step 5 (`pl_detect` needs
  `pl_vbl` and the VBL running, PLCLOCK-3).
- 2.5 step 2: after "`GFX.n` (the 2D store)" add "`HUDTXT.1` (the HUD's
  texts), `RTABLES.1` (milestone 8's constant tables, PLBOOT-8)"; "and the
  card image (`LC.BIN`: ...)" → "and the card images (`LC.BIN`, 32 KB:
  the aux card's 16 KB, then the main card's, each bank 1 `$D000`, bank 2
  `$D000`, `$E000-$FFFF`; read in two halves into main `$6000-$9FFF`)".
- 2.5 step 3: "(`CRCLIST`, as milestone 9's disk ...)" → "(`CRCLIST`: a
  count, then bank, address, length, CRC-32 an entry, `LC.BIN`'s halves
  last; a count other than the segments loaded and two stops)"; "a
  mismatch stops with its bank and address" stays.
- 2.5 step 4: "main `$0200-$BFFF` cleared where the game's persistent
  state lives" → "main `$0200-$03EF` and `$0C00-$1FFF` (the persistent
  state) and `$BF00-$BFFF` cleared, zero page `$00-$17`".
- 2.5 step 5: "`snd_init`, `fx_init`, the mouse card's VBL on, `CLI`" →
  "the mouse card's VBL on (masked), `pl_init`, `snd_init`, `fx_init`
  with `snd_probe`'s answer, `pl_clkset`, `CLI`, `pl_detect`"; "a loop at
  `pl_ready`" → "a loop at `pl_ready` (`$FF00`, 8 B)".
- 2.5 last paragraph: "`DOOM.hdv` (ProDOS 2.4.3 as `musicdisk.py` does)"
  → "`build/native/m11/plboot/DOOM.hdv` (ProDOS 2.4.3 as `musicdisk.py`
  does; 3.9 MB, part `plboot`)".
- 4.4, a row after `$F505-$F8FF`: "| `$FF00-$FF07` | `pl_ready`, the
  ready loop the second half replaces (part `plboot`) | 8 of 250 B |".
- 4.5, row 103: "the effect scripts and the volume table, `SFX.1`" → "...,
  `SFX.1` (on `DOOM.hdv` a bank file of one segment, part `plboot`)";
  a row: "| 48, 116-122 | (milestone 8) | its constant tables, `RTABLES.1`
  on `DOOM.hdv` (part `plboot`, PLBOOT-8) | R |".
- 6.5, row Boot, Pass: add "[M: part `plboot`: f121 5.84 s, fastpath
  5.32 s of model time, 4.3 s of it the CRCs]".

### PLBOOT-6. `MEMORY_MAP.md` 4.2 (`design.md` R2, for the final integrator)

Row `$FF00-$FFF9`: "Platform: phase switch (card bank, RAMWRT, `$C073`
0), BRK and crash stub, IRQ bridge landing (pair build)" → "...; the
ready loop `pl_ready` at `$FF00` (8 B, milestone 11 part `plboot`)".
Section 3.1 row `$0300-$03EF`, "zeroed at start" → "zeroed at start
(`DOOM.SYSTEM`, with `$0200-$02FF`, `$0C00-$1FFF` and `$BF00-$BFFF`)".

### PLBOOT-7. The static tables in main and aux 0 (open: a design gap)

**Why.** `MEMORY_MAP.md` 3.2 and 5 give main `$0800-$0BFF` (`CMPA`,
`CMPB`, `TEXLO`, `XTVLO`, `TEXHI`, `XTVHI`) and aux 0 `$0200-$02BF` (the
drawers), `$0900-$0AC7` (`ROWLO`, `FZDIR`, `ROWHI`) "boot, PRIVATE"; no
part of SCREENS.md loads them in the game, and milestone 9's level load
loads only the per-level colormaps and `FUZZDARK` [R `docs/LEVELS.md`
"Checkpoint B"]. `RENDER.SYSTEM` stages them in two banks and copies them
by PRIVATE [R `tools/native/rdisk.py:458-477`]. `DOOM.SYSTEM` does not.
**What.** For `design.md` (the integrator or the second half): the boot
(or the first level load) stages them in a bank of `RTABLES.1` and sends
the PRIVATE requests (the transport is `lload.s`'s, in W), after the last
MLI call (MEMORY_MAP.md rule 9). Not built here: the boot has 6 B of its
budget left.

### PLBOOT-8. `RTABLES.1` (SCREENS.md 4.5; `LEVELS.md` 1.7 for the final integrator)

`LEVELS.md` 1.7 planned `TABLES.n` with "the constant tables, `GTAB`,
the aux card's tables (about 320 KB)"; the store's `TABLES.1` is bank
99's 17,518 B [M]. `DOOM.hdv` carries milestone 8's constant tables in
RamWorks as `RTABLES.1` (246,036 B, banks 48 and 116-122, laid out by
`render_check.base_records`) and the aux card's in `LC.BIN`. Text for
`LEVELS.md` 1.7, row `TABLES.n`: "(as built: bank 99's tables, 17,518 B;
milestone 8's constant tables are `DOOM.hdv`'s `RTABLES.1` and the aux
card's are in `LC.BIN`, milestone 11 part `plboot`)".

## 8. Decisions where the design left a choice

- **`LC.BIN` a file of its own, read in two halves.** The design names
  it; read last into `$6000-$9FFF`, it keeps the boot's stores out of
  `$3000-$5FFF` (rule 3's write-expensive pages) and leaves `DATABUF`
  8 KB. The aux half goes in while ProDOS still runs (its card is
  main's); the main half's copy is the install.
- **The card's parts from milestone 8's `rcard` link.** Bank 1, bank 2
  and `$F900-$FEFF` are `rcard`'s bytes: `replay.s` imports only
  `bk_cut` [R `src/native/replay.s:73`], `OVLW` imports the card at
  `rcard`'s addresses [R `build/native/m11/s2ovl/ovlw.cfg`], and every
  other image's view of bank 1 is checked equal. `RLOAD`'s run list
  `wl_front` is the render image's (`far_wload` loads it; the other
  images never call it, so theirs, with `__RENDERW_SIZE__` 0, differs
  there only).
- **The CRC in the bank, a page at a time through page 1.** A CRC of
  `DATABUF` would miss a copy into the wrong bank (the first planted bug);
  the boot's code is in main, so a page-1 routine reads the bank into a
  bounce page with `RAMRD` on.
- **The count of `CRCLIST`.** The boot counts the segments it loaded and
  checks the table's count and length against it, so a short or long
  table stops before any CRC.
- **`pl_init` in the boot.** SCREENS.md 2.4 gives `PL_KEYTAB` to the
  boot's `pl_init`; it links `pl_keys.o` and `pl_input.o` (782 B, in the
  discarded boot) rather than waiting for `MENUW`.
- **The music flag.** No byte says "no music" beyond `FX_ON` (`fx_init`
  sets it from `snd_probe`'s answer): the second half reads `FX_ON` to
  know whether to call `snd_start`.
- **The probe's order.** Down from 126 to 0, then up from 1, so a card of
  N banks names bank N (aux 0 written last, with 0).

## 9. Open problems

1. **The static PRIVATE tables** are not loaded (PLBOOT-7): the render
   cannot draw from `DOOM.hdv`'s state alone until someone loads them.
2. **Not run on the card** (milestone 12): the ProDOS read time of 3.9 MB
   (12-35 s at 100-300 KB/s [A: `LEVELS.md` 1.7]) adds to the model's
   5.8 s.
3. **The 2D images and the tic images** are stand-ins or absent
   (PLBOOT-3); the boot loads whatever `CODE.1` holds.
4. **The CRCs** take 4.3 s of `f121`'s 5.8. A faster check needs the
   bytes near with `RAMRD` on (the card or page 1); not pursued.
5. **The part took longer than its 1.5 hours.**

## 10. The wave 8 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.12,
"Wave 8 as integrated"):

| Request | Outcome |
| --- | --- |
| PLBOOT-1 | Applied as written: `s2layout.PL['DISK']` `$C7`, `PL_DISK` in `s2.inc`; `pl_boot.s`'s line and `pldisk.py`'s stand-in went (`pldisk.PL_DISK` is `S.PL['DISK']`); SCREENS.md 4.2's `$03AE` row. `s2layout.check()` now also fails when two stops (`PL`, `S2S`, `llayout.LS`) share a code, and the test checks `pl_boot.s` no longer defines it |
| PLBOOT-2 | Applied: `s2layout.SONG_DIR`, `SONG_DIR_ENTRY` and `SONG_COUNT` (13, checked against `mus.UPSTREAM_SONGS` by the test), `SONG_DIR_BANK`, `SONG_DIR`, `SONG_DIR_ENTRY` in `s2.inc`; `check()` keeps the directory in a song bank's `$0200-$BFFF`; `pldisk.song_segments` reads them and fails when the WAD gives other than `SONG_COUNT` songs; SCREENS.md 4.5's row 100-102 |
| PLBOOT-3 | Recorded in `design.md` R7 item 14 (with the `rcard` card parts) |
| PLBOOT-4 | Applied to SCREENS.md 4.4's row `$F505-$F8FF`, naming `fxpt` as the one exception |
| PLBOOT-5 | Applied: SCREENS.md 2.5, 4.4 (`$FF00-$FF07`), 4.5 (rows 103 and 48, 116-122), 6.5 |
| PLBOOT-6 | Recorded in `design.md` R2 item 6 for the final integrator (`MEMORY_MAP.md` stays untouched while milestone 10 edits it) |
| PLBOOT-7 | Open: recorded as `design.md` R7 item 15 for the second half; not built here |
| PLBOOT-8 | Recorded in `design.md` R9 for the final integrator; SCREENS.md 4.5 and 8.4 |

`plboot.mk` adds the link to `IMAGES`, so `make -f m11.mk` (all,
`images`) links `DOOM.SYSTEM` too. After the integration the link and the
disk are the same bytes (`DOOM.hdv` SHA-1 `990174f8`): `PL_DISK` from
`s2.inc` has the stand-in's value, and every other image of
`build/native/m11` relinked to the same bytes.
