; game/pickup/cheat.s: part pickup's cheats (milestone 10, docs/GAME.md 2.4,
; 3.7; docs/game-parts/pickup.md). A GPL-2 derivative of upstream's
; m_cheat65.s (Doom8088: Apple IIgs Edition, GPL-2): the cheats' effects.
;
;   C_Responder  A = a cheat by its event number (m_cheat65.s's table:
;                0 idchoppers, 1 iddqd, 2 idkfa, 3 idfa, 4 idspispopd,
;                5-10 idbehold v, s, i, r, a, l, 11 idclev, 12 idend,
;                13 idrocket, 14 idrate; the tic stream's events, GAME.md
;                3.7): its effect, A = 1 (upstream's "true" for a
;                completed cheat); a number past the table: nothing, A = 0.
;                Matching typed keys to the sequences (upstream's CHT_P and
;                the event's key) is milestone 11's input
;   power        A = a power: P_GivePower's (FCALL), the result dropped
;   m_cheat_giveAmmo  the ammo of idfa and idkfa: a backpack (twice the
;                maxima, once), armour, the weapons of the shareware game
;                (not the plasma gun, the BFG or the super shotgun), full
;                ammo but cells
;
; The messages are the player's message (ch_msg: the symbol numbers of
; ggame.inc, SYM_*: request P1). idrate's frame rate flag is no canonical
; state: it is the persistent G_FPSSHOW (request P4; the harnesses write
; the reference's _g_fps_show there at a run's start).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/pickup/pk.inc"

        .export C_Responder, power, m_cheat_giveAmmo
        .import fc_call, fc_unbuilt

; MSG sym: the player's message, then rts
.macro MSG sym
        lda #<(sym)
        ldx #>(sym)
        jmp ch_msg
.endmacro

; ---------------------------------------------------------------------------
; C_Responder: A = the cheat's number
; ---------------------------------------------------------------------------
        ROUTINE C_Responder
        cmp #U_NUMCHEATS
        bcc :+
        lda #0
        rts
:       sta PK_CH
        asl a
        tax
        jsr @go
        lda #1
        rts
@go:    jmp (ch_table,x)

; the cheats' effects, in upstream's table order (m_cheat65.s cheats)
ch_table:
        .addr ch_choppers, ch_god, ch_kfa, ch_fa, ch_noclip, ch_beholdv
        .addr ch_beholds, ch_beholdi, ch_beholdr, ch_beholda, ch_beholdl
        .addr ch_clev, ch_end, ch_rocket, ch_rate
        .assert (* - ch_table) / 2 = U_NUMCHEATS, error, "the cheats' table"

; ch_msg: the player's message the symbol A:X (the bridge's "ref" of a
; symbol: tag 1, the number, offset 0, as P_TouchSpecialThing writes it)
ch_msg: sta PLR + PL_MESSAGE + 1
        stx PLR + PL_MESSAGE + 2
        lda #1
        sta PLR + PL_MESSAGE
        stz PLR + PL_MESSAGE + 3
        stz PLR + PL_MESSAGE + 4
        rts

; idchoppers: the chainsaw, invulnerability
ch_choppers:
        lda #1
        sta PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINSAW
        stz PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_CHAINSAW + 1
        lda #UC_WP_CHAINSAW
        sta PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
        lda #UC_PW_INVULNERABILITY
        FCALL power
        MSG SYM_m_cheat_msgChoppers

; iddqd: god mode on or off (on: full health, the player's only)
ch_god: lda PLR + PL_CHEATS
        eor #UC_CF_GODMODE
        sta PLR + PL_CHEATS
        and #UC_CF_GODMODE
        beq :+
        lda #<U_GOD_HEALTH
        sta PLR + PL_HEALTH
        lda #>U_GOD_HEALTH
        sta PLR + PL_HEALTH + 1
        MSG SYM_m_cheat_msgDqdOn
:       MSG SYM_m_cheat_msgDqdOff

; idkfa: the ammo of idfa, and all the cards
ch_kfa: FCALL m_cheat_giveAmmo
        ldx #2 * UC_NUMCARDS - 2
:       lda #1
        sta PLR + PL_CARDS_0,x
        stz PLR + PL_CARDS_0 + 1,x
        dex
        dex
        bpl :-
        MSG SYM_m_cheat_msgKfa

; idfa
ch_fa:  FCALL m_cheat_giveAmmo
        MSG SYM_m_cheat_msgFa

; idspispopd: no clipping on or off
ch_noclip:
        lda PLR + PL_CHEATS
        eor #UC_CF_NOCLIP
        sta PLR + PL_CHEATS
        and #UC_CF_NOCLIP
        beq :+
        MSG SYM_m_cheat_msgNcOn
:       MSG SYM_m_cheat_msgNcOff

; idbehold v, s, i, r, a, l: the powers (no message)
ch_beholdv:
        lda #UC_PW_INVULNERABILITY
        bra ch_power
ch_beholds:
        lda #UC_PW_STRENGTH
        bra ch_power
ch_beholdi:
        lda #UC_PW_INVISIBILITY
        bra ch_power
ch_beholdr:
        lda #UC_PW_IRONFEET
        bra ch_power
ch_beholda:
        lda #UC_PW_ALLMAP
        bra ch_power
ch_beholdl:
        lda #UC_PW_INFRARED
ch_power:
        FCALL power
        rts

; idclev: the level ends (upstream's simplified idclev: G_ExitLevel)
ch_clev:
        FCALL G_ExitLevel
        rts

; idend: the finale
ch_end: lda #UGA_VICTORY
        sta G_GAMEACTION
        stz G_GAMEACTION + 1
        rts

; idrocket: enemy rockets on (with health and the rocket launcher) or off
ch_rocket:
        lda PLR + PL_CHEATS
        eor #UC_CF_ENEMY_ROCKETS
        sta PLR + PL_CHEATS
        and #UC_CF_ENEMY_ROCKETS
        beq @off
        lda #<U_GOD_HEALTH
        sta PLR + PL_HEALTH
        lda #>U_GOD_HEALTH
        sta PLR + PL_HEALTH + 1
        lda #1
        sta PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_MISSILE
        stz PLR + PL_WEAPONOWNED_0 + 2 * UC_WP_MISSILE + 1
        lda PLR + PL_MAXAMMO_0 + 2 * UC_AM_MISL
        sta PLR + PL_AMMO_0 + 2 * UC_AM_MISL
        lda PLR + PL_MAXAMMO_0 + 2 * UC_AM_MISL + 1
        sta PLR + PL_AMMO_0 + 2 * UC_AM_MISL + 1
        lda #UC_WP_MISSILE
        sta PLR + PL_PENDINGWEAPON
        stz PLR + PL_PENDINGWEAPON + 1
        MSG SYM_m_cheat_msgRocketOn
@off:   MSG SYM_m_cheat_msgRocketOff

; idrate: the frame rate on or off (G_FPSSHOW: request P4)
ch_rate:
        lda G_FPSSHOW
        beq @on
        stz G_FPSSHOW
        MSG SYM_m_cheat_msgFpsOff
@on:    lda #1
        sta G_FPSSHOW
        MSG SYM_m_cheat_msgFpsOn

; ---------------------------------------------------------------------------
; power: P_GivePower(&_g_player, A)
; ---------------------------------------------------------------------------
        ROUTINE power
        FCALL P_GivePower
        rts

; ---------------------------------------------------------------------------
; m_cheat_giveAmmo: idfa's and idkfa's
; ---------------------------------------------------------------------------
        ROUTINE m_cheat_giveAmmo
        lda PLR + PL_BACKPACK   ; no backpack: double maximum
        ora PLR + PL_BACKPACK + 1
        bne @arm
        ldx #2 * UC_NUMAMMO - 2
:       asl PLR + PL_MAXAMMO_0,x
        rol PLR + PL_MAXAMMO_0 + 1,x
        dex
        dex
        bpl :-
        lda #1
        sta PLR + PL_BACKPACK
        stz PLR + PL_BACKPACK + 1
@arm:   lda #<U_IDFA_ARMOR
        sta PLR + PL_ARMORPOINTS
        lda #>U_IDFA_ARMOR
        sta PLR + PL_ARMORPOINTS + 1
        lda #<U_IDFA_ARMOR_CLASS
        sta PLR + PL_ARMORTYPE
        lda #>U_IDFA_ARMOR_CLASS
        sta PLR + PL_ARMORTYPE + 1
        ldx #2 * UC_NUMWEAPONS - 2 ; not plasma, BFG, super shotgun
@w:     cpx #2 * UC_WP_PLASMA
        beq @nw
        cpx #2 * UC_WP_BFG
        beq @nw
        cpx #2 * UC_WP_SUPERSHOTGUN
        beq @nw
        lda #1
        sta PLR + PL_WEAPONOWNED_0,x
        stz PLR + PL_WEAPONOWNED_0 + 1,x
@nw:    dex
        dex
        bpl @w
        ldx #2 * UC_NUMAMMO - 2 ; full ammo, not cells
@a:     cpx #2 * UC_AM_CELL
        beq @na
        lda PLR + PL_MAXAMMO_0,x
        sta PLR + PL_AMMO_0,x
        lda PLR + PL_MAXAMMO_0 + 1,x
        sta PLR + PL_AMMO_0 + 1,x
@na:    dex
        dex
        bpl @a
        rts
