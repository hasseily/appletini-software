; game/mobjstate/msstate.s: part mobjstate's states (milestone 10, docs/GAME.md
; 2.2, 2.4; docs/game-parts/mobjstate.md). A GPL-2 derivative of upstream's
; p_tick65.s (P_SetMobjState, rocketCheat, P_MobjBrainlessThinker) and
; p_mobj65.s (P_ExplodeMissile, explode, P_MobjIsPlayer).
;
;   P_SetMobjState  MS_OBJ = a mobj, A:X = a state: S_NULL: its state none
;                and P_RemoveMobj, A = 0; else its state, sprite and frame,
;                then its tics, then the state's action (ACTTAB through
;                DCALL, the mobj in MS_OBJ: upstream's callFn), and while
;                the mobj's tics are 0 the same with its state's next; A =
;                1. With the cheat CF_ENEMY_ROCKETS a state with an action
;                in [missilestate, painstate) of the mobj's type calls
;                A_CyberAttack instead (rocketCheat; FCALL A_CyberAttack).
;                The mobj is on the stack while an action runs: an action
;                may call P_SetMobjState again
;   rocketCheat  A:X = a state, MS_OBJ = the mobj: C set when the state is
;                in [missilestate, painstate) of the mobj's type
;                (missilestate not 0; signed compares)
;   P_MobjBrainlessThinker  THTAB's (MS_OBJ = a mobj): tics -1 stay; else
;                tics - 1, and at 0 P_SetMobjState(mobj, its state's next)
;   P_ExplodeMissile, explode  A:X = a missile: no momentum, its death
;                state, tics -= P_Random() & 3 (at least 1), not
;                MF_MISSILE, its death sound
;   P_MobjIsPlayer  A:X = a mobj: A:X = the player (G_PLAYER) when it is
;                the player's mobj, else 0

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/mobjstate/ms.inc"

        .export P_SetMobjState, rocketCheat, P_MobjBrainlessThinker
        .export P_ExplodeMissile, explode, P_MobjIsPlayer
        .import mo_get, mo_dirty, pl_get, pl_put, state_at, act_num
        .import dc_call, ACTTAB, fc_call, fc_unbuilt, g_random
        .import S_StartSound, mi_get
        .import P_RemoveMobj, A_CyberAttack

; ---------------------------------------------------------------------------
; P_SetMobjState: GT_0-1 the state, GT_2-3 the mobj, GT_4 the action
; ---------------------------------------------------------------------------
        ROUTINE P_SetMobjState
        sta GT_0
        stx GT_1
        lda MS_OBJ
        sta GT_2
        lda MS_OBJ+1
        sta GT_3
@loop:  lda GT_0
        ora GT_1
        bne @state
        lda GT_2                ; S_NULL: mobj->state = NULL, P_RemoveMobj,
        ldx GT_3                ;   false
        jsr mo_get
        lda #$FF
        ldy #LN_A + MA_STATE
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        lda GT_2
        ldx GT_3
        FCALL P_RemoveMobj
        lda #0
        rts
@state: lda GT_0                ; st = &states[state] (LW_STATE)
        ldx GT_1
        jsr state_at
        lda GT_2                ; mobj->state, ->sprite, ->frame
        ldx GT_3
        jsr mo_get
        ldy #LN_A + MA_STATE
        lda GT_0
        sta (GC_MP),y
        iny
        lda GT_1
        sta (GC_MP),y
        ldy #TH_SPR
        lda LW_STATE + U_ST_SPRITE
        sta (GC_MP),y
        ldy #TH_FRAME
        lda LW_STATE + U_ST_FRAME
        sta (GC_MP),y
        iny
        lda LW_STATE + U_ST_FRAME + 1
        sta (GC_MP),y
        lda #D_RTH | D_A
        jsr mo_dirty
        lda GT_2                ; mobj->tics = st->tics (a byte: -1, 1-12)
        ldx GT_3
        jsr pl_get
        lda LW_STATE + U_ST_TICS
        sta PL_T
        lda GT_2
        ldx GT_3
        jsr pl_put
        jsr act_num             ; if (st->action): its ACTTAB number
        beq @next
        sta GT_4
        lda G_PLAYER + PL_CHEATS
        and #UC_CF_ENEMY_ROCKETS
        beq @call
        lda GT_0                ; the rocket cheat
        ldx GT_1
        FCALL rocketCheat
        bcc @call
        stz GT_4                ; (0: A_CyberAttack)
@call:  lda GT_3                ; the mobj on the stack while the action
        pha                     ;   runs; the action's in MS_OBJ
        lda GT_2
        pha
        sta MS_OBJ
        lda GT_3
        sta MS_OBJ+1
        lda GT_4
        beq @cyber
        DCALL ACTTAB
        bra @back
@cyber: FCALL A_CyberAttack
@back:  pla
        sta GT_2
        pla
        sta GT_3
@next:  lda GT_2                ; while (!mobj->tics)
        ldx GT_3
        jsr pl_get
        lda PL_T
        bne @true
        lda GT_2                ;   state = mobj->state->nextstate
        ldx GT_3
        jsr mo_get
        ldy #LN_A + MA_STATE + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr state_at
        lda LW_STATE + U_ST_NEXTSTATE
        sta GT_0
        lda LW_STATE + U_ST_NEXTSTATE + 1
        sta GT_1
        lda GT_2                ; (MS_OBJ the mobj again: rocketCheat's)
        sta MS_OBJ
        lda GT_3
        sta MS_OBJ+1
        jmp @loop
@true:  lda #1
        rts

; ---------------------------------------------------------------------------
; rocketCheat
; ---------------------------------------------------------------------------
        ROUTINE rocketCheat
        sta RC_ST
        stx RC_ST+1
        lda MS_OBJ              ; the mobj's type
        ldx MS_OBJ+1
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        sta RC_T
        ldy #UO_MI_MISSILESTATE ; mobjinfo[type].missilestate, not 0
        jsr mi_get
        lda MS_W
        ora MS_W+1
        beq @no
        sec                     ; state >= missilestate (signed)
        lda RC_ST
        sbc MS_W
        lda RC_ST+1
        sbc MS_W+1
        bvc :+
        eor #$80
:       bmi @no
        lda RC_T                ; state < painstate (signed)
        ldy #UO_MI_PAINSTATE
        jsr mi_get
        sec
        lda RC_ST
        sbc MS_W
        lda RC_ST+1
        sbc MS_W+1
        bvc :+
        eor #$80
:       bpl @no
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; P_MobjBrainlessThinker
; ---------------------------------------------------------------------------
        ROUTINE P_MobjBrainlessThinker
        lda MS_OBJ
        ldx MS_OBJ+1
        jsr pl_get
        lda PL_T
        cmp #$FF                ; -1: the state stays
        beq @done
        dec a                   ; --tics
        sta PL_T
        lda MS_OBJ
        ldx MS_OBJ+1
        jsr pl_put
        lda PL_T
        bne @done
        lda MS_OBJ              ; P_SetMobjState(mobj, mobj->state->
        ldx MS_OBJ+1            ;   nextstate)
        jsr mo_get
        ldy #LN_A + MA_STATE + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr state_at
        lda LW_STATE + U_ST_NEXTSTATE
        ldx LW_STATE + U_ST_NEXTSTATE + 1
        FCALL P_SetMobjState
@done:  rts

; ---------------------------------------------------------------------------
; P_ExplodeMissile, explode
; ---------------------------------------------------------------------------
        ROUTINE P_ExplodeMissile
        FCALL explode
        lda #0
        rts

        ROUTINE explode
        sta GT_0
        stx GT_1
        jsr mo_get              ; momx = momy = momz = 0
        lda #0
        ldy #LN_C + MC_MOMX
        ldx #12
:       sta (GC_MP),y
        iny
        dex
        bne :-
        .assert MC_MOMY = MC_MOMX + 4 && MC_MOMZ = MC_MOMY + 4, error,  "the momentum"
        ldy #LN_A + MA_TYPE     ; (its type)
        lda (GC_MP),y
        sta GT_2
        lda #D_C
        jsr mo_dirty
        lda GT_2                ; P_SetMobjState(mo, deathstate)
        ldy #UO_MI_DEATHSTATE
        jsr mi_get
        lda GT_1                ; (the missile kept on the stack)
        pha
        lda GT_0
        pha
        sta MS_OBJ
        lda GT_1
        sta MS_OBJ+1
        lda MS_W
        ldx MS_W+1
        FCALL P_SetMobjState
        pla
        sta GT_0
        pla
        sta GT_1
        jsr g_random            ; tics -= P_Random() & 3; at least 1
        and #3
        sta GT_2
        lda GT_0
        ldx GT_1
        jsr pl_get
        sec
        lda PL_T
        sbc GT_2
        beq :+
        bpl :++
:       lda #1
:       sta PL_T
        lda GT_0
        ldx GT_1
        jsr pl_put
        lda GT_0                ; flags &= ~MF_MISSILE
        ldx GT_1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #$FF ^ UC_MF_MISSILE_HI
        sta (GC_MP),y
        ldy #LN_A + MA_TYPE     ; (its type)
        lda (GC_MP),y
        sta GT_2
        lda #D_B
        jsr mo_dirty
        lda GT_2                ; the death sound
        ldy #UO_MI_DEATHSOUND
        jsr mi_get
        lda MS_W
        ora MS_W+1
        beq @done
        lda MS_W
        ldx GT_0
        ldy GT_1
        jmp S_StartSound
@done:  rts

; ---------------------------------------------------------------------------
; P_MobjIsPlayer
; ---------------------------------------------------------------------------
        ROUTINE P_MobjIsPlayer
        cmp G_PLAYER + PL_MO
        bne @no
        cpx G_PLAYER + PL_MO + 1
        bne @no
        lda #<G_PLAYER
        ldx #>G_PLAYER
        rts
@no:    lda #0
        tax
        rts
