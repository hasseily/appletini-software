# iigs-doom: technical survey of everything except the renderer

I did not modify any files. All paths below are relative to this repo root:
`<upstream>`

- Git has one commit, 8ea2eac, tagged v1.0. The remote is github.com/Webifi/iigs-doom and the license is GPLv2 (`LICENSE`).
- Line numbers are from the files as they are now. Count methods are in §6.

## 0. What matters most for a 65C02 port
- **All hand-written 65816 assembly.** There is no C and no C library (`Makefile:11-12`). That is 81 files and 82,470 lines, of which about 58,700 are instruction lines. On top of that: 105 macros with 1,265 invocation lines, and an unrolled drawer file generated at build time (`tools/gendraw.py`).
- **At least 4 MB of RAM is required.** The loader refuses to run unless banks $02-$0D and $10-$3F are RAM (`src/iigs/loader.s:339-390`). Every bank from $00 to $3F has an assigned use (`src/iigs/memmap.inc`, `src/iigs/iigs.scm:1-27`).
- **16-bit registers are the default.** There are 8,151 16-bit immediates (`##`) against 1,090 8-bit ones (`#`). `sep #$10` appears only 13 times, so X and Y are effectively always 16-bit.
- **Pointers are 4-byte far pointers.**
  - Every pointer inside a game struct is 4 bytes (24-bit address plus a pad byte).
  - Far data is read through `[dp],y` (2,872 instruction operands) and `long:` (4,678).
  - Globals are 16-bit absolute addresses relative to the data bank register, which is set to $02 (`.near`, 9,106 operands).
- **No operating system.** There is no ProDOS MLI, GS/OS or Toolbox call anywhere (checked by grep). The only firmware used is:
  - the boot slot's ProDOS block driver and SmartPort entry;
  - the monitor ID routine at boot;
  - the TransWarp GS card firmware;
  - one read of the ROM version byte.

## 1. Boot and loading

### 1.1 Disk images (`tools/mkdisk.py`)
- **Floppies.** Each disk is an 800 KB ProDOS volume named `DOOM.DISKn`, 1600 blocks, stored as .po (`mkdisk.py:2-21, 60-61`). Layout:
  - Block 0: boot block.
  - Block 1: custom header starting "DOOMGS".
  - Blocks 2-5: volume directory. Block 6: bitmap.
  - `DOOM.BOOT`: index block 7, data blocks 8-13 (`LOADER_BLOCKS=6`, `mkdisk.py:66-68`; `STAGE2_COUNT=6`, `boot.s:11-13`).
  - `DOOM.DATAn`: contiguous from block 14.
  - `DOOM.SETTINGS`: one block, type $5A, disk 1 only.
  - `README`.
- **Header layout** (`loader.s:30-48`, `mkdisk.py:674-712`):
  - Offset 16: segments, 8 bytes each (24-bit address, flags, first block, block count). Flags are SEG_PIC=1 and SEG_B1=2. At most 44 segments (`mkdisk.py:78`).
  - Offset 368: store map, 8 runs.
  - Offset 432: build ID, a CRC32 over the loader and all payloads (`mkdisk.py:533-536`).
  - Offset 436: the settings block number.
  - Offset 438: the last disk holding resident data. Offset 439: the number of store banks.
  - Offset 448: the order of the title picture's blocks.
- **Hard disk and SCSI images.** `--hd` builds one volume holding everything plus 256 free blocks. `--scsi` wraps that volume in an Apple Partition Map, with the ProDOS partition at block 64 (`mkdisk.py:573-605`).
- **Load addresses** (`Makefile:172-183`):
  - Resident WAD at $10:0000; the pieces that spill into free table space are listed in a `.SEG` file.
  - Sound bank at $2C:0000; log table at $1F:0000; sine table at $20:0000.
  - Title picture at $2A:0000; INTRO song at $2A:8000.
  - Level store at $40:0000.
  - ELF entry point forced to $03:0000.
- **How data is split across disks.**
  - Title picture blocks go first on disk 1, in an interlaced order so the picture appears progressively (`mkdisk.py:117-123, 456-473`).
  - A compressed segment is never split across two disks. Store regions are pinned to a disk via the `.REG` file (`mkdisk.py:489-531`).
  - The level tools group maps (1,2,3), (4,5,6), (7,8,9) per level disk (`tools/levelimg.py:76`).

### 1.2 Stage 1: boot block (`src/iigs/boot.s`)
- The firmware loads block 0 to $0800 and jumps to $0801 in emulation mode, with X = slot×16 (`boot.s:3-9`).
- It sets carry and calls `JSR $FE1F` (ID routine). Carry clear means a IIgs. Otherwise it prints "DOOM NEEDS AN APPLE IIGS." with HOME ($FC58) and COUT ($FDED), then hangs (`boot.s:21-42`).
- The driver entry is $Cn00 plus the byte at $CnFF (`boot.s:44-56`). It issues 6 READ calls through zero-page $42-$47, loading blocks 8-13 to $6000, then `JMP $6000` with X = unit (`boot.s:58-82`).
- On error it writes "BOOT ERROR" straight into text page $0400 (`boot.s:84-90`).

### 1.3 Stage 2: loader (`src/iigs/loader.s`, runs at $00:6000)
Steps are documented at `loader.s:5-23`:
1. Computes the driver and SmartPort entries; SmartPort = driver + 3 (`152-168`).
2. Switches to native mode with 8-bit A and 16-bit X/Y (`175-177`).
3. Probes RAM by writing the bank number and its complement at $xx:8000, for banks $7F down to $02. Builds a 128-bit RAM bitmap (`339-419`).
4. Turns the super hi-res (SHR) screen on, black (`863-894`):
   - sets the linear bit of $C029 first, then zeroes $E1:2000-$9FFF with an overlapping MVN;
   - sets palette 15 and the scan-line control bytes (SCBs) of rows 191-199;
   - sets the border to black, then $C029 |= $C0.
5. For each disk: reads the header, checks "DOOMGS", the disk number and the build ID (`579-610`).
   - Reads each segment one block at a time into $7A00, then MVNs it to the 24-bit destination (`716-735`).
   - Compressed segments are staged at $30:0000 and decoded (`621-714`).
   - Title picture blocks are also copied to the screen with grey palettes (`737-839`).
6. The store (anything at or above $40:0000) is loaded only when those banks are RAM, i.e. 8 MB mode (`203-209, 421-444`).
7. Ejects a finished disk with SmartPort CONTROL code 4 (`553-560`). Waits for the next disk in either drive, polling SmartPort STATUS code 0 and pacing on the vertical-blank flag at $C019 (`562-574, 1155-1256`).
8. Writes a BOOTINFO block at $7E00 (`50-63, 283-327`). Then `rep #$30` and a JML to the entry point, patched into the instruction's operand bytes (`328-333`).
9. The settings block is loaded like any other segment, to $7C00 (`mkdisk.py:85, 698-702`).

### 1.4 How the program image is placed; compression
- **Program image.** The linker runs with `--hosted` (`Makefile:103-106`), so the loader writes initialized data straight to its final address. `crt0` then only zeroes the BSS entries of `data_init_table` (`crt0.s:1-6, 48-89`).
- **ELF parsing.** `mkdisk` reads the ELF's loadable segments using their physical addresses.
- **IRQ code relocation.** Code linked at $00:DC00-$DEFF is stored on disk for $00:BA00-$BCFF (`mkdisk.py:153-156`). `copyMusicIrq` moves it up once the language-card RAM is visible (`s_sound65.s:1410-1419`, `irq65.s:10-13, 449-454`).
- **B1 compression** (`tools/b1.py:1-24`; reference decoder `199-258`):
  - A ZX0-style LZ with interlaced Elias-gamma codes and 16-bit bit-buffer words.
  - Offsets up to 32768, matches of 2-256 bytes, no end marker.
  - The parse is optimal, and results are cached in a directory.
- **When the build compresses.** Each bank-sized chunk below the store is compressed only if that saves at least one block (`mkdisk.py:161-183`). Level-store units are always compressed (`tools/levelimg.py`).
- **The 65816 decoders** use MVN for both literal runs and matches, and patch MVN's bank operands in place (`loader.s:625-714`, `w_level65.s:1284-1397`).

### 1.5 Startup code and `main`
- **`crt0.s:33-46`:**
  - `sei`, `clc`/`xce` to native mode, `rep #$38` (16-bit registers, decimal mode off);
  - S = end of the stack section, D = $0900, data bank register = $02;
  - then `jsl main` (`92-94`).
- **`main`** (`i_iigs65.s:248-285`):
  1. $C036 bit 7 set (fast); $C035 = $3F (all video shadowing off).
  2. `bmAccelOff`: ZipGS AppleTalk delay off and TransWarp GS IRQ slowdown off (`m_menu65.s:2106-2140`).
  3. `I_InitSettings`: copies the settings block and BOOTINFO out of bank 0 (`m_config65.s:97-107`).
  4. Builds the multiply tables: quarter squares (512 KB), reciprocals, and a texture-step table.
  5. Draws a progress cell, then `jmp D_DoomMain`.
- **`D_DoomMain` init order** (`d_main65.s:136-204`): keyboard → DOC timer → start interrupts → sound → zone → defaults → WAD → second sound init → finale/intermission/menu/renderer init → `P_Init` (which calls `W_InitLevels`, `p_setup65.s:165`) → sound, HUD and status bar init → settings → graphics → title loop or timedemo.

### 1.6 Disk I/O while the game runs
All calls go through bank-0 wrappers that set D=0, switch to emulation mode, call the firmware and restore the game stack (`w_level65.s:1921-2020`; `m_config65.s:347-430`):
- `lvRead` and `IIGS_DiskBlock`: ProDOS block driver READ (1) and WRITE (2).
- `lvStatus` and `IIGS_DiskStatus`: SmartPort STATUS code 0.
- `lvDib`: SmartPort STATUS code 3; byte 21 of the device information block gives the device type (3.5" check).
- `lvEject`: SmartPort CONTROL code 4.

Before any disk I/O, `bmDiskOn` / `bmSave` stop the game interrupt, turn the ROM and I/O back on, restore the ROM vectors, and restore the owner's TransWarp GS configuration (`m_menu65.s:1792-1806`, `irq65.s:479-503`).

### 1.7 Native versus emulation mode
- The boot block runs in emulation mode throughout (6502 code plus one 65C02 `bra`).
- The loader runs native and drops to emulation for each firmware call (`loader.s:521-551`).
- The game is native all the time. Its only `xce` instructions are in the firmware wrappers: `crt0.s:36`, `m_config65.s:377/397/409`, `w_level65.s:1950/1981/1999`. The one `cli` is `irq65.s:475`.

## 2. Platform layer

### 2.1 Interrupts (`src/iigs/irq65.s`)
- **Enabled sources:** the ADB data interrupt, the ADB mouse interrupt, and the DOC alarm. The alarm (oscillator 30) runs only while music plays (`irq65.s:3-15`).
- **Disabled sources** (`irq65.s:427-440`):
  - $C041 = 0 (vertical-blank, quarter-second and Mega II mouse interrupts off);
  - $C023 = 0 and $C032 = 0 (VGC interrupts off, flags cleared);
  - $C047 read (clears VBL flags);
  - SCC write register 9 = 0 via $C039;
  - $C027 = $50 (ADB data and mouse interrupts on).
- **Vectors in RAM.** Setting $C035 bit 6 (I/O and language card off) leaves banks 0/1 $C000-$FFFF as plain RAM. The native vectors at $00:FFE0 are then written in RAM (`irq65.s:442-467`):
  - IRQ ($FFEE) → `irqEntry` at $00:DDxx;
  - BRK, COP, ABORT and NMI → a bare `RTI`.
- **Handler** (`irq65.s:69-90`): pushes 8-bit A only; uses long addressing so D and the data bank don't matter.
  - If an ADB byte is waiting it calls `IIGS_PollKeys`.
  - Otherwise it acknowledges the DOC by reading register $E0, then runs a music "wake" with the data bank = $27 (`irq65.s:100-159`).

### 2.2 Keyboard and mouse
- **Keyboard.** The game does not use the $C000 keyboard register (`iigs_asm.s:66-74`, `i_iigs65.s:1-8`). It talks to the ADB microcontroller directly:
  - Setup sends $04 (set modes) with mode $01 so the controller stops auto-polling the keyboard, then $52 to enable keyboard service requests (`iigs_asm.s:352-378`).
  - When the keyboard requests service, the game sends $C2 (Talk register 0 of address 2) and reads two raw key bytes into a 32-byte ring (`iigs_asm.s:96-151, 259-307`).
  - Ports used: $C026 (data/command), $C027 (status).
  - Control-Reset is emulated with ADB command $10 (`iigs_asm.s:397-403`). On exit, command $05 restores normal polling.
- **Mouse.** $C024 gives signed 7-bit deltas plus two buttons; the buttons are mapped to fake key codes $7E (fire) and $70 (strafe) (`iigs_asm.s:183-257`).
- **Joystick / paddles:** none (checked by grep).
- **Mapping to Doom keys.** `I_StartTic` turns the ring into Doom key events through a 128-entry `keyTable`: low byte = Doom key, high byte = menu character. The table can be rebound and is saved in the settings file. Menu auto-repeat is done in software (`i_iigs65.s:98-237, 673-1000`).

### 2.3 Timing
- **There is no VBL interrupt.** `I_GetTime` reads DOC oscillator 31's data register ($7F) through the sound GLU. That oscillator is silent and free-running over a 256-byte ramp in DOC page $FF, at frequency 87, giving 34.94 steps per second; the routine counts steps into a 32-bit value (`i_doc65.s:1-32, 55-155`).
- **Alarm.** Oscillator 30 is a one-shot on the same ramp with its interrupt enabled; the music stream re-arms it at song tempo (`irq65.s:112-138`).
- **Vertical blank** is only ever polled ($C019): in the loader, during disk prompts, and in `titleWipe` (`w_level65.s:1420-1448, 1873-1880`).
- **Frame pacing.** Tics come from the DOC clock. At most MAXTICS tic commands are queued (default 4), so a frame slower than 4 tics slows the game itself (`d_main65.s:320-370`, `tics.inc:14-26`, `Makefile:17-22`).

### 2.4 Sound: Ensoniq DOC
- **Registers:** GLU at $C03C-$C03F. All 32 oscillators are enabled (register $E1 = 62), giving a 26,320 Hz scan rate (`i_doc65.s:26, 83-85`).
- **Oscillator allocation:**
  - 0-15: sound effects, 8 stereo channels (each a left/right one-shot pair);
  - 16-29: music, 14 voices;
  - 30: alarm; 31: timer (`i_doc65.s:5-12`; `s_sound65.s:1-13, 28-44`; `music.inc:54`).
- **Sound effects:**
  - Decoded once from a losslessly compressed bank at $2C:0000 into $27:B000-$29:DFFF (`i_snd65.s`; `s_sound65.s:1074ff`).
  - At each map start, a per-map plan of which sounds live where is uploaded to DOC RAM with `IIGS_DocUpload`; the rest share a pool with eviction (`s_sound65.s:1-13`).
  - Distance and pan follow the Chocolate Doom rules.
- **Music:** the build converts songs offline into DOC wavetables plus a stream of register writes (`data/music/*.mus`, `tools/music/MUSIC_FORMAT.md`). The interrupt plays the stream from bank $27 (`irq65.s:100-406`).

### 2.5 Video: the parts of `i_viigs65.s` that are not rendering
- Screen memory: pixels $E1:2000, SCBs $E1:9D00, palettes $E1:9E00. The back buffer is at $01:2000-$9CFF (`i_viigs65.s:21-30`).
- Init clears the buffers, sets the border and $C029 |= $C0. Shutdown clears $C029 bit 7 (`256-301`).
- Only marked dirty rows are copied from the back buffer to the screen, with MVN from $01 to $E1 (`408-498`).
- Also here: palettes and tints with gamma, SCB management, the loader progress bar (`192-248`), and the 40-column text console and `printf` in bank $E0 used by `I_Error` (`i_iigs65.s:340-670`).
- The renderer toggles $C035 bit 3 every frame so that its writes to bank $01 are shadowed to $E1 (`r_frame65.s:118-121`, `r_list65.s:551-580`, `am_map65.s:1105-1171`).

### 2.6 Accelerator support
- **ZipGS** (`iigs_asm.s:418-461`; `m_menu65.s:2264-2330`):
  - Unlock by writing $5A four times to $C05A, lock with $A5.
  - $C059 holds settings; the AppleTalk-delay bit (bit 5) is cleared while the game runs.
  - $C05B gives the cache size; $C05C is used to detect a ZipGS.
  - A write to $C05F follows each ADB command, as a workaround for a delay MAME inserts.
- **TransWarp GS** firmware in bank $BC (`m_menu65.s:1641-1645, 2099-2176`), called by JSL with D=$0A00:
  - "TWGS" signature at $BC:FF00;
  - $BCFF34 disables the IRQ slowdown; $BCFF3C / $BCFF40 get and set the configuration; $BCFF44 returns the cache size.
- **ROM version** byte read at $FF:FB59 (`m_menu65.s:1646, 2276`).
- **Cache-driven layout.** Code and data placement is tuned to the accelerator's 32 KB direct-mapped cache (slot = address & $7FFF) (`iigs.scm:78-109`). There are 118 `.space` padding lines whose comments say they preserve layout. None of this matters on other hardware.

### 2.7 Every hardware address used

| Address | Use | Where |
|---|---|---|
| $C00C, $C00E | 40 columns, primary character set (error screen) | `loader.s:506-507`; `i_iigs65.s:36-37, 353-354` |
| $C019 | vertical-blank flag, polled | `loader.s:132, 1252-1256`; `w_level65.s:66, 1430, 1874-1880` |
| $C023, $C032, $C041, $C047 | interrupt enables/clears, all set off | `irq65.s:28-33, 435-438` |
| $C024 | mouse data | `iigs_asm.s:10, 193-198` |
| $C026, $C027 | ADB command/data; status and interrupt enables | `iigs_asm.s:11-12`; `irq65.s:24-27, 71, 439-440, 488` |
| $C029 | new-video register: SHR on / linear / text | `loader.s:130, 501-503, 863-893`; `i_iigs65.s:30, 346-349`; `i_viigs65.s:21, 290-299` |
| $C034 | border colour (low nibble; high nibble preserved) | `loader.s:888-890`; `i_iigs65.s:355-357`; `i_viigs65.s:287-289` |
| $C035 | shadow register: $3F at start; bit 3 per frame; bit 6 while running | `i_iigs65.s:252-253`; `irq65.s:449-451, 499-501`; renderer lines listed in §2.5 |
| $C036 | speed register, bit 7 = fast | `i_iigs65.s:249-251` |
| $C039 | SCC channel A command (interrupts off) | `irq65.s:430-434` |
| $C03C-$C03F | sound GLU (DOC access) | `i_doc65.s:21-24`; `irq65.s:34-37`; `s_sound65.s:1482-1485`; `m_menu65.s:2418-2428` |
| $C051, $C054 | text mode, page 1 | `loader.s:504-505`; `i_iigs65.s:34-35` |
| $C059-$C05C, $C05F | ZipGS registers / MAME workaround | as in §2.6 |
| $E0:0400 (and $E0:0554) | text page (console; loader prompt line) | `i_iigs65.s:38`; `w_level65.s:54, 1851-1871` |
| $E1:2000 / $9D00 / $9E00 | SHR pixels, SCBs, palettes | as in §2.5 |
| $00:FFE0-$FFFF | 65816 vectors, in RAM | `irq65.s:50-55` |
| $Cn00+($CnFF), +3 | ProDOS block driver, SmartPort | §1.2, §1.6 |

- **DOC internal registers used:** $00-$1F frequency low; $20-$3F frequency high; $40-$5F volume; $60-$7F data; $80-$9F wavetable pointer; $A0-$BF control; $C0-$DF table size; $E0 interrupt status; $E1 oscillator enable.
- **Not used:** $C068 (state register) and $C02D, both checked by grep. $C02E appears only in a comment (`m_menu65.s:2333`).

### 2.8 IIgs features the game depends on
- 65816 native mode, 24-bit addressing, MVN, and at least 4 MB of RAM.
- SHR 320×200 with per-row palettes, plus fast bank $01 shadowed to $E1.
- $C035 bit 6 to get RAM vectors and bank-0 RAM at $D000 and above.
- Raw ADB keyboard and mouse access.
- The DOC with 64 KB of its own RAM, used for sound, music and as the only clock.
- Fast mode, and ZipGS / TransWarp GS specifics.
- Slot ProDOS and SmartPort firmware, 3.5" drive eject and disk-switch status, two-drive swapping.
- The text page in bank $E0 for error messages.

## 3. Calling conventions and code style
- **Models.** Built with `--code-model=large --data-model=medium` (`Makefile:24`).
  - The Calypsi guide describes the Medium data model as one 64 KB bank (not bank 00) for static data, with 24-bit default pointers and 16-bit near pointers. That guide is in the scratchpad's Calypsi download, not in the repo.
  - Here the near bank is $02: initialized data at $02:0000-$7AFF, BSS at $02:7B00-$FFFF (`iigs.scm:87-90`). Other uninitialized far data is in bank $0D (`iigs.scm:81-86`).
- **Calls and returns.**
  - Between modules: `jsl long:X` / `rtl` (1,120 / 694).
  - Inside a bank: `jsr .kbank X` / `rts` (2,243 / 1,169).
  - Tail calls: `jmp long:` (189). Long branches: `brl` (534).
  - Function pointers (thinker functions, state actions, traversal callbacks) go through a hand-assembled `JML [dp]` (`.byte $DC`) at 8 sites: `p_tick65.s:58-61, 533`, `p_pspr65.s:118`, `p_path65.s:816`, `p_map65.s:2786, 2869`, `patch65.s:381`, `r_sprite65.s:398, 1787`.
  - Jump tables: `jmp (abs,x)` 18 times, `jsr (abs,x)` 14 times (e.g. `irq65.s:148`, `i_snd65.s:166`).
- **Arguments** follow the Calypsi "normal" convention (Calypsi guide §20.3.2):
  - First argument in C (16-bit A), or X:C for 32 bits (X is the high word).
  - Further arguments in the pseudo-registers `_Dp[0-7]`, with far pointers as 4 bytes.
  - Anything more on the stack at `4,s`; the caller cleans up.
  - Results in C or X:C.
  - The caller may lose A, X, Y and `_Dp[0-7]`. This port also preserves `_Dp[8-19]`, where Calypsi's default is `[8-15]` (`crt0.s:18-22`).
  - Examples: `P_SpawnMobj` (`p_spawn65.s:73-77`), `W_GetLumpByNum` (`w_wad65.s:255-275`), `IIGS_CopyHuge` (`iigs_asm.s:465-471`).
  - Monster code saves its actor in `_Dp+8` using `PEI` (`actor.inc:7-28`).
- **Register widths.** 16-bit A and X/Y by default (`crt0.s:37`). Short 8-bit-A windows use `sep #$20` 512 times and `rep #$20` 497 times. Of all 58,691 instruction lines, 1,107 are REP/SEP.
- **Direct page** is $0900 and holds `_Dp` (20 bytes) plus variables in the `ztiny` section.
  - `dp:.tiny` appears 7,900 times; indirect long `[.tiny p],y` 2,872 times.
  - D is moved temporarily: to $0000 for slot firmware, to $0A00 for TransWarp calls and the wall loop, to $8D00 for the B1 decoder (`w_level65.s:85, 1296`).
  - Game tics reuse the column drawers' direct-page slots (`p_tick65.s:8-10`).
- **Data bank register** is $02 (`crt0.s:42-46`).
  - Code that changes it restores it (PHB/PLB 275 times).
  - `P_RunThinkers` deliberately sets it to each thinker's bank and walks fields with `abs,X` (`p_tick65.s:106-227`).
  - MVN leaves it set to the destination bank, so code restores it afterwards.
- **Stack** is $0B00-$3FFF, 13.5 KB (`iigs.scm:32-33, 228`).
  - Each game tic runs on its own stack starting at $1B6F (`p_think65.s:177-197, 293-301`).
  - There are 316 stack-relative `n,s` operands. Stack frames are built with TSC/SBC/TCS.
  - At least one routine discards its caller's frame to return two levels up (`m_menu65.s:2439-2457`).
- **Struct layouts** (`src/iigs/offsets.inc`). Every pointer is 4 bytes, little-endian: offset (16 bits), bank, pad.

| Struct | Size | Notable fields | Lines |
|---|---|---|---|
| seg_t | 18 | vertex x,y stored inline as int16; front/back sector as bytes | 72-81 |
| side_t | 14 | | 83-90 |
| line_t | 36 | | 92-106 |
| sector_t | 58 | 32-bit fixed-point heights; 5 far pointers | 108-127 |
| mobj_t | 120 | thinker 12 bytes; 32-bit x/y/z/momentum/flags; far pointers for sector and block links, subsector, target, lastenemy; movedir and threshold are bytes | 135-171 |
| state_t | 12, padded to 16 | far `action` pointer, 16-bit next-state index | 213-219; `info.inc:4-5` |
| mobjinfo_t | 51, padded to 64 | | 221-244 |
| player_t | 155 | | 246-282 |
| node_t | 28 | int16 fields | 192-199 |
| subsector | 8 | | 201-205 |

  - The pad byte of `thinker.function` (byte 11 of a mobj) is reused as a cached thinker-kind flag (`p_tick65.s:106-117`).
  - `mobj->state` holds a near address in its low word (`p_tick65.s:427`).
  - Lumps and zone blocks never cross a 64 KB bank, so pointer arithmetic can stay 16-bit (`p_map65.s:15`; `wadtool.py:76-80`).
- **Self-modifying and generated code:**
  - MVN bank operands patched (`loader.s:625-632`, `w_level65.s:1287-1294`, `iigs_asm.s:514-518`);
  - the JML target in the loader (`loader.s:328-333`);
  - a benchmark hook patched into the frame code (`m_menu65.s:2197-2251`);
  - HUD text compiled into code at run time (`patch65.s:279-381`);
  - the generated drawers patch an RTS into place (`gendraw.py`, header).

## 4. Memory management

### 4.1 Memory map (`iigs.scm:1-27`, `memmap.inc`)

| Bank(s) | Contents |
|---|---|
| $00 | direct page $0900; stack $0B00-$3FFF; hot game code $4000-$5FFF; loader $6000; disk code and level-loader variables $8000-$8FFF; IRQ/music code at $DC00 (plus state at $BD00) |
| $01 | back buffer, fuzz tables, status bar cache |
| $02 | near data |
| $03-$05 | code (level loader at $05:DC00) |
| $06-$09 | zone (heap) |
| $0A-$0C | sight/path/sound-flood tables, respawn copy of the level (memmap.inc:19-41) |
| $0D | far BSS, colormaps |
| $10-$12 | resident WAD |
| $13-$1A | quarter-square multiply tables, 512 KB |
| $1B-$1C | texture-step table |
| $1D | column records / scratch |
| $1E | reciprocal table |
| $1F | log table |
| $20 | sine table |
| $21 | per-map sight/move tables |
| $22-$26 | sprite/automap/menu tables |
| $27-$29 | current song, decoded sound samples |
| $2A-$3F | level window (22 banks) |
| $0E-$0F, $40-$69 | extra window banks when present |
| $40+ | level store (8 MB mode) |
| $6A | all songs (8 MB only) |

### 4.2 Zone (`src/iigs/z_zone65.s`)
- A Doom-style heap over banks $06-$09: 262,096 bytes (`z_zone65.s:1-33`).
- 16-byte block headers with 16-bit "segment" links (address >> 4, so it only reaches the first 1 MB).
- A static block at the top of each bank stops any block from crossing a bank.
- Tags STATIC=1, LEVEL=2, LEVSPEC=3, CACHE=4. `Z_Free` ignores pointers above bank $09, i.e. lumps used in place (`240-263`).

### 4.3 Resident WAD (`src/iigs/w_wad65.s`)
- Sits at $10:0000. The directory is used in place; a lump address is $10:0000 + filepos, with no copying and no cache (`w_wad65.s:1-10, 62-67, 262-275`).
- Name lookup through 256 hash chains, up to 1,536 lumps.
- The converted WAD stores 16-bit lump sizes, merges identical lumps and places lumps so none crosses a bank (`wadtool.py:76-127`).

### 4.4 Level window and level store (`w_level65.s`, `tools/levelimg.py`, `tools/levelset.py`)
- **Sets.** 1-9 are maps, 10 the title, 11 intermission and finale pictures (`w_level65.s:73-78, 268-270`).
- **What a map set contains** (`levelset.py:1-18`): its map lumps, a subsector grid (SGRIDn), colour lumps (GSVIEWn, GSFLATn), its wall patches (plus switch alternates, slime frames and the sky), and every sprite any possible thing in the map uses.
- **Store format** (`levelimg.py:29-55`):
  - "DOOMST" header, 12-byte set records, 10-byte entries (lump / compressed unit / fill);
  - units are B1-compressed, at most 47 KB each, never crossing a bank;
  - the rest of each bank is zero-filled.
- **Loading a set:**
  - Old lumps are pointed at a placeholder; units are decoded into window banks; directory entries are patched.
  - Common units load once.
  - Title and intermission pictures stay resident when there are at least 32 window banks (`w_level65.s:271-495, 822-1002`).
- **8 MB versus 4 MB.**
  - With 8 MB, loads are memory copies with `IIGS_CopyHuge` (MVN).
  - With 4 MB the game reads floppies at each map start (`1496-1623`):
    - store blocks map to a disk and block through the header's store map;
    - reads are batched into a 48 KB scratch area (`1173-1266`);
    - disk prompts, changed-disk detection (checksum plus the SmartPort "switched" bit) and 3 retries are in `725-819, 1644-1840`.
  - A 4 MB machine booting from floppies plays no title demos (`619-620`).

### 4.5 Converted formats (`tools/wadtool.py:214-387`; `p_setup65.s:29-44`)

| Lump | Converted form |
|---|---|
| THINGS | 8 bytes; multiplayer and deathmatch things dropped |
| LINEDEFS | 15 bytes, vertex coordinates inline; flags, special and tag each a byte |
| SIDEDEFS | 7 bytes, texture and sector numbers as bytes; deduplicated |
| SEGS | 18 bytes, identical to the in-memory seg_t |
| SSECTORS | 1 byte each |
| SECTORS | 12 bytes, flats as numbers into the map's flat list |
| BLOCKMAP | rebuilt with shared list tails |
| VERTEXES | removed |

- Because sector and texture numbers are bytes, a map is limited to 256 sectors and 256 textures.
- **Graphics:**
  - walls and sprites stay as full-resolution Doom patches;
  - flats are removed, since floors are drawn as flat colours (`wadtool.py:493-498`);
  - STBAR becomes raw 320×32;
  - full-screen pictures become 36,864-byte SHR images (`i_viigs65.s:59-62`);
  - various lumps are removed (`wadtool.py:468-499`).

### 4.6 Sizes
- One map needs about 23 window banks, roughly 1.5 MB, including texture columns built at load time. E1M3 needs 22.97 banks, or 23.48 with the extra textures (`w_level65.s:521-532`).
- Raw map lumps in `DOOM1.WAD` (I computed these read-only): 55.7 KB (E1M1) to 152 KB (E1M6). Sprites total 826 KB, wall patches 764 KB, flats 221 KB.
- Converted and compressed sizes only exist after a build; `wadtool` prints them (`wadtool.py:826-834`).
- In memory: lines, sides, sectors, subsectors and a pool of one 120-byte mobj per map thing (at most 512) go in the zone. Segs, nodes, blockmap and reject are used in place (`p_setup65.s:1-7, 216-231`; `p_spawn65.s:29-32`).

### 4.7 What is loaded when
- **Boot:** everything below the store, plus the store itself in 8 MB mode.
- **Startup:** the multiply and reciprocal tables are computed, not loaded. Sounds are decoded.
- **Each map:** `W_LoadSet` from `P_SetupLevel` (`p_setup65.s:103`).
- **On demand:** picture sets.

## 5. Game logic: how complete
- **Content:** episode 1 only, maps E1M1-E1M9 (`levelset.py`; `BUILD.md` "Other WADs").
- **Tables** are cut down to what episode 1 uses (`offsets.inc:1016-1018`): 314 states (vanilla 967), 50 thing types (137), 55 sprites (138), 53 sounds (109).
  - Monsters: zombieman, shotgun guy, imp, demon, spectre, baron, plus barrels (`offsets.inc:501-553`).
  - Weapons: fist, chainsaw, pistol, shotgun, chaingun, rocket launcher. The plasma and BFG constants exist but have no action routines.
- **Menus:** new game (skill select), options, load and save (8 slots), key binding, mouse settings, display and sound (view size, gamma, volumes), benchmark, save settings (`m_menu65.s`). There is no episode menu and no Read This screen. Quit shows a text screen and hangs (`i_iigs65.s:297-305`).
- **Other screens:**
  - Automap: full-screen and rotating overlay mode, with zoom, pan and follow; no marks and no grid found (`am_map65.s:3-11`).
  - Full status bar with face; HUD message line and map title.
  - Intermission and E1 finale (text, then HELP2).
  - Cheats `m_cheat65.s:33-47`: iddqd, idkfa, idfa, idspispopd, idchoppers, idbehold*, idclev, idend, plus two custom ones, idrocket and idrate.
- **Saved games** are level-start snapshots only, as in the GBA/Doom8088 ports: skill, map, times, weapons and ammo, kept in `DOOM.SETTINGS` (`g_game65.s:887-1080`; `m_config65.s:1-16`).
- **Demos:**
  - Playback only, no recording. The title loop plays demo3; demo1 and demo2 are kept only in timedemo builds (`wadtool.py:468-492`; `w_level65.s:639-665`).
  - The stock DEMO2 tic stream is replaced by `data/demo2.hex`, with a hash check on the original (`wadtool.py:735-746`). I assume this is because the stock demo doesn't replay correctly; the code does not say why.
- **Simplifications:**
  - `TICSTEP=N` (default 1, which is exact Doom) runs monsters and the world once every N tics (`tics.inc:1-12`).
  - `MAXTICS` (default 4) makes the game run slower when frames are slow (§2.3).
  - `FixedApproxDiv` gives a reciprocal-based divide with 16 significant bits, used for slopes in attacks and doors (`r_iigs65.s:547-560`, `m_recip65.s:1-10`).
  - Sight side-tests use only the integer parts of coordinates (`p_sight65.s:5-6`).
  - Single player only; a fixed thing pool; floors and ceilings drawn in flat colours.
  - Most other file headers say "with the same results" as the Doom8088 C code.

## 6. Statistics and assembler syntax

### Size by subsystem

| Group | Lines | Instruction lines |
|---|---:|---:|
| boot + loader + crt0 | 1,814 | 1,121 |
| platform (i_iigs, iigs_asm, irq, i_doc, i_snd, s_sound, m_config) | 5,792 | 3,920 |
| i_viigs65 | 2,403 | 1,946 |
| zone / WAD / level | 3,214 | 2,402 |
| p_* + info + includes | 28,953 | 20,889 |
| flow and UI (d_main, g_game, m_menu, m_cheat, st, hu, wi, f, am) | 11,265 | 8,405 |
| math and runtime | 2,416 | 1,313 |
| renderer | 26,613 | 18,695 |
| **Total** | **82,470** | **58,691** |

### 65816-only constructs

| Group | REP/SEP | JSL | JSR | `long:` | `[dp]` | `,s` | `##` imm | `.near` | PHB/PLB | XBA | MVN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| boot | 55 | 1 | 81 | 20 | 9 | 2 | 91 | 0 | 6 | 4 | 5 |
| platform | 127 | 89 | 174 | 648 | 44 | 3 | 496 | 545 | 18 | 13 | 4 |
| i_viigs | 54 | 55 | 87 | 189 | 25 | 17 | 312 | 444 | 2 | 15 | 1 |
| memory | 29 | 43 | 140 | 490 | 122 | 27 | 441 | 167 | 10 | 10 | 3 |
| play | 246 | 456 | 918 | 842 | 1,729 | 155 | 3,498 | 4,124 | 122 | 91 | 0 |
| flow/UI | 103 | 274 | 485 | 707 | 133 | 13 | 1,537 | 2,183 | 23 | 8 | 4 |
| math | 12 | 6 | 10 | 51 | 69 | 79 | 134 | 6 | 10 | 6 | 0 |
| renderer | 481 | 196 | 348 | 1,731 | 741 | 20 | 1,642 | 1,637 | 84 | 473 | 16 |
| **Total** | **1,107** | **1,120** | **2,243** | **4,678** | **2,872** | **316** | **8,151** | **9,106** | **275** | **620** | **33** |

- Other whole-codebase totals: PEI 151, PEA 29, PHD/PLD 34, TCD 23, TSC/TCS 54, TXY/TYX 122, BRL 534, `jmp long:` 189.
- MVN is never written as a mnemonic; it is always `.byte $54,…` (33 sites). MVP is never used.
- 65C02 instructions also used: STZ 606, BRA 905, PHX/PHY/PLX/PLY 387.
- How I counted: source instruction lines per file with an awk pass, comments stripped. Macro bodies count once, not per expansion, and the generated drawer file isn't included.

### Calypsi syntax and ca65 equivalents
- **Directives:**
  - `.section name, text|bss|data|rodata[, root|noroot, noreorder, noinit]` → ca65 `.segment` plus an ld65 config. Linker scripts are Scheme (`*.scm`) with fixed-address placement.
  - `.public` / `.extern` → `.export` / `.import`.
  - `X .equ v` → `X = v`.
  - `.space n` → `.res n`.
  - `.byte`, `.word`, `.long` (32-bit) → `.byte`, `.word`, `.dword`.
  - `.ascii`, `.asciz` → `.byte "…"`, `.asciiz`.
  - `.rtmodel` → drop. `.require` → `.forceimport`.
- **Addressing prefixes:**
  - `dp:`, `abs:`, `long:` → `z:`, `a:`, `f:`.
  - `.tiny X` is relative to the direct-page base; `.near X` is relative to the near-bank base $02:0000; `.kbank X` is a same-bank 16-bit JSR/JMP target with a check.
  - `.byte0/1/2`, `.word0/2` → `<`, `>`, `^`, `.loword`, `.hiword`.
  - `.sectionStart/End/Size` → ld65-defined symbols.
- **Immediates.** `#` is always 8-bit and `##` always 16-bit; the assembler does not track the M/X flags. With ca65 you would need explicit `.a8/.a16/.i8/.i16`.
- **Labels and macros.** Local labels `N$` reset at each non-local label (roughly ca65 `@N`). Macros are `NAME .macro a,b … \a … .endm` (105 macros).
- **Preprocessor.** Full C preprocessor: 152 `#include`, 127 `#if`, 126 `#define`, 93 `#undef`. `r_seg65.s` stamps out variants of `segvar.inc`/`segclip.inc` with `#define`/`#undef` (174 lines).
- **Dependency outside the repo.** `cal_integer.s` is a copy of Calypsi's own `integer.s`. Its licence permits use only with the Calypsi toolchain (`cal_integer.s:3-10`), and it includes `macros.h` from the Calypsi install. That header only maps `libcode` to `farcode` and adds `.rtmodel` lines.

## 7. Build tooling
**Needed by `make`** (Python 3, standard library only):

| Tool | Makefile line | Purpose |
|---|---:|---|
| `gendraw.py` | 96 | generates the unrolled column drawers |
| `loadfont.py` | 116 | loader font and disk icon |
| `gentables.py` | 124 | reciprocal/phase/log tables; only `log.bin` goes on disk |
| `gensine.py` | 128 | 64 KB sine/cosine table |
| `gsview.py` (+ `doomview.py`) | 133 | per-map colour selection, about 60 s |
| `wadtool.py` (+ `gscolor.py`, `sgrid.py`, `levelset.py`, `levelimg.py`, `b1.py`, `levelhot.txt`) | 137/141 | converted WAD, level store, picture and region files |
| `sndbank.py` | 146 | sound bank |
| `packunits.py` (+ `musbank.py`, which imports `dmxmus`, `mussamp`, `musdsp`, `oplchip`, `oplsynth`, `opleg`) | 163 | packs the song units |
| `songunits.py` | 166 | extracts per-song units |
| `mkdisk.py` (+ `b1.py`) | 172 | disk images |

**Development and profiling only:** `elfsyms.py`, `symaddr.py`, `pchist.py`, `profile.py`, `stackprof.py`, `slotmap.py`, `ticcmp.py`, `preview.py`, `shrpng.py`, `probe.lua`/`.sh`, `phases.sh`, `regress*.sh`, `watch.sh` (all MAME harness scripts). `optable.py` is referenced by nothing. `tools/music/*` is an optional SoundFont song converter (`tools/music/README.md`).

Tool sizes: about 8,464 lines on the build path, 1,205 lines of dev scripts, 4,440 lines in the music converter.

**Binaries:**
- Git contains no built binaries. The only binary files tracked are `data/DOOM1.WAD`, `data/demo2.hex`, `data/music/*.mus` and two PNGs.
- The release disk images are on GitHub, not in the repo: `gh release view v1.0` lists `disk1-4.po`, `doom-hd.hdv`, `HD60_512_DOOM.hda` and `SHA256SUMS`.
- The Calypsi toolchain (version 5.18, `BUILD.md:7-9`) is gitignored (`.gitignore:13-15`).
- Note: during my session the working tree gained two gitignored, non-repo items, both timestamped 18:21 by some other process: a `tools/calypsi` symlink into a scratchpad Calypsi install, and a partial `build/` directory. `build/obj` was empty.

## 8. Inconsistencies and uncertainties
- **Loader size.** Comments say the loader occupies blocks 8-19 (`boot.s:7`, `mkdisk.py:10-11`, `loader.s:1`). The code reads 6 blocks, 8-13, a 3 KB limit (`mkdisk.py:381-382`), while `loader.scm` allows $6000-$77FF.
- **Stale comments:**
  - `wadtool.py:31` (`WAD_SPACE`) contradicts the resident WAD address $10:0000.
  - `m_recip65.s:363` says the texture-step table is in banks $7E/$7F; it is at $1B:0000.
- **Referenced files that are not in the repo:** `TECHNICAL.md`, `tools/offsets.py`, `tools/musref.py`, `tests/zipbench.lua`, `research_notes/`, `CLAUDE.md`.
- **Inferred, not stated in code:**
  - which map group ends up on which floppy;
  - why DEMO2 is replaced;
  - the Calypsi data-model semantics, which I took from the Calypsi guide rather than the repo.
- **Stale provenance comments.** Several comments still talk about "C code" (e.g. `p_map65.s:12-14`, `p_inter65.s:6-7`), left over from the original C → assembly conversion.

## Key absolute paths
- `<upstream>/src/iigs/` — `boot.s`, `loader.s`, `crt0.s`, `iigs.scm`, `memmap.inc`, `offsets.inc`, `i_iigs65.s`, `iigs_asm.s`, `irq65.s`, `i_doc65.s`, `s_sound65.s`, `z_zone65.s`, `w_wad65.s`, `w_level65.s`, `p_tick65.s`, `m_menu65.s`, `m_config65.s`
- `<upstream>/tools/` — `mkdisk.py`, `b1.py`, `wadtool.py`, `levelimg.py`, `levelset.py`
- `<upstream>/Makefile`