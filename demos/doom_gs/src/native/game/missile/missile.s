; game/missile/missile.s: part missile, a monster's missile (milestone 10,
; docs/GAME.md 2.4; docs/game-parts/missile.md). A GPL-2 derivative of
; upstream's p_spawn65.s (P_SpawnMissile, checkMissile and their helpers
; srcArg, srcAbove, seeTarget, thSpeed, destDelta, angleMom, speedMom,
; halfMom).
;
;   P_SpawnMissile  GA_0-1 = the source, GA_2-3 = the destination, A = the
;                   type: a missile from 32 units above the source toward
;                   the destination (its angle off by (P_Random() -
;                   P_Random()) << 20 for a shadow destination), its see
;                   sound, target = the source, momx and momy by the
;                   angle at the type's speed, momz = (dest->z -
;                   source->z) / dist (math.s's sdiv32: C's truncation),
;                   dist = P_AproxDistance(dx, dy) / speed at least 1; then
;                   checkMissile. Returns the missile in A:X
;   checkMissile    A:X = a mobj (upstream's P_CheckMissileSpawn of
;                   SP_TH): its tics less P_Random() & 3 (at least 1), half
;                   a move forward (x, y, z += mom >> 1), and for a missile
;                   P_TryMove there; a refused move explodes it
;                   (P_ExplodeMissile). Returns nothing
;
; The helpers part wfire's P_SpawnPlayerMissile shares (GAME.md 2.4: a
; helper two parts need is the earlier part's), each a routine:
;   srcAbove        A:X = a mobj: GA_X, GA_Y, GA_Z = its x, y and z + 32 *
;                   FRACUNIT (upstream's SP_X, SP_Y, SP_Z: P_SpawnMobj's
;                   place, for spawnXYZ)
;   seeTarget       A:X = the missile, GA_0-1 = the source: the missile's
;                   see sound (if its type has one), its target = the source
;   thSpeed         A:X = a mobj: M_A = mobjinfo[its type].speed (4 bytes)
;   angleMom        A:X = the missile, GA_0-3 = the angle: its angle = it;
;                   momx, momy = FixedMulAngle(speed, finecosine,
;                   finesine [angle >> 19]) (upstream's speedMom, which only
;                   angleMom calls, is its local code)
;   halfMom         the fixed_t at line offset X of the mobj line GC_MP +=
;                   the one at line offset Y >> 1 (arithmetic shift, a
;                   32-bit sum: upstream's halfMom exactly); the caller
;                   marks the line dirty. Changes A, X, Y, GT_0-GT_4
;
; Upstream's srcArg (_Dp = SP_SRC) has no code; destDelta, which only
; P_SpawnMissile calls, is its local code (delta): request 1,
; glayout.INLINED.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/missile/missile.inc"

        .export P_SpawnMissile, checkMissile, halfMom
        .export srcAbove, seeTarget, thSpeed, angleMom
        .import mo_get, mo_dirty, mi_get, g_random, S_StartSound
        .import pta3, aproxdist, finesine, finecosine, fixmulang, sdiv32
        .import fc_call, fc_unbuilt

; ===========================================================================
; P_SpawnMissile
; ===========================================================================
        ROUTINE P_SpawnMissile
        pha                     ; (the type)
        lda GA_0
        sta MSL_SRC
        lda GA_1
        sta MSL_SRC+1
        lda GA_2
        sta MSL_DEST
        lda GA_3
        sta MSL_DEST+1
        lda MSL_SRC             ; x, y and z + 32 of the source
        ldx MSL_SRC+1
        FCALL srcAbove
        pla
        FCALL spawnXYZ          ; th = P_SpawnMobj(x, y, z, type)
        sta MSL_TH
        stx MSL_TH+1
        ldy MSL_SRC             ; the see sound; target = source
        sty GA_0
        ldy MSL_SRC+1
        sty GA_1
        FCALL seeTarget
        jsr delta               ; an = R_PointToAngle2(source, dest)
        jsr pta3
        ldx #3
:       lda M_R,x
        sta MSL_AN,x
        dex
        bpl :-
        lda MSL_DEST            ; a shadow dest: an += (P_Random() -
        ldx MSL_DEST+1          ;   P_Random()) << 20 (the first call's
        jsr mo_get              ;   value less the second's)
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<UC_MF_SHADOW_HI
        beq @mom
        jsr g_random
        sta GT_0
        jsr g_random
        sta GT_1
        sec                     ; d = t - r (16 bits)
        lda GT_0
        sbc GT_1
        sta GT_0
        lda #0
        sbc #0
        sta GT_1
        ldx #4                  ; the angle's high word += d << 4
:       asl GT_0
        rol GT_1
        dex
        bne :-
        clc
        lda MSL_AN+2
        adc GT_0
        sta MSL_AN+2
        lda MSL_AN+3
        adc GT_1
        sta MSL_AN+3
@mom:   ldx #3                  ; the angle, momx, momy
:       lda MSL_AN,x
        sta GA_0,x
        dex
        bpl :-
        lda MSL_TH
        ldx MSL_TH+1
        FCALL angleMom
        jsr delta               ; dist = P_AproxDistance(dx, dy) / speed
        jsr aproxdist
        ldx #3
:       lda M_R,x
        sta MSL_T,x
        dex
        bpl :-
        lda MSL_TH
        ldx MSL_TH+1
        FCALL thSpeed
        ldx #3
:       lda M_A,x
        sta M_B,x
        lda MSL_T,x
        sta M_A,x
        dex
        bpl :-
        jsr sdiv32
        lda M_R+3               ; at least 1
        bmi @one
        ora M_R+2
        ora M_R+1
        ora M_R
        bne @dz
@one:   lda #1
        sta M_R
        stz M_R+1
        stz M_R+2
        stz M_R+3
@dz:    ldx #3                  ; momz = (dest->z - source->z) / dist
:       lda M_R,x
        sta M_B,x
        dex
        bpl :-
        lda MSL_DEST
        ldx MSL_DEST+1
        jsr mo_get
        ldy #TH_Z + 3
        ldx #3
:       lda (GC_MP),y
        sta M_A,x
        dey
        dex
        bpl :-
        lda MSL_SRC
        ldx MSL_SRC+1
        jsr mo_get
        ldx #M_A
        ldy #TH_Z
        jsr sub4
        jsr sdiv32
        lda MSL_TH
        ldx MSL_TH+1
        jsr mo_get
        ldy #LN_C + MC_MOMZ
        ldx #0
:       lda M_R,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_C
        jsr mo_dirty
        lda MSL_TH              ; P_CheckMissileSpawn(th); th, kept on the
        pha                     ;   stack, is the result
        ldx MSL_TH+1
        phx
        FCALL checkMissile
        plx
        pla
        rts

; delta (destDelta): M_A = dest->x - source->x, M_B = dest->y - source->y
delta:  lda MSL_DEST
        ldx MSL_DEST+1
        jsr mo_get
        ldy #TH_Y + 3
:       lda (GC_MP),y
        sta M_A,y
        dey
        bpl :-
        lda MSL_SRC
        ldx MSL_SRC+1
        jsr mo_get
        ldx #M_A
        ldy #TH_X
        jsr sub4
        ldx #M_B
        ldy #TH_Y
        ; fall into sub4

; sub4: the 4 bytes at zero page X -= the line's 4 bytes at Y
sub4:   lda #4
        sta GT_1
        sec
:       lda $00,x
        sbc (GC_MP),y
        sta $00,x
        iny
        inx
        dec GT_1
        bne :-
        rts

; ===========================================================================
; srcAbove
; ===========================================================================
        ROUTINE srcAbove
        jsr mo_get
        ldy #TH_Z + 3
:       lda (GC_MP),y
        sta GA_X,y
        dey
        bpl :-
        clc
        lda GA_Z+2
        adc #32
        sta GA_Z+2
        bcc :+
        inc GA_Z+3
:       rts

; ===========================================================================
; seeTarget
; ===========================================================================
        ROUTINE seeTarget
        sta MSL_HT
        stx MSL_HT+1
        lda GA_0
        sta MSL_HS
        lda GA_1
        sta MSL_HS+1
        lda MSL_HT
        jsr mo_get              ; mobjinfo[th->type].seesound
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        ldy #UO_MI_SEESOUND
        jsr mi_get
        stx GT_0
        ora GT_0
        beq @tgt
        lda API_W               ; S_StartSound(th, the sound)
        ldx MSL_HT
        ldy MSL_HT+1
        jsr S_StartSound
@tgt:   lda MSL_HT              ; th->target = source
        ldx MSL_HT+1
        jsr mo_get
        ldy #LN_A + MA_TARGET
        lda MSL_HS
        sta (GC_MP),y
        iny
        lda MSL_HS+1
        sta (GC_MP),y
        lda #D_A
        jmp mo_dirty

; ===========================================================================
; thSpeed
; ===========================================================================
        ROUTINE thSpeed
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        pha
        ldy #UO_MI_SPEED
        jsr mi_get
        sta M_A
        stx M_A+1
        pla
        ldy #UO_MI_SPEED + 2
        jsr mi_get
        sta M_A+2
        stx M_A+3
        rts

; ===========================================================================
; angleMom
; ===========================================================================
        ROUTINE angleMom
        sta MSL_HT
        stx MSL_HT+1
        ldx #3
:       lda GA_0,x
        sta MSL_HA,x
        dex
        bpl :-
        lda MSL_HT              ; the speed
        ldx MSL_HT+1
        FCALL thSpeed
        ldx #3
:       lda M_A,x
        sta MSL_SPD,x
        dex
        bpl :-
        lda MSL_HT              ; th->angle = an
        ldx MSL_HT+1
        jsr mo_get
        ldy #TH_ANGLO
        lda MSL_HA
        sta (GC_MP),y
        iny
        lda MSL_HA+1
        sta (GC_MP),y
        ldy #TH_ANG
        lda MSL_HA+2
        sta (GC_MP),y
        iny
        lda MSL_HA+3
        sta (GC_MP),y
        lda #D_RTH
        jsr mo_dirty
        jsr fine_arg            ; momx = FixedMulAngle(speed,
        jsr finecosine          ;   finecosine[an >> 19])
        ldy #LN_C + MC_MOMX
        jsr speed_mom
        jsr fine_arg            ; momy = FixedMulAngle(speed,
        jsr finesine            ;   finesine[an >> 19])
        ldy #LN_C + MC_MOMY
        ; fall into speed_mom

; speed_mom (speedMom): the missile's fixed_t at line offset Y =
; FixedMulAngle(speed, M_R); group C dirty
speed_mom:
        phy
        ldx #3
:       lda M_R,x
        sta M_B,x
        lda MSL_SPD,x
        sta M_A,x
        dex
        bpl :-
        jsr fixmulang
        lda MSL_HT
        ldx MSL_HT+1
        jsr mo_get
        ply
        ldx #0
:       lda M_R,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_C
        jmp mo_dirty

; fine_arg: M_A = an >> 19 (the high word >> 3: 0-8191)
fine_arg:
        lda MSL_HA+3
        sta M_A+1
        lda MSL_HA+2
        lsr M_A+1
        ror a
        lsr M_A+1
        ror a
        lsr M_A+1
        ror a
        sta M_A
        rts

; ===========================================================================
; checkMissile
; ===========================================================================
        ROUTINE checkMissile
        sta MSL_CK
        stx MSL_CK+1
        FCALL ticsNoise         ; tics -= P_Random() & 3, at least 1
        lda MSL_CK
        ldx MSL_CK+1
        jsr mo_get
        ldx #TH_X               ; x += momx >> 1; y, z the same
        ldy #LN_C + MC_MOMX
        FCALL halfMom
        ldx #TH_Y
        ldy #LN_C + MC_MOMY
        FCALL halfMom
        ldx #TH_Z
        ldy #LN_C + MC_MOMZ
        FCALL halfMom
        lda #D_RTH
        jsr mo_dirty
        ldy #LN_B + MB_FLAGS + 2        ; not a missile: done
        lda (GC_MP),y
        and #<UC_MF_MISSILE_HI
        beq @done
        ldy #TH_Y + 3           ; P_TryMove(th, th->x, th->y)
:       lda (GC_MP),y
        sta GA_2,y
        dey
        bpl :-
        lda MSL_CK              ; (th on the stack over P_TryMove)
        sta GA_0
        pha
        lda MSL_CK+1
        sta GA_1
        pha
        FCALL P_TryMove
        plx                     ; th back from the stack (X high, Y low)
        ply
        cmp #0
        bne @done
        tya                     ; refused: P_ExplodeMissile(th)
        FCALL P_ExplodeMissile
@done:  rts

; ===========================================================================
; halfMom
; ===========================================================================
        ROUTINE halfMom
        stx GT_0
        ldx #0                  ; GT_1-GT_4 = the one at Y
:       lda (GC_MP),y
        sta GT_1,x
        iny
        inx
        cpx #4
        bne :-
        lda GT_4                ; >> 1, arithmetic
        cmp #$80
        ror GT_4
        ror GT_3
        ror GT_2
        ror GT_1
        ldy GT_0                ; the one at X += it
        ldx #0
        clc
:       lda (GC_MP),y
        adc GT_1,x
        sta (GC_MP),y
        iny
        inx
        txa                     ; (the count, the carry kept)
        eor #4
        bne :-
        rts
