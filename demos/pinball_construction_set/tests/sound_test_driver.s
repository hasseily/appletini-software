.setcpu "65C02"

; Test driver for tests/test_sound.py: one caller per entry point of
; src/sound.s. Python sets `param`, sets PC to a t_* label and runs until
; PC reaches `halt`. The hook callers load X and Y with marker values and
; store them afterwards in `result` so the test can see they were kept.

.import snd_init, snd_frame, snd_shutdown, snd_effect, snd_mute, snd_speak
.import SND, SOUND, INITSND, INITSOUND

.export param, result, halt
.export t_init, t_frame, t_shutdown, t_effect, t_mute, t_speak
.export t_snd, t_sound, t_initsnd, t_initsound

.segment "BSS"
param:          .res 2
result:         .res 2

.segment "CODE"

halt:
        jmp     halt

t_init:
        jsr     snd_init
        jmp     halt

t_frame:
        jsr     snd_frame
        jmp     halt

t_shutdown:
        jsr     snd_shutdown
        jmp     halt

t_effect:
        lda     param
        jsr     snd_effect
        jmp     halt

t_mute:
        lda     param
        jsr     snd_mute
        jmp     halt

t_speak:
        lda     param
        jsr     snd_speak
        jmp     halt

t_snd:
        ldx     #$5A
        ldy     #$A5
        jsr     SND
        stx     result
        sty     result+1
        jmp     halt

t_sound:
        ldx     #$5A
        ldy     #$A5
        jsr     SOUND
        stx     result
        sty     result+1
        jmp     halt

t_initsnd:
        jsr     INITSND
        jmp     halt

t_initsound:
        jsr     INITSOUND
        jmp     halt
