; Doom for the Appletini -- the renderer's shared definitions (docs/DESIGN.md
; section 7).
;
; Included by every src/render/*.s file after kernel.inc. The renderer is
; tools/refrender.py in 65C02 assembly: the names below are the reference's
; where it has one (topfrac, rw_scale, ...). What lives where:
;
;   zero page (KZP)   the multiply/divide operands, the bank-read pointers,
;                     the eye, and the seg loop's accumulators (the hottest
;                     values); defined in rmain.s, declared here
;   main memory       code (RCODE read-only in $2000-$5FFF after the tables,
;                     RHICODE writable at $6000), state and buffers (RBSS at
;                     $6000+, RLOBSS at $0C00-$1FBB)
;   LC bank 1         the inner loops that run with RAMRD on (rlc.s): bank
;                     reads, the column-piece queue and its drawer, the span
;                     drawer, the visplane bank copies; bank 1 is switched in
;                     for the whole of render_frame, bank 2 (the blit) after
;   RENDER_BANK       RamWorks bank DD_LAST_BANK + 1: the visplanes' column
;                     arrays, the drawsegs and the openings (rplane.s,
;                     rsegs.s)
;
; Row values of the seg loop (yl, yh, the clip arrays, ...) are biased
; unsigned bytes: row r is stored as r + ROWBIAS, saturated to 0..255
; (rows -64..191). Rows the reference would carry beyond that range behave
; the same in every comparison the renderer and the sprite clipper make
; (see rsegs.s), and -2, Doom's sprite-clip sentinel, is exact.

.include "doomdata.inc"
.include "render/tables.inc"
.include "rview.inc"

; ---------------------------------------------------------------------------
; constants
ROWBIAS     = 64                ; row r is the byte r + ROWBIAS
RENDER_BANK = DD_LAST_BANK + 1  ; the renderer's scratch RamWorks bank
NF_SUBSECTOR = $80              ; bit 15 of a child (high byte)
NONE        = $FF               ; "no plane" / "no sector" handles
PL_OVERFLOW = $80               ; plane handle: a piece drawn at once (no visplane)
TC_SLOTS    = 32                ; the texture-record cache (rplane.s)
QN          = 64                ; the column-piece queue (rlc.s)

; the map arrays the renderer reads (MAPARR_* index of the MAP record)
NARRAYS     = 7                 ; VERTEXES .. SECTORS

; linedef flags
ML_TWOSIDED      = 4
ML_DONTPEGTOP    = 8
ML_DONTPEGBOTTOM = 16

; silhouettes
SIL_BOTTOM  = 1
SIL_TOP     = 2


; RENDER_BANK layout: visplane p's column arrays (index x + 1, columns
; -1..160): top at PL_TOP + p*PL_SIZE, bottom 162 bytes further. Then the
; drawsegs (DS_SIZE each) and the openings.
PL_COLS     = VIEW_W + 2        ; 162
PL_SIZE     = 2 * PL_COLS       ; 324
PL_TOP      = $0200
PL_END      = PL_TOP + MAXVISPLANES * PL_SIZE      ; $A500
DS_BASE     = PL_END
DS_END      = DS_BASE + MAXDRAWSEGS * 26
OPENINGS    = DS_END            ; MAXOPENINGS bytes
.assert OPENINGS + MAXOPENINGS <= $C000, error, "RENDER_BANK overflows"

; ---------------------------------------------------------------------------
; the renderer's zero page (rmain.s)
.globalzp m_a, m_b, m_r, mul_na, mul_nb     ; multiply: m_r = m_a * m_b
.globalzp d_n, d_d, d_r                     ; divide: d_n / d_d -> d_n, rem d_r
.globalzp t0, t1, t2, t3, t4, t5, t6, t7    ; scratch
.globalzp p0, p1, p2                        ; scratch pointers
.globalzp rb_bank, rb_src, rb_dst, cur_bank ; bank reads (rlc.s)
.globalzp vx, vy, vz, va                    ; the eye: 24-bit sub-units, BAM16
.globalzp s_ang, s_val                      ; sin_bam in/out
.globalzp pa_x, pa_y, pa_r                  ; point_to_angle in/out
.globalzp topfrac, topstep, botfrac, botstep
.globalzp pixhigh, pixhighstep, pixlow, pixlowstep
.globalzp rw_scale, rw_step
.globalzp rx, ryl, ryh

; ---------------------------------------------------------------------------
; routines and data across the modules
.global umul, smul, udiv, sdiv, neg_n
.global fine_sin, sin_bam, cos_bam, point_to_angle, tan_fine
.global rb_read, rb_read1, elem_addr, rb_write_on, rb_write_off
.global q_flush, q_count, q_wall, q_fill
.global render_map
