; wpsp.s: the player's weapon, the part both images run (docs/RENDER-
; MASKED.md): pspSprite's vissprite,
; the profile's lookup and wpStart. A GPL-2 derivative of Webifi's IIgs
; DOOM (build/upstream/src/iigs/r_frame65.s psSetup, pspSprite,
; :669-854; r_sprite65.s wpFind, wpStart, :884-917, :1180-1257), written
; for the 65C02 with the weapon profiles tools/native/levelconv.py makes
; (bank WPRO: WPIDX, then upstream's layout of each profile).
;
; The file is assembled twice (render.mk), as rrec.s is: for the front
; end's image (RENDERW: the weapon's clip pass, wclip.s) and, with -D MPSP,
; for the masked phase's (MASKW: the weapon's draw, mpsp.s), each copy with
; its own names (an m before the masked one's).
;
;   ps_vis      pspSprite's vissprite (R_DrawPSprite) of psprite X (0 the
;               weapon, 1 the flash) into FRVIS, from the render inputs:
;               the sprite frame (SPRFR: SFIRST[sprite] + (frame & $7FFF))
;               and its rotation 0's patch, the patch header (WPHB), x1 =
;               80 + (sx - 160 - leftoffset) / 2 and x2 = 79 + (the same +
;               width) / 2 (arithmetic halves), texturemid = 100 << 16 -
;               sy + topoffset << 16, x1 and x2 clipped to the view,
;               startfrac's high word 2 (x1' - x1), the colormap's record
;               page (0: the shadow weapon; the fixed colormap's; full
;               bright; else CMOP[SMAP[(light >> 4) + LT_BASE] - 23], Doom's
;               spritelights[MAXLIGHTSCALE - 1]). C set: no state (PSPF),
;               or off the side (FRVIS keeps what upstream's FR_VIS keeps:
;               the patch and the unclipped x2 are written first).
;   wp_find     the profile of FRVIS's patch (WPIDX) into WP_K. C set:
;               none (the lump's profile cannot be made: R_DrawVisSprite).
;   wp_start    wpStart for FRVIS and the profile WP_K: its header (WPHD),
;               V_YH0 (WP_YH0), V_HI (WP_VHI: viewbottom, screenheight-
;               array's rows), hi (WP_HI), the columns (WP_N: those of the
;               first column's parity from startfrac's column on, at most
;               to the view's right side) and their table entries (WPENT).
;               A = 0: go; 1: no column or no post shows (nothing to do);
;               2: the old code (hi of 255 or more, a first column past the
;               patch, a post above row 0). The front end's (speed wave 2,
;               RENDER-MASKED.md): in a run of frames
;               that skip the weapon rows (the frame before skipped,
;               FR_SKIP) with this frame's vissprite the same (FRVIS =
;               WPREV) and its view bottom (WCLIP's column 0, outside the
;               weapon, holds the first skipping frame's viewbottom + 1),
;               WCLIP is FLOORCLIP after that frame's clip pass, made of the
;               same vissprite, profile and view: FLOORCLIP = WCLIP, A = 1
;               (nw_clip has nothing more to do).
;   wp_list     the list of posts of the column whose entry WP_E points at
;               into WPLST (16 bytes; 56 more when its end is not in them).
;   wp_yh0      WP_YH0 = (CENTERY << 16 - texturemid - 1) >> 16.
;
; Their zero page is rlayout.py's OVW (overlay 2 from MW_SC on).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

.ifdef MPSP
        .define PS_VIS mps_vis
        .define WP_FIND mwp_find
        .define WP_START mwp_start
        .define WP_LIST mwp_list
        .define WP_YH0F mwp_yh0
        .define WP_HEAD mwp_head
        .define TSMAP smap
        .define TCMOP cmop
        .define TSFLO sfirst_lo
        .define TSFHI sfirst_hi
        .import far_get, smap, cmop, sfirst_lo, sfirst_hi
        .export mps_vis, mwp_find, mwp_start, mwp_list, mwp_yh0, mwp_head
        .segment "MASKW"
.else
        .define PS_VIS ps_vis
        .define WP_FIND wp_find
        .define WP_START wp_start
        .define WP_LIST wp_list
        .define WP_YH0F wp_yh0
        .define WP_HEAD wp_head
        .define TSMAP SMAP
        .define TCMOP wcmop
        .define TSFLO wsflo
        .define TSFHI wsfhi
        .import far_get, SMAP
        .export ps_vis, wp_find, wp_start, wp_list, wp_yh0, wp_head
        .segment "RENDERW"
.endif

; ===========================================================================
; ps_vis
; ===========================================================================
PS_VIS:
        stx WP_PSP
        lda psp_bit,x           ; a state?
        and PSPF
        bne :+
        sec
        rts
:       ldy psp_ofs,x           ; Y = the psprite's render inputs
        sty WP_PO
        ldx PSP0_SPR,y          ; SPRFR index = SFIRST[sprite] + (frame &
        lda PSP0_FRAME+1,y      ;   $7FFF)
        and #$7F
        sta WP_T+1
        clc
        lda PSP0_FRAME,y
        adc TSFLO,x
        sta WP_T
        lda WP_T+1
        adc TSFHI,x
        sta WP_T+1
        asl WP_T                ; SPRFRBASE + 24 i = 8 i + 16 i
        rol WP_T+1
        asl WP_T
        rol WP_T+1
        asl WP_T
        rol WP_T+1
        lda WP_T
        asl a
        sta FA_SRC
        lda WP_T+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc WP_T
        sta FA_SRC
        lda FA_SRC+1
        adc WP_T+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SPRFRBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SPRFRBASE
        sta FA_SRC+1
        lda #<WSFR
        sta FA_DST
        lda #>WSFR
        sta FA_DST+1
        lda #SPRT
        sta FA_BANK
        lda #SPRFR_SIZE
        sta FA_N
        jsr far_get
        lda WSFR+SF_FLAGS       ; upstream reads past the sprite's frames
        and #SPRFR_BAD
        beq :+
        lda #ST_SPRFRAME
        sta STATUS
        brk
        .byte ST_SPRFRAME
:       lda WSFR+SF_LUMPS       ; the lump of rotation 0 (upstream's lump[0])
        sta FRVIS+FV_PATCH
        lda WSFR+SF_LUMPS+1
        sta FRVIS+FV_PATCH+1
        jsr WP_HEAD             ; its header: width, leftoffset, topoffset
        ldy WP_PO
        sec                     ; tx = sx - BASEXCENTER - leftoffset
        lda PSP0_SX,y
        sbc #<160
        sta WP_TX
        lda PSP0_SX+1,y
        sbc #>160
        sta WP_TX+1
        sec
        lda WP_TX
        sbc WPHB+PH_LEFT
        sta WP_TX
        lda WP_TX+1
        sbc WPHB+PH_LEFT+1
        sta WP_TX+1
        cmp #$80                ; x1 = CENTERX + (tx >> 1), arithmetic
        ror a
        sta WP_X1+1
        lda WP_TX
        ror a
        clc
        adc #VIEWWIDTH / 2
        sta WP_X1
        bcc :+
        inc WP_X1+1
:       clc                     ; tx += width; x2 = CENTERX + (tx >> 1) - 1
        lda WP_TX
        adc WPHB+PH_WIDTH
        sta WP_TX
        lda WP_TX+1
        adc WPHB+PH_WIDTH+1
        cmp #$80
        ror a
        sta WP_T+1
        lda WP_TX
        ror a
        clc
        adc #VIEWWIDTH / 2 - 1
        sta FRVIS+FV_X2
        lda WP_T+1
        adc #0
        sta FRVIS+FV_X2+1
        bmi @off                ; x2 < 0
        sec                     ; x1 > VIEWWIDTH: off (x1 - 161 >= 0,
        lda WP_X1               ;   signed)
        sbc #<(VIEWWIDTH + 1)
        lda WP_X1+1
        sbc #>(VIEWWIDTH + 1)
        bvc :+
        eor #$80
:       bmi @on
@off:   sec
        rts
@on:    ldy WP_PO
        sec                     ; texturemid = BASEYCENTER << 16 - (sy -
        lda #0                  ;   topoffset << 16)
        sbc PSP0_SY,y
        sta FRVIS+FV_TMID
        lda #0
        sbc PSP0_SY+1,y
        sta FRVIS+FV_TMID+1
        lda #100
        sbc PSP0_SY+2,y
        sta WP_T
        lda #0
        sbc PSP0_SY+3,y
        sta WP_T+1
        clc
        lda WP_T
        adc WPHB+PH_TOP
        sta FRVIS+FV_TMID+2
        lda WP_T+1
        adc WPHB+PH_TOP+1
        sta FRVIS+FV_TMID+3
        lda WP_X1+1             ; x1 = max(x1, 0); startfrac's high word
        bpl @x1                 ;   = xiscale (2.0) * (x1' - x1)
        stz FRVIS+FV_X1
        sec
        lda #0
        sbc WP_X1
        sta WP_T
        lda #0
        sbc WP_X1+1
        asl WP_T
        rol a
        sta FRVIS+FV_SFRAC+1
        lda WP_T
        sta FRVIS+FV_SFRAC
        bra @x2
@x1:    lda WP_X1
        sta FRVIS+FV_X1         ; (0-160)
        stz FRVIS+FV_SFRAC
        stz FRVIS+FV_SFRAC+1
@x2:    lda FRVIS+FV_X2+1       ; x2 = min(x2, VIEWWIDTH - 1) (x2 >= 0)
        bne @clamp
        lda FRVIS+FV_X2
        cmp #VIEWWIDTH
        bcc @map
@clamp: lda #VIEWWIDTH - 1
        sta FRVIS+FV_X2
        stz FRVIS+FV_X2+1
@map:   sec                     ; the shadow weapon: invisibility - 129 >=
        lda PL_INVIS            ;   0 (16 bits, signed), or its bit 3
        sbc #<129
        lda PL_INVIS+1
        sbc #>129
        bpl @shadow
        lda PL_INVIS
        and #8
        bne @shadow
        lda LT_FIXED+1          ; the fixed colormap
        bmi :+
        clc
        adc #CMAPA_PAGE
        bra @page
:       ldy WP_PO               ; FF_FULLBRIGHT: the full colormap
        lda PSP0_FRAME+1,y
        bpl :+
        lda #CMAPA_PAGE
        bra @page
:       lda PL_SECLIGHT         ; CMOP[SMAP[(light >> 4) + LT_BASE] - 23]
        lsr a                   ;   (R_SpriteColorMap with X = $FFFF: d
        lsr a                   ;   23)
        lsr a
        lsr a
        clc
        adc LT_BASE
        tax
        lda TSMAP,x
        sec
        sbc #23
        tax
        lda TCMOP,x
        bra @page
@shadow:
        lda #0
@page:  sta FRVIS+FV_PAGE
        clc
        rts

; ---------------------------------------------------------------------------
; wp_head: FRVIS's patch header into WPHB (SPRT: PHDRBASE + 16 patch)
; ---------------------------------------------------------------------------
WP_HEAD:
        lda FRVIS+FV_PATCH
        sta FA_SRC
        lda FRVIS+FV_PATCH+1
        ldx #4
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<PHDRBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>PHDRBASE
        sta FA_SRC+1
        lda #<WPHB
        sta FA_DST
        lda #>WPHB
        sta FA_DST+1
        lda #SPRT
        sta FA_BANK
        lda #PHDR_SIZE
        sta FA_N
        jmp far_get

; ===========================================================================
; wp_find: WP_K = WPIDX[FRVIS's patch]; C set when $FFFF
; ===========================================================================
WP_FIND:
        lda FRVIS+FV_PATCH
        asl a
        sta FA_SRC
        lda FRVIS+FV_PATCH+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<WPIDX
        sta FA_SRC
        lda FA_SRC+1
        adc #>WPIDX
        sta FA_SRC+1
        lda #<WP_K
        sta FA_DST
        stz FA_DST+1
        lda #WPRO
        sta FA_BANK
        lda #2
        sta FA_N
        jsr far_get
        lda WP_K
        and WP_K+1
        cmp #$FF                ; C set: $FFFF, none
        rts

; ===========================================================================
; wp_yh0: WP_YH0 = the high word of CENTERY << 16 - texturemid, less 1
; when its low word is 0 (V_YH0 of R_DrawVisSprite at unit scale). Changes
; A, WP_T.
; ===========================================================================
WP_YH0F:
        sec
        lda #0
        sbc FRVIS+FV_TMID
        sta WP_T
        lda #0
        sbc FRVIS+FV_TMID+1
        ora WP_T                ; (the low word's bytes: 0?)
        sta WP_T
        lda #CENTERY
        sbc FRVIS+FV_TMID+2
        sta WP_YH0
        lda #0
        sbc FRVIS+FV_TMID+3
        sta WP_YH0+1
        lda WP_T
        bne :+
        lda WP_YH0              ; a low word of 0: one less
        bne @lo
        dec WP_YH0+1
@lo:    dec WP_YH0
:       rts

; ===========================================================================
; wp_start
; ===========================================================================
WP_START:
.ifndef MPSP
        lda FR_SKIP             ; the clip pass of the frame before
        ora FR_SKIP+1
        beq @pass
        lda FRVIS+FV_X1
        beq @pass               ; (column 0 is the weapon's)
        ldx VIEWBOT
        inx
        cpx WCLIP
        bne @pass
        ldx #FV_SIZE - 1
:       lda FRVIS,x
        cmp WPREV,x
        bne @pass
        dex
        bpl :-
        ldx #VIEWWIDTH
:       lda WCLIP-1,x
        sta FLOORCLIP-1,x
        dex
        bne :-
        bra @none
@pass:
.endif
        lda WP_K                ; the profile's header
        sta FA_SRC
        lda WP_K+1
        sta FA_SRC+1
        lda #<WPHD
        sta FA_DST
        lda #>WPHD
        sta FA_DST+1
        lda #WPRO
        sta FA_BANK
        lda #WPH_SIZE
        sta FA_N
        jsr far_get
        jsr WP_YH0F
        lda VIEWBOT             ; V_HI: screenheightarray's viewbottom + 1,
        sta WP_VHI              ;   less 1; 0: nothing
        beq @none
        sec                     ; hi = V_HI - V_YH0: 0 or less, nothing;
        sbc WP_YH0              ;   255 or more, the old code
        sta WP_T
        lda #0
        sbc WP_YH0+1
        bmi @none
        bne @old
        lda WP_T
        beq @none
        cmp #255
        bcs @old
        sta WP_HI
        lda FRVIS+FV_SFRAC      ; c0 (startfrac's column) < width
        cmp WPHD+WPH_WIDTH
        lda FRVIS+FV_SFRAC+1
        sbc WPHD+WPH_WIDTH+1
        bcs @old
        clc                     ; V_YH0 + the minimum a >= 0: no post above
        lda WPHD+WPH_MINA       ;   row 0
        adc WP_YH0
        lda WPHD+WPH_MINA+1
        adc WP_YH0+1
        bpl @par
@old:   lda #2
        rts
@none:  lda #1
        rts
@par:   lda FRVIS+FV_SFRAC      ; the table of c0's parity
        lsr a
        ldx #WPH_NEVEN
        bcc :+
        ldx #WPH_NODD
:       lda FRVIS+FV_SFRAC+1    ; c0 >> 1
        lsr a
        sta WP_C+1
        lda FRVIS+FV_SFRAC
        ror a
        sta WP_C
        sec                     ; its columns from c0: count - c0 >> 1
        lda WPHD,x
        sbc WP_C
        sta WP_T
        lda WPHD+1,x
        sbc WP_C+1
        sta WP_T+1
        sec                     ; at most VIEWWIDTH - x1 (none: nothing)
        lda #VIEWWIDTH
        sbc FRVIS+FV_X1
        beq @none2
        ldy WP_T+1
        bne :+
        cmp WP_T
        bcc :+
        lda WP_T
:       sta WP_N
        asl WP_C                ; the first entry: its table + 2 (c0 >> 1)
        rol WP_C+1
        clc
        lda WPHD+WPH_TEVEN-WPH_NEVEN,x
        adc WP_C
        sta FA_SRC
        lda WPHD+WPH_TEVEN-WPH_NEVEN+1,x
        adc WP_C+1
        sta FA_SRC+1
        lda #<WPENT             ; the entries into WPENT, 2 N bytes (128 a
        sta FA_DST              ;   window)
        lda #>WPENT
        sta FA_DST+1
        lda WP_N
        asl a
        sta WP_T
        lda #0
        rol a
        sta WP_T+1
@get:   lda WP_T+1
        bne @big
        lda WP_T
        beq @go
        cmp #129
        bcc @part
@big:   lda #128
@part:  sta FA_N
        jsr far_get
        clc
        lda FA_SRC
        adc FA_N
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       clc
        lda FA_DST
        adc FA_N
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       sec
        lda WP_T
        sbc FA_N
        sta WP_T
        bcs @get
        dec WP_T+1
        bra @get
@go:    lda #0
        rts
@none2: lda #1
        rts

; ===========================================================================
; wp_list: the list the entry at WP_E names into WPLST
; ===========================================================================
WP_LIST:
        lda (WP_E)
        sta FA_SRC
        ldy #1
        lda (WP_E),y
        sta FA_SRC+1
        lda #<WPLST
        sta FA_DST
        lda #>WPLST
        sta FA_DST+1
        lda #WPRO
        sta FA_BANK
        lda #16
        sta FA_N
        jsr far_get
        lda WPLST               ; its end (a + 1 = 0) at a post's start in
        beq @done               ;   the 16 bytes?
        lda WPLST+WP_POST
        beq @done
        lda WPLST+2*WP_POST
        beq @done
        lda WPLST+3*WP_POST
        beq @done
        clc                     ; the rest: 14 posts and the end at most
        lda FA_SRC
        adc #16
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       lda #<(WPLST + 16)
        sta FA_DST
        lda #>(WPLST + 16)
        sta FA_DST+1
        lda #56
        sta FA_N
        jmp far_get
@done:  rts

; ---------------------------------------------------------------------------
; Constants: each psprite's render inputs' offset and PSPF bit; the front
; end's copies of CMOP and SFIRST (rtables.py; the masked image has
; mproj.s's)
; ---------------------------------------------------------------------------
psp_ofs:
        .byte 0, PSP1_SPR - PSP0_SPR
psp_bit:
        .byte 1, 2
.ifndef MPSP
wcmop:  .incbin "cmop.bin"
wsflo:  .incbin "sfirst.bin", 0, NUMSPRITES
wsfhi:  .incbin "sfirst.bin", NUMSPRITES, NUMSPRITES
.endif
