; Doom for the Appletini -- the level data's hot accessors and caches, 6502
; (docs/DESIGN.md sections 6 and 9).
;
; The assembly twin of p_levdata.c (the C is the reference, compiled on the
; host; this is what GAME.BIN runs). Same functions, same results:
;
;   far_t P_LevAddr(uint8_t array, uint16_t index)
;   void  P_LevRead(uint8_t array, uint16_t index, void *dst, uint16_t len)
;   void  P_LevWrite(uint8_t array, uint16_t index, const void *src, uint16_t len)
;   void  P_SetSectorFloor(uint16_t sector, int16_t height), P_SetSectorCeiling,
;         P_SetSectorSpecial(uint16_t sector, uint8_t special)
;   line_t *P_Line(uint16_t index)          (also leaves the pointer in gli)
;   void  P_SetLineSpecial(uint16_t line, uint8_t special)
;   uint16_t R_PointInSector(fixed_t x, fixed_t y)
;   boolean P_RejectVisible(uint16_t s1, uint16_t s2)
;   void  P_ClearCaches(void)
;
; and for the other assembly modules:
;
;   lev_addr    A = array (MAPARR_*), lev_idx = index -> lev_far (lo, hi, bank)
;   line_get    A/X = index -> gli = the cached line (P_Line without C)
;   rpis        rp_x, rp_y (fixed) -> A/X = sector (R_PointInSector)
;   blk_lines   blk_cell, blk_pos -> up to 16 line numbers of the cell's
;               blockmap list at blk_buf, A = the count (0: done), blk_pos
;               advanced (P_BlockLines with out = blk_buf, max = 16)
;
; The caches, all direct mapped: 64 lines (line_t, 27 bytes), 128 BSP
; nodes and 64 subsectors (byte planes indexed by slot), 16 blockmap cells
; (up to CELL_LINES lines each; longer lists are read from far memory in
; pieces of 16).

.include "gmacros.inc"
.globalzp far_src, far_dst, far_ptr, far_len, ktmp
.import kjt_far_read, kjt_far_write
.import incsp2, incsp5, popax, popa
.import fx_mul, fxa, fxb, fxr
.import _levarr, _numnodes, _numsectors
.import _sec_floorh, _sec_ceilh, _sec_special
.import _rej_known, _rej_bits

.export _P_LevAddr, _P_LevRead, _P_LevWrite
.export _P_SetSectorFloor, _P_SetSectorCeiling, _P_SetSectorSpecial
.export _P_Line, _P_SetLineSpecial, _R_PointInSector, _P_RejectVisible, _P_ClearCaches
.export lev_addr, lev_idx, lev_far, line_get, rpis, rp_x, rp_y
.export blk_lines, blk_cell, blk_pos, blk_buf, far_rd, far_wr

LINECACHE   = 64
NODECACHE   = 128
SSECCACHE   = 64
CELLCACHE   = 16
CELL_LINES  = 27

.segment "BSS"
lev_idx:    .res 2
lev_far:    .res 3
la_tmp:     .res 2
linebuf:    .res LINEDEF_BACKSECTOR + 2 - LINEDEF_FLAGS
linecache:  .res LINECACHE * LI_SIZE
nc_key_lo:  .res NODECACHE
nc_key_hi:  .res NODECACHE
nc_x_lo:    .res NODECACHE
nc_x_hi:    .res NODECACHE
nc_y_lo:    .res NODECACHE
nc_y_hi:    .res NODECACHE
nc_dx_lo:   .res NODECACHE
nc_dx_hi:   .res NODECACHE
nc_dy_lo:   .res NODECACHE
nc_dy_hi:   .res NODECACHE
nc_c0_lo:   .res NODECACHE
nc_c0_hi:   .res NODECACHE
nc_c1_lo:   .res NODECACHE
nc_c1_hi:   .res NODECACHE
ss_key_lo:  .res SSECCACHE
ss_key_hi:  .res SSECCACHE
ss_sec_lo:  .res SSECCACHE
ss_sec_hi:  .res SSECCACHE
nodebuf:    .res NODE_CHILD1 + 2
rp_x:       .res 4
rp_y:       .res 4
rp_dx:      .res 4
rp_dy:      .res 4
rp_left:    .res 4
rp_node:    .res 2
rp_slot:    .res 1
cc_key_lo:  .res CELLCACHE
cc_key_hi:  .res CELLCACHE
cc_count:   .res CELLCACHE
cc_lines:   .res CELLCACHE * CELL_LINES * 2
blk_cell:   .res 2
blk_pos:    .res 2
blk_buf:    .res 32
blk_off:    .res 2
rej_s2:     .res 2
rej_pnum:   .res 4
rej_i:      .res 2
rej_mask:   .res 1

.segment "CODE"

; ---- far_rd / far_wr: far_len bytes between lev_far and the near far_ptr ----
far_rd: lda     lev_far
        sta     far_src
        lda     lev_far+1
        sta     far_src+1
        lda     lev_far+2
        sta     far_src+2
        jmp     kjt_far_read

far_wr: lda     lev_far
        sta     far_dst
        lda     lev_far+1
        sta     far_dst+1
        lda     lev_far+2
        sta     far_dst+2
        jmp     kjt_far_write

; ---- lev_addr ------------------------------------------------------------------
; A = array, lev_idx = index -> lev_far = bank:address of the element
lev_addr:
        ; ptr1 = &levarr[A] (10 bytes each)
        asl     a                       ; 2A
        sta     tmp1
        asl     a
        asl     a                       ; 8A
        clc
        adc     tmp1                    ; 10A (< 256)
        clc
        adc     #<_levarr
        sta     ptr1
        lda     #>_levarr
        adc     #0
        sta     ptr1+1
        ; within = index & mask
        ldy     #LA_MASK
        lda     (ptr1),y
        and     lev_idx
        sta     la_tmp
        iny
        lda     (ptr1),y
        and     lev_idx+1
        sta     la_tmp+1
        ; bank = bank + (index >> log2), if log2 < 16
        ldy     #LA_BANK
        lda     (ptr1),y
        sta     lev_far+2
        ldy     #LA_LOG2
        lda     (ptr1),y
        cmp     #16
        bcs     @nochunk
        tax
        lda     lev_idx
        sta     tmp1
        lda     lev_idx+1
        cpx     #8                      ; >> 8 first when log2 >= 8
        bcc     @sh
        sta     tmp1
        lda     #0
        pha
        txa
        sbc     #8                      ; carry set
        tax
        pla
@sh:    sta     tmp2
        cpx     #0
        beq     @shd
@shl:   lsr     tmp2
        ror     tmp1
        dex
        bne     @shl
@shd:   lda     tmp1
        clc
        adc     lev_far+2
        sta     lev_far+2
@nochunk:
        ; offset = within << shift, or within * elsize
        ldy     #LA_SHIFT
        lda     (ptr1),y
        cmp     #$FF
        beq     @mul
        tax
        beq     @off
@shift: asl     la_tmp
        rol     la_tmp+1
        dex
        bne     @shift
        bra     @off
@mul:   ldy     #LA_ELSIZE
        lda     (ptr1),y
        sta     tmp1                    ; the multiplier (8 bits)
        lda     la_tmp
        sta     tmp2
        lda     la_tmp+1
        sta     tmp3
        stz     la_tmp
        stz     la_tmp+1
@mloop: lsr     tmp1
        bcc     @mnext
        clc
        lda     la_tmp
        adc     tmp2
        sta     la_tmp
        lda     la_tmp+1
        adc     tmp3
        sta     la_tmp+1
@mnext: asl     tmp2
        rol     tmp3
        lda     tmp1
        bne     @mloop
@off:   ldy     #LA_ADDR
        lda     (ptr1),y
        clc
        adc     la_tmp
        sta     lev_far
        iny
        lda     (ptr1),y
        adc     la_tmp+1
        sta     lev_far+1
        rts

; far_t __fastcall__ P_LevAddr(uint8_t array, uint16_t index)
_P_LevAddr:
        sta     lev_idx
        stx     lev_idx+1
        jsr     popa
        jsr     lev_addr
        lda     lev_far+2
        sta     sreg
        stz     sreg+1
        lda     lev_far
        ldx     lev_far+1
        rts

; void __fastcall__ P_LevRead(uint8_t array, uint16_t index, void *dst, uint16_t len)
; C stack: +0 dst, +2 index, +4 array
_P_LevRead:
        jsr     lev_args
        jmp     far_rd

_P_LevWrite:
        jsr     lev_args
        jmp     far_wr

lev_args:
        sta     far_len
        stx     far_len+1
        ldy     #0
        lda     (sp),y
        sta     far_ptr
        iny
        lda     (sp),y
        sta     far_ptr+1
        iny
        lda     (sp),y
        sta     lev_idx
        iny
        lda     (sp),y
        sta     lev_idx+1
        iny
        lda     (sp),y
        pha
        jsr     incsp5
        pla
        jmp     lev_addr

; ---- sectors -----------------------------------------------------------------------
; P_SetSectorFloor(uint16_t sector, int16_t height): near mirror, then the
; far record's field (offset in Y at sec_set).
_P_SetSectorFloor:
        ldy     #SECTOR_FLOORHEIGHT
        sta     tmp3
        stx     tmp4
        lda     _sec_floorh
        ldx     _sec_floorh+1
        bra     sec_set16

_P_SetSectorCeiling:
        ldy     #SECTOR_CEILINGHEIGHT
        sta     tmp3
        stx     tmp4
        lda     _sec_ceilh
        ldx     _sec_ceilh+1
sec_set16:
        ; ptr2 = the near array; the sector from the C stack
        sta     ptr2
        stx     ptr2+1
        sty     la_off
        jsr     popax
        sta     lev_idx
        stx     lev_idx+1
        ; ptr2 += 2 * sector
        asl     a
        sta     tmp1
        txa
        rol     a
        tax
        lda     tmp1
        clc
        adc     ptr2
        sta     ptr2
        txa
        adc     ptr2+1
        sta     ptr2+1
        lda     tmp3
        sta     (ptr2)
        ldy     #1
        lda     tmp4
        sta     (ptr2),y
        ; the far record: 2 bytes from ptr2
        lda     ptr2
        sta     far_ptr
        lda     ptr2+1
        sta     far_ptr+1
        lda     #2
set_far_field:
        sta     far_len
        stz     far_len+1
        lda     #MAPARR_SECTORS
        jsr     lev_addr
        lda     la_off
        clc
        adc     lev_far
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       jmp     far_wr

; P_SetSectorSpecial(uint16_t sector, uint8_t special)
_P_SetSectorSpecial:
        sta     tmp3
        jsr     popax
        sta     lev_idx
        stx     lev_idx+1
        clc
        adc     _sec_special
        sta     ptr2
        txa
        adc     _sec_special+1
        sta     ptr2+1
        lda     tmp3
        sta     (ptr2)
        lda     ptr2
        sta     far_ptr
        lda     ptr2+1
        sta     far_ptr+1
        lda     #SECTOR_SPECIAL
        sta     la_off
        lda     #1
        bra     set_far_field

.segment "BSS"
la_off:     .res 1
.segment "CODE"

; ---- lines ----------------------------------------------------------------------------
; line_get: A/X = line index -> gli = its cache entry (fetched if needed)
_P_Line:
line_get:
        sta     tmp1
        stx     tmp2
        ; gli = linecache + (index & 63) * 27 = slot*32 - slot*4 - slot
        and     #LINECACHE - 1
        sta     tmp3
        stz     tmp4
        asl     a                       ; slot*2 (< 128)
        asl     a                       ; slot*4 (< 256)
        sta     ptr1                    ; ptr1 = slot*4 (8 bits)
        lda     tmp3
        sta     gli
        stz     gli+1
        ldx     #5
@s32:   asl     gli
        rol     gli+1
        dex
        bne     @s32
        sec
        lda     gli
        sbc     ptr1
        sta     gli
        lda     gli+1
        sbc     #0
        sta     gli+1
        sec
        lda     gli
        sbc     tmp3
        sta     gli
        lda     gli+1
        sbc     #0
        sta     gli+1
        clc
        lda     gli
        adc     #<linecache
        sta     gli
        lda     gli+1
        adc     #>linecache
        sta     gli+1
        ; hit?
        ldy     #LI_INDEX
        lda     (gli),y
        cmp     tmp1
        bne     @fetch
        iny
        lda     (gli),y
        cmp     tmp2
        bne     @fetch
        lda     gli
        ldx     gli+1
        rts
@fetch: lda     tmp1
        sta     lev_idx
        lda     tmp2
        sta     lev_idx+1
        lda     #MAPARR_LINEDEFS
        jsr     lev_addr
        lda     lev_far                 ; + LINEDEF_FLAGS
        clc
        adc     #LINEDEF_FLAGS
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<linebuf
        sta     far_ptr
        lda     #>linebuf
        sta     far_ptr+1
        lda     #<(LINEDEF_BACKSECTOR + 2 - LINEDEF_FLAGS)
        sta     far_len
        stz     far_len+1
        jsr     far_rd
B       = linebuf - LINEDEF_FLAGS       ; B + LINEDEF_x is the record's field
        ldy     #LI_INDEX
        lda     lev_idx
        sta     (gli),y
        iny
        lda     lev_idx+1
        sta     (gli),y
        ldy     #LI_FLAGS
        lda     B + LINEDEF_FLAGS
        sta     (gli),y
        ldy     #LI_SPECIAL
        lda     B + LINEDEF_SPECIAL
        sta     (gli),y
        ldy     #LI_SLOPETYPE
        lda     B + LINEDEF_SLOPETYPE
        sta     (gli),y
.macro copy16 dst, src
        ldy     #dst
        lda     src
        sta     (gli),y
        iny
        lda     src+1
        sta     (gli),y
.endmacro
        copy16  LI_TAG, B + LINEDEF_TAG
        copy16  LI_DX, B + LINEDEF_DX
        copy16  LI_DY, B + LINEDEF_DY
        copy16  LI_BBOX + 2 * BOXTOP, B + LINEDEF_BBOX_TOP
        copy16  LI_BBOX + 2 * BOXBOTTOM, B + LINEDEF_BBOX_BOTTOM
        copy16  LI_BBOX + 2 * BOXLEFT, B + LINEDEF_BBOX_LEFT
        copy16  LI_BBOX + 2 * BOXRIGHT, B + LINEDEF_BBOX_RIGHT
        copy16  LI_FRONTSECTOR, B + LINEDEF_FRONTSECTOR
        copy16  LI_BACKSECTOR, B + LINEDEF_BACKSECTOR
        ; v1 is the corner the line starts from
        lda     B + LINEDEF_DX + 1
        bmi     :+
        copy16  LI_V1X, B + LINEDEF_BBOX_LEFT
        bra     @v1y
:       copy16  LI_V1X, B + LINEDEF_BBOX_RIGHT
@v1y:   lda     B + LINEDEF_DY + 1
        bmi     :+
        copy16  LI_V1Y, B + LINEDEF_BBOX_BOTTOM
        bra     @done
:       copy16  LI_V1Y, B + LINEDEF_BBOX_TOP
@done:  lda     gli
        ldx     gli+1
        rts

; P_SetLineSpecial(uint16_t line, uint8_t special)
_P_SetLineSpecial:
        sta     tmp3
        jsr     popax
        sta     lev_idx
        stx     lev_idx+1
        ; the cache entry, if it holds the line (line_get's slot arithmetic
        ; without the fetch: fetch it anyway, it is about to be used)
        lda     tmp3
        pha
        lda     lev_idx
        ldx     lev_idx+1
        jsr     line_get
        pla
        ldy     #LI_SPECIAL
        sta     (gli),y
        sta     tmp3
        lda     #<tmp3
        sta     far_ptr
        stz     far_ptr+1
        lda     #LINEDEF_SPECIAL
        sta     la_off
        lda     #1
        sta     far_len
        stz     far_len+1
        lda     #MAPARR_LINEDEFS
        jsr     lev_addr
        lda     la_off
        clc
        adc     lev_far
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       jmp     far_wr

; ---- the blockmap's line lists ----------------------------------------------------------
; blk_lines: blk_cell, blk_pos -> A = n lines (<= 16) at blk_buf, blk_pos += n
blk_lines:
        lda     blk_cell
        and     #CELLCACHE - 1
        tax
        lda     cc_key_lo,x
        cmp     blk_cell
        bne     @fetch
        lda     cc_key_hi,x
        cmp     blk_cell+1
        bne     @fetch
        jmp     @serve
@fetch: ; the list's offset: BLOCKMAP[4 + cell]
        lda     blk_cell
        sta     cc_key_lo,x
        lda     blk_cell+1
        sta     cc_key_hi,x
        stz     cc_count,x
        stx     rp_slot
        jsr     cell_offset             ; blk_off = the list's word index
        ; ptr3 = &cc_lines[slot * CELL_LINES * 2]
        jsr     cell_ptr
@chunk: lda     blk_off
        sta     lev_idx
        lda     blk_off+1
        sta     lev_idx+1
        lda     #MAPARR_BLOCKMAP
        jsr     lev_addr
        lda     #<blk_buf
        sta     far_ptr
        lda     #>blk_buf
        sta     far_ptr+1
        lda     #32
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        ldy     #0                      ; Y = byte offset in blk_buf
@word:  lda     blk_buf,y
        and     blk_buf+1,y
        cmp     #$FF
        beq     @fetched
        ldx     rp_slot
        lda     cc_count,x
        cmp     #CELL_LINES
        bne     :+
        lda     #255                    ; too long for the cache
        sta     cc_count,x
        bra     @fetched
:       inc     cc_count,x
        asl     a                       ; 2 * count
        phy
        tay
        pla
        pha
        tax                             ; X = byte offset in blk_buf
        lda     blk_buf,x
        sta     (ptr3),y
        iny
        lda     blk_buf+1,x
        sta     (ptr3),y
        ply
        iny
        iny
        cpy     #32
        bne     @word
        clc
        lda     blk_off
        adc     #16
        sta     blk_off
        bcc     @chunk
        inc     blk_off+1
        bra     @chunk
@fetched:
        ldx     rp_slot
@serve: lda     cc_count,x
        cmp     #255
        beq     @long
        ; from the cache: lines [blk_pos, count), at most 16
        sta     tmp1                    ; count
        stx     rp_slot
        jsr     cell_ptr
        ldx     #0                      ; n
@copy:  lda     blk_pos+1
        bne     @end
        lda     blk_pos
        cmp     tmp1
        bcs     @end
        cpx     #16
        bcs     @end
        asl     a
        tay
        phx
        txa
        asl     a
        tax
        lda     (ptr3),y
        sta     blk_buf,x
        iny
        lda     (ptr3),y
        sta     blk_buf+1,x
        plx
        inx
        inc     blk_pos
        bra     @copy
@end:   txa
        rts
@long:  ; read 16 words from the list at blk_pos, stop at $FFFF
        jsr     cell_offset
        clc
        lda     blk_off
        adc     blk_pos
        sta     lev_idx
        lda     blk_off+1
        adc     blk_pos+1
        sta     lev_idx+1
        lda     #MAPARR_BLOCKMAP
        jsr     lev_addr
        lda     #<blk_buf
        sta     far_ptr
        lda     #>blk_buf
        sta     far_ptr+1
        lda     #32
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        ldx     #0
        ldy     #0
@lw:    lda     blk_buf,y
        and     blk_buf+1,y
        cmp     #$FF
        beq     @lend
        inx
        iny
        iny
        cpy     #32
        bne     @lw
@lend:  txa
        clc
        adc     blk_pos
        sta     blk_pos
        bcc     :+
        inc     blk_pos+1
:       txa
        rts

; blk_off = BLOCKMAP[4 + blk_cell]
cell_offset:
        clc
        lda     blk_cell
        adc     #4
        sta     lev_idx
        lda     blk_cell+1
        adc     #0
        sta     lev_idx+1
        lda     #MAPARR_BLOCKMAP
        jsr     lev_addr
        lda     #<blk_off
        sta     far_ptr
        lda     #>blk_off
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jmp     far_rd

; ptr3 = &cc_lines[rp_slot * CELL_LINES * 2] (54 bytes a slot)
cell_ptr:
        lda     rp_slot
        sta     ptr3
        stz     ptr3+1
        ; * 54 = * 64 - * 8 - * 2
        asl     ptr3
        rol     ptr3+1                  ; *2
        lda     ptr3
        sta     tmp2                    ; *2 (8 bits: slot < 16)
        asl     a
        asl     a
        sta     tmp3                    ; *8 (< 128)
        asl     ptr3
        rol     ptr3+1
        asl     ptr3
        rol     ptr3+1
        asl     ptr3
        rol     ptr3+1
        asl     ptr3
        rol     ptr3+1
        asl     ptr3
        rol     ptr3+1                  ; *64
        sec
        lda     ptr3
        sbc     tmp3
        sta     ptr3
        lda     ptr3+1
        sbc     #0
        sta     ptr3+1
        sec
        lda     ptr3
        sbc     tmp2
        sta     ptr3
        lda     ptr3+1
        sbc     #0
        sta     ptr3+1
        clc
        lda     ptr3
        adc     #<cc_lines
        sta     ptr3
        lda     ptr3+1
        adc     #>cc_lines
        sta     ptr3+1
        rts

; ---- BSP: point in sector ---------------------------------------------------------------------
; uint16_t R_PointInSector(fixed_t x, fixed_t y)
_R_PointInSector:
        sta     rp_y
        stx     rp_y+1
        lda     sreg
        sta     rp_y+2
        lda     sreg+1
        sta     rp_y+3
        ldy     #3
:       lda     (sp),y
        sta     rp_x,y
        dey
        bpl     :-
        jsr     incsp4w
rpis:   lda     _numnodes
        ora     _numnodes+1
        bne     :+
        stz     rp_node
        stz     rp_node+1
        jmp     @sub
:       sec
        lda     _numnodes
        sbc     #1
        sta     rp_node
        lda     _numnodes+1
        sbc     #0
        sta     rp_node+1
@walk:  lda     rp_node+1
        bpl     :+
        jmp     @leaf
:       lda     rp_node
        and     #NODECACHE - 1
        tax
        stx     rp_slot
        lda     nc_key_lo,x
        cmp     rp_node
        bne     @miss
        lda     nc_key_hi,x
        cmp     rp_node+1
        beq     @have
@miss:  lda     rp_node
        sta     nc_key_lo,x
        sta     lev_idx
        lda     rp_node+1
        sta     nc_key_hi,x
        sta     lev_idx+1
        lda     #MAPARR_NODES
        jsr     lev_addr
        lda     #<nodebuf
        sta     far_ptr
        lda     #>nodebuf
        sta     far_ptr+1
        lda     #NODE_CHILD1 + 2
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        ldx     rp_slot
        lda     nodebuf+NODE_X
        sta     nc_x_lo,x
        lda     nodebuf+NODE_X+1
        sta     nc_x_hi,x
        lda     nodebuf+NODE_Y
        sta     nc_y_lo,x
        lda     nodebuf+NODE_Y+1
        sta     nc_y_hi,x
        lda     nodebuf+NODE_DX
        sta     nc_dx_lo,x
        lda     nodebuf+NODE_DX+1
        sta     nc_dx_hi,x
        lda     nodebuf+NODE_DY
        sta     nc_dy_lo,x
        lda     nodebuf+NODE_DY+1
        sta     nc_dy_hi,x
        lda     nodebuf+NODE_CHILD0
        sta     nc_c0_lo,x
        lda     nodebuf+NODE_CHILD0+1
        sta     nc_c0_hi,x
        lda     nodebuf+NODE_CHILD1
        sta     nc_c1_lo,x
        lda     nodebuf+NODE_CHILD1+1
        sta     nc_c1_hi,x
@have:  jsr     point_on_side           ; X = slot -> A = side
        ldx     rp_slot
        cmp     #0
        bne     @back
        lda     nc_c0_lo,x
        sta     rp_node
        lda     nc_c0_hi,x
        sta     rp_node+1
        jmp     @walk
@back:  lda     nc_c1_lo,x
        sta     rp_node
        lda     nc_c1_hi,x
        sta     rp_node+1
        jmp     @walk
@leaf:  lda     rp_node+1
        and     #$7F
        sta     rp_node+1
@sub:   ; the subsector's sector
        lda     rp_node
        and     #SSECCACHE - 1
        tax
        lda     ss_key_lo,x
        cmp     rp_node
        bne     @smiss
        lda     ss_key_hi,x
        cmp     rp_node+1
        beq     @shave
@smiss: stx     rp_slot
        lda     rp_node
        sta     ss_key_lo,x
        sta     lev_idx
        lda     rp_node+1
        sta     ss_key_hi,x
        sta     lev_idx+1
        lda     #MAPARR_SSECTORS
        jsr     lev_addr
        lda     lev_far
        clc
        adc     #SSECTOR_SECTOR
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<ktmp
        sta     far_ptr
        stz     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        ldx     rp_slot
        lda     ktmp
        sta     ss_sec_lo,x
        lda     ktmp+1
        sta     ss_sec_hi,x
@shave: lda     ss_sec_lo,x
        pha
        lda     ss_sec_hi,x
        tax
        pla
        rts

incsp4w:
        clc
        lda     sp
        adc     #4
        sta     sp
        bcc     :+
        inc     sp+1
:       rts

; vanilla R_PointOnSide for node slot X and (rp_x, rp_y) -> A = 0 front, 1 back
point_on_side:
        lda     nc_dx_lo,x
        ora     nc_dx_hi,x
        bne     @notv
        ; vertical: x <= node.x ? dy > 0 : dy < 0
        lda     nc_x_lo,x
        sta     tmp1
        lda     nc_x_hi,x
        sta     tmp2
        jsr     x_le_node               ; C set: rp_x <= FIX(node.x)
        bcc     @vgt
        lda     nc_dy_hi,x              ; dy > 0
        bmi     @zero
        ora     nc_dy_lo,x
        beq     @zero
        bra     @one
@vgt:   lda     nc_dy_hi,x              ; dy < 0
        bmi     @one
        bra     @zero
@notv:  lda     nc_dy_lo,x
        ora     nc_dy_hi,x
        bne     @general
        ; horizontal: y <= node.y ? dx < 0 : dx > 0
        lda     nc_y_lo,x
        sta     tmp1
        lda     nc_y_hi,x
        sta     tmp2
        jsr     y_le_node
        bcc     @hgt
        lda     nc_dx_hi,x
        bmi     @one
        bra     @zero
@hgt:   lda     nc_dx_hi,x
        bmi     @zero
        ora     nc_dx_lo,x
        beq     @zero
        bra     @one
@zero:  lda     #0
        rts
@one:   lda     #1
        rts
@general:
        ; dx = x - FIX(node.x), dy = y - FIX(node.y)
        lda     rp_x
        sta     rp_dx
        lda     rp_x+1
        sta     rp_dx+1
        sec
        lda     rp_x+2
        sbc     nc_x_lo,x
        sta     rp_dx+2
        lda     rp_x+3
        sbc     nc_x_hi,x
        sta     rp_dx+3
        lda     rp_y
        sta     rp_dy
        lda     rp_y+1
        sta     rp_dy+1
        sec
        lda     rp_y+2
        sbc     nc_y_lo,x
        sta     rp_dy+2
        lda     rp_y+3
        sbc     nc_y_hi,x
        sta     rp_dy+3
        ; the sign shortcut
        lda     nc_dy_hi,x
        eor     nc_dx_hi,x
        eor     rp_dx+3
        eor     rp_dy+3
        bpl     @mul
        lda     nc_dy_hi,x
        eor     rp_dx+3
        bmi     @one
        bra     @zero
@mul:   ; left = FixedMul(node.dy, dx), right = FixedMul(dy, node.dx)
        lda     nc_dy_lo,x
        sta     fxa
        lda     nc_dy_hi,x
        sta     fxa+1
        jsr     sext_fxa
        mov32   fxb, rp_dx
        jsr     fx_mul
        mov32   rp_left, fxr
        ldx     rp_slot
        mov32   fxa, rp_dy
        lda     nc_dx_lo,x
        sta     fxb
        lda     nc_dx_hi,x
        sta     fxb+1
        and     #$80
        beq     :+
        lda     #$FF
:       sta     fxb+2
        sta     fxb+3
        jsr     fx_mul
        ldx     rp_slot
        lt32    fxr, rp_left            ; right < left: front
        jmi     @zero
        jmp     @one

; fxa+2, fxa+3 = the sign extension of fxa+1
sext_fxa:
        lda     fxa+1
        and     #$80
        beq     :+
        lda     #$FF
:       sta     fxa+2
        sta     fxa+3
        rts

; C set iff rp_x <= FIX(tmp1:tmp2); keeps X
x_le_node:
        ; compare rp_x (32) with tmp2:tmp1:0:0
        lda     rp_x+3
        cmp     tmp2
        bne     @s
        lda     rp_x+2
        cmp     tmp1
        bne     @u
        lda     rp_x+1
        ora     rp_x
        beq     @le                     ; equal
        clc
        rts
@u:     bcc     @le                     ; unsigned below in the middle byte
        clc
        rts
@s:     ; signed compare of the top bytes
        sec
        sbc     tmp2
        bvc     :+
        eor     #$80
:       bmi     @le
        clc
        rts
@le:    sec
        rts

y_le_node:
        lda     rp_y+3
        cmp     tmp2
        bne     @s
        lda     rp_y+2
        cmp     tmp1
        bne     @u
        lda     rp_y+1
        ora     rp_y
        beq     @le
        clc
        rts
@u:     bcc     @le
        clc
        rts
@s:     sec
        sbc     tmp2
        bvc     :+
        eor     #$80
:       bmi     @le
        clc
        rts
@le:    sec
        rts

; ---- reject -------------------------------------------------------------------------------------
; boolean P_RejectVisible(uint16_t s1, uint16_t s2)
_P_RejectVisible:
        sta     tmp3                    ; s2
        stx     tmp4
        jsr     popax                   ; s1
reject_ax:
        sta     rej_i                   ; s1 (the bit index, >> 3 below)
        stx     rej_i+1
        sta     ptr4
        stx     ptr4+1
        ; a new s2: forget the row
        lda     tmp3
        cmp     rej_s2
        bne     @new
        lda     tmp4
        cmp     rej_s2+1
        beq     @same
@new:   lda     tmp3
        sta     rej_s2
        lda     tmp4
        sta     rej_s2+1
        lda     _rej_known
        sta     ptr1
        lda     _rej_known+1
        sta     ptr1+1
        ; (numsectors + 7) >> 3 bytes
        clc
        lda     _numsectors
        adc     #7
        sta     tmp1
        lda     _numsectors+1
        adc     #0
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        tax                             ; pages
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
        beq     @same
@pb:    dey
        sta     (ptr1),y
        cpy     #0
        bne     @pb
@same:  ; mask = 1 << (s1 & 7), i = s1 >> 3
        lda     ptr4
        and     #7
        tax
        lda     #1
:       cpx     #0
        beq     :+
        asl     a
        dex
        bra     :-
:       sta     rej_mask
        lsr     rej_i+1
        ror     rej_i
        lsr     rej_i+1
        ror     rej_i
        lsr     rej_i+1
        ror     rej_i
        jsr     rej_ptrs
        lda     (ptr1)
        and     rej_mask
        jne     @known
        ; pnum = s1 * numsectors + s2
        stz     rej_pnum
        stz     rej_pnum+1
        stz     rej_pnum+2
        stz     rej_pnum+3
        lda     _numsectors
        sta     tmp1
        lda     _numsectors+1
        sta     tmp2
        stz     sreg                    ; s1 << k in ptr4, sreg (32 bits)
        stz     sreg+1
@m:     lda     tmp1
        ora     tmp2
        beq     @md
        lsr     tmp2
        ror     tmp1
        bcc     @mn
        clc
        lda     rej_pnum
        adc     ptr4
        sta     rej_pnum
        lda     rej_pnum+1
        adc     ptr4+1
        sta     rej_pnum+1
        lda     rej_pnum+2
        adc     sreg
        sta     rej_pnum+2
        lda     rej_pnum+3
        adc     sreg+1
        sta     rej_pnum+3
@mn:    asl     ptr4
        rol     ptr4+1
        rol     sreg
        rol     sreg+1
        bra     @m
@md:    clc
        lda     rej_pnum
        adc     tmp3
        sta     rej_pnum
        lda     rej_pnum+1
        adc     tmp4
        sta     rej_pnum+1
        lda     rej_pnum+2
        adc     #0
        sta     rej_pnum+2
        ; the byte pnum >> 3 of REJECT
        lda     rej_pnum
        and     #7
        pha
        ldx     #3
:       lsr     rej_pnum+2
        ror     rej_pnum+1
        ror     rej_pnum
        dex
        bne     :-
        lda     rej_pnum
        sta     lev_idx
        lda     rej_pnum+1
        sta     lev_idx+1
        lda     #MAPARR_REJECT
        jsr     lev_addr
        lda     #<ktmp
        sta     far_ptr
        stz     far_ptr+1
        lda     #1
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        jsr     rej_ptrs                ; (lev_addr used ptr1)
        ; the bit
        plx
        lda     ktmp
:       cpx     #0
        beq     :+
        lsr     a
        dex
        bra     :-
:       lsr     a                       ; C = the bit
        lda     (ptr1)
        ora     rej_mask
        sta     (ptr1)
        lda     (ptr2)
        bcc     @clear
        ora     rej_mask
        bra     :+
@clear: lda     rej_mask
        eor     #$FF
        and     (ptr2)
:       sta     (ptr2)
@known: lda     (ptr2)
        and     rej_mask
        bne     @no
        lda     #1
        ldx     #0
        rts
@no:    lda     #0
        tax
        rts

; ptr1 = rej_known + rej_i, ptr2 = rej_bits + rej_i
rej_ptrs:
        clc
        lda     _rej_known
        adc     rej_i
        sta     ptr1
        lda     _rej_known+1
        adc     rej_i+1
        sta     ptr1+1
        clc
        lda     _rej_bits
        adc     rej_i
        sta     ptr2
        lda     _rej_bits+1
        adc     rej_i+1
        sta     ptr2+1
        rts

; ---- level start ----------------------------------------------------------------------------------
_P_ClearCaches:
        ldx     #0
@l:     lda     #$FF
        cpx     #NODECACHE
        bcs     :+
        sta     nc_key_lo,x
        sta     nc_key_hi,x
:       cpx     #SSECCACHE
        bcs     :+
        sta     ss_key_lo,x
        sta     ss_key_hi,x
:       cpx     #CELLCACHE
        bcs     :+
        sta     cc_key_lo,x
        sta     cc_key_hi,x
:       inx
        cpx     #NODECACHE
        bne     @l
        ; the line cache: index = $FFFF in every entry
        lda     #<linecache
        sta     ptr1
        lda     #>linecache
        sta     ptr1+1
        ldx     #LINECACHE
@lc:    lda     #$FF
        ldy     #LI_INDEX
        sta     (ptr1),y
        iny
        sta     (ptr1),y
        clc
        lda     ptr1
        adc     #LI_SIZE
        sta     ptr1
        bcc     :+
        inc     ptr1+1
:       dex
        bne     @lc
        lda     #$FF
        sta     rej_s2
        sta     rej_s2+1
        rts
