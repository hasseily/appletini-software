; s2_palw.s: the image PALW (docs/SCREENS.md 1.3, 4.1; part s2pal,
; docs/m11-parts/s2pal.md): a level's tints and nibble tables, built into
; bank S2PAL when a level starts and when the gamma changes in a level
; (I_ReloadPalette), then the frame's P2DW. Written from upstream's
; src/iigs/i_viigs65.s: buildTints, tintRecords, tintColors,
; levelPalettes, enterLevelMode and I_SetLevelPalette's palette part [R
; i_viigs65.s:611-704, :788-875, :1015-1200]. The rest of
; I_SetLevelPalette (the colormaps A and B, the flats' colours, FUZZDARK)
; is milestone 9's level converter's; GRAYMAP is the menu's (s2menu1).
;
;   palw_level  TINTPAL (14 tints x the level's 12 palettes, with gamma)
;               from the level's GSVIEWn (bank LVC), GSSTAT's 8 records
;               and GSOVL's 3 (bank S2PAL); the nibble tables of palettes
;               0-11 (12-15 kept); the rows: 0-167 palette 0, the status
;               bar's from GSSTAT's row map; no picture; the colours due
;   palw_gamma  the tints again with the new gamma, the colours due (a
;               level's I_ReloadPalette: s2_reload answered C = 1)
;
; Both fetch PALST from S2STATE and put it back (palw_getst, palw_putst
; alone: around s2_picpal in part s2pal's test). W: PALST at $BC00 (as
; P2DW, WIW, FINW), the TINTPAL being built at $8000, a record's 448
; colour bytes at $9600, s2_nbuf at $9800 (a table, then its pairs).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2pal.inc"

        .export palw_level, palw_gamma, palw_getst, palw_putst
        .export s2_palst, s2_nbuf
        .import s2_nibtab, s2_gamma, far_get, far_put

s2_palst = PALST_W
s2_nbuf  = $9800
PST      = s2_palst
TBUF     = PALW_RT0             ; $8000: TINTPAL (5,376 bytes)
RBUF     = $9600                ; a record's 14 x 16 colours (448 bytes)
TINTS    = 14
TINT_ROW = 384
LEVEL_PALS = 12
PALREC_SIZE = 704
PALREC_PAIRS = 448
VIEW_ROWS = 168

        .segment "S2CODE"

palw_level:
        jsr palget
        jsr tints
        lda #0                  ; the nibble tables of palettes 0-11
@nib:   pha
        jsr record              ; FA_BANK, FA_SRC: the record
        clc
        lda FA_SRC
        adc #<PALREC_PAIRS
        sta FA_SRC
        lda FA_SRC+1
        adc #>PALREC_PAIRS
        sta FA_SRC+1
        lda #<(s2_nbuf+$400)
        sta FA_DST
        lda #>(s2_nbuf+$400)
        sta FA_DST+1
        stz FA_N
        jsr far_get
        pla
        pha
        jsr s2_nibtab
        pla
        inc a
        cmp #LEVEL_PALS
        bne @nib
        lda #0                  ; the view's rows: palette 0
        ldx #0
:       sta PST+PS_SCB,x
        inx
        cpx #VIEW_ROWS
        bne :-
        lda #S2PAL              ; the status bar's: GSSTAT's row map + 1
        sta FA_BANK
        lda #<S2P_GSSTAT
        sta FA_SRC
        lda #>S2P_GSSTAT
        sta FA_SRC+1
        lda #<(PST+PS_SCB+VIEW_ROWS)
        sta FA_DST
        lda #>(PST+PS_SCB+VIEW_ROWS)
        sta FA_DST+1
        lda #200-VIEW_ROWS
        sta FA_N
        jsr far_get
        ldx #VIEW_ROWS
:       inc PST+PS_SCB,x
        inx
        cpx #200
        bne :-
        stz PST+PS_VIEWPAL
        stz PST+PS_STRIPPAL
        lda #$FF                ; no picture
        sta PST+PS_PICTURE
        sta PST+PS_PICTURE+1
        lda #1
        sta PST+PS_SCBCHANGED
        sta PST+PS_TXTINV
        bra due

palw_gamma:
        jsr palget
        jsr tints
due:    lda #1                  ; levelPalettes
        sta PST+PS_LEVELCOPY
        jmp palput

; record: A = the palette (0-11): FA_BANK, FA_SRC = its record (0: the
; level's GSVIEWn; 1-8: GSSTAT's, after its 32-byte row map; 9-11:
; GSOVL's). A kept.
record:
        tax
        lda recbank,x
        sta FA_BANK
        lda reclo,x
        sta FA_SRC
        lda rechi,x
        sta FA_SRC+1
        txa
        rts

; tints: buildTints [R i_viigs65.s:611-704] into TBUF, then into S2PAL.
tints:  lda #0
@pal:   pha
        jsr record              ; its 448 colour bytes into RBUF
        lda #<RBUF
        sta FA_DST
        lda #>RBUF
        sta FA_DST+1
        stz FA_N
        jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        lda #PALREC_PAIRS - 256
        sta FA_N
        jsr far_get
        pla                     ; S2P_B: TBUF + palette * 32 (TBUF is
        pha                     ;   page aligned)
        lsr a
        lsr a
        lsr a
        clc
        adc #>TBUF
        sta S2P_B+1
        pla
        pha
        asl a
        asl a
        asl a
        asl a
        asl a
        sta S2P_B
        stz S2P_F               ; the tint
@tint:  lda S2P_F               ; its 16 colours: RBUF + tint * 32
        and #7
        asl a
        asl a
        asl a
        asl a
        asl a
        tax
        lda S2P_F
        lsr a
        lsr a
        lsr a
        clc
        adc #>RBUF
        sta @lo+2               ; (self-modified: W is RAM)
        sta @hi+2
        stz S2P_C               ; the colour
@col:
@lo:    lda RBUF,x
        sta S2P_A
@hi:    lda RBUF+1,x
        sta S2P_A+1
        phx
        jsr s2_gamma
        plx
        lda S2P_C               ; TBUF + tint * 384 + palette * 32 + 2c
        asl a
        tay
        lda S2P_A
        sta (S2P_B),y
        iny
        lda S2P_A+1
        sta (S2P_B),y
        inx
        inx
        inc S2P_C
        lda S2P_C
        cmp #16
        bne @col
        clc                     ; the next tint's row
        lda S2P_B
        adc #<TINT_ROW
        sta S2P_B
        lda S2P_B+1
        adc #>TINT_ROW
        sta S2P_B+1
        inc S2P_F
        lda S2P_F
        cmp #TINTS
        bne @tint
        pla
        inc a
        cmp #LEVEL_PALS
        beq :+
        jmp @pal
:       lda #S2PAL              ; TBUF to S2PAL's TINTPAL
        sta FA_BANK
        lda #<TBUF
        sta FA_SRC
        lda #>TBUF
        sta FA_SRC+1
        lda #<S2P_TINTPAL
        sta FA_DST
        lda #>S2P_TINTPAL
        sta FA_DST+1
        stz FA_N
        ldx #TINTS * TINT_ROW / 256
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        rts

; palget, palput: PALST from and to S2STATE (as s2_pal's, which PALW does
; not link)
palw_getst:
palget: ldy #0
        bra palx
palw_putst:
palput: ldy #1
palx:   lda #S2STATE
        sta FA_BANK
        stz FA_N
        ldx #0
@page:  txa
        clc
        adc #>SS_PALST
        sta S2P_A
        txa
        clc
        adc #>PST
        cpy #0
        bne @put
        sta FA_DST+1
        lda S2P_A
        sta FA_SRC+1
        lda #<SS_PALST
        sta FA_SRC
        lda #<PST
        sta FA_DST
        phy
        jsr far_get
        bra @next
@put:   sta FA_SRC+1
        lda S2P_A
        sta FA_DST+1
        lda #<PST
        sta FA_SRC
        lda #<SS_PALST
        sta FA_DST
        phy
        jsr far_put
@next:  ply
        inx
        cpx #3
        bne @page
        rts

        .segment "S2RODATA"

; the records of palettes 0-11
REC_STAT = S2P_GSSTAT + 32
recbank:
        .byte S2P_LVC
        .res 8, S2PAL
        .res 3, S2PAL
reclo:  .byte <S2P_GSVIEW
        .repeat 8, k
        .byte <(REC_STAT + k * PALREC_SIZE)
        .endrepeat
        .repeat 3, k
        .byte <(S2P_GSOVL + k * PALREC_SIZE)
        .endrepeat
rechi:  .byte >S2P_GSVIEW
        .repeat 8, k
        .byte >(REC_STAT + k * PALREC_SIZE)
        .endrepeat
        .repeat 3, k
        .byte >(S2P_GSOVL + k * PALREC_SIZE)
        .endrepeat
