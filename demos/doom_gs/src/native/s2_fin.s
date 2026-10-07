; s2_fin.s: the finale, the pages, the loading screen and the busy sign
; (docs/SCREENS.md: the finale, the pages, the signs; part s2fin). The image
; FINW's own code. Written from upstream's src/iigs/f_finale65.s (F_Init's
; lumps, F_Drawer, textSpeed, F_TextWrite, F_LoadScreen [R
; f_finale65.s:60-284]), d_main65.s (D_PageDrawer's V_DrawRawFullScreen [R
; d_main65.s:417-422]) and m_menu65.s (bmSignOn, bmSignOff, bmSignBox,
; bmSignPatch with bmGlyph, bmGlyphCol, bmPut, bmBlanks, bmMargin [R
; m_menu65.s:1759-2091]), with upstream's back buffer replaced by FINW's
; band (docs/SCREENS.md).
;
;   fin_init    F_Init: the picture's and the background's lumps as the 2D
;               store's handles (F_HELP2, F_BACKGROUND), no sign; FINW's own
;               block written to S2STATE (SS_FINW)
;   fin_frame   a frame (docs/SCREENS.md): A bit 0 = a level was left
;               (display's I_SetPalette(0) [R d_main65.s:389-392]), bit 1
;               = the title page (D_PageDrawer) instead of the finale; the
;               input poll and the effect service, PALST from S2STATE,
;               F_Drawer or the page, s2_finish, PALST back
;   fin_load    F_LoadScreen [R f_finale65.s:279-284]: the background
;               flat, then I_FinishUpdate (an update outside a frame)
;   fin_signon  bmSignOn: A = the text (0 "LOADING...", 1 "SAVING...", 2
;               "INSERT DISK n" with X the digit's character, bmDiskAsk's);
;               the first time the rows under the sign are saved (a
;               memory-API COPY of aux 0's rows 88-111 to S2STATE's SS_SIGN:
;               a source in aux 0 is allowed); a new
;               text while the sign is on puts them back first
;   fin_signoff bmSignOff: the rows as they were, when the sign is on
;
; How a screen is composed: the pictures (HELP2, TITLEPIC) in five bands of
; 40 rows (s2_rect: every byte marked, as drawPicture's markRows(0, 200)),
; their palette part once (s2_picpal); the background flat and the text in
; bands of 16 rows (each band's rows' nibble tables, then s2_back, then the
; glyphs that cross the band, clipped to it); the sign in the bands of rows
; 88-103 and 104-111 over the saved rows. A band of 16 rows needs at most
; 16 units of nibble tables (a palette and a parity each, s2_wi.s's
; scheme), so the slots never overflow whatever the rows' palettes.
;
; The finale's state is the card's (F_STAGE, F_COUNT, F_MID: the tic side,
; s2t_fin.s), acceleratestage is the game's WI_ACCEL; F_Drawer's
; textSpeed writes F_MID and WI_ACCEL as upstream's does. Zero page: the
; drawers' S2_*, the far layer's FA_* and FINW's FZ_* ($80-$AA).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2data.inc"
        .include "lgame.inc"
        .include "s2fin.inc"

        .export fin_init, fin_frame, fin_load, fin_signon, fin_signoff
        .export s2_marks, s2_fbuf, s2_palst, s2_begun, s2_nbuf
        .exportzp s2_fbpages
        .import s2_vpatch, s2_back, s2_rect, s2_mark, s2_unmark, s2_publish
        .import s2_palget, s2_palput, s2_finish, s2_setpal, s2_picpal
        .import far_get, far_put, pl_poll, fx_service

s2_marks   = FINW_MARKS
s2_fbuf    = FINW_FBUF
s2_fbpages = FINW_FBPAGES
s2_palst   = PALST_W
s2_begun   = PALST_W + PS_BEGUN
s2_nbuf    = FINW_RT2           ; s2_picpal's build buffer: the slots

ROWL     = s2_marks + $80
ROWR     = s2_marks + $C0
BAND     = FINW_RT0             ; 40 rows of 160 bytes
SLOTS    = FINW_RT2             ; 16 units of 2 pages
OWN      = PALST_W + PALST_SIZE ; FINW's own block ($BF00)
SCBS     = PALST_W + PS_SCB
; the sign's state F_SIGNON (VW_SGON) is s2.inc's, after the field map's
; F_HELP2 and F_BACKGROUND (s2layout's FINW_NATIVE)
OWN_N    = 3
        .assert F_SIGNON = OWN + 2, error, "FINW's own block"

NUNITS   = 16
PICROWS  = 40                   ; a picture's band
FLATROWS = 16                   ; a band of the flat (16 units at most)
PICSIZE  = 32000                ; a picture's pixels, then its SCBs
SCREENH  = 200
FONT_LO  = '!'                  ; HU_FONTSTART .. HU_FONTEND
FONT_N   = '_' - '!' + 1
SPACE_W  = 4                    ; HU_FONT_SPACE_WIDTH
TEXT_X   = 10                   ; F_TextWrite's start and line [R :225-248]
TEXT_DY  = 11
GLYPH_H  = 8                    ; the font's rows below its y (tops <= 0,
                                ;   heights <= 8 - top: s2fin.py checks)
TEXTSPEED = 300                 ; [R f_finale65.s:18]
BUSY_Y   = 88                   ; [R m_menu65.s:1760-1766]
BUSY_H   = 24
BUSY_M   = 4                    ; BUSY_MARGIN
BUSY_END = BUSY_Y + BUSY_H
SIGN_SRC = SS_SIGN - BUSY_Y * 160   ; s2_rect's base: row r at + r * 160

; FINW's temporaries in zero page (FZ_*); the sign's
; over the text's (never live at once)
FZ       = $80
ff       = FZ + 0               ; fin_frame's flags
cx       = FZ + 1               ; F_TextWrite's x, y (2 each)
cy       = FZ + 3
cnt      = FZ + 5               ; the letters (16 bits, saturated)
left     = FZ + 7               ; the letters left in a band's walk (2)
tp       = FZ + 9               ; the text's pointer (2)
mul      = FZ + 11              ; (finalecount - 10) << n (4)
mt       = FZ + 15              ; * 100, then the quotient (4)
rem      = FZ + 19              ; the division's remainder (2)
sg_t     = FZ + 1               ; the sign's text (0-2)
sg_all   = FZ + 2               ; 1: every row of the sign published
sg_w     = FZ + 3               ; its width (2)
sg_x     = FZ + 5               ; the column's x (2)
sg_col   = FZ + 7               ; VW_SGCOL: the glyph column's 8 pixels
sg_g     = FZ + 15              ; the glyph's index
sg_c     = FZ + 16              ; its column
sg_n     = FZ + 17              ; a pixel's nibble
sg_p     = FZ + 18              ; the text's index
sg_d     = FZ + 19              ; bmDiskAsk's digit
sg_m     = FZ + 20              ; the nibble mask
u_next   = FZ + 21              ; the next free unit
ekey     = FZ + 22
emiss    = FZ + 23
er0      = FZ + 24              ; rows er0 .. er1 - 1 get their units
er1      = FZ + 25
pk_bank  = FZ + 26              ; a lump's place (place)
pk_alo   = FZ + 27
pk_ahi   = FZ + 28
pnum     = FZ + 29              ; a picture's lump number, an offset (2)
sg_r     = FZ + 31              ; the band row; a post's length
sg_k     = FZ + 32              ; a column's row in the sign; a post's row
sg_dst   = FZ + 33              ; the band byte (2)
sg_e     = FZ + 35              ; the width's half, the sign's end (2)
FZ_END   = FZ + 37

        .assert FZ_END <= $B0, error, "FINW's zero page meets the math block"

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; fin_init: F_Init [R f_finale65.s:65-73] as handles; no sign.
; ---------------------------------------------------------------------------
fin_init:
        lda #H_HELP2
        sta F_HELP2
        lda #H_FLOOR4_8
        sta F_BACKGROUND
        stz F_SIGNON
        jmp ownput

; ownget, ownput: FINW's own block (its first OWN_N bytes) from and to
; S2STATE's SS_FINW
ownget:
        jsr ownarg
        sta FA_SRC
        stx FA_SRC+1
        lda #<OWN
        sta FA_DST
        lda #>OWN
        sta FA_DST+1
        jmp far_get
ownput:
        jsr ownarg
        sta FA_DST
        stx FA_DST+1
        lda #<OWN
        sta FA_SRC
        lda #>OWN
        sta FA_SRC+1
        jmp far_put
ownarg:
        lda #S2STATE
        sta FA_BANK
        lda #OWN_N
        sta FA_N
        lda #<SS_FINW
        ldx #>SS_FINW
        rts

; ---------------------------------------------------------------------------
; fin_frame: a finale or page frame. A bit 0: a level was left; bit 1: the
; title page.
; ---------------------------------------------------------------------------
fin_frame:
        sta ff
        lda #0                  ; pl_poll's A: no menu up (a menu's frame
        jsr pl_poll             ;   is MENUW's)
        jsr fx_service
        jsr s2_palget
        jsr ownget
        lda ff
        lsr a
        bcc :+
        lda #0                  ; I_SetPalette(0)
        jsr s2_setpal
:       lda ff
        and #2
        beq @fin
        ldx #H_TITLEPIC         ; D_PageDrawer: V_DrawRawFullScreen(
        lda #<FIN_TITLENUM      ;   titlepicnum)
        ldy #>FIN_TITLENUM
        jsr picture
        bra finish
@fin:   jsr f_drawer
finish: jsr s2_finish
        jmp s2_palput

; ---------------------------------------------------------------------------
; fin_load: F_LoadScreen.
; ---------------------------------------------------------------------------
fin_load:
        jsr s2_palget
        jsr ownget
        stz cnt                 ; no text
        stz cnt+1
        jsr backdrop
        bra finish

; ---------------------------------------------------------------------------
; F_Drawer [R f_finale65.s:155-192]: the picture, or the background and
; (finalecount - 10) * 100 / speed letters of the text.
; ---------------------------------------------------------------------------
f_drawer:
        lda F_STAGE
        beq @text
        ldx F_HELP2
        lda #<FIN_HELP2NUM
        ldy #>FIN_HELP2NUM
        jmp picture
@text:  sec                     ; finalecount - 10 (int32)
        ldx #0
:       lda F_COUNT,x
        sbc tens,x
        sta mul,x
        inx
        txa
        eor #4
        bne :-
        ldx #2                  ; * 4 into mt, * 32 and * 64 added
        jsr shl
        ldx #3
:       lda mul,x
        sta mt,x
        dex
        bpl :-
        ldx #3
        jsr shl
        jsr addm
        ldx #1
        jsr shl
        jsr addm
        jsr speed               ; / speed (signed); below 0: none
        lda mt+3
        bmi @zero
        bcc @slow
        ora mt+2                ; fast: the product
        bne @sat
        bra @cnt
@slow:  lda mt+2                ; / 300: the quotient's 16 bits (more: all)
        cmp #<(TEXTSPEED)
        lda mt+3
        sbc #>(TEXTSPEED)
        bcs @sat
        lda mt+2
        sta rem
        lda mt+3
        sta rem+1
        ldx #16
@div:   asl mt
        rol mt+1
        rol rem
        rol rem+1
        lda rem
        sec
        sbc #<TEXTSPEED
        tay
        lda rem+1
        sbc #>TEXTSPEED
        bcc :+
        sta rem+1
        sty rem
        inc mt
:       dex
        bne @div
@cnt:   lda mt
        sta cnt
        lda mt+1
        sta cnt+1
        bra backdrop
@sat:   lda #$FF
        sta cnt
        sta cnt+1
        bra backdrop
@zero:  stz cnt
        stz cnt+1
        ; (falls into backdrop)

; backdrop: V_DrawBackground of F_BACKGROUND, and cnt letters of the text
; (F_TextWrite), in bands of FLATROWS rows
backdrop:
        ldx F_BACKGROUND
        jsr place
        jsr bandinit
@band:  lda S2_Y0
        clc
        adc #FLATROWS
        cmp #SCREENH
        bcc :+
        lda #SCREENH
:       sta S2_Y1
        lda S2_Y0
        sta er0
        lda S2_Y1
        sta er1
        jsr ensure
        jsr pkarg
        jsr s2_back
        jsr text
        jsr s2_publish
        lda S2_Y1
        sta S2_Y0
        cmp #SCREENH
        bcc @band
        rts

; shl: mul <<= X; addm: mt += mul (int32)
shl:    asl mul
        rol mul+1
        rol mul+2
        rol mul+3
        dex
        bne shl
        rts
addm:   clc
        ldx #0
:       lda mt,x
        adc mul,x
        sta mt,x
        inx
        txa
        eor #4
        bne :-
        rts

; speed: textSpeed [R f_finale65.s:94-105], as s2t_fin.s's: C set when
; fast, clear when 300; a request starts the mid stage and is taken
speed:
        lda F_MID
        bne @fast
        lda WI_ACCEL
        ora WI_ACCEL+1
        clc
        beq @r
        lda #1
        sta F_MID
        stz WI_ACCEL
        stz WI_ACCEL+1
@fast:  sec
@r:     rts

; ---------------------------------------------------------------------------
; text: F_TextWrite [R f_finale65.s:216-277] into the band: the first cnt
; letters from (10, 10), 11 rows a line, upper case, a space for the
; others; only the glyphs whose rows cross the band are drawn (clipped to
; it by s2_vpatch), every letter moves x
; ---------------------------------------------------------------------------
text:
        lda #TEXT_X
        sta cx
        sta cy
        stz cx+1
        stz cy+1
        lda #<e1text
        sta tp
        lda #>e1text
        sta tp+1
        lda cnt
        sta left
        lda cnt+1
        sta left+1
@ch:    lda left                ; for (; count; count--)
        ora left+1
        beq @r
        lda left
        bne :+
        dec left+1
:       dec left
        lda (tp)                ; c = *ch++
        beq @r
        inc tp
        bne :+
        inc tp+1
:       cmp #10                 ; a new line
        bne @up
        lda #TEXT_X
        sta cx
        stz cx+1
        lda cy
        clc
        adc #TEXT_DY
        sta cy
        bcc @ch
        inc cy+1
        bra @ch
@up:    cmp #'a'                ; toupper
        bcc :+
        cmp #'z' + 1
        bcs :+
        sbc #'a' - 'A' - 1      ; (C clear)
:       sec                     ; a font character
        sbc #FONT_LO
        cmp #FONT_N
        bcs @sp
        tax
        lda cy+1                ; rows cy .. cy + 7 cross the band?
        bne @adv
        lda cy
        cmp S2_Y1
        bcs @adv
        adc #GLYPH_H            ; (C clear)
        bcs @draw
        cmp S2_Y0
        beq @adv
        bcc @adv
@draw:  phx
        lda cx
        sta S2_X
        lda cx+1
        sta S2_X+1
        lda cy
        sta S2_Y
        lda cy+1
        sta S2_Y+1
        jsr glyph
        jsr s2_vpatch           ; V_DrawPatchNotScaled
        plx
@adv:   lda fin_fwid,x          ; cx += width
        bra @add
@sp:    lda #SPACE_W
@add:   clc
        adc cx
        sta cx
        bcc @ch
        inc cx+1
        bra @ch
@r:     rts

; glyph: S2_PBANK:S2_PADDR = glyph X's patch
glyph:
        lda fin_fbank,x
        sta S2_PBANK
        lda fin_flo,x
        sta S2_PADDR
        lda fin_fhi,x
        sta S2_PADDR+1
        rts

; ---------------------------------------------------------------------------
; picture: V_DrawRawFullScreen [R r_data65.s:586-588] of a picture: X =
; its handle, A, Y = its lump number (picturenum): drawPicture [R
; i_viigs65.s:1226-1295]: its palette part (s2_picpal), then its pixels in
; bands of PICROWS rows, every byte marked
; ---------------------------------------------------------------------------
picture:
        sta pnum
        sty pnum+1
        jsr place
        jsr pkarg
        clc
        lda S2_PADDR
        adc #<PICSIZE
        sta S2_PADDR
        lda S2_PADDR+1
        adc #>PICSIZE
        sta S2_PADDR+1
        lda pnum
        ldx pnum+1
        jsr s2_picpal
        jsr bandinit
@band:  lda S2_Y0
        clc
        adc #PICROWS
        sta S2_Y1
        sta S2_RY1
        lda S2_Y0
        sta S2_RY0
        jsr pkarg
        jsr rectrow
        jsr s2_publish
        lda S2_Y1
        sta S2_Y0
        cmp #SCREENH
        bcc @band
        rts

; rectrow: s2_rect of the band's rows S2_RY0 .. S2_RY1 - 1, all 160 bytes
rectrow:
        stz S2_RB0
        lda #159
        sta S2_RB1
        jmp s2_rect

; bandinit: the band at BAND from row 0, its marks clear, no capture, the
; units free
bandinit:
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        stz S2_Y0
        stz S2_CAP
        jsr s2_unmark
        ; (falls into flush)

; flush: every unit free
flush:
        ldx #2 * NUNITS - 1
:       stz u_page,x
        dex
        bpl :-
        stz u_next
        rts

; pkarg: S2_PBANK:S2_PADDR = the place pk_*
pkarg:
        lda pk_bank
        sta S2_PBANK
        lda pk_alo
        sta S2_PADDR
        lda pk_ahi
        sta S2_PADDR+1
        rts

; place: handle X's bank and address (GFXDIR's) in pk_bank, pk_alo, pk_ahi
place:
        txa
        clc
        adc #<GFXDIR_BK
        sta FA_SRC
        lda #>GFXDIR_BK
        adc #0
        sta FA_SRC+1
        lda #<pk_bank
        sta FA_DST
        stz FA_DST+1
        lda #1
        sta FA_N
        lda #GFXDIR_BANK
        sta FA_BANK
        ldx #3
@a:     phx
        jsr far_get
        plx
        clc
        lda FA_SRC
        adc #<GFX_NH
        sta FA_SRC
        lda FA_SRC+1
        adc #>GFX_NH
        sta FA_SRC+1
        inc FA_DST
        dex
        bne @a
        rts

; ---------------------------------------------------------------------------
; The nibble tables: units of 2 pages (a palette and a parity: the left
; pixel's page, then the right pixel's) in the slots, as s2_wi.s's
; ---------------------------------------------------------------------------

; ensure: the units of the rows er0 .. er1 - 1 (at most 16 rows, so at
; most 16 units), and those rows' ROWL, ROWR
ensure:
        stz emiss               ; the units missing ($FF: wanted)
        ldy er0
@p1:    jsr ukey
        lda u_page,x
        bne :+
        dec u_page,x
        inc emiss
:       iny
        cpy er1
        bcc @p1
        lda #NUNITS             ; fewer free than missing: all freed
        sec
        sbc u_next
        cmp emiss
        bcs :+
        jsr flush
:       ldy er0
@row:   jsr ukey
        lda u_page,x
        beq @new
        cmp #$FF
        bne @have
@new:   lda u_next
        asl a
        adc #>SLOTS             ; (C clear)
        sta u_page,x
        inc u_next
        jsr ufetch
@have:  pha
        tya
        sec
        sbc S2_Y0
        tax
        pla
        sta ROWL,x
        inc a
        sta ROWR,x
        iny
        cpy er1
        bcc @row
        rts

; ukey: X = the unit of row Y: its palette * 2 + its parity
ukey:
        lda SCBS,y
        and #$0F
        asl a
        sta ekey
        tya
        and #1
        ora ekey
        tax
        rts

; ufetch: unit X to the page A: S2NIB's palette X / 2, the pages of the
; parity X & 1 (left at + parity * $100, right 2 pages on). A, X, Y kept.
ufetch:
        pha
        phx
        phy
        sta FA_DST+1
        stz FA_DST
        txa
        and #1
        sta ekey
        txa
        and #$FE
        asl a
        clc
        adc ekey
        adc #>S2P_NIB
        sta FA_SRC+1
        stz FA_SRC
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        jsr far_get
        inc FA_DST+1
        inc FA_SRC+1
        inc FA_SRC+1
        jsr far_get
        ply
        plx
        pla
        rts

; ---------------------------------------------------------------------------
; The busy sign [R m_menu65.s:1799-2091]: a patch of the text in the font,
; each pixel doubled, BUSY_H rows (BUSY_M black, the glyph's rows 0-7 each
; twice, BUSY_M black), between BUSY_M black columns, at x = 160 - width /
; 2, y = BUSY_Y; drawn here column by column into the band by the nibble
; rule (s2_draw's), never built as a patch
; ---------------------------------------------------------------------------
fin_signon:
        sta sg_t
        stx sg_d
        jsr s2_palget           ; the rows' palettes (PALST not changed)
        jsr ownget
        lda #1
        sta sg_all
        lda F_SIGNON
        bne @on                 ; on: the rows as they were first
        stz sg_all
        jsr sgsave
        lda #1
        sta F_SIGNON
        jsr ownput
@on:    ldx sg_t                ; the width: the margins, each glyph's
        lda sign_at,x           ;   width (a space's) twice
        sta sg_p
        lda #2 * BUSY_M
        sta sg_w
        stz sg_w+1
        ldy sg_p
@w:     lda sign_txt,y
        beq @x
        jsr sgchar
        lda #SPACE_W
        bcs :+
        lda fin_fwid,x
:       asl a                   ; (C clear: widths < 128)
        adc sg_w
        sta sg_w
        bcc :+
        inc sg_w+1
:       iny
        bra @w
@x:     lda sg_w+1              ; x = 160 - width / 2 (the sign is
        lsr a                   ;   narrower than the screen)
        lda sg_w
        ror a
        sta sg_e
        lda #160
        sec
        sbc sg_e
        sta sg_x
        stz sg_x+1
        lda #1                  ; I_ShowDirty: no colours, no SCBs
        sta s2_begun
        jsr bandinit
        lda #BUSY_Y
        sta S2_Y0
        lda #BUSY_Y + FLATROWS
        jsr sgband
        lda #BUSY_END
        jsr sgband
        stz s2_begun
        rts

; sgband: the band S2_Y0 .. A - 1: the saved rows, the units, the sign,
; published
sgband:
        sta S2_Y1
        jsr sgrows
        lda sg_all
        bne :+
        jsr s2_unmark           ; only the sign's bytes (markPatch's)
:       lda S2_Y0
        sta er0
        lda S2_Y1
        sta er1
        jsr ensure
        lda sg_x                ; the columns
        pha
        lda sg_x+1
        pha
        ldx #BUSY_M
        jsr blanks
        ldy sg_p
@c:     lda sign_txt,y
        beq @end
        phy
        jsr sgchar
        bcc @g
        ldx #2 * SPACE_W
        jsr blanks
        bra @n
@g:     stx sg_g
        stz sg_c
:       jsr gcol                ; each glyph column, twice
        jsr put
        jsr put
        inc sg_c
        ldx sg_g
        lda sg_c
        cmp fin_fwid,x
        bcc :-
@n:     ply
        iny
        bra @c
@end:   ldx #BUSY_M
        jsr blanks
        pla                     ; the sign's bytes marked: x .. x + w - 1
        sta sg_x+1
        pla
        sta sg_x
        lda sg_x+1              ; (x < 320: x / 2 from 9 bits)
        lsr a
        lda sg_x
        ror a
        sta S2_MB0
        clc
        lda sg_x
        adc sg_w
        sta sg_e
        lda sg_x+1
        adc sg_w+1
        sta sg_e+1
        lda sg_e
        bne :+
        dec sg_e+1
:       dec sg_e
        lsr sg_e+1
        ror sg_e
        lda sg_e                ; (the last byte, at most 159)
        sta S2_MB1
        lda S2_Y0
        ldx S2_Y1
        jsr s2_mark
        jsr s2_publish
        lda S2_Y1
        sta S2_Y0
        rts

; sgrows: the band's rows from the saved rows (SS_SIGN), marked
sgrows:
        lda #S2STATE
        sta S2_PBANK
        lda #<SIGN_SRC
        sta S2_PADDR
        lda #>SIGN_SRC
        sta S2_PADDR+1
        lda S2_Y0
        sta S2_RY0
        lda S2_Y1
        sta S2_RY1
        jmp rectrow

; sgchar: the text's character A (not 0): C clear and X its glyph
; (bmGlyph [R m_menu65.s:1971-1987]), C set for a space (or a character the
; font does not have)
sgchar:
        cmp #'#'                ; bmDiskAsk's digit
        bne :+
        lda sg_d
:       cmp #'a'
        bcc :+
        cmp #'z' + 1
        bcs :+
        sbc #'a' - 'A' - 1      ; (C clear)
:       sec
        sbc #FONT_LO
        tax
        cmp #FONT_N
        rts

; blanks: bmBlanks: X black columns
blanks:
        lda #0
        ldy #7
:       sta sg_col,y
        dey
        bpl :-
:       phx
        jsr put
        plx
        dex
        bne :-
        rts

; gcol: bmGlyphCol [R m_menu65.s:1993-2035]: sg_col = column sg_c of glyph
; sg_g, 0 where it has no post (rows past 7 dropped)
gcol:
        ldx sg_g
        jsr glyph
        lda sg_c                ; columnofs[c]'s low word: at 8 + 4 * c
        asl a
        asl a
        adc #8                  ; (C clear: widths < 64)
        jsr fetch2
        lda s2_fbuf             ; the column's 64 bytes
        sta pnum
        lda s2_fbuf+1
        sta pnum+1
        lda #64
        sta FA_N
        jsr gfetch
        ldy #7
        lda #0
:       sta sg_col,y
        dey
        bpl :-
        ldy #0
@post:  lda s2_fbuf,y           ; a post: row, length, pad, the pixels,
        cmp #$FF                ;   pad; $FF the end
        beq @r
        sta sg_k
        lda s2_fbuf+1,y
        sta sg_r
        iny
        iny
@px:    iny
        ldx sg_k
        cpx #8
        bcs :+
        lda s2_fbuf,y
        sta sg_col,x
:       inc sg_k
        dec sg_r
        bne @px
        iny                     ; (the pad after the pixels)
        iny
        bra @post
@r:     rts

; fetch2: 2 bytes of the glyph's patch at its offset A to s2_fbuf
fetch2:
        sta pnum
        stz pnum+1
        lda #2
        sta FA_N
gfetch: clc                     ; FA_N bytes at the glyph's offset pnum
        lda S2_PADDR
        adc pnum
        sta FA_SRC
        lda S2_PADDR+1
        adc pnum+1
        sta FA_SRC+1
        lda S2_PBANK
        sta FA_BANK
        stz FA_DST
        lda #>s2_fbuf
        sta FA_DST+1
        jmp far_get

; put: bmPut [R m_menu65.s:2039-2079]: the column at sg_x (BUSY_M black,
; each of sg_col twice, BUSY_M black) into the band's rows, then x + 1
put:
        lda sg_x+1              ; x < 320 only (the sign is narrower)
        cmp #2
        bcs @next
        lsr a                   ; C: x's ninth bit
        lda sg_x
        bcc :+
        cmp #<320
        bcs @next
        sec
:       ror a                   ; the byte, C the side
        sta sg_dst
        stz sg_dst+1
        lda #$0F                ; the left pixel keeps the right nibble
        ldx #<ROWL
        bcc :+
        lda #$F0                ; the right pixel keeps the left nibble
        ldx #<ROWR
:       sta sg_m
        stx @rt+1
        lda S2_Y0               ; the band's first row in the sign
        sec
        sbc #BUSY_Y
        sta sg_k
        clc
        lda sg_dst
        adc #<BAND
        sta sg_dst
        lda #>BAND
        adc #0
        sta sg_dst+1
        stz sg_r
@row:   ldy sg_k                ; the pixel: black in the margins, else
        lda #0                  ;   row (k - 4) / 2 of the glyph's column
        cpy #BUSY_M
        bcc @px
        cpy #BUSY_H - BUSY_M
        bcs @px
        tya
        sbc #BUSY_M - 1         ; (C clear)
        lsr a
        tay
        lda sg_col,y
@px:    tay
        ldx sg_r
@rt:    lda ROWL,x              ; the row's nibble page
        sta @nt+2
@nt:    lda $FF00,y
        sta sg_n
        lda (sg_dst)
        and sg_m
        ora sg_n
        sta (sg_dst)
        clc
        lda sg_dst
        adc #160
        sta sg_dst
        bcc :+
        inc sg_dst+1
:       inc sg_k
        inc sg_r
        lda sg_r
        clc
        adc S2_Y0
        cmp S2_Y1
        bcc @row
@next:  inc sg_x
        bne :+
        inc sg_x+1
:       rts

; ---------------------------------------------------------------------------
; fin_signoff: bmSignOff [R m_menu65.s:1820-1827] with bmSignBox's
; restore: the saved rows published whole.
; ---------------------------------------------------------------------------
fin_signoff:
        jsr ownget
        lda F_SIGNON
        beq @r
        stz F_SIGNON
        jsr ownput
        lda #1                  ; no colours, no SCBs
        sta s2_begun
        jsr bandinit
        lda #BUSY_Y
        sta S2_Y0
        lda #BUSY_END
        sta S2_Y1
        jsr sgrows
        jsr s2_publish
        stz s2_begun
@r:     rts

; sgsave: bmSignBox's save: one memory-API COPY of aux 0's rows of the sign
; to SS_SIGN (interrupts masked meanwhile, as s2_mvid.s's mv_amem); a
; failure stops (PL_STATUS PL_SIGNAMEM, then BRK)
SP_DATA    = $CFF0              ; the memory API's raw FIFO transport in
SP_CTRL    = $CFF1              ;   slot 7 (appletini-one
SP_POP     = $CFF2              ;   README_MEMORY_API.md section 7)
SP_RELEASE = $CFFF
SP_ROM     = $C700
sgsave:
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
        stz sg_r
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec sg_r
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
:       lda #PL_SIGNAMEM
        sta PL_STATUS
        brk
        .byte 0

; ---------------------------------------------------------------------------
; Tables
; ---------------------------------------------------------------------------
        .segment "S2RODATA"

tens:   .byte 10, 0, 0, 0
; the sign's COPY: CONTROL (4), the parameters (count 3, unit 0, a pointer
; the raw transport ignores, selector $80, padding), the list's length (8 +
; 16), "AMEM" 1, one descriptor, flags 0; COPY of aux 0's rows 88-111 to
; S2STATE's SS_SIGN (README_MEMORY_API.md sections 3, 7)
am_copy:
        .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0
        .word 8 + 16
        .byte "AMEM", 1, 1, 0, 0
        .byte 1, 0, 1, 0
        .word SHR + BUSY_Y * 160
        .byte 1, S2STATE
        .word SS_SIGN
        .word BUSY_H * 160
        .byte 0, 0, 0, 0
AM_COPY_N = * - am_copy

        .assert BUSY_H * 160 <= SS_SIGN_SIZE, error, "SS_SIGN is too small"

; the font's glyphs '!' .. '_' (the 2D store's places, DOOM1.WAD's widths;
; tools/native/s2fin.py --inc)
fin_fbank:
.repeat FONT_N, I
        .byte .ident(.sprintf("FIN_FB_%d", I))
.endrep
fin_flo:
.repeat FONT_N, I
        .byte <.ident(.sprintf("FIN_FA_%d", I))
.endrep
fin_fhi:
.repeat FONT_N, I
        .byte >.ident(.sprintf("FIN_FA_%d", I))
.endrep
fin_fwid:
.repeat FONT_N, I
        .byte .ident(.sprintf("FIN_FW_%d", I))
.endrep

; the sign's texts [R m_menu65.s:1768-1771] ('#': bmDiskAsk's digit)
sign_txt:
sign_ld: .byte "LOADING...", 0
sign_sv: .byte "SAVING...", 0
sign_in: .byte "INSERT DISK #", 0
sign_at: .byte sign_ld - sign_txt, sign_sv - sign_txt, sign_in - sign_txt

; e1text [R f_finale65.s:44-56] (E1TEXT of the game; s2fin.py checks it
; equal to the release's bytes)
e1text:
        .byte "Once you beat the big badasses", 10
        .byte "and clean out the moon base", 10
        .byte "you're supposed to win?", 10
        .byte "Where's your ticket home?", 10
        .byte "What the hell is this? It's not", 10
        .byte "supposed to end this way!", 10
        .byte 10
        .byte "It stinks like rotten meat, but", 10
        .byte "looks like the lost Deimos base.", 10
        .byte "You're stuck on The Shores of", 10
        .byte "Hell.", 10
        .byte "The only way out is through."
e1end:  .byte 0

        .assert e1end - e1text = FIN_E1LENGTH, error, "the text's length"

        .segment "S2DATA"

u_page: .res 2 * NUNITS         ; each unit's page, 0 none, $FF wanted
