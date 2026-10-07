; s2_mvid.s: the menu's video in MENUW (docs/SCREENS.md, the menu; part
; s2menu1). GPL-2: rewritten from upstream's src/iigs/i_viigs65.s (Doom8088:
; Apple IIgs Edition, GPL-2): I_MenuPalette, uiGrayTables, grayMap,
; uiDimAll, uiDimRect, uiFontNibbles, I_MenuPaletteBack, I_RestoreBackRect
; [R :877-957, :1556-1622, :2030-2402], and d_main65.s's static screen
; (staticUpToDate, restoreRect, skullRect, staticDrawn [R :561-624]).
;
; Upstream saves the screen into a bank, redraws every byte through
; UI_GRAY into its back buffer and copies the marked bytes to the screen.
; Natively the screen is saved by one memory-API COPY of aux
; 0 $2000-$9FFF to bank S2VIEW, and every frame composes 24-row bands in
; W: the saved rows fetched (far_get), each byte through the gray map of
; its row's saved palette, the menu drawn over them (s2_menu.s), the band
; published by s2_publish (CPU stores, RAMWRT). The close fetches the
; saved rows back into the band and publishes them whole, with the saved
; SCBs and palettes in PALST: upstream's black step, SCBs, bytes,
; palettes (s2_begin, s2_finish).
;
;   mv_open     I_MenuPalette's open: the state the close restores, the
;               save (memory API), every row's SCB the menu's palette,
;               mv_tables, the menu palette's colours, the palette state
;               of a new picture (black first, SCBs, colours after)
;   mv_tables   uiGrayTables (UI_GRAY from the saved palettes, grayMap's
;               lightness rule), the menu palette's nibble table in its
;               slot (buildNibtab of GSOVL's first record's pairs) and
;               uiFontNibbles (the font's reds, M_FONTBUF and the slot)
;   mv_band     A = a band's first screen row: the band's rows (S2_BAND,
;               S2_Y0, S2_Y1), no marks, each row's nibble pages (the
;               slot: every row is in the menu's palette), the saved SCBs
;               of its rows
;   mv_dim      uiDimRect clipped to the band: the rows S2M_R0 ..
;               S2M_R1 - 1, the bytes S2M_B0 .. S2M_B1 from the saved
;               screen through the gray map of each row's saved palette,
;               marked
;   mv_restore  I_RestoreBackRect: x S2M_X, y S2M_Y (signed), width
;               S2M_W, height S2M_A; its rows and bytes (clipped as
;               upstream) through mv_dim
;   mv_shade    bmFontShade [R m_menu65.s:2626-2667]: A = 1 the font's
;               reds dimmed (SAVE SETTINGS), 0 back
;   mv_close    I_MenuPaletteBack [R i_viigs65.s:2138-2203]: nothing
;               unless the menu's palette is on; the saved screen
;               published band by band, the saved SCBs and palettes, the
;               view's and strip's palettes, the palette state of a new
;               picture; a changed gamma: s2_reload (M_RELOAD when PALW
;               must rebuild a level's tints)
;   mv_static   staticUpToDate [R d_main65.s:564-596]: C = 1 when the
;               screen shows this menu version; a skull that moved or
;               blinked is put back (its old and new rectangles from the
;               saved screen, then the skull) and published
;   mv_drawn    staticDrawn [R d_main65.s:618-624]
;
; The image's places for the drawers (s2_marks, s2_fbuf, s2_fbpages,
; s2_begun, s2_palst) are exported here; their addresses are s2layout's.
; Zero page: S2_* (the drawers'), S2M_* ($80-$AF), FA_*; A, X, Y changed.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2menu1.inc"

        .export mv_open, mv_tables, mv_band, mv_dim, mv_restore, mv_shade
        .export mv_close, mv_static, mv_drawn, mv_full, mv_amem
        .export s2_marks, s2_fbuf, s2_begun, s2_palst
        .exportzp s2_fbpages
        .import far_get, far_put, s2_unmark, s2_mark, s2_publish
        .import s2_finish, s2_reload, s2_mul160
        .import m_skullrect, m_drawskull, m_page

s2_marks   = S2M_MARKS
s2_fbuf    = S2M_FBUF
s2_fbpages = S2M_FBPAGES
s2_palst   = S2M_PALST
s2_begun   = S2M_PALST + PS_BEGUN

PST     = S2M_PALST
ROWL    = S2M_MARKS + $80
ROWR    = S2M_MARKS + $C0
MENU_PAL = 9                    ; MENU_PAL [R i_viigs65.s:50-51]
NO_CHANGE = 100                 ; NO_PALETTE_CHANGE [R :65]
PALREC_PAIRS = 14 * 16 * 2      ; [R :60]
SAVE_LO = $2000                 ; aux 0 $2000-$9FFF to S2VIEW $2000
SAVE_N  = $8000
SAVED_SCB = SAVE_LO + $7D00     ; the saved SCBs and palettes in S2VIEW
SAVED_PAL = SAVE_LO + $7E00
TMP     = S2M_BAND              ; the band's bytes, free outside a frame's
                                ;   bands: mv_tables' palettes and pairs
FONT_N  = 16                    ; the reds 176-191 [R i_viigs65.s:2335-2398]
FONT_C0 = 176

; the memory API's raw FIFO transport in slot 7 (appletini-one
; README_MEMORY_API.md section 7)
SP_DATA    = $CFF0
SP_CTRL    = $CFF1
SP_POP     = $CFF2
SP_RELEASE = $CFFF
SP_ROM     = $C700

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; mv_open: I_MenuPalette when the menu's palette is off [R i_viigs65.s:
; 2062-2126]; the caller then draws every band (uiDimAll).
; ---------------------------------------------------------------------------
mv_open:
        lda PST+PS_PICTURE      ; what the close puts back
        sta M_PICTURE
        lda PST+PS_PICTURE+1
        sta M_PICTURE+1
        lda PST+PS_VIEWPAL
        sta M_VIEWPAL
        lda PST+PS_STRIPPAL
        sta M_STRIPPAL
        lda SM_GAMMA
        sta M_UIGAMMA
        jsr mv_amem             ; the screen, SCBs and palettes saved
        ldx #199                ; every row in the menu's palette
        lda #MENU_PAL
:       sta PST+PS_SCB,x
        dex
        cpx #$FF
        bne :-
        jsr mv_tables
        ldx #31                 ; the menu palette's colours: GSOVL's first
:       lda TMP+$200,x          ;   record (mv_tables left it at TMP+$200)
        sta PST+PS_PALETTE+MENU_PAL*32,x
        dex
        bpl :-
        lda #1
        sta M_PALON
        stz PST+PS_LEVELCOPY
        lda #NO_CHANGE
        sta PST+PS_NEWPAL
        lda #1
        sta PST+PS_PALCOUNT
        sta PST+PS_SCBCHANGED
        sta PST+PS_TXTINV       ; uiInvalidate (uiDimAll's)
        rts

; ---------------------------------------------------------------------------
; mv_amem: the save, one COPY request through the FIFO (interrupts masked
; meanwhile, as lload.s's am_send); a failure stops (PL_STATUS
; S2M_AMEMSTOP, then BRK): the close could not restore the screen.
; ---------------------------------------------------------------------------
mv_amem:
        php
        sei
        bit SP_RELEASE
        bit SP_ROM
        ldx #0
:       lda am_copy,x
        sta SP_DATA
        inx
        cpx #AM_COPY_N
        bne :-
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
        lda #0
        sta S2M_C
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec S2M_C
        bne @wait
        lda #$6F                ; (no reply came)
        bra @done
@ready: lda SP_DATA
        sta SP_POP
@done:  bit SP_RELEASE
        plp
        cmp #0
        bne :+
        rts
:       lda #S2M_AMEMSTOP
        sta PL_STATUS
        brk
        .byte 0

; ---------------------------------------------------------------------------
; mv_tables: UI_GRAY, the slot and the font's reds [R i_viigs65.s:874-953,
; :2227-2252, :2326-2402]; leaves GSOVL's first record's palette at
; TMP+$200 (32 bytes).
; ---------------------------------------------------------------------------
mv_tables:
        lda #S2VIEW             ; the saved palettes: 512 bytes at TMP
        sta FA_BANK
        stz FA_N
        lda #<SAVED_PAL
        sta FA_SRC
        lda #>SAVED_PAL
        sta FA_SRC+1
        stz FA_DST
        lda #>TMP
        sta FA_DST+1
        jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        jsr far_get
        stz S2M_A               ; uiGrayTables: each colour of each
        lda #>TMP               ;   palette, a word $0RGB at S2M_A, its
        sta S2M_A+1             ;   number X
        ldx #0
@gray:  ldy #1                  ; 3 R
        lda (S2M_A),y
        and #$0F
        sta S2M_C
        asl a
        adc S2M_C               ; (C clear: R <= 15)
        sta S2M_C
        dey                     ; + 6 G
        lda (S2M_A),y
        lsr a
        lsr a
        lsr a
        lsr a
        sta S2M_D
        asl a
        adc S2M_D
        asl a
        adc S2M_C
        sta S2M_C
        lda (S2M_A),y           ; + B
        and #$0F
        adc S2M_C
        ldy #0                  ; the gray: lightness / 30, at most 4
:       cmp #30
        bcc :+
        sbc #30
        iny
        cpy #4
        bcc :-
:       tya
        sta S2M_GRAY,x
        clc
        lda S2M_A
        adc #2
        sta S2M_A
        bcc :+
        inc S2M_A+1
:       inx
        bne @gray
        lda #$FF                ; no row map built from this UI_GRAY yet
        sta mv_mappal
        lda #S2PAL              ; GSOVL's first record: its 32 palette
        sta FA_BANK             ;   bytes at TMP+$200, its pairs at TMP
        lda #<S2P_GSOVL
        sta FA_SRC
        lda #>S2P_GSOVL
        sta FA_SRC+1
        stz FA_DST
        lda #>(TMP+$200)
        sta FA_DST+1
        lda #32
        sta FA_N
        jsr far_get
        lda #<(S2P_GSOVL+PALREC_PAIRS)
        sta FA_SRC
        lda #>(S2P_GSOVL+PALREC_PAIRS)
        sta FA_SRC+1
        stz FA_DST
        lda #>TMP
        sta FA_DST+1
        stz FA_N
        jsr far_get
        ldx #0                  ; buildNibtab [R :705-736]: the left
:       lda TMP,x               ;   pixel's even and odd rows, the right's
        and #$F0
        sta S2M_SLOT,x
        lda TMP,x
        asl a
        asl a
        asl a
        asl a
        sta S2M_SLOT+$100,x
        lda TMP,x
        and #$0F
        sta S2M_SLOT+$200,x
        lda TMP,x
        lsr a
        lsr a
        lsr a
        lsr a
        sta S2M_SLOT+$300,x
        inx
        bne :-
        ldy #0                  ; uiFontNibbles: each shade N, the colour
@font:  lda #$FF                ;   of the record nearest its red
        sta S2M_E               ;   (|R - red| + G + B, the first best)
        ldx #0
@col:   lda TMP+$200,x          ; G + B
        and #$0F
        sta S2M_C
        lda TMP+$200,x
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc S2M_C
        sta S2M_C
        lda TMP+$201,x          ; |R - red|
        and #$0F
        sec
        sbc font_reds,y
        bcs :+
        eor #$FF
        inc a
:       clc
        adc S2M_C
        cmp S2M_E
        bcs :+
        sta S2M_E
        txa
        lsr a
        sta S2M_F
:       inx
        inx
        cpx #32
        bcc @col
        lda S2M_F
        sta M_FONTBUF,y
        jsr shade1
        iny
        cpy #FONT_N
        bcc @font
        rts

; shade1: the slot's four entries of the shade Y (colour 176 + Y) for the
; palette index A (the right pixel's pages: A; the left's: A << 4).
; Changes A; X, Y kept.
shade1:
        sta S2M_SLOT+$200+FONT_C0,y
        sta S2M_SLOT+$300+FONT_C0,y
        asl a
        asl a
        asl a
        asl a
        sta S2M_SLOT+FONT_C0,y
        sta S2M_SLOT+$100+FONT_C0,y
        rts

; ---------------------------------------------------------------------------
; mv_shade: bmFontShade [R m_menu65.s:2629-2667]: A = 1 the shades from
; M_FONTBUF 6 brighter-indexed (at most 15: the dim ramp), 0 back.
; ---------------------------------------------------------------------------
mv_shade:
        sta S2M_C
        ldy #0
@next:  tya
        ldx S2M_C
        beq :+
        clc
        adc #6
        cmp #16
        bcc :+
        lda #15
:       tax
        lda M_FONTBUF,x
        jsr shade1
        iny
        cpy #FONT_N
        bcc @next
        rts

; ---------------------------------------------------------------------------
; mv_band: A = the band's first screen row.
; ---------------------------------------------------------------------------
mv_band:
        sta S2_Y0
        clc
        adc #S2M_BANDROWS
        cmp #200
        bcc :+
        lda #200
:       sta S2_Y1
        lda #<S2M_BAND
        sta S2_BAND
        lda #>S2M_BAND
        sta S2_BAND+1
        stz S2_CAP              ; no text capture (the HUD's)
        jsr s2_unmark
        lda S2_Y1               ; each row's nibble pages: the slot, by the
        sec                     ;   row's parity [R i_viigs65.s:766-787]
        sbc S2_Y0
        sta S2M_N
        ldx #0
:       txa
        clc
        adc S2_Y0
        and #1
        clc
        adc #>S2M_SLOT
        sta ROWL,x
        adc #2
        sta ROWR,x
        inx
        cpx S2M_N
        bcc :-
        lda #S2VIEW             ; the saved SCBs of the band's rows
        sta FA_BANK
        lda S2_Y0
        clc
        adc #<SAVED_SCB
        sta FA_SRC
        lda #>SAVED_SCB
        adc #0
        sta FA_SRC+1
        lda #<mv_scbs
        sta FA_DST
        lda #>mv_scbs
        sta FA_DST+1
        lda S2M_N
        sta FA_N
        jmp far_get

; ---------------------------------------------------------------------------
; mv_dim: uiDimRect [R i_viigs65.s:2259-2322] of the rows S2M_R0 ..
; S2M_R1 - 1 (screen rows) and the bytes S2M_B0 .. S2M_B1, clipped to the
; band. Each byte's right nibble (its low) and left nibble (its high)
; through UI_GRAY of the row's saved palette (a 256-byte map built when
; the palette changes); the rectangle marked.
; ---------------------------------------------------------------------------
mv_dim:
        lda S2M_R0              ; rows: max(R0, Y0) .. min(R1, Y1)
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       sta S2M_E
        lda S2M_R1
        cmp S2_Y1
        bcc :+
        lda S2_Y1
:       sta S2M_F
        lda S2M_E
        cmp S2M_F
        bcc :+
        rts
:       lda S2M_B1              ; the bytes of a row
        sec
        sbc S2M_B0
        inc a
        sta S2M_D
        lda S2M_E
@row:   sec                     ; the band row X
        sbc S2_Y0
        tax
        lda mv_scbs,x           ; the row's map
        and #$0F
        cmp mv_mappal
        beq :+
        jsr mv_map
:       txa                     ; the band row's byte B0: FA_DST, S2M_A
        jsr s2_mul160
        clc
        adc S2_BAND
        sta S2M_A
        txa
        adc S2_BAND+1
        sta S2M_A+1
        clc
        lda S2M_A
        adc S2M_B0
        sta S2M_A
        sta FA_DST
        lda S2M_A+1
        adc #0
        sta S2M_A+1
        sta FA_DST+1
        lda S2M_E               ; the saved row's byte B0
        jsr s2_mul160
        clc
        adc S2M_B0
        sta FA_SRC
        txa
        adc #>SAVE_LO
        sta FA_SRC+1
        lda #S2VIEW
        sta FA_BANK
        lda S2M_D
        sta FA_N
        jsr far_get
        ldy #0                  ; through the map
:       lda (S2M_A),y
        tax
        lda mv_map_t,x
        sta (S2M_A),y
        iny
        cpy S2M_D
        bne :-
        inc S2M_E
        lda S2M_E
        cmp S2M_F
        bcc @row
        lda S2M_B0              ; the mark (markVP's rectangle)
        sta S2_MB0
        lda S2M_B1
        sta S2_MB1
        lda S2M_R0
        cmp S2_Y0
        bcs :+
        lda S2_Y0
:       ldx S2M_F
        jmp s2_mark

; mv_map: A = a palette: mv_map_t[byte] = its two pixels' grays. X kept.
mv_map:
        sta mv_mappal
        phx
        asl a
        asl a
        asl a
        asl a
        sta S2M_T               ; UI_GRAY's row of the palette
        ldy #0                  ; Y: the byte, from 0
@hi:    tya
        lsr a
        lsr a
        lsr a
        lsr a
        ora S2M_T
        tax
        lda S2M_GRAY,x          ; the left pixel's gray, the high nibble
        asl a
        asl a
        asl a
        asl a
        sta S2M_T+1
@lo:    tya
        and #$0F
        ora S2M_T
        tax
        lda S2M_GRAY,x          ; the right pixel's, the low nibble
        ora S2M_T+1
        sta mv_map_t,y
        iny
        beq @done
        tya
        and #$0F
        bne @lo
        bra @hi
@done:  plx
        rts

; ---------------------------------------------------------------------------
; mv_restore: I_RestoreBackRect [R i_viigs65.s:1556-1622] with the menu's
; palette on (all menus use the saved screen): y0 = max(y, 0), y1 =
; min(y + h, 200), b0 = max(x, 0) >> 1, b1 = min(x + w - 1, 319) >> 1;
; mv_dim when not empty.
; ---------------------------------------------------------------------------
mv_restore:
        lda S2M_Y+1             ; y0
        bpl :+
        stz S2M_R0
        bra @y1
:       lda S2M_Y
        sta S2M_R0
@y1:    clc                     ; y1 = y + h, at most 200 (signed)
        lda S2M_Y
        adc S2M_A
        sta S2M_T
        lda S2M_Y+1
        adc #0
        sta S2M_T+1
        bmi @empty
        bne :+
        lda S2M_T
        cmp #201
        bcc :++
:       lda #200
        sta S2M_T
:       lda S2M_T
        sta S2M_R1
        lda S2M_X+1             ; b0
        bpl :+
        stz S2M_B0
        bra @b1
:       lda S2M_X+1
        lsr a
        lda S2M_X
        ror a
        sta S2M_B0
@b1:    clc                     ; b1: x + w - 1 (signed), > 319: 159
        lda S2M_X
        adc S2M_W
        sta S2M_T
        lda S2M_X+1
        adc S2M_W+1
        sta S2M_T+1
        lda S2M_T
        bne :+
        dec S2M_T+1
:       dec S2M_T
        lda S2M_T+1
        bmi @empty
        cmp #2
        bcs @max
        cmp #1
        bne :+
        lda S2M_T
        cmp #<320
        bcs @max
:       lda S2M_T+1
        lsr a
        lda S2M_T
        ror a
        bra :+
@max:   lda #159
:       sta S2M_B1
        lda S2M_R0              ; rectEmpty: y0 >= y1 or b0 > b1
        cmp S2M_R1
        bcs @empty
        lda S2M_B1
        cmp S2M_B0
        bcc @empty
        jmp mv_dim
@empty: rts

; ---------------------------------------------------------------------------
; mv_full: the frame's bands: each from the saved screen through the gray
; (uiDimAll), the menu's drawing over it (s2_menu.s's m_page), published.
; ---------------------------------------------------------------------------
mv_full:
        stz S2M_SEQ
@band:  lda S2M_SEQ
        jsr mv_band
        lda S2_Y0
        sta S2M_R0
        lda S2_Y1
        sta S2M_R1
        stz S2M_B0
        lda #159
        sta S2M_B1
        jsr mv_dim
        jsr m_page
        jsr s2_publish
        lda S2_Y1
        sta S2M_SEQ
        cmp #200
        bcc @band
        rts

; ---------------------------------------------------------------------------
; mv_close: I_MenuPaletteBack [R i_viigs65.s:2143-2203].
; ---------------------------------------------------------------------------
mv_close:
        lda M_PALON
        bne :+
        rts
:       stz M_PALON
        lda #S2VIEW             ; the saved SCBs and palettes into PALST
        sta FA_BANK
        lda #<SAVED_SCB
        sta FA_SRC
        lda #>SAVED_SCB
        sta FA_SRC+1
        lda #<(PST+PS_SCB)
        sta FA_DST
        lda #>(PST+PS_SCB)
        sta FA_DST+1
        lda #200
        sta FA_N
        jsr far_get
        lda #<SAVED_PAL
        sta FA_SRC
        lda #>SAVED_PAL
        sta FA_SRC+1
        lda #<(PST+PS_PALETTE)
        sta FA_DST
        lda #>(PST+PS_PALETTE)
        sta FA_DST+1
        stz FA_N
        jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        jsr far_get
        lda M_VIEWPAL
        sta PST+PS_VIEWPAL
        lda M_STRIPPAL
        sta PST+PS_STRIPPAL
        stz PST+PS_LEVELCOPY
        lda #NO_CHANGE
        sta PST+PS_NEWPAL
        lda #1
        sta PST+PS_PALCOUNT
        sta PST+PS_SCBCHANGED
        sta PST+PS_TXTINV
        stz S2M_SEQ             ; every band: the saved rows, all marked
@band:  lda S2M_SEQ
        jsr mv_band
        lda S2_Y0
        sta S2M_E
@row:   sec                     ; a row: far_get of 160 bytes
        sbc S2_Y0
        jsr s2_mul160
        clc
        adc S2_BAND
        sta FA_DST
        txa
        adc S2_BAND+1
        sta FA_DST+1
        lda S2M_E
        jsr s2_mul160
        sta FA_SRC
        txa
        clc
        adc #>SAVE_LO
        sta FA_SRC+1
        lda #S2VIEW
        sta FA_BANK
        lda #160
        sta FA_N
        jsr far_get
        inc S2M_E
        lda S2M_E
        cmp S2_Y1
        bcc @row
        stz S2_MB0
        lda #159
        sta S2_MB1
        lda S2_Y0
        ldx S2_Y1
        jsr s2_mark
        jsr s2_publish
        lda S2_Y1
        sta S2M_SEQ
        cmp #200
        bcc @band
        jsr s2_finish
        stz M_RELOAD            ; a changed gamma [R :2199-2202]
        lda SM_GAMMA
        cmp M_UIGAMMA
        beq @done
        jsr s2_reload
        bcc @done
        lda #1                  ; a level: PALW rebuilds the tints
        sta M_RELOAD
@done:  rts

; ---------------------------------------------------------------------------
; mv_static: staticUpToDate [R d_main65.s:564-596].
; ---------------------------------------------------------------------------
mv_static:
        lda M_MENUVER
        cmp M_SCRMENUVER
        bne @stale
        lda M_MENUVER+1
        cmp M_SCRMENUVER+1
        beq :+
@stale: clc
        rts
:       lda M_SKULLVER
        cmp M_SCRSKULLVER
        bne :+
        lda M_SKULLVER+1
        cmp M_SCRSKULLVER+1
        bne :+
        sec
        rts
:       lda M_SKSHOWN           ; the old skull's rectangle: skx, sky, skw,
        sta S2M_OLDS            ;   skh as they are
        lda M_SKX
        sta S2M_OLDX
        lda M_SKX+1
        sta S2M_OLDX+1
        lda M_SKY
        sta S2M_OLDY
        lda M_SKW
        sta S2M_OLDW
        lda M_SKH
        sta S2M_OLDH
        jsr m_skullrect         ; the new one (skx..skh); C: a skull
        lda #0
        rol a
        sta S2M_NEWS
        sta M_SKSHOWN
        lda S2M_OLDY            ; the bands from the lower first row
        ldx S2M_NEWS
        beq :+
        cmp M_SKY
        bcc :+
        lda M_SKY
:       ldx S2M_OLDS
        bne :+
        lda M_SKY               ; (no old skull: the new rectangle's)
:       sta S2M_SEQ
        lda S2M_OLDS
        ora S2M_NEWS
        beq @shown              ; nothing to draw
@band:  lda S2M_SEQ
        jsr mv_band
        lda S2M_OLDS
        beq @new
        lda S2M_OLDX            ; the old rectangle
        sta S2M_X
        lda S2M_OLDX+1
        sta S2M_X+1
        lda S2M_OLDY
        sta S2M_Y
        stz S2M_Y+1
        lda S2M_OLDW
        sta S2M_W
        stz S2M_W+1
        lda S2M_OLDH
        sta S2M_A
        stz S2M_A+1
        jsr mv_restore
@new:   lda S2M_NEWS
        beq @pub
        jsr skullrest           ; the new rectangle, then the skull
        jsr m_drawskull
@pub:   jsr s2_publish
        lda S2_Y1               ; the next band while a rectangle goes on
        sta S2M_SEQ
        cmp #200
        bcs @shown
        ldx S2M_OLDS
        beq :+
        lda S2M_OLDY
        clc
        adc S2M_OLDH
        cmp S2M_SEQ
        beq :+
        bcs @band
:       ldx S2M_NEWS
        beq @shown
        lda M_SKY
        clc
        adc M_SKH
        cmp S2M_SEQ
        beq @shown
        bcs @band
@shown: jsr s2_finish           ; (I_ShowDirty: nothing else pending)
        lda M_SKULLVER          ; screenskullversion
        sta M_SCRSKULLVER
        lda M_SKULLVER+1
        sta M_SCRSKULLVER+1
        sec
        rts

; skullrest: mv_restore of skx, sky, skw, skh.
skullrest:
        lda M_SKX
        sta S2M_X
        lda M_SKX+1
        sta S2M_X+1
        lda M_SKY
        sta S2M_Y
        stz S2M_Y+1
        lda M_SKW
        sta S2M_W
        stz S2M_W+1
        lda M_SKH
        sta S2M_A
        stz S2M_A+1
        jmp mv_restore

; ---------------------------------------------------------------------------
; mv_drawn: staticDrawn [R d_main65.s:618-624].
; ---------------------------------------------------------------------------
mv_drawn:
        lda M_MENUVER
        sta M_SCRMENUVER
        lda M_MENUVER+1
        sta M_SCRMENUVER+1
        lda M_SKULLVER
        sta M_SCRSKULLVER
        lda M_SKULLVER+1
        sta M_SCRSKULLVER+1
        jsr m_skullrect
        lda #0
        rol a
        sta M_SKSHOWN
        rts

        .segment "S2RODATA"

; uiFontReds [R i_viigs65.s:2402]
font_reds:
        .byte 15, 14, 13, 13, 12, 11, 11, 10, 9, 8, 7, 7, 6, 5, 5, 4

; the save: CONTROL (4), the parameters (count 3, unit 0, a pointer the
; raw transport ignores, selector $80, padding), the list's length (8 +
; 16), "AMEM" 1, one descriptor, flags 0; COPY of aux 0 $2000 to aux bank
; S2VIEW $2000, $8000 bytes (README_MEMORY_API.md sections 3, 7)
am_copy:
        .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0
        .word 8 + 16
        .byte "AMEM", 1, 1, 0, 0
        .byte 1, 0, 1, 0
        .word SAVE_LO
        .byte 1, S2VIEW
        .word SAVE_LO
        .word SAVE_N
        .byte 0, 0, 0, 0
AM_COPY_N = * - am_copy

        .segment "S2DATA"

mv_mappal:
        .byte $FF               ; the palette mv_map_t is built for
mv_scbs:
        .res S2M_BANDROWS       ; the band rows' saved SCBs
mv_map_t:
        .res 256                ; a byte's two grays (the row's palette)
