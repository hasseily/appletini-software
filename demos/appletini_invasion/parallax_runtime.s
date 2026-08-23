.setcpu "65C02"

; Exact-alpha DHGRi parallax/ship loader and renderer for Appletini Invasion.
;
; Public C API:
;   unsigned char __fastcall__ parallax_assets_load(void);
;   void __fastcall__ parallax_render_slice(unsigned char row_count);
;   void video_ship_fast(void);
;
; Before parallax_render_slice, the caller supplies four 16-bit values through
; fixed zero-page locations:
;   $68/$69  first deep-space source row (0-383)
;   $6A/$6B  first nebula source row (0-383)
;   $6C/$6D  first asteroid source row (0-383)
;   $6E/$6F  first woven destination row (40-355)
;
; The fastcall byte in A is the number of woven rows (normally 106, 106, or
; 104). Source and destination rows advance once per output row. The A13C
; asset contains exact-alpha 65C02 row programs executed from RamWorks banks
; 1-5. They compose into $A0-$EF, which stays in MAIN while RAMRD selects an
; asset bank because ALTZP remains off. Each completed row is copied to
; bank-zero AUX and MAIN DHGR memory with Video-7 color selected in bit 7.

.export _parallax_assets_load, _parallax_render_slice
.export _video_sprite_fast, _video_ship_fast
.exportzp _parallax_deep_row, _parallax_nebula_row
.exportzp _parallax_asteroids_row, _parallax_woven_row

_parallax_deep_row      := $68
_parallax_nebula_row    := $6A
_parallax_asteroids_row := $6C
_parallax_woven_row     := $6E

ROWS_REMAINING  = $70
DIRECTORY_PTR   = $71
DIRECTORY_PTR_HI= $72
PROGRAM_PTR     = $73
PROGRAM_PTR_HI  = $74
PROGRAM_BANK    = $75
DESTINATION     = $76
DESTINATION_HI  = $77
DEST_TABLE      = $78
DEST_TABLE_HI   = $79
ROW_TEMP        = $7A
ROW_TEMP_HI     = $7B
DIRECTORY_BASE  = $7C
DIRECTORY_BASE_HI = $7D
COPY_COUNT      = $7E
COPY_COUNT_HI   = $7F

; cc65's linked zero-page allocation ends below $A0. ALTZP remains off, so
; these 80 bytes are common MAIN memory while row code executes from AUX.
ROW_BUFFER_AUX  = $A0
ROW_BUFFER_MAIN = $C8

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

; Exact 56x64 ship inputs and workspace. SHIP_X is a seven-dot DHGR group
; origin (0-72), while SHIP_FRAME selects frames 0-7. The row cache reuses
; the parallax dispatcher's $70-$7F scratch after a slice has completed.
SHIP_X          = SPRITE_X
SHIP_FRAME      = $25
SHIP_SOURCE     = $26
SHIP_SOURCE_HI  = $27
SHIP_DEST       = $28
SHIP_DEST_HI    = $29
SHIP_TABLE      = $2A
SHIP_TABLE_HI   = $2B
SHIP_ROWS       = $2C
SHIP_CACHE_INDEX= $2D
SHIP_GROUPS     = $2E
SHIP_BYTE_X     = $2F
SHIP_CACHE      = $70

; Installer aliases; installation and rendering never overlap.
COPY_SOURCE     = DIRECTORY_PTR
COPY_SOURCE_HI  = DIRECTORY_PTR_HI
COPY_DEST       = PROGRAM_PTR
COPY_DEST_HI    = PROGRAM_PTR_HI
LOADER_BANK     = PROGRAM_BANK

RAMRDOFF       = $C002
RAMRDON        = $C003
RAMWRTOFF      = $C004
RAMWRTON       = $C005
ALTZPOFF       = $C008
RAMWORKS       = $C073

; The engine is installed only after the final $0C00-$0DFF staging-buffer
; read, so it can safely occupy the otherwise-idle space below $1000.
ENGINE_ADDRESS = $0D00
A13C_HEADER     = $1000
A13C_DIRECTORY  = $1010
A13C_LAYER_SIZE = $0480
A13C_NEBULA_DIR = A13C_DIRECTORY + A13C_LAYER_SIZE
A13C_ASTEROID_DIR = A13C_NEBULA_DIR + A13C_LAYER_SIZE

A13C_VERSION      = 1
A13C_LAYER_COUNT  = 3
A13C_ROW_BYTES    = 80
A13C_PROGRAM_BANK_COUNT = 5
A13C_BANK_COUNT   = 6
A13C_SHIP_BANK    = 6
A13C_WIDTH_LO     = $30
A13C_WIDTH_HI     = $02
A13C_HEIGHT_LO    = $80
A13C_HEIGHT_HI    = $01
A13C_BANK_BASE    = $2000

OPEN_IO_BUFFER  = $0800
READ_BUFFER     = $0C00
MLI             = $BF00
MLI_OPEN        = $C8
MLI_READ        = $CA
MLI_CLOSE       = $CC

.import __ZP_LAST__
.assert __ZP_LAST__ < ROW_BUFFER_AUX, lderror, "cc65 zero page overlaps A13C row buffer"

.segment "RODATA"

; This relocatable blob is installed at exactly $0D00 in MAIN and RamWorks
; banks 0-6. Branches are relative; internal JSRs and self-modifying operands
; use ENGINE_ADDRESS plus assembly-time offsets into the blob.
engine_blob:
slice_entry:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF

        ; Resolve the first destination-table word from woven row 40.
        sec
        lda     _parallax_woven_row
        sbc     #40
        sta     ROW_TEMP
        lda     _parallax_woven_row+1
        sbc     #$00
        sta     ROW_TEMP_HI
        asl     ROW_TEMP
        rol     ROW_TEMP_HI
        clc
        lda     ROW_TEMP
        adc     #<woven_destination_table
        sta     DEST_TABLE
        lda     ROW_TEMP_HI
        adc     #>woven_destination_table
        sta     DEST_TABLE_HI

slice_row:
        ; Deep-space code initializes all 80 composition bytes.
        lda     #<A13C_DIRECTORY
        sta     DIRECTORY_BASE
        lda     #>A13C_DIRECTORY
        sta     DIRECTORY_BASE_HI
        lda     _parallax_deep_row
        ldx     _parallax_deep_row+1
        jsr     ENGINE_RESOLVE_PROGRAM
        jsr     ENGINE_EXECUTE_PROGRAM

        ; Nebula and asteroid code apply exact per-dot alpha masks.
        lda     #<A13C_NEBULA_DIR
        sta     DIRECTORY_BASE
        lda     #>A13C_NEBULA_DIR
        sta     DIRECTORY_BASE_HI
        lda     _parallax_nebula_row
        ldx     _parallax_nebula_row+1
        jsr     ENGINE_RESOLVE_PROGRAM
        jsr     ENGINE_EXECUTE_PROGRAM

        lda     #<A13C_ASTEROID_DIR
        sta     DIRECTORY_BASE
        lda     #>A13C_ASTEROID_DIR
        sta     DIRECTORY_BASE_HI
        lda     _parallax_asteroids_row
        ldx     _parallax_asteroids_row+1
        jsr     ENGINE_RESOLVE_PROGRAM
        jsr     ENGINE_EXECUTE_PROGRAM

        ; Patch both plane stores from this woven row's HGR address.
        ldy     #$00
        lda     (DEST_TABLE),y
        sta     ENGINE_MAIN_ROW_STA+1
        sta     ENGINE_AUX_ROW_STA+1
        sta     DESTINATION
        iny
        lda     (DEST_TABLE),y
        sta     ENGINE_MAIN_ROW_STA+2
        sta     ENGINE_AUX_ROW_STA+2
        sta     DESTINATION_HI

        ; MAIN and AUX buffers are contiguous and already carry Video-7 bit 7.
        ldx     #39
copy_main_row:
        lda     ROW_BUFFER_MAIN,x
main_row_sta:
        sta     $FFFF,x
        dex
        bpl     copy_main_row

        stz     RAMWORKS
        stz     RAMWRTON
        ldx     #39
copy_aux_row:
        lda     ROW_BUFFER_AUX,x
aux_row_sta:
        sta     $FFFF,x
        dex
        bpl     copy_aux_row
        stz     RAMWRTOFF

        clc
        lda     DEST_TABLE
        adc     #$02
        sta     DEST_TABLE
        bcc     :+
        inc     DEST_TABLE_HI
:
        jsr     ENGINE_ADVANCE_ROWS
        dec     ROWS_REMAINING
        bne     slice_row
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF
        rts

; Resolve a source row in A/X through DIRECTORY_BASE. Every directory entry is
; bank,address-low,address-high. The directory remains in MAIN.
resolve_program:
        sta     ROW_TEMP
        stx     ROW_TEMP_HI
        asl     a
        sta     DIRECTORY_PTR
        txa
        rol     a
        sta     DIRECTORY_PTR_HI
        clc
        lda     DIRECTORY_PTR
        adc     ROW_TEMP
        sta     DIRECTORY_PTR
        lda     DIRECTORY_PTR_HI
        adc     ROW_TEMP_HI
        sta     DIRECTORY_PTR_HI
        clc
        lda     DIRECTORY_PTR
        adc     DIRECTORY_BASE
        sta     DIRECTORY_PTR
        lda     DIRECTORY_PTR_HI
        adc     DIRECTORY_BASE_HI
        sta     DIRECTORY_PTR_HI
        ldy     #$00
        lda     (DIRECTORY_PTR),y
        sta     PROGRAM_BANK
        iny
        lda     (DIRECTORY_PTR),y
        sta     PROGRAM_PTR
        iny
        lda     (DIRECTORY_PTR),y
        sta     PROGRAM_PTR_HI
        rts

; Execute the selected row program from its RamWorks bank. A synthetic RTS
; address enters this mirrored return stub, which restores MAIN execution.
execute_program:
        lda     PROGRAM_BANK
        sta     RAMWORKS
        lda     #>(ENGINE_PROGRAM_RETURN-1)
        pha
        lda     #<(ENGINE_PROGRAM_RETURN-1)
        pha
        stz     RAMRDON
        jmp     (PROGRAM_PTR)
program_return:
        stz     RAMRDOFF
        rts

advance_rows:
        inc     _parallax_deep_row
        bne     @deep_check
        inc     _parallax_deep_row+1
@deep_check:
        lda     _parallax_deep_row+1
        cmp     #$01
        bne     @nebula
        lda     _parallax_deep_row
        cmp     #$80
        bne     @nebula
        stz     _parallax_deep_row
        stz     _parallax_deep_row+1
@nebula:
        inc     _parallax_nebula_row
        bne     @nebula_check
        inc     _parallax_nebula_row+1
@nebula_check:
        lda     _parallax_nebula_row+1
        cmp     #$01
        bne     @asteroids
        lda     _parallax_nebula_row
        cmp     #$80
        bne     @asteroids
        stz     _parallax_nebula_row
        stz     _parallax_nebula_row+1
@asteroids:
        inc     _parallax_asteroids_row
        bne     @asteroids_check
        inc     _parallax_asteroids_row+1
@asteroids_check:
        lda     _parallax_asteroids_row+1
        cmp     #$01
        bne     @woven
        lda     _parallax_asteroids_row
        cmp     #$80
        bne     @woven
        stz     _parallax_asteroids_row
        stz     _parallax_asteroids_row+1
@woven:
        inc     _parallax_woven_row
        bne     :+
        inc     _parallax_woven_row+1
:
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

; Cache one exact ship row from bank 6 into common MAIN zero page. Each of the
; eight seven-dot groups is stored as (keep mask, color data), so opaque black
; pixels clear the background while transparent dots remain untouched.
ship_cache_entry:
        stz     RAMRDON
        ldy     #$00
@copy:
        lda     (SHIP_SOURCE),y
        sta     SHIP_CACHE,y
        iny
        cpy     #$10
        bne     @copy
        stz     RAMRDOFF
        rts

; Apply four alternating groups from the cached row to the currently selected
; plane. SHIP_CACHE_INDEX is 0 for local even groups or 2 for local odd groups.
ship_apply_row:
        ldx     SHIP_CACHE_INDEX
        ldy     #$00
        lda     #$04
        sta     SHIP_GROUPS
@group:
        lda     (SHIP_DEST),y
        and     SHIP_CACHE,x
        inx
        ora     SHIP_CACHE,x
        ora     #$80
        sta     (SHIP_DEST),y
        inx
        inx
        inx
        iny
        dec     SHIP_GROUPS
        bne     @group
        rts

; Run the same four-group compositor against bank-zero AUX video. The engine
; is mirrored in bank zero, so execution remains valid after RAMRD is enabled.
ship_aux_entry:
        stz     RAMWORKS
        stz     RAMWRTON
        stz     RAMRDON
        jsr     ENGINE_SHIP_APPLY_ROW
        stz     RAMRDOFF
        stz     RAMWRTOFF
        rts

engine_blob_end:

ENGINE_SLICE_ENTRY         = ENGINE_ADDRESS + (slice_entry-engine_blob)
ENGINE_RESOLVE_PROGRAM     = ENGINE_ADDRESS + (resolve_program-engine_blob)
ENGINE_EXECUTE_PROGRAM     = ENGINE_ADDRESS + (execute_program-engine_blob)
ENGINE_PROGRAM_RETURN      = ENGINE_ADDRESS + (program_return-engine_blob)
ENGINE_ADVANCE_ROWS        = ENGINE_ADDRESS + (advance_rows-engine_blob)
ENGINE_MAIN_ROW_STA        = ENGINE_ADDRESS + (main_row_sta-engine_blob)
ENGINE_AUX_ROW_STA         = ENGINE_ADDRESS + (aux_row_sta-engine_blob)
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
ENGINE_SHIP_CACHE_ENTRY    = ENGINE_ADDRESS + (ship_cache_entry-engine_blob)
ENGINE_SHIP_APPLY_ROW      = ENGINE_ADDRESS + (ship_apply_row-engine_blob)
ENGINE_SHIP_AUX_ENTRY      = ENGINE_ADDRESS + (ship_aux_entry-engine_blob)

.assert (engine_blob_end-engine_blob) <= $0300, error, "A13C engine exceeds its $0D00-$0FFF window"

; Sprite AUX execution reads this table from bank zero at its linked address,
; so the loader mirrors it after installing the engine.
mirror_data_start:
woven_destination_table:
.repeat 158, ROW
        .word   $2000 + (((20+ROW) & 7) << 10) + (((20+ROW) & $38) << 4) + (((20+ROW) >> 6) * $28)
        .word   $4000 + (((20+ROW) & 7) << 10) + (((20+ROW) & $38) << 4) + (((20+ROW) >> 6) * $28)
.endrepeat
mirror_data_end:

parallax_path:
        .byte   21, "/A13INVASION/PARALLAX"

.segment "DATA"

open_params:
        .byte   3
        .word   parallax_path
        .word   OPEN_IO_BUFFER
open_ref:
        .byte   0

read_params:
        .byte   4
read_ref:
        .byte   0
read_buffer:
        .word   A13C_HEADER
read_requested:
        .word   $1000
read_transferred:
        .word   0

close_params:
        .byte   1
close_ref:
        .byte   0

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

install_engines:
        ; MAIN dispatcher/renderer copy.
        jsr     prepare_engine_copy
        jsr     copy_bytes

        ; Bank zero supports AUX drawing, banks 1-5 execute generated A13C row
        ; programs, and bank 6 supplies exact ship rows to the mirrored stub.
        stz     LOADER_BANK
@next_engine_bank:
        jsr     prepare_engine_copy
        lda     LOADER_BANK
        sta     RAMWORKS
        stz     RAMWRTON
        jsr     copy_bytes
        stz     RAMWRTOFF
        inc     LOADER_BANK
        lda     LOADER_BANK
        cmp     #(A13C_BANK_COUNT+1)
        bne     @next_engine_bank
        stz     RAMWORKS
        rts

mirror_sprite_table:
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
        rts

validate_a13c:
        lda     A13C_HEADER+0
        cmp     #'A'
        bne     @header_bad
        lda     A13C_HEADER+1
        cmp     #'1'
        bne     @header_bad
        lda     A13C_HEADER+2
        cmp     #'3'
        bne     @header_bad
        lda     A13C_HEADER+3
        cmp     #'C'
        bne     @header_bad
        lda     A13C_HEADER+4
        cmp     #A13C_VERSION
        bne     @header_bad
        lda     A13C_HEADER+5
        cmp     #A13C_LAYER_COUNT
        bne     @header_bad
        lda     A13C_HEADER+6
        cmp     #A13C_ROW_BYTES
        bne     @header_bad
        lda     A13C_HEADER+7
        cmp     #A13C_BANK_COUNT
        bne     @header_bad
        lda     A13C_HEADER+8
        cmp     #A13C_WIDTH_LO
        bne     @header_bad
        lda     A13C_HEADER+9
        cmp     #A13C_WIDTH_HI
        bne     @header_bad
        lda     A13C_HEADER+10
        cmp     #A13C_HEIGHT_LO
        bne     @header_bad
        lda     A13C_HEADER+11
        cmp     #A13C_HEIGHT_HI
        bne     @header_bad
        lda     A13C_HEADER+12
        cmp     #$10
        bne     @header_bad
        lda     A13C_HEADER+13
        bne     @header_bad
        lda     A13C_HEADER+14
        bne     @header_bad
        lda     A13C_HEADER+15
        cmp     #$10
        bne     @header_bad

        bra     @header_ok
@header_bad:
        jmp     @bad
@header_ok:

        ; Validate all 1,152 (bank,address) entries before executing any asset.
        lda     #<A13C_DIRECTORY
        sta     COPY_SOURCE
        lda     #>A13C_DIRECTORY
        sta     COPY_SOURCE_HI
        lda     #<$0480
        sta     COPY_COUNT
        lda     #>$0480
        sta     COPY_COUNT_HI
@entry:
        ldy     #$00
        lda     (COPY_SOURCE),y
        beq     @bad
        cmp     #(A13C_PROGRAM_BANK_COUNT+1)
        bcs     @bad
        iny
        iny
        lda     (COPY_SOURCE),y
        cmp     #$20
        bcc     @bad
        cmp     #$A0
        bcs     @bad
        clc
        lda     COPY_SOURCE
        adc     #$03
        sta     COPY_SOURCE
        bcc     :+
        inc     COPY_SOURCE_HI
:
        lda     COPY_COUNT
        bne     :+
        dec     COPY_COUNT_HI
:
        dec     COPY_COUNT
        lda     COPY_COUNT
        ora     COPY_COUNT_HI
        bne     @entry
        lda     #$01
        rts
@bad:
        lda     #$00
        rts

; Copy the two-page main READ buffer to the current bank/destination. The MLI
; and all source reads stay in MAIN while RAMWRT redirects only payload stores.
copy_read_buffer:
        lda     #<READ_BUFFER
        sta     COPY_SOURCE
        lda     #>READ_BUFFER
        sta     COPY_SOURCE_HI
        lda     #<$0200
        sta     COPY_COUNT
        lda     #>$0200
        sta     COPY_COUNT_HI
        lda     LOADER_BANK
        sta     RAMWORKS
        stz     RAMWRTON
        jsr     copy_bytes
        stz     RAMWRTOFF
        stz     RAMWORKS
        rts

; fastcall unsigned char parallax_assets_load(void)
; Read A13C through ProDOS/SmartPort, validate it, install six 32 KiB bank
; images, then mirror the bank-safe engine. Returns A=1,X=0 on success.
_parallax_assets_load:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF

        jsr     MLI
        .byte   MLI_OPEN
        .word   open_params
        bcc     :+
        jmp     loader_invalid
:
        lda     open_ref
        sta     read_ref
        sta     close_ref

        ; The 4 KiB prefix lands at $1000. Header and directory occupy
        ; $1000-$1D8F and therefore survive the subsequent HGR page clear.
        lda     #<A13C_HEADER
        sta     read_buffer
        lda     #>A13C_HEADER
        sta     read_buffer+1
        stz     read_requested
        lda     #$10
        sta     read_requested+1
        jsr     MLI
        .byte   MLI_READ
        .word   read_params
        bcs     loader_invalid_close
        lda     read_transferred
        bne     loader_invalid_close
        lda     read_transferred+1
        cmp     #$10
        bne     loader_invalid_close
        jsr     validate_a13c
        beq     loader_invalid_close

        ; Remaining file data is six consecutive 32 KiB bank images.
        lda     #<READ_BUFFER
        sta     read_buffer
        lda     #>READ_BUFFER
        sta     read_buffer+1
        stz     read_requested
        lda     #$02
        sta     read_requested+1
        lda     #$01
        sta     LOADER_BANK
loader_next_bank:
        lda     #<A13C_BANK_BASE
        sta     COPY_DEST
        lda     #>A13C_BANK_BASE
        sta     COPY_DEST_HI
        lda     #64
        sta     ROWS_REMAINING
loader_next_block:
        jsr     MLI
        .byte   MLI_READ
        .word   read_params
        bcs     loader_invalid_close
        lda     read_transferred
        bne     loader_invalid_close
        lda     read_transferred+1
        cmp     #$02
        bne     loader_invalid_close
        jsr     copy_read_buffer
        dec     ROWS_REMAINING
        bne     loader_next_block
        inc     LOADER_BANK
        lda     LOADER_BANK
        cmp     #(A13C_BANK_COUNT+1)
        bne     loader_next_bank

        jsr     MLI
        .byte   MLI_CLOSE
        .word   close_params
        bcs     loader_invalid
        jsr     install_engines
        jsr     mirror_sprite_table
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF
        lda     #$01
        ldx     #$00
        rts

loader_invalid_close:
        jsr     MLI
        .byte   MLI_CLOSE
        .word   close_params
loader_invalid:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF
        lda     #$00
        ldx     #$00
        rts

; Fixed-ZP slice API. No cc65 software-stack access occurs after entry.
_parallax_render_slice:
        sta     ROWS_REMAINING
        beq     @empty
        php
        sei
        jsr     ENGINE_SLICE_ENTRY
        plp
        rts
@empty:
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF
        rts

_video_sprite_fast:
        jsr     ENGINE_SPRITE_ENTRY
        rts

; Draw one exact-alpha 56x64 player frame. SHIP_X is a seven-dot group origin;
; its low two bits select the precompiled global DHGR color phase. The 32 KiB
; ship bank stores 32 fixed 1 KiB variants in frame-major, phase-minor order.
_video_ship_fast:
        php
        sei
        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF

        lda     SHIP_X
        lsr
        sta     SHIP_BYTE_X

        lda     SHIP_FRAME
        and     #$07
        asl
        asl
        sta     SHIP_SOURCE_HI
        lda     SHIP_X
        and     #$03
        clc
        adc     SHIP_SOURCE_HI
        asl
        asl
        clc
        adc     #$20
        sta     SHIP_SOURCE_HI
        stz     SHIP_SOURCE

        lda     #<(woven_destination_table + ((144-20)*4))
        sta     SHIP_TABLE
        lda     #>(woven_destination_table + ((144-20)*4))
        sta     SHIP_TABLE_HI
        lda     #64
        sta     SHIP_ROWS

@row:
        lda     #A13C_SHIP_BANK
        sta     RAMWORKS
        jsr     ENGINE_SHIP_CACHE_ENTRY

        ldy     #$00
        clc
        lda     (SHIP_TABLE),y
        adc     SHIP_BYTE_X
        sta     SHIP_DEST
        iny
        lda     (SHIP_TABLE),y
        adc     #$00
        sta     SHIP_DEST_HI

        ; MAIN receives local odd groups from an even origin and local even
        ; groups from an odd origin. Both begin at the unadjusted byte column.
        lda     SHIP_X
        and     #$01
        bne     @main_even
        lda     #$02
        bra     @main_ready
@main_even:
        lda     #$00
@main_ready:
        sta     SHIP_CACHE_INDEX
        jsr     ENGINE_SHIP_APPLY_ROW

        ; AUX uses the complementary groups. An odd group origin begins its
        ; first AUX byte in the following 14-dot memory column.
        lda     SHIP_X
        and     #$01
        beq     @aux_even
        inc     SHIP_DEST
        bne     :+
        inc     SHIP_DEST_HI
:
        lda     #$02
        bra     @aux_ready
@aux_even:
        lda     #$00
@aux_ready:
        sta     SHIP_CACHE_INDEX
        jsr     ENGINE_SHIP_AUX_ENTRY

        clc
        lda     SHIP_SOURCE
        adc     #$10
        sta     SHIP_SOURCE
        bcc     :+
        inc     SHIP_SOURCE_HI
:
        clc
        lda     SHIP_TABLE
        adc     #$02
        sta     SHIP_TABLE
        bcc     :+
        inc     SHIP_TABLE_HI
:
        dec     SHIP_ROWS
        bne     @row

        stz     RAMRDOFF
        stz     RAMWRTOFF
        stz     RAMWORKS
        stz     ALTZPOFF
        plp
        rts
