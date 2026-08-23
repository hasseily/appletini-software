.setcpu "65C02"

; Whole-layer sparse DHGR parallax renderer for Appletini Invasion.
;
; Public C API:
;   unsigned char __fastcall__ parallax_assets_load(void);
;   void parallax_draw_layer(void);
;   void parallax_move_layer(void);
;
; The caller supplies source rows through fixed zero-page locations:
;   $68/$69  first old/displayed source row (woven row 40)
;   $6A      layer (0=deep space, 1=nebula, 2=asteroids)
;   $6B/$6C  first new/target source row (move only)
;
; Each call covers all 316 visible woven rows.  MAIN entries are applied in
; one pass and AUX entries in a second pass, so RAMRD/RAMWRT switch only once
; per layer rather than once per sparse byte.  The engine, row-address table,
; and asset are mirrored at identical addresses in RamWorks bank zero, making
; the complete AUX pass safe with both reads and writes redirected.

.export _parallax_assets_load, _parallax_draw_layer, _parallax_move_layer
.export _video_sprite_fast
.exportzp _parallax_old_row, _parallax_layer, _parallax_new_row

_parallax_old_row := $68
_parallax_layer   := $6A
_parallax_new_row := $6B

RENDER_MOVE     = $6D
CHUNK_PTR       = $70
CHUNK_PTR_HI    = $71
DIRECTORY_PTR   = $72
DIRECTORY_PTR_HI= $73
RECORD_PTR      = $74
RECORD_PTR_HI   = $75
OLD_ROW         = $76
OLD_ROW_HI      = $77
NEW_ROW         = $78
NEW_ROW_HI      = $79
DEST_TABLE      = $7A
DEST_TABLE_HI   = $7B
NATIVE_ROWS     = $7C
ENTRY_COUNT     = $7D
COPY_COUNT      = $7E
COPY_COUNT_HI   = $7F

; Fixed sprite inputs and workspace. Probe/clear startup code is finished
; before gameplay begins, so its low-zero-page workspace can be reused here.
SPRITE_X        = $20
SPRITE_Y        = $21
SPRITE_HEIGHT   = $22
SPRITE_PTR      = $23
SPRITE_PTR_HI   = $24
SPRITE_AUX_A    = $28                   ; eight cached page-A AUX bytes
SPRITE_AUX_B    = $30                   ; eight cached page-B AUX bytes
SPRITE_TABLE    = $38
SPRITE_TABLE_HI = $39
SPRITE_ROWS     = $3A
SPRITE_INDEX    = $3B

; Installer aliases; installation and rendering never overlap.
COPY_SOURCE     = CHUNK_PTR
COPY_SOURCE_HI  = CHUNK_PTR_HI
COPY_DEST       = DIRECTORY_PTR
COPY_DEST_HI    = DIRECTORY_PTR_HI

RAMRDOFF       = $C002
RAMRDON        = $C003
RAMWRTOFF      = $C004
RAMWRTON       = $C005
RAMWORKS       = $C073

ENGINE_ADDRESS = $1000

A13S_VERSION      = 1
A13S_LAYER_COUNT  = 3
A13S_ROW_BYTES    = 80
A13S_HEIGHT_LO    = $80
A13S_HEIGHT_HI    = $01
A13S_CHUNK_TABLE  = 10
A13S_CHUNK_HEADER = 2

.segment "RODATA"

; This relocatable blob is installed at exactly $1000 in MAIN and bank-zero
; AUX.  Branches are relative; internal JSRs and self-modifying operands use
; ENGINE_ADDRESS plus assembly-time offsets into the blob.
engine_blob:
        stz     RENDER_MOVE
        bra     engine_common

engine_move_entry:
        lda     #$01
        sta     RENDER_MOVE

engine_common:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS

        ; Resolve the selected chunk once for the entire layer.
        lda     _parallax_layer
        cmp     #A13S_LAYER_COUNT
        bcc     @layer_valid
        rts
@layer_valid:
        asl     a
        tax
        clc
        lda     parallax_asset+A13S_CHUNK_TABLE,x
        adc     #<parallax_asset
        sta     CHUNK_PTR
        lda     parallax_asset+A13S_CHUNK_TABLE+1,x
        adc     #>parallax_asset
        sta     CHUNK_PTR_HI

        ; MAIN pass: BCC skips even/AUX interleaved coordinates.
        jsr     ENGINE_PREPARE_PASS
        lda     #$90                    ; BCC opcode
        sta     ENGINE_PARITY_BRANCH
        jsr     ENGINE_RENDER_PASS

        ; AUX pass. RAMWRT is enabled first so self-modification affects the
        ; AUX engine; RAMRD then moves execution and asset reads to its mirror.
        stz     RAMWRTON
        stz     RAMRDON
        jsr     ENGINE_PREPARE_PASS
        lda     #$B0                    ; BCS skips odd/MAIN coordinates
        sta     ENGINE_PARITY_BRANCH
        jsr     ENGINE_RENDER_PASS

        ; The instruction following RAMRDOFF resumes in the MAIN engine.
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        rts

prepare_pass:
        lda     _parallax_old_row
        sta     OLD_ROW
        lda     _parallax_old_row+1
        sta     OLD_ROW_HI
        lda     _parallax_new_row
        sta     NEW_ROW
        lda     _parallax_new_row+1
        sta     NEW_ROW_HI
        lda     #<woven_destination_table
        sta     DEST_TABLE
        lda     #>woven_destination_table
        sta     DEST_TABLE_HI
        lda     #158
        sta     NATIVE_ROWS
        rts

; Render page A then page B for each of native rows 20..177.  Source rows
; advance in woven order and wrap after 383.
render_pass:
@native_loop:
        jsr     ENGINE_RENDER_DESTINATION
        jsr     ENGINE_ADVANCE_ROWS
        jsr     ENGINE_RENDER_DESTINATION
        jsr     ENGINE_ADVANCE_ROWS
        dec     NATIVE_ROWS
        bne     @native_loop
        rts

render_destination:
        ; Patch the absolute indexed destination used by draw_record.
        ldy     #$00
        lda     (DEST_TABLE),y
        sta     ENGINE_DEST_EOR+1
        sta     ENGINE_DEST_STA+1
        iny
        lda     (DEST_TABLE),y
        sta     ENGINE_DEST_EOR+2
        sta     ENGINE_DEST_STA+2
        clc
        lda     DEST_TABLE
        adc     #$02
        sta     DEST_TABLE
        bcc     :+
        inc     DEST_TABLE_HI
:
        lda     OLD_ROW
        ldx     OLD_ROW_HI
        jsr     ENGINE_RESOLVE_RECORD
        jsr     ENGINE_DRAW_RECORD
        lda     RENDER_MOVE
        beq     @done
        lda     NEW_ROW
        ldx     NEW_ROW_HI
        jsr     ENGINE_RESOLVE_RECORD
        jsr     ENGINE_DRAW_RECORD
@done:
        rts

; A/X is a validated source row in 0..383. Resolve its row record using the
; selected chunk's 384-word directory.
resolve_record:
        asl     a
        sta     DIRECTORY_PTR
        txa
        rol     a
        sta     DIRECTORY_PTR_HI
        clc
        lda     DIRECTORY_PTR
        adc     #A13S_CHUNK_HEADER
        sta     DIRECTORY_PTR
        bcc     :+
        inc     DIRECTORY_PTR_HI
:
        clc
        lda     CHUNK_PTR
        adc     DIRECTORY_PTR
        sta     DIRECTORY_PTR
        lda     CHUNK_PTR_HI
        adc     DIRECTORY_PTR_HI
        sta     DIRECTORY_PTR_HI
        ldy     #$00
        lda     (DIRECTORY_PTR),y
        sta     RECORD_PTR
        iny
        lda     (DIRECTORY_PTR),y
        sta     RECORD_PTR_HI
        clc
        lda     CHUNK_PTR
        adc     RECORD_PTR
        sta     RECORD_PTR
        lda     CHUNK_PTR_HI
        adc     RECORD_PTR_HI
        sta     RECORD_PTR_HI
        rts

; Scan one sparse row. The parity branch opcode is BCC in MAIN and BCS in AUX;
; its relative target is identical. Records are at most 27 bytes, so Y cannot
; wrap while walking count,(x,data)*.
draw_record:
        ldy     #$00
        lda     (RECORD_PTR),y
        beq     draw_record_done
        sta     ENTRY_COUNT
        iny
draw_record_entry:
        lda     (RECORD_PTR),y
        lsr     a                       ; X coordinate / 2, parity in carry
        tax
        iny
parity_branch:
        bcc     draw_record_skip        ; patched to BCS for AUX pass
        lda     (RECORD_PTR),y
dest_eor:
        eor     $FFFF,x
        ora     #$80
dest_sta:
        sta     $FFFF,x
draw_record_skip:
        iny
        dec     ENTRY_COUNT
        bne     draw_record_entry
draw_record_done:
        rts

advance_rows:
        inc     OLD_ROW
        bne     @old_check
        inc     OLD_ROW_HI
@old_check:
        lda     OLD_ROW_HI
        cmp     #$01
        bne     @new
        lda     OLD_ROW
        cmp     #$80
        bne     @new
        stz     OLD_ROW
        stz     OLD_ROW_HI
@new:
        lda     RENDER_MOVE
        beq     @done
        inc     NEW_ROW
        bne     @new_check
        inc     NEW_ROW_HI
@new_check:
        lda     NEW_ROW_HI
        cmp     #$01
        bne     @done
        lda     NEW_ROW
        cmp     #$80
        bne     @done
        stz     NEW_ROW
        stz     NEW_ROW_HI
@done:
        rts

; Draw one 1-byte-wide, <=8-row sprite into both DHGRi fields. MAIN sprite
; bytes are applied while the linked C sprite is readable, while AUX bytes are
; cached in common zero page. One bank transition then draws the whole AUX
; sprite instead of using one trampoline transition per scanline.
sprite_entry:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        jsr     ENGINE_SPRITE_PREPARE
        stz     SPRITE_INDEX
        lda     SPRITE_HEIGHT
        sta     SPRITE_ROWS
sprite_main_loop:
        jsr     ENGINE_SPRITE_PATCH_DEST
        ldx     SPRITE_INDEX
        ldy     #$00
        lda     (SPRITE_PTR),y
        sta     SPRITE_AUX_A,x
        iny
        lda     (SPRITE_PTR),y
sprite_main_a_eor:
        eor     $FFFF
        ora     #$80
sprite_main_a_sta:
        sta     $FFFF
        iny
        lda     (SPRITE_PTR),y
        sta     SPRITE_AUX_B,x
        iny
        lda     (SPRITE_PTR),y
sprite_main_b_eor:
        eor     $FFFF
        ora     #$80
sprite_main_b_sta:
        sta     $FFFF
        clc
        lda     SPRITE_PTR
        adc     #$04
        sta     SPRITE_PTR
        bcc     :+
        inc     SPRITE_PTR_HI
:
        jsr     ENGINE_SPRITE_ADVANCE_TABLE
        inc     SPRITE_INDEX
        dec     SPRITE_ROWS
        bne     sprite_main_loop

        stz     RAMWRTON
        stz     RAMRDON
        jsr     ENGINE_SPRITE_PREPARE
        stz     SPRITE_INDEX
        lda     SPRITE_HEIGHT
        sta     SPRITE_ROWS
sprite_aux_loop:
        jsr     ENGINE_SPRITE_PATCH_DEST
        ldx     SPRITE_INDEX
        lda     SPRITE_AUX_A,x
sprite_aux_a_eor:
        eor     $FFFF
        ora     #$80
sprite_aux_a_sta:
        sta     $FFFF
        lda     SPRITE_AUX_B,x
sprite_aux_b_eor:
        eor     $FFFF
        ora     #$80
sprite_aux_b_sta:
        sta     $FFFF
        jsr     ENGINE_SPRITE_ADVANCE_TABLE
        inc     SPRITE_INDEX
        dec     SPRITE_ROWS
        bne     sprite_aux_loop
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        rts

sprite_prepare:
        sec
        lda     SPRITE_Y
        sbc     #20
        sta     SPRITE_TABLE
        stz     SPRITE_TABLE_HI
        asl     SPRITE_TABLE
        rol     SPRITE_TABLE_HI
        asl     SPRITE_TABLE
        rol     SPRITE_TABLE_HI
        clc
        lda     SPRITE_TABLE
        adc     #<woven_destination_table
        sta     SPRITE_TABLE
        lda     SPRITE_TABLE_HI
        adc     #>woven_destination_table
        sta     SPRITE_TABLE_HI
        rts

sprite_patch_destination:
        ldy     #$00
        clc
        lda     (SPRITE_TABLE),y
        adc     SPRITE_X
        sta     ENGINE_SPRITE_MAIN_A_EOR+1
        sta     ENGINE_SPRITE_MAIN_A_STA+1
        sta     ENGINE_SPRITE_AUX_A_EOR+1
        sta     ENGINE_SPRITE_AUX_A_STA+1
        iny
        lda     (SPRITE_TABLE),y
        adc     #$00
        sta     ENGINE_SPRITE_MAIN_A_EOR+2
        sta     ENGINE_SPRITE_MAIN_A_STA+2
        sta     ENGINE_SPRITE_AUX_A_EOR+2
        sta     ENGINE_SPRITE_AUX_A_STA+2
        iny
        clc
        lda     (SPRITE_TABLE),y
        adc     SPRITE_X
        sta     ENGINE_SPRITE_MAIN_B_EOR+1
        sta     ENGINE_SPRITE_MAIN_B_STA+1
        sta     ENGINE_SPRITE_AUX_B_EOR+1
        sta     ENGINE_SPRITE_AUX_B_STA+1
        iny
        lda     (SPRITE_TABLE),y
        adc     #$00
        sta     ENGINE_SPRITE_MAIN_B_EOR+2
        sta     ENGINE_SPRITE_MAIN_B_STA+2
        sta     ENGINE_SPRITE_AUX_B_EOR+2
        sta     ENGINE_SPRITE_AUX_B_STA+2
        rts

sprite_advance_table:
        clc
        lda     SPRITE_TABLE
        adc     #$04
        sta     SPRITE_TABLE
        bcc     :+
        inc     SPRITE_TABLE_HI
:
        rts

engine_blob_end:

ENGINE_MOVE_ENTRY        = ENGINE_ADDRESS + (engine_move_entry-engine_blob)
ENGINE_PREPARE_PASS       = ENGINE_ADDRESS + (prepare_pass-engine_blob)
ENGINE_RENDER_PASS        = ENGINE_ADDRESS + (render_pass-engine_blob)
ENGINE_RENDER_DESTINATION = ENGINE_ADDRESS + (render_destination-engine_blob)
ENGINE_RESOLVE_RECORD     = ENGINE_ADDRESS + (resolve_record-engine_blob)
ENGINE_DRAW_RECORD        = ENGINE_ADDRESS + (draw_record-engine_blob)
ENGINE_ADVANCE_ROWS       = ENGINE_ADDRESS + (advance_rows-engine_blob)
ENGINE_PARITY_BRANCH      = ENGINE_ADDRESS + (parity_branch-engine_blob)
ENGINE_DEST_EOR           = ENGINE_ADDRESS + (dest_eor-engine_blob)
ENGINE_DEST_STA           = ENGINE_ADDRESS + (dest_sta-engine_blob)
ENGINE_SPRITE_ENTRY        = ENGINE_ADDRESS + (sprite_entry-engine_blob)
ENGINE_SPRITE_PREPARE      = ENGINE_ADDRESS + (sprite_prepare-engine_blob)
ENGINE_SPRITE_PATCH_DEST   = ENGINE_ADDRESS + (sprite_patch_destination-engine_blob)
ENGINE_SPRITE_ADVANCE_TABLE = ENGINE_ADDRESS + (sprite_advance_table-engine_blob)
ENGINE_SPRITE_MAIN_A_EOR   = ENGINE_ADDRESS + (sprite_main_a_eor-engine_blob)
ENGINE_SPRITE_MAIN_A_STA   = ENGINE_ADDRESS + (sprite_main_a_sta-engine_blob)
ENGINE_SPRITE_MAIN_B_EOR   = ENGINE_ADDRESS + (sprite_main_b_eor-engine_blob)
ENGINE_SPRITE_MAIN_B_STA   = ENGINE_ADDRESS + (sprite_main_b_sta-engine_blob)
ENGINE_SPRITE_AUX_A_EOR    = ENGINE_ADDRESS + (sprite_aux_a_eor-engine_blob)
ENGINE_SPRITE_AUX_A_STA    = ENGINE_ADDRESS + (sprite_aux_a_sta-engine_blob)
ENGINE_SPRITE_AUX_B_EOR    = ENGINE_ADDRESS + (sprite_aux_b_eor-engine_blob)
ENGINE_SPRITE_AUX_B_STA    = ENGINE_ADDRESS + (sprite_aux_b_sta-engine_blob)

.assert (engine_blob_end-engine_blob) <= $0F00, error, "parallax engine does not fit below $1F00"

; All absolute data read by the AUX pass is mirrored to bank zero at its linked
; address during installation.
mirror_data_start:
woven_destination_table:
.repeat 158, ROW
        .word   $2000 + (((20+ROW) & 7) << 10) + (((20+ROW) & $38) << 4) + (((20+ROW) >> 6) * $28)
        .word   $4000 + (((20+ROW) & 7) << 10) + (((20+ROW) & $38) << 4) + (((20+ROW) >> 6) * $28)
.endrepeat

; Generated by tools/convert_parallax.py and embedded in INVASION.SYSTEM.
parallax_asset:
        .incbin "build/PARALLAX"
parallax_asset_end:
mirror_data_end:

.assert (parallax_asset_end-parallax_asset) < $10000, error, "A13S asset exceeds 16-bit addressing"

.segment "CODE"

copy_bytes:
@copy_test:
        lda     COPY_COUNT
        ora     COPY_COUNT_HI
        beq     @copy_done
        ldy     #$00
        lda     (COPY_SOURCE),y
        sta     (COPY_DEST),y
        inc     COPY_SOURCE
        bne     :+
        inc     COPY_SOURCE_HI
:
        inc     COPY_DEST
        bne     :+
        inc     COPY_DEST_HI
:
        lda     COPY_COUNT
        bne     :+
        dec     COPY_COUNT_HI
:
        dec     COPY_COUNT
        bra     @copy_test
@copy_done:
        rts

prepare_engine_copy:
        lda     #<engine_blob
        sta     COPY_SOURCE
        lda     #>engine_blob
        sta     COPY_SOURCE_HI
        lda     #<ENGINE_ADDRESS
        sta     COPY_DEST
        lda     #>ENGINE_ADDRESS
        sta     COPY_DEST_HI
        lda     #<(engine_blob_end-engine_blob)
        sta     COPY_COUNT
        lda     #>(engine_blob_end-engine_blob)
        sta     COPY_COUNT_HI
        rts

; fastcall unsigned char parallax_assets_load(void)
; Validate the A13S header, then mirror the engine and every absolute data
; dependency. Returns A=1,X=0 on success and restores MAIN/bank zero.
_parallax_assets_load:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS

        lda     parallax_asset+0
        cmp     #'A'
        bne     @bad_fixed_header
        lda     parallax_asset+1
        cmp     #'1'
        bne     @bad_fixed_header
        lda     parallax_asset+2
        cmp     #'3'
        bne     @bad_fixed_header
        lda     parallax_asset+3
        cmp     #'S'
        bne     @bad_fixed_header
        lda     parallax_asset+4
        cmp     #A13S_VERSION
        bne     @bad_fixed_header
        lda     parallax_asset+5
        cmp     #A13S_LAYER_COUNT
        bne     @bad_fixed_header
        lda     parallax_asset+6
        cmp     #A13S_ROW_BYTES
        bne     @bad_fixed_header
        lda     parallax_asset+7
        bne     @bad_fixed_header
        lda     parallax_asset+8
        cmp     #A13S_HEIGHT_LO
        bne     @bad_fixed_header
        lda     parallax_asset+9
        cmp     #A13S_HEIGHT_HI
        bne     @bad_fixed_header
        lda     parallax_asset+10
        cmp     #$10
        bne     @bad_fixed_header
        lda     parallax_asset+11
        bne     @bad_fixed_header
        bra     @fixed_header_valid
@bad_fixed_header:
        jmp     @invalid
@fixed_header_valid:

        lda     parallax_asset+13
        cmp     parallax_asset+11
        bcc     @invalid
        bne     @chunk_one_ordered
        lda     parallax_asset+12
        cmp     parallax_asset+10
        beq     @invalid
        bcc     @invalid
@chunk_one_ordered:
        lda     parallax_asset+15
        cmp     parallax_asset+13
        bcc     @invalid
        bne     @chunk_two_ordered
        lda     parallax_asset+14
        cmp     parallax_asset+12
        beq     @invalid
        bcc     @invalid
@chunk_two_ordered:
        lda     parallax_asset+15
        cmp     #>(parallax_asset_end-parallax_asset)
        bcc     @offsets_valid
        bne     @invalid
        lda     parallax_asset+14
        cmp     #<(parallax_asset_end-parallax_asset)
        bcs     @invalid
@offsets_valid:

        ; Install MAIN and AUX copies of the engine at $1000.
        jsr     prepare_engine_copy
        jsr     copy_bytes
        jsr     prepare_engine_copy
        stz     RAMWORKS
        stz     RAMWRTON
        jsr     copy_bytes
        stz     RAMWRTOFF

        ; Mirror the destination table and A13S asset at their linked address.
        lda     #<mirror_data_start
        sta     COPY_SOURCE
        sta     COPY_DEST
        lda     #>mirror_data_start
        sta     COPY_SOURCE_HI
        sta     COPY_DEST_HI
        lda     #<(mirror_data_end-mirror_data_start)
        sta     COPY_COUNT
        lda     #>(mirror_data_end-mirror_data_start)
        sta     COPY_COUNT_HI
        stz     RAMWORKS
        stz     RAMWRTON
        jsr     copy_bytes
        stz     RAMWRTOFF
        stz     RAMRDOFF
        stz     RAMWORKS
        lda     #$01
        ldx     #$00
        rts

@invalid:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        lda     #$00
        ldx     #$00
        rts

; Fixed-input layer APIs. No cc65 software-stack access occurs after these
; wrappers enter the bank-safe engine.
_parallax_draw_layer:
        jsr     ENGINE_ADDRESS
        rts

_parallax_move_layer:
        jsr     ENGINE_MOVE_ENTRY
        rts

_video_sprite_fast:
        jsr     ENGINE_SPRITE_ENTRY
        rts
