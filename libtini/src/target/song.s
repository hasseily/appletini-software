; Pattern song player for ti_song_start; docs/AUDIO.md describes the bytes
; that tools/music.py writes. ti_audio_update calls it in the foreground and
; it never re-enters. The checks run once from CODE; the rest is in
; LOWCODE, which the full game runs from low MAIN.
.setcpu "65C02"
.include "zeropage.inc"
.macpack longbranch
.export _ti_song_start
.import pusha, pushax, incsp4
.import _ti_near_valid, _ti_audio_voices, _ti_audio_music_mask, _ti_audio_ticks
.import _ti_audio_tone, _ti_music_stop
.import _ti_audio_player, _ti_audio_music_volume, _ti_audio_dirty
.import _ti_audio_music_voices, _ti_audio_music_end

TI_OK       = 0
TI_ARGUMENT = 1
TI_STATE    = 2
TI_RANGE    = 3
REST        = $60
HOLD        = $61
LAST        = $FF       ; ends a pattern
TRACKS      = 12

.segment "BSS"
; A new song and its checks. The playing song keeps its state until a new
; one passes them; then the first block is copied over the second.
new:
head:       .res 7      ; row ticks (8.8), tracks, positions, loop, notes, patterns
new_repeat: .res 1
arg_size:   .res 2      ; the C arguments, size then song
arg_song:   .res 2
new_periods: .res 2
new_offsets: .res 2
NEW         = * - new
order_at:   .res 2
header:     .res 2      ; the address after the tables
limit:      .res 2      ; the address after the song
rowed:      .res 1
mask:       .res 2
instrument: .res 1
voice_no:   .res 1
; The playing song.
live:
step:       .res 2
            .res 1
positions:  .res 1
loop_at:    .res 1
            .res 2
repeat:     .res 1
            .res 2
song:       .res 2
periods:    .res 2
offsets:    .res 2
tracks:     .res 1      ; tracks played
fraction:   .res 1
now:        .res 2
envelope_tick: .res 1
steps:      .res 1
period:     .res 2
; Per track.
voice:      .res TRACKS
position:   .res TRACKS
wait:       .res TRACKS
rows:       .res TRACKS
attack:     .res TRACKS
decay:      .res TRACKS
floor:      .res TRACKS
count:      .res TRACKS
at_lo:      .res TRACKS
at_hi:      .res TRACKS
order_lo:   .res TRACKS
order_hi:   .res TRACKS

.segment "CODE"
; ti_error ti_song_start(const uint8_t *song, uint16_t size, uint8_t loop)
_ti_song_start:
        sta new_repeat
        ldy #3
:       lda (c_sp),y
        sta arg_size,y
        dey
        bpl :-
        jsr incsp4
        jsr _ti_audio_voices
        cmp #0
        bne :+
        lda #TI_STATE
        ldx #0
        rts
        ; The near check also rejects NULL.
:       lda arg_size+1
        bne :+
        lda arg_size
        cmp #8
        bcc argument
:       lda arg_song
        ldx arg_song+1
        jsr pushax
        lda arg_size
        ldx arg_size+1
        jsr pushax
        lda #0
        jsr _ti_near_valid
        cmp #0
        beq argument
        jsr _ti_audio_music_mask
        sta mask
        stx mask+1
        ora mask+1
        beq range
        lda arg_song
        sta ptr1
        lda arg_song+1
        sta ptr1+1
        ldy #6
:       lda (ptr1),y
        sta head,y
        dey
        bpl :-
        ; A row lasts 1..100 ticks: 256..25600 in 8.8.
        lda head+1
        beq range
        cmp #$64
        bcc :+
        bne range
        lda head
        bne range
:       lda head+2
        beq range
        cmp #TRACKS+1
        bcs range
        lda head+3
        beq range
        lda head+4
        cmp head+3
        bcs range
        lda head+5
        beq range
        cmp #REST+1
        bcs range
        lda head+6
        bne layout
argument:
        lda #TI_ARGUMENT
        ldx #0
        rts
range:  lda #TI_RANGE
        ldx #0
        rts
        ; Instruments at 7, then periods, pattern offsets, orders and
        ; patterns.
layout: lda head+2
        asl a
        adc head+2
        adc #7
        sta tmp1
        ldx #0
        jsr at_song
        sta new_periods
        stx new_periods+1
        lda head+5
        asl a
        adc tmp1
        sta tmp2
        ldx #0
        jsr at_song
        sta new_offsets
        stx new_offsets+1
        lda head+6
        asl a
        sta order_at
        lda #0
        rol a
        sta order_at+1
        clc
        lda order_at
        adc new_offsets
        sta order_at
        lda order_at+1
        adc new_offsets+1
        sta order_at+1
        ; The orders hold tracks * positions bytes.
        lda #0
        tax
        ldy head+2
:       clc
        adc head+3
        bcc :+
        inx
:       dey
        bne :--
        clc
        adc order_at
        sta header
        txa
        adc order_at+1
        sta header+1
        lda arg_size
        ldx arg_size+1
        jsr at_song
        sta limit
        stx limit+1
        cmp header
        txa
        sbc header+1
        jcc range
        ; Volume, decay and floor are 0..15; periods 0..2047.
        ldy #7
:       lda (ptr1),y
        cmp #16
        jcs range
        iny
        cpy tmp1
        bcc :-
        iny
:       lda (ptr1),y
        cmp #8
        jcs range
        iny
        iny
        cpy tmp2
        bcc :-
        ; Every order names a pattern.
        lda order_at
        sta ptr2
        lda order_at+1
        sta ptr2+1
:       lda (ptr2)
        cmp head+6
        jcs range
        inc ptr2
        bne :+
        inc ptr2+1
:       lda ptr2
        cmp header
        lda ptr2+1
        sbc header+1
        bcc :--
        ; Every pattern starts after the tables and ends inside the song
        ; after at least one row, so reading a row crosses at most one end.
        lda new_offsets
        sta ptr3
        lda new_offsets+1
        sta ptr3+1
        lda head+6
        sta tmp3
@pattern:
        ldy #1
        lda (ptr3),y
        tax
        lda (ptr3)
        jsr at_song
        sta ptr2
        stx ptr2+1
        cmp header
        txa
        sbc header+1
        jcc range
        stz rowed
@byte:  lda ptr2
        cmp limit
        lda ptr2+1
        sbc limit+1
        jcs range
        lda (ptr2)
        cmp #LAST
        beq @last
        cmp head+5
        bcc @row
        cmp #REST
        beq @row
        cmp #HOLD
        beq @row
        cmp #$80
        jcc range
        cmp #$F0
        jcs range
        bra @next
@row:   lda #1
        sta rowed
@next:  inc ptr2
        bne @byte
        inc ptr2+1
        bra @byte
@last:  lda rowed
        jeq range
        clc
        lda ptr3
        adc #2
        sta ptr3
        bcc :+
        inc ptr3+1
:       dec tmp3
        bne @pattern
        jmp accept

; A/X = the new song's address plus offset A/X.
at_song:
        clc
        adc arg_song
        pha
        txa
        adc arg_song+1
        tax
        pla
        rts

.segment "LOWCODE"
; The song passed: stop the old score, then track i plays on the i-th
; reserved voice. Tracks beyond the reserved voices stay silent, so a
; smaller card plays the first tracks.
accept: jsr _ti_music_stop
        ldx #NEW-1
:       lda new,x
        sta live,x
        dex
        bpl :-
        stz fraction
        lda #7
        ldx #0
        jsr at_song
        sta ptr3
        stx ptr3+1
        stz instrument
        stz voice_no
        ldx #0
        ; Sixteen voice bits feed the used mask from the top, so each one
        ; lands in place.
@map:   lsr mask+1
        ror mask
        bcc @feed
        cpx head+2
        bcs @full
        lda voice_no
        sta voice,x
        lda #1
        sta wait,x
        sta rows,x
        stz position,x
        ldy instrument
        lda (ptr3),y
        sta attack,x
        iny
        lda (ptr3),y
        sta decay,x
        iny
        lda (ptr3),y
        sta floor,x
        iny
        sty instrument
        lda order_at
        sta order_lo,x
        sta ptr2
        lda order_at+1
        sta order_hi,x
        sta ptr2+1
        lda (ptr2)
        jsr pattern
        lda ptr1
        sta at_lo,x
        lda ptr1+1
        sta at_hi,x
        clc
        lda order_at
        adc head+3
        sta order_at
        bcc :+
        inc order_at+1
:       inx
        sec
        bra @feed
@full:  clc
@feed:  ror _ti_audio_music_voices+1
        ror _ti_audio_music_voices
        inc voice_no
        lda voice_no
        cmp #16
        bne @map
        stx tracks
        jsr _ti_audio_ticks
        sta _ti_audio_music_end
        sta envelope_tick
        stx _ti_audio_music_end+1
        lda #<play
        sta _ti_audio_player
        lda #>play
        sta _ti_audio_player+1
        lda #TI_OK
        ldx #0
        rts

; ptr1 = the first byte of pattern A. Keeps X.
pattern:
        stz tmp1
        asl a
        rol tmp1
        adc offsets
        sta ptr2
        lda tmp1
        adc offsets+1
        sta ptr2+1
        ldy #1
        lda (ptr2),y
        tay
        lda (ptr2)
        clc
        adc song
        sta ptr1
        tya
        adc song+1
        sta ptr1+1
        rts

; uint8_t play(uint32_t now): 1 when more than 32 rows were due. Scores
; stop on any gap over 100 ticks, so the low sixteen bits order the times
; and the player keeps only those of the shared deadline.
play:   sta now
        stx now+1
        ; Each decay step lowers a note one level until its floor, before
        ; new rows start their notes at full volume. A late update catches
        ; up at most 16 ticks.
        sec
        sbc envelope_tick
        cmp #17
        bcc :+
        lda #16
:       sta steps
        lda now
        sta envelope_tick
        lda steps
        beq @rows
@tick:  ldx #0
@track: cpx tracks
        bcs @ticked
        lda decay,x
        beq @skip
        ldy voice,x
        lda _ti_audio_music_volume,y
        cmp floor,x
        beq @skip
        bcc @skip
        dec count,x
        bne @skip
        lda decay,x
        sta count,x
        lda _ti_audio_music_volume,y
        dec a
        sta _ti_audio_music_volume,y
@skip:  inx
        bra @track
@ticked:
        dec steps
        bne @tick
@rows:  stz steps
@due:   lda now
        cmp _ti_audio_music_end
        lda now+1
        sbc _ti_audio_music_end+1
        bmi @done
        lda steps
        cmp #32
        beq @late
        inc steps
        jsr row
        bcs @done
        ; The next row: whole ticks plus the carry of the fraction.
        clc
        lda fraction
        adc step
        sta fraction
        lda _ti_audio_music_end
        adc step+1
        sta _ti_audio_music_end
        bcc @due
        inc _ti_audio_music_end+1
        bra @due
@late:  lda #1
        ldx #0
        rts
@done:  lda #0
        tax
        rts

; One row: each track whose note has ended reads up to its next note, rest
; or hold. Carry set when an unrepeated song has ended and stopped.
row:    ldx #0
@track: cpx tracks
        bcc :+
        clc
        rts
:       dec wait,x
        jne @next
        lda at_lo,x
        sta ptr1
        lda at_hi,x
        sta ptr1+1
@read:  lda (ptr1)
        inc ptr1
        bne :+
        inc ptr1+1
:       cmp #REST
        bcc @note
        beq @rest
        cmp #HOLD
        beq @save
        cmp #LAST
        beq @last
        ; $80 rows-1, $C0 volume, $D0 decay, $E0 floor.
        tay
        and #15
        cpy #$C0
        bcs :+
        tya
        and #63
        inc a
        sta rows,x
        bra @read
:       cpy #$D0
        bcs :+
        sta attack,x
        bra @read
:       cpy #$E0
        bcs :+
        sta decay,x
        bra @read
:       sta floor,x
        bra @read
@last:  inc position,x
        lda position,x
        cmp positions
        bne @order
        lda repeat
        beq @stop
        lda loop_at
        sta position,x
@order: lda order_lo,x
        sta ptr2
        lda order_hi,x
        sta ptr2+1
        ldy position,x
        lda (ptr2),y
        jsr pattern
        bra @read
@stop:  jsr _ti_music_stop
        sec
        rts
@rest:  ldy voice,x
        lda #0
        sta _ti_audio_music_volume,y
        lda #1
        sta _ti_audio_dirty
@save:  jsr save
@next:  inx
        jmp @track
@note:  asl a
        tay
        lda periods
        sta ptr2
        lda periods+1
        sta ptr2+1
        lda (ptr2),y
        sta period
        iny
        lda (ptr2),y
        sta period+1
        ldy voice,x
        lda attack,x
        sta _ti_audio_music_volume,y
        lda decay,x
        sta count,x
        jsr save
        phx
        lda voice,x
        jsr pusha
        lda period
        ldx period+1
        jsr pushax
        plx
        phx
        lda attack,x
        jsr _ti_audio_tone
        plx
        bra @next
save:   lda ptr1
        sta at_lo,x
        lda ptr1+1
        sta at_hi,x
        lda rows,x
        sta wait,x
        rts
