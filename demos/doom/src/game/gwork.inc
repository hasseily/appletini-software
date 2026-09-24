; Doom for the Appletini -- the game's 32-bit work area (src/game/gwork.s).
;
; Every 32-bit value the game's assembly works on lives in W, one table of
; 64 four-byte slots, and is named here by its offset. The operations on
; them are subroutines taking the offsets in X and Y (7 bytes a call,
; against about 25 for the same operation written out), see gwork.s. The
; C-visible fixed_t globals of the core (trace, opentop.., tmbbox, tmx..,
; attackrange and the slopes) are slots too: gwork.s exports them under
; their C names.
;
; W_T0..W_T4 are scratch for leaf routines (anything that calls another
; routine may lose them, except fx_mul/fx_div, which keep them); every
; other slot belongs to the routines named with it, which may nest (the
; slots of P_CheckPosition stay valid while its callbacks run, and so on).

.global W

; fixed.s: FixedMul/FixedDiv operands and result (w_mul, w_div)
W_FA        = 0
W_FB        = 4
W_FR        = 8
; scratch
W_T0        = 12
W_T1        = 16
W_T2        = 20
W_T3        = 24
W_T4        = 28
; p_maputl: the trace (divline_t, C: trace), line opening (C: opentop..)
W_TRX       = 32
W_TRY       = 36
W_TRDX      = 40
W_TRDY      = 44
W_OPENTOP   = 48
W_OPENBOTTOM = 52
W_OPENRANGE = 56
W_LOWFLOOR  = 60
; p_maputl: the points of pols (line side) and pods (divline side)
W_PLX       = 64
W_PLY       = 68
W_PDX       = 72
W_PDY       = 76
; p_maputl: a divline built for intercept_vector (x, y, dx, dy)
W_IDLX      = 80
W_IDLY      = 84
W_IDLDX     = 88
W_IDLDY     = 92
; p_maputl: a thing's position (thing_xy)
W_THX       = 96
W_THY       = 100
; p_maputl: P_PathTraverse
W_PTX1      = 104
W_PTY1      = 108
W_PTX2      = 112
W_PTY2      = 116
W_PTXSTEP   = 120
W_PTYSTEP   = 124
W_PTXINT    = 128
W_PTYINT    = 132
W_TIDIST    = 136
; p_map: check position (C: tmbbox[4], tmx, tmy, tmfloorz, tmceilingz, tmdropoffz)
W_TMTOP     = 140
W_TMBOTTOM  = 144
W_TMLEFT    = 148
W_TMRIGHT   = 152
W_TMX       = 156
W_TMY       = 160
W_TMFLOORZ  = 164
W_TMCEILINGZ = 168
W_TMDROPOFFZ = 172
W_TMRADIUS  = 176
; p_map: attacks (C: attackrange, aimslope, topslope, bottomslope)
W_ATTACKRANGE = 180
W_AIMSLOPE  = 184
W_TOPSLOPE  = 188
W_BOTTOMSLOPE = 192
W_SHOOTZ    = 196
; p_map: sliding and moving
W_BESTSLIDE = 200
W_SECONDSLIDE = 204
W_TMXMOVE   = 208
W_TMYMOVE   = 212
W_OLDX      = 216
W_OLDY      = 220
W_LEADX     = 224
W_LEADY     = 228
W_TRAILX    = 232
W_TRAILY    = 236
; p_mobj
W_M0        = 240
W_M1        = 244
W_M2        = 248
W_M3        = 252
W_SIZE      = 256

W_TRACE     = W_TRX
W_TMBBOX    = W_TMTOP
