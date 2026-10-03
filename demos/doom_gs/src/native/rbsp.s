; rbsp.s: the BSP walk of the native renderer (docs/RENDER.md; milestone
; 7, stage A): R_RenderBSPNode, R_CheckBBox, R_Subsector, R_AddLine and
; R_ClipWallSegment with upstream's results, and the vertex-angle cache.
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_bsp65.s, r_iigs65.s): the same walk, the same calls of
; R_StoreWallRange, written for the 65C02 with the native level of
; tools/native/levelconv.py (records in RamWorks, fetched whole by the far
; layer) instead of pointers into the level window.
;
; Interface (RENDER.md 3.2)
;
;   nr_bsp      A:X = the root (numnodes - 1: A the low byte). The frame
;               block's view (VIEWX, VIEWY, VIEWA16), VA_*, VALIDCOUNT,
;               SKYFLAT, NUKAGE, LT_*; SOLIDCOL. Out: nr_storewall called
;               for each wall range, as upstream calls R_StoreWallRange;
;               the vertex cache and each sector's validcount stamped;
;               VA_COUNT (the vertex angles computed, rtest). Changes
;               everything but the frame block's inputs.
;   nr_side     C = the side of the view of the node in the frame FRP
;               (R_PointOnSide: bspNode's tests for dx or dy 0, else
;               viewSide's products; upstream's c14Bounds is dropped, see
;               below)
;   nr_checkbox A = the box's offset in the node frame (ND_BOX0, ND_BOX1).
;               C = the box may be visible (R_CheckBBox with boxPre)
;   nr_scan0, nr_scan1
;               A = the first column from X below BS_LAST that is open (0)
;               or solid (not 0), else BS_LAST
;
; The walk recurses with JSR and keeps each level's node in a node frame
; of W (NODEF + 32 a level, FRP): 2 bytes of stack a level. The back side
; is a tail call that reuses the frame, as upstream's brl.
;
; The box corner cache (speed wave 2, part frontend; RENDER-MASKED.md 6.2
; optimisation 2). A corner's angle, R_PointToAngle16 of the corner from
; the view's map unit, depends on nothing else, so while the view stays
; at one map unit the two corners of the box and case a node last checked
; are kept: in RENDB's CCANG (4 bytes a node), named by the node's tag in
; its record's pad (ND_CCT: the unit's stamp, the box and case), which
; the walk fetches with the node anyway. The cache has its own state
; (CCSTATE: the unit and its stamp), read once a frame (cc_frame); a new
; unit takes a new stamp (after 255, every node's stamp is cleared
; first). A frame at a new unit neither reads nor writes entries (most
; frames move: they pay cc_frame's two windows and a test a node); the
; later frames at the unit read them (one RAMRD window a box) and write
; the ones they miss (one RAMWRT window). A level's load writes its nodes
; with tags of 0, which no stamp takes.

; viewSide: upstream first tries c14Bounds (r_bsp65.s:1237-1311), a log
; table interval test it claims exact, and falls back to the two shiftMul
; products. This code always takes the products, which gives upstream's
; side whenever the claim holds: tools/native/sidecheck.py (check A3 of
; RENDER.md 5.1) compares nr_side with upstream's viewSide on random and
; dense edge cases of every map, with c14Bounds in upstream's path.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, far_put, far_vgather, far_vput, far_vclear
        .import vg_n, vg_vlo, vg_vhi, vg_al, vg_ah, vg_s, vg_d
        .import pta16, umul16, umul16lo
        .import ax_vtox
        .import nr_storewall, nr_planes
        .export nr_bsp, nr_side, nr_checkbox, nr_scan0, nr_scan1
        .export nr_addsprites

; MARK n: in the profiling build (-D RPROF), the cost phase n (a2vm reads
; the value / 2: RENDER.md 4.2), at upstream's places (PHASE of
; r_bsp65.s). Keeps A, X, Y and the flags but N and Z.
.macro MARK n
.ifdef RPROF
        pha
        lda #(n) * 2
        sta PHASE
        pla
.endif
.endmacro

C2      = 2 * CLIPANGLE
SM_AH   = T0+2                  ; shiftmul: the signed high byte of v

        .segment "RENDERW"

; ===========================================================================
; nr_bsp: R_RenderBSPNode(A:X)
; ===========================================================================
nr_bsp:
        sta NB_N
        stx NB_N+1
        stz BS_F                ; no solid column yet
        jsr cc_frame            ; the box corner cache's use this frame
        lda VIEWX+2             ; the vertex angles stay while the view
        cmp VA_VX               ;   stays at the same map unit
        bne @new
        lda VIEWX+3
        cmp VA_VX+1
        bne @new
        lda VIEWY+2
        cmp VA_VY
        bne @new
        lda VIEWY+3
        cmp VA_VY+1
        bne @new
        lda VA_STAMP
        bne @keep
@new:   lda VIEWX+2
        sta VA_VX
        lda VIEWX+3
        sta VA_VX+1
        lda VIEWY+2
        sta VA_VY
        lda VIEWY+3
        sta VA_VY+1
        inc VA_STAMP            ; a new stamp for the angle cache
        bne @keep
        jsr far_vclear          ; after 255 stamps: no angles
        inc VA_STAMP
@keep:  lda #NO_SECTOR          ; (bspSub: no sector before)
        sta CN_LSEC
        lda #<NODEF
        sta FRP
        lda #>NODEF
        sta FRP+1
        lda NB_N
        ldx NB_N+1
        ; fall into bspnode

; ---------------------------------------------------------------------------
; bspnode: A:X = a child (bit 15: a subsector; $FFFF: subsector 0).
; ---------------------------------------------------------------------------
bspnode:
        cpx #$80
        bcc @node
        cpx #$FF                ; -1: subsector 0
        bne :+
        cmp #$FF
        bne :+
        lda #0
        tax
:       jmp nr_sub              ; (bit 15 too: SUBBASE + 4 n drops it)

@node:  sta FA_SRC+1            ; the node into its frame: NODEBASE + 32 n,
        stz FA_SRC              ;   32 n = (n << 8) >> 3 (speed wave 2:
        txa                     ;   shorter and 20 cycles faster; NODEBASE
        lsr a                   ;   page aligned)
        ror FA_SRC+1
        ror FA_SRC
        lsr a
        ror FA_SRC+1
        ror FA_SRC
        lsr a
        ror FA_SRC+1
        ror FA_SRC
        clc
        lda FA_SRC+1
        adc #>NODEBASE
        sta FA_SRC+1
        lda FRP
        sta FA_DST
        lda FRP+1
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #NODE_SIZE
        sta FA_N
        jsr far_get
        lda CC_ON               ; the corner cache: the node's address in
        beq :+                  ;   its frame
        ldy #ND_CCN
        lda FA_SRC
        sta (FRP),y
        iny
        lda FA_SRC+1
        sta (FRP),y
:       jsr nr_side
        bcs @side1

        ldy #ND_CH0             ; side 0: the front space children[0],
        jsr @down               ;   then box 1 and children[1]
        lda #ND_BOX1
        jsr nr_checkbox
        bcc @ret
        ldy #ND_CH1+1
        lda (FRP),y
        tax
        dey
        lda (FRP),y
        jmp bspnode

@side1: ldy #ND_CH1             ; side 1: children[1], box 0, children[0]
        jsr @down
        lda #ND_BOX0
        jsr nr_checkbox
        bcc @ret
        ldy #ND_CH0+1
        lda (FRP),y
        tax
        dey
        lda (FRP),y
        jmp bspnode
@ret:   rts

; @down: the child at Y of this node, one frame deeper.
@down:  lda (FRP),y
        pha
        iny
        lda (FRP),y
        tax
        clc
        lda FRP
        adc #NODE_SIZE
        sta FRP
        bcc :+
        inc FRP+1
:       lda FRP                 ; deeper than the node frames: stop
                                ;   (every build; levelconv.py refuses a
                                ;   level whose BSP is deeper)
        cmp #<NODEF_END
        lda FRP+1
        sbc #>NODEF_END
        bcc :+
        lda #ST_DEPTH
        sta STATUS
        brk
        .byte ST_DEPTH
:       pla
        jsr bspnode
        sec
        lda FRP
        sbc #NODE_SIZE
        sta FRP
        bcs :+
        dec FRP+1
:       rts

; ===========================================================================
; nr_side: C = the side of the view of the node in frame FRP
; ===========================================================================
nr_side:
        ldy #ND_DX
        lda (FRP),y
        iny
        ora (FRP),y
        beq @dx0
        ldy #ND_DY
        lda (FRP),y
        iny
        ora (FRP),y
        beq @dy0
        jmp viewside

@dx0:   ldy #ND_X               ; dx == 0: ix <= node->x ? dy > 0 : dy < 0
        lda (FRP),y             ;   (node->x < ix, signed)
        cmp VIEWX+2
        iny
        lda (FRP),y
        sbc VIEWX+3
        bvc :+
        eor #$80
:       bmi @dx0lt
        ldy #ND_DY+1            ; node->x >= ix: side 1 when dy > 0
        lda (FRP),y
        bmi @s0
        dey
        ora (FRP),y
        beq @s0
        sec
        rts
@dx0lt: ldy #ND_DY+1            ; node->x < ix: side 1 when dy < 0
        lda (FRP),y
        asl a
        rts
@s0:    clc
        rts

@dy0:   ldy #ND_Y               ; dy == 0: iy <= node->y ? dx < 0 : dx > 0
        lda (FRP),y             ;   (node->y < iy, signed)
        cmp VIEWY+2
        iny
        lda (FRP),y
        sbc VIEWY+3
        bvc :+
        eor #$80
:       bmi @dy0lt
        ldy #ND_DX+1            ; node->y >= iy: side 1 when dx < 0
        lda (FRP),y
        asl a
        rts
@dy0lt: ldy #ND_DX+1            ; node->y < iy: side 1 when dx >= 0
        lda (FRP),y
        eor #$80
        asl a
        rts

; viewside: R_PointOnSide for dx != 0, dy != 0 (upstream's viewSide).
; x = viewx - (node->x << 16), y = viewy - (node->y << 16); when the sign
; bits decide, (dy ^ dx ^ x ^ y) < 0, the side is the sign of dy ^ x; else
; L = shiftMul(dx, y) (the low 32 bits of (y >> 8) * dx), R = shiftMul(dy,
; x), and the side is L >= R, signed. Uses SD_L, T0-T3, the math block.
viewside:
        ldy #ND_X               ; the high words of x and y
        sec
        lda VIEWX+2
        sbc (FRP),y
        sta M_B+2               ; (x.hi, kept in M_B+2..3 until R)
        iny
        lda VIEWX+3
        sbc (FRP),y
        sta M_B+3
        ldy #ND_Y
        sec
        lda VIEWY+2
        sbc (FRP),y
        sta T0
        iny
        lda VIEWY+3
        sbc (FRP),y
        sta T0+1
        ldy #ND_DX+1            ; the sign bits decide: dy ^ dx ^ x ^ y < 0
        lda (FRP),y
        eor M_B+3
        eor T0+1
        ldy #ND_DY+1
        eor (FRP),y
        bpl @prod
        lda (FRP),y             ; (dy ^ x) < 0
        eor M_B+3
        asl a
        rts
@prod:  lda M_B+2               ; keep x.hi
        sta T0+2
        lda M_B+3
        sta T0+3
        lda VIEWY+1             ; L = shiftMul(dx, y): AL = bits 8-23 of
        sta M_A                 ;   y, AH = its byte 3
        lda T0
        sta M_A+1
        lda T0+1
        pha
        lda T0+2                ; (shiftmul uses T0-T1 and T0+2; x.hi to
        sta SD_L                ;   the stack and SD_L for now)
        lda T0+3
        sta SD_L+1
        ldy #ND_DX
        lda (FRP),y
        sta M_B
        iny
        lda (FRP),y
        sta M_B+1
        pla
        jsr shiftmul
        lda SD_L                ; x.hi back
        sta T0+2
        lda SD_L+1
        sta T0+3
        lda M_R                 ; L
        sta SD_L
        lda M_R+1
        sta SD_L+1
        lda M_R+2
        sta SD_L+2
        lda M_R+3
        sta SD_L+3
        lda VIEWX+1             ; R = shiftMul(dy, x)
        sta M_A
        lda T0+2
        sta M_A+1
        ldy #ND_DY
        lda (FRP),y
        sta M_B
        iny
        lda (FRP),y
        sta M_B+1
        lda T0+3
        jsr shiftmul
        lda SD_L                ; L - R >= 0, signed: C = not (L < R)
        cmp M_R
        lda SD_L+1
        sbc M_R+1
        lda SD_L+2
        sbc M_R+2
        lda SD_L+3
        sbc M_R+3
        bvc :+
        eor #$80
:       eor #$80
        asl a
        rts

; shiftmul: M_R = the low 32 bits of (A:M_A) * M_B, A the signed high
; byte, M_A unsigned 16, M_B signed 16 (upstream's shiftMul, r_iigs65.s:
; 625-660): AL * C + (AH * C + AL * (C < 0 ? -1 : 0)) << 16. Changes A,
; X, Y, M_A, T0, T0+1, SM_AH, the math's slots.
shiftmul:
        sta SM_AH
        jsr umul16              ; M_R = AL * C, unsigned
        bit M_B+1               ; C < 0: minus AL << 16
        bpl :+
        sec
        lda M_R+2
        sbc M_A
        sta M_R+2
        lda M_R+3
        sbc M_A+1
        sta M_R+3
:       lda SM_AH               ; + the low 16 bits of AH * C
        beq @done
        sta M_A
        stz M_A+1
        bpl :+
        dec M_A+1
:       lda M_R
        sta T0
        lda M_R+1
        sta T0+1
        jsr umul16lo
        clc
        lda M_R
        adc M_R+2
        sta M_R+2
        lda M_R+1
        adc M_R+3
        sta M_R+3
        lda T0
        sta M_R
        lda T0+1
        sta M_R+1
@done:  rts

; ===========================================================================
; nr_checkbox: R_CheckBBox of the box at offset A of the node frame
; ===========================================================================
; The corners to check come from the place of the view: x case 0 (viewx
; <= left << 16), 1 (viewx < right << 16), 2; y case 0 (viewy >= top <<
; 16), 1 (viewy > bottom << 16), 2. Case k = 3 y + x; 4: the view is in
; the box. Upstream's boxPre first (r_bsp65.s:347-370): false when all
; columns are solid, or when the arc of the case's corners lies outside
; the view and no corner is at the view's map unit.
nr_checkbox:
        clc
        adc FRP
        sta BP
        lda FRP+1
        adc #0
        sta BP+1
        ldy #BX_LEFT            ; x
        sec
        lda VIEWX+2
        sbc (BP),y
        sta T0
        iny
        lda VIEWX+3
        sbc (BP),y
        bvs @xv
        bmi @x0
        ora T0
        bne @x4
        lda VIEWX               ; viewx.hi == left: x 0 when viewx.lo == 0
        ora VIEWX+1
        beq @x0
        bra @x4
@xv:    bpl @x0                 ; (the overflow inverts the sign)
@x4:    ldy #BX_RIGHT           ; viewx < right << 16: x 1
        lda VIEWX+2
        cmp (BP),y
        iny
        lda VIEWX+3
        sbc (BP),y
        bvc :+
        eor #$80
:       bmi @x1
        ldx #2
        bra @y
@x1:    ldx #1
        bra @y
@x0:    ldx #0
@y:     ldy #BX_TOP             ; viewy >= top << 16: y 0
        lda VIEWY+2
        cmp (BP),y
        iny
        lda VIEWY+3
        sbc (BP),y
        bvc :+
        eor #$80
:       bpl @y0
        ldy #BX_BOTTOM
        sec
        lda VIEWY+2
        sbc (BP),y
        sta T0
        iny
        lda VIEWY+3
        sbc (BP),y
        bvs @yv
        bmi @y2
        ora T0
        bne @y1
        lda VIEWY               ; viewy.hi == bottom: y 1 when viewy.lo
        ora VIEWY+1             ;   != 0
        bne @y1
        bra @y2
@yv:    bpl @y2
@y1:    txa
        clc
        adc #3
        bra @case
@y2:    txa
        clc
        adc #6
        bra @case
@y0:    txa
@case:  cmp #4                  ; the view is in the box
        bne :+
        sec
        rts
:       tax
        lda BS_F                ; boxPre: all columns solid
        cmp #VIEWWIDTH
        bcs @false
        sec                     ; r0 - clipangle - viewangle >= the
        lda BXR0LO,x            ;   case's limit: the arc may be seen
        sbc VIEWA16
        sta T0
        lda BXR0HI,x
        sbc VIEWA16+1
        sta T0+1
        lda T0
        cmp BXLIMLO,x
        lda T0+1
        sbc BXLIMHI,x
        bcs @go
        jsr viewcorner          ; a corner at the view: go on
        bcs @go
@false: clc
        rts

@go:    stx T0+3                ; the case
        jsr cc_corners          ; CC_A: its two corners' angles
        sec                     ; angle1 = the first corner - viewangle,
        lda CC_A                ;   + $8000 (the signed order is then the
        sbc VIEWA16             ;   unsigned one)
        sta BS_A1
        lda CC_A+1
        sbc VIEWA16+1
        eor #$80
        sta BS_A1+1
        sec                     ; angle2 - viewangle + $8000
        lda CC_A+2
        sbc VIEWA16
        sta T0
        lda CC_A+3
        sbc VIEWA16+1
        eor #$80
        sta T0+1

        ; boxAngles (r_bsp65.s:504-564)
        lda BS_A1               ; angle1 < angle2: behind the view
        cmp T0
        lda BS_A1+1
        sbc T0+1
        bcs @a3
        lda BS_A1+1             ; ANG180 <= angle1 < ANG270: angle1 =
        cmp #$40                ;   INT16_MAX
        bcs @a2min
        lda #$FF
        sta BS_A1
        sta BS_A1+1
        bra @a3
@a2min: stz T0                  ; else angle2 = INT16_MIN
        stz T0+1
@a3:    lda T0                  ; angle2 >= clipangle: both off the left
        cmp #<(CLIPANGLE + $8000)
        lda T0+1
        sbc #>(CLIPANGLE + $8000)
        bcs @false
        lda T0                  ; angle2 <= -clipangle: clip it there
        cmp #<($8000 - CLIPANGLE + 1)
        lda T0+1
        sbc #>($8000 - CLIPANGLE + 1)
        bcs :+
        lda #<($8000 - CLIPANGLE)
        sta T0
        lda #>($8000 - CLIPANGLE)
        sta T0+1
:       sec                     ; sx2 = viewangletox(angle2)
        lda T0
        sbc #<($4000 + 8 * VIEWANGLETOXMAX)
        tax
        lda T0+1
        sbc #>($4000 + 8 * VIEWANGLETOXMAX)
        bcc :+
        jsr vtox_of
        bra :++
:       lda #VIEWWIDTH
:       sta BS_LAST
        lda BS_A1               ; angle1 <= -clipangle: both off the right
        cmp #<($8000 - CLIPANGLE + 1)
        lda BS_A1+1
        sbc #>($8000 - CLIPANGLE + 1)
        bcc @false2
        lda BS_A1               ; angle1 >= clipangle: clip it there
        sta T0
        lda BS_A1+1
        sta T0+1
        lda T0
        cmp #<(CLIPANGLE + $8000)
        lda T0+1
        sbc #>(CLIPANGLE + $8000)
        bcc :+
        lda #<(CLIPANGLE + $8000)
        sta T0
        lda #>(CLIPANGLE + $8000)
        sta T0+1
:       sec                     ; sx1 = viewangletox(angle1)
        lda T0
        sbc #<($4000 + 8 * VIEWANGLETOXMAX)
        tax
        lda T0+1
        sbc #>($4000 + 8 * VIEWANGLETOXMAX)
        bcc :+
        jsr vtox_of
        bra :++
:       lda #VIEWWIDTH
:       cmp BS_LAST             ; sx1 == sx2: no pixel crossed
        beq @false2
        tax                     ; all columns solid?
        jsr nr_scan0
        cmp BS_LAST
        beq @false2
        sec
        rts
@false2:
        clc
        rts

; cc_corners: CC_A = the angles of case T0+3's two corners (C1X/C1Y,
; C2X/C2Y) of the box BP: from the corner cache when it is on (CC_ON) and
; the node's tag is this unit's stamp and this box and case (the key
; CC_K), else computed (corner) and, when it is on, kept. Keeps T0+3.
; Changes A, X, Y, T0, FA_*, the math block.
cc_corners:
        lda CC_ON
        beq @calc
        lda BP                  ; the key: BP's low byte (the node's frame,
        eor T0+3                ;   the same for a node at every visit,
        sta CC_K                ;   + 8 box 0, + 16 box 1) ^ the case
        ldy #ND_CCT             ; the tag: this unit's stamp, this key?
        lda (FRP),y
        cmp CC_ST+4
        bne @calc
        iny
        lda (FRP),y
        cmp CC_K
        bne @calc
        jsr cc_rec              ; FA_SRC = the angles (RENDB)
        lda #<CC_A
        ldx #>CC_A
        ldy #4
        jmp cc_get
@calc:  ldx T0+3
        lda C1X,x
        ldy C1Y,x
        jsr corner
        lda M_R
        sta CC_A
        lda M_R+1
        sta CC_A+1
        ldx T0+3
        lda C2X,x
        ldy C2Y,x
        jsr corner
        lda M_R
        sta CC_A+2
        lda M_R+1
        sta CC_A+3
        lda CC_ON               ; keep them?
        beq @done
        jsr cc_rec              ; FA_SRC = their place, FA_DST = the node
        lda #RENDB
        sta RWBANK
        sta RAMWRTON            ; (W's code and data read as always)
        ldy #3
:       lda CC_A,y
        sta (FA_SRC),y
        dey
        bpl :-
        lda #LVMAP
        sta RWBANK
        ldy #ND_CCT             ; the node's tag
        lda CC_ST+4
        sta (FA_DST),y
        iny
        lda CC_K
        sta (FA_DST),y
        sta RAMWRTOFF
        stz RWBANK
@done:  rts

; cc_rec: FA_DST = the node's address (its frame's ND_CCN), FA_SRC = its
; angles, CCANG + 4 n = the address / 8 + (CCANG - NODEBASE / 8): a page
; (rlayout.py). Changes A, Y.
cc_rec: ldy #ND_CCN
        lda (FRP),y
        sta FA_DST
        sta FA_SRC
        iny
        lda (FRP),y
        sta FA_DST+1
        lsr a
        ror FA_SRC
        lsr a
        ror FA_SRC
        lsr a
        ror FA_SRC
        clc
        adc #>(CCANG - NODEBASE / 8)
        sta FA_SRC+1
        rts

; cc_get: Y bytes of RENDB at FA_SRC into main X:A (far_get)
cc_get: sta FA_DST
        stx FA_DST+1
        sty FA_N
        lda #RENDB
        sta FA_BANK
        jmp far_get

; cc_frame: CC_ST = CCSTATE (RENDB); at its map unit with a stamp, the
; cache is on (CC_ON $C0: its entries read and written); else it is off
; (0) and CCSTATE takes this unit and a new stamp (from 255: every node's
; stamp cleared, then 1). Changes A, X, Y, FA_*.
cc_frame:
        lda #<CCSTATE
        sta FA_SRC
        lda #>CCSTATE
        sta FA_SRC+1
        lda #<CC_ST
        ldx #>CC_ST
        ldy #CCST_SIZE
        jsr cc_get
        stz CC_K                ; the same map unit (CC_K 0)? (it takes
        ldx #3                  ;   this one)
:       ldy cc_unit,x
        lda VIEWX,y
        cmp CC_ST,x
        beq :+
        sta CC_ST,x
        sty CC_K                ; (Y: 2, 3, 6 or 7, not 0)
:       dex
        bpl :--
        lda CC_K
        bne @new
        lda CC_ST+4             ; (stamp 0: a fresh state)
        beq @new
        lda #$C0
        bra @on
@new:   inc CC_ST+4
        bne :+
        jsr cc_clear
        inc CC_ST+4
:       lda #RENDB              ; CCSTATE = CC_ST (one RAMWRT window)
        sta RWBANK
        sta RAMWRTON
        ldx #CCST_SIZE - 1
:       lda CC_ST,x
        sta CCSTATE,x
        dex
        bpl :-
        sta RAMWRTOFF
        stz RWBANK
        lda #0
@on:    sta CC_ON
        rts
cc_unit:                        ; the map unit: VIEWX's, VIEWY's high word
        .byte 2, 3, VIEWY - VIEWX + 2, VIEWY - VIEWX + 3

; cc_clear: every node's stamp 0 (NODES' capacity: the stamps wrapped),
; 8 nodes a page. One RAMWRT window.
cc_clear:
        stz FA_DST
        lda #>NODEBASE
        sta FA_DST+1
        lda #LVMAP
        sta RWBANK
        sta RAMWRTON
        ldy #ND_CCT
        clc
@node:  lda #0
        sta (FA_DST),y
        tya
        adc #NODE_SIZE
        tay
        bcc @node
        inc FA_DST+1            ; (C clear again below the end)
        lda FA_DST+1
        cmp #>(NODEBASE + NODE_SIZE * NODE_CAP)
        bne @node
        sta RAMWRTOFF
        stz RWBANK
        rts
.assert <NODEBASE = 0 && NODE_SIZE = 32 && <(NODE_SIZE * NODE_CAP) = 0, error, "cc_clear's pages"
.assert <(CCANG - NODEBASE / 8) = 0, error, "cc_rec's angles of a node"
.assert <NODEBASE = 0 && NODE_SIZE = 32, error, "bspnode's address of a node"
.assert <SUBBASE = 0 && <SEGBASE = 0, error, "nr_sub's records' bases"
.assert ND_BOX0 = 8 && ND_BOX1 = 16 && <NODEF = 0 && NODE_SIZE = 32, error, "cc_corners's key: 8 ^ k and 16 ^ k (k 0-8) apart"
.assert VIEWY - VIEWX < 252 && VIEWY <> VIEWX, error, "cc_unit"

; corner: M_R = R_PointToAngle16 of the corner (box[A], box[Y]) of the box
; BP: A the x field (BX_LEFT, BX_RIGHT), Y the y field (BX_TOP,
; BX_BOTTOM).
corner:
        phy
        tay
        lda (BP),y
        sta M_A
        iny
        lda (BP),y
        sta M_A+1
        ply
        lda (BP),y
        sta M_A+2
        iny
        lda (BP),y
        sta M_A+3
        lda VIEWX+2
        sta M_B
        lda VIEWX+3
        sta M_B+1
        lda VIEWY+2
        sta M_B+2
        lda VIEWY+3
        sta M_B+3
        jmp pta16

; viewcorner: C = the view's map unit is a corner of the box BP.
viewcorner:
        ldy #BX_LEFT
        jsr @eqx
        beq @xok
        ldy #BX_RIGHT
        jsr @eqx
        bne @no
@xok:   ldy #BX_TOP
        jsr @eqy
        beq @yes
        ldy #BX_BOTTOM
        jsr @eqy
        beq @yes
@no:    clc
        rts
@yes:   sec
        rts
@eqx:   lda VIEWX+2
        cmp (BP),y
        bne :+
        iny
        lda VIEWX+3
        cmp (BP),y
:       rts
@eqy:   lda VIEWY+2
        cmp (BP),y
        bne :+
        iny
        lda VIEWY+3
        cmp (BP),y
:       rts

; vtox_of: A = viewangletox[(A:X) >> 3], A the high byte.
vtox_of:
        stx T0+2
        lsr a
        ror T0+2
        lsr a
        ror T0+2
        lsr a
        ror T0+2
        ldx T0+2
        jmp ax_vtox

; ===========================================================================
; nr_scan0, nr_scan1: R_ScanCols(X, BS_LAST, 0 or 1)
; ===========================================================================
; Upstream tests four columns at a time and reads past the range; with
; SOLIDCOL's bytes 0 or 1 its result is the first such column, or
; BS_LAST.
nr_scan0:
        cpx BS_LAST
        bcs @last
@l:     lda SOLIDCOL,x
        beq @found
        inx
        cpx BS_LAST
        bcc @l
@last:  lda BS_LAST
        rts
@found: txa
        rts

nr_scan1:
        cpx BS_LAST
        bcs @last
@l:     lda SOLIDCOL,x
        bne @found
        inx
        cpx BS_LAST
        bcc @l
@last:  lda BS_LAST
        rts
@found: txa
        rts

; ===========================================================================
; nr_sub: R_Subsector(A:X), then rts (upstream's bspSub)
; ===========================================================================
nr_sub:
        sta FA_SRC              ; its record: SUBBASE + 4 n
        stx FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        asl FA_SRC
        rol FA_SRC+1
        clc                     ; (SUBBASE page aligned)
        lda FA_SRC+1
        adc #>SUBBASE
        sta FA_SRC+1
        lda #<SUBREC
        sta FA_DST
        lda #>SUBREC
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #SUB_SIZE
        sta FA_N
        jsr far_get
        lda SUBREC+SUB_SECTOR
        sta SC_CUR
        cmp CN_LSEC             ; the sector of the subsector before: the
        beq @segs               ;   same plane colours, its things
        sta CN_LSEC
        jsr nr_planes           ; its sector, light and plane colours
        lda FSEC+SEC_VALID      ; R_AddSprites when the things of the
        cmp VALIDCOUNT          ;   sector are not in the frame yet:
        bne @stamp              ;   sec->validcount = validcount
        lda FSEC+SEC_VALID+1
        cmp VALIDCOUNT+1
        beq @segs
@stamp: lda VALIDCOUNT
        sta FSEC+SEC_VALID
        lda VALIDCOUNT+1
        sta FSEC+SEC_VALID+1
        lda SC_CUR              ; SECBASE + 16 sector + SEC_VALID
        stz FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        asl a
        rol FA_DST+1
        clc
        adc #<(SECBASE + SEC_VALID)
        sta FA_DST
        lda FA_DST+1
        adc #>(SECBASE + SEC_VALID)
        sta FA_DST+1
        lda #<(FSEC + SEC_VALID)
        sta FA_SRC
        lda #>(FSEC + SEC_VALID)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #2
        sta FA_N
        jsr far_put
        MARK 11
        jsr nr_addsprites
        MARK 3
@segs:  lda SUBREC+SUB_COUNT    ; (R_LoadSkyPatch: nothing natively)
        bne :+
        rts
:       sta BS_LEFT
        lda SUBREC+SUB_FIRST
        sta BS_SUBN
        lda SUBREC+SUB_FIRST+1
        sta BS_SUBN+1

@batch: lda BS_LEFT             ; the next segs, at most SEGBUF_SEGS
        cmp #SEGBUF_SEGS
        bcc :+
        lda #SEGBUF_SEGS
:       sta BS_BATCH
        asl a                   ; * 24 bytes
        asl a
        asl a
        sta T0
        asl a
        clc
        adc T0
        sta FA_N
        lda BS_SUBN             ; SEGBASE + 24 n: 8 n + 16 n
        sta T0
        lda BS_SUBN+1
        sta T0+1
        asl T0
        rol T0+1
        asl T0
        rol T0+1
        asl T0
        rol T0+1
        lda T0
        asl a
        sta FA_SRC
        lda T0+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc T0
        sta FA_SRC
        lda FA_SRC+1
        adc T0+1
        sta FA_SRC+1
        clc                     ; (SEGBASE page aligned)
        lda FA_SRC+1
        adc #>SEGBASE
        sta FA_SRC+1
        lda #<SEGBUF
        sta FA_DST
        lda #>SEGBUF
        sta FA_DST+1
        lda #LVSEG
        sta FA_BANK
        jsr far_get
        jsr vgather             ; their vertices' angles and stamps
        stz BS_K
        lda #<SEGBUF
        sta SEGR
        lda #>SEGBUF
        sta SEGR+1
@seg:   clc                     ; BS_SEG = the seg's number
        lda BS_SUBN
        adc BS_K
        sta BS_SEG
        lda BS_SUBN+1
        adc #0
        sta BS_SEG+1
        jsr nr_seg
        clc
        lda SEGR
        adc #SEG_SIZE
        sta SEGR
        bcc :+
        inc SEGR+1
:       inc BS_K
        lda BS_K
        cmp BS_BATCH
        bne @seg
        jsr far_vput            ; the new angles back
        clc
        lda BS_SUBN
        adc BS_BATCH
        sta BS_SUBN
        bcc :+
        inc BS_SUBN+1
:       sec
        lda BS_LEFT
        sbc BS_BATCH
        sta BS_LEFT
        beq :+
        jmp @batch
:       rts

; nr_addsprites: R_AddSprites of the subsector's sector, deferred
; (milestone 8, RENDER-MASKED.md 0.3 row 1): the walk reads nothing the
; projection makes, so the sector (SC_CUR) goes on the list SPRSEC (aux 0,
; one RAMWRT window) and the masked phase projects the listed sectors'
; things in this order. SPRN + 1 (at most 254 sectors, each once a frame:
; its validcount stamp). Changes A, X.
nr_addsprites:
        ldx SPRN
        lda SC_CUR
        sta RAMWRTON
        sta SPRSEC,x
        sta RAMWRTOFF
        inc SPRN
        rts

; vgather: the native vertex numbers of the batch's segs (v1 at 2k, v2 at
; 2k + 1) into the gather, then their angles and stamps (far_vgather).
vgather:
        lda #<SEGBUF
        sta BP
        lda #>SEGBUF
        sta BP+1
        lda BS_BATCH
        sta T0+3
        ldx #0
@l:     ldy #SEG_V1N
        lda (BP),y
        sta vg_vlo,x
        iny
        lda (BP),y
        sta vg_vhi,x
        inx
        ldy #SEG_V2N
        lda (BP),y
        sta vg_vlo,x
        iny
        lda (BP),y
        sta vg_vhi,x
        inx
        clc
        lda BP
        adc #SEG_SIZE
        sta BP
        bcc :+
        inc BP+1
:       dec T0+3
        bne @l
        stx vg_n
        jmp far_vgather

; vangle: A (low), Y (high) = the angle of entry X of the gather, the end
; of seg SEGR at offset T0+2 (SEG_V1X or SEG_V2X): the cached one when its
; stamp is this frame's, else R_PointToAngle16 of the point (upstream's
; vtxAngle), then cached in every entry of that vertex, marked for
; far_vput. Changes A, X, Y, T0, T0+1, T0+3, the math block.
vangle:
        lda vg_s,x
        cmp VA_STAMP
        bne @new
        lda vg_al,x
        ldy vg_ah,x
        rts
@new:   stx T0+3
        ldy T0+2
        lda (SEGR),y
        sta M_A
        iny
        lda (SEGR),y
        sta M_A+1
        iny
        lda (SEGR),y
        sta M_A+2
        iny
        lda (SEGR),y
        sta M_A+3
        lda VIEWX+2
        sta M_B
        lda VIEWX+3
        sta M_B+1
        lda VIEWY+2
        sta M_B+2
        lda VIEWY+3
        sta M_B+3
        jsr pta16
        inc VA_COUNT            ; (the count of ref816's vtxAngle calls)
        bne :+
        inc VA_COUNT+1
:       ldx T0+3
        lda #1
        sta vg_d,x
        lda vg_vlo,x
        sta T0
        lda vg_vhi,x
        sta T0+1
        ldx #0
@each:  lda vg_vlo,x
        cmp T0
        bne @next
        lda vg_vhi,x
        cmp T0+1
        bne @next
        lda M_R
        sta vg_al,x
        lda M_R+1
        sta vg_ah,x
        lda VA_STAMP
        sta vg_s,x
@next:  inx
        cpx vg_n
        bne @each
        lda M_R
        ldy M_R+1
        rts

; ===========================================================================
; nr_seg: R_AddLine of the seg SEGR (entries 2 BS_K, 2 BS_K + 1 of the
; gather), and R_ClipWallSegment of its columns (upstream's segLoop and
; clipWall, r_bsp65.s:771-956)
; ===========================================================================
nr_seg:
        ldy #SEG_ANGLE          ; along an axis, with the map unit of the
        lda (SEGR),y            ;   view 2 or more behind the line: the
        bne @full               ;   back side, which the angles would
        iny                     ;   find
        lda (SEGR),y
        and #$3F
        bne @full
        lda (SEGR),y            ; bit 6: x (0) or y (1); bit 7: the sign
        and #$40
        bne @ay
        ldy #SEG_V1X            ; n = (1, 0), (-1, 0): x
        lda VIEWX+2
        sta T0
        lda VIEWX+3
        sta T0+1
        bra @axis
@ay:    ldy #SEG_V1Y            ; n = (0, 1), (0, -1): y
        lda VIEWY+2
        sta T0
        lda VIEWY+3
        sta T0+1
@axis:  phy
        ldy #SEG_ANGLE+1
        lda (SEGR),y
        ply
        asl a
        bcs @minus
        sec                     ; + : view - v1 - 2 >= 0
        lda T0
        sbc (SEGR),y
        sta T0
        iny
        lda T0+1
        sbc (SEGR),y
        bra @minus2
@minus: sec                     ; - : v1 - view - 2 >= 0
        lda (SEGR),y
        sbc T0
        sta T0
        iny
        lda (SEGR),y
        sbc T0+1
@minus2:
        bvs @full
        tay
        sec
        lda T0
        sbc #2
        tya
        sbc #0
        bvs @full
        bmi @full
        rts

@full:  lda BS_K                ; angle2 = R_PointToAngle16(v2)
        asl a
        ora #1
        tax
        lda #SEG_V2X
        sta T0+2
        jsr vangle
        sta BS_A1
        sty BS_A1+1
        lda BS_K                ; angle1 = R_PointToAngle16(v1)
        asl a
        tax
        lda #SEG_V1X
        sta T0+2
        jsr vangle
        sta T0
        sty T0+1
        sec                     ; span = angle1 - angle2 >= ANG180: the
        lda T0                  ;   back side
        sbc BS_A1
        sta BS_SPAN
        lda T0+1
        sbc BS_A1+1
        sta BS_SPAN+1
        bpl :+
        rts
:       sec                     ; tspan = angle1 - viewangle16 + clipangle
        lda T0
        sbc VIEWA16
        tax
        lda T0+1
        sbc VIEWA16+1
        tay
        clc
        txa
        adc #<CLIPANGLE
        sta BS_T1
        tya
        adc #>CLIPANGLE
        sta BS_T1+1
        lda BS_T1               ; tspan > 2 clipangle:
        cmp #<(C2 + 1)
        lda BS_T1+1
        sbc #>(C2 + 1)
        bcc @t1ok
        sec                     ;   tspan - 2 clipangle >= span: off the
        lda BS_T1               ;   left edge
        sbc #<C2
        tax
        lda BS_T1+1
        sbc #>C2
        tay
        txa
        cmp BS_SPAN
        tya
        sbc BS_SPAN+1
        bcc :+
        rts
:       lda #<C2                ;   else angle1 = clipangle
        sta BS_T1
        lda #>C2
        sta BS_T1+1
@t1ok:  clc                     ; tspan = clipangle - (angle2 -
        lda VIEWA16             ;   viewangle16)
        adc #<CLIPANGLE
        tax
        lda VIEWA16+1
        adc #>CLIPANGLE
        tay
        sec
        txa
        sbc BS_A1
        sta T0
        tya
        sbc BS_A1+1
        sta T0+1
        lda T0                  ; > 2 clipangle:
        cmp #<(C2 + 1)
        lda T0+1
        sbc #>(C2 + 1)
        bcc @t2ok
        sec
        lda T0
        sbc #<C2
        tax
        lda T0+1
        sbc #>C2
        tay
        txa
        cmp BS_SPAN
        tya
        sbc BS_SPAN+1
        bcc :+
        rts
:       lda #<C2                ;   angle2 = -clipangle
        sta T0
        lda #>C2
        sta T0+1
@t2ok:  sec                     ; x2 = viewangletox(angle2): ($3FC8 -
        lda #<($4000 + CLIPANGLE - 8 * VIEWANGLETOXMAX)  ; tspan) >> 3
        sbc T0
        tax
        lda #>($4000 + CLIPANGLE - 8 * VIEWANGLETOXMAX)
        sbc T0+1
        bmi :+
        jsr vtox_of
        bra :++
:       lda #VIEWWIDTH
:       sta BS_LAST
        sec                     ; x1 = viewangletox(angle1): (tspan - $48)
        lda BS_T1               ;   >> 3
        sbc #<(8 * VIEWANGLETOXMAX + CLIPANGLE - $4000)
        tax
        lda BS_T1+1
        sbc #>(8 * VIEWANGLETOXMAX + CLIPANGLE - $4000)
        bcc :+
        jsr vtox_of
        bra :++
:       lda #VIEWWIDTH
:       cmp BS_LAST             ; x1 >= x2: no pixel crossed
        bcc :+
        rts
:       sta BS_FIRST

; clipwall: R_ClipWallSegment(BS_FIRST, BS_LAST, 0) (r_bsp65.s:894-924).
; Upstream's render flags of the lines are never set there, so none is
; tested; nr_storewall marks the solid columns.
clipwall:
        ldx BS_FIRST            ; while (first < last)
        cpx BS_LAST
        bcs @done
        lda SOLIDCOL,x
        beq @open
        jsr nr_scan0            ; first = R_ScanCols(first, last, 0)
        sta BS_FIRST
        bra clipwall
@open:  jsr nr_scan1            ; to = R_ScanCols(first, last, 1)
        sta BS_TO
        MARK 9
        dec a                   ; R_StoreWallRange(first, to - 1)
        tax
        lda BS_FIRST
        jsr nr_storewall
        MARK 3
        lda BS_F                ; the first open column moves only when
        cmp BS_FIRST            ;   this wall began at it
        bne @next
        lda BS_LAST
        pha
        lda #VIEWWIDTH
        sta BS_LAST
        ldx BS_F
        jsr nr_scan0
        sta BS_F
        pla
        sta BS_LAST
@next:  lda BS_TO               ; first = to
        sta BS_FIRST
        bra clipwall
@done:  rts

; ---------------------------------------------------------------------------
; checkBox's tables, by case k (upstream's BXR0 and BXLIM, r_bsp65.s:374-
; 380, by rtables.py from the reference's RAM: r0 - clipangle and
; $10000 - 2 clipangle - len + 1 of the case's arc), and the corners of
; each case (the fields of the first and the second corner: box0 right
; top, left bottom; box1 right top, left top; box2 right bottom, left top;
; box4 left top, left bottom; box6 right bottom, right top; box8 left
; top, right bottom; box9 left bottom, right bottom; box10 left bottom,
; right top).
; ---------------------------------------------------------------------------
BXR0LO:  .incbin "bxr0lo.bin"
BXR0HI:  .incbin "bxr0hi.bin"
BXLIMLO: .incbin "bxlimlo.bin"
BXLIMHI: .incbin "bxlimhi.bin"
C1X:    .byte BX_RIGHT, BX_RIGHT, BX_RIGHT, BX_LEFT, 0
        .byte BX_RIGHT, BX_LEFT, BX_LEFT, BX_LEFT
C1Y:    .byte BX_TOP, BX_TOP, BX_BOTTOM, BX_TOP, 0
        .byte BX_BOTTOM, BX_TOP, BX_BOTTOM, BX_BOTTOM
C2X:    .byte BX_LEFT, BX_LEFT, BX_LEFT, BX_LEFT, 0
        .byte BX_RIGHT, BX_RIGHT, BX_RIGHT, BX_RIGHT
C2Y:    .byte BX_BOTTOM, BX_TOP, BX_TOP, BX_BOTTOM, 0
        .byte BX_TOP, BX_BOTTOM, BX_BOTTOM, BX_TOP
