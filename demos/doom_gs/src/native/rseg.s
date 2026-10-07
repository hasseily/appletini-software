; rseg.s: R_RenderSegLoop of the native renderer (docs/RENDER.md):
; the seg's prologue, the loop's choice, genColumn,
; the masked-only loop, texCol with its exact texture u, the tiers and
; their K_TEX records, the ceiling and floor fills with their spans and
; K_FILL records. The 13 loops of segvar.inc are generated
; (tools/native/seggen.py, build/.../gen/segloops.s) and call the routines
; here.
;
; A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_seg65.s, segvar.inc): the same records, clips, spans and masked
; columns, written for the 65C02. What is not upstream's form:
;
;   - the scale of each column is not stepped in the loops: far_fstep
;     (far.s) steps it once for the seg from rw_scale - rw_scalestep, as
;     STEP8 and STEP24W do (24 bits), and writes each column's FSTEP (the
;     table read of tcScale, or fstepHigh's) and, for a seg whose light
;     varies, its light distance d (DLIGHT); the loops read them by column
;   - a record goes into the batch (rrec.s) with its column, not into a
;     column list; R_SRC is the native texel slot of the column
;     (RENDER.md)
;   - the masked texture columns go into MASKLO, MASKHI by column and to
;     the openings at the seg's end
;   - the C16 constant-row products are one product: frac = (row - 85)
;     fracstep + texturemid >> 7, the low 16 bits (two mul8), exact
;   - the C17 and C26 self-modifications are not needed: a loop calls its
;     one tier directly, and texRec takes the light from W_LV and DLW
;
; Interface
;
;   nr_segloop  the seg descriptor: SD_X (rw_x), X2END (rw_stopx), SD_*
;               (spill), the flags WMC ... WMASKED and the edges TF ... PLS
;               (the seg page); FPC, CPC (the plane colours), RW_STEP,
;               W_LCC, W_LFC, W_CEILW, W_FLOORW (the frame block). Out: the
;               records, FLOORCLIP, CEILCLIP, SOLIDCOL, DIDSOLID (set to 1
;               when a column became solid), the spans, the masked columns
;               in the openings, W_LCC ... W_FLOORW
;
; Stage C's parts are in rsky.s: a sky column (sky_col, from ceilfill and
; gencol) and a column of a patchless texture (tier_flat, from tierdraw).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"
        .include "rseg.inc"

        .import rec_room, nr_walllight, SMAP, far_fstep, sky_col, tier_flat
        .import ax_tan3, ax_tan4, ax_out
        .import umul16, umul16lo, mul8, mt_recipe
        .import v02, v04, v05, v06, v07, v08, v10, v12, v13, v14, v15
        .import v20, v28
        .export nr_segloop, segdone, gencol, texcol, drawmid, drawtop
        .export drawbot, ceilfill, floorfill, solidcol, genloop, vmask
        .export fstepcol, tier_row, tier_slot, fillrec

        .segment "RENDERW"

; ===========================================================================
; nr_segloop: R_RenderSegLoop (r_seg65.s:340-504)
; ===========================================================================
nr_segloop:
        lda SD_X                ; rw_x < rw_stopx
        cmp X2END
        bcc :+
        rts
:       lda WSEGTEX
        bne @tex
        jmp @plane

        ; the light of the walls, the tiers, the columns' FSTEP
@tex:   ldx SD_NORMAL           ; R_WallLight: W_CMP = the page of the fixed
        ldy SD_NORMAL+1         ;   colormap, or colormap A's (replaced
        lda SD_LIGHT            ;   below)
        jsr nr_walllight
        txa
        clc
        adc #CMAPA_PAGE
        sta WCMP
        lda #$FF                ; no texture column yet (W_TCX)
        sta TCX
        lda WMIDTEX             ; TIERDIR: texturemid >> 7 of each tier
        beq :+                  ;   with a texture (bits 7-22)
        jsr texslots
        lda SD_MIDMID
        asl a
        lda SD_MIDMID+1
        rol a
        sta MIDTM
        lda SD_MIDMID+2
        rol a
        sta MIDTM+1
:       lda WTOPTEX
        beq :+
        jsr texslots
        lda SD_TOPMID
        asl a
        lda SD_TOPMID+1
        rol a
        sta TOPTM
        lda SD_TOPMID+2
        rol a
        sta TOPTM+1
:       lda WBOTTEX
        beq :+
        jsr texslots
        lda SD_BOTMID
        asl a
        lda SD_BOTMID+1
        rol a
        sta BOTTM
        lda SD_BOTMID+2
        rol a
        sta BOTTM+1

        ; the light: startmap + 24 - d, d = min(23, scale >> 13), the same
        ; at both ends of the drawseg: one page (W_CMP); else each record
        ; its own (W_LV = startmap + 24); a fixed colormap keeps W_CMP
:       stz WLV
        lda LT_FIXED+1
        bpl @light
        ldx LT_I
        lda SMAP,x
        sta GT
        lda SD_SCALE+1
        ldx SD_SCALE+2
        jsr dlight
        sta GT+1
        lda SD_SCALE2+1
        ldx SD_SCALE2+2
        jsr dlight
        cmp GT+1
        beq @one
        lda GT                  ; varying light
        sta WLV
        bra @light
@one:   lda GT
        sec
        sbc GT+1
        tax
        lda PGT,x
        sta WCMP

@light: sec                     ; each column's FSTEP (and d): the scale
        lda SD_SCALE            ;   from rw_scale - rw_scalestep, 24 bits
        sbc RW_STEP
        sta GSC
        lda SD_SCALE+1
        sbc RW_STEP+1
        sta GSC+1
        lda SD_SCALE+2
        sbc RW_STEP+2
        sta GSC+2
        lda RW_STEP
        sta GSS
        lda RW_STEP+1
        sta GSS+1
        lda RW_STEP+2
        sta GSS+2
        ldx SD_X
        jsr far_fstep
        lda GFLAG               ; a scale past 64.0: fsGeneral
        beq @plane
        jsr fsgeneral

        ; the sky, the fill bytes (r_seg65.s:424-448)
@plane: stz WSKY
        lda WMC
        beq :+
        lda CPC
        cmp #$FE
        bne :+
        lda CPC+1
        cmp #$FF
        bne :+
        inc WSKY
:       lda CPC
        cmp W_LCC
        bne :+
        lda CPC+1
        cmp W_LCC+1
        beq @floor
:       lda CPC
        sta W_LCC
        ldx CPC+1
        stx W_LCC+1
        jsr fillbytes
        sta W_CEILW
        stx W_CEILW+1
@floor: lda FPC
        cmp W_LFC
        bne :+
        lda FPC+1
        cmp W_LFC+1
        beq @kind
:       lda FPC
        sta W_LFC
        ldx FPC+1
        stx W_LFC+1
        jsr fillbytes
        sta W_FLOORW
        stx W_FLOORW+1

        ; the loop: masked (genLoop, or vMask without walls or marks);
        ; else 1 top, 2 bottom, 4 markceiling, 8 markfloor, 16 mid
@kind:  stz WDID
        lda WMASKED
        beq @walls
        lda WMC
        ora WMF
        ora WTOPTEX
        ora WBOTTEX
        bne :+
        jmp vmask
:       jmp genloop
@walls: lda #0
        ldy WMF
        beq :+
        ora #8
:       ldy WMC
        beq :+
        ora #4
:       ldy WMIDTEX
        beq :+
        ora #16
        bra @go
:       ldy WBOTTEX
        beq :+
        ora #2
:       ldy WTOPTEX
        beq @go
        ora #1
@go:    asl a
        tax
        jmp (KINDTAB,x)

; texslots: A = a texture: it must have slots (levelconv.py made its
; columns); upstream makes them in the frame (tierMake), which a native
; level never needs (RENDER.md). A texture without slots stops the
; frame (ST_TEXTURE, BRK) in every build: levelconv.py converts every
; texture the level source made. Changes Y.
texslots:
        tay
        lda TXBANK,y
        bne :+
        lda #ST_TEXTURE
        sta STATUS
        brk
        .byte ST_TEXTURE
:       rts

; dlight: A = d = min(23, (X:A) >> 5), X:A = the bytes 1-2 of a scale
; (DLIGHT, r_seg65.s:102-111).
dlight: cpx #>(24 << 5)
        bcc :+
        bne @max
        cmp #<(24 << 5)
        bcs @max
:       stx GT+2                ; (X:A) >> 5 < 24: X << 3 | A >> 5
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        asl GT+2
        asl GT+2
        asl GT+2
        ora GT+2
        rts
@max:   lda #23
        rts

; fillbytes: A (low), X (high) = the fill bytes of the plane colour X:A:
; colormap B's byte of level 0 << 8 | colormap A's, 0 for no colour or
; the sky (fillBytes, r_seg65.s:1793-1805).
fillbytes:
        cpx #0
        bne @none
        tay
        lda CMAPB0,y
        tax
        lda CMAPA0,y
        rts
@none:  lda #0
        tax
        rts

; fsgeneral: the columns whose scale is past 64.0 (far_fstep flags them):
; fsGeneral (r_seg65.s:2642-2681): RECIP_TABLE of the scale's 16 bits
; from its first 1, shifted by the count - 22. Never seen: every wall
; scale is at most 64.0.
fsgeneral:
        sec
        lda SD_SCALE
        sbc RW_STEP
        sta GSC
        lda SD_SCALE+1
        sbc RW_STEP+1
        sta GSC+1
        lda SD_SCALE+2
        sbc RW_STEP+2
        sta GSC+2
        ldx SD_X
@col:   clc
        lda GSC
        adc RW_STEP
        sta GSC
        lda GSC+1
        adc RW_STEP+1
        sta GSC+1
        lda GSC+2
        adc RW_STEP+2
        sta GSC+2
        cmp #$41
        bcc @next
        stz GT+2                ; the count of shifts
        sta GT+1                ; the high word (0:byte 2), the low word
        stz GT                  ;   (GSC+1:GSC) shifted into it
        lda GSC
        sta TAN
        lda GSC+1
        sta TAN+1
@norm:  inc GT+2
        asl TAN
        rol TAN+1
        rol GT+1
        rol GT
        bpl @norm
        lda GT+1                ; RECIP_TABLE[M & $7FFF]
        sta MT_P
        lda GT
        and #$7F
        clc
        adc #>RECIPT
        sta MT_P+1
        phx
        jsr mt_recipe
        plx
        lda #22                 ; >> 22 - s (s = 8 or 9 here)
        sec
        sbc GT+2
        tay
        beq @put
@shr:   lsr MT_E+1
        ror MT_E
        dey
        bne @shr
@put:   lda MT_E
        sta FSTEPLO,x
        lda MT_E+1
        sta FSTEPHI,x
@next:  inx
        cpx X2END
        bcc @col
        rts

; KINDTAB: the loop of each kind (varTab, r_seg65.s:565-575)
KINDTAB:
        .word segdone, genloop, v02, genloop, v04, v05, v06, v07
        .word v08, genloop, v10, genloop, v12, v13, v14, v15
        .word genloop, genloop, genloop, genloop, v20, genloop, genloop
        .word genloop, genloop, genloop, genloop, genloop, v28, genloop
        .word genloop, genloop

; ===========================================================================
; segdone: after the loop (r_seg65.s:535-560): a single sided line with
; marks makes its columns solid; didsolidcol; the masked columns into the
; openings
; ===========================================================================
segdone:
        lda WMIDTEX
        beq @did
        lda WMC
        ora WMF
        beq @did
        ldx SD_X
        lda #1
:       sta SOLIDCOL,x
        inx
        cpx X2END
        bcc :-
        sta WDID
@did:   lda WDID
        beq :+
        lda #1
        sta DIDSOLID
:       lda WMASKED
        bne :+
        rts
:       clc                     ; the masked columns: openings[SD_MASKB +
        lda SD_MASKB            ;   x], low bytes in aux 0, high bytes in
        adc #<OPENLO            ;   OPENHI (RENDB)
        sta FA_DST
        lda SD_MASKB+1
        adc #>OPENLO
        sta FA_DST+1
        ldy SD_X
        sta RAMWRTON
:       lda MASKLO,y
        sta (FA_DST),y
        iny
        cpy X2END
        bcc :-
        sta RAMWRTOFF
        clc
        lda SD_MASKB
        adc #<OPENHI
        sta FA_DST
        lda SD_MASKB+1
        adc #>OPENHI
        sta FA_DST+1
        lda #RENDB
        sta RWBANK
        sta RAMWRTON
        ldy SD_X
:       lda MASKHI,y
        sta (FA_DST),y
        iny
        cpy X2END
        bcc :-
        sta RAMWRTOFF
        stz RWBANK
        rts

; ===========================================================================
; genloop, vmask (r_seg65.s:580-599)
; ===========================================================================
genloop:
        ldx SD_X
:       jsr gencol
        inx
        cpx X2END
        bcc :-
        jmp segdone

vmask:  ldx SD_X
:       jsr texcol
        lda TEXCOL
        sta MASKLO,x
        lda TEXCOL+1
        sta MASKHI,x
        inx
        cpx X2END
        bcc :-
        jmp segdone

; ===========================================================================
; gencol: genColumn (r_seg65.s:1161-1371), column X (kept), as the C
; code: the rows are signed words
; ===========================================================================
gencol:
        STEP32 TF, TS           ; yl
        sta GYL+1
        lda TF+2
        sta GYL
        STEP32 BF, BS           ; yh = bottomfrac's high word - 1
        sec
        lda BF+2
        sbc #1
        sta GYH
        lda BF+3
        sbc #0
        sta GYH+1
        lda CEILCLIP,x          ; top = cc + 1, the ceiling clip + 1
        sta GTOP
        stz GTOP+1
        sec                     ; cc = top - 1
        sbc #1
        sta GCC
        lda #0
        sbc #0
        sta GCC+1
        sec                     ; fc = the floor clip
        lda FLOORCLIP,x
        sbc #1
        sta GFC
        lda #0
        sbc #0
        sta GFC+1
        SLT16 GYL, GTOP         ; if (yl < top) yl = top
        bpl :+
        MOV16 GTOP, GYL

        ; the ceiling
:       lda WMC
        beq @floor0
        sec                     ; bottom = yl - 1
        lda GYL
        sbc #1
        sta GBOT
        lda GYL+1
        sbc #0
        sta GBOT+1
        SLT16 GBOT, GFC         ; if (bottom >= fc) bottom = fc - 1
        bmi :+
        sec
        lda GFC
        sbc #1
        sta GBOT
        lda GFC+1
        sbc #0
        sta GBOT+1
:       SLT16 GBOT, GTOP        ; top <= bottom: rows
        bmi @cc
        lda GTOP
        sta CT
        lda GBOT
        inc a
        sta CB1
        jsr ceilfill            ; (a sky ceiling: the sky)
@cc:    MOV16 GBOT, GCC         ; cc = bottom

        ; the floor
@floor0:
        sec                     ; bottom = fc - 1
        lda GFC
        sbc #1
        sta GBOT
        lda GFC+1
        sbc #0
        sta GBOT+1
        SLT16 GBOT, GYH         ; if (yh > bottom) yh = bottom
        bpl :+
        MOV16 GBOT, GYH
:       lda WMF
        beq @tex
        SLT16 GYH, GCC          ; top = max(yh, cc) + 1
        bmi :+
        MOV16 GYH, GTOP
        bra :++
:       MOV16 GCC, GTOP
:       inc GTOP
        bne :+
        inc GTOP+1
:       SLT16 GBOT, GTOP        ; top <= bottom: rows
        bmi :+
        lda GTOP
        sta FT
        lda GBOT
        inc a
        sta FCR
        jsr floorfill
:       MOV16 GTOP, GFC         ; fc = top

@tex:   lda WSEGTEX
        beq :+
        jsr texcol

        ; the walls
:       lda WMIDTEX
        beq @top
        sec                     ; rows yl .. yh: n = yh - yl + 1, 16
        lda GYH                 ;   bits, drawn when n > 0 (signed)
        sbc GYL
        tay
        lda GYH+1
        sbc GYL+1
        iny
        bne :+
        inc a
:       cmp #0
        bmi @m9
        bne @m8
        tya
        beq @m9
@m8:    sty DCCOUNT
        lda GYL
        sta YL
        jsr drawmid
@m9:    lda #VIEWHEIGHT         ; cc = 168, fc = -1
        sta GCC
        stz GCC+1
        lda #$FF
        sta GFC
        sta GFC+1
        jmp @solid

@top:   lda WTOPTEX
        bne :+
        jmp @notop
:
        STEP32 PH, PHS          ; mid = pixhigh's high word - 1
        sec
        lda PH+2
        sbc #1
        sta GMID
        lda PH+3
        sbc #0
        sta GMID+1
        SLT16 GMID, GFC         ; if (mid >= fc) mid = fc - 1
        bmi :+
        sec
        lda GFC
        sbc #1
        sta GMID
        lda GFC+1
        sbc #0
        sta GMID+1
:       SLT16 GMID, GYL         ; mid >= yl: rows yl .. mid
        bmi @t3
        sec
        lda GMID
        sbc GYL
        inc a
        sta DCCOUNT
        lda GYL
        sta YL
        jsr drawtop
        MOV16 GMID, GCC         ; cc = mid
        bra @bot
@t3:    sec                     ; cc = yl - 1
        lda GYL
        sbc #1
        sta GCC
        lda GYL+1
        sbc #0
        sta GCC+1
        bra @bot
@notop: lda WMC
        beq @bot
        sec
        lda GYL
        sbc #1
        sta GCC
        lda GYL+1
        sbc #0
        sta GCC+1

@bot:   lda WBOTTEX
        bne :+
        jmp @nobot
:
        STEP32 PL, PLS          ; mid = pixlow's high word
        lda PL+2
        sta GMID
        lda PL+3
        sta GMID+1
        SLT16 GCC, GMID         ; if (mid <= cc) mid = cc + 1
        bmi :+
        clc
        lda GCC
        adc #1
        sta GMID
        lda GCC+1
        adc #0
        sta GMID+1
:       SLT16 GYH, GMID         ; mid <= yh: rows mid .. yh
        bmi @b9
        sec
        lda GYH
        sbc GMID
        inc a
        sta DCCOUNT
        lda GMID
        sta YL
        jsr drawbot
        MOV16 GMID, GFC         ; fc = mid
        bra @solid
@b9:    clc                     ; fc = yh + 1
        lda GYH
        adc #1
        sta GFC
        lda GYH+1
        adc #0
        sta GFC+1
        bra @solid
@nobot: lda WMF
        beq @solid
        clc
        lda GYH
        adc #1
        sta GFC
        lda GYH+1
        adc #0
        sta GFC+1

        ; a column that blocks all sight is solid: fc <= cc + 1
@solid: lda WMC
        ora WMF
        beq @mask
        clc
        lda GCC
        adc #1
        sta GT
        lda GCC+1
        adc #0
        sta GT+1
        SLT16 GT, GFC
        bmi @mask
        jsr solidcol
@mask:  lda WMASKED             ; the masked texture column
        beq :+
        lda TEXCOL
        sta MASKLO,x
        lda TEXCOL+1
        sta MASKHI,x
:       lda GFC                 ; the clips + 1, clipped to -1 .. 168
        ldy GFC+1
        jsr clip8
        sta FLOORCLIP,x
        lda GCC
        ldy GCC+1
        jsr clip8
        sta CEILCLIP,x
        rts

; clip8: A = min(max(Y:A, -1), 168) + 1
clip8:  cpy #0
        bmi @neg
        bne @max
        cmp #VIEWHEIGHT + 1
        bcs @max
        inc a
        rts
@max:   lda #VIEWHEIGHT + 1
        rts
@neg:   lda #0
        rts

; solidcol: SOLIDCOL[X] = 1, a column became solid (solidColumn)
solidcol:
        lda #1
        sta SOLIDCOL,x
        sta WDID
        rts

; ===========================================================================
; texcol: texCol (r_seg65.s:1903-2013) for column X (kept): TEXCOL and
; DCFSTEP. The texture u is exact (tcexact) at the start of a span and at
; its end, 8 columns on (2 or 1 at the seg's end), linear between (8 bits
; of fraction), as upstream.
; ===========================================================================
texcol:
        txa                     ; the column after the one before?
        sec
        sbc TCX
        stx TCX
        bcc tc_new
        cmp #1
        bne tc_new
        dec UC                  ; the span's end: its exact u
        beq tc_end
        clc                     ; u += the step
        lda UF8
        adc UDF
        sta UF8
        lda TEXCOL
        adc UDI
        sta TEXCOL
        lda TEXCOL+1
        adc UDI+1
        sta TEXCOL+1
fstepcol:
        lda FSTEPLO,x           ; tcScale: the step of the column
        sta DCFSTEP
        lda FSTEPHI,x
        sta DCFSTEP+1
        rts
tc_end:   lda UN
        sta UI
        lda UN+1
        sta UI+1
        lda UN+2
        sta UI+2
        lda UN+3
        sta UI+3
        bra tc_span
tc_new:   jsr tcexact             ; u exact
        sta UI+2
        sty UI+3
        lda UF
        sta UI
        lda UF+1
        sta UI+1
tc_span:  lda UI+1                ; the running u from the span's start
        sta UF8
        lda UI+2
        sta TEXCOL
        lda UI+3
        sta TEXCOL+1
        txa                     ; the next span: 8 columns on, else 2 or
        clc                     ;   1, before the seg's end
        adc #8
        ldy #3
        cmp X2END
        bcc tc_span2
        sbc #6
        ldy #1
        cmp X2END
        bcc tc_span2
        sbc #1
        ldy #0
        cmp X2END
        bcc tc_span2
        bra fstepcol            ; the last column: no span
tc_span2: sty GT                  ; the shifts: the columns = 1 << GT
        phx
        tax
        jsr tcexact             ; the exact u of the span's end
        sta UN+2
        sty UN+3
        lda UF
        sta UN
        lda UF+1
        sta UN+1
        sec                     ; the step: (UN - UI) >> GT, 16.8
        lda UN
        sbc UI
        sta GT+2
        lda UN+1
        sbc UI+1
        sta GT+3
        lda UN+2
        sbc UI+2
        tay
        lda UN+3
        sbc UI+3
        ldx GT
        beq tc_put
tc_shift: cmp #$80                ; (signed)
        ror a
        pha
        tya
        ror a
        tay
        ror GT+3
        ror GT+2
        pla
        dex
        bne tc_shift
tc_put:   sty UDI
        sta UDI+1
        lda GT+3
        sta UDF
        ldx GT                  ; UC = the columns
        lda TCCOLS,x
        sta UC
        plx
        jmp fstepcol
TCCOLS: .byte 1, 2, 4, 8

; ---------------------------------------------------------------------------
; tcexact: A (low), Y (high) = the whole part, UF = the fraction of the
; exact u of column X (kept) (tcExact, r_seg65.s:2017-2077):
;   ang = (rw_centerangle + xtoviewangle[x]) >> 3
;   u = rw_offset -+ rw_distance * finetangent[ang], 16.16
; the tangent from the aux card (part 3, 16 bits; part 4, 32 bits), the
; products exact (TANPROD); ang >= 4096 takes RULE_TANGENT (@past).
; Changes TAN, GT+1, the math block.
; ---------------------------------------------------------------------------
tcexact:
        clc
        lda SD_CANGLE
        adc XTVLO,x
        sta GT+1
        lda SD_CANGLE+1
        adc XTVHI,x
        lsr a                   ; >> 3: A the high byte (0-31)
        ror GT+1
        lsr a
        ror GT+1
        lsr a
        ror GT+1
        phx
        cmp #>2048
        bcs @hi
        cmp #>1024
        bcs @p3a
        eor #>1023              ; 0 <= ang < 1024: part 4 [1023 - ang], +
        ldx GT+1
        pha
        txa
        eor #$FF
        tax
        pla
        jsr tan4
        bra @plus
@p3a:   eor #>2047              ; 1024 <= ang < 2048: part 3 [2047 - ang], +
        pha
        lda GT+1
        eor #$FF
        tax
        pla
        jsr tan3
@plus:  jsr tanprod             ; rw_offset + M, fraction UF
        clc
        lda GT+2
        adc SD_OFFSET
        pha
        lda GT+3
        adc SD_OFFSET+1
        tay
        pla
        plx
        rts
@hi:    cmp #>3072
        bcs @p4b
        sec                     ; 2048 <= ang < 3072: part 3 [ang - 2048], -
        sbc #>2048
        ldx GT+1
        jsr tan3
        bra @minus
@p4b:   sec                     ; 3072 <= ang: part 4 [ang - 3072], -
        sbc #>3072
        cmp #>1024
        bcs @past
        ldx GT+1
@p4m:   jsr tan4
@minus: jsr tanprod             ; rw_offset - M, fraction ~UF (u minus
        sec                     ;   M:UF, then + $FFFF / $10000)
        lda SD_OFFSET
        sbc GT+2
        pha
        lda SD_OFFSET+1
        sbc GT+3
        tay
        lda UF
        eor #$FF
        sta UF
        lda UF+1
        eor #$FF
        sta UF+1
        pla
        plx
        rts
; 4096 <= ang, a column seen from behind (upstream's `long:` read goes past
; finetangent part 4 into live data): our rule RULE_TANGENT (RENDER.md),
; the table's end: 4095 below 6144 (part 4 [1023], -), else 0
; (part 4 [1023], +)
@past:  cmp #>(6144 - 3072)
        lda #RULE_TANGENT
        tsb RULES
        lda #>1023
        ldx #<1023
        bcc @p4m
        jsr tan4
        jmp @plus

; tan3, tan4: TAN = finetangent part 3 (16 bits) or part 4 (32 bits) at
; A:X (A the high byte).
tan3:   jsr ax_tan3
        sta TAN
        sty TAN+1
        stz TAN+2
        stz TAN+3
        rts
tan4:   jsr ax_tan4
        lda ax_out
        sta TAN
        lda ax_out+1
        sta TAN+1
        lda ax_out+2
        sta TAN+2
        lda ax_out+3
        sta TAN+3
        rts

; tanprod: GT+2 (16 bits) = bits 16-31 of rw_distance * TAN, UF = bits
; 0-15 (TANPROD, r_seg65.s:1888-1901): with du the distance as unsigned,
; hi16(du * tanlo) - (d < 0 ? tanlo : 0) + lo16(du * tanhi).
tanprod:
        lda SD_DIST
        sta M_A
        lda SD_DIST+1
        sta M_A+1
        lda TAN
        sta M_B
        lda TAN+1
        sta M_B+1
        jsr umul16
        lda M_R
        sta UF
        lda M_R+1
        sta UF+1
        lda M_R+2
        sta GT+2
        lda M_R+3
        sta GT+3
        bit SD_DIST+1
        bpl :+
        sec
        lda GT+2
        sbc TAN
        sta GT+2
        lda GT+3
        sbc TAN+1
        sta GT+3
:       lda TAN+2
        ora TAN+3
        beq @done
        lda SD_DIST
        sta M_A
        lda SD_DIST+1
        sta M_A+1
        lda TAN+2
        sta M_B
        lda TAN+3
        sta M_B+1
        jsr umul16lo
        clc
        lda GT+2
        adc M_R
        sta GT+2
        lda GT+3
        adc M_R+1
        sta GT+3
@done:  rts

; ===========================================================================
; drawmid, drawtop, drawbot: the rows YL .. YL + DCCOUNT - 1 of the tier
; in column X (kept): texCol first when the column has none yet, then
; tierdraw (TIER, r_seg65.s:1495-1521)
; ===========================================================================
.macro TIER tex, tm
        cpx TCX
        beq :+
        jsr texcol
:       lda tm
        sta FRAC
        lda tm+1
        sta FRAC+1
        lda tex
        jmp tierdraw
.endmacro
drawmid:
        TIER WMIDTEX, MIDTM
drawtop:
        TIER WTOPTEX, TOPTM
drawbot:
        TIER WBOTTEX, BOTTM

; tierdraw: texture A, FRAC = its texturemid >> 7. The texels: the slot of
; the column, TXLO/TXHI[t] + 128 (TEXCOL & TXWM[t]) in bank TXBANK[t];
; frac = (row - CENTERY - 1) * fracstep + texturemid >> 7, the low 16 bits
; (the C16 products of tierDraw, r_seg65.s:4024-4311, exact whatever the
; method); then the K_TEX record (texRec, r_seg65.s:1601-1643).
tierdraw:
        tay
        lda TXBANK,y
        bpl tier_slot
        jmp tier_flat           ; patchless columns (rsky.s)
tier_slot:                      ; (A = the bank, Y = the texture)
        sta SRC+2
        lda TEXCOL              ; the column
        and TXWM,y
        lsr a                   ; * 128: the high byte col >> 1, the low
        sta GT                  ;   byte bit 0 of col at bit 7
        lda #0
        ror a
        clc
        adc TXLO,y
        sta SRC
        lda GT
        adc TXHI,y
        sta SRC+1
tier_row:                       ; (the sky's entry: SRC, FRAC, DCFSTEP set)
        lda YL                  ; r = row - 85: its magnitude, the sign
        sec
        sbc #CENTERY + 1
        bcs :+
        eor #$FF
        inc a
:       php                     ; (carry clear: r < 0)
        sta GT
        ldy DCFSTEP             ; |r| * fracstep, the low 16 bits
        jsr mul8
        lda M_R
        sta GT+2
        lda M_R+1
        sta GT+3
        lda GT
        ldy DCFSTEP+1
        jsr mul8
        clc
        lda GT+3
        adc M_R
        sta GT+3
        plp
        bcs :+
        sec                     ; r < 0: minus
        lda #0
        sbc GT+2
        sta GT+2
        lda #0
        sbc GT+3
        sta GT+3
:       clc                     ; + texturemid >> 7
        lda FRAC
        adc GT+2
        sta FRAC
        lda FRAC+1
        adc GT+3
        sta FRAC+1

; texrec: the K_TEX record of the tier in column X (kept): kind, column,
; rows, TF, TI (frac >> 1), SF, SI (fracstep >> 1), R_SRC, R_CMP (the
; seg's page, or PGT[W_LV - d] of the column).
texrec:
        lda #TEXREC_SIZE
        jsr rec_room
        lda #K_TEX
        sta BATCH,y
        iny
        txa
        sta BATCH,y
        iny
        lda YL
        sta BATCH,y
        iny
        clc
        adc DCCOUNT
        sta BATCH,y
        iny
        lda FRAC+1
        lsr a
        sta GT
        lda FRAC
        ror a
        sta BATCH,y
        iny
        lda GT
        sta BATCH,y
        iny
        lda DCFSTEP+1
        lsr a
        sta GT
        lda DCFSTEP
        ror a
        sta BATCH,y
        iny
        lda GT
        sta BATCH,y
        iny
        lda SRC
        sta BATCH,y
        iny
        lda SRC+1
        sta BATCH,y
        iny
        lda SRC+2
        sta BATCH,y
        iny
        lda WLV
        beq @cmp
        sec
        sbc DLW,x
        phy
        tay
        lda PGT,y
        ply
        bra @put
@cmp:   lda WCMP
@put:   sta BATCH,y
        iny
        sty RB
        rts

; ===========================================================================
; ceilfill, floorfill: the rows CT .. CB1 - 1 (the ceiling) or FT .. FCR -
; 1 (the floor) of column X (kept), with the spans of the frame before
; (r_seg65.s:1714-1788): a fill from the view's first row (W_TOPR) is the
; column's top span, a fill to the row after the view (W_BOTR) its bottom
; span; when the span of the frame before (stamp W_FSP) has the same
; bytes its rows are on the screen, and the record gets only the others,
; or there is none. The span of this frame (stamp W_FSC) takes its place.
; ===========================================================================
ceilfill:
        lda WSKY                ; a sky ceiling: the sky (rsky.s)
        beq :+
        jmp sky_col
:       lda CT                  ; the top span?
        cmp W_TOPR
        bne @fill
        lda FSSTT,x             ; the frame before's, with the same bytes?
        cmp W_FSP
        bne @new
        lda FSEVT,x
        cmp W_CEILW
        bne @new
        lda FSODT,x
        cmp W_CEILW+1
        bne @new
        lda FSTOP,x             ; its end: the rows above it show
        cmp CB1
        bcs @all
        sta CT                  ; the record from its end
        lda CB1
        sta FSTOP,x
        lda W_FSC
        sta FSSTT,x
        bra @fill
@all:   lda CB1                 ; all the rows show: no record
        sta FSTOP,x
        lda W_FSC
        sta FSSTT,x
        rts
@new:   lda CB1                 ; a new top span
        sta FSTOP,x
        lda W_CEILW
        sta FSEVT,x
        lda W_CEILW+1
        sta FSODT,x
        lda W_FSC
        sta FSSTT,x
@fill:  lda CT
        sta GT
        lda CB1
        sta GT+1
        lda W_CEILW
        sta GT+2
        lda W_CEILW+1
        sta GT+3
        bra fillrec

floorfill:
        lda FCR                 ; the bottom span?
        cmp W_BOTR
        bne @fill
        lda FSSTB,x
        cmp W_FSP
        bne @new
        lda FSEVB,x
        cmp W_FLOORW
        bne @new
        lda FSODB,x
        cmp W_FLOORW+1
        bne @new
        lda FSBOT,x             ; its first row: the rows from it show
        cmp FT
        beq @all
        bcc @all
        sta FCR                 ; the record to its first row
        lda FT
        sta FSBOT,x
        lda W_FSC
        sta FSSTB,x
        bra @fill
@all:   lda FT
        sta FSBOT,x
        lda W_FSC
        sta FSSTB,x
        rts
@new:   lda FT                  ; a new bottom span
        sta FSBOT,x
        lda W_FLOORW
        sta FSEVB,x
        lda W_FLOORW+1
        sta FSODB,x
        lda W_FSC
        sta FSSTB,x
@fill:  lda FT
        sta GT
        lda FCR
        sta GT+1
        lda W_FLOORW
        sta GT+2
        lda W_FLOORW+1
        sta GT+3

; fillrec: the K_FILL record of rows GT .. GT+1 - 1 of column X (kept),
; GT+2 the even rows' byte, GT+3 the odd rows': R_B1 the first row's
; (PLANEFILL, r_seg65.s:1659-1692).
fillrec:
        lda #FILLREC_SIZE
        jsr rec_room
        lda #K_FILL
        sta BATCH,y
        iny
        txa
        sta BATCH,y
        iny
        lda GT
        sta BATCH,y
        iny
        lda GT+1
        sta BATCH,y
        iny
        lda GT
        lsr a
        bcs @odd
        lda GT+2
        sta BATCH,y
        iny
        lda GT+3
        bra @b2
@odd:   lda GT+3
        sta BATCH,y
        iny
        lda GT+2
@b2:    sta BATCH,y
        iny
        sty RB
        rts

; the page of colormap A for startmap + 24 - d (PGT, r_seg65.s:3149-3171,
; from the reference's RAM by tools/native/rtables.py)
PGT:    .incbin "pgt.bin"
