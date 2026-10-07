; game/look/look.inc: part look's places (docs/GAME.md, the parts;
; zero page and scratch). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6
; (GT_7 on is the object API's) and the math block, its arguments GA_*.
; What its routines keep across a call is in the scratch block SB_LOOK
; (32 bytes): upstream's AP and AT of p_enemy65.s (the actor and its
; target, callee-saved direct page there; natively each entry takes its
; actor in GA_0-1 and sets LK_AP) and p_attack65.s's AT_B* (the radius
; attack's spot, source and damage, read by every PIT_RadiusAttack call).
; P_RadiusAttack keeps its block loop on the stack, as upstream does
; (P_DamageMobj runs game logic).
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - a mobj is its handle (a slot; $FFFF none)
;   - the ACTTAB actions: the mobj in GA_MO (= GA_0-1)
;   - lookForPlayers: GA_0-1 the actor, A = allaround; A = 1 seen, 0 not
;   - behindFast: GA_0-1 the actor, GA_2-3 the target; C set: A = 1
;     behind, 0 in front; C clear: it cannot tell (A = $FF)
;   - checkMeleeRange, checkMissileRange, P_CheckMeleeRange,
;     P_CheckMissileRange, faceTarget, loadTarget: GA_0-1 the actor
;   - angleToAT, distanceAT: LK_AP, LK_AT (the part's own); M_R the result
;   - p_enemy_randMod: A = the modulus; p_enemy_startSound: A = the sound,
;     GA_0-1 the origin
;   - P_RadiusAttack: GA_0-1 the spot, GA_2-3 the source, GA_4-5 the damage
;   - PIT_RadiusAttack (ITTAB): GA_0-1 the thing; C set (go on)

LK      = SB_LOOK
        .assert SB_LOOK_SIZE >= 32, error, "look's scratch block"
LK_AP   = LK + 0                ; (2) the actor (upstream's AP)
LK_AT   = LK + 2                ; (2) its target (upstream's AT)
LK_BSPOT = LK + 4               ; (2) P_RadiusAttack: bombspot (AT_BSPOT)
LK_BSRC = LK + 6                ; (2)   bombsource (AT_BSOURCE)
LK_BDMG = LK + 8                ; (2)   bombdamage (AT_BDAMAGE)
LK_BTHING = LK + 10             ; (2) PIT_RadiusAttack: the thing
LK_BDIST = LK + 12              ; (2)   its distance (AT_BDIST)
LK_T    = LK + 14               ; (4) a temporary (EN_T, AT_T)
LK_D    = LK + 18               ; (4) a temporary (EN_D, AT_DIST)
        .assert LK_D + 4 <= LK + 32, error, "look's scratch block"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
LN_B    = 2 * MO_SIZE
LN_C    = 3 * MO_SIZE
D_RTH   = 1
D_A     = 2
D_B     = 4
D_C     = 8

        .assert TH_X = 0 && TH_Y = 4, error, "RTHING's x, y first"
; the flags' bytes this part reads or changes (mobj_t flags: 4 bytes)
        .assert >UC_MF_SHOOTABLE_LO = 0 && >UC_MF_AMBUSH_LO = 0, error, "flags' byte 0"
        .assert >UC_MF_JUSTHIT_LO = 0 && >UC_MF_SOLID_LO = 0, error, "flags' byte 0"
        .assert UC_MF_SHADOW_LO = 0 && >UC_MF_SHADOW_HI = 0, error, "flags' byte 2"
        .assert UC_MELEERANGE_LO = 0, error, "MELEERANGE whole"

; DELTA tgt, act: M_A = tgt's x - act's x, M_B = tgt's y - act's y (32
; bits each; tgt and act the places of two mobj handles). Changes A, X,
; Y, the API's temporaries.
.macro DELTA tgt, act
        lda tgt
        ldx tgt+1
        jsr mo_get
        ldy #7
:       lda (GC_MP),y
        sta M_A,y
        dey
        bpl :-
        lda act
        ldx act+1
        jsr mo_get
        ldy #0
        sec
:       lda M_A,y
        sbc (GC_MP),y
        sta M_A,y
        iny
        tya
        and #3
        bne :-
        sec
:       lda M_A,y
        sbc (GC_MP),y
        sta M_A,y
        iny
        tya
        and #3
        bne :-
.endmacro

; ABS16 src, dst: the word at dst = |the word at src| (16-bit two's
; complement: |$8000| = $8000, upstream's eor / inc). Changes A.
.macro ABS16 src, dst
        lda src+1
        bpl :+
        sec
        lda #0
        sbc src
        sta dst
        lda #0
        sbc src+1
        sta dst+1
        bra :++
:       lda src
        sta dst
        lda src+1
        sta dst+1
:
.endmacro

; GETMO place: mo_get of the handle at place
.macro GETMO place
        lda place
        ldx place+1
        jsr mo_get
.endmacro
