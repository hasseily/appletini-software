; s2_st.s: the status bar's drawer (docs/SCREENS.md, the status bar; part
; s2stbar), in the per-frame 2D image P2DW. Written from upstream's
; src/iigs/st_stuff65.s (ST_Drawer, refresh, diffDraw, ST_diffNum,
; ST_diffIcon, restoreRect, STlib_updateMultIcon, STlib_drawNum, the percent
; signs, stHide) and i_viigs65.s (I_RestoreStatusRect,
; I_SaveStatusBackground, V_DrawRaw's status bar), with upstream's back
; buffer replaced by the status band in W (rows 168-199 at P2DW_RT0)
; composed and published by part s2draw's drawers.
;
;   st_drawer   ST_Drawer: the menu up: stHide (the bar's rows black and
;               marked; the message strip's too when a message is on or
;               the menu hid one), ST_REFRESHED 0; ST_REFRESHED 0: the
;               whole bar (refresh) and ST_REFRESHED 1; else the widgets
;               whose value changed (diffDraw). The band is published
;               before it returns.
;   s2_rows     each band row's nibble table pages (ROWL, ROWR) from its
;               SCB in PALST: A = the first band row, X = the row after
;               the last. A palette's table is fetched from S2PAL's S2NIB
;               into one of P2DW's eight 1 KB slots the first time the
;               frame needs it (st_nslot, st_slotpal: reset by
;               st_drawer; st_nibs counts the fetches). For part s2hud's
;               strip too.
;
; Upstream's back buffer kept the bar's rows between frames; W does not,
; so the bar's rows as published are kept in S2STATE's STBUF (5,120 B,
; the "shadow"): it equals the screen's rows 168-199 whenever
; ST_REFRESHED is 1. A frame with changes runs the widgets twice: first
; marking only (every rectangle the restores and patches will touch,
; upstream's marks), then each marked row's bytes [DRB, DRE) are fetched
; from STBUF with the rows' tables, then the same widgets restore from
; STCACHE and draw (upstream's order and arithmetic), then the marked
; bytes go back to STBUF and the band is published. Every published byte
; is so upstream's back buffer byte.
;
; Its state: the widgets' old values P_OLDREADY .. P_OLDKEYS (21 words,
; upstream's widget order: ready, health, armor, ammo 0-3, maxammo 0-3,
; arms 0-5, face, keys 0-2) in P2DW's state block; ST_REFRESHED,
; ST_FACEINDEX, ST_KEYBOXES, ST_READY (W_READY's value pointer: an ammo
; index, $FE LARGEAMMO, $FF the frame rate) in the card (part s2stbar's
; tic side writes them); STCACHE and STBUF in S2STATE. It reads the
; player at G_PLAYER (the game's), G_MENUACTIVE, PALST's SCBs, the
; 2D store's patches through GFXDIR (part s2data), and STBAR, STARMS.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2data.inc"
        .include "s2stbar.inc"

        .export st_drawer, s2_rows, st_nibs, st_nslot, st_slotpal
        .import s2_vpatch, s2_raw, s2_rect, s2_mark, s2_unmark, s2_publish
        .import s2_markp
        .import s2_mul160, s2_marks, far_get, far_put, udiv16

BAND     = P2DW_RT0             ; the status band: rows 168-199
SLOTS    = P2DW_RT2             ; eight nibble slots of 1 KB
NSLOTS   = 8
DRB      = s2_marks
DRE      = s2_marks + $40
ROWL     = s2_marks + $80
ROWR     = s2_marks + $C0
ST_Y     = 168
ST_ROWS  = 32
ST_BAND  = ST_ROWS * ROW_BYTES  ; 5,120
STCB     = (SS_STCACHE - ST_Y * ROW_BYTES) & $FFFF   ; s2_rect's row 0
LARGEAMMO = 1994
NNUMS    = 11                   ; the number widgets, then the icons
J_ARMS   = 11
J_FACE   = 17
J_KEYS   = 18
; st_glyph's groups (tools/native/s2stmodel.py GLYPHS)
G_TALL   = 0
G_SHORT  = 10
G_GRAY   = 20
G_KEYS   = 26
G_FACES  = 29
G_PERCENT = 71
G_ARMSBG = 72
G_BAR    = 73

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; st_drawer
; ---------------------------------------------------------------------------
st_drawer:
        stz S2_CAP
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        lda #ST_Y
        sta S2_Y0
        lda #ST_Y + ST_ROWS
        sta S2_Y1
        jsr s2_unmark
        stz st_nslot
        stz st_nibs
        lda G_MENUACTIVE
        ora G_MENUACTIVE+1
        beq :+
        stz ST_REFRESHED        ; the bar again when the menu closes
        jmp sthide
:       lda ST_REFRESHED
        bne diff
        jsr refresh
        inc ST_REFRESHED
        rts

; diffDraw: a marking pass, the marked rows from STBUF, the drawing pass
diff:   stz st_pass
        stz st_mode
        jsr runseq
        lda S2_DRY1
        beq @none
        stz st_put
        jsr eachrow
        lda #$80
        sta st_pass
        jsr runseq
        lda #$80
        sta st_put
        jsr eachrow
        jmp s2_publish
@none:  rts

; eachrow: for each marked band row, st_put clear: its tables and STBUF's
; marked bytes into the band; set: the band's marked bytes into STBUF
eachrow:
        ldx S2_DRY0
@row:   stx st_r
        lda DRE,x
        beq @next
        bit st_put
        bmi :+
        txa
        inx
        jsr s2_rows
        ldx st_r
:       jsr shadow
@next:  ldx st_r
        inx
        cpx S2_DRY1
        bcc @row
        rts

; refresh: the bar and its arms' background, saved in STCACHE; every
; widget; the band into STBUF
refresh:
        lda #$80
        sta st_pass
        lda #0
        ldx #ST_ROWS
        jsr s2_rows
        lda #G_BAR              ; V_DrawRaw(STBAR, 168 * 320)
        jsr gplace
        lda #ST_Y
        sta S2_RY0
        lda #ST_Y + ST_ROWS
        sta S2_RY1
        jsr s2_raw
        lda #104                ; STARMS at (104, 168)
        sta st_x
        stz st_x+1
        lda #ST_Y
        sta st_y
        lda #G_ARMSBG
        jsr stpatch
        lda #<SS_STCACHE        ; I_SaveStatusBackground
        ldx #>SS_STCACHE
        jsr bigput
        lda #$80
        sta st_mode
        jsr runseq
        lda #<SS_STBUF
        ldx #>SS_STBUF
        jsr bigput
        jmp s2_publish

; stHide: the bar's rows black; the message strip's too when a message is
; on or the menu hid one (message_on 0, iigs_textShown's first slot 0,
; VW_MHID 1)
sthide:
        jsr zband
        lda #ST_Y
        ldx #ST_Y + ST_ROWS
        jsr markall
        jsr s2_publish
        lda HU_ON
        ora P_MHID
        beq @done
        stz HU_ON
        stz P_TXTSHOWN
        stz P_TXTSHOWN+1
        lda #1
        sta P_MHID
        stz S2_Y0
        lda #10
        sta S2_Y1
        jsr zband
        lda #0
        ldx #10
        jsr markall
        jmp s2_publish
@done:  rts

markall:
        stz S2_MB0
        ldy #159
        sty S2_MB1
        jmp s2_mark

; zband: the band's 5,120 bytes 0
zband:
        lda #<BAND
        sta FA_DST
        lda #>BAND
        sta FA_DST+1
        ldx #ST_BAND / 256
        lda #0
        tay
:       sta (FA_DST),y
        iny
        bne :-
        inc FA_DST+1
        dex
        bne :-
        rts

; bigput: the band's 5,120 bytes into S2STATE at A (low), X (high)
bigput:
        sta FA_DST
        stx FA_DST+1
        lda #<BAND
        sta FA_SRC
        lda #>BAND
        sta FA_SRC+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        ldx #ST_BAND / 256
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        rts

; shadow: band row X's marked bytes [DRB, DRE) from STBUF into the band
; (st_put clear) or back (st_put set)
shadow:
        stx st_r
        lda DRE,x
        sec
        sbc DRB,x
        sta FA_N
        txa
        jsr s2_mul160
        ldy st_r
        clc
        adc DRB,y
        sta st_t
        txa
        adc #0
        sta st_t+1
        lda #S2STATE
        sta FA_BANK
        clc
        lda st_t
        adc #<SS_STBUF
        tax
        lda st_t+1
        adc #>SS_STBUF
        tay
        clc
        lda st_t
        adc #<BAND
        sta st_t
        lda st_t+1
        adc #>BAND
        sta st_t+1
        bit st_put
        bmi @put
        stx FA_SRC
        sty FA_SRC+1
        lda st_t
        sta FA_DST
        lda st_t+1
        sta FA_DST+1
        jmp far_get
@put:   stx FA_DST
        sty FA_DST+1
        lda st_t
        sta FA_SRC
        lda st_t+1
        sta FA_SRC+1
        jmp far_put

; ---------------------------------------------------------------------------
; s2_rows: A = the first band row, X = the row after the last
; ---------------------------------------------------------------------------
s2_rows:
        sta st_rr
        stx st_rend
@row:   lda st_rr
        cmp st_rend
        bcs @done
        clc
        adc S2_Y0
        tax
        lda PALST_W + PS_SCB,x  ; the row's palette
        and #$0F
        jsr slot
        sta st_t
        lda st_rr
        clc
        adc S2_Y0
        and #1                  ; the row's parity: the odd rows' page
        ora st_t
        ldx st_rr
        sta ROWL,x
        clc
        adc #2
        sta ROWR,x
        inc st_rr
        bra @row
@done:  rts

; slot: A = a palette: A = its slot's first page (fetched when new)
slot:
        ldx st_nslot
@find:  dex
        bmi @new
        cmp st_slotpal,x
        bne @find
        bra @page
@new:   ldx st_nslot
        cpx #NSLOTS
        bcc :+
        brk                     ; (more than 8 palettes in the band)
        .byte $00
:       sta st_slotpal,x
        inc st_nslot
        inc st_nibs
        asl a                   ; S2P_NIB + palette * $400
        asl a
        adc #>S2P_NIB
        sta FA_SRC+1
        stz FA_SRC
        txa
        asl a
        asl a
        adc #>SLOTS
        sta FA_DST+1
        stz FA_DST
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        phx
        ldx #4
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
        plx
@page:  txa
        asl a
        asl a
        clc
        adc #>SLOTS
        rts

; ---------------------------------------------------------------------------
; The widgets
; ---------------------------------------------------------------------------

; runseq: the widgets of st_seqs (st_mode bit 7: refresh's, each drawn;
; else diffDraw's, each when it changed): a widget j, a percent sign $40 |
; k (in diffDraw's, when the number before it was drawn), $FF the end
runseq:
        stz st_si
@loop:  ldx st_si
        inc st_si
        lda st_seqs,x
        cmp #$FF
        beq @done
        cmp #$40
        bcs @pct
        tax
        bit st_mode
        bmi @show
        cpx #NNUMS
        bcs :+
        jsr diffnum
        ror st_drawn
        bra @loop
:       jsr difficon
        bra @loop
@show:  stx st_j
        jsr getval
        lda st_j
        cmp #NNUMS
        bcs :+
        jsr drawnum
        bra @loop
:       jsr updicon
        bra @loop
@pct:   and #1
        bit st_mode
        bmi :+
        bit st_drawn
        bpl @loop
:       jsr percent
        bra @loop
@done:  rts

; getval: X = a widget: st_num its value (upstream's word)
getval:
        cpx #0
        bne @n
        lda ST_READY            ; ready: W_READY's pointer
        cmp #$FE
        bne :+
        lda #<LARGEAMMO
        ldy #>LARGEAMMO
        bra @set
:       cmp #$FF
        bne :+
        lda P_FPSRATE
        ldy P_FPSRATE+1
        bra @set
:       stz S2_O+1              ; the player's ammo[k] (k > 7: past it)
        asl a
        rol S2_O+1
        clc
        adc #<(G_PLAYER + PO_AMMO)
        sta S2_O
        lda S2_O+1
        adc #>(G_PLAYER + PO_AMMO)
        sta S2_O+1
        ldy #1
        lda (S2_O),y
        tay
        lda (S2_O)
        bra @set
@n:     cpx #J_FACE
        beq @face
        bcs @key
        ldy st_src,x            ; a field of the player
        lda G_PLAYER+1,y
        pha
        lda G_PLAYER,y
        ply
        bra @set
@face:  lda ST_FACEINDEX
        ldy #0
        bra @set
@key:   lda ST_KEYBOXES - J_KEYS,x
        ldy #0
        cmp #$80
        bcc @set
        dey
@set:   sta st_num
        sty st_num+1
        rts

; gbase: X = a number widget: A = its glyphs' first (tall, else short)
gbase:
        lda #G_TALL
        cpx #3
        bcc :+
        lda #G_SHORT
:       rts

; diffnum: ST_diffNum of widget X: C set when it was drawn again
diffnum:
        stx st_j
        jsr getval
        jsr oldx
        lda st_num
        cmp P_OLDREADY,x
        bne @chg
        lda st_num+1
        cmp P_OLDREADY+1,x
        bne @chg
        clc
        rts
@chg:   ldx st_j                ; restoreRect(x - w, y, p[0], width)
        jsr gbase
        sta st_g0
        jsr ghead
        ldx st_j
        sec
        lda st_wxl,x
        sbc S2_W
        sta rr_x
        lda st_wxh,x
        sbc S2_W+1
        sta rr_x+1
        lda st_wy,x
        sta rr_y
        lda #3                  ; (every number widget's width)
        sta rr_cnt
        lda st_g0
        jsr strest
        jsr drawnum
        sec
        rts

; oldx: X = st_j * 2 (the widget's old value in P_OLDREADY)
oldx:
        lda st_j
        asl a
        tax
        rts

; drawnum: STlib_drawNum of widget st_j, value st_num
drawnum:
        bit st_pass
        bpl :+
        jsr oldx                ; oldnum = num
        lda st_num
        sta P_OLDREADY,x
        lda st_num+1
        sta P_OLDREADY+1,x
:       lda #3
        sta st_dig
        lda st_num+1            ; a negative number: at least -99, then
        bpl @pos                ;   its digits
        cmp #$FF
        bne @clamp
        lda st_num
        cmp #$9D
        bcs @neg
@clamp: lda #$9D
        sta st_num
        lda #$FF
        sta st_num+1
@neg:   sec
        lda #0
        sbc st_num
        sta st_num
        lda #0
        sbc st_num+1
        sta st_num+1
@pos:   lda st_num              ; LARGEAMMO: no number
        cmp #<LARGEAMMO
        bne @go
        lda st_num+1
        cmp #>LARGEAMMO
        bne @go
        rts
@go:    ldx st_j
        jsr gbase
        sta st_g0
        jsr ghead               ; w = the width of p[0]
        lda S2_W
        sta st_gw
        jsr place
        lda st_num
        ora st_num+1
        bne @loop
        jsr stepx               ; 0: the digit 0 at x - w
        lda st_g0
        jmp stpatch
@loop:  lda st_num              ; while (num && digits--)
        ora st_num+1
        beq @done
        lda st_dig
        beq @done
        dec st_dig
        jsr stepx
        lda st_num
        sta M_A
        lda st_num+1
        sta M_A+1
        lda #10
        sta M_B
        stz M_B+1
        jsr udiv16
        lda M_R
        sta st_num
        lda M_R+1
        sta st_num+1
        lda M_T
        clc
        adc st_g0
        jsr stpatch
        bra @loop
@done:  rts

stepx:
        sec
        lda st_x
        sbc st_gw
        sta st_x
        bcs :+
        dec st_x+1
:       rts

; place: st_x, st_y = widget st_j's place
place:
        ldx st_j
        lda st_wxl,x
        sta st_x
        lda st_wxh,x
        sta st_x+1
        lda st_wy,x
        sta st_y
        rts

; difficon: ST_diffIcon of widget X
difficon:
        stx st_j
        jsr getval
        jsr oldx
        lda st_num
        cmp P_OLDREADY,x
        bne @chg
        lda st_num+1
        cmp P_OLDREADY+1,x
        bne @chg
        rts
@chg:   lda P_OLDREADY,x        ; the old icon's rectangle, unless -1
        and P_OLDREADY+1,x
        cmp #$FF
        beq updicon
        lda P_OLDREADY,x
        ldx st_j
        jsr iconglyph
        pha
        jsr place
        lda st_x
        sta rr_x
        lda st_x+1
        sta rr_x+1
        lda st_y
        sta rr_y
        lda #1
        sta rr_cnt
        pla
        jsr strest
; updicon: STlib_updateMultIcon of widget st_j, value st_num
updicon:
        lda st_num
        and st_num+1
        cmp #$FF
        beq @old
        jsr place
        lda st_num
        ldx st_j
        jsr iconglyph
        jsr stpatch
@old:   bit st_pass
        bpl @rts
        jsr oldx
        lda st_num
        sta P_OLDREADY,x
        lda st_num+1
        sta P_OLDREADY+1,x
@rts:   rts

; iconglyph: X = an icon widget, A = its value: A = the glyph
iconglyph:
        cpx #J_FACE
        bcc @arms
        beq @face
        clc
        adc #G_KEYS
        rts
@face:  clc
        adc #G_FACES
        rts
@arms:  sta st_t                ; arms[i][value]: upstream's [6][2]
        txa
        sec
        sbc #J_ARMS
        asl a
        adc st_t
        tay
        lda st_arms,y
        rts

; percent: A = 0 (health's, x 90) or 1 (armor's, x 221), y 171
percent:
        tax
        lda st_pctx,x
        sta st_x
        stz st_x+1
        lda #ST_Y + 3
        sta st_y
        lda #G_PERCENT
; stpatch: V_DrawNumPatchNotScaled(st_x, st_y, glyph A): drawn, or (the
; marking pass) its rectangle marked
stpatch:
        bit st_pass
        bmi @draw
        jsr ghead
        sec
        lda st_x
        sbc S2_LOFS
        sta S2_X
        lda st_x+1
        sbc S2_LOFS+1
        sta S2_X+1
        sec
        lda st_y
        sbc S2_TOFS
        sta S2_Y
        lda #0
        sbc S2_TOFS+1
        sta S2_Y+1
        jmp s2_markp
@draw:  jsr gplace
        lda st_x
        sta S2_X
        lda st_x+1
        sta S2_X+1
        lda st_y
        sta S2_Y
        stz S2_Y+1
        jmp s2_vpatch

; strest: restoreRect(rr_x, rr_y, glyph A, rr_cnt patches) and
; I_RestoreStatusRect: STCACHE's bytes under rr_cnt patches of the
; glyph's width, the last at rr_x, its offsets applied, copied and marked,
; or (the marking pass) marked. Upstream's 16-bit arithmetic: e = x -
; leftoffset + w, the bytes (e - pw) >> 1 .. (e - 1) >> 1 (arithmetic
; shifts) clipped to 0 .. 159, the rows y - topoffset - 168 .. + h clipped
; to 0 .. 32, nothing when empty (upstream's signed rectEmpty: after the
; clips a negative last or a first past 255 is empty)
stnone: rts
strest:
        jsr ghead
        lda #0                  ; pw = count * w
        tay
        ldx rr_cnt
:       clc
        adc S2_W
        pha
        tya
        adc S2_W+1
        tay
        pla
        dex
        bne :-
        sta rr_pw
        sty rr_pw+1
        sec                     ; e = x - leftoffset + w
        lda rr_x
        sbc S2_LOFS
        tax
        lda rr_x+1
        sbc S2_LOFS+1
        tay
        clc
        txa
        adc S2_W
        sta rr_e
        tya
        adc S2_W+1
        sta rr_e+1
        lda rr_e                ; b1 = (e - 1) >> 1, at most 159
        bne :+
        dec rr_e+1
:       dec a
        tax
        lda rr_e+1
        cmp #$80
        ror a
        tay
        txa
        ror a
        cpy #0
        bmi stnone
        bne @c159
        cmp #160
        bcc :+
@c159:  lda #159
:       sta rr_b1
        lda rr_e                ; (e restored: pw from it)
        bne :+
        inc rr_e+1
:       sec                     ; b0 = (e - pw) >> 1, at least 0
        lda rr_e
        sbc rr_pw
        tax
        lda rr_e+1
        sbc rr_pw+1
        cmp #$80
        ror a
        tay
        txa
        ror a
        cpy #0
        bmi @z0
        bne stnone
        bra :+
@z0:    lda #0
:       sta rr_b0
        lda rr_b1
        cmp rr_b0
        bcc @none
        sec                     ; y0 = y - topoffset - 168
        lda rr_y
        sbc S2_TOFS
        tax
        lda #0
        sbc S2_TOFS+1
        tay
        txa
        sec
        sbc #ST_Y
        tax
        tya
        sbc #0
        tay
        clc                     ; y1 = y0 + h, at most 32
        txa
        adc S2_H
        sta rr_y1
        tya
        adc S2_H+1
        bmi @none
        bne @c32
        lda rr_y1
        cmp #ST_ROWS + 1
        bcc :+
@c32:   lda #ST_ROWS
:       sta rr_y1
        tya                     ; y0, at least 0
        bmi @z1
        bne @none
        txa
        bra :+
@z1:    lda #0
:       cmp rr_y1
        bcs @none
        clc
        adc #ST_Y
        bit st_pass
        bmi @copy
        pha                     ; the marking pass: markVP
        lda rr_b0
        sta S2_MB0
        lda rr_b1
        sta S2_MB1
        lda rr_y1
        clc
        adc #ST_Y
        tax
        pla
        jmp s2_mark
@copy:  sta S2_RY0              ; STCACHE's rows into the band, marked
        lda rr_y1
        clc
        adc #ST_Y
        sta S2_RY1
        lda rr_b0
        sta S2_RB0
        lda rr_b1
        sta S2_RB1
        lda #S2STATE
        sta S2_PBANK
        lda #<STCB
        sta S2_PADDR
        lda #>STCB
        sta S2_PADDR+1
        jmp s2_rect
@none:  rts

; ---------------------------------------------------------------------------
; The 2D store: a glyph's place, its header
; ---------------------------------------------------------------------------

; gplace: A = a glyph: S2_PBANK, S2_PADDR its place (GFXDIR's bank and
; address of its handle)
gplace:
        tax
        lda st_glyph,x
        clc
        adc #<GFXDIR_BK
        sta FA_SRC
        lda #>GFXDIR_BK
        adc #0
        sta FA_SRC+1
        lda #S2_PBANK
        sta FA_DST
        stz FA_DST+1
        lda #1
        sta FA_N
        lda #GFXDIR_BANK
        sta FA_BANK
        ldx #3                  ; the bank, the address's low, high byte
:       jsr far_get
        clc
        lda FA_SRC
        adc #<GFX_NH
        sta FA_SRC
        lda FA_SRC+1
        adc #>GFX_NH
        sta FA_SRC+1
        inc FA_DST
        dex
        bne :-
        rts

; ghead: A = a glyph: its place, and its header (width, height, left and
; top offsets) in S2_W, S2_H, S2_LOFS, S2_TOFS
ghead:
        jsr gplace
        lda S2_PADDR
        sta FA_SRC
        lda S2_PADDR+1
        sta FA_SRC+1
        lda S2_PBANK
        sta FA_BANK
        lda #S2_W
        sta FA_DST
        stz FA_DST+1
        lda #8
        sta FA_N
        jmp far_get

; ---------------------------------------------------------------------------
; Tables
; ---------------------------------------------------------------------------
        .segment "S2RODATA"

; each widget's x and y (ST_createWidgets [R st_stuff65.s:240-385]):
; ready, health, armor (tall numbers at 44, 90, 221, y 171), ammo 0-3
; (288) and maxammo 0-3 (314) at ammoRows' 173, 179, 185, 191 (short
; numbers), arms 0-5 (111 + (i % 3) * 12, 172 + (i / 3) * 10), the face
; (143, 168), the keys (239, 171 + 10 * i)
st_wxl: .byte <44, <90, <221, <288, <288, <288, <288
        .byte <314, <314, <314, <314
        .byte <111, <123, <135, <111, <123, <135, <143, <239, <239, <239
st_wxh: .byte >44, >90, >221, >288, >288, >288, >288
        .byte >314, >314, >314, >314
        .byte >111, >123, >135, >111, >123, >135, >143, >239, >239, >239
st_wy:  .byte ST_Y + 3, ST_Y + 3, ST_Y + 3
        .byte ST_Y + 5, ST_Y + 11, ST_Y + 17, ST_Y + 23
        .byte ST_Y + 5, ST_Y + 11, ST_Y + 17, ST_Y + 23
        .byte ST_Y + 4, ST_Y + 4, ST_Y + 4, ST_Y + 14, ST_Y + 14, ST_Y + 14
        .byte ST_Y, ST_Y + 3, ST_Y + 13, ST_Y + 23
; each widget's field in the player (ready, the face and the keys: their
; own sources): health, armorpoints, ammo[0-3], maxammo[0-3],
; weaponowned[1-6]
st_src: .byte 0, PO_HEALTH, PO_ARMOR
        .byte PO_AMMO, PO_AMMO + 2, PO_AMMO + 4, PO_AMMO + 6
        .byte PO_AMMO + 8, PO_AMMO + 10, PO_AMMO + 12, PO_AMMO + 14
        .byte PO_OWNED + 2, PO_OWNED + 4, PO_OWNED + 6
        .byte PO_OWNED + 8, PO_OWNED + 10, PO_OWNED + 12
st_pctx: .byte 90, 221
; the widgets' order (runseq): diffDraw's; refresh's is the same but its
; health, armor, percent, percent (upstream's [R st_stuff65.s:765-781]):
; the armor's patches and the health's percent sign share no byte, so the
; bytes are the same
st_seqs:
        .byte 0, 3, 7, 4, 8, 5, 9, 6, 10, 1, $40, 2, $41
        .byte J_FACE, J_KEYS, J_KEYS + 1, J_KEYS + 2
        .byte J_ARMS, J_ARMS + 1, J_ARMS + 2, J_ARMS + 3, J_ARMS + 4
        .byte J_ARMS + 5, $FF
; arms[i]: gray STGNUM(i + 2), yellow STYSNUM(i + 2) (as glyphs)
st_arms: .byte G_GRAY, G_SHORT + 2, G_GRAY + 1, G_SHORT + 3
        .byte G_GRAY + 2, G_SHORT + 4, G_GRAY + 3, G_SHORT + 5
        .byte G_GRAY + 4, G_SHORT + 6, G_GRAY + 5, G_SHORT + 7
; the glyphs' 2D store handles: ST_Init's lumps (G_* above)
st_glyph:
        .byte H_STTNUM0, H_STTNUM1, H_STTNUM2, H_STTNUM3, H_STTNUM4
        .byte H_STTNUM5, H_STTNUM6, H_STTNUM7, H_STTNUM8, H_STTNUM9
        .byte H_STYSNUM0, H_STYSNUM1, H_STYSNUM2, H_STYSNUM3, H_STYSNUM4
        .byte H_STYSNUM5, H_STYSNUM6, H_STYSNUM7, H_STYSNUM8, H_STYSNUM9
        .byte H_STGNUM2, H_STGNUM3, H_STGNUM4, H_STGNUM5, H_STGNUM6
        .byte H_STGNUM7
        .byte H_STKEYS0, H_STKEYS1, H_STKEYS2
        .byte H_STFST00, H_STFST01, H_STFST02, H_STFTR00, H_STFTL00
        .byte H_STFOUCH0, H_STFEVL0, H_STFKILL0
        .byte H_STFST10, H_STFST11, H_STFST12, H_STFTR10, H_STFTL10
        .byte H_STFOUCH1, H_STFEVL1, H_STFKILL1
        .byte H_STFST20, H_STFST21, H_STFST22, H_STFTR20, H_STFTL20
        .byte H_STFOUCH2, H_STFEVL2, H_STFKILL2
        .byte H_STFST30, H_STFST31, H_STFST32, H_STFTR30, H_STFTL30
        .byte H_STFOUCH3, H_STFEVL3, H_STFKILL3
        .byte H_STFST40, H_STFST41, H_STFST42, H_STFTR40, H_STFTL40
        .byte H_STFOUCH4, H_STFEVL4, H_STFKILL4
        .byte H_STFGOD0, H_STFDEAD0
        .byte H_STTPRCNT, H_STARMS, H_STBAR

        .segment "S2DATA"

st_pass:   .res 1               ; bit 7: the drawing pass
st_mode:   .res 1               ; bit 7: refresh (every widget drawn)
st_si:     .res 1               ; the sequence's next entry
st_drawn:  .res 1               ; bit 7: diffnum drew the last number
st_put:    .res 1               ; bit 7: shadow puts the band into STBUF
st_nslot:  .res 1               ; the slots in use this frame
st_slotpal: .res NSLOTS         ; each slot's palette
st_nibs:   .res 1               ; nibble tables fetched this frame
st_j:      .res 1               ; the widget
st_r:      .res 1
st_rr:     .res 1
st_rend:   .res 1
st_dig:    .res 1
st_g0:     .res 1               ; the number's glyphs' first
st_gw:     .res 1               ; its width
st_x:      .res 2
st_y:      .res 1
st_num:    .res 2
st_t:      .res 2
rr_x:      .res 2
rr_y:      .res 1
rr_cnt:    .res 1
rr_pw:     .res 2
rr_e:      .res 2
rr_y1:     .res 1
rr_b0:     .res 1
rr_b1:     .res 1
