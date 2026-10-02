; s2_wi.s: the intermission (docs/SCREENS.md 1.5.5, 1.5.7; part s2wi,
; docs/m11-parts/s2wi.md). The image WIW's own code. Written from upstream's
; src/iigs/wi_stuff65.s (WI_Init's lumps, WI_Drawer, drawStats,
; drawShowNextLoc, drawAtNode, slamBackground, drawCenteredPatch, nextY,
; drawPercent, digitCount, drawNum, drawTime [R wi_stuff65.s:96-200,
; :586-903]), with upstream's back buffer replaced by WIW's band of 40 rows
; (SCREENS.md 1.2) and its lumps by the 2D store's handles (part s2data).
;
;   wi_init     WI_Init: the 33 lumps' handles into W_LUMPS (WIW's own
;               state block), and to its place in S2STATE (SS_WIW)
;   wi_frame    an intermission frame (SCREENS.md 2.1): A bit 0 = a level
;               was left (display's I_SetPalette(0) [R d_main65.s:389-392]);
;               the input poll and the effect service, PALST and W_LUMPS
;               from S2STATE, WI_Drawer, s2_finish, PALST back
;   wi_drawer   WI_Drawer: the stats (state 0) or the map with the next
;               level; in NoState the pointer shows (WI_SNLPTR = 1, as
;               upstream's WI_Drawer writes snl_pointeron [R :586-592])
;
; The frame is composed as upstream draws it: the picture WIMAP0 (its
; palette part once, s2_picpal: a new picture's rows, palettes, nibble
; tables), then the patches in upstream's order. Natively each of the five
; bands of 40 rows gets the picture's rows (s2_rect: every byte marked, as
; upstream's markRows(0, 200)), then every patch that crosses the band,
; clipped to it, then s2_publish. The patches' places and positions are
; listed once a frame (the list: each patch's bank, address, top-left
; corner and height), so the counts and times are computed once.
;
; The nibble tables. A patch's pixel on row r goes through the table of
; the row's palette (PALST's scb[r]) and parity [R patch65.s:3-9]: two
; pages, the left pixel's and the right pixel's. WIW's 8 KB of slots hold
; 16 such units of 2 pages (a palette and a parity), fetched from S2NIB the
; first time a frame needs them; WIMAP0's rows change palette every few
; rows (13 palettes in rows 0-39), so a 22-row patch can need 10 palettes,
; more than eight 1 KB slots, but at most 16 units (tools/native/s2wi.py
; checks every patch of every case). A patch needing more units than are
; free empties the cache first; more than 16 is a stop.
;
; The wi state is milestone 10's (GAME.md 1.5), read through its generated
; lgame.inc (WI_*, G_WMINFO and WM_*); W_LUMPS is WIW's own (s2layout's
; field map: upstream's lumps as 2D store handles). Zero page: the drawers'
; S2_*, the far layer's FA_* and WIW's S2W_* ($80-$AD) only.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2data.inc"
        .include "lgame.inc"
        .include "s2wi.inc"

        .export wi_init, wi_frame, wi_drawer
        .export s2_marks, s2_fbuf, s2_palst, s2_begun, s2_nbuf
        .exportzp s2_fbpages
        .import s2_patch, s2_rect, s2_unmark, s2_publish
        .import s2_palget, s2_palput, s2_finish, s2_setpal, s2_picpal
        .import far_get, far_put, pl_poll, fx_service

s2_marks   = WIW_MARKS
s2_fbuf    = WIW_FBUF
s2_fbpages = WIW_FBPAGES
s2_palst   = PALST_W
s2_begun   = PALST_W + PS_BEGUN
s2_nbuf    = WIW_RT2            ; s2_picpal's build buffer: the slots

ROWL     = s2_marks + $80
ROWR     = s2_marks + $C0
BAND     = WIW_RT0              ; 40 rows of 160 bytes
SLOTS    = WIW_RT2              ; 16 units of 2 pages
OWN      = PALST_W + PALST_SIZE ; WIW's own block ($BF00)
SCBS     = PALST_W + PS_SCB

BANDROWS = 40
NUNITS   = 16
MAXE     = 47                   ; the list's entries: drawStats' most
;   (2 titles, 3 x (a label, %, 5 digits), 3 x (a label, 7 fields))
PICSIZE  = 32000                ; a picture's pixels, then its SCBs
NLUMPS   = 33

; the lumps in upstream's order of lumpNames [R wi_stuff65.s:52-68]
L_WIMAP0 = 0
L_WIF    = 1
L_WIENTER = 2
L_WICOLON = 3
L_WISUCKS = 4
L_WIPCNT = 5
L_WIURH0 = 6
L_WISPLAT = 7
L_WIOSTK = 8
L_WIOSTI = 9
L_WISCRT2 = 10
L_WITIME = 11
L_WIMSTT = 12
L_WIPAR  = 13
L_WINUM  = 14                   ; WINUM0..9
L_WILV   = 24                   ; WILV00..08

WI_TITLEY = 2                   ; [R wi_stuff65.s:39-49]
SP_STATSX = 50
SP_STATSY = 50
SP_TIMEX = 8
SP_TIMEY = 160
LINEHEIGHT = 18
FONTWIDTH = 11
SCREENW  = 320
SCREENH  = 200
NODE_TOP = 45                   ; "you are here": patch top = node y - 15

; WIW's temporaries in zero page $80-$AD (S2W_*: request S2WI-1; the
; menu's and the automap's own range, free while WIW runs)
S2W      = $80
px       = S2W + 0              ; the x of a drawLump (2)
wx       = S2W + 2              ; WI_X (2)
wy       = S2W + 4              ; WI_Y (2)
wy2      = S2W + 6              ; WI_Y2 (2)
wn       = S2W + 8              ; WI_N (2)
wt       = S2W + 10             ; WI_T (4)
dv       = S2W + 14             ; a dividend, then the quotient (4)
wlast    = S2W + 18             ; WI_LAST in drawShowNextLoc (2)
wi       = S2W + 20             ; WI_I (2)
nlist    = S2W + 22             ; the list's entries
eidx     = S2W + 23
er0      = S2W + 24             ; the rows of a patch in the band
er1      = S2W + 25
emiss    = S2W + 26
ekey     = S2W + 27
u_next   = S2W + 28             ; the next free unit
wd       = S2W + 29             ; WI_D
wfld     = S2W + 30             ; WI_LAST in drawTime: the fields drawn
wk       = S2W + 31
nk       = S2W + 32
dsor     = S2W + 33
wf_flags = S2W + 34
pk_bank  = S2W + 35             ; a patch: its place, its header (width,
pk_alo   = S2W + 36             ;   height, left and top offsets: 8
pk_ahi   = S2W + 37             ;   bytes as the patch has them)
pk_w     = S2W + 38
pk_h     = S2W + 40
pk_lofs  = S2W + 42
pk_tofs  = S2W + 44
PK_SIZE  = 11
S2W_END  = S2W + 46

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; wi_init: WI_Init [R wi_stuff65.s:139-169]: the lumps by name become the
; 2D store's handles, a table of this image.
; ---------------------------------------------------------------------------
wi_init:
        ldx #NLUMPS - 1
:       lda wi_handles,x
        sta W_LUMPS,x
        dex
        bpl :-
        jsr ssw
        sta FA_DST
        stx FA_DST+1
        lda #<W_LUMPS
        sta FA_SRC
        lda #>W_LUMPS
        sta FA_SRC+1
        jmp far_put

; ssw: FA_BANK, FA_N for W_LUMPS's place in S2STATE, its address in A, X
ssw:
        lda #S2STATE
        sta FA_BANK
        lda #NLUMPS
        sta FA_N
        lda #<(SS_WIW + W_LUMPS - OWN)
        ldx #>(SS_WIW + W_LUMPS - OWN)
        rts

; ---------------------------------------------------------------------------
; wi_frame: an intermission frame. A bit 0: a level was left.
; ---------------------------------------------------------------------------
wi_frame:
        sta wf_flags
        lda #0                  ; pl_poll's A: no menu up (a menu over the
        jsr pl_poll             ;   intermission is MENUW's frame)
        jsr fx_service
        jsr s2_palget
        jsr ssw
        sta FA_SRC
        stx FA_SRC+1
        lda #<W_LUMPS
        sta FA_DST
        lda #>W_LUMPS
        sta FA_DST+1
        jsr far_get
        lda wf_flags
        and #1
        beq :+
        lda #0                  ; I_SetPalette(0)
        jsr s2_setpal
:       jsr wi_drawer
        jsr s2_finish
        jmp s2_palput

; ---------------------------------------------------------------------------
; wi_drawer: WI_Drawer [R wi_stuff65.s:586-592].
; ---------------------------------------------------------------------------
wi_drawer:
        stz nlist
        lda WI_STATE
        ora WI_STATE+1
        bne @loc
        jsr stats
        bra draw
@loc:   lda WI_STATE+1
        bpl :+
        lda #1                  ; NoState: the pointer shows
        sta WI_SNLPTR
        stz WI_SNLPTR+1
:       jsr nextloc

; draw: the picture's palette part, then each band: the picture's rows,
; the listed patches crossing it, published
draw:
        ldx #L_WIMAP0
        jsr place
        lda pk_bank
        sta pic_bank
        sta S2_PBANK
        lda pk_alo
        sta pic_alo
        clc
        adc #<PICSIZE
        sta S2_PADDR
        lda pk_ahi
        sta pic_ahi
        adc #>PICSIZE
        sta S2_PADDR+1
        lda #<WI_PICNUM
        ldx #>WI_PICNUM
        jsr s2_picpal
        jsr flush
        jsr s2_unmark
        stz S2_CAP              ; no capture (the HUD's records only)
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        stz S2_Y0
@band:  lda S2_Y0
        clc
        adc #BANDROWS
        sta S2_Y1
        lda pic_bank            ; slamBackground: the picture's rows
        sta S2_PBANK
        lda pic_alo
        sta S2_PADDR
        lda pic_ahi
        sta S2_PADDR+1
        lda S2_Y0
        sta S2_RY0
        lda S2_Y1
        sta S2_RY1
        stz S2_RB0
        lda #159
        sta S2_RB1
        jsr s2_rect
        jsr patches
        jsr s2_publish
        lda S2_Y1
        sta S2_Y0
        cmp #SCREENH
        bcc @band
        rts

; patches: each listed patch that crosses the band [S2_Y0, S2_Y1), its
; rows' nibble tables, then s2_patch
patches:
        ldx #0
@e:     cpx nlist
        bcc :+
        rts
:       stx eidx
        lda l_yhi,x             ; the first row: max(top, Y0)
        bmi @neg
        bne @skip               ; top >= 256
        lda l_ylo,x
        cmp S2_Y1
        bcs @skip               ; top >= Y1
        cmp S2_Y0
        bcs @top
@neg:   lda S2_Y0
@top:   sta er0
        clc                     ; the row after the last: min(top + h, Y1)
        lda l_ylo,x
        adc l_h,x
        sta er1
        lda l_yhi,x
        adc #0
        bmi @skip               ; bottom < 0
        bne @full               ; bottom >= 256
        lda er1
        cmp S2_Y0
        beq @skip
        bcc @skip               ; bottom <= Y0
        cmp S2_Y1
        bcc @end
@full:  lda S2_Y1
@end:   sta er1
        jsr ensure
        ldx eidx
        lda l_bank,x
        sta S2_PBANK
        lda l_alo,x
        sta S2_PADDR
        lda l_ahi,x
        sta S2_PADDR+1
        lda l_xlo,x
        sta S2_X
        lda l_xhi,x
        sta S2_X+1
        lda l_ylo,x
        sta S2_Y
        lda l_yhi,x
        sta S2_Y+1
        jsr s2_patch
@skip:  ldx eidx
        inx
        bra @e

; ---------------------------------------------------------------------------
; The nibble tables: units of 2 pages (a palette and a parity: the left
; pixel's page, then the right pixel's), 16 in the slots
; ---------------------------------------------------------------------------

; ensure: the units of the rows er0 .. er1 - 1, and those rows' ROWL, ROWR
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
        cmp #NUNITS
        bcc :+
        brk                     ; a patch needing more than 16 units
:       asl a
        adc #>SLOTS             ; (C clear)
        sta u_page,x
        inc u_next
        jsr ufetch
        jsr ukey
        lda u_page,x
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
; parity X & 1 (left at + parity * $100, right 2 pages on). X, Y kept.
ufetch:
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
        rts

; flush: every unit free
flush:
        ldx #2 * 16 - 1
:       stz u_page,x
        dex
        bpl :-
        stz u_next
        rts

; ---------------------------------------------------------------------------
; The list: a patch's place and header, an entry
; ---------------------------------------------------------------------------

; place: lump X (an index of W_LUMPS): pk_bank, pk_alo, pk_ahi (GFXDIR's
; bank and address of its handle)
place:
        lda W_LUMPS,x
        clc
        adc #<GFXDIR_BK
        sta FA_SRC
        lda #>GFXDIR_BK
        adc #0
        sta FA_SRC+1
        lda #<pk_bank
        sta FA_DST
        lda #>pk_bank
        sta FA_DST+1
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
        bne :+
        inc FA_DST+1
:       dex
        bne @a
        rts

; phead: lump X's place and its header: pk_w, pk_h, pk_lofs, pk_tofs
phead:
        jsr place
        lda pk_alo
        sta FA_SRC
        lda pk_ahi
        sta FA_SRC+1
        lda pk_bank
        sta FA_BANK
        lda #<pk_w
        sta FA_DST
        lda #>pk_w
        sta FA_DST+1
        lda #8
        sta FA_N
        jmp far_get

; lumpat: drawLump [R wi_stuff65.s:171-178]: lump A at px, wy
lumpat:
        tax
        jsr phead
; emit: the patch of pk_* at px, wy less its offsets (V_DrawPatchScaled
; [R i_viigs65.s:1769-1782]) into the list
emit:
        ldx nlist
        cpx #MAXE
        bcc :+
        brk                     ; the list is full
:       lda pk_bank
        sta l_bank,x
        lda pk_alo
        sta l_alo,x
        lda pk_ahi
        sta l_ahi,x
        sec
        lda px
        sbc pk_lofs
        sta l_xlo,x
        lda px+1
        sbc pk_lofs+1
        sta l_xhi,x
        sec
        lda wy
        sbc pk_tofs
        sta l_ylo,x
        lda wy+1
        sbc pk_tofs+1
        sta l_yhi,x
        lda pk_h
        sta l_h,x
        inc nlist
        rts

; centered: drawCenteredPatch [R :678-691]: x = (320 - width) / 2, signed
centered:
        sec
        lda #<SCREENW
        sbc pk_w
        sta px
        lda #>SCREENW
        sbc pk_w+1
        cmp #$80
        ror a
        sta px+1
        ror px
        bra emit

; nexty: nextY [R :693-708]: wy2 = wy + 5 * height / 4
nexty:
        lda pk_h
        sta wt
        lda pk_h+1
        sta wt+1
        asl wt
        rol wt+1
        asl wt
        rol wt+1
        clc
        lda wt
        adc pk_h
        sta wt
        lda wt+1
        adc pk_h+1
        lsr a
        ror wt
        lsr a
        ror wt
        sta wt+1
        clc
        lda wt
        adc wy
        sta wy2
        lda wt+1
        adc wy+1
        sta wy2+1
        rts

; levelx: X = the lump of level A's name (WILV0n) [R :670-675]
levelx:
        clc
        adc #L_WILV
        tax
        rts

; sety: wy = A
sety:
        sta wy
        stz wy+1
        rts

; setpx: px = A
setpx:
        sta px
        stz px+1
        rts

; ---------------------------------------------------------------------------
; drawStats [R wi_stuff65.s:710-783]
; ---------------------------------------------------------------------------
stats:
        lda G_WMINFO + WM_LAST  ; the level's name, "finished" under it
        jsr levelx
        jsr phead
        lda #WI_TITLEY
        jsr sety
        jsr nexty
        jsr centered
        lda wy2
        sta wy
        lda wy2+1
        sta wy+1
        ldx #L_WIF
        jsr phead
        jsr centered
        stz wk                  ; kills, items, secret
@cnt:   ldx wk
        lda statsy,x
        jsr sety
        lda #SP_STATSX
        jsr setpx
        ldx wk
        lda statsl,x
        jsr lumpat
        ldx wk
        ldy counts,x
        lda WI_CNTKILLS,y
        sta wn
        lda WI_CNTKILLS+1,y
        sta wn+1
        jsr percent
        inc wk
        lda wk
        cmp #3
        bne @cnt
        ldx #0                  ; time, total, par
@time:  stx wk
        lda timey,x
        jsr sety
        lda timex,x
        jsr setpx
        lda timel,x
        jsr lumpat
        ldx wk
        lda timewl,x
        sta wx
        lda timewh,x
        sta wx+1
        cpx #2
        beq @par
        ldy times,x             ; cnt_time, cnt_total_time (longs)
        ldx #0
:       lda WI_CNTTIME,y
        sta wt,x
        iny
        inx
        cpx #4
        bne :-
        bra @draw
@par:   lda WI_CNTPAR           ; cnt_par: a word, sign-extended
        sta wt
        lda WI_CNTPAR+1
        sta wt+1
        ldx #0
        asl a
        bcc :+
        dex
:       stx wt+2
        stx wt+3
@draw:  jsr dtime
        ldx wk
        inx
        cpx #3
        bne @time
        rts

; percent: drawPercent [R :785-796]: nothing for a negative wn; else the
; sign at 270 and the digits left of it
percent:
        lda wn+1
        bmi @no
        lda #<(SCREENW - SP_STATSX)
        sta wx
        sta px
        lda #>(SCREENW - SP_STATSX)
        sta wx+1
        sta px+1
        lda #L_WIPCNT
        jsr lumpat
        jsr digits
        jmp drawnum
@no:    rts

; digits: A = WI_calculateDigits(wn), unsigned [R :798-814]
digits:
        ldx #0
@t:     lda wn
        cmp p10lo,x
        lda wn+1
        sbc p10hi,x
        bcc @n
        inx
        cpx #4
        bne @t
@n:     inx
        txa
        rts

; drawnum: drawNum [R :816-836]: A digits of wn from wx leftwards, 11
; pixels each; wx ends at the left end
drawnum:
        sta wd
@d:     lda wd
        beq @r
        dec wd
        sec
        lda wx
        sbc #FONTWIDTH
        sta wx
        sta px
        lda wx+1
        sbc #0
        sta wx+1
        sta px+1
        lda wn
        sta dv
        lda wn+1
        sta dv+1
        stz dv+2
        stz dv+3
        lda #10
        jsr divb
        tax
        lda dv
        sta wn
        lda dv+1
        sta wn+1
        txa
        clc
        adc #L_WINUM
        jsr lumpat
        bra @d
@r:     rts

; dtime: drawTime [R :838-903]: wt seconds (a signed long) ending at wx:
; nothing below 0; "sucks" at 24 hours or more; else minutes:seconds, the
; hours when there are some
dtime:
        lda wt+3
        bpl :+
        rts
:       lda wt                  ; below $15180 (86,400)?
        cmp #$80
        lda wt+1
        sbc #$51
        lda wt+2
        sbc #$01
        lda wt+3
        sbc #0
        bcc @ok
        ldx #L_WISUCKS
        jsr phead
        sec
        lda wx
        sbc pk_w
        sta px
        lda wx+1
        sbc pk_w+1
        sta px+1
        jmp emit
@ok:    stz wfld                ; WI_LAST: the fields drawn
@f:     ldx #3                  ; wt / 60, the remainder in wn
:       lda wt,x
        sta dv,x
        dex
        bpl :-
        lda #60
        jsr divb
        sta wn
        stz wn+1
        ldx #3
:       lda dv,x
        sta wt,x
        dex
        bpl :-
        lda wfld                ; seconds always two digits; the minutes
        beq @two                ;   two when there are hours
        jsr tzero
        bne @two
        jsr digits
        bra @num
@two:   lda #2
@num:   jsr drawnum
        lda wfld                ; always the first colon
        beq @colon
        jsr tzero
        beq @r
@colon: inc wfld
        ldx #L_WICOLON
        jsr phead
        sec
        lda wx
        sbc pk_w
        sta wx
        sta px
        lda wx+1
        sbc pk_w+1
        sta wx+1
        sta px+1
        jsr emit
        bra @f
@r:     rts

; tzero: Z set when wt is 0
tzero:
        lda wt
        ora wt+1
        ora wt+2
        ora wt+3
        rts

; divb: dv (32 bits) / A: the quotient in dv, the remainder in A (A at
; most 60: the remainder stays below 120 while it shifts)
divb:
        sta dsor
        lda #0
        ldx #32
@l:     asl dv
        rol dv+1
        rol dv+2
        rol dv+3
        rol a
        cmp dsor
        bcc :+
        sbc dsor
        inc dv
:       dex
        bne @l
        rts

; ---------------------------------------------------------------------------
; drawShowNextLoc [R wi_stuff65.s:594-645], drawAtNode [R :647-663]
; ---------------------------------------------------------------------------
nextloc:
        lda G_WMINFO + WM_LAST  ; the levels done: to last, or after the
        sta wlast               ;   secret level (last 8) to next - 1
        ldx G_WMINFO + WM_LAST + 1
        stx wlast+1
        cmp #8
        bne @go
        txa
        bne @go
        sec
        lda G_WMINFO + WM_NEXT
        sbc #1
        sta wlast
        lda G_WMINFO + WM_NEXT + 1
        sbc #0
        sta wlast+1
@go:    stz wi
        stz wi+1
@s:     sec                     ; while i <= last (signed)
        lda wlast
        sbc wi
        lda wlast+1
        sbc wi+1
        bvc :+
        eor #$80
:       bmi @sec
        lda wi
        ldx #L_WISPLAT
        jsr node
        inc wi
        bne @s
        inc wi+1
        bra @s
@sec:   lda G_WMINFO + WM_DIDSECRET
        ora G_WMINFO + WM_DIDSECRET + 1
        beq :+
        lda #8
        ldx #L_WISPLAT
        jsr node
:       lda WI_SNLPTR           ; "you are here"
        ora WI_SNLPTR+1
        beq :+
        lda G_WMINFO + WM_NEXT
        ldx #L_WIURH0
        jsr node
:       lda G_WMINFO + WM_NEXT  ; WI_drawEL: "entering", the next level's
        jsr levelx              ;   name under it (its height first)
        jsr phead
        ldx #PK_SIZE - 1
:       lda pk_bank,x
        sta nm_save,x
        dex
        bpl :-
        lda #WI_TITLEY
        jsr sety
        jsr nexty
        ldx #L_WIENTER
        jsr phead
        jsr centered
        ldx #PK_SIZE - 1
:       lda nm_save,x
        sta pk_bank,x
        dex
        bpl :-
        lda wy2
        sta wy
        lda wy2+1
        sta wy+1
        jmp centered

; node: drawAtNode: lump X at node A; "you are here" no higher than 45
node:
        stx nk
        asl a
        asl a
        tay
        lda lnodes,y
        sta px
        lda lnodes+1,y
        sta px+1
        lda lnodes+2,y
        sta wy
        lda lnodes+3,y
        sta wy+1
        cpx #L_WIURH0
        bne :+
        lda wy+1
        bne :+
        lda wy
        cmp #NODE_TOP
        bcs :+
        lda #NODE_TOP
        sta wy
:       lda nk
        jmp lumpat

; ---------------------------------------------------------------------------
; Tables
; ---------------------------------------------------------------------------
        .segment "S2RODATA"

; WI_Init's lumps as the 2D store's handles, in lumpNames' order
wi_handles:
        .byte H_WIMAP0, H_WIF, H_WIENTER, H_WICOLON, H_WISUCKS, H_WIPCNT
        .byte H_WIURH0, H_WISPLAT, H_WIOSTK, H_WIOSTI, H_WISCRT2, H_WITIME
        .byte H_WIMSTT, H_WIPAR
        .byte H_WINUM0, H_WINUM1, H_WINUM2, H_WINUM3, H_WINUM4
        .byte H_WINUM5, H_WINUM6, H_WINUM7, H_WINUM8, H_WINUM9
        .byte H_WILV00, H_WILV01, H_WILV02, H_WILV03, H_WILV04
        .byte H_WILV05, H_WILV06, H_WILV07, H_WILV08
; the places of the levels on the map [R wi_stuff65.s:126-134]
lnodes: .word 185, 164, 148, 143, 69, 122, 209, 102, 116, 89
        .word 166, 55, 71, 56, 135, 29, 71, 24
; the counts' rows and labels
statsy: .byte SP_STATSY, SP_STATSY + LINEHEIGHT, SP_STATSY + 2 * LINEHEIGHT
statsl: .byte L_WIOSTK, L_WIOSTI, L_WISCRT2
counts: .byte 0, WI_CNTITEMS - WI_CNTKILLS, WI_CNTSECRET - WI_CNTKILLS
; the times (time, total, par): the label's row, x and lump, the value's
; right end (WI_X), the long's offset from cnt_time
timey:  .byte SP_TIMEY, (SP_TIMEY + SCREENH) / 2, SP_TIMEY
timex:  .byte SP_TIMEX, SP_TIMEX, SCREENW / 2 + SP_TIMEX
timel:  .byte L_WITIME, L_WIMSTT, L_WIPAR
timewl: .byte <(SCREENW / 2 - SP_TIMEX), <(SCREENW / 2 - SP_TIMEX)
        .byte <(SCREENW - SP_TIMEX)
timewh: .byte >(SCREENW / 2 - SP_TIMEX), >(SCREENW / 2 - SP_TIMEX)
        .byte >(SCREENW - SP_TIMEX)
times:  .byte 0, WI_CNTTOTAL - WI_CNTTIME
; 10, 100, 1000, 10000
p10lo:  .byte <10, <100, <1000, <10000
p10hi:  .byte >10, >100, >1000, >10000

        .segment "S2DATA"

u_page: .res 32                 ; each unit's page, 0 none, $FF wanted
pic_bank: .res 1                ; the picture's place
pic_alo: .res 1
pic_ahi: .res 1
nm_save: .res PK_SIZE           ; the next level's name (its pk_*)
; the list, an array a field
l_bank: .res MAXE
l_alo:  .res MAXE
l_ahi:  .res MAXE
l_xlo:  .res MAXE
l_xhi:  .res MAXE
l_ylo:  .res MAXE
l_yhi:  .res MAXE
l_h:    .res MAXE
