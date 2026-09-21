; The Bilestoad SHR port: ProDOS loader.
;
; ProDOS loads this SYS file at $2000. The loader checks for RamWorks
; memory, loads the sprite banks from BILESTOAD.SPR into auxiliary banks
; 1..SPRITE_BANKS at $1000, then starts the game. ProDOS is not used again:
; the engine keeps its sprite slots in the language card RAM.

MLI         = $BF00
DEVNUM      = $BF30
MLI_QUIT    = $65
MLI_ONLINE  = $C5
MLI_SETPFX  = $C6
MLI_GETPFX  = $C7
MLI_OPEN    = $C8
MLI_READ    = $CA
MLI_CLOSE   = $CC
COUT        = $FDED
RDKEY       = $FD0C
TWSPEED     = $C074             ; 0 = release a TransWarp-style 1 MHz lock
IO_BUFFER   = $9C00             ; 1 KiB, page aligned (the arena, free for now)
CHUNK       = $A000             ; 4 KiB read buffer
CHUNK_SIZE  = $1000
BANK_BASE   = $1000
BANK_CHUNKS = 11                ; $1000-$BFFF

.segment "STARTUP"
    jmp boot

.segment "LOADER"
boot:
    ; ProDOS enters with the stack pointer low ($1F was seen). The fetch
    ; routine lives at $0110, so the stack must start at the top of page 1.
    ldx #$FF
    txs
    stz TWSPEED
    jsr install_fetch
    ; RamWorks test: bank 1 and bank 0 must hold different bytes at $1000.
    lda #1
    ldx #$5A
    jsr poke_bank
    lda #0
    ldx #$A5
    jsr poke_bank
    lda #<BANK_BASE
    sta SRC
    lda #>BANK_BASE
    sta SRC+1
    lda #<CHUNK
    sta DST
    lda #>CHUNK
    sta DST+1
    lda #1
    sta CNT                     ; one page
    ldx #1
    jsr FETCH
    lda CHUNK
    cmp #$5A
    beq :+
    lda #<msg_ramworks
    ldx #>msg_ramworks
    jmp fail
:
    ; An empty prefix means a cold boot: use the boot volume.
    jsr MLI
    .byte MLI_GETPFX
    .addr p_prefix
    lda path_buffer
    bne @open
    lda DEVNUM
    sta p_online+1
    jsr MLI
    .byte MLI_ONLINE
    .addr p_online
    bcs @open
    lda path_buffer+1
    and #$0F
    beq @open
    inc a
    sta path_buffer             ; length with the leading '/'
    lda #'/'
    sta path_buffer+1
    jsr MLI
    .byte MLI_SETPFX
    .addr p_prefix
@open:
    jsr MLI
    .byte MLI_OPEN
    .addr p_open
    bcc :+
    lda #<msg_file
    ldx #>msg_file
    jmp fail
:   lda p_open+5
    sta p_read+1
    sta p_close+1
    lda #SPRITE_FIRST_BANK
    sta bank
@bank:
    lda #>BANK_BASE
    sta dest_page
    lda #BANK_CHUNKS
    sta chunks
@chunk:
    jsr MLI
    .byte MLI_READ
    .addr p_read
    bcc :+
    lda #<msg_file
    ldx #>msg_file
    jmp fail
:   ; main CHUNK -> auxiliary bank at dest_page
    lda #<CHUNK
    sta SRC
    lda #>CHUNK
    sta SRC+1
    stz DST
    lda dest_page
    sta DST+1
    lda bank
    sta RWBANK
    sta RAMWRT_ON
    ldx #>CHUNK_SIZE
    ldy #0
@copy:
    lda (SRC),y
    sta (DST),y
    iny
    bne @copy
    inc SRC+1
    inc DST+1
    dex
    bne @copy
    sta RAMWRT_OFF
    stz RWBANK
    clc
    lda dest_page
    adc #>CHUNK_SIZE
    sta dest_page
    dec chunks
    bne @chunk
    inc bank
    lda bank
    cmp #SPRITE_FIRST_BANK + SPRITE_BANKS
    bcc @bank
    jsr MLI
    .byte MLI_CLOSE
    .addr p_close
    stz $03F4                   ; CTRL-RESET restarts the machine
    jmp GAME_ENTRY

; A = bank, X = byte: write X to $1000 of that auxiliary bank.
poke_bank:
    sta RWBANK
    sta RAMWRT_ON
    stx BANK_BASE
    sta RAMWRT_OFF
    stz RWBANK
    rts

; A/X = message (zero terminated). Print, wait for a key, quit to ProDOS.
fail:
    sta SRC
    stx SRC+1
    ldy #0
@print:
    lda (SRC),y
    beq @key
    ora #$80
    jsr COUT
    iny
    bne @print
@key:
    jsr RDKEY
    jsr MLI
    .byte MLI_QUIT
    .addr p_quit
    brk

msg_ramworks:
    .byte 13, "THE BILESTOAD NEEDS RAMWORKS MEMORY.", 13
    .byte "SET THE APPLETINI RAM TAB TO 8 MB.", 13, 0
msg_file:
    .byte 13, "CANNOT READ BILESTOAD.SPR", 13, 0

p_prefix:   .byte 1
            .addr path_buffer
p_online:   .byte 2, 0
            .addr path_buffer+1
p_open:     .byte 3
            .addr sprite_name
            .addr IO_BUFFER
            .byte 0
p_read:     .byte 4, 0
            .addr CHUNK
            .word CHUNK_SIZE
            .word 0
p_close:    .byte 1, 0
p_quit:     .byte 4, 0
            .word 0
            .byte 0
            .word 0
sprite_name:
    .byte 13, "BILESTOAD.SPR"

.segment "BSS"
path_buffer: .res 66
bank:        .res 1
dest_page:   .res 1
chunks:      .res 1
