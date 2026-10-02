; s2_drv.s: the a2vm test driver of milestone 11's first half (docs/
; SCREENS.md 4.4 "Test builds", 7.3 part s2lay). Not part of the game: it
; lives in the card's $F900-$FEFF, the replay's place, which no 2D test
; image has (src/native/ldriver.s is the model).
;
;   s2d_start   the IRQ vector (pl_vbl when the build links it, -D PL_VBL;
;               else a stub that acknowledges the mouse card's VBL and
;               counts it in s2d_vbls), the mouse card's VBL interrupt on,
;               then each load of s2d_loads (a bank and its page runs, by
;               far_pload, the cost phase 0), then each call of the list
;               (the routine with A, X, Y; the cost phase 30 around it),
;               the snapshot point s2d_called after each, then the stop
;               S2S_DONE.
;   the stops   a stop code in PL_STATUS ($03AE, LV_STATUS's byte), then
;               BRK: the vector's handler sees the B bit and goes to
;               s2d_brk, which turns the VBL off and ends at s2d_stop
;               (a2vm's stop). The driver writes S2S_RUN first and S2S_DONE
;               at the end; a routine that stops writes its own code; a BRK
;               that wrote none leaves S2S_RUN. The handler writes nothing
;               outside the IRQ contract (MEMORY_MAP.md rule 2), so a BRK
;               in a RAMWRT window stops cleanly.
;
; The harness (tools/native/s2run.py) writes the descriptors (DESC) into
; the card's image before the run: the runs page, the loads, the calls.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .import far_pload
.ifdef PL_VBL
        .import pl_vbl
.endif
        .export s2d_start, s2d_called, s2d_ret, s2d_brk, s2d_stop, s2d_irq
        .export s2d_runs, s2d_nloads, s2d_lbank, s2d_lrun, s2d_ncalls
        .export s2d_clo, s2d_chi, s2d_ca, s2d_cx, s2d_cy, s2d_k, s2d_vec
        .export s2d_vbls

MOUSE_MODE = $C0AE              ; slot 2: mode (bit 3: the VBL interrupt)
MOUSE_ACK  = $C0AF
MODE_VBL   = $08
INTCXROMOFF = $C006
IRQ_VECTOR = $FFFE

.ifdef PL_VBL
HANDLER = pl_vbl
.else
HANDLER = s2d_irq
.endif

        .segment "DRIVER"

s2d_start:
        sei
        lda #S2S_RUN
        sta PL_STATUS
        lda #<HANDLER
        sta IRQ_VECTOR
        lda #>HANDLER
        sta IRQ_VECTOR+1
        stz s2d_vbls
        stz s2d_vbls+1
        sta INTCXROMOFF         ; (slot 7's C8 space for the memory API)
        lda #MODE_VBL
        sta MOUSE_MODE
        lda #PHV_DRIVER         ; the cost phase 0: the driver, the loads
        sta PHASE
        cli
        stz s2d_k
@load:  ldx s2d_k               ; each load: far_pload of its runs (a list
        cpx s2d_nloads          ;   in the runs page) from its bank
        bcs @calls
        lda s2d_lrun,x
        ldy s2d_lbank,x
        ldx #>s2d_runs
        jsr far_pload
        inc s2d_k
        bra @load
@calls: stz s2d_k
s2d_next:
        ldx s2d_k
        cpx s2d_ncalls
        bcs s2d_ret
        lda s2d_clo,x
        sta s2d_vec
        lda s2d_chi,x
        sta s2d_vec+1
        ldy s2d_cy,x
        lda s2d_cx,x
        pha
        lda #PHV_2D             ; the cost phase 30 around the routine
        sta PHASE
        lda s2d_ca,x
        plx
        jsr s2d_jump
        stz PHASE
        sei                     ; (no interrupt returns to the point: one
s2d_called:                     ;   snapshot a call; request S2DRAW-3)
        cli
        inc s2d_k
        bra s2d_next
s2d_ret:
        lda #S2S_DONE
        sta PL_STATUS
        brk
        .byte $00
s2d_jump:
        jmp (s2d_vec)

; s2d_irq: the mouse card's VBL, acknowledged and counted. A BRK (the B
; bit of the pushed P) goes to s2d_brk.
s2d_irq:
        pha
        phx
        tsx
        lda $0103,x
        and #$10
        bne s2d_brk
        lda #3
        sta MOUSE_ACK
        inc s2d_vbls
        bne :+
        inc s2d_vbls+1
:       plx
        pla
        rti

; s2d_brk: the stop (from a BRK, by any handler): the VBL off; a2vm stops
; at s2d_stop
s2d_brk:
        sei
        stz MOUSE_MODE
        lda #3
        sta MOUSE_ACK
s2d_stop:
        bra s2d_stop

; the descriptors, which the harness writes: the runs page first (a
; far_pload list does not cross a page)
        .segment "DESC"
s2d_runs:
        .res 256
s2d_nloads:
        .res 1
s2d_lbank:                      ; each load's bank
        .res DRV_LOADS
s2d_lrun:                       ; each load's runs, an offset in the page
        .res DRV_LOADS
s2d_ncalls:
        .res 1
s2d_clo:                        ; each call's routine, low and high
        .res DRV_CALLS
s2d_chi:
        .res DRV_CALLS
s2d_ca:                         ; and its A, X, Y
        .res DRV_CALLS
s2d_cx:
        .res DRV_CALLS
s2d_cy:
        .res DRV_CALLS
s2d_k:                          ; the load or the call being made
        .res 1
s2d_vec:                        ; the routine's address
        .res 2
s2d_vbls:                       ; the stub's count of VBL interrupts
        .res 2
