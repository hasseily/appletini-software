PYTHON ?= python3
FFMPEG ?= ffmpeg
APPLETINI_ROOT ?= ../../../appletini-one
CACHE ?= ../song_to_phasor/.cache
PHASOR = PYTHONPATH=../song_to_phasor $(PYTHON) -m phasor
FRAMEWORK = $(wildcard ../song_to_phasor/phasor/*.py)

.PHONY: all score streams render preview disk check
all: streams disk
score: score.json cues.json phonemes.json vocal-reference.mid

score.json cues.json phonemes.json vocal-reference.mid &: arrangement.py backing.py percussion.py
	$(PYTHON) arrangement.py

build/ntsc/song.phs: score.json $(FRAMEWORK)
	$(PHASOR) compile score.json --out build/ntsc --clock ntsc --firmware-root $(APPLETINI_ROOT)

build/pal/song.phs: score.json $(FRAMEWORK)
	$(PHASOR) compile score.json --out build/pal --clock pal --firmware-root $(APPLETINI_ROOT)

streams: build/ntsc/song.phs build/pal/song.phs

build/house-of-the-rising-sun.wav: build/ntsc/song.phs
	$(PHASOR) render $< $@ --full --clock ntsc --firmware-root $(APPLETINI_ROOT) --cache $(CACHE) --vocal-output build/vocals.wav --backing-output build/backing.wav

render: build/house-of-the-rising-sun.wav

build/house-of-the-rising-sun.mp3: build/house-of-the-rising-sun.wav
	$(FFMPEG) -v error -nostdin -y -i $< -codec:a libmp3lame -q:a 2 -metadata title="House of the Rising Sun - Phasor No. 1 (Blues-rock revision)" -metadata artist="Appletini Phasor / SSI-263" $@

preview: build/house-of-the-rising-sun.mp3

disk: score
	$(MAKE) -C player all

check: render disk
	$(PYTHON) verify_render.py score.json build/vocals.wav --mix build/house-of-the-rising-sun.wav --output build/audio-validation.json
	$(MAKE) -C player check
