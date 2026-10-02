# src/native/m11/s2hud.mk: part s2hud's builds (docs/SCREENS.md 7.3,
# docs/m11-parts/s2hud.md), read by src/native/m11.mk:
#
#   build/native/m11/s2hud/gen/s2hud.inc     tools/native/s2msgs.py
#                                    --hud-inc: the game's places the HUD
#                                    reads (player.message, G_SHOWMSG,
#                                    G_MSGKEEP, G_GAMEMAP, AUTOMAP) and the
#                                    stand-ins of requests S2HUD-1, -3
#   build/native/m11/s2hud/gen/s2msgs.inc    the font table (the glyphs'
#                                    places from part s2data's s2data.json)
#   build/native/m11/s2hud/HUDTXT.1  the message ids' and the titles' texts,
#                                    a bank file for S2STATE (SS_HUDMSG);
#                                    HUDTXT-test.1 the same with the test's
#                                    synthetic lines
#   build/native/m11/s2hud/gen/s2pal.inc   tools/native/s2pal.py --inc (part
#                                    s2pal's), for s2_pal.s
#   build/native/m11/s2hud/s2ht.*    P2DW's room: s2_hu.s, s2t_hu.s, the
#                                    drawers, the publish, part s2pal's
#                                    s2_pal.s (s2_begin; the glue sets
#                                    s2_begun, so it never runs here: the
#                                    palettes are s2pal's region; until the
#                                    final integration the stand-in
#                                    s2_beginstub.s) and the test glue
#                                    s2_hut.s,
#                                    with MATHW, the far layer and the test
#                                    driver (tools/native/s2hud.py)

S2HUD_DIR := $(M11)/s2hud
S2HUD_GEN := $(S2HUD_DIR)/gen
S2HUD_JSON := $(M11)/s2data/s2data.json
$(eval $(call M11_COMMON,$(S2HUD_DIR)))

$(S2HUD_GEN)/s2hud.inc: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(S2HUD_GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --hud-inc $@
$(S2HUD_GEN)/s2msgs.inc: $(TOOLS)/s2msgs.py $(LAYOUTS) $(S2HUD_JSON)
	@mkdir -p $(S2HUD_GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --inc $@
$(S2HUD_DIR)/HUDTXT.1: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(S2HUD_DIR)
	$(PYTHON) $(TOOLS)/s2msgs.py --bank $@
$(S2HUD_DIR)/HUDTXT-test.1: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(S2HUD_DIR)
	$(PYTHON) $(TOOLS)/s2msgs.py --test --bank $@
# (one rule for the store's manifest, which part s2menu1's fragment also
# names: wave 5's integration)
ifndef M11_S2DATA_JSON_RULE
M11_S2DATA_JSON_RULE := 1
$(S2HUD_JSON):
	@echo "no $(S2HUD_JSON): make -f m11.mk part P=s2data" >&2
	@exit 1
endif

S2HUD_INCS := $(M11_INCS) $(S2HUD_GEN)/s2hud.inc

$(S2HUD_DIR)/s2_hu.o: s2_hu.s $(S2HUD_INCS) $(S2HUD_GEN)/s2msgs.inc
	$(CA65) $(ASFLAGS) -I $(S2HUD_GEN) -o $@ -l $(@:.o=.lst) $<
$(S2HUD_DIR)/s2t_hu.o: s2t_hu.s $(S2HUD_INCS)
	$(CA65) $(ASFLAGS) -I $(S2HUD_GEN) -o $@ -l $(@:.o=.lst) $<
$(S2HUD_DIR)/s2_hut.o: s2_hut.s $(S2HUD_INCS)
	$(CA65) $(ASFLAGS) -I $(S2HUD_GEN) -o $@ -l $(@:.o=.lst) $<
$(S2HUD_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2HUD_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(S2HUD_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2HUD_GEN)/s2pal.inc
	$(CA65) $(ASFLAGS) -I $(S2HUD_GEN) -o $@ -l $(@:.o=.lst) $<

S2HUD_OBJS := $(S2HUD_DIR)/s2_hu.o $(S2HUD_DIR)/s2t_hu.o \
              $(S2HUD_DIR)/s2_hut.o $(S2HUD_DIR)/s2_draw.o \
              $(S2HUD_DIR)/s2_pub.o $(S2HUD_DIR)/s2_pal.o \
              $(S2HUD_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2HUD_DIR)/%)
$(eval $(call M11_IMAGE,$(S2HUD_DIR),s2ht,P2DW,$(S2HUD_OBJS)))

.PHONY: s2hud_all
s2hud_all: gen $(S2HUD_DIR)/s2ht.map $(S2HUD_DIR)/HUDTXT.1 \
           $(S2HUD_DIR)/HUDTXT-test.1

PARTS += s2hud
