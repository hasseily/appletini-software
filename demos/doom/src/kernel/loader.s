; Doom for the Appletini -- DOOM.SYSTEM, the ProDOS loader (docs/DESIGN.md
; sections 4 and 8).
;
; ProDOS boots, loads this file at $2000 and jumps here. ProDOS is used for
; nothing else: the loader reads every file of the game into its final
; place, then takes the whole machine and starts the kernel. In order:
;
;   1. 40-column text, a "LOADING" line; /RAM (slot 3 drive 2, which keeps
;      its files in aux bank 0) is disconnected as the ProDOS 8 Technical
;      Reference shows.
;   2. The RamWorks size: each bank 127..0 gets its number and its
;      complement at aux PROBE; reading them back from bank 0 up (through a
;      stub in page 1: RAMRD moves instruction fetches) finds the first
;      bank that is missing or aliased. Fewer than MIN_BANKS (64 = 4 MB)
;      stops here.
;   3. The data files: the volume directory (the current prefix) is read
;      and every BIN file with aux type $0000 is loaded, in directory
;      order. Each is a bank file: a header listing its segments, then
;      their bytes (format below). Each segment is read through the MLI
;      into the staging buffer in main memory, STAGE_SIZE bytes at a time,
;      and copied into its bank with RAMWRT on. (The images have aux types
;      $0200 and $D000 and are skipped here; tools/build_disk.py writes
;      those types.) Nothing about the data is built into the loader.
;   4. The images: GAME.BIN into RamWorks bank 1 at $0200 (its final
;      place); RENDER.BIN into aux bank 0 at $0200 (the same addresses it
;      will have in main memory; aux bank 0's SHR area is not in use yet);
;      LC.BIN (16 KB) straight into main $6000-$9FFF.
;   5. The install, with interrupts off and ProDOS no longer needed: the
;      language card is written from $6000-$9FFF (bank 2 $D000-$FFFF,
;      bank 1 $D000-$DFFF); then a routine copied to $0100 (page 1: it
;      runs with RAMRD on) copies aux bank 0 $0200.. over main memory page
;      for page -- over this loader and the ProDOS global page -- and
;      jumps to kernel_start in the language card with A = the bank count.
;
; Data file format (tools/wad2a2.py writes them, DESIGN.md section 6;
; tools/make_standin.py too):
;   +0  4    magic "A2DM"
;   +4  1    format version, 1
;   +5  1    n, the number of segments (1..MAX_SEGS)
;   +6  2    zero
;   +8  5n   per segment: bank (2..banks-1), address (u16, >= $0200),
;            length (u16, >= 1, address + length <= $C000)
;   zero padding to 256 bytes, then the n segments' bytes in entry order.
;
; Paths: the prefix (GET_PREFIX; ProDOS sets it to the boot volume), or,
; when there is none, the directory part of the launched program's
; pathname at $0280; every file is opened as prefix + name.
;
; On any error a message is put on the text screen, the program waits for
; a key and quits to ProDOS (which is still intact before step 5).
;
; Main memory while loading: $1400-$1BFF the volume directory (4 blocks),
; $1C00-$1FFF the ProDOS file buffer, $2000-$3FFF this loader, $6000-$9FFF the LC image, $A000-$BDFF the staging
; buffer. Zero page: LZ ($60-$6F), outside what the monitor and the MLI use.

.include "kernel.inc"
.macpack longbranch

CATBUF      = $1400             ; the volume directory, up to CAT_BLOCKS blocks
CAT_BLOCKS  = 4
IOBUF       = $1C00             ; 1 KB, page aligned
LC_STAGE    = $6000             ; LC.BIN: $6000-$8FFF bank 2, $9000-$9FFF bank 1
LC_SIZE     = $4000
STAGE       = $A000
STAGE_SIZE  = $1E00             ; 15 blocks
RENDER_MAX  = $8B80 - $0200     ; RENDER.BIN ends below the view buffer
GAME_MAX    = $B800 - $0200     ; GAME.BIN ends below the C stack
MAX_SEGS    = 49
HEADER_SIZE = 256
SEG_FIRST   = 8                 ; the first segment entry
SEG_SIZE    = 5
PROBE       = $0C00             ; the bank-count probe bytes (any bank)
INSTALL     = $0100             ; the installer's run address (page 1)
; IADDR label: where a label of the installer image is once copied to INSTALL
.define IADDR INSTALL - installer_image +

DEVADR      = $BF10             ; device driver vectors; slot 0 drive 1 = "no device"
RAMSLOT     = $BF26             ; slot 3 drive 2 (/RAM)
DEVCNT      = $BF31
DEVLST      = $BF32
MACHID      = $BF98
LAUNCH_PATH = $0280
POWERUP     = $03F4

ERR_FORMAT  = $F0               ; not a bank file / bad header
ERR_SHORT   = $F1               ; the file ended early
ERR_BANKS   = $F2               ; not enough RamWorks memory
ERR_SEGMENT = $F3               ; a segment outside $0200-$BFFF
ERR_SIZE    = $F4               ; an image too large for its space
ERR_NOMLI   = $F5               ; not started by ProDOS
ERR_NOPATH  = $F6               ; no prefix and nothing at $0280
MLI_GET_PREFIX = $C7
ENTRY_LEN   = $27               ; directory entries
ENTRIES     = $0D               ; per block
FILE_BIN    = $06

; loader zero page
LZ          = $60
lz_src      = LZ+0              ; 2 copy source
lz_dst      = LZ+2              ; 2 copy destination
lz_pages    = LZ+4              ; 1 page count
lz_count    = LZ+5              ; 1 bytes after the whole pages
lz_name     = LZ+6              ; 2 the current file name (length byte first)
lz_seg      = LZ+8              ; 1 current segment
lz_bank     = LZ+9              ; 1 current segment's bank
lz_addr     = LZ+10             ; 2 where the next piece goes
lz_remain   = LZ+12             ; 2 bytes left in the segment
lz_piece    = LZ+14             ; 2 bytes in this piece
lz_entry    = LZ+16             ; 2 the directory entry being looked at
lz_left     = LZ+18             ; 1 entries left in this block
lz_blocks   = LZ+19             ; 1 directory blocks left

HEX_POS     = 20                ; where the code goes in msg_error
TEXT_ROW10  = $0528             ; text page 1 rows 10 and 12 (no screen holes)
TEXT_ROW12  = $0628

.segment "LDRCODE"

loader_start:
        cld
        ldx     #$FF
        txs
        stz     POWERUP                 ; CTRL-RESET restarts the machine
        stz     TWSPEED                 ; the selected speed (TURBO)
        sta     RAMRDOFF
        sta     RAMWRTOFF
        sta     ALTZPOFF
        sta     $C000                   ; 80STORE off
        sta     $C00C                   ; 40 columns
        sta     TEXTON
        sta     $C054                   ; page 1
        lda     #<msg_loading
        ldx     #>msg_loading
        jsr     show_row10
        lda     MLI
        cmp     #$4C
        beq     :+
        lda     #ERR_NOMLI
        jmp     fail_hang
:       jsr     disconnect_ram
        jsr     count_banks
        sta     nbanks
        cmp     #MIN_BANKS
        bcs     :+
        lda     #ERR_BANKS
        jmp     fail
:       jsr     get_prefix
        jcs     fail
        jsr     read_catalog
        jcs     fail

        ; --- the data files: BIN, aux $0000, in directory order ---
        lda     #<(CATBUF+4+ENTRY_LEN)  ; block 0 starts with the volume header
        sta     lz_entry
        lda     #>(CATBUF+4+ENTRY_LEN)
        sta     lz_entry+1
        lda     #ENTRIES-1
        sta     lz_left
@entry: lda     lz_left
        bne     @look
        ; next block
        dec     lz_blocks
        beq     @images
        lda     lz_entry+1              ; the next block's first entry: the
        and     #$FE                    ; blocks are 512-byte aligned from CATBUF
        clc
        adc     #2
        sta     lz_entry+1
        lda     #4
        sta     lz_entry
        lda     #ENTRIES
        sta     lz_left
@look:  lda     (lz_entry)              ; storage type and name length
        and     #$F0
        beq     @skip                   ; a free entry
        cmp     #$40
        bcs     @skip                   ; not a seedling/sapling/tree file
        ldy     #16
        lda     (lz_entry),y
        cmp     #FILE_BIN
        bne     @skip
        ldy     #31
        lda     (lz_entry),y
        iny
        ora     (lz_entry),y
        bne     @skip                   ; an image ($0200, $D000)
        ; fname = the entry's name, length first
        lda     (lz_entry)
        and     #$0F
        sta     fname
        tay
:       lda     (lz_entry),y
        sta     fname,y
        dey
        bne     :-
        lda     #<fname
        sta     lz_name
        lda     #>fname
        sta     lz_name+1
        jsr     load_bank_file
        jcs     fail
@skip:  clc
        lda     lz_entry
        adc     #ENTRY_LEN
        sta     lz_entry
        bcc     :+
        inc     lz_entry+1
:       dec     lz_left
        bra     @entry

        ; --- the images ---
@images:
        lda     #<name_game
        ldx     #>name_game
        ldy     #GAME_BANK
        jsr     load_image
        jcs     fail
        lda     #<name_render
        ldx     #>name_render
        ldy     #0
        jsr     load_image
        jcs     fail
        jsr     load_lc
        jcs     fail
        jmp     install

; ---------------------------------------------------------------------------
; load_bank_file: the bank file named at lz_name. C set with the error in A.
; ---------------------------------------------------------------------------
load_bank_file:
        lda     lz_name
        ldx     lz_name+1
        jsr     open_file
        bcs     @done
        ; the header
        lda     #<header
        ldx     #>header
        ldy     #0                      ; 256 bytes
        jsr     read_exact
        bcs     @close
        ldx     #3
:       lda     header,x
        cmp     magic,x
        bne     @bad
        dex
        bpl     :-
        lda     header+4
        cmp     #1
        bne     @bad
        lda     header+5
        beq     @bad
        cmp     #MAX_SEGS+1
        bcs     @bad
        sta     nsegs
        stz     lz_seg
        lda     #SEG_FIRST
        sta     seg_off
@seg:   ldx     seg_off
        lda     header,x
        sta     lz_bank
        lda     header+1,x
        sta     lz_addr
        lda     header+2,x
        sta     lz_addr+1
        lda     header+3,x
        sta     lz_remain
        lda     header+4,x
        sta     lz_remain+1
        txa
        clc
        adc     #SEG_SIZE
        sta     seg_off
        ; bank 2..nbanks-1
        lda     lz_bank
        cmp     #2
        bcc     @badseg
        cmp     nbanks
        bcs     @nomem
        jsr     check_segment
        bcs     @close
        jsr     copy_segment
        bcs     @close
        inc     lz_seg
        lda     lz_seg
        cmp     nsegs
        bne     @seg
        jsr     close_file
        clc
@done:  rts
@bad:   lda     #ERR_FORMAT
        bra     @err
@badseg:
        lda     #ERR_SEGMENT
        bra     @err
@nomem: lda     #ERR_BANKS
@err:   sec
@close: pha                             ; keep the error, close, fail
        jsr     close_file
        pla
        sec
        rts

; check_segment: length >= 1, address >= $0200, address + length <= $C000.
; C set with ERR_SEGMENT in A when not.
check_segment:
        lda     lz_remain
        ora     lz_remain+1
        beq     @bad
        lda     lz_addr+1
        cmp     #$02
        bcc     @bad
        clc
        lda     lz_addr
        adc     lz_remain
        tax
        lda     lz_addr+1
        adc     lz_remain+1
        bcs     @bad                    ; past $FFFF
        cmp     #$C0
        bcc     @ok
        bne     @bad
        cpx     #0                      ; exactly $C000 is the end
        bne     @bad
@ok:    clc
        rts
@bad:   lda     #ERR_SEGMENT
        sec
        rts

; ---------------------------------------------------------------------------
; copy_segment: lz_remain bytes of the open file to lz_bank:lz_addr, through
; the staging buffer. C set with the error in A.
; ---------------------------------------------------------------------------
copy_segment:
@piece: lda     lz_remain
        ora     lz_remain+1
        jeq     @done
        ; piece = min(remain, STAGE_SIZE)
        lda     lz_remain
        cmp     #<STAGE_SIZE
        lda     lz_remain+1
        sbc     #>STAGE_SIZE
        bcc     @small
        lda     #<STAGE_SIZE
        sta     lz_piece
        lda     #>STAGE_SIZE
        sta     lz_piece+1
        bra     @read
@small: lda     lz_remain
        sta     lz_piece
        lda     lz_remain+1
        sta     lz_piece+1
@read:  lda     #<STAGE
        sta     read_buf
        lda     #>STAGE
        sta     read_buf+1
        lda     lz_piece
        sta     read_req
        lda     lz_piece+1
        sta     read_req+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        bcs     @fail
        lda     read_got
        cmp     lz_piece
        bne     @short
        lda     read_got+1
        cmp     lz_piece+1
        bne     @short
        ; stage -> bank: only zero page is written while RAMWRT is on
        lda     #<STAGE
        sta     lz_src
        lda     #>STAGE
        sta     lz_src+1
        lda     lz_addr
        sta     lz_dst
        lda     lz_addr+1
        sta     lz_dst+1
        lda     lz_piece+1
        sta     lz_pages
        lda     lz_piece
        sta     lz_count
        lda     lz_bank
        sta     RAMWORKS
        sta     RAMWRTON
        jsr     copy_bytes
        sta     RAMWRTOFF
        ; advance
        clc
        lda     lz_addr
        adc     lz_piece
        sta     lz_addr
        lda     lz_addr+1
        adc     lz_piece+1
        sta     lz_addr+1
        sec
        lda     lz_remain
        sbc     lz_piece
        sta     lz_remain
        lda     lz_remain+1
        sbc     lz_piece+1
        sta     lz_remain+1
        jmp     @piece
@done:  clc
        rts
@short: lda     #ERR_SHORT
@fail:  sec
        rts

; copy_bytes: lz_pages pages then lz_count bytes, lz_src -> lz_dst. Writes
; nothing but the zero page (it runs with RAMWRT on).
copy_bytes:
        ldy     #0
        ldx     lz_pages
        beq     @rest
@page:  lda     (lz_src),y
        sta     (lz_dst),y
        iny
        bne     @page
        inc     lz_src+1
        inc     lz_dst+1
        dex
        bne     @page
@rest:  ldx     lz_count
        beq     @done
@byte:  lda     (lz_src),y
        sta     (lz_dst),y
        iny
        dex
        bne     @byte
@done:  rts

; ---------------------------------------------------------------------------
; load_image: the whole file named at A/X into bank Y at $0200 (GAME.BIN:
; bank 1, at most GAME_MAX bytes; RENDER.BIN: aux bank 0, RENDER_MAX).
; C set with the error in A.
; ---------------------------------------------------------------------------
load_image:
        sta     lz_name
        stx     lz_name+1
        sty     lz_bank
        jsr     open_file
        bcs     @done
        jsr     MLI
        .byte   MLI_GET_EOF
        .word   eof_parms
        bcs     @close
        lda     eof_len+2
        bne     @big
        lda     eof_len
        sta     lz_remain
        ldx     eof_len+1
        stx     lz_remain+1
        ldy     lz_bank
        bne     @game
        cmp     #<(RENDER_MAX+1)
        txa
        sbc     #>(RENDER_MAX+1)
        bcs     @big
        bra     @go
@game:  cmp     #<(GAME_MAX+1)
        txa
        sbc     #>(GAME_MAX+1)
        bcs     @big
@go:    lda     #<$0200
        sta     lz_addr
        lda     #>$0200
        sta     lz_addr+1
        lda     lz_remain+1
        sta     image_pages             ; RENDER: pages the installer copies
        inc     image_pages
        jsr     check_segment
        bcs     @close
        jsr     copy_segment
        bcs     @close
        jsr     close_file
        clc
@done:  rts
@big:   lda     #ERR_SIZE
        sec
@close: pha
        jsr     close_file
        pla
        sec
        rts

; load_lc: LC.BIN, exactly LC_SIZE bytes, into main LC_STAGE.
load_lc:
        lda     #<name_lc
        sta     lz_name
        ldx     #>name_lc
        stx     lz_name+1
        jsr     open_file
        bcs     @done
        lda     #<LC_STAGE
        sta     read_buf
        lda     #>LC_STAGE
        sta     read_buf+1
        lda     #<LC_SIZE
        sta     read_req
        lda     #>LC_SIZE
        sta     read_req+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        bcs     @close
        lda     read_got
        bne     @short
        lda     read_got+1
        cmp     #>LC_SIZE
        bne     @short
        jsr     close_file
        clc
@done:  rts
@short: lda     #ERR_SHORT
@close: pha
        jsr     close_file
        pla
        sec
        rts

; ---------------------------------------------------------------------------
; open_file: the file named at A/X (length byte first): the plain name,
; then prefix + name. C clear and the ref number set for read/close, or C
; set with the ProDOS error in A.
; ---------------------------------------------------------------------------
open_file:
        sta     lz_src
        stx     lz_src+1
        jsr     show_name
        ; path2 = prefix + name
        ldx     #0
:       cpx     prefix
        beq     :+
        lda     prefix+1,x
        sta     path2+1,x
        inx
        bra     :-
:       ldy     #0
        lda     (lz_src),y              ; the name's length
        sta     lz_count
:       cpy     lz_count
        beq     :+
        iny
        lda     (lz_src),y
        sta     path2+1,x
        inx
        bra     :-
:       stx     path2
        lda     #<path2
        ldx     #>path2
open_path2:
        sta     open_path
        stx     open_path+1
        jsr     MLI
        .byte   MLI_OPEN
        .word   open_parms
        bcs     @fail
        lda     open_ref
        sta     read_ref
        sta     close_ref
        sta     eof_ref
        clc
        rts
@fail:  sec
        rts

close_file:
        jsr     MLI
        .byte   MLI_CLOSE
        .word   close_parms
        rts

; read_exact: Y bytes (1..255, 0 = 256) into A/X. C set with the error in A.
read_exact:
        sta     read_buf
        stx     read_buf+1
        sty     read_req
        stz     read_req+1
        cpy     #0
        bne     :+
        inc     read_req+1
:       jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        bcs     @done
        lda     read_got
        cmp     read_req
        bne     @short
        lda     read_got+1
        cmp     read_req+1
        bne     @short
        clc
        rts
@short: lda     #ERR_SHORT
        sec
@done:  rts

; get_prefix: prefix = the current prefix ("/DOOM/"), else the directory
; part of $0280, always ending with a slash. C set with ERR_NOPATH.
get_prefix:
        jsr     MLI
        .byte   MLI_GET_PREFIX
        .word   prefix_parms
        bcs     @launch
        lda     prefix
        bne     @done
@launch:
        stz     prefix
        ldx     LAUNCH_PATH
        beq     @none
        cpx     #48
        bcs     @none
@find:  lda     LAUNCH_PATH,x
        and     #$7F
        cmp     #'/'
        beq     @slash
        dex
        bne     @find
@none:  lda     #ERR_NOPATH
        sec
        rts
@slash: stx     prefix
:       lda     LAUNCH_PATH,x
        and     #$7F
        sta     prefix,x
        dex
        bne     :-
@done:  clc
        rts

; read_catalog: the volume directory (the prefix without its last slash)
; into CATBUF, up to CAT_BLOCKS blocks; lz_blocks = the blocks read.
read_catalog:
        ldx     prefix
:       lda     prefix,x
        sta     path2,x
        dex
        bpl     :-
        dec     path2                   ; drop the trailing slash
        lda     #<path2
        sta     lz_src
        lda     #>path2
        sta     lz_src+1
        jsr     show_name
        lda     #<path2
        ldx     #>path2
        jsr     open_path2
        bcs     @done
        lda     #<CATBUF
        sta     read_buf
        lda     #>CATBUF
        sta     read_buf+1
        lda     #<(CAT_BLOCKS*512)
        sta     read_req
        lda     #>(CAT_BLOCKS*512)
        sta     read_req+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_parms
        bcs     @close
        lda     read_got+1
        lsr     a                       ; 512-byte blocks
        beq     @short
        sta     lz_blocks
        jsr     close_file
        clc
@done:  rts
@short: lda     #ERR_SHORT
@close: pha
        jsr     close_file
        pla
        sec
        rts

; ---------------------------------------------------------------------------
; count_banks: A = the number of RamWorks banks (1..128) that hold their
; own bytes. Writes run from here (RAMWRT only moves writes); the reads go
; through a stub in page 1 because RAMRD moves instruction fetches too.
; ---------------------------------------------------------------------------
count_banks:
        ldx     #probe_end-probe_stub-1
:       lda     probe_stub,x
        sta     INSTALL,x
        dex
        bpl     :-
        ldx     #127
@write: stx     RAMWORKS
        sta     RAMWRTON
        stx     PROBE
        txa
        eor     #$FF
        sta     PROBE+1
        sta     RAMWRTOFF
        dex
        bpl     @write
        ldy     #0
@read:  tya
        jsr     INSTALL                 ; A = bank's PROBE, X = PROBE+1
        sta     lz_count
        cpy     lz_count
        bne     @end
        tya
        eor     #$FF
        sta     lz_count
        cpx     lz_count
        bne     @end
        iny
        cpy     #128
        bne     @read
@end:   stz     RAMWORKS
        tya
        rts

probe_stub:
        sta     RAMWORKS
        sta     RAMRDON
        lda     PROBE
        ldx     PROBE+1
        sta     RAMRDOFF
        rts
probe_end:

; ---------------------------------------------------------------------------
; disconnect_ram: take /RAM (slot 3 drive 2) out of the device list (the
; ProDOS 8 Technical Reference's method). From the PCS port's loader.
; ---------------------------------------------------------------------------
disconnect_ram:
        lda     MACHID
        and     #$30
        cmp     #$30
        bne     @done
        lda     RAMSLOT
        cmp     DEVADR
        bne     @connected
        lda     RAMSLOT+1
        cmp     DEVADR+1
        beq     @done
@connected:
        ldy     DEVCNT
@find:  lda     DEVLST,y
        and     #$F3
        cmp     #$B3
        beq     @found
        dey
        bpl     @find
        bra     @done
@found:
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
; install: no way back to ProDOS from here.
; ---------------------------------------------------------------------------
install:
        sei
        ; the language card from LC_STAGE: bank 1 first, then bank 2 (which
        ; stays selected, read and write enabled, for the kernel)
        bit     LCBANK1WR
        bit     LCBANK1WR
        lda     #>(LC_STAGE+$3000)
        ldy     #16
        jsr     copy_to_lc
        bit     LCBANK2WR
        bit     LCBANK2WR
        lda     #>LC_STAGE
        ldy     #48
        jsr     copy_to_lc
        ; the installer into page 1, with its page count and the bank count
        ldx     #installer_end-installer_image-1
:       lda     installer_image,x
        sta     INSTALL,x
        dex
        bpl     :-
        lda     image_pages
        sta     IADDR inst_pages+1
        lda     nbanks
        sta     IADDR inst_banks+1
        jmp     INSTALL

; copy_to_lc: Y pages from page A of main memory to $D000.. of the card.
copy_to_lc:
        sta     lz_src+1
        stz     lz_src
        stz     lz_dst
        lda     #$D0
        sta     lz_dst+1
        tya
        tax
        ldy     #0
:       lda     (lz_src),y
        sta     (lz_dst),y
        iny
        bne     :-
        inc     lz_src+1
        inc     lz_dst+1
        dex
        bne     :-
        rts

; The installer, run at INSTALL ($0100) with interrupts off: aux bank 0
; $0200.. -> main $0200.. page by page (RAMRD on reads aux, RAMWRT off
; writes main), then kernel_start with A = the bank count. Addresses in it
; are relative to INSTALL.
installer_image:
        lda     #0
        sta     RAMWORKS
        sta     RAMRDON
inst_pages:
        ldx     #0                      ; patched: RENDER.BIN pages
        ldy     #0
inst_loop:
        lda     $0200,y                 ; both page bytes advance below
        sta     $0200,y
        iny
        bne     inst_loop
        inc     IADDR inst_loop+2
        inc     IADDR inst_loop+5
        dex
        bne     inst_loop
        sta     RAMRDOFF
inst_banks:
        lda     #0                      ; patched: the bank count
        jmp     kernel_start
installer_end:

; ---------------------------------------------------------------------------
; messages
; ---------------------------------------------------------------------------
show_row10:
        sta     lz_src
        stx     lz_src+1
        ldy     #0
:       lda     (lz_src),y
        beq     :+
        ora     #$80
        sta     TEXT_ROW10,y
        iny
        bra     :-
:       rts

; show_name: the file name at lz_src (length first) after "LOADING " on row 12
show_name:
        ldy     #39
        lda     #$A0
:       sta     TEXT_ROW12,y
        dey
        bpl     :-
        lda     (lz_src)
        beq     @done
        cmp     #31
        bcc     :+
        lda     #31
:       tax
        ldy     #1
:       lda     (lz_src),y
        ora     #$80
        sta     TEXT_ROW12-1,y
        iny
        dex
        bne     :-
@done:  rts

; fail: A = error code. Message, wait for a key, quit to ProDOS.
fail:   jsr     show_error
        sta     KBDSTRB
fail_wait:
        lda     KBD
        bpl     fail_wait
        sta     KBDSTRB
quit:   jsr     MLI
        .byte   MLI_QUIT
        .word   quit_parms
        bra     quit

fail_hang:
        jsr     show_error
:       bra     :-

show_error:
        pha
        lda     #<msg_error
        ldx     #>msg_error
        jsr     show_row10
        pla
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     hex_digit
        sta     TEXT_ROW10+HEX_POS
        pla
        pha
        and     #$0F
        jsr     hex_digit
        sta     TEXT_ROW10+HEX_POS+1
        pla
        rts

hex_digit:
        cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0'
        ora     #$80
        rts

; ---------------------------------------------------------------------------
; data
; ---------------------------------------------------------------------------
msg_loading:
        .byte   "DOOM FOR THE APPLETINI: LOADING        ", 0
msg_error:
        .byte   "CANNOT LOAD, ERROR $00 (PRESS A KEY)   ", 0

magic:  .byte   "A2DM"
prefix_parms:
        .byte   1
        .word   prefix
name_render:
        .byte   10, "RENDER.BIN"
name_lc:
        .byte   6, "LC.BIN"
name_game:
        .byte   8, "GAME.BIN"

open_parms:
        .byte   3
open_path:
        .word   0
        .word   IOBUF
open_ref:
        .byte   0
read_parms:
        .byte   4
read_ref:
        .byte   0
read_buf:
        .word   0
read_req:
        .word   0
read_got:
        .word   0
close_parms:
        .byte   1
close_ref:
        .byte   0
eof_parms:
        .byte   2
eof_ref:
        .byte   0
eof_len:
        .byte   0, 0, 0
quit_parms:
        .byte   4, 0
        .word   0
        .byte   0
        .word   0

nbanks:     .byte   0
nsegs:      .byte   0
image_pages: .byte  0
seg_off:    .byte   0
header:     .res    HEADER_SIZE
prefix:     .res    49
path2:      .res    65
fname:      .res    16
