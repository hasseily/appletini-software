; pl_bridge.s: the aux card's IRQ bridge (milestone 11, part plclock;
; docs/SCREENS.md 2.3 "The aux-card copy", MEMORY_MAP.md 4.4). GPL-2, the
; port's own.
;
; For the pair build (milestone 13: tics with ALTZP on). On F1.2.1 the aux
; card is full of tables and ALTZP is on only with interrupts masked (rule
; 7), so no build links this yet; part plclock tests it on a synthetic
; machine whose aux card holds only these bytes and its vectors.
;
; These bytes sit at $FF00 in BOTH cards, the same bytes at the same
; addresses: an interrupt with ALTZP on fetches the aux card's vector and
; enters at pl_bridge in the aux card; after the store to ALTZPOFF the next
; instruction is fetched from the main card's copy, and after the store to
; ALTZPON from the aux card's again (MEMORY_MAP.md 4.4: "the same bytes as
; main $FF00-$FFF9 at the addresses where the fetch crosses cards").
;
;   pl_bridge   A, X, Y saved on the aux stack; a BRK (the pushed P's B
;               bit, read on the aux stack) goes to pl_crash with ALTZP off;
;               else ALTZP off, pl_vbody (the main handler's body: the
;               mouse card, the clock, the effects, the music) on the main
;               stack, ALTZP on, A, X, Y back and RTI from the aux stack
;
; The main stack: S is not changed when ALTZP switches, so pl_vbody's
; pushes land on main page 1 below S. That is free there as long as the
; program switched ALTZP on with its main S and runs with S at or below it
; (the tic code under ALTZP pushes and pulls only its own frames), which is
; how the pair build enters its tic window. pl_vbody takes 2 bytes for its
; return and its callees' depth; the aux stack takes 6 (the interrupt's 3,
; A, X, Y).

        .setcpu "65C02"

        .import pl_vbody, pl_crash
        .export pl_bridge, pl_bnmi

ALTZPOFF = $C008
ALTZPON  = $C009

        .segment "PLBRIDGE"

pl_bridge:
        pha
        phx
        phy
        tsx
        lda $0104,x             ; the pushed P, on the aux stack
        and #$10
        bne pl_bbrk
        sta ALTZPOFF            ; from here the main card's copy of these bytes
        jsr pl_vbody            ; the main zero page, stack and card
        sta ALTZPON             ; from here the aux card's copy
        ply
        plx
        pla
pl_bnmi:
        rti                     ; from the aux stack
pl_bbrk:   sta ALTZPOFF
        jmp pl_crash

; the aux card's vectors: NMI an RTI, reset unused (the ROM's), IRQ/BRK;
; only addresses in these bytes, which both cards hold
        .segment "AUXVEC"
        .word pl_bnmi, pl_bnmi, pl_bridge
