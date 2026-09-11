# FATDOG MAGIC: exact palette-upload assembly

The disk is `dist/FATDOG_MAGIC.po`, 33,554,432 bytes, containing 32 Standard
HGR images and 20 complete interlaced Brooks images. The Apple II program
loads RAM and controls the existing capture window. Appletini performs the
rendering. No firmware or FPGA source is changed.

| Contents | RAM |
| --- | --- |
| First field | AUX $2000-$9FFF |
| Second field | MAIN $2000-$9FFF |
| First field's 6400-byte palette | AUX $0400-$1CFF |
| Second field's 6400-byte palette | MAIN $0400-$1CFF |
| Staged MAIN palette, then saved low MAIN RAM | AUX $A000-$B8FF |
| Saved names and paths within that block | AUX $A500-$B5FF |
| Directory/palette staging | MAIN $1D00-$1EFF |
| Loader reservation | MAIN $A000-$BAFF |
| ProDOS I/O buffer | MAIN $BB00-$BEFF |

Each field's $9DF9-$9DFB control bytes are `01 00 04` for AUX and `00 00 04`
for MAIN. The original mode byte at $9DF8 is preserved; these images use mode
1, so the renderer weaves AUX and MAIN into the 400-line image.

## Sequence and ordering

1. Read the first 32K field into MAIN staging and copy it to AUX $2000.
   Keep its extension magic unpublished until loading finishes.
2. Read the first palette into MAIN $2000. ARM AUX $0400-$1CFF, wait for
   acknowledgement, copy all 6400 bytes with CPU stores, then OFF and wait.
3. Stage the MAIN palette in AUX $A000-$B8FF. For shared-table files this
   is a copy of the first table. For separate-table files it is the appended
   table, read through MAIN $1D00 after loading the second image field.
4. CLOSE the file before installing the MAIN palette. SmartPort writes
   MAIN $07F8, so a later disk call would overwrite a palette byte.
5. ARM MAIN $0400-$1CFF. For each 256-byte page: move the staged AUX palette
   page into MAIN $1D00; save the old MAIN destination page into the now-free
   AUX staging page; copy the temporary palette page into MAIN. This both
   installs the palette and preserves names, paths and slot workspace.
6. OFF and wait for FRAME_PENDING and ARMED to clear. Publish AUX magic.
   The slideshow wait performs no disk calls and has no extra capture armed.
7. Before help, the menu or the next image OPEN, restore saved MAIN $0400-$1CFF.

LINTXT computes its range as `BASE + 2 * COLS * ROWS`. BASE=$0400, COLS=80
and ROWS=40 therefore give exactly 6400 bytes, ending at $1D00 exclusive.
CONFIG bit 0 selects MAIN (0) or AUX (1). SCALE=$11 is required to pass the
interface's validation; no text is displayed because SHOW is never issued.

OFF is required: HIDE leaves capture armed. The existing vTW bus engine
drains posted writes before slot-7 DEVSEL accesses, so the OFF command is
ordered after the palette stores. The loader also waits for OFF's frame
acknowledgement. It checks STALE/CONFIG_ERROR and bounds all polling loops.

Only the 6400-byte palette destination is temporarily watched in one bank
at a time. Of that range, $0400-$0BFF already belongs to normal text capture;
the extra range is $0C00-$1CFF, 4352 bytes per bank. Two palette uploads add
8704 newly watched destination bytes per image. Staging, catalog saves and
control overhead are separate; this is not a hardware timing measurement.

The loader checks both the slot-ROM descriptor and live DEVSEL identity.
This permits full-memory emulators with a copied Appletini ROM but no
LINTXT register implementation to use the same complete image layout.
Physical Appletini hardware requires the actual LINTXT v1.0 interface.

## Exact file-loading and AUX-upload code

These are literal excerpts from the assembler inputs used for this build,
including the inline comments. They are not a separate assembly target.
The full sources are [formats.a65](../formats.a65) and
[palettes.a65](../palettes.a65).

```asm
load_brooks_pair:
    ; File order: 32K AUX field, 6400 palette bytes, 32K MAIN field,
    ; then an optional second 6400-byte palette. AUX pixels are already loaded.
    jsr capture_detect       ; identify LINTXT before touching its I/O registers

    ; MAIN's second image has not been loaded yet, so its $2000 area is
    ; available to stage the first palette. ProDOS always runs with MAIN
    ; reads/writes and uses an I/O buffer at $BB00, outside palette RAM.
    lda #$20
    ldy #$19                 ; $19 pages * 256 = 6400 bytes
    jsr read_chunk

    lda #1                   ; CONFIG bit 0 = 1: watch AUX writes
    jsr capture_enable       ; ARM exactly AUX $0400-$1CFF; wait for BUSY=0
    lda #$20                 ; source = MAIN $2000
    ldx #$04                 ; destination = AUX $0400
    ldy #$19                 ; copy all 25 pages while the window is armed
    jsr copy_to_aux          ; CPU stores, so vTW posts every palette byte
    jsr capture_disable      ; OFF; wait until ARMED and FRAME_PENDING clear

    lda image_kind
    cmp #$70
    beq brooks_main_field    ; a separate second palette will be uploaded later
    lda #$20                 ; shared table: stage another copy for MAIN
    ldx #$A0                 ; AUX $A000-$B8FF, outside all active capture ranges
    ldy #$19
    jsr copy_to_aux          ; do NOT install MAIN yet: SmartPort uses $07F8

brooks_main_field:
    lda #$20
    ldy #$80                 ; second field: 32768 bytes -> MAIN $2000-$9FFF
    jsr read_chunk
    lda image_kind
    cmp #$70
    beq +                    ; 78336-byte exports append a distinct second table
    jmp brooks_close         ; shared table is already staged in AUX $A000
+   lda #$A0
    sta palette_page
    lda #$19
    sta palette_pages_left
-   lda #>directory_buffer   ; $1D00 staging is just OUTSIDE the capture window
    ldy #1
    jsr read_chunk            ; read 256 bytes without touching either image
    lda #>directory_buffer
    ldx palette_page
    ldy #1
    jsr copy_to_aux           ; stage separate MAIN table in AUX $A000-$B8FF
    inc palette_page
    dec palette_pages_left
    bne -
brooks_close:
    jsr close_file           ; LAST disk call: it may write MAIN $07F8
    jsr install_main_palette ; upload after CLOSE, preserving catalog by swapping
    jmp shr_publish          ; publish AUX magic; no more MLI until navigation

; A=source page, X=destination page, Y=page count. Code/data reads stay MAIN.
; Only zero-page loop state is written while RAMWRT selects AUX.
copy_to_aux:
    sta src_ptr+1
    stx dst_ptr+1
    sty copy_pages
    lda #0
    sta src_ptr
    sta dst_ptr
    jsr main_bank
    ldx copy_pages
    sta $C005
-   ldy #0
--  lda (src_ptr),y
    sta (dst_ptr),y
    iny
    bne --
    inc src_ptr+1
    inc dst_ptr+1
    dex
    bne -
    sta $C004
    rts

; Read Y*256 bytes into MAIN A:00. No MLI executes with auxiliary writes on.
read_chunk:
    sta read_buffer+1
    sty read_length+1
    lda #0
    sta read_buffer
    sta read_length
read_exact:
    jsr main_bank
    jsr MLI
    !byte $CA
    !word read_params
    bcs read_error
    lda read_count
    cmp read_length
    bne read_error
    lda read_count+1
    cmp read_length+1
    bne read_error
    rts
read_error:
    jmp fatal

```

## Exact capture control, MAIN upload and RAM preservation

```asm
; Brooks palette upload through Appletini's EXISTING LINTXT capture window.
; This is a loader only: it writes Apple RAM and issues ARM/OFF commands.
; It never issues SHOW, draws text through LINTXT, or renders image pixels.
; Normal FPGA capture ranges and Appletini firmware are unchanged.

LTO_INDEX  = $C0F0           ; slot 7 indirect register selector
LTO_INC    = $C0F2           ; write selected register, then advance INDEX
LTO_CMD    = $C0F3           ; 0=OFF, 1=ARM, 2=SHOW (unused here), 3=HIDE
LTO_STATUS = $C0F4           ; BUSY=$80, STALE=$40, ERROR=$20, PENDING=$10,
                            ; ARMED=$02, VISIBLE=$01
PALETTE_BASE = $0400
PALETTE_PAGES = $19          ; 25 pages = 6400 bytes; end is $1D00 exclusive
AUX_COPY_ZP = $40

capture_detect:
    lda capture_probed
    bne capture_detect_done
    inc capture_probed
    ; The Appletini demo identifies LINTXT in the slot ROM before touching
    ; DEVSEL. This avoids probing registers belonging to an unrelated card.
    ; This firmware's temporary capture interface is bound to slot 7.
    lda $C015                ; remember INTCXROM in bit 7
    pha
    sta $C006                ; expose external Cx ROM for the read-only probe
    ldx #7
-   lda $C7B0,x              ; ROM descriptor: "LINTXT", $4C, version $10
    cmp capture_signature,x
    bne +
    dex
    bpl -
    ; Confirm the live interface too. An emulator can carry the real slot
    ; ROM without implementing LINTXT's DEVSEL registers. ROM identity alone
    ; must not make us send ARM/OFF to an unimplemented interface.
    ldx #7
-   lda $C0F8,x              ; live "LINTXT", $4C, $10 identity bytes
    cmp capture_signature,x
    bne +
    dex
    bpl -
    inc capture_available
+   pla
    bpl +
    sta $C007                ; restore internal Cx ROM if it was selected
+   lda capture_available
    beq capture_detect_done  ; full-memory emulators need no capture interface
    jsr capture_release      ; start hidden/disarmed; a new ARM clears old STALE
    bcs capture_error
capture_detect_done:
    rts

; A=0 MAIN or A=1 AUX. Arm a 6400-byte window at $0400 in that bank.
; All callers enter with normal MAIN reads and MAIN writes selected.
capture_enable:
    sta capture_config+2     ; patch only CONFIG's bank bit in the setup block
    lda capture_available
    beq capture_enable_done
    jsr capture_wait_idle    ; commands are ignored while BUSY is set
    bcs capture_error
    lda #0
    sta LTO_INDEX            ; first indirect register is BASE_LO
    ldx #0
-   lda capture_config,x
    sta LTO_INC              ; write BASE, CONFIG, dimensions, origin and scale
    inx
    cpx #10
    bne -
    lda #1
    sta LTO_CMD              ; ARM: validate range and clear private text shadow
    jsr capture_wait_idle    ; wait for CPU1's ARM acknowledgement, not just I/O
    bcs capture_error
    and #$63                 ; reject STALE/ERROR, require ARMED=1 and VISIBLE=0
    cmp #$02
    bne capture_error
capture_enable_done:
    rts                      ; palette stores may begin ONLY after this return

capture_disable:
    jsr capture_release
    bcs capture_error
    lda capture_available
    beq +
    lda LTO_STATUS
    and #$60                 ; OFF must not conceal an upload that lost writes
    bne capture_error
+   rts
capture_error:
    jmp fatal                ; fatal attempts bounded OFF cleanup before exit

; OFF is also used by the error handler: return carry set on timeout/error,
; rather than jumping back into fatal and recursing. Never use HIDE here:
; HIDE leaves capture armed and would keep forwarding unrelated RAM writes.
capture_release:
    lda capture_available
    beq capture_release_done
    jsr capture_wait_idle
    bcs capture_release_return
    lda #0
    sta LTO_CMD              ; vTW drains prior posted writes before this I/O
    jsr capture_wait_idle    ; OFF takes effect at an output frame boundary
    bcs capture_release_return
    and #$03                 ; both ARMED and VISIBLE must now be clear
    beq capture_release_done
    sec
    rts
capture_release_done:
    clc
capture_release_return:
    rts

; Return A=the last STATUS byte and C=0 when BUSY/FRAME_PENDING are clear.
; The bounded loop avoids hanging forever if the card stops responding.
; It permits 65536 polls; it is an upper bound, not a delay after success.
capture_wait_idle:
    ldx #0
    ldy #0
-   lda LTO_STATUS
    and #$90                 ; BUSY or FRAME_PENDING => keep waiting
    beq +
    dex
    bne -
    dey
    bne -
    sec
    rts
+   lda LTO_STATUS
    clc
    rts

capture_probed: !byte 0
capture_available: !byte 0
capture_signature: !text "LINTXT"
    !byte $4C,$10
capture_config:
    !byte <PALETTE_BASE, >PALETTE_BASE ; BASE_LO=$00, BASE_HI=$04
    !byte 0                          ; CONFIG: patched to 0 MAIN or 1 AUX
    !byte 80,40                      ; 2 bytes/cell * 80 * 40 = 6400 bytes
    !byte 0,0,0,0                    ; origin X/Y; unused because SHOW is unused
    !byte $11                        ; valid 1x1 scale; also never displayed

; A=MAIN source page, X=MAIN destination page, Y=number of 256-byte pages.
; Use CPU stores for palette uploads. A direct disk/DMA read into palette
; RAM could bypass vTW's CPU-write classifier, so disk reads use staging RAM.
copy_to_main:
    sta src_ptr+1
    stx dst_ptr+1
    sty copy_pages
    jsr main_bank
    sta src_ptr              ; main_bank returns A=0
    sta dst_ptr
    ldx copy_pages
-   ldy #0
--  lda (src_ptr),y
    sta (dst_ptr),y          ; the armed range captures this actual RAM write
    iny
    bne --
    inc src_ptr+1
    inc dst_ptr+1
    dex
    bne -
    rts

; Enter ONLY after ProDOS CLOSE. SmartPort uses MAIN $07F8 as slot workspace;
; a disk call after installing this palette could corrupt that color word.
; AUX $A000-$B8FF holds the complete staged MAIN palette. Swap it pagewise
; with MAIN $0400-$1CFF, using MAIN $1D00 as a 256-byte temporary buffer.
; This saves the old MAIN catalog at AUX $A500-$B5FF without needing another
; 4352 bytes of RAM. The first palette at AUX $0400 remains untouched.
install_main_palette:
    lda #0                   ; watch only MAIN $0400-$1CFF during the swap
    jsr capture_enable
    lda #$04
    sta palette_page
    lda #$A0
    sta palette_stage_page
    lda #$19
    sta palette_pages_left
-   lda palette_stage_page
    ldx #>directory_buffer   ; step 1: AUX palette page -> MAIN $1D00 temporary
    ldy #1
    jsr copy_from_aux
    lda palette_page
    ldx palette_stage_page   ; step 2: old MAIN page -> freed AUX staging page
    ldy #1
    jsr copy_to_aux           ; AUX $A000+ is outside the armed MAIN window
    lda #>directory_buffer
    ldx palette_page         ; step 3: temporary palette page -> MAIN destination
    ldy #1
    jsr copy_to_main          ; these CPU stores are the captured palette upload
    inc palette_page
    inc palette_stage_page
    dec palette_pages_left
    bne -
    lda #1
    sta catalog_saved
    jmp capture_disable      ; drain posted stores, issue OFF and wait for disarm

; Restore low MAIN RAM before menu/help/next-image OPEN, including names,
; paths and SmartPort's slot workspace. Extra capture is already OFF.
restore_catalog:
    lda catalog_saved
    beq +
    lda #$A0                 ; complete saved MAIN $0400-$1CFF block
    ldx #$04
    ldy #$19
    jsr copy_from_aux
    lda #0
    sta catalog_saved
+   rts
catalog_saved: !byte 0
palette_stage_page: !byte 0

; A=AUX source page, X=MAIN destination page, Y=page count.
; Used for both staged palette pages and restoration of saved low MAIN RAM.
; RAMRD also banks the code at $A000, so execute the AUX-read loop in zero
; page. ALTZP remains MAIN throughout. Restore RAMRD before RTS so the
; caller and its stack are fetched normally. Preserve the interrupt state.
copy_from_aux:
    sta src_ptr+1
    stx dst_ptr+1
    sty copy_pages
    jsr main_bank
    sta src_ptr
    sta dst_ptr
    php
    sei                      ; no interrupt handler may run with AUX code reads
    ldx #aux_copy_end-aux_copy_code-1
-   lda aux_copy_code,x
    sta AUX_COPY_ZP,x
    dex
    bpl -
    ldx copy_pages
    jsr AUX_COPY_ZP
    plp
    rts
aux_copy_code:
!pseudopc AUX_COPY_ZP {
    sta $C003                ; AUX reads; zero page/stack still MAIN
-   ldy #0
--  lda (src_ptr),y          ; read a staged palette page or saved RAM from AUX
    sta (dst_ptr),y          ; RAMWRT is off: write it back to MAIN
    iny
    bne --
    inc src_ptr+1
    inc dst_ptr+1
    dex
    bne -
    sta $C002                ; restore MAIN reads before returning to $A000
    rts
}
aux_copy_end:
```

## Final mode publication

```asm
shr_complete:
    jsr close_file
shr_publish:
    jsr main_bank
    sta $C005
    ldx #0
-   lda shr_magic,x
    sta $9DFC,x
    inx
    cpx #4
    bne -
    sta $C004
    rts

```

This source was assembled into a 6578-byte MAGIC.SYSTEM.
Viewer SHA-256: `7b3a1dda671d180353126dc602aa1a0f54d50fd9a3f3a3a1a9b21a526257bc96`.
