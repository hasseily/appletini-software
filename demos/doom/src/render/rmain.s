; Doom for the Appletini -- the renderer: the frame, the map, the BSP walk
; (docs/DESIGN.md section 7; tools/refrender.py Renderer.render,
; render_bsp, check_bbox, subsector, add_line, clip_solid, clip_pass).
;
; render_frame (RENDER space, from the frame loop):
;   1. LC bank 1 in (the renderer's RAMRD-safe code, rlc.s);
;   2. the render packet (src/game/rview.h): RV_HEADER + nthings * RT_SIZE
;      bytes of _rview in bank 1 into rv_buf;
;   3. the map: render_map (a byte in the language card that the game
;      sets: MAPDIR slot 9 * (episode - 1) + map - 1, $FF = none) is loaded
;      when it changes (its MAP record: the array descriptors, the sky);
;      no map: the view buffer is left as it is;
;   4. the frame's state: the eye, the animation of textures and flats for
;      the tic, the clip arrays, the solid-seg list, the caches;
;   5. the BSP walk, front to back, with an explicit node stack
;      (MAXBSPDEPTH frames); subsectors add their segs; the walls are
;      drawn by rsegs.s as they are found;
;   6. the planes (rplane.s); the vissprites (rthings.s r_things, from the
;      sectors the walk listed); then LC bank 2 back in (the kernel's blit
;      wants it) and the masked phase, which lives there (rmasked.s
;      r_masked: sprites, two-sided middles, the weapon).
;
; Map records are read from their banks with rb_read (rlc.s) through
; elem_addr (a far array element's bank and address, from the MAP record's
; descriptors). Per frame, vertexes are cached (angle from the eye and
; coordinates: 256 direct-mapped slots) and so are sectors (64 slots):
; the reference's per-vertex cache, and fewer bank reads; the result does
; not depend on hits or misses.
;
; The per-frame list of sectors reached (the reference's sectors_done, in
; the order of first visit) is kept for the sprite projection: vs_list,
; vs_count (rthings.s replays it after the walk: R_AddSprites' order). The
; first subsector the walk enters is the eye's (each node sends it to the
; eye's side first), unless the node stack overflowed before it: eye_state
; 1 and eye_sec, the weapon's light (rthings.s eye_light).

.include "kernel.inc"
.include "profile.inc"
.include "rdefs.inc"
.include "rpacket.inc"
.macpack longbranch

.import store_wall_range, draw_planes, find_plane, plane_frame
.import flat_trans, tex_trans
.import r_masked, r_things, mul_init, muls_3_2_5, segs_frame, sfa_init
.import tex_cache_reset, shl4tab, shr4tab, sar4tab
.import _rview

VC_SLOTS    = 128               ; vertex cache slots
SC_SLOTS    = 64                ; sector cache slots
MAXSECTORS  = 1024              ; the visited bitmap (E1's most: 699; beyond: not listed)
VS_MAX      = 256               ; visited sectors listed per frame
AN_FLATB    = (DD_NUM_FLATS + 7) / 8
AN_BYTES    = AN_FLATB + (DD_NUM_TEXTURES + 7) / 8
.assert AN_BYTES < 256, error, "an_bits: too many textures"

; a BSP stack frame
BF_BOX      = 0                 ; top, bottom, left, right (s16 map units)
BF_OTHER    = 8                 ; the child still to visit (u16)
BF_STATE    = 10                ; 0: first child running, 1: second
BF_SIZE     = 11

; ---------------------------------------------------------------------------
.ifdef BANKED_GAME
.segment "RZP": zeropage
.else
.segment "KZP": zeropage
.endif
m_a:        .res 4
m_b:        .res 4
m_r:        .res 8
mul_na:     .res 1
mul_nb:     .res 1
d_n:        .res 4
d_d:        .res 4
d_r:        .res 4
t0:         .res 1
t1:         .res 1
t2:         .res 1
t3:         .res 1
t4:         .res 1
t5:         .res 1
t6:         .res 1
t7:         .res 1
p0:         .res 2
p1:         .res 2
p2:         .res 2
rb_bank:    .res 1
rb_src:     .res 2
rb_dst:     .res 2
cur_bank:   .res 1
vx:         .res 3
vy:         .res 3
vz:         .res 3
va:         .res 2
s_ang:      .res 2
s_val:      .res 2
pa_x:       .res 3
pa_y:       .res 3
pa_r:       .res 2
topfrac:    .res 4
topstep:    .res 4
botfrac:    .res 4
botstep:    .res 4
pixhigh:    .res 4
pixhighstep: .res 4
pixlow:     .res 4
pixlowstep: .res 4
rw_scale:   .res 3
rw_step:    .res 3
rx:         .res 1
ryl:        .res 1
ryh:        .res 1
ei:         .res 2              ; elem_addr: the element index
bn:         .res 2              ; the BSP walk: the node or subsector
.exportzp ei

; ---------------------------------------------------------------------------
; render_map: the map to draw, set by the game (both spaces see the card)
.segment "RLCHI"
render_map: .byte   $FF
_render_map := render_map
.export _render_map

; ---------------------------------------------------------------------------
.segment "RLOBSS"
rv_buf:     .res RV_HEADER      ; the render packet's header
rv_tbuf:    .res RT_SIZE        ; a thing of the packet (rv_thing)
bsp_stack:  .res MAXBSPDEPTH * BF_SIZE
; the MAP record and the animation list at load time (map_load runs before
; the walk: the node stack is free then)
mapbuf      = bsp_stack
.assert MAP_SIZE <= MAXBSPDEPTH * BF_SIZE && DD_NUM_ANIMS * ANIM_SIZE <= MAXBSPDEPTH * BF_SIZE, error, "mapbuf"
.export rv_buf, vs_list_lo, vs_list_hi


.segment "RLOWDATA"
vs_list_lo: .res VS_MAX         ; sectors in the order of their first visit
vs_list_hi: .res VS_MAX

.segment "RLOBSS"
vc_tag_lo:  .res VC_SLOTS       ; the vertex cache (slot = index & 127)
vc_tag_hi:  .res VC_SLOTS
vc_ang_lo:  .res VC_SLOTS
vc_ang_hi:  .res VC_SLOTS
vc_x_lo:    .res VC_SLOTS
vc_x_hi:    .res VC_SLOTS
vc_y_lo:    .res VC_SLOTS
vc_y_hi:    .res VC_SLOTS
.segment "RBSS"
r_loaded:   .res 1              ; the map loaded ($FF none; 0 after the kernel's BSS clear
                                ; is taken care of by r_valid)
r_valid:    .res 1              ; a map is loaded
arr_bank:   .res NARRAYS
arr_base_lo: .res NARRAYS
arr_base_hi: .res NARRAYS
arr_shift:  .res NARRAYS        ; log2 - 8
arr_mask:   .res NARRAYS        ; (1 << (log2 - 8)) - 1: the index's in-chunk high bits
arr_esz:    .res NARRAYS        ; element size
map_root:   .res 2              ; the root node (or NF_SUBSECTOR)
map_sky:    .res 2              ; TEXDIR index of the sky
map_nsect:  .res 2              ; sectors
an_kind:    .res DD_NUM_ANIMS
an_count:   .res DD_NUM_ANIMS
an_first_lo: .res DD_NUM_ANIMS
an_first_hi: .res DD_NUM_ANIMS
an_ofs:     .res DD_NUM_ANIMS   ; (tic / 8) mod count, this frame
an_bits:    .res AN_BYTES       ; a bit per animated flat, then per texture
r_extralight: .res 1
r_fixedcm:  .res 1              ; $FF: none
r_tic:      .res 2
basexscale: .res 2              ; Q14 * 8/5, signed
baseyscale: .res 2
sc_tag_lo:  .res SC_SLOTS
sc_tag_hi:  .res SC_SLOTS
sc_floor_lo: .res SC_SLOTS
sc_floor_hi: .res SC_SLOTS
sc_ceil_lo: .res SC_SLOTS
sc_ceil_hi: .res SC_SLOTS
sc_fpic_lo: .res SC_SLOTS
sc_fpic_hi: .res SC_SLOTS
sc_cpic_lo: .res SC_SLOTS
sc_cpic_hi: .res SC_SLOTS
sc_light:   .res SC_SLOTS
vs_bits:    .res MAXSECTORS / 8 ; sectors visited this frame
vs_count:   .res 2              ; entries of vs_list (VS_MAX at most)
eye_state:  .res 1              ; 0 no subsector yet, 1 eye_sec is the eye's, 2 unknown
eye_sec:    .res 2              ; the sector of the walk's first subsector
ss_first:   .res MAXSOLIDSEGS   ; the solid-seg list, columns + 1
ss_last:    .res MAXSOLIDSEGS
ss_n:       .res 1
cclip:      .res VIEW_W         ; ceilingclip, rows + ROWBIAS
fclip:      .res VIEW_W         ; floorclip
bsp_sp:     .res 1              ; frames on the node stack
nodebuf:    .res 28
subbuf:     .res 6
segbuf:     .res 16
sidebuf:    .res 12
secbuf:     .res 16
vtxbuf:     .res 4
; the front and back sectors of the seg being added (subsector / add_line)
fs_index:   .res 2
fs_floor:   .res 2
fs_ceil:    .res 2
fs_fpic:    .res 2
fs_cpic:    .res 2
fs_light:   .res 1
bs_index:   .res 2              ; $FFFF: none
bs_floor:   .res 2
bs_ceil:    .res 2
bs_fpic:    .res 2
bs_cpic:    .res 2
bs_light:   .res 1
v1x:        .res 2              ; the seg's vertexes (map units)
v1y:        .res 2
v2x:        .res 2
v2y:        .res 2
floorplane: .res 1              ; plane handles (rplane.s)
ceilplane:  .res 1
floorpic_t: .res 2              ; their translated flats (for overflow pieces)
ceilpic_t:  .res 2
rb_arr:     .res 1              ; elem_addr's array
ea_lo:      .res 1              ; elem_addr's offset, low byte
sw_first:   .res 1              ; clip_solid / clip_pass: biased columns
sw_last:    .res 1
sw_i:       .res 1
sw_nxt:     .res 1
bb_box:     .res 8              ; check_bbox: top, bottom, left, right (s16 map units)
bb_c:       .res 12             ; the same in sub-units (s24)
bb_a1:      .res 2
bb_a2:      .res 2
bb_span:    .res 2
bb_t:       .res 2
bb_x1:      .res 1
bb_x2:      .res 1
pos_px:     .res 3              ; point_on_side: the point (sub-units)
pos_py:     .res 3
pos_lx:     .res 2              ; the line (map units)
pos_ly:     .res 2
pos_ldx:    .res 2
pos_ldy:    .res 2
pos_dx:     .res 3
pos_dy:     .res 3
pos_l:      .res 5
.export r_extralight, r_fixedcm, r_tic, basexscale, baseyscale, map_sky
.export fs_index, fs_floor, fs_ceil, fs_fpic, fs_cpic, fs_light
.export bs_index, bs_floor, bs_ceil, bs_fpic, bs_cpic, bs_light
.export v1x, v1y, v2x, v2y, segbuf, sidebuf, floorplane, ceilplane, floorpic_t, ceilpic_t
.export cclip, fclip, an_kind, an_count, an_first_lo, an_first_hi, an_ofs
.export an_bits, an_boff, bit8
.export vs_count, fetch_side, fetch_line_flags, point_on_side
.export pos_px, pos_py, pos_lx, pos_ly, pos_ldx, pos_ldy
.export ss_first, ss_last, ss_n
.export eye_state, eye_sec, fetch_node, fetch_sub, nodebuf, subbuf, map_root
.export get_sector, sc_light, bsp_stack, vc_y_hi

; ---------------------------------------------------------------------------
; render_frame and the per-frame setup: in the language card's $E000 area
; (render_frame switches the $D000 bank, which code there may do)
.segment "RLCHI"

render_frame:
        bit     LCBANK1WR               ; LC bank 1: the renderer's inner loops
        bit     LCBANK1WR
        lda     #$FF
        sta     cur_bank                ; unknown until the renderer selects one
        jsr     read_packet
        lda     render_map
        cmp     #$FF
        beq     @done
        ldx     r_valid
        beq     @load
        cmp     r_loaded
        beq     @go
@load:  jsr     map_load
        bcs     @done
@go:    jsr     mul_init
        jsr     frame_setup
        PROFILE_STAGE PROF_WALLS
        jsr     bsp_walk
        jsr     q_flush
        PROFILE_STAGE PROF_PLANES
        jsr     draw_planes
        jsr     q_flush
        PROFILE_STAGE PROF_THINGS
        jsr     r_things                ; the vissprites (rthings.s, LC bank 1)
        bit     LCBANK2WR               ; the masked phase runs in bank 2
        bit     LCBANK2WR
        PROFILE_STAGE PROF_MASKED
        jmp     r_masked                ; (rmasked.s)
@done:  bit     LCBANK2WR               ; bank 2 again: the kernel's blit
        bit     LCBANK2WR
        rts

; ---------------------------------------------------------------------------
; read_packet: the header of _rview (bank 1) -> rv_buf. The things stay in
; bank 1: rv_thing reads one when the masked phase projects it (each thing
; is read at most once a frame, and only those in sectors the walk reached;
; the game does not run while the frame is drawn, so this is the packet as
; the game left it)
read_packet:
        lda     #RV_PACKET_BANK
        sta     rb_bank
        lda     #<RV_PACKET_ADDR
        sta     rb_src
        lda     #>RV_PACKET_ADDR
        sta     rb_src+1
        lda     #<rv_buf
        sta     rb_dst
        lda     #>rv_buf
        sta     rb_dst+1
        ldx     #RV_HEADER
        jsr     rb_read
        lda     rv_buf+RV_NTHINGS
        cmp     #RV_MAXTHINGS+1
        bcc     :+
        lda     #RV_MAXTHINGS
        sta     rv_buf+RV_NTHINGS
:       rts

; rv_thing: A = thing index (< nthings) -> rv_tbuf = its RT_SIZE bytes
rv_thing:
        sta     t0
        stz     t1
        asl     t0                      ; * 4
        rol     t1
        asl     t0
        rol     t1
        lda     t0
        sta     t2
        lda     t1
        sta     t3
        asl     t0                      ; * 16
        rol     t1
        asl     t0
        rol     t1
        clc
        lda     t0
        adc     t2
        sta     t0
        lda     t1
        adc     t3
        sta     t1                      ; * 20
        clc
        lda     t0
        adc     #<(RV_PACKET_ADDR + RV_THINGS)
        sta     rb_src
        lda     t1
        adc     #>(RV_PACKET_ADDR + RV_THINGS)
        sta     rb_src+1
        lda     #RV_PACKET_BANK
        sta     rb_bank
        lda     #<rv_tbuf
        sta     rb_dst
        lda     #>rv_tbuf
        sta     rb_dst+1
        ldx     #RT_SIZE
        jmp     rb_read
.export rv_thing, rv_tbuf

; ---------------------------------------------------------------------------
; map_load: the MAP record of slot render_map -> the array descriptors,
; the sky, the root node; the animation list. C set: no such map.
map_load:
        lda     render_map
        sta     r_loaded
        stz     r_valid
        cmp     #DD_NUM_MAPSLOTS
        jcs     @none
        ; DD_MAPDIR + 128 * slot
        stz     t1
        lsr     a
        ror     t1                      ; slot * 128: hi = slot >> 1, lo = (slot & 1) << 7
        sta     t0
        clc
        lda     #<DD_MAPDIR
        adc     t1
        sta     rb_src
        lda     #>DD_MAPDIR
        adc     t0
        sta     rb_src+1
        lda     #DD_DIR_BANK
        sta     rb_bank
        lda     #<mapbuf
        sta     rb_dst
        lda     #>mapbuf
        sta     rb_dst+1
        ldx     #MAP_SIZE
        jsr     rb_read
        lda     mapbuf+MAP_NAME
        jeq     @none
        ; the descriptors of VERTEXES .. SECTORS
        ldx     #0
        ldy     #MAP_ARRAYS
@desc:  lda     mapbuf+DESC_BANK,y
        sta     arr_bank,x
        lda     mapbuf+DESC_ADDR,y
        sta     arr_base_lo,x
        lda     mapbuf+DESC_ADDR+1,y
        sta     arr_base_hi,x
        lda     mapbuf+DESC_ELSIZE,y
        sta     arr_esz,x
        lda     mapbuf+DESC_LOG2,y
        sec
        sbc     #8
        jcc     @bad                    ; fewer than 256 elements per chunk: not supported
        sta     arr_shift,x
        phy
        tay
        lda     #0
:       cpy     #0
        beq     :+
        sec
        rol     a
        dey
        bra     :-
:       sta     arr_mask,x
        ply
        tya
        clc
        adc     #DESC_SIZE
        tay
        inx
        cpx     #NARRAYS
        bne     @desc
        ; root = nodes - 1, or NF_SUBSECTOR without nodes
        ldy     #MAP_ARRAYS + MAPARR_NODES * DESC_SIZE
        lda     mapbuf+DESC_COUNT,y
        ora     mapbuf+DESC_COUNT+1,y
        bne     :+
        stz     map_root
        lda     #NF_SUBSECTOR
        sta     map_root+1
        bra     @sky
:       sec
        lda     mapbuf+DESC_COUNT,y
        sbc     #1
        sta     map_root
        lda     mapbuf+DESC_COUNT+1,y
        sbc     #0
        sta     map_root+1
@sky:   lda     mapbuf+MAP_SKY
        sta     map_sky
        lda     mapbuf+MAP_SKY+1
        sta     map_sky+1
        ldy     #MAP_ARRAYS + MAPARR_SECTORS * DESC_SIZE
        lda     mapbuf+DESC_COUNT,y
        sta     map_nsect
        lda     mapbuf+DESC_COUNT+1,y
        sta     map_nsect+1
        ; the animations (DD_NUM_ANIMS ANIM records of the directory bank)
        lda     #<DD_ANIMS
        sta     rb_src
        lda     #>DD_ANIMS
        sta     rb_src+1
        lda     #<mapbuf
        sta     rb_dst
        lda     #>mapbuf
        sta     rb_dst+1
        ldx     #DD_NUM_ANIMS * ANIM_SIZE
        jsr     rb_read
        ldx     #0
        ldy     #0
:       lda     mapbuf+ANIM_KIND,y
        sta     an_kind,x
        lda     mapbuf+ANIM_COUNT,y
        sta     an_count,x
        lda     mapbuf+ANIM_FIRST,y
        sta     an_first_lo,x
        lda     mapbuf+ANIM_FIRST+1,y
        sta     an_first_hi,x
        tya
        clc
        adc     #ANIM_SIZE
        tay
        inx
        cpx     #DD_NUM_ANIMS
        bne     :-
        ; the animated indices of each kind, a bit each (anim_trans)
        ldx     #AN_BYTES - 1
:       stz     an_bits,x
        dex
        bpl     :-
        ldy     #0
@abits: ldx     an_kind,y
        lda     an_first_lo,y
        sta     t0
        lda     an_first_hi,y
        sta     t1
        lda     an_count,y
        sta     t2
@abit:  ; set bit t1:t0 of kind X
        lda     t1
        lsr     a
        lda     t0
        ror     a
        lsr     a
        lsr     a
        clc
        adc     an_boff,x
        sta     t3
        lda     t0
        and     #7
        phx
        tax
        lda     bit8,x
        ldx     t3
        ora     an_bits,x
        sta     an_bits,x
        plx
        inc     t0
        bne     :+
        inc     t1
:       dec     t2
        bne     @abit
        iny
        cpy     #DD_NUM_ANIMS
        bne     @abits
        jsr     mul_init
        jsr     sfa_init                ; the per-column sines (rsegs.s)
        jsr     tex_cache_reset         ; (rplane.s)
        lda     #1
        sta     r_valid
        clc
        rts
@bad:
@none:  sec
        rts

; ---------------------------------------------------------------------------
; frame_setup: the eye and the frame's state from the packet
frame_setup:
        ldx     #2
:       lda     rv_buf+RV_X,x
        sta     vx,x
        lda     rv_buf+RV_Y,x
        sta     vy,x
        lda     rv_buf+RV_Z,x
        sta     vz,x
        dex
        bpl     :-
        lda     rv_buf+RV_ANGLE
        sta     va
        lda     rv_buf+RV_ANGLE+1
        sta     va+1
        lda     rv_buf+RV_EXTRALIGHT
        sta     r_extralight
        lda     rv_buf+RV_FIXEDCMAP
        sta     r_fixedcm
        lda     rv_buf+RV_TIC
        sta     r_tic
        lda     rv_buf+RV_TIC+1
        sta     r_tic+1
        ; basexscale = div_trunc(cos_bam(va - ANG90) * 8, 5) = div_trunc(sin_bam(va) * 8, 5)
        lda     va
        sta     s_ang
        lda     va+1
        sta     s_ang+1
        jsr     sin_bam
        jsr     @times8_div5
        lda     d_n
        sta     basexscale
        lda     d_n+1
        sta     basexscale+1
        ; baseyscale = -div_trunc(sin_bam(va - ANG90) * 8, 5)
        lda     va
        sta     s_ang
        sec
        lda     va+1
        sbc     #>ANG90
        sta     s_ang+1
        jsr     sin_bam
        jsr     @times8_div5
        jsr     neg_n
        lda     d_n
        sta     baseyscale
        lda     d_n+1
        sta     baseyscale+1
        ; animation offsets: (tic >> 3) mod count
        ldx     #0
@anim:  lda     r_tic
        sta     d_n
        lda     r_tic+1
        sta     d_n+1
        stz     d_n+2
        stz     d_n+3
        ldy     #3
:       lsr     d_n+1
        ror     d_n
        dey
        bne     :-
        lda     an_count,x
        sta     d_d
        stz     d_d+1
        stz     d_d+2
        stz     d_d+3
        phx
        jsr     udiv
        plx
        lda     d_r
        sta     an_ofs,x
        inx
        cpx     #DD_NUM_ANIMS
        bne     @anim
        ; the caches: every tag invalid (high byte $FF: no index is $FFxx here)
        lda     #$FF
        ldx     #VC_SLOTS-1
:       sta     vc_tag_hi,x
        dex
        bpl     :-
        ldx     #SC_SLOTS-1
:       sta     sc_tag_hi,x
        dex
        bpl     :-
        ; visited sectors
        ldx     #0
:       stz     vs_bits,x
        inx
        bne     :-
        stz     vs_count
        stz     vs_count+1
        stz     eye_state
        ; the solid-seg list: [-inf, -1], [160, +inf] (columns + 1, clamped)
        stz     ss_first
        stz     ss_last
        lda     #VIEW_W + 1
        sta     ss_first+1
        lda     #$FF
        sta     ss_last+1
        lda     #2
        sta     ss_n
        ; clip arrays: ceilingclip -1, floorclip 84
        ldx     #VIEW_W
:       lda     #ROWBIAS - 1
        sta     cclip-1,x
        lda     #ROWBIAS + VIEW_H
        sta     fclip-1,x
        dex
        bne     :-
        stz     q_count
        jsr     segs_frame              ; the per-seg cache (rsegs.s)
        jmp     plane_frame             ; visplanes, drawsegs, openings (rplane.s)

; d_n = div_trunc(s_val * 8, 5) (s_val signed Q14)
@times8_div5:
        lda     s_val
        sta     d_n
        lda     s_val+1
        sta     d_n+1
        and     #$80
        beq     :+
        lda     #$FF
:       sta     d_n+2
        sta     d_n+3
        ldx     #3
:       asl     d_n
        rol     d_n+1
        rol     d_n+2
        rol     d_n+3
        dex
        bne     :-
        lda     #5
        sta     d_d
        stz     d_d+1
        stz     d_d+2
        stz     d_d+3
        jmp     sdiv

; ---------------------------------------------------------------------------
.segment "RHICODE"

; elem_addr: X = array (MAPARR_*), ei = index -> rb_bank, rb_src
elem_addr:
        stx     rb_arr
        lda     ei+1
        and     arr_mask,x
        sta     t7                      ; the in-chunk index, high byte
        lda     ei+1
        ldy     arr_shift,x
        beq     @chunk
:       lsr     a
        dey
        bne     :-
@chunk: clc
        adc     arr_bank,x
        sta     rb_bank
        ; offset = index * element size, by the shift tables (4 .. 32)
        ldy     ei
        sty     ea_lo
        lda     arr_esz,x
        cmp     #16
        beq     @x16
        bcs     @x32
        cmp     #8
        beq     @x8
        bcs     @x12
        ; * 4
        lda     t7
        asl     ea_lo
        rol     a
        asl     ea_lo
        rol     a
        bra     @add
@x8:    lda     t7
        asl     ea_lo
        rol     a
        asl     ea_lo
        rol     a
        asl     ea_lo
        rol     a
        bra     @add
@x12:   ; * 12 = * 8 + * 4
        lda     t7
        asl     ea_lo
        rol     a
        asl     ea_lo
        rol     a
        sta     t6                      ; * 4: t6:ei
        ldy     ea_lo
        asl     ea_lo
        rol     a                       ; * 8: A:ei
        pha
        tya
        clc
        adc     ea_lo
        sta     ea_lo
        pla
        adc     t6
        bra     @add
@x16:   ldx     t7
        lda     shl4tab,x
        ora     shr4tab,y
        pha
        lda     shl4tab,y
        sta     ea_lo
        pla
        ldx     rb_arr
        bra     @add
@x32:   ldx     t7
        lda     shl4tab,x
        ora     shr4tab,y
        pha
        lda     shl4tab,y
        asl     a
        sta     ea_lo
        pla
        rol     a
        ldx     rb_arr
@add:   ; + the chunk's base
        pha
        clc
        lda     ea_lo
        adc     arr_base_lo,x
        sta     rb_src
        pla
        adc     arr_base_hi,x
        sta     rb_src+1
        rts

; fetch: A = array, ei = index, Y/X... common tail: X bytes to (rb_dst)
.macro FETCH array, buf, n
        ldx     #array
        jsr     elem_addr
        lda     #<buf
        sta     rb_dst
        lda     #>buf
        sta     rb_dst+1
        ldx     #n
        jmp     rb_read
.endmacro

fetch_node:     FETCH MAPARR_NODES, nodebuf, 28
fetch_sub:      FETCH MAPARR_SSECTORS, subbuf, 6
fetch_seg:      FETCH MAPARR_SEGS, segbuf, 16
fetch_side:     FETCH MAPARR_SIDEDEFS, sidebuf, 12
fetch_sector:   FETCH MAPARR_SECTORS, secbuf, 16
fetch_vertex:   FETCH MAPARR_VERTEXES, vtxbuf, 4

; fetch_line_flags: ei = linedef -> A = its flags (low byte)
fetch_line_flags:
        ldx     #MAPARR_LINEDEFS
        jsr     elem_addr
        clc
        lda     rb_src
        adc     #LINEDEF_FLAGS
        sta     rb_src
        bcc     :+
        inc     rb_src+1
:       jmp     rb_read1

; ---------------------------------------------------------------------------
; get_sector: A/X = sector -> Y = its cache slot (fields sc_*)
get_sector:
        sta     ei
        stx     ei+1
        and     #SC_SLOTS-1
        tay
        lda     ei
        cmp     sc_tag_lo,y
        bne     @miss
        lda     ei+1
        cmp     sc_tag_hi,y
        bne     @miss
        rts
@miss:  phy
        jsr     fetch_sector
        ply
        lda     ei
        sta     sc_tag_lo,y
        lda     ei+1
        sta     sc_tag_hi,y
        lda     secbuf+SECTOR_FLOORHEIGHT
        sta     sc_floor_lo,y
        lda     secbuf+SECTOR_FLOORHEIGHT+1
        sta     sc_floor_hi,y
        lda     secbuf+SECTOR_CEILINGHEIGHT
        sta     sc_ceil_lo,y
        lda     secbuf+SECTOR_CEILINGHEIGHT+1
        sta     sc_ceil_hi,y
        lda     secbuf+SECTOR_FLOORPIC
        sta     sc_fpic_lo,y
        lda     secbuf+SECTOR_FLOORPIC+1
        sta     sc_fpic_hi,y
        lda     secbuf+SECTOR_CEILINGPIC
        sta     sc_cpic_lo,y
        lda     secbuf+SECTOR_CEILINGPIC+1
        sta     sc_cpic_hi,y
        lda     secbuf+SECTOR_LIGHTLEVEL
        sta     sc_light,y
        rts

; vertex_angle: A/X = vertex -> pa_r = the angle from the eye, t0..t3 = x, y
; (map units); cached per frame
vertex_angle:
        sta     ei
        stx     ei+1
        and     #VC_SLOTS-1
        tay
        lda     ei
        cmp     vc_tag_lo,y
        bne     @miss
        txa
        cmp     vc_tag_hi,y
        bne     @miss
        lda     vc_ang_lo,y
        sta     pa_r
        lda     vc_ang_hi,y
        sta     pa_r+1
        lda     vc_x_lo,y
        sta     t0
        lda     vc_x_hi,y
        sta     t1
        lda     vc_y_lo,y
        sta     t2
        lda     vc_y_hi,y
        sta     t3
        rts
@miss:  jsr     fetch_vertex
        ; pa_x = (x << 4) - vx, pa_y = (y << 4) - vy
        lda     vtxbuf+VERTEX_X
        ldx     vtxbuf+VERTEX_X+1
        jsr     shl4
        sec
        lda     t4
        sbc     vx
        sta     pa_x
        lda     t5
        sbc     vx+1
        sta     pa_x+1
        lda     t6
        sbc     vx+2
        sta     pa_x+2
        lda     vtxbuf+VERTEX_Y
        ldx     vtxbuf+VERTEX_Y+1
        jsr     shl4
        sec
        lda     t4
        sbc     vy
        sta     pa_y
        lda     t5
        sbc     vy+1
        sta     pa_y+1
        lda     t6
        sbc     vy+2
        sta     pa_y+2
        jsr     point_to_angle
        lda     ei
        and     #VC_SLOTS-1
        tay
        lda     ei
        sta     vc_tag_lo,y
        lda     ei+1
        sta     vc_tag_hi,y
        lda     pa_r
        sta     vc_ang_lo,y
        lda     pa_r+1
        sta     vc_ang_hi,y
        lda     vtxbuf+VERTEX_X
        sta     vc_x_lo,y
        sta     t0
        lda     vtxbuf+VERTEX_X+1
        sta     vc_x_hi,y
        sta     t1
        lda     vtxbuf+VERTEX_Y
        sta     vc_y_lo,y
        sta     t2
        lda     vtxbuf+VERTEX_Y+1
        sta     vc_y_hi,y
        sta     t3
        rts

; shl4: A/X = s16 -> t4..t6 = s24 value << 4
.export shl4
shl4:
        phy
        tay
        lda     shl4tab,y
        sta     t4
        lda     shl4tab,x
        ora     shr4tab,y
        sta     t5
        lda     sar4tab,x
        sta     t6
        ply
        rts

; ---------------------------------------------------------------------------
; point_on_side: pos_px/py (s24 sub-units) against the line pos_lx/ly
; (map units) with direction pos_ldx/ldy -> A = 0 front, 1 back (R_PointOnSide)
point_on_side:
        lda     pos_ldx
        ora     pos_ldx+1
        bne     @notv
        ; vertical: x <= nx ? (ldy > 0) : (ldy < 0)
        lda     pos_lx
        ldx     pos_lx+1
        jsr     shl4
        ; px - nx <= 0 ?
        sec
        lda     pos_px
        sbc     t4
        sta     t4
        lda     pos_px+1
        sbc     t5
        sta     t5
        lda     pos_px+2
        sbc     t6
        bmi     @vle
        ora     t4
        ora     t5
        beq     @vle
        ; x > nx: ldy < 0
        lda     pos_ldy+1
        bmi     @one
        bra     @zero
@vle:   ; ldy > 0
        lda     pos_ldy+1
        bmi     @zero
        ora     pos_ldy
        bne     @one
        bra     @zero
@notv:  lda     pos_ldy
        ora     pos_ldy+1
        bne     @gen
        ; horizontal: y <= ny ? (ldx < 0) : (ldx > 0)
        lda     pos_ly
        ldx     pos_ly+1
        jsr     shl4
        sec
        lda     pos_py
        sbc     t4
        sta     t4
        lda     pos_py+1
        sbc     t5
        sta     t5
        lda     pos_py+2
        sbc     t6
        bmi     @hle
        ora     t4
        ora     t5
        beq     @hle
        ; y > ny: ldx > 0
        lda     pos_ldx+1
        bmi     @zero
        bra     @one                    ; ldx != 0 here
@hle:   lda     pos_ldx+1
        bmi     @one
        bra     @zero
@one:   lda     #1
        rts
@zero:  lda     #0
        rts
@gen:   ; dx = px - (lx << 4), dy = py - (ly << 4)
        lda     pos_lx
        ldx     pos_lx+1
        jsr     shl4
        sec
        lda     pos_px
        sbc     t4
        sta     pos_dx
        lda     pos_px+1
        sbc     t5
        sta     pos_dx+1
        lda     pos_px+2
        sbc     t6
        sta     pos_dx+2
        lda     pos_ly
        ldx     pos_ly+1
        jsr     shl4
        sec
        lda     pos_py
        sbc     t4
        sta     pos_dy
        lda     pos_py+1
        sbc     t5
        sta     pos_dy+1
        lda     pos_py+2
        sbc     t6
        sta     pos_dy+2
        ; the signs first: (ldy ^ ldx ^ dx ^ dy) < 0 -> (ldy ^ dx) < 0
        lda     pos_ldy+1
        eor     pos_ldx+1
        eor     pos_dx+2
        eor     pos_dy+2
        bpl     @mul
        lda     pos_ldy+1
        eor     pos_dx+2
        bmi     @one
        bra     @zero
@mul:   ; left = dy * ldx
        ldx     #2
:       lda     pos_dy,x
        sta     m_a,x
        dex
        bpl     :-
        lda     pos_ldx
        sta     m_b
        lda     pos_ldx+1
        sta     m_b+1
        jsr     muls_3_2_5
        ldx     #4
:       lda     m_r,x
        sta     pos_l,x
        dex
        bpl     :-
        ; right = ldy * dx
        ldx     #2
:       lda     pos_dx,x
        sta     m_a,x
        dex
        bpl     :-
        lda     pos_ldy
        sta     m_b
        lda     pos_ldy+1
        sta     m_b+1
        jsr     muls_3_2_5
        ; left >= right ?
        sec
        ldx     #0
        ldy     #5
:       lda     pos_l,x
        sbc     m_r,x
        inx
        dey
        bne     :-
        ora     #0                      ; N = the sign of the last byte (V kept)
        bvc     :+
        eor     #$80
:       jmi     @zero
        jmp     @one

; ---------------------------------------------------------------------------
; bsp_walk: render_bsp from the root, iteratively
bsp_walk:
        stz     bsp_sp
        lda     map_root
        sta     bn
        lda     map_root+1
        sta     bn+1
@enter: lda     bn+1
        bpl     @node
        ; a subsector ($FFFF: 0)
        cmp     #$FF
        bne     :+
        lda     bn
        cmp     #$FF
        bne     :+
        stz     bn
        stz     bn+1
        bra     @sub
:       and     #$7F
        sta     bn+1
@sub:   jsr     subsector
        jmp     @return
@node:  lda     bsp_sp
        cmp     #MAXBSPDEPTH
        bcc     @deep
        lda     eye_state               ; too deep: not visited (and if no
        bne     :+                      ; subsector came first, the eye's
        lda     #2                      ; is unknown)
        sta     eye_state
:       jmp     @return
@deep:
        lda     bn
        sta     ei
        lda     bn+1
        sta     ei+1
        jsr     fetch_node
        ; side = point_on_side(eye, node)
        ldx     #2
:       lda     vx,x
        sta     pos_px,x
        lda     vy,x
        sta     pos_py,x
        dex
        bpl     :-
        ldx     #7
:       lda     nodebuf+NODE_X,x
        sta     pos_lx,x
        dex
        bpl     :-
        jsr     point_on_side
        tax                             ; the side
        ldy     bsp_sp
        lda     bf_lo,y
        sta     p1
        lda     bf_hi,y
        sta     p1+1
        inc     bsp_sp
        ldy     #BF_STATE
        lda     #0
        sta     (p1),y
        txa
        bne     @side1
        ; front side: child0 now; box1 and child1 later
        ldy     #BF_OTHER
        lda     nodebuf+NODE_CHILD1
        sta     (p1),y
        iny
        lda     nodebuf+NODE_CHILD1+1
        sta     (p1),y
        ldy     #7
:       lda     nodebuf+NODE_BBOX1_TOP,y
        sta     (p1),y
        dey
        bpl     :-
        lda     nodebuf+NODE_CHILD0
        sta     bn
        lda     nodebuf+NODE_CHILD0+1
        sta     bn+1
        jmp     @enter
@side1: ; back side: child1 now; box0 and child0 later
        ldy     #BF_OTHER
        lda     nodebuf+NODE_CHILD0
        sta     (p1),y
        iny
        lda     nodebuf+NODE_CHILD0+1
        sta     (p1),y
        ldy     #7
:       lda     nodebuf+NODE_BBOX0_TOP,y
        sta     (p1),y
        dey
        bpl     :-
        lda     nodebuf+NODE_CHILD1
        sta     bn
        lda     nodebuf+NODE_CHILD1+1
        sta     bn+1
        jmp     @enter
@return:
        ldy     bsp_sp
        beq     @done
        lda     bf_lo-1,y               ; the top frame
        sta     p1
        lda     bf_hi-1,y
        sta     p1+1
        ldy     #BF_STATE
        lda     (p1),y
        bne     @pop
        lda     #1
        sta     (p1),y
        ; check_bbox(the frame's box)
        ldy     #7
:       lda     (p1),y
        sta     bb_box,y
        dey
        bpl     :-
        jsr     check_bbox
        bcc     @pop
        ldy     bsp_sp
        lda     bf_lo-1,y
        sta     p1
        lda     bf_hi-1,y
        sta     p1+1
        ldy     #BF_OTHER
        lda     (p1),y
        sta     bn
        iny
        lda     (p1),y
        sta     bn+1
        jmp     @enter
@pop:   dec     bsp_sp
        bra     @return
@done:  rts

; the node stack's frame addresses
bf_lo:
        .repeat MAXBSPDEPTH, i
        .byte   <(bsp_stack + i * BF_SIZE)
        .endrepeat
bf_hi:
        .repeat MAXBSPDEPTH, i
        .byte   >(bsp_stack + i * BF_SIZE)
        .endrepeat

; an_bits offsets by kind (0 flats, 1 textures); bit8[i] = 1 << i
an_boff:    .byte   0, AN_FLATB
bit8:       .byte   1, 2, 4, 8, 16, 32, 64, 128

; ---------------------------------------------------------------------------
; vatx: A/X = an angle clipped to +-clipangle (lo/hi) -> A = its column
; (viewangletox[((angle + ANG90) >> 4) - VATX_FIRST])
vatx:
        sta     t4
        txa
        clc
        adc     #>ANG90
        sta     t5
        lda     t4
        lsr     t5
        ror     a
        lsr     t5
        ror     a
        lsr     t5
        ror     a
        lsr     t5
        ror     a                       ; t5:A = fine index
        sec
        sbc     #<VATX_FIRST
        sta     t4
        lda     t5
        sbc     #>VATX_FIRST
        sta     t5
        clc
        lda     t4
        adc     #<viewangletox
        sta     p0
        lda     t5
        adc     #>viewangletox
        sta     p0+1
        lda     (p0)
        rts

; sub24_sign: A = the high byte of (X-zp s24) - (Y-zp s24), Z clear unless
; zero; N the sign (no overflow: operands within +-2^22)
.macro CMP24 a_, b_
        sec
        lda     a_
        sbc     b_
        sta     t4
        lda     a_+1
        sbc     b_+1
        sta     t5
        lda     a_+2
        sbc     b_+2
.endmacro

; ---------------------------------------------------------------------------
; check_bbox: bb_box (top, bottom, left, right) -> C set if any of it may
; be visible (R_CheckBBox)
CC_TOP = 0
CC_BOT = 3
CC_LEFT = 6
CC_RIGHT = 9
checkcoord:     ; x1, y1, x2, y2 (offsets into bb_c) by boxpos 0..10
        .byte   CC_RIGHT, CC_TOP, CC_LEFT, CC_BOT
        .byte   CC_RIGHT, CC_TOP, CC_LEFT, CC_TOP
        .byte   CC_RIGHT, CC_BOT, CC_LEFT, CC_TOP
        .byte   0, 0, 0, 0
        .byte   CC_LEFT, CC_TOP, CC_LEFT, CC_BOT
        .byte   0, 0, 0, 0
        .byte   CC_RIGHT, CC_BOT, CC_RIGHT, CC_TOP
        .byte   0, 0, 0, 0
        .byte   CC_LEFT, CC_TOP, CC_RIGHT, CC_BOT
        .byte   CC_LEFT, CC_BOT, CC_RIGHT, CC_BOT
        .byte   CC_LEFT, CC_BOT, CC_RIGHT, CC_TOP

check_bbox:
        ; the box in sub-units
        ldx     #0
        ldy     #0
@exp:   phx
        phy
        lda     bb_box,x
        pha
        lda     bb_box+1,x
        tax
        pla
        jsr     shl4
        ply
        lda     t4
        sta     bb_c,y
        lda     t5
        sta     bb_c+1,y
        lda     t6
        sta     bb_c+2,y
        iny
        iny
        iny
        plx
        inx
        inx
        cpx     #8
        bne     @exp
        ; boxx: vx <= left 0, vx < right 1, else 2
        ldx     #0
        CMP24   vx, bb_c+CC_LEFT
        bmi     @bx
        ora     t4
        ora     t5
        beq     @bx
        inx
        CMP24   vx, bb_c+CC_RIGHT
        bmi     @bx
        inx
@bx:    stx     t7
        ; boxy: vy >= top 0, vy > bottom 1, else 2
        ldx     #0
        CMP24   vy, bb_c+CC_TOP
        bpl     @by
        ldx     #4
        CMP24   vy, bb_c+CC_BOT
        bmi     @by2
        ora     t4
        ora     t5
        bne     @by
@by2:   ldx     #8
@by:    txa
        clc
        adc     t7                      ; boxpos
        cmp     #5
        bne     :+
        sec
        rts
:       asl     a
        asl     a
        sta     t7                      ; checkcoord index
        ; angle1 = point_to_angle(x1 - vx, y1 - vy) - va
        tax
        jsr     @corner
        sec
        lda     pa_r
        sbc     va
        sta     bb_a1
        lda     pa_r+1
        sbc     va+1
        sta     bb_a1+1
        lda     t7
        clc
        adc     #2
        tax
        jsr     @corner
        sec
        lda     pa_r
        sbc     va
        sta     bb_a2
        lda     pa_r+1
        sbc     va+1
        sta     bb_a2+1
        ; span = angle1 - angle2; >= ANG180: visible
        sec
        lda     bb_a1
        sbc     bb_a2
        sta     bb_span
        lda     bb_a1+1
        sbc     bb_a2+1
        sta     bb_span+1
        bpl     :+
        sec
        rts
:       jsr     clip_angles
        bcc     @no
        ; sx1 = vatx(angle1), sx2 = vatx(angle2)
        lda     bb_a1
        ldx     bb_a1+1
        jsr     vatx
        sta     bb_x1
        lda     bb_a2
        ldx     bb_a2+1
        jsr     vatx
        cmp     bb_x1
        beq     @no
        sta     bb_x2                   ; = sx2 - 1 + 1 (biased)
        inc     bb_x1                   ; biased
        ; the first solid seg reaching sx2
        ldx     #0
:       lda     ss_last,x
        cmp     bb_x2
        bcs     :+
        inx
        bra     :-
:       ; covered if sx1 >= first and sx2 <= last
        lda     bb_x1
        cmp     ss_first,x
        bcc     @yes
        lda     ss_last,x
        cmp     bb_x2
        bcc     @yes
@no:    clc
        rts
@yes:   sec
        rts
; @corner: X = checkcoord index of (x, y) -> pa_r = point_to_angle(x - vx, y - vy)
@corner:
        ldy     checkcoord,x
        sec
        lda     bb_c,y
        sbc     vx
        sta     pa_x
        lda     bb_c+1,y
        sbc     vx+1
        sta     pa_x+1
        lda     bb_c+2,y
        sbc     vx+2
        sta     pa_x+2
        ldy     checkcoord+1,x
        sec
        lda     bb_c,y
        sbc     vy
        sta     pa_y
        lda     bb_c+1,y
        sbc     vy+1
        sta     pa_y+1
        lda     bb_c+2,y
        sbc     vy+2
        sta     pa_y+2
        jmp     point_to_angle

; clip_angles: bb_a1/bb_a2 (relative to the view) and bb_span -> clipped to
; +-clipangle; C clear: outside the field of view
;   tspan = angle1 + clip; if tspan > 2clip: tspan -= 2clip, if tspan >= span:
;   out, angle1 = clip; the same for clip - angle2
clip_angles:
        clc
        lda     bb_a1
        adc     #<CLIPANGLE
        sta     bb_t
        lda     bb_a1+1
        adc     #>CLIPANGLE
        sta     bb_t+1
        ; tspan > 2 * clip ?
        lda     #<(2 * CLIPANGLE)
        cmp     bb_t
        lda     #>(2 * CLIPANGLE)
        sbc     bb_t+1
        bcs     @a2                     ; 2clip >= tspan
        sec
        lda     bb_t
        sbc     #<(2 * CLIPANGLE)
        sta     bb_t
        lda     bb_t+1
        sbc     #>(2 * CLIPANGLE)
        sta     bb_t+1
        ; tspan >= span: out
        lda     bb_t
        cmp     bb_span
        lda     bb_t+1
        sbc     bb_span+1
        bcs     @out
        lda     #<CLIPANGLE
        sta     bb_a1
        lda     #>CLIPANGLE
        sta     bb_a1+1
@a2:    sec
        lda     #<CLIPANGLE
        sbc     bb_a2
        sta     bb_t
        lda     #>CLIPANGLE
        sbc     bb_a2+1
        sta     bb_t+1
        lda     #<(2 * CLIPANGLE)
        cmp     bb_t
        lda     #>(2 * CLIPANGLE)
        sbc     bb_t+1
        bcs     @in
        sec
        lda     bb_t
        sbc     #<(2 * CLIPANGLE)
        sta     bb_t
        lda     bb_t+1
        sbc     #>(2 * CLIPANGLE)
        sta     bb_t+1
        lda     bb_t
        cmp     bb_span
        lda     bb_t+1
        sbc     bb_span+1
        bcs     @out
        lda     #<(-CLIPANGLE & $FFFF)
        sta     bb_a2
        lda     #>(-CLIPANGLE & $FFFF)
        sta     bb_a2+1
@in:    sec
        rts
@out:   clc
        rts

; ---------------------------------------------------------------------------
; subsector, add_line and the solid-seg list: LC bank 1
.segment "RLC1"

; subsector: bn = subsector -> its planes, its sprites' hook, its segs
subsector:
        lda     bn
        sta     ei
        lda     bn+1
        sta     ei+1
        jsr     fetch_sub
        lda     subbuf+SSECTOR_SECTOR
        ldx     subbuf+SSECTOR_SECTOR+1
        sta     fs_index
        stx     fs_index+1
        ldy     eye_state               ; the frame's first subsector: the eye's
        bne     :+
        sta     eye_sec
        stx     eye_sec+1
        inc     eye_state
:       jsr     get_sector
        lda     sc_floor_lo,y
        sta     fs_floor
        lda     sc_floor_hi,y
        sta     fs_floor+1
        lda     sc_ceil_lo,y
        sta     fs_ceil
        lda     sc_ceil_hi,y
        sta     fs_ceil+1
        lda     sc_fpic_lo,y
        sta     fs_fpic
        lda     sc_fpic_hi,y
        sta     fs_fpic+1
        lda     sc_cpic_lo,y
        sta     fs_cpic
        lda     sc_cpic_hi,y
        sta     fs_cpic+1
        lda     sc_light,y
        sta     fs_light
        ; the floor plane if the floor is below the eye
        lda     #NONE
        sta     floorplane
        lda     fs_floor
        ldx     fs_floor+1
        jsr     shl4
        CMP24   t4, vz
        bpl     @ceil                   ; floor >= eye
        lda     fs_fpic
        ldx     fs_fpic+1
        jsr     flat_trans
        sta     floorpic_t
        stx     floorpic_t+1
        ldy     fs_floor
        sty     t0
        ldy     fs_floor+1
        sty     t1
        jsr     find_plane              ; A/X = pic, t0/t1 = height, fs_light
        sta     floorplane
@ceil:  lda     #NONE
        sta     ceilplane
        lda     fs_cpic
        cmp     #<DD_SKYFLAT
        bne     :+
        lda     fs_cpic+1
        cmp     #>DD_SKYFLAT
        beq     @cplane
:       lda     fs_ceil
        ldx     fs_ceil+1
        jsr     shl4
        CMP24   vz, t4
        bpl     @sprites                ; ceiling <= eye
@cplane:
        lda     fs_cpic
        ldx     fs_cpic+1
        jsr     flat_trans
        sta     ceilpic_t
        stx     ceilpic_t+1
        ldy     fs_ceil
        sty     t0
        ldy     fs_ceil+1
        sty     t1
        jsr     find_plane
        sta     ceilplane
@sprites:
        ; the sector's first visit this frame: list it (rthings.s projects
        ; its things from the list after the walk)
        lda     fs_index+1
        cmp     #>MAXSECTORS
        bcs     @segs                   ; (no map has that many)
        sta     t1
        lda     fs_index
        sta     t0
        and     #7
        tax
        lda     @bits,x
        sta     t2
        lsr     t1                      ; index / 8 < 256
        ror     t0
        lsr     t1
        ror     t0
        lsr     t1
        ror     t0
        ldx     t0
        lda     vs_bits,x
        and     t2
        bne     @segs
        lda     vs_bits,x
        ora     t2
        sta     vs_bits,x
@first: lda     vs_count+1
        bne     :+                      ; the list is full
        ldx     vs_count
        lda     fs_index
        sta     vs_list_lo,x
        lda     fs_index+1
        sta     vs_list_hi,x
:       inc     vs_count
        bne     @segs
        inc     vs_count+1
@segs:  ; the segs
        lda     subbuf+SSECTOR_NUMSEGS
        sta     sub_n
        lda     subbuf+SSECTOR_NUMSEGS+1
        sta     sub_n+1
        lda     subbuf+SSECTOR_FIRSTSEG
        sta     sub_seg
        lda     subbuf+SSECTOR_FIRSTSEG+1
        sta     sub_seg+1
@seg:   lda     sub_n
        ora     sub_n+1
        beq     @done
        lda     sub_seg
        sta     ei
        lda     sub_seg+1
        sta     ei+1
        jsr     fetch_seg
        jsr     add_line
        inc     sub_seg
        bne     :+
        inc     sub_seg+1
:       lda     sub_n
        bne     :+
        dec     sub_n+1
:       dec     sub_n
        bra     @seg
@done:  rts
@bits:  .byte   1, 2, 4, 8, 16, 32, 64, 128

.segment "RBSS"
sub_n:      .res 2
sub_seg:    .res 2              ; the seg being added (its index)
.export sub_seg
al_a1:      .res 2
.segment "RLC1"

; ---------------------------------------------------------------------------
; add_line: the seg in segbuf (R_AddLine)
add_line:
        lda     segbuf+SEG_V1
        ldx     segbuf+SEG_V1+1
        jsr     vertex_angle
        lda     pa_r
        sta     al_a1
        lda     pa_r+1
        sta     al_a1+1
        ldx     #3
:       lda     t0,x
        sta     v1x,x
        dex
        bpl     :-
        lda     segbuf+SEG_V2
        ldx     segbuf+SEG_V2+1
        jsr     vertex_angle
        ldx     #3
:       lda     t0,x
        sta     v2x,x
        dex
        bpl     :-
        ; span = angle1 - angle2 >= ANG180: back side
        sec
        lda     al_a1
        sbc     pa_r
        sta     bb_span
        lda     al_a1+1
        sbc     pa_r+1
        sta     bb_span+1
        bpl     :+
        rts
:       ; relative to the view
        sec
        lda     al_a1
        sbc     va
        sta     bb_a1
        lda     al_a1+1
        sbc     va+1
        sta     bb_a1+1
        sec
        lda     pa_r
        sbc     va
        sta     bb_a2
        lda     pa_r+1
        sbc     va+1
        sta     bb_a2+1
        jsr     clip_angles
        bcs     :+
        rts
:       lda     bb_a1
        ldx     bb_a1+1
        jsr     vatx
        sta     bb_x1
        lda     bb_a2
        ldx     bb_a2+1
        jsr     vatx
        cmp     bb_x1
        bne     :+
        rts
:       sta     sw_last                 ; x2 - 1 + 1 (biased)
        ldx     bb_x1
        inx
        stx     sw_first
        ; the back sector
        lda     segbuf+SEG_BACKSECTOR
        ldx     segbuf+SEG_BACKSECTOR+1
        sta     bs_index
        stx     bs_index+1
        cmp     #$FF
        bne     @two
        cpx     #$FF
        bne     @two
        jmp     clip_solid
@two:   jsr     get_sector
        lda     sc_floor_lo,y
        sta     bs_floor
        lda     sc_floor_hi,y
        sta     bs_floor+1
        lda     sc_ceil_lo,y
        sta     bs_ceil
        lda     sc_ceil_hi,y
        sta     bs_ceil+1
        lda     sc_fpic_lo,y
        sta     bs_fpic
        lda     sc_fpic_hi,y
        sta     bs_fpic+1
        lda     sc_cpic_lo,y
        sta     bs_cpic
        lda     sc_cpic_hi,y
        sta     bs_cpic+1
        lda     sc_light,y
        sta     bs_light
        ; closed door: back ceiling <= front floor or back floor >= front ceiling
        lda     fs_floor
        cmp     bs_ceil
        lda     fs_floor+1
        sbc     bs_ceil+1
        bvc     :+
        eor     #$80
:       bpl     @solid                  ; fs_floor >= bs_ceil
        lda     bs_floor
        cmp     fs_ceil
        lda     bs_floor+1
        sbc     fs_ceil+1
        bvc     :+
        eor     #$80
:       bpl     @solid                  ; bs_floor >= fs_ceil
        ; window: heights differ
        lda     bs_ceil
        cmp     fs_ceil
        bne     @pass
        lda     bs_ceil+1
        cmp     fs_ceil+1
        bne     @pass
        lda     bs_floor
        cmp     fs_floor
        bne     @pass
        lda     bs_floor+1
        cmp     fs_floor+1
        bne     @pass
        ; the same planes and light, no middle texture: invisible
        lda     bs_cpic
        cmp     fs_cpic
        bne     @pass
        lda     bs_cpic+1
        cmp     fs_cpic+1
        bne     @pass
        lda     bs_fpic
        cmp     fs_fpic
        bne     @pass
        lda     bs_fpic+1
        cmp     fs_fpic+1
        bne     @pass
        lda     bs_light
        cmp     fs_light
        bne     @pass
        lda     segbuf+SEG_SIDEDEF
        sta     ei
        lda     segbuf+SEG_SIDEDEF+1
        sta     ei+1
        jsr     fetch_side
        lda     sidebuf+SIDEDEF_MIDTEXTURE
        ora     sidebuf+SIDEDEF_MIDTEXTURE+1
        bne     @pass
        rts
@solid: jmp     clip_solid
@pass:  jmp     clip_pass

; ---------------------------------------------------------------------------
; swr: store_wall_range(A - 1, X - 1) (biased columns to real ones)
swr:
        dec     a
        dex
        jmp     store_wall_range        ; A = start, X = stop

; clip_solid: sw_first..sw_last (biased) -> R_ClipSolidWallSegment
clip_solid:
        ; i = the first seg with last >= first - 1
        ldx     #0
        lda     sw_first
        dec     a
        sta     t0
:       lda     ss_last,x
        cmp     t0
        bcs     :+
        inx
        bra     :-
:       stx     sw_i
        lda     sw_first
        cmp     ss_first,x
        bcs     @inside                 ; first >= ss_first[i]
        ; first < ss_first[i]
        lda     ss_first,x
        dec     a
        sta     t0
        lda     sw_last
        cmp     t0
        bcs     @touch                  ; last >= ss_first[i] - 1
        ; a new fragment: draw it, insert it at i
        lda     sw_first
        ldx     sw_last
        jsr     swr
        ldx     sw_i
        jsr     ss_insert
        rts
@touch: lda     sw_first
        ldx     t0
        jsr     swr
        ldx     sw_i
        lda     sw_first
        sta     ss_first,x
@inside:
        ldx     sw_i
        lda     ss_last,x
        cmp     sw_last
        bcc     :+
        rts                             ; last <= ss_last[i]
:       stx     sw_nxt
@loop:  ; while last >= ss_first[nxt + 1] - 1
        ldx     sw_nxt
        lda     ss_first+1,x
        dec     a
        sta     t0
        lda     sw_last
        cmp     t0
        bcc     @tail
        ; the gap between nxt and nxt + 1
        lda     ss_last,x
        inc     a
        ldx     t0
        jsr     swr
        inc     sw_nxt
        ldx     sw_nxt
        lda     ss_last,x
        cmp     sw_last
        bcc     @loop
        ; last <= ss_last[nxt]: merge i..nxt
        ldx     sw_i
        sta     ss_last,x
        jmp     ss_delete
@tail:  ldx     sw_nxt
        lda     ss_last,x
        inc     a
        ldx     sw_last
        jsr     swr
        ldx     sw_i
        lda     sw_last
        sta     ss_last,x
        jmp     ss_delete

; ss_insert: insert [sw_first, sw_last] at index X
ss_insert:
        stx     t0
        ldx     ss_n
:       dex
        lda     ss_first,x
        sta     ss_first+1,x
        lda     ss_last,x
        sta     ss_last+1,x
        cpx     t0
        bne     :-
        lda     sw_first
        sta     ss_first,x
        lda     sw_last
        sta     ss_last,x
        inc     ss_n
        rts

; ss_delete: remove entries sw_i + 1 .. sw_nxt
ss_delete:
        lda     sw_nxt
        sec
        sbc     sw_i
        beq     @done                   ; nothing
        sta     t0                      ; entries removed
        ldx     sw_i
        inx                             ; destination
        ldy     sw_nxt
        iny                             ; source
@mv:    cpy     ss_n
        bcs     @end
        lda     ss_first,y
        sta     ss_first,x
        lda     ss_last,y
        sta     ss_last,x
        inx
        iny
        bra     @mv
@end:   lda     ss_n
        sec
        sbc     t0
        sta     ss_n
@done:  rts

; clip_pass: sw_first..sw_last (biased) -> R_ClipPassWallSegment
clip_pass:
        ldx     #0
        lda     sw_first
        dec     a
        sta     t0
:       lda     ss_last,x
        cmp     t0
        bcs     :+
        inx
        bra     :-
:       stx     sw_i
        lda     sw_first
        cmp     ss_first,x
        bcs     @inside
        lda     ss_first,x
        dec     a
        sta     t0
        lda     sw_last
        cmp     t0
        bcs     @touch
        lda     sw_first
        ldx     sw_last
        jmp     swr
@touch: lda     sw_first
        ldx     t0
        jsr     swr
@inside:
        ldx     sw_i
        lda     ss_last,x
        cmp     sw_last
        bcc     @loop
        rts
@loop:  ldx     sw_i
        lda     ss_first+1,x
        dec     a
        sta     t0
        lda     sw_last
        cmp     t0
        bcc     @tail
        lda     ss_last,x
        inc     a
        ldx     t0
        jsr     swr
        inc     sw_i
        ldx     sw_i
        lda     ss_last,x
        cmp     sw_last
        bcc     @loop
        rts
@tail:  lda     ss_last,x
        inc     a
        ldx     sw_last
        jmp     swr
