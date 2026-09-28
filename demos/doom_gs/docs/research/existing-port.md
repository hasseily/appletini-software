
# Technical report: the Appletini Doom port (read-only survey)

**File index.** Citations below use `file:line`. All paths are under `<appletini-software>/demos/doom/`:
- Kernel:
  - `src/kernel/video.s`, `frame.s`, `kernel.inc`, `kstart.s`, `loader.s`, `far.s`, `space.s`, `gamebanks.s`, `gamebanks.inc`, `banked.inc`, `amem.s`, `input.s`, `profile.s`, `profile.inc`, `rview.inc`
  - `src/doom.cfg`
- Renderer: `src/render/rlc.s`, `rsegs.s`, `rplane.s`, `rmain.s`, `rmasked.s`, `rthings.s`, `rdefs.inc`, `rmul.inc`, `rfmul.s`, `rpacket.inc`, `stub.s`
- Tools: `tools/a2sim.py`, `run_doom.py`, `build_disk.py`, `wad2a2.py`, `fetch_freedoom.py`, `build_banked.py`, `doomdbg.py`, `profile_doom.py`, `profile_hardware.py`
- Build and tests: `Makefile`, `tests/*.py`
- Docs: `README.md`, `docs/{DESIGN,STATUS,PROFILING,TURBO_MEMORY_STUDY,BANKING_OPTIONS}.md`
- External: the memory API spec is at `<appletini-one>/README_MEMORY_API.md` (F1.1.4, commit 6335a98).

Git branch is `claude/iigs-doom-port`; the tree is clean.

---

## 1. Video pipeline

**Mode.** The port uses SHR4 PAL256 in aux bank 0 (DESIGN.md:60-73, video.s:4-9, kernel.inc:62-68).
- Screen is 320×100 at one byte per pixel. Row y is at aux `$2000+320*y` (`$2000-$9CFF`).
- Each byte indexes a 256-entry RGB444 palette at aux `$9E00-$9FFF`:
  - byte 2i = `G<<4|B`
  - byte 2i+1 = `$20|R`
  - the high nibble 2 is the PAL256 selector.
- Magic `"SHR4"|$80` = `$D3 $C8 $D2 $B4` goes at `$9DFC-$9DFF`. The paging byte at `$9DF8` is 0 (progressive; 1 = interlace, 2 = page-flip, per a2sim.py:1345-1358).
- NEWVIDEO `$C029 = $C1`; bit 5 forces luminance.
- On the 640×400 output each SHR pixel is 2×4.
- **SCBs are not used.** `video_init` just zeroes `$2000-$9DFF`, SCBs included (video.s:55-83).

**3D view.** The view is 160×84 "game pixels" in low detail. Rows 84-99 are reserved for a status bar that is not drawn (DESIGN.md:104-113).
- Projection: centerx 80, centery 42, focal length 80, 90° FOV (DESIGN.md:444-453; tables.inc CENTERX/CENTERY/PROJ).

**Composition.** Nothing is drawn directly to SHR.
- The renderer writes a chunky, column-major 8-bit buffer in main RAM: `VIEWBUF = $8B80`, 13,440 bytes. Column x is at `VIEWBUF+84*x` (doom.cfg:34-37).
- Values are Doom palette indices that have already been through a colormap.
- The buffer is cleared every frame, by ARM FILL or CPU `kmemclr` (space.s:137-143, amem.s:226-252).

**Presentation** (video.s:189-267).
- `present` checks `$C019`. Outside VBL it blits at once; during VBL it spins until line 0 (`kwaits` counts these).
- `blit_view` lives in main LC bank 2 (`KLC2`). It selects `$C073=0` with RAMWRT on and copies each column, writing every byte twice (horizontal doubling):

  ```
  ; video.s:245-255 (unrolled .repeat VIEW_H)
  iny
  lda (bz_p),y
  sta SHR_BASE + SHR_ROW*row, x
  sta SHR_BASE + SHR_ROW*row + 1, x
  ```

  That is 17-18 cycles per game pixel: 13,440 reads and 26,880 writes, ≈236K model cycles (video.s:17-35, DESIGN.md:115-118).
- The comment's premise (3.1 ms at 75 MHz, so no tearing) does **not** match hardware. The v12 capture samples the blit at ≈24 ms/frame (§5). **Inference:** on PAL that is longer than a 20 ms field, so the line-0 policy cannot be tear-free on real hardware.
- The model has also recorded a blit crossing line 0 (STATUS.md:481-485).

**Palettes** (video.s:92-174). `set_palette(n)` copies PLAYPAL n (512 bytes, from `DD_DIR_BANK:DD_PLAYPAL+512n`) through `kbuf`, forcing selector 2. It is exposed at jump-table `$E00C` and as a C prototype (kernel.h:65), but **no game code calls it**, so damage and pickup tints are not implemented (my grep found no calls).

**Lighting** (DESIGN.md:340-344, 444-453, 480-481, 501-502).
- Every graphics bank carries the same 16 colormaps (Doom COLORMAP 0,2,…,30) at `$0200-$11FF`, one per page. So a texel and its colormap are read from the same selected RamWorks bank in one RAMRD session.
- Walls and sprites: `scalelight[16][48]`, index `min(scale>>11,47)`.
- Planes: `zlight[16][128]`, index `min(dist>>8,127)`.
- Light = `sector>>4 + extralight`, with ±1 for horizontal/vertical lines.
- Fixed colormap comes from packet byte `RV_FIXEDCMAP`. The invulnerability map (Doom 32) is not rendered (g_game.c:359-362, a_view.s:742-750).
- Fuzz uses colormap 3 (DESIGN.md:518-519).

**Frame order** (`render_frame`, rmain.s:262-293): LC bank 1 in → read the packet header (bank 124) → load the map if it changed → `frame_setup` → BSP walk (walls queued and drawn per range) → `q_flush` → `draw_planes` → `r_things` → LC bank 2 → `r_masked`.

**Hot loop 1: wall/sky column drawer** (`q_flush`, rlc.s:220-307).
- It runs in LC bank 1 with RAMRD on. The texture and colormap are in the selected graphics bank; writes go to main.
- The 32-entry queue (rlc.s:63-88) batches a whole wall range per RAMRD session. `$C073` is only written when `cur_bank` changes.
- Two-pass since v6: gather raw texels into the 256-byte main-LC `kbuf`, then shade.

  ```
  @loop:                        ; rlc.s:258-282
  @src:   lda $FFFF,y           ; texel (patched column base)
          sta kbuf,x
          lda cf_lo
  @stl:   adc #$00              ; 8.8 step lo (patched)
          sta cf_lo
          tya
  @sth:   adc #$00              ; step hi (patched)
  @hm:    and #$00              ; hmask (patched)
          tay
          inx
  @end:   cpx #$00              ; count (patched)
          bne @loop
  @shade: dex
          lda kbuf,x
          tay
  @cm:    lda $0200,y           ; colormap page (patched)
  @dst:   sta $FFFF,x           ; view column (patched)
          cpx #0
          bne @shade
  ```

- My cycle count from the 65C02 tables is ≈32+22 = **~54 cycles/pixel**. The pre-v6 single pass was documented at ~40 (DESIGN.md:795).
- One-colour fills (flat-shaded planes, visplane overflow) use `@floop` (rlc.s:283-299).
- Per-column setup (`seg_loop` rsegs.s:1669-1862, `column_tex` 1946-2145, `piece` 2165+):
  - one 24×24 tangent product per textured column
  - an `iscale` lookup from a reciprocal table
  - rows derived from biased 32-bit accumulators (`ROWB`)

**Hot loop 2: plane span** (`span_draw`, rlc.s:316-376).
- Flats are 32×32 row-major. Coordinates are 16-bit 5.11 per axis, and two lookup tables at `$D000` split the address.
- Pass 1 gathers texels into `kbuf` (rlc.s:324-353). The core is:

  ```
  ldx sp_yf+1 / lda sp_gh,x / spd_bh: adc #$00 / sta spd_tex+2
  lda sp_xf+1 / lsr / lsr / lsr / ora sp_glo,x / tax
  spd_tex: lda $FF00,x / sta kbuf,y / iny
  ```

  followed by two 16-bit adds with patched `spd_xsl/xsh/ysl/ysh`.
- Pass 2 (rlc.s:359-373):

  ```
  lda kbuf,x
  sta spd_cm+1
  spd_cm: lda $0200
  sta (sp_dp),y
  tya / clc / adc #84 / tay / ...
  ```

- My estimate is **~124 cycles/pixel** (~85 + ~39). The pre-v8 single pass was ~100 (DESIGN.md:796).
- Span setup is in `map_plane` (rplane.s:1026-1136): a row cache of distance/steps and per-column sin/cos, about three products per span.
- Visplanes live in RENDER_BANK (rdefs.inc:55-86). The sky is drawn as columns via `sky_piece` (rplane.s:666-757).

**Hot loop 3: sprite post** (rmasked.s:567-581): patched `dvp_src`/`dvp_cm`/`dvp_dst`/`dvp_stl`/`dvp_sth`/`dvp_end`, 40 cycles/pixel (DESIGN.md:880-896). There is a slow path for posts in page `$BF` (rmasked.s:602-640).

**Arithmetic.**
- 8×8 multiplies use quarter squares through four ZP pointers, about 50 cycles each, unrolled per operand shape (rfmul.s:1-26, rmul.inc).
- `R_ScaleFromGlobalAngle` division is ~1,000 cycles (DESIGN.md:760-768).

**Self-modifying code.**
- LC-resident loops:
  - `q_flush` (rlc.s:234-292)
  - `span_draw`, patched by `span_setflat` and `span_setrow` (rlc.s:379-398)
  - `pl_used`
- Main `RHICODE` at `$6000+`, which exists for patched code:
  - `ct_t0..t2` tangent pages (rsegs.s:1981-1994)
  - `ct_wl`, the per-seg walllights row, patched at rsegs.s:893-894
  - `mp_zl`, the per-plane zlight row (rplane.s:904-907, 1117)
  - `dv_cols` and `ms_draw` (rmasked.s:326-333, 772)
- Loader and installer: rewritten page operands (loader.s:868-877, 911-919).
- Rule from doom.cfg:73-90: main `$2000-$5FFF` (and `$0400-$0BFF`) is mirrored to the motherboard, so that window holds only immutable code and tables (`RCODE`/`RRODATA`/`RTEXTDATA`). Patched code goes at `$6000+` or in LC. The phase snapshot saves `RHICODE` (space.s:38-39).
- Tests also patch immediate limit operands in memory (DESIGN.md:816-819).

**Reference renderer.** `tools/refrender.py` is the bit-exact Python spec; the 6502 view buffer must match it byte for byte. `tools/gen_tables.py` generates `build/render/tables.{s,inc}` (DESIGN.md:413-430).

---

## 2. Kernel / platform layer

### Soft switches and banking semantics (kernel.inc:13-33, DESIGN.md:77-85, BANKING_OPTIONS.md:134-158)

| Address | Use |
|---|---|
| `$C002/$C003` | RAMRD off/on: reads of `$0200-$BFFF` come from the RamWorks bank selected by `$C073`. This includes instruction fetches, so code running with RAMRD on must be in ZP/page 1/LC. |
| `$C004/$C005` | RAMWRT off/on (writes only). |
| `$C008/$C009` | ALTZP: ZP, page 1 and the whole LC come from the selected aux bank. |
| `$C073` | RamWorks bank, write-only, 0-127. Bank 0 is base aux (holds SHR). The model also decodes `$C071` and aliases modulo the bank count (a2sim.py:1070-1076, 1131-1132). |
| `sta $C000` | 80STORE off |
| `bit $C08B` ×2 | LC bank 1 read/write |
| `bit $C083` ×2 | LC bank 2 read/write |
| `$C082` | ROM |
| `$C074` | TWSPEED; writing 0 selects the chosen (TURBO) speed (loader.s:128, kstart.s:122) |
| `$C019` | bit 7 = 0 during VBL |
| `$C029` | NEWVIDEO |
| `$C006` | INTCXROM off |
| `$C061/$C062` | Open Apple / Closed Apple |

- The model maps the alternate `$D000` half of an aux bank's LC at physical `$C000-$CFFF` of that bank (a2sim.py:867-875, 989-995, 1027-1034).
- `$C073` sizing: write each bank's number from 127 down to 0, then read back upward through a page-1 stub (loader.s:694-735).

### Memory layout of the banked build (STATUS.md:8-61, DESIGN.md:122-220)

| Region | Contents |
|---|---|
| Aux LC banks 96, 97, 98, 99, 0, 101, 102 | Seven permanently loaded game code images (`$D000-$FFF9`, own vectors). Bank 0 = base aux LC, the fast control bank; build default `CONTROL_BANK=0`. |
| Bank 125 | Game-phase backing |
| Bank 122 | Renderer-phase backing, plus five 256-byte AMEM overlay pages at `$B800-$BCFF` |
| Bank 124 `$0200` | 2,600-byte render packet (banked.inc:6-9) |
| Bank 127 | Math tables |
| Bank 1 | Blocklink heads and `GAME.INFO` at `$6000` |
| Bank 126 | Specials journal |
| Banks 2-95 | Freedoom data |
| RENDER_BANK = DD_LAST_BANK+1 = 96 (lower RAM) | Visplanes, drawsegs and openings (rdefs.inc:35, 55-86). This is the same bank as code bank 96's LC; lower RAM and LC are independent. |

Main memory map (doom.cfg:40-62, 73-104):
- `RLOW $0200-$03FF`
- `RTEXT $0400-$0BFF` (read-only)
- `RMAIN $0C00-$8B7F`:
  - RLOBSS
  - RRODATA from `$1FBC`
  - RCODE up to `$5FFF`
  - RHICODE, RDATA and RBSS from `$6000`
- `VIEWBUF $8B80-$BFFF`
- Main LC:
  - bank 2 `$D000` (`KLC2`: blit, then `RLC2`, the masked phase)
  - `$E000-$FFF9` (`KJT` jump table at `$E000`, KCODE, KBSS incl. `kbuf`, RLCHI)
  - bank 1 `$D000` (`RLC1`: RAMRD loops, `KLC1TAIL`)
- Free bytes in v12: LC1 16, LCHI 3, LC2 82 (STATUS.md:389-392). The main arena is 31,551 bytes.

### Far access (far.s; C API in `src/game/kernel.h:16-67`)

- ZP args `far_src[3]`, `far_dst[3]` (lo, hi, bank), `far_ptr[2]`, `far_len[2]`, `far_idx[2]` (far.s:41-51).
- `far_read`: `$C073=bank`, RAMRD on, `copy_len`, RAMRD off (far.s:61-79).
- `far_write`: same with RAMWRT (far.s:98-116).
- `far_copy`: bank→bank through the 256-byte `kbuf` bounce buffer, since both switches follow `$C073` (far.s:137-165, 199-232).
- `far_elem`: descriptor `{bank, base, size, log2}` → element address (far.s:266-332).
- Rule: no transfer crosses `$BFFF`.
- Jump table at `$E000` (kstart.s:27-37, 67-96). In the banked build, game-facing entries are `GB_GATE`s into main context.
- The renderer uses its own LC routines `rb_read`/`rb_read1`/`rb_write_on` with `cur_bank` caching (rlc.s:91-155), about 14 cycles/byte.

### Phase swap (space.s)

Game and renderer each own main `$0200-$BFFF` in turn.

- **`space_game`** (space.s:62-103):
  1. Save renderer ZP into the first VIEWBUF bytes.
  2. Save renderer mutable ranges `$0200-$03FF`, `$0C00-$1FFF`, `$6000-RENDER_END` (`RENDER_END` = page after VIEWBUF+RZP, space.s:43) to bank 122.
  3. Load game `$0200-phase_game_end` from bank 125.
- **`space_render`** (space.s:105-151):
  1. Publish `render_map`.
  2. Save game `DATA..arena end` (page-rounded) to 125.
  3. Restore the whole renderer `$0200-RENDER_END` from 122.
  4. Restore renderer ZP.
  5. Clear VIEWBUF.
- Transfer volume is ≈106,752 bytes per frame on E1M1 (TURBO_MEMORY_STUDY.md:238-243), plus the 13,440-byte clear.
- The CPU fallback is an 8×-unrolled `lda (ktmp),y / sta (ktmp),y` loop, 3,437 cycles per 256 bytes (amem.s:104-130, TURBO_MEMORY_STUDY.md:346-349).
- `call_game_active` copies `kin` and `kbanks` into game-visible main storage, then `jmp (kcall)` (space.s:252-260).

### Code-bank gateway (gamebanks.s, gamebanks.inc)

- `GB_GATE bank,target` = `jsr gb_call` plus three inline bytes (gamebanks.inc:16-21).
- `gb_call` (gamebanks.s:163-200) proceeds as follows:
  1. Save A/X/Y/P.
  2. Export 54 logical ZP bytes: 8 game, 26 cc65, 12 far args, 8 `ktmp` (gamebanks.inc:5-11).
  3. Save S per context in `gb_saved_sp[129]`.
  4. Select the context (gamebanks.s:89-101): `sta $C073; sta ALTZPON`, or `ALTZPOFF` for main (`$80`), then `txs`.
  5. Import ZP, push the return bank and `gb_return`, then `jmp (target)`.
- Nesting and callbacks (A→B→A) are safe. IRQs are masked during transitions.
- `gb_irq` (gamebanks.s:220-238): aux-bank IRQ vectors borrow the main stack and call `gb_irq_service`.
- **NMI sources must stay disabled** (gamebanks.s:31-35).

### ARM copy/fill (amem.s; API spec README_MEMORY_API.md:75-235)

**Transport** (`EXCHANGE`, amem.s:37-65):
1. `bit $CFFF` (release C8), then `bit $C700` (select slot-7 C8).
2. Push request bytes to `$CFF0`.
3. `sta $CFF1` with A=2 (execute).
4. Poll `$CFF1` bit 7. The bound is a 3-byte counter; timeout returns status `$6F`.
5. `lda $CFF0` / `sta $CFF2` to pop the status into `amem_status`.

No slot-ROM entry is used, because the ROM writes `$07F8`.

**Probe** (amem.s:146-223):
- Request: STATUS `.byte 0,3,0,0,0,$80,0,0,0,0`.
- Requires:
  - slot-7 bytes `$C701=$20`, `$C703=0`, `$C705=3`, `$C707=0`
  - `$CFF1&$3F=$20`
  - a 32-byte capability block with `"AMEM",1`, descriptor size 16, ≥4 descriptors, features&7=7, address limits `$0200`/`$C000`, max bank ≥125, and the available bit
- Temporary bytes go into VIEWBUF.

**CONTROL request** (`REQUEST`, amem.s:67-71):
- `.byte 4,3,0,0,0,$80,0,0,0,0`
- `.word 8+16N`
- `"AMEM",1,N,0,0`
- then N 16-byte descriptors: `{op 1=COPY/2=FILL, flags bit0=PRIVATE, src space(0 MAIN/1 AUX), src bank, src addr16, dst space, dst bank, dst addr16, count16, fill byte, 3×0}` (API :128-142; `PHASE_COPY` macro amem.s:273-279).

**Rules** (API :147-192):
- PRIVATE is required for MAIN and base-AUX destinations. It produces no renderer capture and no motherboard replay, so it must **not** be used to update the displayed SHR.
- AUX banks 1-126 only; bank 127 is excluded.
- Endpoints in `$0200-$C000`; no same-bank overlap.
- One CPU hold per list, in 504-byte internal chunks.
- `$60` means unavailable, and Doom falls back to the CPU. Any other failure goes to `kernel_crash`; a partial batch is never replayed (amem.s:257-270).

**Doom's usage.** Five overlay pages are loaded into `kbuf` and entered by `jmp kbuf` (space.s:159-165, 201-224):

| Page | Routine | Protocol / contents |
|---|---|---|
| `$B8` | `amem_copy` | A=bank, X=first page, Y=exclusive last page, C=1 load (bank→main), C=0 save (amem.s:73-140) |
| `$B9` | probe | as above |
| `$BA` | FILL | VIEWBUF |
| `$BB` | GAME batch | 4 descriptors |
| `$BC` | RENDER batch | 2 descriptors (amem.s:283-323) |

`amem_init` is at amem.s:24-32.

### Input (input.s)

- The mouse card must be in slot 2. `input_init` checks ID bytes `$C205=$38`, `$C207=$18`, `$C20B=$01`, `$C20C=$20`, then:
  - ACK=3
  - clamp X to 0..`$FFFF` via `$C0A7-$C0AC`
  - X = `$8000`
  - mode `$09` (enable + VBL IRQ) (input.s:102-136)
- `input_frame` (input.s:139-256):
  - Keyboard: `$C000`, strobe clear via `$C010`, bit 7 of `$C010` = any key held. The //e only reports the last key.
  - Buttons: `$C061/$C062`.
  - Mouse X only, read between two reads of the sequence byte `$C0A6` to detect tearing, then re-centred when outside `$2000-$DFFF`.
  - Mouse buttons from `$C0A5`.
- Output is the 8-byte `kin` block (input.s:21-37, kernel.h:34-55). `input_consume` runs after the first tic of each frame (input.s:269-279).

### Timing and VBL

- The mouse-card VBL IRQ at `$FFFE` enters `irq_entry` (kstart.s:200-212, 313-316).
- `irq_mouse_service` (kstart.s:271-285): `ldx $C0A0`, `lda #3 / sta $C0AF`; only if status bit 3 (VBL cause) is set does it increment the 16-bit `vbl_count`. This qualification fixed an IRQ over-count on TURBO (STATUS.md:121-126). BRK → crash `$01`.
- Scheduler (frame.s:61-116, 199-275):
  - each VBL adds 7 units; a tic costs 10 units (PAL) or 12 (NTSC), giving 35 TPS
  - `MAX_TICS=4` (frame.s:41); excess tics are counted in `kdropped` and discarded
  - V toggles 50/60 Hz; the `VIDEO_HZ` build option sets the default
- The mouse card is required (crash `$02` otherwise, kstart.s:154-157).

### Profiling mailbox (profile.s, profile.inc)

- `PROFILE_STAGE n` stores `profile_stage` (13 phases, profile.inc:4-17).
- `profile_tick` runs on each VBL IRQ and increments `profile_samples[stage]` (profile.s:15-20).
- `profile_publish` (profile.s:37-99): at most once per 60 VBLs it builds a 44-byte `DPR1` block: seqlock word, magic, 4-byte build id, vbl/frames/tics, Hz, 13×u16 samples (profile.s:25-35). It then `far_write`s it to **aux bank 0 `$A000`**, just above the palette, as odd sequence → block → even sequence.
- The host reads it over UART at 921600 with `vtw dump 1A000 2C` (profile_hardware.py:172-173, PROFILING.md:35-97).

### Boot (loader.s)

`DOOM.SYSTEM` loads at `$2000` (header loader.s:1-55). Steps:
1. Disconnect `/RAM`.
2. Count banks; **128 are required** (`MIN_BANKS`, kernel.inc:75).
3. Get the prefix and read 4 directory blocks.
4. Load every BIN file with aux type `$0000` in directory order as an `A2DM` bank file (loader.s:156-213, 238-313):
   - Segment rules: bank ≥1, below `nbanks`; address ≥ `$0200`; end ≤ `$C000`.
   - Reads go in ≤7,680-byte pieces into main `$A000`, then are copied with `$C073=bank` and RAMWRT on (loader.s:346-421).
5. Load the images (loader.s:216-233):
   - `GAME.BIN` → bank 125
   - `RENDER.BIN` → aux bank 0 `$0200` (staged)
   - `LC.BIN` (16 KiB) → main `$6000`
6. Install (loader.s:780-809, 838-898):
   - `sei`
   - LC bank 1, then bank 2
   - aux-LC code images from their staging banks, 4 KiB at a time via `far_read`
   - a page-1 installer copies aux0 → main and then `jmp kernel_start` (loader.s:904-924)
7. Errors before install show a message and QUIT to ProDOS.

`kernel_start` (kstart.s:110-172) clears ZP/BSS/VIEWBUF, then runs `video_init`, `input_init`, `amem_init`, `game_phase_init`, `cli`, `frame_loop`.

---

## 3. Emulator and test harness

### What `a2sim.py` models (module doc a2sim.py:1-68)

- **CPU:** py65's `mpu65c02`.
- **Memory:**
  - main plus 128 RamWorks aux banks (`$C073`/`$C071`, modulo aliasing)
  - RAMRD/RAMWRT/ALTZP/80STORE+PAGE2/HIRES
  - LC with double-read write enable
  - ALTZP LC per selected bank (a2sim.py:958-1034, 1056-1076)
- **Timing:**
  - `speed=N` → 17,030·N cycles per 60 Hz frame
  - `speed="turbo"` → 1,250,000 cycles (nominal 75 MHz) plus a 73-cycle surcharge per `$C0xx-$CFFF` access (a2sim.py:75-80, 852-859, 977, 1021, 1080)
  - VBL at line 192; frame start (line 0) at cycle 0
- **Explicitly not modelled:** PSRAM/cache latency, TURBO batching, or mirror flushes. Video and SHR writes are only counted (a2sim.py:1007-1015).
- **Devices:**
  - mouse card: registers, clamp, sequence, VBL IRQ (a2sim.py:105-243)
  - keyboard (`press`/`hold`/`release`), buttons, paddles, speaker counter, `$C019`, `$C029`
  - Phasor: registers only, no timer IRQs
  - `FakeSmartPortMemory`: opt-in AMEM FIFO with failure injection (a2sim.py:698-837)
- **Idle skip:** `idle_pcs[pc] = "vbl" | "line0" | (kind, predicate)` jumps the clock forward (a2sim.py:1216-1233).
- **ProDOS:** `FakeProDOS(files | from_directory)` traps `JSR $BF00` operand fetches from main RAM. It implements open/read/write/close/create/destroy/info/prefix/online/mark/eof/quit and synthesizes real directory blocks (a2sim.py:406-696, 949-967). It does not boot a `.hdv`.
- **Screenshots:**
  - `shr_image()` → 640×400 PIL image of PAL256 (all three paging modes) or standard SHR with SHR4 selectors (a2sim.py:1341-1393)
  - `pal256_pixels()`, `pal256_palette()`, `text_screen()`, `hgr_image()`

### `run_doom.py`

- CLI: `python3 tools/run_doom.py [--build DIR] [--data DIR] [--frames N] [--speed turbo|N] [--banks 128] [--fast] [--do 'F:ACTION'] [--shot F] [--out DIR] [--stats FILE] [--trace LABEL] [--quiet]` (run_doom.py:1-47, 411-432).
- Default boot goes through `FakeProDOS` and the real loader. `--fast` places images and data from Python and starts at `kernel_start` (run_doom.py:154-191).
- `--frames` counts model 60 Hz intervals, not rendered frames.
- Actions: `key`, `hold`, `release`, `mouse DX`, `down`/`up`/`rdown`/`rup`, `oa`/`ca`, `shot NAME` (run_doom.py:273-301).
- Per-frame lines: work cycles excluding idle, blit cycles, waited, torn, io, shr writes. `OUT/final.png` is always saved. `--stats` writes JSON (run_doom.py:303-408).
- **It is Doom-specific.** It needs `doom.lbl` labels (`idle_wait`, `vbl_count`, `clk_last`, `present_wait`, `frame_top`, `present_blit`, `present_done`, `kernel_crash_stop`, `kernel_start`, `ktics`, `kcrash`, `kspace`) and the files `DOOM.SYSTEM`/`RENDER.BIN`/`LC.BIN`/`GAME.BIN`, plus `banked.json`/`DOOM.BANKS` when banked (run_doom.py:65, 111-146).
- The ROM defaults to `$APPLETINI_ROOT/docs/Apple2e_Enhanced.rom`, i.e. `<appletini-one>/docs/Apple2e_Enhanced.rom`, which is present (run_doom.py:63-64).
- `tools/doomdbg.py` calls labelled routines. `tools/profile_doom.py` gives bank-aware per-function cycle profiles (PROFILING.md:457-496).

### Reusing the harness for arbitrary binaries

**Yes, via the Python API.** There is no generic CLI. Example:

```python
import sys; sys.path.insert(0, "<appletini-software>/demos/doom/tools")
import a2sim
m = a2sim.Machine("<appletini-one>/docs/Apple2e_Enhanced.rom",
                  speed=33,            # or "turbo"; ramworks_banks=128 default
                  prodos=None,         # or a2sim.FakeProDOS({"NAME": bytes | (type, aux, bytes)})
                  smartport=None)      # or a2sim.FakeSmartPortMemory()
m.load(0x2000, open("PROG.SYSTEM", "rb").read())    # main; aux_bank=n for RamWorks
m.bank_memory(5)[0x0200:0x0300] = b"..."            # direct bank access
m.mpu.pc, m.mpu.sp = 0x2000, 0xFF
m.idle_pcs[0x1234] = "vbl"                          # optional idle skip
m.run(60 * m.frame_cycles, stop_pc=0x5678)          # or m.step()
m.hold(ord("W")); m.mouse_delta(16, 0)
m.shr_image().save("shot.png")                      # PAL256/SHR -> 640x400 PNG
```

- For LC images, write `m.lc[False][addr-0xC000]` (bank 2/`$E000`) and `m.lc_bank1[False]`, and set `m.lc_read = m.lc_write = m.lc_bank2 = True` (pattern at run_doom.py:184-187).
- `m.cycles`, `m.io_accesses`, `m.shr_writes` and `m.idle_cycles` are available.

### Tests

- `make test` runs every `tests/test_*.py` in sequence with `$(PYTHON)` (Makefile:185-186). There are 29 unittest files.
- Many tests skip without `build/data`, the ROM, or `DOOM_VANILLA_SRC`/`DOOM_ZDOOM_ACTORS`.
- Some tests build their own configurations:
  - `test_platform.py` runs `make STANDIN=1` (test_platform.py:49-51)
  - `test_doom_banked_platform.py` runs `build_banked.py` into `build/host/banked-platform` (test_doom_banked_platform.py:20-34)
  - host C tests use `gcc`
- Flat and banked game simulators: `tests/host/gamesim.py`, `tests/host/bankedsim.py`.

### Dependencies

- cc65 2.18 is at `/opt/homebrew/bin`.
- Python needs `py65` and `Pillow`; pyserial is needed only for hardware capture.
- **py65 is not installed in either system python3** (3.14 at `/opt/homebrew/bin`, or `/usr/bin`). A working venv exists at `<temporary venv>` (py65 plus Pillow 12.3.0). It is ephemeral; the release verification used it.
- The sibling `appletini-one` supplies the ROM and `software/ProDOS_2_4_3.po` (both present).

### Run time (I measured this, in memory, no files written, on the existing `build/`)

| Run | Model cycles | Host time |
|---|---|---|
| `--fast` install | – | ≈0 s |
| First frame (includes E1M1 `game_init`) | 48.25 M | 13.4 s |
| Each later frame (4 tics) | 10.29–10.43 M | 2.9–3.0 s |

- That is ≈3.5 M model cycles per host second.
- Full ProDOS-loader boot: 73.6 M model cycles, 23.7 s, 776 MLI calls.
- **Estimate:** the README command (`--speed 33 --frames 180`) takes ≈1 min.
- Recorded suites: clock tests 1.4 s, memory-API 35 s (14 tests), profiling runtime 21 s (build/profile-v12-amem-batch-pal/*.log). The full `make test` duration is not recorded; I expect tens of minutes.
- **Caveat:** `build/` is stale. Its `banked.json` has control bank 100 and no AMEM, and `banked.stamp` predates `CONTROL_BANK`, so `make` will relink. Current artifacts are in `build/profile-v12-amem-batch-pal/` and `build/hardware-20260926-*`.

---

## 4. Disk builder and data converter

### `build_disk.py`

- Output is a pure-Python ProDOS block-order `.hdv`, sized to its contents plus 64 free blocks, ≤65,535 blocks (build_disk.py:1-31, 40-67).
- Layout:
  - blocks 0-1: boot code from the master `ProDOS_2_4_3.po`
  - 4 directory blocks (**51 entries**)
  - bitmap
  - files in order: `DOOM.SYSTEM` (SYS, aux `$2000`), `PRODOS`, `RENDER.BIN` (BIN, `$0200`), `LC.BIN` (BIN, `$D000`), `GAME.BIN` (BIN, `$0200`), then every `A2DM` data file plus `DOOM.BANKS` as BIN aux `$0000` (build_disk.py:511-538, 541-582)
- After writing, it re-reads and verifies every byte and the bitmap (build_disk.py:437-489).
- Hard-coded: the `IMAGES` tuple (build_disk.py:60) and `VOLUME_NAME "DOOM"` (line 42).
- Current image: 4,473,344 bytes, 8,737 blocks, 40 data files (build/hardware-20260926-textured-pal.log). Together with the 6 program files that is 46 of 51 directory entries.

### `wad2a2.py` (docstring wad2a2.py:1-86; DESIGN.md:273-411)

**Outputs** into `build/data`:
- `DIR.1` (directory bank 2)
- `GFX.1..15` (39 graphics banks, 3..41)
- `E1Mx.n` (map banks from 42)
- `doomdata.inc`, `doomdata.h`, `manifest.json`, `preview/`

Totals: 94 banks (2..95), 4,233,063 data bytes (manifest stats).

**File format.** Each file is ≤128 KB:
- 256-byte header: `"A2DM"`, version 1, n≤49 segments of `{bank u8, addr u16, len u16}`
- then the segment bytes

**Asset formats:**
- All pixels at half resolution; index 247 = transparent.
- Textures: column-major, padded to powers of two.
- Flats: 32×32 row-major.
- Sprites: post format.
- Colormaps: 16 at `$0200` of every graphics bank.
- PLAYPAL pre-converted to PAL256 RGB444, 14×512 bytes, in `DIR`.
- Far array descriptors are chunked so no element crosses a bank.

**Preload.** The whole episode is loaded into RAM at boot; there is no runtime disk I/O. The loader streams each segment to `bank:address` (§2 Boot).

**`DOOM.BANKS`** is built by build_banked.py:62-79. It is the same `A2DM` format, containing:
- each `GBANK*.BIN` at its staging bank `$0200`
- `GAME.TABLES` → bank 127 `$0200`
- `GAME.INFO` → bank 1 `$6000`
- `AMEM.BIN` → bank 122 `$B800`

**WAD source.** Freedoom Phase 1, fetched from the npm tarball `https://registry.npmjs.org/kaboom.claude/-/kaboom.claude-1.5.3.tgz`, member `package/engine/freedoom1.wad`, SHA-256 `7323bcc1…9f703d` (fetch_freedoom.py:30-33).
- The Makefile stores it as `build/freedoom1.wad` (`FREEDOOM ?= build/freedoom1.wad`, `--out $(dir …)`, Makefile:19, 90-94). That differs from the `build/wad/` path given in DESIGN.md:275-277 and the script's default.
- `FREEDOOM=path` overrides it.

---

## 5. Measured hardware performance

Setup: TURBO, stationary E1M1, PAL, 60 s serial captures.

| Build | FPS / TPS | Change |
|---|---|---|
| v2 `efd1f27f` | 2.28 / 9.13 | IRQ fix + packet flag table |
| v3 `61904a52` | 2.30 / 9.20 | scratch moved out of main HGR posted window: no gain |
| v4 `afed1603` | **3.22 / 12.87** | control code/ZP/stack moved from bank 100 to base-aux bank 0: **+40%**; packet 125.8 → 7.0 ms/frame |
| v5 `5ec12366` | 3.32 / 13.28 | copy only the live arena, 8× unroll: +3.2% |
| v6 `d18e857a` | 3.41 / 13.66 | two-pass wall column: +2.9%; walls 86.8 → 79.0 ms |
| v7 `bbc57588` | 3.71 / 14.85 | hot static loop moved from LC bank 97 into main RAM: +8.7%; game tics 54.9 → 29.2 ms |
| v8 `7aafbe11` | 3.73 / 14.92 | two-pass spans: no gain |
| v9 | rejected | 16 catch-up tics: worse controls and FPS |
| v10 | never measured | – |
| v11 `ac9e0e63` (F1.1.4) | **4.03 / 16.13** host | ARM copies: +7.6% vs v8, confounded with firmware change |
| v12 `e2676d7e` | 4.03 / 16.13 | batching 7 → 3 requests: **no gain** |

Sources: STATUS.md:119-237, 239-263, 315-353, 410-442; README.md:6-20.

**Frame time.** ≈248 ms/frame on the host clock.
- The 4-tic cap is saturated: TPS is 46% of 35, and reaching 35 TPS needs 8.75 FPS (STATUS.md:350-353).
- Model cost is ≈10.3–11.4 M py65 cycles/frame (STATUS.md:473-484, plus my runs). There is no hardware cycle counter.

**v12 time per frame** (samples × 20 ms / 242 frames, from `build/profiles/e1m1-idle-turbo-v12-amem-batch-pal.json`). These are coarse VBL samples, and ARM holds can undercount copies.

| Phase | ms/frame |
|---|---|
| walls | 78.6 |
| planes | 33.6 |
| game tics | 32.5 |
| **SHR blit** | **24.0** |
| render copy | 22.3 |
| game copy | 18.2 |
| masked | 16.3 |
| packet | 9.4 |
| things | 4.0 |
| debug | 1.5 |
| setup | 0.7 |
| wait | 0 |

For comparison, v8's two copy phases took 72.3 ms together (effective ≈1.48 MB/s, TURBO_MEMORY_STUDY.md:514-519).

**Lessons on what is fast and slow on this hardware:**
1. **Extended RamWorks banks (PSRAM) are slow for code, ZP and stack.** They sit behind one shared 8-byte write-allocate cache line; the 128-byte shadow cache does not cover PSRAM (TURBO_MEMORY_STUDY.md:262-265, 351-356). Main memory and base-aux bank 0 are fast BRAM. Put hot code in main or base-aux LC; this gave the +40% (v4) and +8.7% (v7).
2. **Bank switching has a hidden cost.** In F1.1.1, every `$C071/$C073` write, every `$C080-$CFFF` access (LC switches) and the mouse IRQ's `$C0A0/$C0AF` accesses trigger a full video-mirror flush (TURBO_MEMORY_STUDY.md:97-115, 135-149). Batch per bank: the renderer's `cur_bank` cache, the 32-entry piece queue, and one RAMRD session per wall range.
3. **Separate texture reads from colormap reads.** This helped walls a little (v6) and did nothing for spans (v8). Model instruction counts mispredict hardware: the v5 model said −8.2% and hardware gave −3.2%; v6 cost +1% CPU and still gained 2.9%.
4. **Moving writable data out of main's posted video windows** (`$0400-$0BFF`, `$2000-$5FFF`) is correct practice, but had no measurable effect for 8,306 writes/frame (v3).
5. **Bulk copies:** the CPU loop is ≈1.5 MB/s effective. The ARM API is an estimated ≤8 MB/s scheduler bound (TURBO_MEMORY_STUDY.md:357-362). Batching requests did not help. ARM holds merge VBL IRQs, so use host time.
6. **SHR writes are costly (my inference).** ≈24 ms for 26,880 byte writes is ≈0.9 µs per write, close to the motherboard bus rate, even though "TURBO batches video writes". SHR (aux) keeps active mirroring (TURBO_MEMORY_STUDY.md:69-72). Minimize bytes written to SHR per frame.
7. **Tic scheduling:** keep catch-up small. v9's 16 tics/frame made both FPS and control feel worse.

---

## 6. Known limitations and unfinished items

- **Missing screens:** no HUD/status bar, title/menu, or intermission/finale presentation. Esc only sets a flag (STATUS.md:84-92, README.md:77-81).
- **No audio:** there is no Phasor sound or music backend; effects are only logged (DESIGN.md:1617-1622).
- **Palette/colormap gaps:** palette tints are never applied (`set_palette` is unused), and the invulnerability colormap is dropped (g_game.c:359-362).
- **Out of scope:** multiplayer, savegames, demos, automap, and high detail (DESIGN.md:37-38).
- **Tearing:** the line-0 tear-free guarantee is unproven (video.s:26-35, STATUS.md:481-485), and the ≈24 ms hardware blit makes it unlikely on PAL (inference).
- **Game slowdown:** game time slows below 8.75 FPS because of the 4-tic cap.
- **Hardware requirements:** 128 RamWorks banks (8 MB) and a slot-2 mouse card; NMI must be disabled; E1 only.
- **Renderer limits:** MAXVISPLANES 128, MAXDRAWSEGS 160, MAXVISSPRITES 96, openings 2 KB, BSP depth 64; things beyond 20,480 units are not drawn (DESIGN.md:552-565, 936-941).
- **Memory is nearly full:** LC free bytes are 16/3/82, and the main arena margin is ≈970–1,176 bytes (STATUS.md:65-70, 389-392).
- **Directory limit:** 51 entries, of which 46 are used.
- **Validation gaps:**
  - hardware profiling covers only stationary E1M1; movement, combat and map changes are unmeasured
  - v10 was never measured
  - prolonged play across all nine maps is untested on hardware (STATUS.md:92, 353, 442)
- **The Python "turbo" mode is not a hardware timing model** (README.md:116-120).
- **Repo hygiene:**
  - `build/` is stale (see §3)
  - the README's `dist/…profile-v12…hdv` is gone; `dist/` has only the `Appletini-DOOM-20260926-pal{,-flat-planes}.hdv` pair (commit d69eb58a)
  - py65 is missing from the system Pythons
