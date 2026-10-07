; game/mobjstate/msthink.s: part mobjstate's thinker list and frees
; (docs/GAME.md: the thinker list, the specials, the sight state, the
; parts). A GPL-2 derivative of upstream's
; p_think65.s (P_RemoveThinker, P_RemoveThing, P_RemoveThinkerDelayed,
; P_RemoveThingDelayed, unlink, P_NextThinker), p_spawn65.s (P_RemoveMobj,
; rmArg, poolFree) and r_list65.s (linkRemove).
;
;   P_RemoveThinker  A:X = a thinker: its function P_RemoveThinkerDelayed
;   P_RemoveThing    A:X = a thinker: its function P_RemoveThingDelayed
;                (the removal is late: the remover runs in the thinker's
;                turn of the walk; a mobj's kind plane loses CLEAN with its
;                new function, as upstream's byte 11)
;   P_RemoveThinkerDelayed  THTAB's (MS_OBJ = a special): out of the list,
;                then its kind's free list (gthink.s gt_spfree: Z_Free). A
;                mobj is a stop (GS_ERROR): only the specials' thinkers call
;                P_RemoveThinker (p_doors65.s, p_plats65.s, p_floor65.s)
;   P_RemoveThingDelayed  THTAB's (MS_OBJ = a mobj): out of the list; a
;                pooled one (MF_POOLED) gets type MT_NOTHING and its bit
;                (poolFree); a zone one goes first on the zone's free list
;                (G_ZMFREE through the TNL, TNH planes; its kind FN_FREE: no
;                object), and a CS_PREV1 or CS_PREV2 that named it becomes
;                stale ($FFFE) with GT_ZPREV raised (docs/GAME.md, the sight
;                state)
;   unlink     A:X = a thinker: next->prev = prev, prev->next = next (the
;                list's first and last are G_THFIRST, G_THLAST)
;   P_NextThinker  A:X = a thinker (none: the first): A:X = the next, none
;                after the last
;   poolFree   A:X = a pool slot: its bit in G_TPBITS (1: free)
;   linkRemove A:X = a mobj: with no function (FN_NONE) it is put on the
;                thinker list first (P_AddThinker: gthink.s gt_add), then
;                P_RemoveThing, so that the delayed free still runs
;   P_RemoveMobj  A:X = a mobj: P_UnsetThingPosition, P_DelSeclist, its
;                sound stopped, target and lastenemy none (but in demo
;                playback), linkRemove. upstream's rmArg is its own SB copy
;                of the mobj (RM_MO)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/mobjstate/ms.inc"

        .export P_RemoveThinker, P_RemoveThing, P_RemoveThinkerDelayed
        .export P_RemoveThingDelayed, unlink, P_NextThinker, poolFree
        .export linkRemove, P_RemoveMobj
        .import mo_get, mo_dirty, sp_get, sp_dirty, pl_get, pl_put, pl_setn
        .import gt_add, gt_spfree, g_stop, S_StopSound
        .import fc_call, fc_unbuilt
        .import P_UnsetThingPosition, P_DelSeclist

; ---------------------------------------------------------------------------
; P_RemoveThinker, P_RemoveThing: the thinker's function a remover
; ---------------------------------------------------------------------------
        ROUTINE P_RemoveThinker
        ldy #FN_REMOVETHINKER
        sta GT_0
        stx GT_1
        sty GT_2
        cpx #>SPEC_HANDLE
        bcs @spec
        jsr pl_get              ; a mobj: its kind plane
        lda GT_2
        sta PL_K
        lda GT_0
        ldx GT_1
        jmp pl_put
@spec:  jsr sp_get              ; a special: its record
        ldy #SP_FUNC
        lda GT_2
        sta (GC_XP),y
        jmp sp_dirty

        ROUTINE P_RemoveThing
        ldy #FN_REMOVETHING
        sta GT_0
        stx GT_1
        sty GT_2
        cpx #>SPEC_HANDLE
        bcs @spec
        jsr pl_get
        lda GT_2
        sta PL_K
        lda GT_0
        ldx GT_1
        jmp pl_put
@spec:  jsr sp_get
        ldy #SP_FUNC
        lda GT_2
        sta (GC_XP),y
        jmp sp_dirty

; ---------------------------------------------------------------------------
; P_RemoveThinkerDelayed
; ---------------------------------------------------------------------------
        ROUTINE P_RemoveThinkerDelayed
        lda MS_OBJ+1
        cmp #>SPEC_HANDLE
        bcs :+
        lda #GS_ERROR           ; (a mobj: never)
        jmp g_stop
:       sta TD_MO+1
        tax
        lda MS_OBJ
        sta TD_MO
        FCALL unlink
        lda TD_MO               ; Z_Free: the kind's free list
        sta GC_H
        lda TD_MO+1
        sta GC_H+1
        jmp gt_spfree

; ---------------------------------------------------------------------------
; P_RemoveThingDelayed
; ---------------------------------------------------------------------------
        ROUTINE P_RemoveThingDelayed
        lda MS_OBJ
        sta TD_MO
        ldx MS_OBJ+1
        stx TD_MO+1
        FCALL unlink
        lda TD_MO
        ldx TD_MO+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 3
        lda (GC_MP),y
        and #>UC_MF_POOLED_HI
        beq @zone
        ldy #LN_A + MA_TYPE     ; pooled: MT_NOTHING, its bit free
        lda #UC_MT_NOTHING
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        lda TD_MO
        ldx TD_MO+1
        FCALL poolFree
        rts
@zone:  ldx #2                  ; Z_Free: CS_PREV2, CS_PREV1 naming it
@prev:  lda CS_PREV1,x          ;   become stale, GT_ZPREV raised
        cmp TD_MO
        bne :+
        lda CS_PREV1+1,x
        cmp TD_MO+1
        bne :+
        lda #<STALE
        sta CS_PREV1,x
        lda #>STALE
        sta CS_PREV1+1,x
        lda #1
        sta GT_ZPREV
:       dex
        dex
        bpl @prev
        .assert CS_PREV2 = CS_PREV1 + 2, error, "CS_PREV1, CS_PREV2"
        lda G_ZMFREE            ; first on the zone's free list: its next
        sta PL_N                ;   the old first, its kind FN_FREE
        lda G_ZMFREE+1
        sta PL_N+1
        lda #FN_FREE
        sta PL_K
        stz PL_T
        lda TD_MO
        sta G_ZMFREE
        ldx TD_MO+1
        stx G_ZMFREE+1
        jmp pl_put

; ---------------------------------------------------------------------------
; unlink
; ---------------------------------------------------------------------------
        ROUTINE unlink
        sta UK_TH
        stx UK_TH+1
        cpx #>SPEC_HANDLE
        bcs @spec
        jsr pl_get              ; a mobj: its next in the planes, its prev
        lda PL_N                ;   in group A
        sta UK_NX
        lda PL_N+1
        sta UK_NX+1
        lda UK_TH
        ldx UK_TH+1
        jsr mo_get
        ldy #LN_A + MA_THPREV
        lda (GC_MP),y
        sta UK_PV
        iny
        lda (GC_MP),y
        sta UK_PV+1
        bra @have
@spec:  jsr sp_get              ; a special: both in its record
        ldy #SP_THNEXT
        lda (GC_XP),y
        sta UK_NX
        iny
        lda (GC_XP),y
        sta UK_NX+1
        ldy #SP_THPREV
        lda (GC_XP),y
        sta UK_PV
        iny
        lda (GC_XP),y
        sta UK_PV+1
@have:  ldx UK_NX+1             ; next->prev = prev (none: the last)
        cpx #$FF
        bne @nprev
        lda UK_PV
        sta G_THLAST
        lda UK_PV+1
        sta G_THLAST+1
        bra @pnext
@nprev: lda UK_NX
        cpx #>SPEC_HANDLE
        bcs @nspec
        jsr mo_get
        ldy #LN_A + MA_THPREV
        lda UK_PV
        sta (GC_MP),y
        iny
        lda UK_PV+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        bra @pnext
@nspec: jsr sp_get
        ldy #SP_THPREV
        lda UK_PV
        sta (GC_XP),y
        iny
        lda UK_PV+1
        sta (GC_XP),y
        jsr sp_dirty
@pnext: ldx UK_PV+1             ; prev->next = next (none: the first)
        cpx #$FF
        bne @pn
        lda UK_NX
        sta G_THFIRST
        lda UK_NX+1
        sta G_THFIRST+1
        rts
@pn:    lda UK_PV
        cpx #>SPEC_HANDLE
        bcs @pspec
        ldy UK_NX
        sty PL_N
        ldy UK_NX+1
        sty PL_N+1
        jmp pl_setn
@pspec: jsr sp_get
        ldy #SP_THNEXT
        lda UK_NX
        sta (GC_XP),y
        iny
        lda UK_NX+1
        sta (GC_XP),y
        jmp sp_dirty

; ---------------------------------------------------------------------------
; P_NextThinker
; ---------------------------------------------------------------------------
        ROUTINE P_NextThinker
        cpx #$FF
        bne @th
        lda G_THFIRST           ; none: the first
        ldx G_THFIRST+1
        rts
@th:    cpx #>SPEC_HANDLE
        bcs @spec
        jsr pl_get
        lda PL_N
        ldx PL_N+1
        rts
@spec:  jsr sp_get
        ldy #SP_THNEXT + 1
        lda (GC_XP),y
        tax
        dey
        lda (GC_XP),y
        rts

; ---------------------------------------------------------------------------
; poolFree
; ---------------------------------------------------------------------------
        ROUTINE poolFree
        pha
        and #7
        tay
        pla
        stx GT_0                ; the byte: slot >> 3
        lsr GT_0
        ror a
        lsr GT_0
        ror a
        lsr GT_0
        ror a
        tax
        lda G_TPBITS,x
        ora @bit,y
        sta G_TPBITS,x
        rts
@bit:   .byte $01, $02, $04, $08, $10, $20, $40, $80

; ---------------------------------------------------------------------------
; linkRemove
; ---------------------------------------------------------------------------
        ROUTINE linkRemove
        sta LR_MO
        stx LR_MO+1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        .assert FN_NONE = 0, error, "FN_NONE"
        bne @on
        lda LR_MO               ; no function: P_AddThinker (the list's
        sta GC_H                ;   last; GC_PREV the one before)
        lda LR_MO+1
        sta GC_H+1
        jsr gt_add
        lda LR_MO               ; its prev; its next none
        ldx LR_MO+1
        jsr mo_get
        ldy #LN_A + MA_THPREV
        lda GC_PREV
        sta (GC_MP),y
        iny
        lda GC_PREV+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        lda #$FF
        sta PL_N
        sta PL_N+1
        lda LR_MO
        ldx LR_MO+1
        jsr pl_setn
@on:    lda LR_MO
        ldx LR_MO+1
        FCALL P_RemoveThing
        rts

; ---------------------------------------------------------------------------
; P_RemoveMobj
; ---------------------------------------------------------------------------
        ROUTINE P_RemoveMobj
        sta RM_MO
        stx RM_MO+1
        FCALL P_UnsetThingPosition
        FCALL P_DelSeclist
        ldx RM_MO               ; S_StopSound(mobj)
        ldy RM_MO+1
        jsr S_StopSound
        lda G_DEMOPLAY          ; target = lastenemy = none (not in demo
        ora G_DEMOPLAY+1        ;   playback)
        bne @link
        lda RM_MO
        ldx RM_MO+1
        jsr mo_get
        lda #$FF
        ldy #LN_A + MA_TARGET
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        ldy #LN_C + MC_LASTEN
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        lda #D_A | D_C
        jsr mo_dirty
@link:  lda RM_MO               ; linkRemove: a quiet mobj linked, removed
        ldx RM_MO+1
        FCALL linkRemove
        rts
