; s2_drawt.s: part s2draw's test image (docs/m11-parts/s2draw.md), linked
; in P2DW's room with its runtime places (the band of 32 rows at $8300,
; the marks page at $9700, the fetch buffer at $B800). Not part of the
; game. tools/native/s2drawcase.py writes the cases into RamWorks:
;
;   bank DESC_BANK   a case's descriptor at $2000 + case * $100 (D_*;
;                    each band: its rows and the palettes of its 8 nibble
;                    slots, $FF: none), each screen row's ROWL page at
;                    $4000 + case * $200 + row, ROWR at $4100 + ... (the
;                    slots' pages in W)
;   a background     bank BG: the screen's pixels at $2000 + row * 160, the
;                    marks before (DRB $A000 + row, DRE $A100 + row); BG +
;                    1, BG + 2: CAPVAL, CAPMSK before (at $2000 + row *
;                    160); BG + 3: the 16 nibble tables at $2000
;                    (upstream's NIBTAB)
;   (a RAMRD window reaches a bank's $0200-$BFFF only)
;   the sources      the patches, raw lumps, flats, rectangles
;
;   s2x_case    A = the case: for each band of its descriptor, the band's
;               rows, marks, nibble slots and row tables (CAPVAL,
;               CAPMSK into the band's rows 10-19 and 20-29 when the case
;               records them), the drawer (the cost phase 30 around it
;               alone), then the band's rows, marks and S2_DRY0/1 into
;               bank R_BANK (as the background; S2_DRY0/1 at $A400 + 2 *
;               band) and CAPVAL, CAPMSK into R_BANK + 1, + 2
;   s2x_pub     A = the case: its first band from the background, then
;               s2_publish (phase 30); its DRE and S2_DRY0/1 after into
;               R_BANK; D_FLAGS bit 0 sets s2_begun first (a frame whose
;               s2_begin has run)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .export s2x_case, s2x_pub
        .export s2_marks, s2_fbuf, s2_begun
        .exportzp s2_fbpages
        .import s2_patch, s2_vpatch, s2_raw, s2_back, s2_rect
        .import s2_publish, s2_mul160, far_get, far_put

s2_marks   = P2DW_MARKS
s2_fbuf    = P2DW_FBUF
s2_fbpages = P2DW_FBPAGES
BANDBUF    = P2DW_RT0
CAPVW      = BANDBUF + 10 * ROW_BYTES
CAPMW      = BANDBUF + 20 * ROW_BYTES
DESCW      = P2DW_STATE
SLOTS      = P2DW_RT2           ; eight nibble slots of 1 KB

DESC_BANK  = 50
R_BANK     = 80

D_KIND     = 0                  ; 0 s2_patch, 1 s2_vpatch, 2 s2_raw,
D_PBANK    = 1                  ;   3 s2_back, 4 s2_rect
D_PADDR    = 2
D_X        = 4                  ; S2_X (or S2_RY0, S2_RY1)
D_Y        = 6                  ; S2_Y (or S2_RB0, S2_RB1)
D_CAP      = 8
D_BG       = 9
D_NB       = 10
D_FLAGS    = 11
D_BANDS    = 12                 ; y0, y1, 8 slots' palettes: a band
BAND_SIZE  = 10

T_B        = $78                ; the band
T_R        = $79                ; the row
T_BANK     = $7A
T_PUT      = $7B                ; 0: RamWorks to W, else W to RamWorks
T_TB       = $7C                ; (2) the bank's address of row 0
T_TW       = $7E                ; (2) W's of the band's row 0
T_K        = $80                ; the case
T_E        = $81                ; its band's entry in DESCW

        .segment "S2CODE"

s2x_case:
        stz PHASE               ; (the test's own work: phase 0)
        jsr getdesc
        stz T_B
@band:  lda T_B
        cmp DESCW+D_NB
        bcc :+
        jmp mark
:       jsr bandin
        lda DESCW+D_CAP
        sta S2_CAP
        bpl @args
        lda #<(CAPVW - BANDBUF)
        sta S2_CAPD
        lda #>(CAPVW - BANDBUF)
        sta S2_CAPD+1
        lda #<(CAPMW - CAPVW)
        sta S2_CAPM
        lda #>(CAPMW - CAPVW)
        sta S2_CAPM+1
        ldx #<CAPVW
        ldy #>CAPVW
        lda #1
        jsr caprows
        ldx #<CAPMW
        ldy #>CAPMW
        lda #2
        jsr caprows
@args:  ldx #2                  ; the source, then x, y (or their aliases)
:       lda DESCW+D_PBANK,x
        sta S2_PBANK,x
        dex
        bpl :-
        ldx #3
:       lda DESCW+D_X,x
        sta S2_X,x
        dex
        bpl :-
        lda #PHV_2D
        sta PHASE
        jsr dispatch
        stz PHASE
        lda #R_BANK             ; the band out
        sta T_BANK
        sta T_PUT
        jsr pixrows
        lda #$A0
        ldx #0
        jsr marksio
        lda #$A1
        ldx #$40
        jsr marksio
        lda T_B                 ; S2_DRY0/1 at $A400 + 2 * band
        asl a
        sta FA_DST
        lda #$A4
        sta FA_DST+1
        lda #S2_DRY0
        sta FA_SRC
        stz FA_SRC+1
        lda #2
        sta FA_N
        jsr far_put
        bit DESCW+D_CAP
        bpl @next
        ldx #<CAPVW
        ldy #>CAPVW
        lda #R_BANK+1
        jsr capout
        ldx #<CAPMW
        ldy #>CAPMW
        lda #R_BANK+2
        jsr capout
@next:  inc T_B
        jmp @band

; mark: the case's number at R_BANK $A5FF, last (tools/native/
; s2drawcase.py tells each call's snapshot by it: a VBL interrupt that
; returns to the driver's snapshot point takes a second snapshot)
mark:   lda #<$A5FF
        sta FA_DST
        lda #>$A5FF
        sta FA_DST+1
        lda #T_K
        sta FA_SRC
        stz FA_SRC+1
        lda #1
        sta FA_N
        lda #R_BANK
        sta FA_BANK
        jmp far_put

dispatch:
        lda DESCW+D_KIND
        asl a
        tax
        jmp (kinds,x)
kinds:  .word s2_patch, s2_vpatch, s2_raw, s2_back, s2_rect

s2x_pub:
        stz PHASE
        jsr getdesc
        stz T_B
        jsr bandin
        lda DESCW+D_FLAGS
        and #1
        beq :+
        sta s2_begun
:       lda #PHV_2D
        sta PHASE
        jsr s2_publish
        stz PHASE
        lda #R_BANK
        sta T_BANK
        sta T_PUT
        lda #$A1
        ldx #$40
        jsr marksio
        stz FA_DST
        lda #$A4
        sta FA_DST+1
        lda #S2_DRY0
        sta FA_SRC
        stz FA_SRC+1
        lda #2
        sta FA_N
        jsr far_put
        bra mark

; getdesc: the descriptor of the case A into DESCW
getdesc:
        sta T_K
        clc
        adc #$20
        sta FA_SRC+1
        stz FA_SRC
        lda #<DESCW
        sta FA_DST
        lda #>DESCW
        sta FA_DST+1
        lda #DESC_BANK
        sta FA_BANK
        stz FA_N
        jmp far_get

; bandin: the band T_B: S2_Y0, S2_Y1, S2_BAND; its rows, marks, row tables
; from the background; S2_DRY0/1 from its marks
bandin:
        lda T_B
        asl a
        sta T_E
        asl a
        asl a
        clc
        adc T_E
        adc #D_BANDS
        sta T_E
        tax
        lda DESCW,x
        sta S2_Y0
        lda DESCW+1,x
        sta S2_Y1
        lda #<BANDBUF
        sta S2_BAND
        lda #>BANDBUF
        sta S2_BAND+1
        lda DESCW+D_BG
        sta T_BANK
        stz T_PUT
        jsr pixrows
        lda #$A0
        ldx #$00
        jsr marksio
        lda #$A1
        ldx #$40
        jsr marksio
        lda #DESC_BANK          ; the row tables
        sta T_BANK
        lda T_K
        asl a
        adc #$40
        pha
        ldx #$80
        jsr marksio
        pla
        inc a
        ldx #$C0
        jsr marksio
        lda DESCW+D_BG          ; the slots: 4 pages each from NIBTAB
        clc
        adc #3
        sta FA_BANK
        lda #<SLOTS
        sta FA_DST
        lda #>SLOTS
        sta FA_DST+1
        stz FA_SRC
        stz FA_N
        ldy #0
@slot:  phy
        tya
        clc
        adc T_E
        tax
        lda DESCW+2,x
        cmp #$FF
        beq @none
        asl a
        asl a
        adc #$20
        sta FA_SRC+1
        ldx #4
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        bra @nx
@none:  lda FA_DST+1
        clc
        adc #4
        sta FA_DST+1
@nx:    ply
        iny
        cpy #8
        bcc @slot
        stz S2_DRY0
        stz S2_DRY1
        lda S2_Y1
        sec
        sbc S2_Y0
        sta S2_CNT
        ldy #0
@h:     cpy S2_CNT
        bcs @done
        lda s2_marks+$40,y
        beq @n
        lda S2_DRY1
        bne :+
        sty S2_DRY0
:       iny
        sty S2_DRY1
        bra @h
@n:     iny
        bra @h
@done:  rts

; pixrows: the band's rows between W (BANDBUF) and bank T_BANK at $2000
pixrows:
        ldx #<BANDBUF
        ldy #>BANDBUF
; rows: the band's rows, W from Y:X, bank T_BANK from $2000 + row * 160
rows:   stx T_TW
        sty T_TW+1
        lda S2_Y0
        sta T_R
@r:     lda T_R
        cmp S2_Y1
        bcs @done
        jsr s2_mul160           ; the bank's row
        clc
        adc #<SHR
        pha
        txa
        adc #>SHR
        pha
        lda T_R                 ; W's
        sec
        sbc S2_Y0
        jsr s2_mul160
        clc
        adc T_TW
        tay
        txa
        adc T_TW+1
        tax
        lda #ROW_BYTES
        sta FA_N
        lda T_BANK
        sta FA_BANK
        lda T_PUT
        bne @put
        sty FA_DST
        stx FA_DST+1
        pla
        sta FA_SRC+1
        pla
        sta FA_SRC
        jsr far_get
        bra @n
@put:   sty FA_SRC
        stx FA_SRC+1
        pla
        sta FA_DST+1
        pla
        sta FA_DST
        jsr far_put
@n:     inc T_R
        bra @r
@done:  rts

; caprows: CAPVAL (A = 1) or CAPMSK (2) of the background into W at Y:X
caprows:
        clc
        adc DESCW+D_BG
        sta T_BANK
        stz T_PUT
        bra rows

; capout: W at Y:X into bank A
capout:
        sta T_BANK
        sta T_PUT
        bra rows

; marksio: the band's rows of a marks page: bank T_BANK's page A (row y0
; at its byte y0), W's s2_marks + X; T_PUT the way
marksio:
        pha
        lda S2_Y1
        sec
        sbc S2_Y0
        sta FA_N
        txa
        clc
        adc #<s2_marks
        tay
        lda #>s2_marks
        adc #0
        tax
        pla
        pha
        lda T_BANK
        sta FA_BANK
        lda T_PUT
        bne @put
        sty FA_DST
        stx FA_DST+1
        lda S2_Y0
        sta FA_SRC
        pla
        sta FA_SRC+1
        jmp far_get
@put:   sty FA_SRC
        stx FA_SRC+1
        lda S2_Y0
        sta FA_DST
        pla
        sta FA_DST+1
        jmp far_put

        .segment "S2DATA"
s2_begun:
        .byte 0
