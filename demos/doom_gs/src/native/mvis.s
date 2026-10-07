; mvis.s: a sprite's records in the masked phase of the native renderer
; (docs/RENDER-MASKED.md). A GPL-2
; derivative of Webifi's IIgs DOOM (build/upstream/src/iigs/r_seg65.s
; R_DrawVisSprite, visCol, visNext, visPost, visFill, :2698-3145;
; r_frame65.s wclipSprite, visColD, vrCol, vrPost, vrNext, vrFill,
; :966-990, :1696-2038; r_sprite65.s visColF, :568-719; lists.inc FSCUT,
; CVSET): the same records, written for the 65C02 with the patch store of
; tools/native/levelconv.py read through the card (mfar.s far_posts).
;
;   nm_vis      R_DrawVisSprite: DS_VP the vissprite (VIS, 40 bytes), PHB
;               its patch header, V_FCP and V_CCP the clip arrays (the
;               clips + 1, bytes: FLOORCLIP, CEILCLIP). The setup of the
;               loop page (the patch, sprtopscreen = CENTERY << 16 -
;               FixedMul(texturemid, spryscale), E - 1 of texel row -1,
;               texturemid >> 7, the step, K = texturemid >> 7 - 85
;               fracstep), then the shadow's columns (a page of 0: K_FUZZ
;               records, the fuzz position FZPOS), or in a frame that skips
;               the weapon rows the floor clip WTMP = min(WCLIP, the clip)
;               (wclipSprite) and the magnified columns (|xiscale| < 0.75,
;               not unit scale: a post is recorded into the next columns
;               that show the same texture column with the same clips) or
;               the others. The columns go on while the texture column
;               (frac >> 16) stays in the patch, not to x2: a sprite can
;               draw a column past x2 (RENDER-MASKED.md). The -D CLIPLOG
;               build (the -c objects of m11/s2ovl.mk's ovf) first logs
;               the vissprite and both clip arrays in the SEAM bank (RENDER-MASKED.md); DS_IDX
;               with bit 7 is the weapon's draw (mpsp.s), logged as $FF00
;               + the psprite.
;   vm_yrow     YHTAB[t] (t = V_T, 16 bits): (E - 1) >> 16 of texel row t,
;               E = sprtopscreen + spryscale t, filled lazily up to the
;               row a post needs (two planes YHL, YHH); V_YH0 + t at unit
;               scale. Out: A the low byte, X the high byte.
;   vm_fscut    FSCUT: the spans of column X end at the rows V_YL ..
;               V_YH1 - 1 when they reach into them.
;   vm_cvset    CVSET: the record just allocated (RSEQ) becomes column X's
;               covered range when it has more rows than the range before.
;
; The covered ranges name their record by its sequence number (RSEQ, from
; mrec_room): the bucket pass turns it into a W address (RENDER-MASKED.md).
; A shadow sets its column's range to 255, 254: none for the frame.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

.if .defined(CLIPLOG) .and .defined(LOCKSTEP)
        .error "CLIPLOG and LOCKSTEP share the SEAM bank (RENDER-MASKED.md)"
.endif

        .import fixmul, far_put, far_posts, far_postsc, mrec_room
        .import pt_n, pt_more, pt_td, pt_len, pt_lo, pt_hi
        .export nm_vis, vm_yrow, vm_fscut, vm_cvset, vm_rows, vm_fetch
        .export vm_nextpost, vm_fetchc, vm_k85, vtexrec

; the quarter-square slots (math.inc): slot 0 the step's low byte, slot 1
; its high byte (low bytes only)
.macro  SLOT0
        sta PSL0
        sta PSH0
        eor #$FF
        sta PNL0
        sta PNH0
.endmacro
.macro  SLOT1
        sta PSL1
        eor #$FF
        sta PNL1
.endmacro

        .segment "MASKW"

; ===========================================================================
; nm_vis: R_DrawVisSprite
; ===========================================================================
nm_vis:
.ifdef CLIPLOG
        jsr cl_log
.endif
        ldy #VR_PAGE            ; the page of the colormap (0: a shadow)
        lda (DS_VP),y
        sta V_CMP
        ldy #VR_X1
        lda (DS_VP),y
        sta V_X
        ldx #0
        ldy #VR_STARTFRAC       ; frac, xiscale, spryscale; texturemid and
:       lda (DS_VP),y           ;   spryscale for FixedMul
        sta V_FRAC,x
        iny
        inx
        cpx #4
        bne :-
        ldx #0
        ldy #VR_XISCALE
:       lda (DS_VP),y
        sta V_XIS,x
        iny
        inx
        cpx #4
        bne :-
        ldx #0
        ldy #VR_SCALE
:       lda (DS_VP),y
        sta V_SS,x
        sta M_B,x
        iny
        inx
        cpx #4
        bne :-
        ldx #0
        ldy #VR_TMID
:       lda (DS_VP),y
        sta M_A,x
        iny
        inx
        cpx #4
        bne :-
        jsr fixmul              ; sprtopscreen = CENTERY << 16 - the product
        sec                     ;   (V_T)
        lda #0
        sbc M_R
        sta V_T
        lda #0
        sbc M_R+1
        sta V_T+1
        lda #CENTERY
        sbc M_R+2
        sta V_T+2
        lda #0
        sbc M_R+3
        sta V_T+3
        clc                     ; E - 1 of row -1: sprtopscreen - spryscale
        lda V_T                 ;   - 1
        sbc V_SS
        sta V_E
        lda V_T+1
        sbc V_SS+1
        sta V_E+1
        lda V_T+2
        sbc V_SS+2
        sta V_E+2
        lda V_T+3
        sbc V_SS+3
        sta V_E+3
        stz V_TN
        stz V_TN+1
        stz V_UNIT              ; spryscale 1.0: V_YH0 = (sprtopscreen - 1)
        lda V_SS                ;   >> 16, no table
        ora V_SS+1
        ora V_SS+3
        bne @patch
        lda V_SS+2
        cmp #1
        bne @patch
        sta V_UNIT
        lda V_T
        ora V_T+1
        cmp #1                  ; C clear: the low word 0, one less
        lda V_T+2
        sbc #0
        sta V_YH0
        lda V_T+3
        sbc #0
        sta V_YH0+1
@patch: lda PHB+PH_BANK         ; the patch: its bank, address and width
        sta V_PB
        lda PHB+PH_ADDR
        sta V_PA
        lda PHB+PH_ADDR+1
        sta V_PA+1
        lda PHB+PH_WIDTH
        sta V_W
        lda PHB+PH_WIDTH+1
        sta V_W+1
        ldy #VR_TMID            ; texturemid >> 7: bits 7-22
        lda (DS_VP),y
        asl a
        iny
        lda (DS_VP),y
        rol a
        sta V_TM7
        iny
        lda (DS_VP),y
        rol a
        sta V_TM7+1
        ldy #VR_FSTEP           ; fracstep, its half (the records' step)
        lda (DS_VP),y
        sta V_F
        iny
        lda (DS_VP),y
        sta V_F+1
        lsr a
        sta V_S2+1
        lda V_F
        ror a
        sta V_S2
        lda V_F                 ; the slots: fL, fH
        SLOT0
        lda V_F+1
        SLOT1
        jsr vm_k85
        lda V_CMP               ; a shadow: its own columns
        bne :+
        jmp vfuzz
:       lda W_WSK               ; a frame that skips the weapon rows: the
        beq :+                  ;   sprite ends above them
        jsr vwclip
:       lda V_UNIT              ; |xiscale| < 0.75, not unit scale: the
        bne @vis                ;   magnified columns
        lda V_XIS+2
        ora V_XIS+3
        bne @neg
        lda V_XIS+1             ; 0 <= xiscale < $C000
        cmp #$C0
        bcs @vis
@mag:   jmp vmag
@neg:   lda V_XIS+2             ; -$C000 < xiscale: the high word $FFFF
        and V_XIS+3             ;   and the low one $4001 or more
        cmp #$FF
        bne @vis
        lda V_XIS+1
        cmp #$40
        bcc @vis
        bne @mag
        lda V_XIS
        bne @mag
@vis:   jmp vcols

; ---------------------------------------------------------------------------
; vm_k85: V_K = V_TM7 - 85 V_F, 16 bits (85 = 64 + 16 + 4 + 1). Changes A,
; X, V_T.
; ---------------------------------------------------------------------------
vm_k85:
        lda V_F
        sta V_T
        lda V_F+1
        sta V_T+1
        lda V_F
        sta V_T+2
        lda V_F+1
        ldx #2                  ; V_T+2:A = 4 f
:       asl V_T+2
        rol a
        dex
        bne :-
        sta V_T+3
        jsr @add                ; f + 4 f
        ldx #2
:       asl V_T+2
        rol V_T+3
        dex
        bne :-
        jsr @add                ; + 16 f
        ldx #2
:       asl V_T+2
        rol V_T+3
        dex
        bne :-
        jsr @add                ; + 64 f
        sec
        lda V_TM7
        sbc V_T
        sta V_K
        lda V_TM7+1
        sbc V_T+1
        sta V_K+1
        rts
@add:   clc                     ; V_T += V_T+2 (16 bits)
        lda V_T
        adc V_T+2
        sta V_T
        lda V_T+1
        adc V_T+3
        sta V_T+1
        rts

; ---------------------------------------------------------------------------
; vwclip: wclipSprite: WTMP = min(WCLIP, the floor clip) for the columns
; x1 .. min(x2 + 1, 159) (the column past x2 included), V_FCP = WTMP
; ---------------------------------------------------------------------------
vwclip:
        lda SP_X2               ; the end: min(x2 + 2, 160)
        clc
        adc #2
        cmp #VIEWWIDTH + 1
        bcc :+
        lda #VIEWWIDTH
:       sta V_T
        ldy V_X
@x:     cpy V_T
        bcs @done
        lda WCLIP,y
        cmp (V_FCP),y
        bcc :+
        lda (V_FCP),y
:       sta WTMP,y
        iny
        bra @x
@done:  lda #<WTMP
        sta V_FCP
        lda #>WTMP
        sta V_FCP+1
        rts

; ---------------------------------------------------------------------------
; vm_fetch: the posts of the texture column frac >> 16 (the card's buffer:
; far_posts), V_PI = 0. The column entry is the patch + 4 c + 8 (16 bits).
; ---------------------------------------------------------------------------
vm_fetch:
        lda V_FRAC+2            ; 4 c + 8
        asl a
        sta FA_SRC
        lda V_FRAC+3
        rol a
        asl FA_SRC
        rol a
        tax
        clc
        lda FA_SRC
        adc #8
        bcc :+
        inx
:       clc
        adc V_PA
        sta FA_SRC
        txa
        adc V_PA+1
        sta FA_SRC+1
vm_fetchc:                      ; (FA_SRC set: a masked wall's column)
        lda V_PA
        sta FA_DST
        lda V_PA+1
        sta FA_DST+1
        lda V_PB
        sta FA_BANK
        jsr far_posts
        stz V_PI
        rts

; ---------------------------------------------------------------------------
; vm_nextpost: the next post of the column into V_TD, V_LEN, V_COL; C set
; when there is none (the card's buffer walked, then refilled while full).
; ---------------------------------------------------------------------------
vm_nextpost:
        ldx V_PI
        cpx pt_n
        bcc @have
        bit pt_more
        bpl @none
        jsr far_postsc          ; (FA_SRC and FA_BANK: the next post)
        stz V_PI
        bra vm_nextpost
@none:  sec
        rts
@have:  lda pt_td,x
        sta V_TD
        lda pt_len,x
        sta V_LEN
        lda pt_lo,x
        sta V_COL
        lda pt_hi,x
        sta V_COL+1
        inc V_PI
        clc
        rts

; ---------------------------------------------------------------------------
; vm_step: visNext: frac += xiscale; C set when the texture column is out
; of the patch (frac < 0 or frac >> 16 >= width), else V_X + 1.
; ---------------------------------------------------------------------------
vm_step:
        clc
        lda V_FRAC
        adc V_XIS
        sta V_FRAC
        lda V_FRAC+1
        adc V_XIS+1
        sta V_FRAC+1
        lda V_FRAC+2
        adc V_XIS+2
        sta V_FRAC+2
        lda V_FRAC+3
        adc V_XIS+3
        sta V_FRAC+3
        bmi @out
        lda V_FRAC+2
        cmp V_W
        lda V_FRAC+3
        sbc V_W+1
        bcs @out
        inc V_X
        clc
        rts
@out:   sec
        rts

; ---------------------------------------------------------------------------
; vm_yrow: A (low), X (high) = YHTAB[V_T] (see above)
; ---------------------------------------------------------------------------
vm_yrow:
        lda V_UNIT
        bne @unit
        lda V_T                 ; V_T < V_TN: in the table
        cmp V_TN
        lda V_T+1
        sbc V_TN+1
        bcc @have
@fill:  clc                     ; E += spryscale: row V_TN
        lda V_E
        adc V_SS
        sta V_E
        lda V_E+1
        adc V_SS+1
        sta V_E+1
        lda V_E+2
        adc V_SS+2
        sta V_E+2
        lda V_E+3
        adc V_SS+3
        sta V_E+3
        ldy V_TN
        lda V_TN+1
        bne @fh
        lda V_E+2
        sta YHL,y
        lda V_E+3
        sta YHH,y
        bra @inc
@fh:    lda V_E+2
        sta YHL+256,y
        lda V_E+3
        sta YHH+256,y
@inc:   inc V_TN
        bne :+
        inc V_TN+1
:       lda V_T                 ; up to row V_T
        cmp V_TN
        lda V_T+1
        sbc V_TN+1
        bcs @fill
@have:  ldy V_T
        lda V_T+1
        bne @h
        lda YHH,y
        tax
        lda YHL,y
        rts
@h:     lda YHH+256,y
        tax
        lda YHL+256,y
        rts
@unit:  clc
        lda V_YH0
        adc V_T
        pha
        lda V_YH0+1
        adc V_T+1
        tax
        pla
        rts

; ---------------------------------------------------------------------------
; vm_rows: visPost's rows of the post V_TD, V_LEN within V_LO .. V_HI - 1:
; yh = YHTAB[topdelta + length] (none when negative or above V_LO), V_YH1
; = min(yh + 1, V_HI); yl = YHTAB[topdelta] + 1 (V_LO when negative; none
; from V_HI), V_YL = max(yl, V_LO); none when V_YH1 <= V_YL. C set: none.
; ---------------------------------------------------------------------------
vm_rows:
        clc
        lda V_TD
        adc V_LEN
        sta V_T
        lda #0
        rol a
        sta V_T+1
        jsr vm_yrow
        cpx #0
        bmi @none               ; negative
        bne @clamp              ; 256 or more: past V_HI
        cmp V_LO
        bcc @none
        cmp V_HI
        bcc :+
@clamp: lda V_HI
        dec a
:       inc a
        sta V_YH1
        lda V_TD
        sta V_T
        stz V_T+1
        jsr vm_yrow
        cpx #0
        bmi @lo
        clc                     ; yl = YHTAB[topdelta] + 1 (16 bits)
        adc #1
        bcc :+
        inx
:       cpx #0
        bne @none               ; 256 or more: from V_HI
        cmp V_HI
        bcs @none
        cmp V_LO
        bcs @yl
@lo:    lda V_LO
@yl:    sta V_YL
        lda V_YH1
        cmp V_YL
        beq @none
        bcc @none
        clc
        rts
@none:  sec
        rts

; ---------------------------------------------------------------------------
; vm_fscut: the spans of column X end at the rows V_YL .. V_YH1 - 1
; ---------------------------------------------------------------------------
vm_fscut:
        lda V_YH1
        cmp FSBOT,x
        bcc :+
        beq :+
        sta FSBOT,x
:       lda V_YL
        cmp FSTOP,x
        bcs :+
        sta FSTOP,x
:       rts

; ---------------------------------------------------------------------------
; vm_cvset: CVSET of column X for the rows V_YL .. V_YH1 - 1 and the
; record RSEQ
; ---------------------------------------------------------------------------
vm_cvset:
        lda CVEND,x             ; the rows of the range (255: none can come)
        sec
        sbc CVFIRST,x
        clc                     ; + first >= end: not more rows
        adc V_YL
        bcs @done
        cmp V_YH1
        bcs @done
        lda V_YL
        sta CVFIRST,x
        lda V_YH1
        sta CVEND,x
        lda RSEQ
        sta CVRECLO,x
        lda RSEQ+1
        sta CVRECHI,x
@done:  rts

; ---------------------------------------------------------------------------
; vtexrec: the K_TEX record of the post V_COL (rows V_YL .. V_YH1 - 1) in
; column X, its position V_T (TF, TI): FSCUT, the room, the record, CVSET
; ---------------------------------------------------------------------------
vtexrec:
        jsr vm_fscut
        lda #TEXREC_SIZE
        jsr mrec_room
        lda #K_TEX
        sta BATCH,y
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
        lda V_S2
        sta BATCH,y
        iny
        lda V_S2+1
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
        lda V_CMP
        sta BATCH,y
        iny
        sty MRB
        jmp vm_cvset

; ===========================================================================
; vcols: visCol, visPost: each post a K_TEX record, its position
; (texturemid >> 7 + (yl - 85) fracstep - 512 topdelta) >> 1, the low 16
; bits: yl fL + (yl fH - 2 topdelta) << 8 + K
; ===========================================================================
vcols:
@col:   ldy V_X
        cpy #VIEWWIDTH
        bcs @done
        lda (V_FCP),y           ; the rows the clips leave: V_LO .. V_HI - 1
        beq @next               ;   (the arrays hold the clips + 1)
        dec a
        sta V_HI
        lda (V_CCP),y
        sta V_LO
        cmp V_HI
        bcs @next
        jsr vm_fetch
@post:  jsr vm_nextpost
        bcs @next
        jsr vm_rows
        bcs @post
        ldy V_YL                ; the position
        sec                     ; yl fL
        lda (PSL0),y
        sbc (PNL0),y
        sta V_T
        lda (PSH0),y
        sbc (PNH0),y
        sta V_T+1
        sec                     ; + (yl fH - 2 topdelta) << 8
        lda (PSL1),y
        sbc (PNL1),y
        sec
        sbc V_TD
        sec
        sbc V_TD
        clc
        adc V_T+1
        sta V_T+1
        clc                     ; + K, >> 1
        lda V_T
        adc V_K
        sta V_T
        lda V_T+1
        adc V_K+1
        lsr a
        sta V_T+1
        ror V_T
        ldx V_X
        jsr vtexrec
        bra @post
@next:  jsr vm_step
        bcc @col
@done:  rts

; ===========================================================================
; vmag: visColD's magnified loop (vrCol, vrPost, vrNext): a post of a
; column is also recorded, the same record, in the V_REP next columns that
; show the same texture column (frac + xiscale: xiscale's high word and
; the carry of the low words sum to 0) with the same clips; the position
; K - 512 topdelta + yl fL (|xiscale| < 0.75 makes fH 0, and upstream
; leaves its product out)
; ===========================================================================
vmag:
@col:   ldy V_X
        cpy #VIEWWIDTH
        bcs @done
        jsr vmcol
        jsr vm_step
        bcc @col
@done:  rts

vmcol:  lda (V_FCP),y           ; the column V_X (Y): its clips, its run,
        bne :+                  ;   its posts
@none:  rts
:       dec a
        sta V_HI
        lda (V_CCP),y
        sta V_LO
        cmp V_HI
        bcs @none
        jsr vm_fetch
        lda V_FRAC              ; the run: V_T = the low word of frac of
        sta V_T+2               ;   its last column
        lda V_FRAC+1
        sta V_T+3
        ldy V_X
@run:   iny
        cpy #VIEWWIDTH
        bcs @end
        clc
        lda V_T+2
        adc V_XIS
        sta V_T+2
        lda V_T+3
        adc V_XIS+1
        sta V_T+3
        lda V_XIS+2             ; the same texture column?
        adc #0
        sta V_T
        lda V_XIS+3
        adc #0
        ora V_T
        bne @back
        lda (V_FCP),y           ; the same clips?
        dec a
        cmp V_HI
        bne @back
        lda (V_CCP),y
        cmp V_LO
        beq @run
@back:  sec                     ; (column Y is not in the run)
        lda V_T+2
        sbc V_XIS
        sta V_T+2
        lda V_T+3
        sbc V_XIS+1
        sta V_T+3
@end:   tya                     ; V_REP = Y - V_X - 1
        clc
        sbc V_X
        sta V_REP
@post:  jsr vm_nextpost
        bcs @last
        jsr vm_rows
        bcs @post
        ldy V_YL                ; K - 512 topdelta + yl fL, >> 1 (V_T,
        sec                     ;   V_T+1)
        lda (PSL0),y
        sbc (PNL0),y
        sta V_T
        lda (PSH0),y
        sbc (PNH0),y
        sec
        sbc V_TD
        sec
        sbc V_TD
        sta V_T+1
        clc
        lda V_T
        adc V_K
        sta V_T
        lda V_T+1
        adc V_K+1
        lsr a
        sta V_T+1
        ror V_T
        clc                     ; the record in each column of the run,
        lda V_X                 ;   V_X .. V_X + V_REP
        adc V_REP
        sta MD_T+2
        ldx V_X
@rec:   phx
        jsr vtexrec
        plx
        cpx MD_T+2
        inx
        bcc @rec
        bra @post
@last:  lda V_REP               ; the run's last column and its frac
        beq @ret
        lda V_T+2
        sta V_FRAC
        lda V_T+3
        sta V_FRAC+1
        clc
        lda V_X
        adc V_REP
        sta V_X
@ret:   rts

; ===========================================================================
; vfuzz: visColF: each post a K_FUZZ record (the room first, then FSCUT,
; the column's covered range none for the frame), the fuzz position
; stepped by the count modulo 50; rows 1 .. 166 only (a shadow reads the
; rows next to its own); YHTAB even at unit scale
; ===========================================================================
vfuzz:
        stz V_UNIT
        lda FZPOS
        sta V_FZ
@col:   ldy V_X
        cpy #VIEWWIDTH
        bcs @done
        lda (V_FCP),y           ; V_HI = min(floorclip, 167), V_LO =
        beq @next               ;   max(ceilingclip + 1, 1)
        dec a
        cmp #VIEWHEIGHT - 1
        bcc :+
        lda #VIEWHEIGHT - 1
:       sta V_HI
        lda (V_CCP),y
        bne :+
        inc a
:       sta V_LO
        cmp V_HI
        bcs @next
        jsr vm_fetch
@post:  jsr vm_nextpost
        bcs @next
        jsr vm_rows
        bcs @post
        ldx V_X
        lda #FUZZREC_SIZE
        jsr mrec_room
        jsr vm_fscut
        lda #255
        sta CVFIRST,x
        lda #254
        sta CVEND,x
        lda #K_FUZZ
        sta BATCH,y
        iny
        txa
        sta BATCH,y
        iny
        lda V_YL
        sta BATCH,y
        iny
        lda V_YH1               ; the count
        sec
        sbc V_YL
        sta BATCH,y
        iny
        pha
        lda V_FZ
        sta BATCH,y
        iny
        sty MRB
        pla                     ; the position + the count, modulo 50
        clc
        adc V_FZ
:       cmp #50
        bcc :+
        sbc #50
        bra :-
:       sta V_FZ
        bra @post
@next:  jsr vm_step
        bcc @col
@done:  lda V_FZ
        sta FZPOS
        rts

.ifdef CLIPLOG
; ---------------------------------------------------------------------------
; cl_log: the clip log (-D CLIPLOG, RENDER-MASKED.md): the vissprite's
; index (2 bytes) and FLOORCLIP, CEILCLIP into the SEAM bank at CL_PTR.
; Three RAMWRT windows (far_put).
; ---------------------------------------------------------------------------
cl_log:
        lda CL_N
        cmp #CLIPLOG_MAX
        bcs @done
        lda DS_IDX              ; the vissprite's index; bit 7: the weapon's
        sta MD_T                ;   draw ($FF00 + the psprite)
        stz MD_T+1
        bpl :+
        and #$7F
        sta MD_T
        dec MD_T+1
:       lda #SEAM
        sta FA_BANK
        lda #<MD_T
        sta FA_SRC
        stz FA_SRC+1
        lda #2
        jsr @put
        lda #<FLOORCLIP
        sta FA_SRC
        lda #>FLOORCLIP
        sta FA_SRC+1
        lda #VIEWWIDTH
        jsr @put
        lda #<CEILCLIP
        sta FA_SRC
        lda #>CEILCLIP
        sta FA_SRC+1
        lda #VIEWWIDTH
        jsr @put
        inc CL_N
@done:  rts
@put:   sta FA_N
        lda CL_PTR
        sta FA_DST
        lda CL_PTR+1
        sta FA_DST+1
        jsr far_put
        clc
        lda CL_PTR
        adc FA_N
        sta CL_PTR
        bcc :+
        inc CL_PTR+1
:       rts
.endif
