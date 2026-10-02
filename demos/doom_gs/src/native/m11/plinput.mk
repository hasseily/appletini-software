# src/native/m11/plinput.mk: part plinput of milestone 11 (docs/SCREENS.md
# 2.4, 6.5, 7.3; docs/m11-parts/plinput.md): the //e's input, the shared
# object pl_poll (src/native/pl_input.s), the key table's routines for the
# boot and the menus (pl_keys.s), their test image and the //e key table
# for the menus. Read by src/native/m11.mk (make -f m11.mk part
# P=plinput).
#
#   build/native/m11/plinput/plit.*         the input's test image in MENUW's
#                                           room (the image that links both
#                                           pl_poll and pl_keys; P2DW's until
#                                           wave 5's integration gave pl_keys
#                                           its row, PLINPUT-5) under the test
#                                           driver s2_drv
#                                           with pl_vbl its handler (-D
#                                           PL_VBL), S2's player in the card,
#                                           part fxplay's effect player
#                                           (fx.s's card part; pl_it.s:
#                                           plt_run)
#   build/native/m11/plinput/gen/plkeys.inc the //e key table and names
#                                           (tools/native/plkeys.py) for the
#                                           menus (part s2menu2)
#
# S2's player.o comes from build/sound65 (make -C src/sound), read only;
# this file never rebuilds it.

PLINPUT_DIR := $(M11)/plinput
SOUND65 ?= $(ROOT)/build/sound65

$(eval $(call M11_COMMON,$(PLINPUT_DIR)))

# S2's objects, read only (the same guarded rules in fxplay.mk and
# fxchan.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

# the card's interrupt code as the release links it (fx.s's card part
# first, then pl_irq.s: request PLBOOT-4)
$(PLINPUT_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                          $(SOUND65)/tables.inc
	@mkdir -p $(PLINPUT_DIR)
	$(CA65) $(ASFLAGS) -I $(SOUND65) -o $@ -l $(@:.o=.lst) $<

PLINPUT_OBJS := $(PLINPUT_DIR)/pl_it.o $(PLINPUT_DIR)/pl_input.o \
                $(PLINPUT_DIR)/pl_keys.o \
                $(PLINPUT_DIR)/s2_drv-pl.o $(PLINPUT_DIR)/fx-card.o \
                $(PLINPUT_DIR)/pl_irq.o $(SOUND65)/player.o \
                $(M11_COMMON_OBJS:%=$(PLINPUT_DIR)/%)
$(eval $(call M11_IMAGE,$(PLINPUT_DIR),plit,MENUW,$(PLINPUT_OBJS)))
$(PLINPUT_DIR)/pl_input.o $(PLINPUT_DIR)/pl_keys.o: pl_input.inc

$(PLINPUT_DIR)/gen/plkeys.inc: $(TOOLS)/plkeys.py
	$(PYTHON) $(TOOLS)/plkeys.py --inc $@

.PHONY: plinput_all
plinput_all: gen $(PLINPUT_DIR)/plit.map $(PLINPUT_DIR)/gen/plkeys.inc

PARTS += plinput
