; pl_input.inc: the places and constants of src/native/pl_input.s and
; pl_keys.s (part plinput; docs/SCREENS.md).
; GPL-2, the port's own. Needs s2.inc.

; From s2.inc: PL_KEYTAB, the //e key table's Doom keys at main
; $1F80-$1FFF; PL_MLX, the mouse's last X (a word); PL_BIND, the key
; setup's byte ($FF waits, a code taken, $80 idle); PLZ, the poll's 16
; bytes of zero page over the drawers' temporaries S2_W .. S2_O.

PLZ_M     = PLZ                 ; the mask being built (3)
PLZ_OLD   = PLZ + 3             ; the old mask (3)
PLZ_T     = PLZ + 6
PLZ_SB    = PLZ + 7             ; pl_mask's buttons
PLZ_NH    = PLZ + 8             ; the held key after the poll
PLZ_NB    = PLZ + 9             ; the buttons after the poll
PLZ_CH    = PLZ + 10            ; the new press's character
PLZ_MENU  = PLZ + 11
PLZ_SKIP  = PLZ + 12            ; a code out of the masks (the key setup's)
PLZ_K     = PLZ + 13            ; pl_bind, pl_action: the Doom key
PLZ_XL    = PLZ + 13            ; the mouse's X
PLZ_XH    = PLZ + 14
PLZ_C     = PLZ + 14            ; pl_bind: the code
PLZ_A0    = PLZ + 14            ; pl_action: the codes found
PLZ_A1    = PLZ + 15

KBD       = $C000
KBDSTRB   = $C010               ; bit 7: a key is down; an access clears
BUTN0     = $C061               ;   $C000's strobe. Open Apple,
BUTN1     = $C062               ;   Solid Apple
MOUSE_XLO = $C0A1               ; the mouse card in slot 2
MOUSE_XHI = $C0A2
MOUSE_BTN = $C0A5               ; bit 0 button 0 (left), bit 1 button 1
MOUSE_SEQ = $C0A6
MOUSE_CLAMPSEL = $C0A7
MOUSE_MIN = $C0A8
MOUSE_MAX = $C0AA
MOUSE_CMD = $C0AC
CMD_CLAMP = 2
CENTRE    = $80                 ; X's high byte at the centre

EV_KEYDOWN = 0
EV_KEYUP  = 1
NOKEY     = $FF
NUMKEYS   = 23
KEYC_UP   = $80                 ; the menu keys' characters: UP, DOWN, LEFT,
KEYC_ENTER = $84                ;   RIGHT, ENTER, BACK
REP_DELAY = 11                  ; [R i_iigs65.s:708-713]
REP_RATE  = 4
QBYTES    = PL_EVENTS * PL_EVENT_SIZE
QMOST     = 7 * PL_EVENT_SIZE   ; a poll's events
BIND_WAIT = PLB_WAIT            ; $FF (s2.inc: the menu writes it too)
BIND_IDLE = PLB_IDLE            ; $80
INPUT_SIZE = PL_BIND + 1 - PL_QUEUE
