; dl_cmd.s: the tic command (docs/PLAY.md 2), in the tic image's group
; DLG_CMD: d_main65.s's buildNewTiccmds and g_game65.s's G_BuildTiccmd
; with its helpers, and p_pspr65.s's P_SwitchWeapon, P_WeaponCycleUp and
; P_WeaponCycleDown (called only by G_BuildTiccmd: docs/GAME.md 0.1). A
; GPL-2 derivative of upstream's src/iigs/d_main65.s, g_game65.s and
; p_pspr65.s (Doom8088: Apple IIgs Edition, GPL-2).
;
;   c_build   buildNewTiccmds: a command for each new tic of the clock
;             (pl_time, I_GetTime's low word), while maketic - gametic is
;             at most MAXTICS - 1 (lastmadetic takes every new tic)
;
; The keys are gamekeydown (DL_KEYS, G_Responder's: dl_brain.s), the mouse
; is pl_poll's PL_MDX (upstream's iigs_mousedx: zeroed when a command takes
; it), the settings are the menu's (DL_SETRUN, DL_SETMOUSE, DL_SETMSPD).
; A command goes to the ring G_CMDS at maketic & (CMDS - 1), 8 bytes:
; forwardmove, sidemove, angleturn (2), buttons, 0 0 0, which part tic's
; G_Ticker copies into the player's (docs/GAME.md 3.7's stream format).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "dl.inc"

        .import fc_call, fc_unbuilt, pl_time, far_put, udiv32
        .export bt_rows
        .export c_build, g_buildcmd, p_switchweapon, p_cycleup, p_cycledown

PLR      = G_PLAYER
FINETURNS = 3
MAXPLMOVE = $32
NOCHANGE = UC_WP_NOCHANGE

; the command being made (upstream's netcmd) and the temporaries: GT_0-6
; (any call may change them: none is live across a call here but
; P_CheckAmmo's, which upstream's takes the player only)
NC_FWD   = GT_0
NC_SIDE  = GT_1
NC_TURN  = GT_2                 ; (2)
NC_BUT   = GT_4
GB_SPEED = GT_5
GB_TURN  = GA_0                 ; (2)
GB_FWD   = GA_2                 ; (2)
GB_SIDE  = GA_4                 ; (2)
GG_T     = GA_6                 ; (2)
CW_T     = GA_8
CW_I     = GA_9
NT_NEW   = GA_10                ; (2)

        .segment "DLGC"
FC_HERE .set DLG_CMD

; ---------------------------------------------------------------------------
; c_build: buildNewTiccmds (d_main65.s:326-370)
; ---------------------------------------------------------------------------
c_build:
        jsr pl_time             ; newtics = now - lastmadetic
        sec
        pha
        sbc DL_LASTM
        sta NT_NEW
        txa
        sbc DL_LASTM+1
        sta NT_NEW+1
        pla
        sta DL_LASTM            ; lastmadetic += newtics
        stx DL_LASTM+1
@next:  lda NT_NEW              ; while (newtics--)
        ora NT_NEW+1
        beq @done
        lda NT_NEW
        bne :+
        dec NT_NEW+1
:       dec NT_NEW
        sec                     ; (int16) (maketic - gametic) > MAXTICS - 1
        lda DL_MAKETIC          ;   : enough
        sbc G_GAMETIC
        tax
        lda DL_MAKETIC+1
        sbc G_GAMETIC+1
        bmi :+
        bne @done
        cpx #MAXTICS
        bcs @done
:       jsr g_buildcmd
        inc DL_MAKETIC
        bne @next
        inc DL_MAKETIC+1
        bra @next
@done:  rts

; ---------------------------------------------------------------------------
; g_buildcmd: G_BuildTiccmd (g_game65.s:185-345)
; ---------------------------------------------------------------------------
g_buildcmd:
        stz NC_FWD
        stz NC_SIDE
        stz NC_TURN
        stz NC_TURN+1
        stz NC_BUT
        lda DL_KEYS + KEY_SPEED ; the run key XOR always run
        eor DL_SETRUN
        and #1
        sta GB_SPEED
        stz GB_FWD
        stz GB_FWD+1
        stz GB_SIDE
        stz GB_SIDE+1
        lda DL_KEYS + KEY_RIGHT
        ora DL_KEYS + KEY_LEFT
        bne @turn
        stz DL_TURNF            ; no turn key
        stz GB_TURN
        stz GB_TURN+1
        bra @turned
@turn:  ldx DL_TURNF            ; a new frame or a new turn: one more
        lda DL_NEWFRAME         ;   frame of the turn
        bne :+
        txa
        bne @tic
:       cpx #FINETURNS + 1
        bcs @tic
        inx
        stx DL_TURNF
        cpx #FINETURNS + 1
        bcs @tic
        lda fineturn_lo-1,x     ; a fine turn (frames 1-3)
        sta GB_TURN
        lda fineturn_hi-1,x
        sta GB_TURN+1
        bra @turned
@tic:   stz GB_TURN             ; the other tics of a fine frame: none;
        stz GB_TURN+1           ;   after the fine frames: Doom's
        cpx #FINETURNS + 1
        bcc @turned
        ldx GB_SPEED
        lda angleturn_lo,x
        sta GB_TURN
        lda angleturn_hi,x
        sta GB_TURN+1
@turned:
        stz DL_NEWFRAME
        lda DL_KEYS + KEY_STRAFE
        beq @noside
        lda DL_KEYS + KEY_RIGHT ; strafe: the turn keys move sideways
        beq :+
        jsr side_add
:       lda DL_KEYS + KEY_LEFT
        beq @moves
        jsr side_sub
        bra @moves
@noside:
        lda DL_KEYS + KEY_RIGHT ; else they turn
        beq :+
        sec
        lda NC_TURN
        sbc GB_TURN
        sta NC_TURN
        lda NC_TURN+1
        sbc GB_TURN+1
        sta NC_TURN+1
:       lda DL_KEYS + KEY_LEFT
        beq @moves
        clc
        lda NC_TURN
        adc GB_TURN
        sta NC_TURN
        lda NC_TURN+1
        adc GB_TURN+1
        sta NC_TURN+1
@moves: lda DL_KEYS + KEY_UP    ; forward and back
        beq :+
        ldx GB_SPEED
        lda forwardmove,x
        clc
        adc GB_FWD
        sta GB_FWD
        bcc :+
        inc GB_FWD+1
:       lda DL_KEYS + KEY_DOWN
        beq :+
        ldx GB_SPEED
        sec
        lda GB_FWD
        sbc forwardmove,x
        sta GB_FWD
        bcs :+
        dec GB_FWD+1
:       lda DL_KEYS + KEY_STRAFERIGHT   ; the strafe keys
        beq :+
        jsr side_add
:       lda DL_KEYS + KEY_STRAFELEFT
        beq :+
        jsr side_sub
:       lda DL_KEYS + KEY_FIRE  ; the buttons
        beq :+
        lda #UC_BT_ATTACK
        tsb NC_BUT
:       lda DL_KEYS + KEY_USE
        beq :+
        lda #UC_BT_USE
        tsb NC_BUT
:       jsr weaponkey           ; the new weapon: a number key, a cycle
        cmp #NOCHANGE           ;   key, or with attackdown and no ammo
        bne @change             ;   the best weapon
        lda DL_KEYS + KEY_WEAPONUP
        beq :+
        jsr p_cycleup
        bra @change
:       lda DL_KEYS + KEY_WEAPONDOWN
        beq :+
        jsr p_cycledown
        bra @change
:       lda PLR + PL_ATTACKDOWN
        ora PLR + PL_ATTACKDOWN + 1
        beq @nochange
        FCALL P_CheckAmmo       ; (part pspr's: A 0 not enough)
        cmp #0
        bne @nochange
        jsr p_switchweapon
        bra @change
@nochange:
        lda #NOCHANGE
@change:
        cmp #NOCHANGE
        beq @mouse
        asl a                   ; the weapon in bits 3+, BT_CHANGE
        asl a
        asl a
        ora #UC_BT_CHANGE
        tsb NC_BUT
@mouse: jsr mousemoves
        lda GB_FWD              ; the limits
        ldx GB_FWD+1
        jsr clampmove
        jsr fudgef              ; forwardmove += fudgef(forward)
        clc
        adc NC_FWD
        sta NC_FWD
        lda GB_SIDE             ; sidemove += side
        ldx GB_SIDE+1
        jsr clampmove
        clc
        adc NC_SIDE
        sta NC_SIDE
        lda DL_MAKETIC          ; the ring's slot of maketic
        and #CMDS - 1
        asl a
        asl a
        asl a
        tax
        lda NC_FWD
        sta G_CMDS,x
        lda NC_SIDE
        sta G_CMDS+1,x
        lda NC_TURN
        sta G_CMDS+2,x
        lda NC_TURN+1
        sta G_CMDS+3,x
        lda NC_BUT
        sta G_CMDS+4,x
        stz G_CMDS+5,x
        stz G_CMDS+6,x
        stz G_CMDS+7,x
        rts

; side_add, side_sub: GB_SIDE +/- sidemove[speed]
side_add:
        ldx GB_SPEED
        lda sidemove,x
        clc
        adc GB_SIDE
        sta GB_SIDE
        bcc :+
        inc GB_SIDE+1
:       rts
side_sub:
        ldx GB_SPEED
        sec
        lda GB_SIDE
        sbc sidemove,x
        sta GB_SIDE
        bcs :+
        dec GB_SIDE+1
:       rts

; weaponkey: A = the weapon of the first number key down, else NOCHANGE.
; Key 1 is the chainsaw when the player has it, but not when the chainsaw
; is up with berserk (g_game65.s:374-396)
weaponkey:
        ldx #0
:       lda DL_KEYS + KEY_WEAPON1,x
        bne @key
        inx
        cpx #7
        bcc :-
        lda #NOCHANGE
        rts
@key:   txa
        bne @rts
        lda PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINSAW
        ora PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINSAW + 1
        beq @fist
        lda PLR + PL_READYWEAPON
        cmp #UC_WP_CHAINSAW
        bne @saw
        lda PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH
        ora PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH + 1
        bne @fist
@saw:   lda #UC_WP_CHAINSAW
        rts
@fist:  lda #UC_WP_FIST
@rts:   rts

; mousemoves: the mouse's motion since the last command (g_game65.s:402-
; 432): X turns (with the strafe key: side moves of 1/16), 15 + 3 x the
; speed a count, X limited to -700..700. The //e's mouse reports X only
; (pl_poll), so the menu's MOUSE MOVE has nothing to move; the mouse off
; (the menu's MOUSE): its motion dropped
mousemoves:
        lda PL_MDX
        ldx PL_MDX+1
        stz PL_MDX
        stz PL_MDX+1
        ldy DL_SETMOUSE
        bne :+
        rts
:       cpx #$80                ; limited to -700..700
        bcs @neg
        cpx #>701
        bcc @scale
        bne :+
        cmp #<701
        bcc @scale
:       lda #<700
        ldx #>700
        bra @scale
@neg:   cpx #>(-700 & $FFFF)
        bcc :+
        bne @scale
        cmp #<(-700 & $FFFF)
        bcs @scale
:       lda #<(-700 & $FFFF)
        ldx #>(-700 & $FFFF)
@scale: sta GG_T                ; C = C x (15 + 3 x speed), the low word
        stx GG_T+1
        lda DL_SETMSPD
        asl a
        adc DL_SETMSPD
        adc #15
        tay
        stz CW_T                ; (the product's low word in CW_T, CW_I)
        stz CW_I
:       lsr a                   ; (Y the multiplier, A its bits)
        bcc :+
        pha
        clc
        lda CW_T
        adc GG_T
        sta CW_T
        lda CW_I
        adc GG_T+1
        sta CW_I
        pla
:       asl GG_T
        rol GG_T+1
        cmp #0
        bne :--
        lda CW_T
        ora CW_I
        beq @rts
        lda DL_KEYS + KEY_STRAFE
        bne @side
        sec                     ; angleturn -= C
        lda NC_TURN
        sbc CW_T
        sta NC_TURN
        lda NC_TURN+1
        sbc CW_I
        sta NC_TURN+1
@rts:   rts
@side:  ldy #4                  ; side += C >> 4 (arithmetic)
:       lda CW_I
        cmp #$80
        ror CW_I
        ror CW_T
        dey
        bne :-
        clc
        lda GB_SIDE
        adc CW_T
        sta GB_SIDE
        lda GB_SIDE+1
        adc CW_I
        sta GB_SIDE+1
        rts

; clampmove: A (low) = A:X limited to -MAXPLMOVE..MAXPLMOVE (int16)
clampmove:
        cpx #$80
        bcs @neg
        cpx #0
        bne @max
        cmp #MAXPLMOVE + 1
        bcc @rts
@max:   lda #MAXPLMOVE
@rts:   rts
@neg:   cpx #$FF
        bne @min
        cmp #<(-MAXPLMOVE)
        bcs @rts
@min:   lda #<(-MAXPLMOVE)
        rts

; fudgef: A = fudgef(A): 0 stays; every 32nd other move is made odd, less
; 2 when more than 2 (int8) (g_game65.s:492-509)
fudgef: cmp #0
        beq @rts
        pha
        inc DL_FUDGE
        lda DL_FUDGE
        and #$1F
        bne @keep
        pla
        ora #1
        cmp #$80
        bcs @rts
        cmp #3
        bcc @rts
        sbc #2
        rts
@keep:  pla
@rts:   rts

; ---------------------------------------------------------------------------
; p_switchweapon: P_SwitchWeapon (p_pspr65.s:179-260): the most preferred
; weapon with ammunition, not the raised one
; ---------------------------------------------------------------------------
p_switchweapon:
        lda PLR + PL_READYWEAPON
        sta CW_T                ; newweapon
        lda #10                 ; i = NUMWEAPONS + 1
        sta CW_I
        ldx #0                  ; prefer
@pref:  lda prefs,x
        inx
        phx
        cmp #1                  ; 1: the fist with berserk, else nothing
        bne @n2
        lda PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH
        ora PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH + 1
        beq @next
        bra @fist
@n2:    cmp #0                  ; 0: the fist
        bne @n3
@fist:  lda #UC_WP_FIST
        bra @take
@n3:    cmp #2                  ; 2: the pistol with clips
        bne @n4
        ldy #2 * UC_AM_CLIP
        jsr ammo
        beq @next
        lda #UC_WP_PISTOL
        bra @take
@n4:    cmp #3                  ; 3: the shotgun with shells
        bne @n5
        ldx #UC_WP_SHOTGUN
        ldy #2 * UC_AM_SHELL
        bra @owned
@n5:    cmp #4                  ; 4: the chaingun with clips
        bne @n6
        ldx #UC_WP_CHAINGUN
        ldy #2 * UC_AM_CLIP
        bra @owned
@n6:    cmp #5                  ; 5: the rocket launcher with rockets
        bne @n8
        ldx #UC_WP_MISSILE
        ldy #2 * UC_AM_MISL
        bra @owned
@n8:    cmp #8                  ; 8: the chainsaw
        bne @next
        ldx #UC_WP_CHAINSAW
        jsr owned
        beq @next
        lda #UC_WP_CHAINSAW
        bra @take
@owned: phx                     ; (the weapon)
        jsr owned
        beq @nope
        jsr ammo
        beq @nope
        pla
        bra @take
@nope:  pla
        bra @next
@take:  sta CW_T
@next:  plx
        lda CW_T                ; while (newweapon == currentweapon && --i)
        cmp PLR + PL_READYWEAPON
        bne @done
        dec CW_I
        bne @pref
@done:  lda CW_T
        rts

; owned: Z clear when the player owns weapon X (A and X change, Y kept)
owned:  txa
        asl a
        tax
        lda PLR + PL_WEAPONOWNED_0,x
        ora PLR + PL_WEAPONOWNED_0 + 1,x
        rts
; ammo: Z clear when the ammunition Y / 2 is not 0 (A changes)
ammo:   lda PLR + PL_AMMO_0,y
        ora PLR + PL_AMMO_0 + 1,y
        rts

; cancan: A = A when the player has the weapon's ammunition, else NOCHANGE
; (p_pspr65.s's checkCanSwitch)
cancan: cmp #UC_WP_FIST
        beq @rts
        cmp #UC_WP_CHAINSAW
        beq @rts
        ldy #2 * UC_AM_CLIP
        cmp #UC_WP_PISTOL
        beq @ammo
        cmp #UC_WP_CHAINGUN
        beq @ammo
        ldy #2 * UC_AM_SHELL
        cmp #UC_WP_SHOTGUN
        beq @ammo
        ldy #2 * UC_AM_MISL
        cmp #UC_WP_MISSILE
        beq @ammo
        ldy #2 * UC_AM_CELL
        cmp #UC_WP_PLASMA
        bne @none
@ammo:  pha
        jsr ammo
        pla
        bne @rts
@none:  lda #NOCHANGE
@rts:   rts

; ownedcan: carry set and A = CW_T when the player owns weapon CW_T and
; has its ammunition
ownedcan:
        ldx CW_T
        jsr owned
        beq @no
        lda CW_T
        jsr cancan
        cmp #NOCHANGE
        beq @no
        lda CW_T
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; p_cycleup, p_cycledown: P_WeaponCycleUp, P_WeaponCycleDown (p_pspr65.s:
; 276-358): the next owned weapon with ammunition, in PSX Doom's order
; ---------------------------------------------------------------------------
p_cycleup:
        lda PLR + PL_READYWEAPON
        sta CW_T
        lda #UC_NUMWEAPONS
        sta CW_I
@next:  lda CW_T                ; w++, 0 after the last
        inc a
        cmp #UC_NUMWEAPONS
        bcc :+
        lda #0
:       ldx #4                  ; PSX Doom's order
:       cmp up_from,x
        beq @map
        dex
        bpl :-
        bra @set
@map:   lda up_to,x
@set:   sta CW_T
        jsr ownedcan
        bcs @rts
        dec CW_I
        bne @next
        lda PLR + PL_READYWEAPON
@rts:   rts

p_cycledown:
        lda PLR + PL_READYWEAPON
        sta CW_T
        lda #UC_NUMWEAPONS
        sta CW_I
@next:  lda CW_T                ; w--, the last after 0
        bne :+
        lda #UC_NUMWEAPONS
:       dec a
        ldx #4
:       cmp down_from,x
        beq @map
        dex
        bpl :-
        bra @set
@map:   lda down_to,x
@set:   sta CW_T
        jsr ownedcan
        bcs @rts
        dec CW_I
        bne @next
        lda PLR + PL_READYWEAPON
@rts:   rts

; the tables (g_game65.s:107-110; p_pspr65.s:59-60, :289-340)
forwardmove:    .byte $19, $32
sidemove:       .byte $18, $28
angleturn_lo:   .byte <640, <1280
angleturn_hi:   .byte >640, >1280
fineturn_lo:    .byte <320, <640, <1280
fineturn_hi:    .byte >320, >640, >1280
prefs:          .byte 6, 9, 4, 3, 2, 8, 5, 7, 1, 0
up_from:        .byte UC_WP_CHAINGUN, UC_WP_FIST, UC_WP_CHAINSAW
                .byte UC_WP_PISTOL, UC_WP_SUPERSHOTGUN
up_to:          .byte UC_WP_SUPERSHOTGUN, UC_WP_CHAINGUN, UC_WP_FIST
                .byte UC_WP_CHAINSAW, UC_WP_PISTOL
down_from:      .byte UC_WP_SHOTGUN, UC_WP_CHAINSAW, UC_WP_FIST
                .byte UC_WP_BFG, UC_WP_SUPERSHOTGUN
down_to:        .byte UC_WP_SUPERSHOTGUN, UC_WP_SHOTGUN, UC_WP_CHAINSAW
                .byte UC_WP_FIST, UC_WP_BFG

; ---------------------------------------------------------------------------
; The benchmark's phase rows (docs/PLAY.md 15; the timing is dl_disp.s's)
; ---------------------------------------------------------------------------
BT_TPAL  = 6500                 ; 64 x the bus cycles of 0.1 ms: 1,015,625
BT_TNTSC = 6531                 ;   Hz (PAL), 1,020,484 Hz (NTSC)
BT_ROW   = 32                   ; M_BROWS: three rows of 32 bytes
BT_MAXT  = 99999                ; a mean shown at most 9999.9 ms
; zero page: the math's temporaries (udiv32 changes MT+0 - MT+5)
BZ_P     = MT + 6               ; a string (2)
BZ_C     = MT + 8               ; a number's digits
BZ_F     = MT + 9               ; bit 7: a point before the last digit
BZ_I     = MT + 10              ; the next byte of bt_txt
        .assert M_BROWS + 3 * BT_ROW <= MENUW_STATE_END, error, "M_BROWS"

; bt_rows: the result page's three rows into MENUW's M_BROWS in S2STATE
; (s2_menu2.s m2_bench draws them): "TIC t  3D t", "MASK t  DRAW t",
; "REST t  N n", and "  OVF n" when the timing lost turns it could not
; place (BT_OVF); t each phase's mean a frame (BT_S / DL_BVIEW, the
; frames), ms with one decimal, rounded
bt_rows:
        stz BZ_I
        lda #<bs_tic
        ldy #>bs_tic
        ldx #PH_TIC
        jsr bt_item
        lda #<bs_3d
        ldy #>bs_3d
        ldx #PH_3D
        jsr bt_item
        lda #BT_ROW
        jsr bt_eol
        lda #<bs_mask
        ldy #>bs_mask
        ldx #PH_MASK
        jsr bt_item
        lda #<bs_draw
        ldy #>bs_draw
        ldx #PH_DRAW
        jsr bt_item
        lda #2 * BT_ROW
        jsr bt_eol
        lda #<bs_rest
        ldy #>bs_rest
        ldx #PH_REST
        jsr bt_item
        lda #<bs_n
        ldy #>bs_n
        jsr bt_str
        lda DL_BVIEW
        ldx DL_BVIEW+1
        jsr bt_int
        lda BT_OVF
        beq :+
        lda #<bs_ovf
        ldy #>bs_ovf
        jsr bt_str
        lda BT_OVF
        ldx #0
        jsr bt_int
:       lda #3 * BT_ROW
        jsr bt_eol
        lda #<bt_txt
        sta FA_SRC
        lda #>bt_txt
        sta FA_SRC+1
        lda #S2STATE
        sta FA_BANK
        lda #<(SS_MENUW + M_BROWS - MENUW_STATE)
        sta FA_DST
        lda #>(SS_MENUW + M_BROWS - MENUW_STATE)
        sta FA_DST+1
        lda #3 * BT_ROW
        sta FA_N
        jmp far_put

; bt_eol: the row's 0, then the rows' writer at A
bt_eol:
        ldx BZ_I
        stz bt_txt,x
        sta BZ_I
        rts

; bt_item: the label Y:A, then phase X's mean a frame
bt_item:
        phx
        jsr bt_str
        plx
        ldy #0
:       lda BT_S-4,x            ; the cycles / the frames
        sta M_A,y
        inx
        iny
        cpy #4
        bne :-
        lda DL_BVIEW
        sta M_B
        lda DL_BVIEW+1
        sta M_B+1
        stz M_B+2
        stz M_B+3
        jsr udiv32
        ldy #6                  ; x 64 (a frame's phase under 66 s)
:       asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        dey
        bne :-
        ldx #<BT_TPAL
        ldy #>BT_TPAL
        bit CLK_STD
        bpl :+
        ldx #<BT_TNTSC
        ldy #>BT_TNTSC
:       stx M_B
        sty M_B+1
        stz M_B+2
        stz M_B+3
        tya                     ; + half the divisor: rounded
        lsr a
        tay
        txa
        ror a
        clc
        adc M_R
        sta M_A
        tya
        adc M_R+1
        sta M_A+1
        lda M_R+2
        adc #0
        sta M_A+2
        lda M_R+3
        adc #0
        sta M_A+3
        jsr udiv32              ; M_R = the tenths of ms
        sec                     ; at most BT_MAXT
        lda M_R
        sbc #<BT_MAXT
        lda M_R+1
        sbc #>BT_MAXT
        lda M_R+2
        sbc #^BT_MAXT
        lda M_R+3
        sbc #0
        bcc :+
        lda #<BT_MAXT
        sta M_R
        lda #>BT_MAXT
        sta M_R+1
        lda #^BT_MAXT
        sta M_R+2
        stz M_R+3
:       sec
        bra bt_num

; bt_int: A:X (low, high) in decimal
bt_int:
        sta M_R
        stx M_R+1
        stz M_R+2
        stz M_R+3
        clc
; bt_num: M_R in decimal into bt_txt at BZ_I; C set: a point before its
; last digit (at least 0.d)
bt_num:
        ror BZ_F
        lda #0                  ; (the digits' end on the stack)
        pha
        stz BZ_C
@div:   ldx #3
:       lda M_R,x
        sta M_A,x
        stz M_B,x
        dex
        bpl :-
        lda #10
        sta M_B
        jsr udiv32              ; M_R / 10, M_T its digit
        lda M_T
        ora #'0'
        pha
        inc BZ_C
        lda M_R
        ora M_R+1
        ora M_R+2
        ora M_R+3
        bne @div
        bit BZ_F
        bpl @put
        lda BZ_C
        cmp #2
        bcc @div
@put:   pla
        beq @done
        ldx BZ_I
        sta bt_txt,x
        inx
        dec BZ_C
        lda BZ_C
        cmp #1
        bne :+
        bit BZ_F
        bpl :+
        lda #'.'
        sta bt_txt,x
        inx
:       stx BZ_I
        bra @put
@done:  rts

; bt_str: the string Y:A (0-terminated) into bt_txt at BZ_I
bt_str:
        sta BZ_P
        sty BZ_P+1
        ldy #0
@ch:    lda (BZ_P),y
        beq @done
        ldx BZ_I
        sta bt_txt,x
        inc BZ_I
        iny
        bra @ch
@done:  rts

bs_tic:  .byte "TIC ", 0
bs_3d:   .byte "  3D ", 0
bs_mask: .byte "MASK ", 0
bs_draw: .byte "  DRAW ", 0
bs_rest: .byte "REST ", 0
bs_n:    .byte "  N ", 0
bs_ovf:  .byte "  OVF ", 0
bt_txt:  .res 3 * BT_ROW
