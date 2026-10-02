# src/native/m11/fxdisk.mk: part fxdisk of milestone 11 (docs/SCREENS.md
# 3, 7.3; tools/sound/README.md "Effects (S4)", "The test disk
# SOUNDS.hdv"; docs/m11-parts/fxdisk.md): SOUNDS.SYSTEM, the program of
# the effects' test disk. Read by src/native/m11.mk (make -f m11.mk part
# P=fxdisk); tools/sound/fxdisk.py makes the disk build/sound/SOUNDS.hdv
# from it.
#
#   build/native/m11/fxdisk/inc/s2.inc        s2layout.py's places of the
#                                             release (s2-release.inc)
#   build/native/m11/fxdisk/inc/sfxnames.inc  the 52 effects' names
#                                             (fxdisk.py --inc, from
#                                             fxconv.py's NAMES)
#   build/native/m11/fxdisk/sounds.*          SOUNDS.SYSTEM linked by
#                                             src/sound/sounds.cfg:
#                                             sounds.main ($2000-$3FFF)
#                                             and sounds.lc ($E900-$FFFF)
#
# Objects: src/sound/sounds.s; src/sound/fx.s twice (its card part, and
# fx_service with -D FX_SERVICE); src/native/pl_irq.s (pl_vbl, the
# clock); S2's player.o and probe.o from build/sound65, read only (S2's
# src/sound/Makefile makes them; this file never rebuilds them).
# FXDISK_SRC can name a copy of src/sound's sounds.s and sounds.cfg (the
# planted bugs of tests/test_m11_fxdisk.py).

FXDISK_DIR := $(M11)/fxdisk
FXDISK_INC := $(FXDISK_DIR)/inc
SOUND65 ?= $(ROOT)/build/sound65
FXDISK_SRC ?= $(ROOT)/src/sound
FXDISK_TOOL := $(ROOT)/tools/sound/fxdisk.py
FXDISK_ASFLAGS = --cpu 65C02 -g -I $(FXDISK_INC) -I $(SOUND65)
FXDISK_INCS := $(FXDISK_INC)/s2.inc

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

$(FXDISK_INC)/s2.inc: $(GEN)/s2-release.inc
	@mkdir -p $(FXDISK_INC)
	cp $< $@

$(FXDISK_INC)/sfxnames.inc: $(FXDISK_TOOL) $(ROOT)/tools/sound/fxconv.py
	@mkdir -p $(FXDISK_INC)
	$(PYTHON) $(FXDISK_TOOL) --inc $@

$(FXDISK_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(FXDISK_INCS) \
                         $(SOUND65)/tables.inc
	$(CA65) $(FXDISK_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(FXDISK_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(FXDISK_INCS) \
                    $(SOUND65)/tables.inc
	$(CA65) $(FXDISK_ASFLAGS) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<

$(FXDISK_DIR)/pl_irq.o: $(ROOT)/src/native/pl_irq.s $(FXDISK_INCS)
	$(CA65) $(FXDISK_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(FXDISK_DIR)/sounds.o: $(FXDISK_SRC)/sounds.s $(FXDISK_INCS) \
                        $(FXDISK_INC)/sfxnames.inc
	$(CA65) $(FXDISK_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

FXDISK_OBJS := $(FXDISK_DIR)/sounds.o $(FXDISK_DIR)/fx-card.o \
               $(FXDISK_DIR)/fx.o $(FXDISK_DIR)/pl_irq.o \
               $(SOUND65)/player.o $(SOUND65)/probe.o

$(FXDISK_DIR)/sounds.map: $(FXDISK_OBJS) $(FXDISK_SRC)/sounds.cfg
	$(LD65) -C $(FXDISK_SRC)/sounds.cfg -o $(FXDISK_DIR)/sounds \
	    -Ln $(FXDISK_DIR)/sounds.lbl -m $@ $(FXDISK_OBJS)

.PHONY: fxdisk_all
fxdisk_all: $(FXDISK_DIR)/sounds.map

PARTS += fxdisk
# `make -f m11.mk` (all) builds SOUNDS.SYSTEM too (request FXDISK-2,
# applied in wave 7; `all` already needs S2's objects for the images)
M11_HOST += fxdisk_all
