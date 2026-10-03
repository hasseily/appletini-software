# The SHR display as bank `$E1`: IIgs shadowing on the Appletini (specification)

Written 2026-10-03 from three candidate designs and their two reviews (firmware and software). This is the recommended design; section 9 lists what was taken from each and what was rejected. Nothing was built or simulated, and no firmware file was changed.

**Marks.** **V**: I read it at the cited file:line in this session. **G**: the grounding or review notes of this design round read it; I did not re-read it. **M**: memory or public knowledge, with a confidence. **E**: my estimate from the cited figures. **I**: my inference. **A**: an assumption still to be checked.

**Paths.** FW = `/Users/henri/Documents/Repos/appletini-one` at 3101934 (F1.2.2). DOOM = `.../appletini-software/demos/doom_gs`. AW = `/Users/henri/Documents/Repos/AppleWin/source`. GSQ = `/Users/henri/Documents/Repos/gssquared` at 78125953. `core` means `FW/hdl/apple/vtw_core_top.sv`.

**Numbering.** In the design document "vTW Memory Fast Path: Design", change 1 is "bank register in the bank-steer list" and the lazy SHR mirror is **change 3** (`requests.md:10`, `:38-43` V; change 1 as "`$C071/$C073` on the bank-steer list": `fws1-spec.md:322` V (check 2026-10-03); `requests.md:10`, `:38-43` support only change 3). Change 5 is the zero-page bank pair at `$C069` (`zpbank-spec.md`). This text uses that numbering.

## 0. Summary

**The answer to the owner's question.** The display buffer is **bank `$E1`**, as on the IIgs. One name, two ways in:

- **The memory API** (the fast way, and the only tear-free one): AUX logical bank `$E1` becomes a COPY/FILL destination for `$2000-$9FFF`. One CONTROL list is one **present**: the renderer shows it whole, at one frame edge.
- **The CPU** (the direct way): writing `$E1` to `$C073` opens a **write-only display window**. Stores that would go to aux `$2000-$9FFF` go to the display instead. Reads, zero page, the stack and the language card stay on the bank selected before.

The owner's decision is built underneath: **`$C035` SHADOW**, IIgs semantics. With shadowing inhibited, CPU stores to aux bank 0 `$2000-$9FFF` (the IIgs bank `$01`) stay in RAM: no record, no bus cycle, no motherboard mirror. They run as TURBO fast writes.

| Item | Decision |
|---|---|
| The display | The renderer's existing aux copy, `g_aux_bank` `$2000-$9FFF` in CPU1's DDR (`FW/ps_sources/frontend/apple_cycle_egress.h:37-39` V). It is fed only by capture records (`apple_cycle_egress.c:270-298` V). No new RAM. |
| `$C035` | Write-only, latched by the vTW core from its own bus write. Honoured only while SHR is selected. Bit 3 inhibits aux `$6000-$9FFF`; bits 3 **and** 4 inhibit aux `$2000-$5FFF` (the IIgs rule, section 1.2). Other bits are stored and ignored. Reset value `$00`, not the IIgs's `$08`. |
| Arming | Nothing changes until software writes `$C035` once after reset. VidHD-era software never does, so for it F1.2.2 behaviour is exact. |
| Inhibited writes | Shadow BRAM only, like a PRIVATE memory-API write today. They never reach the display or the motherboard, and nothing reconciles them later. |
| CPU display window | `$C073 = $E1` (armed only). Write-only. Each store is one direct capture record, at every speed. No shadow write, no bus cycle, no coalescer. |
| API display endpoint | AUX bank `$E1`, destination only, `$2000-$9FFF`, flags 0. The copy engine streams the bytes into the capture FIFO. The PS brackets each CONTROL list with present markers, and CPU1 does not rebuild the SHR frame while one is open. |
| Reading the display | Not in v1. The program reads its RAM copy (aux 0). An API source path is a later, optional stage (section 3.6). |
| Cost | About 150-240 LUTs and 60 FFs, **0 BRAM** (E). About 120-205 lines of PS code (E; the sum of section 3.4's rows, check 2026-10-03). |
| Kill switch | Compile-time `DSP_ENABLE`, runtime `CARD_CTRL 0x35` bit 2. Bit 0 is the paged-SHR fallback (`FW/hdl/apple/apple_top.sv:2821`, `:2964` V); bit 1 is change 3's `lazy_en` (`lazy-mirror-spec.md:12` V). |
| DOOM GS | `$C035 = $18`, draw into aux 0 exactly as today, present `$2000-$88FF` once a frame. DRAW 31.3 → about 21-25 ms, **6.343 → about 6.6-6.8 FPS**, and tear-free (section 8). |

The model is upstream DOOM GS's on the IIgs: shadowing off, draw in bank `$01`, copy the finished ranges to `$E1` (`DOOM/build/upstream/src/iigs/i_viigs65.s:1-3` V, "Other drawing uses the bank $01 back buffer and marks byte ranges; I_FinishUpdate copies only those"). The IIgs's MVN to `$E1` becomes a memory-API COPY.

## 1. The decision this implements

### 1.1 What the Appletini does today

| Fact | Source |
|---|---|
| The picture is CPU1's 64 KB DDR copies, `g_main_bank` and `g_aux_bank`, updated only from capture records; the only other write is the clear at init | V `apple_cycle_egress.c:85-88`, `:270-298` |
| The vTW shadow BRAM is the CPU's RAM; the renderer never reads it | G `vtw_shadow.sv:20-23`, `:101-103` |
| Only physical banks 0 and 1 are ever posted or recorded | V `core:565-568`; V `apple_cycle_capture.sv:67-72` |
| In TURBO every aux `$2000-$9FFF` write is both a direct record and a coalescer byte drained over the bus | V `core:1368-1380`; G `vtw_video_policy.sv:28-31` |
| `$C035` is captured as an I/O record; the renderer stores it and only invalidates its SHR cache | V `apple_cycle_capture.sv:74-79`; V `apple_cycle_renderer.c:241`, `:2926-2928` |
| The core does not decode `$C035`; a write is an exposure access | V `core:1390-1400` |
| PRIVATE memory-API writes update the shadow and emit no record and no motherboard write | V `FW/README_MEMORY_API.md:179-191` |

So the card already behaves like an IIgs with SHR shadowing from bank `$01` always on, plus a third copy the IIgs does not have: the motherboard's aux RAM. That third copy is what costs DOOM its time (CALIB `SHR SEQ` 1.012 µs a byte, `SHR COL` 2.487 µs a byte scattered: `DOOM/docs/results/calib.md:69-70` V).

### 1.2 The IIgs register

| Bit | IIgs meaning | Appletini v1 |
|---|---|---|
| 7 | reserved | stored, ignored |
| 6 | IOLC inhibit | stored, never honoured |
| 5 | text page 2 (ROM 03) | stored, ignored |
| 4 | aux hi-res pages `$01:2000-5FFF` | honoured together with bit 3 |
| 3 | SHR buffer `$01:2000-9FFF` | honoured |
| 2, 1 | hi-res page 2, page 1 (bank `$00`) | stored, ignored |
| 0 | text page 1 | stored, ignored |

Sources: `GSQ/Docs/AppleIIgs-Memory.md:26-84` (V; an emulator author's notes, medium-high confidence).

**Bit 3 alone does not inhibit `$01:2000-5FFF` on the IIgs.** gssquared's shadow test passes bank `$01` hi-res unless both bit 3 and bit 4 are set: "Odd-bank $2000-$5FFF is gated by AUXHGR|SHR (inhibit only when both are set; see SHADOW.s inhbt1)" (`GSQ/src/mmus/mmu_iigs.hpp:117-131` V). Its tests 28 and 29 write `$08` alone and `$10` alone and both expect the byte in `$E1` (`GSQ/apps/iigsmmutest/tests.hpp:493-517` V). The two halves of the range shadow for different reasons: the SHR rule covers `$2000-$9FFF`, the aux hi-res rule covers `$2000-$5FFF`, and a byte is shadowed if either rule says so. Upstream DOOM GS writes `$3F` (`DOOM/build/upstream/src/iigs/i_iigs65.s:252-253` V), so it never sees the difference.

This design follows the IIgs: **`$08` inhibits only `$6000-$9FFF`; `$18` inhibits all of `$2000-$9FFF`.** Software should write `$18` (or upstream's `$3F`). Gssquared's own notes say bits 1 and 2 also gate the aux pages (`AppleIIgs-Memory.md:59`, `:71`, `:77` V); its code says they do not. The difference matters only for values with bit 4 = 0 and bit 1 or 2 = 1, and v1 ignores bits 1 and 2. Question 1 asks the owner to confirm against the IIgs Hardware Reference.

**Reset value.** The IIgs resets SHADOW to `$08` (`GSQ/src/mmus/mmu_iigs.cpp:793` V; M, medium-high for real hardware). The Appletini resets to `$00`: VidHD-era software never writes `$C035`, and `$08` would hide its `$6000-$9FFF` writes.

**Other IIgs facts used here.** The IIgs has no SHR page flip (M, high). Writes to `$E1` are not copied back to `$01`, and changing bit 3 copies nothing either way (M, high). `$C036` bit 4 shadows every bank into `$E1` (`AppleIIgs-Memory.md:96-103` V); it is not modelled.

## 2. Software contract

### 2.1 State

| State | Width | Reset | Set by |
|---|---|---|---|
| SHADOW latch | 8 | `$00` | any write to `$C035` |
| ARMED | 1 | 0 | any write to `$C035` |
| SHR selected | 1 | 0 | `$C029` written with bits 7:6 = 11 (and the host allows fake SHR) |
| Display window | 1 | 0 | `$C071`/`$C073` written with `$E1` while ARMED |
| Underlying bank | 7 | 0 | today's RamWorks bank (`FW/hdl/apple/soft_switch_manager.sv:141-144` V); `$E1` leaves it unchanged |

Everything resets on power-up, Apple RES# (Ctrl-Reset), session start and end, and a CORE_RUN drop: the `core_res_n` term, as in `zpbank-spec.md:242-256` (V). It also resets when the kill switch clears. The display contents survive Apple RES, as `g_aux_bank` does today.

### 2.2 Registers

**`$C035` SHADOW, write.**

- Latches all 8 bits and sets ARMED.
- The write still goes out as a real bus cycle, so capture records it for the renderer as today (`apple_cycle_capture.sv:74-79` V). It stays an exposure access (`core:1399` V); that flush is correct, because bytes written before the switch keep their old class.
- On a //e, `$C030-$C03F` is the speaker, so each write clicks once (M, medium-high; AppleWin says the same: "Writes to $C03x addresses will still toggle the speaker, even with a VidHD present", `AW/Memory.cpp:643-652` V). Write it rarely: entering and leaving SHR.

**`$C035`, read.** Not decoded. A read is a bus cycle that clicks the speaker and returns the floating-bus byte (`core:1104-1107` V; the scanner-byte return for `$C030-$C05F` reads is `core:1255-1270` V, check 2026-10-03). Keep a copy in memory. IIgs code that does `LDA SHADOW / ORA #$08 / STA SHADOW`, as upstream's automap does (`DOOM/build/upstream/src/iigs/am_map65.s:1105-1109` V), must be rewritten. Answering reads is question 3.

**Effective inhibit.**

```
inh_hi  = ARMED && SHR selected && SHADOW[3]                  ; aux $6000-$9FFF
inh_lo  = ARMED && SHR selected && SHADOW[3] && SHADOW[4]     ; aux $2000-$5FFF
```

"Aux" means **physical bank 1**, after RAMRD/RAMWRT, 80STORE/PAGE2/HIRES and `$C073`. Main is never inhibited (IIgs bit 3 concerns bank `$01` only), so the paged-SHR second field in main and the A2Li holes behave as today. Outside SHR, `$C035` has no effect (question 2).

**`$C071` / `$C073`.**

| Value written | F1.2.2 | This design |
|---|---|---|
| `$00-$7F` | selects the bank | same; also closes the display window |
| `$E1`, ARMED | ignored, bank kept (`soft_switch_manager.sv:141-144` V) | **opens the display window**; the bank is kept as the underlying bank |
| `$E1`, not ARMED | ignored | ignored |
| any other `$80-$FF` | ignored | ignored; also closes the display window |

The `$E1` write stays a real bus cycle and an exposure access (`core:1400` V). The motherboard trackers ignore it, as they ignore every bit-7 value. Keeping it on the bus avoids a new FSM branch, as change 5 does for `$C069` (`zpbank-spec.md:121-127` V). Absorbing it is question 6.

### 2.3 What each access reaches

| Access | RAM (shadow) | Display | Motherboard |
|---|---|---|---|
| CPU store to aux 0 `$2000-$9FFF`, not inhibited | yes | yes, one record | yes (posted or coalesced, as F1.2.2) |
| CPU store to aux 0, **inhibited** | yes; TURBO fast write except page `$9D` | **no** | **no, ever** |
| CPU store with the **display window** open, aux-destined, `$2000-$9FFF` | **no** | yes, one direct record | no |
| CPU store with the window open, main-destined (RAMWRT off), or outside `$2000-$9FFF` | as F1.2.2, under the underlying bank | as F1.2.2 | as F1.2.2 |
| CPU load from anywhere, window open or not | RAM, under the underlying bank | — | — |
| Memory API PRIVATE write to aux 0 | yes | no | no (unchanged, `README_MEMORY_API.md:179-191` V) |
| Memory API write to **AUX `$E1`** | **no** | yes, inside one present | no |
| SmartPort block read into aux `$2000-$9FFF`, inhibited | yes | no | no (section 3.5) |
| Native motherboard CPU (vTW off) | motherboard | as today: bit 3 has no effect | — |

Consequences:

- **The display window is write-only.** `INC $2000` with the window open reads RAM and writes the display.
- **Reads under the window follow the underlying bank.** `lda #N / sta $C073 / lda #$E1 / sta $C073` reads bank N and writes the display. With N = 0 it reads aux 0 and writes the display, which is a CPU present.
- **Turning shadowing back on copies nothing.** Bytes written while inhibited reach the display only by a present or by being written again, as on the IIgs.
- **Inhibited and display-only writes leave the motherboard's aux RAM, and PSRAM bank 1 when the Appletini provides aux, stale for good.** This matches the TransWarp contract: "motherboard RAM is deliberately stale outside the video windows" (`FW/README_VIRTUAL_TRANSWARP.md:112` V), and Ctrl-Reset handback returns the machine cold (`:116` V). It is the same staleness a PRIVATE write leaves today. Question 7 asks the owner to confirm.

### 2.4 Mode interactions

| With | Rule |
|---|---|
| `$C029` | Entering SHR with `$18` already latched starts the inhibit at once. Leaving SHR stops it; nothing is copied. Inhibited bytes in aux `$2000-$5FFF` then show stale in DHGR, on the //e's own video and on the Appletini's, until rewritten. The window and the API endpoint work in every mode, because the renderer builds every mode from `g_aux_bank`; `$E1:$2000` written with SHR off shows in DHGR on the Appletini's output only. |
| SCBs `$9D00-$9DC7`, palettes `$9E00-$9FFF` | Part of the range. While inhibited they change on screen only when presented or written through the window. A present that carries them changes them together with the pixels. |
| `$9DC8-$9DFF` | Stays software-reserved. `$9DF8` (paged control) and `$9DFC` (`SHR4`/`3200` magic) change the renderer's mode (G `apple_cycle_renderer.c:1434-1435`, `:1504-1515`). The core's `$9DF8` tracker (`core:1877-1882` V) follows the **display**: it updates on an aux 0 `$9DF8` write that is not inhibited, on a window write and on an API write to `$E1:$9DF8`, and ignores inhibited writes. |
| Paged SHR (SHR4, 3200) | Main second field unchanged. |
| A2Li | The holes are in main (`$0878-$087F`, `$4078-$407F`), never inhibited; the policy keeps them immediate (G `vtw_video_policy.sv:33-37`). |
| ALTZP, language card | Follow the underlying bank; the window does not touch them. |
| Interrupts | The same rules as any RamWorks bank. A handler that stores into `$2000-$9FFF` with RAMWRT on would write the display. |
| ROM, ProDOS, SmartPort calls | Close the window first (`stz $C073`). The `$C035` latch can stay set. |
| Change 5's pair, if built | Optional extension: pair write value `$E1` means the display window for that direction (`zpbank-spec.md:29` reserves `$80-$FF` V). Not needed for v1. |

### 2.5 Memory API 1.1

Major version stays 1; 1.0 lists stay valid. A 1.0 caller checks the signature, the major version, the descriptor size, the feature bits it requires and availability (`README_MEMORY_API.md:36-38` V; `example.s:25-37` checks the signature, the major and availability), so new feature bits and a new minor do not disturb it (check 2026-10-03).

| Field | Rule |
|---|---|
| Destination space 1 (AUX), bank `$E1` | **The display.** `$2000 <= address`, `address + length <= $A000`. Flags must be 0 (PRIVATE has no meaning there). COPY and FILL. |
| Source space 1, bank `$E1` | Invalid in 1.1 (RANGE `$63`). Reserved for the optional stage in section 3.6. |
| Feature bits, STATUS offset 8 | New bit 4 (`$10`) `DISPLAY`: the AUX `$E1` endpoint. New bit 5 (`$20`) `SHADOW`: `$C035` and the CPU window. Today's bits are COPY 1, FILL 2, PRIVATE 4 (`FW/ps_sources/frontend/memory_api.h:23-25` V); change 5 claims 8 (`zpbank-spec.md:301` V). Both new bits require the bitstream's capability bit, the kill switch on and the capture egress enabled. |
| Present | All `$E1` destinations of one CONTROL list form one present. CPU1 does not rebuild the SHR frame between its first and last byte. Other descriptors in the same list run in order as today. |
| Errors | On any refusal or abort after the first `$E1` byte, the present is still closed. The display may then hold part of the list. |
| Old firmware | F1.2.2 refuses AUX bank `$E1` with RANGE (`README_MEMORY_API.md:163-165` V; the code: `memory_api.c:43-47` V, bank > 126), so a caller learns the feature is absent before anything is written: every descriptor is validated before the hold (`memory_api.c:116-153` V) (check 2026-10-03). |

`memory_api.inc` gains `AMEM_DISPLAY = $E1`, `AMEM_FEATURE_DISPLAY = $10` and `AMEM_FEATURE_SHADOW = $20`.

### 2.6 Detection

Use the memory API STATUS (`FW/software/memory_api/example.s:16-41` V), then test the two feature bits. A CPU-only probe is unsafe: a real RamWorks III may alias `$E1` onto a populated bank, and a store to `$2000` there would look like a working window (I, medium). Run the probe only after identifying the Appletini slot ROM, and prefer STATUS.

```
        ; capabilities: the 32-byte STATUS block (example.s, probe_params)
        lda capabilities+8              ; feature bits, low byte
        and #AMEM_FEATURE_DISPLAY|AMEM_FEATURE_SHADOW
        cmp #AMEM_FEATURE_DISPLAY|AMEM_FEATURE_SHADOW
        bne old_path                    ; F1.2.2 or older, AppleWin, VidHD: today's path
```

### 2.7 Examples (ca65, 65C02)

Constants: `RAMRDOFF = $C002`, `RAMRDON = $C003`, `RAMWRTOFF = $C004`, `RAMWRTON = $C005`, `RWBANK = $C073`, `NEWVIDEO = $C029`, `SHADOW = $C035`. `SP_ENTRY` is the Appletini slot-7 SmartPort entry (`$C70D` in `example.s:12` V; discover it in a general caller). The SmartPort entry writes main `$07F8`; save it as `example.s:18-20` does.

**Turning shadowing off and on.**

```
        lda #$C1                ; SHR on: bits 7:6 = 11 (linear) and the bank latch
        sta NEWVIDEO
        lda #$18                ; inhibit: bit 3 (SHR) and bit 4 (aux hi-res)
        sta SHADOW              ; arms the feature; one speaker click on a //e
        sta shadow_copy         ; SHADOW cannot be read back
        ...
        stz SHADOW              ; shadowing on again: nothing is copied
        stz shadow_copy
```

**Drawing a frame into the off-screen buffer** (aux 0, the IIgs bank `$01`; `$C073` = 0).

```
        sta RAMWRTON            ; $0200-$BFFF stores go to aux bank 0
        ldx #0
        lda #$11                ; colour 1 in both pixels
row0:   sta $2000,x             ; RAM only: no record, no bus cycle
        sta $2050,x             ; (TURBO fast writes outside page $9D)
        inx
        cpx #$50
        bne row0
        sta RAMWRTOFF
```

Keep the drawing code's own variables in zero page: RAMWRT redirects every store to `$0200-$BFFF`.

**Presenting it with the memory API** (tear-free; the 65C02 returns before CPU1 has applied it).

```
        lda $07F8
        pha
        jsr SP_ENTRY
        .byte $04               ; CONTROL
        .word present_params
        tax                     ; the result code (TAX, PLA, STA keep C)
        pla
        sta $07F8
        txa                     ; A = the result code again (check 2026-10-03:
        bcs present_failed      ;  the PLA had replaced it with the $07F8 byte)
        ...
present_params:
        .byte 3, 0
        .word present_list
        .byte AMEM_CONTROL_CODE
        .byte 0, 0, 0, 0
present_list:
        AMEM_BEGIN 3
        AMEM_COPY_RECORD AMEM_AUX, 0, $2000, AMEM_AUX, AMEM_DISPLAY, $2000, $7D00, 0  ; pixels
        AMEM_COPY_RECORD AMEM_AUX, 0, $9D00, AMEM_AUX, AMEM_DISPLAY, $9D00, $00C8, 0  ; SCBs
        AMEM_COPY_RECORD AMEM_AUX, 0, $9E00, AMEM_AUX, AMEM_DISPLAY, $9E00, $0200, 0  ; palettes
```

**Presenting it with the CPU** (no SmartPort call; it tears like any direct write). The loop must run from the language card or zero page, because RAMRD also redirects opcode fetches from `$0200-$BFFF`.

```
        ; in language-card RAM, interrupts masked
        sta RAMRDON             ; reads of $0200-$BFFF: aux, underlying bank 0
        sta RAMWRTON
        lda #$E1
        sta RWBANK              ; window open: stores to $2000-$9FFF -> display
        ldy #0                  ; (check 2026-10-03: the label was "cpy",
cp_s:   lda $2000,y             ;  a mnemonic; ca65 rejects it) aux 0 (RAM)
cp_d:   sta $2000,y             ; display
        iny
        bne cp_s
        inc cp_s+2              ; next page, source and destination
        inc cp_d+2
        lda cp_s+2
        cmp #$A0
        bne cp_s
        stz RWBANK              ; window closed, bank 0
        sta RAMWRTOFF
        sta RAMRDOFF
```

**Writing the display directly** (palette 0, colour 15 to white, whatever SHADOW says).

```
        lda #$E1
        sta RWBANK              ; window open (after a $C035 write armed it)
        sta RAMWRTON
        lda #$FF
        sta $9E1E               ; colour 15, low byte: green and blue
        lda #$0F
        sta $9E1F               ; high byte: red
        sta RAMWRTOFF
        stz RWBANK              ; back to bank 0; the window closes
```

RAM (aux 0 `$9E1E`) is unchanged. If the program also keeps aux 0 as its copy of the screen, it writes the same bytes there too.

**Reading it back.** v1 has no read path to the display. A program reads its RAM copy, which equals the display when every display byte also went through aux 0: shadowing on, or drawn in aux 0 and presented.

```
        sta RAMRDON             ; $C073 = 0, window closed
        lda $2000               ; aux 0: the display's byte, under the rule above
        sta RAMRDOFF
```

With the optional stage of section 3.6, `AMEM_COPY_RECORD AMEM_AUX, AMEM_DISPLAY, $2000, AMEM_AUX, N, $2000, $8000, 0` would copy the display itself to bank N.

**Saving and restoring the screen** (aux 0 holds what is shown, as above).

```
save_list:                      ; the screen, SCBs and palettes to bank SAVEBANK
        AMEM_BEGIN 1
        AMEM_COPY_RECORD AMEM_AUX, 0, $2000, AMEM_AUX, SAVEBANK, $2000, $8000, 0
restore_list:                   ; one present, and the RAM copy put back
        AMEM_BEGIN 2
        AMEM_COPY_RECORD AMEM_AUX, SAVEBANK, $2000, AMEM_AUX, AMEM_DISPLAY, $2000, $8000, 0
        AMEM_COPY_RECORD AMEM_AUX, SAVEBANK, $2000, AMEM_AUX, 0, $2000, $8000, AMEM_PRIVATE
```

## 3. Firmware changes

### 3.1 Core (`hdl/apple/vtw_core_top.sv`)

| # | Change | Anchor |
|---|---|---|
| C1 | `shr_selected_q`: decode `$C029` writes from the registered tuple at `X_ROUTE`, value `cycle_wdata_q[7:6]==2'b11`, reset as section 2.1 and on `!fake_shr_allowed`. **Shared with change 3**, which specifies the same register (`lazy-mirror-spec.md:26-32` V). New input `fake_shr_allowed` from `apple_top.sv:1033` (V). | beside `:1877` |
| C2 | `shadow_q[7:0]`, `shadow_armed_q`: latch on `X_ROUTE && xl_is_bus && xl_is_write && cycle_addr_q==16'hC035`, the same pattern as the `$9DF8` tracker. Derive `inh_lo_q`, `inh_hi_q` as registers (section 2.2), so no new decode sits on the cycle path. | `:1877-1882` V |
| C3 | `disp_q`: on a `$C071`/`$C073` write at `X_ROUTE`, `disp_q <= shadow_armed_q && dsp_en && cycle_wdata_q == 8'hE1`. | same block |
| C4 | `xl_inhibited = !xl_is_bus && xl_shadow_valid && xl_is_write && xl_decoded[23:16]==8'd1 && (cycle_addr_q in $6000-$9FFF ? inh_hi_q : cycle_addr_q in $2000-$5FFF ? inh_lo_q : 0) && !xl_is_overlay_post`. `xl_is_posted` gains `&& !xl_inhibited`. Inhibited writes then take the plain shadow path, and TURBO fast-write permission follows from `turbo_map_fast_write = !xl_is_posted && ...` unchanged. | `:565-569`, `:1216-1219` V |
| C5 | **Must-fix: invalidation.** `turbo_invalidate` gains `({inh_lo_q, inh_hi_q, disp_q} != turbo_dsp_q)`. Fast-write permission is computed at fill time (`:1216-1219` V). Without this term, cached fast-write entries for aux `$2000-$9FFF` would survive an inhibit release, and later shadowed writes would skip their records. The cost per `$C035` or window change is one cache refill, like any `$C073` bank change today (`:1185`, `:1206-1211` V). | `:1206-1211` V |
| C5b | `turbo_mapping` at `:1185` is `wire [18:0]` (V). C5 keeps the new state out of `TranslateState`, so that width does not change. | `:1185` V |
| C6 | `xl_is_display = disp_q && xl_is_write && !xl_is_bus && xl_decoded[23:16]!=8'd0 && cycle_addr_q in $2000-$9FFF`. **Must-fix: route it before the RamWorks test.** With an underlying bank of 1 or more, the translation is `APPLE_ROUTE_CACHE` with no shadow backing, so `xl_is_ramworks` (`:643-644` V) would send the write to PSRAM. A display write must touch no shadow byte, no PSRAM line, no posted queue and no coalescer, and fill no TURBO map entry. (check 2026-10-03) The anchor `:643-644` alone does none of the last four. With underlying bank 0 the write has `xl_shadow_valid`, so today it would also be written to shadow at `X_ROUTE` (`core_shadow_issue`, `shadow_a_we`: `:1307-1308`, `:1320` V) and would fill a TURBO write-map entry (`turbo_map_fill`, `:1212-1213` V). That entry's fast bit is `!xl_is_posted && ...` (`:1218-1219` V), which is 1 for a display write that is not posted (and for an inhibited one, C4), and a write hit needs only `write_valid && write_fast` and a page tag (`:1240-1242` V). So without gating, the second store to the same page in TURBO would hit the map and land in shadow RAM, not the display. `turbo_map_fill` (or the fast bit), `core_shadow_issue`'s write enable and `xl_is_posted` each need a `!xl_is_display` term. | `:643-644`, `:1212-1219`, `:1307-1320` V |
| C7 | Display record leg. `video_record_valid` (`:1379` V) gains a display term at **every** speed, with `video_record_addr = {1'b1, cycle_addr_q}`. In TURBO it is admitted like today's direct record but without the coalescer handshake. At classic speeds (`video_selected` is TURBO only, `:1352-1353` V) it first waits for `eng_post_idle && !post_stage_valid_q`, so earlier posted writes reach capture first. | `:1352-1384` V |
| C8 | `$9DF8` tracker: add `!xl_inhibited`; also update on a display write to `$9DF8` (C6) and on the engine's `$E1:$9DF8` byte (input from 3.2). | `:1877-1882` V |
| C9 | Debug: `shadow_q`, ARMED, `disp_q`, `inh_lo_q`, `inh_hi_q` in a read-only card-control word for `vtw status`. | — |

Not changed: `globals.sv translate_apple_addr`, `soft_switch_manager.sv`, `vtw_video_policy.sv`, the coalescer, the bank sync and the motherboard trackers. The exposure list (`:1390-1400` V) is unchanged; with SHR writes inhibited, a `$C073` write in DOOM finds nothing deferred to flush.

### 3.2 Copy engine (`hdl/apple/vtw_copy_engine.sv`) and the record mux

| # | Change | Anchor |
|---|---|---|
| E1 | Destination physical `$E12000-$E19FFF` = display. Classify it before `dest_shadow` (`dst_q < 24'h020000`) and the PSRAM default. (check 2026-10-03) The PS's endpoint mapping makes AUX logical bank `n` physical bank `n+1` (`memory_api.c:52` V), so logical `$E1` would become `$E2xxxx`: the PS must special-case bank `$E1` before that rule (and before `needs_ramworks`, set for any physical address ≥ `$20000`, `memory_api.c:147-148` V), or E1 must decode `$E2xxxx`. | `vtw_copy_engine.sv:47-48` V |
| E2 | New record output `rec_valid`, `rec_addr[16:0]`, `rec_data[7:0]`, `rec_ready`. In place of `SH_WRITE`, emit one record a byte from the source word (4 bytes a shadow read) or line (8 bytes a PSRAM read). `completed` counts accepted records. FILL emits the fill value. | `:7-27` V |
| E3 | `apple_top.sv`: the engine's record port and the core's `video_record_*` share capture's direct port. The engine runs only under a held core, so the core's leg is idle; assert that in simulation. Keep the `egress_cfg_enable_q` gate. | `apple_top.sv:1039-1043`, `:2272-2280` V |
| E4 | Present markers: a new record kind `RECORD_KIND_PRESENT = 3'b011` (kinds 0-2 are used: `apple_cycle_capture_pkg.sv:13-15` V), data 1 = open, 0 = close. A write-only card-control register lets the PS emit one through the same direct port while the engine is idle. | `apple_cycle_capture.sv:298-302` V |

Capture's direct port already keeps FIFO order with physical records, and accepts a direct record only below 4064 entries and on a clock with no physical record (`apple_cycle_capture.sv:298-302` V). The FIFO is 4096 records (`:56` V); the DDR ring holds 131,072 (`lazy-mirror-spec.md:193` V). A 32 KB present therefore never stalls the engine for long, provided egress keeps up (A). (check 2026-10-03) Egress does not keep up with one record a clock: it pulls from the FIFO only between AXI bursts of at most 16 records, each followed by a NOTIFY burst (`apple_cycle_egress.sv:4-12`, `:242-266` V), about 9 records per 28 clocks, "over 30 M records/s" (`lazy-mirror-spec.md:192`, G for the clocks, A for AXI latency). After the first ~4,064 records fill the FIFO, the engine runs at the egress rate, about 23-33 ns a record.

### 3.3 Cost (E)

| Block | LUT | FF | BRAM |
|---|---:|---:|---:|
| C1-C3, C9 latches and decode | 20-35 | 25 | 0 |
| C4-C6 classification, invalidation term | 25-45 | 4 | 0 |
| C7 display record leg, classic wait | 20-35 | 2 | 0 |
| E1-E2 engine display destination | 50-80 | 30 | 0 |
| E3-E4 direct-port mux, present marker | 30-45 | 2 | 0 |
| **Total** | **about 150-240** | **about 60** | **0** |

Budget: 110 of 140 BRAM tiles, 36,086 of 53,200 LUTs, 83.95% of slices occupied (`FW/README_VIVADO_RUNTIME_AUDIT.md:101-106` V; that audit predates F1.2.2's copy engine, A).

**Timing.** C4 adds a term to `xl_is_posted`, on the admission family. The recorded margins are thin: the TURBO shadow-RAM family at +0.171 ns and the capture FIFO at +0.182 ns against a +0.200 ns gate (`FW/docs/FABRIC_TIMING_MARGIN_PLAN.md:2192-2194` V; the column meanings were not re-read, A). (check 2026-10-03) Those two figures are the table's "F1.1.4 baseline" column (`:2186` V); the second trial of the same day shows +0.273 and +0.546 ns, and the +0.200 ns gate is "the then-current" one of the September 25 trials (`:2072` V; the standing rule is a +0.150 ns nominal floor, `:2055` V). No routed figure for F1.2.2 is recorded there. Every new operand is a register (`inh_*_q`, `disp_q`, the registered tuple). Fallback: compute `xl_inhibited` and `xl_is_display` one stage earlier, at `X_CAPTURE`, from `core_addr` and the registered state, as change 5 does for `cycle_zpb_redirect_q` (`zpbank-spec.md:311` V). The mux in E3 should be registered.

### 3.4 PS (ARM) changes

| File | Change | Size (E) |
|---|---|---:|
| `memory_api.h`, `memory_api.c` | AUX bank `$E1` as a destination (section 2.5), feature bits 16 and 32, minor version 1, `memory_api.inc` constants | 40-60 lines |
| `memory_api_hw.c` | Physical `$E1xxxx` on the engine path only; the ARM DMA fallback refuses it (`hw_dma` rejects ≥ `0x800000`, `:150-156` V). Emit present-open before the first `$E1` descriptor and present-close after the last, on every exit path, after the engine reports DONE. | 30-50 lines |
| `apple_cycle_egress.c` | Kind 3: call a renderer hook with open or close. On a gap or resync, force the present closed. | 10-20 lines |
| `apple_cycle_renderer.c` | In the SHR branch (`:3063-3095` V; check 2026-10-03, was `:3062-3090`), skip the rebuild while a present is open, counting it like the settle skip (`:3073-3082` V). Cap: after 8 frame markers with a present open, rebuild anyway, so a lost close cannot freeze the screen. | 15-25 lines |
| `smartport_service.c`, `smartport_card.sv` | Add the inhibit bits to the switch snapshot (as change 5 does, `zpbank-spec.md:277-288` V). Skip `arm_post` for inhibited aux `$2000-$9FFF` bytes (SmartPort posts video-window bytes today: `core:238-241` V). With the window open, direct spans into `$2000-$9FFF` fall back to the core's byte path, which handles the display. | 20-40 lines |
| `vtw_service.c` | `vtw: shadow=$18 armed=1 shr=1 inh=lo,hi win=0` | 5-10 lines |

### 3.5 What is not done

- No reconcile of inhibited bytes to the motherboard: not at SHR exit, not at session end, not on `$C073` writes (section 2.3).
- No readable display RAM (section 9, question 4).
- No IIgs bank `$00`/`$E0` shadowing: main is never inhibited, and there is no main display window.
- No effect on the native motherboard CPU.

### 3.6 Stages

Each stage is one full build against +0.200 ns.

| Stage | Content | Gives |
|---|---|---|
| S0 | C1-C3, C9, kill switch; state latched but unused | Equivalence with F1.2.2; status line |
| S1 | C4, C5, C8: the inhibit | IIgs shadowing; the DOOM speed-up needs S1 and S2 together |
| S2 | E1-E4 and the PS present (3.4) | The API endpoint, tear-free presents |
| S3 | C6, C7: the CPU window | Direct CPU writes to the display |
| S4 (optional) | Packed records (kind 4, 4 bytes a record) for engine presents | CPU1 work per present ÷4, if CPU1 is the bound |
| S5 (optional) | AUX `$E1` as a source: CPU0 asks CPU1 to apply every record up to the hold, clean the range and acknowledge, then reads `g_aux_bank` | Reading the display back, saving the true screen |

S1 without S2 is safe but useless for DOOM: inhibited frames never show. Ship S1 and S2 together.

## 4. Verification

The benches that build and pass under Verilator on this Mac: `tb_vtw_turbo`, `tb_vtw_video_policy`, `tb_vtw_video_coalescer`, `tb_vtw_video_bank_sync` and others; `tb_vtw_system` builds but fails 5 checks, cause unknown (memory note `appletini-firmware-simulation`, F1.2.1; M, high). Whether `tb_apple_cycle_capture` and `tb_vtw_copy_engine` pass here is not known. Timing needs Vivado, which this Mac does not have.

| Bench (script) | Cases |
|---|---|
| `hdl/sim/tb_vtw_turbo.sv` (`scripts/test_vtw_turbo.py`) | Kill switch off, or never armed: traces identical to F1.2.2 (posted count, records, perf counters). `$18` in SHR: a 256-byte aux burst then `lda $C000` gives 0 posted writes, 0 records, no video wait. `$08`: `$2000-$5FFF` still recorded and posted, `$6000-$9FFF` not. Inhibit outside SHR: no effect. Warm fast-write entries for aux page `$40`, then `$C035 = 0`: the next store is recorded (C5). Leave SHR with entries warm: same. Window: `$E1` with underlying bank 0 and 5; stores to `$2000`, `$9FFF`, `$A000`, `$1FFF`; loads under the window; `INC $2000`; one record each and no shadow or PSRAM change (C6); window under 80STORE+PAGE2+HIRES; `$E1` unarmed is ignored; a `$00-$7F` or other `$80-$FF` write closes it. Classic speed (1 MHz, divided): a window store after 20 posted bytes reaches capture after them (C7). `$9DF8` under each class (C8). Apple RES, CORE_RUN drop, kill switch: all state cleared. |
| `hdl/sim/tb_apple_cycle_capture.sv` | Direct records from the engine port and the core port in FIFO order with physical records; kind 3 markers; behaviour at the 4064 threshold. |
| `hdl/sim/tb_vtw_copy_engine.sv` (`scripts/test_vtw_copy_engine.py`) | `$E1` destination from shadow and from PSRAM, unaligned ends, FILL: the record stream equals the source bytes in order, and shadow BRAM is untouched. Abort mid-copy: `completed` equals records accepted. Back-pressure from `rec_ready`. |
| `hdl/sim/tb_apple_cycle_egress.sv` (`scripts/test_apple_cycle_egress.py`) | Kind 3 passes through the ring unchanged. |
| `hdl/sim/tb_vtw_video_policy.sv`, `tb_vtw_video_coalescer.sv`, `tb_vtw_video_bank_sync.sv` | Unchanged modules: must stay green. |
| `hdl/sim/tb_vtw_system.sv` | The translation monitor stays green (translation is unchanged). Needs XSim or a fix for the 5 Verilator failures first. |
| `scripts/test_memory_api.py`, `test_memory_api_hw.py` | Bank `$E1` limits; flags must be 0; source `$E1` refused; markers emitted on success, refusal and abort; feature bits only with the capability bit. |
| `scripts/test_apple_cycle_egress.py`, renderer tests | Present open across a frame marker: the frame is skipped; the cap forces a rebuild after 8; a gap closes the present. |
| `scripts/test_smartport_service.py` | Inhibit bits in the snapshot; inhibited video bytes not posted; window open: no direct span into `$2000-$9FFF`. |

**On the card.** New CALIB page lines (DOOM's `CALIB.hdv`): `INH SEQ` and `INH COL` (the `SHR SEQ`/`SHR COL` loops of `calib.md:69-70` with `$18` latched; expected near plain aux RAM speed), `DSP SEQ` and `DSP COL` (window stores), `PRES 26880` and `PRES 32000` (the API present's 65C02 time), and the egress counters during a present (`lazy-mirror-spec.md:198-203` V) to measure CPU1's record rate. A visual check: a program alternating two full screens by present shows no torn frame.

**In a2vm.** a2vm needs a model of the inhibit, the window and the present, priced from the CALIB lines, before DOOM's gain can be checked (section 8).

## 5. Compatibility

| Software | Effect |
|---|---|
| VidHD-era //e SHR software | Never writes `$C035` (A, medium: VidHD's manual lists no `$C035`, G `vidhd.txt:203-216`), so it is never armed: F1.2.2 behaviour exactly, `$E1` included. |
| RamWorks sizing probes, AppleWorks expanders, RAM disks | `$E1` is ignored unless armed, as all bit-7 values are today (`soft_switch_manager.sv:141-144` V). Probes do not write `$C035` (A). |
| A stray `$C035` write (sound code hitting `$C030-$C03F`) | Arms; harmful only if the byte has bit 3 set while in SHR. Low risk (I). |
| IIgs code ported to the //e | Bit 3 and bit 4 as on the IIgs. Bits 0-2, 5, 6 ignored. `$C035` cannot be read. No `$E0`, no bank `$00` shadowing, no `$C036` bit 4. The display is write-only to the CPU, unlike `$E1` on the IIgs. |
| ONE//e | Uses the same core; untested, as for change 3 (`lazy-mirror-spec.md:255` V). Ship behind the kill switch. |
| II/II+ host | No aux bank 1 in the translation (`README_VIRTUAL_TRANSWARP.md:109` V), so the inhibit never matches. The window's behaviour there is untested. |
| Real VidHD, AppleWin, old Appletini firmware | No `$C035` behaviour and no `$E1`. Software keeps today's path and selects the new one from the feature bits. |

**Emulator: what AppleWin's VidHD would need.**

Today AppleWin stores `$C035` and ignores it (`AW/VidHD.cpp:98` V). It draws SHR through `MemGetAuxPtr` (`AW/VidHD.cpp:134` V), which returns the **active** RamWorks bank for `$4000-$9FFF` and bank 0 only for the 80STORE text and hi-res page 1 windows (`AW/Memory.cpp:1669-1691` V). (check 2026-10-03, precisely: bank 0 for `$0400-$07FF`, and for `$2000-$3FFF` while HIRES is on, when 80STORE+PAGE2 or 80COL is on, `:1677-1686`; every other offset, `$4000-$9FFF` always, comes from the active bank, `:1671-1673`.) That is DOOM's flicker there. `$C073` values at or above the bank count are ignored (`AW/Memory.cpp:2546-2554` V).

1. **Display from aux bank 0 always** (`RWpages[0]`), independent of this design. This alone fixes DOOM's flicker and matches what the Appletini shows today.
2. **A 32 KB display buffer in `VidHDCard`**, which the SHR renderer reads.
   - While bit 3 is 0 (or not armed): the display tracks aux 0. The simple model renders from `RWpages[0]`.
   - On a 0→1 change of the effective inhibit: copy `RWpages[0][$2000-$9FFF]` into the buffer, then render from it. With bit 3 set and bit 4 clear, render `$2000-$5FFF` from aux 0 and `$6000-$9FFF` from the buffer.
   - On 1→0: the IIgs keeps the old bytes until rewritten. The simple model jumps to aux 0 at once; exact behaviour needs a write hook on aux pages `$20-$9F` (AppleWin writes through the `memwrite[]` page table, `AW/Memory.cpp:226`, `:505-508` V; I, medium on the cost).
3. **The window:** in the `$C071`/`$C073` handler, accept `$E1` when armed, keep `g_uActiveBank`, and point the `memwrite[]` entries of aux pages `$20-$9F` at the display buffer while RAMWRT (or 80STORE+PAGE2) selects aux. `memread[]` is untouched. Rebuild in `UpdatePaging`.
4. **The memory API** is Appletini-specific; AppleWin has none. DOOM already has a CPU fallback for machines without it (DOOM commit e3d4649c).

**Period precedent for the bank-0 lock** (added 2026-10-03 after this design round, from a separate verification). On a //e with a RamWorks III or II, the //e's own video (80-column text's aux half, DHGR) always comes from bank 0, whatever `$C073` selects. The verification rates this high confidence; the original 1985 RamWorks is inferred, not documented:

- AE's RamWorks III manual v1.41, p.45: "Only Bank 0 contains the video information. This feature, unique to RamWorks, eliminates a screen flicker problem inherent with some other brands of memory cards when they access other banks". Page 24 says the same for the 80-column and DHGR screens.
- The RamWorks II manual, p.31, says the same.
- US Patent 4,601,018 gives the mechanism: the bank register steers only the CPU phase, and "gate 192 is forced low during the video cycle to force access only to bank 0". AE's RamWorks III brochure cites the patent.
- MAME's `a2eramworks3.cpp:80-83` gives the video a fixed pointer to bank 0.
- AppleWin's hedged comment (`Memory.cpp:1676`) is stale: its maintainer quoted the manual in AppleWin issue #520.

So the Appletini's bank-0 SHR follows the RamWorks line's own rule. The exception is a real VidHD with RamWorks, which is unknown. VidHD builds its picture from snooped writes, and its manual lists neither `$C035` nor `$C073`. If it does not track `$C073`, it takes aux `$2000-$9FFF` writes to any bank as SHR (I). A VidHD, or an emulator modelling one, that honoured `$C035` bit 3 would let the same DOOM protocol work there: shadowing inhibited except while the display is written with bank 0 selected.

## 6. Interaction with the design document's changes

| Change | Interaction |
|---|---|
| Change 1 (bank register in the bank-steer list) | If `$C071`/`$C073` writes join the bank-steer flush, an `$E1` write needs no flush: it changes no motherboard state. Exempt the value, or accept one posted-queue drain per window open. |
| Change 3 (lazy SHR mirror) | Shares `shr_selected_q`. Inhibited and display writes are not lazy: they are never mirrored. Change 3 still speeds up shadowed SHR writes (VidHD-era software). Its `$C073` flush finds no inhibited bytes. |
| Change 5 (zero-page pair) | Optional: pair value `$E1` = the window for that direction. Not needed by DOOM. |
| R4 (API writes that reach the display, `requests.md:147-177` V) | Implemented here as the AUX `$E1` endpoint. R4's "when CPU1 applies the block" is answered: whole, at a frame edge, by the present markers. |
| R9 (bank 127, bit-7 values) | `$E1` becomes the one defined bit-7 value. Question 8. |

## 7. Implementation risks

- **CPU1's record rate is unmeasured.** The lazy spec assumes 1-3 M records a second (`lazy-mirror-spec.md:194` V, A). A 26,880-byte present is then 9-27 ms of CPU1 work, done after the 65C02 has moved on. A frame shows the present 9-47 ms after the request (E, plus up to one PAL frame). S4 divides that by four. Today DOOM already sends about one record per SHR store, 20-26 K a frame (E, section 8), so the load is about the same as now.
- **Ordering.** A present's records follow every record emitted before the hold, because the core is held and its direct leg idle (E3). The classic-speed window leg (C7) needs its bench proof.
- **The present-open cap** trades a frozen screen for one torn frame if a close is lost.

## 8. DOOM GS: use and expected gain

### 8.1 Use

| Where | Today | With this design |
|---|---|---|
| Entering SHR | `$C029` | Also: if STATUS has both feature bits, `$C035 = $18` once (one click), kept in a byte |
| Replay draw (`DOOM/src/native/replay.s:292-295` V: `sta WRAUX`, `$C073` = 0) | aux 0, posted and drained | **unchanged code**; the stores become RAM-only |
| Fuzz and overlay reads (`replay.s:832-864` V: `sta RDAUX` around `aux_fuzz`) | aux 0 | unchanged; aux 0 holds this frame |
| `s2_publish`, palettes, SCBs, automap title | CPU stores into aux 0, drained | unchanged stores; their rows join the frame's present |
| End of frame | — | One CONTROL: COPY AUX 0 `$2000` → AUX `$E1` `$2000`, `$6900` bytes (the view, rows 0-167 = `$2000-$88FF`: `DOOM/docs/MEMORY_MAP.md:55` V), plus descriptors for the status and HUD rows, SCBs and palettes when they changed (at most 16 descriptors a list) |
| Menu (`DOOM/src/native/s2_mvid.s:9-18` V) | save: COPY aux 0 → `S2VIEW`; bands published by CPU; close republishes 32,000 bytes by CPU | save unchanged (aux 0 still holds the screen); bands drawn in aux 0 then presented; close: one present from `S2VIEW` plus a PRIVATE copy back to aux 0 |
| Pictures, intermission, wipe | 32,000 bytes a frame by CPU, about 32 ms of drain (`DOOM/docs/m11-parts/s2wi.md:279` V) | drawn in aux 0, one present a frame |
| Leaving SHR, quitting | — | `$C035 = 0` |
| No API, AppleWin, real VidHD, old firmware | — | today's path, unchanged |

A DOOM invariant follows: **aux 0 always holds the last presented frame plus the frame in progress.** That keeps the menu save, the busy sign's save and restore, and the fuzz correct with no other change. DOOM must check every reader of aux 0 `$2000-$9FFF` against it (open: the busy sign, the wipe's source, dumps).

The present builder needs room: `AMEMLC` is full, 164 of 164 bytes (`DOOM/docs/SPEED.md:376`, `:434` V). It can live in the frame's code area, since the present is made between phases.

DOOM does not need the CPU window (S3) at all. Its whole gain comes from S1 and S2.

### 8.2 Expected gain (E)

**Base.** The card's benchmark on F1.2.2: 6.343 FPS, DRAW 31.3 ms (`DOOM/docs/SPEED.md:415` V). Frame = 1000 / 6.343 = 157.7 ms.

**The draw without the drain.**

- Captured demo frames make 11,657-25,615 screen stores (`DOOM/src/native/README.md:339-351` V). The benchmark is estimated at 20-26 K a frame (E, not measured).
- On demo-01 the draw takes 24.9 ms drained and 14.7 ms without the drain (fastpath), for 25,615 stores (`README.md:340`, `:387-389` V). The drain costs (24.9 − 14.7) / 25,615 = **0.398 µs a store**. (check 2026-10-03) These are a2vm model times, the `f121` and `fastpath` profiles, "not yet measured on the card" (`README.md:324` V), not card measurements. F1.2.2 left the SHR lines unchanged (CALIB page 1 within 0.5% of `f121`; F1.2.2's change is all in the RamWorks lines: `calib.md:218-219` V), so the F1.2.1 drain applies.
- The still frames lose nothing (8.3 against 8.3 ms, `README.md:389` V): not every frame is drain-bound.
- Saving: 20,000 × 0.398 = 8.0 ms to 26,000 × 0.398 = 10.4 ms.
- Not counted: inhibited stores are TURBO fast writes rather than 6-clock recorded writes (`lazy-mirror-spec.md:186` V), about 25,000 × 4 clocks × 7.5 ns ≈ 0.75 ms more (E). Also not counted: the switch writes no longer wait for drains (demo-01's whole replay saves 33.44 − 22.34 = 11.1 ms against the draw's 10.2, `README.md:340` V).

**The present** (26,880 bytes a frame).

- Upper: CALIB's engine rate with the game fit: (46 + 27) µs + (0.038 + 0.022) µs × 26,880 = 0.073 + 1.613 = **1.69 ms** (`calib.md:220`, `SPEED.md:417` V). That rate is PSRAM-bound; a shadow source is faster.
- Lower: 46 µs plus 26,880 records at one a fabric clock (133.3 MHz) = 0.046 + 0.20 = **0.25 ms**, if egress keeps up (A). (check 2026-10-03) Egress does not keep up (section 3.2): about 4,064 records fill the FIFO at one a clock, the other 22,816 go at the egress rate, 23-33 ns each, so the lower bound is 0.046 + 0.53 to 0.76 = **about 0.6-0.8 ms**. The table uses 0.6.

**Net.** (check 2026-10-03: the high-gain column recomputed with a 0.6 ms present; it said 0.25 ms, DRAW 21.2 ms, frame 147.6 ms, 6.78 FPS)

| | Low gain | High gain |
|---|---:|---:|
| Drain saved | 8.0 ms | 10.4 ms |
| Present | −1.7 ms | −0.6 ms |
| DRAW | 31.3 − 6.3 = 25.0 ms | 31.3 − 9.8 = 21.5 ms |
| Frame | 151.4 ms | 147.9 ms |
| FPS | **6.61** | **6.76** |

The uncounted fast-write and switch effects could add about 1-2 ms, about 6.85 FPS (E).

**Full-screen frames.**

- A picture, intermission or wipe frame: 32,000 bytes, about 32 ms of drain today. Present: 0.05 + 32,000 / 133.3 M = 0.29 ms to 0.073 + 0.060 × 32,000 = 1.99 ms. (check 2026-10-03: with the egress bound of section 3.2 the lower figure is 0.046 + 27,936 × 23-33 ns, about 0.7-1.0 ms.)
- Menu close, 46.9 ms today (`DOOM/docs/m11-parts/s2menu1.md:178` V): two 32,000-byte copies from PSRAM at 1.3-2.0 ms each, **about 2.6-4 ms** plus the close's other work (not measured). (check 2026-10-03) The 46.9 ms is a2vm's `f121` model, not the card, and the same close on `fastpath` (no drain) is 43.5 ms (`s2menu1.md:167-171`, `:178` V): the close is mostly not drain. Its gain depends on how much of that other work (the saved rows fetched back into the band, `s2_mvid.s:15-18` V) the present replaces. The restore list copies `$8000` = 32,768 bytes.

**Tearing.** Today a frame boundary that falls mid-draw shows a partial frame (G `apple_cycle_renderer.c:3063-3095`). With presents, the view, the status bar and the palette change at one frame edge. That also removes the colour-before-view difference D1 (`DOOM/docs/SCREENS.md:178` V).

**To confirm before relying on it:** an a2vm profile `f122-shr` with the inhibit and present priced from CALIB, the benchmark's real store count, and the CALIB lines of section 4.

### 8.3 Compared with dropping the mirror alone

If shadowed SHR writes simply never went to the motherboard while SHR is selected (no `$C035` needed), DOOM would save the same 8.0-10.4 ms with **no code change** and no present: about 6.68-6.78 FPS. It would still tear, and every shadowed SHR program would change behaviour. That is change 3 without its reconcile, not a display API; question 10 asks whether to pursue it as well.

## 9. Alternatives rejected

| Alternative | From | Why not |
|---|---|---|
| A readable display RAM (8 RAMB36 fed from the capture FIFO's write side) behind `$C073 = $E1` | the "bank" design | 8 more BRAM tiles at 110 of 140 and 83.95% slices; a new source on the `core_data_in_q` mux next to the shadow (TURBO shadow-RAM family at +0.171 ns) and a write tap on the capture FIFO path (+0.182 ns); a cache veto. Kept: the `$E1` name, arming by `$C035`, the window's address map. Readability is question 4. |
| The zero-page pair as the only CPU path (`zp_wr = $E1`) | the "select" design | Depends on change 5, which is not built, and inherits its rules (`$C069` setup, clear before ROM calls, IRQ saves). Kept: no reconcile, the motherboard left stale, the record address `{1, addr}`, 0 BRAM; the pair value `$E1` as an optional extension. |
| A STALE class with a reconcile at SHR exit, TURBO exit and session end, and a bank sync that steers `$C073` | the "api" design | The most complex firmware of the three, and unnecessary once inhibited writes never reach the motherboard. Kept: the present as a memory-API request, applied whole at a frame edge, and the capture ring as the only path into CPU1's copy. |
| A new space value 2 `DISPLAY` | the "api" design | AUX bank `$E1` gives the CPU and the API one name. |
| Inhibiting main `$2000-$9FFF` in paged SHR | "api", "select" | Not IIgs behaviour; the paged modes have their own A2Li hold. |
| Showing the active RamWorks bank | AppleWin today | Rejected by the owner: it tears, and no period hardware did it. |
| A Videx-style window in `$Cxxx` | period cards | Every `$Cxxx` access is a bus cycle of about 1 µs, as slow as the drain. |
| A page flip to a RamWorks bank | — | Capture covers banks 0 and 1 only (`apple_cycle_capture.sv:67-72` V); scattered PSRAM writes cost 0.504 µs (`calib.md:219` V). |
| Reset value `$08` | the IIgs | VidHD-era software would lose its `$6000-$9FFF` writes. |
| Bit 3 alone inhibiting all of `$2000-$9FFF` | the owner's wording | Differs from the IIgs for `$08` (section 1.2). Question 1. |
| Inhibit outside SHR | the IIgs | The //e's own video and the legacy paged modes depend on aux writes. Question 2. |
| A CPU-only design | — | A CPU present costs 5-7 ms a frame (26,880 bytes at about 0.2-0.27 µs, E) and tears; DOOM's net gain would shrink to 1-5 ms. |

## 10. Open questions for the owner

1. **Bit 4.** Follow the IIgs (`$08` inhibits `$6000-$9FFF` only; `$18` inhibits everything), or make bit 3 alone inhibit all of `$2000-$9FFF`? And should bits 1 and 2 gate the aux pages when bit 4 is 0 (gssquared's notes and code disagree)? Please check against the IIgs Hardware Reference.
2. **Outside SHR.** v1 ignores `$C035` unless SHR is selected. Should the inhibit also apply in DHGR, where the IIgs would apply it?
3. **Reading `$C035`.** Answer reads from the latch inside the card (no click, IIgs read-modify-write works), against the TransWarp rule "no new soft switches" (`README_VIRTUAL_TRANSWARP.md:279` V)?
4. **A readable display.** Is a CPU-readable `$E1` worth 8 BRAM tiles and the timing risk, or is the optional API source path (S5) enough?
5. **Window reads.** v1 reads under `$E1` come from the underlying bank. A readable display later would need a different selector value. Agree to fix this meaning now?
6. **Absorbing `$C035` and `$E1` writes** in the vTW (no bus cycle, no click, no exposure flush) at the cost of a private-serve FSM branch?
7. **The motherboard copy.** Inhibited and display writes never reach the motherboard's aux RAM or PSRAM bank 1, and are never reconciled. Does any consumer depend on them after an SHR session (a //e's own monitor after leaving SHR, the native CPU after handback)?
8. **`$E1` on `$C073`.** Reserve this one bit-7 value permanently (R9), knowing it blocks a future scheme with more than 128 banks from using it?
9. **Present atomicity.** Is "whole, at the next frame edge after CPU1 has applied it" enough, or should the 65C02 be able to wait until a present is shown (a deferred SmartPort response)?
10. **Dropping the mirror for shadowed SHR writes** (section 8.3): pursue it too, for unmodified software, as a variant of change 3?
11. **Kill-switch default.** On by default, given that nothing happens until `$C035` is written?
12. **Native CPU.** Should `$C035` act when the vTW is off (a renderer-side filter on bus records), or stay a vTW feature?
13. **Stage order.** S1+S2 for DOOM first and the CPU window (S3) later, or all at once?
14. **CPU1 measurement first.** Measure CPU1's record rate (the egress counters) before building S2, since it decides whether S4 is needed?

## 11. Not verified

- The IIgs semantics of bits 1, 2 and 4, and the real IIgs reset value: from gssquared, not the Apple IIgs Hardware Reference.
- That a //e clicks on `$C035` writes: from memory and an AppleWin comment.
- That no VidHD-era software or RamWorks probe writes `$C035`.
- What a real RamWorks III does with `$E1`.
- CPU1's record rate, egress throughput during a burst, and the present's real 65C02 cost.
- That the engine's record port and the core's direct leg can never be active together.
- That a read under the window leaves the TURBO write map unfilled for `$2000-$9FFF` (the read and write maps are separate per `FW/README_TURBO.md:47-72`, G). (check 2026-10-03: verified, the map index is `{rw, page_set}`, `vtw_turbo_cache.sv:66`, `:83` V, so a read fills only read entries. A **write** under the window does fill a write entry today: see C6.)
- F1.2.2's BRAM and LUT use after the copy engine.
- Whether `tb_apple_cycle_capture` and `tb_vtw_copy_engine` build and pass under Verilator here.
- DOOM's benchmark store count, and every DOOM reader of aux 0 outside the replay.
