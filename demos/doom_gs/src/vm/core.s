; The core: the entry points, the dispatch loop, events and interrupts,
; the code page cache, and P in and out.

        .segment "CORE"

; ---- entry points, at fixed addresses from $E000 ----

vm_init:        jmp init        ; once: empty cache, default traps, $C073 = 0
vm_flush:       jmp flush       ; after the host changes the map or memory
vm_import:      jmp import      ; vm_p, vm_pc into the interpreter
vm_export:      jmp export      ; and back
vm_run:         jmp run         ; run until an event stops it
vm_step:        jmp step        ; one instruction, or one interrupt entry
vm_abort:       jmp abort       ; A = status: leave vm_run or vm_step

run:    tsx
        stx vm_hsp
        stz vm_status
        bra loop

step:   tsx
        stx vm_hsp
        stz vm_status
        lda #EV_STEP
        tsb vm_event

; ---- the dispatch loop ----
;
; Every handler is entered with Y the low byte of the stored program
; counter (the opcode's address) and must store Y in vpcl once it has
; fetched its operands. It ends with jmp loop.

loop:   lda vm_event
        bne service
fetch:  ldy vpcl
        iny
        bne :+
        jsr next_page
:       lda (cpg),y
        asl a
        tax
        bcs :+
        jmp (optab,x)
:       jmp (optab+256,x)

; An event: A = vm_event.
; The host's interrupt handler may set EV_IRQ or EV_NMI at any time, so
; vm_event changes only by TSB and TRB here.
service:
        bit vm_event
        bmi leave
        bvc @nostep
        lda #EV_STEP            ; this instruction is the last
        trb vm_event
        lda #EV_STOP
        tsb vm_event
@nostep:
        lda vm_event
        and #EV_HALT
        beq @running
        lda vm_state            ; WAI ends on an interrupt line, STP never
        cmp #2
        beq @idle
        lda vm_event
        and #EV_NMI | EV_IRQ
        beq @idle
        stz vm_state
        lda #EV_HALT
        trb vm_event
@running:
        lda vm_event
        and #EV_NMI
        bne @nmi
        lda vm_event
        and #EV_IRQ
        beq @page
        lda vP
        and #$04                ; I
        bne @page
        ldx #$EE                ; native IRQ vector
        ldy #$FE                ; emulation IRQ vector
        bra @hardware
@nmi:   lda #EV_NMI
        trb vm_event
        ldx #$EA
        ldy #$FA
@hardware:
        lda vE
        beq :+
        tya
        tax
:       phx
        jsr getp
        ldx vE
        beq :+
        and #$EF                ; emulation: pushed with B clear
:       plx
        jsr interrupt
@idle:  jmp loop
@page:  lda vm_event
        and #EV_PAGE
        beq fetch
        lda #EV_PAGE
        trb vm_event
        ldy vpcl                ; at the end of a page the fetch itself
        cpy #$FF                ; moves to the next one
        beq :+
        jsr ensure_page         ; with Y = vpcl (see load_page's @trap)
:       jmp fetch

leave:  lda #EV_STOP
        trb vm_event
        ldx vm_hsp
        txs
        rts

; Leave vm_run or vm_step at once, with status A (a trap handler's exit).
abort:  sta vm_status
        sta RDMAIN
        sta WRMAIN
        lda #EV_STOP | EV_STEP
        trb vm_event
        ldx vm_hsp
        txs
        rts

; The default trap handlers.
trap_rd:
        lda #ST_TRAP_READ
        bra abort
trap_wr:
        lda #ST_TRAP_WRITE
        bra abort
trap_ex:
        lda #ST_TRAP_EXEC
        bra abort

; Interrupt entry (BRK, COP, IRQ, NMI): A = P to push, X = the low byte of
; the vector in $00:FFxx. Native mode pushes PBR too.
interrupt:
        sta tmp+2
        stx tmp+3
        lda vE
        bne :+
        lda vPBR
        jsr push8
:       lda vpcl                ; the program counter, stored + 1
        clc
        adc #1
        sta tmp
        lda vpch
        adc #0
        jsr push8
        lda tmp
        jsr push8
        lda tmp+2
        jsr push8
        lda vP
        ora #$04                ; I set
        and #$F7                ; D clear
        sta vP
        stz vPBR
        lda tmp+3
        sta ea
        lda #$FF
        sta ea+1
        stz ea+2
        lda #WR_BANK0
        sta eawrap
        jsr rdptr16
        ; fall into set_pc

; The program counter becomes tmp (a word) in bank vPBR.
set_pc: lda tmp
        sec
        sbc #1
        sta vpcl
        lda tmp+1
        sbc #0
        sta vpch
        ; fall into pc_moved

; After a change of vpch or vPBR: at the next instruction the code page
; must be looked up again, unless it is still the current one. Nothing is
; fetched here, so a jump costs no access to memory the 65816 would not
; touch.
pc_moved:
        lda cpg_ok
        beq :+
        lda vpch
        cmp cpg_vpch
        bne :+
        lda vPBR
        cmp cpg_pbr
        beq :++
:       lda #EV_PAGE
        tsb vm_event
:       rts

; ---- the code page cache ----

; The fetch crossed into the next page: Y = 0.
next_page:
        inc vpch
        ; fall into ensure_page

; Make cpg the page of vPBR:vpch. Keeps Y. Called by next_page with
; Y = 0 and vpcl not 0 (the fetch was at $FF, at most three bytes after
; the stored program counter), by the service of EV_PAGE with Y = vpcl:
; so a trap tells a fetch that crossed into the page, whose move of vpch
; it takes back.
ensure_page:
        lda cpg_ok
        beq load_page
        lda vpch
        cmp cpg_vpch
        bne load_page
        lda vPBR
        cmp cpg_pbr
        bne load_page
        rts
load_page:
        phy
        lda vPBR
        sta cpg_pbr
        ldx vpch
        stx cpg_vpch
        jsr resolve
        bmi @special
        ldx #NSLOT - 1          ; a RamWorks page: in the cache?
@scan:  lda ctag_page,x
        cmp rptr+1
        bne @next
        lda ctag_space,x
        cmp rspace
        beq @hit
@next:  dex
        bpl @scan
        ldx cslot               ; no: replace the next victim
        lda ctag_space,x
        bmi @empty
        eor ctag_page,x
        phx
        tax
        dec watch,x
        plx
@empty: lda rspace
        sta ctag_space,x
        lda rptr+1
        sta ctag_page,x
        eor rspace
        phx
        tax
        inc watch,x
        plx
        txa
        inc a
        and #NSLOT - 1
        sta cslot
        txa
        clc
        adc #>CACHE
        sta cpg+1
        lda rspace
        cmp curbank
        beq :+
        sta curbank
        sta BANKSEL
:       ldy #0
        sta RDAUX
@copy:  lda (rptr),y
        sta (cpg),y
        iny
        bne @copy
        sta RDMAIN
        bra @done
@hit:   txa
        clc
        adc #>CACHE
        sta cpg+1
@done:  lda #1
        sta cpg_ok
        ply
        rts
@special:
        cmp #SP_MAIN
        bne @trap
        lda rptr+1              ; main RAM runs in place
        sta cpg+1
        bra @done
; The page is not mapped. When a fetch crossed into it (Y = 0), vpch goes
; back to the page before, so that the stored program counter is again
; the one before that fetch: vm_export gives the address of the
; instruction (of the opcode at the page's first byte, or of one whose
; operand runs into the page; JSL and JSR (a,x), which store their
; progress to push it before their last operand byte, give that byte),
; and a new run fetches it again. EV_PAGE makes that run look the page
; up again, since cpg is no longer valid. vm_trap_ex must not return.
; The path is as long as it was without these rules (the rest is in
; trap_page, after the core), so the code after it keeps its addresses,
; and with them the costs of docs/INTERPRETER.md, which depend on them
; through the TURBO caches of the cost model.
@trap:  ply
        bne :+
        lda vpcl
        beq :+
        dec vpch
:       stz cpg_ok
        lda #EV_PAGE
        jmp trap_page

; ---- P ----

; A = P from its pieces.
getp:   lda vC
        ldx vZ
        bne :+
        ora #$02
:       ora vP
        bit vMX
        bpl :+
        ora #$20
:       bvc :+
        ora #$10
:       sta dt
        lda vN
        and #$80
        ora dt
        sta dt
        lda vV
        and #$40
        ora dt
        rts

; P = A, then the rules of the mode: in emulation M and X are set and S
; is in page 1; with X set the high bytes of X and Y are zero.
setp:   sta vN
        sta vV
        tax
        and #$01
        sta vC
        txa
        and #$0C
        sta vP
        txa
        and #$02
        eor #$02
        sta vZ
        txa
        asl a
        asl a
        and #$C0
        sta vMX
normalise:
        lda vE
        beq :+
        lda #$C0
        sta vMX
        lda #1
        sta vS+1
:       bit vMX
        bvc :+
        stz vX+1
        stz vY+1
:       rts

; ---- the host's calls ----

import: lda vm_p
        jsr setp
        lda vm_pc
        sec
        sbc #1
        sta vpcl
        lda vm_pc+1
        sbc #0
        sta vpch
        stz vm_state
        stz cpg_ok
        lda vm_event
        and #EV_NMI | EV_IRQ
        ora #EV_PAGE
        sta vm_event
        rts

export: jsr getp
        sta vm_p
        lda vpcl
        clc
        adc #1
        sta vm_pc
        lda vpch
        adc #0
        sta vm_pc+1
        rts

; Forget every cached page and translation.
flush:  ldy #NSLOT - 1
@slot:  lda ctag_space,y
        bmi @next
        eor ctag_page,y
        tax
        stz watch,x
        lda #$FF
        sta ctag_space,y
@next:  dey
        bpl @slot
        stz cslot
        stz cpg_ok
        lda #EV_PAGE
        tsb vm_event
        lda #0
        tax
        jmp resolve_look

init:   stz rptr
        stz ptp
        stz cpg
        ldx #0
:       stz watch,x
        inx
        bne :-
        ldx #NSLOT - 1
        lda #$FF
:       sta ctag_space,x
        stz ctag_page,x
        dex
        bpl :-
        stz cslot
        stz cpg_ok
        stz vm_event
        stz vm_state
        stz vm_status
        stz curbank
        stz BANKSEL
        sta RDMAIN
        sta WRMAIN
        lda #<trap_rd
        sta vm_trap_rd
        lda #>trap_rd
        sta vm_trap_rd+1
        lda #<trap_wr
        sta vm_trap_wr
        lda #>trap_wr
        sta vm_trap_wr+1
        lda #<trap_ex
        sta vm_trap_ex
        lda #>trap_ex
        sta vm_trap_ex+1
        lda #0
        tax
        jmp resolve_look

; ---- the dispatch table ----

optab:
        .repeat 256, I
        .word .ident(.sprintf("h%02X", I))
        .endrepeat

; ---- after the core ----
;
; vm.cfg places this segment after all of CORE (this file and modes.s),
; so that code added here moves nothing the dispatch loop and the
; handlers use.

        .segment "CORETAIL"

; The rest of load_page's @trap: A = EV_PAGE.
trap_page:
        tsb vm_event
        lda vPBR
        sta ea+2
        lda cpg_vpch
        sta ea+1
        stz ea
        jmp (vm_trap_ex)
