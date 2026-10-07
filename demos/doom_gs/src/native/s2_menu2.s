; s2_menu2.s: the settings pages' values, the key setup page, the load and
; save pages' slots and the benchmark's result in MENUW (docs/SCREENS.md,
; the menu; part s2menu2). GPL-2: rewritten from upstream's
; src/iigs/m_menu65.s (Doom8088: Apple IIgs Edition, GPL-2): onOff's and
; thermo's drawing, drawControls, keyName, text, drawSlots (drawLoad,
; drawSave) [R m_menu65.s:1260-1450], the values of uiSettings past ON and
; OFF with uiViewIndex for the full view only and the thermometers'
; positions (uiGammaPos, uiMousePos) [R :2741-2758, :2927-2958],
; uiBenchmark's two rows [R :3012-3058].
;
; Part s2menu1's s2_menu.s calls these hooks inside m_page, with the band
; set (S2_BAND, S2_Y0, S2_Y1); they draw with s2menu1's m_dpatch,
; m_wline, m_wstr and m_align, which skip what misses the band:
;
;   m2_page     A = the page (currentMenu / 2): 2 the load page, 4 the key
;               setup, 5 the save page (M_Drawer's routine before the
;               items: drawLoad, drawControls, drawSave)
;   m2_value    a settings row's value past ON/OFF: S2M_KIND the kind
;               (uiKinds: 20 the view, 28 gamma, 32 the mouse speed, 36
;               the effects' volume, 40 the music's: the release's
;               MUSIC_MENU is 1, its display page has the row), S2M_UIY
;               the row's y
;   m2_bench    the benchmark's result (uiBenchmark): its title, the VIEW
;               and FPS rows; the CPU, CACHE and ROM rows (ZipGS and
;               TransWarp, dropped: docs/SCREENS.md) are
;               black, and on them, each when not empty, the play build's
;               phase rows M_BROWS (docs/PLAY.md, the benchmark: "TIC t  3D
;               t", ...), as labels at x 36
;
; The key setup reads the //e key names (part plinput's plk_names, 8 bytes a
; name, 0-terminated) and the bindings through pl_action (I_ActionKeys: the
; first two //e codes of a Doom key in upstream's order of the ranges
; $30-$3F, $20-$2F, $00-$1F, $40-$7F). The view is the full view only:
; VIEW's value is "FULL". The benchmark's FPS text is M_BFPS in MENUW's
; state block (s2layout's MENUW_NATIVE; the second half's benchmark writes
; it). (The busy sign is FINW's: part s2fin draws it by columns.)
;
; Zero page: s2menu1's S2M_* that m_page and settings do not keep across
; the hooks (S2M_I, S2M_N, S2M_K, S2M_A, S2M_B); pl_action uses PLZ
; ($5A-$69, the drawers' temporaries between two draws). The hooks keep
; S2M_MENU, S2M_ITEM, S2M_LEFT, S2M_UIY, S2M_KIND and S2M_SEQ, which
; their callers loop on. A, X, Y changed.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "s2.inc"
        .include "s2menu1.inc"
        .include "plkeys.inc"
        .include "s2menu2.inc"

        .export m2_page, m2_value, m2_bench
        .import m_dpatch, m_wline, m_wstr, m_align
        .import pl_action, far_get, s2_mul160, s2_mark

M2_I    = S2M_I                 ; the row (drawSlots' MM_I, drawControls'
                                ;   CT_I)
M2_N    = S2M_N                 ; thermo's middles left (TH_N)
M2_K    = S2M_K                 ; the second key (CT_K); a setting's byte
M2_Y    = S2M_A                 ; the row's y (MM_Y, CT_Y): a word
M2_V    = S2M_B                 ; the dot's x (TH_V): a word

CONTROLS = 10                   ; the key setup's actions [R :61]
KIND_VIEW = 20                  ; uiKinds [R :3104-3106]
KIND_SPEED = 32
KIND_SFX = 36
KIND_MUSIC = 40
SET_MSPEED = 3                  ; SS_SETTINGS' mouse speed (s2layout's
                                ;   field map)
TH_X0   = 204                   ; uiSettings' thermometer [R :2952-2958]
TH_STEPS = 16
SLOT_Y0 = 34                    ; drawSlots [R :1395-1450]
SLOT_DY = 13
SLOT_X  = 104
SLOT_TX = 112
SLOT_N  = 8
SLOT_LEN = 8                    ; _g_savegamestrings' 8 bytes a slot
BENCH_Y = 60                    ; uiBenchmark [R :3015-3058]
BENCH_DY = 16
BENCH_X = 36
VALUE_EDGE = 1                  ; m_align: the right edge 284
; X2 (s2check's x2: whole rows black natively): the CPU, CACHE and ROM
; rows, each a glyph's rows y .. y + 7 (the font's top offsets are 0 or
; below, its heights at most 8) for y = 92, 108, 124
X2_Y0   = BENCH_Y + 2 * BENCH_DY
X2_ROWS = 8
X2_Y1   = BENCH_Y + 4 * BENCH_DY + X2_ROWS
M2_BROW = 32                    ; M_BROWS: a row's bytes (s2layout's)
        .assert M2_BROW / 2 = BENCH_DY, error, "M_BROWS' rows"

        .segment "S2CODE"

; ---------------------------------------------------------------------------
; m2_page: drawLoad, drawSave, drawControls [R :1301-1450].
; ---------------------------------------------------------------------------
m2_page:
        cmp #4
        bne slots
        jmp controls

; slots: drawSlots: the title patch centred at y 8, then the 8 slots at y
; 34 + 13 i: the border (M_LSLEFT at x 104, 12 M_LSCNTR from x 112 on,
; M_LSRGHT at 208) and the slot's string at (112, y - 7)
slots:
        ldy #P_M_LOADG
        ldx #M2_LOADG_X
        cmp #2
        beq :+
        ldy #P_M_SAVEG
        ldx #M2_SAVEG_X
:       stx S2M_X
        stz S2M_X+1
        lda #8
        sta S2M_Y
        stz S2M_Y+1
        tya
        jsr m_dpatch
        stz M2_I
        lda #SLOT_Y0
        sta M2_Y
@slot:  lda M2_Y
        sta S2M_Y
        lda #SLOT_X
        sta S2M_X
        lda #P_M_LSLEFT
        jsr m_dpatch
        lda #SLOT_TX
        sta S2M_X
@mid:   lda #P_M_LSCNTR
        jsr m_dpatch
        lda S2M_X
        clc
        adc #8
        sta S2M_X
        cmp #SLOT_TX + 12 * 8
        bcc @mid
        lda #P_M_LSRGHT
        jsr m_dpatch
        lda M2_I                ; the string: _g_savegamestrings + 8 i
        asl a
        asl a
        asl a
        clc
        adc #<M_SAVESTR
        sta S2M_P
        lda #>M_SAVESTR
        adc #0
        sta S2M_P+1
        lda #SLOT_TX
        sta S2M_X
        lda M2_Y
        sec
        sbc #7
        sta S2M_Y
        stz S2M_TP
        jsr m_wline
        lda M2_Y
        clc
        adc #SLOT_DY
        sta M2_Y
        inc M2_I
        lda M2_I
        cmp #SLOT_N
        bcc @slot
        rts

; controls: drawControls: the title centred at y 4; each action's name at
; (48, 24 + 16 i), and at x 176 its first two keys, "---" for none, or the
; request for a key on the row bindRow waits for; the last row DEFAULT
; KEYS alone
controls:
        lda #4
        sta S2M_Y
        stz S2M_Y+1
        lda #<tx_controls
        ldx #>tx_controls
        ldy #0
        jsr m_align
        stz M2_I
@row:   lda M2_I                ; y = 24 + 16 i
        asl a
        asl a
        asl a
        asl a
        clc
        adc #24
        sta M2_Y
        sta S2M_Y
        lda #48
        sta S2M_X
        stz S2M_X+1
        ldx M2_I
        lda ctl_lo,x
        ldy ctl_hi,x
        jsr text
        lda M2_I
        cmp #CONTROLS
        bcs @next
        lda #176
        sta S2M_X
        lda M2_I
        cmp M_BINDROW
        bne @keys
        lda #<tx_press
        ldy #>tx_press
        jsr text
        bra @next
@keys:  ldx M2_I                ; I_ActionKeys
        lda ctl_keys,x
        jsr pl_action
        stx M2_K
        cmp #PLK_NOKEY
        bne :+
        lda #<tx_none
        ldy #>tx_none
        jsr text
        bra @next
:       jsr keyname
        lda M2_K
        bmi @next
        lda #<tx_comma
        ldy #>tx_comma
        jsr text
        lda M2_K
        jsr keyname
@next:  inc M2_I
        lda M2_I
        cmp #CONTROLS + 1
        bcc @row
        rts

; keyname: the name of the //e code A at S2M_X, S2M_Y (writeLine: to its
; 0); text: the string A (low), Y (high) the same way. S2M_X moves on.
keyname:
        stz S2M_P+1
        asl a
        rol S2M_P+1
        asl a
        rol S2M_P+1
        asl a
        rol S2M_P+1
        clc
        adc #<m2_names
        sta S2M_P
        lda S2M_P+1
        adc #>m2_names
        sta S2M_P+1
        stz S2M_TP
        jmp m_wline
text:
        sta S2M_P
        sty S2M_P+1
        stz S2M_TP
        jmp m_wline

; ---------------------------------------------------------------------------
; m2_value: uiSettings' value past ON/OFF [R :2930-2958]: the view's label
; at the right edge 284 (uiViewIndex: the full view only), or the
; thermometer of 16 steps at (204, y - 3) with the dot at the value's step
; ---------------------------------------------------------------------------
m2_value:
        lda S2M_UIY
        sta S2M_Y
        lda S2M_UIY+1
        sta S2M_Y+1
        lda S2M_KIND
        cmp #KIND_VIEW
        bne @thermo
        lda #<tx_full
        ldx #>tx_full
        ldy #VALUE_EDGE
        jmp m_align
@thermo:
        cmp #KIND_MUSIC         ; snd_MusicVolume, 0-15 (the release's
        beq @music              ;   MUSIC_MENU 1)
        cmp #KIND_SFX
        beq @sfx
        cmp #KIND_SPEED
        beq @speed
        ldx GAMMA               ; _g_gamma: uiGammaPos
        lda gamma_pos,x
        bra thermo
@sfx:   lda SND_SFXVOL          ; snd_SfxVolume, 0-15
        bra thermo
@music: ldx #SET_MUSVOL
        jsr setting
        bra thermo
@speed: ldx #SET_MSPEED         ; iigs_mousespeed: uiMousePos
        jsr setting
        tax
        lda mouse_pos,x
        ; (on to thermo)

; thermo: M_DrawThermo at (204, S2M_Y - 3) with the dot at step A: the
; left end at 204, 16 middles from 212, the right end at 276, the dot at
; 212 + 4 A
thermo:
        asl a
        asl a
        clc
        adc #<(TH_X0 + 8)
        sta M2_V
        lda #>(TH_X0 + 8)
        adc #0
        sta M2_V+1
        lda S2M_Y
        sec
        sbc #3
        sta S2M_Y
        bcs :+
        dec S2M_Y+1
:       lda #TH_X0
        sta S2M_X
        stz S2M_X+1
        lda #P_M_THERML
        jsr m_dpatch
        lda #TH_X0 + 8
        sta S2M_X
        lda #TH_STEPS
        sta M2_N
@mid:   lda #P_M_THERMM
        jsr m_dpatch
        jsr x4
        dec M2_N
        bne @mid
        lda #P_M_THERMR
        jsr m_dpatch
        lda M2_V
        sta S2M_X
        lda M2_V+1
        sta S2M_X+1
        lda #P_M_THERMO
        jmp m_dpatch

; setting: A = SS_SETTINGS' byte X (the settings that persist, in bank
; S2STATE)
setting:
        lda #S2STATE
        sta FA_BANK
        txa
        clc
        adc #<SS_SETTINGS
        sta FA_SRC
        lda #>SS_SETTINGS
        adc #0
        sta FA_SRC+1
        lda #<M2_K
        sta FA_DST
        stz FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        lda M2_K
        rts

; x4: S2M_X + 4
x4:
        lda S2M_X
        clc
        adc #4
        sta S2M_X
        bcc :+
        inc S2M_X+1
:       rts

; ---------------------------------------------------------------------------
; m2_bench: uiBenchmark [R :3012-3058]: the title centred at y 24; at y
; 60 + 16 i the label at x 36 (bmWrite) and the value at the right edge
; 284 (uiAlign): VIEW (uiViewIndex's label, the full view only) and FPS
; (the benchmark's text M_BFPS); the CPU, CACHE and ROM rows black (dropped),
; then M_BROWS' three rows over them at x 36 (each when not empty: the
; play build's phase timing, docs/PLAY.md)
; ---------------------------------------------------------------------------
m2_bench:
        lda #24
        sta S2M_Y
        stz S2M_Y+1
        lda #<tx_btitle
        ldx #>tx_btitle
        ldy #0
        jsr m_align
        lda #BENCH_Y
        ldx #<tx_lview
        ldy #>tx_lview
        jsr label
        lda #<tx_full
        ldx #>tx_full
        ldy #VALUE_EDGE
        jsr m_align
        lda #BENCH_Y + BENCH_DY
        ldx #<tx_lfps
        ldy #>tx_lfps
        jsr label
        lda #<M_BFPS
        ldx #>M_BFPS
        ldy #VALUE_EDGE
        jsr m_align
        lda #X2_Y0              ; X2: the dropped rows black, marked
        sta M2_I
@row:   lda M2_I
        sec
        sbc #X2_Y0
        and #BENCH_DY - X2_ROWS ; (the 8 rows between two: not X2's)
        bne @next
        lda M2_I
        cmp S2_Y0
        bcc @next
        cmp S2_Y1
        bcs @next
        sec
        sbc S2_Y0
        jsr s2_mul160
        clc
        adc S2_BAND
        sta M2_Y
        txa
        adc S2_BAND+1
        sta M2_Y+1
        lda #0
        ldy #ROW_BYTES - 1
:       sta (M2_Y),y
        dey
        bne :-
        sta (M2_Y)
        stz S2_MB0
        lda #ROW_BYTES - 1
        sta S2_MB1
        lda M2_I
        tax
        inx
        jsr s2_mark
@next:  inc M2_I
        lda M2_I
        cmp #X2_Y1
        bcc @row
        ldx #0                  ; the play build's phase timing over the
@text:  lda M_BROWS,x           ;   black rows: M_BROWS' rows, each when
        beq @skip               ;   not empty, as the rows' labels
        phx
        txa
        lsr a                   ; (32 B a row: y = 92 + 16 i)
        clc
        adc #X2_Y0
        pha
        txa
        clc
        adc #<M_BROWS
        tax
        lda #>M_BROWS
        adc #0
        tay
        pla
        jsr label
        plx
@skip:  txa
        clc
        adc #M2_BROW
        tax
        cpx #3 * M2_BROW
        bcc @text
        rts

; label: bmWrite of the string X (low), Y (high) at (36, A); S2M_Y = A
label:
        sta S2M_Y
        stz S2M_Y+1
        lda #BENCH_X
        sta S2M_X
        stz S2M_X+1
        txa
        phy
        plx
        jmp m_wstr

        .segment "S2RODATA"

; the key setup: each action's Doom key and name [R :232-247]
ctl_keys:
        .byte 2, 1, 5, 6, 7, 8, 3, 4, 15, 0
ctl_lo: .lobytes tx_fire, tx_use, tx_fwd, tx_back, tx_tleft, tx_tright
        .lobytes tx_sleft, tx_sright, tx_strafe, tx_run, tx_defaults
ctl_hi: .hibytes tx_fire, tx_use, tx_fwd, tx_back, tx_tleft, tx_tright
        .hibytes tx_sleft, tx_sright, tx_strafe, tx_run, tx_defaults
tx_fire:     .asciiz "FIRE"
tx_use:      .asciiz "USE"
tx_fwd:      .asciiz "FORWARD"
tx_back:     .asciiz "BACKWARD"
tx_tleft:    .asciiz "TURN LEFT"
tx_tright:   .asciiz "TURN RIGHT"
tx_sleft:    .asciiz "STRAFE LEFT"
tx_sright:   .asciiz "STRAFE RIGHT"
tx_strafe:   .asciiz "STRAFE (HOLD)"
tx_run:      .asciiz "RUN (HOLD)"
tx_defaults: .asciiz "DEFAULT KEYS"
tx_controls: .asciiz "KEY SETUP"
tx_press:    .asciiz "KEY / ESC CANCEL"
tx_none:     .asciiz "---"
tx_comma:    .asciiz ", "
; uiViewIndex's label of the full view, the benchmark's [R :2778, :3059-3063]
tx_full:     .asciiz "FULL"
tx_btitle:   .asciiz "BENCHMARK: DEMO3"
tx_lview:    .asciiz "VIEW"
tx_lfps:     .asciiz "FPS:"
; the thermometers' dot of each gamma and mouse speed [R :2963-2964]
gamma_pos:   .byte 0, 4, 8, 11, 15
mouse_pos:   .byte 0, 2, 3, 5, 7, 8, 10, 12, 13, 15
; the //e key names (part plinput's tools/native/plkeys.py)
m2_names:
        plk_names
        .assert * - m2_names = PLK_CODES * PLK_NAMESIZE, error, "128 names"

