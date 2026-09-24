; Pinball Construction Set for the Appletini -- start-up, mode glue.
;
; main: initialise the hardware drivers, install the default table in the
; object database, show the title, enter the editor (EDIT.S START). The
; editor never returns; it calls the kits through the entry points below,
; which replace the disk overlay swaps of the original (SWAP.S):
;   SWAP_SWAPWIRE  run the wiring kit (WIRE.S START), back to DRAWKIT
;   SWAP_SWAPDISK  run the file menu (files.s), back to REEDIT
;   DRAWLOGO / SAVELOGO   the logo band (a sprite; nothing to save)
;   MOVESLIDE      the world screen's slider (scale + knob redrawn)
;   DRAWWIRE       a wire of the wiring kit (rendered list)
;   MAGSTART       the magnifier (magnify.s)
; Zero page: the upstream's variables the replaced routines used.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch
.include "assets.inc"

.export main, SWAP_SWAPWIRE, SWAP_SWAPDISK, DRAWLOGO, SAVELOGO, MOVESLIDE, DRAWWIRE
.export mailbox_init, default_table_install, table_normalise
.import kind_tmpl_lo, kind_tmpl_hi, kind_len, kind_loff, kind_spr0, kind_frames
.import spr_dir
.import PBDATA
.import video_init, rd_init, input_init, snd_init, set_text_color, frame_step
.import panel_sprite, ps_id, ps_x, ps_y
.import blit_sprite, sprite_bank, copy_arena, fill_arena
.import bl_id, bl_x, bl_y, bl_cx0, bl_cx1, bl_cy0, bl_cy1
.import arena_stride, cp_x0, cp_y0, cp_w, cp_rows
.import aux_fetch_rows, af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.import spr_w, spr_h
.import cur_hide, wire_toggle, wire_clear, rd_mark_all
.importzp R_A, R_B, R_C
.import EDIT_START, EDIT_DRAWKIT, EDIT_REEDIT, EDIT_SLDXDY
.import WIRE_START, WIRE_TIMES15
.import PPAK_GETOBJ, PPAK_GETBOUNDS
.import files_menu, title_show
.import default_table, default_table_len
.import PBBASE

; WIRE.S / EDIT.S zero page used by the replaced routines
CUROBJ   = $A9                  ; WIRE: the selected gate (1..6) or object
SLB      = $C0                  ; EDIT world screen: slider record pointer
SLOLD    = $C2
SLNEW    = $C3

.segment "ZEROPAGE"
M_PTR:  .res 2
.segment "BSS"
lg_left: .res 1                 ; logo rows still to draw
sl_knob: .res 1                 ; MOVESLIDE: the knob's row

.segment "CODE"

main:
        jsr     mailbox_init
        jsr     video_init
        jsr     rd_init
        jsr     input_init
        jsr     snd_init
        lda     #COL_TEXT
        jsr     set_text_color
        jsr     default_table_install
        jsr     title_show
        lda     #1
        sta     MB_STATE
        jmp     EDIT_START

mailbox_init:
        ldx     #MB_SIZE-1
:       stz     MAILBOX,x
        dex
        bpl     :-
        lda     #'P'
        sta     MB_MAGIC
        lda     #'C'
        sta     MB_MAGIC+1
        lda     #'S'
        sta     MB_MAGIC+2
        lda     #'1'
        sta     MB_MAGIC+3
        rts

; default_table_install: copy the built-in table (LOGIC, WSET, PBDATA) to
; the database and resolve its L-records.
default_table_install:
        jsr     copy_default
        jmp     table_normalise

copy_default:
        lda     #<default_table
        sta     M_PTR
        lda     #>default_table
        sta     M_PTR+1
        lda     #<PBBASE
        sta     PARAM
        lda     #>PBBASE
        sta     PARAM+1
        ldx     default_table_len+1
        ldy     default_table_len
        ; copy X*256+Y bytes
@page:  cpx     #0
        beq     @rest
        phy
        ldy     #0
:       lda     (M_PTR),y
        sta     (PARAM),y
        iny
        bne     :-
        inc     M_PTR+1
        inc     PARAM+1
        dex
        ply
        bra     @page
@rest:  cpy     #0
        beq     @done
        sty     XTEMP                   ; up to 255 bytes: count up
        ldy     #0
:       lda     (M_PTR),y
        sta     (PARAM),y
        iny
        cpy     XTEMP
        bne     :-
@done:  rts

; ---------------------------------------------------------------------------
; The kits. EDIT calls these with JSR and never expects a return (the
; original jumped back into the editor), so the return address is dropped.
; ---------------------------------------------------------------------------
SWAP_SWAPWIRE:
        pla
        pla
        lda     #MB_ST_WIRE
        sta     MB_STATE
        jsr     WIRE_START
        jsr     wire_clear
        lda     #MB_ST_EDIT
        sta     MB_STATE
        jmp     EDIT_DRAWKIT

SWAP_SWAPDISK:
        pla
        pla
        lda     #7
        sta     MB_STATE
        jsr     files_menu
        lda     #1
        sta     MB_STATE
        jmp     EDIT_REEDIT

; the logo band
; The logo is a raw-row picture in RamWorks bank 1 (SPR_BANK_RW1): its rows
; are fetched into the arena LOGO_PASS at a time and copied to the panel.
LOGO_X    = 160
LOGO_Y    = 2
LOGO_PASS = 12                          ; rows per arena pass (12 x 80 <= 1001)
DRAWLOGO:
        jsr     cur_hide
        lda     spr_dir+4*SPR_LOGO
        sta     af_src
        lda     spr_dir+4*SPR_LOGO+1
        sta     af_src+1
        lda     #<ARENA
        sta     af_dst
        lda     #>ARENA
        sta     af_dst+1
        lda     #1
        sta     af_bank
        lda     spr_w+SPR_LOGO
        inc     a
        lsr     a                       ; bytes per row
        sta     af_len
        sta     af_sstride
        sta     af_dstride
        sta     arena_stride
        sta     cp_w
        stz     af_sstride+1
        lda     #<LOGO_X
        sta     cp_x0
        lda     #>LOGO_X
        sta     cp_x0+1
        lda     #LOGO_Y
        sta     cp_y0
        lda     spr_h+SPR_LOGO
        sta     lg_left
@pass:  lda     lg_left
        cmp     #LOGO_PASS
        bcc     :+
        lda     #LOGO_PASS
:       sta     af_rows
        sta     cp_rows
        jsr     aux_fetch_rows
        jsr     copy_arena
        ; next band: af_src += rows * bytes per row
        ldx     cp_rows
@adv:   lda     af_src
        clc
        adc     af_len
        sta     af_src
        bcc     :+
        inc     af_src+1
:       dex
        bne     @adv
        lda     cp_y0
        clc
        adc     cp_rows
        sta     cp_y0
        lda     lg_left
        sec
        sbc     cp_rows
        sta     lg_left
        bne     @pass
        rts

SAVELOGO:
        rts

; ---------------------------------------------------------------------------
; MOVESLIDE (EDIT world screen): SLB = the slider's record, SLNEW = the new
; setting 0..7. Redraw the scale with the knob at y + SLDXDY[SLNEW]; the
; original animated the knob through the intermediate positions. YTEMP is
; restored on exit as the original did.
; ---------------------------------------------------------------------------
MOVESLIDE:
        jsr     cur_hide
        ldy     #3
        lda     (SLB),y                 ; x lo
        sta     bl_x
        sta     ps_x
        iny
        lda     (SLB),y
        sta     bl_x+1
        ldy     #2
        lda     (SLB),y                 ; y
        sta     bl_y
        stz     bl_y+1
        sta     bl_cy0
        ldx     #SPR_SLIDE_SCALE
        stx     bl_id
        lda     bl_y
        clc
        adc     #SLIDE_H-1
        sta     bl_cy1
        lda     bl_x
        and     #$FE
        sta     bl_cx0
        sta     cp_x0
        lda     bl_x+1
        sta     bl_cx0+1
        sta     cp_x0+1
        lda     #SLIDE_BYTES
        sta     arena_stride
        sta     cp_w
        asl     a
        clc
        adc     bl_cx0
        sta     bl_cx1
        lda     bl_cx0+1
        adc     #0
        sta     bl_cx1+1
        lda     bl_cx1
        bne     :+
        dec     bl_cx1+1
:       dec     bl_cx1
        lda     #COL_PANEL*$11
        jsr     fill_arena
        ; the knob at y + SLDXDY[SLNEW] (read here: SLNEW is in the main
        ; zero page, unreachable once ALTZP is on)
        ldy     SLNEW
        lda     EDIT_SLDXDY,y
        clc
        adc     bl_cy0
        sta     sl_knob
        sta     ALTZPON
        lda     #SPR_SLIDE_SCALE
        jsr     sprite_bank
        jsr     blit_sprite
        lda     sl_knob
        sta     bl_y
        lda     #SPR_SLIDE_KNOB
        sta     bl_id
        jsr     sprite_bank
        jsr     blit_sprite
        sta     ALTZPOFF
        lda     bl_cy0
        sta     cp_y0
        lda     #SLIDE_H
        sta     cp_rows
        jsr     copy_arena
        lda     SLNEW
        sta     SLOLD
        ldy     YTEMP
        rts

SLIDE_H     = 28                ; the scale sprite: 14 x 28
SLIDE_BYTES = 8                 ; 14 pixels + odd phase

; ---------------------------------------------------------------------------
; DRAWWIRE (WIRE): A = object index, Y = the contact row offset (2, 7 or
; 12) inside gate CUROBJ's 15-row slot. Wire: from the object's top-right
; corner to x = 160 at the contact row. Drawing twice removes it.
; ---------------------------------------------------------------------------
DRAWWIRE:
        sty     R_C
        tay
        jsr     PPAK_GETOBJ
        jsr     PPAK_GETBOUNDS          ; PARAM: minY, maxY, minX, maxX
        lda     PARAM+3
        sta     R_A                     ; x1
        lda     PARAM
        sta     R_B                     ; y1
        ldy     CUROBJ
        lda     WIRE_TIMES15-1,y
        clc
        adc     R_C
        sta     R_C                     ; y2
        jmp     wire_toggle

; ---------------------------------------------------------------------------
; table_normalise: the database holds a table as stored on disk: every
; L-record's bytes 0-1 are (kind, frame). Rewrite them as the sprite
; directory pointer of that frame and copy bytes 5-7 (box and stride) and
; 10-15 (RUN/INIT/HIT vectors) from the kind's template. Bytes 2-4 (y, x),
; 8-9 (TIME mask, score/noise) and 16+ (state) are the file's.
; ---------------------------------------------------------------------------
.segment "ZEROPAGE"
N_OBJ:  .res 2
N_TPL:  .res 2
.segment "CODE"
table_normalise:
        lda     #<PBDATA
        sta     N_OBJ
        lda     #>PBDATA
        sta     N_OBJ+1
        lda     PBDATA
        jeq     @done
        sta     TEMP2                   ; objects left
        clc
        adc     #1
        adc     N_OBJ
        sta     N_OBJ
        bcc     :+
        inc     N_OBJ+1
:       ldx     #0
@obj:   stx     TEMP                    ; object index
        lda     (N_OBJ)
        cmp     #OBJ_LIBOBJ
        bne     @next
        ; L-record at + 3 + 2n
        ldy     #2
        lda     (N_OBJ),y
        asl     a
        adc     #3
        clc
        adc     N_OBJ
        sta     M_PTR
        lda     N_OBJ+1
        adc     #0
        sta     M_PTR+1
        lda     (M_PTR)                 ; kind
        cmp     #KIND_COUNT
        bcs     @next
        tax
        ; template L-record = kind_tmpl + kind_loff
        lda     kind_tmpl_lo,x
        clc
        adc     kind_loff,x
        sta     N_TPL
        lda     kind_tmpl_hi,x
        adc     #0
        sta     N_TPL+1
        ; sprite pointer = spr_dir + 4 * (spr0 + frame)
        ldy     #1
        lda     (M_PTR),y               ; frame
        cmp     kind_frames,x
        bcc     :+
        lda     #0
:       clc
        adc     kind_spr0,x
        sta     XTEMP
        stz     YTEMP
        asl     XTEMP
        rol     YTEMP
        asl     XTEMP
        rol     YTEMP
        lda     XTEMP
        clc
        adc     #<spr_dir
        sta     (M_PTR)
        lda     YTEMP
        adc     #>spr_dir
        ldy     #1
        sta     (M_PTR),y
        ; bytes 5-7 and 10-15 from the template
        ldy     #5
:       lda     (N_TPL),y
        sta     (M_PTR),y
        iny
        cpy     #8
        bcc     :-
        ldy     #10
:       lda     (N_TPL),y
        sta     (M_PTR),y
        iny
        cpy     #16
        bcc     :-
@next:  ldx     TEMP
        lda     PBDATA+1,x
        clc
        adc     N_OBJ
        sta     N_OBJ
        bcc     :+
        inc     N_OBJ+1
:       inx
        dec     TEMP2
        jne     @obj
@done:  rts
