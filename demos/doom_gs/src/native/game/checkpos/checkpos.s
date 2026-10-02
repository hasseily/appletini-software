; game/checkpos/checkpos.s: part checkpos of milestone 10 (docs/GAME.md 2.4
; row checkpos; docs/game-parts/checkpos.md): whether a thing fits at a
; place. A GPL-2 derivative of upstream's p_map65.s (P_CheckPosition,
; cpCopy, checkPos with loadRad, setBox, walkRange, lineBlocks's
; PIT_CheckLine mode with lCross and ps32, checkThing = PIT_CheckThing).
;
; Things and lines are handles, sectors bytes; every record comes through
; the object API (mo_get, ln_get, sec_get, bk_get, bl_get, mi_get). The
; places (checkpos.inc): tmthing, tmx, tmy, the box, spechit and MP_TRY
; are the shared GM_TM* of GW (request R1); tmfloorz, tmceilingz, tmdropoffz,
; numspechit are GM_* (geom's sectorFloor and baseLite write them first);
; ceilingline G_CEILLINE, MP_CLOB G_MPCLOB, the line record G_LROK, G_LRN,
; G_LRLINES (the globals block).
;
;   P_CheckPosition  GA_0-1 the thing, GA_2-5 x, GA_6-9 y: cpCopy, MP_TRY
;                    0, checkPos. A = 1 when the thing fits there, else 0
;   cpCopy           tmthing = GA_0-1, tmx = GA_2-5, tmy = GA_6-9
;   checkPos         the check of tmthing at tmx, tmy (MP_TRY: P_TryMove's
;                    call when 1). C set and A = 1 when it fits, C clear
;                    and A = 0 when a thing or a line blocks it. setBox;
;                    MP_CLOB 0; with MP_TRY 0 the point's floor and ceiling
;                    (sectorFloor) first, with 1 after the things; baseLite
;                    (numspechit 0, validcount + 1, ceilingline none);
;                    MF_NOCLIP: no walk (LR_OK 0); the things of the blocks
;                    of the box grown by 32 units, x outer and y inner, each
;                    block's list from its first; then lineBlocks
;   setBox           GA_0-1 the thing (tmthing): MP_TMF (missile, picks
;                    up), MP_RAD (its radius), the box: tmx, tmy -/+ the
;                    radius (the low words tmx's and tmy's)
;   walkRange        A = d (whole units): the blocks of the box grown by d,
;                    clamped to the map: CP_BX (xl), CP_XH, CP_YL, CP_YH; C
;                    set when there are none. The block of an edge is bits
;                    7-14 of the 16-bit (edge >> 16) - org +- d, negative
;                    below the map
;   lineBlocks       PIT_CheckLine over the lines of the blocks of the box,
;                    x outer and y inner, each block's list after its first
;                    entry to a negative one; validcount stamps; the box
;                    tests in whole units; a slanted line through
;                    P_BoxOnLineSide (geom); a crossed line recorded
;                    (LR_LINES 2 x the line, LR_N 2 x the count, $FF when
;                    more than 24: lCross), then blocking (one-sided, or
;                    ML_BLOCKING or ML_BLOCKMONSTERS for a monster, unless
;                    tmthing is a missile: C clear, the record's LR_OK
;                    left), else its front then back sector lower
;                    tmceilingz (ceilingline the line), raise tmfloorz,
;                    lower tmdropoffz (ps32), and a special line joins
;                    spechit (4 at most). The walk's end: LR_OK 1, or 0
;                    when LR_N is $FF; no blocks: LR_OK 0. C set: no line
;                    blocks
;   checkThing       PIT_CheckThing(GA_0-1, tmthing) for a thing that
;                    touches tmthing's box: a missile flies over or under
;                    it, passes its shooter, explodes on the shooter's
;                    species (but players), hurts a shootable thing
;                    ((P_Random () % 8 + 1) x its damage: P_DamageMobj)
;                    and blocks; else a special thing is picked up
;                    (P_TouchSpecialThing) when tmthing picks up, and a
;                    solid thing blocks. C set and A = 1: it does not block
;
; Upstream's helpers above (geom's P_BoxOnLineSide has it inline), setBoxL
; (a JSL wrapper: FCALL setBox), lCross, ps32 and loadRad have no code of
; their own: their work is done in place (request R4).
;
; A routine changes A, X, Y, GA_*, GT_*, the math block, the API's
; temporaries and what its callees change (sectorFloor, baseLite,
; P_BoxOnLineSide, P_DamageMobj, P_TouchSpecialThing).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/checkpos/checkpos.inc"

        .export P_CheckPosition, checkPos, setBox, checkThing, lineBlocks
        .export walkRange, cpCopy
        .export CP_TMTHING, CP_TMX, CP_TMY, CP_TMBBOX, CP_SPECHIT, CP_TRY
        .import mo_get, ln_get, ln_dirty, sec_get, bk_get, bl_get, mi_get
        .import g_random, mul8, umul16lo, fc_call, fc_unbuilt

; ROWBASE: CP_ROW = CP_YL x the map's width (both below 256)
.macro ROWBASE
        lda CP_YL
        ldy G_BMW
        jsr mul8
        lda M_R
        sta CP_ROW
        lda M_R+1
        sta CP_ROW+1
.endmacro

; COLUMN: a column's first block: CP_BY = CP_YL, CP_IDX = CP_ROW + CP_BX
.macro COLUMN
        lda CP_YL
        sta CP_BY
        clc
        lda CP_ROW
        adc CP_BX
        sta CP_IDX
        lda CP_ROW+1
        adc #0
        sta CP_IDX+1
.endmacro

; NEXTBLOCK nextcol, done: the next block of the column (y inner), or the
; next column (x outer), or `done` after the last
.macro NEXTBLOCK col, done
        lda CP_BY
        cmp CP_YH
        beq :+
        inc CP_BY
        clc
        lda CP_IDX
        adc G_BMW
        sta CP_IDX
        lda CP_IDX+1
        adc G_BMW+1
        sta CP_IDX+1
        bra :++
:       lda CP_BX
        cmp CP_XH
        jeq done
        inc CP_BX
        jmp col
:
.endmacro

; ===========================================================================
; P_CheckPosition, cpCopy
; ===========================================================================
        ROUTINE P_CheckPosition
        FCALL cpCopy
        stz CP_TRY                      ; (not from P_TryMove)
        FCALL checkPos
        lda #0
        rol a
        rts

        ROUTINE cpCopy
        lda GA_0                        ; tmthing
        sta CP_TMTHING
        lda GA_1
        sta CP_TMTHING+1
        ldx #3                          ; tmx, tmy
:       lda GA_2,x
        sta CP_TMX,x
        lda GA_6,x
        sta CP_TMY,x
        dex
        bpl :-
        rts

; ===========================================================================
; setBox
; ===========================================================================
        ROUTINE setBox
        lda GA_0
        ldx GA_1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2        ; MP_TMF: bit 7 a missile (C), bit 2
        lda (GC_MP),y                   ;   it picks up
        lsr a
        ldy #LN_B + MB_FLAGS + 1
        lda (GC_MP),y
        and #>UC_MF_PICKUP_LO
        ror a
        sta CP_TMF
        ldy #LN_B + MB_RADIUS + 2       ; MP_RAD: the radius (whole units
        lda (GC_MP),y                   ;   below 256)
        sta CP_RAD
        lda CP_TMY                      ; the low words: tmy's, tmx's
        sta BOXT
        sta BOXB
        lda CP_TMY+1
        sta BOXT+1
        sta BOXB+1
        lda CP_TMX
        sta BOXR
        sta BOXL
        lda CP_TMX+1
        sta BOXR+1
        sta BOXL+1
        clc                             ; top = y + radius
        lda CP_TMY+2
        adc CP_RAD
        sta BOXT+2
        lda CP_TMY+3
        adc #0
        sta BOXT+3
        sec                             ; bottom = y - radius
        lda CP_TMY+2
        sbc CP_RAD
        sta BOXB+2
        lda CP_TMY+3
        sbc #0
        sta BOXB+3
        clc                             ; right = x + radius
        lda CP_TMX+2
        adc CP_RAD
        sta BOXR+2
        lda CP_TMX+3
        adc #0
        sta BOXR+3
        sec                             ; left = x - radius
        lda CP_TMX+2
        sbc CP_RAD
        sta BOXL+2
        lda CP_TMX+3
        sbc #0
        sta BOXL+3
        rts

; ===========================================================================
; walkRange
; ===========================================================================
        ROUTINE walkRange
        sta GT_0                        ; d
        clc                             ; xh = (right.hi + d - orgx) >> 7:
        lda BOXR+2                      ;   left of the map: none; clamped
        adc GT_0                        ;   to width - 1
        tax
        lda BOXR+3
        adc #0
        tay
        sec
        txa
        sbc G_BMORGX+2
        tax
        tya
        sbc G_BMORGX+3
        jsr @blk7
        jcs @none
        cmp G_BMW
        bcc :+
        lda G_BMW
        dec a
:       sta CP_XH
        sec                             ; xl = (left.hi - d - orgx) >> 7:
        lda BOXL+2                      ;   negative: 0; right of the map:
        sbc GT_0                        ;   none
        tax
        lda BOXL+3
        sbc #0
        tay
        sec
        txa
        sbc G_BMORGX+2
        tax
        tya
        sbc G_BMORGX+3
        jsr @blk7
        bcc :+
        lda #0
:       cmp G_BMW
        bcs @none
        sta CP_BX
        clc                             ; yh: top, orgy, height
        lda BOXT+2
        adc GT_0
        tax
        lda BOXT+3
        adc #0
        tay
        sec
        txa
        sbc G_BMORGY+2
        tax
        tya
        sbc G_BMORGY+3
        jsr @blk7
        bcs @none
        cmp G_BMH
        bcc :+
        lda G_BMH
        dec a
:       sta CP_YH
        sec                             ; yl: bottom
        lda BOXB+2
        sbc GT_0
        tax
        lda BOXB+3
        sbc #0
        tay
        sec
        txa
        sbc G_BMORGY+2
        tax
        tya
        sbc G_BMORGY+3
        jsr @blk7
        bcc :+
        lda #0
:       cmp G_BMH
        bcs @none
        sta CP_YL
        clc
        rts
@none:  sec
        rts
; @blk7: A = bits 7-14 of the word A:X (A its high byte), C = its bit 15
@blk7:  stx GT_1
        asl GT_1
        rol a
        rts

; ===========================================================================
; checkPos
; ===========================================================================
        ROUTINE checkPos
        lda CP_TMTHING                  ; the box (the thing is tmthing)
        sta GA_0
        lda CP_TMTHING+1
        sta GA_1
        FCALL setBox
        lda G_MPCLOB                    ; MP_CLOB 0 (no game logic yet)
        ora G_MPCLOB+1
        beq :+
        stz G_MPCLOB
        stz G_MPCLOB+1
:       lda CP_TRY                      ; the point's floor and ceiling: for
        bne :+                          ;   P_TryMove after the things
        jsr cp_floor
:       FCALL baseLite                  ; no lines yet
        lda CP_TMTHING                  ; MF_NOCLIP: no checks
        ldx CP_TMTHING+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 1
        lda (GC_MP),y
        and #>UC_MF_NOCLIP_LO
        beq @things
        stz G_LROK                      ; (no record)
        lda CP_TRY
        beq :+
        jsr cp_floor
:       sec
        lda #1
        rts

        ; the things of the blocks of the box grown by MAXRADIUS (32)
@things:
        lda #$FF                        ; no radius yet
        sta CP_PR
        lda #32
        FCALL walkRange
        jcs @tdone
        ROWBASE
@tcol:  COLUMN
@tblk:  lda CP_IDX                      ; the block's first thing
        ldx CP_IDX+1
        jsr bk_get
@thing: cpx #$FF                        ; none: the next block
        jeq @tnextblk
        sta CP_TH
        stx CP_TH+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS            ; neither solid, special nor
        lda (GC_MP),y                   ;   shootable: no
        and #<(UC_MF_SOLID_LO | UC_MF_SPECIAL_LO | UC_MF_SHOOTABLE_LO)
        jeq @tnext
        ldy #LN_B + MB_RADIUS + 2       ; the radii, when this one is new
        lda (GC_MP),y
        cmp CP_PR
        beq @rs
        sta CP_PR
        clc
        adc CP_RAD
        sta CP_RS
        lda #0
        adc #0
        sta CP_RS+1
        lda CP_RS
        asl a
        sta CP_RS2
        lda CP_RS+1
        rol a
        sta CP_RS2+1
@rs:    lda CP_TH                       ; tmthing: no
        cmp CP_TMTHING
        bne :+
        lda CP_TH+1
        cmp CP_TMTHING+1
        jeq @tnext
:       ldy #TH_X + 2                   ; x: whole units settle all but the
        jsr @delta                      ;   two fractional boundaries
        beq @edgex
        lda GT_0                        ; inside: below 2 r
        cmp CP_RS2
        lda GT_1
        sbc CP_RS2+1
        bcc @inx
        lda GT_0                        ; past 2 r: no
        cmp CP_RS2
        jne @tnext
        lda GT_1
        cmp CP_RS2+1
        jne @tnext
        ldy #TH_X                       ; +r: in when the fraction is below
        lda (GC_MP),y                   ;   tmx's
        cmp CP_TMX
        iny
        lda (GC_MP),y
        sbc CP_TMX+1
        jcs @tnext
        bra @inx
@edgex: ldy #TH_X                       ; -r: in when the fraction is above
        lda CP_TMX                      ;   tmx's
        cmp (GC_MP),y
        iny
        lda CP_TMX+1
        sbc (GC_MP),y
        jcs @tnext
        lda CP_RS2                      ; zero radii never overlap
        ora CP_RS2+1
        jeq @tnext
@inx:   ldy #TH_Y + 2                   ; y, the same
        jsr @delta
        beq @edgey
        lda GT_0
        cmp CP_RS2
        lda GT_1
        sbc CP_RS2+1
        bcc @check
        lda GT_0
        cmp CP_RS2
        jne @tnext
        lda GT_1
        cmp CP_RS2+1
        jne @tnext
        ldy #TH_Y
        lda (GC_MP),y
        cmp CP_TMY
        iny
        lda (GC_MP),y
        sbc CP_TMY+1
        jcs @tnext
        bra @check
@edgey: ldy #TH_Y
        lda CP_TMY
        cmp (GC_MP),y
        iny
        lda CP_TMY+1
        sbc (GC_MP),y
        jcs @tnext
        lda CP_RS2
        ora CP_RS2+1
        jeq @tnext

        ; the rest of PIT_CheckThing: no game logic when tmthing is no
        ; missile and picks nothing up here: a solid thing blocks
@check: bit CP_TMF
        bmi @call                       ; a missile
        lda CP_TMF
        beq @solid                      ; picks up: a special thing
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SPECIAL_LO
        bne @call
@solid: ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_SOLID_LO
        jne @false
        jmp @tnext
@call:  ldx #0                          ; checkThing, which can run game
:       lda CP_BX,x                     ;   logic: the walk on the stack
        pha
        inx
        cpx #CP_WALK
        bne :-
        lda CP_TH
        sta GA_0
        lda CP_TH+1
        sta GA_1
        FCALL checkThing
        pha                             ; (the result)
        lda #1                          ; game logic ran: tmthing, tmx, tmy
        sta G_MPCLOB                    ;   and the box can differ
        lda CP_TMTHING                  ; loadRad: tmthing's radius again,
        ldx CP_TMTHING+1                ;   and the radii
        jsr mo_get
        ldy #LN_B + MB_RADIUS + 2
        lda (GC_MP),y
        sta CP_RAD
        lda #$FF
        sta CP_PR
        pla
        sta GT_0
        ldx #CP_WALK - 1
:       pla
        sta CP_BX,x
        dex
        bpl :-
        lda GT_0
        jeq @false
        lda CP_TH                       ; its next
        ldx CP_TH+1
        jsr mo_get
@tnext: ldy #LN_A + MA_BNEXT + 1        ; the thing's next in the block
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jmp @thing
@tnextblk:
        NEXTBLOCK @tcol, @tdone
        jmp @tblk
@false: clc
        lda #0
        rts

        ; the lines; the point's sector of P_TryMove first
@tdone: lda CP_TRY
        beq :+
        jsr cp_floor
:       lda CP_TMTHING                  ; MP_MISSILE: tmthing is a missile
        ldx CP_TMTHING+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 2
        lda (GC_MP),y
        and #<UC_MF_MISSILE_HI
        sta CP_MISS
        ldy #0                          ; MP_PLAYER: it is the player's
        lda CP_TMTHING
        cmp G_PLAYER + PL_MO
        bne :+
        lda CP_TMTHING+1
        cmp G_PLAYER + PL_MO + 1
        bne :+
        iny
:       sty CP_PLAY
        FCALL lineBlocks
        bcc @false
        lda #1
        rts

; @delta: GT_0..1 = the thing's (GC_MP) whole units at Y - tmthing's (tmx
; or tmy: the same offset from CP_TMX) + the radii; Z when 0
@delta: sec
        lda (GC_MP),y
        sbc CP_TMX - TH_X,y
        sta GT_0
        iny
        lda (GC_MP),y
        sbc CP_TMX - TH_X,y
        sta GT_1
        clc
        lda GT_0
        adc CP_RS
        sta GT_0
        lda GT_1
        adc CP_RS+1
        sta GT_1
        ora GT_0
        rts
        .assert CP_TMY - CP_TMX = TH_Y - TH_X, error, "tmx, tmy as x, y"

; cp_floor: sectorFloor at tmx, tmy (tmfloorz, tmceilingz, tmdropoffz; MV_SS,
; MV_SEC)
cp_floor:
        ldx #3
:       lda CP_TMX,x
        sta GA_X,x
        lda CP_TMY,x
        sta GA_Y,x
        dex
        bpl :-
        FCALL sectorFloor
        rts

; ===========================================================================
; lineBlocks (PIT_CheckLine: MP_MODE 0; the PIT_GetSectors mode is the
; game core's, gpos.s gp_secnodes)
; ===========================================================================
        ROUTINE lineBlocks
        stz G_LRN                       ; a new record
        lda BOXR                        ; the box in whole units: right and
        ora BOXR+1                      ;   top less 1 when their low word
        cmp #1                          ;   is 0; an edge of -32768.0: the
        lda BOXR+2                      ;   bottom 32767 then takes every
        sbc #0                          ;   line out
        sta CP_RF
        lda BOXR+3
        sbc #0
        sta CP_RF+1
        bvs @flip
        lda BOXT
        ora BOXT+1
        cmp #1
        lda BOXT+2
        sbc #0
        sta CP_TF
        lda BOXT+3
        sbc #0
        sta CP_TF+1
        bvs @flip
        lda BOXL+2
        sta CP_LH
        lda BOXL+3
        sta CP_LH+1
        lda BOXB+2
        sta CP_BH
        lda BOXB+3
        sta CP_BH+1
        bra @range
@flip:  lda #$FF
        sta CP_BH
        lda #$7F
        sta CP_BH+1
@range: lda #0
        FCALL walkRange
        bcc @walk
        stz G_LROK                      ; no blocks: no record
        sec
        lda #1
        rts
@walk:  ROWBASE
        stz CP_WIN
@lcol:  COLUMN
@lblk:  clc                             ; the block's list: the word at 4 +
        lda CP_IDX                      ;   the block, then its entries
        adc #4                          ;   after its first (a 0)
        sta CP_POS
        lda CP_IDX+1
        adc #0
        sta CP_POS+1
        jsr lb_word
        clc
        adc #1
        sta CP_POS
        txa
        adc #0
        sta CP_POS+1
@line:  jsr lb_word                     ; the line; negative: the end
        cpx #$80
        jcs @lnextblk
        sta CP_LN
        stx CP_LN+1
        jsr ln_get
        ldy #LN_VALID                   ; checked already: the next
        lda (GC_LP),y
        cmp G_VALID
        bne :+
        iny
        lda (GC_LP),y
        cmp G_VALID+1
        jeq @lnext
:       ldy #LN_VALID                   ; its stamp
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
        ldy #LN_TOP                     ; bottom >= bbox[top] << 16: out
        lda CP_BH
        cmp (GC_LP),y
        iny
        lda CP_BH+1
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       jpl @lnext
        ldy #LN_BOTTOM                  ; top <= bbox[bottom] << 16: out
        lda CP_TF
        cmp (GC_LP),y
        iny
        lda CP_TF+1
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       jmi @lnext
        ldy #LN_LEFT                    ; right <= bbox[left] << 16: out
        lda CP_RF
        cmp (GC_LP),y
        iny
        lda CP_RF+1
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       jmi @lnext
        ldy #LN_RIGHT                   ; left >= bbox[right] << 16: out
        lda CP_LH
        cmp (GC_LP),y
        iny
        lda CP_LH+1
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       jpl @lnext
        ldy #LN_SLOPE                   ; slanted: its corners on one side:
        lda (GC_LP),y                   ;   out (P_BoxOnLineSide)
        cmp #U_ST_POSITIVE
        bcc @cross
        ldx #15
:       lda CP_TMBBOX,x
        sta GA_0,x
        dex
        bpl :-
        lda CP_LN
        ldx CP_LN+1
        FCALL P_BoxOnLineSide
        cmp #$FF
        jne @lnext
        lda CP_LN                       ; (the line's record again)
        ldx CP_LN+1
        jsr ln_get

        ; lCross: the record (2 x the line; LR_N $FF: too many)
@cross: ldx G_LRN
        cpx #2 * LR_MAX
        bcs @many
        lda CP_LN
        asl a
        sta G_LRLINES,x
        lda CP_LN+1
        rol a
        sta G_LRLINES+1,x
        inx
        inx
        stx G_LRN
        bra @pit
@many:  lda #$FF
        sta G_LRN
        ; PIT_CheckLine: a one-sided line blocks; a blocking line blocks
        ; all but missiles, a monster-blocking one all but missiles and
        ; the player
@pit:   ldy #LN_SIDE1                   ; one sided: side 1 none
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        beq @block
        lda CP_MISS
        bne @secs
        ldy #LN_FLAGS
        lda (GC_LP),y
        bit #<UC_ML_BLOCKING
        bne @block
        and #<UC_ML_BLOCKMONSTERS
        beq @secs
        lda CP_PLAY
        bne @secs
@block: clc                             ; the line blocks the move
        lda #0
        rts
        ; its front, then its back sector if it is another one: a lower
        ; ceiling lowers tmceilingz (ceilingline the line), a higher floor
        ; raises tmfloorz, a lower floor lowers tmdropoffz
@secs:  ldy #LINE_SIZE                  ; (ln_get's two sectors after the
        lda (GC_LP),y                   ;   record)
        sta CP_SEC
        iny
        lda (GC_LP),y
        sta CP_SEC2
        lda CP_SEC
@sec:   jsr sec_get
        ldy #SEC_CEIL                   ; ceiling < tmceilingz
        lda (GC_SP),y
        cmp GM_TMCEILZ
        iny
        lda (GC_SP),y
        sbc GM_TMCEILZ+1
        iny
        lda (GC_SP),y
        sbc GM_TMCEILZ+2
        iny
        lda (GC_SP),y
        sbc GM_TMCEILZ+3
        bvc :+
        eor #$80
:       bpl @floor
        ldx #3
:       lda (GC_SP),y
        sta GM_TMCEILZ,x
        dey
        dex
        bpl :-
        lda CP_LN
        sta G_CEILLINE
        lda CP_LN+1
        sta G_CEILLINE+1
@floor: ldy #SEC_FLOOR                  ; floor > tmfloorz
        lda GM_TMFLOORZ
        cmp (GC_SP),y
        iny
        lda GM_TMFLOORZ+1
        sbc (GC_SP),y
        iny
        lda GM_TMFLOORZ+2
        sbc (GC_SP),y
        iny
        lda GM_TMFLOORZ+3
        sbc (GC_SP),y
        bvc :+
        eor #$80
:       bpl @drop
        ldx #3
:       lda (GC_SP),y
        sta GM_TMFLOORZ,x
        dey
        dex
        bpl :-
@drop:  ldy #SEC_FLOOR                  ; floor < tmdropoffz
        lda (GC_SP),y
        cmp GM_TMDROPZ
        iny
        lda (GC_SP),y
        sbc GM_TMDROPZ+1
        iny
        lda (GC_SP),y
        sbc GM_TMDROPZ+2
        iny
        lda (GC_SP),y
        sbc GM_TMDROPZ+3
        bvc :+
        eor #$80
:       bpl @other
        ldx #3
:       lda (GC_SP),y
        sta GM_TMDROPZ,x
        dey
        dex
        bpl :-
@other: lda CP_SEC                      ; then the back sector (a line with
        cmp CP_SEC2                     ;   one sector: once)
        beq @spec
        lda CP_SEC2
        sta CP_SEC
        jmp @sec
@spec:  ldy #LN_SPECIAL                 ; a special line: spechit (4 at
        lda (GC_LP),y                   ;   most)
        beq @lnext
        lda GM_NSPEC
        cmp #4
        bcs @lnext
        asl a
        tax
        lda CP_LN
        sta CP_SPECHIT,x
        lda CP_LN+1
        sta CP_SPECHIT+1,x
        inc GM_NSPEC
@lnext: inc CP_POS                      ; the list's next entry
        jne @line
        inc CP_POS+1
        jmp @line
@lnextblk:
        NEXTBLOCK @lcol, @lend
        jmp @lblk
@lend:  ldx #1                          ; the walk's end: its record (LR_N
        lda G_LRN                       ;   $FF: too many lines)
        cmp #$FF
        bne :+
        dex
:       stx G_LROK
        sec
        lda #1
        rts
        .assert SEC_FLOOR = 0, error, "the floor first"

; lb_word: A:X = the blockmap's word CP_POS, through the window of BL_BUF
; (128 words from CP_WB; bl_get when CP_POS is outside it)
lb_word:
        lda CP_WIN
        beq @fetch
        sec
        lda CP_POS
        sbc CP_WB
        tay
        lda CP_POS+1
        sbc CP_WB+1
        bne @fetch
        cpy #128
        bcs @fetch
        tya
        asl a
        tay
        bra @read
@fetch: lda CP_POS
        sta CP_WB
        ldx CP_POS+1
        stx CP_WB+1
        jsr bl_get
        lda #1
        sta CP_WIN
        ldy #0
@read:  lda BL_BUF+1,y
        tax
        lda BL_BUF,y
        rts

; ===========================================================================
; checkThing (PIT_CheckThing)
; ===========================================================================
        ROUTINE checkThing
        lda CP_TMTHING                  ; tmthing's line: GT_4..5
        ldx CP_TMTHING+1
        jsr mo_get
        lda GC_MP
        sta GT_4
        lda GC_MP+1
        sta GT_5
        ldy #LN_B + MB_FLAGS + 2        ; tmthing is a missile
        lda (GT_4),y
        and #<UC_MF_MISSILE_HI
        bne @missile
        ldy #LN_B + MB_FLAGS + 1        ; it picks up: GT_6
        lda (GT_4),y
        and #>UC_MF_PICKUP_LO
        sta GT_6
        lda GA_0                        ; the thing's flags (before the
        ldx GA_1                        ;   pickup, which can remove it)
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        bit #<UC_MF_SPECIAL_LO          ; a special thing: picked up
        beq @solid
        pha
        lda GT_6
        beq :+
        lda CP_TMTHING                  ; P_TouchSpecialThing(thing,
        sta GA_2                        ;   tmthing)
        lda CP_TMTHING+1
        sta GA_3
        FCALL P_TouchSpecialThing
:       pla
@solid: and #<UC_MF_SOLID_LO            ; !(flags & MF_SOLID)
        beq @true
@no:    clc
        lda #0
        rts
@true:  sec
        lda #1
        rts

        ; a missile: over the thing (thing->z + height < tmthing->z), or
        ; under it (tmthing->z + height < thing->z): true
@missile:
        lda GA_0
        ldx GA_1
        jsr mo_get
        clc                             ; GT_0..3 = thing->z + height
.repeat 4, k
        ldy #TH_Z + k
        lda (GC_MP),y
        ldy #LN_B + MB_HEIGHT + k
        adc (GC_MP),y
        sta GT_0 + k
.endrepeat
        ldy #TH_Z                       ; < tmthing->z
        sec
        lda GT_0
        sbc (GT_4),y
.repeat 3, k
        iny
        lda GT_1 + k
        sbc (GT_4),y
.endrepeat
        bvc :+
        eor #$80
:       bmi @true
        clc                             ; GT_0..3 = tmthing->z + height
.repeat 4, k
        ldy #TH_Z + k
        lda (GT_4),y
        ldy #LN_B + MB_HEIGHT + k
        adc (GT_4),y
        sta GT_0 + k
.endrepeat
        ldy #TH_Z                       ; < thing->z
        sec
        lda GT_0
        sbc (GC_MP),y
.repeat 3, k
        iny
        lda GT_1 + k
        sbc (GC_MP),y
.endrepeat
        bvc :+
        eor #$80
:       jmi @true
        lda GC_MP                       ; the thing's line: GT_0..1
        sta GT_0
        lda GC_MP+1
        sta GT_1
        ; the same species as the shooter (tmthing->target): the shooter
        ; itself passes, others explode with no damage, but players hurt
        ; players
        ldy #LN_A + MA_TARGET + 1
        lda (GT_4),y
        cmp #$FF
        beq @shoot                      ; no target
        tax
        dey
        lda (GT_4),y
        sta GT_2
        stx GT_3
        jsr mo_get
        ldy #LN_A + MA_TYPE
        lda (GC_MP),y
        cmp (GT_0),y
        bne @shoot                      ; another species
        lda GA_0                        ; the shooter itself: true
        cmp GT_2
        bne :+
        lda GA_1
        cmp GT_3
        jeq @true
:       lda (GT_0),y                    ; not a player: explodes, no damage
        cmp #UC_MT_PLAYER
        jne @no
@shoot: ldy #LN_B + MB_FLAGS            ; not shootable: !(flags & MF_SOLID)
        lda (GT_0),y
        bit #<UC_MF_SHOOTABLE_LO
        jeq @solid
        ; damage = (P_Random () % 8 + 1) x mobjinfo[tmthing->type].damage
        ; (the low word: IIGS_MulLo16); P_DamageMobj(thing, tmthing,
        ; tmthing->target, damage); false
        ldy #LN_A + MA_TYPE
        lda (GT_4),y
        ldy #UO_MI_DAMAGE
        jsr mi_get
        sta M_B
        stx M_B+1
        jsr g_random
        and #7
        inc a
        sta M_A
        stz M_A+1
        jsr umul16lo
        lda M_R
        sta GA_6
        lda M_R+1
        sta GA_7
        ldy #LN_A + MA_TARGET
        lda (GT_4),y
        sta GA_4
        iny
        lda (GT_4),y
        sta GA_5
        lda CP_TMTHING
        sta GA_2
        lda CP_TMTHING+1
        sta GA_3
        FCALL P_DamageMobj              ; (GA_0..1: the thing)
        clc
        lda #0
        rts
