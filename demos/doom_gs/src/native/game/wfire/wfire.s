; game/wfire/wfire.s: part wfire, the player's weapons firing (milestone 10,
; docs/GAME.md 2.2 ACTTAB, 2.4 row wfire; docs/game-parts/wfire.md). A
; GPL-2 derivative of upstream's p_pspr65.s (A_Punch:767, A_Saw:802,
; meleeAngle, spread, meleeAttack, angleToTarget, randMod, useAmmo,
; A_FireMissile:1005, bulletSlope:1015, aimAt, gunShot:1055, notRefire,
; A_FirePistol:1108, A_FireShotgun:1121, A_FireCGun:1139) and of
; p_spawn65.s (P_SpawnPlayerMissile:640 with aim), Doom8088: Apple IIgs
; Edition. Nothing here comes from upstream's cal_integer.s: the modulo of
; randMod is a subtraction loop, FixedMul is milestone 6's fixmul,
; R_PointToAngle3 the game math's pta3.
;
; The weapon actions (ACTTAB: GS_PSP the psprite, gw_setpsprite's
; convention; upstream's player and psp arguments):
;   A_FirePistol    the pistol's sound, the player to S_PLAY_ATK2, a round
;                   used, the flash (fireSomething 0), bulletSlope, then
;                   gunShot(accurate = !refire)
;   A_FireShotgun   the shotgun's sound, S_PLAY_ATK2, a shell used, the
;                   flash, bulletSlope, then seven gunShot(0): seven
;                   pellets, each its own damage and spread in that order
;   A_FireCGun      only with ammunition (ammo[the weapon's] not 0): the
;                   pistol's sound, S_PLAY_ATK2, a round used, the flash
;                   + (the psprite's state - S_CHAIN1), bulletSlope,
;                   gunShot(!refire)
;   A_FireMissile   the launcher's sound, a rocket used,
;                   P_SpawnPlayerMissile(the player's mobj)
;   A_Punch         damage (P_Random() % 10 + 1) * 2, x 10 with the
;                   berserk power; meleeAngle; meleeAttack(0); a target:
;                   the punch's sound, the player turned to it
;   A_Saw           damage (P_Random() % 10 + 1) * 2; meleeAngle;
;                   meleeAttack(1); no target: the saw's sound; else the
;                   hit's sound, the player turned toward the target by
;                   upstream's steps (d = angle - mo->angle, unsigned:
;                   d > ANG180 and d < -ANG90/20: angle + ANG90/21; d >
;                   ANG180: mo->angle - ANG90/20; d > ANG90/20: angle -
;                   ANG90/21; else mo->angle + ANG90/20), MF_JUSTATTACKED
;
; The routines the actions call (each a routine: the placement may part
; them):
;   P_SpawnPlayerMissile  GA_0-1 = the source: a rocket from 32 units
;                   above it, aimed (P_AimLineAttack at 16 x 64 units)
;                   straight ahead, else 1 << 26 to the left, else 1 << 26
;                   to the right, else level at the source's angle (slope
;                   0); see sound, target the source, angle and momentum
;                   (part missile's srcAbove, spawnXYZ, seeTarget,
;                   angleMom), momz = FixedMul(speed, slope), then
;                   checkMissile. Returns nothing
;   bulletSlope     WF_SLOPE = P_AimLineAttack(the player's mobj, its
;                   angle, 16 x 64 units), else at 1 << 26 to the left,
;                   else to the right (the last one's slope: 0 without a
;                   target)
;   gunShot         A = accurate (0 not): damage 5 x (P_Random() % 3 + 1),
;                   the player's angle with a spread when not accurate,
;                   P_LineAttack(mo, angle, MISSILERANGE, WF_SLOPE, damage)
;   meleeAngle      WF_ANGLE = the player's angle, then spread
;   spread          WF_ANGLE's high word += (t - P_Random()) << 2, t =
;                   P_Random() (the first call's value less the second's,
;                   16 bits)
;   meleeAttack     A = 0 or 1: P_AimLineAttack(mo, WF_ANGLE, MELEERANGE +
;                   A), then P_LineAttack(mo, WF_ANGLE, MELEERANGE + A,
;                   the slope, WF_DMG)
;   angleToTarget   M_R = R_PointToAngle2(the player's mobj's x, y,
;                   linetarget's x, y)
;   p_pspr_randMod  A = c (1-255): A = P_Random() % c
;   useAmmo         ammo[weaponinfo[readyweapon].ammo] - 1 (a word)
;
; Upstream's aim and aimAt (an aim of the retries) and notRefire (C =
; !refire) have no code of their own: the retries are a loop in their
; routine, the refire test is done in place (request R1: INLINED).
;
; Every routine changes A, X, Y, GA_*, GT_*, GS_* and the math block (its
; callees do: P_AimLineAttack, P_LineAttack, P_SpawnMobj).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/wfire/wfire.inc"

        .export A_FirePistol, A_FireShotgun, A_FireCGun, A_FireMissile
        .export A_Punch, A_Saw, P_SpawnPlayerMissile, bulletSlope, gunShot
        .export meleeAngle, spread, meleeAttack, angleToTarget
        .export p_pspr_randMod, useAmmo
        .import mo_get, mo_dirty, g_random, weaponinfo, pta3, fixmul
        .import fc_call, fc_unbuilt

; ===========================================================================
; A_FirePistol, A_FireShotgun, A_FireCGun
; ===========================================================================
        ROUTINE A_FirePistol
        lda #UC_SFX_PISTOL
        FCALL p_pspr_startSound
        lda #<UC_S_PLAY_ATK2    ; the player's attack frame
        ldx #>UC_S_PLAY_ATK2
        FCALL setMoState
        FCALL useAmmo
        lda #0                  ; the flash
        FCALL fireSomething
        FCALL bulletSlope
        ldx #1                  ; gunShot(!refire)
        lda PLR + PL_REFIRE
        ora PLR + PL_REFIRE + 1
        beq :+
        dex
:       txa
        FCALL gunShot
        rts

        ROUTINE A_FireShotgun
        lda #UC_SFX_SHOTGN
        FCALL p_pspr_startSound
        lda #<UC_S_PLAY_ATK2
        ldx #>UC_S_PLAY_ATK2
        FCALL setMoState
        FCALL useAmmo
        lda #0
        FCALL fireSomething
        FCALL bulletSlope
        lda #7                  ; seven pellets
        sta WF_I
:       lda #0
        FCALL gunShot
        dec WF_I
        bne :-
        rts

        ROUTINE A_FireCGun
        lda GS_PSP              ; the psprite (upstream's pei of _Dp[4])
        sta WF_PSP
        FCALL wInfo             ; the sound only with ammunition
        lda weaponinfo + UO_WI_AMMO,x
        asl a
        tay
        lda PLR + PL_AMMO_0,y
        ora PLR + PL_AMMO_0 + 1,y
        bne :+
        rts
:       lda #UC_SFX_PISTOL
        FCALL p_pspr_startSound
        lda #<UC_S_PLAY_ATK2
        ldx #>UC_S_PLAY_ATK2
        FCALL setMoState
        FCALL useAmmo
        ldx WF_PSP              ; the flash + (psp->state - S_CHAIN1)
        beq :+
        ldx #PSP_SIZE
:       sec
        lda PSTATE,x
        sbc #<UC_S_CHAIN1
        FCALL fireSomething
        FCALL bulletSlope
        ldx #1                  ; gunShot(!refire)
        lda PLR + PL_REFIRE
        ora PLR + PL_REFIRE + 1
        beq :+
        dex
:       txa
        FCALL gunShot
        rts

; ===========================================================================
; A_FireMissile, P_SpawnPlayerMissile
; ===========================================================================
        ROUTINE A_FireMissile
        lda #UC_SFX_RLAUNC
        FCALL p_pspr_startSound
        FCALL useAmmo
        lda PLR + PL_MO
        sta GA_0
        lda PLR + PL_MO + 1
        sta GA_1
        FCALL P_SpawnPlayerMissile
        rts

        ROUTINE P_SpawnPlayerMissile
        lda GA_0
        sta WF_SRC
        lda GA_1
        sta WF_SRC+1
        jsr src_angle           ; an = source->angle
        stz WF_K
@aim:   lda WF_SRC              ; aim: slope = P_AimLineAttack(source, an,
        sta GA_0                ;   16 * 64 * FRACUNIT)
        lda WF_SRC+1
        sta GA_1
        ldx #3
:       lda WF_AN,x
        sta GA_2,x
        dex
        bpl :-
        jsr aim_range
        FCALL P_AimLineAttack
        ldx #3
:       lda GA_0,x
        sta WF_SLP,x
        dex
        bpl :-
        lda GM_LINETARGET+1     ; a target: the missile
        cmp #$FF
        bne @spawn
        ldx WF_K                ; an += 1 << 26, then an -= 2 << 26
        cpx #2
        beq @none
        clc
        lda WF_AN+3
        adc aim_step,x
        sta WF_AN+3
        inc WF_K
        bra @aim
@none:  jsr src_angle           ; none: an = source->angle, slope 0
        stz WF_SLP
        stz WF_SLP+1
        stz WF_SLP+2
        stz WF_SLP+3
@spawn: lda WF_SRC              ; th = P_SpawnMobj(x, y, z + 32, MT_ROCKET)
        ldx WF_SRC+1
        FCALL srcAbove
        lda #UC_MT_ROCKET
        FCALL spawnXYZ
        sta WF_TH
        stx WF_TH+1
        ldy WF_SRC              ; the see sound, target = source
        sty GA_0
        ldy WF_SRC+1
        sty GA_1
        FCALL seeTarget
        ldx #3                  ; angle, momx, momy
:       lda WF_AN,x
        sta GA_0,x
        dex
        bpl :-
        lda WF_TH
        ldx WF_TH+1
        FCALL angleMom
        lda WF_TH               ; momz = FixedMul(speed, slope)
        ldx WF_TH+1
        FCALL thSpeed
        ldx #3
:       lda WF_SLP,x
        sta M_B,x
        dex
        bpl :-
        jsr fixmul
        lda WF_TH
        ldx WF_TH+1
        jsr mo_get
        ldy #LN_C + MC_MOMZ
        ldx #0
:       lda M_R,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_C
        jsr mo_dirty
        lda WF_TH               ; P_CheckMissileSpawn(th)
        ldx WF_TH+1
        FCALL checkMissile
        rts

; src_angle: WF_AN = WF_SRC's angle
src_angle:
        lda WF_SRC
        ldx WF_SRC+1
        jsr mo_get
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta WF_AN
        iny
        lda (GC_MP),y
        sta WF_AN+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta WF_AN+2
        iny
        lda (GC_MP),y
        sta WF_AN+3
        rts

; aim_range: GA_6-9 = 16 * 64 * FRACUNIT (the aims' distance)
aim_range:
        stz GA_6
        stz GA_7
        lda #<WF_AIM_HI
        sta GA_8
        lda #>WF_AIM_HI
        sta GA_9
        rts

; the retries' steps of the angle's high byte: + 1 << 26, then - 2 << 26
aim_step:
        .byte $04, $F8

; ===========================================================================
; bulletSlope, gunShot
; ===========================================================================
        ROUTINE bulletSlope
        lda PLR + PL_MO         ; an = mo->angle
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta WF_ANGLE
        iny
        lda (GC_MP),y
        sta WF_ANGLE+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta WF_ANGLE+2
        iny
        lda (GC_MP),y
        sta WF_ANGLE+3
        stz WF_K
@aim:   lda PLR + PL_MO         ; aimAt: bulletslope = P_AimLineAttack(mo,
        sta GA_0                ;   an, 16 * 64 * FRACUNIT)
        lda PLR + PL_MO + 1
        sta GA_1
        ldx #3
:       lda WF_ANGLE,x
        sta GA_2,x
        dex
        bpl :-
        stz GA_6
        stz GA_7
        lda #<WF_AIM_HI
        sta GA_8
        lda #>WF_AIM_HI
        sta GA_9
        FCALL P_AimLineAttack
        ldx #3
:       lda GA_0,x
        sta WF_SLOPE,x
        dex
        bpl :-
        lda GM_LINETARGET+1     ; a target: done
        cmp #$FF
        bne @done
        ldx WF_K                ; an += 1 << 26, then an -= 2 << 26
        cpx #2
        beq @done
        clc
        lda WF_ANGLE+3
        adc @step,x
        sta WF_ANGLE+3
        inc WF_K
        bra @aim
@done:  rts
@step:  .byte $04, $F8

        ROUTINE gunShot
        sta WF_ACC
        lda #3                  ; damage = 5 * (P_Random() % 3 + 1)
        FCALL p_pspr_randMod
        inc a
        sta GT_0
        asl a
        asl a
        clc
        adc GT_0
        sta WF_DMG
        stz WF_DMG+1
        lda PLR + PL_MO         ; angle = mo->angle
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta WF_ANGLE
        iny
        lda (GC_MP),y
        sta WF_ANGLE+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta WF_ANGLE+2
        iny
        lda (GC_MP),y
        sta WF_ANGLE+3
        lda WF_ACC              ; not accurate: the spread
        bne :+
        FCALL spread
:       lda PLR + PL_MO         ; P_LineAttack(mo, angle, MISSILERANGE,
        sta GA_0                ;   bulletslope, damage)
        lda PLR + PL_MO + 1
        sta GA_1
        ldx #3
:       lda WF_ANGLE,x
        sta GA_2,x
        lda WF_SLOPE,x
        sta GA_10,x
        dex
        bpl :-
        stz GA_6
        stz GA_7
        lda #<WF_MISSILE_HI
        sta GA_8
        lda #>WF_MISSILE_HI
        sta GA_9
        lda WF_DMG
        sta GA_14
        lda WF_DMG+1
        sta GA_15
        FCALL P_LineAttack
        rts

; ===========================================================================
; A_Punch, A_Saw
; ===========================================================================
        ROUTINE A_Punch
        lda #10                 ; damage = (P_Random() % 10 + 1) << 1
        FCALL p_pspr_randMod
        inc a
        asl a
        sta WF_DMG
        stz WF_DMG+1
        lda STRENGTH            ; berserk: x 10 (at most 200: a byte)
        ora STRENGTH+1
        beq :+
        lda WF_DMG
        asl a
        asl a
        clc
        adc WF_DMG
        asl a
        sta WF_DMG
:       FCALL meleeAngle
        lda #0                  ; MELEERANGE
        FCALL meleeAttack
        lda GM_LINETARGET+1
        cmp #$FF
        bne :+
        rts
:       lda #UC_SFX_PUNCH
        FCALL p_pspr_startSound
        FCALL angleToTarget     ; turn to face the target
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr mo_get
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
        jmp mo_dirty

        ROUTINE A_Saw
        lda #10                 ; damage = 2 * (P_Random() % 10 + 1)
        FCALL p_pspr_randMod
        inc a
        asl a
        sta WF_DMG
        stz WF_DMG+1
        FCALL meleeAngle
        lda #1                  ; MELEERANGE + 1: the puff shows
        FCALL meleeAttack
        lda GM_LINETARGET+1
        cmp #$FF
        bne @hit
        lda #UC_SFX_SAWFUL      ; no target
        FCALL p_pspr_startSound
        rts
@hit:   lda #UC_SFX_SAWHIT
        FCALL p_pspr_startSound
        FCALL angleToTarget     ; angle = to the target
        ldx #3
:       lda M_R,x
        sta WF_ANGLE,x
        dex
        bpl :-
        lda PLR + PL_MO         ; GT_0-3 = mo->angle
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        ldy #TH_ANG
        lda (GC_MP),y
        sta GT_2
        iny
        lda (GC_MP),y
        sta GT_3
        sec                     ; d = angle - mo->angle
        ldx #0
:       lda WF_ANGLE,x
        sbc GT_0,x
        sta WF_T,x
        inx
        txa
        eor #4
        bne :-
        ; d > ANG180 (unsigned): ANG180 - d borrows
        sec
        lda #<WF_ANG180
        sbc WF_T
        lda #>WF_ANG180
        sbc WF_T+1
        lda #^WF_ANG180
        sbc WF_T+2
        lda #(WF_ANG180 >> 24)
        sbc WF_T+3
        bcs @right
        ; d < -ANG90 / 20: angle + ANG90 / 21, else mo->angle - ANG90 / 20
        sec
        lda WF_T
        sbc #<WF_NANG90_20
        lda WF_T+1
        sbc #>WF_NANG90_20
        lda WF_T+2
        sbc #^WF_NANG90_20
        lda WF_T+3
        sbc #(WF_NANG90_20 >> 24)
        ldx #4                  ; (mo->angle - ANG90 / 20)
        bcs @turn
        ldx #0                  ; (angle + ANG90 / 21)
        bra @turn
        ; d > ANG90 / 20: angle - ANG90 / 21, else mo->angle + ANG90 / 20
@right: sec
        lda #<WF_ANG90_20
        sbc WF_T
        lda #>WF_ANG90_20
        sbc WF_T+1
        lda #^WF_ANG90_20
        sbc WF_T+2
        lda #(WF_ANG90_20 >> 24)
        sbc WF_T+3
        ldx #12                 ; (mo->angle + ANG90 / 20)
        bcs @turn
        ldx #8                  ; (angle - ANG90 / 21)
@turn:  cpx #4                  ; the base: angle (0, 8) or mo->angle (in
        beq :+                  ;   GT_0-3: 4, 12)
        cpx #12
        beq :+
        lda WF_ANGLE
        sta GT_0
        lda WF_ANGLE+1
        sta GT_1
        lda WF_ANGLE+2
        sta GT_2
        lda WF_ANGLE+3
        sta GT_3
:       clc                     ; GT_0-3 += the addend at X
        ldy #0
:       lda GT_0,y
        adc saw_add,x
        sta GT_0,y
        inx
        iny
        tya
        eor #4
        bne :-
        ldy #TH_ANGLO           ; mo->angle = it (the line still mo's)
        lda GT_0
        sta (GC_MP),y
        iny
        lda GT_1
        sta (GC_MP),y
        ldy #TH_ANG
        lda GT_2
        sta (GC_MP),y
        iny
        lda GT_3
        sta (GC_MP),y
        ldy #LN_B + MB_FLAGS    ; flags |= MF_JUSTATTACKED
        lda (GC_MP),y
        ora #<UC_MF_JUSTATTACKED_LO
        sta (GC_MP),y
        lda #D_RTH | D_B
        jmp mo_dirty

; A_Saw's addends (little-endian), by its four results
saw_add:
        .dword WF_ANG90_21                      ; 0: angle + ANG90 / 21
        .dword WF_NANG90_20                     ; 4: mo->angle - ANG90 / 20
        .dword WF_NANG90_21                     ; 8: angle - ANG90 / 21
        .dword WF_ANG90_20                      ; 12: mo->angle + ANG90 / 20

; ===========================================================================
; meleeAngle, spread, meleeAttack, angleToTarget
; ===========================================================================
        ROUTINE meleeAngle
        lda PLR + PL_MO         ; WP_ANGLE = mo->angle
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta WF_ANGLE
        iny
        lda (GC_MP),y
        sta WF_ANGLE+1
        ldy #TH_ANG
        lda (GC_MP),y
        sta WF_ANGLE+2
        iny
        lda (GC_MP),y
        sta WF_ANGLE+3
        FCALL spread            ; (upstream falls into it)
        rts

        ROUTINE spread
        jsr g_random            ; t
        sta GT_0
        jsr g_random            ; t - P_Random(), 16 bits
        sta GT_1
        sec
        lda GT_0
        sbc GT_1
        sta GT_0
        lda #0
        sbc #0
        sta GT_1
        asl GT_0                ; << 2
        rol GT_1
        asl GT_0
        rol GT_1
        clc                     ; + the angle's high word
        lda WF_ANGLE+2
        adc GT_0
        sta WF_ANGLE+2
        lda WF_ANGLE+3
        adc GT_1
        sta WF_ANGLE+3
        rts

        ROUTINE meleeAttack
        sta WF_RNG
        jsr melee_args          ; slope = P_AimLineAttack(mo, WP_ANGLE,
        FCALL P_AimLineAttack   ;   MELEERANGE + C)
        ldx #3
:       lda GA_0,x
        sta GA_10,x
        dex
        bpl :-
        jsr melee_args          ; P_LineAttack(mo, WP_ANGLE, MELEERANGE + C,
        lda WF_DMG              ;   slope, WP_DAMAGE)
        sta GA_14
        lda WF_DMG+1
        sta GA_15
        FCALL P_LineAttack
        rts

; melee_args: GA_0-1 = the player's mobj, GA_2-5 = WF_ANGLE, GA_6-9 =
; MELEERANGE + WF_RNG
melee_args:
        lda PLR + PL_MO
        sta GA_0
        lda PLR + PL_MO + 1
        sta GA_1
        ldx #3
:       lda WF_ANGLE,x
        sta GA_2,x
        dex
        bpl :-
        lda WF_RNG
        sta GA_6
        stz GA_7
        lda #<WF_MELEE_HI
        sta GA_8
        lda #>WF_MELEE_HI
        sta GA_9
        rts

        ROUTINE angleToTarget
        lda GM_LINETARGET       ; M_A, M_B = linetarget's x, y
        ldx GM_LINETARGET+1
        jsr mo_get
        ldy #7
:       lda (GC_MP),y
        sta M_A,y
        dey
        bpl :-
        lda PLR + PL_MO         ; less mo's: dx, dy
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #0
@w:     sec
        ldx #4
:       lda M_A,y
        sbc (GC_MP),y
        sta M_A,y
        iny
        dex
        bne :-
        cpy #8
        bne @w
        jmp pta3                ; M_R = R_PointToAngle3(dx, dy)

; ===========================================================================
; p_pspr_randMod, useAmmo
; ===========================================================================
        ROUTINE p_pspr_randMod
        sta GT_0                ; c
        jsr g_random
:       cmp GT_0                ; P_Random() % c
        bcc :+
        sbc GT_0
        bra :-
:       rts

        ROUTINE useAmmo
        FCALL wInfo             ; ammo[weaponinfo[readyweapon].ammo]--
        lda weaponinfo + UO_WI_AMMO,x
        asl a
        tax
        lda PLR + PL_AMMO_0,x
        bne :+
        dec PLR + PL_AMMO_0 + 1,x
:       dec PLR + PL_AMMO_0,x
        rts
