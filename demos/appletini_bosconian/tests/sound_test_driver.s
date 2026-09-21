.setcpu "65C02"

; Test driver for tests/test_sound.py. Gives every sound.c entry point a
; caller that follows the cc65 fastcall convention (the only argument
; arrives in A). Python sets `param`, sets PC to one of the t_* labels and
; runs until PC reaches `halt`. u8 results land in `result`.

.import _sound_init, _sound_update, _sound_music, _sound_tempo
.import _sound_sfx, _speech_say, _speech_busy
.importzp sp

.export param, result, halt
.export t_init, t_update, t_music, t_tempo, t_sfx, t_say, t_busy

.segment "BSS"
param:          .res 8
result:         .res 2

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
        jsr     _sound_init
        jmp     halt

t_update:
        jsr     setup
        jsr     _sound_update
        jmp     halt

t_music:
        jsr     setup
        lda     param
        jsr     _sound_music
        jmp     halt

t_tempo:
        jsr     setup
        lda     param
        jsr     _sound_tempo
        jmp     halt

t_sfx:
        jsr     setup
        lda     param
        jsr     _sound_sfx
        jmp     halt

t_say:
        jsr     setup
        lda     param
        jsr     _speech_say
        jmp     halt

t_busy:
        jsr     setup
        jsr     _speech_busy
        sta     result
        stx     result+1
        jmp     halt
