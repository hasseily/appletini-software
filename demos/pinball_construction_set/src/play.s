; Pinball Construction Set for the Appletini -- the play loops' pacing.
;
; The upstream play loops (RUN.S PLAY7, RUN2.S PLAY/DOBALL) ran as fast as
; the CPU allowed, one tick per iteration with a WAIT delay set by the
; speed slider. The port keeps the tick bodies and replaces the pacing
; (src/patches.json): each tick starts with PORT_TICK_INPUT, which copies
; the frame's input into the runtime's variables, and ends with
; PORT_TICK_END, which counts ticks and, when the frame's ticks are done,
; renders, plays sound, waits for line 0 and reads the input again. The
; number of ticks per frame comes from the speed slider (WSET+1) as a 4.4
; fixed-point value (docs/DESIGN.md section 8).
;
; PORT_TICK_END returns the key pressed (bit 7 set) or 0, which is what
; the loops used to read from $C000.
;
; RUN2's GETPLAYERCNT and MAIN2 spin on the buttons and the keyboard:
; PORT_POLL / PORT_KEY / PORT_WAIT_FRAME step one frame per call.
;
; Zero page: none of its own.

.setcpu "65C02"
.include "pcs.inc"
.macpack longbranch
.include "assets.inc"

.export PORT_TICK_INPUT, PORT_TICK_END, PORT_POLL, PORT_KEY, PORT_WAIT_FRAME
.export MAKETBLS, MAKEBALL, LBTN
.export play_begin, play_end, play_ticks_per_frame, PORT_PLAY
.import RUN_PLAY, cur_hide, cur_want
.import frame_step, frame_fresh
.import in_flip, in_plunger, in_launch, in_btn, input_getkey
.import rd_flags, rd_mark_all, rd_ax0, rd_ax1, rd_ay0, rd_ay1, rd_mark
.import panel_sprite, panel_fill, ps_id, ps_x, ps_y, pf_x0, pf_y0, pf_x1, pf_y1, pf_color
.import SLEEPLO, SLEEPHI, SLEEPERS, PBDATA, PPAK_GETOBJ, RUN2_SETUP2
.import WSET

RD_INPLAY   = $20
RD_SLEEPERS = $10

.segment "BSS"
LBTN:       .res 1              ; the launcher's release button (bit 7)
tick_acc:   .res 1              ; 4.4 fixed point: ticks owed
tick_due:   .res 1              ; whole ticks left in this frame
ticks_run:  .res 1
balls_shown: .res 1             ; RUN2 balls-left display: bit n = ball n shown
last_plunger: .res 1            ; in_plunger of the previous tick
play_ticks_per_frame: .res 1    ; 4.4

.segment "RODATA"
; speed slider 0..7 -> ticks per frame * 16
tpf_table: .byte 24, 32, 40, 48, 64, 80, 96, 128

.segment "CODE"

; PORT_PLAY: the editor's Play tool (EDIT's PLAYSTART): RUN.S's PLAY
; between play_begin and play_end; RUN returns on Esc.
PORT_PLAY:
        lda     #0
        jsr     play_begin
        jsr     RUN_PLAY
        jmp     play_end

; play_begin: A = 0 for the editor's test play (RUN.S), $80 for the game
; (RUN2.S, with sleepers). Sets the render mode and the tick rate; the
; cursor stays hidden until the editor shows it again.
play_begin:
        pha
        jsr     cur_hide
        stz     cur_want
        lda     #MB_ST_PLAY
        sta     MB_STATE
        pla
        pha
        lda     rd_flags
        ora     #RD_INPLAY
        sta     rd_flags
        pla
        bpl     :+
        lda     rd_flags
        ora     #RD_SLEEPERS
        sta     rd_flags
:       ldx     WSET+1
        cpx     #8
        bcc     :+
        ldx     #4
:       lda     tpf_table,x
        sta     play_ticks_per_frame
        stz     tick_acc
        stz     tick_due
        stz     LBTN
        stz     balls_shown             ; the panel was cleared: no icons yet
        jsr     rd_mark_all
        ; the first frame: start with the input read once
        jsr     frame_step
        jmp     new_frame_ticks

play_end:
        lda     #MB_ST_EDIT
        sta     MB_STATE
        lda     rd_flags
        and     #<~(RD_INPLAY|RD_SLEEPERS)
        sta     rd_flags
        jmp     rd_mark_all

; new_frame_ticks: tick_due = whole ticks owed for this frame
new_frame_ticks:
        lda     tick_acc
        clc
        adc     play_ticks_per_frame
        sta     tick_acc
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     tick_due
        lda     tick_acc
        and     #$0F
        sta     tick_acc
        stz     ticks_run
        rts

; PORT_TICK_INPUT: runtime variables from the frame's input. Keeps X, Y.
;
; The launcher (RUN.S LAUNCHRUN) follows PDL1: LBTN down pulls the plunger
; back; LBTN up advances it towards PDL1/32. While the key is held, the
; plunger retreats. On release, the driver's in_launch window holds the
; charge as the plunger advances. RUN.S LAUNCHHIT uses in_launch to give
; the charged kick only after release, holding the ball on the launcher
; while charging; the original rebound and kick calculations are retained.
PORT_TICK_INPUT:
        phx
        lda     in_flip
        and     #$80
        sta     BTN0
        lda     in_flip
        asl     a
        and     #$80
        sta     BTN1
        lda     in_plunger
        sta     PDL1
        ldx     #0
        bit     in_launch
        bmi     @set                    ; released: let it go
        cmp     #0
        beq     @set
        cmp     last_plunger
        bcc     @set                    ; decaying: let it settle
        ldx     #$80                    ; charging: hold it back
@set:   stx     LBTN
        sta     last_plunger
        plx
        rts

; PORT_TICK_END: called at the end of a tick with the keyboard poll's
; place: A = key (bit 7) or 0.
PORT_TICK_END:
        inc     ticks_run
        lda     tick_due
        beq     @frame
        dec     tick_due
        bne     @more
@frame: lda     ticks_run
        sta     MB_TICKS
        jsr     frame_step
        jsr     new_frame_ticks
        jsr     input_getkey
        rts
@more:  lda     #0
        rts

; PORT_POLL: one frame, then N = the button state. These replace reads of
; $C061/$C000 that RUN2's prompts do with a live Y: X and Y are kept.
PORT_POLL:
        phx
        phy
        jsr     frame_step
        ply
        plx
        lda     in_btn
        rts

; PORT_KEY: one frame, then A = the key or 0.
PORT_KEY:
        phx
        phy
        jsr     frame_step
        jsr     input_getkey
        ply
        plx
        rts

PORT_WAIT_FRAME:
        phx
        phy
        jsr     frame_step
        ply
        plx
        rts

; ---------------------------------------------------------------------------
; MAKETBLS (RUN2): the original built the HGR tables here; the port only
; needs the sleeper slot table, then the game set-up the original did next.
; ---------------------------------------------------------------------------
MAKETBLS:
        lda     #<SLEEPERS
        sta     TEMP
        lda     #>SLEEPERS
        sta     TEMP+1
        ldy     #0
        sty     SLEEPCNT
@slot:  lda     TEMP
        sta     SLEEPLO,y
        lda     TEMP+1
        sta     SLEEPHI,y
        lda     TEMP
        clc
        adc     #23
        sta     TEMP
        bcc     :+
        inc     TEMP+1
:       iny
        cpy     #SLEEP_MAX
        bcc     @slot
        ; the original's set-up head (RUN2.S 438-442)
        lda     PBDATA
        sta     OBJCOUNT
        ldy     #0
        sty     RUNLEN
        jsr     PPAK_GETOBJ
        jmp     RUN2_SETUP2

; ---------------------------------------------------------------------------
; MAKEBALL (RUN2): Y = ball index 0..4; the original XOR-toggled a ball
; icon in the panel (balls left). The port redraws the strip.
; ---------------------------------------------------------------------------
MAKEBALL:
        lda     bitmask,y
        eor     balls_shown
        sta     balls_shown
        ; the strip: five 8-pixel cells at x = 245 + 8*i, y = 72
        ldy     #4
@ball:  phy
        tya
        asl     a
        asl     a
        asl     a
        clc
        adc     #<BALLS_X
        sta     ps_x
        sta     pf_x0
        lda     #>BALLS_X
        adc     #0
        sta     ps_x+1
        sta     pf_x0+1
        lda     #BALLS_Y
        sta     ps_y
        sta     pf_y0
        lda     bitmask,y
        and     balls_shown
        beq     @erase
        lda     #SPR_BALL_0
        sta     ps_id
        jsr     panel_sprite
        bra     @next
@erase: lda     pf_x0
        clc
        adc     #7
        sta     pf_x1
        lda     pf_x0+1
        adc     #0
        sta     pf_x1+1
        lda     #BALLS_Y+5
        sta     pf_y1
        lda     #COL_PANEL
        sta     pf_color
        jsr     panel_fill
@next:  ply
        dey
        bpl     @ball
        rts

BALLS_X = 245
BALLS_Y = 72
bitmask: .byte 1,2,4,8,16
