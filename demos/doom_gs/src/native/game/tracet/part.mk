# src/native/game/tracet/part.mk: part tracet of the game's tic code
# (docs/GAME.md): the block
# steps of a long trace with the fast vertex sides (traceLines,
# traceThings with thFast and thSide) and their setup (sideSetup,
# longTrace). Upstream's patched templates (tlP1, tlP2, thP, gtP1, gtP2,
# ptT1, ptT2) and their patchers (vsPatch, ptPatch) are data here, and
# thFastL is upstream's long-call wrapper: none has code of its own.
PART := tracet
WAVE := 3
tracet_SRC := game/tracet/tracet.s
tracet_ENTRIES := traceLines traceThings sideSetup longTrace
