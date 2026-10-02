# src/native/m11/s2menu1.mk: part s2menu1's builds (docs/SCREENS.md 1.5.3,
# 4.1, 7.3; docs/m11-parts/s2menu1.md), read by src/native/m11.mk (make
# -f m11.mk part P=s2menu1):
#
#   build/native/m11/s2menu1/gen/s2menu1.inc  tools/native/s2menu1.py
#                               --inc: the game's places, the message ids,
#                               the native state and MENUW's places
#                               (STANDINs, requests S2MENU1-1, -2), the
#                               patches and the font from part s2data's
#                               store (s2data.json, GFX.1)
#   build/native/m11/s2menu1/gen/fxchan.inc, s2pal.inc   tools/sound/
#                               fxchan.py --inc and tools/native/s2pal.py
#                               --inc (the shared objects' includes)
#   build/native/m11/s2menu1/s2m1.*   the MENUW image: s2_menu.s, s2_mvid.s,
#                               the shared objects of SCREENS.md 4.1's size
#                               table (s2_draw, s2_pub, s2_pal, fx_service,
#                               fx_chan -D FXC_NOSEP with fx_pcache, part
#                               plinput's pl_poll and pl_keys since wave
#                               5), part s2menu2's s2_menu2.s (one MENUW,
#                               request S2MENU2-3, wave 6), the test glue
#                               s2_menut.s, under the
#                               test driver s2_drv with fx.s's card part,
#                               pl_irq.s (pl_time) and S2's player
#                               (build/sound65, read only)
#   build/native/m11/s2menu1/s2m1t.*  the same with the sound log
#                               (-D S2M_SNDLOG): the checkpoint's image
#
# S2M1SRC can name a copy of src/native's s2_menu.s and s2_mvid.s and
# S2M1_DIR another build directory (the planted bugs of
# tools/native/s2menu1.py); the other sources come from the tree.

S2M1_DIR ?= $(M11)/s2menu1
S2M1SRC ?= $(ROOT)/src/native
S2M1_GEN := $(S2M1_DIR)/gen
SOUND65 ?= $(ROOT)/build/sound65
S2M1_JSON := $(M11)/s2data/s2data.json
S2M1_ASFLAGS = $(ASFLAGS) -I $(S2M1_GEN) -I $(SOUND65)
S2M1_INC := $(S2M1_GEN)/s2menu1.inc
S2M1_INCS := $(M11_INCS) $(S2M1_INC) $(S2M1_GEN)/fxchan.inc \
             $(S2M1_GEN)/s2pal.inc
# part s2menu2's s2_menu2.s also reads these two (S2MENU2-3)
S2M1_M2INCS := $(S2M1_INCS) $(S2M1_GEN)/s2menu2.inc $(S2M1_GEN)/plkeys.inc

$(eval $(call M11_COMMON,$(S2M1_DIR)))

$(S2M1_INC): $(TOOLS)/s2menu1.py $(LAYOUTS) $(S2M1_JSON)
	@mkdir -p $(S2M1_GEN)
	$(PYTHON) $(TOOLS)/s2menu1.py --inc $@
$(S2M1_GEN)/fxchan.inc: $(ROOT)/tools/sound/fxchan.py $(LAYOUTS)
	@mkdir -p $(S2M1_GEN)
	$(PYTHON) $(ROOT)/tools/sound/fxchan.py --inc $@
$(S2M1_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2M1_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(S2M1_GEN)/s2menu2.inc: $(TOOLS)/s2menu2.py $(TOOLS)/s2menu1.py $(LAYOUTS) \
    $(S2M1_JSON)
	@mkdir -p $(S2M1_GEN)
	$(PYTHON) $(TOOLS)/s2menu2.py --inc $@
$(S2M1_GEN)/plkeys.inc: $(TOOLS)/plkeys.py
	@mkdir -p $(S2M1_GEN)
	$(PYTHON) $(TOOLS)/plkeys.py --inc $@
# (one rule for the store's manifest, which part s2hud's fragment also
# names: wave 5's integration)
ifndef M11_S2DATA_JSON_RULE
M11_S2DATA_JSON_RULE := 1
$(S2M1_JSON):
	@echo "no $(S2M1_JSON): make -f m11.mk part P=s2data" >&2
	@exit 1
endif

# S2's objects, read only (as fxplay.mk and fxchan.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

$(S2M1_DIR)/s2_menu.o: $(S2M1SRC)/s2_menu.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/s2_menu-log.o: $(S2M1SRC)/s2_menu.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -D S2M_SNDLOG -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/s2_mvid.o: $(S2M1SRC)/s2_mvid.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/s2_menut.o: s2_menut.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/s2_menu2.o: s2_menu2.s $(S2M1_M2INCS)
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/s2_pal.o: s2_pal.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/fx_chan-ns.o: fx_chan.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -D FXC_NOSEP -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/fx_pcache.o: fx_pcache.s $(S2M1_INCS)
	$(CA65) $(S2M1_ASFLAGS) -D FXC_MSCR -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(S2M1_INCS) $(SOUND65)/tables.inc
	$(CA65) $(S2M1_ASFLAGS) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(S2M1_INCS) $(SOUND65)/tables.inc
	$(CA65) $(S2M1_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M1_DIR)/pl_input.o $(S2M1_DIR)/pl_keys.o: pl_input.inc

S2M1_SHARED := $(S2M1_DIR)/s2_mvid.o $(S2M1_DIR)/s2_menu2.o \
               $(S2M1_DIR)/s2_draw.o \
               $(S2M1_DIR)/s2_pub.o $(S2M1_DIR)/s2_pal.o $(S2M1_DIR)/fx.o \
               $(S2M1_DIR)/fx_chan-ns.o $(S2M1_DIR)/fx_pcache.o \
               $(S2M1_DIR)/s2_menut.o $(S2M1_DIR)/fx-card.o \
               $(S2M1_DIR)/pl_input.o $(S2M1_DIR)/pl_keys.o \
               $(S2M1_DIR)/pl_irq.o \
               $(SOUND65)/player.o $(S2M1_DIR)/s2_drv.o \
               $(M11_COMMON_OBJS:%=$(S2M1_DIR)/%)
$(eval $(call M11_IMAGE,$(S2M1_DIR),s2m1,MENUW,\
    $(S2M1_DIR)/s2_menu.o $(S2M1_SHARED)))
$(eval $(call M11_IMAGE,$(S2M1_DIR),s2m1t,MENUW,\
    $(S2M1_DIR)/s2_menu-log.o $(S2M1_SHARED)))

.PHONY: s2menu1_all
s2menu1_all: gen $(S2M1_DIR)/s2m1.map $(S2M1_DIR)/s2m1t.map

PARTS += s2menu1
