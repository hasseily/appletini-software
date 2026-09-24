.setcpu "65C02"

; Pinball Construction Set for the Appletini -- Phasor sound driver (slot 4).
; docs/DESIGN.md sections 2 and 10.
;
; Interface (every entry clobbers A, X and Y unless stated):
;   snd_init      Phasor to native mode, probe for the AY chips (4, or 2 on
;                 a Mockingboard), reset and silence them, set up the
;                 SSI-263. MB_SOUND = chip count.
;   snd_frame     once per video frame: one step of the effect engine, the
;                 AY registers that changed, one phoneme of the speech queue.
;   snd_shutdown  every chip silent and the speech chip powered down (a
;                 Phasor in native mode holds IRQ while a finished phoneme
;                 waits; ProDOS must not get that). Call before MLI QUIT.
;   snd_effect    A = an EFFECTS offset of RUN.S (0, 4, 12, 20, 36, 56, 76
;                 for noise 1..7): start that effect from its beginning,
;                 restarting it if it is playing. Other values, and any
;                 call while the sound is off (snd_mute or STGL): ignored.
;   snd_mute      A = 0 sound on, A = $80 sound off. Off drops the playing
;                 effect and the speech queue and ignores new ones; the
;                 silence itself is written by the next snd_frame, the
;                 earliest moment the card may be touched.
;   snd_speak     A = phrase 0..6: PLAYER ONE, PLAYER TWO, PLAYER THREE,
;                 PLAYER FOUR, GAME OVER, MULTIBALL, BONUS. Queued, at most
;                 three waiting, spoken one at a time; ignored while the
;                 sound is off. Needs the SSI-263 of a Phasor in native
;                 mode: on a Mockingboard it is ignored.
;   SND = SOUND, INITSND = INITSOUND: the upstream hooks (RUN.S SND/INITSND,
;                 RUN2.S SOUND/INITSOUND, WIRE.S SOUND/INITSOUND; the
;                 runtime calls SND every 4 ticks). They keep the original's
;                 SERIES/SLICE bookkeeping, which DOSND's priority rule
;                 depends on, start the effect at slice 0 and never touch
;                 the card. SND keeps X and Y (the runtime calls it inside
;                 loops).
;   STGL ($3E)    the upstream's sound toggle (RUN.S Ctrl-S flips it; the
;                 play shell keeps that code). Nothing else ever sets it,
;                 so snd_init clears it (sound on, the boot state the
;                 original relied on), and snd_frame honours bit 7 as a
;                 mute like snd_mute's: the effect sounding and the speech
;                 queue are dropped the frame after Ctrl-S, not only the
;                 series to come. The play shell needs no call of its own.
;
; Bus cost (an access of slot 4 slows the vTW to 1 MHz for 512 cycles, so
; every one of them is inside snd_init, snd_frame or snd_shutdown):
;   snd_init      312 accesses (174 on a Mockingboard), once.
;   snd_frame     a quiet frame costs 0 accesses (register shadows). An
;                 effect frame writes the AY registers that changed: at most
;                 8 (48 accesses) on its first frame, 0 to 7 afterwards. A
;                 speaking frame adds one SSI-263 read and at most one
;                 write (two the frame after a mute mid-phrase).
;   snd_shutdown  265 accesses (133 on a Mockingboard), once.
;
; Zero page: 2 bytes (snd_t0, snd_t1) reserved in ZEROPAGE, scratch of the
; period arithmetic only. All other state is in BSS.
;
; Hardware (appletini-one/hdl/apple/mockingboard.sv, as the Bilestoad and
; Bosconian drivers found it): an access to $C0C8 selects Mockingboard
; mode, then $C0C5 adds Phasor native mode. VIA-A answers at $C41x and
; VIA-B at $C48x in both modes. ORB bit 4 selects the first AY behind a
; VIA and bit 3 the second (active low), bit 2 is the AY reset line, bits
; 1-0 are BDIR/BC1. Native mode doubles the PSG clock (every period below
; is doubled there to keep its pitch) and puts the SSI-263 at $C440-$C444,
; where D7 of a read of $C440 reports the end of the phoneme. A plain
; Mockingboard ignores the mode switch and the chip-select bits: the probe
; sees its second-chip write land on the first chip and reports two chips
; (0 behind VIA-A, 2 behind VIA-B). AY data goes through ORA without
; handshake ($1F) because a plain ORA access clears the CA1 flag, the
; speech chip's request line on a Mockingboard.
;
; Time base: the port's frame loop runs at the SHR rate, one snd_frame per
; 1/60 s, so a call is one step. No VIA timer is read: reading one would
; cost two slot accesses on every quiet frame.
;
; Effects: the seven series of the original (RUN.S EFFECTS and NOTES, lines
; 2064-2079) are lists of NOTES rows, byte v = 12 * (row + 1), 0 ending
; the list. Row k is a speaker tone of roughly 1280 / (1 + 0.3k) Hz that
; the original clicks out in a 5 ms burst. Here row k is the AY period
; row_a[k]; a series plays its rows at a fixed number of frames per note
; on chip 0 with a volume envelope on voice A (quarter-volume units, so a
; decay can be slower than one step per frame), a partial on voice B (a
; twelfth above for chimes, an octave below for thumps) and a noise burst
; on voice C. The parameters of each effect are the fxp_* tables. From the
; last note on, the envelope decays at the effect's tail rate: every
; effect is silent again within 40 frames.

.include "pcs.inc"
.macpack longbranch

.export snd_init, snd_frame, snd_shutdown, snd_effect, snd_mute, snd_speak
.export SND, SOUND, INITSND, INITSOUND

; VIA register offsets from VIA_A / VIA_B
V_ORB       = $0
V_ORA       = $1
V_DDRB      = $2
V_DDRA      = $3
V_PCR       = $C
V_IFR       = $D
V_IER       = $E
V_ORANH     = $F                ; ORA without handshake

; SSI-263 register offsets from SSI_BASE
S_DUR       = 0
S_INF       = 1
S_RATE      = 2
S_CTL       = 3
S_FILT      = 4

AY_REGS     = 11                ; registers 0-10: tones, noise, mixer, volumes
MIX_ALL_OFF = $3F
MIX_FX      = $1C               ; tones A and B on, noise on C only
FX_CHIP     = 0                 ; the effect chip: first AY behind VIA-A
SP_QUEUE    = 3
SP_TIMEOUT  = 12                ; frames to wait for D7 (a 96 ms phoneme is 6)
PH_PA       = $00               ; pause phoneme: what the chip repeats when idle
PH_END      = $FF
F_RETRIG    = $80               ; fxp_flags: every note restarts the envelope
F_BRIGHT    = $01               ; voice B a twelfth above voice A
F_DEEP      = $02               ; voice B an octave below voice A

; SSI-263 phoneme length in bits 7-6: 100 %, 75 %, 50 % of the rate's
; 96 ms. Vowels get the full length, fricatives, nasals and liquids three
; quarters, stops and word gaps a half; a vowel written twice is held.
.define L4(c) (c)
.define L3(c) ((c) | $40)
.define L2(c) ((c) | $80)

; ---------------------------------------------------------------------------
.segment "ZEROPAGE"
snd_t0:     .res 1              ; set_tone: period high byte
snd_t1:     .res 1              ; note_start: NOTES row

; ---------------------------------------------------------------------------
.segment "BSS"
native:     .res 1              ; 1 = Phasor native mode: 4 chips, doubled clock, SSI-263
muted:      .res 1              ; $80 = sound off
ay_want:    .res AY_REGS        ; chip 0 as the engine wants it this frame
ay_shadow:  .res AY_REGS        ; chip 0 as it is
ay_chip:    .res 1
ay_reg:     .res 1
ay_val:     .res 1
; effect engine
fx_active:  .res 1
fx_pos:     .res 1              ; index of the next note in effects_tbl
fx_wait:    .res 1              ; frames before that note starts
fx_env:     .res 1              ; voice A envelope, quarter-volume units
fx_dec:     .res 1              ; its decrement per frame
fx_last:    .res 1              ; 1 once the last note has started
fx_nvol:    .res 1              ; noise volume
fx_ndec:    .res 1
fx_rate:    .res 1              ; frames per note
fx_peak:    .res 1              ; envelope at a note start (quarter units)
fx_tail:    .res 1              ; decrement from the last note on
fx_flags:   .res 1
fx_bdrop:   .res 1              ; voice B is this much quieter than A
; speech
sp_active:  .res 1              ; a phrase is being spoken
sp_sent:    .res 1              ; a phoneme of it is in the chip
sp_pos:     .res 1              ; index of the next phoneme in phrases
sp_timer:   .res 1              ; frames left before giving up on D7
sp_stop:    .res 1              ; muted mid-phrase: leave the chip a pause
sp_count:   .res 1
sp_queue:   .res SP_QUEUE

; ---------------------------------------------------------------------------
.segment "RODATA"
; ORB values by chip select: first AY behind the VIA, second AY
sel_latch:  .byte $0F, $17      ; BDIR=1 BC1=1: latch the register address
sel_write:  .byte $0E, $16      ; BDIR=1 BC1=0: write data
sel_idle:   .byte $0C, $14      ; inactive, reset line high

; The original's EFFECTS table, byte for byte (RUN.S 2064-2070): the SND
; hook walks it exactly as the original did, so a series lasts the same
; number of slices, and the effect engine takes its pitch contour from it.
effects_tbl:
    .byte $54,$0C,$54,$00                                   ; 0: tick
    .byte $0C,$18,$24,$30,$3C,$48,$54,$00                   ; 4: falling sweep
    .byte $54,$48,$3C,$30,$24,$18,$0C,$00                   ; 12: rising sweep
    .byte $54,$0C,$54,$0C,$54,$0C,$54,$0C                   ; 20: alternating,
    .byte $0C,$24,$3C,$54,$54,$3C,$24,$00                   ;     then down and up
    .byte $0C,$18,$24,$30,$3C,$48,$54,$48,$3C,$30           ; 36: falling,
    .byte $3C,$48,$3C,$30,$3C,$48,$3C,$30,$3C,$00           ;     then a warble
    .byte $0C,$18,$24,$30,$3C,$48,$54,$54,$48,$3C           ; 56: down, up,
    .byte $30,$24,$18,$0C,$18,$24,$30,$3C,$48,$00           ;     down again
    .byte $0C,$18,$24,$30,$0C,$18,$24,$30,$0C,$18           ; 76: four runs
    .byte $24,$30,$0C,$18,$24,$30,$0C,$18,$24,$00           ;     of four notes

; NOTES row k -> AY tone period at the 1.02 MHz clock, period = 50 + 15k:
; 1278, 983, 799, 673, 581, 511, 457 Hz. row_b is a twelfth above.
row_a:      .byte 50, 65, 80, 95, 110, 125, 140
row_b:      .byte 17, 22, 27, 32, 37, 42, 47

; Effect parameters, one column per effect (noise 1..7):
;   1 tick: three quick bright chimes with a click
;   2 bumper thump: one envelope sliding down through seven pitches over a
;     noise burst, an octave partial for body
;   3 rising run of chimes
;   4 two alternating bells, then a run down and up
;   5 a smooth fall into a slow wobble (continuous envelope)
;   6 chime arpeggio down, up and down
;   7 four repeated four-note runs with a deep partial
fxp_code:   .byte   0,   4,  12,  20,  36,  56,  76     ; EFFECTS offset
fxp_rate:   .byte   4,   3,   3,   2,   2,   2,   2     ; frames per note
fxp_peak:   .byte  60,  60,  52,  60,  60,  56,  60     ; volume * 4
fxp_dec:    .byte  12,   2,   6,   8,   1,   8,  10     ; per frame, * 1/4
fxp_tail:   .byte  16,   8,   6,   8,  16,  20,  20     ; from the last note on
fxp_flags:  .byte F_RETRIG|F_BRIGHT, F_DEEP, F_RETRIG|F_BRIGHT
            .byte F_RETRIG|F_BRIGHT, F_BRIGHT, F_RETRIG|F_BRIGHT
            .byte F_RETRIG|F_DEEP
fxp_bdrop:  .byte   3,   2,   4,   3,   5,   4,   2     ; voice B = A - this
fxp_nvol:   .byte   8,  15,   0,   0,   0,   0,   0     ; noise burst volume
fxp_ndec:   .byte   8,   3,   0,   0,   0,   0,   0     ; its decrement per frame
fxp_nper:   .byte   2,  15,   0,   0,   0,   0,   0     ; noise period (1 MHz clock)

; SSI-263 phrases: P L AY ER, W UH N / T U U / TH R E E / F O R,
; KV AY AY M - O O V ER ER, M UH L T I - B AW L, B O N UH S.
phrases:
ph_p1:  .byte L2($27),L3($20),L4($05),L3($1C),L2(PH_PA)
        .byte L3($23),L4($18),L3($38),PH_END
ph_p2:  .byte L2($27),L3($20),L4($05),L3($1C),L2(PH_PA)
        .byte L2($28),L4($16),L4($16),PH_END
ph_p3:  .byte L2($27),L3($20),L4($05),L3($1C),L2(PH_PA)
        .byte L3($36),L3($1D),L4($01),L4($01),PH_END
ph_p4:  .byte L2($27),L3($20),L4($05),L3($1C),L2(PH_PA)
        .byte L3($34),L4($11),L4($1D),PH_END
ph_go:  .byte L2($26),L4($05),L4($05),L3($37),L3(PH_PA)
        .byte L4($11),L4($11),L3($33),L4($1C),L4($1C),PH_END
ph_mb:  .byte L3($37),L4($18),L3($20),L2($28),L3($07),L2(PH_PA)
        .byte L2($24),L4($10),L3($20),PH_END
ph_bo:  .byte L2($24),L4($11),L3($38),L3($18),L3($30),PH_END
phrase_start:
        .byte ph_p1-phrases, ph_p2-phrases, ph_p3-phrases, ph_p4-phrases
        .byte ph_go-phrases, ph_mb-phrases, ph_bo-phrases

; ---------------------------------------------------------------------------
.segment "CODE"

; ---- init -----------------------------------------------------------------
snd_init:
    bit PHASOR_MB
    bit PHASOR_NATIVE
    ; VIAs: no interrupt source, CA1 on a negative edge, flags cleared
    lda #$7F
    sta VIA_A+V_IER
    stz VIA_A+V_PCR
    sta VIA_A+V_IFR
    sta VIA_B+V_IER
    stz VIA_B+V_PCR
    sta VIA_B+V_IFR
    ; port pins to the AYs, then a reset pulse (ORB bit 2 low) on each VIA:
    ; every register of every chip reads 0 afterwards
    lda #$FF
    sta VIA_A+V_DDRA
    lda #$1F
    sta VIA_A+V_DDRB
    stz VIA_A+V_ORB
    lda #$0C
    sta VIA_A+V_ORB
    lda #$FF
    sta VIA_B+V_DDRA
    lda #$1F
    sta VIA_B+V_DDRB
    stz VIA_B+V_ORB
    lda #$0C
    sta VIA_B+V_ORB
    ; Probe: register 0 of chip 0 = $55 and of chip 1 = $AA, then chip 0
    ; read back. $AA means the second write landed on the first chip: a
    ; Mockingboard. ay_write reaches chip 1 only while native is set.
    lda #1
    sta native
    ldx #0
    ldy #0
    lda #$55
    jsr ay_write
    ldx #1
    lda #$AA
    jsr ay_write
    stz VIA_A+V_ORANH           ; latch register 0 of chip 0
    lda #$0F
    sta VIA_A+V_ORB
    lda #$0C
    sta VIA_A+V_ORB
    stz VIA_A+V_DDRA            ; port A as input, BDIR=0 BC1=1: read
    lda #$0D
    sta VIA_A+V_ORB
    lda VIA_A+V_ORANH
    pha
    lda #$0C
    sta VIA_A+V_ORB
    lda #$FF
    sta VIA_A+V_DDRA
    pla
    cmp #$AA
    bne :+
    stz native
:   lda #4
    ldx native
    bne :+
    lda #2
:   sta MB_SOUND
    ldx native
    beq @chips
    ; the speech chip: control mode, mode bits, inflection, rate $A,
    ; then articulation/amplitude with control off, filter
    lda #$80
    sta SSI_BASE+S_CTL
    lda #$C0
    sta SSI_BASE+S_DUR
    lda #$40
    sta SSI_BASE+S_INF
    lda #$A8
    sta SSI_BASE+S_RATE
    lda #$5A
    sta SSI_BASE+S_CTL
    lda #$E8
    sta SSI_BASE+S_FILT
@chips:
    jsr ay_reset_all            ; every chip: registers 0-10 zero, mixer off
    jsr state_clear             ; want = shadow = silence
    lda #MIX_FX
    sta ay_want+7               ; chip 0 gets its mixer: the one write of ay_flush
    stz muted
    stz STGL                    ; sound on: nobody else initialises the toggle
    jmp ay_flush

; The engine state at rest with chip 0's want and shadow both silence
; (registers 0-10 zero, mixer off), as ay_reset_all leaves the chip.
state_clear:
    ldx #AY_REGS-1
:   stz ay_want,x
    stz ay_shadow,x
    dex
    bpl :-
    lda #MIX_ALL_OFF
    sta ay_want+7
    sta ay_shadow+7
    stz fx_active
    stz sp_active
    stz sp_sent
    stz sp_stop
    stz sp_count
    rts

; Every chip the card has: registers 0-10 written, mixer all off. Chips 1
; and 3 are skipped by ay_write on a Mockingboard.
ay_reset_all:
    ldx #3
@chip:
    ldy #0
@reg:
    lda #0
    cpy #7
    bne :+
    lda #MIX_ALL_OFF
:   jsr ay_write
    iny
    cpy #AY_REGS
    bne @reg
    dex
    bpl @chip
    rts

; ---- shutdown -------------------------------------------------------------
snd_shutdown:
    jsr ay_reset_all
    jsr state_clear
    lda #$80
    sta SSI_BASE+S_CTL          ; speech chip powered down: no request pending
    rts

; ---- frame ----------------------------------------------------------------
snd_frame:
    bit STGL
    bpl :+
    jsr snd_stop                ; Ctrl-S: nothing may sound while it is set
:   jsr fx_step
    jsr ay_flush
    jmp sp_step

; ---- AY access ------------------------------------------------------------
; Chip 0: write every register whose wanted value differs from the shadow,
; periods before volumes so a new note never sounds at the old pitch.
ay_flush:
    ldy #0
@reg:
    lda ay_want,y
    cmp ay_shadow,y
    beq @next
    sta ay_shadow,y
    ldx #FX_CHIP
    jsr ay_write
@next:
    iny
    cpy #AY_REGS
    bne @reg
    rts

; X = chip 0-3, Y = register, A = value. Keeps A, X and Y. Six accesses:
; ORA=reg, ORB=latch, ORB=idle, ORA=value, ORB=write, ORB=idle.
ay_write:
    sta ay_val
    stx ay_chip
    sty ay_reg
    txa
    and #1
    beq :+
    lda native
    beq @done                   ; a Mockingboard has no second chip
    lda #1
:   tay                         ; Y = 0 first AY of the VIA, 1 second
    cpx #2
    bcs @via_b
    lda ay_reg
    sta VIA_A+V_ORANH
    lda sel_latch,y
    sta VIA_A+V_ORB
    lda sel_idle,y
    sta VIA_A+V_ORB
    lda ay_val
    sta VIA_A+V_ORANH
    lda sel_write,y
    sta VIA_A+V_ORB
    lda sel_idle,y
    sta VIA_A+V_ORB
    bra @done
@via_b:
    lda ay_reg
    sta VIA_B+V_ORANH
    lda sel_latch,y
    sta VIA_B+V_ORB
    lda sel_idle,y
    sta VIA_B+V_ORB
    lda ay_val
    sta VIA_B+V_ORANH
    lda sel_write,y
    sta VIA_B+V_ORB
    lda sel_idle,y
    sta VIA_B+V_ORB
@done:
    ldx ay_chip
    ldy ay_reg
    lda ay_val
    rts

; ---- effects --------------------------------------------------------------
; A = EFFECTS offset. The effect starts sounding on the next snd_frame.
snd_effect:
    bit muted
    bmi @rts
    bit STGL
    bmi @rts
    ldx #6
:   cmp fxp_code,x
    beq @found
    dex
    bpl :-
@rts:
    rts
@found:
    sta fx_pos                  ; the series starts at its EFFECTS offset
    lda fxp_rate,x
    sta fx_rate
    lda fxp_peak,x
    sta fx_peak
    sta fx_env                  ; a continuous envelope starts at the peak too
    lda fxp_dec,x
    sta fx_dec
    lda fxp_tail,x
    sta fx_tail
    lda fxp_flags,x
    sta fx_flags
    lda fxp_bdrop,x
    sta fx_bdrop
    lda fxp_ndec,x
    sta fx_ndec
    lda fxp_nvol,x
    sta fx_nvol
    beq @nonoise                ; no burst: the noise period is not worth a write
    lda fxp_nper,x
    ldx native
    beq :+
    asl                         ; doubled clock: keep the noise colour
    cmp #32
    bcc :+
    lda #31
:   sta ay_want+6
@nonoise:
    stz fx_wait
    stz fx_last
    lda #1
    sta fx_active
    rts

; One frame of the effect: start the note that is due, set the three
; volumes from the envelopes, then decay them for the next frame.
fx_step:
    lda fx_active
    beq @silent
    lda fx_wait
    beq @note
    dec fx_wait
    bra @vol
@note:
    ldx fx_pos
    lda effects_tbl,x
    beq @vol                    ; the list is over: only the tail runs
    inc fx_pos
    jsr note_start
    ldx fx_rate
    dex
    stx fx_wait
@vol:
    lda fx_env
    lsr
    lsr
    sta ay_want+8               ; voice A
    tay
    lda fx_flags
    and #F_BRIGHT|F_DEEP
    beq @b_done                 ; no partial: voice B silent (A = 0)
    tya
    sec
    sbc fx_bdrop                ; voice B: quieter than A
    bcs @b_done
    lda #0
@b_done:
    sta ay_want+9
    lda fx_nvol
    sta ay_want+10              ; voice C: noise
    lda fx_last
    beq @decay
    tya
    ora fx_nvol
    bne @decay
    stz fx_active               ; the last note has faded: done
    rts
@decay:
    lda fx_env
    sec
    sbc fx_dec
    bcs :+
    lda #0
:   sta fx_env
    lda fx_nvol
    sec
    sbc fx_ndec
    bcs :+
    lda #0
:   sta fx_nvol
    rts
@silent:
    stz ay_want+8
    stz ay_want+9
    stz ay_want+10
    rts

; A = a NOTES byte (12 * (row + 1)): voice A and B periods of that row,
; the envelope restarted if the effect retriggers, the tail rate armed if
; this is the last note of the list.
note_start:
    ldx #0
@row:
    sec
    sbc #12
    beq @found
    inx
    cpx #6
    bcc @row                    ; a stray value plays the lowest row
@found:
    stx snd_t1
    lda row_a,x
    ldx native
    ldy #0
    jsr set_tone
    ldx snd_t1
    lda fx_flags
    and #F_BRIGHT|F_DEEP
    beq @nob
    cmp #F_DEEP
    beq @deep
    lda row_b,x
    ldx native
    bra @setb
@deep:
    lda row_a,x
    ldx native
    inx                         ; one more doubling: an octave below
@setb:
    ldy #2
    jsr set_tone
@nob:
    bit fx_flags
    bpl :+                      ; F_RETRIG
    lda fx_peak
    sta fx_env
:   ldx fx_pos
    lda effects_tbl,x
    bne :+
    lda fx_tail
    sta fx_dec
    lda #1
    sta fx_last
:   rts

; A = 8-bit period, X = doublings (native mode, octave below), Y = tone
; register (0 voice A, 2 voice B): the 16-bit period into ay_want.
set_tone:
    stz snd_t0
@dbl:
    cpx #0
    beq @out
    asl
    rol snd_t0
    dex
    bra @dbl
@out:
    sta ay_want,y
    lda snd_t0
    sta ay_want+1,y
    rts

; ---- mute -----------------------------------------------------------------
snd_mute:
    and #$80
    sta muted
    bne snd_stop
    rts

; Drop the effect sounding and the speech queue (snd_mute off, STGL set).
; The zero volumes, and a pause to the speech chip if it is mid-phrase,
; go out with the next fx_step / sp_step: the earliest legal moment.
snd_stop:
    stz fx_active
    stz sp_count
    lda sp_active
    beq @rts
    stz sp_active
    stz sp_sent
    lda #1
    sta sp_stop
@rts:
    rts

; ---- speech ---------------------------------------------------------------
; A = phrase 0..6. Native mode only: on a Mockingboard $C44x is VIA-A.
snd_speak:
    bit muted
    bmi @rts
    bit STGL
    bmi @rts
    ldx native
    beq @rts
    cmp #7
    bcs @rts
    ldx sp_count
    cpx #SP_QUEUE
    bcs @rts                    ; full: dropped
    sta sp_queue,x
    inc sp_count
@rts:
    rts

; One frame of speech. The chip repeats the phoneme it holds until the
; next arrives, so each frame looks at D7 and sends the next phoneme when
; the current one is done, or after SP_TIMEOUT frames if the chip never
; answers. A phrase ends with a pause, which the chip repeats silently.
sp_step:
    lda sp_stop
    beq :+
    stz sp_stop
    lda #PH_PA
    sta SSI_BASE+S_DUR
:   lda sp_active
    bne @run
    lda sp_count
    beq @rts
    ldx sp_queue                ; pop the head of the queue
    lda sp_queue+1
    sta sp_queue
    lda sp_queue+2
    sta sp_queue+1
    dec sp_count
    lda phrase_start,x
    sta sp_pos
    lda #1
    sta sp_active
    stz sp_sent
@run:
    lda sp_sent
    beq @send
    lda SSI_BASE+S_DUR          ; D7: the phoneme is finished
    bmi @send
    lda sp_timer
    beq @send                   ; no answer: a card without the chip
    dec sp_timer
@rts:
    rts
@send:
    ldx sp_pos
    lda phrases,x
    cmp #PH_END
    beq @end
    inc sp_pos
    sta SSI_BASE+S_DUR
    lda #1
    sta sp_sent
    lda #SP_TIMEOUT
    sta sp_timer
    rts
@end:
    lda #PH_PA
    sta SSI_BASE+S_DUR
    stz sp_active
    stz sp_sent
    rts

; ---- upstream hooks -------------------------------------------------------
; RUN.S SND (2035-2062) without the speaker loop: STGL bit 7 or a negative
; SERIES = nothing to do; slice 0 starts the effect; the slice count then
; advances and, as in the original, the series ends when the EFFECTS byte
; after the current one is 0 (3 slices for code 0, 7 for 4 and 12, 15 for
; 20, 19 for 36, 56 and 76). No hardware here: snd_frame does the writing.
SND:
SOUND:
    bit STGL
    bmi @rts
    lda SERIES
    bmi @rts
    phx
    phy
    ldx SLICE
    bne :+
    jsr snd_effect              ; A = SERIES
:   inc SLICE
    clc
    lda SERIES
    adc SLICE
    tax
    lda effects_tbl,x
    bne :+
    jsr INITSND
:   ply
    plx
@rts:
    rts

INITSND:
INITSOUND:
    lda #$FF
    sta SERIES
    stz SLICE
    rts
