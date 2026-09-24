; Pinball Construction Set for the Appletini -- loads PCS.SPR into the auxiliary language card.
;
; The run-encoded arcade sprites (about 20 KB, docs/DESIGN.md section 2) do
; not fit next to the code, so tools/gen_assets.py puts most of them into
; build/PCS.SPR, a file that sits beside PCS.SYSTEM on the disk. crt0
; calls load_sprites before main(): the file is read through the ProDOS
; MLI in 1 KB pieces into a buffer in main memory and copied into the
; auxiliary language card ($D000-$FFEF with bank 2, $D000-$DFFF with bank
; 1), which ProDOS 8 never uses. The main card stays ProDOS's own, so QUIT
; keeps working.
;
; File format (gen_assets.py): "BSPR", u8 region count, then per region
; u16 load address, u16 length, u8 bank code (SPR_BANK_1 = bank 1,
; SPR_BANK_AUX = auxiliary card), then the region bytes in order.
;
; The file is opened by its plain name (the prefix is the program's
; directory when a launcher or the boot started PCS.SYSTEM); if that
; fails, the directory part of the launched program's pathname at $0280
; is tried in front of it.
;
; First the /RAM volume (slot 3 drive 2, kept in auxiliary memory) is
; disconnected the way the ProDOS 8 Technical Reference describes, because
; the program overwrites that memory (SHR screen and sprites).
;
; On any error a message is put on the text screen (still showing at this
; point) and the program quits to ProDOS after a key press. Without ProDOS
; (no JMP at $BF00: the py65 test machine, which fills the card from
; PCS.SPR itself) the loader does nothing.

.setcpu "65C02"
.include "pcs.inc"
.include "assets.inc"
.import P1STATE
.macpack longbranch

.export load_sprites
.import exit_to_prodos

DEVADR   = $BF10        ; device driver vectors; slot 0 drive 1 = "no device"
RAMSLOT  = $BF26        ; slot 3 drive 2 (/RAM)
DEVCNT   = $BF31        ; number of devices - 1
DEVLST   = $BF32        ; unit numbers
MACHID   = $BF98        ; bits 4-5 = $30: 128K
LAUNCH_PATH = $0280     ; pathname of the launched program (length byte first)


STAGE_SIZE = 1024
MAX_REGIONS = 8
ERR_FORMAT = $F0        ; our own codes, outside ProDOS's range
ERR_SHORT  = $F1
ERR_NOPATH = $F2

.segment "ZEROPAGE"
LD_SRC:  .res 2         ; copy source (main memory)
LD_DST:  .res 2         ; copy destination (auxiliary card)

TEXT_ROW10 = $0528      ; text page 1, rows 10 and 12 (40 bytes each, no screen holes)
TEXT_ROW12 = $0628
HEX_POS    = 36         ; where the error code goes in msg_error

; ---------------------------------------------------------------------------
.segment "RODATA"

pathname:
        .byte   9, "PCS.SPR"
msg_error:
        .byte   "CANNOT LOAD PCS.SPR, PRODOS ERROR $00", 0
msg_key:
        .byte   "PRESS A KEY TO RETURN TO PRODOS.", 0

; ---------------------------------------------------------------------------
.segment "DATA"

open_parms:
        .byte   3
open_path: .word pathname
        .word   IOBUF
open_ref: .byte 0
read_parms:
        .byte   4
read_ref: .byte 0
read_buf: .word 0
read_req: .word 0
read_got: .word 0
close_parms:
        .byte   1
close_ref: .byte 0

; ---------------------------------------------------------------------------
.segment "BSS"

; one piece of the file: the player state tables, unused until a game starts
stage = P1STATE
header:     .res 5              ; "BSPR", region count
regions:    .res MAX_REGIONS*5  ; address, length, bank per region
path2:      .res 65             ; directory of $0280 + "PCS.SPR"
nregions:   .res 1
region:     .res 1
dest:       .res 2              ; where the next piece goes
remain:     .res 2              ; bytes left in this region
piece:      .res 2              ; bytes in this piece
bank:       .res 1

; ---------------------------------------------------------------------------
.segment "CODE"

load_sprites:
        lda     MLI
        cmp     #$4C                    ; no ProDOS (the py65 test machine, which
        jne     @done                   ; preloads the card itself): nothing to do
        jsr     disconnect_ram
        lda     #<pathname
        ldx     #>pathname
        jsr     open_file
        bcc     @opened
        jsr     build_path2
        jcs     @fail
        lda     #<path2
        ldx     #>path2
        jsr     open_file
        jcs     @fail
@opened:
        ; header: magic and region count
        lda     #<header
        ldx     #>header
        ldy     #5
        jsr     read_exact
        jcs     @fail
        ldx     #3
:       lda     header,x
        cmp     magic,x
        jne     @bad
        dex
        bpl     :-
        lda     header+4
        jeq     @bad
        cmp     #MAX_REGIONS+1
        jcs     @bad
        sta     nregions
        ; region table, 5 bytes per region
        asl     a
        asl     a
        adc     header+4
        tay
        lda     #<regions
        ldx     #>regions
        jsr     read_exact
        jcs     @fail
        stz     region
@region:
        lda     region
        asl     a
        asl     a
        adc     region
        tax
        lda     regions,x
        sta     dest
        lda     regions+1,x
        sta     dest+1
        lda     regions+2,x
        sta     remain
        lda     regions+3,x
        sta     remain+1
        lda     regions+4,x
        sta     bank
@piece:
        lda     remain
        ora     remain+1
        jeq     @next_region
        ; piece = min(remain, STAGE_SIZE)
        lda     remain+1
        cmp     #>STAGE_SIZE
        bcc     @small
        lda     #<STAGE_SIZE
        sta     piece
        lda     #>STAGE_SIZE
        sta     piece+1
        jmp     @read
@small:
        lda     remain
        sta     piece
        lda     remain+1
        sta     piece+1
@read:
        lda     #<stage
        sta     read_buf
        lda     #>stage
        sta     read_buf+1
        lda     piece
        sta     read_req
        lda     piece+1
        sta     read_req+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        jcs     @fail
        lda     read_got
        cmp     piece
        jne     @short
        lda     read_got+1
        cmp     piece+1
        jne     @short
        jsr     copy_piece
        clc
        lda     dest
        adc     piece
        sta     dest
        lda     dest+1
        adc     piece+1
        sta     dest+1
        sec
        lda     remain
        sbc     piece
        sta     remain
        lda     remain+1
        sbc     piece+1
        sta     remain+1
        jmp     @piece
@next_region:
        inc     region
        lda     region
        cmp     nregions
        jcc     @region
        jsr     MLI
        .byte   MLI_CLOSE
        .word   close_parms
@done:  rts

@bad:   lda     #ERR_FORMAT
        bra     @fail
@short: lda     #ERR_SHORT
@fail:  jmp     show_error

magic:  .byte   "BSPR"

; ---------------------------------------------------------------------------
; open_file: A/X = pathname (length byte first). C clear and the ref number
; stored for read/close, or C set with the ProDOS error in A.
; ---------------------------------------------------------------------------
open_file:
        sta     open_path
        stx     open_path+1
        jsr     MLI
        .byte   MLI_OPEN
        .word   open_parms
        bcs     @done
        lda     open_ref
        sta     read_ref
        sta     close_ref
        clc
@done:  rts

; ---------------------------------------------------------------------------
; read_exact: read Y bytes (1..255) into the buffer at A/X. C set with the
; error code in A when ProDOS fails or the file ends early.
; ---------------------------------------------------------------------------
read_exact:
        sta     read_buf
        stx     read_buf+1
        sty     read_req
        stz     read_req+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        bcs     @done
        lda     read_got
        cmp     read_req
        bne     @short
        lda     read_got+1
        bne     @short
        clc
        rts
@short: lda     #ERR_SHORT
        sec
@done:  rts

; ---------------------------------------------------------------------------
; build_path2: path2 = directory part of the pathname at $0280 + "PCS.SPR".
; C set when $0280 holds nothing usable (no length, no slash, too long).
; ---------------------------------------------------------------------------
build_path2:
        ldx     LAUNCH_PATH
        beq     @none
        cpx     #65-10
        bcs     @none
        ; find the last slash
@find:  lda     LAUNCH_PATH,x
        cmp     #'/'
        beq     @slash
        dex
        bne     @find
@none:  lda     #ERR_NOPATH
        sec
        rts
@slash: ; copy 1..x (the slash included) then the file name
        stx     path2
        txa
        tax
:       lda     LAUNCH_PATH,x
        and     #$7F
        sta     path2,x
        dex
        bne     :-
        ldx     path2
        ldy     #1
:       lda     pathname,y
        inx
        sta     path2,x
        iny
        cpy     #10
        bne     :-
        stx     path2
        clc
        rts

; ---------------------------------------------------------------------------
; copy_piece: stage[0..piece) -> dest in the auxiliary card, or in RamWorks
; bank 1 for a raw-row region. ALTZP is on while copying into the card, so
; the zero-page pointers are set after the switch (they land in the
; auxiliary zero page) and the return address, pushed on the main stack,
; is used after switching back.
; ---------------------------------------------------------------------------
copy_piece:
        lda     bank
        and     #SPR_BANK_RW1
        beq     @card
        ; RamWorks bank 1, main-range address: RAMWRT routes the writes
        ; there (the zero page and stack are not affected)
        lda     #1
        sta     RAMWORKS
        sta     RAMWRTON
        jsr     @copy
        sta     RAMWRTOFF
        stz     RAMWORKS
        rts
@card:  sta     ALTZPON
        lda     bank
        and     #SPR_BANK_1
        beq     @bank2
        bit     LCBANK1WR
        bit     LCBANK1WR               ; two reads: RAM readable and writable
        bra     @set
@bank2: bit     LCBANK2WR
        bit     LCBANK2WR
@set:   jsr     @copy
        sta     ALTZPOFF
        rts
@copy:  lda     #<stage
        sta     LD_SRC
        lda     #>stage
        sta     LD_SRC+1
        lda     dest
        sta     LD_DST
        lda     dest+1
        sta     LD_DST+1
        ldx     piece+1
        beq     @rest
@page:  ldy     #0
:       lda     (LD_SRC),y
        sta     (LD_DST),y
        iny
        bne     :-
        inc     LD_SRC+1
        inc     LD_DST+1
        dex
        bne     @page
@rest:  ldx     piece
        beq     @done
        ldy     #0
:       lda     (LD_SRC),y
        sta     (LD_DST),y
        iny
        dex
        bne     :-
@done:  rts

; ---------------------------------------------------------------------------
; disconnect_ram: take /RAM (slot 3 drive 2) out of the ProDOS device list
; on a 128K machine, as the ProDOS 8 Technical Reference shows. Its
; auxiliary memory belongs to the program from here on.
; ---------------------------------------------------------------------------
disconnect_ram:
        lda     MACHID
        and     #$30
        cmp     #$30
        bne     @done                   ; no auxiliary memory: no /RAM
        lda     RAMSLOT
        cmp     DEVADR
        bne     @connected
        lda     RAMSLOT+1
        cmp     DEVADR+1
        beq     @done                   ; already disconnected
@connected:
        ldy     DEVCNT
@find:  lda     DEVLST,y
        and     #$F3                    ; drop the id bits
        cmp     #$B3                    ; slot 3, drive 2
        beq     @found
        dey
        bpl     @find
        bra     @done
@found: ; close the gap in the list
:       cpy     DEVCNT
        beq     :+
        lda     DEVLST+1,y
        sta     DEVLST,y
        iny
        bra     :-
:       lda     #0
        sta     DEVLST,y
        dec     DEVCNT
        lda     DEVADR
        sta     RAMSLOT
        lda     DEVADR+1
        sta     RAMSLOT+1
@done:  rts

; ---------------------------------------------------------------------------
; show_error: A = error code. Two lines on the text screen, wait for a key,
; quit to ProDOS.
; ---------------------------------------------------------------------------
show_error:
        pha
        ldx     #0
:       lda     msg_error,x
        beq     :+
        ora     #$80
        sta     TEXT_ROW10,x
        inx
        bne     :-
:       ldx     #0
:       lda     msg_key,x
        beq     :+
        ora     #$80
        sta     TEXT_ROW12,x
        inx
        bne     :-
:       pla
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     hex_digit
        sta     TEXT_ROW10+HEX_POS
        pla
        and     #$0F
        jsr     hex_digit
        sta     TEXT_ROW10+HEX_POS+1
        sta     KBDSTRB
:       lda     KBD
        bpl     :-
        sta     KBDSTRB
        jmp     exit_to_prodos

hex_digit:
        cmp     #10
        bcc     :+
        adc     #6                      ; carry set: +7, '9'+1 -> 'A'
:       adc     #'0'
        ora     #$80
        rts
