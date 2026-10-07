; lgeom.s: the level load's static steps (docs/LEVELS.md): what upstream's loadLineDefs, groupLines and
; P_InitFlood compute, and the colormaps of I_SetLevelPalette, made from
; the store's bytes and the copied level window, as tools/native/
; lderive.py and lstore.py's HostMachine define them (their bytes are
; each map's window.img):
;
;   lg_lines    LINES: each compact line (the game lump's 15 bytes) into
;               its LVG0 record: v1, v2, dx, dy, the sides, the box (the
;               signed compares: upstream's v1.y - v2.y with the overflow
;               flip, p_setup65.s:311-353), tag, special, flags, the
;               slope type (dx 0: vertical; dy 0: horizontal; else the
;               sign of dy ^ dx), the stamps 0
;   lg_group    GROUP: each subsector's sector (the sector of its first
;               seg with a side, p_setup65.s:778-789) into LVMAP; the line
;               tables (each line in its front sector's, then its back
;               sector's when it has one that differs, :861-895; the
;               tables in sector order) into LVG1; each sector's game
;               record: the sound origin (M_AddToBox over its lines'
;               vertices in table order with upstream's else-if,
;               :1063-1102; halfSum, each 32-bit side shifted right
;               arithmetically, then the sum, :1038-1061), the line count
;               and first entry, special and old special, tag, the handles
;               $FFFF
;   lg_flood    FLOOD: the lines from the last to the first (p_pspr65.s:
;               1300-1303); for each two-sided line with two sectors, the
;               back into the front's list then the front into the back's
;               (fbOne, :1361-1374): without ML_SOUNDBLOCK up from the
;               sector's first entry, with it down from its end; each
;               sector's index (its first entry, the free part's end, the
;               block part's first, its end); the room the lists leave
;               zero
;   lg_cmaps    CMAPS: colormaps A and B in LVC, A[i] = GSVIEW_A[COLORMAP
;               [i]] (i_viigs65.s:1063-1077), the same with B
;   lg_gtabs    GTABS (docs/GAME.md; a game step: only in
;               nl_setup): LVS's tables: each line's front and back sector
;               (LNSECF, LNSECB: lg_prep's, the front twice for a one-sided
;               line: upstream's LNSEC) and each sector's REJECT row
;               (RJROW: sector x numsectors, the low 16 bits, 2 bytes a
;               sector: upstream's SS_ROW by sector, p_sight65.s:1557-1605)
;
; Every store and window access goes through far_get and far_put (the
; card). W holds the scratch (llayout.py: each line's front and back
; sector, each sector's count, first entry and two running positions).
;
; The box of a sector's sound origin keeps the high words of upstream's
; fixed_t sides (the vertices are whole map units: the low words are 0),
; and a flag for each of the two sides that start at INT32_MAX (left,
; bottom); the two that start at INT32_MIN start at $8000 with the low
; word 0, which is that value. halfSum's operands are then h * 2^16 or
; INT32_MAX: on them an arithmetic shift and a division rounding toward
; zero agree, so only the shift's sign is observable.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"

        .export lg_lines, lg_group, lg_flood, lg_cmaps, lg_prep, lg_gtabs
        .import far_get, far_put, ld_stop, ld_block
        .include "lgame.inc"

        .assert SEC_CAP = 255, error, "a sector count is a byte"
        .assert <LVC_CMAPA = 0 && <LVC_CMAPB = 0, error, "colormap pages"
        .assert LW_CMB = LW_CMA + $100, error, "LW_CMB follows LW_CMA"

BOX_HI_X = 0                    ; LG_BOX: each pair's high side, then its
BOX_LO_X  = 2                    ;   low side (the one that starts fresh)
BOX_HI_Y   = 4
BOX_LO_Y   = 6

        .segment "LOADW"

; ===========================================================================
; GTABS
; ===========================================================================
lg_gtabs:
        lda GS_GAME
        bne :+
        rts
:       jsr lg_prep             ; LW_LFRONT, LW_LBACK; LG_NS the sectors
        lda #>LW_LFRONT         ; the front sectors, then the back ones:
        ldy #>LVS_LNSECF        ;   LINE_ROOM bytes each
        jsr @pages
        lda #>LW_LBACK
        ldy #>LVS_LNSECB
        jsr @pages
        stz LG_C                ; RJROW: s * numsectors, from 0 in steps of
        stz LG_C+1              ;   numsectors, into LW_CNTLO (2 bytes a
        lda #<LW_CNTLO          ;   sector: 512 bytes)
        sta LG_PF
        lda #>LW_CNTLO
        sta LG_PF+1
        ldx #0
@row:   cpx LG_NS
        beq @put
        lda LG_C
        jsr @byte
        lda LG_C+1
        jsr @byte
        clc
        lda LG_C
        adc LG_NS
        sta LG_C
        bcc :+
        inc LG_C+1
:       inx
        bra @row
@byte:  sta (LG_PF)
        inc LG_PF
        bne :+
        inc LG_PF+1
:       rts
@put:   lda #>LW_CNTLO
        ldy #>LVS_RJROW
        ldx #2
        bra @run
; @pages: LINE_ROOM bytes of W page A to LVS page Y
@pages: ldx #>LINE_ROOM
@run:   sta FA_SRC+1
        sty FA_DST+1
        stx LG_K
        stz FA_SRC
        stz FA_DST
        stz FA_N                ; (256)
        lda #LVS
        sta FA_BANK
:       jsr far_put
        inc FA_SRC+1
        inc FA_DST+1
        dec LG_K
        bne :-
        rts
        .assert <LVS_LNSECF = 0 && <LVS_LNSECB = 0 && <LVS_RJROW = 0,  error, "LVS's tables on pages"
        .assert LW_CNTHI = LW_CNTLO + $100, error, "RJROW's room"
        .assert <LINE_ROOM = 0, error, "LINE_ROOM in pages"

; ===========================================================================
; LINES
; ===========================================================================
lg_lines:
        jsr nlines
        jsr lines_src           ; LG_SB:LG_SA = the compact lines
        lda #<LINE_BASE
        sta LG_DA
        lda #>LINE_BASE
        sta LG_DA+1
        jsr i_zero
@line:  jsr i_end
        beq @done
        jsr src_load            ; the compact line
        lda #<LW_LC
        ldx #>LW_LC
        ldy #LINEC_SIZE
        jsr getw
        jsr make_line
        lda #LVG0               ; its record
        sta FA_BANK
        lda LG_DA
        sta FA_DST
        lda LG_DA+1
        sta FA_DST+1
        lda #<LW_LR
        ldx #>LW_LR
        ldy #LINE_SIZE
        jsr putw
        lda #LINEC_SIZE
        jsr sa_add
        clc
        lda LG_DA
        adc #LINE_SIZE
        sta LG_DA
        bcc :+
        inc LG_DA+1
:       jsr i_inc
        bra @line
@done:  rts

; make_line: LW_LR = the record of the compact line LW_LC
make_line:
        ldx #7                  ; v1, v2
:       lda LW_LC,x
        sta LW_LR,x
        dex
        bpl :-
        ldx #LC_V1X             ; dx = v2.x - v1.x, dy = v2.y - v1.y
        ldy #LN_DX
        jsr delta
        ldx #LC_V1Y
        ldy #LN_DY
        jsr delta
        ldx #3                  ; the sides
:       lda LW_LC + LC_SIDE0,x
        sta LW_LR + LN_SIDE0,x
        dex
        bpl :-
        ldx #LC_V1Y             ; top, bottom
        jsr order
        ldx #3
:       lda LG_A,x
        sta LW_LR + LN_TOP,x
        dex
        bpl :-
        ldx #LC_V1X             ; right, left
        jsr order
        lda LG_A
        sta LW_LR + LN_RIGHT
        lda LG_A+1
        sta LW_LR + LN_RIGHT + 1
        lda LG_A+2
        sta LW_LR + LN_LEFT
        lda LG_A+3
        sta LW_LR + LN_LEFT + 1
        lda LW_LC + LC_TAG
        sta LW_LR + LN_TAG
        lda LW_LC + LC_SPECIAL
        sta LW_LR + LN_SPECIAL
        lda LW_LC + LC_FLAGS
        sta LW_LR + LN_FLAGS
        ldx #1                  ; ST_VERTICAL: dx 0
        lda LW_LR + LN_DX
        ora LW_LR + LN_DX + 1
        beq @slope
        dex                     ; ST_HORIZONTAL: dy 0
        lda LW_LR + LN_DY
        ora LW_LR + LN_DY + 1
        beq @slope
        ldx #2                  ; ST_POSITIVE, or ST_NEGATIVE by the sign
        lda LW_LR + LN_DX + 1   ;   of dy ^ dx
        eor LW_LR + LN_DY + 1
        bpl @slope
        inx
@slope: stx LW_LR + LN_SLOPE
        stz LW_LR + LN_VALID
        stz LW_LR + LN_VALID + 1
        stz LW_LR + LN_RVALID
        stz LW_LR + LN_RVALID + 1
        rts

; delta: the record's word at Y = v2's coordinate - v1's (X: v1's)
delta:  sec
        lda LW_LC + 4,x
        sbc LW_LC,x
        sta LW_LR,y
        lda LW_LC + 5,x
        sbc LW_LC + 1,x
        sta LW_LR + 1,y
        rts

; order: LG_A = the greater of v1 (LW_LC + X) and v2 (+ 4), LG_A + 2
; the other: v1 < v2 (signed, the overflow flipped as upstream's
; bvc/eor #$8000) puts v2 first, else v1 (an equal pair either way)
        .assert LN_BOTTOM = LN_TOP + 2, error, "the box's top, then bottom"
order:  lda LW_LC,x
        cmp LW_LC + 4,x
        lda LW_LC + 1,x
        sbc LW_LC + 5,x
        bvc :+
        eor #$80
:       bmi @lt
        lda LW_LC,x             ; v1, v2
        sta LG_A
        lda LW_LC + 1,x
        sta LG_A+1
        lda LW_LC + 4,x
        sta LG_A+2
        lda LW_LC + 5,x
        sta LG_A+3
        rts
@lt:    lda LW_LC + 4,x         ; v2, v1
        sta LG_A
        lda LW_LC + 5,x
        sta LG_A+1
        lda LW_LC,x
        sta LG_A+2
        lda LW_LC + 1,x
        sta LG_A+3
        rts

; ===========================================================================
; GROUP
; ===========================================================================
lg_group:
        jsr subsectors
        jsr lg_prep
        jsr place
        jmp origins

; subsectors: each subsector's sector, the sector of its first seg with a
; side (LVSEG), from the side's record (LVMAP byte 7)
subsectors:
        lda LW_HDR + LHC_SUBSECTORS
        sta LG_N
        lda LW_HDR + LHC_SUBSECTORS + 1
        sta LG_N+1
        lda #<SUBBASE
        sta LG_DA
        lda #>SUBBASE
        sta LG_DA+1
        jsr i_zero
@sub:   jsr i_end
        bne :+
        rts
:       lda #LVMAP              ; the record: its count and first seg
        sta FA_BANK
        lda LG_DA
        sta FA_SRC
        lda LG_DA+1
        sta FA_SRC+1
        lda #<LW_SUB
        ldx #>LW_SUB
        ldy #SUB_SIZE
        jsr getw
        lda LW_SUB + SUB_COUNT
        sta LG_KN
        lda LW_SUB + SUB_FIRST  ; LG_V = its first seg's side: SEGBASE +
        sta LG_V                ;   24 first + SEG_SIDE
        lda LW_SUB + SUB_FIRST + 1
        sta LG_V+1
        ldx #3
:       asl LG_V
        rol LG_V+1
        dex
        bne :-
        lda LG_V                ; 8 first
        sta LG_C
        lda LG_V+1
        sta LG_C+1
        asl LG_V                ; 16 first
        rol LG_V+1
        clc
        lda LG_V
        adc LG_C
        tax
        lda LG_V+1
        adc LG_C+1
        sta LG_V+1
        clc
        txa
        adc #<(SEGBASE + SEG_SIDE)
        sta LG_V
        lda LG_V+1
        adc #>(SEGBASE + SEG_SIDE)
        sta LG_V+1
@seg:   lda LG_KN
        bne :+
        lda #LS_NOSIDE          ; no seg with a side
        jmp ld_stop
:       lda #LVSEG
        sta FA_BANK
        lda LG_V
        sta FA_SRC
        lda LG_V+1
        sta FA_SRC+1
        jsr get_be2
        lda LW_BE
        and LW_BE+1
        cmp #$FF
        bne @side
        clc
        lda LG_V
        adc #SEG_SIZE
        sta LG_V
        bcc :+
        inc LG_V+1
:       dec LG_KN
        bra @seg
@side:  jsr sidesec_be          ; its sector, into the subsector's record
        sta LW_BE+6
        lda #LVMAP
        sta FA_BANK
        clc
        lda LG_DA
        adc #SUB_SECTOR
        sta FA_DST
        lda LG_DA+1
        adc #0
        sta FA_DST+1
        lda #<(LW_BE + 6)
        ldx #>(LW_BE + 6)
        ldy #1
        jsr putw
        clc
        lda LG_DA
        adc #SUB_SIZE
        sta LG_DA
        bcc :+
        inc LG_DA+1
:       jsr i_inc
        jmp @sub

; sidesec_be: A = the sector of side LW_BE (a word); sidesec: of side
; LG_C (its LVMAP record's byte 7). Changes X, Y, LG_C, FA_*.
sidesec_be:
        lda LW_BE
        sta LG_C
        lda LW_BE+1
        sta LG_C+1
sidesec:
        asl LG_C
        rol LG_C+1
        asl LG_C
        rol LG_C+1
        asl LG_C
        rol LG_C+1
        clc
        lda LG_C
        adc #<(SIDEBASE + SIDE_SECTOR)
        sta FA_SRC
        lda LG_C+1
        adc #>(SIDEBASE + SIDE_SECTOR)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #<(LW_BE + 7)
        ldx #>(LW_BE + 7)
        ldy #1
        jsr getw
        lda LW_BE + 7
        rts

; ---------------------------------------------------------------------------
; lg_prep: LG_N the lines, LG_NS the sectors; each line's front sector in
; LW_LFRONT, its back sector in LW_LBACK (the front when it has no back
; side); each sector's line count (CNT: the lines whose front it is, and
; those whose back it is when the back differs) and first entry (FST,
; the counts summed in sector order)
; ---------------------------------------------------------------------------
lg_prep:
        jsr nlines
        lda LW_HDR + LHC_SECTORS + 1
        jne many
        lda LW_HDR + LHC_SECTORS        ; (at most 255: SEC_CAP)
        sta LG_NS
        ldx #0
:       stz LW_CNTLO,x
        stz LW_CNTHI,x
        inx
        bne :-
        jsr pf_pb
        jsr lines_src
        jsr i_zero
@line:  jsr i_end
        beq @firsts
        jsr src_load            ; the line's sides
        lda #LC_SIDE0
        jsr src_add
        lda #<LW_BE
        ldx #>LW_BE
        ldy #4
        jsr getw
        jsr sidesec_be
        cmp LG_NS
        bcs many
        sta (LG_PF)
        sta LG_F
        lda LW_BE+2             ; side 1: $FFFF none
        and LW_BE+3
        cmp #$FF
        beq @one
        lda LW_BE+2
        sta LG_C
        lda LW_BE+3
        sta LG_C+1
        jsr sidesec
        cmp LG_NS
        bcs many
        bra @back
@one:   lda LG_F
@back:  sta (LG_PB)
        sta LG_B
        ldx LG_F                ; the counts
        inc LW_CNTLO,x
        bne :+
        inc LW_CNTHI,x
:       lda LG_B
        cmp LG_F
        beq :+
        tax
        inc LW_CNTLO,x
        bne :+
        inc LW_CNTHI,x
:       jsr pf_pb_inc
        lda #LINEC_SIZE
        jsr sa_add
        jsr i_inc
        bra @line
@firsts:
        stz LG_C                ; FST: the counts summed
        stz LG_C+1
        ldx #0
:       lda LG_C
        sta LW_FSTLO,x
        clc
        adc LW_CNTLO,x
        sta LG_C
        lda LG_C+1
        sta LW_FSTHI,x
        adc LW_CNTHI,x
        sta LG_C+1
        inx
        bne :-
        rts
many:   lda #LS_SECTORS
        jmp ld_stop

; place: the line tables into LVG1 at the header's LTAB: line i at its
; front sector's next entry, then at its back sector's when that differs
place:
        ldx #0                  ; POS = FST
:       lda LW_FSTLO,x
        sta LW_POSLO,x
        lda LW_FSTHI,x
        sta LW_POSHI,x
        inx
        bne :-
        jsr pf_pb
        jsr i_zero
@line:  jsr i_end
        bne :+
        rts
:       lda (LG_PF)
        sta LG_F
        jsr put_entry
        lda (LG_PB)
        cmp LG_F
        beq :+
        jsr put_entry
:       jsr pf_pb_inc
        jsr i_inc
        bra @line

; put_entry: line LG_I at sector A's next entry (POS), POS + 1
put_entry:
        tax
        lda LW_POSLO,x          ; LG_C = the entry
        sta LG_C
        lda LW_POSHI,x
        sta LG_C+1
        inc LW_POSLO,x
        bne :+
        inc LW_POSHI,x
:       lda LG_I
        sta LW_BE
        lda LG_I+1
        sta LW_BE+1
        ldy #LHV_LTAB
        jsr entry_at            ; FA_DST = LTAB + 2 LG_C
        lda #LVG1
        sta FA_BANK
        lda #<LW_BE
        ldx #>LW_BE
        ldy #2
        jmp putw

; entry_at: FA_DST = the LVG1 base at LW_HDR + Y, + 2 LG_C
entry_at:
        lda LG_C
        asl a
        sta FA_DST
        lda LG_C+1
        rol a
        sta FA_DST+1
        clc
        lda FA_DST
        adc LW_HDR,y
        sta FA_DST
        lda FA_DST+1
        adc LW_HDR+1,y
        sta FA_DST+1
        rts

; origins: each sector's game record (LVG1 SECG_BASE + 32 s)
origins:
        jsr lines_src           ; LG_SB:LG_SA = the compact lines
        stz LG_S
@sec:   lda LG_S
        cmp LG_NS
        bne :+
        rts
:       lda #3                  ; the box: left and bottom at their
        sta LG_FRESH            ;   start (INT32_MAX), right and top at
        lda #$80                ;   INT32_MIN ($8000, the low word 0)
        stz LG_BOX + BOX_HI_X
        sta LG_BOX + BOX_HI_X + 1
        stz LG_BOX + BOX_HI_Y
        sta LG_BOX + BOX_HI_Y + 1
        ldx LG_S
        lda LW_FSTLO,x
        sta LG_K
        lda LW_FSTHI,x
        sta LG_K+1
        lda LW_CNTLO,x
        sta LG_KN
        lda LW_CNTHI,x
        sta LG_KN+1
@ent:   lda LG_KN               ; each line of its table, in order
        ora LG_KN+1
        beq @rec
        lda LG_K                ; the line: LTAB + 2 K
        sta LG_C
        lda LG_K+1
        sta LG_C+1
        ldy #LHV_LTAB
        jsr entry_at
        lda FA_DST
        sta FA_SRC
        lda FA_DST+1
        sta FA_SRC+1
        lda #LVG1
        sta FA_BANK
        jsr get_be2
        jsr line_at             ; its vertices
        ldy #8
        jsr getw
        ldy #0                  ; v1, then v2
        jsr boxpt
        ldy #4
        jsr boxpt
        inc LG_K
        bne :+
        inc LG_K+1
:       lda LG_KN
        bne :+
        dec LG_KN+1
:       dec LG_KN
        bra @ent
@rec:   ldx #SECG_SIZE - 1      ; the record
:       stz LW_SR,x
        dex
        bpl :-
        lda #$FF
        ldx #1
:       sta LW_SR + SG_TARGET,x
        sta LW_SR + SG_FLOORD,x
        sta LW_SR + SG_CEILD,x
        sta LW_SR + SG_TOUCH,x
        dex
        bpl :-
        ldx LG_S
        lda LW_CNTLO,x
        sta LW_SR + SG_LCOUNT
        lda LW_CNTHI,x
        sta LW_SR + SG_LCOUNT + 1
        lda LW_FSTLO,x
        sta LW_SR + SG_LFIRST
        lda LW_FSTHI,x
        sta LW_SR + SG_LFIRST + 1
        ldx #BOX_HI_X           ; x: half(right) + half(left)
        lda #1
        jsr origin
        ldx #BOX_HI_Y             ; y: half(top) + half(bottom)
        lda #2
        jsr origin
        ldx #LB_SECC            ; special, tag: SECC + 3 s
        jsr ld_block
        lda LG_S
        asl a
        bcc :+
        inc FA_SRC+1
        clc
:       adc LG_S
        bcc :+
        inc FA_SRC+1
:       jsr src_add
        lda #<LW_BE
        ldx #>LW_BE
        ldy #3
        jsr getw
        lda LW_BE
        sta LW_SR + SG_SPECIAL
        sta LW_SR + SG_OLDSPECIAL
        lda LW_BE+1
        sta LW_SR + SG_TAG
        lda LW_BE+2
        sta LW_SR + SG_TAG + 1
        stz FA_DST+1            ; into LVG1: SECG_BASE + 32 s
        lda LG_S
        ldx #5
:       asl a
        rol FA_DST+1
        dex
        bne :-
        clc
        adc #<SECG_BASE
        sta FA_DST
        lda FA_DST+1
        adc #>SECG_BASE
        sta FA_DST+1
        lda #LVG1
        sta FA_BANK
        lda #<LW_SR
        ldx #>LW_SR
        ldy #SECG_SIZE
        jsr putw
        inc LG_S
        jmp @sec

; line_at: FA_BANK:FA_SRC = compact line LW_BE (a word) of the store
; (LG_SB:LG_SA's base + 15 line); A:X = LW_LC for getw
line_at:
        lda LW_BE               ; 16 line - line
        sta LG_C
        lda LW_BE+1
        sta LG_C+1
        ldx #4
:       asl LG_C
        rol LG_C+1
        dex
        bne :-
        sec
        lda LG_C
        sbc LW_BE
        sta LG_C
        lda LG_C+1
        sbc LW_BE+1
        sta LG_C+1
        clc
        lda LG_SA
        adc LG_C
        sta FA_SRC
        lda LG_SA+1
        adc LG_C+1
        sta FA_SRC+1
        lda LG_SB
        sta FA_BANK
        lda #<LW_LC
        ldx #>LW_LC
        rts

; boxpt: M_AddToBox of the vertex at LW_LC + Y (x, then y)
boxpt:  ldx #BOX_HI_X
        lda #1
        jsr boxv
        iny
        iny
        ldx #BOX_HI_Y
        lda #2
; boxv: one coordinate (LW_LC + Y) into the pair at LG_BOX + X (its high
; side, then its low side; A the low side's fresh bit): if v < low, low
; = v (a fresh low side is INT32_MAX: every v is below it), else if v >
; high, high = v (upstream's else-if)
boxv:   sta LG_V
        and LG_FRESH
        bne @setl
        lda LW_LC,y             ; v < low?
        cmp LG_BOX + 2,x
        lda LW_LC + 1,y
        sbc LG_BOX + 3,x
        bvc :+
        eor #$80
:       bmi @setl
        lda LG_BOX,x            ; high < v?
        cmp LW_LC,y
        lda LG_BOX + 1,x
        sbc LW_LC + 1,y
        bvc :+
        eor #$80
:       bpl @done
        lda LW_LC,y
        sta LG_BOX,x
        lda LW_LC + 1,y
        sta LG_BOX + 1,x
@done:  rts
@setl:  lda LW_LC,y
        sta LG_BOX + 2,x
        lda LW_LC + 1,y
        sta LG_BOX + 3,x
        lda LG_V
        eor #$FF
        and LG_FRESH
        sta LG_FRESH
        rts

; origin: the record's words at SOUNDX + X = (high >> 1) + (low >> 1),
; each side of the pair at LG_BOX + X a 32-bit value (its high word, the
; low word 0; the low side INT32_MAX while fresh, A its bit), arithmetic
; shifts, the sum
        .assert SG_SOUNDY = SG_SOUNDX + BOX_HI_Y, error, "the sound origin"
origin: sta LG_V
        stz LG_A                ; LG_A = high >> 1, to the record
        stz LG_A+1
        lda LG_BOX,x
        sta LG_A+2
        lda LG_BOX + 1,x
        jsr asr
        ldy #0
        phx
:       lda LG_A,y
        sta LW_SR + SG_SOUNDX,x
        inx
        iny
        cpy #4
        bne :-
        plx
        lda LG_V                ; LG_A = low >> 1
        and LG_FRESH
        beq @word
        lda #$FF
        sta LG_A
        sta LG_A+1
        sta LG_A+2
        lda #$7F
        bra @shift
@word:  stz LG_A
        stz LG_A+1
        lda LG_BOX + 2,x
        sta LG_A+2
        lda LG_BOX + 3,x
@shift: jsr asr
        clc                     ; the sum
        ldy #0
:       lda LG_A,y
        adc LW_SR + SG_SOUNDX,x
        sta LW_SR + SG_SOUNDX,x
        inx
        iny
        tya
        eor #4
        bne :-
        rts

; asr: LG_A+3 = A, then LG_A (32 bits) shifted right one bit,
; arithmetically
asr:    sta LG_A+3
        cmp #$80
        ror LG_A+3
        ror LG_A+2
        ror LG_A+1
        ror LG_A
        rts

; ===========================================================================
; FLOOD
; ===========================================================================
lg_flood:
        jsr lg_prep
        ldx #0                  ; UP = FST, DN = FST + CNT; a page of 0
:       lda LW_FSTLO,x
        sta LW_POSLO,x
        clc
        adc LW_CNTLO,x
        sta LW_DNLO,x
        lda LW_FSTHI,x
        sta LW_POSHI,x
        adc LW_CNTHI,x
        sta LW_DNHI,x
        stz LW_ZERO,x
        inx
        bne :-
        ldy #LHV_FLENT          ; the entries 0 (the room the lists
        stz LG_C                ;   leave)
        stz LG_C+1
        jsr entry_at
        lda LW_HDR + LHC_FLOOD
        sta LG_C
        lda LW_HDR + LHC_FLOOD + 1
        sta LG_C+1
        lda #LVG1
        sta FA_BANK
@zero:  ldy #0                  ; 256 at a time
        lda LG_C+1
        bne :+
        ldy LG_C                ; the rest
        beq @lines
:       lda #<LW_ZERO
        ldx #>LW_ZERO
        jsr putw
        lda LG_C+1
        beq @lines
        inc FA_DST+1
        dec LG_C+1
        bra @zero
@lines: jsr lines_src           ; the lines, from the last
        lda LG_N
        sta LG_I
        lda LG_N+1
        sta LG_I+1
@line:  lda LG_I
        ora LG_I+1
        jeq @index
        lda LG_I
        bne :+
        dec LG_I+1
:       dec LG_I
        clc                     ; its sectors
        lda #<LW_LFRONT
        adc LG_I
        sta LG_PF
        lda #>LW_LFRONT
        adc LG_I+1
        sta LG_PF+1
        lda (LG_PF)
        sta LG_F
        clc
        lda #<LW_LBACK
        adc LG_I
        sta LG_PB
        lda #>LW_LBACK
        adc LG_I+1
        sta LG_PB+1
        lda (LG_PB)
        sta LG_B
        cmp LG_F
        beq @line               ; one side, or one sector
        lda LG_I                ; its flags
        sta LW_BE
        lda LG_I+1
        sta LW_BE+1
        jsr line_at
        lda #LC_FLAGS
        jsr src_add
        lda #<LW_LC
        ldx #>LW_LC
        ldy #1
        jsr getw
        lda LW_LC
        and #ML_TWOSIDED
        beq @line
        lda LW_LC
        and #ML_SOUNDBLOCK
        bne @block
        lda LG_F                ; the back into the front's free part,
        ldx LG_B                ;   then the front into the back's
        jsr up_entry
        lda LG_B
        ldx LG_F
        jsr up_entry
        bra @line
@block: lda LG_F                ; the same into the block parts, down
        ldx LG_B                ;   from their ends
        jsr down_entry
        lda LG_B
        ldx LG_F
        jsr down_entry
        jmp @line
@index: stz LG_S                ; each sector's index: its first entry,
@idx:   ldx LG_S                ;   UP, DN, its end
        cpx LG_NS
        bne :+
        rts
:       lda LW_FSTLO,x
        sta LW_BE
        clc
        adc LW_CNTLO,x
        sta LW_BE+6
        lda LW_FSTHI,x
        sta LW_BE+1
        adc LW_CNTHI,x
        sta LW_BE+7
        lda LW_POSLO,x
        sta LW_BE+2
        lda LW_POSHI,x
        sta LW_BE+3
        lda LW_DNLO,x
        sta LW_BE+4
        lda LW_DNHI,x
        sta LW_BE+5
        txa                     ; FLIDX + 8 s
        stz LG_C+1
        asl a
        rol LG_C+1
        asl a
        rol LG_C+1
        sta LG_C
        ldy #LHV_FLIDX
        jsr entry_at
        lda #LVG1
        sta FA_BANK
        lda #<LW_BE
        ldx #>LW_BE
        ldy #FLIDX_SIZE
        jsr putw
        inc LG_S
        bra @idx

; up_entry: sector X into sector A's list at its UP, UP + 1
up_entry:
        stx LW_BE
        tax
        lda LW_POSLO,x
        sta LG_E
        lda LW_POSHI,x
        sta LG_E+1
        inc LW_POSLO,x
        bne flent
        inc LW_POSHI,x
        bra flent
; down_entry: DN - 1, then sector X into sector A's list at its DN
down_entry:
        stx LW_BE
        tax
        lda LW_DNLO,x
        bne :+
        dec LW_DNHI,x
:       dec LW_DNLO,x
        lda LW_DNLO,x
        sta LG_E
        lda LW_DNHI,x
        sta LG_E+1
; flent: the byte LW_BE at the header's FLENT + LG_E
flent:  ldy #LHV_FLENT
        clc
        lda LW_HDR,y
        adc LG_E
        sta FA_DST
        lda LW_HDR+1,y
        adc LG_E+1
        sta FA_DST+1
        lda #LVG1
        sta FA_BANK
        lda #<LW_BE
        ldx #>LW_BE
        ldy #1
        jmp putw

; ===========================================================================
; CMAPS
; ===========================================================================
lg_cmaps:
        lda #LVC                ; GSVIEWn's tables A and B
        sta FA_BANK
        lda #<(LVC_GSVIEW + GSVIEW_A)
        sta FA_SRC
        lda #>(LVC_GSVIEW + GSVIEW_A)
        sta FA_SRC+1
        lda #<LW_CMA
        ldx #>LW_CMA
        ldy #0
        jsr getw
        inc FA_SRC+1
        inc FA_DST+1            ; (LW_CMB follows LW_CMA)
        jsr far_get
        stz LG_I                ; each page of COLORMAP
@page:  lda LG_I
        cmp #CMAP_PAGES
        bne :+
        rts
:       lda #GTAB
        sta FA_BANK
        lda #<GT_COLORMAP
        sta FA_SRC
        lda #>GT_COLORMAP
        clc
        adc LG_I
        sta FA_SRC+1
        lda #<LW_CMI
        ldx #>LW_CMI
        ldy #0
        jsr getw
        ldy #0                  ; through A
:       ldx LW_CMI,y
        lda LW_CMA,x
        sta LW_CMO,y
        iny
        bne :-
        lda #>LVC_CMAPA
        jsr @out
        ldy #0                  ; through B
:       ldx LW_CMI,y
        lda LW_CMB,x
        sta LW_CMO,y
        iny
        bne :-
        lda #>LVC_CMAPB
        jsr @out
        inc LG_I
        bra @page
@out:   clc                     ; LW_CMO to LVC at page A + the page
        adc LG_I
        sta FA_DST+1
        lda #<LVC_CMAPA
        sta FA_DST
        lda #LVC
        sta FA_BANK
        lda #<LW_CMO
        ldx #>LW_CMO
        ldy #0
        jmp putw

; ===========================================================================
; helpers
; ===========================================================================
; nlines: LG_N = the header's lines, at most LVG0's
nlines: lda LW_HDR + LHC_LINES
        sta LG_N
        lda LW_HDR + LHC_LINES + 1
        sta LG_N+1
        lda #<LINE_CAP
        cmp LG_N
        lda #>LINE_CAP
        sbc LG_N+1
        bcs :+
        lda #LS_LINES
        jmp ld_stop
:       rts

; getw: Y bytes (0: 256) of FA_BANK:FA_SRC into W at A:X (A the low
; byte); putw: Y bytes of W at A:X to FA_BANK:FA_DST
getw:   sta FA_DST
        stx FA_DST+1
        sty FA_N
        jmp far_get
putw:   sta FA_SRC
        stx FA_SRC+1
        sty FA_N
        jmp far_put

; get_be2: the word at FA_BANK:FA_SRC into LW_BE
get_be2:
        lda #<LW_BE
        ldx #>LW_BE
        ldy #2
        bra getw

; lines_src: LG_SB:LG_SA = the store's compact lines
lines_src:
        ldx #LB_LINES
        jsr ld_block
        lda FA_BANK
        sta LG_SB
        lda FA_SRC
        sta LG_SA
        lda FA_SRC+1
        sta LG_SA+1
        rts

; src_load: FA_BANK:FA_SRC = LG_SB:LG_SA; src_add: FA_SRC + A; sa_add:
; LG_SA + A
src_load:
        lda LG_SB
        sta FA_BANK
        lda LG_SA
        sta FA_SRC
        lda LG_SA+1
        sta FA_SRC+1
        rts
src_add:
        clc
        adc FA_SRC
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       rts
sa_add: clc
        adc LG_SA
        sta LG_SA
        bcc :+
        inc LG_SA+1
:       rts

; i_zero: LG_I = 0; i_end: Z when LG_I = LG_N; i_inc: LG_I + 1
i_zero: stz LG_I
        stz LG_I+1
        rts
i_end:  lda LG_I
        cmp LG_N
        bne :+
        lda LG_I+1
        cmp LG_N+1
:       rts
i_inc:  inc LG_I
        bne :+
        inc LG_I+1
:       rts

; pf_pb: LG_PF, LG_PB at the lines' first front and back; pf_pb_inc:
; both + 1
pf_pb:  lda #<LW_LFRONT
        sta LG_PF
        lda #>LW_LFRONT
        sta LG_PF+1
        lda #<LW_LBACK
        sta LG_PB
        lda #>LW_LBACK
        sta LG_PB+1
        rts
pf_pb_inc:
        inc LG_PF
        bne :+
        inc LG_PF+1
:       inc LG_PB
        bne :+
        inc LG_PB+1
:       rts
