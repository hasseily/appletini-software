; The native record replay of the DOOM GS port (docs/NATIVE.md section 5,
; milestone 5): upstream's column records in, the 3D view's SHR bytes out,
; on today's firmware (F1.2.1) with the gather-then-draw scheme of
; docs/research/native-memory.md 5.2. README.md in this directory gives
; the design, the memory it uses and how it departs from docs/MEMORY_MAP.md.
;
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_list65.s, lists.inc): the same records and the same pixels, written
; for the 65C02. The row blocks come from our own generator
; (tools/native/rowgen.py), not from upstream's gendraw.py.
;
; Interface
;
;   nat_replay      A = the first column of the batch, X = the column after
;                   its last. The batch's records are in W at RECBUF, the
;                   first record of column c at COLLO/COLHI[c] and the end
;                   of column c at entry c + 1. The texels are where the
;                   records point: bank R_SRC+2 (a RamWorks bank) at
;                   R_SRC ($0200-$BFFF), K_TEXC in its chain's bank.
;                   Colormaps, CMPA/CMPB, TEXLO/TEXHI, the covered ranges
;                   (CVFIRST, CVEND, CVRECLO/HI: the covering record's W
;                   address) as layout.inc places them. The language card
;                   reads and writes RAM, bank 1 at $D000 selected;
;                   RAMRD, RAMWRT off; $C073 = 0; ALTZP off; decimal off.
;                   Out: the same switches; the 3D view drawn; the covered
;                   ranges of the batch's columns zeroed. A, X, Y, P lost.
;
; Per batch, in strips of whole columns:
;
;   gather  walk the records of the next columns (RAMRD off). For each
;           texture record, choose where its texels go in the stage (W
;           $8000-$BFFF) and push the stage pointer the draw will use onto
;           the list at the stage's top; queue a copy descriptor in page 1.
;           Every MAXDESC (12) descriptors, and at the strip's end, run
;           them: RAMRD on, one $C073 write per bank present, the copies,
;           RAMRD off.
;           When the next column does not fit the stage, the strip ends
;           before it.
;   draw    RAMWRT on: each column's records through the row blocks (bank
;           2), fills, the fuzz and overlay drawers (aux 0, RAMRD on);
;           covered-range cuts as upstream's. RAMWRT off, then the covered
;           ranges of the strip's columns are zeroed.
;
; A texture record's texels go to the stage one of two ways:
;
;   one texel a row  (chain step whole part >= 2 and at most 128 rows):
;                    the gather steps the texel position exactly as the
;                    row blocks do and copies the texel of each row; the
;                    draw then uses a unit step from position 127.0.
;   span             the bytes the rows can reach, from the first texel
;                    TI to TI + n * step + 1, or all 128 when that passes
;                    127; the draw uses the record's own step.

        .setcpu "65C02"
        .include "layout.inc"

        .export nat_replay, nat_hot, nat_rcode, nat_aux

; MARK n: in the profiling build (-D PROFILE, tools/native/replay_check.py
; --breakdown), the cost phase n + 1 starts: 1 the gather's walk, 2 its
; copies, 3 the draw, 4 the copies' soft-switch writes (RAMRD, $C073).
; Keeps A and the carry.
.macro MARK n
.ifdef PROFILE
        pha
        lda     #(n + 1) * 2
        sta     PHASE
        pla
.endif
.endmacro

; ---------------------------------------------------------------------------
; zero page: $48-$6F (docs/MEMORY_MAP.md section 8)
; ---------------------------------------------------------------------------
.segment "RZP": zeropage
rp:     .res 2          ; the record
re:     .res 2          ; the end of the walk: the list's end or the
                        ;   covering record
rce:    .res 2          ; the list's end, while a cut is on
col:    .res 1          ; the column being drawn
src:    .res 2          ; the texels in the stage: (src),y
cma:    .res 2          ; texel, colormap A page: (cma) is its colour
cmb:    .res 2          ; texel, colormap B page
fr:     .res 1          ; the position's fraction
sf2:    .res 1          ; twice the fraction step (low byte)
si1:    .res 1          ; the whole step
si2:    .res 1          ; the whole step + the rounded carry of sf2
tent:   .res 2          ; the block of the first row
xo:     .res 2          ; the block after the last row (patched)
xop:    .res 1          ; its first byte
cv0:    .res 1          ; the covered range: its first row,
cv0p:   .res 1          ;   + 1 (255: no cut),
cv1:    .res 1          ;   the row after it
csf:    .res 1          ; the chain's step (K_TEX: R_SF, R_SI)
csi:    .res 1
esf:    .res 1          ; the record's step as drawn
esi:    .res 1
pl:     .res 2          ; the next stage pointer (down from STAGE_END)
ta:     .res 1          ; the first row
te:     .res 1          ; the row after the last
tt:     .res 1          ; the texel position (whole part)
dsz:    .res 1          ; the size of the record

gtop:   .res 2          ; the stage's first free byte (gather)
gbank:  .res 1          ; the chain's texel bank (gather)
gdx:    .res 1          ; DESC_SIZE * the descriptors queued

; the gather's walk (RAMRD off) uses the draw's temporaries; the queued
; descriptors can run only at the end of a record, so what a record
; needs after that (gsize) is kept apart from the descriptors' own
gsrc    = xo            ; the record's texels
gptr    = esf           ; (2) the stage pointer the draw will pop
gn      = te            ; its rows
gneed   = dsz           ; the stage bytes it takes
gtf     = fr            ; its position
gti     = tt
gsize   = cv1           ; its size

; while the descriptors run (RAMRD on: only zero page, page 1 and the
; card are near), the draw's zero page holds their state
gs      = src           ; the source (a RamWorks bank)
gd      = cma           ; the destination (the stage)
gfr     = fr            ; the per-row copy's fraction and steps
gsf2    = sf2
gsi1    = si1
gsi2    = si2
gb      = xop           ; the bank of this pass
gend    = cv0           ; DESC_SIZE * the number of descriptors

; the fuzz and overlay drawers (aux 0)
frow    = ta            ; the first row
fcnt    = te            ; the count of rows (K_OVL: the nibble to keep)
fpos    = xop           ; the fuzz position (K_OVL: the colour)
fdst    = tent
fsrc    = xo

; ---------------------------------------------------------------------------
; main scratch $17C2-$17FF: batches and gather only, never read or
; written while RAMRD or RAMWRT is on
; ---------------------------------------------------------------------------
.segment "RSCR"
gcol:   .res 1          ; the next column to gather
cend:   .res 1          ; the column after the batch
sc0:    .res 1          ; the first column of the strip
cgtop:  .res 2          ; gtop, pl and gdx at the column's start
cpl:    .res 2
cgdx:   .res 1
mlo:    .res 1          ; the product's low byte, then a count

        .assert <STAGE = 0 && <STAGE_END = 0, error, "stage alignment"
        .assert R_TF = R_END + 1 && R_TI = R_TF + 1, error, "K_TEX fields"
        .assert R_SI = R_SF + 1 && R_SRC = R_SI + 1, error, "K_TEX fields"
        .assert DESC + MAXDESC * DESC_SIZE <= P1CODE, error, "page 1"

; ---------------------------------------------------------------------------
; the row blocks and tables (tools/native/rowgen.py)
; ---------------------------------------------------------------------------
        .include "rows.s"

; ---------------------------------------------------------------------------
; batches and strips ($F900 part of the card: always visible)
; ---------------------------------------------------------------------------
.segment "RCODE"
nat_rcode:

nat_replay:
        sta     gcol
        stx     cend
        bit     LCBANK2                 ; bank 2: the row blocks, the draw
        bit     LCBANK2
        ldx     #P1_SIZE - 1            ; the per-row copy loop to page 1
:       lda     p1_image,x
        sta     P1CODE,x
        dex
        bpl     :-
@strip: MARK 0
        lda     gcol
        sta     sc0
        stz     gtop
        lda     #>STAGE
        sta     gtop+1
        stz     pl
        lda     #>STAGE_END
        sta     pl+1
        stz     gdx
@next:  lda     gcol
        cmp     cend
        bcs     @full
        lda     gtop                    ; where the column starts
        sta     cgtop
        lda     gtop+1
        sta     cgtop+1
        lda     pl
        sta     cpl
        lda     pl+1
        sta     cpl+1
        lda     gdx
        sta     cgdx
        jsr     gather_column
        bcs     @over
        inc     gcol
        bra     @next
@over:  lda     cgtop                   ; the column does not fit: the
        sta     gtop                    ;   strip ends before it
        lda     cgtop+1
        sta     gtop+1
        lda     cpl
        sta     pl
        lda     cpl+1
        sta     pl+1
        lda     cgdx
        sta     gdx
        lda     gcol
        cmp     sc0
        bne     @full
        brk                             ; one column larger than the stage
        .byte   $01
@full:  jsr     run_descriptors
        jsr     draw_strip
        lda     gcol
        cmp     cend
        bcs     :+
        jmp     @strip
:       bit     LCBANK1                 ; bank 1 again
        bit     LCBANK1
        rts

; ---------------------------------------------------------------------------
; draw_strip: the columns sc0 .. gcol - 1, then their covered ranges 0
; ---------------------------------------------------------------------------
draw_strip:
        MARK 2
        sta     WRAUX                   ; the screen: aux 0 ($C073 is 0)
        stz     pl
        lda     #>STAGE_END
        sta     pl+1
        lda     sc0
@col:   cmp     gcol
        bcs     @done
        sta     col
        jsr     draw_column
        lda     col
        inc     a
        bra     @col
@done:  sta     WRMAIN
        ldx     sc0
@cv:    cpx     gcol
        bcs     @end
        stz     CVFIRST,x
        stz     CVEND,x
        inx
        bra     @cv
@end:   rts

; ---------------------------------------------------------------------------
; gather_column: the texture records of column gcol, queued. C set when
; they do not fit the stage (the caller rolls back to the column's start).
; ---------------------------------------------------------------------------
gather_column:
        ldx     gcol
        lda     COLLO,x
        sta     rp
        lda     COLHI,x
        sta     rp+1
        lda     COLLO+1,x
        sta     re
        lda     COLHI+1,x
        sta     re+1
@rec:   lda     rp
        cmp     re
        bne     @kind
        lda     rp+1
        cmp     re+1
        bne     @kind
        clc
        rts
@kind:  lda     (rp)
        beq     @tex
        cmp     #K_TEXC
        beq     @texc
        cmp     #K_FILL
        bne     @four
        lda     #FILL_SIZE
        bra     @adv
@four:  cmp     #K_FUZZ
        beq     @is4
        cmp     #K_OVL
        bne     @bad
@is4:   lda     #FUZZ_SIZE
@adv:   clc
        adc     rp
        sta     rp
        bcc     @rec
        inc     rp+1
        bra     @rec
@bad:   brk                             ; a record of unknown kind
        .byte   $02
@tex:   ldy     #R_SF                   ; a chain starts: its step, texels
        lda     (rp),y                  ;   and bank
        sta     csf
        iny
        lda     (rp),y
        sta     csi
        iny
        lda     (rp),y
        sta     gsrc
        iny
        lda     (rp),y
        sta     gsrc+1
        iny
        lda     (rp),y
        sta     gbank
        lda     #TEX_SIZE
        bra     @texture
@texc:  ldy     #R_TCSRC
        lda     (rp),y
        sta     gsrc
        iny
        lda     (rp),y
        sta     gsrc+1
        lda     #TEXC_SIZE
@texture:
        sta     gsize
        jsr     gather_texture
        bcs     @no
        lda     gsize
        bra     @adv
@no:    rts

; gather_texture: the record at rp (gsrc; the chain in gbank, csf, csi):
; its stage place, the pointer the draw will pop, its descriptor. C set:
; no room.
gather_texture:
        ldy     #R_ROW
        lda     (rp),y
        sta     ta
        iny
        lda     (rp),y                  ; n = e - a
        sec
        sbc     ta
        sta     gn
        iny
        lda     (rp),y
        sta     gtf
        iny
        lda     (rp),y
        sta     gti
        ldx     gdx
        lda     csi
        cmp     #2
        bcc     @span
        lda     gn
        cmp     #129
        bcs     @all                    ; over 128 rows at a step >= 2
        sta     gneed                   ; one texel a row: the descriptor
        sta     DESC+5,x                ;   steps as the blocks do
        lda     ta
        and     #1
        ora     #$80
        sta     DESC+6,x                ; per row; the first row's parity
        lda     gtf
        sta     DESC+7,x
        lda     gti
        sta     DESC+8,x
        lda     csf
        sta     DESC+9,x
        lda     csi
        sta     DESC+10,x
        lda     gsrc
        sta     DESC+1,x
        lda     gsrc+1
        sta     DESC+2,x
        lda     gtop
        sta     gptr
        lda     gtop+1
        sta     gptr+1
        bra     queue
@span:  jsr     span_length             ; A = the bytes, C set: all 128
        bcs     @all
        ldx     gdx
        sta     gneed
        sta     DESC+5,x
        stz     DESC+6,x
        lda     gsrc                    ; the copy starts at TI; the draw
        clc                             ;   indexes from 0: its pointer is
        adc     gti                     ;   the copy's place less TI
        sta     DESC+1,x
        lda     gsrc+1
        adc     #0
        sta     DESC+2,x
        lda     gtop
        sec
        sbc     gti
        sta     gptr
        lda     gtop+1
        sbc     #0
        sta     gptr+1
        bra     queue
@all:   ldx     gdx
        lda     #128
        sta     gneed
        sta     DESC+5,x
        stz     DESC+6,x
        lda     gsrc
        sta     DESC+1,x
        lda     gsrc+1
        sta     DESC+2,x
        lda     gtop
        sta     gptr
        lda     gtop+1
        sta     gptr+1
        ; fall through

; queue: descriptor gdx gets its bank, place and count; the pointer list
; gets gptr; gtop moves on. Runs the queue when full. C set: no room.
queue:  lda     pl+1                    ; 512 bytes or more between the
        sec                             ;   stage top and the list: room
        sbc     gtop+1
        cmp     #2
        bcs     @room
        jsr     room
        bcc     @room
        rts
@room:  ldx     gdx
        lda     gbank
        sta     DESC+0,x
        lda     gtop
        sta     DESC+3,x
        clc
        adc     gneed
        sta     gtop
        lda     gtop+1
        sta     DESC+4,x
        adc     #0
        sta     gtop+1
        lda     pl                      ; the pointer the draw pops
        sec
        sbc     #2
        sta     pl
        bcs     :+
        dec     pl+1
:       lda     gptr
        sta     (pl)
        ldy     #1
        lda     gptr+1
        sta     (pl),y
        txa
        clc
        adc     #DESC_SIZE
        sta     gdx
        cmp     #MAXDESC * DESC_SIZE
        bcc     :+
        jsr     run_descriptors
        stz     cgdx                    ; a rollback keeps what ran
:       clc
        rts

; room: C clear when gneed bytes fit between gtop and the pointer list
; with one more entry.
room:   lda     gtop                    ; gtop + gneed + 2 <= pl
        clc
        adc     gneed
        tax
        lda     gtop+1
        adc     #0
        tay
        txa
        clc
        adc     #2
        tax
        tya
        adc     #0
        cmp     pl+1
        bcc     @yes
        bne     @no
        cpx     pl
        beq     @yes
        bcc     @yes
@no:    sec
        rts
@yes:   clc
        rts

; span_length: the texels n rows at step csi.csf can reach from TI.TF, as
; a count from TI: n * csi + hi(TF + n * csf) + 2 (the last row's texel
; is at most one past the exact position after n steps), rounded up to 4
; for the unrolled copy. C set when that passes texel 127 (so all 128 are
; copied). csi is 0 or 1 here.
span_length:
        lda     gn                      ; n * csf, shift and add
        sta     mlo
        lda     #0
        ldx     #8
        lsr     mlo
@bit:   bcc     :+
        clc
        adc     csf
:       ror     a
        ror     mlo
        dex
        bne     @bit
        tax                             ; hi(n * csf + TF)
        lda     mlo
        clc
        adc     gtf
        txa
        adc     #2 + 3                  ; + 2, then round up to 4
        bcs     @far
        ldx     csi
        beq     :+
        clc
        adc     gn
        bcs     @far
:       and     #$FC
        cmp     #129
        bcs     @far
        sta     mlo
        clc                             ; TI + the count <= 128
        adc     gti
        cmp     #129
        bcs     @far
        lda     mlo
        clc
        rts
@far:   sec
        rts

; ---------------------------------------------------------------------------
; run_descriptors: the queued copies, one pass (one $C073 write) a bank
; ---------------------------------------------------------------------------
run_descriptors:
        MARK 1
        lda     gdx
        beq     @none
        sta     gend
        stz     gdx
        MARK 3
        sta     RDAUX
        MARK 1
        ldx     #0
@pass:  lda     DESC+0,x
        cmp     #$FF
        beq     @done1
        sta     gb
        MARK 3
        sta     BANKSEL
        MARK 1
        phx
@each:  lda     DESC+0,x
        cmp     gb
        bne     :+
        jsr     run_one
        lda     #$FF
        sta     DESC+0,x
:       txa
        clc
        adc     #DESC_SIZE
        tax
        cpx     gend
        bcc     @each
        plx
@done1: txa
        clc
        adc     #DESC_SIZE
        tax
        cpx     gend
        bcc     @pass
        MARK 3
        stz     BANKSEL
        sta     RDMAIN
@none:  MARK 0
        rts

; run_one: descriptor X (kept). RAMRD on, $C073 its bank.
run_one:
        lda     DESC+1,x
        sta     gs
        lda     DESC+2,x
        sta     gs+1
        lda     DESC+3,x
        sta     gd
        lda     DESC+4,x
        sta     gd+1
        lda     DESC+6,x
        bmi     @rows
        ldy     DESC+5,x                ; a span: 4-128 bytes, a multiple
        dey                             ;   of 4
@copy:  lda     (gs),y
        sta     (gd),y
        dey
        lda     (gs),y
        sta     (gd),y
        dey
        lda     (gs),y
        sta     (gd),y
        dey
        lda     (gs),y
        sta     (gd),y
        dey
        bpl     @copy
        rts
@rows:  lda     DESC+9,x                ; one texel a row: the steps as the
        asl     a                       ;   draw derives them
        sta     gsf2
        lda     DESC+10,x
        sta     gsi1
        adc     #0
        and     #$7F
        sta     gsi2
        lda     gs                      ; the loop's operands: the texels,
        sta     P1CODE+P1_S1            ;   and the stage less 256 - n (X
        sta     P1CODE+P1_S2            ;   counts from 256 - n to 0)
        lda     gs+1
        sta     P1CODE+P1_S1+1
        sta     P1CODE+P1_S2+1
        lda     gd
        clc
        adc     DESC+5,x
        sta     P1CODE+P1_D1
        sta     P1CODE+P1_D2
        lda     gd+1
        adc     #$FF
        sta     P1CODE+P1_D1+1
        sta     P1CODE+P1_D2+1
        lda     DESC+7,x                ; the position one row before the
        sta     gfr                     ;   first, as the draw starts it
        lda     DESC+6,x
        lsr     a
        lda     DESC+8,x
        bcc     @even
        pha                             ; an odd first row: one fraction
        lda     gfr                     ;   step back, the rounded carry
        sec                             ;   ahead
        sbc     DESC+9,x
        sta     gfr
        pla
        sbc     #0
        bit     DESC+9,x
        bpl     :+
        inc     a
:       and     #$7F
        tay
        lda     DESC+5,x
        eor     #$FF
        inc     a
        phx
        tax
        clc
        jsr     P1CODE+P1_ODD
        plx
        rts
@even:  tay
        lda     DESC+5,x
        eor     #$FF
        inc     a
        phx
        tax
        clc
        jsr     P1CODE
        plx
        rts

; p1_image: the per-row copy, run from page 1 (P1CODE) with its absolute
; operands set for each descriptor (page 1 is near in every RAMRD state,
; as zero page is). Y = the texel, X from 256 - n up to 0, carry clear;
; enter at the start for an even first row, at P1_ODD for an odd one.
p1_image:
        tya
        adc     gsi2
        and     #$7F
        tay
P1_S1 = * - p1_image + 1
        lda     a:$FFFF,y
P1_D1 = * - p1_image + 1
        sta     a:$FFFF,x
        inx
        beq     p1_done
P1_ODD = * - p1_image
        lda     gfr
        adc     gsf2
        sta     gfr
        tya
        adc     gsi1
        and     #$7F
        tay
P1_S2 = * - p1_image + 1
        lda     a:$FFFF,y
P1_D2 = * - p1_image + 1
        sta     a:$FFFF,x
        inx
        bne     p1_image
p1_done:
        rts
P1_SIZE = * - p1_image
        .assert P1CODE + P1_SIZE <= P1CODE_END, error, "page 1 code"

; ---------------------------------------------------------------------------
; the fuzz and overlay records: their fields into zero page, then the
; drawer in aux 0 with RAMRD on (it reads the screen)
; ---------------------------------------------------------------------------
        .assert FUZZ_SIZE = OVL_SIZE, error, "fuzz and overlay sizes"
fuzz_or_overlay:
        ldy     #1
        lda     (rp),y
        sta     frow
        iny
        lda     (rp),y
        sta     fcnt
        iny
        lda     (rp),y
        sta     fpos
        lda     (rp)                    ; (the record is main: before
        cmp     #K_FUZZ                 ;   RAMRD goes on)
        bne     @ovl
        sta     RDAUX
        jsr     aux_fuzz
        bra     @back
@ovl:   sta     RDAUX
        jsr     aux_overlay
@back:  sta     RDMAIN
        lda     #FUZZ_SIZE
        jmp     dnext

; ---------------------------------------------------------------------------
; the draw pass: bank 2, entered only while nat_replay runs. RAMWRT on,
; RAMRD off: records, stage, colormaps and tables read from main; the
; screen written in aux 0; zero page, stack and the card as usual.
; ---------------------------------------------------------------------------
.segment "RHOT"
nat_hot:

; draw_column: the records of column col, with its covered-range cut
draw_column:
        ldx     col
        lda     COLLO,x
        sta     rp
        lda     COLHI,x
        sta     rp+1
        lda     COLLO+1,x
        sta     re
        lda     COLHI+1,x
        sta     re+1
        lda     #255                    ; no cut
        sta     cv0p
        lda     CVEND,x                 ; a covered range?
        beq     dloop
        sta     cv1
        lda     CVFIRST,x
        cmp     cv1
        bcs     dloop                   ; (255, 254: a shadow, no range)
        sta     cv0
        inc     a
        sta     cv0p
        lda     re                      ; the cut ends at the covering
        sta     rce                     ;   record
        lda     re+1
        sta     rce+1
        lda     CVRECLO,x
        sta     re
        lda     CVRECHI,x
        sta     re+1
dloop:  lda     rp
        cmp     re
        bne     drec
        lda     rp+1
        cmp     re+1
        bne     drec
        lda     cv0p                    ; at the covering record: no cut
        inc     a                       ;   from it on
        beq     dcol_done
        lda     #255
        sta     cv0p
        lda     rce
        sta     re
        lda     rce+1
        sta     re+1
drec:   lda     (rp)
        cmp     #K_OVL+1
        bcs     bad
        bit     #1
        bne     bad
        tax
        jmp     (kinds,x)
dcol_done:
        rts

kinds:  .word   dtex, dfill, bad, dtexc, fuzz_or_overlay, fuzz_or_overlay
        .assert K_TEX = 0 && K_FILL = 2 && K_TEXC = 6, error, "kinds"
        .assert K_FUZZ = 8 && K_OVL = 10, error, "kinds"
bad:    brk                             ; a record of unknown kind
        .byte   $02

; dnext: A = the size of the record at rp
dnext:  clc
        adc     rp
        sta     rp
        bcc     dloop
        inc     rp+1
        bra     dloop

; ---- K_TEX, K_TEXC ----
dtex:   ldy     #R_SF                   ; a chain: its step and colormaps
        lda     (rp),y
        sta     csf
        iny
        lda     (rp),y
        sta     csi
        ldy     #R_CMP
        lda     (rp),y
        tax
        lda     CMPA-CMAP_FIRST,x
        sta     cma+1
        lda     CMPB-CMAP_FIRST,x
        sta     cmb+1
        lda     #TEX_SIZE
        bra     dtexture
dtexc:  lda     #TEXC_SIZE
dtexture:
        sta     dsz
        lda     pl                      ; its texels in the stage
        sec
        sbc     #2
        sta     pl
        bcs     :+
        dec     pl+1
:       lda     (pl)
        sta     src
        ldy     #1
        lda     (pl),y
        sta     src+1
        lda     (rp),y                  ; the rows
        sta     ta
        iny
        lda     (rp),y
        sta     te
        sec                             ; one texel a row (the gather's
        sbc     ta                      ;   rule): a unit step from 127.0
        ldx     csi
        cpx     #2
        bcc     @own
        cmp     #129
        bcs     @own
        stz     esf
        lda     #1
        sta     esi
        stz     fr
        lda     #127
        sta     tt
        bra     @steps
@own:   lda     csf
        sta     esf
        lda     csi
        sta     esi
        ldy     #R_TF
        lda     (rp),y
        sta     fr
        iny
        lda     (rp),y
        sta     tt
@steps: lda     esf
        asl     a
        sta     sf2
        lda     esi
        sta     si1
        adc     #0
        and     #$7F
        sta     si2
        lda     te                      ; the cut (cutTex of r_list65.s)
        cmp     cv0p
        bcc     @draw                   ; ends before the covered range
        lda     ta
        cmp     cv1
        bcs     @draw                   ; starts after it: all rows
        cmp     cv0
        bcc     @low
        lda     te                      ; starts in it
        cmp     cv1
        beq     @skip
        bcc     @skip                   ; and ends in it: no rows
        jsr     advance                 ; rows c1 .. e - 1
        lda     cv1
        sta     ta
        bra     @draw
@low:   lda     te                      ; starts before it
        cmp     cv1
        beq     :+
        bcs     @draw                   ; ends after it: all rows
:       lda     cv0                     ; rows a .. c0 - 1
        sta     te
@draw:  lda     ta                      ; the position one row before the
        lsr     a                       ;   first, as pairPrepare
        bcs     @oddrow
        ldy     tt
        bra     @enter
@oddrow:
        lda     fr
        sec
        sbc     esf
        sta     fr
        lda     tt
        sbc     #0
        bit     esf
        bpl     :+
        inc     a
:       and     #$7F
        tay
@enter: ldx     ta
        lda     TEXLO,x
        sta     tent
        lda     TEXHI,x
        sta     tent+1
        ldx     te
        lda     TEXLO,x
        sta     xo
        lda     TEXHI,x
        sta     xo+1
        lda     (xo)                    ; the exit: RTS
        sta     xop
        lda     #$60
        sta     (xo)
        ldx     col
        clc
        jsr     jtent
        lda     xop
        sta     (xo)
@skip:  lda     dsz
        jmp     dnext

; (the cold helpers of the draw pass live in the $E000 part)
.segment "RCODE"

; advance: the position tt.fr moves cv1 - ta rows at esi.esf (texStart of
; r_list65.s: the product modulo 2^16, then 15 bits)
advance:
        lda     cv1
        sec
        sbc     ta
        sta     cma                     ; K (cma, cmb: free until drawn)
        lda     esf
        sta     cmb
        lda     esi
        sta     xo
@bit:   lsr     cma
        bcc     :+
        lda     fr
        clc
        adc     cmb
        sta     fr
        lda     tt
        adc     xo
        sta     tt
:       asl     cmb
        rol     xo
        lda     cma
        bne     @bit
        lda     tt
        and     #$7F
        sta     tt
        rts

jtent:  jmp     (tent)

.segment "RHOT"

; ---- K_FILL ----
dfill:  ldy     #R_ROW
        lda     (rp),y
        sta     ta
        iny
        lda     (rp),y
        sta     te
        iny                             ; R_B1: the first row's byte
        lda     ta
        lsr     a
        bcs     @odd
        lda     (rp),y
        sta     fr                      ; even rows
        iny
        lda     (rp),y
        sta     sf2                     ; odd rows
        bra     @cut
@odd:   lda     (rp),y
        sta     sf2
        iny
        lda     (rp),y
        sta     fr
@cut:   lda     te                      ; the cut (cutFill; the bytes go
        cmp     cv0p                    ;   by row parity, so fillStart's
        bcc     @draw                   ;   swap is implicit)
        lda     ta
        cmp     cv1
        bcs     @draw
        cmp     cv0
        bcc     @low
        lda     te
        cmp     cv1
        beq     @skip
        bcc     @skip
        lda     cv1
        sta     ta
        bra     @draw
@low:   lda     te
        cmp     cv1
        beq     :+
        bcs     @draw
:       lda     cv0
        sta     te
@draw:  lda     ta                      ; the even rows
        inc     a
        jsr     fill_offset
        sta     tent
        lda     te
        inc     a
        jsr     fill_offset
        cmp     tent
        beq     @odds
        ldx     #>FILLE
        ldy     fr
        jsr     fill_chain
@odds:  lda     ta                      ; the odd rows
        jsr     fill_offset
        sta     tent
        lda     te
        jsr     fill_offset
        cmp     tent
        beq     @skip
        ldx     #>FILLO
        ldy     sf2
        jsr     fill_chain
@skip:  lda     #FILL_SIZE
        jmp     dnext

.segment "RCODE"

; fill_offset: A = r -> A = 3 * (r >> 1) = (r & $FE) + (r >> 1)
fill_offset:
        tay
        lsr     a
        sta     xop
        tya
        and     #$FE
        clc
        adc     xop
        rts

; fill_chain: tent (low) to A (the exit's low byte), page X, byte Y
fill_chain:
        sta     xo
        stx     xo+1
        stx     tent+1
        lda     (xo)
        sta     xop
        lda     #$60
        sta     (xo)
        tya
        ldx     col
        jsr     jtent
        lda     xop
        sta     (xo)
        rts

; ---------------------------------------------------------------------------
; the drawers that read the screen: aux bank 0 $0200, run with RAMRD and
; RAMWRT on and $C073 = 0 (their code and tables are aux reads)
; ---------------------------------------------------------------------------
.segment "AUXCODE"
nat_aux:

; aux_fuzz: fcnt rows from frow of column col, the fuzz position fpos:
; each row takes the darker colour of the row above or below it
; (fuzzColumn and fuzzBlock of upstream: direction FZDIR[pos], then
; pos + 1 mod 50), top to bottom.
aux_fuzz:
        ldx     frow
        lda     ROWLO,x
        clc
        adc     col
        sta     fdst
        lda     ROWHI,x
        adc     #0
        sta     fdst+1
@row:   ldx     fpos
        lda     FZDIR,x
        bne     @down
        lda     fdst                    ; the row above
        sec
        sbc     #160
        sta     fsrc
        lda     fdst+1
        sbc     #0
        sta     fsrc+1
        bra     @read
@down:  lda     fdst                    ; the row below
        clc
        adc     #160
        sta     fsrc
        lda     fdst+1
        adc     #0
        sta     fsrc+1
@read:  lda     (fsrc)
        tax
        lda     FUZZDARK,x
        sta     (fdst)
        lda     fdst
        clc
        adc     #160
        sta     fdst
        bcc     :+
        inc     fdst+1
:       ldx     fpos
        inx
        cpx     #50
        bcc     :+
        ldx     #0
:       stx     fpos
        dec     fcnt
        bne     @row
        rts

; aux_overlay: the automap pixel at row frow of column col: keep the
; nibble fcnt, or in the colour fpos
aux_overlay:
        ldx     frow
        lda     ROWLO,x
        clc
        adc     col
        sta     fdst
        lda     ROWHI,x
        adc     #0
        sta     fdst+1
        lda     (fdst)
        and     fcnt
        ora     fpos
        sta     (fdst)
        rts
