; Doom for the Appletini -- map geometry utilities, 6502 (docs/DESIGN.md
; section 9).
;
; The assembly twin of p_maputl.c (the C is the reference, compiled on the
; host). For C (cc65 __fastcall__), with p_local.h's prototypes:
;   P_PointOnLineSide, P_BoxOnLineSide, P_PointOnDivlineSide,
;   P_MakeDivline, P_InterceptVector, P_LineOpening, P_BlockX, P_BlockY,
;   P_UnsetThingPosition, P_SetThingPosition, P_LinkStatic, P_UnlinkStatic,
;   P_BlockLinesIterator, P_BlockThingsIterator, P_PathTraverse,
;   P_InitLineMarks, P_NewValidcount, P_LineChecked, P_AproxDistance,
;   and intercepts, intercept_p (trace and opentop.. are slots of W).
;
; For the other assembly modules (32-bit values in W, gwork.inc):
;   pols        side of (W_PLX, W_PLY) to the line gli -> A (0 front, 1 back)
;   bols        side of the box at (gpt) (top, bottom, left, right) to the
;               line gli -> A (0, 1, or $FF: both)
;   pods        side of (W_PDX, W_PDY) to the trace -> A
;   make_divline  the line gli -> W_IDLX..W_IDLDY
;   ivec        W_FR = P_InterceptVector(trace, W_IDL)
;   line_opening  of the line gli -> W_OPENTOP, _OPENBOTTOM, _OPENRANGE, _LOWFLOOR
;   set_pos / unset_pos   the actor gmo in the blockmap (and its sector)
;   blockx / blocky       the cell column/row of W[X] -> A (low), X (high)
;   thing_xy    the position of the thing at gth -> W_THX, W_THY
;   thing_radius  the radius of the thing A/X -> A
;   is_static   C set iff A/X (a thing) is a static
;   lines_iter / things_iter  P_Block*Iterator with bxl/bxh, byl/byh, bl_func
;   path_traverse  P_PathTraverse with W_PTX1..W_PTY2, pt_flags, pt_trav
;   aprox_dist  W_FR = P_AproxDistance(W_T0, W_T1) (both made absolute)
;   call_ax     jsr call_ax calls cf_ptr with A/X
;
; The line marks (vanilla's validcount) are one bit per line of the level
; in the arena, with the list of the bytes set since the last clear
; (MARKLIST of them, beyond which the whole bitset is cleared).
; P_BlockLinesIterator and P_PathTraverse are not reentrant (no callback of
; theirs iterates lines or traces); P_BlockThingsIterator is (P_ChangeSector's
; callback moves things): its state is on the 6502 stack.

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR

.import _P_ArenaAlloc, _numlines, _bmaporgx, _bmaporgy, _bmapwidth, _bmapheight
.import _blocklinks, _statics, _statics_end, _sec_floorh, _sec_ceilh, _mobjinfo
.import rpis, rp_x, rp_y, line_get, blk_lines, blk_cell, blk_pos, blk_buf, sqrlo, sqrhi
.import w_mov, w_add, w_sub, w_neg, w_abs, w_zero, w_cmp, w_sign, w_ldi, w_fix, w_sext
.import w_sar8, w_ldo, w_sto, w_ldp, w_stp, w_fixo, w_fixp, w_fixl, w_sextl, w_mul, w_div
.import w_tst, w_add3, w_sub3
.import popax, incsp4, incsp8, addysp
.if .defined(BANKED_GAME) .or .defined(FAR_BLOCKLINKS) .or .defined(FAR_MOBJINFO)
.globalzp far_src, far_dst, far_ptr, far_len
.import kjt_far_read, kjt_far_write
.endif

.export _P_PointOnLineSide, _P_BoxOnLineSide, _P_PointOnDivlineSide, _P_MakeDivline
.export _P_InterceptVector, _P_LineOpening, _P_BlockX, _P_BlockY
.export _P_UnsetThingPosition, _P_SetThingPosition, _P_LinkStatic, _P_UnlinkStatic
.export _P_BlockLinesIterator, _P_BlockThingsIterator, _P_PathTraverse
.export _P_InitLineMarks, _P_NewValidcount, _P_LineChecked, _P_AproxDistance
.export _intercepts, _intercept_p
.export pols, bols, pods, line_opening, set_pos, unset_pos, blockx, blocky
.export _P_ThingRadius, thing_xy, thing_radius, is_static, mul8, call_ax, cf_ptr, new_validcount
.export line_checked, lines_iter, things_iter, bl_func, bxl, bxh, byl, byh
.export path_traverse, pt_flags, pt_trav, aprox_dist, info_ptr, make_divline, ivec
.export c_ab, ret_w, cell_head, actor_cell, static_cell, find_link, unlink_at, link_head
.export write_link
.export _P_MobjInfo

MARKLIST    = 48

.segment "BSS"
.if .defined(BANKED_GAME) .or .defined(FAR_BLOCKLINKS)
head_addr:      .res 2              ; far address of the currently inspected cell
head_value:     .res 2              ; its near proxy, never retained across callbacks
.endif
.if .defined(BANKED_GAME) .or .defined(FAR_MOBJINFO)
info_valid:     .res 1
info_type:      .res 1
info_record:    .res MI_SIZE
.endif
.ifdef BANKED_GAME
; Path traversal, view construction and the debug row reuse this buffer.
; Keep their frequent writes outside main's posted video windows. Contents
; are scratch: each user initializes what it reads before using it.
.segment "GINTERCEPTS"
.endif
_intercepts:    .res MAXINTERCEPTS * IN_SIZE
.ifdef BANKED_GAME
.segment "BSS"
.endif
_intercept_p:   .res 2
earlyout:       .res 1
linemarks:      .res 2
marked:         .res MARKLIST * 2
nmarked:        .res 1
cf_ptr:         .res 2              ; the callback of call_ax
bl_n:           .res 1
bl_i:           .res 1
bl_func:        .res 2
bs_s1:          .res 1
bxl:            .res 1
bxh:            .res 1
byl:            .res 1
byh:            .res 1
pt_flags:       .res 1
pt_trav:        .res 2
pt_xt1:         .res 2
pt_yt1:         .res 2
pt_xt2:         .res 2
pt_yt2:         .res 2
pt_mapx:        .res 2
pt_mapy:        .res 2
pt_mxstep:      .res 2
pt_mystep:      .res 2
pt_count:       .res 1
ti_count:       .res 1
ti_in:          .res 2
ti_func:        .res 2
save_trace:     .res 16

.segment "CODE"

; ---- helpers -------------------------------------------------------------------
call_ax:
        jmp     (cf_ptr)

; A * X -> A (low), X (high), unsigned 8x8 (quarter squares)
mul8:   stx     tmp1
        sta     tmp2
        clc
        adc     tmp1
        tay                             ; (a + b) & 255, carry = bit 8
        lda     tmp2
        sec
        sbc     tmp1
        bcs     :+
        eor     #$FF
        adc     #1
:       tax                             ; |a - b|
        bcs     @big                    ; (the carry of a + b is gone: test again)
@big:   lda     tmp2
        clc
        adc     tmp1
        bcs     @hi
        lda     sqrlo,y
        sec
        sbc     sqrlo,x
        pha
        lda     sqrhi,y
        sbc     sqrhi,x
        tax
        pla
        rts
@hi:    lda     sqrlo+256,y
        sec
        sbc     sqrlo,x
        pha
        lda     sqrhi+256,y
        sbc     sqrhi,x
        tax
        pla
        rts

; C set iff the thing A/X is a static (statics <= A/X < statics_end)
is_static:
        cpx     _statics+1
        bne     :+
        cmp     _statics
:       bcc     @no
        cpx     _statics_end+1
        bne     :+
        cmp     _statics_end
:       bcs     @no
        sec
        rts
@no:    clc
        rts

; W_THX, W_THY = the position of the thing at gth (keeps gth, gmo)
thing_xy:
        lda     gth
        sta     gpt
        lda     gth+1
        sta     gpt+1
        ldx     gth+1
        lda     gth
        jsr     is_static
        bcc     @actor
        ldx     #W_THX
        ldy     #SO_X
        jsr     w_fixp
        ldx     #W_THY
        ldy     #SO_Y
        jmp     w_fixp
@actor: ldx     #W_THX
        ldy     #MO_X
        jsr     w_ldp
        ldx     #W_THY
        ldy     #MO_Y
        jmp     w_ldp

; A = the radius of the thing A/X (a static's from its type, 0 when gibbed)
_P_ThingRadius:
        jsr     thing_radius
        ldx     #0
        rts
thing_radius:
        sta     ptr1
        stx     ptr1+1
        jsr     is_static
        bcs     @static
        ldy     #MO_RADIUS
        lda     (ptr1),y
        rts
@static:
        ldy     #SO_SFLAGS
        lda     (ptr1),y
        and     #SF_GIBS
        beq     :+
        lda     #0
        rts
:       ldy     #SO_TYPE
        lda     (ptr1),y
        jsr     info_ptr
        ldy     #MI_RADIUS
        lda     (ptr1),y
        rts

; C accessor for immutable object information. The returned record is
; valid until the next info_ptr/P_MobjInfo for a different type.
_P_MobjInfo:
        jsr     info_ptr
        lda     ptr1
        ldx     ptr1+1
        rts

; ptr1 = &mobjinfo[A] (MI_SIZE = 34 bytes each: A * 32 + A * 2).
; The banked game caches one immutable record from bank 1:$6000. Preserve
; X/Y, as the original near-address helper did; callers reload ptr1 after
; any call that can inspect another object's type.
info_ptr:
.if .defined(BANKED_GAME) .or .defined(FAR_MOBJINFO)
        phx
        phy
        ldx     info_valid
        beq     @fetch
        cmp     info_type
        beq     @cached
@fetch: sta     info_type
        ldx     #1
        stx     info_valid
.endif
        stz     ptr1+1
        asl     a
        rol     ptr1+1
        sta     tmp1                    ; A * 2 (the type < 128)
        asl     a
        rol     ptr1+1
        asl     a
        rol     ptr1+1
        asl     a
        rol     ptr1+1
        asl     a
        rol     ptr1+1
        clc
        adc     tmp1
        bcc     :+
        inc     ptr1+1
        clc
:
.if .defined(BANKED_GAME) .or .defined(FAR_MOBJINFO)
        adc     #<$6000
.else
        adc     #<_mobjinfo
.endif
        sta     ptr1
        lda     ptr1+1
.if .defined(BANKED_GAME) .or .defined(FAR_MOBJINFO)
        adc     #>$6000
        sta     far_src+1
        lda     ptr1
        sta     far_src
        lda     #1
        sta     far_src+2
        lda     #<info_record
        sta     far_ptr
        lda     #>info_record
        sta     far_ptr+1
        lda     #MI_SIZE
        sta     far_len
        stz     far_len+1
        jsr     kjt_far_read
@cached:
        lda     #<info_record
        sta     ptr1
        lda     #>info_record
        sta     ptr1+1
        ply
        plx
.else
        adc     #>_mobjinfo
        sta     ptr1+1
.endif
        rts
.assert MI_SIZE = 34, error, "info_ptr multiplies by 34"

; the C arguments (fixed_t a, fixed_t b): a (C stack, popped) -> W_T0,
; b (A/X/sreg) -> W_T1
c_ab:   sta     W+W_T1
        stx     W+W_T1+1
        lda     sreg
        sta     W+W_T1+2
        lda     sreg+1
        sta     W+W_T1+3
        ldy     #3
:       lda     (sp),y
        sta     W+W_T0,y
        dey
        bpl     :-
        jmp     incsp4

; A/X/sreg = W[X]
ret_w:  lda     W+3,x
        sta     sreg+1
        lda     W+2,x
        sta     sreg
        lda     W,x
        pha
        lda     W+1,x
        tax
        pla
        rts

; ---- P_AproxDistance ---------------------------------------------------------------
_P_AproxDistance:
        jsr     c_ab
        jsr     aprox_dist
        ldx     #W_FR
        jmp     ret_w

aprox_dist:
        ldx     #W_T0
        jsr     w_abs
        ldx     #W_T1
        jsr     w_abs
        ; the smaller, halved, into T2
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        bmi     @dxless
        ldy     #W_T1
        bra     @min
@dxless:
        ldy     #W_T0
@min:   ldx     #W_T2
        jsr     w_mov
        lsr     W+W_T2+3
        ror     W+W_T2+2
        ror     W+W_T2+1
        ror     W+W_T2
        ldx     #W_FR
        ldy     #W_T0
        lda     #W_T1
        jsr     w_add3
        ldy     #W_T2
        jmp     w_sub                   ; X = W_FR still

; ---- P_PointOnLineSide ---------------------------------------------------------------
; uint8_t P_PointOnLineSide(fixed_t x, fixed_t y, line_t *line)
_P_PointOnLineSide:
        sta     gli
        stx     gli+1
        ldy     #7
:       lda     (sp),y
        sta     W+W_PLX-4,y             ; x (+4..+7), then y (+0..+3)
        dey
        cpy     #4
        bcs     :-
:       lda     (sp),y
        sta     W+W_PLY,y
        dey
        bpl     :-
        jsr     incsp8
pols:   ldy     #LI_DX
        lda     (gli),y
        iny
        ora     (gli),y
        bne     @notv
        ; x <= v1x ? dy > 0 : dy < 0
        ldx     #W_T0
        ldy     #LI_V1X
        jsr     w_fixl
        ldx     #W_PLX
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        beq     @vgt
        ldy     #LI_DY+1
        lda     (gli),y
        bmi     @zero
        dey
        ora     (gli),y
        beq     @zero
        bra     @one
@vgt:   ldy     #LI_DY+1
        lda     (gli),y
        bmi     @one
        bra     @zero
@notv:  ldy     #LI_DY
        lda     (gli),y
        iny
        ora     (gli),y
        bne     @general
        ; y <= v1y ? dx < 0 : dx > 0
        ldx     #W_T0
        ldy     #LI_V1Y
        jsr     w_fixl
        ldx     #W_PLY
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        beq     @hgt
        ldy     #LI_DX+1
        lda     (gli),y
        bmi     @one
        bra     @zero
@hgt:   ldy     #LI_DX+1
        lda     (gli),y
        bmi     @zero
        dey
        ora     (gli),y
        beq     @zero
@one:   lda     #1
        rts
@zero:  lda     #0
        rts
@general:
        ; T1 = x - v1x, T2 = y - v1y
        ldx     #W_T0
        ldy     #LI_V1X
        jsr     w_fixl
        ldx     #W_T1
        ldy     #W_PLX
        lda     #W_T0
        jsr     w_sub3
        ldx     #W_T0
        ldy     #LI_V1Y
        jsr     w_fixl
        ldx     #W_T2
        ldy     #W_PLY
        lda     #W_T0
        jsr     w_sub3
        ; left = FixedMul(line->dy, dx) -> T3; right = FixedMul(dy, line->dx)
        ldx     #W_T0
        ldy     #LI_DY
        jsr     w_sextl
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_mul
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T0
        ldy     #LI_DX
        jsr     w_sextl
        ldx     #W_T2
        ldy     #W_T0
        jsr     w_mul
        ldx     #W_FR
        ldy     #W_T3
        jsr     w_cmp                   ; right < left: front
        bmi     @zero
        bra     @one

; ---- P_BoxOnLineSide -------------------------------------------------------------------
; int8_t P_BoxOnLineSide(fixed_t *tmbox, line_t *ld)
_P_BoxOnLineSide:
        sta     gli
        stx     gli+1
        jsr     popax
        sta     gpt
        stx     gpt+1
bols:   ldy     #LI_SLOPETYPE
        lda     (gli),y
        cmp     #ST_VERTICAL
        bcc     @horiz
        beq     @vert
        jmp     @slope
@vert:  ; p1 = right < v1x, p2 = left < v1x; both flipped when dy < 0
        ldx     #W_T0
        ldy     #LI_V1X
        jsr     w_fixl
        ldy     #4 * BOXRIGHT
        jsr     box_lt_t0
        sta     bs_s1
        ldy     #4 * BOXLEFT
        jsr     box_lt_t0
        ldy     #LI_DY+1
        bra     @flip
@horiz: ; p1 = top > v1y, p2 = bottom > v1y; both flipped when dx < 0
        ldx     #W_T0
        ldy     #LI_V1Y
        jsr     w_fixl
        ldy     #4 * BOXTOP
        jsr     box_gt_t0
        sta     bs_s1
        ldy     #4 * BOXBOTTOM
        jsr     box_gt_t0
        ldy     #LI_DX+1
@flip:  eor     (gli),y
        sta     tmp1                    ; p2 in bit 7
        lda     bs_s1
        eor     (gli),y                 ; p1 in bit 7
        eor     tmp1
        bmi     @split
        lda     tmp1
        asl     a
        lda     #0
        rol     a
        rts
@split: lda     #$FF
        rts
@slope: cmp     #ST_POSITIVE
        bne     @neg
        ; p1 = side(left, top), p2 = side(right, bottom)
        ldy     #4 * BOXLEFT
        ldx     #4 * BOXTOP
        jsr     box_side
        sta     bs_s1
        ldy     #4 * BOXRIGHT
        ldx     #4 * BOXBOTTOM
        bra     @second
@neg:   ; p1 = side(right, top), p2 = side(left, bottom)
        ldy     #4 * BOXRIGHT
        ldx     #4 * BOXTOP
        jsr     box_side
        sta     bs_s1
        ldy     #4 * BOXLEFT
        ldx     #4 * BOXBOTTOM
@second:
        jsr     box_side
        cmp     bs_s1
        bne     @split
        rts

; A = $80 if box[Y] < T0 (signed), else 0
box_lt_t0:
        ldx     #W_T1
        jsr     w_ldp
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_cmp
        and     #$80
        rts

; A = $80 if box[Y] > T0, else 0
box_gt_t0:
        ldx     #W_T1
        jsr     w_ldp
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        beq     :+
        lda     #0
        rts
:       lda     #$80
        rts

; A = pols(box[Y], box[X])
box_side:
        phx
        ldx     #W_PLX
        jsr     w_ldp
        ply
        ldx     #W_PLY
        jsr     w_ldp
        jmp     pols

; ---- P_PointOnDivlineSide ------------------------------------------------------------------
; uint8_t P_PointOnDivlineSide(fixed_t x, fixed_t y, divline_t *line):
; the trace is kept aside while the divline takes its place
_P_PointOnDivlineSide:
        sta     gpt
        stx     gpt+1
        ldy     #7
:       lda     (sp),y
        sta     W+W_PDX-4,y
        dey
        cpy     #4
        bcs     :-
:       lda     (sp),y
        sta     W+W_PDY,y
        dey
        bpl     :-
        jsr     incsp8
        jsr     trace_aside
        ldy     #DL_SIZE-1
:       lda     (gpt),y
        sta     W+W_TRX,y
        dey
        bpl     :-
        jsr     pods
        pha
        jsr     trace_back
        pla
        ldx     #0
        rts

trace_aside:
        ldy     #15
:       lda     W+W_TRX,y
        sta     save_trace,y
        dey
        bpl     :-
        rts
trace_back:
        ldy     #15
:       lda     save_trace,y
        sta     W+W_TRX,y
        dey
        bpl     :-
        rts

; pods: (W_PDX, W_PDY) against the trace -> A
pods:   ldx     #W_TRDX
        jsr     w_tst
        bne     @notv
        ; x <= trace.x ? dy > 0 : dy < 0
        ldx     #W_PDX
        ldy     #W_TRX
        jsr     w_cmp
        cmp     #1
        beq     @vgt
        ldx     #W_TRDY
        jsr     w_sign
        cmp     #1
        beq     @one
        bra     @zero
@vgt:   lda     W+W_TRDY+3
        bmi     @one
        bra     @zero
@notv:  ldx     #W_TRDY
        jsr     w_tst
        bne     @general
        ; y <= trace.y ? dx < 0 : dx > 0
        ldx     #W_PDY
        ldy     #W_TRY
        jsr     w_cmp
        cmp     #1
        beq     @hgt
        lda     W+W_TRDX+3
        bmi     @one
        bra     @zero
@hgt:   ldx     #W_TRDX
        jsr     w_sign
        cmp     #1
        beq     @one
@zero:  lda     #0
        rts
@one:   lda     #1
        rts
@general:
        ; T0 = dx = x - trace.x, T1 = dy = y - trace.y
        ldx     #W_T0
        ldy     #W_PDX
        lda     #W_TRX
        jsr     w_sub3
        ldx     #W_T1
        ldy     #W_PDY
        lda     #W_TRY
        jsr     w_sub3
        ; the sign shortcut
        lda     W+W_TRDY+3
        eor     W+W_TRDX+3
        eor     W+W_T0+3
        eor     W+W_T1+3
        bpl     @mul
        lda     W+W_TRDY+3
        eor     W+W_T0+3
        bmi     @one
        bra     @zero
@mul:   ; left = FixedMul(line->dy >> 8, dx >> 8) -> T4
        ldx     #W_T2
        ldy     #W_TRDY
        jsr     w_sar8
        ldx     #W_T3
        ldy     #W_T0
        jsr     w_sar8
        ldx     #W_T2
        ldy     #W_T3
        jsr     w_mul
        ldx     #W_T4
        ldy     #W_FR
        jsr     w_mov
        ; right = FixedMul(dy >> 8, line->dx >> 8)
        ldx     #W_T2
        ldy     #W_T1
        jsr     w_sar8
        ldx     #W_T3
        ldy     #W_TRDX
        jsr     w_sar8
        ldx     #W_T2
        ldy     #W_T3
        jsr     w_mul
        ldx     #W_FR
        ldy     #W_T4
        jsr     w_cmp
        bmi     @zero
        bra     @one

; ---- divlines and intercepts -----------------------------------------------------------------
; void P_MakeDivline(line_t *li, divline_t *dl)
_P_MakeDivline:
        sta     gpt
        stx     gpt+1
        jsr     popax
        sta     gli
        stx     gli+1
        jsr     make_divline
        ldy     #DL_SIZE-1
:       lda     W+W_IDLX,y
        sta     (gpt),y
        dey
        bpl     :-
        rts

; W_IDL = the line gli as a divline
make_divline:
        ldx     #W_IDLX
        ldy     #LI_V1X
        jsr     w_fixl
        ldx     #W_IDLY
        ldy     #LI_V1Y
        jsr     w_fixl
        ldx     #W_IDLDX
        ldy     #LI_DX
        jsr     w_fixl
        ldx     #W_IDLDY
        ldy     #LI_DY
        jmp     w_fixl

; fixed_t P_InterceptVector(divline_t *v2, divline_t *v1)
_P_InterceptVector:
        sta     gpt
        stx     gpt+1
        ldy     #DL_SIZE-1
:       lda     (gpt),y
        sta     W+W_IDLX,y
        dey
        bpl     :-
        jsr     popax
        sta     gpt
        stx     gpt+1
        jsr     trace_aside
        ldy     #DL_SIZE-1
:       lda     (gpt),y
        sta     W+W_TRX,y
        dey
        bpl     :-
        jsr     ivec
        jsr     trace_back
        ldx     #W_FR
        jmp     ret_w

; ivec: W_FR = P_InterceptVector(v2 = trace, v1 = W_IDL)
;   den = FixedMul(v1.dy >> 8, v2.dx) - FixedMul(v1.dx >> 8, v2.dy)
;   num = FixedMul((v1.x - v2.x) >> 8, v1.dy) + FixedMul((v2.y - v1.y) >> 8, v1.dx)
ivec:   ldx     #W_T0
        ldy     #W_IDLDY
        jsr     w_sar8
        ldx     #W_T0
        ldy     #W_TRDX
        jsr     w_mul
        ldx     #W_T1
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T0
        ldy     #W_IDLDX
        jsr     w_sar8
        ldx     #W_T0
        ldy     #W_TRDY
        jsr     w_mul
        ldx     #W_T1
        ldy     #W_FR
        jsr     w_sub                   ; T1 = den
        ldx     #W_T1
        jsr     w_tst
        bne     :+
        ldx     #W_FR
        jmp     w_zero
:       ldx     #W_T0
        ldy     #W_IDLX
        lda     #W_TRX
        jsr     w_sub3
        ldx     #W_T0
        ldy     #W_T0
        jsr     w_sar8
        ldx     #W_T0
        ldy     #W_IDLDY
        jsr     w_mul
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T0
        ldy     #W_TRY
        lda     #W_IDLY
        jsr     w_sub3
        ldx     #W_T0
        ldy     #W_T0
        jsr     w_sar8
        ldx     #W_T0
        ldy     #W_IDLDX
        jsr     w_mul
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_add                   ; T2 = num
        ldx     #W_T2
        ldy     #W_T1
        jmp     w_div

; ---- line opening ---------------------------------------------------------------------------
; void P_LineOpening(line_t *linedef)
_P_LineOpening:
        sta     gli
        stx     gli+1
line_opening:
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        bne     :+
        ldx     #W_OPENRANGE
        jmp     w_zero
:       ; ptr1/ptr2 = the ceilings of front/back, ptr3/ptr4 their floors
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        asl     a
        sta     tmp1
        iny
        lda     (gli),y
        rol     a
        sta     tmp2
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        asl     a
        sta     tmp3
        iny
        lda     (gli),y
        rol     a
        sta     tmp4
        clc
        lda     _sec_ceilh
        adc     tmp1
        sta     ptr1
        lda     _sec_ceilh+1
        adc     tmp2
        sta     ptr1+1
        clc
        lda     _sec_ceilh
        adc     tmp3
        sta     ptr2
        lda     _sec_ceilh+1
        adc     tmp4
        sta     ptr2+1
        clc
        lda     _sec_floorh
        adc     tmp1
        sta     ptr3
        lda     _sec_floorh+1
        adc     tmp2
        sta     ptr3+1
        clc
        lda     _sec_floorh
        adc     tmp3
        sta     ptr4
        lda     _sec_floorh+1
        adc     tmp4
        sta     ptr4+1
        ; opentop = min(front ceiling, back ceiling)
        ldy     #1
        lda     (ptr1)
        cmp     (ptr2)
        lda     (ptr1),y
        sbc     (ptr2),y
        bvc     :+
        eor     #$80
:       bmi     @fc
        lda     (ptr2)
        sta     W+W_OPENTOP+2
        lda     (ptr2),y
        sta     W+W_OPENTOP+3
        bra     @floors
@fc:    lda     (ptr1)
        sta     W+W_OPENTOP+2
        lda     (ptr1),y
        sta     W+W_OPENTOP+3
@floors:
        stz     W+W_OPENTOP
        stz     W+W_OPENTOP+1
        stz     W+W_OPENBOTTOM
        stz     W+W_OPENBOTTOM+1
        stz     W+W_LOWFLOOR
        stz     W+W_LOWFLOOR+1
        ; front floor > back floor?  (back - front < 0)
        lda     (ptr4)
        cmp     (ptr3)
        lda     (ptr4),y
        sbc     (ptr3),y
        bvc     :+
        eor     #$80
:       bmi     @fhigh
        lda     (ptr4)                  ; openbottom = back, lowfloor = front
        sta     W+W_OPENBOTTOM+2
        lda     (ptr4),y
        sta     W+W_OPENBOTTOM+3
        lda     (ptr3)
        sta     W+W_LOWFLOOR+2
        lda     (ptr3),y
        sta     W+W_LOWFLOOR+3
        bra     @range
@fhigh: lda     (ptr3)
        sta     W+W_OPENBOTTOM+2
        lda     (ptr3),y
        sta     W+W_OPENBOTTOM+3
        lda     (ptr4)
        sta     W+W_LOWFLOOR+2
        lda     (ptr4),y
        sta     W+W_LOWFLOOR+3
@range: ldx     #W_OPENRANGE
        ldy     #W_OPENTOP
        lda     #W_OPENBOTTOM
        jmp     w_sub3

; ---- blockmap coordinates ------------------------------------------------------------------------
; int16_t P_BlockX(fixed_t x) = (x - FIX(bmaporgx)) >> 23
_P_BlockX:
        jsr     get_t0
        ldx     #W_T0
blockx: lda     _bmaporgx
        sta     tmp1
        lda     _bmaporgx+1
        bra     block_common
_P_BlockY:
        jsr     get_t0
        ldx     #W_T0
blocky: lda     _bmaporgy
        sta     tmp1
        lda     _bmaporgy+1
; ((W[X] >> 16) - org) >> 7 with 24-bit intermediate: A = low, X = high
block_common:
        sta     tmp2
        sec
        lda     W+2,x
        sbc     tmp1
        sta     tmp3                    ; t0
        lda     W+3,x
        sbc     tmp2
        sta     tmp4                    ; t1
        ; t2 = sext(x3) - sext(org_hi) - borrow (the carry is kept)
        lda     W+3,x
        and     #$80
        beq     :+
        lda     #$FF
:       sta     ptr1
        lda     tmp2
        and     #$80
        beq     :+
        lda     #$FF
:       sta     ptr1+1
        lda     ptr1
        sbc     ptr1+1
        ; t >> 7: low = t1 << 1 | t0 >> 7, high = t2 << 1 | t1 >> 7
        asl     tmp3
        rol     tmp4
        rol     a
        tax
        lda     tmp4
        rts

; W_T0 = the C long in A/X/sreg
get_t0: sta     W+W_T0
        stx     W+W_T0+1
        lda     sreg
        sta     W+W_T0+2
        lda     sreg+1
        sta     W+W_T0+3
        rts

; ---- thing positions --------------------------------------------------------------------------
; ptr2 = &blocklinks[by * w + bx] for (bxl/bxh, byl/byh): C clear when the
; cell is outside the blockmap
cell_head:
        lda     bxh
        ora     byh
        bne     @out                    ; negative or >= 256
        lda     bxl
        cmp     _bmapwidth
        bcs     @out
        lda     byl
        cmp     _bmapheight
        bcs     @out
        ldx     _bmapwidth
        jsr     mul8                    ; by * w
        sta     tmp1
        stx     tmp2
        clc
        lda     tmp1
        adc     bxl
        sta     tmp1
        bcc     :+
        inc     tmp2
:       asl     tmp1                    ; * sizeof(mobj_t *)
        rol     tmp2
        clc
        lda     _blocklinks
        adc     tmp1
        sta     ptr2
        lda     _blocklinks+1
        adc     tmp2
        sta     ptr2+1
        sec
        rts
@out:   clc
        rts

; ptr2's cell head -> a near two-byte proxy when the heads live in bank 1.
; Chain traversal itself follows the ordinary near actor/static pointers.
; A caller consumes or updates the proxy before invoking any callbacks,
; so recursively entered thing iterators cannot leave a stale head live.
read_head:
.if .defined(BANKED_GAME) .or .defined(FAR_BLOCKLINKS)
        lda     ptr2
        sta     head_addr
        sta     far_src
        lda     ptr2+1
        sta     head_addr+1
        sta     far_src+1
        lda     #1                      ; BLOCKLINK_BANK in p_setup.c
        sta     far_src+2
        lda     #<head_value
        sta     far_ptr
        sta     ptr2
        lda     #>head_value
        sta     far_ptr+1
        sta     ptr2+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     kjt_far_read
.endif
        sec
        rts

; Store A/X into the link at ptr2. Only the first link in a chain is far;
; the links inside actors/statics are written directly, as before.
write_link:
        sta     (ptr2)
        ldy     #1
        txa
        sta     (ptr2),y
.if .defined(BANKED_GAME) .or .defined(FAR_BLOCKLINKS)
        lda     ptr2
        cmp     #<head_value
        bne     @done
        lda     ptr2+1
        cmp     #>head_value
        bne     @done
        lda     head_addr
        sta     far_dst
        lda     head_addr+1
        sta     far_dst+1
        lda     #1
        sta     far_dst+2
        lda     #<head_value
        sta     far_ptr
        lda     #>head_value
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jmp     kjt_far_write
@done:
.endif
        rts

; the cell of the actor gmo -> cell_head
actor_cell:
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T0
        jsr     blockx
        sta     bxl
        stx     bxh
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        jsr     blocky
        sta     byl
        stx     byh
        jsr     cell_head
        bcc     :+
        jmp     read_head
:       rts

; the cell of the static gmo -> cell_head: ((x - orgx) >> 7, (y - orgy) >> 7)
static_cell:
        lda     _bmaporgx
        sta     tmp3
        lda     _bmaporgx+1
        sta     tmp4
        ldy     #SO_X
        jsr     @one
        sta     bxl
        stx     bxh
        lda     _bmaporgy
        sta     tmp3
        lda     _bmaporgy+1
        sta     tmp4
        ldy     #SO_Y
        jsr     @one
        sta     byl
        stx     byh
        jsr     cell_head
        bcc     :+
        jmp     read_head
:       rts
; ((the int16 at (gmo)+Y) - tmp4:tmp3) >> 7 -> A (low), X (high)
@one:   sec
        lda     (gmo),y
        sbc     tmp3
        sta     tmp1
        iny
        lda     (gmo),y
        sbc     tmp4
        asl     tmp1
        rol     a
        ldx     #0
        bcc     :+
        ldx     #$FF
:       rts

; the link that points at gmo in the chain whose head is at ptr2: C set
; when found (ptr2 is then the link's address)
find_link:
@loop:  ldy     #1
        lda     (ptr2),y
        tax
        lda     (ptr2)
        cmp     gmo
        bne     @next
        cpx     gmo+1
        beq     @found
@next:  cpx     #0
        bne     :+
        cmp     #0
        beq     @none
:       pha
        phx
        jsr     is_static
        plx
        pla
        ldy     #MO_BNEXT
        bcc     :+
        ldy     #SO_BNEXT
:       sty     tmp1
        clc
        adc     tmp1
        sta     ptr2
        txa
        adc     #0
        sta     ptr2+1
        bra     @loop
@found: sec
        rts
@none:  clc
        rts

; *link (ptr2) = BNEXT(gmo)
unlink_at:
        lda     gmo
        ldx     gmo+1
        jsr     is_static
        ldy     #MO_BNEXT
        bcc     :+
        ldy     #SO_BNEXT
:       lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tax
        pla
        jmp     write_link

; link gmo at the head of the chain at ptr2, its bnext at offset Y
link_head:
        lda     (ptr2)
        sta     (gmo),y
        iny
        phy
        ldy     #1
        lda     (ptr2),y
        ply
        sta     (gmo),y
        lda     gmo
        ldx     gmo+1
        jmp     write_link

; void P_UnsetThingPosition(mobj_t *thing)
_P_UnsetThingPosition:
        sta     gmo
        stx     gmo+1
unset_pos:
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_NOBLOCKMAP
        bne     @done
        jsr     actor_cell
        bcc     @done
        jsr     find_link
        bcc     @done
        jmp     unlink_at
@done:  rts

; void P_SetThingPosition(mobj_t *thing)
_P_SetThingPosition:
        sta     gmo
        stx     gmo+1
set_pos:
        ldy     #MO_X+3
:       lda     (gmo),y
        sta     rp_x-MO_X,y
        dey
        cpy     #MO_X
        bcs     :-
        ldy     #MO_Y+3
:       lda     (gmo),y
        sta     rp_y-MO_Y,y
        dey
        cpy     #MO_Y
        bcs     :-
        jsr     rpis
        ldy     #MO_SECTOR
        sta     (gmo),y
        iny
        txa
        sta     (gmo),y
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_NOBLOCKMAP
        bne     @done
        jsr     actor_cell
        ldy     #MO_BNEXT
        bcs     link_head
        lda     #0
        sta     (gmo),y
        iny
        sta     (gmo),y
@done:  rts

; void P_LinkStatic(sobj_t *s)
_P_LinkStatic:
        sta     gmo
        stx     gmo+1
        jsr     static_cell
        ldy     #SO_BNEXT
        bcs     link_head
        lda     #0
        sta     (gmo),y
        iny
        sta     (gmo),y
        rts

; void P_UnlinkStatic(sobj_t *s)
_P_UnlinkStatic:
        sta     gmo
        stx     gmo+1
        jsr     static_cell
        bcc     @done
        jsr     find_link
        bcc     @done
        jmp     unlink_at
@done:  rts

; ---- iterators --------------------------------------------------------------------------------
; boolean P_BlockLinesIterator(int16_t x, int16_t y, boolean (*func)(line_t *))
_P_BlockLinesIterator:
        sta     bl_func
        stx     bl_func+1
        jsr     xy_args
lines_iter:
        jsr     cell_head
        bcc     @true
        ; the cell number = (ptr2 - blocklinks) / 2
        sec
        lda     ptr2
        sbc     _blocklinks
        sta     blk_cell
        lda     ptr2+1
        sbc     _blocklinks+1
        lsr     a
        ror     blk_cell
        sta     blk_cell+1
        stz     blk_pos
        stz     blk_pos+1
@chunk: jsr     blk_lines
        sta     bl_n
        beq     @true
        stz     bl_i
@line:  lda     bl_i
        asl     a
        tay
        lda     blk_buf,y
        ldx     blk_buf+1,y
        jsr     line_checked
        bcs     @next
        lda     bl_i
        asl     a
        tay
        lda     blk_buf,y
        ldx     blk_buf+1,y
        jsr     line_get                ; -> gli, A/X
        ldy     bl_func
        sty     cf_ptr
        ldy     bl_func+1
        sty     cf_ptr+1
        jsr     call_ax
        cmp     #0
        beq     @false
@next:  inc     bl_i
        lda     bl_i
        cmp     bl_n
        bne     @line
        bra     @chunk
@true:  lda     #1
        ldx     #0
        rts
@false: lda     #0
        tax
        rts

; the C arguments (int16_t x, int16_t y) popped into bxl/bxh, byl/byh
xy_args:
        jsr     popax
        sta     byl
        stx     byh
        jsr     popax
        sta     bxl
        stx     bxh
        rts

; boolean P_BlockThingsIterator(int16_t x, int16_t y, boolean (*func)(mobj_t *))
_P_BlockThingsIterator:
        sta     bl_func
        stx     bl_func+1
        jsr     xy_args
things_iter:
        jsr     cell_head
        bcc     @true
        jsr     read_head
        ldy     #1
        lda     (ptr2),y
        tax
        lda     (ptr2)
        ; A/X = the thing; the callback and the thing on the 6502 stack
@loop:  cpx     #0
        bne     :+
        cmp     #0
        beq     @true
:       pha
        phx
        ldy     bl_func+1
        phy
        sty     cf_ptr+1
        ldy     bl_func
        phy
        sty     cf_ptr
        jsr     call_ax
        tay                             ; the callback's result
        pla
        sta     bl_func
        pla
        sta     bl_func+1
        plx
        pla
        cpy     #0
        beq     @false
        ; the next: BNEXT(thing)
        sta     ptr1
        stx     ptr1+1
        jsr     is_static
        ldy     #MO_BNEXT
        bcc     :+
        ldy     #SO_BNEXT
:       lda     (ptr1),y
        pha
        iny
        lda     (ptr1),y
        tax
        pla
        bra     @loop
@true:  lda     #1
        ldx     #0
        rts
@false: lda     #0
        tax
        rts

; ---- line marks ------------------------------------------------------------------------------------
_P_InitLineMarks:
        jsr     marks_size
        jsr     _P_ArenaAlloc
        sta     linemarks
        stx     linemarks+1
        stz     nmarked
        rts

; A/X = (numlines + 7) >> 3, the bytes of the bitset
marks_size:
        clc
        lda     _numlines
        adc     #7
        sta     tmp1
        lda     _numlines+1
        adc     #0
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        tax
        lda     tmp1
        rts

; clear the marks set since the last clear
_P_NewValidcount:
new_validcount:
        lda     nmarked
        cmp     #MARKLIST+1
        bcs     @all
        tax
        beq     @done
@one:   dex
        txa
        asl     a
        tay
        clc
        lda     marked,y
        adc     linemarks
        sta     ptr1
        lda     marked+1,y
        adc     linemarks+1
        sta     ptr1+1
        lda     #0
        sta     (ptr1)
        cpx     #0
        bne     @one
@done:  stz     nmarked
        rts
@all:   lda     linemarks
        sta     ptr1
        lda     linemarks+1
        sta     ptr1+1
        jsr     marks_size
        sta     tmp1
        lda     #0
        ldy     #0
        cpx     #0
        beq     @part
@page:  sta     (ptr1),y
        iny
        bne     @page
        inc     ptr1+1
        dex
        bne     @page
@part:  ldy     tmp1
        beq     @done
@pb:    dey
        sta     (ptr1),y
        cpy     #0
        bne     @pb
        bra     @done

; boolean P_LineChecked(uint16_t line); line_checked: A/X = line -> C set
; if it was already marked
_P_LineChecked:
        jsr     line_checked
        lda     #0
        rol     a
        ldx     #0
        rts
line_checked:
        sta     tmp1
        and     #7
        tay
        lda     #1
:       cpy     #0
        beq     :+
        asl     a
        dey
        bra     :-
:       sta     tmp3                    ; mask
        txa                             ; i = line >> 3
        lsr     a
        sta     tmp2
        lda     tmp1
        ror     a
        lsr     tmp2
        ror     a
        lsr     tmp2
        ror     a
        sta     tmp1                    ; tmp2:tmp1 = i
        clc
        adc     linemarks
        sta     ptr1
        lda     tmp2
        adc     linemarks+1
        sta     ptr1+1
        lda     (ptr1)
        tay
        and     tmp3
        beq     @new
        sec
        rts
@new:   tya
        bne     @set                    ; the byte is listed already
        ldx     nmarked
        cpx     #MARKLIST+1
        bcs     @set
        cpx     #MARKLIST
        bcs     @count
        txa
        asl     a
        tax
        lda     tmp1
        sta     marked,x
        lda     tmp2
        sta     marked+1,x
@count: inc     nmarked
@set:   lda     (ptr1)
        ora     tmp3
        sta     (ptr1)
        clc
        rts

; ---- intercepts --------------------------------------------------------------------------------------
; the line callback of P_PathTraverse (A/X = line_t *)
pit_add_line:
        sta     gli
        stx     gli+1
        ; the trace longer than 16 units on an axis: sides by the divline
        ldx     #W_TRDX
        jsr     big16
        bcs     @div
        ldx     #W_TRDY
        jsr     big16
        bcs     @div
        ; s1 = side(trace start), s2 = side(trace end) to the line
        ldx     #W_PLX
        ldy     #W_TRX
        jsr     w_mov
        ldx     #W_PLY
        ldy     #W_TRY
        jsr     w_mov
        jsr     pols
        sta     bs_s1
        ldx     #W_PLX
        ldy     #W_TRX
        lda     #W_TRDX
        jsr     w_add3
        ldx     #W_PLY
        ldy     #W_TRY
        lda     #W_TRDY
        jsr     w_add3
        jsr     pols
        bra     @sides
@div:   ; s1 = side of v1, s2 = side of v2 to the trace
        jsr     make_divline
        ldx     #W_PDX
        ldy     #W_IDLX
        jsr     w_mov
        ldx     #W_PDY
        ldy     #W_IDLY
        jsr     w_mov
        jsr     pods
        sta     bs_s1
        ldx     #W_PDX
        ldy     #W_IDLX
        lda     #W_IDLDX
        jsr     w_add3
        ldx     #W_PDY
        ldy     #W_IDLY
        lda     #W_IDLDY
        jsr     w_add3
        jsr     pods
@sides: cmp     bs_s1
        beq     @true                   ; not crossed
        jsr     make_divline
        jsr     ivec
        lda     W+W_FR+3
        bmi     @true                   ; behind the source
        lda     earlyout
        beq     @add
        ; frac < FRACUNIT on a one-sided line: stop
        lda     W+W_FR+3
        ora     W+W_FR+2
        bne     @add
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        bne     @add
        lda     #0
        tax
        rts
@add:   jsr     intercept_slot
        bcc     @true
        ldy     #IN_ISALINE
        lda     #1
        sta     (ptr1),y
        ldy     #LI_INDEX
        lda     (gli),y
        ldy     #IN_LINE
        sta     (ptr1),y
        ldy     #LI_INDEX+1
        lda     (gli),y
        ldy     #IN_LINE+1
        sta     (ptr1),y
@true:  lda     #1
        ldx     #0
        rts

; C set iff W[X] > 16 << 16 or W[X] < -(16 << 16)
big16:  lda     W+3,x
        bmi     @neg
        bne     @yes
        lda     W+2,x
        cmp     #16
        bcc     @no
        bne     @yes
        lda     W+1,x
        ora     W,x
        bne     @yes
@no:    clc
        rts
@yes:   sec
        rts
@neg:   cmp     #$FF
        bne     @yes
        lda     W+2,x
        cmp     #$F0
        bcc     @yes
        clc                             ; >= -16.0
        rts

; ptr1 = the next intercept, its frac = W_FR; C clear if the array is full
intercept_slot:
        lda     _intercept_p
        cmp     #<(_intercepts + MAXINTERCEPTS * IN_SIZE)
        bne     :+
        lda     _intercept_p+1
        cmp     #>(_intercepts + MAXINTERCEPTS * IN_SIZE)
        bne     :+
        clc
        rts
:       lda     _intercept_p
        sta     ptr1
        clc
        adc     #IN_SIZE
        sta     _intercept_p
        lda     _intercept_p+1
        sta     ptr1+1
        adc     #0
        sta     _intercept_p+1
        ldy     #IN_FRAC+3
:       lda     W+W_FR-IN_FRAC,y
        sta     (ptr1),y
        dey
        bpl     :-
        sec
        rts

; the thing callback of P_PathTraverse (A/X = thing)
pit_add_thing:
        sta     gth
        stx     gth+1
        jsr     thing_xy
        lda     gth
        ldx     gth+1
        jsr     thing_radius
        ldy     #0
        ldx     #W_T0
        jsr     w_fix                   ; T0 = FIX(radius)
        ; the corners: (x1, y1) in IDLX/IDLY, (x2, y2) in IDLDX/IDLDY for now
        ldx     #W_IDLX
        ldy     #W_THX
        lda     #W_T0
        jsr     w_sub3                  ; x1 = x - r
        ldx     #W_IDLDX
        ldy     #W_THX
        lda     #W_T0
        jsr     w_add3                  ; x2 = x + r
        ; tracepositive = (trace.dx ^ trace.dy) > 0
        lda     W+W_TRDX+3
        eor     W+W_TRDY+3
        bmi     @notpos
        ldx     #3
@x:     lda     W+W_TRDX,x
        eor     W+W_TRDY,x
        bne     @pos
        dex
        bpl     @x
@notpos:
        ldx     #W_IDLY
        ldy     #W_THY
        lda     #W_T0
        jsr     w_sub3                  ; y1 = y - r
        ldx     #W_IDLDY
        ldy     #W_THY
        lda     #W_T0
        jsr     w_add3                  ; y2 = y + r
        bra     @sides
@pos:   ldx     #W_IDLY
        ldy     #W_THY
        lda     #W_T0
        jsr     w_add3                  ; y1 = y + r
        ldx     #W_IDLDY
        ldy     #W_THY
        lda     #W_T0
        jsr     w_sub3                  ; y2 = y - r
@sides: ldx     #W_PDX
        ldy     #W_IDLX
        jsr     w_mov
        ldx     #W_PDY
        ldy     #W_IDLY
        jsr     w_mov
        jsr     pods
        sta     bs_s1
        ldx     #W_PDX
        ldy     #W_IDLDX
        jsr     w_mov
        ldx     #W_PDY
        ldy     #W_IDLDY
        jsr     w_mov
        jsr     pods
        cmp     bs_s1
        beq     @true
        ; the divline (x1, y1, x2 - x1, y2 - y1)
        ldx     #W_IDLDX
        ldy     #W_IDLX
        jsr     w_sub
        ldx     #W_IDLDY
        ldy     #W_IDLY
        jsr     w_sub
        jsr     ivec
        lda     W+W_FR+3
        bmi     @true
        jsr     intercept_slot
        bcc     @true
        ldy     #IN_ISALINE
        lda     #0
        sta     (ptr1),y
        ldy     #IN_THING
        lda     gth
        sta     (ptr1),y
        iny
        lda     gth+1
        sta     (ptr1),y
@true:  lda     #1
        ldx     #0
        rts

; traverse the intercepts nearest first up to frac FRACUNIT, calling
; ti_func(intercept); A = 0 if a callback stopped
traverse:
        ; count = (intercept_p - intercepts) / IN_SIZE
        sec
        lda     _intercept_p
        sbc     #<_intercepts
        sta     tmp1
        lda     _intercept_p+1
        sbc     #>_intercepts
        sta     tmp2
        ldx     #0
@div:   lda     tmp1
        ora     tmp2
        beq     @dd
        sec
        lda     tmp1
        sbc     #IN_SIZE
        sta     tmp1
        bcs     :+
        dec     tmp2
:       inx
        bra     @div
@dd:    stx     ti_count
@round: lda     ti_count
        bne     :+
        jmp     @alldone
:       dec     ti_count
        ldx     #W_TIDIST
        jsr     w_ldi
        .dword  $7FFFFFFF
        stz     ti_in
        stz     ti_in+1
        lda     #<_intercepts
        sta     ptr1
        lda     #>_intercepts
        sta     ptr1+1
@scan:  lda     ptr1
        cmp     _intercept_p
        bne     :+
        lda     ptr1+1
        cmp     _intercept_p+1
        beq     @scanned
:       ; frac < dist ?
        ldy     #IN_FRAC
        lda     (ptr1),y
        cmp     W+W_TIDIST
        iny
        lda     (ptr1),y
        sbc     W+W_TIDIST+1
        iny
        lda     (ptr1),y
        sbc     W+W_TIDIST+2
        iny
        lda     (ptr1),y
        sbc     W+W_TIDIST+3
        bvc     :+
        eor     #$80
:       bpl     @snext
        ldy     #IN_FRAC+3
:       lda     (ptr1),y
        sta     W+W_TIDIST-IN_FRAC,y
        dey
        bpl     :-
        lda     ptr1
        sta     ti_in
        lda     ptr1+1
        sta     ti_in+1
@snext: clc
        lda     ptr1
        adc     #IN_SIZE
        sta     ptr1
        bcc     @scan
        inc     ptr1+1
        bra     @scan
@scanned:
        ; dist > FRACUNIT: done
        lda     W+W_TIDIST+3
        bmi     @call
        bne     @alldone
        lda     W+W_TIDIST+2
        cmp     #2
        bcs     @alldone
        cmp     #1
        bne     @call
        lda     W+W_TIDIST+1
        ora     W+W_TIDIST
        bne     @alldone
@call:  lda     ti_func
        sta     cf_ptr
        lda     ti_func+1
        sta     cf_ptr+1
        lda     ti_in
        ldx     ti_in+1
        jsr     call_ax
        cmp     #0
        beq     @stopped
        ; in->frac = MAXINT
        lda     ti_in
        sta     ptr1
        lda     ti_in+1
        sta     ptr1+1
        ldy     #IN_FRAC
        lda     #$FF
        sta     (ptr1),y
        iny
        sta     (ptr1),y
        iny
        sta     (ptr1),y
        iny
        lda     #$7F
        sta     (ptr1),y
        jmp     @round
@alldone:
        lda     #1
        ldx     #0
        rts
@stopped:
        lda     #0
        tax
        rts

; ---- P_PathTraverse -------------------------------------------------------------------------------
; boolean P_PathTraverse(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2,
;                        uint8_t flags, traverser_t trav)
; C stack: +0 flags, +1 y2, +5 x2, +9 y1, +13 x1 (17 bytes)
_P_PathTraverse:
        sta     pt_trav
        stx     pt_trav+1
        lda     (sp)
        sta     pt_flags
        ldy     #16
        ldx     #3
:       lda     (sp),y                  ; x1: +13..+16
        sta     W+W_PTX1,x
        dey
        dex
        bpl     :-
        ldx     #3
:       lda     (sp),y                  ; y1: +9..+12
        sta     W+W_PTY1,x
        dey
        dex
        bpl     :-
        ldx     #3
:       lda     (sp),y                  ; x2: +5..+8
        sta     W+W_PTX2,x
        dey
        dex
        bpl     :-
        ldx     #3
:       lda     (sp),y                  ; y2: +1..+4
        sta     W+W_PTY2,x
        dey
        dex
        bpl     :-
        ldy     #17
        jsr     addysp
path_traverse:
        lda     pt_flags
        and     #PT_EARLYOUT
        sta     earlyout
        jsr     new_validcount
        lda     #<_intercepts
        sta     _intercept_p
        lda     #>_intercepts
        sta     _intercept_p+1
        ; don't side exactly on a line: x1 += FRACUNIT when (x1 - orgx) is
        ; a multiple of the block size (its low 23 bits zero)
        ldx     #W_PTX1
        lda     _bmaporgx
        jsr     nudge
        ldx     #W_PTY1
        lda     _bmaporgy
        jsr     nudge
        ; the trace
        ldx     #W_TRX
        ldy     #W_PTX1
        jsr     w_mov
        ldx     #W_TRY
        ldy     #W_PTY1
        jsr     w_mov
        ldx     #W_TRDX
        ldy     #W_PTX2
        lda     #W_PTX1
        jsr     w_sub3
        ldx     #W_TRDY
        ldy     #W_PTY2
        lda     #W_PTY1
        jsr     w_sub3
        ; relative to the blockmap origin
        ldx     #W_PTX1
        jsr     sub_orgx
        ldx     #W_PTX2
        jsr     sub_orgx
        ldx     #W_PTY1
        jsr     sub_orgy
        ldx     #W_PTY2
        jsr     sub_orgy
        ; the cells: value >> 23
        ldx     #W_PTX1
        jsr     shr23
        sta     pt_xt1
        stx     pt_xt1+1
        ldx     #W_PTY1
        jsr     shr23
        sta     pt_yt1
        stx     pt_yt1+1
        ldx     #W_PTX2
        jsr     shr23
        sta     pt_xt2
        stx     pt_xt2+1
        ldx     #W_PTY2
        jsr     shr23
        sta     pt_yt2
        stx     pt_yt2+1
        ; along x: the step direction, ystep, partial, yintercept
        lda     pt_xt1
        sta     ptr1
        lda     pt_xt1+1
        sta     ptr1+1
        lda     pt_xt2
        ldx     pt_xt2+1
        jsr     cmp16
        sta     pt_mxstep
        ldx     #W_PTX1
        ldy     #W_PTX2
        lda     #W_PTYSTEP
        jsr     axis_setup
        ; yintercept = (y1 >> 7) + FixedMul(partial, ystep)
        ldx     #W_T3
        ldy     #W_PTY1
        jsr     sr7
        ldx     #W_PTYINT
        ldy     #W_T3
        lda     #W_FR
        jsr     w_add3
        ; along y
        lda     pt_yt1
        sta     ptr1
        lda     pt_yt1+1
        sta     ptr1+1
        lda     pt_yt2
        ldx     pt_yt2+1
        jsr     cmp16
        sta     pt_mystep
        ldx     #W_PTY1
        ldy     #W_PTY2
        lda     #W_PTXSTEP
        jsr     axis_setup
        ldx     #W_T3
        ldy     #W_PTX1
        jsr     sr7
        ldx     #W_PTXINT
        ldy     #W_T3
        lda     #W_FR
        jsr     w_add3
        ; the steps as int16
        lda     pt_mxstep
        and     #$80
        beq     :+
        lda     #$FF
:       sta     pt_mxstep+1
        lda     pt_mystep
        and     #$80
        beq     :+
        lda     #$FF
:       sta     pt_mystep+1
        lda     pt_xt1
        sta     pt_mapx
        lda     pt_xt1+1
        sta     pt_mapx+1
        lda     pt_yt1
        sta     pt_mapy
        lda     pt_yt1+1
        sta     pt_mapy+1
        stz     pt_count
@step:  lda     pt_flags
        and     #PT_ADDLINES
        beq     @nolines
        jsr     map_cell
        lda     #<pit_add_line
        sta     bl_func
        lda     #>pit_add_line
        sta     bl_func+1
        jsr     lines_iter
        cmp     #0
        bne     @nolines
        jmp     @early
@nolines:
        lda     pt_flags
        and     #PT_ADDTHINGS
        beq     @nothings
        jsr     map_cell
        lda     #<pit_add_thing
        sta     bl_func
        lda     #>pit_add_thing
        sta     bl_func+1
        jsr     things_iter
        cmp     #0
        bne     @nothings
        jmp     @early
@nothings:
        ; mapx == xt2 && mapy == yt2: done
        lda     pt_mapx
        cmp     pt_xt2
        bne     @adv
        lda     pt_mapx+1
        cmp     pt_xt2+1
        bne     @adv
        lda     pt_mapy
        cmp     pt_yt2
        bne     @adv
        lda     pt_mapy+1
        cmp     pt_yt2+1
        beq     @walked
@adv:   ; (yintercept >> 16) == mapy: step x; else (xintercept >> 16) == mapx: step y
        lda     W+W_PTYINT+2
        cmp     pt_mapy
        bne     @tryx
        lda     W+W_PTYINT+3
        cmp     pt_mapy+1
        bne     @tryx
        ldx     #W_PTYINT
        ldy     #W_PTYSTEP
        jsr     w_add
        clc
        lda     pt_mapx
        adc     pt_mxstep
        sta     pt_mapx
        lda     pt_mapx+1
        adc     pt_mxstep+1
        sta     pt_mapx+1
        bra     @count
@tryx:  lda     W+W_PTXINT+2
        cmp     pt_mapx
        bne     @count
        lda     W+W_PTXINT+3
        cmp     pt_mapx+1
        bne     @count
        ldx     #W_PTXINT
        ldy     #W_PTXSTEP
        jsr     w_add
        clc
        lda     pt_mapy
        adc     pt_mystep
        sta     pt_mapy
        lda     pt_mapy+1
        adc     pt_mystep+1
        sta     pt_mapy+1
@count: inc     pt_count
        lda     pt_count
        cmp     #64
        bcs     @walked
        jmp     @step
@walked:
        lda     pt_trav
        sta     ti_func
        lda     pt_trav+1
        sta     ti_func+1
        jmp     traverse
@early: lda     #0
        tax
        rts

map_cell:
        lda     pt_mapx
        sta     bxl
        lda     pt_mapx+1
        sta     bxh
        lda     pt_mapy
        sta     byl
        lda     pt_mapy+1
        sta     byh
        rts

; one axis of P_PathTraverse: X = the start slot (W_PTX1 or _PTY1), Y = the
; end slot, A = the step slot of the other axis (W_PTYSTEP or _PTXSTEP);
; the direction is in the A of the preceding cmp16 (saved by the caller
; in pt_mxstep/pt_mystep, and still in tmp4 here). Leaves the other axis'
; step and W_FR = FixedMul(partial, step).
axis_setup:
        sta     as_step
        stx     as_start
        sty     as_end
        ; direction: the last cmp16 result was stored; read it back
        lda     as_start
        cmp     #W_PTX1
        bne     :+
        lda     pt_mxstep
        bra     @dir
:       lda     pt_mystep
@dir:   sta     as_dir
        cmp     #0
        beq     @zero
        ; step = FixedDiv(other end - other start, |end - start|)
        ldx     #W_T1
        ldy     as_end
        lda     as_start
        jsr     w_sub3
        ldx     #W_T1
        jsr     w_abs
        ; the other axis: the slots after PTX1/PTX2 are PTY1/PTY2
        lda     as_start
        cmp     #W_PTX1
        bne     @ofy
        ldy     #W_PTY2
        lda     #W_PTY1
        bra     @other
@ofy:   ldy     #W_PTX2
        lda     #W_PTX1
@other: ldx     #W_T0
        jsr     w_sub3
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_div
        ldx     as_step
        ldy     #W_FR
        jsr     w_mov
        ; partial = (start >> 7) & $FFFF, or FRACUNIT minus it going up
        ldx     #W_T2
        ldy     as_start
        jsr     sr7
        stz     W+W_T2+2
        stz     W+W_T2+3
        lda     as_dir
        bmi     @mul
        ldx     #W_T0
        jsr     w_ldi
        .dword  $10000
        ldx     #W_T0
        ldy     #W_T2
        jsr     w_sub
        ldx     #W_T2
        ldy     #W_T0
        jsr     w_mov
        bra     @mul
@zero:  ldx     #W_T2
        jsr     w_ldi
        .dword  $10000
        ldx     as_step
        jsr     w_ldi
        .dword  $1000000
@mul:   ldx     #W_T2
        ldy     as_step
        jmp     w_mul

.segment "BSS"
as_step:    .res 1
as_start:   .res 1
as_end:     .res 1
as_dir:     .res 1
.segment "CODE"

; W[X] += FRACUNIT if its low 16 bits are zero and ((its byte 2) - A) & $7F is 0
nudge:  sta     tmp1
        lda     W,x
        ora     W+1,x
        bne     @no
        sec
        lda     W+2,x
        sbc     tmp1
        and     #$7F
        bne     @no
        inc     W+2,x
        bne     @no
        inc     W+3,x
@no:    rts

; W[X] -= FIX(bmaporgx) / FIX(bmaporgy)
sub_orgx:
        lda     _bmaporgx
        ldy     _bmaporgx+1
        bra     sub_org
sub_orgy:
        lda     _bmaporgy
        ldy     _bmaporgy+1
sub_org:
        sta     tmp1
        sec
        lda     W+2,x
        sbc     tmp1
        sta     W+2,x
        tya
        sta     tmp1
        lda     W+3,x
        sbc     tmp1
        sta     W+3,x
        rts

; A/X = W[X] >> 23 (arithmetic): low = bits 23-30, high = copies of bit 31
shr23:  lda     W+2,x
        asl     a
        lda     W+3,x
        rol     a
        pha
        lda     W+3,x
        and     #$80
        beq     :+
        lda     #$FF
:       tax
        pla
        rts

; W[X] = W[Y] >> 7 (arithmetic)
sr7:    lda     W,y
        asl     a
        lda     W+1,y
        rol     a
        sta     W,x
        lda     W+2,y
        rol     a
        sta     W+1,x
        lda     W+3,y
        rol     a
        sta     W+2,x
        lda     W+3,y
        and     #$80
        beq     :+
        lda     #$FF
:       sta     W+3,x
        rts

; A = the sign of (A/X - ptr1) as int16s: $FF, 0, 1
cmp16:  cpx     ptr1+1
        bne     @hi
        cmp     ptr1
        beq     @eq
        bcc     @lt
        lda     #1
        rts
@hi:    txa
        sec
        sbc     ptr1+1
        bvc     :+
        eor     #$80
:       bmi     @lt
        lda     #1
        rts
@lt:    lda     #$FF
        rts
@eq:    lda     #0
        rts

.endif ; DD_MAPDIR
