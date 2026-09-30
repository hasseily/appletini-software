# src/sound: the 65C02 music player for the Phasor, assembled with ca65 and
# linked with ld65 (cc65 2.18) into build/sound65/LAYOUT/, one build for
# each voice layout (native12, mb6):
#
#   sound.lc      the player: code, tables and vectors, $E000-$FFFF of the
#                 main language card
#   sound.main    the test driver and the probe (probe.s, boot code),
#                 main memory at $0800
#   sound.lbl     every symbol (VICE labels, ld65 -Ln); sound.map, *.lst
#   tables.inc    the player's tables, from tools/sound/tables65.py
#
#   make            both layouts
#   make sizes      code and data of each against native-sound.md 4.3
#   make clean
#
# The comparison with tools/sound/player.py and the cost report are
# tools/sound/run65.py (README.md).

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/sound65

CA65 = ca65
LD65 = ld65
PYTHON = python3

LAYOUTS := native12 mb6
TOOLS := $(ROOT)/tools/sound/tables65.py $(ROOT)/tools/sound/tables.py
SOURCES := player irq driver probe

.PHONY: all sizes clean
.SECONDARY:

all: $(foreach l,$(LAYOUTS),$(OUT)/$(l)/sound.lc)

$(OUT)/%/tables.inc: $(TOOLS)
	@mkdir -p $(dir $@)
	$(PYTHON) $(ROOT)/tools/sound/tables65.py $* $@

$(OUT)/%/player.o: $(HERE)player.s $(HERE)sound.inc $(OUT)/%/tables.inc
	$(CA65) --cpu 65C02 -g -I $(HERE) -I $(OUT)/$* -o $@ \
	    -l $(OUT)/$*/player.lst $<

$(OUT)/%/irq.o: $(HERE)irq.s $(HERE)sound.inc $(OUT)/%/tables.inc
	$(CA65) --cpu 65C02 -g -I $(HERE) -o $@ -l $(OUT)/$*/irq.lst $<

$(OUT)/%/driver.o: $(HERE)driver.s $(HERE)sound.inc $(OUT)/%/tables.inc
	$(CA65) --cpu 65C02 -g -I $(HERE) -I $(OUT)/$* -o $@ \
	    -l $(OUT)/$*/driver.lst $<

$(OUT)/%/probe.o: $(HERE)probe.s $(HERE)sound.inc
	@mkdir -p $(dir $@)
	$(CA65) --cpu 65C02 -g -I $(HERE) -o $@ -l $(OUT)/$*/probe.lst $<

$(OUT)/%/sound.lc: $(foreach s,$(SOURCES),$(OUT)/%/$(s).o) $(HERE)sound.cfg
	$(LD65) -C $(HERE)sound.cfg -o $(OUT)/$*/sound -Ln $(OUT)/$*/sound.lbl \
	    -m $(OUT)/$*/sound.map $(foreach s,$(SOURCES),$(OUT)/$*/$(s).o)

sizes: all
	$(PYTHON) $(ROOT)/tools/sound/run65.py --sizes

clean:
	rm -rf $(OUT)
