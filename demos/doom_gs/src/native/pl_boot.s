; pl_boot.s: DOOM.SYSTEM, the game's boot (milestone 11, part plboot;
; docs/SCREENS.md 2.5, 4.5, 6.5; docs/m11-parts/plboot.md). GPL-2, the
; port's own: written from the design and LEVELS.SYSTEM's boot
; (src/native/lboot.s, read only, whose bank-file loader, RamWorks probe,
; memory-API probe, mouse-card probe and CRC-32 it follows), the //e
; kernel's loader (demos/doom/src/kernel/loader.s: the A2DM bank files)
; and SOUNDS.SYSTEM's boot order (src/sound/sounds.s). Nothing of
; upstream's. tools/native/pldisk.py builds DOOM.hdv and checks it on a2vm.
;
; Under ProDOS, at $2000, interrupts masked (SCREENS.md 2.5):
;   1. the text screen; the probes, each a stop with its message and its
;      code in PL_STATUS (s2layout.PL): RamWorks banks 1-126 (each bank's
;      number written to its $0200, from 126 down to 0, then each read
;      back from 1 up: the first that does not hold its number is the
;      first missing, PL_BANKS); the mouse card in slot 2 (its ROM's ID
;      bytes, PL_NOMOUSE); the memory API in slot 7 (COPY, FILL,
;      PRIVATE; PL_NOAMEM); snd_probe (no native mode: a message, the game
;      goes on without music or effects, the effect player off);
;   2. CATALOG (the bank files' names), then every bank file through the
;      MLI ("A2DM", version 1, a segment count, 5 bytes a segment: bank,
;      address, length; zero padding to 256 bytes; the bytes): each
;      segment read 8 KB at a time into DATABUF and copied into its bank
;      (RAMWRT on, $C073 its bank); a bank outside 1-126 or a segment
;      outside $0200-$BFFF stops (PL_DISK);
;   3. CRCLIST (the disk builder's table: a count, then 9 bytes an entry:
;      bank, address, length, zlib's CRC-32): its count must be the
;      segments loaded and the card image's two halves, else a stop
;      (PL_CRC); then the CRC-32 of every segment in its bank, read back
;      a page at a time by the page-1 routine (RAMRD on), against its
;      entry: a mismatch stops with its bank and address (PL_CRC);
;   4. LC.BIN, the card images (16 KB each: bank 1 $D000-$DFFF, bank 2
;      $D000-$DFFF, $E000-$FFFF): the aux card's read into STAGE, its CRC
;      checked, installed by CPU copy with ALTZP on (RamWorks bank 0's
;      card); then the main card's read into STAGE and checked; the file
;      closed (the last MLI call); then the install: the main card by CPU
;      copy (ProDOS's card overwritten, the vector pl_vbl), LC bank 1
;      selected (MEMORY_MAP.md rule 1), main $0200-$03EF, $0C00-$1FFF
;      (the persistent state: the globals, the renderer's persistent rows,
;      the game's globals, the key table) and ProDOS's global page
;      $BF00-$BFFF cleared, zero page $00-$17 cleared and the pair
;      $06-$07 zeroed [R NATIVE.md 10; MEMORY_MAP.md 2];
;   5. the mouse card's VBL on (mode $09, masked), pl_init (the input
;      block, the key table, the mouse's window), snd_init, fx_init with
;      snd_probe's answer, pl_clkset (PAL until pl_detect), CLI,
;      pl_detect (PAL or NTSC: its clock), PL_STATUS = PL_READY, and the
;      ready loop pl_ready in the card, which the second half replaces
;      with the title loop.
;
; Main memory while booting: this code $2000-$2FFF (DOOM.SYSTEM; the
; boot is discarded: nothing calls it after pl_ready), STAGE and DATABUF
; $6000-$9FFF, ProDOS's buffer $A000, the catalog $A400, a header $A500,
; the bounce page $A600, the CRC tables $A700-$AAFF, CRCLIST $AB00-$BEFF;
; page 1's routine at $0100. The boot's CPU stores in $2000-$5FFF are its
; own variables and patched operands in $2000-$2FFF, and none reaches
; $0878-$087F or $4078-$407F (MEMORY_MAP.md rule 8); the probe leaves
; each bank's number at its $0200 (aux 0's too: 0) where no file writes.
; Its zero page is $18-$3F (overlay 1).
;
; The card part (segment PLRES, $FF00-$FFF9 "platform": MEMORY_MAP.md
; 4.2): pl_ready, a loop that waits for each VBL (pl_ridle the wait,
; pl_rvbl each VBL's visit: a2vm's idle skip and its count of VBLs).

        .setcpu "65C02"
        .macpack longbranch
        .include "s2.inc"

        .import snd_probe, snd_init, fx_init, pl_clkset, pl_detect, pl_init
        .importzp vbl_count
        .export boot, bt_halt, bt_installed, bt_done, check_files, load_card
        .export pl_ready, pl_ridle, pl_rvbl
        .exportzp bt_music, bt_nseg

; PL_DISK (s2.inc, request PLBOOT-1 applied in wave 8): a stop of the
; disk (a ProDOS error, a file that is not a bank file, a segment outside
; its room)

MLI            = $BF00
STORE80OFF      = $C000
RAMRDOFF        = $C002
RAMRDON         = $C003
RAMWRTOFF       = $C004
RAMWRTON        = $C005
INTCXROMOFF     = $C006
ALTZPOFF        = $C008
ALTZPON         = $C009
COL80OFF        = $C00C
ALTCHAROFF      = $C00E
NEWVIDEO        = $C029
TEXTON          = $C051
MIXEDOFF        = $C052
PAGE1           = $C054
RWBANK          = $C073
LCROM           = $C082         ; read the ROM (ProDOS's callers' state)
LCBANK2         = $C083         ; twice: RAM read and write, $D000 bank 2
LCBANK1         = $C08B         ; twice: RAM read and write, $D000 bank 1
MOUSE_ROM       = $C200
MOUSE_MODE      = $C0AE
MOUSE_ACK       = $C0AF
MODE_VBL        = $09           ; the mouse card on, its VBL interrupt on
ACK_ALL         = $03
SP_DATA         = $CFF0         ; the memory API's FIFO (slot 7)
SP_CTRL         = $CFF1
SP_POP          = $CFF2
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F
AMEM_MAX        = 16            ; descriptors a request (llayout.AMEM_MAX)

SND_MUSIC       = 0             ; snd_probe's answer: native mode
STD_PAL         = 0             ; pl_clkset's standard
BANKS           = 126           ; the banks the game needs (NATIVE.md 15.1)
ZP_PAIR         = $06           ; zp_rd, zp_wr (MEMORY_MAP.md 2)
ZP_PLATFORM_END = $18           ; $00-$17: the platform's (cleared)

BOOT_END        = $3000         ; this code (DOOM.SYSTEM) $2000-$2FFF
STAGE           = $6000         ; a card image, 16 KB
STAGE_SIZE      = $4000
DATABUF         = $6000         ; a bank file's bytes, 8 KB at a time
DATAMAX         = $2000
IOBUF           = $A000         ; ProDOS's buffer for the open file
CATBUF          = $A400         ; CATALOG
CAT_MAX         = $0100
HDRBUF          = $A500         ; a bank file's header
BOUNCE          = $A600         ; a page read back from a bank
CRC_T0          = $A700         ; zlib's CRC-32 table, a plane a byte
CRC_T1          = $A800
CRC_T2          = $A900
CRC_T3          = $AA00
CRCBUF          = $AB00         ; CRCLIST
CRC_MAX         = $BF00 - CRCBUF
P1CODE          = $0100         ; page 1's routine (near with RAMRD on)
C_NAMES         = 16            ; CATALOG: +0 the files, +16 their names
ENTRY           = 9             ; CRCLIST: bank, address, length, CRC-32

; zero page (overlay 1)
bsrc            = $18
bdst            = $1A
blen            = $1C
crcz            = $1E           ; (4)
sptr            = $22           ; the header's next segment
segs            = $24           ; the file's segments left
bfile           = $25
hdr             = $26           ; (5) a segment: bank, address, length
bt_nseg         = $2B           ; (2) the segments loaded
eptr            = $2D           ; (2) CRCLIST's next entry
ecnt            = $2F           ; (2) its entries left to check
line            = $31           ; (2) the text row
col             = $33
bnk             = $34
wcount          = $35
bt_music        = $36           ; snd_probe's answer
tmp             = $37           ; (2)

; ===========================================================================
.segment "PLBOOT"
; ===========================================================================
boot:   sei
        cld
        ldx #$FF
        txs
        sta STORE80OFF
        sta RAMRDOFF
        sta RAMWRTOFF
        sta ALTZPOFF
        sta INTCXROMOFF
        stz RWBANK
        lda #$01                ; SHR off
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
        lda #0
        ldx #<s_title
        ldy #>s_title
        jsr say
        ldx #p1_end - p1_code - 1       ; page 1's routine
:       lda p1_code,x
        sta P1CODE,x
        dex
        bpl :-
        jsr probe_banks
        jsr probe_mouse
        jsr probe_amem
        jsr snd_probe           ; native mode or not
        sta bt_music
        cmp #SND_MUSIC
        beq :+
        lda #2
        ldx #<s_nomusic
        ldy #>s_nomusic
        jsr say
:       lda #1
        jsr row
        jsr load_files
        jsr crc_tables
        jsr check_files
        jsr load_card
; ---- the install: ProDOS goes ----
        lda #0
        jsr lc_put              ; the main card
        bit LCBANK1             ; bank 1 selected (MEMORY_MAP.md rule 1)
        bit LCBANK1
        ldx #0                  ; the persistent state cleared:
:       stz $0200,x             ;   $0200-$03EF,
        stz $BF00,x             ;   ProDOS's global page
        cpx #$F0
        bcs :+
        stz $0300,x
:       inx
        bne :--
        lda #$0C                ;   $0C00-$1FFF
        sta bdst+1
        stz bdst
        ldx #$20 - $0C
        lda #0
        tay
:       sta (bdst),y
        iny
        bne :-
        inc bdst+1
        dex
        bne :-
        ldx #ZP_PLATFORM_END - 1        ; the platform's zero page: $08-$17
:       stz $00,x
        dex
        cpx #ZP_PAIR + 1
        bne :-
        ldx #ZP_PAIR - 1                ;   and $00-$05
:       stz $00,x
        dex
        bpl :-
        stz ZP_PAIR             ; the pair zeroed [R NATIVE.md 10]
        stz ZP_PAIR + 1
bt_installed:                   ; (a2vm's snapshot: the card as the image)
        lda #ACK_ALL            ; the VBL on, still masked
        sta MOUSE_ACK
        lda #MODE_VBL
        sta MOUSE_MODE
        jsr pl_init             ; the input, the key table
        jsr snd_init
        lda bt_music
        jsr fx_init             ; A: snd_probe's answer
        lda #STD_PAL
        jsr pl_clkset           ; the clock defined until pl_detect
        cli
        jsr pl_detect           ; PAL or NTSC, the clock from 0
        lda #PL_READY
        sta PL_STATUS
        lda #4
        ldx #<s_ready
        ldy #>s_ready
        jsr say
bt_done:
        ldx #$FF
        txs
        jmp pl_ready

; ---------------------------------------------------------------------------
; the probes
; ---------------------------------------------------------------------------

; probe_banks: banks 1-126 there and distinct, else the stop PL_BANKS with
; the first missing
probe_banks:
        lda #BANKS
        sta bnk
@write: lda bnk
        sta RWBANK
        sta RAMWRTON
        sta $0200
        sta RAMWRTOFF
        dec bnk
        bpl @write              ; 126 down to 0
        stz RWBANK
        lda #1
        sta bnk
@read:  lda bnk
        sta RWBANK
        lda #<$0200
        ldy #>$0200
        ldx #1
        jsr P1CODE
        stz RWBANK
        lda BOUNCE
        cmp bnk
        bne @short
        inc bnk
        lda bnk
        cmp #BANKS + 1
        bcc @read
        rts
@short: ldx #<s_banks
        ldy #>s_banks
        jsr fail_say
        lda bnk
        jsr hex
        lda #PL_BANKS
        jmp bt_stop

; probe_mouse: the mouse card's ROM in slot 2 (its ID bytes), else the stop
probe_mouse:
        sta INTCXROMOFF
        lda MOUSE_ROM + $05
        cmp #$38
        bne @none
        lda MOUSE_ROM + $07
        cmp #$18
        bne @none
        lda MOUSE_ROM + $0B
        cmp #$01
        bne @none
        lda MOUSE_ROM + $0C
        cmp #$20
        bne @none
        rts
@none:  ldx #<s_nomouse
        ldy #>s_nomouse
        jsr fail_say
        lda #PL_NOMOUSE
        jmp bt_stop

; probe_amem: the memory API in slot 7 with COPY, FILL and PRIVATE
; (appletini-one README_MEMORY_API.md; as lboot.s's amem_probe), else the
; stop with the answer ($FF none, $FE a capability missing, $6F no reply,
; else its error)
probe_amem:
        sta INTCXROMOFF
        bit SP_RELEASE
        lda SP_ROM + 1
        cmp #$20
        jne @absent
        lda SP_ROM + 3
        ora SP_ROM + 7
        jne @absent
        lda SP_ROM + 5
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
        sta BOUNCE,x            ; (the capabilities)
        inx
        cpx #32
        bcc :-
        ldx #4                  ; "AMEM", version 1
:       lda BOUNCE,x
        cmp amem_magic,x
        bne @bad
        dex
        bpl :-
        lda BOUNCE + 6          ; descriptors of 16 bytes, 16 of them
        cmp #16
        bne @bad
        lda BOUNCE + 7
        cmp #AMEM_MAX
        bcc @bad
        lda BOUNCE + 8          ; COPY, FILL, PRIVATE
        and #7
        cmp #7
        bne @bad
        lda BOUNCE + 15         ; available
        and #1
        beq @bad
        bit SP_RELEASE
        rts
@absent:
        lda #$FF
        bra @fail
@bad:   lda #$FE
@fail:  bit SP_RELEASE
        pha
        ldx #<s_noamem
        ldy #>s_noamem
        jsr fail_say
        pla
        jsr hex
        lda #PL_NOAMEM
        jmp bt_stop

; ---------------------------------------------------------------------------
; the bank files
; ---------------------------------------------------------------------------

; load_files: CATALOG, then each bank file's segments into their banks;
; bt_nseg counts the segments
load_files:
        lda #<p_catalog
        ldx #>p_catalog
        jsr open
        lda #<CATBUF
        ldx #>CATBUF
        sta rd_buf
        stx rd_buf+1
        lda #<CAT_MAX
        ldx #>CAT_MAX
        sta rd_count
        stx rd_count+1
        jsr read_any
        jsr close
        stz bt_nseg
        stz bt_nseg+1
        stz bfile
@file:  lda bfile               ; each bank file
        cmp CATBUF
        bcc :+
        rts
:       lda #'.' | $80
        jsr putc
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
        lda #<HDRBUF            ; its header
        ldx #>HDRBUF
        sta rd_buf
        stx rd_buf+1
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
        ldy #4
:       lda (sptr),y
        sta hdr,y
        dey
        bpl :-
        lda hdr                 ; a bank of the game: 1-126
        beq @bad
        cmp #BANKS + 1
        bcs @bad
        lda hdr+2               ; from $0200
        cmp #$02
        bcc @bad
        lda hdr+3               ; at least a byte
        ora hdr+4
        beq @bad
        clc                     ; to $C000 at most
        lda hdr+1
        adc hdr+3
        lda hdr+2
        adc hdr+4
        bcs @bad
        cmp #$C0
        bcc :+
        bne @bad
        lda hdr+1               ; (the end exactly $C000)
        clc
        adc hdr+3
        bne @bad
:       jsr segment
        inc bt_nseg
        bne :+
        inc bt_nseg+1
:       clc
        lda sptr
        adc #5
        sta sptr
        dec segs
        bra @seg
@end:   jsr close
        inc bfile
        jmp @file
@bad:   ldx #<s_notbank
        ldy #>s_notbank
        jsr fail_say
        lda bfile
        jsr hex
        lda #PL_DISK
        jmp bt_stop

; segment: the segment hdr from the open file into its bank, 8 KB at a
; time through DATABUF
segment:
@chunk: lda hdr+4
        cmp #>DATAMAX
        bcc :+
        lda #<DATAMAX
        ldx #>DATAMAX
        bra :++
:       lda hdr+3
        ldx hdr+4
:       sta rd_count
        stx rd_count+1
        sta blen
        stx blen+1
        lda #<DATABUF
        ldx #>DATABUF
        sta rd_buf
        stx rd_buf+1
        sta bsrc
        stx bsrc+1
        jsr read
        lda hdr+1
        sta bdst
        lda hdr+2
        sta bdst+1
        lda hdr
        sta RWBANK              ; its RamWorks bank
        sta RAMWRTON
        jsr copy
        sta RAMWRTOFF
        stz RWBANK
        clc                     ; what is left
        lda hdr+1
        adc rd_count
        sta hdr+1
        lda hdr+2
        adc rd_count+1
        sta hdr+2
        sec
        lda hdr+3
        sbc rd_count
        sta hdr+3
        lda hdr+4
        sbc rd_count+1
        sta hdr+4
        ora hdr+3
        bne @chunk
        rts

; copy: blen bytes (1-65,535) from bsrc to bdst, forward
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

; ---------------------------------------------------------------------------
; the CRCs
; ---------------------------------------------------------------------------

; check_files: CRCLIST read; its count must be the segments loaded and
; LC.BIN's two halves; then each segment's CRC in its bank against its
; entry. eptr is left at the first half's entry
check_files:
        lda #<p_crclist
        ldx #>p_crclist
        jsr open
        lda #<CRCBUF
        ldx #>CRCBUF
        sta rd_buf
        stx rd_buf+1
        lda #<CRC_MAX
        ldx #>CRC_MAX
        sta rd_count
        stx rd_count+1
        jsr read_any
        jsr close
        clc                     ; the count: the segments and two halves
        lda bt_nseg
        adc #2
        tax
        lda bt_nseg+1
        adc #0
        cmp CRCBUF+1
        bne @short
        cpx CRCBUF
        bne @short
        stx tmp                 ; the bytes read: 2 + 9 x the count
        sta tmp+1
        asl tmp
        rol tmp+1
        asl tmp
        rol tmp+1
        asl tmp
        rol tmp+1
        txa
        clc
        adc tmp
        tax
        lda CRCBUF+1
        adc tmp+1
        sta tmp+1
        txa
        clc
        adc #2
        tax
        lda tmp+1
        adc #0
        cmp rd_trans+1
        bne @short
        cpx rd_trans
        bne @short
        lda #<(CRCBUF + 2)
        sta eptr
        lda #>(CRCBUF + 2)
        sta eptr+1
        lda bt_nseg
        sta ecnt
        lda bt_nseg+1
        sta ecnt+1
@one:   lda ecnt
        ora ecnt+1
        beq @done
        jsr check_entry
        lda ecnt
        bne :+
        dec ecnt+1
:       dec ecnt
        bra @one
@done:  rts
@short: ldx #<s_crclist
        ldy #>s_crclist
        jsr fail_say
        lda bt_nseg+1
        jsr hex
        lda bt_nseg
        jsr hex
        lda #PL_CRC
        jmp bt_stop

; check_entry: the CRC-32 of eptr's range (bank 0: main memory; else the
; bank's, a page at a time through BOUNCE) against the entry's; a mismatch
; stops with the bank and the address; eptr to the next entry
check_entry:
        ldy #4
:       lda (eptr),y
        sta hdr,y
        dey
        bpl :-
        lda #$FF
        sta crcz
        sta crcz+1
        sta crcz+2
        sta crcz+3
        lda hdr
        bne @bank
        lda hdr+1               ; main: the whole range at once
        sta bsrc
        lda hdr+2
        sta bsrc+1
        lda hdr+3
        sta blen
        lda hdr+4
        sta blen+1
        jsr crc_bytes
        bra @end
@bank:  lda hdr+4               ; a page or what is left
        beq :+
        lda #0
        bra :++
:       lda hdr+3
:       sta tmp                 ; (0: 256)
        lda hdr
        sta RWBANK
        lda hdr+1
        ldy hdr+2
        ldx tmp
        jsr P1CODE
        stz RWBANK
        ldx tmp
        jsr crc_page
        lda tmp                 ; the next page
        bne :+
        inc hdr+2
        dec hdr+4
        bra @next
:       clc
        adc hdr+1
        sta hdr+1
        bcc :+
        inc hdr+2
:       sec
        lda hdr+3
        sbc tmp
        sta hdr+3
        bcs @next
        dec hdr+4
@next:  lda hdr+3
        ora hdr+4
        bne @bank
@end:   ldy #5                  ; the result against the entry
        ldx #0
:       lda crcz,x
        eor #$FF
        cmp (eptr),y
        bne @bad
        iny
        inx
        cpx #4
        bne :-
        clc
        lda eptr
        adc #ENTRY
        sta eptr
        bcc :+
        inc eptr+1
:       rts
@bad:   ldx #<s_crcbad
        ldy #>s_crcbad
        jsr fail_say
        lda (eptr)              ; the bank
        jsr hex
        ldx #<s_at
        ldy #>s_at
        jsr puts
        ldy #2                  ; the address
        lda (eptr),y
        jsr hex
        dey
        lda (eptr),y
        jsr hex
        lda #PL_CRC
        jmp bt_stop

; crc_bytes: crcz over blen bytes (1-65,535) at bsrc
crc_bytes:
        ldy #0
@byte:  lda (bsrc),y
        eor crcz
        tax
        lda crcz+1
        eor CRC_T0,x
        sta crcz
        lda crcz+2
        eor CRC_T1,x
        sta crcz+1
        lda crcz+3
        eor CRC_T2,x
        sta crcz+2
        lda CRC_T3,x
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

; crc_page: crcz over the X bytes (0: 256) at BOUNCE
crc_page:
        stx wcount
        ldy #0
@byte:  lda BOUNCE,y
        eor crcz
        tax
        lda crcz+1
        eor CRC_T0,x
        sta crcz
        lda crcz+2
        eor CRC_T1,x
        sta crcz+1
        lda crcz+3
        eor CRC_T2,x
        sta crcz+2
        lda CRC_T3,x
        sta crcz+3
        iny
        cpy wcount
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
        sta CRC_T0,x
        lda crcz+1
        sta CRC_T1,x
        lda crcz+2
        sta CRC_T2,x
        lda crcz+3
        sta CRC_T3,x
        inx
        bne @entry
        rts

; ---------------------------------------------------------------------------
; the card images
; ---------------------------------------------------------------------------

; load_card: LC.BIN: the aux card's half into STAGE, checked, installed;
; the main card's half into STAGE, checked; the file closed
load_card:
        lda #<p_lcbin
        ldx #>p_lcbin
        jsr open
        jsr read_half
        jsr check_entry
        lda #$80
        jsr lc_put              ; the aux card (ALTZP on)
        bit LCROM               ; ProDOS's callers' state
        jsr read_half
        jsr check_entry
        jmp close               ; the last MLI call

read_half:
        lda #<STAGE
        ldx #>STAGE
        sta rd_buf
        stx rd_buf+1
        lda #<STAGE_SIZE
        ldx #>STAGE_SIZE
        sta rd_count
        stx rd_count+1
        jmp read

; lc_put: STAGE into the card, bank 1 $D000-$DFFF, bank 2 $D000-$DFFF,
; $E000-$FFFF; A bit 7: the aux card's (ALTZP on while copying: RamWorks
; bank 0's card), else the main card's. Interrupts masked; no zero page
; or stack while ALTZP is on
lc_put: sta lc_alt
        lda #>STAGE
        sta lp_ld+2
        stz lp_ld+1
        stz lp_st+1
        lda #$D0
        sta lp_st+2
        bit LCBANK1
        bit LCBANK1
        ldx #$10
        jsr lc_pages
        lda #$D0
        sta lp_st+2
        bit LCBANK2
        bit LCBANK2
        ldx #$10
        jsr lc_pages
        ldx #$20                ; $E000-$FFFF
lc_pages:
        lda lc_alt
        beq :+
        sta ALTZPON
:       ldy #0
lp_ld:  lda $FF00,y
lp_st:  sta $FF00,y
        iny
        bne lp_ld
        inc lp_ld+2
        inc lp_st+2
        dex
        bne lp_ld
        sta ALTZPOFF
        rts

; ---------------------------------------------------------------------------
; the MLI
; ---------------------------------------------------------------------------

open:   sta op_path
        stx op_path+1
        jsr MLI
        .byte $C8
        .word op_parms
        bcs mli_fail
        lda op_ref
        sta rd_ref
        sta cl_ref
        rts

read:   jsr MLI
        .byte $CA
        .word rd_parms
        bcs mli_fail
        rts

read_any:                       ; (a file shorter than the count: its end
        jsr MLI                 ;   is not an error)
        .byte $CA
        .word rd_parms
        bcc :+
        cmp #$4C                ; EOF
        bne mli_fail
:       rts

close:  jsr MLI
        .byte $CC
        .word cl_parms
        bcs mli_fail
        rts

mli_fail:
        pha
        ldx #<s_prodos
        ldy #>s_prodos
        jsr fail_say
        pla
        jsr hex
        lda #PL_DISK
        ; fall through

; bt_stop: A = the stop's code into PL_STATUS; the message is on the
; screen; the loop bt_halt (interrupts masked: the boot's stops all come
; before its CLI)
bt_stop:
        sta PL_STATUS
bt_halt:
        bra bt_halt

; ---------------------------------------------------------------------------
; the text screen
; ---------------------------------------------------------------------------

; say: A = the row, X/Y = the string (0-ended)
say:    phx
        jsr row
        plx
        ; fall through
puts:   stx tmp
        sty tmp+1
        ldy #0
:       lda (tmp),y
        beq :+
        ora #$80
        jsr putc
        iny
        bne :-
:       rts

; fail_say: the stop's message on row 6
fail_say:
        lda #6
        bra say

row:    lsr a               ; rows 0-7: $0400 + $80 x the row
        tax
        lda #0
        ror a
        sta line
        txa
        adc #>$0400             ; (C clear: ror's carry is bit 7 of 0)
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


; ---------------------------------------------------------------------------
; page 1's routine (copied to P1CODE): X bytes (0: 256) from A/Y (low,
; high) of the RamWorks bank selected into BOUNCE, RAMRD on while reading
; ---------------------------------------------------------------------------
p1_code:
        sta P1CODE + (p1_ld - p1_code) + 1
        sty P1CODE + (p1_ld - p1_code) + 2
        ldy #0
        sta RAMRDON
p1_ld:  lda $FFFF,y
        sta BOUNCE,y
        iny
        dex
        bne p1_ld
        sta RAMRDOFF
        rts
p1_end:

; ---------------------------------------------------------------------------
; data
; ---------------------------------------------------------------------------
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
rd_trans:
        .word 0
cl_parms:
        .byte 1
cl_ref: .byte 0
lc_alt: .byte 0
magic:  .byte "A2DM"
status_request:
        .byte 0, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; STATUS, unit 0, selector $80
amem_magic:
        .byte "AMEM", 1

p_catalog:
        .byte 7, "CATALOG"
p_crclist:
        .byte 7, "CRCLIST"
p_lcbin:
        .byte 6, "LC.BIN"

s_title:
        .byte "DOOM: LOADING", 0
s_ready:
        .byte "READY", 0
s_nomusic:
        .byte "NO MUSIC OR EFFECTS: NO NATIVE MODE", 0
s_banks:
        .byte "8 MB OF RAMWORKS NEEDED: NO BANK $", 0
s_nomouse:
        .byte "NO MOUSE CARD IN SLOT 2", 0
s_noamem:
        .byte "NO MEMORY API IN SLOT 7 $", 0
s_prodos:
        .byte "PRODOS ERROR $", 0
s_notbank:
        .byte "NOT A BANK FILE: $", 0
s_crclist:
        .byte "CRCLIST BAD: SEGMENTS $", 0
s_crcbad:
        .byte "CRC BAD: BANK $", 0
s_at:
        .byte " AT $", 0

        .assert p1_end - p1_code <= $40, error, "page 1's routine"
        .assert * <= BOOT_END, error, "the boot passes $3000"
        .assert IOBUF >= STAGE + STAGE_SIZE, error, "ProDOS's buffer"
        .assert DATABUF + DATAMAX <= IOBUF, error, "the data buffer"
        .assert CRCBUF + CRC_MAX <= MLI, error, "CRCLIST's buffer"

; ===========================================================================
.segment "PLRES"
; ===========================================================================
; pl_ready: the ready state's loop (SCREENS.md 2.5 step 5); the second half
; replaces it with the title loop. Each VBL's visit is pl_rvbl.
pl_ready:
        lda vbl_count
pl_ridle:
        cmp vbl_count
        beq pl_ridle
pl_rvbl:
        bra pl_ready
