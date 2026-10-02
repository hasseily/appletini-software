; The AY timing test: what an AY register write and the slow window after
; a burst cost on the card, measured by frame counts. Key T of MUSIC.SYSTEM.
;
; Every access to slot 4 ($C400-$C4FF, $C0C0-$C0CF) runs the CPU at 1 MHz
; for the next `vtw.slowdown.cycles` CPU cycles (512 by default, 32 with
; the DOOM profile, PROFILE.TXT; FW-S1, a proposed firmware change, would
; exempt the port writes). The design expects a register write of the
; burst loop, 41 cycles, to take 40.4 us, and the window after the last
; write to run 512 cycles at 1 MHz (504 us) or 32 (31.5 us).
;
; The measure. The timer interrupt (irq.s) counts frames: it comes once a
; frame's bus cycles, and its acknowledge, a slot-4 access, opens a window
; too. Three phases of AYT_FRAMES frames each; in each frame, after the
; interrupt, AYT_AFTER spin turns that outlast that window, then a burst
; of K writes (R8 of chip 0 = 0: a silent level) with the player's own
; 41-cycle loop, then a spin loop that counts its turns until the next
; interrupt (the AYT_AFTER turns included):
;   F: K = 0, the reference: the frame's time is all spin, in TURBO but
;      for the interrupt's window, W cycles at 1 MHz;
;   1: K = AYT_K1;   2: K = AYT_K2.
; With cF, c1, c2 the phases' spin counts and b the Apple bus cycle, the
; time a burst of K writes took from the frame, in bus cycles, is
;   D = (cF - c) / cF x (the frame's bus cycles - W)
; and, the window being W cycles after the last write of the burst,
;   D = 41 K - 12 + W  -  (W - 6) s          (in b)
; where s is a spin cycle's time in TURBO, ((the frame - W) / cF) / 13: the
; burst's first 7 cycles run in TURBO before the first slot-4 access
; opens the window, that access is one bus cycle, the last write's DEX
; and BNE and the spin's LDY (6 cycles) are the window's first cycles,
; and the rest of the window is spin turns at 1 MHz that TURBO would have
; run in (W - 6) s. So
;   a write:  t = (D2 - D1) / (K2 - K1)             (41 b by the design)
;   the tail: E = D1 - K1 t = (W - 12) - (W - 6) s,
;             W = (E + 12 - 6 s) / (1 - s)           (512 or 32 cycles)
; W is on both sides: ayt_math solves with the whole frame, then again
; with the frame less the W found, which leaves W a relative error of
; about (W / frame)^2, under half a cycle. When a write takes less than
; 20 bus cycles the port writes open no window (FW-S1): the tail is 0 by
; the design, and E, what a burst costs beyond its writes, is shown
; instead, from the whole frame (the interrupt's window, unmeasured then,
; makes t and E about W / frame too high: 2.5 % with 512 cycles). All
; arithmetic is in thousandths of a bus cycle ("mc"), 32 and 64 bits;
; microseconds are cycles x b, with b 984,615 ps on PAL (1,015,625 Hz) and
; 979,927 ps on NTSC (1,020,484 Hz).
;
; Results (in build/music.lbl): ayt_cf, ayt_c1,
; ayt_c2 (spin counts), ayt_d1, ayt_d2, ayt_tw, ayt_e (signed), ayt_s (all
; mc), ayt_w10 (the window in tenths of a cycle), ayt_verdict (0 another
; window, 1 the default 512, 2 the Doom profile's 32, 3 FW-S1).

        .setcpu "65C02"
        .include "sound.inc"

        .import put_at, put_char, put_str, clear_rows, wait_irq
        .import mus_stop
        .importzp irq_count, ptr, ntsc
        .export ayt_run, ayt_done
        .export ayt_cf, ayt_c1, ayt_c2, ayt_d1, ayt_d2, ayt_tw, ayt_e
        .export ayt_s, ayt_w10, ayt_verdict, ayt_spin, ayt_burst

AYT_FRAMES      = 32
AYT_K1          = 16
AYT_K2          = 208
AYT_AFTER       = 128           ; turns before the burst: 1,664 cycles at 1 MHz
SPIN_CYCLES     = 13            ; one turn of the spin loop (no carry)
FWS1_LIMIT      = 20000         ; mc: a write this fast opens no window
ROW             = 17

        .assert AYT_K2 < 256, error, "the write tables are one page"

.macro LOAD32 dst, value
        .repeat 4, I
        lda     #<((value) >> (I * 8))
        sta     dst + I
        .endrep
.endmacro

.macro COPY32 dst, src
        .repeat 4, I
        lda     src + I
        sta     dst + I
        .endrep
.endmacro

.macro SUB32 dst, left, right
        sec
        .repeat 4, I
        lda     left + I
        sbc     right + I
        sta     dst + I
        .endrep
.endmacro

.macro ADD32 dst, left, right
        clc
        .repeat 4, I
        lda     left + I
        adc     right + I
        sta     dst + I
        .endrep
.endmacro

; ---------------------------------------------------------------------------
        .segment "MUSZP": zeropage
kcur:   .res 1          ; the phase's K
frames: .res 1          ; frames left in the phase
vseen:  .res 1          ; the interrupt count the frame began at
spinhi: .res 2          ; the spin count's bytes 1 and 2 (Y is byte 0)

        .segment "MUSBSS"
        .align  256
wregt:  .res 256        ; the burst's registers (entries 1 to K)
wvalt:  .res 256        ; and values
sum:    .res 4
ma:     .res 4          ; muldiv: ma x mb / md, rounded
mb:     .res 4
md:     .res 4
mp:     .res 8
fmc:    .res 4          ; the frame, mc
bps:    .res 4          ; a bus cycle, ps
t32:    .res 4
ayt_cf: .res 4
ayt_c1: .res 4
ayt_c2: .res 4
ayt_d1: .res 4
ayt_d2: .res 4
ayt_tw: .res 4
ayt_e:  .res 4
ayt_s:  .res 4
ayt_w10:.res 4
ayt_verdict:
        .res 1
neg:    .res 1
digits: .res 12

; ---------------------------------------------------------------------------
        .segment "MUSCODE"

ayt_run:
        jsr     mus_stop                ; the music stops (its burst goes
        jsr     wait_irq                ;   out at the next interrupt)
        jsr     wait_irq
        lda     #ROW
        ldx     #7
        jsr     clear_rows
        ldx     #0
        ldy     #ROW
        jsr     put_at
        lda     #<s_measuring
        ldx     #>s_measuring
        jsr     put_str
        ldx     #0
:       lda     #8                      ; R8 (chip 0's level A) = 0
        sta     wregt,x
        stz     wvalt,x
        inx
        bne     :-
        jsr     wait_irq                ; the text's bytes drain (the
        jsr     wait_irq                ;   interrupt's I/O waits for them)
        jsr     wait_irq
        lda     #0
        jsr     ayt_phase
        COPY32  ayt_cf, sum
        lda     #AYT_K1
        jsr     ayt_phase
        COPY32  ayt_c1, sum
        lda     #AYT_K2
        jsr     ayt_phase
        COPY32  ayt_c2, sum
        jsr     ayt_math
        jsr     ayt_print
ayt_done:
        rts

; ayt_phase: A = K; sum = the spin turns of AYT_FRAMES frames, each a
; burst of K writes then the spin to the next interrupt
ayt_phase:
        sta     kcur
        stz     sum
        stz     sum+1
        stz     sum+2
        stz     sum+3
        lda     #AYT_FRAMES
        sta     frames
        lda     irq_count               ; start at an interrupt
:       cmp     irq_count
        beq     :-
        lda     irq_count
        sta     vseen
ayt_frame:
        stz     spinhi
        stz     spinhi+1
        ldy     #0
ayt_after:                              ; AYT_AFTER spin turns, past the
        iny                             ;   interrupt's window
        nop
        nop
        nop
        cpy     #AYT_AFTER
        bne     ayt_after
        ldx     kcur
        beq     ayt_spun
        ldy     #ORB_IDLE0
ayt_burst:                              ; 41 cycles a write, as player.s's
        lda     wregt,x                 ; burst
        sta     VIA_A_ORA_NH
        lda     #ORB_LATCH0
        sta     VIA_A_ORB
        sty     VIA_A_ORB
        lda     wvalt,x
        sta     VIA_A_ORA_NH
        lda     #ORB_WRITE0
        sta     VIA_A_ORB
        sty     VIA_A_ORB
        dex
        bne     ayt_burst
ayt_spun:
        ldy     #AYT_AFTER              ; the turns so far
ayt_spin:                               ; 13 cycles a turn
        iny
        beq     @carry
@check: lda     irq_count
        cmp     vseen
        beq     ayt_spin
        sta     vseen                   ; the frame ended: its count
        clc
        tya
        adc     sum
        sta     sum
        lda     spinhi
        adc     sum+1
        sta     sum+1
        lda     spinhi+1
        adc     sum+2
        sta     sum+2
        lda     #0
        adc     sum+3
        sta     sum+3
        dec     frames
        bne     ayt_frame
        rts
@carry: inc     spinhi
        bne     @check
        inc     spinhi+1
        bra     @check
        .assert >ayt_after = >(ayt_burst - 6), error, "the wait crosses a page"
        .assert >ayt_burst = >(ayt_spun - 1), error, "the burst crosses a page"
        .assert >ayt_spin = >(@check + 6), error, "the spin crosses a page"

; ---------------------------------------------------------------------------
ayt_math:
        ldx     #3
:       lda     fmc_pal,x               ; the frame and the bus cycle
        sta     fmc,x
        lda     bps_pal,x
        sta     bps,x
        dex
        bpl     :-
        bit     ntsc
        bpl     @machine
        ldx     #3
:       lda     fmc_ntsc,x
        sta     fmc,x
        lda     bps_ntsc,x
        sta     bps,x
        dex
        bpl     :-
@machine:
        jsr     ayt_solve               ; W, from the whole frame
        COPY32  ma, ayt_w10             ; the frame less the interrupt's
        LOAD32  mb, 100                 ;   window (W x 100 mc), and again
        LOAD32  md, 1
        jsr     muldiv
        SUB32   fmc, fmc, mp
        jsr     ayt_solve
        ; the regime
        LOAD32  t32, FWS1_LIMIT
        SUB32   t32, ayt_tw, t32
        bcs     @verdict                ; t >= FWS1_LIMIT
        lda     #3
        sta     ayt_verdict
        rts
@verdict:
        lda     #1                      ; 504-520 cycles: the default
        ldx     #<5040
        ldy     #>5040
        jsr     w10_at_least
        bcc     :+
        ldx     #<5201
        ldy     #>5201
        jsr     w10_at_least
        bcc     @set
:       lda     #2                      ; 28-36 cycles: the profile's 32
        ldx     #<280
        ldy     #>280
        jsr     w10_at_least
        bcc     @other
        ldx     #<361
        ldy     #>361
        jsr     w10_at_least
        bcc     @set
@other: lda     #0
@set:   sta     ayt_verdict
        rts

; ayt_solve: D1, D2, t, E, s and W (ayt_w10) from the spin counts and fmc
ayt_solve:
        ; D1, D2: (cF - c) x frame / cF
        SUB32   ma, ayt_cf, ayt_c1
        COPY32  mb, fmc
        COPY32  md, ayt_cf
        jsr     muldiv
        COPY32  ayt_d1, mp
        SUB32   ma, ayt_cf, ayt_c2
        COPY32  mb, fmc
        COPY32  md, ayt_cf
        jsr     muldiv
        COPY32  ayt_d2, mp
        ; a write: (D2 - D1) / (K2 - K1)
        SUB32   ma, ayt_d2, ayt_d1
        LOAD32  mb, 1
        LOAD32  md, AYT_K2 - AYT_K1
        jsr     muldiv
        COPY32  ayt_tw, mp
        ; E = D1 - K1 t (signed)
        COPY32  ma, ayt_tw
        LOAD32  mb, AYT_K1
        LOAD32  md, 1
        jsr     muldiv
        SUB32   ayt_e, ayt_d1, mp
        ; s = frame x FRAMES / (cF x 13)
        COPY32  ma, ayt_cf
        LOAD32  mb, SPIN_CYCLES
        LOAD32  md, 1
        jsr     muldiv
        COPY32  md, mp
        COPY32  ma, fmc
        LOAD32  mb, AYT_FRAMES
        jsr     muldiv
        COPY32  ayt_s, mp
        ; W, 0 when a write opens no window (FW-S1) or below 0
        stz     ayt_w10
        stz     ayt_w10+1
        stz     ayt_w10+2
        stz     ayt_w10+3
        LOAD32  t32, FWS1_LIMIT
        SUB32   t32, ayt_tw, t32
        bcs     @window
        rts                             ; t < FWS1_LIMIT
@window:
        ; W x 10 = (E + 12000 - 6 s) x 10 / (1000 - s)
        COPY32  ma, ayt_s
        LOAD32  mb, 6
        LOAD32  md, 1
        jsr     muldiv
        LOAD32  t32, 12000
        ADD32   t32, t32, ayt_e
        SUB32   ma, t32, mp
        lda     ma+3
        bmi     @done                   ; below 0: W = 0
        LOAD32  mb, 10
        LOAD32  t32, 1000
        SUB32   md, t32, ayt_s
        jsr     muldiv
        COPY32  ayt_w10, mp
@done:  rts

; w10_at_least: carry set when ayt_w10 >= Y:X (A is kept)
w10_at_least:
        pha
        lda     ayt_w10+2
        ora     ayt_w10+3
        bne     @yes
        cpx     #0                      ; (sets carry)
        lda     ayt_w10
        stx     t32
        sty     t32+1
        cmp     t32
        lda     ayt_w10+1
        sbc     t32+1
        pla
        rts
@yes:   pla
        sec
        rts

; muldiv: mp = ma x mb / md, rounded to the nearest (the quotient must fit
; 32 bits); mb is consumed
muldiv:
        ldx     #7
:       stz     mp,x
        dex
        bpl     :-
        ldx     #32
@mul:   lsr     mb+3
        ror     mb+2
        ror     mb+1
        ror     mb
        bcc     @shift
        clc
        lda     mp+4
        adc     ma
        sta     mp+4
        lda     mp+5
        adc     ma+1
        sta     mp+5
        lda     mp+6
        adc     ma+2
        sta     mp+6
        lda     mp+7
        adc     ma+3
        sta     mp+7
@shift: ror     mp+7
        ror     mp+6
        ror     mp+5
        ror     mp+4
        ror     mp+3
        ror     mp+2
        ror     mp+1
        ror     mp
        dex
        bne     @mul
        lda     md+3                    ; + md / 2: rounded
        lsr     a
        sta     t32+3
        lda     md+2
        ror     a
        sta     t32+2
        lda     md+1
        ror     a
        sta     t32+1
        lda     md
        ror     a
        clc
        adc     mp
        sta     mp
        lda     t32+1
        adc     mp+1
        sta     mp+1
        lda     t32+2
        adc     mp+2
        sta     mp+2
        lda     t32+3
        adc     mp+3
        sta     mp+3
        bcc     div64
        inc     mp+4
        bne     div64
        inc     mp+5
        bne     div64
        inc     mp+6
        bne     div64
        inc     mp+7
; div64: mp (64 bits) / md: the quotient in mp+0-3, the remainder in mp+4-7
div64:  ldx     #32
@bit:   asl     mp
        rol     mp+1
        rol     mp+2
        rol     mp+3
        rol     mp+4
        rol     mp+5
        rol     mp+6
        rol     mp+7
        bcs     @sub                    ; past 32 bits: at least md
        lda     mp+4
        cmp     md
        lda     mp+5
        sbc     md+1
        lda     mp+6
        sbc     md+2
        lda     mp+7
        sbc     md+3
        bcc     @next
@sub:   sec
        lda     mp+4
        sbc     md
        sta     mp+4
        lda     mp+5
        sbc     md+1
        sta     mp+5
        lda     mp+6
        sbc     md+2
        sta     mp+6
        lda     mp+7
        sbc     md+3
        sta     mp+7
        inc     mp                      ; the quotient's bit
@next:  dex
        bne     @bit
        rts

; ---------------------------------------------------------------------------
; the screen
; ---------------------------------------------------------------------------
ayt_print:
        lda     #ROW
        ldx     #7
        jsr     clear_rows
        ldy     #ROW                    ; the heading
        jsr     row0
        lda     #<s_head
        ldx     #>s_head
        jsr     put_str
        lda     #<s_pal
        ldx     #>s_pal
        bit     ntsc
        bpl     :+
        lda     #<s_ntsc
        ldx     #>s_ntsc
:       jsr     put_str
        ldy     #ROW + 1                ; a write
        jsr     row0
        lda     #<s_write
        ldx     #>s_write
        jsr     put_str
        COPY32  ma, ayt_tw
        jsr     put_mc_us
        lda     #<s_expect
        ldx     #>s_expect
        jsr     put_str
        LOAD32  ma, 41000
        jsr     put_mc_us
        lda     ayt_verdict
        cmp     #3
        bne     @tail
        ldy     #ROW + 2                ; FW-S1: no window
        jsr     row0
        lda     #<s_notail
        ldx     #>s_notail
        jsr     put_str
        COPY32  ma, ayt_e
        stz     neg
        lda     ma+3
        bpl     :+
        inc     neg
        LOAD32  t32, 0
        SUB32   ma, t32, ayt_e
:       lda     neg
        beq     :+
        lda     #'-'
        jsr     put_char
:       jsr     put_mc_us
        bra     @expected
@tail:  ldy     #ROW + 2                ; the window: cycles and us
        jsr     row0
        lda     #<s_tail
        ldx     #>s_tail
        jsr     put_str
        COPY32  ma, ayt_w10
        jsr     put_dec1
        lda     #<s_cyc
        ldx     #>s_cyc
        jsr     put_str
        COPY32  ma, ayt_w10
        jsr     put_c10_us
        lda     #<s_us
        ldx     #>s_us
        jsr     put_str
@expected:
        ldy     #ROW + 3
        jsr     row0
        lda     #<s_exp512
        ldx     #>s_exp512
        jsr     put_str
        LOAD32  ma, 5120
        jsr     put_c10_us
        lda     #<s_default
        ldx     #>s_default
        jsr     put_str
        ldy     #ROW + 4
        jsr     row0
        lda     #<s_exp32
        ldx     #>s_exp32
        jsr     put_str
        LOAD32  ma, 320
        jsr     put_c10_us
        lda     #<s_profile
        ldx     #>s_profile
        jsr     put_str
        ldy     #ROW + 5                ; the verdict
        jsr     row0
        lda     ayt_verdict
        asl     a
        tax
        lda     verdicts+1,x
        pha
        lda     verdicts,x
        plx
        jsr     put_str
        ldy     #ROW + 6
        jsr     row0
        lda     #<s_fws1
        ldx     #>s_fws1
        jmp     put_str

row0:   ldx     #0
        jmp     put_at

; put_mc_us: ma (mc) as microseconds, one decimal: ma x bps / 10^8
put_mc_us:
        COPY32  mb, bps
        LOAD32  md, 100000000
        bra     put_us
; put_c10_us: ma (tenths of a cycle) as microseconds: ma x bps / 10^6
put_c10_us:
        COPY32  mb, bps
        LOAD32  md, 1000000
put_us: jsr     muldiv
        COPY32  ma, mp
        ; (falls into put_dec1)

; put_dec1: ma (unsigned) / 10, a point, ma mod 10
put_dec1:
        ldy     #0
@digit: phy
        COPY32  mp, ma
        stz     mp+4
        stz     mp+5
        stz     mp+6
        stz     mp+7
        LOAD32  md, 10
        jsr     div64
        ply
        lda     mp+4
        sta     digits,y
        iny
        COPY32  ma, mp
        cpy     #2                      ; at least "0.0"
        bcc     @digit
        lda     ma
        ora     ma+1
        ora     ma+2
        ora     ma+3
        bne     @digit
@print: dey
        lda     digits,y
        clc
        adc     #'0'
        phy
        jsr     put_char
        ply
        cpy     #1
        bne     :+
        lda     #'.'
        phy
        jsr     put_char
        ply
:       cpy     #0
        bne     @print
        rts

; ---------------------------------------------------------------------------
        .segment "MUSDATA"
fmc_pal:        .dword  312 * 65 * 1000         ; a frame, mc
fmc_ntsc:       .dword  262 * 65 * 1000
bps_pal:        .dword  984615                  ; 10^12 / 1,015,625 Hz
bps_ntsc:       .dword  979927                  ; 10^12 / 1,020,484 Hz

verdicts:       .word   s_other, s_is512, s_is32, s_isfws1

s_measuring:
        .byte   "AY TIMING: MEASURING (2 SECONDS)", 0
s_head: .byte   "AY TIMING, ", 0
s_pal:  .byte   "PAL (1,015,625 HZ)", 0
s_ntsc: .byte   "NTSC (1,020,484 HZ)", 0
s_write:.byte   "A WRITE ", 0
s_expect:
        .byte   " US, EXPECTED ", 0
s_tail: .byte   "TAIL ", 0
s_cyc:  .byte   " CYCLES = ", 0
s_us:   .byte   " US", 0
s_notail:
        .byte   "NO TAIL. A BURST'S EXTRA US: ", 0
s_exp512:
        .byte   "EXPECTED 512 = ", 0
s_default:
        .byte   " US: DEFAULT", 0
s_exp32:
        .byte   "      OR  32 = ", 0
s_profile:
        .byte   " US: DOOM PROFILE", 0
s_is512:.byte   "SO THE WINDOW IS 512: THE DEFAULT", 0
s_is32: .byte   "SO THE WINDOW IS 32: THE DOOM PROFILE", 0
s_isfws1:
        .byte   "PORT WRITES ARE NOT SLOWED: FW-S1", 0
s_other:.byte   "ANOTHER WINDOW THAN 512 OR 32", 0
s_fws1: .byte   "(FW-S1: A WRITE ABOUT 8.4 US, NO TAIL)", 0
