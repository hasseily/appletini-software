; s2_pal.s: the palettes, the tints, the SCBs, the finish and the wipe
; (docs/SCREENS.md, the palettes; part s2pal). The shared object s2_pal,
; linked into P2DW, MENUW, WIW and FINW. Written from upstream's
; src/iigs/i_viigs65.s (I_SetPalette, I_ReloadPalette, I_FinishUpdate and
; D_Wipe without showDirty, I_ApplyColors, newColors, pictureColors,
; I_ViewPalette, I_MessageStrip, setRows, rowPalette), st_stuff65.s
; (ST_doPaletteStuff) and d_main65.s (stripEarly's palette).
;
; The palette state PALST (s2layout.py's PS_*: scb, palette, newpal,
; curtint, levelcopy, palettecount, scbchanged, picturenum, viewpal,
; strippal, PS_BEGUN, PS_TXTINV) is at s2_palst in W, which each image
; exports; s2_palget and s2_palput move it from and to S2STATE's SS_PALST
; (docs/SCREENS.md). Natively PS_PALCOUNT is a flag: upstream's
; palettecount is 0 or 256 words [R i_viigs65.s:1274-1275, :2124, :2187].
;
; The order of the screen's stores is upstream's [R i_viigs65.s:327-345]
; through two entries: s2_begin, which s2_publish calls before the
; frame's first band (the black palettes when a picture is new, then
; newColors), and s2_finish at the frame's end (s2_begin if no band was
; published, then pictureColors). Every screen store is a CPU store with
; RAMWRT on, to aux 0 $9D00-$9FFF; TINTPAL's row comes from bank S2PAL
; through page 1 (S2P_BOUNCE, 128 bytes at a time).
;
;   s2_palget, s2_palput   PALST from and to S2STATE (3 x 256 bytes)
;   s2_begin               the black step and newColors (once a frame)
;   s2_finish              s2_begin if no band came, pictureColors; the
;                          frame's s2_begun cleared
;   s2_setpal              I_SetPalette: A = the tint
;   s2_reload              I_ReloadPalette: C = 1 when a level's tints
;                          must be rebuilt (PALW's palw_gamma), else the
;                          picture comes new at its next draw
;   s2_viewpal             I_ViewPalette: A = the view rows' palette
;   s2_strip               I_MessageStrip's palette: A = on, X = clear;
;                          C = 1 when the strip's rows must be cleared
;                          and marked (part s2hud's band)
;   s2_stripearly          stripEarly's: A = DD_PAUSED (the frame
;                          driver's); message_new from the card (HU_NEW);
;                          C as s2_strip
;   s2_setrows             setRows: rows X .. Y - 1 get palette A
;   st_palette             ST_doPaletteStuff (P2DW): the player's damage,
;                          berserk, bonus and radiation suit into
;                          st_palette (P_STPALETTE) and newpal
;
; Zero page S2P_A .. S2P_F ($78-$7F) and the far layer's FA_*; A, X, Y
; changed. The band's zero page (S2_BAND .. S2_DRY1) is kept, since
; s2_publish calls s2_begin with its band set.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2pal.inc"

        .export s2_palget, s2_palput, s2_begin, s2_finish
        .export s2_setpal, s2_reload, s2_viewpal, s2_strip, s2_stripearly
        .export s2_setrows, st_palette
        .import s2_palst, far_get, far_put

NO_CHANGE   = 100               ; NO_PALETTE_CHANGE [R i_viigs65.s:66]
MSG_PAL     = 10
VIEW_ROWS   = 168
STRIP_ROWS  = 10
TINT_ROW    = 384
NUMREDPALS  = 8                 ; [R st_stuff65.s:36-40]
NUMBONUSPALS = 4
STARTREDPALS = 1
STARTBONUSPALS = 9
RADIATIONPAL = 13

PST         = s2_palst
PLR         = S2P_PLAYER

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; s2_palget, s2_palput: PALST between W (s2_palst) and S2STATE (SS_PALST),
; three far_get or far_put calls of 256 bytes.
; ---------------------------------------------------------------------------
s2_palget:
        lda #0
        bra palx
s2_palput:
        lda #1
palx:   sta S2P_C
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        ldx #0
@page:  txa                     ; S2P_A: the bank's page, S2P_B: W's
        clc
        adc #>SS_PALST
        sta S2P_A
        txa
        clc
        adc #>PST
        sta S2P_B
        lda S2P_C
        bne @put
        lda #<SS_PALST
        sta FA_SRC
        lda S2P_A
        sta FA_SRC+1
        lda #<PST
        sta FA_DST
        lda S2P_B
        sta FA_DST+1
        jsr far_get
        bra @next
@put:   lda #<PST
        sta FA_SRC
        lda S2P_B
        sta FA_SRC+1
        lda #<SS_PALST
        sta FA_DST
        lda S2P_A
        sta FA_DST+1
        jsr far_put
@next:  inx
        cpx #3
        bne @page
        rts

; ---------------------------------------------------------------------------
; s2_begin: with a new picture (palettecount) the 512 palette bytes black,
; then newColors [R i_viigs65.s:329-391]: a new tint (newpal) becomes
; curtint and, in a level, its TINTPAL row is due (levelcopy); the SCBs
; when they changed; the level's 12 palettes of the tint.
; ---------------------------------------------------------------------------
s2_begin:
        lda PST+PS_PALCOUNT
        beq newcolors
        sta RAMWRTON
        ldx #0
:       stz PALETTES,x
        stz PALETTES+$100,x
        inx
        bne :-
        sta RAMWRTOFF
newcolors:
        lda PST+PS_NEWPAL
        cmp #NO_CHANGE
        beq @scb
        sta PST+PS_CURTINT
        lda PST+PS_PICTURE+1    ; a level (picturenum < 0): its colours
        bpl :+
        lda #1
        sta PST+PS_LEVELCOPY
:       lda #NO_CHANGE
        sta PST+PS_NEWPAL
@scb:   lda PST+PS_SCBCHANGED
        beq @tint
        stz PST+PS_SCBCHANGED
        sta RAMWRTON
        ldx #200
:       lda PST+PS_SCB-1,x
        sta SCB-1,x
        dex
        bne :-
        sta RAMWRTOFF
@tint:  lda PST+PS_LEVELCOPY
        beq @done
        stz PST+PS_LEVELCOPY
        lda PST+PS_CURTINT      ; TINTPAL + curtint * 384 (upstream's
        lsr a                   ;   16 bits): * 256 + * 128
        sta S2P_C
        lda #0
        ror a
        clc
        adc #<S2P_TINTPAL
        sta FA_SRC
        lda PST+PS_CURTINT
        adc S2P_C
        clc
        adc #>S2P_TINTPAL
        sta FA_SRC+1
        lda #S2PAL
        sta FA_BANK
        lda #<S2P_BOUNCE
        sta FA_DST
        lda #>S2P_BOUNCE
        sta FA_DST+1
        lda #S2P_BOUNCE_SIZE
        sta FA_N
        lda #<PALETTES
        sta S2P_B
        lda #>PALETTES
        sta S2P_B+1
        lda #TINT_ROW / S2P_BOUNCE_SIZE
        sta S2P_D
@chunk: jsr far_get
        sta RAMWRTON
        ldy #0
:       lda S2P_BOUNCE,y
        sta (S2P_B),y
        iny
        cpy #S2P_BOUNCE_SIZE
        bne :-
        sta RAMWRTOFF
        clc
        lda FA_SRC
        adc #S2P_BOUNCE_SIZE
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       clc
        lda S2P_B
        adc #S2P_BOUNCE_SIZE
        sta S2P_B
        bcc :+
        inc S2P_B+1
:       dec S2P_D
        bne @chunk
@done:  rts

; ---------------------------------------------------------------------------
; s2_finish: the frame's end. s2_begin if no band called it, then
; pictureColors [R i_viigs65.s:394-405]: a picture's 512 palette bytes.
; ---------------------------------------------------------------------------
s2_finish:
        lda PST+PS_BEGUN
        bne :+
        jsr s2_begin
:       stz PST+PS_BEGUN
        lda PST+PS_PALCOUNT
        beq @done
        stz PST+PS_PALCOUNT
        sta RAMWRTON
        ldx #0
:       lda PST+PS_PALETTE,x
        sta PALETTES,x
        lda PST+PS_PALETTE+$100,x
        sta PALETTES+$100,x
        inx
        bne :-
        sta RAMWRTOFF
@done:  rts

; ---------------------------------------------------------------------------
; s2_setpal: I_SetPalette [R i_viigs65.s:315-317]. s2_reload:
; I_ReloadPalette [R :318-328].
; ---------------------------------------------------------------------------
s2_setpal:
        sta PST+PS_NEWPAL
        rts

s2_reload:
        lda PST+PS_PICTURE+1
        bmi :+                  ; a level: PALW rebuilds its tints (C = 1)
        lda #$FF                ; a picture: new at its next draw
        sta PST+PS_PICTURE
        sta PST+PS_PICTURE+1
        clc
        rts
:       sec
        rts

; ---------------------------------------------------------------------------
; s2_setrows: setRows [R i_viigs65.s:738-753] and rowPalette's SCB [R
; :766-787]: rows X .. Y - 1 get palette A; the SCBs changed; the text
; cache invalid. (A row's nibble pages are derived from its SCB by the
; drawer's image.)
; ---------------------------------------------------------------------------
s2_setrows:
        sty S2P_C
:       cpx S2P_C
        bcs :+
        sta PST+PS_SCB,x
        inx
        bra :-
:       lda #1
        sta PST+PS_SCBCHANGED
        sta PST+PS_TXTINV
        rts

; ---------------------------------------------------------------------------
; s2_viewpal: I_ViewPalette [R i_viigs65.s:509-518]: the view's rows.
; ---------------------------------------------------------------------------
s2_viewpal:
        cmp PST+PS_VIEWPAL
        beq @done
        sta PST+PS_VIEWPAL
        sta PST+PS_STRIPPAL
        ldx #0
        ldy #VIEW_ROWS
        jmp s2_setrows
@done:  rts

; ---------------------------------------------------------------------------
; s2_stripearly: stripEarly [R d_main65.s:769-778]: A = DD_PAUSED. The
; menu's text needs a fresh clear: message_new is 1 while a menu is up.
; s2_strip: I_MessageStrip [R i_viigs65.s:519-555], its palette: the
; strip's rows in MSG_PAL when on (C = 1: a clear is due when they turn
; on or with X), else in the view's palette.
; ---------------------------------------------------------------------------
s2_stripearly:
        cmp #0
        bne @paused
        ldx HU_NEW
        stz HU_NEW
        lda S2P_MENUACTIVE
        ora S2P_MENUACTIVE+1
        beq :+
        inc HU_NEW
:       lda HU_ON
        bra s2_strip
@paused:
        clc
        rts

s2_strip:
        stz S2P_D               ; no clear
        cmp #0
        beq @off
        lda PST+PS_STRIPPAL
        cmp #MSG_PAL
        bne @clear
        txa
        beq @on
@clear: inc S2P_D
@on:    lda #MSG_PAL
        bra @set
@off:   lda PST+PS_VIEWPAL
@set:   cmp PST+PS_STRIPPAL
        beq @done
        sta PST+PS_STRIPPAL
        ldx #0
        ldy #STRIP_ROWS
        jsr s2_setrows
@done:  lsr S2P_D               ; C: the clear
        rts

; ---------------------------------------------------------------------------
; st_palette: ST_doPaletteStuff [R st_stuff65.s:1103-1171], upstream's
; 16-bit arithmetic: the red of damage (or of the fading berserk), half in
; the menu; else the gold of a bonus; else the radiation suit's green
; (blinking when it runs out). A new value goes to st_palette (P2DW's
; P_STPALETTE, a signed byte) and newpal.
; ---------------------------------------------------------------------------
st_palette:
        lda PLR+S2P_DAMAGE      ; cnt
        sta S2P_A
        lda PLR+S2P_DAMAGE+1
        sta S2P_A+1
        lda PLR+S2P_STRENGTH
        ora PLR+S2P_STRENGTH+1
        beq @cnt
        lda PLR+S2P_STRENGTH+1  ; bzc = 12 - (strength >> 6)
        sta S2P_B+1
        lda PLR+S2P_STRENGTH
        ldx #6
:       lsr S2P_B+1
        ror a
        dex
        bne :-
        sta S2P_B
        sec
        lda #12
        sbc S2P_B
        sta S2P_B
        lda #0
        sbc S2P_B+1
        sta S2P_B+1
        cmp S2P_A+1             ; bzc == cnt: kept
        bne :+
        lda S2P_B
        cmp S2P_A
        beq @cnt
:       sec                     ; bzc - cnt negative: kept
        lda S2P_B
        sbc S2P_A
        lda S2P_B+1
        sbc S2P_A+1
        bmi @cnt
        lda S2P_B
        sta S2P_A
        lda S2P_B+1
        sta S2P_A+1
@cnt:   lda S2P_A
        ora S2P_A+1
        beq @bonus
        ldy #7                  ; red: (cnt + 7) >> 3, at most 7
        jsr add_asr3
        lda #NUMREDPALS
        jsr at_most
        lda S2P_MENUACTIVE      ; half in the menu
        ora S2P_MENUACTIVE+1
        beq :+
        jsr asr1
:       lda #STARTREDPALS
        bra @add
@bonus: lda PLR+S2P_BONUS
        sta S2P_A
        lda PLR+S2P_BONUS+1
        sta S2P_A+1
        ora S2P_A
        beq @suit
        ldy #7                  ; gold: (bonuscount + 7) >> 3, at most 3
        jsr add_asr3
        lda #NUMBONUSPALS
        jsr at_most
        lda #STARTBONUSPALS
@add:   clc
        adc S2P_A
        sta S2P_A
        bcc @new
        inc S2P_A+1
        bra @new
@suit:  sec                     ; the suit: > 128, or bit 3 blinking
        lda PLR+S2P_IRONFEET
        sbc #<(4 * 32 + 1)
        lda PLR+S2P_IRONFEET+1
        sbc #>(4 * 32 + 1)
        bpl @rad
        lda PLR+S2P_IRONFEET
        and #8
        bne @rad
        stz S2P_A               ; (S2P_A+1 is 0: bonuscount was)
        bra @new
@rad:   lda #RADIATIONPAL
        sta S2P_A
        stz S2P_A+1
@new:   ldx #0                  ; st_palette, sign extended
        lda P_STPALETTE
        bpl :+
        dex
:       cmp S2P_A
        bne :+
        cpx S2P_A+1
        beq @done
:       lda S2P_A
        sta P_STPALETTE
        sta PST+PS_NEWPAL       ; I_SetPalette
@done:  rts

; S2P_A = (S2P_A + Y) >> 3, arithmetic, 16 bits
add_asr3:
        tya
        clc
        adc S2P_A
        sta S2P_A
        bcc :+
        inc S2P_A+1
:       jsr asr1
        jsr asr1
asr1:   lda S2P_A+1
        cmp #$80
        ror S2P_A+1
        ror S2P_A
        rts

; S2P_A = A - 1 unless S2P_A - A is negative (upstream's cmp, bmi)
at_most:
        sta S2P_C
        sec
        lda S2P_A
        sbc S2P_C
        lda S2P_A+1
        sbc #0
        bmi :+
        ldx S2P_C
        dex
        stx S2P_A
        stz S2P_A+1
:       rts
