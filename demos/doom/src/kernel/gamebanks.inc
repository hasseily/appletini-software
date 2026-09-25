; Common-main gateways for code in RamWorks auxiliary language cards.
; See gamebanks.s for entry conditions and interrupt restrictions.
.ifndef GAMEBANKS_INC
GAMEBANKS_INC = 1
GB_MAIN_CONTEXT = $80             ; ALTZP off: main zero page/stack/LC
GB_CONTEXT_COUNT = 129            ; raw $C073 banks 0..127, plus main
GB_GAME_ZP_SIZE = 8               ; gmo, gth, gli, gpt
GB_C_ZP_SIZE = 26                 ; cc65 zeropage.inc: zpspace
GB_FAR_ZP_SIZE = 12              ; far_src..far_idx kernel arguments/results
GB_SCRATCH_ZP_SIZE = 8           ; ktmp is also a far-transfer destination
GB_ZP_SIZE = GB_GAME_ZP_SIZE + GB_C_ZP_SIZE + GB_FAR_ZP_SIZE + GB_SCRATCH_ZP_SIZE
.global gb_call

; Public function pointers name this stable main-memory entry. The
; descriptor is consumed; gb_call returns to this entry's original caller.
.macro GB_GATE bank, target
    .assert (bank >= 0) .and (bank <= GB_MAIN_CONTEXT), error, "invalid game code bank"
    jsr gb_call
    .byte bank
    .word target
.endmacro
.endif
