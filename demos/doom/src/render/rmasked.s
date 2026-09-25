; Doom for the Appletini -- the masked phase: sprites, two-sided middle
; textures and the weapon (docs/DESIGN.md 7.2; tools/refrender.py
; draw_masked, draw_sprite, draw_vissprite, draw_post,
; render_masked_seg_range, draw_psprite).
;
; r_masked runs last in render_frame, with LC bank 2 in (the bank the
; kernel's blit wants anyway): this phase's code that runs with RAMRD on
; sits in LC bank 2 beside the blit (bank 1 is full), the rest in main
; memory. Nothing here may call the LC bank 1 routines (rb_read, q_flush,
; ...): bank reads go through rb2_read, the same loop in bank 2.
;
;   1. The vissprites (rthings.s made them) are sorted by scale, ties in
;      the order they were made (insertion sort: the reference's key).
;   2. Each sprite, far to near (R_DrawSprite): its clip rows start at -2
;      (biased 62) in every column; a RAMRD session over the drawsegs,
;      last first, lists those overlapping it with a silhouette or a masked
;      middle; for each, from its record: a wall behind the sprite (its
;      larger scale below the sprite's, or its smaller one below and the
;      sprite on its front by R_PointOnSegSide, exact) only has its masked
;      middle drawn over the overlap, now; a wall in front clips: its
;      silhouette, less the parts the thing's z is clear of, fills the clip
;      rows still at -2 from the drawseg's openings (a RAMRD session on
;      RENDER_BANK). The rows left at -2 become 84 and -1.
;   3. The sprite (draw_vis, R_DrawVisSprite): the rows of the post
;      offsets 0..height come from a table built per sprite by additions
;      (rowt[k] = ceil(sprtopscreen + k * spryscale), biased, saturated to
;      1..255), the 8.8 fraction of every screen row it can cover from
;      another (yf[y] = texturemid + (y - 42) * iscale), so the column loop
;      has no product: it runs in one RAMRD session on the sprite's bank
;      (the patch's posts, its texels and the colormap are all there: every
;      graphics bank has the colormaps), with the clip rows and tables in
;      the language card. A post is Doom's R_DrawMaskedColumn: rows
;      max(rowt[top], cliptop + 1) .. min(rowt[top + length], clipbot) - 1,
;      the index not masked, 8.8 stepping. A shadow (the spectre) lists
;      its posts' rows instead (in main memory: RAMRD does not move
;      writes), drawn after the session with RAMRD off, since Doom's fuzz
;      reads the view buffer: colormap 3 of the pixel one row above or
;      below, rows 1..82, fuzzpos from 0 each frame.
;   4. The two-sided middles (R_RenderMaskedSegRange, msr): the wall phase
;      kept the texture, texturemid and light in the drawseg (rsegs.s);
;      per call a session on RENDER_BANK (RAMRD and RAMWRT on) reads the
;      columns' texture column, drawn mark and clip rows into the language
;      card and marks them drawn; then per column, RAMRD off, the rows of
;      sprtopscreen = 42 - texturemid * scale and bottomscreen = that +
;      scale * height (both exact in 48 bits, stepped by additions across
;      the range), iscale, colormap and fraction; then one session on the
;      texture's bank draws them, texel 247 a hole.
;   5. The weapon layers (R_DrawPSprite): one texel per pixel, the clip
;      rows -1 and 84, lit by the eye's sector at the brightest scale
;      (rthings.s ps_cm) unless full bright or the fixed colormap.
;
; Memory: rmask.inc (dead buffers of the walls and planes), the seg loop's
; zero page.

.include "kernel.inc"
.include "rdefs.inc"
.include "rpacket.inc"
.include "rmask.inc"
.include "rmul.inc"
.macpack longbranch

.import r_iscale, sprite_lump
.importzp is_s, is_r
.import rv_buf, r_fixedcm, ds_n, ds_addr, light_row
.import pos_px, pos_py, pos_lx, pos_ly, pos_ldx, pos_ldy, point_on_side
.import smul, mulu_3_2_5, shr4tab, shl4tab, sar4tab, _rview
.importzp ei, mul_na, mul_nb
.import vc_y_hi, spanstart, xc_shi, pl_maxx, rc_ok, rc_ys1, mtcbuf, fclip

.export r_masked, rb2_read

; the regions of rmask.inc are contiguous where their owners define them
.assert vc_y_hi + 128 - bsp_stack = VS_REGION, lderror, "rmask.inc: node stack .. vertex cache"
.assert VS_END - bsp_stack <= VS_REGION, lderror, "rmask.inc: the vissprites"
.assert fclip = cclip + VIEW_W, lderror, "rmask.inc: cclip, fclip"
.assert mtcbuf + VIEW_W - ct = CT_REGION, lderror, "rmask.inc: ct .. mtcbuf"
.assert CT_END - ct <= CT_REGION, lderror, "rmask.inc: the ct region"
.assert spanstart + VIEW_H - pt_top >= 3 * FZ_N, lderror, "rmask.inc: the fuzz list"
.assert xc_shi + VIEW_W - xc_ok >= 2 * MAXDRAWSEGS + 256, lderror, "rmask.inc: the xc region"
.assert rc_ok = pl_maxx + MAXVISPLANES, lderror, "rmask.inc: visplane headers .. row cache"
.assert rc_ys1 + VIEW_H - pl_hlo = LC_REGION, lderror, "rmask.inc: the LC region"
.assert LC_END - pl_hlo <= LC_REGION, lderror, "rmask.inc: the LC region's use"
.assert yf_hi + VIEW_H <= LC_END, lderror, "rmask.inc: the sprite tables"

; ---------------------------------------------------------------------------
; zero page (the seg loop's, free in this phase)
dv_frac     = MZ                ; column fraction (32-bit signed, 16.16)
dv_xstep    = MZ+4              ; its step per column
dv_dst      = MZ+8              ; the column's view buffer address - ROWBIAS
dv_p        = MZ+10             ; the post
dv_q        = MZ+12             ; the column offset entry / msr's bottom clips
dv_x        = MZ+14             ; the column
dv_x2       = MZ+15             ; the last column
dv_w        = MZ+16             ; the patch's width
dv_len      = MZ+17             ; the post's length / ds_scan's count
dv_flo      = MZ+18             ; f, fraction byte
dv_ye       = MZ+19             ; the post's rows: yl .. ye - 1 (biased)
dv_yl       = MZ+20
dv_td       = MZ+21             ; the post's top offset / msr: f's high byte
fz_n        = MZ+22             ; fuzz list entries
dv_fz       = MZ+23             ; bit 7: a shadow / ds_scan's mode
dv_cb       = MZ+24             ; the patch's column offsets (addr + 6)
dv_addr     = MZ+26             ; the patch
sp_r1       = MZ+28             ; a drawseg's overlap with the sprite
sp_r2       = MZ+29
cf_p        = MZ+30             ; clip_fill's openings / msr's masked columns
ms_tp       = MZ+32             ; msr: the top clips
.assert is_s = MZ+34 && is_r = MZ+37, error, "rmasked.s: r_iscale's operands moved"

; ---------------------------------------------------------------------------
.segment "RLC2"

; r_masked: R_DrawMasked and the weapon (render_frame: LC bank 2 in)
r_masked:
        lda     #<rb2_read
        sta     rd_vec
        lda     #>rb2_read
        sta     rd_vec+1
        stz     fuzzpos
        stz     fz_ok
        lda     #$FF
        sta     ms_ds
        jsr     vis_sort
        stz     sp_i
:       ldx     sp_i
        cpx     vis_n
        beq     :+
        lda     ord,x
        jsr     draw_sprite
        inc     sp_i
        bra     :-
:       jsr     masked_rest
        jmp     draw_psprites

; rb2_read: X bytes (0 = 256) from rb_bank:(rb_src) to (rb_dst) (rlc.s
; rb_read, here for LC bank 2)
rb2_read:
        lda     rb_bank
        jsr     sel_bank
        sta     RAMRDON
        ldy     #0
@l:     lda     (rb_src),y
        sta     (rb_dst),y
        iny
        dex
        bne     @l
        sta     RAMRDOFF
        rts

; sel_render / sel_bank: $C073 = RENDER_BANK / A (written only on a change)
sel_render:
        lda     #RENDER_BANK
sel_bank:
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       rts

; ---------------------------------------------------------------------------
; ds_scan: A = 0: the drawsegs a sprite must consider: those overlapping its
; columns sp_r1..sp_r2 with a silhouette or a masked middle, except that one
; entirely behind it (both scales below the sprite's, dv_xstep) matters only
; for its masked middle and is flagged so (candf bit 7: no record needed);
; A = 1: the drawsegs with a masked middle. Last first, into cand / candf
; (dv_len of them); one RAMRD session on RENDER_BANK
ds_scan:
        stz     dv_len
        ldx     ds_n
        bne     :+
        rts
:       tay
        lda     #@spr - @l - 2
        cpy     #0
        beq     :+
        lda     #@mtc - @l - 2
:       sta     @l+1
        dex
        stx     dv_td                   ; the drawseg
        txa
        jsr     ds_addr
        sta     dv_p
        stx     dv_p+1
        jsr     sel_render
        sta     RAMRDON
@l:     bra     @spr                    ; (patched: the mode)
@spr:   ldy     #DS_X1
        lda     sp_r2
        cmp     (dv_p),y
        bcc     @n                      ; x1 > the sprite's x2
        ldy     #DS_X2
        lda     (dv_p),y
        cmp     sp_r1
        bcc     @n                      ; x2 < its x1
        ldy     #DS_SCALE1
        jsr     @below
        bcs     @full
        ldy     #DS_SCALE2
        jsr     @below
        bcs     @full
        lda     #$80                    ; behind: its masked middle only
        bra     @mtc2
@full:  ldy     #DS_SIL
        lda     (dv_p),y
        bne     @take                   ; (A = the silhouette: bit 7 clear)
@mtc:   lda     #0
@mtc2:  sta     dv_fz
        ldy     #DS_MTC
        lda     (dv_p),y
        iny
        ora     (dv_p),y
        beq     @n
        lda     dv_fz
@take:  ldx     dv_len
        sta     candf,x                 ; (writes: main memory)
        lda     dv_td
        sta     cand,x
        inc     dv_len
@n:     sec
        lda     dv_p
        sbc     #DS_SIZE
        sta     dv_p
        bcs     :+
        dec     dv_p+1
:       dec     dv_td
        lda     dv_td
        cmp     #$FF
        bne     @l
        sta     RAMRDOFF
        rts
; @below: Y = a scale's offset -> C clear if it is below the sprite's
@below: lda     (dv_p),y
        cmp     dv_xstep
        iny
        lda     (dv_p),y
        sbc     dv_xstep+1
        iny
        lda     (dv_p),y
        sbc     dv_xstep+2
        rts

; clip_fill: A/X = mc_bot or mc_top, Y = DS_BOTCLIP or DS_TOPCLIP of dsrec:
; the rows sp_r1..sp_r2 still -2 get the drawseg's
clip_fill:
        sta     @a1+1
        sta     @a2+1
        stx     @a1+2
        stx     @a2+2
        lda     dsrec+1,y
        bne     @arr
        ; a constant: rows 84 or -1
        ldx     dsrec,y
        lda     #ROWBIAS + VIEW_H
        cpx     #DS_SCREENHEIGHT
        beq     :+
        lda     #ROWBIAS - 1
:       sta     @cv+1
        lda     #$A9                    ; lda #
        bra     @set
@arr:   ; the openings: column x at the pointer + x - ds.x1
        sec
        lda     dsrec,y
        sbc     dsrec+DS_X1
        sta     cf_p
        lda     dsrec+1,y
        sbc     #0
        sta     cf_p+1
        lda     #cf_p
        sta     @cv+1
        jsr     sel_render
        sta     RAMRDON
        lda     #$B1                    ; lda (cf_p),y
@set:   sta     @cv
        ldy     sp_r1
@l:
@a1:    lda     $FFFF,y
        cmp     #ROWBIAS - 2
        bne     :+
@cv:    lda     (cf_p),y
@a2:    sta     $FFFF,y
:       cpy     sp_r2
        iny
        bcc     @l
        sta     RAMRDOFF                ; (after a constant too: harmless)
        rts

; ---------------------------------------------------------------------------
; draw_vis: R_DrawVisSprite. dv_bank/dv_addr/dv_cb the patch, dv_x..dv_x2
; the columns, dv_skip the columns clipped off the left, dv_flip, dv_top
; sprtopscreen, dv_ys spryscale, dv_is iscale, dv_tm texturemid, dv_cm the
; colormap page (0: the fuzz); mc_top/mc_bot the clip rows
draw_vis:
        lda     dv_bank
        sta     rb_bank
        lda     dv_addr
        sta     rb_src
        lda     dv_addr+1
        sta     rb_src+1
        lda     #<dv_hdr
        sta     rb_dst
        lda     #>dv_hdr
        sta     rb_dst+1
        ldx     #2
        jsr     rb2_read
        lda     dv_hdr
        sta     dv_w
        jsr     build_rows
        jsr     build_yf
        bcs     @done                   ; no row of it can show
        jsr     dv_frac0
        ; the first column's view buffer address - ROWBIAS
        ldx     dv_x
        sec
        lda     coladdr_lo,x
        sbc     #ROWBIAS
        sta     dv_dst
        lda     coladdr_hi,x
        sbc     #0
        sta     dv_dst+1
        ; the step of f: (iscale + 128) >> 8, the colormap
        clc
        lda     dv_is
        adc     #$80
        lda     dv_is+1
        adc     #0
        sta     dvp_stl+1
        lda     dv_is+2
        adc     #0
        sta     dvp_sth+1
        stz     dv_fz
        stz     fz_n
        lda     dv_cm
        sta     dvp_cm+2
        bne     @sess
        dec     dv_fz                   ; a shadow
        jsr     fz_load
@sess:  jsr     dv_cols
        php
        bit     dv_fz
        bpl     :+
        jsr     fz_flush
:       plp
        bcs     @sess                   ; the fuzz list was full: go on
@done:  rts

; build_rows: rowt[k] = ceil((sprtopscreen + k * spryscale) / 65536) + 64,
; saturated to 1..255, k = 0..height
build_rows:
        clc
        lda     dv_top
        adc     #$FF
        sta     bs_s
        lda     dv_top+1
        adc     #$FF
        sta     bs_s+1
        ldx     #2
        ldy     #4
:       lda     dv_top,x
        adc     #0
        sta     bs_s,x
        inx
        dey
        bne     :-
        ldy     #0
        ; beyond the last row: all 255
        lda     bs_s+5
        bmi     @neg
        ora     bs_s+4
        ora     bs_s+3
        bne     @hi
        lda     bs_s+2
        cmp     #256 - ROWBIAS
        bcs     @hi
        bra     @k
@neg:   ; below -2^31: -2^31 (the rows saturate all the same)
        and     bs_s+4
        cmp     #$FF
        bne     @clamp
        lda     bs_s+3
        bmi     @k
@clamp: lda     #$80
        sta     bs_s+3
        stz     bs_s+2
@k:     lda     bs_s+3
        bmi     @lo
        bne     @hi
        lda     bs_s+2
        cmp     #256 - ROWBIAS
        bcs     @hi
        adc     #ROWBIAS
        bra     @put
@lo:    cmp     #$FF
        bne     @one
        lda     bs_s+2
        cmp     #<(1 - ROWBIAS)
        bcc     @one
        adc     #ROWBIAS - 1            ; (C set)
        bra     @put
@one:   lda     #1
@put:   sta     rowt,y
        clc
        lda     bs_s
        adc     dv_ys
        sta     bs_s
        lda     bs_s+1
        adc     dv_ys+1
        sta     bs_s+1
        lda     bs_s+2
        adc     dv_ys+2
        sta     bs_s+2
        bcc     :+
        inc     bs_s+3
:       cpy     dv_hdr+1
        iny
        bcc     @k
        rts
@hi:    lda     #255
:       sta     rowt,y
        cpy     dv_hdr+1
        iny
        bcc     :-
        rts

; build_yf: the rows a post can cover, ylo = max(rowt[0], 64) .. ye =
; min(rowt[height], 148) - 1: yf[y] = bytes 1, 2 of texturemid + (y - 42) *
; iscale. C set: none
build_yf:
        lda     rowt
        cmp     #ROWBIAS
        bcs     :+
        lda     #ROWBIAS
:       sta     dv_yl
        ldy     dv_hdr+1
        lda     rowt,y
        cmp     #ROWBIAS + VIEW_H
        bcc     :+
        lda     #ROWBIAS + VIEW_H
:       sta     dv_ye
        lda     dv_yl
        cmp     dv_ye
        bcc     :+
        rts                             ; (C set)
:       jsr     mul_row                 ; ms_v = (ylo - 42) * iscale
        clc
        ldx     #0
        ldy     #3
:       lda     ms_v,x
        adc     dv_tm,x
        sta     ms_v,x
        inx
        dey
        bne     :-
        ldy     dv_yl
@y:     lda     ms_v+1
        sta     yf_lo - ROWBIAS,y
        lda     ms_v+2
        sta     yf_hi - ROWBIAS,y
        clc
        lda     ms_v
        adc     dv_is
        sta     ms_v
        lda     ms_v+1
        adc     dv_is+1
        sta     ms_v+1
        lda     ms_v+2
        adc     dv_is+2
        sta     ms_v+2
        iny
        cpy     dv_ye
        bne     @y
        clc
        rts

; dv_cols: the columns dv_x .. dv_x2, in one RAMRD session on the patch's
; bank. C set on return: a shadow's list is full, call again after
; fz_flush (dv_x and the rest are where they stopped)
dv_cols:
        lda     dv_bank
        jsr     sel_bank
        sta     RAMRDON
dvc_col:
        lda     fz_n
        cmp     #FZ_N - 64
        bcc     :+
        sta     RAMRDOFF
        rts                             ; (C set)
:       lda     dv_dst
        sta     dvp_dst+1
        lda     dv_dst+1
        sta     dvp_dst+2
        ; the patch column: frac >> 16, 0 .. width - 1
        lda     dv_frac+3
        jne     dvc_skip
        lda     dv_frac+2
        cmp     dv_w
        jcs     dvc_skip
        asl     a                       ; its column offset: addr + 6 + 2 * col
        sta     dv_q
        lda     #0
        rol     a
        sta     dv_q+1
        clc
        lda     dv_q
        adc     dv_cb
        sta     dv_q
        lda     dv_q+1
        adc     dv_cb+1
        sta     dv_q+1
        ldy     #0
        clc
        lda     (dv_q),y
        adc     dv_addr
        sta     dv_p
        iny
        lda     (dv_q),y
        adc     dv_addr+1
        sta     dv_p+1
dvc_post:
        lda     (dv_p)
        cmp     #$FF
        jeq     dvc_skip
        sta     dv_td
        tax
        ldy     #1
        lda     (dv_p),y
        sta     dv_len
        ; ye = min(rowt[top + length], clipbot)
        clc
        adc     dv_td
        tay
        lda     rowt,y
        ldy     dv_x
        cmp     mc_bot,y
        bcc     :+
        lda     mc_bot,y
:       sta     dv_ye
        ; yl = max(rowt[top], cliptop + 1)
        lda     mc_top,y
        cmp     rowt,x
        bcs     :+                      ; rowt <= cliptop
        lda     rowt,x
        bra     :++
:       inc     a
:       cmp     dv_ye
        bcs     dvc_next
        bit     dv_fz
        bmi     dvc_fuzz
        tay
        lda     yf_lo - ROWBIAS,y
        sta     dv_flo
        lda     yf_hi - ROWBIAS,y
        sec
        sbc     dv_td
        tax
        clc
        lda     dv_p
        adc     #2
        sta     dvp_src+1
        lda     dv_p+1
        adc     #0
        sta     dvp_src+2
        cmp     #$BF                    ; the bank's last page: see dvc_bf
        beq     dvc_bf
dvc_go: lda     dv_ye
        sta     dvp_end+1
        clc
dvc_pix:
dvp_src: lda    $FFFF,x                 ; the texel (the post's, unmasked index)
        sta     dvp_cm+1
dvp_cm:  lda    $FF00                   ; through the colormap
dvp_dst: sta    $FFFF,y
        lda     dv_flo
dvp_stl: adc    #0
        sta     dv_flo
        txa
dvp_sth: adc    #0
        tax
        clc
        iny
dvp_end: cpy    #0
        bne     dvc_pix
dvc_next:
        lda     dv_len                  ; p += 2 + length
        sec
        adc     dv_p
        sta     dv_p
        bcc     :+
        inc     dv_p+1
:       inc     dv_p
        jne     dvc_post
        inc     dv_p+1
        jmp     dvc_post
dvc_fuzz:
        ldx     fz_n
        sta     fzl_yl,x
        lda     dv_ye
        sta     fzl_ye,x
        lda     dv_x
        sta     fzl_x,x
        inc     fz_n
        bra     dvc_next
; a post whose pixels start in page $BF: the unmasked index (Doom's
; rounding can make it up to 255) may reach past $BFFF, which the 6502
; would read from the I/O space; the bank there reads as 0 (the reference's
; bank image), so such a post is drawn by this slower loop
dvc_bf: lda     dvp_src+1
        beq     dvc_go                  ; $BF00 + 255: still in the bank
        sta     dvs_lo+1
        lda     dv_ye
        sta     dvs_end+1
        lda     dvp_cm+2
        sta     dvs_cm+2
        lda     dvp_dst+1
        sta     dvs_dst+1
        lda     dvp_dst+2
        sta     dvs_dst+2
dvs_pix: txa
        clc
dvs_lo: adc     #0
        bcs     :+
        phy
        tay
        lda     $BF00,y
        ply
        bra     :++
:       lda     #0
:       sta     dvs_cm+1
dvs_cm: lda     $FF00
dvs_dst: sta    $FFFF,y
        clc
        lda     dv_flo
        adc     dvp_stl+1
        sta     dv_flo
        txa
        adc     dvp_sth+1
        tax
        iny
dvs_end: cpy    #0
        bne     dvs_pix
        jmp     dvc_next
dvc_skip:
        clc
        lda     dv_frac
        adc     dv_xstep
        sta     dv_frac
        lda     dv_frac+1
        adc     dv_xstep+1
        sta     dv_frac+1
        lda     dv_frac+2
        adc     dv_xstep+2
        sta     dv_frac+2
        lda     dv_frac+3
        adc     dv_xstep+3
        sta     dv_frac+3
        clc
        lda     dv_dst
        adc     #VIEW_H
        sta     dv_dst
        bcc     :+
        inc     dv_dst+1
:       lda     dv_x
        cmp     dv_x2
        inc     dv_x
        jcc     dvc_col
        sta     RAMRDOFF
        clc
        rts

; ---------------------------------------------------------------------------
; ms_gather: for columns ms_r1..ms_r2 of the drawseg set up: m_slo = the
; texture column, m_yl = cliptop (0: drawn already), m_ye = clipbot; each
; column marked drawn. One session on RENDER_BANK with RAMRD and RAMWRT on:
; the other writes go to the language card and the zero page
ms_gather:
        ; the masked columns: 2 bytes per column from x1
        sec
        lda     ms_r1
        sbc     ms_x1
        asl     a
        sta     cf_p
        lda     #0
        rol     a
        sta     cf_p+1
        clc
        lda     cf_p
        adc     ms_mtc
        sta     cf_p
        lda     cf_p+1
        adc     ms_mtc+1
        sta     cf_p+1
        ; the clip rows: lda (pointer - x1),y, or lda #row
        ldx     #ms_tp
        lda     ms_tc
        ldy     ms_tc+1
        jsr     msg_clip
        stx     msg_t
        sta     msg_t+1
        ldx     #dv_q
        lda     ms_bc
        ldy     ms_bc+1
        jsr     msg_clip
        stx     msg_b
        sta     msg_b+1
        lda     ms_r2
        sta     sp_r2
        ldx     ms_r1
        jsr     sel_render
        sta     RAMRDON
        sta     RAMWRTON
msg_l:  ldy     #1
        lda     (cf_p),y
        bne     msg_drawn
        lda     #1
        sta     (cf_p),y                ; drawn (RAMWRT: into the bank)
        lda     (cf_p)
        sta     m_slo,x
        txa
        tay
msg_t:  lda     (ms_tp),y
        sta     m_yl,x
msg_b:  lda     (dv_q),y
        sta     m_ye,x
        bra     msg_n
msg_drawn:
        stz     m_yl,x
msg_n:  clc
        lda     cf_p
        adc     #2
        sta     cf_p
        bcc     :+
        inc     cf_p+1
:       cpx     sp_r2
        inx
        bcc     msg_l
        sta     RAMWRTOFF
        sta     RAMRDOFF
        rts
; msg_clip: A/Y = a clip pointer, X = the zero-page pointer to use -> X/A = the
; instruction reading it: lda (zp),y with zp = pointer - x1, or lda #row
msg_clip:
        cpy     #0
        bne     :+
        tax
        lda     #ROWBIAS + VIEW_H
        cpx     #DS_SCREENHEIGHT
        beq     @const
        lda     #ROWBIAS - 1
@const: ldx     #$A9                    ; lda #
        rts
:       sec
        sbc     ms_x1
        sta     0,x
        tya
        sbc     #0
        sta     1,x
        txa
        ldx     #$B1                    ; lda (zp),y
        rts

; ms_draw: the columns ms_r1..ms_r2 with m_yl != 0: one session on the
; texture's bank (texel 247 is a hole)
ms_draw:
        ldx     ms_r1
        sec
        lda     coladdr_lo,x
        sbc     #ROWBIAS
        sta     dv_dst
        lda     coladdr_hi,x
        sbc     #0
        sta     dv_dst+1
        lda     ms_tex+TEX_HMASK
        sta     msd_hm+1
        lda     ms_r2
        sta     sp_r2
        lda     ms_tex+TEX_BANK
        jsr     sel_bank
        sta     RAMRDON
msd_col:
        lda     m_yl,x
        beq     msd_next
        tay
        lda     dv_dst
        sta     msd_dst+1
        lda     dv_dst+1
        sta     msd_dst+2
        lda     m_slo,x
        sta     msd_src+1
        lda     m_shi,x
        sta     msd_src+2
        lda     m_cm,x
        sta     msd_cm+2
        lda     m_stl,x
        sta     msd_stl+1
        lda     m_sth,x
        sta     msd_sth+1
        lda     m_ye,x
        sta     msd_end+1
        lda     m_flo,x
        sta     dv_flo
        lda     m_fhi,x
        sta     dv_td
        stx     dv_x
msd_pix:
        lda     dv_td
msd_hm: and     #0
        tax
msd_src: lda    $FFFF,x
        cmp     #DD_TRANSPARENT
        beq     :+
        sta     msd_cm+1
msd_cm: lda     $FF00
msd_dst: sta    $FFFF,y
:       clc
        lda     dv_flo
msd_stl: adc    #0
        sta     dv_flo
        lda     dv_td
msd_sth: adc    #0
        sta     dv_td
        iny
msd_end: cpy    #0
        bne     msd_pix
        ldx     dv_x
msd_next:
        clc
        lda     dv_dst
        adc     #VIEW_H
        sta     dv_dst
        bcc     :+
        inc     dv_dst+1
:       cpx     sp_r2
        inx
        bcc     msd_col
        sta     RAMRDOFF
        rts

; ===========================================================================
; the rest: the language card where there was room, else main memory (all
; of it runs with RAMRD off)
.segment "RLC2"                ; (LC bank 2)

; ---------------------------------------------------------------------------
; draw_sprite: A = vissprite (R_DrawSprite)
draw_sprite:
        sta     sp_v
        tax
        lda     vis_x2,x
        sta     sp_x2
        lda     vis_x1,x
        sta     sp_x1
        cmp     sp_x2
        beq     :+
        bcc     :+
        rts                             ; no column (x2 < x1): nothing at all
:       lda     vis_sc0,x
        sta     sp_sc
        lda     vis_sc1,x
        sta     sp_sc+1
        lda     vis_sc2,x
        sta     sp_sc+2
        stz     sp_thok
        ; every clip row unset (-2)
        ldx     sp_x1
        lda     #ROWBIAS - 2
:       sta     mc_top,x
        sta     mc_bot,x
        cpx     sp_x2
        inx
        bcc     :-
        lda     sp_x1
        sta     sp_r1
        lda     sp_x2
        sta     sp_r2
        ldx     #2
:       lda     sp_sc,x
        sta     dv_xstep,x              ; (the scan compares with it)
        dex
        bpl     :-
        lda     #0
        jsr     ds_scan
        lda     dv_len
        sta     cand_n
        stz     sp_ci
@cand:  ldx     sp_ci
        cpx     cand_n
        jeq     @clipped
        inc     sp_ci
        lda     cand,x
        sta     ps_x1                   ; the drawseg
        ldy     candf,x
        bpl     @rec
        ; entirely behind: its masked middle over the overlap, now
        jsr     msr_setup
        lda     ms_x1
        cmp     sp_x1
        bcs     :+
        lda     sp_x1
:       sta     ms_r1
        lda     ms_x2
        cmp     sp_x2
        bcc     :+
        lda     sp_x2
:       sta     ms_r2
        jsr     msr_range
        jmp     @cand
@rec:   jsr     ds_read
        ; the overlap
        lda     dsrec+DS_X1
        cmp     sp_x1
        bcs     :+
        lda     sp_x1
:       sta     sp_r1
        lda     dsrec+DS_X2
        cmp     sp_x2
        bcc     :+
        lda     sp_x2
:       sta     sp_r2
        ; scale = max(scale1, scale2), lowscale = min: X / Y their offsets
        ldx     #DS_SCALE1
        ldy     #DS_SCALE2
        lda     dsrec+DS_SCALE2
        cmp     dsrec+DS_SCALE1
        lda     dsrec+DS_SCALE2+1
        sbc     dsrec+DS_SCALE1+1
        lda     dsrec+DS_SCALE2+2
        sbc     dsrec+DS_SCALE1+2
        bcc     :+                      ; scale2 < scale1
        ldx     #DS_SCALE2
        ldy     #DS_SCALE1
:       ; scale < the sprite's: behind
        lda     dsrec,x
        cmp     sp_sc
        lda     dsrec+1,x
        sbc     sp_sc+1
        lda     dsrec+2,x
        sbc     sp_sc+2
        bcc     @behind
        ; lowscale < the sprite's, and the sprite on the seg's front: behind
        lda     dsrec,y
        cmp     sp_sc
        lda     dsrec+1,y
        sbc     sp_sc+1
        lda     dsrec+2,y
        sbc     sp_sc+2
        bcs     @front
        jsr     sp_thing
        jsr     seg_side
        bne     @front
@behind:
        lda     dsrec+DS_MTC
        ora     dsrec+DS_MTC+1
        jeq     @cand
        lda     sp_r1
        sta     ms_r1
        lda     sp_r2
        sta     ms_r2
        lda     ps_x1
        jsr     msr_setup
        jsr     msr_range
        jmp     @cand
@front: ; the silhouette, less what the thing's z is clear of
        lda     dsrec+DS_SIL
        sta     sp_sil
        jeq     @cand
        jsr     sp_thing
        ; gz >= bsilheight <=> gz >> 4 >= bsil (map units): no bottom clip
        ldx     #DS_BSIL
        ldy     #0
        jsr     cmp_sil                 ; C set: gz4 >= bsil
        bcc     :+
        lda     sp_sil
        and     #<~SIL_BOTTOM
        sta     sp_sil
:       ; gzt <= tsilheight <=> (gzt + 15) >> 4 <= tsil: no top clip
        ldx     #DS_TSIL
        ldy     #3
        jsr     cmp_sil                 ; C clear: gzt4 < tsil
        bcc     @notop
        lda     ps_t+3                  ; equal: no top clip either
        bne     :+
@notop: lda     sp_sil
        and     #<~SIL_TOP
        sta     sp_sil
:       lda     sp_sil
        lsr     a                       ; SIL_BOTTOM
        bcc     :+
        lda     #<mc_bot
        ldx     #>mc_bot
        ldy     #DS_BOTCLIP
        jsr     clip_fill
:       lda     sp_sil
        and     #SIL_TOP
        jeq     @cand
        lda     #<mc_top
        ldx     #>mc_top
        ldy     #DS_TOPCLIP
        jsr     clip_fill
        jmp     @cand
@clipped:
        ; the rows still unset: the whole screen
        ldx     sp_x1
@f:     lda     mc_bot,x
        cmp     #ROWBIAS - 2
        bne     :+
        lda     #ROWBIAS + VIEW_H
        sta     mc_bot,x
:       lda     mc_top,x
        cmp     #ROWBIAS - 2
        bne     :+
        lda     #ROWBIAS - 1
        sta     mc_top,x
:       cpx     sp_x2
        inx
        bcc     @f
        ; draw it: the patch, columns, fractions, the screen rows
        ldx     sp_v
        lda     vis_llo,x
        sta     pj_lump
        lda     vis_lhi,x
        sta     dv_flip
        and     #$3F
        sta     pj_lump+1
        jsr     lump_rec
        ldx     sp_v
        lda     sp_x1
        sta     dv_x
        lda     sp_x2
        sta     dv_x2
        lda     vis_sk0,x
        sta     dv_skip
        lda     vis_sk1,x
        sta     dv_skip+1
        lda     vis_i0,x
        sta     dv_is
        lda     vis_i1,x
        sta     dv_is+1
        lda     vis_i2,x
        sta     dv_is+2
        ; spryscale = 2 * scale
        lda     sp_sc
        asl     a
        sta     dv_ys
        lda     sp_sc+1
        rol     a
        sta     dv_ys+1
        lda     sp_sc+2
        rol     a
        sta     dv_ys+2
        ; texturemid << 11 (mod 2^24)
        lda     vis_t0,x
        sta     ps_t
        lda     vis_t1,x
        sta     ps_t+1
        jsr     tm_shl11
        stx     dv_tm+1
        sta     dv_tm+2
        stz     dv_tm
        ; sprtopscreen = (42 << 16) - ((texturemid * scale) >> 4)
        ldx     sp_v
        lda     vis_t0,x
        sta     m_a
        lda     vis_t1,x
        sta     m_a+1
        lda     vis_t2,x
        sta     m_a+2
        ldx     #2
:       lda     sp_sc,x
        sta     m_b,x
        dex
        bpl     :-
        jsr     smul33
        jsr     mr_shr4
        jsr     top_sub
        ; the colormap page: 0 for a shadow
        ldx     sp_v
        lda     vis_cm,x
        cmp     #$FF
        beq     :+
        clc
        adc     #>DD_COLORMAPS
        bra     :++
:       lda     #0
:       sta     dv_cm
        jmp     draw_vis

; msr_range: R_RenderMaskedSegRange of the drawseg set up, columns
; ms_r1 .. ms_r2
msr_range:
        ; scale = scale1 + (r1 - x1) * scalestep
        sec
        lda     ms_r1
        sbc     ms_x1
        sta     m_a
        stz     m_a+1
        ldx     #2
:       lda     ms_st,x
        sta     m_b,x
        dex
        bpl     :-
        lda     #2
        sta     mul_na
        lda     #3
        sta     mul_nb
        jsr     smul
        clc
        ldx     #0
        ldy     #3
:       lda     m_r,x
        adc     ms_s1,x
        sta     ms_sc,x
        sta     m_b,x
        lda     ms_tmid,x
        sta     m_a,x
        inx
        dey
        bne     :-
        ; T = texturemid * scale, H = scale * height
        jsr     smul33
        ldx     #5
:       lda     m_r,x
        sta     ms_t,x
        dex
        bpl     :-
        ldx     #2
:       lda     ms_sc,x
        sta     m_a,x
        dex
        bpl     :-
        ldy     #ms_h - cclip
        jsr     mul_h
        jsr     ms_gather
        ; the columns
        lda     ms_r1
        sta     ms_x
@col:   ldx     ms_x
        lda     m_yl,x
        jeq     @step
        ; sprtopscreen = (42 << 16) - (T >> 4), bottomscreen = that + H
        ldx     #5
:       lda     ms_t,x
        sta     m_r,x
        dex
        bpl     :-
        jsr     mr_shr4
        ldx     #0
        ldy     #6
        sec
:       lda     top42,x
        sbc     ms_v,x
        sta     ms_v,x
        inx
        dey
        bne     :-
        ldx     #0
        ldy     #6
        clc
:       lda     ms_v,x
        adc     ms_h,x
        sta     ms_w,x
        inx
        dey
        bne     :-
        ; yl = max(ceil(top), cliptop + 1), ye = min(ceil(bottom), clipbot)
        ldx     #ms_v - cclip
        jsr     row48
        ldx     ms_x
        cmp     m_yl,x                  ; cliptop
        beq     :+
        bcs     :++
:       lda     m_yl,x
        inc     a
:       sta     ps_x1                   ; yl
        ldx     #ms_w - cclip
        jsr     row48
        ldx     ms_x
        cmp     m_ye,x
        bcc     :+
        lda     m_ye,x
:       sta     m_ye,x                  ; ye
        lda     ps_x1
        cmp     m_ye,x
        bcc     :+
        stz     m_yl,x                  ; nothing to draw
        jmp     @step
:       sta     m_yl,x
        ; the column's texel address: addr + ((col & wmask) << log2h)
        lda     m_slo,x
        and     ms_tex+TEX_WMASK
        sta     ps_t
        lda     #0
        ldy     ms_tex+TEX_LOG2H
        beq     :++
:       asl     ps_t
        rol     a
        dey
        bne     :-
:       tay
        clc
        lda     ps_t
        adc     ms_tex+TEX_ADDR
        sta     m_slo,x
        tya
        adc     ms_tex+TEX_ADDR+1
        sta     m_shi,x
        ; the colormap: fixed, or walllights[min(scale >> 11, 47)]
        lda     r_fixedcm
        cmp     #$FF
        bne     @cm
        lda     ms_sc+2
        cmp     #2
        bcs     :+
        lsr     a
        lda     ms_sc+1
        ror     a
        lsr     a
        lsr     a
        cmp     #MAXLIGHTSCALE
        bcc     :++
:       lda     #MAXLIGHTSCALE - 1
:       tay
        lda     ms_wl
        sta     cf_p
        lda     ms_wl+1
        sta     cf_p+1
        lda     (cf_p),y
@cm:    clc
        adc     #>DD_COLORMAPS
        sta     m_cm,x
        ; iscale, the step, f = bytes 1, 2 of (texturemid << 11) + (yl - 42) * iscale
        ldx     #2
:       lda     ms_sc,x
        sta     is_s,x
        dex
        bpl     :-
        jsr     r_iscale
        ldx     ms_x
        clc
        lda     is_r
        sta     dv_is
        adc     #$80
        lda     is_r+1
        sta     dv_is+1
        adc     #0
        sta     m_stl,x
        lda     is_r+2
        sta     dv_is+2
        adc     #0
        sta     m_sth,x
        lda     m_yl,x
        jsr     mul_row
        ldx     ms_x
        clc
        lda     ms_v+1
        adc     ms_tm+1
        sta     m_flo,x
        lda     ms_v+2
        adc     ms_tm+2
        sta     m_fhi,x
@step:  ; T += dT, H += dH, scale += scalestep
        ldx     #0
        ldy     #6
        clc
:       lda     ms_t,x
        adc     ms_dt,x
        sta     ms_t,x
        inx
        dey
        bne     :-
        ldx     #0
        ldy     #6
        clc
:       lda     ms_h,x
        adc     ms_dh,x
        sta     ms_h,x
        inx
        dey
        bne     :-
        ldx     #0
        ldy     #3
        clc
:       lda     ms_sc,x
        adc     ms_st,x
        sta     ms_sc,x
        inx
        dey
        bne     :-
        lda     ms_x
        cmp     ms_r2
        inc     ms_x
        jcc     @col
        jmp     ms_draw

.segment "RLOCODE"                ; (main memory, below the tables)

; ---------------------------------------------------------------------------
; draw_psprites: the weapon layers of the packet (R_DrawPSprite)
draw_psprites:
        stz     sp_i
@l:     lda     sp_i
        cmp     rv_buf+RV_NPSPRITES
        bcs     @done
        cmp     #2
        bcs     @done
        jsr     draw_psprite
        inc     sp_i
        bra     @l
@done:  rts

; draw_psprite: A = layer (one texel per pixel)
draw_psprite:
        asl     a                       ; RV_PSPRITES + 10 * layer
        sta     ps_t
        asl     a
        asl     a
        adc     ps_t
        adc     #RV_PSPRITES
        sta     ms_x
        tay
        lda     rv_buf+RP_SPRITE,y
        cmp     #$FF
        bne     :+
        rts
:       stz     pj_rot
        tax
        lda     rv_buf+RP_FRAME,y
        jsr     sprite_lump
        bcc     :+
        rts
:       jsr     patch_of
        lda     pj_lump+1
        sta     dv_flip
        ; x1 = 80 + ((sx - (160 << 16)) >> 17) - left (tx's high half + 80)
        ldy     ms_x
        sec
        lda     rv_buf+RP_SX+2,y
        sbc     #160
        tax
        lda     rv_buf+RP_SX+3,y
        sbc     #0
        cmp     #$80
        ror     a
        sta     ps_t+1
        txa
        ror     a
        sec
        sbc     pj_buf+SPRLUMP_LEFT
        tax
        lda     ps_t+1
        sbc     pj_buf+SPRLUMP_LEFT+1
        sta     ps_x1+1
        clc
        txa
        adc     #CENTERX
        sta     ps_x1
        bcc     :+
        inc     ps_x1+1
:       ; beyond the right edge: nothing
        lda     ps_x1+1
        bmi     :+
        bne     @out
        lda     ps_x1
        cmp     #VIEW_W
        bcs     @out
:       ; x2 = x1 + width - 1; left of the view: nothing
        clc
        lda     ps_x1
        adc     pj_buf+SPRLUMP_WIDTH
        tax
        lda     ps_x1+1
        adc     #0
        sta     ps_t+1
        txa
        bne     :+
        dec     ps_t+1
:       dec     a
        sta     ps_t                    ; x2 (s16 in ps_t, ps_t+1)
        lda     ps_t+1
        bpl     :+
@out:   rts
:       ; the columns on screen, the columns clipped off the left
        stz     dv_skip
        stz     dv_skip+1
        lda     ps_x1+1
        bpl     :+
        sec
        lda     #0
        sbc     ps_x1
        sta     dv_skip
        lda     #0
        sbc     ps_x1+1
        sta     dv_skip+1
        lda     #0
        bra     :++
:       lda     ps_x1
:       sta     dv_x
        lda     ps_t+1
        bne     @x2max
        lda     ps_t
        cmp     #VIEW_W
        bcc     :+
@x2max: lda     #VIEW_W - 1
:       sta     dv_x2
        ; texturemid = (((100 << 16) + $8000 - sy) >> 1) + (top << 16)
        ldy     ms_x
        sec
        lda     #$00
        sbc     rv_buf+RP_SY,y
        sta     ms_v
        lda     #$80
        sbc     rv_buf+RP_SY+1,y
        sta     ms_v+1
        lda     #BASEYCENTER
        sbc     rv_buf+RP_SY+2,y
        sta     ms_v+2
        lda     #0
        sbc     rv_buf+RP_SY+3,y
        cmp     #$80
        ror     a
        sta     ms_v+3
        ror     ms_v+2
        ror     ms_v+1
        ror     ms_v
        clc
        lda     ms_v+2
        adc     pj_buf+SPRLUMP_TOP
        sta     ms_v+2
        lda     ms_v+3
        adc     pj_buf+SPRLUMP_TOP+1
        sta     ms_v+3
        ldx     #0                      ; its sign extension to 48 bits
        and     #$80
        beq     :+
        dex
:       stx     ms_v+4
        stx     ms_v+5
        ldx     #2
:       lda     ms_v,x
        sta     dv_tm,x
        dex
        bpl     :-
        ; sprtopscreen = (42 << 16) - texturemid
        jsr     top_sub
        ; spryscale = iscale = 1.0
        stz     dv_ys
        stz     dv_ys+1
        lda     #1
        sta     dv_ys+2
        stz     dv_is
        stz     dv_is+1
        sta     dv_is+2
        ; the colormap: fixed, full bright, or the eye sector's
        lda     r_fixedcm
        cmp     #$FF
        bne     @cm
        ldy     ms_x
        lda     rv_buf+RP_FRAME,y
        bpl     :+
        lda     #0
        bra     @cm
:       lda     ps_cm
@cm:    clc
        adc     #>DD_COLORMAPS
        sta     dv_cm
        ; the clip rows: the whole view
        ldx     dv_x
:       lda     #ROWBIAS - 1
        sta     mc_top,x
        lda     #ROWBIAS + VIEW_H
        sta     mc_bot,x
        cpx     dv_x2
        inx
        bcc     :-
        jmp     draw_vis

; sp_thing: the sprite's thing's x, y, z into sp_tb; sp_gz4 = gz >> 4,
; sp_gz4 + 3 = (gzt + 15) >> 4 (for the silhouettes)
sp_thing:
        lda     sp_thok
        jne     @done
        inc     sp_thok
        ldx     sp_v
        lda     vis_th,x
        ; _rview + RV_THINGS + 20 * i
        sta     ps_t
        stz     ps_t+1
        asl     ps_t
        rol     ps_t+1
        asl     ps_t
        rol     ps_t+1                  ; 4i
        lda     ps_t
        ldy     ps_t+1
        asl     ps_t
        rol     ps_t+1
        asl     ps_t
        rol     ps_t+1                  ; 16i
        clc
        adc     ps_t
        sta     ps_t
        tya
        adc     ps_t+1
        sta     ps_t+1                  ; 20i
        clc
        lda     ps_t
        adc     #<(RV_PACKET_ADDR + RV_THINGS)
        sta     rb_src
        lda     ps_t+1
        adc     #>(RV_PACKET_ADDR + RV_THINGS)
        sta     rb_src+1
        lda     #RV_PACKET_BANK
        sta     rb_bank
        lda     #<sp_tb
        sta     rb_dst
        lda     #>sp_tb
        sta     rb_dst+1
        ldx     #12
        jsr     rb2_read
        ; gz >> 4
        ldx     #0
        lda     sp_tb+8
        ldy     sp_tb+9
        jsr     @shr4
        ; (gzt + 15) >> 4, gzt = texturemid + vz
        ldx     sp_v
        clc
        lda     vis_t0,x
        adc     vz
        sta     ps_t
        lda     vis_t1,x
        adc     vz+1
        sta     ps_t+1
        lda     vis_t2,x
        adc     vz+2
        sta     ps_t+2
        clc
        lda     ps_t
        adc     #15
        pha
        lda     ps_t+1
        adc     #0
        tay
        lda     ps_t+2
        adc     #0
        sta     sp_tb+10                ; (z's top byte: not needed any more)
        pla
        ldx     #3
@shr4:  ; A/Y/sp_tb+10 (s24) >> 4 -> sp_gz4 + X
        phy
        tay
        lda     shr4tab,y
        ply
        ora     shl4tab,y
        sta     sp_gz4,x
        lda     shr4tab,y
        ldy     sp_tb+10
        ora     shl4tab,y
        sta     sp_gz4+1,x
        lda     sar4tab,y
        sta     sp_gz4+2,x
@done:  rts

; fz_load: colormap FUZZ_COLORMAP (any graphics bank has it) -> fz_cm
fz_load:
        lda     fz_ok
        bne     :+
        inc     fz_ok
        lda     dv_bank
        sta     rb_bank
        lda     #<(DD_COLORMAPS + 256 * FUZZ_COLORMAP)
        sta     rb_src
        lda     #>(DD_COLORMAPS + 256 * FUZZ_COLORMAP)
        sta     rb_src+1
        lda     #<fz_cm
        sta     rb_dst
        lda     #>fz_cm
        sta     rb_dst+1
        ldx     #0
        jmp     rb2_read
:       rts

.segment "RCODE"                ; (main memory (read-only window))

; vtx_read: X = 0 (v1) / 2 (v2) of sp_seg, A/Y = destination -> the vertex
vtx_read:
        pha
        lda     sp_seg,x
        sta     ei
        lda     sp_seg+1,x
        sta     ei+1
        pla
        ldx     #MAPARR_VERTEXES
; map_read4: X = array, ei = index, A/Y = destination -> its first 4 bytes
map_read4:
        sta     rb_dst
        sty     rb_dst+1
        jsr     elem_addr
        ldx     #4
        jmp     rb2_read


; vis_sort: ord = the vissprites by scale, ties in the order made
vis_sort:
        ldx     #0
@j:     cpx     vis_n
        beq     @done
        stx     ps_t+3                  ; j
        lda     vis_sc0,x
        sta     ps_t
        lda     vis_sc1,x
        sta     ps_t+1
        lda     vis_sc2,x
        sta     ps_t+2
        txa
        tay                             ; i = j
@i:     cpy     #0
        beq     @put
        ldx     ord-1,y
        ; scale[ord[i - 1]] > key: move it up
        lda     ps_t
        cmp     vis_sc0,x
        lda     ps_t+1
        sbc     vis_sc1,x
        lda     ps_t+2
        sbc     vis_sc2,x
        bcs     @put                    ; key >= it
        txa
        sta     ord,y
        dey
        bra     @i
@put:   lda     ps_t+3
        sta     ord,y
        tax
        inx
        bra     @j
@done:  rts

.segment "RHICODE"

; cmp_sil: X = DS_BSIL / DS_TSIL, Y = 0 (gz >> 4) / 3 ((gzt + 15) >> 4) ->
; C set if the thing's value >= the drawseg's (map units); ps_t+3 = 0 if equal
cmp_sil:
        sec
        lda     sp_gz4,y
        sbc     dsrec,x
        sta     ps_t
        lda     sp_gz4+1,y
        sbc     dsrec+1,x
        sta     ps_t+1
        lda     dsrec+1,x               ; the drawseg's sign extension
        and     #$80
        beq     :+
        lda     #$FF
:       sta     ps_t+2
        lda     sp_gz4+2,y
        sbc     ps_t+2
        sta     ps_t+2
        ora     ps_t+1
        ora     ps_t
        sta     ps_t+3
        lda     ps_t+2
        eor     #$80
        asl     a                       ; C = not the sign
        rts

; tm_shl11: ps_t/ps_t+1 = texturemid's low bytes -> X/A = bytes 1, 2 of
; texturemid << 11
tm_shl11:
        lda     ps_t
        asl     a
        asl     a
        asl     a
        tax
        lda     ps_t
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     ps_t
        lda     ps_t+1
        asl     a
        asl     a
        asl     a
        ora     ps_t
        rts

; smul33: m_r (6 bytes) = m_a (s24) * m_b (s24)
smul33:
        lda     #3
        sta     mul_na
        sta     mul_nb
        jmp     smul

; mr_shr4: ms_v = m_r (s48) >> 4
mr_shr4:
        ldx     #0
:       ldy     m_r,x
        lda     shr4tab,y
        ldy     m_r+1,x
        ora     shl4tab,y
        sta     ms_v,x
        inx
        cpx     #5
        bne     :-
        ldy     m_r+5
        lda     sar4tab,y
        sta     ms_v+5
        rts

; top_sub: dv_top = (42 << 16) - ms_v (48 bits)
top_sub:
        ldx     #0
        ldy     #6
        sec
:       lda     top42,x
        sbc     ms_v,x
        sta     dv_top,x
        inx
        dey
        bne     :-
        rts
top42:  .byte   0, 0, CENTERY, 0, 0, 0

; lump_rec: pj_lump -> pj_buf = its SPRLUMP record, dv_bank, dv_addr, dv_cb
lump_rec:
        lda     pj_lump+1
        sta     ps_t+1
        lda     pj_lump
        ldx     #3
:       asl     a
        rol     ps_t+1
        dex
        bne     :-
        clc
        adc     #<DD_SPRLUMP
        sta     rb_src
        lda     ps_t+1
        adc     #>DD_SPRLUMP
        sta     rb_src+1
        lda     #DD_DIR_BANK
        sta     rb_bank
        lda     #<pj_buf
        sta     rb_dst
        lda     #>pj_buf
        sta     rb_dst+1
        ldx     #SPRLUMP_SIZE
        jsr     rb2_read
patch_of:
        lda     pj_buf+SPRLUMP_BANK
        sta     dv_bank
        lda     pj_buf+SPRLUMP_ADDR
        sta     dv_addr
        clc
        adc     #6
        sta     dv_cb
        lda     pj_buf+SPRLUMP_ADDR+1
        sta     dv_addr+1
        adc     #0
        sta     dv_cb+1
        rts

.segment "RHICODE"                ; (main memory)

; row48: X = offset from cclip of a 6-byte value -> A = ceil(value / 65536)
; + 64, saturated to 1..255
row48:
        clc
        lda     cclip,x
        adc     #$FF
        lda     cclip+1,x
        adc     #$FF
        lda     cclip+2,x
        adc     #0
        sta     ps_t                    ; the row: low byte
        lda     cclip+3,x
        adc     #0
        sta     ps_t+1                  ; high byte
        lda     cclip+4,x
        adc     #0
        sta     ps_t+2
        lda     cclip+5,x
        adc     #0
        bmi     @neg
        ora     ps_t+2
        ora     ps_t+1
        bne     @max
        lda     ps_t
        cmp     #256 - ROWBIAS
        bcs     @max
        adc     #ROWBIAS
        rts
@neg:   and     ps_t+2
        and     ps_t+1
        cmp     #$FF
        bne     @one
        lda     ps_t
        cmp     #<(1 - ROWBIAS)
        bcc     @one
        adc     #ROWBIAS - 1            ; (C set)
        rts
@one:   lda     #1
        rts
@max:   lda     #255
        rts


; seg_side: R_PointOnSegSide(gx, gy, the seg of dsrec) -> A (Z set: front)
seg_side:
        lda     dsrec+DS_SEG
        sta     ei
        lda     dsrec+DS_SEG+1
        sta     ei+1
        ldx     #MAPARR_SEGS
        lda     #<sp_seg
        ldy     #>sp_seg
        jsr     map_read4
        ldx     #0
        lda     #<pos_lx                ; pos_lx, pos_ly
        ldy     #>pos_lx
        jsr     vtx_read
        ldx     #2
        lda     #<sp_v2
        ldy     #>sp_v2
        jsr     vtx_read
        sec
        lda     sp_v2
        sbc     pos_lx
        sta     pos_ldx
        lda     sp_v2+1
        sbc     pos_lx+1
        sta     pos_ldx+1
        sec
        lda     sp_v2+2
        sbc     pos_ly
        sta     pos_ldy
        lda     sp_v2+3
        sbc     pos_ly+1
        sta     pos_ldy+1
        ldx     #2
:       lda     sp_tb,x
        sta     pos_px,x
        lda     sp_tb+4,x
        sta     pos_py,x
        dex
        bpl     :-
        jsr     point_on_side
        cmp     #0
        rts

; ds_read: A = drawseg -> dsrec
ds_read:
        jsr     ds_addr
        sta     rb_src
        stx     rb_src+1
        lda     #RENDER_BANK
        sta     rb_bank
        lda     #<dsrec
        sta     rb_dst
        lda     #>dsrec
        sta     rb_dst+1
        ldx     #DS_SIZE
        jmp     rb2_read

; dv_frac0: the first column's patch column and the step: flipped, from
; (width << 16) - 1 by -iscale, else from 0 by iscale; dv_skip columns on
dv_frac0:
        lda     dv_is
        sta     dv_xstep
        sta     m_a
        lda     dv_is+1
        sta     dv_xstep+1
        sta     m_a+1
        lda     dv_is+2
        sta     dv_xstep+2
        sta     m_a+2
        stz     dv_xstep+3
        lda     dv_skip
        sta     m_b
        lda     dv_skip+1
        sta     m_b+1
        jsr     mulu_3_2_5              ; iscale * skip
        bit     dv_flip
        bmi     @flip
        ldx     #3
:       lda     m_r,x
        sta     dv_frac,x
        dex
        bpl     :-
        rts
@flip:  ; (width << 16) - 1 - iscale * skip; the step -iscale
        lda     #$FF
        sta     dv_frac
        sta     dv_frac+1
        ldx     dv_w
        dex
        stx     dv_frac+2
        stz     dv_frac+3
        ldx     #0
        ldy     #4
        sec
:       lda     dv_frac,x
        sbc     m_r,x
        sta     dv_frac,x
        inx
        dey
        bne     :-
        ldx     #0
        ldy     #4
        sec
:       lda     #0
        sbc     dv_xstep,x
        sta     dv_xstep,x
        inx
        dey
        bne     :-
        rts

; fz_flush: the listed posts of a shadow: rows max(yl, 1) .. min(yh, 82),
; each the colormap-3 shade of the pixel fuzzoffset[fuzzpos] rows away
fz_flush:
        ldx     #0
@e:     cpx     fz_n
        beq     @done
        ldy     fzl_x,x
        lda     coladdr_lo,y
        sta     cf_p
        lda     coladdr_hi,y
        sta     cf_p+1
        lda     fzl_ye,x                ; the end: min(yh, 82) + 1
        sec
        sbc     #ROWBIAS
        cmp     #VIEW_H - 1
        bcc     :+
        lda     #VIEW_H - 1
:       sta     @end+1
        lda     fzl_yl,x                ; the first row: max(yl, 1)
        sec
        sbc     #ROWBIAS
        bne     :+
        lda     #1
:       cmp     @end+1
        bcs     @n
        phx
        tax                             ; the row
        ldy     fuzzpos
@y:     stx     ps_t
        txa
        clc
        adc     fuzzoffset,y            ; +-1 row
        sty     ps_t+1
        tay
        lda     (cf_p),y
        tay
        lda     fz_cm,y
        ldy     ps_t
        sta     (cf_p),y
        ldy     ps_t+1
        iny
        cpy     #FUZZTABLE
        bne     :+
        ldy     #0
:       inx
@end:   cpx     #0
        bne     @y
        sty     fuzzpos
        plx
@n:     inx
        bra     @e
@done:  stz     fz_n
        rts

.segment "RTEXTDATA"               ; (main memory, the text pages: read-only code)

; mul_row: A = a biased row -> ms_v = the low 3 bytes of (row - 42) * dv_is
; (quarter squares; the row is 0..83)
mul_row:
        sec
        sbc     #ROWBIAS + CENTERY
        php
        bpl     :+
        eor     #$FF
        inc     a
:       stz     ms_v
        stz     ms_v+1
        stz     ms_v+2
        tax
        beq     @sign
        sta     ms1
        sta     ms3
        eor     #$FF
        sta     ms2
        sta     ms4
        ldy     dv_is
        sec
        lda     (ms1),y
        sbc     (ms2),y
        sta     ms_v
        lda     (ms3),y
        sbc     (ms4),y
        sta     ms_v+1
        ldy     dv_is+1
        sec
        lda     (ms1),y
        sbc     (ms2),y
        tax
        lda     (ms3),y
        sbc     (ms4),y
        tay
        txa
        clc
        adc     ms_v+1
        sta     ms_v+1
        tya
        adc     #0
        sta     ms_v+2
        ldy     dv_is+2
        sec
        lda     (ms1),y
        sbc     (ms2),y
        clc
        adc     ms_v+2
        sta     ms_v+2
@sign:  plp
        bpl     @done
        ldx     #0
        ldy     #3
        sec
:       lda     #0
        sbc     ms_v,x
        sta     ms_v,x
        inx
        dey
        bne     :-
@done:  rts

.segment "RLCHI"                ; (the language card's $E000 area)

; ---------------------------------------------------------------------------
; msr_setup: A = drawseg -> its masked middle's setup (kept for the last
; one set up): its fields, the texture's record, texturemid, the light, the
; steps of texturemid * scale and scale * height
msr_setup:
        cmp     ms_ds
        bne     :+
        rts
:       sta     ms_ds
        jsr     ds_read
        lda     dsrec+DS_X1
        sta     ms_x1
        lda     dsrec+DS_X2
        sta     ms_x2
        ldx     #2
:       lda     dsrec+DS_SCALE1,x
        sta     ms_s1,x
        lda     dsrec+DS_STEP,x
        sta     ms_st,x
        sta     m_b,x
        lda     dsrec+DS_TMID,x
        sta     ms_tmid,x
        sta     m_a,x
        dex
        bpl     :-
        ldx     #1
:       lda     dsrec+DS_TOPCLIP,x
        sta     ms_tc,x
        lda     dsrec+DS_BOTCLIP,x
        sta     ms_bc,x
        lda     dsrec+DS_MTC,x
        sta     ms_mtc,x
        dex
        bpl     :-
        ; dT = texturemid * scalestep
        jsr     smul33
        ldx     #5
:       lda     m_r,x
        sta     ms_dt,x
        dex
        bpl     :-
        ; texturemid << 11 (mod 2^24)
        lda     ms_tmid
        sta     ps_t
        lda     ms_tmid+1
        sta     ps_t+1
        jsr     tm_shl11
        stx     ms_tm+1
        sta     ms_tm+2
        ; the light row
        lda     dsrec+DS_LIGHT
        jsr     light_row
        sta     ms_wl
        stx     ms_wl+1
        ; the texture's record: DD_TEXDIR + 16 * texture
        lda     dsrec+DS_TEX+1
        sta     ps_t+1
        lda     dsrec+DS_TEX
        ldx     #4
:       asl     a
        rol     ps_t+1
        dex
        bne     :-
        clc
        adc     #<DD_TEXDIR
        sta     rb_src
        lda     ps_t+1
        adc     #>DD_TEXDIR
        sta     rb_src+1
        lda     #DD_DIR_BANK
        sta     rb_bank
        lda     #<ms_tex
        sta     rb_dst
        lda     #>ms_tex
        sta     rb_dst+1
        ldx     #TEX_SIZE
        jsr     rb2_read
        ; dH = scalestep * height
        ldx     #2
:       lda     ms_st,x
        sta     m_a,x
        dex
        bpl     :-
        ldy     #ms_dh - cclip
        ; (on into mul_h)

; mul_h: m_a (s24) * the texture's height -> 6 bytes at cclip + Y
mul_h:
        lda     ms_tex+TEX_HEIGHT
        sta     m_b
        lda     ms_tex+TEX_HEIGHT+1
        sta     m_b+1
        lda     #3
        sta     mul_na
        lda     #2
        sta     mul_nb
        phy
        jsr     smul
        ply
        ldx     #0
:       lda     m_r,x
        sta     cclip,y
        iny
        inx
        cpx     #5
        bne     :-
        lda     m_r+4
        and     #$80
        beq     :+
        lda     #$FF
:       sta     cclip,y
        rts

; masked_rest: the masked middles not drawn yet, last drawseg first
masked_rest:
        lda     #1
        jsr     ds_scan
        lda     dv_len
        sta     ml_n
        stz     ml_i
@m:     ldx     ml_i
        cpx     ml_n
        beq     @done
        lda     cand,x
        jsr     msr_setup
        lda     ms_x1
        sta     ms_r1
        lda     ms_x2
        sta     ms_r2
        jsr     msr_range
        inc     ml_i
        bra     @m
@done:  rts
