; game/sight/sight.inc: part sight's scratch block (docs/GAME.md). GPL-2,
; the port's own.
;
; The part keeps P_CheckSight's state across its calls (the object API, the
; math, its own routines in other groups) in its scratch block: upstream's
; near variables of p_sight65.s (los, the box of the line of sight, the
; opening, the fraction, sightblocker, TWOBLOCKER, CS_Z, CS_T, the
; products and quotient of interceptFrac).
;
; The block is SG_NEED (106) bytes, glayout.SCRATCH_REQUESTS['sight'].

SG      = SB_SIGHT
SG_NEED = 106
        .assert SB_SIGHT_SIZE >= SG_NEED, error, "sight's scratch block"

SG_T1   = SG + 0            ; t1, t2 (mobj slots)
SG_T2   = SG + 2
SG_SX   = SG + 4            ; strace: x, y (fixed_t), then dx, dy
SG_SY   = SG + 8
SG_DX   = SG + 12
SG_DY   = SG + 16
SG_EX   = SG + 20           ; t2x, t2y
SG_EY   = SG + 24
SG_XL   = SG + 28           ; the box of the line of sight, whole units
SG_XH   = SG + 30           ;   + $8000: x (L the ceil of the lower end,
SG_YL   = SG + 32           ;   H the whole part of the higher), then y
SG_YH   = SG + 34
SG_ZS   = SG + 36           ; los.sightzstart
SG_TOP  = SG + 40           ; los.topslope
SG_BOT  = SG + 44           ; los.bottomslope
SG_OTOP = SG + 48           ; the opening: the lower ceiling
SG_OBOT = SG + 52           ;   and the higher floor
SG_FRAC = SG + 56           ; interceptFrac's result (PS_FRAC)
SG_SB   = SG + 58           ; sightblocker (a line + 1, 0 none)
SG_TB   = SG + 60           ; TWOBLOCKER
SG_LINE = SG + 62           ; the seg's line
SG_SEG  = SG + 64           ; the seg
SG_SC   = SG + 66           ; the segs left in the subsector
SG_CSZ  = SG + 67           ; CS_Z: 1 when zSetup has run in this check
SG_FS   = SG + 68           ; the seg's front and back sectors
SG_BS   = SG + 69
SG_S0   = SG + 70           ; S before the walk's marker
SG_S1   = SG + 71           ; a first side
SG_FSP  = SG + 72           ; the sector cache lines of FS and BS
SG_BSP  = SG + 74
SG_DLP  = SG + 76           ; the divline of side_pt (a node or a line)
; the union: the side test's products, zSetup's CS_T, sightSlope's whole
; part, interceptFrac's work (never active at once)
SG_U    = SG + 78
SG_QA   = SG_U + 0          ; the side test: right = QA QB, left = QC QD
SG_QB   = SG_U + 2
SG_QC   = SG_U + 4
SG_QD   = SG_U + 6
SG_QR   = SG_U + 8          ;   right (4)
SG_QS   = SG_U + 12         ;   a product's sign
SG_CST  = SG_U + 0          ; zSetup: CS_T (4)
SG_SLW  = SG_U + 0          ; sightSlope: (height - sightzstart) >> 16
SG_IFV  = SG_U + 0          ; smul48: the 32-bit operand (4; lost), then
SG_IFR  = SG_U + 0          ;   interceptFrac's remainder (4)
SG_IFP  = SG_U + 4          ; smul48: the 48-bit product (6)
SG_IFS  = SG_U + 10         ; smul48: its sign
SG_IFQS = SG_U + 11         ; interceptFrac: the quotient's sign
SG_NUM  = SG_U + 12         ; interceptFrac: num (4), then the quotient
SG_IFE  = SG_U + 16         ;   den, then den >> 12 (4)
SG_DLN  = SG_U + 20         ;   the line: v1 x, y, dx, dy (whole units)
SG_END  = SG_U + 28
        .assert SG_END - SG = SG_NEED, error, "the scratch's size"
