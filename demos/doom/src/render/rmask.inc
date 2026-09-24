; Doom for the Appletini -- the masked phase's memory (docs/DESIGN.md 7.2):
; rthings.s (the vissprites) and rmasked.s (sprites, two-sided middles, the
; weapon) share these.
;
; The masked phase runs after the walls and the planes, so it takes over
; buffers that are dead by then instead of memory of its own (there is
; none left): the BSP node stack and the vertex cache (rmain.s), the clip
; arrays (rmain.s), the plane copy-back and the span column cache
; (rplane.s), the wall range's marks (rsegs.s), the seg loop's zero page,
; and, in the language card's $E000 area (readable while RAMRD is on, in
; either $D000 bank), the visplane headers and the span row cache
; (rplane.s). Each region is contiguous inside one module; rmasked.s
; asserts the layout at link time.

.import bsp_stack, cclip, ct, pt_top, xc_ok, pl_hlo

; ---------------------------------------------------------------------------
; the vissprites: structure of arrays, MAXVISSPRITES each, in the node
; stack and the vertex cache (704 + 1,024 bytes, rmain.s)
VS_REGION   = 1728
VN          = MAXVISSPRITES
vis_th      = bsp_stack             ; the thing (packet index)
vis_sc0     = vis_th + VN           ; scale (xscale, 16.16 pixels per unit)
vis_sc1     = vis_sc0 + VN
vis_sc2     = vis_sc1 + VN
vis_x1      = vis_sc2 + VN          ; columns, clipped to the view
vis_x2      = vis_x1 + VN
vis_sk0     = vis_x2 + VN           ; columns clipped off the left (x1c - x1)
vis_sk1     = vis_sk0 + VN
vis_i0      = vis_sk1 + VN          ; iscale (texels per pixel, 16.16)
vis_i1      = vis_i0 + VN
vis_i2      = vis_i1 + VN
vis_llo     = vis_i2 + VN           ; the SPRLUMP; bit 7 of vis_lhi: flipped
vis_lhi     = vis_llo + VN
vis_cm      = vis_lhi + VN          ; stored colormap, $FF shadow (fuzz)
vis_t0      = vis_cm + VN           ; texturemid = gzt - vz (s24 sub-units)
vis_t1      = vis_t0 + VN
vis_t2      = vis_t1 + VN
VS_END      = vis_t2 + VN

; ---------------------------------------------------------------------------
; the wall range's marks (ct .. mtcbuf, 800 bytes, rsegs.s)
CT_REGION   = 800
th_slo      = ct                    ; the things' sectors (packet order)
th_shi      = th_slo + 128
th_next     = th_shi + 128          ; the next thing of the same bucket
th_head     = th_next + 128         ; first / last thing of a bucket
th_tail     = th_head + 64
ord         = th_tail + 64          ; the vissprites sorted (draw order)
dsrec       = ord + VN              ; a drawseg record
mlist       = dsrec + DS_SIZE       ; drawsegs with masked middles
CT_END      = mlist + MAXDRAWSEGS

; the plane copy-back (pt_top .. spanstart, 408 bytes, rplane.s): the
; fuzz list (column, first row, end row; FZ_N entries)
FZ_N        = 128
fzl_x       = pt_top
fzl_yl      = fzl_x + FZ_N
fzl_ye      = fzl_yl + FZ_N

; the span column cache (xc_ok .. xc_shi, 800 bytes, rplane.s)
cand        = xc_ok                 ; a sprite's candidate drawsegs
candf       = cand + MAXDRAWSEGS    ; their flags (bit 7: entirely behind it)
fz_cm       = candf + MAXDRAWSEGS   ; colormap FUZZ_COLORMAP (256 bytes)

; ---------------------------------------------------------------------------
; language card $E000 area: the visplane headers and the span row cache
; (pl_hlo .. rc_ys1, 1,904 bytes, rplane.s): readable in a RAMRD session
LC_REGION   = 1904
mc_top      = pl_hlo                ; the sprite's clip rows (biased), by column
mc_bot      = mc_top + VIEW_W
; a masked middle's columns (rmasked.s msr), by column
m_slo       = mc_bot + VIEW_W       ; texture column address
m_shi       = m_slo + VIEW_W
m_yl        = m_shi + VIEW_W        ; first row (biased; 0: nothing)
m_ye        = m_yl + VIEW_W         ; last row + 1 (biased)
m_flo       = m_ye + VIEW_W         ; f (8.8)
m_fhi       = m_flo + VIEW_W
m_stl       = m_fhi + VIEW_W        ; step
m_sth       = m_stl + VIEW_W
m_cm        = m_sth + VIEW_W        ; colormap page
LC_END      = m_cm + VIEW_W
; the sprite being drawn (the same place: a sprite is drawn after its
; clipping, which is when two-sided middles are drawn)
rowt        = mc_bot + VIEW_W       ; rowt[k]: ceil(row of post offset k), biased
yf_lo       = rowt + 256            ; yf[y]: f of row y (y 0..83)
yf_hi       = yf_lo + VIEW_H

; ---------------------------------------------------------------------------
; the phase's variables: in the clip arrays (cclip, fclip: 320 bytes)
MS_REGION   = 2 * VIEW_W
__ms        .set 0
.macro MSVAR name, size
name        = cclip + __ms
__ms        .set __ms + size
.endmacro
        MSVAR   rd_vec, 2           ; dir_read's bank read (rb_read / rb2_read)
        MSVAR   vis_n, 1            ; vissprites this frame
        MSVAR   viewcos, 2          ; cos_bam(va), sin_bam(va) (Q14)
        MSVAR   viewsin, 2
        MSVAR   ps_cm, 1            ; the weapon's colormap (not full bright)
        MSVAR   pj_buf, 16          ; SPRDEF, SPRFRAME, SPRLUMP records
        MSVAR   pj_t, 4             ; scratch
        MSVAR   pj_rot, 1           ; the rotation (0..7)
        MSVAR   pj_lump, 2          ; SPRFRAME entry: lump, bit 15 flipped
        MSVAR   sp_v, 1             ; the vissprite being drawn
        MSVAR   sp_x1, 1
        MSVAR   sp_x2, 1
        MSVAR   sp_sc, 3            ; its scale
        MSVAR   sp_ci, 1            ; the next candidate
        MSVAR   cand_n, 1           ; candidates
        MSVAR   sp_thok, 1          ; its thing is in sp_tb
        MSVAR   sp_tb, 12           ; x, y, z of the thing (32-bit each)
        MSVAR   sp_gz4, 6           ; gz >> 4, (gzt + 15) >> 4 (s24 map units)
        MSVAR   sp_sil, 1
        MSVAR   sp_seg, 4           ; v1, v2 of a drawseg's seg
        MSVAR   sp_v2, 4
        MSVAR   sp_i, 1             ; the loop over the vissprites
        MSVAR   dv_bank, 1          ; draw_vis: the patch's bank
        MSVAR   dv_top, 6           ; sprtopscreen (s48, 16.16)
        MSVAR   dv_ys, 3            ; spryscale (pixels per texel)
        MSVAR   dv_is, 3            ; iscale (texels per pixel)
        MSVAR   dv_tm, 3            ; texturemid (texels 16.16), mod 2^24
        MSVAR   dv_cm, 1            ; colormap page; 0: the fuzz
        MSVAR   dv_skip, 2          ; columns clipped off the left
        MSVAR   dv_flip, 1          ; bit 7: flipped
        MSVAR   dv_hdr, 2           ; the patch's width and height
        MSVAR   bs_s, 6             ; build_rows' accumulator
        MSVAR   fuzzpos, 1
        MSVAR   fz_ok, 1            ; fz_cm is loaded
        MSVAR   ms_ds, 1            ; msr: the drawseg set up ($FF none)
        MSVAR   ms_x1, 1
        MSVAR   ms_x2, 1
        MSVAR   ms_s1, 3            ; scale1
        MSVAR   ms_st, 3            ; scalestep
        MSVAR   ms_tc, 2            ; clip pointers, masked columns
        MSVAR   ms_bc, 2
        MSVAR   ms_mtc, 2
        MSVAR   ms_tex, TEX_SIZE    ; the texture's record
        MSVAR   ms_wl, 2            ; the walllights row
        MSVAR   ms_tmid, 3          ; texturemid (s24 sub-units)
        MSVAR   ms_tm, 3            ; texturemid << 11, mod 2^24
        MSVAR   ms_dt, 6            ; texturemid * scalestep
        MSVAR   ms_dh, 6            ; scalestep * height
        MSVAR   ms_sc, 3            ; the column's scale
        MSVAR   ms_t, 6             ; texturemid * scale
        MSVAR   ms_h, 6             ; scale * height
        MSVAR   ms_v, 6             ; sprtopscreen
        MSVAR   ms_w, 6             ; bottomscreen
        MSVAR   ms_r1, 1            ; the columns to draw
        MSVAR   ms_r2, 1
        MSVAR   ms_x, 1
        MSVAR   ml_n, 1
        MSVAR   ml_i, 1
        MSVAR   ps_t, 4             ; scratch
        MSVAR   ps_x1, 2
.assert __ms <= MS_REGION, error, "rmask.inc: the variables overflow the clip arrays"

; ---------------------------------------------------------------------------
; zero page: the seg loop's accumulators (topfrac .. ryh, 41 bytes) are free
; in the masked phase
MZ          = topfrac
