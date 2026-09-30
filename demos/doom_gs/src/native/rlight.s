; rlight.s: the sector light and the plane colours of the native renderer
; (docs/RENDER.md 1.5; milestone 7, stage A): bspSub's plane colours with
; c21Floor's worldbottom (r_bsp65.s:627-763, r_wall65.s:1446-1463) and
; R_WallLight (r_bsp65.s:1036-1058). A GPL-2 derivative of Webifi's IIgs
; DOOM (build/upstream/src/iigs/r_bsp65.s, r_wall65.s): the same colours,
; written for the 65C02.
;
; The light of Doom's renderer, as upstream: lightnum = (lightlevel >> 4) +
; extralight + gamma gives startmap = (15 - lightnum) * 4, and a floor or
; a ceiling takes the colormap startmap - PLANE_D (10). Tables do the
; clamps: SMAP[lightnum + 16] = startmap + 24, PCMO[startmap + 24 - d] =
; the colormap's row in FLATCM (32 bytes a colormap, the level's flat
; colours). The planes leave extralight out (upstream: "without the gun
; flash: the fill colors stay", r_bsp65.s:678-680). The fixed colormap
; (invulnerability, light amplification) replaces all: LT_FIXED, n * 256.

        .setcpu "65C02"
        .include "rlayout.inc"

        .import far_get
        .export nr_planes, nr_walllight, flatcolor, SMAP

        .segment "RENDERW"

; ---------------------------------------------------------------------------
; nr_planes: sector SC_CUR into the sector frame FSEC; BS_CM, the row of
; FLATCM for its light; WBOT = floorheight - viewz (upstream's c21Floor:
; worldbottom, kept for the walls of the sector); FPC, the floor colour
; ($FFFF: none, the floor is not below the view), CPC, the ceiling colour
; ($FFFE: a sky, $FFFF: none, the ceiling is not above the view).
; Changes A, X, Y, T0, T0+1, FA_*.
; ---------------------------------------------------------------------------
nr_planes:
        lda SC_CUR              ; sector * 16 from SECBASE
        stz T0+1
        asl a
        rol T0+1
        asl a
        rol T0+1
        asl a
        rol T0+1
        asl a
        rol T0+1
        clc
        adc #<SECBASE
        sta FA_SRC
        lda T0+1
        adc #>SECBASE
        sta FA_SRC+1
        lda #<FSEC
        sta FA_DST
        lda #>FSEC
        sta FA_DST+1
        lda #LVMAP
        sta FA_BANK
        lda #SEC_SIZE
        sta FA_N
        jsr far_get

        lda LT_FIXED+1          ; the fixed colormap: LT_FIXED >> 3
        bmi @light
        sta BS_CM+1
        lda LT_FIXED
        lsr BS_CM+1
        ror a
        lsr BS_CM+1
        ror a
        lsr BS_CM+1
        ror a
        sta BS_CM
        bra @floor
@light: lda FSEC+SEC_LIGHT      ; (lightlevel >> 4) + LT_BASE - extralight
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc LT_BASE
        sec
        sbc EXTRALIGHT
        tax
        lda SMAP,x              ; startmap + 24
        sec
        sbc #PLANE_D
        tax
        lda PCMOLO,x
        sta BS_CM
        lda PCMOHI,x
        sta BS_CM+1

@floor: sec                     ; worldbottom = floorheight - viewz; the
        lda FSEC+SEC_FLOOR      ;   floor shows when it is below the view
        sbc VIEWZ               ;   (signed)
        sta WBOT
        lda FSEC+SEC_FLOOR+1
        sbc VIEWZ+1
        sta WBOT+1
        lda FSEC+SEC_FLOOR+2
        sbc VIEWZ+2
        sta WBOT+2
        lda FSEC+SEC_FLOOR+3
        sbc VIEWZ+3
        sta WBOT+3
        bvc :+
        eor #$80
:       bpl @nofloor
        lda FSEC+SEC_FPIC
        jsr flatcolor
        sta FPC
        stz FPC+1
        bra @ceiling
@nofloor:
        lda #$FF
        sta FPC
        sta FPC+1

@ceiling:
        lda FSEC+SEC_CPIC       ; a sky
        cmp SKYFLAT
        bne @c1
        lda #$FE
        sta CPC
        lda #$FF
        sta CPC+1
        rts
@c1:    lda VIEWZ               ; the ceiling shows when it is above the
        cmp FSEC+SEC_CEIL       ;   view: viewz < ceilingheight (signed)
        lda VIEWZ+1
        sbc FSEC+SEC_CEIL+1
        lda VIEWZ+2
        sbc FSEC+SEC_CEIL+2
        lda VIEWZ+3
        sbc FSEC+SEC_CEIL+3
        bvc :+
        eor #$80
:       bpl @noceil
        lda FSEC+SEC_CPIC
        jsr flatcolor
        sta CPC
        stz CPC+1
        rts
@noceil:
        lda #$FF
        sta CPC
        sta CPC+1
        rts

; ---------------------------------------------------------------------------
; flatcolor: A = FLATCM[BS_CM + pic], pic = A (flats 0-2: the nukage frame
; of the time, NUKAGE). Changes A, T0, T0+1.
; ---------------------------------------------------------------------------
flatcolor:
        cmp #3
        bcs :+
        lda NUKAGE
:       clc
        adc BS_CM
        sta T0
        lda BS_CM+1
        adc #0
        sta T0+1
        clc
        lda T0
        adc #<FLATCM
        sta T0
        lda T0+1
        adc #>FLATCM
        sta T0+1
        lda (T0)
        rts

; ---------------------------------------------------------------------------
; nr_walllight: R_WallLight (r_bsp65.s:1036-1058). In: A = the light
; level, X:Y = the seg's normal angle (X the low byte). LT_I = (light >>
; 4) + LT_BASE, + 1 when the angle & $7FFF is 0, - 1 when it is $4000
; (the fake contrast). Out: A (low), X (high) = LT_FIXED when there is a
; fixed colormap, else 0. Changes A, X.
; ---------------------------------------------------------------------------
nr_walllight:
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
        tya
        and #$7F
        bne @x
        cpx #0
        bne @done
        inc LT_I                ; along y: + 1
        bne @done
        inc LT_I+1
        bra @done
@x:     cmp #$40
        bne @done
        cpx #0
        bne @done
        lda LT_I                ; along x: - 1
        bne :+
        dec LT_I+1
:       dec LT_I
@done:  lda LT_FIXED+1
        bmi @none
        tax
        lda LT_FIXED
        rts
@none:  lda #0
        tax
        rts

; ---------------------------------------------------------------------------
; The light tables (upstream's SMAP and PCMO, r_bsp65.s:1000-1032; copied
; from the reference's RAM and checked against their formulas by
; tools/native/rtables.py): SMAP as bytes, PCMO as two byte planes.
; ---------------------------------------------------------------------------
SMAP:   .incbin "smap.bin"
PCMOLO: .incbin "pcmolo.bin"
PCMOHI: .incbin "pcmohi.bin"
