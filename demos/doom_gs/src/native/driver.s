; The test driver of the native replay, for a2vm (tools/native/
; replay_check.py). Not part of the game: it stands in for the frame loop
; and the bucket pass that fills W with a batch of records.
;
; For each batch of the table at DRVDATA (tools/native/loader.py writes
; it), the driver copies the batch's records into W at RECBUF and its
; column tables to COLLO, both from the records bank, marks the cost
; phase (PHASE = 2: phase 1 of a2vm --cost-phase), calls nat_replay, and
; clears the phase. The call of batch K is at drv_callK and returns to
; drv_retK, so a2vm can snapshot the machine just before and just after
; each call. The run ends at drv_halt; a BRK (the replay's crash) or an
; unexpected interrupt ends at drv_crash. S starts at DRV_STACK ($EF), so
; $01F0-$01FF above it stands for a caller's frame, which the harness
; checks the replay leaves alone.
;
; The batch table: +0 the number of batches (1 to MAX_BATCHES), +1 the
; records bank, then per batch: the first column, the column after the
; last, the records' length (2 bytes) and address (2) in the records bank,
; the column tables' address (2).

        .setcpu "65C02"
        .include "layout.inc"

        .import nat_replay
        .export drv_start, drv_halt, drv_crash

DRV_N           = DRVDATA
DRV_BANK        = DRVDATA + 1
DRV_B           = DRVDATA + 2
COL_BYTES       = 2 * (COLUMNS + 1)

.segment "DZP": zeropage
dsrc:   .res 2
ddst:   .res 2
dlen:   .res 2
dbank:  .res 1

.segment "DRIVER"
drv_start:
        sei
        cld
        ldx     #DRV_STACK              ; $01F0-$01FF: a caller's frame the
        txs                             ;   replay must leave alone
        sta     RDMAIN
        sta     WRMAIN
        stz     BANKSEL
        bit     LCBANK1                 ; bank 1 at $D000, as outside the
        bit     LCBANK1                 ;   replay in the game
        stz     PHASE
.repeat MAX_BATCHES, K
        lda     #K
        cmp     DRV_N
        bcs     drv_done
        ldx     #K * 8
        jsr     load_batch
        lda     #2
        sta     PHASE
        lda     DRV_B + K * 8
        ldx     DRV_B + K * 8 + 1
.ident(.sprintf("drv_call%d", K)):
        jsr     nat_replay
.ident(.sprintf("drv_ret%d", K)):
        stz     PHASE
.endrep
drv_done:
drv_halt:
        bra     drv_halt

drv_crash:
        bra     drv_crash

; load_batch: X = 8 * the batch
load_batch:
        lda     DRV_BANK
        sta     dbank
        lda     DRV_B + 2,x
        sta     dlen
        lda     DRV_B + 3,x
        sta     dlen+1
        lda     DRV_B + 4,x
        sta     dsrc
        lda     DRV_B + 5,x
        sta     dsrc+1
        lda     #<RECBUF
        sta     ddst
        lda     #>RECBUF
        sta     ddst+1
        phx
        jsr     copy_far
        plx
        lda     DRV_B + 6,x
        sta     dsrc
        lda     DRV_B + 7,x
        sta     dsrc+1
        lda     #<COLLO
        sta     ddst
        lda     #>COLLO
        sta     ddst+1
        lda     #<COL_BYTES
        sta     dlen
        lda     #>COL_BYTES
        sta     dlen+1
        ; fall through

; copy_far: dlen bytes from dbank:dsrc to main ddst (runs from the card)
copy_far:
        lda     dbank
        sta     BANKSEL
        sta     RDAUX
        ldy     #0
        ldx     dlen+1
        beq     @rest
@page:  lda     (dsrc),y
        sta     (ddst),y
        iny
        bne     @page
        inc     dsrc+1
        inc     ddst+1
        dex
        bne     @page
@rest:  ldx     dlen
        beq     @done
@byte:  lda     (dsrc),y
        sta     (ddst),y
        iny
        dex
        bne     @byte
@done:  sta     RDMAIN
        stz     BANKSEL
        rts

.segment "VECTORS"
        .word   drv_crash               ; NMI
        .word   drv_start               ; reset
        .word   drv_crash               ; IRQ, BRK
