; Doom for the Appletini -- visplanes, floors, ceilings and the sky
; (docs/DESIGN.md section 7; tools/refrender.py find_plane, check_plane,
; draw_planes, make_spans, map_plane, draw_sky_column; _animate).
;
; Visplanes: MAXVISPLANES of them. The header of each (height, flat,
; light, minx, maxx) is in main memory; the column arrays (top and bottom
; row of each column, index x + 1 for columns -1..160, top $FF = unused)
; are in RENDER_BANK at PL_TOP + p * PL_SIZE (rdefs.inc). Only columns
; within [minx - 1, maxx + 1] are ever read, so a plane's arrays are
; initialised as its range grows: check_plane writes $FF/0 into the
; columns it adds (RAMWRT on, at once, since the other plane of the same
; wall range may be this one), the seg loop gathers a wall range's marks
; in main memory (rsegs.s) and plane_store copies them at the end of the
; range. draw_planes copies a plane's columns back (rb_read) before its
; spans. A plane handle is its number, PL_OVERFLOW for a piece that found
; no visplane (the table is full, or the flat-shaded mode, which has no
; visplanes: such pieces are drawn at once by the seg loop), NONE for no
; plane.
;
; Spans (map_plane): the distance and the steps of a row are cached per
; row and plane height for the frame (the reference's R_MapPlane cache);
; the span itself is span_draw (rlc.s) with the flat's bank selected.
;
; Animation: a texture or flat inside an ANIMS sequence shows frame
; first + ((tic >> 3) + i - first) mod count; an_ofs holds (tic >> 3) mod
; count per sequence (rmain.s frame_setup).

.include "kernel.inc"
.include "rdefs.inc"
.macpack longbranch

.import r_extralight, r_fixedcm, basexscale, baseyscale, map_sky, shl4
.import fs_light, an_kind, an_count, an_first_lo, an_first_hi, an_ofs
.import an_bits, an_boff, bit8
.import span_setrow, span_setflat, span_draw, pl_used
.importzp sp_xf, sp_yf, sp_dp, sp_n
.import mulu_3_2_5, mulu_4_2_5, muls_4_2_4, muls_2_3_3
.import q_in_bank, q_in_dst, q_in_cnt, q_in_src, q_in_f, q_in_step, q_in_cm, q_in_hm

.export plane_frame, find_plane, check_plane, draw_planes, flat_trans, tex_trans
.export tex_fetch, texbuf, flat_fetch, flatbuf, sky_piece, render_shaded
.export pl_start, pl_stop, plane_fill, rc_xs0, rc_xs1, rc_ys0, rc_ys1
.export vp_n, ds_n, op_used
.export pt_top, spanstart, xc_ok, xc_shi, pl_hlo, pl_maxx, rc_ok, rc_ys1

; ---------------------------------------------------------------------------
; render_shaded: 0 textured floors and ceilings, else flat-shaded (a byte
; in the language card: the game may flip it at run time). The default is
; the build option RENDER_SHADED (ca65 -D RENDER_SHADED=1).
.ifndef RENDER_SHADED
RENDER_SHADED = 0
.endif
.segment "RLCHI"
render_shaded: .byte RENDER_SHADED
_render_shaded := render_shaded
.export _render_shaded

PL_BUCKETS  = 64                ; find_plane's hash
.segment "RBSS"
pl_head:    .res PL_BUCKETS     ; the first and last plane of each bucket
pl_tail:    .res PL_BUCKETS
pl_next:    .res MAXVISPLANES   ; the next plane of the same bucket
vp_n:       .res 1              ; visplanes in use
ds_n:       .res 1              ; drawsegs recorded
op_used:    .res 2              ; openings used (bytes)
.segment "RLCBSS"
pl_hlo:     .res MAXVISPLANES   ; height (map units)
pl_hhi:     .res MAXVISPLANES
pl_plo:     .res MAXVISPLANES   ; flat (translated)
pl_phi:     .res MAXVISPLANES
pl_light:   .res MAXVISPLANES
pl_minx:    .res MAXVISPLANES   ; columns + 1 (minx 161 / maxx 0: empty)
pl_maxx:    .res MAXVISPLANES
.segment "RBSS"
pf_n:       .res 1              ; pending plane fills (plane_fill)
pf_p:       .res 4
pf_a:       .res 4
pf_b:       .res 4
pl_start:   .res 1              ; check_plane's range (columns)
pl_stop:    .res 1
texbuf:     .res TEX_SIZE
flatbuf:    .res FLAT_SIZE
fp_h:       .res 2
fp_p:       .res 2
fp_l:       .res 1
cp_new:     .res 1
dp_pl:      .res 1              ; draw_planes: the plane
dp_x:       .res 1
dp_end:     .res 1
dp_t1:      .res 1
dp_b1:      .res 1
dp_t2:      .res 1
dp_b2:      .res 1
dp_hgt:     .res 3              ; |height - eye| (sub-units)
dp_bank:    .res 1              ; the flat
dp_addr:    .res 2
sky_bank:   .res 1              ; the sky texture of this frame
sky_addr:   .res 2
sky_wmask:  .res 1
sky_hmask:  .res 1
sky_log2h:  .res 1
sky_ok:     .res 1              ; the sky record is loaded
mp_y:       .res 1
mp_x1:      .res 1
mp_x2:      .res 1
mp_dist:    .res 4
mp_len:     .res 4
.export sky_ok

.segment "RLOBSS"
pt_top:     .res PL_COLS        ; a plane's columns, copied back
pt_bot:     .res PL_COLS
spanstart:  .res VIEW_H

.segment "RLOBSS"
xc_ok:      .res VIEW_W         ; the column cache: sin/cos of va + xtoviewangle[x]
xc_clo:     .res VIEW_W
xc_chi:     .res VIEW_W
xc_slo:     .res VIEW_W
xc_shi:     .res VIEW_W
vx6:        .res 2              ; (vx << 6) & $FFFF
nvy6:       .res 2              ; -(vy << 6) & $FFFF
tg_i:       .res 2
tc_tlo:     .res TC_SLOTS       ; the texture cache
tc_thi:     .res TC_SLOTS
tc_bank:    .res TC_SLOTS
tc_alo:     .res TC_SLOTS
tc_ahi:     .res TC_SLOTS
tc_wmask:   .res TC_SLOTS
tc_hmask:   .res TC_SLOTS
tc_log2h:   .res TC_SLOTS
tc_hlo:     .res TC_SLOTS
tc_hhi:     .res TC_SLOTS
.export tex_get, tex_cache_reset, tc_bank, tc_alo, tc_ahi, tc_wmask, tc_hmask, tc_log2h
.export tc_hlo, tc_hhi

.segment "RLCBSS"
rc_ok:      .res VIEW_H         ; the row cache: valid this frame
rc_h0:      .res VIEW_H         ; plane height of the entry
rc_h1:      .res VIEW_H
rc_h2:      .res VIEW_H
rc_d0:      .res VIEW_H         ; distance
rc_d1:      .res VIEW_H
rc_d2:      .res VIEW_H
rc_d3:      .res VIEW_H
rc_xs0:     .res VIEW_H         ; xstep, ystep
rc_xs1:     .res VIEW_H
rc_ys0:     .res VIEW_H
rc_ys1:     .res VIEW_H

.segment "RCODE"

; the RENDER_BANK address of each plane's top array
pl_alo:
        .repeat MAXVISPLANES, i
        .byte   <(PL_TOP + i * PL_SIZE)
        .endrepeat
pl_ahi:
        .repeat MAXVISPLANES, i
        .byte   >(PL_TOP + i * PL_SIZE)
        .endrepeat
.export pl_alo, pl_ahi

; plane_frame: no visplanes, drawsegs, openings; the row cache empty
plane_frame:
        stz     vp_n
        stz     ds_n
        stz     op_used
        stz     op_used+1
        stz     sky_ok
        ldx     #VIEW_H-1
:       stz     rc_ok,x
        dex
        bpl     :-
        lda     #NONE
        ldx     #PL_BUCKETS-1
:       sta     pl_head,x
        dex
        bpl     :-
        ldx     #VIEW_W
:       stz     xc_ok-1,x
        dex
        bne     :-
        ; vx6 = (vx << 6) & $FFFF, nvy6 = -(vy << 6) & $FFFF
        lda     vx+1
        sta     t1
        lda     vx
        lsr     t1
        ror     a
        lsr     t1
        ror     a
        sta     vx6+1
        lda     vx
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a
        sta     vx6
        lda     vy+1
        sta     t1
        lda     vy
        lsr     t1
        ror     a
        lsr     t1
        ror     a
        sta     t1
        lda     vy
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a
        asl     a
        sec
        eor     #$FF
        adc     #0
        sta     nvy6
        lda     t1
        eor     #$FF
        adc     #0
        sta     nvy6+1
        rts

; ---------------------------------------------------------------------------
; flat_trans / tex_trans: A/X = flat / texture -> A/X = the frame shown
flat_trans:
        ldy     #0
        bra     anim_trans
tex_trans:
        ldy     #1
anim_trans:
        sta     t4
        stx     t5
        sty     t6
        ; not in any sequence (an_bits, a bit per index): itself (the common case)
        lda     t5
        lsr     a
        lda     t4
        ror     a
        lsr     a
        lsr     a                       ; index >> 3 (< 256 for these counts)
        clc
        adc     an_boff,y
        tay
        lda     t4
        and     #7
        tax
        lda     an_bits,y
        and     bit8,x
        beq     @none
        ldy     #0
@a:     lda     an_kind,y
        cmp     t6
        bne     @next
        ; first <= i < first + count ?
        lda     t4
        sec
        sbc     an_first_lo,y
        sta     t7
        lda     t5
        sbc     an_first_hi,y
        bne     @next                   ; below first (borrow) or far above
        lda     t7
        cmp     an_count,y
        bcs     @next
        ; first + (i - first + ofs) mod count
        clc
        adc     an_ofs,y
        bcs     @wrap                   ; (count < 128 in practice; kept exact)
        cmp     an_count,y
        bcc     @in
@wrap:  sec
        sbc     an_count,y
@in:    clc
        adc     an_first_lo,y
        pha
        lda     an_first_hi,y
        adc     #0
        tax
        pla
        rts
@next:  iny
        cpy     #DD_NUM_ANIMS
        bne     @a
@none:  lda     t4
        ldx     t5
        rts

; tex_fetch: A/X = texture -> texbuf (its TEX record)
tex_fetch:
        sta     t4
        stx     t5
        ; DD_TEXDIR + 16 * i
        asl     t4
        rol     t5
        asl     t4
        rol     t5
        asl     t4
        rol     t5
        asl     t4
        rol     t5
        clc
        lda     t4
        adc     #<DD_TEXDIR
        sta     rb_src
        lda     t5
        adc     #>DD_TEXDIR
        sta     rb_src+1
        lda     #<texbuf
        sta     rb_dst
        lda     #>texbuf
        sta     rb_dst+1
        lda     #DD_DIR_BANK
        sta     rb_bank
        ldx     #TEX_SIZE
        jmp     rb_read

; tex_get: A/X = texture -> Y = its slot in the texture cache (tc_*: bank,
; address, wmask, hmask, log2h, height): TEXDIR never changes, so the cache
; lives until the next map load (tex_cache_reset)

tex_get:
        sta     tg_i
        stx     tg_i+1
        and     #TC_SLOTS-1
        tay
        lda     tg_i
        cmp     tc_tlo,y
        bne     @miss
        lda     tg_i+1
        cmp     tc_thi,y
        bne     @miss
        rts
@miss:  phy
        lda     tg_i
        ldx     tg_i+1
        jsr     tex_fetch
        ply
        lda     tg_i
        sta     tc_tlo,y
        lda     tg_i+1
        sta     tc_thi,y
        lda     texbuf+TEX_BANK
        sta     tc_bank,y
        lda     texbuf+TEX_ADDR
        sta     tc_alo,y
        lda     texbuf+TEX_ADDR+1
        sta     tc_ahi,y
        lda     texbuf+TEX_WMASK
        sta     tc_wmask,y
        lda     texbuf+TEX_HMASK
        sta     tc_hmask,y
        lda     texbuf+TEX_LOG2H
        sta     tc_log2h,y
        lda     texbuf+TEX_HEIGHT
        sta     tc_hlo,y
        lda     texbuf+TEX_HEIGHT+1
        sta     tc_hhi,y
        rts

; tex_cache_reset: every slot empty
tex_cache_reset:
        ldx     #TC_SLOTS-1
        lda     #$FF
:       sta     tc_thi,x
        dex
        bpl     :-
        rts

; flat_fetch: A/X = flat -> flatbuf (its FLAT record)
flat_fetch:
        sta     t4
        stx     t5
        asl     t4
        rol     t5
        asl     t4
        rol     t5
        asl     t4
        rol     t5
        clc
        lda     t4
        adc     #<DD_FLATDIR
        sta     rb_src
        lda     t5
        adc     #>DD_FLATDIR
        sta     rb_src+1
        lda     #<flatbuf
        sta     rb_dst
        lda     #>flatbuf
        sta     rb_dst+1
        lda     #DD_DIR_BANK
        sta     rb_bank
        ldx     #FLAT_SIZE
        jmp     rb_read

; ---------------------------------------------------------------------------
; find_plane: A/X = flat (translated), t0/t1 = height (map units), light
; fs_light -> A = the plane handle (R_FindPlane)
find_plane:
        sta     fp_p
        stx     fp_p+1
        lda     t0
        sta     fp_h
        lda     t1
        sta     fp_h+1
        lda     fs_light
        sta     fp_l
        lda     fp_p
        cmp     #<DD_SKYFLAT
        bne     :+
        lda     fp_p+1
        cmp     #>DD_SKYFLAT
        bne     :+
        stz     fp_h                    ; the sky: height 0, light 0
        stz     fp_h+1
        stz     fp_l
:       ; the planes with this key's hash, in the order they were made (the
        ; reference returns the first match)
        jsr     plane_hash
        ldx     pl_head,y
@s:     cpx     #NONE
        beq     new_plane
        lda     pl_hlo,x
        cmp     fp_h
        bne     @n
        lda     pl_hhi,x
        cmp     fp_h+1
        bne     @n
        lda     pl_plo,x
        cmp     fp_p
        bne     @n
        lda     pl_phi,x
        cmp     fp_p+1
        bne     @n
        lda     pl_light,x
        cmp     fp_l
        bne     @n
        txa
        rts
@n:     lda     pl_next,x
        tax
        bra     @s

; plane_hash: Y = the hash bucket of fp_h, fp_p, fp_l
plane_hash:
        lda     fp_h
        eor     fp_p
        eor     fp_l
        eor     fp_h+1
        and     #PL_BUCKETS-1
        tay
        rts
; new_plane: a visplane with fp_h, fp_p, fp_l and no columns -> A
new_plane:
        lda     render_shaded
        bne     @ovf
        ldx     vp_n
        cpx     #MAXVISPLANES
        bcs     @ovf
        inc     vp_n
        lda     fp_h
        sta     pl_hlo,x
        lda     fp_h+1
        sta     pl_hhi,x
        lda     fp_p
        sta     pl_plo,x
        lda     fp_p+1
        sta     pl_phi,x
        lda     fp_l
        sta     pl_light,x
        lda     #VIEW_W + 1
        sta     pl_minx,x
        stz     pl_maxx,x
        ; appended to its bucket's list
        lda     #NONE
        sta     pl_next,x
        jsr     plane_hash
        lda     pl_head,y
        cmp     #NONE
        bne     :+
        txa
        sta     pl_head,y
        bra     :++
:       phx
        lda     pl_tail,y
        tax
        pla
        sta     pl_next,x
        tax
:       txa
        sta     pl_tail,y
        rts
@ovf:   lda     #PL_OVERFLOW
        rts

; ---------------------------------------------------------------------------
; check_plane: A = handle, pl_start..pl_stop (columns) -> A = the handle to
; mark them in (R_CheckPlane). Columns the plane gains are set unused in
; RENDER_BANK at once.
check_plane:
        cmp     #PL_OVERFLOW
        bcc     :+
        rts
:       tax
        stx     cp_new
        ; intersection intrl..intrh (columns + 1) of [minx, maxx] and [start, stop]
        lda     pl_start
        inc     a
        sta     t0                      ; start + 1
        lda     pl_stop
        inc     a
        sta     t1                      ; stop + 1
        lda     pl_minx,x
        cmp     t0
        bcs     :+
        lda     t0                      ; intrl = max(minx, start)
:       sta     t2
        lda     pl_maxx,x
        cmp     t1
        bcc     :+
        lda     t1                      ; intrh = min(maxx, stop)
:       sta     t3
        ; any column intrl..intrh in use?
        lda     t3
        cmp     t2
        bcc     @free                   ; empty intersection
        sec
        sbc     t2
        inc     a
        tay                             ; count
        ; p0 = top array + index x + 1 = base + intrl (biased already)
        clc
        lda     pl_alo,x
        adc     t2
        sta     p0
        lda     pl_ahi,x
        adc     #0
        sta     p0+1
        tya
        tax
        jsr     pl_used
        bcs     @new
@free:  ; the plane grows to the union; its new columns are unused
        ldx     cp_new
        lda     pl_minx,x
        sta     t2                      ; old minx
        lda     pl_maxx,x
        sta     t3                      ; old maxx
        lda     t0
        cmp     t2
        bcs     :+
        sta     pl_minx,x
:       lda     t1
        cmp     t3
        bcc     :+
        sta     pl_maxx,x
:       ; fill [newmin, newmax] minus [oldmin, oldmax]
        lda     t3
        cmp     t2
        bcs     @grow
        ; the plane was empty: all of it
        lda     pl_minx,x
        ldy     pl_maxx,x
        jsr     plane_fill
        bra     @done
@grow:  lda     pl_minx,x
        cmp     t2
        bcs     :+
        ; left part: newmin .. oldmin - 1
        ldy     t2
        dey
        jsr     plane_fill
        ldx     cp_new
:       lda     t3
        cmp     pl_maxx,x
        bcs     @done
        ; right part: oldmax + 1 .. newmax
        inc     a
        ldy     pl_maxx,x
        jsr     plane_fill
@done:  lda     cp_new
        rts
@new:   ; a new plane with the same height, flat and light, just start..stop
        ldx     cp_new
        lda     pl_hlo,x
        sta     fp_h
        lda     pl_hhi,x
        sta     fp_h+1
        lda     pl_plo,x
        sta     fp_p
        lda     pl_phi,x
        sta     fp_p+1
        lda     pl_light,x
        sta     fp_l
        jsr     new_plane
        cmp     #PL_OVERFLOW
        bcs     :+
        tax
        stx     cp_new
        lda     t0
        sta     pl_minx,x
        lda     t1
        sta     pl_maxx,x
        lda     t0
        ldy     t1
        jsr     plane_fill
        lda     cp_new
:       rts

; plane_fill: plane cp_new, columns + 1 from A to Y (A <= Y) are to be set
; unused (tops $FF, bottoms 0): recorded, written by pf_write in the wall
; range's one RENDER_BANK session (at most two per check_plane, two
; check_planes per range)
plane_fill:
        ldx     pf_n
        sta     pf_a,x
        tya
        sta     pf_b,x
        lda     cp_new
        sta     pf_p,x
        inc     pf_n
        rts

; pf_write: the recorded fills (RAMWRT on: writes only RENDER_BANK and the
; zero page)
pf_write:
        ldx     #0
@f:     cpx     pf_n
        beq     @done
        ldy     pf_p,x
        clc
        lda     pl_alo,y
        adc     pf_a,x
        sta     p0
        lda     pl_ahi,y
        adc     #0
        sta     p0+1
        clc
        lda     p0
        adc     #<PL_COLS
        sta     p1
        lda     p0+1
        adc     #>PL_COLS
        sta     p1+1
        lda     pf_b,x
        sec
        sbc     pf_a,x
        tay                             ; count - 1
:       lda     #$FF
        sta     (p0),y
        lda     #0
        sta     (p1),y
        dey
        cpy     #$FF
        bne     :-
        inx
        bra     @f
@done:  rts
.export pf_write, pf_n

; ---------------------------------------------------------------------------
; sky_piece: column X, rows A..Y (real rows, A <= Y): queue the sky column
; (texture column (angle >> 7), row y + 8, colormap 0 or the fixed one)
sky_piece:
        sta     t0                      ; yl
        sty     t1                      ; yh
        stx     t2                      ; x
        lda     sky_ok
        bne     @have
        lda     map_sky
        ldx     map_sky+1
        jsr     tex_trans
        jsr     tex_fetch
        lda     texbuf+TEX_BANK
        sta     sky_bank
        lda     texbuf+TEX_ADDR
        sta     sky_addr
        lda     texbuf+TEX_ADDR+1
        sta     sky_addr+1
        lda     texbuf+TEX_WMASK
        sta     sky_wmask
        lda     texbuf+TEX_HMASK
        sta     sky_hmask
        lda     texbuf+TEX_LOG2H
        sta     sky_log2h
        lda     #1
        sta     sky_ok
@have:  ; column = ((va + xtoviewangle[x]) >> 7) & wmask
        ldx     t2
        clc
        lda     va
        adc     xtoviewangle_lo,x
        lda     va+1
        adc     xtoviewangle_hi,x
        sta     t4
        ; (angle >> 7) = angle_hi * 2 + (angle_lo >> 7): recompute with the low byte
        clc
        lda     va
        adc     xtoviewangle_lo,x
        asl     a                       ; bit 7 into C
        lda     t4
        rol     a                       ; (angle >> 7) & $FF
        and     sky_wmask
        ; << log2h: (c << 8) >> (8 - log2h)
        sta     t5
        stz     t4
        lda     #8
        sec
        sbc     sky_log2h
        tay
        beq     :+
@sh:    lsr     t5
        ror     t4
        dey
        bne     @sh
:       clc
        lda     t4
        adc     sky_addr
        sta     q_in_src
        lda     t5
        adc     sky_addr+1
        sta     q_in_src+1
        lda     sky_bank
        sta     q_in_bank
        ldx     t2
        clc
        lda     coladdr_lo,x
        adc     t0
        sta     q_in_dst
        lda     coladdr_hi,x
        adc     #0
        sta     q_in_dst+1
        lda     t1
        sec
        sbc     t0
        inc     a
        sta     q_in_cnt
        stz     q_in_f                  ; f = (50 + yl - 42) << 8
        lda     t0
        clc
        adc     #50 - CENTERY
        sta     q_in_f+1
        stz     q_in_step
        lda     #1
        sta     q_in_step+1
        lda     r_fixedcm
        cmp     #$FF
        bne     :+
        lda     #0
:       clc
        adc     #>DD_COLORMAPS
        sta     q_in_cm
        lda     sky_hmask
        sta     q_in_hm
        jmp     q_wall

; ---------------------------------------------------------------------------
; draw_planes: R_DrawPlanes
draw_planes:
        stz     dp_pl
@plane: lda     dp_pl
        cmp     vp_n
        bne     :+
        rts
:       tax
        lda     pl_maxx,x
        cmp     pl_minx,x
        bcs     :+
        jmp     @next                   ; no columns
:       ; its columns back from RENDER_BANK: indices minx - 1 + 1 .. maxx + 1 + 1
        ; (columns + 1 is the index; pl_minx is minx + 1)
        lda     #RENDER_BANK
        sta     rb_bank
        lda     pl_minx,x
        dec     a                       ; index of column minx - 1
        sta     t0
        clc
        adc     pl_alo,x
        sta     rb_src
        lda     pl_ahi,x
        adc     #0
        sta     rb_src+1
        clc
        lda     #<pt_top
        adc     t0
        sta     rb_dst
        lda     #>pt_top
        adc     #0
        sta     rb_dst+1
        lda     pl_maxx,x
        sec
        sbc     t0
        clc
        adc     #2                      ; maxx + 1 .. : count = maxx + 2 - (minx - 1) + 1
        sta     t1
        tax
        jsr     rb_read
        clc
        lda     rb_src
        adc     #<PL_COLS
        sta     rb_src
        lda     rb_src+1
        adc     #>PL_COLS
        sta     rb_src+1
        clc
        lda     #<pt_bot
        adc     t0
        sta     rb_dst
        lda     #>pt_bot
        adc     #0
        sta     rb_dst+1
        ldx     t1
        jsr     rb_read
        ; the sentinels: top[maxx + 2] = top[minx] = $FF (bottoms 0)
        ldx     dp_pl
        ldy     pl_maxx,x
        iny
        lda     #$FF
        sta     pt_top,y
        lda     #0
        sta     pt_bot,y
        ldy     pl_minx,x
        dey
        lda     #$FF
        sta     pt_top,y
        lda     #0
        sta     pt_bot,y
        ; the sky: columns
        lda     pl_plo,x
        cmp     #<DD_SKYFLAT
        bne     @flat
        lda     pl_phi,x
        cmp     #>DD_SKYFLAT
        bne     @flat
        lda     pl_minx,x
        sta     dp_x                    ; index = column + 1
@sky:   ldy     dp_x                    ; index: column + 1
        lda     pt_top,y
        cmp     pt_bot,y
        beq     @skyc
        bcs     @skyn                   ; top > bottom (or $FF): nothing
@skyc:  lda     pt_bot,y
        pha
        lda     pt_top,y
        ldx     dp_x
        dex                             ; the column
        ply
        jsr     sky_piece
@skyn:  ldx     dp_pl
        lda     dp_x
        inc     dp_x
        cmp     pl_maxx,x
        bne     @sky
        jmp     @next
@flat:  ; planeheight = |(height << 4) - vz|
        lda     pl_hlo,x
        pha
        lda     pl_hhi,x
        tax
        pla
        jsr     shl4
        sec
        lda     t4
        sbc     vz
        sta     dp_hgt
        lda     t5
        sbc     vz+1
        sta     dp_hgt+1
        lda     t6
        sbc     vz+2
        sta     dp_hgt+2
        bpl     :+
        sec
        lda     #0
        sbc     dp_hgt
        sta     dp_hgt
        lda     #0
        sbc     dp_hgt+1
        sta     dp_hgt+1
        lda     #0
        sbc     dp_hgt+2
        sta     dp_hgt+2
:       ; zlight row: clamp((light >> 4) + extralight) * 128
        ldx     dp_pl
        lda     pl_light,x
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     r_extralight
        cmp     #LIGHTLEVELS
        bcc     :+
        lda     #LIGHTLEVELS-1
:       stz     t4
        lsr     a
        ror     t4                      ; * 128
        sta     t5
        clc
        lda     #<zlight
        adc     t4
        sta     mp_zl+1
        lda     #>zlight
        adc     t5
        sta     mp_zl+2
        ; the flat
        lda     pl_plo,x
        pha
        lda     pl_phi,x
        tax
        pla
        jsr     flat_fetch
        lda     flatbuf+FLAT_BANK
        sta     dp_bank
        lda     flatbuf+FLAT_ADDR
        sta     dp_addr
        lda     flatbuf+FLAT_ADDR+1
        sta     dp_addr+1
        lda     dp_addr
        ldx     dp_addr+1
        jsr     span_setflat
        ; R_MakeSpans for x = minx .. maxx + 1 (index x + 1 has column x)
        ; (a column with the same top and bottom as the previous one starts
        ; and ends no span: make_spans would do nothing)
        ldx     dp_pl
        lda     pl_maxx,x
        sta     dp_end                  ; the last x is maxx + 1 = pl_maxx
        lda     pl_minx,x
        dec     a
        sta     dp_x                    ; x = minx (real)
        tay
@col:   lda     pt_top,y                ; index x: column x - 1
        cmp     pt_top+1,y
        bne     @ms
        lda     pt_bot,y
        cmp     pt_bot+1,y
        beq     @same
@ms:    lda     pt_top,y
        sta     dp_t1
        lda     pt_bot,y
        sta     dp_b1
        lda     pt_top+1,y
        sta     dp_t2
        lda     pt_bot+1,y
        sta     dp_b2
        jsr     make_spans
        ldy     dp_x
@same:  cpy     dp_end
        beq     @next
        iny
        sty     dp_x
        bra     @col
@next:  inc     dp_pl
        jmp     @plane

; make_spans: dp_x, dp_t1/b1 (column x - 1), dp_t2/b2 (column x)
make_spans:
@a:     lda     dp_t1                   ; while t1 < t2 and t1 <= b1
        cmp     dp_t2
        bcs     @b
        lda     dp_b1
        cmp     dp_t1
        bcc     @b
        ldy     dp_t1
        jsr     map_row
        inc     dp_t1
        bra     @a
@b:     lda     dp_b2                   ; while b1 > b2 and b1 >= t1
        cmp     dp_b1
        bcs     @c
        lda     dp_b1
        cmp     dp_t1
        bcc     @c
        ldy     dp_b1
        jsr     map_row
        dec     dp_b1
        bra     @b
@c:     lda     dp_t2                   ; while t2 < t1 and t2 <= b2
        cmp     dp_t1
        bcs     @d
        lda     dp_b2
        cmp     dp_t2
        bcc     @d
        ldy     dp_t2
        lda     dp_x
        sta     spanstart,y
        inc     dp_t2
        bra     @c
@d:     lda     dp_b1                   ; while b2 > b1 and b2 >= t2
        cmp     dp_b2
        bcs     @e
        lda     dp_b2
        cmp     dp_t2
        bcc     @e
        ldy     dp_b2
        lda     dp_x
        sta     spanstart,y
        dec     dp_b2
        bra     @d
@e:     rts

; ---------------------------------------------------------------------------
; the spans: RHICODE (map_plane's colormap row is patched per plane)
.segment "RHICODE"

; map_row: Y = row -> map_plane(y, spanstart[y], x - 1)
map_row:
        sty     mp_y
        lda     spanstart,y
        sta     mp_x1
        lda     dp_x
        dec     a
        sta     mp_x2
        ; fall through

; map_plane: row mp_y, columns mp_x1..mp_x2 of the current plane
; (R_MapPlane + R_DrawSpan):
;   distance = planeheight * yslope[y] >> 8, xstep/ystep = distance *
;   basex/yscale >> 15 (per row and plane height: the row cache)
;   length = distance * distscale[x1] >> 14
;   xfrac = (vx << 6) + (cos(va + xtoviewangle[x1]) * length >> 8),
;   yfrac = -(vy << 6) - (sin(..) * length >> 8), 16 bits each (the
;   sines per column: the column cache, filled on first use each frame)
map_plane:
        ldy     mp_y
        lda     rc_ok,y
        beq     @calc
        lda     rc_h0,y
        cmp     dp_hgt
        bne     @calc
        lda     rc_h1,y
        cmp     dp_hgt+1
        bne     @calc
        lda     rc_h2,y
        cmp     dp_hgt+2
        beq     @cached
@calc:  jsr     row_calc
        ldy     mp_y
@cached:
        ; length = (distance * distscale[x1]) >> 14: bits 14..37 of the product
        lda     rc_d0,y
        sta     m_a
        lda     rc_d1,y
        sta     m_a+1
        lda     rc_d2,y
        sta     m_a+2
        lda     rc_d3,y
        sta     m_a+3
        ldx     mp_x1
        lda     distscale_lo,x
        sta     m_b
        lda     distscale_hi,x
        sta     m_b+1
        jsr     mulu_4_2_5
        lda     m_r+1
        asl     a
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        asl     a
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        lda     m_r+2
        sta     mp_len
        lda     m_r+3
        sta     mp_len+1
        lda     m_r+4
        sta     mp_len+2
        ; the column's cosine and sine
        ldx     mp_x1
        lda     xc_ok,x
        bne     :+
        jsr     col_trig
        ldx     mp_x1
:       ; xfrac = vx6 + (cos * length >> 8)
        lda     xc_clo,x
        sta     m_a
        lda     xc_chi,x
        sta     m_a+1
        jsr     trig_len
        clc
        lda     m_r+1
        adc     vx6
        sta     sp_xf
        lda     m_r+2
        adc     vx6+1
        sta     sp_xf+1
        ; yfrac = nvy6 - (sin * length >> 8)
        ldx     mp_x1
        lda     xc_slo,x
        sta     m_a
        lda     xc_shi,x
        sta     m_a+1
        jsr     trig_len
        sec
        lda     nvy6
        sbc     m_r+1
        sta     sp_yf
        lda     nvy6+1
        sbc     m_r+2
        sta     sp_yf+1
        ; the colormap: fixed, or zlight[light][min(distance >> 8, 127)]
        ldy     mp_y
        lda     r_fixedcm
        cmp     #$FF
        bne     mp_cm
        lda     rc_d2,y
        ora     rc_d3,y
        bne     mp_far
        lda     rc_d1,y
        bpl     :+
mp_far:   lda     #MAXLIGHTZ-1
:       tax
mp_zl:  lda     zlight,x                ; (the plane's zlight row: draw_planes)
mp_cm:    clc
        adc     #>DD_COLORMAPS
        jsr     span_setrow             ; A = colormap page, Y = the row
        ; the view buffer address of (x1, y), the length
        ldx     mp_x1
        clc
        lda     coladdr_lo,x
        adc     mp_y
        sta     sp_dp
        lda     coladdr_hi,x
        adc     #0
        sta     sp_dp+1
        lda     mp_x2
        sec
        sbc     mp_x1
        inc     a
        sta     sp_n
        lda     dp_bank
        jmp     span_draw

; trig_len: m_r (bytes 1, 2) = (m_a (s16) * mp_len (low 24 bits)) >> 8,
; the product modulo 2^24
trig_len:
        lda     mp_len
        sta     m_b
        lda     mp_len+1
        sta     m_b+1
        lda     mp_len+2
        sta     m_b+2
        jmp     muls_2_3_3

; row_calc: the row cache entry of row mp_y for the plane height dp_hgt
row_calc:
        ; distance = (planeheight * yslope[y]) >> 8
        lda     dp_hgt
        sta     m_a
        lda     dp_hgt+1
        sta     m_a+1
        lda     dp_hgt+2
        sta     m_a+2
        ldy     mp_y
        lda     yslope_lo,y
        sta     m_b
        lda     yslope_hi,y
        sta     m_b+1
        jsr     mulu_3_2_5
        ldy     mp_y
        lda     m_r+1
        sta     rc_d0,y
        lda     m_r+2
        sta     rc_d1,y
        lda     m_r+3
        sta     rc_d2,y
        lda     m_r+4
        sta     rc_d3,y
        ; xstep = (distance * basexscale) >> 15, ystep likewise (16 bits kept)
        lda     basexscale
        ldx     basexscale+1
        jsr     @step
        ldy     mp_y
        sta     rc_xs0,y
        txa
        sta     rc_xs1,y
        lda     baseyscale
        ldx     baseyscale+1
        jsr     @step
        ldy     mp_y
        sta     rc_ys0,y
        txa
        sta     rc_ys1,y
        lda     dp_hgt
        sta     rc_h0,y
        lda     dp_hgt+1
        sta     rc_h1,y
        lda     dp_hgt+2
        sta     rc_h2,y
        lda     #1
        sta     rc_ok,y
        rts
; @step: A/X = base (signed 16) -> A/X = ((distance * base) >> 15) & $FFFF
@step:  sta     m_b
        stx     m_b+1
        ldy     mp_y
        lda     rc_d0,y
        sta     m_a
        lda     rc_d1,y
        sta     m_a+1
        lda     rc_d2,y
        sta     m_a+2
        lda     rc_d3,y
        sta     m_a+3
        jsr     muls_4_2_4
        ; bits 15..30
        lda     m_r+1
        asl     a
        lda     m_r+2
        rol     a
        pha
        lda     m_r+3
        rol     a
        tax
        pla
        rts

; col_trig: X = column -> xc_* = cos_bam and sin_bam of va + xtoviewangle[x]
col_trig:
        clc
        lda     va
        adc     xtoviewangle_lo,x
        sta     s_ang
        lda     va+1
        adc     xtoviewangle_hi,x
        sta     s_ang+1
        pha
        jsr     sin_bam
        ldx     mp_x1
        lda     s_val
        sta     xc_slo,x
        lda     s_val+1
        sta     xc_shi,x
        pla
        sta     s_ang+1                 ; (sin_bam keeps s_ang's low byte)
        jsr     cos_bam
        ldx     mp_x1
        lda     s_val
        sta     xc_clo,x
        lda     s_val+1
        sta     xc_chi,x
        lda     #1
        sta     xc_ok,x
        rts
