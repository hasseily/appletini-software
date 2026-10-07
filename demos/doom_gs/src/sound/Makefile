# src/sound: the 65C02 music player for the Phasor, assembled with ca65
# (cc65 2.18) into build/sound65/: the objects play.mk links into the
# game (the voice layout native12: 4 AY chips, the card in native mode).
#
#   player.o      the player
#   probe.o       the probe (boot code)
#   tables.inc    the player's tables, from tools/sound/tables65.py
#
#   make            all three
#   make clean

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/sound65

CA65 = ca65
PYTHON = python3

TOOLS := $(ROOT)/tools/sound/tables65.py $(ROOT)/tools/sound/tables.py

.PHONY: all clean

all: $(OUT)/player.o $(OUT)/probe.o $(OUT)/tables.inc

$(OUT)/tables.inc: $(TOOLS)
	@mkdir -p $(OUT)
	$(PYTHON) $(ROOT)/tools/sound/tables65.py $@

$(OUT)/player.o: $(HERE)player.s $(HERE)sound.inc $(OUT)/tables.inc
	$(CA65) --cpu 65C02 -g -I $(HERE) -I $(OUT) -o $@ \
	    -l $(OUT)/player.lst $<

$(OUT)/probe.o: $(HERE)probe.s $(HERE)sound.inc
	@mkdir -p $(OUT)
	$(CA65) --cpu 65C02 -g -I $(HERE) -o $@ -l $(OUT)/probe.lst $<

clean:
	rm -rf $(OUT)
