# src/native/m11/s2wi.mk: part s2wi's builds (docs/SCREENS.md 1.5.5, 4.1,
# 7.3; docs/m11-parts/s2wi.md), read by src/native/m11.mk
# (make -f m11.mk part P=s2wi):
#
#   build/native/m11/s2wi/gen/lgame.inc   milestone 10's generated include
#                                    (tools/native/llayout.py --game: the wi
#                                    state WI_*, G_WMINFO, WM_*), read only
#   build/native/m11/s2wi/gen/s2wi.inc    tools/native/s2wi.py --inc: the
#                                    release's lump number of WIMAP0 (PALST's
#                                    picturenum)
#   build/native/m11/s2wi/gen/s2pal.inc   tools/native/s2pal.py --inc (part
#                                    s2pal's), for s2_pal.s and s2_nib.s
#   build/native/m11/s2wi/wiw.*      the image WIW: s2_wi.s, the drawers, the
#                                    publish, s2_pal, s2_nib, pl_poll (part
#                                    plinput's pl_input.s; since wave 5's
#                                    integration, S2WI-3), fx_service (src/
#                                    sound/fx.s -D FX_SERVICE) and fx.s's card
#                                    part with S2's player (build/sound65,
#                                    read only) and pl_irq.s (pl_time, in the
#                                    card as the release), under the test
#                                    driver
#   build/native/m11/s2wi/s2wt.*     the same with the test glue s2_wit.s
#
# The 2D store's include (part s2data's build/native/m11/s2data/s2data.inc:
# make -f m11.mk part P=s2data, which this file does not rebuild) and S2's
# objects (make -C src/sound) must exist.

S2WI_DIR := $(M11)/s2wi
S2WI_GEN := $(S2WI_DIR)/gen
S2WI_DATA := $(M11)/s2data
S2WI_SOUND65 := $(ROOT)/build/sound65
$(eval $(call M11_COMMON,$(S2WI_DIR)))

$(S2WI_GEN)/lgame.inc: $(TOOLS)/llayout.py $(TOOLS)/rlayout.py
	@mkdir -p $(S2WI_GEN)
	$(PYTHON) $(TOOLS)/llayout.py --game $@
$(S2WI_GEN)/s2wi.inc: $(TOOLS)/s2wi.py
	@mkdir -p $(S2WI_GEN)
	$(PYTHON) $(TOOLS)/s2wi.py --inc $@
$(S2WI_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2WI_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@

ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(S2WI_SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(S2WI_SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

S2WI_ASFLAGS = $(ASFLAGS) -I $(S2WI_GEN) -I $(S2WI_DATA)
S2WI_INCS := $(M11_INCS) $(S2WI_GEN)/lgame.inc $(S2WI_GEN)/s2wi.inc \
             $(S2WI_DATA)/s2data.inc

$(S2WI_DIR)/s2_wi.o: s2_wi.s $(S2WI_INCS)
	$(CA65) $(S2WI_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2WI_DIR)/s2_wit.o: s2_wit.s $(S2WI_INCS)
	$(CA65) $(S2WI_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2WI_DIR)/pl_input.o: pl_input.inc
$(S2WI_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2WI_GEN)/s2pal.inc
	$(CA65) $(S2WI_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2WI_DIR)/s2_nib.o: s2_nib.s $(M11_INCS) $(S2WI_GEN)/s2pal.inc
	$(CA65) $(S2WI_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2WI_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                  $(S2WI_SOUND65)/tables.inc
	@mkdir -p $(S2WI_DIR)
	$(CA65) $(ASFLAGS) -I $(S2WI_SOUND65) -D FX_SERVICE -o $@ \
	    -l $(@:.o=.lst) $<
$(S2WI_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                       $(S2WI_SOUND65)/tables.inc
	@mkdir -p $(S2WI_DIR)
	$(CA65) $(ASFLAGS) -I $(S2WI_SOUND65) -o $@ -l $(@:.o=.lst) $<

S2WI_SHARED := $(S2WI_DIR)/s2_draw.o $(S2WI_DIR)/s2_pub.o \
               $(S2WI_DIR)/s2_pal.o $(S2WI_DIR)/s2_nib.o \
               $(S2WI_DIR)/pl_input.o $(S2WI_DIR)/fx.o \
               $(S2WI_DIR)/fx-card.o $(S2WI_DIR)/pl_irq.o \
               $(S2WI_SOUND65)/player.o \
               $(S2WI_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2WI_DIR)/%)
$(eval $(call M11_IMAGE,$(S2WI_DIR),wiw,WIW,\
    $(S2WI_DIR)/s2_wi.o $(S2WI_SHARED)))
$(eval $(call M11_IMAGE,$(S2WI_DIR),s2wt,WIW,\
    $(S2WI_DIR)/s2_wit.o $(S2WI_DIR)/s2_wi.o $(S2WI_SHARED)))

.PHONY: s2wi_all
s2wi_all: gen $(S2WI_DIR)/wiw.map $(S2WI_DIR)/s2wt.map

PARTS += s2wi
