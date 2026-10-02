; game/mobjstate/mstest.s: part mobjstate's test routine (milestone 10,
; docs/GAME.md 2.4's synthetic cases; docs/game-parts/mobjstate.md). In the
; part's own checkpoint image only (part.mk: MS_TEST=1), never in a wave's,
; the game's or the release's. GPL-2, the port's own.
;
;   ms_t_seq   a removal as the game makes it, in one run: Y = flags; with
;              MT_GIVEN A:X is the mobj, else P_SpawnMobj (GA_X, GA_Y,
;              GA_Z, GA_TYPE: kept in ms_t_args) makes it; MT_PREV:
;              CS_PREV1 names it; P_RemoveMobj; then its thinker's turn of
;              the walk: THTAB's entry of its kind (P_RemoveThingDelayed:
;              the free); MT_AGAIN: P_SpawnMobj again with the same
;              arguments. ms_t_res: the mobj, the second spawn's ($FFFF
;              none), the flags. A:X = the mobj
;
; tools/native/gparts/mobjstate.py runs the same steps on ref816 (--call of
; upstream's P_SpawnMobj, P_RemoveMobj, P_RemoveThingDelayed, one after
; the other) and compares the states: a zone mobj removed and its slot
; taken again (the gate "no slot handed out twice"), a zone mobj CS_PREV
; names freed ($FFFE, GT_ZPREV), a mobj with no function removed
; (linkRemove).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/mobjstate/ms.inc"

        .export ms_t_seq, ms_t_res, ms_t_args
        .import pl_get, dc_call, THTAB, fc_call, fc_unbuilt
        .import P_SpawnMobj, P_RemoveMobj

MT_GIVEN = 1
MT_PREV  = 2
MT_AGAIN = 4

.ifdef TESTBUILD
        ; test-only code goes in the card's driver area, not the core
        ; (wave 1 as integrated: the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0

ms_t_seq:
        sty ms_t_res+4
        sta ms_t_res
        stx ms_t_res+1
        lda #$FF
        sta ms_t_res+2
        sta ms_t_res+3
        ldx #GA_TYPE - GA_X     ; the spawn's arguments kept
:       lda GA_X,x
        sta ms_t_args,x
        dex
        bpl :-
        lda ms_t_res+4
        and #MT_GIVEN
        bne :+
        FCALL P_SpawnMobj
        sta ms_t_res
        stx ms_t_res+1
:       lda ms_t_res+4
        and #MT_PREV
        beq :+
        lda ms_t_res
        sta CS_PREV1
        lda ms_t_res+1
        sta CS_PREV1+1
:       lda ms_t_res
        ldx ms_t_res+1
        FCALL P_RemoveMobj
        lda ms_t_res            ; the thinker's turn: THTAB's entry of its
        sta MS_OBJ              ;   kind
        ldx ms_t_res+1
        stx MS_OBJ+1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        DCALL THTAB
        lda ms_t_res+4
        and #MT_AGAIN
        beq :++
        ldx #GA_TYPE - GA_X
:       lda ms_t_args,x
        sta GA_X,x
        dex
        bpl :-
        FCALL P_SpawnMobj
        sta ms_t_res+2
        stx ms_t_res+3
:       lda ms_t_res
        ldx ms_t_res+1
        rts

ms_t_res:  .res 8
ms_t_args: .res 16
.endif
