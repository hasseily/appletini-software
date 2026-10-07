; s2_am.inc: the automap's places, shared by s2_am.s (the image AMAPW) and
; s2_amline.s (the transform, the clip and the line loops, which part
; s2ovl's OVLW links too). Part s2amap; docs/SCREENS.md (the automap).
;
; Three bases, which another image can set before including this file
; (OVLW lives in the renderer's W, where AMAPW's places are not free):
;   AMZ    the automap's zero page, 48 bytes ($80-$AF: s2layout.py's
;          S2A_*)
;   AMW    its W variables, 192 bytes (AMAPW: $A840-$A8FF, the part of
;          its marks range the marks page leaves)
;   AMST   its state block (AMAPW: $AC00, s2layout's A_* places are
;          offsets from it)

.ifndef AMZ
AMZ     = $80
.endif
.ifndef AMW
AMW     = $A840
.endif
.ifndef AMST
AMST    = AMAPW_STATE
.endif

; ---- the state block: s2layout's field map (A_*: upstream's forms) and
; this part's own fields (s2amap.inc: A_MODE, A_OLDTOP, A_ON, A_OB) ------
ST_MX     = A_MX - AMAPW_STATE + AMST         ; m_x .. (int32 each)
ST_MY     = A_MY - AMAPW_STATE + AMST
ST_MW     = A_MW - AMAPW_STATE + AMST
ST_MH     = A_MH - AMAPW_STATE + AMST
ST_MX2    = A_MX2 - AMAPW_STATE + AMST
ST_MY2    = A_MY2 - AMAPW_STATE + AMST
ST_MINX   = A_MINX - AMAPW_STATE + AMST
ST_MINY   = A_MINY - AMAPW_STATE + AMST
ST_MAXX   = A_MAXX - AMAPW_STATE + AMST
ST_MAXY   = A_MAXY - AMAPW_STATE + AMST
ST_MAXW   = A_MAXW - AMAPW_STATE + AMST
ST_MAXH   = A_MAXH - AMAPW_STATE + AMST
ST_MINSC  = A_MINSCALEMTOF - AMAPW_STATE + AMST
ST_MAXSC  = A_MAXSCALEMTOF - AMAPW_STATE + AMST
ST_SCALE  = A_SCALEMTOF - AMAPW_STATE + AMST
ST_FTOM   = A_SCALEFTOM - AMAPW_STATE + AMST
ST_MZOOM  = A_MTOFZOOMMUL - AMAPW_STATE + AMST
ST_FZOOM  = A_FTOMZOOMMUL - AMAPW_STATE + AMST
ST_PAN    = A_MPANINC - AMAPW_STATE + AMST    ; x (4), y (4)
ST_OLDLOC = A_FOLDLOC - AMAPW_STATE + AMST    ; x (4), y (4)
ST_STOPPED = A_STOPPED - AMAPW_STATE + AMST   ; words
ST_LASTLEV = A_LASTLEVEL - AMAPW_STATE + AMST
ST_MODE   = A_AUTOMAPMODE - AMAPW_STATE + AMST
ST_VALID  = A_AMVALID - AMAPW_STATE + AMST
ST_BAND   = A_AMBAND - AMAPW_STATE + AMST
ST_AMMODE = A_MODE - AMAPW_STATE + AMST       ; AM_MODE (a byte)
ST_OLDTOP = A_OLDTOP - AMAPW_STATE + AMST     ; AM_OLDTOP (a byte)
ST_ON     = A_ON - AMAPW_STATE + AMST         ; the old list's entries
ST_OB     = A_OB - AMAPW_STATE + AMST         ; its bands' first entries
ST_END    = A_OB + 8 - AMAPW_STATE + AMST

; automapmode [R am_map65.s:31-34]
AMF_ACTIVE  = 1
AMF_OVERLAY = 2
AMF_ROTATE  = 4
AMF_FOLLOW  = 8

AM_FW     = 320                 ; the map window: the screen's width,
AM_FH     = 168                 ;   the view's height
AM_TITLEY = AM_FH - 1 - 7       ; the lines' rows end there (HU_TITLEY)
AM_STRIP  = 10                  ; the message strip's rows

; ---- zero page -----------------------------------------------------------
PX      = AMZ + $00             ; the pixel's x (2)
ERR2    = AMZ + $02             ; twice the error (2)
LNY     = AMZ + $04             ; the pixel's row (0-167)
SYS     = AMZ + $05             ; the y step: $01 or $FF
ROWP    = AMZ + $06             ; the row in the band: BOFF + LNY * 160
SROW    = AMZ + $08             ; the row on the screen: $2000 + LNY * 160
SXS     = AMZ + $0A             ; the x step: 1 or -1 (2)
ALDX     = AMZ + $0C             ; dx (2)
ALDY     = AMZ + $0E             ; dy = -|y1 - y0| (2)
DX2     = AMZ + $10             ; 2 dx, 2 dy, 2 dx + 2 dy (2 each)
DY2     = AMZ + $12
DD2     = AMZ + $14
CNT     = AMZ + $16             ; the pixels left - 1 (2)
NIBH    = AMZ + $18             ; the colour's nibble, left and right pixel
NIBL    = AMZ + $19
COLI    = AMZ + $1A             ; the colour's index (s2amap.inc AMC_*)
PLO     = AMZ + $1B             ; the rows plotted: PLO .. PHI - 1
PHI     = AMZ + $1C
BY0     = AMZ + $1D             ; the band's first screen row
LNP     = AMZ + $1E             ; the new list's next entry (2)
LAST    = AMZ + $20             ; the last entry listed (2)
OVF     = AMZ + $22             ; the new list is full
AT0      = AMZ + $23             ; temporaries AT0 .. AT7
AT1      = AMZ + $24
AT2      = AMZ + $25
AT3      = AMZ + $26
AT4      = AMZ + $27
AT5      = AMZ + $28
AT6      = AMZ + $29
AT7      = AMZ + $2A
PA      = AMZ + $2B             ; the 32-bit helpers' pointers (2 each)
PB      = AMZ + $2D
AMZ_END = AMZ + $2F

; ---- W variables -----------------------------------------------------------
ML      = AMW + $00             ; the line on the map: a.x, a.y, b.x, b.y
FL      = AMW + $10             ; the line on the screen (int16 each)
OC1     = AMW + $18             ; the outcodes of its ends
OC2     = AMW + $19
OCT     = AMW + $1A
OUTS    = AMW + $1B
TMPX    = AMW + $1C             ; the clipped end (2 each)
TMPY    = AMW + $1E
ACLD     = AMW + $20
AMT     = AMW + $22             ; AM_T, AM_U (4 each)
AMU     = AMW + $26
RTX     = AMW + $2A             ; the rotation: the new x, the origin, the
RTOX    = AMW + $2E             ;   point from the origin, the cosine and
RTOY    = AMW + $32             ;   the sine (4 each)
RTDX    = AMW + $36
RTDY    = AMW + $3A
ARTC     = AMW + $3E
ARTS     = AMW + $42
AMDX    = AMW + $46             ; the arrow's place (4 each)
AMDY    = AMW + $4A
MIN16   = AMW + $4E             ; the box of the lines: x, y (int16 each)
MAX16   = AMW + $52
AMI     = AMW + $56             ; a line's number, a counter (2)
AMTURN  = AMW + $58             ; the arrow turns
AWTOP    = AMW + $59             ; the lines' rows: AWTOP .. AWBOT - 1
AWBOT    = AMW + $5A
LB      = AMW + $5B             ; a line's record (AM_LINE_FETCH bytes)
SECF    = AMW + $77             ; its sectors: floor, ceiling (4 each),
SECB    = AMW + $80             ;   oldspecial (1)
MOB     = AMW + $89             ; the player's RTHING (24)
BOFF    = AMW + $A1             ; the band's W address less BY0 * 160 (2)
FFLAGS  = AMW + $A3             ; the frame: FF_REDRAW, FF_STRIP
NB      = AMW + $A4             ; the new list's bands' first entries (5 words)
SEGN    = AMW + $AE             ; the frame's lines on the screen (2)
SEGK    = AMW + $B0             ; one of them (2)
AMEV    = AMW + $B2             ; the responder's key (2)
AMTYPE  = AMW + $B4             ; and the event's type
AMTICS  = AMW + $B5             ; am_frame's tics
SPECW   = AMW + $B6             ; a line's special, sign-extended (2)
BANDK   = AMW + $B8             ; the band
AMW_END = AMW + $B9

FF_REDRAW = $01                 ; the frame draws all (upstream's redraw)
FF_STRIP  = $02                 ; the strip goes black (clearStrip)

; the record of a line on the screen (SS_AMSEG, 8 bytes): x0 (2), y0,
; x1 (2), y1, the colour's index, a pad
SG_X0   = 0
SG_Y0   = 2
SG_X1   = 3
SG_Y1   = 5
SG_COL  = 6

; ---- macros ------------------------------------------------------------
; PTR ptr, addr: the zero page pointer ptr = addr
.macro PTR ptr, addr
        lda #<(addr)
        sta ptr
        lda #>(addr)
        sta ptr+1
.endmacro

; CP4 src, dst: 4 bytes
.macro CP4 src, dst
        lda src
        sta dst
        lda src+1
        sta dst+1
        lda src+2
        sta dst+2
        lda src+3
        sta dst+3
.endmacro
