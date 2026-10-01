; far.s: the far layer of the native renderer, F1.2.1 back end
; (docs/NATIVE.md 4.5, docs/RENDER.md 3.4 and 3.5), and the loops that
; must run inside a read window.
;
; It lives in the main card's bank 1 from $DC43, after MATHFAR
; (docs/MEMORY_MAP.md 4.2: the far layer's $DC00-$DFFF): inside a RAMRD
; window only zero page, the stack page and the card are near, and RAMRD
; also moves the fetches of $0200-$BFFF (NATIVE.md 4.5 rules 1 and 2), so
; the code of a read window and the data it keeps are in the card. Its
; arguments are in zero page $00-$05 (FA_*, rlayout.py).
;
; Every window writes $C073 at its start and 0 at its end, as mt_far does
; (math.s): between windows RAMRD, RAMWRT and $C073 are 0 (RENDER.md 3.2),
; so no shadow of $C073 is kept.
;
; The vertex-angle gather (RENDER.md 3.5): the walk puts the native vertex
; numbers of a batch of segs in vg_vlo/vg_vhi (the card: near in the
; window), far_vgather reads their angles and stamps from LVMAP in one
; window, the walk computes the missing ones and marks them in vg_d, and
; far_vput writes those back in one window.
;
; The phase loader (stage C, RENDER.md 3.4; MEMORY_MAP.md 3.5, 4.2): on
; F1.2.1 the tics run in W before the frame, so the render window is
; loaded each frame from its image in RamWorks bank WCODE_BANK, at the
; same addresses: far_wload copies the code (from $6000 to the page after
; the end of RENDERW, the last segment of W) and the per-level tables'
; pages (WTABLES_PAGE for WTABLES_PAGES) with RAMRD on, the stores going
; to main W. It is its own segment, RLOAD, so that the harness can tell
; its writes (W only) from the render code's. Milestone 8 (RENDER-MASKED.md
; 3.2): the loader takes a bank and a list of page runs (far_pload), and
; mfar.s's far_mload loads the masked phase's image from MCODE_BANK.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .export far_get, far_put, far_vgather, far_vput, far_vclear
        .export far_fstep, far_wload, far_pload
        .import __RENDERW_RUN__, __RENDERW_SIZE__
        .export vg_n, vg_vlo, vg_vhi, vg_al, vg_ah, vg_s, vg_d

        .segment "RFAR"

; ---------------------------------------------------------------------------
; far_get: FA_N bytes (1-255; 0: 256) of RamWorks bank FA_BANK from FA_SRC
; to main FA_DST (zero page, or $0200-$BFFF: RAMWRT stays off). One RAMRD
; window. Changes A, Y.
; ---------------------------------------------------------------------------
far_get:
        lda FA_BANK
        sta RWBANK
        sta RAMRDON
        ldy #0
:       lda (FA_SRC),y
        sta (FA_DST),y
        iny
        cpy FA_N
        bne :-
        sta RAMRDOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; far_put: FA_N bytes (1-255; 0: 256) of main FA_SRC to RamWorks bank
; FA_BANK at FA_DST. One RAMWRT window. Changes A, Y.
; ---------------------------------------------------------------------------
far_put:
        lda FA_BANK
        sta RWBANK
        sta RAMWRTON
        ldy #0
:       lda (FA_SRC),y
        sta (FA_DST),y
        iny
        cpy FA_N
        bne :-
        sta RAMWRTOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; far_vgather: for each of the vg_n vertices (native numbers in vg_vlo,
; vg_vhi), its angle (vg_al, vg_ah) and stamp (vg_s) from LVMAP's planes
; VAL, VAH, VAS; vg_d cleared. One RAMRD window. Changes A, X, FA_SRC.
; ---------------------------------------------------------------------------
far_vgather:
        lda #LVMAP
        sta RWBANK
        sta RAMRDON
        ldx #0
@next:  cpx vg_n
        beq @done
        clc
        lda vg_vlo,x
        adc #<VAL
        sta FA_SRC
        lda vg_vhi,x
        adc #>VAL
        sta FA_SRC+1
        lda (FA_SRC)
        sta vg_al,x
        lda FA_SRC+1
        clc
        adc #>VTX_STRIDE
        sta FA_SRC+1
        lda (FA_SRC)
        sta vg_ah,x
        lda FA_SRC+1
        clc
        adc #>VTX_STRIDE
        sta FA_SRC+1
        lda (FA_SRC)
        sta vg_s,x
        stz vg_d,x
        inx
        bra @next
@done:  sta RAMRDOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; far_vput: the entries of the gather with vg_d set back into LVMAP (angle
; and stamp). One RAMWRT window. Changes A, X, FA_DST.
; ---------------------------------------------------------------------------
far_vput:
        lda #LVMAP
        sta RWBANK
        sta RAMWRTON
        ldx #0
@next:  cpx vg_n
        beq @done
        lda vg_d,x
        beq @skip
        clc
        lda vg_vlo,x
        adc #<VAL
        sta FA_DST
        lda vg_vhi,x
        adc #>VAL
        sta FA_DST+1
        lda vg_al,x
        sta (FA_DST)
        lda FA_DST+1
        clc
        adc #>VTX_STRIDE
        sta FA_DST+1
        lda vg_ah,x
        sta (FA_DST)
        lda FA_DST+1
        clc
        adc #>VTX_STRIDE
        sta FA_DST+1
        lda vg_s,x
        sta (FA_DST)
@skip:  inx
        bra @next
@done:  sta RAMWRTOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; far_vclear: every vertex stamp 0 (NVERT of them, the frame block): the
; stamp wrapped (RENDER.md 1.3). One RAMWRT window. Changes A, X, Y,
; FA_DST.
; ---------------------------------------------------------------------------
far_vclear:
        lda #<VAS
        sta FA_DST
        lda #>VAS
        sta FA_DST+1
        ldx NVERT+1             ; whole pages
        lda #LVMAP
        sta RWBANK
        sta RAMWRTON
        lda #0
        ldy #0
        cpx #0
        beq @part
@page:  sta (FA_DST),y
        iny
        bne @page
        inc FA_DST+1
        dex
        bne @page
@part:  cpy NVERT               ; the last part page
        beq @done
        sta (FA_DST),y
        iny
        bra @part
@done:  sta RAMWRTOFF
        stz RWBANK
        rts

; ---------------------------------------------------------------------------
; far_fstep: the columns X .. X2END - 1 of the seg: GSC (the scale, one
; step early) += GSS each column; FSTEPLO, FSTEPHI of the column; DLW
; when WLV is not 0. One RAMRD window. Changes A, X, UI (4), UN (2), GSC.
; ---------------------------------------------------------------------------
far_fstep:
        stz GFLAG
        lda #$FF                ; no FSTEP bank yet
        sta UN
        sta RAMRDON
@col:   clc                     ; the scale of the column (STEP8)
        lda GSC
        adc GSS
        sta GSC
        lda GSC+1
        adc GSS+1
        sta GSC+1
        lda GSC+2
        adc GSS+2
        sta GSC+2
        bne @high
        lda GSC                 ; below 1.0: FSTEP_TABLE[scale]
        sta UI
        lda GSC+1
        jsr @entry
        lda UI+2
        sta FSTEPLO,x
        lda UI+3
        sta FSTEPHI,x
        bra @light
@high:  cmp #$40                ; fstepHigh
        bcs @clamp
        lda GSC                 ; r = the scale / 256, rounded
        cmp #$80
        lda GSC+1
        adc #0
        sta UN+1
        lda GSC+2
        adc #0
        cmp #$40
        bcs @seven
        asl UN+1                ; the entry 2 r, >> 7
        rol a
        pha
        lda UN+1
        sta UI
        pla
        jsr @entry
        lda UI+2
        asl a
        lda UI+3
        rol a
        sta FSTEPLO,x
        lda #0
        rol a
        sta FSTEPHI,x
        bra @light
@clamp: bne @gen                ; 64.0: 7
@seven: lda #7
        sta FSTEPLO,x
        stz FSTEPHI,x
        bra @light
@gen:   lda #1                  ; past 64.0: the W code (fsGeneral)
        sta GFLAG
@light: lda WLV
        beq @next
        lda GSC+2               ; d = min(bytes 1-2, 767) >> 5, 23 at most
        cmp #>(24 << 5)
        bcs @d23
        asl a
        asl a
        asl a
        sta UN+1
        lda GSC+1
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        ora UN+1
        bra @d
@d23:   lda #23
@d:     sta DLW,x
@next:  inx
        cpx X2END
        bcs :+
        jmp @col
:       sta RAMRDOFF
        stz RWBANK
        rts

; @entry: UI+2 (low), UI+3 (high) = FSTEP_TABLE entry A:UI, from bank
; FSTEP0 + (A >> 6) at $2000 + (A & $3F):UI (low plane), + $4000 (high)
@entry: pha
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc #FSTEP0
        cmp UN
        beq :+
        sta UN
        sta RWBANK
:       pla
        and #$3F
        clc
        adc #$20
        sta UI+1
        lda (UI)
        sta UI+2
        lda UI+1
        clc
        adc #$40
        sta UI+1
        lda (UI)
        sta UI+3
        rts

; ---------------------------------------------------------------------------
; The gather's entries: two a seg of the bounce buffer (v1 at 2k, v2 at
; 2k + 1). In the card, so that far_vgather reads its inputs and writes
; its outputs in the window.
; ---------------------------------------------------------------------------
vg_n:   .res 1
vg_vlo: .res VG_MAX
vg_vhi: .res VG_MAX
vg_al:  .res VG_MAX
vg_ah:  .res VG_MAX
vg_s:   .res VG_MAX
vg_d:   .res VG_MAX

; ---------------------------------------------------------------------------
; far_wload: the render window's image into main W (the phase loader);
; far_pload: the page runs of the list at A:X (A the low byte; each run
; its first page and its count, a first page of 0 ends the list; in the
; card, near in the window) of RamWorks bank Y into the same addresses of
; main memory (milestone 8: the masked phase's image too, mfar.s). One
; RAMRD window. Changes A, X, Y, FA_SRC, FA_DST, FA_N.
; ---------------------------------------------------------------------------
        .segment "RLOAD"

WL_FIRST = $60                  ; the front end's code: its first page
far_wload:
        lda #<wl_front
        ldx #>wl_front
        ldy #WCODE_BANK
far_pload:
        sta FA_DST
        stx FA_DST+1
        sty RWBANK
        sta RAMRDON
        stz FA_SRC
@run:   lda (FA_DST)            ; the run's first page, 0: no more
        beq @done
        sta FA_SRC+1
        inc FA_DST
        lda (FA_DST)            ; (a list does not cross a page)
        sta FA_N
        inc FA_DST
        ldy #0
:       lda (FA_SRC),y          ; read from the image (RAMRD), written to
        sta (FA_SRC),y          ;   main
        iny
        lda (FA_SRC),y
        sta (FA_SRC),y
        iny
        bne :-
        inc FA_SRC+1
        dec FA_N
        bne :-
        bra @run
@done:  sta RAMRDOFF
        stz RWBANK
        rts
wl_front:
        .byte WL_FIRST, <(((__RENDERW_RUN__ + __RENDERW_SIZE__ + $FF) >> 8) - WL_FIRST)
        .byte WTABLES_PAGE, WTABLES_PAGES, 0
.assert >wl_front = >(wl_front + 4), lderror, "the loader's list crosses a page"
