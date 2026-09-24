; Doom for the Appletini -- damage, death and pickups, 6502 (docs/DESIGN.md
; section 9).
;
; The assembly twin of p_inter.c (the C is the reference, compiled on the
; host; read it for the why of each step):
;
;   void P_DamageMobj(mobj_t *target, mobj_t *inflictor, mobj_t *source, int16_t damage)
;   void P_KillMobj(mobj_t *source, mobj_t *target)
;   void P_TouchSpecialThing(mobj_t *special, mobj_t *toucher)
;
; P_DamageMobj is reentrant as vanilla's: the target's pain and see states
; run their actions at once (a monster turning on its attacker runs its
; A_Chase, which may move it into a charging lost soul...), and
; P_KillMobj's death state and dropped item likewise. Its four arguments
; are kept in variables that it saves on the 6502 stack on entry and gets
; back on exit, which is what C's locals are.
;
; A pickup is identified by its sprite, as vanilla does: a table gives
; each sprite of episode 1's pickups a kind and its numbers, and the kinds
; are small routines (ammo, weapon, key, power, and the health and armour
; items). For the py65 harness this code may sit in a code-only window
; (MCODE, gmacros.inc): the tables are in RODATA.

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR

.import set_state, mo_sound, mo_info, angle_to, info_ptr, mul8
.import fx_mul, fx_div, fx_sine, fx_cosine, fxa, fxb, fxr
.import w_ldo, w_sto, w_add, ret_w
.import _P_Random, _P_SpawnMobj, _P_RemoveMobj, _P_DropWeapon, _S_StartSound
.import _player, _gameskill, _sec_special, _weaponinfo, _maxammo, _clipammo, _st_sprite
.import pushax, pusheax, popax, incsp2, incsp4

.export _P_DamageMobj, _P_KillMobj, _P_TouchSpecialThing

PL          = _player
BONUSADD    = 6

.segment "BSS"
dm_target:  .res 2                  ; P_DamageMobj's arguments (saved on entry,
dm_inflictor: .res 2                ; restored on exit: reentrant)
dm_source:  .res 2
dm_damage:  .res 2
DM_SIZE     = 8
dm_saved:   .res 2                  ; the armour saved
dm_ang:     .res 2
km_item:    .res 1
tp_sound:   .res 1                  ; P_TouchSpecialThing
tp_special: .res 2
tp_dropped: .res 1
tp_msg:     .res 1                  ; the kinds' message
tp_i:       .res 1                  ; the pickup's index; the backpack's ammo type
tp_old:     .res 2                  ; P_GiveAmmo: the old ammo
ga_type:    .res 1                  ; P_GiveAmmo
ga_n:       .res 2

.segment "RODATA"
; the pickups by sprite: a kind (the routine, KIND_*) and two arguments
.define PICKUP_SPRITES SPR_ARM1, SPR_ARM2, SPR_BON1, SPR_BON2, SPR_SOUL, SPR_BKEY, SPR_YKEY, SPR_RKEY, SPR_BSKU, SPR_YSKU, SPR_RSKU, SPR_STIM, SPR_MEDI, SPR_PINV, SPR_PSTR, SPR_PINS, SPR_SUIT, SPR_PMAP, SPR_PVIS, SPR_CLIP, SPR_AMMO, SPR_ROCK, SPR_BROK, SPR_CELL, SPR_CELP, SPR_SHEL, SPR_SBOX, SPR_BPAK, SPR_MGUN, SPR_CSAW, SPR_LAUN, SPR_PLAS, SPR_SHOT
pk_sprite:  .byte PICKUP_SPRITES
NPICKUPS    = * - pk_sprite
KIND_ARMOR  = 0                     ; arg1 armour class, arg2 message
KIND_BON1   = 2
KIND_BON2   = 4
KIND_SOUL   = 6
KIND_KEY    = 8                     ; arg1 card, arg2 message
KIND_BODY   = 10                    ; arg1 amount (stimpack), arg2 message; 25: the medikit
KIND_POWER  = 12                    ; arg1 power, arg2 message
KIND_AMMO   = 14                    ; arg1 ammo | $80 if dropped halves, arg2 clips; message kept
KIND_BPAK   = 16
KIND_WEAPON = 18                    ; arg1 weapon | $80 if its drop counts, arg2 message
pk_kind:    .byte KIND_ARMOR, KIND_ARMOR, KIND_BON1, KIND_BON2, KIND_SOUL
            .byte KIND_KEY, KIND_KEY, KIND_KEY, KIND_KEY, KIND_KEY, KIND_KEY
            .byte KIND_BODY, KIND_BODY
            .byte KIND_POWER, KIND_POWER, KIND_POWER, KIND_POWER, KIND_POWER, KIND_POWER
            .byte KIND_AMMO, KIND_AMMO, KIND_AMMO, KIND_AMMO, KIND_AMMO, KIND_AMMO
            .byte KIND_AMMO, KIND_AMMO, KIND_BPAK
            .byte KIND_WEAPON, KIND_WEAPON, KIND_WEAPON, KIND_WEAPON, KIND_WEAPON
pk_arg1:    .byte 1, 2, 0, 0, 0
            .byte it_bluecard, it_yellowcard, it_redcard, it_blueskull, it_yellowskull, it_redskull
            .byte 10, 25
            .byte pw_invulnerability, pw_strength, pw_invisibility, pw_ironfeet, pw_allmap, pw_infrared
            .byte am_clip | $80, am_clip, am_misl, am_misl, am_cell, am_cell
            .byte am_shell, am_shell, 0
            .byte wp_chaingun | $80, wp_chainsaw, wp_missile, wp_plasma, wp_shotgun | $80
pk_arg2:    .byte MSG_GOTARMOR, MSG_GOTMEGA, MSG_GOTHTHBONUS, MSG_GOTARMBONUS, MSG_GOTSUPER
            .byte MSG_GOTBLUECARD, MSG_GOTYELWCARD, MSG_GOTREDCARD, MSG_GOTBLUESKUL
            .byte MSG_GOTYELWSKUL, MSG_GOTREDSKULL
            .byte MSG_GOTSTIM, MSG_GOTMEDIKIT
            .byte MSG_GOTINVUL, MSG_GOTBERSERK, MSG_GOTINVIS, MSG_GOTSUIT, MSG_GOTMAP, MSG_GOTVISOR
            .byte 1, 5, 1, 5, 1, 5
            .byte 1, 5, 0
            .byte MSG_GOTCHAINGUN, MSG_GOTCHAINSAW, MSG_GOTLAUNCHER, MSG_GOTPLASMA, MSG_GOTSHOTGUN
PK_FIRSTAMMO = 19                   ; the index of SPR_CLIP in pk_sprite
pk_ammomsg: .byte MSG_GOTCLIP, MSG_GOTCLIPBOX, MSG_GOTROCKET, MSG_GOTROCKBOX, MSG_GOTCELL
            .byte MSG_GOTCELLBOX, MSG_GOTSHELLS, MSG_GOTSHELLBOX
.assert * - pk_arg2 - 8 = NPICKUPS, error, "pickup tables"
pk_routine: .word pk_armor, pk_bon1, pk_bon2, pk_soul, pk_key, pk_body, pk_power, pk_ammo
            .word pk_bpak, pk_weapon
; the power-up durations (0: just 1, as vanilla's P_GivePower)
pw_tics:    .word INVULNTICS, 0, INVISTICS, IRONTICS, 0, INFRATICS

MONCODE

; ---- P_DamageMobj ---------------------------------------------------------------------------
; C stack: +0 source, +2 inflictor, +4 target; A/X damage
_P_DamageMobj:
        ; the caller's (an outer P_DamageMobj's) variables on the 6502 stack
        pha
        phx
        ldx     #DM_SIZE - 1
:       lda     dm_target,x
        pha
        dex
        bpl     :-
        tsx
        lda     $0100 + DM_SIZE + 1,x   ; the damage (pushed before them)
        sta     dm_damage+1
        lda     $0100 + DM_SIZE + 2,x
        sta     dm_damage
        ldy     #5                      ; the C stack: +4 target, +2 inflictor, +0 source
        lda     (sp),y
        sta     dm_target+1
        dey
        lda     (sp),y
        sta     dm_target
        dey
        lda     (sp),y
        sta     dm_inflictor+1
        dey
        lda     (sp),y
        sta     dm_inflictor
        dey
        lda     (sp),y
        sta     dm_source+1
        lda     (sp)
        sta     dm_source
        jsr     damage
        ; back: the caller's variables, then the damage's two bytes
        ldx     #0
:       pla
        sta     dm_target,x
        inx
        cpx     #DM_SIZE
        bne     :-
        pla
        pla
        clc                             ; pop the three pointers
        lda     sp
        adc     #6
        sta     sp
        bcc     :+
        inc     sp+1
:       rts
.assert dm_inflictor = dm_target + 2 && dm_source = dm_target + 4, error, "dm_ order"

; the damage itself, dm_* set
damage:
        jsr     gmo_target
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_SHOOTABLE
        bne     :+
        rts                             ; shouldn't happen...
:       ldy     #MO_HEALTH+1
        lda     (gmo),y
        bmi     @rts0
        dey
        ora     (gmo),y
        bne     :+
@rts0:  rts
:       ; a charging lost soul stops
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        beq     @noskull
        ldy     #MO_MOMX
        lda     #0
        ldx     #12
@zero:  sta     (gmo),y
        iny
        dex
        bne     @zero
.assert MO_MOMY = MO_MOMX + 4 && MO_MOMZ = MO_MOMX + 8, error, "momx, momy, momz"
@noskull:
        ; take half damage in trainer mode
        jsr     is_player
        bne     :+
        lda     _gameskill
        bne     :+
        lda     dm_damage+1
        cmp     #$80
        ror     dm_damage+1
        ror     dm_damage
:       ; the thrust (unless there is no inflictor, the target does not
        ; clip, or the player's chainsaw is the source)
        lda     dm_inflictor
        ora     dm_inflictor+1
        jeq     @player
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_NOCLIP
        jne     @player
        lda     dm_source
        ora     dm_source+1
        beq     @kick
        lda     dm_source
        cmp     PL+PL_MO
        bne     @kick
        lda     dm_source+1
        cmp     PL+PL_MO+1
        bne     @kick
        lda     PL+PL_READYWEAPON
        cmp     #wp_chainsaw
        jeq     @player
@kick:  jsr     thrust
@player:
        ; the player: the E1M8 floor, god mode, armour, health, the flash
        jsr     gmo_target
        jsr     is_player
        jne     @hurt
        ; end of game hell hack: sector special 11 never kills
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
        cmp     #11
        bne     :+
        ldy     #MO_HEALTH
        lda     dm_damage               ; damage >= health: health - 1
        cmp     (gmo),y
        iny
        lda     dm_damage+1
        sbc     (gmo),y
        bvc     @v1
        eor     #$80
@v1:    bmi     :+
        ldy     #MO_HEALTH
        sec
        lda     (gmo),y
        sbc     #1
        sta     dm_damage
        iny
        lda     (gmo),y
        sbc     #0
        sta     dm_damage+1
:       ; below 1000, ignore damage in god mode or invulnerable
        lda     dm_damage+1
        bmi     :+
        lda     dm_damage
        cmp     #<1000
        lda     dm_damage+1
        sbc     #>1000
        bcs     @armour
:       lda     PL+PL_CHEATS
        and     #CF_GODMODE
        bne     @none
        lda     PL+PL_POWERS+2*pw_invulnerability
        ora     PL+PL_POWERS+2*pw_invulnerability+1
        beq     @armour
@none:  rts
@armour:
        lda     PL+PL_ARMORTYPE
        beq     @health
        ; saved = damage / 3 (class 1) or / 2
        cmp     #1
        bne     @half
        lda     dm_damage
        ldx     dm_damage+1
        jsr     div3
        bra     @saved
@half:  lda     dm_damage+1
        cmp     #$80
        ror     a
        tax
        lda     dm_damage
        ror     a
@saved: sta     dm_saved
        stx     dm_saved+1
        ; the armour used up (armorpoints <= saved): all it has
        sec
        lda     PL+PL_ARMORPOINTS
        sbc     dm_saved
        sta     tmp1
        lda     PL+PL_ARMORPOINTS+1
        sbc     dm_saved+1
        tay
        bvc     :+
        eor     #$80
:       bmi     @usedup
        tya
        ora     tmp1
        bne     @take
@usedup:
        lda     PL+PL_ARMORPOINTS
        sta     dm_saved
        lda     PL+PL_ARMORPOINTS+1
        sta     dm_saved+1
        stz     PL+PL_ARMORTYPE
@take:  sec
        lda     PL+PL_ARMORPOINTS
        sbc     dm_saved
        sta     PL+PL_ARMORPOINTS
        lda     PL+PL_ARMORPOINTS+1
        sbc     dm_saved+1
        sta     PL+PL_ARMORPOINTS+1
        sec
        lda     dm_damage
        sbc     dm_saved
        sta     dm_damage
        lda     dm_damage+1
        sbc     dm_saved+1
        sta     dm_damage+1
@health:
        sec
        lda     PL+PL_HEALTH
        sbc     dm_damage
        sta     PL+PL_HEALTH
        lda     PL+PL_HEALTH+1
        sbc     dm_damage+1
        sta     PL+PL_HEALTH+1
        bpl     :+
        stz     PL+PL_HEALTH
        stz     PL+PL_HEALTH+1
:       lda     dm_source
        sta     PL+PL_ATTACKER
        lda     dm_source+1
        sta     PL+PL_ATTACKER+1
        ; damagecount += damage, at most 100
        clc
        lda     PL+PL_DAMAGECOUNT
        adc     dm_damage
        tax
        lda     #0
        adc     dm_damage+1
        bne     @hundred
        cpx     #101
        bcc     :+
@hundred:
        ldx     #100
:       stx     PL+PL_DAMAGECOUNT
@hurt:  ; do the damage
        jsr     gmo_target
        ldy     #MO_HEALTH
        sec
        lda     (gmo),y
        sbc     dm_damage
        sta     (gmo),y
        iny
        lda     (gmo),y
        sbc     dm_damage+1
        sta     (gmo),y
        bmi     @dies
        dey
        ora     (gmo),y
        bne     @alive
@dies:  lda     dm_source
        ldx     dm_source+1
        jsr     pushax
        lda     dm_target
        ldx     dm_target+1
        jmp     _P_KillMobj
@alive: ; the pain chance (a lost soul's is 256: always)
        jsr     _P_Random
        sta     dm_saved                ; (free by now)
        jsr     gmo_target
        jsr     mo_info
        ldy     #MI_PAINCHANCE+1
        lda     (ptr1),y
        bne     @pain                   ; 256 or more
        dey
        lda     dm_saved
        cmp     (ptr1),y
        bcs     @awake
@pain:  ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        bne     @awake
        ldy     #MO_FLAGS
        lda     (gmo),y
        ora     #MF0_JUSTHIT            ; fight back!
        sta     (gmo),y
        ldy     #MI_PAINSTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     set_state
@awake: jsr     gmo_target
        ldy     #MO_REACTIONTIME
        lda     #0
        sta     (gmo),y                 ; we're awake now...
        ; if not intent on another thing, chase after this one
        ldy     #MO_THRESHOLD
        lda     (gmo),y
        bne     @rts
        lda     dm_source
        ora     dm_source+1
        beq     @rts
        lda     dm_source
        cmp     dm_target
        bne     :+
        lda     dm_source+1
        cmp     dm_target+1
        beq     @rts
:       ldy     #MO_TARGET
        lda     dm_source
        sta     (gmo),y
        iny
        lda     dm_source+1
        sta     (gmo),y
        ldy     #MO_THRESHOLD
        lda     #BASETHRESHOLD
        sta     (gmo),y
        jsr     mo_info
        ldy     #MO_STATE
        lda     (gmo),y
        ldy     #MI_SPAWNSTATE
        cmp     (ptr1),y
        bne     @rts
        ldy     #MO_STATE+1
        lda     (gmo),y
        ldy     #MI_SPAWNSTATE+1
        cmp     (ptr1),y
        bne     @rts
        ldy     #MI_SEESTATE
        lda     (ptr1),y
        iny
        ora     (ptr1),y
        beq     @rts
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jmp     set_state
@rts:   rts

; gmo = dm_target
gmo_target:
        lda     dm_target
        sta     gmo
        lda     dm_target+1
        sta     gmo+1
        rts

; Z set iff gmo is the player's mobj
is_player:
        lda     gmo
        cmp     PL+PL_MO
        bne     :+
        lda     gmo+1
        cmp     PL+PL_MO+1
:       rts

; A/X = A/X / 3 (unsigned 16-bit)
div3:   sta     tmp1
        stx     tmp2
        lda     #0
        ldx     #16
:       asl     tmp1
        rol     tmp2
        rol     a
        cmp     #3
        bcc     :+
        sbc     #3
        inc     tmp1
:       dex
        bne     :--
        lda     tmp1
        ldx     tmp2
        rts

; the target pushed away from the inflictor:
; thrust = damage * (FRACUNIT >> 3) * 100 / mass (vanilla's int: it wraps)
thrust: lda     dm_inflictor
        sta     gmo
        lda     dm_inflictor+1
        sta     gmo+1
        lda     dm_target
        sta     gpt
        lda     dm_target+1
        sta     gpt+1
        jsr     angle_to                ; the angle from the inflictor to the target
        sta     dm_ang
        stx     dm_ang+1
        ; damage * 200 << 12 (= * 819200) mod 2^32
        lda     dm_damage
        ldx     #200
        jsr     mul8
        sta     fxa
        stx     fxa+1
        lda     dm_damage+1
        ldx     #200
        jsr     mul8
        clc
        adc     fxa+1
        sta     fxa+1
        txa
        adc     #0
        sta     fxa+2
        stz     fxa+3                   ; damage * 200 (damage >= 0)
        ldx     #12
:       asl     fxa
        rol     fxa+1
        rol     fxa+2
        rol     fxa+3
        dex
        bne     :-
        ; / mass: FixedDiv(t, mass << 16) is the truncated int division
        jsr     gmo_target
        jsr     mo_info
        stz     fxb
        stz     fxb+1
        ldy     #MI_MASS
        lda     (ptr1),y
        sta     fxb+2
        iny
        lda     (ptr1),y
        sta     fxb+3
        jsr     fx_div                  ; fxr = thrust
        ; make it fall forwards sometimes: damage < 40, damage > health,
        ; target->z - inflictor->z > 64 units, and P_Random() & 1
        lda     dm_damage+1
        jne     @push
        lda     dm_damage
        cmp     #40
        jcs     @push
        ldy     #MO_HEALTH
        lda     (gmo),y
        cmp     dm_damage
        iny
        lda     (gmo),y
        sbc     #0
        bvc     :+
        eor     #$80
:       jpl     @push                   ; health >= damage
        ; target->z - inflictor->z > 64 << 16
        ldy     #MO_Z
        ldx     #W_T0
        jsr     w_ldo
        lda     dm_inflictor
        sta     gpt
        lda     dm_inflictor+1
        sta     gpt+1
        ldy     #MO_Z
        sec
        ldx     #0
:       lda     W+W_T0,x
        sbc     (gpt),y
        sta     W+W_T0,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        lda     W+W_T0+3
        bmi     @push
        bne     @far
        lda     W+W_T0+2
        cmp     #64
        bcc     @push
        bne     @far
        lda     W+W_T0+1
        ora     W+W_T0
        beq     @push                   ; exactly 64 units
@far:   mov32   W+W_T1, fxr             ; (P_Random keeps W)
        jsr     _P_Random
        lsr     a
        bcc     @keep
        clc
        lda     dm_ang+1
        adc     #>ANG180
        sta     dm_ang+1
        ldx     #2
:       asl     W+W_T1                  ; thrust *= 4
        rol     W+W_T1+1
        rol     W+W_T1+2
        rol     W+W_T1+3
        dex
        bne     :-
@keep:  mov32   fxr, W+W_T1
@push:  ; momx += FixedMul(thrust, cosine), momy += FixedMul(thrust, sine)
        mov32   W+W_T1, fxr
        lda     dm_ang
        sta     tmp1
        lda     dm_ang+1
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        sta     tmp2
        pha
        lda     tmp1
        pha
        ldx     tmp2
        jsr     fx_cosine
        mov32   fxa, W+W_T1
        mov32   fxb, fxr
        jsr     fx_mul
        jsr     gmo_target
        ldy     #MO_MOMX
        jsr     add_fr
        pla
        plx
        jsr     fx_sine
        mov32   fxa, W+W_T1
        mov32   fxb, fxr
        jsr     fx_mul
        ldy     #MO_MOMY
; the fixed at (gmo)+Y += fxr
add_fr: clc
        ldx     #0
:       lda     (gmo),y
        adc     fxr,x
        sta     (gmo),y
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        rts

; ---- P_KillMobj ---------------------------------------------------------------------------------
; void P_KillMobj(mobj_t *source, mobj_t *target): C stack source; A/X target
_P_KillMobj:
        sta     gmo
        stx     gmo+1
        jsr     incsp2                  ; (the source is not needed: one player)
        ; not shootable, floating or charging; falls (but a lost soul); a corpse
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #<~MF0_SHOOTABLE
        sta     (gmo),y
        iny
        lda     (gmo),y
        and     #<~MF1_FLOAT
        sta     (gmo),y
        ldy     #MO_TYPE
        lda     (gmo),y
        cmp     #MT_SKULL
        beq     :+
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #<~MF1_NOGRAVITY
        sta     (gmo),y
:       ldy     #MO_FLAGS+1
        lda     (gmo),y
        ora     #MF1_DROPOFF
        sta     (gmo),y
        iny
        lda     (gmo),y
        ora     #MF2_CORPSE
        sta     (gmo),y
        iny
        lda     (gmo),y
        and     #<~MF3_SKULLFLY
        sta     (gmo),y
        ; height >>= 2
        ldx     #2
:       ldy     #MO_HEIGHT+3
        lda     (gmo),y
        cmp     #$80
        ror     a
        sta     (gmo),y
        dey
        lda     (gmo),y
        ror     a
        sta     (gmo),y
        dey
        lda     (gmo),y
        ror     a
        sta     (gmo),y
        dey
        lda     (gmo),y
        ror     a
        sta     (gmo),y
        dex
        bne     :-
        ; count all monster deaths, even those caused by other monsters
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_COUNTKILL
        beq     :+
        inc     PL+PL_KILLCOUNT
        bne     :+
        inc     PL+PL_KILLCOUNT+1
:       ; the player: not solid, dead, the weapon down
        jsr     is_player
        bne     @state
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #<~MF0_SOLID
        sta     (gmo),y
        lda     #PST_DEAD
        sta     PL+PL_PLAYERSTATE
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     #<_player
        ldx     #>_player
        jsr     _P_DropWeapon
        pla
        sta     gmo+1
        pla
        sta     gmo
@state: ; the death state: gibbed below -spawnhealth if it has one
        jsr     mo_info
        ldy     #MI_XDEATHSTATE
        lda     (ptr1),y
        iny
        ora     (ptr1),y
        beq     @death
        ; health < -spawnhealth: health + spawnhealth < 0
        clc
        ldy     #MO_HEALTH
        lda     (gmo),y
        ldy     #MI_SPAWNHEALTH
        adc     (ptr1),y
        ldy     #MO_HEALTH+1
        lda     (gmo),y
        ldy     #MI_SPAWNHEALTH+1
        adc     (ptr1),y
        bvc     :+
        eor     #$80
:       bpl     @death
        ldy     #MI_XDEATHSTATE
        bra     @set
@death: ldy     #MI_DEATHSTATE
@set:   lda     (ptr1),y
        pha
        iny
        lda     (ptr1),y
        tax
        pla
        ldy     gmo                     ; (the target across set_state)
        phy
        ldy     gmo+1
        phy
        jsr     set_state
        ply
        sty     gmo+1
        ply
        sty     gmo
        ; tics -= P_Random() & 3, at least 1 (a signed byte)
        jsr     _P_Random
        and     #3
        sta     tmp1
        ldy     #MO_TICS
        lda     (gmo),y
        sec
        sbc     tmp1
        beq     :+
        bpl     :++
:       lda     #1
:       sta     (gmo),y
        ; drop stuff: the zombieman's clip, the shotgun guy's shotgun
        ldy     #MO_TYPE
        lda     (gmo),y
        ldx     #MT_CLIP
        cmp     #MT_POSSESSED
        beq     @drop
        ldx     #MT_SHOTGUN
        cmp     #MT_SHOTGUY
        beq     @drop
        rts
@drop:  stx     km_item
        ldy     #MO_X
        jsr     push_fixed
        ldy     #MO_Y
        jsr     push_fixed
        lda     #0                      ; ONFLOORZ
        sta     sreg
        lda     #$80
        sta     sreg+1
        lda     #0
        tax
        jsr     pusheax
        lda     km_item
        jsr     _P_SpawnMobj
        sta     gmo
        stx     gmo+1
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        ora     #MF2_DROPPED            ; the special versions of items
        sta     (gmo),y
        rts

; the fixed_t at (gmo)+Y onto the C stack
push_fixed:
        ldx     #W_T0
        jsr     w_ldo
        ldx     #W_T0
        jsr     ret_w
        jmp     pusheax

; ---- P_TouchSpecialThing ---------------------------------------------------------------------------
; C stack: special; A/X toucher
_P_TouchSpecialThing:
        sta     gpt                     ; the toucher
        stx     gpt+1
        jsr     popax
        sta     gmo                     ; the special (maybe the static view)
        stx     gmo+1
        sta     tp_special
        stx     tp_special+1
        ; out of reach: special->z - toucher->z > toucher->height or < -8 units
        ldy     #MO_Z
        ldx     #0
        sec
:       lda     (gmo),y
        sbc     (gpt),y
        sta     W+W_T0,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        ldy     #MO_HEIGHT              ; height - delta < 0: too high
        ldx     #0
        sec
:       lda     (gpt),y
        sbc     W+W_T0,x
        sta     W+W_T1,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        lda     W+W_T1+3
        bpl     :+
        rts
:       ; delta < -8 << 16 ($FFF80000)
        lda     W+W_T0+3
        bpl     :+
        cmp     #$FF
        bne     @rts
        lda     W+W_T0+2
        cmp     #$F8
        bcc     @rts
:       ; a dead thing touching (a sliding player corpse)
        ldy     #MO_HEALTH+1
        lda     (gpt),y
        bmi     @rts
        dey
        ora     (gpt),y
        beq     @rts
        lda     #sfx_itemup
        sta     tp_sound
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_DROPPED
        sta     tp_dropped
        ; identify by sprite
        ldy     #MO_STATE
        lda     (gmo),y
        clc
        adc     #<_st_sprite
        sta     ptr1
        iny
        lda     (gmo),y
        adc     #>_st_sprite
        sta     ptr1+1
        lda     (ptr1)
        ldx     #NPICKUPS - 1
:       cmp     pk_sprite,x
        beq     @found
        dex
        bpl     :-
@rts:   rts                             ; (vanilla: I_Error; nothing else is gettable)
@found: lda     pk_kind,x
        tay
        lda     pk_routine,y
        sta     ptr2
        lda     pk_routine+1,y
        sta     ptr2+1
        lda     pk_arg1,x
        ldy     pk_arg2,x
        jsr     @call                   ; C clear: not picked up
        bcc     @rts
        ; picked up: counted, removed, the bonus flash and the sound
        lda     tp_special
        sta     gmo
        lda     tp_special+1
        sta     gmo+1
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_COUNTITEM
        beq     :+
        inc     PL+PL_ITEMCOUNT
        bne     :+
        inc     PL+PL_ITEMCOUNT+1
:       lda     tp_special
        ldx     tp_special+1
        jsr     _P_RemoveMobj
        clc
        lda     PL+PL_BONUSCOUNT
        adc     #BONUSADD
        sta     PL+PL_BONUSCOUNT
        lda     #0
        tax
        jsr     pushax
        lda     tp_sound
        jmp     _S_StartSound
@call:  jmp     (ptr2)

; the kinds: A = arg1, Y = arg2, X = the pickup's index -> C set if taken
pk_armor:
        sty     tp_msg
        jsr     give_armor
        bcc     :+
        lda     tp_msg
        sta     PL+PL_MESSAGE
:       rts

pk_bon1:                                ; health + 1, up to 200 (over 100%)
        sty     PL+PL_MESSAGE
        inc     PL+PL_HEALTH
        bne     :+
        inc     PL+PL_HEALTH+1
:       ldx     #200
        jsr     health_cap
        sec
        rts

pk_bon2:                                ; armour + 1, up to 200; class 1 if none
        sty     PL+PL_MESSAGE
        inc     PL+PL_ARMORPOINTS
        bne     :+
        inc     PL+PL_ARMORPOINTS+1
:       lda     PL+PL_ARMORPOINTS+1
        bne     :+
        lda     PL+PL_ARMORPOINTS
        cmp     #201
        bcc     :++
:       lda     #200
        sta     PL+PL_ARMORPOINTS
        stz     PL+PL_ARMORPOINTS+1
:       lda     PL+PL_ARMORTYPE
        bne     :+
        inc     PL+PL_ARMORTYPE
:       sec
        rts

pk_soul:                                ; health + 100, up to 200
        sty     PL+PL_MESSAGE
        clc
        lda     PL+PL_HEALTH
        adc     #100
        sta     PL+PL_HEALTH
        bcc     :+
        inc     PL+PL_HEALTH+1
:       ldx     #200
        jsr     health_cap
        lda     #sfx_getpow
        sta     tp_sound
        sec
        rts

pk_key: ; always taken (not a net game); the message only if new
        tax
        lda     PL+PL_CARDS,x
        bne     :+
        sty     PL+PL_MESSAGE
        lda     #BONUSADD
        sta     PL+PL_BONUSCOUNT
        lda     #1
        sta     PL+PL_CARDS,x
:       sec
        rts

pk_body:
        sty     tp_msg
        jsr     give_body
        bcc     @rts
        lda     tp_msg
        cmp     #MSG_GOTMEDIKIT
        bne     @msg
        ; (vanilla tests the health after the heal: "needed" never shows)
        lda     PL+PL_HEALTH+1
        bne     @msg
        lda     PL+PL_HEALTH
        cmp     #25
        bcs     @msg
        lda     #MSG_GOTMEDINEED
        sta     tp_msg
@msg:   lda     tp_msg
        sta     PL+PL_MESSAGE
        sec
@rts:   rts

pk_power:
        sty     tp_msg
        pha
        jsr     give_power
        pla
        bcc     @rts
        cmp     #pw_strength            ; berserk: the fist comes up
        bne     :+
        ldx     PL+PL_READYWEAPON
        beq     :+
        stz     PL+PL_PENDINGWEAPON     ; (wp_fist = 0)
:       lda     tp_msg
        sta     PL+PL_MESSAGE
        lda     #sfx_getpow
        sta     tp_sound
        sec
@rts:   rts
.assert wp_fist = 0, error, "wp_fist"

pk_ammo:
        stx     tp_i                    ; (the index, for the message)
        pha
        and     #$7F
        sta     ga_type
        pla
        bpl     @n
        ldx     tp_dropped              ; a dropped clip: half a clip
        beq     @n
        ldy     #0
@n:     tya
        jsr     give_ammo
        bcc     @rts
        lda     tp_i
        sec
        sbc     #PK_FIRSTAMMO
        tax
        lda     pk_ammomsg,x
        sta     PL+PL_MESSAGE
        sec
@rts:   rts

pk_bpak:
        lda     PL+PL_BACKPACK
        bne     @give
        ldx     #2 * NUMAMMO - 2
:       asl     PL+PL_MAXAMMO,x
        rol     PL+PL_MAXAMMO+1,x
        dex
        dex
        bpl     :-
        lda     #1
        sta     PL+PL_BACKPACK
@give:  stz     tp_i
@each:  lda     tp_i
        sta     ga_type
        lda     #1
        jsr     give_ammo
        inc     tp_i
        lda     tp_i
        cmp     #NUMAMMO
        bne     @each
        lda     #MSG_GOTBACKPACK
        sta     PL+PL_MESSAGE
        sec
        rts

pk_weapon:
        sty     tp_msg
        pha
        and     #$7F
        tax
        pla
        and     #$80                    ; its drop counts and it was dropped: one clip
        beq     :+
        lda     tp_dropped
        beq     :+
        lda     #1
:       jsr     give_weapon             ; X = weapon, A = dropped
        bcc     @rts
        lda     tp_msg
        sta     PL+PL_MESSAGE
        lda     #sfx_wpnup
        sta     tp_sound
        sec
@rts:   rts
.assert MF2_DROPPED <> 0, error, "tp_dropped"

; health = min(health, X) (and the mobj's)
health_cap:
        lda     PL+PL_HEALTH+1
        bne     :+
        cpx     PL+PL_HEALTH
        bcs     :++
:       stx     PL+PL_HEALTH
        stz     PL+PL_HEALTH+1
:       ldy     #MO_HEALTH
        lda     PL+PL_MO
        sta     gpt
        lda     PL+PL_MO+1
        sta     gpt+1
        lda     PL+PL_HEALTH
        sta     (gpt),y
        iny
        lda     PL+PL_HEALTH+1
        sta     (gpt),y
        rts

; ---- getting stuff --------------------------------------------------------------------------------
; P_GiveBody(A): C set if taken (health below 100)
give_body:
        tax
        lda     PL+PL_HEALTH+1
        bmi     :+
        bne     @no
        lda     PL+PL_HEALTH
        cmp     #MAXHEALTH
        bcs     @no
:       txa
        clc
        adc     PL+PL_HEALTH
        sta     PL+PL_HEALTH
        bcc     :+
        inc     PL+PL_HEALTH+1
:       ldx     #MAXHEALTH
        jsr     health_cap
        sec
        rts
@no:    clc
        rts

; P_GiveArmor(A = class): C set if taken (the current armour is worse)
give_armor:
        pha
        ldx     #100
        jsr     mul8                    ; hits = class * 100
        sta     tmp1
        stx     tmp2
        lda     PL+PL_ARMORPOINTS
        cmp     tmp1
        lda     PL+PL_ARMORPOINTS+1
        sbc     tmp2
        bvc     :+
        eor     #$80
:       bpl     @no                     ; armorpoints >= hits: don't pick up
        pla
        sta     PL+PL_ARMORTYPE
        lda     tmp1
        sta     PL+PL_ARMORPOINTS
        lda     tmp2
        sta     PL+PL_ARMORPOINTS+1
        sec
        rts
@no:    pla
        clc
        rts

; P_GivePower(A): C set if taken
give_power:
        asl     a
        tax
        cmp     #2 * pw_strength
        bne     :+
        lda     #100
        jsr     give_body
        lda     #1
        sta     PL+PL_POWERS+2*pw_strength
        stz     PL+PL_POWERS+2*pw_strength+1
        sec
        rts
:       lda     pw_tics,x
        ora     pw_tics+1,x
        beq     @once
        lda     pw_tics,x
        sta     PL+PL_POWERS,x
        lda     pw_tics+1,x
        sta     PL+PL_POWERS+1,x
        cpx     #2 * pw_invisibility
        bne     :+
        lda     PL+PL_MO                ; invisible: a shadow
        sta     gpt
        lda     PL+PL_MO+1
        sta     gpt+1
        ldy     #MO_FLAGS+2
        lda     (gpt),y
        ora     #MF2_SHADOW
        sta     (gpt),y
:       sec
        rts
@once:  lda     PL+PL_POWERS,x          ; the computer map: once
        ora     PL+PL_POWERS+1,x
        bne     @no
        lda     #1
        sta     PL+PL_POWERS,x
        stz     PL+PL_POWERS+1,x
        sec
        rts
@no:    clc
        rts

; P_GiveAmmo(ga_type, A = clip loads, 0 = half a clip): C set if taken
give_ammo:
        sta     tmp3
        lda     ga_type
        asl     a
        tax
        ; full: not taken
        lda     PL+PL_AMMO,x
        cmp     PL+PL_MAXAMMO,x
        bne     :+
        lda     PL+PL_AMMO+1,x
        cmp     PL+PL_MAXAMMO+1,x
        bne     :+
        clc
        rts
:       ; n = loads * clipammo, or clipammo / 2
        lda     _clipammo,x
        ldy     tmp3
        bne     :+
        lsr     a
        sta     ga_n
        stz     ga_n+1
        bra     @dbl
:       phx
        ldx     tmp3
        jsr     mul8
        sta     ga_n
        stx     ga_n+1
        plx
@dbl:   ; double ammo in trainer mode and nightmare
        lda     _gameskill
        beq     :+
        cmp     #sk_nightmare
        bne     :++
:       asl     ga_n
        rol     ga_n+1
:       ; the old ammo decides the weapon change below
        lda     PL+PL_AMMO,x
        sta     tp_old
        lda     PL+PL_AMMO+1,x
        sta     tp_old+1
        clc
        lda     PL+PL_AMMO,x
        adc     ga_n
        sta     PL+PL_AMMO,x
        lda     PL+PL_AMMO+1,x
        adc     ga_n+1
        sta     PL+PL_AMMO+1,x
        ; at most the maximum
        lda     PL+PL_MAXAMMO,x
        cmp     PL+PL_AMMO,x
        lda     PL+PL_MAXAMMO+1,x
        sbc     PL+PL_AMMO+1,x
        bvc     :+
        eor     #$80
:       bpl     :+
        lda     PL+PL_MAXAMMO,x
        sta     PL+PL_AMMO,x
        lda     PL+PL_MAXAMMO+1,x
        sta     PL+PL_AMMO+1,x
:       ; had some: the player was low on purpose, no change
        lda     tp_old
        ora     tp_old+1
        bne     @taken
        ; down to zero: select a new weapon (vanilla's preferences)
        lda     ga_type
        ldx     PL+PL_READYWEAPON
        cmp     #am_clip
        bne     @shell
        cpx     #wp_fist
        bne     @taken
        ldy     #wp_pistol
        lda     PL+PL_WEAPONOWNED+wp_chaingun
        beq     @pend
        ldy     #wp_chaingun
        bra     @pend
@shell: cmp     #am_shell
        bne     @cell
        ldy     #wp_shotgun
        bra     @fistpistol
@cell:  cmp     #am_cell
        bne     @misl
        ldy     #wp_plasma
@fistpistol:
        cpx     #wp_fist
        beq     :+
        cpx     #wp_pistol
        bne     @taken
:       lda     PL+PL_WEAPONOWNED,y
        beq     @taken
        bra     @pend
@misl:  cpx     #wp_fist                ; (am_misl)
        bne     @taken
        ldy     #wp_missile
        lda     PL+PL_WEAPONOWNED+wp_missile
        beq     @taken
@pend:  sty     PL+PL_PENDINGWEAPON
@taken: sec
        rts

; P_GiveWeapon(X = weapon, A = dropped): C set if taken (the weapon is
; new, or its ammo was)
give_weapon:
        sta     tmp4
        phx
        txa
        jsr     wi_ammo                 ; A = its ammo type
        cmp     #am_noammo
        beq     @noammo
        sta     ga_type
        lda     tmp4                    ; a dropped one gives one clip, a placed one two
        eor     #1
        inc     a
        jsr     give_ammo
        lda     #0
        rol     a
        bra     :+
@noammo:
        lda     #0
:       sta     tmp4                    ; gave ammo
        plx
        lda     PL+PL_WEAPONOWNED,x
        bne     @owned
        lda     #1
        sta     PL+PL_WEAPONOWNED,x
        stx     PL+PL_PENDINGWEAPON
        sec
        rts
@owned: lda     tmp4
        lsr     a
        rts

; A = weaponinfo[A].ammo (WI_SIZE = 11)
wi_ammo:
        sta     tmp1
        asl     a
        sta     tmp2
        asl     a
        asl     a
        clc
        adc     tmp2
        adc     tmp1
        tax
        lda     _weaponinfo+WI_AMMO,x
        rts
.assert WI_SIZE = 11, error, "wi_ammo multiplies by 11"

.endif
