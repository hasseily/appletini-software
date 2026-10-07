; ProDOS SYS entry, Phasor native mode in slot 4: Appletini F1.2.5+ or a real card.
; The entire bounded song is loaded before the timer starts. Foreground
; polling leaves ProDOS's language-card image and vectors undisturbed.
        .setcpu "65C02"
        .import phs_init, phs_start, phs_stop, phs_tick
        .import phs_reader, phs_playing, phs_error, phs_tick_hz
        .import phs_memory_read, phs_mem_end
        .importzp phs_mem_pos
        .export start, load_song, start_song, poll, timer_on, timer_off
        .export region, loaded, error, song_length, status, open_path
        .export quit, mli_call
        .ifdef SHOWCASE
        .import __RELOAD_LOAD__, __RELOAD_RUN__, __RELOAD_SIZE__
        .export reload_basic
        .endif

MLI = $BF00
SONG = $3000
MAX_SONG = $8800             ; $3000..$B7FF; never overwrite ProDOS
IOBUF = $1C00               ; 1K aligned, above BSS and below code
T1CL = $C484
T1CH = $C485
T1LL = $C486
T1LH = $C487
ACR = $C48B
IFR = $C48D
IER = $C48E
NTSC_LATCH = 10203          ; 1,020,484 / 100 rounded, minus 2
PAL_LATCH = 10154           ; 1,015,625 / 100 rounded, minus 2
        .ifndef DEFAULT_REGION
DEFAULT_REGION = 1          ; PAL; -D DEFAULT_REGION=0 starts in NTSC
        .endif
        .assert DEFAULT_REGION = 0 .or DEFAULT_REGION = 1, error, "region must be NTSC (0) or PAL (1)"

        .segment "ZEROPAGE"
text_ptr: .res 2
screen_ptr: .res 2
        .segment "BSS"
region: .res 1              ; 0 NTSC, 1 PAL
loaded: .res 1
error: .res 1               ; MLI code or $F0 size/$F1 rate/$F2 late/$F3 card
song_length: .res 2
status: .res 1              ; 0 stopped, 1 playing, 2 complete, 3 error

        .segment "CODE"
start:
        sei
        cld
        ldx #$FF
        txs
        sta $C000           ; 80STORE off
        sta $C002           ; main reads
        sta $C004           ; main writes
        sta $C008           ; main zero page
        sta $C006           ; slot ROMs visible
        sta $C00C           ; 40 columns
        sta $C00E           ; normal character set
        sta $C051           ; text
        sta $C052           ; mixed off
        sta $C054           ; page 1
        lda #1
        sta $C029           ; Appletini SHR off
        .if DEFAULT_REGION
        lda #1
        sta region
        .else
        stz region
        .endif
        stz loaded
        stz error
        stz status
        jsr draw_screen
        jsr phs_init
        ; Verify writable VIA timer latches before starting its clock.
        lda #$5A
        sta T1LL
        lda #$A5
        sta T1LH
        cmp T1LH
        bne no_card
        lda T1LL
        cmp #$5A
        bne no_card
        jsr load_song
        bcs load_failed
        jsr start_song
        jmp poll
no_card:
        lda #$F3
        sta error
load_failed:
        jsr show_error
poll:
        lda phs_playing
        beq keys
        lda IFR
        and #$40
        beq keys
        sta IFR             ; acknowledge without reading T1CL
        jsr phs_tick
        bcs playback_failed
        lda phs_playing
        beq completed
        lda IFR             ; more than one period in processing: fail closed
        and #$40
        beq keys
        lda #$F2
        sta error
        bra playback_failed
completed:
        jsr timer_off
        lda #2
        sta status
        lda #<s_complete
        ldx #>s_complete
        jsr status_text
        bra keys
playback_failed:
        lda error
        bne :+
        lda phs_error
        sta error
:       jsr phs_stop
        jsr timer_off
        jsr show_error
keys:
        lda $C000
        bpl poll
        sta $C010
        and #$7F
        cmp #'a'
        bcc :+
        cmp #'z'+1
        bcs :+
        and #$DF
:       cmp #'Q'
        beq quit
        cmp #$1B
        beq quit
        cmp #' '
        beq stop
        cmp #'R'
        beq replay
        cmp #'N'
        beq ntsc
        cmp #'P'
        bne poll
        lda #1
        bra set_region
ntsc:   lda #0
set_region:
        sta region
        jsr load_song
        bcc replay
        jmp load_failed
replay: jsr start_song
        jmp poll
stop:   jsr phs_stop
        jsr timer_off
        stz status
        lda #<s_stopped
        ldx #>s_stopped
        jsr status_text
        jmp poll
quit:
        jsr phs_stop
        jsr timer_off
        bit $C0C8           ; restore Mockingboard mode for next program
        .ifdef SHOWCASE
        ; BASIC.SYSTEM replaces $2000 upward, including this SYS program.
        ; Relocate the entire return routine AND its MLI parameter blocks.
        lda #<__RELOAD_LOAD__
        sta text_ptr
        lda #>__RELOAD_LOAD__
        sta text_ptr+1
        lda #<__RELOAD_RUN__
        sta screen_ptr
        lda #>__RELOAD_RUN__
        sta screen_ptr+1
        ldy #0
copy_reload:
        lda (text_ptr),y
        sta (screen_ptr),y
        inc text_ptr
        bne :+
        inc text_ptr+1
:       inc screen_ptr
        bne :+
        inc screen_ptr+1
:       lda text_ptr
        cmp #<(__RELOAD_LOAD__ + __RELOAD_SIZE__)
        bne copy_reload
        lda text_ptr+1
        cmp #>(__RELOAD_LOAD__ + __RELOAD_SIZE__)
        bne copy_reload
        jmp reload_basic
        .else
        jsr MLI
        .byte $65
        .word quit_params
        jmp quit            ; QUIT normally never returns
        .endif

; The only disk accesses. GET_EOF prevents silently accepting an oversized
; file; READ must return the complete file, and CLOSE is always attempted.
load_song:
        jsr phs_stop
        jsr timer_off
        stz loaded
        stz error
        lda #<s_loading
        ldx #>s_loading
        jsr status_text
        lda #<path_ntsc
        ldx #>path_ntsc
        ldy region
        beq :+
        lda #<path_pal
        ldx #>path_pal
:       sta open_path
        stx open_path+1
        lda #$C8
        ldx #<open_params
        ldy #>open_params
        jsr mli_do
        bcc :+
        sta error
        sec
        rts
:       lda open_ref
        sta eof_ref
        sta read_ref
        sta close_ref
        lda #$D1
        ldx #<eof_params
        ldy #>eof_params
        jsr mli_do
        bcs file_error
        lda eof_length+2
        bne bad_size
        lda eof_length+1
        cmp #>MAX_SONG
        bcc small_enough
        bne bad_size
        lda eof_length
        bne bad_size
small_enough:
        lda eof_length+1
        bne size_ok
        lda eof_length
        cmp #16
        bcc bad_size
size_ok:
        lda eof_length
        sta read_count
        sta song_length
        lda eof_length+1
        sta read_count+1
        sta song_length+1
        lda #$CA
        ldx #<read_params
        ldy #>read_params
        jsr mli_do
        bcs file_error
        lda read_got
        cmp song_length
        bne bad_size
        lda read_got+1
        cmp song_length+1
        bne bad_size
        bra close_file
bad_size:
        lda #$F0
file_error:
        sta error
close_file:
        lda #$CC
        ldx #<close_params
        ldy #>close_params
        jsr mli_do
        bcc :+
        ldx error
        bne :+
        sta error
:       lda error
        beq :+
        sec
        rts
:       inc loaded
        clc
        rts

start_song:
        jsr timer_off
        jsr phs_stop
        lda loaded
        beq cannot_start
        stz error
        ; Reject incompatible timing before phs_start emits time-zero sound.
        lda SONG+4
        cmp #100
        bne wrong_rate
        lda SONG+5
        bne wrong_rate
        lda #<SONG
        sta phs_mem_pos
        lda #>SONG
        sta phs_mem_pos+1
        clc
        lda song_length
        adc #<SONG
        sta phs_mem_end
        lda song_length+1
        adc #>SONG
        sta phs_mem_end+1
        lda #<phs_memory_read
        sta phs_reader
        lda #>phs_memory_read
        sta phs_reader+1
        jsr phs_start
        bcs start_error
        lda #1
        sta status
        lda #<s_ntsc
        ldx #>s_ntsc
        ldy region
        beq :+
        lda #<s_pal
        ldx #>s_pal
:       jsr status_text
        jsr timer_on
        clc
        rts
wrong_rate:
        lda #$F1
        sta error
        bra cannot_start
start_error:
        lda phs_error
        sta error
cannot_start:
        jsr show_error
        sec
        rts

timer_on:
        lda #$40
        sta ACR
        ldx #<NTSC_LATCH
        ldy #>NTSC_LATCH
        lda region
        beq :+
        ldx #<PAL_LATCH
        ldy #>PAL_LATCH
:       stx T1CL
        sty T1CH
        rts
timer_off:
        lda #$7F
        sta IER
        stz ACR
        lda #$40
        sta IFR
        rts

mli_do:
        sta mli_command
        stx mli_params
        sty mli_params+1
mli_call:
        jsr MLI
mli_command: .byte 0
mli_params: .word 0
        sei                 ; MLI may have changed interrupt state
        cld
        rts

draw_screen:
        lda #$A0
        ldx #0
:       sta $400,x
        sta $500,x
        sta $600,x
        sta $700,x
        inx
        bne :-
        lda #<s_title
        ldx #>s_title
        ldy #1
        jsr line_text
        lda #<s_subtitle
        ldx #>s_subtitle
        ldy #3
        jsr line_text
        lda #<s_hardware
        ldx #>s_hardware
        ldy #5
        jsr line_text
        lda #<s_keys
        ldx #>s_keys
        ldy #9
        jsr line_text
        lda #<s_region
        ldx #>s_region
        ldy #11
        jsr line_text
        lda #<s_voice
        ldx #>s_voice
        ldy #13
        jmp line_text
show_error:
        lda #3
        sta status
        lda #<s_error
        ldx #>s_error
        jsr status_text
        lda error
        pha
        lsr
        lsr
        lsr
        lsr
        tax
        lda hex,x
        ora #$80
        sta $798+7           ; row 23, offset 7
        pla
        and #15
        tax
        lda hex,x
        ora #$80
        sta $798+8
        rts
status_text:
        ldy #23
line_text:
        sta text_ptr
        stx text_ptr+1
        lda row_lo,y
        sta screen_ptr
        lda row_hi,y
        sta screen_ptr+1
        ldy #39
        lda #$A0
:       sta (screen_ptr),y
        dey
        bpl :-
        ldy #0
:       lda (text_ptr),y
        beq :+
        ora #$80
        sta (screen_ptr),y
        iny
        cpy #40
        bne :-
:       rts

        .segment "RODATA"
        .ifdef SHOWCASE
path_ntsc: .byte path_ntsc_end-path_ntsc-1, "/MSDOS/MUSIC/SUN.NTSC"
path_ntsc_end:
path_pal: .byte path_pal_end-path_pal-1, "/MSDOS/MUSIC/SUN.PAL"
path_pal_end:
        .else
path_ntsc: .byte path_ntsc_end-path_ntsc-1, "/RISING.SUN/SUN.NTSC"
path_ntsc_end:
path_pal: .byte path_pal_end-path_pal-1, "/RISING.SUN/SUN.PAL"
path_pal_end:
        .endif
open_params: .byte 3
open_path: .word path_ntsc
        .word IOBUF
open_ref: .byte 0
eof_params: .byte 2
eof_ref: .byte 0
eof_length: .res 3, 0
read_params: .byte 4
read_ref: .byte 0
        .word SONG
read_count: .word 0
read_got: .word 0
close_params: .byte 1
close_ref: .byte 0
quit_params: .byte 4, 0
        .word 0
        .byte 0
        .word 0
row_lo: .repeat 24, R
        .byte <($400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
row_hi: .repeat 24, R
        .byte >($400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
hex: .byte "0123456789ABCDEF"
s_title: .byte "HOUSE OF THE RISING SUN",0
s_subtitle: .byte "A TRADITIONAL SONG FOR PHASOR",0
s_hardware: .byte "PHASOR SLOT 4 / APPLETINI F1.2.5+",0
        .ifdef SHOWCASE
s_keys: .byte "R REPLAY   SPACE STOP   Q MENU",0
        .else
s_keys: .byte "R REPLAY   SPACE STOP   Q QUIT",0
        .endif
s_region: .byte "N NTSC     P PAL (RELOADS SONG)",0
s_voice: .byte "FOUR AY CHIPS + TWO SSI-263 VOICES",0
s_loading: .byte "LOADING...",0
s_ntsc: .byte "PLAYING: NTSC / 100 HZ",0
s_pal: .byte "PLAYING: PAL / 100 HZ",0
s_stopped: .byte "STOPPED. PRESS R TO REPLAY.",0
s_complete: .byte "COMPLETE. PRESS R TO REPLAY.",0
s_error: .byte "ERROR $00. N/P RETRY; Q QUIT.",0

        .ifdef SHOWCASE
; Appletini_Demos contains the known 10,240-byte BASIC.SYSTEM. Check its
; complete length before replacing ourselves, then check READ and CLOSE.
; No reference here may point back into the overwritten SYS code or data.
BASIC_SIZE = $2800
        .segment "RELOAD"
reload_basic:
        jsr MLI
        .byte $C8
        .word basic_open
        bcs return_fallback
        lda basic_ref
        sta basic_eof_ref
        sta basic_read_ref
        sta basic_close_ref
        jsr MLI
        .byte $D1
        .word basic_eof
        bcs return_close_error
        lda basic_length
        cmp #<BASIC_SIZE
        bne return_close_error
        lda basic_length+1
        cmp #>BASIC_SIZE
        bne return_close_error
        lda basic_length+2
        bne return_close_error
        jsr MLI
        .byte $CA
        .word basic_read
        bcs return_close_error
        lda basic_got
        cmp #<BASIC_SIZE
        bne return_close_error
        lda basic_got+1
        cmp #>BASIC_SIZE
        bne return_close_error
        jsr MLI
        .byte $CC
        .word basic_close
        bcs return_fallback
        ; A BASIC dash launch can leave the MLI prefix empty. STARTUP and
        ; its relative file references must resolve against the root.
        jsr MLI
        .byte $C6
        .word basic_prefix
        bcs return_fallback
        jmp $2000
return_close_error:
        jsr MLI
        .byte $CC
        .word basic_close
return_fallback:
        jsr MLI
        .byte $65
        .word basic_quit
:       jmp :-              ; don't execute a partly loaded BASIC on error

basic_open: .byte 3
        .word basic_path, IOBUF
basic_ref: .byte 0
basic_eof: .byte 2
basic_eof_ref: .byte 0
basic_length: .res 3, 0
basic_read: .byte 4
basic_read_ref: .byte 0
        .word $2000, BASIC_SIZE
basic_got: .word 0
basic_close: .byte 1
basic_close_ref: .byte 0
basic_prefix: .byte 1
        .word root_path
basic_quit: .byte 4, 0
        .word 0
        .byte 0
        .word 0
basic_path: .byte basic_path_end-basic_path-1, "/MSDOS/BASIC.SYSTEM"
basic_path_end:
root_path: .byte root_path_end-root_path-1, "/MSDOS"
root_path_end:
        .endif
