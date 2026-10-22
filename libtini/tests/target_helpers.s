.setcpu "65C02"

.export _test_backend_flags
.export _test_flags_failure
.import _ti_cpu_read, _ti_cpu_write

.segment "BSS"
saved_flags: .res 1
_test_flags_failure: .res 1

.segment "CODE"
; C sets the backend globals before calling. Exercise the real routines with
; both incoming IRQ states and test all flags promised by the backend ABI.
_test_backend_flags:
    lda #0
    sta _test_flags_failure
    cld
    cli
    sec
    php
    pla
    sta saved_flags
    pha
    plp
    jsr _ti_cpu_write
    php
    pla
    eor saved_flags
    and #$CF
    sta _test_flags_failure
    sei
    clc
    php
    pla
    sta saved_flags
    pha
    plp
    jsr _ti_cpu_read
    php
    pla
    eor saved_flags
    and #$CF
    ora _test_flags_failure
    sta _test_flags_failure
    cli
    rts
