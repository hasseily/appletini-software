; gcall.s: the code paging and the dispatch tables of the tic phase
; (milestone 10, docs/GAME.md 2.2, 3.4, 4.3). GPL-2, the port's own; the
; dispatch replaces upstream's callFn and callAction (p_tick65.s,
; p_pspr65.s), which are GPL-2 upstream.
;
;   fc_call     FCALL's stub for a target in another image (gplace.inc):
;               jsr fc_call / .byte group / .word target. The lazy
;               restore (docs/SPEED.md 4, item 14): SLOT_NEED (the slot's
;               entry) is the group the slot's innermost active FCALL
;               frame needs, $FF none. The call saves it (a byte on the
;               stack: $80 | the slot for none) and makes the target's
;               group the need; the target's group is loaded into the
;               slot when another is there; the target runs; on its
;               return the saved need is the slot's again and is loaded
;               when the slot now holds another, whoever the caller is
;               (review 1). A slot no active frame needs is left as it
;               is: only a frame entered through fc_go runs in a slot, so
;               every frame that returns into a slot finds its group. A,
;               X, Y go to the target and back, and P comes back (a
;               carry result). 5 bytes of stack.
;   fc_unbuilt  an FCALL of a routine whose part is not built: GS_ARG = its
;               number, GS_UNBUILT
;   dc_call     DCALL table (number in A, the table in Y:X; 0 none): the
;               entry's group and address, through fc_call's path; an
;               unbuilt entry: GS_ARG = its number and table, GS_UNBUILTD
;   act_num     A = the ACTTAB number of the action of the state LW_STATE
;               (0 none; a stop GS_ACTION for an action not in ACT_ADDR)
;   gr_load     group A into its slot, a W slot's or a frame slot's (slot
;               FS_FIRST and up, main $2000-$5FFF: docs/GAME.md 4.1, 4.3):
;               its length (its image's whole pages from its bank, then
;               the used bytes of its last page) by one memory-API PRIVATE
;               request (am_one; docs/SPEED.md 9 and 10); SLOT_GRP updated
;   fs_restore  the colormap bytes of every frame slot loaded since the
;               tic phase began, back from the level's copy in LVC: one
;               PRIVATE request, a descriptor a slot (at most 2,048 B
;               each, interrupts masked for the request), the slots
;               emptied, FS_DIRTY set. The play build's brain calls it at
;               the tic phase's end (dl_brain.s), the test drivers before
;               a frame (gdriver.s): every replay reads the colormaps
;   am_*        the memory API's transport (AMEMLC, in the main card: the
;               request's head and descriptor am_req, am_begin, am_push,
;               am_fin, and the kernel's am_runs; docs/SPEED.md 10)
;   g_stop      A = a stop code: GS_STATUS = A, then BRK
;   ld_stop     the game core's stops in the tic image (LV_STATUS, BRK),
;               as lload.s's in the load image
;
; The group directory (grp_bank, grp_src, grp_pages, grp_tail: each group
; image's bank, first page, whole pages and the bytes it copies of the page
; after them: its byte length, rounded up to an even count, or to the page
; when that copies faster) is the image's, written by the harness
; (tools/native/grun.py) or the disk's builder (tools/native/playdisk.py)
; where they put the images in GCODE0-1; grp_slot is the placement's
; (gplace.inc).

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
        .export grp_tail, fs_restore, am_one
        .export am_req, am_begin, am_push, am_fin, am_sent, am_runs
        .export ACTTAB, THTAB, ITTAB, TRVTAB, LSTAB

; the directory's entries: group 0 (none), the placement's groups (gplace.py
; MAX_GROUPS, 43, at most: the disk's CODE.2 holds 49 segments), then the
; play link's glue groups (playlayout.py DL_GROUPS: 5; playdisk.py checks
; they fit) or the test builds' harness groups (glayout.py TEST_GROUPS: 3)
MAXGRP  = 43 + 5 + 1
        .assert GROUPS < MAXGRP, error, "too many groups"

        .include "gdisp.inc"

; the memory API's transport (below: AMEMLC)
SP_DATA    = $CFF0              ; the memory API's raw FIFO transport in slot
SP_CTRL    = $CFF1              ;   7 (appletini-one README_MEMORY_API.md
SP_POP     = $CFF2              ;   section 7)
SP_RELEASE = $CFFF
SP_ROM     = $C700
FS_TIMEOUT = $6F                ; (ours: no reply came)
AM_HEAD    = 20                 ; am_req: the CONTROL head and the list's
AM_DESC    = AM_HEAD            ;   head, then the descriptor
AM_DESC_N  = 16
AM_MAX     = 15                 ; descriptors a request (the list's length
                                ;   8 + 16 N a byte; the API takes 16)
AMD_BANK   = AM_DESC + 3        ; the descriptor's fields
AMD_SRC    = AM_DESC + 5        ;   (the source's page)
AMD_DST    = AM_DESC + 9        ;   (the destination's page)
AMD_COUNT  = AM_DESC + 10
        .exportzp AMD_BANK, AMD_SRC, AMD_DST, AMD_COUNT, AM_DESC, AM_DESC_N

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
        lda SLOT_NEED-1,x       ; the slot's need, saved ($FF, none:
        bpl :+                  ;   $80 | the slot; a group is below 64)
        txa
        ora #$80
:       pha
        lda FC_GRP              ; the target's group: the slot's need
        sta SLOT_NEED-1,x
        cmp SLOT_GRP,x
        beq :+
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
        pla                     ; the slot's need at the call
        bmi @none
        tax
        ldy grp_slot,x
        sta SLOT_NEED-1,y       ; (the slot's need again)
        cmp SLOT_GRP,y
        beq @back
        jsr gr_load             ; (FC_PS, the callee's P, stays)
@back:  lda FC_PS
        pha
        lda FC_A
        ldx FC_X
        ldy FC_Y
        plp
        rts
@none:  and #$7F                ; no active frame needs the slot: none,
        tay                     ;   and no load
        lda #$FF
        sta SLOT_NEED-1,y
        bra @back

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
; gr_load: group A into its slot, from page grp_src of bank grp_bank to the
; slot's first page (both page aligned): its grp_pages whole pages (at
; least one: 0 marks a group the image does not hold) and, when grp_tail
; is not 0, the first grp_tail bytes of the page after them: the group's
; length, not its last page's padding (docs/SPEED.md 4, item 4;
; playdisk.py and grun.py choose the entry: grun.group_entry). One
; memory-API PRIVATE request copies it (am_one: docs/SPEED.md 10; the
; copy engine of F1.2.2 moves a byte in 0.038 us, the CPU in 0.231), into
; a W slot (main $9E00, $A600) as into a frame slot (the frame slots
; below). The slot's bytes past the group keep what they held: no group
; reads them (its link's segments end within its length, which
; playdisk.py checks). Changes A, X, Y and the far layer's zero page.
; ---------------------------------------------------------------------------
gr_load:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        ldy #2 * 28             ; the paging's phase (docs/GAME.md 5.4)
        sty PHASE
.endif
.endif
        tax
        lda grp_pages,x         ; the whole pages
        bne :+
        lda #GS_GROUP           ; (a group the image does not hold)
        jmp g_stop
:       ldy grp_slot,x
        txa
        sta SLOT_GRP,y
        cpy #FS_FIRST           ; a frame slot: its own place
        bcc @w
        stz FS_DIRTY            ; (bit 7 clear: fs_restore has work)
        lda fs_page-FS_FIRST,y
        bra @go
@w:     lda slot_page-1,y
@go:    sta FA_DST+1
        lda grp_bank,x
        ldy grp_src,x
        jsr am_one
gr_loaded:                      ; (playtime.py times am_one to here)
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
; am_one: one PRIVATE request of one COPY (the transport's am_begin, am_push,
; am_fin in the card, below): group X's length, grp_pages pages and
; grp_tail bytes, from page Y of RamWorks bank A to main page FA_DST+1.
; Interrupts masked for the request. Changes A, X, Y.
; ---------------------------------------------------------------------------
am_one:
        php
        sei
        sta am_req + AMD_BANK   ; the descriptor: the source's bank, page
        sty am_req + AMD_SRC
        lda FA_DST+1            ; the destination's page
        sta am_req + AMD_DST
        lda grp_tail,x          ; the count
        sta am_req + AMD_COUNT
        lda grp_pages,x
        sta am_req + AMD_COUNT + 1
        lda #1
        jsr am_begin
        ldx #AM_DESC
        ldy #AM_DESC_N
        jsr am_push
        stz am_req + AMD_COUNT  ; (whole pages: am_runs' and planes_out's)
        jmp am_fin

; ---------------------------------------------------------------------------
; The frame slots (docs/GAME.md 4.1, 4.3; docs/SPEED.md 9). A pinned group
; (slot FS_FIRST and up: glayout.py frame_slots) has its own place in main
; $2000-$5FFF, colormaps A and B of light levels 0-31, which only the
; replay reads (MEMORY_MAP.md 3.4). A CPU store there is a video write
; (rule 3): the group comes in by the memory API's PRIVATE copy (gr_load),
; which writes no capture record, and no group that stores into its own
; bytes is pinned (gplace.py; playdisk.py checks the links). Before the tic
; phase ends fs_restore copies the colormap bytes each loaded slot covered
; back from the level's copy in LVC (lg_cmaps's, the same bytes the load's
; PRIVATE request put there), so every replay finds its colormaps.
;
; fs_restore: every frame slot that holds a group: its group's length back
; from LVC (the slot's colormap bytes there, fs_src), a descriptor each,
; all in one request (at most AM_MAX of them: glayout.py's frame slots);
; then the slots empty, FS_DIRTY set. Changes A, X, Y.
; ---------------------------------------------------------------------------
fs_restore:
        bit FS_DIRTY            ; (with no frame slot gr_load never sets it
        bmi @done               ;   and FS_DIRTY stays $FF: the loop is the
        ldx #0                  ;   same bytes in every placement, as
        ldy #FS_FIRST + FSLOTS - 1      ;   gplace.py measures the core)
@count: lda SLOT_GRP,y          ; the slots that hold a group: X (at least
        cmp #$FF                ;   one: FS_DIRTY is clear)
        beq :+
        inx
:       dey
        cpy #FS_FIRST
        bcs @count
        php
        sei
        txa
        jsr am_begin
        lda #LVC                ; every source in LVC
        sta am_req + AMD_BANK
        ldy #FS_FIRST + FSLOTS - 1
@slot:  ldx SLOT_GRP,y
        cpx #$FF
        beq @next
        lda #$FF
        sta SLOT_GRP,y
        lda fs_src-FS_FIRST,y
        sta am_req + AMD_SRC
        lda fs_page-FS_FIRST,y
        sta am_req + AMD_DST
        lda grp_tail,x
        sta am_req + AMD_COUNT
        lda grp_pages,x
        sta am_req + AMD_COUNT + 1
        phy
        ldx #AM_DESC
        ldy #AM_DESC_N
        jsr am_push
        ply
@next:  dey
        cpy #FS_FIRST
        bcs @slot
        stz am_req + AMD_COUNT
        lda #$FF
        sta FS_DIRTY
        jmp am_fin
@done:  rts
        .assert FSLOTS <= AM_MAX, error, "more frame slots than a request's descriptors"

; each frame slot's first page in main and its colormap bytes' first page
; in LVC (glayout.py's, in gplace.inc)
fs_page:
        .repeat FSLOTS, I
        .byte .ident(.sprintf("FSLOT%d_PAGE", I + FS_FIRST))
        .assert .ident(.sprintf("GRP%d_SLOT", .ident(.sprintf("FSLOT%d_GRP", I + FS_FIRST)))) = I + FS_FIRST, error, "a frame slot's group"
        .endrepeat
fs_src:
        .repeat FSLOTS, I
        .byte .ident(.sprintf("FSLOT%d_SRC", I + FS_FIRST))
        .endrepeat
        .assert FS_FIRST + FSLOTS <= FS_FIRST + FS_MAX, error, "frame slots"

; ---------------------------------------------------------------------------
; The memory API's transport (docs/SPEED.md 10; appletini-one
; README_MEMORY_API.md sections 3, 4 and 7), in the main card's bank 1
; after MATHLC (AMEMLC, $DB5C-$DBFF: MEMORY_MAP.md 4.2), near in every
; phase but the replay. A request may replace all of W, the core with it
; (the kernel's loads: K_TIC's core, the images of K_LOAD), and the code
; that waits for its result must survive it: so the card. The request
; streams through slot 7's FIFO (lload.s's am_send): the SmartPort CONTROL
; head and the list's head from am_req, then each descriptor, am_req's
; template, which the callers patch: COPY, PRIVATE (every main destination
; needs it; a RamWorks one takes it), from AUX bank AMD_BANK page AMD_SRC
; to MAIN page AMD_DST, AMD_COUNT bytes (each address on a page). A
; caller that patches the spaces (dl_disp.s planes_out) puts them back.
; AMD_COUNT's low byte is 0 between requests (am_runs copies whole pages).
;
;   am_begin  A = the descriptors (1-AM_MAX): the request's head into the
;             FIFO, C8 selected. The caller has masked interrupts (php,
;             sei) and pushes each descriptor (am_push) before am_fin.
;             Leaves X = 20, Y = 0
;   am_push   Y bytes of am_req from X into the FIFO
;   am_fin    execute; the result (FS_TIMEOUT when no reply comes); C8
;             released; a refusal stops (GS_AMEM, GS_ARG the result); then
;             plp and rts: the caller's P from its php, interrupts as they
;             were, and back to the caller's caller
;   am_runs   (the kernel's: K_TIC, K_LOAD) the page runs of the list at
;             A:X (A the low byte; each run its first page and its count,
;             a first page of 0 ends it; at most AM_MAX runs) of RamWorks
;             bank Y into the same addresses of main: one request, a
;             descriptor a run, interrupts masked for it (far_pload's
;             arguments). Changes A, X, Y, FA_DST.
; ---------------------------------------------------------------------------

        .segment "AMEMLC"

; the request's head and descriptor first, at AM_REQ (glayout.py: the
; parts' write logs leave these bytes out, the transport's own working
; memory)
am_req: .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0   ; CONTROL, unit 0, selector $80
        .word 0                                ; the list's length (am_begin)
        .byte "AMEM", 1, 0, 0, 0               ; (the count: am_begin)
        .byte 1, 1, 1, 0, 0, 0, 0, 0, 0, 0     ; COPY, PRIVATE, from AUX bank
        .word 0                                ;   b page p to MAIN page q, the
        .byte 0, 0, 0, 0                       ;   count, no fill value
        .assert * - am_req = AM_HEAD + AM_DESC_N, error, "am_req"
        .assert am_req = AM_REQ, lderror, "am_req is not at AM_REQ"

am_begin:
        sta am_req + 17         ; the count, the list's length 8 + 16 N
        asl a
        asl a
        asl a
        asl a
        ora #8
        sta am_req + 10
        bit SP_RELEASE          ; C8: Appletini's
        bit SP_ROM
        ldx #0
        ldy #AM_HEAD
am_push:
        lda am_req,x
        sta SP_DATA
        inx
        dey
        bne am_push
        rts

am_runs:
        sta FA_DST
        stx FA_DST+1
        sty am_req + AMD_BANK
        php
        sei
        ldy #$FE                ; the runs: Y = 2 N
:       iny
        iny
        lda (FA_DST),y
        bne :-
        tya
        lsr a
        jsr am_begin            ; (Y = 0)
@run:   lda (FA_DST),y          ; a run: from its page to the same page
        beq am_fin
        sta am_req + AMD_SRC
        sta am_req + AMD_DST
        iny
        lda (FA_DST),y          ; its pages
        sta am_req + AMD_COUNT + 1
        iny
        phy
        ldx #AM_DESC
        ldy #AM_DESC_N
        jsr am_push
        ply
        bra @run

am_fin: lda #2                  ; execute
        sta SP_CTRL
        ldy #0                  ; (X as it is: the wait, 64 K turns at most)
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        lda #FS_TIMEOUT
        bra am_sent
@ready: lda SP_DATA             ; the result
        sta SP_POP
am_sent:                        ; (the request done: playtime.py times
        bit SP_RELEASE          ;   am_begin to here)
        tax
        bne @stop
        plp
        rts
@stop:  sta GS_ARG              ; (BRK: pl_crash, drv_crash; GS_STATUS
        lda #GS_AMEM            ;   names the stop)
        sta GS_STATUS
        brk


        .segment "LOADW"

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
grp_tail:
        .res MAXGRP, 0
