; s2_am.s: the automap's full mode, the image AMAPW (docs/SCREENS.md
; 1.5.4, 4.1; part s2amap, docs/m11-parts/s2amap.md). A GPL-2 rewrite in
; 65C02 of upstream's src/iigs/am_map65.s: AM_Stop, AM_Responder,
; AM_Start, AM_findMinMaxBoundaries [R am_map65.s:224-553], AM_Drawer's
; full mode with its byte lists (eraseOld, drawLines, showBytes,
; clearStrip, clearView, plot's pixFull, rowColors) [R :1021-1100,
; :1179-1306, :1337-1389, :1638-1662, :2843-2861]; the window, the ticker,
; the walls and the line loops are s2_amline.s's (shared with OVLW).
;
; Upstream draws the map into the back buffer and lists the bytes it
; wrote; the next frame blacks the old list's bytes, draws again and shows
; both lists' bytes (or all the view's rows after another screen). Here
; the map is composed in four bands of 42 rows in W (each from zeros, the
; frame's lines clipped once into S2STATE's SS_AMSEG, then drawn into each
; band they cross), and each band publishes upstream's bytes: the old
; list's and the new list's (both in the order of the bands), all its rows
; when upstream redraws all, the strip's rows when upstream clears it.
; The screen after AMAPW is upstream's in the map's rows; the strip's and
; the title's rows it blacks are P2DW's to redraw (S2_MAIL's bits).
;
;   am_frame       A = the frame's tics: AM_Ticker for each, then
;                  AM_Drawer's full mode (nothing unless the full map is
;                  on); the state block from and to S2STATE
;   am_responder   AM_Responder: A = the event's type (0 down, 1 up),
;                  X, Y = its key (low, high); A = 1 when it took it
;   am_tick        one AM_Ticker (the overlay's frames and the tests)
;   am_load, am_save   the state block from and to S2STATE (SS_AMAPW)
;
; AMAPW holds neither the input poll nor the effect service: P2DW follows
; it in every full-map frame (1.5.4). Its publishes end drained (RAMWRT
; off). It never calls s2_begin: the frame's colours go out with P2DW,
; which comes after (s2_begun is a byte that stays 1 here).
;
; Places: s2_am.inc (zero page AMZ, W AMW, the state block), and W's
; runtime: the band $8E00-$A83F, the marks $A900 (s2_pub's DRB, DRE), the
; nibble cache NCACHE, the rows' cache bases RBASE, the lines' buffer
; AMSEGBUF, the new byte list $B000-$BFFF.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2amap.inc"
        .include "s2_am.inc"

        .export am_frame, am_responder, am_tick, am_load, am_save
        .export am_seg, am_plot, am_rowcol
        .export s2_marks, s2_begin, s2_begun
        .import am_ticker, am_walls, am_players, am_drawfl, am_getmo
        .import am_windowsize, am_center, am_oldlocnone, am_newftom
        .import am_chgloc, am_tomap, am_momap, am_lt32, am_setauto
        .import am_cp32, am_sub32, am_neg32, am_ftom
        .import ld_ma, ld_mb, st_mr, stw_mr
        .import s2_publish, far_get, far_put
        .import approxdiv

BAND    = AMAPW_RT0             ; 42 rows of 160 bytes
BAND_ROWS = 42
BAND_SIZE = BAND_ROWS * 160
s2_marks = AMAPW_MARKS          ; DRB, then DRE at +$40 (s2_pub.s)
DRB     = s2_marks
DRE     = s2_marks + $40
NCACHE  = s2_marks + $80        ; 4 palettes x 40: the colours' nibbles
RBASE   = NCACHE + 160          ; each row's base in NCACHE (168)
AMSEGBUF  = $AB00                 ; a page of SS_AMSEG or of the old list
LIST    = AMAPW_RT3             ; the new byte list, 2,048 entries
LIST_END = AMAPW_RT3_END
AMAP_PAL = 11                   ; i_viigs65.s: the full map's palette
NSLOTS  = 4
M_ZOOMIN  = 66846               ; (int32_t) (1.02 * FRACUNIT)
M_ZOOMOUT = 64250               ; (int32_t) (FRACUNIT / 1.02)
INITSCALE = 45875               ; (int32_t) (0.7 * FRACUNIT)
EV_KEYDOWN = 0
EV_KEYUP   = 1
; the stops PL_AMPALS (a frame whose map rows use more than 4 palettes)
; and PL_AMSEGS (more lines than SS_AMSEG holds) are s2.inc's (S2AMAP-4)

        .assert ST_END - AMST <= 256, error, "the state block's page"
        .assert RBASE + 168 <= AMSEGBUF, error, "RBASE"
        .assert NCACHE >= DRE + $40, error, "NCACHE after the marks"
        .assert BAND + BAND_SIZE <= AMW, error, "the band"
        .assert AMW_END <= s2_marks, error, "the W variables"
        .assert AMZ_END <= $B0, error, "the zero page"
        .assert AMSEGBUF + 256 <= AMAPW_STATE, error, "AMSEGBUF"

        .segment "S2CODE"

s2_begin:                       ; (never called: s2_begun stays 1)
        rts

; ---------------------------------------------------------------------------
; am_load, am_save: the state block (its first page: the fields of
; s2layout's field map and this part's) from and to S2STATE's SS_AMAPW
; ---------------------------------------------------------------------------
am_load:
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
am_save:
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

; am_mail: what the tic and the frames left in S2_MAIL: an AM_Stop of the
; tics (R6), a view drawn without the overlay (upstream's display then
; zeroes am_valid and am_band [R d_main65.s:497-503])
am_mail:
        lda S2_MAIL
        and #MAIL_AMSTOP
        beq :+
        jsr am_stop
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

; am_stop: AM_Stop [R am_map65.s:224-236]
am_stop:
        lda ST_AMMODE           ; the overlay on the half view ends
        cmp #2
        bne :+
        lda #3
        sta ST_AMMODE
:       stz ST_MODE
        stz ST_MODE+1
        lda #1
        sta ST_STOPPED
        stz ST_STOPPED+1
        rts

; am_tick: one AM_Ticker, the state block loaded and saved
am_tick:
        jsr am_load
        jsr am_mail
        jsr am_getmo
        jsr am_ticker
        jsr am_setauto
        jmp am_save

; ===========================================================================
; am_responder: AM_Responder [R am_map65.s:238-379]
; ===========================================================================

.macro KEYIS key, target
        lda AMEV
        cmp #<key
        bne :+
        lda AMEV+1
        cmp #>key
        bne :+
        jmp target
:
.endmacro

am_responder:
        sta AMTYPE
        stx AMEV
        sty AMEV+1
        jsr am_load
        jsr am_mail
        lda ST_MODE
        and #AMF_ACTIVE
        bne @active
        lda AMTYPE              ; not active: the map key starts the
        beq :+                  ;   automap
        jmp @no
:
        KEYIS AM_KEY_MAP, @start
        jmp @no
@start: jsr am_start
        jmp @yes
@active:
        lda AMTYPE
        cmp #EV_KEYUP
        bne :+
        jmp keyup
:       cmp #EV_KEYDOWN
        beq :+
        jmp @no
:
        ldx #0                  ; a key down
        KEYIS AM_KEY_MAP_RIGHT, @plus
        KEYIS AM_KEY_MAP_LEFT, @minus
        ldx #4
        KEYIS AM_KEY_MAP_UP, @plus
        KEYIS AM_KEY_MAP_DOWN, @minus
        KEYIS AM_KEY_MAP, @map
        KEYIS AM_KEY_MAP_FOLLOW, @follow
        KEYIS AM_KEY_MAP_ZOOMOUT, @zout
        KEYIS AM_KEY_MAP_ZOOMIN, @zin
        jmp @no
@zin:   ldx #0                  ; zoom in
:       lda zin,x
        sta ST_MZOOM,x
        lda zout,x
        sta ST_FZOOM,x
        inx
        cpx #4
        bne :-
        jmp @yes
@zout:  ldx #0                  ; zoom out
:       lda zout,x
        sta ST_MZOOM,x
        lda zin,x
        sta ST_FZOOM,x
        inx
        cpx #4
        bne :-
        jmp @yes
@plus:  lda #0
        bra @pan
@minus: lda #1
@pan:   sta AT7                  ; a pan key (X: the axis): not in the
        lda ST_MODE             ;   follow mode
        and #AMF_FOLLOW
        beq :+
        jmp @no
:
        stx AT6
        jsr panstep
        lda AT7
        beq :+
        PTR PA, M_R
        jsr am_neg32
:       ldx AT6
        ldy #0
:       lda M_R,y
        sta ST_PAN,x
        inx
        iny
        cpy #4
        bne :-
        jmp @yes
@map:   lda ST_MODE             ; the map key: the overlay, then off
        and #AMF_OVERLAY
        beq :+
        jsr am_stop
        jmp @yes
:       lda ST_MODE
        ora #AMF_OVERLAY | AMF_ROTATE | AMF_FOLLOW
        sta ST_MODE
        jmp @yes
@follow:
        lda ST_MODE             ; follow on or off
        eor #AMF_FOLLOW
        sta ST_MODE
        jsr am_oldlocnone
        ldx #<AM_MSG_OFF        ; player.message: a symbol's reference
        ldy #>AM_MSG_OFF
        lda ST_MODE
        and #AMF_FOLLOW
        beq :+
        ldx #<AM_MSG_ON
        ldy #>AM_MSG_ON
:       lda #1
        sta AM_PLMSG
        stx AM_PLMSG+1
        sty AM_PLMSG+2
        stz AM_PLMSG+3
        stz AM_PLMSG+4
@yes:   lda #1
        bra done
@no:    lda #0
done:   sta AMTYPE
        jsr am_setauto
        jsr am_save
        lda AMTYPE
        rts

; keyup: a key up: the pan or the zoom stops (A = 0)
keyup:  ldx #0
        KEYIS AM_KEY_MAP_RIGHT, @pan
        KEYIS AM_KEY_MAP_LEFT, @pan
        ldx #4
        KEYIS AM_KEY_MAP_UP, @pan
        KEYIS AM_KEY_MAP_DOWN, @pan
        KEYIS AM_KEY_MAP_ZOOMOUT, @zoom
        KEYIS AM_KEY_MAP_ZOOMIN, @zoom
        jmp @no
@zoom:  stz ST_MZOOM            ; FRACUNIT
        stz ST_MZOOM+1
        stz ST_MZOOM+3
        stz ST_FZOOM
        stz ST_FZOOM+1
        stz ST_FZOOM+3
        lda #1
        sta ST_MZOOM+2
        sta ST_FZOOM+2
        jmp @no
@pan:   lda ST_MODE
        and #AMF_FOLLOW
        beq :+
        jmp @no
:
        stz ST_PAN,x
        stz ST_PAN+1,x
        stz ST_PAN+2,x
        stz ST_PAN+3,x
@no:    lda #0
        jmp done

zin:    .dword M_ZOOMIN
zout:   .dword M_ZOOMOUT

; panstep: M_R = FTOM(F_PANINC)
panstep:
        lda #4
        sta M_A
        stz M_A+1
        stz M_A+2
        stz M_A+3
        jmp am_ftom

; ===========================================================================
; am_start: AM_Start [R am_map65.s:381-431]: the automap of the level (its
; limits and scale when the level is new), on the player, in the follow
; mode
; ===========================================================================
am_start:
        lda ST_STOPPED
        ora ST_STOPPED+1
        bne :+
        jsr am_stop
:       stz ST_STOPPED
        stz ST_STOPPED+1
        lda ST_LASTLEV          ; a new level: AM_LevelInit
        cmp AM_GAMEMAP
        bne @new
        lda ST_LASTLEV+1
        cmp AM_GAMEMAP+1
        beq @init
@new:   jsr minmax              ; scale_mtof = min_scale_mtof / 0.7
        ldx #ST_MINSC - AMST
        jsr ld_ma
        lda #<INITSCALE
        sta M_B
        lda #>INITSCALE
        sta M_B+1
        stz M_B+2
        stz M_B+3
        jsr approxdiv
        ldx #ST_SCALE - AMST
        jsr st_mr
        PTR PA, ST_MAXSC        ; more than the maximum: the minimum
        PTR PB, ST_SCALE
        jsr am_lt32
        bcc :+
        PTR PA, ST_SCALE
        PTR PB, ST_MINSC
        jsr am_cp32
:       jsr am_newftom
        lda AM_GAMEMAP
        sta ST_LASTLEV
        lda AM_GAMEMAP+1
        sta ST_LASTLEV+1
@init:  lda ST_MODE             ; AM_initVariables
        ora #AMF_ACTIVE | AMF_FOLLOW
        sta ST_MODE
        jsr am_oldlocnone
        ldx #7
:       stz ST_PAN,x
        dex
        bpl :-
        jsr am_windowsize
        jsr am_getmo            ; the window on the player
        PTR PA, ST_MX
        ldy #AM_TH_X
        jsr am_momap
        PTR PA, ST_MY
        ldy #AM_TH_Y
        jsr am_momap
        jsr am_center
        jmp am_chgloc

; minmax: AM_findMinMaxBoundaries: the box of the line ends (upstream's
; else if), the scale limits [R am_map65.s:433-553]
minmax:
        lda #$FF                ; min = INT16_MAX, max = -INT16_MAX
        sta MIN16
        sta MIN16+2
        lda #$7F
        sta MIN16+1
        sta MIN16+3
        lda #$01
        sta MAX16
        sta MAX16+2
        lda #$80
        sta MAX16+1
        sta MAX16+3
        stz AMI
        stz AMI+1
@line:  lda AMI
        cmp AM_NLINES
        lda AMI+1
        sbc AM_NLINES+1
        bcs @box
        lda AMI                 ; a page of 8 lines
        and #7
        bne :+
        jsr linepage
:       lda AMI                 ; Y = the line's record in AMSEGBUF
        and #7
        asl a
        asl a
        asl a
        asl a
        asl a
        tay
        ldx #0                  ; v1.x, v2.x, v1.y, v2.y
        lda AMSEGBUF+AM_LV1X,y
        sta AT0
        lda AMSEGBUF+AM_LV1X+1,y
        jsr mm16
        lda AMSEGBUF+AM_LV2X,y
        sta AT0
        lda AMSEGBUF+AM_LV2X+1,y
        jsr mm16
        ldx #2
        lda AMSEGBUF+AM_LV1Y,y
        sta AT0
        lda AMSEGBUF+AM_LV1Y+1,y
        jsr mm16
        lda AMSEGBUF+AM_LV2Y,y
        sta AT0
        lda AMSEGBUF+AM_LV2Y+1,y
        jsr mm16
        inc AMI
        bne @line
        inc AMI+1
        bra @line
@box:   PTR PA, ST_MINX         ; the limits << MAPBITS
        lda MIN16
        ldx MIN16+1
        jsr am_tomap
        PTR PA, ST_MINY
        lda MIN16+2
        ldx MIN16+3
        jsr am_tomap
        PTR PA, ST_MAXX
        lda MAX16
        ldx MAX16+1
        jsr am_tomap
        PTR PA, ST_MAXY
        lda MAX16+2
        ldx MAX16+3
        jsr am_tomap
        PTR PA, ST_MAXW         ; max_w, max_h
        PTR PB, ST_MAXX
        jsr am_cp32
        PTR PB, ST_MINX
        jsr am_sub32
        PTR PA, ST_MAXH
        PTR PB, ST_MAXY
        jsr am_cp32
        PTR PB, ST_MINY
        jsr am_sub32
        ldx #ST_MAXW - AMST
        jsr ld_mb        ; a = FixedApproxDiv(f_w << 16, max_w)
        lda #<AM_FW
        ldx #>AM_FW
        jsr hidiv
        ldx #AMT - AMW
        jsr stw_mr
        ldx #ST_MAXH - AMST
        jsr ld_mb        ; b = FixedApproxDiv(f_h << 16, max_h)
        lda #<AM_FH
        ldx #>AM_FH
        jsr hidiv
        ldx #AMU - AMW
        jsr stw_mr
        PTR PA, AMT             ; min_scale_mtof: the smaller
        PTR PB, AMU
        jsr am_lt32
        bcs :+
        PTR PA, AMU
:       lda PA
        sta PB
        lda PA+1
        sta PB+1
        PTR PA, ST_MINSC
        jsr am_cp32
        stz M_B                 ; max_scale_mtof = FixedApproxDiv(f_h <<
        stz M_B+1               ;   16, 2 * PLAYERRADIUS)
        lda #2
        sta M_B+2
        stz M_B+3
        lda #<AM_FH
        ldx #>AM_FH
        jsr hidiv
        ldx #ST_MAXSC - AMST
        jsr st_mr
        rts

; hidiv: M_R = FixedApproxDiv(X:A << 16, M_B)
hidiv:
        stz M_A
        stz M_A+1
        sta M_A+2
        stx M_A+3
        jmp approxdiv

; mm16: minMax: the int16 A:AT0 (A high) less than MIN16[X]: the minimum;
; else more than MAX16[X]: the maximum (signed, the overflow fixed) [R
; am_map65.s:532-553]. Y kept.
mm16:   sta AT1
        lda AT0                  ; v - min
        cmp MIN16,x
        lda AT1
        sbc MIN16+1,x
        bvc :+
        eor #$80
:       bpl @max
        lda AT0
        sta MIN16,x
        lda AT1
        sta MIN16+1,x
        rts
@max:   lda AT0                  ; v - max: 0 or negative: no
        sec
        sbc MAX16,x
        sta AT2
        lda AT1
        sbc MAX16+1,x
        bvs @v
        bmi @no
        ora AT2
        beq @no
        bra @set
@v:     bpl @no                 ; (overflow: the sign is the other)
@set:   lda AT0
        sta MAX16,x
        lda AT1
        sta MAX16+1,x
@no:    rts

; linepage: the 8 lines from AMI (a multiple of 8) into AMSEGBUF
linepage:
        lda AMI
        sta FA_SRC
        lda AMI+1
        ldx #5
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<AM_LINE0
        sta FA_SRC
        lda FA_SRC+1
        adc #>AM_LINE0
        sta FA_SRC+1
        lda #<AMSEGBUF
        sta FA_DST
        lda #>AMSEGBUF
        sta FA_DST+1
        lda #AM_LVG0
        sta FA_BANK
        stz FA_N
        jmp far_get

; ===========================================================================
; am_frame: the frame's tics (AM_Ticker), then AM_Drawer's full mode [R
; am_map65.s:1033-1100]
; ===========================================================================
am_frame:
        sta AMTICS
        lda #1
        sta s2_begun
        jsr am_load
        jsr am_mail
        jsr am_getmo
@tic:   lda AMTICS
        beq @draw
        jsr am_ticker
        dec AMTICS
        bra @tic
@draw:  lda ST_MODE             ; the full map only (the overlay is OVLW's)
        and #AMF_ACTIVE | AMF_OVERLAY
        cmp #AMF_ACTIVE
        beq :+
        jmp @end
:       stz ST_AMMODE
        ldx #0                  ; the lines' rows: below the strip when a
        lda HU_ON               ;   message is on, above the title
        beq :+
        ldx #AM_STRIP
:       stx AWTOP
        lda #AM_TITLEY
        sta AWBOT
        stz FFLAGS
        lda ST_VALID            ; the map is on the screen: only the
        ora ST_VALID+1          ;   bytes of the lines
        beq @redraw
        lda AWTOP
        cmp ST_OLDTOP
        bne @redraw
        lda AM_MENU
        ora AM_MENU+1
        bne @redraw
        lda HU_NEW              ; a new message: only its strip is black
        beq @lines
        stz HU_NEW              ;   (clearStrip)
        lda #FF_STRIP
        sta FFLAGS
        lda S2_MAIL
        ora #MAIL_AMSTRIP
        sta S2_MAIL
        bra @lines
@redraw:
        stz HU_NEW              ; all again (clearView; the HUD's texts
        lda #FF_REDRAW          ;   are gone: P2DW draws them)
        sta FFLAGS
        lda S2_MAIL
        ora #MAIL_AMSTRIP | MAIL_AMTITLE
        sta S2_MAIL
        lda #1
        sta ST_BAND
        stz ST_BAND+1
        sta ST_VALID
        stz ST_VALID+1
        lda AWTOP
        sta ST_OLDTOP
@lines: jsr nibcache            ; the colours of the rows
        stz SEGN                ; the lines on the screen, once a frame
        stz SEGN+1
        jsr am_walls
        jsr am_players
        jsr segflush
        lda #<LIST              ; the new list
        sta LNP
        lda #>LIST
        sta LNP+1
        stz OVF
        stz BANDK
@band:  jsr band
        inc BANDK
        lda BANDK
        cmp #BANDS_N
        bne @band
        lda OVF                 ; a full list: all again next time
        beq :+
        stz ST_VALID
        stz ST_VALID+1
:       jsr listsave
@end:   jsr am_setauto
        jmp am_save

BANDS_N = 4

; band: the band BANDK: from zeros, the lines that cross it, published
band:
        lda BANDK
        bne @next
        jsr clearall            ; (the first: W held another image)
        bra @set
@next:  lda OVF                 ; the band before: its listed bytes are
        beq :+                  ;   all it drew (a full list: all)
        jsr clearall
        bra @set
:       jsr clearlisted
@set:   lda BANDK               ; BY0 = 42 k; BOFF = BAND - BY0 * 160
        asl a
        tax
        lda bandy0,x
        sta BY0
        lda bandoff,x
        sta BOFF
        lda bandoff+1,x
        sta BOFF+1
        lda LNP                 ; NB[k]: the band's first new entry
        sec
        sbc #<LIST
        sta AT0
        lda LNP+1
        sbc #>LIST
        lsr a
        ror AT0
        sta NB+1,x
        lda AT0
        sta NB,x
        lda AWTOP                ; PLO = max(AWTOP, BY0), PHI = min(AWBOT,
        cmp BY0                 ;   BY0 + 42)
        bcs :+
        lda BY0
:       sta PLO
        lda BY0
        clc
        adc #BAND_ROWS
        cmp AWBOT
        bcc :+
        lda AWBOT
:       sta PHI
        lda #$FF
        sta LAST
        sta LAST+1
        lda PLO
        cmp PHI
        bcs @pub
        jsr drawsegs
@pub:   jmp publish

bandy0: .word 0, BAND_ROWS, 2 * BAND_ROWS, 3 * BAND_ROWS
bandoff:
        .word BAND, BAND - BAND_ROWS * 160, BAND - 2 * BAND_ROWS * 160
        .word BAND - 3 * BAND_ROWS * 160

; clearall: the band's 6,720 bytes zero
clearall:
        ldx #0
@page:  .repeat BAND_SIZE / 256, k
        stz BAND + k * 256,x
        .endrepeat
        inx
        bne @page
        ldx #<(BAND_SIZE .mod 256) - 1
:       stz BAND + (BAND_SIZE / 256) * 256,x
        dex
        cpx #$FF
        bne :-
        rts

; clearlisted: the bytes the band before listed back to zero (its
; entries NB[k-1] .. the list's end, at the band before's BOFF)
clearlisted:
        lda BANDK
        dec a
        asl a
        tax
        sec                     ; K = BOFF(k-1) - SHR
        lda bandoff,x
        sbc #<SHR
        sta AT6
        lda bandoff+1,x
        sbc #>SHR
        sta AT7
        lda NB,x                ; PA = LIST + 2 NB[k-1]
        asl a
        sta PA
        lda NB+1,x
        rol a
        clc
        adc #>LIST
        sta PA+1
        clc
        lda PA
        adc #<LIST
        sta PA
        bcc :+
        inc PA+1
:
@loop:  lda PA
        cmp LNP
        lda PA+1
        sbc LNP+1
        bcs @done
        ldy #0
        clc
        lda (PA),y
        adc AT6
        sta AT2
        iny
        lda (PA),y
        adc AT7
        sta AT3
        lda #0
        sta (AT2)
        clc
        lda PA
        adc #2
        sta PA
        bcc @loop
        inc PA+1
        bra @loop
@done:  rts

; drawsegs: each of the frame's lines whose rows meet PLO .. PHI - 1, drawn
; into the band
drawsegs:
        stz SEGK
        stz SEGK+1
@seg:   lda SEGK
        cmp SEGN
        lda SEGK+1
        sbc SEGN+1
        bcs @done
        lda SEGK                ; a new page of records
        and #31
        bne :+
        jsr segpage
:       lda SEGK
        and #31
        asl a
        asl a
        asl a
        tay
        lda AMSEGBUF+SG_Y0,y      ; the rows ymin .. ymax
        ldx AMSEGBUF+SG_Y1,y
        cmp AMSEGBUF+SG_Y1,y
        bcc :+
        tax                     ; (X: the larger)
        lda AMSEGBUF+SG_Y1,y
:       cmp PHI                 ; ymin >= PHI: not here
        bcs @next
        cpx PLO                 ; ymax < PLO: not here
        bcc @next
        lda AMSEGBUF+SG_X0,y
        sta FL
        lda AMSEGBUF+SG_X0+1,y
        sta FL+1
        lda AMSEGBUF+SG_Y0,y
        sta FL+2
        stz FL+3
        lda AMSEGBUF+SG_X1,y
        sta FL+4
        lda AMSEGBUF+SG_X1+1,y
        sta FL+5
        lda AMSEGBUF+SG_Y1,y
        sta FL+6
        stz FL+7
        lda AMSEGBUF+SG_COL,y
        sta COLI
        jsr am_drawfl
@next:  inc SEGK
        bne @seg
        inc SEGK+1
        bra @seg
@done:  rts

; segpage: the page of SS_AMSEG holding SEGK into AMSEGBUF
segpage:
        lda SEGK+1              ; page = SEGK / 32
        sta AT0
        lda SEGK
        lsr AT0
        ror a
        lsr AT0
        ror a
        lsr AT0
        ror a
        lsr AT0
        ror a
        lsr AT0
        ror a
        clc
        adc #>SS_AMSEG
        sta FA_SRC+1
        lda #<SS_AMSEG
        sta FA_SRC
        lda #<AMSEGBUF
        sta FA_DST
        lda #>AMSEGBUF
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jmp far_get

; am_seg: a line on the screen (FL, COLI) into AMSEGBUF, a full page to
; SS_AMSEG
am_seg:
        lda SEGN+1              ; (at most AM_SEG_MAX: lines and arrows)
        cmp #>AM_SEG_MAX
        bcc :+
        lda #PL_AMSEGS
        sta PL_STATUS
        brk
        .byte 0
:       lda SEGN
        and #31
        asl a
        asl a
        asl a
        tay
        lda FL
        sta AMSEGBUF+SG_X0,y
        lda FL+1
        sta AMSEGBUF+SG_X0+1,y
        lda FL+2
        sta AMSEGBUF+SG_Y0,y
        lda FL+4
        sta AMSEGBUF+SG_X1,y
        lda FL+5
        sta AMSEGBUF+SG_X1+1,y
        lda FL+6
        sta AMSEGBUF+SG_Y1,y
        lda COLI
        sta AMSEGBUF+SG_COL,y
        inc SEGN
        bne :+
        inc SEGN+1
:       lda SEGN
        and #31
        bne :+
        jsr segput              ; (a full page: the one before SEGN)
:       rts

; segflush: the last page when it is not full
segflush:
        lda SEGN
        and #31
        beq :+
        lda SEGN                ; round up: its page is SEGN / 32
        ora #31
        clc
        adc #1
        sta AT0
        lda SEGN+1
        adc #0
        sta AT1
        bra segput2
:       rts
; segput: AMSEGBUF to the page (SEGN - 1) / 32 of SS_AMSEG
segput: lda SEGN
        sta AT0
        lda SEGN+1
        sta AT1
segput2:
        lda AT0                  ; page = AT1:AT0 / 32 - 1
        lsr AT1
        ror a
        lsr AT1
        ror a
        lsr AT1
        ror a
        lsr AT1
        ror a
        lsr AT1
        ror a
        dec a
        clc
        adc #>SS_AMSEG
        sta FA_DST+1
        lda #<SS_AMSEG
        sta FA_DST
        lda #<AMSEGBUF
        sta FA_SRC
        lda #>AMSEGBUF
        sta FA_SRC+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jmp far_put

; am_plot: the pixel PX of the row LNY in NIBH, NIBL, when the row is one
; of PLO .. PHI - 1: into the band, and its byte into the new list (once
; after the entry before; none once the list is full) [R am_map65.s:1337-
; 1389]
am_plot:
        lda LNY
        cmp PLO
        bcc @out
        cmp PHI
        bcs @out
        lda PX+1                ; Y = the byte, C = x odd
        lsr a
        lda PX
        ror a
        tay
        bcs @odd
        lda (ROWP),y            ; x even: the high nibble
        and #$0F
        ora NIBH
        sta (ROWP),y
        bra @list
@odd:   lda (ROWP),y            ; x odd: the low nibble
        and #$F0
        ora NIBL
        sta (ROWP),y
@list:  tya                     ; its byte on the screen: X low, A high
        clc
        adc SROW
        tax
        lda SROW+1
        adc #0
        cpx LAST
        bne :+
        cmp LAST+1
        beq @out
:       stx LAST
        sta LAST+1
        lda OVF
        bne @out
        lda LNP+1
        cmp #>LIST_END
        bcs @full
        txa
        sta (LNP)
        ldy #1
        lda LAST+1
        sta (LNP),y
        clc
        lda LNP
        adc #2
        sta LNP
        bcc @out
        inc LNP+1
@out:   rts
@full:  lda #1
        sta OVF
        rts

; am_rowcol: NIBH, NIBL of the colour COLI in the row LNY (rowColors: the
; nibble table of the row's palette and parity [R am_map65.s:2843-2861])
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
; nibcache: each row's palette (I_ViewPalette(AMAP_PAL) of display, then
; the palette state's scb: the strip's rows may hold MSG_PAL), the
; colours' nibbles of each palette from S2NIB (upstream's NIBTAB: left
; even, left odd, right even, right odd pages) into NCACHE, and each row's
; base in it (palette slot * 40 + parity * 20; the left nibbles, then the
; right ones 10 on)
; ---------------------------------------------------------------------------
nibcache:
        lda #<(SS_PALST + PS_SCB)
        sta FA_SRC
        lda #>(SS_PALST + PS_SCB)
        sta FA_SRC+1
        lda #<BAND
        sta FA_DST
        lda #>BAND
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        lda #AM_FH
        sta FA_N
        jsr far_get
        lda #<(SS_PALST + PS_VIEWPAL)
        sta FA_SRC
        lda #>(SS_PALST + PS_VIEWPAL)
        sta FA_SRC+1
        lda #<AT0
        sta FA_DST
        stz FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        lda AT0                  ; I_ViewPalette(AMAP_PAL): the view's rows
        cmp #AMAP_PAL           ;   get it when the view had another
        beq :+
        ldx #AM_FH - 1
        lda #AMAP_PAL
@all:   sta BAND,x
        dex
        cpx #$FF
        bne @all
:       ldx #NSLOTS - 1         ; the slots: none
        lda #$FF
:       sta slotp,x
        dex
        bpl :-
        stz AT1                  ; the slots used
        ldy #0
@row:   lda BAND,y
        cmp #16
        bcc :+
        jmp @bad
:
        ldx #0
:       cpx AT1
        beq @newslot
        cmp slotp,x
        beq @found
        inx
        bra :-
@newslot:
        cpx #NSLOTS
        bcc :+
        jmp @bad
:
        sta slotp,x
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
        cpy #AM_FH
        beq :+
        jmp @row
:
        stz AT3                  ; each slot's nibbles
@slot:  ldx AT3
        cpx AT1
        beq @done
        lda slotp,x             ; S2NIB + palette * $400 -> BAND + $100
        asl a
        asl a
        clc
        adc #>S2P_NIB
        sta AT4
        ldx #0
:       lda AT4
        sta FA_SRC+1
        stz FA_SRC
        txa
        clc
        adc #>(BAND + $100)
        sta FA_DST+1
        lda #<(BAND + $100)
        sta FA_DST
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        phx
        jsr far_get
        plx
        inc AT4
        inx
        cpx #4
        bne :-
        ldx AT3
        lda slot40,x
        tax
        ldy #0
@col:   phy
        lda colours,y
        tay
        lda BAND + $100,y       ; the left pixel, even row
        sta NCACHE,x
        lda BAND + $300,y       ; the right pixel, even row
        sta NCACHE+10,x
        lda BAND + $200,y       ; the left pixel, odd row
        sta NCACHE+20,x
        lda BAND + $400,y       ; the right pixel, odd row
        sta NCACHE+30,x
        ply
        inx
        iny
        cpy #AM_NCOLOURS
        bne @col
        inc AT3
        jmp @slot
@done:  rts
@bad:   lda #PL_AMPALS
        sta PL_STATUS
        brk
        .byte 0

slot40: .byte 0, 40, 80, 120
colours: AM_COLOURS

; ---------------------------------------------------------------------------
; publish: the band's bytes on the screen (upstream's: showBytes' lists or
; I_MarkRect's rows [R am_map65.s:1059-1100, :1273-1306])
; ---------------------------------------------------------------------------
publish:
        lda FFLAGS
        and #FF_REDRAW
        beq @lists
        lda #0                  ; all again: every row of the band
        ldx #BAND_ROWS
        jmp rows
@lists: jsr pubold              ; the old list's bytes of the band
        lda BANDK               ; and the new list's
        asl a
        tax
        lda NB,x
        asl a
        sta PA
        lda NB+1,x
        rol a
        sta PA+1
        clc
        lda PA
        adc #<LIST
        sta PA
        lda PA+1
        adc #>LIST
        sta PA+1
        sec                     ; their count: (LNP - PA) / 2
        lda LNP
        sbc PA
        sta AT0
        lda LNP+1
        sbc PA+1
        lsr a
        ror AT0
        sta AT1
        jsr pubents
        lda #$FF                ; the rows: the strip (clearStrip), the
        sta AT4                  ;   lines' rows once the list is full
        stz AT5
        lda BANDK
        bne :+
        lda FFLAGS
        and #FF_STRIP
        beq :+
        stz AT4
        lda #AM_STRIP
        sta AT5
:       lda OVF
        beq @rows
        lda PLO
        cmp PHI
        bcs @rows
        sec
        sbc BY0
        cmp AT4
        bcs :+
        sta AT4
:       lda PHI
        sec
        sbc BY0
        cmp AT5
        bcc @rows
        sta AT5
@rows:  lda AT4
        cmp AT5
        bcs @none
        ldx AT5
        bra rows
@none:  rts

; rows: the band's rows A .. X - 1, every byte, by s2_publish
rows:   sta S2_DRY0
        stx S2_DRY1
        tax
:       stz DRB,x
        lda #160
        sta DRE,x
        inx
        cpx S2_DRY1
        bne :-
        lda #<BAND
        sta S2_BAND
        lda #>BAND
        sta S2_BAND+1
        lda BY0
        sta S2_Y0
        jmp s2_publish

; pubold: the old list's entries of the band (ST_OB[k] .. ST_OB[k+1], or
; ST_ON for the last), a page of them at a time from SS_AMOLD
pubold:
        lda BANDK
        asl a
        tax
        lda ST_OB,x             ; AT2:AT3 = the first entry
        sta AT2
        lda ST_OB+1,x
        sta AT3
        cpx #6                  ; the end
        bcc :+
        lda ST_ON
        sta AT4
        lda ST_ON+1
        sta AT5
        bra @page
:       lda ST_OB+2,x
        sta AT4
        lda ST_OB+3,x
        sta AT5
@page:  lda AT2                  ; AT0:AT1 = min(128, end - first)
        cmp AT4
        lda AT3
        sbc AT5
        bcs @done
        sec
        lda AT4
        sbc AT2
        sta AT0
        lda AT5
        sbc AT3
        sta AT1
        bne :+
        lda AT0
        cmp #128
        bcc :++
:       lda #128
        sta AT0
        stz AT1
:       lda AT2                  ; FA_SRC = SS_AMOLD + 2 first
        asl a
        sta FA_SRC
        lda AT3
        rol a
        clc
        adc #>SS_AMOLD
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SS_AMOLD
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       lda #<AMSEGBUF
        sta FA_DST
        sta PA
        lda #>AMSEGBUF
        sta FA_DST+1
        sta PA+1
        lda #S2STATE
        sta FA_BANK
        lda AT0
        asl a
        sta FA_N                ; (128 entries: 0, 256 bytes)
        lda AT2
        clc
        adc AT0
        sta AT2
        bcc :+
        inc AT3
:       jsr far_get
        jsr pubents
        bra @page
@done:  rts

pubsrc  = PB                    ; (zero page: the window keeps it main)
pubdst  = SROW

; pubents: AT1:AT0 entries at (PA): each screen byte from the band (W =
; the entry + BOFF - SHR) to aux 0, CPU stores in one RAMWRT window.
; Changes AT0, AT1, PA, AT6, AT7 and the zero page AMZ+$2F .. (none).
pubents:
        sec                     ; K = BOFF - SHR
        lda BOFF
        sbc #<SHR
        sta AT6
        lda BOFF+1
        sbc #>SHR
        sta AT7
        lda AT0
        ora AT1
        beq @done
        sta RAMWRTON
@loop:  lda (PA)                ; the entry
        sta pubdst
        clc
        adc AT6
        sta pubsrc
        ldy #1
        lda (PA),y
        sta pubdst+1
        adc AT7
        sta pubsrc+1
        lda (pubsrc)
        sta (pubdst)
        clc
        lda PA
        adc #2
        sta PA
        bcc :+
        inc PA+1
:       lda AT0
        bne :+
        dec AT1
:       dec AT0
        lda AT0
        ora AT1
        bne @loop
        sta RAMWRTOFF
@done:  rts


; listsave: the new list to SS_AMOLD (the next frame's old list), its
; entries ST_ON and its bands' first entries ST_OB
listsave:
        sec
        lda LNP
        sbc #<LIST
        sta AT0
        lda LNP+1
        sbc #>LIST
        lsr a
        ror AT0
        sta ST_ON+1
        lda AT0
        sta ST_ON
        ldx #7
:       lda NB,x
        sta ST_OB,x
        dex
        bpl :-
        lda LNP+1               ; pages: (LNP - LIST + 255) / 256
        sec
        sbc #>LIST
        sta AT1
        lda LNP
        beq :+
        inc AT1
:       stz AT2
@page:  lda AT2
        cmp AT1
        beq @done
        clc
        adc #>LIST
        sta FA_SRC+1
        stz FA_SRC
        lda AT2
        clc
        adc #>SS_AMOLD
        sta FA_DST+1
        lda #<SS_AMOLD
        sta FA_DST
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jsr far_put
        inc AT2
        bra @page
@done:  rts

        .segment "S2DATA"
s2_begun:
        .byte 1
slotp:  .res NSLOTS
