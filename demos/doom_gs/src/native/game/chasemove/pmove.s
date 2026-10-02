; game/chasemove/pmove.s: part chasemove's walk (milestone 10, docs/GAME.md
; 2.4 row chasemove; docs/game-parts/chasemove.md). A GPL-2 derivative of
; upstream's p_enemy65.s with TICSTEP 1, the release's (P_Move as pMove,
; with speedStep, mulSpeed, umul16x and their tables speedTab, speeds,
; SPD47; P_TryWalk with tryWalk).
;
;   pMove       GA_0-1 the actor (CM_AP). A = 0 (C clear) when its movedir
;               is DI_NODIR. Else its try point: when its type's speed is
;               below 65536, each coordinate plus speed times its direction's
;               class (speedTab: 0 none, 1 47000, 2 FRACUNIT, 3 -47000, 4
;               -FRACUNIT): an axis adds or takes the speed from the whole
;               part, a diagonal adds or takes SPD47[speed] (speed * 47000)
;               for a speed below 32, else the product (umul16x); a speed of
;               65536 or more takes the 32-bit products (mulSpeed). Then
;               P_TryMove(actor, x, y) (part trymove): moved, z = floorz and
;               A = 1 (C set); refused with no special line met
;               (numspechit 0), A = 0; else movedir = DI_NODIR and every
;               line of spechit, the last first, numspechit re-read each
;               turn and left at $FF (upstream's -1), gets
;               P_UseSpecialLine(actor, line) (part lines), A = 1 when any
;               of them opened, else 0 (C as A)
;   tryWalk     GA_0-1 the actor: pMove; when it moved, movecount =
;               P_Random() & 15 (a word) and A = 1 (C set); else A = 0
;               (C clear)
;   P_TryWalk   upstream's public P_TryWalk: tryWalk
;
; The helpers have no code of their own (docs/game-parts/chasemove.md R1,
; glayout.INLINED): speedStep is cm_step, mulSpeed cm_mulspeed, umul16x
; cm_umul16x (milestone 6's umul16), the tables cm_class (speedTab), the
; class values cm_value (speeds: the value of each direction is its class's,
; so the two tables of 16 longs are one of 5) and cm_spd47 (SPD47). Every
; product is math.s's (umul16, mul32). Records through the object API
; (mo_get, mi_get). A routine changes A, X, Y, GA_*, GT_*, the math block,
; the API's temporaries and what its callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/chasemove/chasemove.inc"

        .export pMove, tryWalk, P_TryWalk
        .import mo_get, mo_dirty, mi_get, g_random, umul16, mul32
        .import fc_call, fc_unbuilt
.ifdef TESTBUILD
        .export cm_umul16x, cm_mulspeed
.endif

; the speed of pMove's mulSpeed path (4 bytes): CM_DDX, dead whenever pMove
; runs (newChaseDir copies it into CM_D before doNewChaseDir's walks)
CM_SPD  = CM_DDX

; ===========================================================================
; pMove
; ===========================================================================
        ROUTINE pMove
        lda GA_0
        sta CM_AP
        ldx GA_1
        stx CM_AP+1
        jsr mo_get
        ldy #LN_C + MC_MOVEDIR          ; DI_NODIR: no move
        lda (GC_MP),y
        cmp #UC_DI_NODIR
        bne :+
        lda #0
        clc
        rts
:       ldy #LN_A + MA_TYPE             ; the type's speed
        lda (GC_MP),y
        pha
        ldy #UO_MI_SPEED + 2
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @small
        jmp @big
@small: pla
        ldy #UO_MI_SPEED
        jsr mi_get
        sta GT_0                        ; speed (EN_T)
        stx GT_1
        jsr cm_get
        ldy #LN_C + MC_MOVEDIR          ; x: speedStep(xspeed class)
        lda (GC_MP),y
        tax
        lda cm_class,x
        ldx #TH_X
        jsr cm_step
        ldy #LN_C + MC_MOVEDIR          ; y: speedStep(yspeed class)
        lda (GC_MP),y
        tax
        lda cm_class + 8,x
        ldx #TH_Y
        jsr cm_step
@try:   lda CM_AP                       ; P_TryMove(actor, tryx, tryy)
        sta GA_0
        lda CM_AP+1
        sta GA_1
        FCALL P_TryMove
        cmp #0
        bne @moved
        lda GM_NSPEC                    ; blocked: open any specials
        bne @spec
        clc
        rts
@spec:  jsr cm_get                      ; movedir = DI_NODIR
        lda #UC_DI_NODIR
        ldy #LN_C + MC_MOVEDIR
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        stz CM_GOOD
@next:  lda GM_NSPEC                    ; for ( ; numspechit--; )
        dec GM_NSPEC
        cmp #0
        beq @done
        lda GM_NSPEC                    ; P_UseSpecialLine(actor,
        asl a                           ;   spechit[numspechit])
        tax
        lda GM_SPECHIT,x
        sta GA_2
        lda GM_SPECHIT+1,x
        sta GA_3
        lda CM_AP
        sta GA_0
        lda CM_AP+1
        sta GA_1
        FCALL P_UseSpecialLine
        cmp #0
        beq @next
        lda #1
        sta CM_GOOD
        bra @next
@done:  lda CM_GOOD
        cmp #1
        rts
@moved: jsr cm_get                      ; z = floorz (P_TryMove's move took
        ldy #LN_B + MB_FLOORZ + 3       ;   CLEAN off already)
        ldx #3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        ldy #TH_Z + 3
        ldx #3
:       lda GT_0,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        lda #D_RTH
        jsr mo_dirty
        lda #1
        sec
        rts

        ; a speed of 65536 or more (never a walking monster's): x and y
        ; with the 32-bit products (pMoveMul32, mulSpeed); the type on the
        ; stack
@big:   pla
        pha
        ldy #UO_MI_SPEED
        jsr mi_get
        sta CM_SPD
        stx CM_SPD+1
        pla
        ldy #UO_MI_SPEED + 2
        jsr mi_get
        sta CM_SPD+2
        stx CM_SPD+3
        ldx #TH_X                       ; x, then y
@coord: phx
        jsr cm_get
        plx
        phx
        txa                             ; the coordinate
        tay
        ldx #0
:       lda (GC_MP),y
        sta GT_0,x
        iny
        inx
        cpx #4
        bne :-
        ldx #3                          ; the speed
:       lda CM_SPD,x
        sta M_A,x
        dex
        bpl :-
        ldy #LN_C + MC_MOVEDIR          ; speeds[dir] (x), speeds[8 + dir]
        lda (GC_MP),y                   ;   (y)
        plx
        phx
        cpx #TH_Y
        bne :+
        ora #8
:       jsr cm_mulspeed
        plx
        ldy #0
:       lda GT_0,y
        sta GA_2,x
        inx
        iny
        cpy #4
        bne :-
        cpx #TH_Y + 4
        bne @coord
        jmp @try

; cm_get: GC_MP = the actor's line (CM_AP)
cm_get: lda CM_AP
        ldx CM_AP+1
        jmp mo_get

; ---------------------------------------------------------------------------
; cm_step (speedStep): GA_2 + X .. + 3 = the actor's coordinate at X (TH_X,
; TH_Y) + speed (GT_0-1) times the value of class A (0: 0, 1: 47000, 2:
; FRACUNIT, 3: -47000, 4: -FRACUNIT), modulo 2^32; GC_MP the actor's line.
; An axis adds the speed to the whole part (the low word as it is), a
; diagonal SPD47[speed] for a speed below 32, else the product (umul16x).
; Changes A, X, Y, GT_2-3, the math block
; ---------------------------------------------------------------------------
cm_step:
        stx GT_3                        ; the coordinate
        sta GT_2                        ; the class
        stz M_R
        stz M_R+1
        tax
        beq @zero                       ; 0: the coordinate
        cmp #2
        beq @axis
        cmp #4
        beq @axis
        lda GT_1                        ; a diagonal: speed * 47000
        bne @mul
        lda GT_0
        cmp #32
        bcs @mul
        asl a                           ; SPD47[speed]
        asl a
        tax
        ldy #0
:       lda cm_spd47,x
        sta M_R,y
        inx
        iny
        cpy #4
        bne :-
        bra @sign
@mul:   lda GT_0                        ; 32 or more: the product
        sta M_A
        lda GT_1
        sta M_A+1
        lda #<47000
        sta M_B
        lda #>47000
        sta M_B+1
        jsr cm_umul16x
        bra @sign
@axis:  lda GT_0                        ; speed << 16
        sta M_R+2
        lda GT_1
        sta M_R+3
        bra @sign
@zero:  stz M_R+2
        stz M_R+3
@sign:  ldy GT_3
        ldx #0
        lda GT_2                        ; 3, 4: minus
        cmp #3
        bcs @minus
        clc
:       lda (GC_MP),y
        adc M_R,x
        sta GA_2,y
        iny
        inx
        txa
        eor #4
        bne :-
        rts
@minus: sec
:       lda (GC_MP),y
        sbc M_R,x
        sta GA_2,y
        iny
        inx
        txa
        eor #4
        bne :-
        rts

; cm_umul16x (umul16x): M_R = M_A * M_B, unsigned 16 x 16 (math.s's
; umul16, upstream's umul16 in umul16x)
cm_umul16x:
        jmp umul16

; cm_mulspeed (mulSpeed): GT_0-3 = GT_0-3 (a coordinate) + M_A (the speed,
; 32 bits) * speeds[A] (A 0-15: xspeeds by direction, then yspeeds; each
; the value of its direction's class), modulo 2^32 (math.s's mul32, as
; upstream's _Mul32). Changes A, X, Y, the math block
cm_mulspeed:
        tax
        lda cm_class,x
        asl a
        asl a
        tax
        ldy #0
:       lda cm_value,x
        sta M_B,y
        inx
        iny
        cpy #4
        bne :-
        jsr mul32
        ldx #0
        clc
:       lda GT_0,x
        adc M_R,x
        sta GT_0,x
        inx
        txa
        eor #4
        bne :-
        rts

; speedTab: the class of each direction's x step, then of its y step
cm_class:
        .byte 2, 1, 0, 3, 4, 3, 0, 1
        .byte 0, 1, 2, 1, 0, 3, 4, 3
; speeds: each class's value (upstream's xspeeds and yspeeds, by class)
cm_value:
        .dword 0, 47000, $10000, (-47000) & $FFFFFFFF, $FFFF0000
; SPD47: speed * 47000 for the speeds 0-31
cm_spd47:
        .repeat 32, I
        .dword I * 47000
        .endrepeat

; ===========================================================================
; tryWalk, P_TryWalk
; ===========================================================================
        ROUTINE tryWalk
        FCALL pMove                     ; (GA_0-1: the actor; pMove sets
        cmp #0                          ;   CM_AP)
        bne :+
        clc
        rts
:       jsr g_random                    ; movecount = P_Random() & 15
        and #15
        pha
        lda CM_AP
        ldx CM_AP+1
        jsr mo_get
        pla
        ldy #LN_C + MC_MOVEC
        sta (GC_MP),y
        iny
        lda #0
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        lda #1
        sec
        rts

        ROUTINE P_TryWalk
        FCALL tryWalk
        rts
