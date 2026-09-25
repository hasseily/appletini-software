; Doom for the Appletini -- kernel definitions (docs/DESIGN.md sections 2, 4, 8).
;
; Hardware equates, the kernel's zero page and the entry points every
; kernel/renderer module may use. Included by every src/kernel/*.s and
; src/render/*.s file. The kernel's zero page lives in the KZP segment
; ($02-$DF, src/doom.cfg); cc65's ZEROPAGE ($E0-$FF) is never touched
; from assembly except through the C glue.

.setcpu "65C02"

; ---------------------------------------------------------------------------
; soft switches
KBD         = $C000
KBDSTRB     = $C010
RAMRDOFF    = $C002
RAMRDON     = $C003
RAMWRTOFF   = $C004
RAMWRTON    = $C005
ALTZPOFF    = $C008
ALTZPON     = $C009
RDVBLBAR    = $C019             ; bit 7 = 0 during vertical blanking
NEWVIDEO    = $C029
TEXTOFF     = $C050
TEXTON      = $C051
BUTTON0     = $C061             ; Open Apple
BUTTON1     = $C062             ; Closed Apple
RAMWORKS    = $C073             ; RamWorks bank select
TWSPEED     = $C074             ; vTW speed lock: 0 = selected speed
LCBANK2RD   = $C080             ; RAM read, bank 2, write off
LCROM       = $C082             ; ROM read, RAM write off
LCBANK2WR   = $C083             ; RAM read+write bank 2 (read twice)
LCBANK1RD   = $C088
LCBANK1WR   = $C08B             ; RAM read+write bank 1 (read twice)

; the mouse card, slot 2 (appletini-one/hdl/apple/mouse_card.sv)
MOUSE_STATUS   = $C0A0
MOUSE_XLO      = $C0A1
MOUSE_XHI      = $C0A2
MOUSE_YLO      = $C0A3
MOUSE_YHI      = $C0A4
MOUSE_BTN      = $C0A5          ; bit 0 left, bit 1 right
MOUSE_CLAMPSEL = $C0A7
MOUSE_MINLO    = $C0A8
MOUSE_MINHI    = $C0A9
MOUSE_MAXLO    = $C0AA
MOUSE_MAXHI    = $C0AB
MOUSE_CMD      = $C0AC
MOUSE_MODE     = $C0AE
MOUSE_ACK      = $C0AF
MOUSE_ROM      = $C200          ; ID bytes $C205=$38 $C207=$18 $C20B=$01 $C20C=$20

; ProDOS (the loader only)
MLI         = $BF00
MLI_QUIT    = $65
MLI_OPEN    = $C8
MLI_READ    = $CA
MLI_CLOSE   = $CC
MLI_GET_EOF = $D1

; ---------------------------------------------------------------------------
; the SHR4 PAL256 screen (aux bank 0)
SHR_BASE    = $2000             ; row y at $2000 + 320*y, 320x100 bytes
SHR_ROW     = 320
SHR_PAGING  = $9DF8             ; 0 = progressive
SHR_MAGIC   = $9DFC             ; "SHR4" | $80
SHR_PAL     = $9E00             ; 256 x (G<<4|B, $20|R)
VIEW_W      = 160               ; game pixels (each two screen pixels wide)
VIEW_H      = 84                ; rows 0-83; 84-99 the status bar

; ---------------------------------------------------------------------------
; memory
GAME_BANK   = 1                 ; legacy GAME space / banked far game records
.ifdef BANKED_GAME
.include "banked.inc"
MIN_BANKS   = 128               ; banked engine, snapshots and converted episode
.else
MIN_BANKS   = 64                ; legacy platform configuration
.endif
.import VIEWBUF, VIEWBUF_SIZE   ; column x at VIEWBUF + 84*x (src/doom.cfg)

; kspace values
SPACE_RENDER = 0
SPACE_GAME   = 1

; ---------------------------------------------------------------------------
; the kernel's zero page (defined in kstart.s, far.s, frame.s). .globalzp
; and .global export from the defining module and import everywhere else.
.globalzp kspace                ; SPACE_RENDER or SPACE_GAME
.globalzp kcall                 ; 2: the GAME routine call_game calls
.globalzp vbl_count             ; 16-bit count, +1 per VBL interrupt (50/60 Hz)
.globalzp far_src               ; 3: lo, hi, bank -- a far address
.globalzp far_dst               ; 3: lo, hi, bank
.globalzp far_ptr               ; 2: a near address in the caller's space
.globalzp far_len               ; 2: byte count
.globalzp far_idx               ; 2: element index for far_elem
.globalzp ktmp                  ; 8 scratch bytes, free between kernel calls

; ---------------------------------------------------------------------------
; entry points (LC; callable from RENDER-space assembly)
.global space_game, space_render, call_game
.global far_read, far_write, far_copy, far_elem
.global set_palette, blit_view, present
.global input_init, input_frame, kin
.global kernel_start, kernel_crash, kernel_reboot
.global frame_loop, render_frame
