I've finished the read-only investigation of `<upstream>`. I changed no files.

All paths below are relative to that repo root. `r_*.s`, `i_viigs65.s`, `patch65.s`, `m_*.s` and `*.inc` are all in `src/iigs/`. Cycle counts are my own estimates from 65816 timings; nothing was measured. Section 7 lists stale comments and anything else I could not confirm.

A `build/` directory appeared while I was working (at 18:21; `build/wad/gsview/*.lmp` exists). I did not create it, so another process is probably running `make`. I used only the GSVIEW lump sizes from it.

# 0. The main facts

- **The 3D view has no back-buffer copy.** Walls, floors, sprites and so on first become per-column records. At the end of the frame, `R_DrawLists` replays them column by column. It writes to bank `$01` with SHR shadowing on, and the hardware mirrors every write into `$E1`.
- **Everything else is copied.** The status bar, HUD text, menus and full-screen pictures are drawn into bank `$01` with shadowing off. Dirty byte ranges are then copied to `$E1` with one MVN per dirty row.
- **Resolution and dither.** The view is 160x168 bytes; one Doom column is one byte, which is two SHR pixels. Colour quantisation, lighting and a 2x2 four-colour dither are all folded into two 34x256 tables, `iigs_shrcmapA` for even rows and `iigs_shrcmapB` for odd rows. So a pixel costs one table read.
- **Floors and ceilings are one flat colour per sector plane.** There are no visplanes or spans; floors are column fills.
- **The drawers are unrolled, one block per screen row.** Entry is computed from a table of row-block addresses. The exit is made by patching the first opcode of the row after the last one.
- **Most of the tuning targets the ZipGS.** That means its 32 KB direct-mapped cache with 1-byte lines (only banks `$00-$6F` are cached) and a presumed single-entry write buffer. Section 3 separates those optimisations from real work reductions.

# 1. Frame pipeline (BSP to SHR pixels)

This is the order inside `display` (`d_main65.s:377-558`).

1. **Frame setup.**
   - `W_FSW`/`W_FSG` record whether the previous frame's view is still on screen (`d_main65.s:377-381`).
   - `I_ViewPalette` sets the view rows' SCB palette (`d_main65.s:446-450`).
   - `viewtop` is set to 9 when a message strip shows, and `viewbottom` is set (`:468-483`).
2. **`vwFrame`** picks the view size and paints the border (`r_frame65.s:2040-2059`; `VWTAB` at `:2151-2155`).
3. **`R_FillStamps`** sets the fill-span stamps and selects the seg-loop patches for the view size via `segMode` (`r_list65.s:143-185`).
4. **`R_RenderPlayerView`** (`r_frame65.s:108-178`):
   - turns SHR shadowing on (`:118-121`), then runs `setupFrame`;
   - clears `solidcol`, drawsegs and the byte clip arrays (`:125-162`);
   - runs `weaponClipSame` (`:164`). This is a clip pass of the weapon that raises `floorclip` so nothing is drawn under the opaque weapon.
   - calls `R_RenderBSPNode` (`:170-174`).
5. **BSP walk** (`r_bsp65.s`).
   - `R_RenderBSPNode` (`:110-140`) keeps a vertex-angle cache per map unit (`:12-15`, `:114-134`).
   - `bspNode` (`:154-240`) recurses with `JSR` and pushes 4 bytes per level (node address plus return address).
   - `bspSub` (`:627`) computes the plane colours (`:666-728`) and calls `R_AddSprites` (`:730-742`; the projection is in `r_thing65.s`).
   - The wall path runs R_AddLine and R_ClipWallSegment via `scan0`/`scan1`, then `R_StoreWallRange` (`r_bsp65.s:898-911`).
6. **`R_StoreWallRange`** (`r_wall65.s:340+`) computes scales without division using `RECIP_TABLE` (`scaleFast`, `:1035-1047`). It writes the wall edges into WPAGE (`:1627-1690`) and calls `R_RenderSegLoop` (`:935-938`).
7. **`R_RenderSegLoop`** (`r_seg65.s:340-504`).
   - It switches the direct page to WPAGE (`$0A00`) and the data bank to the records bank.
   - It picks one of 13 specialised column loops from `segvar.inc` via `JMP (varTab,X)`; the loop kind is 1 top, 2 bottom, 4 ceiling mark, 8 floor mark, 16 one-sided (`:464-504`, `:565-575`).
   - Each column emits `K_FILL` records for ceiling and floor (`ceilFill`/`floorFill`, `:1653-1788`).
   - Each wall tier emits a `K_TEX` record (`texCol` then `tierDraw` then `texRec`, `:1553-1650`).
   - It updates the clip arrays and `solidcol`.
8. **`drawMasked`** (`r_frame65.s:180-212`).
   - Sprites are drawn back to front (`R_DrawSprite`, `r_sprite65.s:1460`, then `R_DrawVisSprite`, `r_seg65.s:2698`); each post becomes a `K_TEX` record.
   - Spectre "shadow" sprites become `K_FUZZ` records.
   - Masked mid textures become `K_TEX`/`K_TEXC` records (`mwCols`, `r_frame65.s:1121-1249`).
   - The weapon is drawn by `playerSkip` (`:947`).
9. **Automap overlay.** If it is on, its lines become `K_OVL` records (`d_main65.s:491-496`).
10. **Colours.** `stripEarly` and `I_ApplyColors` (`i_viigs65.s:346-349`) write the SCBs and palettes just before the view appears (`d_main65.s:499-500`).
11. **`R_DrawLists`** (`r_list65.s:549-557`), via `drawSel` and `drawAll` (`:559-769`):
    - It sets the data bank to `$01` and turns shadowing on (`:571-580`).
    - For c = 0..159 it walks column c's list and dispatches on the record kind: `K_TEX`/`K_TEXC` to the texture row blocks, `K_FILL` to the fill row blocks, `K_FUZZ` to the fuzz blocks, `K_OVL` to the overlay pixel code.
    - It empties the list as it goes (`col2`, `:601-610`), then restores shadowing and turns it off (`:550-556`, `:760-764`).
    - If the record pages run out mid-frame, `newPage` calls `flush`, which draws everything early (`:272-323`).
12. **2D overlays.** `ST_doPaletteStuff`, `ST_Drawer`, `HU_Drawer` and `M_Drawer` (`d_main65.s:531-542`) draw into bank `$01` with shadowing off and mark dirty rectangles.
13. **`I_FinishUpdate`** (`i_viigs65.s:329-345`): `newColors` (tint palettes, SCBs), then `showDirty`, which MVNs the dirty ranges from `$01` to `$E1`.

The `PHASE` markers used for profiling are 2 setup, 3 BSP, 9 StoreWallRange, 10 seg loop, 11 AddSprites, 4 masked, 12 replay, 5 status bar, 6 menu, 7 finish (for example `r_frame65.s:123-176`, `d_main65.s:501-556`). No VBL wait is in the frame path; I found only `titleWipe` (`w_level65.s:1420-1433`) and the loader. The view is therefore not double-buffered: the replay overwrites the old frame left to right.

Header quotes:

- `r_list65.s:3-13`: "Each frame, the walls, floors, ceilings, sprites, masked walls and shadows of the 3D view become records in the lists of their columns (lists.inc). R_DrawLists draws all lists at the end of the frame, column by column, with SHR shadowing on. The screen keeps the frame before while the new one is made, and then gets the new frame in one pass. The drawers do the slow screen writes while the accelerator goes on with their register work."
- `i_viigs65.s:1-4`: "SHR video … 320 x 200, 16 colors per row. R_DrawLists writes the 3D view directly. Other drawing uses the bank $01 back buffer and marks byte ranges; I_FinishUpdate copies only those."

# 2. SHR techniques

## 2.1 Back buffer, shadowing and blits

- **Screen setup.** `NEWVIDEO |= $C0` turns on SHR in linear mode (`i_viigs65.s:290-292`). Only 320-mode palette numbers are written to the SCBs (`rowPalette`, `:756-783`); fill mode and 640 mode are not used.
- **Bank `$01` layout** (`iigs.scm:14-17`; `i_viigs65.s:26-31`):
  - `SHRBUF` at `$01:2000-$9CFF`, 32,000 bytes;
  - `FUZZ_DARKEN` at `$A000` (256 bytes) and `FUZZ_DIR` at `$A100` (50 bytes);
  - `STCACHE` at `$A200` (5,120 bytes, the status-bar background in SHR format);
  - `TEXLO`/`TEXHI` at `$1E41`.
- **Shadowing** is controlled by `$C035` bit 3 (set means no SHR shadowing; `am_map65.s:70`). Bank `$01` always mirrors `$E1`, because the view is written to both and the 2D path copies. That matters because the fuzz drawer and the overlay read screen bytes back from `$01` (`r_list65.s:523-526`; `gendraw.py:413-416`).
- **Copying.** `markRect` keeps a first byte and last+1 byte per row (`DRB`/`DRE`) plus a row range (`i_viigs65.s:407-457`). `showDirty` (`:459-498`) does one `MVN $E1,$01` per dirty row. Other copies use `IIGS_CopyHuge` (`iigs_asm.s:478+`, a self-modified MVN).
- **No PEA/stack blits.** `TCS` appears only in non-render code: `cal_integer`, `p_map65`, `I_Error`, `titleWipe`.
- **SCBs and palettes** come from near copies (`scb` 200 bytes, `palette` 512 bytes, `i_viigs65.s:99-100`). SCBs are written with a word loop (`:363-371`). Palettes are copied as one 384-byte tint row of `TINTPAL` via `IIGS_CopyHuge` (`:372-390`).

## 2.2 View geometry and the pixel byte

- `gendraw.py:4-6`: "The back buffer has the layout of the SHR screen and is in bank BUF_BANK at offset 0x2000, 160 bytes for each of the 200 rows. One Doom column is one byte (two SHR pixels)."
- The view is 160x168 (`VIEW_ROWS 168`, `i_viigs65.s:40`; `CONST_VIEWWIDTH 160`, `CONST_VIEWHEIGHT 168`, `CONST_CENTERY 84`, `offsets.inc:1004-1006`). The status bar is rows 168-199. The message strip is rows 0-9 (`STRIP_ROWS`, `i_viigs65.s:58`).
- The view byte is `iigs_shrcmapA[cm][texel]` on even rows and `iigs_shrcmapB[cm][texel]` on odd rows.
- Per `gsview.py:48-54`: "byte A = a d on even rows, byte B = c b on odd rows, so each 2x2 block of screen pixels has all four" (a..d are four palette colours ordered by lightness). The code is `bytes_for` at `gsview.py:660-665`.
- Smaller view sizes (half 80x84, 2/3 107x112, 1/3, 1/4, 3/4) skip rows and columns at replay time (`viewwin.inc:1-14`, `:100-105`; `VWTAB` at `r_frame65.s:2151-2155`).

## 2.3 Palettes and SCBs

- **View palette.** One 16-colour palette per map, `GSVIEW1`..`GSVIEW9` (plus `GSVIEW0` for all maps), designed offline by `tools/gsview.py` (docstring `:1-69`):
  - 96 random views per map are rendered with `tools/doomview.py`, plus sprite and weapon usage histograms with group weights (`CFG`, `:88-99`);
  - k-means in OKLab, then a local search; black and `$DDD` white are fixed (`:529`);
  - each Doom colour gets a mix of four palette colours chosen by error plus lambda times noise (`Mixes`, `:637-665`).
- **GSVIEW lump layout** (1216 bytes; confirmed from `build/wad/gsview`): 14 tints x 16 colours x 2 bytes, then a 256-byte "best pair" table, then 256 bytes of byte A, then 256 bytes of byte B.
- **GSFLATn** is one Doom colour per flat: the nearest palette entry to the linear-light mean of the flat's texels (`gsview.py:211-218`, `:711-712`).
- **Palette slots in a level** (`i_viigs65.s:47-58`):
  - 0: view;
  - 1-8: status bar, chosen per row by GSSTAT's 32-byte row map (`enterLevelMode`, `:785-872`);
  - 9: `MENU_PAL`; 10: `MSG_PAL`; 11: `AMAP_PAL`.
  - 12 palettes x 14 PLAYPAL tints are precomputed with gamma into `TINTPAL` (5,376 bytes, `:85`, `:609-700`). A damage or bonus flash only copies a tint row.
- **Full-screen pictures** (TITLEPIC, HELP2, WIMAP0) use `tools/gscolor.py`. From its docstring: 16 palettes, a palette chosen per row, k-means plus Floyd-Steinberg (`:225-304`). The lump format is 36,864 bytes (`:15-23`).
- Palette slot order is aligned across all palettes, so colours stay near their places (`align4`, `:41-51`, `:115-125`).

## 2.4 Dithering

- **View:** the fixed 2x2 ordered pattern described in 2.2. The tables pre-dither it, so drawing costs nothing extra.
- **Patches and pictures:** checkerboard "pairs" through the nibble tables (2.6); pictures use Floyd-Steinberg offline.
- **Stale docstring:** `gendraw.py:14-16` says A and B "hold the same color pairs with the nibbles swapped". The generator now produces four-colour mixes.

## 2.5 Colormaps and lighting

- `iigs_shrcmapA` and `iigs_shrcmapB` are 34x256 bytes each (17,408 bytes, contiguous) in bank `$0D` at `$4600` (`gendraw.py:141-143`; `iigs.scm:81-82`).
- They are built per level as `A[fullcolormap[cm*256+i]]` and `B[…]` (`i_viigs65.s:1068-1080`). `CMAP_B = 34` pages (`r_list65.s:37`).
- A record stores only the colormap page (`R_CMP`). The replay reads the odd-row page as `R_CMP + 34` (`r_list65.s:719-723`).
- **Light model** (`r_bsp65.s:960-980`):
  - startmap is (15 - lightnum) x 4;
  - walls and sprites use d = min(47, scale >> 12) / 2; walls use d from `rw_scale >> 13` (`DLIGHT`, `r_seg65.s:98-111`);
  - planes use a fixed `PLANE_D = 10` (`r_bsp65.s:41-43`);
  - the weapon uses d = 23.
- Lookup tables `SMAP`, `CMO`, `PCMO` and `PGT` do the clamping (`r_bsp65.s:1004-1040`; `r_seg65.s:3147-3162`).
- A seg whose two ends have the same d gets one page (`W_CMP`); otherwise `texRec` lights each column record through a patched lookup `c26Lookup` (`r_seg65.s:391-422`, `:1613-1623`, `:2616-2627`).
- Plane colours deliberately ignore `extralight` so fill reuse survives gun flashes (`r_bsp65.s:677-679`, "experiment FL1").
- The fuzz darken table `FUZZ_DARKEN` maps a byte to a darker byte, per nibble at 3/4 brightness (`i_viigs65.s:1083-1188`).

## 2.6 Nibble tables (`MM_NIBTAB`, `$0B:8000`, 16 KB)

- `patch65.s:3-9`: "Each patch pixel is one SHR pixel (a nibble). There is a nibble table of 1 KB for each of the 16 palettes, with four parts of 256 entries: left pixel even row, left pixel odd row, right pixel even row, right pixel odd row. iigs_rowpageL and iigs_rowpageR give the page of the table for each screen row…"
- They are built from the palette record's best-pair byte (`buildNibtab`, `i_viigs65.s:702-735`).
- Patch drawing is a read-and-mask-or per pixel into bank `$01` (`pixLoop`, `patch65.s:157-175`). HUD graphics therefore have full 320-pixel resolution.

## 2.7 Column records (`MM_RECBASE` = `$1D:0000`)

- `lists.inc:1-13`: "The records are in bank RECBANK… No page is in cache slots $0900-$1FFF (pages $09-$1F, $89-$9F)… The list of column c starts at page COLPAGE(c): c for c < 9, c + $17 up to column 113, c + $2E after. A full page goes on in an extra page (a K_NEXT record); the extra pages are XP_FIRST..$FF."
- That is 160 home pages plus 50 extra pages (`$CE-$FF`), at most 53,760 bytes. A record must end at offset 254 or earlier (`PAGE_ROOM`).
- `COLW` holds the write pointer per column as page<<8 | offset (`r_list65.s:87-93`).
- **Record kinds** (`lists.inc:32-72`, `:180-185`):

| Kind | Size | Fields |
|---|---|---|
| `K_TEX` | 11 bytes | kind, first row, end row, TF, TI, SF, SI (position and step in 7.8), 24-bit texel pointer, colormap page |
| `K_FILL` | 5 bytes | kind, first row, end row, first-row byte, second-row byte |
| `K_TEXC` | 7 bytes | chained masked post; only `mwCols` emits it (`r_frame65.s:1531-1538`) |
| `K_FUZZ` | 4 bytes | shadow sprite post |
| `K_OVL` | 4 bytes | automap pixel |
| `K_NEXT` | 2 bytes | continue the list in another page |

- Records are created by `recTex`, `fillCol`, `recFuzz` and `recOvl` (`r_list65.s:326-466`). The fast producers are inlined: `texRec` (`r_seg65.s:1596-1650`), `PLANEFILL` (`:1659-1692`) and `visPost` (`:3028-3087`).

## 2.8 Floors, ceilings, fill spans, covered ranges, weapon skip

- **Planes are single colours.** `floorplane_color` and `ceilingplane_color` come from `FLATCM[cm*32 + flat]` (`r_bsp65.s:666-728`, `:752-763`, `:992-996`). `fillBytes` turns a colour into the even/odd byte pair (`r_seg65.s:1790-1805`).
- **Fill spans (`FS_*`)** are 4 tables of 2 bytes per column at `$23:EF00`. From `lists.inc:73-87`: "Its top span is the ceiling fill of a column from the first row of the view…; its bottom span is the floor fill to the row after the view… A fill of the same bytes gets a record only for its rows that its span of the frame before (stamp W_FSP) did not show. A record over the rows of the walls… cuts the spans of its column (FSCUT)." The implementation is in `r_seg65.s:1708-1788`; the stamps are in `R_FillStamps`.
- **Covered ranges (`CV_*`)**, from `lists.inc:108-117`: for each column, the opaque masked record with the most rows. "R_DrawLists does not paint those rows for the records before it in the list, as it paints them again." The replay cuts are in `r_list65.s:612-679`, `:835-863` and `:1082-1137`.
- **Weapon skip (`WCLIP`)**: if the weapon is the same as last frame and the view was shown, its bottom rows are neither redrawn nor painted under (`r_frame65.s:880-960`; `lists.inc:123-131`).
- **Sky** is `K_TEX` records at one texel per row (`skyColumn`, `r_seg65.s:1397-1475`).

## 2.9 Unrolled drawers and how they are entered

- `gendraw.py:8-12` (its entry/exit description is partly stale, see section 7): "There is one code block for each screen row, with the row address in the store instruction, and X holds the column byte."
- **Texture row block, as generated** (`gendraw.py:65-79`), 19 bytes: `xba / adc SF / xba / tya / adc SI / and #$7f / tay / lda [SRC],y / sta CMA|CMB / lda [CMA|CMB] / sta $2000+r*160,x`.
- **Runtime full-view "pair" image.** `pairSetDetail`/`pairMake` (`r_list65.s:6194-6335`) rewrite the image into 34-byte row pairs.
  - Even rows (15 bytes) drop the fraction step and use `adc SI+1`, a rounded integer step.
  - Odd rows use `adc SF+1`, twice the fraction, so every odd row lands exactly. From `:1049-1052`: "Odd rows are exact. Even rows round the carry to its nearer value."
- **Entry.** Per-row block addresses sit in `TEXLO`/`TEXHI` in bank `$01` at `$1E41` (`r_list65.s:41-50`). The replay reads them, sets X = column, Y = TI, B = TF, 8-bit index registers and carry clear, then does `JMP (RL_TENT)` (`r_list65.s:737-744`).
- **Exit.** The first byte of the block after the last row is patched to `$6C`, so `EB 65 05` or `98 65 07` becomes `JMP ($0565)` or `JMP ($0765)`. Those two vector words in text page 1 of bank 0 are borrowed for the duration of the replay (`pairBegin`/`pairEnd`, `:6176-6192`; comment `:44-47`).
- **Fill blocks:** `xba / sta row,x` per row (4 bytes, 8 cycles). Entry is `jsr rlFillJump` (`jmp (RL_FENT)`); the block after the last row is patched to `RTS` (`$60`) and back (`r_list65.s:865-902`, `:943-944`; `gendraw.py:332-349`).
- **Fuzz blocks:** 217 rows x 10 bytes. Each row reads the byte above or below, maps it through `FUZZ_DARKEN` and writes it back. Entry is `JML [DC_ENTRY]`; exit is a patched `RTL` (`gendraw.py:399-426`; `r_sprite65.s:1735-1788`).
- **Other jump tables:**
  - seg loops: `JMP (varTab,X)` (`r_seg65.s:504`);
  - record kinds: `JMP (kinds,X)` (`r_list65.s:822`);
  - constant-row multiply kernels: `JMP (c16Rows,X)` (`r_seg65.s:4037-4043`);
  - reciprocal shift chains: `JMP (rcShl1,X)` and similar (`m_recip65.s:81-107`).
- **Per-seg self-modifying code:**
  - `c17Return`, one word store per seg choosing `RTS` or `JMP` to the tier (`r_seg65.s:1936-1939`, `:5164-5215`);
  - the `c26Lookup` operand (`:2620-2627`).
- **Mode installers** run only when the view size changes: `c16Mode`, `c17Mode`, `c19Install` (MVN copies of kernels), `R_ViewMode`, `R_SegHalf`, `pairSetDetail` (`r_seg65.s:4008-4020`, `:4228-4310`).

## 2.10 Texture column storage

- **`MM_COLDIR`** (`$25:0000`) holds 256 textures x 4 bytes: word 0 is the column-table address, byte 2 the bank, byte 3 the width mask (`r_data65.s:863-868`, `:1061-1072`; read by `TIERDIR`, `r_seg65.s:305-330`).
- **Column tables** have (widthmask+1) x 4 entries. Each entry is a 24-bit pointer to raw patch post texels (`patch + columnofs[x] + 3`, used in place in the level window), or to a composed column when patches overlap. A value of 0 with 1 in the top byte means "no patch": the tier is drawn flat (`r_data65.s:939-1081`, `:1109-1197`; `r_seg65.s:1509`).
- Tables are made per level; hot textures are placed first (`R_MakeLevelColumns`, `r_data65.s:871-910`).
- The drawer wraps texel rows with `AND #$7F`. Reads can run up to 127 bytes past a column start, hence `OVERREAD 128` in `tools/levelimg.py:23-26`.
- **`texBlocks`** is in section `hotdraw` at `$05:0B00-$1A1A`: `flatBlocks` (672 bytes) followed by `texBlocks` (3,195 bytes) (`iigs.scm:174-175`; `r_list65.s:38-40`).

## 2.11 Sprites, masked walls, weapon, shadows

- **Ordinary sprites.** `R_DrawSprite` clips against drawsegs using byte arrays `dsX1`/`dsX2` (`dscols.inc:1-16`; `r_sprite65.s:1450-1682`). `R_DrawVisSprite` (`r_seg65.s:2684-2862`) builds `YHTAB` (the row at which each texel row ends) and emits one `K_TEX` per visible post (`visPost`, `:2949-3087`). The same texture row blocks draw them at replay.
- **Magnified sprites** reuse a record across repeated columns (`visColD`, `r_frame65.s:1660-1670`).
- **Masked mid textures:** `mwCols` (`r_frame65.s:1121-1249`).
- **Weapon.** A clip pass, then a draw from precomputed "profiles" of the patch's posts. From `r_sprite65.s:725-735`: "demo3: the pass took 1.9 ms a frame, the draw 2.2." Profile arenas are at `$0A:D000-E3FF` and `$0A:ED00-FEFF` (`:746-755`).
- **Spectre shadows:** `K_FUZZ` records, drawn with `fuzzBlock` (`r_sprite65.s:462-472`, `:1719-1788`).

## 2.12 Status bar, menus, text code, capture masks

- **Status bar.** The background is cached in `STCACHE` (`V_DrawRaw`, `i_viigs65.s:1305-1367`). Widgets are patches drawn via `IIGS_DrawPatch` into bank `$01`, with dirty marks (`st_stuff65.s:1-4`).
- **HUD text cache** (`i_viigs65.s:1784-1897`; `patch65.s:278-383`).
  - While capturing, `IIGS_DrawPatch` also writes each value to `MM_CAPVAL` and each written-nibble mask to `MM_CAPMSK`. Both are screen-shaped buffers at back-buffer offsets `$2000-$9CFF` in banks `$26`/`$25` (`patch65.s:232-276`).
  - `IIGS_TextCode` then compiles the capture into straight-line code at `MM_TEXTCODE` (2 slots x 16 KB). From `patch65.s:279-283`: "for a byte with written nibbles m and value v, lda abs:byte / and #~m / ora #v / sta abs:byte … then RTL". That is 10 bytes of code per screen byte.
  - A redraw of the same text is `JML [COLP]` into that code (`:359-382`).
- **Menus** grey the saved view using `MENU_PAL` and `GRAYMAP`. The view is saved in `VIEWSAVE`/`VIEWSAVE2` (`i_viigs65.s:874-953`, `:2057+`; `memmap.inc:72-80`, `:96-97`).

# 3. What exists because of the accelerator versus real work reductions

The cache model is described in `tools/slotmap.py:5-10`: "The ZipGS cache is direct mapped with 1-byte lines: the slot of a byte is its address & (CACHE - 1), CACHE = 32768 by default, and only banks $00-$6F are cached." The README (`README.md:13`) says the write-buffer work may be "all for naught".

## A. Cache-slot layout (irrelevant without a direct-mapped cache)

- **The whole memory map is organised by slot** (`iigs.scm:78-231`). From `iigs.scm:91-109`: "The view stores (bank 01 $2000-$88FF) take the slots $2000-$7FFF and $0000-$08FF in each frame, so: $0900-$1FFF: the direct page, the row blocks of the drawers (hotdraw), the replay of the lists (hotlist), the entries of the blocks at $1E41…"
  - Hot sections: `segcode` `$2000`, `bspcode` `$4000`, `hotmul` `$6000`, `maskcode`, `listfuzz`, `listovl`, `thirdlist`, `halflist`, `paircode`.
  - Code is kept in place by `.space` padding throughout, for example `r_list65.s:916-918`, `:1053-1079`; `r_seg65.s:530`, `:2862`; `r_frame65.s:1050-1051`; `r_iigs65.s:271-273`, `:622-624`.
- **Data placed by slot:**
  - "A hot table keeps the low 15 bits of its old address" (`memmap.inc:7-10`);
  - `dsX1`/`dsX2` in the slots of `genColumn` (`dscols.inc:4-9`);
  - the multiply table T in slots `$1800-$1DFB` (`mul.inc:3-7`);
  - `FS` in slots `$6F00-$7AFF` (`memmap.inc:82-84`);
  - `TEXLO`/`TEXHI` (`r_list65.s:41-43`);
  - colormaps (`iigs.scm:78-82`);
  - weapon profile arenas (`r_sprite65.s:746-748`).
- **Record pages avoid slots `$0900-$1FFF`** (`lists.inc:6-28`). Smaller views have their own page maps `T_PAGE2`, `O_PAGE2`, `Q_PAGE2` (`r_list65.s:2262-2268`, `:2840-2842`, `:3832`).
- **Hot composed texture columns are kept off the replay's slots** (`r_data65.s:1732-1745`; hot list `CM_COLD`, `:1094-1106`).
- **Level lumps are ordered by per-slot read heat** (`tools/levelimg.py:92-101`; `tools/levelhot.txt:1-12`).
- **Rare drawers got their own slots.** `r_list65.s:470-474` notes a spectre column and a texture column "pushed each other out (-6 ms a spectre frame)".

## B. Write-through and single-entry write buffer (every store is a motherboard bus write)

- **Stores are bytes** (`r_wall65.s:7-8`, `r_thing65.s:10`, `segvar.inc:11-16`). From `p_tick65.s:12-14`: "a 16-bit store is two writes back to back, and the accelerator buffers one write".
- **The 16-bit store rule** (`r_wall65.s:117-122`): "a 16-bit store where no register work or cache-hit read fits".
- **Register work after each store.** Examples: `lists.inc:148-149` "(register work while the bus writes)"; `r_seg65.s:1618-1619` "(after the light: the writes before it drain)"; `r_seg65.s:396-397` "each write holds the bus"; `r_seg65.s:1656-1658`; `am_map65.s:1275`.
- **Fewest possible stores.**
  - Keep products in registers: "a product stores one word" (`m_fixed65.s:4-6`), `qmul` has "one word of temporary store" (`r_wall65.s:1727-1730`), and `recipCore` does its shifts "in registers … with one store" (`m_recip65.s:24-28`).
  - Test before storing (`r_wall65.s:360-364`; `r_seg65.s:2042-2044`).
- **REP/SEP avoidance** because "each costs a slow cycle" (`r_list65.s:589-594`, `:681-683`, `:870`; `r_seg65.s:1597-1600`, `:2864-2866`, `:2888-2890`; `r_frame65.s:1223-1225`, `:1712-1713`). This is done with XBA plus TAX/TAY copying B, and PEA/PLB/PLB (`r_seg65.s:499-502`). This is a model-specific claim I cannot confirm on hardware, and it does not apply to a 65C02 anyway.

## C. Consequences of the IIgs video design (slow `$E1` writes, one SHR page, shadowing)

Whether these carry over depends on your target's video RAM.

- **Direct-to-screen replay with no 3D-view copy** (`r_list65.s:3-9`; `r_frame65.s:118-121`).
- **Deferred column lists.** The old frame stays visible until one left-to-right pass.
- **Dirty rectangles plus MVN** for 2D (`i_viigs65.s:407-498`).
- **Fewer screen writes:** fill-span reuse, covered-range overdraw removal and the weapon skip (section 2.8). These also save real drawer work.
- **Caches:** `STCACHE` and the compiled text code.

## D. Real CPU-work reductions (portable)

- 160-wide view (half horizontal resolution); flat-coloured planes as 8-cycle fill rows.
- Colormap, dither and palette folded into one table read.
- Unrolled per-row blocks with the row address baked in as an immediate; computed entry, patched exit.
- Even/odd row pairing: even rows skip the fraction step.
- Texture u is exact only every 8 columns and linear in between (`TC_N = 8`, `r_seg65.s:1807-1831`).
- `FSTEP_TABLE` gives the texture step as 1/scale (`r_seg65.s:1926-1943`, `fstepHigh` at `:2583-2615`).
- 24-bit edge stepping with 8 fraction bits, "can be off by one" (`STEP8E`, `r_seg65.s:171-186`).
- 13 loops specialised by tier and mark (`segvar.inc`; `varTab`).
- Constant-row multiply kernels (C16/C19, `r_seg65.s:4024-4060`, 86 kernels from `:4314`).
- Quarter-square and table multiply/reciprocal (section 5); non-restoring 3-bits-per-step `slopeT` (`r_iigs65.s:135-143`).
- Vertex angle cache (`r_bsp65.s:12-15`); C14 log-bound side test (`:1237-1311`); sprite scale tables (`r_thing65.s:4-6`, `:32-38`).
- One light per seg when its ends match (`r_seg65.s:391-422`).
- Weapon profiles; magnified-sprite repeats; lazy texture-column creation (`tierMake`).

# 4. Dependence on 65816 features

Approximate counts per file from grep, after stripping comments:

| File | Instructions | REP/SEP | `long:` | JSL/RTL/JML | XBA | BRL | MVN |
|---|---|---|---|---|---|---|---|
| `r_list65.s` | 4,148 | 163 | 658 | 53 | 379 | 139 | 22 |
| `r_seg65.s` | 2,609 | 88 | 285 | 40 | 18 | 14 | 2 |
| `r_frame65.s` | 1,568 | 60 | 184 | 41 | — | — | — |
| `r_thing65.s` | 1,287 | 61 | 246 | 43 | — | — | — |
| `r_wall65.s` | 1,186 | 37 | 98 | — | — | — | 1 |
| `r_sprite65.s` | 1,151 | 40 | 88 | — | — | — | — |
| `i_viigs65.s` | 1,566 | 54 | 189 | 91 | — | — | 1 |

Across the 12 main renderer/math files there are roughly 1,850 long-address operands, 510 REP/SEP, 390 JSL/RTL/JML, 490 XBA and 230 BRL.

**How each feature is used:**

- **16-bit A/X/Y.**
  - X = 2 x column; records are indexed by X = page<<8 | offset.
  - All 16.16 fixed-point maths works in 16-bit halves.
  - The innermost row blocks run with 8-bit A, X and Y (`sep #$10` before entry, `r_list65.s:741`). They are the most portable part.
- **Direct page relocation.**
  - DP `$0900` for the C-style code and drawers: `DC_*` occupy offsets `$00-$2B`, with SF at `$04` and SI at `$06`.
  - WPAGE at `$0A00` for the seg loop and sprites (`wpage.inc:1-8`; switched at `r_seg65.s:347-349`, `:2793-2795`; `CENV`/`WENV` at `:278-295`).
  - A 65C02 has only one zero page. `DC_*` (44 bytes), WPAGE (about 250 bytes) and `BSPDP` (72 bytes) will not all fit.
- **Long indirect `[dp]` and `[dp],Y` in every texture pixel:** `lda [SRC],y` for the texel and `lda [CMA]` for the colormap. On a 65C02 these become `(zp),y` and `(zp)`, so the texel column and the colormap must be mapped into the 64 KB space together with the screen.
- **Data bank register.** It is `$01` during replay, so the screen store is plain `sta abs,x` (`r_list65.s:571-576`), and `RECBANK` in the seg loop, so the record stores are `sta abs,y`.
- **MVN:** dirty blit, drawer image installs, `saveClip` (`r_wall65.s:1592-1597`), `IIGS_CopyHuge`.
- **JML `[dp]`:** fuzz, text code, `callColumn` (`r_sprite65.s:398`).
- **PEA/PEI:** only for DBR setup and for saving DP words (`r_bsp65.s:131-134`; `r_data65.s:947-950`).
- **Stack-relative:** a handful of uses, for example `lda 2,s` in `recTex` (`r_list65.s:347`).
- **Stack size.** 13.5 KB at `$0B00-$3FFF` (`iigs.scm:32-33`, `:228`), but the BSP recursion uses only 4 bytes per level.
- **`JMP (abs,X)`** dispatch works as is on a 65C02.

### Hottest loops (excerpts)

**(a) Wall/sprite column drawer: generator** (`tools/gendraw.py:69-79`, one block per row r):

```
              xba                       ; row {r}
              adc     dp:.tiny SF
              xba
              tya
              adc     dp:.tiny SI
              and     #0x7f
              tay
              lda     [.tiny SRC],y
              sta     dp:.tiny {cm}     ; CMA even rows / CMB odd rows
              lda     [.tiny {cm}]
              sta     abs:0x{ROW0 + r * 160:04x},x
```

At runtime, `pairMake` (`r_list65.s:6211-6304`) turns it into the following. This is my reconstruction from the byte copies and operand patches.

```
; even row r (15 bytes)                       ; odd row r+1 (19 bytes)
98        tya                                 EB        xba
65 07     adc $07   ; SI+1 (rounded step)     65 05     adc $05   ; SF+1 = 2*SF
29 7F     and #$7F                            EB        xba
A8        tay                                 98        tya
B7 08     lda [$08],y ; texel                 65 06     adc $06   ; SI + carry
85 0C     sta $0C   ; CMA low byte            29 7F / A8 / B7 08
A7 0C     lda [$0C] ; shrcmapA[page][texel]   85 10 / A7 10       ; CMB
9D xx xx  sta $2000+r*160,x                   9D xx xx  sta $2000+(r+1)*160,x
```

That is about 29 and 38 cycles (65816, 8-bit, DL=0), 33.5 per row on average, before bus stalls.

**Entry and exit** (`r_list65.s:709-748`, trimmed):

```
texEndY:      lda     abs:TEXLO,y        ; block after the last row
              sta     dp:.tiny RL_XO
              lda     abs:TEXHI,y
              sta     dp:.tiny (RL_XO+1)
              lda     long:(RECBASE+R_SRC),x ; the texels (24-bit)
              ...
              lda     long:(RECBASE+R_CMP),x ; colormaps even/odd
              sta     dp:.tiny (DC_CMA+1)
              clc
              adc     #CMAP_B
              sta     dp:.tiny (DC_CMB+1)
              ...
pairReady:    tay                         ; (TF:TI)
              lda     #0x6c               ; JMP through the row exit word
              sta     [.tiny RL_XO]
              ldx     dp:.tiny RL_C       ; X = the column
              sep     #0x10
              clc
              .byte   0x6c                ; JMP (RL_TENT)
              .word   .word0 RL_TENT
texContinue:  rep     #0x10
              lda     #0xeb
pairRestore:  sta     [.tiny RL_XO]       ; restore opcode
              ldx     dp:.tiny RL_P
done:         cpx     dp:.tiny RL_E
              bne     rec
```

By my hand count the per-record overhead in this replay path is roughly 180-200 cycles (not measured).

**(b) Flat fill** (`gendraw.py:348-349` per row, `xba` / `sta abs:$2000+r*160,x`, 8 cycles) and its caller (`r_list65.s:874-902`):

```
              rep     #0x20
              tay
              xba                     ; entry = flatBlocks + 4 * the row
              and     ##0x00ff
              asl     a
              asl     a
              adc     ##.word0 flatBlocks
              sta     dp:.tiny RL_FENT
              tya
fillEndW:     and     ##0x00ff        ; Y = the block after the last row
              asl     a
              asl     a
              adc     ##.word0 flatBlocks
              tay
              sep     #0x20
              ...
              lda     #0x60           ; RTS there
              sta     [.tiny RL_FX],y
              lda     long:(RECBASE+R_B1),x ; B = first-row byte, A = second
              xba
              lda     long:(RECBASE+R_B2),x
              ldx     dp:.tiny RL_C
              jsr     .kbank rlFillJump     ; jmp (RL_FENT)
              lda     #0xeb           ; XBA again
              sta     [.tiny RL_FX],y
```

The record producer `PLANEFILL` is at `r_seg65.s:1659-1692`.

**(c) Sprite column: post to record** (`r_seg65.s:3030-3086`, trimmed). The pixels are then drawn by (a).

```
11$:          ldx     dp:W_X2
              FSCUT   dp:V_YL, dp:V_YH1     ; cut fill spans
              lda     long:(COLW+1),x       ; free byte of the list (B = page)
              xba
              lda     long:COLW,x
              tay
              cmp     #(PAGE_ROOM - TEX_SIZE + 1)
              bcs     18$
13$:          adc     #TEX_SIZE
              sta     long:COLW,x
              CVSETB  dp:V_YL, dp:V_YH1
              tyx
              lda     #K_TEX
              sta     abs:R_KIND,x          ; DBR = RECBANK
              lda     dp:V_YL
              sta     abs:R_ROW,x
              lda     dp:V_YH1
              sta     abs:R_END,x
              rep     #0x20                 ; frac of the first row via T tables
              lda     dp:V_YL
              asl     a
              tay
              lda     [V_QP2],y
              sec
              sbc     [V_QM2],y
              ...
              lsr     a
              sep     #0x20
              sta     abs:R_TF,x
              xba
              sta     abs:R_TI,x
              ...
              lda     dp:W_CMP
              sta     abs:R_CMP,x
              brl     visAdv
```

**(d) Screen "blit"** (`i_viigs65.s:462-498`, `showDirty`); the 3D view needs none because of shadowing (`r_list65.s:577-580`):

```
showDirty:    lda     .near DRY0
              sta     .near MR_Y
1$:           lda     .near MR_Y
              cmp     .near DRY1
              bcs     8$
              tax
              lda     long:DRE,x
              and     ##0x00ff
              beq     4$
              sta     .near MR_T
              lda     long:DRB,x
              and     ##0x00ff
              sta     .near MR_B
              lda     .near MR_Y
              jsr     .kbank rowOffset
              clc
              adc     ##(SHRBUF & 0xffff)
              adc     .near MR_B
              tax
              tay
              lda     .near MR_T
              sec
              sbc     .near MR_B
              dec     a
              phb
              .byte   0x54, (SHR_SCREEN >> 16), (SHRBUF >> 16)  ; MVN $E1,$01
              plb
```

For the per-column wall producer, see `segvar.inc:41-80` (8-bit A, 16-bit X, `long:floorclip,x`, `STEP8E`) and `texRec` at `r_seg65.s:1601-1643`.

# 5. Maths tables

- **`SQL` and `SQH`** (`m_fixed65.s:45-93`).
  - sq(n) = floor(n²/4) for n = 0..131071, split into low words (`SQL`, banks `$13-$16`) and high words (`SQH`, banks `$17-$1A`). That is 256 KB each, 512 KB total. Byte offset 2n gives entry n.
  - The index 2n is 18 bits. The carry out of a+b, then the carry out of `ASL`, selects which of four explicit code paths runs, each doing `long:SQL+q*$10000,X` (`MULHI16`, `r_seg65.s:191-238`).
  - sq(|a-b|) only ever needs the first two banks.
  - A full 16x16 to 32 product takes 4 table reads; the low half alone takes 2 (`QMULLOR`).
  - The tables are built at boot by incremental differences (`IIGS_InitSquares`, `m_fixed65.s:266-352`).
- **T** (`mul.inc:1-29`; `m_fixed65.s:20-23`): 766 words, k = -255..510 (1,532 bytes), for byte x byte products via long pointers `QP` and `QM`.
- **`RECIP_TABLE`** (`m_recip65.s:1-10`, `:311-353`): bank `$1E`, 32,768 words, entry i = floor((2^31-1)/(32768+i)). v is normalised so bit 31 is set, the top 16 bits M are used as `asl`/`tax`, and the result is shifted by jumping into unrolled shift chains.
- **`FSTEP_TABLE`**: banks `$1B-$1C`, 65,536 words. It is the texture step for scales below 1.0 (33554431/L for L >= 512), indexed by the scale low word times 2 with the carry selecting the bank (`r_seg65.s:1926-1943`; `m_recip65.s:355-396`).
- **`LOGTAB`**: bank `$1F`, 32,768 words, round(log2(n) x 2048) (`tools/gentables.py:20-24`). Used for sight and C14 BSP side tests (`p_sight65.s:108-109`; `r_bsp65.s:1237-1311`). Per-node and per-line logs are in bank `$21` (`p_sight65.s:100-104`).
- **`SINE`**: bank `$20`, 64 KB, 8192 x 4 bytes each of finesine and finecosine (`tools/gensine.py`).
- **Smaller tables:**
  - `finetangentTable_part_3` (1,024 words) and `_part_4` (1,024 longs) at `r_seg65.s:3459`, `:3588`;
  - `tantoangleTable`, 2,049 longs (`r_iigs65.s:1144`);
  - `xtoviewangleTable`, 161 words (`tables65.s:341-344`);
  - sprite scale tables for d = 1..1280, about 32 KB at `$22:0000` (`r_thing65.s:32-38`; `memmap.inc:66-70`);
  - C16 kernels, 1,088 bytes at `$00:AF00` (`iigs.scm:75-77`).

# 6. RAM

| Region | Contents | Size |
|---|---|---|
| Bank `$00` | DP, WPAGE, stack, low code, disk code, music IRQ | 64 KB |
| Bank `$01` | Screen buffer 32,000 + `STCACHE` 5,120 + fuzz tables + `TEXLO`/`TEXHI` | ~38 KB used |
| Bank `$02` | Near data and BSS (`fullcolormap` 8,704; drawsegs 128x42; vissprites 80x42; openings 2560x2) | 64 KB |
| Banks `$03-$05` | Code | 192 KB of address space |
| Banks `$06-$09` | Zone | 256 KB |
| Bank `$0A` | Misc, including weapon profiles | — |
| Bank `$0B` | Includes `NIBTAB` | 16 KB |
| Bank `$0C` | Misc | — |
| Bank `$0D` | Colormaps (17,408), `TINTPAL`, `FLATCM` | — |
| Banks `$10-$12` | Resident WAD | 192 KB |
| Banks `$13-$1A` | Square tables | 512 KB |
| Banks `$1B-$1C` | `FSTEP` | 128 KB |
| Bank `$1D` | Records (≤53,760 used) | 64 KB |
| Banks `$1E`/`$1F`/`$20` | Reciprocal / log / sine | 192 KB |
| Bank `$21` | Sight/move tables | ~62 KB |
| Banks `$22-$26` | Sprite tables, `VIEWSAVE`, seg angles/vertices, `FS`, `COLDIR`, busy sign, text code, capture buffers | — |
| Banks `$27-$29` | Music 44 KB + SFX PCM 140 KB | 184 KB |
| Banks `$2A-$3F` | Level window, 22 banks | 1,408 KB |
| Banks `$40-$6F` | 8 MB machines only: level store and songs | — |

Sources: `memmap.inc:15-148`; `iigs.scm:1-27`.

**What truly needs more than 1 MB:**

- **The level window is the only large, irreducible item.** It holds each map's lumps, wall patches, sprites and composed columns. `w_level65.s:527-529`: "E1M3 needs 22.97 banks without these textures, 23.48 with all of them", which is about 1.5 MB.
- **About 830 KB of tables are pure speed-for-space and replaceable:** `SQL`/`SQH` 512 KB, `FSTEP` 128 KB, reciprocal, log and sine 192 KB.
- **The per-frame renderer working set is small:** records ≤54 KB, colormaps 17 KB, the 26,880-byte view, about 4 KB of drawer code (plus 2.2 KB of fuzz code), plus the texels of the visible textures.

# 7. Stale comments and anything I could not confirm

- **Records bank.** `r_list65.s:11-13` says `RECBANK` is not cached, and `lists.inc:81`, `:114`, `:128` say "Bank $74: the cache does not hold it". These are stale: `RECBANK` is now `$1D`, which is cached (`lists.inc:6-9`), and `FS`/`CV`/`WCLIP` are in banks `$23` and `$0A`.
- **FSTEP location.** `m_recip65.s:363` says `FSTEP` is in banks `$7E-$7F`; `memmap.inc:51` puts it at `$1B`.
- **gendraw docstring.** `gendraw.py:8-16` describes a JSR entry and an RTS exit, with A and B being swapped nibbles. The runtime uses `JMP (RL_TENT)`, a patched `JMP` exit through text-page vectors, and four-colour mixes.
- **Unverified without a link map:** the T table sitting in slots `$1800-$1DFB`, and the `DC_*` offsets (I inferred them from `r_list65.s:44-48`).
- **"REP/SEP costs a slow cycle"** and the write-buffer behaviour come from the author's MAME bus model. README line 13 itself doubts that real hardware behaves this way.
- **All cycle counts are my estimates.** The source's own timings are "~4 FPS" on an emulated 12 MHz ZipGS (`README.md:15`) and "222 ms against 135 ms" (`w_level65.s:521-522`).
