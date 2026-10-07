PYTHON ?= python3
PHASOR = PYTHONPATH=../song_to_phasor $(PYTHON) -m phasor
FRAMEWORK = $(wildcard ../song_to_phasor/phasor/*.py)

.PHONY: all score streams disk check
all: streams disk
score: score.json cues.json phonemes.json vocal-reference.mid

score.json cues.json phonemes.json vocal-reference.mid &: arrangement.py backing.py percussion.py
	$(PYTHON) arrangement.py

build/ntsc/song.phs: score.json $(FRAMEWORK)
	$(PHASOR) compile score.json --out build/ntsc --clock ntsc --profile physical-ssi263

build/pal/song.phs: score.json $(FRAMEWORK)
	$(PHASOR) compile score.json --out build/pal --clock pal --profile physical-ssi263

streams: build/ntsc/song.phs build/pal/song.phs

disk: score
	$(MAKE) -C player all

check: disk
	$(MAKE) -C player check
