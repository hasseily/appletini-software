; Bounded, callback-fed PHS1 register player for the slot 4 Phasor
; (Appletini One F1.2.5+ native Phasor, or a real card).
; This module owns both VIAs' sound ports, four AYs, and both SSI-263s.
; Caller supplies a stream reader and a clock; see README.md for the ABI.

        .setcpu "65C02"
        .include "phasor.inc"
        .export phs_init, phs_start, phs_tick, phs_stop
        .export phs_reader, phs_playing, phs_error, phs_tick_hz
        .export phs_duration, phs_elapsed

        .segment "BSS"
phs_reader:     .res 2
phs_playing:    .res 1
phs_error:      .res 1
header:         .res 4
phs_tick_hz:    .res 2
flags:          .res 2
phs_duration:   .res 4
records_left:   .res 4
phs_elapsed:    .res 4
record_time:    .res 4
delay:          .res 2
loaded:         .res 1
count:          .res 1
records_budget: .res 1
writes_budget:  .res 1
opcodes:        .res 255
values:         .res 255
write_opcode:   .res 1
write_value:    .res 1
stop_chip:      .res 1

        .segment "RODATA"
magic:          .byte "PHS1"
ay_writer:      .word write_ay0, write_ay1, write_ay2, write_ay3

        .segment "CODE"

; Claim sound ports. Call once before installing a caller-owned timer IRQ.
; Deliberately does not install an IRQ handler or configure VIA timers.
phs_init:
        bit     $C0C8
        bit     $C0C5
        lda     #$7F
        sta     PHS_VIA0_IER
        sta     PHS_VIA1_IER
        lda     #$FF
        sta     PHS_VIA0_DDRA
        sta     PHS_VIA1_DDRA
        lda     #$1F
        sta     PHS_VIA0_DDRB
        sta     PHS_VIA1_DDRB
        stz     PHS_VIA0_ORB
        stz     PHS_VIA1_ORB
        lda     #$0C
        sta     PHS_VIA0_ORB
        sta     PHS_VIA1_ORB
        stz     phs_reader
        stz     phs_reader+1
        stz     phs_error
        jmp     phs_stop

; Stop immediately, keeping the last error. Hold SSI CONTROL high, amplitude 0.
; A falling CONTROL edge here could accidentally latch a new mode/enable IRQ.
; No read of ORA with handshake: CA1/SSI state is not acknowledged by music.
phs_stop:
        stz     phs_playing
        stz     loaded
        lda     #$80
        sta     PHS_SSI0+3
        sta     PHS_SSI1+3
        stz     stop_chip
@chip:
        lda     stop_chip
        ora     #7
        sta     write_opcode
        lda     #$3F
        sta     write_value
        jsr     write_register
        inc     write_opcode
        stz     write_value
        jsr     write_register
        inc     write_opcode
        jsr     write_register
        inc     write_opcode
        jsr     write_register
        lda     stop_chip
        clc
        adc     #$10
        sta     stop_chip
        cmp     #$40
        bne     @chip
        rts

; Start consumes header and emits every record at time 0 synchronously.
; Success C=0; failure C=1, A=phs_error. Reader is already positioned at PHS1.
phs_start:
        jsr     phs_stop
        stz     phs_error
        lda     phs_reader
        ora     phs_reader+1
        bne     @reader_ok
        lda     #PHS_ERR_READER
        jmp     fail
@reader_ok:
        ldx     #0
@header:
        jsr     read_byte
        bcc     :+
        jmp     read_fail
:       sta     header,x
        inx
        cpx     #16
        bne     @header
        ldx     #3
@magic:
        lda     header,x
        cmp     magic,x
        bne     @bad_header
        dex
        bpl     @magic
        lda     phs_tick_hz
        ora     phs_tick_hz+1
        beq     @bad_header
        lda     flags
        ora     flags+1
        bne     @bad_header
        ldx     #3
@clear:
        stz     phs_elapsed,x
        stz     record_time,x
        dex
        bpl     @clear
        lda     #1
        sta     phs_playing
        jsr     load_record
        bcc     :+
        rts
:       jmp     run_due
@bad_header:
        lda     #PHS_ERR_HEADER
        jmp     fail

; Each call advances elapsed time by exactly one header tick.
; Decimal mode must be clear. All public routines clobber A/X/Y and flags.
phs_tick:
        lda     phs_playing
        bne     :+
        clc
        rts
:       inc     phs_elapsed
        bne     run_due
        inc     phs_elapsed+1
        bne     run_due
        inc     phs_elapsed+2
        bne     run_due
        inc     phs_elapsed+3

run_due:
        lda     #PHS_MAX_RECORDS
        sta     records_budget
        lda     #PHS_MAX_WRITES
        sta     writes_budget
@next:
        lda     loaded
        beq     @duration
        ldx     #3
@compare:
        lda     record_time,x
        cmp     phs_elapsed,x
        bne     @duration             ; future record; no work this tick
        dex
        bpl     @compare
        lda     records_budget
        beq     @budget_fail
        dec     records_budget
        sec
        lda     writes_budget
        sbc     count
        bcc     @budget_fail
        sta     writes_budget
        ldx     #0
@write:
        cpx     count
        beq     @advance
        lda     opcodes,x
        sta     write_opcode
        lda     values,x
        sta     write_value
        phx
        jsr     write_register
        plx
        inx
        bra     @write
@advance:
        jsr     load_record
        bcc     @next
        rts
@duration:
        ldx     #3
@end_compare:
        lda     phs_elapsed,x
        cmp     phs_duration,x
        bne     @ok
        dex
        bpl     @end_compare
        jsr     phs_stop
@ok:    clc
        rts
@budget_fail:
        lda     #PHS_ERR_BUDGET
        jmp     fail

; Read and validate a complete next record before any of its writes.
; SSI edge-triggered duplicates/order are deliberately kept intact.
load_record:
        stz     loaded
        lda     records_left
        ora     records_left+1
        ora     records_left+2
        ora     records_left+3
        bne     @read
        clc
        rts
@read:
        jsr     read_byte
        bcc     :+
        jmp     read_fail
:       sta     delay
        jsr     read_byte
        bcc     :+
        jmp     read_fail
:       sta     delay+1
        clc
        lda     record_time
        adc     delay
        sta     record_time
        lda     record_time+1
        adc     delay+1
        sta     record_time+1
        lda     record_time+2
        adc     #0
        sta     record_time+2
        lda     record_time+3
        adc     #0
        sta     record_time+3
        bcs     @time_fail
        ldx     #3
@time:
        lda     record_time,x
        cmp     phs_duration,x
        bcc     @count
        bne     @time_fail
        dex
        bpl     @time
@count:
        jsr     read_byte
        bcs     read_fail
        sta     count
        ldx     #0
@command:
        cpx     count
        beq     @done
        jsr     read_byte
        bcs     read_fail
        sta     opcodes,x
        cmp     #$40
        bcs     @ssi
        and     #$0F
        cmp     #14
        bcs     @command_fail
        bra     @value
@ssi:   cmp     #$60
        bcs     @command_fail
        and     #$0F
        cmp     #5
        bcs     @command_fail
@value:
        jsr     read_byte
        bcs     read_fail
        sta     values,x
        inx
        bra     @command
@done:
        ; Decrement remaining 32-bit record count without decimal arithmetic.
        ldx     #0
@borrow:
        lda     records_left,x
        bne     @decrement
        dec     records_left,x
        inx
        bra     @borrow
@decrement:
        dec     records_left,x
        lda     #1
        sta     loaded
        clc
        rts
@time_fail:
        lda     #PHS_ERR_TIME
        jmp     fail
@command_fail:
        lda     #PHS_ERR_COMMAND
        jmp     fail

read_fail:
        lda     #PHS_ERR_READ
fail:
        sta     phs_error
        jsr     phs_stop
        lda     phs_error
        sec
        rts

; Reader callback may clobber A/X/Y; C=0 byte in A, C=1 unavailable/EOF.
; It must return with decimal mode clear and preserve SP except its RTS.
read_byte:
        phx
        phy
        jsr     @dispatch
        ply
        plx
        rts
@dispatch:
        jmp     (phs_reader)

; Ordered bus burst: every AY command explicitly latches its register.
; Native hardware order is primary VIA0, primary VIA1, secondary VIA0/1.
write_register:
        lda     write_opcode
        cmp     #$40
        bcs     @ssi
        and     #$30
        lsr     a
        lsr     a
        lsr     a
        tax
        lda     write_opcode
        and     #$0F
        jmp     (ay_writer,x)
@ssi:   and     #$0F
        tax
        lda     write_opcode
        cmp     #$50
        bcs     @ssi1
        lda     write_value
        sta     PHS_SSI0,x
        rts
@ssi1:  lda     write_value
        sta     PHS_SSI1,x
        rts

; Static addresses keep each AY bus transaction to six VIA stores.
; A contains register; every write ends with BDIR/BC1 idle.
.macro WRITE_AY ora, orb, idle
        ldy     #idle
        sta     ora
        lda     #idle | 3
        sta     orb
        sty     orb
        lda     write_value
        sta     ora
        lda     #idle | 2
        sta     orb
        sty     orb
        rts
.endmacro

write_ay0:
        WRITE_AY PHS_VIA0_ORA_NH, PHS_VIA0_ORB, $0C
write_ay1:
        WRITE_AY PHS_VIA1_ORA_NH, PHS_VIA1_ORB, $0C
write_ay2:
        WRITE_AY PHS_VIA0_ORA_NH, PHS_VIA0_ORB, $14
write_ay3:
        WRITE_AY PHS_VIA1_ORA_NH, PHS_VIA1_ORB, $14
