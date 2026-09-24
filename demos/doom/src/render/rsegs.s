; Doom for the Appletini -- wall ranges (docs/DESIGN.md section 7;
; tools/refrender.py scale_from_angle, store_wall_range, mark_plane,
; draw_wall_column, _opening).
;
; store_wall_range (A = start, X = stop: the columns of the seg in segbuf,
; front sector fs_*, back sector bs_* or none) is Doom's R_StoreWallRange
; and R_RenderSegLoop:
;
;   setup   the sidedef and the line's flags; rw_distance and rw_offset as
;           dot products with the seg's normal and direction (sin_bam);
;           the scale at both ends (scale_from_angle: num = 80 sin(b),
;           den = rw_distance sin(a) >> 14, (num << 6) / den clamped) and
;           the step; Doom's pegging, silhouettes and plane marks; the
;           textures of the frame (tex_trans) and their records; topfrac,
;           bottomfrac, pixhigh, pixlow and their steps (32-bit, the
;           reference's s32 wrap); check_plane for the planes marked
;   loop    per column: yl/yh from the accumulators, clipped; the plane
;           marks into ct/cb/ft/fb (main memory) or, for a piece without
;           a visplane (flat-shaded mode, visplane overflow), queued at
;           once as a fill or a sky column; the texture column (rw_offset
;           - tan(angle) * rw_distance >> 12, only its low 8 bits after
;           >> 5 matter: every texture is at most 256 wide), the colormap
;           by scale, iscale from the reciprocal table; the pieces queued
;           for the drawer (rlc.s); the clip arrays updated
;   end     the marks copied into the visplanes (RENDER_BANK), the queue
;           flushed, the drawseg recorded with its openings
;
; Rows are biased bytes (row + ROWBIAS, rdefs.inc), saturated: a row the
; reference would carry beyond -64..191 only ever meets values in
; -2..85 (the clip arrays, whose extremes the saturation keeps in the same
; order), so every comparison, every mark and every pixel is the same;
; -2 (Doom's sprite-clip sentinel) is exact.
;
; The drawseg (DS_SIZE bytes in RENDER_BANK at DS_BASE + 30 * n), for the
; masked phase:
;   +0 x1, +1 x2, +2 scale1 (3), +5 scale2 (3), +8 scalestep (3, signed),
;   +11 silhouette, +12 bsilheight (2, map units: the reference's value is
;   always a height << 4; $7FFF MAXINT), +14 tsilheight (2; $8000 MININT),
;   +16 sprtopclip (2), +18 sprbottomclip (2), +20 maskedtexturecol (2),
;   +22 seg (2); for a masked middle, what R_RenderMaskedSegRange needs of
;   the seg, known here already: +24 the texture of this frame (2), +26
;   texturemid (3, sub-units), +29 the light level index (before clamping)
; The clip pointers are the RENDER_BANK address of column x1's byte in the
; openings (biased rows), or DS_NONE, DS_SCREENHEIGHT (all 84), DS_NEGONE
; (all -1); maskedtexturecol is the address of column x1's two bytes
; (texcol & 255, then 0: the masked phase's "drawn" mark) or DS_NONE.

.include "kernel.inc"
.include "rdefs.inc"
.macpack longbranch
.include "rmul.inc"

.import segbuf, sidebuf, fs_index, fs_floor, fs_ceil, fs_fpic, fs_cpic, fs_light
.import bs_index, bs_floor, bs_ceil, bs_fpic, bs_cpic, bs_light
.import v1x, v1y, v2x, v2y, floorplane, ceilplane, floorpic_t, ceilpic_t
.import cclip, fclip, r_extralight, r_fixedcm
.import fetch_side, fetch_line_flags, shl4, sub_seg
.import tex_trans, tex_fetch, texbuf, flat_fetch, flatbuf, sky_piece
.import tex_get, tc_bank, tc_alo, tc_ahi, tc_wmask, tc_hmask, tc_log2h, tc_hlo, tc_hhi
.import check_plane, pl_start, pl_stop, pl_alo, pl_ahi
.import vp_n, ds_n, op_used, pf_write, pf_n
.import q_in_bank, q_in_dst, q_in_cnt, q_in_src, q_in_f, q_in_step, q_in_cm, q_in_hm
.importzp ei
.import muls_3_2_5, muls_3_3_5, muls_3_3_4, mulu_1_3_3, mulu_3_2_5, mulu_3_3_5
.import div_scale, div_step
.import shr4tab, shl4tab, bitlen
.import q_bank, q_dlo, q_dhi, q_cnt, q_slo, q_shi, q_flo, q_fhi, q_stl, q_sth, q_cm, q_hm

.export store_wall_range, light_row, ds_addr, ct, mtcbuf
.assert finetangent_mid = finetangent_lo + 1024 && finetangent_hi = finetangent_mid + 1024, lderror, "column_tex: the tangent planes must be 1024 apart"


.segment "KZP": zeropage
sg_texcol:  .res 1              ; the column's texture column (& 255)
sg_cm:      .res 1              ; the column's colormap page
sg_isc:     .res 3              ; the column's iscale
sg_step:    .res 2              ; (iscale + 128) >> 8
sg_mid:     .res 1

.segment "RBSS"
sw_start:   .res 1
sw_stop:    .res 1
sw_flags:   .res 1              ; the linedef's flags (low byte)
sw_record:  .res 1              ; a drawseg is recorded
rw_normal:  .res 2              ; rw_normalangle
rw_dist:    .res 3              ; rw_distance (s24)
rw_center:  .res 2              ; rw_centerangle
rw_offset:  .res 3
worldtop:   .res 3
worldbot:   .res 3
worldhigh:  .res 3
worldlow:   .res 3
markfloor:  .res 1
markceil:   .res 1
masked:     .res 1
textured:   .res 1              ; segtextured
tex_on:     .res 3              ; slot in use: 0 mid, 1 top, 2 bottom
wt_bank:    .res 3              ; the slots' textures (translated)
wt_alo:     .res 3
wt_ahi:     .res 3
wt_wmask:   .res 3
wt_hmask:   .res 3
wt_log2h:   .res 3
wt_tm1:     .res 3              ; texturemid << 11, bytes 1 and 2
wt_tm2:     .res 3
walllights: .res 2              ; scalelight row
filllights: .res 2              ; scalelight row of the plane light (fills)
fill_c:     .res 3              ; ceiling fills: sky flag, bank, colour
fill_f:     .res 3              ; floor fills
ds_rec:     .res DS_SIZE        ; the drawseg being built
sw_tm:      .res 3              ; a texturemid being computed
sfa_a:      .res 2              ; sinea
sfa_num:    .res 4
sfa_den:    .res 5
hf_h:       .res 3              ; hfrac's height
hf_step:    .res 4              ; hfrac's step
hf_sign:    .res 1
sg_stepm:   .res 3              ; |rw_step|
sg_steps:   .res 1              ; its sign
sw_n:       .res 1              ; columns in the range
sg_ctop:    .res 1              ; the column's ceilingclip + 1
sg_have:    .res 1              ; the column's texture column is computed
sg_dm:      .res 3              ; |rw_distance|
sg_dsign:   .res 1              ; its sign ($80 negative)
sg_psign:   .res 1              ; the sign of tan * rw_distance
sg_ro:      .res 4              ; (rw_offset << 12) + 4095
wt_sh:      .res 3              ; 8 - log2h per slot
sc_seg:     .res 2              ; the seg whose values are below ($FFFF none)
sc_offok:   .res 1              ; its rw_offset, rw_centerangle, walllights are set
sg_sinna:   .res 2              ; sin_bam(rw_normalangle)
sw_lnum:    .res 1              ; its light level index (walllights' row)
.segment "RLOBSS"
sinea_lo:   .res VIEW_W + 1     ; sin_bam(ANG90 + xtoviewangle[x]) per column
sinea_hi:   .res VIEW_W + 1
.segment "RBSS"
sw_x:       .res 1
dsw_top:    .res 2              ; ds_prepare -> ds_write
dsw_bot:    .res 2
dsw_mtc:    .res 2
dsw_rec:    .res 2
dsa_t:      .res 2              ; ds_addr
dsa_u:      .res 1
.export sw_start, sw_stop

.segment "RLOBSS"
ct:         .res VIEW_W         ; the range's ceiling marks: top ($FF none), bottom
cb:         .res VIEW_W
ft:         .res VIEW_W         ; floor marks
fb:         .res VIEW_W
mtcbuf:     .res VIEW_W         ; masked texture columns

.segment "RHICODE"

; ---------------------------------------------------------------------------
store_wall_range:
        sta     sw_start
        stx     sw_stop
        txa
        sec
        sbc     sw_start
        inc     a
        sta     sw_n
        stz     sw_record
        lda     ds_n
        cmp     #MAXDRAWSEGS
        bcs     :+
        inc     sw_record
:       ; the seg's own values (sidedef, flags, normal, distance, and later
        ; offset and light) are the same for every range of the seg this frame
        lda     sub_seg
        cmp     sc_seg
        bne     @newseg
        lda     sub_seg+1
        cmp     sc_seg+1
        bne     @newseg
        jmp     @scales
@newseg:
        lda     sub_seg
        sta     sc_seg
        lda     sub_seg+1
        sta     sc_seg+1
        stz     sc_offok
        ; the sidedef and the line's flags
        lda     segbuf+SEG_SIDEDEF
        sta     ei
        lda     segbuf+SEG_SIDEDEF+1
        sta     ei+1
        jsr     fetch_side
        lda     segbuf+SEG_LINEDEF
        sta     ei
        lda     segbuf+SEG_LINEDEF+1
        sta     ei+1
        jsr     fetch_line_flags
        sta     sw_flags
        ; rw_normalangle = seg angle + ANG90
        clc
        lda     segbuf+SEG_ANGLE
        sta     rw_normal
        lda     segbuf+SEG_ANGLE+1
        adc     #>ANG90
        sta     rw_normal+1
        ; rw_distance = (dx cos(na) + dy sin(na)) >> 14, d = v1 - eye
        lda     v1x
        ldx     v1x+1
        jsr     shl4
        sec
        lda     t4
        sbc     vx
        sta     m_a
        lda     t5
        sbc     vx+1
        sta     m_a+1
        lda     t6
        sbc     vx+2
        sta     m_a+2
        lda     rw_normal
        sta     s_ang
        lda     rw_normal+1
        sta     s_ang+1
        jsr     cos_bam
        jsr     mul_24_sval             ; m_r = m_a * s_val (5 bytes)
        jsr     acc_save                ; acc = m_r
        lda     v1y
        ldx     v1y+1
        jsr     shl4
        sec
        lda     t4
        sbc     vy
        sta     m_a
        lda     t5
        sbc     vy+1
        sta     m_a+1
        lda     t6
        sbc     vy+2
        sta     m_a+2
        lda     rw_normal
        sta     s_ang
        lda     rw_normal+1
        sta     s_ang+1
        jsr     sin_bam
        lda     s_val                   ; sin(na) = cos(seg angle): rw_offset's too
        sta     sg_sinna
        lda     s_val+1
        sta     sg_sinna+1
        jsr     mul_24_sval
        jsr     acc_add_shr14           ; t0..t2 = (acc + m_r) >> 14
        lda     t0
        sta     rw_dist
        lda     t1
        sta     rw_dist+1
        lda     t2
        sta     rw_dist+2
        ; |rw_distance| and its sign (sfa, column_tex)
        sta     sg_dm+2
        and     #$80
        sta     sg_dsign
        lda     t0
        sta     sg_dm
        lda     t1
        sta     sg_dm+1
        lda     sg_dsign
        beq     @scales
        sec
        lda     #0
        sbc     sg_dm
        sta     sg_dm
        lda     #0
        sbc     sg_dm+1
        sta     sg_dm+1
        lda     #0
        sbc     sg_dm+2
        sta     sg_dm+2
@scales: ; the scales
        ldx     sw_start
        jsr     sfa
        lda     sfa_num
        sta     rw_scale
        sta     ds_rec+DS_SCALE1
        lda     sfa_num+1
        sta     rw_scale+1
        sta     ds_rec+DS_SCALE1+1
        lda     sfa_num+2
        sta     rw_scale+2
        sta     ds_rec+DS_SCALE1+2
        stz     rw_step
        stz     rw_step+1
        stz     rw_step+2
        lda     sw_n
        cmp     #1
        bne     :+
        ; one column: scale2 = scale1, no step
        lda     rw_scale
        sta     ds_rec+DS_SCALE2
        lda     rw_scale+1
        sta     ds_rec+DS_SCALE2+1
        lda     rw_scale+2
        sta     ds_rec+DS_SCALE2+2
        bra     @world
:       ldx     sw_stop
        jsr     sfa
        lda     sfa_num
        sta     ds_rec+DS_SCALE2
        lda     sfa_num+1
        sta     ds_rec+DS_SCALE2+1
        lda     sfa_num+2
        sta     ds_rec+DS_SCALE2+2
        ; scalestep = div_trunc(scale2 - scale1, stop - start)
        sec
        lda     sfa_num
        sbc     rw_scale
        sta     d_n
        lda     sfa_num+1
        sbc     rw_scale+1
        sta     d_n+1
        lda     sfa_num+2
        sbc     rw_scale+2
        sta     d_n+2
        lda     #0
        sbc     #0
        sta     d_n+3                   ; the sign (both scales < 2^23)
        lda     sw_n
        dec     a
        jsr     div_step
        lda     d_n
        sta     rw_step
        lda     d_n+1
        sta     rw_step+1
        lda     d_n+2
        sta     rw_step+2
@world: ; |rw_step| and its sign (hfrac)
        lda     rw_step+2
        and     #$80
        sta     sg_steps
        beq     :+
        sec
        lda     #0
        sbc     rw_step
        sta     sg_stepm
        lda     #0
        sbc     rw_step+1
        sta     sg_stepm+1
        lda     #0
        sbc     rw_step+2
        sta     sg_stepm+2
        bra     :++
:       lda     rw_step
        sta     sg_stepm
        lda     rw_step+1
        sta     sg_stepm+1
        lda     rw_step+2
        sta     sg_stepm+2
:       lda     rw_step
        sta     ds_rec+DS_STEP
        lda     rw_step+1
        sta     ds_rec+DS_STEP+1
        lda     rw_step+2
        sta     ds_rec+DS_STEP+2
        lda     sw_start
        sta     ds_rec+DS_X1
        lda     sw_stop
        sta     ds_rec+DS_X2
        ; worldtop = (ceiling << 4) - vz, worldbottom = (floor << 4) - vz
        lda     fs_ceil
        ldx     fs_ceil+1
        ldy     #worldtop - worldtop
        jsr     world
        lda     fs_floor
        ldx     fs_floor+1
        ldy     #worldbot - worldtop
        jsr     world
        stz     tex_on
        stz     tex_on+1
        stz     tex_on+2
        stz     masked
        stz     markfloor
        stz     markceil
        lda     #DS_NONE
        sta     ds_rec+DS_TOPCLIP
        sta     ds_rec+DS_TOPCLIP+1
        sta     ds_rec+DS_BOTCLIP
        sta     ds_rec+DS_BOTCLIP+1
        sta     ds_rec+DS_MTC
        sta     ds_rec+DS_MTC+1
        lda     bs_index
        and     bs_index+1
        cmp     #$FF
        beq     :+
        jmp     @twosided
:       ; ---- one-sided: the middle texture, both planes marked
        lda     sidebuf+SIDEDEF_MIDTEXTURE
        ldx     sidebuf+SIDEDEF_MIDTEXTURE+1
        jsr     tex_trans
        ldy     #0
        jsr     slot_setup
        lda     #1
        sta     markfloor
        sta     markceil
        lda     sw_flags
        and     #ML_DONTPEGBOTTOM
        beq     @mtop
        ; vtop = (floor + height(raw mid)) << 4, texturemid = vtop - vz
        lda     sidebuf+SIDEDEF_MIDTEXTURE
        ldx     sidebuf+SIDEDEF_MIDTEXTURE+1
        jsr     tex_get
        clc
        lda     fs_floor
        adc     tc_hlo,y
        pha
        lda     fs_floor+1
        adc     tc_hhi,y
        tax
        pla
        jsr     world_tm
        bra     @mset
@mtop:  lda     worldtop
        sta     sw_tm
        lda     worldtop+1
        sta     sw_tm+1
        lda     worldtop+2
        sta     sw_tm+2
@mset:  ldy     #0
        jsr     tm_set
        lda     #SIL_BOTTOM | SIL_TOP
        sta     ds_rec+DS_SIL
        lda     #DS_SCREENHEIGHT
        sta     ds_rec+DS_TOPCLIP
        lda     #DS_NEGONE
        sta     ds_rec+DS_BOTCLIP
        jsr     bsil_max
        jsr     tsil_min
        jmp     @textured

        ; ---- two-sided
@twosided:
        stz     ds_rec+DS_SIL
        ldx     #3
:       stz     ds_rec+DS_BSIL,x
        dex
        bpl     :-
        ; fs_floor > bs_floor: SIL_BOTTOM, bsil = floor << 4
        lda     bs_floor
        cmp     fs_floor
        lda     bs_floor+1
        sbc     fs_floor+1
        bvc     :+
        eor     #$80
:       bpl     @b2                     ; bs_floor >= fs_floor
        lda     #SIL_BOTTOM
        sta     ds_rec+DS_SIL
        lda     fs_floor
        sta     ds_rec+DS_BSIL
        lda     fs_floor+1
        sta     ds_rec+DS_BSIL+1
        bra     @t1
@b2:    ; (bs_floor << 4) > vz: SIL_BOTTOM, bsil MAXINT
        lda     bs_floor
        ldx     bs_floor+1
        jsr     shl4
        sec
        lda     vz
        sbc     t4
        lda     vz+1
        sbc     t5
        lda     vz+2
        sbc     t6
        bpl     @t1                     ; vz >= floor
        lda     #SIL_BOTTOM
        sta     ds_rec+DS_SIL
        jsr     bsil_max
@t1:    ; fs_ceil < bs_ceil: SIL_TOP, tsil = ceil << 4
        lda     fs_ceil
        cmp     bs_ceil
        lda     fs_ceil+1
        sbc     bs_ceil+1
        bvc     :+
        eor     #$80
:       bpl     @t2
        lda     ds_rec+DS_SIL
        ora     #SIL_TOP
        sta     ds_rec+DS_SIL
        lda     fs_ceil
        sta     ds_rec+DS_TSIL
        lda     fs_ceil+1
        sta     ds_rec+DS_TSIL+1
        bra     @cl
@t2:    ; (bs_ceil << 4) < vz: SIL_TOP, tsil MININT
        lda     bs_ceil
        ldx     bs_ceil+1
        jsr     shl4
        sec
        lda     t4
        sbc     vz
        lda     t5
        sbc     vz+1
        lda     t6
        sbc     vz+2
        bpl     @cl
        lda     ds_rec+DS_SIL
        ora     #SIL_TOP
        sta     ds_rec+DS_SIL
        jsr     tsil_min
@cl:    ; bs_ceil <= fs_floor: sprbottomclip negone, bsil MAXINT, SIL_BOTTOM
        lda     fs_floor
        cmp     bs_ceil
        lda     fs_floor+1
        sbc     bs_ceil+1
        bvc     :+
        eor     #$80
:       bmi     @cl2                    ; fs_floor < bs_ceil
        lda     #DS_NEGONE
        sta     ds_rec+DS_BOTCLIP
        jsr     bsil_max
        lda     ds_rec+DS_SIL
        ora     #SIL_BOTTOM
        sta     ds_rec+DS_SIL
@cl2:   ; bs_floor >= fs_ceil: sprtopclip screenheight, tsil MININT, SIL_TOP
        lda     bs_floor
        cmp     fs_ceil
        lda     bs_floor+1
        sbc     fs_ceil+1
        bvc     :+
        eor     #$80
:       bmi     @wh
        lda     #DS_SCREENHEIGHT
        sta     ds_rec+DS_TOPCLIP
        jsr     tsil_min
        lda     ds_rec+DS_SIL
        ora     #SIL_TOP
        sta     ds_rec+DS_SIL
@wh:    ; worldhigh, worldlow
        lda     bs_ceil
        ldx     bs_ceil+1
        ldy     #worldhigh - worldtop
        jsr     world
        lda     bs_floor
        ldx     bs_floor+1
        ldy     #worldlow - worldtop
        jsr     world
        ; the sky hack: both ceilings sky -> worldtop = worldhigh
        lda     fs_cpic
        cmp     #<DD_SKYFLAT
        bne     @marks
        lda     fs_cpic+1
        cmp     #>DD_SKYFLAT
        bne     @marks
        lda     bs_cpic
        cmp     #<DD_SKYFLAT
        bne     @marks
        lda     bs_cpic+1
        cmp     #>DD_SKYFLAT
        bne     @marks
        lda     worldhigh
        sta     worldtop
        lda     worldhigh+1
        sta     worldtop+1
        lda     worldhigh+2
        sta     worldtop+2
@marks: ; markfloor: worldlow != worldbottom, flats or lights differ
        ldx     #2
:       lda     worldlow,x
        cmp     worldbot,x
        bne     @mf1
        dex
        bpl     :-
        lda     bs_fpic
        cmp     fs_fpic
        bne     @mf1
        lda     bs_fpic+1
        cmp     fs_fpic+1
        bne     @mf1
        lda     bs_light
        cmp     fs_light
        beq     @mc
@mf1:   lda     #1
        sta     markfloor
@mc:    ldx     #2
:       lda     worldhigh,x
        cmp     worldtop,x
        bne     @mc1
        dex
        bpl     :-
        lda     bs_cpic
        cmp     fs_cpic
        bne     @mc1
        lda     bs_cpic+1
        cmp     fs_cpic+1
        bne     @mc1
        lda     bs_light
        cmp     fs_light
        beq     @closed
@mc1:   lda     #1
        sta     markceil
@closed:
        ; a closed door: both marked
        lda     fs_floor
        cmp     bs_ceil
        lda     fs_floor+1
        sbc     bs_ceil+1
        bvc     :+
        eor     #$80
:       bpl     @both                   ; bs_ceil <= fs_floor
        lda     bs_floor
        cmp     fs_ceil
        lda     bs_floor+1
        sbc     fs_ceil+1
        bvc     :+
        eor     #$80
:       bmi     @tops
@both:  lda     #1
        sta     markfloor
        sta     markceil
@tops:  ; worldhigh < worldtop: the upper texture
        ldx     #worldhigh - worldtop
        ldy     #0
        jsr     cmp_world               ; C clear: worldhigh < worldtop
        bcs     @bots
        lda     sidebuf+SIDEDEF_TOPTEXTURE
        ldx     sidebuf+SIDEDEF_TOPTEXTURE+1
        jsr     tex_trans
        ldy     #1
        jsr     slot_setup
        lda     sw_flags
        and     #ML_DONTPEGTOP
        beq     :+
        lda     worldtop
        sta     sw_tm
        lda     worldtop+1
        sta     sw_tm+1
        lda     worldtop+2
        sta     sw_tm+2
        bra     @tset
:       lda     sidebuf+SIDEDEF_TOPTEXTURE
        ldx     sidebuf+SIDEDEF_TOPTEXTURE+1
        jsr     tex_get
        clc
        lda     bs_ceil
        adc     tc_hlo,y
        pha
        lda     bs_ceil+1
        adc     tc_hhi,y
        tax
        pla
        jsr     world_tm
@tset:  ldy     #1
        jsr     tm_set
@bots:  ; worldlow > worldbottom: the lower texture
        ldx     #worldbot - worldtop
        ldy     #worldlow - worldtop
        jsr     cmp_world               ; C clear: worldbottom < worldlow
        bcs     @mid
        lda     sidebuf+SIDEDEF_BOTTOMTEXTURE
        ldx     sidebuf+SIDEDEF_BOTTOMTEXTURE+1
        jsr     tex_trans
        ldy     #2
        jsr     slot_setup
        lda     sw_flags
        and     #ML_DONTPEGBOTTOM
        beq     :+
        lda     worldtop
        sta     sw_tm
        lda     worldtop+1
        sta     sw_tm+1
        lda     worldtop+2
        sta     sw_tm+2
        bra     @bset
:       lda     worldlow
        sta     sw_tm
        lda     worldlow+1
        sta     sw_tm+1
        lda     worldlow+2
        sta     sw_tm+2
@bset:  ldy     #2
        jsr     tm_set
@mid:   ; a two-sided middle texture: masked, if the openings allow
        lda     sidebuf+SIDEDEF_MIDTEXTURE
        ora     sidebuf+SIDEDEF_MIDTEXTURE+1
        jeq     @textured
        lda     sw_record
        jeq     @textured
        ; need = 2 * n
        lda     sw_n
        asl     a
        sta     t0
        lda     #0
        rol     a
        sta     t1
        clc
        lda     op_used
        adc     t0
        sta     t2
        lda     op_used+1
        adc     t1
        sta     t3
        ; <= MAXOPENINGS ?
        lda     #<MAXOPENINGS
        cmp     t2
        lda     #>MAXOPENINGS
        sbc     t3
        jcc     @textured               ; overflow: no masked middle
        lda     #1
        sta     masked
        clc
        lda     op_used
        adc     #<OPENINGS
        sta     ds_rec+DS_MTC
        lda     op_used+1
        adc     #>OPENINGS
        sta     ds_rec+DS_MTC+1
        lda     t2
        sta     op_used
        lda     t3
        sta     op_used+1
        ; for the masked phase: the texture, texturemid = ((DONTPEGBOTTOM ?
        ; max(floors) + height : min(ceilings)) + yoffset) << 4 - vz
        lda     sidebuf+SIDEDEF_MIDTEXTURE
        ldx     sidebuf+SIDEDEF_MIDTEXTURE+1
        jsr     tex_trans
        sta     ds_rec+DS_TEX
        stx     ds_rec+DS_TEX+1
        lda     sw_flags
        and     #ML_DONTPEGBOTTOM
        beq     @mceil
        lda     ds_rec+DS_TEX
        ldx     ds_rec+DS_TEX+1
        jsr     tex_get
        lda     fs_floor                ; the higher floor
        cmp     bs_floor
        lda     fs_floor+1
        sbc     bs_floor+1
        bvc     :+
        eor     #$80
:       bmi     :+
        lda     fs_floor
        ldx     fs_floor+1
        bra     :++
:       lda     bs_floor
        ldx     bs_floor+1
:       clc
        adc     tc_hlo,y
        sta     t2
        txa
        adc     tc_hhi,y
        bra     @mmid
@mceil: lda     bs_ceil                 ; the lower ceiling
        cmp     fs_ceil
        lda     bs_ceil+1
        sbc     fs_ceil+1
        bvc     :+
        eor     #$80
:       bmi     :+
        lda     fs_ceil
        sta     t2
        lda     fs_ceil+1
        bra     @mmid
:       lda     bs_ceil
        sta     t2
        lda     bs_ceil+1
@mmid:  tax
        clc
        lda     t2
        adc     sidebuf+SIDEDEF_YOFFSET
        pha
        txa
        adc     sidebuf+SIDEDEF_YOFFSET+1
        tax
        pla
        jsr     world_tm
        lda     sw_tm
        sta     ds_rec+DS_TMID
        lda     sw_tm+1
        sta     ds_rec+DS_TMID+1
        lda     sw_tm+2
        sta     ds_rec+DS_TMID+2

        ; ---- segtextured: rw_offset, rw_centerangle, the wall's light
@textured:
        lda     tex_on
        ora     tex_on+1
        ora     tex_on+2
        ora     masked
        sta     textured
        bne     :+
        jmp     @nolight
:       lda     sc_offok                ; this seg's offset, angle, light: known?
        beq     :+
        jmp     @nolight
:       inc     sc_offok
        ; rw_offset = ((eye - v1) . (cos, sin)(seg angle)) >> 14 + (xoffset + offset) << 4
        lda     v1x
        ldx     v1x+1
        jsr     shl4
        sec
        lda     vx
        sbc     t4
        sta     m_a
        lda     vx+1
        sbc     t5
        sta     m_a+1
        lda     vx+2
        sbc     t6
        sta     m_a+2
        lda     sg_sinna                ; cos_bam(seg angle) = sin_bam(na)
        sta     s_val
        lda     sg_sinna+1
        sta     s_val+1
        jsr     mul_24_sval
        jsr     acc_save
        lda     v1y
        ldx     v1y+1
        jsr     shl4
        sec
        lda     vy
        sbc     t4
        sta     m_a
        lda     vy+1
        sbc     t5
        sta     m_a+1
        lda     vy+2
        sbc     t6
        sta     m_a+2
        lda     segbuf+SEG_ANGLE
        sta     s_ang
        lda     segbuf+SEG_ANGLE+1
        sta     s_ang+1
        jsr     sin_bam
        jsr     mul_24_sval
        jsr     acc_add_shr14
        clc
        lda     sidebuf+SIDEDEF_XOFFSET
        adc     segbuf+SEG_OFFSET
        pha
        lda     sidebuf+SIDEDEF_XOFFSET+1
        adc     segbuf+SEG_OFFSET+1
        tax
        pla
        pha
        jsr     shl4                    ; (17-bit sum: its low 16 bits suffice, only
        pla                             ;  rw_offset's low 13 bits are ever used)
        clc
        lda     t0
        adc     t4
        sta     rw_offset
        lda     t1
        adc     t5
        sta     rw_offset+1
        lda     t2
        adc     t6
        sta     rw_offset+2
        ; rw_centerangle = ANG90 + va - rw_normalangle
        sec
        lda     va
        sbc     rw_normal
        sta     rw_center
        lda     va+1
        sbc     rw_normal+1
        clc
        adc     #>ANG90
        sta     rw_center+1
        ; walllights: (light >> 4) + extralight, -1 horizontal, +1 vertical
        lda     fs_light
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     r_extralight
        tay
        lda     v1y
        cmp     v2y
        bne     @vert
        lda     v1y+1
        cmp     v2y+1
        bne     @vert
        dey
        bra     @lclamp
@vert:  lda     v1x
        cmp     v2x
        bne     @lclamp
        lda     v1x+1
        cmp     v2x+1
        bne     @lclamp
        iny
@lclamp:
        sty     sw_lnum
        tya
        jsr     light_row
        sta     walllights
        stx     walllights+1
        sta     ct_wl+1                 ; column_tex's walllights row
        stx     ct_wl+2
@nolight:
        ; the planes seen from the eye's side only
        lda     fs_floor
        ldx     fs_floor+1
        jsr     shl4
        sec
        lda     t4
        sbc     vz
        lda     t5
        sbc     vz+1
        lda     t6
        sbc     vz+2
        bmi     :+
        stz     markfloor               ; floor >= eye
:       lda     fs_cpic
        cmp     #<DD_SKYFLAT
        bne     :+
        lda     fs_cpic+1
        cmp     #>DD_SKYFLAT
        beq     @fracs
:       lda     fs_ceil
        ldx     fs_ceil+1
        jsr     shl4
        sec
        lda     vz
        sbc     t4
        lda     vz+1
        sbc     t5
        lda     vz+2
        sbc     t6
        bmi     @fracs
        stz     markceil                ; ceiling <= eye
@fracs: ; topfrac/topstep from worldtop, bottomfrac/bottomstep from worldbottom
        ldx     #worldtop - worldtop
        jsr     hfrac
        ldx     #3
:       lda     t0,x
        sta     topfrac,x
        lda     hf_step,x               ; (hfrac: the frac in t0..t3, the step in hf_step)
        sta     topstep,x
        dex
        bpl     :-
        ldx     #worldbot - worldtop
        jsr     hfrac
        ldx     #3
:       lda     t0,x
        sta     botfrac,x
        lda     hf_step,x
        sta     botstep,x
        dex
        bpl     :-
        lda     tex_on+1
        beq     @nohigh
        ldx     #worldhigh - worldtop
        jsr     hfrac
        ldx     #3
:       lda     t0,x
        sta     pixhigh,x
        lda     hf_step,x
        sta     pixhighstep,x
        dex
        bpl     :-
@nohigh:
        lda     tex_on+2
        beq     @nolow
        ldx     #worldlow - worldtop
        jsr     hfrac
        ldx     #3
:       lda     t0,x
        sta     pixlow,x
        lda     hf_step,x
        sta     pixlowstep,x
        dex
        bpl     :-
@nolow: jsr     seg_bias
        ; the planes
        lda     sw_start
        sta     pl_start
        lda     sw_stop
        sta     pl_stop
        stz     pf_n
        lda     markceil
        beq     @cp2
        lda     ceilplane
        jsr     check_plane
        sta     ceilplane
        ; the floor in the same plane that the ceiling check just grew: free
        ; over the range by that check (its fills are still pending)
        cmp     floorplane
        bne     @cp2
        cmp     #PL_OVERFLOW
        bcc     @cpok
@cp2:   lda     markfloor
        beq     @cpok
        lda     floorplane
        jsr     check_plane
        sta     floorplane
@cpok:  jsr     fill_setup
        jsr     seg_loop
        jsr     ds_prepare
        ; the range's one RENDER_BANK session: fills, marks, drawseg
        jsr     rb_write_on
        jsr     pf_write
        jsr     plane_store
        jsr     ds_write
        jsr     rb_write_off
        jmp     q_flush

; ---------------------------------------------------------------------------
; segs_frame: no seg's values are known yet this frame
segs_frame:
        lda     #$FF
        sta     sc_seg
        sta     sc_seg+1
        rts

; sfa_init: sinea_* = sin_bam(ANG90 + xtoviewangle[x]), x = 0..160
sfa_init:
        ldx     #0
:       lda     xtoviewangle_lo,x
        sta     s_ang
        clc
        lda     xtoviewangle_hi,x
        adc     #>ANG90
        sta     s_ang+1
        phx
        jsr     sin_bam
        plx
        lda     s_val
        sta     sinea_lo,x
        lda     s_val+1
        sta     sinea_hi,x
        inx
        cpx     #VIEW_W + 1
        bne     :-
        rts
.export segs_frame, sfa_init

; ---------------------------------------------------------------------------
; helpers of the setup

; world: A/X = height (map units), Y = offset from worldtop -> (h << 4) - vz there
world:
        phy
        jsr     shl4
        ply
        sec
        lda     t4
        sbc     vz
        sta     worldtop,y
        lda     t5
        sbc     vz+1
        sta     worldtop+1,y
        lda     t6
        sbc     vz+2
        sta     worldtop+2,y
        rts

; world_tm: A/X = height -> sw_tm = (h << 4) - vz
world_tm:
        jsr     shl4
        sec
        lda     t4
        sbc     vz
        sta     sw_tm
        lda     t5
        sbc     vz+1
        sta     sw_tm+1
        lda     t6
        sbc     vz+2
        sta     sw_tm+2
        rts

; cmp_world: C clear if world[X] < world[Y] (offsets from worldtop), signed
cmp_world:
        sec
        lda     worldtop,x
        sbc     worldtop,y
        lda     worldtop+1,x
        sbc     worldtop+1,y
        lda     worldtop+2,x
        sbc     worldtop+2,y
        bvc     :+
        eor     #$80
:       asl     a                       ; C = the sign: set if X < Y
        bcs     :+
        sec
        rts
:       clc
        rts

; tm_set: Y = slot, sw_tm = its texturemid -> += rowoffset, << 11 bytes 1, 2
tm_set:
        phy
        lda     sidebuf+SIDEDEF_YOFFSET
        ldx     sidebuf+SIDEDEF_YOFFSET+1
        jsr     shl4
        ply
        clc
        lda     sw_tm
        adc     t4
        sta     t0
        lda     sw_tm+1
        adc     t5
        sta     t1
        ; << 3: bytes 1 and 2 of << 11
        asl     t0
        rol     t1
        asl     t0
        rol     t1
        asl     t0
        rol     t1
        lda     t0
        sta     wt_tm1,y
        lda     t1
        sta     wt_tm2,y
        rts

; slot_setup: A/X = texture (translated), Y = slot -> the slot's record;
; texture 0 leaves the slot off
slot_setup:
        sta     t0
        ora     #0
        stx     t1
        ora     t1
        bne     :+
        lda     #0
        sta     tex_on,y
        rts
:       phy
        lda     t0
        ldx     t1
        jsr     tex_get
        tya
        tax
        ply
        lda     #1
        sta     tex_on,y
        lda     tc_bank,x
        sta     wt_bank,y
        lda     tc_alo,x
        sta     wt_alo,y
        lda     tc_ahi,x
        sta     wt_ahi,y
        lda     tc_wmask,x
        sta     wt_wmask,y
        lda     tc_hmask,x
        sta     wt_hmask,y
        lda     tc_log2h,x
        sta     wt_log2h,y
        rts

bsil_max:
        lda     #$FF
        sta     ds_rec+DS_BSIL
        lda     #$7F
        sta     ds_rec+DS_BSIL+1
        rts
tsil_min:
        stz     ds_rec+DS_TSIL
        lda     #$80
        sta     ds_rec+DS_TSIL+1
        rts

; light_row: A = light level (signed, clamped to 0..15) -> A/X = scalelight row
light_row:
        cmp     #$80
        bcc     :+
        lda     #0
:       cmp     #LIGHTLEVELS
        bcc     :+
        lda     #LIGHTLEVELS - 1
:       ; * 48 = * 32 + * 16
        sta     t4
        stz     t5
        asl     t4
        asl     t4
        asl     t4
        asl     t4                      ; * 16 (<= 240)
        lda     t4
        asl     a
        rol     t5                      ; * 32
        clc
        adc     t4
        sta     t4
        lda     t5
        adc     #0
        sta     t5
        clc
        lda     t4
        adc     #<scalelight
        pha
        lda     t5
        adc     #>scalelight
        tax
        pla
        rts

; mul_24_sval: m_r = m_a (s24) * s_val (s16), 5 bytes
mul_24_sval:
        lda     s_val
        sta     m_b
        lda     s_val+1
        sta     m_b+1
        jmp     muls_3_2_5

; acc_save: sfa_den (5 bytes) = m_r
acc_save:
        ldx     #4
:       lda     m_r,x
        sta     sfa_den,x
        dex
        bpl     :-
        rts

; acc_add_shr14: t0..t2 = (sfa_den + m_r) >> 14 (arithmetic; 40-bit sum)
acc_add_shr14:
        clc
        ldx     #0
:       lda     sfa_den,x
        adc     m_r,x
        sta     m_r,x
        inx
        txa
        eor     #5
        bne     :-
        ; >> 14 = bytes 1.. << 2 >> 8: take m_r+1..4, shift left 2, drop the low byte
        ldx     #2
:       asl     m_r+1
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        dex
        bne     :-
        lda     m_r+2
        sta     t0
        lda     m_r+3
        sta     t1
        lda     m_r+4
        sta     t2
        rts

; ---------------------------------------------------------------------------
; sfa: X = column -> sfa_num (3 bytes) = R_ScaleFromGlobalAngle(va + xtoviewangle[x])
sfa:
        ; sin(anglea), anglea = ANG90 + visangle - va = ANG90 + xtoviewangle[x]:
        ; per column, from the table (sfa_init)
        lda     sinea_lo,x
        sta     sfa_a
        lda     sinea_hi,x
        sta     sfa_a+1
        ; angleb = ANG90 + va + xtoviewangle[x] - rw_normalangle
        clc
        lda     va
        adc     xtoviewangle_lo,x
        sta     t0
        lda     va+1
        adc     xtoviewangle_hi,x
        sta     t1
        sec
        lda     t0
        sbc     rw_normal
        sta     s_ang
        lda     t1
        sbc     rw_normal+1
        clc
        adc     #>ANG90
        sta     s_ang+1
        jsr     sin_bam
        ; the reference's order: den = rw_distance * sinea >> 14 <= 0 gives
        ; SCALE_MAX, then num = 80 * sineb <= 0 gives SCALE_MIN. sinea (the
        ; cosine of a column's angle, |angle| <= 45 degrees) is > 11585, so
        ; den <= 0 exactly when rw_distance < 2 (it was made positive or
        ; negative by the eye's side: sg_dsign)
        lda     sg_dsign
        jne     @max
        lda     sg_dm+2
        ora     sg_dm+1
        bne     :+
        lda     sg_dm
        cmp     #2
        jcc     @max
:       lda     s_val+1
        jmi     @min
        ora     s_val
        jeq     @min
        ; den = (|rw_distance| * sinea) >> 14
        lda     sg_dm
        sta     m_a
        lda     sg_dm+1
        sta     m_a+1
        lda     sg_dm+2
        sta     m_a+2
        lda     sfa_a
        sta     m_b
        lda     sfa_a+1
        sta     m_b+1
        jsr     mulu_3_2_5
        ; >> 14: (m_r+1..4) << 2, drop a byte -> den = m_r+2..4
        lda     m_r+1
        asl     a
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        asl     a
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        ; num = 80 * sineb (0 < sineb <= 16384): 16 s + 64 s
        ldx     s_val
        ldy     s_val+1
        lda     shl4tab,x
        sta     t0
        lda     shl4tab,y
        ora     shr4tab,x
        sta     t1
        lda     shr4tab,y
        sta     t2                      ; 16 s
        lda     t0
        asl     a
        sta     t3
        lda     t1
        rol     a
        sta     t4
        lda     t2
        rol     a
        sta     t5
        asl     t3
        rol     t4
        rol     t5                      ; 64 s
        clc
        lda     t0
        adc     t3
        sta     sfa_num
        lda     t1
        adc     t4
        sta     sfa_num+1
        lda     t2
        adc     t5
        sta     sfa_num+2
        ; num >= den << 16 (only possible when den < 32): SCALE_MAX
        lda     m_r+4
        ora     m_r+3
        bne     @div
        lda     m_r+2
        cmp     #32
        bcs     @div
        ; num >= den * 65536 <=> num >> 16 >= den (num < 2^21)
        lda     sfa_num+2
        cmp     m_r+2
        bcs     @max
@div:   ; (num << 6) / den
        lda     sfa_num
        sta     d_n
        lda     sfa_num+1
        sta     d_n+1
        lda     sfa_num+2
        sta     d_n+2
        lda     m_r+2
        sta     d_d
        lda     m_r+3
        sta     d_d+1
        lda     m_r+4
        sta     d_d+2
        jsr     div_scale
        ; max(SCALE_MIN, q)
        lda     d_n+2
        ora     d_n+1
        beq     @min
        lda     d_n
        sta     sfa_num
        lda     d_n+1
        sta     sfa_num+1
        lda     d_n+2
        sta     sfa_num+2
        rts
@max:   stz     sfa_num
        stz     sfa_num+1
        lda     #>(SCALE_MAX >> 8)
        sta     sfa_num+2
        rts
@min:   stz     sfa_num
        lda     #1
        sta     sfa_num+1
        stz     sfa_num+2
        rts

; hfrac: X = offset of a height h from worldtop ->
;   t0..t3 = (CENTERY << 12) - ((h * rw_scale) >> 8)   (32-bit wrap)
;   hf_step = -((rw_step * h) >> 8)
; with unsigned products of the magnitudes: for a negative product P,
; P >> 8 (floor) is -((|P| + 255) >> 8)
hfrac:
        stz     hf_sign
        lda     worldtop+2,x
        bpl     :+
        lda     #$80
        sta     hf_sign
        sec
        lda     #0
        sbc     worldtop,x
        sta     m_a
        lda     #0
        sbc     worldtop+1,x
        sta     m_a+1
        lda     #0
        sbc     worldtop+2,x
        sta     m_a+2
        bra     :++
:       lda     worldtop,x
        sta     m_a
        lda     worldtop+1,x
        sta     m_a+1
        lda     worldtop+2,x
        sta     m_a+2
:       ; the step: |h| * |rw_step|
        lda     sg_stepm
        sta     m_b
        lda     sg_stepm+1
        sta     m_b+1
        lda     sg_stepm+2
        sta     m_b+2
        jsr     mulu_3_3_5
        lda     hf_sign
        eor     sg_steps
        bmi     @sneg
        ; (rw_step * h) >= 0: step = -(P >> 8)
        sec
        lda     #0
        sbc     m_r+1
        sta     hf_step
        lda     #0
        sbc     m_r+2
        sta     hf_step+1
        lda     #0
        sbc     m_r+3
        sta     hf_step+2
        lda     #0
        sbc     m_r+4
        sta     hf_step+3
        bra     @frac
@sneg:  ; < 0: step = (|P| + 255) >> 8
        lda     m_r
        cmp     #1                      ; C set when the low byte is not 0
        lda     m_r+1
        adc     #0
        sta     hf_step
        lda     m_r+2
        adc     #0
        sta     hf_step+1
        lda     m_r+3
        adc     #0
        sta     hf_step+2
        lda     m_r+4
        adc     #0
        sta     hf_step+3
@frac:  ; |h| * rw_scale
        lda     rw_scale
        sta     m_b
        lda     rw_scale+1
        sta     m_b+1
        lda     rw_scale+2
        sta     m_b+2
        jsr     mulu_3_3_5
        bit     hf_sign
        bmi     @fneg
        ; h >= 0: (42 << 12) - (P >> 8)
        sec
        lda     #<(CENTERY << HEIGHTBITS)
        sbc     m_r+1
        sta     t0
        lda     #>(CENTERY << HEIGHTBITS)
        sbc     m_r+2
        sta     t1
        lda     #^(CENTERY << HEIGHTBITS)
        sbc     m_r+3
        sta     t2
        lda     #0
        sbc     m_r+4
        sta     t3
        rts
@fneg:  ; h < 0: (42 << 12) + ((|P| + 255) >> 8)
        lda     m_r
        cmp     #1
        lda     m_r+1
        adc     #<(CENTERY << HEIGHTBITS)
        sta     t0
        lda     m_r+2
        adc     #>(CENTERY << HEIGHTBITS)
        sta     t1
        lda     m_r+3
        adc     #^(CENTERY << HEIGHTBITS)
        sta     t2
        lda     m_r+4
        adc     #0
        sta     t3
        rts

; fill_setup: for the planes that have no visplane, what their pieces draw
fill_setup:
        lda     fs_light
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     r_extralight
        jsr     light_row
        sta     filllights
        stx     filllights+1
        lda     markceil
        beq     :+
        lda     ceilplane
        cmp     #PL_OVERFLOW
        bne     :+
        lda     ceilpic_t
        ldx     ceilpic_t+1
        ldy     #0
        jsr     @one
:       lda     markfloor
        beq     :+
        lda     floorplane
        cmp     #PL_OVERFLOW
        bne     :+
        lda     floorpic_t
        ldx     floorpic_t+1
        ldy     #3
        jsr     @one
:       rts
@one:   ; A/X = flat, Y = 0 (ceiling) / 3 (floor): sky flag, bank, colour
        cmp     #<DD_SKYFLAT
        bne     :+
        cpx     #>DD_SKYFLAT
        bne     :+
        lda     #1
        sta     fill_c,y
        rts
:       phy
        jsr     flat_fetch
        ply
        lda     #0
        sta     fill_c,y
        lda     flatbuf+FLAT_BANK
        sta     fill_c+1,y
        lda     flatbuf+FLAT_COLOR
        sta     fill_c+2,y
        rts

; ---------------------------------------------------------------------------
; The seg loop's accumulators are kept biased: topfrac + $40FFF, bottomfrac
; + $40000, pixhigh + $40000, pixlow + $40FFF (seg_bias), so a row, ceil or
; floor as the reference takes it, + ROWBIAS, is bits 12..19 of the sum, or
; saturated (ROWB). The sums wrap at 32 bits like the reference's s32
; accumulators; a value the bias carried past 2^31 is recognised (the
; unsigned sum is then below $80000000 + bias) and saturates high.
.macro ROWB acc, bhi, bmid, blo
        .local neg, hi, lo, done
        lda     acc+3
        bmi     neg
        bne     hi
        ldx     acc+2
        cpx     #$10
        bcs     hi
        lda     shl4tab,x
        ldx     acc+1
        ora     shr4tab,x
        bra     done
neg:    cmp     #$80
        bne     lo
        lda     acc+2
        cmp     #bhi
        bcc     hi
        bne     lo
        lda     acc+1
        cmp     #bmid
        bcc     hi
        bne     lo
        lda     acc
        cmp     #blo
        bcc     hi
lo:     lda     #0
        bra     done
hi:     lda     #$FF
done:
.endmacro

.macro ADD32 dst, src
        clc
        lda     dst
        adc     src
        sta     dst
        lda     dst+1
        adc     src+1
        sta     dst+1
        lda     dst+2
        adc     src+2
        sta     dst+2
        lda     dst+3
        adc     src+3
        sta     dst+3
.endmacro

; seg_bias: the accumulators get their biases; the per-range constants of
; column_tex (|rw_distance| and its sign, (rw_offset << 12) + 4095) and of
; piece (8 - log2h per slot)
seg_bias:
        clc
        lda     topfrac
        adc     #$FF
        sta     topfrac
        lda     topfrac+1
        adc     #$0F
        sta     topfrac+1
        lda     topfrac+2
        adc     #$04
        sta     topfrac+2
        lda     topfrac+3
        adc     #0
        sta     topfrac+3
        clc
        lda     botfrac+2
        adc     #$04
        sta     botfrac+2
        lda     botfrac+3
        adc     #0
        sta     botfrac+3
        clc
        lda     pixhigh+2
        adc     #$04
        sta     pixhigh+2
        lda     pixhigh+3
        adc     #0
        sta     pixhigh+3
        clc
        lda     pixlow
        adc     #$FF
        sta     pixlow
        lda     pixlow+1
        adc     #$0F
        sta     pixlow+1
        lda     pixlow+2
        adc     #$04
        sta     pixlow+2
        lda     pixlow+3
        adc     #0
        sta     pixlow+3
        ; RO = (rw_offset << 12) + 4095, low 32 bits: bytes $FF, (off0 << 4) | $0F,
        ; off0 >> 4 | off1 << 4, off1 >> 4 | off2 << 4
        lda     #$FF
        sta     sg_ro
        ldx     rw_offset
        lda     shl4tab,x
        ora     #$0F
        sta     sg_ro+1
        ldy     rw_offset+1
        lda     shl4tab,y
        ora     shr4tab,x
        sta     sg_ro+2
        ldx     rw_offset+2
        lda     shl4tab,x
        ora     shr4tab,y
        sta     sg_ro+3
        ; 8 - log2h per slot
        ldx     #2
:       lda     #8
        sec
        sbc     wt_log2h,x
        sta     wt_sh,x
        dex
        bpl     :-
        rts

; ---------------------------------------------------------------------------
; seg_loop: R_RenderSegLoop over sw_start..sw_stop
seg_loop:
        lda     sw_start
        sta     rx
sl_col:   ; yl = max(ceil(topfrac), ceilingclip + 1)
        ROWB    topfrac, $04, $0F, $FF
        ldx     rx
        ldy     cclip,x
        iny
        sty     sg_ctop                 ; ceilingclip + 1
        cmp     sg_ctop
        bcs     :+
        tya
:       sta     ryl
        ; yh = min(floor(bottomfrac), floorclip - 1)
        ROWB    botfrac, $04, $00, $00
        ldx     rx
        cmp     fclip,x
        bcc     :+
        lda     fclip,x
        dec     a
:       sta     ryh
        ; ---- the ceiling mark: rows ceilingclip + 1 .. min(yl, floorclip) - 1
        ; (and not below yh when the floor is marked too)
        lda     markceil
        beq     sl_fmark
        lda     fclip,x
        cmp     ryl
        bcc     :+
        lda     ryl
:       dec     a
        ldy     markfloor
        beq     :+
        cmp     ryh
        bcc     :+
        lda     ryh
:       cmp     sg_ctop
        bcc     sl_cnone
        ldy     ceilplane
        bmi     sl_cnow
        sec
        sbc     #ROWBIAS
        sta     cb,x
        lda     sg_ctop
        sbc     #ROWBIAS
        sta     ct,x
        bra     sl_fmark
sl_cnow:  sta     t2
        lda     sg_ctop
        sta     t3
        lda     #0
        jsr     mark_now
        ldx     rx
        bra     sl_fmark
sl_cnone: lda     #$FF
        sta     ct,x
        ; ---- the floor mark: rows max(yh + 1, ceilingclip + 1) .. floorclip - 1
sl_fmark: lda     markfloor
        beq     sl_pieces
        lda     ryh
        inc     a
        cmp     sg_ctop
        bcs     :+
        lda     sg_ctop
:       sta     t3
        lda     fclip,x
        dec     a
        cmp     t3
        bcc     sl_fnone
        ldy     floorplane
        bmi     sl_fnow
        sec
        sbc     #ROWBIAS
        sta     fb,x
        lda     t3
        sbc     #ROWBIAS
        sta     ft,x
        bra     sl_pieces
sl_fnow:  sta     t2
        lda     #3
        jsr     mark_now
        ldx     rx
        bra     sl_pieces
sl_fnone: lda     #$FF
        sta     ft,x
sl_pieces:
        stz     sg_have                 ; the texture column is computed on demand
        lda     masked
        beq     :+
        jsr     column_tex              ; a masked middle wants every column's
        ldx     rx
:       lda     tex_on
        beq     sl_nomid
        ; the middle texture: the whole column, then closed
        lda     ryh
        cmp     ryl
        bcc     :+
        lda     ryl
        ldy     ryh
        ldx     #0
        jsr     piece
        ldx     rx
:       lda     #ROWBIAS + VIEW_H
        sta     cclip,x
        lda     #ROWBIAS - 1
        sta     fclip,x
        jmp     sl_next
sl_nomid: lda     tex_on+1
        beq     sl_notop
        ; the upper texture: yl .. min(floor(pixhigh), floorclip - 1)
        ROWB    pixhigh, $04, $00, $00
        ldx     rx
        cmp     fclip,x
        bcc     :+
        lda     fclip,x
        dec     a
:       sta     sg_mid
        ADD32   pixhigh, pixhighstep
        lda     sg_mid
        cmp     ryl
        bcc     sl_topno
        lda     ryl
        ldy     sg_mid
        ldx     #1
        jsr     piece
        ldx     rx
        lda     sg_mid
        sta     cclip,x
        bra     sl_bot
sl_topno: ldx     rx
        lda     ryl
        dec     a
        sta     cclip,x
        bra     sl_bot
sl_notop: lda     markceil
        beq     sl_bot
        lda     ryl
        dec     a
        sta     cclip,x
sl_bot:   lda     tex_on+2
        jeq     sl_nobot
        ; the lower texture: max(ceil(pixlow), ceilingclip + 1) .. yh
        ROWB    pixlow, $04, $0F, $FF
        ldx     rx
        cmp     cclip,x
        beq     :+
        bcs     :++
:       lda     cclip,x
        inc     a
:       sta     sg_mid
        ADD32   pixlow, pixlowstep
        lda     ryh
        cmp     sg_mid
        bcc     sl_botno
        lda     sg_mid
        ldy     ryh
        ldx     #2
        jsr     piece
        ldx     rx
        lda     sg_mid
        sta     fclip,x
        bra     sl_mtc
sl_botno: ldx     rx
        lda     ryh
        inc     a
        sta     fclip,x
        bra     sl_mtc
sl_nobot: lda     markfloor
        beq     sl_mtc
        lda     ryh
        inc     a
        sta     fclip,x
sl_mtc:   lda     masked
        beq     sl_next
        lda     sg_texcol
        sta     mtcbuf,x
sl_next:  ; rw_scale += step, topfrac += topstep, bottomfrac += bottomstep
        clc
        lda     rw_scale
        adc     rw_step
        sta     rw_scale
        lda     rw_scale+1
        adc     rw_step+1
        sta     rw_scale+1
        lda     rw_scale+2
        adc     rw_step+2
        sta     rw_scale+2
        ADD32   topfrac, topstep
        ADD32   botfrac, botstep
        lda     rx
        cmp     sw_stop
        beq     :+
        inc     rx
        jmp     sl_col
:       rts

; mark_now: column rx, rows t3..t2 (biased, t3 <= t2) of a plane that has
; no visplane; A = 0 ceiling, 3 floor (fill_c / fill_f): drawn at once
mark_now:
        tay
        ldx     rx
        cmp     #0
        bne     :+
        lda     #$FF
        sta     ct,x
        bra     :++
:       lda     #$FF
        sta     ft,x
:       lda     fill_c,y
        beq     @fill
        ; the sky
        lda     t3
        sec
        sbc     #ROWBIAS
        pha
        lda     t2
        sec
        sbc     #ROWBIAS
        tay
        pla
        ldx     rx
        jmp     sky_piece
@fill:  lda     fill_c+1,y
        sta     q_in_bank
        lda     fill_c+2,y
        sta     q_in_f
        ; the colormap: fixed, or scalelight[plane light][min(scale >> 11, 47)]
        lda     r_fixedcm
        cmp     #$FF
        bne     :+
        jsr     scale_index
        tay
        lda     filllights
        sta     p1
        lda     filllights+1
        sta     p1+1
        lda     (p1),y
:       clc
        adc     #>DD_COLORMAPS
        sta     q_in_cm
        ldx     rx
        lda     t3
        sec
        sbc     #ROWBIAS
        clc
        adc     coladdr_lo,x
        sta     q_in_dst
        lda     coladdr_hi,x
        adc     #0
        sta     q_in_dst+1
        lda     t2
        sec
        sbc     t3
        inc     a
        sta     q_in_cnt
        jmp     q_fill

; scale_index: A = min(rw_scale >> 11, 47)
scale_index:
        lda     rw_scale+2
        cmp     #2
        bcs     @max                    ; >= 2^17: >> 11 >= 64
        lsr     a                       ; bit 16 into C
        lda     rw_scale+1
        ror     a
        lsr     a
        lsr     a                       ; bits 11..16
        cmp     #MAXLIGHTSCALE
        bcc     :+
@max:   lda     #MAXLIGHTSCALE - 1
:       rts

; ---------------------------------------------------------------------------
; column_tex: the texture column (& 255), colormap page and iscale of column
; rx. The texture column is (rw_offset - (tan(a) * rw_distance >> 12)) >> 5,
; taken as ((rw_offset << 12) + 4095 - tan * rw_distance) >> 17: the same
; floor, one subtraction (the 4095 makes up for the inner floor); only
; the product's low 25 bits matter.
column_tex:
        lda     #1
        sta     sg_have
        ; a = (rw_centerangle + xtoviewangle[x]) >> 4, clamped to 0..2047
        ldx     rx
        clc
        lda     rw_center
        adc     xtoviewangle_lo,x
        tay
        lda     rw_center+1
        adc     xtoviewangle_hi,x
        tax
        lda     shr4tab,x               ; fine index, high part
        cmp     #8
        jcs     ct_clamp
        sta     t1
        lda     shl4tab,x
        ora     shr4tab,y
        tay                             ; fine index, low byte
        lda     t1
ct_tan:   ; >= 1024: tan_pos[a - 1024]; else -tan_pos[1023 - a]
        cmp     #4
        bcs     ct_pos
        eor     #3
        sta     t1
        tya
        eor     #$FF
        tay
        lda     #$80
        bra     ct_look
ct_pos:   sbc     #4
        sta     t1
        lda     #0
ct_look:  eor     sg_dsign                ; the product's sign
        sta     sg_psign
        lda     t1                      ; the three planes are 1024 bytes apart
        clc
        adc     #>finetangent_lo
        sta     ct_t0+2
        adc     #4
        sta     ct_t1+2
        adc     #4
        sta     ct_t2+2
ct_t0:    lda     finetangent_lo & $FF,y
        sta     m_a
ct_t1:    lda     finetangent_mid & $FF,y
        sta     m_a+1
ct_t2:    lda     finetangent_hi & $FF,y
        sta     m_a+2
        jsr     mul_tan                 ; m_r = |tan| * |rw_distance|, 4 bytes
        ; V = RO -+ P; texcol = V >> 17
        bit     sg_psign
        bmi     ct_plus
        sec
        lda     sg_ro
        sbc     m_r
        lda     sg_ro+1
        sbc     m_r+1
        lda     sg_ro+2
        sbc     m_r+2
        tax
        lda     sg_ro+3
        sbc     m_r+3
        bra     ct_col
ct_plus:  clc
        lda     sg_ro
        adc     m_r
        lda     sg_ro+1
        adc     m_r+1
        lda     sg_ro+2
        adc     m_r+2
        tax
        lda     sg_ro+3
        adc     m_r+3
ct_col:   lsr     a
        txa
        ror     a
        sta     sg_texcol
        ; the colormap: fixed, or walllights[min(scale >> 11, 47)]
        lda     r_fixedcm
        cmp     #$FF
        bne     ct_fixed
        lda     rw_scale+2
        cmp     #2
        bcs     ct_lmax                   ; >= 2^17: >> 11 >= 64
        lsr     a                       ; bit 16 into C
        lda     rw_scale+1
        ror     a
        lsr     a
        lsr     a                       ; bits 11..16
        cmp     #MAXLIGHTSCALE
        bcc     :+
ct_lmax:  lda     #MAXLIGHTSCALE - 1
:       tay
ct_wl:                                  ; (patched per seg)
        lda     scalelight,y            ; (the seg's walllights row: patched)
ct_fixed: clc
        adc     #>DD_COLORMAPS
        sta     sg_cm
        ; iscale = recip[mantissa] >> n, n = bitlen(scale) - 9
        ldx     rw_scale+2
        beq     ct_small
        ; bitlen(scale) = 16 + bitlen(hi): mantissa = (hi:mid) >> (bitlen(hi) - 1),
        ; iscale = (recip >> 8) >> (bitlen(hi) - 1)
        ldy     bitlen,x
        dey
        lda     rw_scale+1
        stx     t1
        cpy     #0
        beq     :++
:       lsr     t1
        ror     a
        dey
        bne     :-
:       tax
        lda     recip_mid,x
        sta     sg_isc
        lda     recip_hi,x
        sta     sg_isc+1
        stz     sg_isc+2
        ldx     rw_scale+2
        ldy     bitlen,x
        dey
        beq     ct_step
:       lsr     sg_isc+1
        ror     sg_isc
        dey
        bne     :-
        bra     ct_step
ct_small: ; bitlen(scale) = 8 + bitlen(mid): n = bitlen(mid) - 1. Shifting
        ; right n times or left 8 - n times and dropping a byte: at most 4
        ldx     rw_scale+1
        ldy     bitlen,x
        dey
        cpy     #5
        bcs     ct_left
        sty     t1                      ; n (0..4)
        lda     rw_scale
        cpy     #0
        beq     :++
        stx     t0
:       lsr     t0
        ror     a
        dey
        bne     :-
:       tax
        lda     recip_lo,x
        sta     sg_isc
        lda     recip_mid,x
        sta     sg_isc+1
        lda     recip_hi,x
        sta     sg_isc+2
        ldy     t1
        beq     ct_step
:       lsr     sg_isc+2
        ror     sg_isc+1
        ror     sg_isc
        dey
        bne     :-
        bra     ct_step
ct_left: ; n = 5..7: the mantissa is the high byte of (mid:lo) << (8 - n),
        ; iscale = (recip << (8 - n)) >> 8
        tya
        eor     #7                      ; 7 - n = 8 - n - 1
        tay
        iny                             ; 8 - n (1..3)
        sty     t1
        lda     rw_scale
        sta     t0
        txa
:       asl     t0
        rol     a
        dey
        bne     :-
        tax                             ; the mantissa's low byte
        lda     recip_lo,x
        sta     t0
        lda     recip_mid,x
        sta     sg_isc
        lda     recip_hi,x
        sta     sg_isc+1
        stz     sg_isc+2
        ldy     t1
:       asl     t0
        rol     sg_isc
        rol     sg_isc+1
        rol     sg_isc+2
        dey
        bne     :-
ct_step:  ; step = ((iscale + 128) >> 8) & $FFFF
        clc
        lda     sg_isc
        adc     #$80
        lda     sg_isc+1
        adc     #0
        sta     sg_step
        lda     sg_isc+2
        adc     #0
        sta     sg_step+1
        rts
ct_clamp: ; a >= 2048: 2047 below 3072, else 0
        cmp     #12
        bcs     :+
        ldy     #$FF
        lda     #7
        jmp     ct_tan
:       ldy     #0
        lda     #0
        jmp     ct_tan

; mul_tan: m_r (4 bytes) = the low 32 bits of m_a (3 bytes) * sg_dm (3 bytes)
mul_tan:
        MULUB   3, 3, 4, sg_dm
        rts

; ---------------------------------------------------------------------------
; piece: column rx, biased rows A..Y (A <= Y), slot X -> a queue entry
; (bank, view buffer address, count, texture column address, f, step,
; colormap, hmask) written straight into the queue
piece:
        sta     t2                      ; lo
        sty     t3                      ; hi
        stx     t7                      ; slot
        lda     sg_have
        bne     :+
        jsr     column_tex
        ldx     t7
:       ldy     q_count
        cpy     #QN
        bcc     :+
        jsr     q_flush
        ldx     t7
        ldy     #0
:       lda     wt_bank,x
        sta     q_bank,y
        lda     wt_hmask,x
        sta     q_hm,y
        lda     sg_cm
        sta     q_cm,y
        lda     sg_step
        sta     q_stl,y
        lda     sg_step+1
        sta     q_sth,y
        ; the texture column: addr + ((texcol & wmask) << log2h)
        lda     sg_texcol
        and     wt_wmask,x
        sta     t5
        lda     #0
        phy
        ldy     wt_sh,x
        beq     :++
:       lsr     t5
        ror     a
        dey
        bne     :-
:       ply
        clc
        adc     wt_alo,x
        sta     q_slo,y
        lda     t5
        adc     wt_ahi,x
        sta     q_shi,y
        ; the view buffer: column rx, row lo; the count
        ldx     rx
        lda     t2
        sec
        sbc     #ROWBIAS
        clc
        adc     coladdr_lo,x
        sta     q_dlo,y
        lda     coladdr_hi,x
        adc     #0
        sta     q_dhi,y
        lda     t3
        sec
        sbc     t2
        inc     a
        sta     q_cnt,y
        ; f = bytes 1, 2 of (texturemid << 11) + (yl - 42) * iscale
        lda     t2
        sec
        sbc     #ROWBIAS + CENTERY
        sta     t6                      ; yl - 42
        bpl     :+
        eor     #$FF
        inc     a
:       beq     @f0
        ; |yl - 42| * iscale, low 3 bytes
        sta     ms1
        sta     ms3
        eor     #$FF
        sta     ms2
        sta     ms4
        phy
        ldy     sg_isc
        sec
        lda     (ms1),y
        sbc     (ms2),y
        sta     t0
        lda     (ms3),y
        sbc     (ms4),y
        sta     t1
        ldy     sg_isc+1
        sec
        lda     (ms1),y
        sbc     (ms2),y
        tax
        lda     (ms3),y
        sbc     (ms4),y
        sta     t4
        txa
        clc
        adc     t1
        sta     t1
        lda     t4
        adc     #0
        sta     t4
        ldy     sg_isc+2
        sec
        lda     (ms1),y
        sbc     (ms2),y
        clc
        adc     t4
        sta     t4
        ply
        bit     t6
        bpl     :+
        sec
        lda     #0
        sbc     t0
        lda     #0
        sbc     t1
        sta     t1
        lda     #0
        sbc     t4
        sta     t4
:       ldx     t7
        clc
        lda     t1
        adc     wt_tm1,x
        sta     q_flo,y
        lda     t4
        adc     wt_tm2,x
        sta     q_fhi,y
        iny
        sty     q_count
        rts
@f0:    ldx     t7
        lda     wt_tm1,x
        sta     q_flo,y
        lda     wt_tm2,x
        sta     q_fhi,y
        iny
        sty     q_count
        rts

; ---------------------------------------------------------------------------
; plane_store: the range's marks into the visplanes (in the session: writes
; only RENDER_BANK and the zero page)
plane_store:
        lda     markceil
        beq     @floor
        lda     ceilplane
        cmp     #PL_OVERFLOW
        bcs     @floor
        tax
        jsr     @dest
        ldx     sw_start
        ldy     #0
:       lda     ct,x
        sta     (p0),y
        cmp     #$FF
        bne     :+
        lda     #0
        bra     :++
:       lda     cb,x
:       sta     (p1),y
        inx
        iny
        cpy     sw_n
        bne     :---
@floor: lda     markfloor
        beq     @done
        lda     floorplane
        cmp     #PL_OVERFLOW
        bcs     @done
        tax
        jsr     @dest
        ; the same plane as the ceiling: only the columns marked here
        lda     markceil
        beq     @all
        lda     floorplane
        cmp     ceilplane
        bne     @all
        ldx     sw_start
        ldy     #0
@some:  lda     ft,x
        cmp     #$FF
        beq     :+
        sta     (p0),y
        lda     fb,x
        sta     (p1),y
:       inx
        iny
        cpy     sw_n
        bne     @some
        rts
@all:   ldx     sw_start
        ldy     #0
:       lda     ft,x
        sta     (p0),y
        cmp     #$FF
        bne     :+
        lda     #0
        bra     :++
:       lda     fb,x
:       sta     (p1),y
        inx
        iny
        cpy     sw_n
        bne     :---
@done:  rts
; @dest: X = plane -> p0 = its top at column sw_start, p1 its bottom
@dest:  sec                             ; index start + 1
        lda     pl_alo,x
        adc     sw_start
        sta     p0
        lda     pl_ahi,x
        adc     #0
        sta     p0+1
        clc
        lda     p0
        adc     #<PL_COLS
        sta     p1
        lda     p0+1
        adc     #>PL_COLS
        sta     p1+1
        rts

; ---------------------------------------------------------------------------
; ds_prepare: the drawseg's openings and final fields (before the session:
; this writes main memory). The copies it leaves for ds_write: dsw_top /
; dsw_bot (the clip arrays' RENDER_BANK addresses, 0 none), dsw_mtc (the
; masked columns' address, 0 none), dsw_rec (the record's address, 0 none).
ds_prepare:
        stz     dsw_top+1
        stz     dsw_bot+1
        stz     dsw_mtc+1
        stz     dsw_rec+1
        lda     sw_record
        bne     :+
        rts
:       lda     sub_seg                 ; the seg (rmain.s: its index)
        sta     ds_rec+DS_SEG
        lda     sub_seg+1
        sta     ds_rec+DS_SEG+1
        ; sprtopclip: SIL_TOP or masked, not set yet -> the ceiling clip
        lda     ds_rec+DS_TOPCLIP
        ora     ds_rec+DS_TOPCLIP+1
        bne     @bot
        lda     ds_rec+DS_SIL
        and     #SIL_TOP
        ora     masked
        beq     @bot
        jsr     @alloc
        bcs     @ovf
        sta     ds_rec+DS_TOPCLIP
        stx     ds_rec+DS_TOPCLIP+1
        sta     dsw_top
        stx     dsw_top+1
@bot:   lda     ds_rec+DS_BOTCLIP
        ora     ds_rec+DS_BOTCLIP+1
        bne     @mask
        lda     ds_rec+DS_SIL
        and     #SIL_BOTTOM
        ora     masked
        beq     @mask
        jsr     @alloc
        bcs     @ovf
        sta     ds_rec+DS_BOTCLIP
        stx     ds_rec+DS_BOTCLIP+1
        sta     dsw_bot
        stx     dsw_bot+1
        bra     @mask
@ovf:   ; out of openings: this drawseg clips nothing (and copies nothing)
        stz     ds_rec+DS_SIL
        lda     #DS_NONE
        sta     ds_rec+DS_TOPCLIP
        sta     ds_rec+DS_TOPCLIP+1
        sta     ds_rec+DS_BOTCLIP
        sta     ds_rec+DS_BOTCLIP+1
        sta     ds_rec+DS_MTC
        sta     ds_rec+DS_MTC+1
        stz     dsw_top+1
        stz     dsw_bot+1
@mask:  ; a masked middle: both silhouettes
        lda     ds_rec+DS_MTC
        ora     ds_rec+DS_MTC+1
        beq     @rec
        lda     ds_rec+DS_MTC
        sta     dsw_mtc
        lda     ds_rec+DS_MTC+1
        sta     dsw_mtc+1
        lda     sw_lnum
        sta     ds_rec+DS_LIGHT
        lda     ds_rec+DS_SIL
        and     #SIL_TOP
        bne     :+
        lda     ds_rec+DS_SIL
        ora     #SIL_TOP
        sta     ds_rec+DS_SIL
        jsr     tsil_min
:       lda     ds_rec+DS_SIL
        and     #SIL_BOTTOM
        bne     @rec
        lda     ds_rec+DS_SIL
        ora     #SIL_BOTTOM
        sta     ds_rec+DS_SIL
        jsr     bsil_max
@rec:   ; the record at DS_BASE + 30 * n
        lda     ds_n
        jsr     ds_addr
        sta     dsw_rec
        stx     dsw_rec+1
        inc     ds_n
        rts

; @alloc: n = sw_n openings -> A/X = the address of column x1's byte; C set:
; none left (MAXOPENINGS)
@alloc: clc
        lda     op_used
        adc     sw_n
        sta     t0
        lda     op_used+1
        adc     #0
        sta     t1
        lda     #<MAXOPENINGS
        cmp     t0
        lda     #>MAXOPENINGS
        sbc     t1
        bcc     @full
        clc
        lda     op_used
        adc     #<OPENINGS
        pha
        lda     op_used+1
        adc     #>OPENINGS
        tax
        lda     t0
        sta     op_used
        lda     t1
        sta     op_used+1
        pla
        clc
        rts
@full:  sec
        rts

; ds_write: the copies ds_prepare left (in the session: writes only
; RENDER_BANK and the zero page)
ds_write:
        lda     dsw_top+1
        beq     @bot
        lda     dsw_top
        sta     p0
        lda     dsw_top+1
        sta     p0+1
        ldx     sw_start
        ldy     #0
:       lda     cclip,x
        sta     (p0),y
        inx
        iny
        cpy     sw_n
        bne     :-
@bot:   lda     dsw_bot+1
        beq     @mtc
        lda     dsw_bot
        sta     p0
        lda     dsw_bot+1
        sta     p0+1
        ldx     sw_start
        ldy     #0
:       lda     fclip,x
        sta     (p0),y
        inx
        iny
        cpy     sw_n
        bne     :-
@mtc:   lda     dsw_mtc+1
        beq     @rec
        lda     dsw_mtc
        sta     p0
        lda     dsw_mtc+1
        sta     p0+1
        ldx     sw_start
        ldy     #0
:       lda     mtcbuf,x
        sta     (p0),y
        iny
        lda     #0
        sta     (p0),y
        iny
        bne     :+
        inc     p0+1                    ; (more than 128 columns: 2 bytes each)
:       inx
        cpx     sw_stop
        beq     :--
        bcc     :--
@rec:   lda     dsw_rec+1
        beq     @done
        lda     dsw_rec
        sta     p0
        lda     dsw_rec+1
        sta     p0+1
        ldy     #DS_SIZE - 1
:       lda     ds_rec,y
        sta     (p0),y
        dey
        bpl     :-
@done:  rts

; ds_addr: A = drawseg (0 .. MAXDRAWSEGS - 1) -> A/X = its RENDER_BANK
; address, DS_BASE + 30n = DS_BASE + 32n - 2n (also rmasked.s)
.assert DS_SIZE = 30, error, "ds_addr: DS_SIZE"
ds_addr:
        stz     dsa_t+1
        asl     a
        rol     dsa_t+1
        sta     dsa_t                   ; 2n
        ldx     dsa_t+1
        stx     dsa_u
        asl     a
        rol     dsa_t+1
        asl     a
        rol     dsa_t+1
        asl     a
        rol     dsa_t+1
        asl     a
        rol     dsa_t+1                 ; 32n
        sec
        sbc     dsa_t
        tay
        lda     dsa_t+1
        sbc     dsa_u
        tax                             ; 30n
        tya
        clc
        adc     #<DS_BASE
        tay
        txa
        adc     #>DS_BASE
        tax
        tya
        rts
