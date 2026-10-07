# src/native/m11/s2fin.mk: part s2fin's builds (docs/SCREENS.md: the
# help, title and end screens), read by src/native/m11.mk
# (make -f m11.mk part P=s2fin):
#
#   build/native/m11/s2fin/gen/lgame.inc   the game's generated include
#                                    (tools/native/llayout.py --game:
#                                    WI_ACCEL, G_GAMEACTION, G_GAMESTATE),
#                                    read only
#   build/native/m11/s2fin/gen/s2fin.inc   tools/native/s2fin.py --inc: the
#                                    release's lump numbers of HELP2 and
#                                    TITLEPIC (PALST's picturenum), the end
#                                    text's length, GS_FINALE, the font's
#                                    places and widths
#   build/native/m11/s2fin/gen/s2pal.inc   tools/native/s2pal.py --inc (part
#                                    s2pal's), for s2_pal.s and s2_nib.s
#   build/native/m11/s2fin/finw.*    the image FINW: s2_fin.s, the drawers,
#                                    the publish, s2_pal, s2_nib, pl_poll
#                                    (part plinput's pl_input.s), fx_service
#                                    (src/sound/fx.s -D FX_SERVICE) and
#                                    fx.s's card part with S2's player
#                                    (build/sound65, read only) and pl_irq.s
#                                    (pl_time), with the driver s2_drv.s
#
# The 2D store's include and manifest (part s2data: make -f m11.mk part
# P=s2data, which this file does not rebuild) and S2's objects (make -C
# src/sound) must exist.

S2FIN_DIR := $(M11)/s2fin
S2FIN_GEN := $(S2FIN_DIR)/gen
S2FIN_DATA := $(M11)/s2data
S2FIN_SOUND65 := $(ROOT)/build/sound65
$(eval $(call M11_COMMON,$(S2FIN_DIR)))

$(S2FIN_GEN)/lgame.inc: $(TOOLS)/llayout.py $(TOOLS)/rlayout.py
	@mkdir -p $(S2FIN_GEN)
	$(PYTHON) $(TOOLS)/llayout.py --game $@
$(S2FIN_GEN)/s2fin.inc: $(TOOLS)/s2fin.py $(S2FIN_DATA)/s2data.json
	@mkdir -p $(S2FIN_GEN)
	$(PYTHON) $(TOOLS)/s2fin.py --inc $@
$(S2FIN_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(LAYOUTS)
	@mkdir -p $(S2FIN_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@

# S2's objects, read only (the guarded rules of plboot.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(S2FIN_SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(S2FIN_SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif
# (one rule for the store's manifest, which part s2menu2's fragment also
# names)
ifndef M11_S2DATA_JSON_RULE
M11_S2DATA_JSON_RULE := 1
$(S2FIN_DATA)/s2data.json:
	@echo "no $(S2FIN_DATA)/s2data.json: make -f m11.mk part P=s2data" >&2
	@exit 1
endif

S2FIN_ASFLAGS = $(ASFLAGS) -I $(S2FIN_GEN) -I $(S2FIN_DATA)
S2FIN_INCS := $(M11_INCS) $(S2FIN_GEN)/lgame.inc $(S2FIN_GEN)/s2fin.inc \
              $(S2FIN_DATA)/s2data.inc

$(S2FIN_DIR)/s2_fin.o: s2_fin.s $(S2FIN_INCS)
	$(CA65) $(S2FIN_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2FIN_DIR)/pl_input.o: pl_input.inc
$(S2FIN_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2FIN_GEN)/s2pal.inc
	$(CA65) $(S2FIN_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2FIN_DIR)/s2_nib.o: s2_nib.s $(M11_INCS) $(S2FIN_GEN)/s2pal.inc
	$(CA65) $(S2FIN_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2FIN_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                   $(S2FIN_SOUND65)/tables.inc
	@mkdir -p $(S2FIN_DIR)
	$(CA65) $(ASFLAGS) -I $(S2FIN_SOUND65) -D FX_SERVICE -o $@ \
	    -l $(@:.o=.lst) $<
$(S2FIN_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                        $(S2FIN_SOUND65)/tables.inc
	@mkdir -p $(S2FIN_DIR)
	$(CA65) $(ASFLAGS) -I $(S2FIN_SOUND65) -o $@ -l $(@:.o=.lst) $<

S2FIN_SHARED := $(S2FIN_DIR)/s2_draw.o $(S2FIN_DIR)/s2_pub.o \
                $(S2FIN_DIR)/s2_pal.o $(S2FIN_DIR)/s2_nib.o \
                $(S2FIN_DIR)/pl_input.o $(S2FIN_DIR)/fx.o \
                $(S2FIN_DIR)/fx-card.o $(S2FIN_DIR)/pl_irq.o \
                $(S2FIN_SOUND65)/player.o \
                $(S2FIN_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2FIN_DIR)/%)
$(eval $(call M11_IMAGE,$(S2FIN_DIR),finw,FINW,\
    $(S2FIN_DIR)/s2_fin.o $(S2FIN_SHARED)))

.PHONY: s2fin_all
s2fin_all: gen $(S2FIN_DIR)/finw.map

PARTS += s2fin
