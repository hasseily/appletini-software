; wclip.s: the weapon's clip pass of the native renderer's front end
; (docs/RENDER-MASKED.md 3.2 phase 3; milestone 8, stage C), in place of
; milestone 7's seam. A GPL-2 derivative of Webifi's IIgs DOOM
; (build/upstream/src/iigs/r_frame65.s weaponClip, psSetup, pspSprite,
; :647-854; r_sprite65.s wcDraw3, wpCheck, wcProf, :794-880, :1259-1301;
; r_seg65.s visCol, visPost 30$, visNext, :2887-3116), written for the
; 65C02.
;
;   nw_clip     weaponClip: pspSprite of the weapon (psprite 0) at the view
;               only (psSetup: mfloorclip screenheightarray, mceilingclip
;               negonearray) into FRVIS (wpsp.s ps_vis); unless it has no
;               state, is off the side or is the shadow weapon, wcDraw3's
;               clip pass: MM_WPOK (FRVIS holds this frame's weapon), then
;               from its profile (wcProf: in each column, the lowest post
;               whose rows reach the view's last row, its run's first row
;               + 1 into FLOORCLIP) or, when the lump has none or wpStart
;               refuses it, R_DrawVisSprite's clip pass (visPost 30$: a run
;               of touching posts reaching the view's last row makes the
;               column's floor clip its first row + 1, when that is lower).
;               FLOORCLIP holds the view's bottom + 1 from nr_clear.
;
; wcDraw3's other tests always pass here: wpCheck (unit scale, xiscale 2.0,
; whole startfrac, the clip arrays of psSetup: pspSprite's vissprite), and
; W_WSK is 0 when a frame starts (every frame's end leaves it 0: sortSkip,
; playerSkip; tools/native/framestate.py checks it), so the clip pass takes
; no wclipSprite.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "math.inc"

        .import far_get, ps_vis, wp_find, wp_start, wp_list, wp_yh0
        .export nw_clip

        .segment "RENDERW"

; ===========================================================================
; nw_clip
; ===========================================================================
nw_clip:
        ldx #0                  ; psSetup, pspSprite(the weapon)
        jsr ps_vis
        bcs @done               ; no state, or off the side
        lda FRVIS+FV_PAGE       ; the shadow weapon: no clip pass
        beq @done
        lda #1                  ; wcDraw3: MM_WPOK (0x5AA5)
        sta MM_WPOK
        jsr wp_find
        bcs clip_vis            ; no profile: the old code
        jsr wp_start
        cmp #1
        beq @done               ; nothing shows
        bcs clip_vis            ; the old code
        ; wcProf: each column's lowest post that shows and reaches V_HI
        lda #<WPENT
        sta WP_E
        lda #>WPENT
        sta WP_E+1
        lda FRVIS+FV_X1
        sta WP_X
        lda WP_N
        sta WP_I
@col:   jsr wp_list
        ldx #0
        lda WP_HI               ; hi > b: it ends above V_HI (and those
        cmp WPLST+1,x           ;   above it)
        bcs @next
        cmp WPLST,x             ; hi > a: it shows and reaches V_HI
        bcs @clip
@up:    inx                     ; the post above
        inx
        inx
        inx
        inx
        lda WPLST,x             ; (a + 1 = 0: no more)
        beq @next
        lda WP_HI
        cmp WPLST+1,x
        bcs @next
        cmp WPLST,x
        bcc @up
@clip:  lda WPLST+2,x           ; floorclip = V_YH0 + the a of its run + 1
        adc WP_YH0              ;   (carry set)
        ldy WP_X
        sta FLOORCLIP,y
@next:  inc WP_X
        clc
        lda WP_E
        adc #2
        sta WP_E
        bcc :+
        inc WP_E+1
:       dec WP_I
        bne @col
@done:  rts

; ===========================================================================
; clip_vis: R_DrawVisSprite's clip pass of FRVIS (VS_CLIP): unit scale, the
; texture column startfrac's high word, 2 of them a screen column, while in
; the patch; V_HI the view's bottom (screenheightarray - 1), V_LO 0
; (negonearray); the posts read through the far layer (the patch header in
; WPHB, ps_vis's). A rare path: no capture takes it.
; ===========================================================================
clip_vis:
        jsr wp_yh0
        lda VIEWBOT
        sta WP_VHI
        lda FRVIS+FV_SFRAC
        sta WP_C
        lda FRVIS+FV_SFRAC+1
        sta WP_C+1
        lda FRVIS+FV_X1
        sta WP_X
@col:   lda WP_X                ; to the view's right side
        cmp #VIEWWIDTH
        bcc :+
        rts
:       lda WP_VHI              ; no free row (V_LO 0 >= V_HI): next
        bne :+
        jmp @next
:       lda WP_C                ; the column: patch + columnofs[c]'s low
        asl a                   ;   word (no lump crosses a bank)
        sta FA_SRC
        lda WP_C+1
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
        adc WPHB+PH_ADDR
        sta FA_SRC
        txa
        adc WPHB+PH_ADDR+1
        sta FA_SRC+1
        jsr get2                ; WP_T = the column's offset
        clc
        lda WP_T
        adc WPHB+PH_ADDR
        sta WP_E
        lda WP_T+1
        adc WPHB+PH_ADDR+1
        sta WP_E+1
        lda #$FE                ; no run yet
        sta WP_PYH
@post:  lda WP_E
        sta FA_SRC
        lda WP_E+1
        sta FA_SRC+1
        jsr get2                ; WP_T = topdelta, WP_T+1 = length
        lda WP_T                ; $FF: no more posts
        cmp #$FF
        bne :+
        jmp @next
:
        jsr rows                ; WP_YL, WP_YH1; C set: none
        bcs @adv
        lda WP_PYH              ; 30$: a new run unless the post goes on
        inc a                   ;   from the one above
        cmp WP_YL
        beq :+
        lda WP_YL
        sta WP_RUN
:       lda WP_YH1              ; the last row of the post
        dec a
        sta WP_PYH
        inc a
        cmp WP_VHI              ; it reaches V_HI: the run's first row + 1
        bne @adv                ;   when lower than the floor clip
        ldx WP_X
        lda WP_RUN
        inc a
        cmp FLOORCLIP,x
        bcs @adv
        sta FLOORCLIP,x
@adv:   clc                     ; the next post: + length + 4
        lda WP_T+1
        adc #4
        bcc :+
        inc WP_E+1
        clc
:       adc WP_E
        sta WP_E
        bcc @post
        inc WP_E+1
        bra @post
@next:  clc                     ; frac += 2.0: the next column while in
        lda WP_C                ;   the patch
        adc #2
        sta WP_C
        bcc :+
        inc WP_C+1
:       lda WP_C
        cmp WPHB+PH_WIDTH
        lda WP_C+1
        sbc WPHB+PH_WIDTH+1
        bcs @done
        inc WP_X
        jmp @col
@done:  rts

; get2: WP_T = 2 bytes of the patch's bank at FA_SRC
get2:   lda #<WP_T
        sta FA_DST
        stz FA_DST+1
        lda WPHB+PH_BANK
        sta FA_BANK
        lda #2
        sta FA_N
        jmp far_get

; rows: visPost's rows of the post (topdelta WP_T, length WP_T+1) at unit
; scale within V_LO (0) .. V_HI - 1: yh = V_YH0 + topdelta + length (none
; when negative), V_YH1 = min(yh + 1, V_HI); yl = V_YH0 + topdelta (V_LO
; when negative, else + 1: none from V_HI); none when V_YH1 <= V_YL. C set:
; none.
rows:   clc
        lda WP_T
        adc WP_T+1
        sta WP_TX
        lda #0
        adc #0
        sta WP_TX+1
        clc
        lda WP_TX
        adc WP_YH0
        sta WP_TX
        lda WP_TX+1
        adc WP_YH0+1
        bmi @none               ; negative (and so below V_LO, 0)
        bne @clamp              ; 256 or more: past V_HI
        lda WP_TX
        cmp WP_VHI
        bcc :+
@clamp: lda WP_VHI
        dec a
:       inc a
        sta WP_YH1
        clc                     ; yl
        lda WP_T
        adc WP_YH0
        sta WP_TX
        lda #0
        adc WP_YH0+1
        bmi @lo
        tax
        lda WP_TX               ; + 1
        clc
        adc #1
        bcc :+
        inx
:       cpx #0
        bne @none               ; 256 or more: from V_HI
        cmp WP_VHI
        bcs @none
        bra @yl                 ; (V_LO is 0)
@lo:    lda #0
@yl:    sta WP_YL
        lda WP_YH1
        cmp WP_YL
        beq @none
        bcc @none
        clc
        rts
@none:  sec
        rts
