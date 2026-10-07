; game/sight/sight.s: P_CheckSight, part sight of the game's tic code
; (docs/GAME.md). GPL-2: rewritten from upstream's
; p_sight65.s (P_CheckSight:138, the walk of P_CrossBSPNode and
; P_CrossSubsector, nodeSide, lineSideS, sideTest, nodeDone, lineDone,
; straceDone, hintOf, half, qbd, bitTab), Doom8088: Apple IIgs Edition.
;
;   P_CheckSight    GA_0-1 t1, GA_2-3 t2 (mobj slots). Out: A = 1 seen, 0
;                   not (Z from A). Changes X, Y, GA_*, GT_*, the API's
;                   temporaries, the math block.
;
; As upstream, step by step:
;
;   the same pair as the last call (CS_PREV1, CS_PREV2: handles; $FFFE,
;   stale, names no slot): the last answer CS_PREVR, no validcount++ (with
;   TESTBUILD, which no build here defines, the hit goes to a hit log,
;   hl_add)
;   REJECT: the bit RJROW[t1's sector] + t2's sector of the map's REJECT
;   lump (LVG2 at G_REJECTAT), bit 0 the lowest (upstream's bitTab)
;   the same subsector: seen
;   else validcount++ (gvalid.s gv_inc), the line of sight (strace, t2x,
;   t2y, its box in whole units + $8000) and the walk: first the hint, the
;   line that stopped t1's last check: its sightline (one-sided) or the
;   hint plane by its slot (HINTL, HINTH, two-sided; upstream's SIGHTHINT
;   by address) when it is a line of the map, as a subsector of one
;   seg (the line's sectors from LVS through ln_get) while the tree waits;
;   then the tree from the root: at a node the sides of both ends, the
;   start's child first and the other one waiting on the stack when the
;   line of sight crosses it; at a subsector each seg's line, once a check
;   (its validcount stamp), its box against the line of sight's, a
;   two-sided line with the same floor and ceiling on both sides passes,
;   then the two side tests; a crossed one-sided line blocks
;   (sightblocker), a crossed two-sided one narrows the slopes
;   (p_sight_opening, zSetup the first time, interceptFrac, sightSlope)
;   and blocks when they close (TWOBLOCKER)
;   the end: CS_PREVR, t1's sightline = sightblocker, its hint =
;   TWOBLOCKER. A zone mobj as t1 raises GT_HINT (docs/GAME.md: upstream
;   keys its hint by the mobj's address)
;
; The side tests (P_DivlineSide) take the whole parts of the coordinates
; as 16-bit values with their wrap, as upstream's (p_sight65.s:620-650,
; 838-913), and compare the exact signed products QA QB and QC QD (sg_side:
; two umul16), where upstream first tries its log fast path (LOGTAB, the
; side test of p_sight65.s:695-702); the two agree. half and qbd are
; folded into sg_mag and the
; operands; nodeDone, lineDone and straceDone into the walk; hintOf is the
; slot itself.
;
; The walk's waiting children are on the stack, two bytes each (hi, lo),
; over the marker $7FFF; a block puts S back (SG_S0). E1's trees are at
; most 19 nodes deep: 40 bytes at most.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/sight/sight.inc"

        .export P_CheckSight
        .import mo_get, mo_dirty, ss_get, nd_get, sg_get, ln_get, ln_dirty
        .import sec_get, gv_inc, umul16, far_get, far_put
        .import hn_get, hn_put, rj_row, rj_byte
        .import zSetup, sightSlope, interceptFrac, p_sight_opening
        .import fc_call, fc_unbuilt
.ifdef TESTBUILD
        .import hl_add, smul48, mt_init
        .export sg_bulk, sg_timed
.endif

MARK_HI = $7F                   ; the walk's marker: no child waits
MARK_LO = $FF
LN_FS   = LINE_SIZE             ; a line cache line: the record, then its
LN_BS   = LINE_SIZE + 1         ;   front and back sectors (LVS)

; ===========================================================================
; P_CheckSight
; ===========================================================================
        ROUTINE P_CheckSight
        ldx #3
:       lda GA_0,x
        sta SG_T1,x
        dex
        bpl :-
        ; the same pair as the last call: its answer (p_sight65.s:138-147)
        ldx #3
@pair:  lda SG_T1,x
        cmp CS_PREV1,x
        bne @new
        dex
        bpl @pair
.ifdef TESTBUILD
        ldx #3                  ; the hit log: t1, t2 (GT_0-3)
:       lda SG_T1,x
        sta GT_0,x
        dex
        bpl :-
        jsr hl_add
.endif
        lda CS_PREVR
        rts
@new:   ldx #3                  ; the pair is kept (p_sight65.s:148-153)
:       lda SG_T1,x
        sta CS_PREV1,x
        dex
        bpl :-
        ; REJECT bit RJROW[t1's sector] + t2's sector (p_sight65.s:155-195)
        lda SG_T2
        ldx SG_T2+1
        jsr sub_sec             ; t2: SG_SEG its subsector, A its sector
        sta SG_BS
        lda SG_SEG
        sta SG_LINE             ; (t2's subsector)
        lda SG_SEG+1
        sta SG_LINE+1
        lda SG_T1
        ldx SG_T1+1
        jsr sub_sec             ; t1
        jsr rj_row              ; A:X = its REJECT row
        clc
        adc SG_BS
        sta GT_0                ; the bit
        txa
        adc #0
        sta GT_1
        lda GT_0
        and #7
        sta SG_S1               ; bit & 7
        lsr GT_1                ; its byte: bit >> 3
        ror GT_0
        lsr GT_1
        ror GT_0
        lsr GT_1
        ror GT_0
        lda GT_0
        ldx GT_1
        jsr rj_byte             ; A = the byte (REJECT, the object API)
        ldx SG_S1
        and bitTab,x
        beq @noreject
        stz CS_PREVR            ; cannot be connected
        lda #0
        rts
        ; the same subsector: seen
@noreject:
        lda SG_SEG
        cmp SG_LINE
        bne @walk
        lda SG_SEG+1
        cmp SG_LINE+1
        bne @walk
        lda #1
        sta CS_PREVR
        rts

@walk:  jsr gv_inc              ; validcount++
        lda SG_T1               ; t1 a zone mobj: its hint and sightline
        cmp G_POOLN             ;   are upstream's by address (GT_HINT,
        lda SG_T1+1             ;   docs/GAME.md)
        sbc G_POOLN+1
        bcc :+
        lda #1
        sta GT_HINT
        ; t2x, t2y, then strace.x, y: t1's
:       lda SG_T2
        ldx SG_T2+1
        jsr mo_get
        ldy #7
:       lda (GC_MP),y
        sta SG_EX,y
        dey
        bpl :-
        lda SG_T1
        ldx SG_T1+1
        jsr mo_get
        ldy #7
:       lda (GC_MP),y
        sta SG_SX,y
        dey
        bpl :-
        ldy #3 * MO_SIZE + MC_SIGHT     ; t1's sightline: the first hint
        lda (GC_MP),y
        sta SG_LINE
        iny
        lda (GC_MP),y
        sta SG_LINE+1
        ; strace.dx, dy = t2x - x, t2y - y
        ldx #0
        jsr dsub
        ldx #4
        jsr dsub
        ; the box: x (X = 0), then y (X = 4)
        ldx #0
        jsr box
        ldx #4
        jsr box
        stz SG_SB
        stz SG_SB+1
        stz SG_TB
        stz SG_TB+1
        stz SG_CSZ
        ; the walk: the marker, then the hint, else the root
        tsx
        stx SG_S0
        lda #MARK_HI
        pha
        lda #MARK_LO
        pha
        lda SG_LINE             ; t1's sightline (a line + 1, upstream
        ora SG_LINE+1           ;   takes it as it is)
        bne @hint
        lda SG_T1               ; else its hint, when a line of this map
        ldx SG_T1+1
        jsr hn_get
        sta SG_LINE
        stx SG_LINE+1
        ora SG_LINE+1
        beq @root
        lda SG_LINE             ; hint - 1 < numlines
        sec
        sbc #1
        tay
        lda SG_LINE+1
        sbc #0
        cpy LVCOUNT2
        sbc LVCOUNT2+1
        bcs @root
@hint:  jsr root                ; the tree waits
        phx
        pha
        lda SG_LINE             ; the line: hint - 1, with its sectors
        bne :+
        dec SG_LINE+1
:       dec SG_LINE
        ldx SG_LINE+1
        lda SG_LINE
        jsr ln_get
        ldy #LN_FS
        lda (GC_LP),y
        sta SG_FS
        iny
        lda (GC_LP),y
        sta SG_BS
        stz SG_SC               ; a subsector of one seg: none after it
        jmp seg_line
@root:  jsr root
        jmp node_loop

; root: A:X = numnodes - 1
root:   lda LVCOUNT2+6
        sec
        sbc #1
        pha
        lda LVCOUNT2+7
        sbc #0
        tax
        pla
        rts

; ---------------------------------------------------------------------------
; The walk (P_CrossBSPNode): node_loop with A:X a child (bit 15: a
; subsector)
; ---------------------------------------------------------------------------
node_loop:
        cpx #$80
        bcs subsector
        jsr nd_get              ; LW_NODEB
        lda #<LW_NODEB
        sta SG_DLP
        lda #>LW_NODEB
        sta SG_DLP+1
        ldx #SG_SX - SG         ; the start's side ("on": the front)
        ldy #NODE_DX
        jsr side_pt
        and #1
        sta SG_S1
        ldx #SG_EX - SG         ; the end's
        ldy #NODE_DX
        jsr side_pt
        cmp SG_S1
        beq @same
        lda SG_S1               ; crossed: the other child waits
        eor #1
        jsr child
        phx
        pha
@same:  lda SG_S1               ; the start's child
        jsr child
        bra node_loop

; child: A:X = the node's children[A]
child:  asl a
        tay
        lda LW_NODEB + NODE_CH0 + 1,y
        tax
        lda LW_NODEB + NODE_CH0,y
        rts

; P_CrossSubsector: the subsector A:X & $7FFF ($FFFF: 0)
subsector:
        cmp #$FF
        bne :+
        cpx #$FF
        bne :+
        lda #0
        tax
:       pha
        txa
        and #$7F
        tax
        pla
        jsr ss_get
        lda SS_BUF + SUB_COUNT
        sta SG_SC
        lda SS_BUF + SUB_FIRST
        sta SG_SEG
        lda SS_BUF + SUB_FIRST + 1
        sta SG_SEG+1
seg_top:
        lda SG_SC
        jeq sub_done
        dec SG_SC
        lda SG_SEG
        ldx SG_SEG+1
        jsr sg_get
        lda SG_BUF + SEG_LINE
        sta SG_LINE
        lda SG_BUF + SEG_LINE + 1
        sta SG_LINE+1
        lda SG_BUF + SEG_FRONT
        sta SG_FS
        lda SG_BUF + SEG_BACK
        sta SG_BS
        ; the seg's line, once a check (its stamp)
seg_line:
        lda SG_LINE
        ldx SG_LINE+1
        jsr ln_get
        ldy #LN_VALID
        lda (GC_LP),y
        cmp G_VALID
        bne @stamp
        iny
        lda (GC_LP),y
        cmp G_VALID+1
        jeq next_seg
@stamp: ldy #LN_VALID
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
        ; its box misses the line of sight's: left > XH, right < XL,
        ; bottom > YH or top < YL (+ $8000, p_sight65.s:453-476)
        ldy #LN_LEFT + 1
        lda (GC_LP),y
        eor #$80
        sta GT_0
        dey
        lda SG_XH
        cmp (GC_LP),y
        lda SG_XH+1
        sbc GT_0
        jcc next_seg
        ldy #LN_RIGHT + 1
        lda (GC_LP),y
        eor #$80
        sta GT_0
        dey
        lda (GC_LP),y
        cmp SG_XL
        lda GT_0
        sbc SG_XL+1
        jcc next_seg
        ldy #LN_BOTTOM + 1
        lda (GC_LP),y
        eor #$80
        sta GT_0
        dey
        lda SG_YH
        cmp (GC_LP),y
        lda SG_YH+1
        sbc GT_0
        jcc next_seg
        ldy #LN_TOP + 1
        lda (GC_LP),y
        eor #$80
        sta GT_0
        dey
        lda (GC_LP),y
        cmp SG_YL
        lda GT_0
        sbc SG_YL+1
        jcc next_seg
        ; two-sided with the same floor and ceiling on both sides: no
        ; wall to block sight with
        ldy #LN_FLAGS
        lda (GC_LP),y
        and #ML_TWOSIDED
        beq sides
        jsr fs_bs
        ldy #SEC_CEIL + 3       ; the floor and the ceiling (8 bytes)
:       lda (GT_0),y
        cmp (GT_2),y
        bne sides
        dey
        bpl :-
        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the heights"
        jmp next_seg

        ; the ends of the line of sight on the two sides of the line, and
        ; the ends of the line on the two sides of the line of sight
sides:  lda GC_LP
        sta SG_DLP
        lda GC_LP+1
        sta SG_DLP+1
        ldx #SG_SX - SG
        ldy #LN_DX
        jsr side_pt
        sta SG_S1
        ldx #SG_EX - SG
        ldy #LN_DX
        jsr side_pt
        cmp SG_S1
        jeq next_seg
        ldy #LN_V1X
        jsr line_side
        sta SG_S1
        ldy #LN_V2X
        jsr line_side
        cmp SG_S1
        jeq next_seg
        ; crossed: a one-sided line blocks (sightblocker = the line + 1)
        ldy #LN_FLAGS
        lda (GC_LP),y
        and #ML_TWOSIDED
        bne two_sided
        clc
        lda SG_LINE
        adc #1
        sta SG_SB
        lda SG_LINE+1
        adc #0
        sta SG_SB+1
        jmp blocked

        ; a two-sided line: blocked when its opening is closed; else the
        ; slopes narrow to its bottom and top where the floors or the
        ; ceilings differ, blocked when they close (p_sight65.s:540-607)
two_sided:
        FCALL p_sight_opening
        lda SG_OBOT             ; openbottom >= opentop: closed
        cmp SG_OTOP
        lda SG_OBOT+1
        sbc SG_OTOP+1
        lda SG_OBOT+2
        sbc SG_OTOP+2
        lda SG_OBOT+3
        sbc SG_OTOP+3
        bvc :+
        eor #$80
:       jpl keep_two
        lda SG_CSZ              ; the heights of los, the first time
        bne :+
        FCALL zSetup
:       FCALL interceptFrac
        ldy #SEC_FLOOR          ; the floors differ: bottomslope =
        jsr same_h              ;   max(bottomslope, the slope)
        beq @ceil
        ldx #3
:       lda SG_OBOT,x
        sta GA_0,x
        dex
        bpl :-
        FCALL sightSlope
        lda M_R
        cmp SG_BOT
        lda M_R+1
        sbc SG_BOT+1
        lda M_R+2
        sbc SG_BOT+2
        lda M_R+3
        sbc SG_BOT+3
        bvc :+
        eor #$80
:       bmi @ceil
        ldx #3
:       lda M_R,x
        sta SG_BOT,x
        dex
        bpl :-
@ceil:  ldy #SEC_CEIL           ; the ceilings differ: topslope =
        jsr same_h              ;   min(topslope, the slope)
        beq @test
        ldx #3
:       lda SG_OTOP,x
        sta GA_0,x
        dex
        bpl :-
        FCALL sightSlope
        lda M_R
        cmp SG_TOP
        lda M_R+1
        sbc SG_TOP+1
        lda M_R+2
        sbc SG_TOP+2
        lda M_R+3
        sbc SG_TOP+3
        bvc :+
        eor #$80
:       bpl @test
        ldx #3
:       lda M_R,x
        sta SG_TOP,x
        dex
        bpl :-
@test:  lda SG_BOT              ; topslope <= bottomslope: blocked
        cmp SG_TOP
        lda SG_BOT+1
        sbc SG_TOP+1
        lda SG_BOT+2
        sbc SG_TOP+2
        lda SG_BOT+3
        sbc SG_TOP+3
        bvc :+
        eor #$80
:       jpl keep_two
        ; (on into next_seg)
next_seg:
        inc SG_SEG
        jne seg_top
        inc SG_SEG+1
        jmp seg_top

        ; blocked by the two-sided line: the line + 1 for its hint
keep_two:
        clc
        lda SG_LINE
        adc #1
        sta SG_TB
        lda SG_LINE+1
        adc #0
        sta SG_TB+1
        ; blocked: the waiting children go
blocked:
        ldx SG_S0
        txs
        lda #0
        bra walk_end

        ; crossed: the next waiting child, or seen
sub_done:
        pla
        plx
        cmp #MARK_LO
        bne :+
        cpx #MARK_HI
        beq @seen
:       jmp node_loop
@seen:  lda #1
        ; CS_PREVR; t1's sightline = sightblocker; its hint = TWOBLOCKER
walk_end:
        sta CS_PREVR
        lda SG_T1
        ldx SG_T1+1
        jsr mo_get
        ldy #3 * MO_SIZE + MC_SIGHT
        lda SG_SB
        sta (GC_MP),y
        iny
        lda SG_SB+1
        sta (GC_MP),y
        lda #8                  ; group C
        jsr mo_dirty
        lda SG_TB               ; the hint = TWOBLOCKER
        sta API_W
        lda SG_TB+1
        sta API_W+1
        lda SG_T1
        ldx SG_T1+1
        jsr hn_put
        lda CS_PREVR
        rts

; ---------------------------------------------------------------------------
; Helpers of the walk
; ---------------------------------------------------------------------------

; sub_sec: mobj slot A:X: SG_SEG = its subsector, A = the subsector's
; sector
sub_sec:
        jsr mo_get
        ldy #MO_SIZE + MA_SUBSEC
        lda (GC_MP),y
        sta SG_SEG
        iny
        lda (GC_MP),y
        sta SG_SEG+1
        tax
        lda SG_SEG
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        rts

; dsub: strace.d (SG_DX + X) = t2 (SG_EX + X) - strace (SG_SX + X), 32 bits
dsub:   sec
        jsr :+
        jsr :+
        jsr :+
:       lda SG_EX,x
        sbc SG_SX,x
        sta SG_DX,x
        inx
        rts

; box: the line of sight's box on axis X (0: x, 4: y): H = the whole part
; of the higher end + $8000, L = the ceil of the lower end + $8000
; (p_sight65.s:242-273)
box:    lda SG_EX,x             ; C = t2 < t1
        cmp SG_SX,x
        lda SG_EX+1,x
        sbc SG_SX+1,x
        lda SG_EX+2,x
        sbc SG_SX+2,x
        lda SG_EX+3,x
        sbc SG_SX+3,x
        bvc :+
        eor #$80
:       asl a
        txa
        bcc :+
        ldy #SG_SX - SG         ; t1 the higher end, t2 the lower
        adc #SG_EX - SG - 1     ;   (C set)
        bra @ends
:       ldy #SG_EX - SG         ; t2 the higher end, t1 the lower
        adc #SG_SX - SG         ;   (C clear)
@ends:  sta GT_0                ; the lower end's offset
        stx GT_1
        tya
        clc
        adc GT_1
        tay                     ; the higher end's
        lda SG+2,y
        sta SG_XH,x
        lda SG+3,y
        eor #$80
        sta SG_XH+1,x
        ldy GT_0
        lda SG,y                ; C = a fraction
        ora SG+1,y
        cmp #1
        lda SG+2,y
        adc #0
        sta SG_XL,x
        lda SG+3,y
        adc #$80
        sta SG_XL+1,x
        rts
        .assert SG_YL - SG_XL = 4 && SG_YH - SG_XH = 4, error, "the box"
        .assert SG_SY - SG_SX = 4 && SG_EY - SG_EX = 4, error, "the ends"

; fs_bs: the sectors SG_FS, SG_BS into the sector cache: SG_FSP, SG_BSP
; their lines, GT_0-1 and GT_2-3 too
fs_bs:  lda SG_FS
        jsr sec_get
        lda GC_SP
        sta SG_FSP
        lda GC_SP+1
        sta SG_FSP+1
        lda SG_BS
        jsr sec_get
        lda GC_SP
        sta SG_BSP
        lda GC_SP+1
        sta SG_BSP+1
        ; (on into fs_ptr)

; fs_ptr: GT_0-1 = SG_FSP, GT_2-3 = SG_BSP
fs_ptr: ldx #3
:       lda SG_FSP,x
        sta GT_0,x
        dex
        bpl :-
        rts
        .assert SG_BSP = SG_FSP + 2, error, "FSP, BSP"

; same_h: Z set when the 32-bit heights at offset Y of FS and BS are equal
; (sameHeight)
same_h: jsr fs_ptr
        ldx #4
:       lda (GT_0),y
        cmp (GT_2),y
        bne @out
        iny
        dex
        bne :-
@out:   rts

; ---------------------------------------------------------------------------
; The side tests (P_DivlineSide): A = 0 front, 1 back, 2 on
; ---------------------------------------------------------------------------

; side_pt: the point at SG + X (x, then y at SG + X + 4: fixed_t) against
; the divline at SG_DLP (x, y at 0, 2; dx, dy at Y, Y + 2: whole units):
;   !dx ? x == dl.x ? 2 : x <= dl.x ? dy > 0 : dy < 0 :
;   !dy ? y == dl.y ? 2 : y <= dl.y ? dx < 0 : dx > 0 :
;   sg_side with QA = y.hi - dl.y, QB = dx, QC = x.hi - dl.x, QD = dy
; (16-bit differences with their wrap; p_sight65.s:620-693)
side_pt:
        lda SG_DLP
        sta GT_0
        lda SG_DLP+1
        sta GT_1
        sty GT_3
        lda (GT_0),y            ; dx
        iny
        ora (GT_0),y
        jeq @dx0
        iny
        lda (GT_0),y            ; dy
        iny
        ora (GT_0),y
        jeq @dy0
        ldy GT_3                ; QB = dx, QD = dy
        lda (GT_0),y
        sta SG_QB
        iny
        lda (GT_0),y
        sta SG_QB+1
        iny
        lda (GT_0),y
        sta SG_QD
        iny
        lda (GT_0),y
        sta SG_QD+1
        ldy #2                  ; QA = y.hi - dl.y
        sec
        lda SG+6,x
        sbc (GT_0),y
        sta SG_QA
        iny
        lda SG+7,x
        sbc (GT_0),y
        sta SG_QA+1
        sec                     ; QC = x.hi - dl.x
        lda SG+2,x
        sbc (GT_0)
        sta SG_QC
        ldy #1
        lda SG+3,x
        sbc (GT_0),y
        sta SG_QC+1
        jmp sg_side
@dx0:   sec                     ; dx == 0: x.hi - dl.x
        lda SG+2,x
        sbc (GT_0)
        sta GT_2
        ldy #1
        lda SG+3,x
        sbc (GT_0),y
        tay
        ora GT_2
        beq @xeq
        tya
        bvc :+
        eor #$80
:       bmi @xlt
@xgt:   lda GT_3                ; x > dl.x: dy < 0
        clc
        adc #3
        tay
        lda (GT_0),y
        bmi @r1
        bra @r0
@xeq:   lda SG,x                ; the same whole part: a fraction is more
        ora SG+1,x
        bne @xgt
        lda #2
        rts
@xlt:   lda GT_3                ; x < dl.x: dy > 0
        clc
        adc #3
        tay
        lda (GT_0),y
        bmi @r0
        dey
        ora (GT_0),y
        bne @r1
@r0:    lda #0
        rts
@r1:    lda #1
        rts
@dy0:   ldy #2                  ; dy == 0 (dx != 0): y.hi - dl.y
        sec
        lda SG+6,x
        sbc (GT_0),y
        sta GT_2
        iny
        lda SG+7,x
        sbc (GT_0),y
        tay
        ora GT_2
        beq @yeq
        tya
        bvc :+
        eor #$80
:       bmi @ylt
@ygt:   ldy GT_3                ; y > dl.y: dx > 0
        iny
        lda (GT_0),y
        bmi @r0
        bra @r1
@yeq:   lda SG+4,x
        ora SG+5,x
        bne @ygt
        lda #2
        rts
@ylt:   ldy GT_3                ; y < dl.y: dx < 0
        iny
        lda (GT_0),y
        bmi @r1
        bra @r0

; line_side: the line's vertex at offset Y of the line (GC_LP), v << 16,
; against the line of sight (lineSideS, p_sight65.s:838-913):
;   !s.dx ? x == s.x ? 2 : x <= s.x ? s.dy > 0 : s.dy < 0 :
;   !s.dy ? y == s.y ? 2 : y <= s.y ? s.dx < 0 : s.dx > 0 :
;   sg_side with QA = (y - s.y) >> 16 (0 when s.dx >> 16 is 0), QB =
;   s.dx >> 16, QC = (x - s.x) >> 16 (0 when s.dy >> 16 is 0), QD =
;   s.dy >> 16
line_side:
        lda (GC_LP),y           ; GT_2-3 vx, GT_4-5 vy
        sta GT_2
        iny
        lda (GC_LP),y
        sta GT_3
        iny
        lda (GC_LP),y
        sta GT_4
        iny
        lda (GC_LP),y
        sta GT_5
        lda SG_DX
        ora SG_DX+1
        ora SG_DX+2
        ora SG_DX+3
        jeq @dx0
        lda SG_DY
        ora SG_DY+1
        ora SG_DY+2
        ora SG_DY+3
        jeq @dy0
        lda #0                  ; QA: borrow when s.y has a fraction
        cmp SG_SY
        lda #0
        sbc SG_SY+1
        lda GT_4
        sbc SG_SY+2
        sta SG_QA
        lda GT_5
        sbc SG_SY+3
        sta SG_QA+1
        lda #0                  ; QC
        cmp SG_SX
        lda #0
        sbc SG_SX+1
        lda GT_2
        sbc SG_SX+2
        sta SG_QC
        lda GT_3
        sbc SG_SX+3
        sta SG_QC+1
        lda SG_DX+2             ; QB, and QA 0 when it is 0
        sta SG_QB
        lda SG_DX+3
        sta SG_QB+1
        ora SG_QB
        bne :+
        stz SG_QA
        stz SG_QA+1
:       lda SG_DY+2             ; QD, and QC 0 when it is 0
        sta SG_QD
        lda SG_DY+3
        sta SG_QD+1
        ora SG_QD
        bne :+
        stz SG_QC
        stz SG_QC+1
:       jmp sg_side
@dx0:   sec                     ; s.dx == 0: vx - s.x.hi
        lda GT_2
        sbc SG_SX+2
        sta GT_6
        lda GT_3
        sbc SG_SX+3
        tay
        ora GT_6
        beq @xeq
        tya
        bvc :+
        eor #$80
:       bmi @xlt
        lda SG_DY+3             ; x > s.x: s.dy < 0
        bmi @r1
        bra @r0
@xeq:   lda SG_SX               ; the same whole part: s.x with a
        ora SG_SX+1             ;   fraction is more
        bne @xlt
        lda #2
        rts
@xlt:   lda SG_DY+3             ; x < s.x: s.dy > 0
        bmi @r0
        ora SG_DY+2
        ora SG_DY+1
        ora SG_DY
        beq @r0
        bra @r1
@dy0:   sec                     ; s.dy == 0 (s.dx != 0): vy - s.y.hi
        lda GT_4
        sbc SG_SY+2
        sta GT_6
        lda GT_5
        sbc SG_SY+3
        tay
        ora GT_6
        beq @yeq
        tya
        bvc :+
        eor #$80
:       bmi @ylt
        lda SG_DX+3             ; y > s.y: s.dx > 0
        bmi @r0
        bra @r1
@yeq:   lda SG_SY
        ora SG_SY+1
        bne @ylt
        lda #2
        rts
@ylt:   lda SG_DX+3             ; y < s.y: s.dx < 0
        bmi @r1
@r0:    lda #0
        rts
@r1:    lda #1
        rts

; sg_side: A = 0 when QA QB < QC QD, 2 when equal, else 1 (the exact
; signed products: sideTest's answer)
sg_side:
        ldx #0
        jsr smul16
        ldx #3
:       lda M_R,x
        sta SG_QR,x
        dex
        bpl :-
        ldx #SG_QC - SG_QA
        jsr smul16
        sec                     ; QR - M_R: its sign, or 0
        lda SG_QR
        sbc M_R
        sta GT_0
        lda SG_QR+1
        sbc M_R+1
        tsb GT_0
        lda SG_QR+2
        sbc M_R+2
        tsb GT_0
        lda SG_QR+3
        sbc M_R+3
        tax
        ora GT_0
        beq @eq
        txa
        bvc :+
        eor #$80
:       bmi @r0
        bra @r1
@eq:    lda #2
        rts
@r0:    lda #0
        rts
@r1:    lda #1
        rts

; smul16: M_R = (SG_QA + X) (SG_QB + X), signed 16 x 16 -> 32, exact
smul16: lda SG_QA+1,x
        eor SG_QB+1,x
        sta SG_QS
        lda SG_QA,x
        ldy SG_QA+1,x
        jsr sg_mag
        sta M_A
        sty M_A+1
        lda SG_QB,x
        ldy SG_QB+1,x
        jsr sg_mag
        sta M_B
        sty M_B+1
        phx
        jsr umul16
        plx
        bit SG_QS
        bpl :+
        sec
        lda #0
        sbc M_R
        sta M_R
        lda #0
        sbc M_R+1
        sta M_R+1
        lda #0
        sbc M_R+2
        sta M_R+2
        lda #0
        sbc M_R+3
        sta M_R+3
:       rts

; sg_mag: A:Y = |v| for v = A:Y (low, high): 0-32768, -32768 giving 32768
; (upstream's half of 2 |v|)
sg_mag: cpy #$80
        bcc :+
        eor #$FF
        clc
        adc #1
        pha
        tya
        eor #$FF
        adc #0
        tay
        pla
:       rts

; bitTab: REJECT's bit order (p_sight65.s:1442)
bitTab: .byte 1, 2, 4, 8, 16, 32, 64, 128

; ---------------------------------------------------------------------------
; sg_bulk (TESTBUILD only, which no build here defines): the arithmetic
; helpers on many inputs, for random checks against upstream's helpers on
; ref816. A = the helper: 0 sg_mag (2 bytes in, 2 out), 1 the
; side test (QA, QB, QC, QD in; its answer out, 1 byte), 2 smul48 (V 4
; and C 2 in; 6 out); X:Y = the count. The inputs from bank SPARE_IN at
; $0200, the outputs to bank SPARE_OUT at $0200.
; ---------------------------------------------------------------------------
.ifdef TESTBUILD
        ; test-only code goes in the card's driver area, not the core
        ; (the core's room is the game's)
        .segment "DRIVER"
FC_HERE .set 0
; sg_timed (TESTBUILD only): a timing harness's call of entry A (0
; P_CheckSight, 1 zSetup, 2 sightSlope, 3 interceptFrac, 4 p_sight_opening)
; with the cost phase (rlayout PHASE) 1 around it (a2vm --cost-phase: the
; value written / 2), so a2vm's cost report times the call alone; A, X, Y
; and the carry come back from the entry
sg_timed:
        ldx #2
        stx PHASE
        cmp #1
        beq @z
        cmp #2
        beq @s
        cmp #3
        beq @i
        cmp #4
        beq @o
        FCALL P_CheckSight
        bra @end
@z:     FCALL zSetup
        bra @end
@s:     FCALL sightSlope
        bra @end
@i:     FCALL interceptFrac
        bra @end
@o:     FCALL p_sight_opening
@end:   php
        stz PHASE
        plp
        rts

BULK_IN  = 93
BULK_OUT = 94
SB_IP   = SG_DLN                ; the input's place, the output's, the count
SB_OP   = SG_DLN + 2
SB_N    = SG_DLN + 4
SB_K    = SG_DLN + 6            ; the helper
        ; sg_bulk calls sg_mag and sg_side, P_CheckSight's own: its image
        ; must be resident (the placement keeps it in the core)
        .assert GP_P_CheckSight_G = 0, error, "P_CheckSight in the core"
sg_bulk:
        pha                     ; (a machine with no game: the math's
        phx                     ;   square pointers first)
        phy
        jsr mt_init
        ply
        plx
        pla
        sta SB_K
        stx SB_N
        sty SB_N+1
        lda #<$0200
        sta SB_IP
        sta SB_OP
        lda #>$0200
        sta SB_IP+1
        sta SB_OP+1
@next:  lda SB_N
        ora SB_N+1
        bne :+
        rts
:       lda SB_N
        bne :+
        dec SB_N+1
:       dec SB_N
        lda SB_K
        beq @mag
        cmp #1
        beq @side
        lda #6                  ; smul48: V, C
        jsr bulk_in
        ldx #3
:       lda GA_0,x
        sta SG_IFV,x
        dex
        bpl :-
        lda GA_4
        ldx GA_5
        FCALL smul48
        ldx #5
:       lda SG_IFP,x
        sta GA_0,x
        dex
        bpl :-
        lda #6
        bra @out
@mag:   lda #2
        jsr bulk_in
        lda GA_0
        ldy GA_1
        jsr sg_mag
        sta GA_0
        sty GA_1
        lda #2
        bra @out
@side:  lda #8
        jsr bulk_in
        ldx #7
:       lda GA_0,x
        sta SG_QA,x
        dex
        bpl :-
        jsr sg_side
        sta GA_0
        lda #1
@out:   sta FA_N                ; GA_0.. to the output
        lda #<GA_0
        sta FA_SRC
        stz FA_SRC+1
        lda SB_OP
        sta FA_DST
        lda SB_OP+1
        sta FA_DST+1
        lda #BULK_OUT
        sta FA_BANK
        jsr far_put
        clc
        lda SB_OP
        adc FA_N
        sta SB_OP
        bcc :+
        inc SB_OP+1
:       jmp @next

; bulk_in: A bytes of the input to GA_0..
bulk_in:
        sta FA_N
        lda SB_IP
        sta FA_SRC
        lda SB_IP+1
        sta FA_SRC+1
        lda #<GA_0
        sta FA_DST
        stz FA_DST+1
        lda #BULK_IN
        sta FA_BANK
        jsr far_get
        clc
        lda SB_IP
        adc FA_N
        sta SB_IP
        bcc :+
        inc SB_IP+1
:       rts
        .assert SG_QB = SG_QA + 2 && SG_QC = SG_QA + 4 && SG_QD = SG_QA + 6, error, "QA-QD"
.endif
