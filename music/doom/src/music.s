; MUSIC.SYSTEM: plays the 13 songs on the Phasor's four AY chips. The
; Makefile builds it and the disk.
;
; Boot, at $2000 under ProDOS, with interrupts masked:
;   1. the text screen (40 columns, page 1; SHR off);
;   2. a mouse card in any slot (its ID bytes) is set to mode 0 and its
;      interrupt cleared (mouse_off): only VIA-B may interrupt;
;   3. the card in slot 4 has a 6522 VIA-B (timer_check): timer 1 of
;      VIA-B is the music's clock; none, and the program says so and
;      quits;
;   4. the aux 64K: ProDOS's /RAM disk (slot 3, drive 2) is disconnected
;      (ram_off), then aux_check: no aux memory, and the program says so
;      and quits;
;   5. snd_probe (probe.s): SND_MUSIC (the card switched to the Phasor's
;      native mode, 4 AY chips) or SND_NO_MUSIC, which the screen explains
;      (there is no 6-voice fallback);
;   6. ProDOS's $E000-$FFFF is saved in aux SAVE_PRODOS, then the card
;      gets the player (player.s, at the addresses of music.cfg): its
;      vector at $FFFE is snd_irq (irq.s);
;   7. snd_init;
;   8. PAL or NTSC, interrupts masked: VIA-A's timer 1 counts Apple bus
;      cycles from the start of a vertical blanking to the next, seen at
;      $C019 (RDVBLBAR: bit 7 low in the blanking): 20,280 on a PAL //e
;      (312 lines of 65 cycles), 17,030 on NTSC (262 lines);
;   9. VIA-B's timer 1 free-running with a frame of that standard a period
;      (timer_on), its interrupt on, CLI: an interrupt at the VBL's rate,
;      50.08 Hz on PAL and 59.92 Hz on NTSC; V switches the tables by hand,
;      not the timer;
;  10. with music, the first song loads and starts, looping.
;
; Then the main loop serves each interrupt (mus_service, once a frame):
; the keys, the next song when one ends in "play all" mode, snd_refill,
; the clock on the screen. Its wait (mus_idle) spins to the next
; interrupt.
;
; Keys: A-M play a song, SPACE stops, N (or right arrow) the next, P (or
; left arrow) the previous, R switches between each song looping and
; playing all the songs once in turn, T runs the AY timing test
; (aytime.s), V switches PAL and NTSC tables, Q (or ESC) quits: the chips
; are reset, VIA-B's timer is stopped (timer_off), ProDOS's card is put
; back, the Phasor goes back to Mockingboard mode, and ProDOS's QUIT runs.
;
; One song is in memory, main SONG_ADDR, read whole from the disk when it
; is chosen (load_song): the music stops, ProDOS's $E000-$FFFF goes back
; into the card for the MLI calls (card_prodos: interrupts masked, VIA-B's
; interrupt off), then the player comes back (card_player: ProDOS's
; bytes, as the calls left them, kept in aux SAVE_PRODOS; the player's
; state pages cleared, its code from the card image). The player reads the
; song from main memory: no mapping switch while the music plays.
;
; Memory, main: $0100-$013F the page-1 copy (p1_code), $0400-$07FF the
; text page, $1000-$1FFF this program's data (MUSBSS), $2000-$3FFF its
; code, $4000-$56FF the card image, $5C00-$5FFF ProDOS's buffer for the
; open file, $6000-$B7FF the song, $BF00-$BFFF ProDOS's global page.
; Aux: $A000-$BFFF ProDOS's $E000-$FFFF (SAVE_PRODOS), outside the video
; pages, whose writes the Appletini copies to the motherboard. The card:
; $E000-$FFFF the player (music.cfg), $D000-$DFFF (both banks) ProDOS's,
; never written.
;
; The interrupt runs only irq.s and the player: the zero page $D8-$FF, the
; stack, $E000-$FFFF and the Phasor. This program's zero page is at $18;
; no CPU store of it reaches $0878-$087F or $4078-$407F, where the
; Appletini firmware reads its A2Li signature.

        .setcpu "65C02"
        .include "sound.inc"
        .include "songs.inc"

        .import snd_probe, snd_init, snd_start, snd_stop, snd_refill
        .import snd_song_addr, snd_song_flags, snd_song_matt
        .import snd_error, snd_playing, ended
        .importzp irq_count
        .import ayt_run

        .export start, mus_idle, mus_service, mus_quit, mus_fatal, mus_stop
        .export mus_loaded, mus_playing
        .export put_at, put_char, put_str, put_spaces, clear_rows
        .export wait_irq, draw_status, draw_songs, song_path
        .export vblcyc, errcode, load_song, load_done, mli_call
        .exportzp ptr, inv, state, ntsc, music, seen

MLI             = $BF00
KBD             = $C000
KBDSTRB         = $C010
STORE80OFF      = $C000
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
LCROM           = $C082         ; read the ROM, no writes
LCBANK1         = $C08B         ; twice: read and write RAM, $D000 bank 1
MACHID          = $BF98         ; ProDOS: bits 5-4 = 11, 128K
NODEV           = $BF10         ; ProDOS: the "no device" driver
DEVADR32        = $BF26         ; ProDOS: the driver of slot 3, drive 2
DEVCNT          = $BF31         ; ProDOS: the last index of DEVLST
DEVLST          = $BF32         ; ProDOS: the online devices' unit numbers
RDVBLBAR        = $C019         ; bit 7 low in the vertical blanking
VIA_A_T1CL      = $C414         ; VIA-A's timer 1 (in both card modes)
VIA_A_T1CH      = $C415
VIA_A_T1LL      = $C416
ACR_FREE        = $40           ; ACR: timer 1 free-running, no PB7 output

LC_IMAGE        = $4000         ; the card image in MUSIC.SYSTEM (music.cfg)
LC_RUN          = $E900
LC_PAGES        = $17           ; $E900-$FFFF
CARD            = $E000         ; the part of the card the player takes:
CARD_PAGES      = $20           ;   $E000-$FFFF
IOBUF           = $5C00         ; ProDOS's buffer for the open file
SONG_ADDR       = $6000         ; the song in memory, main, read whole
DATAMAX         = $5800         ;   $6000-$B7FF
SAVE_PRODOS     = $A000         ; aux: ProDOS's $E000-$FFFF (player in)
STATE_PAGES     = >LC_RUN - >CARD ; the player's state: $E000-$E8FF
P1COPY          = $0100         ; the page-1 copy (p1_code)
MOUSE_SET       = $12           ; mouse firmware: SETMOUSE's entry offset
MOUSE_SERVE     = $13           ;   and SERVEMOUSE's
GAP             = 50            ; frames from a song's end to the next ("all")
PAL_FRAME       = 20280         ; bus cycles a frame: 312 lines of 65
NTSC_FRAME      = 17030         ;   and 262
PAL_NTSC_CUT    = (PAL_FRAME + NTSC_FRAME) / 2
T1_PAL          = PAL_FRAME - 2 ; VIA-B's latch: free-running, a 6522's
T1_NTSC         = NTSC_FRAME - 2 ;  timer 1 times out every latch + 2 cycles

ROW_TITLE       = 0
ROW_MACHINE     = 1
ROW_CARD        = 2
ROW_SONGS       = 4             ; 7 rows, two columns
ROW_STATUS      = 12
ROW_KEYS        = 14
ROW_MSG         = 17            ; 17-23: the timing test, messages
COL_TIME        = 17

        .assert NSONGS <= 14, error, "the song list has 14 places"
        .assert LC_IMAGE + LC_PAGES * $100 <= IOBUF, error, "the image"
        .assert IOBUF + $400 <= SONG_ADDR, error, "the file buffer"
        .assert SONG_ADDR + DATAMAX <= $BF00, error, "the song buffer"
        .assert MAX_SONG <= DATAMAX, error, "a song larger than the buffer"
        .assert SAVE_PRODOS + CARD_PAGES * $100 <= $C000, error, "aux"

; ---------------------------------------------------------------------------
        .segment "MUSZP": zeropage
ptr:    .res 2          ; the text position
src:    .res 2          ; copies
dst:    .res 2
seen:   .res 2          ; the interrupt count the main loop has served
tmp:    .res 2
num:    .res 2          ; a number to print
song:   .res 1          ; the song shown, 0 to NSONGS-1
state:  .res 1          ; 1: a song plays
music:  .res 1          ; 1: snd_probe said SND_MUSIC
ntsc:   .res 1          ; SONG_NTSC or 0
rate:   .res 1          ; interrupts a second on the screen's clock: 50 or 60
through:.res 1          ; 1: play all, each song once in turn; 0: loop
endwait:.res 1          ; interrupts since the song ended ("all")
fsub:   .res 1          ; interrupts into the clock's second
secs:   .res 2          ; the song's time, in seconds
inv:    .res 1          ; text: $80 normal, 0 inverse
loaded: .res 1          ; the song in memory, $FF for none
index:  .res 1
lastv:  .res 1          ; the interrupt count at the clock's last call
ticked: .res 1
lead:   .res 1          ; put_u16: a digit was printed

        .segment "MUSBSS"
scratch:.res 256        ; the aux check reads a page here
vblcyc: .res 2          ; timer 1 cycles over one VBL, as measured
errcode:.res 1          ; the last error (ProDOS or snd_start's)
mus_loaded:
        .res 1          ; songs loaded from the disk, a count
mus_playing:
        .res 1          ; the song playing +1, 0 for none
length: .res 2          ; a file's length, as read
fatal_msg:
        .res 2
mvec:   .res 2          ; a mouse firmware entry
wanted: .res 1          ; the song load_song loads

; ---------------------------------------------------------------------------
        .segment "MUSCODE"

start:  sei
        cld
        ldx     #$FF
        txs
        sta     STORE80OFF
        sta     RAMRD_OFF
        sta     RAMWRT_OFF
        sta     ALTZPOFF
        sta     INTCXROMOFF
        lda     #$01                    ; SHR off
        sta     NEWVIDEO
        sta     COL80OFF
        sta     ALTCHAROFF
        sta     TEXTON
        sta     MIXEDOFF
        sta     PAGE1
        lda     #$80
        sta     inv
        stz     state
        stz     music
        stz     ntsc
        stz     through
        stz     song
        stz     mus_loaded
        stz     mus_playing
        stz     errcode
        lda     #$FF
        sta     loaded
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
        jsr     mouse_off               ; only VIA-B interrupts
        ; VIA-B: the music's clock
        jsr     timer_check
        bcc     :+
        lda     #<s_notimer
        ldx     #>s_notimer
        jmp     mus_fatal
:       ; the aux 64K
        jsr     ram_off
        jsr     aux_check
        bcc     :+
        lda     #<s_noaux
        ldx     #>s_noaux
        jmp     mus_fatal
:       ; the Phasor
        jsr     snd_probe
        bcs     :+
        inc     music
:       jsr     save_prodos
        jsr     install
        jsr     snd_init
        jsr     detect_video
        jsr     timer_on
        cli
        jsr     draw_all
        sei
        lda     irq_count
        sta     seen
        sta     lastv
        lda     irq_count+1
        sta     seen+1
        cli
        lda     music
        beq     mus_service
        lda     #0
        jsr     play

; ---------------------------------------------------------------------------
; the main loop: one service an interrupt
; ---------------------------------------------------------------------------
mus_service:
        sei
        lda     irq_count
        sta     seen
        lda     irq_count+1
        sta     seen+1
        cli
        jsr     keys
        jsr     through_check
        lda     music
        beq     :+
        jsr     snd_refill
:       jsr     clock
mus_idle:
        lda     irq_count
        cmp     seen
        beq     mus_idle
        bra     mus_service

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
:       cmp     #'Q'
        beq     @quit
        cmp     #$1B                    ; ESC
        beq     @quit
        cmp     #'T'
        beq     @time
        cmp     #'V'
        beq     @video
        ldx     music
        beq     @none                   ; no music: Q, T, V only
        cmp     #'A'
        bcc     @control
        cmp     #'A' + NSONGS
        bcs     @control
        sbc     #'A' - 1                ; (carry clear)
        jmp     play
@control:
        cmp     #' '
        beq     mus_stop
        cmp     #'N'
        beq     next
        cmp     #$15                    ; right arrow
        beq     next
        cmp     #'P'
        beq     previous
        cmp     #$08                    ; left arrow
        beq     previous
        cmp     #'R'
        beq     @repeat
@none:  rts
@quit:  jmp     mus_quit
@time:  jsr     ayt_run
        jmp     draw_status
@repeat:
        lda     through
        eor     #1
        sta     through
        jmp     draw_status
@video: lda     ntsc
        eor     #SONG_NTSC
        sta     ntsc
        jsr     set_rate
        jsr     draw_machine
        lda     state
        beq     :+
        lda     song                    ; the song again, on the new tables
        jmp     play
:       rts

mus_stop:
        lda     state
        beq     :+
        jsr     snd_stop
        stz     state
        stz     mus_playing
        jsr     draw_songs
        jmp     draw_status
:       rts

next:   lda     song
        inc     a
        cmp     #NSONGS
        bcc     play
        lda     #0
        bra     play

previous:
        lda     song
        bne     :+
        lda     #NSONGS
:       dec     a
        ; (falls into play)

; play: the song A (0 to NSONGS-1), from its start; loaded from the disk
; first unless it is the one in memory
play:   sta     song
        cmp     loaded
        beq     @start
        jsr     load_song
        bcc     @start
        pha                             ; not loaded: stopped, the message
        phx
        jsr     draw_songs
        jsr     draw_status
        plx
        pla
        jmp     show_error
@start: lda     #<SONG_ADDR
        sta     snd_song_addr
        lda     #>SONG_ADDR
        sta     snd_song_addr+1
        lda     through                 ; loop unless "play all"
        eor     #SONG_LOOP
        and     #SONG_LOOP
        ora     ntsc
        sta     snd_song_flags
        stz     snd_song_matt
        jsr     snd_start
        bcc     :+
        sta     errcode
        stz     state
        stz     mus_playing
        jsr     draw_songs
        jsr     draw_status
        lda     #<s_refused
        ldx     #>s_refused
        jmp     show_error
:       lda     #1
        sta     state
        lda     song
        inc     a
        sta     mus_playing
        stz     secs
        stz     secs+1
        stz     fsub
        stz     endwait
        lda     seen
        sta     lastv
        jsr     draw_songs
        jmp     draw_status

; through_check: in "play all" mode, the next song GAP interrupts after
; the end
through_check:
        lda     through
        beq     @no
        lda     state
        beq     @no
        lda     ended
        beq     @no
        inc     endwait
        lda     endwait
        cmp     #GAP
        bcc     @no
        jmp     next
@no:    rts

; clock: the song's time on the screen, from the interrupts served
clock:  lda     seen
        sec
        sbc     lastv
        ldx     seen
        stx     lastv
        ldx     state
        beq     @done
        ldx     ended                   ; a song that ended stops its clock
        bne     @done
        clc
        adc     fsub
        sta     fsub
        stz     ticked
@second:
        lda     fsub
        cmp     rate
        bcc     @show
        sbc     rate
        sta     fsub
        inc     secs
        bne     :+
        inc     secs+1
:       inc     ticked
        bra     @second
@show:  lda     ticked
        beq     @done
        jmp     draw_time
@done:  rts

; ---------------------------------------------------------------------------
; the screen
; ---------------------------------------------------------------------------
draw_all:
        lda     #1
        ldx     #23
        jsr     clear_rows
        jsr     draw_machine
        lda     music
        bne     :+
        ldy     #ROW_CARD
        lda     #<s_nomusic
        ldx     #>s_nomusic
        jmp     put_lines
:       ldx     #0
        ldy     #ROW_CARD
        jsr     put_at
        lda     #<s_card
        ldx     #>s_card
        jsr     put_str
        jsr     draw_songs
        jsr     draw_status
        ldy     #ROW_KEYS
        lda     #<s_keys
        ldx     #>s_keys
        jmp     put_lines

draw_machine:
        lda     #ROW_MACHINE
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_MACHINE
        jsr     put_at
        lda     #<s_pal
        ldx     #>s_pal
        bit     ntsc
        bpl     :+
        lda     #<s_ntsc
        ldx     #>s_ntsc
:       jsr     put_str
        lda     #<s_t1
        ldx     #>s_t1
        jsr     put_str
        lda     vblcyc
        sta     num
        lda     vblcyc+1
        sta     num+1
        jsr     put_u16
        lda     #<s_cycles
        ldx     #>s_cycles
        jmp     put_str

; draw_songs: the list, the playing song's letter in inverse
draw_songs:
        lda     music
        beq     @done
        stz     index
@song:  lda     index
        ldx     #1
        cmp     #7
        bcc     :+
        sbc     #7
        ldx     #21
:       clc
        adc     #ROW_SONGS
        tay
        jsr     put_at
        lda     state
        beq     :+
        lda     index
        cmp     song
        bne     :+
        stz     inv
:       lda     index
        clc
        adc     #'A'
        jsr     put_char
        lda     #$80
        sta     inv
        lda     #' '
        jsr     put_char
        lda     index
        jsr     put_label
        lda     #' '
        jsr     put_char
        ldx     index
        lda     song_secs_lo,x
        sta     num
        lda     song_secs_hi,x
        sta     num+1
        jsr     put_time
        inc     index
        lda     index
        cmp     #NSONGS
        bcc     @song
@done:  rts

; draw_status: what plays, its time, the mode
draw_status:
        lda     music
        beq     @done
        lda     #ROW_STATUS
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_STATUS
        jsr     put_at
        lda     #<s_stopped
        ldx     #>s_stopped
        ldy     state
        beq     :+
        lda     #<s_playing
        ldx     #>s_playing
:       jsr     put_str
        lda     song
        jsr     put_label
        jsr     draw_time
        ldx     #COL_TIME + 7
        ldy     #ROW_STATUS
        jsr     put_at
        lda     #<s_of
        ldx     #>s_of
        jsr     put_str
        ldx     song
        lda     song_secs_lo,x
        sta     num
        lda     song_secs_hi,x
        sta     num+1
        jsr     put_time
        ldx     #34
        ldy     #ROW_STATUS
        jsr     put_at
        lda     #<s_loop
        ldx     #>s_loop
        ldy     through
        beq     :+
        lda     #<s_all
        ldx     #>s_all
:       jmp     put_str
@done:  rts

draw_time:
        ldx     #COL_TIME
        ldy     #ROW_STATUS
        jsr     put_at
        lda     secs
        sta     num
        lda     secs+1
        sta     num+1
        jsr     put_time
        lda     #' '
        jmp     put_char

; show_error: the string A/X, then errcode in hex unless 0, on the last
; row
show_error:
        pha
        phx
        lda     #23
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #23
        jsr     put_at
        plx
        pla
        jsr     put_str
        lda     errcode
        beq     :+
        lda     #'$'
        jsr     put_char
        lda     errcode
        jmp     put_hex
:       rts

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

; put_label: the song A's name (8 characters)
put_label:
        asl     a
        asl     a
        asl     a
        tax
        ldy     #8
:       lda     song_label,x
        phx
        phy
        jsr     put_char
        ply
        plx
        inx
        dey
        bne     :-
        rts

; put_time: num seconds as M:SS
put_time:
        stz     tmp
        stz     tmp+1
@minute:
        lda     num+1
        bne     :+
        lda     num
        cmp     #60
        bcc     @print
:       sec
        lda     num
        sbc     #60
        sta     num
        bcs     :+
        dec     num+1
:       inc     tmp
        bne     @minute
        inc     tmp+1
        bra     @minute
@print: lda     num                     ; the seconds, while num takes
        pha                             ; the minutes
        lda     tmp
        sta     num
        lda     tmp+1
        sta     num+1
        jsr     put_u16
        lda     #':'
        jsr     put_char
        pla
        ldx     #'0' - 1
:       inx
        sec
        sbc     #10
        bcs     :-
        adc     #'0' + 10
        pha
        txa
        jsr     put_char
        pla
        jmp     put_char

; put_u16: num in decimal, no leading zeros (num is consumed)
put_u16:
        ldy     #4
        stz     lead
@digit: ldx     #0
@sub:   sec
        lda     num
        sbc     pow_lo,y
        sta     tmp
        lda     num+1
        sbc     pow_hi,y
        bcc     @put
        sta     num+1
        lda     tmp
        sta     num
        inx
        bra     @sub
@put:   txa                             ; X: the digit
        bne     @print
        cpy     #0                      ; the units always print
        beq     @print
        lda     lead                    ; a zero, printed after a digit
        beq     @skip
@print: lda     #1
        sta     lead
        txa
        clc
        adc     #'0'
        phy
        jsr     put_char
        ply
@skip:  dey
        bpl     @digit
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
wait_irq:
        lda     irq_count
:       cmp     irq_count
        beq     :-
        rts

; detect_video: timer 1 over one VBL; PAL (20,280 cycles) or NTSC (17,030).
; The first blanking only starts the measure: both reads of the timer then
; come after a frame without a slot-4 access, the CPU in the same state.
detect_video:
        lda     #$FF
        sta     VIA_A_T1LL
        sta     VIA_A_T1CH              ; $FFFF, counting down
        jsr     vbl_start
        jsr     vbl_start
        lda     VIA_A_T1CL
        ldx     VIA_A_T1CH
        sta     tmp
        stx     tmp+1
        jsr     vbl_start
        lda     VIA_A_T1CL
        ldx     VIA_A_T1CH
        sta     num
        stx     num+1
        sec
        lda     tmp
        sbc     num
        sta     vblcyc
        lda     tmp+1
        sbc     num+1
        sta     vblcyc+1
        stz     ntsc
        lda     vblcyc
        cmp     #<PAL_NTSC_CUT
        lda     vblcyc+1
        sbc     #>PAL_NTSC_CUT
        bcs     set_rate
        lda     #SONG_NTSC
        sta     ntsc
set_rate:
        lda     #50
        bit     ntsc
        bpl     :+
        lda     #60
:       sta     rate
        rts

; mus_quit: the timer stopped, the chips reset, ProDOS back, ProDOS's QUIT
mus_quit:
        sei
        jsr     timer_off
        jsr     snd_init
        jsr     restore_prodos
        lda     #0
        ldx     #24
        jsr     clear_rows
; quit_prodos: the Phasor back in Mockingboard mode, its power-on mode
; (snd_probe and snd_init leave it native: 4 AY chips), for the next
; program; then ProDOS's QUIT. Harmless on a card that is no Phasor.
quit_prodos:
        bit     PHASOR_MB
        jsr     MLI
        .byte   $65                     ; QUIT
        .word   quit_parms
:       bra     :-

; mus_fatal: the string A/X on the message rows, a key, ProDOS's QUIT
; (before the player is installed: ProDOS is still in the card)
mus_fatal:
        sta     fatal_msg
        stx     fatal_msg+1
        lda     #ROW_MSG
        ldx     #7
        jsr     clear_rows
        lda     fatal_msg
        ldx     fatal_msg+1
        ldy     #ROW_MSG
        jsr     put_lines
        lda     #<s_anykey
        ldx     #>s_anykey
        ldy     #22
        jsr     put_lines
        sta     KBDSTRB
:       lda     KBD
        bpl     :-
        sta     KBDSTRB
        bra     quit_prodos

; This program's part of MUSCODE keeps the length MUSCODE_LENGTH: the
; timing test's code (aytime.s) follows it, its loops where their page
; checks hold. The rest of the program's code is linked after its data
; (SNDBOOT).
MUSCODE_LENGTH  = $6C3
        .assert * - start <= MUSCODE_LENGTH, error, "MUSCODE is too long"
        .res    MUSCODE_LENGTH - (* - start)

; ---------------------------------------------------------------------------
; The aux 64K, ProDOS's card and the song loads; VIA-B's timer 1, the
; music's clock: linked after the program's data (SNDBOOT), so that the
; timing test's loops keep their pages
; ---------------------------------------------------------------------------
        .segment "SNDBOOT"

; ---- the aux 64K and ProDOS's card ----

; ram_off: ProDOS's /RAM disk, slot 3 drive 2, disconnected, as the ProDOS
; 8 Technical Reference says (5.2.2.3), so that this program may use the
; aux 64K, where /RAM keeps its blocks: on a 128K machine (MACHID) whose
; slot 3 drive 2 has a driver, its unit number ($B3, $B7, $BB or $BF) is
; taken out of the device list and the driver set to NODEV. /RAM stays
; disconnected after the quit, until the next boot.
ram_off:
        lda     MACHID
        and     #$30
        cmp     #$30
        bne     @done                   ; not 128K: no /RAM
        lda     DEVADR32
        cmp     NODEV
        bne     @driver
        lda     DEVADR32+1
        cmp     NODEV+1
        beq     @done                   ; no driver in slot 3, drive 2
@driver:
        ldx     DEVCNT
@find:  lda     DEVLST,x
        and     #$F3
        cmp     #$B3
        beq     @remove
        dex
        bpl     @find
        rts                             ; not in the list: left alone
@remove:
        cpx     DEVCNT                  ; the entries after it move down
        beq     :+
        lda     DEVLST+1,x
        sta     DEVLST,x
        inx
        bra     @remove
:       dec     DEVCNT
        lda     NODEV
        sta     DEVADR32
        lda     NODEV+1
        sta     DEVADR32+1
@done:  rts

; aux_check: carry clear when the aux 64K answers: aux SAVE_PRODOS and
; SAVE_PRODOS + $1000 keep what is written there, apart from each other
; and from main memory (a 1K 80-column card, which repeats its kilobyte,
; fails), read back through the page-1 copy (a read with RAMRD on runs
; from page 1)
AUX_TEST        = SAVE_PRODOS + $1000
aux_check:
        stz     SAVE_PRODOS             ; main: 0 at both
        stz     AUX_TEST
        sta     RAMWRT_ON
        lda     #$A5
        sta     SAVE_PRODOS
        lda     #$5A
        sta     AUX_TEST
        sta     RAMWRT_OFF
        jsr     p1_install
        lda     #>SAVE_PRODOS
        jsr     aux_byte
        cmp     #$A5
        bne     @none
        lda     #>AUX_TEST
        jsr     aux_byte
        cmp     #$5A
        bne     @none
        lda     SAVE_PRODOS
        ora     AUX_TEST
        bne     @none
        clc
        rts
@none:  sec
        rts

; aux_byte: A = the first byte of the aux page A (the page read into
; scratch)
aux_byte:
        sta     src+1
        stz     src
        lda     #<scratch
        sta     dst
        lda     #>scratch
        sta     dst+1
        ldx     #1
        jsr     P1COPY
        lda     scratch
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

; card_to_aux: the card's $E000-$FFFF (its RAM read) into aux at page A,
; with RAMWRT on: the code still runs from main, the card is the card's
card_to_aux:
        sta     dst+1
        stz     dst
        stz     src
        lda     #>CARD
        sta     src+1
        sta     RAMWRT_ON
        ldx     #CARD_PAGES
        jsr     copy_pages
        sta     RAMWRT_OFF
        rts

; aux_to_card: aux from page A into the card's $E000-$FFFF (its RAM
; written), through the page-1 copy
aux_to_card:
        sta     src+1
        stz     src
        stz     dst
        lda     #>CARD
        sta     dst+1
        jsr     p1_install
        ldx     #CARD_PAGES
        jmp     P1COPY

; save_prodos: ProDOS's $E000-$FFFF into aux SAVE_PRODOS, before the
; player takes the card
save_prodos:
        bit     LCBANK1
        bit     LCBANK1
        lda     #>SAVE_PRODOS
        jmp     card_to_aux

; install: the player's state pages cleared ($E000-$E8FF: the player
; stopped), its image into the card ($E900-$FFFF); $D000 bank 1 stays
; selected
install:
        bit     LCBANK1
        bit     LCBANK1
        lda     #>CARD
        sta     dst+1
        stz     dst
        lda     #0
        ldx     #STATE_PAGES
        ldy     #0
:       sta     (dst),y
        iny
        bne     :-
        inc     dst+1
        dex
        bne     :-
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

; card_prodos: ProDOS's own bytes back in the card for MLI calls (the
; music stopped): interrupts masked and VIA-B's timer interrupt off (the
; timer runs on), ProDOS's $E000-$FFFF from aux SAVE_PRODOS, then the ROM
; selected, as ProDOS started this program
card_prodos:
        sei
        lda     #IFR_T1                 ; IER bit 7 clear: timer 1's off
        sta     VIA_B_IER
        bit     LCBANK1
        bit     LCBANK1
        lda     #>SAVE_PRODOS
        jsr     aux_to_card
        bit     LCROM
        rts

; card_player: the player back after MLI calls: ProDOS's $E000-$FFFF, as
; the calls left them, into aux SAVE_PRODOS, then the player stopped, as
; at the boot (install), VIA-B's timer interrupt on, CLI (a timer flag set
; meanwhile interrupts at once)
card_player:
        sei
        bit     LCBANK1
        bit     LCBANK1
        lda     #>SAVE_PRODOS
        jsr     card_to_aux
        jsr     install
        lda     #$80 | IFR_T1
        sta     VIA_B_IER
        cli
        rts

; restore_prodos: ProDOS's $E000-$FFFF back from aux SAVE_PRODOS, the ROM
; selected (the quit; interrupts masked, the timer stopped)
restore_prodos:
        bit     LCBANK1
        bit     LCBANK1
        lda     #>SAVE_PRODOS
        jsr     aux_to_card
        bit     LCROM
        rts

; mli_do: the MLI call A with the parameters at Y/X (high/low), from one
; place (mli_call); carry and A as the MLI returns them
mli_do: sta     mli_cmd
        stx     mli_parm
        sty     mli_parm+1
mli_call:
        jsr     MLI
mli_cmd:.byte   0
mli_parm:
        .word   0
        rts

; load_song: the song A (0 to NSONGS-1) from the disk into SONG_ADDR,
; read whole. The music stops first (its silence goes out at the next
; interrupt), then OPEN, READ and CLOSE run with ProDOS's card
; (card_prodos, card_player). Carry clear: loaded, its length the one
; songs.inc gives. Carry set: not loaded, no song in memory, A/X the
; message for show_error and errcode ProDOS's error (0 for a wrong
; length).
load_song:
        sta     wanted
        lda     #$FF
        sta     loaded
        jsr     mus_stop
:       lda     snd_playing             ; the silence's interrupt
        bne     :-
        stz     secs                    ; the clock at 0 for the new song
        stz     secs+1
        lda     #ROW_STATUS
        ldx     #1
        jsr     clear_rows
        ldx     #0
        ldy     #ROW_STATUS
        jsr     put_at
        lda     #<s_loading
        ldx     #>s_loading
        jsr     put_str
        lda     wanted
        jsr     put_label
        lda     wanted                  ; its ProDOS path: 16 bytes a song
        asl     a
        asl     a
        asl     a
        asl     a
        clc
        adc     #<song_path
        sta     op_path
        lda     #>song_path
        adc     #0
        sta     op_path+1
        stz     rd_got
        stz     rd_got+1
        jsr     card_prodos
        lda     #$C8                    ; OPEN
        ldx     #<op_parms
        ldy     #>op_parms
        jsr     mli_do
        bcs     @called
        lda     op_ref
        sta     rd_ref
        sta     cl_ref
        lda     #$CA                    ; READ
        ldx     #<rd_parms
        ldy     #>rd_parms
        jsr     mli_do
        php
        pha
        lda     #$CC                    ; CLOSE
        ldx     #<cl_parms
        ldy     #>cl_parms
        jsr     mli_do
        pla
        plp
@called:
        bcs     :+                      ; ProDOS's error, 0 for none (the
        lda     #0                      ;   flags stay here: card_player's
:       sta     errcode                 ;   CLI holds)
        jsr     card_player
        lda     errcode
        bne     @prodos
        ldx     wanted                  ; the length songs.inc gives
        lda     rd_got
        cmp     song_size_lo,x
        bne     @size
        lda     rd_got+1
        cmp     song_size_hi,x
        bne     @size
        stx     loaded
        inc     mus_loaded
        bra     load_done
@prodos:
        lda     #<s_prodos
        ldx     #>s_prodos
        sec
        rts
@size:  stz     errcode
        lda     #<s_size
        ldx     #>s_size
        sec
        rts
load_done:
        clc
        rts


; mouse_off: a mouse card in any slot, found by the AppleMouse ID bytes
; ($Cn05 $38, $Cn07 $18, $Cn0B $01, $Cn0C $20, $CnFB $D6), is set to mode
; 0 by its firmware's SETMOUSE (none of its interrupts), then its
; SERVEMOUSE clears an interrupt it may have pending: the timer's handler
; would never acknowledge it. Interrupts masked.
mouse_off:
        ldx     #7
@slot:  txa
        ora     #$C0
        sta     src+1
        stz     src
        ldy     #4
@id:    phy
        lda     mouse_at,y
        tay
        lda     (src),y
        ply
        cmp     mouse_id,y
        bne     @next
        dey
        bpl     @id
        phx
        lda     #0                      ; mode 0: off
        ldy     #MOUSE_SET
        jsr     mouse_call
        ldy     #MOUSE_SERVE
        jsr     mouse_call
        plx
@next:  dex
        bne     @slot
        rts

; mouse_call: the firmware routine whose entry is the byte at $Cn00 + Y
; (src = $Cn00), A its argument, called as the firmware asks: X = $Cn,
; Y = $n0
mouse_call:
        pha
        lda     (src),y
        sta     mvec
        lda     src+1
        sta     mvec+1
        tax
        asl     a
        asl     a
        asl     a
        asl     a
        tay
        pla
        jmp     (mvec)

; timer_check: carry clear when slot 4 has VIA-B's timer 1: its latch
; holds what is written ($55AA, then $AA55)
timer_check:
        ldx     #$55
        jsr     @try
        bcs     @done
        ldx     #$AA
@try:   stx     VIA_B_T1LL
        txa
        eor     #$FF
        sta     VIA_B_T1LH
        cpx     VIA_B_T1LL
        bne     @none
        cmp     VIA_B_T1LH
        bne     @none
        clc
@done:  rts
@none:  sec
        rts

; timer_on: VIA-B's timer 1 free-running, a frame of the detected standard
; a period, its interrupt on (interrupts masked). A 6522 in free-run mode
; times out every latch + 2 cycles of the bus: latch 20,278 on PAL and
; 17,028 on NTSC, the 20,280 and 17,030 cycles of a frame, the VBL's rate.
timer_on:
        lda     #ACR_FREE
        sta     VIA_B_ACR
        ldx     #<T1_PAL
        ldy     #>T1_PAL
        bit     ntsc
        bpl     :+
        ldx     #<T1_NTSC
        ldy     #>T1_NTSC
:       stx     VIA_B_T1CL              ; the low latch
        sty     VIA_B_T1CH              ; the high latch: the count starts
        lda     #$80 | IFR_T1
        sta     VIA_B_IER
        rts

; timer_off: VIA-B's timer 1 stopped (interrupts masked). Its interrupt
; off, one-shot mode, then a one-shot of 0, whose flag comes 2 cycles on
; and is the last; the latch back to $FFFF and every flag clear. The
; counter still counts, as a 6522's does, but flags nothing until the
; next program writes T1C-H.
timer_off:
        lda     #$7F
        sta     VIA_B_IER
        stz     VIA_B_ACR
        stz     VIA_B_T1CL
        stz     VIA_B_T1CH
:       bit     VIA_B_IFR               ; V: the flag, IFR bit 6
        bvc     :-
        lda     #$FF
        sta     VIA_B_T1LL
        sta     VIA_B_T1LH
        lda     #$7F
        sta     VIA_B_IFR
        rts

; vbl_start: to the start of a vertical blanking ($C019 bit 7 goes low)
vbl_start:
:       bit     RDVBLBAR                ; in a blanking: to its end
        bpl     :-
:       bit     RDVBLBAR                ; the display: to the blanking
        bmi     :-
        rts

; ---------------------------------------------------------------------------
        .segment "MUSDATA"

; the page-1 copy: X pages from (src) in aux memory (RAMRD on) to (dst).
; It runs at $0100: page 1 stays main memory whatever RAMRD says, where
; code in main $0200-$BFFF would be fetched from aux. Only relative
; branches, so it runs wherever it is copied.
p1_code:
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
        rts
p1_end:
        .assert p1_end - p1_code <= $40, error, "the page-1 copy"

mouse_at:
        .byte   $05, $07, $0B, $0C, $FB ; the AppleMouse ID bytes' places
mouse_id:
        .byte   $38, $18, $01, $20, $D6 ;   and values

op_parms:
        .byte   3
op_path:
        .word   0
        .word   IOBUF
op_ref: .byte   0
rd_parms:
        .byte   4
rd_ref: .byte   0
        .word   SONG_ADDR
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

row_lo: .repeat 24, R
        .byte   <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
row_hi: .repeat 24, R
        .byte   >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
pow_lo: .byte   <1, <10, <100, <1000, <10000
pow_hi: .byte   >1, >10, >100, >1000, >10000

        SONG_TABLES

s_title:
        .byte   "DOOM: THE MUSIC ON THE PHASOR", 0
s_pal:  .byte   "PAL //E", 0
s_ntsc: .byte   "NTSC //E", 0
s_t1:   .byte   ": TIMER 1 COUNTS ", 0
s_cycles:
        .byte   " A VBL", 0
s_card: .byte   "PHASOR IN NATIVE MODE, 4 AY CHIPS", 0
s_loading:
        .byte   "LOADING ", 0
s_playing:
        .byte   "PLAYING ", 0
s_stopped:
        .byte   "STOPPED ", 0
s_of:   .byte   "OF ", 0
s_loop: .byte   "LOOP", 0
s_all:  .byte   "ALL", 0
s_keys: .byte   "A-M PLAY  N NEXT  P PREVIOUS  SPACE STOP", $0D
        .byte   "R LOOP OR ALL  V PAL OR NTSC  Q QUIT", $0D
        .byte   "T AY TIMING TEST", 0
s_nomusic:
        .byte   "NO MUSIC. THE CARD IN SLOT 4 DID NOT", $0D
        .byte   "SWITCH TO THE PHASOR'S NATIVE MODE: IT", $0D
        .byte   "HAS 2 AY CHIPS, AND THE MUSIC NEEDS 4.", $0D
        .byte   "IT IS A MOCKINGBOARD, OR THE PHASOR", $0D
        .byte   "WITH ITS MOCKINGBOARD ONLY OPTION ON.", $0D
        .byte   "IN THE APPLETINI MENU: PHASOR IN SLOT 4", $0D
        .byte   "ON, MOCKINGBOARD ONLY OFF; THEN REBOOT.", $0D
        .byte   $0D
        .byte   "T AY TIMING TEST  V PAL OR NTSC  Q QUIT", 0
s_notimer:
        .byte   "NO 6522 TIMER IN SLOT 4. THE MUSIC'S", $0D
        .byte   "CLOCK IS TIMER 1 OF THE PHASOR'S VIA-B:", $0D
        .byte   "IN THE APPLETINI MENU, TURN ON THE", $0D
        .byte   "PHASOR IN SLOT 4.", 0
s_noaux:
        .byte   "NO AUX MEMORY. THE MUSIC NEEDS AN", $0D
        .byte   "ENHANCED //E WITH 128K: ITS 64K", $0D
        .byte   "AUXILIARY MEMORY CARD.", 0
s_prodos:
        .byte   "PRODOS ERROR LOADING THE SONG: ", 0
s_size: .byte   "A SONG FILE HAS THE WRONG LENGTH.", 0
s_refused:
        .byte   "THE PLAYER REFUSED THE SONG: ERROR ", 0
s_anykey:
        .byte   "PRESS A KEY TO QUIT.", 0
