; rsky.s: the sky and the patchless columns of the native renderer's seg
; loops (docs/RENDER.md): skyColumn and
; ceilSky (r_seg65.s:1403-1474, :1696-1706), tierFlat (:1525-1543) with
; R_DrawColumnFlat's fill record and its span cut (build/gen/drawcol.s:
; 142-, fillCol and FSCUTE of r_list65.s:423-450, lists.inc). A GPL-2
; derivative of Webifi's IIgs DOOM, written for the 65C02.
;
;   sky_col     the sky in rows CT .. CB1 - 1 of column X (kept), as
;               ceilFill calls it for a sky ceiling (W_SKY) and genColumn
;               for its ceiling rows: a K_TEX record of the texel column
;               ((viewangle >> 16) + xtoviewangle[x]) >> 6 of the sky patch
;               (skywidthmask 255: levelconv.py checks it), its slot in
;               SKYBANK:SKYHI:SKYLO + 128 c (RENDER.md), one texel a
;               row (SKYFRACSTEP 512), texturemid 100 << 16, the page of
;               the fixed colormap or of colormap A's full light. As
;               upstream, the wall's yl goes through DC_ROW (DCROW = YL on
;               return) and the step of the column is left at SKYFRACSTEP
;               (every tier after it takes its column's from texCol).
;   tier_flat   from tierdraw: A = TXBANK[t] (bit 7: the texture has
;               patchless columns), Y = t, column X (kept), the tier's rows
;               YL .. YL + DCCOUNT - 1. When the texture's column has no
;               patch (the level's TXFLAT bitmap, LVMAP) the rows become a
;               K_FILL of the colour t (colormap A's and B's full-light
;               bytes), after the span cut of R_DrawColumnFlat's fillCol.
;               Else the texture's slot (tier_slot). Upstream runs
;               R_DrawColumnFlat on the C code's direct page (CENV), so its
;               row and count there leave WPAGE's DC_ROW alone: the loops
;               of kind 6 and 14 read the ceiling clip from it after the
;               tier (the synthetic frames flatv06 and flatv14 show it).
;
; The skyFlat path (no sky patch) is not ported: RENDER.md.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import tier_row, tier_slot, fillrec, far_get
        .export sky_col, tier_flat

SKYFRACSTEP = 512               ; FRACUNIT >> COLEXTRABITS (r_seg65.s:59)
SKYTMID7    = 100 << 9          ; texturemid (100 << FRACBITS) >> 7

        .segment "RENDERW"

; ---------------------------------------------------------------------------
; sky_col (skyColumn, ceilSky)
; ---------------------------------------------------------------------------
sky_col:
        clc                     ; the texel column: bits 6-13 of
        lda VIEWA16             ;   (viewangle >> 16) + xtoviewangle[x]
        adc XTVLO,x
        sta GT
        lda VIEWA16+1
        adc XTVHI,x
        asl GT
        rol a
        asl GT
        rol a
        lsr a                   ; its slot: + 128 c (C = bit 0 of c)
        sta GT+1
        lda #0
        ror a
        clc
        adc SKYLO
        sta SRC
        lda GT+1
        adc SKYHI
        sta SRC+1
        lda SKYBANK
        sta SRC+2
        lda WLV                 ; the light of the walls, back after the sky
        pha
        lda WCMP
        pha
        stz WLV                 ; the fixed colormap's page, else colormap
        lda LT_FIXED+1          ;   A's full light
        bpl :+
        lda #0
:       clc
        adc #CMAPA_PAGE
        sta WCMP
        lda YL                  ; the wall's yl, back after the sky
        sta DCROW
        lda CT                  ; rows CT .. CB1 - 1
        sta YL
        lda CB1
        sec
        sbc CT
        sta DCCOUNT
        lda #<SKYFRACSTEP
        sta DCFSTEP
        lda #>SKYFRACSTEP
        sta DCFSTEP+1
        lda #<SKYTMID7
        sta FRAC
        lda #>SKYTMID7
        sta FRAC+1
        jsr tier_row            ; the position and the K_TEX record
        pla
        sta WCMP
        pla
        sta WLV
        lda DCROW
        sta YL
        rts

; ---------------------------------------------------------------------------
; tier_flat (tierFlat, R_DrawColumnFlat, fillCol)
; ---------------------------------------------------------------------------
tier_flat:
        and #$7F                ; the texture's bank
        pha
        sty GT                  ; t
        lda TEXCOL              ; its column c
        and TXWM,y
        sta GT+1
        lda #GT+2               ; k = TXFLAT_INDEX[t] (LVMAP) into GT+2
        sta FA_DST
        stz FA_DST+1
        clc
        tya
        adc #<TXFLAT_INDEX
        sta FA_SRC
        lda #0
        adc #>TXFLAT_INDEX
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #1
        sta FA_N
        jsr far_get
        lda GT+2                ; the byte of c: TXFLAT_MAPS + 32 k + c / 8
        stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        sta FA_SRC
        lda GT+1
        lsr a
        lsr a
        lsr a
        clc
        adc FA_SRC
        sta FA_SRC
        lda FA_SRC+1
        adc #0
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<TXFLAT_MAPS
        sta FA_SRC
        lda FA_SRC+1
        adc #>TXFLAT_MAPS
        sta FA_SRC+1
        jsr far_get             ; (FA_DST, FA_BANK, FA_N as before)
        lda GT+1                ; the bit of c
        and #7
        tay
        lda GT+2
:       dey
        bmi :+
        lsr a
        bra :-
:       lsr a
        bcs @flat
        ldy GT                  ; a column with its patch: its slot
        pla
        jmp tier_slot

@flat:  pla
        lda YL                  ; the fill spans of the column end at its
        clc                     ;   rows (FSCUTE): the bottom span starts
        adc DCCOUNT             ;   after them, the top span ends before
        sta GT+1
        cmp FSBOT,x
        bcc :+
        beq :+
        sta FSBOT,x
:       lda YL
        cmp FSTOP,x
        bcs :+
        sta FSTOP,x
:       ldy GT                  ; the colour t: colormap A's byte (even
        lda CMAPA0,y            ;   rows), B's (odd rows), full light
        sta GT+2
        lda CMAPB0,y
        sta GT+3
        lda YL
        sta GT
        jmp fillrec             ; rows YL .. GT+1 - 1
