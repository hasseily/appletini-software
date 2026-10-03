; dl_init.s: DLINIT, the playable game's one-shot image (docs/PLAY.md 2.1,
; 3), loaded into W from DLBANK by the boot's list and by the quit's.
; GPL-2, the port's own (the memory API's transport follows appletini-
; one's README_MEMORY_API.md section 7, as lload.s's am_send does).
;
;   dli_main  the static tables (MEMORY_MAP.md 3.2 and 5: "boot, PRIVATE";
;             docs/m11-parts/design.md R7 item 15): one memory-API request
;             of PRIVATE copies from DLBANK (the disk builder's, at
;             DLB_PRIV: its 20-byte header, then its descriptors; its
;             length in DLB_PRIV's first two bytes) into main $0800-$0BFF
;             and aux 0's $0200 and $0900 tables, after the last MLI call
;             (MEMORY_MAP.md rule 9); a refused request stops (PL_STATUS
;             PL_DLINIT, LV_AMEM the API's result, then BRK). Then the
;             screen: the 200 SCBs and 16 palettes of aux 0 black (CPU
;             stores, RAMWRT on), SHR on (NEWVIDEO $C1): the title page's
;             first frame shows a black screen first (SCREENS.md 1.5.8)
;   dli_quit  I_Quit: the music stops, the effects off, SHR off, a text
;             screen that says so (ProDOS was given up at the boot: the
;             machine is turned off or reset)

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "playsym.inc"

        .export dli_main, dli_quit

SP_DATA     = $CFF0             ; the memory API's FIFO in slot 7
SP_CTRL     = $CFF1
SP_POP      = $CFF2
SP_RELEASE  = $CFFF
SP_ROM      = $C700
NEWVIDEO    = $C029
TEXTON      = $C051
MIXEDOFF    = $C052
PAGE1       = $C054
PL_DLINIT   = $C8               ; (PL_STATUS: the static tables refused)
LV_AMEM_B   = $03AF             ; (llayout's LV_AMEM: the API's result)
REQ         = DLINIT_HI - $0200 ; the request's W buffer (256 B)
DLZ         = $80               ; zero page: a pointer, a count, a wait

        .segment "DLINIT"

dli_main:
        lda #DLBANK             ; the request's length, then the request
        sta FA_BANK
        lda #<DLB_PRIV
        sta FA_SRC
        lda #>DLB_PRIV
        sta FA_SRC+1
        lda #<REQ
        sta FA_DST
        lda #>REQ
        sta FA_DST+1
        stz FA_N                ; (256 bytes)
        jsr XS_far_get
        lda REQ                 ; the length
        sta DLZ+2
        lda REQ+1
        sta DLZ+3
        lda #<(REQ + 2)
        sta DLZ
        lda #>(REQ + 2)
        sta DLZ+1
dli_send:                       ; (the request; without the memory API
        php                     ;   DOOM.SYSTEM writes a CPU walker of it
        sei                     ;   here, to dli_screen: tools/native/amcpu.py)
        bit SP_RELEASE
        bit SP_ROM
        ldy #0
@byte:  lda (DLZ),y
        sta SP_DATA
        iny
        bne :+
        inc DLZ+1
:       lda DLZ+2
        bne :+
        dec DLZ+3
:       dec DLZ+2
        lda DLZ+2
        ora DLZ+3
        bne @byte
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
        lda #0
        sta DLZ+4
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec DLZ+4
        bne @wait
        lda #$6F                ; (no reply)
        bra @done
@ready: lda SP_DATA
        sta SP_POP
@done:  bit SP_RELEASE
        plp
        cmp #0
        beq dli_screen
        sta LV_AMEM_B
        lda #PL_DLINIT
        sta PL_STATUS
        brk
        .byte 0
dli_screen:
        sta RAMWRTON            ; the SCBs and palettes black ($9D00-$9FFF
        ldx #0                  ;   of aux 0: rule 10's $9DC8-$9DFF stays
:       stz $9D00,x             ;   zero)
        stz $9E00,x
        stz $9F00,x
        inx
        bne :-
        sta RAMWRTOFF
        lda #$C1                ; SHR on (linear, colour)
        sta NEWVIDEO
        rts

dli_quit:
        jsr XS_snd_stop         ; the music stops at the next interrupt,
        jsr XS_fx_stopall       ;   the effects end
        ldx #4                  ; four VBLs for their last bursts
:       lda XS_vbl_count
:       cmp XS_vbl_count
        beq :-
        dex
        bne :--
        stz FX_ON               ; no more effects
        sei
        lda #$01                ; SHR off, the text page
        sta NEWVIDEO
        sta TEXTON
        sta MIXEDOFF
        sta PAGE1
        ldx #0
        lda #' ' | $80
:       sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        inx
        bne :-
        ldx #0
:       lda q_text,x
        beq :+
        ora #$80
        sta $0400 + 128 * 1 + 2,x
        inx
        bra :-
:       cli
        rts
q_text: .byte "DOOM HAS ENDED. TURN THE COMPUTER OFF.", 0
