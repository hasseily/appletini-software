; s2_ovd.s: part s2ovl's test driver (not the game's; docs/SCREENS.md
; 1.5.4, 4.4 "Test builds"; docs/m11-parts/s2ovl.md). It is linked after
; milestone 8's rdriver.s (-D MASKED -D FRAME8) into the card's $E000 part
; of milestone 8's whole frame (src/native/render.cfg), and runs that
; frame as rdriver.s's drv_fframe does (RENDER-MASKED.md 3.2, phases
; 1-13), with the automap overlay's step of SCREENS.md 1.5.4 between the
; masked phase and the bucket pass:
;
;   ovd_frame   the front end's window (far_wload) and nr_frame; the
;               masked phase's window (far_mload) and nm_masked (its last
;               batch staged); then, when the frame block's AUTOMAP has
;               the automap on with its overlay: OVLW's room poisoned
;               (ovd_fill: OVLW must not read what MASKW left there),
;               OVLW loaded by far_pload from its bank (OVLW_BANK, the
;               page runs at ovd_runs) and called at its first byte with A
;               = ovd_tics (am_ovl, which ends with OVLW's nm_bkload);
;               else MASKW's nm_bkload; then nb_frame (the bucket pass and
;               the replay). The cost phases: 1 the front end's window, 13
;               the masked window, 30 OVLW's load and am_ovl (with its
;               nm_bkload), 18 the bucket pass, as rdriver.s.
;   ovd_ltime   OVLW's load alone in the cost phase 30 (its time)
;
; Labels for the harness's snapshots and the write log's phases:
; ovd_fload (the walk's end), ovd_ovl (the masked phase's end, before
; OVLW), ovd_load (OVLW's load), ovd_post (after am_ovl and its
; nm_bkload), ovd_plain (a frame without the overlay: before nm_bkload).
; ovd_runs, ovd_fill and ovd_tics are the harness's (image records).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"

        .import mt_init, far_wload, nr_frame, far_mload, nm_masked
        .import far_pload, nm_bkload, nb_frame, drv_irq, drv_ret
        .importzp IRQCNT
        .export ovd_frame, ovd_fload, ovd_ovl, ovd_load, ovd_post
        .export ovd_plain
        .export ovd_ltime, ovd_runs, ovd_fill, ovd_tics

MOUSE_MODE = $C0AE              ; slot 2: mode (bit 3: the VBL interrupt)
MODE_VBL   = $08
OVLW_ENTRY = OVLW_LO            ; OVLW's first bytes: jmp am_ovl
AM_ON_OVL  = 3                  ; AUTOMAP: AM_ACTIVE | AM_OVERLAY
PZ         = $80                ; the poison's pointer (dead zero page)

        .segment "DRIVER"

ovd_frame:
        jsr ovd_setup
        cli
        lda #2                  ; the cost phase 1: the front end's load
        sta PHASE
        jsr far_wload
        stz PHASE
        jsr nr_frame
ovd_fload:
        lda #26                 ; the cost phase 13: the masked load
        sta PHASE
        jsr far_mload
        stz PHASE
        jsr nm_masked
        lda AUTOMAP             ; the overlay on: OVLW
        and #AM_ON_OVL
        cmp #AM_ON_OVL
        bne ovd_plain
ovd_ovl:
        stz PHASE               ; (the driver's phase 0: the masked phase's
        jsr poison              ;   end in the write log)
ovd_load:
        lda #60                 ; the cost phase 30: OVLW's load, am_ovl
        sta PHASE
        lda #<ovd_runs
        ldx #>ovd_runs
        ldy #OVLW_BANK
        jsr far_pload
        lda ovd_tics
        jsr OVLW_ENTRY          ; am_ovl, then OVLW's nm_bkload
ovd_post:
        bra ovd_bucket
ovd_plain:
        lda #36                 ; the cost phase 18: the bucket pass (its
        sta PHASE               ;   code into main first)
        jsr nm_bkload
ovd_bucket:
        lda #36
        sta PHASE
        jsr nb_frame            ; (it marks 18 and 12, the replay)
        stz PHASE
        jmp drv_ret

ovd_ltime:
        jsr ovd_setup
        cli
        jsr poison
        lda #60                 ; the cost phase 30: OVLW's load
        sta PHASE
        lda #<ovd_runs
        ldx #>ovd_runs
        ldy #OVLW_BANK
        jsr far_pload
        stz PHASE
        jmp drv_ret

; poison: OVLW's room ($6800-$9BFF) all ovd_fill
poison: lda #<OVLW_LO
        sta PZ
        lda #>OVLW_LO
        sta PZ+1
        lda ovd_fill
        ldy #0
:       sta (PZ),y
        iny
        bne :-
        inc PZ+1
        ldx PZ+1
        cpx #>OVLW_HI
        bne :-
        rts
        .assert <OVLW_LO = 0 && <OVLW_HI = 0, error, "OVLW's room"

; ovd_setup: rdriver.s's drv_setup without the lockstep stub's state: the
; IRQ vector (drv_irq: the VBL counted, a BRK to drv_crash), the counter,
; the mouse card's VBL interrupt (enabled by the caller's CLI)
ovd_setup:
        jsr mt_init
        lda #<drv_irq
        sta $FFFE
        lda #>drv_irq
        sta $FFFF
        stz IRQCNT
        stz IRQCNT+1
        lda #MODE_VBL
        sta MOUSE_MODE
        rts

ovd_runs: .res 16, 0            ; OVLW's page runs: page, count, ..., 0
ovd_fill: .byte $A5
ovd_tics: .byte 0
