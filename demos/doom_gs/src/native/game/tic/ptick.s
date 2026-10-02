; game/tic/ptick.s: part tic's level tic and thinker walk (milestone 10,
; docs/GAME.md 1.3, 2.2 THTAB, 2.4, 5.1; docs/game-parts/tic.md). A GPL-2
; derivative of upstream's p_think65.s (P_Ticker) and p_tick65.s
; (P_RunThinkers, P_MobjThinker with mobjArg and stillMobjThinker), the
; release's TICSTEP 1 (tics.inc) (Doom8088: Apple IIgs Edition).
;
;   P_Ticker        one tic of the level: nothing while the menu is up out
;                   of a demo, unless viewz is 1 (the tic after a setup);
;                   P_PlayerThink (gamestate GS_LEVEL), P_RunThinkers,
;                   P_UpdateSpecials, P_MapEnd, then leveltime + 1
;   P_RunThinkers   the walk of the thinker list from G_THFIRST: a thinker's
;                   next is read before its turn (RT_NEXT: a call may remove
;                   it, and a removed thinker's link is its free list's);
;                   a mobj's next, kind and tics from the planes (pl_get), a
;                   special's from its record. A mobj of P_MobjThinker with
;                   no momentum on its floor gets CLEAN (the kind plane's
;                   bit 7, upstream's byte 11 = 1) and then, as one CLEAN
;                   already, and as P_MobjBrainlessThinker's, only its tics:
;                   -1 stays (but a CLEAN COUNTKILL mobj with
;                   respawnmonsters: P_MobjThinker), else - 1, and at 0
;                   P_SetMobjState(mobj, its state's next) (upstream's
;                   inline state change, the same as P_SetMobjState's);
;                   a mobj of P_MobjThinker that is not clean: P_MobjThinker;
;                   no function: nothing; any other function: THTAB (DCALL,
;                   the thinker in GA_MO)
;   P_MobjThinker   THTAB's (GA_MO = a mobj): with momx or momy
;                   P_XYMovement, and if its function is no longer
;                   P_MobjThinker (removed) the end; with z != floorz or
;                   momz P_ZMovement, the same; then its tics: -1 is the
;                   nightmare respawn (MF_COUNTKILL, respawnmonsters,
;                   ++movecount >= 12 * 35, leveltime & 31 = 0, P_Random()
;                   <= 4: P_NightmareRespawn), else - 1 and at 0
;                   P_SetMobjState(mobj, its state's next)
;
; mobjArg (upstream's _Dp = MO_P) and stillMobjThinker (the function still
; P_MobjThinker) are P_MobjThinker's local subroutines mt_mo and mt_still,
; with no label of the part table (request R1: INLINED). Every routine changes A, X, Y, GA_*, GT_* and what its callees
; change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/tic/tic.inc"

        .export P_Ticker, P_RunThinkers, P_MobjThinker
        .import mo_get, mo_dirty, pl_get, pl_put, sp_get, state_at
        .import dc_call, THTAB, fc_call, fc_unbuilt, g_random

; TK_ZMOVE: Z clear when the mobj line GC_MP has z != floorz or momz != 0
; (upstream's "if (mobj->z != mobj->floorz || mobj->momz)")
.macro TK_ZMOVE
        .local loop, done
        ldy #TH_Z
        ldx #0
loop:   lda (GC_MP),y
        sta GT_0,x
        iny
        inx
        cpx #4
        bne loop
        ldy #TK_LN_B + MB_FLOORZ
        ldx #0
:       lda (GC_MP),y
        cmp GT_0,x
        bne done
        iny
        inx
        cpx #4
        bne :-
        ldy #TK_LN_C + MC_MOMZ
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        iny
        ora (GC_MP),y
        iny
        ora (GC_MP),y
done:
.endmacro

; TK_NEXTSTATE mo: P_SetMobjState(mo, mo->state->nextstate) (the mobj in
; GA_MO, mobjstate's MS_OBJ)
.macro TK_NEXTSTATE mo
        lda mo
        ldx mo+1
        jsr mo_get
        ldy #TK_LN_A + MA_STATE + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr state_at
        lda mo
        sta GA_MO
        lda mo+1
        sta GA_MO+1
        lda LW_STATE + U_ST_NEXTSTATE
        ldx LW_STATE + U_ST_NEXTSTATE + 1
        FCALL P_SetMobjState
.endmacro

; ---------------------------------------------------------------------------
; P_Ticker
; ---------------------------------------------------------------------------
        ROUTINE P_Ticker
        lda G_MENUACTIVE        ; paused in the menu (not in a demo), but
        ora G_MENUACTIVE+1      ;   the tic after a setup (viewz 1)
        beq pt_run
        lda G_DEMOPLAY
        ora G_DEMOPLAY+1
        bne pt_run
        lda G_PLAYER + PL_VIEWZ_G
        cmp #1
        bne pt_rts
        lda G_PLAYER + PL_VIEWZ_G + 1
        ora G_PLAYER + PL_VIEWZ_G + 2
        ora G_PLAYER + PL_VIEWZ_G + 3
        bne pt_rts
pt_run: lda G_GAMESTATE         ; the player (in a level)
        ora G_GAMESTATE+1
        bne :+
        FCALL P_PlayerThink
:       FCALL P_RunThinkers
        FCALL P_UpdateSpecials
        FCALL P_MapEnd
        inc G_LEVELTIME         ; leveltime++, after the specials
        bne pt_rts
        inc G_LEVELTIME+1
        bne pt_rts
        inc G_LEVELTIME+2
        bne pt_rts
        inc G_LEVELTIME+3
pt_rts: rts

; ---------------------------------------------------------------------------
; P_RunThinkers
; ---------------------------------------------------------------------------
        ROUTINE P_RunThinkers
        lda G_THFIRST
        ldx G_THFIRST+1
rt_th:  cpx #$FF                ; none (a handle's high byte $FF names
        bne :+                  ;   nothing else): the list's end
        rts
:       sta RT_TH
        stx RT_TH+1
        cpx #>SPEC_HANDLE
        bcs rt_spec
        jsr pl_get              ; a mobj: its next (read before its turn),
        lda PL_N                ;   its kind and tics
        sta RT_NEXT
        lda PL_N+1
        sta RT_NEXT+1
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta TK_KIND
        cmp #FN_MOBJ
        beq rt_mobj
        cmp #FN_BRAINLESS
        jeq rt_tics
        cmp #FN_NONE            ; no function: nothing
        beq rt_step
        bra rt_call
rt_spec:
        jsr sp_get              ; a special: its next and function
        ldy #SP_THNEXT
        lda (GC_XP),y
        sta RT_NEXT
        iny
        lda (GC_XP),y
        sta RT_NEXT+1
        ldy #SP_FUNC
        lda (GC_XP),y
        beq rt_step
rt_call:
        ldx RT_TH               ; th->function(th): THTAB
        stx GA_MO
        ldx RT_TH+1
        stx GA_MO+1
        DCALL THTAB
rt_step:
        lda RT_NEXT             ; th = the next read before
        ldx RT_NEXT+1
        jmp rt_th

rt_mobj:
        bit PL_K                ; CLEAN: only its tics
        bmi rt_tics
        lda RT_TH               ; no momentum and on its floor: CLEAN
        ldx RT_TH+1
        jsr mo_get
        ldy #TK_LN_C + MC_MOMX
        lda #0
:       ora (GC_MP),y
        iny
        cpy #TK_LN_C + MC_MOMY + 4
        bne :-
        tax
        jne rt_full
        TK_ZMOVE
        bne rt_full
        lda PL_K
        ora #KIND_CLEAN
        sta PL_K
        lda RT_TH
        ldx RT_TH+1
        jsr pl_put
rt_tics:
        lda PL_T                ; the tics: -1 or 1-12 (a byte)
        cmp #$FF
        beq rt_ever
        dec a
        sta PL_T
        lda RT_TH
        ldx RT_TH+1
        jsr pl_put
        lda PL_T
        bne rt_step
        TK_NEXTSTATE RT_TH      ; the state ends
        jmp rt_step
rt_ever:
        lda TK_KIND             ; -1: only a P_MobjThinker's COUNTKILL
        cmp #FN_MOBJ            ;   mobj with respawnmonsters has more
        jne rt_step             ;   to do (the nightmare respawn)
        lda G_RESPAWN
        ora G_RESPAWN+1
        jeq rt_step
        lda RT_TH
        ldx RT_TH+1
        jsr mo_get
        ldy #TK_LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_COUNTKILL_HI
        jeq rt_step
rt_full:
        lda RT_TH               ; P_MobjThinker(th)
        sta GA_MO
        lda RT_TH+1
        sta GA_MO+1
        FCALL P_MobjThinker
        jmp rt_step
        .assert UC_MF_COUNTKILL_LO = 0, error, "MF_COUNTKILL's byte"

; ---------------------------------------------------------------------------
; P_MobjThinker
; ---------------------------------------------------------------------------
        ROUTINE P_MobjThinker
        lda GA_MO
        sta TK_MO
        ldx GA_MO+1
        stx TK_MO+1
        jsr mo_get              ; momentum movement (momx, momy)
        ldy #TK_LN_C + MC_MOMX
        lda #0
:       ora (GC_MP),y
        iny
        cpy #TK_LN_C + MC_MOMY + 4
        bne :-
        tax
        beq mt_z
        jsr mt_mo
        FCALL P_XYMovement
        jsr mt_still            ; removed: the end
        jne mt_rts
mt_z:   jsr mt_mo               ; z != floorz or momz: P_ZMovement
        jsr mo_get
        TK_ZMOVE
        beq mt_tics
        jsr mt_mo
        FCALL P_ZMovement
        jsr mt_still
        bne mt_rts
mt_tics:
        jsr mt_mo               ; the tics: -1 or 1-12
        jsr pl_get
        lda PL_T
        cmp #$FF
        beq mt_nm
        dec a
        sta PL_T
        jsr mt_mo
        jsr pl_put
        lda PL_T
        bne mt_rts
        jsr mt_mo               ; the state ends: P_SetMobjState(mobj,
        jsr mo_get              ;   mobj->state->nextstate)
        ldy #TK_LN_A + MA_STATE + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr state_at
        lda TK_MO
        sta GA_MO
        lda TK_MO+1
        sta GA_MO+1
        lda LW_STATE + U_ST_NEXTSTATE
        ldx LW_STATE + U_ST_NEXTSTATE + 1
        FCALL P_SetMobjState
mt_rts: rts

mt_nm:  jsr mt_mo               ; the nightmare respawn: MF_COUNTKILL,
        jsr mo_get              ;   respawnmonsters
        ldy #TK_LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_COUNTKILL_HI
        beq mt_rts
        lda G_RESPAWN
        ora G_RESPAWN+1
        beq mt_rts
        ldy #TK_LN_C + MC_MOVEC ; if (++movecount < 12 * 35) return
        lda (GC_MP),y           ;   (signed)
        inc a
        sta (GC_MP),y
        bne :+
        iny
        lda (GC_MP),y
        inc a
        sta (GC_MP),y
:       lda #TK_D_C
        jsr mo_dirty
        ldy #TK_LN_C + MC_MOVEC
        sec
        lda (GC_MP),y
        sbc #<TK_RESPAWN_TICS
        iny
        lda (GC_MP),y
        sbc #>TK_RESPAWN_TICS
        bvc :+
        eor #$80
:       bmi mt_rts
        lda G_LEVELTIME         ; if (leveltime & 31) return
        and #31
        bne mt_rts
        jsr g_random            ; if (P_Random() > 4) return
        cmp #5
        bcs mt_rts
        jsr mt_mo
        FCALL P_NightmareRespawn
        rts

; mt_still: Z set when TK_MO's function is still P_MobjThinker (upstream's
; stillMobjThinker: the kind plane, CLEAN aside); mt_mo: A:X = TK_MO
; (upstream's mobjArg). Local subroutines: their return is on the stack
; under pl_get (request R3: OWN_STACK)
mt_still:
        jsr mt_mo
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        cmp #FN_MOBJ
        rts
mt_mo:  lda TK_MO
        ldx TK_MO+1
        rts
