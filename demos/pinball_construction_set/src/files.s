; Pinball Construction Set for the Appletini -- the title screen, the file
; menu and the game shell entry (DISK.S and SWAP.S replaced: ProDOS files).
;
; files_menu is the editor's disk tool (SWAP_SWAPDISK): under the logo band
; the panel shows LOAD, SAVE, EDIT, QUIT, PLAY GAME and a catalog of the
; table files of the ProDOS prefix directory (BIN files named *.PCS), all
; DOMENU items; the keys L, S, E, Q, P and Esc do the same. A click on a
; catalog entry selects it (a second click loads it). LOAD, EDIT and Esc
; return to the editor (main.s continues into EDIT_REEDIT); SAVE asks for
; a name (letters, digits, periods; Return saves, Esc cancels); PLAY GAME
; runs RUN2's game shell with the port's player-count prompt
; (GETPLAYERCNT, replacing the upstream's XOR text prompt); QUIT asks for
; a second QUIT and leaves to ProDOS.
;
; Table file (docs/DESIGN.md section 11): "PCS1", LOGIC (24), WSET (4),
; PBDATA (count, sizes, records; L-record bytes 0-1 = kind, frame), then
; "OVL1", the 72-byte overlay tile map (ov_tiles) and the pixels of every
; set tile, 32 bytes each (8 rows of 4 bytes) in tile order, run-length
; coded: n (1..127) = n literal bytes follow, $80|n = the next byte n
; times, 0 = the end.
;
; ProDOS: the MLI is called with its file buffer at IOBUF ($BB00, the
; render arena), so nothing is drawn while a file is open; a LOAD checks
; the header, the sizes and the file's length before it touches the
; database. Every variable of this module lives in the player state pages
; (P1STATE, 2 KB, only the game shell uses them), so it costs no BSS; the
; catalog is read again after a game. Without ProDOS (no JMP at $BF00:
; the test machine) the file operations report "NO PRODOS".
;
; Zero page: BASE1/BASE2 ($10-$13) as pointers and PARAM, TEMP, XTEMP,
; YTEMP, TEMP2 as scratch: the upstream's, nothing of the editor's is
; live while the menu runs.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch
.include "assets.inc"

.export files_menu, title_show, GETPLAYERCNT
.export fm_err, fm_count, fm_sel, fm_name, fm_names, fm_flags
.import frame_step, input_getkey, in_btn
.import DOMENU, XDRAWCRSR, CHARTO, PRINT, PRCHAR, CHARBITS
.import set_text_color, text_color
.import panel_fill, panel_frame, panel_sprite, ps_id, ps_x, ps_y
.import pf_x0, pf_y0, pf_x1, pf_y1, pf_color
.import DRAWLOGO, PORT_DRAWDISPLAY, table_normalise
.import ov_tiles, ov_enabled
.import aux_fetch_rows, aux_store_rows
.import af_bank, af_src, af_dst, af_len, af_rows, af_sstride, af_dstride
.import play_begin, play_end, RUN2_DISKPLAY, RUN2_CLOSE2, exit_to_prodos
.import P1STATE, PBBASE, PBDATA, spr_dir, kind_spr0, kind_frames

; MLI calls pcs.inc does not name
MLI_GETMARK = $CF
MLI_SETEOF  = $D0
MLI_GETEOF  = $D1
DEVNUM      = $BF30             ; ProDOS: the last device used

; error codes of this module (outside ProDOS's range)
ERR_FORMAT  = $F0               ; not a table file
ERR_SHORT   = $F1               ; the file ends early
ERR_NOMLI   = $F2               ; no ProDOS

; --- the layout of the panel (screen pixels) ---------------------------
ROW_A_Y     = 66                ; LOAD SAVE EDIT QUIT
ROW_B_Y     = 78                ; PLAY GAME
CAT_Y0      = 90                ; the catalog
CAT_PITCH   = 9
CAT_MAX     = 11                ; entries shown (90..180)
CAT_TX      = 166               ; the names
MSG_Y       = 192               ; the message line
MENU_TOP    = 62                ; the panel below the logo
NAME_MAX    = 11                ; 15 - ".PCS"
; the player-count prompt of the game shell, below the shell's score rows
PP_Y        = 178
PB_X0       = 168               ; the digit boxes: 168 + 30k, 14 wide
PB_PITCH    = 30
PB_W        = 13
PB_Y0       = 187
PB_Y1       = 199
PB_TY       = 190
PP_TOP      = 176
PP_BOT      = 199
; a table's records may use this much of the database
REC_MAX     = $1000

; --- variables in the player state pages ----------------------------------
fm_stage    = P1STATE           ; 512: directory blocks, RLE chunks, output
fm_names    = P1STATE+512       ; CAT_MAX names: length, 15 characters
fm_path     = P1STATE+688       ; a pathname (length byte first), 65 bytes
fm_name     = P1STATE+756       ; the typed name, 16 bytes
fm_parms    = P1STATE+772       ; MLI parameter blocks (parms_tmpl)
p_open      = fm_parms          ; 3, path, buffer, ref
p_rw        = fm_parms+8        ; 4, ref, buffer, request, transferred
p_close     = fm_parms+16       ; 1, ref
p_create    = fm_parms+20       ; 7, path, access, type, aux, storage, dates
p_mark      = fm_parms+32       ; 2, ref, position (3)
p_prefix    = fm_parms+40       ; 1, buffer
p_online    = fm_parms+44       ; 2, unit, buffer
fm_tile     = P1STATE+820       ; one 8x8 tile: 8 rows of 4 bytes
fm_count    = P1STATE+852       ; catalog entries
fm_sel      = P1STATE+853       ; the selected entry, $FF = none
fm_err      = P1STATE+854       ; the last error code, 0 = none
fm_flags    = P1STATE+855       ; bit 7: leave the menu; bit 6: QUIT armed
fm_dblen    = P1STATE+856       ; 16-bit: LOGIC + WSET + PBDATA length
fm_sum      = P1STATE+858       ; 16-bit: the records' length
fm_pos      = P1STATE+860       ; RLE output position in fm_stage
fm_left     = P1STATE+861       ; RLE: bytes left in the run
fm_mode     = P1STATE+862       ; RLE: 0 control, 1 literal, 2 repeat
fm_tpos     = P1STATE+863       ; bytes in fm_tile
fm_trow     = P1STATE+864       ; the current tile
fm_tcol     = P1STATE+865
fm_have     = P1STATE+866       ; bit 7: fm_trow/fm_tcol is a set tile

; --- text ------------------------------------------------------------------
; the font codes: 0..9 digits, 10..35 letters, 36 space; bit 7 ends a string
.macro fcode c, last
    .if (c >= '0') && (c <= '9')
        .byte (c - '0') | last
    .elseif (c >= 'A') && (c <= 'Z')
        .byte (c - 'A' + 10) | last
    .else
        .byte FONT_SPACE | last
    .endif
.endmacro
.macro text str
    .repeat .strlen(str), i
        .if i = .strlen(str) - 1
            fcode {.strat(str, i)}, $80
        .else
            fcode {.strat(str, i)}, 0
        .endif
    .endrepeat
.endmacro
; the text position (x, y) in screen pixels: CHARTO's column and offset
.macro textat px, py
        lda     #((px) .mod 7)
        ldx     #((px) / 7)
        ldy     #(py)
        jsr     CHARTO
.endmacro
.macro prints s
        lda     #<(s)
        ldx     #>(s)
        jsr     PRINT
.endmacro

.segment "RODATA"
s_load:     text "LOAD"
s_save:     text "SAVE"
s_edit:     text "EDIT"
s_quit:     text "QUIT"
s_play:     text "PLAY GAME"
s_select:   text "PICK A TABLE"
s_saved:    text "SAVED"
s_name:     text "NAME "
s_confirm:  text "QUIT AGAIN TO EXIT"
s_notatable: text "NOT A TABLE"
s_diskerr:  text "DISK ERROR "
s_noprodos: text "NO PRODOS"
s_players:  text "HOW MANY PLAYERS"
s_budge:    text "BILL BUDGE 1982"
s_port:     text "APPLETINI PORT"
s_click:    text "CLICK OR PRESS A KEY"
s_magic:    .byte "PCS1"
s_ovl:      .byte "OVL1"
s_pcs:      .byte ".PCS"

; the menu: rectangle records and the (record, handler) list; the catalog
; is one item, do_pick finds the entry under the cursor
r_load:     .byte ROW_A_Y-2, <162, >162, 10, 27, 0
r_save:     .byte ROW_A_Y-2, <204, >204, 10, 27, 0
r_edit:     .byte ROW_A_Y-2, <246, >246, 10, 27, 0
r_quit:     .byte ROW_A_Y-2, <288, >288, 10, 27, 0
r_play:     .byte ROW_B_Y-2, <162, >162, 10, 59, 0
r_cat:      .byte CAT_Y0-1, <162, >162, CAT_MAX*CAT_PITCH-1, 155, 0
menu_list:  .word r_load, do_load, r_save, do_save, r_edit, do_edit
            .word r_quit, do_quit, r_play, do_play, r_cat, do_pick, 0
; the keys and their handlers (less one for the RTS dispatch)
KEYS = 6
key_tab:    .byte 'L', 'S', 'E', 'Q', 'P', $1B
key_lo:     .byte <(do_load-1), <(do_save-1), <(do_edit-1), <(do_quit-1), <(do_play-1), <(do_edit-1)
key_hi:     .byte >(do_load-1), >(do_save-1), >(do_edit-1), >(do_quit-1), >(do_play-1), >(do_edit-1)
; the player-count digits: CHARTO offset and column of x = 174 + 30k
pb_off:     .byte 174 .mod 7, 204 .mod 7, 234 .mod 7, 264 .mod 7
pb_col:     .byte 174 / 7, 204 / 7, 234 / 7, 264 / 7
bitmask:    .byte 1, 2, 4, 8, 16, 32, 64, 128
; the MLI parameter blocks, copied to fm_parms by menu_enter
parms_tmpl: .byte 3, <fm_path, >fm_path, <IOBUF, >IOBUF, 0, 0, 0
            .byte 4, 0, 0, 0, 0, 0, 0, 0
            .byte 1, 0, 0, 0
            .byte 7, <fm_path, >fm_path, $C3, $06, 0, 0, 1, 0, 0, 0, 0
            .byte 2, 0, 0, 0, 0, 0, 0, 0
            .byte 1, <fm_path, >fm_path, 0
            .byte 2, 0, <fm_stage, >fm_stage
PARMS_LEN = 48

.segment "CODE"

; ---------------------------------------------------------------------------
; title_show: the logo, three lines of text and the default table (its
; span database is built here; EDIT's START builds it again) until a
; click or a key. The panel is cleared on the way out.
; ---------------------------------------------------------------------------
title_show:
        lda     MB_NOTITLE
        cmp     #$A5
        beq     @skip                   ; the test machine's hook
        lda     #MB_ST_TITLE
        sta     MB_STATE
        jsr     DRAWLOGO
        textat  196, 72
        prints  s_budge
        textat  198, 84
        prints  s_port
        textat  182, 130
        prints  s_click
        stz     SCANMODE
        jsr     PORT_DRAWDISPLAY
@wait:  jsr     frame_step
        jsr     input_getkey
        bne     @done
        bit     in_btn
        bpl     @wait
@done:  jsr     frame_step              ; the release
        bit     in_btn
        bmi     @done
        lda     #0
        ldx     #SCREEN_H-1
        jmp     panel_rows
@skip:  rts

; ---------------------------------------------------------------------------
; files_menu: the disk tool. The logo band is already drawn (EDIT's DISKIO).
; ---------------------------------------------------------------------------
files_menu:
        lda     #MB_ST_DISK
        sta     MB_STATE
        jsr     menu_enter
@loop:  jsr     frame_step
        jsr     input_getkey
        bne     @key
        bit     in_btn
        bpl     @next
        stz     LASTITEM+1
        lda     #<menu_list
        ldx     #>menu_list
        jsr     DOMENU
@next:  bit     fm_flags
        bpl     @loop
        jmp     menu_clear              ; back to the editor
@key:   and     #$7F
        cmp     #'a'
        bcc     @find
        cmp     #'z'+1
        bcs     @find
        sbc     #$1F                    ; carry clear: upper case
@find:  ldx     #KEYS-1
@k:     cmp     key_tab,x
        beq     @go
        dex
        bpl     @k
        bra     @loop
@go:    jsr     @call
        bra     @next
@call:  lda     key_hi,x
        pha
        lda     key_lo,x
        pha
        rts

; menu_enter: the parameter blocks, the catalog and the menu (also after a
; game, which used the pages all this lives in, and after a SAVE)
menu_enter:
        ldx     #PARMS_LEN-1
:       lda     parms_tmpl,x
        sta     fm_parms,x
        dex
        bpl     :-
        stz     fm_flags
        lda     #$FF
        sta     fm_sel
        jsr     cat_read
menu_draw:
        jsr     menu_clear
        textat  164, ROW_A_Y
        prints  s_load
        textat  206, ROW_A_Y
        prints  s_save
        textat  248, ROW_A_Y
        prints  s_edit
        textat  290, ROW_A_Y
        prints  s_quit
        textat  164, ROW_B_Y
        prints  s_play
        ldx     #0
@cat:   cpx     fm_count
        bcs     @msg
        phx
        jsr     cat_item
        plx
        inx
        bra     @cat
@msg:   lda     fm_err
        beq     :+
        jsr     show_error
:       rts

; cat_item: entry X at (CAT_TX, CAT_Y0 + 9X), without its ".PCS", in
; white when it is the selected one
cat_item:
        lda     #COL_TEXT
        cpx     fm_sel
        bne     :+
        lda     #COL_WHITE
:       jsr     set_text_color
        txa
        asl     a
        asl     a
        asl     a
        sta     TEMP
        txa
        clc
        adc     TEMP
        adc     #CAT_Y0
        tay
        phx
        lda     #CAT_TX .mod 7
        ldx     #CAT_TX / 7
        jsr     CHARTO
        plx
        jsr     sel_name
        lda     (BASE2)
        sec
        sbc     #4
        jsr     print_name
        lda     #COL_TEXT
        jmp     set_text_color

; sel_name: BASE2 = the catalog name X. Keeps X.
sel_name:
        txa
        asl     a
        asl     a
        asl     a
        asl     a
        clc
        adc     #<fm_names
        sta     BASE2
        lda     #>fm_names
        adc     #0
        sta     BASE2+1
        rts

; print_name: A characters of the name at BASE2 (length byte first) at the
; text position: letters, digits, a 2x2 dot for a period. Stops at column
; 44 so a glyph never leaves the screen.
print_name:
        sta     XTEMP
        beq     @done
        ldy     #1
@c:     lda     CHARBITS+3
        cmp     #44
        bcs     @done
        lda     (BASE2),y
        phy
        cmp     #'.'
        beq     @dot
        cmp     #'A'
        bcc     @digit
        sbc     #'A'-FONT_A             ; carry set
        bra     @pr
@digit: sec
        sbc     #'0'
@pr:    jsr     PRCHAR
        bra     @next
@dot:   jsr     print_dot
@next:  ply
        iny
        dec     XTEMP
        bne     @c
@done:  rts

; print_dot: a period: a 2x2 dot on the baseline, then 3 pixels on
print_dot:
        jsr     text_x
        lda     pf_x0
        and     #$FE
        sta     pf_x0
        ora     #1
        sta     pf_x1
        lda     pf_x0+1
        sta     pf_x1+1
        lda     CHARBITS+2
        clc
        adc     #5
        sta     pf_y0
        inc     a
        sta     pf_y1
        lda     text_color
        sta     pf_color
        jsr     panel_fill
        lda     CHARBITS+4
        clc
        adc     #3
        cmp     #7
        bcc     :+
        sbc     #7
        inc     CHARBITS+3
:       sta     CHARBITS+4
        rts

; text_x: pf_x0 = the text position's x (column * 7 + offset), 16-bit
text_x:
        stz     pf_x0+1
        lda     CHARBITS+3
        asl     a
        asl     a
        rol     pf_x0+1
        asl     a
        rol     pf_x0+1                 ; column * 8
        sec
        sbc     CHARBITS+3
        bcs     :+
        dec     pf_x0+1
:       clc
        adc     CHARBITS+4
        sta     pf_x0
        bcc     :+
        inc     pf_x0+1
:       rts

; panel_rows: rows A..X of the panel in the panel colour
panel_rows:
        sta     pf_y0
        stx     pf_y1
        lda     #PANEL_X
        sta     pf_x0
        stz     pf_x0+1
        lda     #<(SCREEN_W-1)
        sta     pf_x1
        lda     #>(SCREEN_W-1)
        sta     pf_x1+1
        lda     #COL_PANEL
        sta     pf_color
        jmp     panel_fill

menu_clear:
        lda     #MENU_TOP
        ldx     #SCREEN_H-1
        bra     panel_rows

msg_clear:
        lda     #MSG_Y
        ldx     #SCREEN_H-1
        bra     panel_rows

; msg_print: A/X = the text, on a cleared message line
msg_print:
        pha
        phx
        jsr     msg_clear
        textat  164, MSG_Y
        plx
        pla
        jmp     PRINT

; show_error: A = the error code -> fm_err and the message line
show_error:
        sta     fm_err
        cmp     #ERR_FORMAT
        beq     @format
        cmp     #ERR_NOMLI
        beq     @nomli
        pha
        lda     #<s_diskerr
        ldx     #>s_diskerr
        jsr     msg_print
        pla
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     PRCHAR                  ; hex digits are their font codes
        pla
        and     #$0F
        jmp     PRCHAR
@format:
        lda     #<s_notatable
        ldx     #>s_notatable
        jmp     msg_print
@nomli: lda     #<s_noprodos
        ldx     #>s_noprodos
        jmp     msg_print

; disarm: a QUIT click is forgotten by any other action
disarm: lda     fm_flags
        and     #$BF
        sta     fm_flags
        rts

; ---------------------------------------------------------------------------
; The menu handlers (DOMENU: entered on the button's release).
; ---------------------------------------------------------------------------
do_edit:
        lda     #$80
        sta     fm_flags
        rts

do_quit:
        bit     fm_flags
        bvs     @go
        lda     fm_flags
        ora     #$40
        sta     fm_flags
        lda     #<s_confirm
        ldx     #>s_confirm
        jmp     msg_print
@go:    jmp     exit_to_prodos

; do_pick: the entry under the cursor (CAT_PITCH rows each from CAT_Y0-1)
do_pick:
        jsr     disarm
        lda     CURSORY
        sec
        sbc     #CAT_Y0-1
        ldx     #0
:       cmp     #CAT_PITCH
        bcc     :+
        sbc     #CAT_PITCH
        inx
        bra     :-
:       cpx     fm_count
        bcs     @none
        cpx     fm_sel
        beq     do_load                 ; the selected entry again: load it
        lda     fm_sel
        stx     fm_sel
        tax
        cpx     #$FF
        beq     :+
        jsr     cat_item                ; the old one back in grey
:       ldx     fm_sel
        jmp     cat_item
@none:  rts

do_load:
        jsr     disarm
        ldx     fm_sel
        bmi     @none
        jsr     load_file
        bcs     @err
        lda     #$80
        sta     fm_flags
        rts
@err:   jmp     show_error
@none:  lda     #<s_select
        ldx     #>s_select
        jmp     msg_print

do_save:
        jsr     disarm
        stz     fm_name
        ldx     fm_sel
        bmi     @prompt
        jsr     sel_name                ; the selection as the default name
        lda     (BASE2)
        sec
        sbc     #4
        sta     fm_name
        tay
:       lda     (BASE2),y
        sta     fm_name,y
        dey
        bne     :-
@prompt:
        jsr     name_prompt
        bcs     @cancel
        lda     fm_name
        beq     @cancel
        jsr     save_file
        bcs     @err
        jsr     menu_enter
        lda     #<s_saved
        ldx     #>s_saved
        jmp     msg_print
@err:   jmp     show_error
@cancel:
        jmp     msg_clear

do_play:
        jsr     disarm
        jsr     menu_clear
        lda     #$80
        jsr     play_begin
        jsr     RUN2_DISKPLAY           ; returns on Esc
        jsr     play_end
        lda     #MB_ST_DISK
        sta     MB_STATE
        jsr     XDRAWCRSR               ; the cursor back
        jmp     menu_enter

; ---------------------------------------------------------------------------
; name_prompt: "NAME " and fm_name with the caret on the message line;
; letters, digits and periods up to NAME_MAX, left arrow or delete erases,
; Return accepts (C clear), Esc cancels (C set).
; ---------------------------------------------------------------------------
name_prompt:
@draw:  jsr     msg_clear
        textat  164, MSG_Y
        prints  s_name
        lda     #<fm_name
        sta     BASE2
        lda     #>fm_name
        sta     BASE2+1
        lda     fm_name
        jsr     print_name
        jsr     text_x
        lda     pf_x0
        sta     ps_x
        lda     pf_x0+1
        sta     ps_x+1
        lda     #MSG_Y
        sta     ps_y
        lda     #SPR_CARET
        sta     ps_id
        jsr     panel_sprite
@key:   jsr     frame_step
        jsr     input_getkey
        beq     @key
        and     #$7F
        cmp     #$0D
        beq     @ok
        cmp     #$1B
        beq     @cancel
        cmp     #$08
        beq     @del
        cmp     #$7F
        beq     @del
        cmp     #'a'
        bcc     :+
        cmp     #'z'+1
        bcs     :+
        sbc     #$1F
:       cmp     #'.'
        beq     @add
        cmp     #'0'
        bcc     @key
        cmp     #'9'+1
        bcc     @add
        cmp     #'A'
        bcc     @key
        cmp     #'Z'+1
        bcs     @key
@add:   ldx     fm_name
        cpx     #NAME_MAX
        bcs     @key
        inx
        sta     fm_name,x
        stx     fm_name
        jmp     @draw
@del:   lda     fm_name
        beq     @key
        dec     fm_name
        jmp     @draw
@ok:    clc
        rts
@cancel:
        sec
        rts

; ---------------------------------------------------------------------------
; GETPLAYERCNT (RUN2's MAIN2, between games): "HOW MANY PLAYERS" and four
; digit boxes below the logo; a digit key or a click sets PLAYERCNT, Esc
; leaves the shell as the upstream's QUIT did (its two callers' returns
; are dropped, CLOSE2 puts the objects' rest state back). The cursor is
; shown for the prompt only. DOMENU is not used here: its NEWITEM/LASTITEM
; are RUN2's LIVEBALLS and GAMEMODE.
; ---------------------------------------------------------------------------
GETPLAYERCNT:
        jsr     XDRAWCRSR
        textat  164, PP_Y
        prints  s_players
        lda     #PB_Y0
        sta     pf_y0
        lda     #PB_Y1
        sta     pf_y1
        lda     #<PB_X0
        sta     pf_x0
        lda     #>PB_X0
        sta     pf_x0+1
        lda     #COL_TEXT
        sta     pf_color
        ldx     #0
@box:   stx     XTEMP                   ; (PRCHAR uses TEMP and TEMP2)
        lda     pf_x0
        clc
        adc     #PB_W
        sta     pf_x1
        lda     pf_x0+1
        adc     #0
        sta     pf_x1+1
        jsr     panel_frame             ; keeps pf_*
        ldx     XTEMP
        lda     pb_col,x
        pha
        lda     pb_off,x
        plx
        ldy     #PB_TY
        jsr     CHARTO
        ldx     XTEMP
        inx
        txa
        jsr     PRCHAR
        lda     pf_x0
        clc
        adc     #PB_PITCH
        sta     pf_x0
        bcc     :+
        inc     pf_x0+1
:       ldx     XTEMP
        inx
        cpx     #4
        bne     @box
@loop:  jsr     frame_step
        jsr     input_getkey
        beq     @nokey
        cmp     #$9B
        beq     @esc
        and     #$7F
        sec
        sbc     #'1'
        cmp     #4
        bcs     @loop
        bra     @set
@nokey: bit     in_btn
        bpl     @loop
        lda     CURSORY                 ; in a box?
        sec
        sbc     #PB_Y0
        cmp     #PB_Y1-PB_Y0+1
        bcs     @loop
        lda     CURSORX
        sec
        sbc     #<PB_X0
        tay
        lda     CURSORXH
        sbc     #>PB_X0
        bne     @loop                   ; left of, or far right of, the boxes
        tya
        ldx     #0
:       cmp     #PB_PITCH
        bcc     :+
        sbc     #PB_PITCH
        inx
        bra     :-
:       cmp     #PB_W+1
        bcs     @loop                   ; between two boxes
        cpx     #4
        bcs     @loop
        txa
@set:   inc     a
        sta     PLAYERCNT
        jmp     pp_end
@esc:   jsr     pp_end
        pla
        pla
        pla
        pla
        jmp     RUN2_CLOSE2

; pp_end: wait for the button's release, erase the prompt, hide the cursor
pp_end: jsr     frame_step
        bit     in_btn
        bmi     pp_end
        lda     #PP_TOP
        ldx     #PP_BOT
        jsr     panel_rows
        jmp     XDRAWCRSR

; ---------------------------------------------------------------------------
; ProDOS. mli: A = the call number, X/Y = the parameter block; returns C
; set with the error in A. Without ProDOS every call fails with ERR_NOMLI.
; ---------------------------------------------------------------------------
mli:    sta     @num
        stx     @parm
        sty     @parm+1
        lda     MLI
        cmp     #$4C
        bne     @none
        jsr     MLI
@num:   .byte   0
@parm:  .word   0
        rts
@none:  lda     #ERR_NOMLI
        sec
        rts

; open_path: open fm_path with the file buffer at IOBUF; the reference
; number goes into the read/write, close and mark blocks
open_path:
        lda     #MLI_OPEN
        ldx     #<p_open
        ldy     #>p_open
        jsr     mli
        bcs     @done
        lda     p_open+5
        sta     p_rw+1
        sta     p_close+1
        sta     p_mark+1
        clc
@done:  rts

; close_all: close every open file (reference 0)
close_all:
        stz     p_close+1
        lda     #MLI_CLOSE
        ldx     #<p_close
        ldy     #>p_close
        jmp     mli

; read_to: A bytes into the buffer X/Y; fm_read: A/X bytes into BASE1.
; A short read is ERR_SHORT. write_from / fm_write: the same for writing.
read_to:
        stx     BASE1
        sty     BASE1+1
        ldx     #0
fm_read:
        jsr     rw_setup
        lda     #MLI_READ
        jsr     rw_call
        bcs     @done
        lda     p_rw+6
        cmp     p_rw+4
        bne     @short
        lda     p_rw+7
        cmp     p_rw+5
        bne     @short
        clc
        rts
@short: lda     #ERR_SHORT
        sec
@done:  rts

write_from:
        stx     BASE1
        sty     BASE1+1
        ldx     #0
fm_write:
        jsr     rw_setup
        lda     #MLI_WRITE
rw_call:
        ldx     #<p_rw
        ldy     #>p_rw
        jmp     mli

rw_setup:
        sta     p_rw+4
        stx     p_rw+5
        lda     BASE1
        sta     p_rw+2
        lda     BASE1+1
        sta     p_rw+3
        rts

; mark_call: A = GET_MARK, SET_EOF or GET_EOF on p_mark
mark_call:
        ldx     #<p_mark
        ldy     #>p_mark
        jmp     mli

; ---------------------------------------------------------------------------
; cat_read: the catalog: the *.PCS files (BIN) of the prefix directory,
; up to CAT_MAX, into fm_names. Without a prefix the last used device's
; volume becomes the prefix (ON_LINE). Errors go to fm_err.
; ---------------------------------------------------------------------------
cat_read:
        stz     fm_count
        stz     fm_err
        lda     #MLI_GETPREFIX
        jsr     prefix_call
        jcs     @err
        lda     fm_path
        bne     @have
        ; no prefix: "/VOLUME/" of the last device used
        lda     DEVNUM
        sta     p_online+1
        lda     #MLI_ONLINE
        ldx     #<p_online
        ldy     #>p_online
        jsr     mli
        bcs     @err
        lda     fm_stage
        and     #$0F
        beq     @novol
        sta     TEMP
        lda     #'/'
        sta     fm_path+1
        ldy     #0
:       lda     fm_stage+1,y
        sta     fm_path+2,y
        iny
        cpy     TEMP
        bne     :-
        lda     #'/'
        sta     fm_path+2,y
        iny
        iny
        sty     fm_path
        lda     #MLI_SETPREFIX
        jsr     prefix_call
        bcs     @err
@have:  ldx     fm_path                 ; the directory: no trailing slash
        lda     fm_path,x
        cmp     #'/'
        bne     :+
        dex
        stx     fm_path
:       jsr     open_path
        bcs     @err
@block: lda     #<512
        ldx     #<fm_stage
        ldy     #>fm_stage
        stx     BASE1
        sty     BASE1+1
        ldx     #>512
        jsr     fm_read
        bcs     @done                   ; the end of the directory
        lda     #<(fm_stage+4)          ; past the block's links
        sta     BASE1
        lda     #>(fm_stage+4)
        sta     BASE1+1
        lda     #13                     ; entries per block
        sta     TEMP2
@entry: jsr     cat_entry
        lda     BASE1
        clc
        adc     #39                     ; entry length
        sta     BASE1
        bcc     :+
        inc     BASE1+1
:       dec     TEMP2
        bne     @entry
        bra     @block
@novol: lda     #$45                    ; volume not found
@err:   sta     fm_err
@done:  jmp     close_all

prefix_call:
        ldx     #<p_prefix
        ldy     #>p_prefix
        jmp     mli

; cat_entry: the directory entry at BASE1: a BIN file named *.PCS is added
cat_entry:
        lda     (BASE1)
        and     #$F0
        beq     @no                     ; unused
        cmp     #$40
        bcs     @no                     ; a directory or a header
        ldy     #16
        lda     (BASE1),y
        cmp     #$06                    ; BIN
        bne     @no
        lda     (BASE1)
        and     #$0F
        sta     TEMP
        cmp     #5
        bcc     @no
        sbc     #3                      ; carry set: the '.' of ".PCS"
        tay
        ldx     #0
:       lda     (BASE1),y
        cmp     s_pcs,x
        bne     @no
        iny
        inx
        cpx     #4
        bne     :-
        ldx     fm_count
        cpx     #CAT_MAX
        bcs     @no
        jsr     sel_name
        ldy     TEMP
:       lda     (BASE1),y
        sta     (BASE2),y
        dey
        bne     :-
        lda     TEMP
        sta     (BASE2)
        inc     fm_count
@no:    rts

; ---------------------------------------------------------------------------
; load_file: catalog entry X into the database and the overlay layer. The
; header, the count, the sizes and the file's length are checked before
; anything is written, so the table is kept when the file is not one; a
; bad overlay part leaves the table loaded and the overlay cleared. C set
; with the error in A.
; ---------------------------------------------------------------------------
load_file:
        jsr     sel_name
        ldy     #15
:       lda     (BASE2),y
        sta     fm_path,y
        dey
        bpl     :-
        jsr     open_path
        jcs     @err
        lda     #4
        ldx     #<fm_stage
        ldy     #>fm_stage
        jsr     read_to
        jcs     @err
        ldx     #3
:       lda     fm_stage,x
        cmp     s_magic,x
        jne     @format
        dex
        bpl     :-
        lda     #29                     ; LOGIC, WSET, count
        ldx     #<fm_stage
        ldy     #>fm_stage
        jsr     read_to
        jcs     @err
        lda     fm_stage+28
        jeq     @format
        jmi     @format
        ldx     #<(fm_stage+29)         ; the sizes
        ldy     #>(fm_stage+29)
        jsr     read_to
        jcs     @err
        lda     #<fm_stage
        sta     BASE1
        lda     #>fm_stage
        sta     BASE1+1
        jsr     db_length
        lda     fm_sum+1
        cmp     #>REC_MAX
        jcs     @format
        ; the file holds the records, "OVL1" and the map at least
        lda     #MLI_GETEOF
        jsr     mark_call
        jcs     @err
        lda     p_mark+4
        bne     @long
        lda     fm_dblen
        clc
        adc     #80
        sta     TEMP
        lda     fm_dblen+1
        adc     #0
        sta     TEMP+1
        lda     p_mark+2                ; eof < needed: too short
        cmp     TEMP
        lda     p_mark+3
        sbc     TEMP+1
        bcc     @format
@long:  ; commit: LOGIC, WSET, count, sizes, then the records
        lda     fm_stage+28
        clc
        adc     #29
        sta     TEMP
        ldy     #0
:       lda     fm_stage,y
        sta     PBBASE,y
        iny
        cpy     TEMP
        bne     :-
        lda     PBDATA
        clc
        adc     #<(PBDATA+1)
        sta     BASE1
        lda     #>(PBDATA+1)
        adc     #0
        sta     BASE1+1
        lda     fm_sum
        ldx     fm_sum+1
        jsr     fm_read
        bcs     @err2
        lda     #4                      ; "OVL1"
        ldx     #<fm_tile
        ldy     #>fm_tile
        jsr     read_to
        bcs     @err2
        ldx     #3
:       lda     fm_tile,x
        cmp     s_ovl,x
        bne     @format2
        dex
        bpl     :-
        lda     #72
        ldx     #<ov_tiles
        ldy     #>ov_tiles
        jsr     read_to
        bcs     @err2
        jsr     ov_decode
        bcs     @err2
        jsr     close_all
        bcs     @err2
        jsr     table_refresh
        clc
        rts
@format:
        lda     #ERR_FORMAT
@err:   sta     fm_err
        jsr     close_all
        lda     fm_err
        sec
        rts
@format2:
        lda     #ERR_FORMAT
@err2:  sta     fm_err                  ; the table is in: no overlay
        ldx     #71
:       stz     ov_tiles,x
        dex
        bpl     :-
        jsr     table_refresh
        jsr     close_all
        lda     fm_err
        sec
        rts

; table_refresh: the loaded database: L-records resolved, ov_enabled from
; the tile map, the span database rebuilt and the table redrawn
table_refresh:
        jsr     table_normalise
        ldx     #71
        lda     #0
:       ora     ov_tiles,x
        dex
        bpl     :-
        cmp     #0
        beq     :+
        lda     #1
:       sta     ov_enabled
        stz     SCANMODE
        jmp     PORT_DRAWDISPLAY

; db_length: for the database image at BASE1 (count at +28, sizes after):
; fm_sum = the records' length, fm_dblen = 29 + count + fm_sum
db_length:
        stz     fm_sum
        stz     fm_sum+1
        ldy     #28
        lda     (BASE1),y
        sta     TEMP
        beq     @zero
        ldy     #29
@s:     lda     (BASE1),y
        clc
        adc     fm_sum
        sta     fm_sum
        bcc     :+
        inc     fm_sum+1
:       iny
        dec     TEMP
        bne     @s
@zero:  ldy     #28
        lda     (BASE1),y
        clc
        adc     #29
        clc
        adc     fm_sum
        sta     fm_dblen
        lda     fm_sum+1
        adc     #0
        sta     fm_dblen+1
        rts

; ---------------------------------------------------------------------------
; save_file: the database and the overlay as fm_name + ".PCS" (created if
; missing, truncated otherwise). C set with the error in A.
; ---------------------------------------------------------------------------
save_file:
        ldx     #NAME_MAX
:       lda     fm_name,x
        sta     fm_path,x
        dex
        bpl     :-
        ldx     fm_name
        inx
        ldy     #0
:       lda     s_pcs,y
        sta     fm_path,x
        inx
        iny
        cpy     #4
        bne     :-
        lda     fm_name
        clc
        adc     #4
        sta     fm_path
        lda     #MLI_CREATE             ; BIN, aux 0, seedling (parms_tmpl)
        ldx     #<p_create
        ldy     #>p_create
        jsr     mli
        bcc     :+
        cmp     #$47                    ; duplicate: overwrite it
        bne     @err
:       jsr     open_path
        bcs     @err
        lda     #4
        ldx     #<s_magic
        ldy     #>s_magic
        jsr     write_from
        bcs     @err
        lda     #<PBBASE
        sta     BASE1
        lda     #>PBBASE
        sta     BASE1+1
        jsr     db_length
        jsr     table_denorm            ; L-records as kind, frame (walks BASE1)
        lda     #<PBBASE
        sta     BASE1
        lda     #>PBBASE
        sta     BASE1+1
        lda     fm_dblen
        ldx     fm_dblen+1
        jsr     fm_write
        sta     fm_err
        php
        jsr     table_normalise         ; and back
        plp
        lda     fm_err
        bcs     @err
        lda     #4
        ldx     #<s_ovl
        ldy     #>s_ovl
        jsr     write_from
        bcs     @err
        lda     #72
        ldx     #<ov_tiles
        ldy     #>ov_tiles
        jsr     write_from
        bcs     @err
        jsr     ov_encode
        bcs     @err
        lda     #MLI_GETMARK            ; the end of file: here
        jsr     mark_call
        bcs     @err
        lda     #MLI_SETEOF
        jsr     mark_call
        bcs     @err
        jsr     close_all
        bcs     @err
        clc
        rts
@err:   sta     fm_err
        jsr     close_all
        lda     fm_err
        sec
        rts

; table_denorm: every L-record's sprite pointer becomes (kind, frame): the
; kind whose frames hold the sprite's directory index (the sprite ranges
; of the kinds are disjoint). The inverse of table_normalise (main.s).
table_denorm:
        lda     #<(PBDATA+1)
        sta     BASE1
        lda     #>(PBDATA+1)
        sta     BASE1+1
        lda     PBDATA
        beq     @done
        sta     XTEMP                   ; objects left
        clc
        adc     BASE1
        sta     BASE1
        bcc     :+
        inc     BASE1+1
:       stz     YTEMP                   ; object index
@obj:   lda     (BASE1)
        cmp     #OBJ_LIBOBJ
        bne     @next
        ldy     #2
        lda     (BASE1),y
        asl     a
        clc
        adc     #3
        adc     BASE1
        sta     BASE2
        lda     BASE1+1
        adc     #0
        sta     BASE2+1
        lda     (BASE2)                 ; id = (ptr - spr_dir) / 4
        sec
        sbc     #<spr_dir
        sta     TEMP
        ldy     #1
        lda     (BASE2),y
        sbc     #>spr_dir
        lsr     a
        ror     TEMP
        lsr     a
        ror     TEMP
        ldx     #KIND_COUNT-1
@k:     lda     kind_frames,x
        beq     @nk
        lda     TEMP
        sec
        sbc     kind_spr0,x
        bcc     @nk
        cmp     kind_frames,x
        bcc     @found
@nk:    dex
        bpl     @k
        lda     #0                      ; unknown: kind 0, frame 0
@found: ldy     #1
        sta     (BASE2),y               ; frame
        txa
        bpl     :+
        lda     #0
:       sta     (BASE2)                 ; kind
@next:  ldy     YTEMP
        lda     PBDATA+1,y
        clc
        adc     BASE1
        sta     BASE1
        bcc     :+
        inc     BASE1+1
:       inc     YTEMP
        dec     XTEMP
        bne     @obj
@done:  rts

; ---------------------------------------------------------------------------
; The overlay layer (RamWorks bank 1, $2000 + 160*y, 77 bytes per row).
; Tile (row, column) of 8x8 pixels: 8 rows of 4 bytes at $2000 + 1280*row
; + 4*column; ov_tiles bit column%8 of byte 3*row + column/8 says it holds
; edits (render.s reads the same map).
; ---------------------------------------------------------------------------
; first_tile: the tile cursor before the first tile, then the first set
; one; tile_next: the next set one. fm_have bit 7: there is one.
first_tile:
        lda     #$FF
        sta     fm_tcol
        stz     fm_trow
tile_next:
@n:     inc     fm_tcol
        lda     fm_tcol
        cmp     #20
        bcc     :+
        stz     fm_tcol
        inc     fm_trow
        lda     fm_trow
        cmp     #24
        bcs     @none
:       lda     fm_trow
        asl     a
        adc     fm_trow                 ; * 3
        sta     TEMP
        lda     fm_tcol
        lsr     a
        lsr     a
        lsr     a
        clc
        adc     TEMP
        tax
        lda     fm_tcol
        and     #7
        tay
        lda     ov_tiles,x
        and     bitmask,y
        beq     @n
        lda     #$80
        bne     :+
@none:  lda     #0
:       sta     fm_have
        rts

; tile_setup: af_* for the current tile, the bank-1 address in TEMP
tile_setup:
        lda     fm_tcol
        asl     a
        asl     a
        sta     TEMP
        lda     fm_trow
        asl     a
        asl     a
        adc     fm_trow                 ; * 5 pages
        clc
        adc     #>SHR_BASE
        sta     TEMP+1
        lda     #1
        sta     af_bank
        lda     #4
        sta     af_len
        lda     #8
        sta     af_rows
        stz     af_sstride+1
        stz     af_dstride+1
        rts

; store_tile: fm_tile -> the current tile
store_tile:
        jsr     tile_setup
        lda     TEMP
        sta     af_dst
        lda     TEMP+1
        sta     af_dst+1
        lda     #<fm_tile
        sta     af_src
        lda     #>fm_tile
        sta     af_src+1
        lda     #4
        sta     af_sstride
        lda     #SHR_ROW
        sta     af_dstride
        jmp     aux_store_rows

; fetch_tile: the current tile -> fm_tile
fetch_tile:
        jsr     tile_setup
        lda     TEMP
        sta     af_src
        lda     TEMP+1
        sta     af_src+1
        lda     #<fm_tile
        sta     af_dst
        lda     #>fm_tile
        sta     af_dst+1
        lda     #SHR_ROW
        sta     af_sstride
        lda     #4
        sta     af_dstride
        jmp     aux_fetch_rows

; ov_decode: the RLE stream from the open file into the set tiles; the
; layer is cleared first. C set with the error in A.
ov_decode:
        ldx     #79
        lda     #0
:       sta     fm_stage,x
        dex
        bpl     :-
        lda     #1
        sta     af_bank
        lda     #<fm_stage
        sta     af_src
        lda     #>fm_stage
        sta     af_src+1
        stz     af_dst
        lda     #>SHR_BASE
        sta     af_dst+1
        lda     #80
        sta     af_len
        lda     #TABLE_H
        sta     af_rows
        stz     af_sstride
        stz     af_sstride+1
        lda     #SHR_ROW
        sta     af_dstride
        stz     af_dstride+1
        jsr     aux_store_rows
        stz     fm_mode
        stz     fm_tpos
        jsr     first_tile
@chunk: lda     #<fm_stage
        sta     BASE1
        lda     #>fm_stage
        sta     BASE1+1
        lda     #255
        ldx     #0
        jsr     rw_setup
        lda     #MLI_READ
        jsr     rw_call
        bcs     @done
        lda     p_rw+6
        beq     @format
        ldy     #0
@byte:  lda     fm_stage,y
        phy                             ; (a full tile's store clobbers Y)
        jsr     rle_byte
        ply
        bcs     @stop
        iny
        cpy     p_rw+6
        bne     @byte
        bra     @chunk
@stop:  cmp     #0
        bne     @fail                   ; an error
        lda     fm_tpos                 ; the end: nothing half done
        bne     @format
        bit     fm_have
        bmi     @format
        clc
        rts
@format:
        lda     #ERR_FORMAT
@fail:  sec
@done:  rts

; rle_byte: one byte of the stream. C set at the end (A = 0) or on an
; error (A = the code).
rle_byte:
        ldx     fm_mode
        bne     @data
        cmp     #0
        beq     @end
        bmi     @rep
        sta     fm_left
        inc     fm_mode                 ; 1: literal bytes follow
        clc
        rts
@rep:   and     #$7F
        sta     fm_left
        ldx     #2                      ; 2: the value follows
        stx     fm_mode
        clc
        rts
@data:  dex
        bne     @repeat
        jsr     emit
        bcs     @rts
        dec     fm_left
        bne     @ok
        stz     fm_mode
@ok:    clc
        rts
@repeat:
        pha
        jsr     emit
        bcs     @rerr
        pla
        dec     fm_left
        bne     @repeat
        stz     fm_mode
        clc
        rts
@rerr:  plx                             ; the value; A = the error
        rts
@end:   sec
@rts:   rts

; emit: A into the tile; a full tile is stored and the next one begins
emit:   bit     fm_have
        bpl     @over
        ldx     fm_tpos
        sta     fm_tile,x
        inx
        stx     fm_tpos
        cpx     #32
        bcc     @ok
        jsr     store_tile
        stz     fm_tpos
        jsr     tile_next
@ok:    clc
        rts
@over:  lda     #ERR_FORMAT             ; more tiles than the map has
        sec
        rts

; ov_encode: the set tiles as the RLE stream, written through fm_stage: a
; tile of one value is $80|32 and the value, any other 32 literals
ov_encode:
        stz     fm_pos
        jsr     first_tile
@tile:  bit     fm_have
        bpl     @end
        jsr     fetch_tile
        lda     fm_tile
        ldx     #31
:       cmp     fm_tile,x
        bne     @lit
        dex
        bne     :-
        lda     #$80|32
        jsr     out
        lda     fm_tile
        jsr     out
        bra     @room
@lit:   lda     #32
        jsr     out
        ldx     #0
:       lda     fm_tile,x
        jsr     out
        inx
        cpx     #32
        bne     :-
@room:  lda     fm_pos
        cmp     #200                    ; room for a tile's 33 bytes
        bcc     :+
        jsr     flush
        bcs     @fail
:       jsr     tile_next
        bra     @tile
@end:   lda     #0
        jsr     out
        bra     flush
@fail:  rts

; flush: fm_stage[0..fm_pos) to the file
flush:  lda     fm_pos
        ldx     #<fm_stage
        ldy     #>fm_stage
        jsr     write_from
        stz     fm_pos
        rts

; out: A appended to fm_stage. Keeps X.
out:    ldy     fm_pos
        sta     fm_stage,y
        inc     fm_pos
        rts
