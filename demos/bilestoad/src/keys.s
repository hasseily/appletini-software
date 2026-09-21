; The Bilestoad SHR port: keyboard handler.
;
; Upstream PDL compared the raw keyboard code with upper-case letters only,
; which was right on the Apple II+ the game came from. A //e sends
; lower-case codes unless Caps Lock is down, so on a //e no torso or arm
; command ever matched: only the paddle buttons (thrust) did anything. This
; PDL folds a-z to A-Z first, then applies the upstream table.
;
; Player 1: Q E turn the torso, A D the shield arm, Z C the axe arm,
; W S X stop each of them. Player 2: I P, K ;, , / and O L . stop.
; CTRL-S toggles the sound, ESC pauses until the next key, CTRL-R restarts.
; A key that is none of these reads the keyboard again, as upstream did.

KBDSTRB     = $C010
KEYS_P1     = 9                 ; the first nine table entries are player 1

PDL:
    lda KBD
    sta KBDSTRB
    bmi @key
    rts
@key:
    cmp #$93                    ; CTRL-S: sound on/off
    bne :+
    lda SND
    eor #$FF
    sta SND
    rts
:   cmp #$9B                    ; ESC: pause until the next key
    bne :+
@pause:
    lda KBD
    bpl @pause
    lda KBDSTRB
    rts
:   cmp #$92                    ; CTRL-R: restart
    bne :+
    jmp RIN
:   cmp #$E1                    ; a-z -> A-Z
    bcc @lookup
    cmp #$FB
    bcs @lookup
    and #$DF
@lookup:
    ldx #key_count-1
@find:
    cmp key_code,x
    beq @found
    dex
    bpl @find
    jmp PDL                     ; not a command: look for the next key
@found:
    cpx #KEYS_P1
    bcs @player2
    lda PDL0
    and key_mask,x
    ora key_bits,x
    sta PDL0
    rts
@player2:
    lda PDL1
    and key_mask,x
    ora key_bits,x
    sta PDL1
    rts

;           Q    E    A    D    Z    C    W    S    X    I    P    K    ;    ,    /    O    L    .
key_code:   .byte $D1, $C5, $C1, $C4, $DA, $C3, $D7, $D3, $D8, $C9, $D0, $CB, $BB, $AC, $AF, $CF, $CC, $AE
key_mask:   .byte $3C, $3C, $33, $33, $0F, $0F, $3C, $33, $0F, $3C, $3C, $33, $33, $0F, $0F, $3C, $33, $0F
key_bits:   .byte $01, $02, $04, $08, $10, $20, $00, $00, $00, $01, $02, $04, $08, $10, $20, $00, $00, $00
key_count   = * - key_bits
