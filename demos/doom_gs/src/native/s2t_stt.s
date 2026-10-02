; s2t_stt.s: part s2stbar's test image glue for the tic side
; (docs/m11-parts/s2stbar.md). Not part of the game: it gives s2t_st.s
; what milestone 10's tic image will (the callback s2t_pos, the scratch
; block st_sb) and runs its cases.
;
; tools/native/s2stbar.py stages the cases in RamWorks:
;
;   banks T_TIC+    case k at bank T_TIC + k / TICS_A_BANK, $0200 +
;                   (k % TICS_A_BANK) * $100: +$00 the card's S2T block
;                   (61), +$40 the player (G_PLAYER, 148), +$D8 M_Random's
;                   value, +$D9 the call (0 st_ticker, 1 st_start, 2
;                   st_init), +$DA P_FPS, +$DB newpal before, +$E0 the
;                   positions: two handles, each with x, y, angle (2 + 12
;                   bytes each)
;   banks T_RES+    case k's result at bank T_RES + k / RES_A_BANK, $0200
;                   + (k % RES_A_BANK) * $80: +$00 the card's S2T block,
;                   +$40 P2DW's state block's P_OLDREADY .. P_STPALETTE
;                   (43) in S2STATE, +$6C newpal in S2STATE
;
;   stt_run     A = the first case / 256, X = the first case % 256, Y =
;               the count: each case's inputs into their places (P_FPS
;               and newpal into S2STATE), its call in the cost phase 30
;               alone, its result out
;   s2t_pos     the callback: A, X a handle: GT_POS its x, y, angle from
;               the case's two (a BRK for another)
;
; Zero page $80-$87.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2stbar.inc"

        .export stt_run, s2t_pos, st_sb, stt_marker
        .import st_ticker, st_start, st_init, far_get, far_put, mt_init

T_TIC      = 40
T_RES      = 70
TICS_A_BANK = 188               ; ($0200-$BFFF) / $100
RES_A_BANK = 376                ; ($0200-$BFFF) / $80
P2DW_BLOCK = PALST_W + PALST_SIZE

C_PLAYER   = $40
C_RND      = $D8
C_OP       = $D9
C_FPS      = $DA
C_NEWPAL   = $DB
C_POS      = $E0

T_K        = $80                ; (2) the case
T_N        = $82                ; (2) the count left
T_B        = $84
T_O        = $85                ; (2)

        .segment "S2CODE"

stt_run:
        stz PHASE
        sta T_K+1
        stx T_K
        sty T_N
        jsr mt_init
@case:  lda T_K
        sta stt_marker
        lda T_K+1
        sta stt_marker+1
        jsr locate              ; the case into buf
        lda #<buf
        sta FA_DST
        lda #>buf
        sta FA_DST+1
        stz FA_N
        jsr far_get
        ldx #S2T_SIZE - 1       ; the card's block, the player
:       lda buf,x
        sta S2T_BASE,x
        dex
        bpl :-
        ldx #0
:       lda buf + C_PLAYER,x
        sta G_PLAYER,x
        inx
        cpx #148
        bne :-
        lda buf + C_FPS         ; P_FPS, newpal into S2STATE
        ldx #<(SS_P2DW + P_FPS - P2DW_BLOCK)
        ldy #>(SS_P2DW + P_FPS - P2DW_BLOCK)
        jsr put1
        lda buf + C_NEWPAL
        ldx #<(SS_PALST + PS_NEWPAL)
        ldy #>(SS_PALST + PS_NEWPAL)
        jsr put1
        lda #PHV_2D
        sta PHASE
        lda buf + C_OP
        beq @tick
        cmp #1
        beq @start
        jsr st_init
        bra @done
@start: jsr st_start
        bra @done
@tick:  lda buf + C_RND
        jsr st_ticker
@done:  stz PHASE
        ldx #S2T_SIZE - 1       ; the result: the card's block
:       lda S2T_BASE,x
        sta buf,x
        dex
        bpl :-
        lda #<(SS_P2DW + P_OLDREADY - P2DW_BLOCK)   ; P2DW's state's
        sta FA_SRC                                  ;   old values and
        lda #>(SS_P2DW + P_OLDREADY - P2DW_BLOCK)   ;   st_palette
        sta FA_SRC+1
        lda #<(buf + $40)
        sta FA_DST
        lda #>(buf + $40)
        sta FA_DST+1
        lda #P_STPALETTE + 1 - P_OLDREADY
        sta FA_N
        lda #S2STATE
        sta FA_BANK
        jsr far_get
        lda #<(SS_PALST + PS_NEWPAL)
        sta FA_SRC
        lda #>(SS_PALST + PS_NEWPAL)
        sta FA_SRC+1
        lda #<(buf + $6C)
        sta FA_DST
        lda #>(buf + $6C)
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        jsr result              ; the result out
        lda #<buf
        sta FA_SRC
        lda #>buf
        sta FA_SRC+1
        lda #$80
        sta FA_N
        jsr far_put
        inc T_K
        bne :+
        inc T_K+1
:       dec T_N
        beq :+
        jmp @case
:       rts

; locate: FA_BANK, FA_SRC = case T_K's place
locate: lda T_K                 ; T_K / 188, T_K % 188
        sta T_O
        lda T_K+1
        sta T_O+1
        lda #T_TIC
        sta T_B
:       lda T_O+1
        bne :+
        lda T_O
        cmp #TICS_A_BANK
        bcc :++
:       sec
        lda T_O
        sbc #TICS_A_BANK
        sta T_O
        lda T_O+1
        sbc #0
        sta T_O+1
        inc T_B
        bra :--
:       lda T_B
        sta FA_BANK
        lda T_O
        clc
        adc #2
        sta FA_SRC+1
        stz FA_SRC
        rts

; result: FA_BANK, FA_DST = case T_K's result place
result: lda T_K
        sta T_O
        lda T_K+1
        sta T_O+1
        lda #T_RES
        sta T_B
:       lda T_O+1               ; T_O < 376?
        cmp #>RES_A_BANK
        bcc :++
        bne :+
        lda T_O
        cmp #<RES_A_BANK
        bcc :++
:       sec
        lda T_O
        sbc #<RES_A_BANK
        sta T_O
        lda T_O+1
        sbc #>RES_A_BANK
        sta T_O+1
        inc T_B
        bra :--
:       lda T_B
        sta FA_BANK
        lda T_O                 ; $0200 + T_O * $80
        lsr T_O+1
        ror a
        sta FA_DST+1
        lda #0
        ror a
        sta FA_DST
        lda FA_DST+1
        clc
        adc #2
        sta FA_DST+1
        rts

; put1: A into S2STATE at X (low), Y (high)
put1:   sta one
        stx FA_DST
        sty FA_DST+1
        lda #<one
        sta FA_SRC
        lda #>one
        sta FA_SRC+1
        lda #1
        sta FA_N
        lda #S2STATE
        sta FA_BANK
        jmp far_put

; s2t_pos: A, X a handle: GT_POS = its x, y, angle (the case's table)
s2t_pos:
        sta handle
        stx handle+1
        ldy #0
@try:   lda handle
        cmp buf + C_POS,y
        bne @next
        lda handle+1
        cmp buf + C_POS + 1,y
        bne @next
        ldx #0
:       lda buf + C_POS + 2,y
        sta GT_POS,x
        iny
        inx
        cpx #12
        bne :-
        rts
@next:  cpy #14
        beq @none
        ldy #14
        bra @try
@none:  brk
        .byte $00

        .segment "S2DATA"
stt_marker: .res 2
one:    .res 1
handle: .res 2
st_sb:  .res 32
buf:    .res 256
