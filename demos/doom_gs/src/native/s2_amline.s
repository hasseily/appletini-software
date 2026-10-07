; s2_amline.s: the automap's window, its ticker, the transform, the clip,
; the walls, the player's arrow and the line loops (docs/SCREENS.md, the
; automap; part s2amap). A GPL-2 rewrite in 65C02 of upstream's
; src/iigs/am_map65.s: the window, scale and follow routines
; (AM_changeWindowLoc, AM_activateNewScale, AM_changeWindowScale,
; AM_doFollowPlayer, AM_Ticker) [R am_map65.s:559-811], the fixed-point
; helpers [R :813-1019], drawWalls, drawPlayers, the clip and drawFL [R
; :1664-1892, :2354-2861]; the rotation's fast path (fastLine and its vertex
; cache, the overlay's only) is part s2ovl's (s2_ovl.s: am_fastsetup,
; am_fastline, through this file's hook when assembled with -D AM_FASTLINE).
;
; Shared by the image AMAPW (with s2_am.s) and part s2ovl's OVLW: the
; places come from s2_am.inc (AMZ, AMW, AMST), and three routines are the
; linking image's own:
;   am_seg      a line on the screen: FL (clipped, inside 0-319 x 0-167)
;               in the colour COLI (AMAPW: kept for the bands; OVLW: drawn)
;   am_plot     a pixel: PX, LNY in the colour NIBH, NIBL (AMAPW: into the
;               band and its byte list; OVLW: a K_OVL record)
;   am_rowcol   NIBH, NIBL of the colour COLI in the row LNY
;
;   am_ticker   AM_Ticker: one tic (follow, zoom, pan)
;   am_walls    drawWalls: am_seg for each line to show (needs am_getmo)
;   am_players  drawPlayers: the player's arrow (needs am_getmo)
;   am_drawfl   drawFL: the pixels of FL (Bresenham) through am_plot, the
;               rows PLO .. PHI - 1 only (it stops when the line leaves
;               them for good); BOFF, the band's address less BY0 * 160
;   am_getmo    the player's RTHING into MOB
;   am_windowsize, am_center, am_setx2y2, am_oldlocnone, am_newftom,
;   am_chgloc   the window routines (AM_Start and AM_Responder use them)
;   am_tomap    (PA) = the int16 X:A << MAPBITS
;   am_momap    (PA) = the fixed_t at MOB + Y >> 4
;   am_lt32     C = (PA) < (PB), int32
;   am_setauto  the frame block's AUTOMAP = automapmode (the renderer's)
;
; The math is MATHW's and MATHLC's (src/native/MATH.md): fixmul, mul32,
; fixmulang, recip, umul16lo, sdiv16, sineapprox, cosineapprox, with
; operands in M_A, M_B and the result in M_R. Zero page: AMZ's 48 bytes,
; the math block, the far layer's FA_*.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2amap.inc"
        .include "s2_am.inc"

        .export am_ticker, am_walls, am_players, am_drawfl, am_getmo
        .export am_windowsize, am_center, am_setx2y2, am_oldlocnone
        .export am_newftom, am_chgloc, am_tomap, am_momap, am_lt32
        .export am_setauto, am_cp32, am_add32, am_sub32, am_neg32
        .export am_half32, am_ftom, ld_ma, ld_mb, st_mr, stw_mr, mr_ma
        .import am_seg, am_plot, am_rowcol
.ifdef AM_FASTLINE
        .import am_fastsetup, am_fastline   ; (OVLW's)
        .export toscreen, clipscr
.endif
        .import far_get
        .import fixmul, mul32, fixmulang, recip, umul16lo, sdiv16
        .import sineapprox, cosineapprox

        .segment "S2CODE"

; ===========================================================================
; 32-bit helpers on (PA), (PB): little-endian int32s in W or zero page
; ===========================================================================

; am_cp32: (PA) = (PB)
am_cp32:
        ldy #3
:       lda (PB),y
        sta (PA),y
        dey
        bpl :-
        rts

; am_add32: (PA) += (PB)
am_add32:
        clc
        ldy #0
:       lda (PA),y
        adc (PB),y
        sta (PA),y
        iny
        tya
        eor #4
        bne :-
        rts

; am_sub32: (PA) -= (PB)
am_sub32:
        sec
        ldy #0
:       lda (PA),y
        sbc (PB),y
        sta (PA),y
        iny
        tya
        eor #4
        bne :-
        rts

; am_neg32: (PA) = -(PA)
am_neg32:
        sec
        ldy #0
:       lda #0
        sbc (PA),y
        sta (PA),y
        iny
        tya
        eor #4
        bne :-
        rts

; am_half32: (PA) = (PA) / 2, toward 0 [R am_map65.s:840-853: a negative
; value + 1 first]
am_half32:
        ldy #3
        lda (PA),y
        bpl @shift
        ldy #0                  ; + 1
:       lda (PA),y
        clc
        adc #1
        sta (PA),y
        bcc @shift
        iny
        cpy #4
        bne :-
@shift: ldy #3
        lda (PA),y
        cmp #$80                ; the sign into the carry
:       lda (PA),y
        ror a
        sta (PA),y
        dey
        bpl :-
        rts

; ld_ma, ld_mb: M_A or M_B = the int32 at AMST + X; st_mr: AMST + X =
; M_R; stw_mr: AMW + X = M_R; mr_ma: M_A = M_R. Change X, Y.
ld_ma:  ldy #0
        bra ld4
ld_mb:  ldy #M_B - M_A
ld4:    lda AMST,x
        sta M_A,y
        inx
        iny
        tya
        and #3
        bne ld4
        rts
st_mr:  ldy #0
:       lda M_R,y
        sta AMST,x
        inx
        iny
        cpy #4
        bne :-
        rts
stw_mr: ldy #0
:       lda M_R,y
        sta AMW,x
        inx
        iny
        cpy #4
        bne :-
        rts
mr_ma:  ldx #3
:       lda M_R,x
        sta M_A,x
        dex
        bpl :-
        rts

; am_lt32: C = 1 when (PA) < (PB), signed [R am_map65.s:876-883]
am_lt32:
        ldy #0
        lda (PA),y
        cmp (PB),y
        ldy #1
        lda (PA),y
        sbc (PB),y
        ldy #2
        lda (PA),y
        sbc (PB),y
        ldy #3
        lda (PA),y
        sbc (PB),y
        bvc :+
        eor #$80
:       asl a
        rts

; am_tomap: (PA) = the int16 X:A (X high) << MAPBITS (12), sign-extended
; [R am_map65.s:885-904]
am_tomap:
        sta AT0
        stx AT1
        ldy #0
        lda #0
        sta (PA),y              ; bits 0-7
        lda AT0                  ; bits 8-15: (v & $F) << 4
        asl a
        asl a
        asl a
        asl a
        iny
        sta (PA),y
        lda AT1                  ; bits 16-31: v >> 4, arithmetic
        cmp #$80
        ror a
        ror AT0
        cmp #$80
        ror a
        ror AT0
        cmp #$80
        ror a
        ror AT0
        cmp #$80
        ror a
        ror AT0
        ldy #3
        sta (PA),y
        dey
        lda AT0
        sta (PA),y
        rts

; am_momap: (PA) = the fixed_t at MOB + Y, >> 4 (arithmetic) [R
; am_map65.s:913-927]
am_momap:
        ldx #0
:       lda MOB,y
        sta AT0,x
        iny
        inx
        cpx #4
        bne :-
        ldx #4
@sh:    lda AT3
        cmp #$80
        ror AT3
        ror AT2
        ror AT1
        ror AT0
        dex
        bne @sh
        ldy #3
:       lda AT0,y
        sta (PA),y
        dey
        bpl :-
        rts

; am_getmo: the player's mobj's RTHING (x, y, z, its angle) into MOB
am_getmo:
        lda AM_PLMO             ; slot * 24
        sta FA_SRC
        lda AM_PLMO+1
        sta FA_SRC+1
        asl FA_SRC              ; * 8
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        lda FA_SRC              ; * 3
        sta AT0
        lda FA_SRC+1
        sta AT1
        asl FA_SRC
        rol FA_SRC+1
        clc
        lda FA_SRC
        adc AT0
        sta FA_SRC
        lda FA_SRC+1
        adc AT1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<AM_RTH0
        sta FA_SRC
        lda FA_SRC+1
        adc #>AM_RTH0
        sta FA_SRC+1
        lda #<MOB
        sta FA_DST
        lda #>MOB
        sta FA_DST+1
        lda #AM_RTH
        sta FA_BANK
        lda #24
        sta FA_N
        jmp far_get

; am_setauto: the frame block's AUTOMAP byte = automapmode (the renderer
; reads AM_ACTIVE and AM_OVERLAY there: docs/RENDER-MASKED.md)
am_setauto:
        lda ST_MODE
        sta AM_FAUTO
        rts

; ===========================================================================
; The fixed-point transforms [R am_map65.s:817-838]
; ===========================================================================

; am_ftom: M_R = FTOM(M_A) = M_A * scale_ftom, the low 32 bits
am_ftom:
        ldx #ST_FTOM - AMST
        jsr ld_mb
        jmp mul32

; mtof: M_R = MTOF(M_A) = (int16) (FixedMul(M_A, scale_mtof) >> 16),
; sign-extended; A, X = its low and high byte
mtof:
        ldx #ST_SCALE - AMST
        jsr ld_mb
        jsr fixmul
        lda M_R+2
        sta M_R
        ldx M_R+3
        stx M_R+1
        ldy #0
        cpx #$80
        bcc :+
        dey
:       sty M_R+2
        sty M_R+3
        rts

; ===========================================================================
; The window [R am_map65.s:559-704]
; ===========================================================================

; am_oldlocnone: f_oldloc.x = INT32_MAX
am_oldlocnone:
        lda #$FF
        sta ST_OLDLOC
        sta ST_OLDLOC+1
        sta ST_OLDLOC+2
        lda #$7F
        sta ST_OLDLOC+3
        rts

; am_newftom: scale_ftom = FixedReciprocal(scale_mtof)
am_newftom:
        ldx #ST_SCALE - AMST
        jsr ld_ma
        jsr recip
        ldx #ST_FTOM - AMST
        jsr st_mr
        rts

; am_windowsize: m_w = FTOM(f_w), m_h = FTOM(f_h)
am_windowsize:
        lda #<AM_FW
        ldx #>AM_FW
        jsr ftom16
        ldx #ST_MW - AMST
        jsr st_mr
        lda #<AM_FH
        ldx #>AM_FH
        jsr ftom16
        ldx #ST_MH - AMST
        jsr st_mr
        rts

; ftom16: M_R = FTOM(the unsigned X:A)
ftom16:
        sta M_A
        stx M_A+1
        stz M_A+2
        stz M_A+3
        jmp am_ftom

; am_center: m_x -= m_w / 2, m_y -= m_h / 2 (AM_T: the half)
am_center:
        PTR PB, ST_MW
        lda #<ST_MX
        ldx #>ST_MX
        jsr subhalf
        PTR PB, ST_MH
        lda #<ST_MY
        ldx #>ST_MY
subhalf:                        ; X:A -= half of (PB), through AMT
        pha
        phx
        PTR PA, AMT
        jsr am_cp32
        jsr am_half32
        PTR PB, AMT
        plx
        pla
        sta PA
        stx PA+1
        jmp am_sub32

; addhalf: X:A += half of (PB)
addhalf:
        pha
        phx
        PTR PA, AMT
        jsr am_cp32
        jsr am_half32
        PTR PB, AMT
        plx
        pla
        sta PA
        stx PA+1
        jmp am_add32

; am_setx2y2: m_x2 = m_x + m_w, m_y2 = m_y + m_h
am_setx2y2:
        clc
        ldx #0
:       lda ST_MX,x
        adc ST_MW,x
        sta ST_MX2,x
        inx
        txa
        eor #4
        bne :-
        clc
        ldx #0
:       lda ST_MY,x
        adc ST_MH,x
        sta ST_MY2,x
        inx
        txa
        eor #4
        bne :-
        rts

; am_chgloc: AM_changeWindowLoc: a pan ends the follow mode; the window
; moves, with its centre in the map
am_chgloc:
        ldx #7
        lda #0
:       ora ST_PAN,x
        dex
        bpl :-
        tax
        beq @move
        lda ST_MODE
        and #<~AMF_FOLLOW
        sta ST_MODE
        jsr am_setauto
        jsr am_oldlocnone
@move:  PTR PA, ST_MX           ; m_x += paninc.x, m_y += paninc.y
        PTR PB, ST_PAN
        jsr am_add32
        PTR PA, ST_MY
        PTR PB, ST_PAN+4
        jsr am_add32
        PTR PB, ST_MW           ; the centre in the map
        lda #<ST_MX
        ldx #>ST_MX
        jsr clamp
        PTR PB, ST_MH
        lda #<ST_MY
        ldx #>ST_MY
        jsr clamp
        jmp am_setx2y2

; clamp: clampCenter for the axis at X:A (m_x or m_y; its limits min_x,
; max_x at the same distances) with the size (PB): c = m + size / 2 more
; than max: m = max - size / 2; else less than min: m = min - size / 2
; [R am_map65.s:589-628]
clamp:
        sta AT6
        stx AT7
        PTR PA, AMU             ; U = size / 2
        jsr am_cp32
        jsr am_half32
        PTR PA, AMT             ; T = U + m
        PTR PB, AMU
        jsr am_cp32
        lda AT6
        sta PB
        lda AT7
        sta PB+1
        jsr am_add32
        clc                     ; PA = max: max < c?
        lda AT6
        adc #<(ST_MAXX - ST_MX)
        sta PA
        lda AT7
        adc #>(ST_MAXX - ST_MX)
        sta PA+1
        PTR PB, AMT
        jsr am_lt32
        bcs @lim
        clc                     ; c < min?
        lda AT6
        adc #<(ST_MINX - ST_MX)
        sta PB
        lda AT7
        adc #>(ST_MINX - ST_MX)
        sta PB+1
        PTR PA, AMT
        jsr am_lt32
        bcc @done
        lda PB                  ; the limit
        sta PA
        lda PB+1
        sta PA+1
@lim:   lda PA                  ; m = the limit (PA) - U
        sta PB
        lda PA+1
        sta PB+1
        lda AT6
        sta PA
        lda AT7
        sta PA+1
        jsr am_cp32
        PTR PB, AMU
        jmp am_sub32
@done:  rts

; actscale: AM_activateNewScale: the window keeps its centre at the new
; scale
actscale:
        PTR PB, ST_MW
        lda #<ST_MX
        ldx #>ST_MX
        jsr addhalf
        PTR PB, ST_MH
        lda #<ST_MY
        ldx #>ST_MY
        jsr addhalf
        jsr am_windowsize
        jsr am_center
        jmp am_setx2y2

; chgscale: AM_changeWindowScale: the zoom of a tic, in the scale limits
; [R am_map65.s:781-811]
chgscale:
        ldx #ST_SCALE - AMST
        jsr ld_ma
        ldx #ST_MZOOM - AMST
        jsr ld_mb
        jsr fixmul
        ldx #ST_SCALE - AMST
        jsr st_mr
        jsr am_newftom
        PTR PA, ST_SCALE        ; less than the minimum
        PTR PB, ST_MINSC
        jsr am_lt32
        bcs @min
        PTR PA, ST_MAXSC        ; more than the maximum
        PTR PB, ST_SCALE
        jsr am_lt32
        bcc @done
        PTR PB, ST_MAXSC
        bra @set
@min:   PTR PB, ST_MINSC
@set:   PTR PA, ST_SCALE
        jsr am_cp32
        jsr am_newftom
@done:  jmp actscale

; follow: AM_doFollowPlayer: the window on the player when he moved [R
; am_map65.s:730-779]
follow:
        ldx #3
:       lda MOB+AM_TH_X,x
        cmp ST_OLDLOC,x
        bne @moved
        lda MOB+AM_TH_Y,x
        cmp ST_OLDLOC+4,x
        bne @moved
        dex
        bpl :-
        rts
@moved: ldx #3
:       lda MOB+AM_TH_X,x
        sta ST_OLDLOC,x
        lda MOB+AM_TH_Y,x
        sta ST_OLDLOC+4,x
        dex
        bpl :-
        PTR PA, M_A             ; m_x = FTOM(MTOF(mo->x >> 4))
        ldy #AM_TH_X
        jsr am_momap
        jsr mtof
        jsr mr_ma
        jsr am_ftom
        ldx #ST_MX - AMST
        jsr st_mr
        PTR PA, M_A             ; m_y the same
        ldy #AM_TH_Y
        jsr am_momap
        jsr mtof
        jsr mr_ma
        jsr am_ftom
        ldx #ST_MY - AMST
        jsr st_mr
        jsr am_center
        jmp am_setx2y2

; am_ticker: AM_Ticker: one tic [R am_map65.s:709-728]. The state block in
; W, the player's RTHING in MOB (am_getmo).
am_ticker:
        lda ST_MODE
        and #AMF_ACTIVE
        beq @done
        lda ST_MODE
        and #AMF_FOLLOW
        beq :+
        jsr follow
:       lda ST_FZOOM            ; zoom: ftom_zoommul is not FRACUNIT
        ora ST_FZOOM+1
        ora ST_FZOOM+3
        bne @zoom
        lda ST_FZOOM+2
        cmp #1
        beq @pan
@zoom:  jsr chgscale
@pan:   ldx #7
        lda #0
:       ora ST_PAN,x
        dex
        bpl :-
        tax
        beq @done
        jmp am_chgloc
@done:  rts

; ===========================================================================
; The rotation [R am_map65.s:929-1019]
; ===========================================================================

; sincos: ARTC, ARTS = the cosine and sine of the angle whose high word is
; X:A (the fine angle: >> 3)
sincos:
        stx AT1
        lsr AT1
        ror a
        lsr AT1
        ror a
        lsr AT1
        ror a
        sta AT0
        sta M_A
        lda AT1
        sta M_A+1
        jsr cosineapprox
        ldx #ARTC - AMW
        jsr stw_mr
        lda AT0
        sta M_A
        lda AT1
        sta M_A+1
        jsr sineapprox
        ldx #ARTS - AMW
        jsr stw_mr
        rts

; mulang: M_R = FixedMulAngle((X:A), (PB)) (the delta, then the cosine or
; the sine)
mulang:
        sta PA
        stx PA+1
        ldy #3
:       lda (PA),y
        sta M_A,y
        lda (PB),y
        sta M_B,y
        dey
        bpl :-
        jmp fixmulang

; rotate: AM_rotate of the point at (PA) (x, then y) about RTOX, RTOY
; with ARTC, ARTS
rotate:
        lda PA
        sta AT6
        lda PA+1
        sta AT7
        PTR PB, RTOX            ; dx = x - xorig
        PTR PA, RTDX
        jsr cpfrom
        jsr am_sub32
        lda AT6                  ; dy = y - yorig
        clc
        adc #4
        sta PB
        lda AT7
        adc #0
        sta PB+1
        PTR PA, RTDY
        jsr am_cp32
        PTR PB, RTOY
        jsr am_sub32
        PTR PB, ARTC             ; x = dx cos - dy sin + xorig
        lda #<RTDX
        ldx #>RTDX
        jsr mulang
        ldx #AMT - AMW
        jsr stw_mr
        PTR PB, ARTS
        lda #<RTDY
        ldx #>RTDY
        jsr mulang
        PTR PA, AMT
        PTR PB, M_R
        jsr am_sub32
        CP4 AMT, RTX
        PTR PB, ARTS             ; y = yorig + dx sin + dy cos
        lda #<RTDX
        ldx #>RTDX
        jsr mulang
        ldx #AMT - AMW
        jsr stw_mr
        PTR PB, ARTC
        lda #<RTDY
        ldx #>RTDY
        jsr mulang
        PTR PA, AMT
        PTR PB, M_R
        jsr am_add32
        lda AT6                  ; the point's y = AMT + yorig
        clc
        adc #4
        sta PA
        lda AT7
        adc #0
        sta PA+1
        PTR PB, AMT
        jsr am_cp32
        PTR PB, RTOY
        jsr am_add32
        lda AT6                  ; its x = RTX + xorig
        sta PA
        lda AT7
        sta PA+1
        PTR PB, RTX
        jsr am_cp32
        PTR PB, RTOX
        jmp am_add32

; cpfrom: (PA) = the point at AT6:AT7 (x), then PB = RTOX's pointer kept
cpfrom:
        lda PB
        pha
        lda PB+1
        pha
        lda AT6
        sta PB
        lda AT7
        sta PB+1
        jsr am_cp32
        pla
        sta PB+1
        pla
        sta PB
        rts

; ===========================================================================
; The walls [R am_map65.s:1664-1892]
; ===========================================================================

; am_walls: drawWalls: each line to show, in the colour of its kind, to
; am_seg (clipped, on the screen)
am_walls:
        lda ST_MODE             ; the rotation of the frame
        and #AMF_ROTATE
        beq :+
        jsr wallrot
.ifdef AM_FASTLINE
        jsr am_fastsetup        ; fastSetup [R am_map65.s:1665-1670]
.endif
:       stz AMI
        stz AMI+1
@line:  lda AMI
        cmp AM_NLINES
        lda AMI+1
        sbc AM_NLINES+1
        bcc :+
        rts
:       lda AMI+1               ; seen (ML_MAPPED: LNMAP's bit)?
        sta AT1
        lda AMI
        lsr AT1
        ror a
        lsr AT1
        ror a
        lsr AT1
        ror a
        clc
        adc #<AM_LNMAP
        sta AT2
        lda AT1
        adc #>AM_LNMAP
        sta AT3
        lda AMI
        and #7
        tax
        lda bits,x
        and (AT2)
        bne @mapped
        lda AM_PLALLMAP         ; else with the computer map
        ora AM_PLALLMAP+1
        beq @next
        jsr fetchline
        lda LB+AM_LFLAGS
        bmi @next               ; (ML_DONTDRAW)
        lda #AMC_UNSN
        bra @draw
@mapped:
        jsr fetchline
        lda LB+AM_LFLAGS
        bmi @next               ; ML_DONTDRAW
        and #$20
        bne @secret             ; ML_SECRET
        lda LB+AM_LSPECIAL      ; a keyed door: special 26-34
        sta SPECW
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx SPECW+1
        sec
        sbc #26
        tay
        lda SPECW+1
        sbc #0
        bne @nodoor
        cpy #9
        bcs @nodoor
        lda doors,y
        bpl @draw
@nodoor:
        jsr onesided            ; one sided: Z
        beq @one
        lda SPECW+1             ; a teleporter
        bne @two
        lda SPECW
        cmp #97
        bne @two
        lda #AMC_TELE
        bra @draw
@secret:
        jsr onesided            ; a secret door: the wall colour (one
        beq @one                ;   sided: as the others)
        lda #AMC_WALL
        bra @draw
@one:   jsr frontsec
        lda SECF+8
        cmp #9
        bne :+
        lda #AMC_SECR
        bra @draw
:       lda #AMC_WALL
        bra @draw
@two:   jsr twosided
        bcs @next
@draw:  sta COLI
.ifdef AM_FASTLINE
        jsr am_fastline         ; the rotation's fast turn: C = 1 drawn
        bcs @next               ;   [R am_map65.s:1771-1779]
.endif
        jsr slowline
@next:  inc AMI
        bne :+
        inc AMI+1
:       jmp @line

bits:   .byte $01, $02, $04, $08, $10, $20, $40, $80
doors:  AM_DOORS

; onesided: Z = 1 when the line's second side is none ($FFFF)
onesided:
        lda LB+AM_LSIDE1
        and LB+AM_LSIDE1+1
        cmp #$FF
        rts

; twosided: A = the colour of a two-sided line, or C = 1: none [R
; am_map65.s:1805-1868]
twosided:
        jsr frontsec
        lda #<(AM_LNSECB - AM_LNSECF)
        ldx #>(AM_LNSECB - AM_LNSECF)
        ldy #SECB - SECF
        jsr sector
        ldx #3                  ; a closed door: floor = ceiling in the
:       lda SECB,x              ;   back or the front sector
        cmp SECB+4,x
        bne @front
        dex
        bpl :-
        bra @closed
@front: ldx #3
:       lda SECF,x
        cmp SECF+4,x
        bne @secret
        dex
        bpl :-
@closed:
        lda #AMC_CLSD
        clc
        rts
@secret:
        lda SECF+8              ; the bound of a secret sector
        cmp #9
        beq :+
        lda SECB+8
        cmp #9
        bne @floor
:       lda #AMC_SECR
        clc
        rts
@floor: ldx #3                  ; a floor change
:       lda SECB,x
        cmp SECF,x
        bne @fchg
        dex
        bpl :-
        ldx #3                  ; a ceiling change
:       lda SECB+4,x
        cmp SECF+4,x
        bne @cchg
        dex
        bpl :-
        sec
        rts
@fchg:  lda #AMC_FCHG
        clc
        rts
@cchg:  lda #AMC_CCHG
        clc
        rts

; frontsec: the line's front sector into SECF
frontsec:
        lda #0
        tax
        tay
; sector: the sector at LNSECF + X:A + AMI (the line's) into SECF + Y:
; floor, ceiling (LVMAP), oldspecial (LVG1)
sector:
        sty AT5
        clc
        adc #<AM_LNSECF
        sta AT0
        txa
        adc #>AM_LNSECF
        sta AT1
        clc                     ; + the line
        lda AT0
        adc AMI
        sta FA_SRC
        lda AT1
        adc AMI+1
        sta FA_SRC+1
        lda #AM_LVS
        sta FA_BANK
        lda #<AT4
        sta FA_DST
        stz FA_DST+1
        lda #1
        sta FA_N
        jsr far_get             ; AT4 = the sector
        lda AT4                  ; LVMAP: SEC0 + 16 s
        stz AT3
        asl a
        rol AT3
        asl a
        rol AT3
        asl a
        rol AT3
        asl a
        rol AT3
        clc
        adc #<(AM_SEC0 + AM_SEC_FLOOR)
        sta FA_SRC
        lda AT3
        adc #>(AM_SEC0 + AM_SEC_FLOOR)
        sta FA_SRC+1
        clc
        lda #<SECF
        adc AT5
        sta FA_DST
        lda #>SECF
        adc #0
        sta FA_DST+1
        lda #AM_LVMAP
        sta FA_BANK
        lda #8                  ; floor (4), ceiling (4)
        sta FA_N
        .assert AM_SEC_CEIL = AM_SEC_FLOOR + 4, error, "the sector's heights"
        jsr far_get
        lda AT4                  ; LVG1: SECG0 + 32 s + OLDSPECIAL
        stz AT3
        asl a
        rol AT3
        asl a
        rol AT3
        asl a
        rol AT3
        asl a
        rol AT3
        asl a
        rol AT3
        clc
        adc #<(AM_SECG0 + AM_SECG_OLDSP)
        sta FA_SRC
        lda AT3
        adc #>(AM_SECG0 + AM_SECG_OLDSP)
        sta FA_SRC+1
        clc
        lda FA_DST
        adc #8
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       lda #AM_LVG1
        sta FA_BANK
        lda #1
        sta FA_N
        jmp far_get

; fetchline: the line AMI's record (its first AM_LINE_FETCH bytes) into LB
fetchline:
        lda AMI                 ; LINE0 + 32 i
        sta FA_SRC
        lda AMI+1
        ldx #5
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<AM_LINE0
        sta FA_SRC
        lda FA_SRC+1
        adc #>AM_LINE0
        sta FA_SRC+1
        lda #<LB
        sta FA_DST
        lda #>LB
        sta FA_DST+1
        lda #AM_LVG0
        sta FA_BANK
        lda #AM_LINE_FETCH
        sta FA_N
        jmp far_get

; slowline: the line's ends << MAPBITS into ML, turned with the player in
; the rotation mode, then drawMline [R am_map65.s:1780-1804]
slowline:
        PTR PA, ML
        lda LB+AM_LV1X
        ldx LB+AM_LV1X+1
        jsr am_tomap
        PTR PA, ML+4
        lda LB+AM_LV1Y
        ldx LB+AM_LV1Y+1
        jsr am_tomap
        PTR PA, ML+8
        lda LB+AM_LV2X
        ldx LB+AM_LV2X+1
        jsr am_tomap
        PTR PA, ML+12
        lda LB+AM_LV2Y
        ldx LB+AM_LV2Y+1
        jsr am_tomap
        lda ST_MODE
        and #AMF_ROTATE
        beq :+
        PTR PA, ML
        jsr rotate
        PTR PA, ML+8
        jsr rotate
:       jmp mline

; wallrot: wallRotation: the angle ANG90 - mo->angle, about the player
; [R am_map65.s:2354-2375]
wallrot:
        sec
        lda #0
        sbc MOB+AM_TH_ANGLO
        lda #0
        sbc MOB+AM_TH_ANGLO+1
        lda #0
        sbc MOB+AM_TH_ANGHI
        tay
        lda #$40
        sbc MOB+AM_TH_ANGHI+1
        tax
        tya
        jsr sincos
        PTR PA, RTOX
        ldy #AM_TH_X
        jsr am_momap
        PTR PA, RTOY
        ldy #AM_TH_Y
        jmp am_momap

; ===========================================================================
; The player's arrow [R am_map65.s:2377-2478]
; ===========================================================================

am_players:
        PTR PA, AMDX            ; the place: mo->x >> 4, mo->y >> 4
        ldy #AM_TH_X
        jsr am_momap
        PTR PA, AMDY
        ldy #AM_TH_Y
        jsr am_momap
        lda ST_MODE             ; the angle: ANG90 in the rotation mode,
        and #AMF_ROTATE         ;   else mo->angle
        beq :+
        lda #1
        sta AMTURN
        lda #$00
        ldx #$40
        bra @turn
:       lda MOB+AM_TH_ANGLO
        ora MOB+AM_TH_ANGLO+1
        ora MOB+AM_TH_ANGHI
        ora MOB+AM_TH_ANGHI+1
        sta AMTURN              ; (0: no turn)
        beq @lines
        lda MOB+AM_TH_ANGHI
        ldx MOB+AM_TH_ANGHI+1
@turn:  jsr sincos
        ldx #7                  ; about 0
:       stz RTOX,x
        dex
        bpl :-
        .assert RTOY = RTOX + 4, error, "RTOX, RTOY"
@lines: stz AMI
@line:  lda AMI                 ; ML = playerArrow[i]
        asl a
        asl a
        asl a
        asl a
        tax
        ldy #0
:       lda arrow,x
        sta ML,y
        inx
        iny
        cpy #16
        bne :-
        PTR PA, ML
        jsr arrowpt
        PTR PA, ML+8
        jsr arrowpt
        lda #AMC_CLSD           ; COLOR_SNGL (208, as COLOR_CLSD)
        sta COLI
        jsr mline
        inc AMI
        lda AMI
        cmp #7
        bne @line
        rts

arrow:  AM_ARROW

; arrowpt: the point at (PA) turned (AMTURN), then moved to the player's
; place
arrowpt:
        lda AMTURN
        beq @move
        lda ST_MODE             ; the rotation mode turns by ANG90: x, y =
        and #AMF_ROTATE         ;   -y, x without products
        beq @rot
        ldy #3
:       lda (PA),y
        sta AMU,y
        dey
        bpl :-
        sec
        ldy #4
        ldx #0
:       lda #0
        sbc (PA),y
        sta AT0,x
        iny
        inx
        cpx #4
        bne :-
        ldy #3
:       lda AT0,y
        sta (PA),y
        dey
        bpl :-
        ldy #7
        ldx #3
:       lda AMU,x
        sta (PA),y
        dey
        dex
        bpl :-
        bra @move
@rot:   lda PA
        pha
        lda PA+1
        pha
        jsr rotate
        pla
        sta PA+1
        pla
        sta PA
@move:  PTR PB, AMDX
        jsr am_add32
        clc
        lda PA
        adc #4
        sta PA
        bcc :+
        inc PA+1
:       PTR PB, AMDY
        jmp am_add32

; ===========================================================================
; drawMline, the clip [R am_map65.s:2480-2718]
; ===========================================================================

; mline: AM_drawMline(ML, COLI): the part of the line in the window, on the
; screen, to am_seg
mline:
        PTR PA, ML              ; the trivial reject on the map
        jsr mapcode
        sta OC1
        PTR PA, ML+8
        jsr mapcode
        and OC1
        beq :+
        rts
:       PTR PA, ML              ; the screen coordinates
        PTR PB, FL
        jsr toscreen
        PTR PA, ML+8
        PTR PB, FL+4
        jsr toscreen
        jsr clipscr
        bcs :+
        rts
:       jmp am_seg

; clipscr: the Cohen-Sutherland loop on FL: C = 1 when a part is on the
; screen (FL is it)
clipscr:
        ldx #0
        jsr outcode
        sta OC1
        ldx #4
        jsr outcode
        sta OC2
        and OC1
        beq @loop
@out:   clc
        rts
@loop:  lda OC1                 ; until both ends are in the view
        ora OC2
        bne :+
        sec
        rts
:       lda OC1                 ; the end outside
        bne :+
        lda OC2
:       sta OUTS
        bit #8                  ; to the top: y = 0
        beq @bot
        lda FL+2
        ldx FL+3
        jsr clipy
        stz TMPY
        stz TMPY+1
        bra @new
@bot:   bit #4                  ; to the bottom: y = f_h - 1
        beq @right
        sec
        lda FL+2
        sbc #<AM_FH
        pha
        lda FL+3
        sbc #>AM_FH
        tax
        pla
        jsr clipy
        lda #<(AM_FH - 1)
        sta TMPY
        stz TMPY+1
        bra @new
@right: bit #2                  ; to the right: x = f_w - 1
        beq @left
        sec
        lda #<(AM_FW - 1)
        sbc FL
        pha
        lda #>(AM_FW - 1)
        sbc FL+1
        tax
        pla
        jsr clipx
        lda #<(AM_FW - 1)
        sta TMPX
        lda #>(AM_FW - 1)
        sta TMPX+1
        bra @new
@left:  sec                     ; to the left: x = 0
        lda #0
        sbc FL
        pha
        lda #0
        sbc FL+1
        tax
        pla
        jsr clipx
        stz TMPX
        stz TMPX+1
@new:   lda OUTS                ; that end at the new point
        cmp OC1
        bne @b
        ldx #3
:       lda TMPX,x
        sta FL,x
        dex
        bpl :-
        .assert TMPY = TMPX + 2, error, "TMPX, TMPY"
        ldx #0
        jsr outcode
        sta OC1
        and OC2
        bra @test
@b:     ldx #3
:       lda TMPX,x
        sta FL+4,x
        dex
        bpl :-
        ldx #4
        jsr outcode
        sta OC2
        and OC1
@test:  bne @out2
        jmp @loop
@out2:  clc
        rts

; outcode: A = the outcode of FL + X (int16 x, y): y < 0 TOP (8), else
; y >= f_h BOTTOM (4); x < 0 LEFT (1), else x >= f_w RIGHT (2) [R
; am_map65.s:2657-2678: the compares' N flag, for values >= 0]
outcode:
        ldy #0
        lda FL+3,x
        bpl :+
        ldy #8
        bra @x
:       lda FL+2,x              ; N of y - f_h
        cmp #<AM_FH
        lda FL+3,x
        sbc #>AM_FH
        bmi @x
        ldy #4
@x:     lda FL+1,x
        bpl :+
        tya
        ora #1
        rts
:       lda FL,x                ; N of x - f_w
        cmp #<AM_FW
        lda FL+1,x
        sbc #>AM_FW
        bmi :+
        tya
        ora #2
        rts
:       tya
        rts

; clipy: TMPX = a.x + (dx * (X:A)) / dy, dy = a.y - b.y, dx = b.x - a.x
; (int16: the low word of the product, C's division)
clipy:
        sta M_A
        stx M_A+1
        sec
        lda FL+4
        sbc FL
        sta M_B
        lda FL+5
        sbc FL+1
        sta M_B+1
        jsr umul16lo
        lda M_R
        sta M_A
        lda M_R+1
        sta M_A+1
        sec
        lda FL+2
        sbc FL+6
        sta M_B
        lda FL+3
        sbc FL+7
        sta M_B+1
        jsr sdiv16
        clc
        lda M_R
        adc FL
        sta TMPX
        lda M_R+1
        adc FL+1
        sta TMPX+1
        rts

; clipx: TMPY = a.y + (dy * (X:A)) / dx, dy = b.y - a.y, dx = b.x - a.x
clipx:
        sta M_A
        stx M_A+1
        sec
        lda FL+6
        sbc FL+2
        sta M_B
        lda FL+7
        sbc FL+3
        sta M_B+1
        jsr umul16lo
        lda M_R
        sta M_A
        lda M_R+1
        sta M_A+1
        sec
        lda FL+4
        sbc FL
        sta M_B
        lda FL+5
        sbc FL+1
        sta M_B+1
        jsr sdiv16
        clc
        lda M_R
        adc FL+2
        sta TMPY
        lda M_R+1
        adc FL+3
        sta TMPY+1
        rts

; mapcode: A = the outcode of the map point (PA) against the window: y >
; m_y2 TOP, else y < m_y BOTTOM; x < m_x LEFT, else x > m_x2 RIGHT [R
; am_map65.s:2580-2623]
mapcode:
        lda PA
        sta AT6
        lda PA+1
        sta AT7
        clc                     ; (PB) = its y
        lda AT6
        adc #4
        sta PB
        lda AT7
        adc #0
        sta PB+1
        PTR PA, ST_MY2          ; m_y2 < y
        jsr am_lt32
        lda #8
        bcs @x
        lda PB                  ; y < m_y
        sta PA
        lda PB+1
        sta PA+1
        PTR PB, ST_MY
        jsr am_lt32
        lda #0
        bcc @x
        lda #4
@x:     sta OCT
        lda AT6                  ; x < m_x
        sta PA
        lda AT7
        sta PA+1
        PTR PB, ST_MX
        jsr am_lt32
        bcc :+
        lda OCT
        ora #1
        rts
:       PTR PA, ST_MX2          ; m_x2 < x
        lda AT6
        sta PB
        lda AT7
        sta PB+1
        jsr am_lt32
        bcc :+
        lda OCT
        ora #2
        rts
:       lda OCT
        rts

; toscreen: the screen point (PB) (int16 x, y) of the map point (PA):
; CXMTOF(x) = MTOF(x - m_x), CYMTOF(y) = f_h - MTOF(y - m_y)
toscreen:
        lda PB
        sta AT6
        lda PB+1
        sta AT7
        sec                     ; x - m_x
        ldy #0
:       lda (PA),y
        sbc ST_MX,y
        sta M_A,y
        iny
        tya
        eor #4
        bne :-
        jsr mtof
        lda M_R
        sta (AT6)
        ldy #1
        lda M_R+1
        sta (AT6),y
        sec                     ; y - m_y
        ldy #4
        ldx #0
:       lda (PA),y
        sbc ST_MY,x
        sta M_A,x
        iny
        inx
        txa
        eor #4
        bne :-
        jsr mtof
        sec                     ; f_h - it
        lda #<AM_FH
        sbc M_R
        ldy #2
        sta (AT6),y
        lda #>AM_FH
        sbc M_R+1
        iny
        sta (AT6),y
        rts

; ===========================================================================
; drawFL [R am_map65.s:2720-2861]: the pixels from FL.a to FL.b, the error
; doubled (ERR2 = 2 err); am_plot for each, am_rowcol at each new row. The
; rows PLO .. PHI - 1 only: the loop ends when the line has left them for
; good (its y is monotonic).
; ===========================================================================

am_drawfl:
        sec                     ; dx = abs(x1 - x0), sx
        lda FL+4
        sbc FL
        tax
        lda FL+5
        sbc FL+1
        bmi @xneg
        bne @xpos
        cpx #0
        bne @xpos
@xneg:  sta AT1                  ; (0 or negative: sx = -1)
        txa
        eor #$FF
        clc
        adc #1
        tax
        lda AT1
        eor #$FF
        adc #0
        ldy #$FF
        bra @xset
@xpos:  ldy #1
@xset:  stx ALDX
        sta ALDX+1
        sty SXS
        sty SXS+1
        cpy #1
        bne :+
        stz SXS+1
:       lda ALDX                 ; 2 dx
        asl a
        sta DX2
        lda ALDX+1
        rol a
        sta DX2+1
        sec                     ; dy = -abs(y1 - y0), sy
        lda FL+6
        sbc FL+2
        tax
        lda FL+7
        sbc FL+3
        bmi @yneg
        bne @ypos
        cpx #0
        bne @ypos
@yneg:  ldy #$FF                ; (0 or negative: sy = -1, dy = y1 - y0)
        bra @yset
@ypos:  sta AT1                  ; positive: dy = -(y1 - y0)
        txa
        eor #$FF
        clc
        adc #1
        tax
        lda AT1
        eor #$FF
        adc #0
        ldy #1
@yset:  stx ALDY
        sta ALDY+1
        sty SYS
        lda ALDY                 ; 2 dy, 2 dx + 2 dy = 2 err
        asl a
        sta DY2
        lda ALDY+1
        rol a
        sta DY2+1
        clc
        lda DY2
        adc DX2
        sta DD2
        sta ERR2
        lda DY2+1
        adc DX2+1
        sta DD2+1
        sta ERR2+1
        lda FL                  ; the pixel and its row
        sta PX
        lda FL+1
        sta PX+1
        lda FL+2
        sta LNY
        jsr row160              ; ROWP, SROW
        jsr am_rowcol
        clc                     ; dx >= -dy: an x step each pixel
        lda ALDX
        adc ALDY
        lda ALDX+1
        adc ALDY+1
        bmi ymajor
        lda ALDX                 ; (dx + 1 pixels)
        sta CNT
        lda ALDX+1
        sta CNT+1
xmajor: jsr am_plot
        lda CNT
        bne :+
        lda CNT+1
        beq @done
        dec CNT+1
:       dec CNT
        clc                     ; the x step
        lda PX
        adc SXS
        sta PX
        lda PX+1
        adc SXS+1
        sta PX+1
        sec                     ; a y step if 2 err <= dx (the compare's
        lda ERR2                ;   Z or N, as upstream)
        sbc ALDX
        tax
        lda ERR2+1
        sbc ALDX+1
        bmi @ystep
        bne @nostep
        cpx #0
        bne @nostep
@ystep: clc
        lda ERR2
        adc DD2
        sta ERR2
        lda ERR2+1
        adc DD2+1
        sta ERR2+1
        jsr ystep
        bcc xmajor
@done:  rts
@nostep:
        clc
        lda ERR2
        adc DY2
        sta ERR2
        lda ERR2+1
        adc DY2+1
        sta ERR2+1
        bra xmajor

ymajor: sec                     ; a y step each pixel (-dy + 1 pixels)
        lda #0
        sbc ALDY
        sta CNT
        lda #0
        sbc ALDY+1
        sta CNT+1
yloop:  jsr am_plot
        lda CNT
        bne :+
        lda CNT+1
        beq @done
        dec CNT+1
:       dec CNT
        sec                     ; an x step if 2 err >= dy (N of the
        lda ERR2                ;   compare, as upstream)
        sbc ALDY
        lda ERR2+1
        sbc ALDY+1
        bmi @noxs
        clc
        lda ERR2
        adc DD2
        sta ERR2
        lda ERR2+1
        adc DD2+1
        sta ERR2+1
        clc
        lda PX
        adc SXS
        sta PX
        lda PX+1
        adc SXS+1
        sta PX+1
        bra @step
@noxs:  clc
        lda ERR2
        adc DX2
        sta ERR2
        lda ERR2+1
        adc DX2+1
        sta ERR2+1
@step:  jsr ystep
        bcc yloop
@done:  rts

; ystep: the next row and its colour; C = 1 when the line has left the rows
; PLO .. PHI - 1 for good
ystep:
        lda SYS
        bmi @up
        inc LNY
        clc
        lda ROWP
        adc #160
        sta ROWP
        bcc :+
        inc ROWP+1
:       clc
        lda SROW
        adc #160
        sta SROW
        bcc :+
        inc SROW+1
:       lda LNY
        cmp PHI
        bcs @left
        bra @col
@up:    dec LNY
        sec
        lda ROWP
        sbc #160
        sta ROWP
        bcs :+
        dec ROWP+1
:       sec
        lda SROW
        sbc #160
        sta SROW
        bcs :+
        dec SROW+1
:       lda LNY
        cmp PLO
        bcc @left
@col:   jsr am_rowcol
        clc
        rts
@left:  sec
        rts

; row160: SROW = $2000 + LNY * 160, ROWP = BOFF + LNY * 160
row160:
        lda LNY                 ; LNY * 160 = LNY * 128 + LNY * 32
        stz AT1
        lsr a
        ror AT1
        sta AT2                  ; AT2:AT1 = LNY * 128
        lda LNY
        stz AT4
        asl a
        rol AT4
        asl a
        rol AT4
        asl a
        rol AT4
        asl a
        rol AT4
        asl a
        rol AT4                  ; AT4:A = LNY * 32
        clc
        adc AT1
        sta AT1
        lda AT4
        adc AT2
        sta AT2
        clc
        lda AT1
        sta SROW
        lda AT2
        adc #>SHR
        sta SROW+1
        clc
        lda AT1
        adc BOFF
        sta ROWP
        lda AT2
        adc BOFF+1
        sta ROWP+1
        rts
