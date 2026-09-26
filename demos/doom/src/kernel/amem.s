; Optional Appletini ARM COPY/FILL service, SmartPort controller selector $80.
; No slot-ROM entry is called: its $07F8 workspace belongs to the GAME image.
; Five immutable pages in bank 122 are overlaid on the existing LC kbuf.
; The mouse IRQ only touches $C0A0/$C0AF and never takes C800 ownership or kbuf.
.include "kernel.inc"
.import kbuf, kmemclr, amem_load
.import phase_game_end, _arena_ptr, __DATA_RUN__
.importzp RENDER_END
.export amem_init, amem_available, amem_status

SP_DATA = $CFF0
SP_CTRL = $CFF1
SP_POP = $CFF2
SP_RELEASE = $CFFF
SP_ROM = $C700
AMEM_UNAVAILABLE = $60
AMEM_TIMEOUT = $6F

.segment "KBSS"
amem_available: .res 1
amem_status:    .res 1

.segment "KCODE"
amem_init:
        bit LCBANK1WR
        bit LCBANK1WR
        lda #$B9
        jsr amem_load
        jsr kbuf
        bit LCBANK2WR
        bit LCBANK2WR
        rts

; A response is consumed only after ready. The three-byte poll bound also
; fails closed if a verified transport stops replying after a request.
; CPU holds do not advance this loop; IRQs may run without changing C8 owner.
.macro EXCHANGE request, count
        .local send, wait, ready
        bit SP_RELEASE
        bit SP_ROM
        ldx #0
send:   lda request,x
        sta SP_DATA
        inx
        cpx #count
        bne send
        lda #2
        sta SP_CTRL
        ldx #0
        ldy #0
        stz ktmp+7
wait:   lda SP_CTRL
        bmi ready
        dex
        bne wait
        dey
        bne wait
        dec ktmp+7
        bne wait
        lda #AMEM_TIMEOUT
        bra :+
ready:  lda SP_DATA
        sta SP_POP
:       sta amem_status
.endmacro

.macro REQUEST descriptors
        .byte 4,3,0,0,0,$80,0,0,0,0
        .word 8+16*descriptors
        .byte "AMEM",1,descriptors,0,0
.endmacro

; A=bank, X=first page, Y=exclusive last page; C=load, clear=save.
; The CPU fallback still uses the same eight-byte unrolled copy.
.segment "AMEMCOPY"
amem_copy:
        php
        sta copy_desc+3
        sta copy_desc+7
        stx copy_desc+5
        stx copy_desc+9
        stx ktmp
        tya
        sec
        sbc ktmp
        sta copy_desc+11
        plp
        lda #0
        bcc @save
        sta copy_desc+6
        sta copy_desc+7
        bra @ready
@save: sta copy_desc+2
        sta copy_desc+3
@ready: lda amem_available
        beq copy_cpu
        EXCHANGE copy_request,36
        bit SP_RELEASE
        lda amem_status
        beq copy_done
        cmp #AMEM_UNAVAILABLE
        bne copy_failed
        stz amem_available
copy_cpu:
        lda copy_desc+2
        beq @save
        lda copy_desc+3
        sta RAMWORKS
        sta RAMRDON
        bra @copy
@save: lda copy_desc+7
        sta RAMWORKS
        sta RAMWRTON
@copy: stz ktmp
        lda copy_desc+5
        sta ktmp+1
        ldx copy_desc+11
        ldy #0
@byte:
.repeat 8
        lda (ktmp),y
        sta (ktmp),y
        iny
.endrepeat
        bne @byte
        inc ktmp+1
        dex
        bne @byte
        sta RAMRDOFF
        sta RAMWRTOFF
copy_done:
        rts
copy_failed:
        jmp kernel_crash
copy_request:
        REQUEST 1
copy_desc:
        .byte 1,1,1,0,0,0,1,0,0,0,0,0,0,0,0,0
.assert *-amem_copy <= 256, error, "COPY overlay exceeds kbuf"
.res 256-(*-amem_copy),0

; Probe only the known slot-7 signature and accelerated private transport.
; A normal ROM/model without that transport never receives a FIFO command.
; Temporary capability bytes occupy the not-yet-rendered VIEWBUF.
.segment "AMEMPROBE"
amem_probe:
        stz amem_available
        lda #$FF
        sta amem_status
        bit SP_RELEASE
        lda SP_ROM+1
        cmp #$20
        bne probe_absent
        lda SP_ROM+3
        ora SP_ROM+7
        bne probe_absent
        lda SP_ROM+5
        cmp #3
        bne probe_absent
        lda SP_CTRL
        and #$3F
        cmp #$20
        beq probe_transport
probe_absent:
        bit SP_RELEASE
        rts
probe_transport:
        EXCHANGE probe_request,10
        lda amem_status
        bne probe_done
        lda SP_DATA
        sta SP_POP
        cmp #32
        bne probe_done
        lda SP_DATA
        sta SP_POP
        bne probe_done
        ldx #0
@read: lda SP_DATA
        sta SP_POP
        sta VIEWBUF,x
        inx
        cpx #32
        bne @read
        ldx #4
@id:   lda VIEWBUF,x
        cmp probe_magic,x
        bne probe_done
        dex
        bpl @id
        lda VIEWBUF+6
        cmp #16
        bne probe_done
        lda VIEWBUF+7
        cmp #4                  ; largest phase batch has four descriptors
        bcc probe_done
        lda VIEWBUF+8
        and #7
        cmp #7
        bne probe_done
        lda VIEWBUF+10
        ora VIEWBUF+12
        bne probe_done
        lda VIEWBUF+11
        cmp #2
        bne probe_done
        lda VIEWBUF+13
        cmp #$C0
        bne probe_done
        lda VIEWBUF+14
        cmp #GAME_HOME_BANK
        bcc probe_done
        lda VIEWBUF+15
        and #1
        sta amem_available
probe_done:
        bit SP_RELEASE
        rts
probe_request:
        .byte 0,3,0,0,0,$80,0,0,0,0
probe_magic: .byte "AMEM",1
.assert *-amem_probe <= 256, error, "PROBE overlay exceeds kbuf"
.res 256-(*-amem_probe),0

.segment "AMEMFILL"
amem_fill:
        EXCHANGE fill_request,36
        bit SP_RELEASE
        lda amem_status
        beq @done
        cmp #AMEM_UNAVAILABLE
        bne @failed
        stz amem_available
        lda #<VIEWBUF
        sta ktmp
        lda #>VIEWBUF
        sta ktmp+1
        lda #<VIEWBUF_SIZE
        ldx #>VIEWBUF_SIZE
        jmp kmemclr
@failed:
        jmp kernel_crash
@done: rts
fill_request:
        REQUEST 1
        .byte 2,1,0,0
        .word 0
        .byte 0,0
        .word VIEWBUF,VIEWBUF_SIZE
        .byte 0,0,0,0
.assert *-amem_fill <= 256, error, "FILL overlay exceeds kbuf"
.res 256-(*-amem_fill),0

; A batch either completes (C clear), is rejected before execution with $60
; (C set, disable API so the caller runs the whole CPU fallback), or stops.
; Never replay a partially executed list after any other error.
.macro BATCH_RESULT
        .local done, failed
        bit SP_RELEASE
        lda amem_status
        beq done
        cmp #AMEM_UNAVAILABLE
        bne failed
        stz amem_available
        sec
        rts
done:   clc
        rts
failed: jmp kernel_crash
.endmacro

; Same-address phase copy, with explicit PRIVATE permission for working RAM.
.macro PHASE_COPY source, source_bank, destination, destination_bank, first, last
        .byte 1,1,source,source_bank
        .word first
        .byte destination,destination_bank
        .word first,last-first
        .byte 0,0,0,0
.endmacro

; Save all mutable renderer ranges before the final descriptor replaces MAIN
; with GAME. On the first handoff phase_game_end is still $B8 (full load).
.segment "AMEMGAME"
amem_game:
        lda phase_game_end
        sec
        sbc #$02
        sta game_load_desc+11
        EXCHANGE game_request,84
        BATCH_RESULT
game_request:
        REQUEST 4
        PHASE_COPY 0,0,1,RENDER_HOME_BANK,$0200,$0400
        PHASE_COPY 0,0,1,RENDER_HOME_BANK,$0C00,$2000
        PHASE_COPY 0,0,1,RENDER_HOME_BANK,$6000,RENDER_END*$100
game_load_desc:
        PHASE_COPY 1,GAME_HOME_BANK,0,0,$0200,$0200
.assert *-amem_game <= 256, error, "GAME batch overlay exceeds kbuf"
.res 256-(*-amem_game),0

; Save live GAME state before restoring RENDER. The saved renderer zero page
; lives in VIEWBUF, so its FILL must wait until space_render recovers that ZP.
.segment "AMEMRENDER"
amem_render:
        ldy _arena_ptr+1
        lda _arena_ptr
        beq @rounded
        iny
@rounded:
        sty phase_game_end
        tya
        sec
        sbc #>__DATA_RUN__
        sta game_save_desc+11
        EXCHANGE render_request,52
        BATCH_RESULT
render_request:
        REQUEST 2
game_save_desc:
        PHASE_COPY 0,0,1,GAME_HOME_BANK,(__DATA_RUN__ & $FF00),(__DATA_RUN__ & $FF00)
        PHASE_COPY 1,RENDER_HOME_BANK,0,0,$0200,RENDER_END*$100
.assert *-amem_render <= 256, error, "RENDER batch overlay exceeds kbuf"
.res 256-(*-amem_render),0
