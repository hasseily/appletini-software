; game/pspr/pspr.s: part pspr's weapon sprites (docs/GAME.md). A GPL-2
; derivative of upstream's
; p_pspr65.s (P_MovePsprites, tickPsprite, A_WeaponReady with signExt4 and
; signExt0, A_ReFire, A_Lower, A_GunFlash, fireSomething, A_Light0-2,
; fireWeapon with the noise alert, checkAmmo, P_CheckAmmo, startSound,
; setMoState). The flood itself, recursiveSound, is pflood.s.
;
;   P_MovePsprites  each tic: tickPsprite of the weapon, then of the flash;
;                   the flash takes the weapon's sx and sy
;   tickPsprite     A = a psprite: with a state and tics not -1, tics - 1,
;                   and at 0 its state's next (gw_setpsprite)
;   A_WeaponReady   (ACTTAB, GS_PSP) out of the player's attack states; the
;                   chainsaw's idle sound; a change pending or no health:
;                   lowerWeapon; the attack button: fireWeapon (not again
;                   by itself for the rocket launcher and the BFG); else the
;                   bob: sx = 1 + hi16(bob x bhw) + hi16(ahw x blw) of
;                   finecosine (the low 32 bits of each product, _Mul32's:
;                   math.s mul32), sy = WEAPONTOP + FixedMulAngle(bob,
;                   finesine), the angle (leveltime & 63) << 7
;   signExt4        A:X (a word): M_B = it sign extended (upstream's
;                   _Dp[4-7], _Mul32's second operand)
;   signExt0        A:X: M_A = it sign extended (_Dp[0-3])
;   A_ReFire        (ACTTAB) the attack held, no change pending, alive:
;                   refire + 1 and fireWeapon; else refire 0
;   A_Lower         (ACTTAB, GS_PSP) sy += LOWERSPEED; at the bottom: dead,
;                   it stays there; no health, the weapon's psprite none;
;                   else the pending weapon comes up (bringUpWeapon)
;   A_GunFlash      (ACTTAB) the player to S_PLAY_ATK2, fireSomething(0)
;   fireSomething   A = k: the flash psprite to the weapon's flash state + k
;   A_Light0-2      (ACTTAB) extralight 0, 1, 2
;   fireWeapon      checkAmmo; enough: the player to S_PLAY_ATK1, the
;                   weapon's attack state, then the noise alert
;                   (P_NoiseAlert: validcount + 1, the flood from the
;                   player's sector with no sound block, the target the
;                   player's mobj)
;   checkAmmo       A = 1 when the ready weapon has the ammunition of a
;                   shot (1, the BFG 40, the super shotgun 2; ammo[a] >=
;                   count, signed) or needs none, else 0. Upstream's
;                   checkAmmo switches no weapon (G_BuildTiccmd's
;                   P_SwitchWeapon does: dl_cmd.s)
;   P_CheckAmmo     the same (upstream's JSL entry)
;   p_pspr_startSound  A = a sound: S_StartSound(player->mo, A)
;   setMoState      A:X = a state: P_SetMobjState(player->mo, A:X)
;
; argMo (upstream's _Dp = player->mo) has no code: the routines read the
; player's PL_MO where upstream calls it.
;
; Every routine changes A, X, Y, GT_*, GS_ST, GS_PSP, the math's block and
; what its callees change; GA_* only through its callees.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/pspr/pspr.inc"

        .export P_MovePsprites, tickPsprite, A_WeaponReady, A_ReFire
        .export A_Lower, A_GunFlash, A_Light0, A_Light1, A_Light2
        .export fireWeapon, checkAmmo, P_CheckAmmo, p_pspr_startSound
        .export setMoState, signExt4, signExt0, fireSomething
        .import mo_get, ss_get, state_at, gw_setpsprite, gv_inc
        .import bringUpWeapon
        .import S_StartSound, weaponinfo, mul32, fixmulang, finesine
        .import finecosine, fc_call, fc_unbuilt

; ===========================================================================
; P_MovePsprites, tickPsprite
; ===========================================================================
        ROUTINE P_MovePsprites
        lda #0
        FCALL tickPsprite
        lda #1
        FCALL tickPsprite
        lda PSX                 ; the flash follows the weapon
        sta PSX + PSP_SIZE
        lda PSX+1
        sta PSX + PSP_SIZE + 1
        ldx #3
:       lda PSY,x
        sta PSY + PSP_SIZE,x
        dex
        bpl :-
        rts

; tickPsprite: A = the psprite
        ROUTINE tickPsprite
        sta GS_PSP
        tax
        beq :+
        ldx #PSP_SIZE
:       lda PSTATE,x            ; no state: nothing
        and PSTATE+1,x
        cmp #$FF
        beq @done
        lda PTICS,x             ; tics -1: nothing
        and PTICS+1,x
        cmp #$FF
        beq @done
        lda PTICS,x             ; tics - 1 (a word)
        bne :+
        dec PTICS+1,x
:       dec PTICS,x
        lda PTICS,x
        ora PTICS+1,x
        bne @done
        lda PSTATE,x            ; the state's next
        pha
        lda PSTATE+1,x
        tax
        pla
        jsr state_at
        lda LW_STATE + U_ST_NEXTSTATE
        sta GS_ST
        lda LW_STATE + U_ST_NEXTSTATE + 1
        sta GS_ST+1
        jmp gw_setpsprite       ; (GS_PSP the psprite)
@done:  rts

; ===========================================================================
; A_WeaponReady, signExt4, signExt0
; ===========================================================================
        ROUTINE A_WeaponReady
        lda GS_PSP              ; the psprite, on the stack (an action it
        pha                     ;   runs may set GS_PSP again)
        lda PLR + PL_MO         ; out of the attack states of the player
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #LN_A + MA_STATE + 1
        lda (GC_MP),y
        bne @saw
        dey
        lda (GC_MP),y
        .assert >UC_S_PLAY_ATK1 = 0 && >UC_S_PLAY_ATK2 = 0, error, "states"
        cmp #<UC_S_PLAY_ATK1
        beq :+
        cmp #<UC_S_PLAY_ATK2
        bne @saw
:       lda #<UC_S_PLAY
        ldx #>UC_S_PLAY
        FCALL setMoState
@saw:   lda PLR + PL_READYWEAPON + 1    ; the chainsaw idles
        bne @chg
        lda PLR + PL_READYWEAPON
        cmp #UC_WP_CHAINSAW
        bne @chg
        pla
        pha
        tax
        beq :+
        ldx #PSP_SIZE
:       lda PSTATE,x
        cmp #<UC_S_SAW
        bne @chg
        lda PSTATE+1,x
        cmp #>UC_S_SAW
        bne @chg
        lda #UC_SFX_SAWIDL
        FCALL p_pspr_startSound
@chg:   lda PLR + PL_PENDINGWEAPON      ; a change, or dead: down
        cmp #UC_WP_NOCHANGE
        bne @lower
        lda PLR + PL_PENDINGWEAPON + 1
        bne @lower
        lda PLR + PL_HEALTH
        ora PLR + PL_HEALTH + 1
        bne @fire
@lower: FCALL lowerWeapon
        pla
        rts
@fire:  lda PLR + PL_CMD_BUTTONS        ; fire
        and #UC_BT_ATTACK
        beq @up
        lda PLR + PL_ATTACKDOWN         ; the rocket launcher and the BFG
        ora PLR + PL_ATTACKDOWN + 1     ;   do not fire again by themselves
        beq @shoot
        lda PLR + PL_READYWEAPON + 1
        bne @shoot
        lda PLR + PL_READYWEAPON
        cmp #UC_WP_MISSILE
        beq @bob
        cmp #UC_WP_BFG
        beq @bob
@shoot: lda #1
        sta PLR + PL_ATTACKDOWN
        stz PLR + PL_ATTACKDOWN + 1
        FCALL fireWeapon
        pla
        rts
@up:    stz PLR + PL_ATTACKDOWN
        stz PLR + PL_ATTACKDOWN + 1
        ; the bob with the movement: angle = (leveltime & 63) << 7
@bob:   lda G_LEVELTIME
        and #$3F
        lsr a
        sta PS_ANG+1
        lda #0
        ror a
        sta PS_ANG
        sta M_A
        lda PS_ANG+1
        sta M_A+1
        jsr finecosine          ; cos (32 bits)
        ldx #3
:       lda M_R,x
        sta PS_COS,x
        dex
        bpl :-
        lda PS_COS+2            ; hi16(bob * (int32_t)bhw)
        ldx PS_COS+3
        FCALL signExt4
        ldx #3
:       lda PLR + PL_BOB,x
        sta M_A,x
        dex
        bpl :-
        jsr mul32
        lda M_R+2
        sta PS_T
        lda M_R+3
        sta PS_T+1
        lda PLR + PL_BOB + 2    ; + hi16((uint32_t)ahw * blw)
        ldx PLR + PL_BOB + 3
        FCALL signExt0
        lda PS_COS
        sta M_B
        lda PS_COS+1
        sta M_B+1
        stz M_B+2
        stz M_B+3
        jsr mul32
        pla                     ; psp->sx = the two + 1
        pha
        tax
        beq :+
        ldx #PSP_SIZE
:       sec
        lda M_R+2
        adc PS_T
        sta PSX,x
        lda M_R+3
        adc PS_T+1
        sta PSX+1,x
        lda PS_ANG              ; sy = WEAPONTOP + FixedMulAngle(bob,
        sta M_A                 ;   finesine(angle & 4095))
        lda PS_ANG+1
        and #$0F
        sta M_A+1
        jsr finesine
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda PLR + PL_BOB,x
        sta M_A,x
        dex
        bpl :-
        jsr fixmulang
        pla
        tax
        beq :+
        ldx #PSP_SIZE
:       lda M_R
        sta PSY,x
        lda M_R+1
        sta PSY+1,x
        clc
        lda M_R+2
        adc #<U_WEAPONTOP_HI
        sta PSY+2,x
        lda M_R+3
        adc #>U_WEAPONTOP_HI
        sta PSY+3,x
        rts

; signExt4: M_B = A:X sign extended (upstream's _Dp[4-7] = C)
        ROUTINE signExt4
        sta M_B
        stx M_B+1
        ldy #0
        txa
        bpl :+
        dey
:       sty M_B+2
        sty M_B+3
        rts

; signExt0: M_A = A:X sign extended (upstream's _Dp[0-3] = C)
        ROUTINE signExt0
        sta M_A
        stx M_A+1
        ldy #0
        txa
        bpl :+
        dey
:       sty M_A+2
        sty M_A+3
        rts

; ===========================================================================
; A_ReFire
; ===========================================================================
        ROUTINE A_ReFire
        lda PLR + PL_CMD_BUTTONS
        and #UC_BT_ATTACK
        beq @no
        lda PLR + PL_PENDINGWEAPON
        cmp #UC_WP_NOCHANGE
        bne @no
        lda PLR + PL_PENDINGWEAPON + 1
        bne @no
        lda PLR + PL_HEALTH
        ora PLR + PL_HEALTH + 1
        beq @no
        inc PLR + PL_REFIRE     ; refire + 1, and fire
        bne :+
        inc PLR + PL_REFIRE + 1
:       FCALL fireWeapon
        rts
@no:    stz PLR + PL_REFIRE     ; (P_CheckAmmo has no effect here)
        stz PLR + PL_REFIRE + 1
        rts

; ===========================================================================
; A_Lower
; ===========================================================================
        ROUTINE A_Lower
        ldx GS_PSP
        beq :+
        ldx #PSP_SIZE
:       clc                     ; psp->sy += LOWERSPEED (its high word)
        lda PSY+2,x
        adc #<U_LOWERSPEED_HI
        sta PSY+2,x
        tay
        lda PSY+3,x
        adc #>U_LOWERSPEED_HI
        sta PSY+3,x
        cpy #<U_WEAPONBOTTOM_HI ; still going down: the word's cmp
        sbc #>U_WEAPONBOTTOM_HI ;   WEAPONBOTTOM gives N (no overflow
        bpl :+                  ;   test, as upstream's bpl)
        rts
:       lda PLR + PL_PLAYERSTATE        ; dead: stays at the bottom
        cmp #<UC_PST_DEAD
        bne @alive
        lda PLR + PL_PLAYERSTATE + 1
        cmp #>UC_PST_DEAD
        bne @alive
        stz PSY,x
        stz PSY+1,x
        lda #<U_WEAPONBOTTOM_HI
        sta PSY+2,x
        lda #>U_WEAPONBOTTOM_HI
        sta PSY+3,x
        rts
@alive: lda PLR + PL_HEALTH     ; no health: off the screen
        ora PLR + PL_HEALTH + 1
        bne @up
        stz GS_ST               ; S_NULL on the weapon's psprite
        stz GS_ST+1
        stz GS_PSP
        jmp gw_setpsprite
@up:    lda PLR + PL_PENDINGWEAPON      ; the new weapon comes up
        sta PLR + PL_READYWEAPON
        lda PLR + PL_PENDINGWEAPON + 1
        sta PLR + PL_READYWEAPON + 1
        jmp bringUpWeapon       ; (gweap.s, the core)

; ===========================================================================
; A_GunFlash, fireSomething
; ===========================================================================
        ROUTINE A_GunFlash
        lda #<UC_S_PLAY_ATK2
        ldx #>UC_S_PLAY_ATK2
        FCALL setMoState
        lda #0
        FCALL fireSomething
        rts

; fireSomething: A = k: setPsprite(ps_flash, the flash state + k)
        ROUTINE fireSomething
        pha
        FCALL wInfo
        pla
        clc
        adc weaponinfo + UO_WI_FLASHSTATE,x
        sta GS_ST
        lda weaponinfo + UO_WI_FLASHSTATE + 1,x
        adc #0
        sta GS_ST+1
        lda #1
        sta GS_PSP
        jmp gw_setpsprite

; ===========================================================================
; A_Light0, A_Light1, A_Light2
; ===========================================================================
        ROUTINE A_Light0
        stz PLR + PL_EXTRALIGHT
        stz PLR + PL_EXTRALIGHT + 1
        rts

        ROUTINE A_Light1
        lda #1
        sta PLR + PL_EXTRALIGHT
        stz PLR + PL_EXTRALIGHT + 1
        rts

        ROUTINE A_Light2
        lda #2
        sta PLR + PL_EXTRALIGHT
        stz PLR + PL_EXTRALIGHT + 1
        rts

; ===========================================================================
; fireWeapon with the noise alert
; ===========================================================================
        ROUTINE fireWeapon
        FCALL checkAmmo
        cmp #0
        bne :+
        rts
:       lda #<UC_S_PLAY_ATK1
        ldx #>UC_S_PLAY_ATK1
        FCALL setMoState
        FCALL wInfo             ; setPsprite(ps_weapon, the attack state)
        lda weaponinfo + UO_WI_ATKSTATE,x
        sta GS_ST
        lda weaponinfo + UO_WI_ATKSTATE + 1,x
        sta GS_ST+1
        stz GS_PSP
        jsr gw_setpsprite
        ; noiseAlert: P_NoiseAlert(player->mo, player->mo): validcount + 1,
        ; the flood from mo->subsector->sector with no sound block, its
        ; target the player's mobj
        jsr gv_inc
        lda PLR + PL_MO
        sta PS_TGT
        ldx PLR + PL_MO + 1
        stx PS_TGT+1
        jsr mo_get
        ldy #LN_A + MA_SUBSEC
        lda (GC_MP),y
        pha
        iny
        lda (GC_MP),y
        tax
        pla
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        ldy #0
        FCALL recursiveSound
        rts

; ===========================================================================
; checkAmmo, P_CheckAmmo
; ===========================================================================
        ROUTINE checkAmmo
        ldy #1                  ; count
        lda PLR + PL_READYWEAPON + 1
        bne @count
        lda PLR + PL_READYWEAPON
        cmp #UC_WP_BFG
        bne :+
        ldy #40                 ; BFGCELLS
        bra @count
:       cmp #UC_WP_SUPERSHOTGUN
        bne @count
        ldy #2
@count: sty PS_CNT
        FCALL wInfo
        lda weaponinfo + UO_WI_AMMO + 1,x       ; am_noammo: none needed
        bne @ammo
        lda weaponinfo + UO_WI_AMMO,x
        cmp #UC_AM_NOAMMO
        beq @yes
@ammo:  lda weaponinfo + UO_WI_AMMO,x          ; ammo[a] >= count (signed)
        asl a
        tay
        sec
        lda PLR + PL_AMMO_0,y
        sbc PS_CNT
        lda PLR + PL_AMMO_0 + 1,y
        sbc #0
        bvc :+
        eor #$80
:       bpl @yes
        lda #0
        rts
@yes:   lda #1
        rts

        ROUTINE P_CheckAmmo
        FCALL checkAmmo
        rts

; ===========================================================================
; startSound, setMoState
; ===========================================================================
; p_pspr_startSound: S_StartSound(player->mo, A)
        ROUTINE p_pspr_startSound
        ldx PLR + PL_MO
        ldy PLR + PL_MO + 1
        jmp S_StartSound

; setMoState: P_SetMobjState(player->mo, A:X)
        ROUTINE setMoState
        ldy PLR + PL_MO
        sty GA_MO
        ldy PLR + PL_MO + 1
        sty GA_MO+1
        FCALL P_SetMobjState
        rts
