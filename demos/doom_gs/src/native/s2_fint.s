; s2_fint.s: part s2fin's test image glue (docs/m11-parts/s2fin.md). Not
; part of the game: the image s2ft (FINW's room) links it with s2_fin.s,
; the tic side s2t_fin.s and the shared objects, under the test driver
; s2_drv.
;
; tools/native/s2fin.py stages each case in RamWorks: case k (0-30) at
; bank T_STAGE + k / 21, $0200 + (k % 21) * $0900:
;
;   +$000   WI_ACCEL (2), the card's F_STAGE, F_COUNT (4), F_MID, GAMMA (2)
;   +$100   PALST (768 bytes, SS_PALST)
;   +$400   FINW's own block (256 bytes, SS_FINW)
;   +$500   the screen's $9D00-$9FFF (the SCBs and the palettes)
;   +$800   C_KIND (0 fin_frame, 1 fin_load, 2 fin_signon, 3 fin_signoff),
;           C_FLAGS (bits 0-1 fin_frame's A; bit 2 PALST and the own block
;           stay as the last case left them; bit 3 fin_init first),
;           C_FILL (the pixels' poison), C_SCREEN (a bank holding a whole
;           screen at $0200, the pixels, SCBs and palettes: staged instead
;           of the poison and +$500; 0 none), C_TEXT, C_DIGIT (fin_signon's
;           A and X)
;
;   fint_case   A = k: the case into its places (outside the cost phase),
;               then its routine in the cost phase 30 (PHASE written PHV_2D
;               before, 0 after: the write log's cut)
;   fint_tics   A = the input bank, X = the output bank: the count at the
;               input's $0200 (a word), the records from $0210, 16 bytes
;               each (I_*); each f_ticker or f_start in the cost phase 30,
;               its outputs (O_*) at the output's $0200 + 16 * k
;
; Zero page $B0-$B6 (the math block's: FINW calls no math).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "lgame.inc"

        .export fint_case, fint_tics
        .import fin_frame, fin_load, fin_signon, fin_signoff, fin_init
        .import f_ticker, f_start, far_get, far_put

T_STAGE  = 80                   ; the stage's first bank
PER_BANK = 21
REC_PAGES = 9
C_KIND   = $800
C_FLAGS  = $801
C_FILL   = $802
C_SCREEN = $803
C_TEXT   = $804
C_DIGIT  = $805
V_ACCEL  = 0
V_CARD   = 2
V_GAMMA  = 8
BAND     = FINW_RT0
OWN      = PALST_W + PALST_SIZE

; the tic records
I_KIND   = 0                    ; 0 f_ticker, 1 f_start
I_MODE   = 1                    ; bit 0: the card's F_* from the record;
                                ;   bit 1: WI_ACCEL from the record;
                                ;   bit 2: G_GAMEACTION, G_GAMESTATE,
                                ;   AUTOMAP from the record
I_CARD   = 2                    ; F_STAGE, F_COUNT (4), F_MID
I_ACCEL  = 8
I_ACTION = 10
I_STATE  = 12
I_AUTOMAP = 14
O_CARD   = 0                    ; F_STAGE, F_COUNT (4), F_MID
O_ACCEL  = 6
O_ACTION = 8
O_STATE  = 10
O_AUTOMAP = 12
O_MAIL   = 13
NCARD    = 6

T_BANK   = $B0
T_PAGE   = $B1
T_N      = $B2
T_K      = $B3                  ; fint_tics: the records left (2)
T_IB     = $B5
T_OB     = $B6
T_A      = $B7                  ; the output's address: $0200 + 16 * k (2)

        .assert F_COUNT = F_STAGE + 1 && F_MID = F_STAGE + 5, error, "F_*"

        .segment "S2DATA"
ctl:    .res 6
rec:    .res 16

        .segment "S2CODE"

fint_case:
        stz PHASE
        ldx #T_STAGE
:       cmp #PER_BANK
        bcc :+
        sbc #PER_BANK
        inx
        bra :-
:       stx T_BANK
        sta T_N                 ; page 2 + k * 9
        asl a
        asl a
        asl a
        adc T_N
        adc #2
        sta T_PAGE
        ldx #>C_KIND            ; the controls
        ldy #1
        jsr fetch
        ldx #5
:       lda BAND + <C_KIND,x
        sta ctl,x
        dex
        bpl :-
        ldx #0                  ; WI_ACCEL, the card, GAMMA
        ldy #1
        jsr fetch
        lda BAND + V_ACCEL
        sta WI_ACCEL
        lda BAND + V_ACCEL + 1
        sta WI_ACCEL+1
        ldx #NCARD - 1
:       lda BAND + V_CARD,x
        sta F_STAGE,x
        dex
        bpl :-
        lda BAND + V_GAMMA
        sta GAMMA
        lda BAND + V_GAMMA + 1
        sta GAMMA+1
        lda ctl + <(C_FLAGS - C_KIND)
        and #4
        bne @screen
        ldx #1                  ; PALST
        ldy #3
        jsr fetch
        ldx #>SS_PALST
        ldy #3
        jsr store
        ldx #4                  ; FINW's own block
        ldy #1
        jsr fetch
        ldx #>SS_FINW
        ldy #1
        jsr store
@screen:
        lda ctl + <(C_SCREEN - C_KIND)
        beq @poison
        sta T_BANK              ; a whole screen: 128 pages from its bank
        lda #2
        sta T_PAGE
        lda #>SHR
        sta T_N
:       ldx #0
        ldy #1
        jsr fetch
        lda T_N
        sta @w+2
        sta RAMWRTON
        ldx #0
:       lda BAND,x
@w:     sta SHR,x
        inx
        bne :-
        sta RAMWRTOFF
        inc T_PAGE
        inc T_N
        lda T_N
        cmp #>(SCB + $0300)     ; (the screen's end, $A000)
        bne :--
        bra @call
@poison:
        ldx #5                  ; $9D00-$9FFF
        ldy #3
        jsr fetch
        sta RAMWRTON
        ldx #0
:       lda BAND,x
        sta SCB,x
        lda BAND+$100,x
        sta SCB+$100,x
        lda BAND+$200,x
        sta SCB+$200,x
        inx
        bne :-
        lda ctl + <(C_FILL - C_KIND)
        ldy #>SHR               ; the pixels poisoned
:       sty @poke+2
        ldx #0
@poke:  sta SHR,x
        inx
        bne @poke
        iny
        cpy #>SCB
        bne :-
        sta RAMWRTOFF
@call:  lda ctl + <(C_FLAGS - C_KIND)
        and #8
        beq :+
        jsr fin_init
:       lda #PHV_2D
        sta PHASE
        lda ctl + <(C_KIND - C_KIND)
        beq @frame
        cmp #1
        beq @load
        cmp #2
        beq @on
        jsr fin_signoff
        bra @end
@on:    lda ctl + <(C_TEXT - C_KIND)
        ldx ctl + <(C_DIGIT - C_KIND)
        jsr fin_signon
        bra @end
@load:  jsr fin_load
        bra @end
@frame: lda ctl + <(C_FLAGS - C_KIND)
        and #3
        jsr fin_frame
@end:   stz PHASE
        rts

; fetch: Y pages of the case from its page + X into the band
fetch:  txa
        clc
        adc T_PAGE
        sta FA_SRC+1
        stz FA_SRC
        lda T_BANK
        sta FA_BANK
        lda #<BAND
        sta FA_DST
        lda #>BAND
        sta FA_DST+1
        stz FA_N
:       phy
        jsr far_get
        ply
        inc FA_SRC+1
        inc FA_DST+1
        dey
        bne :-
        rts

; store: Y pages of the band into S2STATE from page X
store:  stx FA_DST+1
        stz FA_DST
        lda #S2STATE
        sta FA_BANK
        lda #<BAND
        sta FA_SRC
        lda #>BAND
        sta FA_SRC+1
        stz FA_N
:       phy
        jsr far_put
        ply
        inc FA_SRC+1
        inc FA_DST+1
        dey
        bne :-
        rts

; ---------------------------------------------------------------------------
; fint_tics: the tic side's cases
; ---------------------------------------------------------------------------
fint_tics:
        stz PHASE
        sta T_IB
        stx T_OB
        sta FA_BANK             ; the count
        stz FA_SRC
        lda #2
        sta FA_SRC+1
        lda #<T_K
        sta FA_DST
        stz FA_DST+1
        lda #2
        sta FA_N
        jsr far_get
        stz T_A
        lda #2
        sta T_A+1
@next:  lda T_K
        ora T_K+1
        bne :+
        rts
:       lda T_IB                ; the record: $0210 + 16 * k
        sta FA_BANK
        clc
        lda T_A
        adc #$10
        sta FA_SRC
        lda T_A+1
        adc #0
        sta FA_SRC+1
        lda #<rec
        sta FA_DST
        lda #>rec
        sta FA_DST+1
        lda #16
        sta FA_N
        jsr far_get
        lda rec + I_MODE
        lsr a
        bcc :+
        ldx #NCARD - 1
@c:     lda rec + I_CARD,x
        sta F_STAGE,x
        dex
        bpl @c
:       lda rec + I_MODE
        and #2
        beq :+
        lda rec + I_ACCEL
        sta WI_ACCEL
        lda rec + I_ACCEL + 1
        sta WI_ACCEL+1
:       lda rec + I_MODE
        and #4
        beq :+
        lda rec + I_ACTION
        sta G_GAMEACTION
        lda rec + I_ACTION + 1
        sta G_GAMEACTION+1
        lda rec + I_STATE
        sta G_GAMESTATE
        lda rec + I_STATE + 1
        sta G_GAMESTATE+1
        lda rec + I_AUTOMAP
        sta AUTOMAP
:       lda #PHV_2D
        sta PHASE
        lda rec + I_KIND
        bne @start
        jsr f_ticker
        bra @out
@start: jsr f_start
@out:   stz PHASE
        ldx #NCARD - 1          ; the outputs
:       lda F_STAGE,x
        sta rec + O_CARD,x
        dex
        bpl :-
        lda WI_ACCEL
        sta rec + O_ACCEL
        lda WI_ACCEL+1
        sta rec + O_ACCEL + 1
        lda G_GAMEACTION
        sta rec + O_ACTION
        lda G_GAMEACTION+1
        sta rec + O_ACTION + 1
        lda G_GAMESTATE
        sta rec + O_STATE
        lda G_GAMESTATE+1
        sta rec + O_STATE + 1
        lda AUTOMAP
        sta rec + O_AUTOMAP
        lda S2_MAIL
        sta rec + O_MAIL
        lda T_OB
        sta FA_BANK
        lda T_A
        sta FA_DST
        lda T_A+1
        sta FA_DST+1
        lda #<rec
        sta FA_SRC
        lda #>rec
        sta FA_SRC+1
        lda #16
        sta FA_N
        jsr far_put
        clc
        lda T_A
        adc #16
        sta T_A
        bcc :+
        inc T_A+1
:       lda T_K
        bne :+
        dec T_K+1
:       dec T_K
        jmp @next
