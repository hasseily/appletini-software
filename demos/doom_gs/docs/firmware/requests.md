# Further firmware requests from the DOOM port (not yet designed)


Written 2026-09-30 and checked against the F1.2.1 source by a second pass; the same text is the section "Further requests (not yet designed)" of the design document "vTW Memory Fast Path: Design".

The IIgs DOOM port work produced nine firmware requests. Changes 0 to 8 do not specify any of them. Two were open questions of change 8 (R2 and R8), and change 3 covers most of R5. None of them has a specification or a review yet, so each subsection gives only its evidence and the points a design would have to settle.

| # | Request | Problem | Who it helps | Size (estimate) | Priority |
|---|---|---|---|---|---|
| R1 | The coalescer scans only dirty bytes | A page drain scans all 256 bytes, at least 513 fabric clocks. Scattered SHR bytes drain about 4 times slower than the bus. | Software that writes sparse bytes in TURBO. The DOOM port only while change 3 is off. | 64-128 LUTs of distributed RAM or one BRAM18, plus 30-50 LUTs | Medium. High if change 3 slips. |
| R2 | Mask the stale IRQ sample | On a //e or II+, a TURBO `RTI` takes the interrupt again after a virtual card releases it | Every virtual card acknowledged in TURBO. It also lets change 8 widen. | 1-2 FFs, 2-4 LUTs | High |
| R3 | Memory API: check liveness per chunk, batch the reads | 6 AXI accesses per 4 bytes written to fast memory, 12 per 4 bytes read | The existing port (+10.5% frames a second in a2vm), the DOOM port's code loads | About 50-100 lines of PS code. Optional 10-20 LUTs. | High |
| R4 | Memory API writes that reach the display | Every main and base-aux destination needs PRIVATE, which emits no capture | Programs that present finished frames from an off-screen buffer | A few hundred lines of PS code on both cores. Optional 20-40 LUTs. | Low |
| R5 | A hold without the mirror drain | The hold drains the mirror and the RamWorks line before granting | Change 3 covers the SHR case. A small remainder is left. | Nothing beyond change 3 | Low |
| R6 | Key state for the USB keyboard | The //e reports only the last key and "any key down" | Keyboard-only players of action games | 100-200 lines of PS code. Optionally 32 FFs, 20 LUTs. | Low |
| R7 | A microsecond counter the 6502 can read | No time counter can be read without a SmartPort exchange | Profiling on the card for both ports, and firmware measurement | About 60 FFs, 30-50 LUTs | Medium |
| R8 | FW-S2: window presets 16, 32 and 64 | The menu cannot select the Doom profile's window, and stepping from it loses it | The DOOM port and other Phasor users | A few lines of PS code, one test change | Medium |
| R9 | Hardening: `$C073` bit 7, bank 127, the language card in the API | Bank values with no defined meaning. The API cannot write the language card. | All RamWorks software, and the DOOM port's code loads | From documentation up to about 100 lines of PS code | Low to medium |

Each claim carries a mark: (V) read at the cited file:line, (S) simulated, (M) measured on the card or in a2vm, (A) assumed. Firmware paths are in `<appletini-one>` F1.2.1. Paths under `docs/`, `src/` and `tools/` are in the IIgs DOOM port. All sizes are estimates, not synthesis results (A).

### R1. The coalescer scans only dirty bytes

**Problem.**
- In TURBO, every write to aux `$2000-$9FFF` enters the coalescer as an active byte (V `apple_top.sv:2189`, `vtw_core_top.sv:1352-1353`, `vtw_video_policy.sv:31`).
- The scanner steps through the page indexes one a clock (V `vtw_video_coalescer.sv:119-128`). For each dirty page it then fetches and checks all 256 bytes at 2 clocks a byte, dirty or not (V `:129-149`).
- A page therefore costs at least 513 fabric clocks, 3.9 Apple cycles, however few of its bytes are dirty (V).
- A column of the 3D view leaves about 1.6 dirty bytes a page: 168 bytes on 105 pages (V `docs/results/fuzz-timing-2026-09-30.md:29`, `:177`). After a 168-row column's writes, the wait for its drain took 41,854 clocks on the RTL (S). a2vm, which drains one byte an Apple cycle, predicted 9,690 (M, `fuzz-timing-2026-09-30.md:30-31`, `:165`).
- Any `$Cxxx` access waits while active bytes are pending (V `vtw_core_top.sv:1414-1415`). The replay's `RDAUX` and `RDMAIN` writes around each fuzz record each waited for one such drain (V `fuzz-timing-2026-09-30.md:32-36`).
- On the card, demo-10 and demo-11 took 48.1 and 49.3 ms, against a2vm's 34.3 and 35.1 (M). Modelling the scan explains 85-88% of the difference (M, a2vm patched model, checked against the RTL: `fuzz-timing-2026-09-30.md:233-245`).

**Who it helps.**
- The DOOM port already works around it. Drawing the fuzz records after each strip took demo-10 from 48.1 to 36.2 ms on the card (M, `docs/results/replay-card-2026-09-30.md:54`).
- With that workaround in place, R1 would save about 0.4 ms on demo-10 (M, a2vm: 33.27 ms with the scan modelled, against 32.87 ms without it, `fuzz-timing-2026-09-30.md:102`, `:101`).
- The existing port gains nothing. Its E1M1 frame is 248.6 ms with and without the scan (M, a2vm, `fuzz-timing-2026-09-30.md:222`, `:297`).
- Other software that writes scattered bytes in TURBO and then touches `$Cxxx` would gain, for example sprite drawing (A).

**How it interacts with change 3.**
- Change 3 sends SHR writes down the inactive path, so `$Cxxx` accesses no longer wait for them (V `docs/firmware/lazy-mirror-review.md:20`, `:72`). The fast-path replay times do not change when the scan is modelled (M, a2vm, `fuzz-timing-2026-09-30.md:300`).
- The scan still runs at every lazy flush. A full frame's pages are dense, so the scan costs little there (A).
- A `$C073` write after a few scattered SHR bytes still flushes them (V `lazy-mirror-review.md:87`), and that flush runs through the same page scan (V `vtw_video_coalescer.sv:45-48`). It still pays 513 clocks for each dirty page.
- R1 still matters where writes stay active: the displayed text and hi-res pages (V `vtw_video_policy.sv:36-40`), armed overlays, II+ hosts, and SHR with `lazy_en` off (ONE//e until tested, `lazy-mirror-review.md:32`).
- Both changes edit `vtw_video_coalescer.sv`, and change 3 adds `lazy_mask_en` to the flush-mode `select_page` (V `lazy-mirror-review.md:72`). Build them in one stage with one bench, or build R1 after change 3.

**Size and risk.**
- A summary of dirty 32-byte or 16-byte blocks is 4,096 or 8,192 bits. That is 64-128 LUTs of distributed RAM, or one BRAM18 (A).
- The scan control adds 30-50 LUTs (A).
- With 16-byte blocks, a column's page would cost about 50-70 clocks. That is below one Apple cycle, so the bus would set the rate (A).
- Timing risk is medium on the scan path (A). Change 3 also puts logic beside `next_page_q` (`lazy-mirror-review.md:72`).

**Priority.** Medium. It becomes high if change 3 is deferred, because every TURBO SHR program then pays this cost.

**A design would have to settle:**
- The block size, and whether the summary uses BRAM. The baseline already uses 110 of 140 BRAM tiles (V `docs/firmware/cache-plan.md:101`).
- How a write sets a block bit without losing the scanner's clear. Today a page's bit clears when the scanner selects it, and a write during the scan sets it again (V `vtw_video_coalescer.sv:100-110`). The block bits need the same rule.
- Whether to replace the 512-step page walk. Once bytes are cheap, one index a clock can add up to 512 clocks a pass (A).
- An alternative design: a bounded list of dirty addresses that falls back to the full scan when it overflows (A).
- Bank flushes (`flush_valid`) run through the same scan (V `vtw_video_coalescer.sv:45-48`), so they must skip clean blocks too.

### R2. Mask the stale IRQ sample after a virtual card releases its IRQ

**Problem.**
- The core's interrupt input is `core_irq_n = ab_read.irq & ~irq_assert_in` (V `vtw_core_top.sv:356-359`).
- On a //e or II+, `ab_read.irq` is the physical line, sampled once per Apple cycle at the data snap. A low must be seen on two snaps in a row (V `apple_bus_wrapper.sv:657-676`).
- A virtual card's acknowledge drops `irq_assert_in` at the data strobe. The old low sample remains until the next snap, up to one Apple cycle (V `docs/firmware/fws1-review.md:46-48`).
- A TURBO `RTI` finishes inside that cycle and takes the same interrupt again (S, `fws1-review.md:49`, `:53-57`).
- A handler that acknowledges with `STA IFR` got 20 entries for 10 interrupts, with no slowdown at all (S, `fws1-review.md:76-78`).
- For the Phasor, the slot-4 window hides this today: the handler's tail runs at 1 MHz, and F1.2.1 counts 10 entries for 10 interrupts (S, `fws1-review.md:50`, `:53-57`).
- ONE//e is not affected, because it presents a live IRQ level (V `apple_virtual_bus.sv:84`, `:129`).
- This was question 31 of change 8. Here it becomes a request of its own.

**Who it helps.**
- Mockingboard and Phasor software that acknowledges with `STA IFR` counts its ticks twice whenever the window is off (S at mask 0).
- Programs using mouse-card or SSC interrupts in TURBO (A: not simulated for those cards).
- Change 8: with the mask in place, IFR and IER writes could join the exempt set (`fws1-review.md:83`).
- The DOOM port is not affected. Its VBL handler reads the mouse status before the acknowledge and counts only VBL causes (V `src/sound/irq.s:32-37`), so a spurious entry would cost time, not correctness (A: not simulated for the mouse card, `fws1-review.md:79`).

**Size and risk.** 1-2 flip-flops and 2-4 LUTs, all driven from flops (A). The risk is functional, not timing: the change sits on every card's interrupt path.

**Priority.** High. It fixes a correctness bug in existing software for a few LUTs.

**A design would have to settle:**
- How long the mask lasts: from the fall of `irq_assert_in` to the first data snap after the release (`fws1-review.md:83`).
- The open-collector line rises through a pull-up. Check that the next snap, about 1 µs later, sees it high (A).
- A physical card that holds the shared line low during the mask is seen up to one cycle later. The two-snap filter already adds one cycle of latency (V `apple_bus_wrapper.sv:669-676`).
- How the mask interacts with the II+ re-arm notch, `irq_rearm_release_q` (V `apple_bus_wrapper.sv:498-502`).
- Tests. The review's `tb_fws1_irq` bench is a scratch bench in neither repository (V `fws1-review.md:5-7`), so it has to be added. On the card, an `STA IFR` handler at mask 0 must count 10 entries for 10 interrupts.

### R3. Memory API: check liveness once per chunk, batch the reads

**Problem.**
- `hw_held` costs 4 AXI reads: the hold register plus the three status registers read by `hw_session` (V `memory_api_hw.c:70-92`).
- Each packed write word calls `hw_held`, reads `DATA4_STATUS` and writes `DATA4`: 6 accesses per 4 bytes (V `:254-272`).
- Each read word costs 12 accesses: a ready poll (5), a `READ4` write, a busy poll (5) and a `READ4_DATA` read (V `:187-215`).
- The shadow port drains a word from its two-word queue in a few fabric clocks. The built port is wide, so an aligned word takes one write (V `vtw_shadow_host_port.sv:56`, `:64-73`; `apple_top.sv:2100`).
- One AXI access takes about 0.135 µs, 18 fabric clocks (A: fitted to the existing port's card frame time, not measured; `tools/a2vm/costs/appletini.json`, `axi_us`).
- The check on every word is deliberate: the code checks ownership before every packed submission (V `memory_api_hw.c:256-257`).

**Throughput in MB/s** (M, the a2vm cost model at `axi_us` 0.135, `tools/a2vm/cost.c:1009-1062`, steady state per 504-byte chunk):

| Transfer | F1.2.1 | Liveness per chunk, PS only | Plus a fabric read port, no write poll |
|---|---:|---:|---:|
| Write to fast memory | 4.9 | 14.1 | 26.9 |
| Read from fast memory | 2.5 | 9.7 | 28.3 |
| PSRAM to main (load) | 3.0 | 5.0 | 6.0 |
| Main to PSRAM (save) | 1.9 | 4.3 | 6.1 |
| Main to main | 1.6 | 5.8 | 13.8 |

- "PS only" costs 2 accesses per write word and 3 per read word, with the liveness checks once per 504-byte chunk.
- The last column costs one access per word in each direction. For reads it needs a `READ4_DATA` read that also fetches the next word. For writes it drops the ready poll, which is an open point below (A).
- With either change, the PSRAM DMA becomes the larger part of a load or save. It moves one 8-byte line an Apple cycle, about 8.1 MB/s (V `psram_simple.sv:437`; arithmetic): about 62 µs of each 504-byte chunk, against 36 µs of shadow writes with PS only (M, model).
- Change 2 raises that limit only if its relaxed admission also applies to PS DMA (A).

**Effect on the existing port** (M, a2vm, E1M1 standing still, 20 frames):

| Profile | Frame ms | Copy phases ms | Frames a second |
|---|---:|---:|---:|
| F1.2.1 | 248.6 | 47.0 | 4.02 |
| F1.2.1, liveness per chunk | 225.0 | 24.0 | 4.44 |
| F1.2.1, plus a fabric read port, no write poll | 219.2 | 18.6 | 4.56 |
| Fast-path profile | 188.6 | 63.6 | 5.30 |
| Fast-path profile, liveness per chunk | 165.6 | 40.5 | 6.04 |

- The port moves 120,192 bytes a frame in three requests, half saves and half loads (V `docs/research/native-memory.md:89-91`; M, a2vm counters).
- The fast-path rows' copy phases include one lazy flush a frame, 27.3 ms. The port selects bank 122 with `$C073` before its exchange, and that flush comes from change 7's reconciler, not from the API (M, `tools/a2vm/README.md:796-803`).
- `axi_us` was fitted to this very frame, and the gain scales with it (A). Milestone 0 measures it.

**Who it helps.**
- The existing port gains 10.5% more frames a second from PS code alone (M, a2vm).
- The DOOM port's per-frame code loads. On F1.2.1 one 24 KB window is reloaded every frame (V `native-memory.md:34`). A 24 KB load from PSRAM falls from about 8.2 to 4.9 ms (M, model).
- After R3, the API would beat the CPU's PSRAM-to-main copy, which costs 0.246 µs a byte (M, model, `native-memory.md:33`). The API would cost about 0.20 µs a byte.

**Size and risk.**
- PS only: about 50-100 lines in `memory_api_hw.c`, with no bitstream change (A).
- Between checks, up to one chunk (504 bytes) could land after an Apple reset releases the hold (V `vtw_core_top.sv:1834-1843`). The shadow port has no hold input, so nothing in the fabric stops those writes (V `vtw_shadow_host_port.sv:10-42`). The program that restarts may already own that memory.
- The fabric could close that gap. It would refuse packed words unless the hold is granted, and report a sticky refusal (A: 5-10 LUTs).
- The auto-fetching read port adds about 5-10 LUTs (A).

**Priority.** High. It is the cheapest large gain available to the existing port.

**A design would have to settle:**
- The liveness rule: once per chunk, once per request behind the fabric gate, or an abort line the PS takes as an interrupt.
- One status word that holds every live bit. `hw_held` would then cost a single read even where checks stay (A).
- Whether a write word can skip the ready poll. The queue drains in a clock or two, faster than AXI writes arrive (A). The accepted count at the end of each chunk would prove it (V `memory_api_hw.c:220-231`, `:273`).
- The host test `scripts/test_memory_api_hw.py` and its fake MMIO.

### R4. Memory API writes that reach the display

**Problem.**
- Every main and base-aux destination needs PRIVATE (V `memory_api_hw.c:345-353`). PRIVATE emits no renderer capture and no motherboard replay (V `README_MEMORY_API.md:171-187`).
- Version 1 has no flag for copies to visible video (V `README_MEMORY_API.md:186-187`), so a program cannot use DMA to write the displayed SHR screen.
- The renderer's SHR copy is `g_aux_bank`. CPU1 updates it only from capture records (V `apple_cycle_egress.c:273-287`; the only other write is the clear at `:86`).

**What it needs.**
- A descriptor flag, say VISIBLE, that is accepted only for destinations in the SHR range of base aux (A).
- The renderer side. CPU0 hands the written range to CPU1. CPU1 applies it after the records written before the hold, then sets `s_shr_cache_invalidate` (A; the flag is V `apple_cycle_renderer.c:254`).
- The motherboard side. Under change 3, the bytes would enter the coalescer as lazy bytes. That needs a write port into the coalescer, used while the core is held (A: 20-40 LUTs).
- Without change 3, the only way to the motherboard is one bus cycle a byte, about 32 ms a screen (A: arithmetic, 32,768 bytes × 131 clocks, `docs/firmware/lazy-mirror-spec.md:58`).

**What it costs.**
- Copying 32,000 bytes from PSRAM takes about 10.7 ms today and 6.4 ms after R3 (M, model).
- The CPU does the same copy at about 0.246 µs a byte from PSRAM, about 7.9 ms (M, model, `native-memory.md:33`). Change 3 does not change the 6 fabric clocks of each SHR write cycle (V `lazy-mirror-spec.md:186`), and it may be bound by CPU1's record rate (A, `lazy-mirror-spec.md:193-196`). So R4 is at best slightly faster than the CPU, not a large speed gain.
- A hold whose destination lies in the SHR range first flushes the pending lazy bytes, up to 32 ms (V `lazy-mirror-review.md:22`, `:87`; A for the time). Entering the new bytes as lazy bytes would avoid that flush (A).

**Who it helps.**
- Programs that draw off screen and present whole frames without tearing (A).
- The existing port's blit doubles every pixel, so a plain copy cannot replace it (V `docs/research/existing-port.md:40-50`).
- The DOOM port draws in place and has no use for R4 today.

**Size and risk.** A few hundred lines of PS code across both cores, plus the optional coalescer port (A). The risks are ordering against capture records, and tearing if a block is applied mid-frame.

**Priority.** Low. Reconsider it once R3 and change 3 are in.

**A design would have to settle:**
- When CPU1 applies the block: at once, or at the next frame edge.
- Main SHR ranges in the paged modes set by `$9DF8`.
- Whether the motherboard copy may stay stale until SHR is left, as change 3's software contract already allows.

### R5. The hold's mirror drain

**Problem.**
- `hw_begin` raises the flush request before any transfer (V `memory_api_hw.c:127`).
- The hold is granted only after the mirror is idle, because `rw_flush_unsafe` includes `video_mirror_pending` (V `vtw_core_top.sv:1604-1611`). The flush request also forces a full flush of the deferred bytes (V `:1408-1410`).
- The dirty RamWorks line is then written back and invalidated (V `:1804-1824`). The flush request also clears both TURBO caches (V `:1206-1207`).

**What change 3 covers.**
- With KEEP_LAZY, SHR bytes survive a hold whose destinations avoid base aux `$2000-$9FFF`, and main `$2000-$9FFF` too in the paged SHR modes (V `lazy-mirror-review.md:20`, `:22`, `:72`).
- The other exposure accesses, `$C7xx` and the rest of `$C080-$CFFF` included, no longer flush them either (V `lazy-mirror-spec.md:13`, `:74`).
- The DOOM port stores to mirrored memory only in SHR, so for it change 3 covers the whole request (A, from the memory map in `docs/NATIVE.md:198-206`).

**What remains.**
- Active bytes still drain before the grant: the displayed text and hi-res pages, and SHR with `lazy_en` off. The deferred bytes of hidden pages still flush too (V `vtw_core_top.sv:1408-1410`).
- The bus is idle during a hold. When no destination is mirrored, that drain could overlap the ARM's work (A: gain not modelled).
- The line write-back is one PSRAM write, at most about one Apple cycle (A). It does not justify a request.
- `cache-review.md` finding 3 already proposes skipping the cache invalidate on shadow-only calls, as a refinement for change 6 (V `docs/firmware/cache-review.md:13`).
- The existing port's one lazy flush a frame under the fast path (27.3 ms in a2vm) does not come from the hold. It comes from its `$C073` selection before the exchange. It is fixed in the port or by a slot-7 exemption in change 7 (M, `tools/a2vm/README.md:796-803`).

**Priority.** Low. Record R5 as covered by change 3, and reopen it only if change 3 is dropped.

### R6. Key state for the USB keyboard

**Problem.**
- The //e reports the last key at `$C000` and "any key down" in bit 7 of `$C010`. A game cannot see two keys held at once (V `docs/research/existing-port.md:297`).
- A program can combine one key with Open Apple and Closed Apple (`$C061`, `$C062`) and with the mouse (V `existing-port.md:297-301`). The existing port reads the mouse X axis (V `existing-port.md:299`).
- On a //e or II+ host, USB keys never reach the Apple. The input service feeds them only to the ONE//e bridge (V `onee_input_service.c:1`, `:669-674`).
- On those hosts, vTW receives only USB joystick input (V `vtw_core_top.sv:592-603`).
- The PS already tracks up to 8 held keys and the modifier byte for each keyboard (V `onee_input_service.c:15`, `:735-766`; `usb_hid_service.c:1068-1107`).
- The //e's own keyboard cannot provide this. `$C000` and `$C010` reads go to the real bus (V `vtw_core_top.sv:575-576`), and the //e's keyboard hardware reports one key (A).

**Who it helps.** Keyboard-only players of action games, including both DOOM ports (A). A game would still read `$C000` for typing.

**Where it could live.**
- The TransWarp contract says "no new soft switches": `$C074` stays the only decoded register (V `README_VIRTUAL_TRANSWARP.md:279-281`). Change 5 already makes one exception, at `$C069`.
- Option A: the PS writes a key bitmap into a main page that the program names through the memory API. It needs no new address and no RTL.
- With option A, each PS write clears the TURBO caches once (V `vtw_core_top.sv:1207`). Whether PS writes into the shadow are safe while the core runs was not checked (A).
- Option B: a read-only block in slot 7's C8 window. Today `$CFF3-$CFFE` return ROM bytes, served inside the fabric (V `vtw_core_top.sv:678-692`; A: latency not read). This costs about 32 FFs and 20 LUTs (A). A read there is an exposure access and waits at the `$Cxxx` barrier (see R7).

**Size and risk.** 100-200 lines of PS code (A). The risk is low.

**Priority.** Low. The mouse already covers turning.

**A design would have to settle:**
- The key set: HID usages chosen by the program, or a fixed set.
- The latency, which follows the HID report interval (A).
- Speed-key bindings, which fire whether the menu is open or not (V `README_VIRTUAL_TRANSWARP.md:281-284`).
- Whether the same table should also work on ONE//e.

### R7. A microsecond counter the 6502 can read

**Problem.**
- The core's counters (`perf_count`, V `vtw_core_top.sv:1622-1652`) are read by the ARM, through `TURBO_PERF` (V `card_control_regs.h:293`). Change 0's counters are also read by the ARM (A).
- The memory API's STATUS block carries the ARM microsecond counter at offset 16 (V `README_MEMORY_API.md:94`). Reading it takes a SmartPort exchange.
- Timings on the card are VBL counts, 0.625 ms over 32 runs (V `fuzz-timing-2026-09-30.md:64`). ARM holds also merge VBL interrupts (V `README_MEMORY_API.md:233-235`).
- The existing port has no hardware cycle counter (V `docs/research/existing-port.md:510`).

**Who it helps.** Profiling on the card for both DOOM ports, measuring the effect of the changes in this document, and any benchmark program (A).

**Size and risk.** A 32-bit counter, a 24-bit latch and a prescaler: about 60 FFs and 30-50 LUTs (A). The risk is low.

**Priority.** Medium. It is small, and it makes every card measurement exact.

**A design would have to settle:**
- The address. Slot 7's C8 window adds no soft switch, but a `$C7xx` access must select it first (V `vtw_core_top.sv:678-681`).
- The effect of reading it. Any `$C800-$CFFF` access is an exposure access and waits at the `$Cxxx` barrier (V `vtw_core_top.sv:1390-1400`, `:1414-1415`).
- Without an exemption, a read would drain the mirror and disturb the timing it measures. Either exempt the counter reads or accept the drain.
- The unit: microseconds, Apple cycles, or fabric clocks divided by 8. At 133.333 MHz, the fabric clock does not divide to 1 MHz by an integer (V `appletini.json` `fabric_mhz`).
- An atomic read. Reading the low byte would latch the three upper bytes.
- Whether it shares one block with R6's option B.

### R8. FW-S2: slowdown presets 16, 32 and 64

**Problem.**
- The menu presets run from 256 to 65535 cycles (V `config_menu.c:84-86`). The Doom profile sets `vtw.slowdown.cycles=32` by hand (V `docs/NATIVE.md:577`). A profile accepts any value up to 65535 (V `config_menu.c:3550-3552`).
- The menu shows the active value, "32 cyc" (V `config_menu_device_tabs.c:722-723`). But a value that is not a preset maps to index 1, "default 512" (V `config_menu.c:4694-4704`). One step either way then gives 256 or 1024, and the menu cannot return to 32 (V `:4711-4714`).
- Adding three presets at the front moves 512 to index 4, so the fallback must search for the default instead of assuming its index.
- `scripts/test_config_profiles.py:675-680` pins the table (V). Changing it is a specification change, not a weaker test.
- This is question 35 of change 8.

**Who it helps.** The DOOM port, and any Phasor user who wants a short window from the menu.

**Size and risk.** A few lines of PS code and one test change, with no RTL. A window shorter than a detection loop needs could make card detection fail in other software (A). The menu help should say so.

**Priority.** Medium. It costs almost nothing and belongs in change 8's stage 8b.

### R9. Hardening

**`$C073` values with bit 7 set.**
- Both switch trackers ignore such a write, and the bank stays as it was (V `soft_switch_manager.sv:132-144`). The write still lands in the //e's paddle-trigger region (V `:135-137`; A for what the motherboard does with it).
- The vTW tracker is the same module (V `vtw_core_top.sv:427-433`).
- A sizing probe that stores to banks `$80-$FF` would write into the bank selected before (A: no such probe was tested). What a real RamWorks card does was not checked (A).
- Request: state the rule in `README_VIRTUAL_TRANSWARP.md`, and keep it consistent with the zero-page pair, where 127-255 mean "follow" (V `docs/firmware/zpbank-review.md:134`). Size: documentation only.

**Bank 127, which is physical bank 128.**
- The comments in `psram_simple.sv` disagree. `:35-37` says bank 128 "is not served". `:123-125` says it is served through address bit 23 and must not be rejected (V).
- The memory API stops at bank 126 (V `memory_api.h:13`). SmartPort rejects physical banks above 127 (V `smartport_service.c:382-384`). The core's tracker accepts `$C073` values 0-127 (V `soft_switch_manager.sv:141-144`), and the PSRAM side serves decode bank `$80` (V `psram_simple.sv:123-125`).
- `psram_driver.sv:16` takes a 24-bit address. Where bank 128 lands, and what lives there, is still open (A: `zpbank-review.md:28`, most likely `0x00xxxx`).
- Software sizes the card by probing (V `soft_switch_manager.sv:138-140`), so a probe may write bank 127 (A).
- Request: decide whether bank 127 exists. Then make the core, the API, SmartPort and the advertised size agree. Size: a few LUTs, or documentation only.

**The language card as a memory API endpoint.**
- Endpoints must lie in `$0200-$BFFF`, which excludes the language card (V `README_MEMORY_API.md:159-162`).
- The DOOM port fills its main language card by CPU copy (V `docs/NATIVE.md:204`).
- In the design with the pair, tic overflow is paged into the aux card by CPU copy every frame (V `docs/research/native-memory.md:211`).
- Today the CPU copies PSRAM to main at 0.246 µs a byte, against 0.345 for the API (M, model, `native-memory.md:33`).
- After R3, the API would take about 0.20 µs a byte (M, model), so this item pays off only once R3 is in.
- Size: PS range checks and the `$D000` bank selection, about 50-100 lines (A).
- Risk: a caller could overwrite its own transport code. The README tells callers to keep that code in the language card (V `README_MEMORY_API.md:197-200`).

**Priority.** Low for bit 7 and bank 127: both problems are latent, and no affected program is known. Medium for the language card, once R3 is in.