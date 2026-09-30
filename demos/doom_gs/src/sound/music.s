; MUSIC.SYSTEM: the music disk of milestone S3 (docs/NATIVE.md 13, the
; sound track), for the owner to run on the card. tools/sound/musicdisk.py
; builds it and the disk.
;
; Boot, at $2000 under ProDOS, with interrupts masked:
;   1. the text screen (40 columns, page 1; SHR off);
;   2. the mouse card in slot 2 (its ID bytes): the music's clock is its
;      VBL interrupt; none, and the program says so and quits;
;   3. RamWorks: banks 1 to SAVE_BANK must be distinct memory;
;   4. snd_probe (probe.s): SND_MUSIC (the card switched to the Phasor's
;      native mode, 4 AY chips) or SND_NO_MUSIC, which the screen explains
;      (NATIVE.md 15.1, row 11: no 6-voice fallback);
;   5. with music, the 13 song files into RamWorks banks 1-13 at $1000
;      (the song files of tools/sound/README.md, "The song file");
;   6. ProDOS's language card is saved in bank SAVE_BANK, then the card
;      gets the S2 player where docs/MEMORY_MAP.md 4.2 puts it in the game
;      (src/sound/music.cfg): its vector at $FFFE is snd_vbl (irq.s);
;   7. snd_init, the mouse card's VBL interrupt on, CLI;
;   8. PAL or NTSC: VIA-A's timer 1 counts Apple bus cycles; over one VBL
;      it counts 20,280 on a PAL //e (312 lines of 65 cycles) and 17,030
;      on NTSC (262 lines); V switches by hand;
;   9. with music, the first song starts, looping.
;
; Then the main loop serves each VBL (mus_service, once a VBL): the keys,
; the next song when one ends in "play all" mode, snd_refill, the clock
; on the screen. Its wait (mus_idle) is the loop a2vm skips to the next
; VBL (--idle mus_idle:vbl:eq=vbl_count,seen).
;
; Keys: A-M play a song, SPACE stops, N (or right arrow) the next, P (or
; left arrow) the previous, R switches between each song looping and
; playing all the songs once in turn, T runs the AY timing test
; (aytime.s), V switches PAL and NTSC tables, Q (or ESC) quits: the chips
; are reset, ProDOS's card is put back, the Phasor goes back to
; Mockingboard mode, and ProDOS's QUIT runs.
;
; The interrupt runs only irq.s and the player: the zero page $D8-$FF, the
; stack, $E000-$FFFF, the mouse card and the Phasor (docs/MEMORY_MAP.md
; rule 2). This program's data is in main $1000-$1FFF and its zero page at
; $18; no CPU store of it reaches $0878-$087F or $4078-$407F (rule 8).

        .setcpu "65C02"
        .include "sound.inc"
        .include "songs.inc"

        .import snd_probe, snd_init, snd_start, snd_stop, snd_refill
        .import snd_song_bank, snd_song_addr, snd_song_flags, snd_song_matt
        .import snd_error, ended
        .importzp vbl_count
        .import ayt_run

        .export start, mus_idle, mus_service, mus_quit, mus_fatal, mus_stop
        .export mus_loaded, mus_playing
        .export put_at, put_char, put_str, put_spaces, clear_rows
        .export wait_vbl, draw_status, draw_songs, song_path
        .export vblcyc, errcode
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
MOUSE_ROM       = $C200
MODE_VBL        = $09           ; the mouse card on, its VBL interrupt on
ACK_ALL         = $03
VIA_A_T1CL      = $C414         ; VIA-A's timer 1 (in both card modes)
VIA_A_T1CH      = $C415
VIA_A_T1LL      = $C416

SONG_ADDR       = $1000         ; each song at $1000 of its bank, 1-NSONGS
SAVE_BANK       = NSONGS + 1    ; ProDOS's card while the player has it:
SAVE_ADDR       = $2000         ;   $2000-$4FFF $D000-$FFFF (bank 1),
                                ;   $5000-$5FFF $D000-$DFFF (bank 2)
RAMCHECK        = $0C00         ; the byte each bank's check writes
LC_IMAGE        = $4000         ; the card image in MUSIC.SYSTEM (music.cfg)
LC_RUN          = $E900
LC_PAGES        = $17           ; $E900-$FFFF
IOBUF           = $5C00         ; ProDOS's buffer for the open file
DATABUF         = $6000         ; a song file, read whole
DATAMAX         = $5800         ;   $6000-$B7FF
P1COPY          = $0100         ; the page-1 copy (p1_code)
GAP             = 50            ; VBLs from a song's end to the next ("all")
PAL_NTSC_CUT    = 18655         ; cycles a VBL: halfway, 17,030 to 20,280

ROW_TITLE       = 0
ROW_MACHINE     = 1
ROW_CARD        = 2
ROW_SONGS       = 4             ; 7 rows, two columns
ROW_STATUS      = 12
ROW_KEYS        = 14
ROW_MSG         = 17            ; 17-23: the timing test, messages
COL_TIME        = 17

        .assert NSONGS <= 14, error, "the song list has 14 places"
        .assert SAVE_BANK < 127, error, "RamWorks has banks 1-126"
        .assert LC_IMAGE + LC_PAGES * $100 <= IOBUF, error, "the image"
        .assert DATABUF + DATAMAX <= $BF00, error, "the song buffer"
        .assert SONG_ADDR + MAX_SONG <= $C000, error, "a song past $BFFF"
        .assert MAX_SONG <= DATAMAX, error, "a song larger than the buffer"

; ---------------------------------------------------------------------------
        .segment "MUSZP": zeropage
ptr:    .res 2          ; the text position
src:    .res 2          ; copies
dst:    .res 2
seen:   .res 2          ; the VBL count the main loop has served
tmp:    .res 2
num:    .res 2          ; a number to print
song:   .res 1          ; the song shown, 0 to NSONGS-1
state:  .res 1          ; 1: a song plays
music:  .res 1          ; 1: snd_probe said SND_MUSIC
ntsc:   .res 1          ; SONG_NTSC or 0
rate:   .res 1          ; VBLs a second on the screen's clock: 50 or 60
through:.res 1          ; 1: play all, each song once in turn; 0: loop
endwait:.res 1          ; VBLs since the song ended ("all")
fsub:   .res 1          ; VBLs into the clock's second
secs:   .res 2          ; the song's time, in seconds
inv:    .res 1          ; text: $80 normal, 0 inverse
p1bank: .res 1          ; the bank the page-1 copy reads
index:  .res 1
lastv:  .res 1          ; the VBL count at the clock's last call
ticked: .res 1
lead:   .res 1          ; put_u16: a digit was printed

        .segment "MUSBSS"
scratch:.res 256        ; the RamWorks check reads a page here
vblcyc: .res 2          ; timer 1 cycles over one VBL, as measured
errcode:.res 1          ; the last error (ProDOS or snd_start's)
mus_loaded:
        .res 1          ; songs loaded
mus_playing:
        .res 1          ; the song playing +1, 0 for none (the harness)
length: .res 2          ; a file's length, as read
fatal_msg:
        .res 2

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
        stz     RAMWORKS
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
        ; the mouse card: the music's clock
        jsr     mouse_check
        bcc     :+
        lda     #<s_nomouse
        ldx     #>s_nomouse
        jmp     mus_fatal
:       jsr     mouse_off
        ; RamWorks
        jsr     ram_check
        bcc     :+
        lda     #<s_noram
        ldx     #>s_noram
        jmp     mus_fatal
:       ; the Phasor
        jsr     snd_probe
        bcs     :+
        inc     music
        jsr     load_songs
:       jsr     save_prodos
        jsr     install
        jsr     snd_init
        jsr     mouse_on
        cli
        jsr     detect_video
        jsr     draw_all
        sei
        lda     vbl_count
        sta     seen
        sta     lastv
        lda     vbl_count+1
        sta     seen+1
        cli
        lda     music
        beq     mus_service
        lda     #0
        jsr     play

; ---------------------------------------------------------------------------
; the main loop: one service a VBL
; ---------------------------------------------------------------------------
mus_service:
        sei
        lda     vbl_count
        sta     seen
        lda     vbl_count+1
        sta     seen+1
        cli
        jsr     keys
        jsr     through_check
        lda     music
        beq     :+
        jsr     snd_refill
:       jsr     clock
mus_idle:
        lda     vbl_count
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

; play: the song A (0 to NSONGS-1), from its start
play:   sta     song
        inc     a
        sta     snd_song_bank
        lda     #<SONG_ADDR
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

; through_check: in "play all" mode, the next song GAP VBLs after the end
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

; clock: the song's time on the screen, from the VBLs served
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

; show_error: the string A/X, then errcode in hex, on the last row
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

wait_vbl:
        lda     vbl_count
:       cmp     vbl_count
        beq     :-
        rts

; detect_video: timer 1 over one VBL; PAL (20,280 cycles) or NTSC (17,030)
detect_video:
        lda     #$FF
        sta     VIA_A_T1LL
        sta     VIA_A_T1CH              ; $FFFF, counting down
        jsr     wait_vbl
        lda     VIA_A_T1CL
        ldx     VIA_A_T1CH
        sta     tmp
        stx     tmp+1
        jsr     wait_vbl
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

; ram_check: carry clear when RamWorks banks 1 to SAVE_BANK are distinct
; memory. Each bank gets its number at RAMCHECK (highest first, so a bank
; that repeats a lower one is overwritten by it), then each is read back
; through the page-1 copy (the read with RAMRD on runs from page 1).
ram_check:
        ldx     #SAVE_BANK
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
        cmp     #SAVE_BANK + 1
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

; load_songs: each song file into its bank (song i in bank i + 1, $1000)
load_songs:
        ldx     #0
        ldy     #ROW_CARD
        jsr     put_at
        lda     #<s_loading
        ldx     #>s_loading
        jsr     put_str
        stz     index
@song:  ldx     #8                      ; the song's name, as it loads
        ldy     #ROW_CARD
        jsr     put_at
        lda     index
        jsr     put_label
        lda     index                   ; its ProDOS path: 16 bytes a song
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
        ldx     index                   ; the length the tool wrote
        lda     rd_got
        sta     length
        cmp     song_size_lo,x
        bne     @size
        lda     rd_got+1
        sta     length+1
        cmp     song_size_hi,x
        bne     @size
        lda     index                   ; into bank index + 1
        inc     a
        sta     RAMWORKS
        sta     RAMWRT_ON
        lda     #<DATABUF
        sta     src
        lda     #>DATABUF
        sta     src+1
        lda     #<SONG_ADDR
        sta     dst
        lda     #>SONG_ADDR
        sta     dst+1
        ldx     length+1
        inx                             ; whole pages (the buffer's tail
        jsr     copy_pages              ;   too: at most DATAMAX)
        sta     RAMWRT_OFF
        stz     RAMWORKS
        inc     mus_loaded
        inc     index
        lda     index
        cmp     #NSONGS
        bcs     :+
        jmp     @song
:       rts
@prodos:
        sta     errcode
        lda     #<s_prodos
        ldx     #>s_prodos
        jmp     mus_fatal_code
@size:  lda     #<s_size
        ldx     #>s_size
        jmp     mus_fatal

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

; install: the player's image into the card ($E900-$FFFF); $D000 bank 1
; stays selected (docs/MEMORY_MAP.md rule 1)
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

; mus_quit: the chips reset, ProDOS back, ProDOS's QUIT
mus_quit:
        sei
        jsr     mouse_off
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
        stz     errcode
mus_fatal_code:
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
        .segment "MUSDATA"

; the page-1 copy: X pages from (src) in RamWorks bank p1bank (RAMRD on) to
; (dst). It runs at $0100: page 1 stays main memory whatever RAMRD says,
; where code in main $0200-$BFFF would be fetched from the bank. Only
; relative branches, so it runs wherever it is copied.
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
        .byte   "DOOM GS: THE MUSIC ON THE PHASOR", 0
s_pal:  .byte   "PAL //E", 0
s_ntsc: .byte   "NTSC //E", 0
s_t1:   .byte   ": TIMER 1 COUNTS ", 0
s_cycles:
        .byte   " A VBL", 0
s_card: .byte   "PHASOR IN NATIVE MODE, 4 AY CHIPS", 0
s_loading:
        .byte   "LOADING", 0
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
s_nomouse:
        .byte   "NO MOUSE CARD IN SLOT 2. ITS VBL", $0D
        .byte   "INTERRUPT IS THE MUSIC'S CLOCK: TURN ON", $0D
        .byte   "THE APPLETINI'S MOUSE CARD IN SLOT 2.", 0
s_noram:
        .byte   "THE SONGS NEED RAMWORKS BANKS 1-14:", $0D
        .byte   "TURN ON THE APPLETINI'S RAMWORKS.", 0
s_prodos:
        .byte   "PRODOS ERROR LOADING A SONG: $", 0
s_size: .byte   "A SONG FILE HAS THE WRONG LENGTH.", 0
s_refused:
        .byte   "THE PLAYER REFUSED THE SONG: ERROR $", 0
s_anykey:
        .byte   "PRESS A KEY TO QUIT.", 0
