; game/pspr/pflood.s: part pspr's sound flood (milestone 10, docs/GAME.md
; 2.4, 4.1; docs/LEVELS.md 5.5; docs/game-parts/pspr.md). A GPL-2
; derivative of upstream's p_pspr65.s recursiveSound (P_RecursiveSound),
; made iterative with a work stack of 512 entries.
;
;   recursiveSound  A = a sector, Y = the sound blocks (0 or 1), PS_TGT the
;                   sound target: the sound floods from the sector through
;                   the open two-sided lines; a line with ML_SOUNDBLOCK
;                   lets it through once. A sector already flooded in this
;                   validcount with as few blocks (soundtraversed <= blocks
;                   + 1) is left; else it gets validcount, soundtraversed =
;                   blocks + 1 and soundtarget, and then its flood list's
;                   entries without ML_SOUNDBLOCK, in the list's order, pass
;                   the sound on with its blocks, and when it came with none
;                   the entries with ML_SOUNDBLOCK pass it on with 1. An
;                   entry is skipped when its sector is flooded already with
;                   as few blocks or the opening of the two sectors is
;                   closed (openrange <= 0, 32 bits)
;
; Upstream recurses with the hardware stack (6 bytes a level and its
; return); here each level that passes the sound on pushes its entry and
; its part on a work stack of FL_DEPTH entries (two planes of FL_DEPTH
; bytes: the entry's low byte, its high bits with v and the part) in this
; routine's group, after its code (docs/GAME.md 4.1: the group keeps its
; data in its slot), and the callee's level runs in the same loop. A
; level's sector is not kept: it is the first level's (PS_ST) or the flood
; entry of the level below it (LEVELS.md 5.5 planned 3 bytes an entry, the
; sector too: 2 leave the group room for its code). The order of every stamp is upstream's. A flood deeper than
; FL_DEPTH is a stop (PS_GS_FLOOD, the sector in GS_ARG), never a silent
; cut: the deepest flood of an E1 map with every line open is 93, its bound
; 500 (LEVELS.md 5.5).
;
; Two pieces of code kept here, marked where they are (docs/game-parts/
; pspr.md R3 and R5, refused at wave 3's integration: the core is full,
; and P_LineOpening's hot callers would load the flood's 1.9 KB group):
;   - the flood lists (LVG1 FLIDX, FLENT) are read through the object API's
;     lt_get, whose entry i is the word at G_LTABAT + 2 i of LVG1, the
;     lists being after the line tables (llayout.py "LVG1": the line
;     tables, the index, the entries, each from the end of the one before,
;     so at even distances)
;   - the opening is computed here (P_LineOpeningXY's openrange of the two
;     sectors: the lower ceiling less the higher floor, 32 bits): an FCALL
;     of geom's P_LineOpeningXY in another group of this group's slot
;     would reload the slot and lose the work stack, so the flood calls
;     only the core
;
; Changes A, X, Y, GT_0-GT_6, the API's temporaries, the scratch block's
; flood bytes.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/pspr/pspr.inc"

        .export recursiveSound, ps_stack
        .import sec_get, sec_dirty, lt_get, g_stop, fc_call, fc_unbuilt

        ROUTINE recursiveSound
        sta PS_SEC
        sta PS_ST               ; (the first level's sector)
        tya                     ; v = the blocks (bit 7), the part without
        lsr a                   ;   ML_SOUNDBLOCK
        ror a
        and #FL_V
        sta PS_V
        stz PS_SP               ; the work stack empty
        stz PS_SP+1
        ldx #2                  ; (R3 refused) PS_FLI, PS_FLE: the
:       sec                     ;   index's and the entries' places as
        lda G_FLIDXAT,x         ;   lt_get entries
        sbc G_LTABAT
        sta GT_0
        lda G_FLIDXAT+1,x
        sbc G_LTABAT+1
        lsr a
        sta PS_FLI+1,x
        lda GT_0
        ror a
        sta PS_FLI,x
        dex
        dex
        bpl :-
        .assert G_FLENTAT = G_FLIDXAT + 2 && PS_FLE = PS_FLI + 2, error, "the places"
        ; ---- a level: the sector PS_SEC with the blocks of PS_V --------
@enter: lda PS_SEC
        jsr sec_get
        jsr stamped             ; flooded already with as few blocks:
        jcs @ret                ;   back to the level that called
        ldy #SEC_VALID          ; validcount, soundtraversed, soundtarget
        lda G_VALID
        sta (GC_SP),y
        iny
        lda G_VALID+1
        sta (GC_SP),y
        jsr vplus1
        ldy #SEC_G + SG_TRAVERSED
        sta (GC_SP),y
        ldy #SEC_G + SG_TARGET
        lda PS_TGT
        sta (GC_SP),y
        iny
        lda PS_TGT+1
        sta (GC_SP),y
        lda #3                  ; the render record and the game record
        jsr sec_dirty
        ldy #0                  ; the entries without ML_SOUNDBLOCK
@part:  jsr fl_idx              ; the part's first entry (Y), its end
        sta PS_POS
        stx PS_POS+1
        jsr fl_end
        ; ---- the entries of the part --------------------------------------
@loop:  lda PS_POS              ; the end of the part?
        cmp PS_END
        lda PS_POS+1
        sbc PS_END+1
        jcs @pend
        lda PS_POS              ; the other sector
        ldx PS_POS+1
        jsr fl_ent
        sta PS_OTH
        jsr sec_get             ; flooded already with soundtraversed <=
        jsr stamped             ;   v + 1: no call
        bcs @next
        jsr opening             ; closed: no call
        bcc @next
        ; P_RecursiveSound(other, v): this level on the work stack
        lda PS_SP+1
        cmp #>FL_DEPTH
        bcs @deep
        lda PS_POS+1
        cmp #FL_B
        bcc :+
@deep:  lda PS_SEC              ; deeper than the stack (or an entry past
        sta GS_ARG              ;   $3FFF: never in E1): a stop
        lda #PS_GS_FLOOD
        jmp g_stop
:       ora PS_V                ; the high bits, v, the part
        pha
        jsr at_top
        lda PS_POS
        sta (GT_2)
        jsr plane
        pla
        sta (GT_2)
        inc PS_SP
        bne :+
        inc PS_SP+1
:       lda PS_OTH              ; the callee's level: the other sector with
        sta PS_SEC              ;   v, the part without ML_SOUNDBLOCK
        lda PS_V
        and #FL_V
        sta PS_V
        jmp @enter
        ; ---- the next entry ------------------------------------------------
@next:  inc PS_POS
        jne @loop
        inc PS_POS+1
        jmp @loop
        ; ---- the end of a part: after v = 0, the entries with
        ; ML_SOUNDBLOCK with v = 1; else the level is done ---------------------
@pend:  lda PS_V
        bne @ret
        lda #FL_V | FL_B
        sta PS_V
        ldy #2
        jmp @part
        ; ---- a level done: back to the one that called ---------------------
@ret:   lda PS_SP
        ora PS_SP+1
        bne :+
        rts
:       lda PS_SP
        bne :+
        dec PS_SP+1
:       dec PS_SP
        jsr at_top
        lda (GT_2)
        sta PS_POS
        jsr plane
        lda (GT_2)
        tax
        and #FL_B - 1
        sta PS_POS+1
        txa
        and #FL_V | FL_B
        sta PS_V
        lda PS_ST               ; its sector: the first level's, or the
        ldx PS_SP               ;   entry of the level below it
        bne :+
        ldx PS_SP+1
        beq @sec
:       lda GT_2                ; the entry below the top (GT_2-3:
        bne :+                  ;   the second plane at the top)
        dec GT_3
:       dec GT_2
        lda (GT_2)
        and #FL_B - 1
        tax
        dec GT_3
        dec GT_3
        lda (GT_2)
        jsr fl_ent
@sec:   sta PS_SEC
        jsr fl_end
        jmp @next

; at_top: GT_2-3 = the work stack's first plane at the top; plane: the
; second
at_top: clc
        lda #<ps_stack
        adc PS_SP
        sta GT_2
        lda #>ps_stack
        adc PS_SP+1
        sta GT_3
        rts
plane:  lda GT_3
        clc
        adc #>FL_DEPTH
        sta GT_3
        rts
        .assert <FL_DEPTH = 0, error, "the planes a whole number of pages"

; fl_ent: A = the flood entry A:X (a sector: LVG1 G_FLENTAT + the entry, a
; byte), through lt_get (request R3 refused: the header)
fl_ent: sta GT_0                ; PS_FLE + the entry / 2
        txa
        lsr a
        tax
        lda GT_0
        ror a
        clc
        adc PS_FLE
        pha
        txa
        adc PS_FLE+1
        tax
        pla
        jsr lt_get
        lsr GT_0                ; an odd entry: the high byte
        bcc :+
        txa
:       rts

; vplus1: A = v + 1 (v: bit 7 of PS_V)
vplus1: lda PS_V
        asl a
        lda #1
        adc #0
        rts

; stamped: C set when the sector at GC_SP is flooded already in this
; validcount with soundtraversed <= v + 1, signed (upstream's tests,
; p_pspr65.s:453-463 and :488-495: soundtraversed is a byte here, sign
; extended, so upstream's 16-bit differences cannot overflow)
stamped:
        ldy #SEC_VALID
        lda (GC_SP),y
        cmp G_VALID
        bne @no
        iny
        lda (GC_SP),y
        cmp G_VALID+1
        bne @no
        ldy #SEC_G + SG_TRAVERSED
        lda (GC_SP),y
        bmi @yes                ; negative: <= any
        sta GT_0
        jsr vplus1              ; v + 1 >= soundtraversed
        cmp GT_0
        rts
@yes:   sec
        rts
@no:    clc
        rts

; fl_end: PS_END = the end of PS_V's part (index word 1 or 3); fl_idx:
; A:X = word Y (0 the first entry, 1 the end of the entries without
; ML_SOUNDBLOCK, 2 the first with it, 3 the end) of PS_SEC's flood index
; (LVG1 G_FLIDXAT + 8 s + 2 Y), through lt_get (request R3 refused)
fl_end: ldy #1
        bit PS_V
        bvc :+
        ldy #3
:       jsr fl_idx
        sta PS_END
        stx PS_END+1
        rts
fl_idx: sty GT_0                ; PS_FLI + 4 s + Y
        stz GT_1
        lda PS_SEC
        asl a
        rol GT_1
        asl a
        rol GT_1
        adc GT_0                ; (C clear: rol of a zero)
        bcc :+
        inc GT_1
:       clc
        adc PS_FLI
        pha
        lda GT_1
        adc PS_FLI+1
        tax
        pla
        jmp lt_get

; opening: C set when the opening of the sectors PS_OTH and PS_SEC is open
; (openrange > 0): openrange = min(the ceilings) - max(the floors), 32
; bits, the compares signed with the overflow corrected, as upstream's
; openXY (p_map65.s:2412-2450). Request R5 (FCALL P_LineOpeningXY)
; refused: the header
opening:
        lda PS_SEC
        jsr sec_get
        lda GC_SP
        sta GT_2
        lda GC_SP+1
        sta GT_3
        lda PS_OTH
        jsr sec_get             ; (the four most recent lines stay)
        lda GC_SP
        sta GT_0
        lda GC_SP+1
        sta GT_1
        ldy #SEC_FLOOR          ; GT_4-5 = the higher floor's sector
        jsr cmp32               ;   (other's - sec's floor)
        bmi :+
        ldx #0
        bra :++
:       ldx #2
:       lda GT_0,x
        sta GT_4
        lda GT_1,x
        sta GT_5
        ldy #SEC_CEIL           ; GT_0-1 = the lower ceiling's sector
        jsr cmp32
        bmi :+
        lda GT_2
        sta GT_0
        lda GT_3
        sta GT_1
:       clc                     ; its ceiling: GT_0-1 + SEC_CEIL
        lda GT_0
        adc #SEC_CEIL
        sta GT_0
        bcc :+
        inc GT_1
:       ldy #SEC_FLOOR          ; openrange = ceiling - floor
        stz GT_6
        ldx #4
        sec
:       lda (GT_0),y
        sbc (GT_4),y
        tsb GT_6                ; (its bits gathered; C stays)
        iny
        dex
        bne :-
        tax                     ; negative or 0: closed
        bmi @shut
        lda GT_6
        beq @shut
        sec
        rts
@shut:  clc
        rts
        .assert SEC_FLOOR = 0, error, "the floor first"

; cmp32: N = the sign of (GT_0),y - (GT_2),y over 4 bytes, the overflow
; corrected (upstream's sbc, bvc, eor); changes X, Y
cmp32:  ldx #4
        sec
:       lda (GT_0),y
        sbc (GT_2),y
        iny
        dex
        bne :-
        bvc :+
        eor #$80
:       ora #0
        rts

; the work stack: two planes of FL_DEPTH bytes (scratch: a load of the
; group brings zeros)
ps_stack:
        .res FL_BYTES
