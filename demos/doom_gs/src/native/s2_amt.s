; s2_amt.s: part s2amap's test image glue (docs/m11-parts/s2amap.md). Not
; part of the game: the image s2at (AMAPW's room) links it with s2_am.s,
; s2_amline.s and s2_pub.s under the test driver s2_drv.
;
; tools/native/s2amap.py stages each case in RamWorks and lists them in a
; directory (bank T_DIR, $0200: the count, then each case's bank and
; address, 3 bytes). A case:
;
;   +0      the number of copies (below), the number of events
;   +2      the call: 0 am_frame, 1 am_responder, 2 am_tick; its A, X, Y
;   +6      the events before it: type, key low, key high (3 bytes each)
;   +$40    the copies, 8 bytes each: the place's kind (0 main, 1 a
;           RamWorks bank, 2 the card), its bank, its address (2), the
;           length (2), the data's offset in the case (2)
;
;   amt_case    A = k: the math's mt_init (the boot's), case k's copies
;               into place (outside the cost phase),
;               its events (am_responder, the cost phase 30 around each),
;               then its call (the cost phase 30 around it)
;   amt_calls   A = n: cases 0 .. n - 1 the same, each one's results to
;               the results bank T_RES at $0200 + 128 k: the state block's
;               first page's fields (ST_END - AMST bytes), player.message
;               (5), the call's A, the frame block's AUTOMAP, S2_MAIL
;
; Zero page: none but the far layer's FA_* (its variables are in S2DATA:
; mt_init and the image use the zero page).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2amap.inc"
        .include "s2_am.inc"

        .export amt_case, amt_calls
        .import am_frame, am_responder, am_tick, far_get, far_put, mt_init

T_DIR    = 76                   ; the directory's bank
T_RES    = 75                   ; the results' bank
BOUNCE   = $AB00                ; a page of W (AMAPW's AMSEGBUF)
RES_SIZE = 128
NSTATE   = ST_END - AMST


        .assert NSTATE + 8 <= RES_SIZE, error, "a result"

        .segment "S2CODE"

amt_calls:
        sta amt_n
        stz amt_k
@next:  lda amt_k
        cmp amt_n
        beq @done
        jsr amt_case
        jsr result
        inc amt_k
        bra @next
@done:  rts

; result: case amt_k's results to T_RES
result:
        ldx #0                  ; FA_DST = $0200 + 128 k
        lda amt_k
        lsr a
        bcc :+
        ldx #$80
:       stx FA_DST
        clc
        adc #2
        sta FA_DST+1
        ldx #NSTATE - 1         ; the record in BOUNCE
:       lda AMST,x
        sta BOUNCE,x
        dex
        cpx #$FF
        bne :-
        ldx #4
:       lda AM_PLMSG,x
        sta BOUNCE+NSTATE,x
        dex
        bpl :-
        lda amt_ret
        sta BOUNCE+NSTATE+5
        lda AM_FAUTO
        sta BOUNCE+NSTATE+6
        lda S2_MAIL
        sta BOUNCE+NSTATE+7
        lda #<BOUNCE
        sta FA_SRC
        lda #>BOUNCE
        sta FA_SRC+1
        lda #T_RES
        sta FA_BANK
        lda #RES_SIZE
        sta FA_N
        jmp far_put

amt_case:
        stz PHASE
        sta C_K
        jsr mt_init             ; (the boot's: the squares' pointers)
        lda C_K
        stz C_N+1               ; the directory's entry: $0201 + 3 k
        asl a
        rol C_N+1
        clc
        adc C_K
        sta C_N
        lda C_N+1
        adc #0
        sta C_N+1
        clc
        lda C_N
        adc #<$0201
        sta FA_SRC
        lda C_N+1
        adc #>$0201
        sta FA_SRC+1
        lda #T_DIR
        sta FA_BANK
        lda #3
        sta FA_N
        lda #<BOUNCE
        sta FA_DST
        lda #>BOUNCE
        sta FA_DST+1
        jsr far_get
        lda BOUNCE
        sta C_BANK
        lda BOUNCE+1
        sta C_BASE
        lda BOUNCE+2
        sta C_BASE+1
        jsr head                ; the case's first page into BOUNCE
        lda BOUNCE              ; the copies
        sta amt_nc
        stz amt_c
@copy:  lda amt_c
        cmp amt_nc
        beq @events
        jsr head
        lda amt_c               ; $40 + 8 c
        asl a
        asl a
        asl a
        clc
        adc #$40
        tax
        lda BOUNCE,x
        sta amt_kind
        lda BOUNCE+1,x
        sta amt_bank
        lda BOUNCE+2,x
        sta amt_dst
        lda BOUNCE+3,x
        sta amt_dst+1
        lda BOUNCE+4,x
        sta amt_len
        lda BOUNCE+5,x
        sta amt_len+1
        clc
        lda BOUNCE+6,x
        adc C_BASE
        sta amt_src
        lda BOUNCE+7,x
        adc C_BASE+1
        sta amt_src+1
        jsr copy
        inc amt_c
        bra @copy
@events:
        jsr head
        stz C_EV
@ev:    lda C_EV
        cmp BOUNCE+1
        beq @call
        asl a                   ; 6 + 3 e
        clc
        adc C_EV
        tax
        lda BOUNCE+6,x
        pha
        ldy BOUNCE+8,x
        lda BOUNCE+7,x
        tax
        pla
        jsr phase_on
        jsr am_responder
        stz PHASE
        jsr head
        inc C_EV
        bra @ev
@call:  lda BOUNCE+2
        sta amt_kind
        ldy BOUNCE+5
        ldx BOUNCE+4
        lda BOUNCE+3
        jsr phase_on
        pha
        lda amt_kind
        beq @frame
        cmp #1
        beq @resp
        pla
        jsr am_tick
        lda #0
        bra @ret
@frame: pla
        jsr am_frame
        lda #0
        bra @ret
@resp:  pla
        jsr am_responder
@ret:   stz PHASE
        sta amt_ret
        rts

phase_on:
        pha
        lda #PHV_2D
        sta PHASE
        pla
        rts

; head: the case's first page into BOUNCE
head:   lda C_BASE
        sta FA_SRC
        lda C_BASE+1
        sta FA_SRC+1
        lda C_BANK
        sta FA_BANK
        lda #<BOUNCE
        sta FA_DST
        lda #>BOUNCE
        sta FA_DST+1
        stz FA_N
        jmp far_get

; copy: amt_len bytes from the case's bank at amt_src to the place
; (amt_kind, amt_bank, amt_dst), a page at a time through BOUNCE (a main
; or card place directly)
copy:
@more:  lda amt_len
        ora amt_len+1
        bne :+
        rts
:       lda amt_len+1           ; this piece: 256, or what is left
        bne :+
        lda amt_len
        bra :++
:       lda #0
:       sta FA_N
        sta amt_piece
        lda amt_src
        sta FA_SRC
        lda amt_src+1
        sta FA_SRC+1
        lda C_BANK
        sta FA_BANK
        lda amt_kind
        cmp #1
        beq @aux
        lda amt_dst             ; main or the card: directly
        sta FA_DST
        lda amt_dst+1
        sta FA_DST+1
        jsr far_get
        bra @adv
@aux:   lda #<BOUNCE
        sta FA_DST
        lda #>BOUNCE
        sta FA_DST+1
        jsr far_get
        lda #<BOUNCE
        sta FA_SRC
        lda #>BOUNCE
        sta FA_SRC+1
        lda amt_dst
        sta FA_DST
        lda amt_dst+1
        sta FA_DST+1
        lda amt_bank
        sta FA_BANK
        lda amt_piece
        sta FA_N
        jsr far_put
@adv:   lda amt_piece           ; 0: 256
        bne :+
        inc amt_src+1
        inc amt_dst+1
        dec amt_len+1
        jmp @more
:       clc
        adc amt_src
        sta amt_src
        bcc :+
        inc amt_src+1
:       clc
        lda amt_piece
        adc amt_dst
        sta amt_dst
        bcc :+
        inc amt_dst+1
:       sec
        lda amt_len
        sbc amt_piece
        sta amt_len
        bcs :+
        dec amt_len+1
:
        jmp @more

        .segment "S2DATA"
amt_n:    .res 1
amt_k:    .res 1
amt_nc:   .res 1
amt_c:    .res 1
amt_kind: .res 1
amt_bank: .res 1
amt_dst:  .res 2
amt_src:  .res 2
amt_len:  .res 2
amt_piece: .res 1
amt_ret:  .res 1
C_BANK:   .res 1                ; the case's bank and address
C_BASE:   .res 2
C_K:      .res 1
C_N:      .res 2
C_EV:     .res 1
