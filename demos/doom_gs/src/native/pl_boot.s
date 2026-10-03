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
;      bytes and the Appletini's own: probe_mouse, mo_check; without the
;      Appletini's card the clock is the Phasor's VIA-B timer 1, and
;      without that either the stop PL_NOMOUSE, docs/PLAY.md 20); the
;      memory API in slot 7 (COPY, FILL,
;      PRIVATE: probe_amem; without it a message, and the game goes on
;      with the CPU's copies: step 4's am_patch; docs/PLAY.md 19);
;      snd_probe (no native mode: a message, the game goes on without
;      music or effects, the effect player off);
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
;   5. bt_init: the mouse card's VBL on (mode $09, masked), or without
;      the Appletini's card mo_recs and bt_mpatch's records (the handler
;      on VIA-B's timer 1, no mouse read: tools/native/nomouse.py); then
;      (without the memory API) am_patch writes bt_patch's records: the
;      transport's CPU version over the card, each W image's walker over its own
;      transport in its bank, tools/native/amcpu.py), pl_init (the input
;      block, the key table, the mouse's window), snd_init, fx_init with
;      snd_probe's answer, pl_clkset (PAL until pl_detect), CLI,
;      bt_detect (PAL or NTSC: its clock; pl_detect with the mouse card,
;      else the VBL flag timed by VIA-B's timer, which then runs at a
;      frame's period, and row 5 says so), PL_STATUS = PL_READY, and the
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
        .import pl_vbody, pl_vnone, pl_crash, pl_iwin, pl_defaults
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
MOUSE_ROOM      = 44            ; probe_mouse's bytes in A (fd3ce9fd)
RDVBLBAR        = $C019         ; bit 7 low in the vertical blanking
VIA_B_T1CL      = $C484         ; the Phasor's VIA-B, timer 1 (both modes;
VIA_B_T1CH      = $C485         ;   a Mockingboard's second VIA too)
VIA_B_T1LL      = $C486
VIA_B_T1LH      = $C487
VIA_B_ACR       = $C48B
VIA_B_IFR       = $C48D
VIA_B_IER       = $C48E
ACR_FREE        = $40           ; ACR: timer 1 free-running, no PB7 output
IFR_T1          = $40           ; IFR and IER bit 6: timer 1
PAL_FRAME       = 20280         ; bus cycles a frame: 312 lines of 65
NTSC_FRAME      = 17030         ;   and 262
T1_PAL          = PAL_FRAME - 2 ; VIA-B's latch: free-running, a 6522's
T1_NTSC         = NTSC_FRAME - 2 ;  timer 1 times out every latch + 2
FRAME_WIN       = 512           ; a frame's count: within this of either
FRAME_MIN       = $40           ; a measured frame's high byte: at least
                                ;   16,384 counts (under NTSC's window)
FRAME_FIX       = 11            ; the latch from a measured frame: + the
                                ;   13 counts from its reading to the
                                ;   restart (vb_edge), less 2
SP_DATA         = $CFF0         ; the memory API's FIFO (slot 7)
SP_CTRL         = $CFF1
SP_POP          = $CFF2
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F
AMEM_MAX        = 16            ; descriptors a request (llayout.AMEM_MAX)
AMEM_WAIT       = 4             ; STATUS's wait: 64 K turns times this
PROBE_ROOM      = 215           ; probe_amem's bytes in A (fd3ce9fd)
PATCH_SIZE      = 512           ; am_patch's table (amcpu.PATCH_SIZE)
MPATCH_SIZE     = 52            ; bt_mpatch (nomouse.MPATCH_SIZE)

SND_MUSIC       = 0             ; snd_probe's answer: native mode
STD_PAL         = 0             ; pl_clkset's standard
STD_NTSC        = $80
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
        jsr probe_amem          ; none: bt_amem's bit 7 (its message)
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
        bra :+                  ; (bt_init: the mouse card's VBL on, still
        .res 8                  ;   masked; A's ACK and mode had this room)
:       jsr bt_init             ; (am_patch without the memory API), then
                                ;   pl_init: the input, the key table
        jsr snd_init
        lda bt_music
        jsr fx_init             ; A: snd_probe's answer
        lda #STD_PAL
        jsr pl_clkset           ; the clock defined until pl_detect
        cli
        jsr bt_detect           ; PAL or NTSC, the clock from 0
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

; probe_mouse: the Appletini's mouse card in slot 2: its ROM's AppleMouse
; ID bytes, as A's probe read them, then mo_check its own bytes (an
; AppleMouse II has the same ID bytes but not the Appletini's register
; model). Else bt_mouse $FF and the clock is VIA-B's timer 1, or the stop
; when there is none (mo_none). In A's room (MOUSE_ROOM): the routines
; after it keep their addresses.
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
        jmp mo_check
@none:  jmp mo_none
        .assert * - probe_mouse <= MOUSE_ROOM, error, "probe_mouse's room"
        .res MOUSE_ROOM - (* - probe_mouse)

; probe_amem: the memory API in slot 7 (appletini-one README_MEMORY_API.md
; sections 1, 2 and 7) with COPY, FILL and PRIVATE, available: returns
; with bt_amem 0. Else bt_amem $FF (bit 7: the CPU's copies) and row 3
; says so with the answer ($FF no Appletini SmartPort ROM in slot 7, $FE a
; capability missing or the API unavailable, $6F no reply, else the
; STATUS call's error). Nothing is written to slot 7 before its bytes read
; as the Appletini's, twice over (an empty slot reads the floating bus):
; the SmartPort ID bytes $C701, $C703, $C705, $C707 ($20, $00, $03, $00: a
; Disk II's $C707 is $3C), the ProDOS entry's offset $C7FF ($0A: the
; SmartPort entry $C70D), then in its C8 space the FIFO's control register
; $CFF1, bits 0-5 $20 (vTW's flag, no reply pending); only then the STATUS
; request goes into the FIFO ($CFF0, $CFF1). The reply is waited for
; AMEM_WAIT times 64 K turns (about 0.5 s on the card, four times am_fin's
; wait for a CONTROL), so that a card whose ROM shows those bytes but does
; not answer holds the boot that long, not the 33 s of a CONTROL's wait.
; At A's place in PLBOOT, in A's room (PROBE_ROOM): everything after it in
; DOOM.SYSTEM stays where it was, so the boot's time with the API is A's
; (docs/PLAY.md 19: the CRC loop's TURBO read-cache sets).
probe_amem:
        sta INTCXROMOFF
        bit SP_RELEASE          ; (no card's C8 space selected)
        lda #2                  ; each byte twice
        sta wcount
@twice: ldx #PR_N - 1
@id:    ldy pr_at,x             ; the slot ROM's bytes
        lda SP_ROM,y
        cmp pr_is,x
        bne @absent
        dex
        bpl @id
        lda SP_CTRL             ; (slot 7's C8 space: its ROM was read)
        and #$3F
        cmp #$20
        bne @absent
        dec wcount
        bne @twice
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
        lda #AMEM_WAIT
        sta wcount
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
@absent:
        lda #$FF
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
@bad:   lda #$FE
@fail:  bit SP_RELEASE
        dec bt_amem             ; $FF: the CPU's copies
        jmp am_none             ; (PLAMEM: the message)
        .assert * - probe_amem <= PROBE_ROOM, error, "probe_amem's room"
        .res PROBE_ROOM - (* - probe_amem)

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
s_noclock:                      ; (in A's s_nomouse and s_noamem: the
        .byte "NO CLOCK: NO APPLETINI MOUSE OR PHASOR", 0 ; strings and the
s_pal:  .byte "PAL", 0          ;   parts after DOOM.SYSTEM's PLBOOT stay
s_ntsc: .byte "NTSC", 0         ;   put)
        .res 50 - (* - s_noclock)
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
.segment "PLAMEM"
; ===========================================================================
; Without the memory API, the CPU's copies (docs/PLAY.md 19): the message
; and the patch, in a segment of their own after the boot's (pl_boot.s's
; own code, PLBOOT, keeps its 2 KB budget and A's layout: probe_amem).

; am_none: probe_amem's answer A on row 3 (nothing else runs it)
am_none:
        pha
        lda #3
        ldx #<s_cpu
        ldy #>s_cpu
        jsr say
        pla
        jmp hex

; bt_init: after the install, interrupts masked. With the Appletini's
; mouse card its VBL interrupt on (mode $09, as A's boot did at
; bt_installed); without it mo_recs's records (the card's handler on
; VIA-B's timer 1, pl_init over the mouse's window, then playdisk.py's
; records in bt_mpatch: the frame images' polls without the mouse). Then
; am_patch when probe_amem found no API, then pl_init.
bt_init:
        bit bt_mouse
        bmi @nomouse
        lda #ACK_ALL
        sta MOUSE_ACK
        lda #MODE_VBL
        sta MOUSE_MODE
        bra @amem
@nomouse:
        lda #<mo_recs
        ldx #>mo_recs
        jsr am_records
@amem:  bit bt_amem
        bpl :+
        jsr am_patch
:       jmp pl_init

; am_patch: bt_patch's records (playdisk.py writes them: tools/native/
; amcpu.py's table), each a length (1-255; 0 ends them), a bank (0 the
; main card, its bank 1 at $D000; else that RamWorks bank, RAMWRT on), an
; address, the bytes. Interrupts masked; after the install.
am_patch:
        lda #<bt_patch
        ldx #>bt_patch
am_records:                     ; (A/X: the records)
        sta bsrc
        stx bsrc+1
@rec:   lda (bsrc)              ; the length
        beq @done
        sta blen
        stz blen+1
        ldy #1
        lda (bsrc),y            ; the bank
        sta bnk
        iny
        lda (bsrc),y            ; the address
        sta bdst
        iny
        lda (bsrc),y
        sta bdst+1
        clc                     ; the bytes
        lda bsrc
        adc #4
        sta bsrc
        bcc :+
        inc bsrc+1
:       lda bnk
        sta RWBANK
        beq :+
        sta RAMWRTON
:       jsr copy                ; (bsrc as it was: under a page)
        sta RAMWRTOFF
        stz RWBANK
        clc                     ; the next record
        lda bsrc
        adc blen
        sta bsrc
        bcc @rec
        inc bsrc+1
        bra @rec
@done:  rts

PR_N    = 5
pr_at:  .byte $01, $03, $05, $07, $FF   ; slot 7's ROM: where and what
pr_is:  .byte $20, $00, $03, $00, $0A
s_cpu:  .byte "NO MEMORY API: COPIES BY THE CPU $", 0
bt_amem:
        .byte 0                 ; bit 7: no memory API (the CPU's copies)
bt_mouse:
        .byte 0                 ; bit 7: not the Appletini's mouse card
                                ;   (the clock VIA-B's timer 1)

; ---------------------------------------------------------------------------
; The mouse card optional (docs/PLAY.md 20): with the Appletini's mouse
; card in slot 2 the boot and the game are A's; without it (an emulator's
; AppleMouse II, or no card) the clock is the Phasor's VIA-B timer 1 at a
; frame's period, as MUSIC.SYSTEM's (music/doom), and the game reads no
; mouse.
; ---------------------------------------------------------------------------

; mo_check: the ID bytes matched; the Appletini's own bytes too: its slot
; helper at $C200 (LDX #2) and its command stub at $C20D (STA $C0AC), both
; pinned by appletini-one's scripts/build_mouse_rom.py (an AppleMouse II's
; ROM starts BIT $FF58 and has no register at $C0AC)
mo_check:
        ldx #MO_N - 1
:       ldy mo_at,x
        lda MOUSE_ROM,y
        cmp mo_is,x
        bne mo_none
        dex
        bpl :-
        rts                     ; bt_mouse 0: the Appletini's
; mo_none: no Appletini mouse card: VIA-B's timer 1 must be there (its
; latch holds what is written, MUSIC.SYSTEM's timer_check), else the stop
mo_none:
        dec bt_mouse
        ldx #$55
        jsr @try
        bcs @stop
        ldx #$AA
@try:   stx VIA_B_T1LL
        txa
        eor #$FF
        sta VIA_B_T1LH
        cpx VIA_B_T1LL
        bne @stop
        cmp VIA_B_T1LH
        bne @stop
        clc
        rts
@stop:  ldx #<s_noclock
        ldy #>s_noclock
        jsr fail_say
        lda #PL_NOMOUSE
        jmp bt_stop

; bt_detect: PAL or NTSC, the clock from 0 (after snd_init, whose IER $7F
; turned both VIAs' interrupts off; interrupts enabled). With the
; Appletini's mouse card: pl_detect, as before, then its count checked
; (std_of): near neither frame, the clock is NTSC's. Without it, masked:
; two frames between starts of a blanking seen at RDVBLBAR, each counted
; by VIA-B's timer 1 from $FFFF (vb_edge), and then:
;   - both near the same standard (std_of) and within 256 counts of each
;     other: that standard, the timer at its frame (T1_PAL, T1_NTSC);
;   - within 256 counts of each other and at least 16,384, but near no
;     standard (a VIA counting another clock than the bus's, such as an
;     emulator's accelerated one): the timer at the frame measured, so
;     that it still times out once a frame, and the tic step NTSC's, or
;     PAL's when half the frame is near PAL's (a VIA at twice the bus
;     clock), with a '?';
;   - else (no blanking, or a frame of 65,536 counts or more, or two
;     frames that differ): NTSC, the timer at its frame, with a '?';
; then the timer free-running, its interrupt on, row 5 saying so, CLI.
VB      = crcz                  ; (5) the first frame, the standard, its
                                ;   mark, the second's standard
bt_detect:
        bit bt_mouse
        bmi @via
        jsr pl_detect           ; A = the standard, X:Y = the count
        jsr std_of
        bcs :+
        lda #STD_NTSC
        jsr pl_clkset
:       rts
@via:   sei
        lda #ACR_FREE
        sta VIA_B_ACR
        lda #'?' | $80          ; until measured: NTSC, marked
        sta VB+3
        lda #STD_NTSC
        sta VB+2
        lda #$FF
        sta VIA_B_T1LL
        sta VIA_B_T1CH          ; counting down from $FFFF
        jsr vb_edge             ; to a blanking's start
        bcs @dflt
        jsr vb_edge             ; the first frame, X:Y (high, low)
        bcs @dflt
        sty VB
        stx VB+1
        jsr vb_edge             ; the second
        bcs @dflt
        sec                     ; the two within 256 counts
        tya
        sbc VB
        txa
        sbc VB+1
        inc a
        cmp #2
        bcs @dflt
        cpx #FRAME_MIN          ; not a blanking flag gone wild
        bcc @dflt
        jsr std_of              ; the second's standard
        bcc @meas
        sta VB+4
        ldy VB
        ldx VB+1
        jsr std_of              ; the first's
        bcc @meas
        cmp VB+4
        bne @meas
        sta VB+2                ; that standard, measured
        stz VB+3
        asl a
        bcs @dflt               ; NTSC: its frame
        ldx #<T1_PAL
        ldy #>T1_PAL
        bra @set
@meas:  lda VB+1                ; near no standard: half of it near one,
        lsr a                   ;   that one (a VIA at twice the bus
        tax                     ;   clock)
        lda VB
        ror a
        tay
        jsr std_of
        bcc :+
        sta VB+2
:       clc                     ; the timer at the frame measured
        lda VB
        adc #FRAME_FIX
        tax
        lda VB+1
        adc #0
        tay
        bcc @set
@dflt:  ldx #<T1_NTSC           ; (and a latch past $FFFF)
        ldy #>T1_NTSC
@set:   stx VIA_B_T1CL          ; the low latch
        sty VIA_B_T1CH          ; the high latch: the count starts
        lda VB+2
        jsr pl_clkset           ; (php, sei, plp: still masked)
        lda #$80 | IFR_T1
        sta VIA_B_IER
        lda #5
        ldx #<s_viaclk
        ldy #>s_viaclk
        jsr say
        ldx #<s_pal
        ldy #>s_pal
        bit VB+2
        bpl :+
        ldx #<s_ntsc
        ldy #>s_ntsc
:       jsr puts
        lda VB+3
        beq :+
        jsr putc
:       cli
        rts

; std_of: X:Y (high, low) bus cycles a frame: C set and A the standard
; when within FRAME_WIN of 17,030 (NTSC) or 20,280 (PAL), else C clear
std_of: cpy #<(NTSC_FRAME - FRAME_WIN)
        txa
        sbc #>(NTSC_FRAME - FRAME_WIN)
        bcc @no
        cmp #>(2 * FRAME_WIN)
        lda #STD_NTSC
        bcc @yes
        cpy #<(PAL_FRAME - FRAME_WIN)
        txa
        sbc #>(PAL_FRAME - FRAME_WIN)
        bcc @no
        cmp #>(2 * FRAME_WIN)
        lda #STD_PAL
        bcc @yes
@no:    clc
        rts
@yes:   sec
        rts
        .assert <(2 * FRAME_WIN) = 0, error, "std_of's window"

; vb_edge: to the start of the next blanking (RDVBLBAR bit 7 goes low, as
; MUSIC.SYSTEM's vbl_start), then VIA-B's timer 1 read (the high byte the
; same before and after) and restarted from $FFFF (the write to T1C-H
; clears its flag): X:Y (high, low) = the counts since the last restart
; ($FFFF less the reading) and C clear. C set when the timer times out
; first: 65,536 counts or more since the restart (no blanking: 64 ms at
; the bus clock; or a frame too long for the timer). A count is never
; taken across a time-out, so it is never a wrapped one.
vb_edge:
@end:   bit VIA_B_IFR           ; in a blanking: to its end
        bvs @no
        bit RDVBLBAR
        bpl @end
@disp:  bit VIA_B_IFR           ; the display: to the blanking
        bvs @no
        bit RDVBLBAR
        bmi @disp
@read:  ldx VIA_B_T1CH
        ldy VIA_B_T1CL
        cpx VIA_B_T1CH
        bne @read
        lda #$FF
        sta VIA_B_T1CH          ; restarted (13 cycles from the reading)
        txa
        eor #$FF
        tax
        tya
        eor #$FF
        tay
        clc
        rts
@no:    sec
        rts

; the card's records without the Appletini's mouse card (am_records' form,
; bank 0: main and the main card), then bt_mpatch's (playdisk.py's: each
; frame image's pl_poll without the mouse, tools/native/nomouse.py), 0
; ending them:
;   pl_vbody's head: the cause VIA-B's timer 1 flag (IFR bit 6), cleared by
;     writing it back (MUSIC.SYSTEM's snd_irq: in native mode a read of
;     T1C-L would step the counter once more), in A's 13 bytes
;   pl_crash's: VIA-B's interrupts off, for the mouse card's mode and ACK
;   pl_init's: a BRA over the mouse card's window and centring
mo_recs:
        .byte VH_N, 0
        .word pl_vbody
mo_vh:  .byte $AD               ; lda VIA_B_IFR
        .word VIA_B_IFR
        .byte $29, IFR_T1       ; and #IFR_T1
        .byte $F0, <(pl_vnone - (pl_vbody + 7))  ; beq pl_vnone
        .byte $8D               ; sta VIA_B_IFR: the flag cleared
        .word VIA_B_IFR
        .byte $EA, $EA, $EA
VH_N = * - mo_vh
        .byte VC_N, 0
        .word pl_crash + 1
mo_vc:  .byte $A9, $7F          ; lda #$7F
        .byte $8D               ; sta VIA_B_IER
        .word VIA_B_IER
        .byte $EA, $EA, $EA
VC_N = * - mo_vc
        .byte 2, 0
        .word pl_iwin
        .byte $80, <(pl_defaults - (pl_iwin + 2))   ; bra pl_defaults
bt_mpatch:
        .res MPATCH_SIZE
bt_mpatch_end:
        .assert VH_N = 13 && VC_N = 8, error, "the card's records"
        .assert pl_vnone - (pl_vbody + 7) < 128, lderror, "pl_vnone's branch"
        .assert pl_defaults - (pl_iwin + 2) < 128, lderror, "pl_iwin's branch"

MO_N    = 5
mo_at:  .byte $00, $01, $0D, $0E, $0F   ; slot 2's ROM: where and what
mo_is:  .byte $A2, $02, $8D, $AC, $C0
s_viaclk:
        .byte "NO APPLETINI MOUSE: PHASOR CLOCK, ", 0

; the patch table (zero in m11's link: nothing to patch)
bt_patch:
        .res PATCH_SIZE
bt_patch_end:
        .assert * <= BOOT_END, error, "the boot passes $3000"

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
