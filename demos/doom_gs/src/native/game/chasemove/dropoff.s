; game/chasemove/dropoff.s: part chasemove's drop-off avoidance
; (milestone 10, docs/GAME.md 2.4 row chasemove, 2.2 ITTAB;
; docs/game-parts/chasemove.md). A GPL-2 derivative of upstream's
; p_enemy65.s (avoidDropoff with boxPlus, boxMinus, blockOf;
; PIT_AvoidDropoff with boxAbove, boxBelow, sideFloor, signed, times32).
;
;   avoidDropoff      CM_AP the actor: _g_tmbbox (GM_TMBBOX) its box (y +
;                     radius, y - radius, x + radius, x - radius), the
;                     block range (box - bmaporg) >> MAPBLOCKSHIFT
;                     (arithmetic), floorz = its z, dropoff_deltax and
;                     _deltay 0, validcount + 1, then
;                     P_BlockLinesIterator(bx, by, PIT_AvoidDropoff) for bx
;                     xl..xh, by yl..yh (signed words; part geom). A = 1 (C
;                     set) when the deltas are not both 0, else A = 0 (C
;                     clear)
;   PIT_AvoidDropoff  ITTAB's entry: GA_0-1 the line. A two-sided line that
;                     the box touches (tmbbox[RIGHT] > left, tmbbox[LEFT] <
;                     right, tmbbox[TOP] > bottom, tmbbox[BOTTOM] < top,
;                     the line's box words << 16, signed) and crosses
;                     (P_BoxOnLineSide $FF), between the floor of the actor
;                     and a floor more than 24.0 below it: with the back
;                     floor at floorz and the front below floorz - 24.0, the
;                     angle of (dx, dy) << 16; else with the front at floorz
;                     and the back below, of (-dx, -dy) << 16 (16-bit
;                     negations); dropoff_deltax -= finesine(angle >> 19) *
;                     32, dropoff_deltay += finecosine(angle >> 19) * 32. C
;                     set (go on), always
;
; The helpers have no code of their own (docs/game-parts/chasemove.md R1):
; cm_boxplus, cm_boxminus, cm_blockof, cm_above, cm_below, cm_signed,
; cm_times32; sideFloor is the line's front and back sectors of the line
; cache (LVS's LNSECF, LNSECB: side 0's and side 1's sectors). The angle and
; the sines are milestone 6's (pta3, finesine, finecosine). A routine
; changes A, X, Y, GA_*, GT_*, the math block, the API's temporaries and
; what its callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/chasemove/chasemove.inc"

        .export avoidDropoff, PIT_AvoidDropoff
        .import mo_get, ln_get, sec_get, gv_inc, pta3, finesine, finecosine
        .import fc_call, fc_unbuilt
.ifdef TESTBUILD
        .export cm_times32
.endif

; ===========================================================================
; avoidDropoff
; ===========================================================================
        ROUTINE avoidDropoff
        lda CM_AP
        ldx CM_AP+1
        jsr mo_get
        ldy #LN_B + MB_RADIUS + 3       ; GT_0-3 = the radius
        ldx #3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        ldy #TH_Y                       ; the box
        ldx #UC_BOXTOP * 4
        jsr cm_boxplus
        ldx #UC_BOXBOTTOM * 4
        jsr cm_boxminus
        ldy #TH_X
        ldx #UC_BOXRIGHT * 4
        jsr cm_boxplus
        ldx #UC_BOXLEFT * 4
        jsr cm_boxminus
        ldx #UC_BOXLEFT * 4             ; the blocks: xl, xh, yl, yh
        ldy #0
        jsr cm_blockof
        sta CM_BX
        stx CM_BX+1
        ldx #UC_BOXRIGHT * 4
        ldy #0
        jsr cm_blockof
        sta CM_XH
        stx CM_XH+1
        ldx #UC_BOXBOTTOM * 4
        ldy #4
        jsr cm_blockof
        sta CM_YL
        stx CM_YL+1
        ldx #UC_BOXTOP * 4
        ldy #4
        jsr cm_blockof
        sta CM_YH
        stx CM_YH+1
        ldy #TH_Z + 3                   ; floorz = the actor's z
        ldx #3
:       lda (GC_MP),y
        sta CM_FLOORZ,x
        dey
        dex
        bpl :-
        ldx #7                          ; dropoff_deltax, _deltay = 0
:       stz CM_DDX,x
        dex
        bpl :-
        jsr gv_inc                      ; validcount + 1
@bx:    sec                             ; bx <= xh: xh - bx not negative
        lda CM_XH
        sbc CM_BX
        lda CM_XH+1
        sbc CM_BX+1
        bvc :+
        eor #$80
:       bmi @done
        lda CM_YL
        sta CM_BY
        lda CM_YL+1
        sta CM_BY+1
@by:    sec                             ; by <= yh
        lda CM_YH
        sbc CM_BY
        lda CM_YH+1
        sbc CM_BY+1
        bvc :+
        eor #$80
:       bmi @nextx
        lda CM_BX                       ; P_BlockLinesIterator(bx, by,
        sta GA_0                        ;   PIT_AvoidDropoff)
        lda CM_BX+1
        sta GA_1
        lda CM_BY
        sta GA_2
        lda CM_BY+1
        sta GA_3
        lda #ITTAB_PIT_AvoidDropoff
        sta GA_4
        FCALL P_BlockLinesIterator
        inc CM_BY
        bne @by
        inc CM_BY+1
        bra @by
@nextx: inc CM_BX
        bne @bx
        inc CM_BX+1
        bra @bx
@done:  ldx #7                          ; (dropoff_deltax | _deltay) != 0
        lda #0
:       ora CM_DDX,x
        dex
        bpl :-
        cmp #0
        beq :+
        lda #1
        sec
        rts
:       clc
        rts

; cm_boxplus (boxPlus), cm_boxminus (boxMinus): GM_TMBBOX + X = the
; actor's coordinate at Y plus or minus GT_0-3 (GC_MP the actor's line).
; Y is kept; X changes
cm_boxplus:
        clc
        lda (GC_MP),y
        adc GT_0
        sta GM_TMBBOX,x
        iny
        lda (GC_MP),y
        adc GT_1
        sta GM_TMBBOX+1,x
        iny
        lda (GC_MP),y
        adc GT_2
        sta GM_TMBBOX+2,x
        iny
        lda (GC_MP),y
        adc GT_3
        sta GM_TMBBOX+3,x
        dey
        dey
        dey
        rts
cm_boxminus:
        sec
        lda (GC_MP),y
        sbc GT_0
        sta GM_TMBBOX,x
        iny
        lda (GC_MP),y
        sbc GT_1
        sta GM_TMBBOX+1,x
        iny
        lda (GC_MP),y
        sbc GT_2
        sta GM_TMBBOX+2,x
        iny
        lda (GC_MP),y
        sbc GT_3
        sta GM_TMBBOX+3,x
        dey
        dey
        dey
        rts

; cm_blockof (blockOf): A:X = (GM_TMBBOX + X - the origin G_BMORGX + Y,
; Y 0 for x, 4 for y) >> 23, arithmetic: the high word of the difference
; >> 7
        .assert G_BMORGY = G_BMORGX + 4, error, "bmaporgx, bmaporgy"
cm_blockof:
        sec
        lda GM_TMBBOX,x
        sbc G_BMORGX,y
        lda GM_TMBBOX+1,x
        sbc G_BMORGX+1,y
        lda GM_TMBBOX+2,x
        sbc G_BMORGX+2,y
        sta GT_4
        lda GM_TMBBOX+3,x
        sbc G_BMORGX+3,y
        sta GT_5
        lda GT_4                        ; >> 7: bits 7-15 down, the sign
        asl a                           ;   above
        lda GT_5
        rol a
        ldx #0
        bcc :+
        dex
:       rts

; ===========================================================================
; PIT_AvoidDropoff
; ===========================================================================
        ROUTINE PIT_AvoidDropoff
        lda GA_0
        sta CM_LINE
        ldx GA_1
        stx CM_LINE+1
        jsr ln_get
        ldy #LN_SIDE1                   ; one-sided lines do not count
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        bne :+
        jmp @done
        ; the box touches the line's box
:       ldx #UC_BOXRIGHT * 4            ; tmbbox[RIGHT] > left << 16
        ldy #LN_LEFT
        jsr cm_above
        bmi :+
        jmp @done
:       ldx #UC_BOXLEFT * 4             ; tmbbox[LEFT] < right << 16
        ldy #LN_RIGHT
        jsr cm_below
        bmi :+
        jmp @done
:       ldx #UC_BOXTOP * 4              ; tmbbox[TOP] > bottom << 16
        ldy #LN_BOTTOM
        jsr cm_above
        bmi :+
        jmp @done
:       ldx #UC_BOXBOTTOM * 4           ; tmbbox[BOTTOM] < top << 16
        ldy #LN_TOP
        jsr cm_below
        bmi :+
        jmp @done
        ; and crosses it: P_BoxOnLineSide(tmbbox, line) = -1
:       ldx #15
:       lda GM_TMBBOX,x
        sta GA_0,x
        dex
        bpl :-
        lda CM_LINE
        ldx CM_LINE+1
        FCALL P_BoxOnLineSide
        cmp #$FF
        beq :+
        jmp @done
        ; the front and back floors (sideFloor): GT_0-3, M_A
:       lda CM_LINE
        ldx CM_LINE+1
        jsr ln_get
        ldy #LINE_SIZE + 1              ; the back sector
        lda (GC_LP),y
        pha
        dey                             ; the front
        lda (GC_LP),y
        jsr sec_get
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        pla
        jsr sec_get
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        sta M_A,x
        dey
        dex
        bpl :-
        lda CM_FLOORZ                   ; M_B = floorz - 24.0
        sta M_B
        lda CM_FLOORZ+1
        sta M_B+1
        sec
        lda CM_FLOORZ+2
        sbc #24
        sta M_B+2
        lda CM_FLOORZ+3
        sbc #0
        sta M_B+3
        ; back = floorz and front < floorz - 24.0: + (dx, dy)
        ldx #3
:       lda M_A,x
        cmp CM_FLOORZ,x
        bne @front
        dex
        bpl :-
        lda GT_0
        cmp M_B
        lda GT_1
        sbc M_B+1
        lda GT_2
        sbc M_B+2
        lda GT_3
        sbc M_B+3
        bvc :+
        eor #$80
:       bpl @front
        lda #0
        bra @sign
        ; front = floorz and back < floorz - 24.0: - (dx, dy)
@front: ldx #3
:       lda GT_0,x
        cmp CM_FLOORZ,x
        jne @done
        dex
        bpl :-
        lda M_A
        cmp M_B
        lda M_A+1
        sbc M_B+1
        lda M_A+2
        sbc M_B+2
        lda M_A+3
        sbc M_B+3
        bvc :+
        eor #$80
:       jpl @done
        lda #$FF
@sign:  sta GT_4                        ; the sign: 0 or $FF
        lda CM_LINE
        ldx CM_LINE+1
        jsr ln_get
        stz M_B                         ; y = (+-dy) << 16
        stz M_B+1
        ldy #LN_DY
        jsr cm_signed
        sta M_B+2
        stx M_B+3
        stz M_A                         ; x = (+-dx) << 16
        stz M_A+1
        ldy #LN_DX
        jsr cm_signed
        sta M_A+2
        stx M_A+3
        jsr pta3
        lda M_R+3                       ; the fine angle: angle >> 19
        lsr a
        sta GT_6
        lda M_R+2
        ror a
        lsr GT_6
        ror a
        lsr GT_6
        ror a
        sta GT_5
        sta M_A                         ; dropoff_deltax -= finesine * 32
        lda GT_6
        sta M_A+1
        jsr finesine
        jsr cm_times32
        ldx #0
        sec
:       lda CM_DDX,x
        sbc M_R,x
        sta CM_DDX,x
        inx
        txa
        eor #4
        bne :-
        lda GT_5                        ; dropoff_deltay += finecosine * 32
        sta M_A
        lda GT_6
        sta M_A+1
        jsr finecosine
        jsr cm_times32
        ldx #0
        clc
:       lda CM_DDY,x
        adc M_R,x
        sta CM_DDY,x
        inx
        txa
        eor #4
        bne :-
@done:  lda #1
        sec
        rts

; cm_above (boxAbove): N set when GM_TMBBOX + X > the line's word at Y
; << 16 (signed 32 bits: the sign of word << 16 - box). Y changes
cm_above:
        sec
        lda #0
        sbc GM_TMBBOX,x
        lda #0
        sbc GM_TMBBOX+1,x
        lda (GC_LP),y
        sbc GM_TMBBOX+2,x
        iny
        lda (GC_LP),y
        sbc GM_TMBBOX+3,x
        bvc :+
        eor #$80
:       rts

; cm_below (boxBelow): N set when GM_TMBBOX + X < the line's word at Y
; << 16. Y changes
cm_below:
        sec
        lda GM_TMBBOX,x
        sbc #0
        lda GM_TMBBOX+1,x
        sbc #0
        lda GM_TMBBOX+2,x
        sbc (GC_LP),y
        iny
        lda GM_TMBBOX+3,x
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       rts

; cm_signed (signed): A:X = the line's word at Y (GC_LP), negated (16
; bits) when GT_4's bit 7 is set
cm_signed:
        lda (GC_LP),y
        pha
        iny
        lda (GC_LP),y
        tax
        pla
        bit GT_4
        bpl :+
        eor #$FF
        clc
        adc #1
        pha
        txa
        eor #$FF
        adc #0
        tax
        pla
:       rts

; cm_times32 (times32): M_R = M_R << 5 (32 bits)
cm_times32:
        ldx #5
:       asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        dex
        bne :-
        rts
