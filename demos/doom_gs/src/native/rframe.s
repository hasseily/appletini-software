; rframe.s: the frame of the native renderer's front end (docs/RENDER.md;
; milestone 7): R_FillStamps (r_list65.s:153-203, without segMode: the
; full view only), R_RenderPlayerView to drawMasked (r_frame65.s:117-177),
; R_SetupFrame (setupFrame, :216-286), the clears at the frame's start
; (:125-169) and the weapon skip (weaponClipSame, :892-943). A GPL-2
; derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/r_frame65.s,
; r_list65.s), written for the 65C02.
;
; The weapon's clip pass itself (weaponClip: sprite code) is milestone 8's;
; until then the test driver's wclip_pass puts the reference's result in
; its place (the seam of RENDER.md 2.3): FLOORCLIP, FRVIS, MM_WPOK.
;
;   nr_frame    the frame block and the render inputs (RIN: the player's
;               view, rlayout.py), the level, the persistent state. Out:
;               the spans' stamps, the weapon skip, then through nr_bsp
;               the records (staged whole: rec_start, the last batch
;               flushed at the end), the drawsegs and openings, the clips,
;               the spans. Changes everything but the inputs.
;   nr_fillstamps
;               R_FillStamps: W_FSC + 1; W_FSP = W_FSC - 1 when the view of
;               the frame before shows (W_FSW) with the same first row and
;               row after it (W_TOPR, W_BOTR: set to this view's), else
;               W_FSC; every 128 frames all span stamps W_FSC ^ $80
;               (fsFill); no plane colour of the fill bytes (W_LCC, W_LFC:
;               $80 in the high byte)
;   nr_wskip    weaponClipSame's bookkeeping after the clip pass: FR_SKIP
;               = W_FSW when there is a weapon (PSPF 1: a weapon, no
;               flash), no automap overlay, a weapon that is not the
;               shadow one (FRVIS's colormap) and the same vissprite as the
;               frame before's (WPREV, which becomes FRVIS), else 0; WCLIP
;               = FLOORCLIP at the first frame that skips; W_WSK = FR_SKIP;
;               no weapon: WPREV's lump $FFFF
;   nr_setup    VIEWX, VIEWY, VIEWZ, VIEWANGLE, VIEWA16, EXTRALIGHT from
;               the player; LT_BASE = extralight + gamma + 16; LT_FIXED =
;               the fixed colormap's offset (n * 256) or $FFFF;
;               VIEWSIN, VIEWCOS = finesineapprox and finecosineapprox of
;               viewangle >> 19; VALIDCOUNT + 1
;   nr_clear    SOLIDCOL all 0 (R_ClearClipSegs); CEILCLIP = viewtop + 1,
;               FLOORCLIP = viewbottom + 1 (the clip arrays hold the clips
;               + 1, as upstream's segvar.inc); no drawseg (R_ClearDrawSegs),
;               no opening (R_ClearOpenings)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import nr_bsp, sineapprox, cosineapprox, wclip_pass
        .import rec_start, rec_flush
        .export nr_frame, nr_setup, nr_clear, nr_fillstamps, nr_wskip

.macro MARK n
.ifdef RPROF
        pha
        lda #(n) * 2
        sta PHASE
        pla
.endif
.endmacro

        .segment "RENDERW"

nr_frame:
        MARK 2
        jsr nr_fillstamps       ; (display, d_main65.s:485)
        jsr nr_setup
        jsr nr_clear
        jsr wclip_pass          ; the weapon's clip pass (RENDER.md 2.3)
        jsr nr_wskip
        jsr rec_start
        MARK 3
        sec                     ; R_RenderBSPNode(numnodes - 1)
        lda NUMNODES
        sbc #1
        tay
        lda NUMNODES+1
        sbc #0
        tax
        tya
        jsr nr_bsp
        jmp rec_flush           ; the last batch into the staging

; ---------------------------------------------------------------------------
; nr_fillstamps: R_FillStamps (r_list65.s:153-194)
; ---------------------------------------------------------------------------
nr_fillstamps:
        ldy #0                  ; Y = 1: the old spans show
        lda W_FSW
        beq :+
        iny
:       lda VIEWTOP             ; the first row of the view
        inc a
        cmp W_TOPR
        beq :+
        sta W_TOPR              ; (another one: no old spans)
        ldy #0
:       lda VIEWBOT             ; the row after the view
        cmp W_BOTR
        beq :+
        sta W_BOTR
        ldy #0
:       lda #$80                ; no plane colours of the frame before (the
        sta W_LCC+1             ;   colormaps can change between frames)
        sta W_LFC+1
        lda W_FSC               ; the stamp of this frame
        inc a
        sta W_FSC
        bit #$7F
        bne :+
        jsr fsfill
:       cpy #0
        beq :+
        dec a
:       sta W_FSP
        rts

; fsfill: every span stamp (the top and bottom spans of each column) =
; A ^ $80. A kept.
fsfill: eor #$80
        ldx #0
:       sta FSSTT,x
        sta FSSTB,x
        inx
        cpx #VIEWWIDTH
        bne :-
        eor #$80
        rts

; ---------------------------------------------------------------------------
; nr_wskip: weaponClipSame after weaponClip (r_frame65.s:896-943). T0: the
; frame before skipped (FR_SKIP was not 0), so WCLIP holds this weapon.
; ---------------------------------------------------------------------------
nr_wskip:
        lda FR_SKIP
        ora FR_SKIP+1
        sta T0
        stz FR_SKIP
        stz FR_SKIP+1
        lda PSPF                ; a weapon (bit 0), no flash (bit 1)
        cmp #1
        bne @none
        lda AUTOMAP             ; not the automap overlay (AM_ACTIVE |
        and #3                  ;   AM_OVERLAY)
        cmp #3
        beq @none
        lda FRVIS+VIS_COLORMAP  ; not the shadow weapon (no colormap)
        ora FRVIS+VIS_COLORMAP+1
        ora FRVIS+VIS_COLORMAP+2
        ora FRVIS+VIS_COLORMAP+3
        beq @none
        ldy W_FSW               ; Y = W_FSW: the view of the frame before
        ldx #VIS_SIZE - 1       ;   shows; WPREV = FRVIS, Y = 0 when they
:       lda FRVIS,x             ;   are not the same
        cmp WPREV,x
        beq :+
        ldy #0
        sta WPREV,x
:       dex
        bpl :--
        sty FR_SKIP
        tya
        beq @done
        lda T0                  ; the first frame that skips: WCLIP =
        bne @done               ;   floorclip
        ldx #0
:       lda FLOORCLIP,x
        sta WCLIP,x
        inx
        cpx #VIEWWIDTH
        bne :-
@done:  lda FR_SKIP
        sta W_WSK
        rts
@none:  lda #$FF                ; WPREV: none
        sta WPREV+VIS_LUMP
        sta WPREV+VIS_LUMP+1
        bra @done

nr_setup:
        ldx #3                  ; viewx, viewy, viewz, viewangle
:       lda PL_X,x
        sta VIEWX,x
        lda PL_Y,x
        sta VIEWY,x
        lda PL_VIEWZ,x
        sta VIEWZ,x
        lda PL_ANGLE,x
        sta VIEWANGLE,x
        dex
        bpl :-
        lda PL_ANGLE+2
        sta VIEWA16
        lda PL_ANGLE+3
        sta VIEWA16+1
        lda PL_XLIGHT           ; extralight; LT_BASE = extralight +
        sta EXTRALIGHT          ;   gamma + 16
        clc
        adc GAMMA
        tax
        lda PL_XLIGHT+1
        sta EXTRALIGHT+1
        adc GAMMA+1
        tay
        clc
        txa
        adc #16
        sta LT_BASE
        tya
        adc #0
        sta LT_BASE+1
        lda PL_FIXCM            ; the fixed colormap: its low byte * 256,
        ora PL_FIXCM+1          ;   else none ($FFFF)
        beq :+
        stz LT_FIXED
        lda PL_FIXCM
        sta LT_FIXED+1
        bra :++
:       lda #$FF
        sta LT_FIXED
        sta LT_FIXED+1
:       jsr @angle              ; viewsin, viewcos: angle >> 3
        jsr sineapprox
        ldx #3
:       lda M_R,x
        sta VIEWSIN,x
        dex
        bpl :-
        jsr @angle
        jsr cosineapprox
        ldx #3
:       lda M_R,x
        sta VIEWCOS,x
        dex
        bpl :-
        inc VALIDCOUNT          ; a new validcount
        bne :+
        inc VALIDCOUNT+1
:       rts
@angle: lda VIEWA16+1           ; M_A = viewangle16 >> 3
        lsr a
        sta M_A+1
        lda VIEWA16
        ror a
        lsr M_A+1
        ror a
        lsr M_A+1
        ror a
        sta M_A
        rts

nr_clear:
        lda VIEWTOP             ; the clips + 1 of the view's rows
        inc a
        tay
        lda VIEWBOT
        inc a
        sta T0
        ldx #VIEWWIDTH
:       dex
        stz SOLIDCOL,x
        tya
        sta CEILCLIP,x
        lda T0
        sta FLOORCLIP,x
        txa
        bne :-
        stz DSCOUNT
        stz LASTOPEN
        stz LASTOPEN+1
        rts
