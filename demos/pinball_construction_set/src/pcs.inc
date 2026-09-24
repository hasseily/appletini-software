; Pinball Construction Set for the Appletini -- shared definitions.
;
; Zero page: the upstream modules keep their original zero-page map
; ($00-$26 draw/scan locals, $3E sound toggle, $80-$AE cursor/object/DB
; globals, $C0-$FF runtime and scan-converter arrays). The port's own
; variables are linked into ZEROPAGE ($40-$7F), which the upstream never
; touches (verified: only STGL $3E lies between $27 and $7F); RUN2's
; game variables are moved to $27-$35 (see below).

; --- soft switches -----------------------------------------------------
KBD         = $C000
STORE80OFF  = $C000
STORE80ON   = $C001
RAMRDOFF    = $C002
RAMRDON     = $C003
RAMWRTOFF   = $C004
RAMWRTON    = $C005
ALTZPOFF    = $C008
ALTZPON     = $C009
KBDSTRB     = $C010
RDVBLBAR    = $C019
NEWVIDEO    = $C029
TEXTOFF     = $C050
TEXTON      = $C051
BUTTON0     = $C061
BUTTON1     = $C062
PADDLE0     = $C064
PADDLE1     = $C065
PTRIG       = $C070
RAMWORKS    = $C073
TWSPEED     = $C074
LCBANK2RD   = $C080
LCBANK2WR   = $C083
LCBANK1RD   = $C088
LCBANK1WR   = $C08B
LCROM       = $C082             ; ROM read, RAM write off: ProDOS's normal state

; mouse card, slot 2
MOUSE_STATUS = $C0A0
MOUSE_XLO   = $C0A1
MOUSE_XHI   = $C0A2
MOUSE_YLO   = $C0A3
MOUSE_YHI   = $C0A4
MOUSE_BTN   = $C0A5
MOUSE_CLAMPSEL = $C0A7
MOUSE_MINLO = $C0A8
MOUSE_MINHI = $C0A9
MOUSE_MAXLO = $C0AA
MOUSE_MAXHI = $C0AB
MOUSE_CMD   = $C0AC
MOUSE_MODE  = $C0AE
MOUSE_ACK   = $C0AF
MOUSE_ROM   = $C200             ; ID bytes $C205=$38 $C207=$18 $C20B=$01 $C20C=$20

; Phasor, slot 4
PHASOR_MB     = $C0C8
PHASOR_NATIVE = $C0C5
VIA_A       = $C410
VIA_B       = $C480
SSI_BASE    = $C440

; ProDOS
MLI         = $BF00
MLI_QUIT    = $65
MLI_OPEN    = $C8
MLI_READ    = $CA
MLI_WRITE   = $CB
MLI_CLOSE   = $CC
MLI_CREATE  = $C0
MLI_GETPREFIX = $C7
MLI_SETPREFIX = $C6
MLI_ONLINE  = $C5
IOBUF       = $BB00             ; 1 KB ProDOS file buffer during file I/O
ARENA       = $BB00             ; render arena when no file is open
ARENA_ROWS  = 13                ; 13 rows of 77 bytes = 1001 bytes
ARENA_SIZE  = $0400             ; $BB00-$BEFF, the ProDOS buffer's 1 KB
ARENA_BYTES = ARENA_ROWS * 77

; --- screen ------------------------------------------------------------
SHR_BASE    = $2000
SHR_ROW     = 160
SHR_SCB     = $9D00
SHR_PAL     = $9E00
TABLE_W     = 154               ; table pixels 0..153 (polygon units)
TABLE_H     = 192
TABLE_BYTES = 77                ; 154 / 2
PANEL_X     = 154               ; the panel starts here (as in the original)
SCREEN_W    = 320
SCREEN_H    = 200

; colours (palette 0, docs/DESIGN.md section 3)
COL_BLACK   = 0
COL_DKGREY  = 1
COL_GREY    = 2
COL_LTGREY  = 3
COL_WHITE   = 4
COL_DKRED   = 5
COL_RED     = 6
COL_ORANGE  = 7
COL_YELLOW  = 8
COL_DKGREEN = 9
COL_GREEN   = 10
COL_NAVY    = 11
COL_BLUE    = 12
COL_CYAN    = 13
COL_VIOLET  = 14
COL_BROWN   = 15
COL_PANEL   = COL_DKGREY
COL_TEXT    = COL_LTGREY
COL_HILITE  = COL_YELLOW
COL_INVISO  = $10               ; FILLCOLOR of library objects

; --- upstream zero page (names as in the sources) -----------------------
PARAM       = $00               ; 7 bytes
TEMP        = $07
XTEMP       = $08
YTEMP       = $09
TEMP2       = $0A
BASE1       = $10
BASE2       = $12
SCANLINE    = $1F
HCNT        = $25
STGL        = $3E               ; bit 7 = sound off
CURSOR      = $80               ; 7-byte bitmap record: ptr, y, x lo, x hi, h, w
CURSORY     = $82
CURSORX     = $83               ; the port keeps x as a 16-bit value here
CURSORXH    = $84
CURSORHEIGHT = $85
CURSORWIDTH = $86
NEWITEM     = $8D
LASTITEM    = $8F
OBJ         = $91
NEXTOBJ     = $93
OBJCOUNT    = $94
PLYPTRX     = $95
PLYPTRY     = $97
OBJID       = $99
FILLCOLOR   = $9A
VRTXCOUNT   = $9B
LBASE       = $9C
SCANMODE    = $9E
MEMBTM      = $9F
MIDBTM      = $A1
MIDTOP      = $A3
MIDY        = $A5
COLOR       = $A6               ; EDIT: current paint colour
EDITMODE    = $A8
; RUN / RUN2 runtime
RUNLEN      = $C0
PDL0        = $C1
PDL1        = $C2
BTN0        = $C3
BTN1        = $C4
PTM1        = $C5
PTM2        = $C6
SERIES      = $C8
SLICE       = $C9
DSCORE      = $CB
DBONUS      = $CC
BMULT       = $CD
INITMODE    = $CE
BST         = $D1
X1          = $D2
Y1          = $D3
X2          = $D4
Y2          = $D5
; RUN2 (moved from $80-$8E by src/patches.json: the cursor record above
; is written every frame, including the game's)
PLAYER      = $27
PLAYERCNT   = $28
BALLS       = $29
SLEEPCNT    = $2A
LIVEBALLS   = $34
GAMEMODE    = $35

; object record
OBJ_POLYGON = 1
OBJ_BPOLYGON = 2
OBJ_LIBOBJ  = 3
; L-record offsets
L_PTR       = 0                 ; sprite pointer (directory entry of the frame)
L_Y         = 2
L_X         = 3
L_XH        = 4
L_H         = 5
L_W         = 6
L_STRIDE    = 7
L_STATE     = 8
L_SCORE     = 9
L_RUN       = 10
L_INIT      = 12
L_HIT       = 14
L_BST       = 16                ; ball: state
L_X1        = 17                ; ball: position
L_Y1        = 18

; --- debug mailbox at $0300 ----------------------------------------------
MAILBOX     = $0300
MB_MAGIC    = MAILBOX+0         ; "PCS1"
MB_STATE    = MAILBOX+4         ; 0 title, 1 editor, 2 play, 3 game, 4 wire, 5 magnifier, 6 world, 7 files
; MB_STATE values (tools/run_editor.py names them)
MB_ST_BOOT  = 0
MB_ST_EDIT  = 1
MB_ST_WIRE  = 2
MB_ST_MAG   = 3
MB_ST_DISK  = 4
MB_ST_PLAY  = 5
MB_ST_GAME  = 6
MB_ST_TITLE = 7
MB_ST_QUIT  = 8
MB_FRAME    = MAILBOX+5         ; 16-bit frame counter
MB_WRITES   = MAILBOX+7         ; SHR bytes written by the last frame
MB_MAXWRITES = MAILBOX+9        ; largest count seen
MB_RECTS    = MAILBOX+11        ; dirty rectangles rendered last frame
MB_MOUSEX   = MAILBOX+12        ; 16-bit
MB_MOUSEY   = MAILBOX+14
MB_INPUT    = MAILBOX+15        ; input bits
MB_TICKS    = MAILBOX+16        ; ticks run last frame
MB_HAVEMOUSE = MAILBOX+17
MB_RAMWORKS = MAILBOX+18        ; RamWorks banks found
MB_SOUND    = MAILBOX+19        ; sound chips
MB_SIZE     = 20
MB_NOTITLE  = MAILBOX+MB_SIZE   ; $A5 here at start-up skips the title screen (a test
                                ; hook: mailbox_init clears MB_SIZE bytes, not this one)

; multiball sleepers kept by the port (the original had 255 slots)
SLEEP_MAX   = 8

; --- stack page routine ---------------------------------------------------
AUX_FETCH   = $0110             ; aux_fetch copied here at start-up
AUX_STORE   = $0140             ; its write counterpart (aux_store_rows)
