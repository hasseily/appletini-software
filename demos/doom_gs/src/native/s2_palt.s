; s2_palt.s: part s2pal's test image glue (docs/m11-parts/s2pal.md). Not
; part of the game. Assembled twice: with -D P2DW for the image s2pp in
; P2DW's room (s2_pal and s2_pub: a level's frames), and without for s2pf
; in WIW's room (s2_pal, s2_nib, s2_pub: every frame, pictures too).
;
; tools/native/s2pal.py stages up to 16 cases in RamWorks:
;
;   bank T_STAGE    case k at $0200 + k * $800: +$000 PALST (768 bytes,
;                   the native form), +$300 the screen's $9D00-$9FFF,
;                   +$600 the inputs (I_*), +$610 the steps (3 bytes each:
;                   an op, a low and a high byte, a picture's j after its
;                   step; op 0 ends)
;   bank T_TINTS    TINTPAL j at $0200 + j * $1600
;   bank T_PICS     picture j's bytes from its offset 32,000 at $0200 +
;                   j * $1400
;
;   s2y_case    A = k: the case's PALST into S2STATE, its screen bytes
;               into aux 0, its inputs into their places (the player,
;               the menu flag, P_STPALETTE, HU_ON, HU_NEW, GAMMA), its
;               TINTPAL into S2PAL when it is not there; then, in the
;               cost phase 30, s2_palget, the steps, and (I_FLAGS bit 0)
;               a band of rows 100-101 published by s2_publish
;   s2y_end     s2_finish, s2_palput (phase 30)
;
; MARKER ($BFF0) gets the case's number first (the write log's cut),
; CLEARED and RELOADED the C of s2_stripearly and s2_reload.
;
; Zero page $80-$87 (the menu's and the automap's in their images).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2pal.inc"

        .export s2y_case, s2y_end
        .export s2_palst, s2_begun, s2_marks
        .import s2_palget, s2_palput, s2_finish, s2_setpal, s2_viewpal
        .import s2_stripearly, st_palette, s2_publish, s2_reload
        .import far_get, far_put
.ifndef P2DW
        .export s2_nbuf
        .import s2_picpal
.endif

s2_palst = PALST_W
s2_begun = PALST_W + PS_BEGUN
.ifdef P2DW
s2_marks = P2DW_MARKS
BAND     = P2DW_RT0
.else
s2_marks = WIW_MARKS
BAND     = WIW_RT0
s2_nbuf  = WIW_RT2              ; a nibble slot's 5 pages
.endif
DRB      = s2_marks
DRE      = s2_marks + $40
MARKER   = $BFF0                ; the case's number (the write log's cut)
CLEARED  = $BFF1                ; s2_stripearly's C
RELOADED = $BFF2                ; s2_reload's C

T_STAGE  = 61
T_TINTS  = 63
T_PICS   = 62

I_DAMAGE = $600
I_STRENGTH = $602
I_BONUS  = $604
I_IRON   = $606
I_MENU   = $608
I_STPAL  = $60A
I_HUON   = $60B
I_HUNEW  = $60C
I_GAMMA  = $60D
I_TINT   = $60E
I_FLAGS  = $60F
I_STEPS  = $610

OP_SETPAL = 1
OP_VIEWPAL = 2
OP_STRIP = 3
OP_STPAL = 4
OP_PICTURE = 5                  ; low, high: the lump; then the picture j
OP_RELOAD = 6

T_K      = $80
T_BASE   = $81                  ; the case's page in T_STAGE
T_STEP   = $82
T_TINT   = $83                  ; the TINTPAL in S2PAL (+1: none yet)
T_N      = $84

        .segment "S2CODE"

s2y_case:
        stz PHASE
        sta T_K
        sta MARKER
        stz CLEARED
        stz RELOADED
        asl a                   ; $0200 + k * $800
        asl a
        asl a
        clc
        adc #2
        sta T_BASE
        lda #T_STAGE              ; PALST into S2STATE (through the band)
        ldx #0
        ldy #3
        jsr fetch
        lda #S2STATE
        ldx #>SS_PALST
        ldy #3
        jsr store
        lda #T_STAGE              ; the screen's $9D00-$9FFF
        ldx #3
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
        sta RAMWRTOFF
        lda #T_STAGE              ; the inputs and steps
        ldx #6
        ldy #1
        jsr fetch
        ldx #1
:       lda BAND+I_DAMAGE-$600,x
        sta S2P_PLAYER+S2P_DAMAGE,x
        lda BAND+I_STRENGTH-$600,x
        sta S2P_PLAYER+S2P_STRENGTH,x
        lda BAND+I_BONUS-$600,x
        sta S2P_PLAYER+S2P_BONUS,x
        lda BAND+I_IRON-$600,x
        sta S2P_PLAYER+S2P_IRONFEET,x
        lda BAND+I_MENU-$600,x
        sta S2P_MENUACTIVE,x
        dex
        bpl :-
        lda BAND+I_STPAL-$600
        sta P_STPALETTE
        lda BAND+I_HUON-$600
        sta HU_ON
        lda BAND+I_HUNEW-$600
        sta HU_NEW
        lda BAND+I_GAMMA-$600
        sta GAMMA
        stz GAMMA+1
        lda BAND+I_TINT-$600    ; TINTPAL j, unless it is there
        inc a
        cmp T_TINT
        beq @tinted
        sta T_TINT
        dec a
        sta T_N                 ; $0200 + j * $1600: page 2 + j * 22
        asl a
        asl a
        asl a
        adc T_N                 ; (j < 8: no carry)
        adc T_N
        adc T_N
        asl a
        adc #2
        tax
        lda #T_TINTS
        ldy #21
        jsr fetchp
        lda #S2PAL
        ldx #>S2P_TINTPAL
        ldy #21
        jsr store
        lda #T_STAGE              ; (the steps again: the band changed)
        ldx #6
        ldy #1
        jsr fetch
@tinted:
        ldx #$1F                ; the steps out of the band's way
:       lda BAND+I_STEPS-$600,x
        sta steps,x
        dex
        bpl :-
        lda BAND+I_FLAGS-$600
        sta flags
        lda #PHV_2D
        sta PHASE
        jsr s2_palget
        stz T_STEP
@step:  ldx T_STEP
        lda steps,x
        beq @steps
        inx
        inx
        inx
        stx T_STEP
        ldy steps-2,x           ; the argument
        cmp #OP_SETPAL
        bne :+
        tya
        jsr s2_setpal
        bra @step
:       cmp #OP_VIEWPAL
        bne :+
        tya
        jsr s2_viewpal
        bra @step
:       cmp #OP_STRIP
        bne :+
        tya
        jsr s2_stripearly
        lda #0                  ; its C: the strip's clear
        rol a
        sta CLEARED
        bra @step
:       cmp #OP_STPAL
        bne :+
        jsr st_palette
        bra @step
:       cmp #OP_RELOAD
        bne :+
        jsr s2_reload
        lda #0                  ; its C: PALW's rebuild
        rol a
        sta RELOADED
        bra @step
:
.ifndef P2DW
        cmp #OP_PICTURE
        bne @bad
        lda #T_PICS               ; picture j (the byte after the step)
        sta S2_PBANK
        lda steps,x
        sta T_N                 ; $0200 + j * $1400: page 2 + j * 20
        asl a
        asl a
        adc T_N
        asl a
        asl a
        adc #2
        sta S2_PADDR+1
        stz S2_PADDR
        inx
        stx T_STEP
        lda steps-3,x           ; the lump: low, high
        pha
        lda steps-2,x
        tax
        pla
        jsr s2_picpal
        bra @step
.endif
@bad:   brk
@steps: lda flags
        and #1
        beq @done
        stz PHASE               ; the band: rows 100-101, every byte
        ldx #0
:       txa
        eor #$5A
        sta BAND,x
        eor #$FF
        sta BAND+160,x
        inx
        cpx #160
        bne :-
        stz DRB
        stz DRB+1
        lda #160
        sta DRE
        sta DRE+1
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        lda #100
        sta S2_Y0
        lda #102
        sta S2_Y1
        stz S2_DRY0
        lda #2
        sta S2_DRY1
        lda #PHV_2D
        sta PHASE
        jsr s2_publish
@done:  stz PHASE
        rts

s2y_end:
        lda #PHV_2D
        sta PHASE
        jsr s2_finish
        jsr s2_palput
        stz PHASE
        rts

; fetch: Y pages of bank A from the case's page + X into the band
fetch:  pha
        txa
        clc
        adc T_BASE
        tax
        pla
; fetchp: Y pages of bank A from page X into the band
fetchp: sta FA_BANK
        stx FA_SRC+1
        stz FA_SRC
        lda #<BAND
        sta FA_DST
        lda #>BAND
        sta FA_DST+1
        stz FA_N
        sty T_N                 ; (far_get changes Y)
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dec T_N
        bne :-
        rts

; store: Y pages of the band into bank A from page X
store:  sta FA_BANK
        stx FA_DST+1
        stz FA_DST
        lda #<BAND
        sta FA_SRC
        lda #>BAND
        sta FA_SRC+1
        stz FA_N
        sty T_N                 ; (far_put changes Y)
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dec T_N
        bne :-
        rts

        .segment "S2DATA"
steps:  .res 32
flags:  .res 1
