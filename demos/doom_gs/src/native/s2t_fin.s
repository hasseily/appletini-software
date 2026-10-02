; s2t_fin.s: the finale's tic side (docs/SCREENS.md 1.5.6, 4.7; part
; s2fin, docs/m11-parts/s2fin.md). A tic-side module: milestone 10's tic
; image links it and its hooks call it (request R4; GAME.md 4.4's
; conventions: no zero page, A, X, Y changed). Written from upstream's
; src/iigs/f_finale65.s (F_StartFinale, F_Ticker, textSpeed [R
; f_finale65.s:74-148]).
;
;   f_start     F_StartFinale [R :74-86]: gameaction ga_nothing, gamestate
;               GS_FINALE, the automap's AM_ACTIVE off (the frame block's
;               AUTOMAP byte, as request R6's AM_Stop clears it for the
;               renderer), acceleratestage, midstage, finalestage and
;               finalecount 0. The W_StartFinale hook calls it.
;   f_ticker    F_Ticker [R :111-148] after its first call: the F_Ticker
;               hook calls milestone 10's WI_checkForAccelerate (flow's,
;               gwi.s), then f_ticker (request S2FIN-4). finalecount + 1;
;               in the text stage the text's time (its length * speed /
;               100 + the wait) passed, or in the mid stage a new request:
;               the picture (finalestage 1, finalecount 0)
;
; The finale's state is the card's (s2layout's S2T block: F_STAGE, a byte;
; F_COUNT, upstream's int32; F_MID, a byte), so FINW's drawer reads what
; the tic left; acceleratestage is milestone 10's WI_ACCEL (a word).
; Upstream's F_Ticker also sets display's wipegamestate to -1 (a wipe):
; natively the new picture's black step comes from s2_picpal's picturenum
; (s2_pal.s, part s2pal), so nothing is written for it.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "lgame.inc"
        .include "s2fin.inc"

        .export f_start, f_ticker

TEXTSPEED    = 300              ; [R f_finale65.s:18-21]
TEXTWAIT     = 250
NEWTEXTWAIT  = 1000
AM_ACTIVE    = 1                ; [R :22]
T_SLOW       = FIN_E1LENGTH * TEXTSPEED / 100
T_FAST       = FIN_E1LENGTH / 100   ; (NEWTEXTSPEED 1)

        .assert T_SLOW + NEWTEXTWAIT < $8000, error, "the text's time"

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; f_start: F_StartFinale.
; ---------------------------------------------------------------------------
f_start:
        stz G_GAMEACTION        ; (ga_nothing)
        stz G_GAMEACTION+1
        lda #FIN_GS_FINALE
        sta G_GAMESTATE
        stz G_GAMESTATE+1
        lda AUTOMAP
        and #<~AM_ACTIVE
        sta AUTOMAP
        stz WI_ACCEL
        stz WI_ACCEL+1
        stz F_MID
        stz F_STAGE
        ldx #3
:       stz F_COUNT,x
        dex
        bpl :-
        rts

; ---------------------------------------------------------------------------
; f_ticker: F_Ticker after WI_checkForAccelerate.
; ---------------------------------------------------------------------------
f_ticker:
        ldx #0                  ; finalecount + 1 (int32)
:       inc F_COUNT,x
        bne :+
        inx
        cpx #4
        bne :-
:       lda F_STAGE
        bne @r
        jsr speed               ; the text's time: strlen * speed / 100
        ldx #<T_FAST
        ldy #>T_FAST
        bcs :+
        ldx #<T_SLOW
        ldy #>T_SLOW
:       lda F_MID               ; + the wait
        beq @slow
        txa
        clc
        adc #<NEWTEXTWAIT
        tax
        tya
        adc #>NEWTEXTWAIT
        bra @cmp
@slow:  txa
        clc
        adc #<TEXTWAIT
        tax
        tya
        adc #>TEXTWAIT
@cmp:   tay                     ; finalecount > the time (int32): 0:time
        txa                     ;   - finalecount negative
        cmp F_COUNT
        tya
        sbc F_COUNT+1
        lda #0
        sbc F_COUNT+2
        lda #0
        sbc F_COUNT+3
        bvc :+
        eor #$80
:       bmi @pic
        lda F_MID               ; or the mid stage and a request
        beq @r
        lda WI_ACCEL
        ora WI_ACCEL+1
        beq @r
@pic:   ldx #3                  ; the picture
:       stz F_COUNT,x
        dex
        bpl :-
        lda #1
        sta F_STAGE
@r:     rts

; speed: textSpeed [R :94-105]: C set when fast (1), clear when 300. The
; mid stage starts at a request: midstage = acceleratestage (1), and the
; request is taken (acceleratestage 0).
speed:
        lda F_MID
        bne @fast
        lda WI_ACCEL
        ora WI_ACCEL+1
        clc
        beq @r                  ; (midstage stays 0)
        lda #1
        sta F_MID
        stz WI_ACCEL
        stz WI_ACCEL+1
@fast:  sec
@r:     rts
