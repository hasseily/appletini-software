; Doom for the Appletini -- the things of a frame: R_AddSprites and
; R_ProjectSprite (docs/DESIGN.md 7.2; tools/refrender.py add_sprites,
; sprite_lump, project_sprite).
;
; The reference projects a sector's things when the BSP walk first enters
; the sector, in the packet's order. Nothing the walls or planes draw
; depends on the vissprites, so the 6502 does the same work after the
; walk (r_things, called by render_frame before the masked phase): the
; walk lists the sectors in the order of their first visit (rmain.s
; vs_list), the packet's things are hashed by sector (64 buckets, each a
; chain in packet order), and the list is replayed, which gives the same
; vissprites in the same order. Done late, the projection can keep the
; vissprites in buffers the walk no longer needs (rmask.inc).
;
; A vissprite keeps what the masked phase needs (rmask.inc): its thing
; (the packet index: gx, gy, gz are read again only if a drawseg needs
; them), scale, columns, startfrac, iscale, lump and flip, colormap and
; texturemid. Things farther than 20,480 units (a scale under 1/256, whose
; reciprocal would not fit 24 bits) are not drawn: E1's largest map
; spans 7,642 units corner to corner.
;
; Runs with LC bank 1 in: it uses the walk's bank reads (rb_read,
; rv_thing), sector cache and multiplies. It also finds the light of the
; eye's sector for the weapon (the walk's first subsector is the eye's;
; see rmain.s subsector).

.include "kernel.inc"
.include "rdefs.inc"
.include "rpacket.inc"
.include "rmask.inc"
.macpack longbranch

.import rv_buf, rv_tbuf, rv_thing, vs_list_lo, vs_list_hi, vs_count
.import get_sector, sc_light, r_extralight, r_fixedcm, light_row
.import muls_3_2_5, muls_3_3_5
.import eye_state, eye_sec, fetch_node, fetch_sub, nodebuf, subbuf, map_root
.import pos_px, pos_py, pos_lx, point_on_side
.import bitlen, _rview
.importzp ei

.export r_things, r_iscale, sprite_lump
.exportzp is_s, is_r

; ---------------------------------------------------------------------------
; zero page (the seg loop's, free in this phase: rmask.inc)
pj_trx      = MZ                ; tr_x, tr_y: thing - eye (s24 sub-units)
pj_try      = MZ+3
pj_tz       = MZ+6              ; s24
pj_tx       = MZ+9              ; s24
pj_xs       = MZ+12             ; xscale (u24)
pj_x1       = MZ+15             ; s16
pj_x2       = MZ+17
th_n        = MZ+19             ; things in the packet
th_p        = MZ+20             ; th_gather's pointer (2)
pj_i        = MZ+22             ; the thing being projected
pj_j        = MZ+26             ; vs_list index
pj_jn       = MZ+27             ; entries to replay (0 = 256)
pj_row      = MZ+28             ; the sector's scalelight row (2)
pj_s        = MZ+30             ; the sector being replayed (2)
pj_k        = MZ+32             ; the chain's thing
pj_lit      = MZ+33             ; pj_row is set for pj_s
is_s        = MZ+34             ; r_iscale: scale in (3)
is_r        = MZ+37             ; iscale out (3)
.assert is_r + 3 <= MZ + 41, error, "rthings: zero page"

.segment "RLC1"

; ---------------------------------------------------------------------------
; r_things: every thing of the packet in a sector the walk reached ->
; vissprites (vis_n), in the reference's order; the weapon's light
r_things:
        lda     #<rb_read
        sta     rd_vec
        lda     #>rb_read
        sta     rd_vec+1
        stz     vis_n
        lda     va
        sta     s_ang
        lda     va+1
        sta     s_ang+1
        jsr     cos_bam
        lda     s_val
        sta     viewcos
        lda     s_val+1
        sta     viewcos+1
        lda     va
        sta     s_ang
        lda     va+1
        sta     s_ang+1
        jsr     sin_bam
        lda     s_val
        sta     viewsin
        lda     s_val+1
        sta     viewsin+1
        jsr     eye_light
        lda     rv_buf+RV_NTHINGS
        bne     :+
        rts
:       sta     th_n
        jsr     th_gather
        ; the buckets: sector & 63, chains in packet order
        lda     #$FF
        ldx     #63
:       sta     th_head,x
        dex
        bpl     :-
        ldx     #0
@ins:   lda     #$FF
        sta     th_next,x
        lda     th_slo,x
        and     #63
        tay
        lda     th_head,y
        cmp     #$FF
        bne     @app
        txa
        sta     th_head,y
        sta     th_tail,y
        bra     @insn
@app:   phx
        lda     th_tail,y
        tax                             ; the old tail
        pla
        sta     th_next,x
        sta     th_tail,y
        tax
@insn:  inx
        cpx     th_n
        bne     @ins
        ; replay the sectors in the order of their first visit
        lda     vs_count+1
        beq     :+
        lda     #0                      ; more than 256: the first 256 (vs_list)
        bra     :++
:       lda     vs_count
        bne     :+
        rts
:       sta     pj_jn
        stz     pj_j
@sec:   ldx     pj_j
        lda     vs_list_lo,x
        sta     pj_s
        lda     vs_list_hi,x
        sta     pj_s+1
        stz     pj_lit
        lda     pj_s
        and     #63
        tax
        lda     th_head,x
@chain: cmp     #$FF
        beq     @nexts
        sta     pj_k
        tax
        lda     th_slo,x
        cmp     pj_s
        bne     @nextt
        lda     th_shi,x
        cmp     pj_s+1
        bne     @nextt
        ; a thing of this sector: its light row once per sector
        lda     pj_lit
        bne     :+
        lda     pj_s
        ldx     pj_s+1
        jsr     get_sector
        lda     sc_light,y
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     r_extralight
        jsr     light_row
        sta     pj_row
        stx     pj_row+1
        inc     pj_lit
:       lda     pj_k
        sta     pj_i
        jsr     project
@nextt: ldx     pj_k
        lda     th_next,x
        bra     @chain
@nexts: inc     pj_j
        lda     pj_j
        cmp     pj_jn
        bne     @sec
        rts

; th_gather: the sector of each of the th_n things -> th_slo/th_shi. One
; RAMRD session on bank 1 (reads of the zero page and this code only;
; the writes go to main memory)
th_gather:
        lda     #RV_PACKET_BANK
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       lda     #<(RV_PACKET_ADDR + RV_THINGS + RT_SECTOR)
        sta     th_p
        lda     #>(RV_PACKET_ADDR + RV_THINGS + RT_SECTOR)
        sta     th_p+1
        sta     RAMRDON
        ldx     #0
@l:     lda     (th_p)
        sta     th_slo,x
        ldy     #1
        lda     (th_p),y
        sta     th_shi,x
        clc
        lda     th_p
        adc     #RT_SIZE
        sta     th_p
        bcc     :+
        inc     th_p+1
:       inx
        cpx     th_n
        bne     @l
        sta     RAMRDOFF
        rts

; ---------------------------------------------------------------------------
; eye_light: ps_cm = the weapon's colormap when not full bright: the fixed
; colormap, else scalelight[light of the eye's sector + extralight][47]
eye_light:
        lda     r_fixedcm
        cmp     #$FF
        beq     :+
        sta     ps_cm
        rts
:       lda     rv_buf+RV_NPSPRITES
        bne     :+
        rts
:       lda     eye_state
        cmp     #1
        beq     @known
        ; the walk did not reach the eye's subsector first (its node stack
        ; overflowed on the way): R_PointInSubsector
        lda     map_root
        sta     ei
        lda     map_root+1
        sta     ei+1
@node:  lda     ei+1
        bmi     @sub
        jsr     fetch_node
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
        asl     a
        tax
        lda     nodebuf+NODE_CHILD0,x
        sta     ei
        lda     nodebuf+NODE_CHILD0+1,x
        sta     ei+1
        bra     @node
@sub:   and     #$7F
        sta     ei+1
        cmp     #$7F
        bne     :+
        lda     ei
        cmp     #$FF
        bne     :+
        stz     ei                      ; no nodes ($FFFF): subsector 0
        stz     ei+1
:       jsr     fetch_sub
        lda     subbuf+SSECTOR_SECTOR
        ldx     subbuf+SSECTOR_SECTOR+1
        bra     @light
@known: lda     eye_sec
        ldx     eye_sec+1
@light: jsr     get_sector
        lda     sc_light,y
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     r_extralight
        jsr     light_row
        sta     pj_row
        stx     pj_row+1
        ldy     #MAXLIGHTSCALE - 1
        lda     (pj_row),y
        sta     ps_cm
        rts

; ---------------------------------------------------------------------------
; TRIG tr, trig: m_r+2..m_r+4 = (tr (s24) * trig (Q14)) >> 14
.macro TRIG tr, trig
        lda     tr
        sta     m_a
        lda     tr+1
        sta     m_a+1
        lda     tr+2
        sta     m_a+2
        lda     trig
        sta     m_b
        lda     trig+1
        sta     m_b+1
        jsr     muls_3_2_5
        jsr     shr14
.endmacro

; project: thing pj_i of sector pj_s (scalelight row pj_row) -> a vissprite
project:
        lda     pj_i
        jsr     rv_thing
        sec
        lda     rv_tbuf+RT_X
        sbc     vx
        sta     pj_trx
        lda     rv_tbuf+RT_X+1
        sbc     vx+1
        sta     pj_trx+1
        lda     rv_tbuf+RT_X+2
        sbc     vx+2
        sta     pj_trx+2
        sec
        lda     rv_tbuf+RT_Y
        sbc     vy
        sta     pj_try
        lda     rv_tbuf+RT_Y+1
        sbc     vy+1
        sta     pj_try+1
        lda     rv_tbuf+RT_Y+2
        sbc     vy+2
        sta     pj_try+2
        ; tz = (tr_x cos >> 14) + (tr_y sin >> 14)
        TRIG    pj_trx, viewcos
        lda     m_r+2
        sta     pj_tz
        lda     m_r+3
        sta     pj_tz+1
        lda     m_r+4
        sta     pj_tz+2
        TRIG    pj_try, viewsin
        clc
        lda     pj_tz
        adc     m_r+2
        sta     pj_tz
        lda     pj_tz+1
        adc     m_r+3
        sta     pj_tz+1
        lda     pj_tz+2
        adc     m_r+4
        sta     pj_tz+2
        ; tz < MINZ: not drawn
        jmi     @out
        ora     pj_tz+1
        bne     :+
        lda     pj_tz
        cmp     #MINZ
        jcc     @out
:       ; xscale = (80 << 20) / tz
        jsr     div_xscale
        lda     pj_xs+2
        ora     pj_xs+1
        jeq     @out                    ; below 1/256: too far (see the header)
        ; tx = (tr_x sin >> 14) - (tr_y cos >> 14)
        TRIG    pj_trx, viewsin
        lda     m_r+2
        sta     pj_tx
        lda     m_r+3
        sta     pj_tx+1
        lda     m_r+4
        sta     pj_tx+2
        TRIG    pj_try, viewcos
        sec
        lda     pj_tx
        sbc     m_r+2
        sta     pj_tx
        lda     pj_tx+1
        sbc     m_r+3
        sta     pj_tx+1
        lda     pj_tx+2
        sbc     m_r+4
        sta     pj_tx+2
        ; |tx| > tz << 2: not drawn
        jsr     tx_side
        bcc     :+
@out:   rts
:       ; the rotation: ((angle to the thing - its angle + $9000) >> 13)
        ldx     #2
:       lda     pj_trx,x
        sta     pa_x,x
        lda     pj_try,x
        sta     pa_y,x
        dex
        bpl     :-
        jsr     point_to_angle
        sec
        lda     pa_r
        sbc     rv_tbuf+RT_ANGLE
        lda     pa_r+1
        sbc     rv_tbuf+RT_ANGLE+1
        clc
        adc     #$90
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     pj_rot
        lda     rv_tbuf+RT_FRAME
        ldx     rv_tbuf+RT_SPRITE
        jsr     sprite_lump
        bcs     @out
        ; SPRLUMP: bank, addr, width, left, top (pj_buf)
        ; tx -= left << 5
        lda     pj_buf+SPRLUMP_LEFT
        ldx     pj_buf+SPRLUMP_LEFT+1
        jsr     shl5
        sec
        lda     pj_tx
        sbc     pj_t
        sta     pj_tx
        lda     pj_tx+1
        sbc     pj_t+1
        sta     pj_tx+1
        lda     pj_tx+2
        sbc     pj_t+2
        sta     pj_tx+2
        ; x1 = (tx * xscale + (80 << 20)) >> 20
        jsr     tx_column
        sta     pj_x1
        stx     pj_x1+1
        txa
        bmi     :+
        bne     @out
        lda     pj_x1
        cmp     #VIEW_W
        bcs     @out
:       ; x2 = ((tx + (width << 5)) * xscale + (80 << 20)) >> 20) - 1
        lda     pj_buf+SPRLUMP_WIDTH
        ldx     #0
        jsr     shl5
        clc
        lda     pj_tx
        adc     pj_t
        sta     pj_tx
        lda     pj_tx+1
        adc     pj_t+1
        sta     pj_tx+1
        lda     pj_tx+2
        adc     pj_t+2
        sta     pj_tx+2
        jsr     tx_column
        sec
        sbc     #1
        sta     pj_x2
        txa
        sbc     #0
        sta     pj_x2+1
        jmi     @out                    ; x2 < 0
        ldx     vis_n
        cpx     #MAXVISSPRITES
        jcs     @out                    ; no room: not drawn
        ; the vissprite
        lda     pj_i
        sta     vis_th,x
        lda     pj_xs
        sta     vis_sc0,x
        sta     is_s
        lda     pj_xs+1
        sta     vis_sc1,x
        sta     is_s+1
        lda     pj_xs+2
        sta     vis_sc2,x
        sta     is_s+2
        lda     #0
        bit     pj_x1+1
        bmi     :+
        lda     pj_x1
:       sta     vis_x1,x
        lda     pj_x2+1
        bne     @x2max
        lda     pj_x2
        cmp     #VIEW_W
        bcc     :+
@x2max: lda     #VIEW_W - 1
:       sta     vis_x2,x
        ; texturemid = z + (top << 5) - vz
        lda     pj_buf+SPRLUMP_TOP
        ldx     pj_buf+SPRLUMP_TOP+1
        jsr     shl5
        ldx     vis_n
        clc
        lda     pj_t
        adc     rv_tbuf+RT_Z
        sta     pj_t
        lda     pj_t+1
        adc     rv_tbuf+RT_Z+1
        sta     pj_t+1
        lda     pj_t+2
        adc     rv_tbuf+RT_Z+2
        sta     pj_t+2
        sec
        lda     pj_t
        sbc     vz
        sta     vis_t0,x
        lda     pj_t+1
        sbc     vz+1
        sta     vis_t1,x
        lda     pj_t+2
        sbc     vz+2
        sta     vis_t2,x
        ; iscale
        jsr     r_iscale
        ldx     vis_n
        lda     is_r
        sta     vis_i0,x
        lda     is_r+1
        sta     vis_i1,x
        lda     is_r+2
        sta     vis_i2,x
        ; the columns clipped off the left: x1c - x1 (startfrac is made
        ; from it when the sprite is drawn)
        lda     #0
        sta     vis_sk0,x
        sta     vis_sk1,x
        bit     pj_x1+1
        bpl     :+
        sec
        sbc     pj_x1
        sta     vis_sk0,x
        lda     #0
        sbc     pj_x1+1
        sta     vis_sk1,x
:
        ; the lump and the flip (bit 7 of the high byte)
        lda     pj_lump
        sta     vis_llo,x
        lda     pj_lump+1
        and     #$BF
        sta     vis_lhi,x
        ; the colormap: shadow, fixed, full bright, else by scale
        lda     rv_tbuf+RT_FLAGS
        and     #RT_SHADOW
        beq     :+
        lda     #$FF
        bra     @cm
:       lda     r_fixedcm
        cmp     #$FF
        bne     @cm
        lda     rv_tbuf+RT_FRAME
        bpl     :+
        lda     #0
        bra     @cm
:       ; spritelights[min(xscale >> 11, 47)]
        lda     pj_xs+2
        cmp     #2
        bcs     @lmax
        lsr     a
        lda     pj_xs+1
        ror     a
        lsr     a
        lsr     a
        cmp     #MAXLIGHTSCALE
        bcc     :+
@lmax:  lda     #MAXLIGHTSCALE - 1
:       tay
        lda     (pj_row),y
@cm:    sta     vis_cm,x
        inc     vis_n
        rts

; div_xscale: pj_xs = (80 << 20) / tz (tz = pj_tz, 64 .. 2^23 - 1). The
; dividend is 101 followed by 24 zero bits: its top six bits (40) are below
; any tz, so the remainder starts at 40 and 21 zero bits are shifted in,
; each giving a quotient bit (the six before are 0)
.assert (PROJ << 20) >> 21 = 40 && (PROJ << 20) & $1FFFFF = 0 && MINZ > 40, error, "div_xscale"
div_xscale:
        lda     #40
        sta     pj_t
        stz     pj_t+1
        stz     pj_t+2
        stz     pj_xs
        stz     pj_xs+1
        stz     pj_xs+2
        ldx     #21
@l:     asl     pj_xs
        rol     pj_xs+1
        rol     pj_xs+2
        asl     pj_t
        rol     pj_t+1
        rol     pj_t+2
        sec
        lda     pj_t
        sbc     pj_tz
        tay
        lda     pj_t+1
        sbc     pj_tz+1
        sta     pj_t+3
        lda     pj_t+2
        sbc     pj_tz+2
        bcc     @n
        sta     pj_t+2
        lda     pj_t+3
        sta     pj_t+1
        sty     pj_t
        inc     pj_xs
@n:     dex
        bne     @l
        rts

; tx_side: C set if |tx| > tz << 2
tx_side:
        lda     pj_tz
        asl     a
        sta     pj_t
        lda     pj_tz+1
        rol     a
        sta     pj_t+1
        lda     pj_tz+2
        rol     a
        sta     pj_t+2
        lda     #0
        rol     a
        sta     pj_t+3
        asl     pj_t
        rol     pj_t+1
        rol     pj_t+2
        rol     pj_t+3
        ; |tx| (tz > 0 here, so pj_t+3 is small)
        lda     pj_tx+2
        bpl     @pos
        ; tx < 0: |tx| > t <=> -tx > t <=> tx + t < 0
        clc
        lda     pj_tx
        adc     pj_t
        lda     pj_tx+1
        adc     pj_t+1
        lda     pj_tx+2
        adc     pj_t+2
        tax
        lda     #$FF
        adc     pj_t+3
        asl     a                       ; C = the sign
        rts
@pos:   ; tx > t <=> t - tx < 0
        sec
        lda     pj_t
        sbc     pj_tx
        lda     pj_t+1
        sbc     pj_tx+1
        lda     pj_t+2
        sbc     pj_tx+2
        lda     pj_t+3
        sbc     #0
        asl     a
        rts

; tx_column: A/X = (tx * xscale + (80 << 20)) >> 20 (s16)
tx_column:
        lda     pj_tx
        sta     m_a
        lda     pj_tx+1
        sta     m_a+1
        lda     pj_tx+2
        sta     m_a+2
        lda     pj_xs
        sta     m_b
        lda     pj_xs+1
        sta     m_b+1
        lda     pj_xs+2
        sta     m_b+2
        jsr     muls_3_3_5
        clc
        lda     m_r+3
        adc     #<((PROJ << 20) >> 24)  ; 80 << 20: byte 3
        sta     m_r+3
        bcc     :+
        inc     m_r+4
:       ; bits 20..35
        lda     m_r+2
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     pj_t
        lda     m_r+3
        asl     a
        asl     a
        asl     a
        asl     a
        ora     pj_t
        pha
        lda     m_r+3
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     pj_t
        lda     m_r+4
        asl     a
        asl     a
        asl     a
        asl     a
        ora     pj_t
        tax
        pla
        rts

; ---------------------------------------------------------------------------
.segment "RCODE"

; shl5: A/X (s16) -> pj_t..pj_t+2 = the value << 5 (s24)
shl5:
        sta     pj_t
        stx     pj_t+1
        txa
        and     #$80
        beq     :+
        lda     #$FF
:       sta     pj_t+2
        ldy     #5
:       asl     pj_t
        rol     pj_t+1
        rol     pj_t+2
        dey
        bne     :-
        rts

; shr14: m_r+2..m_r+4 = m_r (40 bits, signed) >> 14 (its low 24 bits)
shr14:
        asl     m_r+1
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        asl     m_r+1
        rol     m_r+2
        rol     m_r+3
        rol     m_r+4
        rts

; sprite_lump: A = frame (bit 7 full bright), X = sprite, pj_rot -> C clear
; and pj_lump (SPRFRAME entry: lump | flipped << 15), pj_buf = its SPRLUMP
; record; C set: none (tools/refrender.py sprite_lump)
sprite_lump:
        and     #$7F
        sta     pj_t+3
        cpx     #DD_NUM_SPRITES
        jcs     @none
        ; SPRDEF: DD_SPRDEF + 4 * sprite
        stx     pj_t
        stz     pj_t+1
        asl     pj_t
        rol     pj_t+1
        asl     pj_t
        rol     pj_t+1
        clc
        lda     pj_t
        adc     #<DD_SPRDEF
        sta     rb_src
        lda     pj_t+1
        adc     #>DD_SPRDEF
        sta     rb_src+1
        ldx     #SPRDEF_SIZE
        jsr     dir_read
        lda     pj_t+3
        cmp     pj_buf+SPRDEF_NUMFRAMES
        bcs     @none
        ; SPRFRAME: DD_SPRFRAME + 16 * (firstframe + frame)
        clc
        adc     pj_buf+SPRDEF_FIRSTFRAME
        sta     pj_t
        lda     pj_buf+SPRDEF_FIRSTFRAME+1
        adc     #0
        ldx     #4
:       asl     pj_t
        rol     a
        dex
        bne     :-
        sta     pj_t+1
        clc
        lda     pj_t
        adc     #<DD_SPRFRAME
        sta     rb_src
        lda     pj_t+1
        adc     #>DD_SPRFRAME
        sta     rb_src+1
        ldx     #SPRFRAME_SIZE
        jsr     dir_read
        ldx     #0
        lda     pj_buf+SPRFRAME_ROT0+1
        and     #$40
        beq     :+
        lda     pj_rot
        asl     a
        tax
:       lda     pj_buf,x
        sta     pj_lump
        lda     pj_buf+1,x
        sta     pj_lump+1
        and     #$3F
        cmp     #>DD_SPR_NOLUMP
        bne     :+
        lda     pj_lump
        cmp     #<DD_SPR_NOLUMP
        beq     @none
:       ; SPRLUMP: DD_SPRLUMP + 8 * lump
        lda     pj_lump+1
        and     #$3F
        sta     pj_t+1
        lda     pj_lump
        asl     a
        rol     pj_t+1
        asl     a
        rol     pj_t+1
        asl     a
        rol     pj_t+1
        clc
        adc     #<DD_SPRLUMP
        sta     rb_src
        lda     pj_t+1
        adc     #>DD_SPRLUMP
        sta     rb_src+1
        ldx     #SPRLUMP_SIZE
        jsr     dir_read
        clc
        rts
@none:  sec
        rts

; dir_read: X bytes of the directory bank at rb_src -> pj_buf, through
; rd_vec (rb_read with LC bank 1 in, rb2_read with bank 2)
dir_read:
        lda     #DD_DIR_BANK
        sta     rb_bank
        lda     #<pj_buf
        sta     rb_dst
        lda     #>pj_buf
        sta     rb_dst+1
        jmp     (rd_vec)

; r_iscale: is_s (3 bytes, >= 256) -> is_r = texels per pixel (16.16):
; recip[the 9-bit mantissa] >> (bitlen - 9) (tools/refrender.py
; Tables.iscale; rsegs.s column_tex does the same inline)
r_iscale:
        ldx     is_s+2
        beq     @small
        ; bitlen = 16 + bitlen(hi): mantissa = (hi:mid) >> (bitlen(hi) - 1),
        ; iscale = (recip >> 8) >> (bitlen(hi) - 1)
        ldy     bitlen,x
        dey
        sty     pj_t
        lda     is_s+1
        stx     pj_t+1
        cpy     #0
        beq     :++
:       lsr     pj_t+1
        ror     a
        dey
        bne     :-
:       tax
        lda     recip_mid,x
        sta     is_r
        lda     recip_hi,x
        sta     is_r+1
        stz     is_r+2
        ldy     pj_t
        beq     @done
:       lsr     is_r+1
        ror     is_r
        dey
        bne     :-
@done:  rts
@small: ; bitlen = 8 + bitlen(mid), n = bitlen(mid) - 1 (0..7)
        ldx     is_s+1
        ldy     bitlen,x
        dey
        cpy     #5
        bcs     @left
        sty     pj_t
        lda     is_s
        stx     pj_t+1
        cpy     #0
        beq     :++
:       lsr     pj_t+1
        ror     a
        dey
        bne     :-
:       tax
        lda     recip_lo,x
        sta     is_r
        lda     recip_mid,x
        sta     is_r+1
        lda     recip_hi,x
        sta     is_r+2
        ldy     pj_t
        beq     @done
:       lsr     is_r+2
        ror     is_r+1
        ror     is_r
        dey
        bne     :-
        rts
@left:  ; n = 5..7: the mantissa is the high byte of (mid:lo) << (8 - n),
        ; iscale = (recip << (8 - n)) >> 8
        tya
        eor     #7
        tay
        iny                             ; 8 - n (1..3)
        sty     pj_t+2
        lda     is_s
        sta     pj_t
        txa
:       asl     pj_t
        rol     a
        dey
        bne     :-
        tax
        lda     recip_lo,x
        sta     pj_t
        lda     recip_mid,x
        sta     is_r
        lda     recip_hi,x
        sta     is_r+1
        stz     is_r+2
        ldy     pj_t+2
:       asl     pj_t
        rol     is_r
        rol     is_r+1
        rol     is_r+2
        dey
        bne     :-
        rts
