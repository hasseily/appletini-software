; Appletini Bosconian -- keyboard, button and joystick driver.
;
; C interface (bosco.h, docs/DESIGN.md section 7):
;   u8   input_keys(void);          keyboard + Apple/game buttons -> IN_* mask
;   void input_joy_calibrate(void); sample both axes with the stick centered
;   u8   input_joy(void);           one axis per call -> IN_* direction bits
;
; Bus cost per call (every $C0xx access is a 1 MHz bus cycle on the
; virtual TransWarp): input_keys makes exactly four accesses ($C000,
; $C010, $C061, $C062). input_joy makes one $C070 trigger plus one $C064
; or $C065 read per poll, at most JOY_CAP polls, with a CPU-only delay of
; about 40 cycles between polls.
;
; Keys (upper or lower case):
;   arrows / I J K L      up left down right
;   U O M , .             diagonals (U=up-left O=up-right M=down-left
;                         , and . = down-right)
;   Space                 IN_FIRE
;   Return                IN_START
;   Esc                   IN_PAUSE | IN_QUIT (the game picks by state)
;   P                     IN_PAUSE
;   Q                     IN_QUIT
;   Open/Closed Apple, game buttons 0/1: IN_FIRE
;
; Hold behavior: the //e latches one key and its strobe. When a call finds
; no new strobe, it reads $C010: bit 7 there is "any key down". While it
; is set, the direction/fire bits of the last key are reported again so
; holding Space keeps firing and holding a direction keeps steering.
; IN_START, IN_PAUSE and IN_QUIT are reported only on the call that saw
; the key strobe, so they act as edges.
;
; Zero page: $60-$6F (ZP_INPUT in bosco.inc). Nothing here runs with
; RAMWRT on; all variables are in BSS ($0C00-$1FFF).

.setcpu "65C02"
.include "bosco.inc"

.export _input_keys, _input_joy_calibrate, _input_joy

IN_UP    = $01
IN_DOWN  = $02
IN_LEFT  = $04
IN_RIGHT = $08
IN_FIRE  = $10
IN_START = $20
IN_PAUSE = $40
IN_QUIT  = $80
IN_HELD_MASK = IN_UP | IN_DOWN | IN_LEFT | IN_RIGHT | IN_FIRE

; joystick tuning
JOY_CAP   = 400         ; polls per axis read (upper bound on bus cycles)
JOY_DELAY = 7           ; dey/bne iterations: 2 + 7*5 - 1 + 3 (bra) = 39 cycles

; zero page scratch
zp_mask  = ZP_INPUT + 0 ; $60 mask being built
zp_cnt   = ZP_INPUT + 2 ; $62-$63 poll count
zp_tmp   = ZP_INPUT + 4 ; $64-$65 shift scratch
zp_axis  = ZP_INPUT + 6 ; $66 axis of the current input_joy call

.segment "BSS"
key_hold:   .res 1      ; held direction/fire bits of the last key
joy_axis:   .res 1      ; 0 = read X next, 1 = read Y next
joy_ok:     .res 2      ; per axis: 1 when calibrated and not capped
joy_lo:     .res 4      ; per axis u16: below -> left/up
joy_hi:     .res 4      ; per axis u16: above -> right/down
joy_center: .res 4      ; per axis u16: calibrated count

.segment "RODATA"
; key code (upper case) and mask, zero terminated
key_table:
        .byte $08, IN_LEFT
        .byte $15, IN_RIGHT
        .byte $0B, IN_UP
        .byte $0A, IN_DOWN
        .byte 'I', IN_UP
        .byte 'J', IN_LEFT
        .byte 'K', IN_DOWN
        .byte 'L', IN_RIGHT
        .byte 'U', IN_UP | IN_LEFT
        .byte 'O', IN_UP | IN_RIGHT
        .byte 'M', IN_DOWN | IN_LEFT
        .byte ',', IN_DOWN | IN_RIGHT
        .byte '.', IN_DOWN | IN_RIGHT
        .byte ' ', IN_FIRE
        .byte $0D, IN_START
        .byte $1B, IN_PAUSE | IN_QUIT
        .byte 'P', IN_PAUSE
        .byte 'Q', IN_QUIT
        .byte 0

.segment "CODE"

; ---------------------------------------------------------------------------
; u8 input_keys(void)
; ---------------------------------------------------------------------------
_input_keys:
        lda     KBD
        bmi     @new_key
        ; No new strobe. $C010 bit 7 = any key down (reading it clears a
        ; strobe, but there is none right now).
        lda     KBDSTRB
        bpl     @released
        lda     key_hold
        bra     @buttons
@released:
        stz     key_hold
        lda     #0
        bra     @buttons

@new_key:
        sta     KBDSTRB         ; clear the strobe (write, no read side effect)
        and     #$7F
        cmp     #'a'
        bcc     @lookup
        cmp     #'z'+1
        bcs     @lookup
        sbc     #$1F            ; carry clear: subtract $20 -> upper case
@lookup:
        ldx     #0
@next:
        ldy     key_table,x
        beq     @unknown
        cmp     key_table,x
        beq     @found
        inx
        inx
        bra     @next
@found:
        lda     key_table+1,x
        tay
        and     #IN_HELD_MASK
        sta     key_hold
        tya
        bra     @buttons
@unknown:
        stz     key_hold
        lda     #0

@buttons:
        sta     zp_mask
        lda     BUTTON0
        ora     BUTTON1
        bpl     @done
        lda     zp_mask
        ora     #IN_FIRE
        sta     zp_mask
@done:
        lda     zp_mask
        ldx     #0
        rts

; ---------------------------------------------------------------------------
; read_axis: X = 0 (PADDLE0) or 1 (PADDLE1). Returns the poll count in
; zp_cnt (0..JOY_CAP). One $C070 trigger, then one paddle read per poll.
; ---------------------------------------------------------------------------
read_axis:
        stz     zp_cnt
        stz     zp_cnt+1
        lda     PTRIG           ; start both paddle timers
@poll:
        lda     PADDLE0,x
        bpl     @done           ; timer expired: bit 7 clear
        inc     zp_cnt
        bne     @check
        inc     zp_cnt+1
@check:
        lda     zp_cnt+1
        cmp     #>JOY_CAP
        bcc     @delay
        lda     zp_cnt
        cmp     #<JOY_CAP
        bcs     @done           ; cap reached
@delay:
        ldy     #JOY_DELAY      ; CPU-only wait, no bus access
@wait:
        dey
        bne     @wait
        bra     @poll
@done:
        rts

; ---------------------------------------------------------------------------
; shr_tmp: zp_tmp >>= 1 (16 bit)
; ---------------------------------------------------------------------------
shr_tmp:
        lsr     zp_tmp+1
        ror     zp_tmp
        rts

; ---------------------------------------------------------------------------
; calibrate_axis: X = axis (0/1). Uses zp_cnt as the centered count and
; stores center, lo = center - 35%, hi = center + 35%. The 35% is
; computed as c/4 + c/8 - c/32 = 0.344 c. A count at the cap means the
; timer never expired inside the poll budget: the axis is switched off.
; ---------------------------------------------------------------------------
calibrate_axis:
        txa
        asl     a
        tay                     ; Y = axis*2 (u16 table index)
        lda     zp_cnt
        sta     joy_center,y
        lda     zp_cnt+1
        sta     joy_center+1,y
        ; capped?
        lda     zp_cnt+1
        cmp     #>JOY_CAP
        bcc     @usable
        lda     zp_cnt
        cmp     #<JOY_CAP
        bcc     @usable
        stz     joy_ok,x
        rts
@usable:
        lda     #1
        sta     joy_ok,x
        ; t = a + b - d with a = c>>2, b = c>>3, d = c>>5; t built in joy_lo
        lda     zp_cnt
        sta     zp_tmp
        lda     zp_cnt+1
        sta     zp_tmp+1
        jsr     shr_tmp
        jsr     shr_tmp         ; a
        lda     zp_tmp
        sta     joy_lo,y
        lda     zp_tmp+1
        sta     joy_lo+1,y
        jsr     shr_tmp         ; b
        clc
        lda     joy_lo,y
        adc     zp_tmp
        sta     joy_lo,y
        lda     joy_lo+1,y
        adc     zp_tmp+1
        sta     joy_lo+1,y
        jsr     shr_tmp
        jsr     shr_tmp         ; d
        sec
        lda     joy_lo,y
        sbc     zp_tmp
        sta     joy_lo,y
        lda     joy_lo+1,y
        sbc     zp_tmp+1
        sta     joy_lo+1,y      ; joy_lo = t
        ; hi = center + t
        clc
        lda     joy_center,y
        adc     joy_lo,y
        sta     joy_hi,y
        lda     joy_center+1,y
        adc     joy_lo+1,y
        sta     joy_hi+1,y
        ; lo = center - t (floor at 0)
        sec
        lda     joy_center,y
        sbc     joy_lo,y
        sta     zp_tmp
        lda     joy_center+1,y
        sbc     joy_lo+1,y
        sta     zp_tmp+1
        bcs     @store_lo
        stz     zp_tmp
        stz     zp_tmp+1
@store_lo:
        lda     zp_tmp
        sta     joy_lo,y
        lda     zp_tmp+1
        sta     joy_lo+1,y
        rts

; ---------------------------------------------------------------------------
; void input_joy_calibrate(void)
; ---------------------------------------------------------------------------
_input_joy_calibrate:
        ldx     #0
        jsr     read_axis
        ldx     #0
        jsr     calibrate_axis
        ldx     #1
        jsr     read_axis
        ldx     #1
        jsr     calibrate_axis
        stz     joy_axis
        rts

; ---------------------------------------------------------------------------
; u8 input_joy(void)
; Reads X on one call and Y on the next. Returns direction bits only
; (no buttons: input_keys already reports them).
; ---------------------------------------------------------------------------
_input_joy:
        lda     joy_axis
        sta     zp_axis
        eor     #1
        sta     joy_axis
        ldx     zp_axis
        lda     joy_ok,x
        beq     @none
        jsr     read_axis
        lda     zp_axis
        asl     a
        tay                     ; Y = axis*2
        ; count < lo ?
        lda     zp_cnt
        cmp     joy_lo,y
        lda     zp_cnt+1
        sbc     joy_lo+1,y
        bcc     @low
        ; count > hi ?  (hi < count)
        lda     joy_hi,y
        cmp     zp_cnt
        lda     joy_hi+1,y
        sbc     zp_cnt+1
        bcc     @high
@none:
        lda     #0
        ldx     #0
        rts
@low:
        lda     zp_axis
        bne     @up
        lda     #IN_LEFT
        ldx     #0
        rts
@up:
        lda     #IN_UP
        ldx     #0
        rts
@high:
        lda     zp_axis
        bne     @down
        lda     #IN_RIGHT
        ldx     #0
        rts
@down:
        lda     #IN_DOWN
        ldx     #0
        rts
