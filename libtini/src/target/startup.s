; ProDOS SYS entry and normal exit. No LC RAM is overwritten or mapped.
; Launch contract: enhanced //e/65C02, ProDOS SYS launch, MAIN RAMRD/RAMWRT,
; ALTZP off, RamWorks selector0, and Appletini fake SHR off ($C029=$01).
; C029/C073 are write-only interfaces; their previous values cannot be read.
; The launcher's RESET vector and ProDOS device list are never modified.
.setcpu "65C02"
.include "zeropage.inc"
.export __STARTUP__ : absolute = 1
.export _exit
.import _main, _ti_shutdown, _ti_platform_setup, zerobss
.import __STACKSTART__
.import __RODATA_LOAD__, __RODATA_RUN__, __RODATA_SIZE__
.import __AMEMCODE_LOAD__, __AMEMCODE_RUN__, __AMEMCODE_SIZE__
.import __LOWCODE_LOAD__, __LOWCODE_RUN__, __LOWCODE_SIZE__
.import __NEARBSS_RUN__, __NEARBSS_SIZE__

.segment "STARTUP"
; Entry code that runs once lives in ONCE. The full-game layout loads ONCE
; where BSS will lie, so zerobss reclaims those bytes; nothing in ONCE may
; run after it.
start:
        jmp entry
constants_ready:
        jsr zerobss
        lda #<__STACKSTART__
        sta c_sp
        lda #>__STACKSTART__
        sta c_sp+1
        jsr _ti_platform_setup
        lda entry_status
        and #$04                   ; inherit entry IRQ policy, binary C mode
        bne irq_disabled
        cli
irq_disabled:
        jsr _main

; ti_shutdown is idempotent and restores an active diagnostic AUX backup.
; Normal exit is supported; asynchronous Control-Reset is not a cleanup API.
_exit:
        jsr _ti_shutdown
        cmp #0
        beq cleanup_complete
        ; A failed DEALLOC_INTERRUPT must not leave an OS callback pointing
        ; at an unloaded SYS. Keep this program loaded and permit a retry.
        lda #1
        sta $C029
        bit $C051
        bit $C054
        ldx #0
show_cleanup_error:
        lda cleanup_error_text,x
        beq wait_cleanup_key
        ora #$80
        sta $0400,x
        inx
        bra show_cleanup_error
wait_cleanup_key:
        lda $C000
        bpl wait_cleanup_key
        bit $C010
        bra _exit
cleanup_complete:
        sei
        cld
        ldx #$FF
        txs
        sta $C002
        sta $C004
        sta $C008
        stz $C073
        lda #$01
        sta $C029                  ; documented entry state: fake SHR off

        ; Restore display switches in their normal read/write forms.
        ldx #0
restore_video:
        txa
        asl a
        tay
        lda saved_video,x
        bpl video_off
        iny
video_off:
        ; $C050/52/54/56 address pairs follow the first four saved flags.
        cpx #4
        bcs character_switch
        sta $C050,y
        bra next_video
character_switch:
        ; ALTCHAR and 80COL are write-only on $C00E/F and $C00C/D.
        cpx #4
        bne column_switch
        tya
        and #1
        tay
        sta $C00E,y
        bra next_video
column_switch:
        tya
        and #1
        tay
        sta $C00C,y
next_video:
        inx
        cpx #6
        bne restore_video
        lda saved_80store
        bpl store80_off
        sta $C001
        bra restore_memory
store80_off:
        sta $C000
restore_memory:
        ldx #$3F
restore_trampoline:
        lda saved_trampoline,x
        sta $0140,x
        dex
        bpl restore_trampoline
        ldx #zpspace-1
restore_zp:
        lda saved_zp,x
        sta c_sp,x
        dex
        bpl restore_zp
        lda entry_status
        pha
        plp
quit:
        jsr $BF00
        .byte $65
        .word quit_parameters
        ; QUIT should not return. A failed dispatcher call stays bounded
        ; in a retry loop with the same clean mappings; no stale RTS.
        jmp quit

cleanup_error_text:
        .byte "CLEANUP ERROR. KEY RETRIES; CODE RETAINED",0

.segment "RODATA"
quit_parameters:
        .byte 4,0
        .word 0
        .byte 0
        .word 0

; OSSTATE, deliberately outside zerobss and public writable near ranges:
; saved before the BSS is initialized and required for clean OS return.
.segment "OSSTATE"
entry_status:    .byte 0
saved_80store:   .byte 0
saved_video:    .res 6,0
saved_zp:       .res zpspace,0
saved_trampoline: .res $40,0

.segment "ONCE"
entry:
        php
        pla
        sta entry_status
        sei
        cld
        ldx #$FF
        txs

        ldx #zpspace-1
save_zp:
        lda c_sp,x
        sta saved_zp,x
        dex
        bpl save_zp
        ldx #$3F
save_trampoline:
        lda $0140,x
        sta saved_trampoline,x
        dex
        bpl save_trampoline

        ; These //e flags have standard status readback. Save before
        ; disabling 80STORE so it cannot redirect transfer address ranges.
        lda $C018
        sta saved_80store
        ldx #5
save_video:
        lda $C01A,x
        sta saved_video,x
        dex
        bpl save_video
        sta $C000                  ; 80STORE off
        sta $C002                  ; RAMRD main
        sta $C004                  ; RAMWRT main
        sta $C008                  ; ALTZP main
        stz $C073

        ; A full game may keep constant near data in low MAIN memory. The
        ; ProDOS load image can overlap future BSS/software stack; relocate
        ; constants before either is used. Foundation layout has LOAD=RUN.
        lda #<__RODATA_LOAD__
        sta ptr1
        lda #>__RODATA_LOAD__
        sta ptr1+1
        lda #<__RODATA_RUN__
        sta ptr2
        lda #>__RODATA_RUN__
        sta ptr2+1
        lda #<__RODATA_SIZE__
        sta sreg
        lda #>__RODATA_SIZE__
        sta sreg+1
        jsr copy_range
        lda #<__AMEMCODE_LOAD__
        sta ptr1
        lda #>__AMEMCODE_LOAD__
        sta ptr1+1
        lda #<__AMEMCODE_RUN__
        sta ptr2
        lda #>__AMEMCODE_RUN__
        sta ptr2+1
        lda #<__AMEMCODE_SIZE__
        sta sreg
        lda #>__AMEMCODE_SIZE__
        sta sreg+1
        jsr copy_range
        lda #<__LOWCODE_LOAD__
        sta ptr1
        lda #>__LOWCODE_LOAD__
        sta ptr1+1
        lda #<__LOWCODE_RUN__
        sta ptr2
        lda #>__LOWCODE_RUN__
        sta ptr2+1
        lda #<__LOWCODE_SIZE__
        sta sreg
        lda #>__LOWCODE_SIZE__
        sta sreg+1
        jsr copy_range
        ; Variables in the caller near arena's NEARBSS start at zero too.
        ; This follows relocation: the load image may extend over the arena.
        lda #<__NEARBSS_RUN__
        sta ptr1
        lda #>__NEARBSS_RUN__
        sta ptr1+1
        lda #0
        tay
        ldx #>__NEARBSS_SIZE__
        beq near_tail
near_page:
        sta (ptr1),y
        iny
        bne near_page
        inc ptr1+1
        dex
        bne near_page
near_tail:
        cpy #<__NEARBSS_SIZE__
        beq near_clear
        sta (ptr1),y
        iny
        bra near_tail
near_clear:
        jmp constants_ready
copy_range:
        lda ptr1
        cmp ptr2
        bne copy_start
        lda ptr1+1
        cmp ptr2+1
        beq copy_done
copy_start:
        ldy #0
copy_constant:
        lda sreg
        ora sreg+1
        beq copy_done
        lda (ptr1),y
        sta (ptr2),y
        inc ptr1
        bne :+
        inc ptr1+1
:       inc ptr2
        bne :+
        inc ptr2+1
:       lda sreg
        bne :+
        dec sreg+1
:       dec sreg
        bra copy_constant
copy_done:
        rts

; Keep the optional segment's linker symbols available in CPU-only layouts.
.segment "AMEMCODE"
        nop
.segment "LOWCODE"
        nop

; Every program has this segment, so its bounds are always defined.
.segment "NEARBSS"
