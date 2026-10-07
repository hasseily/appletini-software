CA65 ?= ca65
LD65 ?= ld65
PYTHON ?= python3
BUILD := build

.PHONY: all check clean
all: $(BUILD)/phasor.bin

$(BUILD)/phasor.o: phasor.s phasor.inc
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -o $@ -l $(BUILD)/phasor.lst phasor.s

$(BUILD)/memory_reader.o: memory_reader.s
	@mkdir -p $(BUILD)
	$(CA65) --cpu 65C02 -g -o $@ memory_reader.s

$(BUILD)/phasor.bin: $(BUILD)/phasor.o $(BUILD)/memory_reader.o player.cfg
	$(LD65) -C player.cfg -o $@ -Ln $(BUILD)/phasor.lbl -m $(BUILD)/phasor.map $(filter %.o,$^)

check: all
	PYTHON="$(PYTHON)" sh check.sh

clean:
	rm -rf $(BUILD)
