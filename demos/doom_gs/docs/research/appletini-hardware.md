## Appletini technical report for the Doom port (read-only research)

**Path legend:** `[A1]` = `<appletini-one>/`, `[SW]` = `<appletini-software>/`. Citations are `file:line`.

**Checkouts examined:**
- appletini-one is on branch `codex/memory-copy-fill-api`, HEAD `6335a98` (F1.1.4).
- appletini-software is on branch `claude/iigs-doom-port`, HEAD `d69eb58a`.

---

### 1. CPU

**It is a soft core in the FPGA, and only while the virtual TransWarp (vTW) is on.**
- The card is a Zynq-7020: fabric (PL) plus two ARM cores (`[A1]README.md:3-6`). The A9 cores run services and the renderer, and Apple software cannot program them directly (`[A1]README_VIDEO_MONO.md:91`).
- With vTW on, the card asserts /DMA and the motherboard 65C02 "sleeps" (`[A1]README_VIRTUAL_TRANSWARP.md:109`). A fabric W65C02S core runs the program out of on-chip RAM (BRAM):
  - core file: `[A1]hdl/apple/w65c02_core.sv:2-3`
  - instantiated at `[A1]hdl/apple/vtw_core_top.sv:354-387`
  - listed in `[A1]hdl/hdl_sources.txt:30-38`
- With vTW off, the Apple's own motherboard CPU runs at native 1 MHz.
- The vTW always presents an Enhanced //e with an embedded Enhanced //e ROM (`[A1]README_VIRTUAL_TRANSWARP.md:10-17`).
- A fallback that would run the 65C02 as an interpreter on the ARM is only a de-risk plan; it is not implemented (`[A1]README_VIRTUAL_TRANSWARP.md:379-382`).

**No 65816 support of any kind.**
- The core implements the full W65C02S map: CMOS ops, RMB/SMB, BBR/BBS, WAI, STP, and the reserved NOPs (`[A1]README_W65C02_CORE.md:3-6`).
- Opcodes that mean something else on a 65816 decode as NOPs or as W65C02S ops:
  - `$E2`/`$C2` (SEP/REP) are 2-byte NOPs (`w65c02_core.sv:529,495`).
  - `$FB` (XCE) and `$EB` (XBA) are 1-cycle NOPs (`:555,538`).
  - `$5C` (JML) and `$DC`/`$FC` are 3-byte NOPs (`:386,522,556`).
  - `$x7` is RMB/SMB and `$xF` is BBR/BBS (`:296,304`).
- Registers are 8-bit and the address bus is 16-bit (`:14-56`).
- A search of hdl, ps_sources and the READMEs for "65816|65c816|XCE" returned no hits.

**Clock speeds.** The fabric clock is 133.333 MHz. Presets (`[A1]ps_sources/frontend/vtw_service.c:96-106`; `[A1]README_VIRTUAL_TRANSWARP.md:60-66`):

| Preset | How it is made |
|---|---|
| 1 MHz | Cycle-locked to Apple PHI0 |
| 2.6 MHz | Divider 51 |
| 3.6 MHz | Divider 37 |
| 7 MHz | Divider 19 |
| 13 MHz | Divider 10 |
| 26 MHz | Divider 5 |
| 33 MHz ("FULL") | One core cycle per 4 fabric clocks (`vtw_core_top.sv:18`) |
| 0.05 MHz "slug" | Debug key only (`vtw_service.c:86-87`) |
| TURBO | Speed mode 3 (`vtw_core_top.sv:70,1029-1032`) |

- TURBO "has no fixed MHz rating" (`[A1]README_TURBO.md:20-21`).
- The only benchmark is a simulated 16-byte copy loop, 2.28–2.44 times faster than 33 MHz (`README_TURBO.md:25-36`).
- TURBO is opt-in and off by default (`README_TURBO.md:3-11`; `[A1]ps_sources/frontend/config_menu.c:72`).
- vTW itself defaults off and can only be switched on or off in BOOT mode (`config_menu.c:67`; `[A1]ps_sources/frontend/config_menu_help.c:496-497`).
- Software can write `$C074`: 0 = selected speed, 1 = 1 MHz, 3 = off until reset (`README_VIRTUAL_TRANSWARP.md:115`). Doom writes 0 (`[SW]demos/doom/src/kernel/loader.s:128`).

**What TURBO does:**
- **CPU shortcuts.** It retires implied/accumulator ops at fetch, folds indexing, and drops dummy cycles outside I/O. Stack, decimal, IRQ, WAI and STP keep their semantics. TURBO permission is sampled per instruction at fetch (`README_TURBO.md:71-79`).
- **Caches** (`vtw_turbo_cache.sv`; `vtw_core_top.sv:1132`):
  - a 64-entry page table (32 read and 32 write mappings, 256-byte pages)
  - a 128-byte word cache
  - A hit takes 2 fabric clocks (`README_TURBO.md:46-58`).
- **What stays out of the caches.** Only BRAM-backed pages outside `$C000-$CFFF` are cached. PSRAM (RamWorks) responses are never cached (`README_TURBO.md:49,69`).
- **Cache invalidation.** Any change to the full mapping state invalidates both caches. That includes RAMRD, RAMWRT, ALTZP, 80STORE, PAGE2, HIRES, language card and RamWorks bank (`vtw_core_top.sv:1160-1169`; `README_TURBO.md:64-68`).
- **Cycle-counted code.** It is not preserved (`README_TURBO.md:156-160`).

**How TURBO sends video writes to the display:**
- Each video write goes straight into the renderer's capture stream at fabric speed, with lossless backpressure (`README_TURBO.md:100-104`; `apple_cycle_capture.sv:293-301`).
- A separate "latest-value" mirror copies the bytes to motherboard RAM through the physical bus at one byte per idle Apple cycle (`vtw_video_coalescer.sv:2-6`; `vtw_bus_engine.sv:20-21`).
- Hidden text/lores and MAIN HGR pages can stay pending. AUX graphics, SHR and paged MAIN SHR are always mirrored immediately:
  - `README_TURBO.md:106-114`
  - `vtw_video_policy.sv:28-31`: "AUX graphics also hold SHR pixels ... keep the whole extended range immediate."
- **Key point (RTL):** while those immediate-mirror bytes are pending, the CPU stalls on its next `$Cxxx` access until they have reached the motherboard:
  - `video_barrier = ... || (video_active_pending_q && (core_addr[15:12] == 4'hC))` (`vtw_core_top.sv:1368-1369`)
  - the flag clears only when the pending pages are drained and the posted queue is idle (`:1412-1425`)
  - the stall state is `X_VIDEO_WAIT` (`:1841-1854`)
- **Exposure accesses** force a full flush of the deferred banks as well (`vtw_core_top.sv:1344-1355`):
  - `$C080-$CFFF` (language card, slot I/O, slot ROMs)
  - `$C05x`
  - writes to `$C000/1`, `$C00C-F`, `$C022`, `$C029`, `$C034`, `$C035`, `$C071`, `$C073`

**What else slows the CPU:**
- **Every `$C000-$CFFF` access** is a real bus cycle synced to PHI0: "0–1 µs sync + 1 µs cycle" (`README_VIRTUAL_TRANSWARP.md:110,185`). Exceptions:
  - `$C011-$C01F` reads are answered internally (`vtw_core_top.sv:560-569`).
  - Slot-7 SmartPort ROM, `$C800` space and FIFO are served inside the fabric (`README_VIRTUAL_TRANSWARP.md:306-325`).
  - Virtual Disk II even reads (`README_VIRTUAL_TRANSWARP.md:326-341`).
- **Slot 4 (Phasor).** When the virtual Phasor is enabled, slot 4 is always slowed to 1 MHz for 512 Apple cycles by default, re-triggered on each access (`config_menu.c:75,4336-4356`). Doom deferred a VIA-based clock for this reason (`[SW]demos/doom/docs/STATUS.md:453`).
- **Optional slowdown regions**, all off by default (`vtw_core_top.sv:78-85,1059-1106`; `config_menu.c:74`):
  - floating-bus/speaker/video `$C030-$C05F` plus `$C019`
  - paddles
  - per-slot `$C0n0` / `$Cn00`
- **Disk II.** Native accesses and Q7 write mode force 1 MHz (`vtw_core_top.sv:1108-1115`).
- **RamWorks cache misses** (section 2).
- **Armed LINTXT overlay.** It disables TURBO's fast-write path (`vtw_core_top.sv:1195-1200`).
- **AD8088.** It cannot run together with vTW (`[A1]README_AD8088.md:16-20`).

---

### 2. Memory

**Physical memory:**
- **On-chip RAM (BRAM) shadow, 144 KB:** main 64K, base aux 64K, ROM 16K (`[A1]hdl/apple/vtw_shadow.sv:9-21`). Both language cards are folded into their 64K. This is the fast memory.
- **PSRAM, 16 MB** (2 chips; `[A1]AGENTS.md:21`): holds aux and RamWorks.
- **DDR3L, 1 GB:** ARM-only (`AGENTS.md:20`).

**RamWorks:**
- 8 MB = 128 × 64K banks, counting base aux (`soft_switch_manager.sv:63-68,135-140`; `[SW]demos/doom/docs/DESIGN.md:10`).
- The bank is selected by a write to `$C071` or `$C073` with data bit 7 = 0 (`soft_switch_manager.sv:141-144`).
  - Values above 127 are ignored.
  - The switch is write-only (`DESIGN.md:82-84`).
  - It only works when RamWorks is enabled in the RAM tab (`vtw_core_top.sv:107-113`).
- Physical bank = `$C073` value + 1 (`[A1]hdl/globals.sv:251`). Bank 0 is main.
- ALTZP routes `$0000-$01FF` and `$D000-$FFFF` to the selected bank. So **every bank has its own zero page, stack and full language card**; LC bank-1 `$Dxxx` is stored at offset `$Cxxx` of the same bank (`globals.sv:257-262,271-276`).
- RAMRD and RAMWRT route `$0200-$BFFF`. With 80STORE, PAGE2 steers the display windows (`globals.sv:263-268`).

**Fast versus slow:**
- **Fast:** main (with main LC) and base aux (`$C073=0`, with aux LC and ZP/stack) are BRAM (`vtw_shadow.sv:47-56`).
- **Slower:** RamWorks banks `$C073` = 1..127 are PSRAM behind one 8-byte write-allocate line cache (`vtw_core_top.sv:994-1006`). Misses go through a PSRAM admission window that allows one operation per Apple bus cycle (`[A1]hdl/apple/psram_simple.sv:28-33,232-239`).
- Doom's hardware data shows a gain of about 40% when its control code moved from bank 100 to base aux (`STATUS.md:156-181`).
- **Slowest:** anything on the motherboard bus (`$Cxxx`, and the video mirror).

---

### 3. Video (SHR on a //e)

**How SHR is turned on:**
- It is "fake SHR": the ARM renderer draws from a captured copy of the AUX memory it has seen written.
- `$C029` with bits 7:6 = 11 turns it on (`apple_cycle_capture.sv:140-171`; `apple_cycle_renderer.c:419-421`). Doom writes `$C1` (`[SW]demos/doom/src/kernel/video.s:81-82`) and `$01` to turn it off.
- `$C029` bit 5 forces black and white (`apple_cycle_renderer.c:423-445`).
- `$C029` is honored only on a //e or II+ host, or in ONE//e standalone mode (`[A1]hdl/apple/apple_top.sv:995`).

**Memory layout:**
- Everything lives in base AUX (`$C073=0`), `$2000-$9FFF` (`vtw_bus_engine.sv:42-47`):
  - pixels at `$2000 + 160*y`
  - SCBs at `$9D00`
  - an Appletini control area at `$9DF8-$9DFF`
  - 16 palettes at `$9E00`
- The display always reads fixed physical bank 1 (`soft_switch_manager.sv:71-72`).
- SCB bits 7 (640 mode) and 5 (fill) are supported (`apple_cycle_renderer.c:2039-2074`).
- `$C022` and `$C034` are captured. `$C035` is stored but never used (`apple_cycle_renderer.c:2872-2907`).

**Extensions**, compatible with SuperDuperDisplay (SDD):
- **SHR4.** Magic `D3 C8 D2 B4` at `$9DFC`. The high nibble of each palette entry's second byte selects a per-pixel submode (`apple_cycle_renderer.c:1395-1407,1944-1981`):
  - 0: standard
  - 1: RGGB Bayer
  - 2: PAL256, 8 bits per pixel, 320×100, 256-entry RGB444 palette at `$9E00` (`:1883-1909`)
  - 3: R4G4B4 direct color (`:1860-1881`)
- **SHR-3200 (Brooks).** Magic `'3200'`. `$9DF9` = palette bank, `$9DFA/B` = palette base (`:1911-1926,2016-2035`).
- **`$9DF8` paging** works only with SHR4 or 3200 magic (`:2178-2197`). It needs main `$2000-$9FFF` mirrored (`vtw_core_top.sv:514-519`).
  - 1 = interlace: the second field is in MAIN `$2000-$9FFF`. PAL256 interlace gives **320×200 at 8 bpp**, with AUX holding rows 0–99 and MAIN rows 100–199 (`:2122-2133`).
  - 2 = page flip, blended 50/50 below 120 Hz output (`:2134-2147,2222-2243`).

**Not found:** hardware blit, scanline IRQ, application-controlled double buffering, or an 8 bpp mode beyond PAL256.

**Frame publication:** a new frame is built from the captured copy at Apple line 0. A frame is torn if SHR writes are in progress as line 0 passes (`apple_cycle_renderer.c:246-251,3026-3058`; `[SW]demos/doom/docs/DESIGN.md:70-73`).

---

### 4. ARM memory API ("AMEM")

**Requirements and transport:**
- Needs F1.1.4 with its rebuilt FPGA image (F1.1.2 introduced the API), an active vTW at any speed, and RamWorks for extended banks (`[A1]README_MEMORY_API.md:3-22`).
- Called as SmartPort unit 0, selector `$80` (`README_MEMORY_API.md:26-42`; `[A1]ps_sources/frontend/smartport_service.c:1216-1218,1744-1764`):
  - STATUS returns a 32-byte capability block including "AMEM" (`README_MEMORY_API.md:75-99`), with an ARM microsecond counter at offset 16.
  - CONTROL takes an "AMEM" header plus 1–16 descriptors of 16 bytes each (`README_MEMORY_API.md:107-145`).
- The raw `$CFF0`/`$CFF1`/`$CFF2` FIFO transport avoids the ROM's write to `$07F8` (`README_MEMORY_API.md:66-73,273-308`). Doom uses it (`[SW]demos/doom/src/kernel/amem.s:37-71`).

**Operations and limits:**
- Operations are COPY, FILL and the PRIVATE flag.
- Endpoints must be in `$0200` up to (not including) `$C000`.
- Banks: MAIN 0, AUX 0, AUX 1–126. Bank 127 is excluded (`README_MEMORY_API.md:147-169`).
- Overlapping COPY is rejected.
- MAIN and base-AUX destinations need PRIVATE, which sends **no renderer records and no motherboard writes**. So it cannot update the visible SHR screen (`README_MEMORY_API.md:171-188`; `memory_api_hw.c:345-353`).
- Errors `$60`–`$69`. A failure mid-batch is not atomic, so never retry (`README_MEMORY_API.md:212-231`).

**How it works and what it costs:**
- One CPU hold covers the whole list.
- BRAM is read by the ARM 4 bytes at a time through MMIO with polling (`memory_api_hw.c:176-218`).
- PSRAM goes through DMA in 504-byte chunks (`memory_api_hw.c:149-174`).
- Timeouts: 10 ms per transfer, 100 ms to get the hold (`memory_api_hw.c:17-18`).
- Long holds merge VBL IRQs (`README_MEMORY_API.md:233-237`).
- The user saw no significant speedup (`README_MEMORY_API.md:18-19`). Doom v11 and v12 both measure 4.03 FPS (`STATUS.md:315-433`).

**Other services Apple software can use:**
- **Mouse card, slot 2** (default off): registers at `$C0n0-F`. Mode bit 3 gives a VBL IRQ; write 3 to `$C0nF` to acknowledge; status bit 3 is the VBL cause (`mouse_card.sv:34-57,172-181,447-450`).
- **`$C019` VBL flag:** synthesized, "generally one cycle early" (`README_VIRTUAL_TRANSWARP.md:19-25`).
- **SmartPort, slot 7:** GETDIB returns "Appletini SP". Under vTW, reads go straight into the BRAM shadow (`smartport_service.c:1661-1693`).
- **Phasor/Mockingboard, slot 4:** 2 or 4 AY chips, dual SSI-263 speech (`mockingboard.sv:2-10`). **No Ensoniq DOC** (no matches in the source).
- **SuperSprite, slot 7:** TMS9918A VDP overlay plus AY. It disables SmartPort (`[SW]examples/detect_appletini/README.md:67`).
- **LINTXT text overlay** at `$C0F0` (`[A1]docs/linear_ram_text_overlay_interface_v1.0.html`). It can also serve as an extra capture window (`[SW]demos/fatdog_magic/README.md:22-27`).
- **Slot 1:** Uthernet II and an SSC wired to a virtual ImageWriter printer.
- **No-slot clock.**
- **Slot 5:** Z80 Appli-Card, or AD8088 (incompatible with vTW).

**Not found:** multiply/divide helpers, a blitter, DMA registers visible to the 65C02, a general-purpose timer, or a serial console for the 65C02 (the UART console belongs to the ARM).

---

### 5. IIgs

- The card works in IIgs physical slot 7 for the boot menu and SmartPort only.
- "Logical slots 1-6, memory replacement, RamWorks, vTW, AD8088, PS host-memory operations and fake-SHR C029 writes remain blocked" (`[A1]README_IIGS_SAFETY.md:66-71`).
- vTW lists IIgs support as a non-goal and refuses a IIgs (`README_VIRTUAL_TRANSWARP.md:109,374`).
- The Doom docs contain no IIgs material.

---

### 6. Firmware versions

| Version | What changed | Source |
|---|---|---|
| F1.1.0 | TURBO became opt-in | commit `85f17ad` |
| F1.1.1 | 33 MHz label; last git tag | commit `03a107b`; origin/main is `b9fcdef` |
| F1.1.2 | Memory API added (not in F1.1.1) | commits `d87c8c4`, `86b9922` |
| F1.1.3 | Timer-conversion fix | `README_MEMORY_API.md:13-16` |
| F1.1.4 | DMA completion is kept until the next command; needs the new bitstream | `6335a98`; `[A1]ps_sources/image_versions.h:11-12`; `README_MEMORY_API.md:7-11` |

F1.1.2–F1.1.4 exist only on the `codex/memory-copy-fill-api` branch.

---

### Where documents disagree or are stale

1. `README_W65C02_CORE.md:8-9` says the core is "not yet instantiated". The manifest and `vtw_core_top` show it is.
2. `README_TURBO.md:18` says the current firmware is F1.1.2. The code says F1.1.4.
3. `README.md:89-91` says the memory API uses "the existing F1.1.1 hardware image". `README_MEMORY_API.md` says it needs F1.1.4.
4. F1.1.3 is never a version string in the repo. The timer fix commit `de67420` did not bump the version.
5. `README_VIRTUAL_TRANSWARP.md:147-150` gives the shadow as "~172 KB"; it is actually 144 KB (`:37`; `vtw_shadow.sv`).
6. `README_VIRTUAL_TRANSWARP.md:66-68` says acceleration "always has 8MB (lives in the shadow)". RamWorks is actually in PSRAM and depends on the RAM tab setting.
7. `vtw_shadow.sv:11,55` still says RamWorks banks use "bus cycles". This is stale.
8. On bank 127:
   - `psram_simple.sv:35-37` says bank 127 is not served.
   - `psram_simple.sv:123-125` and `soft_switch_manager.sv:145-146` serve it.
   - Doom uses bank 127 (`DESIGN.md:198`).
   - The memory API excludes it.
9. `vtw_core_top.sv:93-95` refers to a Disk II motor input, but that input is unused.
10. `main.c:183` says RamWorks "Defaults OFF". `config_menu.c:98,3939-3940` default it on.
11. Framing of TURBO video writes. The software docs say "TURBO batches video writes, don't model 1 MHz" (`[SW]AGENTS.md:3-5`; `DESIGN.md:46-48`). That is true per write. But the RTL stalls the next `$Cxxx` access until the AUX/SHR mirror has drained at about one byte per Apple cycle. The Bosconian docs state that floor outright (`[SW]demos/appletini_bosconian/docs/DESIGN.md:46-61`).
    - **My inference, not measured:** Doom's 26,880-byte blit means about 26 ms before `sta RAMWRTOFF` completes (`video.s:242`). That is consistent with the v11 "blit" share of 9.76% of about 248 ms (`STATUS.md:326-345`).
12. `README_TURBO.md:125-128` says pending video costs "one fabric wait state". That understates the drain stall described in item 11.
