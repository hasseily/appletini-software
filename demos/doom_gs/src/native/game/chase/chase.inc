; game/chase/chase.inc: part chase's places (milestone 10, docs/GAME.md
; 2.4, 4.4; docs/game-parts/chase.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_3, its
; arguments GA_*. What its routines keep across a call is in the scratch
; block SB_CHASE (32 bytes): upstream's AP (the actor, callee-saved direct
; page there) and p_enemy65.s's near scratch AC_ANGLE, AC_BASE, AC_SLOPE,
; AC_I. A_Chase, the attacks and A_BossDeath keep their bytes apart, so a
; chase routine that a dispatched action reaches inside another one
; cannot change the outer one's bytes.
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - a mobj is its handle (a slot; $FFFF none)
;   - the ACTTAB actions: the mobj in GA_MO (= GA_0-1)
;   - the attacks' helpers: the actor in AK_AP; aimLine: AK_ANG -> AK_SLOPE;
;     spreadAngle: AK_BASE -> AK_ANG; lineAttack: A = the damage;
;     damageTarget: A = the damage; spawnMissile: A = the type

CH      = SB_CHASE
        .assert SB_CHASE_SIZE >= 32, error, "chase's scratch block"
CH_AP   = CH + 0                ; (2) A_Chase: the actor (upstream's AP)
CH_TY   = CH + 2                ; (1) A_Chase: its type
AK_AP   = CH + 3                ; (2) the attacks: the actor (AP)
AK_ANG  = CH + 5                ; (4) the angle (AC_ANGLE)
AK_BASE = CH + 9                ; (4) the spread's base (AC_BASE)
AK_SLOPE = CH + 13              ; (4) the aim's slope (AC_SLOPE)
AK_I    = CH + 17               ; (1) A_SPosAttack's count (AC_I)
BD_AP   = CH + 18               ; (2) A_BossDeath: the dying boss
BD_TH   = CH + 20               ; (2)   the thinker walked
BD_NX   = CH + 22               ; (2)   its next
BD_SEC  = CH + 24               ; (1)   the tag search's sector
BD_FL   = CH + 25               ; (2)   the new floor
        .assert BD_FL + 2 <= CH + 32, error, "chase's scratch block"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

; the layouts this code relies on
        .assert >UC_MF_SHOOTABLE_LO = 0 && >UC_MF_JUSTATTACKED_LO = 0, error, "flags' byte 0"
        .assert >UC_MF_JUSTHIT_LO = 0, error, "flags' byte 0"
        .assert UC_MISSILERANGE_LO = 0, error, "MISSILERANGE whole"
        .assert GA_MO = GA_0, error, "an action's mobj in GA_0-1"
        .assert MC_THRESH = MC_MOVEDIR + 1, error, "movedir, threshold"

; GETMO place: mo_get of the handle at place
.macro GETMO place
        lda place
        ldx place+1
        jsr mo_get
.endmacro

; SOUND snd, place: S_StartSound(the mobj at place, snd); snd an immediate
; or an absolute place
.macro SOUND snd, place
        lda snd
        ldx place
        ldy place+1
        jsr S_StartSound
.endmacro

; ARG01 place: GA_0-1 = the handle at place
.macro ARG01 place
        lda place
        sta GA_0
        lda place+1
        sta GA_1
.endmacro
