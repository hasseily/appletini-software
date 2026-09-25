; Hardware performance readout for the resident banked game.
;
; The kernel supplies atomic, monotonically wrapping 16-bit snapshots before
; calling _debug_readout after _game_frame. VBL is actual hardware time. Press
; V to select the 50/60 Hz rate matching the machine's video standard. This
; also controls the game scheduler; no CPU-frequency or per-video-write
; timing model enters the rates.
; A sample spans at least two seconds. The displayed tenths are floor(delta *
; Hz * 10 / elapsed), including game, rendering, banking and presentation work.
;
; The path/intercept scratch is dead here. Only that buffer and this module's
; small BSS are touched. Text goes directly to auxiliary bank 0, rows 88..94;
; the renderer's 84-row viewport and its main-memory workspace are untouched.

.setcpu "65C02"
.include "zeropage.inc"

.ifndef VIDEO_HZ
VIDEO_HZ = 60
.endif
.assert (VIDEO_HZ = 50) .or (VIDEO_HZ = 60), error, "VIDEO_HZ must be 50 or 60"

.ifdef BANKED_GAME
.globalzp far_dst, far_ptr, far_len
.import kjt_far_write, _intercepts, _kin
.export _debug_readout, _debug_vbl, _debug_tics, _debug_frames
.export _debug_fps10, _debug_tps10, _debug_updates, _debug_hz

DEBUG_FG = 4                         ; converted PLAYPAL: white
DEBUG_BG = 0                         ; converted PLAYPAL: black
DEBUG_FONT_WIDTH = 5
DEBUG_CHAR_WIDTH = 6
DEBUG_CHARS = 24
DEBUG_LEFT = (320 - DEBUG_CHARS * DEBUG_CHAR_WIDTH) / 2
DEBUG_SCREEN = $2000 + 88 * 320
GLYPH_F = 10
GLYPH_P = 11
GLYPH_S = 12
GLYPH_T = 13
GLYPH_DOT = 14
GLYPH_DASH = 15
GLYPH_SPACE = 16
GLYPH_H = 17
GLYPH_Z = 18
GLYPHS = 19

.segment "BSS"
debug_bss_start:
_debug_vbl:     .res 2
_debug_tics:    .res 2
_debug_frames:  .res 2
_debug_fps10:   .res 2
_debug_tps10:   .res 2
_debug_updates: .res 2
previous_vbl:   .res 2
previous_tics:  .res 2
previous_frames:.res 2
elapsed:        .res 2
initialized:    .res 1
_debug_hz:      .res 1
last_v:         .res 1
number:         .res 4
multiplicand:   .res 4
multiplier:     .res 2
remainder:      .res 3
iterations:     .res 1
text_line:      .res DEBUG_CHARS
draw_row:       .res 1
draw_char:      .res 1
draw_address:   .res 2
digit_place:    .res 1
digit:          .res 1
.assert * - debug_bss_start <= 80, error, "debug readout near BSS budget exceeded"

.segment "RODATA"
text_template:
        .byte GLYPH_F, GLYPH_P, GLYPH_S, GLYPH_SPACE
        .byte GLYPH_SPACE, GLYPH_DASH, GLYPH_DASH, GLYPH_DOT, GLYPH_DASH
        .byte GLYPH_SPACE, GLYPH_T, GLYPH_P, GLYPH_S, GLYPH_SPACE
        .byte GLYPH_SPACE, GLYPH_DASH, GLYPH_DASH, GLYPH_DOT, GLYPH_DASH
        .byte GLYPH_SPACE, VIDEO_HZ / 10, 0, GLYPH_H, GLYPH_Z
places_lo: .byte <1000, <100, <10, <1
places_hi: .byte >1000, >100, >10, >1

; Five high bits are the pixels, in glyph order 0..9 F P S T . - space H Z.
; Rows are adjacent so the scanline renderer needs one table pointer per row.
font:
        .byte $70,$20,$70,$F0,$10,$F8,$70,$F8,$70,$70,$F8,$F0,$78,$F8,$00,$00,$00,$88,$F8
        .byte $88,$60,$88,$08,$30,$80,$80,$08,$88,$88,$80,$88,$80,$20,$00,$00,$00,$88,$08
        .byte $98,$20,$08,$08,$50,$80,$80,$10,$88,$88,$80,$88,$80,$20,$00,$00,$00,$88,$10
        .byte $A8,$20,$10,$70,$90,$F0,$F0,$20,$70,$78,$F0,$F0,$70,$20,$00,$F8,$00,$F8,$20
        .byte $C8,$20,$20,$08,$F8,$08,$88,$40,$88,$08,$80,$80,$08,$20,$00,$00,$00,$88,$40
        .byte $88,$20,$40,$08,$10,$08,$88,$40,$88,$08,$80,$80,$08,$20,$00,$00,$00,$88,$80
        .byte $70,$70,$F8,$F0,$10,$F0,$70,$40,$70,$70,$80,$80,$F0,$20,$20,$00,$00,$88,$F8

.segment "CODE"
_debug_readout:
        lda     initialized
        bne     @key
        inc     initialized
        lda     #VIDEO_HZ
        sta     _debug_hz
@reset:
        ldx     #DEBUG_CHARS-1
@template:
        lda     text_template,x
        sta     text_line,x
        dex
        bpl     @template
        ldx     #6
        lda     _debug_hz
        cmp     #60
        beq     :+
        dex
:       stx     text_line+20
        stz     _debug_fps10
        stz     _debug_fps10+1
        stz     _debug_tps10
        stz     _debug_tps10+1
        jsr     save_baseline
        jmp     draw_readout
@key:
        lda     _kin+4
        cmp     #'V'
        bne     @released
        lda     last_v
        bne     @sample
        inc     last_v
        lda     _debug_hz
        eor     #(50 ^ 60)
        sta     _debug_hz
        bra     @reset
@released:
        stz     last_v
@sample:
        sec
        lda     _debug_vbl
        sbc     previous_vbl
        sta     elapsed
        lda     _debug_vbl+1
        sbc     previous_vbl+1
        sta     elapsed+1
        bne     @ready
        lda     _debug_hz
        asl     a
        sta     tmp1
        lda     elapsed
        cmp     tmp1
        bcs     @ready
        rts
@ready:
        sec
        lda     _debug_frames
        sbc     previous_frames
        sta     multiplicand
        lda     _debug_frames+1
        sbc     previous_frames+1
        sta     multiplicand+1
        jsr     calculate_rate
        lda     number
        sta     _debug_fps10
        lda     number+1
        sta     _debug_fps10+1
        ldx     #4
        jsr     format_rate
        sec
        lda     _debug_tics
        sbc     previous_tics
        sta     multiplicand
        lda     _debug_tics+1
        sbc     previous_tics+1
        sta     multiplicand+1
        jsr     calculate_rate
        lda     number
        sta     _debug_tps10
        lda     number+1
        sta     _debug_tps10+1
        ldx     #14
        jsr     format_rate
        inc     _debug_updates
        bne     :+
        inc     _debug_updates+1
:       jsr     save_baseline
        jmp     draw_readout

save_baseline:
        ldx     #1
:       lda     _debug_vbl,x
        sta     previous_vbl,x
        lda     _debug_tics,x
        sta     previous_tics,x
        lda     _debug_frames,x
        sta     previous_frames,x
        dex
        bpl     :-
        rts

; multiplicand[0..1] is the unsigned counter delta; elapsed is >= Hz * 2.
; number becomes min(9999, floor(delta * Hz * 10 / elapsed)). Full-width multiply
; and restoring division keep long render stalls and counter wrap exact.
calculate_rate:
        stz     multiplicand+2
        stz     multiplicand+3
        stz     number
        stz     number+1
        stz     number+2
        stz     number+3
        lda     #<600
        sta     multiplier
        lda     #>600
        sta     multiplier+1
        lda     _debug_hz
        cmp     #60
        beq     @multiply
        lda     #<500
        sta     multiplier
        lda     #>500
        sta     multiplier+1
@multiply:
        lsr     multiplier+1
        ror     multiplier
        bcc     @shift
        clc
        lda     number
        adc     multiplicand
        sta     number
        lda     number+1
        adc     multiplicand+1
        sta     number+1
        lda     number+2
        adc     multiplicand+2
        sta     number+2
        lda     number+3
        adc     multiplicand+3
        sta     number+3
@shift:
        asl     multiplicand
        rol     multiplicand+1
        rol     multiplicand+2
        rol     multiplicand+3
        lda     multiplier
        ora     multiplier+1
        bne     @multiply
        stz     remainder
        stz     remainder+1
        stz     remainder+2
        lda     #32
        sta     iterations
@divide:
        asl     number
        rol     number+1
        rol     number+2
        rol     number+3
        rol     remainder
        rol     remainder+1
        rol     remainder+2
        lda     remainder+2
        bne     @subtract
        lda     remainder+1
        cmp     elapsed+1
        bcc     @next_bit
        bne     @subtract
        lda     remainder
        cmp     elapsed
        bcc     @next_bit
@subtract:
        sec
        lda     remainder
        sbc     elapsed
        sta     remainder
        lda     remainder+1
        sbc     elapsed+1
        sta     remainder+1
        lda     remainder+2
        sbc     #0
        sta     remainder+2
        inc     number                     ; the newly shifted low bit is zero
@next_bit:
        dec     iterations
        bne     @divide
        lda     number+2
        ora     number+3
        bne     @clamp
        lda     number+1
        cmp     #>9999
        bcc     @done
        bne     @clamp
        lda     number
        cmp     #<9999
        bcc     @done
@clamp:
        lda     #<9999
        sta     number
        lda     #>9999
        sta     number+1
@done:  rts

; Format the four decimal digits of number[0..1] at text_line+X, keeping
; the existing decimal point between the third and fourth digits.
format_rate:
        stz     digit_place
@place:
        stz     digit
        ldy     digit_place
@subtract:
        lda     number+1
        cmp     places_hi,y
        bcc     @put
        bne     @take
        lda     number
        cmp     places_lo,y
        bcc     @put
@take:
        sec
        lda     number
        sbc     places_lo,y
        sta     number
        lda     number+1
        sbc     places_hi,y
        sta     number+1
        inc     digit
        bra     @subtract
@put:
        lda     digit
        sta     text_line,x
        inx
        inc     digit_place
        lda     digit_place
        cmp     #3
        bne     :+
        inx                             ; leave the decimal point intact
:       cmp     #4
        bne     @place
        ; Suppress only leading hundreds/tens, retaining the units digit.
        txa
        sec
        sbc     #5
        tax
        lda     text_line,x
        bne     @done
        lda     #GLYPH_SPACE
        sta     text_line,x
        inx
        lda     text_line,x
        bne     @done
        lda     #GLYPH_SPACE
        sta     text_line,x
@done:  rts

draw_readout:
        stz     draw_row
        lda     #<DEBUG_SCREEN
        sta     draw_address
        lda     #>DEBUG_SCREEN
        sta     draw_address+1
@row:
        lda     #DEBUG_BG
        ldx     #0
@clear_page:
        sta     _intercepts,x
        inx
        bne     @clear_page
        ldx     #63
@clear_tail:
        sta     _intercepts+256,x
        dex
        bpl     @clear_tail
        lda     #<(_intercepts + DEBUG_LEFT)
        sta     ptr1
        lda     #>(_intercepts + DEBUG_LEFT)
        sta     ptr1+1
        ; ptr2 = font + draw_row * GLYPHS (19 = 16 + 2 + 1).
        lda     draw_row
        asl     a
        sta     tmp1
        asl     a
        asl     a
        asl     a
        clc
        adc     tmp1
        clc
        adc     draw_row
        clc
        adc     #<font
        sta     ptr2
        lda     #>font
        adc     #0
        sta     ptr2+1
        stz     draw_char
@character:
        ldx     draw_char
        ldy     text_line,x
        lda     (ptr2),y
        sta     tmp1
        ldy     #0
@pixel:
        asl     tmp1
        bcc     :+
        lda     #DEBUG_FG
        sta     (ptr1),y
:       iny
        cpy     #DEBUG_FONT_WIDTH
        bne     @pixel
        clc
        lda     ptr1
        adc     #DEBUG_CHAR_WIDTH
        sta     ptr1
        bcc     :+
        inc     ptr1+1
:       inc     draw_char
        lda     draw_char
        cmp     #DEBUG_CHARS
        bne     @character
        ; The bank gateway may clobber every temporary. Rebuild all far
        ; arguments and pointers per row; persistent loop state is in BSS.
        lda     draw_address
        sta     far_dst
        lda     draw_address+1
        sta     far_dst+1
        stz     far_dst+2
        lda     #<_intercepts
        sta     far_ptr
        lda     #>_intercepts
        sta     far_ptr+1
        lda     #<320
        sta     far_len
        lda     #>320
        sta     far_len+1
        jsr     kjt_far_write
        clc
        lda     draw_address
        adc     #<320
        sta     draw_address
        lda     draw_address+1
        adc     #>320
        sta     draw_address+1
        inc     draw_row
        lda     draw_row
        cmp     #7
        beq     @done
        jmp     @row
@done:  rts
.endif
