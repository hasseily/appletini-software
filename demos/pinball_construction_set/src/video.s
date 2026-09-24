; Pinball Construction Set for the Appletini -- SHR video primitives.
;
; Everything is drawn into a main-memory arena (ARENA, $BB00, 1001 bytes,
; a rectangle of `arena_stride` bytes per row) and copied to the SHR
; framebuffer in AUX memory with RAMWRT on and no other soft-switch access
; inside the copy (docs/DESIGN.md section 2: every AUX write is posted to
; the 1 MHz bus; RAMWRT toggles drain the posted queue, so one pair per
; rectangle).
;
; blit_sprite draws a sprite into the arena with per-pixel transparency
; (nibble 0 = transparent, through masktab). Sprites in the auxiliary
; language card are read with ALTZP on; the caller switches ALTZP and the
; card bank (sprite_bank), and this file's zero-page variables are then
; the auxiliary zero page's, which is why every input is passed in BSS
; (absolute addresses) and never in zero page.
;
; aux_fetch runs from the stack page ($0110, AUX_FETCH): RAMRD moves every
; read from $0200 up to auxiliary memory, pages 0 and 1 excepted, so a copy
; loop that reads AUX must live there. Zero-page use: this file's
; ZEROPAGE variables only (V_*), never the upstream's.

.setcpu "65C02"
.include "pcs.inc"
.include "assets.inc"
.macpack longbranch

.export video_init, video_shutdown, video_wait_vbl
.export blit_sprite, sprite_bank, copy_arena, fill_arena, aux_fetch_rows
.export row_lo, row_hi, masktab
.export bl_id, bl_x, bl_y, bl_cx0, bl_cx1, bl_cy0, bl_cy1
.export arena_stride, cp_x0, cp_y0, cp_w, cp_rows, cp_count
.export af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.exportzp V_SRC, V_DST, V_REC, V_TMP, V_PTR
.import spr_dir, spr_w, spr_h, spr_bank, palette0


; ---------------------------------------------------------------------------
.segment "ZEROPAGE"
V_SRC:   .res 2
V_DST:   .res 2
V_REC:   .res 2
V_TMP:   .res 2
V_PTR:   .res 2
V_H:     .res 1
V_W:     .res 1
V_ROWS:  .res 1
V_START: .res 1
V_LEN:   .res 1
V_MORE:  .res 1
V_SY:    .res 1
V_BC:    .res 1
V_SKIP:  .res 1
V_END:   .res 1

; ---------------------------------------------------------------------------
.segment "BSS"
; blit_sprite inputs
bl_id:   .res 1                 ; sprite id
bl_x:    .res 2                 ; signed x of the sprite's left edge (screen pixels)
bl_y:    .res 2                 ; signed y of its top row
bl_cx0:  .res 2                 ; arena rectangle: left pixel (even), right pixel (odd)
bl_cx1:  .res 2
bl_cy0:  .res 1                 ; top row and bottom row, inclusive
bl_cy1:  .res 1
arena_stride: .res 1            ; bytes per arena row
bank_sel: .res 1                ; card bank selected for reads (0 = none)
; copy_arena inputs
cp_x0:   .res 2                 ; screen pixel (even) of the arena's left column
cp_y0:   .res 1                 ; screen row of the arena's first row
cp_w:    .res 1                 ; bytes per row to copy
cp_rows: .res 1
cp_count: .res 2                ; AUX bytes written this frame
; aux_fetch inputs
af_bank: .res 1                 ; RamWorks bank (0 = base auxiliary memory)
af_src:  .res 2                 ; AUX source of the first row
af_dst:  .res 2                 ; main destination of the first row
af_len:  .res 1                 ; bytes per row (1..255)
af_rows: .res 1
af_sstride: .res 2              ; source row pitch
af_dstride: .res 1              ; destination row pitch

; ---------------------------------------------------------------------------
.segment "RODATA"

; AUX row addresses: $2000 + y*160 for y = 0..199
row_lo:
.repeat SCREEN_H, i
        .byte <(SHR_BASE + i*SHR_ROW)
.endrepeat
row_hi:
.repeat SCREEN_H, i
        .byte >(SHR_BASE + i*SHR_ROW)
.endrepeat

; Sprite byte to keep-mask: a zero nibble is transparent.
masktab:
.repeat 256, I
        .byte ((I & $F0) = 0) * $F0 + ((I & $0F) = 0) * $0F
.endrepeat

; ---------------------------------------------------------------------------
.segment "CODE"

; video_init: 80STORE off (RAMWRT then owns $2000+ routing), clear the SHR
; memory, palette 0, SCBs = 320 mode palette 0, switch SHR on, and copy
; aux_fetch into the stack page.
video_init:
        sta     STORE80OFF
        sta     RAMWRTON
        lda     #<SHR_BASE
        sta     V_PTR
        lda     #>SHR_BASE
        sta     V_PTR+1
        ldx     #$80                    ; $2000-$9FFF = 128 pages
        lda     #0
        tay
@clear: sta     (V_PTR),y
        iny
        bne     @clear
        inc     V_PTR+1
        dex
        bne     @clear
        ldx     #31
:       lda     palette0,x
        sta     SHR_PAL,x
        dex
        bpl     :-
        sta     RAMWRTOFF
        lda     #$C1
        sta     NEWVIDEO
        stz     cp_count
        stz     cp_count+1
        stz     bank_sel
        ; aux_fetch into the stack page
        ldx     #aux_fetch_end-aux_fetch_image-1
:       lda     aux_fetch_image,x
        sta     AUX_FETCH,x
        dex
        bpl     :-
        rts

video_shutdown:
        sta     RAMWRTOFF
        sta     ALTZPOFF
        lda     #$01
        sta     NEWVIDEO
        sta     TEXTON
        rts

; video_wait_vbl: return right after line 0, where the Appletini publishes
; the SHR shadow ($C019 bit 7 = 1 during display, 0 in blank).
video_wait_vbl:
:       bit     RDVBLBAR
        bmi     :-                      ; wait for the blank
:       bit     RDVBLBAR
        bpl     :-                      ; wait for line 0
        rts

; ---------------------------------------------------------------------------
; sprite_bank: make sprite A's data readable. Card sprites need ALTZP on
; (the caller's business) and the right $D000 bank; main sprites need
; nothing. One bus cycle when the bank changes.
; ---------------------------------------------------------------------------
sprite_bank:
        tax
        lda     spr_bank,x
        beq     @done
        cmp     bank_sel
        beq     @done
        sta     bank_sel
        and     #SPR_BANK_1
        beq     @bank2
        bit     LCBANK1RD
        rts
@bank2: bit     LCBANK2RD
@done:  rts

; ---------------------------------------------------------------------------
; fill_arena: fill bl_cy1-bl_cy0+1 rows of arena_stride bytes with A (a
; byte of two pixels).
; ---------------------------------------------------------------------------
fill_arena:
        pha
        lda     #<ARENA
        sta     V_DST
        lda     #>ARENA
        sta     V_DST+1
        lda     bl_cy1
        sec
        sbc     bl_cy0
        inc     a
        sta     V_ROWS
        pla
@row:   ldy     arena_stride
        dey
:       sta     (V_DST),y
        dey
        bpl     :-
        pha
        lda     V_DST
        clc
        adc     arena_stride
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       pla
        dec     V_ROWS
        bne     @row
        rts

; ---------------------------------------------------------------------------
; blit_sprite: draw sprite bl_id at (bl_x, bl_y) into the arena, which
; holds screen pixels bl_cx0..bl_cx1 (bl_cx0 even, bl_cx1 odd) of rows
; bl_cy0..bl_cy1. Transparent pixels (nibble 0) leave the arena alone.
; The sprite's data must be readable (sprite_bank, ALTZP for the card).
;
; A row of the encoded sprite is one or more runs: run_off (bit 7 = another
; run follows; $FF = empty row), run_len, bytes. Both x phases exist, so
; the run bytes land on byte boundaries: byte column = x >> 1.
; ---------------------------------------------------------------------------
blit_sprite:
        ; vertical overlap of the sprite (bl_y .. bl_y+h-1) with cy0..cy1
        ldx     bl_id
        lda     spr_h,x
        sta     V_H
        lda     spr_w,x
        sta     V_W
        ; first sprite row to draw (V_SKIP) and screen row (V_SY)
        lda     bl_y+1
        bmi     @y_neg
        jne     @off                    ; y >= 256
        lda     bl_y
        cmp     bl_cy0
        bcc     @y_above
        ; sprite top at or below cy0
        cmp     bl_cy1
        beq     :+
        jcs     @off                    ; below the rectangle
:       sta     V_SY
        stz     V_SKIP
        bra     @rows_count
@y_neg:
        lda     bl_y+1
        cmp     #$FF
        jne     @off
@y_above:
        ; sprite starts above cy0: skip cy0 - y rows
        lda     bl_cy0
        sec
        sbc     bl_y
        cmp     V_H
        jcs     @off                    ; ends above cy0
        sta     V_SKIP
        lda     bl_cy0
        sta     V_SY
@rows_count:
        ; rows to draw = min(h - skip, cy1 - sy + 1)
        lda     V_H
        sec
        sbc     V_SKIP
        sta     V_ROWS
        lda     bl_cy1
        sec
        sbc     V_SY
        inc     a
        cmp     V_ROWS
        bcs     :+
        sta     V_ROWS
:
        ; variant and record pointer: entry = spr_dir + 4*id (+2 for the
        ; odd variant); 4*id does not fit a byte index
        ldx     bl_id
        stz     V_REC+1
        txa
        asl     a
        rol     V_REC+1
        asl     a
        rol     V_REC+1
        sta     V_REC
        lda     bl_x
        and     #1
        beq     :+
        lda     #2                      ; odd variant
:       clc
        adc     V_REC
        sta     V_REC
        lda     V_REC+1
        adc     #0
        sta     V_REC+1
        lda     V_REC
        clc
        adc     #<spr_dir
        sta     V_REC
        lda     V_REC+1
        adc     #>spr_dir
        sta     V_REC+1
        lda     (V_REC)
        tax
        ldy     #1
        lda     (V_REC),y
        sta     V_REC+1
        stx     V_REC
        ; skip the height/width header
        lda     V_REC
        clc
        adc     #2
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:
        ; byte column of the sprite's first byte relative to the arena:
        ; (x >> 1) - (cx0 >> 1), signed
        lda     bl_x+1
        cmp     #$80
        ror     a
        sta     V_TMP+1
        lda     bl_x
        ror     a
        sta     V_TMP                   ; x >> 1, signed 16-bit
        lda     bl_cx0+1
        lsr     a
        lda     bl_cx0
        ror     a
        sta     V_END                   ; cx0 >> 1 (0..159)
        lda     V_TMP
        sec
        sbc     V_END
        sta     V_BC
        lda     V_TMP+1
        sbc     #0
        sta     V_TMP+1                 ; high byte of the column: 0 or $FF
        ; arena bytes per row = (cx1 - cx0 + 1) / 2 = arena_stride
        lda     arena_stride
        sta     V_END
        ; skip V_SKIP rows of run records
        lda     V_SKIP
        beq     @rows
@skip:  lda     (V_REC)
        tax
        ldy     #1
        lda     (V_REC),y
        clc
        adc     #2
        adc     V_REC
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       cpx     #$FF
        beq     :+
        txa
        bmi     @skip                   ; another run of the same row
:       dec     V_SKIP
        bne     @skip
@rows:
        ; destination row pointer = ARENA + (sy - cy0) * stride
        lda     V_SY
        sec
        sbc     bl_cy0
        tax
        lda     #<ARENA
        sta     V_DST
        lda     #>ARENA
        sta     V_DST+1
        cpx     #0
        beq     @row
:       lda     V_DST
        clc
        adc     arena_stride
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       dex
        bne     :--
@row:
        lda     (V_REC)                 ; run_off
        cmp     #$FF
        bne     :+
        stz     V_MORE
        jmp     @next
:       sta     V_MORE
        and     #$7F
        clc
        adc     V_BC                    ; start column in the arena (signed 16)
        sta     V_START
        lda     V_TMP+1
        adc     #0
        bmi     @neg
        bne     @next                   ; >= 256: past the right edge
        lda     V_START
        cmp     V_END
        bcs     @next                   ; starts past the right edge
        ldy     #1
        lda     (V_REC),y
        sta     V_LEN
        lda     V_REC
        clc
        adc     #2
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
        bra     @clip
@neg:   ; start < 0: drop -start bytes of the run
        lda     V_START
        eor     #$FF
        inc     a
        sta     V_TMP
        ldy     #1
        lda     (V_REC),y
        sec
        sbc     V_TMP
        beq     @next
        bcc     @next
        sta     V_LEN
        stz     V_START
        lda     V_TMP
        clc
        adc     #2
        adc     V_REC
        sta     V_SRC
        lda     V_REC+1
        adc     #0
        sta     V_SRC+1
@clip:  lda     V_END
        sec
        sbc     V_START                 ; bytes to the right edge
        cmp     V_LEN
        bcs     :+
        sta     V_LEN
:       ; draw V_LEN bytes at V_DST + V_START with transparency
        lda     V_DST
        clc
        adc     V_START
        sta     V_PTR
        lda     V_DST+1
        adc     #0
        sta     V_PTR+1
        ldy     V_LEN
        dey
@byte:  lda     (V_SRC),y
        beq     @skipb
        tax
        lda     masktab,x
        beq     @opaque
        and     (V_PTR),y
        sta     V_TMP
        txa
        ora     V_TMP
        sta     (V_PTR),y
        dey
        bpl     @byte
        bra     @next
@opaque:
        txa
        sta     (V_PTR),y
@skipb: dey
        bpl     @byte
@next:  ; rec += 2 + run_len
        ldy     #1
        lda     (V_REC),y
        clc
        adc     #2
        adc     V_REC
        sta     V_REC
        bcc     :+
        inc     V_REC+1
:       bit     V_MORE
        jmi     @row
        ; next row
        lda     V_DST
        clc
        adc     arena_stride
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       inc     V_SY
        dec     V_ROWS
        jne     @row
@off:   rts

; ---------------------------------------------------------------------------
; copy_arena: copy cp_rows rows of cp_w bytes from the arena (row pitch
; arena_stride) to the SHR at byte column cp_x0/2, row cp_y0. RAMWRT on
; for the whole copy; reads come from main memory. Adds to cp_count.
; ---------------------------------------------------------------------------
copy_arena:
        lda     #<ARENA
        sta     V_SRC
        lda     #>ARENA
        sta     V_SRC+1
        ldx     cp_y0
        lda     row_lo,x
        sta     V_DST
        lda     row_hi,x
        sta     V_DST+1
        ; + cp_x0/2
        lda     cp_x0+1
        lsr     a
        lda     cp_x0
        ror     a
        clc
        adc     V_DST
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       lda     cp_rows
        beq     @done
        sta     V_ROWS
        ; count
        lda     cp_w
        ldx     cp_rows
@cnt:   clc
        adc     cp_count
        sta     cp_count
        bcc     :+
        inc     cp_count+1
:       lda     cp_w
        dex
        bne     @cnt
        sta     RAMWRTON
@row:   ldy     cp_w
        dey
:       lda     (V_SRC),y
        sta     (V_DST),y
        dey
        bpl     :-
        lda     V_SRC
        clc
        adc     arena_stride
        sta     V_SRC
        bcc     :+
        inc     V_SRC+1
:       lda     V_DST
        clc
        adc     #SHR_ROW
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       dec     V_ROWS
        bne     @row
        sta     RAMWRTOFF
@done:  rts

; ---------------------------------------------------------------------------
; aux_fetch_rows: copy af_rows rows of af_len bytes from auxiliary memory
; (RamWorks bank af_bank; 0 = the base bank that holds the SHR screen) at
; af_src to main memory at af_dst, with row pitches af_sstride/af_dstride.
; Runs through the stack-page routine; one RAMRD on/off pair per row.
; ---------------------------------------------------------------------------
aux_fetch_rows:
        lda     af_src
        sta     V_SRC
        lda     af_src+1
        sta     V_SRC+1
        lda     af_dst
        sta     V_DST
        lda     af_dst+1
        sta     V_DST+1
        lda     af_rows
        beq     @done
        sta     V_ROWS
@row:   ldx     af_bank
        ldy     af_len
        jsr     AUX_FETCH
        lda     V_SRC
        clc
        adc     af_sstride
        sta     V_SRC
        lda     V_SRC+1
        adc     af_sstride+1
        sta     V_SRC+1
        lda     V_DST
        clc
        adc     af_dstride
        sta     V_DST
        bcc     :+
        inc     V_DST+1
:       dec     V_ROWS
        bne     @row
@done:  rts

; The stack-page routine: X = RamWorks bank, Y = byte count (1..255),
; V_SRC = auxiliary address, V_DST = main address. Copied to AUX_FETCH.
aux_fetch_image:
        stx     RAMWORKS
        sta     RAMRDON
        dey
:       lda     (V_SRC),y
        sta     (V_DST),y
        dey
        bpl     :-
        sta     RAMRDOFF
        stz     RAMWORKS
        rts
aux_fetch_end:
.assert aux_fetch_end - aux_fetch_image <= $70, error, "aux_fetch too long for the stack page"
