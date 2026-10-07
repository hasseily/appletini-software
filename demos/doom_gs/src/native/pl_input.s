; pl_input.s: the //e's input, the shared object pl_poll (part
; plinput; docs/SCREENS.md).
; GPL-2, the port's own: written from the design, upstream's documented
; behaviour of I_InitKeyboard, I_StartTic, repeatStart, repeat, I_BindKey,
; I_DefaultKeys, recount, I_ActionKeys and postKey [R i_iigs65.s:676-1000]
; and the input_frame of the earlier Appletini Doom port's //e kernel
; (the keyboard, the Apple keys, the mouse card's X between two reads of
; its sequence byte, re-centred).
;
;   pl_poll      once a frame, in every frame image (docs/SCREENS.md), first
;                after the replay; A = nonzero while a menu is up (the
;                menu's arrow repeat, upstream's _g_menuactive test).
;                The keys' events into PL_QUEUE, the mouse's X motion
;                added to PL_MDX (upstream's iigs_mousedx). A, X, Y and
;                the PLZ_* zero page clobbered
;   pl_xhi       (a label: the read of X's high byte, the point for a
;                report between the two reads)
;
; pl_keys.s holds what the boot and the menus call (pl_init, pl_defaults,
; pl_bind, pl_action: I_InitKeyboard, I_DefaultKeys, I_BindKey,
; I_ActionKeys), so the object every frame image links is the poll alone.
;
; The sources (docs/SCREENS.md). The //e knows one key down: the held key
; PL_HELD (0: none) is the last code read at $C000, folded to upper case
; ($61-$7A less $20), and it goes up when $C010's bit 7 (a key is down)
; clears. The Apple keys and the mouse's buttons are four more keys, read
; each poll into PL_BUTTONS: bit 0 the pseudo-key $70 (button 1, MOUSE 2),
; bit 1 $71 (button 0, MOUSE 1), bit 2 $72 (Open Apple), bit 3 $73 (Solid
; Apple). A source is a //e code; PL_KEYTAB gives its Doom key.
;
; A poll:
;   1. Room: fewer than 7 free events (a poll makes at most 7: a key up, a
;      key down and its character, the four other keys) and the poll posts
;      nothing: $C000's strobe, the Apple keys, the buttons and the repeat
;      wait for the next poll; PL_DEFER counts it. The mouse is read.
;   2. The old Doom keys: a 23-bit mask from the sources before the poll
;      (upstream's counts, recomputed: a Doom key is down while any of its
;      sources is).
;   3. The keyboard. A new code (the strobe) that is the held key while
;      $C010 says down is the //e's auto-repeat: nothing. Any other is a
;      new press: it is the held key now (the old one goes up), its
;      character is posted, and a menu arrow starts upstream's repeat
;      (REP_DELAY 11 tics). A tap (the key already up at $C010) stays held
;      for this poll: it goes up at the next (upstream's rule 4). No new
;      code: $C010's bit 7 clear and the held key goes up.
;   4. The Apple keys ($C061, $C062) and the buttons ($C0A5).
;   5. The key setup (PL_BIND = $FF, upstream's iigs_bindwait): the first
;      new press, of the keyboard or else of the four keys in the order
;      $70-$73, is written to PL_BIND and makes no event this poll (no
;      Doom key, no character); the //e's key stays held, so its
;      auto-repeat is ignored and its release is an up of nothing that
;      went down (harmless, as an up only clears gamekeydown).
;   6. The new mask; the Doom keys that changed are posted from 22 down to
;      0, upstream recount's order: EV_KEYDOWN or EV_KEYUP with the key.
;      Then the new press's character (EV_KEYDOWN), then the repeat: the
;      arrow still held and a menu up, its time come (pl_time's low word,
;      signed), the next 4 tics later (REP_RATE).
;   7. The mouse: the sequence byte, X (low, high), the sequence byte again
;      (a report between the reads: once more); the motion X - the last X
;      added to PL_MDX; X outside $2000-$DFFF goes back to $8000.
;
; The queue: PL_EVENTS (15) entries of 3 bytes in a ring of PL_QUEUE;
; PL_QTAIL the next in (this file's), PL_QHEAD the next out (the
; consumer's, D_PostEvent's in the second half); empty when equal, so 14
; hold events. An event: the type (EV_KEYDOWN 0, EV_KEYUP 1), then data1
; as upstream's event_t, a word: a Doom key 0-22 or a character >= 23
; [R keys.inc:1-3], its high byte 0. A full queue drops an event: a poll
; never meets it (step 1); pl_keys.s's recount posts at most 10.
;
; Writes: the input block $03B3-$03ED, PLZ_*, the mouse card's X ($C0A1,
; $C0A2); pl_keys.s writes PL_KEYTAB and the card's window too. $Cxxx: $C000, $C010, $C061, $C062, $C0A5, $C0A6 twice,
; $C0A1, $C0A2 a poll (docs/SCREENS.md), two more to re-centre.

        .setcpu "65C02"
        .include "s2.inc"
        .include "pl_input.inc"

        .import pl_time
        .export pl_poll, pl_xhi, pl_centre
        .export pl_bold, pl_mask, pl_diff     ; (pl_keys.s's recount)

        .segment "S2CODE"

; ---------------------------------------------------------------------------
pl_poll:
        sta PLZ_MENU
        stz PLZ_CH
        lda PL_QTAIL            ; 1. the bytes queued, (tail - head) mod 45
        sec
        sbc PL_QHEAD
        bcs :+
        adc #QBYTES
:       cmp #QBYTES - PL_EVENT_SIZE - QMOST + 1
        bcc @room
        inc PL_DEFER            ; fewer than 7 free: nothing posted
        jmp pl_mouse
@room:  jsr pl_bold             ; 2. the old mask
        ldx PL_HELD             ; 3. X: the held key after the poll
        lda KBD
        bpl @nokey
        and #$7F
        cmp #$61                ; lower case to upper
        bcc :+
        cmp #$7B
        bcs :+
        sbc #$1F                ; (carry clear: less $20)
:       tay                     ; Y: the code
        lda KBDSTRB             ; the strobe cleared, bit 7: a key down
        bpl @new                ; up already: a tap
        cpy PL_HELD
        beq @keys               ; the held key again: the //e's repeat
@new:   tya
        tax                     ; the new key is held
        lda PL_BIND             ; 5. the key setup's key: no event
        cmp #BIND_WAIT
        bne @press
        sty PL_BIND
        sty PLZ_SKIP
        bra @keys
@press: jsr pl_chr
        sta PLZ_CH
        cmp #KEYC_ENTER         ; a menu arrow: the repeat starts
        bcs @keys
        cmp #KEYC_UP
        bcc @keys
        sta PL_REPCH
        stx PL_REPKEY
        phx
        jsr pl_time
        clc
        adc #REP_DELAY
        sta PL_REPTIC
        txa
        adc #0
        sta PL_REPTIC+1
        plx
        bra @keys
@nokey: lda KBDSTRB
        bmi @keys
        ldx #0                  ; no key down: the held key goes up
@keys:  stx PLZ_NH
        stz PLZ_NB              ; 4. bits 3-0: Solid Apple, Open Apple,
        lda BUTN1               ;   button 0, button 1
        asl a
        rol PLZ_NB
        lda BUTN0
        asl a
        rol PLZ_NB
        lda MOUSE_BTN
        lsr a
        rol PLZ_NB
        lsr a
        rol PLZ_NB
        lda PL_BIND             ; 5. the key setup's: a button or Apple key
        cmp #BIND_WAIT          ;   pressed
        bne @mask
        lda PL_BUTTONS
        eor #$FF
        and PLZ_NB
        beq @mask
        ldy #$70
:       lsr a
        bcs :+
        iny
        bra :-
:       sty PL_BIND
        sty PLZ_SKIP
@mask:  lda PLZ_NB              ; 6. the new mask, the changes
        sta PLZ_SB
        lda PLZ_NH
        jsr pl_mask
        jsr pl_diff
        ldx PLZ_CH              ; the new press's character
        beq @rep
        lda #EV_KEYDOWN
        jsr pl_post
@rep:   lda PL_REPCH            ; the repeat (upstream's repeat)
        beq @done
        lda PL_REPKEY
        cmp PLZ_NH
        beq :+
        stz PL_REPCH            ; up: no more repeats
        bra @done
:       lda PLZ_MENU
        beq @done
        jsr pl_time
        sec
        sbc PL_REPTIC
        txa
        sbc PL_REPTIC+1
        bmi @done
        lda PL_REPTIC
        clc
        adc #REP_RATE
        sta PL_REPTIC
        bcc :+
        inc PL_REPTIC+1
:       ldx PL_REPCH
        lda #EV_KEYDOWN
        jsr pl_post
@done:  lda PLZ_NH
        sta PL_HELD
        lda PLZ_NB
        sta PL_BUTTONS

; 7. the mouse
pl_mouse:
        ldy #2                  ; at most two reads
pl_mseq:   ldx MOUSE_SEQ
        lda MOUSE_XLO
        sta PLZ_XL
pl_xhi: lda MOUSE_XHI
        sta PLZ_XH
        cpx MOUSE_SEQ
        beq pl_mxok
        dey
        bne pl_mseq
pl_mxok:   sec                     ; the motion: X - the last X
        lda PLZ_XL
        sbc PL_MLX
        tax
        lda PLZ_XH
        sbc PL_MLX+1
        tay
        txa
        clc
        adc PL_MDX
        sta PL_MDX
        tya
        adc PL_MDX+1
        sta PL_MDX+1
        lda PLZ_XL
        sta PL_MLX
        lda PLZ_XH
        sta PL_MLX+1
        cmp #$20                ; outside $2000-$DFFF: back to the centre
        bcc pl_centre
        cmp #$E0
        bcs pl_centre
        rts
pl_centre:
        stz MOUSE_XLO
        lda #CENTRE
        sta MOUSE_XHI
        stz PL_MLX
        sta PL_MLX+1
        rts

; ---------------------------------------------------------------------------
; pl_bold: the old mask from PL_HELD and PL_BUTTONS into PLZ_OLD
pl_bold:
        stz PLZ_SKIP
        lda PL_BUTTONS
        sta PLZ_SB
        lda PL_HELD
        jsr pl_mask
        ldx #2
:       lda PLZ_M,x
        sta PLZ_OLD,x
        dex
        bpl :-
        rts

; pl_mask: A = the held code, PLZ_SB = the buttons: their Doom keys into
; PLZ_M (PLZ_SB consumed)
pl_mask:
        stz PLZ_M
        stz PLZ_M+1
        stz PLZ_M+2
        jsr pl_src
        lda #$70
@b:     lsr PLZ_SB
        bcc :+
        pha
        jsr pl_src
        pla
:       inc a
        cmp #$74
        bcc @b
        rts

; pl_src: A = a source's code (0: none): its Doom key's bit into PLZ_M
pl_src:
        tay
        beq @r
        cpy PLZ_SKIP
        beq @r
        lda PL_KEYTAB,y
        cmp #NUMKEYS
        bcs @r                  ; NOKEY
        jsr pl_bit
        ora PLZ_M,y
        sta PLZ_M,y
@r:     rts

; pl_bit: A = a Doom key: Y = its byte in a mask, A = its bit; X kept
pl_bit:
        pha
        lsr a
        lsr a
        lsr a
        tay
        pla
        and #7
        phx
        tax
        lda pl_bits,x
        plx
        rts

; pl_diff: each Doom key whose bit differs in PLZ_OLD and PLZ_M, 22 to 0:
; EV_KEYDOWN when the new mask has it, else EV_KEYUP
pl_diff:
        ldx #NUMKEYS - 1
@k:     txa
        jsr pl_bit
        sta PLZ_T
        lda PLZ_M,y
        eor PLZ_OLD,y
        and PLZ_T
        beq @n
        and PLZ_M,y
        beq @up
        lda #EV_KEYDOWN
        .byte $2C               ; (BIT abs: over the next LDA)
@up:    lda #EV_KEYUP
        jsr pl_post
@n:     dex
        bpl @k
        rts

; pl_post: the event A (type) with data1 X into the queue; X kept
pl_post:
        ldy PL_QTAIL
        sta PL_QUEUE,y
        txa
        sta PL_QUEUE+1,y
        lda #0
        sta PL_QUEUE+2,y
        tya
        clc
        adc #PL_EVENT_SIZE
        cmp #QBYTES
        bcc :+
        lda #0
:       cmp PL_QHEAD
        beq :+                  ; full: dropped
        sta PL_QTAIL
:       rts

; pl_chr: X = a folded code: A = its character (0: none); X kept
pl_chr:
        txa
        cmp #'0'
        bcc @sp
        cmp #'9' + 1
        bcc @r                  ; a digit
        cmp #'A'
        bcc @no
        cmp #'Z' + 1
        bcs @sp
        ora #$20                ; a letter: its lower case
@r:     rts
@sp:    ldy #5
:       cmp pl_menuk,y
        beq @hit
        dey
        bpl :-
@no:    lda #0
        rts
@hit:   tya
        ora #KEYC_UP
        rts

        .segment "S2RODATA"
pl_bits:
        .byte $01, $02, $04, $08, $10, $20, $40, $80
pl_menuk:                       ; KEYC_UP + index: UP, DOWN, LEFT, RIGHT,
        .byte $0B, $0A, $08, $15, $0D, $7F      ; RETURN, DELETE
