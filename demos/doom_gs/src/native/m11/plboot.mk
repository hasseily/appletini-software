# src/native/m11/plboot.mk: part plboot of milestone 11 (docs/SCREENS.md
# 2.5, 4.5, 6.5, 7.3; docs/m11-parts/plboot.md): DOOM.SYSTEM, the game's
# boot, and the card's code it installs. Read by src/native/m11.mk (make
# -f m11.mk part P=plboot); tools/native/pldisk.py makes DOOM.hdv from
# the link (with milestone 8's card parts, read only) and checks it.
#
#   build/native/m11/plboot/inc/s2.inc   s2layout.py's places of the
#                                        release (s2-release.inc)
#   build/native/m11/plboot/plboot.cfg   the link's map (pldisk.py --cfg,
#                                        from s2layout.py's places)
#   build/native/m11/plboot/plboot.*     the link: .boot DOOM.SYSTEM
#                                        ($2000-$2FFF), .snd S2's code and
#                                        tables ($E900), .fxc pl_vbl and
#                                        the effects' card part ($F505),
#                                        .plat the ready loop ($FF00), .vec
#                                        the vectors
#
# Objects: src/native/pl_boot.s (PLBOOT_SRC can name a copy: the planted
# bugs of tests/test_m11_plboot.py); src/native/pl_irq.s, pl_input.s,
# pl_keys.s; src/sound/fx.s's card part; S2's player.o and probe.o from
# build/sound65, read only (S2's src/sound/Makefile makes them; this file
# never rebuilds them).

PLBOOT_DIR := $(M11)/plboot
PLBOOT_INC := $(PLBOOT_DIR)/inc
PLBOOT_SRC ?= $(ROOT)/src/native
SOUND65 ?= $(ROOT)/build/sound65
PLBOOT_TOOL := $(ROOT)/tools/native/pldisk.py
PLBOOT_ASFLAGS = --cpu 65C02 -g -I $(PLBOOT_INC) -I $(ROOT)/src/native \
                 -I $(SOUND65)
PLBOOT_INCS := $(PLBOOT_INC)/s2.inc

# S2's objects, read only (the guarded rules of fxplay.mk and fxchan.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

$(PLBOOT_INC)/s2.inc: $(GEN)/s2-release.inc
	@mkdir -p $(PLBOOT_INC)
	cp $< $@

$(PLBOOT_DIR)/plboot.cfg: $(PLBOOT_TOOL) $(LAYOUTS)
	@mkdir -p $(PLBOOT_DIR)
	$(PYTHON) $(PLBOOT_TOOL) --cfg $@

$(PLBOOT_DIR)/pl_boot.o: $(PLBOOT_SRC)/pl_boot.s $(PLBOOT_INCS)
	$(CA65) $(PLBOOT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(PLBOOT_DIR)/pl_irq.o: $(ROOT)/src/native/pl_irq.s $(PLBOOT_INCS)
	$(CA65) $(PLBOOT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(PLBOOT_DIR)/pl_input.o: $(ROOT)/src/native/pl_input.s \
                          $(ROOT)/src/native/pl_input.inc $(PLBOOT_INCS)
	$(CA65) $(PLBOOT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(PLBOOT_DIR)/pl_keys.o: $(ROOT)/src/native/pl_keys.s \
                         $(ROOT)/src/native/pl_input.inc $(PLBOOT_INCS)
	$(CA65) $(PLBOOT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(PLBOOT_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(PLBOOT_INCS) \
                         $(SOUND65)/tables.inc
	$(CA65) $(PLBOOT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

# (FXCODE: fx.s's card part first, then pl_irq.s, the order of the frame
# images that resolve fx_copy, fxc_ld, fxc_st, fx_volume and pl_time by
# linking the same objects: MENUW, WIW, FINW, and SOUNDS.SYSTEM; request
# PLBOOT-4)
PLBOOT_OBJS := $(PLBOOT_DIR)/pl_boot.o $(PLBOOT_DIR)/fx-card.o \
               $(PLBOOT_DIR)/pl_irq.o \
               $(PLBOOT_DIR)/pl_input.o $(PLBOOT_DIR)/pl_keys.o \
               $(SOUND65)/player.o $(SOUND65)/probe.o

$(PLBOOT_DIR)/plboot.map: $(PLBOOT_OBJS) $(PLBOOT_DIR)/plboot.cfg \
                          $(HERE)m11/plboot.mk
	$(LD65) -C $(PLBOOT_DIR)/plboot.cfg -o $(PLBOOT_DIR)/plboot \
	    -Ln $(PLBOOT_DIR)/plboot.lbl -m $@ $(PLBOOT_OBJS)

.PHONY: plboot_all
plboot_all: $(PLBOOT_DIR)/plboot.map

PARTS += plboot
# make -f m11.mk (all, images) links DOOM.SYSTEM too (wave 8's integration)
IMAGES += $(PLBOOT_DIR)/plboot.map
