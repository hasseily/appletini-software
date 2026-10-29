; SPDX-License-Identifier: MIT
; ProDOS loads SYS files at $2000. Move the high-linked browser to $6000
; before its video backend takes ownership of $2000-$5FFF in both banks.
; Copy from the end: the source and destination overlap for large payloads.
.setcpu "6502"
.segment "CODE"
.export mono_loader_entry, mono_loader_payload

mono_loader_entry:
    php
    sei
    cld
copy:
source:
    lda mono_loader_payload + PAYLOAD_SIZE - 1
destination:
    sta $6000 + PAYLOAD_SIZE - 1
    lda source+1
    bne source_low
    dec source+2
source_low:
    dec source+1
    lda destination+1
    bne destination_low
    dec destination+2
destination_low:
    dec destination+1
    lda remaining
    bne count_low
    dec remaining+1
count_low:
    dec remaining
    lda remaining
    ora remaining+1
    bne copy
    plp
    jmp $6000
remaining:
    .word PAYLOAD_SIZE
mono_loader_payload:
    .incbin "A2MONO.payload.bin"
