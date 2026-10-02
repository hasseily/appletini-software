; gcall.s: the code paging and the dispatch tables of the tic phase
; (milestone 10, docs/GAME.md 2.2, 3.4, 4.3). GPL-2, the port's own; the
; dispatch replaces upstream's callFn and callAction (p_tick65.s,
; p_pspr65.s), which are GPL-2 upstream.
;
;   fc_call     FCALL's stub for a target in another image (gplace.inc):
;               jsr fc_call / .byte group / .word target. The group the
;               target's slot holds is saved (a byte on the stack); the
;               target's group is loaded into the slot when another is
;               there; the target runs; on its return the saved group is
;               loaded again when the slot now holds another, whoever the
;               caller is (review 1). A, X, Y go to the target and back,
;               and P comes back (a carry result). 5 bytes of stack.
;   fc_unbuilt  an FCALL of a routine whose part is not built: GS_ARG = its
;               number, GS_UNBUILT
;   dc_call     DCALL table (number in A, the table in Y:X; 0 none): the
;               entry's group and address, through fc_call's path; an
;               unbuilt entry: GS_ARG = its number and table, GS_UNBUILTD
;   act_num     A = the ACTTAB number of the action of the state LW_STATE
;               (0 none; a stop GS_ACTION for an action not in ACT_ADDR)
;   gr_load     group A into its slot (its image's pages from its bank,
;               far_get a page at a time); SLOT_GRP updated
;   g_stop      A = a stop code: GS_STATUS = A, then BRK
;   ld_stop     the game core's stops in the tic image (LV_STATUS, BRK),
;               as lload.s's in the load image
;
; The group directory (grp_bank, grp_src, grp_pages: each group image's
; bank, first page and pages) is the image's, written by the harness
; (tools/native/grun.py) or the boot where it puts the images in GCODE0-1;
; grp_slot is the placement's (gplace.inc).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export fc_call, fc_unbuilt, dc_call, act_num, gr_load, g_stop
        .export ld_stop, fc_go, grp_bank, grp_src, grp_pages, grp_slot
        .export ACTTAB, THTAB, ITTAB, TRVTAB, LSTAB
        .import far_get

MAXGRP  = 64
        .assert GROUPS < MAXGRP, error, "too many groups"

        .include "gdisp.inc"

        .segment "LOADW"

; ---------------------------------------------------------------------------
; fc_call
; ---------------------------------------------------------------------------
fc_call:
        sta FC_A
        stx FC_X
        sty FC_Y
        pla                     ; the inline data - 1
        sta FC_P
        pla
        sta FC_P+1
        ldy #1
        lda (FC_P),y            ; the target's group
        sta FC_GRP
        iny
        lda (FC_P),y            ; the target
        sta FC_T
        iny
        lda (FC_P),y
        sta FC_T+1
        clc                     ; the caller's return: after the inline
        lda FC_P                ;   data (rts adds 1)
        adc #3
        tay
        lda FC_P+1
        adc #0
        pha
        phy
        ; (on into fc_go)

; fc_go: the caller's return on the stack, FC_GRP and FC_T the target
fc_go:
        ldx FC_GRP
        lda grp_slot,x
        sta FC_SLOT
        tax
        lda SLOT_GRP,x          ; the slot's group, saved
        pha
        cmp FC_GRP
        beq :+
        lda FC_GRP
        jsr gr_load
:       lda #>(fc_ret - 1)
        pha
        lda #<(fc_ret - 1)
        pha
        lda FC_A
        ldx FC_X
        ldy FC_Y
        jmp (FC_T)

fc_ret: php
        sta FC_A
        stx FC_X
        sty FC_Y
        pla
        sta FC_PS
        pla                     ; the group the slot held at the call
        cmp #$FF
        beq @back
        tax
        ldy grp_slot,x
        cmp SLOT_GRP,y
        beq @back
        ldy FC_PS               ; (gr_load counts its pages in FC_PS: the
        phy                     ;   callee's P kept on the stack; wave 1
        jsr gr_load             ;   as integrated, secfind.md request 11)
        pla
        sta FC_PS
@back:  lda FC_PS
        pha
        lda FC_A
        ldx FC_X
        ldy FC_Y
        plp
        rts

; ---------------------------------------------------------------------------
; fc_unbuilt: jsr fc_unbuilt / .word the routine's number
; ---------------------------------------------------------------------------
fc_unbuilt:
        pla
        sta FC_P
        pla
        sta FC_P+1
        ldy #1
        lda (FC_P),y
        sta GS_ARG
        iny
        lda (FC_P),y
        sta GS_ARG+1
        lda #GS_UNBUILT
        jmp g_stop

; ---------------------------------------------------------------------------
; dc_call: entry A of the table at Y:X (3 bytes an entry: the group, the
; address; $FE, the number, the table: unbuilt)
; ---------------------------------------------------------------------------
dc_call:
        cmp #0
        bne :+
        rts
:       stx FC_P
        sty FC_P+1
        sta FC_A
        sec                     ; 3 (n - 1)
        sbc #1
        sta FC_T
        asl a
        adc FC_T                ; (C clear: n - 1 < 85)
        tay
        lda (FC_P),y
        cmp #$FE
        beq @unbuilt
        sta FC_GRP
        iny
        lda (FC_P),y
        sta FC_T
        iny
        lda (FC_P),y
        sta FC_T+1
        lda FC_GRP
        bne @paged
        jmp (FC_T)              ; the core: its rts returns to the caller
@paged: jmp fc_go
@unbuilt:
        iny
        lda (FC_P),y
        sta GS_ARG
        iny
        lda (FC_P),y
        sta GS_ARG+1
        lda #GS_UNBUILTD
        jmp g_stop

; ---------------------------------------------------------------------------
; act_num: A = the number of LW_STATE's action (ACT_ADDR's order, from 1)
; ---------------------------------------------------------------------------
act_num:
        lda LW_STATE + U_ST_ACTION
        ora LW_STATE + U_ST_ACTION + 1
        ora LW_STATE + U_ST_ACTION + 2
        bne :+
        rts                     ; (A = 0: none)
:       ldx #0
        ldy #1
@next:  lda ACT_ADDR,x
        cmp LW_STATE + U_ST_ACTION
        bne @skip
        lda ACT_ADDR+1,x
        cmp LW_STATE + U_ST_ACTION + 1
        bne @skip
        lda ACT_ADDR+2,x
        cmp LW_STATE + U_ST_ACTION + 2
        bne @skip
        tya
        rts
@skip:  inx
        inx
        inx
        iny
        cpy #ACT_ADDR_N + 1
        bne @next
        lda #GS_ACTION
        jmp g_stop

; ---------------------------------------------------------------------------
; gr_load: group A into its slot
; ---------------------------------------------------------------------------
gr_load:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        ldy #2 * 28             ; the paging's phase (docs/GAME.md 5.4: the
        sty PHASE               ;   copy is far_get's, which the PC map
.endif                          ;   counts as the object API's)
.endif
        tax
        lda grp_pages,x
        bne :+
        lda #GS_GROUP           ; (a group the image does not hold)
        jmp g_stop
:       sta FC_PS               ; (the pages left)
        lda grp_bank,x
        sta FA_BANK
        lda grp_src,x
        sta FA_SRC+1
        stz FA_SRC
        ldy grp_slot,x
        txa
        sta SLOT_GRP,y
        lda slot_page-1,y
        sta FA_DST+1
        stz FA_DST
        stz FA_N                ; (256)
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dec FC_PS
        bne :-
        inc FC_LOADS
        bne :+
        inc FC_LOADS+1
:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        ldy #2 * 30             ; the tic again (gdriver.s PH_TIC)
        sty PHASE
.endif
.endif
        rts
slot_page:
        .byte >TW_SLOT1, >TW_SLOT2
        .assert <TW_SLOT1 = 0 && <TW_SLOT2 = 0, error, "slots on pages"

; ---------------------------------------------------------------------------
; The stops
; ---------------------------------------------------------------------------
g_stop: sta GS_STATUS
        brk
        .byte 0
ld_stop:
        sta LV_STATUS
        brk
        .byte 0

; ---------------------------------------------------------------------------
; The group directory: the image's (the harness and the boot write it);
; grp_slot from the placement
; ---------------------------------------------------------------------------
grp_slot:
        .byte 0
        .repeat GROUPS, I
        .byte .ident(.sprintf("GRP%d_SLOT", I + 1))
        .endrepeat
        .res MAXGRP - GROUPS - 1, 0
grp_bank:
        .res MAXGRP, 0
grp_src:
        .res MAXGRP, 0
grp_pages:
        .res MAXGRP, 0
