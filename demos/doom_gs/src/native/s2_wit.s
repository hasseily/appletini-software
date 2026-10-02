; s2_wit.s: part s2wi's test image glue (docs/m11-parts/s2wi.md). Not part
; of the game: the image s2wt (WIW's room) links it with s2_wi.s and the
; shared objects, under the test driver s2_drv.
;
; tools/native/s2wi.py stages each case in RamWorks: case k (0-30) at bank
; T_STAGE + k / 19, $0200 + (k % 19) * $0A00:
;
;   +$000   main G_WMINFO .. WI_SNLPTR + 1 (the wi state, milestone 10's
;           places; the bytes between them the run's fill or the case's)
;   +$200   PALST (768 bytes, SS_PALST)
;   +$500   WIW's own block (256 bytes, SS_WIW: W_LUMPS)
;   +$600   the screen's $9D00-$9FFF (the SCBs and the palettes)
;   +$900   C_FLAGS: bit 0 a level was left (wi_frame's A), bit 1 chained
;           (PALST and the own block stay the last frame's), bit 2
;           wi_init first; C_FILL the pixels' poison; C_GAMMA (2)
;
;   wit_case    A = k: the case into its places (outside the cost phase),
;               the pixels $2000-$9CFF set to C_FILL, then wi_frame in the
;               cost phase 30 (PHASE written PHV_2D before, 0 after: the
;               write log's cut)
;
; Zero page $B0-$B4 (the math block's: WIW calls no math).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "lgame.inc"

        .export wit_case
        .import wi_frame, wi_init, far_get, far_put

T_STAGE  = 80                   ; the stage's first bank
PER_BANK = 19
REC_PAGES = 10
MB_LO    = G_WMINFO
MB_HI    = WI_SNLPTR + 2
C_FLAGS  = $900
C_FILL   = $901
C_GAMMA  = $902
BAND     = WIW_RT0

T_BANK   = $B0
T_PAGE   = $B1
T_FLAGS  = $B2
T_N      = $B3
T_FILL   = $B4

        .assert MB_HI - MB_LO <= $200, error, "the wi state's block"

        .segment "S2CODE"

wit_case:
        stz PHASE
        ldx #T_STAGE
:       cmp #PER_BANK
        bcc :+
        sbc #PER_BANK
        inx
        bra :-
:       stx T_BANK
        sta T_N                 ; page 2 + k * 10
        asl a
        asl a
        adc T_N
        asl a
        adc #2
        sta T_PAGE
        ldx #>C_FLAGS           ; the controls
        ldy #1
        jsr fetch
        lda BAND + <C_FLAGS
        sta T_FLAGS
        lda BAND + <C_GAMMA
        sta GAMMA
        lda BAND + <C_GAMMA + 1
        sta GAMMA+1
        lda BAND + <C_FILL
        sta T_FILL
        ldx #0                  ; the wi state: two pages to the band
        ldy #2
        jsr fetch
        ldx #0
.if MB_HI - MB_LO > $100
:       lda BAND,x
        sta MB_LO,x
        inx
        bne :-
:       lda BAND+$100,x
        sta MB_LO+$100,x
        inx
        cpx #<(MB_HI - MB_LO)
        bne :-
.else
:       lda BAND,x
        sta MB_LO,x
        inx
        cpx #<(MB_HI - MB_LO)
        bne :-
.endif
        lda T_FLAGS
        and #2
        bne @screen
        ldx #2                  ; PALST
        ldy #3
        jsr fetch
        ldx #>SS_PALST
        ldy #3
        jsr store
        ldx #5                  ; WIW's own block
        ldy #1
        jsr fetch
        ldx #>SS_WIW
        ldy #1
        jsr store
@screen:
        ldx #6                  ; $9D00-$9FFF
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
        lda T_FILL
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
        lda T_FLAGS
        and #4
        beq :+
        jsr wi_init
:       lda #PHV_2D
        sta PHASE
        lda T_FLAGS
        and #1
        jsr wi_frame
        stz PHASE
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
        sty T_N
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dec T_N
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
        sty T_N
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dec T_N
        bne :-
        rts
