; gspec.s: the game core's specials at the start of a level (milestone 9,
; stage C; docs/LEVELS.md 2.5). A GPL-2 derivative of upstream's
; p_spec65.s (P_SpawnSpecials, addScroller, getNextSector) and
; p_lights65.s (P_SpawnLightFlash, P_SpawnStrobeFlash,
; P_SpawnGlowingLight, P_FindMinSurroundingLight).
;
;   gx_specials  the load program's SPECIALS step (only in nl_setup:
;                GS_GAME): each sector in order by its special: 1 a light
;                flash, 2 and 3 strobes (fast, slow), 8 a glow, 9 a secret
;                (totalsecret), 12 and 13 synchronised strobes (slow,
;                fast); each light spawner sets the sector's special to 0;
;                then no buttons; then a scroller for each line of special
;                48, in line order. Each special is a thinker at the list's
;                end; its P_Random calls in this order
;
; A sector's lines are its line table (LVG1: LFIRST, LCOUNT); a line's
; other sector is upstream's getNextSector by lg_prep's front and back
; sectors (the front twice for a one-sided line); the light levels are the
; sectors' render records (LVMAP), a byte each (0-255: upstream's signed
; compares of them are unsigned byte compares).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gx_specials
        .import g_get, g_put, g_put2, g_random, gt_add, gt_spectake

        .segment "LOADW"

; ---------------------------------------------------------------------------
; gx_specials: the SPECIALS step
; ---------------------------------------------------------------------------
gx_specials:
        lda GS_GAME
        bne :+
        rts
:       stz GS_I                ; each sector
@sec:   lda GS_I
        cmp LVCOUNT
        lda #0
        sbc LVCOUNT+1
        jcs @buttons
        jsr sg_addr             ; its game record
        lda #<LW_SG
        ldx #>LW_SG
        ldy #SECG_SIZE
        jsr g_get
        lda LW_SG + SG_SPECIAL
        cmp #1
        bne :+
        jsr flash
        bra @next
:       cmp #2
        bne :+
        lda #U_FASTDARK
        ldx #0
        bra @strobe
:       cmp #3
        bne :+
        lda #U_SLOWDARK
        ldx #0
        bra @strobe
:       cmp #8
        bne :+
        jsr glow
        bra @next
:       cmp #9
        bne :+
        inc G_TOTALSECRET
        bne @next
        inc G_TOTALSECRET+1
        bne @next
        inc G_TOTALSECRET+2
        bne @next
        inc G_TOTALSECRET+3
        bra @next
:       cmp #12
        bne :+
        lda #U_SLOWDARK
        ldx #1
        bra @strobe
:       cmp #13
        bne @next
        lda #U_FASTDARK
        ldx #1
@strobe:
        jsr strobe
@next:  inc GS_I
        bra @sec
@buttons:
        ldx #4 * BT_SIZE - 1    ; no buttons: line none, the words 0, the
:       stz G_BUTTONS,x         ;   sound origin none
        dex
        bpl :-
        ldx #0
:       lda #$FF
        sta G_BUTTONS + BT_LINE,x
        sta G_BUTTONS + BT_LINE + 1,x
        sta G_BUTTONS + BT_SOUNDORG,x
        txa
        clc
        adc #BT_SIZE
        tax
        cpx #4 * BT_SIZE
        bcc :-
        .assert U_MAXBUTTONS = 4, error, "four buttons"
        stz GS_I                ; the scrollers: each line of special 48
        stz GS_I+1
@line:  lda GS_I
        cmp LVCOUNT2
        lda GS_I+1
        sbc LVCOUNT2+1
        bcs @done
        lda GS_I                ; its record: LINE_BASE + 32 n
        sta FA_SRC
        lda GS_I+1
        ldx #5
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<LINE_BASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>LINE_BASE
        sta FA_SRC+1
        lda #LVG0
        sta FA_BANK
        lda #<LW_LINEB
        ldx #>LW_LINEB
        ldy #LN_SPECIAL + 1
        jsr g_get
        lda LW_LINEB + LN_SPECIAL
        cmp #48
        bne :+
        jsr scroller
:       inc GS_I
        bne @line
        inc GS_I+1
        bra @line
@done:  rts

; sg_addr: FA_BANK:FA_SRC = sector GS_I's game record (LVG1), GC_T its
; address
sg_addr:
        lda GS_I
        stz GC_T+1
        ldx #5
:       asl a
        rol GC_T+1
        dex
        bne :-
        clc
        adc #<SECG_BASE
        sta GC_T
        sta FA_SRC
        lda GC_T+1
        adc #>SECG_BASE
        sta GC_T+1
        sta FA_SRC+1
        lda #LVG1
        sta FA_BANK
        rts

; no_special: sector GS_I's special 0 (LVG1)
no_special:
        jsr sg_addr
        clc
        lda GC_T
        adc #SG_SPECIAL
        sta FA_DST
        lda GC_T+1
        adc #0
        sta FA_DST+1
        stz GC_V
        lda #<GC_V
        ldx #>GC_V
        ldy #1
        jmp g_put

; light: GC_S = sector A's light level (a word)
light:  stz FA_SRC+1
        ldx #4
:       asl a
        rol FA_SRC+1
        dex
        bne :-
        clc
        adc #<(SECBASE + SEC_LIGHT)
        sta FA_SRC
        lda FA_SRC+1
        adc #>(SECBASE + SEC_LIGHT)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        stz GC_S+1
        lda #<GC_S
        ldx #>GC_S
        ldy #1
        jmp g_get

; newlight: a special of kind X for sector GS_I, at the thinker list's
; end: LW_SPEC its record (function A, sector, links), GC_H its handle,
; GS_ST its address; GS_K = its sector's light level
newlight:
        pha
        jsr gt_spectake         ; GC_H, GC_P (ZONE0)
        lda GC_P                ; (gt_add and minlight change GC_P)
        sta GS_ST
        lda GC_P+1
        sta GS_ST+1
        jsr gt_add              ; GC_PREV
        ldx #SPEC_SIZE - 1
:       stz LW_SPEC,x
        dex
        bpl :-
        pla
        sta LW_SPEC + SP_FUNC
        lda GS_I
        sta LW_SPEC + SP_SECTOR
        lda GC_PREV
        sta LW_SPEC + SP_THPREV
        lda GC_PREV+1
        sta LW_SPEC + SP_THPREV + 1
        lda #$FF
        sta LW_SPEC + SP_THNEXT
        sta LW_SPEC + SP_THNEXT + 1
        lda GS_I
        jsr light
        lda GC_S
        sta GS_K
        stz GS_K+1
        rts

; putspec: LW_SPEC into its record GS_ST (ZONE0)
putspec:
        lda #ZONE0
        sta FA_BANK
        lda GS_ST
        sta FA_DST
        lda GS_ST+1
        sta FA_DST+1
        lda #<LW_SPEC
        ldx #>LW_SPEC
        ldy #SPEC_SIZE
        jmp g_put

; flash: P_SpawnLightFlash(sector GS_I)
flash:  jsr no_special          ; (takeSector)
        lda #FN_FLASH
        ldx #SPK_LIGHTFLASH
        jsr newlight
        lda GS_K                ; maxlight = the light level
        sta LW_SPEC + SPLI_MAXLIGHT
        jsr minlight            ; minlight
        lda GS_L
        sta LW_SPEC + SPLI_MINLIGHT
        jsr g_random            ; count = (P_Random() & 64) + 1
        and #64
        inc a
        sta LW_SPEC + SPLI_COUNT
        jmp putspec

; strobe: P_SpawnStrobeFlash(sector GS_I, darktime A, in sync X)
strobe: pha
        phx
        lda #FN_STROBE
        ldx #SPK_STROBE
        jsr newlight
        plx
        stx GS_CNT
        pla
        sta LW_SPEC + SPST_DARKTIME
        lda GS_K                ; maxlight = the light level
        sta LW_SPEC + SPST_MAXLIGHT
        jsr minlight            ; minlight, 0 when it is maxlight
        lda GS_L
        cmp GS_K
        bne :+
        lda #0
:       sta LW_SPEC + SPST_MINLIGHT
        jsr no_special
        lda #1                  ; in sync: count 1, else (P_Random() & 7)
        ldx GS_CNT              ;   + 1
        bne :+
        jsr g_random
        and #7
        inc a
:       sta LW_SPEC + SPST_COUNT
        jmp putspec

; glow: P_SpawnGlowingLight(sector GS_I)
glow:   lda #FN_GLOW
        ldx #SPK_GLOW
        jsr newlight
        jsr minlight            ; minlight
        lda GS_L
        sta LW_SPEC + SPGL_MINLIGHT
        lda GS_K                ; maxlight
        sta LW_SPEC + SPGL_MAXLIGHT
        lda #$FF                ; direction -1
        sta LW_SPEC + SPGL_DIRECTION
        jsr no_special
        jmp putspec

; scroller: addScroller(sidenum[0] of the line LW_LINEB): a T_Scroll
; thinker whose texture offset is that side's
scroller:
        ldx #SPK_SCROLL
        jsr gt_spectake
        lda GC_P
        sta GS_ST
        lda GC_P+1
        sta GS_ST+1
        jsr gt_add
        ldx #SPEC_SIZE - 1
:       stz LW_SPEC,x
        dex
        bpl :-
        lda #FN_SCROLL
        sta LW_SPEC + SP_FUNC
        lda GC_PREV
        sta LW_SPEC + SP_THPREV
        lda GC_PREV+1
        sta LW_SPEC + SP_THPREV + 1
        lda #$FF
        sta LW_SPEC + SP_THNEXT
        sta LW_SPEC + SP_THNEXT + 1
        sta LW_SPEC + SP_SECTOR
        lda LW_LINEB + LN_SIDE0
        sta LW_SPEC + SPSC_SIDE
        lda LW_LINEB + LN_SIDE0 + 1
        sta LW_SPEC + SPSC_SIDE + 1
        jmp putspec

; minlight: GS_L = P_FindMinSurroundingLight(sector GS_I, GS_K): the lowest
; light level of the other sectors of its lines, at most GS_K
minlight:
        lda GS_K
        sta GS_L
        jsr sg_addr             ; its count and first entry
        lda #<LW_SG
        ldx #>LW_SG
        ldy #SG_LFIRST + 2
        jsr g_get
        lda LW_SG + SG_LCOUNT
        sta GC_N
        lda LW_SG + SG_LCOUNT + 1
        sta GC_N+1
        lda LW_SG + SG_LFIRST   ; GC_W = the table's entry: LTAB + 2 first
        asl a
        sta GC_W
        lda LW_SG + SG_LFIRST + 1
        rol a
        sta GC_W+1
        clc
        lda GC_W
        adc LW_HDR + LHV_LTAB
        sta GC_W
        lda GC_W+1
        adc LW_HDR + LHV_LTAB + 1
        sta GC_W+1
@entry: lda GC_N
        ora GC_N+1
        beq @done
        lda #LVG1               ; the line
        sta FA_BANK
        lda GC_W
        sta FA_SRC
        lda GC_W+1
        sta FA_SRC+1
        lda #<GC_X
        ldx #>GC_X
        ldy #2
        jsr g_get
        clc                     ; getNextSector: its front when not the
        lda GC_X                ;   sector, else its back when not the
        adc #<LW_LFRONT         ;   sector (one-sided: the front again),
        sta GC_P                ;   else none
        lda GC_X+1
        adc #>LW_LFRONT
        sta GC_P+1
        lda (GC_P)
        cmp GS_I
        bne @other
        clc
        lda GC_P+1
        adc #>LINE_ROOM
        sta GC_P+1
        lda (GC_P)
        cmp GS_I
        beq @skip
@other: jsr light               ; its light below the least: the least
        lda GC_S
        cmp GS_L
        bcs @skip
        sta GS_L
@skip:  clc
        lda GC_W
        adc #2
        sta GC_W
        bcc :+
        inc GC_W+1
:       lda GC_N
        bne :+
        dec GC_N+1
:       dec GC_N
        bra @entry
@done:  rts
        .assert <LINE_ROOM = 0, error, "LINE_ROOM in pages"
