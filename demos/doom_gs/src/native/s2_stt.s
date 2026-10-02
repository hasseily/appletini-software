; s2_stt.s: part s2stbar's test image glue for the drawer (docs/m11-parts/
; s2stbar.md). Not part of the game. Linked in P2DW's room with s2_st.s,
; part s2draw's s2_draw.s and s2_pub.s, and part s2pal's s2_pal.s for
; s2_begin (the SCBs and palettes are part s2pal's region).
;
; tools/native/s2stbar.py stages up to 32 frames in RamWorks:
;
;   bank T_CASE     frame k at $0200 + k * $400: +$000 P2DW's own state
;                   block (256), +$100 the card's S2T block (64), +$140
;                   which of its bytes to set (64: 0 keep), +$180 the
;                   player (G_PLAYER, 148), +$220 PALST's SCBs (200),
;                   +$2F0 G_MENUACTIVE (2), +$2F2 the flags (bit 0: the 2D
;                   state injected), +$2F3 the blobs (STCACHE, STBUF, the
;                   screen's rows 168-199; $FF none)
;   banks T_BLOB+   blob j (5,120 B) at bank T_BLOB + j / 9, $0200 +
;                   (j % 9) * $1400
;
;   stx_case    A = k: the frame's state into its places (the own block
;               into S2STATE when injected; the card's bytes it sets; the
;               player; the menu; PALST's SCBs at W $BC00; STCACHE, STBUF
;               and aux 0's rows 168-199 from their blobs), P2DW's own
;               block fetched from S2STATE as the frame does, st_drawer in
;               the cost phase 30 alone, the block written back, st_nibs
;               into stx_nibs. stx_marker gets k first (the write log's
;               cut).
;
; Zero page $80-$87.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2stbar.inc"

        .export stx_case, stx_marker, stx_nibs
        .export s2_marks, s2_fbuf, s2_begun, s2_palst
        .exportzp s2_fbpages
        .import st_drawer, st_nibs, far_get, far_put

s2_marks   = P2DW_MARKS
s2_fbuf    = P2DW_FBUF
s2_fbpages = P2DW_FBPAGES
s2_begun   = PALST_W + PS_BEGUN
s2_palst   = PALST_W                    ; (s2_pal's PALST)
BAND       = P2DW_RT0
OWN        = PALST_W + PALST_SIZE       ; P2DW's own block, W $BF00
ST_ROW0    = SHR + 168 * ROW_BYTES      ; aux 0's row 168

T_CASE     = 50
T_BLOB     = 52
BLOBS_A_BANK = 9

R_OWN      = $000
R_CARD     = $100
R_MASK     = $140
R_PLAYER   = $180
R_SCB      = $220
R_MENU     = $2F0
R_FLAGS    = $2F2
R_BLOBS    = $2F3

T_K        = $80
T_N        = $81
T_P        = $82                ; (2)

        .segment "S2CODE"

stx_case:
        stz PHASE
        sta stx_marker
        sta T_K
        asl a                   ; the record: $0200 + k * $400
        asl a
        clc
        adc #2
        tax
        lda #T_CASE
        ldy #4
        jsr fetch               ; into the band
        ldx #2                  ; its small fields
:       lda BAND + R_BLOBS,x
        sta blobs,x
        dex
        bpl :-
        lda BAND + R_FLAGS
        sta flags
        lda BAND + R_MENU
        sta G_MENUACTIVE
        lda BAND + R_MENU+1
        sta G_MENUACTIVE+1
        ldx #0                  ; the card's bytes
:       lda BAND + R_MASK,x
        beq :+
        lda BAND + R_CARD,x
        sta S2T_BASE,x
:       inx
        cpx #S2T_SIZE
        bne :--
        ldx #0                  ; the player, PALST's SCBs
:       lda BAND + R_PLAYER,x
        sta G_PLAYER,x
        inx
        cpx #148
        bne :-
        ldx #0
:       lda BAND + R_SCB,x
        sta PALST_W + PS_SCB,x
        inx
        cpx #200
        bne :-
        lda flags
        and #1
        beq @own
        lda #<BAND              ; injected: the own block into S2STATE
        sta FA_SRC
        lda #>BAND
        sta FA_SRC+1
        lda #<SS_P2DW
        sta FA_DST
        lda #>SS_P2DW
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jsr far_put
        lda blobs               ; STCACHE, STBUF
        ldx #>SS_STCACHE
        ldy #<SS_STCACHE
        jsr blobput
        lda blobs+1
        ldx #>SS_STBUF
        ldy #<SS_STBUF
        jsr blobput
        lda blobs+2             ; aux 0's rows 168-199
        cmp #$FF
        beq @own
        jsr blobget
        lda #<BAND
        sta T_P
        lda #>BAND
        sta T_P+1
        lda #<ST_ROW0
        sta FA_DST
        lda #>ST_ROW0
        sta FA_DST+1
        ldx #20
        ldy #0
        sta RAMWRTON
:       lda (T_P),y
        sta (FA_DST),y
        iny
        bne :-
        inc T_P+1
        inc FA_DST+1
        dex
        bne :-
        sta RAMWRTOFF
@own:   lda #<SS_P2DW           ; the frame's fetch of the own block
        sta FA_SRC
        lda #>SS_P2DW
        sta FA_SRC+1
        lda #<OWN
        sta FA_DST
        lda #>OWN
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jsr far_get
        lda #PHV_2D
        sta PHASE
        jsr st_drawer
        stz PHASE
        lda st_nibs
        sta stx_nibs
        lda #<OWN               ; the block back
        sta FA_SRC
        lda #>OWN
        sta FA_SRC+1
        lda #<SS_P2DW
        sta FA_DST
        lda #>SS_P2DW
        sta FA_DST+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        jmp far_put

; fetch: Y pages of bank A from page X into the band
fetch:  sta FA_BANK
        stx FA_SRC+1
        stz FA_SRC
        lda #<BAND
        sta FA_DST
        lda #>BAND
        sta FA_DST+1
        stz FA_N
        sty T_N
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dec T_N
        bne :-
        rts

; blobget: blob A into the band (20 pages)
blobget:
        ldx #0                  ; bank T_BLOB + A / 9, page 2 + (A % 9) * 20
:       cmp #BLOBS_A_BANK
        bcc :+
        sbc #BLOBS_A_BANK
        inx
        bra :-
:       sta T_N
        txa
        clc
        adc #T_BLOB
        pha
        lda T_N
        asl a
        asl a
        adc T_N
        asl a
        asl a
        adc #2
        tax
        pla
        ldy #20
        jmp fetch

; blobput: blob A (unless $FF) into S2STATE at Y (low), X (high)
blobput:
        cmp #$FF
        beq @none
        phx
        phy
        jsr blobget
        pla
        sta FA_DST
        pla
        sta FA_DST+1
        lda #<BAND
        sta FA_SRC
        lda #>BAND
        sta FA_SRC+1
        lda #S2STATE
        sta FA_BANK
        stz FA_N
        ldx #20
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne :-
@none:  rts

        .segment "S2DATA"
stx_marker: .res 1
stx_nibs:   .res 1
flags:      .res 1
blobs:      .res 3
