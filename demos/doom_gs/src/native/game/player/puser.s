; game/player/puser.s: part player's think (milestone 10, docs/GAME.md 2.4;
; docs/game-parts/player.md). A GPL-2 derivative of upstream's p_user65.s
; (P_PlayerThink with the death think, movePlayer with bobAndThrust and
; addMom, calcHeight with fixedSquare, angleToAttacker, specialSector with
; hurt32, onGround, thrustMul).
;
;   P_PlayerThink   each tic: MF_NOCLIP from the cheat, the chainsaw's run
;                   forward, the death think when dead; else the reaction
;                   time or movePlayer, calcHeight, the sector's special
;                   (specialSector), a weapon change (not to the plasma
;                   gun or the BFG, an owned one), the use button (P_UseLines
;                   once a press), P_MovePsprites, the powers' counts, the
;                   damage and bonus counts, the colormap
;   movePlayer      the turn (angle's high word += angleturn), onGround, and
;                   on the ground the thrusts of forwardmove (the angle) and
;                   sidemove (the angle - ANG90), each m = move << 11,
;                   FixedMulAngle(m, cosine), (m, sine) added to the mobj's
;                   and the player's momentum (CLEAN cleared); standing in
;                   S_PLAY: S_PLAY_RUN1
;   calcHeight      bob = (fixedSquare(momx) + fixedSquare(momy)) >> 2, at
;                   most MAXBOB; in the air viewz = z + VIEWHEIGHT; else
;                   the bob's offset FixedMulAngle(bob / 2, finesine((409
;                   leveltime) & 8191)), the view height with its delta
;                   (alive), viewz = z + viewheight + offset; viewz at most
;                   ceilingz - 4 FRACUNIT
;   fixedSquare     X = 0 (momx) or 4 (momy) of the player: M_R =
;                   (a + alw) * ahw + ((alw * alw) >> 16), upstream's
;                   FixedSquare with its wrap (mul32: the low 32 bits)
;   angleToAttacker M_R = R_PointToAngle3(attacker - mo) (pta3)
;   specialSector   A = the player's sector: on its floor, the specials 5
;                   (10, not with the suit), 7 (5), 16 (20, with the suit
;                   when P_Random() < 5), each when leveltime & 31 is 0; 9
;                   (a secret: secretcount + 1, the special 0); 11 (god
;                   mode off, 20 when leveltime & 31 is 0, then the exit
;                   when health <= 10)
;   onGround        PY_ONG = mo->z <= mo->floorz (signed)
;   thrustMul       M_R = FixedMulAngle(PY_T, M_R) (fixmulang)
;   hurt32          A:X = a damage: when leveltime & 31 is 0, C set and
;                   P_DamageMobj's arguments in GA_0-7 (the player's mobj,
;                   no inflictor, no source, the damage), which the caller
;                   then calls; else C clear. Upstream's hurt32 makes the
;                   call itself: natively the arguments are the helper's,
;                   so that its random check needs no damage run
;
; argMo, moSector, countDown, blink, bobAndThrust and addMom have no code of
; their own: the routines that call them do their work in place (local
; subroutines named pt_*, pm_*; request R2: INLINED).
;
; Every routine changes A, X, Y, GT_*, the math's block and what its
; callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/player/player.inc"

        .export P_PlayerThink, movePlayer, calcHeight, fixedSquare
        .export angleToAttacker, specialSector, onGround, thrustMul, hurt32
        .import mo_get, mo_dirty, ss_get, sec_get, sec_dirty, pl_get, pl_put
        .import g_random, fixmulang, mul32, umul16, umul16lo, finesine
        .import finecosine, pta3, fc_call, fc_unbuilt

; ===========================================================================
; P_PlayerThink
; ===========================================================================
        ROUTINE P_PlayerThink
        jsr pt_mo
        ldy #PO_B + MB_FLAGS + 1        ; MF_NOCLIP with the noclip cheat
        lda (GC_MP),y
        and #<~(>UC_MF_NOCLIP_LO)
        tax
        lda PLR + PL_CHEATS
        and #UC_CF_NOCLIP
        beq :+
        txa
        ora #>UC_MF_NOCLIP_LO
        tax
:       txa
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
        ldy #PO_B + MB_FLAGS            ; the chainsaw runs forward
        lda (GC_MP),y
        bit #<UC_MF_JUSTATTACKED_LO
        beq @state
        and #<~UC_MF_JUSTATTACKED_LO
        sta (GC_MP),y
        stz PLR + PL_CMD_ANGLETURN
        stz PLR + PL_CMD_ANGLETURN + 1
        lda #100                        ; forwardmove 100, sidemove 0
        sta PLR + PL_CMD_FORWARDMOVE
        stz PLR + PL_CMD_SIDEMOVE
@state: lda PLR + PL_PLAYERSTATE
        cmp #<UC_PST_DEAD
        bne @live
        lda PLR + PL_PLAYERSTATE + 1
        bne @live
        jmp pt_death

@live:  jsr pt_mo                       ; no move for a while after a
        ldy #PO_C + MC_REACT            ;   teleport
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        beq @move
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
        bra @height
@move:  FCALL movePlayer
@height:
        FCALL calcHeight
        jsr pt_mo                       ; a special sector?
        ldy #PO_A + MA_SUBSEC + 1
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        pha
        jsr sec_get
        pla
        ldy #SEC_G + SG_SPECIAL
        tax
        lda (GC_SP),y
        beq @weapon
        txa
        FCALL specialSector

@weapon:
        lda PLR + PL_CMD_BUTTONS        ; a weapon change
        and #UC_BT_CHANGE
        beq @use
        lda PLR + PL_CMD_BUTTONS
        and #UC_BT_WEAPONMASK
        lsr a
        lsr a
        lsr a
        cmp PLR + PL_READYWEAPON        ; (a word: its high byte 0)
        bne :+
        ldx PLR + PL_READYWEAPON + 1
        beq @use
:       cmp #UC_WP_PLASMA               ; not to plasma or BFG
        beq @use
        cmp #UC_WP_BFG
        beq @use
        tay
        asl a
        tax
        lda PLR + PL_WEAPONOWNED_0,x    ; (upstream's word at 2 w: past
        ora PLR + PL_WEAPONOWNED_0 + 1,x ;  weaponowned[8] the ammo, as
        beq @use                        ;   upstream's layout)
        sty PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
@use:   lda PLR + PL_CMD_BUTTONS        ; use
        and #UC_BT_USE
        beq @nouse
        lda PLR + PL_USEDOWN
        ora PLR + PL_USEDOWN + 1
        bne @psp
        FCALL P_UseLines
        lda #1
        sta PLR + PL_USEDOWN
        stz PLR + PL_USEDOWN + 1
        bra @psp
@nouse: stz PLR + PL_USEDOWN
        stz PLR + PL_USEDOWN + 1
@psp:   FCALL P_MovePsprites

        ; the counters of the power ups
        lda PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH      ; strength counts up
        ora PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH + 1
        beq :+
        inc PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH
        bne :+
        inc PLR + PL_POWERS_0 + 2 * UC_PW_STRENGTH + 1
:       ldx #2 * UC_PW_INVULNERABILITY
        jsr pt_count
        ldx #2 * UC_PW_INVISIBILITY
        jsr pt_count
        bcc @infra
        jsr pt_mo                       ; visible again
        ldy #PO_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<~UC_MF_SHADOW_HI
        sta (GC_MP),y
        lda #D_B
        jsr mo_dirty
@infra: ldx #2 * UC_PW_INFRARED
        jsr pt_count
        ldx #2 * UC_PW_IRONFEET
        jsr pt_count
        ldx #PL_DAMAGECOUNT
        jsr pt_dec
        ldx #PL_BONUSCOUNT
        jsr pt_dec
        ; the colormap: inverse for invulnerability, 1 for light
        ; amplification, both blink at the end
        ldy #INVERSECOLORMAP
        ldx #2 * UC_PW_INVULNERABILITY
        jsr pt_blink
        bcs @cmap
        ldy #1
        ldx #2 * UC_PW_INFRARED
        jsr pt_blink
        bcs @cmap
        ldy #0
@cmap:  sty PLR + PL_FIXEDCOLORMAP
        stz PLR + PL_FIXEDCOLORMAP + 1
        rts

; pt_mo: the player's mobj into the cache (GC_MP)
pt_mo:  lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jmp mo_get

; pt_count (upstream's countDown): X = 2 the power: if (powers > 0)
; powers--; C set when it went to 0 (the invisibility's end)
pt_count:
        lda PLR + PL_POWERS_0 + 1,x
        bmi @no
        ora PLR + PL_POWERS_0,x
        beq @no
        lda PLR + PL_POWERS_0,x
        sec
        sbc #1
        sta PLR + PL_POWERS_0,x
        lda PLR + PL_POWERS_0 + 1,x
        sbc #0
        sta PLR + PL_POWERS_0 + 1,x
        ora PLR + PL_POWERS_0,x
        bne @no
        sec
        rts
@no:    clc
        rts

; pt_dec: the player's word at X - 1 when it is not 0
pt_dec: lda PLR,x
        ora PLR + 1,x
        beq :+
        lda PLR,x
        sec
        sbc #1
        sta PLR,x
        lda PLR + 1,x
        sbc #0
        sta PLR + 1,x
:       rts

; pt_blink (upstream's blink): X = 2 the power: C set when powers > 4 * 32
; (signed) or powers & 8. Keeps Y.
pt_blink:
        sec
        lda PLR + PL_POWERS_0,x
        sbc #4 * 32 + 1
        lda PLR + PL_POWERS_0 + 1,x
        sbc #0
        bvc :+
        eor #$80
:       bpl @yes
        lda PLR + PL_POWERS_0,x
        and #8
        beq @no
@yes:   sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; pt_death (upstream's deathThink): fall to the ground and turn to the
; killer. Ends P_PlayerThink.
; ---------------------------------------------------------------------------
pt_death:
        FCALL P_MovePsprites
        sec                             ; viewheight > 6 FRACUNIT: - FRACUNIT
        lda #0
        sbc PLR + PL_VIEWHEIGHT
        lda #0
        sbc PLR + PL_VIEWHEIGHT + 1
        lda #6
        sbc PLR + PL_VIEWHEIGHT + 2
        lda #0
        sbc PLR + PL_VIEWHEIGHT + 3
        bvc :+
        eor #$80
:       bpl @floor
        lda PLR + PL_VIEWHEIGHT + 2     ; (the high word's decrement)
        sec
        sbc #1
        sta PLR + PL_VIEWHEIGHT + 2
        lda PLR + PL_VIEWHEIGHT + 3
        sbc #0
        sta PLR + PL_VIEWHEIGHT + 3
@floor: sec                             ; < 6 FRACUNIT: 6 FRACUNIT
        lda PLR + PL_VIEWHEIGHT
        sbc #0
        lda PLR + PL_VIEWHEIGHT + 1
        sbc #0
        lda PLR + PL_VIEWHEIGHT + 2
        sbc #6
        lda PLR + PL_VIEWHEIGHT + 3
        sbc #0
        bvc :+
        eor #$80
:       bpl @delta
        stz PLR + PL_VIEWHEIGHT
        stz PLR + PL_VIEWHEIGHT + 1
        lda #6
        sta PLR + PL_VIEWHEIGHT + 2
        stz PLR + PL_VIEWHEIGHT + 3
@delta: stz PLR + PL_DELTAVIEWHEIGHT
        stz PLR + PL_DELTAVIEWHEIGHT + 1
        stz PLR + PL_DELTAVIEWHEIGHT + 2
        stz PLR + PL_DELTAVIEWHEIGHT + 3
        FCALL onGround
        FCALL calcHeight
        lda PLR + PL_ATTACKER           ; an attacker that is not the player
        and PLR + PL_ATTACKER + 1
        cmp #$FF
        jeq @fade
        lda PLR + PL_ATTACKER
        cmp PLR + PL_MO
        bne @turn
        lda PLR + PL_ATTACKER + 1
        cmp PLR + PL_MO + 1
        jeq @fade
@turn:  FCALL angleToAttacker           ; delta = angle - mo->angle
        ldx #3
:       lda M_R,x
        sta PY_X1,x
        dex
        bpl :-
        jsr pt_mo
        sec
        lda PY_X1
        ldy #TH_ANGLO
        sbc (GC_MP),y
        sta PY_T
        lda PY_X1 + 1
        iny
        sbc (GC_MP),y
        sta PY_T + 1
        lda PY_X1 + 2
        ldy #TH_ANG
        sbc (GC_MP),y
        sta PY_T + 2
        lda PY_X1 + 3
        iny
        sbc (GC_MP),y
        sta PY_T + 3
        sec                             ; -ANG5 < delta || delta < ANG5
        lda #<NANG5                     ;   (unsigned): look at it
        sbc PY_T
        lda #>NANG5
        sbc PY_T + 1
        lda #^NANG5
        sbc PY_T + 2
        lda #<(NANG5 >> 24)
        sbc PY_T + 3
        bcc @look
        lda PY_T
        cmp #<ANG5
        lda PY_T + 1
        sbc #>ANG5
        lda PY_T + 2
        sbc #^ANG5
        lda PY_T + 3
        sbc #<(ANG5 >> 24)
        bcs @step
@look:  ldy #TH_ANGLO                   ; mo->angle = angle, the flash fades
        lda PY_X1
        sta (GC_MP),y
        iny
        lda PY_X1 + 1
        sta (GC_MP),y
        ldy #TH_ANG
        lda PY_X1 + 2
        sta (GC_MP),y
        iny
        lda PY_X1 + 3
        sta (GC_MP),y
        lda #D_TH
        jsr mo_dirty
        bra @fade
@step:  lda PY_T + 3                    ; delta < ANG180: + ANG5, else - ANG5
        bmi @minus
        clc
        ldy #TH_ANGLO
        lda (GC_MP),y
        adc #<ANG5
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc #>ANG5
        sta (GC_MP),y
        ldy #TH_ANG
        lda (GC_MP),y
        adc #^ANG5
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc #<(ANG5 >> 24)
        sta (GC_MP),y
        bra @turned
@minus: sec
        ldy #TH_ANGLO
        lda (GC_MP),y
        sbc #<ANG5
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #>ANG5
        sta (GC_MP),y
        ldy #TH_ANG
        lda (GC_MP),y
        sbc #^ANG5
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #<(ANG5 >> 24)
        sta (GC_MP),y
@turned:
        lda #D_TH
        jsr mo_dirty
        bra @reborn
@fade:  ldx #PL_DAMAGECOUNT             ; the damage flash fades
        jsr pt_dec
@reborn:
        lda PLR + PL_CMD_BUTTONS        ; use: play again
        and #UC_BT_USE
        beq :+
        lda #<UC_PST_REBORN
        sta PLR + PL_PLAYERSTATE
        lda #>UC_PST_REBORN
        sta PLR + PL_PLAYERSTATE + 1
:       rts

; ===========================================================================
; onGround: PY_ONG = mo->z <= mo->floorz
; ===========================================================================
        ROUTINE onGround
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_Z + 3                   ; !(floorz < z), signed
        ldx #3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        sec
        ldy #PO_B + MB_FLOORZ
        lda (GC_MP),y
        sbc GT_0
        iny
        lda (GC_MP),y
        sbc GT_1
        iny
        lda (GC_MP),y
        sbc GT_2
        iny
        lda (GC_MP),y
        sbc GT_3
        bvc :+
        eor #$80
:       bmi @air
        lda #1
        sta PY_ONG
        rts
@air:   stz PY_ONG
        rts

; ===========================================================================
; movePlayer: turn, and thrust when on the ground
; ===========================================================================
        ROUTINE movePlayer
        jsr pm_mo                       ; mo->angle += angleturn << 16
        clc
        ldy #TH_ANG
        lda (GC_MP),y
        adc PLR + PL_CMD_ANGLETURN
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        adc PLR + PL_CMD_ANGLETURN + 1
        sta (GC_MP),y
        lda #D_TH
        jsr mo_dirty
        FCALL onGround
        lda PLR + PL_CMD_FORWARDMOVE    ; forwardmove | sidemove
        ora PLR + PL_CMD_SIDEMOVE
        bne :+
        rts
:       lda PY_ONG
        beq @state
        lda PLR + PL_CMD_FORWARDMOVE    ; forward: the angle
        beq @side
        jsr pm_mo
        ldy #TH_ANG
        lda (GC_MP),y
        sta PY_ANG
        iny
        lda (GC_MP),y
        jsr pm_shr3
        lda PLR + PL_CMD_FORWARDMOVE
        jsr pm_thrust
@side:  lda PLR + PL_CMD_SIDEMOVE       ; sideways: the angle - ANG90
        beq @state
        jsr pm_mo
        ldy #TH_ANG
        lda (GC_MP),y
        sta PY_ANG
        iny
        lda (GC_MP),y
        sec
        sbc #$40
        jsr pm_shr3
        lda PLR + PL_CMD_SIDEMOVE
        jsr pm_thrust
@state: jsr pm_mo                       ; standing: the run animation
        ldy #PO_A + MA_STATE
        lda (GC_MP),y
        cmp #<UC_S_PLAY
        bne @done
        iny
        lda (GC_MP),y
        cmp #>UC_S_PLAY
        bne @done
        lda PLR + PL_MO
        sta GA_MO
        lda PLR + PL_MO + 1
        sta GA_MO + 1
        lda #<UC_S_PLAY_RUN1
        ldx #>UC_S_PLAY_RUN1
        FCALL P_SetMobjState
@done:  rts

pm_mo:  lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jmp mo_get

; pm_shr3: PY_ANG = (A:PY_ANG, a word) >> 3, the fine angle
pm_shr3:
        lsr a
        ror PY_ANG
        lsr a
        ror PY_ANG
        lsr a
        ror PY_ANG
        sta PY_ANG + 1
        rts

; pm_thrust (upstream's bobAndThrust): A = the move (a signed byte), PY_ANG
; the fine angle: m = move << 11 (PY_T), FixedMulAngle(m, finecosine) to
; the x momentum, FixedMulAngle(m, finesine) to the y momentum
pm_thrust:
        stz PY_T
        sta PY_T + 1
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx PY_T + 2
        stx PY_T + 3
        ldx #3
:       asl PY_T + 1
        rol PY_T + 2
        rol PY_T + 3
        dex
        bne :-
        lda PY_ANG                      ; x
        sta M_A
        lda PY_ANG + 1
        sta M_A + 1
        jsr finecosine
        FCALL thrustMul
        ldx #0
        jsr pm_addmom
        lda PY_ANG                      ; y
        sta M_A
        lda PY_ANG + 1
        sta M_A + 1
        jsr finesine
        FCALL thrustMul
        ldx #4
        ; fall into pm_addmom

; pm_addmom (upstream's addMom): mo->mom and player->mom += M_R, x for X =
; 0, y for X = 4; the mobj not CLEAN
pm_addmom:
        stx GT_4
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr pl_put
        jsr pm_mo
        lda GT_4
        clc
        adc #PO_C + MC_MOMX
        tay
        ldx #0
        clc
:       lda (GC_MP),y
        adc M_R,x
        sta (GC_MP),y
        iny
        inx
        txa
        eor #4
        bne :-
        lda #D_C
        jsr mo_dirty
        ldx GT_4
        ldy #0
        clc
:       lda PLR + PL_MOMX,x
        adc M_R,y
        sta PLR + PL_MOMX,x
        inx
        iny
        tya
        eor #4
        bne :-
        rts

; ===========================================================================
; thrustMul: M_R = FixedMulAngle(m = PY_T, M_R)
; ===========================================================================
        ROUTINE thrustMul
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda PY_T,x
        sta M_A,x
        dex
        bpl :-
        jmp fixmulang

; ===========================================================================
; calcHeight: the bobbing and the view height
; ===========================================================================
        ROUTINE calcHeight
        ldx #0                          ; bob = (FixedSquare(momx) +
        FCALL fixedSquare               ;        FixedSquare(momy)) >> 2
        ldx #3
:       lda M_R,x
        sta PY_BOB,x
        dex
        bpl :-
        ldx #4
        FCALL fixedSquare
        clc
        ldx #0
:       lda PY_BOB,x
        adc M_R,x
        sta PY_BOB,x
        inx
        txa
        eor #4
        bne :-
        ldx #2
:       lda PY_BOB + 3
        cmp #$80
        ror PY_BOB + 3
        ror PY_BOB + 2
        ror PY_BOB + 1
        ror PY_BOB
        dex
        bne :-
        sec                             ; bob > MAXBOB: MAXBOB
        lda #0
        sbc PY_BOB
        lda #0
        sbc PY_BOB + 1
        lda #MAXBOB_HI
        sbc PY_BOB + 2
        lda #0
        sbc PY_BOB + 3
        bvc :+
        eor #$80
:       bpl :+
        stz PY_BOB
        stz PY_BOB + 1
        lda #MAXBOB_HI
        sta PY_BOB + 2
        stz PY_BOB + 3
:       ldx #3
:       lda PY_BOB,x
        sta PLR + PL_BOB,x
        dex
        bpl :-
        lda PY_ONG                      ; in the air: viewz = z + VIEWHEIGHT
        bne @ground
        jsr ch_mo
        clc
        ldy #TH_Z
        lda (GC_MP),y
        sta PLR + PL_VIEWZ_G
        iny
        lda (GC_MP),y
        sta PLR + PL_VIEWZ_G + 1
        iny
        lda (GC_MP),y
        adc #<UC_VIEWHEIGHT_HI
        sta PLR + PL_VIEWZ_G + 2
        iny
        lda (GC_MP),y
        adc #0
        sta PLR + PL_VIEWZ_G + 3
        jmp ch_ceiling

        ; bob = FixedMulAngle(player->bob / 2, finesine(angle)),
        ; angle = (FINEANGLES / 20 * leveltime) & FINEMASK
@ground:
        lda G_LEVELTIME
        sta M_A
        lda G_LEVELTIME + 1
        sta M_A + 1
        lda #<409
        sta M_B
        lda #>409
        sta M_B + 1
        jsr umul16lo
        lda M_R
        sta M_A
        lda M_R + 1
        and #$1F
        sta M_A + 1
        jsr finesine
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda PLR + PL_BOB,x
        sta M_A,x
        dex
        bpl :-
        lda M_A + 3                     ; bob / 2, toward 0
        bpl @half
        inc M_A
        bne @half
        inc M_A + 1
        bne @half
        inc M_A + 2
        bne @half
        inc M_A + 3
@half:  lda M_A + 3
        cmp #$80
        ror M_A + 3
        ror M_A + 2
        ror M_A + 1
        ror M_A
        jsr fixmulang
        ldx #3
:       lda M_R,x
        sta PY_BOB,x
        dex
        bpl :-

        lda PLR + PL_PLAYERSTATE        ; alive: the view height moves
        ora PLR + PL_PLAYERSTATE + 1
        jne @viewz
        clc                             ; viewheight += deltaviewheight
        ldx #0
:       lda PLR + PL_VIEWHEIGHT,x
        adc PLR + PL_DELTAVIEWHEIGHT,x
        sta PLR + PL_VIEWHEIGHT,x
        inx
        txa
        eor #4
        bne :-
        sec                             ; > VIEWHEIGHT: VIEWHEIGHT, delta 0
        lda #0
        sbc PLR + PL_VIEWHEIGHT
        lda #0
        sbc PLR + PL_VIEWHEIGHT + 1
        lda #<UC_VIEWHEIGHT_HI
        sbc PLR + PL_VIEWHEIGHT + 2
        lda #0
        sbc PLR + PL_VIEWHEIGHT + 3
        bvc :+
        eor #$80
:       bpl @half2
        stz PLR + PL_VIEWHEIGHT
        stz PLR + PL_VIEWHEIGHT + 1
        lda #<UC_VIEWHEIGHT_HI
        sta PLR + PL_VIEWHEIGHT + 2
        stz PLR + PL_VIEWHEIGHT + 3
        stz PLR + PL_DELTAVIEWHEIGHT
        stz PLR + PL_DELTAVIEWHEIGHT + 1
        stz PLR + PL_DELTAVIEWHEIGHT + 2
        stz PLR + PL_DELTAVIEWHEIGHT + 3
@half2: sec                             ; < VIEWHEIGHT / 2: VIEWHEIGHT / 2,
        lda PLR + PL_VIEWHEIGHT         ;   and delta at least 1
        sbc #<VIEWHALF_LO
        lda PLR + PL_VIEWHEIGHT + 1
        sbc #>VIEWHALF_LO
        lda PLR + PL_VIEWHEIGHT + 2
        sbc #VIEWHALF_HI
        lda PLR + PL_VIEWHEIGHT + 3
        sbc #0
        bvc :+
        eor #$80
:       bpl @step
        lda #<VIEWHALF_LO
        sta PLR + PL_VIEWHEIGHT
        lda #>VIEWHALF_LO
        sta PLR + PL_VIEWHEIGHT + 1
        lda #VIEWHALF_HI
        sta PLR + PL_VIEWHEIGHT + 2
        stz PLR + PL_VIEWHEIGHT + 3
        lda PLR + PL_DELTAVIEWHEIGHT + 3        ; delta <= 0: 1
        bmi @one
        ora PLR + PL_DELTAVIEWHEIGHT + 2
        ora PLR + PL_DELTAVIEWHEIGHT + 1
        ora PLR + PL_DELTAVIEWHEIGHT
        bne @step
@one:   lda #1
        sta PLR + PL_DELTAVIEWHEIGHT
        stz PLR + PL_DELTAVIEWHEIGHT + 1
        stz PLR + PL_DELTAVIEWHEIGHT + 2
        stz PLR + PL_DELTAVIEWHEIGHT + 3
@step:  lda PLR + PL_DELTAVIEWHEIGHT    ; delta: += FRACUNIT / 4, but not
        ora PLR + PL_DELTAVIEWHEIGHT + 1        ; to 0
        ora PLR + PL_DELTAVIEWHEIGHT + 2
        ora PLR + PL_DELTAVIEWHEIGHT + 3
        beq @viewz
        clc
        lda PLR + PL_DELTAVIEWHEIGHT + 1
        adc #$40
        sta PLR + PL_DELTAVIEWHEIGHT + 1
        lda PLR + PL_DELTAVIEWHEIGHT + 2
        adc #0
        sta PLR + PL_DELTAVIEWHEIGHT + 2
        lda PLR + PL_DELTAVIEWHEIGHT + 3
        adc #0
        sta PLR + PL_DELTAVIEWHEIGHT + 3
        ora PLR + PL_DELTAVIEWHEIGHT + 2
        ora PLR + PL_DELTAVIEWHEIGHT + 1
        ora PLR + PL_DELTAVIEWHEIGHT
        bne @viewz
        lda #1
        sta PLR + PL_DELTAVIEWHEIGHT

@viewz: jsr ch_mo                       ; viewz = z + viewheight + bob
        ldy #TH_Z
        ldx #0
        clc
:       lda (GC_MP),y
        adc PLR + PL_VIEWHEIGHT,x
        sta PLR + PL_VIEWZ_G,x
        iny
        inx
        txa
        eor #4
        bne :-
        ldx #0
        clc
:       lda PLR + PL_VIEWZ_G,x
        adc PY_BOB,x
        sta PLR + PL_VIEWZ_G,x
        inx
        txa
        eor #4
        bne :-
        ; fall into ch_ceiling

; ch_ceiling (upstream's viewCeiling): viewz at most ceilingz - 4 FRACUNIT
; (GC_MP the player's mobj)
ch_ceiling:
        ldy #PO_B + MB_CEILZ
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        iny
        lda (GC_MP),y
        sec
        sbc #4
        sta GT_2
        iny
        lda (GC_MP),y
        sbc #0
        sta GT_3
        sec                             ; (ceilingz - 4) < viewz: the ceiling
        lda GT_0
        sbc PLR + PL_VIEWZ_G
        lda GT_1
        sbc PLR + PL_VIEWZ_G + 1
        lda GT_2
        sbc PLR + PL_VIEWZ_G + 2
        lda GT_3
        sbc PLR + PL_VIEWZ_G + 3
        bvc :+
        eor #$80
:       bpl @done
        ldx #3
:       lda GT_0,x
        sta PLR + PL_VIEWZ_G,x
        dex
        bpl :-
@done:  rts

ch_mo:  lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jmp mo_get

; ===========================================================================
; fixedSquare: M_R = FixedSquare(a), a = the player's mom (X = 0 x, 4 y):
;   (a + alw) * ahw + ((alw * alw) >> 16), alw = a & $FFFF, ahw = a >> 16
; ===========================================================================
        ROUTINE fixedSquare
        stx GT_2
        lda PLR + PL_MOMX,x             ; alw * alw
        sta M_A
        sta M_B
        lda PLR + PL_MOMX + 1,x
        sta M_A + 1
        sta M_B + 1
        jsr umul16
        lda M_R + 2                     ; (alw * alw) >> 16
        sta GT_0
        lda M_R + 3
        sta GT_1
        ldx GT_2
        lda PLR + PL_MOMX,x             ; a + alw
        asl a
        sta M_A
        lda PLR + PL_MOMX + 1,x
        rol a
        sta M_A + 1
        lda PLR + PL_MOMX + 2,x
        adc #0
        sta M_A + 2
        lda PLR + PL_MOMX + 3,x
        adc #0
        sta M_A + 3
        lda PLR + PL_MOMX + 2,x         ; * ahw, sign extended
        sta M_B
        lda PLR + PL_MOMX + 3,x
        sta M_B + 1
        ldy #0
        cmp #$80
        bcc :+
        dey
:       sty M_B + 2
        sty M_B + 3
        jsr mul32
        clc
        lda M_R
        adc GT_0
        sta M_R
        lda M_R + 1
        adc GT_1
        sta M_R + 1
        bcc :+
        inc M_R + 2
        bne :+
        inc M_R + 3
:       rts

; ===========================================================================
; angleToAttacker: M_R = R_PointToAngle2(mo->x, mo->y, attacker->x,
; attacker->y)
; ===========================================================================
        ROUTINE angleToAttacker
        lda PLR + PL_ATTACKER
        ldx PLR + PL_ATTACKER + 1
        jsr mo_get
        ldy #TH_X + 7                   ; the attacker's x, y
        ldx #7
:       lda (GC_MP),y
        sta M_A,x
        dey
        dex
        bpl :-
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr mo_get
        sec                             ; dx
        ldy #TH_X
        ldx #0
:       lda M_A,x
        sbc (GC_MP),y
        sta M_A,x
        iny
        inx
        txa
        eor #4
        bne :-
        sec                             ; dy
:       lda M_A,x
        sbc (GC_MP),y
        sta M_A,x
        iny
        inx
        txa
        eor #8
        bne :-
        jmp pta3

; ===========================================================================
; specialSector: P_PlayerInSpecialSector: the damaging floors, the secrets
; and the end of E1M8. A = the player's sector.
; ===========================================================================
        ROUTINE specialSector
        sta GT_6
        lda PLR + PL_MO                 ; not in the air: z = the floor
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #TH_Z + 3
        ldx #3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        lda GT_6
        jsr sec_get
        ldy #SEC_FLOOR
        ldx #0
:       lda (GC_SP),y
        cmp GT_0,x
        bne @done
        iny
        inx
        cpx #4
        bne :-
        ldy #SEC_G + SG_SPECIAL
        lda (GC_SP),y
        cmp #5                          ; 5: 10 damage every 32 tics, no suit
        bne :+
        lda #10
        bra @suit
:       cmp #7                          ; 7: 5 damage
        bne :+
        lda #5
        bra @suit
:       cmp #16                         ; 16: 20 damage, also with the suit
        bne @s9                         ;   when P_Random() < 5
        lda PLR + PL_POWERS_0 + 2 * UC_PW_IRONFEET
        ora PLR + PL_POWERS_0 + 2 * UC_PW_IRONFEET + 1
        beq @s20
        jsr g_random
        cmp #5
        bcs @done
@s20:   lda #20
        bra @hurt
@s9:    cmp #9                          ; 9: a secret, found
        bne @s11
        inc PLR + PL_SECRETCOUNT
        bne :+
        inc PLR + PL_SECRETCOUNT + 1
:       lda #0
        sta (GC_SP),y
        lda #2
        jmp sec_dirty
@s11:   cmp #11                         ; 11: the end of E1M8
        bne @done
        lda PLR + PL_CHEATS
        and #<~UC_CF_GODMODE
        sta PLR + PL_CHEATS
        lda #20
        jsr @hurt
        sec                             ; health <= 10 (N of health - 11)
        lda PLR + PL_HEALTH
        sbc #11
        lda PLR + PL_HEALTH + 1
        sbc #0
        bpl @done
        FCALL G_ExitLevel
@done:  rts
@suit:  tax                             ; (suitHurt) the radiation suit
        lda PLR + PL_POWERS_0 + 2 * UC_PW_IRONFEET
        ora PLR + PL_POWERS_0 + 2 * UC_PW_IRONFEET + 1
        bne @done
        txa
@hurt:  ldx #0                          ; (hurt) P_DamageMobj(player->mo,
        FCALL hurt32                    ;   NULL, NULL, A) when leveltime &
        bcc @done                       ;   31 is 0
        FCALL P_DamageMobj
        rts

; ===========================================================================
; hurt32: A:X = a damage: C set and GA_0-7 = P_DamageMobj's arguments
; (player->mo, NULL, NULL, A:X) when (int16_t)leveltime & $1F is 0, else C
; clear
; ===========================================================================
        ROUTINE hurt32
        sta GA_6
        stx GA_7
        lda G_LEVELTIME
        and #$1F
        bne @no
        lda PLR + PL_MO
        sta GA_0
        lda PLR + PL_MO + 1
        sta GA_1
        lda #$FF                        ; no inflictor, no source
        sta GA_2
        sta GA_3
        sta GA_4
        sta GA_5
        sec
        rts
@no:    clc
        rts
