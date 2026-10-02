; game/look/look.s: part look's monster senses (milestone 10, docs/GAME.md
; 2.4; docs/game-parts/look.md). A GPL-2 derivative of upstream's
; p_enemy65.s (A_Look, lookForPlayers, behindFast with its bfTab cases,
; angleToAT, distanceAT, loadTarget, checkMeleeRange, checkMissileRange,
; P_CheckMeleeRange, P_CheckMissileRange, A_FaceTarget, faceTarget,
; randMod, startSound, A_Scream, A_XScream, A_Pain, A_Fall,
; A_PlayerScream).
;
;   A_Look        GA_MO = the actor: threshold 0, pursuecount 0; the sound
;                 target of its sector, when shootable, becomes its target
;                 and is seen at once (or, with MF_AMBUSH, when
;                 P_CheckSight sees it); else lookForPlayers(actor, 0);
;                 when seen: the see sound (posit1/posit2: posit1 +
;                 P_Random() % 3; bgsit1: bgsit1 + (P_Random() & 1)) and
;                 P_SetMobjState(actor, seestate)
;   lookForPlayers GA_0-1 = the actor, A = allaround: 0 when the player is
;                 dead; without allaround, a player behind the actor (the
;                 angle to it less the actor's angle in (ANG90, ANG270),
;                 behindFast's answer when it can tell) and farther than
;                 MELEERANGE is not seen; then P_CheckSight(actor, the
;                 player's mobj): seen, its target the player's mobj,
;                 threshold 60, A = 1
;   behindFast    GA_0-1 = the actor, GA_2-3 = the target: for an actor
;                 angle that is a multiple of ANG45 (its low 29 bits 0), k
;                 = angle >> 29, from the whole units xi, yi of the target
;                 less the actor (the high words of the 32-bit
;                 differences), |xi|, |yi| < 4096, S = |xi| + |yi| >= 64,
;                 T = (S + 2) >> 4, d = (xi, yi) dot direction k (bfTab:
;                 xi, xi + yi, yi, yi - xi, -xi, -xi - yi, -yi, xi - yi): a
;                 diagonal (k odd) tells when |d| - 2 > T, an axis when
;                 2 (|d| - 1) > T (16-bit unsigned); then C set and A = 1
;                 behind (d < 0), 0 in front; else C clear (A = $FF)
;   angleToAT     M_R = R_PointToAngle2(LK_AP, LK_AT) (pta3 of the target
;                 less the actor)
;   distanceAT    M_R = P_AproxDistance(the target less the actor)
;   loadTarget    GA_0-1 = the actor: LK_AP = it, LK_AT = A:X = its
;                 target; C set when it has one
;   checkMeleeRange (P_CheckMeleeRange) GA_0-1 = the actor: A = 1 when it
;                 has a target nearer (signed 32 bits) than MELEERANGE - 20
;                 units + the target type's radius and P_CheckSight sees it
;   checkMissileRange (P_CheckMissileRange) GA_0-1 = the actor (with a
;                 target): 0 unseen; MF_JUSTHIT: cleared, 1; a reaction
;                 time: 0; else dist = the distance's whole units - 64
;                 (- 128 more with no melee state), at most 200 (signed),
;                 and A = 0 when P_Random() < dist (signed), else 1
;   faceTarget    GA_0-1 = the actor: A = 0 with no target; else the
;                 actor's MF_AMBUSH cleared, its angle the angle to the
;                 target, and for a shadow target its angle's high word +=
;                 (P_Random() - P_Random()) << 5 (the first call's value
;                 less the second's; upstream's << 21 of the angle), A = 1
;   A_FaceTarget  the action: faceTarget(GA_MO)
;   p_enemy_randMod  A = c: A = P_Random() % c (math.s's sdiv16, upstream's
;                 _Mod16)
;   p_enemy_startSound  A = a sound, GA_0-1 = the origin: S_StartSound
;   A_Scream      the death sound (podth1/podth2: podth1 + P_Random() % 3;
;                 bgdth1: bgdth1 + (P_Random() & 1)), when the type has one
;   A_XScream     sfx_slop; A_Pain the pain sound when there is one;
;   A_PlayerScream sfx_pldeth; A_Fall: MF_SOLID cleared
;
; The bfTab cases (bfD0 .. bfD7) have no code of their own: a computed
; branch on k inside behindFast (request 1: glayout.INLINED). Every
; product, divide and angle is milestone 6's math.s (pta3, aproxdist,
; sdiv16); the P_Random calls are upstream's, in its order.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/look/look.inc"

        .export A_Look, lookForPlayers, behindFast, angleToAT, distanceAT
        .export loadTarget, checkMeleeRange, checkMissileRange
        .export P_CheckMeleeRange, P_CheckMissileRange, faceTarget
        .export A_FaceTarget, p_enemy_randMod, p_enemy_startSound
        .export A_Scream, A_XScream, A_Pain, A_Fall, A_PlayerScream
        .import mo_get, mo_dirty, mi_get, ss_get, sec_get, g_random
        .import S_StartSound, pta3, aproxdist, sdiv16
        .import fc_call, fc_unbuilt

PLR     = G_PLAYER

; ===========================================================================
; A_Look
; ===========================================================================
        ROUTINE A_Look
        lda GA_MO
        sta LK_AP
        lda GA_MO+1
        sta LK_AP+1
        GETMO LK_AP             ; threshold = 0, pursuecount = 0
        lda #0
        ldy #LN_C + MC_THRESH
        sta (GC_MP),y
        ldy #LN_C + MC_PURSUE
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        ldy #LN_A + MA_SUBSEC + 1       ; targ = its sector's soundtarget
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        ldy #SEC_SIZE + SG_TARGET
        lda (GC_SP),y
        sta LK_AT
        iny
        lda (GC_SP),y
        sta LK_AT+1
        cmp #$FF                ; none
        beq @look
        GETMO LK_AT             ; targ->flags & MF_SHOOTABLE
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        beq @look
        GETMO LK_AP             ; actor->target = targ
        ldy #LN_A + MA_TARGET
        lda LK_AT
        sta (GC_MP),y
        iny
        lda LK_AT+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        ldy #LN_B + MB_FLAGS    ; MF_AMBUSH: seen only when visible
        lda (GC_MP),y
        and #<UC_MF_AMBUSH_LO
        beq @see
        jsr ap_at_args
        FCALL P_CheckSight
        cmp #0
        bne @see
@look:  lda LK_AP               ; not seen: lookForPlayers(actor, 0)
        sta GA_0
        lda LK_AP+1
        sta GA_1
        lda #0
        FCALL lookForPlayers
        cmp #0
        bne @see
        rts
@see:   GETMO LK_AP             ; the see sound
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        pha                     ; (the type, for the see state)
        ldy #UO_MI_SEESOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @state
        lda API_W               ; (every sound number is below $100: a
        ldx API_W+1             ;   word above it is no special case, and
        bne @snd                ;   the hook takes the low byte)
        cmp #UC_SFX_POSIT1
        beq @posit
        cmp #UC_SFX_POSIT2
        beq @posit
        cmp #UC_SFX_BGSIT1
        bne @snd
        jsr g_random            ; sfx_bgsit1 + P_Random() % 2
        and #1
        clc
        adc #UC_SFX_BGSIT1
        bra @snd
@posit: jsr g_random            ; sfx_posit1 + P_Random() % 3
        sta M_A
        stz M_A+1
        lda #3
        sta M_B
        stz M_B+1
        jsr sdiv16
        lda M_T
        clc
        adc #UC_SFX_POSIT1
@snd:   ldx LK_AP
        ldy LK_AP+1
        jsr S_StartSound
@state: pla                     ; P_SetMobjState(actor, seestate)
        ldy #UO_MI_SEESTATE
        jsr mi_get
        lda LK_AP
        sta GA_MO
        lda LK_AP+1
        sta GA_MO+1
        lda API_W
        ldx API_W+1
        FCALL P_SetMobjState
        rts

; ap_at_args: GA_0-1 = LK_AP, GA_2-3 = LK_AT (P_CheckSight's t1, t2)
ap_at_args:
        lda LK_AP
        sta GA_0
        lda LK_AP+1
        sta GA_1
        lda LK_AT
        sta GA_2
        lda LK_AT+1
        sta GA_3
        rts

; ===========================================================================
; lookForPlayers
; ===========================================================================
        ROUTINE lookForPlayers
        pha                     ; allaround
        lda GA_0
        sta LK_AP
        lda GA_1
        sta LK_AP+1
        lda PLR + PL_HEALTH + 1 ; the player dead (health <= 0): not seen
        jmi @dead
        ora PLR + PL_HEALTH
        jeq @dead
        pla
        jne @sight              ; allaround: the sight check only
        lda PLR + PL_MO         ; behindFast(actor, player->mo)
        sta LK_AT
        sta GA_2
        lda PLR + PL_MO + 1
        sta LK_AT+1
        sta GA_3
        lda LK_AP
        sta GA_0
        lda LK_AP+1
        sta GA_1
        FCALL behindFast
        bcc @angle
        cmp #0
        beq @sight              ; in front
        bra @dist               ; behind
@angle: FCALL angleToAT         ; an = the angle to it - actor->angle
        GETMO LK_AP
        sec
        ldy #TH_ANGLO
        lda M_R
        sbc (GC_MP),y
        sta GT_0
        iny
        lda M_R+1
        sbc (GC_MP),y
        sta GT_1
        ldy #TH_ANG
        lda M_R+2
        sbc (GC_MP),y
        sta GT_2
        iny
        lda M_R+3
        sbc (GC_MP),y
        sta GT_3
        ; ANG90 < an && an < ANG270 (unsigned): an - (ANG90 + 1) >= 0 and
        ; its high word below $C000
        lda GT_0
        cmp #1
        lda GT_1
        sbc #0
        lda GT_2
        sbc #0
        lda GT_3
        sbc #>UC_ANG90_HI
        bcc @sight
        lda GT_3
        cmp #$C0
        bcs @sight
@dist:  FCALL distanceAT        ; P_AproxDistance > MELEERANGE: not seen
        lda M_R                 ; dist - (MELEERANGE + 1) < 0 (signed)
        cmp #1
        lda M_R+1
        sbc #0
        lda M_R+2
        sbc #<UC_MELEERANGE_HI
        lda M_R+3
        sbc #>UC_MELEERANGE_HI
        bvc :+
        eor #$80
:       bmi @sight
        lda #0
        rts
@sight: lda LK_AP               ; P_CheckSight(actor, player->mo)
        sta GA_0
        lda LK_AP+1
        sta GA_1
        lda PLR + PL_MO
        sta GA_2
        lda PLR + PL_MO + 1
        sta GA_3
        FCALL P_CheckSight
        cmp #0
        bne @seen
        rts
@seen:  GETMO LK_AP             ; actor->target = player->mo, threshold 60
        ldy #LN_A + MA_TARGET
        lda PLR + PL_MO
        sta (GC_MP),y
        iny
        lda PLR + PL_MO + 1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        lda #60
        ldy #LN_C + MC_THRESH
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        lda #1
        rts
@dead:  pla
        lda #0
        rts


; ===========================================================================
; behindFast: xi, yi in M_A+2, M_B+2 (the DELTA's high words), GT_0-1 |xi|
; then d, GT_2-3 |yi|, GT_4-5 S then T, GT_6 2k, LK_T |d| then v
; ===========================================================================
        ROUTINE behindFast
        lda GA_0
        ldx GA_1
        jsr mo_get              ; k = angle >> 29, the low 29 bits 0
        ldy #TH_ANG
        lda (GC_MP),y
        jne @no
        iny
        lda (GC_MP),y
        and #$1F
        jne @no
        lda (GC_MP),y           ; 2k
        lsr a
        lsr a
        lsr a
        lsr a
        and #$0E
        sta GT_6
        ldy #TH_ANGLO
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        jne @no
        DELTA GA_2, GA_0        ; the target less the actor
        ABS16 M_B+2, GT_2       ; |yi| < 4096
        lda GT_3
        cmp #>4096
        bcs @no
        ABS16 M_A+2, GT_0       ; |xi| < 4096
        lda GT_1
        cmp #>4096
        bcs @no
        clc                     ; S = |xi| + |yi| >= 64
        lda GT_0
        adc GT_2
        sta GT_4
        lda GT_1
        adc GT_3
        sta GT_5
        bne @big
        lda GT_4
        cmp #64
        bcc @no
@big:   clc                     ; T = (S + 2) >> 4
        lda GT_4
        adc #2
        sta GT_4
        bcc :+
        inc GT_5
:       ldx #4
:       lsr GT_5
        ror GT_4
        dex
        bne :-
        ldx GT_6                ; d by k (upstream's bfTab)
        jmp (bf_tab,x)
@no:    lda #$FF                ; it cannot tell
        clc
        rts

bf_tab: .word bf_d0, bf_d1, bf_d2, bf_d3, bf_d4, bf_d5, bf_d6, bf_d7

bf_d0:  lda M_A+2               ; d = xi
        sta GT_0
        lda M_A+3
        sta GT_1
        jmp bf_even
bf_d2:  lda M_B+2               ; d = yi
        sta GT_0
        lda M_B+3
        sta GT_1
        jmp bf_even
bf_d4:  sec                     ; d = -xi
        lda #0
        sbc M_A+2
        sta GT_0
        lda #0
        sbc M_A+3
        sta GT_1
        jmp bf_even
bf_d6:  sec                     ; d = -yi
        lda #0
        sbc M_B+2
        sta GT_0
        lda #0
        sbc M_B+3
        sta GT_1
        bra bf_even
bf_d1:  clc                     ; d = xi + yi
        lda M_A+2
        adc M_B+2
        sta GT_0
        lda M_A+3
        adc M_B+3
        sta GT_1
        bra bf_odd
bf_d3:  sec                     ; d = yi - xi
        lda M_B+2
        sbc M_A+2
        sta GT_0
        lda M_B+3
        sbc M_A+3
        sta GT_1
        bra bf_odd
bf_d5:  sec                     ; d = -xi - yi
        lda #0
        sbc M_A+2
        sta GT_0
        lda #0
        sbc M_A+3
        sta GT_1
        sec
        lda GT_0
        sbc M_B+2
        sta GT_0
        lda GT_1
        sbc M_B+3
        sta GT_1
        bra bf_odd
bf_d7:  sec                     ; d = xi - yi
        lda M_A+2
        sbc M_B+2
        sta GT_0
        lda M_A+3
        sbc M_B+3
        sta GT_1
        ; (on into bf_odd)
bf_odd: ABS16 GT_0, LK_T        ; a diagonal: v = |d| - 2 > T
        sec
        lda LK_T
        sbc #2
        sta LK_T
        lda LK_T+1
        sbc #0
        sta LK_T+1
        bcc bf_no
        bra bf_cmp
bf_even:
        ABS16 GT_0, LK_T        ; an axis: v = 2 (|d| - 1) > T
        sec
        lda LK_T
        sbc #1
        sta LK_T
        lda LK_T+1
        sbc #0
        sta LK_T+1
        bcc bf_no
        asl LK_T
        rol LK_T+1
bf_cmp: lda LK_T+1              ; v <= T (unsigned): it cannot tell
        cmp GT_5
        bcc bf_no
        bne bf_yes
        lda LK_T
        cmp GT_4
        beq bf_no
        bcc bf_no
bf_yes: lda GT_1                ; behind: d < 0
        asl a
        lda #0
        rol a
        sec
        rts
bf_no:  lda #$FF
        clc
        rts

; ===========================================================================
; angleToAT, distanceAT: the target LK_AT less the actor LK_AP into M_A,
; M_B; M_R = pta3 (R_PointToAngle3), aproxdist (P_AproxDistance)
; ===========================================================================
        ROUTINE angleToAT
        DELTA LK_AT, LK_AP
        jmp pta3

        ROUTINE distanceAT
        DELTA LK_AT, LK_AP
        jmp aproxdist           ; (math-g.o, the core: request 2)

; ===========================================================================
; loadTarget: LK_AP = GA_0-1, LK_AT = A:X = its target; C set when one
; ===========================================================================
        ROUTINE loadTarget
        lda GA_0
        sta LK_AP
        ldx GA_1
        stx LK_AP+1
        jsr mo_get
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta LK_AT
        iny
        lda (GC_MP),y
        sta LK_AT+1
        eor #$FF                ; C set: a mobj (a handle below $FF00);
        cmp #1                  ;   clear: none ($FFFF)
        lda LK_AT
        ldx LK_AT+1
        rts

; ===========================================================================
; checkMeleeRange, P_CheckMeleeRange
; ===========================================================================
        ROUTINE P_CheckMeleeRange
        FCALL checkMeleeRange
        rts

        ROUTINE checkMeleeRange
        FCALL loadTarget
        bcs @have
        lda #0
        rts
@have:  FCALL distanceAT
        ldx #3
:       lda M_R,x
        sta LK_T,x
        dex
        bpl :-
        GETMO LK_AT             ; the limit: mobjinfo[pl->type].radius +
        ldy #LN_A + MA_TYPE     ;   (MELEERANGE - 20) << 16
        lda (GC_MP),y
        pha
        ldy #UO_MI_RADIUS
        jsr mi_get
        sta LK_D
        stx LK_D+1
        pla
        ldy #UO_MI_RADIUS + 2
        jsr mi_get
        clc
        adc #<(UC_MELEERANGE_HI - 20)
        sta LK_D+2
        txa
        adc #>(UC_MELEERANGE_HI - 20)
        sta LK_D+3
        lda LK_T                ; dist < limit (signed 32 bits)
        cmp LK_D
        lda LK_T+1
        sbc LK_D+1
        lda LK_T+2
        sbc LK_D+2
        lda LK_T+3
        sbc LK_D+3
        bvc :+
        eor #$80
:       bmi @sight
        lda #0
        rts
@sight: jsr ap_at_args2         ; P_CheckSight(actor, pl)
        FCALL P_CheckSight
        rts

; ap_at_args2: GA_0-1 = LK_AP, GA_2-3 = LK_AT
ap_at_args2:
        lda LK_AP
        sta GA_0
        lda LK_AP+1
        sta GA_1
        lda LK_AT
        sta GA_2
        lda LK_AT+1
        sta GA_3
        rts

; ===========================================================================
; checkMissileRange, P_CheckMissileRange
; ===========================================================================
        ROUTINE P_CheckMissileRange
        FCALL checkMissileRange
        rts

        ROUTINE checkMissileRange
        FCALL loadTarget        ; P_CheckSight(actor, actor->target)
        jsr ap_at_args3
        FCALL P_CheckSight
        cmp #0
        bne @seen
        rts
@seen:  GETMO LK_AP             ; just hit: fight back
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        bit #<UC_MF_JUSTHIT_LO
        beq @react
        and #<~UC_MF_JUSTHIT_LO
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
        lda #1
        rts
@react: ldy #LN_C + MC_REACT    ; do not attack yet
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        beq @dist
        lda #0
        rts
@dist:  FCALL distanceAT        ; dist = the whole units - 64
        sec
        lda M_R+2
        sbc #64
        sta LK_T
        lda M_R+3
        sbc #0
        sta LK_T+1
        GETMO LK_AP             ; no melee state: - 128
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        ldy #UO_MI_MELEESTATE
        jsr mi_get
        stx GT_0
        ora GT_0
        bne @clamp
        sec
        lda LK_T
        sbc #128
        sta LK_T
        lda LK_T+1
        sbc #0
        sta LK_T+1
@clamp: lda LK_T                ; dist > 200 (signed): 200
        cmp #201
        lda LK_T+1
        sbc #0
        bvc :+
        eor #$80
:       bmi @rand
        lda #200
        sta LK_T
        stz LK_T+1
@rand:  jsr g_random            ; P_Random() < dist (signed): false
        sec
        sbc LK_T
        lda #0
        sbc LK_T+1
        bvc :+
        eor #$80
:       bmi @no
        lda #1
        rts
@no:    lda #0
        rts

; ap_at_args3: GA_0-1 = LK_AP, GA_2-3 = LK_AT
ap_at_args3:
        lda LK_AP
        sta GA_0
        lda LK_AP+1
        sta GA_1
        lda LK_AT
        sta GA_2
        lda LK_AT+1
        sta GA_3
        rts

; ===========================================================================
; A_FaceTarget, faceTarget
; ===========================================================================
        ROUTINE A_FaceTarget
        FCALL faceTarget        ; (GA_MO is GA_0)
        rts

        ROUTINE faceTarget
        FCALL loadTarget
        bcs @have
        lda #0
        rts
@have:  GETMO LK_AP             ; flags &= ~MF_AMBUSH
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<~UC_MF_AMBUSH_LO
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
        FCALL angleToAT         ; angle = R_PointToAngle2(actor, target)
        GETMO LK_AP
        ldy #TH_ANGLO
        lda M_R
        sta (GC_MP),y
        iny
        lda M_R+1
        sta (GC_MP),y
        ldy #TH_ANG
        lda M_R+2
        sta (GC_MP),y
        iny
        lda M_R+3
        sta (GC_MP),y
        lda #D_RTH
        jsr mo_dirty
        GETMO LK_AT             ; a shadow target: angle +=
        ldy #LN_B + MB_FLAGS + 2        ;   (t - P_Random()) << 21
        lda (GC_MP),y
        and #<UC_MF_SHADOW_HI
        beq @done
        jsr g_random            ; t = the first P_Random()
        sta GT_0
        jsr g_random            ; v = t - the second (16 bits)
        sta GT_1
        sec
        lda GT_0
        sbc GT_1
        sta GT_0
        lda #0
        sbc #0
        sta GT_1
        ldx #5                  ; v << 5
:       asl GT_0
        rol GT_1
        dex
        bne :-
        GETMO LK_AP             ; the angle's high word += v
        ldy #TH_ANG
        clc
        lda (GC_MP),y
        adc GT_0
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc GT_1
        sta (GC_MP),y
        lda #D_RTH
        jsr mo_dirty
@done:  lda #1
        rts

; ===========================================================================
; p_enemy_randMod: A = P_Random() % A; p_enemy_startSound: S_StartSound(
; GA_0-1, A)
; ===========================================================================
        ROUTINE p_enemy_randMod
        sta M_B
        stz M_B+1
        jsr g_random
        sta M_A
        stz M_A+1
        jsr sdiv16
        lda M_T
        rts

        ROUTINE p_enemy_startSound
        ldx GA_0
        ldy GA_1
        jmp S_StartSound

; ===========================================================================
; A_Scream, A_XScream, A_Pain, A_PlayerScream, A_Fall
; ===========================================================================
        ROUTINE A_Scream
        lda GA_MO
        ldx GA_MO+1
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        ldy #UO_MI_DEATHSOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @done
        lda API_W
        cpx #0                  ; (every sound number is below $100)
        bne @snd
        cmp #UC_SFX_PODTH1
        beq @podth
        cmp #UC_SFX_PODTH2
        beq @podth
        cmp #UC_SFX_BGDTH1
        bne @snd
        jsr g_random            ; sfx_bgdth1 + P_Random() % 2
        and #1
        clc
        adc #UC_SFX_BGDTH1
        bra @snd
@podth: lda #3                  ; sfx_podth1 + P_Random() % 3
        FCALL p_enemy_randMod
        clc
        adc #UC_SFX_PODTH1
@snd:   FCALL p_enemy_startSound        ; (GA_0-1 is GA_MO)
@done:  rts

        ROUTINE A_XScream
        lda #UC_SFX_SLOP
        FCALL p_enemy_startSound
        rts

        ROUTINE A_Pain
        lda GA_MO
        ldx GA_MO+1
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        ldy #UO_MI_PAINSOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @done
        lda API_W
        FCALL p_enemy_startSound
@done:  rts

        ROUTINE A_PlayerScream
        lda #UC_SFX_PLDETH
        FCALL p_enemy_startSound
        rts

        ROUTINE A_Fall
        lda GA_MO               ; flags &= ~MF_SOLID
        ldx GA_MO+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<~UC_MF_SOLID_LO
        sta (GC_MP),y
        lda #D_B
        jmp mo_dirty
