; Doom for the Appletini -- line of sight, 6502 (docs/DESIGN.md section 9).
;
; The assembly twin of p_sight.c (the C is the reference, compiled on the
; host; read it for the why): P_CheckSight is vanilla's REJECT test, then
; the BSP walk along the sight line with an explicit stack of the "other
; side" children, crossing in each subsector the linedefs of its segs.
;
;   boolean P_CheckSight(mobj_t *t1, mobj_t *t2)     cc65 __fastcall__
;   check_sight   sg_t1, sg_t2 -> A = 0/1 (and Z)
;   sight_reset   at level start (the subsector cache)
;
; How it is fast enough (a monster looks every few tics; a walk visits
; some 30 nodes, 15 subsectors and 20 lines on E1M1):
;
;   - vanilla's P_DivlineSide needs only whole units: every divline it
;     meets has either whole-unit fields (a node, a line) or is the sight
;     line, and every point has either a whole-unit position (a vertex) or
;     is one of the two ends. So each test is two 16-bit differences and
;     two 16 x 16 products (quarter squares, mul8), with no products at
;     all when their signs already decide; the few fixed-point facts the
;     tests need (an end's fraction is zero; the ceiling of an end) are
;     taken once per walk.
;   - a subsector's line numbers are cached (SSL_SLOTS lists of up to
;     SSL_MAX); otherwise a seg gives only its linedef (a 2-byte far read).
;     The line comes from the line cache and is marked (the core's line
;     marks, vanilla's validcount), so a line is tested once per walk.
;   - the fixed-point work (the intercept and the slopes: four FixedMul
;     and up to three FixedDiv) only for a two-sided line the sight line
;     really crosses, whose sectors differ in height.
;
; It calls nothing that calls back (far reads, the caches, the line marks,
; fx_mul/fx_div), so its state is plain variables. topslope and
; bottomslope are the attack code's W slots, as in vanilla. For the py65
; harness this code may sit in a code-only window (MCODE, gmacros.inc).

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR

.globalzp far_ptr, far_len
.import lev_addr, lev_idx, lev_far, far_rd, line_get, line_checked, new_validcount, mul8
.import node_get, nc_x_lo, nc_x_hi, nc_y_lo, nc_y_hi, nc_dx_lo, nc_dx_hi, nc_dy_lo, nc_dy_hi
.import nc_c0_lo, nc_c0_hi, nc_c1_lo, nc_c1_hi
.import fx_mul, fx_div, fxa, fxb, fxr, w_cmp, w_mov
.import _P_RejectVisible, _numnodes, _sec_floorh, _sec_ceilh
.import pushax, popax

.export _P_CheckSight, check_sight, sg_t1, sg_t2, sight_reset

SIGHTSTACK  = 64                    ; pending BSP children (E1's deepest BSP: 43)
.ifndef SSL_SLOTS
SSL_SLOTS   = 32                    ; subsectors whose line lists are cached (a power of 2)
.endif
SSL_MAX     = 8                     ; lines in a cached list (SSL_SLOTS * SSL_MAX <= 256)

.segment "BSS"
sg_t1:      .res 2
sg_t2:      .res 2
sg_zs:      .res 4                  ; sightzstart
st_x:       .res 4                  ; strace (fixed): t1's x, y; t2 - t1
st_y:       .res 4
st_dx:      .res 4
st_dy:      .res 4
sg_t2x:     .res 4
sg_t2y:     .res 4
; the ends as side_pl sees them, [0] t1, [1] t2: whole units, and 0 if
; the fraction is 0
e_xh_lo:    .res 2
e_xh_hi:    .res 2
e_xf:       .res 2
e_yh_lo:    .res 2
e_yh_hi:    .res 2
e_yf:       .res 2
; the sight line as side_vs sees it: its dx, dy >> 16, whether they are
; 0, and t1's ceiling (whole units)
s_dxh:      .res 2
s_dyh:      .res 2
s_dxz:      .res 1                  ; 0: dx == 0
s_dyz:      .res 1
s_xc:       .res 2                  ; ceil(t1.x), ceil(t1.y)
s_yc:       .res 2
; a divline of whole units (a node, a line)
l_x:        .res 2
l_y:        .res 2
l_dx:       .res 2
l_dy:       .res 2
; the general test's operands: left = a * b, right = c * d
sd_a:       .res 2
sd_b:       .res 2
sd_c:       .res 2
sd_d:       .res 2
sd_cls:     .res 1                  ; the sign class of left (-1, 0, 1)
sd_left:    .res 4
mu_a:       .res 2                  ; smul16's operands and product
mu_b:       .res 2
mu_r:       .res 4
mu_neg:     .res 1
sg_stack_lo: .res SIGHTSTACK
sg_stack_hi: .res SIGHTSTACK
sg_depth:   .res 1
sg_node:    .res 2
sg_slot:    .res 1
sg_side:    .res 1
cs_hdr:                             ; the SSECTOR record's first 4 bytes
cs_count:   .res 2
cs_seg:     .res 2
cs_line:    .res 2
cs_ss:      .res 2                  ; the subsector
cs_slot:    .res 1                  ; its slot in the line-list cache
cs_i:       .res 1                  ; the next line of the slot; bit 7: no slot, read segs
; the subsectors' line lists (direct mapped by number; lists of up to
; SSL_MAX lines, most subsectors' 1-6; longer ones are read each time)
ssl_key_lo: .res SSL_SLOTS
ssl_key_hi: .res SSL_SLOTS          ; $FFxx: empty
ssl_count:  .res SSL_SLOTS
ssl_lo:     .res SSL_SLOTS * SSL_MAX
ssl_hi:     .res SSL_SLOTS * SSL_MAX
cs_ff:      .res 2                  ; the floors and ceilings of the line's sectors
cs_bf:      .res 2
cs_fc:      .res 2
cs_bc:      .res 2
cs_top:     .res 2                  ; the opening (whole units)
cs_bot:     .res 2
cs_diff:    .res 1                  ; bit 0: floors differ, bit 1: ceilings differ
sg_frac:    .res 4
sg_num:     .res 4

MONCODE

; ---- P_CheckSight -------------------------------------------------------------------------
_P_CheckSight:
        sta     sg_t2
        stx     sg_t2+1
        jsr     popax
        sta     sg_t1
        stx     sg_t1+1
        jsr     check_sight
        ldx     #0
        rts

check_sight:
        ; first check for trivial rejection: REJECT[t1's sector][t2's sector]
        lda     sg_t1
        sta     gmo
        lda     sg_t1+1
        sta     gmo+1
        ldy     #MO_SECTOR
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tax
        pla
        jsr     pushax
        lda     sg_t2
        sta     gpt
        lda     sg_t2+1
        sta     gpt+1
        ldy     #MO_SECTOR+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        jsr     _P_RejectVisible
        cmp     #0
        bne     :+
        rts                             ; A = 0: can't possibly be connected
:       jsr     new_validcount
        ; sightzstart = t1's z + height - (height >> 2)
        lda     sg_t1
        sta     gmo
        lda     sg_t1+1
        sta     gmo+1
        lda     sg_t2
        sta     gpt
        lda     sg_t2+1
        sta     gpt+1
        ldy     #MO_HEIGHT
        ldx     #0
:       lda     (gmo),y
        sta     fxa,x                   ; (scratch: fxa = height, fxb = height >> 2)
        sta     fxb,x
        iny
        inx
        cpx     #4
        bne     :-
        ldx     #2
:       lda     fxb+3
        cmp     #$80
        ror     fxb+3
        ror     fxb+2
        ror     fxb+1
        ror     fxb
        dex
        bne     :-
        ldy     #MO_Z
        clc
        ldx     #0
:       lda     (gmo),y
        adc     fxa,x
        sta     sg_zs,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        sub32   sg_zs, sg_zs, fxb
        ; t1's and t2's x, y
        ldy     #MO_X
        ldx     #0
:       lda     (gmo),y
        sta     st_x,x                  ; (st_y follows st_x, MO_Y follows MO_X)
        lda     (gpt),y
        sta     sg_t2x,x                ; (sg_t2y follows sg_t2x)
        iny
        inx
        cpx     #8
        bne     :-
.assert MO_Y = MO_X + 4 && st_y = st_x + 4 && sg_t2y = sg_t2x + 4, error, "x, y"
        ; the slopes to t2's top and bottom
        ldy     #MO_Z
        ldx     #0
:       lda     (gpt),y
        sta     W+W_BOTTOMSLOPE,x
        iny
        inx
        cpx     #4
        bne     :-
        ldy     #MO_HEIGHT
        clc
        ldx     #0
:       lda     (gpt),y
        adc     W+W_BOTTOMSLOPE,x
        sta     W+W_TOPSLOPE,x
        iny
        inx
        txa
        eor     #4
        bne     :-
        sub32   W+W_TOPSLOPE, W+W_TOPSLOPE, sg_zs
        sub32   W+W_BOTTOMSLOPE, W+W_BOTTOMSLOPE, sg_zs
        ; strace.dx, dy = t2 - t1
        sub32   st_dx, sg_t2x, st_x
        sub32   st_dy, sg_t2y, st_y
        ; what the side tests need of them
        jsr     prepare
        jmp     cross_bsp

; the ends' whole units and zero fractions; the sight line's whole units
; and zero facts, t1's ceiling
prepare:
        lda     st_x+2                  ; t1
        sta     e_xh_lo
        lda     st_x+3
        sta     e_xh_hi
        lda     st_x
        ora     st_x+1
        sta     e_xf
        lda     st_y+2
        sta     e_yh_lo
        lda     st_y+3
        sta     e_yh_hi
        lda     st_y
        ora     st_y+1
        sta     e_yf
        lda     sg_t2x+2                ; t2
        sta     e_xh_lo+1
        lda     sg_t2x+3
        sta     e_xh_hi+1
        lda     sg_t2x
        ora     sg_t2x+1
        sta     e_xf+1
        lda     sg_t2y+2
        sta     e_yh_lo+1
        lda     sg_t2y+3
        sta     e_yh_hi+1
        lda     sg_t2y
        ora     sg_t2y+1
        sta     e_yf+1
        lda     st_dx+2
        sta     s_dxh
        lda     st_dx+3
        sta     s_dxh+1
        lda     st_dy+2
        sta     s_dyh
        lda     st_dy+3
        sta     s_dyh+1
        lda     st_dx
        ora     st_dx+1
        ora     st_dx+2
        ora     st_dx+3
        sta     s_dxz
        lda     st_dy
        ora     st_dy+1
        ora     st_dy+2
        ora     st_dy+3
        sta     s_dyz
        ; ceil(t1) = whole part + (fraction != 0)
        lda     e_xf
        cmp     #1                      ; C = fraction != 0
        lda     st_x+2
        adc     #0
        sta     s_xc
        lda     st_x+3
        adc     #0
        sta     s_xc+1
        lda     e_yf
        cmp     #1
        lda     st_y+2
        adc     #0
        sta     s_yc
        lda     st_y+3
        adc     #0
        sta     s_yc+1
        rts

; ---- the side tests (vanilla P_DivlineSide) ----------------------------------------------
; side_pl: the end X (0 t1, 1 t2) against the whole-unit divline l_* -> A
; (0 front, 1 back, 2 on). The end's position is fixed and the divline's
; origin whole, so (x - l.x) >> 16 is the end's whole part minus l.x.
side_pl:
        lda     l_dx
        ora     l_dx+1
        bne     @notv
        ; vertical: x == l.x: on; x <= l.x: back iff l.dy > 0
        lda     e_xh_lo,x
        cmp     l_x
        bne     @vlt
        lda     e_xh_hi,x
        cmp     l_x+1
        bne     @vlt
        lda     e_xf,x
        beq     @on                     ; x == l.x exactly
        bra     @vgt                    ; (a fraction above l.x)
@vlt:   lda     e_xh_lo,x               ; the whole parts differ: x < l.x?
        cmp     l_x
        lda     e_xh_hi,x
        sbc     l_x+1
        bvc     :+
        eor     #$80
:       bpl     @vgt
        lda     l_dy+1                  ; x <= l.x: l.dy > 0
        bmi     @zero
        ora     l_dy
        beq     @zero
        bra     @one
@vgt:   lda     l_dy+1                  ; x > l.x: l.dy < 0
        bmi     @one
@zero:  lda     #0
        rts
@one:   lda     #1
        rts
@on:    lda     #2
        rts
@notv:  lda     l_dy
        ora     l_dy+1
        bne     @gen
        ; horizontal: x == l.y (sic): on; y <= l.y: back iff l.dx < 0
        lda     e_xh_lo,x
        cmp     l_y
        bne     @hy
        lda     e_xh_hi,x
        cmp     l_y+1
        bne     @hy
        lda     e_xf,x
        beq     @on
@hy:    lda     e_yh_lo,x
        cmp     l_y
        bne     @hlt
        lda     e_yh_hi,x
        cmp     l_y+1
        bne     @hlt
        lda     e_yf,x
        beq     @hle                    ; y == l.y exactly
        bra     @hgt
@hlt:   lda     e_yh_lo,x
        cmp     l_y
        lda     e_yh_hi,x
        sbc     l_y+1
        bvc     :+
        eor     #$80
:       bpl     @hgt
@hle:   lda     l_dx+1                  ; y <= l.y: l.dx < 0
        bmi     @one
        bra     @zero
@hgt:   lda     l_dx+1                  ; y > l.y: l.dx > 0 (l.dx != 0 here)
        bmi     @zero
        bra     @one
@gen:   ; left = l.dy * (x - l.x), right = (y - l.y) * l.dx
        sec
        lda     e_xh_lo,x
        sbc     l_x
        sta     sd_b
        lda     e_xh_hi,x
        sbc     l_x+1
        sta     sd_b+1
        sec
        lda     e_yh_lo,x
        sbc     l_y
        sta     sd_c
        lda     e_yh_hi,x
        sbc     l_y+1
        sta     sd_c+1
        lda     l_dy
        sta     sd_a
        lda     l_dy+1
        sta     sd_a+1
        lda     l_dx
        sta     sd_d
        lda     l_dx+1
        sta     sd_d+1
        jmp     side_gen

; side_vs: the vertex at (gli)+Y (whole units x, y) against the sight
; line -> A. The vertex is whole and the line's origin t1 fixed: the whole
; part of v - t1 is v minus t1's ceiling.
side_vs:
        lda     (gli),y
        sta     sd_b                    ; (v.x, v.y while the cases look)
        iny
        lda     (gli),y
        sta     sd_b+1
        iny
        lda     (gli),y
        sta     sd_c
        iny
        lda     (gli),y
        sta     sd_c+1
; the same for the vertex (sd_b, sd_c)
side_vs_bc:
        lda     s_dxz
        bne     @notv
        ; vertical: v.x == t1.x: on; v.x <= t1.x: back iff dy > 0
        lda     sd_b
        cmp     e_xh_lo
        bne     @vlt
        lda     sd_b+1
        cmp     e_xh_hi
        bne     @vlt
        lda     e_xf
        beq     @on
        bra     @vle                    ; (v.x = t1's whole part, t1 above it)
@vlt:   lda     e_xh_lo                 ; v.x <= t1.x iff v.x <= t1's whole part
        cmp     sd_b
        lda     e_xh_hi
        sbc     sd_b+1
        bvc     :+
        eor     #$80
:       bmi     @vgt
@vle:   lda     st_dy+3                 ; dy > 0
        bmi     @zero
        lda     s_dyz
        beq     @zero
        bra     @one
@vgt:   lda     st_dy+3                 ; dy < 0
        bmi     @one
@zero:  lda     #0
        rts
@one:   lda     #1
        rts
@on:    lda     #2
        rts
@notv:  lda     s_dyz
        bne     @gen
        ; horizontal: v.x == t1.y (sic): on; v.y <= t1.y: back iff dx < 0
        lda     sd_b
        cmp     e_yh_lo
        bne     @hy
        lda     sd_b+1
        cmp     e_yh_hi
        bne     @hy
        lda     e_yf
        beq     @on
@hy:    lda     e_yh_lo                 ; v.y <= t1's whole part
        cmp     sd_c
        lda     e_yh_hi
        sbc     sd_c+1
        bvc     :+
        eor     #$80
:       bmi     @hgt
        lda     st_dx+3                 ; dx < 0
        bmi     @one
        bra     @zero
@hgt:   lda     st_dx+3                 ; dx > 0 (dx != 0 here)
        bmi     @zero
        bra     @one
@gen:   ; b = v.x - ceil(t1.x), c = v.y - ceil(t1.y); a, d = dy, dx >> 16
        sec
        lda     sd_b
        sbc     s_xc
        sta     sd_b
        lda     sd_b+1
        sbc     s_xc+1
        sta     sd_b+1
        sec
        lda     sd_c
        sbc     s_yc
        sta     sd_c
        lda     sd_c+1
        sbc     s_yc+1
        sta     sd_c+1
        lda     s_dyh
        sta     sd_a
        lda     s_dyh+1
        sta     sd_a+1
        lda     s_dxh
        sta     sd_d
        lda     s_dxh+1
        sta     sd_d+1
; left = a * b, right = c * d: 0 if right < left, 2 if equal, else 1.
; The sign classes (-1, 0, 1) of the two products decide when they differ.
side_gen:
        lda     sd_a
        ora     sd_a+1
        beq     @l0
        lda     sd_b
        ora     sd_b+1
        beq     @l0
        lda     sd_a+1
        eor     sd_b+1
        bmi     @lneg
        lda     #1
        bra     @lset
@lneg:  lda     #$FF
        bra     @lset
@l0:    lda     #0
@lset:  sta     sd_cls
        lda     sd_c
        ora     sd_c+1
        beq     @r0
        lda     sd_d
        ora     sd_d+1
        beq     @r0
        lda     sd_c+1
        eor     sd_d+1
        bmi     @rneg
        lda     #1
        bra     @rset
@rneg:  lda     #$FF
        bra     @rset
@r0:    lda     #0
@rset:  cmp     sd_cls
        beq     @same
        sec                             ; class(right) < class(left): front
        sbc     sd_cls
        bmi     @front
        lda     #1
        rts
@front: lda     #0
        rts
@same:  cmp     #0
        bne     @mul
        lda     #2                      ; both 0
        rts
@mul:   lda     sd_a
        sta     mu_a
        lda     sd_a+1
        sta     mu_a+1
        lda     sd_b
        sta     mu_b
        lda     sd_b+1
        sta     mu_b+1
        jsr     smul16
        mov32   sd_left, mu_r
        lda     sd_c
        sta     mu_a
        lda     sd_c+1
        sta     mu_a+1
        lda     sd_d
        sta     mu_b
        lda     sd_d+1
        sta     mu_b+1
        jsr     smul16                  ; mu_r = right
        sec                             ; right - left
        lda     mu_r
        sbc     sd_left
        sta     mu_a
        lda     mu_r+1
        sbc     sd_left+1
        ora     mu_a
        sta     mu_a
        lda     mu_r+2
        sbc     sd_left+2
        ora     mu_a
        sta     mu_a
        lda     mu_r+3
        sbc     sd_left+3
        tay
        bvc     :+
        eor     #$80
:       jmi     @front
        tya
        ora     mu_a
        beq     :+
        lda     #1                      ; back side
        rts
:       lda     #2                      ; left == right: on
        rts

; ---- smul16: mu_r = mu_a * mu_b, signed 16 x 16 -> 32 --------------------------------------
smul16: lda     mu_a+1
        eor     mu_b+1
        sta     mu_neg
        lda     mu_a+1
        bpl     :+
        sec
        lda     #0
        sbc     mu_a
        sta     mu_a
        lda     #0
        sbc     mu_a+1
        sta     mu_a+1
:       lda     mu_b+1
        bpl     :+
        sec
        lda     #0
        sbc     mu_b
        sta     mu_b
        lda     #0
        sbc     mu_b+1
        sta     mu_b+1
:       ; |a| * |b| by byte pairs (mul8: A * X -> A low, X high); a zero
        ; high byte skips its two
        lda     mu_a
        ldx     mu_b
        jsr     mul8
        sta     mu_r
        stx     mu_r+1
        stz     mu_r+2
        stz     mu_r+3
        lda     mu_a+1
        beq     @b1
        ldx     mu_b
        jsr     mul8
        clc
        adc     mu_r+1
        sta     mu_r+1
        txa
        adc     #0
        sta     mu_r+2
        lda     mu_b+1
        beq     @sign
        lda     mu_a+1
        ldx     mu_b+1
        jsr     mul8
        clc
        adc     mu_r+2
        sta     mu_r+2
        txa
        adc     #0
        sta     mu_r+3
@b1:    lda     mu_b+1
        beq     @sign
        lda     mu_a
        ldx     mu_b+1
        jsr     mul8
        clc
        adc     mu_r+1
        sta     mu_r+1
        txa
        adc     mu_r+2
        sta     mu_r+2
        bcc     @sign
        inc     mu_r+3
@sign:  bit     mu_neg
        bpl     :+
        neg32   mu_r, mu_r
:       rts

; ---- the BSP walk (vanilla P_CrossBSPNode (numnodes - 1)) -------------------------------------
cross_bsp:
        stz     sg_depth
        lda     _numnodes
        ora     _numnodes+1
        bne     :+
        lda     #0
        tax
        jmp     cross_sub
:       sec
        lda     _numnodes
        sbc     #1
        sta     sg_node
        lda     _numnodes+1
        sbc     #0
        sta     sg_node+1
@down:  lda     sg_node+1
        jmi     @leaf
        lda     sg_node
        ldx     sg_node+1
        jsr     node_get
        stx     sg_slot
        lda     nc_x_lo,x               ; the partition
        sta     l_x
        lda     nc_x_hi,x
        sta     l_x+1
        lda     nc_y_lo,x
        sta     l_y
        lda     nc_y_hi,x
        sta     l_y+1
        lda     nc_dx_lo,x
        sta     l_dx
        lda     nc_dx_hi,x
        sta     l_dx+1
        lda     nc_dy_lo,x
        sta     l_dy
        lda     nc_dy_hi,x
        sta     l_dy+1
        ; the side of the start (an "on" crosses both sides: the front first)
        ldx     #0
        jsr     side_pl
        cmp     #2
        bne     :+
        lda     #0
:       sta     sg_side
        ; the side of the end: if another, the other child after this one
        ldx     #1
        jsr     side_pl
        ldx     sg_slot
        cmp     sg_side
        beq     @first
        ldy     sg_depth
        cpy     #SIGHTSTACK
        bcs     @first
        lda     sg_side
        bne     :+
        lda     nc_c1_lo,x
        sta     sg_stack_lo,y
        lda     nc_c1_hi,x
        sta     sg_stack_hi,y
        bra     @push
:       lda     nc_c0_lo,x
        sta     sg_stack_lo,y
        lda     nc_c0_hi,x
        sta     sg_stack_hi,y
@push:  inc     sg_depth
@first: lda     sg_side
        bne     :+
        lda     nc_c0_lo,x
        sta     sg_node
        lda     nc_c0_hi,x
        sta     sg_node+1
        jmp     @down
:       lda     nc_c1_lo,x
        sta     sg_node
        lda     nc_c1_hi,x
        sta     sg_node+1
        jmp     @down
@leaf:  and     #$7F
        tax
        lda     sg_node
        jsr     cross_sub
        beq     @done                   ; blocked: false
        ldy     sg_depth
        beq     @done                   ; A = 1: every subsector passed
        dey
        sty     sg_depth
        lda     sg_stack_lo,y
        sta     sg_node
        lda     sg_stack_hi,y
        sta     sg_node+1
        jmp     @down
@done:  rts

; ---- a subsector (vanilla P_CrossSubsector): A/X = its number -> A = 0/1 (and Z) --------------
cross_sub:
        sta     cs_ss
        stx     cs_ss+1
        and     #SSL_SLOTS - 1
        sta     cs_slot
        tax
        lda     ssl_key_lo,x
        cmp     cs_ss
        bne     @fetch
        lda     ssl_key_hi,x
        cmp     cs_ss+1
        bne     @fetch
        lda     ssl_count,x             ; cached: its lines' numbers
        sta     cs_count
        stz     cs_i
        bra     @seg
@fetch: ; the SSECTOR record: numsegs, firstseg
        lda     cs_ss
        sta     lev_idx
        lda     cs_ss+1
        sta     lev_idx+1
        lda     #MAPARR_SSECTORS
        jsr     lev_addr
        lda     #<cs_hdr
        sta     far_ptr
        lda     #>cs_hdr
        sta     far_ptr+1
        lda     #4
        sta     far_len
        stz     far_len+1
        jsr     far_rd                  ; cs_count = numsegs, cs_seg = firstseg
        lda     #$80                    ; (not cached: read seg by seg)
        sta     cs_i
        lda     cs_count+1
        bne     @seg
        lda     cs_count
        cmp     #SSL_MAX + 1
        bcs     @seg
        ; a short list: its lines into the slot, then from there
        ldx     cs_slot
        lda     cs_ss
        sta     ssl_key_lo,x
        lda     cs_ss+1
        sta     ssl_key_hi,x
        lda     cs_count
        sta     ssl_count,x
        stz     cs_i
@fill:  lda     cs_i
        cmp     cs_count
        beq     @filled
        jsr     seg_line
        lda     cs_slot
        asl     a
        asl     a
        asl     a
        ora     cs_i
        tax
        lda     cs_line
        sta     ssl_lo,x
        lda     cs_line+1
        sta     ssl_hi,x
        inc     cs_i
        bra     @fill
@filled:
        stz     cs_i
@seg:   ; the next line: from the slot, or read from the next seg
        bit     cs_i
        bmi     @read
        lda     cs_i
        cmp     cs_count
        bne     :+
        lda     #1                      ; passed the subsector
        rts
:       lda     cs_slot
        asl     a
        asl     a
        asl     a
        ora     cs_i
        tax
        lda     ssl_lo,x
        sta     cs_line
        lda     ssl_hi,x
        sta     cs_line+1
        inc     cs_i
        bra     @line
@read:  lda     cs_count
        ora     cs_count+1
        bne     :+
        lda     #1
        rts
:       lda     cs_count
        bne     :+
        dec     cs_count+1
:       dec     cs_count
        jsr     seg_line
@line:  ; already checked (from its other side)?
        lda     cs_line
        ldx     cs_line+1
        jsr     line_checked
        bcs     @seg
        lda     cs_line
        ldx     cs_line+1
        jsr     line_get
        ; its two ends against the sight line (v2 = v1 + d)
        ldy     #LI_V1X
        jsr     side_vs
        sta     sg_side
        clc
        ldy     #LI_V1X
        lda     (gli),y
        ldy     #LI_DX
        adc     (gli),y
        sta     sd_b
        ldy     #LI_V1X+1
        lda     (gli),y
        ldy     #LI_DX+1
        adc     (gli),y
        sta     sd_b+1
        clc
        ldy     #LI_V1Y
        lda     (gli),y
        ldy     #LI_DY
        adc     (gli),y
        sta     sd_c
        ldy     #LI_V1Y+1
        lda     (gli),y
        ldy     #LI_DY+1
        adc     (gli),y
        sta     sd_c+1
        jsr     side_vs_bc
        cmp     sg_side
        jeq     @seg                    ; the line isn't crossed
        ; the sight line's ends against the line
        ldy     #LI_V1X
        ldx     #0
:       lda     (gli),y                 ; l_x, l_y, l_dx, l_dy = v1x, v1y, dx, dy
        sta     l_x,x
        iny
        inx
        cpx     #8
        bne     :-
.assert LI_V1Y = LI_V1X + 2 && LI_DX = LI_V1X + 4 && LI_DY = LI_V1X + 6, error, "line_t"
.assert l_y = l_x + 2 && l_dx = l_x + 4 && l_dy = l_x + 6, error, "l_*"
        ldx     #0
        jsr     side_pl
        sta     sg_side
        ldx     #1
        jsr     side_pl
        cmp     sg_side
        jeq     @seg
        ; an "impassible glass" line (no back sector), or one-sided: blocks
        ldy     #LI_BACKSECTOR+1
        lda     (gli),y
        dey
        and     (gli),y
        cmp     #$FF
        jeq     @block
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        jeq     @block
        ; the heights of its two sectors
        ldy     #LI_FRONTSECTOR
        jsr     sec_heights
        stx     cs_ff
        sta     cs_ff+1
        lda     tmp1
        sta     cs_fc
        lda     tmp2
        sta     cs_fc+1
        ldy     #LI_BACKSECTOR
        jsr     sec_heights
        stx     cs_bf
        sta     cs_bf+1
        lda     tmp1
        sta     cs_bc
        lda     tmp2
        sta     cs_bc+1
        stz     cs_diff
        lda     cs_ff
        cmp     cs_bf
        bne     :+
        lda     cs_ff+1
        cmp     cs_bf+1
        beq     :++
:       inc     cs_diff                 ; bit 0: the floors differ
:       lda     cs_fc
        cmp     cs_bc
        bne     :+
        lda     cs_fc+1
        cmp     cs_bc+1
        beq     :++
:       lda     cs_diff
        ora     #2
        sta     cs_diff
:       lda     cs_diff
        jeq     @seg                    ; no wall to block sight with
        ; the opening: the lower ceiling, the higher floor
        lda     cs_fc
        cmp     cs_bc
        lda     cs_fc+1
        sbc     cs_bc+1
        bvc     :+
        eor     #$80
:       bmi     @fclow
        lda     cs_bc
        sta     cs_top
        lda     cs_bc+1
        sta     cs_top+1
        bra     @bot
@fclow: lda     cs_fc
        sta     cs_top
        lda     cs_fc+1
        sta     cs_top+1
@bot:   lda     cs_ff
        cmp     cs_bf
        lda     cs_ff+1
        sbc     cs_bf+1
        bvc     :+
        eor     #$80
:       bpl     @ffhigh
        lda     cs_bf
        sta     cs_bot
        lda     cs_bf+1
        sta     cs_bot+1
        bra     @open
@ffhigh:
        lda     cs_ff
        sta     cs_bot
        lda     cs_ff+1
        sta     cs_bot+1
@open:  ; openbottom >= opentop: a closed door
        lda     cs_bot
        cmp     cs_top
        lda     cs_bot+1
        sbc     cs_top+1
        bvc     :+
        eor     #$80
:       bpl     @block
        jsr     intercept2              ; sg_frac
        lda     cs_diff
        lsr     a
        bcc     @ceil
        ; slope = FixedDiv(openbottom - sightzstart, frac) > bottomslope?
        lda     cs_bot
        ldx     cs_bot+1
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        bmi     @ceil
        beq     @ceil
        ldx     #W_BOTTOMSLOPE
        ldy     #W_FR
        jsr     w_mov
@ceil:  lda     cs_diff
        and     #2
        beq     @test
        lda     cs_top
        ldx     cs_top+1
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_TOPSLOPE
        jsr     w_cmp
        bpl     @test
        ldx     #W_TOPSLOPE
        ldy     #W_FR
        jsr     w_mov
@test:  ldx     #W_TOPSLOPE             ; topslope <= bottomslope: blocked
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        bmi     @block
        beq     @block
        jmp     @seg
@block: lda     #0
        rts

; cs_line = the linedef of the seg cs_seg (a 2-byte far read); cs_seg + 1
seg_line:
        lda     cs_seg
        sta     lev_idx
        lda     cs_seg+1
        sta     lev_idx+1
        inc     cs_seg
        bne     :+
        inc     cs_seg+1
:       lda     #MAPARR_SEGS
        jsr     lev_addr
        clc
        lda     lev_far
        adc     #SEG_LINEDEF
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<cs_line
        sta     far_ptr
        lda     #>cs_line
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jmp     far_rd

; sight_reset: at level start, the subsector cache forgets its lists
sight_reset:
        ldx     #SSL_SLOTS - 1
        lda     #$FF
:       sta     ssl_key_hi,x
        dex
        bpl     :-
        rts

; the sector whose index is at (gli)+Y: X/A = its floor (low/high),
; tmp1/tmp2 its ceiling
sec_heights:
        lda     (gli),y
        asl     a
        sta     ptr1
        iny
        lda     (gli),y
        rol     a
        sta     ptr1+1
        clc
        lda     _sec_ceilh
        adc     ptr1
        sta     ptr2
        lda     _sec_ceilh+1
        adc     ptr1+1
        sta     ptr2+1
        clc
        lda     _sec_floorh
        adc     ptr1
        sta     ptr1
        lda     _sec_floorh+1
        adc     ptr1+1
        sta     ptr1+1
        lda     (ptr2)
        sta     tmp1
        ldy     #1
        lda     (ptr2),y
        sta     tmp2
        lda     (ptr1),y
        pha
        lda     (ptr1)
        tax
        pla
        rts

; W_FR = FixedDiv(FIX(A/X) - sightzstart, frac)
slope_to:
        stz     fxa
        stz     fxa+1
        sta     fxa+2
        stx     fxa+3
        sub32   fxa, fxa, sg_zs
        mov32   fxb, sg_frac
        jmp     fx_div

; ---- vanilla P_InterceptVector2 (strace, divl): sg_frac -----------------------------------------
; den = FixedMul(divl.dy >> 8, strace.dx) - FixedMul(divl.dx >> 8, strace.dy)
; num = FixedMul((divl.x - strace.x) >> 8, divl.dy) + FixedMul((strace.y - divl.y) >> 8, divl.dx)
; divl is the line, whole units (l_*): divl.dy >> 8 is dy << 8 and
; divl.dy itself dy << 16
intercept2:
        ldx     #l_dy - l_x             ; divl.dy >> 8
        jsr     units_sh8
        mov32   fxb, st_dx
        jsr     fx_mul
        mov32   sg_frac, fxr            ; (den so far)
        ldx     #l_dx - l_x             ; divl.dx >> 8
        jsr     units_sh8
        mov32   fxb, st_dy
        jsr     fx_mul
        sub32   sg_frac, sg_frac, fxr   ; den
        lda     sg_frac
        ora     sg_frac+1
        ora     sg_frac+2
        ora     sg_frac+3
        bne     :+
        rts                             ; parallel: 0
:       ; ((l.x << 16) - strace.x) >> 8
        ldx     #l_x - l_x
        jsr     units_fix
        sub32   fxa, fxa, st_x
        jsr     fxa_sar8
        ldx     #l_dy - l_x
        jsr     units_fixb
        jsr     fx_mul
        mov32   sg_num, fxr
        ; (strace.y - (l.y << 16)) >> 8
        ldx     #l_y - l_x
        jsr     units_fix
        sub32   fxa, st_y, fxa
        jsr     fxa_sar8
        ldx     #l_dx - l_x
        jsr     units_fixb
        jsr     fx_mul
        add32   fxa, sg_num, fxr        ; num
        mov32   fxb, sg_frac
        jsr     fx_div
        mov32   sg_frac, fxr
        rts

; fxa = the l_* word at X << 8
units_sh8:
        stz     fxa
        lda     l_x,x
        sta     fxa+1
        lda     l_x+1,x
        sta     fxa+2
        asl     a                       ; its sign
        lda     #0
        adc     #$FF
        eor     #$FF
        sta     fxa+3
        rts

; fxa / fxb = the l_* word at X << 16
units_fix:
        stz     fxa
        stz     fxa+1
        lda     l_x,x
        sta     fxa+2
        lda     l_x+1,x
        sta     fxa+3
        rts
units_fixb:
        stz     fxb
        stz     fxb+1
        lda     l_x,x
        sta     fxb+2
        lda     l_x+1,x
        sta     fxb+3
        rts

; fxa >>= 8 (arithmetic)
fxa_sar8:
        lda     fxa+1
        sta     fxa
        lda     fxa+2
        sta     fxa+1
        lda     fxa+3
        sta     fxa+2
        asl     a
        lda     #0
        adc     #$FF
        eor     #$FF
        sta     fxa+3
        rts

.endif
