; game/lines/lines.s: part lines of milestone 10 (docs/GAME.md 2.4, wave
; 2): the special lines a thing uses or crosses, the dispatch of their
; handlers through LSTAB, the exits, the switch textures and the buttons.
; A GPL-2 derivative of upstream's p_switch65.s (P_UseSpecialLine,
; P_CrossSpecialLine, findSpecial with its tables usetab and crosstab,
; lnExit, P_ChangeSwitchTexture with startButton; the helpers swLine,
; swSide and isPlayer are done in place).
;
; The native interfaces (docs/game-parts/lines.md, "Interfaces"):
;
;   P_UseSpecialLine    GA_0-1 = the thing (a mobj handle), GA_2-3 = the
;                       line (upstream's _Dp[0-3], _Dp[4-7]) -> A = 1 or 0
;                       (upstream's C)
;   P_CrossSpecialLine  GA_0-1 = the line, GA_2-3 = the thing (upstream's
;                       _Dp[0-3], _Dp[4-7]), A = the side the thing was on
;                       (upstream's C: 0 front, 1 back); no result
;   findSpecial         A:X = the line, Y = 0: usetab, else crosstab ->
;                       C clear: no tag where one is needed, or the special
;                       is not in the table; C set: A = the entry's
;                       argument, X = its handler (its LSTAB number), Y =
;                       its mode, GT_0 = its index in spectab (upstream's
;                       SW_I / 8)
;   P_ChangeSwitchTexture
;                       A:X = the line, Y = useAgain (0: the line loses its
;                       special; else a button changes the switch back)
;   LSTAB's handlers    GA_0-1 = the line, GA_2-3 = the entry's argument
;                       (README: the table's convention), and from this
;                       part GA_4-5 = the thing (upstream's SW_THING, which
;                       lnVDoor and lnTele pass on as _Dp[4-7]) and, from
;                       P_CrossSpecialLine only, GA_6 = the side (upstream's
;                       SW_CSIDE, lnTele's C) -> A = 1 started, 0 not
;   lnExit (LSTAB 9)    the above, GA_2 = 0 the exit, 1 the secret exit
;
; Upstream's 16-bit fields are the native bytes: a line's special, tag
; and flags (LN_SPECIAL, LN_TAG, LN_FLAGS: every value of E1 below 256),
; a mobj's type, a side's textures (below 256: COLDIR, r_data65.s), the
; handlers' results (0 or 1). The switch's texture is found through
; GTAB's SW_IDX (2 i + 1 for the first switchlist[i] of a texture, 0
; none: P_InitSwitchList's table), which gives the first i of the scan
; of p_switch65.s:240-261 for each of the three textures; the least i
; wins, top before middle before bottom at one i, as the scan's order.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export P_UseSpecialLine, P_CrossSpecialLine, findSpecial
        .export P_ChangeSwitchTexture, lnExit
        .export spectab, usetab, usetab_end, crosstab, crosstab_end
        .import ln_get, ln_dirty, mo_get, sd_get, sd_put, g_get
        .import S_StartSound, S_StartSound2, I_Error
        .import dc_call, LSTAB, fc_call, fc_unbuilt

        .assert UC_TOP = 0 && UC_MIDDLE = 1 && UC_BOTTOM = 2, error, "places"
        .assert BT_SIZE = 9 && U_MAXBUTTONS = 4, error, "the buttons"
        .assert SIDE_SIZE = 8, error, "the side record"

; GTAB's switchlist and SW_IDX (GT_SWLIST, GT_SWIDX) and LSTAB's entry
; numbers by handler (LSTAB_lnDoor ...) are ggame.inc's (requests 1 and 2,
; wave 2 as integrated)
; ---------------------------------------------------------------------------

BUTTONTIME = UC_TICRATE         ; p_switch65.s:21

; a spectab entry: special, handler, argument, mode
SPF_SPECIAL = 0
SPF_HANDLER = 1
SPF_ARG     = 2
SPF_MODE    = 3
.macro SPEC special, handler, arg, mode
        .byte special, handler, arg, mode
.endmacro

; ---------------------------------------------------------------------------
; The scratch block (SB_LINES: what a routine keeps across a call)
; ---------------------------------------------------------------------------
SB_LN   = SB_LINES              ; P_UseSpecialLine, P_CrossSpecialLine:
SB_TH   = SB_LINES + 2          ;   the line, the thing (2 each),
SB_CS   = SB_LINES + 4          ;   the side (cross),
SB_MD   = SB_LINES + 5          ;   the entry's mode
SB_FL   = SB_LINES + 6          ; findSpecial: the line (2),
SB_FT   = SB_LINES + 8          ;   the table
SB_CL   = SB_LINES + 9          ; P_ChangeSwitchTexture: the line (2),
SB_AG   = SB_LINES + 11         ;   useAgain,
SB_SD   = SB_LINES + 12         ;   the front side (2),
SB_K    = SB_LINES + 14         ;   the place looked at (0-2),
SB_PS   = SB_LINES + 15         ;   the switch's place (UC_TOP ..),
SB_BV   = SB_LINES + 16         ;   its SW_IDX value (2 i + 1),
SB_V    = SB_LINES + 17         ;   a texture's SW_IDX value,
SB_TX   = SB_LINES + 18         ;   the switch's texture,
SB_NW   = SB_LINES + 19         ;   the other texture (2),
SB_OR   = SB_LINES + 21         ;   the front sector (the sound origin)
SB_EL   = SB_LINES + 22         ; lnExit: the line (2),
SB_EA   = SB_LINES + 24         ;   0 the exit, 1 the secret exit
SB_END  = SB_LINES + 25
        .assert SB_END <= SB_LINES + SB_LINES_SIZE, error, "scratch"

; IS_PLAYER: Z set when the mobj handle at `at` is the player's mobj
; (upstream's isPlayer of p_switch65.s:351, done in place)
.macro IS_PLAYER at
        lda G_PLAYER + PL_MO
        cmp at
        bne :+
        lda G_PLAYER + PL_MO + 1
        cmp at + 1
:
.endmacro

; SW_LINE: A:X = the line at `at` (upstream's swLine: _Dp = SW_LINE)
.macro SW_LINE at
        lda at
        ldx at + 1
.endmacro

; HANDLER: the handler's arguments (GA_0-1 the line, GA_2-3 the argument
; in A, GA_4-5 the thing), then its call through LSTAB (its number in X)
; with its result in A
.macro HANDLER
        sta GA_2
        stz GA_3
        lda SB_LN
        sta GA_0
        lda SB_LN + 1
        sta GA_1
        lda SB_TH
        sta GA_4
        lda SB_TH + 1
        sta GA_5
        txa
        DCALL LSTAB
.endmacro

; ===========================================================================
; P_UseSpecialLine: a thing uses (pushes) a line. Monsters open only the
; manual doors that are not secret (1, 32-34). A special of usetab runs its
; handler: mode 0 gives the handler's result; modes 1 and 2 give 1, and a
; handler that started changes the switch (1 once, 2 a button). Any other
; special: 1.
; ===========================================================================
        ROUTINE P_UseSpecialLine
        lda GA_0
        sta SB_TH
        lda GA_1
        sta SB_TH + 1
        lda GA_2
        sta SB_LN
        lda GA_3
        sta SB_LN + 1
        IS_PLAYER SB_TH
        beq @find
        SW_LINE SB_LN           ; a monster: not a secret line,
        jsr ln_get
        ldy #LN_FLAGS
        lda (GC_LP),y
        and #UC_ML_SECRET
        bne @no
        ldy #LN_SPECIAL         ;   and only the manual doors 1, 32-34
        lda (GC_LP),y
        cmp #1
        beq @find
        cmp #32
        bcc @no
        cmp #35
        bcc @find
@no:    lda #0
        rts
@find:  SW_LINE SB_LN
        ldy #0                  ; usetab
        FCALL findSpecial
        bcs @run
        lda #1                  ; the other specials: nothing
        rts
@run:   sty SB_MD
        HANDLER
        ldy SB_MD               ; 0: the handler's result
        beq @ret
        cmp #0                  ; 1, 2: true; a handler that started
        beq @one                ;   changes the switch (1 once, 2 again)
        dey
        SW_LINE SB_LN
        FCALL P_ChangeSwitchTexture
@one:   lda #1
@ret:   rts

; ===========================================================================
; P_CrossSpecialLine: a thing crosses a line with a special (crosstab).
; Monsters trigger only the teleporter 97 and the lift 88, and the
; rockets, imp and baron shots nothing; a walk-once line (mode 1) loses
; its special when its handler starts.
; ===========================================================================
        ROUTINE P_CrossSpecialLine
        sta SB_CS
        lda GA_0
        sta SB_LN
        lda GA_1
        sta SB_LN + 1
        lda GA_2
        sta SB_TH
        lda GA_3
        sta SB_TH + 1
        IS_PLAYER SB_TH
        beq @find
        lda SB_TH               ; not the player: not these missiles
        ldx SB_TH + 1
        jsr mo_get
        ldy #MO_SIZE + MA_TYPE
        lda (GC_MP),y
        cmp #UC_MT_ROCKET
        beq @no
        cmp #UC_MT_TROOPSHOT
        beq @no
        cmp #UC_MT_BRUISERSHOT
        beq @no
        SW_LINE SB_LN           ; and only 97 and 88
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        cmp #97
        beq @find
        cmp #88
        bne @no
@find:  SW_LINE SB_LN
        ldy #1                  ; crosstab
        FCALL findSpecial
        bcc @no
        sty SB_MD
        pha
        lda SB_CS               ; the side (lnTele's)
        sta GA_6
        pla
        HANDLER
        ldy SB_MD               ; walk once (1) and started: no more
        beq @no                 ;   special
        cmp #0
        beq @no
        SW_LINE SB_LN
        jsr ln_get
        lda #0
        ldy #LN_SPECIAL
        sta (GC_LP),y
        jsr ln_dirty
@no:    rts

; ===========================================================================
; findSpecial: P_CheckTag of the line (a zero tag only for some specials),
; then its special in usetab (Y = 0) or crosstab: C set when it is there,
; with A = its argument, X = its handler, Y = its mode, GT_0 = its index
; in spectab
; ===========================================================================
        ROUTINE findSpecial
        sta SB_FL
        stx SB_FL + 1
        sty SB_FT
        FCALL P_CheckTag        ; A:X = the line -> A = 1 or 0
        cmp #0
        beq @none
        SW_LINE SB_FL
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        sta GT_1
        ldx #usetab - spectab
        ldy #usetab_end - spectab
        lda SB_FT
        beq :+
        ldx #crosstab - spectab
        ldy #crosstab_end - spectab
:       sty GT_2
@find:  lda spectab + SPF_SPECIAL,x
        cmp GT_1
        beq @found
        inx
        inx
        inx
        inx
        cpx GT_2
        bcc @find
@none:  clc
        rts
@found: txa
        lsr a
        lsr a
        sta GT_0
        ldy spectab + SPF_MODE,x
        lda spectab + SPF_HANDLER,x
        pha
        lda spectab + SPF_ARG,x
        plx
        sec
        rts

; spectab: special, handler (LSTAB's number), argument, mode; in
; findSpecial's group (its only reader). usetab (P_UseSpecialLine): mode
; 0 the handler's result, 1 the switch changes, 2 a button. crosstab
; (P_CrossSpecialLine): mode 1 walk once, 0 walk again.
spectab:
usetab: SPEC 1, LSTAB_lnVDoor, 0, 0                    ; the manual doors
        SPEC 26, LSTAB_lnVDoor, 0, 0
        SPEC 27, LSTAB_lnVDoor, 0, 0
        SPEC 28, LSTAB_lnVDoor, 0, 0
        SPEC 31, LSTAB_lnVDoor, 0, 0
        SPEC 32, LSTAB_lnVDoor, 0, 0
        SPEC 33, LSTAB_lnVDoor, 0, 0
        SPEC 34, LSTAB_lnVDoor, 0, 0
        SPEC 7, LSTAB_lnStairs, 0, 1                   ; switches
        SPEC 9, LSTAB_lnDonut, 0, 1
        SPEC 11, LSTAB_lnExit, 0, 0
        SPEC 18, LSTAB_lnFloor, UC_RAISEFLOORTONEAREST, 1
        SPEC 20, LSTAB_lnPlat, UC_RAISETONEARESTANDCHANGE, 1
        SPEC 23, LSTAB_lnFloor, UC_LOWERFLOORTOLOWEST, 1
        SPEC 51, LSTAB_lnExit, 1, 0
        SPEC 103, LSTAB_lnDoor, UC_DOPEN, 1
        SPEC 62, LSTAB_lnPlat, UC_DOWNWAITUPSTAY, 2    ; buttons
        SPEC 63, LSTAB_lnDoor, UC_NORMAL, 2
        SPEC 70, LSTAB_lnFloor, UC_TURBOLOWER, 2
usetab_end:
crosstab:
        SPEC 2, LSTAB_lnDoor, UC_DOPEN, 1              ; walk once
        SPEC 5, LSTAB_lnFloor, UC_RAISEFLOOR, 1
        SPEC 8, LSTAB_lnStairs, 0, 1
        SPEC 16, LSTAB_lnDoor, UC_CLOSE30THENOPEN, 1
        SPEC 22, LSTAB_lnPlat, UC_RAISETONEARESTANDCHANGE, 1
        SPEC 35, LSTAB_lnLight, 35, 1
        SPEC 36, LSTAB_lnFloor, UC_TURBOLOWER, 1
        SPEC 76, LSTAB_lnDoor, UC_CLOSE30THENOPEN, 0   ; walk again
        SPEC 82, LSTAB_lnFloor, UC_LOWERFLOORTOLOWEST, 0
        SPEC 86, LSTAB_lnDoor, UC_DOPEN, 0
        SPEC 88, LSTAB_lnPlat, UC_DOWNWAITUPSTAY, 0
        SPEC 90, LSTAB_lnDoor, UC_NORMAL, 0
        SPEC 91, LSTAB_lnFloor, UC_RAISEFLOOR, 0
        SPEC 97, LSTAB_lnTele, 0, 0
        SPEC 98, LSTAB_lnFloor, UC_TURBOLOWER, 0
crosstab_end:
        .assert crosstab_end - spectab < 256, error, "spectab's offsets"

; ===========================================================================
; lnExit (LSTAB): the exit (GA_2 = 0) or the secret exit (1). A dead
; player cannot leave (the sound noway, 0); else the switch changes, the
; level is completed, 1.
; ===========================================================================
        ROUTINE lnExit
        lda GA_0
        sta SB_EL
        lda GA_1
        sta SB_EL + 1
        lda GA_2
        sta SB_EA
        IS_PLAYER GA_4
        bne @go
        lda G_PLAYER + PL_HEALTH + 1    ; health 0 or below: no
        bmi @dead
        ora G_PLAYER + PL_HEALTH
        bne @go
@dead:  ldx GA_4                ; S_StartSound(thing, sfx_noway)
        ldy GA_5
        lda #UC_SFX_NOWAY
        jsr S_StartSound
        lda #0
        rts
@go:    SW_LINE SB_EL
        ldy #0
        FCALL P_ChangeSwitchTexture
        lda SB_EA
        bne @secret
        FCALL G_ExitLevel
        lda #1
        rts
@secret:
        FCALL G_SecretExitLevel
        lda #1
        rts

; ===========================================================================
; P_ChangeSwitchTexture: the switch texture of the line's front side (the
; first of its top, middle and bottom in switchlist's order) changes to
; the other one, with the switch sound at the front sector; a line not
; used again loses its special; one used again gets a button (startButton)
; that changes it back after BUTTONTIME tics.
; ===========================================================================
        ROUTINE P_ChangeSwitchTexture
        sta SB_CL
        stx SB_CL + 1
        sty SB_AG
        jsr ln_get
        ldy #LN_SIDE0           ; the front side
        lda (GC_LP),y
        sta SB_SD
        iny
        lda (GC_LP),y
        sta SB_SD + 1
        lda SB_AG               ; not again: line->special = 0
        bne :+
        ldy #LN_SPECIAL
        sta (GC_LP),y
        jsr ln_dirty
:       lda SB_SD
        ldx SB_SD + 1
        jsr sd_get
        stz SB_BV               ; the switch: the least SW_IDX of the three
        ldx #0
@pos:   stx SB_K
        ldy sw_ofs,x            ; the texture at this place
        lda SD_BUF,y
        clc                     ; SW_IDX[it]
        adc #<GT_SWIDX
        sta FA_SRC
        lda #>GT_SWIDX
        adc #0
        sta FA_SRC + 1
        lda #GTAB
        sta FA_BANK
        lda #<SB_V
        ldx #>SB_V
        ldy #1
        jsr g_get
        lda SB_V
        beq @next               ; not a switch
        ldx SB_BV
        beq @take
        cmp SB_BV               ; an earlier i only (top first at one i)
        bcs @next
@take:  sta SB_BV
        lda SB_K
        sta SB_PS
@next:  ldx SB_K
        inx
        cpx #3
        bcc @pos
        lda SB_BV
        bne @found
        rts                     ; none
@found: ldx SB_PS
        ldy sw_ofs,x
        lda SD_BUF,y            ; switchlist[i]: the texture itself
        sta SB_TX
        lda SB_BV               ; the other one, switchlist[i ^ 1]:
        dec a                   ;   GTAB switchlist + (2 i ^ 2)
        eor #2
        clc
        adc #<GT_SWLIST
        sta FA_SRC
        lda #>GT_SWLIST
        adc #0
        sta FA_SRC + 1
        lda #GTAB
        sta FA_BANK
        lda #<SB_NW
        ldx #>SB_NW
        ldy #2
        jsr g_get
        ldx SB_PS
        ldy sw_ofs,x
        lda SB_NW
        sta SD_BUF,y
        jsr sd_put
        lda SD_BUF + SIDE_SECTOR        ; the sound at the front sector
        sta SB_OR
        tax
        ldy #$80
        lda #UC_SFX_SWTCHN
        jsr S_StartSound2
        lda SB_AG
        bne @button
        rts

; startButton: a button for the line if it has none, in the first free
; slot: P_StartButton(line, place, texture, BUTTONTIME)
@button:
        ldx #0
@b1:    lda G_BUTTONS + BT_BTIMER,x
        ora G_BUTTONS + BT_BTIMER + 1,x
        beq @n1
        lda G_BUTTONS + BT_LINE,x
        cmp SB_CL
        bne @n1
        lda G_BUTTONS + BT_LINE + 1,x
        cmp SB_CL + 1
        bne @n1
        rts                     ; pressed already
@n1:    txa
        clc
        adc #BT_SIZE
        tax
        cpx #U_MAXBUTTONS * BT_SIZE
        bcc @b1
        ldx #0
@b2:    lda G_BUTTONS + BT_BTIMER,x
        ora G_BUTTONS + BT_BTIMER + 1,x
        beq @put
        txa
        clc
        adc #BT_SIZE
        tax
        cpx #U_MAXBUTTONS * BT_SIZE
        bcc @b2
        jmp I_Error             ; "no button slots left!" (a stop)
@put:   lda SB_CL
        sta G_BUTTONS + BT_LINE,x
        lda SB_CL + 1
        sta G_BUTTONS + BT_LINE + 1,x
        lda SB_PS
        sta G_BUTTONS + BT_WHERE,x
        stz G_BUTTONS + BT_WHERE + 1,x
        lda SB_TX
        sta G_BUTTONS + BT_BTEXTURE,x
        stz G_BUTTONS + BT_BTEXTURE + 1,x
        lda #<BUTTONTIME
        sta G_BUTTONS + BT_BTIMER,x
        lda #>BUTTONTIME
        sta G_BUTTONS + BT_BTIMER + 1,x
        lda SB_OR
        sta G_BUTTONS + BT_SOUNDORG,x
        rts

; the places' textures in the side's record, in upstream's order
sw_ofs: .byte SIDE_TOP, SIDE_MID, SIDE_BOTTOM
