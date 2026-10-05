CA65 ?= ca65
LD65 ?= ld65
PYTHON ?= python3
BUILD := build
FRAMEWORK := ../../song_to_phasor/player
COMPILER_SOURCES := $(wildcard ../../song_to_phasor/phasor/*.py)
DOOM := ../../doom
SCORE ?= ../score.json

.PHONY: all check clean
all: $(BUILD)/RISING.SUN.hdv

$(BUILD)/demo.o: demo.s
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -o $@ -l $(BUILD)/demo.lst $<

$(BUILD)/phasor.o: $(FRAMEWORK)/phasor.s $(FRAMEWORK)/phasor.inc
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -I $(FRAMEWORK) -o $@ $<

$(BUILD)/memory_reader.o: $(FRAMEWORK)/memory_reader.s
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -o $@ $<

$(BUILD)/SUN.SYSTEM: $(BUILD)/demo.o $(BUILD)/phasor.o $(BUILD)/memory_reader.o player.cfg
	$(LD65) -C player.cfg -o $@ -Ln $(BUILD)/sun.lbl -m $(BUILD)/sun.map $(filter %.o,$^)

$(BUILD)/SUN.NTSC $(BUILD)/SUN.PAL &: $(SCORE) prepare.py $(COMPILER_SOURCES)
	PYTHONPATH=../../song_to_phasor $(PYTHON) prepare.py $(SCORE) $(BUILD)

$(BUILD)/RISING.SUN.hdv: $(BUILD)/SUN.SYSTEM $(BUILD)/SUN.NTSC $(BUILD)/SUN.PAL $(DOOM)/tools/mkdisk.py $(DOOM)/assets/ProDOS_2_4_3.po
	$(PYTHON) $(DOOM)/tools/mkdisk.py -o $@ -v RISING.SUN -m $(DOOM)/assets/ProDOS_2_4_3.po $(BUILD)/SUN.SYSTEM,SYS,2000 $(BUILD)/SUN.NTSC,BIN,3000 $(BUILD)/SUN.PAL,BIN,3000

check: all
	$(PYTHON) check.py

clean:
	rm -rf $(BUILD)
