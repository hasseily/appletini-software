# src/native/m11/s2hud.mk: part s2hud's builds (docs/SCREENS.md), read
# by src/native/m11.mk:
#
#   build/native/m11/s2hud/HUDTXT.1  the message ids' and the titles' texts,
#                                    a bank file for S2STATE (SS_HUDMSG)

S2HUD_DIR := $(M11)/s2hud

$(S2HUD_DIR)/HUDTXT.1: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(S2HUD_DIR)
	$(PYTHON) $(TOOLS)/s2msgs.py --bank $@

.PHONY: s2hud_all
s2hud_all: $(S2HUD_DIR)/HUDTXT.1

PARTS += s2hud
# make -f m11.mk (all) writes the texts too
M11_HOST += $(S2HUD_DIR)/HUDTXT.1
