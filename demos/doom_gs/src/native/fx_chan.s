; fx_chan.s: the sound channel logic (milestone 11, part fxchan; sound
; track S4). A GPL-2 derivative of upstream's s_sound65.s: S_StartSound,
; S_StartSound2, sameOrigin, getChannel, priority, stopChannel,
; S_StopSound, S_UpdateSounds and S_AdjustSoundParams with units,
; mulLong, divAtt and absDelta [R build/upstream/src/iigs/s_sound65.s:
; 177-670], the priority table read from its sfxPriority [R :1274-1285]
; by tools/sound/fxchan.py into the generated fxchan.inc. The DOC is gone:
; every decision lands in its channel's mailbox, latest wins (docs/
; SCREENS.md 3; tools/sound/README.md "The game side"), and fxplay's
; fx_isplaying answers isPlaying (the channel's voice active or a start in
; its mailbox). tools/sound/fxchan.py is the host model.
;
; A tic-side module (docs/SCREENS.md 4.7; GAME.md 4.4's conventions):
;
;   sc_start    S_StartSound. GA+0-1 the sound (upstream's word, with
;               PICKUP_SOUND $8000), GA+2 the origin's kind (ORG_NONE,
;               ORG_MOBJ, ORG_PLAYER: the player's mobj), GA+3-4 its
;               handle (a mobj slot; $FFFF for ORG_NONE), GA+5-8
;               and GA+9-12 its x and y (fixed point; ORG_MOBJ)
;   sc_start2   S_StartSound2: GA+0-1 the sound, GA+5-12 the point's x, y
;               (a sector's sound origin): the one fake mobj FM
;   sc_stop     S_StopSound: GA+2 the kind, GA+3-4 the handle
;   sc_update   S_UpdateSounds, once a frame after the tics (or in a menu's
;               paused frame); nothing when there is no listener (musFrame
;               calls it only when the player has a mobj)
;
; It calls s2t_pos (A:X a handle, A the high byte: its x, y, angle into
; GT+0-11, carry clear; carry set: none; the handle FXC_LISTENER is the
; listener, the player's mobj), fx_isplaying (X a channel: carry set when
; it plays; X kept) and the math (mul32, sdiv32; pta3 and sineapprox for
; the separation). Zero page: GA (read at the start), GT, the math block.
; Its own bytes: the 32-byte scratch block fxc_scr (imported: each image
; places it), the card's channel table and mailboxes (SC_BASE, SC_MAIL),
; FM_X/FM_Y and the listener's last position LS_X/LS_Y/LS_ANGLE (the
; positions MENUW's fx_pcache answers from), LS_ON, SND_SFXVOL.
;
; -D FXC_NOSEP (MENUW's build): S_AdjustSoundParams without the
; separation. MENUW's starts have no origin (the menu's sounds) and an
; update's separation reaches no mailbox (the side is chosen at the start:
; fx_service uses only a volume), so MENUW links neither pta3 nor
; sineapprox, which its W block does not hold (docs/m11-parts/fxchan.md).

        .setcpu "65C02"
        .include "s2.inc"
        .include "math.inc"
        .include "fxchan.inc"

        .import s2t_pos, fx_isplaying, fxc_scr
        .import mul32, sdiv32
.ifndef FXC_NOSEP
        .import pta3, sineapprox
.endif
.ifdef FXC_TRACE
        .import fxc_trace
.endif
        .export sc_start, sc_start2, sc_stop, sc_update
        .export fxc_prio

NORM_SEP = 128

; -D FXC_TRACE (the test machines only): each adjust's channel, SS_VOL,
; SS_SEP and audibility to the driver's trace (fxc_trace keeps A, X, Y, P)
.macro TRACE
.ifdef FXC_TRACE
        jsr fxc_trace
.endif
.endmacro

; the arguments
A_SFX   = FXC_GA + 0            ; 2
A_KIND  = FXC_GA + 2            ; then the handle (2), x (4), y (4)
A_HND   = FXC_GA + 3
A_X     = FXC_GA + 5
; the temporaries of S_AdjustSoundParams
Z_D     = FXC_GT + 0            ; adx, then the distance (4)
Z_T     = FXC_GT + 4            ; ady (4)
Z_ANG   = FXC_GT + 8            ; the min (4)

; the scratch block (S_KIND to S_SX + 7 in the arguments' order)
S_SFX   = fxc_scr + 0           ; the sound, 1-52
S_PICK  = fxc_scr + 1           ; CHF_PICKUP or 0
S_KIND  = fxc_scr + 2           ; the origin's kind
S_HND   = fxc_scr + 3           ; its handle ($FFFF for none and FM)
S_SX    = fxc_scr + 5           ; the source's x, then y (8)
S_VOL   = fxc_scr + 13          ; SS_VOL (2)
S_SEP   = fxc_scr + 15          ; SS_SEP (2)
S_C     = fxc_scr + 17          ; a channel
S_CO    = fxc_scr + 18          ; its record's offset
S_AUD   = fxc_scr + 19          ; the last adjust: 1 audible
S_PR    = fxc_scr + 20          ; the new sound's priority
S_U     = fxc_scr + 21          ; units (2)
FXC_SCR_USED = 23

        .assert FM_Y = FM_X + 4, error, "FM's x, y"
        .assert LS_Y = LS_X + 4 && LS_ANGLE = LS_Y + 4, error, "LS"
        .assert CH_X = CH_HANDLE + 2 && CH_Y = CH_X + 4, error, "a record"
        .assert NUM_CHANNELS * CHAN_SIZE < 256, error, "the table"
        .assert Z_T = Z_D + 4, error, "absd"

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; sc_start2: S_StartSound2: FM takes the point; then S_StartSound with FM
; as the origin, so every sound of sc_start2 has the same origin [R
; s_sound65.s:185-198]
; ---------------------------------------------------------------------------
sc_start2:
        ldx #7
:       lda A_X,x
        sta FM_X,x
        dex
        bpl :-
        lda #ORG_FM
        sta A_KIND
        lda #$FF
        sta A_HND
        sta A_HND+1

; ---------------------------------------------------------------------------
; sc_start: S_StartSound [R :199-272]
; ---------------------------------------------------------------------------
sc_start:
        ldy #0                  ; is_pickup: PICKUP_SOUND, oof, noway
        lda A_SFX+1
        bmi @pick
        lda A_SFX
        cmp #FXC_OOF
        beq @pick
        cmp #FXC_NOWAY
        bne @nopk
@pick:  ldy #CHF_PICKUP
@nopk:  sty S_PICK
        lda A_SFX+1             ; sfx_None < id < NUMSFX (upstream:
        and #$7F                ;   I_Error; here no sound)
        bne @rts
        lda A_SFX
        beq @rts
        cmp #FXC_NUMSFX
        bcs @rts
        sta S_SFX
        jsr origin
        lda #NORM_SEP           ; sep = NORM_SEP
        sta S_SEP
        stz S_SEP+1
        lda S_KIND              ; no origin or the player: volume * 8
        cmp #ORG_MOBJ
        beq @adj
        cmp #ORG_FM
        beq @adj
        jsr fullvol
        bra @kill
@adj:   jsr getlis              ; else the params, or not audible
        bcs @rts
        jsr adjust
        TRACE
        bcc @rts
@kill:  jsr first               ; kill the old sound of the origin (the
@k1:    lda SC_BASE+CH_SFX,x    ;   same kind of sound)
        beq @k2
        jsr samep
        bne @k2
        jsr stopch
        bra @get
@k2:    jsr next
        bcc @k1
@get:   jsr getch               ; a channel, or none
        bcc @rts
        jsr mbox                ; I_StartSound: the mailbox's start
        ora #MX_START
        sta SC_MAIL+MX_FLAGS,y
        lda S_SFX
        sta SC_MAIL+MX_SOUND,y
        lda S_VOL
        sta SC_MAIL+MX_VOL,y
        lda S_SEP
        sta SC_MAIL+MX_SEP,y
@rts:   rts

; origin: the origin's kind, handle and position from the arguments
origin:
        ldx #10
:       lda A_KIND,x
        sta S_KIND,x
        dex
        bpl :-
        rts

; ---------------------------------------------------------------------------
; getChannel [R :284-334]: the first free channel, or before it a channel
; of the same origin and kind (stopped); none: the first channel whose
; priority is not lower (a number not below the new sound's), stopped.
; Carry set and X the record (S_C the channel) with the sound, origin,
; kind and the source's position set; carry clear: none.
; ---------------------------------------------------------------------------
getch:
        jsr first
@g1:    lda SC_BASE+CH_SFX,x
        beq @take               ; free
        lda S_KIND              ; the same origin and kind: stopped
        beq @g2
        jsr samep
        bne @g2
        jsr stopch
        bra @take
@g2:    jsr next
        bcc @g1
        ldy S_SFX               ; none free: priority[c] >= priority
        lda fxc_prio,y
        sta S_PR
        jsr first
@g3:    ldy SC_BASE+CH_SFX,x
        lda fxc_prio,y
        cmp S_PR
        bcs @evict
        jsr next
        bcc @g3
        clc                     ; no lower priority
        rts
@evict: jsr stopch
@take:  lda S_SFX               ; the channel is decided
        sta SC_BASE+CH_SFX,x
        lda S_KIND
        ora S_PICK
        sta SC_BASE+CH_KIND,x
        phx                     ; the handle, the origin's last position
        ldy #0
:       lda S_HND,y
        sta SC_BASE+CH_HANDLE,x
        inx
        iny
        cpy #10
        bne :-
        plx
        sec
        rts

; samep: Z set if the record X has the origin S_KIND, S_HND and the
; pickup flag S_PICK; same: the origin only (sameOrigin [R :274-282])
samep:
        jsr same
        bne @r
        lda SC_BASE+CH_KIND,x
        and #CHF_PICKUP
        cmp S_PICK
@r:     rts
same:
        lda SC_BASE+CH_KIND,x
        and #CHF_KIND
        cmp S_KIND
        bne @r
        lda SC_BASE+CH_HANDLE,x
        cmp S_HND
        bne @r
        lda SC_BASE+CH_HANDLE+1,x
        cmp S_HND+1
@r:     rts

; first: X the first record, S_C 0. next: the next; carry set after the
; last
first:
        ldx #0
        stz S_C
        rts
next:
        txa
        clc
        adc #CHAN_SIZE
        tax
        inc S_C
        lda S_C
        cmp #NUM_CHANNELS
        rts

; mbox: Y the mailbox of S_C, A its flags
mbox:
        lda S_C
        asl a
        asl a
        tay
        lda SC_MAIL+MX_FLAGS,y
        rts

; ---------------------------------------------------------------------------
; stopChannel [R :344-355]: a channel with a sound is free and its
; mailbox stops it (stop set; start and volume cleared). X kept.
; ---------------------------------------------------------------------------
stopch:
        lda SC_BASE+CH_SFX,x
        beq @r
        stz SC_BASE+CH_SFX,x
        jsr mbox
        and #<~(MX_START | MX_VOLUME)
        ora #MX_STOP
        sta SC_MAIL+MX_FLAGS,y
@r:     rts

; ---------------------------------------------------------------------------
; sc_stop: S_StopSound [R :360-376]: the first channel of the origin stops
; ---------------------------------------------------------------------------
sc_stop:
        jsr origin
        jsr first
@s1:    lda SC_BASE+CH_SFX,x
        beq @s2
        jsr same
        bne @s2
        jmp stopch
@s2:    jsr next
        bcc @s1
        rts

; ---------------------------------------------------------------------------
; sc_update: S_UpdateSounds [R :383-423]: a channel whose sound ended is
; free; the other sounds (not of the player) get the volume of the new
; positions, or stop when not audible
; ---------------------------------------------------------------------------
sc_update:
        jsr getlis
        bcs @rts
        jsr first
@u1:    stx S_CO
        jsr upd1
        ldx S_CO
        jsr next
        bcc @u1
@rts:   rts

; upd1: the channel S_C (its record S_CO, in X)
upd1:
        lda SC_BASE+CH_SFX,x
        beq @r
        ldx S_C
        jsr fx_isplaying
        ldx S_CO
        bcs @play
        jmp stopch              ; ended
@play:  lda SC_BASE+CH_KIND,x   ; an origin, not the player
        and #CHF_KIND
        cmp #ORG_FM
        beq @fm
        cmp #ORG_MOBJ
        bne @r
        lda SC_BASE+CH_HANDLE+1,x
        pha
        lda SC_BASE+CH_HANDLE,x
        tax
        pla
        jsr s2t_pos
        ldx S_CO
        ldy #0                  ; the source, and its last position
:       lda FXC_GT,y
        sta S_SX,y
        sta SC_BASE+CH_X,x
        inx
        iny
        cpy #8
        bne :-
        bra @adj
@fm:    ldy #7
:       lda FM_X,y
        sta S_SX,y
        dey
        bpl :-
@adj:   lda #NORM_SEP           ; sep (the volume: adjust's)
        sta S_SEP
        stz S_SEP+1
        jsr adjust
        TRACE
        ldx S_CO
        bcs @vol
        jmp stopch              ; not audible
@vol:   jsr mbox                ; I_UpdateSoundParams: the volume
        ora #MX_VOLUME
        sta SC_MAIL+MX_FLAGS,y
        lda S_VOL
        sta SC_MAIL+MX_VOL,y
@r:     rts

; getlis: the listener (the player's mobj) through s2t_pos into LS_X,
; LS_Y, LS_ANGLE and LS_ON; carry set: none
getlis:
        lda #>FXC_LISTENER
        ldx #<FXC_LISTENER
        jsr s2t_pos
        bcs @none
        ldx #11
:       lda FXC_GT,x
        sta LS_X,x
        dex
        bpl :-
        lda #$80
        sta LS_ON
        clc
        rts
@none:  stz LS_ON
        rts

; fullvol: S_VOL = snd_SfxVolume * 8
fullvol:
        stz S_VOL+1
        lda SND_SFXVOL
        asl a
        rol S_VOL+1
        asl a
        rol S_VOL+1
        asl a
        rol S_VOL+1
        sta S_VOL
        rts

; ---------------------------------------------------------------------------
; adjust: S_AdjustSoundParams(the listener LS_*, the source S_SX, S_SY,
; S_VOL, S_SEP) [R :425-618]: the separation from the angle of the
; source to the view, the volume from its distance (full within
; S_CLOSE_DIST, none beyond S_CLIPPING_DIST except on map 8). Carry set
; and S_AUD 1 if audible.
; ---------------------------------------------------------------------------
adjust:
        stz S_AUD
        ldx #0                  ; adx, ady (absDelta)
        jsr absd
        jsr absd
        ldx #4                  ; approx_dist = adx + ady - (min >> 1):
        lda Z_D                 ;   adx < ady (signed): adx is the min
        cmp Z_T
        lda Z_D+1
        sbc Z_T+1
        lda Z_D+2
        sbc Z_T+2
        lda Z_D+3
        sbc Z_T+3
        bvc :+
        eor #$80
:       bpl :+
        ldx #0
:       lda Z_D+3,x             ; min >> 1 (arithmetic)
        cmp #$80
        ror a
        sta Z_ANG+3
        lda Z_D+2,x
        ror a
        sta Z_ANG+2
        lda Z_D+1,x
        ror a
        sta Z_ANG+1
        lda Z_D,x
        ror a
        sta Z_ANG
        clc                     ; adx + ady - that
        ldx #$FC
:       lda Z_D+4,x
        adc Z_T+4,x
        sta Z_D+4,x
        inx
        bne :-
        sec
        ldx #$FC
:       lda Z_D+4,x
        sbc Z_ANG+4,x
        sta Z_D+4,x
        inx
        bne :-
        lda Z_D                 ; zero distance: full volume
        ora Z_D+1
        ora Z_D+2
        ora Z_D+3
        bne :+
        jmp @full
:       jsr clipd               ; S_CLIPPING_DIST < dist (signed): not
        bvc :+                  ;   audible (except on map 8); units
        eor #$80
:       bpl @near
        jsr map8
        beq @near
        clc
        rts
@near:
.ifndef FXC_NOSEP
        ; the angle of the source from the view: R_PointToAngle2(listener,
        ; source), less 1 when it is not more than the view angle, less
        ; the view angle
        ldx #0                  ; M_A = dx, M_B = dy
@dxy:   txa
        and #3
        bne :+
        sec
:       lda S_SX,x
        sbc LS_X,x
        sta M_A,x
        inx
        txa
        eor #8
        bne @dxy
        jsr pta3
        lda LS_ANGLE            ; angle <= listener->angle: - 1, as a
        cmp M_R                 ;   borrow into the difference
        lda LS_ANGLE+1
        sbc M_R+1
        lda LS_ANGLE+2
        sbc M_R+2
        lda LS_ANGLE+3
        sbc M_R+3
        lda #0
        rol a
        eor #1
        lsr a
        lda M_R                 ; (angle - listener->angle) >> 19
        sbc LS_ANGLE
        lda M_R+1
        sbc LS_ANGLE+1
        lda M_R+2
        sbc LS_ANGLE+2
        sta M_A
        lda M_R+3
        sbc LS_ANGLE+3
        lsr a
        ror M_A
        lsr a
        ror M_A
        lsr a
        ror M_A
        sta M_A+1
        jsr sineapprox          ; sep = 128 - ((S_STEREO_SWING *
        jsr rtoa                ;   finesineapprox(angle)) >> 16)
        lda #FXC_SWING
        ldx #0
        jsr setb
        jsr mul32
        sec
        lda #NORM_SEP
        sbc M_R+2
        sta S_SEP
        lda #0
        sbc M_R+3
        sta S_SEP+1
.endif
        lda Z_D+2               ; dist < S_CLOSE_DIST (signed): full
        cmp #<FXC_CLOSEHI
        lda Z_D+3
        sbc #>FXC_CLOSEHI
        bvc :+
        eor #$80
:       bpl @dist
@full:  jsr fullvol
        bra @done
@dist:  jsr map8
        bne @far
        jsr clipd               ; map 8: dist > S_CLIPPING_DIST
        bcs @u8                 ;   (unsigned): that, no units
        stz S_U
        stz S_U+1
@u8:    jsr fullvol             ; 15 + (snd * 8 - 15) * units /
        sec                     ;   S_ATTENUATOR
        lda S_VOL
        sbc #15
        sta M_A
        lda S_VOL+1
        sbc #0
        clc
        jsr mullong
        clc
        lda M_R
        adc #15
        sta S_VOL
        lda M_R+1
        adc #0
        bra @dhi
@far:   lda SND_SFXVOL          ; snd * units * 8 / S_ATTENUATOR
        sta M_A
        lda #0
        sec
        jsr mullong
        lda M_R
        sta S_VOL
        lda M_R+1
@dhi:   sta S_VOL+1
@done:  lda S_VOL+1             ; audible: *vol > 0
        bmi @no
        ora S_VOL
        beq @no
        inc S_AUD
        sec
        rts
@no:    clc
        rts

; clipd: (S_CLIPPING_DIST - dist): S_U its high word (units), the flags
; of the last byte's subtraction (N, V; carry clear: dist is above)
clipd:
        lda #0
        cmp Z_D
        sbc Z_D+1
        lda #<FXC_CLIPHI
        sbc Z_D+2
        sta S_U
        lda #>FXC_CLIPHI
        sbc Z_D+3
        sta S_U+1
        rts

; map8: Z set when gamemap is 8
map8:
        lda FXC_GAMEMAP+1
        bne @r
        lda FXC_GAMEMAP
        cmp #8
@r:     rts

; absd: Z_D,X.. = |the listener's - the source's| x (X 0) or y (X 4)
; (absDelta [R :651-670]: D_abs); X ends 4 bytes on
absd:
        ldy #4
        sec
@a:     lda LS_X,x
        sbc S_SX,x
        sta Z_D,x
        inx
        dey
        bne @a
        bit Z_D-1,x
        bpl @r
        dex
        dex
        dex
        dex
        ldy #4
        sec
:       lda #0
        sbc Z_D,x
        sta Z_D,x
        inx
        dey
        bne :-
@r:     rts

; mullong: M_R = (M_A, A: a 16-bit value, sign-extended) * units /
; S_ATTENUATOR, signed (mulLong and divAtt [R :622-649]); carry set: the
; product shifted left by 3 first
mullong:
        php
        sta M_A+1
        lda #0
        bit M_A+1
        bpl :+
        lda #$FF
:       sta M_A+2
        sta M_A+3
        lda S_U
        ldx S_U+1
        jsr setb
        jsr mul32
        plp
        bcc @div
        ldx #3
:       asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        dex
        bne :-
@div:   jsr rtoa                ; divAtt: / S_ATTENUATOR (signed)
        lda #<FXC_ATTEN
        ldx #>FXC_ATTEN
        jsr setb
        jmp sdiv32

; setb: M_B = X:A, unsigned
setb:
        sta M_B
        stx M_B+1
        stz M_B+2
        stz M_B+3
        rts

; rtoa: M_A = M_R
rtoa:
        ldx #3
:       lda M_R,x
        sta M_A,x
        dex
        bpl :-
        rts

        .segment "S2RODATA"

; priority: the priority of each sound (sfxenum_t order), 0-127, a low
; number first [R :1274-1285], as tools/sound/fxchan.py reads it
fxc_prio:
        FXC_PRIORITIES
