; gweap.s: the game core's weapon at the start of a level (docs/LEVELS.md).
; A GPL-2 derivative of upstream's p_pspr65.s (P_SetupPsprites, bringUpWeapon, setPsprite, A_Raise).
;
;   gw_setup        P_SetupPsprites: both psprites' states none, the
;                   pending weapon the ready one, then bringUpWeapon: the
;                   pending weapon's up state from the bottom of the
;                   screen (sy = WEAPONBOTTOM + 2), the pending weapon
;                   WP_NOCHANGE
;   gw_setpsprite   P_SetPsprite(psprite GS_PSP, state GS_ST): the state,
;                   its tics, its action, then the next state while the
;                   tics are 0. In the tic image the action goes through
;                   ACTTAB (DCALL: docs/GAME.md; a weapon action takes its psprite in GS_PSP); in
;                   the load image the actions an up state reaches are
;                   known (A_Raise) and any other is a stop (LS_ACTION)
;   A_Raise         sy -= RAISESPEED; at WEAPONTOP or above the weapon is
;                   ready (its ready state)
;
; The chainsaw's raising sound (S_StartSound, sfx_sawup) goes to the hook
; S_StartSound (dl_hook.s) in the tic image; the load image has no sound. A state's action is upstream's address in the states table (GTAB
; holds upstream's records): A_Raise's is U_A_RAISE; act_num gives its
; ACTTAB number in the tic image.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gw_setup, gw_setpsprite, A_Raise, bringUpWeapon
        .import state_at, ld_stop
        .include "ggame.inc"
.ifndef LOADIMG
        .include "gplace.inc"
        .import act_num, dc_call, S_StartSound, ACTTAB
.endif

PLR     = G_PLAYER
PSP_SIZE = PL_PSPRITES_1_STATE - PL_PSPRITES_0_STATE
        .assert PSP_SIZE = 10, error, "a psprite: state, tics, sx, sy"
PSTATE  = PLR + PL_PSPRITES_0_STATE      ; psprite k's fields at + 10 k
PTICS   = PLR + PL_PSPRITES_0_TICS
PSY     = PLR + PL_PSPRITES_0_SY

        .segment "LOADW"

; ---------------------------------------------------------------------------
; gw_setup: P_SetupPsprites(&_g_player)
; ---------------------------------------------------------------------------
gw_setup:
        lda #$FF                ; both states none
        sta PSTATE
        sta PSTATE+1
        sta PSTATE + PSP_SIZE
        sta PSTATE + PSP_SIZE + 1
        lda PLR + PL_READYWEAPON ; pending = ready
        sta PLR + PL_PENDINGWEAPON
        lda PLR + PL_READYWEAPON + 1
        sta PLR + PL_PENDINGWEAPON + 1
        ; bringUpWeapon (an entry of its own: part pspr's A_Lower calls
        ; it)
bringUpWeapon:
        lda PLR + PL_PENDINGWEAPON       ; WP_NOCHANGE: the ready one
        cmp #U_WP_NOCHANGE
        bne :+
        lda PLR + PL_PENDINGWEAPON + 1
        bne :+
        lda PLR + PL_READYWEAPON
        sta PLR + PL_PENDINGWEAPON
        lda PLR + PL_READYWEAPON + 1
        sta PLR + PL_PENDINGWEAPON + 1
:       lda PLR + PL_PENDINGWEAPON + 1   ; weaponinfo[pending].upstate
        jne bad
        ldx PLR + PL_PENDINGWEAPON
        cpx #U_NUMWEAPONS
        jcs bad
        lda wi_up_lo,x
        sta GS_ST
        lda wi_up_hi,x
        sta GS_ST+1
.ifndef LOADIMG
        cpx #U_WP_CHAINSAW      ; the chainsaw: its raising sound
        bne :+
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        phx
        tax
        ply
        lda #UC_SFX_SAWUP
        jsr S_StartSound
        ldx PLR + PL_PENDINGWEAPON
:
.endif
        lda #U_WP_NOCHANGE      ; pending = WP_NOCHANGE
        sta PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
        stz PSY                 ; sy = WEAPONBOTTOM + 2 (whole units)
        stz PSY+1
        lda #<(U_WEAPONBOTTOM_HI + 2)
        sta PSY+2
        lda #>(U_WEAPONBOTTOM_HI + 2)
        sta PSY+3
        stz GS_PSP              ; the weapon's psprite
        ; (on into gw_setpsprite)

; ---------------------------------------------------------------------------
; gw_setpsprite: P_SetPsprite(&_g_player, GS_PSP, GS_ST)
; ---------------------------------------------------------------------------
gw_setpsprite:
        ldx GS_PSP              ; X = 10 k: the psprite's offset
        lda psp_off,x
        tax
        lda GS_ST               ; S_NULL: the psprite removed
        ora GS_ST+1
        bne @state
        lda #$FF
        sta PSTATE,x
        sta PSTATE+1,x
        rts
@state: lda GS_ST
        sta PSTATE,x
        lda GS_ST+1
        sta PSTATE+1,x
        phx
        lda GS_ST
        ldx GS_ST+1
        jsr state_at            ; LW_STATE
        plx
        lda LW_STATE + U_ST_TICS        ; tics = state->tics
        sta PTICS,x
        lda LW_STATE + U_ST_TICS + 1
        sta PTICS+1,x
        lda LW_STATE + U_ST_ACTION      ; the action
        ora LW_STATE + U_ST_ACTION + 1
        ora LW_STATE + U_ST_ACTION + 2
        ora LW_STATE + U_ST_ACTION + 3
        beq @next
.ifdef LOADIMG
        lda LW_STATE + U_ST_ACTION
        cmp #<U_A_RAISE
        bne bad
        lda LW_STATE + U_ST_ACTION + 1
        cmp #>U_A_RAISE
        bne bad
        lda LW_STATE + U_ST_ACTION + 2
        cmp #^U_A_RAISE
        bne bad
        lda LW_STATE + U_ST_ACTION + 3
        bne bad
        lda GS_PSP              ; A_Raise(the player, the psprite)
        pha
        jsr a_raise
.else
        lda GS_PSP              ; the action (ACTTAB), the psprite in GS_PSP
        pha
        jsr act_num
        DCALL ACTTAB
.endif
        pla
        sta GS_PSP
        tax
        lda psp_off,x
        tax
        lda PSTATE,x            ; removed: done
        and PSTATE+1,x
        cmp #$FF
        beq @done
@next:  lda PSTATE,x            ; stnum = psp->state->nextstate
        phx
        pha
        lda PSTATE+1,x
        tax
        pla
        jsr state_at
        plx
        lda LW_STATE + U_ST_NEXTSTATE
        sta GS_ST
        lda LW_STATE + U_ST_NEXTSTATE + 1
        sta GS_ST+1
        lda PTICS,x             ; while (!psp->tics)
        ora PTICS+1,x
        jeq gw_setpsprite
@done:  rts

bad:    lda #LS_ACTION
        jmp ld_stop

; a_raise: A_Raise(&_g_player, psprite GS_PSP): sy -= RAISESPEED; at or
; above WEAPONTOP: sy = WEAPONTOP and the ready state of the ready weapon
; on the weapon's psprite
a_raise:
A_Raise:
        ldx GS_PSP
        lda psp_off,x
        tax
        sec                     ; sy's high word - RAISESPEED
        lda PSY+2,x
        sbc #<U_LOWERSPEED_HI
        sta PSY+2,x
        lda PSY+3,x
        sbc #>U_LOWERSPEED_HI
        sta PSY+3,x
        sec                     ; sy > WEAPONTOP: still going up
        lda PSY+2,x
        sbc #<U_WEAPONTOP_HI
        tay
        lda PSY+3,x
        sbc #>U_WEAPONTOP_HI
        bmi @ready
        bne @done
        tya
        bne @done
        lda PSY,x
        ora PSY+1,x
        beq @ready
@done:  rts
@ready: stz PSY,x               ; sy = WEAPONTOP, ready
        stz PSY+1,x
        lda #<U_WEAPONTOP_HI
        sta PSY+2,x
        lda #>U_WEAPONTOP_HI
        sta PSY+3,x
        lda PLR + PL_READYWEAPON + 1
        bne bad
        ldx PLR + PL_READYWEAPON
        cpx #U_NUMWEAPONS
        bcs bad
        lda wi_ready_lo,x
        sta GS_ST
        lda wi_ready_hi,x
        sta GS_ST+1
        stz GS_PSP              ; the weapon's psprite
        jmp gw_setpsprite

psp_off:
        .byte 0, PSP_SIZE
; weaponinfo's up and ready states (the release's table, lgame.inc)
wi_up_lo:
        .byte <U_WI_UP_0, <U_WI_UP_1, <U_WI_UP_2, <U_WI_UP_3, <U_WI_UP_4
        .byte <U_WI_UP_5, <U_WI_UP_6, <U_WI_UP_7, <U_WI_UP_8
wi_up_hi:
        .byte >U_WI_UP_0, >U_WI_UP_1, >U_WI_UP_2, >U_WI_UP_3, >U_WI_UP_4
        .byte >U_WI_UP_5, >U_WI_UP_6, >U_WI_UP_7, >U_WI_UP_8
wi_ready_lo:
        .byte <U_WI_READY_0, <U_WI_READY_1, <U_WI_READY_2, <U_WI_READY_3
        .byte <U_WI_READY_4, <U_WI_READY_5, <U_WI_READY_6, <U_WI_READY_7
        .byte <U_WI_READY_8
wi_ready_hi:
        .byte >U_WI_READY_0, >U_WI_READY_1, >U_WI_READY_2, >U_WI_READY_3
        .byte >U_WI_READY_4, >U_WI_READY_5, >U_WI_READY_6, >U_WI_READY_7
        .byte >U_WI_READY_8
        .assert U_NUMWEAPONS = 9, error, "nine weapons"
