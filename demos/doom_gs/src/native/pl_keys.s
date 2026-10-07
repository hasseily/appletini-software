; pl_keys.s: the //e key table's routines (part plinput;
; docs/SCREENS.md): what the boot and
; the menus call, apart from the poll every frame image links
; (pl_input.s), so pl_poll keeps its 600 B. GPL-2,
; the port's own, written from upstream's documented behaviour of
; I_InitKeyboard, I_DefaultKeys, I_BindKey, recount and I_ActionKeys
; [R i_iigs65.s:685-700, :857-990].
;
;   pl_init      I_InitKeyboard (the boot): the input block cleared,
;                PL_BIND idle, the mouse card's X window 0-$FFFF and X
;                at $8000 (the mode, VBL and enable, is the boot's), the
;                default keys
;   pl_defaults  I_DefaultKeys: the default keys, then recount's events
;   pl_bind      I_BindKey: A = a Doom key, X = a //e code: the code is
;                the only key of the Doom key, then recount's events
;   pl_action    I_ActionKeys: A = a Doom key; returns A, X = its first
;                two //e codes ($FF: none) in upstream's order of the
;                ranges $30-$3F, $20-$2F, $00-$1F, $40-$7F
;
; recount: the Doom keys of the sources down (PL_HELD, PL_BUTTONS)
; before the table changes and after it; each that changed posted as
; the poll does (pl_diff, 22 to 0), at most 10 events.

        .setcpu "65C02"
        .include "s2.inc"
        .include "pl_input.inc"

        .import pl_bold, pl_mask, pl_diff, pl_centre
        .export pl_init, pl_defaults, pl_bind, pl_action
        .export pl_iwin         ; (pl_boot.s: without the Appletini's mouse
                                ;   card the boot branches over the window)

        .segment "S2CODE"

pl_init:
        ldx #INPUT_SIZE - 1     ; the block cleared
:       stz PL_QUEUE,x
        dex
        bpl :-
        lda #BIND_IDLE
        sta PL_BIND
pl_iwin:
        stz MOUSE_CLAMPSEL      ; X's window 0-$FFFF
        stz MOUSE_MIN
        stz MOUSE_MIN+1
        lda #$FF
        sta MOUSE_MAX
        sta MOUSE_MAX+1
        lda #CMD_CLAMP
        sta MOUSE_CMD
        jsr pl_centre
pl_defaults:
        jsr pl_bold
        ldx #$7F
        lda #NOKEY
:       sta PL_KEYTAB,x
        dex
        bpl :-
        ldx #DEFAULTS_SIZE - 2
:       ldy pl_defs,x           ; a code
        lda pl_defs+1,x         ; its Doom key
        sta PL_KEYTAB,y
        dex
        dex
        bpl :-
        bra pl_recount

pl_bind:
        sta PLZ_K
        stx PLZ_C
        jsr pl_bold
        ldx #$7F                ; the Doom key's codes: none
:       lda PL_KEYTAB,x
        cmp PLZ_K
        bne :+
        lda #NOKEY
        sta PL_KEYTAB,x
:       dex
        bpl :--
        ldx PLZ_C
        lda PLZ_K
        sta PL_KEYTAB,x
; recount: the new mask from the sources down, the changes posted
pl_recount:
        lda PL_BUTTONS
        sta PLZ_SB
        lda PL_HELD
        jsr pl_mask
        jmp pl_diff

pl_action:
        sta PLZ_K
        lda #$FF
        sta PLZ_A0
        sta PLZ_A1
        ldy #0
@r:     ldx pl_rlo,y
@c:     lda PL_KEYTAB,x
        cmp PLZ_K
        bne @n
        lda PLZ_A0
        bpl :+
        stx PLZ_A0
        bra @n
:       lda PLZ_A1
        bpl @n
        stx PLZ_A1
@n:     inx
        txa
        cmp pl_rhi,y
        bcc @c
        iny
        cpy #4
        bcc @r
        lda PLZ_A0
        ldx PLZ_A1
        rts


        .segment "S2RODATA"
pl_rlo: .byte $30, $20, $00, $40        ; I_ActionKeys' ranges
pl_rhi: .byte $40, $30, $20, $80
; the default keys (docs/SCREENS.md; the same as tools/native/plkeys.py's
; DEFAULTS): a //e code and its Doom key
pl_defs:
        .byte $0B, 5, $0A, 6, $08, 7, $15, 8   ; the arrows
        .byte 'W', 5, 'S', 6, 'A', 3, 'D', 4   ; move, strafe
        .byte ',', 3, '.', 4                    ; strafe
        .byte 'E', 1, ' ', 1, $0D, 1            ; use
        .byte $1B, 9, $09, 10, '-', 11, '=', 12 ; menu, map, zoom
        .byte $72, 2, $73, 1, $71, 2, $70, 15   ; Open Apple fire, Solid
                                                ;   Apple use, MOUSE 1 fire,
                                                ;   MOUSE 2 strafe
        .byte '1', 16, '2', 17, '3', 18, '4', 19, '5', 20, '6', 21, '7', 22
DEFAULTS_SIZE = * - pl_defs
