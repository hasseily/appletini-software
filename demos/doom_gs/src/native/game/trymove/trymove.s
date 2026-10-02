; game/trymove/trymove.s: part trymove's move (milestone 10, docs/GAME.md
; 2.4 row trymove, 0.3 fact 4; docs/game-parts/trymove.md). A GPL-2
; derivative of upstream's p_map65.s (P_TryMove with lessHeight, overStep,
; its move, mvNodes, spec and specLine).
;
;   P_TryMove   GA_0-1 the thing, GA_2-5 x, GA_6-9 y. A = 1 (C set) when
;               the thing moved there, else A = 0 (C clear). cpCopy and
;               checkPos with MP_TRY 1 (part checkpos); when PIT_CheckThing
;               ran (G_MPCLOB) tmthing, tmx, tmy come back from the part's
;               copy and pointSector (geom) finds the new sector again.
;               Unless MF_NOCLIP: tmceilingz - tmfloorz < height, then
;               tmceilingz - z < height (lessHeight, signed), then
;               tmfloorz - z > 24.0 (overStep: the step), then, unless
;               MF_DROPOFF, tmfloorz - tmdropoffz > 24.0 (the drop-off)
;               refuse the move. The move: oldx, oldy kept when numspechit
;               is not 0; unless MF_NOSECTOR the sector list (the thing
;               stays when it is the first of the new sector's list already:
;               mvSector, part mobjstate); unless MF_NOBLOCKMAP the block
;               list (mvBlock); the kind plane's CLEAN off; floorz, ceilingz,
;               dropoffz = tmfloorz, tmceilingz, tmdropoffz; x, y = tmx,
;               tmy; the subsector GM_SS; unless MF_NOSECTOR the node list
;               (mvNodes); unless MF_NOCLIP the crossed special lines
;               (spec)
;   mvNodes     (in place) with no game logic in the check (G_MPCLOB 0) and
;               its line record kept (LR_OK): when the box crossed no line
;               (LR_N 0) and the thing's node list is one node, of the new
;               sector, upstream's shortcut: validcount + 1 and
;               _s_sector_list none, the list as it was; else LR_USE 1 (the
;               walk takes the record's lines, stamping none: fact 4).
;               Then P_SetSeclist (_s_sector_list = the thing's list, its
;               list none) and P_CreateSecNodeList (the core's)
;   spec        (in place) while (numspechit--): the line spechit[numspechit]
;               with a special whose side of oldx, oldy differs from the
;               thing's side now gets P_CrossSpecialLine(line, the thing,
;               the old side) (part lines). numspechit is re-read each turn
;               (game logic may change it); it ends at $FF (upstream's -1)
;   lessHeight, overStep, specLine  (in place) the signed 32-bit tests and
;               the line's fetch
;
; Every record through the object API (mo_get, sec_get, ln_get, sn_get, the
; planes); upstream's TP is the handle TM_TH, its frame the scratch block
; (trymove.inc). A routine changes A, X, Y, GA_*, GT_*, the math block, the
; API's temporaries and what its callees change.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/trymove/trymove.inc"

        .export P_TryMove
        .import mo_get, mo_dirty, sec_get, ln_get, sn_get, pl_get, pl_put
        .import gv_inc, fc_call, fc_unbuilt

; ===========================================================================
; P_TryMove
; ===========================================================================
        ROUTINE P_TryMove
        FCALL cpCopy                    ; tmthing, tmx, tmy
        ldx #9                          ; the frame's copy of them
:       lda GM_TMTHING,x
        sta TM_SAVE,x
        dex
        bpl :-
        lda #1                          ; MP_TRY: from P_TryMove
        sta GM_MPTRY
        FCALL checkPos
        bcs :+
        jmp tm_false
:       lda G_MPCLOB                    ; game logic ran: tmthing, tmx, tmy
        ora G_MPCLOB+1                  ;   back, and their sector
        beq @clean
        ldx #9
:       lda TM_SAVE,x
        sta GM_TMTHING,x
        dex
        bpl :-
        ldx #7                          ; pointSector(tmx, tmy)
:       lda GM_TMX,x
        sta GA_X,x
        dex
        bpl :-
        FCALL pointSector
@clean: lda GM_TMTHING                  ; TP = the thing
        sta TM_TH
        ldx GM_TMTHING+1
        stx TM_TH+1
        jsr mo_get
        ldy #LN_B + MB_FLAGS + 1        ; MF_NOCLIP: no height checks
        lda (GC_MP),y
        and #>UC_MF_NOCLIP_LO
        jne tm_move
        ; tmceilingz - tmfloorz < height
        ldx #0
        sec
:       lda GM_TMCEILZ,x
        sbc GM_TMFLOORZ,x
        sta GT_0,x
        inx
        txa
        eor #4
        bne :-
        jsr lessHeight
        bcs tm_false
        ; tmceilingz - z < height
        ldx #GM_TMCEILZ - GM_TMFLOORZ
        jsr fromZ
        jsr lessHeight
        bcs tm_false
        ; tmfloorz - z > 24.0 (the step)
        ldx #0
        jsr fromZ
        jsr overStep
        bcs tm_false
        ; !MF_DROPOFF && tmfloorz - tmdropoffz > 24.0
        ldy #LN_B + MB_FLAGS + 1
        lda (GC_MP),y
        and #>UC_MF_DROPOFF_LO
        jne tm_move
        ldx #0
        sec
:       lda GM_TMFLOORZ,x
        sbc GM_TMDROPZ,x
        sta GT_0,x
        inx
        txa
        eor #4
        bne :-
        jsr overStep
        jcc tm_move
tm_false:
        lda #0
        clc
        rts

; fromZ: GT_0-3 = (tmfloorz + X) - the thing's z (GC_MP its line)
fromZ:  ldy #TH_Z
        sec
        lda GM_TMFLOORZ,x
        sbc (GC_MP),y
        sta GT_0
        iny
        lda GM_TMFLOORZ+1,x
        sbc (GC_MP),y
        sta GT_1
        iny
        lda GM_TMFLOORZ+2,x
        sbc (GC_MP),y
        sta GT_2
        iny
        lda GM_TMFLOORZ+3,x
        sbc (GC_MP),y
        sta GT_3
        rts

; lessHeight: C set when the 32-bit GT_0-3 < the thing's height, signed
lessHeight:
        ldy #LN_B + MB_HEIGHT
        lda GT_0
        cmp (GC_MP),y
        iny
        lda GT_1
        sbc (GC_MP),y
        iny
        lda GT_2
        sbc (GC_MP),y
        iny
        lda GT_3
        sbc (GC_MP),y
        bvc :+
        eor #$80
:       asl a                           ; (the sign)
        rts

; overStep: C set when the 32-bit GT_0-3 > 24.0 ($0018:0000), signed:
; the sign of 24.0 - GT
overStep:
        sec
        lda #0
        sbc GT_0
        lda #0
        sbc GT_1
        lda #24
        sbc GT_2
        lda #0
        sbc GT_3
        bvc :+
        eor #$80
:       asl a
        rts

; ---------------------------------------------------------------------------
; the move (GC_MP the thing's line)
; ---------------------------------------------------------------------------
tm_move:
        lda GM_NSPEC                    ; oldx, oldy for the special lines
        beq @sector
        ldy #TH_X + 7
        ldx #7
:       lda (GC_MP),y
        sta TM_OX,x
        dey
        dex
        bpl :-
@sector:
        ldy #LN_B + MB_FLAGS            ; the sector list
        lda (GC_MP),y
        and #<UC_MF_NOSECTOR_LO
        bne @block
        ldy #LN_A + MA_SPREV + 1        ; the first of the new sector's list
        lda (GC_MP),y                   ;   already: it stays
        cmp #$FF
        bne @mvsec
        lda GM_SEC
        jsr sec_get
        ldy #SEC_THINGS
        lda (GC_SP),y
        cmp TM_TH
        bne @mvsec
        iny
        lda (GC_SP),y
        cmp TM_TH+1
        beq @block
@mvsec: lda GM_SEC
        sta GA_0
        lda TM_TH
        ldx TM_TH+1
        FCALL mvSector
@block: jsr tm_get                      ; the block list
        ldy #LN_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_NOBLOCKMAP_LO
        bne @fields
        ldx #7                          ; (tmx, tmy)
:       lda GM_TMX,x
        sta GA_X,x
        dex
        bpl :-
        lda TM_TH
        ldx TM_TH+1
        FCALL mvBlock
@fields:
        lda TM_TH                       ; not CLEAN (floorz can change)
        ldx TM_TH+1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda TM_TH
        ldx TM_TH+1
        jsr pl_put
        jsr tm_get
        ldy #LN_B + MB_FLOORZ + 11      ; floorz, ceilingz, dropoffz
        ldx #11
:       lda GM_TMFLOORZ,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        ldy #TH_X + 7                   ; x, y = tmx, tmy
        ldx #7
:       lda GM_TMX,x
        sta (GC_MP),y
        dey
        dex
        bpl :-
        ldy #LN_A + MA_SUBSEC           ; the subsector
        lda GM_SS
        sta (GC_MP),y
        iny
        lda GM_SS+1
        sta (GC_MP),y
        lda #D_RTH | D_A | D_B
        jsr mo_dirty
        ldy #LN_B + MB_FLAGS            ; the node list
        lda (GC_MP),y
        and #<UC_MF_NOSECTOR_LO
        bne @spec
        jsr mvNodes
@spec:  jsr tm_get                      ; the special lines that were crossed
        ldy #LN_B + MB_FLAGS + 1
        lda (GC_MP),y
        and #>UC_MF_NOCLIP_LO
        bne @done
        lda GM_NSPEC
        beq @done
        jsr spec
@done:  lda #1
        sec
        rts

; tm_get: GC_MP = the thing's line
tm_get: lda TM_TH
        ldx TM_TH+1
        jmp mo_get

; ---------------------------------------------------------------------------
; mvNodes: the node list of the thing at its new place
; ---------------------------------------------------------------------------
mvNodes:
        lda G_MPCLOB                    ; game logic ran, or no record: the
        ora G_MPCLOB+1                  ;   walk
        bne @list
        lda G_LROK
        beq @list
        lda G_LRN                       ; lines crossed: the record
        bne @use
        jsr tm_get                      ; one node, of the new sector: the
        ldy #LN_A + MA_TOUCH + 1        ;   list stays
        lda (GC_MP),y
        cmp #$FF
        beq @use
        tax
        dey
        lda (GC_MP),y
        jsr sn_get
        lda SN_BUF + SN_TNEXT + 1
        cmp #$FF
        bne @use
        lda SN_BUF + SN_SECTOR
        cmp GM_SEC
        bne @use
        jsr gv_inc                      ; the rest that P_CreateSecNodeList
        lda #$FF                        ;   leaves: validcount + 1, no list
        sta G_SECLIST
        sta G_SECLIST+1
        rts
@use:   lda #1                          ; the walk takes the record
        sta G_LRUSE
@list:  jsr tm_get                      ; P_SetSeclist(thing's list), its
        ldy #LN_A + MA_TOUCH            ;   list none
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
        lda TM_TH                       ; P_CreateSecNodeList(thing)
        ldx TM_TH+1
        FCALL P_CreateSecNodeList
        rts

; ---------------------------------------------------------------------------
; spec: the special lines that were crossed, the last first
; ---------------------------------------------------------------------------
spec:
@next:  dec GM_NSPEC                    ; while (numspechit--)
        lda GM_NSPEC
        cmp #$FF
        bne :+
        rts
:       asl a                           ; specLine: the line, its special
        tax
        lda GM_SPECHIT,x
        sta TM_LN
        lda GM_SPECHIT+1,x
        sta TM_LN+1
        tax
        lda TM_LN
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        beq @next
        ldx #7                          ; oldside = the side of oldx, oldy
:       lda TM_OX,x
        sta GA_X,x
        dex
        bpl :-
        lda TM_LN
        ldx TM_LN+1
        FCALL P_PointOnLineSide
        sta TM_OS
        jsr tm_get                      ; the side of the thing's x, y now
        ldy #TH_X + 7
        ldx #7
:       lda (GC_MP),y
        sta GA_X,x
        dey
        dex
        bpl :-
        lda TM_LN
        ldx TM_LN+1
        FCALL P_PointOnLineSide
        cmp TM_OS
        beq @next
        lda TM_LN                       ; P_CrossSpecialLine(line, thing,
        sta GA_0                        ;   oldside)
        lda TM_LN+1
        sta GA_1
        lda TM_TH
        sta GA_2
        lda TM_TH+1
        sta GA_3
        lda TM_OS
        FCALL P_CrossSpecialLine
        jmp @next
