; gobj.s: the object API (milestone 10, docs/GAME.md 1.1, 3.4): the parts
; and milestone 9's game core read and write the game's objects only
; through it. GPL-2, the port's own.
;
;   mo_get      A:X = a mobj slot: its RTHING and groups A, B, C in a line
;               of the mobj cache (main MOC: 8 lines of 96 bytes, the
;               layout of LW_MOB); GC_MP its pointer
;   mo_dirty    A = the groups changed (bit 0 RTHING, 1 A, 2 B, 3 C) of the
;               mobj line last got
;   mo_store    the mobj at LW_MOB into slot GC_MO's line, all its groups
;               dirty, without reading the slot's old record (a spawn: the
;               line the slot has, dirty or not, is overwritten, so a later
;               eviction writes the new record)
;   sec_get     A = a sector: its LVMAP render record (16) and LVG1 game
;               record (32) in a line of the sector cache (main SCC: 8 lines
;               of 48); GC_SP its pointer
;   sec_dirty   A = 1 the render record, 2 the game record
;   ln_get      A:X = a line: its LVG0 record (32) and its front and back
;               sectors from LVS (LNSECF, LNSECB) in a line of the line cache
;               (W LNC: 8 lines of 34); GC_LP its pointer
;   ln_dirty    the line last got: its record changed (LVS is read-only)
;   sp_get      A:X = a special's handle: its ZONE0 record (32) in a line of
;               the special cache (W SPC: SPC_LINES of 32); GC_XP
;   sp_dirty    the special last got changed
;   sp_store    the special at LW_SPEC into handle GC_H's line, dirty
;   nd_get      A:X = a node: its record (NODEB_SIZE) into LW_NODEB
;   sg_get      A:X = a seg: its record into SG_BUF
;   ss_get      A:X = a subsector: its record into SS_BUF
;   bl_get      A:X = a word of the blockmap: 256 bytes from it into BL_BUF
;   go_flush    every dirty line written back, then every line empty: at
;               the tic phase's end, before a load, before a frame, at the
;               end of a routine-mode call
;   go_reset    every line empty, nothing written (a fresh machine)
;   pl_get      A:X = a mobj slot: PL_N (its next thinker), PL_K (its kind:
;               FN and bit 7 CLEAN), PL_T (its tics, $FF for -1) from the
;               planes; pl_put writes the four back; pl_setn the next only;
;               a slot of PLANE_SLOTS or more is a stop (GS_PLANES)
;
; The tic images' uncached records (wave 1 as integrated, docs/GAME.md;
; docs/game-parts/geom.md R2, mobjstate.md R2, secfind.md requests 1-2,
; sight.md R2), not in the load image. API_W (GW) is the word some of them
; take or give:
;   sd_get      A:X = a side: its LVMAP record (SIDE_SIZE) into SD_BUF, its
;               address in SD_AT; sd_put: SD_BUF back to the side last got
;   lt_get      A:X = an entry of the line tables (a sector's first + i):
;               A:X = its line (LVG1 G_LTABAT + 2 entry), API_W too
;   bk_get      A:X = a block's index: A:X = the first mobj of its list
;               (LVG1 G_BLINKSAT + 2 index; $FFFF none), API_W too;
;               bk_put: its first = API_W
;   sn_get      A:X = a sector node: its ZONE1 record (SN_SIZE) into SN_BUF;
;               sn_put: the node = SN_BUF; sn_putw: its word at offset Y =
;               API_W
;   mi_get      A = a mobj type, Y = an offset: API_W and A:X = the word
;               there of its mobjinfo record (GTAB GT_MOBJINFO + 64 type)
;   hn_get      A:X = a mobj slot: A:X = its sight hint (MOBJP HINTL,
;               HINTH: a line + 1, 0 none); hn_put: its hint = API_W
;   rj_row      A = a sector: A:X = its REJECT row (LVS RJROW)
;   rj_byte     A:X = a byte's offset in REJECT: A = the byte (LVG2
;               G_REJECTAT + the offset)
;
; A line's pointer stays valid until the next get of the same kind that
; misses; the replacement is the least recently got line, so the four most
; recently got lines of a kind are never evicted (SPC_LINES is 5 for that).
; Every get, store and flush changes A, X, Y, the API's temporaries
; (GO_*, among GT_*) and the far layer's arguments (FA_*); nothing else.
;
; The load image (nl_setup) links it too, assembled with -D LOADIMG: the
; planes are then reached far in bank MOBJP (W holds the load's data), the
; caches are the same places (llayout.py: main and W $AE00-$B3FF, the
; load's dead scratch once GTABS has run).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"

        .export mo_get, mo_dirty, mo_store, sec_get, sec_dirty, ln_get
        .export ln_dirty, sp_get, sp_dirty, sp_store, nd_get, sg_get, ss_get
        .export bl_get, go_flush, go_reset, pl_get, pl_put, pl_setn
        .export mo_tagged, go_stamps0
.ifndef LOADIMG
        .export sd_get, sd_put, lt_get, bk_get, bk_put, sn_get, sn_put
        .export sn_putw, mi_get, hn_get, hn_put, rj_row, rj_byte
.endif
        .import far_get, far_put
.ifdef LOADIMG
        .import ld_stop
.else
        .import g_stop
.endif

        .assert MOC_LINE = 96 && SCC_LINE = 48 && LNC_LINE = 34 &&  SPC_LINE = 32, error, "the cache lines"
        .assert MOC_LINES = 8 && SCC_LINES = 8 && LNC_LINES = 8, error,  "eight lines"
        .assert SPC_LINES <= 8, error, "the special lines"

        .segment "LOADW"

; ===========================================================================
; The mobjs
; ===========================================================================

; mo_get: GC_MP = the line of mobj slot A:X
mo_get:
        sta GO_T
        stx GO_T+1
        ldx #MOC_LINES - 1
@find:  lda MOC_TL,x
        cmp GO_T
        bne @next
        lda MOC_TH,x
        cmp GO_T+1
        beq @hit
@next:  dex
        bpl @find
        jsr count_miss
        ldx MOC_ORD + MOC_LINES - 1     ; the least recently got
        jsr mo_wback
        lda GO_T
        sta MOC_TL,x
        lda GO_T+1
        sta MOC_TH,x
        stz MOC_DT,x
        jsr mo_fetch
        bra mo_front
@hit:   jsr count_hit
        ; (on into mo_front)

; mo_front: line X first in the recency order; GC_MP its address
mo_front:
        ldy #0
:       lda MOC_ORD,y
        stx GO_I
        cmp GO_I
        beq :+
        iny
        cpy #MOC_LINES
        bne :-
        lda #GS_API             ; (a line not in the order: never)
        jmp stop
:       cpy #0                  ; shift the ones before it down
        beq :+
        lda MOC_ORD-1,y
        sta MOC_ORD,y
        dey
        bra :-
:       stx MOC_ORD
        lda moc_lo,x
        sta GC_MP
        lda moc_hi,x
        sta GC_MP+1
        stx GO_LAST
        rts

; mo_dirty: the groups A of the line last got
mo_dirty:
        ldx MOC_ORD
        pha
        lda MOC_TH,x
        cmp #$FF
        beq @none
        pla
        ora MOC_DT,x
        sta MOC_DT,x
        rts
@none:  pla
        lda #GS_API
        jmp stop

; mo_tagged: carry set when slot A:X has a line (X: the line), for the
; tests and the spawn
mo_tagged:
        sta GO_T
        stx GO_T+1
        ldx #MOC_LINES - 1
:       lda MOC_TL,x
        cmp GO_T
        bne @next
        lda MOC_TH,x
        cmp GO_T+1
        bne @next
        sec
        rts
@next:  dex
        bpl :-
        clc
        rts

; mo_store: LW_MOB into slot GC_MO's line, every group dirty
mo_store:
        lda GC_MO
        ldx GC_MO+1
        jsr mo_tagged
        bcs @have
        ldx MOC_ORD + MOC_LINES - 1
        jsr mo_wback
        lda GC_MO
        sta MOC_TL,x
        lda GC_MO+1
        sta MOC_TH,x
@have:  lda #$0F
        sta MOC_DT,x
        jsr mo_front            ; GC_MP
        ldy #MOC_LINE - 1
:       lda LW_MOB,y
        sta (GC_MP),y
        dey
        bpl :-
        rts

; mo_wback: line X's dirty groups to their banks; X kept
mo_wback:
        lda MOC_DT,x
        beq @done
        lda MOC_TH,x
        cmp #$FF
        beq @clean
        jsr mo_addr             ; GO_P = the record's address
        lda #0                  ; GO_J = the group
        sta GO_J
@group: lda MOC_DT,x
        ldy GO_J
        and bit_of,y
        beq @skip
        lda mo_bank,y
        sta FA_BANK
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        clc
        lda moc_lo,x
        adc mo_ofs,y
        sta FA_SRC
        lda moc_hi,x
        adc #0
        sta FA_SRC+1
        lda #MO_SIZE
        sta FA_N
        jsr far_put
        jsr count_wback
@skip:  inc GO_J
        lda GO_J
        cmp #4
        bne @group
@clean: stz MOC_DT,x
@done:  rts

; mo_fetch: line X from slot MOC_TL/TH,x's four records; X kept
mo_fetch:
        jsr mo_addr
        ldy #3
@group: lda mo_bank,y
        sta FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        clc
        lda moc_lo,x
        adc mo_ofs,y
        sta FA_DST
        lda moc_hi,x
        adc #0
        sta FA_DST+1
        lda #MO_SIZE
        sta FA_N
        phy
        jsr far_get
        ply
        dey
        bpl @group
        rts

; mo_addr: GO_P = RTHBASE + 24 slot (the tag of line X); X kept
mo_addr:
        lda MOC_TL,x
        sta GO_P
        lda MOC_TH,x
        asl GO_P                ; 8 slot
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        sta GO_P+1
        lda GO_P
        sta GO_I
        lda GO_P+1
        pha
        asl GO_P                ; + 16 slot
        rol GO_P+1
        clc
        lda GO_P
        adc GO_I
        sta GO_P
        pla
        adc GO_P+1
        sta GO_P+1
        clc
        lda GO_P
        adc #<RTHBASE
        sta GO_P
        lda GO_P+1
        adc #>RTHBASE
        sta GO_P+1
        rts

mo_bank:
        .byte RTH, MOBJA, MOBJB, MOBJC
mo_ofs: .byte 0, MO_SIZE, 2 * MO_SIZE, 3 * MO_SIZE
bit_of: .byte 1, 2, 4, 8
moc_lo:
        .repeat MOC_LINES, I
        .byte <(MOC + MOC_LINE * I)
        .endrepeat
moc_hi:
        .repeat MOC_LINES, I
        .byte >(MOC + MOC_LINE * I)
        .endrepeat

; ===========================================================================
; The sectors
; ===========================================================================

; sec_get: GC_SP = the line of sector A
sec_get:
        sta GO_T
        ldx #SCC_LINES - 1
:       lda SCC_TAG,x
        cmp GO_T
        beq @hit
        dex
        bpl :-
        jsr count_miss
        ldx SCC_ORD + SCC_LINES - 1
        jsr sec_wback
        lda GO_T
        sta SCC_TAG,x
        stz SCC_DT,x
        jsr sec_addr
        lda #LVMAP              ; the render record
        sta FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        lda scc_lo,x
        sta FA_DST
        lda scc_hi,x
        sta FA_DST+1
        lda #SEC_SIZE
        sta FA_N
        jsr far_get
        lda #LVG1               ; the game record
        sta FA_BANK
        lda GO_I
        sta FA_SRC
        lda GO_J
        sta FA_SRC+1
        clc
        lda scc_lo,x
        adc #SEC_SIZE
        sta FA_DST
        lda scc_hi,x
        adc #0
        sta FA_DST+1
        lda #SECG_SIZE
        sta FA_N
        jsr far_get
        bra sec_front
@hit:   jsr count_hit
sec_front:
        ldy #0
:       txa
        cmp SCC_ORD,y
        beq :+
        iny
        cpy #SCC_LINES
        bne :-
        lda #GS_API
        jmp stop
:       cpy #0
        beq :+
        lda SCC_ORD-1,y
        sta SCC_ORD,y
        dey
        bra :-
:       stx SCC_ORD
        lda scc_lo,x
        sta GC_SP
        lda scc_hi,x
        sta GC_SP+1
        stx GO_LAST+1
        rts

; sec_dirty: the records A (1 render, 2 game) of the sector line last got
sec_dirty:
        ldx SCC_ORD
        pha
        lda SCC_TAG,x
        cmp #$FF
        beq @none
        pla
        ora SCC_DT,x
        sta SCC_DT,x
        rts
@none:  pla
        lda #GS_API
        jmp stop

sec_wback:
        lda SCC_DT,x
        beq @done
        lda SCC_TAG,x
        cmp #$FF
        beq @clean
        jsr sec_addr
        lda SCC_DT,x
        and #1
        beq @game
        lda #LVMAP
        sta FA_BANK
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        lda scc_lo,x
        sta FA_SRC
        lda scc_hi,x
        sta FA_SRC+1
        lda #SEC_SIZE
        sta FA_N
        jsr far_put
        jsr count_wback
@game:  lda SCC_DT,x
        and #2
        beq @clean
        lda #LVG1
        sta FA_BANK
        lda GO_I
        sta FA_DST
        lda GO_J
        sta FA_DST+1
        clc
        lda scc_lo,x
        adc #SEC_SIZE
        sta FA_SRC
        lda scc_hi,x
        adc #0
        sta FA_SRC+1
        lda #SECG_SIZE
        sta FA_N
        jsr far_put
        jsr count_wback
@clean: stz SCC_DT,x
@done:  rts

; sec_addr: GO_P = SECBASE + 16 s (LVMAP), GO_I:GO_J = SECG_BASE + 32 s
; (LVG1), s the tag of line X; X kept
sec_addr:
        lda SCC_TAG,x
        sta GO_P
        stz GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        lda GO_P                ; 32 s
        asl a
        sta GO_I
        lda GO_P+1
        rol a
        sta GO_J
        clc
        lda GO_I
        adc #<SECG_BASE
        sta GO_I
        lda GO_J
        adc #>SECG_BASE
        sta GO_J
        clc
        lda GO_P
        adc #<SECBASE
        sta GO_P
        lda GO_P+1
        adc #>SECBASE
        sta GO_P+1
        rts
        .assert SEC_SIZE = 16 && SECG_SIZE = 32, error, "the sector records"

scc_lo:
        .repeat SCC_LINES, I
        .byte <(SCC + SCC_LINE * I)
        .endrepeat
scc_hi:
        .repeat SCC_LINES, I
        .byte >(SCC + SCC_LINE * I)
        .endrepeat

; ===========================================================================
; The lines
; ===========================================================================

; ln_get: GC_LP = the line of line A:X: its record and its two sectors
ln_get:
        sta GO_T
        stx GO_T+1
        ldx #LNC_LINES - 1
@find:  lda LNC_TL,x
        cmp GO_T
        bne @next
        lda LNC_TH,x
        cmp GO_T+1
        beq @hit
@next:  dex
        bpl @find
        jsr count_miss
        ldx LNC_ORD + LNC_LINES - 1
        jsr ln_wback
        lda GO_T
        sta LNC_TL,x
        lda GO_T+1
        sta LNC_TH,x
        stz LNC_DT,x
        jsr ln_addr
        lda #LVG0               ; the record
        sta FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        lda lnc_lo,x
        sta FA_DST
        lda lnc_hi,x
        sta FA_DST+1
        lda #LINE_SIZE
        sta FA_N
        jsr far_get
        lda #LVS                ; its front sector, then its back sector
        sta FA_BANK
        clc
        lda LNC_TL,x
        adc #<LVS_LNSECF
        sta FA_SRC
        lda LNC_TH,x
        adc #>LVS_LNSECF
        sta FA_SRC+1
        clc
        lda lnc_lo,x
        adc #LINE_SIZE
        sta FA_DST
        lda lnc_hi,x
        adc #0
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        clc
        lda FA_SRC+1
        adc #>(LVS_LNSECB - LVS_LNSECF)
        sta FA_SRC+1
        inc FA_DST
        bne :+
        inc FA_DST+1
:       jsr far_get
        bra ln_front
@hit:   jsr count_hit
ln_front:
        ldy #0
:       txa
        cmp LNC_ORD,y
        beq :+
        iny
        cpy #LNC_LINES
        bne :-
        lda #GS_API
        jmp stop
:       cpy #0
        beq :+
        lda LNC_ORD-1,y
        sta LNC_ORD,y
        dey
        bra :-
:       stx LNC_ORD
        lda lnc_lo,x
        sta GC_LP
        lda lnc_hi,x
        sta GC_LP+1
        stx GO_LAST+2
        rts
        .assert <(LVS_LNSECB - LVS_LNSECF) = 0, error, "LNSECB a page on"

; ln_dirty: the record of the line last got changed
ln_dirty:
        ldx LNC_ORD
        lda LNC_TH,x
        cmp #$FF
        beq @none
        lda #1
        sta LNC_DT,x
        rts
@none:  lda #GS_API
        jmp stop

ln_wback:
        lda LNC_DT,x
        beq @done
        lda LNC_TH,x
        cmp #$FF
        beq @clean
        jsr ln_addr
        lda #LVG0
        sta FA_BANK
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        lda lnc_lo,x
        sta FA_SRC
        lda lnc_hi,x
        sta FA_SRC+1
        lda #LINE_SIZE
        sta FA_N
        jsr far_put
        jsr count_wback
@clean: stz LNC_DT,x
@done:  rts

; ln_addr: GO_P = LINE_BASE + 32 n, n the tag of line X; X kept
ln_addr:
        lda LNC_TL,x
        sta GO_P
        lda LNC_TH,x
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        sta GO_P+1
        clc
        lda GO_P
        adc #<LINE_BASE
        sta GO_P
        lda GO_P+1
        adc #>LINE_BASE
        sta GO_P+1
        rts
        .assert LINE_SIZE = 32, error, "a line record"

lnc_lo:
        .repeat LNC_LINES, I
        .byte <(LNC + LNC_LINE * I)
        .endrepeat
lnc_hi:
        .repeat LNC_LINES, I
        .byte >(LNC + LNC_LINE * I)
        .endrepeat

; ===========================================================================
; The specials
; ===========================================================================

; sp_get: GC_XP = the line of special handle A:X
sp_get:
        sta GO_T
        stx GO_T+1
        jsr sp_find
        bcs @hit
        jsr count_miss
        jsr sp_take
        jsr sp_addr
        lda #ZONE0
        sta FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        lda spc_lo,x
        sta FA_DST
        lda spc_hi,x
        sta FA_DST+1
        lda #SPEC_SIZE
        sta FA_N
        jsr far_get
        bra sp_front
@hit:   jsr count_hit
sp_front:
        ldy #0
:       txa
        cmp SPC_ORD,y
        beq :+
        iny
        cpy #SPC_LINES
        bne :-
        lda #GS_API
        jmp stop
:       cpy #0
        beq :+
        lda SPC_ORD-1,y
        sta SPC_ORD,y
        dey
        bra :-
:       stx SPC_ORD
        lda spc_lo,x
        sta GC_XP
        lda spc_hi,x
        sta GC_XP+1
        stx GO_LAST+3
        rts

; sp_find: carry set and X = the line of handle GO_T
sp_find:
        ldx #SPC_LINES - 1
:       lda SPC_TL,x
        cmp GO_T
        bne @next
        lda SPC_TH,x
        cmp GO_T+1
        bne @next
        sec
        rts
@next:  dex
        bpl :-
        clc
        rts

; sp_take: X = the least recently got line, written back, tagged GO_T
sp_take:
        ldx SPC_ORD + SPC_LINES - 1
        jsr sp_wback
        lda GO_T
        sta SPC_TL,x
        lda GO_T+1
        sta SPC_TH,x
        stz SPC_DT,x
        rts

; sp_store: LW_SPEC into handle GC_H's line, dirty
sp_store:
        lda GC_H
        sta GO_T
        lda GC_H+1
        sta GO_T+1
        jsr sp_find
        bcs :+
        jsr sp_take
:       lda #1
        sta SPC_DT,x
        jsr sp_front
        ldy #SPEC_SIZE - 1
:       lda LW_SPEC,y
        sta (GC_XP),y
        dey
        bpl :-
        rts

; sp_dirty: the special last got changed
sp_dirty:
        ldx SPC_ORD
        lda SPC_TH,x
        cmp #$FF
        beq @none
        lda #1
        sta SPC_DT,x
        rts
@none:  lda #GS_API
        jmp stop

sp_wback:
        lda SPC_DT,x
        beq @done
        lda SPC_TH,x
        cmp #$FF
        beq @clean
        jsr sp_addr
        lda #ZONE0
        sta FA_BANK
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        lda spc_lo,x
        sta FA_SRC
        lda spc_hi,x
        sta FA_SRC+1
        lda #SPEC_SIZE
        sta FA_N
        jsr far_put
        jsr count_wback
@clean: stz SPC_DT,x
@done:  rts

; sp_addr: GO_P = SPEC_BASE + 32 (handle - SPEC_HANDLE) of line X; X kept
sp_addr:
        sec
        lda SPC_TL,x
        sbc #<SPEC_HANDLE
        sta GO_P
        lda SPC_TH,x
        sbc #>SPEC_HANDLE
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        asl GO_P
        rol a
        sta GO_P+1
        clc
        lda GO_P
        adc #<SPEC_BASE
        sta GO_P
        lda GO_P+1
        adc #>SPEC_BASE
        sta GO_P+1
        rts
        .assert SPEC_SIZE = 32, error, "a special's record"

spc_lo:
        .repeat SPC_LINES, I
        .byte <(SPC + SPC_LINE * I)
        .endrepeat
spc_hi:
        .repeat SPC_LINES, I
        .byte >(SPC + SPC_LINE * I)
        .endrepeat

; ===========================================================================
; The read-only fetches (no cache)
; ===========================================================================

; nd_get: LW_NODEB = node A:X (LVMAP NODEBASE + 32 n)
nd_get:
        sta FA_SRC
        txa
        ldx #5
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<NODEBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>NODEBASE
        sta FA_SRC+1
        ldx #<LW_NODEB
        ldy #>LW_NODEB
        lda #NODEB_SIZE
        sta FA_N
        lda #LVMAP
        jmp fetch_to
        .assert NODE_SIZE = 32, error, "a node record"

; sg_get: SG_BUF = seg A:X (LVSEG SEGBASE + 24 n)
sg_get:
        sta GO_P                ; 24 n = 8 n + 16 n
        stx GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        asl GO_P
        rol GO_P+1
        clc
        lda FA_SRC
        adc GO_P
        sta FA_SRC
        lda FA_SRC+1
        adc GO_P+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SEGBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SEGBASE
        sta FA_SRC+1
        ldx #<SG_BUF
        ldy #>SG_BUF
        lda #SEG_SIZE_G
        sta FA_N
        lda #LVSEG
        jmp fetch_to

; ss_get: SS_BUF = subsector A:X (LVMAP SUBBASE + 4 n)
ss_get:
        sta FA_SRC
        txa
        asl FA_SRC
        rol a
        asl FA_SRC
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SUBBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SUBBASE
        sta FA_SRC+1
        ldx #<SS_BUF
        ldy #>SS_BUF
        lda #SUB_SIZE
        sta FA_N
        lda #LVMAP
        jmp fetch_to

; bl_get: BL_BUF = 256 bytes of the blockmap from its word A:X (LVG2
; BLOCKMAP_AT + 2 w)
bl_get:
        sta FA_SRC
        txa
        asl FA_SRC
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<BLOCKMAP_AT
        sta FA_SRC
        lda FA_SRC+1
        adc #>BLOCKMAP_AT
        sta FA_SRC+1
        ldx #<BL_BUF
        ldy #>BL_BUF
        stz FA_N                ; (256)
        lda #LVG2
; fetch_to: FA_N bytes of bank A at FA_SRC to main Y:X
fetch_to:
        sta FA_BANK
        stx FA_DST
        sty FA_DST+1
        jmp far_get

; ===========================================================================
; The tic images' uncached records (no cache: each a far access)
; ===========================================================================
.ifndef LOADIMG

; sd_get: SD_BUF = side A:X (LVMAP SIDEBASE + 8 n), SD_AT its address
sd_get:
        sta SD_AT
        txa
        asl SD_AT
        rol a
        asl SD_AT
        rol a
        asl SD_AT
        rol a
        clc
        adc #>SIDEBASE
        sta SD_AT+1
        sta FA_SRC+1
        lda SD_AT
        sta FA_SRC
        ldx #<SD_BUF
        ldy #>SD_BUF
        lda #SIDE_SIZE
        sta FA_N
        lda #LVMAP
        jmp fetch_to
        .assert <SIDEBASE = 0 && SIDE_SIZE = 8, error, "a side"

; sd_put: SD_BUF back to the side at SD_AT
sd_put:
        lda SD_AT
        sta FA_DST
        lda SD_AT+1
        sta FA_DST+1
        lda #<SD_BUF
        sta FA_SRC
        lda #>SD_BUF
        sta FA_SRC+1
        lda #SIDE_SIZE
        sta FA_N
        lda #LVMAP
        sta FA_BANK
        jmp far_put

; lt_get: A:X = API_W = the line of line-table entry A:X (LVG1 G_LTABAT +
; 2 n)
lt_get:
        sta FA_SRC
        txa
        asl FA_SRC
        rol a
        tax
        clc
        lda FA_SRC
        adc G_LTABAT
        sta FA_SRC
        txa
        adc G_LTABAT+1
        sta FA_SRC+1
        bra word_get

; bk_get: A:X = API_W = the first mobj of block A:X's list (LVG1
; G_BLINKSAT + 2 n)
bk_get:
        jsr bk_at
; word_get: A:X = API_W = the word of LVG1 at FA_SRC
word_get:
        lda #LVG1
word_bank:
        ldx #<API_W
        ldy #>API_W
        sta FA_BANK
        stx FA_DST
        sty FA_DST+1
        lda #2
        sta FA_N
        jsr far_get
        lda API_W
        ldx API_W+1
        rts

; bk_put: the first mobj of block A:X's list = API_W
bk_put:
        jsr bk_at
        lda FA_SRC
        sta FA_DST
        lda FA_SRC+1
        sta FA_DST+1
        lda #LVG1
; word_put: the word API_W to bank A at FA_DST
word_put:
        sta FA_BANK
        lda #<API_W
        sta FA_SRC
        lda #>API_W
        sta FA_SRC+1
        lda #2
        sta FA_N
        jmp far_put

; bk_at: FA_SRC = G_BLINKSAT + 2 block A:X
bk_at:
        sta FA_SRC
        txa
        asl FA_SRC
        rol a
        tax
        clc
        lda FA_SRC
        adc G_BLINKSAT
        sta FA_SRC
        txa
        adc G_BLINKSAT+1
        sta FA_SRC+1
        rts

; sn_get: SN_BUF = sector node A:X (ZONE1 SN_BASE + 16 n)
sn_get:
        ldy #0
        jsr sn_at
        ldx #<SN_BUF
        ldy #>SN_BUF
        lda #SN_SIZE
        sta FA_N
        lda #ZONE1
        jmp fetch_to

; sn_put: sector node A:X = SN_BUF
sn_put:
        ldy #0
        jsr sn_at
        lda #<SN_BUF
        sta FA_SRC
        lda #>SN_BUF
        sta FA_SRC+1
        lda #SN_SIZE
        sta FA_N
        lda #ZONE1
        sta FA_BANK
        jmp far_put

; sn_putw: the word at offset Y of sector node A:X = API_W
sn_putw:
        jsr sn_at
        lda #ZONE1
        bra word_put

; sn_at: FA_DST = FA_SRC = SN_BASE + 16 node A:X + Y
sn_at:
        sta GO_P
        stx GO_P+1
        ldx #4
:       asl GO_P
        rol GO_P+1
        dex
        bne :-
        tya
        clc
        adc GO_P
        sta GO_P
        bcc :+
        inc GO_P+1
:       clc
        lda GO_P
        adc #<SN_BASE
        sta FA_SRC
        sta FA_DST
        lda GO_P+1
        adc #>SN_BASE
        sta FA_SRC+1
        sta FA_DST+1
        rts
        .assert SN_SIZE = 16, error, "a sector node"

; mi_get: A:X = API_W = the word at offset Y of mobjinfo[type A] (GTAB
; GT_MOBJINFO + 64 type)
mi_get:
        sty GO_P
        stz FA_SRC
        lsr a
        ror FA_SRC
        lsr a
        ror FA_SRC
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc GO_P
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       clc
        lda FA_SRC
        adc #<GT_MOBJINFO
        sta FA_SRC
        lda FA_SRC+1
        adc #>GT_MOBJINFO
        sta FA_SRC+1
        lda #GTAB
        jmp word_bank
        .assert INFO_SIZE = 64, error, "a mobjinfo record"

; hn_get: A:X = the sight hint of mobj slot A:X (MOBJP HINTL, HINTH)
hn_get:
        jsr hn_at
        lda #<GO_T
        sta FA_DST
        lda #>GO_T
        sta FA_DST+1
        jsr far_get             ; HINTL
        jsr hn_high
        inc FA_DST
        jsr far_get             ; HINTH
        lda GO_T
        ldx GO_T+1
        rts

; hn_put: the sight hint of mobj slot A:X = API_W
hn_put:
        jsr hn_at
        lda FA_SRC
        sta FA_DST
        lda FA_SRC+1
        sta FA_DST+1
        lda #<API_W
        sta FA_SRC
        lda #>API_W
        sta FA_SRC+1
        jsr far_put             ; HINTL
        clc
        lda FA_DST+1
        adc #>(PL_HINTH - PL_HINTL)
        sta FA_DST+1
        inc FA_SRC
        bne :+
        inc FA_SRC+1
:       jmp far_put             ; HINTH

; hn_at: FA_SRC = HINTL + slot A:X, bank MOBJP, one byte
hn_at:
        clc
        adc #<PL_HINTL
        sta FA_SRC
        txa
        adc #>PL_HINTL
        sta FA_SRC+1
        lda #MOBJP
        sta FA_BANK
        lda #1
        sta FA_N
        rts
; hn_high: FA_SRC from HINTL's plane to HINTH's
hn_high:
        clc
        lda FA_SRC+1
        adc #>(PL_HINTH - PL_HINTL)
        sta FA_SRC+1
        rts
        .assert <(PL_HINTH - PL_HINTL) = 0 && <GO_T <> $FF, error,  "the hint planes"

; rj_row: A:X = RJROW[sector A] (LVS)
rj_row:
        asl a
        sta FA_SRC
        lda #0
        rol a
        tax
        clc
        lda FA_SRC
        adc #<LVS_RJROW
        sta FA_SRC
        txa
        adc #>LVS_RJROW
        sta FA_SRC+1
        lda #LVS
        jmp word_bank

; rj_byte: A = the byte of REJECT at offset A:X (LVG2 G_REJECTAT + A:X)
rj_byte:
        clc
        adc G_REJECTAT
        sta FA_SRC
        txa
        adc G_REJECTAT+1
        sta FA_SRC+1
        lda #LVG2
        sta FA_BANK
        lda #<GO_T
        sta FA_DST
        lda #>GO_T
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        lda GO_T
        rts
.endif

; ===========================================================================
; The whole caches
; ===========================================================================

; go_flush: every dirty line back, then every line empty
go_flush:
        ldx #MOC_LINES - 1
:       jsr mo_wback
        dex
        bpl :-
        ldx #SCC_LINES - 1
:       jsr sec_wback
        dex
        bpl :-
        ldx #LNC_LINES - 1
:       jsr ln_wback
        dex
        bpl :-
        ldx #SPC_LINES - 1
:       jsr sp_wback
        dex
        bpl :-
        ; (on into go_reset)

; go_reset: every line empty, the orders 0 up, no line last got
go_reset:
        ldx #7
:       lda #$FF
        sta MOC_TL,x
        sta MOC_TH,x
        sta SCC_TAG,x
        sta LNC_TL,x
        sta LNC_TH,x
        stz MOC_DT,x
        stz SCC_DT,x
        stz LNC_DT,x
        txa
        sta MOC_ORD,x
        sta SCC_ORD,x
        sta LNC_ORD,x
        dex
        bpl :-
        ldx #SPC_LINES - 1
:       lda #$FF
        sta SPC_TL,x
        sta SPC_TH,x
        stz SPC_DT,x
        txa
        sta SPC_ORD,x
        dex
        bpl :-
        lda #$FF
        sta GO_LAST
        sta GO_LAST+1
        sta GO_LAST+2
        sta GO_LAST+3
        rts

; go_stamps0: the release's validcount wrap (gvalid.s): the caches
; flushed and emptied, then every sector's stamp (LVMAP) and every line's
; two stamps (LVG0) 0
go_stamps0:
        jsr go_flush
        stz GO_I                ; a zero word, twice
        stz GO_J
        stz GO_T
        stz GO_T+1
        .assert GO_J = GO_I + 1 && GO_T = GO_J + 1, error, "four zeros"
        lda #LVMAP
        sta FA_BANK
        lda #<(SECBASE + SEC_VALID)
        sta FA_DST
        lda #>(SECBASE + SEC_VALID)
        sta FA_DST+1
        lda LVCOUNT
        sta GO_P
        lda LVCOUNT+1
        sta GO_P+1
        lda #SEC_SIZE
        sta FC_PS               ; (the record's size)
        lda #2
        jsr @zeros
        lda #LVG0
        sta FA_BANK
        lda #<(LINE_BASE + LN_VALID)
        sta FA_DST
        lda #>(LINE_BASE + LN_VALID)
        sta FA_DST+1
        lda LVCOUNT2
        sta GO_P
        lda LVCOUNT2+1
        sta GO_P+1
        lda #LINE_SIZE
        sta FC_PS
        lda #4
; (A bytes of zeros at FA_DST, then the next record, GO_P times)
@zeros: sta FA_N
        lda #<GO_I
        sta FA_SRC
        lda #>GO_I
        sta FA_SRC+1
@rec:   lda GO_P
        ora GO_P+1
        beq @done
        jsr far_put
        clc
        lda FA_DST
        adc FC_PS
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       lda GO_P
        bne :+
        dec GO_P+1
:       dec GO_P
        bra @rec
@done:  rts
        .assert LN_RVALID = LN_VALID + 2, error, "the line's two stamps"

; the counters (the tests read them)
count_hit:
        inc GO_HITS
        bne :+
        inc GO_HITS+1
:       rts
count_miss:
        inc GO_MISS
        bne :+
        inc GO_MISS+1
:       rts
count_wback:
        inc GO_WBACK
        bne :+
        inc GO_WBACK+1
:       rts

; stop: the API's stops (A the code)
stop:
.ifdef LOADIMG
        cmp #GS_PLANES
        bne :+
        lda #LS_PLANES
        jmp ld_stop
:       lda #LS_API
        jmp ld_stop
.else
        jmp g_stop
.endif

; ===========================================================================
; The planes (docs/GAME.md 1.3): in W in the tic phase, far (bank MOBJP)
; in the load image
; ===========================================================================

; pl_get: PL_N, PL_K, PL_T = the planes of slot A:X
pl_get:
        jsr pl_ptr
.ifdef LOADIMG
        stz GO_J
:       jsr pl_far
        jsr far_get
        inc GO_J
        lda GO_J
        cmp #4
        bne :-
        rts
.else
        lda (GO_P)
        sta PL_N
        jsr pl_page
        lda (GO_P)
        sta PL_N+1
        jsr pl_page
        lda (GO_P)
        sta PL_K
        jsr pl_page
        lda (GO_P)
        sta PL_T
        rts
.endif

; pl_put: the planes of slot A:X = PL_N, PL_K, PL_T
pl_put:
        jsr pl_ptr
.ifdef LOADIMG
        stz GO_J
:       jsr pl_far
        jsr pl_swap
        jsr far_put
        inc GO_J
        lda GO_J
        cmp #4
        bne :-
        rts
.else
        lda PL_N
        sta (GO_P)
        jsr pl_page
        lda PL_N+1
        sta (GO_P)
        jsr pl_page
        lda PL_K
        sta (GO_P)
        jsr pl_page
        lda PL_T
        sta (GO_P)
        rts
.endif

; pl_setn: the next thinker of slot A:X = PL_N
pl_setn:
        jsr pl_ptr
.ifdef LOADIMG
        stz GO_J
:       jsr pl_far
        jsr pl_swap
        jsr far_put
        inc GO_J
        lda GO_J
        cmp #2
        bne :-
        rts
.else
        lda PL_N
        sta (GO_P)
        jsr pl_page
        lda PL_N+1
        sta (GO_P)
        rts
.endif

; pl_ptr: GO_P = PL_TNL + slot A:X (a stop past the planes)
pl_ptr:
        cpx #>PLANE_SLOTS
        bcc :+
        lda #GS_PLANES
        jmp stop
:       clc
        adc #<PL_TNL
        sta GO_P
        txa
        adc #>PL_TNL
        sta GO_P+1
        rts
        .assert <PL_TNL = 0 && <PLANE_SLOTS = 0, error, "pages"

.ifdef LOADIMG
; pl_far: the far layer's arguments for plane GO_J of GO_P: one byte of
; bank MOBJP at GO_P + GO_J planes on, to (or from) PL_N + GO_J (the
; planes' order is the values' order)
pl_far:
        lda #MOBJP
        sta FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_J
        asl a                   ; GO_J * 3 pages
        adc GO_J
        adc GO_P+1
        sta FA_SRC+1
        lda GO_J
        clc
        adc #<PL_N
        sta FA_DST
        lda #>PL_N
        adc #0
        sta FA_DST+1
        lda #1
        sta FA_N
        rts
        .assert PL_K = PL_N + 2 && PL_T = PL_K + 1, error, "the order"
        .assert >PLANE_SLOTS = 3, error, "three pages a plane"
; pl_swap: FA_SRC and FA_DST exchanged (a put)
pl_swap:
        lda FA_SRC
        ldx FA_DST
        sta FA_DST
        stx FA_SRC
        lda FA_SRC+1
        ldx FA_DST+1
        sta FA_DST+1
        stx FA_SRC+1
        rts
.else
; pl_page: GO_P one plane on (PLANE_SLOTS: three pages)
pl_page:
        clc
        lda GO_P+1
        adc #>PLANE_SLOTS
        sta GO_P+1
        rts
.endif
