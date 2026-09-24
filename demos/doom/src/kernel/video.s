; Doom for the Appletini -- SHR4 PAL256 video: set-up, palettes, the view
; blit and when it runs (docs/DESIGN.md sections 2, 3 and 8).
;
; video_init turns the SHR screen (aux bank 0) into the Appletini's SHR4
; PAL256 mode (appletini-one/ps_sources/frontend/apple_cycle_renderer.c):
; the pixel area $2000-$9CFF and the SCBs are cleared, the paging byte
; $9DF8 = 0 (progressive), the magic "SHR4"|$80 goes to $9DFC-$9DFF, the
; palette gets PLAYPAL 0, and NEWVIDEO ($C029) = $C1 turns SHR on. The
; screen is then 320x100, one byte per pixel, row y at $2000 + 320*y.
;
; set_palette (A = 0..13) copies PLAYPAL n (DD_DIR_BANK:DD_PLAYPAL + 512*n
; in the converter's data, doomdata.inc; entry i is the bytes G<<4|B and
; $20|R) to $9E00-$9FFF, making sure of the selector nibble 2 in every odd
; byte: every entry is a PAL256 entry. Without DD_PLAYPAL (no converted
; data) palette 0 is a grey ramp. Works from both spaces.
;
; blit_view copies the view buffer (VIEWBUF, 160x84 column major, column x
; at VIEWBUF + 84*x) to SHR rows 0-83, every byte twice (a game pixel is
; two screen pixels wide). The copy runs per column: X = 2x (two halves,
; x < 128 and x >= 128, since 2x must fit in X), Y = the row, and an
; unrolled block of 84 rows of
;       iny / lda (bz_p),y / sta SHR+320*row,x / sta SHR+320*row+1,x
; 17 or 18 cycles per game pixel. It lives in the language card's bank-2
; $D000 area (KLC2), 1,512 bytes.
;
; present: the line-0 policy. The Appletini publishes the SHR shadow at
; the frame marker (line 0): a frame is complete on screen only if nothing
; writes the SHR area while line 0 passes. Outside vertical blanking
; ($C019 bit 7 set: lines 0-191) the next line 0 is at least 70 lines
; (4.45 ms) away, more than the blit takes (tools/a2sim.py: 236,029
; cycles, 3.1 ms at 75 MHz; it needs at least 53 MHz on average to fit),
; so the blit starts at once. During vertical blanking line 0 may be
; closer than that, so present waits for the end of blanking (line 0)
; and blits right after it. The wait costs up to 70 lines (27% of a
; frame); kwaits counts the frames that waited.

.include "kernel.inc"
.include "doomdata.inc"

.import kbuf

; ---------------------------------------------------------------------------
.segment "KZP": zeropage
bz_p:       .res 2              ; the view column being copied

.segment "KBSS"
kwaits:     .res 2              ; frames whose blit waited for line 0
kblits:     .res 2              ; blits done
.export kwaits, kblits

; ---------------------------------------------------------------------------
.segment "KCODE"

video_init:
        stz     RAMWORKS
        sta     RAMWRTON
        ; $2000-$9DFF: pixels, SCBs and the control bytes
        lda     #<SHR_BASE
        sta     ktmp
        lda     #>SHR_BASE
        sta     ktmp+1
        lda     #0
        tay
        ldx     #$9E - $20
:       sta     (ktmp),y
        iny
        bne     :-
        inc     ktmp+1
        dex
        bne     :-
        stz     SHR_PAGING              ; progressive
        ldx     #3
:       lda     shr4_magic,x
        sta     SHR_MAGIC,x
        dex
        bpl     :-
        sta     RAMWRTOFF
        lda     #0
        jsr     set_palette
        lda     #$C1                    ; SHR on, linear
        sta     NEWVIDEO
        rts

shr4_magic:
        .byte   $D3, $C8, $D2, $B4      ; "SHR4" | $80

; ---------------------------------------------------------------------------
; set_palette: A = PLAYPAL number (0..13; others are taken mod 16 and
; must not be used). Leaves the space as it found it.
; ---------------------------------------------------------------------------
set_palette:
        sta     RAMRDON
        sta     RAMWRTON
.ifdef DD_PLAYPAL
        and     #$0F
        asl     a                       ; 512 bytes per palette: hi byte += 2n
        clc
        adc     #>DD_PLAYPAL
        sta     ktmp+1
        lda     #<DD_PLAYPAL
        sta     ktmp
        ldx     #0                      ; X = 0, 1: the two halves
@half:  lda     #DD_DIR_BANK
        sta     RAMWORKS
        ldy     #0
:       lda     (ktmp),y
        sta     kbuf,y
        iny
        bne     :-
        stz     RAMWORKS
        cpx     #0
        bne     @hi
:       lda     kbuf,y
        sta     SHR_PAL,y
        iny
        lda     kbuf,y
        and     #$0F
        ora     #$20                    ; selector 2: PAL256
        sta     SHR_PAL,y
        iny
        bne     :-
        inc     ktmp+1
        inx
        bra     @half
@hi:
:       lda     kbuf,y
        sta     SHR_PAL+256,y
        iny
        lda     kbuf,y
        and     #$0F
        ora     #$20
        sta     SHR_PAL+256,y
        iny
        bne     :-
.else
        ; no data: a grey ramp, entry i = (i >> 4) in all three channels
        stz     RAMWORKS
        lda     #<SHR_PAL
        sta     ktmp
        lda     #>SHR_PAL
        sta     ktmp+1
        ldx     #0
@grey:  txa
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     ktmp+2                  ; the level, 0..15
        asl     a
        asl     a
        asl     a
        asl     a
        ora     ktmp+2                  ; G<<4|B
        ldy     #0
        sta     (ktmp),y
        lda     ktmp+2
        ora     #$20                    ; selector 2 | R
        iny
        sta     (ktmp),y
        inc     ktmp
        inc     ktmp
        bne     :+
        inc     ktmp+1
:       inx
        bne     @grey
.endif
        lda     kspace
        bne     @game
        sta     RAMRDOFF
        sta     RAMWRTOFF
        rts
@game:  lda     #GAME_BANK
        sta     RAMWORKS
        rts

; ---------------------------------------------------------------------------
; present: blit the view when line 0 will not pass during the copy.
; ---------------------------------------------------------------------------
present:
        lda     RDVBLBAR
        bmi     present_blit            ; lines 0-191: at once
        inc     kwaits
        bne     present_wait
        inc     kwaits+1
present_wait:                           ; tools/a2sim.py skips this wait ("line0")
        lda     RDVBLBAR
        bpl     present_wait
present_blit:
        jsr     blit_view
present_done:
        inc     kblits
        bne     :+
        inc     kblits+1
:       rts
.export present_wait, present_blit, present_done

; ---------------------------------------------------------------------------
; blit_view: VIEWBUF -> SHR rows 0-83 (aux bank 0), from RENDER space.
; ---------------------------------------------------------------------------
.segment "KLC2"

blit_view:
        stz     RAMWORKS
        sta     RAMWRTON
        lda     #<VIEWBUF
        sta     bz_p
        lda     #>VIEWBUF
        sta     bz_p+1
        ldx     #0
@lo:    jsr     blit_col_lo             ; columns 0-127: X = 0, 2, .. 254
        clc
        lda     bz_p
        adc     #VIEW_H
        sta     bz_p
        bcc     :+
        inc     bz_p+1
:       inx
        inx
        bne     @lo
@hi:    jsr     blit_col_hi             ; columns 128-159: X = 0, 2, .. 62
        clc
        lda     bz_p
        adc     #VIEW_H
        sta     bz_p
        bcc     :+
        inc     bz_p+1
:       inx
        inx
        cpx     #(VIEW_W-128)*2
        bne     @hi
        sta     RAMWRTOFF
        rts

blit_col_lo:
        ldy     #0
.repeat VIEW_H, row
.if row <> 0
        iny
.endif
        lda     (bz_p),y
        sta     SHR_BASE + SHR_ROW*row, x
        sta     SHR_BASE + SHR_ROW*row + 1, x
.endrep
        rts

blit_col_hi:
        ldy     #0
.repeat VIEW_H, row
.if row <> 0
        iny
.endif
        lda     (bz_p),y
        sta     SHR_BASE + SHR_ROW*row + 256, x
        sta     SHR_BASE + SHR_ROW*row + 257, x
.endrep
        rts

.export blit_view
.global video_init
