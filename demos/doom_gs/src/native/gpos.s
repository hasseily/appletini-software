; gpos.s: the game core's things in the level (milestone 9, stage C;
; docs/LEVELS.md 2.4). A GPL-2 derivative of upstream's r_iigs65.s
; (R_PointInSubsector and its walk, shiftMul) and p_map65.s
; (P_SetThingPosition, P_CreateSecNodeList with lineBlocks, walkRange,
; PIT_GetSectors and P_AddSecnode, P_BoxOnLineSide's slanted case).
;
;   gp_pointsub   R_PointInSubsector(GC_X, GC_Y): GC_S = the subsector. The
;                 descent from the root through LVMAP's nodes with upstream's
;                 side test (whole parts when dx or dy is 0; the signs; else
;                 the low 32 bits of (y' >> 8) dx against (x' >> 8) dy); no
;                 grid and no last-point cache (neither changes a result)
;   gp_setpos     P_SetThingPosition of the mobj LW_MOB (slot GC_MO): its
;                 subsector; unless MF_NOSECTOR the head of its sector's
;                 thing list (LVMAP's head, RTHING's snext, the game part's
;                 sprev), then P_CreateSecNodeList; unless MF_NOBLOCKMAP the
;                 head of its block's list (LVG1's blocklinks), none off the
;                 map. GC_SEC = its subsector's sector
;   gp_secnodes   P_CreateSecNodeList: validcount + 1 (gv_inc); the block
;                 walk of the thing's box, x outer and y inner, each block's
;                 list after its first entry, each line not stamped with
;                 validcount stamped and tested (the box's edges in whole
;                 units, the corners of a slanted line), the crossed lines'
;                 front and back sectors added (P_AddSecnode); then the
;                 thing's own sector; its node list the new ones, the last
;                 first
;
; Every record of the level comes through far_get (g_get) into W, every
; write goes through far_put (g_put): LVMAP's nodes, subsectors and
; sectors, LVG0's lines, LVG1's sectors' game part and blocklinks, LVG2's
; blockmap, ZONE1's nodes, MOBJA's links. The lines' front and back
; sectors are lg_prep's tables in W (LW_LFRONT, LW_LBACK: the front twice
; for a one-sided line, upstream's LNSEC).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gp_pointsub, gp_setpos, gp_secnodes
        .import g_get, g_put, g_put2, gt_moaddr, gt_nodetake, sn_addr
        .import gv_inc, ld_stop, mul32, mul8

        .assert LW_LBACK = LW_LFRONT + LINE_ROOM, error, "the lines' sectors"

MO_A    = LW_MOB + MO_SIZE      ; the mobj's game parts in W
MO_B    = LW_MOB + 2 * MO_SIZE

        .segment "LOADW"

; ---------------------------------------------------------------------------
; gp_pointsub: GC_S = R_PointInSubsector(GC_X, GC_Y). Changes A, X, Y,
; GC_T, GC_V, GC_W, GS_L, GS_K, the math's block, FA_*.
; ---------------------------------------------------------------------------
gp_pointsub:
        lda LVCOUNT2+6          ; no nodes: subsector 0
        ora LVCOUNT2+7
        bne @root
        stz GC_S
        stz GC_S+1
        rts
@root:  sec                     ; the root: numnodes - 1
        lda LVCOUNT2+6
        sbc #1
        sta GC_T
        lda LVCOUNT2+7
        sbc #0
        sta GC_T+1
@node:  lda GC_T                ; the node: NODEBASE + 32 n
        sta FA_SRC
        lda GC_T+1
        ldx #5
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<NODEBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>NODEBASE
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #<LW_NODEB
        ldx #>LW_NODEB
        ldy #NODE_CH1 + 2
        jsr g_get
        lda GC_X                ; GC_V = x - (node.x << 16), GC_W = y -
        sta GC_V                ;   (node.y << 16)
        lda GC_X+1
        sta GC_V+1
        sec
        lda GC_X+2
        sbc LW_NODEB + NODE_X
        sta GC_V+2
        lda GC_X+3
        sbc LW_NODEB + NODE_X + 1
        sta GC_V+3
        lda GC_Y
        sta GC_W
        lda GC_Y+1
        sta GC_W+1
        sec
        lda GC_Y+2
        sbc LW_NODEB + NODE_Y
        sta GC_W+2
        lda GC_Y+3
        sbc LW_NODEB + NODE_Y + 1
        sta GC_W+3
        lda LW_NODEB + NODE_DX
        ora LW_NODEB + NODE_DX + 1
        beq @dx0
        lda LW_NODEB + NODE_DY
        ora LW_NODEB + NODE_DY + 1
        beq @dy0
        lda LW_NODEB + NODE_DY + 1      ; the signs decide: (dy ^ dx ^ x' ^
        eor LW_NODEB + NODE_DX + 1      ;   y') < 0, then (dy ^ x') < 0: 1
        eor GC_V+3
        eor GC_W+3
        bpl @prod
        lda LW_NODEB + NODE_DY + 1
        eor GC_V+3
        bmi @one
        bra @zero
@prod:  lda LW_NODEB + NODE_DX          ; L = (y' >> 8) dx, R = (x' >> 8) dy:
        sta GS_K                        ;   L >= R: 1
        lda LW_NODEB + NODE_DX + 1
        sta GS_K+1
        ldx #GC_W
        jsr shiftmul
        ldx #3
:       lda M_R,x
        sta GS_L,x
        dex
        bpl :-
        lda LW_NODEB + NODE_DY
        sta GS_K
        lda LW_NODEB + NODE_DY + 1
        sta GS_K+1
        ldx #GC_V
        jsr shiftmul
        jsr l_ge_r
        bcc @zero
        bra @one
@dx0:   lda LW_NODEB + NODE_X           ; dx 0: node.x < x.hi ? dy < 0
        cmp GC_X+2                      ;   : dy > 0
        lda LW_NODEB + NODE_X + 1
        sbc GC_X+3
        bvc :+
        eor #$80
:       bmi @dx0lt
        lda LW_NODEB + NODE_DY + 1
        bmi @zero
        ora LW_NODEB + NODE_DY
        beq @zero
        bra @one
@dx0lt: lda LW_NODEB + NODE_DY + 1
        bmi @one
        bra @zero
@dy0:   lda LW_NODEB + NODE_Y           ; dy 0: node.y < y.hi ? dx > 0
        cmp GC_Y+2                      ;   : dx < 0
        lda LW_NODEB + NODE_Y + 1
        sbc GC_Y+3
        bvc :+
        eor #$80
:       bmi @dy0lt
        lda LW_NODEB + NODE_DX + 1
        bmi @one
        bra @zero
@dy0lt: lda LW_NODEB + NODE_DX + 1
        bmi @zero
@one:   ldx #NODE_CH1
        bra @child
@zero:  ldx #NODE_CH0
@child: lda LW_NODEB + 1,x
        bmi @leaf
        sta GC_T+1
        lda LW_NODEB,x
        sta GC_T
        jmp @node
@leaf:  and #$7F
        sta GC_S+1
        lda LW_NODEB,x
        sta GC_S
        rts

; shiftmul: M_R = the low 32 bits of (v >> 8) * GS_K, v the fixed_t at zero
; page X, both signed (upstream's shiftMul and posMul: v's bits 8-31, its
; byte 3 signed). Changes A, X, Y, the math's block.
shiftmul:
        lda 1,x
        sta M_A
        lda 2,x
        sta M_A+1
        lda 3,x
        sta M_A+2
        jsr sign
        sta M_A+3
        lda GS_K
        sta M_B
        lda GS_K+1
        sta M_B+1
        jsr sign
        sta M_B+2
        sta M_B+3
        jmp mul32
; sign: A = $FF when A is negative, else 0
sign:   asl a
        lda #0
        bcc :+
        lda #$FF
:       rts

; l_ge_r: carry set when GS_L >= M_R, signed 32-bit (the sign of the
; 33-bit difference). Changes A.
l_ge_r: sec
        lda GS_L
        sbc M_R
        lda GS_L+1
        sbc M_R+1
        lda GS_L+2
        sbc M_R+2
        lda GS_L+3
        sbc M_R+3
        bvc :+
        eor #$80
:       asl a                   ; C = the sign: 1 when L < R
        bcs :+
        sec
        rts
:       clc
        rts

; ---------------------------------------------------------------------------
; gp_setpos: P_SetThingPosition of the mobj LW_MOB, slot GC_MO. Changes
; everything but GC_MO and LW_MOB's other fields.
; ---------------------------------------------------------------------------
gp_setpos:
        ldx #3
:       lda LW_MOB + TH_X,x
        sta GC_X,x
        lda LW_MOB + TH_Y,x
        sta GC_Y,x
        dex
        bpl :-
        jsr gp_pointsub
        lda GC_S
        sta MO_A + MA_SUBSEC
        lda GC_S+1
        sta MO_A + MA_SUBSEC + 1
        lda GC_S                ; GC_SEC = its sector: SUBBASE + 4 s
        sta FA_SRC
        lda GC_S+1
        asl FA_SRC
        rol a
        asl FA_SRC
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<(SUBBASE + SUB_SECTOR)
        sta FA_SRC
        lda FA_SRC+1
        adc #>(SUBBASE + SUB_SECTOR)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #<GC_SEC
        ldx #>GC_SEC
        ldy #1
        jsr g_get
        lda MO_B + MB_FLAGS
        and #U_MF_NOSECTOR
        bne @block
        jsr sec_head            ; the head of its sector's list
        lda #<GC_H
        ldx #>GC_H
        ldy #2
        jsr g_get
        lda GC_H
        sta LW_MOB + TH_SNEXT
        lda GC_H+1
        sta LW_MOB + TH_SNEXT + 1
        lda #$FF
        sta MO_A + MA_SPREV
        sta MO_A + MA_SPREV + 1
        lda #MA_SPREV           ; the old head's sprev = the thing
        jsr link_prev
        jsr sec_head            ; the head = the thing
        lda FA_SRC
        sta FA_DST
        lda FA_SRC+1
        sta FA_DST+1
        lda #<GC_MO
        ldx #>GC_MO
        jsr g_put2
        jsr gp_secnodes
@block: lda MO_B + MB_FLAGS
        and #U_MF_NOBLOCKMAP
        jne @done
        sec                     ; blocky = (y - orgy) >> 23, a byte, its
        lda LW_MOB + TH_Y + 2   ;   sign in the carry
        sbc G_BMORGY+2
        tax
        lda LW_MOB + TH_Y + 3
        sbc G_BMORGY+3
        jsr blk7
        jcs @off
        cmp G_BMH
        jcs @off
        sta GS_BY
        sec                     ; blockx
        lda LW_MOB + TH_X + 2
        sbc G_BMORGX+2
        tax
        lda LW_MOB + TH_X + 3
        sbc G_BMORGX+3
        jsr blk7
        jcs @off
        cmp G_BMW
        jcs @off
        sta GS_BX
        jsr blk_index           ; GC_T = blocky * width + blockx
        asl GC_T                ; its blocklink: BLINKS + 2 b
        rol GC_T+1
        clc
        lda GC_T
        adc LW_HDR + LHV_BLINKS
        sta GC_T
        sta FA_SRC
        lda GC_T+1
        adc LW_HDR + LHV_BLINKS + 1
        sta GC_T+1
        sta FA_SRC+1
        lda #LVG1
        sta FA_BANK
        lda #<GC_H
        ldx #>GC_H
        ldy #2
        jsr g_get
        lda GC_H
        sta MO_A + MA_BNEXT
        lda GC_H+1
        sta MO_A + MA_BNEXT + 1
        lda #$FF
        sta MO_A + MA_BPREV
        sta MO_A + MA_BPREV + 1
        lda #MA_BPREV
        jsr link_prev
        lda #LVG1               ; the head = the thing
        sta FA_BANK
        lda GC_T
        sta FA_DST
        lda GC_T+1
        sta FA_DST+1
        lda #<GC_MO
        ldx #>GC_MO
        jmp g_put2
@off:   lda #$FF                ; off the map: in no block
        sta MO_A + MA_BNEXT
        sta MO_A + MA_BNEXT + 1
        sta MO_A + MA_BPREV
        sta MO_A + MA_BPREV + 1
@done:  rts

; sec_head: FA_BANK:FA_SRC = the thing list head of sector GC_SEC (LVMAP)
sec_head:
        lda GC_SEC
        stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        clc
        adc #<(SECBASE + SEC_THINGS)
        sta FA_SRC
        lda FA_SRC+1
        adc #>(SECBASE + SEC_THINGS)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        rts
        .assert SEC_SIZE = 16, error, "a sector's render record"

; link_prev: when the old head GC_H is a thing, its link at offset A of
; game part A (sprev, bprev) = GC_MO
link_prev:
        ldx GC_H+1
        cpx #$FF
        beq @none
        pha
        lda GC_H
        jsr gt_moaddr
        pla
        clc
        adc GC_P
        sta FA_DST
        lda GC_P+1
        adc #0
        sta FA_DST+1
        lda #MOBJA
        sta FA_BANK
        lda #<GC_MO
        ldx #>GC_MO
        jmp g_put2
@none:  rts

; blk7: A = (d >> 7) & $FF of the word d = A:X (A its high byte), C its sign
blk7:   sta GC_P
        txa
        asl a
        lda GC_P
        rol a
        rts

; blk_index: GC_T = GS_BY * G_BMW + GS_BX
blk_index:
        lda GS_BY
        ldy G_BMW
        jsr mul8
        clc
        lda M_R
        adc GS_BX
        sta GC_T
        lda M_R+1
        adc #0
        sta GC_T+1
        rts

; ---------------------------------------------------------------------------
; gp_secnodes: P_CreateSecNodeList(GC_MO) for the mobj LW_MOB (sector
; GC_SEC). Changes everything but GC_MO and LW_MOB's other fields.
; ---------------------------------------------------------------------------
gp_secnodes:
        jsr gv_inc
        stz GS_NSEC
        ldx #2                  ; the box: the low words the thing's, the
@box:   lda LW_MOB + TH_X,x     ;   high words its x, y +- its radius
        sta GS_RIGHT,x          ;   (whole units below 256)
        sta GS_LEFT,x
        lda LW_MOB + TH_Y,x
        sta GS_TOP,x
        sta GS_BOT,x
        dex
        bpl @box
        clc
        lda LW_MOB + TH_X + 2
        adc MO_B + MB_RADIUS + 2
        sta GS_RIGHT+2
        lda LW_MOB + TH_X + 3
        adc MO_B + MB_RADIUS + 3
        sta GS_RIGHT+3
        sec
        lda LW_MOB + TH_X + 2
        sbc MO_B + MB_RADIUS + 2
        sta GS_LEFT+2
        lda LW_MOB + TH_X + 3
        sbc MO_B + MB_RADIUS + 3
        sta GS_LEFT+3
        clc
        lda LW_MOB + TH_Y + 2
        adc MO_B + MB_RADIUS + 2
        sta GS_TOP+2
        lda LW_MOB + TH_Y + 3
        adc MO_B + MB_RADIUS + 3
        sta GS_TOP+3
        sec
        lda LW_MOB + TH_Y + 2
        sbc MO_B + MB_RADIUS + 2
        sta GS_BOT+2
        lda LW_MOB + TH_Y + 3
        sbc MO_B + MB_RADIUS + 3
        sta GS_BOT+3
        lda GS_RIGHT            ; the walk's edges in whole units: right
        ora GS_RIGHT+1          ;   and top less 1 when their low word is
        cmp #1                  ;   0; an edge of -32768.0 overflows: the
        lda GS_RIGHT+2          ;   bottom 32767 then takes every line
        sbc #0                  ;   out
        sta GS_RF
        lda GS_RIGHT+3
        sbc #0
        sta GS_RF+1
        bvs @flip
        lda GS_TOP
        ora GS_TOP+1
        cmp #1
        lda GS_TOP+2
        sbc #0
        sta GS_TF
        lda GS_TOP+3
        sbc #0
        sta GS_TF+1
        bvs @flip
        lda GS_LEFT+2
        sta GS_LH
        lda GS_LEFT+3
        sta GS_LH+1
        lda GS_BOT+2
        sta GS_BH
        lda GS_BOT+3
        sta GS_BH+1
        bra @range
@flip:  lda #$FF
        sta GS_BH
        lda #$7F
        sta GS_BH+1
@range: jsr walkrange
        bcs @own
        lda GS_XL               ; x outer, y inner
        sta GS_BX
@col:   lda GS_YL
        sta GS_BY
@blk:   jsr walkblock
        lda GS_BY
        cmp GS_YH
        beq :+
        inc GS_BY
        bra @blk
:       lda GS_BX
        cmp GS_XH
        beq @own
        inc GS_BX
        bra @col
@own:   lda GC_SEC              ; the thing's own sector
        jsr addsec
        lda G_SECLIST           ; its list; _s_sector_list none
        sta MO_A + MA_TOUCH
        lda G_SECLIST+1
        sta MO_A + MA_TOUCH + 1
        lda #$FF
        sta G_SECLIST
        sta G_SECLIST+1
        rts

; walkrange: the blocks of the box, clamped to the map (walkRange with no
; growth): GS_XL..GS_XH, GS_YL..GS_YH; C set: none
walkrange:
        sec                     ; xh: (right - orgx) >> 23, clamped
        lda GS_RIGHT+2
        sbc G_BMORGX+2
        tax
        lda GS_RIGHT+3
        sbc G_BMORGX+3
        jsr blk7
        bcs @none
        cmp G_BMW
        bcc :+
        lda G_BMW
        dec a
:       sta GS_XH
        sec                     ; xl: left of the map: 0
        lda GS_LEFT+2
        sbc G_BMORGX+2
        tax
        lda GS_LEFT+3
        sbc G_BMORGX+3
        jsr blk7
        bcc :+
        lda #0
:       cmp G_BMW
        bcs @none
        sta GS_XL
        sec                     ; yh
        lda GS_TOP+2
        sbc G_BMORGY+2
        tax
        lda GS_TOP+3
        sbc G_BMORGY+3
        jsr blk7
        bcs @none
        cmp G_BMH
        bcc :+
        lda G_BMH
        dec a
:       sta GS_YH
        sec                     ; yl
        lda GS_BOT+2
        sbc G_BMORGY+2
        tax
        lda GS_BOT+3
        sbc G_BMORGY+3
        jsr blk7
        bcc :+
        lda #0
:       cmp G_BMH
        bcs @none
        sta GS_YL
        clc
        rts
@none:  sec
        rts

; walkblock: the lines of block GS_BX, GS_BY: its list in LVG2's blockmap
; (BLOCKMAP_AT + 2 * blockmap[block]), after its first entry, to a
; negative entry
walkblock:
        jsr blk_index
        asl GC_T                ; the offset: the lump's word 4 + block
        rol GC_T+1
        clc
        lda GC_T
        adc #<(BLOCKMAP_AT + 8)
        sta FA_SRC
        lda GC_T+1
        adc #>(BLOCKMAP_AT + 8)
        sta FA_SRC+1
        lda #LVG2
        sta FA_BANK
        lda #<GS_LIST
        ldx #>GS_LIST
        ldy #2
        jsr g_get
        asl GS_LIST             ; the list, after its first entry
        rol GS_LIST+1
        clc
        lda GS_LIST
        adc #<(BLOCKMAP_AT + 2)
        sta GS_LIST
        lda GS_LIST+1
        adc #>(BLOCKMAP_AT + 2)
        sta GS_LIST+1
@entry: lda #LVG2
        sta FA_BANK
        lda GS_LIST
        sta FA_SRC
        lda GS_LIST+1
        sta FA_SRC+1
        lda #<GS_LN
        ldx #>GS_LN
        ldy #2
        jsr g_get
        lda GS_LN+1
        bmi @done
        jsr walkline
        clc
        lda GS_LIST
        adc #2
        sta GS_LIST
        bcc @entry
        inc GS_LIST+1
        bra @entry
@done:  rts

; walkline: line GS_LN of the walk: none if stamped with validcount; else
; stamped, the box's edges tested, a slanted line's corners, and the
; crossed line's sectors added
walkline:
        lda GS_LN               ; its record: LINE_BASE + 32 n
        sta GC_P
        lda GS_LN+1
        ldx #5
:       asl GC_P
        rol a
        dex
        bne :-
        sta GC_P+1
        clc
        lda GC_P
        adc #<LINE_BASE
        sta GC_P
        sta FA_SRC
        lda GC_P+1
        adc #>LINE_BASE
        sta GC_P+1
        sta FA_SRC+1
        lda #LVG0
        sta FA_BANK
        lda #<LW_LINEB
        ldx #>LW_LINEB
        ldy #LN_VALID + 2
        jsr g_get
        lda LW_LINEB + LN_VALID
        cmp G_VALID
        bne @test
        lda LW_LINEB + LN_VALID + 1
        cmp G_VALID+1
        bne @test
        rts
@test:  lda GS_BH               ; bottom >= bbox[top]: out
        cmp LW_LINEB + LN_TOP
        lda GS_BH+1
        sbc LW_LINEB + LN_TOP + 1
        bvc :+
        eor #$80
:       bpl stamp
        lda GS_TF               ; top <= bbox[bottom]: out
        cmp LW_LINEB + LN_BOTTOM
        lda GS_TF+1
        sbc LW_LINEB + LN_BOTTOM + 1
        bvc :+
        eor #$80
:       bmi stamp
        lda GS_RF               ; right <= bbox[left]: out
        cmp LW_LINEB + LN_LEFT
        lda GS_RF+1
        sbc LW_LINEB + LN_LEFT + 1
        bvc :+
        eor #$80
:       bmi stamp
        lda GS_LH               ; left >= bbox[right]: out
        cmp LW_LINEB + LN_RIGHT
        lda GS_LH+1
        sbc LW_LINEB + LN_RIGHT + 1
        bvc :+
        eor #$80
:       bpl stamp
        jsr stamp
        lda LW_LINEB + LN_SLOPE ; a slanted line: its corners on one side:
        cmp #U_ST_POSITIVE      ;   out
        bcc @cross
        jsr corners
        bne @cross
        rts
@cross: clc                     ; its front and back sectors
        lda GS_LN
        adc #<LW_LFRONT
        sta GC_P
        lda GS_LN+1
        adc #>LW_LFRONT
        sta GC_P+1
        lda (GC_P)
        sta GS_SIDE
        clc
        lda GC_P+1
        adc #>LINE_ROOM
        sta GC_P+1
        lda (GC_P)
        sta GS_BP
        lda GS_SIDE
        jsr addsec
        lda GS_BP
        cmp GS_SIDE
        beq :+
        jmp addsec
:       rts
        .assert <LINE_ROOM = 0, error, "LINE_ROOM in pages"

; stamp: the line's validcount (its record at GC_P) = G_VALID
stamp:  clc
        lda GC_P
        adc #LN_VALID
        sta FA_DST
        lda GC_P+1
        adc #0
        sta FA_DST+1
        lda #LVG0
        sta FA_BANK
        lda #<G_VALID
        ldx #>G_VALID
        jmp g_put2

; corners: A = 0 when the box's two corners of a slanted line LW_LINEB are
; on one side of it (P_BoxOnLineSide != -1): positive, (right, bottom) and
; (left, top); negative, (left, bottom) and (right, top)
corners:
        lda LW_LINEB + LN_SLOPE
        cmp #U_ST_NEGATIVE
        beq @neg
        ldx #GS_RIGHT
        ldy #GS_BOT
        jsr side
        sta GS_CNT
        ldx #GS_LEFT
        ldy #GS_TOP
        bra @two
@neg:   ldx #GS_LEFT
        ldy #GS_BOT
        jsr side
        sta GS_CNT
        ldx #GS_RIGHT
        ldy #GS_TOP
@two:   jsr side
        eor GS_CNT
        rts

; side: A = P_PointOnLineSide(x at zero page X, y at zero page Y) of the
; slanted line LW_LINEB: 1 when ((y - (v1.y << 16)) >> 8) dx >= dy ((x -
; (v1.x << 16)) >> 8) (upstream's pointOnLineSide and posMul)
side:   lda 0,x                 ; GC_V = x - (v1.x << 16)
        sta GC_V
        lda 1,x
        sta GC_V+1
        sec
        lda 2,x
        sbc LW_LINEB + LN_V1X
        sta GC_V+2
        lda 3,x
        sbc LW_LINEB + LN_V1X + 1
        sta GC_V+3
        lda a:0,y               ; GC_W = y - (v1.y << 16)
        sta GC_W
        lda a:1,y
        sta GC_W+1
        sec
        lda a:2,y
        sbc LW_LINEB + LN_V1Y
        sta GC_W+2
        lda a:3,y
        sbc LW_LINEB + LN_V1Y + 1
        sta GC_W+3
        lda LW_LINEB + LN_DX    ; left = (GC_W >> 8) dx
        sta GS_K
        lda LW_LINEB + LN_DX + 1
        sta GS_K+1
        ldx #GC_W
        jsr shiftmul
        ldx #3
:       lda M_R,x
        sta GS_L,x
        dex
        bpl :-
        lda LW_LINEB + LN_DY    ; right = (GC_V >> 8) dy
        sta GS_K
        lda LW_LINEB + LN_DY + 1
        sta GS_K+1
        ldx #GC_V
        jsr shiftmul
        jsr l_ge_r              ; left >= right: 1
        lda #0
        rol a
        rts

; ---------------------------------------------------------------------------
; addsec: P_AddSecnode(sector A, GC_MO): a sector the thing has no node
; for yet gets a new one at the head of the thing's list (G_SECLIST) and
; of the sector's (its game record's TOUCH). Changes A, X, Y, GC_N, GC_P,
; GC_T, FA_*.
; ---------------------------------------------------------------------------
addsec: sta GS_S1
        ldx GS_NSEC             ; one already: nothing (its m_thing is the
:       dex                     ;   thing)
        bmi @new
        cmp LW_SECL,x
        bne :-
        rts
@new:   ldx GS_NSEC
        cpx #SECL_MAX
        bcc :+
        lda #LS_SECL
        jmp ld_stop
:       sta LW_SECL,x
        inc GS_NSEC
        jsr gt_nodetake         ; GC_N
        ldx #SN_SIZE - 1        ; its record
:       stz LW_SN,x
        dex
        bpl :-
        lda GS_S1
        sta LW_SN + SN_SECTOR
        lda GC_MO
        sta LW_SN + SN_THING
        lda GC_MO+1
        sta LW_SN + SN_THING + 1
        lda #$FF
        sta LW_SN + SN_TPREV
        sta LW_SN + SN_TPREV + 1
        sta LW_SN + SN_SPREV
        sta LW_SN + SN_SPREV + 1
        lda G_SECLIST
        sta LW_SN + SN_TNEXT
        lda G_SECLIST+1
        sta LW_SN + SN_TNEXT + 1
        jsr sg_touch            ; m_snext: the sector's head
        lda #<(LW_SN + SN_SNEXT)
        ldx #>(LW_SN + SN_SNEXT)
        ldy #2
        jsr g_get
        lda GC_N                ; the node
        ldx GC_N+1
        jsr sn_addr
        lda #ZONE1
        sta FA_BANK
        lda GC_P
        sta FA_DST
        lda GC_P+1
        sta FA_DST+1
        lda #<LW_SN
        ldx #>LW_SN
        ldy #SN_SIZE
        jsr g_put
        lda G_SECLIST           ; the thing's old head: m_tprev = the node
        ldx G_SECLIST+1
        ldy #SN_TPREV
        jsr node_prev
        lda LW_SN + SN_SNEXT    ; the sector's old head: m_sprev
        ldx LW_SN + SN_SNEXT + 1
        ldy #SN_SPREV
        jsr node_prev
        jsr sg_touch            ; the sector's head = the node
        lda GC_T
        sta FA_DST
        lda GC_T+1
        sta FA_DST+1
        lda #<GC_N
        ldx #>GC_N
        jsr g_put2
        lda GC_N                ; the thing's head = the node
        sta G_SECLIST
        lda GC_N+1
        sta G_SECLIST+1
        rts

; node_prev: node A:X (none: $FFFF) gets GC_N in its link at offset Y
node_prev:
        cpx #$FF
        beq @none
        phy
        jsr sn_addr
        pla
        clc
        adc GC_P
        sta FA_DST
        lda GC_P+1
        adc #0
        sta FA_DST+1
        lda #ZONE1
        sta FA_BANK
        lda #<GC_N
        ldx #>GC_N
        jmp g_put2
@none:  rts

; sg_touch: GC_T, FA_SRC = sector GS_S1's TOUCH in LVG1 (SECG_BASE + 32 s +
; SG_TOUCH), FA_BANK = LVG1
sg_touch:
        lda GS_S1
        stz GC_T+1
        ldx #5
:       asl a
        rol GC_T+1
        dex
        bne :-
        clc
        adc #<(SECG_BASE + SG_TOUCH)
        sta GC_T
        sta FA_SRC
        lda GC_T+1
        adc #>(SECG_BASE + SG_TOUCH)
        sta GC_T+1
        sta FA_SRC+1
        lda #LVG1
        sta FA_BANK
        rts
        .assert SECG_SIZE = 32, error, "a sector's game record"
