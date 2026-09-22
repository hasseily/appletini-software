.setcpu "65C02"

; Test driver for tests/test_video.py. It stands in for build/assets.s
; (sprite tables, font, palette live in RAM so Python can fill them) and
; gives every video.s entry point a caller that follows the cc65 fastcall
; convention: earlier arguments pushed with pusha, the last one in A/X.
;
; Python sets the parameter block `param` (8 bytes), sets PC to one of the
; t_* labels, and runs until PC reaches `halt`.

.import _video_init, _video_shutdown, _video_wait_vbl, _video_speed_probe
.import _video_render, _video_clear_playfield, _video_clear_all
.import _video_set_panel_color
.import _panel_text, _panel_text_small, _panel_fill, _panel_dot, _panel_sprite
.import _field_text, _field_text_big
.import pusha
.importzp sp

.export _spr_even_lo, _spr_even_hi, _spr_odd_lo, _spr_odd_hi
.export _spr_width, _spr_height, _spr_bank, _font8, _palette0
.export param, result, sprite_buf, halt
.export t_init, t_shutdown, t_wait_vbl, t_speed_probe, t_render
.export t_clear_playfield, t_clear_all, t_set_panel_color
.export t_panel_text, t_panel_text_small, t_panel_fill, t_panel_dot
.export t_panel_sprite, t_field_text, t_field_text_big

.segment "BSS"
_spr_even_lo:   .res 64
_spr_even_hi:   .res 64
_spr_odd_lo:    .res 64
_spr_odd_hi:    .res 64
_spr_width:     .res 64
_spr_height:    .res 64
_spr_bank:      .res 64
_font8:         .res 512
sprite_buf:     .res 1024
param:          .res 8
result:         .res 2

.segment "RODATA"
_palette0:
        .byte $00,$00, $FF,$0F, $AA,$0A, $55,$05, $00,$0F, $80,$0F, $F0,$0F, $C0,$00
        .byte $FF,$00, $0F,$00, $08,$00, $0F,$0F, $8B,$0F, $40,$08, $60,$00, $BF,$08

.segment "CODE"

; cc65 software stack top at $B800
setup:
        stz     sp
        lda     #$B8
        sta     sp+1
        rts

halt:
        jmp     halt

t_init:
        jsr     setup
        jsr     _video_init
        jmp     halt

t_shutdown:
        jsr     setup
        jsr     _video_shutdown
        jmp     halt

t_wait_vbl:
        jsr     setup
        jsr     _video_wait_vbl
        jmp     halt

t_speed_probe:
        jsr     setup
        jsr     _video_speed_probe
        sta     result
        stx     result+1
        jmp     halt

t_render:
        jsr     setup
        jsr     _video_render
        jmp     halt

t_clear_playfield:
        jsr     setup
        jsr     _video_clear_playfield
        jmp     halt

t_clear_all:
        jsr     setup
        jsr     _video_clear_all
        jmp     halt

; video_set_panel_color(param0)
t_set_panel_color:
        jsr     setup
        lda     param
        jsr     _video_set_panel_color
        jmp     halt

; text(param0, param1, param2, ptr param3/param4)
t_panel_text:
        jsr     setup
        jsr     push3
        jsr     _panel_text
        jmp     halt

t_panel_text_small:
        jsr     setup
        jsr     push3
        jsr     _panel_text_small
        jmp     halt

t_field_text:
        jsr     setup
        jsr     push3
        jsr     _field_text
        jmp     halt

t_field_text_big:
        jsr     setup
        jsr     push3
        jsr     _field_text_big
        jmp     halt

push3:
        lda     param
        jsr     pusha
        lda     param+1
        jsr     pusha
        lda     param+2
        jsr     pusha
        lda     param+3
        ldx     param+4
        rts

; panel_fill(param0, param1, param2, param3, param4)
t_panel_fill:
        jsr     setup
        lda     param
        jsr     pusha
        lda     param+1
        jsr     pusha
        lda     param+2
        jsr     pusha
        lda     param+3
        jsr     pusha
        lda     param+4
        jsr     _panel_fill
        jmp     halt

; panel_dot(param0, param1, param2)
t_panel_dot:
        jsr     setup
        jsr     push2
        jsr     _panel_dot
        jmp     halt

; panel_sprite(param0, param1, param2)
t_panel_sprite:
        jsr     setup
        jsr     push2
        jsr     _panel_sprite
        jmp     halt

push2:
        lda     param
        jsr     pusha
        lda     param+1
        jsr     pusha
        lda     param+2
        rts
