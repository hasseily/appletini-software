# src/native/m11/s2fin.mk: part s2fin's builds (docs/SCREENS.md 1.5.6-1.5.8,
# 4.1, 4.7, 7.3; docs/m11-parts/s2fin.md), read by src/native/m11.mk
# (make -f m11.mk part P=s2fin):
#
#   build/native/m11/s2fin/gen/lgame.inc   milestone 10's generated include
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
#                                    (pl_time), under the test driver
#   build/native/m11/s2fin/s2ft.*    the same with the tic side s2t_fin.s
#                                    and the test glue s2_fint.s
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
$(S2FIN_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2FIN_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@

ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(S2FIN_SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(S2FIN_SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif
# (one rule for the store's manifest, which parts s2menu1's and s2hud's
# fragments also name)
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
$(S2FIN_DIR)/s2t_fin.o: s2t_fin.s $(S2FIN_INCS)
	$(CA65) $(S2FIN_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2FIN_DIR)/s2_fint.o: s2_fint.s $(S2FIN_INCS)
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
$(eval $(call M11_IMAGE,$(S2FIN_DIR),s2ft,FINW,\
    $(S2FIN_DIR)/s2_fint.o $(S2FIN_DIR)/s2_fin.o $(S2FIN_DIR)/s2t_fin.o \
    $(S2FIN_SHARED)))

.PHONY: s2fin_all
s2fin_all: gen $(S2FIN_DIR)/finw.map $(S2FIN_DIR)/s2ft.map

PARTS += s2fin
