; game/trymove/nightmare.s: part trymove's nightmare respawn (milestone 10,
; docs/GAME.md 2.4 row trymove; docs/game-parts/trymove.md). A GPL-2
; derivative of upstream's p_spawn65.s (P_NightmareRespawn with nmArg, nmXY,
; subFloor and fog).
;
;   P_NightmareRespawn  A:X = a dead monster (nightmare). Back at the place
;               of its death, not its spawn point (p_spawn65.s:1121-1124):
;               none when its x and y are both 0; else when
;               P_CheckPosition(it, x, y) (part checkpos) finds room, a
;               teleport fog (MT_TFOG, sfx_telept) at x, y on the floor of
;               its subsector's sector, another at x, y on the floor of
;               R_PointInSubsector(x, y)'s sector, then P_SpawnMobj(x, y,
;               ONFLOORZ, its type) (spawnXYZ: part spawn) with its angle
;               and reaction time 18, then P_RemoveMobj(it) (part
;               mobjstate)
;
; upstream's nmArg and nmXY (NR_MO to _Dp, its x, y to SP_X, SP_Y), subFloor
; (a subsector's floor to SP_Z) and fog are done in place: natively the
; coordinates go straight into GA_X..GA_Z (spawnXYZ's), the mobj is a
; handle (NR_MO, trymove.inc). Every record through the object API.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/trymove/trymove.inc"

        .export P_NightmareRespawn
        .import mo_get, mo_dirty, sec_get, ss_get, gp_pointsub, S_StartSound
        .import fc_call, fc_unbuilt

        ROUTINE P_NightmareRespawn
        sta NR_MO
        stx NR_MO+1
        jsr mo_get                      ; x = y = 0: no
        ldy #TH_X + 7
        lda #0
:       ora (GC_MP),y
        dey
        bpl :-
        .assert TH_X = 0, error, "x first"
        tax
        bne :+
        rts
:       ldy #TH_X + 7                   ; P_CheckPosition(mobj, x, y)
        ldx #7
:       lda (GC_MP),y
        sta GA_2,x
        dey
        dex
        bpl :-
        lda NR_MO
        sta GA_0
        lda NR_MO+1
        sta GA_1
        FCALL P_CheckPosition
        cmp #0
        bne :+
        rts
:       jsr nr_get                      ; the fog at the old spot, on the
        ldy #LN_A + MA_SUBSEC + 1       ;   floor of its subsector's sector
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr nr_floor
        jsr nr_fog
        jsr nr_xy                       ; the fog at the new spot (the same
        ldx #3                          ;   x, y), on the floor of the
:       lda GA_X,x                      ;   sector of R_PointInSubsector(x,
        sta GC_X,x                      ;   y)
        lda GA_Y,x
        sta GC_Y,x
        dex
        bpl :-
        jsr gp_pointsub
        lda GC_S
        ldx GC_S+1
        jsr nr_floor
        jsr nr_fog
        jsr nr_xy                       ; P_SpawnMobj(x, y, ONFLOORZ, type)
        stz GA_Z
        stz GA_Z+1
        lda #<(UC_ONFLOORZ_HI & $FFFF)
        sta GA_Z+2
        lda #>(UC_ONFLOORZ_HI & $FFFF)
        sta GA_Z+3
        .assert UC_ONFLOORZ_LO = 0 && (UC_ONFLOORZ_HI & $FFFF) = $8000, error, "ONFLOORZ: $8000:0000"
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        FCALL spawnXYZ
        sta NR_NEW
        stx NR_NEW+1
        jsr nr_get                      ; angle = mobj->angle
        ldy #TH_ANG
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        ldy #TH_ANGLO
        lda (GC_MP),y
        sta GT_2
        iny
        lda (GC_MP),y
        sta GT_3
        lda NR_NEW
        ldx NR_NEW+1
        jsr mo_get
        ldy #TH_ANG
        lda GT_0
        sta (GC_MP),y
        iny
        lda GT_1
        sta (GC_MP),y
        ldy #TH_ANGLO
        lda GT_2
        sta (GC_MP),y
        iny
        lda GT_3
        sta (GC_MP),y
        ldy #LN_C + MC_REACT            ; reactiontime 18
        lda #18
        sta (GC_MP),y
        iny
        lda #0
        sta (GC_MP),y
        lda #D_RTH | D_C
        jsr mo_dirty
        lda NR_MO                       ; P_RemoveMobj(mobj)
        ldx NR_MO+1
        FCALL P_RemoveMobj
        rts

; nr_get: GC_MP = the dead monster's line
nr_get: lda NR_MO
        ldx NR_MO+1
        jmp mo_get

; nr_xy: GA_X, GA_Y = the dead monster's x, y (nmXY); GC_MP its line
nr_xy:  jsr nr_get
        ldy #TH_X + 7
        ldx #7
:       lda (GC_MP),y
        sta GA_X,x
        dey
        dex
        bpl :-
        rts

; nr_floor: GA_Z = the floor of the sector of subsector A:X (subFloor)
nr_floor:
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        ldy #SEC_FLOOR + 3
:       lda (GC_SP),y
        sta GA_Z - SEC_FLOOR,y
        dey
        bpl :-
        .assert SEC_FLOOR = 0, error, "the floor first"
        rts

; nr_fog: S_StartSound(P_SpawnMobj(the dead monster's x, y, GA_Z, MT_TFOG),
; sfx_telept) (fog)
nr_fog: jsr nr_xy
        lda #UC_MT_TFOG
        FCALL spawnXYZ
        phx                             ; Y:X the origin (X its low byte)
        tax
        ply
        lda #UC_SFX_TELEPT
        jmp S_StartSound
