; game/sight/sfrac.s: the two-sided line's heights, part sight of milestone
; 10 (docs/GAME.md 2.4). GPL-2: rewritten from upstream's p_sight65.s
; (zSetup:1061, sightSlope:1407, interceptFrac:1150, opening:985, pick,
; sameHeight, st32, shr8V, smul48), Doom8088: Apple IIgs Edition. The
; products, the reciprocal and _Mul32 upstream makes through m_fixed65.s
; and m_recip65.s are milestone 6's (math.s: umul16, recipsmall, mul32);
; smul48 and interceptFrac's own division are upstream's arithmetic,
; mirrored.
;
;   zSetup          the heights of los for the first two-sided line of a
;                   check: from t1, t2 (SG_T1, SG_T2): sightzstart = t1.z
;                   + t1.height - (t1.height >> 2), bottomslope = t2.z -
;                   sightzstart, topslope = bottomslope + t2.height; CS_Z
;   sightSlope      GA_0-3 a height: M_R = frac ? ((height - sightzstart)
;                   >> 16) FixedReciprocalSmall(frac) : INT32_MAX (frac =
;                   SG_FRAC)
;   interceptFrac   SG_FRAC = P_InterceptVector2(strace, the line SG_LINE)
;                   as upstream computes it: num = NDY (((NX << 16) - s.x)
;                   >> 8) + NDX ((s.y - (NY << 16)) >> 8), den = (s.dx NDY)
;                   >> 8 - (s.dy NDX) >> 8 (48-bit products, the low 32
;                   bits); 0 if num = 0 or den >> 12 = 0, else |num << 4| /
;                   |den >> 12| limited to $FFFF, $FFFF for a negative
;                   quotient
;   p_sight_opening the sectors SG_FS, SG_BS: SG_OTOP the lower ceiling,
;                   SG_OBOT the higher floor (upstream's opening and pick:
;                   FS's when it is strictly lower (higher), else BS's)
;   smul48          SG_IFP (48 bits) = SG_IFV (32, signed; lost) x A:X (16,
;                   signed)
;
; Each changes A, X, Y, GT_*, the math block and the API's temporaries.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/sight/sight.inc"

        .export zSetup, sightSlope, interceptFrac, p_sight_opening, smul48
        .import mo_get, ln_get, sec_get, umul16, recipsmall, mul32
        .import fc_call, fc_unbuilt

MO_RH   = 2 * MO_SIZE + MB_HEIGHT   ; a mobj cache line: the height
MO_RZ   = TH_Z                      ;   and z

; ===========================================================================
; zSetup (p_sight65.s:1061)
; ===========================================================================
        ROUTINE zSetup
        lda SG_T1
        ldx SG_T1+1
        jsr mo_get
        ldy #MO_RH              ; CS_T = height >> 2 (arithmetic)
        ldx #0
:       lda (GC_MP),y
        sta SG_CST,x
        iny
        inx
        cpx #4
        bne :-
        ldx #2
:       lda SG_CST+3
        cmp #$80
        ror SG_CST+3
        ror SG_CST+2
        ror SG_CST+1
        ror SG_CST
        dex
        bne :-
        ldy #MO_RH              ; CS_T = height - CS_T
        sec
        lda (GC_MP),y
        sbc SG_CST
        sta SG_CST
        iny
        lda (GC_MP),y
        sbc SG_CST+1
        sta SG_CST+1
        iny
        lda (GC_MP),y
        sbc SG_CST+2
        sta SG_CST+2
        iny
        lda (GC_MP),y
        sbc SG_CST+3
        sta SG_CST+3
        ldy #MO_RZ              ; sightzstart = t1.z + CS_T
        clc
        lda (GC_MP),y
        adc SG_CST
        sta SG_ZS
        iny
        lda (GC_MP),y
        adc SG_CST+1
        sta SG_ZS+1
        iny
        lda (GC_MP),y
        adc SG_CST+2
        sta SG_ZS+2
        iny
        lda (GC_MP),y
        adc SG_CST+3
        sta SG_ZS+3
        lda SG_T2
        ldx SG_T2+1
        jsr mo_get
        ldy #MO_RZ              ; bottomslope = t2.z - sightzstart
        sec
        lda (GC_MP),y
        sbc SG_ZS
        sta SG_BOT
        iny
        lda (GC_MP),y
        sbc SG_ZS+1
        sta SG_BOT+1
        iny
        lda (GC_MP),y
        sbc SG_ZS+2
        sta SG_BOT+2
        iny
        lda (GC_MP),y
        sbc SG_ZS+3
        sta SG_BOT+3
        ldy #MO_RH              ; topslope = bottomslope + t2.height
        clc
        lda (GC_MP),y
        adc SG_BOT
        sta SG_TOP
        iny
        lda (GC_MP),y
        adc SG_BOT+1
        sta SG_TOP+1
        iny
        lda (GC_MP),y
        adc SG_BOT+2
        sta SG_TOP+2
        iny
        lda (GC_MP),y
        adc SG_BOT+3
        sta SG_TOP+3
        lda #1
        sta SG_CSZ
        rts

; ===========================================================================
; sightSlope (p_sight65.s:1407)
; ===========================================================================
        ROUTINE sightSlope
        lda SG_FRAC
        ora SG_FRAC+1
        bne @go
        lda #$FF                ; INT32_MAX
        sta M_R
        sta M_R+1
        sta M_R+2
        lda #$7F
        sta M_R+3
        rts
@go:    sec                     ; (height - sightzstart) >> 16
        lda GA_0
        sbc SG_ZS
        lda GA_1
        sbc SG_ZS+1
        lda GA_2
        sbc SG_ZS+2
        sta SG_SLW
        lda GA_3
        sbc SG_ZS+3
        sta SG_SLW+1
        lda SG_FRAC             ; FixedReciprocalSmall(frac)
        sta M_A
        lda SG_FRAC+1
        sta M_A+1
        jsr recipsmall
        ldx #3
:       lda M_R,x
        sta M_B,x
        dex
        bpl :-
        lda SG_SLW              ; the whole part, sign extended, times it
        sta M_A
        lda SG_SLW+1
        sta M_A+1
        and #$80
        beq :+
        lda #$FF
:       sta M_A+2
        sta M_A+3
        jmp mul32

; ===========================================================================
; p_sight_opening (p_sight65.s:985: opening, pick)
; ===========================================================================
        ROUTINE p_sight_opening
        lda SG_FS
        jsr sec_get
        lda GC_SP
        sta SG_FSP
        lda GC_SP+1
        sta SG_FSP+1
        lda SG_BS
        jsr sec_get
        lda GC_SP
        sta SG_BSP
        lda GC_SP+1
        sta SG_BSP+1
        ; opentop: FS's ceiling when it is below BS's, else BS's
        ldx #3
:       lda SG_FSP,x
        sta GT_0,x
        dex
        bpl :-
        ldy #SEC_CEIL
        jsr lower               ; N: FS's is lower
        bmi :+
        jsr swap                ; (BS's)
:       ldy #SEC_CEIL
        ldx #SG_OTOP - SG
        jsr copy4
        ; openbottom: FS's floor when BS's is below it, else BS's
        ldx #3
:       lda SG_FSP,x
        sta GT_0,x
        dex
        bpl :-
        jsr swap                ; GT_0 BS, GT_2 FS
        ldy #SEC_FLOOR
        jsr lower               ; N: BS's is lower
        bpl :+
        jsr swap                ; (FS's)
:       ldy #SEC_FLOOR
        ldx #SG_OBOT - SG
        ; (on into copy4)

; copy4: the 4 bytes at offset Y of (GT_0) to SG + X
copy4:  lda (GT_0),y
        sta SG,x
        iny
        inx
        lda (GT_0),y
        sta SG,x
        iny
        inx
        lda (GT_0),y
        sta SG,x
        iny
        inx
        lda (GT_0),y
        sta SG,x
        rts

; lower: N set when the 32-bit value at offset Y of (GT_0) is below that of
; (GT_2) (signed)
lower:  sec
        lda (GT_0),y
        sbc (GT_2),y
        iny
        lda (GT_0),y
        sbc (GT_2),y
        iny
        lda (GT_0),y
        sbc (GT_2),y
        iny
        lda (GT_0),y
        sbc (GT_2),y
        bvc :+
        eor #$80
:       rts

; swap: GT_0-1 and GT_2-3 exchanged
swap:   ldx #1
:       lda GT_0,x
        ldy GT_2,x
        sta GT_2,x
        sty GT_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; interceptFrac (p_sight65.s:1150)
; ===========================================================================
        ROUTINE interceptFrac
        lda SG_LINE             ; the line: v1 x, y, dx, dy (DLN)
        ldx SG_LINE+1
        jsr ln_get
        ldy #3
:       lda (GC_LP),y
        sta SG_DLN,y
        dey
        bpl :-
        ldy #LN_DX + 3
:       lda (GC_LP),y
        sta SG_DLN + 4 - LN_DX,y
        dey
        cpy #LN_DX
        bcs :-
        .assert LN_V1X = 0 && LN_V1Y = 2, error, "v1 first"
        ; num = NDY (((NX << 16) - s.x) >> 8)
        sec
        lda #0
        sbc SG_SX
        sta SG_IFP
        lda #0
        sbc SG_SX+1
        sta SG_IFP+1
        lda SG_DLN              ; NX
        sbc SG_SX+2
        sta SG_IFP+2
        lda SG_DLN+1
        sbc SG_SX+3
        sta SG_IFP+3
        jsr shr8v
        lda SG_DLN+6            ; NDY
        ldx SG_DLN+7
        FCALL smul48
        ldx #3
:       lda SG_IFP,x
        sta SG_NUM,x
        dex
        bpl :-
        ; + NDX ((s.y - (NY << 16)) >> 8)
        lda SG_SY
        sta SG_IFP
        lda SG_SY+1
        sta SG_IFP+1
        sec
        lda SG_SY+2
        sbc SG_DLN+2            ; NY
        sta SG_IFP+2
        lda SG_SY+3
        sbc SG_DLN+3
        sta SG_IFP+3
        jsr shr8v
        lda SG_DLN+4            ; NDX
        ldx SG_DLN+5
        FCALL smul48
        clc
        lda SG_NUM
        adc SG_IFP
        sta SG_NUM
        lda SG_NUM+1
        adc SG_IFP+1
        sta SG_NUM+1
        lda SG_NUM+2
        adc SG_IFP+2
        sta SG_NUM+2
        lda SG_NUM+3
        adc SG_IFP+3
        sta SG_NUM+3
        ora SG_NUM
        ora SG_NUM+1
        ora SG_NUM+2
        bne :+
        jmp frac0
        ; den = ((s.dx NDY) >> 8) - ((s.dy NDX) >> 8)
:       ldx #3
:       lda SG_DX,x
        sta SG_IFV,x
        dex
        bpl :-
        lda SG_DLN+6            ; NDY
        ldx SG_DLN+7
        FCALL smul48
        ldx #3
:       lda SG_IFP+1,x
        sta SG_IFE,x
        dex
        bpl :-
        ldx #3
:       lda SG_DY,x
        sta SG_IFV,x
        dex
        bpl :-
        lda SG_DLN+4            ; NDX
        ldx SG_DLN+5
        FCALL smul48
        sec
        lda SG_IFE
        sbc SG_IFP+1
        sta SG_IFE
        lda SG_IFE+1
        sbc SG_IFP+2
        sta SG_IFE+1
        lda SG_IFE+2
        sbc SG_IFP+3
        sta SG_IFE+2
        lda SG_IFE+3
        sbc SG_IFP+4
        sta SG_IFE+3
        ; den >> 12, arithmetic: the bytes 1-3 and the sign, 4 bits
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx GT_0
        ldx #0
:       lda SG_IFE+1,x
        sta SG_IFE,x
        inx
        cpx #3
        bne :-
        lda GT_0
        sta SG_IFE+3
        ldx #4
:       lda SG_IFE+3
        cmp #$80
        ror SG_IFE+3
        ror SG_IFE+2
        ror SG_IFE+1
        ror SG_IFE
        dex
        bne :-
        lda SG_IFE
        ora SG_IFE+1
        ora SG_IFE+2
        ora SG_IFE+3
        bne :+
        jmp frac0
        ; num << 4, the quotient's sign, |num|, |den >> 12|
:       ldx #4
:       asl SG_NUM
        rol SG_NUM+1
        rol SG_NUM+2
        rol SG_NUM+3
        dex
        bne :-
        lda SG_NUM+3
        eor SG_IFE+3
        sta SG_IFQS
        ldx #SG_NUM - SG
        jsr abs32
        ldx #SG_IFE - SG
        jsr abs32
        ; a quotient of $10000 or more: $FFFF
        lda SG_IFE+2
        ora SG_IFE+3
        bne @div
        lda SG_NUM+2
        cmp SG_IFE
        lda SG_NUM+3
        sbc SG_IFE+1
        bcc @div
        lda #$FF
        sta SG_FRAC
        sta SG_FRAC+1
        rts
        ; 16 steps: the remainder from the dividend's high word, the
        ; quotient into its low word
@div:   lda SG_NUM+2
        sta SG_IFR
        lda SG_NUM+3
        sta SG_IFR+1
        stz SG_IFR+2
        stz SG_IFR+3
        ldx #16
@step:  asl SG_NUM
        rol SG_NUM+1
        rol SG_IFR
        rol SG_IFR+1
        rol SG_IFR+2
        rol SG_IFR+3
        sec
        lda SG_IFR
        sbc SG_IFE
        sta GT_0
        lda SG_IFR+1
        sbc SG_IFE+1
        sta GT_1
        lda SG_IFR+2
        sbc SG_IFE+2
        sta GT_2
        lda SG_IFR+3
        sbc SG_IFE+3
        bcc @no
        sta SG_IFR+3
        lda GT_2
        sta SG_IFR+2
        lda GT_1
        sta SG_IFR+1
        lda GT_0
        sta SG_IFR
        inc SG_NUM
@no:    dex
        bne @step
        ; a negative quotient: $FFFF
        lda SG_NUM
        ldx SG_NUM+1
        bit SG_IFQS
        bpl :+
        cmp #0
        bne @neg
        cpx #0
        beq :+
@neg:   lda #$FF
        tax
:       sta SG_FRAC
        stx SG_FRAC+1
        rts
frac0:  stz SG_FRAC
        stz SG_FRAC+1
        rts

; shr8v: SG_IFV = SG_IFP (32 bits) >> 8, arithmetic (shr8V)
shr8v:  lda SG_IFP+1
        sta SG_IFV
        lda SG_IFP+2
        sta SG_IFV+1
        lda SG_IFP+3
        sta SG_IFV+2
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx SG_IFV+3
        rts

; abs32: the 32-bit value at SG + X made positive ($80000000 stays)
abs32:  lda SG+3,x
        bpl :+
        sec
        lda #0
        sbc SG,x
        sta SG,x
        lda #0
        sbc SG+1,x
        sta SG+1,x
        lda #0
        sbc SG+2,x
        sta SG+2,x
        lda #0
        sbc SG+3,x
        sta SG+3,x
:       rts

; ===========================================================================
; smul48 (p_sight65.s:1346)
; ===========================================================================
        ROUTINE smul48
        stz SG_IFS
        cpx #$80                ; |C|, the sign
        bcc :+
        eor #$FF
        clc
        adc #1
        pha
        txa
        eor #$FF
        adc #0
        tax
        pla
        dec SG_IFS
:       sta M_B
        stx M_B+1
        lda SG_IFV+3            ; |V|, the sign
        bpl :+
        sec
        lda #0
        sbc SG_IFV
        sta SG_IFV
        lda #0
        sbc SG_IFV+1
        sta SG_IFV+1
        lda #0
        sbc SG_IFV+2
        sta SG_IFV+2
        lda #0
        sbc SG_IFV+3
        sta SG_IFV+3
        lda SG_IFS
        eor #$FF
        sta SG_IFS
:       lda SG_IFV              ; |V| low |C|
        sta M_A
        lda SG_IFV+1
        sta M_A+1
        jsr umul16
        ldx #3
:       lda M_R,x
        sta SG_IFP,x
        dex
        bpl :-
        lda SG_IFV+2            ; + |V| high |C| << 16
        sta M_A
        lda SG_IFV+3
        sta M_A+1
        jsr umul16
        clc
        lda M_R
        adc SG_IFP+2
        sta SG_IFP+2
        lda M_R+1
        adc SG_IFP+3
        sta SG_IFP+3
        lda M_R+2
        adc #0
        sta SG_IFP+4
        lda M_R+3
        adc #0
        sta SG_IFP+5
        lda SG_IFS              ; the sign
        beq @done
        sec
        ldx #0
:       lda #0
        sbc SG_IFP,x
        sta SG_IFP,x
        inx
        txa                     ; (C kept: cpx would change it)
        eor #6
        bne :-
@done:  rts
