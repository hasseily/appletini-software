; Doom for the Appletini -- mouse and keyboard (docs/DESIGN.md section 10).
;
; input_init finds the mouse card in slot 2 (its ID bytes, as the PCS
; port's input.s does), enables it with the VBL interrupt (mode $09: the
; kernel's 60 Hz clock, kstart.s), acknowledges anything a previous program
; left pending, opens the X window to 0..$FFFF and puts the mouse at
; $8000. C set when there is no card: the kernel stops (no clock).
;
; input_frame, once per pass of the frame loop, reads:
;   the keyboard: $C000 (a new key: the strobe is cleared by a write to
;     $C010) or $C010 (bit 7: a key is still down, so the last key counts
;     as held). The //e reports one key, the last one: holding W and then
;     pressing Space moves the held key to Space.
;   Open Apple ($C061) and Closed Apple ($C062), independent of the keys.
;   the mouse: X (lo, hi) between two reads of the card's sequence byte,
;     read again if a report landed in between; the buttons. The motion is
;     the difference with the last X; when X leaves $2000..$DFFF it is put
;     back to $8000 (two writes), so the window never clamps a motion.
; and fills kin, the block the game reads (C: struct kinput, kernel.h):
;
;   +0 mouse_dx  s16  mouse X motion since the game last took it (Doom
;                     turns right for positive motion)
;   +2 buttons   u8   KB_FIRE: Open Apple or the left mouse button;
;                     KB_USE: Closed Apple or the right mouse button;
;                     KB_RUN: the run toggle (Tab). Fire and use are the
;                     held state OR'd with any press since the game last
;                     took them, so a click between two tics is not lost.
;   +3 move      u8   from the held key: KM_FORWARD (up arrow, W),
;                     KM_BACK (down arrow, S), KM_LEFT / KM_RIGHT (left
;                     and right arrows: turn), KM_STRAFEL (A or ,),
;                     KM_STRAFER (D or .)
;   +4 key       u8   the held key, upper case, 0 when none
;   +5 newkey    u8   the last key pressed since the game last took it
;                     (upper case; Esc = $1B), 0 when none
;   +6 weapon    u8   1..7 when a digit key was pressed since the game
;                     last took it, else 0
;   +7 flags     u8   KF_MENU: Esc was pressed since the game last took it
;
; "Since the game last took it": input_consume clears mouse_dx, newkey,
; weapon, flags and the latched fire/use presses; the frame loop calls it
; after the first game tic of each rendered frame (the other tics of the
; frame see no motion and no new keys, as Doom's tics after a lag do).
; kmouse_x is the running sum of the mouse motion (never cleared): the
; test pattern (src/render/stub.s) draws a column from it.
;
; Cost: 2 keyboard, 2 button and 5 mouse accesses per call (seq, X lo,
; X hi, seq, buttons), 2 more when X is re-centred; all $Cxxx.

.include "kernel.inc"

KB_FIRE     = $01
KB_USE      = $02
KB_RUN      = $80
KM_FORWARD  = $01
KM_BACK     = $02
KM_LEFT     = $04
KM_RIGHT    = $08
KM_STRAFEL  = $10
KM_STRAFER  = $20
KF_MENU     = $01

MOUSE_SEQ   = $C0A6
MODE_ENABLE_VBL = $09           ; enable + VBL interrupt
ACK_ALL     = $03
CMD_CLAMP   = $02
CENTRE      = $80               ; X hi of the centre ($8000)

KEY_LEFT    = $08
KEY_TAB     = $09
KEY_DOWN    = $0A
KEY_UP      = $0B
KEY_RIGHT   = $15
KEY_ESC     = $1B

; ---------------------------------------------------------------------------
.segment "KBSS"
kin:
kin_dx:     .res 2
kin_buttons: .res 1
kin_move:   .res 1
kin_key:    .res 1
kin_newkey: .res 1
kin_weapon: .res 1
kin_flags:  .res 1
latch:      .res 1              ; fire/use presses not yet taken
run:        .res 1              ; KB_RUN or 0
key_hold:   .res 1
last_x:     .res 2
kmouse_x:   .res 2
.export kin, _kin := kin, kmouse_x

.segment "KZP": zeropage
in_x:       .res 2              ; the card's X this frame
in_btn:     .res 1              ; fire/use held this frame

; ---------------------------------------------------------------------------
.segment "KCODE"

input_init:
        sta     $C006                   ; INTCXROM off: the slot ROMs are visible
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
        lda     #ACK_ALL
        sta     MOUSE_ACK
        stz     MOUSE_CLAMPSEL          ; X: 0..$FFFF
        stz     MOUSE_MINLO
        stz     MOUSE_MINHI
        lda     #$FF
        sta     MOUSE_MAXLO
        sta     MOUSE_MAXHI
        lda     #CMD_CLAMP
        sta     MOUSE_CMD
        stz     MOUSE_XLO
        lda     #CENTRE
        sta     MOUSE_XHI
        stz     last_x
        sta     last_x+1
        lda     #MODE_ENABLE_VBL
        sta     MOUSE_MODE
        clc
        rts
@none:  sec
        rts

; ---------------------------------------------------------------------------
input_frame:
        ; --- the keyboard ---
        lda     KBD
        bmi     @new
        lda     KBDSTRB                 ; bit 7: a key is still down
        bmi     @apple
        stz     key_hold
        bra     @apple
@new:   sta     KBDSTRB                 ; clear the strobe (a write)
        and     #$7F
        cmp     #'a'
        bcc     :+
        cmp     #'z'+1
        bcs     :+
        sbc     #$1F                    ; carry clear: -$20
:       sta     key_hold
        sta     kin_newkey
        cmp     #KEY_TAB
        bne     :+
        lda     run
        eor     #KB_RUN
        sta     run
        bra     @apple
:       cmp     #KEY_ESC
        bne     :+
        lda     #KF_MENU
        tsb     kin_flags
        bra     @apple
:       cmp     #'1'
        bcc     @apple
        cmp     #'8'
        bcs     @apple
        sbc     #'0'-1                  ; carry clear: - '0'
        sta     kin_weapon

        ; --- Open and Closed Apple ---
@apple: stz     in_btn
        lda     BUTTON0
        bpl     :+
        lda     #KB_FIRE
        tsb     in_btn
:       lda     BUTTON1
        bpl     :+
        lda     #KB_USE
        tsb     in_btn

        ; --- the mouse: X between two reads of the sequence byte ---
:       ldy     #2                      ; at most two tries
@seq:   ldx     MOUSE_SEQ
        lda     MOUSE_XLO
        sta     in_x
        lda     MOUSE_XHI
        sta     in_x+1
        cpx     MOUSE_SEQ
        beq     @xok
        dey
        bne     @seq
@xok:   lda     MOUSE_BTN
        and     #3                      ; bit 0 left = fire, bit 1 right = use
        tsb     in_btn
        ; motion = X - last_x
        sec
        lda     in_x
        sbc     last_x
        tax
        lda     in_x+1
        sbc     last_x+1
        tay                             ; Y:X = the motion
        clc
        txa
        adc     kin_dx
        sta     kin_dx
        tya
        adc     kin_dx+1
        sta     kin_dx+1
        clc
        txa
        adc     kmouse_x
        sta     kmouse_x
        tya
        adc     kmouse_x+1
        sta     kmouse_x+1
        lda     in_x
        sta     last_x
        lda     in_x+1
        sta     last_x+1
        cmp     #$20
        bcc     @centre
        cmp     #$E0
        bcc     @buttons
@centre:
        stz     MOUSE_XLO
        lda     #CENTRE
        sta     MOUSE_XHI
        stz     last_x
        sta     last_x+1

        ; --- buttons: held | latched, and the run toggle ---
@buttons:
        lda     in_btn
        tsb     latch
        lda     latch
        ora     run
        sta     kin_buttons

        ; --- movement from the held key ---
        lda     key_hold
        sta     kin_key
        ldx     #move_keys_end-move_keys-1
:       cmp     move_keys,x
        beq     @move
        dex
        bpl     :-
        stz     kin_move
        rts
@move:  lda     move_bits,x
        sta     kin_move
        rts

move_keys:
        .byte   KEY_UP, 'W', KEY_DOWN, 'S', KEY_LEFT, KEY_RIGHT, 'A', ',', 'D', '.'
move_keys_end:
move_bits:
        .byte   KM_FORWARD, KM_FORWARD, KM_BACK, KM_BACK, KM_LEFT, KM_RIGHT
        .byte   KM_STRAFEL, KM_STRAFEL, KM_STRAFER, KM_STRAFER

; ---------------------------------------------------------------------------
; input_consume: the game has taken the motion, the new keys and the
; latched presses (called by the frame loop after the first tic).
; ---------------------------------------------------------------------------
input_consume:
        stz     kin_dx
        stz     kin_dx+1
        stz     kin_newkey
        stz     kin_weapon
        stz     kin_flags
        stz     latch
        lda     in_btn                  ; what is still held stays
        ora     run
        sta     kin_buttons
        rts
.export input_consume
