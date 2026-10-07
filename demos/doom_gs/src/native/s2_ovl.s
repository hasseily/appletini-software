; s2_ovl.s: the automap's overlay, the image OVLW (docs/SCREENS.md, the
; automap; part s2ovl). A GPL-2 rewrite in 65C02 of upstream's
; src/iigs/am_map65.s: AM_Drawer's overlay path with titleBand, drawLines,
; plot's overlay case ovl (recOvl of r_list65.s inline, with lists.inc's
; FSCUTE), rowColors, and the rotation's fast path (fastSetup, sq16, w16,
; fastLine, fpoint, smul) [R am_map65.s:1033- 1058, :1179-1219, :1337-1352,
; :1461-1509, :1893-2352, :2843-2861; lists.inc:65-106]. The window, the
; ticker, the walls, the arrow, the clip and the line loops are part
; s2amap's s2_amline.s, which OVLW links with its fast path's hook.
;
; Upstream's overlay appends a K_OVL record for each pixel of the map's
; lines to the list of its column, after the view's records, and cuts the
; fill spans of the column at the pixel's row [R am_map65.s:1461-1509];
; R_DrawLists then draws them over the view. Natively OVLW runs in
; the renderer's frame between the masked phase (nm_masked: its last batch
; staged) and the bucket pass: it is loaded by far_pload from its bank
; (OVLW_BANK) into MASKW's code room, and am_ovl makes the records through
; the masked copy of rrec.s (mrec_room: the page model of upstream's
; lists; the column byte after the kind, as every staged record), cuts
; FSTOP/FSBOT as FSCUTE, stages its last batch, and ends by calling OVLW's
; own copy of bucket.s's nm_bkload (BKFAR and BKFAR2 are data in OVLW, as
; in MASKW: MASKW is not loaded again). The replay draws the records
; (their kind K_OVL).
;
;   am_ovl      A = the frame's tics: AM_Ticker for each (s2_amline's
;               am_ticker, with the player's last position), then
;               AM_Drawer's overlay (nothing but the tics when the
;               automap is not on with its overlay); the state block from
;               and to S2STATE's SS_AMAPW; then nm_bkload. Entered by the
;               jump at OVLW_LO ($6800), the image's first bytes.
;   am_fastsetup, am_fastline   the fast path's hook (s2_amline.s built
;               with -D AM_FASTLINE)
;   am_seg, am_plot, am_rowcol  what s2_amline.s needs of the linking
;               image (a line on the screen drawn at once; a pixel a
;               K_OVL record; a row's nibbles)
;
; titleBand: when am_band is 0 (the view drew rows 160-167 since the map
; last showed), the title band's rows 160-167 go black on the screen at
; once (CPU stores, one RAMWRT window) and S2_MAIL's MAIL_AMTITLE tells
; P2DW the title's text is not on the screen (upstream clears
; iigs_textShown+2) [R am_map65.s:1203-1219]. Upstream blacks the back
; buffer's rows and shows them at I_FinishUpdate; the frame's final screen
; is the same.
;
; The rows' colours: each row's palette as rowColors sees it: display's
; I_ViewPalette(0) first (a view frame [R d_main65.s:443-450]: all 168
; rows palette 0 when viewpal was another), else the palette state's scb
; (SS_PALST, as P2DW left it); the ten colours' nibbles of each palette
; (at most 4) from S2NIB into NCACHE, as part s2amap's nibcache.
;
; Places: the code from $6800; at run time $9400-$9BFF (the nibble pages,
; NCACHE, RBASE, the fast path's variables, s2_amline's W variables AMW
; at $9A00, the state block AMST at $9B00), all in MASKW's code room
; (the renderer's other W ranges untouched: the records go through
; mrec_room's batch BATCH, the renderer's). Zero page: s2_amline's AMZ
; ($80-$AE), the math block, the far layer's FA_*, MRB and RSEQ (the
; masked copy of rrec.s), bucket.s's BK_P and BK_Q (nm_bkload): overlay 2
; is dead after the masked phase and the bucket pass sets its own later.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2amap.inc"

; AMW (s2_amline's W variables, $9A00) and AMST (the state block, $9B00)
; are the makefile's (-D, the same for s2_amline.s: src/native/m11/
; s2ovl.mk)
.ifndef AMW
        .error "AMW is the makefile's"
.endif
.ifndef AMST
        .error "AMST is the makefile's"
.endif
        .include "s2_am.inc"

        .export am_ovl, am_seg, am_plot, am_rowcol
        .export am_fastsetup, am_fastline, ovl_tail
        .import am_ticker, am_walls, am_players, am_drawfl, am_getmo
        .import am_setauto, am_tomap, toscreen, clipscr
        .import mrec_room, mrec_flush, nm_bkload
        .import far_get, far_put, fixmul, umul16

K_OVL     = 10                  ; lists.inc: the kind (bucket.s's too)
OVLREC_SIZE = 5                 ; K_OVL, the column, the row, keep, colour
VIEW_ROWS = AM_FH               ; I_ViewPalette's rows (168)
VIEW_PAL  = 0                   ; a view frame's palette (display)
NSLOTS    = 4

NBUF    = $9400                 ; the nibble tables' pages of a palette
NCACHE  = $9800                 ; 4 palettes x 40: the colours' nibbles
RBASE   = NCACHE + 160          ; each row's base in NCACHE (168)
OVV     = RBASE + 168           ; this file's variables
AMTICS2 = OVV + 0               ; am_ovl's tics
SLOTP   = OVV + 1               ; the palettes of the slots (4)
RF_OK   = OVV + 5               ; the fast turn this frame (fastSetup)
RF_MC   = OVV + 6               ; |s cos| (0.16), then its sign (bit 7)
RF_SC   = OVV + 8
RF_MS   = OVV + 9               ; |s sin|, then its sign
RF_SS   = OVV + 11
RF_OX   = OVV + 12              ; the origin, map units (int16)
RF_OY   = OVV + 14
RF_CX   = OVV + 16              ; its screen point (int16 x, y)
RF_CY   = OVV + 18
RF_DX   = OVV + 20              ; an end from the origin (int16)
RF_DY   = OVV + 22
RF_P    = OVV + 24              ; a product (int32)
RF_S    = OVV + 28              ; smul's sign
RF_PT   = OVV + 30              ; the origin as a map point (int32 x, y)
OVV_END = OVV + 38              ; (fpoint's point: PA, FL or FL + 4)

        .assert OVV_END <= AMW, error, "OVLW's variables"
        .assert AMW_END <= AMST, error, "the W variables"
        .assert ST_END <= OVLW_HI, error, "the state block"
        .assert AMZ_END <= $B0, error, "the zero page"
        .import __S2CODE_RUN__, __S2CODE_SIZE__
        .assert NBUF >= __S2CODE_RUN__ + __S2CODE_SIZE__, lderror, "NBUF"

; ---------------------------------------------------------------------------
; The image's first bytes: its entry (the frame driver's jsr OVLW_LO)
; ---------------------------------------------------------------------------
        .segment "OVLHEAD"
        jmp am_ovl

        .segment "S2CODE"

; ===========================================================================
; am_ovl: the tics, then AM_Drawer's overlay [R am_map65.s:1033-1058]
; ===========================================================================
am_ovl:
        sta AMTICS2
        jsr ovl_load
        jsr ovl_mail
        jsr am_getmo
@tic:   lda AMTICS2             ; AM_Ticker once a tic
        beq @draw
        jsr am_ticker
        dec AMTICS2
        bra @tic
@draw:  lda ST_MODE             ; the overlay on (the half views are
        and #AMF_ACTIVE | AMF_OVERLAY   ;   not built)
        cmp #AMF_ACTIVE | AMF_OVERLAY
        bne @end
        lda #1                  ; AM_MODE: the overlay
        sta ST_AMMODE
        ldx #0                  ; the lines' rows: below the strip when a
        lda HU_ON               ;   message is on, above the title
        beq :+
        ldx #AM_STRIP
:       stx AWTOP
        stx PLO
        lda #AM_TITLEY
        sta AWBOT
        sta PHI
        jsr titleband
        jsr nibcache
        stz RF_OK               ; (no fast turn unless fastSetup says so)
        jsr am_walls            ; drawLines: the walls, the arrow
        jsr am_players
        stz ST_VALID            ; a view frame: display zeroes am_valid
        stz ST_VALID+1          ;   after R_DrawLists [R d_main65.s:503]
@end:   jsr am_setauto
        jsr ovl_save
        jsr mrec_flush          ; the overlay's last batch
ovl_tail:
        jmp nm_bkload           ; BKFAR, BKFAR2 into main (OVLW's copies)

; ---------------------------------------------------------------------------
; ovl_load, ovl_save: the state block from and to S2STATE's SS_AMAPW
; ---------------------------------------------------------------------------
ovl_load:
        lda #<SS_AMAPW
        sta FA_SRC
        lda #>SS_AMAPW
        sta FA_SRC+1
        lda #<AMST
        sta FA_DST
        lda #>AMST
        sta FA_DST+1
        jsr stbank
        jmp far_get
ovl_save:
        lda #<AMST
        sta FA_SRC
        lda #>AMST
        sta FA_SRC+1
        lda #<SS_AMAPW
        sta FA_DST
        lda #>SS_AMAPW
        sta FA_DST+1
        jsr stbank
        jmp far_put
stbank: lda #S2STATE
        sta FA_BANK
        lda #<(ST_END - AMST)
        sta FA_N
        rts

; ovl_mail: S2_MAIL's AM_Stop of the tics and a view drawn without
; the overlay since the automap last ran (display zeroes am_valid and
; am_band then [R d_main65.s:497-503]), as AMAPW's am_mail
ovl_mail:
        lda S2_MAIL
        and #MAIL_AMSTOP
        beq :+
        lda ST_AMMODE           ; AM_Stop [R am_map65.s:228-236]: the half
        cmp #2                  ;   overlay ends at the next view
        bne @stop
        lda #3
        sta ST_AMMODE
@stop:  stz ST_MODE
        stz ST_MODE+1
        lda #1
        sta ST_STOPPED
        stz ST_STOPPED+1
        lda S2_MAIL
        and #<~MAIL_AMSTOP
        sta S2_MAIL
:       lda S2_MAIL
        and #MAIL_AMVIEW
        beq :+
        stz ST_VALID
        stz ST_VALID+1
        stz ST_BAND
        stz ST_BAND+1
        lda S2_MAIL
        and #<~MAIL_AMVIEW
        sta S2_MAIL
:       rts

; ---------------------------------------------------------------------------
; titleband: titleBand [R am_map65.s:1203-1219]: once (am_band 0), the
; title's rows black on the screen, the title's text gone (MAIL_AMTITLE)
; ---------------------------------------------------------------------------
TITLE_AT = SHR + AM_TITLEY * 160
titleband:
        lda ST_BAND
        ora ST_BAND+1
        bne @done
        lda #1
        sta ST_BAND
        lda S2_MAIL
        ora #MAIL_AMTITLE
        sta S2_MAIL
        ldx #0                  ; 8 rows: 5 runs of 256 bytes
        lda #0
        sta RAMWRTON
:       .repeat (AM_FH - AM_TITLEY) * 160 / 256, k
        sta TITLE_AT + k * 256,x
        .endrepeat
        inx
        bne :-
        sta RAMWRTOFF
@done:  rts
        .assert (AM_FH - AM_TITLEY) * 160 .mod 256 = 0, error, "the title"

; ---------------------------------------------------------------------------
; nibcache: each row's palette (display's I_ViewPalette(0) applied, else
; the palette state's scb), the ten colours' nibbles of each palette
; from S2NIB (upstream's NIBTAB: left even, left odd, right even, right
; odd pages) into NCACHE, and each row's base in it (slot * 40 + parity
; * 20; the left nibbles, the right ones 10 on) [R am_map65.s:2843-2861;
; i_viigs65.s:510-519, :738-783]
; ---------------------------------------------------------------------------
nibcache:
        lda #<(SS_PALST + PS_SCB)
        sta FA_SRC
        lda #>(SS_PALST + PS_SCB)
        sta FA_SRC+1
        lda #<NBUF
        sta FA_DST
        lda #>NBUF
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        lda #VIEW_ROWS
        sta FA_N
        jsr far_get
        lda #<(SS_PALST + PS_VIEWPAL)
        sta FA_SRC
        lda #>(SS_PALST + PS_VIEWPAL)
        sta FA_SRC+1
        lda #<AT0
        sta FA_DST
        stz FA_DST+1
        lda #S2STATE
        sta FA_BANK
        lda #1
        sta FA_N
        jsr far_get
        lda AT0                  ; I_ViewPalette(VIEW_PAL): every view row
        cmp #VIEW_PAL           ;   gets it when the view had another
        beq :+
        ldx #VIEW_ROWS - 1
        lda #VIEW_PAL
@all:   sta NBUF,x
        dex
        cpx #$FF
        bne @all
:       ldx #NSLOTS - 1         ; the slots: none
        lda #$FF
:       sta SLOTP,x
        dex
        bpl :-
        stz AT1                  ; the slots used
        ldy #0
@row:   lda NBUF,y
        cmp #16
        jcs bad
        ldx #0
:       cpx AT1
        beq @newslot
        cmp SLOTP,x
        beq @found
        inx
        bra :-
@newslot:
        cpx #NSLOTS
        jcs bad
        sta SLOTP,x
        inc AT1
@found: lda slot40,x            ; slot * 40 + (row & 1) * 20
        sta AT2
        tya
        and #1
        beq :+
        lda #20
:       clc
        adc AT2
        sta RBASE,y
        iny
        cpy #VIEW_ROWS
        bne @row
        stz AT3                  ; each slot's nibbles
@slot:  ldx AT3
        cpx AT1
        beq @done
        lda SLOTP,x             ; S2NIB + palette * $400 -> NBUF
        asl a
        asl a
        clc
        adc #>S2P_NIB
        sta FA_SRC+1
        stz FA_SRC
        lda #<NBUF
        sta FA_DST
        lda #>NBUF
        sta FA_DST+1
        lda #S2PAL
        sta FA_BANK
        ldx #4                  ; 4 pages, 256 bytes a call
:       stz FA_N
        phx
        jsr far_get
        plx
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        ldx AT3
        lda slot40,x
        tax
        ldy #0
@col:   phy
        lda colours,y
        tay
        lda NBUF,y              ; the left pixel, even row
        sta NCACHE,x
        lda NBUF + $200,y       ; the right pixel, even row
        sta NCACHE+10,x
        lda NBUF + $100,y       ; the left pixel, odd row
        sta NCACHE+20,x
        lda NBUF + $300,y       ; the right pixel, odd row
        sta NCACHE+30,x
        ply
        inx
        iny
        cpy #AM_NCOLOURS
        bne @col
        inc AT3
        bra @slot
@done:  rts
bad:    lda #PL_AMPALS          ; more than 4 palettes (impossible
        sta PL_STATUS           ;   upstream: the view's and the strip's)
        brk
        .byte 0

slot40: .byte 0, 40, 80, 120
colours: AM_COLOURS

; am_rowcol: NIBH, NIBL of the colour COLI in the row LNY (rowColors)
am_rowcol:
        ldx LNY
        lda RBASE,x
        clc
        adc COLI
        tax
        lda NCACHE,x
        sta NIBH
        lda NCACHE+10,x
        sta NIBL
        rts

; ---------------------------------------------------------------------------
; am_seg: a line on the screen (FL, clipped; COLI): drawn at once, its
; rows AWTOP .. AWBOT - 1 (PLO, PHI)
; ---------------------------------------------------------------------------
am_seg: jmp am_drawfl

; ---------------------------------------------------------------------------
; am_plot: plot's overlay case [R am_map65.s:1337-1352, :1461-1509]: the
; pixel PX of the row LNY, when the row is one of the lines' (PLO .. PHI
; - 1), a K_OVL record of its column (the byte PX / 2): the row, the
; nibble to keep (x even: the low one, $0F), the colour's nibble (NIBH,
; or NIBL for an odd x); then FSCUTE: the column's top span ends at the
; row, its bottom span starts after it
; ---------------------------------------------------------------------------
am_plot:
        lda LNY
        cmp PLO
        bcc @out
        cmp PHI
        bcs @out
        lda PX+1                ; X = the column, C = x odd
        lsr a
        lda PX
        ror a
        tax
        php
        lda #OVLREC_SIZE
        jsr mrec_room           ; (keeps X; Y = the batch's free byte)
        lda #K_OVL
        sta BATCH,y
        iny
        txa
        sta BATCH,y
        iny
        lda LNY
        sta BATCH,y
        iny
        plp
        bcs @odd
        lda #$0F                ; x even: keep the low nibble
        sta BATCH,y
        iny
        lda NIBH
        bra @col
@odd:   lda #$F0                ; x odd: keep the high nibble
        sta BATCH,y
        iny
        lda NIBL
@col:   sta BATCH,y
        iny
        sty MRB
        lda LNY                 ; FSCUTE: the end LNY + 1, the first LNY
        inc a
        cmp FSBOT,x
        bcc :+
        beq :+
        sta FSBOT,x
:       lda LNY
        cmp FSTOP,x
        bcs @out
        sta FSTOP,x
@out:   rts

; ===========================================================================
; The rotation's fast path [R am_map65.s:1893-2352]: 4 products of 16 x 16
; an end instead of the 32-bit rotation and transform; upstream's overlay
; takes it whenever |s cos| and |s sin| stay below 0.25 (s = scale_mtof /
; 2^20), and its rounding is not the 32-bit path's, so OVLW has it too.
; Upstream's vertex cache (lvCheck, lvFrame, VS_TAB) only saves the
; products of an end two lines share: the same point either way, so OVLW
; computes each end (the pixels are the same).
; ===========================================================================

; am_fastsetup: fastSetup, after s2_amline's wallrot (ARTC, ARTS the cosine
; and sine, RTOX, RTOY the origin): RF_OK = 1 and the constants, or 0
; when |s cos| or |s sin| is 0.25 or more [R am_map65.s:1893-1925]
am_fastsetup:
        stz RF_OK
        ldx #ARTC - AMW
        jsr sq16
        bcs @none
        sta RF_MC
        stx RF_MC+1
        sty RF_SC
        ldx #ARTS - AMW
        jsr sq16
        bcs @none
        sta RF_MS
        stx RF_MS+1
        sty RF_SS
        ldx #RTOX - AMW         ; RF_OX = w16(the origin's x)
        jsr w16
        sta RF_OX
        stx RF_OX+1
        ldx #RTOY - AMW
        jsr w16
        sta RF_OY
        stx RF_OY+1
        PTR PA, RF_PT           ; the origin as a map point: toMap(RF_OX),
        lda RF_OX               ;   toMap(RF_OY)
        ldx RF_OX+1
        jsr am_tomap
        PTR PA, RF_PT+4
        lda RF_OY
        ldx RF_OY+1
        jsr am_tomap
        PTR PA, RF_PT           ; RF_CX, RF_CY: its screen point
        PTR PB, RF_CX
        jsr toscreen
        lda #1
        sta RF_OK
@none:  rts
        .assert RF_CY = RF_CX + 2, error, "RF_CX, RF_CY"

; sq16: A:X = |FixedMul(the int32 at AMW + X, scale_mtof)| >> 4 (0.16),
; Y = its sign ($80 or 0); C = 1 when it is 0.25 or more (the magnitude's
; high word 4 or more) [R am_map65.s:1927-1964]
sq16:
        ldy #0
:       lda AMW,x
        sta M_A,y
        lda ST_SCALE,y
        sta M_B,y
        inx
        iny
        cpy #4
        bne :-
        jsr fixmul
        ldy #0
        lda M_R+3
        bpl @pos
        ldy #$80                ; negative: the magnitude
        sec
        ldx #0
:       lda #0
        sbc M_R,x
        sta M_R,x
        inx
        txa
        eor #4
        bne :-
@pos:   lda M_R+3               ; the high word 4 or more: no fast turn
        bne @big
        lda M_R+2
        cmp #4
        bcs @big
        ldx #4                  ; >> 4: bits 4-19 of the magnitude
:       lsr M_R+2
        ror M_R+1
        ror M_R
        dex
        bne :-
        lda M_R
        ldx M_R+1
        clc
        rts
@big:   sec
        rts

; w16: A:X = the int32 at AMW + X >> MAPBITS (12, arithmetic), clamped to
; the int16 range [R am_map65.s:2323-2352]
w16:
        lda AMW+2,x             ; its high word + $0800 below $1000: in
        sta AT0                  ;   range
        lda AMW+3,x
        sta AT1
        clc
        lda AT0
        adc #<$0800
        lda AT1
        adc #>$0800
        cmp #$10
        bcc @in
        lda AT1                 ; out of range: $7FFF or $8000
        bmi @neg
        lda #$FF
        ldx #$7F
        rts
@neg:   lda #$00
        ldx #$80
        rts
@in:    lda AMW+1,x             ; (high word << 4) | (low word >> 12)
        sta AT2
        ldy #4
:       lsr AT2
        dey
        bne :-
        lda AT0
        asl a
        asl a
        asl a
        asl a
        ora AT2
        pha
        lda AT1
        asl a
        asl a
        asl a
        asl a
        sta AT2
        lda AT0
        lsr a
        lsr a
        lsr a
        lsr a
        ora AT2
        tax
        pla
        rts

; am_fastline: fastLine of the line in LB in the colour COLI [R
; am_map65.s:1966-2063]: C = 1 when the fast turn drew it (or found no
; part of it on the screen), C = 0 when the slow path is to draw it (no
; rotation, no fast turn this frame, or an end too far for int16)
am_fastline:
        lda ST_MODE
        and #AMF_ROTATE
        beq @slow
        lda RF_OK
        beq @slow
        ldx #AM_LV1X            ; the first end
        lda #<FL
        ldy #>FL
        jsr fend
        bcs @slow
        ldx #AM_LV2X            ; the second end
        lda #<(FL + 4)
        ldy #>(FL + 4)
        jsr fend
        bcs @slow
        jsr clipscr
        bcc @drawn
        jsr am_seg
@drawn: sec
        rts
@slow:  clc
        rts

; fend: the end at LB + X (int16 x, y) to the screen point at Y:A (fpoint):
; C = 1 when x - RF_OX or y - RF_OY overflows int16 (too far)
fend:
        sta PA
        sty PA+1
        sec                     ; RF_DX = x - RF_OX
        lda LB,x
        sbc RF_OX
        sta RF_DX
        lda LB+1,x
        sbc RF_OX+1
        sta RF_DX+1
        bvs @far
        sec                     ; RF_DY = y - RF_OY
        lda LB+2,x
        sbc RF_OY
        sta RF_DY
        lda LB+3,x
        sbc RF_OY+1
        sta RF_DY+1
        bvs @far
        jsr fpoint
        clc
        rts
@far:   sec
        rts
        .assert AM_LV1Y = AM_LV1X + 2 && AM_LV2Y = AM_LV2X + 2, error, "the line's ends"

; fpoint: (PA) = the screen point of RF_DX, RF_DY [R am_map65.s:
; 2219-2266]: x = CX + hi(dx c' - dy s'), y = CY - hi(dx s' + dy c'),
; c' = s cos, s' = s sin (RF_MC, RF_MS with their signs)
fpoint:
        ldx #RF_DX - OVV        ; P = dx c'
        ldy #RF_MC - OVV
        jsr smul
        jsr keep_p
        ldx #RF_DY - OVV        ; - dy s': its high word, + CX
        ldy #RF_MS - OVV
        jsr smul
        sec
        lda RF_P
        sbc M_R
        lda RF_P+1
        sbc M_R+1
        lda RF_P+2
        sbc M_R+2
        sta AT0
        lda RF_P+3
        sbc M_R+3
        sta AT1
        clc
        lda AT0
        adc RF_CX
        sta (PA)
        lda AT1
        adc RF_CX+1
        ldy #1
        sta (PA),y
        ldx #RF_DX - OVV        ; P = dx s'
        ldy #RF_MS - OVV
        jsr smul
        jsr keep_p
        ldx #RF_DY - OVV        ; + dy c': its high word, CY less it
        ldy #RF_MC - OVV
        jsr smul
        clc
        lda RF_P
        adc M_R
        lda RF_P+1
        adc M_R+1
        lda RF_P+2
        adc M_R+2
        sta AT0
        lda RF_P+3
        adc M_R+3
        sta AT1
        sec
        lda RF_CY
        sbc AT0
        ldy #2
        sta (PA),y
        lda RF_CY+1
        sbc AT1
        iny
        sta (PA),y
        rts

keep_p: ldx #3
:       lda M_R,x
        sta RF_P,x
        dex
        bpl :-
        rts

; smul: M_R = the int16 at OVV + X times the 0.16 magnitude at OVV + Y
; (below $4000) with the sign at OVV + Y + 2 (RF_SC for RF_MC, RF_SS for
; RF_MS: bit 7), signed 32 bits [R am_map65.s:2268-2321: quarter squares
; of |a| and |m|, exact; here umul16]
smul:
        lda OVV+2,y             ; the sign: m's, turned when a < 0
        sta RF_S
        lda OVV,y
        sta M_B
        lda OVV+1,y
        sta M_B+1
        lda OVV,x
        sta M_A
        lda OVV+1,x
        sta M_A+1
        bpl @pos
        sec                     ; |a| ($8000 stays $8000: 32,768)
        lda #0
        sbc M_A
        sta M_A
        lda #0
        sbc M_A+1
        sta M_A+1
        lda RF_S
        eor #$80
        sta RF_S
@pos:   jsr umul16
        lda RF_S
        bpl @done
        sec                     ; -(M_R)
        ldx #0
:       lda #0
        sbc M_R,x
        sta M_R,x
        inx
        txa
        eor #4
        bne :-
@done:  rts
        .assert RF_SC = RF_MC + 2 && RF_SS = RF_MS + 2, error, "RF_SC"
