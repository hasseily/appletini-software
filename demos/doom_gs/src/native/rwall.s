; rwall.s: R_StoreWallRange of the native renderer (docs/RENDER.md 3.2;
; milestone 7, stage B): the drawseg, the scales, the heights, the marks
; and textures, the texture edges, the seg descriptor for R_RenderSegLoop,
; and after it the silhouettes and the clips saved for the sprites.
;
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_wall65.s, r_iigs65.s: R_StoreWallRange and its helpers,
; R_ScaleFromGlobalAngle): the same drawsegs, openings, clips and loop
; inputs, bit for bit, with upstream's shortcuts kept (RENDER.md 5.2):
; qmulh's "+ 0 or 1" in scaleFast and FIXAL, scaleFast's 1.001 step and
; its bail-outs to scaleSlow, distAny's 8-bit view fractions, the edges
; from the heights' shared low word, rowMod's remainder. The products are
; math.s's (exact where upstream's are exact: FMFAST is AH * B + cb modulo
; 2^32, a mul32 here); the divides are math.s's own (MATH.md: rowMod's
; remainder by sdiv16, scaleSlow's step by udiv32, upstream's own byte
; division there).
;
;   nr_storewall  A = start, X = stop (inclusive); BS_SEG, SEGR (the seg's
;               24 bytes), FSEC (the front sector), SC_CUR, FPC, CPC
;               (upstream's floorplane_color, ceilingplane_color: a
;               FLATCM byte, $FFFF none, $FFFE the sky), WBOT (worldbottom)
;               from the walk (rbsp.s, rlight.s); the frame block; RW_STEP
;               (rw_scalestep of the wall before). Out: the drawseg DSCOUNT
;               in RENDB, DSX1, DSX2, DSCOUNT + 1; the openings; LASTOPEN;
;               the line's bit in LNMAP; what R_RenderSegLoop makes
;               (rseg.s); RW_STEP.
;
; One upstream behaviour the harness must know: scaleSlow leaves
; rw_scalestep and the drawseg's scalestep as they were for a wall of one
; column (r_wall65.s:1975-1982); the edges of that wall are made with the
; old step, so RW_STEP is kept from wall to wall, and from frame to frame
; (the frame block), as upstream's rw_scalestep is.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, far_put, nr_segloop
        .import umul16, umul16lo, qmulh, mul8, mul32, fixmul, fixmul3216
        .import sdiv16, udiv32, approxdiv, mt_far, mt_recipe
        .export nr_storewall, sina, sinelow, rsga

; ---------------------------------------------------------------------------
; Macros: 32-bit operations on little-endian variables
; ---------------------------------------------------------------------------
.macro MOV32 p_src, p_dst
        lda p_src
        sta p_dst
        lda p_src+1
        sta p_dst+1
        lda p_src+2
        sta p_dst+2
        lda p_src+3
        sta p_dst+3
.endmacro

.macro SUB32 p_a, p_b, p_dst ; dst = a - b
        sec
        lda p_a
        sbc p_b
        sta p_dst
        lda p_a+1
        sbc p_b+1
        sta p_dst+1
        lda p_a+2
        sbc p_b+2
        sta p_dst+2
        lda p_a+3
        sbc p_b+3
        sta p_dst+3
.endmacro

.macro ADD32 p_a, p_b, p_dst ; dst = a + b
        clc
        lda p_a
        adc p_b
        sta p_dst
        lda p_a+1
        adc p_b+1
        sta p_dst+1
        lda p_a+2
        adc p_b+2
        sta p_dst+2
        lda p_a+3
        adc p_b+3
        sta p_dst+3
.endmacro

.macro NEG32 p_a
        sec
        lda #0
        sbc p_a
        sta p_a
        lda #0
        sbc p_a+1
        sta p_a+1
        lda #0
        sbc p_a+2
        sta p_a+2
        lda #0
        sbc p_a+3
        sta p_a+3
.endmacro

; SLT32 a, b: N = (a < b), signed 32-bit (upstream's SLT32). Changes A.
.macro SLT32 p_a, p_b
        lda p_a
        cmp p_b
        lda p_a+1
        sbc p_b+1
        lda p_a+2
        sbc p_b+2
        lda p_a+3
        sbc p_b+3
        bvc *+4                 ; (no label: a macro's own label would
        eor #$80                ;   end the caller's cheap local scope)
.endmacro

; EQ32 a, b: Z = (a == b). Changes A, SW_EQ.
.macro EQ32 p_a, p_b
        lda p_a
        eor p_b
        sta SW_EQ
        lda p_a+1
        eor p_b+1
        tsb SW_EQ
        lda p_a+2
        eor p_b+2
        tsb SW_EQ
        lda p_a+3
        eor p_b+3
        ora SW_EQ
.endmacro

        .segment "RENDERW"

; ===========================================================================
; nr_storewall: R_StoreWallRange(start, stop) (r_wall65.s:340-1029)
; ===========================================================================
nr_storewall:
        sta SW_START
        lda DSCOUNT             ; the drawsegs are full: nothing
        cmp #MAXDRAWSEGS
        bcc :+
        rts
:       inx                     ; rw_stopx = stop + 1
        stx X2END

        ; linedef->r_flags |= ML_MAPPED (a bit of LNMAP), the pegs
        ldy #SEG_LINE+1
        lda (SEGR),y
        sta SW_T+1
        dey
        lda (SEGR),y
        tax
        lsr SW_T+1              ; line >> 3
        ror a
        lsr SW_T+1
        ror a
        lsr SW_T+1
        ror a
        tay
        txa
        and #7
        tax
        lda LNMAP,y
        ora BITS,x
        sta LNMAP,y
        ldy #SEG_PEGS
        lda (SEGR),y
        sta SW_LF

        ; R_CheckOpenings: lastopening + 2 (rw_stopx - start) past
        ; MAXOPENINGS: nothing more
        sec
        lda X2END
        sbc SW_START
        asl a
        sta SW_T
        lda #0
        rol a
        sta SW_T+1
        clc
        lda SW_T
        adc LASTOPEN
        sta SW_T
        lda SW_T+1
        adc LASTOPEN+1
        sta SW_T+1
        lda #<MAXOPENINGS       ; need > MAXOPENINGS: return
        cmp SW_T
        lda #>MAXOPENINGS
        sbc SW_T+1
        bcs :+
        rts

        ; the side into its frame; rw_normalangle
:       ldy #SEG_SIDE           ; SIDEBASE + 8 side
        lda (SEGR),y
        sta FA_SRC
        iny
        lda (SEGR),y
        asl FA_SRC
        rol a
        asl FA_SRC
        rol a
        asl FA_SRC
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SIDEBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SIDEBASE
        sta FA_SRC+1
        lda #<FSIDE
        sta FA_DST
        lda #>FSIDE
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #SIDE_SIZE
        sta FA_N
        jsr far_get
        ldy #SEG_ANGLE
        lda (SEGR),y
        sta SD_NORMAL
        iny
        lda (SEGR),y
        sta SD_NORMAL+1

        ; D = (v1 - view) . n and OFF = (v1 - view) . (-sin, cos): along
        ; an axis differences, else distAny; rw_distance = floor(D)
        lda SD_NORMAL
        bne @any
        lda SD_NORMAL+1
        and #$3F
        beq @axis
@any:   jsr distany
        jmp @dist
@axis:  lda SD_NORMAL+1         ; the quadrant
        asl a
        bcs @n8c
        bmi @n4
        ldy #SEG_V1X            ; n = (1, 0): D = v1.x - viewx,
        jsr v1minus             ;   OFF = floor(v1.y - viewy)
        ldy #SEG_V1Y
        jsr v1floor
        bra @dist
@n4:    ldy #SEG_V1Y            ; n = (0, 1): D = v1.y - viewy,
        jsr v1minus2            ;   OFF = viewx.hi - v1.x
        sec
        ldy #SEG_V1X
        lda VIEWX+2
        sbc (SEGR),y
        sta SW_OFF
        iny
        lda VIEWX+3
        sbc (SEGR),y
        sta SW_OFF+1
        bra @dist
@n8c:   bmi @nc
        sec                     ; n = (-1, 0): D = viewx - v1.x,
        ldy #SEG_V1X            ;   OFF = viewy.hi - v1.y
        lda VIEWX
        sta SW_D
        lda VIEWX+1
        sta SW_D+1
        lda VIEWX+2
        sbc (SEGR),y
        sta SW_D+2
        iny
        lda VIEWX+3
        sbc (SEGR),y
        sta SW_D+3
        sec
        ldy #SEG_V1Y
        lda VIEWY+2
        sbc (SEGR),y
        sta SW_OFF
        iny
        lda VIEWY+3
        sbc (SEGR),y
        sta SW_OFF+1
        bra @dist
@nc:    sec                     ; n = (0, -1): D = viewy - v1.y,
        ldy #SEG_V1Y            ;   OFF = floor(v1.x - viewx)
        lda VIEWY
        sta SW_D
        lda VIEWY+1
        sta SW_D+1
        lda VIEWY+2
        sbc (SEGR),y
        sta SW_D+2
        iny
        lda VIEWY+3
        sbc (SEGR),y
        sta SW_D+3
        ldy #SEG_V1X
        jsr v1floorx
@dist:  lda SW_D+2              ; rw_distance = floor(D)
        sta SD_DIST
        lda SW_D+3
        sta SD_DIST+1

        ; the drawseg: curline, x1, x2
        lda BS_SEG
        sta DSBUF+DS_SEG
        lda BS_SEG+1
        sta DSBUF+DS_SEG+1
        lda SW_START
        sta DSBUF+DS_X1
        ldx X2END
        dex
        stx DSBUF+DS_X2

        ; the scales: scaleFast, or scaleSlow for D below 4 map units and
        ; for a scale at a clamp
        lda SW_D+3
        bmi @slow
        bne @fast
        lda SW_D+2
        cmp #4
        bcc @slow
@fast:  jsr scalefast
        beq @front
@slow:  jsr scaleslow

        ; worldtop = frontsector->ceilingheight - viewz (worldbottom: WBOT)
@front: SUB32 FSEC+SEC_CEIL, VIEWZ, WTOP
        ldy #SEG_BACK
        lda (SEGR),y
        cmp #NO_SECTOR
        bne :+
        jmp onesided
:       jmp twosided

; v1minus: SW_D = (v1.[Y] << 16) - view (VIEWX for SEG_V1X); v1minus2:
; the same with VIEWY. v1floor: SW_OFF = the high word of (v1.y << 16) -
; viewy; v1floorx: of (v1.x << 16) - viewx.
v1minus:
        sec
        lda #0
        sbc VIEWX
        sta SW_D
        lda #0
        sbc VIEWX+1
        sta SW_D+1
        lda (SEGR),y
        sbc VIEWX+2
        sta SW_D+2
        iny
        lda (SEGR),y
        sbc VIEWX+3
        sta SW_D+3
        rts
v1minus2:
        sec
        lda #0
        sbc VIEWY
        sta SW_D
        lda #0
        sbc VIEWY+1
        sta SW_D+1
        lda (SEGR),y
        sbc VIEWY+2
        sta SW_D+2
        iny
        lda (SEGR),y
        sbc VIEWY+3
        sta SW_D+3
        rts
v1floor:
        lda #0                  ; carry: no borrow from 0 - viewy.lo
        cmp VIEWY
        lda #0
        sbc VIEWY+1
        lda (SEGR),y
        sbc VIEWY+2
        sta SW_OFF
        iny
        lda (SEGR),y
        sbc VIEWY+3
        sta SW_OFF+1
        rts
v1floorx:
        lda #0
        cmp VIEWX
        lda #0
        sbc VIEWX+1
        lda (SEGR),y
        sbc VIEWX+2
        sta SW_OFF
        iny
        lda (SEGR),y
        sbc VIEWX+3
        sta SW_OFF+1
        rts

BITS:   .byte $01, $02, $04, $08, $10, $20, $40, $80

; ===========================================================================
; onesided: a single sided line (r_wall65.s:545-589)
; ===========================================================================
onesided:
        lda #<DS_NULL           ; ds_p->maskedtexturecol = NULL
        sta DSBUF+DS_MASKED
        lda #>DS_NULL
        sta DSBUF+DS_MASKED+1
        stz SW_EDGES
        lda #1                  ; markfloor = markceiling = 1, no masked,
        sta WMF                 ;   top or bottom texture
        sta WMC
        stz WMASKED
        stz WTOPTEX
        stz WBOTTEX
        ldy FSIDE+SIDE_MID      ; midtexture = texturetranslation[mid]
        lda TEXTRANS,y
        sta WMIDTEX
        jsr rowmod
        lda SW_LF
        and #ML_DONTPEGBOTTOM
        beq @top
        ldy FSIDE+SIDE_MID      ; the bottom at the bottom: worldbottom +
        clc                     ;   (r + textureheight[mid]) << 16
        lda SW_T
        adc TXHT,y
        tax
        lda SW_T+1
        adc #0
        tay
        txa
        ldx #<WBOT
        jsr midtexw
        bra @sil
@top:   lda SW_T                ; the top at the top: worldtop + r << 16
        ldy SW_T+1
        ldx #<WTOP
        jsr midtexv
@sil:   lda #SIL_BOTH           ; silBoth: sprtopclip = screenheightarray,
        sta SW_SIL              ;   sprbottomclip = negonearray, the
        lda #<DS_SCREENH        ;   heights INT32_MIN and INT32_MAX
        sta DSBUF+DS_TOPCLIP
        lda #>DS_SCREENH
        sta DSBUF+DS_TOPCLIP+1
        lda #<DS_NEGONE
        sta DSBUF+DS_BOTCLIP
        lda #>DS_NEGONE
        sta DSBUF+DS_BOTCLIP+1
        stz SW_OPEN
        jsr tsilmin
        jsr bsilmax
        jmp textured

; midtexw: SD_MIDMID = WBOT (the spill) + (Y:A << 16); midtexv: = the
; variable X of the wall variables (WTOP) + (Y:A << 16). The same for the
; top and bottom mids with midtop, midbot below.
midtexw:
        clc
        adc WBOT+2
        sta SD_MIDMID+2
        tya
        adc WBOT+3
        sta SD_MIDMID+3
        lda WBOT
        sta SD_MIDMID
        lda WBOT+1
        sta SD_MIDMID+1
        rts
midtexv:
        clc
        adc WTOP+2
        sta SD_MIDMID+2
        tya
        adc WTOP+3
        sta SD_MIDMID+3
        lda WTOP
        sta SD_MIDMID
        lda WTOP+1
        sta SD_MIDMID+1
        rts

; rowmod: SW_T (16 bits) = Mod(sidedef->rowoffset, textureheight[A]) (rowMod,
; r_wall65.s:1564-1590): 0 for a row offset of 0; a & (b - 1) for b a
; power of 2 (b = 0: a); else a % b (C, sdiv16), + b when negative.
rowmod:
        tax                     ; the texture
        lda FSIDE+SIDE_ROWOFS
        ora FSIDE+SIDE_ROWOFS+1
        bne :+
        stz SW_T
        stz SW_T+1
        rts
:       lda TXHT,x              ; b
        bne :+
        lda FSIDE+SIDE_ROWOFS   ; b = 0: b - 1 is $FFFF, a & b - 1 = a
        sta SW_T
        lda FSIDE+SIDE_ROWOFS+1
        sta SW_T+1
        rts
:       sta SW_T+2
        dec a
        and SW_T+2
        bne @mod
        lda SW_T+2              ; a & (b - 1)
        dec a
        and FSIDE+SIDE_ROWOFS
        sta SW_T
        stz SW_T+1
        rts
@mod:   lda FSIDE+SIDE_ROWOFS   ; r = a % b; r < 0: r + b
        sta M_A
        lda FSIDE+SIDE_ROWOFS+1
        sta M_A+1
        lda SW_T+2
        sta M_B
        stz M_B+1
        jsr sdiv16
        lda M_T
        sta SW_T
        lda M_T+1
        sta SW_T+1
        bpl :+
        clc
        lda SW_T
        adc SW_T+2
        sta SW_T
        lda SW_T+1
        adc #0
        sta SW_T+1
:       rts

; tsilmin: the drawseg's tsilheight = INT32_MIN; bsilmax: bsilheight =
; INT32_MAX
tsilmin:
        stz DSBUF+DS_TSIL
        stz DSBUF+DS_TSIL+1
        stz DSBUF+DS_TSIL+2
        lda #$80
        sta DSBUF+DS_TSIL+3
        rts
bsilmax:
        lda #$FF
        sta DSBUF+DS_BSIL
        sta DSBUF+DS_BSIL+1
        sta DSBUF+DS_BSIL+2
        lda #$7F
        sta DSBUF+DS_BSIL+3
        rts

; ===========================================================================
; twosided: a two sided line (r_wall65.s:596-843)
; ===========================================================================
twosided:
        sta FA_SRC              ; the back sector into BSEC: SECBASE + 16 n
        stz FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        clc
        lda FA_SRC
        adc #<SECBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SECBASE
        sta FA_SRC+1
        lda #<BSEC
        sta FA_DST
        lda #>BSEC
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #SEC_SIZE
        sta FA_N
        jsr far_get
        SUB32 BSEC+SEC_CEIL, VIEWZ, WHIGH       ; worldhigh
        SUB32 BSEC+SEC_FLOOR, VIEWZ, WLOW       ; worldlow
        lda #1                  ; its own clips; SIL_NONE; no mid texture
        sta SW_OPEN
        stz SW_SIL
        stz WMIDTEX

        ; the bottom silhouette: frontsector->floorheight >
        ; backsector->floorheight (worldlow < worldbottom), or the back
        ; floor above the view (worldlow > 0)
        SLT32 WLOW, WBOT
        bpl @low0
        ldx #3
:       lda FSEC+SEC_FLOOR,x
        sta DSBUF+DS_BSIL,x
        dex
        bpl :-
        bra @bsil
@low0:  lda WLOW+3
        bmi @top
        ora WLOW+2
        ora WLOW+1
        ora WLOW
        beq @top
        jsr bsilmax
@bsil:  lda #SIL_BOTTOM
        sta SW_SIL

        ; the top silhouette: worldtop < worldhigh, or the back ceiling
        ; below the view (worldhigh < 0)
@top:   SLT32 WTOP, WHIGH
        bpl @high0
        ldx #3
:       lda FSEC+SEC_CEIL,x
        sta DSBUF+DS_TSIL,x
        dex
        bpl :-
        bra @tsil
@high0: lda WHIGH+3
        bpl @closed
        jsr tsilmin
@tsil:  lda SW_SIL
        ora #SIL_TOP
        sta SW_SIL

        ; a closed door: worldhigh <= worldbottom or worldlow >= worldtop
@closed:
        ldx #1
        SLT32 WBOT, WHIGH
        bpl :+
        SLT32 WLOW, WTOP
        bpl :+
        dex
:       stx SW_T                ; 1: closed
        lda FSEC+SEC_CPIC       ; both skies: worldtop = worldhigh
        cmp SKYFLAT
        bne @marks
        lda BSEC+SEC_CPIC
        cmp SKYFLAT
        bne @marks
        MOV32 WHIGH, WTOP

        ; markfloor, markceiling: both for a closed door or other lights;
        ; else a plane whose height, pic differ
@marks: lda SW_T
        bne @both
        lda BSEC+SEC_LIGHT
        cmp FSEC+SEC_LIGHT
        bne @both
        ldx #0
        EQ32 WLOW, WBOT
        bne :+
        lda BSEC+SEC_FPIC
        cmp FSEC+SEC_FPIC
        beq :++
:       inx
:       stx WMF
        ldx #0
        EQ32 WHIGH, WTOP
        bne :+
        lda BSEC+SEC_CPIC
        cmp FSEC+SEC_CPIC
        beq :++
:       inx
:       stx WMC
        bra @tiers
@both:  lda #1
        sta WMF
        sta WMC

        ; the tiers: 1 worldhigh < worldtop (the top wall), 2 worldbottom
        ; < worldlow (the bottom wall)
@tiers: ldx #0
        SLT32 WHIGH, WTOP
        bpl :+
        inx
:       SLT32 WBOT, WLOW
        bpl :+
        inx
        inx
:       stx SW_EDGES
        txa
        lsr a
        bcs :+
        stz WTOPTEX
        jmp @bottex
:       ldy FSIDE+SIDE_TOP      ; toptexture = texturetranslation[top]
        lda TEXTRANS,y
        sta WTOPTEX
        jsr rowmod
        lda SW_LF
        and #ML_DONTPEGTOP
        beq @hitop
        lda SW_T                ; the top at the top: worldtop + r << 16
        ldy SW_T+1
        ldx #<WTOP
        jsr midtop
        bra @bottex
@hitop: ldy FSIDE+SIDE_TOP      ; worldhigh + (r + textureheight[top])
        clc                     ;   << 16
        lda SW_T
        adc TXHT,y
        tax
        lda SW_T+1
        adc #0
        tay
        txa
        ldx #<WHIGH
        jsr midtop

@bottex:
        lda SW_EDGES
        and #2
        bne :+
        stz WBOTTEX
        bra @masked
:       ldy FSIDE+SIDE_BOTTOM   ; bottomtexture = texturetranslation[bottom]
        lda TEXTRANS,y
        sta WBOTTEX
        jsr rowmod
        lda SW_LF
        and #ML_DONTPEGBOTTOM
        beq @lo
        lda SW_T                ; the bottom at the bottom: worldtop
        ldy SW_T+1
        ldx #<WTOP
        jsr midbot
        bra @masked
@lo:    lda SW_T                ; else worldlow
        ldy SW_T+1
        ldx #<WLOW
        jsr midbot

        ; a masked mid texture: its columns in the openings from
        ; lastopening (maskedtexturecol = lastopening - rw_x)
@masked:
        lda FSIDE+SIDE_MID
        bne :+
        stz WMASKED
        lda #<DS_NULL
        sta DSBUF+DS_MASKED
        lda #>DS_NULL
        sta DSBUF+DS_MASKED+1
        jmp textured
:       sec
        lda LASTOPEN
        sbc SW_START
        sta SD_MASKB
        sta DSBUF+DS_MASKED
        lda LASTOPEN+1
        sbc #0
        sta SD_MASKB+1
        sta DSBUF+DS_MASKED+1
        lda #1
        sta WMASKED
        sec
        lda X2END
        sbc SW_START
        clc
        adc LASTOPEN
        sta LASTOPEN
        bcc textured
        inc LASTOPEN+1
        bra textured

; midtop, midbot: SD_TOPMID, SD_BOTMID = the wall variable at X (low byte
; of its address; WTOP, WHIGH, WLOW are in SWVAR's page) + (Y:A << 16)
midtop: clc
        adc SWVAR_PAGE+2,x
        sta SD_TOPMID+2
        tya
        adc SWVAR_PAGE+3,x
        sta SD_TOPMID+3
        lda SWVAR_PAGE,x
        sta SD_TOPMID
        lda SWVAR_PAGE+1,x
        sta SD_TOPMID+1
        rts
midbot: clc
        adc SWVAR_PAGE+2,x
        sta SD_BOTMID+2
        tya
        adc SWVAR_PAGE+3,x
        sta SD_BOTMID+3
        lda SWVAR_PAGE,x
        sta SD_BOTMID
        lda SWVAR_PAGE+1,x
        sta SD_BOTMID+1
        rts
SWVAR_PAGE = WTOP & $FF00

; ===========================================================================
; textured: segtextured, rw_offset, rw_centerangle, rw_lightlevel; the
; marks of the planes the view cannot see; the edges; the seg loop; the
; silhouettes and clips (r_wall65.s:847-1029)
; ===========================================================================
textured:
        lda WMIDTEX
        ora WTOPTEX
        ora WBOTTEX
        ora WMASKED
        sta WSEGTEX
        beq @planes
        clc                     ; rw_offset = floor(OFF) + textureoffset
        lda SW_OFF              ;   + curline->offset
        adc FSIDE+SIDE_TEXOFS
        tax
        lda SW_OFF+1
        adc FSIDE+SIDE_TEXOFS+1
        sta SD_OFFSET+1
        txa
        ldy #SEG_OFFSET
        clc
        adc (SEGR),y
        sta SD_OFFSET
        iny
        lda SD_OFFSET+1
        adc (SEGR),y
        sta SD_OFFSET+1
        sec                     ; rw_centerangle = $4000 + viewangle16 -
        lda VIEWA16             ;   rw_normalangle
        sbc SD_NORMAL
        sta SD_CANGLE
        lda VIEWA16+1
        sbc SD_NORMAL+1
        clc
        adc #$40
        sta SD_CANGLE+1
        lda FSEC+SEC_LIGHT      ; rw_lightlevel
        sta SD_LIGHT

        ; no colour: no mark (the plane is on the view's other side)
@planes:
        lda CPC
        and CPC+1
        cmp #$FF
        bne :+
        stz WMC
:       lda FPC
        and FPC+1
        cmp #$FF
        bne :+
        stz WMF

        ; the edges of the tiers, one step early
:       jsr edgeal
        lda WMC
        ora WTOPTEX
        ora WMIDTEX
        beq :+
        MOV32 WTOP, SW_Q
        stz SW_ER
        ldx #TS
        jsr edge
:       lda WMF
        ora WBOTTEX
        ora WMIDTEX
        beq :+
        MOV32 WBOT, SW_Q
        lda #1
        sta SW_ER
        ldx #BS
        jsr edge
:       lda SW_EDGES
        lsr a
        bcc :+
        MOV32 WHIGH, SW_Q
        lda #1
        sta SW_ER
        ldx #PHS
        jsr edge
:       lda SW_EDGES
        and #2
        beq :+
        MOV32 WLOW, SW_Q
        stz SW_ER
        ldx #PLS
        jsr edge

        ; R_RenderSegLoop(rw_x)
:       stz DIDSOLID
        lda SW_START
        sta SD_X
        lda #20                 ; (the profiling build's phase 10)
        jsr mark
        jsr nr_segloop
        lda #18                 ; (phase 9)
        jsr mark

        ; a two sided line with its own clips: a column made solid needs
        ; the silhouettes
        lda SW_OPEN
        bne :+
        jmp @done
:       lda DIDSOLID
        beq @save
        lda SW_SIL
        and #SIL_BOTTOM
        bne :++
        ldx #3
:       lda BSEC+SEC_FLOOR,x
        sta DSBUF+DS_BSIL,x
        dex
        bpl :-
        lda SW_SIL
        ora #SIL_BOTTOM
        sta SW_SIL
:       lda SW_SIL
        and #SIL_TOP
        bne @save
        ldx #3
:       lda BSEC+SEC_CEIL,x
        sta DSBUF+DS_TSIL,x
        dex
        bpl :-
        lda SW_SIL
        ora #SIL_TOP
        sta SW_SIL

        ; the clips for the sprites
@save:  lda SW_SIL
        and #SIL_TOP
        ora WMASKED
        beq :+
        jsr saveceil
:       lda SW_SIL
        and #SIL_BOTTOM
        ora WMASKED
        beq :+
        jsr savefloor
:       lda WMASKED             ; a masked mid texture: both silhouettes
        beq @done
        lda SW_SIL
        and #SIL_TOP
        bne :+
        jsr tsilmin
:       lda SW_SIL
        and #SIL_BOTTOM
        bne :+
        jsr bsilmax
:       lda #SIL_BOTH
        sta SW_SIL

        ; the silhouette; the columns of the drawseg (x1 255: it neither
        ; clips sprites nor has a masked texture); the drawseg into RENDB
@done:  ldx DSCOUNT
        lda SW_SIL
        sta DSBUF+DS_SIL
        beq :+
        lda SW_START
        bra :++
:       lda #$FF
:       sta DSX1,x
        lda X2END
        dec a
        sta DSX2,x
        txa                     ; DRAWSEGS + 32 n
        stz FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        clc
        adc #<DRAWSEGS
        sta FA_DST
        lda FA_DST+1
        adc #>DRAWSEGS
        sta FA_DST+1
        lda #<DSBUF
        sta FA_SRC
        lda #>DSBUF
        sta FA_SRC+1
        lda #RENDB
        sta FA_BANK
        lda #DS_SIZE
        sta FA_N
        jsr far_put
        inc DSCOUNT
        rts

; mark: the cost phase A / 2 in the profiling build (RENDER.md 4.2)
mark:
.ifdef RPROF
        sta PHASE
.endif
        rts

; saveceil, savefloor: the clip + 1 of the wall's columns into the
; openings from lastopening; the drawseg's clip field = lastopening -
; start (saveClip, r_wall65.s:1598-1625)
saveceil:
        jsr saveat
        sta DSBUF+DS_TOPCLIP
        stx DSBUF+DS_TOPCLIP+1
        sta RAMWRTON
        ldy SW_START
:       lda CEILCLIP,y
        sta (FA_DST),y
        iny
        cpy X2END
        bcc :-
        sta RAMWRTOFF
        bra saved
savefloor:
        jsr saveat
        sta DSBUF+DS_BOTCLIP
        stx DSBUF+DS_BOTCLIP+1
        sta RAMWRTON
        ldy SW_START
:       lda FLOORCLIP,y
        sta (FA_DST),y
        iny
        cpy X2END
        bcc :-
        sta RAMWRTOFF
saved:  sec                     ; lastopening += rw_stopx - start
        lda X2END
        sbc SW_START
        clc
        adc LASTOPEN
        sta LASTOPEN
        bcc :+
        inc LASTOPEN+1
:       rts
; saveat: X:A = lastopening - start; FA_DST = OPENLO + that
saveat: sec
        lda LASTOPEN
        sbc SW_START
        pha
        lda LASTOPEN+1
        sbc #0
        tax
        clc
        pla
        pha
        adc #<OPENLO
        sta FA_DST
        txa
        adc #>OPENLO
        sta FA_DST+1
        pla
        rts

; ===========================================================================
; distany: SW_D = D, SW_OFF = floor(OFF) for a seg not along an axis
; (distAny, r_wall65.s:1279-1327): (c, s) the unit vector of
; rw_normalangle, v1 - view = (dx - fx, dy - fy) with the map units dx =
; v1.x - viewx.hi and the fraction fx = viewx's byte 1:
;   D = dx c + dy s - (fx c + fy s),  OFF = dy c - dx s - (fy c - fx s)
; ===========================================================================
distany:
        sec                     ; dx, dy
        ldy #SEG_V1X
        lda (SEGR),y
        sbc VIEWX+2
        sta SW_DX
        iny
        lda (SEGR),y
        sbc VIEWX+3
        sta SW_DX+1
        sec
        iny
        lda (SEGR),y
        sbc VIEWY+2
        sta SW_DY
        iny
        lda (SEGR),y
        sbc VIEWY+3
        sta SW_DY+1
        clc                     ; c
        lda SD_NORMAL
        ldx SD_NORMAL+1
        pha
        txa
        adc #$40
        tax
        pla
        jsr sina
        jsr sfrac
        lda VIEWX+1             ; D = dx c - fx c
        ldx #SW_DX - SWVAR_PAGE
        jsr fmulv
        MOV32 SW_Q, SW_D
        lda VIEWY+1             ; O = dy c - fy c
        ldx #SW_DY - SWVAR_PAGE
        jsr fmulv
        MOV32 SW_Q, SW_O
        lda SD_NORMAL           ; s
        ldx SD_NORMAL+1
        jsr sina
        jsr sfrac
        lda VIEWY+1             ; D += dy s - fy s
        ldx #SW_DY - SWVAR_PAGE
        jsr fmulv
        ADD32 SW_D, SW_Q, SW_D
        lda VIEWX+1             ; OFF = O - (dx s - fx s)
        ldx #SW_DX - SWVAR_PAGE
        jsr fmulv
        SUB32 SW_O, SW_Q, SW_Q
        lda SW_Q+2
        sta SW_OFF
        lda SW_Q+3
        sta SW_OFF+1
        rts

; sfrac: SW_M = MT_E (the magnitude, 0.16), SW_BS = the carry in bit 7
; (the sign)
sfrac:  lda MT_E
        sta SW_M
        lda MT_E+1
        sta SW_M+1
        lda #0
        ror a
        sta SW_BS
        rts

; fmulv: SW_Q = (d - f / 256) * the fraction (SW_M, SW_BS), 16.16, for the
; signed map units d (the wall variable at SWVAR_PAGE + X) and the byte f
; = A: d * m less f * the high byte of m (fmulv, r_wall65.s:1343-1391),
; the sign of the product (d <= 0) ^ the sign of m, as upstream computes
; it (the sign bit of (d - 1) ^ SW_BS)
fmulv:  ldy SW_M+1              ; T = f * m8
        jsr mul8
        lda M_R
        sta SW_T
        lda M_R+1
        sta SW_T+1
        sec                     ; the sign: bit 15 of (d - 1) ^ SW_BS
        lda SWVAR_PAGE,x
        sbc #1
        lda SWVAR_PAGE+1,x
        sbc #0
        eor SW_BS
        sta SW_T+2
        lda SWVAR_PAGE+1,x      ; d > 0: d * m - T
        bmi @neg
        ora SWVAR_PAGE,x
        beq @neg
        lda SWVAR_PAGE,x
        sta M_B
        lda SWVAR_PAGE+1,x
        sta M_B+1
        jsr @mul
        sec
        lda SW_Q
        sbc SW_T
        sta SW_Q
        lda SW_Q+1
        sbc SW_T+1
        sta SW_Q+1
        lda SW_Q+2
        sbc #0
        sta SW_Q+2
        lda SW_Q+3
        sbc #0
        sta SW_Q+3
        bra @sign
@neg:   sec                     ; d <= 0: -d * m + T
        lda #0
        sbc SWVAR_PAGE,x
        sta M_B
        lda #0
        sbc SWVAR_PAGE+1,x
        sta M_B+1
        jsr @mul
        clc
        lda SW_Q
        adc SW_T
        sta SW_Q
        lda SW_Q+1
        adc SW_T+1
        sta SW_Q+1
        lda SW_Q+2
        adc #0
        sta SW_Q+2
        lda SW_Q+3
        adc #0
        sta SW_Q+3
@sign:  bit SW_T+2
        bpl :+
        NEG32 SW_Q
:       rts
@mul:   lda SW_M                ; SW_Q = m * M_B, unsigned
        sta M_A
        lda SW_M+1
        sta M_A+1
        jsr umul16
        MOV32 M_R, SW_Q
        rts

; ===========================================================================
; sina: MT_E = |finesineapprox((X:A) >> 3)|, the table value (sinA,
; r_wall65.s:1227-1248), carry = its sign (the angle >> 3 at 4096 or
; more). The quarter table in the tables bank. Changes A, X, Y, MT_P.
; ===========================================================================
sina:   sta MT_P
        txa
        lsr a
        ror MT_P
        lsr a
        ror MT_P
        lsr a
        ror MT_P
        cmp #$10                ; the sign
        php
        and #$0F
        cmp #$08                ; 2048 or more: 4095 - c
        bcc :+
        eor #$0F
        pha
        lda MT_P
        eor #$FF
        sta MT_P
        pla
:       clc
        adc #>QUARTLO
        sta MT_P+1
        lda #MT_TBANK
        ldx #2
        ldy #>(QUARTHI - QUARTLO)
        jsr mt_far
        plp
        rts

; ===========================================================================
; The scales (scaleFast, normD, r_wall65.s:1048-1222)
; ===========================================================================
; scalefast: Z set when done; Z clear: scaleSlow must do it.
scalefast:
        sec                     ; th = viewangle16 - rw_normalangle
        lda VIEWA16
        sbc SD_NORMAL
        sta SW_TH
        lda VIEWA16+1
        sbc SD_NORMAL+1
        sta SW_TH+1
        ldx SW_START            ; s1 = sin(ANG90 + xa[start] + th)
        clc
        lda XTVLO,x
        adc SW_TH
        tay
        lda XTVHI,x
        adc SW_TH+1
        clc
        adc #$40
        tax
        tya
        jsr sina
        bcc :+
        jmp @slow               ; below 0: the old way
:       lda MT_E                ; P1 = hi16(s1 * KS[start]) (+ 0 or 1)
        sta M_A
        lda MT_E+1
        sta M_A+1
        ldx SW_START
        lda KSLO,x
        sta M_B
        lda KSHI,x
        sta M_B+1
        jsr qmulh
        lda M_R
        sta SW_S1
        lda M_R+1
        sta SW_S1+1
        jsr normd               ; SW_R = R16, SW_LZ = lz
        lda SW_S1
        sta M_A
        lda SW_S1+1
        sta M_A+1
        lda SW_R
        sta M_B
        lda SW_R+1
        sta M_B+1
        lda SW_LZ
        cmp #8
        bcs @big
        jsr qmulh               ; lz < 8: hi16(P1 * R16) >> (7 - lz)
        lda #7
        sec
        sbc SW_LZ
        tax
        beq :++
:       lsr M_R+1
        ror M_R
        dex
        bne :-
:       stz M_R+2
        stz M_R+3
        bra @s1
@big:   jsr umul16              ; lz >= 8: (P1 * R16) >> (23 - lz)
        lda M_R+1               ;   (>> 8, then 15 - lz more)
        sta M_R
        lda M_R+2
        sta M_R+1
        lda M_R+3
        sta M_R+2
        stz M_R+3
        lda #15
        sec
        sbc SW_LZ
        tax
:       lsr M_R+2
        ror M_R+1
        ror M_R
        dex
        bne :-
@s1:    lda M_R+2               ; below 256: the old way
        ora M_R+1
        bne :+
        jmp @slow
:       MOV32 M_R, SD_SCALE     ; rw_scale = ds_p->scale1
        MOV32 M_R, DSBUF+DS_SCALE1
        ldx X2END               ; one column: scale2 = scale1, step 0
        dex
        cpx SW_START
        bne @step
        MOV32 SD_SCALE, DSBUF+DS_SCALE2
        MOV32 SD_SCALE, SD_SCALE2
        stz RW_STEP
        stz RW_STEP+1
        stz RW_STEP+2
        stz RW_STEP+3
        MOV32 RW_STEP, DSBUF+DS_STEP
        lda #0
        rts

        ; the step: hi16(|sin th| * R16) >> (14 - lz), times 1.001
@step:  lda SW_TH
        ldx SW_TH+1
        jsr sina
        lda MT_E
        sta M_A
        lda MT_E+1
        sta M_A+1
        lda SW_R
        sta M_B
        lda SW_R+1
        sta M_B+1
        jsr umul16
        lda #14
        sec
        sbc SW_LZ
        tax
:       lsr M_R+3
        ror M_R+2
        dex
        bne :-
        lda M_R+3               ; + >> 10
        lsr a
        lsr a
        clc
        adc M_R+2
        sta SW_T                ; |step|
        lda M_R+3
        adc #0
        sta SW_T+1
        ; scale2 = scale1 + (stop - start) * step
        lda X2END
        clc
        sbc SW_START            ; n = stop - start
        cmp #3
        bcs @mul
        stz SW_Q+2
        stz SW_Q+3
        lda SW_T
        sta SW_Q
        lda SW_T+1
        sta SW_Q+1
        lda X2END
        clc
        sbc SW_START
        cmp #1
        beq @sign
        asl SW_Q                ; n = 2
        rol SW_Q+1
        rol SW_Q+2
        bra @sign
@mul:   sta M_B
        stz M_B+1
        lda SW_T
        sta M_A
        lda SW_T+1
        sta M_A+1
        jsr umul16
        MOV32 M_R, SW_Q
@sign:  bit SW_TH+1             ; the sign of sin th: th's top bit
        bpl :+
        NEG32 SW_Q
:       ADD32 SW_Q, SD_SCALE, SW_Q
        lda SW_Q+3              ; below 256: the old way
        bmi @slow2
        ora SW_Q+2
        ora SW_Q+1
        bne :+
@slow2: jmp @slow
:       MOV32 SW_Q, DSBUF+DS_SCALE2
        MOV32 SW_Q, SD_SCALE2
        lda SW_T                ; rw_scalestep = ds_p->scalestep
        sta RW_STEP
        lda SW_T+1
        sta RW_STEP+1
        stz RW_STEP+2
        stz RW_STEP+3
        bit SW_TH+1
        bpl :+
        NEG32 RW_STEP
:       MOV32 RW_STEP, DSBUF+DS_STEP
        lda #0
        rts
@slow:  lda #1
        rts

; normd: SW_R = RECIP_TABLE[M] ~ (2^31 - 1) / M for the 16 bits M of D
; (SW_D, 4..32767 map units) from its first 1 bit, D ~ M 2^-lz; SW_LZ =
; lz (normD, r_wall65.s:1202-1222). Changes SW_Q, MT_P, MT_E.
normd:  lda SW_D+3
        beq @small
        lda SW_D                ; D >= 256: M from the high word
        sta SW_Q
        lda SW_D+1
        sta SW_Q+1
        lda SW_D+2
        sta SW_Q+2
        lda SW_D+3
        sta SW_Q+3
        stz SW_LZ
        bra @norm
@small: stz SW_Q                ; D < 256: from bytes 1-2, lz = 8 more
        lda SW_D
        sta SW_Q+1
        lda SW_D+1
        sta SW_Q+2
        lda SW_D+2
        sta SW_Q+3
        lda #8
        sta SW_LZ
@norm:  lda SW_Q+3
        bmi @done
        inc SW_LZ
        asl SW_Q
        rol SW_Q+1
        rol SW_Q+2
        rol SW_Q+3
        bra @norm
@done:  lda SW_Q+2              ; RECIP_TABLE[M & $7FFF]
        sta MT_P
        lda SW_Q+3
        and #$7F
        clc
        adc #>RECIPT
        sta MT_P+1
        jsr mt_recipe
        lda MT_E
        sta SW_R
        lda MT_E+1
        sta SW_R+1
        rts

; ===========================================================================
; scaleslow: the scales the old way (scaleSlow, r_wall65.s:1971-2059):
; R_ScaleFromGlobalAngle at both ends, the step by division, truncated as
; C (upstream divides |N| by bytes: the same quotient). For one column
; rw_scalestep and the drawseg's scalestep stay as they were.
; ===========================================================================
scaleslow:
        lda SW_START
        jsr rsga
        MOV32 M_R, SD_SCALE
        MOV32 M_R, DSBUF+DS_SCALE1
        ldx X2END
        dex
        cpx SW_START
        bne :+
        MOV32 SD_SCALE, DSBUF+DS_SCALE2
        MOV32 SD_SCALE, SD_SCALE2
        rts
:       txa
        jsr rsga
        MOV32 M_R, DSBUF+DS_SCALE2
        MOV32 M_R, SD_SCALE2
        SUB32 SD_SCALE2, SD_SCALE, SW_Q         ; N
        lda SW_Q+3
        sta SW_T                ; its sign
        bpl :+
        NEG32 SW_Q
:       MOV32 SW_Q, M_A         ; |N| / d, d = stop - start
        lda X2END
        clc
        sbc SW_START
        sta M_B
        stz M_B+1
        stz M_B+2
        stz M_B+3
        jsr udiv32
        bit SW_T
        bpl :+
        NEG32 M_R
:       MOV32 M_R, RW_STEP
        MOV32 M_R, DSBUF+DS_STEP
        rts

; ---------------------------------------------------------------------------
; rsga: M_R = R_ScaleFromGlobalAngle(A) (r_iigs65.s:448-530): anglea =
; ANG90 + xtoviewangle[x], angleb = anglea + viewangle16 - rw_normalangle;
; den = rw_distance * sin(anglea), num = PROJECTIONY * sin(angleb), both
; sines as sineLow reads them; 64.0 when den <= num >> 16, else
; FixedApproxDiv(num, den) clamped to 256 .. 64.0. A column seen from
; behind (angleb >= ANG180: its sine is negative) takes our rule RULE_SINE
; (RENDER.md 3.9): the scale 256, vanilla DOOM's result (a negative num
; over a positive den, clamped), and the bit in RULES. Upstream's sineLow
; reads its own code there (sinelow below). anglea = ANG90 + xtoviewangle
; lies in $2000 .. $6000 (tests/test_native_render.py checks the table), so
; neither sine index is negative after that test.
; ---------------------------------------------------------------------------
rsga:   tax
        clc
        lda XTVLO,x
        sta SW_Q
        lda XTVHI,x
        adc #$40
        sta SW_Q+1              ; anglea
        clc                     ; angleb
        lda SW_Q
        adc VIEWA16
        tay
        lda SW_Q+1
        adc VIEWA16+1
        tax
        sec
        tya
        sbc SD_NORMAL
        sta SW_Q+2
        txa
        sbc SD_NORMAL+1
        sta SW_Q+3
        bpl @front              ; angleb >= ANG180: seen from behind
        lda #RULE_SINE
        tsb RULES
        jmp @256                ; the scale 256
@front: lda SW_Q                ; den = rw_distance * sin(anglea): the
        ldx SW_Q+1              ;   unsigned product, less sin << 16 for
        jsr sinelow             ;   rw_distance < 0
        lda MT_E
        sta M_A
        sta SW_T
        lda MT_E+1
        sta M_A+1
        sta SW_T+1
        lda SD_DIST
        sta M_B
        lda SD_DIST+1
        sta M_B+1
        jsr umul16
        MOV32 M_R, SW_P
        bit SD_DIST+1
        bpl :+
        sec
        lda SW_P+2
        sbc SW_T
        sta SW_P+2
        lda SW_P+3
        sbc SW_T+1
        sta SW_P+3
:       lda SW_Q+2              ; num = PROJECTIONY * sin(angleb)
        ldx SW_Q+3
        jsr sinelow
        lda MT_E
        sta M_A
        lda MT_E+1
        sta M_A+1
        lda #PROJECTIONY
        sta M_B
        stz M_B+1
        jsr umul16
        MOV32 M_R, SW_Q         ; num
        ; den > num >> 16 (signed 32 bits)?
        lda SW_Q+2
        cmp SW_P
        lda SW_Q+3
        sbc SW_P+1
        ldx #0
        bit SW_Q+3
        bpl :+
        dex
:       txa
        sbc SW_P+2
        txa
        sbc SW_P+3
        bvc :+
        eor #$80
:       bmi @div
        stz M_R                 ; 64 * FRACUNIT
        stz M_R+1
        lda #64
        sta M_R+2
        stz M_R+3
        rts
@div:   MOV32 SW_Q, M_A         ; FixedApproxDiv(num, den)
        MOV32 SW_P, M_B
        jsr approxdiv
        lda M_R                 ; above 64 * FRACUNIT: 64 * FRACUNIT
        cmp #1
        lda M_R+1
        sbc #0
        lda M_R+2
        sbc #64
        lda M_R+3
        sbc #0
        bvc :+
        eor #$80
:       bmi :+
        stz M_R
        stz M_R+1
        lda #64
        sta M_R+2
        stz M_R+3
        rts
:       lda M_R+3               ; below 256: 256
        bmi @256
        ora M_R+2
        bne @ok
        lda M_R+1
        bne @ok
@256:   stz M_R
        lda #1
        sta M_R+1
        stz M_R+2
        stz M_R+3
@ok:    rts

; sinelow: MT_E = the word sineLow reads (r_iigs65.s:535-542) for the
; angle X:A >> 3, C = 0 .. 4095 (rsga sees to X:A < $8000): the
; quarter table at C when C < 2048, at C ^ 4095 from 2048. For C < 0
; upstream's index is negative: `lda finesineTable_part_1,x` with X = 2 C
; reaches past the bank ($02:5900 + $FFFE is $03:58FE) and reads
; upstream's own code in bank 3, one word of it patched per seg
; (c17Return). Not reproduced: rsga takes RULE_SINE instead.
sinelow:
        sta SW_M                ; C = X:A >> 3 (X:A < $8000)
        txa
        lsr a
        ror SW_M
        lsr a
        ror SW_M
        lsr a
        ror SW_M
        cmp #>2048              ; 2048 .. 4095: 4095 - C
        bcc :+
        eor #$0F
        tay
        lda SW_M
        eor #$FF
        sta SW_M
        tya
:       clc
        adc #>QUARTLO
        sta MT_P+1
        lda SW_M
        sta MT_P
        lda #MT_TBANK
        ldx #2
        ldy #>(QUARTHI - QUARTLO)
        jmp mt_far

; ===========================================================================
; The edges of the tiers (edgeAL, edge, edgeSlow; r_wall65.s:1642-1723,
; :1921-1954): for a height h,
;   step  = -FixedMul(h, rw_scalestep)
;   start = (CENTERY << 16) + round - FixedMul(h, rw_scale) - step
; round = FRACUNIT - 1 (SW_ER 0) or FRACUNIT (SW_ER 1). The heights of a
; seg share their low word AL: FixedMul(h, B) = AH B + FixedMul(AL, B)
; (FMFAST, modulo 2^32), FixedMul(AL, B) once a seg by FIXAL (qmulh's "+ 0
; or 1" for B.hi 0 or -1); a height with another low word takes FixedMul.
; ===========================================================================
; edgeal: SW_AL = worldtop's low word, SW_CS = FIXAL(rw_scale), SW_CSS =
; FIXAL(rw_scalestep) (not set for a step of 0: FIXALZ).
edgeal: lda WTOP
        sta SW_AL
        lda WTOP+1
        sta SW_AL+1
        ora SW_AL
        bne :+
        stz SW_CS
        stz SW_CS+1
        stz SW_CS+2
        stz SW_CS+3
        stz SW_CSS
        stz SW_CSS+1
        stz SW_CSS+2
        stz SW_CSS+3
        rts
:       MOV32 SD_SCALE, SW_P
        jsr fixal
        MOV32 M_R, SW_CS
        lda RW_STEP
        ora RW_STEP+1
        ora RW_STEP+2
        ora RW_STEP+3
        beq :+
        MOV32 RW_STEP, SW_P
        jsr fixal
        MOV32 M_R, SW_CSS
:       rts

; fixal: M_R = FixedMul(AL, B), B = SW_P: for B.hi 0 or -1 hi16(AL * B.lo)
; (qmulh) - (B.hi = -1 ? AL : 0), 32 bits; else FixedMul3216(B, AL). The
; same as FIXALZ for any B other than 0 (B.lo = 0: qmulh gives 0 exactly).
fixal:  lda SW_P+2
        and SW_P+3
        cmp #$FF
        beq @q
        lda SW_P+2
        ora SW_P+3
        beq @q
        MOV32 SW_P, M_A
        lda SW_AL
        sta M_B
        lda SW_AL+1
        sta M_B+1
        jmp fixmul3216
@q:     lda SW_AL
        sta M_A
        lda SW_AL+1
        sta M_A+1
        lda SW_P
        sta M_B
        lda SW_P+1
        sta M_B+1
        jsr qmulh
        stz M_R+2
        stz M_R+3
        lda SW_P+2
        beq @done
        sec                     ; B.hi = -1: - AL
        lda M_R
        sbc SW_AL
        sta M_R
        lda M_R+1
        sbc SW_AL+1
        sta M_R+1
        bcs @done
        dec M_R+2
        dec M_R+3
@done:  rts

; edge: the edge of the height SW_Q into the step at zero page X and the
; start at X - 4, SW_ER the rounding.
edge:   stx SW_EO
        lda SW_Q
        cmp SW_AL
        bne @slow0
        lda SW_Q+1
        cmp SW_AL+1
        beq :+
@slow0: jmp @slow
:
        ; edgeH: step = -(AH * rw_scalestep + SW_CSS), 0 for a step of 0;
        ; P = AH * rw_scale + SW_CS
        lda RW_STEP
        ora RW_STEP+1
        ora RW_STEP+2
        ora RW_STEP+3
        bne :+
        stz SW_T
        stz SW_T+1
        stz SW_T+2
        stz SW_T+3
        bra @p
:       MOV32 RW_STEP, M_B
        jsr ahmul
        ADD32 M_R, SW_CSS, SW_T
        NEG32 SW_T
@p:     MOV32 SD_SCALE, M_B
        jsr ahmul
        ADD32 M_R, SW_CS, SW_P
        jmp @start
        ; edgeSlow: P = FixedMul(h, rw_scale), step = -FixedMul(h,
        ; rw_scalestep)
@slow:  MOV32 SW_Q, M_A
        MOV32 SD_SCALE, M_B
        jsr fixmul
        MOV32 M_R, SW_P
        MOV32 SW_Q, M_A
        MOV32 RW_STEP, M_B
        jsr fixmul
        MOV32 M_R, SW_T
        NEG32 SW_T
        ; start = ((CENTERY + 1) << 16) - 1 + round - P - step
@start: ldx SW_EO
        lda SW_T
        sta 0,x
        lda SW_T+1
        sta 1,x
        lda SW_T+2
        sta 2,x
        lda SW_T+3
        sta 3,x
        sec
        lda #$FF
        sbc SW_P
        tay
        lda #$FF
        sbc SW_P+1
        pha
        lda #CENTERY
        sbc SW_P+2
        pha
        lda #0
        sbc SW_P+3
        sta SW_Q+3
        pla
        sta SW_Q+2
        pla
        sta SW_Q+1
        sty SW_Q
        clc                     ; + round (0 or 1)
        lda SW_Q
        adc SW_ER
        sta SW_Q
        bcc :+
        inc SW_Q+1
        bne :+
        inc SW_Q+2
        bne :+
        inc SW_Q+3
:       sec                     ; - step
        lda SW_Q
        sbc SW_T
        sta $FC,x
        lda SW_Q+1
        sbc SW_T+1
        sta $FD,x
        lda SW_Q+2
        sbc SW_T+2
        sta $FE,x
        lda SW_Q+3
        sbc SW_T+3
        sta $FF,x
        rts

; ahmul: M_R = AH * M_B modulo 2^32, AH = SW_Q's high word (signed)
ahmul:  lda SW_Q+2
        sta M_A
        lda SW_Q+3
        sta M_A+1
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx M_A+2
        stx M_A+3
        jmp mul32

; the scale constant of each column: PROJECTIONY / sin(ANG90 +
; xtoviewangle[x]) (8.8), upstream's KS (r_wall65.s:1466-1487), from the
; reference's RAM by tools/native/rtables.py
KSLO:   .incbin "kslo.bin"
KSHI:   .incbin "kshi.bin"
