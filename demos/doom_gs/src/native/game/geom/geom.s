; game/geom/geom.s: part geom of the game (docs/GAME.md, the parts):
; the side tests, the openings, the point's sector and the box's blocks. A
; GPL-2 derivative of upstream's p_map65.s (P_PointOnLineSide with
; pointOnLineSide and posMul, P_BoxOnLineSide with boxOnLineSide, above,
; vertical, slanted, box1, box2, P_LineOpening, P_LineOpeningXY with openXY,
; pointSector, sectorFloor, baseFloor, baseFloorL, baseLite, blockRange).
; The iterators are giter.s.
;
; Lines and sectors are handles (a line 16 bits, a sector a byte); every
; record comes through the object API (ln_get, sec_get, ss_get); the
; results upstream leaves in its near scratch are in the scratch block
; (geom.inc). A routine changes A, X, Y, GT_*, the math's block, the API's
; temporaries and, for the ones that call R_PointInSubsector or validcount,
; what those change (gpos.s gp_pointsub, gvalid.s gv_inc); GA_* are never
; written here, so a caller's arguments survive (P_BoxOnLineSide relies on
; it for P_PointOnLineSide).
;
;   P_PointOnLineSide  A = the side (0 or 1) of the point GA_X, GA_Y
;                      (fixed_t) to line A:X: when dx is 0, x <= v1.x << 16
;                      ? dy > 0 : dy < 0; when dy is 0, y <= v1.y << 16 ? dx
;                      < 0 : dx > 0; else 1 when L >= R (signed 32 bits), L
;                      and R the low 32 bits of ((y - (v1.y << 16)) >> 8) dx
;                      and of ((x - (v1.x << 16)) >> 8) dy (posMul)
;   posMul             M_R = the low 32 bits of V F: V the signed 24-bit
;                      M_A..M_A+2, F the signed 16-bit M_B..M_B+1 (upstream's
;                      posMul: V.lo F + (V.hi F) << 16, as _Mul32 gives it:
;                      math.s's mul32). Changes M_A+3, M_B+2..3 and
;                      what mul32 changes
;   P_BoxOnLineSide    A = the side of the box GA_0..GA_15 (top, bottom,
;                      left, right: geom.inc) to line A:X: 0, 1, or $FF when
;                      the box crosses it. Horizontal: (bottom > v1.y << 16)
;                      == (p = top > v1.y << 16) ? p ^ (dx < 0) : -1;
;                      vertical: (left < v1.x << 16) == (p = right < v1.x <<
;                      16) ? p ^ (dy < 0) : -1; positive: side(right, bottom)
;                      == (p = side(left, top)) ? p : -1; negative:
;                      side(left, bottom) == (p = side(right, top)) ? p : -1
;   P_LineOpening      the opening of line A:X: one-sided (no side 1):
;                      openrange 0 and nothing else; else P_LineOpeningXY of
;                      its back and front sectors
;   P_LineOpeningXY    the opening of sectors A (upstream's X) and X
;                      (upstream's Y): openbottom the higher floor (A's when
;                      they are the same), opentop the lower ceiling (the
;                      other's when they are the same), openrange their
;                      difference. Upstream keeps no lowfloor (its
;                      _g_lowfloor is "not stored: no code reads it",
;                      p_map65.s:298)
;   pointSector        A = GEO_SEC = the sector of GEO_SS =
;                      R_PointInSubsector(GA_X, GA_Y) (gp_pointsub)
;   sectorFloor        pointSector, then tmfloorz = tmdropoffz = its floor,
;                      tmceilingz = its ceiling
;   baseLite           numspechit 0, validcount + 1 (gv_inc), ceilingline
;                      none
;   baseFloor          sectorFloor, then baseLite
;   baseFloorL         baseFloor (upstream's JSL entry)
;   blockRange         the blocks of the box GA_0..GA_15 grown by the whole
;                      units GA_16..GA_17 on each side, clamped to the map:
;                      GEO_BXL .. GEO_BYH; C set when there are none (then
;                      the four are not read: P_TeleportMove,
;                      p_map65.s:3450-3462)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/geom/geom.inc"

        .export P_PointOnLineSide, posMul, P_BoxOnLineSide, P_LineOpening
        .export P_LineOpeningXY, pointSector, sectorFloor, baseLite
        .export baseFloor, baseFloorL, blockRange
        ; the results (geom.inc), for the later parts that read them
        .export GEO_OPENTOP, GEO_OPENBOT, GEO_OPENRANGE, GEO_TMFLOORZ
        .export GEO_TMCEILZ, GEO_TMDROPZ, GEO_SS, GEO_SEC, GEO_NSPEC
        .export GEO_BXL, GEO_BXH, GEO_BYL, GEO_BYH
        .import ln_get, sec_get, ss_get, mul32, mul8, gv_inc, gp_pointsub
        .import fc_call, fc_unbuilt

; ===========================================================================
; P_PointOnLineSide
; ===========================================================================
        ROUTINE P_PointOnLineSide
        jsr ln_get                      ; GC_LP: the line's record
        ldy #LN_DX
        lda (GC_LP),y
        iny
        ora (GC_LP),y
        jeq @dx0
        ldy #LN_DY
        lda (GC_LP),y
        iny
        ora (GC_LP),y
        jeq @dy0
        ; L = ((y - (v1.y << 16)) >> 8) dx: the operand is the difference's
        ; bytes 1-3 (its low word's byte 1 is y's: v1.y << 16 has none)
        lda GA_Y+1
        sta M_A
        ldy #LN_V1Y
        sec
        lda GA_Y+2
        sbc (GC_LP),y
        sta M_A+1
        iny
        lda GA_Y+3
        sbc (GC_LP),y
        sta M_A+2
        ldy #LN_DX
        lda (GC_LP),y
        sta M_B
        iny
        lda (GC_LP),y
        sta M_B+1
        FCALL posMul
        ldx #3                          ; (GC_LP stays: no line got since)
:       lda M_R,x
        sta GT_0,x
        dex
        bpl :-
        ; R = ((x - (v1.x << 16)) >> 8) dy
        lda GA_X+1
        sta M_A
        ldy #LN_V1X
        sec
        lda GA_X+2
        sbc (GC_LP),y
        sta M_A+1
        iny
        lda GA_X+3
        sbc (GC_LP),y
        sta M_A+2
        ldy #LN_DY
        lda (GC_LP),y
        sta M_B
        iny
        lda (GC_LP),y
        sta M_B+1
        FCALL posMul
        sec                             ; L - R: its sign (the 33-bit
        lda GT_0                        ;   difference's): 1 unless L < R
        sbc M_R
        lda GT_1
        sbc M_R+1
        lda GT_2
        sbc M_R+2
        lda GT_3
        sbc M_R+3
        bvc :+
        eor #$80
:       bmi @zero
@one:   lda #1
        rts
@zero:  lda #0
        rts
@dx0:   ldy #LN_V1X                     ; dx 0: x <= v1.x << 16 ? dy > 0 :
        sec                             ;   dy < 0
        lda GA_X+2
        sbc (GC_LP),y
        sta GT_0
        iny
        lda GA_X+3
        sbc (GC_LP),y
        sta GT_1
        bvc :+
        eor #$80
:       bmi @dypos                      ; x's whole part below: <=
        lda GT_0
        ora GT_1
        bne @dyneg                      ; above: >
        lda GA_X                        ; the same whole part: <= when the
        ora GA_X+1                      ;   fraction is 0
        bne @dyneg
@dypos: ldy #LN_DY+1                    ; dy > 0
        lda (GC_LP),y
        bmi @zero
        dey
        ora (GC_LP),y
        beq @zero
        bra @one
@dyneg: ldy #LN_DY+1                    ; dy < 0
        lda (GC_LP),y
        bmi @one
        bra @zero
@dy0:   ldy #LN_V1Y                     ; dy 0: y <= v1.y << 16 ? dx < 0 :
        sec                             ;   dx > 0
        lda GA_Y+2
        sbc (GC_LP),y
        sta GT_0
        iny
        lda GA_Y+3
        sbc (GC_LP),y
        sta GT_1
        bvc :+
        eor #$80
:       bmi @dxneg
        lda GT_0
        ora GT_1
        bne @dxpos
        lda GA_Y
        ora GA_Y+1
        bne @dxpos
@dxneg: ldy #LN_DX+1                    ; dx < 0
        lda (GC_LP),y
        bmi @one
        bra @zero
@dxpos: ldy #LN_DX+1                    ; dx > 0
        lda (GC_LP),y
        bmi @zero
        dey
        ora (GC_LP),y
        beq @zero
        bra @one

; ===========================================================================
; posMul: M_R = the low 32 bits of V (M_A, 24 bits) F (M_B, 16 bits)
; ===========================================================================
        ROUTINE posMul
        lda M_A+2                       ; the signs, extended
        jsr @sign
        sta M_A+3
        lda M_B+1
        jsr @sign
        sta M_B+2
        sta M_B+3
        jmp mul32
@sign:  asl a
        lda #0
        bcc :+
        lda #$FF
:       rts

; ===========================================================================
; P_BoxOnLineSide
; ===========================================================================
        ROUTINE P_BoxOnLineSide
        sta GT_5                        ; the line
        stx GT_6
        jsr ln_get
        ldy #LN_SLOPE
        lda (GC_LP),y
        cmp #UC_ST_POSITIVE
        jcs @slanted
        cmp #UC_ST_VERTICAL
        beq @vert
        ; horizontal (and any other slope type below ST_POSITIVE that is
        ; not vertical, as upstream's default)
        ldx #GEO_BOTTOM - GA_0          ; bottom above v1.y << 16?
        ldy #LN_V1Y
        jsr @above
        php
        ldx #GEO_TOP - GA_0             ; top above?
        ldy #LN_V1Y
        jsr @above
        lda #0
        rol a                           ; A = top above
        plp
        bcs :+
        cmp #0                          ; bottom not above: top not above,
        bne @cross                      ;   p = 0
        bra @hsign
:       cmp #1                          ; bottom above: top above, p = 1
        bne @cross
@hsign: ldy #LN_DX+1                    ; p ^ (dx < 0)
        bra @xsign
@vert:  ldx #GEO_LEFT - GA_0            ; left < v1.x << 16 (its whole part
        jsr @less                       ;   below v1.x)
        php
        ldx #GEO_RIGHT - GA_0
        jsr @less
        lda #0
        rol a                           ; A = right less
        plp
        bcs :+
        cmp #0                          ; left not less: right not less,
        bne @cross                      ;   p = 0
        bra @vsign
:       cmp #1                          ; left less: right less, p = 1
        bne @cross
@vsign: ldy #LN_DY+1                    ; p ^ (dy < 0)
@xsign: tax
        lda (GC_LP),y
        bpl :+
        txa
        eor #1
        rts
:       txa
        rts
@cross: lda #$FF
        rts

; @above: C = the fixed_t GA_0 + X > the line's whole units at Y << 16
@above: sec
        lda GA_0+2,x
        sbc (GC_LP),y
        sta GT_0
        iny
        lda GA_0+3,x
        sbc (GC_LP),y
        sta GT_1
        bvc :+
        eor #$80
:       bmi @no                         ; the whole part below
        lda GT_0
        ora GT_1
        bne @yes                        ; above
        lda GA_0,x                      ; the same: above when the fraction
        ora GA_0+1,x                    ;   is not 0
        bne @yes
@no:    clc
        rts
@yes:   sec
        rts

; @less: C = the fixed_t GA_0 + X < the line's v1.x << 16 (its whole part
; below v1.x)
@less:  ldy #LN_V1X
        lda GA_0+2,x
        cmp (GC_LP),y
        iny
        lda GA_0+3,x
        sbc (GC_LP),y
        bvc :+
        eor #$80
:       asl a                           ; C = the sign: below
        rts

        ; slanted: the two corners' sides through P_PointOnLineSide (GA_X,
        ; GA_Y: the box's top word and bottom word, so the top is kept on
        ; the stack; P_PointOnLineSide leaves GA_* as they are)
@slanted:
        lsr a                           ; C: negative
        lda GEO_TOP+3                   ; the top, kept
        pha
        lda GEO_TOP+2
        pha
        lda GEO_TOP+1
        pha
        lda GEO_TOP
        pha
        lda GT_6                        ; the line
        pha
        lda GT_5
        pha
        ldx #GEO_RIGHT - GA_0           ; positive: (right, bottom), then
        ldy #GEO_LEFT - GA_0            ;   (left, top); negative: (left,
        bcc :+                          ;   bottom), then (right, top)
        ldx #GEO_LEFT - GA_0
        ldy #GEO_RIGHT - GA_0
:       phy                             ; the second x
        jsr @xcorner                    ; GA_X = the first x (GA_Y: bottom)
        tsx
        lda $0102,x                     ; the line
        pha
        lda $0103,x
        tax
        pla
        FCALL P_PointOnLineSide
        sta GT_4                        ; the first side
        pla                             ; the second x
        tax
        jsr @xcorner
        pla                             ; the line
        sta GT_5
        pla
        sta GT_6
        ldx #0                          ; GA_Y = the top
:       pla
        sta GA_Y,x
        inx
        cpx #4
        bne :-
        lda GT_4
        pha
        lda GT_5
        ldx GT_6
        FCALL P_PointOnLineSide
        sta GT_4
        pla
        cmp GT_4
        jne @cross
        rts

; @xcorner: GA_X = the fixed_t GA_0 + X
@xcorner:
        ldy #0
:       lda GA_0,x
        sta GA_X,y
        inx
        iny
        cpy #4
        bne :-
        rts

; ===========================================================================
; P_LineOpening, P_LineOpeningXY
; ===========================================================================
        ROUTINE P_LineOpening
        jsr ln_get
        ldy #LN_SIDE1                   ; one-sided: openrange 0
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        bne @two
        stz GEO_OPENRANGE
        stz GEO_OPENRANGE+1
        stz GEO_OPENRANGE+2
        stz GEO_OPENRANGE+3
        rts
@two:   ldy #LINE_SIZE + 1              ; the back sector (upstream's X),
        lda (GC_LP),y                   ;   the front (Y): LVS's LNSECB,
        pha                             ;   LNSECF
        dey
        lda (GC_LP),y
        tax
        pla
        FCALL P_LineOpeningXY
        rts

        ROUTINE P_LineOpeningXY
        stx GT_6                        ; Y
        jsr sec_get                     ; X: its line (the four most recent
        lda GC_SP                       ;   lines stay: both pointers hold)
        sta GT_2
        lda GC_SP+1
        sta GT_3
        lda GT_6
        jsr sec_get
        lda GC_SP
        sta GT_4
        lda GC_SP+1
        sta GT_5
        ldy #SEC_FLOOR                  ; X = the higher floor: X's floor
        sec                             ;   below Y's: swap
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        bvc :+
        eor #$80
:       bpl @ceil
        ldx GT_2
        lda GT_4
        sta GT_2
        stx GT_4
        ldx GT_3
        lda GT_5
        sta GT_3
        stx GT_5
@ceil:  ldy #SEC_CEIL                   ; Y = the lower ceiling: X's ceiling
        sec                             ;   below Y's: Y = X
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        iny
        lda (GT_2),y
        sbc (GT_4),y
        bvc :+
        eor #$80
:       bpl @open
        lda GT_2
        sta GT_4
        lda GT_3
        sta GT_5
@open:  ldx #0                          ; opentop = Y's ceiling, openbottom
        sec                             ;   = X's floor, openrange = their
:       txa                             ;   difference
        clc
        adc #SEC_CEIL
        tay
        lda (GT_4),y
        sta GEO_OPENTOP,x
        txa                             ; (SEC_FLOOR + x)
        .assert SEC_FLOOR = 0, error, "the floor first"
        tay
        lda (GT_2),y
        sta GEO_OPENBOT,x
        inx
        cpx #4
        bne :-
        sec
        ldx #0
:       lda GEO_OPENTOP,x
        sbc GEO_OPENBOT,x
        sta GEO_OPENRANGE,x
        inx
        txa                             ; (no carry change: cpx would)
        eor #4
        bne :-
        rts

; ===========================================================================
; pointSector, sectorFloor, baseLite, baseFloor, baseFloorL
; ===========================================================================
        ROUTINE pointSector
        ldx #3
:       lda GA_X,x
        sta GC_X,x
        lda GA_Y,x
        sta GC_Y,x
        dex
        bpl :-
        jsr gp_pointsub                 ; R_PointInSubsector (gpos.s)
        lda GC_S
        sta GEO_SS
        ldx GC_S+1
        stx GEO_SS+1
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        sta GEO_SEC
        rts

        ROUTINE sectorFloor
        FCALL pointSector               ; (GA_X, GA_Y: the caller's)
        lda GEO_SEC
        jsr sec_get
        ldy #3
:       lda (GC_SP),y                   ; tmfloorz = tmdropoffz = the floor
        sta GEO_TMFLOORZ,y
        sta GEO_TMDROPZ,y
        dey
        bpl :-
        ldy #SEC_CEIL + 3               ; tmceilingz = the ceiling
        ldx #3
:       lda (GC_SP),y
        sta GEO_TMCEILZ,x
        dey
        dex
        bpl :-
        lda GEO_SEC
        rts
        .assert SEC_FLOOR = 0, error, "the floor first"

        ROUTINE baseLite
        stz GEO_NSPEC                   ; numspechit = 0
        jsr gv_inc                      ; validcount++
        lda #$FF                        ; ceilingline = none
        sta G_CEILLINE
        sta G_CEILLINE+1
        rts

        ROUTINE baseFloor
        FCALL sectorFloor
        FCALL baseLite
        rts

        ROUTINE baseFloorL
        FCALL baseFloor
        rts

; ===========================================================================
; blockRange
; ===========================================================================
        ROUTINE blockRange
        ; xl = max(0, ((left - orgx) >> 16) - d) >> 7)
        ldx #GEO_LEFT - GA_0
        ldy #G_BMORGX - G_BMORGX
        jsr @hiword
        sec
        txa
        sbc GA_16
        tax
        tya
        sbc GA_17
        jsr @shr7
        cpy #0
        beq :+
        lda #0
:       sta GEO_BXL
        ; xh = min(((right - orgx) >> 16) + d) >> 7, width - 1): its high
        ; byte in GT_0
        ldx #GEO_RIGHT - GA_0
        ldy #G_BMORGX - G_BMORGX
        jsr @hiword
        clc
        txa
        adc GA_16
        tax
        tya
        adc GA_17
        jsr @shr7
        ldx #G_BMW - G_BMW
        jsr @clamp
        sta GEO_BXH
        sty GT_0
        ; yl, yh the same with bottom, top, orgy, height: yh's high byte in
        ; GT_1
        ldx #GEO_BOTTOM - GA_0
        ldy #G_BMORGY - G_BMORGX
        jsr @hiword
        sec
        txa
        sbc GA_16
        tax
        tya
        sbc GA_17
        jsr @shr7
        cpy #0
        beq :+
        lda #0
:       sta GEO_BYL
        ldx #GEO_TOP - GA_0
        ldy #G_BMORGY - G_BMORGX
        jsr @hiword
        clc
        txa
        adc GA_16
        tax
        tya
        adc GA_17
        jsr @shr7
        ldx #G_BMH - G_BMW
        jsr @clamp
        sta GEO_BYH
        sty GT_1
        ; none when yh < yl or xh < xl (signed words; xl, yl from 0 to 255)
        lda GEO_BYH
        cmp GEO_BYL
        lda GT_1
        sbc #0
        bvc :+
        eor #$80
:       bmi @none
        lda GEO_BXH
        cmp GEO_BXL
        lda GT_0
        sbc #0
        bvc :+
        eor #$80
:       bmi @none
        clc
        rts
@none:  sec
        rts

; @hiword: Y:X (Y the high byte) = the high word of the fixed_t GA_0 + X
; less the fixed_t G_BMORGX + Y
@hiword:
        sec
        lda GA_0,x
        sbc G_BMORGX,y
        lda GA_0+1,x
        sbc G_BMORGX+1,y
        lda GA_0+2,x
        sbc G_BMORGX+2,y
        sta GT_2
        lda GA_0+3,x
        sbc G_BMORGX+3,y
        tay
        ldx GT_2
        rts

; @shr7: the word A:X (A the high byte) shifted right 7, arithmetic
; (upstream's SHR7): A its low byte, Y its high ($00 or $FF)
@shr7:  sta GT_2
        txa
        asl a
        lda GT_2
        rol a
        ldy #0
        bcc :+
        ldy #$FF
:       rts

; @clamp: Y:A = min(Y:A, G_BMW + X - 1) (signed words; G_BMW + X the width
; or the height)
@clamp: sta GT_2
        sty GT_3
        cmp G_BMW,x
        tya
        sbc G_BMW+1,x
        bvc :+
        eor #$80
:       bmi :+                          ; below: itself
        sec
        lda G_BMW,x
        sbc #1
        sta GT_2
        lda G_BMW+1,x
        sbc #0
        sta GT_3
:       lda GT_2
        ldy GT_3
        rts
