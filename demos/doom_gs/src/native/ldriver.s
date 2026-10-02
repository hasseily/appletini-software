; ldriver.s: the a2vm test driver of the level load (milestone 9, stage
; B; docs/LEVELS.md 5.4: image runs). Not part of the game: it lives in
; the card's $E000 part, which the game gives the sound and the IRQ.
;
;   drv_level   the mouse card's VBL interrupt on (a stub handler that
;               acknowledges and counts it), the load phase's image into
;               W by the phase loader (far_pload from bank LCODE: MATHW,
;               AUXW and the load code, at W's addresses), then for each
;               map of the list dl_maps (dl_n of them, the harness writes
;               them): with dl_pre's entry $FF nl_load (stage B: the
;               level's data), else (stage C) that test pre-state copied
;               from bank PRE_BANK (the game globals block and P_Random's
;               and M_Random's indexes: llayout.PRE_RECORD a record) and
;               nl_setup; the snapshot point drv_loaded after each; then
;               the halt. A BRK (a load's stop) goes to drv_crash.
;
; The harness's image (tools/native/lrun.py) is the machine after the
; boot: the store's bank files in their banks, the card (the math's
; tables and code, the far layer and the phase loader), the load image in
; LCODE, the persistent globals 0, every other byte poisoned.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .import far_pload, nl_load, nl_setup, far_get
        .import __LOADW_RUN__, __LOADW_SIZE__
        .export drv_level, drv_loaded, drv_ret, drv_halt, drv_crash
        .export drv_irq, dl_n, dl_maps, dl_k, dl_pre
        .exportzp IRQCNT

MOUSE_MODE = $C0AE              ; slot 2: mode (bit 3: the VBL interrupt)
MOUSE_ACK  = $C0AF
MODE_VBL   = $08
INTCXROMOFF = $C006

IRQCNT  = $D8                   ; the interrupts taken (the stub's)
ROOM_FIRST = $0200              ; a RamWorks bank's first byte RAMRD reaches
LIM_FIRST = $60                 ; the load image: W from $6000

        .segment "DRIVER"

drv_level:
        lda #<drv_irq           ; the IRQ vector of the card
        sta $FFFE
        lda #>drv_irq
        sta $FFFF
        stz IRQCNT
        stz IRQCNT+1
        sta INTCXROMOFF         ; (slot 7's C8 space for the memory API)
        lda #MODE_VBL
        sta MOUSE_MODE
        cli
        lda #2                  ; the cost phase 1: the image's load
        sta PHASE
        lda #<dl_runs
        ldx #>dl_runs
        ldy #LCODE
        jsr far_pload
        stz PHASE
        stz dl_k
dl_next:
        ldx dl_k
        cpx dl_n
        bcs drv_ret
        lda dl_pre,x
        cmp #$FF
        bne @setup
        lda dl_maps,x
        jsr nl_load
        bra drv_loaded
@setup: jsr drv_pre             ; the pre-state, then P_SetupLevel
        ldx dl_k
        lda dl_maps,x
        jsr nl_setup
drv_loaded:
        inc dl_k
        bra dl_next
drv_ret:
        sei
        stz MOUSE_MODE
        lda #3
        sta MOUSE_ACK
drv_halt:
        bra drv_halt
drv_crash:
        bra drv_crash

; drv_irq: the mouse card's VBL: acknowledged and counted. A BRK (the B
; bit of the pushed P) goes to drv_crash, where a2vm stops.
drv_irq:
        pha
        phx
        tsx
        lda $0103,x
        and #$10
        bne @brk
        lda #3
        sta MOUSE_ACK
        inc IRQCNT
        bne :+
        inc IRQCNT+1
:       plx
        pla
        rti
@brk:   jmp drv_crash

; drv_pre: test pre-state A (bank PRE_BANK, $0200 + PRE_RECORD A): the
; game globals block into main GBLOCK (whole pages: the bytes after the
; block's used part are the record's), then P_Random's and M_Random's
; indexes into PRND, PRND + 1; one RAMRD window, the driver's own copy
drv_pre:
        tax
        lda #<ROOM_FIRST
        sta FA_SRC
        lda #>ROOM_FIRST
        sta FA_SRC+1
:       dex                     ; + PRE_RECORD a record
        bmi :+
        clc
        lda FA_SRC
        adc #<PRE_RECORD
        sta FA_SRC
        lda FA_SRC+1
        adc #>PRE_RECORD
        sta FA_SRC+1
        bra :-
:       lda #<GBLOCK
        sta FA_DST
        lda #>GBLOCK
        sta FA_DST+1
        lda #PRE_BANK
        sta RWBANK
        sta RAMRDON
        ldx #>(PRE_RND + $FF)
        ldy #0
@page:  lda (FA_SRC),y
        sta (FA_DST),y
        iny
        bne @page
        inc FA_SRC+1
        inc FA_DST+1
        dex
        bne @page
        sec                     ; the indexes: the record + PRE_RND
        lda FA_SRC+1
        sbc #>(PRE_RND + $FF)
        sta FA_SRC+1
        ldy #<PRE_RND
        lda #>PRE_RND
        clc
        adc FA_SRC+1
        sta FA_SRC+1
        lda (FA_SRC),y
        sta PRND
        iny
        bne :+
        inc FA_SRC+1
:       lda (FA_SRC),y
        sta PRND+1
        iny                     ; then validcount (the frame block's,
        bne :+                  ;   G_VALID: milestone 10)
        inc FA_SRC+1
:       lda (FA_SRC),y
        sta G_VALID
        iny
        bne :+
        inc FA_SRC+1
:       lda (FA_SRC),y
        sta G_VALID+1
        sta RAMRDOFF
        stz RWBANK
        rts
        .assert PRE_VALID = PRE_RND + 2, error, "validcount after the indexes"
        .assert GBLOCK + ((PRE_RND + $FF) & $FF00) <= $2000, error, "pre-state pages"
        .assert PRE_RECORD >= ((PRE_RND + $FF) & $FF00), error, "pre-state pages"

; the load image's pages (far_pload's list: in the card, near in its
; window)
dl_runs:
        .byte LIM_FIRST
        .byte <(((__LOADW_RUN__ + __LOADW_SIZE__ + $FF) >> 8) - LIM_FIRST)
        .byte 0

        .segment "DESC"
dl_k:   .res 1                  ; the maps loaded so far
dl_n:   .res 1                  ; the list (the harness's)
dl_maps:
        .res DL_MAX
dl_pre:                         ; each map's pre-state ($FF: nl_load alone)
        .res DL_MAX
