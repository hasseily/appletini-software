; s2_hu.s: the HUD's drawer in P2DW (docs/SCREENS.md, the HUD; part s2hud).
; GPL-2: rewritten from upstream's src/iigs/hu_stuff65.s (HU_Drawer,
; drawTextLine) and src/iigs/ i_viigs65.s (I_DrawCachedText,
; I_EndTextCapture, textInvalidate, the clear of I_MessageStrip) (Doom8088:
; Apple IIgs Edition, GPL-2). The text cache keeps a record of the bytes a
; line wrote (CAPVAL, CAPMSK) instead of upstream's generated 65816 code
; (IIGS_TextCode).
;
;   hu_drawer   HU_Drawer: the map's title over the automap (slot 1, rows
;               160-167), then the message (slot 0, rows 0-9), each
;               composed in P2DW's band and published. A = the frame's
;               flags (the frame driver's and AMAPW's):
;                 bit 0  the strip is cleared: I_MessageStrip's clear
;                        (s2_stripearly's C = 1): rows 0-9 black, marked,
;                        the message's text not on the screen
;                 bit 1  the message's text is not on the screen (the view
;                        drew rows 0-9: VIEWTOP $FF; the full map cleared
;                        the strip or the view: clearStrip, clearView)
;                 bit 2  the title's text is not on the screen (a view
;                        frame without the overlay; the map's titleBand or
;                        clearView)
;               PALST's PS_TXTINV (set by s2_setrows, s2_nibtab,
;               s2_picpal: upstream's textInvalidate) empties both slots
;               first, then is cleared.
;
; The state: the card's HU_ON, HU_MSGID, HU_TITLEMAP (s2t_hu.s's), the
; frame block's AUTOMAP, PALST's PS_SCB (the rows' palettes) and
; PS_TXTINV, and P2DW's own block: P_TITLE, P_MESSAGE (upstream's lines:
; y, the text, its length), P_TXTVALID, P_TXTLEN, P_TXTY, P_TXTSHOWN
; (upstream's words, a slot each), and the stand-ins P_TXTTEXT,
; P_MSGFILL, P_MAPFILL (s2hud.inc). A line's text comes
; from its id: the table SS_HUDMSG in S2STATE (tools/native/s2msgs.py,
; the bank file HUDTXT.1) gives each
; message id and each title its text, fetched when the line's id
; changes. A slot's record (CAPVAL then CAPMSK of its rows, 3,328 bytes
; with the copy's tail) is at S2STATE's SS_HUDTXT + slot * $1000.
;
; The band (P2DW's, after the status bar is published): the line's rows
; 0-9 (the title's 0-7: the font's '$', '@' and 'Q' are 8 rows), CAPVAL
; in its rows 10-19, CAPMSK in 20-29. A line starts from black: the strip
; is black under a message (I_MessageStrip clears it when it turns on and
; for every new message; the full map's clearStrip and clearView), and
; the title's rows are black under the title (titleBand, clearView): so
; a line drawn again over its own old pixels gives upstream's bytes.
;
; The nibble tables of the line's rows (their palettes from PS_SCB) are
; fetched from S2PAL's S2NIB into P2DW's slots from the last one down,
; only for a line drawn afresh (a replay needs none). Zero page: S2_*
; (the drawers' arguments) and S2P_A (a pointer, never live across a
; call); the variables are the image's own (S2DATA).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2hud.inc"

        .export hu_drawer
        .import s2_vpatch, s2_mark, s2_unmark, s2_publish
        .import far_get, far_put, s2_marks, s2_palst

DRB   = s2_marks
DRE   = s2_marks + $40
ROWL  = s2_marks + $80
ROWR  = s2_marks + $C0
PST   = s2_palst

; (ROW_BYTES: s2.inc)
BAND  = P2DW_RT0                ; the band, then CAPVAL, CAPMSK
CAPV  = BAND + 10 * ROW_BYTES
CAPM  = BAND + 20 * ROW_BYTES
REC_PAGES = 13                  ; CAPVAL and CAPMSK (3,200 B) by pages
SLOTS = P2DW_RT2                ; eight nibble slots of 1 KB
NSLOTS = 8

TL_Y    = 0                     ; a line [R hu_stuff65.s:29-32]
TL_TEXT = 2
TL_LEN  = 37
TL_SIZE = 39
TEXTMAX = 40                    ; [R i_viigs65.s:66, :68]
TEXT_H  = 10
HU_TITLEY = 160                 ; VIEWHEIGHT - 1 - 7 [R hu_stuff65.s:22]
AM_ACTIVE = 1
SPACE_W = 4                     ; HU_FONT_SPACE_WIDTH
FONT_LO = $21                   ; '!' .. '_'
FONT_HI = $5F
SCREENWIDTH = 320

F_CLEAR = 1                     ; the flags
F_STRIP = 2
F_TITLE = 4

        .segment "S2DATA"
hz_flags: .res 1
hz_slot: .res 1                 ; 0 the message, 1 the title
hz_lb:   .res 1                 ; the line's offset from P_TITLE
hz_len:  .res 1
hz_i:    .res 1
hz_x:    .res 2
hz_t:    .res 2
hz_id:   .res 2
hz_next: .res 1                 ; the next nibble slot (from the last down)
hz_pslot: .res 16               ; a palette's slot page, 0: none

        .segment "S2RODATA"
; slot 0 (the message), 1 (the title): y, rows, the line's offset
ytab:   .byte 0, HU_TITLEY
rowtab: .byte 10, 8
lbtab:  .byte TL_SIZE, 0
        .include "s2msgs.inc"   ; the font: hu_fbank, hu_flo, hu_fhi, hu_fwid

        .segment "S2CODE"

hu_drawer:
        sta hz_flags
        lda PST+PS_TXTINV       ; textInvalidate [R i_viigs65.s:1891-1897]
        beq :+
        ldx #3
@inv:   stz P_TXTVALID,x
        stz P_TXTSHOWN,x
        dex
        bpl @inv
        stz PST+PS_TXTINV
:       lda hz_flags            ; the texts the frame took off the screen
        and #F_CLEAR | F_STRIP
        beq :+
        stz P_TXTSHOWN
:       lda hz_flags
        and #F_TITLE
        beq :+
        stz P_TXTSHOWN+2
:       ldx #NSLOTS             ; no nibble table fetched yet
        stx hz_next
        ldx #15
:       stz hz_pslot,x
        dex
        bpl :-
        lda HU_AUTOMAP          ; the map's title [R hu_stuff65.s:124-129]
        and #AM_ACTIVE
        beq :+
        ldx #1
        jsr line
:       ldx #0                  ; the message (and the strip's clear)
        ; (fall into line)

; ---------------------------------------------------------------------------
; line: slot X's line in the band, published: drawTextLine with
; I_DrawCachedText and I_EndTextCapture [R hu_stuff65.s:140-214;
; i_viigs65.s:1792-1889]; for slot 0, the strip's clear too.
; ---------------------------------------------------------------------------
line:
        stx hz_slot
        lda lbtab,x
        sta hz_lb
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        lda ytab,x
        sta S2_Y0
        clc
        adc rowtab,x
        sta S2_Y1
        jsr s2_unmark
        stz S2_CAP
        ldx hz_slot             ; the message: only while message_on; the
        bne @title              ;   strip's clear alone otherwise
        lda HU_ON
        bne @fill
        lda hz_flags
        and #F_CLEAR
        bne @zero
        rts
@title: ; (the title: called while the map is up)
@fill:  jsr fill
        jsr cached
        bcc @fresh
        lda hz_slot             ; the same text: drawn again only when it
        asl a                   ;   is not on the screen
        tax
        lda P_TXTSHOWN,x
        beq @replay
        lda hz_slot             ; shown: nothing but the strip's clear,
        bne @rts                ;   which bit 0 never sets with it shown
        lda hz_flags
        and #F_CLEAR
        beq @rts
@zero:  jsr zeroband
        jsr clearmark
        jmp s2_publish
@rts:   rts
@replay:
        lda #1
        sta P_TXTSHOWN,x
        stz P_TXTSHOWN+1,x
        jsr zeroband
        jsr clearmark
        jsr replay
        jmp s2_publish
@fresh: jsr zeroband
        jsr clearmark
        jsr draw
        jmp s2_publish

; clearmark: slot 0 with the clear: rows 0-9 marked (markRows [R
; i_viigs65.s:550-552])
clearmark:
        lda hz_slot
        bne :+
        lda hz_flags
        and #F_CLEAR
        beq :+
        stz S2_MB0
        lda #ROW_BYTES - 1
        sta S2_MB1
        lda #0
        ldx #10
        jmp s2_mark
:       rts

; zeroband: the line's rows black
zeroband:
        lda #<BAND
        sta S2P_A
        lda #>BAND
        sta S2P_A+1
        ldx hz_slot
        lda rowtab,x
        tax
@row:   lda #0
        ldy #ROW_BYTES - 1
:       sta (S2P_A),y
        dey
        bne :-
        sta (S2P_A)
        clc
        lda S2P_A
        adc #ROW_BYTES
        sta S2P_A
        bcc :+
        inc S2P_A+1
:       dex
        bne @row
        rts

;---------------------------------------------------------------------------
; fill: the line's text from its id when the id changed: the message's
; HU_MSGID (its key: the id, below HU_KEY_END), the title's map (its key
; HU_KEY_TITLE + map), from the table SS_HUDMSG in S2STATE: the key's
; word in the index (the entry's address, 0: none), then the entry's 36
; bytes (the text padded to 35, its length) to the line's TL_TEXT and
; TL_LEN; an id the table lacks gives the empty text.
; ---------------------------------------------------------------------------
fill:
        ldx hz_slot
        bne @map
        lda HU_MSGID
        ldy HU_MSGID+1
        cmp P_MSGFILL
        bne :+
        cpy P_MSGFILL+1
        beq @rts
:       sta P_MSGFILL
        sty P_MSGFILL+1
        cpy #0                  ; a message's key: its id
        bne @none
        cmp #HU_KEY_END
        bcs @none
        bra @find
@map:   lda HU_TITLEMAP
        cmp P_MAPFILL
        beq @rts
        sta P_MAPFILL
        cmp #10
        bcs @none
        adc #HU_KEY_TITLE       ; (carry clear)
@find:  asl a                   ; the index's word: SS_HUDMSG + key * 2
        sta FA_SRC
        lda #0
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SS_HUDMSG
        sta FA_SRC
        lda FA_SRC+1
        adc #>SS_HUDMSG
        sta FA_SRC+1
        lda #<hz_t
        sta FA_DST
        lda #>hz_t
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        lda #2
        sta FA_N
        jsr far_get
        lda hz_t+1
        beq @none
        sta FA_SRC+1
        lda hz_t
        sta FA_SRC
        lda hz_lb               ; the entry to the line
        clc
        adc #<(P_TITLE + TL_TEXT)
        sta FA_DST
        lda #>(P_TITLE + TL_TEXT)
        adc #0
        sta FA_DST+1
        lda #TL_LEN - TL_TEXT + 1
        sta FA_N
        jsr far_get
        ldx hz_lb
        bra @len
@none:  ldx hz_lb
        stz P_TITLE+TL_LEN,x
@len:   stz P_TITLE+TL_LEN+1,x
@rts:   rts

; ---------------------------------------------------------------------------
; cached: C = 1 when slot hz_slot holds this text at this y (I_DrawCachedText
; [R i_viigs65.s:1792-1818]); hz_len the line's length (its low byte).
; ---------------------------------------------------------------------------
cached:
        ldx hz_lb
        lda P_TITLE+TL_LEN,x
        sta hz_len
        lda hz_slot
        asl a
        tay
        lda P_TXTVALID,y
        ora P_TXTVALID+1,y
        beq @no
        lda P_TXTLEN,y
        cmp hz_len
        bne @no
        lda P_TXTLEN+1,y
        cmp P_TITLE+TL_LEN+1,x
        bne @no
        ldx hz_slot
        lda ytab,x
        cmp P_TXTY,y
        bne @no
        lda P_TXTY+1,y
        bne @no
        ldy #0                  ; the text: slot 1's at TEXTMAX
        lda hz_slot
        beq :+
        ldy #TEXTMAX
:       ldx hz_lb
        lda hz_len
        sta hz_i
@cmp:   lda hz_i
        beq @yes
        lda P_TITLE+TL_TEXT,x
        cmp P_TXTTEXT,y
        bne @no
        inx
        iny
        dec hz_i
        bra @cmp
@yes:   sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------
; draw: the line afresh, recorded (drawTextLine [R hu_stuff65.s:150-207]),
; then I_EndTextCapture [R i_viigs65.s:1843-1889]
; ---------------------------------------------------------------------------
draw:
        jsr tables
        lda #<CAPV              ; the record empty
        sta S2P_A
        lda #>CAPV
        sta S2P_A+1
        ldx #(CAPM - CAPV) * 2 / 256 + 1
        lda #0
        tay
:       sta (S2P_A),y
        iny
        bne :-
        inc S2P_A+1
        dex
        bne :-
        lda #<(CAPV - BAND)
        sta S2_CAPD
        lda #>(CAPV - BAND)
        sta S2_CAPD+1
        lda #<(CAPM - CAPV)
        sta S2_CAPM
        lda #>(CAPM - CAPV)
        sta S2_CAPM+1
        lda #$80
        sta S2_CAP
        stz hz_x
        stz hz_x+1
        stz hz_i
@char:  lda hz_i
        cmp hz_len
        jcs @end
        clc
        adc hz_lb
        tax
        lda P_TITLE+TL_TEXT,x
        cmp #'a'                ; toupper
        bcc :+
        cmp #'z' + 1
        bcs :+
        sbc #'a' - 'A' - 1      ; (carry clear: - $20)
:       cmp #FONT_LO            ; a font character
        bcc @space
        cmp #FONT_HI + 1
        bcs @space
        sbc #FONT_LO - 1        ; (carry clear: the glyph's index)
        tax
        clc                     ; x + w > SCREENWIDTH: the end
        lda hz_x
        adc hu_fwid,x
        sta hz_t
        lda hz_x+1
        adc #0
        sta hz_t+1
        lda hz_t
        cmp #<(SCREENWIDTH + 1)
        lda hz_t+1
        sbc #>(SCREENWIDTH + 1)
        bcs @end
        lda hz_x                ; V_DrawPatchNotScaled(x, y, patch)
        sta S2_X
        lda hz_x+1
        sta S2_X+1
        lda S2_Y0
        sta S2_Y
        stz S2_Y+1
        lda hu_fbank,x
        sta S2_PBANK
        lda hu_flo,x
        sta S2_PADDR
        lda hu_fhi,x
        sta S2_PADDR+1
        jsr s2_vpatch
        lda hz_t
        sta hz_x
        lda hz_t+1
        sta hz_x+1
        bra @next
@space: clc                     ; another character: a space
        lda hz_x
        adc #SPACE_W
        sta hz_x
        bcc :+
        inc hz_x+1
:       lda hz_x                ; x >= SCREENWIDTH: the end
        cmp #<SCREENWIDTH
        lda hz_x+1
        sbc #>SCREENWIDTH
        bcs @end
@next:  inc hz_i
        jmp @char
@end:   stz S2_CAP
        lda hz_slot             ; I_EndTextCapture
        asl a
        tax
        lda #1
        sta P_TXTSHOWN,x
        stz P_TXTSHOWN+1,x
        ldy hz_lb               ; valid when len <= TEXTMAX
        lda P_TITLE+TL_LEN+1,y
        bne @long
        lda hz_len
        cmp #TEXTMAX + 1
        bcc @valid
@long:  stz P_TXTVALID,x
        stz P_TXTVALID+1,x
        rts
@valid: lda #1
        sta P_TXTVALID,x
        stz P_TXTVALID+1,x
        lda hz_len
        sta P_TXTLEN,x
        stz P_TXTLEN+1,x
        ldy hz_slot
        lda ytab,y
        sta P_TXTY,x
        stz P_TXTY+1,x
        ldx #0                  ; the text
        tya
        beq :+
        ldx #TEXTMAX
:       ldy hz_lb
        lda hz_len
        sta hz_i
@txt:   lda hz_i
        beq @rec
        lda P_TITLE+TL_TEXT,y
        sta P_TXTTEXT,x
        inx
        iny
        dec hz_i
        bra @txt
@rec:   lda #0                  ; the record to S2STATE
        jmp record

; replay: the record back from S2STATE, then each byte of the line's rows
; byte & ~CAPMSK | CAPVAL; its rows marked whole (upstream's code of the
; capture, then markRows(y, y + TEXT_H) [R i_viigs65.s:1822-1840])
replay:
        lda #1
        jsr record
        ldx hz_slot
        lda rowtab,x            ; the bytes: rows * 160 (whole pages, then
        cmp #8                  ;   the rest: 1,600 = 6 * 256 + 64, 1,280 =
        beq :+                  ;   5 * 256)
        ldx #6
        ldy #64
        bra @set
:       ldx #5
        ldy #0
@set:   sty hz_t
        lda #>BAND
        sta @b1+2
        sta @b2+2
        lda #>CAPV
        sta @v+2
        lda #>CAPM
        sta @m+2
        lda #<BAND
        sta @b1+1
        sta @b2+1
        lda #<CAPV
        sta @v+1
        lda #<CAPM
        sta @m+1
        ldy #0
@page:  cpx #0
        bne @byte
        cpy hz_t                ; the last part page
        beq @mark
@byte:
@m:     lda $FFFF,y
        eor #$FF
@b1:    and $FFFF,y
@v:     ora $FFFF,y
@b2:    sta $FFFF,y
        iny
        bne :+
        inc @m+2
        inc @b1+2
        inc @v+2
        inc @b2+2
        dex
:       bra @page
@mark:  stz S2_MB0
        lda #ROW_BYTES - 1
        sta S2_MB1
        lda S2_Y0
        clc
        adc #TEXT_H
        tax
        lda S2_Y0
        jmp s2_mark

; record: A = 0 the record from W to S2STATE (far_put), else back
; (far_get): REC_PAGES pages from CAPV, at SS_HUDTXT + slot * $1000
record:
        sta hz_t+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        lda hz_slot
        asl a
        asl a
        asl a
        asl a
        clc
        adc #>SS_HUDTXT
        sta hz_t
        ldx #0
@page:  lda hz_t+1
        bne @get
        lda #<CAPV
        sta FA_SRC
        txa
        clc
        adc #>CAPV
        sta FA_SRC+1
        lda #<SS_HUDTXT
        sta FA_DST
        txa
        clc
        adc hz_t
        sta FA_DST+1
        phx
        jsr far_put
        bra @next
@get:   lda #<SS_HUDTXT
        sta FA_SRC
        txa
        clc
        adc hz_t
        sta FA_SRC+1
        lda #<CAPV
        sta FA_DST
        txa
        clc
        adc #>CAPV
        sta FA_DST+1
        phx
        jsr far_get
@next:  plx
        inx
        cpx #REC_PAGES
        bcc @page
        rts

; ---------------------------------------------------------------------------
; tables: each row of the line its nibble table pages (ROWL, ROWR: the
; palette's slot, + 1 on an odd row, + 2 for the right pixel [R
; i_viigs65.s:762-787]), the palette's table fetched into the next slot
; the first time this frame
; ---------------------------------------------------------------------------
tables:
        ldx #0
@row:   txa
        clc
        adc S2_Y0
        cmp S2_Y1
        bcs @rts
        tay
        lda PST+PS_SCB,y
        and #$0F
        tay
        lda hz_pslot,y
        bne @have
        phx
        phy
        dec hz_next
        lda hz_next
        asl a
        asl a
        clc
        adc #>SLOTS
        sta hz_pslot,y
        jsr fetch               ; palette Y's table to page A
        ply
        plx
        lda hz_pslot,y
@have:  sta hz_t                ; the row's parity
        txa
        clc
        adc S2_Y0
        and #1
        ora hz_t
        sta ROWL,x
        clc
        adc #2
        sta ROWR,x
        inx
        bra @row
@rts:   rts

; fetch: S2NIB's table of palette Y (1 KB at S2P_NIB + Y * $400 in S2PAL)
; to the page A
fetch:
        sta FA_DST+1
        stz FA_DST
        stz FA_SRC
        tya
        asl a
        asl a
        clc
        adc #>S2P_NIB
        sta FA_SRC+1
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        ldx #4
:       phx
        jsr far_get
        plx
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        rts
