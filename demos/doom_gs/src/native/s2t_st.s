; s2t_st.s: the status bar's tic side (docs/SCREENS.md 1.5.1, 4.7; part
; s2stbar, docs/m11-parts/s2stbar.md): a module for milestone 10's tic
; image, with GAME.md 4.4's calling conventions, called by its hooks
; (request R4). Written from upstream's src/iigs/st_stuff65.s (ST_Init's
; state, ST_Start with ST_initData and ST_createWidgets, ST_Ticker but
; M_Random: readyNum, the key boxes, updateFace, painOffset, muchPain,
; ouch, turnHead, st_oldhealth), with upstream's 16-bit arithmetic and
; its quirks (ST_createWidgets' pointer has no NOAMMO check; a ready
; weapon past weaponinfo's 9 reads the release's next bytes, kept in
; st_wammo for 9 and 10).
;
;   st_ticker   ST_Ticker: A = M_Random's value (flow's st_tick makes the
;               call). The ready number's source (P_FPS, the fps cheat's,
;               read from P2DW's state block in S2STATE), the key boxes,
;               the face, st_oldhealth.
;   st_start    ST_Start: ST_REFRESHED 0 (the next frame redraws the
;               bar); after the first, I_SetPalette(0) (newpal 0 in
;               S2STATE's PALST, request S2PAL-9); the face 0, st_palette
;               -1 (P2DW's state), st_oldhealth -1, the old weapons, the
;               key boxes -1, the ready number's source, the widgets' old
;               values (0, -1 for the icons) in P2DW's state.
;   st_init     ST_Init's state, at boot: the card's status bar block 0
;               but st_lastattackdown and st_oldhealthPO -1.
;
; State: the card's ST_* (s2.inc's S2T block, S2T_BASE of the build);
; ST_READY and ST_RUNNING (request S2STBAR-1). It reads the player at
; G_PLAYER (mo and attacker as mobj handles). turnHead asks the positions
; of the player's mobj and of the attacker of the callback s2t_pos (A, X
; a handle: x, y, angle at GT_POS, 4 bytes each; milestone 10's, with
; mo_get; request R4, S2STBAR-4) and calls pta3 (R_PointToAngle3) and
; sdiv16 (_Div16) of the math. What it keeps across the callback is in
; its scratch block st_sb (32 bytes; milestone 10's SB_ of the module).
; No zero page of its own: FA_* for the far layer, the math's M_*, GT_POS.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "s2.inc"
        .include "s2stbar.inc"

        .export st_ticker, st_start, st_init
        .import s2t_pos, st_sb, pta3, sdiv16, far_get, far_put

PLR     = G_PLAYER
TICRATE = 35
ST_DEADFACE = 41
ST_GODFACE = 40
ST_TURNOFFSET = 3
ST_OUCHOFFSET = 5
ST_EVILGRINOFFSET = 6
ST_RAMPAGEOFFSET = 7
ST_MUCHPAIN = 20
ST_STRAIGHTFACECOUNT = 18
ST_TURNCOUNT = TICRATE
ST_EVILGRINCOUNT = 2 * TICRATE
ST_RAMPAGEDELAY = 2 * TICRATE
ANG45_HI = $2000
NUMWEAPONS = 9
P2DW_BLOCK = P2DW_STATE + $0300 ; P2DW's own 256 B (s2layout: PALST first)
; the scratch block
SB_MX   = st_sb                 ; the player's mobj: x, y, angle
SB_MY   = st_sb + 4
SB_MA   = st_sb + 8
SB_I    = st_sb + 12            ; turnHead's i
SB_DIFF = st_sb + 13            ; its diffang (4)
SB_T    = st_sb + 17            ; (2)
SB_BUF  = st_sb + 8             ; st_start's 22 bytes (+8: 30 of 32)

        .segment "S2TCODE"

; ---------------------------------------------------------------------------
; st_ticker
; ---------------------------------------------------------------------------
st_ticker:
        sta ST_RANDOM
        lda #<(SS_P2DW + P_FPS - P2DW_BLOCK)   ; readyNum: the fps cheat,
        ldx #>(SS_P2DW + P_FPS - P2DW_BLOCK)   ;   else weaponinfo's ammo,
        jsr getbyte                            ;   LARGEAMMO for none
        lda #$FF
        bcs @ready
        ldx PLR + PO_READYW
        lda st_wammo,x
        cmp #AM_NOAMMO
        bne @ready
        lda #$FE
@ready: sta ST_READY
        ldy #0                  ; keyboxes[i] = cards[i] ? i : -1
@kb:    tya
        asl a
        tax
        lda PLR + PO_CARDS,x
        ora PLR + PO_CARDS+1,x
        beq :+
        tya
        bra :++
:       lda #$FF
:       sta ST_KEYBOXES,y
        iny
        cpy #3
        bcc @kb
        jsr updateface
        lda PLR + PO_HEALTH     ; st_oldhealth
        sta ST_OLDHEALTH
        lda PLR + PO_HEALTH+1
        sta ST_OLDHEALTH+1
        rts

; getbyte: C = the byte of S2STATE at A (low), X (high) is not 0
getbyte:
        sta FA_SRC
        stx FA_SRC+1
        lda #<SB_T
        sta FA_DST
        lda #>SB_T
        sta FA_DST+1
        lda #1
        sta FA_N
        lda #S2STATE
        sta FA_BANK
        jsr far_get
        lda SB_T
        cmp #1
        rts

; ---------------------------------------------------------------------------
; updateFace: dead > evil grin > attacked > damage > rampage > god >
; straight ahead
; ---------------------------------------------------------------------------
updateface:
        lda ST_PRIORITY         ; the dead face
        cmp #10
        bcs @grin
        lda PLR + PO_HEALTH
        ora PLR + PO_HEALTH+1
        bne @grin
        ldx #9
        lda #ST_DEADFACE
        jsr fixface
@grin:  lda ST_PRIORITY         ; a new weapon with a bonus: the evil grin
        cmp #9
        bcs @att
        lda PLR + PO_BONUS
        ora PLR + PO_BONUS+1
        beq @att
        stz SB_T                ; (the weapons that changed)
        ldy #NUMWEAPONS - 1
@w:     tya
        asl a
        tax
        lda PLR + PO_OWNED,x
        cmp ST_OLDWEAPONS,y
        bne :+
        lda PLR + PO_OWNED+1,x
        beq @wn
:       lda PLR + PO_OWNED,x
        sta ST_OLDWEAPONS,y
        inc SB_T
@wn:    dey
        bpl @w
        lda SB_T
        beq @att
        lda #8
        sta ST_PRIORITY
        ldx #ST_EVILGRINCOUNT
        ldy #ST_EVILGRINOFFSET
        jsr face
@att:   lda ST_PRIORITY         ; attacked by someone else
        cmp #8
        bcs @dmg
        jsr damaged
        beq @dmg
        lda PLR + PO_ATTACKER
        and PLR + PO_ATTACKER+1
        cmp #$FF                ; (NO_HANDLE: none)
        beq @dmg
        lda PLR + PO_ATTACKER
        cmp PLR + PO_MO
        bne :+
        lda PLR + PO_ATTACKER+1
        cmp PLR + PO_MO+1
        beq @dmg
:       lda #7
        sta ST_PRIORITY
        jsr muchpain
        bpl :+
        jsr ouch
        bra @dmg
:       jsr turnhead
@dmg:   lda ST_PRIORITY         ; damage: ouch, or the rampage face
        cmp #7
        bcs @ramp
        jsr damaged
        beq @ramp
        jsr muchpain
        bpl :+
        lda #7
        sta ST_PRIORITY
        jsr ouch
        bra @ramp
:       lda #6
        sta ST_PRIORITY
        ldx #ST_TURNCOUNT
        ldy #ST_RAMPAGEOFFSET
        jsr face
@ramp:  lda ST_PRIORITY         ; firing for a while: the rampage face
        cmp #6
        bcs @god
        lda PLR + PO_ATTACKDOWN
        ora PLR + PO_ATTACKDOWN+1
        beq @up
        lda ST_LASTATTACK
        inc a
        bne :+
        lda #ST_RAMPAGEDELAY    ; (-1: the delay starts)
        sta ST_LASTATTACK
        bra @god
:       dec ST_LASTATTACK
        bne @god
        lda #5
        sta ST_PRIORITY
        ldx #1
        ldy #ST_RAMPAGEOFFSET
        jsr face
        lda #1
        bra :+
@up:    lda #$FF
:       sta ST_LASTATTACK
@god:   lda ST_PRIORITY         ; god mode, invulnerability
        cmp #5
        bcs @time
        lda PLR + PO_CHEATS
        and #CF_GODMODE
        ora PLR + PO_POWERS
        ora PLR + PO_POWERS+1
        beq @time
        ldx #4
        lda #ST_GODFACE
        jsr fixface
@time:  lda ST_FACECOUNT        ; timed out: straight ahead, looking
        ora ST_FACECOUNT+1      ;   left or right
        bne @dec
        lda ST_RANDOM           ; randomnumber % 3
:       cmp #3
        bcc :+
        sbc #3
        bra :-
:       tay
        ldx #ST_STRAIGHTFACECOUNT
        jsr face
        stz ST_PRIORITY
@dec:   lda ST_FACECOUNT
        bne :+
        dec ST_FACECOUNT+1
:       dec ST_FACECOUNT
        rts

; damaged: Z clear when damagecount is not 0
damaged:
        lda PLR + PO_DAMAGE
        ora PLR + PO_DAMAGE+1
        rts

; fixface: X = the priority, A = the face, for 1 tic
fixface:
        stx ST_PRIORITY
        sta ST_FACEINDEX
        ldx #1
        bra count
; ouch: the ouch face for ST_TURNCOUNT tics
ouch:   ldx #ST_TURNCOUNT
        ldy #ST_OUCHOFFSET
; face: X tics of the face painoffset + Y
face:   phy
        jsr painoffset
        sta SB_T
        pla
        clc
        adc SB_T
        sta ST_FACEINDEX
count:  stx ST_FACECOUNT
        stz ST_FACECOUNT+1
        rts

; muchpain: N set when (20 - st_oldhealth) + health < 0, the add's
; overflow corrected (upstream's: st_oldhealth - health > ST_MUCHPAIN)
muchpain:
        sec
        lda #ST_MUCHPAIN
        sbc ST_OLDHEALTH
        tax
        lda #0
        sbc ST_OLDHEALTH+1
        tay
        clc
        txa
        adc PLR + PO_HEALTH
        tya
        adc PLR + PO_HEALTH+1
        bvc :+
        eor #$80
:       rts

; painoffset: A = ST_FACESTRIDE * (((100 - health) * 5) / 101), health at
; most 100 (the N of health - 101, as upstream's bmi), computed when it
; changes (st_oldhealthPO, st_lastcalc); X kept
painoffset:
        phx
        lda PLR + PO_HEALTH
        ldy PLR + PO_HEALTH+1
        cmp #101
        tax
        tya
        sbc #0
        bmi :+
        ldx #100
        ldy #0
:       cpx ST_OLDHEALTHPO
        bne @calc
        cpy ST_OLDHEALTHPO+1
        beq @done
@calc:  stx ST_OLDHEALTHPO
        sty ST_OLDHEALTHPO+1
        sec                     ; (100 - h) * 5 in M_A
        lda #100
        sbc ST_OLDHEALTHPO
        sta M_B
        lda #0
        sbc ST_OLDHEALTHPO+1
        sta M_B+1
        ldx #1
:       lda M_B,x
        sta M_A,x
        dex
        bpl :-
        asl M_A
        rol M_A+1
        asl M_A
        rol M_A+1
        clc
        lda M_A
        adc M_B
        sta M_A
        lda M_A+1
        adc M_B+1
        sta M_A+1
        lda #101                ; / 101, signed (_Div16)
        sta M_B
        stz M_B+1
        jsr sdiv16
        lda M_R                 ; * 8
        asl a
        asl a
        asl a
        sta ST_LASTCALC
@done:  plx
        lda ST_LASTCALC
        rts

; turnhead: the face turns to the attacker: head-on within 45 degrees,
; else right or left
turnhead:
        lda PLR + PO_MO         ; the player's mobj: x, y, angle
        ldx PLR + PO_MO+1
        jsr s2t_pos
        ldx #11
:       lda GT_POS,x
        sta SB_MX,x
        dex
        bpl :-
        lda PLR + PO_ATTACKER   ; the attacker's: dx, dy into M_A, M_B
        ldx PLR + PO_ATTACKER+1
        jsr s2t_pos
        ldx #0
@xy:    ldy #4
        sec
:       lda GT_POS,x
        sbc SB_MX,x
        sta M_A,x
        inx
        dey
        bne :-
        cpx #8
        bne @xy
        jsr pta3                ; badguyangle in M_R
        ldx #0                  ; diffang = angle - badguyangle, or its
        ldy #4                  ;   negation when angle < badguyangle
        sec
:       lda SB_MA,x
        sbc M_R,x
        sta SB_DIFF,x
        inx
        dey
        bne :-
        tya                     ; (A = 0)
        rol a
        sta SB_I                ; 1: angle >= badguyangle
        bne :++
        ldx #0
        ldy #4
        sec
:       lda #0                  ; (the negation)
        sbc SB_DIFF,x
        sta SB_DIFF,x
        inx
        dey
        bne :-
:       lda #0                  ; c = diffang <= ANG180; i = c when
        cmp SB_DIFF             ;   angle >= badguyangle, else !c
        lda #0
        sbc SB_DIFF+1
        lda #0
        sbc SB_DIFF+2
        lda #$80
        sbc SB_DIFF+3
        lda #0
        rol a
        eor SB_I
        eor #1
        sta SB_I
        ldy #ST_RAMPAGEOFFSET   ; diffang < ANG45: head-on
        lda SB_DIFF+3
        cmp #>ANG45_HI
        bcc :+
        ldy #ST_TURNOFFSET      ; right, else left
        lda SB_I
        bne :+
        iny
:       ldx #ST_TURNCOUNT
        jmp face

; ---------------------------------------------------------------------------
; st_start
; ---------------------------------------------------------------------------
st_start:
        stz ST_REFRESHED
        lda ST_RUNNING          ; ST_Stop: I_SetPalette(0)
        beq :+
        stz SB_BUF
        lda #<(SS_PALST + PS_NEWPAL)
        ldx #>(SS_PALST + PS_NEWPAL)
        ldy #1
        jsr putbuf
        stz ST_RUNNING
:       stz ST_FACEINDEX        ; ST_initData
        lda #$FF
        sta ST_OLDHEALTH
        sta ST_OLDHEALTH+1
        sta ST_KEYBOXES
        sta ST_KEYBOXES+1
        sta ST_KEYBOXES+2
        ldy #NUMWEAPONS - 1     ; oldweaponsowned = weaponowned
:       tya
        asl a
        tax
        lda PLR + PO_OWNED,x
        sta ST_OLDWEAPONS,y
        dey
        bpl :-
        ldx PLR + PO_READYW     ; ST_createWidgets: the ready number's
        lda st_wammo,x          ;   source, without readyNum's NOAMMO
        sta ST_READY
        ldx #21                 ; the widgets' old values: the 11 numbers
:       stz SB_BUF,x            ;   0, then the 10 icons -1 and
        dex                     ;   st_palette -1 (P_OLDARMS ..
        bpl :-                  ;   P_STPALETTE: 21 bytes)
        lda #<(SS_P2DW + P_OLDREADY - P2DW_BLOCK)
        ldx #>(SS_P2DW + P_OLDREADY - P2DW_BLOCK)
        ldy #22
        jsr putbuf
        ldx #20
        lda #$FF
:       sta SB_BUF,x
        dex
        bpl :-
        lda #<(SS_P2DW + P_OLDARMS - P2DW_BLOCK)
        ldx #>(SS_P2DW + P_OLDARMS - P2DW_BLOCK)
        ldy #P_STPALETTE + 1 - P_OLDARMS
        jsr putbuf
        lda #1
        sta ST_RUNNING
        rts

; putbuf: Y bytes of SB_BUF into S2STATE at A (low), X (high)
putbuf:
        sta FA_DST
        stx FA_DST+1
        sty FA_N
        lda #<SB_BUF
        sta FA_SRC
        lda #>SB_BUF
        sta FA_SRC+1
        lda #S2STATE
        sta FA_BANK
        jmp far_put

; ---------------------------------------------------------------------------
; st_init: ST_Init's state (the boot's; upstream's bss is 0)
; ---------------------------------------------------------------------------
st_init:
        ldx #ST_REFRESHED - ST_FACEINDEX
:       stz ST_FACEINDEX,x
        dex
        bpl :-
        lda #$FD                ; W_READY NULL (s2state.READY_NONE)
        sta ST_READY
        stz ST_RUNNING
        lda #$FF
        sta ST_LASTATTACK
        sta ST_OLDHEALTHPO
        sta ST_OLDHEALTHPO+1
        rts

        .segment "S2TRODATA"

; weaponinfo's ammo types (the release's p_pspr65.s table), then the two
; words after its 9 entries, which readyNum reads for a ready weapon 9 or
; 10 (wp_nochange)
st_wammo:
        .byte ST_WAMMO0, ST_WAMMO1, ST_WAMMO2, ST_WAMMO3, ST_WAMMO4
        .byte ST_WAMMO5, ST_WAMMO6, ST_WAMMO7, ST_WAMMO8, ST_WAMMO9
        .byte ST_WAMMO10
