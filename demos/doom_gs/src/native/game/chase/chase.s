; game/chase/chase.s: part chase (milestone 10, wave 6; docs/GAME.md 2.4;
; docs/game-parts/chase.md). A GPL-2 derivative of upstream's p_enemy65.s
; (A_Chase with TICSTEP 1, the release's; A_PosAttack, A_SPosAttack,
; A_TroopAttack, A_SargAttack, A_CyberAttack, A_BruisAttack, A_Explode,
; A_BossDeath; the helpers lineAttack, aimLine, spreadAngle, damageTarget,
; spawnMissile).
;
;   A_Chase       GA_MO = the actor: reactiontime - 1 when not 0; a
;                 threshold: - 1 while the target lives, else 0; turned
;                 towards its movedir (the angle a multiple of ANG45, 45
;                 degrees a call); no shootable target: lookForPlayers(1),
;                 else its spawn state; just attacked: the flag cleared and
;                 (but at nightmare) a new direction; the melee attack
;                 (attack sound, melee state, MF_JUSTHIT with no missile
;                 state); the missile attack (movecount 0 or nightmare,
;                 checkMissileRange: the missile state, MF_JUSTATTACKED);
;                 with no threshold the pursuit count (0: BASETHRESHOLD and
;                 a new target unless the live target is seen); --movecount
;                 < 0 or a refused pMove: newChaseDir; the active sound when
;                 P_Random() < 3
;   A_PosAttack   faced: the aim, the pistol sound, the angle spread, the
;                 damage (P_Random() % 5 + 1) * 3, P_LineAttack
;   A_SPosAttack  with a target: the shotgun sound, faced, the aim, three
;                 pellets as A_PosAttack's from the same base angle
;   A_TroopAttack faced: in melee range the claw sound and P_DamageMobj of
;                 (P_Random() & 7 + 1) * 3, else a troopshot
;   A_SargAttack  faced and in melee range: P_DamageMobj of (P_Random() % 10
;                 + 1) * 4
;   A_CyberAttack faced: the rocket sound and a rocket
;   A_BruisAttack with a target: in melee range the claw sound and
;                 P_DamageMobj of (P_Random() & 7 + 1) * 10, else a
;                 bruisershot
;   A_Explode     P_RadiusAttack(it, its target, 128)
;   A_BossDeath   on map 8, for a baron, with the player alive: when no
;                 other baron of the thinkers lives, the floors of tag 666
;                 down to the lowest floor next to each (EV_DoFloor's
;                 lowerFloorToLowest, upstream's junk line of tag 666)
;
; Every product and divide is milestone 6's (p_enemy_randMod: math.s's
; sdiv16, upstream's _Mod16); the P_Random calls are upstream's, in its
; order. Upstream's helpers of the same file that part look built
; (loadTarget, faceTarget, randMod, startSound, checkMeleeRange,
; checkMissileRange, lookForPlayers) are called through FCALL, but
; loadTarget's and startSound's few bytes, which are done in place (the
; target read from the actor's line; S_StartSound, the core's hook).
;
; A_BossDeath's floors (request 1): upstream calls EV_DoFloor with a junk
; line of tag 666 (AC_JUNK); a native line's tag is a byte (no line of E1
; has a tag above 127), so EV_DoFloor (part evfloor) cannot be given that
; line. The stand-in bd_floors below does EV_DoFloor's lowerFloorToLowest
; for the tag 666 itself, from part evfloor's newFloor and part secfind's
; P_FindLowestFloorSurrounding and the floor's layout (llayout's SPFL_*),
; as evfloor's floorUp (down) and setDest write it.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/chase/chase.inc"

        .export A_Chase, A_PosAttack, A_SPosAttack, A_TroopAttack
        .export A_SargAttack, A_CyberAttack, A_BruisAttack, A_Explode
        .export A_BossDeath, lineAttack, aimLine, spreadAngle, damageTarget
        .export spawnMissile
        .import mo_get, mo_dirty, mi_get, sec_get, sp_get, sp_dirty, pl_get
        .import g_random, S_StartSound
        .import fc_call, fc_unbuilt

PLR     = G_PLAYER
BOSSTAG = 666                   ; A_BossDeath's tag (p_enemy65.s:2134)
FLOORSPEED_HI = UC_FRACUNIT_HI  ; FLOORSPEED = FRACUNIT (p_floor65.s:46)

; ===========================================================================
; A_Chase
; ===========================================================================
        ROUTINE A_Chase
        lda GA_MO
        sta CH_AP
        lda GA_MO+1
        sta CH_AP+1
        GETMO CH_AP
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        sta CH_TY
        ldy #LN_C + MC_REACT    ; if (reactiontime) reactiontime--
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        beq @thresh
        dey
        lda (GC_MP),y
        sec
        sbc #1
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #0
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
@thresh:
        ldy #LN_C + MC_THRESH   ; a threshold: - 1 while the target lives
        lda (GC_MP),y
        beq @turn
        ldy #LN_A + MA_TARGET + 1
        lda (GC_MP),y
        cmp #$FF                ; no target
        beq @thr0
        tax
        dey
        lda (GC_MP),y
        jsr mo_get              ; its health > 0
        ldy #LN_A + MA_HEALTH + 1
        lda (GC_MP),y
        bmi @thr0g
        dey
        ora (GC_MP),y
        beq @thr0g
        GETMO CH_AP             ; threshold--
        ldy #LN_C + MC_THRESH
        lda (GC_MP),y
        dec a
        bra @thrst
@thr0g: GETMO CH_AP
@thr0:  lda #0                  ; threshold = 0
@thrst: ldy #LN_C + MC_THRESH
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty

        ; turn towards the movement direction: the angle's high word &=
        ; 7 << 13 and its low word 0, then 45 degrees towards movedir << 13
        ; (only the high byte is not 0: the sign of the difference is its
        ; bit 7)
@turn:  ldy #LN_C + MC_MOVEDIR
        lda (GC_MP),y
        cmp #8
        bcs @look
        asl a
        asl a
        asl a
        asl a
        asl a
        sta GT_0                ; T = movedir << 5 (the high byte)
        ldy #TH_ANG + 1
        lda (GC_MP),y
        and #$E0
        sta GT_1
        sec                     ; delta = angle - T
        sbc GT_0
        beq @ang
        bmi @plus
        lda GT_1                ; delta > 0: angle -= ANG90 / 2
        sec
        sbc #$20
        bra @angst
@plus:  lda GT_1                ; delta < 0: angle += ANG90 / 2
        clc
        adc #$20
@angst: sta GT_1
@ang:   lda #0
        ldy #TH_ANGLO
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        ldy #TH_ANG
        sta (GC_MP),y
        iny
        lda GT_1
        sta (GC_MP),y
        lda #D_RTH
        jsr mo_dirty

        ; no target that can be shot: look for a new one
@look:  ldy #LN_A + MA_TARGET + 1
        lda (GC_MP),y
        cmp #$FF
        beq @nolook
        tax
        dey
        lda (GC_MP),y
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        bne @target
@nolook:
        ARG01 CH_AP             ; lookForPlayers(actor, true)
        lda #1
        FCALL lookForPlayers
        cmp #0
        bne @rts1
        lda CH_TY               ; no new target: the spawn state
        ldy #UO_MI_SPAWNSTATE
        jmp ch_state

        ; do not attack twice in a row
@target:
        GETMO CH_AP
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        bit #<UC_MF_JUSTATTACKED_LO
        beq @melee
        and #<~UC_MF_JUSTATTACKED_LO
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
        lda G_GAMESKILL
        cmp #UC_SK_NIGHTMARE
        beq @rts1
        ARG01 CH_AP
        FCALL newChaseDir
@rts1:  rts

        ; the melee attack
@melee: lda CH_TY
        ldy #UO_MI_MELEESTATE
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @missile
        ARG01 CH_AP
        FCALL checkMeleeRange
        cmp #0
        beq @missile
        lda CH_TY               ; the attack sound
        ldy #UO_MI_ATTACKSOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq :+
        SOUND API_W, CH_AP
:       lda CH_TY               ; P_SetMobjState(actor, meleestate)
        ldy #UO_MI_MELEESTATE
        jsr ch_state
        lda CH_TY               ; no missile: remember the attack
        ldy #UO_MI_MISSILESTATE
        jsr mi_get
        stx GT_0
        ora GT_0
        bne @rts1
        lda #<UC_MF_JUSTHIT_LO
        jmp ch_flag

        ; the missile attack
@missile:
        lda CH_TY
        ldy #UO_MI_MISSILESTATE
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @pursue
        lda G_GAMESKILL         ; !(gameskill < nightmare && movecount)
        cmp #UC_SK_NIGHTMARE
        bcs @range
        GETMO CH_AP
        ldy #LN_C + MC_MOVEC
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        bne @pursue
@range: ARG01 CH_AP
        FCALL checkMissileRange
        cmp #0
        beq @pursue
        lda CH_TY               ; P_SetMobjState(actor, missilestate)
        ldy #UO_MI_MISSILESTATE
        jsr ch_state
        lda #<UC_MF_JUSTATTACKED_LO
        jmp ch_flag

        ; the pursuit time, and maybe a new target
@pursue:
        GETMO CH_AP
        ldy #LN_C + MC_THRESH
        lda (GC_MP),y
        bne @chase
        ldy #LN_C + MC_PURSUE   ; pursuecount: not 0: - 1
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        beq @p41
        dey
        lda (GC_MP),y
        sec
        sbc #1
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #0
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        bra @chase
@p41:   lda #0                  ; 0: BASETHRESHOLD again
        sta (GC_MP),y
        dey
        lda #UC_BASETHRESHOLD
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        ldy #LN_A + MA_TARGET + 1       ; unless a live target is seen,
        lda (GC_MP),y                   ;   a new one
        cmp #$FF
        beq @p42
        sta GA_3
        dey
        lda (GC_MP),y
        sta GA_2
        ldx GA_3
        jsr mo_get
        ldy #LN_A + MA_HEALTH + 1
        lda (GC_MP),y
        bmi @p42
        dey
        ora (GC_MP),y
        beq @p42
        ARG01 CH_AP             ; P_CheckSight(actor, target)
        FCALL P_CheckSight
        cmp #0
        bne @chase
@p42:   ARG01 CH_AP
        lda #1
        FCALL lookForPlayers
        cmp #0
        bne @rts2

        ; chase towards the target
@chase: GETMO CH_AP             ; if (--movecount < 0 || !P_Move(actor))
        ldy #LN_C + MC_MOVEC
        lda (GC_MP),y
        sec
        sbc #1
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #0
        sta (GC_MP),y
        php
        lda #D_C
        jsr mo_dirty
        plp
        bmi @newdir
        ARG01 CH_AP
        FCALL pMove
        cmp #0
        bne @sound
@newdir:
        ARG01 CH_AP
        FCALL newChaseDir

        ; the active sound
@sound: lda CH_TY
        ldy #UO_MI_ACTIVESOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @rts2
        jsr g_random
        cmp #3
        bcs @rts2
        SOUND API_W, CH_AP
@rts2:  rts

; ch_state: P_SetMobjState(CH_AP, mobjinfo[A].<field Y>)
ch_state:
        jsr mi_get
        pha
        lda CH_AP
        sta GA_MO
        lda CH_AP+1
        sta GA_MO+1
        pla
        FCALL P_SetMobjState
        rts

; ch_flag: CH_AP's flags |= A (byte 0)
ch_flag:
        pha
        GETMO CH_AP
        pla
        ldy #LN_B + MB_FLAGS
        ora (GC_MP),y
        sta (GC_MP),y
        lda #D_B
        jmp mo_dirty

; ===========================================================================
; The attacks. Each takes its actor in GA_MO and keeps it in AK_AP.
; ===========================================================================

; AKSTART: AK_AP = GA_MO
.macro AKSTART
        lda GA_MO
        sta AK_AP
        lda GA_MO+1
        sta AK_AP+1
.endmacro

; FACE: faceTarget(AK_AP); no target: rts
.macro FACE
        ARG01 AK_AP
        FCALL faceTarget
        cmp #0
        bne :+
        rts
:
.endmacro

; HASTARGET: AK_AP's target none: rts (upstream's loadTarget, in place)
.macro HASTARGET
        GETMO AK_AP
        ldy #LN_A + MA_TARGET + 1
        lda (GC_MP),y
        cmp #$FF
        bne :+
        rts
:
.endmacro

; MELEE lbl: not in melee range of AK_AP's target: to lbl
.macro MELEE lbl
        ARG01 AK_AP
        FCALL checkMeleeRange
        cmp #0
        beq lbl
.endmacro

; ANGLE: AK_ANG = AK_AP's angle
.macro ANGLE
        GETMO AK_AP
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta AK_ANG
        iny
        lda (GC_MP),y
        sta AK_ANG+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta AK_ANG+2
        iny
        lda (GC_MP),y
        sta AK_ANG+3
.endmacro

; TIMES3: A = A * 3 (below 256)
.macro TIMES3
        sta GT_0
        asl a
        clc
        adc GT_0
.endmacro

        ROUTINE A_PosAttack
        AKSTART
        FACE
        ANGLE                   ; angle = actor->angle
        FCALL aimLine           ; slope = P_AimLineAttack(...)
        SOUND #UC_SFX_PISTOL, AK_AP
        ldx #3                  ; angle += (P_Random() - P_Random()) << 20
:       lda AK_ANG,x
        sta AK_BASE,x
        dex
        bpl :-
        FCALL spreadAngle
        lda #5                  ; damage = (P_Random() % 5 + 1) * 3
        FCALL p_enemy_randMod
        inc a
        TIMES3
        FCALL lineAttack
        rts

        ROUTINE A_SPosAttack
        AKSTART
        HASTARGET
        SOUND #UC_SFX_SHOTGN, AK_AP
        ARG01 AK_AP
        FCALL faceTarget
        ANGLE                   ; bangle = actor->angle
        ldx #3
:       lda AK_ANG,x
        sta AK_BASE,x
        dex
        bpl :-
        FCALL aimLine
        lda #3
        sta AK_I
@pellet:
        FCALL spreadAngle       ; angle = bangle + the spread
        lda #5                  ; damage = (P_Random() % 5 + 1) * 3
        FCALL p_enemy_randMod
        inc a
        TIMES3
        FCALL lineAttack
        dec AK_I
        bne @pellet
        rts

        ROUTINE A_TroopAttack
        AKSTART
        FACE
        MELEE @missile
        SOUND #UC_SFX_CLAW, AK_AP
        jsr g_random            ; damage = (P_Random() % 8 + 1) * 3
        and #7
        inc a
        TIMES3
        FCALL damageTarget
        rts
@missile:
        lda #UC_MT_TROOPSHOT
        FCALL spawnMissile
        rts

        ROUTINE A_SargAttack
        AKSTART
        FACE
        MELEE @rts
        lda #10                 ; damage = ((P_Random() % 10) + 1) * 4
        FCALL p_enemy_randMod
        inc a
        asl a
        asl a
        FCALL damageTarget
@rts:   rts

        ROUTINE A_CyberAttack
        AKSTART
        FACE
        SOUND #UC_SFX_RLAUNC, AK_AP
        lda #UC_MT_ROCKET
        FCALL spawnMissile
        rts

        ROUTINE A_BruisAttack
        AKSTART
        HASTARGET
        MELEE @missile
        SOUND #UC_SFX_CLAW, AK_AP
        jsr g_random            ; damage = (P_Random() % 8 + 1) * 10
        and #7
        inc a
        asl a
        sta GT_0
        asl a
        asl a
        clc
        adc GT_0
        FCALL damageTarget
        rts
@missile:
        lda #UC_MT_BRUISERSHOT
        FCALL spawnMissile
        rts

; ===========================================================================
; The attacks' helpers
; ===========================================================================

; MISSILERANGE into GA_6-9 (P_AimLineAttack's and P_LineAttack's distance)
.macro RANGE
        stz GA_6
        stz GA_7
        lda #<UC_MISSILERANGE_HI
        sta GA_8
        lda #>UC_MISSILERANGE_HI
        sta GA_9
.endmacro

; aimLine: AK_SLOPE = P_AimLineAttack(AK_AP, AK_ANG, MISSILERANGE)
        ROUTINE aimLine
        ARG01 AK_AP
        ldx #3
:       lda AK_ANG,x
        sta GA_2,x
        dex
        bpl :-
        RANGE
        FCALL P_AimLineAttack
        ldx #3
:       lda GA_0,x
        sta AK_SLOPE,x
        dex
        bpl :-
        rts

; lineAttack: P_LineAttack(AK_AP, AK_ANG, MISSILERANGE, AK_SLOPE, A)
        ROUTINE lineAttack
        sta GA_14
        stz GA_15
        ARG01 AK_AP
        ldx #3
:       lda AK_ANG,x
        sta GA_2,x
        lda AK_SLOPE,x
        sta GA_10,x
        dex
        bpl :-
        RANGE
        FCALL P_LineAttack
        rts

; spreadAngle: AK_ANG = AK_BASE + (t - P_Random()) << 20, t = P_Random()
; (the first call's value less the second's, 16 bits, << 4 on the high
; word)
        ROUTINE spreadAngle
        jsr g_random
        sta GT_0
        jsr g_random
        sta GT_1
        sec
        lda GT_0
        sbc GT_1
        sta GT_0
        lda #0
        sbc #0
        sta GT_1
        ldx #4
:       asl GT_0
        rol GT_1
        dex
        bne :-
        lda AK_BASE
        sta AK_ANG
        lda AK_BASE+1
        sta AK_ANG+1
        clc
        lda AK_BASE+2
        adc GT_0
        sta AK_ANG+2
        lda AK_BASE+3
        adc GT_1
        sta AK_ANG+3
        rts

; damageTarget: P_DamageMobj(AK_AP->target, AK_AP, AK_AP, A)
        ROUTINE damageTarget
        sta GA_6
        stz GA_7
        GETMO AK_AP
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta GA_0
        iny
        lda (GC_MP),y
        sta GA_1
        lda AK_AP
        sta GA_2
        sta GA_4
        lda AK_AP+1
        sta GA_3
        sta GA_5
        FCALL P_DamageMobj
        rts

; spawnMissile: P_SpawnMissile(AK_AP, AK_AP->target, A)
        ROUTINE spawnMissile
        sta GT_0
        GETMO AK_AP
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta GA_2
        iny
        lda (GC_MP),y
        sta GA_3
        ARG01 AK_AP
        lda GT_0
        FCALL P_SpawnMissile
        rts

; ===========================================================================
; A_Explode: P_RadiusAttack(GA_MO, its target, 128)
; ===========================================================================
        ROUTINE A_Explode
        lda GA_MO               ; (GA_0-1 is GA_MO: the spot)
        ldx GA_MO+1
        jsr mo_get
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta GA_2
        iny
        lda (GC_MP),y
        sta GA_3
        lda #128
        sta GA_4
        stz GA_5
        FCALL P_RadiusAttack
        rts

; ===========================================================================
; A_BossDeath: on map 8, when the last baron dies and the player lives, the
; floors of tag 666 down to the lowest floor next to each
; ===========================================================================
        ROUTINE A_BossDeath
        lda G_GAMEMAP + 1       ; gamemap == 8 (a word)
        bne @rts
        lda G_GAMEMAP
        cmp #8
        bne @rts
        lda GA_MO
        sta BD_AP
        ldx GA_MO+1
        stx BD_AP+1
        jsr mo_get              ; a baron
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        cmp #UC_MT_BRUISER
        bne @rts
        lda PLR + PL_HEALTH + 1 ; the player alive (health > 0)
        bmi @rts
        ora PLR + PL_HEALTH
        bne @walk
@rts:   rts
        ; any other baron alive in the thinkers? (upstream's order: the
        ; list from its first)
@walk:  lda G_THFIRST
        ldx G_THFIRST+1
@th:    sta BD_TH
        stx BD_TH+1
        cpx #$FF                ; the list's end: victory
        beq bd_floors
        cpx #>SPEC_HANDLE       ; a special: its next
        bcc @mobj
        jsr sp_get
        ldy #SP_THNEXT + 1
        lda (GC_XP),y
        tax
        dey
        lda (GC_XP),y
        bra @th
@mobj:  jsr pl_get              ; a mobj: its function, its next
        lda PL_N
        sta BD_NX
        lda PL_N+1
        sta BD_NX+1
        lda PL_K
        and #$FF ^ KIND_CLEAN   ; P_MobjThinker (CLEAN or not)
        cmp #FN_MOBJ
        bne @next
        lda BD_TH               ; not the boss itself
        cmp BD_AP
        bne @other
        lda BD_TH+1
        cmp BD_AP+1
        beq @next
@other: GETMO BD_TH
        ldy #LN_A + MA_TYPE     ; the same type, alive: no victory
        lda (GC_MP),y
        cmp #UC_MT_BRUISER
        bne @next
        ldy #LN_A + MA_HEALTH + 1
        lda (GC_MP),y
        bmi @next
        dey
        ora (GC_MP),y
        bne @rts
@next:  lda BD_NX
        ldx BD_NX+1
        bra @th

; bd_floors: EV_DoFloor(the junk line of tag 666, lowerFloorToLowest): for
; each sector of tag 666 (in their order) with no moving floor, a floor
; down to the lowest floor next to it. The stand-in of request 1,
; accepted at wave 6's integration (chase.md R1 (b): EV_DoFloor by a tag
; would change two verified parts): evfloor's newFloor, floorUp's down
; (direction -1, the sector, FLOORSPEED) and setDest, secfind's
; P_FindLowestFloorSurrounding, as EV_DoFloor does them
bd_floors:
        lda #$FF                ; secnum = -1
        sta BD_SEC
@sec:   inc BD_SEC              ; the next sector of tag 666
        lda LVCOUNT+1
        bne :+
        lda BD_SEC
        cmp LVCOUNT
        bcs @done
:       lda BD_SEC
        jsr sec_get
        ldy #SEC_SIZE + SG_TAG
        lda (GC_SP),y
        cmp #<BOSSTAG
        bne @sec
        iny
        lda (GC_SP),y
        cmp #>BOSSTAG
        bne @sec
        ldy #SEC_SIZE + SG_FLOORD + 1   ; a moving floor already: no
        lda (GC_SP),y
        cmp #$FF
        bne @sec
        lda BD_SEC              ; floor = newFloor(sec, lowerFloorToLowest)
        ldy #UC_LOWERFLOORTOLOWEST
        FCALL newFloor
        sta BD_FL
        stx BD_FL+1
        jsr sp_get              ; floorDown: direction -1, the sector,
        lda #$FF                ;   speed FLOORSPEED
        ldy #SPFL_DIRECTION
        sta (GC_XP),y
        lda BD_SEC
        ldy #SP_SECTOR
        sta (GC_XP),y
        lda #FLOORSPEED_HI
        ldy #SPFL_SPEED + 2
        sta (GC_XP),y
        jsr sp_dirty
        lda BD_SEC              ; the destination: the lowest floor
        FCALL P_FindLowestFloorSurrounding      ;   surrounding
        lda BD_FL
        ldx BD_FL+1
        jsr sp_get
        ldy #SPFL_DEST
        ldx #0
:       lda GA_0,x
        sta (GC_XP),y
        iny
        inx
        cpx #4
        bne :-
        jsr sp_dirty
        bra @sec
@done:  rts
bd_floors_end:
