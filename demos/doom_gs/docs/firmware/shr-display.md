# The SHR display as bank `$E1`: IIgs shadowing on the Appletini (specification)

**Revised 2026-10-04: the owner dropped the CPU display window; the memory API is the only way to write the display.** The window (`$C073 = $E1`) is now in section 9 with its reasons. Every other section was revised to match; edits of this revision are marked "(rev 2026-10-04)" where a figure or reference changed.

Written 2026-10-03 from three candidate designs and their two reviews (firmware and software). This is the recommended design; section 9 lists what was taken from each and what was rejected. Nothing was built or simulated, and no firmware file was changed.

**Marks.** **V**: I read it at the cited file:line in this session. **G**: the grounding or review notes of this design round read it; I did not re-read it. **M**: memory or public knowledge, with a confidence. **E**: my estimate from the cited figures. **I**: my inference. **A**: an assumption still to be checked.

**Paths.** FW = `/Users/henri/Documents/Repos/appletini-one` at 3101934 (F1.2.2). DOOM = `.../appletini-software/demos/doom_gs`. AW = `/Users/henri/Documents/Repos/AppleWin/source`. GSQ = `/Users/henri/Documents/Repos/gssquared` at 78125953. `core` means `FW/hdl/apple/vtw_core_top.sv`.

**Numbering.** In the design document "vTW Memory Fast Path: Design", change 1 is "bank register in the bank-steer list" and the lazy SHR mirror is **change 3** (`requests.md:10`, `:38-43` V; change 1 as "`$C071/$C073` on the bank-steer list": `fws1-spec.md:322` V (check 2026-10-03); `requests.md:10`, `:38-43` support only change 3). Change 5 is the zero-page bank pair at `$C069` (`zpbank-spec.md`). This text uses that numbering.

## 0. Summary

**The answer to the owner's question.** The display buffer is **bank `$E1`**, as on the IIgs, and **the memory API is the only way in** (the owner, 2026-10-04): AUX logical bank `$E1` becomes a COPY/FILL destination for `$2000-$9FFF`. One CONTROL list is one **present**: the renderer shows it whole, at one frame edge. The CPU has no path that writes the display directly; `$C071`/`$C073` are unchanged from F1.2.2 (section 9 says why the window was dropped).

The owner's decision is built underneath: **`$C035` SHADOW**, IIgs semantics. With shadowing inhibited, CPU stores to aux bank 0 `$2000-$9FFF` (the IIgs bank `$01`) stay in RAM: no record, no bus cycle, no motherboard mirror. They run as TURBO fast writes.

| Item | Decision |
|---|---|
| The display | The renderer's existing aux copy, `g_aux_bank` `$2000-$9FFF` in CPU1's DDR (`FW/ps_sources/frontend/apple_cycle_egress.h:37-39` V). It is fed only by capture records (`apple_cycle_egress.c:270-298` V). No new RAM. |
| `$C035` | Write-only, latched by the vTW core from its own bus write. Honoured only while SHR is selected. Bit 3 inhibits aux `$6000-$9FFF`; bits 3 **and** 4 inhibit aux `$2000-$5FFF` (the IIgs rule, section 1.2). Other bits are stored and ignored. Reset value `$00`, not the IIgs's `$08`. |
| Arming | Nothing changes until software writes `$C035` once after reset. VidHD-era software never does, so for it F1.2.2 behaviour is exact. |
| Inhibited writes | Shadow BRAM only, like a PRIVATE memory-API write today. They never reach the display or the motherboard, and nothing reconciles them later. |
| CPU display window | None (rev 2026-10-04). `$E1` on `$C071`/`$C073` is ignored, as every bit-7 value is today (`FW/hdl/apple/soft_switch_manager.sv:141-144` V). |
| API display endpoint | AUX bank `$E1`, destination only, `$2000-$9FFF`, flags 0. The copy engine streams the bytes into the capture FIFO. The PS brackets each CONTROL list that writes `$E1` with present markers (check 2026-10-04: was "each CONTROL list"; section 3.4 emits them around the `$E1` descriptors only), and CPU1 does not rebuild the SHR frame while one is open. |
| Reading the display | Not in v1. The program reads its RAM copy (aux 0). An API source path is a later, optional stage (section 3.6). |
| Cost | About 110-185 LUTs and 58 FFs, **0 BRAM** (E; section 3.3, rev 2026-10-04, was 150-240 and 60 with the window). About 115-195 lines of PS code (E; the sum of section 3.4's rows, rev 2026-10-04, was 120-205). |
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

(rev 2026-10-04: the display-window bit and the "underlying bank" are gone; the RamWorks bank is today's, untouched.)

Everything resets on power-up, Apple RES# (Ctrl-Reset), session start and end, and a CORE_RUN drop: the `core_res_n` term, as in `zpbank-spec.md:242-256` (V). It also resets when the kill switch clears. The display contents survive Apple RES, as `g_aux_bank` does today.

### 2.2 Registers

**`$C035` SHADOW, write.**

- Latches all 8 bits and sets ARMED.
- The write still goes out as a real bus cycle, so capture records it for the renderer as today (`apple_cycle_capture.sv:74-79` V). It stays an exposure access (`core:1399` V); that flush is correct, because bytes written before the switch keep their old class. Absorbing it is question 5 (check 2026-10-04: that question had lost its reference with the `$C073` table).
- On a //e, `$C030-$C03F` is the speaker, so each write clicks once (M, medium-high; AppleWin says the same: "Writes to $C03x addresses will still toggle the speaker, even with a VidHD present", `AW/Memory.cpp:643-652` V). Write it rarely: entering and leaving SHR.

**`$C035`, read.** Not decoded. A read is a bus cycle that clicks the speaker and returns the floating-bus byte (`core:1104-1107` V; the scanner-byte return for `$C030-$C05F` reads is `core:1255-1270` V, check 2026-10-03). Keep a copy in memory. IIgs code that does `LDA SHADOW / ORA #$08 / STA SHADOW`, as upstream's automap does (`DOOM/build/upstream/src/iigs/am_map65.s:1105-1109` V), must be rewritten. Answering reads is question 3.

**Effective inhibit.**

```
inh_hi  = ARMED && SHR selected && SHADOW[3]                  ; aux $6000-$9FFF
inh_lo  = ARMED && SHR selected && SHADOW[3] && SHADOW[4]     ; aux $2000-$5FFF
```

"Aux" means **physical bank 1**, after RAMRD/RAMWRT, 80STORE/PAGE2/HIRES and `$C073`. Main is never inhibited (IIgs bit 3 concerns bank `$01` only), so the paged-SHR second field in main and the A2Li holes behave as today. Outside SHR, `$C035` has no effect (question 2).

**`$C071` / `$C073`.** Unchanged from F1.2.2 (rev 2026-10-04). `$00-$7F` selects the bank while `ramworks_en` is set (check 2026-10-04: the decode is gated on it, `soft_switch_manager.sv:141` V); every `$80-$FF` value, `$E1` included, is ignored and the bank kept (`soft_switch_manager.sv:141-144` V). The design adds no state, decode or meaning to these addresses.

### 2.3 What each access reaches

| Access | RAM (shadow) | Display | Motherboard |
|---|---|---|---|
| CPU store to aux 0 `$2000-$9FFF`, not inhibited | yes | yes, one record | yes (posted or coalesced, as F1.2.2) |
| CPU store to aux 0, **inhibited** | yes; TURBO fast write except page `$9D` | **no** | **no, ever** |
| Any other CPU store or load | as F1.2.2 | as F1.2.2 | as F1.2.2 |
| Memory API PRIVATE write to aux 0 | yes | no | no (unchanged, `README_MEMORY_API.md:179-191` V) |
| Memory API write to **AUX `$E1`** | **no** | yes, inside one present | no |
| SmartPort block read into aux `$2000-$9FFF`, inhibited | yes | no | no (section 3.4; rev 2026-10-04, was "3.5") |
| Native motherboard CPU (vTW off) | motherboard | as today: bit 3 has no effect | — |

(rev 2026-10-04: the window rows are gone. No CPU access reaches the display without also writing aux 0: the display is changed by the CPU only through a shadowed store, and otherwise only by a present.)

Consequences:

- **The CPU cannot read the display.** A program reads its RAM copy, aux 0 (section 2.7).
- **Turning shadowing back on copies nothing.** Bytes written while inhibited reach the display only by a present or by being written again, as on the IIgs.
- **Inhibited writes and presents leave the motherboard's aux RAM, and PSRAM bank 1 when the Appletini provides aux, stale for good.** This matches the TransWarp contract: "motherboard RAM is deliberately stale outside the video windows" (`FW/README_VIRTUAL_TRANSWARP.md:112` V), and Ctrl-Reset handback returns the machine cold (`:116` V). It is the same staleness a PRIVATE write leaves today. Question 6 asks the owner to confirm.

### 2.4 Mode interactions

| With | Rule |
|---|---|
| `$C029` | Entering SHR with `$18` already latched starts the inhibit at once. Leaving SHR stops it; nothing is copied. Inhibited bytes in aux `$2000-$5FFF` then show stale in DHGR, on the //e's own video and on the Appletini's, until rewritten. The API endpoint works in every mode, because the renderer builds every mode from `g_aux_bank`; `$E1:$2000` written with SHR off shows in DHGR on the Appletini's output only. |
| SCBs `$9D00-$9DC7`, palettes `$9E00-$9FFF` | Part of the range. While inhibited they change on screen only when presented. A present that carries them changes them together with the pixels. |
| `$9DC8-$9DFF` | Stays software-reserved. `$9DF8` (paged control) and `$9DFC` (`SHR4`/`3200` magic) change the renderer's mode (G `apple_cycle_renderer.c:1434-1435`, `:1504-1515`). The core's `$9DF8` tracker (`core:1877-1882` V) follows the **display**: it updates on an aux 0 `$9DF8` write that is not inhibited and on an API write to `$E1:$9DF8`, and ignores inhibited writes. |
| Paged SHR (SHR4, 3200) | Main second field unchanged. |
| A2Li | The holes are in main (`$0878-$087F`, `$4078-$407F`), never inhibited; the policy keeps them immediate (G `vtw_video_policy.sv:33-37`). |
| ALTZP, language card, interrupts, ROM, ProDOS, SmartPort calls | No new rule (rev 2026-10-04: the rows for the window are gone). The `$C035` latch can stay set across them; an inhibited store from a handler stays in RAM like any other (I). |
| Change 5's pair, if built | No interaction (rev 2026-10-04): this design defines no pair value, and `zpbank-spec.md:29`'s `$80-$FF` reservation (V) is left as it is. |

### 2.5 Memory API 1.1

Major version stays 1; 1.0 lists stay valid. A 1.0 caller checks the signature, the major version, the descriptor size, the feature bits it requires and availability (`README_MEMORY_API.md:36-38` V; `example.s:25-37` checks the signature, the major and availability), so new feature bits and a new minor do not disturb it (check 2026-10-03).

| Field | Rule |
|---|---|
| Destination space 1 (AUX), bank `$E1` | **The display.** `$2000 <= address`, `address + length <= $A000`. Flags must be 0 (PRIVATE has no meaning there). COPY and FILL. |
| Source space 1, bank `$E1` | Invalid in 1.1 (RANGE `$63`). Reserved for the optional stage in section 3.6. |
| Feature bits, STATUS offset 8 | New bit 4 (`$10`) `DISPLAY`: the AUX `$E1` endpoint. New bit 5 (`$20`) `SHADOW`: the `$C035` inhibit (rev 2026-10-04: no longer also the CPU window). Today's bits are COPY 1, FILL 2, PRIVATE 4 (`FW/ps_sources/frontend/memory_api.h:23-25` V); change 5 claims 8 (`zpbank-spec.md:301` V). Both new bits require the bitstream's capability bit, the kill switch on and the capture egress enabled. |
| Present | All `$E1` destinations of one CONTROL list form one present. CPU1 does not rebuild the SHR frame between its first and last byte. Other descriptors in the same list run in order as today. |
| Errors | On any refusal or abort after the first `$E1` byte, the present is still closed. The display may then hold part of the list. |
| Old firmware | F1.2.2 refuses AUX bank `$E1` with RANGE (`README_MEMORY_API.md:163-165` V; the code: `memory_api.c:43-47` V, bank > 126), so a caller learns the feature is absent before anything is written: every descriptor is validated before the hold (`memory_api.c:116-153` V) (check 2026-10-03). |

`memory_api.inc` gains `AMEM_DISPLAY = $E1`, `AMEM_FEATURE_DISPLAY = $10` and `AMEM_FEATURE_SHADOW = $20`.

### 2.6 Detection

Use the memory API STATUS (`FW/software/memory_api/example.s:16-41` V), then test the two feature bits. There is no CPU-only probe (rev 2026-10-04): the CPU can neither write nor read the display, and `$C035` cannot be read back (section 2.2), so STATUS is the only test.

```
        ; capabilities: the 32-byte STATUS block (example.s, probe_params)
        lda capabilities+8              ; feature bits, low byte
        and #AMEM_FEATURE_DISPLAY|AMEM_FEATURE_SHADOW
        cmp #AMEM_FEATURE_DISPLAY|AMEM_FEATURE_SHADOW
        bne old_path                    ; F1.2.2 or older, AppleWin, VidHD: today's path
```

### 2.7 Examples (ca65, 65C02)

Constants: `RAMRDOFF = $C002`, `RAMRDON = $C003`, `RAMWRTOFF = $C004`, `RAMWRTON = $C005`, `NEWVIDEO = $C029`, `SHADOW = $C035`. `SP_ENTRY` is the Appletini slot-7 SmartPort entry (`$C70D` in `example.s:12` V; discover it in a general caller). The SmartPort entry writes main `$07F8`; save it as `example.s:18-20` does.

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

(check 2026-10-04: the parameter block, `AMEM_BEGIN` and `AMEM_COPY_RECORD`'s argument order match `FW/software/memory_api/memory_api.inc` and `example.s:63-71` (V). Every `$E1` range ends within section 2.5's limit: `$2000 + $7D00 = $9D00`, `$9D00 + $C8 = $9DC8`, `$9E00 + $200 = $A000`; flags are 0.)

(rev 2026-10-04: the "presenting it with the CPU" example, a copy loop through the `$C073 = $E1` window, is removed with the window. The API present above is the only present.)

**Changing a few display bytes** (palette 0, colour 15 to white, while inhibited). Write the RAM copy, then present just those bytes. (rev 2026-10-04: replaces the window example "writing the display directly".)

```
        sta RAMWRTON            ; aux 0, $C073 = 0
        lda #$FF
        sta $9E1E               ; colour 15, low byte: green and blue (RAM only)
        lda #$0F
        sta $9E1F               ; high byte: red
        sta RAMWRTOFF
        ; then CONTROL with pal_list, as in the present above
pal_list:
        AMEM_BEGIN 1
        AMEM_COPY_RECORD AMEM_AUX, 0, $9E1E, AMEM_AUX, AMEM_DISPLAY, $9E1E, $0002, 0
```

A FILL to `$E1` writes the display without touching RAM; this colour needs two, one a byte value (`AMEM_FILL_RECORD AMEM_AUX, AMEM_DISPLAY, $9E1E, 1, $FF, 0` and `AMEM_FILL_RECORD AMEM_AUX, AMEM_DISPLAY, $9E1F, 1, $0F, 0`; check 2026-10-04: the text showed only the first, which leaves red unchanged; the macro's argument order checked against `FW/software/memory_api/memory_api.inc:49-55`, V 2026-10-04), but then aux 0 no longer equals the display, which breaks the rule below. Shadowing on, the two stores alone change the display, as F1.2.2 does.

**Reading it back.** v1 has no read path to the display. A program reads its RAM copy, which equals the display when every display byte also went through aux 0: shadowing on, or drawn in aux 0 and presented.

```
        sta RAMRDON             ; $C073 = 0
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

(rev 2026-10-04: the window's items, old C3 `disp_q`, C6 `xl_is_display` and C7 the display record leg, are removed, and the rest renumbered: old C4, C5, C5b, C8, C9 are now C3, C4, C4b, C5, C6. Section 9 lists what the window would have needed. What remains is the inhibit alone; C3 and C4 were re-checked against the core on 2026-10-04.)

| # | Change | Anchor |
|---|---|---|
| C1 | `shr_selected_q`: decode `$C029` writes from the registered tuple at `X_ROUTE`, value `cycle_wdata_q[7:6]==2'b11`, reset as section 2.1 and on `!fake_shr_allowed`. **Shared with change 3**, which specifies the same register (`lazy-mirror-spec.md:26-32` V). New input `fake_shr_allowed` from `apple_top.sv:1033` (V). | beside `:1877` |
| C2 | `shadow_q[7:0]`, `shadow_armed_q`: latch on `X_ROUTE && xl_is_bus && xl_is_write && cycle_addr_q==16'hC035`, the same pattern as the `$9DF8` tracker. Derive `inh_lo_q`, `inh_hi_q` as registers (section 2.2), so no new decode sits on the cycle path. | `:1877-1882` V |
| C3 | `xl_inhibited = !xl_is_bus && xl_shadow_valid && xl_is_write && xl_decoded[23:16]==8'd1 && (cycle_addr_q in $6000-$9FFF ? inh_hi_q : cycle_addr_q in $2000-$5FFF ? inh_lo_q : 0) && !xl_is_overlay_post`. `xl_is_posted` gains `&& !xl_inhibited`. Inhibited writes then take the plain shadow path: shadow written at `X_ROUTE` (`core_shadow_issue`, `shadow_a_we`: `:1307-1308`, `:1320` V), no post request (`core_post_req` needs `xl_is_posted`, `:1347-1348` V), so no `X_POST_STALL`, no TURBO record (`video_record_valid` comes only from `X_POST_STALL`, `:1370-1371`, `:1379` V) and no coalescer byte; the FSM goes to `X_MEM_CAPTURE` as for any private write (`:2037-2042` V). No new FSM branch. TURBO fast-write permission follows from `turbo_map_fast_write = !xl_is_posted && ...` unchanged (`:1218-1219` V), so an inhibited page fills its map entry with the fast bit set. | `:565-569`, `:1218-1219` V |
| C4 | **Must-fix: invalidation** (re-checked 2026-10-04; still needed without the window). `turbo_invalidate` gains `({inh_lo_q, inh_hi_q} != turbo_inh_q)`, with `turbo_inh_q` registered beside `turbo_overlay_q` (`:1186-1201` V). Fast-write permission is computed at fill time (`:1218-1219` V) and stored in each map entry (`vtw_turbo_cache.sv:96`, read back as `write_fast` at `:79` V), and a write hit needs only `write_valid && write_fast` and a page tag (`:1240-1242` V). An entry filled while inhibited has the fast bit set (C3). Without this term it would survive an inhibit release (`$C035` back to 0, or leaving SHR with `$C029`), and later stores, which must now be recorded and posted, would complete as TURBO fast writes with no record and no motherboard write. Nothing invalidates on those writes today: neither changes `turbo_mapping`, and "Cxxx accesses always take the original route" (`:1202-1211` V). The other direction (0→1) is safe without the term, since entries filled while shadowed carry fast = 0 and miss (I); comparing both bits covers both. Cost per change of the effective inhibit: one cache refill, like any `$C073` bank change today (`:1185`, `:1206-1211` V). | `:1202-1211` V |
| C4b | `turbo_mapping` at `:1185` is `wire [18:0]` (V). C4 keeps the new state out of `TranslateState`, so that width does not change. | `:1185` V |
| C5 | `$9DF8` tracker: add `!xl_inhibited`; also update on the engine's `$E1:$9DF8` byte (input from 3.2). (rev 2026-10-04: the window term is gone.) Page `$9D` is never a fast write (`:1218-1219` V), so every aux `$9DF8` store reaches the tracker at `X_ROUTE`. | `:1877-1882` V |
| C6 | Debug: `shadow_q`, ARMED, `inh_lo_q`, `inh_hi_q` in a read-only card-control word for `vtw status`. | — |

Not changed: `globals.sv translate_apple_addr`, `soft_switch_manager.sv`, `vtw_video_policy.sv`, the coalescer, the bank sync, the motherboard trackers, and (rev 2026-10-04) the `xl_is_ramworks` routing (`:643-644` V), `turbo_map_fill` (`:1212-1213` V), the shadow write enable (`:1307-1308`, `:1320` V; check 2026-10-04: the citation had read as if it were in `:1352-1384`) and the record leg (`:1352-1384` V), which the window would have changed. The exposure list (`:1390-1400` V) is unchanged; with SHR writes inhibited, a `$C073` write in DOOM finds nothing deferred to flush.

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
| C1, C2, C6 latches and decode | 17-30 | 24 | 0 |
| C3-C5 inhibit classification, invalidation term, tracker gate | 14-28 | 2 | 0 |
| E1-E2 engine display destination | 50-80 | 30 | 0 |
| E3-E4 direct-port mux, present marker | 30-45 | 2 | 0 |
| **Total** | **about 110-185** | **58** | **0** |

(rev 2026-10-04, E.) The 2026-10-03 table had the latches row (with old C3) at 20-35 LUT, 25 FF; the classification row (old C4-C6) at 25-45 LUT, 4 FF; and a C7 record-leg row at 20-35 LUT, 2 FF; the E rows are unchanged. Without the window:

- Latches: minus `disp_q` (1 FF) and its `$C071`/`$C073` decode with an 8-bit compare against `$E1` (about 3-5 LUTs): 20-35 − 3-5 = **17-30 LUT**, 25 − 1 = **24 FF**.
- Classification: minus old C6's `xl_is_display` (an address range, a bank test, and gate terms on `turbo_map_fill`, the shadow write enable, `xl_is_posted` and the routing before `xl_is_ramworks`: about 11-17 LUTs): 25-45 − 11-17 = **14-28 LUT**. FFs: the invalidation snapshot `turbo_inh_q` is 2 bits (was `turbo_dsp_q`, 3 bits, in a 4-FF row): **2 FF**.
- Record leg: removed, −20-35 LUT, −2 FF.
- Total LUT: 17 + 14 + 50 + 30 = 111 to 30 + 28 + 80 + 45 = 183. Total FF: 24 + 2 + 30 + 2 = 58 (was 25 + 4 + 2 + 30 + 2 = 63, "about 60").
- The window's share was therefore about 34-57 LUTs (3 + 11 + 20 to 5 + 17 + 35) and 5 FFs.

Budget: 110 of 140 BRAM tiles, 36,086 of 53,200 LUTs, 83.95% of slices occupied (`FW/README_VIVADO_RUNTIME_AUDIT.md:101-106` V; that audit predates F1.2.2's copy engine, A).

**Timing.** C3 adds a term to `xl_is_posted`, on the admission family. The recorded margins are thin: the TURBO shadow-RAM family at +0.171 ns and the capture FIFO at +0.182 ns against a +0.200 ns gate (`FW/docs/FABRIC_TIMING_MARGIN_PLAN.md:2192-2194` V; the column meanings were not re-read, A). (check 2026-10-03) Those two figures are the table's "F1.1.4 baseline" column (`:2186` V); the second trial of the same day shows +0.273 and +0.546 ns, and the +0.200 ns gate is "the then-current" one of the September 25 trials (`:2072` V; the standing rule is a +0.150 ns nominal floor, `:2055` V). No routed figure for F1.2.2 is recorded there. Every new operand is a register (`inh_*_q`, the registered tuple). Without the window, `xl_is_posted` gains one term, not two, and `turbo_map_fill` and the shadow write enable gain none (rev 2026-10-04). Fallback: compute `xl_inhibited` one stage earlier, at `X_CAPTURE`, from `core_addr` and the registered state, as change 5 does for `cycle_zpb_redirect_q` (`zpbank-spec.md:311` V). The mux in E3 should be registered.

### 3.4 PS (ARM) changes

| File | Change | Size (E) |
|---|---|---:|
| `memory_api.h`, `memory_api.c` | AUX bank `$E1` as a destination (section 2.5), feature bits 16 and 32, minor version 1, `memory_api.inc` constants | 40-60 lines |
| `memory_api_hw.c` | Physical `$E1xxxx` on the engine path only; the ARM DMA fallback refuses it (`hw_dma` rejects ≥ `0x800000`, `:150-156` V). Emit present-open before the first `$E1` descriptor and present-close after the last, on every exit path, after the engine reports DONE. | 30-50 lines |
| `apple_cycle_egress.c` | Kind 3: call a renderer hook with open or close. On a gap or resync, force the present closed. | 10-20 lines |
| `apple_cycle_renderer.c` | In the SHR branch (`:3063-3095` V; check 2026-10-03, was `:3062-3090`), skip the rebuild while a present is open, counting it like the settle skip (`:3073-3082` V). Cap: after 8 frame markers with a present open, rebuild anyway, so a lost close cannot freeze the screen. | 15-25 lines |
| `smartport_service.c`, `smartport_card.sv` | Add the inhibit bits to the switch snapshot (as change 5 does, `zpbank-spec.md:277-288` V). Skip `arm_post` for inhibited aux `$2000-$9FFF` bytes (SmartPort posts video-window bytes today: `core:238-241` V). (rev 2026-10-04: the window's span fallback is gone, 20-40 → 15-30, E.) | 15-30 lines |
| `vtw_service.c` | `vtw: shadow=$18 armed=1 shr=1 inh=lo,hi` | 5-10 lines |

Sum (rev 2026-10-04): 40 + 30 + 10 + 15 + 15 + 5 = 115 to 60 + 50 + 20 + 25 + 30 + 10 = 195 lines (E).

### 3.5 What is not done

- No reconcile of inhibited bytes to the motherboard: not at SHR exit, not at session end, not on `$C073` writes (section 2.3).
- No readable display RAM (section 9, question 4).
- No CPU path to the display, read or write (rev 2026-10-04; section 9).
- No IIgs bank `$00`/`$E0` shadowing: main is never inhibited.
- No effect on the native motherboard CPU.

### 3.6 Stages

Each stage is one full build against +0.200 ns.

| Stage | Content | Gives |
|---|---|---|
| S0 | C1, C2, C6, kill switch; state latched but unused; PS: `vtw_service.c`'s status line (3.4) | Equivalence with F1.2.2; status line |
| S1 | C3, C4, C5: the inhibit; PS: `smartport_service.c`/`smartport_card.sv`'s inhibit snapshot and `arm_post` skip (3.4) | IIgs shadowing; the DOOM speed-up needs S1 and S2 together |
| S2 | E1-E4 and the PS present: `memory_api*`, `apple_cycle_egress.c`, `apple_cycle_renderer.c` (3.4) | The API endpoint, tear-free presents |
| S3 (optional) | Packed records (kind 4, 4 bytes a record) for engine presents | CPU1 work per present ÷4, if CPU1 is the bound |
| S4 (optional) | AUX `$E1` as a source: CPU0 asks CPU1 to apply every record up to the hold, clean the range and acknowledge, then reads `g_aux_bank` | Reading the display back, saving the true screen |

(rev 2026-10-04: the old S3, the CPU window, is dropped; old S4 and S5 are now S3 and S4.) S1 without S2 is safe but useless: inhibited frames never show, and with no window the API is the only way to show them. Ship S1 and S2 together.

## 4. Verification

The benches that build and pass under Verilator on this Mac: `tb_vtw_turbo`, `tb_vtw_video_policy`, `tb_vtw_video_coalescer`, `tb_vtw_video_bank_sync` and others; `tb_vtw_system` builds but fails 5 checks, cause unknown (memory note `appletini-firmware-simulation`, F1.2.1; M, high). Whether `tb_apple_cycle_capture` and `tb_vtw_copy_engine` pass here is not known. Timing needs Vivado, which this Mac does not have.

| Bench (script) | Cases |
|---|---|
| `hdl/sim/tb_vtw_turbo.sv` (`scripts/test_vtw_turbo.py`) | Kill switch off, or never armed: traces identical to F1.2.2 (posted count, records, perf counters). `$18` in SHR: a 256-byte aux burst then `lda $C000` gives 0 posted writes, 0 records, no video wait. `$08`: `$2000-$5FFF` still recorded and posted, `$6000-$9FFF` not. Inhibit outside SHR: no effect. With `$C035 = $18` latched, warm fast-write entries for aux page `$40`, then `$C035 = 0`: the next store is recorded and posted (C4). Leave SHR with entries warm: same. `$C035 = $18` with entries warm from shadowed stores: the next store misses, refills fast, and is not recorded. `$C073 = $E1`, armed or not: ignored, the bank kept, traces as F1.2.2 (rev 2026-10-04: replaces the window cases). Page `$9D` inhibited: never fast, shadow only (C3). `$9DF8` shadowed and inhibited (C5). Apple RES, CORE_RUN drop, kill switch: all state cleared. |
| `hdl/sim/tb_apple_cycle_capture.sv` | Direct records from the engine port and the core port in FIFO order with physical records; kind 3 markers; behaviour at the 4064 threshold. |
| `hdl/sim/tb_vtw_copy_engine.sv` (`scripts/test_vtw_copy_engine.py`) | `$E1` destination from shadow and from PSRAM, unaligned ends, FILL: the record stream equals the source bytes in order, and shadow BRAM is untouched. Abort mid-copy: `completed` equals records accepted. Back-pressure from `rec_ready`. |
| `hdl/sim/tb_apple_cycle_egress.sv` (`scripts/test_apple_cycle_egress.py`) | Kind 3 passes through the ring unchanged. |
| `hdl/sim/tb_vtw_video_policy.sv`, `tb_vtw_video_coalescer.sv`, `tb_vtw_video_bank_sync.sv` | Unchanged modules: must stay green. |
| `hdl/sim/tb_vtw_system.sv` | The translation monitor stays green (translation is unchanged). Needs XSim or a fix for the 5 Verilator failures first. |
| `scripts/test_memory_api.py`, `test_memory_api_hw.py` | Bank `$E1` limits; flags must be 0; source `$E1` refused; markers emitted on success, refusal and abort; feature bits only with the capability bit. |
| `scripts/test_apple_cycle_egress.py`, renderer tests | Present open across a frame marker: the frame is skipped; the cap forces a rebuild after 8; a gap closes the present. |
| `scripts/test_smartport_service.py` | Inhibit bits in the snapshot; inhibited video bytes not posted. |

**On the card.** New CALIB page lines (DOOM's `CALIB.hdv`): `INH SEQ` and `INH COL` (the `SHR SEQ`/`SHR COL` loops of `calib.md:69-70` with `$18` latched; expected near plain aux RAM speed), `PRES 26880` and `PRES 32000` (the API present's 65C02 time), and the egress counters during a present (`lazy-mirror-spec.md:198-203` V) to measure CPU1's record rate. A visual check: a program alternating two full screens by present shows no torn frame.

**In a2vm.** a2vm needs a model of the inhibit and the present, priced from the CALIB lines, before DOOM's gain can be checked (section 8).

## 5. Compatibility

| Software | Effect |
|---|---|
| VidHD-era //e SHR software | Never writes `$C035` (A, medium: VidHD's manual lists no `$C035`, G `vidhd.txt:203-216`), so it is never armed: F1.2.2 behaviour exactly. |
| RamWorks sizing probes, AppleWorks expanders, RAM disks | Unaffected (rev 2026-10-04): `$C071`/`$C073` are unchanged, and `$E1` is ignored as all bit-7 values are today (`soft_switch_manager.sv:141-144` V), armed or not. A probe that also writes `$C035` (none known, A) could only inhibit aux stores in SHR. |
| A stray `$C035` write (sound code hitting `$C030-$C03F`) | Arms; harmful only if the byte has bit 3 set while in SHR. Low risk (I). |
| IIgs code ported to the //e | Bit 3 and bit 4 as on the IIgs. Bits 0-2, 5, 6 ignored. `$C035` cannot be read. No `$E0`, no bank `$00` shadowing, no `$C036` bit 4. The CPU cannot address `$E1` at all, unlike the IIgs: its `MVN` to `$E1` becomes a memory-API COPY (section 0). |
| ONE//e | Uses the same core; untested, as for change 3 (`lazy-mirror-spec.md:255` V). Ship behind the kill switch. |
| II/II+ host | No aux bank 1 in the translation (`README_VIRTUAL_TRANSWARP.md:109` V), so the inhibit never matches. |
| Real VidHD, AppleWin, old Appletini firmware | No `$C035` behaviour and no `$E1`. Software keeps today's path and selects the new one from the feature bits. |
| A future scheme with more than 128 banks | Unaffected (rev 2026-10-04): `$E1` on `$C073` is no longer reserved. This design defines no bit-7 value, so R9 is left open (section 6). |

**Emulator: what AppleWin's VidHD would need.**

Today AppleWin stores `$C035` and ignores it (`AW/VidHD.cpp:98` V). It draws SHR through `MemGetAuxPtr` (`AW/VidHD.cpp:134` V), which returns the **active** RamWorks bank for `$4000-$9FFF` and bank 0 only for the 80STORE text and hi-res page 1 windows (`AW/Memory.cpp:1669-1691` V). (check 2026-10-03, precisely: bank 0 for `$0400-$07FF`, and for `$2000-$3FFF` while HIRES is on, when 80STORE+PAGE2 or 80COL is on, `:1677-1686`; every other offset, `$4000-$9FFF` always, comes from the active bank, `:1671-1673`.) That is DOOM's flicker there. `$C073` values at or above the bank count are ignored (`AW/Memory.cpp:2546-2554` V).

1. **Display from aux bank 0 always** (`RWpages[0]`), independent of this design. This alone fixes DOOM's flicker and matches what the Appletini shows today.
2. **A 32 KB display buffer in `VidHDCard`**, which the SHR renderer reads.
   - While bit 3 is 0 (or not armed): the display tracks aux 0. The simple model renders from `RWpages[0]`.
   - On a 0→1 change of the effective inhibit: copy `RWpages[0][$2000-$9FFF]` into the buffer, then render from it. With bit 3 set and bit 4 clear, render `$2000-$5FFF` from aux 0 and `$6000-$9FFF` from the buffer.
   - On 1→0: the IIgs keeps the old bytes until rewritten. The simple model jumps to aux 0 at once; exact behaviour needs a write hook on aux pages `$20-$9F` (AppleWin writes through the `memwrite[]` page table, `AW/Memory.cpp:226`, `:505-508` V; I, medium on the cost).
3. **The memory API** is Appletini-specific; AppleWin has none, and with no CPU window (rev 2026-10-04) it is the only way to write the buffer of item 2. Without an API model, item 2 alone can only follow aux 0. DOOM already has a CPU fallback for machines without the API (DOOM commit e3d4649c).

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
| Change 1 (bank register in the bank-steer list) | None (rev 2026-10-04): this design gives `$C071`/`$C073` no new value, so nothing needs exempting from the bank-steer flush. |
| Change 3 (lazy SHR mirror) | Shares `shr_selected_q`. Inhibited writes are not lazy: they are never mirrored, and API presents never touch the motherboard. Change 3 still speeds up shadowed SHR writes (VidHD-era software). Its `$C073` flush finds no inhibited bytes. |
| Change 5 (zero-page pair) | None (rev 2026-10-04): with no window there is no pair value `$E1`; the pair's `$80-$FF` reservation (`zpbank-spec.md:29` V) stays its own. |
| R4 (API writes that reach the display, `requests.md:147-177` V) | Implemented here as the AUX `$E1` endpoint, now the only way to write the display. R4's "when CPU1 applies the block" is answered: whole, at a frame edge, by the present markers. |
| R9 (bank 127, bit-7 values) | Unaffected (rev 2026-10-04): `$E1` on `$C073` stays an ignored bit-7 value and needs no reserving. `$E1` is now only a memory-API bank number, free there because F1.2.2's API refuses AUX banks above 126 (`memory_api.c:43-47` V, section 2.5). |

## 7. Implementation risks

- **CPU1's record rate is unmeasured.** The lazy spec assumes 1-3 M records a second (`lazy-mirror-spec.md:194` V, A). A 26,880-byte present is then 9-27 ms of CPU1 work, done after the 65C02 has moved on. A frame shows the present 9-47 ms after the request (E, plus up to one PAL frame). S3 divides that by four (check 2026-10-04: said S4, the old number of the packed-records stage). Today DOOM already sends about one record per SHR store, 20-26 K a frame (E, section 8), so the load is about the same as now.
- **Ordering.** A present's records follow every record emitted before the hold, because the core is held and its direct leg idle (E3). (rev 2026-10-04: with no window there is no classic-speed record leg to prove.)
- **The invalidation term (C4).** The inhibit's one must-fix. Missing it fails silently: after an inhibit release, TURBO stores to a page warmed while inhibited skip their record and their motherboard write, so the screen misses them. The bench case in section 4 covers it.
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

DOOM never used the CPU window (the old S3), so dropping it changes nothing here (rev 2026-10-04). Its whole gain comes from S1 and S2, and section 8.2 stands as written.

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

If shadowed SHR writes simply never went to the motherboard while SHR is selected (no `$C035` needed), DOOM would save the same 8.0-10.4 ms with **no code change** and no present: about 6.68-6.78 FPS. It would still tear, and every shadowed SHR program would change behaviour. That is change 3 without its reconcile, not a display API; question 8 asks whether to pursue it as well.

## 9. Alternatives rejected

| Alternative | From | Why not |
|---|---|---|
| **The CPU display window**: `$C073 = $E1`, armed by `$C035`, write-only; stores to aux `$2000-$9FFF` become one direct capture record each (the 2026-10-03 design's old C3, C6, C7 and stage S3) | the 2026-10-03 design | (rev 2026-10-04) **The owner's decision, 2026-10-04: "drop the CPU window, API only".** The check of 2026-10-03 also showed it was not cheap. In TURBO every window store after the first one to a page would land in aux-0 shadow RAM, not the display: the first store fills a TURBO write-map entry (`turbo_map_fill`, `core:1212-1213` V) whose fast bit is `!xl_is_posted && ...` (`:1218-1219` V), 1 for an unposted window store, and a write hit needs only that bit and a page tag (`:1240-1242` V). The fast bit (or the fill), the shadow write enable (`core_shadow_issue`, `shadow_a_we`, `:1307-1308`, `:1320` V) and `xl_is_posted` would each have needed a display term. Other costs: routing before `xl_is_ramworks`, since with a RamWorks bank of 1 or more the write would otherwise go to PSRAM whenever `ramworks_en` is set (`:643-644` V); a record leg at every speed that waits at classic speed for the posted queue (`:1352-1384` V); about 34-57 LUTs, 5 FFs and 5-10 PS lines (section 3.3, E); `$E1` reserved on `$C073` for good (R9); a probe hazard on a real RamWorks III (I, medium); and a CPU present that tears and costs 5-7 ms a frame (the CPU-only row below). DOOM never used it (section 8.1). |
| A readable display RAM (8 RAMB36 fed from the capture FIFO's write side) behind `$C073 = $E1` | the "bank" design | 8 more BRAM tiles at 110 of 140 and 83.95% slices; a new source on the `core_data_in_q` mux next to the shadow (TURBO shadow-RAM family at +0.171 ns) and a write tap on the capture FIFO path (+0.182 ns); a cache veto. Kept: the `$E1` name and arming by `$C035` (rev 2026-10-04: no longer the window's address map, now dropped too). Reading the display back is question 4. |
| The zero-page pair as the only CPU path (`zp_wr = $E1`) | the "select" design | Depends on change 5, which is not built, and inherits its rules (`$C069` setup, clear before ROM calls, IRQ saves); and (rev 2026-10-04) any CPU path to the display is now ruled out by the owner. Kept: no reconcile, the motherboard left stale, 0 BRAM. |
| A STALE class with a reconcile at SHR exit, TURBO exit and session end, and a bank sync that steers `$C073` | the "api" design | The most complex firmware of the three, and unnecessary once inhibited writes never reach the motherboard. Kept: the present as a memory-API request, applied whole at a frame edge, and the capture ring as the only path into CPU1's copy. |
| A new space value 2 `DISPLAY` | the "api" design | AUX bank `$E1` keeps the IIgs's name for the buffer and needs no new space value; old firmware already refuses it with RANGE (section 2.5). (rev 2026-10-04: the reason was "gives the CPU and the API one name"; the CPU no longer reaches it.) |
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
4. **Reading the display.** With the CPU kept out (rev 2026-10-04), the only read path would be the optional API source stage (S4). Is it wanted, or is the RAM copy in aux 0 enough?
5. **Absorbing `$C035` writes** in the vTW (no bus cycle, no click, no exposure flush) at the cost of a private-serve FSM branch?
6. **The motherboard copy.** Inhibited writes and presents never reach the motherboard's aux RAM or PSRAM bank 1, and are never reconciled. Does any consumer depend on them after an SHR session (a //e's own monitor after leaving SHR, the native CPU after handback)?
7. **Present atomicity.** Is "whole, at the next frame edge after CPU1 has applied it" enough, or should the 65C02 be able to wait until a present is shown (a deferred SmartPort response)?
8. **Dropping the mirror for shadowed SHR writes** (section 8.3): pursue it too, for unmodified software, as a variant of change 3?
9. **Kill-switch default.** On by default, given that nothing happens until `$C035` is written?
10. **Native CPU.** Should `$C035` act when the vTW is off (a renderer-side filter on bus records), or stay a vTW feature?
11. **CPU1 measurement first.** Measure CPU1's record rate (the egress counters) before building S2, since it decides whether S3 (packed records) is needed?

(rev 2026-10-04: dropped with the window: old 5, window reads; old 8, reserving `$E1` on `$C073`; old 13, stage order with the window as S3. Old 4 lost its CPU-readable option; old 6 lost the `$E1` write. The rest are renumbered: old 7, 9, 10, 11, 12, 14 are now 6, 7, 8, 9, 10, 11.)

## 11. Not verified

- The IIgs semantics of bits 1, 2 and 4, and the real IIgs reset value: from gssquared, not the Apple IIgs Hardware Reference.
- That a //e clicks on `$C035` writes: from memory and an AppleWin comment.
- That no VidHD-era software or RamWorks probe writes `$C035`.
- CPU1's record rate, egress throughput during a burst, and the present's real 65C02 cost.
- That the engine's record port and the core's direct leg (today's TURBO record) can never be active together.
- That no cached state other than the TURBO map's per-entry fast bit (`vtw_turbo_cache.sv:79`, `:96` V) carries a write's class across an inhibit change; the byte cache holds read data only and is snooped on shadow writes (`core:1214-1215`, `:1232-1235` V), so C4 is believed sufficient (I).
- F1.2.2's BRAM and LUT use after the copy engine.
- The LUT split behind section 3.3's revised figures: the window's share is estimated, not synthesized.
- Whether `tb_apple_cycle_capture` and `tb_vtw_copy_engine` build and pass under Verilator here.
- DOOM's benchmark store count, and every DOOM reader of aux 0 outside the replay.

(rev 2026-10-04: dropped with the window: what a real RamWorks III does with `$E1`, and whether a read under the window fills the TURBO write map. Check 2026-10-04: this note moved below the list, which it had split in two.)
