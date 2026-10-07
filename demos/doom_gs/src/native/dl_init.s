; dl_init.s: DLINIT, the playable game's one-shot image (docs/PLAY.md),
; loaded into W from DLBANK by the boot's list and by the quit's.
; GPL-2, the port's own (the memory API's transport follows appletini-
; one's README_MEMORY_API.md section 7, as lload.s's am_send does).
;
;   dli_main  the static tables (docs/MEMORY_MAP.md: "boot, PRIVATE"):
;             one memory-API request
;             of PRIVATE copies from DLBANK (the disk builder's, at
;             DLB_PRIV: its 20-byte header, then its descriptors; its
;             length in DLB_PRIV's first two bytes) into main $0800-$0BFF
;             and aux 0's $0200 and $0900 tables, after the last MLI call
;             (docs/MEMORY_MAP.md's rules); a refused request stops (PL_STATUS
;             PL_DLINIT, LV_AMEM the API's result, then BRK). Then the
;             screen: the 200 SCBs and 16 palettes of aux 0 black (CPU
;             stores, RAMWRT on), SHR on (NEWVIDEO $C1): the title page's
;             first frame shows a black screen first (docs/SCREENS.md)
;             first of all dli_apply: the settings of DOOM.SETTINGS
;   dli_quit  I_Quit: the music stops, the effects off, SHR off, a text
;             screen that says so (ProDOS was given up at the boot: the
;             machine is turned off or reset)
;   dli_save  SAVE SETTINGS (G_SaveSettings, the menu's REQ_SAVESET): the
;             settings into DOOM.SETTINGS's block by the boot device's
;             block driver; M_SAVERES in MENUW's state block the answer
;
; The settings (docs/PLAY.md, "The settings file"; upstream's
; m_config65.s G_LoadSettings, G_SettingsChanged, G_SaveSettings):
; DOOM.SYSTEM left the file as it read it at SET_FILE of SET_BANK and the
; save's details at SET_INFO (s2layout's SET_*, SI_*). dli_apply checks the
; file (the magic, the version, the sum of bytes 12-511) and, when it is
; good, applies it, each value clamped as upstream's: gamma 0-4, always
; run, messages, the mouse and mouse move 0 or 1, the mouse speed 0-9,
; the effects' and the music's volumes 0-15, each key code's Doom key
; (NUMKEYS and above: none); a missing or bad file leaves the defaults.
; Then collect writes the settings as they are into SET_FILE: the
; settings as the disk has them (upstream's settingsKnown), which MENUW
; compares (SAVE SETTINGS dim while equal) and dli_save writes when they
; differ.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "playsym.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export dli_main, dli_quit, dli_save

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
; the settings: W above the image (free while DLINIT is in W:
; playlayout.check), zero page after DLZ's
FILEBUF     = DLINIT_HI         ; the file collect makes (512 B)
KNOWNBUF    = FILEBUF + SET_SIZE ; the settings as the disk has them
HOLEBUF     = KNOWNBUF + SET_SIZE ; the slot holes around the driver (64 B)
SZ_P        = $86               ; (2) a pointer
SZ_SUM      = $88               ; (2) the file's sum
SZ_N        = $8A               ; a byte
SZ_C        = $8B               ; the driver's carry (bit 0)
SZ_ERR      = $8C               ; its A
SZ_SW       = $8D               ; (2) RAMWRT's and 80STORE's states
SZ_INFO     = $8F               ; (SI_SIZE) SET_INFO
SZ_SS       = $95               ; (6) SS_SETTINGS' bytes
SZ_ZP       = $9B               ; (6) zero page $42-$47 around the driver
SS_RUN      = 0                 ; SS_SETTINGS' bytes (s2layout's field
SS_DETAIL   = 1                 ;   map: _g_alwaysRun, detailLevel,
SS_MOUSE    = 2                 ;   iigs_mouseon, iigs_mousespeed,
SS_MSPEED   = 3                 ;   iigs_mousemove, snd_MusicVolume;
SS_MMOVE    = 4                 ;   s2_menu.s's SET_*)
SS_MUSVOL   = 5
SS_N        = 6
NOKEY       = $FF
RES_FAIL    = 1                 ; M_SAVERES: the write failed, saved
RES_SAVED   = 2
PD_CMD      = $42               ; the ProDOS block driver's parameters:
PD_UNIT     = $43               ;   the command, the unit, the buffer,
PD_BUF      = $44               ;   the block
PD_BLOCK    = $46
PD_WRITE    = 2
STORE80OFF  = $C000
STORE80ON   = $C001
INTCXROMOFF = $C006
ALTZPOFF    = $C008
RDRAMWRT    = $C014
RD80STORE   = $C018
LCBANK1     = $C08B
        .assert SZ_ZP + 6 <= $B0, error, "DLINIT's zero page"
        .assert SZ_SS = SZ_INFO + SI_SIZE, error, "SZ_INFO"

        .segment "DLINIT"

dli_main:
        jsr dli_apply           ; the settings of DOOM.SETTINGS
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

; ---------------------------------------------------------------------------
; dli_apply: G_LoadSettings (m_config65.s): the boot's file, checked, its
; values clamped into the game's places (GAMMA, showMessages, the
; effects' volume, SS_SETTINGS, PL_KEYTAB); a missing or bad file keeps
; the defaults (upstream's "no valid file"). Then the settings as they are
; into SET_FILE (collect, G_RememberSettings).
; ---------------------------------------------------------------------------
dli_apply:
        lda #>FILEBUF
        jsr set_get             ; the boot's file, SET_INFO into SZ_INFO
        lda SZ_INFO + SI_FLAGS
        bpl @known              ; no file read: the defaults
        jsr set_check
        bcs @known              ; not a good file: the defaults
        lda FILEBUF + SETF_GAMMA
        ldx #4
        jsr inrange
        sta GAMMA
        stz GAMMA+1
        lda FILEBUF + SETF_MESSAGES
        jsr flag
        sta G_SHOWMSG
        stz G_SHOWMSG+1
        lda FILEBUF + SETF_SFXVOL
        ldx #15
        jsr inrange
        sta SND_SFXVOL
        jsr ss_get
        lda FILEBUF + SETF_RUN
        jsr flag
        sta SZ_SS + SS_RUN
        lda FILEBUF + SETF_MOUSE
        jsr flag
        sta SZ_SS + SS_MOUSE
        lda FILEBUF + SETF_MSPEED
        ldx #9
        jsr inrange
        sta SZ_SS + SS_MSPEED
        lda FILEBUF + SETF_MMOVE
        jsr flag
        sta SZ_SS + SS_MMOVE
        lda FILEBUF + SETF_MUSICVOL
        ldx #15
        jsr inrange
        sta SZ_SS + SS_MUSVOL
        jsr ss_put
        ldx #127                ; the keys: a Doom key or none
@key:   lda FILEBUF + SETF_KEYS,x
        cmp #NUMKEYS
        bcc :+
        lda #NOKEY
:       sta PL_KEYTAB,x
        dex
        bpl @key
@known: jsr collect
        jmp set_put

; ---------------------------------------------------------------------------
; dli_save: G_SaveSettings: the settings now (collect) against those the
; disk has (SET_FILE): the same, nothing to write; else, when the boot
; found the driver and the block (SIF_SAVE), the block written (blk_write)
; and SET_FILE the new settings. M_SAVERES (RES_SAVED, or RES_FAIL with
; SET_FILE kept, so SAVE SETTINGS stays lit for another try) into MENUW's
; state block in S2STATE; A the same.
; ---------------------------------------------------------------------------
dli_save:
        jsr collect
        lda #>KNOWNBUF
        jsr set_get
        ldx #0
:       lda FILEBUF,x
        cmp KNOWNBUF,x
        bne @write
        lda FILEBUF+$100,x
        cmp KNOWNBUF+$100,x
        bne @write
        inx
        bne :-
        bra @saved              ; unchanged: the disk has them
@write: lda SZ_INFO + SI_FLAGS
        and #SIF_SAVE
        beq @fail               ; no driver or no block: not saved
        jsr blk_write
        bcs @fail
        jsr set_put
@saved: lda #RES_SAVED
        bra @res
@fail:  lda #RES_FAIL
@res:   sta SZ_N
        lda #S2STATE
        sta FA_BANK
        lda #<SZ_N
        sta FA_SRC
        stz FA_SRC+1
        lda #<(SS_MENUW + M_SAVERES - MENUW_STATE)
        sta FA_DST
        lda #>(SS_MENUW + M_SAVERES - MENUW_STATE)
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr XS_far_put
        lda SZ_N
        rts

; ---------------------------------------------------------------------------
; blk_write: FILEBUF into the block SI_BLOCK of the unit SI_UNIT by its
; ProDOS block driver SI_DRIVER (in its slot's ROM: DOOM.SYSTEM checked),
; with the machine as a slot driver expects it and the game's state put
; back after: interrupts masked for the call (the music and the clock wait:
; a slot driver may not take an interrupt mid-transfer, and the game's
; handler is the card's), binary mode; main memory for zero page, the
; stack and the buffer (ALTZP, RAMRD, RAMWRT, 80STORE off: RAMWRT and
; 80STORE as they were after), $C073 0, the slots' ROM in (INTCXROM off),
; no card's $C800 space selected before and after ($CFFF); zero page
; $42-$47 and the 64 slot screen holes of main $0400-$07FF (the firmware's
; scratch: the Appletini's writes MSLOT, $07F8) kept and put back (only
; the bytes the driver changed are stored: rule 3's pages); then the
; card's $D000 bank 1 RAM read and write again (rule 1). C set: the
; driver's error (its code in SZ_ERR).
; ---------------------------------------------------------------------------
; HOLEPUT hole, at: the hole of slot X back from HOLEBUF + at, when the
; driver changed it
.macro HOLEPUT hole, at
        .local same
        lda HOLEBUF + at,x
        cmp hole,x
        beq same
        sta hole,x
same:
.endmacro

blk_write:
        php
        sei
        cld
        lda RDRAMWRT
        sta SZ_SW
        lda RD80STORE
        sta SZ_SW+1
        sta STORE80OFF
        sta RAMRDOFF
        sta RAMWRTOFF
        sta ALTZPOFF
        sta INTCXROMOFF
        stz RWBANK
        ldx #5                  ; zero page $42-$47
:       lda PD_CMD,x
        sta SZ_ZP,x
        dex
        bpl :-
        ldx #7                  ; the slot holes, slot x of each page
:       lda $0478,x
        sta HOLEBUF,x
        lda $04F8,x
        sta HOLEBUF+8,x
        lda $0578,x
        sta HOLEBUF+16,x
        lda $05F8,x
        sta HOLEBUF+24,x
        lda $0678,x
        sta HOLEBUF+32,x
        lda $06F8,x
        sta HOLEBUF+40,x
        lda $0778,x
        sta HOLEBUF+48,x
        lda $07F8,x
        sta HOLEBUF+56,x
        dex
        bpl :-
        lda #PD_WRITE
        sta PD_CMD
        lda SZ_INFO + SI_UNIT
        sta PD_UNIT
        lda #<FILEBUF
        sta PD_BUF
        lda #>FILEBUF
        sta PD_BUF+1
        lda SZ_INFO + SI_BLOCK
        sta PD_BLOCK
        lda SZ_INFO + SI_BLOCK + 1
        sta PD_BLOCK+1
        bit SP_RELEASE
        jsr bw_call
        sta SZ_ERR
        lda #0
        rol a
        sta SZ_C
        bit SP_RELEASE
        bit LCBANK1             ; the card: bank 1, RAM read and write
        bit LCBANK1
        ldx #7                  ; the holes the driver changed back
bw_hole:
        HOLEPUT $0478, 0
        HOLEPUT $04F8, 8
        HOLEPUT $0578, 16
        HOLEPUT $05F8, 24
        HOLEPUT $0678, 32
        HOLEPUT $06F8, 40
        HOLEPUT $0778, 48
        HOLEPUT $07F8, 56
        dex
        bpl bw_hole
        ldx #5
:       lda SZ_ZP,x
        sta PD_CMD,x
        dex
        bpl :-
        bit SZ_SW+1             ; 80STORE and RAMWRT as they were
        bpl :+
        sta STORE80ON
:       bit SZ_SW
        bpl :+
        sta RAMWRTON
:       plp
        lsr SZ_C                ; C: the driver's
        rts
bw_call:
        jmp (SZ_INFO + SI_DRIVER)

; ---------------------------------------------------------------------------
; collect: FILEBUF = the settings now in the file's layout (upstream's
; collect: the magic, the version, each setting, the keys, the sum; the
; detail and the view size are this version's only ones)
; ---------------------------------------------------------------------------
collect:
        ldx #0
:       stz FILEBUF,x
        stz FILEBUF+$100,x
        inx
        bne :-
        ldx #SETF_VERSION - 1
:       lda set_magic,x
        sta FILEBUF,x
        dex
        bpl :-
        lda #SET_VERSION
        sta FILEBUF + SETF_VERSION
        lda GAMMA
        sta FILEBUF + SETF_GAMMA
        lda G_SHOWMSG
        sta FILEBUF + SETF_MESSAGES
        lda SND_SFXVOL
        sta FILEBUF + SETF_SFXVOL
        jsr ss_get
        lda SZ_SS + SS_RUN
        sta FILEBUF + SETF_RUN
        lda SZ_SS + SS_DETAIL
        sta FILEBUF + SETF_DETAIL
        lda SZ_SS + SS_MOUSE
        sta FILEBUF + SETF_MOUSE
        lda SZ_SS + SS_MSPEED
        sta FILEBUF + SETF_MSPEED
        lda SZ_SS + SS_MMOVE
        sta FILEBUF + SETF_MMOVE
        lda SZ_SS + SS_MUSVOL
        sta FILEBUF + SETF_MUSICVOL
        lda #SET_FULLVIEW
        sta FILEBUF + SETF_VSIZE
        ldx #127
:       lda PL_KEYTAB,x
        sta FILEBUF + SETF_KEYS,x
        dex
        bpl :-
        jsr set_sum
        sta FILEBUF + SETF_SUM
        stx FILEBUF + SETF_SUM + 1
        rts

; set_check: C clear when FILEBUF has the magic, the version and the sum
set_check:
        ldx #SETF_VERSION - 1
:       lda FILEBUF,x
        cmp set_magic,x
        bne @bad
        dex
        bpl :-
        lda FILEBUF + SETF_VERSION
        cmp #SET_VERSION
        bne @bad
        jsr set_sum
        cmp FILEBUF + SETF_SUM
        bne @bad
        cpx FILEBUF + SETF_SUM + 1
        bne @bad
        clc
        rts
@bad:   sec
        rts

; set_sum: X:A = the sum of FILEBUF's bytes 12-511 (16 bits)
set_sum:
        stz SZ_SUM
        stz SZ_SUM+1
        ldy #SETF_GAMMA
@p0:    lda FILEBUF,y
        jsr @add
        iny
        bne @p0
@p1:    lda FILEBUF+$100,y
        jsr @add
        iny
        bne @p1
        lda SZ_SUM
        ldx SZ_SUM+1
        rts
@add:   clc
        adc SZ_SUM
        sta SZ_SUM
        bcc :+
        inc SZ_SUM+1
:       rts

; inrange: A, or X when A is more; flag: A = 1 when A is not 0
inrange:
        stx SZ_N
        cmp SZ_N
        bcc :+
        txa
:       rts
flag:   cmp #0
        beq :+
        lda #1
:       rts

; set_get: SET_FILE into the two pages from A (FILEBUF or KNOWNBUF),
; SET_INFO into SZ_INFO. set_put: FILEBUF into SET_FILE.
set_get:
        jsr set_ptr
        jsr XS_far_get
        inc FA_SRC+1
        inc FA_DST+1
        jsr XS_far_get
        lda #<SET_INFO
        sta FA_SRC
        lda #>SET_INFO
        sta FA_SRC+1
        lda #<SZ_INFO
        sta FA_DST
        stz FA_DST+1
        lda #SI_SIZE
        sta FA_N
        jmp XS_far_get
set_put:
        lda #>FILEBUF
        jsr set_ptr
        lda FA_DST              ; (main FILEBUF to SET_FILE)
        ldx FA_SRC
        sta FA_SRC
        stx FA_DST
        lda FA_DST+1
        ldx FA_SRC+1
        sta FA_SRC+1
        stx FA_DST+1
        jsr XS_far_put
        inc FA_SRC+1
        inc FA_DST+1
        jmp XS_far_put
set_ptr:
        sta FA_DST+1
        stz FA_DST
        lda #SET_BANK
        sta FA_BANK
        lda #<SET_FILE
        sta FA_SRC
        lda #>SET_FILE
        sta FA_SRC+1
        stz FA_N                ; (256 bytes)
        rts

; ss_get, ss_put: SS_SETTINGS' bytes to and from SZ_SS
ss_get:
        jsr ss_ptr
        jmp XS_far_get
ss_put:
        jsr ss_ptr
        lda #<SZ_SS
        sta FA_SRC
        stz FA_SRC+1
        lda #<SS_SETTINGS
        sta FA_DST
        lda #>SS_SETTINGS
        sta FA_DST+1
        jmp XS_far_put
ss_ptr:
        lda #S2STATE
        sta FA_BANK
        lda #SS_N
        sta FA_N
        lda #<SS_SETTINGS
        sta FA_SRC
        lda #>SS_SETTINGS
        sta FA_SRC+1
        lda #<SZ_SS
        sta FA_DST
        stz FA_DST+1
        rts

set_magic:
        .byte "DOOMSET"
        .assert * - set_magic = SETF_VERSION, error, "the magic"
        .assert <FILEBUF = 0 && <KNOWNBUF = 0, error, "the settings' buffers"
