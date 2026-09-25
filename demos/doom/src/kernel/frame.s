; Doom for the Appletini -- the frame loop and the tic clock (docs/DESIGN.md
; section 8).
;
; Doom targets 35 tics per second, using the mouse-card VBL clock.
; Each VBL adds 7 accumulator units: PAL takes a tic per 10, NTSC per 12.
; VIDEO_HZ selects the boot default; V changes the game clock and readout.
; Run at most four tics per rendered frame. At low FPS, deliberately slow
; game time and drop excess tics instead of amplifying frame/input latency
; with long catch-up batches. PAL calibration does not change this budget.
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
;                game_frame() in GAME space: the render packet (rview)
;                render_frame (RENDER space: src/render/)
;                present: the line-0 policy and the blit (video.s)
;
; Counters (KBSS, 16 bits, for the tests and tools/run_doom.py): ktics
; (tics run), kframes (frames rendered), kdropped (tics dropped).

.include "kernel.inc"
.include "profile.inc"

.import input_consume, _game_tic, _game_frame
.ifdef BANKED_GAME
.import call_game_active
.import _debug_readout, _debug_vbl, _debug_tics, _debug_frames, _debug_hz
.endif

.ifndef VIDEO_HZ
VIDEO_HZ = 60
.endif
.assert VIDEO_HZ = 50 .or VIDEO_HZ = 60, error, "VIDEO_HZ must be 50 or 60"
MAX_TICS    = 4

; ---------------------------------------------------------------------------
.segment "KZP": zeropage
clk_last:   .res 2              ; last atomic VBL snapshot, modulo 65536
clk_acc:    .res 1              ; 7 per VBL, a tic per clk_divisor
clk_divisor:.res 1              ; 10 for PAL, 12 for NTSC
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
        jsr     clock_init
frame_top:
        PROFILE_STAGE PROF_IDLE
        jsr     input_frame
        jsr     clock_tics
        bne     frame_run
        jmp     idle_wait
frame_run:
        sta     tic_left
.ifdef BANKED_GAME
        PROFILE_STAGE PROF_GAME_COPY
        jsr     space_game
        PROFILE_STAGE PROF_GAME
.endif
        lda     #<_game_tic
        sta     kcall
        lda     #>_game_tic
        sta     kcall+1
@tic:
.ifdef BANKED_GAME
        jsr     call_game_active
.else
        jsr     call_game
.endif
        inc     ktics
        bne     :+
        inc     ktics+1
:       lda     tic_left
        cmp     tics_due                ; after the first tic of the frame
        bne     :+
        jsr     input_consume
:       dec     tic_left
        bne     @tic
        PROFILE_STAGE PROF_PACKET
        lda     #<_game_frame
        sta     kcall
        lda     #>_game_frame
        sta     kcall+1
.ifdef BANKED_GAME
        jsr     call_game_active
        PROFILE_STAGE PROF_DEBUG
        jsr     debug_sample
        PROFILE_STAGE PROF_RENDER_COPY
        jsr     space_render
        PROFILE_STAGE PROF_SETUP
.else
        jsr     call_game
.endif
        jsr     render_frame
        PROFILE_STAGE PROF_PRESENT
        jsr     present
        inc     kframes
        bne     frame_top
        inc     kframes+1
        bra     frame_top
.export frame_top, idle_wait

.ifdef BANKED_GAME
; Called after packet publication, with GAME data in main RAM and main LC
; selected. The readout borrows the now-dead path-intercept scratch. Keep the
; tiny bridge in spare D000 bank-2 space normally. PROFILE places it in
; common GAME code and uses its LC space for clock_tics instead. Formatting
; and drawing live in the weapons code bank. No CPU-speed estimate enters these measurements.
.ifdef PROFILE
.segment "GBANKCODE"
.else
.segment "KLC2"
.endif
debug_sample:
        php
        sei
        lda     vbl_count
        sta     _debug_vbl
        lda     vbl_count+1
        sta     _debug_vbl+1
        plp
        lda     ktics
        sta     _debug_tics
        lda     ktics+1
        sta     _debug_tics+1
        lda     kframes
        sta     _debug_frames
        lda     kframes+1
        sta     _debug_frames+1
        jsr     _debug_readout
.ifdef PROFILE
        jsr     clock_select
        jmp     profile_publish
.else
        jmp     clock_select
.endif
; The readout lives in GAME memory. Copy its selection into resident
; state before the renderer replaces that memory.
clock_select:
        ldx     #12
        lda     _debug_hz
        cmp     #50
        bne     :+
        ldx     #10
:       cpx     clk_divisor
        beq     :+
        stx     clk_divisor
        stz     clk_acc                 ; old fraction uses a different unit
:       rts
.export debug_sample
.segment "KCODE"
.endif

; ---------------------------------------------------------------------------
; clock_tics: A = tics_due = the tics due since the last call (0..MAX_TICS),
; Z set when none.
; ---------------------------------------------------------------------------
.segment "RCODE"
; Only called in RENDER space. Use its read-only gap below $6000 instead
; of scarce resident language-card RAM.
clock_init:
        lda     #VIDEO_HZ/5
        sta     clk_divisor
        stz     clk_acc
        php
        sei
        lda     vbl_count
        sta     clk_last
        lda     vbl_count+1
        sta     clk_last+1
        plp
        rts

idle_wait:                              ; tools/a2sim.py skips to the next VBL
        lda     vbl_count
        cmp     clk_last
        bne     @ready
        lda     vbl_count+1
        cmp     clk_last+1
        beq     idle_wait
@ready: jmp     frame_top

clock_tics:
        php
        sei
        lda     vbl_count
        ldx     vbl_count+1
        plp
        tay
        sec
        sbc     clk_last
        sta     ktmp                    ; elapsed VBLs, full 16-bit interval
        txa
        sbc     clk_last+1
        sta     ktmp+1
        sty     clk_last
        stx     clk_last+1
        stz     ktmp+2                  ; due tics before the catch-up cap
        stz     ktmp+3
        ; Whole 10/12-VBL groups each yield 7 tics. The remainder loop
        ; then needs at most 11 iterations, even after a long pause.
@group: lda     ktmp+1
        bne     @subtract
        lda     ktmp
        cmp     clk_divisor
        bcc     @remainder
@subtract:
        sec
        lda     ktmp
        sbc     clk_divisor
        sta     ktmp
        lda     ktmp+1
        sbc     #0
        sta     ktmp+1
        clc
        lda     ktmp+2
        adc     #7
        sta     ktmp+2
        bcc     @group
        inc     ktmp+3
        bra     @group
@remainder:
        ldx     ktmp
        beq     @cap
@vbl:   lda     clk_acc
        clc
        adc     #7
        cmp     clk_divisor
        bcc     :+
        sbc     clk_divisor             ; carry set
        inc     ktmp+2
        bne     :+
        inc     ktmp+3
:       sta     clk_acc
        dex
        bne     @vbl
@cap:   lda     ktmp+3
        bne     @drop
        lda     ktmp+2
        cmp     #MAX_TICS+1
        bcc     @done
@drop:  sec
        lda     ktmp+2
        sbc     #MAX_TICS
        sta     ktmp+2
        lda     ktmp+3
        sbc     #0
        sta     ktmp+3
        clc
        lda     ktmp+2
        adc     kdropped
        sta     kdropped
        lda     ktmp+3
        adc     kdropped+1
        sta     kdropped+1
        lda     #MAX_TICS
@done:  sta     tics_due
        lda     tics_due                ; frame_loop branches on the due count
        rts
.export clock_init, clock_tics
