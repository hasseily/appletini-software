; Doom for the Appletini -- the player's tic and the weapons, 6502
; (docs/DESIGN.md sections 9, 10).
;
; The assembly twin of p_user.c and p_pspr.c (the C is the reference,
; compiled on the host; read it for the why): P_PlayerThink with the
; thrust, the view height and bob, the death view, use, weapon change and
; the power counters; the weapon layers (P_SetPsprite, P_MovePsprites..)
; and the weapon actions A_*. The weapon tables (weaponinfo, maxammo,
; clipammo) stay in p_pspr.c, which compiles to data only on the 6502.
;
; There is one player (the C's player_t *p is always &player): its fields
; are read at absolute addresses. The weapon actions take cc65's
; (player_t *, pspdef_t *) arguments and drop the first.

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR


.import set_state, try_move, ret_w, info_ptr, call_ax, cf_ptr
.import w_mov, w_add, w_sub, w_zero, w_cmp, w_sign, w_ldi, w_fix, w_sext
.import w_ldo, w_sto, w_mul, w_tst, w_add3, w_sub3
.import fx_sine, fx_cosine
.import _P_Random, _P_SubRandom, _S_StartSound, _P_NoiseAlert, _P_UseLines
.import _P_PlayerInSpecialSector, _P_AimLineAttack, _P_LineAttack
.import _P_SpawnPlayerMissile, _R_PointToAngle2, _linetarget
.import _player, _leveltime, _sec_special, _st_tics, _st_action, _st_next
.import _weapon_actions, _weaponinfo
.import pushax, pusha, pusheax, incsp2, addysp, w_stp, mul8

.export _P_Thrust, _P_CalcHeight, _P_PlayerThink
.export _P_SetPsprite, _P_BringUpWeapon, _P_CheckAmmo, _P_DropWeapon
.export _P_SetupPsprites, _P_MovePsprites, _bulletslope
.export _A_WeaponReady, _A_ReFire, _A_Lower, _A_Raise, _A_GunFlash, _A_Punch, _A_Saw
.export _A_FireMissile, _A_FirePlasma, _A_FirePistol, _A_FireShotgun, _A_FireCGun
.export _A_Light0, _A_Light1, _A_Light2

PL      = _player
PSW     = _player + PL_PSPRITES                 ; the weapon layer
PSF     = _player + PL_PSPRITES + PS_SIZE       ; the flash layer
ANG5    = $4000 / 18
VIEWH   = 41                                    ; VIEWHEIGHT, map units

.segment "BSS"
onground:       .res 1
_bulletslope:   .res 4
sp_st:          .res 2
pt_angle:       .res 2
gs_dmg:         .res 2
psp_save:       .res 2

.segment "CODE"

; ---- helpers --------------------------------------------------------------------------
; gmo = player.mo
gmo_pl: lda     PL+PL_MO
        sta     gmo
        lda     PL+PL_MO+1
        sta     gmo+1
        rts

; onground = mo->z <= FIX(mo->floorz)
set_onground:
        jsr     gmo_pl
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldy     #MO_FLOORZ+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        phx
        ply
        ldx     #W_T1
        jsr     w_fix
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        stz     onground
        cmp     #1
        beq     :+
        inc     onground
:       rts

; A/X = the fine angle of the BAM16 angle A/X
fine:   stx     tmp1
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        ldx     tmp1
        rts

; A = P_Random() % A (A > 0), by subtraction
random_mod:
        sta     tmp4
        jsr     _P_Random
:       cmp     tmp4
        bcc     :+
        sbc     tmp4
        bra     :-
:       rts

; ptr1 = &weaponinfo[A] (WI_SIZE = 11: A * 8 + A * 2 + A)
wi_ptr: sta     tmp1
        asl     a
        sta     tmp2
        asl     a
        asl     a
        clc
        adc     tmp2
        adc     tmp1
        adc     #<_weaponinfo
        sta     ptr1
        lda     #>_weaponinfo
        adc     #0
        sta     ptr1+1
        rts
.assert WI_SIZE = 11, error, "wi_ptr multiplies by 11"

; A/X = the state at offset Y of the ready weapon's weaponinfo
ready_state:
        phy
        lda     PL+PL_READYWEAPON
        jsr     wi_ptr
        ply
wi_word:
        iny
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        rts

; ---- thrust and view -----------------------------------------------------------------
; void P_Thrust(player_t *p, angle_t angle, fixed_t move)
_P_Thrust:
        sta     W+W_T3
        stx     W+W_T3+1
        lda     sreg
        sta     W+W_T3+2
        lda     sreg+1
        sta     W+W_T3+3
        lda     (sp)
        pha
        ldy     #1
        lda     (sp),y
        tax
        pla
        pha
        phx
        ldy     #4
        jsr     addysp
        plx
        pla
; thrust: the player's momentum += W_T3 along the BAM16 angle A/X
thrust: jsr     fine
        sta     pt_angle
        stx     pt_angle+1
        jsr     fx_cosine
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mul
        jsr     gmo_pl
        ldx     #W_T0
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_FR
        jsr     w_add
        ldx     #W_T0
        ldy     #MO_MOMX
        jsr     w_sto
        lda     pt_angle
        ldx     pt_angle+1
        jsr     fx_sine
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_T0
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_FR
        jsr     w_add
        ldx     #W_T0
        ldy     #MO_MOMY
        jmp     w_sto

; void P_CalcHeight(player_t *p)
_P_CalcHeight:
calc_height:
        jsr     gmo_pl
        ; bob = (momx^2 + momy^2) / 4, at most MAXBOB
        ldx     #W_T0
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T0
        jsr     w_mul
        ldx     #W_T1
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T0
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T0
        jsr     w_mul
        ldx     #W_T1
        ldy     #W_FR
        jsr     w_add
        ldx     #2
:       lda     W+W_T1+3
        cmp     #$80
        ror     W+W_T1+3
        ror     W+W_T1+2
        ror     W+W_T1+1
        ror     W+W_T1
        dex
        bne     :-
        lda     W+W_T1+3
        bmi     @bobok
        bne     @maxbob
        lda     W+W_T1+2
        cmp     #$10
        bcc     @bobok
        bne     @maxbob
        lda     W+W_T1+1
        ora     W+W_T1
        beq     @bobok
@maxbob:
        ldx     #W_T1
        jsr     w_ldi
        .dword  $100000
@bobok: ldx     #3
:       lda     W+W_T1,x
        sta     PL+PL_BOB,x
        dex
        bpl     :-
        ; ceil4 = FIX(ceilingz) - 4 units -> T4
        ldy     #MO_CEILINGZ
        lda     (gmo),y
        sec
        sbc     #4
        pha
        iny
        lda     (gmo),y
        sbc     #0
        tay
        pla
        ldx     #W_T4
        jsr     w_fix
        ; z -> T2
        ldx     #W_T2
        ldy     #MO_Z
        jsr     w_ldo
        lda     PL+PL_CHEATS
        and     #CF_NOMOMENTUM
        bne     @still
        lda     onground
        bne     @bob
@still: ; viewz = z + viewheight (vanilla computes and drops the clipped one)
        ldx     #<-4                    ; (X counts $FC..$FF: inx keeps the carry)
        clc
:       lda     W+W_T2+4-256,x
        adc     PL+PL_VIEWHEIGHT+4-256,x
        sta     PL+PL_VIEWZ+4-256,x
        inx
        bne     :-
        rts
@bob:   ; bob = FixedMul(p->bob / 2, sine((409 * leveltime) & FINEMASK)) -> T3
        lda     _leveltime
        sta     tmp1
        lda     _leveltime+1
        sta     tmp2
        ; 409 = 256 + 128 + 16 + 8 + 1
        lda     tmp1
        sta     ptr1                    ; acc = t
        lda     tmp2
        sta     ptr1+1
        ldx     #3
:       asl     tmp1                    ; t * 8
        rol     tmp2
        dex
        bne     :-
        jsr     @addt                   ; + t * 8
        asl     tmp1
        rol     tmp2
        jsr     @addt                   ; + t * 16
        asl     tmp1
        rol     tmp2
        asl     tmp1
        rol     tmp2
        asl     tmp1
        rol     tmp2
        jsr     @addt                   ; + t * 128
        asl     tmp1
        rol     tmp2
        jsr     @addt                   ; + t * 256
        lda     ptr1+1
        and     #$1F
        tax
        lda     ptr1
        jsr     fx_sine
        ldx     #W_T0
        ldy     #W_T1                   ; the new bob
        jsr     w_mov
        lsr     W+W_T0+3                ; / 2 (>= 0)
        ror     W+W_T0+2
        ror     W+W_T0+1
        ror     W+W_T0
        ldx     #W_T0
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mov
        lda     PL+PL_PLAYERSTATE
        cmp     #PST_LIVE
        jne     @viewz
        ; viewheight += deltaviewheight
        clc
        ldx     #<-4
:       lda     PL+PL_VIEWHEIGHT+4-256,x
        adc     PL+PL_DELTAVIEWHEIGHT+4-256,x
        sta     PL+PL_VIEWHEIGHT+4-256,x
        inx
        bne     :-
        ; > VIEWHEIGHT: VIEWHEIGHT, no delta
        lda     PL+PL_VIEWHEIGHT+3
        bmi     @notover
        bne     @over
        lda     PL+PL_VIEWHEIGHT+2
        cmp     #VIEWH
        bcc     @notover
        bne     @over
        lda     PL+PL_VIEWHEIGHT+1
        ora     PL+PL_VIEWHEIGHT
        beq     @notover
@over:  stz     PL+PL_VIEWHEIGHT
        stz     PL+PL_VIEWHEIGHT+1
        lda     #VIEWH
        sta     PL+PL_VIEWHEIGHT+2
        stz     PL+PL_VIEWHEIGHT+3
        stz     PL+PL_DELTAVIEWHEIGHT
        stz     PL+PL_DELTAVIEWHEIGHT+1
        stz     PL+PL_DELTAVIEWHEIGHT+2
        stz     PL+PL_DELTAVIEWHEIGHT+3
@notover:
        ; < VIEWHEIGHT / 2 ($148000): that, and the delta at least 1
        lda     PL+PL_VIEWHEIGHT+3
        bmi     @under
        bne     @notunder
        lda     PL+PL_VIEWHEIGHT+2
        cmp     #$14
        bcc     @under
        bne     @notunder
        lda     PL+PL_VIEWHEIGHT+1
        cmp     #$80
        bcs     @notunder
@under: stz     PL+PL_VIEWHEIGHT
        lda     #$80
        sta     PL+PL_VIEWHEIGHT+1
        lda     #$14
        sta     PL+PL_VIEWHEIGHT+2
        stz     PL+PL_VIEWHEIGHT+3
        lda     PL+PL_DELTAVIEWHEIGHT+3
        bmi     @one
        ora     PL+PL_DELTAVIEWHEIGHT+2
        ora     PL+PL_DELTAVIEWHEIGHT+1
        ora     PL+PL_DELTAVIEWHEIGHT
        bne     @notunder
@one:   lda     #1
        sta     PL+PL_DELTAVIEWHEIGHT
        stz     PL+PL_DELTAVIEWHEIGHT+1
        stz     PL+PL_DELTAVIEWHEIGHT+2
        stz     PL+PL_DELTAVIEWHEIGHT+3
@notunder:
        ; a delta grows by FRACUNIT / 4 (and is never 0 on the way)
        lda     PL+PL_DELTAVIEWHEIGHT
        ora     PL+PL_DELTAVIEWHEIGHT+1
        ora     PL+PL_DELTAVIEWHEIGHT+2
        ora     PL+PL_DELTAVIEWHEIGHT+3
        beq     @viewz
        clc
        lda     PL+PL_DELTAVIEWHEIGHT+1
        adc     #$40
        sta     PL+PL_DELTAVIEWHEIGHT+1
        bcc     :+
        inc     PL+PL_DELTAVIEWHEIGHT+2
        bne     :+
        inc     PL+PL_DELTAVIEWHEIGHT+3
:       lda     PL+PL_DELTAVIEWHEIGHT
        ora     PL+PL_DELTAVIEWHEIGHT+1
        ora     PL+PL_DELTAVIEWHEIGHT+2
        ora     PL+PL_DELTAVIEWHEIGHT+3
        bne     @viewz
        inc     PL+PL_DELTAVIEWHEIGHT
@viewz: ; viewz = z + viewheight + bob, at most ceil4
        ldx     #<-4
        clc
:       lda     W+W_T2+4-256,x
        adc     PL+PL_VIEWHEIGHT+4-256,x
        sta     W+W_T2+4-256,x
        inx
        bne     :-
        ldx     #W_T2
        ldy     #W_T3
        jsr     w_add
        ldx     #W_T2
        ldy     #W_T4
        jsr     w_cmp
        cmp     #1
        bne     :+
        ldx     #W_T2
        ldy     #W_T4
        jsr     w_mov
:       ldx     #3
:       lda     W+W_T2,x
        sta     PL+PL_VIEWZ,x
        dex
        bpl     :-
        rts
; ptr1 += tmp2:tmp1
@addt:  clc
        lda     ptr1
        adc     tmp1
        sta     ptr1
        lda     ptr1+1
        adc     tmp2
        sta     ptr1+1
        rts

; ---- the player's tic -------------------------------------------------------------------
move_player:
        jsr     gmo_pl
        ; mo->angle += cmd.angleturn
        ldy     #MO_ANGLE
        clc
        lda     (gmo),y
        adc     PL+PL_CMD+TC_ANGLETURN
        sta     (gmo),y
        iny
        lda     (gmo),y
        adc     PL+PL_CMD+TC_ANGLETURN+1
        sta     (gmo),y
        jsr     set_onground
        lda     onground
        beq     @run
        lda     PL+PL_CMD+TC_FORWARDMOVE
        beq     @side
        jsr     move_t3
        ldy     #MO_ANGLE+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        jsr     thrust
@side:  lda     PL+PL_CMD+TC_SIDEMOVE
        beq     @run
        jsr     move_t3
        jsr     gmo_pl
        ldy     #MO_ANGLE
        lda     (gmo),y
        iny
        sec                             ; angle - ANG90
        pha
        lda     (gmo),y
        sbc     #$40
        tax
        pla
        jsr     thrust
@run:   lda     PL+PL_CMD+TC_FORWARDMOVE
        ora     PL+PL_CMD+TC_SIDEMOVE
        beq     @rts
        jsr     gmo_pl
        ldy     #MO_STATE
        lda     (gmo),y
        cmp     #<S_PLAY
        bne     @rts
        iny
        lda     (gmo),y
        cmp     #>S_PLAY
        bne     @rts
        lda     #<S_PLAY_RUN1
        ldx     #>S_PLAY_RUN1
        jmp     set_state
@rts:   rts

; W_T3 = (int8 A) * 2048
move_t3:
        ldy     #0
        cmp     #$80
        bcc     :+
        dey
:       ldx     #W_T3
        jsr     w_sext
        ldx     #11
:       asl     W+W_T3
        rol     W+W_T3+1
        rol     W+W_T3+2
        rol     W+W_T3+3
        dex
        bne     :-
        rts

death_think:
        jsr     move_psprites
        ; fall to the ground: viewheight -1 unit down to 6 units
        lda     PL+PL_VIEWHEIGHT+3
        bmi     @low
        bne     @high
        lda     PL+PL_VIEWHEIGHT+2
        cmp     #6
        bcc     @low
        bne     @high
        lda     PL+PL_VIEWHEIGHT+1
        ora     PL+PL_VIEWHEIGHT
        beq     @six
@high:  lda     PL+PL_VIEWHEIGHT+2
        bne     :+
        dec     PL+PL_VIEWHEIGHT+3
:       dec     PL+PL_VIEWHEIGHT+2
        ; below 6 units now?
        lda     PL+PL_VIEWHEIGHT+3
        bne     @six
        lda     PL+PL_VIEWHEIGHT+2
        cmp     #6
        bcs     @six
@low:   stz     PL+PL_VIEWHEIGHT
        stz     PL+PL_VIEWHEIGHT+1
        lda     #6
        sta     PL+PL_VIEWHEIGHT+2
        stz     PL+PL_VIEWHEIGHT+3
@six:   stz     PL+PL_DELTAVIEWHEIGHT
        stz     PL+PL_DELTAVIEWHEIGHT+1
        stz     PL+PL_DELTAVIEWHEIGHT+2
        stz     PL+PL_DELTAVIEWHEIGHT+3
        jsr     set_onground
        jsr     calc_height
        ; turn to the killer
        lda     PL+PL_ATTACKER
        ora     PL+PL_ATTACKER+1
        jeq     @fade
        lda     PL+PL_ATTACKER
        cmp     PL+PL_MO
        bne     @turn
        lda     PL+PL_ATTACKER+1
        cmp     PL+PL_MO+1
        jeq     @fade
@turn:  jsr     gmo_pl
        ldx     #W_T0
        ldy     #MO_X
        jsr     push_mo_field
        ldy     #MO_Y
        jsr     push_mo_field
        lda     PL+PL_ATTACKER
        sta     gmo
        lda     PL+PL_ATTACKER+1
        sta     gmo+1
        ldy     #MO_X
        jsr     push_mo_field
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        jsr     ret_w
        jsr     _R_PointToAngle2
        sta     pt_angle
        stx     pt_angle+1
        jsr     gmo_pl
        ; delta = angle - mo->angle
        ldy     #MO_ANGLE
        sec
        lda     pt_angle
        sbc     (gmo),y
        sta     tmp1
        iny
        lda     pt_angle+1
        sbc     (gmo),y
        sta     tmp2
        ; delta < ANG5 or delta > -ANG5: face it
        lda     tmp1
        cmp     #<ANG5
        lda     tmp2
        sbc     #>ANG5
        bcc     @face
        lda     #<(-ANG5)
        cmp     tmp1
        lda     #>(-ANG5)
        sbc     tmp2
        bcc     @face
        lda     tmp2
        bmi     @left                   ; delta >= ANG180
        ldy     #MO_ANGLE
        clc
        lda     (gmo),y
        adc     #<ANG5
        sta     (gmo),y
        iny
        lda     (gmo),y
        adc     #>ANG5
        sta     (gmo),y
        bra     @use
@left:  ldy     #MO_ANGLE
        sec
        lda     (gmo),y
        sbc     #<ANG5
        sta     (gmo),y
        iny
        lda     (gmo),y
        sbc     #>ANG5
        sta     (gmo),y
        bra     @use
@face:  ldy     #MO_ANGLE
        lda     pt_angle
        sta     (gmo),y
        iny
        lda     pt_angle+1
        sta     (gmo),y
@fade:  lda     PL+PL_DAMAGECOUNT
        beq     @use
        dec     PL+PL_DAMAGECOUNT
@use:   lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_USE
        beq     :+
        lda     #PST_REBORN
        sta     PL+PL_PLAYERSTATE
:       rts

; push the fixed_t at (gmo)+Y on the C stack (X = a W scratch slot)
push_mo_field:
        ldx     #W_T0
        jsr     w_ldo
        ldx     #W_T0
        jsr     ret_w
        jmp     pusheax

; void P_PlayerThink(player_t *p)
_P_PlayerThink:
        lda     PL+PL_MO
        ora     PL+PL_MO+1
        bne     :+
        rts
:       jsr     gmo_pl
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #<~MF1_NOCLIP
        sta     (gmo),y
        lda     PL+PL_CHEATS
        and     #CF_NOCLIP
        beq     :+
        lda     (gmo),y
        ora     #MF1_NOCLIP
        sta     (gmo),y
:       ; the chainsaw's run forward
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_JUSTATTACKED
        beq     :+
        lda     (gmo),y
        and     #<~MF0_JUSTATTACKED
        sta     (gmo),y
        stz     PL+PL_CMD+TC_ANGLETURN
        stz     PL+PL_CMD+TC_ANGLETURN+1
        lda     #$C800 / 512
        sta     PL+PL_CMD+TC_FORWARDMOVE
        stz     PL+PL_CMD+TC_SIDEMOVE
:       lda     PL+PL_PLAYERSTATE
        cmp     #PST_DEAD
        bne     :+
        jmp     death_think
:       ; frozen after a teleport
        ldy     #MO_REACTIONTIME
        lda     (gmo),y
        beq     :+
        dec     a
        sta     (gmo),y
        bra     :++
:       jsr     move_player
:       jsr     calc_height
        ; a special sector
        jsr     gmo_pl
        ldy     #MO_SECTOR
        lda     (gmo),y
        clc
        adc     _sec_special
        sta     ptr1
        iny
        lda     (gmo),y
        adc     _sec_special+1
        sta     ptr1+1
        lda     (ptr1)
        beq     :+
        lda     #<PL
        ldx     #>PL
        jsr     _P_PlayerInSpecialSector
:       ; a weapon change
        lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_CHANGE
        beq     @use
        lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_WEAPONMASK
        lsr     a
        lsr     a
        lsr     a
        .assert BT_WEAPONSHIFT = 3, error, "the weapon bits"
        bne     @owned                  ; not the fist
        ldx     PL+PL_WEAPONOWNED+wp_chainsaw
        beq     @owned
        ; the fist key gives the chainsaw, unless it is out with strength
        ldx     PL+PL_READYWEAPON
        cpx     #wp_chainsaw
        bne     @saw
        ldx     PL+PL_POWERS+2*pw_strength
        bne     @owned
        ldx     PL+PL_POWERS+2*pw_strength+1
        bne     @owned
@saw:   lda     #wp_chainsaw
@owned: cmp     #NUMWEAPONS
        bcs     @use
        tax
        lda     PL+PL_WEAPONOWNED,x
        beq     @use
        cpx     PL+PL_READYWEAPON
        beq     @use
        stx     PL+PL_PENDINGWEAPON
@use:   lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_USE
        beq     @nouse
        lda     PL+PL_USEDOWN
        bne     @psp
        lda     #<PL
        ldx     #>PL
        jsr     _P_UseLines
        lda     #1
        sta     PL+PL_USEDOWN
        bra     @psp
@nouse: stz     PL+PL_USEDOWN
@psp:   jsr     move_psprites
        ; the power counters
        ldx     #2*pw_strength
        jsr     power_zero
        beq     :+
        inc     PL+PL_POWERS+2*pw_strength
        bne     :+
        inc     PL+PL_POWERS+2*pw_strength+1
:       ldx     #2*pw_invulnerability
        jsr     power_dec
        ldx     #2*pw_invisibility
        jsr     power_dec
        bcc     :+
        bne     :+
        jsr     gmo_pl                  ; visible again
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #<~MF2_SHADOW
        sta     (gmo),y
:       ldx     #2*pw_infrared
        jsr     power_dec
        ldx     #2*pw_ironfeet
        jsr     power_dec
        lda     PL+PL_DAMAGECOUNT
        beq     :+
        dec     PL+PL_DAMAGECOUNT
:       lda     PL+PL_BONUSCOUNT
        beq     :+
        dec     PL+PL_BONUSCOUNT
:       ; the colormaps
        ldx     #2*pw_invulnerability
        jsr     power_zero
        beq     @infra
        ldy     #32                     ; INVERSECOLORMAP
        bra     @blink
@infra: ldx     #2*pw_infrared
        jsr     power_zero
        beq     @none
        ldy     #1
@blink: ; > 4 * 32 tics left, or the blink's on phase
        lda     PL+PL_POWERS+1,x
        bne     @on
        lda     PL+PL_POWERS,x
        cmp     #4*32+1
        bcs     @on
        and     #8
        bne     @on
@none:  ldy     #0
@on:    sty     PL+PL_FIXEDCOLORMAP
        rts

; Z clear iff powers[X/2] != 0
power_zero:
        lda     PL+PL_POWERS,x
        ora     PL+PL_POWERS+1,x
        rts

; powers[X/2]-- if it is not 0: C set if it counted, Z set if it hit 0
power_dec:
        jsr     power_zero
        clc
        beq     @rts
        lda     PL+PL_POWERS,x
        bne     :+
        dec     PL+PL_POWERS+1,x
:       dec     PL+PL_POWERS,x
        jsr     power_zero
        sec
@rts:   rts

; ---- the weapon layers -----------------------------------------------------------------------
; gpt = &player.psprites[X]
psp_ptr:
        lda     #<PSW
        cpx     #0
        beq     :+
        lda     #<PSF
:       sta     gpt
        lda     #>PSW
        cpx     #0
        beq     :+
        lda     #>PSF
:       sta     gpt+1
        rts

; void P_SetPsprite(player_t *p, uint8_t position, uint16_t stnum)
_P_SetPsprite:
        pha
        phx
        lda     (sp)                    ; the position
        tax
        jsr     incsp2_1
        ply
        pla
        bra     set_psprite
incsp2_1:
        ldy     #3                      ; position (1) + player (2)
        jmp     addysp

; set_psprite: layer X to the state A/Y (lo/hi), on through the zero-tic
; states and their actions
set_psprite:
        sta     sp_st
        sty     sp_st+1
        phx
@loop:  plx
        phx
        jsr     psp_ptr
        lda     sp_st
        ora     sp_st+1
        bne     @live
        lda     #0                      ; off
        sta     (gpt)
        ldy     #PS_STATE+1
        sta     (gpt),y
        jmp     @done
@live:  lda     sp_st
        sta     (gpt)
        ldy     #PS_STATE+1
        lda     sp_st+1
        sta     (gpt),y
        clc
        lda     sp_st
        adc     #<_st_tics
        sta     ptr1
        lda     sp_st+1
        adc     #>_st_tics
        sta     ptr1+1
        lda     (ptr1)
        ldy     #PS_TICS
        sta     (gpt),y
        clc
        lda     sp_st
        adc     #<_st_action
        sta     ptr1
        lda     sp_st+1
        adc     #>_st_action
        sta     ptr1+1
        lda     (ptr1)
        and     #$7F
        beq     @next
        ; weapon_actions[ac - AC_FIRST_WEAPON](&player, psp)
        sec
        sbc     #AC_FIRST_WEAPON
        asl     a
        tay
        lda     _weapon_actions,y
        sta     cf_ptr
        lda     _weapon_actions+1,y
        sta     cf_ptr+1
        lda     #<PL
        ldx     #>PL
        jsr     pushax
        lda     gpt
        ldx     gpt+1
        jsr     call_ax
        plx
        phx
        jsr     psp_ptr
        lda     (gpt)
        ldy     #PS_STATE+1
        ora     (gpt),y
        beq     @done                   ; the action turned it off
@next:  ; stnum = st_next[psp->state]
        lda     (gpt)
        asl     a
        sta     ptr1
        ldy     #PS_STATE+1
        lda     (gpt),y
        rol     a
        sta     ptr1+1
        clc
        lda     ptr1
        adc     #<_st_next
        sta     ptr1
        lda     ptr1+1
        adc     #>_st_next
        sta     ptr1+1
        lda     (ptr1)
        sta     sp_st
        ldy     #1
        lda     (ptr1),y
        sta     sp_st+1
        ldy     #PS_TICS
        lda     (gpt),y
        jeq     @loop
@done:  plx
        rts

; void P_MovePsprites(player_t *p)
_P_MovePsprites:
move_psprites:
        ldx     #0
        jsr     @one
        ldx     #1
        jsr     @one
        ldx     #7
:       lda     PSW+PS_SX,x             ; the flash follows the weapon (sx, sy)
        sta     PSF+PS_SX,x
        dex
        bpl     :-
        rts
@one:   jsr     psp_ptr
        lda     (gpt)
        ldy     #PS_STATE+1
        ora     (gpt),y
        beq     @rts
        ldy     #PS_TICS
        lda     (gpt),y
        cmp     #ST_FOREVER
        beq     @rts
        dec     a
        sta     (gpt),y
        bne     @rts
        lda     (gpt)
        asl     a
        sta     ptr1
        ldy     #PS_STATE+1
        lda     (gpt),y
        rol     a
        sta     ptr1+1
        clc
        lda     ptr1
        adc     #<_st_next
        sta     ptr1
        lda     ptr1+1
        adc     #>_st_next
        sta     ptr1+1
        ldy     #1
        lda     (ptr1),y
        tay
        lda     (ptr1)
        jmp     set_psprite
@rts:   rts
.assert PS_SY = PS_SX + 4, error, "sx and sy copied at once"

; the weapon layer to the ready weapon's state at weaponinfo offset Y
weapon_to:
        jsr     ready_state
        phx
        ply
        ldx     #ps_weapon
        jmp     set_psprite

; void P_BringUpWeapon(player_t *p)
_P_BringUpWeapon:
bring_up:
        lda     PL+PL_PENDINGWEAPON
        cmp     #wp_nochange
        bne     :+
        lda     PL+PL_READYWEAPON
        sta     PL+PL_PENDINGWEAPON
:       cmp     #wp_chainsaw
        bne     :+
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     #sfx_sawup
        jsr     _S_StartSound
:       lda     PL+PL_PENDINGWEAPON
        jsr     wi_ptr
        lda     #wp_nochange
        sta     PL+PL_PENDINGWEAPON
        stz     PSW+PS_SY
        stz     PSW+PS_SY+1
        lda     #128                    ; WEAPONBOTTOM
        sta     PSW+PS_SY+2
        stz     PSW+PS_SY+3
        ldy     #WI_UPSTATE
        jsr     wi_word
        phx
        ply
        ldx     #ps_weapon
        jmp     set_psprite

; boolean P_CheckAmmo(player_t *p)
_P_CheckAmmo:
check_ammo:
        lda     PL+PL_READYWEAPON
        jsr     wi_ptr
        lda     (ptr1)                  ; WI_AMMO = 0
        cmp     #am_noammo
        beq     @yes
        asl     a
        tax
        lda     PL+PL_AMMO+1,x
        bmi     @out
        ora     PL+PL_AMMO,x
        bne     @yes
@out:   ; pick the weapon to change to, in vanilla's order
        ldy     #wp_plasma
        ldx     #2*am_cell
        jsr     @has
        bne     @pick
        ldy     #wp_chaingun
        ldx     #2*am_clip
        jsr     @has
        bne     @pick
        ldy     #wp_shotgun
        ldx     #2*am_shell
        jsr     @has
        bne     @pick
        ldy     #wp_pistol
        lda     PL+PL_AMMO+2*am_clip
        ora     PL+PL_AMMO+2*am_clip+1
        bne     @pick
        ldy     #wp_chainsaw
        lda     PL+PL_WEAPONOWNED+wp_chainsaw
        bne     @pick
        ldy     #wp_missile
        ldx     #2*am_misl
        jsr     @has
        bne     @pick
        ldy     #wp_fist
@pick:  sty     PL+PL_PENDINGWEAPON
        ldy     #WI_DOWNSTATE
        jsr     weapon_to
        lda     #0
        tax
        rts
@yes:   lda     #1
        ldx     #0
        rts
; Z clear iff the weapon Y is owned and has ammo X/2
@has:   lda     PL+PL_WEAPONOWNED,y
        beq     :+
        lda     PL+PL_AMMO,x
        ora     PL+PL_AMMO+1,x
:       rts

fire_weapon:
        jsr     check_ammo
        cmp     #0
        beq     @rts
        jsr     gmo_pl
        lda     #<S_PLAY_ATK1
        ldx     #>S_PLAY_ATK1
        jsr     set_state
        ldy     #WI_ATKSTATE
        jsr     weapon_to
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        jmp     _P_NoiseAlert
@rts:   rts

; void P_DropWeapon(player_t *p)
_P_DropWeapon:
        ldy     #WI_DOWNSTATE
        jmp     weapon_to

; void P_SetupPsprites(player_t *p)
_P_SetupPsprites:
        stz     PSW+PS_STATE
        stz     PSW+PS_STATE+1
        stz     PSF+PS_STATE
        stz     PSF+PS_STATE+1
        lda     PL+PL_READYWEAPON
        sta     PL+PL_PENDINGWEAPON
        jmp     bring_up

; ---- the weapon actions: (player_t *p, pspdef_t *psp) ------------------------------------------
; gpt = psp (A/X), the player dropped from the C stack
action_args:
        sta     gpt
        stx     gpt+1
        jmp     incsp2

; the player's mobj to a state
mo_state:
        pha
        phx
        jsr     gmo_pl
        plx
        pla
        jmp     set_state

_A_WeaponReady:
        jsr     action_args
        lda     gpt
        pha
        lda     gpt+1
        pha
        ; the player's own sprite leaves its attack frames
        jsr     gmo_pl
        ldy     #MO_STATE+1
        lda     (gmo),y
        bne     @notatk
        dey
        lda     (gmo),y
        cmp     #S_PLAY_ATK1
        beq     :+
        cmp     #S_PLAY_ATK2
        bne     @notatk
:       lda     #<S_PLAY
        ldx     #>S_PLAY
        jsr     set_state
@notatk:
        pla
        sta     gpt+1
        pla
        sta     gpt
        lda     PL+PL_READYWEAPON
        cmp     #wp_chainsaw
        bne     @nosaw
        lda     (gpt)
        cmp     #<S_SAW
        bne     @nosaw
        ldy     #PS_STATE+1
        lda     (gpt),y
        cmp     #>S_SAW
        bne     @nosaw
        lda     gpt
        pha
        lda     gpt+1
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     #sfx_sawidl
        jsr     _S_StartSound
        pla
        sta     gpt+1
        pla
        sta     gpt
@nosaw: ; put the weapon away when it changes or the player dies
        lda     PL+PL_PENDINGWEAPON
        cmp     #wp_nochange
        bne     @down
        lda     PL+PL_HEALTH
        ora     PL+PL_HEALTH+1
        bne     @fire
@down:  ldy     #WI_DOWNSTATE
        jmp     weapon_to
@fire:  lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_ATTACK
        beq     @up
        lda     PL+PL_ATTACKDOWN
        beq     @shoot
        lda     PL+PL_READYWEAPON
        cmp     #wp_missile
        beq     @bob
        cmp     #wp_bfg
        beq     @bob
@shoot: lda     #1
        sta     PL+PL_ATTACKDOWN
        jmp     fire_weapon
@up:    stz     PL+PL_ATTACKDOWN
@bob:   ; sx = FRACUNIT + FixedMul(bob, cos(a)), sy = WEAPONTOP + FixedMul(bob,
        ; sin(a & 4095)), a = (128 * leveltime) & FINEMASK
        lda     gpt
        sta     psp_save
        lda     gpt+1
        sta     psp_save+1
        lda     _leveltime
        lsr     a
        lda     #0
        ror     a
        sta     pt_angle                ; (leveltime & 1) << 7
        lda     _leveltime
        lsr     a
        and     #$1F
        sta     pt_angle+1              ; (leveltime >> 1) & 31
        ldx     #3
:       lda     PL+PL_BOB,x
        sta     W+W_T0,x
        dex
        bpl     :-
        lda     pt_angle
        ldx     pt_angle+1
        jsr     fx_cosine
        ldx     #W_T0
        ldy     #W_FR
        jsr     w_mul
        inc     W+W_FR+2                ; + FRACUNIT
        bne     :+
        inc     W+W_FR+3
:       jsr     psp_back
        ldx     #W_FR
        ldy     #PS_SX
        jsr     w_stp
        lda     pt_angle+1
        and     #$0F
        tax
        lda     pt_angle
        jsr     fx_sine
        ldx     #W_T0
        ldy     #W_FR
        jsr     w_mul
        clc
        lda     W+W_FR+2
        adc     #32                     ; WEAPONTOP
        sta     W+W_FR+2
        bcc     :+
        inc     W+W_FR+3
:       jsr     psp_back
        ldx     #W_FR
        ldy     #PS_SY
        jmp     w_stp
psp_back:
        lda     psp_save
        sta     gpt
        lda     psp_save+1
        sta     gpt+1
        rts

_A_ReFire:
        jsr     action_args
        lda     PL+PL_CMD+TC_BUTTONS
        and     #BT_ATTACK
        beq     @no
        lda     PL+PL_PENDINGWEAPON
        cmp     #wp_nochange
        bne     @no
        lda     PL+PL_HEALTH
        ora     PL+PL_HEALTH+1
        beq     @no
        inc     PL+PL_REFIRE
        jmp     fire_weapon
@no:    stz     PL+PL_REFIRE
        jmp     check_ammo

_A_Lower:
        jsr     action_args
        clc
        ldy     #PS_SY+2
        lda     (gpt),y
        adc     #6                      ; LOWERSPEED
        sta     (gpt),y
        iny
        lda     (gpt),y
        adc     #0
        sta     (gpt),y
        ; below WEAPONBOTTOM: not yet
        bmi     @rts
        bne     @bottom
        dey
        lda     (gpt),y
        cmp     #128
        bcc     @rts
@bottom:
        lda     PL+PL_PLAYERSTATE
        cmp     #PST_DEAD
        bne     :+
        ldy     #PS_SY                  ; the weapon stays down
        lda     #0
        sta     (gpt),y
        iny
        sta     (gpt),y
        iny
        lda     #128
        sta     (gpt),y
        iny
        lda     #0
        sta     (gpt),y
        rts
:       lda     PL+PL_HEALTH
        ora     PL+PL_HEALTH+1
        bne     :+
        lda     #0
        tay
        ldx     #ps_weapon
        jmp     set_psprite
:       lda     PL+PL_PENDINGWEAPON
        sta     PL+PL_READYWEAPON
        jmp     bring_up
@rts:   rts

_A_Raise:
        jsr     action_args
        sec
        ldy     #PS_SY+2
        lda     (gpt),y
        sbc     #6                      ; RAISESPEED
        sta     (gpt),y
        iny
        lda     (gpt),y
        sbc     #0
        sta     (gpt),y
        ; above WEAPONTOP: not yet
        bmi     @top
        bne     @rts
        dey
        lda     (gpt),y
        cmp     #32
        bcc     @top
        bne     @rts
        ldy     #PS_SY+1
        lda     (gpt),y
        dey
        ora     (gpt),y
        bne     @rts
@top:   ldy     #PS_SY
        lda     #0
        sta     (gpt),y
        iny
        sta     (gpt),y
        iny
        lda     #32
        sta     (gpt),y
        iny
        lda     #0
        sta     (gpt),y
        ldy     #WI_READYSTATE
        jmp     weapon_to
@rts:   rts

_A_GunFlash:
        jsr     action_args
        lda     #<S_PLAY_ATK2
        ldx     #>S_PLAY_ATK2
        jsr     mo_state
flash:  ldy     #WI_FLASHSTATE
        jsr     ready_state
flash_ax:
        phx
        ply
        ldx     #ps_flash
        jmp     set_psprite

; the ammo of the ready weapon -= 1
decrease_ammo:
        lda     PL+PL_READYWEAPON
        jsr     wi_ptr
        lda     (ptr1)
        asl     a
        tax
        lda     PL+PL_AMMO,x
        bne     :+
        dec     PL+PL_AMMO+1,x
:       dec     PL+PL_AMMO,x
        rts

; pt_angle = mo->angle + (P_SubRandom() << 2)
spread_angle:
        jsr     _P_SubRandom
        stx     tmp2
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        pha
        jsr     gmo_pl
        pla
        ldy     #MO_ANGLE
        clc
        adc     (gmo),y
        sta     pt_angle
        iny
        lda     tmp2
        adc     (gmo),y
        sta     pt_angle+1
        rts

; P_AimLineAttack(mo, pt_angle, A * FRACUNIT) -> W_T4 (and on to the attack)
aim_melee:
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        pla
        sta     sreg
        stz     sreg+1
        lda     #0
        tax
        jsr     _P_AimLineAttack
        sta     W+W_T4
        stx     W+W_T4+1
        lda     sreg
        sta     W+W_T4+2
        lda     sreg+1
        sta     W+W_T4+3
        rts

; P_LineAttack(mo, pt_angle, A.X units (whole, fraction byte 1), W_T4, gs_dmg)
line_attack:
        pha
        phx
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        plx
        pla
        sta     sreg
        stz     sreg+1
        lda     #0
        jsr     pusheax
        ldx     #W_T4
        jsr     ret_w
        jsr     pusheax
        lda     gs_dmg
        ldx     gs_dmg+1
        jmp     _P_LineAttack

; mo->angle = R_PointToAngle2(mo->x, mo->y, linetarget->x, linetarget->y) -> A/X
angle_to_target:
        jsr     gmo_pl
        ldy     #MO_X
        jsr     push_mo_field
        ldy     #MO_Y
        jsr     push_mo_field
        lda     _linetarget
        sta     gmo
        lda     _linetarget+1
        sta     gmo+1
        ldy     #MO_X
        jsr     push_mo_field
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        jsr     ret_w
        jmp     _R_PointToAngle2

; S_StartSound(player.mo, A)
pl_sound:
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        pla
        jmp     _S_StartSound

_A_Punch:
        jsr     action_args
        lda     #10
        jsr     random_mod
        inc     a
        asl     a
        sta     gs_dmg
        stz     gs_dmg+1
        lda     PL+PL_POWERS+2*pw_strength
        ora     PL+PL_POWERS+2*pw_strength+1
        beq     :+
        lda     gs_dmg                  ; * 10
        ldx     #10
        jsr     mul8
        sta     gs_dmg
        stx     gs_dmg+1
:       jsr     spread_angle
        lda     #64                     ; MELEERANGE
        jsr     aim_melee
        lda     #64
        ldx     #0
        jsr     line_attack
        lda     _linetarget
        ora     _linetarget+1
        beq     @rts
        lda     #sfx_punch
        jsr     pl_sound
        jsr     angle_to_target
        pha
        jsr     gmo_pl
        pla
        ldy     #MO_ANGLE
        sta     (gmo),y
        iny
        txa
        sta     (gmo),y
@rts:   rts

_A_Saw:
        jsr     action_args
        lda     #10
        jsr     random_mod
        inc     a
        asl     a
        sta     gs_dmg
        stz     gs_dmg+1
        jsr     spread_angle
        ; MELEERANGE + 1: the puff doesn't skip the flash
        lda     #64
        jsr     aim_melee_1
        lda     #64
        ldx     #1
        jsr     line_attack_1
        lda     _linetarget
        ora     _linetarget+1
        bne     :+
        lda     #sfx_sawful
        jmp     pl_sound
:       lda     #sfx_sawhit
        jsr     pl_sound
        ; turn to face the target
        jsr     angle_to_target
        sta     pt_angle
        stx     pt_angle+1
        jsr     gmo_pl
        ldy     #MO_ANGLE
        sec
        lda     pt_angle
        sbc     (gmo),y
        sta     tmp1
        iny
        lda     pt_angle+1
        sbc     (gmo),y
        sta     tmp2                    ; d = angle - mo->angle
        ; d > ANG180 (unsigned)
        cmp     #$80
        bcc     @right
        bne     @left
        lda     tmp1
        beq     @right
@left:  ; (int16) d < -(ANG90 / 20): angle + ANG90 / 21, else mo->angle - ANG90 / 20
        lda     tmp1
        cmp     #<(-($4000 / 20))
        lda     tmp2
        sbc     #>(-($4000 / 20))
        bvc     :+
        eor     #$80
:       bpl     @nudgel
        clc
        lda     pt_angle
        adc     #<($4000 / 21)
        tax
        lda     pt_angle+1
        adc     #>($4000 / 21)
        bra     @set
@nudgel:
        ldy     #MO_ANGLE
        sec
        lda     (gmo),y
        sbc     #<($4000 / 20)
        tax
        iny
        lda     (gmo),y
        sbc     #>($4000 / 20)
        bra     @set
@right: ; d > ANG90 / 20: angle - ANG90 / 21, else mo->angle + ANG90 / 20
        lda     #<($4000 / 20)
        cmp     tmp1
        lda     #>($4000 / 20)
        sbc     tmp2
        bcs     @nudger
        sec
        lda     pt_angle
        sbc     #<($4000 / 21)
        tax
        lda     pt_angle+1
        sbc     #>($4000 / 21)
        bra     @set
@nudger:
        ldy     #MO_ANGLE
        clc
        lda     (gmo),y
        adc     #<($4000 / 20)
        tax
        iny
        lda     (gmo),y
        adc     #>($4000 / 20)
@set:   ldy     #MO_ANGLE+1
        sta     (gmo),y
        dey
        txa
        sta     (gmo),y
        ldy     #MO_FLAGS
        lda     (gmo),y
        ora     #MF0_JUSTATTACKED
        sta     (gmo),y
        rts

; aim / attack at A units + 1/65536 (the chainsaw's MELEERANGE + 1)
aim_melee_1:
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        pla
        sta     sreg
        stz     sreg+1
        lda     #1
        ldx     #0
        jsr     _P_AimLineAttack
        sta     W+W_T4
        stx     W+W_T4+1
        lda     sreg
        sta     W+W_T4+2
        lda     sreg+1
        sta     W+W_T4+3
        rts
line_attack_1:
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        pla
        sta     sreg
        stz     sreg+1
        lda     #1
        ldx     #0
        jsr     pusheax
        ldx     #W_T4
        jsr     ret_w
        jsr     pusheax
        lda     gs_dmg
        ldx     gs_dmg+1
        jmp     _P_LineAttack

_A_FireMissile:
        jsr     action_args
        jsr     decrease_ammo
        lda     #MT_ROCKET
missile:
        pha
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        pla
        jmp     _P_SpawnPlayerMissile

_A_FirePlasma:
        jsr     action_args
        jsr     decrease_ammo
        jsr     _P_Random
        and     #1
        sta     tmp3
        ldy     #WI_FLASHSTATE
        jsr     ready_state
        clc
        adc     tmp3
        bcc     :+
        inx
:       jsr     flash_ax
        lda     #MT_PLASMA
        bra     missile

; bulletslope = the autoaim at 16 * 64 units, tried at the angle, then
; 1 << 10 left and right of it
bullet_slope:
        jsr     gmo_pl
        ldy     #MO_ANGLE
        lda     (gmo),y
        sta     pt_angle
        iny
        lda     (gmo),y
        sta     pt_angle+1
        jsr     @aim
        bne     @rts
        clc
        lda     pt_angle+1
        adc     #>(1 << 10)
        sta     pt_angle+1
        jsr     @aim
        bne     @rts
        sec
        lda     pt_angle+1
        sbc     #>(2 << 10)
        sta     pt_angle+1
@aim:   lda     #0                      ; 1024 units = $04000000
        sta     tmp4
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        lda     #0
        sta     sreg
        lda     #4
        sta     sreg+1
        lda     #0
        tax
        jsr     _P_AimLineAttack
        sta     _bulletslope
        stx     _bulletslope+1
        lda     sreg
        sta     _bulletslope+2
        lda     sreg+1
        sta     _bulletslope+3
        lda     _linetarget
        ora     _linetarget+1
@rts:   rts

; P_GunShot(mo, accurate: C set)
gun_shot:
        php
        lda     #3
        jsr     random_mod
        inc     a
        sta     tmp1
        asl     a
        asl     a
        adc     tmp1                    ; * 5
        sta     gs_dmg
        stz     gs_dmg+1
        jsr     gmo_pl
        ldy     #MO_ANGLE
        lda     (gmo),y
        sta     pt_angle
        iny
        lda     (gmo),y
        sta     pt_angle+1
        plp
        bcs     :+
        jsr     spread_angle
:       ldx     #3
:       lda     _bulletslope,x
        sta     W+W_T4,x
        dex
        bpl     :-
        lda     #0                      ; MISSILERANGE: 2048 units
        ldx     #0
        jsr     line_attack_big
        rts

; P_LineAttack at 2048 units ($08000000)
line_attack_big:
        lda     PL+PL_MO
        ldx     PL+PL_MO+1
        jsr     pushax
        lda     pt_angle
        ldx     pt_angle+1
        jsr     pushax
        lda     #0
        sta     sreg
        lda     #8
        sta     sreg+1
        lda     #0
        tax
        jsr     pusheax
        ldx     #W_T4
        jsr     ret_w
        jsr     pusheax
        lda     gs_dmg
        ldx     gs_dmg+1
        jmp     _P_LineAttack

; C set iff !refire (an accurate first shot)
accurate:
        clc
        lda     PL+PL_REFIRE
        bne     :+
        sec
:       rts

_A_FirePistol:
        jsr     action_args
        lda     #sfx_pistol
        jsr     pl_sound
        lda     #<S_PLAY_ATK2
        ldx     #>S_PLAY_ATK2
        jsr     mo_state
        jsr     decrease_ammo
        jsr     flash
        jsr     bullet_slope
        jsr     accurate
        jmp     gun_shot

_A_FireShotgun:
        jsr     action_args
        lda     #sfx_shotgn
        jsr     pl_sound
        lda     #<S_PLAY_ATK2
        ldx     #>S_PLAY_ATK2
        jsr     mo_state
        jsr     decrease_ammo
        jsr     flash
        jsr     bullet_slope
        lda     #7
@shot:  pha
        clc
        jsr     gun_shot
        pla
        dec     a
        bne     @shot
        rts

_A_FireCGun:
        jsr     action_args
        lda     gpt
        pha
        lda     gpt+1
        pha
        lda     #sfx_pistol
        jsr     pl_sound
        pla
        sta     gpt+1
        pla
        sta     gpt
        lda     PL+PL_READYWEAPON
        jsr     wi_ptr
        lda     (ptr1)
        asl     a
        tax
        lda     PL+PL_AMMO,x
        ora     PL+PL_AMMO+1,x
        beq     @rts
        ; the flash follows the gun's frame: flashstate + psp->state - S_CHAIN1
        sec
        lda     (gpt)
        sbc     #<S_CHAIN1
        sta     tmp3
        lda     gpt
        pha
        lda     gpt+1
        pha
        lda     #<S_PLAY_ATK2
        ldx     #>S_PLAY_ATK2
        jsr     mo_state
        jsr     decrease_ammo
        pla
        sta     gpt+1
        pla
        sta     gpt
        sec
        lda     (gpt)
        sbc     #<S_CHAIN1
        sta     tmp3
        ldy     #WI_FLASHSTATE
        jsr     ready_state
        clc
        adc     tmp3
        bcc     :+
        inx
:       jsr     flash_ax
        jsr     bullet_slope
        jsr     accurate
        jmp     gun_shot
@rts:   rts

_A_Light0:
        lda     #0
        bra     light
_A_Light1:
        lda     #1
        bra     light
_A_Light2:
        lda     #2
light:  sta     PL+PL_EXTRALIGHT
        jmp     incsp2

.endif ; DD_MAPDIR
