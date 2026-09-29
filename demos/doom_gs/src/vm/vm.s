; The 65816 interpreter of the DOOM GS port: tier 0 of the virtual 65816
; machine (docs/ARCHITECTURE.md sections 1 and 3, docs/MILESTONES.md 3.2).
; README.md in this directory describes the design, the interface and the
; memory it uses.
;
; One translation unit: the parts below are included here, so that the
; dispatch table can name every handler. ld65 places the segments
; (vm.cfg), and the size of each memory area there is the budget of
; ARCHITECTURE.md section 3.2: a part that grows past it fails the link.

        .setcpu "65C02"

; ---- the machine ----

RDMAIN          = $C002         ; RAMRD off
RDAUX           = $C003         ; RAMRD on
WRMAIN          = $C004         ; RAMWRT off
WRAUX           = $C005         ; RAMWRT on
BANKSEL         = $C073         ; RamWorks bank of aux $0200-$BFFF

; ---- the configuration: fixed by the planner of milestone 5 ----

NSLOT           = 16            ; code cache pages
CACHE           = $8800         ; the code cache: NSLOT pages of main RAM
PTAB            = $1A00         ; the page tables: up to NPTAB of 256 bytes
NPTAB           = 6

; ---- the mapping (far.s) ----
;
; A virtual 24-bit address is bank:page:offset. map0 (banks $00-$7F) and
; map1 ($80-$FF) have one entry a virtual half-bank of 32 KB, at index
; (bank * 2 + page / 128) mod 256:
;
;   $00-$7F   a flat granule: RamWorks bank n, virtual page p at physical
;             page (p & $7F) + $40, so the half-bank lies in $4000-$BFFF
;   $80+t     page table t (t < NPTAB) at PTAB + 256 * t: two bytes a
;             virtual page (p & $7F): the space, then the physical page
;   $FF       unmapped: every access traps
;
; A space is a RamWorks bank ($00-$7F, reached with RAMRD or RAMWRT and
; $C073; physical pages $02-$BF), SP_MAIN (main RAM, reached directly) or
; SP_TRAP (the access calls the trap vectors).

SP_MAIN         = $80
SP_TRAP         = $FF

; How the address of the next byte of an operand is formed (ea_next).
WR_LINEAR       = $00           ; 24 bits, carrying into the bank
WR_BANK0        = $80           ; 16 bits, wrapping in the bank
WR_PAGE         = $40           ; 8 bits, wrapping in the page

; vm_event bits: any bit set sends the dispatch loop to service.
EV_STOP         = $80           ; leave vm_run or vm_step now
EV_STEP         = $40           ; vm_step: stop after one instruction
EV_HALT         = $20           ; WAI or STP executed (vm_state 1 or 2)
EV_PAGE         = $10           ; the program counter left the code page
EV_NMI          = $02           ; an NMI is pending (set by the host)
EV_IRQ          = $01           ; the IRQ line is active (set by the host)

; vm_status after vm_run or vm_step: 0 (cleared on entry), or one of these
ST_TRAP_READ    = 1             ; the default trap vectors
ST_TRAP_WRITE   = 2
ST_TRAP_EXEC    = 3

; ---- zero page ----

        .segment "VMZP": zeropage

; The virtual 65816 registers. A, X, Y, S and D are 16-bit words, low byte
; first (A's high byte is B). With the index flag set the high bytes of X
; and Y are zero; in emulation mode S is $01xx.
vA:             .res 2
vX:             .res 2
vY:             .res 2
vS:             .res 2
vD:             .res 2
vDBR:           .res 1
vPBR:           .res 1
vE:             .res 1          ; 0 native, 1 emulation
; P and PC as the host sees them: vm_import reads them, vm_export writes
; them. In between the interpreter keeps them in the fields below.
vm_p:           .res 1
vm_pc:          .res 2

; The program counter, less one: the address of the last byte fetched.
vpcl:           .res 1
vpch:           .res 1
; P in pieces: N is bit 7 of vN, V bit 6 of vV, Z is set when vZ is zero,
; C is vC (0 or 1); vMX has M in bit 7 and X in bit 6; vP holds D and I.
vN:             .res 1
vV:             .res 1
vZ:             .res 1
vC:             .res 1
vMX:            .res 1
vP:             .res 1

vm_event:       .res 1
vm_state:       .res 1          ; 0 running, 1 waiting (WAI), 2 stopped
vm_status:      .res 1
vm_hsp:         .res 1          ; the host S at vm_run or vm_step

; The code page: cpg points at the page of main RAM holding virtual page
; cpg_pbr:cpg_vpch (a cache page, or the page itself in main RAM).
cpg:            .res 2
cpg_vpch:       .res 1
cpg_pbr:        .res 1
cpg_ok:         .res 1

; The far layer's interface: the effective address and its wrap rule.
ea:             .res 3
eawrap:         .res 1
eas:            .res 3          ; ea saved by read-modify-write
dat:            .res 2          ; an operand
tmp:            .res 4          ; handler scratch
dt:             .res 6          ; decimal scratch

; The far layer's own: the last translation, and the bank in $C073.
rptr:           .res 2          ; low byte always 0
rspace:         .res 1
rk_bank:        .res 1
rk_hi:          .res 1
curbank:        .res 1
ptp:            .res 2          ; low byte always 0
wval:           .res 1
cslot:          .res 1          ; next code cache victim

; ---- main RAM ----

        .segment "VMTAB"
; Written by the host only: the half-bank map.
map0:           .res 256
map1:           .res 256

        .segment "VMRAM"
; Written by the interpreter: the write watch (a count of cached pages by
; physical page ^ space) and the code cache tags ($FF: empty).
watch:          .res 256
ctag_space:     .res NSLOT
ctag_page:      .res NSLOT
; The trap vectors, set to the defaults by vm_init; the host may change
; them. vm_trap_rd returns the byte read in A; vm_trap_wr gets the byte
; in A; vm_trap_ex is taken when code would run from an unmapped page.
; The address is in ea.
vm_trap_rd:     .res 2
vm_trap_wr:     .res 2
vm_trap_ex:     .res 2

; ---- the interface ----

        .exportzp vA, vX, vY, vS, vD, vDBR, vPBR, vE, vm_p, vm_pc
        .exportzp vm_event, vm_state, vm_status, ea, curbank
        .export vm_init, vm_flush, vm_import, vm_export, vm_run, vm_step
        .export vm_abort, map0, map1, watch, ctag_space, ctag_page
        .export vm_trap_rd, vm_trap_wr, vm_trap_ex
        .export far_rd, far_wr, ea_next, resolve
        .export VM_PTAB, VM_CACHE, VM_NSLOT, VM_NPTAB
VM_PTAB         = PTAB
VM_CACHE        = CACHE
VM_NSLOT        = NSLOT
VM_NPTAB        = NPTAB

; The next byte of the instruction stream into A. Y is the low byte of
; the stored program counter (the address of the last byte fetched) and
; advances; crossing into the next page loads it.
.macro FETCH
        iny
        bne :+
        jsr next_page
:       lda (cpg),y
.endmacro

        .include "core.s"
        .include "modes.s"
        .include "far.s"
        .include "alu.s"
        .include "handlers.s"
