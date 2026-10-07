; msprite.s: R_DrawSprite of the native renderer's masked phase
; (docs/RENDER-MASKED.md). A GPL-2
; derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/r_sprite65.s
; R_DrawSprite, dsLoop, clipIt, ltScale2, clipPtr, dsVisible, :481-561,
; :1460-1716; r_data65.s R_PointOnSegSide, :768-): the same clips, the
; same masked ranges drawn in the middle of the scan, the same test of
; whether the sprite can show, written for the 65C02 with the drawsegs
; copied into W (DSW) and the openings read through the far layer.
;
;   nm_drawsprite  X = the vissprite (its index). The clips of its columns
;               x1 .. x2 start at the view's (viewbottom + 1, viewtop + 1:
;               the arrays hold the clips + 1); the drawsegs from the last
;               to the first, those whose columns (DSX1, DSX2) meet the
;               sprite's: behind the sprite (both scales less than its
;               scale, or one of them and the sprite on the front side of
;               the seg) a drawseg draws its masked columns r1 .. r2 now
;               (mwall.s nm_mwall); in front, its silhouettes clip the
;               columns not clipped yet (upstream's test against the view
;               bottom + 1 and the view top + 1). Then dsVisible: an open
;               column in x1 .. x2 + 1, or past them the column x2 + 2 when
;               the texture can reach it; then mvis.s nm_vis with the clips.
;   md_dsptr    DS_P = drawseg DS_K: its copy in DSW (slot DS_SLOT), or
;               for a slot past DSW_MAX a fetch from RENDB into DSB.
;   md_cliprun  a clip array of the drawseg (A low, X high: an opening
;               index less x1, or DS_SCREENH, DS_NEGONE) for the columns
;               DS_R1 .. DS_R2 into FA_DST (CLIPBUF, MCCLIP): the openings'
;               low bytes (aux 0, one window), or the view's bottom + 1,
;               or 0.
;   nm_ptseg    R_PointOnSegSide(the thing's x and y, the drawseg's seg):
;               C set for the back side.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, fixmul, fixmul3216, nm_vis, nm_mwall
        .import vis_lo, vis_hi
        .export nm_drawsprite, md_dsptr, md_cliprun, nm_ptseg, md_phdr

        .segment "MASKW"

; ===========================================================================
; nm_drawsprite
; ===========================================================================
nm_drawsprite:
        stx DS_IDX
        lda vis_lo,x
        sta DS_VP
        lda vis_hi,x
        sta DS_VP+1
        ldy #VR_X1
        lda (DS_VP),y
        sta SP_X1
        ldy #VR_X2
        lda (DS_VP),y
        sta SP_X2
        ldx SP_X1               ; clipbot[x] = viewbottom + 1, cliptop[x] =
        cpx SP_X2               ;   viewtop + 1 for x1 .. x2
        beq @init
        bcs @scan
@init:  lda SPRBOT
        sta FLOORCLIP,x
        lda SPRTOP
        sta CEILCLIP,x
        cpx SP_X2
        inx
        bcc @init
@scan:  lda DS_TOT              ; the drawsegs from the last to the first:
        sta DS_SLOT             ;   DS_SLOT counts the slots of those that
        lda DSCOUNT             ;   clip (DSX1 not 255)
        sta DS_K
@ds:    lda DS_K
        bne :+
        jmp @end
:       dec DS_K
        ldx DS_K
        lda DSX1,x              ; (255: neither clips nor has masked columns)
        cmp #$FF
        beq @ds
        dec DS_SLOT
        cmp SP_X2               ; ds->x1 >= spr->x2 + 1
        beq :+
        bcs @ds
:       lda DSX2,x              ; ds->x2 < spr->x1
        cmp SP_X1
        bcc @ds
        lda DSX1,x              ; r1 = max(ds->x1, x1), r2 = min(ds->x2, x2)
        cmp SP_X1
        bcs :+
        lda SP_X1
:       sta DS_R1
        lda DSX2,x
        cmp SP_X2
        bcc :+
        lda SP_X2
:       sta DS_R2
        jsr md_dsptr
        ; max(scale1, scale2) < spr->scale: behind; else min(scale1,
        ; scale2) < spr->scale: behind when the sprite is on the front side
        ldy #DS_SCALE1
        jsr ltscale
        php
        ldy #DS_SCALE2
        jsr ltscale
        bpl @ge2
        plp                     ; scale2 < scale: and scale1?
        bmi @behind
        bra @side
@ge2:   plp                     ; scale2 >= scale: and scale1?
        bpl @clip
@side:  jsr nm_ptseg            ; the back side: it clips
        bcs @clip
@behind:
        ldy #DS_MASKED+1        ; its masked columns r1 .. r2 now
        lda (DS_P),y
        cmp #>DS_NULL
        bne :+
        dey
        lda (DS_P),y
        cmp #<DS_NULL
        beq @next
:       lda DS_R1
        sta MW_X
        lda DS_R2
        sta MW_X2
        jsr nm_mwall
@next:  jmp @ds

@clip:  ldy #DS_SIL             ; the bottom silhouette: sil & SIL_BOTTOM
        lda (DS_P),y            ;   and spr->gz < ds->bsilheight
        and #SIL_BOTTOM
        beq @top
        sec
        ldy #VR_GZ
        lda (DS_VP),y
        ldy #DS_BSIL
        sbc (DS_P),y
        ldy #VR_GZ+1
        lda (DS_VP),y
        ldy #DS_BSIL+1
        sbc (DS_P),y
        ldy #VR_GZ+2
        lda (DS_VP),y
        ldy #DS_BSIL+2
        sbc (DS_P),y
        ldy #VR_GZ+3
        lda (DS_VP),y
        ldy #DS_BSIL+3
        sbc (DS_P),y
        bvc :+
        eor #$80
:       bpl @top
        ldx DS_R1               ; a column not clipped yet?
:       lda FLOORCLIP,x
        cmp SPRBOT
        beq @bfetch
        cpx DS_R2
        inx
        bcc :-
        bra @top
@bfetch:
        lda #<CLIPBUF
        sta FA_DST
        lda #>CLIPBUF
        sta FA_DST+1
        ldy #DS_BOTCLIP+1
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr md_cliprun
        ldx DS_R1
        ldy #0
:       lda FLOORCLIP,x
        cmp SPRBOT
        bne :+
        lda CLIPBUF,y
        sta FLOORCLIP,x
:       iny
        cpx DS_R2
        inx
        bcc :--
@top:   ldy #DS_SIL             ; the top silhouette: sil & SIL_TOP and gzt
        lda (DS_P),y            ;   > ds->tsilheight (gzt: gz's low word,
        and #SIL_TOP            ;   GZT its high word)
        beq @next
        sec
        ldy #DS_TSIL
        lda (DS_P),y
        ldy #VR_GZ
        sbc (DS_VP),y
        ldy #DS_TSIL+1
        lda (DS_P),y
        ldy #VR_GZ+1
        sbc (DS_VP),y
        ldy #DS_TSIL+2
        lda (DS_P),y
        ldy #VR_GZT
        sbc (DS_VP),y
        ldy #DS_TSIL+3
        lda (DS_P),y
        ldy #VR_GZT+1
        sbc (DS_VP),y
        bvc :+
        eor #$80
:       bmi :+
        jmp @ds
:       ldx DS_R1
:       lda CEILCLIP,x
        cmp SPRTOP
        beq @tfetch
        cpx DS_R2
        inx
        bcc :-
        jmp @ds
@tfetch:
        lda #<CLIPBUF
        sta FA_DST
        lda #>CLIPBUF
        sta FA_DST+1
        ldy #DS_TOPCLIP+1
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr md_cliprun
        ldx DS_R1
        ldy #0
:       lda CEILCLIP,x
        cmp SPRTOP
        bne :+
        lda CLIPBUF,y
        sta CEILCLIP,x
:       iny
        cpx DS_R2
        inx
        bcc :--
        jmp @ds

@end:   ldy #VR_PATCH           ; the patch's header (PHB), then dsVisible
        lda (DS_VP),y
        tax
        iny
        lda (DS_VP),y
        jsr md_phdr
        jsr dsvis
        bcc @none
        lda #<FLOORCLIP         ; R_DrawVisSprite with the clips
        sta V_FCP
        lda #>FLOORCLIP
        sta V_FCP+1
        lda #<CEILCLIP
        sta V_CCP
        lda #>CEILCLIP
        sta V_CCP+1
        jmp nm_vis
@none:  rts

; ---------------------------------------------------------------------------
; ltscale: N = the drawseg's scale at Y < the sprite's scale (signed)
; ---------------------------------------------------------------------------
ltscale:
        sty MD_T
        sec
        lda (DS_P),y
        ldy #VR_SCALE
        sbc (DS_VP),y
        ldy MD_T
        iny
        lda (DS_P),y
        ldy #VR_SCALE+1
        sbc (DS_VP),y
        ldy MD_T
        iny
        iny
        lda (DS_P),y
        ldy #VR_SCALE+2
        sbc (DS_VP),y
        ldy MD_T
        iny
        iny
        iny
        lda (DS_P),y
        ldy #VR_SCALE+3
        sbc (DS_VP),y
        bvc :+
        eor #$80
:       ora #0                  ; (N from A)
        rts

; ---------------------------------------------------------------------------
; md_phdr: the patch header of the store index A:X (A the high byte) into
; PHB (SPRT: PHDRBASE + 16 index). One window.
; ---------------------------------------------------------------------------
md_phdr:
        stx FA_SRC
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
        lda #<PHB
        sta FA_DST
        lda #>PHB
        sta FA_DST+1
        lda #SPRT
        sta FA_BANK
        lda #PHDR_SIZE
        sta FA_N
        jmp far_get

; ---------------------------------------------------------------------------
; dsvis: dsVisible (r_sprite65.s:481-561). C set: the sprite can show.
; ---------------------------------------------------------------------------
dsvis:
        lda SP_X2               ; an open column in x1 .. min(x2 + 1, 159)
        clc
        adc #2
        cmp #VIEWWIDTH
        bcc :+
        lda #VIEWWIDTH
:       sta MD_T
        ldx SP_X1
@scan:  cpx MD_T
        bcs @beyond
        jsr opencol
        bcs @yes
        inx
        bra @scan
@beyond:
        cpx #VIEWWIDTH          ; x2 + 2 is past the view: none
        bcs @no
        lda PHB+PH_WIDTH+1      ; width < 512 and |xiscale| >= 1: the
        cmp #2                  ;   column x2 + 2 decides
        bcs @exact
        ldy #VR_XISCALE+2
        lda (DS_VP),y
        iny
        ora (DS_VP),y
        beq @exact
        ldy #VR_XISCALE+2
        lda (DS_VP),y
        iny
        and (DS_VP),y
        cmp #$FF
        beq @exact
        jmp opencol
@exact: ldy #VR_XISCALE         ; the texture column at x2 + 2: startfrac
        ldx #0                  ;   + FixedMul(xiscale, (x - x1) << 16)
:       lda (DS_VP),y
        sta M_A,x
        iny
        inx
        cpx #4
        bne :-
        stz M_B
        stz M_B+1
        lda MD_T
        sec
        sbc SP_X1
        sta M_B+2
        stz M_B+3
        jsr fixmul
        clc
        ldy #VR_STARTFRAC
        lda M_R
        adc (DS_VP),y
        iny
        lda M_R+1
        adc (DS_VP),y
        iny
        lda M_R+2
        adc (DS_VP),y
        tax
        iny
        lda M_R+3
        adc (DS_VP),y
        bmi @no                 ; frac < 0
        cpx PHB+PH_WIDTH        ; frac >> 16 < width: it can show
        sbc PHB+PH_WIDTH+1
        bcc @yes
@no:    clc
        rts
@yes:   sec
        rts

; opencol: C set when column X has an open row: floorclip - 1 >
; ceilingclip (floorclip 0: none)
opencol:
        lda FLOORCLIP,x
        beq @no
        dec a
        cmp CEILCLIP,x
        beq @no
        bcc @no
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; md_dsptr: DS_P = drawseg DS_K (DSW slot DS_SLOT, or fetched into DSB)
; ---------------------------------------------------------------------------
md_dsptr:
        lda DS_SLOT
        cmp #DSW_MAX
        bcs @far
        stz DS_P+1              ; DSW + 32 slot
        ldx #5
:       asl a
        rol DS_P+1
        dex
        bne :-
        clc
        adc #<DSW
        sta DS_P
        lda DS_P+1
        adc #>DSW
        sta DS_P+1
        rts
@far:   lda DS_K                ; DRAWSEGS + 32 k in RENDB
        stz FA_SRC+1
        ldx #5
:       asl a
        rol FA_SRC+1
        dex
        bne :-
        clc
        adc #<DRAWSEGS
        sta FA_SRC
        lda FA_SRC+1
        adc #>DRAWSEGS
        sta FA_SRC+1
        lda #<DSB
        sta FA_DST
        sta DS_P
        lda #>DSB
        sta FA_DST+1
        sta DS_P+1
        lda #RENDB
        sta FA_BANK
        lda #DS_SIZE
        sta FA_N
        jmp far_get

; ---------------------------------------------------------------------------
; md_cliprun: see above. A:X the field (A low), FA_DST the buffer.
; ---------------------------------------------------------------------------
md_cliprun:
        cpx #>DS_SCREENH        ; the markers ($7FFF, $7FFE)
        bne @open
        cmp #<DS_SCREENH
        beq @sha
        cmp #<DS_NEGONE
        beq @neg
@open:  clc                     ; OPENLO + the field + r1 (aux 0)
        adc DS_R1
        sta FA_SRC
        txa
        adc #0
        tax
        clc
        lda FA_SRC
        adc #<OPENLO
        sta FA_SRC
        txa
        adc #>OPENLO
        sta FA_SRC+1
        stz FA_BANK
        lda DS_R2
        sec
        sbc DS_R1
        inc a
        sta FA_N
        jmp far_get
@sha:   lda SPRBOT              ; screenheightarray: viewbottom + 1
        bra @fill
@neg:   lda #0                  ; negonearray: 0
@fill:  pha
        lda DS_R2
        sec
        sbc DS_R1
        sta MD_T+3              ; (the last index)
        pla
        ldy #0
:       sta (FA_DST),y
        cpy MD_T+3
        iny
        bcc :-
        rts

; ===========================================================================
; nm_ptseg: R_PointOnSegSide (r_data65.s:768-) of the vissprite's thing
; (TX, TY) and the drawseg's seg: its vertices from LVSEG (8 bytes into
; SEGB). C set: the back side.
; ===========================================================================
nm_ptseg:
        ldy #DS_SEG             ; SEGBASE + 24 seg = 8 seg + 16 seg
        lda (DS_P),y
        sta MD_T
        iny
        lda (DS_P),y
        sta MD_T+1
        asl MD_T
        rol MD_T+1
        asl MD_T
        rol MD_T+1
        asl MD_T
        rol MD_T+1
        lda MD_T
        asl a
        sta FA_SRC
        lda MD_T+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc MD_T
        sta FA_SRC
        lda FA_SRC+1
        adc MD_T+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SEGBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SEGBASE
        sta FA_SRC+1
        lda #<SEGB
        sta FA_DST
        lda #>SEGB
        sta FA_DST+1
        lda #LVSEG
        sta FA_BANK
        lda #8
        sta FA_N
        jsr far_get
        sec                     ; ldx, ldy: MD_T, MD_T+2
        lda SEGB+SEG_V2X
        sbc SEGB+SEG_V1X
        sta MD_T
        lda SEGB+SEG_V2X+1
        sbc SEGB+SEG_V1X+1
        sta MD_T+1
        sec
        lda SEGB+SEG_V2Y
        sbc SEGB+SEG_V1Y
        sta MD_T+2
        lda SEGB+SEG_V2Y+1
        sbc SEGB+SEG_V1Y+1
        sta MD_T+3
        lda MD_T
        ora MD_T+1
        bne @ldy
        ; !ldx: x <= lx << 16 ? ldy > 0 : ldy < 0
        sec
        lda #0
        ldy #VR_TX
        sbc (DS_VP),y
        lda #0
        iny
        sbc (DS_VP),y
        lda SEGB+SEG_V1X
        iny
        sbc (DS_VP),y
        lda SEGB+SEG_V1X+1
        iny
        sbc (DS_VP),y
        bvc :+
        eor #$80
:       bmi @yneg
@ypos:  lda MD_T+3              ; ldy > 0
        bmi @front
        ora MD_T+2
        beq @front
@back:  sec
        rts
@yneg:  lda MD_T+3              ; ldy < 0
        bmi @back
@front: clc
        rts
@ldy:   lda MD_T+2
        ora MD_T+3
        bne @signs
        ; !ldy: y <= ly << 16 ? ldx < 0 : ldx > 0
        sec
        lda #0
        ldy #VR_TY
        sbc (DS_VP),y
        lda #0
        iny
        sbc (DS_VP),y
        lda SEGB+SEG_V1Y
        iny
        sbc (DS_VP),y
        lda SEGB+SEG_V1Y+1
        iny
        sbc (DS_VP),y
        bvc :+
        eor #$80
:       bmi @xpos
        lda MD_T+1              ; ldx < 0
        bmi @back
        bra @front
@xpos:  lda MD_T+1              ; ldx > 0
        bmi @front
        ora MD_T
        beq @front
        bra @back
@signs: ; x -= lx << 16, y -= ly << 16: M_A (x), and y's high word in V_T
        ldy #VR_TX
        lda (DS_VP),y
        sta M_A
        iny
        lda (DS_VP),y
        sta M_A+1
        iny
        sec
        lda (DS_VP),y
        sbc SEGB+SEG_V1X
        sta M_A+2
        iny
        lda (DS_VP),y
        sbc SEGB+SEG_V1X+1
        sta M_A+3
        ldy #VR_TY+2
        sec
        lda (DS_VP),y
        sbc SEGB+SEG_V1Y
        sta V_T+2
        iny
        lda (DS_VP),y
        sbc SEGB+SEG_V1Y+1
        sta V_T+3
        eor M_A+3               ; the signs of y, x, ldx, ldy
        eor MD_T+1
        eor MD_T+3
        bpl @prod
        lda MD_T+3              ; ldy ^ x < 0: the back
        eor M_A+3
        bmi @back
        bra @front
@prod:  lda MD_T+2              ; right = FixedMul3216(x, ldy) (M_A: x)
        sta M_B
        lda MD_T+3
        sta M_B+1
        jsr fixmul3216
        ldx #3
:       lda M_R,x
        sta V_FRAC,x            ; (V_FRAC: free between sprites)
        dex
        bpl :-
        ldy #VR_TY              ; left = FixedMul3216(y, ldx)
        lda (DS_VP),y
        sta M_A
        iny
        lda (DS_VP),y
        sta M_A+1
        lda V_T+2
        sta M_A+2
        lda V_T+3
        sta M_A+3
        lda MD_T
        sta M_B
        lda MD_T+1
        sta M_B+1
        jsr fixmul3216
        sec                     ; left >= right (signed): the back
        lda M_R
        sbc V_FRAC
        lda M_R+1
        sbc V_FRAC+1
        lda M_R+2
        sbc V_FRAC+2
        lda M_R+3
        sbc V_FRAC+3
        bvc :+
        eor #$80
:       bmi :+
        sec                     ; the back
        rts
:       clc                     ; the front
        rts
