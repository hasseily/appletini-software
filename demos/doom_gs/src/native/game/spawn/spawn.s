; game/spawn/spawn.s: part spawn's puffs and blood (milestone 10, docs/GAME.md
; 2.4; docs/game-parts/spawn.md). A GPL-2 derivative of upstream's
; p_spawn65.s (P_SpawnPuff, P_SpawnBlood, saveXYZ, zNoise, spawnXYZ,
; ticsNoise, thArg) and p_attack65.s (P_IsAttackRangeMeleeRange).
;
;   P_SpawnPuff  GA_X, GA_Y, GA_Z = x, y, z: a puff (MT_PUFF) at z +
;                (P_Random() - P_Random()) << 10, momz FRACUNIT, its tics
;                less P_Random() & 3 (at least 1), and S_PUFF3 when the
;                attack's range is MELEERANGE (a punch: no spark)
;   P_SpawnBlood GA_X, GA_Y, GA_Z, GA_DMG = x, y, z, damage (signed): blood
;                (MT_BLOOD) at the same noisy z, momz 2 * FRACUNIT, the
;                same tics noise, then S_BLOOD3 for damage < 9, S_BLOOD2
;                for 9 <= damage <= 12 (signed compares)
;   zNoise       GA_Z += (P_Random() - P_Random()) << 10 (the first call's
;                value less the second's)
;   spawnXYZ     A = a type, GA_X, GA_Y, GA_Z: P_SpawnMobj; the slot in
;                A:X and SP_TH (upstream's spawnXYZ takes SP_X, SP_Y, SP_Z:
;                natively the caller's GA_X..GA_Z, so that parts missile,
;                wfire and trymove call it with their own coordinates)
;   ticsNoise    A:X = a mobj: tics -= P_Random() & 3; at least 1
;   P_IsAttackRangeMeleeRange  A = 1 (Z clear) when attackrange (AT_RANGE)
;                is MELEERANGE, else 0 (Z set)
;
; upstream's saveXYZ (X:C, _Dp to SP_X..SP_Z), moArg and thArg (SM_MO,
; SP_TH to _Dp) copy arguments between upstream's registers, its _Dp and
; its near scratch; natively the coordinates stay in GA_X..GA_Z and the
; slot is A:X or SP_TH, so they have no code (request 3: glayout.INLINED).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/spawn/sp.inc"

        .export P_SpawnPuff, P_SpawnBlood, zNoise, spawnXYZ, ticsNoise
        .export P_IsAttackRangeMeleeRange
        .import mo_get, mo_dirty, pl_get, pl_put, g_random
        .import fc_call, fc_unbuilt

; ---------------------------------------------------------------------------
; P_SpawnPuff
; ---------------------------------------------------------------------------
        ROUTINE P_SpawnPuff
        FCALL zNoise            ; z += noise (saveXYZ: GA_X..GA_Z kept)
        lda #UC_MT_PUFF         ; the puff
        FCALL spawnXYZ
        ldy #1                  ; momz = FRACUNIT
        jsr momz
        lda SP_TH               ; the tics' noise
        ldx SP_TH+1
        FCALL ticsNoise
        FCALL P_IsAttackRangeMeleeRange
        beq @done
        lda SP_TH               ; a punch: P_SetMobjState(th, S_PUFF3)
        sta GA_MO
        lda SP_TH+1
        sta GA_MO+1
        lda #<UC_S_PUFF3
        ldx #>UC_S_PUFF3
        FCALL P_SetMobjState
@done:  rts

; momz: the momz of SP_TH = Y * FRACUNIT (Y the high word's low byte)
momz:   phy
        lda SP_TH
        ldx SP_TH+1
        jsr mo_get
        ply
        tya
        ldy #LN_C + MC_MOMZ + 2
        sta (GC_MP),y
        lda #0
        iny
        sta (GC_MP),y
        ldy #LN_C + MC_MOMZ + 1
        sta (GC_MP),y
        dey
        sta (GC_MP),y
        lda #D_C
        jmp mo_dirty

; ---------------------------------------------------------------------------
; P_SpawnBlood
; ---------------------------------------------------------------------------
        ROUTINE P_SpawnBlood
        lda GA_DMG              ; the damage (P_SpawnMobj's GA_TYPE is the
        sta SP_DMG              ;   same byte)
        lda GA_DMG+1
        sta SP_DMG+1
        FCALL zNoise
        lda #UC_MT_BLOOD
        FCALL spawnXYZ
        ldy #2                  ; momz = 2 * FRACUNIT
        jsr bmomz
        lda SP_TH
        ldx SP_TH+1
        FCALL ticsNoise
        sec                     ; damage < 9 (signed): S_BLOOD3
        lda SP_DMG
        sbc #9
        lda SP_DMG+1
        sbc #0
        bvc :+
        eor #$80
:       bmi @b3
        sec                     ; damage <= 12 (damage < 13): S_BLOOD2
        lda SP_DMG
        sbc #13
        lda SP_DMG+1
        sbc #0
        bvc :+
        eor #$80
:       bpl @done
        lda #<UC_S_BLOOD2
        ldx #>UC_S_BLOOD2
        bra @set
@b3:    lda #<UC_S_BLOOD3
        ldx #>UC_S_BLOOD3
@set:   ldy SP_TH               ; P_SetMobjState(th, state)
        sty GA_MO
        ldy SP_TH+1
        sty GA_MO+1
        FCALL P_SetMobjState
@done:  rts

; bmomz: momz for P_SpawnBlood's group (momz's twin: a routine's local code
; stays in its own group's segment)
bmomz:  phy
        lda SP_TH
        ldx SP_TH+1
        jsr mo_get
        ply
        tya
        ldy #LN_C + MC_MOMZ + 2
        sta (GC_MP),y
        lda #0
        iny
        sta (GC_MP),y
        ldy #LN_C + MC_MOMZ + 1
        sta (GC_MP),y
        dey
        sta (GC_MP),y
        lda #D_C
        jmp mo_dirty

; ---------------------------------------------------------------------------
; zNoise: GA_Z += d << 10, d = P_Random() - P_Random() (16 bits: -255..255)
; ---------------------------------------------------------------------------
        ROUTINE zNoise
        jsr g_random            ; t
        sta GT_0
        jsr g_random            ; r
        sta GT_1
        sec                     ; d = t - r: GT_0 low, GT_1 high
        lda GT_0
        sbc GT_1
        sta GT_0
        lda #0
        sbc #0
        sta GT_1
        asl GT_0                ; d << 2: bytes 1-3 of d << 10
        rol GT_1
        asl GT_0
        rol GT_1
        lda GT_1                ; (its sign for byte 3)
        and #$80
        beq :+
        lda #$FF
:       sta GT_2
        clc                     ; GA_Z bytes 1-3 += d << 2 (byte 0: + 0)
        lda GA_Z+1
        adc GT_0
        sta GA_Z+1
        lda GA_Z+2
        adc GT_1
        sta GA_Z+2
        lda GA_Z+3
        adc GT_2
        sta GA_Z+3
        rts

; ---------------------------------------------------------------------------
; spawnXYZ: P_SpawnMobj(GA_X, GA_Y, GA_Z, type A); SP_TH = A:X = the slot
; ---------------------------------------------------------------------------
        ROUTINE spawnXYZ
        sta GA_TYPE
        FCALL P_SpawnMobj
        sta SP_TH
        stx SP_TH+1
        rts

; ---------------------------------------------------------------------------
; ticsNoise: the mobj A:X's tics -= P_Random() & 3; at least 1 (the tics
; plane's byte: -1 is $FF, states' tics are -1 or 1-12)
; ---------------------------------------------------------------------------
        ROUTINE ticsNoise
        sta GT_0
        stx GT_1
        jsr g_random
        and #3
        sta GT_2
        lda GT_0
        ldx GT_1
        jsr pl_get
        sec
        lda PL_T
        sbc GT_2
        beq :+
        bpl :++
:       lda #1
:       sta PL_T
        lda GT_0
        ldx GT_1
        jmp pl_put

; ---------------------------------------------------------------------------
; P_IsAttackRangeMeleeRange
; ---------------------------------------------------------------------------
        ROUTINE P_IsAttackRangeMeleeRange
        lda AT_RANGE            ; MELEERANGE: $0040:0000
        ora AT_RANGE+1
        bne @no
        lda AT_RANGE+2
        cmp #<UC_MELEERANGE_HI
        bne @no
        lda AT_RANGE+3
        bne @no
        lda #1
        rts
@no:    lda #0
        rts
