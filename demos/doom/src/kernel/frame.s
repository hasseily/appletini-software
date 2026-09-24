; Doom for the Appletini -- the frame loop and the tic clock (docs/DESIGN.md
; section 8).
;
; Doom's game runs at 35 tics per second; the Apple's clock is the 60 Hz
; VBL interrupt (vbl_count, kstart.s). 35/60 = 7/12: every VBL adds 7 to
; an accumulator and every 12 in it make a tic, so 12 VBLs give exactly 7
; tics and 60 give 35, spread 1,1,0,1,1,0,.. as evenly as frames allow.
;
; frame_loop, forever:
;   frame_top    input_frame (input.s)
;                clock_tics: the tics due since the last pass (at most
;                MAX_TICS per rendered frame: when rendering falls further
;                behind, the extra tics are dropped and the game slows down
;                instead of stepping in bigger jumps)
;   idle_wait    no tic due: wait for the next VBL and start over (Doom
;                renders only after a tic; tools/a2sim.py skips this wait)
;                otherwise, per tic: game_tic() in GAME space (call_game);
;                after the first, input_consume
;                render_frame (RENDER space: src/render/)
;                present: the line-0 policy and the blit (video.s)
;
; Counters (KBSS, 16 bits, for the tests and tools/run_doom.py): ktics
; (tics run), kframes (frames rendered), kdropped (tics dropped).

.include "kernel.inc"

.import input_consume, _game_tic

MAX_TICS    = 4

; ---------------------------------------------------------------------------
.segment "KZP": zeropage
clk_last:   .res 1              ; vbl_count at the last clock_tics
clk_acc:    .res 1              ; 7 per VBL, a tic per 12
tics_due:   .res 1              ; tics to run this pass
tic_left:   .res 1

.segment "KBSS"
ktics:      .res 2
kframes:    .res 2
kdropped:   .res 2
.export ktics, _ktics := ktics, kframes, kdropped
.exportzp clk_last

; ---------------------------------------------------------------------------
.segment "KCODE"

frame_loop:
        lda     vbl_count
        sta     clk_last
frame_top:
        jsr     input_frame
        jsr     clock_tics
        bne     frame_run
idle_wait:                              ; tools/a2sim.py skips to the next VBL
        lda     vbl_count
        cmp     clk_last
        beq     idle_wait
        bra     frame_top
frame_run:
        sta     tic_left
        lda     #<_game_tic
        sta     kcall
        lda     #>_game_tic
        sta     kcall+1
@tic:   jsr     call_game
        inc     ktics
        bne     :+
        inc     ktics+1
:       lda     tic_left
        cmp     tics_due                ; after the first tic of the frame
        bne     :+
        jsr     input_consume
:       dec     tic_left
        bne     @tic
        jsr     render_frame
        jsr     present
        inc     kframes
        bne     frame_top
        inc     kframes+1
        bra     frame_top
.export frame_top, idle_wait

; ---------------------------------------------------------------------------
; clock_tics: A = tics_due = the tics due since the last call (0..MAX_TICS),
; Z set when none.
; ---------------------------------------------------------------------------
clock_tics:
        lda     vbl_count
        tax
        sec
        sbc     clk_last                ; VBLs since the last call
        stx     clk_last
        cmp     #13
        bcc     :+
        lda     #12                     ; 12 VBLs are 7 tics: past MAX_TICS anyway
:       tax
        stz     tics_due
        cpx     #0
        beq     @cap
@vbl:   lda     clk_acc
        clc
        adc     #7
        cmp     #12
        bcc     :+
        sbc     #12                     ; carry set
        inc     tics_due
:       sta     clk_acc
        dex
        bne     @vbl
@cap:   lda     tics_due
        cmp     #MAX_TICS+1
        bcc     @done
        sbc     #MAX_TICS               ; carry set: the tics dropped
        clc
        adc     kdropped
        sta     kdropped
        bcc     :+
        inc     kdropped+1
:       lda     #MAX_TICS
        sta     tics_due
@done:  lda     tics_due
        rts
