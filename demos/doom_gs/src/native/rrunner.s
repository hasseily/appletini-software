; RENDER.SYSTEM: the native renderer's whole frame on the card, written
; as a standalone disk of recorded frames for the owner's hardware
; (docs/RENDER-MASKED.md). Not part of the game: it is still linked into
; rcard (render.mk), whose render images and tables the game disk takes
; (playdisk.py), but this boot and runner are on no disk now.
;
; Boot (at $2000, under ProDOS): read CATALOG, then each data file it
; names; their records go into RamWorks banks (the level: segs, map,
; texels, the patch store, the sprite tables and weapon profiles, the
; render window's two images, the FSTEP and math tables, the staging of
; the static tables; and the frames' data), or, bank $FE, into the aux
; card (the trig tables of MEMORY_MAP.md, with ALTZP on, interrupts
; off, no stack or zero page in the loop). Then ProDOS is given up: the
; card image that follows this code in the file ($2800: main card bank 1
; $D000-$DFFF, bank 2 $D000-$DFFF, $E000-$FFFF) goes into the language
; card, the catalog after the runner, and the runner starts.
;
; The runner: the mouse card's VBL interrupt (the clock), the memory API;
; one request of PRIVATE copies puts the static tables into their
; write-expensive pages (main's colormaps, CMPA/CMPB, TEXLO/TEXHI,
; xtoviewangle; aux 0's drawers, FUZZDARK and row tables: MEMORY_MAP.md
; rules 3 and 8, no CPU store ever reaches them). Then for each of the
; catalog's frames:
;   * its data, from the frames' store in RamWorks (records of a
;     destination, an address, a length and run-length coded bytes: main
;     by CPU, aux 0 and RamWorks banks through RAMWRT windows): in the
;     chained mode (the default) the game's state of the frame (the render
;     inputs, the frame block's game fields, the sectors, sides, things,
;     TEXTRANS) and the screen's patch (where its input screen differs from
;     the reference's screen at the frame before's end: the status bar,
;     the message strip, the colours), the renderer's own state carried
;     from the frame before as in the game; the first frame, and every
;     frame in the full mode, from its full data (everything, the
;     renderer's state and the whole input screen too);
;   * SHR left and entered again, then a $Cxxx read: the data's SHR bytes
;     are out before the count (the fast path's lazy mirror flushes when
;     SHR is left; F1.2.1's drain ends before a $Cxxx access);
;   * the whole frame (RENDER-MASKED.md: the front
;     end's window, nr_frame, the masked window, nm_masked, nm_bkload,
;     nb_frame), its VBLs counted;
;   * the CRC-32 of aux 0 $2000-$9FFF (zlib's) against the expected one
;     (the reference's screen at R_DrawLists' return).
; At the end the text screen shows each frame's result (OK or NO, and its
; VBLs), the frames OK, the VBLs of all the frames' rendering and the
; frames a second at 50 Hz (NTSC: x 60 / 50); C runs the frames again
; chained, F fully injected, any other key the same mode again.
;
; The IRQ handler follows the game's contract (docs/MEMORY_MAP.md rule 2):
; zero page $D8-$FF, the stack, $E000-$FFFF and the mouse card only.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import mt_init, far_wload, far_mload, nr_frame, nm_masked
        .import nm_bkload, nb_frame
        .export boot, run_start, run_frame, run_framed, run_key
        .export run_crash, run_table, results, rn_mode, rn_vbls, rn_ok

MLI             = $BF00
RDMAIN          = RAMRDOFF      ; (math.inc's names)
RDAUX           = RAMRDON
WRMAIN          = RAMWRTOFF
WRAUX           = RAMWRTON
BANKSEL         = RWBANK
NEWVIDEO        = $C029
KBD             = $C000
KBDSTRB         = $C010
ALTZPOFF        = $C008
ALTZPON         = $C009
COL80OFF        = $C00C
ALTCHAROFF      = $C00E
INTCXROMOFF     = $C006
TEXTON          = $C051
MIXEDOFF        = $C052
PAGE1           = $C054
LCROM           = $C082
LCBANK2         = $C083
LCBANK1         = $C08B
MOUSE_STATUS    = $C0A0
MOUSE_MODE      = $C0AE
MOUSE_ACK       = $C0AF
MOUSE_ROM       = $C200
MODE_VBL        = $09           ; the card on, with its VBL interrupt
ACK_ALL         = $03

SP_DATA         = $CFF0         ; the memory API's raw FIFO transport in
SP_CTRL         = $CFF1         ;   slot 7 (appletini-one
SP_POP          = $CFF2         ;   README_MEMORY_API.md section 7)
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F           ; (ours: no reply came)

LCIMAGE         = $2800         ; the card image, after the boot code:
LCIMAGE_SIZE    = $4000         ;   bank 1 $D000, bank 2 $D000, $E000
IOBUF           = $6800         ; ProDOS's buffer for the open file
CATBUF          = $6C00         ; the catalog while booting (4 KB)
DATABUF         = $7C00         ; file data, 8 KB at a time
DATAMAX         = $2000

; CATALOG: +0 frames, +1 data files, +2 the start
; mode (0 chained, 1 full), +3 the first frame's number (2), +5 PRIVATE
; descriptors, +6 store banks, +7 VBLs to show a frame; +16 the data
; files' names (16 bytes each: length, name); then the PRIVATE descriptors
; (16 bytes each, the memory API's, with their source banks); then the
; store banks (one byte each: the frames' data run through them in this
; order, $0200-$BFFF of each); then 12 bytes a frame: its chained data's
; position and its full data's (store index, address), the expected CRC.
C_FRAMES        = 0
C_FILES         = 1
C_MODE          = 2
C_FIRST         = 3
C_NDESC         = 5
C_NSTORE        = 6
C_WAIT          = 7
C_NAMES         = 16
F_ENTRY         = 12
F_CHAINED       = 0
F_FULL          = 3
F_CRC           = 6
CAT_MAX         = $0680         ; the catalog's room in the card
MAX_FRAMES      = 100

; records of a data file (boot) and of the frames' data (run): the
; destination (1: $FF main, $80 aux 0, $FE the aux card, else a RamWorks
; bank; 0 ends the data), the address (2), the length (2); a data file's
; bytes follow as they are, a frame's run-length coded: a token t < $80,
; t + 1 bytes; t >= $80, the next byte t - $80 + 3 times
D_END           = $00
D_MAIN          = $FF
D_AUX0          = $80
D_AUXLC         = $FE

; ---------------------------------------------------------------------------
; zero page: the boot's and the loads' (overlay 1: never live across a
; frame's rendering); the IRQ's VBL count ($D8-$FF)
; ---------------------------------------------------------------------------
vbl             = $D8           ; VBLs since the start (IRQ)
waitc           = $DA           ; VBLs left to wait (the IRQ counts down)
bsrc            = $18           ; copies
bdst            = $1A
blen            = $1C
tmp             = $1E           ; (4)
line            = $22           ; text output
col             = $24
wcount          = $25           ; the memory API's reply wait
crc             = $26           ; (4)
in_ptr          = $2A           ; the frames' store: the next page to read
in_idx          = $2C           ;   (its store index), the input page's
in_at           = $2D           ;   next byte, 1 when it holds bytes not
in_len          = $2E           ;   read yet
out_n           = $2F           ; bytes in the output page
rec_dst         = $30           ; the record: its destination, address,
rec_at          = $31           ;   bytes left
rec_left        = $33
run_n           = $35           ; a run: bytes left, its byte, literals
run_b           = $36
run_lit         = $37
sptr            = $38           ; the catalog's store banks
rptr            = $3A           ; the frame's result
num             = $3C           ; a number to print
prod            = $3E           ; (3) the frames a second's product

; ===========================================================================
; boot: runs at $2000 under ProDOS
; ===========================================================================
.segment "BOOT"
boot:   sei
        cld
        ldx     #$FF
        txs
        sta     TEXTON                  ; (no ROM calls: the text page
        sta     MIXEDOFF                ;   directly)
        sta     PAGE1
        sta     COL80OFF
        ldx     #0
        lda     #' ' | $80
:       sta     $0400,x
        sta     $0500,x
        sta     $0600,x
        sta     $0700,x
        inx
        bne     :-
:       lda     msg_load,x
        beq     :+
        sta     $0400,x
        inx
        bra     :-
:       stx     bcol
        lda     #<path_catalog          ; CATALOG
        ldx     #>path_catalog
        jsr     open
        lda     #<CATBUF
        sta     rd_buf
        lda     #>CATBUF
        sta     rd_buf+1
        lda     #<CAT_MAX
        sta     rd_count
        lda     #>CAT_MAX
        sta     rd_count+1
        jsr     read_any
        jsr     close
        stz     bfile
@file:  lda     bfile                   ; each data file
        cmp     CATBUF+C_FILES
        bcc     :+
        jmp     @loaded
:       lda     #'.' | $80
        ldx     bcol
        sta     $0400,x
        inc     bcol
        lda     bfile                   ; its name: C_NAMES + 16 k
        asl     a
        asl     a
        asl     a
        asl     a
        clc
        adc     #<(CATBUF + C_NAMES)
        tay
        lda     #>(CATBUF + C_NAMES)
        adc     #0
        tax
        tya
        jsr     open
@rec:   lda     #<hdr                   ; a record: destination, address,
        sta     rd_buf                  ;   length
        lda     #>hdr
        sta     rd_buf+1
        lda     #5
        sta     rd_count
        stz     rd_count+1
        jsr     read
        lda     hdr
        bne     :+
        jmp     @end
:
@chunk: lda     hdr+4                   ; up to 8 KB at a time
        cmp     #>DATAMAX
        bcc     :+
        lda     #<DATAMAX
        sta     rd_count
        lda     #>DATAMAX
        sta     rd_count+1
        bra     :++
:       lda     hdr+3
        sta     rd_count
        lda     hdr+4
        sta     rd_count+1
:       lda     #<DATABUF
        sta     rd_buf
        lda     #>DATABUF
        sta     rd_buf+1
        jsr     read
        lda     #<DATABUF
        sta     bsrc
        lda     #>DATABUF
        sta     bsrc+1
        lda     hdr+1
        sta     bdst
        lda     hdr+2
        sta     bdst+1
        lda     rd_count
        sta     blen
        lda     rd_count+1
        sta     blen+1
        lda     hdr
        cmp     #D_AUXLC
        bne     @bank
        jsr     aux_lc                  ; the aux card
        bra     @next
@bank:  sta     BANKSEL                 ; a RamWorks bank
        sta     WRAUX
        jsr     copy
        sta     WRMAIN
        stz     BANKSEL
@next:  lda     hdr+1                   ; what is left
        clc
        adc     rd_count
        sta     hdr+1
        lda     hdr+2
        adc     rd_count+1
        sta     hdr+2
        lda     hdr+3
        sec
        sbc     rd_count
        sta     hdr+3
        lda     hdr+4
        sbc     rd_count+1
        sta     hdr+4
        ora     hdr+3
        beq     :+
        jmp     @chunk
:       jmp     @rec
@end:   jsr     close
        inc     bfile
        jmp     @file
@loaded:
        bit     LCBANK1                 ; ProDOS goes: the card image, bank
        bit     LCBANK1                 ;   1, then bank 2 and $E000-$FFFF
        lda     #<LCIMAGE
        sta     bsrc
        lda     #>LCIMAGE
        sta     bsrc+1
        stz     bdst
        lda     #$D0
        sta     bdst+1
        stz     blen
        lda     #$10
        sta     blen+1
        jsr     copy
        bit     LCBANK2
        bit     LCBANK2
        lda     #<(LCIMAGE + $1000)
        sta     bsrc
        lda     #>(LCIMAGE + $1000)
        sta     bsrc+1
        stz     bdst
        lda     #$D0
        sta     bdst+1
        stz     blen
        lda     #$30
        sta     blen+1
        jsr     copy
        bit     LCBANK1                 ; (bank 1, as outside the replay)
        bit     LCBANK1
        lda     #<CATBUF                ; the catalog, into the card
        sta     bsrc
        lda     #>CATBUF
        sta     bsrc+1
        lda     #<catalog
        sta     bdst
        lda     #>catalog
        sta     bdst+1
        lda     #<CAT_MAX
        sta     blen
        lda     #>CAT_MAX
        sta     blen+1
        jsr     copy
        jmp     run_start

; aux_lc: blen bytes from bsrc to the aux card at a2vm's address bdst
; ($C000-$CFFF: bank 1 at $D000; $D000-$DFFF: bank 2; $E000-$FFFF), ALTZP
; on, interrupts off, the loop with absolute operands (the aux zero page
; and stack are live)
aux_lc: lda     bdst+1
        cmp     #$D0
        bcs     :+
        adc     #$10                    ; bank 1: $C000 is $D000
        sta     bdst+1
        lda     #$8B                    ; LCBANK1
        bra     :++
:       lda     #$83                    ; LCBANK2 ($E000 up: either)
:       sta     @sw1+1
        sta     @sw2+1
        lda     bsrc                    ; the loop's operands
        sta     @ld+1
        lda     bsrc+1
        sta     @ld+2
        lda     bdst
        sta     @st+1
        lda     bdst+1
        sta     @st+2
        lda     blen
        sta     @cnt
        lda     blen+1
        sta     @cnt+1
        sta     ALTZPON
@sw1:   bit     $C08B                   ; (patched)
@sw2:   bit     $C08B
@ld:    lda     $FFFF                   ; (patched)
@st:    sta     $FFFF
        inc     @ld+1
        bne     :+
        inc     @ld+2
:       inc     @st+1
        bne     :+
        inc     @st+2
:       lda     @cnt
        bne     :+
        dec     @cnt+1
:       dec     @cnt
        lda     @cnt
        ora     @cnt+1
        bne     @ld
        sta     ALTZPOFF
        bit     LCROM                   ; (ProDOS's: ROM read)
        rts
@cnt:   .res    2

; copy: blen bytes from bsrc to bdst, forward (blen > 0)
copy:   ldy     #0
        ldx     blen+1
        beq     @rest
@page:  lda     (bsrc),y
        sta     (bdst),y
        iny
        bne     @page
        inc     bsrc+1
        inc     bdst+1
        dex
        bne     @page
@rest:  ldx     blen
        beq     @done
@byte:  lda     (bsrc),y
        sta     (bdst),y
        iny
        dex
        bne     @byte
@done:  rts

open:   sta     op_path
        stx     op_path+1
        jsr     MLI
        .byte   $C8
        .word   op_parms
        bcs     boot_fail
        lda     op_ref
        sta     rd_ref
        sta     cl_ref
        rts

read:   jsr     MLI
        .byte   $CA
        .word   rd_parms
        bcs     boot_fail
        rts

read_any:                               ; (a file shorter than the count:
        jsr     MLI                     ;   its end is not an error)
        .byte   $CA
        .word   rd_parms
        bcc     :+
        cmp     #$4C                    ; EOF
        bne     boot_fail
:       rts

close:  jsr     MLI
        .byte   $CC
        .word   cl_parms
        rts

boot_fail:
        tay
        ldx     #0
:       lda     msg_fail,x
        beq     :+
        sta     $0480,x
        inx
        bra     :-
:       tya                             ; the ProDOS error, in hex
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     bf_digit
        tya
        and     #$0F
        jsr     bf_digit
boot_stop:
        bra     boot_stop
bf_digit:
        cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0' | $80
        sta     $0480,x
        inx
        rts

op_parms:
        .byte   3
op_path:
        .word   0
        .word   IOBUF
op_ref: .byte   0
rd_parms:
        .byte   4
rd_ref: .byte   0
rd_buf: .word   0
rd_count:
        .word   0
        .word   0
cl_parms:
        .byte   1
cl_ref: .byte   0
hdr:    .res    5
bcol:   .res    1
bfile:  .res    1

path_catalog:
        .byte   7, "CATALOG"
msg_load:
        .repeat .strlen("NATIVE RENDERER: LOADING"), I
        .byte   .strat("NATIVE RENDERER: LOADING", I) | $80
        .endrep
        .byte   0
msg_fail:
        .repeat .strlen("PRODOS ERROR $"), I
        .byte   .strat("PRODOS ERROR $", I) | $80
        .endrep
        .byte   0
        .assert * <= LCIMAGE, error, "the boot code overlaps the card image"
        .assert IOBUF >= LCIMAGE + LCIMAGE_SIZE, error, "ProDOS's buffer"
        .assert CATBUF >= IOBUF + $400, error, "the catalog's buffer"
        .assert DATABUF >= CATBUF + CAT_MAX, error, "the data buffer"
        .assert DATABUF + DATAMAX <= $BF00, error, "the data buffer's end"

; ===========================================================================
; the runner: the main language card's $E000 part (segment DRIVER)
; ===========================================================================
.segment "DRIVER"
run_start:
        sei
        cld
        ldx     #$FF
        txs
        sta     RDMAIN
        sta     WRMAIN
        sta     ALTZPOFF
        stz     BANKSEL
        bit     LCBANK1                 ; bank 1, as outside the replay
        bit     LCBANK1
        stz     vbl
        stz     vbl+1
        stz     waitc
        jsr     mt_init
        jsr     crc_tables
        jsr     mouse_init
        bcc     :+
        ldx     #msg_nomouse - messages
        jmp     fatal
:       jsr     amem_probe
        bcc     :+
        ldx     #msg_noamem - messages
        jmp     fatal_code
:       jsr     statics                 ; the static tables (PRIVATE)
        lda     catalog+C_MODE
        sta     rn_mode
        cli
run_again:
        stz     rn_frame
        stz     rn_ok
        stz     rn_vbls
        stz     rn_vbls+1
rn_loop:
        lda     rn_frame
        cmp     catalog+C_FRAMES
        bcs     rn_table
        jsr     frame_data              ; its data (chained or full)
        lda     #$41                    ; the data's SHR bytes out before
        sta     NEWVIDEO                ;   the count: SHR left (the lazy
        lda     #$C1                    ;   mirror of the fast path flushes
        sta     NEWVIDEO                ;   there), SHR on, then a $Cxxx
        bit     KBD                     ;   read (it waits for the drain)
        sei                             ; the frame, its VBLs counted
        lda     vbl
        sta     rn_t0
        lda     vbl+1
        sta     rn_t0+1
        cli
run_frame:
        jsr     far_wload               ; RENDER-MASKED.md
        jsr     nr_frame
        jsr     far_mload
        jsr     nm_masked
        jsr     nm_bkload
        jsr     nb_frame
run_framed:
        sei
        sec
        lda     vbl
        sbc     rn_t0
        sta     tmp
        lda     vbl+1
        sbc     rn_t0+1
        sta     tmp+1
        cli
        lda     tmp                     ; the rendering's VBLs, in all
        clc
        adc     rn_vbls
        sta     rn_vbls
        lda     tmp+1
        adc     rn_vbls+1
        sta     rn_vbls+1
        jsr     screen_crc
        jsr     result                  ; its CRC, VBLs, OK
        lda     catalog+C_WAIT          ; show it
        jsr     wait
        inc     rn_frame
        jmp     rn_loop
rn_table:
        jsr     show_table
run_table:
run_key:
        lda     KBD
        bpl     run_key
        sta     KBDSTRB
        and     #$DF                    ; (upper case)
        cmp     #'C' | $80
        bne     :+
        stz     rn_mode
:       cmp     #'F' | $80
        bne     :+
        lda     #1
        sta     rn_mode
:       jmp     run_again

; result: the frame's result (rptr: results + 8 frame): its CRC (4), its
; VBLs (tmp, 2), 1 when the CRC is the expected one
result: lda     rn_frame
        jsr     fentry                  ; bsrc = its catalog entry
        jsr     rentry
        ldy     #0
        stz     tmp+2                   ; (a byte differs)
:       lda     crc,y
        sta     (rptr),y
        phy
        pha
        tya
        clc
        adc     #F_CRC
        tay
        pla
        cmp     (bsrc),y
        beq     :+
        inc     tmp+2
:       ply
        iny
        cpy     #4
        bcc     :--
        lda     tmp                     ; the VBLs
        sta     (rptr),y
        iny
        lda     tmp+1
        sta     (rptr),y
        iny
        lda     tmp+2                   ; OK
        bne     :+
        inc     rn_ok
        lda     #1
        sta     (rptr),y
        rts
:       lda     #0
        sta     (rptr),y
        rts

; rentry: rptr = results + 8 rn_frame
rentry: lda     rn_frame
        stz     rptr+1
        asl     a
        rol     rptr+1
        asl     a
        rol     rptr+1
        asl     a
        rol     rptr+1
        clc
        adc     #<results
        sta     rptr
        lda     rptr+1
        adc     #>results
        sta     rptr+1
        rts

; fentry: bsrc = the catalog entry of frame A (after the names, the
; descriptors and the store banks); sptr = the store banks
fentry: sta     tmp+3
        lda     catalog+C_FILES         ; C_NAMES + 16 (files + descriptors)
        clc
        adc     catalog+C_NDESC
        stz     bsrc+1
        asl     a
        rol     bsrc+1
        asl     a
        rol     bsrc+1
        asl     a
        rol     bsrc+1
        asl     a
        rol     bsrc+1
        clc
        adc     #<(catalog + C_NAMES)
        sta     sptr
        lda     bsrc+1
        adc     #>(catalog + C_NAMES)
        sta     sptr+1
        clc                             ; + the store banks
        lda     sptr
        adc     catalog+C_NSTORE
        sta     bsrc
        lda     sptr+1
        adc     #0
        sta     bsrc+1
        ldx     tmp+3                   ; + 12 frame
        beq     @done
:       clc
        lda     bsrc
        adc     #F_ENTRY
        sta     bsrc
        bcc     :+
        inc     bsrc+1
:       dex
        bne     :--
@done:  rts

; ---------------------------------------------------------------------------
; frame_data: the frame's data (the chained data but for the first frame
; or in the full mode) from the store into its destinations
; ---------------------------------------------------------------------------
frame_data:
        lda     rn_frame
        jsr     fentry
        ldy     #F_CHAINED
        lda     rn_mode
        bne     @full
        lda     rn_frame
        bne     @pos
@full:  ldy     #F_FULL
@pos:   lda     (bsrc),y                ; its position: store index, page
        sta     in_idx
        iny
        iny
        lda     (bsrc),y
        sta     in_ptr+1
        stz     in_ptr
        stz     in_len
        stz     in_at
@rec:   jsr     getb                    ; a record: destination, address,
        sta     rec_dst                 ;   length
        cmp     #D_END
        beq     @done
        jsr     getb
        sta     rec_at
        jsr     getb
        sta     rec_at+1
        jsr     getb
        sta     rec_left
        jsr     getb
        sta     rec_left+1
        stz     out_n
        stz     run_n
@byte:  lda     rec_left                ; its bytes, a page at a time
        ora     rec_left+1
        beq     @last
        jsr     rle                     ; A = the next decoded byte
        ldx     out_n
        sta     bounce,x
        inx
        stx     out_n
        lda     rec_left
        bne     :+
        dec     rec_left+1
:       dec     rec_left
        cpx     #0                      ; (a page: 256 bytes)
        bne     @byte
        jsr     flush
        bra     @byte
@last:  lda     out_n
        beq     @rec
        jsr     flush
        bra     @rec
@done:  rts

; rle: the next decoded byte of the record
rle:    lda     run_n
        bne     @have
        jsr     getb                    ; a token
        cmp     #$80
        bcs     @rep
        inc     a                       ; t + 1 literals
        sta     run_n
        lda     #1
        sta     run_lit
        bra     @have
@rep:   sec
        sbc     #$80 - 3                ; t - $80 + 3 of the next byte
        sta     run_n
        jsr     getb
        sta     run_b
        stz     run_lit
@have:  dec     run_n
        lda     run_lit
        bne     getb                    ; a literal: the next input byte
        lda     run_b
        rts

; getb: A = the next byte of the frames' store, read a page into the card
; at a time through a RAMRD window (X, Y kept). The data start at a page.
getb:   phx
        lda     in_len
        bne     :+
        jsr     fill
:       ldx     in_at
        lda     inbuf,x
        inx
        stx     in_at
        bne     :+
        stz     in_len                  ; (the page is read)
:       plx
        rts
fill:   phy
        ldy     in_idx                  ; the store bank
        lda     (sptr),y
        sta     BANKSEL
        sta     RDAUX
        ldy     #0
:       lda     (in_ptr),y
        sta     inbuf,y
        iny
        bne     :-
        sta     RDMAIN
        stz     BANKSEL
        inc     in_ptr+1                ; the next page; at $C000 the next
        lda     in_ptr+1                ;   store bank from $0200
        cmp     #$C0
        bcc     :+
        lda     #$02
        sta     in_ptr+1
        inc     in_idx
:       lda     #1
        sta     in_len
        ply
        rts

; flush: out_n bytes (0: 256) of bounce to the record's destination
; (rec_at), which moves on
flush:  lda     rec_dst
        cmp     #D_MAIN
        beq     @main
        cmp     #D_AUX0
        bne     :+
        lda     #0
:       sta     BANKSEL
        sta     WRAUX
@main:  lda     rec_at
        sta     bdst
        lda     rec_at+1
        sta     bdst+1
        ldy     #0
:       lda     bounce,y
        sta     (bdst),y
        iny
        cpy     out_n
        bne     :-
        sta     WRMAIN
        stz     BANKSEL
        lda     out_n                   ; the address past them
        bne     :+
        inc     rec_at+1
        bra     @done
:       clc
        adc     rec_at
        sta     rec_at
        bcc     @done
        inc     rec_at+1
@done:  stz     out_n
        rts

; ---------------------------------------------------------------------------
; statics: the static tables into their write-expensive pages, one request
; of the catalog's PRIVATE descriptors
; ---------------------------------------------------------------------------
statics:
        lda     catalog+C_NDESC         ; the request: CONTROL, unit 0,
        asl     a                       ;   selector $80, the list's length,
        asl     a                       ;   its header, the descriptors
        asl     a
        asl     a
        sta     tmp
        clc
        adc     #8
        sta     rq_len
        lda     catalog+C_NDESC
        sta     rq_count
        ldx     #0
:       lda     rq_head,x
        sta     bounce,x
        inx
        cpx     #RQ_HEAD
        bcc     :-
        lda     catalog+C_FILES         ; the descriptors, after the names
        asl     a
        asl     a
        asl     a
        asl     a
        tay
        ldx     #RQ_HEAD
:       lda     catalog+C_NAMES,y
        sta     bounce,x
        iny
        inx
        dec     tmp
        bne     :-
        lda     #<bounce
        sta     bsrc
        lda     #>bounce
        sta     bsrc+1
        php
        sei
        jsr     amem_send
        bit     SP_RELEASE
        plp
        cmp     #0
        beq     :+
        ldx     #msg_amem - messages
        jmp     fatal_code
:       rts
RQ_HEAD = 10 + 2 + 8
rq_head:
        .byte   4, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; CONTROL, unit 0, selector $80
rq_len: .word   0
        .byte   "AMEM", 1
rq_count:
        .byte   0, 0, 0

; ---- the memory API (appletini-one README_MEMORY_API.md) ----

; amem_probe: C clear when slot 7 has the API with PRIVATE copies
amem_probe:
        php
        sei
        bit     SP_RELEASE
        lda     SP_ROM+1                ; the Appletini SmartPort ROM
        cmp     #$20
        bne     @absent
        lda     SP_ROM+3
        ora     SP_ROM+7
        bne     @absent
        lda     SP_ROM+5
        cmp     #3
        bne     @absent
        lda     SP_CTRL                 ; its raw transport
        and     #$3F
        cmp     #$20
        bne     @absent
        lda     #<status_request
        sta     bsrc
        lda     #>status_request
        sta     bsrc+1
        ldx     #10
        jsr     amem_send
        cmp     #0
        bne     @fail
        lda     SP_DATA                 ; the length: 32
        sta     SP_POP
        cmp     #32
        bne     @bad
        lda     SP_DATA
        sta     SP_POP
        bne     @bad
        ldx     #0
:       lda     SP_DATA
        sta     SP_POP
        sta     bounce,x
        inx
        cpx     #32
        bcc     :-
        ldx     #4                      ; "AMEM", version 1
:       lda     bounce,x
        cmp     amem_magic,x
        bne     @bad
        dex
        bpl     :-
        lda     bounce+6                ; descriptors of 16 bytes
        cmp     #16
        bne     @bad
        lda     bounce+7                ; as many as the statics'
        cmp     catalog+C_NDESC
        bcc     @bad
        lda     bounce+8                ; COPY, FILL, PRIVATE
        and     #7
        cmp     #7
        bne     @bad
        lda     bounce+15               ; available
        and     #1
        beq     @bad
        bit     SP_RELEASE
        plp
        clc
        rts
@absent:
        lda     #$FF
        bra     @fail
@bad:   lda     #$FE
@fail:  bit     SP_RELEASE
        plp
        sec
        rts

; amem_send: X bytes from (bsrc) into the FIFO, execute, wait for the
; reply and pop its first byte: A = the SmartPort result
amem_send:
        bit     SP_RELEASE
        bit     SP_ROM
        stx     tmp
        ldy     #0
:       lda     (bsrc),y
        sta     SP_DATA
        iny
        cpy     tmp
        bne     :-
        lda     #2
        sta     SP_CTRL
        ldx     #0
        ldy     #0
        stz     wcount
@wait:  lda     SP_CTRL
        bmi     @ready
        dex
        bne     @wait
        dey
        bne     @wait
        dec     wcount
        bne     @wait
        lda     #AMEM_TIMEOUT
        rts
@ready: lda     SP_DATA
        sta     SP_POP
        rts

status_request:
        .byte   0, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; STATUS, unit 0, selector $80
amem_magic:
        .byte   "AMEM", 1

; wait: A VBLs
wait:   sta     waitc
:       lda     waitc
        bne     :-
        rts

; ---- CRC-32 of aux 0 $2000-$9FFF (zlib's: reflected, $EDB88320) ----
screen_crc:
        lda     #$FF
        sta     crc
        sta     crc+1
        sta     crc+2
        sta     crc+3
        stz     bsrc
        lda     #$20
        sta     bsrc+1
        sta     RDAUX                   ; ($C073 is 0: aux 0)
        ldy     #0
@byte:  lda     (bsrc),y
        eor     crc
        tax
        lda     crc+1
        eor     crc_t0,x
        sta     crc
        lda     crc+2
        eor     crc_t1,x
        sta     crc+1
        lda     crc+3
        eor     crc_t2,x
        sta     crc+2
        lda     crc_t3,x
        sta     crc+3
        iny
        bne     @byte
        inc     bsrc+1
        lda     bsrc+1
        cmp     #$A0
        bcc     @byte
        sta     RDMAIN
        ldx     #3
:       lda     crc,x
        eor     #$FF
        sta     crc,x
        dex
        bpl     :-
        rts

crc_tables:
        ldx     #0
@entry: stx     crc
        stz     crc+1
        stz     crc+2
        stz     crc+3
        ldy     #8
@bit:   lsr     crc+3
        ror     crc+2
        ror     crc+1
        ror     crc
        bcc     :+
        lda     crc
        eor     #$20
        sta     crc
        lda     crc+1
        eor     #$83
        sta     crc+1
        lda     crc+2
        eor     #$B8
        sta     crc+2
        lda     crc+3
        eor     #$ED
        sta     crc+3
:       dey
        bne     @bit
        lda     crc
        sta     crc_t0,x
        lda     crc+1
        sta     crc_t1,x
        lda     crc+2
        sta     crc_t2,x
        lda     crc+3
        sta     crc_t3,x
        inx
        bne     @entry
        rts

; ---- the mouse card: C set when there is none ----
mouse_init:
        sta     INTCXROMOFF
        lda     MOUSE_ROM+$05
        cmp     #$38
        bne     @none
        lda     MOUSE_ROM+$07
        cmp     #$18
        bne     @none
        lda     MOUSE_ROM+$0B
        cmp     #$01
        bne     @none
        lda     MOUSE_ROM+$0C
        cmp     #$20
        bne     @none
        lda     #ACK_ALL
        sta     MOUSE_ACK
        lda     #MODE_VBL
        sta     MOUSE_MODE
        clc
        rts
@none:  sec
        rts

; ---- the interrupt: VBLs; a BRK is the frame's stop (its STATUS) ----
irq:    pha
        phx
        tsx
        lda     $0103,x
        and     #$10
        bne     @brk
        ldx     MOUSE_STATUS
        lda     #ACK_ALL
        sta     MOUSE_ACK
        txa
        and     #$08
        beq     @done
        inc     vbl
        bne     :+
        inc     vbl+1
:       lda     waitc
        beq     @done
        dec     waitc
@done:  plx
        pla
        rti
@brk:   lda     STATUS
        ldx     #msg_crash - messages
        bra     fatal_code

; fatal_code: fatal, then A in hex
fatal_code:
        sei
        pha
        jsr     fatal_text
        pla
        jsr     hex
:       bra     :-

; fatal: text screen, the message at messages + X, stop
fatal:  sei
        jsr     fatal_text
:       bra     :-

fatal_text:
run_crash:
        stz     MOUSE_MODE
        sta     RDMAIN
        sta     WRMAIN
        stz     BANKSEL
        bit     LCBANK1
        bit     LCBANK1
        phx
        jsr     text_mode
        plx
        stz     line
        lda     #$04
        sta     line+1
        stz     col
        jmp     print

; ---- the table: 5 frames a row (OK or NO, VBLs), then the summary ----
show_table:
        jsr     text_mode
        lda     #0
        jsr     row
        ldx     #msg_title - messages
        jsr     print
        lda     catalog+C_FIRST
        sta     num
        lda     catalog+C_FIRST+1
        sta     num+1
        jsr     dec5
        lda     #' ' | $80
        jsr     putc
        ldx     #msg_chained - messages
        lda     rn_mode
        beq     :+
        ldx     #msg_full - messages
:       jsr     print
        stz     rn_frame
@row:   lda     rn_frame
        cmp     catalog+C_FRAMES
        bcs     @sum
        ldx     #0                      ; row 1 + frame / 5, column 8 (frame
:       cmp     #5                      ;   % 5)
        bcc     :+
        sbc     #5
        inx
        bra     :-
:       asl     a
        asl     a
        asl     a
        pha
        txa
        inc     a
        jsr     row
        pla
        sta     col
        jsr     rentry
        ldy     #6                      ; OK or NO
        lda     (rptr),y
        beq     @no
        lda     #'O' | $80
        jsr     putc
        lda     #'K' | $80
        bra     :+
@no:    lda     #'N' | $80
        jsr     putc
        lda     #'O' | $80
:       jsr     putc
        ldy     #4                      ; the VBLs, 3 digits
        lda     (rptr),y
        sta     num
        iny
        lda     (rptr),y
        sta     num+1
        jsr     dec3
        inc     rn_frame
        bra     @row
@sum:   lda     #22
        jsr     row
        ldx     #msg_ok - messages
        jsr     print
        lda     rn_ok
        sta     num
        stz     num+1
        jsr     dec3
        ldx     #msg_vbl - messages
        jsr     print
        lda     rn_vbls
        sta     num
        lda     rn_vbls+1
        sta     num+1
        jsr     dec5
        ldx     #msg_fps - messages
        jsr     print
        jsr     fps                     ; frames x 500 / VBLs: tenths
        jsr     dec5
        lda     #23
        jsr     row
        ldx     #msg_key - messages
        jmp     print

; fps: num = frames * 500 / rn_vbls rounded down, the frames a second at
; 50 Hz in tenths (0 when no VBL). prod: frames * 500 (24 bits)
fps:    stz     prod
        stz     prod+1
        stz     prod+2
        ldx     catalog+C_FRAMES        ; (a sum: at most 100 * 500)
        beq     @div0
:       clc
        lda     prod
        adc     #<500
        sta     prod
        lda     prod+1
        adc     #>500
        sta     prod+1
        bcc     :+
        inc     prod+2
:       dex
        bne     :--
@div0:  stz     num                     ; / VBLs, 24 by 16 bits: the
        stz     num+1                   ;   quotient into num (16 bits)
        lda     rn_vbls
        ora     rn_vbls+1
        beq     @done
        stz     tmp                     ; the remainder
        stz     tmp+1
        ldx     #24
@div:   asl     prod
        rol     prod+1
        rol     prod+2
        rol     tmp
        rol     tmp+1
        asl     num
        rol     num+1
        lda     tmp
        sec
        sbc     rn_vbls
        tay
        lda     tmp+1
        sbc     rn_vbls+1
        bcc     @next
        sta     tmp+1
        sty     tmp
        inc     num
@next:  dex
        bne     @div
@done:  rts

; dec3, dec5: num in decimal, 3 or 5 digits, leading blanks (num lost)
dec3:   ldx     #2
        bra     decn
dec5:   ldx     #0
decn:   stz     crc                     ; a digit printed yet
@digit: ldy     #0
@sub:   lda     num
        sec
        sbc     powers_lo,x
        pha
        lda     num+1
        sbc     powers_hi,x
        bcc     @done1
        sta     num+1
        pla
        sta     num
        iny
        bra     @sub
@done1: pla
        tya
        bne     @print
        lda     crc
        bne     @print
        cpx     #4                      ; always the units digit
        bcs     @print
        lda     #' ' | $80
        bra     @put
@print: inc     crc
        tya
        ora     #'0' | $80
@put:   jsr     putc
        inx
        cpx     #5
        bcc     @digit
        rts
powers_lo:
        .byte   <10000, <1000, <100, <10, <1
powers_hi:
        .byte   >10000, >1000, >100, >10, >1

text_mode:
        lda     #$01                    ; SHR off
        sta     NEWVIDEO
        sta     TEXTON
        sta     MIXEDOFF
        sta     PAGE1
        sta     COL80OFF
        sta     ALTCHAROFF
        ldx     #0                      ; blank the text page
        lda     #' ' | $80
:       sta     $0400,x
        sta     $0500,x
        sta     $0600,x
        sta     $0700,x
        inx
        bne     :-
        rts

; row: line = the text address of row A, col = 0
row:    tax
        lda     text_lo,x
        sta     line
        lda     text_hi,x
        sta     line+1
        stz     col
        rts

putc:   phy
        ldy     col
        sta     (line),y
        inc     col
        ply
        rts

hex:    pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     @digit
        pla
        and     #$0F
@digit: cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0' | $80
        jmp     putc

; print: the message at messages + X (0 ends it)
print:  lda     messages,x
        beq     @done
        ora     #$80
        jsr     putc
        inx
        bra     print
@done:  rts

text_lo:
        .repeat 24, R
        .byte   <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
text_hi:
        .repeat 24, R
        .byte   >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep

messages:
msg_title:
        .byte   "RENDER: DEMO3 FRAMES FROM ", 0
msg_chained:
        .byte   "CHAINED", 0
msg_full:
        .byte   "FULL", 0
msg_ok:
        .byte   "OK ", 0
msg_vbl:
        .byte   "  VBL ", 0
msg_fps:
        .byte   "  FPS X10 ", 0
msg_key:
        .byte   "C: CHAINED, F: FULL, ELSE AGAIN", 0
msg_nomouse:
        .byte   "NO MOUSE CARD IN SLOT 2: NO VBL CLOCK", 0
msg_crash:
        .byte   "THE FRAME STOPPED (BRK), STATUS $", 0
msg_noamem:
        .byte   "NO MEMORY API IN SLOT 7 (F1.1.4 OR LATER) $", 0
msg_amem:
        .byte   "MEMORY API ERROR $", 0

; ---------------------------------------------------------------------------
.segment "DESC"
catalog:        .res    CAT_MAX
rn_mode:        .res    1       ; 0 chained, 1 full
rn_frame:       .res    1
rn_ok:          .res    1
rn_vbls:        .res    2       ; the rendering's VBLs, all frames
rn_t0:          .res    2
results:        .res    8 * MAX_FRAMES  ; CRC (4), VBLs (2), OK (1), pad
bounce:         .res    256
inbuf:          .res    256
crc_t0:         .res    256
crc_t1:         .res    256
crc_t2:         .res    256
crc_t3:         .res    256

.segment "VECTORS"
        .word   irq                     ; NMI
        .word   run_start               ; reset
        .word   irq                     ; IRQ, BRK
