; s2_hut.s: part s2hud's test glue (docs/m11-parts/s2hud.md), linked in
; P2DW's room with its runtime places (the band at $8300, the marks page
; at $9700, the nibble slots at $9800, the fetch buffer at $B800, PALST at
; $BC00, P2DW's own state at $BF00). Not part of the game.
; tools/native/s2hud.py writes the cases into RamWorks banks; a run's
; write log (a2vm) is its output for the frames: every byte published to
; the screen and every write of the state, in order.
;
;   hut_tics    A = the first input bank, X = the first output bank: the
;               count at the first bank's $0200 (a word), then from $0210 a
;               record of 16 bytes a call (T_*), 2,975 a bank, the next
;               bank after: HU_Ticker (hu_ticker, then the STANDIN of
;               milestone 10's hu_tick: player.message and G_MSGKEEP
;               cleared, request R5's order) or HU_Start (hu_start, then
;               the hook's clear of G_MSGKEEP); the card's HUD state is
;               carried from call to call, or set from the record (its
;               mode); after each call the state (O_*) at $0200 + 16 *
;               the call in the output banks (2,992 a bank)
;   hut_frames  A = the first input bank, Y = the bank of the nibble table
;               sets: the count at $0200, then from $0300 a frame every
;               $140 bytes (150 a bank, the next bank after): its
;               parameters (F_*: the flags, the card's HU_ON, HU_MSGID,
;               HU_TITLEMAP, AUTOMAP, PS_TXTINV, the set of nibble tables
;               (palettes 0, 10, 11 at $0200 + set * $C00 in bank Y,
;               copied into S2PAL's S2NIB when the set changes), the rows'
;               palettes, the mode: bit 0, P2DW's state block from the
;               record's F_STATE), then hu_drawer (the cost phase 30
;               around it alone); hut_k counts the frames (its writes
;               delimit them in the write log)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2hud.inc"

        .export hut_tics, hut_frames, hut_k
        .export s2_marks, s2_fbuf, s2_begun, s2_palst
        .exportzp s2_fbpages
        .import hu_ticker, hu_start, hu_drawer, far_get, far_put

s2_marks   = P2DW_MARKS
s2_fbuf    = P2DW_FBUF
s2_fbpages = P2DW_FBPAGES
s2_palst   = PALST_W
TMP        = P2DW_RT2           ; a page: slot 0 (the HUD fetches from 7 down)

T_KIND  = 0                     ; 0 HU_Ticker, 1 HU_Start
T_MODE  = 1                     ; bit 0: the card's state from the record;
                                ;   bit 1: HU_NEW alone from it
T_TAG   = 2                     ; player.message: tag, id (2)
T_SHOW  = 5                     ; G_SHOWMSG (2)
T_KEEP  = 7                     ; G_MSGKEEP (2)
T_MAP   = 5                     ; HU_Start: gamemap (a word)
T_COUNT = 9                     ; the card's state: HU_COUNTER (2), HU_ON,
                                ;   HU_NEW, HU_MSGID (2)
                                ; the output: HU_ON, HU_NEW, HU_COUNTER (2),
                                ;   HU_MSGID (2), HU_TITLEMAP, the tag,
                                ;   G_MSGKEEP (2)
F_FLAGS = 0
F_ON    = 1
F_MSGID = 2
F_MAP   = 4
F_AUTOMAP = 5
F_TXTINV = 6
F_SET   = 7
F_MODE  = 8
F_SCB   = 16                    ; the palettes of rows 0-9, then 160-167
F_STATE = $40                   ; (mode bit 0) P2DW's state block
P_STATE = P2DW_STATE + $0300    ; P2DW's own block ($BF00)
FRAME   = $0140
FRAMES_A_BANK = 150
NROWS   = 18
TICS_A_BANK = 2975

        .segment "S2DATA"
s2_begun: .res 1
hut_k:  .res 2                  ; the call or the frame being made
hut_n:  .res 2
hut_b:  .res 2                  ; the calls or frames left in this bank
hut_in: .res 2                  ; the record's address in the input bank
hut_out: .res 2
hut_ib: .res 1
hut_ob: .res 1
hut_nb: .res 1
hut_set: .res 1                 ; the nibble tables' set in S2PAL
hut_p:  .res 1
hut_pg: .res 1
hut_q:  .res 1
rec:    .res 64

        .segment "S2RODATA"
; the 18 rows' screen rows (0-9, 160-167) and the sets' palettes
rows:   .byte 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
        .byte 160, 161, 162, 163, 164, 165, 166, 167
pals:   .byte 0, 10, 11

        .segment "S2CODE"

; get: FA_N bytes of bank hut_ib at hut_in to W at A:X
get:    sta FA_DST+1
        stx FA_DST
        lda hut_ib
        sta FA_BANK
        lda hut_in
        sta FA_SRC
        lda hut_in+1
        sta FA_SRC+1
        jmp far_get

; count: hut_n from the input bank's $0200; hut_k = 0
count:  stz hut_in
        lda #2
        sta hut_in+1
        lda #2
        sta FA_N
        lda #>hut_n
        ldx #<hut_n
        jsr get
        stz hut_k
        stz hut_k+1
        rts

; next: hut_k + 1; C = 1 when it is hut_n
next:   inc hut_k
        bne :+
        inc hut_k+1
:
; done: C = 1 when hut_k = hut_n
done:   lda hut_k
        cmp hut_n
        bne :+
        lda hut_k+1
        cmp hut_n+1
        bne :+
        sec
        rts
:       clc
        rts

; bankleft: hut_b - 1; Z = 1 when the bank is done
bankleft:
        lda hut_b
        bne :+
        dec hut_b+1
:       dec hut_b
        lda hut_b
        ora hut_b+1
        rts

; ---------------------------------------------------------------------------
hut_tics:
        stz PHASE
        sta hut_ib
        stx hut_ob
        jsr count
        lda #$10
        sta hut_in
        stz hut_out
        lda #2
        sta hut_out+1
        lda #<TICS_A_BANK
        sta hut_b
        lda #>TICS_A_BANK
        sta hut_b+1
        jsr done
        bcc @call
        rts
@call:  lda #16
        sta FA_N
        lda #>rec
        ldx #<rec
        jsr get
        lda rec+T_TAG           ; the game's inputs
        sta HU_PLMSG
        lda rec+T_TAG+1
        sta HU_PLMSG+1
        lda rec+T_TAG+2
        sta HU_PLMSG+2
        stz HU_PLMSG+3
        stz HU_PLMSG+4
        lda rec+T_SHOW
        sta HU_SHOWMSG
        lda rec+T_SHOW+1
        sta HU_SHOWMSG+1
        lda rec+T_KEEP
        sta HU_KEEP
        lda rec+T_KEEP+1
        sta HU_KEEP+1
        lda rec+T_MODE          ; the card's state
        lsr a
        bcc @new
        lda rec+T_COUNT
        sta HU_COUNTER
        lda rec+T_COUNT+1
        sta HU_COUNTER+1
        lda rec+T_COUNT+2
        sta HU_ON
        lda rec+T_COUNT+4
        sta HU_MSGID
        lda rec+T_COUNT+5
        sta HU_MSGID+1
@nw:    lda rec+T_COUNT+3
        sta HU_NEW
        bra @run
@new:   lsr a
        bcs @nw
@run:   lda rec+T_KIND
        bne @start
        lda #PHV_2D             ; HU_Ticker: request R5's order
        sta PHASE
        jsr hu_ticker
        stz PHASE
        jsr hutick
        bra @out
@start: lda rec+T_MAP           ; HU_Start
        sta HU_GAMEMAP
        lda rec+T_MAP+1
        sta HU_GAMEMAP+1
        lda #PHV_2D
        sta PHASE
        jsr hu_start
        stz PHASE
        stz HU_KEEP             ; (the hook's, request R5)
        stz HU_KEEP+1
@out:   lda HU_ON
        sta rec
        lda HU_NEW
        sta rec+1
        lda HU_COUNTER
        sta rec+2
        lda HU_COUNTER+1
        sta rec+3
        lda HU_MSGID
        sta rec+4
        lda HU_MSGID+1
        sta rec+5
        lda HU_TITLEMAP
        sta rec+6
        lda HU_PLMSG
        sta rec+7
        lda HU_KEEP
        sta rec+8
        lda HU_KEEP+1
        sta rec+9
        lda #<rec
        sta FA_SRC
        lda #>rec
        sta FA_SRC+1
        lda hut_out
        sta FA_DST
        lda hut_out+1
        sta FA_DST+1
        lda hut_ob
        sta FA_BANK
        lda #16
        sta FA_N
        jsr far_put
        clc
        lda hut_in
        adc #16
        sta hut_in
        bcc :+
        inc hut_in+1
:       clc
        lda hut_out
        adc #16
        sta hut_out
        bcc :+
        inc hut_out+1
:       jsr bankleft            ; the bank's last: the next banks
        bne :+
        inc hut_ib
        inc hut_ob
        lda #$10
        sta hut_in
        lda #2
        sta hut_in+1
        stz hut_out
        sta hut_out+1
        lda #<TICS_A_BANK
        sta hut_b
        lda #>TICS_A_BANK
        sta hut_b+1
:       jsr next
        bcs :+
        jmp @call
:       rts

; hutick: STANDIN of milestone 10's hu_tick (src/native/game/flow/
; gwi.s:638-653, request R5): when messages are on or kept and a message
; is set, player.message and G_MSGKEEP cleared
hutick:
        lda HU_SHOWMSG
        ora HU_SHOWMSG+1
        ora HU_KEEP
        ora HU_KEEP+1
        beq @rts
        lda HU_PLMSG
        beq @rts
        ldx #4
:       stz HU_PLMSG,x
        dex
        bpl :-
        stz HU_KEEP
        stz HU_KEEP+1
@rts:   rts

; ---------------------------------------------------------------------------
hut_frames:
        stz PHASE
        sta hut_ib
        sty hut_nb
        lda #$FF                ; no set copied yet
        sta hut_set
        jsr count
        stz hut_in
        lda #3
        sta hut_in+1
        lda #FRAMES_A_BANK
        sta hut_b
        stz hut_b+1
        jsr done
        bcc @frame
        rts
@frame: lda #F_STATE            ; the parameters
        sta FA_N
        lda #>rec
        ldx #<rec
        jsr get
        lda rec+F_MODE          ; P2DW's state block from the record
        lsr a
        bcc :+
        clc
        lda hut_in
        adc #F_STATE
        sta FA_SRC
        lda hut_in+1
        adc #0
        sta FA_SRC+1
        lda #<P_STATE
        sta FA_DST
        lda #>P_STATE
        sta FA_DST+1
        lda hut_ib
        sta FA_BANK
        stz FA_N
        jsr far_get
:       lda rec+F_ON
        sta HU_ON
        lda rec+F_MSGID
        sta HU_MSGID
        lda rec+F_MSGID+1
        sta HU_MSGID+1
        lda rec+F_MAP
        sta HU_TITLEMAP
        lda rec+F_AUTOMAP
        sta HU_AUTOMAP
        lda rec+F_TXTINV
        sta s2_palst+PS_TXTINV
        ldx #NROWS - 1          ; the rows' palettes
:       ldy rows,x
        lda rec+F_SCB,x
        sta s2_palst+PS_SCB,y
        dex
        bpl :-
        lda rec+F_SET
        cmp hut_set
        beq :+
        sta hut_set
        jsr nibset
:       lda #1                  ; (no s2_begin: s2pal's part)
        sta s2_begun
        lda #PHV_2D
        sta PHASE
        lda rec+F_FLAGS
        jsr hu_drawer
        stz PHASE
        clc                     ; the next frame
        lda hut_in
        adc #<FRAME
        sta hut_in
        lda hut_in+1
        adc #>FRAME
        sta hut_in+1
        jsr bankleft
        bne :+
        inc hut_ib
        stz hut_in
        lda #3
        sta hut_in+1
        lda #FRAMES_A_BANK
        sta hut_b
:       jsr next
        bcs :+
        jmp @frame
:       rts

; nibset: set hut_set's three tables (palettes 0, 10, 11, at $0200 + set
; * $C00 in bank hut_nb) to S2PAL's S2NIB, a page at a time through TMP
nibset:
        lda hut_set             ; the set's first page: 2 + set * 12
        asl a
        asl a
        sta hut_q
        asl a
        clc
        adc hut_q
        adc #2
        sta hut_q
        ldx #0
@pal:   stx hut_p
        ldy #0
@page:  sty hut_pg
        lda hut_p               ; the source: the set's page + pal * 4 +
        asl a                   ;   page
        asl a
        clc
        adc hut_q
        adc hut_pg
        sta FA_SRC+1
        stz FA_SRC
        stz FA_DST
        lda #>TMP
        sta FA_DST+1
        lda hut_nb
        sta FA_BANK
        stz FA_N
        jsr far_get
        stz FA_SRC
        lda #>TMP
        sta FA_SRC+1
        ldx hut_p
        lda pals,x
        asl a
        asl a
        clc
        adc hut_pg
        adc #>S2P_NIB
        sta FA_DST+1
        stz FA_DST
        lda #S2PAL
        sta FA_BANK
        stz FA_N
        jsr far_put
        ldy hut_pg
        iny
        cpy #4
        bcc @page
        ldx hut_p
        inx
        cpx #3
        bcc @pal
        rts
