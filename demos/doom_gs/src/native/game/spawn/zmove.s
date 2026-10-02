; game/spawn/zmove.s: part spawn's height move (milestone 10, docs/GAME.md
; 2.4; docs/game-parts/spawn.md). A GPL-2 derivative of upstream's
; p_mobj65.s (P_ZMovement with TICSTEP 1, missileHit, shr3, isPlayer).
;
;   P_ZMovement  A:X = a mobj: the player's squat (a player below its
;                floor: viewheight less the step, deltaviewheight =
;                (VIEWHEIGHT - viewheight) >> 3); z += momz; on or below
;                the floor: a fall (momz < 0) ends (the player's hard
;                landing below -8 * GRAVITY: deltaviewheight = momz >> 3,
;                "oof" when alive), z = floorz, a missile explodes; in the
;                air gravity (momz -= GRAVITY, twice from rest) but with
;                MF_NOGRAVITY; then above the ceiling: a rise ends, z =
;                ceilingz - height, a missile explodes
;   missileHit   A:X = a mobj: a missile without MF_NOCLIP explodes
;                (part mobjstate's explode); C set when it did (A = 1),
;                else C clear (A = 0)
;   shr3         GA_0-3 = GA_0-3 >> 3, arithmetic (upstream's C:X)
;   p_mobj_isPlayer  A:X = a mobj: A = 1 (Z clear) when it is the
;                player's, else 0 (Z set)
;
; Signed 32-bit compares as upstream's SLT32: a - b on the four bytes,
; the sign of the result with the overflow folded in.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/spawn/sp.inc"

        .export P_ZMovement, missileHit, shr3, p_mobj_isPlayer
        .import mo_get, mo_dirty, S_StartSound
        .import fc_call, fc_unbuilt

; P_ZMovement's working copies (GA bytes it owns between its calls)
ZZ      = GA_4                  ; (4) z
ZF      = GA_8                  ; (4) floorz, then ceilingz
ZT      = GA_12                 ; (4) a difference, z + height

; ---------------------------------------------------------------------------
; P_ZMovement
; ---------------------------------------------------------------------------
        ROUTINE P_ZMovement
        sta ZM_MO
        stx ZM_MO+1
        FCALL p_mobj_isPlayer
        sta ZM_PL
        jsr zget                ; the line; ZZ = z, ZF = floorz
        lda ZM_PL
        beq @move
        jsr zlt                 ; the player below its floor: z < floorz
        bpl @move
        sec                     ; viewheight -= floorz - z
        ldx #0
        ldy #4
:       lda ZF,x
        sbc ZZ,x
        sta ZT,x
        inx
        dey
        bne :-
        sec
        ldx #0
        ldy #4
:       lda G_PLAYER + PL_VIEWHEIGHT,x
        sbc ZT,x
        sta G_PLAYER + PL_VIEWHEIGHT,x
        inx
        dey
        bne :-
        sec                     ; deltaviewheight = (VIEWHEIGHT -
        ldx #0                  ;   viewheight) >> 3
        ldy #4
:       lda vhconst,x
        sbc G_PLAYER + PL_VIEWHEIGHT,x
        sta GA_0,x
        inx
        dey
        bne :-
        FCALL shr3
        jsr dvh
        jsr zget                ; (the line again)
@move:  clc                     ; z += momz
        ldx #0
        ldy #LN_C + MC_MOMZ
:       lda ZZ,x
        adc (GC_MP),y
        sta ZZ,x
        iny
        inx
        txa
        eor #4
        bne :-                  ; (eor leaves the carry)
        ldy #TH_Z               ; (stored)
        jsr zput
        jsr zle                 ; on or below the floor: !(floorz < z)
        jmi @air
        ldy #LN_C + MC_MOMZ + 3 ; a fall: momz < 0
        lda (GC_MP),y
        bpl @onf
        ldx ZM_PL               ; the player lands hard: momz < -8 * GRAVITY
        beq @stop               ;   (its high word below $10000 - 8)
        cmp #$FF
        bcc @hard
        dey
        lda (GC_MP),y
        cmp #<($10000 - 8 * GRAVITY_HI)
        bcs @stop
@hard:  ldx #3                  ; deltaviewheight = momz >> 3
        ldy #LN_C + MC_MOMZ + 3
:       lda (GC_MP),y
        sta GA_0,x
        dey
        dex
        bpl :-
        FCALL shr3
        jsr dvh
        jsr zget
        ldy #LN_A + MA_HEALTH + 1 ; "oof" unless dead (health > 0)
        lda (GC_MP),y
        bmi @stop
        dey
        ora (GC_MP),y
        beq @stop
        lda #UC_SFX_OOF
        ldx ZM_MO
        ldy ZM_MO+1
        jsr S_StartSound
        jsr zget
@stop:  lda #0                  ; momz = 0
        ldy #LN_C + MC_MOMZ
        jsr fill4
        lda #D_C
        jsr mo_dirty
@onf:   ldy #TH_Z               ; z = floorz (ZF)
        ldx #0
:       lda ZF,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_RTH
        jsr mo_dirty
        lda ZM_MO
        ldx ZM_MO+1
        FCALL missileHit
        bcc @ceil
        rts
@air:   ldy #LN_B + MB_FLAGS + 1 ; gravity but with MF_NOGRAVITY
        lda (GC_MP),y
        and #>UC_MF_NOGRAVITY_LO
        bne @ceil0
        ldy #LN_C + MC_MOMZ     ; if (!momz) momz's high word = -GRAVITY
        lda (GC_MP),y
        iny
        ora (GC_MP),y
        iny
        ora (GC_MP),y
        iny
        ora (GC_MP),y
        bne :+
        lda #$FF
        sta (GC_MP),y
        dey
        sta (GC_MP),y
        iny
:       dey                     ; momz's high word -= GRAVITY
        sec
        lda (GC_MP),y
        sbc #<GRAVITY_HI
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sbc #>GRAVITY_HI
        sta (GC_MP),y
        lda #D_C
        jsr mo_dirty
        bra @ceil0
@ceil:  jsr zget                ; (the line again: missileHit's calls)
@ceil0: clc                     ; ZT = z + height
        ldx #0
        ldy #LN_B + MB_HEIGHT
:       lda ZZ,x
        adc (GC_MP),y
        sta ZT,x
        iny
        inx
        txa
        eor #4
        bne :-                  ; (eor leaves the carry)
        ldy #LN_B + MB_CEILZ    ; ZF = ceilingz
        ldx #ZF
        jsr ld4
        jsr zct                 ; ceilingz < z + height
        bpl @done
        ldy #LN_C + MC_MOMZ + 3 ; a rise ends: if (momz > 0) momz = 0
        lda (GC_MP),y
        bmi @top
        dey
        ora (GC_MP),y
        dey
        ora (GC_MP),y
        dey
        ora (GC_MP),y
        beq @top
        lda #0
        jsr fill4
        lda #D_C
        jsr mo_dirty
@top:   ldy #LN_B + MB_HEIGHT   ; z = ceilingz - height
        ldx #ZT
        jsr ld4
        ldx #0
        ldy #4
        sec
:       lda ZF,x
        sbc ZT,x
        sta ZZ,x
        inx
        dey
        bne :-
        ldy #TH_Z
        jsr zput
        lda ZM_MO
        ldx ZM_MO+1
        FCALL missileHit
@done:  rts

; zget: GC_MP = the line of ZM_MO; ZZ = z, ZF = floorz
zget:   lda ZM_MO
        ldx ZM_MO+1
        jsr mo_get
        ldy #TH_Z
        ldx #ZZ
        jsr ld4
        ldy #LN_B + MB_FLOORZ
        ldx #ZF
        ; (falls into ld4)

; ld4: the zero page's 4 bytes at X = the line's 4 bytes at Y
ld4:    lda #4
        sta GT_3
:       lda (GC_MP),y
        sta 0,x
        iny
        inx
        dec GT_3
        bne :-
        rts

; zput: the line's 4 bytes at Y = ZZ, its RTHING group dirty
zput:   ldx #0
:       lda ZZ,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_RTH
        jmp mo_dirty

; zlt: N set when ZZ < ZF (z < floorz); zle: N set when ZF < ZZ (floorz <
; z: in the air); zct: N set when ZF < ZT (ceilingz < z + height). Signed:
; the high byte's sign with the overflow folded in (inx and dey leave V)
zlt:    ldx #0
        ldy #4
        sec
:       lda ZZ,x
        sbc ZF,x
        inx
        dey
        bne :-
        bra sgn
zle:    ldx #0
        ldy #4
        sec
:       lda ZF,x
        sbc ZZ,x
        inx
        dey
        bne :-
        bra sgn
zct:    ldx #0
        ldy #4
        sec
:       lda ZF,x
        sbc ZT,x
        inx
        dey
        bne :-
sgn:    bvc :+
        eor #$80
:       ora #0                  ; (N from the result's high byte)
        rts

; dvh: the player's deltaviewheight = GA_0-3
dvh:    ldx #3
:       lda GA_0,x
        sta G_PLAYER + PL_DELTAVIEWHEIGHT,x
        dex
        bpl :-
        rts

; fill4: the line's 4 bytes at Y = A
fill4:  ldx #4
:       sta (GC_MP),y
        iny
        dex
        bne :-
        rts

; VIEWHEIGHT, 32 bits
vhconst: .byte <UC_VIEWHEIGHT_LO, >UC_VIEWHEIGHT_LO
        .byte <UC_VIEWHEIGHT_HI, >UC_VIEWHEIGHT_HI

; ---------------------------------------------------------------------------
; missileHit: a missile (not MF_NOCLIP) explodes; C set if it did
; ---------------------------------------------------------------------------
        ROUTINE missileHit
        sta GT_0
        stx GT_1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<UC_MF_MISSILE_HI
        beq @no
        dey
        lda (GC_MP),y
        and #>UC_MF_NOCLIP_LO
        bne @no
        lda GT_0
        ldx GT_1
        FCALL explode
        lda #1
        sec
        rts
@no:    lda #0
        clc
        rts

; ---------------------------------------------------------------------------
; shr3: GA_0-3 >>= 3, arithmetic
; ---------------------------------------------------------------------------
        ROUTINE shr3
        ldx #3
:       lda GA_3
        cmp #$80
        ror GA_3
        ror GA_2
        ror GA_1
        ror GA_0
        dex
        bne :-
        rts

; ---------------------------------------------------------------------------
; p_mobj_isPlayer: the player's mobj
; ---------------------------------------------------------------------------
        ROUTINE p_mobj_isPlayer
        cmp G_PLAYER + PL_MO
        bne @no
        cpx G_PLAYER + PL_MO + 1
        bne @no
        lda #1
        rts
@no:    lda #0
        rts
