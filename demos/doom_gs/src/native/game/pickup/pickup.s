; game/pickup/pickup.s: part pickup's pickups (docs/GAME.md). A GPL-2
; derivative of upstream's
; p_inter65.s (Doom8088: Apple IIgs Edition, GPL-2): P_TouchSpecialThing
; with pickTab's cases, P_GivePower and the give functions. The one
; product (giveAmmo's clips times clipammo, and P_GiveArmor's type times
; 100) is math.s's umul16lo, as upstream's IIGS_MulLo16.
;
;   P_TouchSpecialThing  GA_0-1 = the special thing, GA_2-3 = the toucher
;                (mobj slots): out of reach (the toucher's height below
;                the thing's z over its own, or the thing 8 units or more
;                below it) or a dead toucher: nothing. Else the thing's
;                sprite in pickTab (none: I_Error) gives its case, its
;                message and its argument; the case says whether the
;                player takes it; if so the message (not a card the player
;                has), the item count (MF_COUNTITEM), P_RemoveMobj, the
;                bonus count + BONUSADD and the pickup sound (the
;                S_StartSound hook, PICKUP_SOUND in bit 7, the player's
;                mobj its origin)
;   P_GivePower  A = a power: A = 1, C set when given (A = 0, C clear not)
;   and the helpers of pk.inc's list.
;
; Signed compares are upstream's: a 32-bit subtract with the overflow
; corrected for the reach; the sign of a 16-bit difference alone (no
; overflow correction: "signed, small values") for the health, armour and
; ammo limits, as upstream's bmi after a cmp.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/pickup/pk.inc"

        .export P_TouchSpecialThing, P_GivePower, giveBody, p_inter_giveAmmo
        .export giveWeapon, givePower, pkArmor, pkHealthBonus, pkSoul
        .export pkArmorBonus, pkCard, pkBody, pkPower, pkClip, pkAmmo
        .export pkBackpack, pkWeapon
        .import mo_get, mo_dirty, umul16lo, S_StartSound, I_Error
        .import weaponinfo
        .import fc_call, fc_unbuilt

        .assert UC_WP_FIST = 0, error, "WP_FIST is not 0"

; SETHEALTH: player->health = player->mo->health = PK_V; C set; rts
; (upstream's setHealth, which three routines of different groups end in)
.macro SETHEALTH
        lda PK_V
        sta PLR + PL_HEALTH
        lda PK_V+1
        sta PLR + PL_HEALTH + 1
        lda PLR + PL_MO
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #LN_A + MA_HEALTH
        lda PK_V
        sta (GC_MP),y
        iny
        lda PK_V+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
        sec
        rts
.endmacro

; CLAMP lim, top: PK_V = top when PK_V - lim is not negative (upstream's
; cmp ##lim, bmi: the sign of the 16-bit difference)
.macro CLAMP lim, top
        .local keep
        sec
        lda PK_V
        sbc #<(lim)
        lda PK_V+1
        sbc #>(lim)
        bmi keep
        lda #<(top)
        sta PK_V
        lda #>(top)
        sta PK_V+1
keep:
.endmacro

; ---------------------------------------------------------------------------
; P_TouchSpecialThing (GT_0-3: the thing's z less the toucher's)
; ---------------------------------------------------------------------------
        ROUTINE P_TouchSpecialThing
        lda GA_0
        sta PK_SPEC
        lda GA_1
        sta PK_SPEC+1
        lda GA_2
        sta PK_TCH
        lda GA_3
        sta PK_TCH+1
        lda PK_SPEC             ; delta = special->z - toucher->z
        ldx PK_SPEC+1
        jsr mo_get
        ldy #TH_Z
        ldx #0
:       lda (GC_MP),y
        sta GT_0,x
        iny
        inx
        cpx #4
        bne :-
        lda PK_TCH
        ldx PK_TCH+1
        jsr mo_get
        sec
        ldy #TH_Z
        lda GT_0
        sbc (GC_MP),y
        sta GT_0
        ldy #TH_Z+1
        lda GT_1
        sbc (GC_MP),y
        sta GT_1
        ldy #TH_Z+2
        lda GT_2
        sbc (GC_MP),y
        sta GT_2
        ldy #TH_Z+3
        lda GT_3
        sbc (GC_MP),y
        sta GT_3
        sec                     ; toucher->height < delta: out of reach
        ldy #LN_B + MB_HEIGHT
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
:       bmi @out
        lda GT_2                ; delta < -8 * FRACUNIT: out of reach
        cmp #$F8
        lda GT_3
        sbc #$FF
        bvc :+
        eor #$80
:       bmi @out
        ldy #LN_A + MA_HEALTH   ; a dead toucher: no
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        beq @out
        lda (GC_MP),y
        bmi @out
        lda #UC_SFX_ITEMUP
        sta PK_SND
        lda PK_SPEC             ; the sprite in pickTab
        ldx PK_SPEC+1
        jsr mo_get
        ldy #TH_SPR
        lda (GC_MP),y
        ldx #0
:       cmp pk_spr,x
        beq @found
        inx
        cpx #PK_N
        bcc :-
        jmp I_Error             ; "P_SpecialThing: Unknown gettable thing"
@out:   rts
@found: lda pk_msglo,x          ; the message, the argument, the case
        sta PK_MSG
        lda pk_msghi,x
        sta PK_MSG+1
        lda pk_arglo,x
        sta PK_ARG
        lda pk_arghi,x
        sta PK_ARG+1
        lda pk_case,x
        tax
        jsr @case               ; carry clear: not taken
        bcc @out
        ldx PK_MSG+1            ; the message (none for a card the
        cpx #NO_MSG             ;   player has): the bridge's "ref" of a
        beq :+                  ;   symbol: tag 1, the number, offset 0
        stx PLR + PL_MESSAGE + 2
        lda PK_MSG
        sta PLR + PL_MESSAGE + 1
        lda #1
        sta PLR + PL_MESSAGE
        stz PLR + PL_MESSAGE + 3
        stz PLR + PL_MESSAGE + 4
:       lda PK_SPEC             ; an item to count
        ldx PK_SPEC+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_COUNTITEM_HI
        beq :+
        inc PLR + PL_ITEMCOUNT
        bne :+
        inc PLR + PL_ITEMCOUNT + 1
:       lda PK_SPEC             ; the thing goes away
        ldx PK_SPEC+1
        FCALL P_RemoveMobj
        clc                     ; bonuscount += BONUSADD
        lda PLR + PL_BONUSCOUNT
        adc #<U_BONUSADD
        sta PLR + PL_BONUSCOUNT
        lda PLR + PL_BONUSCOUNT + 1
        adc #>U_BONUSADD
        sta PLR + PL_BONUSCOUNT + 1
        lda PLR + PL_MO         ; S_StartSound(player->mo, sound |
        ldx PLR + PL_MO + 1     ;   PICKUP_SOUND)
        phx
        tax
        ply
        lda PK_SND
        ora #PICKUP_SOUND
        jmp S_StartSound
@case:  jmp (pk_jump,x)

; the cases through FCALL (the placement decides where each one is)
pk_c_armor:
        FCALL pkArmor
        rts
pk_c_hbonus:
        FCALL pkHealthBonus
        rts
pk_c_abonus:
        FCALL pkArmorBonus
        rts
pk_c_soul:
        FCALL pkSoul
        rts
pk_c_card:
        FCALL pkCard
        rts
pk_c_body:
        FCALL pkBody
        rts
pk_c_power:
        FCALL pkPower
        rts
pk_c_clip:
        FCALL pkClip
        rts
pk_c_ammo:
        FCALL pkAmmo
        rts
pk_c_backpack:
        FCALL pkBackpack
        rts
pk_c_weapon:
        FCALL pkWeapon
        rts

; pickTab (upstream's p_inter65.s:1144-1169, the same order): the sprite,
; the case, the message's symbol and the argument of each pickup
C_ARMOR = 0
C_HBONUS = 2
C_ABONUS = 4
C_SOUL = 6
C_CARD = 8
C_BODY = 10
C_POWER = 12
C_CLIP = 14
C_AMMO = 16
C_BACKPACK = 18
C_WEAPON = 20
pk_jump:
        .addr pk_c_armor, pk_c_hbonus, pk_c_abonus, pk_c_soul, pk_c_card
        .addr pk_c_body, pk_c_power, pk_c_clip, pk_c_ammo, pk_c_backpack
        .addr pk_c_weapon

PK_N = 25                       ; (six parallel arrays, entry by entry)
pk_spr:
        .byte UC_SPR_ARM1, UC_SPR_ARM2, UC_SPR_BON1, UC_SPR_BON2, UC_SPR_SOUL
        .byte UC_SPR_BKEY, UC_SPR_YKEY, UC_SPR_RKEY, UC_SPR_STIM, UC_SPR_MEDI
        .byte UC_SPR_PINS, UC_SPR_SUIT, UC_SPR_PMAP, UC_SPR_PVIS, UC_SPR_CLIP
        .byte UC_SPR_AMMO, UC_SPR_ROCK, UC_SPR_BROK, UC_SPR_SHEL, UC_SPR_SBOX
        .byte UC_SPR_BPAK, UC_SPR_MGUN, UC_SPR_CSAW, UC_SPR_LAUN, UC_SPR_SHOT
pk_case:
        .byte C_ARMOR, C_ARMOR, C_HBONUS, C_ABONUS, C_SOUL
        .byte C_CARD, C_CARD, C_CARD, C_BODY, C_BODY
        .byte C_POWER, C_POWER, C_POWER, C_POWER, C_CLIP
        .byte C_AMMO, C_AMMO, C_AMMO, C_AMMO, C_AMMO
        .byte C_BACKPACK, C_WEAPON, C_WEAPON, C_WEAPON, C_WEAPON
pk_msglo:
        .byte <(SYM_p_inter_msgArmor), <(SYM_p_inter_msgMega), <(SYM_p_inter_msgHthBonus)
        .byte <(SYM_p_inter_msgArmBonus), <(SYM_p_inter_msgSuper), <(SYM_p_inter_msgBlueCard)
        .byte <(SYM_p_inter_msgYelwCard), <(SYM_p_inter_msgRedCard), <(SYM_p_inter_msgStim)
        .byte <(SYM_p_inter_msgMedikit), <(SYM_p_inter_msgInvis), <(SYM_p_inter_msgSuit)
        .byte <(SYM_p_inter_msgMap), <(SYM_p_inter_msgVisor), <(SYM_p_inter_msgClip)
        .byte <(SYM_p_inter_msgClipBox), <(SYM_p_inter_msgRocket), <(SYM_p_inter_msgRockBox)
        .byte <(SYM_p_inter_msgShells), <(SYM_p_inter_msgShellBox), <(SYM_p_inter_msgBackpack)
        .byte <(SYM_p_inter_msgChaingun), <(SYM_p_inter_msgChainsaw), <(SYM_p_inter_msgLauncher)
        .byte <(SYM_p_inter_msgShotgun)
pk_msghi:
        .byte >(SYM_p_inter_msgArmor), >(SYM_p_inter_msgMega), >(SYM_p_inter_msgHthBonus)
        .byte >(SYM_p_inter_msgArmBonus), >(SYM_p_inter_msgSuper), >(SYM_p_inter_msgBlueCard)
        .byte >(SYM_p_inter_msgYelwCard), >(SYM_p_inter_msgRedCard), >(SYM_p_inter_msgStim)
        .byte >(SYM_p_inter_msgMedikit), >(SYM_p_inter_msgInvis), >(SYM_p_inter_msgSuit)
        .byte >(SYM_p_inter_msgMap), >(SYM_p_inter_msgVisor), >(SYM_p_inter_msgClip)
        .byte >(SYM_p_inter_msgClipBox), >(SYM_p_inter_msgRocket), >(SYM_p_inter_msgRockBox)
        .byte >(SYM_p_inter_msgShells), >(SYM_p_inter_msgShellBox), >(SYM_p_inter_msgBackpack)
        .byte >(SYM_p_inter_msgChaingun), >(SYM_p_inter_msgChainsaw), >(SYM_p_inter_msgLauncher)
        .byte >(SYM_p_inter_msgShotgun)
pk_arglo:
        .byte <(1), <(2), <(0), <(0)
        .byte <(0), <(UC_IT_BLUECARD), <(UC_IT_YELLOWCARD), <(UC_IT_REDCARD)
        .byte <(10), <(25), <(UC_PW_INVISIBILITY), <(UC_PW_IRONFEET)
        .byte <(UC_PW_ALLMAP), <(UC_PW_INFRARED), <(0), <(UC_AM_CLIP + 5 * 256)
        .byte <(UC_AM_MISL + 1 * 256), <(UC_AM_MISL + 5 * 256), <(UC_AM_SHELL + 1 * 256), <(UC_AM_SHELL + 5 * 256)
        .byte <(0), <(UC_WP_CHAINGUN + 1 * 256), <(UC_WP_CHAINSAW), <(UC_WP_MISSILE)
        .byte <(UC_WP_SHOTGUN + 1 * 256)
pk_arghi:
        .byte >(1), >(2), >(0), >(0)
        .byte >(0), >(UC_IT_BLUECARD), >(UC_IT_YELLOWCARD), >(UC_IT_REDCARD)
        .byte >(10), >(25), >(UC_PW_INVISIBILITY), >(UC_PW_IRONFEET)
        .byte >(UC_PW_ALLMAP), >(UC_PW_INFRARED), >(0), >(UC_AM_CLIP + 5 * 256)
        .byte >(UC_AM_MISL + 1 * 256), >(UC_AM_MISL + 5 * 256), >(UC_AM_SHELL + 1 * 256), >(UC_AM_SHELL + 5 * 256)
        .byte >(0), >(UC_WP_CHAINGUN + 1 * 256), >(UC_WP_CHAINSAW), >(UC_WP_MISSILE)
        .byte >(UC_WP_SHOTGUN + 1 * 256)
        .assert pk_case - pk_spr = PK_N && pk_msglo - pk_case = PK_N && pk_msghi - pk_msglo = PK_N && pk_arglo - pk_msghi = PK_N && * - pk_arghi = PK_N, error, "pickTab's arrays"

; ---------------------------------------------------------------------------
; The cases: PK_ARG the argument; C set when the player takes the thing
; ---------------------------------------------------------------------------

; pkArmor: P_GiveArmor(player, C): armortype C with C * 100 points, when
; that is more than now
        ROUTINE pkArmor
        lda PK_ARG
        sta M_A
        lda PK_ARG+1
        sta M_A+1
        lda #100
        sta M_B
        stz M_B+1
        jsr umul16lo
        sec                     ; armorpoints >= hits: no (the sign of
        lda M_R                 ;   hits - armorpoints, or 0)
        sbc PLR + PL_ARMORPOINTS
        sta GT_0
        lda M_R+1
        sbc PLR + PL_ARMORPOINTS + 1
        bmi @no
        ora GT_0
        beq @no
        lda M_R
        sta PLR + PL_ARMORPOINTS
        lda M_R+1
        sta PLR + PL_ARMORPOINTS + 1
        lda PK_ARG
        sta PLR + PL_ARMORTYPE
        lda PK_ARG+1
        sta PLR + PL_ARMORTYPE + 1
        sec
        rts
@no:    clc
        rts

; pkHealthBonus: health + 1, at most 200
        ROUTINE pkHealthBonus
        clc
        lda PLR + PL_HEALTH
        adc #1
        sta PK_V
        lda PLR + PL_HEALTH + 1
        adc #0
        sta PK_V+1
        CLAMP 201, 200
        SETHEALTH

; pkSoul: health + 100, at most 200; the power-up sound
        ROUTINE pkSoul
        lda #UC_SFX_GETPOW
        sta PK_SND
        clc
        lda PLR + PL_HEALTH
        adc #100
        sta PK_V
        lda PLR + PL_HEALTH + 1
        adc #0
        sta PK_V+1
        CLAMP 201, 200
        SETHEALTH

; pkArmorBonus: armorpoints + 1, at most 200; green armour if none
        ROUTINE pkArmorBonus
        clc
        lda PLR + PL_ARMORPOINTS
        adc #1
        sta PK_V
        lda PLR + PL_ARMORPOINTS + 1
        adc #0
        sta PK_V+1
        CLAMP 201, 200
        lda PK_V
        sta PLR + PL_ARMORPOINTS
        lda PK_V+1
        sta PLR + PL_ARMORPOINTS + 1
        lda PLR + PL_ARMORTYPE
        ora PLR + PL_ARMORTYPE + 1
        bne :+
        lda #1
        sta PLR + PL_ARMORTYPE
:       sec
        rts

; pkCard: the card C; no message when the player has it (P_GiveCard then
; does nothing), else bonuscount = BONUSADD and the card
        ROUTINE pkCard
        lda PK_ARG
        asl a
        tax
        lda PLR + PL_CARDS_0,x
        ora PLR + PL_CARDS_0 + 1,x
        beq @new
        lda #NO_MSG             ; (the high byte says none)
        sta PK_MSG+1
        sec
        rts
@new:   lda #<U_BONUSADD
        sta PLR + PL_BONUSCOUNT
        lda #>U_BONUSADD
        sta PLR + PL_BONUSCOUNT + 1
        lda #1
        sta PLR + PL_CARDS_0,x
        stz PLR + PL_CARDS_0 + 1,x
        sec
        rts

; pkBody: P_GiveBody(player, C)
        ROUTINE pkBody
        lda PK_ARG
        ldx PK_ARG+1
        FCALL giveBody
        rts

; pkPower: P_GivePower(player, C), the power-up sound
        ROUTINE pkPower
        lda PK_ARG
        FCALL givePower
        bcc :+
        lda #UC_SFX_GETPOW      ; (C stays set)
        sta PK_SND
:       rts

; pkClip: a clip: P_GiveAmmo(player, am_clip, dropped ? 0 : 1)
        ROUTINE pkClip
        lda PK_SPEC
        ldx PK_SPEC+1
        jsr mo_get
        ldx #1
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_DROPPED_HI
        beq :+
        dex
:       lda #UC_AM_CLIP
        FCALL p_inter_giveAmmo
        rts

; pkAmmo: P_GiveAmmo(player, C & $FF, C >> 8)
        ROUTINE pkAmmo
        ldx PK_ARG+1
        lda PK_ARG
        FCALL p_inter_giveAmmo
        rts

; pkBackpack: twice the maximum ammo (once), and a clip of each ammo
        ROUTINE pkBackpack
        lda PLR + PL_BACKPACK
        ora PLR + PL_BACKPACK + 1
        bne @give
        ldx #2 * UC_NUMAMMO - 2
:       asl PLR + PL_MAXAMMO_0,x
        rol PLR + PL_MAXAMMO_0 + 1,x
        dex
        dex
        bpl :-
        lda #1
        sta PLR + PL_BACKPACK
        stz PLR + PL_BACKPACK + 1
@give:  stz PK_I
:       lda PK_I
        ldx #1
        FCALL p_inter_giveAmmo
        inc PK_I
        lda PK_I
        cmp #UC_NUMAMMO
        bcc :-
        sec
        rts

; pkWeapon: P_GiveWeapon(player, C & $FF, dropped), dropped only when C >>
; 8 is not 0 and the thing is MF_DROPPED; the weapon sound
        ROUTINE pkWeapon
        ldx #0
        lda PK_ARG+1
        beq :+
        lda PK_SPEC
        ldx PK_SPEC+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_DROPPED_HI
        tax
:       lda PK_ARG
        FCALL giveWeapon
        bcc :+
        lda #UC_SFX_WPNUP       ; (C stays set)
        sta PK_SND
:       rts

; ---------------------------------------------------------------------------
; giveBody: P_GiveBody(player, A:X): health + A:X, at most 100, when the
; health is below 100
; ---------------------------------------------------------------------------
        ROUTINE giveBody
        sta PK_V
        stx PK_V+1
        sec                     ; health >= 100: no (the sign of health -
        lda PLR + PL_HEALTH     ;   100)
        sbc #100
        lda PLR + PL_HEALTH + 1
        sbc #0
        bmi :+
        clc
        rts
:       clc
        lda PK_V
        adc PLR + PL_HEALTH
        sta PK_V
        lda PK_V+1
        adc PLR + PL_HEALTH + 1
        sta PK_V+1
        CLAMP 101, 100
        SETHEALTH

; ---------------------------------------------------------------------------
; p_inter_giveAmmo: P_GiveAmmo(player, A = ammo, X = clips (0: half a
; clip)): C set when taken. With no ammo before, a better weapon for it
; comes up. (GT_0-1 the amount, GT_2 a difference's low byte, GT_0-1 then
; the ready weapon)
; ---------------------------------------------------------------------------
        ROUTINE p_inter_giveAmmo
        cmp #UC_AM_NOAMMO
        bne :+
        clc
        rts
:       stx PK_NUM
        asl a
        sta PK_AMMO
        tay
        lda PLR + PL_AMMO_0,y   ; full: no
        cmp PLR + PL_MAXAMMO_0,y
        bne @take
        lda PLR + PL_AMMO_0 + 1,y
        cmp PLR + PL_MAXAMMO_0 + 1,y
        bne @take
        clc
        rts
@take:  lda PLR + PL_AMMO_0,y
        sta PK_OLD
        lda PLR + PL_AMMO_0 + 1,y
        sta PK_OLD+1
        lda PK_NUM              ; num * clipammo, or half a clip
        beq @half
        sta M_A
        stz M_A+1
        lda pk_clip,y
        sta M_B
        lda pk_clip+1,y
        sta M_B+1
        jsr umul16lo
        lda M_R
        ldx M_R+1
        bra @skill
@half:  lda pk_half,y
        ldx pk_half+1,y
@skill: sta GT_0
        stx GT_1
        lda G_GAMESKILL + 1     ; twice in baby and nightmare
        bne @add
        lda G_GAMESKILL
        cmp #UC_SK_BABY
        beq @twice
        cmp #UC_SK_NIGHTMARE
        bne @add
@twice: asl GT_0
        rol GT_1
@add:   ldy PK_AMMO             ; ammo += num, at most maxammo (the sign
        clc                     ;   of the sum - maxammo, or 0: keep)
        lda GT_0
        adc PK_OLD
        sta GT_0
        lda GT_1
        adc PK_OLD+1
        sta GT_1
        sec
        lda GT_0
        sbc PLR + PL_MAXAMMO_0,y
        sta GT_2
        lda GT_1
        sbc PLR + PL_MAXAMMO_0 + 1,y
        bmi @store
        ora GT_2
        beq @store
        lda PLR + PL_MAXAMMO_0,y
        sta GT_0
        lda PLR + PL_MAXAMMO_0 + 1,y
        sta GT_1
@store: lda GT_0
        sta PLR + PL_AMMO_0,y
        lda GT_1
        sta PLR + PL_AMMO_0 + 1,y
        lda PK_OLD              ; some ammo before: done
        ora PK_OLD+1
        beq @none
        sec
        rts
@none:  lda PLR + PL_READYWEAPON ; none before: a better weapon
        sta GT_0
        lda PLR + PL_READYWEAPON + 1
        sta GT_1
        cpy #2 * UC_AM_CLIP
        bne @shell
        jsr @fist               ; clip: the chaingun or the pistol instead
        bne @done               ;   of the fist
        lda PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINGUN
        ora PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINGUN + 1
        beq :+
        lda #UC_WP_CHAINGUN
        bra @pend
:       lda #UC_WP_PISTOL
        bra @pend
@shell: cpy #2 * UC_AM_SHELL
        bne @cell
        ldx #UC_WP_SHOTGUN      ; shell: the shotgun instead of the fist
        bra @fp                 ;   or the pistol
@cell:  cpy #2 * UC_AM_CELL
        bne @misl
        ldx #UC_WP_PLASMA       ; cell: the plasma gun, the same
@fp:    jsr @fist
        beq @own
        lda GT_1
        bne @done
        lda GT_0
        cmp #UC_WP_PISTOL
        bne @done
@own:   txa
        asl a
        tay
        lda PLR + PL_WEAPONOWNED_0,y
        ora PLR + PL_WEAPONOWNED_0 + 1,y
        beq @done
        txa
        bra @pend
@misl:  cpy #2 * UC_AM_MISL
        bne @done
        jsr @fist               ; rockets: the launcher instead of the fist
        bne @done
        lda PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_MISSILE
        ora PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_MISSILE + 1
        beq @done
        lda #UC_WP_MISSILE
@pend:  sta PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
@done:  sec
        rts
@fist:  lda GT_0                ; Z set: the ready weapon is the fist
        ora GT_1
        rts
; clipammo[] and clipammo[] / 2 by ammo type (the release's tables)
pk_clip:
        .word U_CLIPAMMO_0, U_CLIPAMMO_1, U_CLIPAMMO_2, U_CLIPAMMO_3
pk_half:
        .word U_HALFCLIP_0, U_HALFCLIP_1, U_HALFCLIP_2, U_HALFCLIP_3
        .assert UC_NUMAMMO = 4, error, "clipAmmo's length"

; ---------------------------------------------------------------------------
; giveWeapon: P_GiveWeapon(player, A = weapon, X = dropped): its ammo (1
; clip dropped, else 2) and the weapon; C set if either
; ---------------------------------------------------------------------------
        ROUTINE giveWeapon
        sta PK_WPN
        stx PK_DROP
        asl a                   ; weaponinfo[weapon].ammo: damage's table
        adc PK_WPN              ;   in the core (12 bytes a weapon)
        asl a
        asl a
        tax
        lda weaponinfo + UO_WI_AMMO,x
        cmp #UC_AM_NOAMMO
        beq @none
        ldx #2                  ; dropped: 1 clip, else 2
        ldy PK_DROP
        beq :+
        ldx #1
:       FCALL p_inter_giveAmmo
        lda #0
        rol a                   ; gaveammo = carry
        bra @gave
@none:  lda #0
@gave:  sta PK_GAVE
        lda PK_WPN              ; the weapon: new, or not
        asl a
        tax
        lda PLR + PL_WEAPONOWNED_0,x
        ora PLR + PL_WEAPONOWNED_0 + 1,x
        bne @had
        lda #1
        sta PLR + PL_WEAPONOWNED_0,x
        stz PLR + PL_WEAPONOWNED_0 + 1,x
        lda PK_WPN
        sta PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
        sec
        rts
@had:   lda PK_GAVE             ; only the ammo
        lsr a
        rts
        .assert UC_NUMWEAPONS = 9, error, "weaponinfo's length"

; ---------------------------------------------------------------------------
; P_GivePower: A = a power: A = 1 (C set) given, 0 (C clear) not
; ---------------------------------------------------------------------------
        ROUTINE P_GivePower
        FCALL givePower
        lda #0
        rol a
        rts

; ---------------------------------------------------------------------------
; givePower: P_GivePower(player, A): the power for its time (unless the
; player has it for ever: a negative count); the map only once; strength
; also heals; invisibility makes the player's mobj a shadow (MF_SHADOW,
; and the renderer's copy of it, RTHING's flags bit 0). C set when given
; ---------------------------------------------------------------------------
        ROUTINE givePower
        sta PK_PWR
        cmp #UC_PW_INVISIBILITY
        bne @map
        lda PLR + PL_MO         ; mo->flags |= MF_SHADOW
        ldx PLR + PL_MO + 1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        ora #UC_MF_SHADOW_HI
        sta (GC_MP),y
        ldy #TH_FLAGS
        lda (GC_MP),y
        ora #1
        sta (GC_MP),y
        lda #D_RTH | D_B
        jsr mo_dirty
        bra @time
@map:   cmp #UC_PW_ALLMAP
        bne @str
        lda PLR + PL_POWERS_0 + 2 * UC_PW_ALLMAP
        ora PLR + PL_POWERS_0 + 2 * UC_PW_ALLMAP + 1
        beq @time
        clc                     ; the map again: no
        rts
@str:   cmp #UC_PW_STRENGTH
        bne @time
        lda #100
        ldx #0
        FCALL giveBody
@time:  lda PK_PWR              ; the time, unless negative (for ever)
        asl a
        tax
        lda PLR + PL_POWERS_0 + 1,x
        bmi @done
        lda pk_ptics,x
        sta PLR + PL_POWERS_0,x
        lda pk_ptics+1,x
        sta PLR + PL_POWERS_0 + 1,x
@done:  sec
        rts
; the tics of each power (the release's powerTics)
pk_ptics:
        .word U_POWERTICS_0, U_POWERTICS_1, U_POWERTICS_2, U_POWERTICS_3, U_POWERTICS_4
        .word U_POWERTICS_5
        .assert UC_NUMPOWERS = 6, error, "powerTics' length"
