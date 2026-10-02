; game/teleport/teleport.s: part teleport of milestone 10 (docs/GAME.md 2.4,
; wave 4): the teleporters. A GPL-2 derivative of upstream's p_telept65.s
; (EV_Teleport with its helpers fogSound, times20, destination; thingArg
; and destArg done in place), p_map65.s (P_TeleportMove, stompThing =
; PIT_StompThing, farFrom; tpThing done in place) and p_switch65.s (lnTele:
; LSTAB's teleporter entry).
;
; The native interfaces (docs/game-parts/teleport.md, "Interfaces"):
;
;   EV_Teleport      GA_0-1 = the line, GA_4-5 = the thing (a mobj handle),
;                    GA_6 = the side (0 front, 1 back): upstream's _Dp[0-3],
;                    _Dp[4-7] and C -> A = 1 teleported, else 0
;   lnTele           LSTAB's entry (P_CrossSpecialLine's convention, the
;                    same places): EV_Teleport's result in A
;   P_TeleportMove   GA_0-1 = the thing, GA_2-5 = x, GA_6-9 = y, GA_10 =
;                    boss (0, 1): upstream's _Dp[0-3], X:C, _Dp[4-7], 4,s
;                    -> A = 1 moved, 0 blocked; tmthing, tmx, tmy
;                    (GM_TMTHING, GM_TMX, GM_TMY), tmfloorz .. (baseFloorL)
;   stompThing       ITTAB's entry (geom's convention): GA_0-1 = a mobj ->
;                    C set go on, C clear blocked
;   fogSound         GA_X, GA_Y, GA_Z: a teleport fog there, its sound
;   times20          GA_0-3 = 20 * GA_0-3 (the low 32 bits)
;   destination      TP_LINE -> C set: TP_DEST the destination
;   farFrom          GC_MP the thing, Y = TH_X or TH_Y, X = 0 (tmx) or 4
;                    (tmy), GT_0-3 = the block distance -> C set when
;                    |the thing's - tm's| >= it (signed, as upstream)
;
; Upstream's 16-bit and pointer fields are native handles and bytes: a
; mobj a slot ($FFFF none), a sector a byte ($FF none), a thinker a handle
; (a mobj below SPEC_HANDLE, a special above). Its CLEARCLEAN is the kind
; plane's KIND_CLEAN bit (pl_get, pl_put).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/teleport/teleport.inc"

        .export EV_Teleport, lnTele, P_TeleportMove, stompThing
        .export fogSound, times20, destination, farFrom
        .import mo_get, mo_dirty, pl_get, pl_put, ss_get, sec_get, sp_get
        .import S_StartSound, finesine, finecosine
        .import fc_call, fc_unbuilt

PLR     = G_PLAYER
REACT_PLAYER = 18               ; the player waits 18 tics (p_telept65.s:193)
TELEFRAG = 10000                ; stompThing's damage (p_map65.s:3586)
MAXRADIUS_UNITS = 32            ; blockRange's growth (p_map65.s:3449)

; IS_PLAYER at: Z set when the handle at `at` is the player's mobj
.macro IS_PLAYER at
        lda PLR + PL_MO
        cmp at
        bne :+
        lda PLR + PL_MO + 1
        cmp at + 1
:
.endmacro

; MOGET at: GC_MP = the mobj whose handle is at `at`
.macro MOGET at
        lda at
        ldx at + 1
        jsr mo_get
.endmacro

; ===========================================================================
; EV_Teleport: a thing on the front side (not a missile) goes to the
; teleport destination in a sector with the tag of the line, with fog and
; sound at both ends, and stops there
; ===========================================================================
        ROUTINE EV_Teleport
        lda GA_6                ; the back side: no
        bne @no
        lda GA_0
        sta TP_LINE
        lda GA_1
        sta TP_LINE + 1
        lda GA_4
        sta TP_THING
        lda GA_5
        sta TP_THING + 1
        MOGET TP_THING          ; a missile: no
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<UC_MF_MISSILE_HI
        bne @no
        FCALL destination
        bcs @found
@no:    lda #0
        rts
@found: MOGET TP_THING          ; the old position
        ldy #TH_Z + 3
:       lda (GC_MP),y
        sta TP_OX,y
        dey
        bpl :-
        MOGET TP_DEST           ; P_TeleportMove(thing, m->x, m->y, false)
        ldy #TH_Y + 3
:       lda (GC_MP),y
        sta GA_2,y
        dey
        bpl :-
        lda TP_THING
        sta GA_0
        lda TP_THING + 1
        sta GA_1
        stz GA_10
        FCALL P_TeleportMove
        cmp #0
        beq @no
        lda TP_THING            ; z = floorz (CLEARCLEAN)
        ldx TP_THING + 1
        jsr clean
        MOGET TP_THING
        ldy #LN_B + MB_FLOORZ + 3
        ldx #3
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        ldy #TH_Z + 3
        ldx #3
:       lda GT_0,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        lda #D_RTH
        jsr mo_dirty
        IS_PLAYER TP_THING      ; the player: viewz = z + viewheight
        bne @fog1
        clc
        ldx #0
        ldy #4
:       lda GT_0,x
        adc PLR + PL_VIEWHEIGHT,x
        sta PLR + PL_VIEWZ_G,x
        inx
        dey
        bne :-
@fog1:  ldx #11                 ; the fog at the old position
:       lda TP_OX,x
        sta GA_X,x
        dex
        bpl :-
        FCALL fogSound
        MOGET TP_DEST           ; the fog 20 units in front of the
        ldy #TH_ANG + 1         ;   destination: an = angle >> 19
        lda (GC_MP),y
        sta TP_AN + 1
        dey
        lda (GC_MP),y
        ldx #3
:       lsr TP_AN + 1
        ror a
        dex
        bne :-
        sta TP_AN
        lda TP_AN               ; y + 20 * finesine(an)
        sta M_A
        lda TP_AN + 1
        sta M_A + 1
        jsr finesine
        ldy #TH_Y
        jsr front
        lda TP_AN               ; x + 20 * finecosine(an)
        sta M_A
        lda TP_AN + 1
        sta M_A + 1
        jsr finecosine
        ldy #TH_X
        jsr front
        MOGET TP_THING          ; P_SpawnMobj(x, y, thing->z, MT_TFOG)
        ldy #TH_Z + 3
        ldx #3
:       lda (GC_MP),y
        sta GA_Z,x
        dey
        dex
        bpl :-
        ldx #7
:       lda TP_OX,x
        sta GA_X,x
        dex
        bpl :-
        FCALL fogSound
        MOGET TP_DEST           ; angle = m->angle
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
        MOGET TP_THING
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
        lda #0                  ; no momentum
        ldy #LN_C + MC_MOMX
:       sta (GC_MP),y
        iny
        cpy #LN_C + MC_MOMZ + 4
        bne :-
        IS_PLAYER TP_THING      ; the player waits 18 tics
        bne @dirty
        ldy #LN_C + MC_REACT
        lda #<REACT_PLAYER
        sta (GC_MP),y
        iny
        lda #>REACT_PLAYER
        sta (GC_MP),y
@dirty: lda #D_RTH | D_C
        jsr mo_dirty
        IS_PLAYER TP_THING      ; the player: no bob momentum
        bne @yes
        ldx #7
:       stz PLR + PL_MOMX,x
        dex
        bpl :-
@yes:   lda #1
        rts

; front: TP_OX + Y (Y = TH_X, TH_Y) = the destination's x or y + 20 M_R
; (upstream's times20, then the add)
front:  phy
        ldx #3
:       lda M_R,x
        sta GA_0,x
        dex
        bpl :-
        FCALL times20
        MOGET TP_DEST
        ply
        ldx #0
        clc
:       lda (GC_MP),y
        adc GA_0,x
        sta TP_OX,y
        iny
        inx
        txa
        eor #4
        bne :-
        rts

; clean: CLEARCLEAN of the mobj A:X (its kind plane's KIND_CLEAN bit)
clean:  pha
        phx
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        plx
        pla
        jmp pl_put

; ===========================================================================
; lnTele: LSTAB's teleporter (p_switch65.s:515): EV_Teleport(line, side,
; thing), its result
; ===========================================================================
        ROUTINE lnTele
        FCALL EV_Teleport
        rts

; ===========================================================================
; fogSound: S_StartSound(P_SpawnMobj(GA_X, GA_Y, GA_Z, MT_TFOG),
; sfx_telept)
; ===========================================================================
        ROUTINE fogSound
        lda #UC_MT_TFOG
        sta GA_TYPE
        FCALL P_SpawnMobj
        pha                     ; the origin in Y:X
        txa
        tay
        plx
        lda #UC_SFX_TELEPT
        jmp S_StartSound

; ===========================================================================
; times20: GA_0-3 = 20 * GA_0-3 (fixed_t, the low 32 bits): 4 v + 16 v
; ===========================================================================
        ROUTINE times20
        ldx #2                  ; 4 v
:       asl GA_0
        rol GA_1
        rol GA_2
        rol GA_3
        dex
        bne :-
        ldx #3                  ; GT_0-3 = 16 v
:       lda GA_0,x
        sta GT_0,x
        dex
        bpl :-
        ldx #2
:       asl GT_0
        rol GT_1
        rol GT_2
        rol GT_3
        dex
        bne :-
        ldx #0                  ; 4 v + 16 v
        ldy #4
        clc
:       lda GA_0,x
        adc GT_0,x
        sta GA_0,x
        inx
        dey
        bne :-
        rts

; ===========================================================================
; destination: P_TeleportDestination(TP_LINE): for each sector with the tag
; of the line, the first teleport destination thing in it, in the order of
; the thinkers. C set when there is one: TP_DEST
; ===========================================================================
        ROUTINE destination
        lda #$FF                ; (the search from the first sector)
        sta TP_SEC
@sec:   lda TP_LINE
        ldx TP_LINE + 1
        ldy TP_SEC
        FCALL P_FindSectorFromLineTag
        sta TP_SEC
        cmp #NO_SECTOR
        bne @first
        clc
        rts
@first: lda G_THFIRST           ; th = the first thinker
        ldx G_THFIRST + 1
@th:    sta TP_TH
        stx TP_TH + 1
        cpx #$FF                ; the end: the next sector
        beq @sec
        cpx #>SPEC_HANDLE       ; a special: its next
        bcc @mobj
        jsr sp_get
        ldy #SP_THNEXT + 1
        lda (GC_XP),y
        tax
        dey
        lda (GC_XP),y
        bra @th
@mobj:  jsr pl_get              ; a mobj: its function, its next
        lda PL_N
        sta TP_NX
        lda PL_N + 1
        sta TP_NX + 1
        lda PL_K
        and #$FF ^ KIND_CLEAN   ; P_MobjThinker (CLEAN or not)
        cmp #FN_MOBJ
        bne @next
        MOGET TP_TH             ; a teleport destination
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        cmp #UC_MT_TELEPORTMAN
        bne @next
        ldy #LN_A + MA_SUBSEC + 1       ; in the sector
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        cmp TP_SEC
        bne @next
        lda TP_TH
        sta TP_DEST
        lda TP_TH + 1
        sta TP_DEST + 1
        sec
        rts
@next:  lda TP_NX
        ldx TP_NX + 1
        bra @th

; ===========================================================================
; P_TeleportMove: the thing moves to x, y. A shootable thing in the way
; dies (telefrag) when the thing is the player or boss is set, else it
; stops the move
; ===========================================================================
        ROUTINE P_TeleportMove
        ldx #3
:       lda GA_2,x              ; tmx = MP_TPX = x, tmy = MP_TPY = y
        sta GM_TMX,x
        sta TP_TPX,x
        lda GA_6,x
        sta GM_TMY,x
        sta TP_TPY,x
        dex
        bpl :-
        lda GA_0                ; tmthing = MP_TPT = the thing
        sta GM_TMTHING
        sta TP_TPT
        lda GA_1
        sta GM_TMTHING + 1
        sta TP_TPT + 1
        lda GA_10               ; telefrag = the player || boss
        sta TP_TF
        IS_PLAYER GM_TMTHING
        bne :+
        inc TP_TF
:       FCALL setBox            ; (the thing in GA_0-1; tmx, tmy)
        ldx #7
:       lda GM_TMX,x
        sta GA_X,x
        dex
        bpl :-
        FCALL baseFloorL
        ldx #15                 ; the things in the blocks grown by
:       lda GM_TMBBOX,x         ;   MAXRADIUS (the loop's state on the
        sta GA_0,x              ;   stack: P_DamageMobj runs game logic)
        dex
        bpl :-
        lda #MAXRADIUS_UNITS
        sta GA_16
        stz GA_17
        FCALL blockRange
        bcs @move
        lda GM_BYH              ; $0101,x bx, $0102 XH, $0103 YL, $0104 YH
        pha
        lda GM_BYL
        pha
        lda GM_BXH
        pha
        lda GM_BXL
        pha
@col:   tsx                     ; by = YL
        lda $0103,x
        pha                     ; $0101 by, $0102 bx, $0103 XH, .., $0105 YH
@row:   tsx                     ; P_BlockThingsIterator(bx, by, stompThing)
        lda $0102,x
        sta GA_0
        stz GA_1
        lda $0101,x
        sta GA_2
        stz GA_3
        lda #ITTAB_stompThing
        sta GA_4
        FCALL P_BlockThingsIterator
        cmp #0
        bne @go
        pla                     ; a thing in the way: false
        pla
        pla
        pla
        pla
        lda #0
        rts
@go:    tsx                     ; by++ while by <= YH
        lda $0101,x
        cmp $0105,x
        inc $0101,x
        bcc @row
        pla
        tsx                     ; bx++ while bx <= XH
        lda $0101,x
        cmp $0102,x
        inc $0101,x
        bcc @col
        pla
        pla
        pla
        pla
@move:  lda TP_TPT              ; out of the old blocks and sectors
        ldx TP_TPT + 1
        FCALL P_UnsetThingPosition
        lda TP_TPT              ; CLEARCLEAN
        ldx TP_TPT + 1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda TP_TPT
        ldx TP_TPT + 1
        jsr pl_put
        MOGET TP_TPT            ; floorz, ceilingz, dropoffz, x, y
        ldy #LN_B + MB_FLOORZ + 11
        ldx #11
:       lda GM_TMFLOORZ,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        ldy #TH_Y + 3
:       lda TP_TPX,y
        sta (GC_MP),y
        dey
        bpl :-
        lda #D_RTH | D_B
        jsr mo_dirty
        lda TP_TPT              ; into the new ones
        ldx TP_TPT + 1
        FCALL P_SetThingPosition
        lda #1
        rts

; ===========================================================================
; stompThing: PIT_StompThing (ITTAB): a shootable thing (not tmthing) in
; the way dies when telefrag, else it blocks the move
; ===========================================================================
        ROUTINE stompThing
        lda GA_0                ; not tmthing
        cmp GM_TMTHING
        bne @other
        lda GA_1
        cmp GM_TMTHING + 1
        jeq @on
@other: lda GA_0                ; shootable
        ldx GA_1
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        jeq @on
        ldy #LN_B + MB_RADIUS + 3       ; blockdist = thing->radius +
        ldx #3                          ;   tmthing->radius (GT_0-3)
:       lda (GC_MP),y
        sta GT_0,x
        dey
        dex
        bpl :-
        MOGET GM_TMTHING
        ldy #LN_B + MB_RADIUS
        ldx #0
        clc
:       lda (GC_MP),y
        adc GT_0,x
        sta GT_0,x
        iny
        inx
        txa
        eor #4
        bne :-
        lda GA_0                ; |thing->x - tmx| >= blockdist: go on
        ldx GA_1
        jsr mo_get
        ldy #TH_X
        ldx #0
        FCALL farFrom
        jcs @on
        ldy #TH_Y               ; |thing->y - tmy| >= blockdist: go on
        ldx #4
        FCALL farFrom
        jcs @on
        lda TP_TF               ; no telefrag: blocked
        bne @frag
        clc
        rts
@frag:
        lda GM_TMTHING          ; P_DamageMobj(thing, tmthing, tmthing,
        sta GA_2                ;   10000)
        sta GA_4
        lda GM_TMTHING + 1
        sta GA_3
        sta GA_5
        lda #<TELEFRAG
        sta GA_6
        lda #>TELEFRAG
        sta GA_7
        FCALL P_DamageMobj
        ; (upstream's P_CreateSecNodeList leaves tmx, tmy = its thing's
        ; x, y, p_map65.s:2524-2531: when the damage sets a thing in the
        ; level, a dropped item at the victim's x, y, the later stomps of
        ; this move measure from there; the core's gp_secnodes does the
        ; same, request R4 as integrated)
@on:    sec
        rts

; ===========================================================================
; farFrom: C set when |the fixed_t at Y of the mobj GC_MP - the one at
; GM_TMX + X| >= GT_0-3, a signed compare as upstream's (SLT32); changes
; GT_4-7
; ===========================================================================
        ROUTINE farFrom
        sec
        lda (GC_MP),y
        sbc GM_TMX,x
        sta GT_4
        iny
        lda (GC_MP),y
        sbc GM_TMX + 1,x
        sta GT_5
        iny
        lda (GC_MP),y
        sbc GM_TMX + 2,x
        sta GT_6
        iny
        lda (GC_MP),y
        sbc GM_TMX + 3,x
        sta GT_7
        bpl @abs                ; negative: its negation
        ldx #0
        ldy #4
        sec
:       lda #0
        sbc GT_4,x
        sta GT_4,x
        inx
        dey
        bne :-
@abs:   lda GT_4                ; |d| < blockdist (signed): near
        cmp GT_0
        lda GT_5
        sbc GT_1
        lda GT_6
        sbc GT_2
        lda GT_7
        sbc GT_3
        bvc :+
        eor #$80
:       bmi @near
        sec
        rts
@near:  clc
        rts
