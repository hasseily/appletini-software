; Doom for the Appletini -- the renderer's language-card code (docs/DESIGN.md
; section 7): everything that runs with RAMRD on.
;
; With RAMRD on, reads of $0200-$BFFF come from the RamWorks bank selected
; by $C073, so this code, and every byte it reads besides the bank's, lives
; in the language card (LC bank 1, switched in by render_frame) or the zero
; page. Writes still go to main memory (RAMWRT stays off): the view buffer
; and the renderer's buffers. Each routine turns RAMRD on once, does all its
; work, and turns it off. $C073 is written only when the bank differs from
; cur_bank (the last bank selected by the renderer; the kernel's far routines
; are not used while rendering, so it stays true). TURBO batches video
; writes; actual I/O and RamWorks cache costs depend on the target firmware.
;
;   rb_read     X bytes (0 = 256) from rb_bank:(rb_src) to (rb_dst) in main
;   rb_read1    one byte from rb_bank:(rb_src) -> A
;   q_wall      queue a textured column piece (the q_in_* parameters)
;   q_fill      queue a one-colour column piece (flat-shaded planes)
;   q_flush     draw every queued piece: per piece its graphics bank, its
;               column of texels and its colormap, both in that bank
;               (DESIGN.md 6: every graphics bank has the 16 colormaps at
;               $0200), written down the view buffer column
;   span_draw   one span of a plane: row y, columns x1..x2, flat texels
;               through a colormap
;   pl_used     is any column top of a visplane (RENDER_BANK) in use?
;
; A column piece is Doom's R_DrawColumn with 8.8 stepping, as the reference
; draws it: texel row (f >> 8) & hmask, f += step; the queue lets one
; RAMRD session draw a whole wall range (flushed at the end of each range,
; when full, and before the planes).

.include "kernel.inc"
.include "rdefs.inc"
.import rc_xs0, rc_xs1, rc_ys0, rc_ys1
.import kbuf


.ifdef BANKED_GAME
.segment "RZP": zeropage
.else
.segment "KZP": zeropage
.endif
cf_lo:      .res 1              ; column piece: the fraction byte of f
q_i:        .res 1
sp_xf:      .res 2              ; span: xfrac, yfrac (5.11)
sp_yf:      .res 2
sp_dp:      .res 2              ; span: view buffer address (+ Y)
sp_n:       .res 1              ; span: pixels left
.exportzp sp_xf, sp_yf, sp_dp, sp_n

.segment "RLC1"

; the span loop's tables, first in the segment: page aligned ($D000)
sp_gh:                          ; v >> 6
        .repeat 256, i
        .byte   i >> 6
        .endrepeat
sp_glo:                         ; (v >> 3 & 7) << 5
        .repeat 256, i
        .byte   ((i >> 3) & 7) << 5
        .endrepeat
.assert <sp_gh = 0, lderror, "sp_gh must be page aligned"

; the queue (structure of arrays)
q_count:    .res 1
q_bank:     .res QN
q_dlo:      .res QN             ; view buffer address of the first pixel
q_dhi:      .res QN
q_cnt:      .res QN             ; pixels
q_slo:      .res QN             ; texture column address; q_shi = 0: a fill
q_shi:      .res QN
q_flo:      .res QN             ; f & $FF (a fill: the colour)
q_fhi:      .res QN             ; f >> 8
q_stl:      .res QN             ; step
q_sth:      .res QN
q_cm:       .res QN             ; colormap page (>DD_COLORMAPS + k)
q_hm:       .res QN             ; hmask

; the parameters of q_wall / q_fill (set by the caller)
q_in_bank:  .res 1
q_in_dst:   .res 2
q_in_cnt:   .res 1
q_in_src:   .res 2
q_in_f:     .res 2
q_in_step:  .res 2
q_in_cm:    .res 1
q_in_hm:    .res 1
.export q_bank, q_dlo, q_dhi, q_cnt, q_slo, q_shi, q_flo, q_fhi, q_stl, q_sth, q_cm, q_hm
.export q_in_bank, q_in_dst, q_in_cnt, q_in_src, q_in_f, q_in_step, q_in_cm, q_in_hm

; ---------------------------------------------------------------------------
; rb_read: X bytes (0 = 256) from rb_bank:(rb_src) to (rb_dst): the odd
; bytes, then four per loop (14 cycles a byte rather than 18: the renderer
; reads some 16 KB of records a frame this way)
rb_read:
        lda     rb_bank
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       sta     RAMRDON
        stx     rb_cnt
        ldy     #0
        txa
        and     #3
        tax
        beq     @q
@r:     lda     (rb_src),y
        sta     (rb_dst),y
        iny
        dex
        bne     @r
@q:     lda     rb_cnt
        lsr     a
        lsr     a
        tax
        bne     @l
        lda     rb_cnt
        bne     @done
        ldx     #64                     ; X = 0: 256 bytes
@l:     .repeat 4
        lda     (rb_src),y
        sta     (rb_dst),y
        iny
        .endrepeat
        dex
        bne     @l
@done:  sta     RAMRDOFF
        rts
rb_cnt: .res    1

; rb_read1: A = the byte at rb_bank:(rb_src)
rb_read1:
        lda     rb_bank
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       sta     RAMRDON
        lda     (rb_src)
        sta     RAMRDOFF
        rts

; rb_write_on / rb_write_off: writes of $0200-$BFFF go to RENDER_BANK
; (code keeps running from main memory: only writes move)
rb_write_on:
        lda     #RENDER_BANK
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       sta     RAMWRTON
        rts
rb_write_off:
        sta     RAMWRTOFF
        rts

; ---------------------------------------------------------------------------
; q_wall: queue the piece q_in_*; flushes first when the queue is full
q_wall:
        ldx     q_count
        cpx     #QN
        bcc     :+
        jsr     q_flush
        ldx     #0
:       lda     q_in_bank
        sta     q_bank,x
        lda     q_in_dst
        sta     q_dlo,x
        lda     q_in_dst+1
        sta     q_dhi,x
        lda     q_in_cnt
        sta     q_cnt,x
        lda     q_in_src
        sta     q_slo,x
        lda     q_in_src+1
        sta     q_shi,x
        lda     q_in_f
        sta     q_flo,x
        lda     q_in_f+1
        sta     q_fhi,x
        lda     q_in_step
        sta     q_stl,x
        lda     q_in_step+1
        sta     q_sth,x
        lda     q_in_cm
        sta     q_cm,x
        lda     q_in_hm
        sta     q_hm,x
        inx
        stx     q_count
        rts

; q_fill: queue a fill of colour q_in_f (through colormap page q_in_cm of
; bank q_in_bank), q_in_cnt pixels at q_in_dst
q_fill:
        ldx     q_count
        cpx     #QN
        bcc     :+
        jsr     q_flush
        ldx     #0
:       lda     q_in_bank
        sta     q_bank,x
        lda     q_in_dst
        sta     q_dlo,x
        lda     q_in_dst+1
        sta     q_dhi,x
        lda     q_in_cnt
        sta     q_cnt,x
        stz     q_shi,x                 ; a fill
        lda     q_in_f
        sta     q_flo,x
        lda     q_in_cm
        sta     q_cm,x
        inx
        stx     q_count
        rts

; ---------------------------------------------------------------------------
; q_flush: draw and empty the queue
q_flush:
        lda     q_count
        bne     :+
        rts
:       sta     RAMRDON
        ldx     #0
@entry: stx     q_i
        lda     q_bank,x
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       lda     q_shi,x
        beq     @fill
        sta     @src+2
        lda     q_slo,x
        sta     @src+1
        lda     q_dlo,x
        sta     @dst+1
        lda     q_dhi,x
        sta     @dst+2
        lda     q_cm,x
        sta     @cm+2
        lda     q_stl,x
        sta     @stl+1
        lda     q_sth,x
        sta     @sth+1
        lda     q_hm,x
        sta     @hm+1
        lda     q_cnt,x
        sta     @end+1
        lda     q_flo,x
        sta     cf_lo
        lda     q_fhi,x
        and     q_hm,x
        tay
        ldx     #0
        clc
@loop:
@src:   lda     $FFFF,y                 ; the texel (column base + row)
        sta     kbuf,x                  ; separate texture and colormap reads
        lda     cf_lo
@stl:   adc     #$00
        sta     cf_lo
        tya
@sth:   adc     #$00
@hm:    and     #$00
        tay
        inx
@end:   cpx     #$00                    ; X < count: carry clear for the adc
        bne     @loop
        ; The kernel bounce buffer is idle throughout rendering and IRQs
        ; leave it alone. It remains visible in main LC with RAMRD on.
        ; Every raw texel is ready before shading; descending X preserves
        ; destination offsets without another counter (0 means 256 pixels).
@shade: dex
        lda     kbuf,x
        tay
@cm:    lda     $0200,y                 ; through the selected colormap
@dst:   sta     $FFFF,x
        cpx     #0
        bne     @shade
        bra     @next
@fill:  lda     q_dlo,x
        sta     @fdst+1
        lda     q_dhi,x
        sta     @fdst+2
        lda     q_cnt,x
        sta     @fend+1
        lda     q_cm,x
        sta     @fc+2
        lda     q_flo,x
        sta     @fc+1
@fc:    lda     $0200
        ldx     #0
@floop:
@fdst:  sta     $FFFF,x
        inx
@fend:  cpx     #$00
        bne     @floop
@next:  ldx     q_i
        inx
        cpx     q_count
        beq     :+
        jmp     @entry
:       sta     RAMRDOFF
        stz     q_count
        rts

; ---------------------------------------------------------------------------
; span_draw: A = the flat's bank; sp_n pixels of a row of the current
; plane. sp_dp = the view buffer address of the first pixel (the next pixel
; is 84 bytes on), sp_xf/sp_yf the flat coordinates (5.11, texel (x, y) of
; the 32x32 flat at base + 32y + x); span_set patched the steps, the flat
; and the colormap. The bank is selected and RAMRD is on for both passes:
; gather raw texels in kbuf, then shade them with the original 84-byte stride.
span_draw:
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       sta     RAMRDON
        ldy     #0
        clc
spd_pix: ldx    sp_yf+1
        lda     sp_gh,x                 ; y >> 6: the flat's quarter (256 bytes)
spd_bh: adc     #$00                    ; + the flat's address, high byte
        sta     spd_tex+2
        lda     sp_xf+1
        lsr     a
        lsr     a
        lsr     a                       ; x = xfrac >> 11
        ora     sp_glo,x                ; + 32 * (y & 7)
        tax
spd_tex: lda     $FF00,x                 ; low byte: the flat's address
        sta     kbuf,y
        iny
        clc
        lda     sp_xf
spd_xsl: adc     #$00
        sta     sp_xf
        lda     sp_xf+1
spd_xsh: adc     #$00
        sta     sp_xf+1
        clc
        lda     sp_yf
spd_ysl: adc     #$00
        sta     sp_yf
        lda     sp_yf+1
spd_ysh: adc     #$00
        sta     sp_yf+1
        clc
        dec     sp_n
        bne     spd_pix
        ; Y is the original count modulo 256 (zero still means 256).
        ; Restore it for the shading pass; no new persistent state is needed.
        sty     sp_n
        ldx     #0
        ldy     #0
spd_shade:
        lda     kbuf,x
        sta     spd_cm+1
spd_cm: lda     $0200                   ; colormap page patched by span_setrow
        sta     (sp_dp),y
        ; Preserve the destination cursor, including its final increment.
        tya
        clc
        adc     #VIEW_H
        tay
        bcc     :+
        inc     sp_dp+1
:       inx
        dec     sp_n
        bne     spd_shade
        clc                             ; original span return carry
        sta     RAMRDOFF
        rts

; span_setflat: A/X = the flat's address (per plane)
span_setflat:
        sta     spd_tex+1
        stx     spd_bh+1
        rts

; span_setrow: A = the colormap page, Y = the row: its steps from the row
; cache (rc_xs*, rc_ys*). Called with RAMRD off. Its instructions are
; immutable; only the LC span loop's operands are patched by these stores.
.segment "RTEXTDATA"
span_setrow:
        sta     spd_cm+2
        lda     rc_xs0,y
        sta     spd_xsl+1
        lda     rc_xs1,y
        sta     spd_xsh+1
        lda     rc_ys0,y
        sta     spd_ysl+1
        lda     rc_ys1,y
        sta     spd_ysh+1
        rts
.export span_setflat, span_setrow, span_draw

; ---------------------------------------------------------------------------
.segment "RLC1"
; pl_used: C set if any of the X (1..255) bytes at RENDER_BANK:(p0) is not
; $FF (a visplane's column tops: in use)
.export pl_used
pl_used:
        lda     #RENDER_BANK
        cmp     cur_bank
        beq     :+
        sta     cur_bank
        sta     RAMWORKS
:       sta     RAMRDON
        ldy     #0
@l:     lda     (p0),y
        cmp     #$FF
        bne     @used
        iny
        dex
        bne     @l
        sta     RAMRDOFF
        clc
        rts
@used:  sta     RAMRDOFF
        sec
        rts
