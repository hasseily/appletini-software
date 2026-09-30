; REPLAY.SYSTEM: the native replay on the card, for the owner to run
; (milestone 5, acceptance 3). tools/native/disk.py builds the disk.
;
; Boot (at $2000, under ProDOS): read CATALOG, then each frame's file,
; whose records go into RamWorks banks (the frame's texels, records, and a
; copy of its main and aux-0 state, tools/native/disk.py). Then ProDOS is
; given up: the language-card image that follows this code in the file
; ($2800) goes to $D000-$FFFF, and the runner starts there.
;
; The runner, for each frame, then again after a key:
;   * restores the frame's state from its copies in RamWorks, as the game
;     loads it (docs/MEMORY_MAP.md rules 3, 4 and 8): main $0200-$03FF
;     and $0C00-$1FFF, and aux 0's screen $2000-$9FFF, by CPU; main's
;     colormaps and tables, aux 0's drawers and tables, by one memory-API
;     request of PRIVATE copies (appletini-one README_MEMORY_API.md, raw
;     FIFO transport; tools/native/layout.py PRIVATE_MAIN, PRIVATE_AUX0):
;     no CPU store ever reaches main $0400-$0BFF or $2000-$5FFF, so none
;     reaches the firmware's A2Li bytes $0878-$087F and $4078-$407F; then
;     shows SHR;
;   * runs the replay once, batch by batch (as src/native/driver.s), and
;     takes the CRC-32 of aux 0 $2000-$9FFF (zlib's);
;   * shows the frame for WAIT_VBL vertical blanks;
;   * runs it REPS more times (the covered ranges restored and the batches
;     loaded before each), counting the mouse card's VBL interrupts over
;     the whole loop, then the same loop without the replay calls;
; and at the end shows a table on the text screen: each frame's name, its
; CRC and whether it equals the expected one (the truth's, from the
; reference), then milliseconds a run at 50 Hz: the loop with the replay
; (LOOP), the loop without it (BASE), and their difference (REPLAY, the
; replay's time). Each is VBLs * 20 ms / REPS, rounded to 0.1 ms, so at
; REPS = 200 (tools/native/disk.py's default) one VBL is 0.1 ms a run and
; the figures are the VBL counts themselves.
;
; The IRQ handler follows the game's contract (docs/MEMORY_MAP.md rule 2):
; zero page $D8-$FF, the stack, $E000-$FFFF and the mouse card only. It
; never touches the C8 space, but the memory-API exchanges mask it anyway
; (README_MEMORY_API.md section 7).

        .setcpu "65C02"
        .include "layout.inc"
        .include "restore.inc"

        .import nat_replay
        .export boot, run_start, run_wait, run_key, run_crash
        .export run_restore, run_restored

MLI             = $BF00
NEWVIDEO        = $C029
KBD             = $C000
KBDSTRB         = $C010
ALTZPOFF        = $C008
COL80OFF        = $C00C
ALTCHAROFF      = $C00E
INTCXROMOFF     = $C006
TEXTON          = $C051
MIXEDOFF        = $C052
PAGE1           = $C054
LORES           = $C056
LCROMRD         = $C082
MOUSE_STATUS    = $C0A0
MOUSE_MODE      = $C0AE
MOUSE_ACK       = $C0AF
MOUSE_ROM       = $C200
MODE_VBL        = $09           ; the card on, with its VBL interrupt
ACK_ALL         = $03

SP_DATA         = $CFF0         ; the memory API's raw FIFO transport in
SP_CTRL         = $CFF1         ;   slot 7 (appletini-one
SP_POP          = $CFF2         ;   README_MEMORY_API.md section 7)
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F           ; (ours: no reply came)
RQ_HEAD         = 10 + 2 + 8    ; a request: the call, the list's length
                                ;   and header, then the descriptors

LCIMAGE         = $2800         ; the card image, after this code
LCIMAGE_SIZE    = $3000         ; $D000-$FFFF
IOBUF           = $6000         ; ProDOS's buffer for the open file
DATABUF         = $6800         ; file data, 8 KB at a time (above the
DATAMAX         = $2000         ;   card image, $2800-$57FF)
CATBUF          = DATABUF       ; CATALOG while booting

; CATALOG: +0 frames, +1 REPS, +2 WAIT_VBL, +3 unused, then 48 bytes a
; frame: its file's name (a ProDOS path: length, then up to 15 letters),
; its name to show (12 letters), the expected CRC (4 bytes), its first
; bank (texels base .. base + 3, records base + 4, main copy base + 5,
; aux-0 copy base + 6).
CAT_ENTRY       = 48
CAT_FIRST       = 4
E_FILE          = 0
E_NAME          = 16
E_CRC           = 28
E_BANK          = 32
MAX_FRAMES      = 20

; ---------------------------------------------------------------------------
.segment "IRQZP": zeropage
vbl:    .res 2          ; VBLs since the start
waitc:  .res 1          ; VBLs left to wait (the IRQ counts it down)

.segment "RUNZP": zeropage
bsrc:   .res 2          ; copies
bdst:   .res 2
blen:   .res 2
bbank:  .res 1
frame:  .res 1          ; the frame
entry:  .res 2          ; its catalog entry
reps:   .res 1
ticks:  .res 2          ; VBLs of the timed runs
t0:     .res 2
withrep:.res 1          ; bit 7: call the replay
crc:    .res 4
tmp:    .res 2
line:   .res 2          ; text output
col:    .res 1
wcount: .res 1          ; the memory API's reply wait

; ---------------------------------------------------------------------------
; boot: runs at $2000 under ProDOS
; ---------------------------------------------------------------------------
.segment "BOOT"
boot:   sei
        cld
        ldx     #$FF
        txs
        sta     TEXTON                  ; (no ROM calls: the text page
        sta     MIXEDOFF                ;   directly)
        sta     PAGE1
        sta     COL80OFF
        ldx     #0
        lda     #' ' | $80
:       sta     $0400,x
        sta     $0500,x
        sta     $0600,x
        sta     $0700,x
        inx
        bne     :-
:       lda     msg_load,x
        beq     :+
        sta     $0400,x
        inx
        bra     :-
:       stx     bcol
        lda     #<path_catalog          ; CATALOG
        ldx     #>path_catalog
        jsr     open
        lda     #<CATBUF
        sta     rd_buf
        lda     #>CATBUF
        sta     rd_buf+1
        lda     #<(CAT_FIRST + MAX_FRAMES * CAT_ENTRY)
        sta     rd_count
        lda     #>(CAT_FIRST + MAX_FRAMES * CAT_ENTRY)
        sta     rd_count+1
        jsr     read
        jsr     close
        ldx     #0                      ; keep it while the frames load
:       lda     CATBUF,x
        sta     cat_copy,x
        lda     CATBUF+$100,x
        sta     cat_copy+$100,x
        lda     CATBUF+$200,x
        sta     cat_copy+$200,x
        lda     CATBUF+$300,x
        sta     cat_copy+$300,x
        inx
        bne     :-
        stz     frame
@frame: lda     frame
        cmp     cat_copy
        bcc     :+
        jmp     @loaded
:
        jsr     boot_entry              ; tmp = the entry
        lda     #'.' | $80
        ldx     bcol
        sta     $0400,x
        inc     bcol
        lda     tmp                     ; its file (E_FILE = 0)
        ldx     tmp+1
        jsr     open
@rec:   lda     #<hdr                   ; a record: bank, address, length
        sta     rd_buf
        lda     #>hdr
        sta     rd_buf+1
        lda     #5
        sta     rd_count
        stz     rd_count+1
        jsr     read
        lda     hdr+3
        ora     hdr+4
        bne     :+
        jmp     @end
:
@chunk: lda     hdr+4                   ; up to 8 KB at a time
        cmp     #>DATAMAX
        bcc     :+
        lda     #<DATAMAX
        sta     rd_count
        lda     #>DATAMAX
        sta     rd_count+1
        bra     :++
:       lda     hdr+3
        sta     rd_count
        lda     hdr+4
        sta     rd_count+1
:       lda     #<DATABUF
        sta     rd_buf
        lda     #>DATABUF
        sta     rd_buf+1
        jsr     read
        lda     hdr                     ; into its bank
        sta     BANKSEL
        sta     WRAUX
        lda     #<DATABUF
        sta     bsrc
        lda     #>DATABUF
        sta     bsrc+1
        lda     hdr+1
        sta     bdst
        lda     hdr+2
        sta     bdst+1
        lda     rd_count
        sta     blen
        lda     rd_count+1
        sta     blen+1
        jsr     copy
        sta     WRMAIN
        stz     BANKSEL
        lda     hdr+1                   ; what is left
        clc
        adc     rd_count
        sta     hdr+1
        lda     hdr+2
        adc     rd_count+1
        sta     hdr+2
        lda     hdr+3
        sec
        sbc     rd_count
        sta     hdr+3
        lda     hdr+4
        sbc     rd_count+1
        sta     hdr+4
        ora     hdr+3
        beq     :+
        jmp     @chunk
:
        jmp     @rec
@end:   jsr     close
        inc     frame
        jmp     @frame
@loaded:
        bit     LCBANK2                 ; ProDOS goes: the card image
        bit     LCBANK2
        lda     #<LCIMAGE
        sta     bsrc
        lda     #>LCIMAGE
        sta     bsrc+1
        stz     bdst
        lda     #$D0
        sta     bdst+1
        lda     #<LCIMAGE_SIZE
        sta     blen
        lda     #>LCIMAGE_SIZE
        sta     blen+1
        jsr     copy
        ldx     #0                      ; the catalog, into the card
:       lda     cat_copy,x
        sta     catalog,x
        lda     cat_copy+$100,x
        sta     catalog+$100,x
        lda     cat_copy+$200,x
        sta     catalog+$200,x
        lda     cat_copy+$300,x
        sta     catalog+$300,x
        inx
        bne     :-
        jmp     run_start

; boot_entry: tmp = the catalog entry of frame (the boot's copy)
boot_entry:
        lda     #<(cat_copy + CAT_FIRST)
        sta     tmp
        lda     #>(cat_copy + CAT_FIRST)
        sta     tmp+1
        ldx     frame
        beq     @done
:       lda     tmp
        clc
        adc     #CAT_ENTRY
        sta     tmp
        bcc     :+
        inc     tmp+1
:       dex
        bne     :--
@done:  rts

; copy: blen bytes from bsrc to bdst, forward (blen > 0)
copy:   ldy     #0
        ldx     blen+1
        beq     @rest
@page:  lda     (bsrc),y
        sta     (bdst),y
        iny
        bne     @page
        inc     bsrc+1
        inc     bdst+1
        dex
        bne     @page
@rest:  ldx     blen
        beq     @done
@byte:  lda     (bsrc),y
        sta     (bdst),y
        iny
        dex
        bne     @byte
@done:  rts

open:   sta     op_path
        stx     op_path+1
        jsr     MLI
        .byte   $C8
        .word   op_parms
        bcs     boot_fail
        lda     op_ref
        sta     rd_ref
        sta     cl_ref
        rts

read:   jsr     MLI
        .byte   $CA
        .word   rd_parms
        bcs     boot_fail
        rts

close:  jsr     MLI
        .byte   $CC
        .word   cl_parms
        rts

boot_fail:
        tay
        ldx     #0
:       lda     msg_fail,x
        beq     :+
        sta     $0480,x
        inx
        bra     :-
:       tya                             ; the ProDOS error, in hex
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     bf_digit
        tya
        and     #$0F
        jsr     bf_digit
boot_stop:
        bra     boot_stop
bf_digit:
        cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0' | $80
        sta     $0480,x
        inx
        rts

op_parms:
        .byte   3
op_path:
        .word   0
        .word   IOBUF
op_ref: .byte   0
rd_parms:
        .byte   4
rd_ref: .byte   0
rd_buf: .word   0
rd_count:
        .word   0
        .word   0
cl_parms:
        .byte   1
cl_ref: .byte   0
hdr:    .res    5
bcol:   .res    1

path_catalog:
        .byte   7, "CATALOG"
msg_load:
        .repeat .strlen("NATIVE REPLAY: LOADING"), I
        .byte   .strat("NATIVE REPLAY: LOADING", I) | $80
        .endrep
        .byte   0
msg_fail:
        .repeat .strlen("PRODOS ERROR $"), I
        .byte   .strat("PRODOS ERROR $", I) | $80
        .endrep
        .byte   0
cat_copy = IOBUF + $400         ; (after ProDOS's buffer)
        .assert * <= LCIMAGE, error, "the boot code overlaps the card image"
        .assert IOBUF >= LCIMAGE + LCIMAGE_SIZE, error, "ProDOS's buffer"
        .assert cat_copy + $400 <= DATABUF, error, "the catalog's copy"
        .assert DATABUF + DATAMAX <= $BF00, error, "the data buffer"

; ---------------------------------------------------------------------------
; the runner: the main language card ($E000 part)
; ---------------------------------------------------------------------------
.segment "RUNNER"
run_start:
        sei
        cld
        ldx     #$FF
        txs
        sta     RDMAIN
        sta     WRMAIN
        sta     ALTZPOFF
        stz     BANKSEL
        bit     LCBANK1                 ; bank 1, as outside the replay
        bit     LCBANK1
        stz     vbl
        stz     vbl+1
        stz     waitc
        jsr     crc_tables
        jsr     mouse_init
        bcc     :+
        ldx     #msg_nomouse - messages
        jmp     fatal
:       jsr     amem_probe
        bcc     :+
        ldx     #msg_noamem - messages
        jmp     fatal_code
:       cli
run_again:
        stz     frame
@frame: lda     frame
        cmp     catalog
        bcs     @table
        jsr     run_entry
        jsr     restore
        lda     #$C1                    ; SHR on
        sta     NEWVIDEO
        lda     #$80
        sta     withrep
        jsr     replay_all              ; once, from the captured screen
        jsr     screen_crc
        ldy     #0                      ; the result: CRC, then the VBLs
        lda     frame
        asl     a
        asl     a
        asl     a
        tax
:       lda     crc,y
        sta     results,x
        inx
        iny
        cpy     #4
        bcc     :-
        lda     catalog+2               ; show it
        jsr     wait
        sec                             ; REPS runs: the covered ranges,
        jsr     timed                   ;   the batches, the replay
        lda     frame
        asl     a
        asl     a
        asl     a
        tax
        lda     ticks
        sta     results+4,x
        lda     ticks+1
        sta     results+5,x
        clc                             ; the same without the replay
        jsr     timed
        lda     frame
        asl     a
        asl     a
        asl     a
        tax
        lda     ticks
        sta     results+6,x
        lda     ticks+1
        sta     results+7,x
        inc     frame
        jmp     @frame
@table: jsr     show_table
run_key:
        lda     KBD
        bpl     run_key
        sta     KBDSTRB
        bra     run_again

; run_entry: entry = the catalog entry of frame
run_entry:
        lda     #<(catalog + CAT_FIRST)
        sta     entry
        lda     #>(catalog + CAT_FIRST)
        sta     entry+1
        ldx     frame
        beq     @done
:       lda     entry
        clc
        adc     #CAT_ENTRY
        sta     entry
        bcc     :+
        inc     entry+1
:       dex
        bne     :--
@done:  rts

; bank: A = the entry's bank + Y
entry_bank:
        sty     tmp
        ldy     #E_BANK
        lda     (entry),y
        clc
        adc     tmp
        rts

; restore: the frame's state from its copies (the header above)
restore:
run_restore:
        ldy     #L_MAIN_COPY            ; main $0200-$03FF, $0C00-$1FFF by
        jsr     entry_bank              ;   CPU
        sta     bbank
        lda     #$02
        ldx     #$04
        jsr     to_main
        lda     #$0C
        ldx     #$20
        jsr     to_main
        ldy     #L_AUX_COPY             ; the screen by CPU (rule 4)
        jsr     entry_bank
        sta     bbank
        lda     #$20
        ldx     #$A0
        jsr     to_aux0
        ldy     #L_MAIN_COPY            ; the rest by PRIVATE: the source
        jsr     entry_bank              ;   banks of the descriptors
        ldx     #0
        ldy     #0
:       cpy     #RESTORE_MAIN
        bne     :+
        inc     a                       ; (L_AUX_COPY = L_MAIN_COPY + 1)
:       sta     restore_list + 3 + RQ_HEAD,x
        pha
        txa
        clc
        adc     #16
        tax
        pla
        iny
        cpy     #RESTORE_N
        bcc     :--
        lda     #<restore_list
        sta     bsrc
        lda     #>restore_list
        sta     bsrc+1
        ldx     #RQ_HEAD + 16 * RESTORE_N
        php
        sei
        jsr     amem_send
        bit     SP_RELEASE
        plp
        cmp     #0
        beq     run_restored
        ldx     #msg_amem - messages
        jmp     fatal_code
run_restored:
        rts
        .assert L_AUX_COPY = L_MAIN_COPY + 1, error, "copy banks"

; restore_covered: the covered ranges the replay clears
restore_covered:
        ldy     #L_MAIN_COPY
        jsr     entry_bank
        sta     bbank
        lda     #>CVFIRST
        ldx     #>CVRECLO
        .assert <CVFIRST = 0 && <CVRECLO = $40, error, "covered ranges"
        jmp     to_main

; to_main: pages A .. X - 1 from bank bbank to main (RAMRD on, code here)
to_main:
        sta     bsrc+1
        sta     bdst+1
        stx     tmp
        stz     bsrc
        stz     bdst
        lda     bbank
        sta     BANKSEL
        sta     RDAUX
        ldy     #0
@page:  lda     (bsrc),y
        sta     (bdst),y
        iny
        bne     @page
        inc     bsrc+1
        inc     bdst+1
        lda     bsrc+1
        cmp     tmp
        bcc     @page
        sta     RDMAIN
        stz     BANKSEL
        rts

; to_aux0: pages A .. X - 1 from bank bbank to aux 0, a page at a time
; through the card
to_aux0:
        sta     bsrc+1
        stx     tmp
        stz     bsrc
@page:  lda     bbank
        sta     BANKSEL
        sta     RDAUX
        ldy     #0
:       lda     (bsrc),y
        sta     bounce,y
        iny
        bne     :-
        sta     RDMAIN
        stz     BANKSEL
        sta     WRAUX
:       lda     bounce,y
        sta     (bsrc),y
        iny
        bne     :-
        sta     WRMAIN
        inc     bsrc+1
        lda     bsrc+1
        cmp     tmp
        bcc     @page
        rts

; ---- the memory API (appletini-one README_MEMORY_API.md) ----

; amem_probe: C clear when slot 7 has the API with PRIVATE copies of
; RESTORE_N descriptors (sections 1-2; the ROM and transport checks of
; demos/doom's kernel/amem.s); else C set, A = the SmartPort result or
; $FF (no API)
amem_probe:
        php
        sei
        bit     SP_RELEASE
        lda     SP_ROM+1                ; the Appletini SmartPort ROM
        cmp     #$20
        bne     @absent
        lda     SP_ROM+3
        ora     SP_ROM+7
        bne     @absent
        lda     SP_ROM+5
        cmp     #3
        bne     @absent
        lda     SP_CTRL                 ; its raw transport
        and     #$3F
        cmp     #$20
        bne     @absent
        lda     #<status_request
        sta     bsrc
        lda     #>status_request
        sta     bsrc+1
        ldx     #10
        jsr     amem_send
        cmp     #0
        bne     @fail
        lda     SP_DATA                 ; the length: 32
        sta     SP_POP
        cmp     #32
        bne     @bad
        lda     SP_DATA
        sta     SP_POP
        bne     @bad
        ldx     #0
:       lda     SP_DATA
        sta     SP_POP
        sta     bounce,x
        inx
        cpx     #32
        bcc     :-
        ldx     #4                      ; "AMEM", version 1
:       lda     bounce,x
        cmp     amem_magic,x
        bne     @bad
        dex
        bpl     :-
        lda     bounce+6                ; descriptors of 16 bytes
        cmp     #16
        bne     @bad
        lda     bounce+7                ; as many as the restore's
        cmp     #RESTORE_N
        bcc     @bad
        lda     bounce+8                ; COPY, FILL, PRIVATE
        and     #7
        cmp     #7
        bne     @bad
        lda     bounce+15               ; available
        and     #1
        beq     @bad
        bit     SP_RELEASE
        plp
        clc
        rts
@absent:
        lda     #$FF
        bra     @fail
@bad:   lda     #$FE
@fail:  bit     SP_RELEASE
        plp
        sec
        rts

; amem_send: X bytes from (bsrc) into the FIFO, execute, wait for the
; reply and pop its first byte: A = the SmartPort result (AMEM_TIMEOUT
; when no reply comes). Interrupts masked by the caller; C8 stays
; selected (the caller releases it).
amem_send:
        bit     SP_RELEASE
        bit     SP_ROM
        stx     tmp
        ldy     #0
:       lda     (bsrc),y
        sta     SP_DATA
        iny
        cpy     tmp
        bne     :-
        lda     #2
        sta     SP_CTRL
        ldx     #0
        ldy     #0
        stz     wcount
@wait:  lda     SP_CTRL
        bmi     @ready
        dex
        bne     @wait
        dey
        bne     @wait
        dec     wcount
        bne     @wait
        lda     #AMEM_TIMEOUT
        rts
@ready: lda     SP_DATA
        sta     SP_POP
        rts

status_request:
        .byte   0, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; STATUS, unit 0, selector $80
amem_magic:
        .byte   "AMEM", 1

restore_list:
        .byte   4, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; CONTROL, unit 0, selector $80
        .word   8 + 16 * RESTORE_N
        .byte   "AMEM", 1, RESTORE_N, 0, 0
        RESTORE_LIST                    ; (restore.inc)
        .assert * - restore_list = RQ_HEAD + 16 * RESTORE_N, error, "list"
        .assert RQ_HEAD + 16 * RESTORE_N < 256, error, "one exchange"

; timed: C set: REPS runs of the frame (its covered ranges restored, its
; batches loaded, the replay called); C clear: the same without the
; replay. ticks = the VBLs of the whole loop.
timed:  ror     withrep
        lda     catalog+1
        sta     reps
        sei
        lda     vbl
        sta     t0
        lda     vbl+1
        sta     t0+1
        cli
@rep:   jsr     restore_covered
        jsr     replay_all
        dec     reps
        bne     @rep
        sei
        lda     vbl
        sec
        sbc     t0
        sta     ticks
        lda     vbl+1
        sbc     t0+1
        sta     ticks+1
        cli
        rts

; replay_all: every batch of the frame (the table at DRVDATA, restored),
; the replay called on each unless withrep is clear (bit 7)
replay_all:
        ldx     #0
@batch: txa
        lsr     a
        lsr     a
        lsr     a
        cmp     DRVDATA
        bcs     @done
        phx
        jsr     load_batch
        plx
        bit     withrep
        bpl     @next
        phx
        lda     DRVDATA+2,x
        pha
        lda     DRVDATA+3,x
        tax
        pla
        jsr     nat_replay
        plx
@next:  txa
        clc
        adc     #8
        tax
        bra     @batch
@done:  rts

; load_batch: X = 8 * the batch (src/native/driver.s load_batch)
load_batch:
        lda     DRVDATA+1
        sta     bbank
        lda     DRVDATA+2+2,x
        sta     blen
        lda     DRVDATA+2+3,x
        sta     blen+1
        lda     DRVDATA+2+4,x
        sta     bsrc
        lda     DRVDATA+2+5,x
        sta     bsrc+1
        lda     #<RECBUF
        sta     bdst
        lda     #>RECBUF
        sta     bdst+1
        phx
        jsr     copy_far
        plx
        lda     DRVDATA+2+6,x
        sta     bsrc
        lda     DRVDATA+2+7,x
        sta     bsrc+1
        lda     #<COLLO
        sta     bdst
        lda     #>COLLO
        sta     bdst+1
        lda     #<(2 * (COLUMNS + 1))
        sta     blen
        lda     #>(2 * (COLUMNS + 1))
        sta     blen+1
copy_far:
        lda     bbank
        sta     BANKSEL
        sta     RDAUX
        ldy     #0
        ldx     blen+1
        beq     @rest
@page:  lda     (bsrc),y
        sta     (bdst),y
        iny
        bne     @page
        inc     bsrc+1
        inc     bdst+1
        dex
        bne     @page
@rest:  ldx     blen
        beq     @done
@byte:  lda     (bsrc),y
        sta     (bdst),y
        iny
        dex
        bne     @byte
@done:  sta     RDMAIN
        stz     BANKSEL
        rts

; wait: A VBLs
wait:   sta     waitc
run_wait:
        lda     waitc
        bne     run_wait
        rts

; ---- CRC-32 of aux 0 $2000-$9FFF (zlib's: reflected, $EDB88320) ----
screen_crc:
        lda     #$FF
        sta     crc
        sta     crc+1
        sta     crc+2
        sta     crc+3
        stz     bsrc
        lda     #$20
        sta     bsrc+1
        sta     RDAUX                   ; ($C073 is 0: aux 0)
        ldy     #0
@byte:  lda     (bsrc),y
        eor     crc
        tax
        lda     crc+1
        eor     crc_t0,x
        sta     crc
        lda     crc+2
        eor     crc_t1,x
        sta     crc+1
        lda     crc+3
        eor     crc_t2,x
        sta     crc+2
        lda     crc_t3,x
        sta     crc+3
        iny
        bne     @byte
        inc     bsrc+1
        lda     bsrc+1
        cmp     #$A0
        bcc     @byte
        sta     RDMAIN
        ldx     #3
:       lda     crc,x
        eor     #$FF
        sta     crc,x
        dex
        bpl     :-
        rts

; crc_tables: table[i] = i shifted right 8 times through $EDB88320, as
; four byte planes
crc_tables:
        ldx     #0
@entry: stx     crc
        stz     crc+1
        stz     crc+2
        stz     crc+3
        ldy     #8
@bit:   lsr     crc+3
        ror     crc+2
        ror     crc+1
        ror     crc
        bcc     :+
        lda     crc
        eor     #$20
        sta     crc
        lda     crc+1
        eor     #$83
        sta     crc+1
        lda     crc+2
        eor     #$B8
        sta     crc+2
        lda     crc+3
        eor     #$ED
        sta     crc+3
:       dey
        bne     @bit
        lda     crc
        sta     crc_t0,x
        lda     crc+1
        sta     crc_t1,x
        lda     crc+2
        sta     crc_t2,x
        lda     crc+3
        sta     crc_t3,x
        inx
        bne     @entry
        rts

; ---- the mouse card: C set when there is none ----
mouse_init:
        sta     INTCXROMOFF
        lda     MOUSE_ROM+$05
        cmp     #$38
        bne     @none
        lda     MOUSE_ROM+$07
        cmp     #$18
        bne     @none
        lda     MOUSE_ROM+$0B
        cmp     #$01
        bne     @none
        lda     MOUSE_ROM+$0C
        cmp     #$20
        bne     @none
        lda     #ACK_ALL
        sta     MOUSE_ACK
        lda     #MODE_VBL
        sta     MOUSE_MODE
        clc
        rts
@none:  sec
        rts

; ---- the interrupt: VBLs; a BRK is the replay's crash ----
irq:    pha
        phx
        tsx
        lda     $0103,x
        and     #$10
        bne     @brk
        ldx     MOUSE_STATUS
        lda     #ACK_ALL
        sta     MOUSE_ACK
        txa
        and     #$08
        beq     @done
        inc     vbl
        bne     :+
        inc     vbl+1
:       lda     waitc
        beq     @done
        dec     waitc
@done:  plx
        pla
        rti
@brk:   ldx     #msg_crash - messages
        bra     fatal

; fatal_code: fatal, then A in hex
fatal_code:
        sei
        sta     withrep
        jsr     fatal_text
        lda     withrep
        jsr     hex
:       bra     :-

; fatal: text screen, the message at messages + X, stop
fatal:  sei
        jsr     fatal_text
:       bra     :-

; fatal_text: the text screen with the message at messages + X (tools/
; native/disk.py stops its run here)
fatal_text:
run_crash:
        stz     MOUSE_MODE
        sta     RDMAIN
        sta     WRMAIN
        stz     BANKSEL
        phx
        jsr     text_mode
        plx
        stz     line
        lda     #$04
        sta     line+1
        stz     col
        jmp     print

; ---- the table ----
show_table:
        jsr     text_mode
        lda     #0                      ; the title on row 0
        jsr     row
        ldx     #msg_title - messages
        jsr     print
        lda     #1                      ; the units on row 1
        jsr     row
        ldx     #msg_units - messages
        jsr     print
        stz     frame
@line:  lda     frame
        cmp     catalog
        bcc     :+
        jmp     @done
:
        clc
        adc     #2
        jsr     row
        jsr     run_entry
        ldy     #E_NAME                 ; the name: its first 7 letters
:       lda     (entry),y
        ora     #$80
        jsr     putc
        iny
        cpy     #E_NAME + 7
        bcc     :-
        lda     #' ' | $80
        jsr     putc
        lda     frame                   ; the CRC, high byte first
        asl     a
        asl     a
        asl     a
        tax
        lda     results+3,x
        jsr     hex
        lda     results+2,x
        jsr     hex
        lda     results+1,x
        jsr     hex
        lda     results,x
        jsr     hex
        lda     #' ' | $80
        jsr     putc
        ldy     #E_CRC                  ; equal to the expected one?
        lda     (entry),y
        cmp     results,x
        bne     @bad
        iny
        lda     (entry),y
        cmp     results+1,x
        bne     @bad
        iny
        lda     (entry),y
        cmp     results+2,x
        bne     @bad
        iny
        lda     (entry),y
        cmp     results+3,x
        bne     @bad
        lda     #'O' | $80
        jsr     putc
        lda     #'K' | $80
        bra     @vbl
@bad:   lda     #'N' | $80
        jsr     putc
        lda     #'O' | $80
@vbl:   jsr     putc
        lda     results+4,x             ; LOOP: the VBLs with the replay
        sta     tmp
        lda     results+5,x
        sta     tmp+1
        jsr     ms_field
        lda     results+6,x             ; BASE: without it
        sta     tmp
        lda     results+7,x
        sta     tmp+1
        jsr     ms_field
        lda     results+4,x             ; REPLAY: the difference (0 if
        sec                             ;   the base took longer)
        sbc     results+6,x
        sta     tmp
        lda     results+5,x
        sbc     results+7,x
        sta     tmp+1
        bcs     :+
        stz     tmp
        stz     tmp+1
:       jsr     ms_field
        inc     frame
        jmp     @line
@done:  lda     frame
        clc
        adc     #3
        jsr     row
        ldx     #msg_key - messages
        jmp     print

; ms_field: a blank, then tmp VBLs as milliseconds a run at 50 Hz,
; "NNN.N" (X kept)
ms_field:
        lda     #' ' | $80
        jsr     putc
        jsr     tenths
        jmp     decimal

; tenths: tmp = tmp * 200 / REPS rounded (tenths of a millisecond a run
; at 20 ms a VBL), at most 9,999. The product has 24 bits (crc .. crc+2).
tenths: phx
        lda     tmp                     ; crc = tmp * 8
        sta     crc
        lda     tmp+1
        sta     crc+1
        stz     crc+2
        ldy     #3
:       asl     crc
        rol     crc+1
        rol     crc+2
        dey
        bne     :-
        lda     crc                     ; tmp.crc+3 = tmp * 8 (kept)
        sta     tmp
        lda     crc+1
        sta     tmp+1
        lda     crc+2
        sta     crc+3
        ldx     #2                      ; + tmp * 64, + tmp * 128
@add:   ldy     #3                      ;   (* 8 more, then * 2 more)
        cpx     #1
        bne     :+
        ldy     #1
:       asl     tmp
        rol     tmp+1
        rol     crc+3
        dey
        bne     :-
        lda     crc
        clc
        adc     tmp
        sta     crc
        lda     crc+1
        adc     tmp+1
        sta     crc+1
        lda     crc+2
        adc     crc+3
        sta     crc+2
        dex
        bne     @add
        lda     catalog+1               ; + REPS / 2: rounded
        lsr     a
        clc
        adc     crc
        sta     crc
        bcc     :+
        inc     crc+1
        bne     :+
        inc     crc+2
:       lda     #0                      ; / REPS: 24 by 8 bits, the
        ldy     #24                     ;   quotient in place
@div:   asl     crc
        rol     crc+1
        rol     crc+2
        rol     a
        bcs     @sub                    ; (9 bits: over REPS)
        cmp     catalog+1
        bcc     @next
@sub:   sbc     catalog+1
        inc     crc
@next:  dey
        bne     @div
        lda     crc
        sta     tmp
        lda     crc+1
        sta     tmp+1
        lda     crc+2                   ; at most 9,999
        bne     @max
        lda     tmp
        cmp     #<10000
        lda     tmp+1
        sbc     #>10000
        bcc     @done
@max:   lda     #<9999
        sta     tmp
        lda     #>9999
        sta     tmp+1
@done:  plx
        rts

; decimal: tmp (tenths, < 1,000.0) as "NNN.N", leading blanks
decimal:
        phx
        ldx     #1                      ; (from the thousands' digit)
        stz     crc                     ; a digit printed yet
@digit: ldy     #0
@sub:   lda     tmp
        sec
        sbc     powers_lo,x
        pha
        lda     tmp+1
        sbc     powers_hi,x
        bcc     @done1
        sta     tmp+1
        pla
        sta     tmp
        iny
        bra     @sub
@done1: pla
        tya
        bne     @print
        lda     crc
        bne     @print
        cpx     #3                      ; always the units digit
        bcs     @print
        lda     #' ' | $80
        bra     @put
@print: inc     crc
        tya
        ora     #'0' | $80
@put:   jsr     putc
        cpx     #3
        bne     :+
        lda     #'.' | $80
        jsr     putc
:       inx
        cpx     #5
        bcc     @digit
        plx
        rts
powers_lo:
        .byte   <10000, <1000, <100, <10, <1
powers_hi:
        .byte   >10000, >1000, >100, >10, >1

text_mode:
        lda     #$01                    ; SHR off
        sta     NEWVIDEO
        sta     TEXTON
        sta     MIXEDOFF
        sta     PAGE1
        sta     COL80OFF
        sta     ALTCHAROFF
        ldx     #0                      ; blank the text page
        lda     #' ' | $80
:       sta     $0400,x
        sta     $0500,x
        sta     $0600,x
        sta     $0700,x
        inx
        bne     :-
        rts

; row: line = the text address of row A, col = 0
row:    tax
        lda     text_lo,x
        sta     line
        lda     text_hi,x
        sta     line+1
        stz     col
        rts

putc:   phy
        ldy     col
        sta     (line),y
        inc     col
        ply
        rts

hex:    pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     @digit
        pla
        and     #$0F
@digit: cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0' | $80
        jmp     putc

; print: the message at messages + X (0 ends it)
print:  lda     messages,x
        beq     @done
        ora     #$80
        jsr     putc
        inx
        bra     print
@done:  rts

text_lo:
        .repeat 24, R
        .byte   <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
text_hi:
        .repeat 24, R
        .byte   >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep

messages:
msg_title:
        .byte   "FRAME   CRC-32   OK  LOOP  BASE REPLAY", 0
msg_units:
        .byte   "MS A RUN AT 50 HZ (NTSC: MS X 0.834)", 0
msg_key:
        .byte   "REPLAY = LOOP - BASE. A KEY: AGAIN", 0
msg_nomouse:
        .byte   "NO MOUSE CARD IN SLOT 2: NO VBL CLOCK", 0
msg_crash:
        .byte   "THE REPLAY CRASHED (BRK)", 0
msg_noamem:
        .byte   "NO MEMORY API IN SLOT 7 (F1.1.4 OR LATER) $", 0
msg_amem:
        .byte   "MEMORY API ERROR $", 0

L_MAIN_COPY     = 5
L_AUX_COPY      = 6

.segment "RUNBSS"
catalog:        .res    $400            ; (the boot copies 1 KB)
        .assert CAT_FIRST + MAX_FRAMES * CAT_ENTRY <= $400, error, "catalog"
results:        .res    8 * MAX_FRAMES  ; CRC (4), the VBLs of the loop
                                        ;   with the replay (2), without (2)
bounce:         .res    256
crc_t0:         .res    256
crc_t1:         .res    256
crc_t2:         .res    256
crc_t3:         .res    256

.segment "VECTORS"
        .word   irq                     ; NMI
        .word   run_start               ; reset
        .word   irq                     ; IRQ, BRK
