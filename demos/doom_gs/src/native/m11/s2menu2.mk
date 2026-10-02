# src/native/m11/s2menu2.mk: part s2menu2's builds (docs/SCREENS.md 1.5.3,
# 4.1, 7.3; docs/m11-parts/s2menu2.md), read by src/native/m11.mk (make
# -f m11.mk part P=s2menu2):
#
#   build/native/m11/s2menu2/gen/s2menu2.inc  tools/native/s2menu2.py
#                               --inc: the load and save titles' x, the
#                               music's byte in SS_SETTINGS
#   build/native/m11/s2menu2/gen/s2menu1.inc, fxchan.inc, s2pal.inc,
#                               plkeys.inc   the other parts' generators
#                               (s2menu1.py, fxchan.py, s2pal.py,
#                               plkeys.py), run into this directory
#   build/native/m11/s2menu2/s2m2.*   MENUW with both menu parts (the same
#                               objects as part s2menu1's s2m1 since wave
#                               6's integration, S2MENU2-3): s2_menu.s,
#                               s2_mvid.s, this part's s2_menu2.s, the
#                               shared objects of SCREENS.md 4.1's size
#                               table and the test glue s2_menut.s, under
#                               the test driver with fx.s's card part,
#                               pl_irq.s and S2's player (build/sound65,
#                               read only)
#   build/native/m11/s2menu2/s2m2t.*  the same with the sound log
#                               (-D S2M_SNDLOG): the checkpoint's image
#
# (The busy sign's font, s2_menu2.s -D M2_SIGNFONT with its test image
# s2sgt, went at wave 6's integration: S2MENU2-4 with S2FIN-8.)
#
# S2M2SRC can name a copy of src/native's s2_menu2.s, S2M2PLSRC one of
# pl_keys.s, S2M2_DIR another build directory (the planted bugs of
# tools/native/s2menu2.py); the other sources come from the tree.

S2M2_DIR ?= $(M11)/s2menu2
S2M2SRC ?= $(ROOT)/src/native
S2M2PLSRC ?= $(ROOT)/src/native
S2M2_GEN := $(S2M2_DIR)/gen
SOUND65 ?= $(ROOT)/build/sound65
S2M2_JSON := $(M11)/s2data/s2data.json
S2M2_ASFLAGS = $(ASFLAGS) -I $(S2M2_GEN) -I $(SOUND65)
S2M2_INC := $(S2M2_GEN)/s2menu2.inc
S2M2_INCS := $(M11_INCS) $(S2M2_INC) $(S2M2_GEN)/s2menu1.inc \
             $(S2M2_GEN)/fxchan.inc $(S2M2_GEN)/s2pal.inc \
             $(S2M2_GEN)/plkeys.inc

$(eval $(call M11_COMMON,$(S2M2_DIR)))

$(S2M2_INC): $(TOOLS)/s2menu2.py $(TOOLS)/s2menu1.py $(LAYOUTS) $(S2M2_JSON)
	@mkdir -p $(S2M2_GEN)
	$(PYTHON) $(TOOLS)/s2menu2.py --inc $@
$(S2M2_GEN)/s2menu1.inc: $(TOOLS)/s2menu1.py $(LAYOUTS) $(S2M2_JSON)
	@mkdir -p $(S2M2_GEN)
	$(PYTHON) $(TOOLS)/s2menu1.py --inc $@
$(S2M2_GEN)/fxchan.inc: $(ROOT)/tools/sound/fxchan.py $(LAYOUTS)
	@mkdir -p $(S2M2_GEN)
	$(PYTHON) $(ROOT)/tools/sound/fxchan.py --inc $@
$(S2M2_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2M2_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(S2M2_GEN)/plkeys.inc: $(TOOLS)/plkeys.py
	@mkdir -p $(S2M2_GEN)
	$(PYTHON) $(TOOLS)/plkeys.py --inc $@
# (one rule for the store's manifest, which parts s2menu1 and s2hud name
# too: wave 5's integration)
ifndef M11_S2DATA_JSON_RULE
M11_S2DATA_JSON_RULE := 1
$(S2M2_JSON):
	@echo "no $(S2M2_JSON): make -f m11.mk part P=s2data" >&2
	@exit 1
endif

# S2's objects, read only (as fxplay.mk, fxchan.mk and s2menu1.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

$(S2M2_DIR)/s2_menu2.o: $(S2M2SRC)/s2_menu2.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/s2_menut.o: s2_menut.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/pl_keys.o: $(S2M2PLSRC)/pl_keys.s pl_input.inc $(M11_INCS)
	$(CA65) $(ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/s2_menu.o: s2_menu.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/s2_menu-log.o: s2_menu.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -D S2M_SNDLOG -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/s2_mvid.o: s2_mvid.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/s2_pal.o: s2_pal.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/fx_chan-ns.o: fx_chan.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -D FXC_NOSEP -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/fx_pcache.o: fx_pcache.s $(S2M2_INCS)
	$(CA65) $(S2M2_ASFLAGS) -D FXC_MSCR -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(S2M2_INCS) $(SOUND65)/tables.inc
	$(CA65) $(S2M2_ASFLAGS) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(S2M2_INCS) $(SOUND65)/tables.inc
	$(CA65) $(S2M2_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2M2_DIR)/pl_input.o: pl_input.inc

S2M2_SHARED := $(S2M2_DIR)/s2_mvid.o $(S2M2_DIR)/s2_menu2.o \
               $(S2M2_DIR)/s2_draw.o $(S2M2_DIR)/s2_pub.o \
               $(S2M2_DIR)/s2_pal.o $(S2M2_DIR)/fx.o \
               $(S2M2_DIR)/fx_chan-ns.o $(S2M2_DIR)/fx_pcache.o \
               $(S2M2_DIR)/s2_menut.o $(S2M2_DIR)/fx-card.o \
               $(S2M2_DIR)/pl_input.o $(S2M2_DIR)/pl_keys.o \
               $(S2M2_DIR)/pl_irq.o \
               $(SOUND65)/player.o $(S2M2_DIR)/s2_drv.o \
               $(M11_COMMON_OBJS:%=$(S2M2_DIR)/%)
$(eval $(call M11_IMAGE,$(S2M2_DIR),s2m2,MENUW,\
    $(S2M2_DIR)/s2_menu.o $(S2M2_SHARED)))
$(eval $(call M11_IMAGE,$(S2M2_DIR),s2m2t,MENUW,\
    $(S2M2_DIR)/s2_menu-log.o $(S2M2_SHARED)))

.PHONY: s2menu2_all
s2menu2_all: gen $(S2M2_DIR)/s2m2.map $(S2M2_DIR)/s2m2t.map

PARTS += s2menu2
