; mproj.s: the sprite projection and sort of the native renderer's masked
; phase (docs/RENDER-MASKED.md).
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_thing65.s: R_AddSprites and R_ProjectSprite, :155-707, the G parts,
; gTZ, gTX, labsTZ, :713-821, :999-1245; r_wall65.s R_WallFrame's G parts,
; :1879-1917; r_frame65.s sortSprites and sortSkip, :288-347, :995-1015):
; the same vissprites in the same order, written for the 65C02 with the
; native level (RTHING, SPRFR, PHDR and the scale records of
; tools/native/levelconv.py and rtables.py, fetched whole by the far
; layer) instead of long pointers.
;
; The walk does not call R_AddSprites: it lists the sector (rbsp.s,
; nr_addsprites: SPRSEC), and nm_project projects the listed sectors'
; things here, in the walk's order. Nothing of the walk reads what the
; projection makes (RENDER-MASKED.md), so the vissprites, their
; order and the MAXVISSPRITES cut are upstream's.
;
;   nm_project  the frame block's view (VIEWX, VIEWY, VIEWZ, VIEWSIN,
;               VIEWCOS, LT_BASE, LT_FIXED), SPRSEC and SPRN, the sectors
;               (LVMAP), the things (RTH), SPRB (SPRBOUND in W), SPRFR,
;               PHDR and the scale records (SPRT). Out: NVIS vissprites
;               from VIS (40 bytes each, rlayout.VISREC). A thing whose
;               frame is not one (SPRFR_BAD: upstream reads past its
;               sprite's frames) stops the frame: STATUS = ST_SPRFRAME and
;               BRK. Changes everything of the masked phase's zero page.
;   nm_sort     R_SortVisSprites and sortSkip: FRORD = the vissprite
;               indexes by scale, the largest first, equal scales in their
;               order (an insertion sort, as the C code's); a frame that
;               skips the weapon rows (FR_SKIP) and has a shadow among its
;               vissprites does not (FR_SKIP = 0, W_WSK = 0).
;
; The arithmetic is upstream's, bit for bit: tz =
; TXH c + TYH s + G, tx = TXH s - TYH c + G, each product of a signed
; 16-bit high word and the view's sine or cosine (high word 0 or -1)
; modulo 2^32 (upstream's gTZ and gTX by Gauss's three products: the same
; value); G = G(TXL, c) + G(TYL, s) and G(TXL, s) - G(TYL, c), G(L, b) =
; hi16(L b.lo) - (b.hi != 0 ? L : 0): exact (umul16) for a thing at whole
; map units, whose G parts are the frame's (R_WallFrame), and upstream's
; qmulh, "+ 0 or 1" in the last bit, for another thing (gGZ, gGX); xl by
; qmulh and the signed product of tx's high word, or FixedMul when the low
; word of xl or of xr would be 0, or when xscale is 1.0 or more.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, umul16, umul16lo, qmulh, fixmul, mul32, pta16
        .export nm_project, nm_sort, vis_lo, vis_hi, smap, cmop
        .export sfirst_lo, sfirst_hi

.macro MARK n
.ifdef RPROF
        pha
        lda #(n) * 2
        sta PHASE
        pla
.endif
.endmacro

VS      = VIEWSIN               ; VIEWCOS = VIEWSIN + 4 (the frame block)
.assert VIEWCOS = VIEWSIN + 4, error, "VIEWCOS does not follow VIEWSIN"
YSIN    = 0                     ; Y for the sine, the cosine (VS,y)
YCOS    = 4
CENTERX = VIEWWIDTH / 2
SFR     = FETCH                 ; the thing's sprite frame (SPRFR, 24)
SSEC    = FETCH + SPRFR_SIZE    ; the listed sector's record (16)

        .segment "MASKW"

; ===========================================================================
; nm_project
; ===========================================================================
nm_project:
        stz NVIS
        lda SPRN                ; the listed sectors into W (SECLIST), one
        bne :+                  ;   window
        rts
:       sta FA_N
        lda #<SPRSEC
        sta FA_SRC
        lda #>SPRSEC
        sta FA_SRC+1
        lda #<SECLIST
        sta FA_DST
        lda #>SECLIST
        sta FA_DST+1
        stz FA_BANK             ; (aux 0)
        jsr far_get
        jsr gframe              ; the G parts of a thing at whole map units
        stz MP_SEC
@sector:
        ldx MP_SEC
        lda SECLIST,x           ; its record: SECBASE + 16 sector
        stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        clc
        adc #<SECBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SECBASE
        sta FA_SRC+1
        lda #<SSEC
        sta FA_DST
        lda #>SSEC
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #SEC_SIZE
        sta FA_N
        jsr far_get
        lda SSEC+SEC_LIGHT      ; MP_S = SMAP[(lightlevel >> 4) + LT_BASE]
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc LT_BASE
        tax
        lda smap,x
        sta MP_S
        lda SSEC+SEC_THINGS     ; the first thing
        sta MP_SLOT
        lda SSEC+SEC_THINGS+1
        sta MP_SLOT+1
@thing: lda MP_SLOT+1           ; NO_THING ($FFFF): the sector's end
        cmp #>NO_THING
        bne :+
        lda MP_SLOT
        cmp #<NO_THING
        beq @next
:       jsr project
        lda MP_TH+TH_SNEXT
        sta MP_SLOT
        lda MP_TH+TH_SNEXT+1
        sta MP_SLOT+1
        bra @thing
@next:  inc MP_SEC
        lda MP_SEC
        cmp SPRN
        bne @sector
        rts

; ---------------------------------------------------------------------------
; gframe: MP_GZ0 = G(-viewx.lo, c) + G(-viewy.lo, s), MP_GX0 = G(-viewx.lo,
; s) - G(-viewy.lo, c), exact (R_WallFrame, r_wall65.s:1879-1916)
; ---------------------------------------------------------------------------
gframe:
        sec                     ; M_A = -viewx.lo
        lda #0
        sbc VIEWX
        sta M_A
        lda #0
        sbc VIEWX+1
        sta M_A+1
        ldy #YCOS
        clc
        jsr gpart
        ldx #MP_GZ0
        jsr put32
        ldy #YSIN
        clc
        jsr gpart
        ldx #MP_GX0
        jsr put32
        sec                     ; M_A = -viewy.lo
        lda #0
        sbc VIEWY
        sta M_A
        lda #0
        sbc VIEWY+1
        sta M_A+1
        ldy #YSIN
        clc
        jsr gpart
        ldx #MP_GZ0
        jsr add32
        ldy #YCOS
        clc
        jsr gpart
        ldx #MP_GX0
        jmp sub32

; ---------------------------------------------------------------------------
; gpart: MP_T5 = G(M_A, b), b the sine (Y = YSIN) or the cosine (YCOS):
; hi16(M_A * b.lo), exact (C clear) or upstream's qmulh (C set), less
; M_A when b's high word is not 0 (a signed 32-bit value). Keeps M_A.
; ---------------------------------------------------------------------------
gpart:
        lda VS,y
        sta M_B
        lda VS+1,y
        sta M_B+1
        phy
        bcs @q
        jsr umul16
        lda M_R+2
        sta MP_T5
        lda M_R+3
        sta MP_T5+1
        bra @s
@q:     jsr qmulh
        lda M_R
        sta MP_T5
        lda M_R+1
        sta MP_T5+1
@s:     stz MP_T5+2
        stz MP_T5+3
        ply
        lda VS+2,y
        ora VS+3,y
        beq @done
        sec
        lda MP_T5
        sbc M_A
        sta MP_T5
        lda MP_T5+1
        sbc M_A+1
        sta MP_T5+1
        bcs @done
        dec MP_T5+2
        dec MP_T5+3
@done:  rts

; ---------------------------------------------------------------------------
; smulv: M_R = M_A (a signed 16-bit value) * b (the sine: Y = YSIN, or the
; cosine: YCOS; its high word 0 or -1) modulo 2^32 (gTZ's and gTX's
; products). Keeps M_A, Y.
; ---------------------------------------------------------------------------
smulv:
        lda VS,y
        sta M_B
        lda VS+1,y
        sta M_B+1
        phy
        jsr umul16
        ply
        bit M_A+1               ; M_A < 0: the high word less b.lo
        bpl :+
        sec
        lda M_R+2
        sbc M_B
        sta M_R+2
        lda M_R+3
        sbc M_B+1
        sta M_R+3
:       lda VS+2,y              ; b < 0: the high word less M_A
        ora VS+3,y
        beq :+
        sec
        lda M_R+2
        sbc M_A
        sta M_R+2
        lda M_R+3
        sbc M_A+1
        sta M_R+3
:       rts

; put32, add32, sub32: the zero-page 32-bit value at X =, +=, -= MP_T5
; (put32t, add32r, sub32r: M_R for MP_T5)
put32:  lda MP_T5
        sta 0,x
        lda MP_T5+1
        sta 1,x
        lda MP_T5+2
        sta 2,x
        lda MP_T5+3
        sta 3,x
        rts
add32:  clc
        lda 0,x
        adc MP_T5
        sta 0,x
        lda 1,x
        adc MP_T5+1
        sta 1,x
        lda 2,x
        adc MP_T5+2
        sta 2,x
        lda 3,x
        adc MP_T5+3
        sta 3,x
        rts
sub32:  sec
        lda 0,x
        sbc MP_T5
        sta 0,x
        lda 1,x
        sbc MP_T5+1
        sta 1,x
        lda 2,x
        sbc MP_T5+2
        sta 2,x
        lda 3,x
        sbc MP_T5+3
        sta 3,x
        rts
putr:   lda M_R
        sta 0,x
        lda M_R+1
        sta 1,x
        lda M_R+2
        sta 2,x
        lda M_R+3
        sta 3,x
        rts
addr:   clc
        lda 0,x
        adc M_R
        sta 0,x
        lda 1,x
        adc M_R+1
        sta 1,x
        lda 2,x
        adc M_R+2
        sta 2,x
        lda 3,x
        adc M_R+3
        sta 3,x
        rts
subr:   sec
        lda 0,x
        sbc M_R
        sta 0,x
        lda 1,x
        sbc M_R+1
        sta 1,x
        lda 2,x
        sbc M_R+2
        sta 2,x
        lda 3,x
        sbc M_R+3
        sta 3,x
        rts

; ===========================================================================
; project: R_ProjectSprite of the thing in slot MP_SLOT (its RTHING into
; MP_TH, whose SNEXT the caller reads after), with the sector's MP_S
; ===========================================================================
project:
        lda MP_SLOT             ; RTHBASE + 24 slot: 8 slot + 16 slot
        sta MP_T4
        lda MP_SLOT+1
        sta MP_T4+1
        asl MP_T4
        rol MP_T4+1
        asl MP_T4
        rol MP_T4+1
        asl MP_T4
        rol MP_T4+1
        lda MP_T4
        asl a
        sta FA_SRC
        lda MP_T4+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc MP_T4
        sta FA_SRC
        lda FA_SRC+1
        adc MP_T4+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<RTHBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>RTHBASE
        sta FA_SRC+1
        lda #<MP_TH
        sta FA_DST
        stz FA_DST+1
        lda #RTH
        sta FA_BANK
        lda #RTHING_SIZE
        sta FA_N
        jsr far_get
        ; tr_x = x - viewx, tr_y = y - viewy
        sec
        lda MP_TH+TH_X
        sbc VIEWX
        sta MP_TRX
        lda MP_TH+TH_X+1
        sbc VIEWX+1
        sta MP_TRX+1
        lda MP_TH+TH_X+2
        sbc VIEWX+2
        sta MP_TRX+2
        lda MP_TH+TH_X+3
        sbc VIEWX+3
        sta MP_TRX+3
        sec
        lda MP_TH+TH_Y
        sbc VIEWY
        sta MP_TRY
        lda MP_TH+TH_Y+1
        sbc VIEWY+1
        sta MP_TRY+1
        lda MP_TH+TH_Y+2
        sbc VIEWY+2
        sta MP_TRY+2
        lda MP_TH+TH_Y+3
        sbc VIEWY+3
        sta MP_TRY+3
        ; behind the view (gTZ, gGZcheck): TXH and c of opposite signs,
        ; and TYH and s
        lda MP_TRX+3
        eor VIEWCOS+3
        bpl @front
        lda MP_TRY+3
        eor VIEWSIN+3
        bpl @front
        rts
@front: lda MP_TH+TH_X          ; whole map units: the frame's G parts
        ora MP_TH+TH_X+1
        ora MP_TH+TH_Y
        ora MP_TH+TH_Y+1
        bne @frac
        ldx #3
:       lda MP_GZ0,x
        sta MP_GZ,x
        lda MP_GX0,x
        sta MP_GX,x
        dex
        bpl :-
        bra @tz
@frac:  lda MP_TRX              ; gGZ, gGX: upstream's qmulh
        sta M_A
        lda MP_TRX+1
        sta M_A+1
        ldy #YCOS
        sec
        jsr gpart
        ldx #MP_GZ
        jsr put32
        ldy #YSIN
        sec
        jsr gpart
        ldx #MP_GX
        jsr put32
        lda MP_TRY
        sta M_A
        lda MP_TRY+1
        sta M_A+1
        ldy #YSIN
        sec
        jsr gpart
        ldx #MP_GZ
        jsr add32
        ldy #YCOS
        sec
        jsr gpart
        ldx #MP_GX
        jsr sub32
@tz:    lda MP_TRX+2            ; tz = TXH c + TYH s + GZ
        sta M_A
        lda MP_TRX+3
        sta M_A+1
        ldy #YCOS
        jsr smulv
        ldx #MP_TZ
        jsr putr
        ldy #YSIN               ; tx = TXH s - ...
        jsr smulv
        ldx #MP_TX
        jsr putr
        lda MP_TRY+2
        sta M_A
        lda MP_TRY+3
        sta M_A+1
        ldy #YSIN
        jsr smulv
        ldx #MP_TZ
        jsr addr
        ldy #YCOS               ; ... - TYH c
        jsr smulv
        ldx #MP_TX
        jsr subr
        clc                     ; + the G parts
        ldx #0
:       lda MP_TZ,x
        adc MP_GZ,x
        sta MP_TZ,x
        inx
        txa
        eor #4
        bne :-
        clc
        ldx #0
:       lda MP_TX,x
        adc MP_GX,x
        sta MP_TX,x
        inx
        txa
        eor #4
        bne :-
        ; TZTEST: 4.0 <= tz < 1280.0, or tz = 1280.0
        sec
        lda MP_TZ+2
        sbc #4
        tax
        lda MP_TZ+3
        sbc #0
        cmp #>(MAXZ - 4)
        bcc @near
        bne @far
        cpx #<(MAXZ - 4)
        bcc @near
        bne @far
        lda MP_TZ               ; tz.hi 1280: only 1280.0
        ora MP_TZ+1
        beq @near
@far:   rts
@near:
        ; off the side, whatever the frame: K = (tz.hi >> 6) + E + tz.hi
        ; + 2 (16 bits); tx >= 0: K - tx.hi - 1 must not be negative;
        ; tx < 0: K + tx.hi
        lda MP_TH+TH_SPR
        asl a
        asl a
        tax                     ; X = sprite * 4
        lda MP_TZ+2             ; tz.hi >> 6 (tz.hi <= 1280: a byte)
        sta MP_T4
        lda MP_TZ+3
        asl MP_T4
        rol a
        asl MP_T4
        rol a
        sec                     ; + E + 1
        adc SPRB,x
        sta MP_T4
        lda SPRB+1,x
        adc #0
        sta MP_T4+1
        sec                     ; + tz.hi + 1
        lda MP_T4
        adc MP_TZ+2
        sta MP_T4
        lda MP_T4+1
        adc MP_TZ+3
        sta MP_T4+1
        bit MP_TX+3
        bmi @txneg
        clc                     ; K - tx.hi - 1
        lda MP_T4
        sbc MP_TX+2
        lda MP_T4+1
        sbc MP_TX+3
        bpl @side
        rts
@txneg: clc                     ; K + tx.hi
        lda MP_T4
        adc MP_TX+2
        lda MP_T4+1
        adc MP_TX+3
        bpl @side
        rts
@side:  ; labs(tx) > tz << 2 (labsTZ): only for tz.hi < E / 2 + 2
        lda MP_TZ+2
        cmp SPRB+2,x
        lda MP_TZ+3
        sbc SPRB+3,x
        bcs @frame
        lda MP_TZ               ; MP_T4 = tz << 2
        asl a
        sta MP_T4
        lda MP_TZ+1
        rol a
        sta MP_T4+1
        lda MP_TZ+2
        rol a
        sta MP_T4+2
        lda MP_TZ+3
        rol a
        sta MP_T4+3
        asl MP_T4
        rol MP_T4+1
        rol MP_T4+2
        rol MP_T4+3
        bit MP_TX+3
        bmi @lneg
        sec                     ; tx >= 0: (tz << 2) - tx < 0: off
        lda MP_T4
        sbc MP_TX
        lda MP_T4+1
        sbc MP_TX+1
        lda MP_T4+2
        sbc MP_TX+2
        lda MP_T4+3
        sbc MP_TX+3
        bpl @frame
        rts
@lneg:  clc                     ; tx < 0: (tz << 2) + tx < 0: off
        lda MP_T4
        adc MP_TX
        lda MP_T4+1
        adc MP_TX+1
        lda MP_T4+2
        adc MP_TX+2
        lda MP_T4+3
        adc MP_TX+3
        bpl @frame
        rts
@frame: jmp frame

; ---------------------------------------------------------------------------
; frame: the sprite frame, its rotation, the patch, and the rest of
; R_ProjectSprite (the thing passed the distance and side tests)
; ---------------------------------------------------------------------------
frame:
        ldx MP_TH+TH_SPR        ; SPRFR index = SFIRST[sprite] + (frame &
        lda MP_TH+TH_FRAME+1    ;   $7FFF)
        and #$7F
        sta MP_T4+1
        clc
        lda MP_TH+TH_FRAME
        adc sfirst_lo,x
        sta MP_T4
        lda MP_T4+1
        adc sfirst_hi,x
        sta MP_T4+1
        ; SPRFRBASE + 24 i = 8 i + 16 i
        asl MP_T4
        rol MP_T4+1
        asl MP_T4
        rol MP_T4+1
        asl MP_T4
        rol MP_T4+1
        lda MP_T4
        asl a
        sta FA_SRC
        lda MP_T4+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc MP_T4
        sta FA_SRC
        lda FA_SRC+1
        adc MP_T4+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SPRFRBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SPRFRBASE
        sta FA_SRC+1
        lda #<SFR
        sta FA_DST
        lda #>SFR
        sta FA_DST+1
        lda #SPRT
        sta FA_BANK
        lda #SPRFR_SIZE
        sta FA_N
        jsr far_get
        lda SFR+SF_FLAGS        ; upstream reads past the sprite's frames
        and #SPRFR_BAD
        beq :+
        lda #ST_SPRFRAME
        sta STATUS
        brk
        .byte ST_SPRFRAME
:       stz MP_ROT              ; the rotation for the view angle
        lda SFR+SF_ROT
        beq @rot
        lda MP_TH+TH_X+2        ; R_PointToAngle16(x.hi, y.hi) from the
        sta M_A                 ;   view's map unit
        lda MP_TH+TH_X+3
        sta M_A+1
        lda MP_TH+TH_Y+2
        sta M_A+2
        lda MP_TH+TH_Y+3
        sta M_A+3
        lda VIEWX+2
        sta M_B
        lda VIEWX+3
        sta M_B+1
        lda VIEWY+2
        sta M_B+2
        lda VIEWY+3
        sta M_B+3
        jsr pta16
        sec                     ; - (the thing's angle >> 16) + $9000,
        lda M_R                 ;   >> 13
        sbc MP_TH+TH_ANG
        lda M_R+1
        sbc MP_TH+TH_ANG+1
        clc
        adc #$90
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        sta MP_ROT
@rot:   ldx MP_ROT              ; flip = (1 << rot) & flipmask
        lda bitof,x
        and SFR+SF_FLIP
        sta MP_FLIP
        txa                     ; the patch: SFR's lump index of rot
        asl a
        tax
        lda SFR+SF_LUMPS,x
        sta MP_PATCH
        lda SFR+SF_LUMPS+1,x
        sta MP_PATCH+1
        ; its header: PHDRBASE + 16 patch
        lda MP_PATCH
        sta FA_SRC
        lda MP_PATCH+1
        ldx #4
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<PHDRBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>PHDRBASE
        sta FA_SRC+1
        lda #<MP_PH
        sta FA_DST
        stz FA_DST+1
        lda #PHDR_SIZE
        sta FA_N
        jsr far_get             ; (FA_BANK still SPRT)
        ; tx -= (flip ? width - leftoffset : leftoffset) << 16
        lda MP_FLIP
        beq @left
        sec
        lda MP_PH+PH_WIDTH
        sbc MP_PH+PH_LEFT
        sta MP_T4
        lda MP_PH+PH_WIDTH+1
        sbc MP_PH+PH_LEFT+1
        sta MP_T4+1
        bra @sub
@left:  lda MP_PH+PH_LEFT
        sta MP_T4
        lda MP_PH+PH_LEFT+1
        sta MP_T4+1
@sub:   sec
        lda MP_TX+2
        sbc MP_T4
        sta MP_TX+2
        lda MP_TX+3
        sbc MP_T4+1
        sta MP_TX+3
        ; the distance's scale record: SCALEBASE + 16 tz.hi
        lda MP_TZ+2
        sta FA_SRC
        lda MP_TZ+3
        ldx #4
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<SCALEBASE
        sta FA_SRC
        lda FA_SRC+1
        adc #>SCALEBASE
        sta FA_SRC+1
        lda #<MP_SC
        sta FA_DST
        stz FA_DST+1
        lda #SCALE_SIZE
        sta FA_N
        jsr far_get
        ; W = width * xscale (the low 32 bits): width * xs.lo, + (width *
        ; xs.hi) << 16 when xscale is 1.0 or more (wHi)
        lda MP_PH+PH_WIDTH
        sta M_A
        lda MP_PH+PH_WIDTH+1
        sta M_A+1
        lda MP_SC+SC_XS
        sta M_B
        lda MP_SC+SC_XS+1
        sta M_B+1
        jsr umul16
        ldx #MP_W
        jsr putr
        lda MP_SC+SC_XS+2
        ora MP_SC+SC_XS+3
        beq @w
        lda MP_SC+SC_XS+2
        sta M_B
        lda MP_SC+SC_XS+3
        sta M_B+1
        jsr umul16lo
        clc
        lda MP_W+2
        adc M_R
        sta MP_W+2
        lda MP_W+3
        adc M_R+1
        sta MP_W+3
@w:     ; too small: W < 1.25 ($14001)
        lda MP_W+3
        bne @wide
        lda MP_W+2
        beq @small
        cmp #1
        bne @wide
        lda MP_W+1
        cmp #$40
        bcc @small
        bne @wide
        lda MP_W
        bne @wide
@small: rts
@wide:  jmp place

; ---------------------------------------------------------------------------
; place: xl, x1, xr, and the vissprite
; ---------------------------------------------------------------------------
place:
        lda MP_SC+SC_XS+2       ; xscale 1.0 or more: FixedMul
        ora MP_SC+SC_XS+3
        bne @fixmul
        lda MP_SC+SC_XS         ; hs = qmulh(TXL, xs.lo)
        sta M_B
        lda MP_SC+SC_XS+1
        sta M_B+1
        lda MP_TX
        sta M_A
        lda MP_TX+1
        sta M_A+1
        jsr qmulh
        lda M_R
        sta MP_T4
        lda M_R+1
        sta MP_T4+1
        lda MP_TX+2             ; TXH * xs.lo, signed
        sta M_A
        lda MP_TX+3
        sta M_A+1
        jsr umul16
        bit MP_TX+3
        bpl :+
        sec
        lda M_R+2
        sbc M_B
        sta M_R+2
        lda M_R+3
        sbc M_B+1
        sta M_R+3
:       clc                     ; xl.lo = product.lo + hs
        lda M_R
        adc MP_T4
        sta MP_XL
        lda M_R+1
        adc MP_T4+1
        sta MP_XL+1
        php
        lda MP_XL               ; its low word 0: FixedMul
        ora MP_XL+1
        bne :+
        plp
        bra @fixmul
:       plp
        lda M_R+2
        adc #0
        sta MP_XL+2
        lda M_R+3
        adc #0
        sta MP_XL+3
        clc                     ; the low word of xr (xl.lo + W.lo) 0:
        lda MP_XL               ;   FixedMul
        adc MP_W
        tax
        lda MP_XL+1
        adc MP_W+1
        bne @xl
        txa
        bne @xl
@fixmul:
        ldx #3
:       lda MP_TX,x
        sta M_A,x
        lda MP_SC+SC_XS,x
        sta M_B,x
        dex
        bpl :-
        jsr fixmul
        ldx #MP_XL
        jsr putr
@xl:    clc                     ; x1 = xl.hi + CENTERX; xl += CENTERX << 16
        lda MP_XL+2
        adc #CENTERX
        sta MP_XL+2
        sta MP_X1
        lda MP_XL+3
        adc #0
        sta MP_XL+3
        sta MP_X1+1
        ; x1 > VIEWWIDTH: off the side
        sec
        lda MP_X1
        sbc #<(VIEWWIDTH + 1)
        lda MP_X1+1
        sbc #>(VIEWWIDTH + 1)
        bvc :+
        eor #$80
:       bmi :+
        rts
:       ; xr = xl + W - FRACUNIT; xr < 0: off the side
        clc
        lda MP_XL
        adc MP_W
        sta MP_XR
        lda MP_XL+1
        adc MP_W+1
        sta MP_XR+1
        lda MP_XL+2
        adc MP_W+2
        sta MP_XR+2
        lda MP_XL+3
        adc MP_W+3
        sta MP_XR+3
        lda MP_XR+2
        bne :+
        dec MP_XR+3
:       dec MP_XR+2
        bit MP_XR+3
        bpl :+
        rts
:       lda NVIS                ; no more vissprites (MAXVISSPRITES)
        cmp #MAXVIS
        bcc :+
        rts
:       tax
        lda vis_lo,x
        sta MP_VP
        lda vis_hi,x
        sta MP_VP+1
        inc NVIS
        ; x1 (0 for a negative x1), x2 (VIEWWIDTH - 1 at most)
        ldy #VR_X1
        lda MP_X1
        bit MP_X1+1
        bpl :+
        lda #0
:       sta (MP_VP),y
        ldy #VR_X2
        lda MP_XR+3
        bne @x2max
        lda MP_XR+2
        cmp #VIEWWIDTH
        bcc :+
@x2max: lda #VIEWWIDTH - 1
:       sta (MP_VP),y
        ; scale = SPRYSCALE[d], gz = z, the thing's x and y
        ldx #0
        ldy #VR_SCALE
:       lda MP_SC+SC_YS,x
        sta (MP_VP),y
        iny
        inx
        cpx #4
        bne :-
        ldx #0
        ldy #VR_GZ
:       lda MP_TH+TH_Z,x
        sta (MP_VP),y
        iny
        inx
        cpx #4
        bne :-
        ldx #0
        ldy #VR_TX
:       lda MP_TH+TH_X,x
        sta (MP_VP),y
        iny
        inx
        cpx #8                  ; (x then y: VR_TY = VR_TX + 4)
        bne :-
        ; gzt = z.hi + topoffset; texturemid = z - viewz + (topoffset << 16)
        ldy #VR_GZT
        clc
        lda MP_TH+TH_Z+2
        adc MP_PH+PH_TOP
        sta (MP_VP),y
        iny
        lda MP_TH+TH_Z+3
        adc MP_PH+PH_TOP+1
        sta (MP_VP),y
        ldy #VR_TMID
        sec
        lda MP_TH+TH_Z
        sbc VIEWZ
        sta (MP_VP),y
        iny
        lda MP_TH+TH_Z+1
        sbc VIEWZ+1
        sta (MP_VP),y
        iny
        lda MP_TH+TH_Z+2
        sbc VIEWZ+2
        tax
        lda MP_TH+TH_Z+3
        sbc VIEWZ+3
        pha
        clc
        txa
        adc MP_PH+PH_TOP
        sta (MP_VP),y
        iny
        pla
        adc MP_PH+PH_TOP+1
        sta (MP_VP),y
        ; fracstep = q + (r + t) / 5, t = (tz >> 12) & 15
        lda MP_TZ+1
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc MP_SC+SC_R          ; r + t: 0-19
        ldx #0
        cmp #5
        bcc @fq
        inx
        cmp #10
        bcc @fq
        inx
        cmp #15
        bcc @fq
        inx
@fq:    txa
        ldy #VR_FSTEP
        clc
        adc MP_SC+SC_Q
        sta (MP_VP),y
        iny
        lda MP_SC+SC_Q+1
        adc #0
        sta (MP_VP),y
        ; the patch, the slot
        ldy #VR_PATCH
        lda MP_PATCH
        sta (MP_VP),y
        iny
        lda MP_PATCH+1
        sta (MP_VP),y
        ldy #VR_SLOT
        lda MP_SLOT
        sta (MP_VP),y
        iny
        lda MP_SLOT+1
        sta (MP_VP),y
        ; xiscale = SPRISCALE[d] (negated for a flip); startfrac = 0, or
        ; (width << 16) - 1 for a flip
        ldy #VR_XISCALE
        lda MP_FLIP
        bne @flip
        ldx #0
:       lda MP_SC+SC_IS,x
        sta (MP_VP),y
        iny
        inx
        cpx #4
        bne :-
        ldy #VR_STARTFRAC
        lda #0
        sta (MP_VP),y
        iny
        sta (MP_VP),y
        iny
        sta (MP_VP),y
        iny
        sta (MP_VP),y
        bra @x1neg
@flip:  sec
        ldx #0
:       lda #0
        sbc MP_SC+SC_IS,x
        sta (MP_VP),y
        iny
        inx
        txa
        eor #4                  ; (keeps the carry)
        bne :-
        ldy #VR_STARTFRAC
        lda #$FF
        sta (MP_VP),y
        iny
        sta (MP_VP),y
        iny
        sec
        lda MP_PH+PH_WIDTH
        sbc #1
        sta (MP_VP),y
        iny
        lda MP_PH+PH_WIDTH+1
        sbc #0
        sta (MP_VP),y
@x1neg: ; x1 < 0: startfrac += xiscale * (int16_t)(-x1)
        bit MP_X1+1
        bpl @map
        ldy #VR_XISCALE
        ldx #0
:       lda (MP_VP),y
        sta M_A,x
        iny
        inx
        cpx #4
        bne :-
        sec                     ; -x1, sign extended
        lda #0
        sbc MP_X1
        sta M_B
        lda #0
        sbc MP_X1+1
        sta M_B+1
        lda #0
        bit M_B+1
        bpl :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        jsr mul32
        ldy #VR_STARTFRAC
        ldx #0
        clc
:       lda (MP_VP),y
        adc M_R,x
        sta (MP_VP),y
        iny
        inx
        txa
        eor #4                  ; (keeps the carry)
        bne :-
@map:   ; the colormap as its record page: 0 a shadow; the fixed
        ; colormap's; full bright: level 0's; else CMOP[MP_S - min(23,
        ; ((scale >> 8) & $FFFF) >> 5)]
        ldy #VR_PAGE
        lda MP_TH+TH_FLAGS
        and #1
        beq :+
        lda #0
        sta (MP_VP),y
        rts
:       lda LT_FIXED+1
        bmi :+
        clc
        adc #CMAPA_PAGE
        sta (MP_VP),y
        rts
:       bit MP_TH+TH_FRAME+1
        bpl :+
        lda #CMAPA_PAGE
        sta (MP_VP),y
        rts
:       lda MP_SC+SC_YS+2       ; (scale >> 13) & $7FF, 23 at most
        cmp #3
        bcs @d23
        asl a
        asl a
        asl a
        sta MP_T4
        lda MP_SC+SC_YS+1
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        ora MP_T4
        cmp #24
        bcc :+
@d23:   lda #23
:       sta MP_T4
        sec
        lda MP_S
        sbc MP_T4
        tax
        lda cmop,x
        sta (MP_VP),y
        rts

; ===========================================================================
; nm_sort: FRORD by scale, the largest first (sortSprites), then sortSkip
; ===========================================================================
nm_sort:
        ldx NVIS
        beq @skip
        dex
:       txa                     ; the order of the array first
        sta FRORD,x
        dex
        bpl :-
        lda #1                  ; for i = 1 .. n - 1
        sta MP_K
@i:     lda MP_K
        cmp NVIS
        bcs @skip
        tax                     ; temp = s[i], its scale in MP_FT
        lda FRORD,x
        sta MP_TMP
        tax
        lda vis_lo,x
        sta MP_VP
        lda vis_hi,x
        sta MP_VP+1
        ldy #VR_SCALE
        ldx #0
:       lda (MP_VP),y
        sta MP_FT,x
        iny
        inx
        cpx #4
        bne :-
        lda MP_K                ; j = i
        sta MP_J
@j:     ldx MP_J                ; while j > 0 and s[j - 1] < temp: s[j] =
        beq @put                ;   s[j - 1], j - 1
        lda FRORD-1,x
        sta MP_TMP2
        tax
        lda vis_lo,x
        sta MP_VP
        lda vis_hi,x
        sta MP_VP+1
        ldy #VR_SCALE           ; s[j - 1]'s scale < temp's, signed
        lda (MP_VP),y
        cmp MP_FT
        iny
        lda (MP_VP),y
        sbc MP_FT+1
        iny
        lda (MP_VP),y
        sbc MP_FT+2
        iny
        lda (MP_VP),y
        sbc MP_FT+3
        bvc :+
        eor #$80
:       bpl @put
        ldx MP_J
        lda MP_TMP2
        sta FRORD,x
        dec MP_J
        bra @j
@put:   ldx MP_J
        lda MP_TMP
        sta FRORD,x
        inc MP_K
        bra @i
@skip:  ; sortSkip: a shadow reads the rows next to its own, so a frame
        ; with one draws the weapon again
        lda FR_SKIP
        ora FR_SKIP+1
        beq @done
        ldx NVIS
        beq @done
@v:     dex
        lda vis_lo,x
        sta MP_VP
        lda vis_hi,x
        sta MP_VP+1
        ldy #VR_PAGE
        lda (MP_VP),y
        beq @shadow
        txa
        bne @v
@done:  rts
@shadow:
        stz FR_SKIP
        stz FR_SKIP+1
        stz W_WSK
        rts

; ---------------------------------------------------------------------------
; Constants: the vissprites' addresses, SMAP, CMOP (the record page of
; CMO[i], rtables.py), SFIRST (the first SPRFR record of each sprite,
; rtables.py: the frames the states use), bitOf (1 << rot)
; ---------------------------------------------------------------------------
vis_lo:
        .repeat MAXVIS, i
        .byte <(VIS + VISREC_SIZE * i)
        .endrepeat
vis_hi:
        .repeat MAXVIS, i
        .byte >(VIS + VISREC_SIZE * i)
        .endrepeat
smap:   .incbin "smap.bin"
cmop:   .incbin "cmop.bin"
sfirst_lo:
        .incbin "sfirst.bin", 0, NUMSPRITES
sfirst_hi:
        .incbin "sfirst.bin", NUMSPRITES, NUMSPRITES
bitof:  .byte 1, 2, 4, 8, 16, 32, 64, 128
