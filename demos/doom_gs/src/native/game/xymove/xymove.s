; game/xymove/xymove.s: part xymove's move (docs/GAME.md). A GPL-2
; derivative of
; upstream's p_mobj65.s (P_XYMovement with TICSTEP 1 and its helpers
; clampMove, isBig, wholeMove, halfMove, skyHit, quarterOut, slow,
; frictionAP, frictionNear, friction), Doom8088: Apple IIgs Edition. The
; products are math.s's (umul16).
;
;   P_XYMovement  A:X = a mobj. No momentum: nothing. Else (its kind's
;               CLEAN off: the momentum changes) momx, momy clamped to
;               -MAXMOVE..MAXMOVE, xmove, ymove = them; then while xmove or
;               ymove: when either is more than MAXMOVE / 2 or less than
;               -MAXMOVE / 2 the half steps (ptry = pos + move / 2 toward 0,
;               move >>= 1, arithmetic), else the whole move (ptry = pos +
;               move, move 0); P_TryMove(mo, ptryx, ptryy) (part trymove);
;               refused: the player's mobj slides (slideMove), a missile
;               goes into the sky (the ceiling line's back sector has the
;               sky's ceiling and is below its z: P_RemoveMobj, the end) or
;               explodes (part mobjstate's explode), anything else stops
;               (momx = momy = 0). Then, but for a missile or a mobj in the
;               air (floorz < z): a corpse with more than FRACUNIT / 4 of
;               momentum on a floor that is not its sector's goes on; a
;               momentum below STOPSPEED both ways stops (the player's: with
;               no forwardmove nor sidemove, its walking frames back to
;               S_PLAY and its own momentum 0); else friction on momx,
;               momy (and the player's momx, momy)
;   friction    GA_0-3 = FixedMul32OrigFriction(GA_0-3) = ((lo ORIG_FRICTION)
;               >> 16) + (int16_t) hi ORIG_FRICTION, as upstream's
;               (p_mobj65.s:1180-1206: two umul16, the sign's correction);
;               changes GT_0-1 and the math block
;
; Every record through the object API (mo_get, ln_get, sec_get, ss_get,
; pl_get, pl_put); what lives across a call is the scratch block's
; (xymove.inc). A routine changes A, X, Y, GA_*, GT_*, the math block, the
; API's temporaries and what its callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/xymove/xymove.inc"

        .export P_XYMovement, friction
        .import mo_get, mo_dirty, ln_get, sec_get, ss_get, pl_get, pl_put
        .import umul16, fc_call, fc_unbuilt

; ===========================================================================
; P_XYMovement
; ===========================================================================
        ROUTINE P_XYMovement
        sta XY_MO
        stx XY_MO+1
        jsr mo_get
        ldy #LN_C + MC_MOMX             ; no momentum: nothing to do
        lda #0
        ldx #8
:       ora (GC_MP),y
        iny
        dex
        bne :-
        tay
        bne @go
        rts
@go:    lda XY_MO                       ; (CLEARCLEAN: the momentum
        ldx XY_MO+1                     ;   changes)
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda XY_MO
        ldx XY_MO+1
        jsr pl_put
        ldy #0                          ; MV_PL: the player's mobj
        lda XY_MO
        cmp G_PLAYER + PL_MO
        bne :+
        lda XY_MO+1
        cmp G_PLAYER + PL_MO + 1
        bne :+
        iny
:       sty XY_PL
        jsr xm_mo
        ldy #LN_C + MC_MOMX             ; momx, momy in -MAXMOVE..MAXMOVE
        FCALL clampMove
        ldy #LN_C + MC_MOMY
        FCALL clampMove
        jsr xm_mo
        ldy #LN_C + MC_MOMX + 7         ; xmove, ymove = momx, momy
        ldx #7
:       lda (GC_MP),y
        sta XY_XM,x
        dey
        dex
        bpl :-

        ; the move, in halves while it is more than MAXMOVE / 2
@loop:  ldx #0
        jsr big
        bcs @half
        ldx #4
        jsr big
        bcs @half
        jsr xm_mo                       ; ptry = pos + move, move = 0
        ldx #0
        jsr whole
        ldx #4
        jsr whole
        bra @try
@half:  jsr xm_mo                       ; ptry = pos + move / 2, move >>= 1
        ldx #0
        jsr half
        ldx #4
        jsr half
@try:   lda XY_MO                       ; P_TryMove(mo, ptryx, ptryy)
        sta GA_0
        lda XY_MO+1
        sta GA_1
        FCALL P_TryMove
        bcs @next
        lda XY_PL                       ; blocked: the player slides
        beq @other
        lda XY_MO
        ldx XY_MO+1
        FCALL slideMove
        bra @next
@other: jsr xm_mo                       ; a missile explodes
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_MISSILE_HI
        beq @halt
        FCALL skyHit                    ; unless it goes into the sky
        bcc @expl
        lda XY_MO
        ldx XY_MO+1
        FCALL P_RemoveMobj
        rts
@expl:  lda XY_MO
        ldx XY_MO+1
        FCALL explode
        bra @next
@halt:  ldy #LN_C + MC_MOMX             ; anything else stops
        jsr zero8
@next:  lda XY_XM                       ; while (xmove || ymove)
        ldx #7
:       ora XY_XM,x
        dex
        bne :-
        tax
        beq @fric
        jmp @loop

        ; friction: not for missiles, and not in the air
@fric:  jsr xm_mo
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_MISSILE_HI
        beq :+
        rts
:       ldy #LN_B + MB_FLOORZ           ; floorz < z: in the air
        ldx #GT_0
        jsr ld4
        ldy #TH_Z
        ldx #GT_4
        jsr ld4
        jsr slt
        bpl :+
        rts
        ; a corpse that slides off a step with some momentum goes on
:       ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_CORPSE_HI
        beq @still
        ldy #LN_C + MC_MOMX
        FCALL quarterOut
        bcs @corpse
        ldy #LN_C + MC_MOMY
        FCALL quarterOut
        bcc @still
@corpse:
        ldy #LN_A + MA_SUBSEC           ; floorz != its sector's floor
        lda (GC_MP),y
        pha
        iny
        lda (GC_MP),y
        tax
        pla
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        jsr xm_mo
        ldy #LN_B + MB_FLOORZ
        ldx #GT_0
        jsr ld4
        ldy #SEC_FLOOR
        ldx #0
:       lda GT_0,x
        cmp (GC_SP),y
        beq :+
        rts
:       iny
        inx
        cpx #4
        bne :--

        ; momentum below STOPSPEED and no player move: stop
@still: jsr xm_mo
        ldy #LN_C + MC_MOMX
        FCALL slow
        bcc @frict
        ldy #LN_C + MC_MOMY
        FCALL slow
        bcc @frict
        lda XY_PL
        beq @zero
        lda G_PLAYER + PL_CMD_FORWARDMOVE ; forwardmove | sidemove
        ora G_PLAYER + PL_CMD_SIDEMOVE
        bne @frict
        ldy #LN_A + MA_STATE            ; in a walking frame: S_PLAY
        sec
        lda (GC_MP),y
        sbc #<UC_S_PLAY_RUN1
        tax
        iny
        lda (GC_MP),y
        sbc #>UC_S_PLAY_RUN1
        bne @pmom
        cpx #4
        bcs @pmom
        lda XY_MO
        sta GA_MO
        lda XY_MO+1
        sta GA_MO+1
        lda #<UC_S_PLAY
        ldx #>UC_S_PLAY
        FCALL P_SetMobjState
@pmom:  ldx #7                          ; the player's momx = momy = 0
:       stz G_PLAYER + PL_MOMX,x
        dex
        bpl :-
@zero:  jsr xm_mo                       ; momx = momy = 0
        ldy #LN_C + MC_MOMX
        jmp zero8

        ; else friction
@frict: ldy #LN_C + MC_MOMX
        FCALL frictionAP
        jsr xm_mo
        ldy #LN_C + MC_MOMY
        FCALL frictionAP
        lda XY_PL
        beq @done
        ldx #0
        FCALL frictionNear
        ldx #4
        FCALL frictionNear
@done:  rts

; xm_mo: GC_MP = the line of the mobj XY_MO
xm_mo:  lda XY_MO
        ldx XY_MO+1
        jmp mo_get

; ld4: the zero page's 4 bytes at X = the line's 4 bytes at Y
ld4:    lda (GC_MP),y
        sta 0,x
        iny
        lda (GC_MP),y
        sta 1,x
        iny
        lda (GC_MP),y
        sta 2,x
        iny
        lda (GC_MP),y
        sta 3,x
        rts

; slt: N set when GT_0-3 < GT_4-7 (signed: the difference's sign with the
; overflow folded in, as upstream's SLT32)
slt:    ldx #0
        ldy #4
        sec
:       lda GT_0,x
        sbc GT_4,x
        inx
        dey
        bne :-
        bvc :+
        eor #$80
:       ora #0
        rts

; big (isBig): C set when the move at XY_XM + X is more than MAXMOVE / 2
; (>= $000F0001) or less than -MAXMOVE / 2 (< $FFF10000)
big:    lda XY_XM+3,x
        bmi @neg
        lda XY_XM,x
        cmp #1
        lda XY_XM+1,x
        sbc #0
        lda XY_XM+2,x
        sbc #XY_MAXMOVE_HI / 2
        lda XY_XM+3,x
        sbc #0
        rts
@neg:   lda XY_XM,x
        cmp #0
        lda XY_XM+1,x
        sbc #0
        lda XY_XM+2,x
        sbc #<($10000 - XY_MAXMOVE_HI / 2)
        lda XY_XM+3,x
        sbc #$FF
        bcs :+
        sec
        rts
:       clc
        rts

; whole (wholeMove): GA_2 + X (ptry) = the coordinate (X 0 x, 4 y) + the
; move at XY_XM + X, then the move = 0
whole:  txa
        clc
        adc #TH_X
        tay
        clc
        lda (GC_MP),y
        adc XY_XM,x
        sta GA_2,x
        iny
        lda (GC_MP),y
        adc XY_XM+1,x
        sta GA_3,x
        iny
        lda (GC_MP),y
        adc XY_XM+2,x
        sta GA_4,x
        iny
        lda (GC_MP),y
        adc XY_XM+3,x
        sta GA_5,x
        stz XY_XM,x
        stz XY_XM+1,x
        stz XY_XM+2,x
        stz XY_XM+3,x
        rts

; half (halfMove): GA_2 + X (ptry) = the coordinate + the move / 2 (toward
; 0, as C: a negative move + 1, then >> 1), then the move >>= 1
; (arithmetic)
half:   lda XY_XM,x
        sta GT_0
        lda XY_XM+1,x
        sta GT_1
        lda XY_XM+2,x
        sta GT_2
        lda XY_XM+3,x
        sta GT_3
        bpl @shr
        inc GT_0
        bne @shr
        inc GT_1
        bne @shr
        inc GT_2
        bne @shr
        inc GT_3
@shr:   lda GT_3
        cmp #$80
        ror GT_3
        ror GT_2
        ror GT_1
        ror GT_0
        txa
        clc
        adc #TH_X
        tay
        clc
        lda (GC_MP),y
        adc GT_0
        sta GA_2,x
        iny
        lda (GC_MP),y
        adc GT_1
        sta GA_3,x
        iny
        lda (GC_MP),y
        adc GT_2
        sta GA_4,x
        iny
        lda (GC_MP),y
        adc GT_3
        sta GA_5,x
        lda XY_XM+3,x                   ; move >>= 1
        cmp #$80
        ror XY_XM+3,x
        ror XY_XM+2,x
        ror XY_XM+1,x
        ror XY_XM,x
        rts

; zero8: the line's 8 bytes at Y = 0 (momx, momy), group C dirty
zero8:  lda #0
        ldx #8
:       sta (GC_MP),y
        iny
        dex
        bne :-
        lda #D_C
        jmp mo_dirty

; ===========================================================================
; clampMove: the momentum at line offset Y (the line got) to -MAXMOVE..
; MAXMOVE: above $001E0000 it becomes MAXMOVE, below $FFE20000 -MAXMOVE
; ===========================================================================
        ROUTINE clampMove
        iny                             ; Y: byte 3
        iny
        iny
        lda (GC_MP),y
        bmi @neg
        bne @pos
        dey                             ; byte 2
        lda (GC_MP),y
        cmp #XY_MAXMOVE_HI
        bcc @ok
        bne @pos1
        dey                             ; 30: the low word not 0
        lda (GC_MP),y
        dey
        ora (GC_MP),y
        beq @ok
        iny
        iny
        bra @pos1
@pos:   dey
@pos1:  lda #XY_MAXMOVE_HI              ; MAXMOVE
        ldx #0
        bra @set
@neg:   cmp #$FF                        ; below $FFE20000
        bne @neg1
        dey
        lda (GC_MP),y
        cmp #<($10000 - XY_MAXMOVE_HI)
        bcs @ok
        bra @neg2
@neg1:  dey
@neg2:  lda #<($10000 - XY_MAXMOVE_HI)  ; -MAXMOVE
        ldx #$FF
@set:   sta (GC_MP),y                   ; (Y: byte 2)
        iny
        txa
        sta (GC_MP),y
        dey
        dey
        lda #0
        sta (GC_MP),y
        dey
        sta (GC_MP),y
        lda #D_C
        jmp mo_dirty
@ok:    rts

; ===========================================================================
; skyHit: C set when the missile XY_MO that the ceiling line stopped went
; into the sky: the line has a back side, its back sector's ceiling is the
; sky's and lies below the missile's z
; ===========================================================================
        ROUTINE skyHit
        lda G_CEILLINE
        and G_CEILLINE+1
        cmp #$FF
        beq @no                         ; no ceiling line
        lda G_CEILLINE
        ldx G_CEILLINE+1
        jsr ln_get
        ldy #LN_SIDE1                   ; no back side: no back sector
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        beq @no
        ldy #LINE_SIZE + 1              ; the back sector (LVS's LNSECB)
        lda (GC_LP),y
        jsr sec_get
        ldy #SEC_CPIC                   ; its ceiling is the sky's
        lda (GC_SP),y
        cmp #XY_SKYPIC
        bne @no
        ldy #SEC_CEIL + 3               ; GT_0-3 = ceilingheight
        ldx #3
:       lda (GC_SP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        lda XY_MO
        ldx XY_MO+1
        jsr mo_get
        ldy #TH_Z                       ; ceilingheight < z (signed)
        sec
        lda GT_0
        sbc (GC_MP),y
        iny
        lda GT_1
        sbc (GC_MP),y
        iny
        lda GT_2
        sbc (GC_MP),y
        iny
        lda GT_3
        sbc (GC_MP),y
        bvc :+
        eor #$80
:       ora #0
        bpl @no
        sec
        rts
@no:    clc
        rts

; ===========================================================================
; quarterOut: C set when the momentum at line offset Y (the line got) is
; more than FRACUNIT / 4 (>= $4001) or less than -FRACUNIT / 4 (<
; $FFFFC000)
; ===========================================================================
        ROUTINE quarterOut
        iny
        iny
        iny
        lda (GC_MP),y                   ; byte 3
        bmi @neg
        bne @yes
        dey
        lda (GC_MP),y
        bne @yes
        dey
        lda (GC_MP),y
        cmp #$40
        bcc @no
        bne @yes
        dey                             ; $40: the low byte not 0
        lda (GC_MP),y
        cmp #1
        rts
@neg:   cmp #$FF
        bne @yes
        dey
        lda (GC_MP),y
        cmp #$FF
        bne @yes
        dey
        lda (GC_MP),y
        cmp #$C0
        bcc @yes
@no:    clc
        rts
@yes:   sec
        rts

; ===========================================================================
; slow: C set when the momentum at line offset Y (the line got) is more
; than -STOPSPEED (>= $FFFFF001) and less than STOPSPEED (< $1000)
; ===========================================================================
        ROUTINE slow
        iny
        iny
        iny
        lda (GC_MP),y                   ; byte 3
        bmi @neg
        bne @no
        dey
        lda (GC_MP),y
        bne @no
        dey
        lda (GC_MP),y
        cmp #$10
        bcs @no
@yes:   sec
        rts
@neg:   cmp #$FF
        bne @no
        dey
        lda (GC_MP),y
        cmp #$FF
        bne @no
        dey
        lda (GC_MP),y
        cmp #$F0
        bcc @no
        bne @yes
        dey                             ; $F0: the low byte not 0
        lda (GC_MP),y
        cmp #1
        rts
@no:    clc
        rts

; ===========================================================================
; frictionAP: the momentum of XY_MO at line offset Y (the line got) =
; friction(it), its group C dirty
; ===========================================================================
        ROUTINE frictionAP
        phy
        ldx #0
:       lda (GC_MP),y
        sta GA_0,x
        iny
        inx
        cpx #4
        bne :-
        FCALL friction
        lda XY_MO
        ldx XY_MO+1
        jsr mo_get
        ply
        ldx #0
:       lda GA_0,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_C
        jmp mo_dirty

; ===========================================================================
; frictionNear: the player's momentum (X 0 momx, 4 momy) = friction(it)
; ===========================================================================
        ROUTINE frictionNear
        phx
        ldy #0
:       lda G_PLAYER + PL_MOMX,x
        sta GA_0,y
        inx
        iny
        cpy #4
        bne :-
        FCALL friction
        plx
        ldy #0
:       lda GA_0,y
        sta G_PLAYER + PL_MOMX,x
        inx
        iny
        cpy #4
        bne :-
        rts

; ===========================================================================
; friction: GA_0-3 = FixedMul32OrigFriction(GA_0-3)
; ===========================================================================
        ROUTINE friction
        lda GA_0                        ; lo * ORIG_FRICTION
        sta M_A
        lda GA_1
        sta M_A+1
        jsr fr_f
        lda M_R+2                       ; its high word
        sta GT_0
        lda M_R+3
        sta GT_1
        lda GA_2                        ; hi * ORIG_FRICTION, unsigned
        sta M_A
        lda GA_3
        sta M_A+1
        jsr fr_f
        bit GA_3                        ; hi < 0: - ORIG_FRICTION << 16
        bpl :+
        sec
        lda M_R+2
        sbc #<UC_ORIG_FRICTION
        sta M_R+2
        lda M_R+3
        sbc #>UC_ORIG_FRICTION
        sta M_R+3
:       clc                             ; + the low product's high word
        lda M_R
        adc GT_0
        sta GA_0
        lda M_R+1
        adc GT_1
        sta GA_1
        lda M_R+2
        adc #0
        sta GA_2
        lda M_R+3
        adc #0
        sta GA_3
        rts

; fr_f: M_R = M_A (16 bits) * ORIG_FRICTION, unsigned (umul16)
fr_f:   lda #<UC_ORIG_FRICTION
        sta M_B
        lda #>UC_ORIG_FRICTION
        sta M_B+1
        jmp umul16
