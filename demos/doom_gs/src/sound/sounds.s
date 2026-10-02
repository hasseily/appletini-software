; SOUNDS.SYSTEM: the effects' test disk SOUNDS.hdv (milestone 11, part
; fxdisk; sound track S4), for the owner's ear on the card. GPL-2, the
; port's own: written from the design (tools/sound/README.md "Effects
; (S4)", "The test disk SOUNDS.hdv"; docs/SCREENS.md 3) and MUSIC.SYSTEM
; (src/sound/music.s, whose boot, text and quit it follows). Nothing of
; upstream's. tools/sound/fxdisk.py builds it and the disk.
;
; With S2's music player (player.s, probe.s, from build/sound65), the
; platform's interrupt pl_vbl (src/native/pl_irq.s) and the effect player
; (src/sound/fx.s: its card part and fx_service) at the game's places
; (s2layout.py; src/sound/sounds.cfg), linked with the release's s2.inc.
;
; Boot, at $2000 under ProDOS, interrupts masked:
;   1. the text screen (40 columns, page 1, SHR off);
;   2. the mouse card in slot 2 (the clock and the interrupt), else a
;      message, a key, ProDOS's QUIT;
;   3. RamWorks banks 1 to SFX_BANK distinct, else the same;
;   4. snd_probe: native mode (4 AY chips) or not;
;   5. SFX.1 into bank SFX (103) at $0200 (the game's bank file); each
;      tuned effect's automatic script from SFXAUTO.1 after it, in the
;      bank's room (s2layout's SFX_ROOM, to $3FFF); with native mode the
;      song file E1M1.AY into the songs' first bank (100) at $1000;
;   6. ProDOS's language card saved in bank SAVE_BANK, the card image
;      installed ($E900-$FFFF; its vector is pl_vbl);
;   7. snd_init, fx_init with snd_probe's answer, pl_clkset (PAL), the
;      mouse card's VBL on, CLI, pl_detect (PAL or NTSC, its clock).
;
; The main loop serves each VBL (sds_service): the repeat, the keys, a
; frame (fx_service, then snd_refill: as the game's frame images), then
; the screen. Its wait (sds_idle) is the loop a2vm skips to the next VBL.
;
; Keys (a play stops every effect first, then starts the chosen one on
; channel 0 by the game's mailbox, docs/SCREENS.md 3):
;   arrows     the effect (up and down one, left and right a column)
;   RETURN     separation 128, a source ahead: the game's rule (voice C,
;              the centre)
;   A, B       separation 64 (left: voice A) or 200 (right: voice B)
;   C          voice C (the centre) by the fallback: channel 0 takes A
;              and channel 1 the effect at separation 64, A busy, so C,
;              one service, channel 0 stopped, a second service
;              (interrupts masked: A is never heard); the effect plays on
;              channel 1
;   1, 2, 3    the distance: volume 127, 63 (about 680 units), 6 (1,150);
;              the playing effect's volume changes too (a volume mail)
;   T          the effect's tuned or automatic script (the ten tuned):
;              its directory entry in bank SFX is rewritten
;   R          repeat the last play every second (50 or 60 VBLs)
;   M          D_E1M1 under the effects (fx_song), or silence (snd_stop)
;   S          every effect stopped (fx_stopall), the repeat off
;   V          PAL or NTSC: pl_clkset (the effects' tempo), and the song
;              again on the other tables
;   Q, ESC     quit as MUSIC.SYSTEM: the chips reset, ProDOS's card back,
;              the Phasor in Mockingboard mode, ProDOS's QUIT
; Without native mode the keys still write the mailboxes and fx_service
; empties them (FX_ON 0): no AY register is written; M plays nothing.
;
; sds_mark, which fxdisk.py's write log reads with the time of each
; store: the kind of the step the main loop is in (fxrun65.py's codes:
; SONG 1, SONGSTOP 2, START 3, STOP 4, VOLUME 5, STOPALL 7, SERVICE 10;
; and TOGGLE 11, STD 12, QUIT $FF), $80 in a frame's fx_service, $81 in
; its snd_refill, 0 between. Every step but SONG runs with interrupts
; masked.
;
; The interrupt runs pl_vbl only: zero page $D8-$FF, the stack, $E000-
; $FFFF, the mouse card and the Phasor (docs/MEMORY_MAP.md rule 2). The
; program's data is in main $1000-$1FFF and its zero page at $18; no CPU
; store of it reaches $0878-$087F or $4078-$407F (rule 8).

        .setcpu "65C02"
        .include "s2.inc"
        .include "sfxnames.inc"

        .import snd_probe, snd_init, snd_stop, snd_refill
        .import snd_song_bank, snd_song_addr, snd_song_flags, snd_song_matt
        .import snd_error
        .import fx_init, fx_service, fx_song, fx_stopall
        .import fx_copy, fxc_ld, fxc_st
        .import pl_clkset, pl_detect
        .importzp vbl_count

        .export start, sds_service, sds_idle, sds_quit, sds_fatal
        .export sds_tuned, sds_ver, sds_tdir, sds_adir, sds_next
        .export sds_sum, sds_lastch, sds_std, sds_cur
        .exportzp seen, sds_mark

MLI             = $BF00
KBD             = $C000
KBDSTRB         = $C010
STORE80OFF      = $C000
RAMRD_OFF       = $C002
RAMRD_ON        = $C003
RAMWRT_OFF      = $C004
RAMWRT_ON       = $C005
INTCXROMOFF     = $C006
ALTZPOFF        = $C008
COL80OFF        = $C00C
ALTCHAROFF      = $C00E
NEWVIDEO        = $C029
TEXTON          = $C051
MIXEDOFF        = $C052
PAGE1           = $C054
RAMWORKS        = $C073
LCROM           = $C082         ; read the ROM, no writes
LC_RW_BANK2     = $C083         ; twice: read and write RAM, $D000 bank 2
LCBANK1         = $C08B         ; twice: read and write RAM, $D000 bank 1
MOUSE_ROM       = $C200
MOUSE_MODE      = $C0AE
MOUSE_ACK       = $C0AF
MODE_VBL        = $09           ; the mouse card on, its VBL interrupt on
ACK_ALL         = $03
PHASOR_MB       = $C0C8         ; the Phasor's Mockingboard mode

SND_MUSIC       = 0             ; snd_probe's answer: native mode
SONG_LOOP       = $01
SONG_NTSC       = $80           ; = pl_clkset's NTSC standard

NSFX            = 52
COLROWS         = 18            ; the list: 3 columns of 18
SFX_BANK        = S2SFX         ; 103
SFX_AT          = $0200         ; SFX.1 in the bank (fx.s FX_DIR)
SFX_END         = $4000         ; s2layout's SFX_ROOM: $0200-$3FFF
SONG_BANK       = SONGS0        ; 100
SONG_AT         = $1000
SAVE_BANK       = 1             ; ProDOS's card while the program has it:
SAVE_ADDR       = $2000         ;   $2000-$4FFF $D000-$FFFF (bank 1),
                                ;   $5000-$5FFF $D000-$DFFF (bank 2)
RAMCHECK        = $0C00         ; the byte each bank's check writes
LC_IMAGE        = $4000         ; the card image in SOUNDS.SYSTEM
LC_RUN          = $E900
LC_PAGES        = $17           ; $E900-$FFFF
IOBUF           = $5C00         ; ProDOS's buffer for the open file
DATABUF         = $6000         ; a file, read whole
DATAMAX         = $5800         ;   $6000-$B7FF; a file this long is too long
P1COPY          = $0100         ; the page-1 copy (p1_code)

VOL_NEAR        = 127           ; fxrun65.py VOL_NEAR, VOL_MID, VOL_FAR
VOL_MID         = 63
VOL_FAR         = 6
SEP_AHEAD       = 128           ; the centre: a source ahead
SEP_LEFT        = 64
SEP_RIGHT       = 200

K_RETURN        = 1             ; lastkey: the play keys
K_A             = 2
K_B             = 3
K_C             = 4

M_SONG          = 1             ; sds_mark (fxrun65.py's action codes)
M_SONGSTOP      = 2
M_START         = 3
M_STOP          = 4
M_VOLUME        = 5
M_STOPALL       = 7
M_SERVICE       = 10
M_TOGGLE        = 11
M_STD           = 12
M_QUIT          = $FF           ; the quit (never cleared)
M_FRAME         = $80
M_REFILL        = $81

ROW_TITLE       = 0
ROW_MACHINE     = 1
ROW_LIST        = 2             ; 18 rows
ROW_EFFECT      = 20
ROW_KEYS        = 21
ROW_MSG         = 17            ; boot errors, 17-23
COL_VER         = 7
COL_SUM         = 13
COL_DIST        = 22
COL_VOICE       = 27
COL_MUSIC       = 31
COL_REPEAT      = 37

        .assert LC_IMAGE + LC_PAGES * $100 <= IOBUF, error, "the image"
        .assert DATABUF + DATAMAX <= $BF00, error, "the file buffer"
        .assert SFX_BANK < 127 && SONG_BANK < SFX_BANK, error, "the banks"
        .assert NSFX <= 3 * COLROWS, error, "the list"
        .assert NUM_CHANNELS >= 2, error, "key C needs two channels"

; ---------------------------------------------------------------------------
        .segment "SDSZP": zeropage
ptr:    .res 2          ; the text position
src:    .res 2          ; copies
dst:    .res 2
cnt:    .res 2
seen:   .res 2          ; the VBL count the main loop has served
tmp:    .res 2
num:    .res 2
sds_mark:
        .res 1          ; the main loop's step (above)
inv:    .res 1          ; text: $80 normal, 0 inverse
index:  .res 1
p1bank: .res 1          ; the bank the page-1 copy reads
lead:   .res 1
music:  .res 1          ; 1: snd_probe said native mode
songon: .res 1          ; 1: D_E1M1 plays
rep:    .res 1          ; 1: repeat
rcount: .res 1          ; visits since the last play
lastkey:.res 1          ; the last play key (K_*), 0 none
rate:   .res 1          ; VBLs a second: 50 or 60
dist:   .res 1          ; 0 near, 1 mid, 2 far
showv:  .res 1          ; 1: show the voice after the frame's service
redraw: .res 1          ; bit 0 the machine row, 1 the list, 2 the effect
snd:    .res 1          ; the sound (1-52) of a play
vol:    .res 1
sdszp_end:

        .segment "SDSBSS"
scratch:.res 256        ; reads of bank SFX (fx_copy), the RamWorks check
sds_tuned:
        .res NSFX       ; 1: SFX.1 has the effect tuned
sds_ver:.res NSFX       ; 0: its tuned script in the directory, 1 automatic
sds_tdir:
        .res 4 * NSFX   ; SFX.1's directory entries (address, length)
sds_adir:
        .res 4 * NSFX   ; the automatic scripts of the tuned, in the bank
sds_next:
        .res 2          ; the bank's next free byte
sds_sum:.res 2          ; the shown effect's checksum
sds_lastch:
        .res 1          ; the channel of the last play, $FF none
sds_std:.res 1          ; 0 PAL, $80 NTSC (CLK_STD)
sds_cur:.res 1          ; the chosen effect, 0-51
errcode:.res 1
length: .res 2          ; a file's length, as read
fatal_msg:
        .res 2

; ---------------------------------------------------------------------------
        .segment "SDSCODE"

start:  sei
        cld
        ldx     #$FF
        txs
        sta     STORE80OFF
        sta     RAMRD_OFF
        sta     RAMWRT_OFF
        sta     ALTZPOFF
        sta     INTCXROMOFF
        stz     RAMWORKS
        lda     #$01                    ; SHR off
        sta     NEWVIDEO
        sta     COL80OFF
        sta     ALTCHAROFF
        sta     TEXTON
        sta     MIXEDOFF
        sta     PAGE1
        ldx     #sdszp_end - ptr - 1    ; the program's zero page
:       stz     ptr,x
        dex
        bpl     :-
        lda     #$80
        sta     inv
        stz     sds_cur
        stz     sds_std
        stz     errcode
        lda     #$FF
        sta     sds_lastch
        lda     #50
        sta     rate
        lda     #0
        ldx     #24
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_TITLE
        jsr     put_at
        lda     #<s_title
        ldx     #>s_title
        jsr     put_str
        jsr     mouse_check
        bcc     :+
        lda     #<s_nomouse
        ldx     #>s_nomouse
        jmp     sds_fatal
:       jsr     mouse_off
        jsr     ram_check
        bcc     :+
        lda     #<s_noram
        ldx     #>s_noram
        jmp     sds_fatal
:       jsr     snd_probe
        pha
        cmp     #SND_MUSIC
        bne     :+
        inc     music
:       jsr     load_sfx
        lda     music
        beq     :+
        jsr     load_song
:       jsr     save_prodos
        jsr     install
        jsr     snd_init
        pla
        jsr     fx_init                 ; A: snd_probe's answer
        lda     #0
        jsr     pl_clkset               ; the clock defined (PAL) until
        jsr     mouse_on                ;   pl_detect
        cli
        jsr     pl_detect
        sta     sds_std
        jsr     set_rate
        jsr     draw_all
        sei
        lda     vbl_count
        sta     seen
        lda     vbl_count+1
        sta     seen+1
        cli

; ---------------------------------------------------------------------------
; the main loop: one service a VBL
; ---------------------------------------------------------------------------
sds_service:
        sei
        lda     vbl_count
        sta     seen
        lda     vbl_count+1
        sta     seen+1
        cli
        jsr     repeat_tick
        jsr     keys
        lda     #M_FRAME                ; the frame, as the game's images
        sta     sds_mark
        jsr     fx_service
        lda     #M_REFILL
        sta     sds_mark
        lda     music
        beq     :+
        jsr     snd_refill
:       stz     sds_mark
        jsr     screen
sds_idle:
        lda     vbl_count
        cmp     seen
        beq     sds_idle
        bra     sds_service

; repeat_tick: with the repeat on, the last play again every `rate` visits
repeat_tick:
        lda     rep
        beq     @no
        lda     lastkey
        beq     @no
        inc     rcount
        lda     rcount
        cmp     rate
        bcc     @no
        lda     lastkey
        jmp     play
@no:    rts

; ---- the keys ----
keys:   lda     KBD
        bmi     :+
        rts
:       sta     KBDSTRB
        and     #$7F
        cmp     #'a'
        bcc     :+
        cmp     #'z'+1
        bcs     :+
        and     #$DF                    ; lower case: as upper
:       ldx     #key_count - 1
:       cmp     key_codes,x
        beq     @found
        dex
        bpl     :-
        rts
@found: txa
        asl     a
        tax
        jmp     (key_jumps,x)

key_codes:
        .byte   $0B, $0A, $08, $15, $0D, 'A', 'B', 'C'
        .byte   '1', '2', '3', 'T', 'R', 'M', 'S', 'V', 'Q', $1B
key_count = * - key_codes
key_jumps:
        .word   k_up, k_down, k_left, k_right, k_return, k_a, k_b, k_c
        .word   k_dist, k_dist, k_dist, k_tuned, k_repeat, k_music, k_stop
        .word   k_video, sds_quit, sds_quit
        .assert (* - key_jumps) = 2 * key_count, error, "the key table"

k_up:   lda     sds_cur
        bne     :+
        lda     #NSFX
:       dec     a
        bra     set_cur
k_down: lda     sds_cur
        inc     a
        cmp     #NSFX
        bcc     set_cur
        lda     #0
        bra     set_cur
k_left: lda     sds_cur
        sec
        sbc     #COLROWS
        bcs     set_cur
        rts
k_right:
        lda     sds_cur
        clc
        adc     #COLROWS
        cmp     #NSFX
        bcc     set_cur
        rts
set_cur:
        sta     sds_cur
        lda     #6                      ; the list and the effect line
        tsb     redraw
        rts

k_return:
        lda     #K_RETURN
        bra     k_play
k_a:    lda     #K_A
        bra     k_play
k_b:    lda     #K_B
        bra     k_play
k_c:    lda     #K_C
k_play: jmp     play

; 1, 2, 3: the distance; the playing effect's volume follows
k_dist: txa                             ; X: 2 x the key's index
        lsr     a
        sec
        sbc     #8                      ; '1' is key 8
        sta     dist
        lda     #4
        tsb     redraw
        ldx     sds_lastch
        bmi     @none
        php
        sei
        lda     #M_VOLUME
        sta     sds_mark
        txa
        asl     a
        asl     a
        tax
        lda     SC_MAIL + MX_FLAGS,x
        ora     #MX_VOLUME
        sta     SC_MAIL + MX_FLAGS,x
        ldy     dist
        lda     vol_of,y
        sta     SC_MAIL + MX_VOL,x
        stz     sds_mark
        plp
@none:  rts

; T: the tuned or the automatic script of a tuned effect: its directory
; entry in bank SFX rewritten
k_tuned:
        ldx     sds_cur
        lda     sds_tuned,x
        bne     :+
        rts
:       php
        sei
        lda     #M_TOGGLE
        sta     sds_mark
        lda     sds_ver,x
        eor     #1
        sta     sds_ver,x
        txa
        asl     a
        asl     a
        tay                             ; Y: the entry's offset
        lda     sds_ver,x
        bne     @auto
        lda     #<sds_tdir
        ldx     #>sds_tdir
        bra     :+
@auto:  lda     #<sds_adir
        ldx     #>sds_adir
:       sta     src
        stx     src+1
        tya
        clc
        adc     src
        sta     src
        bcc     :+
        inc     src+1
:       tya                             ; the bank's directory entry
        clc
        adc     #<SFX_AT
        sta     dst
        lda     #>SFX_AT
        adc     #0
        sta     dst+1
        lda     #4
        sta     cnt
        stz     cnt+1
        jsr     to_sfx
        stz     sds_mark
        plp
        lda     #6
        tsb     redraw
        rts

k_repeat:
        lda     rep
        eor     #1
        sta     rep
        stz     rcount
        lda     #1
        tsb     redraw
        rts

k_music:
        lda     music
        beq     @rts
        lda     songon
        bne     @off
        jmp     song_start
@off:   php
        sei
        lda     #M_SONGSTOP
        sta     sds_mark
        jsr     snd_stop
        stz     sds_mark
        plp
        stz     songon
        lda     #1
        tsb     redraw
@rts:   rts

k_stop: php
        sei
        lda     #M_STOPALL
        sta     sds_mark
        jsr     fx_stopall
        stz     sds_mark
        plp
        stz     rep
        lda     #1
        tsb     redraw
        rts

; V: PAL or NTSC. pl_clkset counts the VBLs from 0: the loop's count with it
k_video:
        php
        sei
        lda     #M_STD
        sta     sds_mark
        lda     sds_std
        eor     #SONG_NTSC
        sta     sds_std
        jsr     pl_clkset
        lda     vbl_count
        sta     seen
        lda     vbl_count+1
        sta     seen+1
        stz     sds_mark
        plp
        jsr     set_rate
        lda     #1
        tsb     redraw
        lda     songon
        beq     :+
        jmp     song_start              ; the song again, on the new tables
:       rts

set_rate:
        lda     #50
        bit     sds_std
        bpl     :+
        lda     #60
:       sta     rate
        rts

; song_start: D_E1M1 from its start, looping, on the tables of sds_std;
; interrupts on (fx_song holds the effects while snd_start bursts)
song_start:
        lda     #SONG_BANK
        sta     snd_song_bank
        lda     #<SONG_AT
        sta     snd_song_addr
        lda     #>SONG_AT
        sta     snd_song_addr+1
        lda     sds_std
        and     #SONG_NTSC
        ora     #SONG_LOOP
        sta     snd_song_flags
        stz     snd_song_matt
        lda     #M_SONG
        sta     sds_mark
        jsr     fx_song
        stz     sds_mark
        bcc     :+
        sta     errcode
        stz     songon
        lda     #1
        tsb     redraw
        lda     #<s_refused
        ldx     #>s_refused
        jmp     show_error
:       lda     #1
        sta     songon
        tsb     redraw
        rts

; ---------------------------------------------------------------------------
; play: A = the key (K_*): every effect stopped, then the chosen effect
; at the chosen distance by the mailboxes (fxrun65.py act_start's writes)
; ---------------------------------------------------------------------------
play:   sta     lastkey
        stz     rcount
        php
        sei
        lda     #M_STOPALL
        sta     sds_mark
        jsr     fx_stopall
        lda     sds_cur
        inc     a
        sta     snd
        ldy     dist
        lda     vol_of,y
        sta     vol
        ldx     #0
        stx     sds_lastch
        lda     lastkey
        cmp     #K_C
        beq     @c
        tay
        lda     sep_of - 1,y
        jsr     mail_start              ; channel 0
        bra     @done
@c:     lda     #SEP_LEFT               ; channel 0 takes A
        jsr     mail_start
        ldx     #1                      ; channel 1, the effect: C
        stx     sds_lastch
        lda     #SEP_LEFT
        jsr     mail_start
        lda     #M_SERVICE
        sta     sds_mark
        jsr     fx_service
        lda     #M_STOP                 ; channel 0 stopped: A ends
        sta     sds_mark
        lda     SC_MAIL + MX_FLAGS
        ora     #MX_STOP
        and     #<~(MX_START | MX_VOLUME)
        sta     SC_MAIL + MX_FLAGS
        lda     #M_SERVICE
        sta     sds_mark
        jsr     fx_service
@done:  stz     sds_mark
        plp
        lda     #1
        sta     showv
        lda     #4
        tsb     redraw
        rts

; mail_start: channel X's mailbox: start, snd, vol, separation A. X kept.
mail_start:
        pha
        lda     #M_START
        sta     sds_mark
        phx
        txa
        asl     a
        asl     a
        tax
        lda     SC_MAIL + MX_FLAGS,x
        ora     #MX_START
        sta     SC_MAIL + MX_FLAGS,x
        lda     snd
        sta     SC_MAIL + MX_SOUND,x
        lda     vol
        sta     SC_MAIL + MX_VOL,x
        plx
        pla
        phx
        pha
        txa
        asl     a
        asl     a
        tax
        pla
        sta     SC_MAIL + MX_SEP,x
        plx
        rts

vol_of: .byte   VOL_NEAR, VOL_MID, VOL_FAR
sep_of: .byte   SEP_AHEAD, SEP_LEFT, SEP_RIGHT

; ---------------------------------------------------------------------------
; the screen
; ---------------------------------------------------------------------------
draw_all:
        lda     #1
        ldx     #23
        jsr     clear_rows
        ldy     #ROW_KEYS
        lda     #<s_keys
        ldx     #>s_keys
        jsr     put_lines
        lda     #7
        sta     redraw
        ; (falls into screen)

; screen: what changed; the voice of the last play after its service
screen: lda     redraw
        lsr     a
        bcc     :+
        jsr     draw_machine
:       lda     redraw
        and     #2
        beq     :+
        jsr     draw_list
:       lda     redraw
        and     #4
        beq     :+
        jsr     draw_effect
:       stz     redraw
        lda     showv
        beq     :+
        stz     showv
        jmp     draw_voice
:       rts

draw_machine:
        lda     #ROW_MACHINE
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_MACHINE
        jsr     put_at
        lda     #<s_pal
        ldx     #>s_pal
        bit     sds_std
        bpl     :+
        lda     #<s_ntsc
        ldx     #>s_ntsc
:       jsr     put_str
        ldx     #9
        ldy     #ROW_MACHINE
        jsr     put_at
        lda     music
        bne     :+
        lda     #<s_noeffects
        ldx     #>s_noeffects
        jmp     put_str
:       lda     #<s_native
        ldx     #>s_native
        jsr     put_str
        lda     songon
        beq     :+
        ldx     #COL_MUSIC
        ldy     #ROW_MACHINE
        jsr     put_at
        lda     #<s_music
        ldx     #>s_music
        jsr     put_str
:       lda     rep
        beq     :+
        ldx     #COL_REPEAT
        ldy     #ROW_MACHINE
        jsr     put_at
        lda     #<s_repeat
        ldx     #>s_repeat
        jsr     put_str
:       rts

; draw_list: 52 cells, 3 columns of 18: the cursor, the name, T (tuned)
; or A (a tuned effect set to its automatic script)
draw_list:
        stz     index
@cell:  lda     index
        ldx     #0
:       cmp     #COLROWS
        bcc     :+
        sbc     #COLROWS
        inx
        bra     :-
:       clc
        adc     #ROW_LIST
        tay
        lda     col_x,x
        tax
        jsr     put_at
        lda     #' '
        ldx     index
        cpx     sds_cur
        bne     :+
        lda     #'>'
:       jsr     put_char
        lda     #' '
        jsr     put_char
        lda     index
        jsr     put_name
        lda     #' '
        jsr     put_char
        ldx     index
        lda     #' '
        ldy     sds_tuned,x
        beq     :+
        lda     #'T'
        ldy     sds_ver,x
        beq     :+
        lda     #'A'
:       jsr     put_char
        inc     index
        lda     index
        cmp     #NSFX
        bcc     @cell
        rts

col_x:  .byte   0, 13, 26

; draw_effect: the chosen effect: its name, version, checksum, distance
draw_effect:
        lda     #ROW_EFFECT
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_EFFECT
        jsr     put_at
        lda     sds_cur
        jsr     put_name
        ldx     #COL_VER
        ldy     #ROW_EFFECT
        jsr     put_at
        ldx     sds_cur
        lda     sds_tuned,x
        beq     @auto
        lda     sds_ver,x
        bne     @auto
        lda     #<s_tuned
        ldx     #>s_tuned
        bra     :+
@auto:  lda     #<s_auto
        ldx     #>s_auto
:       jsr     put_str
        ldx     #COL_SUM
        ldy     #ROW_EFFECT
        jsr     put_at
        lda     #<s_sum
        ldx     #>s_sum
        jsr     put_str
        jsr     script_sum
        lda     sds_sum+1
        jsr     put_hex
        lda     sds_sum
        jsr     put_hex
        ldx     #COL_DIST
        ldy     #ROW_EFFECT
        jsr     put_at
        lda     dist
        asl     a
        tax
        lda     s_dists,x
        pha
        lda     s_dists+1,x
        tax
        pla
        jmp     put_str

s_dists:
        .word   s_near, s_mid, s_far

; draw_voice: the voice the last play's channel has, after its service
; (fx.s's voices in the card), '-' when none
draw_voice:
        ldx     #COL_VOICE
        ldy     #ROW_EFFECT
        jsr     put_at
        ldx     #0
        ldy     #0
@v:     lda     FXV_BASE + V_FLAGS,x
        bpl     @n
        lda     FXV_BASE + V_CHAN,x
        cmp     sds_lastch
        beq     @found
@n:     txa
        clc
        adc     #VOICE_SIZE
        tax
        iny
        cpy     #VOICES
        bcc     @v
        lda     #<s_novoice
        ldx     #>s_novoice
        jmp     put_str
@found: tya
        asl     a
        tax
        lda     s_voices,x
        pha
        lda     s_voices+1,x
        tax
        pla
        jmp     put_str

s_voices:
        .word   s_va, s_vb, s_vc

; script_sum: sds_sum = the checksum of the chosen effect's script as the
; directory in bank SFX gives it (header included): for each byte, the
; sum rotated left one bit, then the byte added (fxdisk.py script_sum)
script_sum:
        stz     sds_sum
        stz     sds_sum+1
        lda     sds_cur                 ; its directory entry, read
        asl     a
        asl     a
        clc
        adc     #<SFX_AT
        sta     fxc_ld + 1
        lda     #>SFX_AT
        adc     #0
        sta     fxc_ld + 2
        lda     #<scratch
        sta     fxc_st + 1
        lda     #>scratch
        sta     fxc_st + 2
        lda     #4
        jsr     fx_copy
        lda     scratch
        sta     src
        lda     scratch+1
        sta     src+1
        lda     scratch+2
        sta     cnt
        lda     scratch+3
        sta     cnt+1
@piece: lda     cnt
        ora     cnt+1
        beq     @done
        lda     cnt+1                   ; a piece: at most 128 bytes
        bne     @full
        lda     cnt
        cmp     #128
        bcc     :+
@full:  lda     #128
:       sta     index
        lda     src
        sta     fxc_ld + 1
        lda     src+1
        sta     fxc_ld + 2
        lda     index
        jsr     fx_copy                 ; to scratch (fxc_st kept)
        ldy     #0
@byte:  lda     sds_sum+1               ; rotated left, bit 15 into bit 0
        asl     a
        rol     sds_sum
        rol     sds_sum+1
        clc
        lda     sds_sum
        adc     scratch,y
        sta     sds_sum
        bcc     :+
        inc     sds_sum+1
:       iny
        cpy     index
        bne     @byte
        lda     src                     ; on
        clc
        adc     index
        sta     src
        bcc     :+
        inc     src+1
:       sec
        lda     cnt
        sbc     index
        sta     cnt
        bcs     @piece
        dec     cnt+1
        bra     @piece
@done:  rts

; show_error: the string A/X, then errcode in hex, on the effect row
show_error:
        pha
        phx
        lda     #ROW_EFFECT
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_EFFECT
        jsr     put_at
        plx
        pla
        jsr     put_str
        lda     errcode
        jmp     put_hex

; ---------------------------------------------------------------------------
; text: the 40-column page 1, written directly (no ROM)
; ---------------------------------------------------------------------------
; put_at: X = column, Y = row
put_at: txa
        clc
        adc     row_lo,y
        sta     ptr
        lda     row_hi,y
        adc     #0
        sta     ptr+1
        rts

; put_char: A, an ASCII character (upper case in inverse), at ptr
put_char:
        bit     inv
        bmi     :+
        and     #$3F
        bra     :++
:       ora     #$80
:       sta     (ptr)
        inc     ptr
        rts

; put_str: the zero-terminated string at A/X (lo/hi)
put_str:
        sta     tmp
        stx     tmp+1
        ldy     #0
:       lda     (tmp),y
        beq     :+
        phy
        jsr     put_char
        ply
        iny
        bne     :-
:       rts

; put_lines: Y = the first row; the string at A/X, its lines separated by
; $0D, from column 0
put_lines:
        sta     src
        stx     src+1
        sty     index
@line:  ldx     #0
        ldy     index
        jsr     put_at
@char:  lda     (src)
        beq     @done
        inc     src
        bne     :+
        inc     src+1
:       cmp     #$0D
        beq     @next
        jsr     put_char
        bra     @char
@next:  inc     index
        bra     @line
@done:  rts

put_spaces:                             ; X spaces
:       lda     #' '
        phx
        jsr     put_char
        plx
        dex
        bne     :-
        rts

; clear_rows: X rows from row A
clear_rows:
        stx     tmp
        sta     tmp+1
:       phx
        ldx     #0
        ldy     tmp+1
        jsr     put_at
        ldx     #40
        jsr     put_spaces
        plx
        inc     tmp+1
        dec     tmp
        bne     :-
        rts

; put_name: the effect A's name (6 characters)
put_name:
        sta     tmp
        stz     tmp+1
        asl     a
        adc     tmp                     ; x 3 (A < 52: no carry)
        asl     a                       ; x 6, its carry into the high byte
        rol     tmp+1
        clc
        adc     #<sfx_names
        sta     tmp
        lda     tmp+1
        adc     #>sfx_names
        sta     tmp+1
        ldy     #0
:       lda     (tmp),y
        phy
        jsr     put_char
        ply
        iny
        cpy     #6
        bne     :-
        rts

; put_hex: A as two hexadecimal digits
put_hex:
        pha
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        jsr     @nibble
        pla
        and     #$0F
@nibble:
        cmp     #10
        bcc     :+
        adc     #6
:       adc     #'0'
        jmp     put_char

; ---------------------------------------------------------------------------
; the machine
; ---------------------------------------------------------------------------
mouse_check:                            ; carry clear: the mouse card
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
        clc
        rts
@none:  sec
        rts

mouse_on:
        lda     #ACK_ALL
        sta     MOUSE_ACK
        lda     #MODE_VBL
        sta     MOUSE_MODE
        rts

mouse_off:
        stz     MOUSE_MODE
        lda     #ACK_ALL
        sta     MOUSE_ACK
        rts

; ram_check: carry clear when RamWorks banks 1 to SFX_BANK are distinct
; memory (MUSIC.SYSTEM's check, to bank SFX): each bank gets its number at
; RAMCHECK, highest first, then each is read back by the page-1 copy
ram_check:
        ldx     #SFX_BANK
:       stx     RAMWORKS
        sta     RAMWRT_ON
        stx     RAMCHECK
        sta     RAMWRT_OFF
        dex
        bne     :-
        stz     RAMWORKS
        jsr     p1_install
        lda     #1
        sta     index
@bank:  lda     index
        sta     p1bank
        lda     #<RAMCHECK
        sta     src
        lda     #>RAMCHECK
        sta     src+1
        lda     #<scratch
        sta     dst
        lda     #>scratch
        sta     dst+1
        ldx     #1
        jsr     P1COPY
        lda     scratch
        cmp     index
        bne     @bad
        inc     index
        lda     index
        cmp     #SFX_BANK + 1
        bcc     @bank
        clc
        rts
@bad:   sec
        rts

p1_install:
        ldx     #p1_end - p1_code - 1
:       lda     p1_code,x
        sta     P1COPY,x
        dex
        bpl     :-
        rts

; copy_pages: X pages from (src) to (dst)
copy_pages:
        ldy     #0
:       lda     (src),y
        sta     (dst),y
        iny
        bne     :-
        inc     src+1
        inc     dst+1
        dex
        bne     :-
        rts

; to_sfx: cnt bytes from main (src) to bank SFX (dst), by RAMWRT (this
; code reads main memory). src and dst advance; cnt ends at 0.
to_sfx: lda     #SFX_BANK
        sta     RAMWORKS
        sta     RAMWRT_ON
@byte:  lda     cnt
        ora     cnt+1
        beq     @done
        lda     (src)
        sta     (dst)
        inc     src
        bne     :+
        inc     src+1
:       inc     dst
        bne     :+
        inc     dst+1
:       lda     cnt
        bne     :+
        dec     cnt+1
:       dec     cnt
        bra     @byte
@done:  sta     RAMWRT_OFF
        stz     RAMWORKS
        rts

; load_file: the file whose ProDOS path is at A/X into DATABUF, whole;
; length = its length. A ProDOS error or a file that fills the buffer
; stops the boot.
load_file:
        sta     op_path
        stx     op_path+1
        jsr     MLI
        .byte   $C8                     ; OPEN
        .word   op_parms
        bcs     @prodos
        lda     op_ref
        sta     rd_ref
        sta     cl_ref
        jsr     MLI
        .byte   $CA                     ; READ
        .word   rd_parms
        php
        pha
        jsr     MLI
        .byte   $CC                     ; CLOSE
        .word   cl_parms
        pla
        plp
        bcs     @prodos
        lda     rd_got
        sta     length
        lda     rd_got+1
        sta     length+1
        cmp     #>DATAMAX
        bcs     @size
        rts
@prodos:
        sta     errcode
        lda     #<s_prodos
        ldx     #>s_prodos
        jmp     sds_fatal_code
@size:  lda     #<s_size
        ldx     #>s_size
        jmp     sds_fatal

; load_sfx: SFX.1 into bank SFX at $0200; its directory and tuned flags
; noted; then each tuned effect's automatic script from SFXAUTO.1 after
; SFX.1 in the bank, and its entry noted
load_sfx:
        ldx     #0
        ldy     #ROW_MSG
        jsr     put_at
        lda     #<s_loading
        ldx     #>s_loading
        jsr     put_str
        lda     #<p_sfx
        ldx     #>p_sfx
        jsr     load_file
        lda     length                  ; it must leave the room's end free
        cmp     #<(SFX_END - SFX_AT)
        lda     length+1
        sbc     #>(SFX_END - SFX_AT)
        bcc     :+
        jmp     @room
:       lda     #<DATABUF
        sta     src
        lda     #>DATABUF
        sta     src+1
        lda     #<SFX_AT
        sta     dst
        lda     #>SFX_AT
        sta     dst+1
        lda     length
        sta     cnt
        lda     length+1
        sta     cnt+1
        jsr     to_sfx
        lda     dst                     ; the bank's next free byte
        sta     sds_next
        lda     dst+1
        sta     sds_next+1
        ldx     #0                      ; X: the effect; Y: its entry
@entry: txa
        asl     a
        asl     a
        tay
        lda     DATABUF,y
        sta     sds_tdir,y
        sta     src
        lda     DATABUF+1,y
        sta     sds_tdir+1,y
        sta     src+1
        lda     DATABUF+2,y
        sta     sds_tdir+2,y
        lda     DATABUF+3,y
        sta     sds_tdir+3,y
        clc                             ; its header's flags: DATABUF +
        lda     src                     ; address - SFX_AT + 1
        adc     #<(DATABUF - SFX_AT + 1)
        sta     src
        lda     src+1
        adc     #>(DATABUF - SFX_AT + 1)
        sta     src+1
        lda     (src)
        and     #1                      ; bit 0: tuned
        sta     sds_tuned,x
        eor     #1
        sta     sds_ver,x               ; tuned ones start tuned
        inx
        cpx     #NSFX
        bcc     @entry
        lda     #<p_auto
        ldx     #>p_auto
        jsr     load_file
        ldx     #0
@auto:  lda     sds_tuned,x
        beq     @next
        txa
        asl     a
        asl     a
        tay
        lda     sds_next                ; its place in the bank
        sta     sds_adir,y
        sta     dst
        lda     sds_next+1
        sta     sds_adir+1,y
        sta     dst+1
        lda     DATABUF+2,y             ; its length
        sta     sds_adir+2,y
        sta     cnt
        lda     DATABUF+3,y
        sta     sds_adir+3,y
        sta     cnt+1
        clc                             ; the next free byte after it
        lda     sds_next
        adc     cnt
        sta     sds_next
        lda     sds_next+1
        adc     cnt+1
        sta     sds_next+1
        cmp     #>SFX_END
        bcs     @room
        clc                             ; from DATABUF + address - SFX_AT
        lda     DATABUF,y
        adc     #<(DATABUF - SFX_AT)
        sta     src
        lda     DATABUF+1,y
        adc     #>(DATABUF - SFX_AT)
        sta     src+1
        phx
        jsr     to_sfx
        plx
@next:  inx
        cpx     #NSFX
        bcc     @auto
        rts
@room:  lda     #<s_room
        ldx     #>s_room
        jmp     sds_fatal

; load_song: E1M1.AY into the songs' bank at SONG_AT
load_song:
        lda     #<p_song
        ldx     #>p_song
        jsr     load_file
        lda     #SONG_BANK
        sta     RAMWORKS
        sta     RAMWRT_ON
        lda     #<DATABUF
        sta     src
        lda     #>DATABUF
        sta     src+1
        lda     #<SONG_AT
        sta     dst
        lda     #>SONG_AT
        sta     dst+1
        ldx     length+1
        inx                             ; whole pages
        jsr     copy_pages
        sta     RAMWRT_OFF
        stz     RAMWORKS
        rts

; save_prodos: ProDOS's card (both $D000 banks and $E000-$FFFF) into
; SAVE_BANK, for the quit
save_prodos:
        bit     LCBANK1
        bit     LCBANK1
        lda     #SAVE_BANK
        sta     RAMWORKS
        sta     RAMWRT_ON
        stz     src
        lda     #$D0
        sta     src+1
        stz     dst
        lda     #>SAVE_ADDR
        sta     dst+1
        ldx     #$30
        jsr     copy_pages
        bit     LC_RW_BANK2
        bit     LC_RW_BANK2
        stz     src
        lda     #$D0
        sta     src+1
        ldx     #$10
        jsr     copy_pages              ; dst goes on at SAVE_ADDR + $3000
        sta     RAMWRT_OFF
        stz     RAMWORKS
        rts

; install: the card image ($E900-$FFFF); $D000 bank 1 stays selected
install:
        bit     LCBANK1
        bit     LCBANK1
        lda     #<LC_IMAGE
        sta     src
        lda     #>LC_IMAGE
        sta     src+1
        lda     #<LC_RUN
        sta     dst
        lda     #>LC_RUN
        sta     dst+1
        ldx     #LC_PAGES
        jmp     copy_pages

; restore_prodos: ProDOS's card back from SAVE_BANK, the ROM selected
restore_prodos:
        jsr     p1_install
        lda     #SAVE_BANK
        sta     p1bank
        bit     LCBANK1
        bit     LCBANK1
        stz     src
        lda     #>SAVE_ADDR
        sta     src+1
        stz     dst
        lda     #$D0
        sta     dst+1
        ldx     #$30
        jsr     P1COPY
        bit     LC_RW_BANK2
        bit     LC_RW_BANK2
        lda     #$D0
        sta     dst+1
        ldx     #$10
        jsr     P1COPY                  ; src goes on at SAVE_ADDR + $3000
        bit     LCROM
        rts

; sds_quit: the chips reset, ProDOS back, ProDOS's QUIT
sds_quit:
        sei
        lda     #M_QUIT
        sta     sds_mark
        jsr     mouse_off
        jsr     snd_init
        jsr     restore_prodos
        lda     #0
        ldx     #24
        jsr     clear_rows
; quit_prodos: the Phasor back in Mockingboard mode, its power-on mode,
; for the next program; then ProDOS's QUIT
quit_prodos:
        bit     PHASOR_MB
        jsr     MLI
        .byte   $65                     ; QUIT
        .word   quit_parms
:       bra     :-

; sds_fatal: the string A/X on the message rows, a key, ProDOS's QUIT
; (before the card image is installed: ProDOS is still in the card)
sds_fatal:
        stz     errcode
sds_fatal_code:
        sta     fatal_msg
        stx     fatal_msg+1
        lda     #ROW_MSG
        ldx     #7
        jsr     clear_rows
        lda     fatal_msg
        ldx     fatal_msg+1
        ldy     #ROW_MSG
        jsr     put_lines
        lda     errcode
        beq     :+
        jsr     put_hex
:       lda     #<s_anykey
        ldx     #>s_anykey
        ldy     #22
        jsr     put_lines
        sta     KBDSTRB
:       lda     KBD
        bpl     :-
        sta     KBDSTRB
        bra     quit_prodos

; ---------------------------------------------------------------------------
        .segment "SDSDATA"

; the page-1 copy: X pages from (src) in RamWorks bank p1bank (RAMRD on) to
; (dst). It runs at $0100: page 1 stays main memory whatever RAMRD says.
; Only relative branches, so it runs wherever it is copied.
p1_code:
        lda     p1bank
        sta     RAMWORKS
        sta     RAMRD_ON
        ldy     #0
:       lda     (src),y
        sta     (dst),y
        iny
        bne     :-
        inc     src+1
        inc     dst+1
        dex
        bne     :-
        sta     RAMRD_OFF
        stz     RAMWORKS
        rts
p1_end:
        .assert p1_end - p1_code <= $40, error, "the page-1 copy"

op_parms:
        .byte   3
op_path:
        .word   0
        .word   IOBUF
op_ref: .byte   0
rd_parms:
        .byte   4
rd_ref: .byte   0
        .word   DATABUF
        .word   DATAMAX
rd_got: .word   0
cl_parms:
        .byte   1
cl_ref: .byte   0
quit_parms:
        .byte   4, 0
        .word   0
        .byte   0
        .word   0

p_sfx:  .byte   5, "SFX.1"
p_auto: .byte   9, "SFXAUTO.1"
p_song: .byte   7, "E1M1.AY"

row_lo: .repeat 24, R
        .byte   <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
row_hi: .repeat 24, R
        .byte   >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep

        SFX_NAMES

s_title:
        .byte   "DOOM GS: THE EFFECTS ON THE PHASOR", 0
s_pal:  .byte   "PAL //E", 0
s_ntsc: .byte   "NTSC //E", 0
s_native:
        .byte   "PHASOR NATIVE  CHIP 3", 0
s_noeffects:
        .byte   "NO EFFECTS: NO NATIVE MODE", 0
s_music:.byte   "MUSIC", 0
s_repeat:
        .byte   "REP", 0
s_tuned:.byte   "TUNED", 0
s_auto: .byte   "AUTO", 0
s_sum:  .byte   "SUM ", 0
s_near: .byte   "NEAR", 0
s_mid:  .byte   "MID", 0
s_far:  .byte   "FAR", 0
s_va:   .byte   "A LEFT", 0
s_vb:   .byte   "B RIGHT", 0
s_vc:   .byte   "C CENTRE", 0
s_novoice:
        .byte   "-", 0
s_keys: .byte   "ARROWS CHOOSE  RETURN PLAY  A B C VOICE", $0D
        .byte   "1 NEAR 2 MID 3 FAR  T TUNED  R REPEAT", $0D
        .byte   "M MUSIC  S STOP  V PAL/NTSC  Q QUIT", 0
s_loading:
        .byte   "LOADING", 0
s_nomouse:
        .byte   "NO MOUSE CARD IN SLOT 2. ITS VBL", $0D
        .byte   "INTERRUPT IS THE EFFECTS' CLOCK: TURN ON", $0D
        .byte   "THE APPLETINI'S MOUSE CARD IN SLOT 2.", 0
s_noram:
        .byte   "THE EFFECTS NEED RAMWORKS BANKS 1-103:", $0D
        .byte   "TURN ON THE APPLETINI'S RAMWORKS.", 0
s_prodos:
        .byte   "PRODOS ERROR LOADING A FILE: $", 0
s_size: .byte   "A FILE IS TOO LONG.", 0
s_room: .byte   "THE SCRIPTS PASS $3FFF OF THEIR BANK.", 0
s_refused:
        .byte   "THE PLAYER REFUSED THE SONG: ERROR $", 0
s_anykey:
        .byte   "PRESS A KEY TO QUIT.", 0
