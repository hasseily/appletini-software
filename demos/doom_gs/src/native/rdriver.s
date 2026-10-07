; rdriver.s: the native renderer's driver for host runs on a2vm (not part
; of the game; docs/RENDER.md). It lives in the card's $E000 part,
; which the game gives the sound and the IRQ code. Of its builds only
; rdriver-f.o (-D MASKED -D FRAME8, render.mk) is made now: m11/s2ovl.mk
; links it into the whole frame ovf, whose map places OVLW (s2_ovd.s,
; linked after it, is that frame's driver). The other entries and the
; LOCKSTEP stub are kept as written.
;
;   drv_frame   one frame: the mouse card's VBL interrupt on (a stub
;               handler that acknowledges and counts it), nr_frame between
;               drv_call and drv_ret, then the halt. With -D LOCKSTEP
;               the lockstep stub below is nr_storewall.
;   drv_wframe  the same, the render window first loaded from its image
;               in RamWorks (far_wload, the phase loader: the frame
;               mode, RENDER.md), between drv_wload and drv_call
;   drv_bulk    the cases of a descriptor: for
;               each, its input bytes to their places (or the registers A,
;               X, Y), the call, its output bytes to the results; cases
;               and results in RamWorks banks. For rt_side and the aux
;               card's reads.
;   drv_wall    routine mode (RENDER.md): nr_storewall(RT_A,
;               RT_X) on the state the harness put in the image, then the
;               record batch flushed; drv_seg the same for nr_segloop. Without
;               LOCKSTEP the real wall code (rwall.s) is linked.
;   drv_mframe  (-D MASKED) the frame to the masked phase's end: the
;               front end's window (far_wload), nr_frame, then at drv_mload
;               the masked phase's window (far_mload, RENDER-MASKED.md) and
;               nm_masked. The cost phases: 1 the front end's load, 13 the
;               masked load (RENDER-MASKED.md).
;   drv_fframe  (-D FRAME8) the whole frame (RENDER-MASKED.md),
;               from the front end's window to the replay's last SHR write:
;               as drv_mframe to nm_masked (with the weapon), then at
;               drv_mend nm_bkload (the bucket pass's code into main) and
;               nb_frame (the bucket pass and the replay of each batch).
;               This is the order the game's frame driver keeps (the main
;               loop's: W is the phases' window).
;
; With -D LOCKSTEP (no current build defines it) the lockstep stub below
; is nr_storewall; without it rwall.s's is linked.
;
; The lockstep data are in RamWorks bank SEAM (RENDER.md,
; tools/native/rlayout.py; the weapon's clip pass is native, so the seam
; of floorclip, FR_VIS and MM_WPOK is gone):
;
;   SEAM_HDR    +0: the reference's R_StoreWallRange calls in this frame
;   SEAM_CALLS  16 bytes a call of nr_storewall, written by the stub:
;               start, stop, the seg (2), the front sector, the floor and
;               ceiling colours (2 each), worldbottom (4)
;   SEAM_SOLID  160 bytes a reference call: solidcol after it, which the
;               stub puts in SOLIDCOL so the walk goes on as upstream's

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import mt_init, nr_frame, nr_side, far_wload
.ifdef MASKED
        .import far_mload, nm_masked, nm_rsetup, nm_drawsprite, nm_visx
        .import far_pload
        .import nm_mwall, md_dsptr, mrec_flush
        .export drv_mframe, drv_mload, drv_mroutine
        .export mr_kind, mr_vis, mr_ds, mr_slot, mr_x1, mr_x2
.endif
        .export drv_frame, drv_call, drv_ret, drv_halt, drv_crash
        .export drv_bulk, drv_desc, drv_stub, drv_irq, rt_side
        .export drv_wframe, drv_wload
.ifdef FRAME8
        .import nm_bkload, nb_frame
        .export drv_fframe, drv_mend, drv_fload
.endif
.ifdef LOCKSTEP
        .export nr_storewall, rec_start, rec_flush
.else
        .import nr_storewall, nr_segloop, rec_flush
        .export drv_wall, drv_seg, drv_rcall, drv_rret, RT_A, RT_X, RT_SPIN
.endif
        .exportzp DRV_IA, DRV_IX, DRV_IY, DRV_OA, DRV_OX, DRV_OY
        .exportzp IRQCNT, LS_K

MOUSE_MODE = $C0AE              ; slot 2: mode (bit 3: the VBL interrupt)
MOUSE_ACK  = $C0AF              ;   acknowledge: bit 0 the events, bit 1
MODE_VBL   = $08                ;   the interrupt line

IRQCNT  = $D8                   ; the interrupts taken (the stub's)
DRV_IA  = $E0                   ; drv_bulk: the registers into the call
DRV_IX  = $E1
DRV_IY  = $E2
DRV_OA  = $E3                   ;   and out of it
DRV_OX  = $E4
DRV_OY  = $E5
IP      = $E6                   ;   the next case, the next result
OP      = $E8
IB      = $EA                   ;   their banks
OB      = $EB
CNT     = $EC                   ;   cases left, 3 bytes
DP      = $F0                   ;   the place of a byte
LS_K    = $F2                   ; the lockstep stub: calls so far
LS_NREF = $F3                   ;   the reference's calls
LS_PTR  = $F4                   ;   the next call record (SEAM)
LS_SOL  = $F6                   ;   the next reference solidcol (SEAM)

        .segment "DRIVER"

; ---------------------------------------------------------------------------
; drv_frame
; ---------------------------------------------------------------------------
drv_frame:
        jsr drv_setup
        cli
drv_call:
        jsr nr_frame
drv_ret:
        sei
        stz MOUSE_MODE
        lda #3
        sta MOUSE_ACK
drv_halt:
        bra drv_halt
drv_crash:
        bra drv_crash

drv_wframe:
        jsr drv_setup
        cli
        lda #2                  ; the cost phase 1: the window load
        sta PHASE
drv_wload:
        jsr far_wload
        stz PHASE
        bra drv_call

.ifdef MASKED
drv_mframe:
        jsr drv_setup
        cli
        lda #2                  ; the cost phase 1: the front end's load
        sta PHASE
        jsr far_wload
        stz PHASE
        jsr nr_frame
drv_mload:
        lda #26                 ; the cost phase 13: the masked load
        sta PHASE
        jsr far_mload
        stz PHASE
        jsr nm_masked
        jmp drv_ret

.ifdef FRAME8
drv_fframe:
        jsr drv_setup
        cli
        lda #2                  ; the cost phase 1: the front end's load
        sta PHASE
        jsr far_wload
        stz PHASE
        jsr nr_frame
drv_fload:
        lda #26                 ; the cost phase 13: the masked load
        sta PHASE
        jsr far_mload
        stz PHASE
        jsr nm_masked
drv_mend:
        lda #36                 ; the cost phase 18: the bucket pass (its
        sta PHASE               ;   code into main first)
        jsr nm_bkload
        jsr nb_frame            ; (it marks 18 and 12, the replay)
        stz PHASE
        jmp drv_ret
.endif

; drv_mroutine: routine mode of the masked phase (RENDER-MASKED.md):
; the windows (the front end's for the shared math and the
; W tables, the masked image), the draw phase's constants, then one call
; with the reference's state the harness injected: mr_kind 0 R_DrawSprite
; of vissprite mr_vis, 1 R_DrawVisSprite of it with the clips, 2
; R_RenderMaskedSegRange of drawseg mr_ds (its DSW slot mr_slot) for the
; columns mr_x1 .. mr_x2; the last batch flushed
drv_mroutine:
        jsr drv_setup
        cli
        jsr far_wload
        jsr far_mload
        lda #<mr_runs           ; W's drawseg copy and vissprites (the
        ldx #>mr_runs           ;   harness's, in bank MRTN_BANK)
        ldy #MRTN_BANK
        jsr far_pload
        jsr nm_rsetup
        lda mr_kind
        beq @sprite
        cmp #1
        beq @vis
        lda mr_ds
        sta DS_K
        lda mr_slot
        sta DS_SLOT
        jsr md_dsptr
        lda mr_x1
        sta MW_X
        lda mr_x2
        sta MW_X2
        jsr nm_mwall
        bra @done
@sprite:
        ldx mr_vis
        jsr nm_drawsprite
        bra @done
@vis:   ldx mr_vis
        jsr nm_visx
@done:  jsr mrec_flush
        jmp drv_ret
mr_runs: .byte >DSW, (>(VIS + MAXVIS * VISREC_SIZE - 1)) - (>DSW) + 1, 0
mr_kind: .byte 0
mr_vis: .byte 0
mr_ds:  .byte 0
mr_slot: .byte 0
mr_x1:  .byte 0
mr_x2:  .byte 0
.endif

; drv_setup: the IRQ vector, the counters, the lockstep stub's state, the
; mouse card's VBL interrupt (enabled by the caller's CLI)
drv_setup:
        jsr mt_init
        lda #<drv_irq           ; the IRQ vector of the card
        sta $FFFE
        lda #>drv_irq
        sta $FFFF
        stz IRQCNT
        stz IRQCNT+1
        stz LS_K
        lda #<SEAM_CALLS
        sta LS_PTR
        lda #>SEAM_CALLS
        sta LS_PTR+1
        lda #<SEAM_SOLID
        sta LS_SOL
        lda #>SEAM_SOLID
        sta LS_SOL+1
        lda #SEAM               ; the reference's count of calls
        sta RWBANK
        sta RAMRDON
        lda SEAM_HDR
        sta RAMRDOFF
        stz RWBANK
        sta LS_NREF
        lda #MODE_VBL           ; the VBL interrupt: a live source for
        sta MOUSE_MODE          ;   a2vm's --irq-bounds
        rts

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

.ifndef LOCKSTEP
; ---------------------------------------------------------------------------
; drv_wall, drv_seg: routine mode. The interrupt on as drv_frame, the
; routine between drv_rcall and drv_rret, then the batch into the
; staging.
; ---------------------------------------------------------------------------
drv_wall:
        jsr drv_on
        lda #18                 ; the cost phase 9, wall setup (the
        sta PHASE               ;   profiling build marks 10 inside)
        lda RT_A
        ldx RT_X
drv_rcall:
        jsr nr_storewall
drv_rret:
        stz PHASE               ; (phase 0: the driver)
        jsr rec_flush
        jmp drv_ret
drv_seg:
        jsr drv_on
        lda #20                 ; phase 10, the seg loop
        sta PHASE
        jsr nr_segloop
        jmp drv_rret
; drv_on: the interrupt on; wait for the first VBL, then RT_SPIN turns
; of a loop, so that the next VBL comes where the harness chose inside the
; routine (a routine is often shorter than the VBL period); IRQCNT from 0.
drv_on: jsr mt_init
        lda #<drv_irq
        sta $FFFE
        lda #>drv_irq
        sta $FFFF
        stz IRQCNT
        stz IRQCNT+1
        lda #MODE_VBL
        sta MOUSE_MODE
        cli
:       lda IRQCNT
        beq :-
        stz IRQCNT
@spin:  lda RT_SPIN
        bne :+
        lda RT_SPIN+1
        beq @go
        dec RT_SPIN+1
:       dec RT_SPIN
        bra @spin
@go:    rts
RT_A:   .byte 0                 ; the routine's A and X (the harness's)
RT_X:   .byte 0
RT_SPIN: .word 0                ; the turns before the routine
.endif

.ifdef LOCKSTEP
; the staging, which the lockstep build does not have (rrec.s)
rec_start:
rec_flush:
        rts

; ---------------------------------------------------------------------------
; nr_storewall, the lockstep stub (-D LOCKSTEP; RENDER.md): its
; arguments (A = start, X = stop, BS_SEG, SC_CUR, FPC, CPC, WBOT) into the
; next call record, then SOLIDCOL = the reference's solidcol after the
; same call, when the reference made it.
; ---------------------------------------------------------------------------
nr_storewall:
        ldy LS_K                ; at most SEAM_MAXCALLS records
        cpy #SEAM_MAXCALLS - 1
        bcs @solid
        pha
        lda #SEAM
        sta RWBANK
        sta RAMWRTON
        pla
        ldy #0
        sta (LS_PTR),y
        iny
        txa
        sta (LS_PTR),y
        iny
        lda BS_SEG
        sta (LS_PTR),y
        iny
        lda BS_SEG+1
        sta (LS_PTR),y
        iny
        lda SC_CUR
        sta (LS_PTR),y
        iny
        lda FPC
        sta (LS_PTR),y
        iny
        lda FPC+1
        sta (LS_PTR),y
        iny
        lda CPC
        sta (LS_PTR),y
        iny
        lda CPC+1
        sta (LS_PTR),y
        iny
        ldx #0
:       lda WBOT,x
        sta (LS_PTR),y
        iny
        inx
        cpx #4
        bne :-
        sta RAMWRTOFF
        stz RWBANK
        clc
        lda LS_PTR
        adc #SEAM_CALLREC
        sta LS_PTR
        bcc @solid
        inc LS_PTR+1
@solid: lda LS_K
        cmp LS_NREF
        bcs @done
        lda #SEAM
        sta RWBANK
        sta RAMRDON
        ldy #VIEWWIDTH
:       dey
        lda (LS_SOL),y
        sta SOLIDCOL,y
        tya
        bne :-
        sta RAMRDOFF
        stz RWBANK
        clc
        lda LS_SOL
        adc #VIEWWIDTH
        sta LS_SOL
        bcc @done
        inc LS_SOL+1
@done:  inc LS_K
        rts
.endif

; ---------------------------------------------------------------------------
; rt_side: A = nr_side's side (0 or 1) of the node at NODEF (the case's 8
; bytes: x, y, dx, dy) from the view in VIEWX, VIEWY.
; ---------------------------------------------------------------------------
rt_side:
        lda #<NODEF
        sta FRP
        lda #>NODEF
        sta FRP+1
        jsr nr_side
        lda #0
        rol a
        rts

; ---------------------------------------------------------------------------
; drv_bulk: the descriptor drv_desc's cases, the descriptor filled
; by the harness (tools/native/render_check.py).
; ---------------------------------------------------------------------------
drv_bulk:
        jsr mt_init
        lda d_inbank
        sta IB
        lda d_outbank
        sta OB
        lda d_inbase
        sta IP
        lda d_inbase+1
        sta IP+1
        lda d_outbase
        sta OP
        lda d_outbase+1
        sta OP+1
        lda d_count
        sta CNT
        lda d_count+1
        sta CNT+1
        lda d_count+2
        sta CNT+2
@case:  lda CNT
        ora CNT+1
        ora CNT+2
        bne :+
        jmp drv_halt
:       ldx IB                  ; the inputs
        stx RWBANK
        sta RAMRDON
        ldy #0
@in:    cpy d_nin
        beq @indone
        lda d_inlo,y
        sta DP
        lda d_inhi,y
        sta DP+1
        lda (IP),y
        sta (DP)
        iny
        bra @in
@indone:
        sta RAMRDOFF
        stz RWBANK
        lda #2                  ; phase 1: the call
        sta PHASE
        lda DRV_IA
        ldx DRV_IX
        ldy DRV_IY
        jsr drv_call1
        sta DRV_OA
        stx DRV_OX
        sty DRV_OY
        stz PHASE
        ldx OB                  ; the outputs
        stx RWBANK
        sta RAMWRTON
        ldy #0
@out:   cpy d_nout
        beq @outdone
        lda d_outlo,y
        sta DP
        lda d_outhi,y
        sta DP+1
        lda (DP)
        sta (OP),y
        iny
        bra @out
@outdone:
        sta RAMWRTOFF
        stz RWBANK
        clc                     ; the next case
        lda IP
        adc d_nin
        sta IP
        bcc :+
        inc IP+1
        lda IP+1
        cmp d_limit
        bne :+
        lda d_inbase+1
        sta IP+1
        inc IB
:       clc                     ; the next result
        lda OP
        adc d_nout
        sta OP
        bcc :+
        inc OP+1
        lda OP+1
        cmp d_limit
        bne :+
        lda d_outbase+1
        sta OP+1
        inc OB
:       lda CNT                 ; one case fewer
        bne @c0
        lda CNT+1
        bne @c1
        dec CNT+2
@c1:    dec CNT+1
@c0:    dec CNT
        jmp @case

drv_call1:
        jmp (d_entry)

drv_stub:
        rts

; the descriptor, filled by the harness
        .segment "DESC"
drv_desc:
d_entry:    .res 2          ; the routine
d_nin:      .res 1          ; input bytes a case (a power of 2)
d_nout:     .res 1          ; output bytes a result (a power of 2)
d_count:    .res 3          ; cases
d_inbank:   .res 1
d_outbank:  .res 1
d_inbase:   .res 2          ; the first case (page aligned)
d_outbase:  .res 2
d_limit:    .res 1          ; the page after a bank's cases or results
            .res 2
d_inlo:     .res 16         ; each input byte's place
d_inhi:     .res 16
d_outlo:    .res 16         ; each output byte's place
d_outhi:    .res 16
