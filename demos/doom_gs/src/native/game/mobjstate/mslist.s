; game/mobjstate/mslist.s: part mobjstate's lists of a mobj (docs/GAME.md,
; the mobj, the parts). A GPL-2 derivative
; of upstream's p_map65.s (P_UnsetThingPosition, unlist, link, mvSector,
; mvBlock, blockOf, P_DelSeclist, P_DelSecnode, snLink).
;
;   P_UnsetThingPosition  A:X = a mobj: unless MF_NOSECTOR out of its
;                sector's thing list and its node list to _s_sector_list
;                (G_SECLIST; its own list none); unless MF_NOBLOCKMAP out of
;                its block's list (the flags read once, at the entry)
;   unlist     A:X = a mobj, Y = the list (K_SEC its sector's, K_BLK its
;                block's): if prev, *prev = next and if next, next->prev =
;                prev. Natively a list's first thing has prev none: it is
;                the first of the list of its subsector's sector (of the
;                block of its x, y) when that list's head names it, else in
;                no list (upstream's NULL prev: nothing changes)
;   link       A:X = a mobj, Y = the list, UL_HD its place (a sector, a
;                block's index): the mobj first in that list
;   mvSector   A:X = a mobj, GA_0 = a sector: out of its sector's list, the
;                first of the other's (P_TryMove's)
;   mvBlock    A:X = a mobj, GA_X, GA_Y = its new place (tmx, tmy; their
;                high words): the block of the place (off the map: out of
;                its list, its block links none); its list stays when it is
;                that block's first already, else out of its list and the
;                first of the new one (P_TryMove's)
;   p_map_blockOf  (upstream's p_map65.s:blockOf) GA_0-1 = x, GA_2-3 = y
;                (whole units: the high words): C set off the map, else A:X
;                = the block's index (blocky * width + blockx)
;   P_DelSeclist  every node of _s_sector_list deleted, the list none
;   P_DelSecnode  A:X = a sector node (none: none back): out of its thing's
;                thread and its sector's (the sector's list starts at its
;                next when it was the first), then first on the free list
;                (G_SNFREE, its free byte 1); A:X = its next on the thing's
;                thread. upstream's snLink is this routine's own four link
;                updates
;
; Every record through the object API: the cached kinds (mo_get, sec_get,
; ss_get), the sector nodes (sn_get, sn_put, sn_putw) and the blocklinks
; (bk_get, bk_put).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/mobjstate/ms.inc"

        .export P_UnsetThingPosition, unlist, link, mvSector, mvBlock
        .export p_map_blockOf, P_DelSeclist, P_DelSecnode
        .import mo_get, mo_dirty, sec_get, sec_dirty, ss_get, mul8
        .import fc_call, fc_unbuilt
        .import sn_get, sn_put, sn_putw, bk_get, bk_put

; ---------------------------------------------------------------------------
; P_UnsetThingPosition
; ---------------------------------------------------------------------------
        ROUTINE P_UnsetThingPosition
        sta UT_MO
        stx UT_MO+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        sta UT_FL
        and #<UC_MF_NOSECTOR
        bne @block
        lda UT_MO               ; out of the sector's list
        ldx UT_MO+1
        ldy #K_SEC
        FCALL unlist
        lda UT_MO               ; _s_sector_list = its node list, its list
        ldx UT_MO+1             ;   none
        jsr mo_get
        ldy #LN_A + MA_TOUCH
        lda (GC_MP),y
        sta G_SECLIST
        lda #$FF
        sta (GC_MP),y
        iny
        lda (GC_MP),y
        sta G_SECLIST+1
        lda #$FF
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
@block: lda UT_FL               ; out of the block's list
        and #<UC_MF_NOBLOCKMAP
        bne @done
        lda UT_MO
        ldx UT_MO+1
        ldy #K_BLK
        FCALL unlist
@done:  rts

; ---------------------------------------------------------------------------
; unlist
; ---------------------------------------------------------------------------
        ROUTINE unlist
        sta UL_MO
        stx UL_MO+1
        sty UL_K
        jsr mo_get
        ldx UL_K                ; the list's next and prev in the line
        ldy @nxt,x
        lda (GC_MP),y
        sta UL_NX
        iny
        lda (GC_MP),y
        sta UL_NX+1
        ldy @prv,x
        lda (GC_MP),y
        sta UL_PV
        iny
        lda (GC_MP),y
        sta UL_PV+1
        cmp #$FF
        beq @head
        lda UL_PV               ; *prev = next: the prev's next
        ldx UL_PV+1
        jsr mo_get
        ldx UL_K
        ldy @nxt,x
        lda UL_NX
        sta (GC_MP),y
        iny
        lda UL_NX+1
        sta (GC_MP),y
        lda @dirty,x
        jsr mo_dirty
        bra @next
@head:  txa                     ; (X = UL_K; GC_MP: the mobj's line still)
        bne @block
        ldy #LN_A + MA_SUBSEC + 1       ; its sector's list: the head
        lda (GC_MP),y
        tax
        dey
        lda (GC_MP),y
        jsr ss_get
        lda SS_BUF + SUB_SECTOR
        jsr sec_get
        ldy #SEC_THINGS
        lda (GC_SP),y
        cmp UL_MO
        bne @done               ; (not its first: in no list)
        iny
        lda (GC_SP),y
        cmp UL_MO+1
        bne @done
        lda UL_NX+1
        sta (GC_SP),y
        dey
        lda UL_NX
        sta (GC_SP),y
        lda #1                  ; (the render record)
        jsr sec_dirty
        bra @next
@block: ldx #3                  ; its block's list: the block of its x, y
:       ldy @xy,x               ;   (their high words: GA_0-3)
        lda (GC_MP),y
        sta GA_0,x
        dex
        bpl :-
        FCALL p_map_blockOf
        bcs @done               ; (off the map: in no list)
        sta GT_0
        stx GT_1
        jsr bk_get
        lda MS_W
        cmp UL_MO
        bne @done               ; (not its first: in no list)
        lda MS_W+1
        cmp UL_MO+1
        bne @done
        lda UL_NX
        sta MS_W
        lda UL_NX+1
        sta MS_W+1
        lda GT_0
        ldx GT_1
        jsr bk_put
@next:  ldx UL_NX+1             ; next->prev = prev
        cpx #$FF
        beq @done
        lda UL_NX
        jsr mo_get
        ldx UL_K
        ldy @prv,x
        lda UL_PV
        sta (GC_MP),y
        iny
        lda UL_PV+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
@done:  rts
; the lists' fields in a mobj's line (K_SEC, K_BLK), the next's group
@nxt:   .byte TH_SNEXT, LN_A + MA_BNEXT
@prv:   .byte LN_A + MA_SPREV, LN_A + MA_BPREV
@dirty: .byte D_RTH, D_A
@xy:    .byte TH_X + 2, TH_X + 3, TH_Y + 2, TH_Y + 3
        .assert K_SEC = 0 && K_BLK = 1, error, "the lists"

; ---------------------------------------------------------------------------
; link
; ---------------------------------------------------------------------------
        ROUTINE link
        sta UL_MO
        stx UL_MO+1
        sty UL_K
        tya
        bne @bhead
        lda UL_HD               ; next = the head: the sector's first
        jsr sec_get
        ldy #SEC_THINGS
        lda (GC_SP),y
        sta UL_NX
        iny
        lda (GC_SP),y
        sta UL_NX+1
        bra @thing
@bhead: lda UL_HD               ;   or the block's
        ldx UL_HD+1
        jsr bk_get
        lda MS_W
        sta UL_NX
        lda MS_W+1
        sta UL_NX+1
@thing: lda UL_MO               ; thing->next = next, thing->prev = &head
        ldx UL_MO+1             ;   (none)
        jsr mo_get
        ldx UL_K
        ldy @nxt,x
        lda UL_NX
        sta (GC_MP),y
        iny
        lda UL_NX+1
        sta (GC_MP),y
        ldy @prv,x
        lda #$FF
        sta (GC_MP),y
        iny
        sta (GC_MP),y
        lda @dirty,x
        jsr mo_dirty
        ldx UL_NX+1             ; next->prev = the thing
        cpx #$FF
        beq @head
        lda UL_NX
        jsr mo_get
        ldx UL_K
        ldy @prv,x
        lda UL_MO
        sta (GC_MP),y
        iny
        lda UL_MO+1
        sta (GC_MP),y
        lda #D_A
        jsr mo_dirty
@head:  lda UL_K                ; head = the thing
        bne @bput
        lda UL_HD
        jsr sec_get
        ldy #SEC_THINGS
        lda UL_MO
        sta (GC_SP),y
        iny
        lda UL_MO+1
        sta (GC_SP),y
        lda #1
        jmp sec_dirty
@bput:  lda UL_MO
        sta MS_W
        lda UL_MO+1
        sta MS_W+1
        lda UL_HD
        ldx UL_HD+1
        jmp bk_put
@nxt:   .byte TH_SNEXT, LN_A + MA_BNEXT
@prv:   .byte LN_A + MA_SPREV, LN_A + MA_BPREV
@dirty: .byte D_RTH | D_A, D_A

; ---------------------------------------------------------------------------
; mvSector
; ---------------------------------------------------------------------------
        ROUTINE mvSector
        sta MV_MO
        stx MV_MO+1
        lda GA_0
        sta MV_B
        lda MV_MO
        ldx MV_MO+1
        ldy #K_SEC
        FCALL unlist
        lda MV_B
        sta UL_HD
        lda MV_MO
        ldx MV_MO+1
        ldy #K_SEC
        FCALL link
        rts

; ---------------------------------------------------------------------------
; mvBlock
; ---------------------------------------------------------------------------
        ROUTINE mvBlock
        sta MV_MO
        stx MV_MO+1
        lda GA_X+2              ; blockOf(tmx, tmy): their high words
        sta GA_0
        lda GA_X+3
        sta GA_1
        lda GA_Y+2
        sta GA_2
        lda GA_Y+3
        sta GA_3
        .assert GA_X = GA_0 && GA_Y = GA_0 + 4, error, "GA_X, GA_Y"
        FCALL p_map_blockOf
        bcs @off
        sta MV_B
        stx MV_B+1
        lda MV_MO               ; its block's first already: the list stays
        ldx MV_MO+1
        jsr mo_get
        ldy #LN_A + MA_BPREV + 1
        lda (GC_MP),y
        cmp #$FF
        bne @move
        lda MV_B
        ldx MV_B+1
        jsr bk_get
        lda MS_W
        cmp MV_MO
        bne @move
        lda MS_W+1
        cmp MV_MO+1
        bne @move
        rts
@move:  lda MV_MO               ; out of the old list, first in the new
        ldx MV_MO+1
        ldy #K_BLK
        FCALL unlist
        lda MV_B
        sta UL_HD
        lda MV_B+1
        sta UL_HD+1
        lda MV_MO
        ldx MV_MO+1
        ldy #K_BLK
        FCALL link
        rts
@off:   lda MV_MO               ; off the map: out of the old list, bnext =
        ldx MV_MO+1             ;   bprev = none
        ldy #K_BLK
        FCALL unlist
        lda MV_MO
        ldx MV_MO+1
        jsr mo_get
        lda #$FF
        ldy #LN_A + MA_BNEXT
        ldx #4
:       sta (GC_MP),y
        iny
        dex
        bne :-
        .assert MA_BPREV = MA_BNEXT + 2, error, "bnext, bprev"
        lda #D_A
        jmp mo_dirty

; ---------------------------------------------------------------------------
; p_map_blockOf
; ---------------------------------------------------------------------------
        ROUTINE p_map_blockOf
        sec                     ; blocky = (y - orgy) >> 23: a byte, its
        lda GA_2                ;   sign in the carry (the origin's low
        sbc G_BMORGY+2          ;   word is 0)
        tax
        lda GA_3
        sbc G_BMORGY+3
        jsr @blk7
        bcs @off
        cmp G_BMH
        bcs @off
        sta GT_0
        sec                     ; blockx
        lda GA_0
        sbc G_BMORGX+2
        tax
        lda GA_1
        sbc G_BMORGX+3
        jsr @blk7
        bcs @off
        cmp G_BMW
        bcs @off
        sta GT_1
        lda GT_0                ; blocky * width + blockx
        ldy G_BMW
        jsr mul8
        clc
        lda M_R
        adc GT_1
        pha
        lda M_R+1
        adc #0
        tax
        pla
        clc
        rts
@off:   sec
        rts
; @blk7: A = (d >> 7) & $FF of the word d = A:X (A its high byte), C its
; sign (upstream's asl, xba)
@blk7:  sta GT_2
        txa
        asl a
        lda GT_2
        rol a
        rts

; ---------------------------------------------------------------------------
; P_DelSeclist
; ---------------------------------------------------------------------------
        ROUTINE P_DelSeclist
        lda G_SECLIST
        ldx G_SECLIST+1
@node:  cpx #$FF
        beq @done
        FCALL P_DelSecnode      ; A:X = the next node
        bra @node
@done:  lda #$FF
        sta G_SECLIST
        sta G_SECLIST+1
        rts

; ---------------------------------------------------------------------------
; P_DelSecnode
; ---------------------------------------------------------------------------
        ROUTINE P_DelSecnode
        cpx #$FF
        bne @node
        lda #$FF                ; none: none
        rts
@node:  sta GT_0
        stx GT_1
        jsr sn_get            ; DN_REC
        lda DN_REC + SN_TNEXT   ; (the result)
        sta DS_TN
        lda DN_REC + SN_TNEXT + 1
        sta DS_TN+1
        ldx #3                  ; upstream's snLink, four times: the node's
@link:  phx                     ;   neighbour (if any) gets its field
        ldy @fld,x
        lda DN_REC,y
        sta MS_W
        lda DN_REC+1,y
        sta MS_W+1
        ldy @ptr,x
        lda DN_REC,y
        pha
        lda DN_REC+1,y
        tax
        pla
        cpx #$FF
        beq @skip
        ply                     ; (the entry)
        phy
        pha
        lda @fld,y
        tay
        pla
        jsr sn_putw
@skip:  plx
        dex
        bpl @link
        ldx DN_REC + SN_SPREV + 1       ; no sp: the sector's thread starts
        cpx #$FF                        ;   at sn
        bne @free
        lda DN_REC + SN_SECTOR
        jsr sec_get
        ldy #SEC_SIZE + SG_TOUCH
        lda DN_REC + SN_SNEXT
        sta (GC_SP),y
        iny
        lda DN_REC + SN_SNEXT + 1
        sta (GC_SP),y
        lda #2                  ; (the game record)
        jsr sec_dirty
@free:  lda G_SNFREE            ; the node first on the free list
        sta DN_REC + SN_TNEXT
        lda G_SNFREE+1
        sta DN_REC + SN_TNEXT + 1
        lda #1
        sta DN_REC + SN_FREE
        lda GT_0
        ldx GT_1
        jsr sn_put
        lda GT_0
        sta G_SNFREE
        lda GT_1
        sta G_SNFREE+1
        lda DS_TN               ; the next node of the thing
        ldx DS_TN+1
        rts
; (the neighbour, its field), from the last entry down: tp->m_tnext = tn,
; tn->m_tprev = tp, sn->m_sprev = sp, sp->m_snext = sn (upstream's order;
; no two of them are one node)
@ptr:   .byte SN_SPREV, SN_SNEXT, SN_TNEXT, SN_TPREV
@fld:   .byte SN_SNEXT, SN_SPREV, SN_TPREV, SN_TNEXT
