# src/native/m11/fxchan.mk: part fxchan of milestone 11 (docs/SCREENS.md
# 3, 4.4, 4.7, 7.3; tools/sound/README.md "The game side"; docs/m11-parts/
# fxchan.md): the channel logic src/native/fx_chan.s, MENUW's position
# callback src/native/fx_pcache.s and their test machines under
# src/native/fx_cdrv.s. Read by src/native/m11.mk (make -f m11.mk part
# P=fxchan).
#
#   build/native/m11/fxchan/gen/fxchan.inc   tools/sound/fxchan.py --inc
#                                            (the priority table, the
#                                            constants, the stand-ins)
#   build/native/m11/fxchan/gen8/s2.inc      s2-fxch8.inc (FXCH8's places)
#   build/native/m11/fxchan/fxc8.*     FXCH8, 8 channels: isPlaying and
#                                      the positions injected
#   build/native/m11/fxchan/fxc8r.*    FXCH8 with fxplay's fx_isplaying
#   build/native/m11/fxchan/fxc3.*     3 channels (the release's places)
#                                      with fxplay's fx_isplaying
#   build/native/m11/fxchan/fxcm8.*    MENUW's object (-D FXC_NOSEP) and
#                                      fx_pcache, FXCH8, isPlaying injected
#   build/native/m11/fxchan/rel/fx_chan.o   the tic image's object (the
#                                      release's places, no trace): its size
#   build/native/m11/fxchan/fxcmw.*    MENUW's linkage: fx_chan (-D
#                                      FXC_NOSEP), fx_pcache, fx.s's card
#                                      part in MENUW's room under s2_drv
#                                      (the size table's fx_chan row)
#
# The test machines' map comes from tools/native/fxcrun.py --cfg. S2's
# objects are made by src/sound/Makefile into build/sound65 (read only).
# FXCSRC can name a copy of fx_chan.s, fx_pcache.s, fx_cdrv.s, FXSRC one
# of src/sound's fx.s and FXCHAN_DIR another build directory (the planted
# bugs of tests/test_m11_fxchan.py).

FXCHAN_DIR ?= $(M11)/fxchan
FXCSRC ?= $(ROOT)/src/native
FXSRC ?= $(ROOT)/src/sound
SOUND65 ?= $(ROOT)/build/sound65
FXCHAN_GEN := $(FXCHAN_DIR)/gen
FXCHAN_GEN8 := $(FXCHAN_DIR)/gen8
FXCHAN_TOOL := $(ROOT)/tools/sound/fxchan.py
FXCRUN_TOOL := $(TOOLS)/fxcrun.py
FXCHAN_INC := $(FXCHAN_GEN)/fxchan.inc
# the flags without m11.mk's -I $(GEN) first, so FXCH8's s2.inc can come
# before the test build's
FXC_FLAGS = --cpu 65C02 -g -I $(FXCHAN_GEN) -I $(GEN) -I $(ROOT)/src/native \
            --bin-include-dir $(TABLES) --bin-include-dir $(TABLES)/math
FXC8_FLAGS = --cpu 65C02 -g -I $(FXCHAN_GEN8) -I $(FXCHAN_GEN) -I $(GEN) \
             -I $(ROOT)/src/native --bin-include-dir $(TABLES) \
             --bin-include-dir $(TABLES)/math
FXCHAN_DEPS := $(M11_INCS) $(FXCHAN_INC) $(GEN)/s2-fxch8.inc

$(eval $(call M11_COMMON,$(FXCHAN_DIR)))

$(FXCHAN_INC): $(FXCHAN_TOOL) $(LAYOUTS)
	@mkdir -p $(FXCHAN_GEN)
	$(PYTHON) $(FXCHAN_TOOL) --inc $@

$(FXCHAN_GEN8)/s2.inc: $(GEN)/s2-fxch8.inc
	@mkdir -p $(FXCHAN_GEN8)
	cp $< $@

$(FXCHAN_DIR)/fxct.cfg: $(FXCRUN_TOOL) $(LAYOUTS)
	@mkdir -p $(FXCHAN_DIR)
	$(PYTHON) $(FXCRUN_TOOL) --cfg $@

# S2's objects, read only (the same guarded rules in fxplay.mk and
# fxchan.mk: each part builds alone, and m11.mk's all includes both)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

# ---- objects: c3 (the test build's s2.inc, 3 channels), c8 (FXCH8) ----
define FXCHAN_OBJ
$(FXCHAN_DIR)/$(1)/$(2).o: $(3) $$(FXCHAN_DEPS) $(FXCHAN_GEN8)/s2.inc
	@mkdir -p $(FXCHAN_DIR)/$(1)
	$$(CA65) $(4) $(5) -o $$@ -l $$(@:.o=.lst) $$<
endef

$(eval $(call FXCHAN_OBJ,c8,fx_chan,$(FXCSRC)/fx_chan.s,$$(FXC8_FLAGS),-D FXC_TRACE))
$(eval $(call FXCHAN_OBJ,c8,fx_chan-ns,$(FXCSRC)/fx_chan.s,$$(FXC8_FLAGS),-D FXC_NOSEP -D FXC_TRACE))
$(eval $(call FXCHAN_OBJ,c8,fx_pcache,$(FXCSRC)/fx_pcache.s,$$(FXC8_FLAGS),))
$(eval $(call FXCHAN_OBJ,c8,fx_cdrv-pp,$(FXCSRC)/fx_cdrv.s,$$(FXC8_FLAGS),-D FCD_PLAY -D FCD_POS))
$(eval $(call FXCHAN_OBJ,c8,fx_cdrv-p,$(FXCSRC)/fx_cdrv.s,$$(FXC8_FLAGS),-D FCD_POS))
$(eval $(call FXCHAN_OBJ,c8,fx_cdrv-y,$(FXCSRC)/fx_cdrv.s,$$(FXC8_FLAGS),-D FCD_PLAY))
$(eval $(call FXCHAN_OBJ,c8,fx-card,$(FXSRC)/fx.s,$$(FXC8_FLAGS) -I $$(SOUND65),))
$(eval $(call FXCHAN_OBJ,c3,fx_chan,$(FXCSRC)/fx_chan.s,$$(FXC_FLAGS),-D FXC_TRACE))
$(eval $(call FXCHAN_OBJ,rel,fx_chan,$(FXCSRC)/fx_chan.s,$$(FXC_FLAGS),))
$(eval $(call FXCHAN_OBJ,c3,fx_cdrv-p,$(FXCSRC)/fx_cdrv.s,$$(FXC_FLAGS),-D FCD_POS))
$(eval $(call FXCHAN_OBJ,c3,fx-card,$(FXSRC)/fx.s,$$(FXC_FLAGS) -I $$(SOUND65),))
$(eval $(call FXCHAN_OBJ,menuw,fx_chan-ns,$(FXCSRC)/fx_chan.s,$$(FXC_FLAGS),-D FXC_NOSEP))
$(eval $(call FXCHAN_OBJ,menuw,fx_pcache,$(FXCSRC)/fx_pcache.s,$$(FXC_FLAGS),-D FXC_MSCR))

# the game's math (not the render subset: pta3, sineapprox)
$(FXCHAN_DIR)/math.o: math.s $(ROOT)/src/native/math.inc
	@mkdir -p $(FXCHAN_DIR)
	$(CA65) $(FXC_FLAGS) -o $@ -l $(@:.o=.lst) $<

# ---- the test machines ----
define FXCHAN_MACHINE
$(FXCHAN_DIR)/$(1).map: $(2) $(FXCHAN_DIR)/math.o $(FXCHAN_DIR)/fxct.cfg
	$$(LD65) -C $(FXCHAN_DIR)/fxct.cfg -o $(FXCHAN_DIR)/$(1) \
	    -Ln $(FXCHAN_DIR)/$(1).lbl -m $$@ $(2) $(FXCHAN_DIR)/math.o
endef

$(eval $(call FXCHAN_MACHINE,fxc8,$(FXCHAN_DIR)/c8/fx_cdrv-pp.o $(FXCHAN_DIR)/c8/fx_chan.o))
$(eval $(call FXCHAN_MACHINE,fxc8r,$(FXCHAN_DIR)/c8/fx_cdrv-p.o $(FXCHAN_DIR)/c8/fx_chan.o $(FXCHAN_DIR)/c8/fx-card.o $(SOUND65)/player.o))
$(eval $(call FXCHAN_MACHINE,fxc3,$(FXCHAN_DIR)/c3/fx_cdrv-p.o $(FXCHAN_DIR)/c3/fx_chan.o $(FXCHAN_DIR)/c3/fx-card.o $(SOUND65)/player.o))
$(eval $(call FXCHAN_MACHINE,fxcm8,$(FXCHAN_DIR)/c8/fx_cdrv-y.o $(FXCHAN_DIR)/c8/fx_chan-ns.o $(FXCHAN_DIR)/c8/fx_pcache.o))

# ---- MENUW's linkage: its room, its size table ----
FXCHAN_MW_OBJS := $(FXCHAN_DIR)/menuw/fx_chan-ns.o \
                  $(FXCHAN_DIR)/menuw/fx_pcache.o \
                  $(FXCHAN_DIR)/c3/fx-card.o $(SOUND65)/player.o \
                  $(FXCHAN_DIR)/s2_drv.o \
                  $(M11_COMMON_OBJS:%=$(FXCHAN_DIR)/%)
$(eval $(call M11_IMAGE,$(FXCHAN_DIR),fxcmw,MENUW,$(FXCHAN_MW_OBJS)))

.PHONY: fxchan_all
fxchan_all: gen $(FXCHAN_DIR)/rel/fx_chan.o $(FXCHAN_DIR)/fxc8.map $(FXCHAN_DIR)/fxc8r.map \
            $(FXCHAN_DIR)/fxc3.map $(FXCHAN_DIR)/fxcm8.map \
            $(FXCHAN_DIR)/fxcmw.map

PARTS += fxchan
