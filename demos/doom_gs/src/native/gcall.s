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
;   gr_load     group A into its slot (its image's whole pages from its
;               bank, then the used bytes of its last page: far_gcopy, one
;               read window each in the play build's kernel, dl_kern.s;
;               far_get a page at a time in the test builds' driver,
;               gdriver.s); SLOT_GRP updated. A frame slot's group (slot
;               FS_FIRST and up, main $2000-$5FFF: docs/GAME.md 4.1, 4.3)
;               comes by one memory-API PRIVATE request instead (fs_load)
;   fs_restore  the colormap bytes of every frame slot loaded since the
;               tic phase began, back from the level's copy in LVC: one
;               PRIVATE request a slot (at most 2,048 B each, interrupts
;               masked for one request at a time), the slots emptied,
;               FS_DIRTY set. The play build's brain calls it at the tic
;               phase's end (dl_brain.s), the test drivers before a frame
;               (gdriver.s): every replay reads the colormaps
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
        .export grp_tail, fs_restore, fs_load, fs_send, fs_sent
        .export ACTTAB, THTAB, ITTAB, TRVTAB, LSTAB
        .import far_gcopy       ; (game.cfg: the kernel's, KERN_GCOPY,
                                ;   unless the test driver links its own)

; the directory's entries: group 0 (none), the placement's groups (gplace.py
; MAX_GROUPS, 43, at most: the disk's CODE.2 holds 49 segments), then the
; play link's glue groups (playlayout.py DL_GROUPS: 5; playdisk.py checks
; they fit) or the test builds' harness groups (glayout.py TEST_GROUPS: 3)
MAXGRP  = 43 + 5 + 1
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
; is not 0, the first grp_tail bytes (an even count) of the page after
; them: the group's length, not its last page's padding (docs/SPEED.md 4,
; item 4; playdisk.py and grun.py choose the entry: grun.group_entry). One
; far_gcopy call copies them all (part ticloads' request 3, speed wave 2
; as integrated): FA_N = the pages + 1 from the page before, low byte
; grp_tail, and Y = 256 - grp_tail, so its first page is the group's
; first grp_tail bytes and the pages after them end at its last. far_gcopy
; copies FA_N pages from FA_SRC + Y to FA_DST + Y (the first page from
; byte Y). The play build's is the kernel's one read window (dl_kern.s):
; with RAMRD on, the fetches of $0200-$BFFF come from the bank, so the
; core cannot hold the copy. The test builds' is the driver's, far_get a
; page at a time with the pages counted in FC_PS, as gr_load's own loop
; was (gdriver.s: the parts' write checks allow far_get's stores into the
; slots; fc_ret keeps the callee's P across a load). Both leave X as it
; was. The slot's bytes past the group keep what they held: no group
; reads them (its link's segments end within its length, which
; playdisk.py checks).
; ---------------------------------------------------------------------------
gr_load:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        ldy #2 * 28             ; the paging's phase (docs/GAME.md 5.4: the
        sty PHASE               ;   copy is far_get's, which the PC map
.endif                          ;   counts as the object API's)
.endif
        tax
        lda grp_pages,x         ; the whole pages
        bne :+
        lda #GS_GROUP           ; (a group the image does not hold)
        jmp g_stop
:       ldy grp_slot,x
        cpy #FS_FIRST           ; a frame slot: one PRIVATE request
        bcc @w
        jsr fs_load
        bra @loaded
@w:     sta FA_N
        lda grp_bank,x
        sta FA_BANK
        lda grp_src,x
        sta FA_SRC+1
        txa
        sta SLOT_GRP,y
        lda slot_page-1,y
        sta FA_DST+1
        ldy #0
        lda grp_tail,x          ; a tail: one page more, from byte 256 -
        sta FA_SRC              ;   grp_tail of the page before the group
        sta FA_DST
        beq :+
        dec FA_SRC+1
        dec FA_DST+1
        inc FA_N
        eor #$FF
        inc a
        tay
:       jsr far_gcopy
@loaded:
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
; The frame slots (docs/GAME.md 4.1, 4.3; docs/SPEED.md 9). A pinned group
; (slot FS_FIRST and up: glayout.py frame_slots) has its own place in main
; $2000-$5FFF, colormaps A and B of light levels 0-31, which only the
; replay reads (MEMORY_MAP.md 3.4). A CPU store there is a video write
; (rule 3): the group comes in by the memory API's PRIVATE copy, which
; writes no capture record, and no group that stores into its own bytes
; is pinned (gplace.py; playdisk.py checks the links). Before the tic
; phase ends fs_restore copies the colormap bytes each loaded slot covered
; back from the level's copy in LVC (lg_cmaps's, the same bytes the load's
; PRIVATE request put there), so every replay finds its colormaps.
;
; fs_load: group X into its frame slot Y, its length (grp_pages pages and
; grp_tail bytes) from its image in bank grp_bank, page grp_src; the slot
; then holds it until K_TIC (or fs_restore) empties it
; ---------------------------------------------------------------------------
fs_load:
        txa
        sta SLOT_GRP,y
        stz FS_DIRTY            ; (bit 7 clear: fs_restore has work)
        lda grp_bank,x
        sta FA_BANK
        lda grp_src,x
        sta FA_SRC+1
        lda fs_page-FS_FIRST,y
        sta FA_DST+1
        ; (on into fs_copy)

; fs_copy: group X's length from page FA_SRC+1 of bank FA_BANK to main page
; FA_DST+1: one request
fs_copy:
        lda grp_tail,x          ; the count: grp_pages pages, grp_tail bytes
        sta FA_SRC
        cmp #1                  ; (C: a tail)
        lda grp_pages,x
        sta FA_N
        adc #0                  ; A = the pages the copy touches (playtime.py
                                ;   logs it at fs_send)
        ; (on into fs_send)

; fs_send: one COPY with PRIVATE through slot 7's FIFO (lload.s's am_send,
; the request streamed from fs_head and the far layer's zero page): FA_N
; pages and FA_SRC bytes from page FA_SRC+1 of RamWorks bank FA_BANK to main
; page FA_DST+1 (both on pages). Interrupts masked meanwhile; a refusal
; stops (GS_AMEM, GS_ARG the result). Changes A, X, Y.
SP_DATA    = $CFF0              ; the memory API's raw FIFO transport in slot
SP_CTRL    = $CFF1              ;   7 (appletini-one README_MEMORY_API.md
SP_POP     = $CFF2              ;   section 7)
SP_RELEASE = $CFFF
SP_ROM     = $C700
FS_TIMEOUT = $6F                ; (ours: no reply came)
fs_send:
        php
        sei
        bit SP_RELEASE
        bit SP_ROM
        ldx #0
@head:  lda fs_head,x
        sta SP_DATA
        inx
        cpx #FS_HEAD_N
        bne @head
        lda FA_BANK             ; the source: AUX, the bank, its page
        sta SP_DATA
        stz SP_DATA
        lda FA_SRC+1
        sta SP_DATA
        stz SP_DATA             ; the destination: MAIN, bank 0, its page
        stz SP_DATA
        stz SP_DATA
        lda FA_DST+1
        sta SP_DATA
        lda FA_SRC              ; the count
        sta SP_DATA
        lda FA_N
        sta SP_DATA
        ldx #4                  ; no fill value, the reserved bytes
@zero:  stz SP_DATA
        dex
        bne @zero
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        lda #FS_TIMEOUT
        bra fs_sent
@ready: lda SP_DATA             ; the result
        sta SP_POP
fs_sent:                        ; (the request done: playtime.py times
        bit SP_RELEASE          ;   fs_send to here)
        plp
        cmp #0
        bne :+
        rts
:       sta GS_ARG
        lda #GS_AMEM
        jmp g_stop
fs_head:
        .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0   ; CONTROL, unit 0, selector $80
        .word 8 + 16                           ; the list: one descriptor
        .byte "AMEM", 1, 1, 0, 0
        .byte 1, 1, 1                          ; COPY, PRIVATE, from AUX
FS_HEAD_N = * - fs_head
        .assert FS_HEAD_N = 23, error, "fs_head is not the descriptor's head"

; ---------------------------------------------------------------------------
; fs_restore: every frame slot that holds a group: its group's length back
; from LVC (the slot's colormap bytes there, fs_src), then the slot empty;
; FS_DIRTY set. Changes A, X, Y and the far layer's zero page.
; ---------------------------------------------------------------------------
fs_restore:
        bit FS_DIRTY            ; (with no frame slot fs_load never runs and
        bmi @done               ;   FS_DIRTY stays $FF: the loop is the same
        ldy #FS_FIRST + FSLOTS - 1      ;   bytes in every placement, as
                                ;   gplace.py measures the core)
@slot:  ldx SLOT_GRP,y
        cpx #$FF
        beq @next
        lda #$FF
        sta SLOT_GRP,y
        lda #LVC
        sta FA_BANK
        lda fs_src-FS_FIRST,y
        sta FA_SRC+1
        lda fs_page-FS_FIRST,y
        sta FA_DST+1
        phy
        jsr fs_copy
        ply
@next:  dey
        cpy #FS_FIRST
        bcs @slot
        lda #$FF
        sta FS_DIRTY
@done:  rts

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
