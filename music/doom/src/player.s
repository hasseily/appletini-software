; The music player for the Phasor. Original code: no id Software code was
; used.
;
; Where it runs:
;
;   snd_tick     in VIA-B's timer interrupt (irq.s calls it after the
;                acknowledge), once a frame, 50 or 60 times a second: the
;                ticks due, the levels, then one burst of the registers
;                that changed.
;                It touches only the zero page, the stack, the language
;                card and the Phasor, and never a mapping switch.
;   snd_start    in the main loop: reads a song file in main memory, keeps
;                its tables in the card, fills the ring, writes the first
;                burst.
;   snd_refill   in the main loop, as often as it likes (once a frame is
;                enough): when half the ring is free, copies 512 bytes of
;                the stream from the song file into it.
;   snd_stop     in the main loop: the next interrupt silences the music
;                voices and the player stops.
;   snd_init     once: the VIAs, the chips' reset, the card mode.
;
; The stream reaches the player through a ring of RING_SIZE bytes in the
; card, refilled a page at a time. When the bytes of
; the next command are not all in the ring (an underrun: the main loop did
; not refill), the player silences every music voice and holds its
; position; the commands go on when the bytes arrive.
;
; The voice layout is native12, the only one: 12 voices on the 4 AY chips
; of the card in native mode (there is no 6-voice fallback). tables.inc
; gives its voices, the registers the music owns and the period tables of
; native mode.
; PAL or NTSC is chosen at snd_start.

        .setcpu "65C02"
        .include "sound.inc"
        .include "tables.inc"

        .export snd_init, snd_start, snd_stop, snd_refill, snd_tick
        .export snd_song_addr, snd_song_flags, snd_song_matt
        .export snd_error, snd_playing
        ; the player's state, for a debugger (build/music.lbl)
        .export ring, want, shadow, wreg, wval, wn, period_pal, period_ntsc
        .export bend_magnitude, level_of_att, envtab, drumtab, owned_list
        .export phase, eatt_lo, eatt_hi, rpos, wpos_hi, exhausted, ended

; ---------------------------------------------------------------------------
; zero page
; ---------------------------------------------------------------------------
        .segment "SNDZP": zeropage
; owned by the interrupt
rp:             .res 2          ; the ring at rpos
rpos:           .res 2          ; stream bytes consumed since snd_start
ptab:           .res 2          ; the period table: 128 low bytes, then high
avail:          .res 2          ; bytes in the ring not yet consumed
cmdlen:         .res 1          ; the command's bytes, operands included
pl:             .res 1          ; a tone period
ph:             .res 1
prod:           .res 3          ; the bend's 12 x 8 bit product
mul:            .res 1
roff:           .res 1          ; a drum recipe's offset in drumtab
mix:            .res 1          ; a mixer value being built
fbase:          .res 1          ; flush: the chip's index in want
fout:           .res 1          ; flush: the next entry of the write list
nticks:         .res 1
wrapped:        .res 1          ; met the end once in this tick
; owned by the main loop (snd_start, snd_refill)
src:            .res 2
dst:            .res 2
rem:            .res 2
lim:            .res 1
mt:             .res 1

; ---------------------------------------------------------------------------
; the card: the ring, the write lists, the state
; ---------------------------------------------------------------------------
        .segment "SNDRING"      ; page aligned
ring:           .res RING_SIZE
ring_mirror:    .res 3          ; ring[0-2] again, so a command that wraps
                                ; reads its operands with (rp),y

        .segment "SNDLIST"      ; after the ring, not aligned: see below
wreg:           .res 64         ; chip c's writes at c x 16, in the order
wval:           .res 64         ; flush found them (registers descending)
; The burst's lda wreg+c*16-1,x and lda wval+c*16-1,x (X = 1-16) must not
; cross a page, or each costs a cycle more than the 41 cycles a
; register: wreg-1 to wval+63 in one page. The ring ends 3 bytes
; into a page, so the lists fit after it; the linker checks the map.
        .assert >(wreg - 1) = >(wval + 63), lderror, "SNDLIST crosses a page"

        .segment "SNDBSS"
want:           .res 64         ; chip x 16 + register: what the music wants
shadow:         .res 64         ; what the chips hold
retrig:         .res 4          ; R13 again, even when equal
wn:             .res 4          ; writes queued for each chip
; the voices
phase:          .res NV
eatt_lo:        .res NV         ; envelope attenuation, 1/256 steps
eatt_hi:        .res NV
natt:           .res NV
envoff:         .res NV         ; the envelope index x 8 (its offset in envtab)
note:           .res NV
bend:           .res NV
flags:          .res NV
dstep_lo:       .res NV
dstep_hi:       .res NV
hit:            .res NV
; the player
snd_playing:    .res 1          ; the interrupt plays
stop_req:       .res 1
loopflag:       .res 1
ended:          .res 1
wait:           .res 1
frac:           .res 2
tfrac:          .res 2          ; tempo: whole ticks and 16-bit fraction
tint:           .res 1
matt:           .res 1          ; music attenuation
wpos_hi:        .res 1          ; stream bytes in the ring / 256 (a page at a time)
exhausted:      .res 1          ; the stream is all in the ring (no loop)
srcpos:         .res 2          ; the next stream byte to copy
srcend:         .res 2
srcloop:        .res 2
hdr:            .res 8
envtab:         .res MAX_ENVELOPES * ENV_SIZE
drumtab:        .res MAX_DRUMS * DRUM_SIZE
; snd_start's arguments and result
snd_song_addr:  .res 2          ; the song file, in main $0200-$BFFF
snd_song_flags: .res 1          ; SONG_LOOP, SONG_NTSC
snd_song_matt:  .res 1          ; music attenuation, 0-80 (0.5 dB steps)
snd_error:      .res 1

; ---------------------------------------------------------------------------
; tables
; ---------------------------------------------------------------------------
        .segment "SNDRODATA"
        SND_VOICE_TABLES
        SND_PERIOD_TABLES
        SND_LEVEL_TABLES

cmd_length:     .byte   2, 3, 4, 1, 2, 2, 3, 1  ; commands $0v-$7v
cmd_table:      .word   cmd_note, cmd_note_att, cmd_note_att_env, cmd_off
                .word   cmd_att, cmd_bend, cmd_drum, cmd_cut
chip_in_layout: .byte   LAYOUT_CHIPS & 1, (LAYOUT_CHIPS >> 1) & 1
                .byte   (LAYOUT_CHIPS >> 2) & 1, (LAYOUT_CHIPS >> 3) & 1

        .segment "SNDCODE"

; ---------------------------------------------------------------------------
; snd_tick: one timer interrupt (a frame). A, X, Y: clobbered.
; ---------------------------------------------------------------------------
snd_tick:
        lda     snd_playing
        bne     @playing
        rts
@playing:
        lda     stop_req
        beq     @run
        jsr     silence                 ; snd_stop: the voices go quiet
        jsr     compose
        jsr     flush
        jsr     burst
        stz     snd_playing
        stz     stop_req
        rts
@run:
        ; 1. a note that started and ended in the last interrupt was heard
        ;    in that one; its release starts now. The flags are cleared.
        ldx     #NV-1
@pending:
        lda     flags,x
        and     #OFF_PENDING
        beq     @clear
        lda     phase,x
        dec     a                       ; ATTACK..SUSTAIN become 0..2
        cmp     #SUSTAIN
        bcs     @clear
        lda     #RELEASE
        sta     phase,x
@clear: stz     flags,x
        dex
        bpl     @pending
        ; 2. the ticks due: TEMPO_INT plus the carry of the fraction
        clc
        lda     frac
        adc     tfrac
        sta     frac
        lda     frac+1
        adc     tfrac+1
        sta     frac+1
        lda     tint
        adc     #0
        beq     @compose
        sta     nticks
@tick:  lda     ended
        bne     @envelopes
        jsr     commands
@envelopes:
        jsr     envelopes
        dec     nticks
        bne     @tick
        ; 3. the levels, 4. the burst
@compose:
        jsr     compose
        jsr     flush
        jmp     burst

; ---------------------------------------------------------------------------
; commands: the stream commands due in this tick
; ---------------------------------------------------------------------------
commands:
        lda     wait
        beq     @go
        dec     wait
        beq     @go
        rts
@go:    stz     wrapped
@next:  ; the bytes in the ring: wpos (a whole page) - rpos
        sec
        lda     #0
        sbc     rpos
        sta     avail
        lda     wpos_hi
        sbc     rpos+1
        sta     avail+1
        ora     avail
        beq     @starved
        lda     (rp)
        cmp     #$FF
        beq     @end
        cmp     #$80
        bcc     @command
        and     #$7F                    ; $81-$FE: wait 1-126 ticks
        beq     @bad                    ; $80 is not a command
        sta     wait
        lda     #1
        jmp     advance
@end:   lda     loopflag
        beq     @stop
        lda     wrapped
        bne     @bad                    ; a looping stream without a wait
        inc     wrapped
        lda     #1                      ; the refill put the loop's bytes
        jsr     advance                 ; right after the $FF
        bra     @next
@stop:  lda     #1
        sta     ended
        rts
@command:
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        tax
        lda     cmd_length,x
        sta     cmdlen
        ldy     avail+1
        bne     @enough
        cmp     avail
        beq     @enough
        bcs     @starved                ; not all its bytes are in the ring
@enough:
        lda     (rp)
        and     #$0F
        cmp     #NV
        bcs     @bad
        txa
        asl     a
        tax
        jsr     @dispatch
        lda     cmdlen
        jsr     advance
        bra     @next
@dispatch:
        jmp     (cmd_table,x)
@starved:
        jmp     silence                 ; hold the position, voices quiet
@bad:
stream_error:
        lda     #ERR_STREAM             ; a broken stream:
        sta     snd_error               ; the player stops reading
        lda     #1
        sta     ended
        rts

; advance: A = bytes consumed (1-4). The ring is page aligned, so rp
; leaves it only across a page boundary.
advance:
        pha
        clc
        adc     rpos
        sta     rpos
        bcc     :+
        inc     rpos+1
:       pla
        clc
        adc     rp
        sta     rp
        bcc     @done
        lda     rp+1
        inc     a
        cmp     #>(ring + RING_SIZE)
        bne     :+
        lda     #>ring
:       sta     rp+1
@done:  rts

voice_x:
        lda     (rp)
        and     #$0F
        tax
        rts

; ---- the commands: X is free on entry, (rp) is the command byte ----------

cmd_note:                               ; $0v nn
        jsr     voice_x
        ldy     #1
        lda     (rp),y
        bra     note_on

cmd_note_att:                           ; $1v nn aa
        jsr     voice_x
        ldy     #2
        lda     (rp),y
        sta     natt,x
        dey
        lda     (rp),y
        bra     note_on

cmd_note_att_env:                       ; $2v nn aa ee
        jsr     voice_x
        ldy     #3
        lda     (rp),y
        cmp     hdr+2                   ; an envelope of the song?
        bcs     bad_operand
        asl     a
        asl     a
        asl     a
        sta     envoff,x
        dey
        lda     (rp),y
        sta     natt,x
        dey
        lda     (rp),y
        ; fall through

; note_on: X = voice, A = note. The attack starts from
; the voice's current envelope level, as an OPL key-on does.
note_on:
        sta     note,x
        jsr     tone_of_note
        jsr     set_tone
        lda     #ATTACK
        sta     phase,x
        lda     #JUST_ON                ; and OFF_PENDING cleared
        sta     flags,x
        rts

cmd_off:                                ; $3v
        jsr     voice_x
        lda     flags,x
        lsr     a                       ; JUST_ON
        bcc     @held
        lda     flags,x
        ora     #OFF_PENDING            ; heard for one interrupt first
        sta     flags,x
        rts
@held:  lda     phase,x
        dec     a
        cmp     #SUSTAIN                ; ATTACK..SUSTAIN
        bcs     @done
        lda     #RELEASE
        sta     phase,x
@done:  rts

cmd_att:                                ; $4v aa
        jsr     voice_x
        ldy     #1
        lda     (rp),y
        sta     natt,x
        rts

cmd_bend:                               ; $5v bb
        jsr     voice_x
        ldy     #1
        lda     (rp),y
        sta     bend,x
        lda     note,x
        jsr     tone_of_note
        jmp     set_tone

cmd_drum:                               ; $6v dd aa: latched until compose
        jsr     voice_x
        ldy     #1
        lda     (rp),y
        cmp     hdr+3                   ; a drum recipe of the song?
        bcs     bad_operand
        inc     a
        sta     hit,x
        iny
        lda     (rp),y
        sta     natt,x
        rts

cmd_cut:                                ; $7v
        jsr     voice_x
        jmp     silence_voice

; an envelope or drum index outside the song's tables: the command's
; return to commands is dropped and the player stops reading, as for a
; bad voice
bad_operand:
        pla
        pla
        jmp     stream_error

; tone_of_note: X = voice, A = note: pl/ph = its period with the voice's
; bend
tone_of_note:
        tay
        lda     (ptab),y
        sta     pl
        tya
        ora     #$80
        tay
        lda     (ptab),y
        sta     ph
        lda     bend,x
        cmp     #128
        bne     bend_period
        rts

; bend_period: X = voice, A = its bend (not 128), pl/ph = the period.
; delta = (P x M[bend] + 1024) >> 11, a 12 x 8 bit product of up to 20
; bits; a bend below 128 lowers the pitch (the period grows, at most
; 4095), above 128 raises it (at least 1).
bend_period:
        tay
        lda     bend_magnitude,y
        sta     mul
        stz     prod
        stz     prod+1
        stz     prod+2
        ldy     #8
@bit:   asl     prod
        rol     prod+1
        rol     prod+2
        asl     mul
        bcc     @next
        clc
        lda     prod
        adc     pl
        sta     prod
        lda     prod+1
        adc     ph
        sta     prod+1
        bcc     @next
        inc     prod+2
@next:  dey
        bne     @bit
        clc                             ; + 1024
        lda     prod+1
        adc     #4
        sta     prod+1
        bcc     :+
        inc     prod+2
:       lda     prod+2                  ; >> 11: bits 11-19
        lsr     a
        ror     prod+1
        lsr     a
        ror     prod+1
        lsr     a
        ror     prod+1
        sta     prod+2                  ; delta: prod+2 (high), prod+1
        lda     bend,x
        bmi     @raise
        clc
        lda     pl
        adc     prod+1
        sta     pl
        lda     ph
        adc     prod+2
        sta     ph
        cmp     #$10
        bcc     @done
        lda     #$FF                    ; 4095
        sta     pl
        lda     #$0F
        sta     ph
@done:  rts
@raise: sec
        lda     pl
        sbc     prod+1
        sta     pl
        lda     ph
        sbc     prod+2
        sta     ph
        bcc     @one
        ora     pl
        bne     @done
@one:   lda     #1
        sta     pl
        stz     ph
        rts

; set_tone: X = voice, pl/ph = period
set_tone:
        ldy     v_tone,x
        lda     pl
        sta     want,y
        lda     ph
        sta     want+1,y
        rts

; silence_voice: X = voice: idle, silent, no flags, no latched hit
silence_voice:
        stz     phase,x                 ; IDLE
        stz     eatt_lo,x
        lda     #ATT_MAX
        sta     eatt_hi,x
        stz     flags,x
        stz     hit,x
        rts

silence:
        ldx     #NV-1
:       jsr     silence_voice
        dex
        bpl     :-
        rts

; ---------------------------------------------------------------------------
; envelopes: every voice's envelope one tick. A 16-bit
; add that carries is past every limit, like a sum at or above it.
; ---------------------------------------------------------------------------
envelopes:
        ldx     #NV-1
@voice: lda     phase,x
        cmp     #DRUM_SOFT
        beq     @soft
        cmp     #ATTACK
        beq     @attack
        cmp     #DECAY
        beq     @decay
        cmp     #RELEASE
        beq     @release
@next:  dex
        bpl     @voice
        rts
@soft:  clc
        lda     eatt_lo,x
        adc     dstep_lo,x
        sta     eatt_lo,x
        lda     eatt_hi,x
        adc     dstep_hi,x
        bcs     @silent
        cmp     #ATT_MAX                ; >= 80 x 256
        bcs     @silent
        sta     eatt_hi,x
        bra     @next
@silent:
        stz     eatt_lo,x
        lda     #ATT_MAX
        sta     eatt_hi,x
        stz     phase,x                 ; IDLE
        bra     @next
@attack:
        ldy     envoff,x
        sec
        lda     eatt_lo,x
        sbc     envtab+0,y
        sta     eatt_lo,x
        lda     eatt_hi,x
        sbc     envtab+1,y
        bcc     @full                   ; below 0
        sta     eatt_hi,x
        ora     eatt_lo,x
        bne     @next
@full:  stz     eatt_lo,x
        stz     eatt_hi,x
        lda     #DECAY
        sta     phase,x
        bra     @next
@release:
        ldy     envoff,x
        clc
        lda     eatt_lo,x
        adc     envtab+4,y
        sta     eatt_lo,x
        lda     eatt_hi,x
        adc     envtab+5,y
        bcs     @silent
        cmp     #ATT_MAX
        bcs     @silent
        sta     eatt_hi,x
        bra     @next
@decay: ldy     envoff,x
        clc
        lda     eatt_lo,x
        adc     envtab+2,y
        sta     eatt_lo,x
        lda     eatt_hi,x
        adc     envtab+3,y
        bcs     @sustain
        cmp     envtab+6,y              ; >= sustain x 256
        bcs     @sustain
        sta     eatt_hi,x
        jmp     @next
@sustain:
        lda     envtab+6,y
        sta     eatt_hi,x
        stz     eatt_lo,x
        lda     envtab+7,y
        and     #ENV_SUSTAINED
        beq     :+
        lda     #SUSTAIN
        sta     phase,x
        jmp     @next
:       lda     #RELEASE                ; a percussive program decays on
        sta     phase,x
        jmp     @next

; ---------------------------------------------------------------------------
; compose: the latched drum hits start, then every voice's level register
; ---------------------------------------------------------------------------
compose:
        ldx     #0
@voice: lda     hit,x
        beq     @level
        jsr     drum_start
        stz     hit,x
@level: lda     phase,x
        beq     @zero                   ; IDLE
        cmp     #DRUM_HW
        beq     @hw
        clc                             ; natt + eatt / 256 + matt, at most 80
        lda     natt,x
        adc     eatt_hi,x
        bcs     @max
        adc     matt
        bcs     @max
        cmp     #ATT_MAX+1
        bcc     @look
@max:   lda     #ATT_MAX
@look:  tay
        lda     level_of_att,y
        bra     @store
@hw:    lda     #$10                    ; the chip's envelope
        bra     @store
@zero:  lda     #0
@store: ldy     v_level,x
        sta     want,y
        inx
        cpx     #NV
        bne     @voice
        rts

; drum_start: X = voice, hit,x = recipe + 1: tone,
; noise and mixer from the recipe, then the chip's envelope for a loud
; hit or a software decay from full level for a quiet one
drum_start:
        lda     hit,x
        dec     a
        sta     roff
        asl     a
        adc     roff                    ; x 3 (a recipe index is below 43)
        asl     a                       ; x 6
        sta     roff
        ldy     v_base,x
        lda     want+7,y                ; tone and noise off
        ora     v_tonebit,x
        ora     v_noisebit,x
        sta     mix
        ldy     roff
        lda     drumtab+0,y             ; tone note, not bent
        beq     @noise
        tay
        lda     (ptab),y
        sta     pl
        tya
        ora     #$80
        tay
        lda     (ptab),y
        sta     ph
        jsr     set_tone
        lda     v_tonebit,x
        eor     #$FF
        and     mix
        sta     mix
@noise: ldy     roff
        lda     drumtab+1,y
        beq     @mixer
        ldy     v_base,x
        sta     want+6,y
        lda     v_noisebit,x
        eor     #$FF
        and     mix
        sta     mix
@mixer: ldy     v_base,x
        lda     mix
        sta     want+7,y
        clc
        lda     natt,x
        adc     matt
        bcs     @soft
        cmp     #HW_DRUM_ATT+1
        bcs     @soft
        ldy     roff                    ; loud: the envelope period, shape \___
        lda     drumtab+3,y
        pha
        lda     drumtab+2,y
        ldy     v_base,x
        sta     want+11,y
        pla
        sta     want+12,y
        lda     #0
        sta     want+13,y
        ldy     v_chip,x
        lda     #1
        sta     retrig,y
        lda     #DRUM_HW
        sta     phase,x
        rts
@soft:  stz     eatt_lo,x
        stz     eatt_hi,x
        ldy     roff
        lda     drumtab+4,y
        sta     dstep_lo,x
        lda     drumtab+5,y
        sta     dstep_hi,x
        lda     #DRUM_SOFT
        sta     phase,x
        rts

; ---------------------------------------------------------------------------
; flush: the owned registers that differ from the shadow,
; into each chip's write list. owned_list gives the chips in descending
; order, each with its registers in descending order, so the burst,
; which walks a list backwards, writes chips and registers ascending.
; ---------------------------------------------------------------------------
flush:
        stz     wn
        stz     wn+1
        stz     wn+2
        stz     wn+3
        ldy     #0
@chip:  lda     owned_list,y
        cmp     #$FF
        beq     @done
        and     #3
        tax
        asl     a
        asl     a
        asl     a
        asl     a
        sta     fbase
        sta     fout
        lda     retrig,x                ; R13 again after a retrigger:
        beq     @regs                   ; make its shadow differ
        stz     retrig,x
        ldx     fbase
        lda     want+13,x
        eor     #1
        sta     shadow+13,x
@regs:  iny
@reg:   ldx     owned_list,y
        bmi     @end
        lda     want,x
        cmp     shadow,x
        beq     @same
        sta     shadow,x
        phy
        ldy     fout
        sta     wval,y
        txa
        and     #$0F
        sta     wreg,y
        inc     fout
        ply
@same:  iny
        bra     @reg
@end:   lda     fbase
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        tax
        sec
        lda     fout
        sbc     fbase
        sta     wn,x
        bra     @chip
@done:  rts

; ---------------------------------------------------------------------------
; burst: each chip's write list, chips ascending, six VIA stores a
; register (41 cycles a register)
; ---------------------------------------------------------------------------
.macro BURST_CHIP chip, ora, orb, latch, write, idle
        .local loop, skip
        ldx     wn+chip
        beq     skip
        ldy     #idle
loop:   lda     wreg+chip*16-1,x
        sta     ora
        lda     #latch
        sta     orb
        sty     orb
        lda     wval+chip*16-1,x
        sta     ora
        lda     #write
        sta     orb
        sty     orb
        dex
        bne     loop
skip:
.endmacro

; The four chips of native mode, the layout's.
        .assert LAYOUT_CHIPS = $0F, error, "the player drives four chips"

burst:
        BURST_CHIP 0, VIA_A_ORA_NH, VIA_A_ORB, ORB_LATCH0, ORB_WRITE0, ORB_IDLE0
        BURST_CHIP 1, VIA_A_ORA_NH, VIA_A_ORB, ORB_LATCH1, ORB_WRITE1, ORB_IDLE1
        BURST_CHIP 2, VIA_B_ORA_NH, VIA_B_ORB, ORB_LATCH0, ORB_WRITE0, ORB_IDLE0
        BURST_CHIP 3, VIA_B_ORA_NH, VIA_B_ORB, ORB_LATCH1, ORB_WRITE1, ORB_IDLE1
        rts

; ---------------------------------------------------------------------------
; snd_init: once, after snd_probe and before any snd_start, whatever the
; probe answered. The card's native mode ($C0C8 then $C0C5), the VIAs'
; interrupts off, their ports as outputs, both AYs of each VIA reset (ORB
; 0, then idle), and the player stopped, so that snd_tick returns at once
; until a snd_start. With SND_NO_MUSIC (a card that cannot switch) the
; program calls nothing else of the player: the mode switch is ignored and
; the resets leave the chips quiet.
; ---------------------------------------------------------------------------
snd_init:
        bit     PHASOR_MB
        bit     PHASOR_NATIVE
        lda     #$7F
        sta     VIA_A_IER
        sta     VIA_B_IER
        lda     #$FF
        sta     VIA_A_DDRA
        sta     VIA_B_DDRA
        lda     #$1F
        sta     VIA_A_DDRB
        sta     VIA_B_DDRB
        stz     VIA_A_ORB
        stz     VIA_B_ORB
        lda     #ORB_IDLE0
        sta     VIA_A_ORB
        sta     VIA_B_ORB
        stz     snd_playing
        stz     stop_req
        stz     snd_error
        rts

; ---------------------------------------------------------------------------
; snd_stop: the next interrupt silences the music voices, writes that
; burst and stops the player.
; ---------------------------------------------------------------------------
snd_stop:
        lda     snd_playing
        beq     :+
        lda     #1
        sta     stop_req
:       rts

; ---------------------------------------------------------------------------
; snd_start: play the song file at snd_song_addr with
; snd_song_flags and snd_song_matt.
; Carry clear: playing. Carry set: refused, A = snd_error. Runs in the
; main loop with interrupts on; the player is off until it ends.
; ---------------------------------------------------------------------------
snd_start:
        stz     snd_playing
        stz     stop_req
        lda     snd_song_addr
        sta     src
        lda     snd_song_addr+1
        sta     src+1
        ldy     #7
@header:
        lda     (src),y
        sta     hdr,y
        dey
        bpl     @header
        jsr     check_header
        bcc     :+
        jmp     @refuse
:       lda     #8
        jsr     skip_src
        lda     hdr+2                   ; the envelopes: 8 bytes each
        asl     a
        asl     a
        asl     a
        tax
        beq     @drums
        ldy     #0
:       lda     (src),y
        sta     envtab,y
        iny
        dex
        bne     :-
        tya
        jsr     skip_src
@drums: lda     hdr+3                   ; the drum recipes: 6 bytes each
        asl     a
        adc     hdr+3
        asl     a
        tax
        beq     @stream
        ldy     #0
:       lda     (src),y
        sta     drumtab,y
        iny
        dex
        bne     :-
        tya
        jsr     skip_src
@stream:
        lda     src                     ; srcpos: the stream
        sta     srcpos
        clc
        adc     hdr+4
        sta     srcend
        lda     src+1
        sta     srcpos+1
        adc     hdr+5
        sta     srcend+1
        clc
        lda     src
        adc     hdr+6
        sta     srcloop
        lda     src+1
        adc     hdr+7
        sta     srcloop+1
        ; the machine: period table and tempo
        lda     snd_song_flags
        bmi     @ntsc
        lda     #<period_pal
        ldx     #>period_pal
        ldy     #TEMPO_INT_PAL
        sty     tint
        ldy     #<TEMPO_FRAC_PAL
        sty     tfrac
        ldy     #>TEMPO_FRAC_PAL
        bra     @machine
@ntsc:  lda     #<period_ntsc
        ldx     #>period_ntsc
        ldy     #TEMPO_INT_NTSC
        sty     tint
        ldy     #<TEMPO_FRAC_NTSC
        sty     tfrac
        ldy     #>TEMPO_FRAC_NTSC
@machine:
        sty     tfrac+1
        sta     ptab
        stx     ptab+1
        lda     snd_song_flags
        and     #SONG_LOOP
        sta     loopflag
        lda     snd_song_matt
        sta     matt
        ; the voices
        ldx     #NV-1
@voices:
        jsr     silence_voice
        stz     natt,x
        stz     envoff,x
        stz     note,x
        stz     dstep_lo,x
        stz     dstep_hi,x
        lda     #128
        sta     bend,x
        dex
        bpl     @voices
        stz     rpos
        stz     rpos+1
        lda     #<ring
        sta     rp
        lda     #>ring
        sta     rp+1
        stz     wpos_hi
        stz     exhausted
        stz     wait
        stz     frac
        stz     frac+1
        stz     ended
        stz     snd_error
        jsr     refill
        jsr     reset_chips
        lda     #1
        sta     snd_playing
        clc
        rts
@refuse:
        sta     snd_error
        sec
        rts

; check_header: carry set and A = the error when hdr is not a song file
; this player can play
check_header:
        lda     #ERR_VERSION
        ldx     hdr+0
        cpx     #SONG_VERSION
        bne     @refuse
        lda     #ERR_LAYOUT
        ldx     hdr+1
        cpx     #LAYOUT_ID
        bne     @refuse
        lda     #ERR_TABLES
        ldx     hdr+2
        cpx     #MAX_ENVELOPES+1
        bcs     @refuse
        ldx     hdr+3
        cpx     #MAX_DRUMS+1
        bcs     @refuse
        ldx     hdr+6                   ; the loop must start inside
        cpx     hdr+4                   ; the stream
        lda     hdr+7
        sbc     hdr+5
        lda     #ERR_LOOP
        rts                             ; carry clear: loop < length
@refuse:
        sec
        rts

skip_src:                               ; src += A
        clc
        adc     src
        sta     src
        bcc     :+
        inc     src+1
:       rts

; reset_chips: the first burst: every chip of the layout
; gets R0-R12, all 0 but the mixer R7, $38 (tones on, noises off)
reset_chips:
        ldx     #63
:       stz     want,x
        stz     shadow,x
        dex
        bpl     :-
        lda     #$38
        sta     want+7
        sta     want+16+7
        sta     want+32+7
        sta     want+48+7
        sta     shadow+7
        sta     shadow+16+7
        sta     shadow+32+7
        sta     shadow+48+7
        ldx     #3
@chip:  stz     retrig,x
        stz     wn,x
        lda     chip_in_layout,x
        beq     @next
        lda     #13
        sta     wn,x
        txa
        asl     a
        asl     a
        asl     a
        asl     a
        tay
        lda     #12                     ; the burst walks backwards: R12
        sta     mt                      ; first in the list, R0 last
@reg:   lda     mt
        sta     wreg,y
        cmp     #7
        bne     :+
        lda     #$38
        bra     :++
:       lda     #0
:       sta     wval,y
        iny
        dec     mt
        bpl     @reg
@next:  dex
        bpl     @chip
        jmp     burst

; ---------------------------------------------------------------------------
; snd_refill and refill: when half the ring or more is free, copy 512
; bytes of the stream into it (two pages), until less than half is free
; or the stream (not looping) is all in the ring. After the $FF of a
; looping song comes its loop, so the player reads on. Main loop only.
; ---------------------------------------------------------------------------
snd_refill:
        lda     snd_playing
        bne     refill
        rts
refill:
@again: lda     exhausted
        bne     @done
        php                             ; rpos belongs to the interrupt
        sei
        ldy     rpos
        ldx     rpos+1
        plp
        sty     mt
        stx     lim
        sec
        lda     #0
        sbc     mt
        tay                             ; used = wpos - rpos: low ...
        lda     wpos_hi
        sbc     lim                     ; ... and high
        cmp     #2                      ; at most 512?
        bcc     @copy
        bne     @done
        cpy     #0
        bne     @done
@copy:  jsr     copy_page
        lda     exhausted
        bne     @again
        jsr     copy_page
        bra     @again
@done:  rts

; copy_page: the next ring page from the stream.
; A page is published (wpos_hi + 1, one byte, so the interrupt never sees
; half of it) once all its bytes are in.
copy_page:
        lda     wpos_hi
        and     #>(RING_SIZE - 1)
        clc
        adc     #>ring
        sta     dst+1
        stz     dst
        ldy     #0                      ; Y: the offset in the page
@run:   sec                             ; the bytes left in the stream
        lda     srcend
        sbc     srcpos
        sta     rem
        lda     srcend+1
        sbc     srcpos+1
        sta     rem+1
        ora     rem
        bne     @bytes
        lda     loopflag                ; the end: the loop, or no more
        beq     @exhausted
        lda     srcloop
        sta     srcpos
        lda     srcloop+1
        sta     srcpos+1
        bra     @run
@exhausted:
        lda     #1
        sta     exhausted
        bra     @publish
@bytes: sty     mt                      ; src = srcpos - Y: (src),y = srcpos
        sec
        lda     srcpos
        sbc     mt
        sta     src
        lda     srcpos+1
        sbc     #0
        sta     src+1
        lda     rem+1                   ; to the page end or the stream end
        bne     @whole
        tya
        clc
        adc     rem
        bcs     @whole
        sta     lim
        bra     @copy
@whole: stz     lim
@copy:  lda     (src),y
        sta     (dst),y
        iny
        cpy     lim
        bne     @copy
        tya                             ; srcpos = src + Y (+ 256 when Y
        clc                             ; wrapped at the page end)
        adc     src
        sta     srcpos
        lda     src+1
        adc     #0
        cpy     #0
        bne     :+
        inc     a
:       sta     srcpos+1
        cpy     #0
        bne     @run                    ; the stream ended in the page
@publish:
        lda     wpos_hi
        and     #>(RING_SIZE - 1)
        bne     :+
        lda     ring                    ; page 0: its first bytes again
        sta     ring_mirror             ; after the ring's end
        lda     ring+1
        sta     ring_mirror+1
        lda     ring+2
        sta     ring_mirror+2
:       inc     wpos_hi
        rts
