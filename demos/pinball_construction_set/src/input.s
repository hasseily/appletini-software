; Pinball Construction Set for the Appletini -- mouse, keyboard and paddle
; input (docs/DESIGN.md section 9).
;
; Interface:
;   input_init        find the mouse card; set it up or calibrate the
;                     paddles. MB_HAVEMOUSE = 1 with a card, else 0.
;   input_frame       once per frame, after the line-0 wait: read the
;                     hardware and update the variables below.
;   input_getkey      A = in_key (bit 7 set) or 0; clears in_key. Keeps X, Y.
;   input_set_cursor  A/X = x lo/hi, Y = y: move the cursor and, with a
;                     card, its position registers (the editor snaps the
;                     cursor to an object's edge when a drag starts).
;
; Variables (BSS, exported):
;   in_mx (16-bit), in_my   the cursor, 0..319 x 0..199: the mouse position,
;                     or moved by the arrow keys (1 pixel per frame, 4 once
;                     held for more than 15 frames) or, without a mouse, by
;                     the paddles as a rate controller with the same speeds.
;                     While an arrow key is held the keys own the cursor:
;                     the card's position is not read but written, so the
;                     mouse carries on from where the keys left it.
;   in_btn            bit 7 while the button is down: the left mouse button,
;                     Open Apple, Closed Apple or Space held. The editor's
;                     drag and menu code needs the held state, not an edge.
;   in_key            the key pressed this frame, bit 7 set, or 0. It is
;                     cleared by input_getkey (a key is reported once) and
;                     by the next input_frame: a key nobody takes must not
;                     wait around for the play loop, whose first poll would
;                     act on an Esc pressed in the editor long before.
;   in_flip           bit 7 = left flipper (Open Apple, Z, left mouse
;                     button), bit 6 = right flipper (Closed Apple, /, right
;                     mouse button); held states.
;   in_plunger        0..255: +4 per frame while Space or the down arrow is
;                     held (in_launch = 0). On release in_launch = $80 for
;                     12 frames while in_plunger keeps its value, then
;                     in_plunger falls by 32 per frame and in_launch is 0.
;   in_launch         see in_plunger.
; Esc, Ctrl-S, the digits and every other key are only reported through
; in_key. The mailbox gets MB_MOUSEX/MB_MOUSEY (the cursor) and MB_INPUT
; (bit 7 button, 6 left flipper, 5 right flipper, 4 launch, 3..0 the
; direction being applied: right, left, down, up).
;
; Bus cost (every $C0xx access is a 1 MHz bus cycle under the vTW):
; input_frame reads $C000 and $C010 (2: the strobe read and either the
; strobe clear or the "any key down" read), $C061/$C062 (2), then with a
; card its X lo, X hi, Y lo and buttons (4; Y hi is never needed, the card
; clamps Y to 0..199) -- or, on a frame where a held arrow key moves the
; cursor, the buttons only (1) and, after the move, X lo, X hi, Y lo
; written back (3): exactly 8 with a mouse, 4 without. Without a mouse,
; each usable paddle axis is polled on alternate frames as Bosconian's
; input.s does: one $C070 trigger and one read per poll, about 11 us
; apart, at most JOY_CAP polls; an axis whose timer never expires within
; the cap at calibration is switched off, so a machine with neither mouse
; nor paddles pays for the calibration once and nothing per frame.
;
; The card (appletini-one/hdl/apple/mouse_card.sv): X/Y update only from
; the PS's commits and only while mode bit 0 is set; position writes store
; raw values (the PS adds its next delta to what it reads back); the home
; command goes to the clamp minimum, so the screen centre is written
; directly. A mode write leaves the status and IRQ latches alone (only
; the ACK register clears them), so input_init acknowledges whatever a
; previous program left armed. Its slot ROM shows the AppleMouse ID bytes
; while INTCXROM is off; the internal //e ROM's slot 3 page has three of
; the four, never all.
;
; Zero page: none. All state is in BSS; nothing here runs with RAMWRT on.

.setcpu "65C02"
.include "pcs.inc"

.export input_init, input_frame, input_getkey, input_set_cursor
.export in_mx, in_my, in_btn, in_key, in_flip, in_plunger, in_launch

INTCXROMOFF = $C006             ; slot ROMs visible at $C100-$C7FF

; the card
MOUSE_ID5   = $38
MOUSE_ID7   = $18
MOUSE_IDB   = $01
MOUSE_IDC   = $20
MODE_ENABLE = $01
CMD_CLAMP   = $02               ; commit the selected axis's window, re-clamp
ACK_ALL     = $03               ; bit 0 the status causes, bit 1 the IRQ latch
CENTRE_X    = SCREEN_W / 2
CENTRE_Y    = SCREEN_H / 2

; keys ($C000 values with bit 7 stripped)
KEY_LEFT    = $08
KEY_RIGHT   = $15
KEY_UP      = $0B
KEY_DOWN    = $0A

; direction bits (dir_mask, MB_INPUT bits 3..0)
DIR_UP      = $01
DIR_DOWN    = $02
DIR_LEFT    = $04
DIR_RIGHT   = $08

HOLD_FAST     = 15              ; frames held before the 4-pixel steps
LAUNCH_FRAMES = 12
PLUNGER_PULL  = 4
PLUNGER_DROP  = 32

; paddles (Bosconian's tuning)
JOY_CAP     = 400               ; polls per axis read: the bus-cycle bound
JOY_DELAY   = 69                ; dey/bne iterations between polls: about
                                ; 11 us at 33 MHz, the ROM PREAD granularity

.segment "BSS"
state_begin:
in_mx:      .res 2
in_my:      .res 1
in_btn:     .res 1
in_key:     .res 1
in_flip:    .res 1
in_plunger: .res 1
in_launch:  .res 1
have_mouse: .res 1
mouse_btn:  .res 1              ; the card's button byte this frame
apple_keys: .res 1              ; bit 7 Open Apple, bit 6 Closed Apple
key_hold:   .res 1              ; the last key (upper case) while any key is down
dir_mask:   .res 1
hold_count: .res 1              ; frames the direction has been held (<= HOLD_FAST)
step:       .res 1              ; pixels to move this frame
pl_state:   .res 1              ; 0 idle, 1 pulling, 2 launching
launch_timer: .res 1
joy_axis:   .res 1              ; 0 = read X next, 1 = read Y next
joy_dir:    .res 2              ; per axis: the direction bit last seen
joy_ok:     .res 2              ; per axis: 1 when calibrated and not capped
joy_lo:     .res 4              ; per axis u16: below -> left / up
joy_hi:     .res 4              ; per axis u16: above -> right / down
joy_center: .res 4              ; per axis u16: the calibrated count
joy_cnt:    .res 2              ; poll count of the last read
joy_tmp:    .res 2
state_end:

.segment "RODATA"
flip_tab:   .byte $00, $80, $40, $C0    ; card buttons (bit 0 L, bit 1 R) -> in_flip
axis_low:   .byte DIR_LEFT, DIR_UP
axis_high:  .byte DIR_RIGHT, DIR_DOWN

.segment "CODE"

; ---------------------------------------------------------------------------
; input_init
; ---------------------------------------------------------------------------
input_init:
        ldx     #state_end-state_begin-1
:       stz     state_begin,x
        dex
        bpl     :-
        lda     #<CENTRE_X
        sta     in_mx
        lda     #>CENTRE_X
        sta     in_mx+1
        lda     #CENTRE_Y
        sta     in_my
        ; the ID bytes are in the slot ROM space, hidden while INTCXROM is on
        sta     INTCXROMOFF
        lda     MOUSE_ROM+$05
        cmp     #MOUSE_ID5
        bne     @nomouse
        lda     MOUSE_ROM+$07
        cmp     #MOUSE_ID7
        bne     @nomouse
        lda     MOUSE_ROM+$0B
        cmp     #MOUSE_IDB
        bne     @nomouse
        lda     MOUSE_ROM+$0C
        cmp     #MOUSE_IDC
        bne     @nomouse
        ; found: enable without interrupts, release any IRQ a previous
        ; program left asserted, clamp X to 0..319 and Y to 0..199, centre
        lda     #MODE_ENABLE
        sta     MOUSE_MODE
        lda     #ACK_ALL
        sta     MOUSE_ACK
        stz     MOUSE_CLAMPSEL
        stz     MOUSE_MINLO
        stz     MOUSE_MINHI
        lda     #<(SCREEN_W-1)
        sta     MOUSE_MAXLO
        lda     #>(SCREEN_W-1)
        sta     MOUSE_MAXHI
        lda     #CMD_CLAMP
        sta     MOUSE_CMD
        lda     #1
        sta     MOUSE_CLAMPSEL
        stz     MOUSE_MINLO
        stz     MOUSE_MINHI
        lda     #SCREEN_H-1
        sta     MOUSE_MAXLO
        stz     MOUSE_MAXHI
        lda     #CMD_CLAMP
        sta     MOUSE_CMD
        lda     #<CENTRE_X
        sta     MOUSE_XLO
        lda     #>CENTRE_X
        sta     MOUSE_XHI
        lda     #CENTRE_Y
        sta     MOUSE_YLO
        stz     MOUSE_YHI
        lda     #1
        sta     have_mouse
        sta     MB_HAVEMOUSE
        rts
@nomouse:
        stz     MB_HAVEMOUSE
        jmp     joy_calibrate

; ---------------------------------------------------------------------------
; input_getkey
; ---------------------------------------------------------------------------
input_getkey:
        lda     in_key
        stz     in_key
        rts

; ---------------------------------------------------------------------------
; input_set_cursor: A/X = x, Y = y
; ---------------------------------------------------------------------------
input_set_cursor:
        sta     in_mx
        stx     in_mx+1
        sty     in_my
        lda     have_mouse
        bne     card_set_pos
        rts

; card_set_pos: the card's position from in_mx/in_my. Y hi is not written:
; the card clamps Y to 0..199 on every commit, input_init wrote 0 and this
; driver only ever writes y < 200, so it is 0 already.
card_set_pos:
        lda     in_mx
        sta     MOUSE_XLO
        lda     in_mx+1
        sta     MOUSE_XHI
        lda     in_my
        sta     MOUSE_YLO
        rts

; ---------------------------------------------------------------------------
; input_frame
; ---------------------------------------------------------------------------
input_frame:
        ; --- the keyboard: 2 accesses ---
        ; The //e latches one key with a strobe; $C010 bit 7 says whether
        ; any key is down. While it is, the last key counts as held, so a
        ; held arrow keeps moving and a held Space keeps the button down.
        lda     KBD
        bmi     @new_key
        stz     in_key          ; no key this frame
        lda     KBDSTRB         ; no strobe to clear: this is the key-down bit
        bmi     @apple_keys
        stz     key_hold
        bra     @apple_keys
@new_key:
        sta     KBDSTRB         ; clear the strobe (a write: no read side effect)
        sta     in_key
        and     #$7F
        cmp     #'a'
        bcc     :+
        cmp     #'z'+1
        bcs     :+
        sbc     #$1F            ; carry clear: -$20, upper case
:       sta     key_hold

        ; --- Open and Closed Apple: 2 reads ---
@apple_keys:
        lda     BUTTON0
        and     #$80
        sta     apple_keys
        lda     BUTTON1
        and     #$80
        lsr     a
        tsb     apple_keys

        ; --- the held arrow key ---
        ldx     #0
        lda     key_hold
        cmp     #KEY_LEFT
        bne     :+
        ldx     #DIR_LEFT
:       cmp     #KEY_RIGHT
        bne     :+
        ldx     #DIR_RIGHT
:       cmp     #KEY_UP
        bne     :+
        ldx     #DIR_UP
:       cmp     #KEY_DOWN
        bne     :+
        ldx     #DIR_DOWN
:       stx     dir_mask

        ; --- the card: 4 reads, or 1 while an arrow key is held ---
        ; While the keys move the cursor the card's position is not
        ; read: the frame writes it back after the move (3 writes), which
        ; keeps the frame at 8 accesses and the card in step.
        stz     mouse_btn
        lda     have_mouse
        beq     @paddles
        lda     dir_mask
        bne     @card_btn
        lda     MOUSE_XLO
        sta     in_mx
        lda     MOUSE_XHI
        sta     in_mx+1
        lda     MOUSE_YLO
        sta     in_my
@card_btn:
        lda     MOUSE_BTN
        and     #$03
        sta     mouse_btn
        bra     @flippers

        ; --- or the paddles, as a rate controller ---
@paddles:
        jsr     joy_read        ; A = the paddles' direction bits
        tsb     dir_mask

        ; --- flippers ---
@flippers:
        ldx     mouse_btn
        lda     flip_tab,x
        ora     apple_keys
        sta     in_flip
        lda     key_hold
        cmp     #'Z'
        bne     :+
        lda     #$80
        tsb     in_flip
        bra     @button
:       cmp     #'/'
        bne     @button
        lda     #$40
        tsb     in_flip

        ; --- the button ---
@button:
        lda     apple_keys
        bne     @btn_down
        lda     mouse_btn
        lsr     a
        bcs     @btn_down       ; left mouse button
        lda     key_hold
        cmp     #' '
        beq     @btn_down
        stz     in_btn
        bra     @move
@btn_down:
        lda     #$80
        sta     in_btn

        ; --- move the cursor: 1 pixel a frame, 4 once held past HOLD_FAST ---
@move:
        lda     dir_mask
        bne     @moving
        stz     hold_count
        bra     @plunger
@moving:
        ldy     #1
        lda     hold_count
        cmp     #HOLD_FAST
        bcs     @fast
        inc     hold_count
        bra     @step
@fast:  ldy     #4
@step:  sty     step
        jsr     move_cursor
        lda     have_mouse
        beq     @plunger
        jsr     card_set_pos    ; 3 writes: the card follows the keys

        ; --- the plunger ---
@plunger:
        lda     key_hold
        cmp     #' '
        beq     @pull
        cmp     #KEY_DOWN
        beq     @pull
        lda     pl_state
        beq     @drop           ; idle
        cmp     #1
        bne     @launching
        lda     #2              ; pulling until now: released
        sta     pl_state
        lda     #LAUNCH_FRAMES
        sta     launch_timer
        lda     #$80
        sta     in_launch
        bra     @mailbox
@launching:
        dec     launch_timer
        bne     @mailbox        ; in_launch stays $80, in_plunger keeps its value
        stz     pl_state
@drop:
        stz     in_launch
        lda     in_plunger
        sec
        sbc     #PLUNGER_DROP
        bcs     :+
        lda     #0
:       sta     in_plunger
        bra     @mailbox
@pull:
        lda     #1
        sta     pl_state
        stz     in_launch
        lda     in_plunger
        clc
        adc     #PLUNGER_PULL
        bcc     :+
        lda     #$FF
:       sta     in_plunger

        ; --- the mailbox ---
@mailbox:
        lda     in_mx
        sta     MB_MOUSEX
        lda     in_mx+1
        sta     MB_MOUSEX+1
        lda     in_my
        sta     MB_MOUSEY
        lda     in_flip
        lsr     a               ; flippers to bits 6 and 5
        ora     in_btn
        ora     dir_mask
        sta     MB_INPUT
        lda     in_launch
        lsr     a
        lsr     a
        lsr     a               ; $80 -> $10
        tsb     MB_INPUT
        rts

; ---------------------------------------------------------------------------
; move_cursor: in_mx/in_my by `step` in the directions of dir_mask, kept
; on the screen.
; ---------------------------------------------------------------------------
move_cursor:
        lda     dir_mask
        and     #DIR_UP
        beq     @not_up
        lda     in_my
        sec
        sbc     step
        bcs     :+
        lda     #0
:       sta     in_my
@not_up:
        lda     dir_mask
        and     #DIR_DOWN
        beq     @not_down
        lda     in_my
        clc
        adc     step
        cmp     #SCREEN_H
        bcc     :+
        lda     #SCREEN_H-1
:       sta     in_my
@not_down:
        lda     dir_mask
        and     #DIR_LEFT
        beq     @not_left
        lda     in_mx
        sec
        sbc     step
        sta     in_mx
        lda     in_mx+1
        sbc     #0
        sta     in_mx+1
        bcs     @not_left
        stz     in_mx
        stz     in_mx+1
@not_left:
        lda     dir_mask
        and     #DIR_RIGHT
        beq     @not_right
        lda     in_mx
        clc
        adc     step
        sta     in_mx
        lda     in_mx+1
        adc     #0
        sta     in_mx+1
        lda     in_mx
        cmp     #<SCREEN_W
        lda     in_mx+1
        sbc     #>SCREEN_W
        bcc     @not_right      ; in_mx < 320
        lda     #<(SCREEN_W-1)
        sta     in_mx
        lda     #>(SCREEN_W-1)
        sta     in_mx+1
@not_right:
        rts

; ---------------------------------------------------------------------------
; Paddles, as Bosconian's input.s: one axis per frame, a direction bit
; when the count leaves the 35% band around the calibrated centre.
; ---------------------------------------------------------------------------

; read_axis: X = 0 (PADDLE0) or 1 (PADDLE1). joy_cnt = polls until the
; timer expired (0..JOY_CAP). One $C070 trigger, then one read per poll
; with a CPU-only wait between polls. Keeps X.
read_axis:
        stz     joy_cnt
        stz     joy_cnt+1
        lda     PTRIG           ; start both paddle timers
@poll:  lda     PADDLE0,x
        bpl     @done           ; timer expired: bit 7 clear
        inc     joy_cnt
        bne     :+
        inc     joy_cnt+1
:       lda     joy_cnt+1
        cmp     #>JOY_CAP
        bcc     @delay
        lda     joy_cnt
        cmp     #<JOY_CAP
        bcs     @done           ; cap reached
@delay: ldy     #JOY_DELAY
:       dey
        bne     :-
        bra     @poll
@done:  rts

; shr_tmp: joy_tmp >>= 1
shr_tmp:
        lsr     joy_tmp+1
        ror     joy_tmp
        rts

; calibrate_axis: X = axis. joy_cnt is the centred count: centre = count,
; lo = centre - 35%, hi = centre + 35% (c/4 + c/8 - c/32 = 0.344 c). A
; count at the cap means the timer never expired: the axis is switched off.
calibrate_axis:
        txa
        asl     a
        tay                     ; Y = axis*2 (u16 index)
        lda     joy_cnt
        sta     joy_center,y
        lda     joy_cnt+1
        sta     joy_center+1,y
        cmp     #>JOY_CAP
        bcc     @usable
        lda     joy_cnt
        cmp     #<JOY_CAP
        bcc     @usable
        stz     joy_ok,x
        rts
@usable:
        lda     #1
        sta     joy_ok,x
        ; t = c/4 + c/8 - c/32, built in joy_lo
        lda     joy_cnt
        sta     joy_tmp
        lda     joy_cnt+1
        sta     joy_tmp+1
        jsr     shr_tmp
        jsr     shr_tmp         ; c/4
        lda     joy_tmp
        sta     joy_lo,y
        lda     joy_tmp+1
        sta     joy_lo+1,y
        jsr     shr_tmp         ; c/8
        clc
        lda     joy_lo,y
        adc     joy_tmp
        sta     joy_lo,y
        lda     joy_lo+1,y
        adc     joy_tmp+1
        sta     joy_lo+1,y
        jsr     shr_tmp
        jsr     shr_tmp         ; c/32
        sec
        lda     joy_lo,y
        sbc     joy_tmp
        sta     joy_lo,y
        lda     joy_lo+1,y
        sbc     joy_tmp+1
        sta     joy_lo+1,y      ; joy_lo = t
        ; hi = centre + t
        clc
        lda     joy_center,y
        adc     joy_lo,y
        sta     joy_hi,y
        lda     joy_center+1,y
        adc     joy_lo+1,y
        sta     joy_hi+1,y
        ; lo = centre - t, floor 0
        sec
        lda     joy_center,y
        sbc     joy_lo,y
        sta     joy_tmp
        lda     joy_center+1,y
        sbc     joy_lo+1,y
        sta     joy_tmp+1
        bcs     :+
        stz     joy_tmp
        stz     joy_tmp+1
:       lda     joy_tmp
        sta     joy_lo,y
        lda     joy_tmp+1
        sta     joy_lo+1,y
        rts

; joy_calibrate: both axes with the stick centred (called at start-up).
joy_calibrate:
        ldx     #0
        jsr     read_axis
        ldx     #0
        jsr     calibrate_axis
        ldx     #1
        jsr     read_axis
        ldx     #1
        jsr     calibrate_axis
        rts

; joy_read: one axis (alternating), then A = the direction bits of both
; axes. An axis that is off, or centred, contributes nothing; the other
; axis's bit is at most one frame old.
joy_read:
        ldx     joy_axis
        txa
        eor     #1
        sta     joy_axis        ; the other axis next frame
        stz     joy_dir,x       ; centred unless the count says otherwise
        lda     joy_ok,x
        beq     @merge
        jsr     read_axis
        txa
        asl     a
        tay                     ; Y = axis*2
        ; count < lo ?
        lda     joy_cnt
        cmp     joy_lo,y
        lda     joy_cnt+1
        sbc     joy_lo+1,y
        bcc     @low
        ; hi < count ?
        lda     joy_hi,y
        cmp     joy_cnt
        lda     joy_hi+1,y
        sbc     joy_cnt+1
        bcc     @high
        bra     @merge
@low:   lda     axis_low,x
        bra     @set
@high:  lda     axis_high,x
@set:   sta     joy_dir,x
@merge: lda     joy_dir
        ora     joy_dir+1
        rts
