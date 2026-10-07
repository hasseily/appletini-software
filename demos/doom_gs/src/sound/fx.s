; fx.s: the sound effects' player on chip 3 of the Phasor. GPL-2, the port's
; own: written from the design (tools/sound/README.md "Effects (S4)", "The
; player"; docs/SCREENS.md) and the music player (src/sound/player.s: its
; burst loop and the Phasor's addressing). Nothing of upstream's: its DOC
; code is dropped.
;
; It was written against a Python model of the player (no longer in this
; tree): the same state, the same steps in the same order, the same
; integer arithmetic, the same registers of chip 3 in the same order at
; every interrupt.
;
; Two objects come from this file (src/native/play.mk: fx.o, fx-card.o):
;
;   the card part (FXCODE, the main card's $F505-$F8FF with pl_vbl):
;     fx_step      the VBL interrupt, before snd_tick (pl_vbl's step 4):
;                  the effects' tempo, each active voice's ticks from its
;                  ring, then chip 3's registers composed and the ones
;                  that differ from the shadow put in the write list. No
;                  I/O; with no voice active or ending it returns at once
;     fx_burst     the same interrupt, right after snd_tick's burst (step
;                  6): the write list to the second AY of VIA-B, S2's
;                  41-cycle loop; nothing when the list is empty
;     fx_song      the main loop's song start: FX_HOLD set, S2's
;                  snd_start (its arguments as S2's; returns its carry
;                  and A), FX_INVAL set, FX_HOLD cleared
;     fx_init      boot, after snd_probe and snd_init: A = snd_probe's
;                  answer; FX_ON 1 for SND_MUSIC (native mode), else 0;
;                  the shadow invalid; every voice idle; the mailboxes
;                  empty
;     fx_stopall   main loop: every active voice stops (level 0 at the
;                  next interrupt), every mailbox emptied
;     fx_isplaying main loop (the channel logic's isPlaying): X = a
;                  channel; A = 1 and carry set when its voice is active
;                  or its mailbox holds a start, else A = 0, carry clear.
;                  X kept
;     fx_copy      main loop: A bytes (1-255) of the effects' bank S2SFX
;                  from the address in fxc_ld+1 to the one in fxc_st+1,
;                  through a RAMRD window (code of the card: a window
;                  hides $0200-$BFFF of main memory)
;     fx_volume    main loop: the voice at X gets VATT[mailbox Y's
;                  volume], read from SFX.1's table through a window
;
;   the frame side (S2CODE, a shared object of every frame image; -D
;   FX_SERVICE):
;     fx_service   the main loop, once a frame: each channel's mailbox in
;                  order (a stop silences the channel's voice; a start
;                  stops it too, chooses a voice by the stereo rule,
;                  copies the script's head into its ring and sets the
;                  voice active last; a volume sets the voice's
;                  attenuation), the mailbox emptied; then every active
;                  voice's ring refilled, a piece at a time, each piece
;                  published (V_WPOS) after its bytes. With FX_ON 0 the
;                  mailboxes are emptied and nothing starts
;
; The voices (s2layout.py VOICE_FIELDS, card $E413-$E442, 16 B each):
;   V_FLAGS  VF_ACTIVE, VF_ENDING (level 0 at the next interrupt, then
;            idle), VF_STARVED (no bytes this interrupt), VF_LAST (the
;            script ends when the wait expires)
;   V_HEAD   the next script byte to copy, an address in bank S2SFX
;   V_LEFT   the script's bytes not yet in the ring
;   V_WPOS   the bytes put in the ring, mod 256 (the main loop's)
;   V_RPOS   the bytes the interrupt took from it, mod 256
;   V_RUN    the ticks left of the current state (0: read the script)
;   V_PER    the tone period (0: tone off); V_LEVEL the step's
;            attenuation (0-80); V_NOISE the noise period (0: off)
;   V_CHAN   the channel whose sound it plays; V_ATT the volume's
;            attenuation (VATT[volume]); V_SOUND the sound (1-52)
; A ring holds 128 bytes; wpos - rpos (mod 256) of them are unread.
;
; The script (tools/sound/fxconv.py, version 1): $00-$3F wait 1-64 ticks;
; $40-$4F a set (bit 0 a u16 period, bit 1 the attenuation, bit 2 the
; noise period follow, in that order; bit 3: one wait byte follows and
; the script ends when it expires); $FF the end. A byte $50-$FE ends the
; voice too. A start copies the script's first bytes, its 4-byte header
; with them, into the ring, and takes the header at once (rpos 4).

        .setcpu "65C02"
        .include "s2.inc"
        .include "tables.inc"

; ---- the Phasor and the machine (S2's src/sound/sound.inc; its names,
; not included: its RING_SIZE is the song ring's) -----------------------
VIA_B_ORB       = $C480
VIA_B_ORA_NH    = $C48F
ORB_LATCH1      = $17           ; the second AY of a VIA
ORB_WRITE1      = $16
ORB_IDLE1       = $14
RAMRD_OFF       = $C002
RAMRD_ON        = $C003
RAMWORKS        = $C073
SND_MUSIC       = 0             ; snd_probe's answer: native mode

; ---- the effects --------------------------------------------------------
VF_ACTIVE       = $80
VF_ENDING       = $40
VF_STARVED      = $02
VF_LAST         = $01
FX_DIR          = $0200         ; SFX.1 in bank S2SFX: the directory,
FX_VATT         = $02D0         ; the volume table (fxconv.py)
ATT_SILENT      = 80
NREGS           = 11            ; R0-R10 of chip 3

; the interrupt's zero page: s2layout's FX_ZP in ZP_FXRING ($F7-$FC):
; FXZ_RING (2) the ring of the voice being run; FXZ_N the ticks of this
; interrupt; FXZ_T the voice's ticks left; FXZ_AV the unread bytes; FXZ_OP
; the set's field bits. Compose reuses the last four under these names:
FXZ_MIX         = FXZ_N         ; the mixer
FXZ_BEST        = FXZ_T         ; the loudest noise's attenuation
FXZ_A           = FXZ_AV        ; the voice's attenuation
FXZ_V           = FXZ_OP        ; the voice's number

; fx_service's temporaries: FX_SVC's 4 bytes (main loop only)
FXS_C           = FX_SVC        ; the mailbox's offset
FXS_V           = FX_SVC + 1    ; the voice's offset
FXS_N           = FX_SVC + 2    ; bytes to copy; a channel; a count
FXS_P           = FX_SVC + 3    ; a piece; a count

        .assert TEMPO_INT_PAL = TEMPO_INT_NTSC, error, "one whole tempo"
        .assert VOICES = 3 && MAIL_SIZE = 4, error, "3 voices, 4-byte mail"
        .assert >FXV_BASE = >(FXV_BASE + VOICES * VOICE_SIZE - 1), error, "the voices in one page"
        .assert <FX_RING < $80 && RING_SIZE = 128, error, "the rings: 128 bytes from $xx00-$xx7F"
        .assert FX_RING + VOICES * RING_SIZE <= $E8C0, error, "the rings"
        .assert NUM_CHANNELS * MAIL_SIZE < 256, error, "the mailboxes"

.ifndef FX_SERVICE
; ===========================================================================
; the card part
; ===========================================================================

        .import snd_start, level_of_att
        .export fx_step, fx_burst, fx_song, fx_init, fx_stopall
        .export fx_isplaying, fx_copy, fxc_ld, fxc_st, fx_volume
        .export fx_want, fx_shadow, fx_wn

        .segment "FXCODE"

; ---------------------------------------------------------------------------
; fx_step: the interrupt's steps. A, X, Y free.
; ---------------------------------------------------------------------------
fx_step:
        lda FX_ON
        beq @rts
        lda FXV_BASE + V_FLAGS
        ora FXV_BASE + VOICE_SIZE + V_FLAGS
        ora FXV_BASE + 2 * VOICE_SIZE + V_FLAGS
        and #VF_ACTIVE | VF_ENDING
        bne @work
@rts:   rts
@work:  ldx #<TEMPO_FRAC_PAL    ; the tempo: the music's, its own fraction
        ldy #>TEMPO_FRAC_PAL
        bit CLK_STD
        bpl :+
        ldx #<TEMPO_FRAC_NTSC
        ldy #>TEMPO_FRAC_NTSC
:       clc
        txa
        adc FX_TEMPO
        sta FX_TEMPO
        tya
        adc FX_TEMPO + 1
        sta FX_TEMPO + 1
        lda #TEMPO_INT_PAL
        adc #0
        sta FXZ_N
        ldx #0                  ; X: the voice's offset
@voice: lda FXV_BASE + V_FLAGS,x
        and #<~VF_STARVED
        sta FXV_BASE + V_FLAGS,x
        bpl @next               ; not active
        txa                     ; its ring: FX_RING + 128 x the voice
        asl a
        asl a
        asl a
        ldy #>FX_RING
        bcc :+
        iny
:       ora #<FX_RING
        sta FXZ_RING
        sty FXZ_RING + 1
        lda FXZ_N
        sta FXZ_T
@tick:  jsr fx_tick
        bcs @next               ; starved or ended: no more ticks
        dec FXZ_T
        bne @tick
@next:  txa
        clc
        adc #VOICE_SIZE
        tax
        cpx #VOICES * VOICE_SIZE
        bne @voice
        ; compose chip 3: R0-R5 the periods, R6 the noise of the loudest
        ; voice with noise on, R7 the mixer, R8-R10 the levels
        lda #$3F
        sta FXZ_MIX
        lda #$FF
        sta FXZ_BEST
        ldx #0
@cv:    txa
        lsr a
        lsr a
        lsr a
        lsr a
        sta FXZ_V
        tay
        lda FXV_BASE + V_FLAGS,x
        and #VF_ACTIVE | VF_STARVED
        cmp #VF_ACTIVE
        beq @on
        lda #0                  ; silent; an ending voice goes idle
        sta fx_want + 8,y
        lda FXV_BASE + V_FLAGS,x
        bmi @cnext
        stz FXV_BASE + V_FLAGS,x
        bra @cnext
@on:    clc                     ; LEVEL[min(80, step + volume)]
        lda FXV_BASE + V_LEVEL,x
        adc FXV_BASE + V_ATT,x
        cmp #ATT_SILENT + 1
        bcc :+
        lda #ATT_SILENT
:       sta FXZ_A
        tay
        lda level_of_att,y
        ldy FXZ_V
        sta fx_want + 8,y
        lda FXV_BASE + V_NOISE,x
        beq @tone
        lda fx_nbit,y
        trb FXZ_MIX
        lda FXZ_A
        cmp FXZ_BEST
        bcs @tone               ; not louder than an earlier voice
        sta FXZ_BEST
        lda FXV_BASE + V_NOISE,x
        sta fx_want + 6
@tone:  lda FXV_BASE + V_PER,x
        ora FXV_BASE + V_PER + 1,x
        beq :+
        lda fx_tbit,y
        trb FXZ_MIX
:       tya
        asl a
        tay
        lda FXV_BASE + V_PER,x
        sta fx_want,y
        lda FXV_BASE + V_PER + 1,x
        sta fx_want + 1,y
@cnext: txa
        clc
        adc #VOICE_SIZE
        tax
        cpx #VOICES * VOICE_SIZE
        bne @cv
        lda FXZ_MIX
        sta fx_want + 7
        ; the write list: nothing while a song starts; every register
        ; when the shadow is invalid; else those that changed. Built
        ; R10 first, so the burst, which walks it backwards, writes R0
        ; first
        lda FX_HOLD
        bne @done
        ldy #0
        ldx #NREGS - 1
@reg:   lda fx_want,x
        cmp fx_shadow,x
        bne @write
        lda FX_INVAL
        beq @same
        lda fx_want,x
@write: sta fx_shadow,x
        sta fx_wval,y
        txa
        sta fx_wreg,y
        iny
@same:  dex
        bpl @reg
        stz FX_INVAL
        sty fx_wn
@done:  rts

; fx_tick: one tick of the voice at X. Carry set:
; it took no more ticks in this interrupt (starved, or ended).
fx_tick:
        lda FXV_BASE + V_RUN,x
        beq @read
        dec FXV_BASE + V_RUN,x
        bne @ok
        lda FXV_BASE + V_FLAGS,x
        lsr a                   ; VF_LAST: the script ends here
        bcs @end
@read:  sec                     ; the unread bytes
        lda FXV_BASE + V_WPOS,x
        sbc FXV_BASE + V_RPOS,x
        beq @starve
        sta FXZ_AV
        lda FXV_BASE + V_RPOS,x
        and #RING_SIZE - 1
        tay
        lda (FXZ_RING),y        ; the step, not taken yet
        cmp #$40
        bcc @wait
        cmp #$50
        bcs @end                ; $FF, or no step: the end
        and #$0F
        tay
        lda fx_setlen,y
        cmp FXZ_AV
        beq :+
        bcs @starve             ; not all its bytes are in the ring
:       jsr fx_byte
        lsr a                   ; bit 0: the period
        sta FXZ_OP
        bcc :+
        jsr fx_byte
        sta FXV_BASE + V_PER,x
        jsr fx_byte
        sta FXV_BASE + V_PER + 1,x
:       lsr FXZ_OP              ; bit 1: the attenuation
        bcc :+
        jsr fx_byte
        sta FXV_BASE + V_LEVEL,x
:       lsr FXZ_OP              ; bit 2: the noise period
        bcc :+
        jsr fx_byte
        sta FXV_BASE + V_NOISE,x
:       lsr FXZ_OP              ; bit 3: a last wait follows
        bcc @read
        lda FXV_BASE + V_FLAGS,x
        ora #VF_LAST
        sta FXV_BASE + V_FLAGS,x
@wait:  jsr fx_byte             ; a wait: this tick is its first
        and #$3F
        inc a
        sta FXV_BASE + V_RUN,x
@ok:    clc
        rts
@starve:
        lda FXV_BASE + V_FLAGS,x
        ora #VF_STARVED
        sta FXV_BASE + V_FLAGS,x
        sec
        rts
@end:   lda #VF_ENDING
        sta FXV_BASE + V_FLAGS,x
        sec
        rts

; fx_byte: the next byte of the ring of the voice at X, taken
fx_byte:
        lda FXV_BASE + V_RPOS,x
        inc FXV_BASE + V_RPOS,x
        and #RING_SIZE - 1
        tay
        lda (FXZ_RING),y
        rts

; ---------------------------------------------------------------------------
; fx_burst: the write list to chip 3, S2's loop (player.s BURST_CHIP)
; ---------------------------------------------------------------------------
fx_burst:
        ldx fx_wn
        beq @none
        ldy #ORB_IDLE1
@loop:  lda fx_wreg - 1,x
        sta VIA_B_ORA_NH
        lda #ORB_LATCH1
        sta VIA_B_ORB
        sty VIA_B_ORB
        lda fx_wval - 1,x
        sta VIA_B_ORA_NH
        lda #ORB_WRITE1
        sta VIA_B_ORB
        sty VIA_B_ORB
        dex
        bne @loop
        stz fx_wn
@none:  rts

; ---------------------------------------------------------------------------
; fx_song: a song start: snd_start ends with
; reset_chips, a burst of all four chips from the main loop; an effect
; burst inside it would tear VIA-B's latch sequence, and after it chip 3
; no longer holds what the shadow says. snd_start's carry and A kept.
; ---------------------------------------------------------------------------
fx_song:
        lda #1
        sta FX_HOLD
        jsr snd_start
        php
        ldx #1
        stx FX_INVAL
        stz FX_HOLD
        plp
        rts

; ---------------------------------------------------------------------------
; fx_init: A = snd_probe's answer (boot, after snd_init)
; ---------------------------------------------------------------------------
fx_init:
        ldx #0
        cmp #SND_MUSIC
        bne :+
        inx
:       stx FX_ON
        stz FX_HOLD
        lda #1
        sta FX_INVAL
        stz FX_TEMPO
        stz FX_TEMPO + 1
        stz fx_wn
        ldx #NREGS - 1
:       stz fx_want,x
        dex
        bpl :-
        lda #$3F                ; every tone and noise off
        sta fx_want + 7
        ldx #(VOICES - 1) * VOICE_SIZE
:       stz FXV_BASE + V_FLAGS,x
        txa
        sec
        sbc #VOICE_SIZE
        tax
        bcs :-
        ; fall through: the mailboxes empty

; fx_mailclear: every mailbox empty
fx_mailclear:
        ldx #(NUM_CHANNELS - 1) * MAIL_SIZE
:       stz SC_MAIL + MX_FLAGS,x
        txa
        sec
        sbc #MAIL_SIZE
        tax
        bcs :-
        rts

; ---------------------------------------------------------------------------
; fx_stopall
; ---------------------------------------------------------------------------
fx_stopall:
        ldx #(VOICES - 1) * VOICE_SIZE
@v:     lda FXV_BASE + V_FLAGS,x
        bpl :+
        lda #VF_ENDING
        sta FXV_BASE + V_FLAGS,x
:       txa
        sec
        sbc #VOICE_SIZE
        tax
        bcs @v
        bra fx_mailclear

; ---------------------------------------------------------------------------
; fx_isplaying: X = the channel
; ---------------------------------------------------------------------------
fx_isplaying:
        txa
        asl a
        asl a
        tay
        lda SC_MAIL + MX_FLAGS,y
        and #MX_START
        bne @yes                ; a start the service has not taken
        ldy #(VOICES - 1) * VOICE_SIZE
@v:     lda FXV_BASE + V_FLAGS,y
        bpl @n
        txa
        cmp FXV_BASE + V_CHAN,y
        beq @yes
@n:     tya
        sec
        sbc #VOICE_SIZE
        tay
        bcs @v
        lda #0
        clc
        rts
@yes:   lda #1
        sec
        rts

; ---------------------------------------------------------------------------
; fx_copy: A bytes (1-255) from bank S2SFX (the address at fxc_ld+1) to
; main memory or the card (fxc_st+1). X kept; Y 0 after. A RAMRD window:
; this code and its operands are in the card, which the window does not
; move.
; ---------------------------------------------------------------------------
fx_copy:
        phx
        tax
        lda #S2SFX
        sta RAMWORKS
        sta RAMRD_ON
        ldy #0
fxc_ld: lda $FFFF,y
fxc_st: sta $FFFF,y
        iny
        dex
        bne fxc_ld
        sta RAMRD_OFF
        stz RAMWORKS
        plx
        rts

; fx_volume: V_ATT of the voice at X = VATT[the volume of mailbox Y],
; the volume table in bank S2SFX (bit 7 of the volume ignored). X, Y
; kept.
fx_volume:
        phy
        lda SC_MAIL + MX_VOL,y
        and #$7F
        tay
        lda #S2SFX
        sta RAMWORKS
        sta RAMRD_ON
        lda FX_VATT,y
        sta RAMRD_OFF
        stz RAMWORKS
        sta FXV_BASE + V_ATT,x
        ply
        rts

; ---------------------------------------------------------------------------
; tables and state
; ---------------------------------------------------------------------------
; the bytes of a set $4k, from its field bits
fx_setlen:
        .repeat 16, k
        .byte 1 + 2 * (k & 1) + ((k >> 1) & 1) + ((k >> 2) & 1) + ((k >> 3) & 1)
        .endrepeat
fx_tbit:        .byte $01, $02, $04     ; R7's tone bits of A, B, C
fx_nbit:        .byte $08, $10, $20     ; and their noise bits
fx_want:        .res NREGS              ; what chip 3 should hold
fx_shadow:      .res NREGS              ; what it holds (FX_INVAL: unknown)
fx_wn:          .res 1                  ; the write list's length
fx_wreg:        .res NREGS              ; the list: registers, R10 first
fx_wval:        .res NREGS              ; and values
        .assert >(fx_wreg - 1) = >(fx_wval + NREGS - 1), lderror, "fx_burst's lists cross a page (41 cycles a register)"

.else
; ===========================================================================
; the frame side: fx_service. X: a voice's offset; Y: a mailbox's.
; ===========================================================================

        .import fx_copy, fxc_ld, fxc_st, fx_volume
        .export fx_service

        .segment "S2CODE"

fx_service:
        ldy #0
@mail:  sty FXS_C
        lda SC_MAIL + MX_FLAGS,y
        beq @next
        ldx FX_ON
        beq @empty              ; no effects: the mailbox emptied
        and #MX_STOP | MX_START
        beq @vol
        jsr fx_chanvoice        ; a stop or a start: the channel's voice
        bcs :+                  ; stops
        lda #VF_ENDING
        sta FXV_BASE + V_FLAGS,x
:       lda SC_MAIL + MX_FLAGS,y
        and #MX_START
        beq @vol
        jsr fx_choose
        bcs @vol                ; every voice busy (more channels than voices)
        jsr fx_start
@vol:   lda SC_MAIL + MX_FLAGS,y
        and #MX_VOLUME
        beq @empty
        jsr fx_chanvoice
        bcs @empty
        jsr fx_volume
@empty: lda #0
        sta SC_MAIL + MX_FLAGS,y
@next:  iny
        iny
        iny
        iny
        cpy #NUM_CHANNELS * MAIL_SIZE
        bne @mail
        ldx #0                  ; the refills
@refill:
        lda FXV_BASE + V_FLAGS,x
        bpl :+
        jsr fx_refill
:       jsr fx_nextv
        bne @refill
        rts

; fx_nextv: X the next voice; Z set past the last. A kept.
fx_nextv:
        pha
        txa
        clc
        adc #VOICE_SIZE
        tax
        pla
        cpx #VOICES * VOICE_SIZE
        rts

; fx_chanvoice: X = the active voice of mailbox Y's channel, carry clear;
; carry set: none. Y kept.
fx_chanvoice:
        tya
        lsr a
        lsr a                   ; the channel
        ldx #0
@v:     bit FXV_BASE + V_FLAGS,x
        bpl @n
        cmp FXV_BASE + V_CHAN,x
        clc
        beq @r
@n:     jsr fx_nextv
        bne @v
        sec
@r:     rts

; fx_choose: the stereo rule (tools/sound/README.md "Stereo by voice";
; tables.fx_voice_order): a separation below 96 tries the left voice
; first, 96 to 160 the centre, above 160 the right; a busy voice falls
; back to the nearest free one in pan (the centre to the side the
; separation leans to, 128 to the left). Three comparisons make the
; band 0 (left), 1 (centre, left), 3 (centre, right) or 7 (right), its
; order's offset in fx_order. X = the voice, carry clear; carry set:
; every voice busy. Y = FXS_C after (the mailbox's offset: kept).
fx_choose:
        ldx SC_MAIL + MX_SEP,y
        lda #0
        cpx #FX_SEP_RIGHT + 1   ; carry: the right
        rol a
        cpx #FX_SEP_CENTRE + 1  ; carry: right of the centre
        rol a
        cpx #FX_SEP_LEFT        ; carry: not the left
        rol a
        tay
        sec                     ; none free: carry set
@try:   lda fx_order,y
        bmi @out
        iny
        tax
        lda FXV_BASE + V_FLAGS,x
        bmi @try
        clc
@out:   ldy FXS_C
        rts

; fx_start: mailbox Y's sound on the voice at X; the script's first
; bytes (its header with them) into the ring, the header taken. X, Y kept.
fx_start:
        tya
        lsr a
        lsr a
        sta FXV_BASE + V_CHAN,x
        lda SC_MAIL + MX_SOUND,y
        sta FXV_BASE + V_SOUND,x
        dec a                   ; its directory entry: (sound - 1) x 4
        asl a
        asl a
        sta fxc_ld + 1
        lda #>FX_DIR
        sta fxc_ld + 2
        txa                     ; into V_HEAD, V_LEFT
        clc
        adc #<(FXV_BASE + V_HEAD)
        sta fxc_st + 1
        lda #>FXV_BASE
        sta fxc_st + 2
        lda #4
        jsr fx_copy
        ldy FXS_C
        stz FXV_BASE + V_WPOS,x ; tone 0, attenuation 80, noise 0
        stz FXV_BASE + V_RPOS,x
        stz FXV_BASE + V_RUN,x
        stz FXV_BASE + V_PER,x
        stz FXV_BASE + V_PER + 1,x
        stz FXV_BASE + V_NOISE,x
        lda #ATT_SILENT
        sta FXV_BASE + V_LEVEL,x
        jsr fx_volume
        jsr fx_refill
        lda #4                  ; the header, taken
        sta FXV_BASE + V_RPOS,x
        lda #VF_ACTIVE          ; active last
        sta FXV_BASE + V_FLAGS,x
        rts

; fx_refill: the ring of the voice at X as full as its script allows, in
; at most two pieces (to the ring's end, then from its start), each
; published (V_WPOS) after its bytes. X kept; Y = FXS_C after.
fx_rfout:
        ldy FXS_C
        rts
fx_refill:
        jsr fx_piece
fx_piece:
        lda FXV_BASE + V_WPOS,x
        sec
        sbc FXV_BASE + V_RPOS,x ; unread
        eor #$FF
        clc
        adc #RING_SIZE + 1      ; free: 128 - unread
        beq fx_rfout
        sta FXS_P
        lda FXV_BASE + V_WPOS,x
        and #RING_SIZE - 1
        tay                     ; the first free byte's offset
        eor #RING_SIZE - 1
        inc a                   ; to the ring's end
        cmp FXS_P
        bcs :+
        sta FXS_P
:       lda FXV_BASE + V_LEFT + 1,x
        bne :+
        lda FXV_BASE + V_LEFT,x ; the script's end is nearer
        beq fx_rfout
        cmp FXS_P
        bcs :+
        sta FXS_P
:       txa                     ; the voice's ring: FX_RING + 128 x voice
        asl a
        asl a
        asl a
        sta fxc_st + 1
        lda #>FX_RING
        adc #0
        sta fxc_st + 2
        tya
        ora fxc_st + 1
        clc
        adc #<FX_RING
        sta fxc_st + 1
        bcc :+
        inc fxc_st + 2
:       lda FXV_BASE + V_HEAD,x
        sta fxc_ld + 1
        lda FXV_BASE + V_HEAD + 1,x
        sta fxc_ld + 2
        lda FXS_P
        jsr fx_copy
        lda FXS_P               ; V_HEAD += the piece
        clc
        adc FXV_BASE + V_HEAD,x
        sta FXV_BASE + V_HEAD,x
        bcc :+
        inc FXV_BASE + V_HEAD + 1,x
:       sec                     ; V_LEFT -= the piece
        lda FXV_BASE + V_LEFT,x
        sbc FXS_P
        sta FXV_BASE + V_LEFT,x
        bcs :+
        dec FXV_BASE + V_LEFT + 1,x
:       lda FXS_P               ; published: its bytes are in
        clc
        adc FXV_BASE + V_WPOS,x
        sta FXV_BASE + V_WPOS,x
        ldy FXS_C
        rts

; the stereo rule's orders, overlapping, read from a band's offset to the
; $FF (a voice met again is busy, so it changes nothing): from 0 the
; left's (L, C, R), from 1 the centre's leaning left (C, L, R), from 3
; the centre's leaning right (C, R, L), from 7 the right's (R, C, L)
FXO_L           = FX_VOICE_LEFT * VOICE_SIZE
FXO_C           = FX_VOICE_CENTRE * VOICE_SIZE
FXO_R           = FX_VOICE_RIGHT * VOICE_SIZE
fx_order:
        .byte FXO_L, FXO_C, FXO_L, FXO_C, FXO_R, FXO_L, FXO_R
        .byte FXO_R, FXO_C, FXO_L, $FF

.endif
