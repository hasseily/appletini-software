; game/damage/dinter.s: part damage's damage and deaths (milestone 10,
; docs/GAME.md 2.4; docs/game-parts/damage.md). A GPL-2 derivative of
; upstream's p_inter65.s (P_DamageMobj, killMobj and their helpers).
;
;   P_DamageMobj  GA_0-1 the target, GA_2-3 the inflictor, GA_4-5 the
;                 source ($FFFF none for both), GA_6-7 the damage: nothing
;                 for a target that is not shootable or not alive; the
;                 player's damage halved in baby; the thrust; the player's
;                 part (playerDamage: god mode, the armour, ...); the
;                 health; a death (killMobj); else the player's attacker
;                 as its target, the pain state when P_Random() is below
;                 the pain chance (a byte compare, upstream's), the
;                 reaction time 0, a new target (the source, with
;                 BASETHRESHOLD and the see state from the spawn state)
;                 when the source is another mobj and the threshold is
;                 0, MF_JUSTHIT after a pain state
;   killMobj      the death of DM_TGT (P_KillMobj(DM_SRC, DM_TGT)): a
;                 corpse (not shootable, gravity, may drop off, a quarter
;                 of its height), counted when MF_COUNTKILL, the player
;                 dead (not solid, PST_DEAD, P_DropWeapon, AM_Stop), the
;                 extreme death state when its health is below
;                 -spawnhealth and it has one, else the death state, its
;                 tics less P_Random() & 3 (at least 1), and the item a
;                 zombieman or a shotgun guy drops (with the cheat
;                 CF_ENEMY_ROCKETS a rocket launcher from types
;                 MT_POSSESSED to MT_BRUISERSHOT), MF_DROPPED
;   thrust        with an inflictor, not MF_NOCLIP, and not the player's
;                 chainsaw: the angle from the inflictor to the target
;                 (R_PointToAngle3), thrust = damage * 819200 / mass (the
;                 product's 32 bits as upstream builds them, then math.s's
;                 32-bit divide), turned over for a hard hit from below
;                 (health < damage < 40, 64 units, P_Random() & 1): the
;                 angle + ANG180, the thrust x 4; the momentum
;                 += FixedMulAngle(thrust, the cosine, the sine) (addThrust
;                 in place); the mobj's CLEAN bit off
;   playerDamage  the exit sector (special 11) keeps the player at 1
;                 health; god mode, and invulnerability below 1000, take
;                 no damage (carry clear); the armour (green a third, blue
;                 a half, math.s's 16-bit divide) until it is used up; the
;                 player's health (at least 0), attacker and damage count
;                 (at most 100); carry set
;   setState      P_SetMobjState(DM_TGT, A:X) with DM_TGT, DM_SRC and
;                 DM_TYPE kept on the stack across it
;   lastEnemy     the old target becomes the last enemy unless the last
;                 enemy lives and the old target is the source
;
; targetArg, setTarget and addThrust have no code of their own: their work
; is done in place (request R3). The routines' order of P_Random calls is
; upstream's: the thrust's (turned over), then the pain chance's, or the
; death tics'.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/damage/damage.inc"

        .export P_DamageMobj, killMobj, thrust, playerDamage, setState
        .export lastEnemy
        .import mo_get, mo_dirty, pl_get, pl_put, mi_get, ss_get, sec_get
        .import g_random, AM_Stop, fc_call, fc_unbuilt
        .import sdiv32, sdiv16, fixmulang, udiv32, pta3, finesine, finecosine
        .import P_SetMobjState, P_SpawnMobj, P_DropWeapon

PLR     = G_PLAYER

; ===========================================================================
; P_DamageMobj
; ===========================================================================
        ROUTINE P_DamageMobj
        ldx #7                  ; the target, inflictor, source, damage
:       lda GA_0,x
        sta DM_TGT,x
        dex
        bpl :-
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS    ; not shootable: no
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        beq @no
        ldy #LN_A + MA_HEALTH + 1       ; dead (health <= 0): no
        lda (GC_MP),y
        bmi @no
        dey
        ora (GC_MP),y
        bne @live
@no:    rts
@live:  ldy #LN_A + MA_TYPE     ; DM_INFO: the type
        lda (GC_MP),y
        sta DM_TYPE
        stz DM_PLY              ; the player: half damage in baby
        lda PLR + PL_MO
        cmp DM_TGT
        bne @thr
        lda PLR + PL_MO + 1
        cmp DM_TGT+1
        bne @thr
        inc DM_PLY
        lda G_GAMESKILL
        ora G_GAMESKILL+1
        bne @thr
        lda DM_DMG+1            ; damage >> 1, arithmetic
        cmp #$80
        ror DM_DMG+1
        ror DM_DMG
@thr:   FCALL thrust
        lda DM_PLY
        beq @hurt
        FCALL playerDamage
        bcs @hurt
        rts                     ; god mode, invulnerable
@hurt:  lda DM_TGT              ; the damage
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_HEALTH
        sec
        lda (GC_MP),y
        sbc DM_DMG
        sta (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sbc DM_DMG+1
        sta (GC_MP),y
        sta GT_1
        lda #D_A
        jsr mo_dirty
        lda GT_1                ; 0 or below: the death
        bmi @kill
        ora GT_0
        bne @alive
@kill:  FCALL killMobj
        rts
@alive: lda DM_PLY              ; the player: its target = the source
        beq @pain
        jsr set_target
@pain:  jsr g_random            ; the pain chance (its low byte, unsigned:
        sta GT_0                ;   upstream's byte compare)
        lda DM_TYPE
        ldy #UO_MI_PAINCHANCE
        jsr mi_get
        sta GT_1
        lda GT_0
        cmp GT_1
        lda #0
        bcs @jh
        lda DM_TYPE             ; justhit, the pain state
        ldy #UO_MI_PAINSTATE
        jsr mi_get
        FCALL setState
        lda #1
@jh:    pha                     ; justhit, on the stack
        lda DM_TGT              ; reactiontime = 0: awake
        ldx DM_TGT+1
        jsr mo_get
        lda #0
        ldy #LN_C + MC_REACT
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        lda DM_SRC+1            ; a source, not the target itself, and no
        cmp #$FF                ;   threshold: a new target
        beq @flag
        lda DM_SRC
        cmp DM_TGT
        bne :+
        lda DM_SRC+1
        cmp DM_TGT+1
        beq @flag
:       lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_C + MC_THRESH
        lda (GC_MP),y
        bne @flag
        FCALL lastEnemy
        jsr set_target          ; target = source, the threshold
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        lda #UC_BASETHRESHOLD
        ldy #LN_C + MC_THRESH
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        ldy #LN_A + MA_STATE    ; in the spawn state with a see state:
        lda (GC_MP),y           ;   the see state
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        lda DM_TYPE
        ldy #UO_MI_SPAWNSTATE
        jsr mi_get
        cmp GT_0
        bne @flag
        cpx GT_1
        bne @flag
        lda DM_TYPE
        ldy #UO_MI_SEESTATE
        jsr mi_get
        stx GT_1
        ora GT_1
        beq @flag
        lda API_W
        FCALL setState
@flag:  pla                     ; justhit: MF_JUSTHIT
        beq @done
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        ora #<UC_MF_JUSTHIT_LO
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
@done:  rts

; set_target: (setTarget) the target's target = DM_SRC
set_target:
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_TARGET
        lda DM_SRC
        sta (GC_MP),y
        iny
        lda DM_SRC+1
        sta (GC_MP),y
        lda #D_A
        jmp mo_dirty

; ===========================================================================
; setState: P_SetMobjState(DM_TGT, A:X)
; ===========================================================================
        ROUTINE setState
        sta GT_0
        stx GT_1
        lda DM_TGT              ; the mobj (MS_OBJ: GA_MO)
        sta GA_MO
        lda DM_TGT+1
        sta GA_MO+1
        ldx #0                  ; DM_TGT, DM_SRC, DM_TYPE on the stack
:       lda DM_TGT,x
        pha
        inx
        cpx #2
        bne :-
        lda DM_SRC
        pha
        lda DM_SRC+1
        pha
        lda DM_TYPE
        pha
        lda GT_0
        ldx GT_1
        FCALL P_SetMobjState
        pla
        sta DM_TYPE
        pla
        sta DM_SRC+1
        pla
        sta DM_SRC
        pla
        sta DM_TGT+1
        pla
        sta DM_TGT
        rts

; ===========================================================================
; lastEnemy: lastenemy = target unless lastenemy lives and target is the
; source
; ===========================================================================
        ROUTINE lastEnemy
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_C + MC_LASTEN
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        ldy #LN_A + MA_TARGET
        lda (GC_MP),y
        sta GT_2
        iny
        lda (GC_MP),y
        sta GT_3
        lda GT_1                ; no last enemy
        cmp #$FF
        beq @set
        lda GT_0                ; a dead one (health <= 0)
        ldx GT_1
        jsr mo_get
        ldy #LN_A + MA_HEALTH + 1
        lda (GC_MP),y
        bmi @set
        dey
        ora (GC_MP),y
        beq @set
        lda GT_2                ; target->target != source
        cmp DM_SRC
        bne @set
        lda GT_3
        cmp DM_SRC+1
        beq @done
@set:   lda DM_TGT              ; lastenemy = target->target
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_C + MC_LASTEN
        lda GT_2
        sta (GC_MP),y
        iny
        lda GT_3
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
@done:  rts

; ===========================================================================
; thrust
; ===========================================================================
        ROUTINE thrust
        lda DM_INF+1            ; an inflictor
        cmp #$FF
        bne :+
        rts
:       lda DM_TGT              ; not MF_NOCLIP
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 1
        lda (GC_MP),y
        and #>UC_MF_NOCLIP_LO
        beq :+
        rts
:       lda DM_SRC              ; the source is the player with the
        cmp PLR + PL_MO         ;   chainsaw: no push
        bne @go
        lda DM_SRC+1
        cmp PLR + PL_MO + 1
        bne @go
        lda PLR + PL_READYWEAPON
        cmp #UC_WP_CHAINSAW
        bne @go
        lda PLR + PL_READYWEAPON + 1
        bne @go
        rts
@go:    lda DM_TYPE             ; the mass: its low word, sign-extended
        ldy #UO_MI_MASS
        jsr mi_get
        sta DM_T
        stx DM_T+1
        lda DM_INF              ; the angle from the inflictor to the
        ldx DM_INF+1            ;   target: R_PointToAngle3(dx, dy)
        jsr mo_get
        ldy #7                  ; (TH_X, TH_Y: M_A, M_B)
:       lda (GC_MP),y
        sta M_A,y
        dey
        bpl :-
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #TH_X
        jsr dsub4               ; M_A = x - M_A
        jsr dsub4               ; M_B = y - M_B
        jsr pta3
        ldx #3
:       lda M_R,x
        sta DM_ANG,x
        dex
        bpl :-
        ; thrust = damage * 819200 / mass, 32 bits: (12 * damage +
        ; (damage >> 1)) << 16 + (damage & 1) << 15, arithmetic shift
        lda DM_T                ; the divisor
        sta M_B
        lda DM_T+1
        sta M_B+1
        and #$80
        beq :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        lda DM_DMG              ; 12 * damage (16 bits) in M_A+2
        asl a
        sta M_A+2
        lda DM_DMG+1
        rol a
        sta M_A+3
        clc
        lda M_A+2
        adc DM_DMG
        sta M_A+2
        lda M_A+3
        adc DM_DMG+1
        sta M_A+3
        asl M_A+2
        rol M_A+3
        asl M_A+2
        rol M_A+3
        lda DM_DMG+1            ; damage >> 1 (GT_0-1), its bit 0 in C
        cmp #$80
        ror a
        sta GT_1
        lda DM_DMG
        ror a
        sta GT_0
        lda #0                  ; (damage & 1) << 15
        ror a
        sta M_A+1
        stz M_A
        clc
        lda M_A+2
        adc GT_0
        sta M_A+2
        lda M_A+3
        adc GT_1
        sta M_A+3
        jsr sdiv32
        ldx #3
:       lda M_R,x
        sta DM_THR,x
        dex
        bpl :-
        ; turned over: health < damage && damage < 40 && z - inflictor's z
        ; > 64 * FRACUNIT && P_Random() & 1
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_HEALTH
        sec
        lda (GC_MP),y
        sbc DM_DMG
        iny
        lda (GC_MP),y
        sbc DM_DMG+1
        bvc :+
        eor #$80
:       bpl @push
        sec
        lda DM_DMG
        sbc #40
        lda DM_DMG+1
        sbc #0
        bvc :+
        eor #$80
:       bpl @push
        ldy #TH_Z + 3           ; dz = z - the inflictor's z
        ldx #3
:       lda (GC_MP),y
        sta DM_T,x
        dey
        dex
        bpl :-
        lda DM_INF
        ldx DM_INF+1
        jsr mo_get
        ldy #TH_Z
        sec
        ldx #4
:       lda DM_T - TH_Z,y
        sbc (GC_MP),y
        sta DM_T - TH_Z,y
        iny
        dex
        bne :-
        sec                     ; 64 * FRACUNIT < dz (signed)
        lda #0
        sbc DM_T
        lda #0
        sbc DM_T+1
        lda #64
        sbc DM_T+2
        lda #0
        sbc DM_T+3
        bvc :+
        eor #$80
:       bpl @push
        jsr g_random
        and #1
        beq @push
        lda DM_ANG+3            ; ang += ANG180, thrust *= 4
        eor #$80
        sta DM_ANG+3
        ldx #2
:       asl DM_THR
        rol DM_THR+1
        rol DM_THR+2
        rol DM_THR+3
        dex
        bne :-
@push:  lda DM_ANG+2            ; the fine angle: ang >> 19
        sta DM_FA
        lda DM_ANG+3
        ldx #3
:       lsr a
        ror DM_FA
        dex
        bne :-
        sta DM_FA+1
        jsr fa_arg              ; momx += FixedMulAngle(thrust,
        jsr finecosine       ;   finecosine(ang))
        ldy #LN_C + MC_MOMX
        jsr add_thrust
        jsr fa_arg              ; momy += FixedMulAngle(thrust,
        jsr finesine         ;   finesine(ang))
        ldy #LN_C + MC_MOMY
        jsr add_thrust
        lda DM_TGT              ; (upstream's CLEARCLEAN: a momentum
        ldx DM_TGT+1            ;   change)
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda DM_TGT
        ldx DM_TGT+1
        jmp pl_put

; dsub4: M_A + (Y - TH_X) = the line's 4 bytes at Y - them; Y += 4
dsub4:  sec
        ldx #4
:       lda (GC_MP),y
        sbc M_A - TH_X,y
        sta M_A - TH_X,y
        iny
        dex
        bne :-
        rts

; fa_arg: M_A = DM_FA
fa_arg: lda DM_FA
        sta M_A
        lda DM_FA+1
        sta M_A+1
        rts

; add_thrust: (addThrust) the target's fixed_t at line offset Y +=
; FixedMulAngle(DM_THR, M_R); its group C dirty
add_thrust:
        phy
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda DM_THR,x
        sta M_A,x
        dex
        bpl :-
        jsr fixmulang
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ply
        clc
        lda (GC_MP),y
        adc M_R
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc M_R+1
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc M_R+2
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc M_R+3
        sta (GC_MP),y
        lda #D_C
        jmp mo_dirty

; ===========================================================================
; playerDamage
; ===========================================================================
        ROUTINE playerDamage
        lda DM_TGT              ; the exit sector (special 11): at least 1
        ldx DM_TGT+1            ;   health
        jsr mo_get
        ldy #LN_A + MA_SUBSEC + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        ldy #SEC_SIZE + SG_SPECIAL
        lda (GC_SP),y
        cmp #11
        bne @god
        lda DM_TGT              ; damage >= health: health - 1
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_HEALTH
        sec
        lda DM_DMG
        sbc (GC_MP),y
        iny
        lda DM_DMG+1
        sbc (GC_MP),y
        bvc :+
        eor #$80
:       bmi @god
        dey
        lda (GC_MP),y
        sec
        sbc #1
        sta DM_DMG
        iny
        lda (GC_MP),y
        sbc #0
        sta DM_DMG+1
@god:   lda PLR + PL_CHEATS     ; (damage < 1000 || god) && (god ||
        and #UC_CF_GODMODE      ;   invulnerable): no damage
        bne @none
        sec
        lda DM_DMG
        sbc #<1000
        lda DM_DMG+1
        sbc #>1000
        bvc :+
        eor #$80
:       bpl @armor
        lda PLR + PL_POWERS_0   ; (pw_invulnerability)
        ora PLR + PL_POWERS_0 + 1
        beq @armor
@none:  clc
        rts
@armor: lda PLR + PL_ARMORTYPE  ; the armour
        ora PLR + PL_ARMORTYPE + 1
        beq @health
        ldx #2                  ; saved = damage / 3 (green) or / 2
        lda PLR + PL_ARMORTYPE + 1
        bne :+
        lda PLR + PL_ARMORTYPE
        cmp #1
        bne :+
        ldx #3
:       stx M_B
        stz M_B+1
        lda DM_DMG
        sta M_A
        lda DM_DMG+1
        sta M_A+1
        jsr sdiv16
        sec                     ; armorpoints <= saved (saved - armorpoints
        lda M_R                 ;   zero or not negative): used up
        sbc PLR + PL_ARMORPOINTS
        lda M_R+1
        sbc PLR + PL_ARMORPOINTS + 1
        bmi @saved
        lda PLR + PL_ARMORPOINTS
        sta M_R
        lda PLR + PL_ARMORPOINTS + 1
        sta M_R+1
        stz PLR + PL_ARMORTYPE
        stz PLR + PL_ARMORTYPE + 1
@saved: sec                     ; armorpoints -= saved, damage -= saved
        lda PLR + PL_ARMORPOINTS
        sbc M_R
        sta PLR + PL_ARMORPOINTS
        lda PLR + PL_ARMORPOINTS + 1
        sbc M_R+1
        sta PLR + PL_ARMORPOINTS + 1
        sec
        lda DM_DMG
        sbc M_R
        sta DM_DMG
        lda DM_DMG+1
        sbc M_R+1
        sta DM_DMG+1
@health:
        sec                     ; health -= damage, at least 0
        lda PLR + PL_HEALTH
        sbc DM_DMG
        tax
        lda PLR + PL_HEALTH + 1
        sbc DM_DMG+1
        bpl :+
        lda #0
        tax
:       stx PLR + PL_HEALTH
        sta PLR + PL_HEALTH + 1
        lda DM_SRC              ; attacker = source
        sta PLR + PL_ATTACKER
        lda DM_SRC+1
        sta PLR + PL_ATTACKER + 1
        clc                     ; damagecount += damage, at most 100
        lda PLR + PL_DAMAGECOUNT
        adc DM_DMG
        sta GT_0
        lda PLR + PL_DAMAGECOUNT + 1
        adc DM_DMG+1
        sta GT_1
        sec
        lda GT_0
        sbc #101
        lda GT_1
        sbc #0
        bmi :+
        lda #100
        sta GT_0
        stz GT_1
:       lda GT_0
        sta PLR + PL_DAMAGECOUNT
        lda GT_1
        sta PLR + PL_DAMAGECOUNT + 1
        sec
        rts

; ===========================================================================
; killMobj
; ===========================================================================
        ROUTINE killMobj
        lda DM_TGT              ; not shootable, gravity, a corpse that
        ldx DM_TGT+1            ;   can drop off
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<~UC_MF_SHOOTABLE_LO
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        and #>~UC_MF_NOGRAVITY_LO
        ora #>UC_MF_DROPOFF_LO
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        ora #<UC_MF_CORPSE_HI
        sta (GC_MP),y
        jsr asr_height          ; height >>= 2 (arithmetic)
        jsr asr_height
        lda #D_B
        jsr mo_dirty
        ldy #LN_B + MB_FLAGS + 2        ; a monster: totallive--,
        lda (GC_MP),y                   ;   killcount++
        and #<UC_MF_COUNTKILL_HI
        beq @player
        lda G_TOTALLIVE
        bne @d0
        lda G_TOTALLIVE+1
        bne @d1
        lda G_TOTALLIVE+2
        bne @d2
        dec G_TOTALLIVE+3
@d2:    dec G_TOTALLIVE+2
@d1:    dec G_TOTALLIVE+1
@d0:    dec G_TOTALLIVE
        inc PLR + PL_KILLCOUNT
        bne @player
        inc PLR + PL_KILLCOUNT + 1
@player:
        lda DM_PLY              ; the player: not solid, dead, the weapon
        beq @state              ;   down, no automap
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<~UC_MF_SOLID_LO
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
        lda #<UC_PST_DEAD
        sta PLR + PL_PLAYERSTATE
        lda #>UC_PST_DEAD
        sta PLR + PL_PLAYERSTATE + 1
        FCALL P_DropWeapon
        jsr AM_Stop             ; (its own test of the automap: request R4)
@state: lda DM_TYPE             ; health < -spawnhealth and an extreme
        ldy #UO_MI_SPAWNHEALTH  ;   death state: that one
        jsr mi_get
        eor #$FF
        clc
        adc #1
        sta DM_T
        txa
        eor #$FF
        adc #0
        sta DM_T+1
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_HEALTH
        sec
        lda (GC_MP),y
        sbc DM_T
        iny
        lda (GC_MP),y
        sbc DM_T+1
        bvc :+
        eor #$80
:       bpl @death
        lda DM_TYPE
        ldy #UO_MI_XDEATHSTATE
        jsr mi_get
        stx GT_0
        ora GT_0
        bne @xdeath
@death: lda DM_TYPE
        ldy #UO_MI_DEATHSTATE
        jsr mi_get
        bra @set
@xdeath:
        lda API_W
@set:   FCALL setState
        jsr g_random            ; tics -= P_Random() & 3, at least 1
        and #3
        sta GT_0
        lda DM_TGT
        ldx DM_TGT+1
        jsr pl_get
        lda PL_T                ; (a byte: -1, 1-12)
        sec
        sbc GT_0
        beq :+
        bpl :++
:       lda #1
:       sta PL_T
        lda DM_TGT
        ldx DM_TGT+1
        jsr pl_put
        lda DM_TGT              ; the item to drop
        ldx DM_TGT+1
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        sta DM_K
        lda PLR + PL_CHEATS
        ora PLR + PL_CHEATS + 1
        beq @norm
        lda PLR + PL_CHEATS     ; the cheat: everyone from MT_POSSESSED to
        and #UC_CF_ENEMY_ROCKETS        ;   MT_BRUISERSHOT drops a rocket
        beq @norm                       ;   launcher
        lda DM_K
        cmp #UC_MT_POSSESSED
        bcc @norm
        cmp #UC_MT_BRUISERSHOT + 1
        bcs @norm
        lda #UC_MT_MISC27
        bra @drop
@norm:  lda DM_K
        cmp #UC_MT_POSSESSED
        bne :+
        lda #UC_MT_CLIP
        bra @drop
:       cmp #UC_MT_SHOTGUY
        beq :+
        rts
:       lda #UC_MT_SHOTGUN
@drop:  sta GA_TYPE             ; P_SpawnMobj(x, y, ONFLOORZ, item)
        lda DM_TGT
        ldx DM_TGT+1
        jsr mo_get
        ldy #TH_Y + 3
:       lda (GC_MP),y
        sta GA_X - TH_X,y
        dey
        bpl :-
        stz GA_Z
        stz GA_Z+1
        stz GA_Z+2
        lda #$80
        sta GA_Z+3
        FCALL P_SpawnMobj
        jsr mo_get              ; MF_DROPPED
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        ora #<UC_MF_DROPPED_HI
        sta (GC_MP),y
        lda #D_B
        jmp mo_dirty

; asr_height: the mobj line's height (GC_MP) >>= 1, arithmetic
asr_height:
        ldy #LN_B + MB_HEIGHT + 3
        lda (GC_MP),y
        cmp #$80
        ror a
        sta (GC_MP),y
        ldx #3
:       dey
        lda (GC_MP),y
        ror a
        sta (GC_MP),y
        dex
        bne :-
        rts

        .assert TH_Y = TH_X + 4 && TH_X = 0, error, "x, y"
        .assert GA_Y = GA_X + 4, error, "GA_X, GA_Y"
        .assert M_B = M_A + 4, error, "M_A, M_B"
        .assert <UC_ONFLOORZ_LO = 0 && >UC_ONFLOORZ_LO = 0 && <UC_ONFLOORZ_HI = 0 && >UC_ONFLOORZ_HI = $80, error, "ONFLOORZ"
