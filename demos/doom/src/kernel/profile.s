; Low-overhead sampler: no extra peripheral reads in the IRQ. All live
; state remains in main ZP/LC, safe with RAMRD/RAMWRT and either D000 half.
; The host reads a separate aux0:A000 snapshot via vtw dump 1A000 2C.
.include "kernel.inc"
.include "profile.inc"
.ifdef PROFILE
.include "profile-build.inc"
.import ktics, kframes, _debug_hz
.export profile_samples, profile_snapshot, profile_tick, profile_publish
.segment "KZP": zeropage
profile_stage: .res 1
.segment "KBSS"
profile_samples: .res PROF_COUNT*2
.segment "KCODE"
profile_tick:
        ldx profile_stage
        inc profile_samples,x
        bne :+
        inc profile_samples+1,x
:       rts

; Only called after the game packet and readout have completed, in main
; context with GAME loaded. This avoids consuming scarce resident LC space.
.segment "DATA"
profile_snapshot:
        .word 0                         ; seqlock
        .byte "DPR1"
        PROFILE_BUILD_BYTES
        .word 0,0,0                     ; VBL, frames, tics
        .byte 60,0                      ; calibration, reserved
        .res PROF_COUNT*2,0
PROFILE_SIZE = *-profile_snapshot
.assert PROFILE_SIZE = 44, error, "update profiling metadata after ABI change"
profile_last: .word 0
profile_started: .byte 0
.segment "GBANKCODE"
profile_publish:
        ; Initial publication and then at most once per 60 VBLs. IRQs are
        ; masked only during the small coherent copy, not the far writes.
        php
        sei
        lda vbl_count
        sec
        sbc profile_last
        tax
        lda vbl_count+1
        sbc profile_last+1
        bne @ready
        cpx #60
        bcs @ready
        lda profile_started
        beq @ready
        plp
        rts
@ready:
        lda #1
        sta profile_started
        ldx #1
@clock: lda vbl_count,x
        sta profile_snapshot+10,x
        sta profile_last,x
        lda kframes,x
        sta profile_snapshot+12,x
        lda ktics,x
        sta profile_snapshot+14,x
        dex
        bpl @clock
        ldx #PROF_COUNT*2-1
@sample:
        lda profile_samples,x
        sta profile_snapshot+18,x
        dex
        bpl @sample
        plp
        lda _debug_hz
        sta profile_snapshot+16
        ; Publish odd sequence, the whole block, then even sequence. UART
        ; readers bracket their full dump with sequence reads and retry if
        ; either odd or changed. No IRQ touches this published block.
        jsr @sequence
        lda #PROFILE_SIZE
        jsr @write
@sequence:
        inc profile_snapshot
        bne :+
        inc profile_snapshot+1
:       lda #2
@write:
        sta far_len
        stz far_len+1
        lda #<profile_snapshot
        sta far_ptr
        lda #>profile_snapshot
        sta far_ptr+1
        stz far_dst
        lda #$A0
        sta far_dst+1
        stz far_dst+2
        jmp far_write
.endif
