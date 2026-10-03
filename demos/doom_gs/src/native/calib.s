; calib.s: CALIB.SYSTEM, the calibration disk's program (docs/SPEED.md 5,
; docs/results/calib.md). GPL-2, the port's own.
;
; A fixed list of 52 microbenchmarks, each timed on the card in TURBO by
; the Phasor's timers, then shown on the 80-column text screen with
; a2vm's f121 prediction beside each (gen/calibpred.inc, written by
; tools/native/calibdisk.py from an a2vm run of this same program): the
; first 44 on text page 1, the memory API's 8 on text page 2 (both are
; written after a run; SPACE shows the other one). Key R runs the list
; again; CTRL-RESET reboots (the program leaves ProDOS's card overwritten
; and its reset vector invalid, so the //e boots cold).
;
; The time base. Timer 1 of the Phasor's VIA-B, free-running with the
; latch $FFFE, counts Apple bus cycles (1,015,625 a second on PAL,
; 1,020,484 on NTSC) with a period of exactly 65,536. Each measurement
; reads it at its start and at its end only, the low byte then the high
; byte as the music disk does, and the low byte again: a read whose two
; low bytes show a wrap of the low byte is taken again (the high byte
; may have stepped in between). The wrap of the counter itself: VIA-A's
; timer 1 runs beside it free with the latch $FEFE, a period of 65,280,
; read the same way just after; the two elapsed counts differ by 256 for
; every 65,536 cycles, so the number of VIA-B wraps is the difference / 256
; rounded, and the elapsed time E is that number x 65,536 + VIA-B's count
; (up to 254 wraps, 16 s; a difference that is not a multiple of 256 within
; DELTA_MAX marks the measurement bad). Every timer read is a slot-4
; access, which opens the slowdown window (512 CPU cycles at 1 MHz by
; default, 32 with the DOOM profile). Each operation is measured twice, n
; and 2n times in the same loop, and its time is (E(2n) - E(n)) / n: the
; reads and their window cancel exactly, and the counts are chosen so that
; E(n) is about 55,000 bus cycles on a2vm f121, where the reads' window
; is under 1% of it. Interrupts stay masked throughout.
;
; The operations (the table below; docs/results/calib.md says what each
; measures): the CPU and memory baselines, RamWorks reads and writes (bank
; 16) with the line cache's hits and misses apart, far_gcopy, far_pload,
; far_get and far_put, the object API's page-1 window copy, the soft
; switches each followed by code run from main, an SHR write burst and its
; drain, the slot-4 window, and the memory API's PRIVATE copy from a
; RamWorks bank into main (appletini-one README_MEMORY_API.md: one request
; through slot 7's FIFO, as lload.s's am_send sends one) at $2000, the
; colormaps' place in the game, and at $6000. The game's own routines are not
; reassembled: calibdisk.py copies their bytes from the play build (far.s's
; far area of the card, the kernel's far_gcopy, gobj.s's page-1 window)
; into gen/*.bin, and this program puts them back at the addresses the
; game runs them from, so the card times exactly the code the game runs.
;
; A read whose low bytes wrapped is taken again, about 15 bus cycles
; later: E moves by that much (0.03% of a measurement) when the start's or
; the end's read is retaken, and the two timers' counts differ by it when
; VIA-A's is (within DELTA_MAX). An operation whose unit is bound to the
; bus (a soft switch, a slot-4 read) takes a whole number of bus cycles,
; or alternates between two: its figure depends on where its code falls
; against the bus cycle, on the card as on a2vm.
;
; The results stay in memory for the host (res: a record of 64 bytes an
; operation, the timer reads included; g_*): calibdisk.py reads them from
; a2vm's snapshot and checks the screen against its own computation from
; the timer reads.

        .setcpu "65C02"
        .macpack longbranch
        .include "calibplay.inc"        ; the play build's addresses (gen)

; ---------------------------------------------------------------------------
; The machine
; ---------------------------------------------------------------------------
KBD         = $C000
KBDSTRB     = $C010
STORE80ON   = $C001
RAMRDOFF    = $C002
RAMRDON     = $C003
RAMWRTOFF   = $C004
RAMWRTON    = $C005
ALTZPOFF    = $C008
ALTZPON     = $C009
COL80ON     = $C00D
RDVBLBAR    = $C019
TXTSET      = $C051
MIXCLR      = $C052
TXTPAGE1    = $C054
TXTPAGE2    = $C055
LORES       = $C056
RWBANK      = $C073
LCBANK1     = $C08B             ; read twice: bank 1 RAM, read and write
SOFTEV_HI   = $03F3             ; the reset vector's high byte and its
PWREDUP     = $03F4             ;   check byte

VIA_A_DDRA  = $C413             ; VIA-A (in both card modes: address bit 4)
VIA_A_T1CL  = $C414
VIA_A_T1CH  = $C415
VIA_A_T1LL  = $C416
VIA_A_T1LH  = $C417
VIA_A_ACR   = $C41B
VIA_A_IFR   = $C41D
VIA_A_IER   = $C41E
VIA_B_T1CL  = $C484             ; VIA-B (address bit 7, bit 4 clear)
VIA_B_T1CH  = $C485
VIA_B_T1LL  = $C486
VIA_B_T1LH  = $C487
VIA_B_ACR   = $C48B
VIA_B_IFR   = $C48D
VIA_B_IER   = $C48E
ACR_FREE    = $40               ; timer 1 free-running, no PB7

BPS_PAL     = 984615            ; ps a bus cycle: 1,015,625 Hz
BPS_NTSC    = 979927            ;                 1,020,484 Hz
PAL_CUT     = 18655             ; a frame: 20,280 bus cycles PAL, 17,030 NTSC
DELTA_MAX   = 24                ; the two timers' counts may differ by this

; the buffers (main, aux bank 0 and RamWorks bank 16 alike)
BUF         = $A000             ; 16 pages: the streams, the copies
STRIDE      = $8000             ; the scattered reads and writes
RWB         = 16                ; the RamWorks bank
SHR         = $2000             ; aux bank 0: the SHR pixels
RWS         = 17                ; the memory API's source bank: a copy of
                                ;   main's bytes made before each timing,
                                ;   so the copies rewrite main's bytes
                                ;   with the same bytes

; the memory API's raw FIFO transport in slot 7 (appletini-one
; README_MEMORY_API.md section 7)
SP_DATA     = $CFF0
SP_CTRL     = $CFF1
SP_POP      = $CFF2
SP_RELEASE  = $CFFF
SP_ROM      = $C700
INTCXROMOFF = $C006
STORE80OFF  = $C000             ; (a write)
AMEM_TIMEOUT = $6F              ; (ours: no reply came)
REQ_LEN     = 36                ; a request of one descriptor: 10 + 2 + 24
RQ_FLAGS    = 21                ; the descriptor's flags, source (space,
RQ_SRCSP    = 22                ;   bank, address), destination (space,
RQ_SRCB     = 23                ;   bank, address), byte count
RQ_SRC      = 24
RQ_DSTSP    = 26
RQ_DSTB     = 27
RQ_DST      = 28
RQ_SIZE     = 30

; the counts of nominal 65C02 cycles of one unit of REG and SPIN, the
; driver's loop included (calibdisk.py checks them on a2vm's core)
UC_REG      = 1313
UC_SPIN     = 837

; the operations the header uses (their places in the table, OPS)
OP_REG      = 0
OP_SPIN     = 20
OP_WIN      = 21
OP_PR       = 44                ; the first of the memory API's (page 2)

; ---------------------------------------------------------------------------
; Zero page (FA_* at $00-$05 are the far layer's, calibplay.inc)
; ---------------------------------------------------------------------------
        .zeropage
m_a:    .res 8          ; the 64-bit arithmetic: m_r = m_a x m_b,
m_b:    .res 8          ;   m_r = round(m_a / m_b)
m_r:    .res 8
m_t:    .res 8
m_u:    .res 8
cnt:    .res 2          ; units left in a measurement
opx:    .res 1          ; the operation
ncur:   .res 2          ; its n
mode:   .res 1          ; its window: bit 0 RAMRD, bit 1 RAMWRT
bank:   .res 1          ;   on this bank
rec:    .res 2          ; its result record
txt:    .res 2          ; a string
col:    .res 1          ; the text cursor
row:    .res 1
scr:    .res 2
ts:     .res 8          ; the start's reads (VIA-B, VIA-A), the end's
eb:     .res 2          ; VIA-B's elapsed count
ea:     .res 2          ; VIA-A's
xx:     .res 2          ; their difference, mod 65,280
qq:     .res 1          ; VIA-B's wraps
dlt:    .res 1          ; the difference less 256 qq (signed)
el:     .res 4          ; E
eerr:   .res 1          ; 1: the two timers disagree
nums:   .res 8          ; D x a bus cycle (ps)
den:    .res 8
tmp:    .res 4
dig:    .res 10
wid:    .res 1
video:  .res 1          ; 0 PAL, $80 NTSC
tptr:   .res 2
am_err: .res 1          ; the memory API's lines: a request's result
am_w:   .res 1          ; the transport's wait

        .exportzp opx, cnt, am_err

; ---------------------------------------------------------------------------
; The results (main $1000: the host reads them)
; ---------------------------------------------------------------------------
NOPS    = 52
NOPS1   = 44            ; the lines of page 1 (the rest: page 2)
R_E1    = 0             ; E(n), bus cycles (4 bytes)
R_E2    = 4             ; E(2n)
R_D     = 8             ; E(2n) - E(n)
R_V     = 12            ; ns an operation
R_VB    = 16            ; ns a byte (0: none)
R_ERR   = 20            ; bit 0 E(n) bad, bit 1 E(2n) bad, bit 2 D <= 0
R_DLT1  = 21            ; the timers' difference in E(n), E(2n)
R_DLT2  = 22
R_N     = 24            ; the n the arithmetic used (2 bytes)
R_TS1   = 32            ; E(n)'s timer reads: the start's VIA-B, VIA-A,
R_TS2   = 40            ;   the end's (8 bytes); E(2n)'s
R_SIZE  = 64

        .segment "BSS"
res:    .res NOPS * R_SIZE
g_bps:  .res 4          ; ps a bus cycle
g_vbl:  .res 4          ; a frame, bus cycles (E)
g_verr: .res 1
g_w10:  .res 4          ; the slot-4 window, tenths of a CPU cycle
g_wbad: .res 1          ; 1: no window could be computed
g_mhz:  .res 4          ; the CPU, hundredths of a MHz (REG)
g_runs: .res 1          ; runs so far
g_tts:  .res 8          ; the whole run's timer reads (its start, its end)
g_time: .res 4          ; the whole run, bus cycles (E)
g_terr: .res 1
g_tms:  .res 4          ; the whole run, ms
g_done: .res 1          ; 1 once the screen shows a run
strb:   .res 16
try:    .res 8
w_ds:   .res 8          ; SPIN's D, WIN's D
w_dw:   .res 8
g_amem: .res 1          ; the memory API's probe: 0 there, else why not
g_page: .res 1          ; the text page shown (0: 1, 1: 2)
pr_d:   .res 1          ; a PRIVATE line's setup: the destination's page,
pr_sz:  .res 2          ;   a request's bytes, the requests, the next
pr_cnt: .res 1          ;   request's address
pr_lo:  .res 1
pr_hi:  .res 1
q_req:  .res 8 * REQ_LEN        ; the requests
q_snap: .res REQ_LEN            ; the setup's copy of main into RWS
q_caps: .res 32                 ; the probe's answer
        .export res, g_bps, g_vbl, g_verr, g_w10, g_wbad, g_mhz, g_runs
        .export g_tts, g_time, g_terr, g_tms
        .export g_done, g_amem, q_req, q_snap

; ---------------------------------------------------------------------------
; Macros
; ---------------------------------------------------------------------------
.macro ZERO8 dst
        .repeat 8, I
        stz dst + I
        .endrep
.endmacro

.macro COPY8 dst, src
        .repeat 8, I
        lda src + I
        sta dst + I
        .endrep
.endmacro

; dst (8 bytes) = a 32-bit constant
.macro LOAD8 dst, value
        .repeat 4, I
        lda #<((value) >> (I * 8))
        sta dst + I
        .endrep
        .repeat 4, I
        stz dst + 4 + I
        .endrep
.endmacro

; dst (8 bytes) = the 4 bytes at src
.macro LOAD4 dst, src
        .repeat 4, I
        lda src + I
        sta dst + I
        .endrep
        .repeat 4, I
        stz dst + 4 + I
        .endrep
.endmacro

; SUB8: dst (8 bytes) = left - right; carry clear: below 0
.macro SUB8 dst, left, right
        sec
        .repeat 8, I
        lda left + I
        sbc right + I
        sta dst + I
        .endrep
.endmacro

; dst (8 bytes) = operation op's n
.macro LOADN dst, op
        lda op_n_lo + op
        sta dst
        lda op_n_hi + op
        sta dst + 1
        .repeat 6, I
        stz dst + 2 + I
        .endrep
.endmacro

; dst (8 bytes) = the 2 bytes at src
.macro LOAD2 dst, src
        lda src
        sta dst
        lda src + 1
        sta dst + 1
        .repeat 6, I
        stz dst + 2 + I
        .endrep
.endmacro

; ---------------------------------------------------------------------------
; The start (main $2000)
; ---------------------------------------------------------------------------
        .segment "CODE"
        .import __LCCODE_LOAD__, __LCCODE_RUN__, __LCCODE_SIZE__
        .export start, done, crash

start:  sei
        cld
        ldx #$FF
        txs
        lda LCBANK1             ; the card: bank 1 RAM, read and write
        lda LCBANK1
        lda #<__LCCODE_LOAD__   ; this program's card part to $E000
        ldx #>__LCCODE_LOAD__
        ldy #>__LCCODE_RUN__
        jsr cp_setup
        lda #>(__LCCODE_SIZE__ + $FF)
        jsr cp_pages
        lda #<pay_far           ; the far area of the play build's card
        ldx #>pay_far
        ldy #>FAR_LO
        jsr cp_setup
        lda #>FAR_LEN
        jsr cp_pages
        ldx #KERN_LEN - 1       ; the kernel's far_gcopy
:       lda pay_kern,x
        sta KERN_LO,x
        dex
        bpl :-
        ldx #PW_LEN - 1         ; gobj.s's window code into page 1
:       lda pay_pw,x
        sta PW_GO,x
        dex
        bpl :-
        lda #<crash_brk         ; the vectors: everything is a crash
        sta $FFFA
        sta $FFFE
        lda #>crash_brk
        sta $FFFB
        sta $FFFF
        lda #<start
        sta $FFFC
        lda #>start
        sta $FFFD
        lda SOFTEV_HI           ; CTRL-RESET boots cold: the check byte
        eor #$A5 ^ $01          ;   never matches
        sta PWREDUP
        sta TXTSET              ; 80-column text, page 1; HIRES off (with
        sta MIXCLR              ;   80STORE, HIRES would make $2000-$3FFF
        sta LORES               ;   follow PAGE2, not RAMWRT)
        sta TXTPAGE1
        sta STORE80ON
        sta COL80ON
        jsr timer_check
        bcc :+
        lda #<s_notimer
        ldx #>s_notimer
        jmp stop_msg
:       jsr timers_on
        stz g_runs
        jsr detect_all          ; the video standard, the memory API
run_all:
        stz g_done
        inc g_runs
        jsr cls_p1
        lda #<s_measuring
        ldx #>s_measuring
        jsr put_str_at0
        ldx #0                  ; the whole run's start
        jsr t_read
        ldx #3
:       lda ts,x
        sta g_tts,x
        dex
        bpl :-
        ldx #0
@op:    phx
        jsr run_opx
        plx
        inx
        cpx #NOPS
        bne @op
        ldx #4                  ; its end
        jsr t_read
        ldx #3
:       lda g_tts,x
        sta ts,x
        lda ts + 4,x
        sta g_tts + 4,x
        dex
        bpl :-
        jsr t_elapsed
        ldx #3
:       lda el,x
        sta g_time,x
        dex
        bpl :-
        lda eerr
        sta g_terr
        jsr calc_globals
        jsr show_all
        lda #1
        sta g_done
done:   lda KBD                 ; (a2vm's run stops here)
        bpl done
        sta KBDSTRB
        jmp on_key              ; R: again; SPACE: the other page
        .res 6, $EA             ; (unused: the units keep the addresses
                                ;   of the disk the card measured)

; cp_setup: m_u = A:X (source), m_u+2 = Y:00 (destination); cp_pages: A
; pages from the one to the other
cp_setup:
        sta m_u
        stx m_u + 1
        stz m_u + 2
        sty m_u + 3
        rts
cp_pages:
        tax
        ldy #0
:       lda (m_u),y
        sta (m_u + 2),y
        iny
        bne :-
        inc m_u + 1
        inc m_u + 3
        dex
        bne :-
        rts

; timer_check: carry clear when slot 4 has both VIAs' timer 1: their
; latches hold what is written ($55AA, then $AA55), as music.s checks
timer_check:
        ldx #$55
        jsr @try
        bcs @done
        ldx #$AA
@try:   stx VIA_B_T1LL
        stx VIA_A_T1LL
        txa
        eor #$FF
        sta VIA_B_T1LH
        sta VIA_A_T1LH
        cpx VIA_B_T1LL
        bne @none
        cpx VIA_A_T1LL
        bne @none
        cmp VIA_B_T1LH
        bne @none
        cmp VIA_A_T1LH
        bne @none
        clc
@done:  rts
@none:  sec
        rts

; timers_on: VIA-B's and VIA-A's timer 1 free-running, latches $FFFE and
; $FEFE, their interrupts off
timers_on:
        lda #$7F
        sta VIA_B_IER
        sta VIA_A_IER
        lda #ACR_FREE
        sta VIA_B_ACR
        sta VIA_A_ACR
        lda #$FE
        sta VIA_B_T1LL
        lda #$FF
        sta VIA_B_T1CH          ; latch $FFFE: loaded, counting
        lda #$FE
        sta VIA_A_T1LL
        sta VIA_A_T1CH          ; latch $FEFE
        lda #$7F
        sta VIA_B_IFR
        sta VIA_A_IFR
        rts

; detect_video: one frame (a blanking's start to the next) on the timers;
; PAL above PAL_CUT bus cycles
detect_video:
        jsr vbl_start
        jsr vbl_start
        ldx #0
        jsr t_read
        jsr vbl_start
        ldx #4
        jsr t_read
        jsr t_elapsed
        ldx #3
:       lda el,x
        sta g_vbl,x
        dex
        bpl :-
        lda eerr
        sta g_verr
        stz video
        ldx #3
:       lda bps_pal,x
        sta g_bps,x
        dex
        bpl :-
        lda el
        cmp #<PAL_CUT
        lda el + 1
        sbc #>PAL_CUT
        lda el + 2
        sbc #0
        bcs @pal
        lda #$80
        sta video
        ldx #3
:       lda bps_ntsc,x
        sta g_bps,x
        dex
        bpl :-
@pal:   rts
bps_pal:
        .dword BPS_PAL
bps_ntsc:
        .dword BPS_NTSC

vbl_start:
:       bit RDVBLBAR            ; in a blanking: to its end
        bpl :-
:       bit RDVBLBAR            ; the display: to the blanking
        bmi :-
        rts

; ---------------------------------------------------------------------------
; One operation: E(n), E(2n), D and the figures. X = the operation
; ---------------------------------------------------------------------------
run_op:
        stx opx
        txa
        jsr rec_of
        ldx opx
        lda op_n_lo,x
        sta ncur
        lda op_n_hi,x
        sta ncur + 1
        lda op_mode,x
        sta mode
        lda op_bank,x
        sta bank
        lda op_setup_lo,x       ; the driver's two calls
        sta m_setup + 1
        lda op_setup_hi,x
        sta m_setup + 2
        lda op_unit_lo,x
        sta m_call + 1
        lda op_unit_hi,x
        sta m_call + 2
        ; E(n)
        lda ncur
        sta cnt
        lda ncur + 1
        sta cnt + 1
        jsr measure
        ldy #R_TS1
        jsr store_ts
        ldy #R_E1
        jsr store_e
        lda dlt
        ldy #R_DLT1
        sta (rec),y
        lda eerr
        ldy #R_ERR
        sta (rec),y
        ; E(2n)
        lda ncur
        asl a                   ; (2n: the second measure)
        sta cnt
        lda ncur + 1
        rol a
        sta cnt + 1
        jsr measure
        ldy #R_TS2
        jsr store_ts
        ldy #R_E2
        jsr store_e
        lda dlt
        ldy #R_DLT2
        sta (rec),y
        lda eerr
        asl a
        ldy #R_ERR
        ora (rec),y
        sta (rec),y
        ldy #R_N
        lda ncur
        sta (rec),y
        iny
        lda ncur + 1
        sta (rec),y
        jmp calc_op

; store_ts: the timer reads (ts) at rec + Y
store_ts:
        ldx #0
:       lda ts,x
        sta (rec),y
        iny
        inx
        cpx #8
        bne :-
        rts

; store_e: E (el) at rec + Y
store_e:
        ldx #0
:       lda el,x
        sta (rec),y
        iny
        inx
        cpx #4
        bne :-
        rts

; calc_op: D = E(2n) - E(n); V = round(D x bps / (n k 1000)); VB the same
; over b bytes an operation
calc_op:
        ldy #R_E2
        jsr ld_tmp
        ldy #R_E1
        sec
        .repeat 4, I
        lda tmp + I
        sbc (rec),y
        sta tmp + I
        iny
        .endrepeat
        ldy #R_D
        ldx #0
:       lda tmp,x
        sta (rec),y
        iny
        inx
        cpx #4
        bne :-
        lda tmp + 3             ; D <= 0: bad
        bmi @bad
        ora tmp + 2
        ora tmp + 1
        ora tmp
        bne @good
@bad:   ldy #R_ERR
        lda (rec),y
        ora #4
        sta (rec),y
@good:  LOAD4 m_a, tmp          ; nums = D x bps
        LOAD4 m_b, g_bps
        jsr mul64
        COPY8 nums, m_r
        LOAD2 m_a, ncur         ; den = n x k x 1000
        ldx opx
        lda op_k_lo,x
        sta m_b
        lda op_k_hi,x
        sta m_b + 1
        .repeat 6, I
        stz m_b + 2 + I
        .endrep
        jsr mul64
        COPY8 m_a, m_r
        LOAD8 m_b, 1000
        jsr mul64
        COPY8 den, m_r
        COPY8 m_a, nums
        COPY8 m_b, den
        jsr divr64
        ldy #R_V
        jsr store_r4
        ldx opx
        lda op_b_lo,x
        ora op_b_hi,x
        bne :+
        jmp @nob
:
        COPY8 m_a, den          ; den x b
        lda op_b_lo,x
        sta m_b
        lda op_b_hi,x
        sta m_b + 1
        .repeat 6, I
        stz m_b + 2 + I
        .endrep
        jsr mul64
        COPY8 m_b, m_r
        COPY8 m_a, nums
        jsr divr64
        ldy #R_VB
        jmp store_r4
@nob:   ldy #R_VB
        lda #0
        sta (rec),y
        iny
        sta (rec),y
        iny
        sta (rec),y
        iny
        sta (rec),y
        rts

; store_r4: m_r's 4 low bytes at rec + Y (a quotient past 32 bits: $FFFFFFFF)
store_r4:
        lda m_r + 4
        ora m_r + 5
        ora m_r + 6
        ora m_r + 7
        beq :+
        lda #$FF
        sta m_r
        sta m_r + 1
        sta m_r + 2
        sta m_r + 3
:       ldx #0
:       lda m_r,x
        sta (rec),y
        iny
        inx
        cpx #4
        bne :-
        rts

; ---------------------------------------------------------------------------
; The globals: the CPU's speed (REG) and the slot-4 window (SPIN, WIN)
; ---------------------------------------------------------------------------
; rec_of: rec = the record of operation A (0-63: 64 A, carry from 8 A on)
rec_of:
        stz rec + 1
        asl a
        asl a
        asl a
        rol rec + 1
        asl a
        rol rec + 1
        asl a
        rol rec + 1
        asl a
        rol rec + 1
        clc
        adc #<res
        sta rec
        lda rec + 1
        adc #>res
        sta rec + 1
        rts

; ld_d: m_a = D of rec (8 bytes)
ld_d:   ldy #R_D
        ldx #0
:       lda (rec),y
        sta m_a,x
        iny
        inx
        cpx #4
        bne :-
        stz m_a + 4
        stz m_a + 5
        stz m_a + 6
        stz m_a + 7
        rts

calc_globals:
        ; the run in ms = round(E bps / 10^9)
        LOAD4 m_a, g_time
        LOAD4 m_b, g_bps
        jsr mul64
        COPY8 m_a, m_r
        LOAD8 m_b, 1000000000
        jsr divr64
        ldx #3
:       lda m_r,x
        sta g_tms,x
        dex
        bpl :-
        ; MHz x 100 = round(n UC_REG 10^8 / (D bps))
        lda #OP_REG
        jsr rec_of
        jsr ld_d
        LOAD4 m_b, g_bps
        jsr mul64
        COPY8 den, m_r
        ldx #OP_REG
        lda op_n_lo,x
        sta m_a
        lda op_n_hi,x
        sta m_a + 1
        .repeat 6, I
        stz m_a + 2 + I
        .endrep
        LOAD8 m_b, UC_REG * 100000
        jsr mul64
        COPY8 m_a, m_r
        LOAD8 m_b, 1000
        jsr mul64
        COPY8 m_a, m_r
        COPY8 m_b, den
        jsr divr64
        ldx #3
:       lda m_r,x
        sta g_mhz,x
        dex
        bpl :-
        ; the window: with t = D / n a unit of SPIN (s) or WIN (w),
        ; W = (tw - ts - 1) / (1 - ts / UC_SPIN), in CPU cycles: the slot-4
        ; read's own bus cycle (1) aside, the window's W cycles at 1 MHz less
        ; the time TURBO would have run them in. W x 10 =
        ; round(10 UC (Dw ns - Ds nw - nw ns) / (nw (UC ns - Ds))), 0 below 0
        stz g_wbad
        lda #OP_SPIN
        jsr rec_of
        jsr ld_d
        COPY8 w_ds, m_a
        lda #OP_WIN
        jsr rec_of
        jsr ld_d
        COPY8 w_dw, m_a
        COPY8 m_a, w_dw         ; m_u = Dw ns
        LOADN m_b, OP_SPIN
        jsr mul64
        COPY8 m_u, m_r
        COPY8 m_a, w_ds         ;   - Ds nw
        LOADN m_b, OP_WIN
        jsr mul64
        SUB8 m_u, m_u, m_r
        bcs :+
        jmp @zero
:       LOADN m_a, OP_WIN       ;   - nw ns
        LOADN m_b, OP_SPIN
        jsr mul64
        SUB8 m_u, m_u, m_r
        bcs :+
        jmp @zero
:       LOADN m_a, OP_SPIN      ; den = (UC ns - Ds) nw
        LOAD8 m_b, UC_SPIN
        jsr mul64
        SUB8 m_a, m_r, w_ds
        bcs :+
        jmp @bad
:       LOADN m_b, OP_WIN
        jsr mul64
        COPY8 den, m_r
        lda #0
        .repeat 8, I
        ora den + I
        .endrep
        bne :+
        jmp @bad
:       COPY8 m_a, m_u          ; num = 10 UC m_u
        LOAD8 m_b, 10 * UC_SPIN
        jsr mul64
        COPY8 m_a, m_r
        COPY8 m_b, den
        jsr divr64
        ldx #3
:       lda m_r,x
        sta g_w10,x
        dex
        bpl :-
        rts
@bad:   lda #1
        sta g_wbad
@zero:  stz g_w10
        stz g_w10 + 1
        stz g_w10 + 2
        stz g_w10 + 3
        rts

; ---------------------------------------------------------------------------
; 64-bit arithmetic
; ---------------------------------------------------------------------------
; mul64: m_r = m_a x m_b (the low 64 bits); m_a, m_b are consumed
mul64:  ZERO8 m_r
        ldy #64
@bit:   lsr m_b + 7
        .repeat 7, I
        ror m_b + 6 - I
        .endrepeat
        bcc @shift
        clc
        .repeat 8, I
        lda m_r + I
        adc m_a + I
        sta m_r + I
        .endrepeat
@shift: asl m_a
        .repeat 7, I
        rol m_a + 1 + I
        .endrepeat
        dey
        bne @bit
        rts

; divr64: m_r = round(m_a / m_b) (halves up), m_b not 0; m_a, m_t are
; consumed
divr64: COPY8 m_t, m_b          ; m_a += m_b / 2
        lsr m_t + 7
        .repeat 7, I
        ror m_t + 6 - I
        .endrepeat
        clc
        .repeat 8, I
        lda m_a + I
        adc m_t + I
        sta m_a + I
        .endrepeat
        ZERO8 m_t               ; m_t: the remainder; m_a: the quotient
        ldy #64
@bit:   asl m_a
        .repeat 7, I
        rol m_a + 1 + I
        .endrepeat
        .repeat 8, I
        rol m_t + I
        .endrepeat
        sec                     ; try m_t - m_b
        .repeat 8, I
        lda m_t + I
        sbc m_b + I
        sta try + I
        .endrepeat
        bcc @next
        COPY8 m_t, try
        inc m_a                 ; (bit 0 is 0 after the shift)
@next:  dey
        beq @done
        jmp @bit
@done:  COPY8 m_r, m_a
        rts

; ---------------------------------------------------------------------------
; The screen: 80 columns, row 0 the machine, row 1 the heads, rows 2-23
; the operations (0-21 left, 22-43 right): a name, the card's us an
; operation, us a byte, a2vm f121's us an operation. Text page 2 holds
; operations 44-51 (show2, below)
; ---------------------------------------------------------------------------
cls:    ldy #23
@row:   sty row
        lda rowlo,y
        sta scr
        lda rowhi,y
        sta scr + 1
        ldy #39
        lda #$A0
:       sta (scr),y             ; main (the odd columns)
        dey
        bpl :-
        sta TXTPAGE2
        ldy #39
:       sta (scr),y             ; aux (the even ones)
        dey
        bpl :-
        sta TXTPAGE1
        ldy row
        dey
        bpl @row
        rts

; put_char: A (ASCII) at col, row; col + 1
put_char:
        ora #$80
        pha
        ldy row
        lda rowlo,y
        sta scr
        lda rowhi,y
        sta scr + 1
        lda col
        lsr a
        tay
        pla
        bcs @main
        sta TXTPAGE2
        sta (scr),y
        sta TXTPAGE1
        bra @next
@main:  sta (scr),y
@next:  inc col
        rts

; put_str: the string at A:X (0 ends it) from col, row
put_str:
        sta txt
        stx txt + 1
        lda #0
@next:  pha
        tay
        lda (txt),y
        beq @done
        jsr put_char
        pla
        inc a
        bra @next
@done:  pla
        rts

put_str_at0:
        stz col
        stz row
        jmp put_str

; put_spaces: X spaces
put_spaces:
        cpx #0
        beq @done
:       lda #' '
        phx
        jsr put_char
        plx
        dex
        bne :-
@done:  rts

; put_fix: the 32-bit value at tmp, thousandths, as d.ddd right-aligned
; in wid columns (more when it needs them)
put_fix:
        ldx #9                  ; ten digits, the last first
@digit: phx
        jsr div10
        plx
        sta dig,x
        dex
        bpl @digit
        ldx #0                  ; the integer part from its first digit
:       lda dig,x               ;   that is not 0 (its last digit always)
        bne :+
        inx
        cpx #6
        bne :-
:       ldy #0
:       lda dig,x
        ora #'0'
        sta strb,y
        iny
        inx
        cpx #7
        bne :-
        lda #'.'
        sta strb,y
        iny
:       lda dig,x
        ora #'0'
        sta strb,y
        iny
        inx
        cpx #10
        bne :-
        lda #0
        sta strb,y
        sec                     ; the padding: wid - the length
        lda wid
        sty wid
        sbc wid
        bcc :+
        tax
        jsr put_spaces
:       lda #<strb
        ldx #>strb
        jmp put_str

; put_int: the 32-bit value at tmp as an integer (no padding)
put_int:
        ldx #9
@digit: phx
        jsr div10
        plx
        sta dig,x
        dex
        bpl @digit
        ldx #0
:       lda dig,x
        bne :+
        inx
        cpx #9
        bne :-
:       lda dig,x
        ora #'0'
        phx
        jsr put_char
        plx
        inx
        cpx #10
        bne :-
        rts

; div10: tmp = tmp / 10, A = the remainder
div10:  lda #0
        ldx #32
@bit:   asl tmp
        rol tmp + 1
        rol tmp + 2
        rol tmp + 3
        rol a
        cmp #10
        bcc :+
        sbc #10
        inc tmp
:       dex
        bne @bit
        rts

; ld_tmp: tmp = the 4 bytes at rec + Y
ld_tmp: ldx #0
:       lda (rec),y
        sta tmp,x
        iny
        inx
        cpx #4
        bne :-
        rts

show:   jsr cls
        stz col                 ; row 0: the machine
        stz row
        lda #<s_head
        ldx #>s_head
        jsr put_str
        lda #<s_pal
        ldx #>s_pal
        bit video
        bpl :+
        lda #<s_ntsc
        ldx #>s_ntsc
:       jsr put_str
        lda #' '                ; its frame, bus cycles
        jsr put_char
        ldx #3
:       lda g_vbl,x
        sta tmp,x
        dex
        bpl :-
        jsr put_int
        lda #<s_window
        ldx #>s_window
        jsr put_str
        jsr show_window
        lda #<s_cpu
        ldx #>s_cpu
        jsr put_str
        ldx #3                  ; MHz: hundredths, shown as tenths of
:       lda g_mhz,x             ;   thousandths (x.xx0)
        sta tmp,x
        dex
        bpl :-
        jsr times10
        lda #0
        sta wid
        jsr put_fix
        lda #<s_mhz
        ldx #>s_mhz
        jsr put_str
        lda #<s_time            ; the whole run, s
        ldx #>s_time
        jsr put_str
        lda g_terr
        beq @time
        lda #'?'
        jsr put_char
        bra @secs
@time:  ldx #3
:       lda g_tms,x
        sta tmp,x
        dex
        bpl :-
        lda #0
        sta wid
        jsr put_fix
@secs:  lda #<s_secs
        ldx #>s_secs
        jsr put_str
        lda #<s_run
        ldx #>s_run
        jsr put_str
        lda g_runs
        sta tmp
        stz tmp + 1
        stz tmp + 2
        stz tmp + 3
        jsr put_int
        lda #<s_again
        ldx #>s_again
        jsr put_str
        stz col                 ; row 1: the heads
        lda #1
        sta row
        lda #<s_cols
        ldx #>s_cols
        jsr put_str
        lda #40
        sta col
        lda #<s_cols
        ldx #>s_cols
        jsr put_str
        ldx #0                  ; rows 2-23
@op:    phx
        jsr show_op
        plx
        inx
        cpx #NOPS1
        bne @op
        rts

; times10: tmp = tmp x 10
times10:
        ldx #3
:       lda tmp,x
        sta m_a,x
        stz m_a + 4,x
        dex
        bpl :-
        LOAD8 m_b, 10
        jsr mul64
        ldx #3
:       lda m_r,x
        sta tmp,x
        dex
        bpl :-
        rts

; show_window: 512, 32, NONE, or the window in whole cycles (W x 10 / 10,
; rounded); ? when it could not be computed
show_window:
        lda g_wbad
        beq :+
        lda #<s_wbad
        ldx #>s_wbad
        jmp put_str
:       lda g_w10 + 2
        ora g_w10 + 3
        bne @figure
        lda #>4800              ; 480.0-540.0: the default
        ldy #<4800
        jsr w10_ge
        bcc @w32
        lda #>5401
        ldy #<5401
        jsr w10_ge
        bcs @w32
        lda #<s_w512
        ldx #>s_w512
        bra @named
@w32:   lda #>240               ; 24.0-44.0: the DOOM profile's
        ldy #<240
        jsr w10_ge
        bcc @w0
        lda #>441
        ldy #<441
        jsr w10_ge
        bcs @w0
        lda #<s_w32
        ldx #>s_w32
        bra @named
@w0:    lda #>50                ; below 5.0: no window
        ldy #<50
        jsr w10_ge
        bcs @figure
        lda #<s_w0
        ldx #>s_w0
@named: jmp put_str
@figure:
        clc                     ; (W x 10 + 5) / 10
        lda g_w10
        adc #5
        sta tmp
        .repeat 3, I
        lda g_w10 + 1 + I
        adc #0
        sta tmp + 1 + I
        .endrep
        jsr div10
        jmp put_int

; w10_ge: carry set when g_w10 (16 bits) >= A:Y (A high)
w10_ge: sta tptr + 1
        sty tptr
        lda g_w10
        cmp tptr
        lda g_w10 + 1
        sbc tptr + 1
        rts

; show_op: operation X's line
show_op:
        stx opx
        txa
        ldy #0                  ; its column: 0 or 40, row 2 + X mod 22
        sec
        sbc #22
        bcc :+
        ldy #40
        bra :++
:       txa
:       clc
        adc #2
        sta row
        sty col
show_at:                        ; (page 2's lines: opx, row, col set)
        lda opx
        jsr rec_of
        lda opx                 ; the name: op_names + 8 X
        stz tptr + 1
        asl a
        asl a
        rol tptr + 1
        asl a
        rol tptr + 1
        clc
        adc #<op_names
        sta tptr
        lda tptr + 1
        adc #>op_names
        sta tptr + 1
        ldy #0
:       lda (tptr),y
        phy
        jsr put_char
        ply
        iny
        cpy #8
        bne :-
        ldy #R_ERR
        lda (rec),y
        beq @good
        lda #<s_err
        ldx #>s_err
        jsr put_str
        bra @pred
@good:  ldy #R_V                ; us an operation
        jsr ld_tmp
        lda #9
        sta wid
        jsr put_fix
        ldy #R_VB               ; us a byte
        jsr ld_tmp
        lda tmp
        ora tmp + 1
        ora tmp + 2
        ora tmp + 3
        beq @nob
        lda #7
        sta wid
        jsr put_fix
        bra @pred
@nob:   ldx #7
        jsr put_spaces
@pred:  lda opx                 ; a2vm f121's
        asl a
        asl a
        tax
        lda pred_v,x
        sta tmp
        lda pred_v + 1,x
        sta tmp + 1
        lda pred_v + 2,x
        sta tmp + 2
        lda pred_v + 3,x
        sta tmp + 3
        ora tmp + 2
        ora tmp + 1
        ora tmp
        beq @none
        lda #10
        sta wid
        jmp put_fix
@none:  ldx #9
        jsr put_spaces
        lda #'-'
        jmp put_char

; the text rows' addresses
rowlo:  .repeat 24, R
        .byte <($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep
rowhi:  .repeat 24, R
        .byte >($0400 + (R .mod 8) * $80 + (R / 8) * $28)
        .endrep

        .segment "RODATA"
s_measuring:
        .byte "CALIB: MEASURING (ABOUT 10 S)", 0
s_head: .byte "CALIB ", 0
s_pal:  .byte "PAL", 0
s_ntsc: .byte "NTSC", 0
s_window:
        .byte "  WIN ", 0
s_cpu:  .byte "  CPU ", 0
s_mhz:  .byte " MHZ", 0
s_time: .byte "  TIME ", 0
s_secs: .byte " S", 0
s_run:  .byte "  RUN ", 0
s_again:
        .byte "  SPACE: MORE", 0
s_cols: .byte "OP          US/OP   US/B A2VM F121", 0
s_err:  .byte "      ERR       ", 0
s_wbad: .byte "?", 0
s_w512: .byte "512", 0
s_w32:  .byte "32", 0
s_w0:   .byte "NONE", 0

; ---------------------------------------------------------------------------
; The operations
; ---------------------------------------------------------------------------
; M_RD, M_WR: the driver's window around the whole measurement (RAMRD or
; RAMWRT on, RWBANK = the operation's bank), for the loops of this
; program that read or write another bank; the game's routines open their
; own windows (M_NONE)
M_NONE  = 0
M_RD    = 1
M_WR    = 2

.macro OPS
        ;  name        setup     unit      mode    bank n     k     b
        OP "REG     ", nothing,  u_reg,    M_NONE, 0,   4540, 256,  0
        OP "MAIN RD ", nothing,  u_rd16,   M_NONE, 0,   119,  4096, 0
        OP "MAIN WR ", nothing,  u_wr16,   M_NONE, 0,   126,  4096, 0
        OP "AUX RD  ", nothing,  u_rd16,   M_RD,   0,   119,  4096, 0
        OP "AUX WR  ", nothing,  u_wr16,   M_WR,   0,   126,  4096, 0
        OP "RW HIT  ", nothing,  u_rdhit,  M_RD,   RWB, 103,  4096, 0
        OP "RW SEQ  ", nothing,  u_rd16,   M_RD,   RWB, 72,   4096, 0
        OP "RW UHIT ", nothing,  u_uhit,   M_RD,   RWB, 8580, 64,   0
        OP "RW S64  ", nothing,  u_s64,    M_RD,   RWB, 859,  64,   0
        OP "RW S256 ", nothing,  u_s256,   M_RD,   RWB, 859,  64,   0
        OP "RW WHIT ", nothing,  u_wrhit,  M_WR,   RWB, 103,  4096, 0
        OP "RW WSEQ ", nothing,  u_wr16,   M_WR,   RWB, 53,   4096, 0
        OP "RW WS64 ", nothing,  u_ws64,   M_WR,   RWB, 430,  64,   0
        OP "GC RW 1 ", set_b16,  u_gc1,    M_NONE, 0,   776,  1,    256
        OP "GC RW 4 ", set_b16,  u_gc4,    M_NONE, 0,   210,  1,    1024
        OP "GC RW 8 ", set_b16,  u_gc8,    M_NONE, 0,   106,  1,    2048
        OP "GC AX 1 ", set_b0,   u_gc1,    M_NONE, 0,   1019, 1,    256
        OP "GC AX 4 ", set_b0,   u_gc4,    M_NONE, 0,   274,  1,    1024
        OP "GC AX 8 ", set_b0,   u_gc8,    M_NONE, 0,   139,  1,    2048
        OP "PLOAD 4 ", nothing,  u_pl4,    M_NONE, 0,   208,  1,    1024
        OP "SPIN    ", nothing,  u_spin,   M_NONE, 0,   7033, 1,    0
        OP "WIN     ", nothing,  u_win,    M_NONE, 0,   1341, 1,    0
        OP "GET RW 4", set_g4,   FAR_GET,  M_NONE, 0,   7857, 1,    4
        OP "GET RW24", set_g24,  FAR_GET,  M_NONE, 0,   3929, 1,    24
        OP "GET RW96", set_g96,  FAR_GET,  M_NONE, 0,   1341, 1,    96
        OP "GET AX 4", set_a4,   FAR_GET,  M_NONE, 0,   7857, 1,    4
        OP "GET AX24", set_a24,  FAR_GET,  M_NONE, 0,   4587, 1,    24
        OP "GET AX96", set_a96,  FAR_GET,  M_NONE, 0,   1833, 1,    96
        OP "PUT RW 4", set_p4,   FAR_PUT,  M_NONE, 0,   7051, 1,    4
        OP "PUT RW24", set_p24,  FAR_PUT,  M_NONE, 0,   3102, 1,    24
        OP "PUT RW96", set_p96,  FAR_PUT,  M_NONE, 0,   1008, 1,    96
        OP "PUT AX 4", set_q4,   FAR_PUT,  M_NONE, 0,   7757, 1,    4
        OP "PUT AX24", set_q24,  FAR_PUT,  M_NONE, 0,   4231, 1,    24
        OP "PUT AX96", set_q96,  FAR_PUT,  M_NONE, 0,   1794, 1,    96
        OP "MO GET  ", set_mog,  u_pw3,    M_NONE, 0,   1462, 1,    96
        OP "MO PUT  ", set_mop,  u_pw3,    M_NONE, 0,   1108, 1,    96
        OP "LN GET  ", set_lng,  u_pw2,    M_NONE, 0,   2587, 1,    34
        OP "SW NONE ", nothing,  u_sw0,    M_NONE, 0,   20393, 2,    0
        OP "SW RAMRD", nothing,  u_swrd,   M_NONE, 0,   6342, 2,    0
        OP "SW RAMWR", nothing,  u_swwr,   M_NONE, 0,   6347, 2,    0
        OP "SW C073 ", nothing,  u_sw73,   M_NONE, 0,   9190, 2,    0
        OP "SW ALTZP", nothing,  u_swzp,   M_NONE, 0,   6346, 2,    0
        OP "SHR SEQ ", nothing,  u_shr,    M_NONE, 0,   209,  1,    256
        OP "SHR COL ", nothing,  u_shrc,   M_NONE, 0,   227,  1,    96
        OP "PR2 256 ", set_pr0,  u_pr1,    M_NONE, 0,   N_P256, 1,  256
        OP "PR2 2K  ", set_pr1,  u_pr1,    M_NONE, 0,   N_P2K,  1,  2048
        OP "PR2 16K ", set_pr2,  u_pr1,    M_NONE, 0,   N_P16K, 1,  16384
        OP "PR2 8X2K", set_pr3,  u_pr8,    M_NONE, 0,   N_P8X,  8,  2048
        OP "PR6 256 ", set_pr4,  u_pr1,    M_NONE, 0,   N_P256, 1,  256
        OP "PR6 2K  ", set_pr5,  u_pr1,    M_NONE, 0,   N_P2K,  1,  2048
        OP "PR6 16K ", set_pr6,  u_pr1,    M_NONE, 0,   N_P16K, 1,  16384
        OP "PR6 8X2K", set_pr7,  u_pr8,    M_NONE, 0,   N_P8X,  8,  2048
.endmacro

; the memory API's lines' n (E(n) about 55,000 bus cycles on a2vm f121)
N_P256  = 505
N_P2K   = 76
N_P16K  = 10
N_P8X   = 10


; OP: one field of the table, the one OPLIST selects
.macro OP name, setup, unit, wmode, wbank, count, k, b
        .if OPLIST = 0
        .assert (count) >= 1 && (count) <= 32767, error, "n: 1-32767 (2n in 16 bits)"
        .byte name
        .elseif OPLIST = 1
        .byte <(setup)
        .elseif OPLIST = 2
        .byte >(setup)
        .elseif OPLIST = 3
        .byte <(unit)
        .elseif OPLIST = 4
        .byte >(unit)
        .elseif OPLIST = 5
        .byte wmode
        .elseif OPLIST = 6
        .byte wbank
        .elseif OPLIST = 7
        .byte <(count)
        .elseif OPLIST = 8
        .byte >(count)
        .elseif OPLIST = 9
        .byte <(k)
        .elseif OPLIST = 10
        .byte >(k)
        .elseif OPLIST = 11
        .byte <(b)
        .elseif OPLIST = 12
        .byte >(b)
        .endif
.endmacro

op_names:
OPLIST .set 0
        OPS
op_end:
        .assert op_end - op_names = 8 * NOPS, error, "NOPS names of 8"
op_setup_lo:
OPLIST .set 1
        OPS
op_setup_hi:
OPLIST .set 2
        OPS
op_unit_lo:
OPLIST .set 3
        OPS
op_unit_hi:
OPLIST .set 4
        OPS
op_mode:
OPLIST .set 5
        OPS
op_bank:
OPLIST .set 6
        OPS
op_n_lo:
OPLIST .set 7
        OPS
op_n_hi:
OPLIST .set 8
        OPS
op_k_lo:
OPLIST .set 9
        OPS
op_k_hi:
OPLIST .set 10
        OPS
op_b_lo:
OPLIST .set 11
        OPS
op_b_hi:
OPLIST .set 12
        OPS
        .export op_names, op_n_lo, op_n_hi, op_k_lo, op_k_hi, op_b_lo
        .export op_b_hi, op_mode, op_bank, op_unit_lo, op_unit_hi

; ---------------------------------------------------------------------------
; The setups (before each measurement, untimed) and the units in main
; ---------------------------------------------------------------------------
        .segment "CODE"
nothing:
        rts

; far_gcopy's bank
set_b16:
        lda #RWB
        bra :+
set_b0: lda #0
:       sta FA_BANK
        stz FA_SRC
        stz FA_DST
        rts

; far_get: from the bank's BUF to main BUF + $800; far_put: back
set_g4: lda #4
        bra set_g
set_g24:
        lda #24
        bra set_g
set_g96:
        lda #96
set_g:  ldx #RWB
        bra set_get
set_a4: lda #4
        bra set_a
set_a24:
        lda #24
        bra set_a
set_a96:
        lda #96
set_a:  ldx #0
set_get:
        sta FA_N
        stx FA_BANK
        stz FA_SRC
        lda #>BUF
        sta FA_SRC + 1
        stz FA_DST
        lda #>(BUF + $800)
        sta FA_DST + 1
        rts
set_p4: lda #4
        bra set_p
set_p24:
        lda #24
        bra set_p
set_p96:
        lda #96
set_p:  ldx #RWB
        bra set_put
set_q4: lda #4
        bra set_q
set_q24:
        lda #24
        bra set_q
set_q96:
        lda #96
set_q:  ldx #0
set_put:
        sta FA_N
        stx FA_BANK
        stz FA_SRC
        lda #>(BUF + $800)
        sta FA_SRC + 1
        stz FA_DST
        lda #>BUF
        sta FA_DST + 1
        rts

; the object API's window (gobj.s): the descriptors as mo_fetch, mo_wback
; and ln_miss write them, for mobj slot MO_SLOT (cache line 0) and line
; LN_LINE (line 0 of the line cache)
MO_SLOT = 5
LN_LINE = 300
MO_AT   = RTHBASE + MO_SIZE * MO_SLOT
LN_AT   = LINE_BASE + LINE_SIZE * LN_LINE

set_mog:
        lda #<RAMRDON           ; pw_get: the slot's four records to the
        sta PW_ON               ;   cache line (mo_fetch)
        lda #<RAMRDOFF
        sta PW_OFF
        ldx #3
@desc:  lda mo_banks,x
        sta PW_BANK,x
        lda #MO_SIZE - 1
        sta PW_N,x
        lda #<MO_AT
        sta PW_SL,x
        lda #>MO_AT
        sta PW_SH,x
        lda mo_lo,x
        sta PW_DL,x
        lda #>MOC
        sta PW_DH,x
        dex
        bpl @desc
        rts
set_mop:
        lda #<RAMWRTON          ; pw_put: the line's four groups back
        sta PW_ON               ;   (mo_wback, all four dirty)
        lda #<RAMWRTOFF
        sta PW_OFF
        ldx #3
@desc:  lda mo_banks,x
        sta PW_BANK,x
        lda #MO_SIZE - 1
        sta PW_N,x
        lda #<MO_AT
        sta PW_DL,x
        lda #>MO_AT
        sta PW_DH,x
        lda mo_lo,x
        sta PW_SL,x
        lda #>MOC
        sta PW_SH,x
        dex
        bpl @desc
        rts
mo_banks:
        .byte RTH, MOBJA, MOBJB, MOBJC
mo_lo:  .byte <MOC, <(MOC + MO_SIZE), <(MOC + 2 * MO_SIZE), <(MOC + 3 * MO_SIZE)
        .assert >MOC = >(MOC + 4 * MO_SIZE - 1), error, "the mobj line on one page"

set_lng:
        lda #<RAMRDON
        sta PW_ON
        lda #<RAMRDOFF
        sta PW_OFF
        lda #LVG0               ; the record
        sta PW_BANK
        lda #<LN_AT
        sta PW_SL
        lda #>LN_AT
        sta PW_SH
        lda #LVS                ; its front sector, then its back sector
        sta PW_BANK + 1
        sta PW_BANK + 2
        lda #<LN_LINE
        sta PW_SL + 1
        sta PW_SL + 2
        lda #>(LVS_LNSECF + LN_LINE)
        sta PW_SH + 1
        lda #>(LVS_LNSECB + LN_LINE)
        sta PW_SH + 2
        lda #<LNC
        sta PW_DL
        lda #<(LNC + LINE_SIZE)
        sta PW_DL + 1
        lda #<(LNC + LINE_SIZE + 1)
        sta PW_DL + 2
        lda #>LNC
        sta PW_DH
        sta PW_DH + 1
        sta PW_DH + 2
        lda #LINE_SIZE - 1
        sta PW_N
        stz PW_N + 1
        stz PW_N + 2
        rts
        .assert <LVS_LNSECF = 0 && <LVS_LNSECB = 0, error, "LNSECF, LNSECB on pages"

; the units in main: far_gcopy, far_pload and the window are called from
; main code, as the game calls them (far_get and far_put are units
; themselves: the driver in the card calls them)
u_gc1:  lda #1
        bra u_gc
u_gc4:  lda #4
        bra u_gc
u_gc8:  lda #8
u_gc:   sta FA_N                ; (as gr_load: whole pages, Y = 0)
        lda #>BUF
        sta FA_SRC + 1
        sta FA_DST + 1
        ldy #0
        jmp FAR_GCOPY

u_pl4:  lda #<pl_list           ; 4 pages of the bank to the same main ones
        ldx #>pl_list
        ldy #RWB
        jmp FAR_PLOAD

u_pw3:  ldx #3                  ; a mobj's four groups
        jmp PW_GO
u_pw2:  ldx #2                  ; a line's record and its two sector bytes
        jmp PW_GO

; the switches, each followed by code run from main (mblock); two an
; operation's unit (k = 2)
u_sw0:  .repeat 2
        jsr mblock
        .endrep
        rts
u_swwr: .repeat 2
        sta RAMWRTON
        sta RAMWRTOFF
        jsr mblock
        .endrep
        rts
u_sw73: .repeat 2
        stz RWBANK
        jsr mblock
        .endrep
        rts
u_swzp: .repeat 2
        sta ALTZPON
        sta ALTZPOFF
        jsr mblock
        .endrep
        rts
mblock: .repeat 16
        lda BUF,x
        .endrep
        rts

; the SHR bursts, each followed by a $C0xx read (the drain): a page of
; contiguous bytes, and a column of 96 rows (a byte every 160)
u_shr:  sta RAMWRTON
        ldx #0
:       sta SHR,x
        inx
        bne :-
        sta RAMWRTOFF
        lda KBD
        rts
u_shrc: sta RAMWRTON
        .repeat 96, I
        sta SHR + 160 * I
        .endrep
        sta RAMWRTOFF
        lda KBD
        rts

; ---------------------------------------------------------------------------
; The card part (run at $E000): the driver, the timers, the loops that run
; inside a read window
; ---------------------------------------------------------------------------
        .segment "LCCODE"
        .export measure, m_go, m_call, m_end, t_read, t_bok

; measure: cnt units of the operation (cnt not 0), timed: el = E,
; dlt, eerr. The setup, then the window (mode), then the start's read,
; the units, the end's read, the window closed
measure:
m_setup:
        jsr nothing             ; (patched: the operation's setup)
        lda mode
        beq m_go
        ldx bank
        stx RWBANK
        lsr a
        bcc :+
        sta RAMRDON
:       lsr a
        bcc m_go
        sta RAMWRTON
m_go:   ldx #0
        jsr t_read
m_loop:
m_call: jsr nothing             ; (patched: the operation's unit)
        lda cnt
        bne :+
        dec cnt + 1
:       dec cnt
        lda cnt
        ora cnt + 1
        bne m_loop
m_end:  ldx #4
        jsr t_read
        sta RAMRDOFF
        sta RAMWRTOFF
        stz RWBANK
        jmp t_elapsed
        .assert >m_loop = >(m_end - 1), error, "the driver's loop crosses a page"

; t_read: VIA-B's counter then VIA-A's into ts + X, + X + 2: the low
; byte, the high byte, the low byte again (a wrap between: again)
t_read:
@b:     lda VIA_B_T1CL
        ldy VIA_B_T1CH
        cmp VIA_B_T1CL          ; carry set: no wrap of the low byte
        bcc @b
t_bok:  sta ts,x                ; (the host's clock check: the read held)
        sty ts + 1,x
@a:     lda VIA_A_T1CL
        ldy VIA_A_T1CH
        cmp VIA_A_T1CL
        bcc @a
        sta ts + 2,x
        sty ts + 3,x
        rts

; t_elapsed: el = E from ts (the start) and ts + 4 (the end); dlt, eerr
t_elapsed:
        sec                     ; VIA-B: a period of 65,536
        lda ts
        sbc ts + 4
        sta eb
        lda ts + 1
        sbc ts + 5
        sta eb + 1
        ldx #2                  ; VIA-A: its $FFFF (before a reload) is
        jsr a_map               ;   the step before $FEFE: $FEFF
        ldx #6
        jsr a_map
        sec                     ; a period of 65,280: a borrow is 256 less
        lda ts + 2
        sbc ts + 6
        sta ea
        lda ts + 3
        sbc ts + 7
        sta ea + 1
        bcs :+
        dec ea + 1
:       sec                     ; xx = ea - eb mod 65,280
        lda ea
        sbc eb
        sta xx
        lda ea + 1
        sbc eb + 1
        sta xx + 1
        bcs :+
        dec xx + 1
:       lda xx + 1              ; from $FE80 (-128 mod 65,280): no wrap,
        cmp #$FE                ;   a negative difference
        bcc @wraps
        lda xx
        cmp #$80
        bcc @wraps
        stz qq
        lda xx
        sta dlt
        bra @check
@wraps: clc                     ; qq = (xx + 128) / 256
        lda xx
        adc #$80
        tay
        lda xx + 1
        adc #0
        sta qq
        tya
        sec
        sbc #$80
        sta dlt
@check: stz eerr
        lda dlt                 ; |dlt| <= DELTA_MAX
        bpl :+
        eor #$FF
        inc a
:       cmp #DELTA_MAX + 1
        bcc :+
        inc eerr
:       lda eb
        sta el
        lda eb + 1
        sta el + 1
        lda qq
        sta el + 2
        stz el + 3
        rts

a_map:  lda ts,x
        and ts + 1,x
        cmp #$FF
        bne :+
        dec ts + 1,x
:       rts

; the units that run in a read window (the code must be near: the card)
u_reg:  ldy #0                  ; 256 turns of a register-only loop
:       dey
        bne :-
        rts
        .assert >u_reg = >(* - 1), error, "REG crosses a page"

; 16 pages in order, lda abs,y (sta abs,y); the same byte (abs,x, X = 0)
u_rd16: .repeat 16, P
        ldy #0
:       lda BUF + P * $100,y
        iny
        bne :-
        .endrep
        rts
u_wr16: .repeat 16, P
        ldy #0
:       sta BUF + P * $100,y
        iny
        bne :-
        .endrep
        rts
u_rdhit:
        ldx #0
        .repeat 16, P
        ldy #0
:       lda BUF,x
        iny
        bne :-
        .endrep
        rts
u_wrhit:
        ldx #0
        .repeat 16, P
        ldy #0
:       sta BUF,x
        iny
        bne :-
        .endrep
        rts

; 64 reads unrolled: of one byte, a stride of 64, a stride of 256; 64
; writes a stride of 64
u_uhit: .repeat 64
        lda STRIDE
        .endrep
        rts
u_s64:  .repeat 64, I
        lda STRIDE + 64 * I
        .endrep
        rts
u_s256: .repeat 64, I
        lda STRIDE + 256 * I
        .endrep
        rts
u_ws64: .repeat 64, I
        sta STRIDE + 64 * I
        .endrep
        rts

; the switch of RAMRD, from the card (its next fetch would come from the
; bank otherwise), then main code
u_swrd: .repeat 2
        sta RAMRDON
        sta RAMRDOFF
        jsr mblock
        .endrep
        rts

; the slot-4 window: a read of VIA-A's DDRA (no side effect) then 800
; cycles of a register loop; SPIN: a main read in its place
u_spin: lda BUF
        ldy #160
:       dey
        bne :-
        rts
        .assert >u_spin = >(* - 1), error, "SPIN crosses a page"
u_win:  lda VIA_A_DDRA
        ldy #160
:       dey
        bne :-
        rts
        .assert >u_win = >(* - 1), error, "WIN crosses a page"

pl_list:
        .byte >BUF, 4, 0        ; far_pload's list: near in its window

; crash_brk: a BRK, NMI or IRQ: the address on the screen, then stop
crash_brk:
        sta RAMRDOFF
        sta RAMWRTOFF
        sta ALTZPOFF
        stz RWBANK
        ldx #$FF
        txs
        jmp crash_main

; the memory API's units (after the others, which keep their addresses):
; one request, eight requests
u_pr1:  lda #<q_req
        ldx #>q_req
        jmp am_go
u_pr8:  .repeat 8, I
        lda #<(q_req + REQ_LEN * I)
        ldx #>(q_req + REQ_LEN * I)
        jsr am_go
        .endrep
        rts

; am_go: the request at A:X (REQ_LEN bytes) through slot 7's FIFO
; (README_MEMORY_API.md section 7), as lload.s's am_send sends one: C8
; released, slot 7's ROM read, the bytes pushed, executed, the reply's
; first byte (its result) popped, C8 released. The result goes to am_err;
; once it is not 0, no more requests (a missing reply waits about a
; second, and the whole line would wait n of them)
am_go:  ldy am_err
        bne @skip
        sta @src + 1
        stx @src + 2
        php
        sei
        bit SP_RELEASE
        bit SP_ROM
        ldy #0
@src:   lda $FFFF,y             ; (patched: the request)
        sta SP_DATA
        iny
        cpy #REQ_LEN
        bne @src
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
        stz am_w
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec am_w
        bne @wait
        lda #AMEM_TIMEOUT
        bra @done
@ready: lda SP_DATA
        sta SP_POP
@done:  bit SP_RELEASE
        plp
        sta am_err
@skip:  rts

; pg_copy: text page 1's memory to page 2's, main then aux (80STORE off
; for the aux half, so that RAMRD and RAMWRT reach $0400-$0BFF; this
; code is in the card, which they do not switch)
pg_copy:
        jsr @four
        sta STORE80OFF
        sta RAMRDON
        sta RAMWRTON
        jsr @four
        sta RAMRDOFF
        sta RAMWRTOFF
        sta STORE80ON
        rts
@four:  ldx #0
:       .repeat 4, P
        lda $0400 + P * $100,x
        sta $0800 + P * $100,x
        .endrep
        inx
        bne :-
        rts
        .assert * <= $F000, error, "the card part passes $EFFF"

        .segment "CODE"
crash_main:
        lda #<s_crash
        ldx #>s_crash
; stop_msg: the message at A:X alone on the screen, then stop
stop_msg:
        pha
        phx
        jsr cls
        plx
        pla
        jsr put_str_at0
crash:  bra crash               ; (a2vm's run stops here)
s_crash:
        .byte "CALIB: CRASH (BRK OR INTERRUPT)", 0
s_notimer:
        .byte "CALIB: NO 6522 TIMERS IN SLOT 4: TURN THE PHASOR ON", 0

; ---------------------------------------------------------------------------
; The memory API's lines and page 2 (after everything above, so that the
; other lines' code keeps its addresses)
; ---------------------------------------------------------------------------
detect_all:
        jsr detect_video
        ; (on to am_probe)

; am_probe: g_amem = 0 when slot 7 has the memory API with COPY, FILL and
; PRIVATE, available (appletini-one README_MEMORY_API.md sections 2 and 7;
; as pl_boot.s's probe_amem asks): $FF none, $FE a capability missing,
; AMEM_TIMEOUT no reply, else the STATUS's error
am_probe:
        lda #$FF
        sta g_amem
        sta INTCXROMOFF
        bit SP_RELEASE
        lda SP_ROM + 1          ; a SmartPort ROM
        cmp #$20
        jne @out
        lda SP_ROM + 3
        ora SP_ROM + 7
        jne @out
        lda SP_ROM + 5
        cmp #3
        jne @out
        lda SP_CTRL             ; the Appletini's FIFO
        and #$3F
        cmp #$20
        jne @out
        bit SP_RELEASE
        bit SP_ROM
        ldy #0
:       lda status_rq,y
        sta SP_DATA
        iny
        cpy #10
        bne :-
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
        stz am_w
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec am_w
        bne @wait
        lda #AMEM_TIMEOUT
        bra @set
@ready: lda SP_DATA
        sta SP_POP
        cmp #0
        bne @set
        lda SP_DATA             ; the length: 32
        sta SP_POP
        cmp #32
        bne @bad
        lda SP_DATA
        sta SP_POP
        bne @bad
        ldx #0
:       lda SP_DATA
        sta SP_POP
        sta q_caps,x
        inx
        cpx #32
        bcc :-
        ldx #4                  ; "AMEM", version 1
:       lda q_caps,x
        cmp amem_magic,x
        bne @bad
        dex
        bpl :-
        lda q_caps + 6          ; descriptors of 16 bytes
        cmp #16
        bne @bad
        lda q_caps + 8          ; COPY, FILL, PRIVATE
        and #7
        cmp #7
        bne @bad
        lda q_caps + 15         ; available
        and #1
        beq @bad
        lda #0
        bra @set
@bad:   lda #$FE
@set:   sta g_amem
@out:   bit SP_RELEASE
        rts
status_rq:
        .byte 0, 3, 0, 0, 0, $80, 0, 0, 0, 0  ; STATUS, unit 0, selector $80
amem_magic:
        .byte "AMEM", 1

; run_opx: operation X; the memory API's lines only when the probe found
; it (else ERR: the record's error flags 8), and ERR (16) when a request
; was refused or got no reply
run_opx:
        cpx #OP_PR
        bcs :+
        jmp run_op
:       stz am_err
        lda g_amem
        bne @none
        jsr run_op
        lda am_err
        beq @done
        lda #16
        bra @flag
@none:  stx opx
        txa
        jsr rec_of
        ldy #R_SIZE - 1
        lda #0
:       sta (rec),y
        dey
        bpl :-
        lda #8
@flag:  ldy #R_ERR
        ora (rec),y
        sta (rec),y
@done:  rts

; the setups of the PRIVATE lines: X = the line (0-7) in the prt_* tables;
; the requests into q_req (pr_cnt of pr_sz bytes each, RWS:a to main a,
; from page pr_d on), then main's 16 KB from page pr_d copied into RWS
; (untimed: the timed requests rewrite main with the bytes it holds)
set_pr0:
        ldx #0
        bra set_pr
set_pr1:
        ldx #1
        bra set_pr
set_pr2:
        ldx #2
        bra set_pr
set_pr3:
        ldx #3
        bra set_pr
set_pr4:
        ldx #4
        bra set_pr
set_pr5:
        ldx #5
        bra set_pr
set_pr6:
        ldx #6
        bra set_pr
set_pr7:
        ldx #7
set_pr: lda prt_page,x
        sta pr_d
        sta pr_hi
        stz pr_lo
        lda prt_szl,x
        sta pr_sz
        lda prt_szh,x
        sta pr_sz + 1
        lda prt_cnt,x
        sta pr_cnt
        lda #<q_req
        sta m_u
        lda #>q_req
        sta m_u + 1
@req:   ldy #REQ_LEN - 1        ; the template, then its addresses
:       lda rq_tmpl,y
        sta (m_u),y
        dey
        bpl :-
        ldy #RQ_SRC
        lda pr_lo
        sta (m_u),y
        ldy #RQ_DST
        sta (m_u),y
        lda pr_hi
        ldy #RQ_SRC + 1
        sta (m_u),y
        ldy #RQ_DST + 1
        sta (m_u),y
        ldy #RQ_SIZE
        lda pr_sz
        sta (m_u),y
        iny
        lda pr_sz + 1
        sta (m_u),y
        clc                     ; the next request's address
        lda pr_lo
        adc pr_sz
        sta pr_lo
        lda pr_hi
        adc pr_sz + 1
        sta pr_hi
        clc
        lda m_u
        adc #REQ_LEN
        sta m_u
        bcc :+
        inc m_u + 1
:       dec pr_cnt
        bne @req
        ldy #REQ_LEN - 1        ; the copy of main into RWS: the template
:       lda rq_tmpl,y           ;   turned round, not PRIVATE (an extended
        sta q_snap,y            ;   bank needs none)
        dey
        bpl :-
        stz q_snap + RQ_FLAGS
        stz q_snap + RQ_SRCSP
        stz q_snap + RQ_SRCB
        lda #1
        sta q_snap + RQ_DSTSP
        lda #RWS
        sta q_snap + RQ_DSTB
        stz q_snap + RQ_SRC
        stz q_snap + RQ_DST
        lda pr_d
        sta q_snap + RQ_SRC + 1
        sta q_snap + RQ_DST + 1
        stz q_snap + RQ_SIZE
        lda #>$4000
        sta q_snap + RQ_SIZE + 1
        lda #<q_snap
        ldx #>q_snap
        jmp am_go

; the lines' destinations, bytes a request and requests a unit (the OPS
; table's PR2 and PR6 lines, in order)
prt_page:
        .byte $20, $20, $20, $20, $60, $60, $60, $60
prt_szl:
        .byte <256, <2048, <16384, <2048, <256, <2048, <16384, <2048
prt_szh:
        .byte >256, >2048, >16384, >2048, >256, >2048, >16384, >2048
prt_cnt:
        .byte 1, 1, 1, 8, 1, 1, 1, 8

; a request of one PRIVATE copy (README_MEMORY_API.md sections 1, 3 and
; 7): the SmartPort CONTROL with its nine parameter bytes (unit 0, the
; pointer the FIFO does not use, selector $80, padding), the list's
; length, its header, the descriptor: COPY, PRIVATE, AUX RWS:0 to MAIN
; 0:0, 0 bytes (set_pr's fields)
rq_tmpl:
        .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0
        .word 8 + 16
        .byte "AMEM", 1, 1, 0, 0
        .byte 1, 1, 1, RWS
        .word 0
        .byte 0, 0
        .word 0
        .word 0
        .byte 0, 0, 0, 0
        .assert * - rq_tmpl = REQ_LEN, error, "a request of 36 bytes"

; page 2: the memory API's lines, written on page 1's memory first and
; moved to page 2's (pg_copy, in the card), then page 1 as before
show_all:
        jsr cls
        jsr show2
        jsr pg_copy
        jmp show

show2:  stz col
        stz row
        lda #<s_head2
        ldx #>s_head2
        jsr put_str
        stz col
        lda #1
        sta row
        lda #<s_cols
        ldx #>s_cols
        jsr put_str
        lda #40
        sta col
        lda #<s_cols
        ldx #>s_cols
        jsr put_str
        ldx #OP_PR              ; PR2 left, PR6 right, rows 2-5
@op:    phx
        stx opx
        txa
        sec
        sbc #OP_PR
        ldy #0
        cmp #4
        bcc :+
        sbc #4
        ldy #40
:       clc
        adc #2
        sta row
        sty col
        jsr show_at
        plx
        inx
        cpx #NOPS
        bne @op
        ldx #0                  ; the legend, rows 7-10
@leg:   phx
        txa
        clc
        adc #7
        sta row
        stz col
        lda s_legl,x
        pha
        lda s_legh,x
        tax
        pla
        jsr put_str
        plx
        inx
        cpx #4
        bne @leg
        lda g_amem
        beq :+
        lda #12
        sta row
        stz col
        lda #<s_noamem
        ldx #>s_noamem
        jmp put_str
:       rts

; cls_p1: page 1 shown, then cls
cls_p1: stz g_page
        sta TXTPAGE1
        sta STORE80ON
        jmp cls

; on_key: the key in A (its strobe cleared): R runs again, SPACE shows
; the other page; then back to the loop
on_key: and #$DF                ; R or r
        cmp #'R' | $80
        bne :+
        jmp run_all
:       cmp #' ' & $DF | $80    ; SPACE
        bne @back
        lda g_page
        eor #1
        sta g_page
        beq @p1
        sta STORE80OFF          ; page 2: 80STORE off, then PAGE2
        sta TXTPAGE2
        bra @back
@p1:    sta TXTPAGE1            ; page 1: PAGE1, then 80STORE
        sta STORE80ON
@back:  jmp done

s_head2:
        .byte "CALIB PAGE 2: THE MEMORY API  SPACE: PAGE 1  R: RUN AGAIN", 0
s_leg0: .byte "PR2: ONE PRIVATE COPY FROM RAMWORKS BANK 17 TO MAIN $2000 (THE "
        .byte "COLORMAPS)", 0
s_leg1: .byte "PR6: THE SAME TO MAIN $6000. EACH LINE A MEMORY-API REQUEST, "
        .byte "FIFO INCLUDED", 0
s_leg2: .byte "256, 2K, 16K: ONE REQUEST OF THAT SIZE; 8X2K: EIGHT REQUESTS OF "
        .byte "2K IN A ROW", 0
s_leg3: .byte "US/OP: A REQUEST; US/B: A BYTE; A2VM F121: THE MODEL'S US/OP", 0
s_legl: .byte <s_leg0, <s_leg1, <s_leg2, <s_leg3
s_legh: .byte >s_leg0, >s_leg1, >s_leg2, >s_leg3
s_noamem:
        .byte "NO MEMORY API IN SLOT 7 (APPLETINI F1.1.4 OR LATER, VTW ON): "
        .byte "NOT MEASURED", 0

; ---------------------------------------------------------------------------
; The play build's bytes (gen: calibdisk.py), copied into place at start
; ---------------------------------------------------------------------------
        .segment "PAYLOAD"
pay_far:
        .incbin "far.bin"       ; $DC00-$DFFF of the card's bank 1
        .assert * - pay_far = FAR_LEN, error, "far.bin"
pay_kern:
        .incbin "kern.bin"      ; the kernel's far_gcopy
        .assert * - pay_kern = KERN_LEN, error, "kern.bin"
pay_pw: .incbin "pw.bin"        ; gobj.s's window
        .assert * - pay_pw = PW_LEN, error, "pw.bin"

; a2vm f121's figures (ns an operation), last: they change no address
        .segment "PRED"
pred_v: .include "calibpred.inc"
        .assert * - pred_v = 4 * NOPS, error, "the predictions"
        .export pred_v
