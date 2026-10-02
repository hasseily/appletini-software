; game/damage/dweap.s: part damage's weapon down and the weapon records
; (milestone 10, docs/GAME.md 2.4; docs/game-parts/damage.md). A GPL-2
; derivative of upstream's p_pspr65.s (P_DropWeapon, lowerWeapon, wInfo,
; wInfoOf, weaponinfo).
;
;   P_DropWeapon  the player died: lowerWeapon
;   lowerWeapon   the weapon's psprite to its down state
;                 (setPsprite(ps_weapon, weaponinfo[readyweapon].downstate):
;                 milestone 9's gw_setpsprite, its action through ACTTAB)
;   wInfo         X = A = the offset in weaponinfo of the ready weapon's
;                 record
;   wInfoOf       A = a weapon: X = A = its record's offset, 12 A (the low
;                 byte of math.s's mul8: upstream's IIGS_MulLo16, whose
;                 product is the record's near address less the table's)
;   weaponinfo    upstream's table (weaponinfo_t: ammo, up, down, ready,
;                 attack and flash states, a word each), in the core: a
;                 caller of wInfo in any group reads it (request R2)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/damage/damage.inc"

        .export P_DropWeapon, lowerWeapon, wInfo, wInfoOf, weaponinfo
        .import gw_setpsprite, mul8, fc_call, fc_unbuilt

; ---------------------------------------------------------------------------
; P_DropWeapon
; ---------------------------------------------------------------------------
        ROUTINE P_DropWeapon
        FCALL lowerWeapon
        rts

; ---------------------------------------------------------------------------
; lowerWeapon
; ---------------------------------------------------------------------------
        ROUTINE lowerWeapon
        FCALL wInfo
        lda weaponinfo + WI_DOWN,x
        sta GS_ST
        lda weaponinfo + WI_DOWN + 1,x
        sta GS_ST+1
        stz GS_PSP              ; ps_weapon
        jmp gw_setpsprite

; ---------------------------------------------------------------------------
; wInfo, wInfoOf
; ---------------------------------------------------------------------------
        ROUTINE wInfo
        lda G_PLAYER + PL_READYWEAPON
        FCALL wInfoOf
        rts

        ROUTINE wInfoOf
        ldy #WI_SIZE
        jsr mul8
        lda M_R
        tax
        rts

; ---------------------------------------------------------------------------
; weaponinfo: upstream's (p_pspr65.s), in the core
; ---------------------------------------------------------------------------
        .segment "GCORE"
FC_HERE .set 0
weaponinfo:                     ; the release's table (lgame.inc's U_WI_*:
                                ;   llayout.py reads it; request R2, wave 2
                                ;   as integrated)
.repeat U_NUMWEAPONS, W
        .word .ident(.sprintf("U_WI_AMMO_%d", W))
        .word .ident(.sprintf("U_WI_UP_%d", W))
        .word .ident(.sprintf("U_WI_DOWN_%d", W))
        .word .ident(.sprintf("U_WI_READY_%d", W))
        .word .ident(.sprintf("U_WI_ATK_%d", W))
        .word .ident(.sprintf("U_WI_FLASH_%d", W))
.endrepeat
        .assert * - weaponinfo = WI_SIZE * U_NUMWEAPONS, error, "nine weapons"
        .assert WI_AMMO = UO_WI_AMMO && WI_UP = UO_WI_UPSTATE && WI_DOWN = UO_WI_DOWNSTATE, error, "weaponinfo_t"
        .assert WI_READY = UO_WI_READYSTATE && WI_ATK = UO_WI_ATKSTATE && WI_FLASH = UO_WI_FLASHSTATE, error, "weaponinfo_t"
