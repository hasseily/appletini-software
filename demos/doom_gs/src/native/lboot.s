; lboot.s: LEVELS.SYSTEM, the level store's boot load and the level
; loads on the card, for the owner to run at milestone 12 (milestone 9,
; stage B; docs/LEVELS.md 1.7, 5.4). tools/native/ldisk.py builds the
; disk and runs it on a2vm end to end (--check). Milestone 11's
; DOOM.SYSTEM takes the same boot.
;
; Boot (at $2000, under ProDOS):
;   * the RamWorks probe: banks 1-126 must all be there (8 MB, bank 127
;     excluded: NATIVE.md 15.1 row 8): each bank's number written to its
;     $0200, then each read back; a missing bank stops with a message;
;   * CATALOG, then each bank file it names (demos/doom/src/kernel/
;     loader.s's format, lstore.bank_file: "A2DM", version 1, a segment
;     count, 5 bytes a segment: bank, address, length; zero padding to
;     256 bytes; the bytes): each segment read through the MLI into a
;     main staging buffer, 8 KB at a time, and copied into its bank (CPU
;     copy with RAMWRT and $C073): the store (TEXELS, PATCHES, MAPS,
;     TABLES) and the load phase's image (CODE: bank LCODE at W's
;     addresses);
;   * the persistent globals main $0300-$03EF zeroed (LV_VARMAP 0: the
;     stores canonical);
;   * ProDOS is given up: the card image that follows this code in the
;     file ($2800: main card bank 1 $D000-$DFFF, bank 2 $D000-$DFFF,
;     $E000-$FFFF) goes into the language card, the catalog after the
;     runner, and the runner starts.
;
; The runner (the card's $E000 part): the mouse card's VBL interrupt (the
; clock), the memory API's probe (COPY, FILL, PRIVATE), the load phase's
; image into W (far_pload from LCODE), then each entry of the catalog's
; sequence, its VBLs counted: with a pre-state (stage C) that test
; pre-state (bank PRE_BANK, the file PRESTATE.1: the game globals block
; and the random indexes of the E dump of the map's tour-sk2 setup) and
; nl_setup, then the CRC-32 (zlib's) of the map's window ranges and of
; its setup state's ranges (bank CRC_BANK, the file CRCLIST.1, which
; also holds each entry's expected CRCs); without one (stage B) nl_load;
; run_loaded after each (where a2vm's harness takes its snapshot); at the
; end (run_done) the text screen shows each entry's map, VBLs and CRCs
; with OK or BAD, and "SETUPS OK" or "CRCS DIFFER" (the text page is main
; $0400-$07FF, where the loads put colormap levels 32 and 33: the table
; overwrites them after the CRCs, a test disk's licence; the CRC ranges
; leave out the page's slot holes, which firmware may write). A load's
; stop (BRK) shows its LV_STATUS.
;
; The IRQ handler follows the game's contract (docs/MEMORY_MAP.md rule 2):
; zero page $D8-$FF, the stack, $E000-$FFFF and the mouse card only.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"

        .include "lgame.inc"

        .import far_pload, nl_load, nl_setup
        .import __LOADW_RUN__, __LOADW_SIZE__
        .export boot, run_start, run_loaded, run_done, run_crash
        .export rn_results, rn_k, catalog, rn_crcs, rn_ok

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
LCBANK2         = $C083
LCBANK1         = $C08B
MOUSE_STATUS    = $C0A0
MOUSE_MODE      = $C0AE
MOUSE_ACK       = $C0AF
MOUSE_ROM       = $C200
MODE_VBL        = $09
ACK_ALL         = $03

SP_DATA         = $CFF0
SP_CTRL         = $CFF1
SP_POP          = $CFF2
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F

LCIMAGE         = $2800         ; the card image, after the boot code
LCIMAGE_SIZE    = $4000
IOBUF           = $6800         ; ProDOS's buffer for the open file
CATBUF          = $6C00         ; the catalog while booting
CAT_MAX         = $0100
HDRBUF          = $6D00         ; a bank file's header
DATABUF         = $7C00         ; file data, 8 KB at a time
DATAMAX         = $2000
PROBE           = $0100         ; the probe's read, in page 1 (near with
                                ;   RAMRD on)
BANKS           = 126           ; the banks the game needs
LIM_FIRST       = $60           ; the load image: W from $6000

; CATALOG (tools/native/ldisk.py): +0 the bank files, +1 the entries;
; +16 the files' names (16 bytes each: length, name); then each entry's
; map, then each entry's pre-state ($FF: a load alone)
C_FILES         = 0
C_MAPS          = 1
C_NAMES         = 16
MAX_MAPS        = 40
; CRCLIST (bank CRC_BANK, tools/native/ldisk.py): at CL_LISTS each map's
; two range lists (window, state: their addresses in the bank, 4 bytes a
; map from map 1); at CL_EXPECT each entry's expected CRCs (window,
; state: 8 bytes); a list: its range count (a word), then 6 bytes a
; range: kind (0 main, 1 RamWorks), bank, address, length
CRC_BANK        = 4
CL_LISTS        = $0200
CL_EXPECT       = $0240
CL_RANGE        = 6

; zero page: the boot's and the runner's (overlay 1, before the loads);
; the IRQ's VBL count ($D8-$FF)
vbl             = $D8
bsrc            = $18
bdst            = $1A
blen            = $1C
tmp             = $1E           ; (4)
line            = $22
col             = $24
wcount          = $25
num             = $26           ; (2)
bnk             = $28           ; the probe's bank
segs            = $29           ; a bank file's segments left
sptr            = $2A           ; its next segment's entry
crcz            = $2C           ; the CRC being made (4)
rptr            = $30           ; a range list's place (2)
rcount          = $32           ; its ranges left (2)

; ===========================================================================
; boot: runs at $2000 under ProDOS
; ===========================================================================
.segment "BOOT"
boot:   sei
        cld
        ldx #$FF
        txs
        sta TEXTON
        sta MIXEDOFF
        sta PAGE1
        sta COL80OFF
        ldx #0
        lda #' ' | $80
:       sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        inx
        bne :-
:       lda msg_load,x
        beq :+
        sta $0400,x
        inx
        bra :-
:       stx bcol
        jsr probe               ; 126 banks
        lda #<path_catalog
        ldx #>path_catalog
        jsr open
        lda #<CATBUF
        sta rd_buf
        lda #>CATBUF
        sta rd_buf+1
        lda #<CAT_MAX
        sta rd_count
        lda #>CAT_MAX
        sta rd_count+1
        jsr read_any
        jsr close
        stz bfile
@file:  lda bfile               ; each bank file
        cmp CATBUF + C_FILES
        bcc :+
        jmp @loaded
:       lda #'.' | $80
        ldx bcol
        sta $0400,x
        inc bcol
        lda bfile               ; its name: C_NAMES + 16 k
        asl a
        asl a
        asl a
        asl a
        clc
        adc #<(CATBUF + C_NAMES)
        tay
        lda #>(CATBUF + C_NAMES)
        adc #0
        tax
        tya
        jsr open
        lda #<HDRBUF            ; its header: "A2DM", 1, the segments
        sta rd_buf
        lda #>HDRBUF
        sta rd_buf+1
        stz rd_count
        lda #1
        sta rd_count+1
        jsr read
        ldx #3
:       lda HDRBUF,x
        cmp magic,x
        bne @bad
        dex
        bpl :-
        lda HDRBUF+4
        cmp #1
        bne @bad
        lda HDRBUF+5
        sta segs
        lda #<(HDRBUF + 8)
        sta sptr
        lda #>(HDRBUF + 8)
        sta sptr+1
@seg:   lda segs                ; each segment: bank, address, length
        beq @end
        ldy #0
        lda (sptr),y
        beq @bad
        cmp #BANKS + 1
        bcs @bad
        sta hdr
        iny
        lda (sptr),y
        sta hdr+1
        iny
        lda (sptr),y
        sta hdr+2
        iny
        lda (sptr),y
        sta hdr+3
        iny
        lda (sptr),y
        sta hdr+4
        jsr segment
        clc
        lda sptr
        adc #5
        sta sptr
        dec segs
        bra @seg
@end:   jsr close
        inc bfile
        jmp @file
@bad:   lda #$FE                ; (ours: not a bank file)
        jmp boot_fail
@loaded:
        ldx #0                  ; the persistent globals 0
:       stz $0300,x
        inx
        cpx #$F0
        bcc :-
        bit LCBANK1             ; ProDOS goes: the card image, bank 1,
        bit LCBANK1             ;   then bank 2 and $E000-$FFFF
        lda #<LCIMAGE
        sta bsrc
        lda #>LCIMAGE
        sta bsrc+1
        stz bdst
        lda #$D0
        sta bdst+1
        stz blen
        lda #$10
        sta blen+1
        jsr copy
        bit LCBANK2
        bit LCBANK2
        lda #<(LCIMAGE + $1000)
        sta bsrc
        lda #>(LCIMAGE + $1000)
        sta bsrc+1
        stz bdst
        lda #$D0
        sta bdst+1
        stz blen
        lda #$30
        sta blen+1
        jsr copy
        bit LCBANK1
        bit LCBANK1
        lda #<CATBUF            ; the catalog, into the card
        sta bsrc
        lda #>CATBUF
        sta bsrc+1
        lda #<catalog
        sta bdst
        lda #>catalog
        sta bdst+1
        lda #<CAT_MAX
        sta blen
        lda #>CAT_MAX
        sta blen+1
        jsr copy
        jmp run_start

; segment: the segment hdr (bank, address, length) from the open file
; into its bank, 8 KB at a time through DATABUF
segment:
@chunk: lda hdr+4
        cmp #>DATAMAX
        bcc :+
        lda #<DATAMAX
        sta rd_count
        lda #>DATAMAX
        sta rd_count+1
        bra :++
:       lda hdr+3
        sta rd_count
        lda hdr+4
        sta rd_count+1
:       lda #<DATABUF
        sta rd_buf
        lda #>DATABUF
        sta rd_buf+1
        jsr read
        lda #<DATABUF
        sta bsrc
        lda #>DATABUF
        sta bsrc+1
        lda hdr+1
        sta bdst
        lda hdr+2
        sta bdst+1
        lda rd_count
        sta blen
        lda rd_count+1
        sta blen+1
        lda hdr
        sta RWBANK              ; a RamWorks bank
        sta RAMWRTON
        jsr copy
        sta RAMWRTOFF
        stz RWBANK
        lda hdr+1               ; what is left
        clc
        adc rd_count
        sta hdr+1
        lda hdr+2
        adc rd_count+1
        sta hdr+2
        lda hdr+3
        sec
        sbc rd_count
        sta hdr+3
        lda hdr+4
        sbc rd_count+1
        sta hdr+4
        ora hdr+3
        jne @chunk
        rts

; probe: banks 1-126 there and distinct (each one's number written to its
; $0200, then each read back through the page-1 routine), else a stop
; with the first one missing
probe:  ldx #probe_end - probe_rd - 1
:       lda probe_rd,x
        sta PROBE,x
        dex
        bpl :-
        lda #1
        sta bnk
@write: lda bnk
        sta RWBANK
        sta RAMWRTON
        sta $0200
        sta RAMWRTOFF
        stz RWBANK
        inc bnk
        lda bnk
        cmp #BANKS + 1
        jcc @write
        lda #1
        sta bnk
@read:  lda bnk
        sta RWBANK
        jsr PROBE
        stz RWBANK
        cmp bnk
        bne @short
        inc bnk
        lda bnk
        cmp #BANKS + 1
        bcc @read
        rts
@short: ldx #0
:       lda msg_banks,x
        beq :+
        sta $0480,x
        inx
        bra :-
:       lda bnk                 ; the first bank missing, in hex
        tay
        jmp bf_hex
probe_rd:                       ; (copied to page 1)
        sta RAMRDON
        lda $0200
        sta RAMRDOFF
        rts
probe_end:

; copy: blen bytes from bsrc to bdst, forward (blen > 0)
copy:   ldy #0
        ldx blen+1
        beq @rest
@page:  lda (bsrc),y
        sta (bdst),y
        iny
        bne @page
        inc bsrc+1
        inc bdst+1
        dex
        bne @page
@rest:  ldx blen
        beq @done
@byte:  lda (bsrc),y
        sta (bdst),y
        iny
        dex
        bne @byte
@done:  rts

open:   sta op_path
        stx op_path+1
        jsr MLI
        .byte $C8
        .word op_parms
        bcs boot_fail
        lda op_ref
        sta rd_ref
        sta cl_ref
        rts

read:   jsr MLI
        .byte $CA
        .word rd_parms
        bcs boot_fail
        rts

read_any:                       ; (a file shorter than the count: its end
        jsr MLI                 ;   is not an error)
        .byte $CA
        .word rd_parms
        bcc :+
        cmp #$4C                ; EOF
        bne boot_fail
:       rts

close:  jsr MLI
        .byte $CC
        .word cl_parms
        rts

boot_fail:
        tay
        ldx #0
:       lda msg_fail,x
        beq bf_hex
        sta $0480,x
        inx
        bra :-
bf_hex: tya                     ; Y in hex at $0480 + X
        lsr a
        lsr a
        lsr a
        lsr a
        jsr bf_digit
        tya
        and #$0F
        jsr bf_digit
boot_stop:
        bra boot_stop
bf_digit:
        cmp #10
        bcc :+
        adc #6
:       adc #'0' | $80
        sta $0480,x
        inx
        rts

op_parms:
        .byte 3
op_path:
        .word 0
        .word IOBUF
op_ref: .byte 0
rd_parms:
        .byte 4
rd_ref: .byte 0
rd_buf: .word 0
rd_count:
        .word 0
        .word 0
cl_parms:
        .byte 1
cl_ref: .byte 0
hdr:    .res 5
bcol:   .res 1
bfile:  .res 1
magic:  .byte "A2DM"

path_catalog:
        .byte 7, "CATALOG"
msg_load:
        .repeat .strlen("LEVELS: THE STORE INTO RAMWORKS"), I
        .byte .strat("LEVELS: THE STORE INTO RAMWORKS", I) | $80
        .endrep
        .byte 0
msg_fail:
        .repeat .strlen("PRODOS ERROR $"), I
        .byte .strat("PRODOS ERROR $", I) | $80
        .endrep
        .byte 0
msg_banks:
        .repeat .strlen("8 MB OF RAMWORKS NEEDED: NO BANK $"), I
        .byte .strat("8 MB OF RAMWORKS NEEDED: NO BANK $", I) | $80
        .endrep
        .byte 0
        .assert * <= LCIMAGE, error, "the boot code overlaps the card image"
        .assert IOBUF >= LCIMAGE + LCIMAGE_SIZE, error, "ProDOS's buffer"
        .assert CATBUF >= IOBUF + $400, error, "the catalog's buffer"
        .assert HDRBUF >= CATBUF + CAT_MAX, error, "the header's buffer"
        .assert DATABUF >= HDRBUF + $100, error, "the data buffer"
        .assert DATABUF + DATAMAX <= $BF00, error, "the data buffer's end"
        .assert probe_end - probe_rd <= $40, error, "the probe's read"

; ===========================================================================
; the runner: the main language card's $E000 part (segment DRIVER)
; ===========================================================================
.segment "DRIVER"
run_start:
        sei
        cld
        ldx #$FF
        txs
        sta RAMRDOFF
        sta RAMWRTOFF
        sta ALTZPOFF
        stz RWBANK
        bit LCBANK1
        bit LCBANK1
        stz vbl
        stz vbl+1
        jsr mouse_init
        bcc :+
        ldx #msg_nomouse - messages
        jmp fatal
:       jsr amem_probe
        bcc :+
        ldx #msg_noamem - messages
        jmp fatal_code
:       cli
        lda #<rn_runs           ; the load phase's image into W
        ldx #>rn_runs
        ldy #LCODE
        jsr far_pload
        jsr crc_tables
        stz rn_k
rn_map: lda rn_k                ; each entry of the sequence
        cmp catalog + C_MAPS
        bcs rn_done
        jsr t_now
        jsr entry_map           ; X: its map's place in the catalog
        lda catalog + C_NAMES,x
        sta rn_m
        lda catalog + C_NAMES + MAX_MAPS,x
        cmp #$FF
        bne @setup
        lda rn_m
        jsr nl_load
        bra run_loaded
@setup: jsr run_pre             ; the pre-state, then P_SetupLevel
        lda rn_m
        jsr nl_setup
run_loaded:
        lda rn_k                ; its VBLs
        asl a
        tax
        sei
        sec
        lda vbl
        sbc rn_t0
        sta rn_results,x
        lda vbl+1
        sbc rn_t0+1
        sta rn_results+1,x
        cli
        jsr entry_map           ; the CRCs of a setup
        lda catalog + C_NAMES + MAX_MAPS,x
        cmp #$FF
        beq :+
        jsr crcs
:       inc rn_k
        bra rn_map
rn_done:
        jsr show
run_done:
        bra run_done

t_now:  sei
        lda vbl
        sta rn_t0
        lda vbl+1
        sta rn_t0+1
        cli
        rts

; entry_map: X = the place of entry rn_k's map in the catalog (after the
; names: C_NAMES + 16 files + k)
entry_map:
        lda catalog + C_FILES
        asl a
        asl a
        asl a
        asl a
        clc
        adc rn_k
        tax
        rts

; run_pre: the entry's test pre-state (bank PRE_BANK, $0200 + PRE_RECORD
; k): the game globals block into main GBLOCK (whole pages), then the
; random indexes into PRND; one RAMRD window, this code in the card
run_pre:
        lda catalog + C_NAMES + MAX_MAPS,x
        tax
        lda #<ROOM_FIRST
        sta bsrc
        lda #>ROOM_FIRST
        sta bsrc+1
:       dex
        bmi :+
        clc
        lda bsrc
        adc #<PRE_RECORD
        sta bsrc
        lda bsrc+1
        adc #>PRE_RECORD
        sta bsrc+1
        bra :-
:       lda #<GBLOCK
        sta bdst
        lda #>GBLOCK
        sta bdst+1
        lda #PRE_BANK
        sta RWBANK
        sta RAMRDON
        ldx #>(PRE_RND + $FF)
        ldy #0
@page:  lda (bsrc),y
        sta (bdst),y
        iny
        bne @page
        inc bsrc+1
        inc bdst+1
        dex
        bne @page
        sec
        lda bsrc+1
        sbc #>(PRE_RND + $FF)
        sta bsrc+1
        ldy #<PRE_RND
        lda #>PRE_RND
        clc
        adc bsrc+1
        sta bsrc+1
        lda (bsrc),y
        sta PRND
        iny
        bne :+
        inc bsrc+1
:       lda (bsrc),y
        sta PRND+1
        iny                     ; then validcount (the frame block's,
        bne :+                  ;   G_VALID: milestone 10)
        inc bsrc+1
:       lda (bsrc),y
        sta G_VALID
        iny
        bne :+
        inc bsrc+1
:       lda (bsrc),y
        sta G_VALID+1
        sta RAMRDOFF
        stz RWBANK
        rts
        .assert PRE_VALID = PRE_RND + 2, error, "validcount after the indexes"
ROOM_FIRST      = $0200

; crcs: entry rn_k's two CRCs (its map rn_m's window ranges, then its
; state ranges) into rn_crcs (8 bytes an entry) and their match with the
; expected ones (CRCLIST's CL_EXPECT) into rn_ok (bit 0 the window, bit 1
; the state)
crcs:   lda rn_k
        asl a
        asl a
        asl a
        sta rn_i                ; 8 k
        lda rn_m                ; the map's lists: CL_LISTS + 4 (m - 1)
        dec a
        asl a
        asl a
        tax
        jsr crc_list            ; the window
        ldx rn_i
        jsr crc_put
        lda rn_m
        dec a
        asl a
        asl a
        tax
        inx
        inx
        jsr crc_list            ; the state
        lda rn_i
        clc
        adc #4
        tax
        jsr crc_put
        ldx rn_k                ; the matches
        stz rn_ok,x
        lda rn_i
        jsr crc_match
        bne :+
        lda #1
        ora rn_ok,x
        sta rn_ok,x
:       lda rn_i
        clc
        adc #4
        jsr crc_match
        bne :+
        lda #2
        ora rn_ok,x
        sta rn_ok,x
:       rts

; crc_put: crcz into rn_crcs + X
crc_put:
        ldy #0
:       lda crcz,y
        sta rn_crcs,x
        inx
        iny
        cpy #4
        bne :-
        rts

; crc_match: Z set when rn_crcs + A equals CRCLIST's CL_EXPECT + A (8 k:
; the expected CRCs read with RAMRD on, this code in the card). Keeps X.
crc_match:
        tay
        lda #4
        sta rn_n
        lda #CRC_BANK
        sta RWBANK
        sta RAMRDON
:       lda CL_EXPECT,y
        cmp rn_crcs,y
        bne @done
        iny
        dec rn_n
        bne :-
@done:  php                     ; (the soft switches keep the flags)
        sta RAMRDOFF
        stz RWBANK
        plp
        rts

; crc_list: crcz = the CRC-32 of the ranges of the list whose address is
; at CRCLIST's CL_LISTS + X
crc_list:
        lda #$FF
        sta crcz
        sta crcz+1
        sta crcz+2
        sta crcz+3
        lda #CRC_BANK
        sta RWBANK
        sta RAMRDON
        lda CL_LISTS,x
        sta rptr
        lda CL_LISTS+1,x
        sta rptr+1
        ldy #0                  ; the count
        lda (rptr),y
        sta rcount
        iny
        lda (rptr),y
        sta rcount+1
        sta RAMRDOFF
        stz RWBANK
        clc
        lda rptr
        adc #2
        sta rptr
        bcc @range
        inc rptr+1
@range: lda rcount
        ora rcount+1
        beq @end
        lda #CRC_BANK           ; the range: kind, bank, address, length
        sta RWBANK
        sta RAMRDON
        ldy #CL_RANGE - 1
:       lda (rptr),y
        sta rn_rg,y
        dey
        bpl :-
        sta RAMRDOFF
        stz RWBANK
        lda rn_rg + 2
        sta bsrc
        lda rn_rg + 3
        sta bsrc+1
        lda rn_rg + 4
        sta blen
        lda rn_rg + 5
        sta blen+1
        lda rn_rg               ; RamWorks: its bank, RAMRD on
        beq :+
        lda rn_rg + 1
        sta RWBANK
        sta RAMRDON
:       jsr crc_bytes
        sta RAMRDOFF
        stz RWBANK
        clc
        lda rptr
        adc #CL_RANGE
        sta rptr
        bcc :+
        inc rptr+1
:       lda rcount
        bne :+
        dec rcount+1
:       dec rcount
        bra @range
@end:   ldx #3
:       lda crcz,x
        eor #$FF
        sta crcz,x
        dex
        bpl :-
        rts

; crc_bytes: crcz over blen bytes (1-65,535) at bsrc (main, or the window
; set up), the tables and this code in the card
crc_bytes:
        ldy #0
@byte:  lda (bsrc),y
        eor crcz
        tax
        lda crcz+1
        eor crc_t0,x
        sta crcz
        lda crcz+2
        eor crc_t1,x
        sta crcz+1
        lda crcz+3
        eor crc_t2,x
        sta crcz+2
        lda crc_t3,x
        sta crcz+3
        iny
        bne :+
        inc bsrc+1
:       lda blen
        bne :+
        dec blen+1
:       dec blen
        lda blen
        ora blen+1
        bne @byte
        rts

; crc_tables: zlib's CRC-32 table (reflected, $EDB88320), a plane a byte
crc_tables:
        ldx #0
@entry: stx crcz
        stz crcz+1
        stz crcz+2
        stz crcz+3
        ldy #8
@bit:   lsr crcz+3
        ror crcz+2
        ror crcz+1
        ror crcz
        bcc :+
        lda crcz
        eor #$20
        sta crcz
        lda crcz+1
        eor #$83
        sta crcz+1
        lda crcz+2
        eor #$B8
        sta crcz+2
        lda crcz+3
        eor #$ED
        sta crcz+3
:       dey
        bne @bit
        lda crcz
        sta crc_t0,x
        lda crcz+1
        sta crc_t1,x
        lda crcz+2
        sta crc_t2,x
        lda crcz+3
        sta crc_t3,x
        inx
        bne @entry
        rts

; show: the text screen: each entry's map and VBLs, and a setup's two
; CRCs with OK or BAD (an entry a row, 22 at most), then "SETUPS OK" or
; "CRCS DIFFER"
show:   jsr text_mode
        lda #0
        jsr row
        ldx #msg_title - messages
        jsr print
        stz rn_i
        stz rn_bad
@one:   lda rn_i
        cmp catalog + C_MAPS
        jcs @sum
        cmp #22
        jcs @sum
        inc a                   ; row 1 + i
        jsr row
        ldx #msg_map - messages
        jsr print
        lda rn_i
        sta rn_k
        jsr entry_map
        lda catalog + C_NAMES,x
        ora #'0' | $80
        jsr putc
        ldx #msg_vbl - messages
        jsr print
        lda rn_i
        asl a
        tax
        lda rn_results,x
        sta num
        lda rn_results+1,x
        sta num+1
        jsr dec5
        jsr entry_map           ; a setup: its CRCs
        lda catalog + C_NAMES + MAX_MAPS,x
        cmp #$FF
        beq @next
        lda rn_i
        asl a
        asl a
        asl a
        tay
        lda #1                  ; W: the window's
        ldx #msg_w - messages
        jsr show_crc
        lda #2                  ; S: the state's
        ldx #msg_s - messages
        jsr show_crc
@next:  inc rn_i
        jmp @one
@sum:   lda #23
        jsr row
        ldx #msg_ok - messages
        lda rn_bad
        beq :+
        ldx #msg_differ - messages
:       jmp print

; show_crc: message X, then the CRC at rn_crcs + Y (4 bytes, shown high
; first; Y + 4 after), then OK when bit A of the entry's rn_ok is set,
; else BAD (counted in rn_bad)
show_crc:
        sta rn_bit
        jsr print
        iny
        iny
        iny
        ldx #4
:       lda rn_crcs,y
        jsr hex
        dey
        dex
        bne :-
        iny
        iny
        iny
        iny
        iny
        phy
        ldx rn_i
        lda rn_ok,x
        and rn_bit
        bne :+
        inc rn_bad
        ldx #msg_bad - messages
        bra :++
:       ldx #msg_crcok - messages
:       jsr print
        ply
        rts

; ---- the memory API (appletini-one README_MEMORY_API.md) ----

; amem_probe: C clear when slot 7 has the API with COPY, FILL and PRIVATE
amem_probe:
        php
        sei
        sta INTCXROMOFF
        bit SP_RELEASE
        lda SP_ROM+1
        cmp #$20
        jne @absent
        lda SP_ROM+3
        ora SP_ROM+7
        jne @absent
        lda SP_ROM+5
        cmp #3
        jne @absent
        lda SP_CTRL
        and #$3F
        cmp #$20
        jne @absent
        bit SP_RELEASE
        bit SP_ROM
        ldy #0
:       lda status_request,y
        sta SP_DATA
        iny
        cpy #10
        bne :-
        lda #2
        sta SP_CTRL
        ldx #0
        ldy #0
        stz wcount
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec wcount
        bne @wait
        lda #AMEM_TIMEOUT
        bra @fail
@ready: lda SP_DATA
        sta SP_POP
        cmp #0
        bne @fail
        lda SP_DATA             ; the length: 32
        sta SP_POP
        cmp #32
        bne @bad
        lda SP_DATA
        sta SP_POP
        bne @bad
        ldx #0
:       lda SP_DATA
        sta SP_POP
        sta rn_caps,x
        inx
        cpx #32
        bcc :-
        ldx #4                  ; "AMEM", version 1
:       lda rn_caps,x
        cmp amem_magic,x
        bne @bad
        dex
        bpl :-
        lda rn_caps+6           ; descriptors of 16 bytes, 16 of them
        cmp #16
        bne @bad
        lda rn_caps+7
        cmp #AMEM_MAX
        bcc @bad
        lda rn_caps+8           ; COPY, FILL, PRIVATE
        and #7
        cmp #7
        bne @bad
        lda rn_caps+15          ; available
        and #1
        beq @bad
        bit SP_RELEASE
        plp
        clc
        rts
@absent:
        lda #$FF
        bra @fail
@bad:   lda #$FE
@fail:  bit SP_RELEASE
        plp
        sec
        rts
status_request:
        .byte 0, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; STATUS, unit 0, selector $80
amem_magic:
        .byte "AMEM", 1

; ---- the mouse card: C set when there is none ----
mouse_init:
        sta INTCXROMOFF
        lda MOUSE_ROM+$05
        cmp #$38
        bne @none
        lda MOUSE_ROM+$07
        cmp #$18
        bne @none
        lda MOUSE_ROM+$0B
        cmp #$01
        bne @none
        lda MOUSE_ROM+$0C
        cmp #$20
        bne @none
        lda #ACK_ALL
        sta MOUSE_ACK
        lda #MODE_VBL
        sta MOUSE_MODE
        clc
        rts
@none:  sec
        rts

; ---- the interrupt: VBLs; a BRK is a load's stop (its LV_STATUS) ----
irq:    pha
        phx
        tsx
        lda $0103,x
        and #$10
        bne @brk
        ldx MOUSE_STATUS
        lda #ACK_ALL
        sta MOUSE_ACK
        txa
        and #$08
        beq @done
        inc vbl
        bne @done
        inc vbl+1
@done:  plx
        pla
        rti
@brk:   lda LV_STATUS
        ldx #msg_crash - messages
        bra fatal_code

fatal_code:
        sei
        pha
        jsr fatal_text
        pla
        jsr hex
:       bra :-
fatal:  sei
        jsr fatal_text
:       bra :-
fatal_text:
run_crash:
        stz MOUSE_MODE
        sta RAMRDOFF
        sta RAMWRTOFF
        stz RWBANK
        bit LCBANK1
        bit LCBANK1
        phx
        jsr text_mode
        plx
        stz line
        lda #$04
        sta line+1
        stz col
        jmp print

; dec5: num in decimal, 5 digits, leading blanks
dec5:   ldx #0
        stz tmp
@digit: ldy #0
@sub:   lda num
        sec
        sbc powers_lo,x
        pha
        lda num+1
        sbc powers_hi,x
        bcc @done1
        sta num+1
        pla
        sta num
        iny
        bra @sub
@done1: pla
        tya
        bne @print
        lda tmp
        bne @print
        cpx #4
        bcs @print
        lda #' ' | $80
        bra @put
@print: inc tmp
        tya
        ora #'0' | $80
@put:   jsr putc
        inx
        cpx #5
        bcc @digit
        rts
powers_lo:
        .byte <10000, <1000, <100, <10, <1
powers_hi:
        .byte >10000, >1000, >100, >10, >1

text_mode:
        lda #$01
        sta NEWVIDEO
        sta TEXTON
        sta MIXEDOFF
        sta PAGE1
        sta COL80OFF
        sta ALTCHAROFF
        ldx #0
        lda #' ' | $80
:       sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        inx
        bne :-
        rts

row:    tax
        lda text_lo,x
        sta line
        lda text_hi,x
        sta line+1
        stz col
        rts

putc:   phy
        ldy col
        sta (line),y
        inc col
        ply
        rts

hex:    pha
        lsr a
        lsr a
        lsr a
        lsr a
        jsr @digit
        pla
        and #$0F
@digit: cmp #10
        bcc :+
        adc #6
:       adc #'0' | $80
        jmp putc

print:  lda messages,x
        beq @done
        ora #$80
        jsr putc
        inx
        bra print
@done:  rts

text_lo:
        .repeat 24, R
        .byte <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
text_hi:
        .repeat 24, R
        .byte >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep

messages:
msg_title:
        .byte "SETUP  VBLS  WINDOW CRC     STATE CRC", 0
msg_map:
        .byte "E1M", 0
msg_vbl:
        .byte " ", 0
msg_w:
        .byte " W ", 0
msg_s:
        .byte " S ", 0
msg_crcok:
        .byte " OK", 0
msg_bad:
        .byte " BAD", 0
msg_ok:
        .byte "SETUPS OK: EVERY CRC AS EXPECTED", 0
msg_differ:
        .byte "CRCS DIFFER (BAD ABOVE)", 0
msg_nomouse:
        .byte "NO MOUSE CARD IN SLOT 2: NO VBL CLOCK", 0
msg_crash:
        .byte "THE LOAD STOPPED (BRK), LV_STATUS $", 0
msg_noamem:
        .byte "NO MEMORY API IN SLOT 7 (F1.1.4 OR LATER) $", 0

rn_runs:
        .byte LIM_FIRST
        .byte <(((__LOADW_RUN__ + __LOADW_SIZE__ + $FF) >> 8) - LIM_FIRST)
        .byte 0

; ---------------------------------------------------------------------------
.segment "DESC"
catalog:        .res CAT_MAX
rn_k:           .res 1
rn_i:           .res 1
rn_m:           .res 1          ; the entry's map
rn_t0:          .res 2          ; its first VBL
rn_bad:         .res 1
rn_bit:         .res 1
rn_n:           .res 1
rn_rg:          .res CL_RANGE   ; a range
rn_results:     .res 2 * MAX_MAPS
rn_crcs:        .res 8 * MAX_MAPS
rn_ok:          .res MAX_MAPS
rn_caps:        .res 32
        .align 256
crc_t0:         .res 256
crc_t1:         .res 256
crc_t2:         .res 256
crc_t3:         .res 256

.segment "VECTORS"
        .word irq                       ; NMI
        .word run_start                 ; reset
        .word irq                       ; IRQ, BRK
