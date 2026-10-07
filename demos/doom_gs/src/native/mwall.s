; mwall.s: R_RenderMaskedSegRange of the native renderer's masked phase
; (docs/RENDER-MASKED.md). A GPL-2 derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/
; r_frame65.s maskedRange, lineFlags, higher, lower, smul48, mwCols,
; mwCol, mwPost, mwNextCol, :357-637, :1060-1648; r_bsp65.s R_WallLight,
; :1036-1058): the same records, written for the 65C02 with the native
; level (the seg, side and sectors fetched from LVSEG and LVMAP), the
; openings read through the far layer and the texture's first patch from
; the patch store (TXMP).
;
;   nm_mwall    DS_P the drawseg (its W copy), MW_X .. MW_X2 its columns
;               to draw. rw_scalestep (RW_STEP, kept for the walls of the
;               next frame) = its scalestep; spryscale = scale1 + (x1 -
;               ds->x1) rw_scalestep (the low 32 bits); texturemid: with
;               ML_DONTPEGBOTTOM the higher floor + the texture's height,
;               else the lower ceiling (the back sector's when equal), -
;               viewz, + rowoffset << 16; R_WallLight (LT_I, the fake
;               contrast; a fixed colormap's page); the patch: TXMP of
;               texturetranslation[midtexture] ($FFFF: not in the store,
;               the frame stops, ST_TEXTURE); P = texturemid * spryscale
;               and its step B = texturemid * rw_scalestep, bits 0-47 of
;               the signed products (smul48); the light of the columns
;               (PGT[startmap + 24 - d], d = min(23, spryscale >> 13): one
;               page for the range when d is the same at both of the
;               drawseg's ends, else each column's). The masked texture
;               columns of the range (the openings' low and high bytes)
;               into MTCLO, MTCHI, mfloorclip (sprbottomclip) into CLIPBUF
;               and mceilingclip (sprtopclip) into MCCLIP (main SOLIDCOL,
;               dead once the walk ends), one window each (none for a
;               marker). Each column not drawn yet (its texture column
;               $7FFF: drawn) is marked drawn, and when it has rows
;               (mceilingclip + 1 .. mfloorclip - 1) its posts become
;               records: H(b) = (sprtopscreen + $FFFF + spryscale b) >> 16
;               (spryscale's bytes 0-2, upstream's products), yl =
;               max(H(topdelta), the first row), the row after the last
;               min(H(topdelta + length), the clip); a K_TEXC when the post
;               before in this column made the column's last record and it
;               fits upstream's page (UPOFS + 7 <= 254, the page model of
;               rrec.s), else a K_TEX; the position (yl step + K) >> 1, K =
;               texturemid >> 7 - 85 step, less topdelta in the texel
;               byte; the step FSTEP_TABLE[spryscale] below 1.0, else
;               FixedReciprocal(spryscale) >> 7. After the range the marks
;               go back into the openings (two windows).

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, far_put, mul8, mul32, umul16, recip, mrec_room
        .import md_cliprun, md_phdr, smap
        .import vm_fetchc, vm_nextpost, vm_fscut, vm_cvset, vm_k85
        .export nm_mwall, pgt

        .segment "MASKW"

nm_mwall:
        lda MW_X                ; the range for md_cliprun
        sta DS_R1
        lda MW_X2
        sta DS_R2
        ldy #DS_STEP            ; rw_scalestep = ds->scalestep
        ldx #0
:       lda (DS_P),y
        sta MW_STEP,x
        sta RW_STEP,x
        iny
        inx
        cpx #4
        bne :-
        ldy #DS_SCALE1          ; spryscale = scale1 + (x1 - ds->x1) step
        ldx #0
:       lda (DS_P),y
        sta MW_SC,x
        iny
        inx
        cpx #4
        bne :-
        ldy #DS_X1
        lda MW_X
        sec
        sbc (DS_P),y
        beq @seg
        sta M_B
        stz M_B+1
        stz M_B+2
        stz M_B+3
        ldx #3
:       lda MW_STEP,x
        sta M_A,x
        dex
        bpl :-
        jsr mul32
        clc
        ldx #0
:       lda MW_SC,x
        adc M_R,x
        sta MW_SC,x
        inx
        txa
        eor #4                  ; (keeps the carry)
        bne :-
@seg:   ; the seg: SEGBASE + 24 seg (8 seg + 16 seg)
        ldy #DS_SEG
        lda (DS_P),y
        sta MD_T
        iny
        lda (DS_P),y
        sta MD_T+1
        ldx #3
:       asl MD_T
        rol MD_T+1
        dex
        bne :-
        lda MD_T
        asl a
        sta FA_SRC
        lda MD_T+1
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc MD_T
        sta FA_SRC
        lda FA_SRC+1
        adc MD_T+1
        sta FA_SRC+1
        lda #<SEGBASE
        ldx #>SEGBASE
        jsr addsrc
        lda #LVSEG
        sta FA_BANK
        lda #<SEGB
        ldx #>SEGB
        ldy #SEG_SIZE
        jsr getinto
        ; its side: SIDEBASE + 8 side
        lda SEGB+SEG_SIDE
        sta FA_SRC
        lda SEGB+SEG_SIDE+1
        ldx #3
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        lda #<SIDEBASE
        ldx #>SIDEBASE
        jsr addsrc
        lda #LVMAP
        sta FA_BANK
        lda #<SIDEB
        ldx #>SIDEB
        ldy #SIDE_SIZE
        jsr getinto
        ; the front and back sectors: SECBASE + 16 n
        lda SEGB+SEG_FRONT
        jsr secsrc
        lda #<MSEC_F
        ldx #>MSEC_F
        ldy #SEC_SIZE
        jsr getinto
        lda SEGB+SEG_BACK
        jsr secsrc
        lda #<MSEC_B
        ldx #>MSEC_B
        ldy #SEC_SIZE
        jsr getinto
        ; the texture and its width mask
        ldx SIDEB+SIDE_MID      ; texnum = texturetranslation[midtexture]
        lda TEXTRANS,x
        sta MW_TEX
        tax
        lda TXWM,x
        sta MW_WM
        ; texturemid
        lda SEGB+SEG_PEGS       ; ML_DONTPEGBOTTOM: the higher floor
        and #ML_DONTPEGBOTTOM
        beq @ceil
        sec                     ; back < front: the front's, else the
        lda MSEC_B+SEC_FLOOR    ;   back's
        sbc MSEC_F+SEC_FLOOR
        lda MSEC_B+SEC_FLOOR+1
        sbc MSEC_F+SEC_FLOOR+1
        lda MSEC_B+SEC_FLOOR+2
        sbc MSEC_F+SEC_FLOOR+2
        lda MSEC_B+SEC_FLOOR+3
        sbc MSEC_F+SEC_FLOOR+3
        bvc :+
        eor #$80
:       bmi :+
        ldx #MSEC_B - MSEC_F    ; the back's
        bra :++
:       ldx #0                  ; the front's
:       ldy #0
:       lda MSEC_F+SEC_FLOOR,x
        sta MW_TMID,y
        inx
        iny
        cpy #4
        bne :-
        ldx MW_TEX              ; + textureheight << 16
        clc
        lda MW_TMID+2
        adc TXHT,x
        sta MW_TMID+2
        bcc @tm
        inc MW_TMID+3
        bra @tm
@ceil:  sec                     ; front < back: the front's, else the back's
        lda MSEC_F+SEC_CEIL
        sbc MSEC_B+SEC_CEIL
        lda MSEC_F+SEC_CEIL+1
        sbc MSEC_B+SEC_CEIL+1
        lda MSEC_F+SEC_CEIL+2
        sbc MSEC_B+SEC_CEIL+2
        lda MSEC_F+SEC_CEIL+3
        sbc MSEC_B+SEC_CEIL+3
        bvc :+
        eor #$80
:       bmi :+
        ldx #MSEC_B - MSEC_F    ; the back's
        bra :++
:       ldx #0                  ; the front's
:       ldy #0
:       lda MSEC_F+SEC_CEIL,x
        sta MW_TMID,y
        inx
        iny
        cpy #4
        bne :-
@tm:    sec                     ; - viewz, + rowoffset << 16
        lda MW_TMID
        sbc VIEWZ
        sta MW_TMID
        lda MW_TMID+1
        sbc VIEWZ+1
        sta MW_TMID+1
        lda MW_TMID+2
        sbc VIEWZ+2
        tax
        lda MW_TMID+3
        sbc VIEWZ+3
        tay
        clc
        txa
        adc SIDEB+SIDE_ROWOFS
        sta MW_TMID+2
        tya
        adc SIDEB+SIDE_ROWOFS+1
        sta MW_TMID+3
        ; R_WallLight: LT_I = (light >> 4) + LT_BASE, + 1 when the normal
        ; angle (the seg's + $4000) & $7FFF is 0, - 1 when it is $4000
        lda MSEC_F+SEC_LIGHT
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc LT_BASE
        sta LT_I
        lda LT_BASE+1
        adc #0
        sta LT_I+1
        lda SEGB+SEG_ANGLE
        bne @light
        lda SEGB+SEG_ANGLE+1
        clc
        adc #$40
        and #$7F
        beq @inc
        cmp #$40
        bne @light
        lda LT_I                ; - 1
        bne :+
        dec LT_I+1
:       dec LT_I
        bra @light
@inc:   inc LT_I                ; + 1
        bne @light
        inc LT_I+1
@light: lda #CMAPA_PAGE         ; the colormap's page: a fixed colormap's,
        ldx LT_FIXED+1          ;   else full light's until the columns'
        bmi :+
        clc
        adc LT_FIXED+1
:       sta MW_CMP
        ; the patch: TXMP[texnum]
        ldx MW_TEX
        lda TXMP+256,x
        tay
        and TXMP,x
        cmp #$FF
        bne :+
        lda #ST_TEXTURE         ; not in the store
        sta STATUS
        brk
        .byte ST_TEXTURE
:       lda TXMP,x
        tax
        tya
        jsr md_phdr
        lda PHB+PH_BANK
        sta V_PB
        lda PHB+PH_ADDR
        sta V_PA
        lda PHB+PH_ADDR+1
        sta V_PA+1
        ; P = texturemid * spryscale, B = texturemid * rw_scalestep
        ldx #MW_SC
        jsr smul48
        ldx #5
:       lda MW_CL,x
        sta MW_P,x
        dex
        bpl :-
        ldx #MW_STEP
        jsr smul48
        ldx #5
:       lda MW_CL,x
        sta MW_B,x
        dex
        bpl :-
        ; the light of the columns (not with a fixed colormap)
        stz MW_LVF
        lda LT_FIXED+1
        bpl @tm7
        ldy #DS_SCALE1+2
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr mdlight
        pha                     ; d at scale1
        ldy #DS_SCALE2+2
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr mdlight
        sta MW_S2               ; d at scale2
        ldx LT_I
        lda smap,x              ; startmap + 24
        tax
        pla
        cmp MW_S2
        beq @one
        stx MW_LVF              ; two lights: each column's
        bra @tm7
@one:   txa                     ; one light: PGT[startmap + 24 - d]
        sec
        sbc MW_S2
        tax
        lda pgt,x
        sta MW_CMP
@tm7:   lda MW_TMID             ; texturemid >> 7: bits 7-22
        asl a
        lda MW_TMID+1
        rol a
        sta V_TM7
        lda MW_TMID+2
        rol a
        sta V_TM7+1
        ; the range: its masked texture columns, its clips
        lda DS_R2
        sec
        sbc DS_R1
        inc a
        sta FA_N
        ldy #DS_MASKED          ; OPENLO + masked + x1 (aux 0); the opening
        clc                     ;   index kept in MW_TMID (free now)
        lda (DS_P),y
        adc MW_X
        sta MW_TMID
        iny
        lda (DS_P),y
        adc #0
        sta MW_TMID+1
        clc
        lda MW_TMID
        adc #<OPENLO
        sta FA_SRC
        lda MW_TMID+1
        adc #>OPENLO
        sta FA_SRC+1
        stz FA_BANK
        lda #<MTCLO
        sta FA_DST
        lda #>MTCLO
        sta FA_DST+1
        jsr far_get
        clc                     ; OPENHI + masked + x1 (RENDB)
        lda MW_TMID
        adc #<OPENHI
        sta FA_SRC
        lda MW_TMID+1
        adc #>OPENHI
        sta FA_SRC+1
        lda #RENDB
        sta FA_BANK
        lda #<MTCHI
        sta FA_DST
        lda #>MTCHI
        sta FA_DST+1
        jsr far_get
        lda #<CLIPBUF           ; mfloorclip = sprbottomclip
        sta FA_DST
        lda #>CLIPBUF
        sta FA_DST+1
        ldy #DS_BOTCLIP+1
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr md_cliprun
        lda #<MCCLIP            ; mceilingclip = sprtopclip
        sta FA_DST
        lda #>MCCLIP
        sta FA_DST+1
        ldy #DS_TOPCLIP+1
        lda (DS_P),y
        tax
        dey
        lda (DS_P),y
        jsr md_cliprun
        ; the columns
        lda MW_X
        sta V_X
        stz MW_I
@col:   ldy MW_I
        lda MTCHI,y             ; $7FFF: drawn already
        cmp #$7F
        bne :+
        lda MTCLO,y
        cmp #$FF
        beq @next
:       lda MTCLO,y             ; xc & the width mask (MD_T: free until
        and MW_WM               ;   the posts' rows)
        sta MD_T
        lda #$FF                ; drawn
        sta MTCLO,y
        lda #$7F
        sta MTCHI,y
        lda CLIPBUF,y           ; the rows that can show: mceilingclip + 1
        beq @next               ;   .. mfloorclip - 1 (the clips + 1)
        dec a
        sta V_HI
        lda MCCLIP,y
        sta V_LO
        cmp V_HI
        bcs @next
        jsr mwcol
@next:  lda V_X                 ; x <= x2
        cmp MW_X2
        beq @back
        inc V_X
        inc MW_I
        clc                     ; spryscale += rw_scalestep, P += B
        ldx #0
:       lda MW_SC,x
        adc MW_STEP,x
        sta MW_SC,x
        inx
        txa
        eor #4
        bne :-
        clc
        ldx #0
:       lda MW_P,x
        adc MW_B,x
        sta MW_P,x
        inx
        txa
        eor #6
        bne :-
        jmp @col
@back:  ; the marks into the openings: the texture columns of the range
        lda DS_R2
        sec
        sbc DS_R1
        inc a
        sta FA_N
        clc
        lda MW_TMID
        adc #<OPENLO
        sta FA_DST
        lda MW_TMID+1
        adc #>OPENLO
        sta FA_DST+1
        stz FA_BANK
        lda #<MTCLO
        sta FA_SRC
        lda #>MTCLO
        sta FA_SRC+1
        jsr far_put
        clc
        lda MW_TMID
        adc #<OPENHI
        sta FA_DST
        lda MW_TMID+1
        adc #>OPENHI
        sta FA_DST+1
        lda #RENDB
        sta FA_BANK
        lda #<MTCHI
        sta FA_SRC
        lda #>MTCHI
        sta FA_SRC+1
        jmp far_put

; addsrc: FA_SRC += A:X (A low)
addsrc: clc
        adc FA_SRC
        sta FA_SRC
        txa
        adc FA_SRC+1
        sta FA_SRC+1
        rts
; secsrc: FA_SRC = SECBASE + 16 A, FA_BANK = LVMAP
secsrc: stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        sta FA_SRC
        lda #<SECBASE
        ldx #>SECBASE
        jsr addsrc
        lda #LVMAP
        sta FA_BANK
        rts
; getinto: Y bytes from FA_SRC (FA_BANK) to A:X (A low)
getinto:
        sta FA_DST
        stx FA_DST+1
        sty FA_N
        jmp far_get

; mdlight: A = d = min(23, bits 8-23 of a scale >> 5), A its byte 1, X its
; byte 2 (upstream's MDLIGHT). Changes MW_S2.
mdlight:
        cpx #3
        bcs @d23
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        sta MW_S2
        txa
        asl a
        asl a
        asl a
        ora MW_S2
        rts
@d23:   lda #23
        rts

; ---------------------------------------------------------------------------
; smul48: MW_CL .. MW_CL+5 = bits 0-47 of MW_TMID * the 4 bytes of zero
; page at X, signed (the unsigned product less b << 32 when texturemid < 0
; and texturemid << 32 when b < 0). Changes A, X, Y, MD_T, the math block.
; ---------------------------------------------------------------------------
smul48:
        ldy #0
:       lda 0,x
        sta MD_T,y
        inx
        iny
        cpy #4
        bne :-
        lda MW_TMID             ; aL bL
        sta M_A
        lda MW_TMID+1
        sta M_A+1
        lda MD_T
        sta M_B
        lda MD_T+1
        sta M_B+1
        jsr umul16
        ldx #3
:       lda M_R,x
        sta MW_CL,x
        dex
        bpl :-
        stz MW_CL+4
        stz MW_CL+5
        lda MW_TMID+2           ; aH bL, at byte 2
        sta M_A
        lda MW_TMID+3
        sta M_A+1
        jsr umul16
        jsr @add2
        lda MW_TMID             ; aL bH, at byte 2
        sta M_A
        lda MW_TMID+1
        sta M_A+1
        lda MD_T+2
        sta M_B
        lda MD_T+3
        sta M_B+1
        jsr umul16
        jsr @add2
        lda MW_TMID+2           ; aH bH: its low word at byte 4
        sta M_A
        lda MW_TMID+3
        sta M_A+1
        jsr umul16
        clc
        lda MW_CL+4
        adc M_R
        sta MW_CL+4
        lda MW_CL+5
        adc M_R+1
        sta MW_CL+5
        bit MW_TMID+3           ; the signs
        bpl :+
        sec
        lda MW_CL+4
        sbc MD_T
        sta MW_CL+4
        lda MW_CL+5
        sbc MD_T+1
        sta MW_CL+5
:       bit MD_T+3
        bpl :+
        sec
        lda MW_CL+4
        sbc MW_TMID
        sta MW_CL+4
        lda MW_CL+5
        sbc MW_TMID+1
        sta MW_CL+5
:       rts
@add2:  clc                     ; MW_CL+2 .. +5 += M_R
        lda MW_CL+2
        adc M_R
        sta MW_CL+2
        lda MW_CL+3
        adc M_R+1
        sta MW_CL+3
        lda MW_CL+4
        adc M_R+2
        sta MW_CL+4
        lda MW_CL+5
        adc M_R+3
        sta MW_CL+5
        rts

; ===========================================================================
; mwcol: the posts of column V_X (its texture column MD_T, its rows V_LO
; .. V_HI - 1) as records
; ===========================================================================
mwcol:
        ; CL = sprtopscreen + $FFFF, sprtopscreen = CENTERY << 16 - (P >> 16)
        sec
        lda #0
        sbc MW_P+2
        sta MW_CL
        lda #0
        sbc MW_P+3
        sta MW_CL+1
        lda #CENTERY
        sbc MW_P+4
        sta MW_CL+2
        lda #0
        sbc MW_P+5
        sta MW_CL+3
        clc
        lda MW_CL
        adc #$FF
        sta MW_CL
        lda MW_CL+1
        adc #$FF
        sta MW_CL+1
        lda MW_CL+2
        adc #0
        sta MW_CL+2
        lda MW_CL+3
        adc #0
        sta MW_CL+3
        lda MW_LVF              ; two lights: the column's page
        beq @step
        lda MW_SC+1
        ldx MW_SC+2
        jsr mdlight
        eor #$FF
        sec
        adc MW_LVF
        tax
        lda pgt,x
        sta MW_CMP
@step:  lda MW_SC+2             ; the step: FSTEP_TABLE[spryscale] below
        ora MW_SC+3             ;   1.0 (the entry's low byte from bank
        bne @recip              ;   FSTEP0 + (i >> 14) at $2000 + (i &
        lda MW_SC+1             ;   $3FFF), its high byte $4000 after)
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc #FSTEP0
        sta FA_BANK
        lda MW_SC
        sta FA_SRC
        lda MW_SC+1
        and #$3F
        clc
        adc #$20
        sta FA_SRC+1
        lda #<MW_ST
        ldx #0
        ldy #1
        jsr getinto
        lda FA_SRC+1
        clc
        adc #$40
        sta FA_SRC+1
        lda #<(MW_ST+1)
        ldx #0
        ldy #1
        jsr getinto
        bra @st
@recip: ldx #3                  ; FixedReciprocal(spryscale) >> 7: bits
:       lda MW_SC,x             ;   7-22
        sta M_A,x
        dex
        bpl :-
        jsr recip
        asl M_R
        rol M_R+1
        rol M_R+2
        lda M_R+1
        sta MW_ST
        lda M_R+2
        sta MW_ST+1
@st:    lda MW_ST+1             ; its half, the records' SF, SI
        lsr a
        sta MW_S2+1
        lda MW_ST
        ror a
        sta MW_S2
        lda MW_ST               ; K = texturemid >> 7 - 85 step
        sta V_F
        lda MW_ST+1
        sta V_F+1
        jsr vm_k85
        lda MD_T                ; the posts: the patch + columnofs[xc] (after
        stz MD_T+1              ;   the step's reads: far_postsc goes on
        asl a                   ;   from FA_SRC and FA_BANK)
        rol MD_T+1
        asl a
        rol MD_T+1
        clc
        adc #8
        bcc :+
        inc MD_T+1
:       clc
        adc V_PA
        sta FA_SRC
        lda MD_T+1
        adc V_PA+1
        sta FA_SRC+1
        jsr vm_fetchc
        stz MW_CONT             ; the first post of a column: a K_TEX
@post:  jsr vm_nextpost
        bcc :+
        rts
:       jsr mwrows
        bcc :+
        stz MW_CONT             ; no record: the next post is a K_TEX
        bra @post
:       ldx V_X
        jsr vm_fscut
        lda MW_ST               ; the position: (yl step + K) >> 1
        ldy V_YL
        jsr mul8
        lda M_R
        sta V_T
        lda M_R+1
        sta V_T+1
        lda MW_ST+1
        jsr mul8
        clc
        lda M_R
        adc V_T+1
        sta V_T+1
        clc
        lda V_T
        adc V_K
        sta V_T
        lda V_T+1
        adc V_K+1
        lsr a
        ror V_T
        sec                     ; TI = the texel byte - topdelta, 7 bits
        sbc V_TD
        and #$7F
        sta V_T+1
        ldx V_X
        bit MW_CONT             ; right after this column's last record, a
        bpl @tex                ;   K_TEXC when it fits the page
        lda UPOFS,x
        cmp #PAGE_ROOM - (TEXCREC_SIZE - 1) + 1
        bcs @tex
        lda #TEXCREC_SIZE
        jsr mrec_room
        lda #K_TEXC
        jsr @head
        clc                     ; the texels: the post + 3, the low word
        lda V_COL
        adc #3
        sta BATCH,y
        iny
        lda V_COL+1
        adc #0
        sta BATCH,y
        iny
        bra @cv
@tex:   lda #TEXREC_SIZE
        jsr mrec_room
        lda #K_TEX
        jsr @head
        lda MW_S2
        sta BATCH,y
        iny
        lda MW_S2+1
        sta BATCH,y
        iny
        clc                     ; the texels: the post + 3 (its bank: no
        lda V_COL               ;   lump crosses one)
        adc #3
        sta BATCH,y
        iny
        lda V_COL+1
        adc #0
        sta BATCH,y
        iny
        lda V_PB
        sta BATCH,y
        iny
        lda MW_CMP
        sta BATCH,y
        iny
@cv:    sty MRB
        jsr vm_cvset
        lda #$80                ; the next post may be a K_TEXC
        sta MW_CONT
        jmp @post
@head:  sta BATCH,y             ; kind, column, rows, TF, TI
        iny
        txa
        sta BATCH,y
        iny
        lda V_YL
        sta BATCH,y
        iny
        lda V_YH1
        sta BATCH,y
        iny
        lda V_T
        sta BATCH,y
        iny
        lda V_T+1
        sta BATCH,y
        iny
        rts

; mwrows: the post's rows V_YL .. V_YH1 - 1 within V_LO .. V_HI - 1: yl =
; max(H(topdelta), V_LO) (none from V_HI), the row after min(H(topdelta +
; length), V_HI) (none when negative or not past yl). C set: none.
mwrows:
        ldy V_TD                ; yl
        jsr hrow
        cpx #0
        bmi @cc
        bne @none               ; 256 or more: past the rows
        cmp V_LO
        bcs @yl
@cc:    lda V_LO
@yl:    cmp V_HI
        bcs @none
        sta V_YL
        lda V_TD                ; the row after
        clc
        adc V_LEN
        bcs @tall
        tay
        jsr hrow
        cpx #0
        bmi @none
        bne @fcl
        cmp V_HI
        bcc :+
@fcl:   lda V_HI
:       sta V_YH1
        cmp V_YL
        beq @none
        bcc @none
        clc
        rts
@none:  sec
        rts
@tall:  lda #ST_TALL            ; a post past texture row 255 (upstream's
        sta STATUS              ;   mwTall: I_Error)
        brk
        .byte ST_TALL

; hrow: A (low), X (high) = H(Y) = (MW_CL + spryscale's bytes 0-2 * Y) >>
; 16, 32 bits (the sum in MD_T)
hrow:
        lda MW_CL
        sta MD_T
        lda MW_CL+1
        sta MD_T+1
        lda MW_CL+2
        sta MD_T+2
        lda MW_CL+3
        sta MD_T+3
        lda MW_SC               ; s0 b at byte 0
        jsr mul8
        clc
        lda MD_T
        adc M_R
        sta MD_T
        lda MD_T+1
        adc M_R+1
        sta MD_T+1
        bcc :+
        inc MD_T+2
        bne :+
        inc MD_T+3
:       lda MW_SC+1             ; s1 b at byte 1
        jsr mul8
        clc
        lda MD_T+1
        adc M_R
        sta MD_T+1
        lda MD_T+2
        adc M_R+1
        sta MD_T+2
        bcc :+
        inc MD_T+3
:       lda MW_SC+2             ; s2 b at byte 2
        jsr mul8
        clc
        lda MD_T+2
        adc M_R
        pha
        lda MD_T+3
        adc M_R+1
        tax
        pla
        rts

; PGT[i]: the record page of colormap A for startmap + 24 - d (r_seg65.s
; PGT, rtables.py's table)
pgt:    .incbin "pgt.bin"
