; game/look/radius.s: part look's radius attack (docs/GAME.md, the
; parts). A GPL-2 derivative of upstream's
; p_attack65.s (P_RadiusAttack, PIT_RadiusAttack, blockPair, absDelta).
;
;   P_RadiusAttack  GA_0-1 the spot, GA_2-3 the source ($FFFF none), GA_4-5
;                 the damage: bombspot, bombsource, bombdamage (LK_BSPOT,
;                 LK_BSRC, LK_BDMG); the blocks from (it - dmg - org) >> 23
;                 to (it + dmg - org) >> 23 of x and y (blockPair: the high
;                 word of it - org, then +- the damage in 16 bits, then
;                 >> 7 arithmetic: upstream's C loses MAXRADIUS in 32
;                 bits), y outer, x inner, each loop run at least once and
;                 on while its end >= the counter (signed words): for each
;                 P_BlockThingsIterator(x, y, PIT_RadiusAttack). The loop's
;                 five words are on the stack, as upstream keeps them
;                 (P_DamageMobj runs game logic)
;   PIT_RadiusAttack  ITTAB's, GA_0-1 a thing: a shootable thing within
;                 bombdamage units of bombspot (dist = the larger of |dx|
;                 and |dy| (absDelta: 32-bit, the larger by a signed
;                 compare), then the high word of dist - its radius, 0 when
;                 negative, against bombdamage unsigned) that P_CheckSight
;                 (thing, bombspot) sees takes P_DamageMobj(thing,
;                 bombspot, bombsource, bombdamage - dist). C set (go on)
;
; blockPair and absDelta have no code of their own: their work is done in
; place (glayout.INLINED).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/look/look.inc"

        .export P_RadiusAttack, PIT_RadiusAttack
        .import mo_get, mo_dirty
        .import fc_call, fc_unbuilt

; the loop's frame (tsx; $0101,x ...): x, y, yh, xl, xh, a word each
RF_X    = $0101
RF_Y    = $0103
RF_YH   = $0105
RF_XL   = $0107
RF_XH   = $0109

; ===========================================================================
; P_RadiusAttack
; ===========================================================================
        ROUTINE P_RadiusAttack
        ldx #5                  ; bombspot, bombsource, bombdamage
:       lda GA_0,x
        sta LK_BSPOT,x
        dex
        bpl :-
        .assert LK_BSRC = LK_BSPOT + 2 && LK_BDMG = LK_BSPOT + 4, error, "GA_0-5's order"
        GETMO LK_BSPOT          ; the high words of x - org, y - org
        sec
        ldy #TH_X
        lda (GC_MP),y
        sbc G_BMORGX
        iny
        lda (GC_MP),y
        sbc G_BMORGX+1
        iny
        lda (GC_MP),y
        sbc G_BMORGX+2
        sta GT_0
        iny
        lda (GC_MP),y
        sbc G_BMORGX+3
        sta GT_1
        sec
        ldy #TH_Y
        lda (GC_MP),y
        sbc G_BMORGY
        iny
        lda (GC_MP),y
        sbc G_BMORGY+1
        iny
        lda (GC_MP),y
        sbc G_BMORGY+2
        sta GT_2
        iny
        lda (GC_MP),y
        sbc G_BMORGY+3
        sta GT_3
        ldx #0                  ; (blockPair) xh, xl into LK_T, LK_T+2
        jsr pair
        ldx #2                  ; yh, yl into LK_D, LK_D+2
        jsr pair
        lda LK_T+1              ; the frame: xh, xl, yh, y = yl (each its
        pha                     ;   high byte first)
        lda LK_T
        pha
        lda LK_T+3
        pha
        lda LK_T+2
        pha
        lda LK_D+1
        pha
        lda LK_D
        pha
        lda LK_D+3
        pha
        lda LK_D+2
        pha
@yloop: tsx                     ; x = xl
        lda RF_XL - 2 + 1,x
        pha
        lda RF_XL - 2,x
        pha
@xloop: tsx                     ; P_BlockThingsIterator(x, y, PIT_RadiusAttack)
        lda RF_X,x
        sta GA_0
        lda RF_X+1,x
        sta GA_1
        lda RF_Y,x
        sta GA_2
        lda RF_Y+1,x
        sta GA_3
        lda #ITTAB_PIT_RadiusAttack
        sta GA_4
        FCALL P_BlockThingsIterator
        tsx                     ; x++ while x <= xh (signed)
        inc RF_X,x
        bne :+
        inc RF_X+1,x
:       sec
        lda RF_XH,x
        sbc RF_X,x
        lda RF_XH+1,x
        sbc RF_X+1,x
        bvc :+
        eor #$80
:       bpl @xloop
        pla                     ; y++ while y <= yh (signed)
        pla
        tsx
        inc RF_X,x
        bne :+
        inc RF_X+1,x
:       sec
        lda RF_X + 2,x
        sbc RF_X,x
        lda RF_X + 3,x
        sbc RF_X+1,x
        bvc :+
        eor #$80
:       bpl @yloop
        ldx #8                  ; y, yh, xl, xh off
:       pla
        dex
        bne :-
        rts

; pair: (blockPair) from the high word GT_0 + X of it - org (X 0: x into
; LK_T, X 2: y into LK_D): the word at LK_T + 2X = (it + dmg) >> 7, the
; next = (it - dmg) >> 7 (16-bit sums, arithmetic shifts)
pair:   txa
        asl a
        tay                     ; Y = 2X: LK_T or LK_D
        clc                     ; + dist
        lda GT_0,x
        adc LK_BDMG
        sta GT_4
        lda GT_1,x
        adc LK_BDMG+1
        jsr shr7
        sta LK_T+1,y
        lda GT_4
        sta LK_T,y
        sec                     ; - dist
        lda GT_0,x
        sbc LK_BDMG
        sta GT_4
        lda GT_1,x
        sbc LK_BDMG+1
        jsr shr7
        sta LK_T+3,y
        lda GT_4
        sta LK_T+2,y
        rts
        .assert LK_D = LK_T + 4, error, "pair's places"

; shr7: (A:GT_4) >> 7, arithmetic: GT_4 its low byte, A its high byte
shr7:   asl GT_4                ; C = the low byte's bit 7
        rol a                   ; A = the result's low byte, C the sign
        sta GT_4
        lda #0
        bcc :+
        lda #$FF
:       rts

; ===========================================================================
; PIT_RadiusAttack: M_A, M_B the thing less the spot, then |dx| in LK_D,
; |dy| in LK_T (absDelta), dist in LK_D
; ===========================================================================
        ROUTINE PIT_RadiusAttack
        lda GA_0
        sta LK_BTHING
        ldx GA_1
        stx LK_BTHING+1
        jsr mo_get              ; not shootable: nothing
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        jeq @true
        DELTA LK_BTHING, LK_BSPOT       ; thing - spot
        ldx #0                  ; dx = |thing->x - spot->x| (LK_D)
        jsr abs32
        ldx #4                  ; dy = |thing->y - spot->y| (LK_T)
        jsr abs32
        lda LK_T                ; dist = dy < dx ? dx : dy (signed 32)
        cmp LK_D
        lda LK_T+1
        sbc LK_D+1
        lda LK_T+2
        sbc LK_D+2
        lda LK_T+3
        sbc LK_D+3
        bvc :+
        eor #$80
:       bmi :+
        ldx #3
@cp:    lda LK_T,x
        sta LK_D,x
        dex
        bpl @cp
:       GETMO LK_BTHING         ; (dist - radius) >> FRACBITS, 0 when
        ldy #LN_B + MB_RADIUS   ;   negative
        sec
        lda LK_D
        sbc (GC_MP),y
        iny
        lda LK_D+1
        sbc (GC_MP),y
        iny
        lda LK_D+2
        sbc (GC_MP),y
        sta LK_BDIST
        iny
        lda LK_D+3
        sbc (GC_MP),y
        sta LK_BDIST+1
        bpl :+
        stz LK_BDIST
        stz LK_BDIST+1
:       lda LK_BDIST            ; dist >= bombdamage (unsigned): out of
        cmp LK_BDMG             ;   range
        lda LK_BDIST+1
        sbc LK_BDMG+1
        bcs @true
        lda LK_BTHING           ; P_CheckSight(thing, bombspot)
        sta GA_0
        lda LK_BTHING+1
        sta GA_1
        lda LK_BSPOT
        sta GA_2
        lda LK_BSPOT+1
        sta GA_3
        FCALL P_CheckSight
        cmp #0
        beq @true
        lda LK_BTHING           ; P_DamageMobj(thing, bombspot, bombsource,
        sta GA_0                ;   bombdamage - dist)
        lda LK_BTHING+1
        sta GA_1
        lda LK_BSPOT
        sta GA_2
        lda LK_BSPOT+1
        sta GA_3
        lda LK_BSRC
        sta GA_4
        lda LK_BSRC+1
        sta GA_5
        sec
        lda LK_BDMG
        sbc LK_BDIST
        sta GA_6
        lda LK_BDMG+1
        sbc LK_BDIST+1
        sta GA_7
        FCALL P_DamageMobj
@true:  sec
        rts

; abs32: (absDelta) the 32-bit word at M_A + X made |its value| into LK_D
; (X 0) or LK_T (X 4): 32-bit two's complement (|$80000000| = $80000000)
abs32:  txa
        eor #4                  ; Y: the place's offset from LK_T (0 for
        tay                     ;   X = 4, 4 for X = 0: LK_D = LK_T + 4)
        lda M_A+3,x
        bpl @pos
        sec
        lda #0
        sbc M_A,x
        sta LK_T,y
        lda #0
        sbc M_A+1,x
        sta LK_T+1,y
        lda #0
        sbc M_A+2,x
        sta LK_T+2,y
        lda #0
        sbc M_A+3,x
        sta LK_T+3,y
        rts
@pos:   lda M_A,x
        sta LK_T,y
        lda M_A+1,x
        sta LK_T+1,y
        lda M_A+2,x
        sta LK_T+2,y
        lda M_A+3,x
        sta LK_T+3,y
        rts
