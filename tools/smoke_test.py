#!/usr/bin/env python3
"""Boot and exercise Appletini Invasion in a fresh GSSquared instance."""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[3]
GAME_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = GAME_DIR / "appletini-invasion.gs2"
DEFAULT_EMULATOR = ROOT / "build/GSSquared.app/Contents/MacOS/GSSquared"
CLIENT_SRC = ROOT / "clients/python/src"
TOOLS_DIR = GAME_DIR / "tools"
SDL_SCANCODE_SPACE = 44
SDL_SCANCODE_RIGHT = 79
SDL_SCANCODE_LEFT = 80
MAILBOX_ADDRESS = 0x0300
MAILBOX_SIZE = 41
PARALLAX_PATH = GAME_DIR / "build/PARALLAX"
SHIP_PATH = GAME_DIR / "build/SHIP"
PARALLAX_LAYER_COUNT = 3
PARALLAX_SOURCE_ROWS = 384
PARALLAX_ROW_BYTES = 80
PARALLAX_PROGRAM_BANK_COUNT = 5
PARALLAX_BANK_COUNT = 6
PARALLAX_BANK_SIZE = 32 * 1024
PARALLAX_BANK_LOAD = 0x2000
PARALLAX_DIRECTORY_OFFSET = 16
PARALLAX_BANK_IMAGES_OFFSET = 4096
PARALLAX_PHASE_MODULUS = 384 * 20
PARALLAX_SPEEDS = (5, 12, 28)
REPLAY_FIRST_BANK = 7
MB_DEEP_PHASE = 20
MB_NEBULA_PHASE = 22
MB_ASTEROID_PHASE = 24
MB_MUSIC_STEP = 26
MB_MUSIC_LOOPS = 27
MB_MUSIC_TICK = 28
MB_AY_MIXER = 29
MB_EFFECT_KIND = 30
MB_LEAD_NOTE = 31
MB_BASS_NOTE = 32
MB_MUSIC_EVENTS = 33
MB_PARALLAX_COMMITS = 34
MB_SHIP_FRAME = 35
MB_ENEMY_BULLET_ACTIVE = 36
MB_ENEMY_BULLET_SOURCE = 37
MB_ENEMY_ALIVE = 38
SHIP_WOVEN_TOP = 288
SHIP_FRAME_COUNT = 8
SHIP_PHASE_COUNT = 4
SHIP_VARIANT_SIZE = 1024
# Player shots stop above row 24 and invaders start below it, so these rows
# remain a deterministic background-only oracle throughout gameplay.
BACKGROUND_TEST_ROWS = range(20, 23)

ParallaxRow = tuple[bytes, bytes]
ParallaxLayer = tuple[ParallaxRow, ...]
ParallaxLayers = tuple[ParallaxLayer, ...]
ShipVariants = tuple[tuple[bytes, ...], ...]

sys.path.insert(0, str(CLIENT_SRC))
sys.path.insert(0, str(TOOLS_DIR))

from gs2debug import (  # noqa: E402
    Client,
    MEM_MAIN_RAW,
    PLATFORM_APPLE_IIE_ENHANCED,
    ProtocolError,
)
from convert_parallax import (  # noqa: E402
    AssetError as ParallaxAssetError,
    LAYERS as PARALLAX_SOURCE_FILES,
    pack_row as pack_parallax_row,
    read_rgba_png,
)
from convert_ship import (  # noqa: E402
    FRAMES as SHIP_SOURCE_FILES,
    HEIGHT as SHIP_HEIGHT,
    WIDTH as SHIP_WIDTH,
    pack_variant as pack_ship_variant,
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def frame_number(mailbox: bytes) -> int:
    return mailbox[6] | (mailbox[7] << 8)


def cpu_cycle(client: Client) -> int:
    return int.from_bytes(client.get_regs()[:8], "little")


def mailbox_word(mailbox: bytes, offset: int) -> int:
    return mailbox[offset] | (mailbox[offset + 1] << 8)


def prodos_root_files(image: bytes) -> dict[str, tuple[int, int]]:
    """Return root file name -> (type, aux type) from a ProDOS block image."""
    files: dict[str, tuple[int, int]] = {}
    block = 2
    first = True
    visited: set[int] = set()
    while block:
        if block in visited or (block + 1) * 512 > len(image):
            fail(f"invalid ProDOS root-directory block chain at block {block}")
        visited.add(block)
        directory = image[block * 512:(block + 1) * 512]
        next_block = int.from_bytes(directory[2:4], "little")
        first_entry = 1 if first else 0
        for entry_index in range(first_entry, 13):
            offset = 4 + entry_index * 39
            storage_and_length = directory[offset]
            name_length = storage_and_length & 0x0F
            if not name_length:
                continue
            name = directory[offset + 1:offset + 1 + name_length].decode("ascii")
            files[name] = (
                directory[offset + 16],
                int.from_bytes(directory[offset + 31:offset + 33], "little"),
            )
        block = next_block
        first = False
    return files


def parallax_phases(mailbox: bytes) -> tuple[int, int, int]:
    return (
        mailbox_word(mailbox, MB_DEEP_PHASE),
        mailbox_word(mailbox, MB_NEBULA_PHASE),
        mailbox_word(mailbox, MB_ASTEROID_PHASE),
    )


def hgr_address(y: int, page: int = 0x2000) -> int:
    return page + ((y & 7) << 10) + ((y & 0x38) << 4) + ((y >> 6) * 0x28)


def wait_for(predicate: Callable[[], object], timeout: float, description: str) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.02)
    fail(f"timed out waiting for {description}; last value was {last!r}")


def connect_debug(client: Client, socket_path: Path, process: subprocess.Popen[bytes],
                  timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(f"GSSquared exited before opening its debug socket (status {process.returncode})")
        try:
            client.connect(str(socket_path))
            client.hello()
            return
        except OSError as exc:
            last_error = exc
            client.close()
            time.sleep(0.05)
    fail(f"could not connect to {socket_path}: {last_error}")


def read_mailbox(client: Client) -> bytes:
    return client.read_mem(MEM_MAIN_RAW, MAILBOX_ADDRESS, MAILBOX_SIZE)


def matching_mailbox(client: Client, predicate: Callable[[bytes], bool]) -> bytes | None:
    mailbox = read_mailbox(client)
    return mailbox if predicate(mailbox) else None


def matching_memory(client: Client, address: int, wanted: bytes) -> bytes | None:
    value = client.read_mem(MEM_MAIN_RAW, address, len(wanted))
    return value if value == wanted else None


def capture_committed_dhgri(client: Client) -> tuple[bytes, dict[str, bytes]]:
    wanted_marker = bytes((0xC1, 0xB2, 0xCC, 0xE9, 0x01))
    for _ in range(30):
        captured: tuple[bytes, dict[str, bytes]] | None = None
        client.pause()
        try:
            if client.read_mem(MEM_MAIN_RAW, 0x4078, 5) == wanted_marker:
                mailbox = read_mailbox(client)
                planes = {
                    "main page 1": client.read_mem(MEM_MAIN_RAW, 0x02000, 0x2000),
                    "aux page 1": client.read_mem(MEM_MAIN_RAW, 0x12000, 0x2000),
                    "main page 2": client.read_mem(MEM_MAIN_RAW, 0x04000, 0x2000),
                    "aux page 2": client.read_mem(MEM_MAIN_RAW, 0x14000, 0x2000),
                }
                if client.read_mem(MEM_MAIN_RAW, 0x4078, 5) == wanted_marker:
                    captured = mailbox, planes
        finally:
            client.continue_()
        if captured is not None:
            return captured
        time.sleep(0.02)
    fail("could not pause on a committed A2Li DHGRi frame")


def load_ship(path: Path) -> tuple[ShipVariants, bytes, str]:
    payload = path.read_bytes()
    expected_size = (
        SHIP_FRAME_COUNT * SHIP_PHASE_COUNT * SHIP_VARIANT_SIZE
    )
    if len(payload) != expected_size:
        fail(f"SHIP is {len(payload)} bytes; expected {expected_size}")

    variants: list[tuple[bytes, ...]] = []
    expected = bytearray()
    try:
        for filename in SHIP_SOURCE_FILES:
            source_path = GAME_DIR / "assets" / filename
            rows = read_rgba_png(source_path, SHIP_WIDTH, SHIP_HEIGHT)
            frame_variants = tuple(
                pack_ship_variant(source_path, rows, phase)
                for phase in range(SHIP_PHASE_COUNT)
            )
            variants.append(frame_variants)
            expected.extend(b"".join(frame_variants))
    except ParallaxAssetError as error:
        fail(f"invalid canonical ship source: {error}")
    if payload != expected:
        fail("SHIP does not exactly encode the eight canonical RGBA frames")
    return tuple(variants), payload, hashlib.sha256(payload).hexdigest()


def load_parallax(path: Path, ship_bank: bytes) -> tuple[ParallaxLayers, str]:
    payload = path.read_bytes()
    expected_size = (
        PARALLAX_BANK_IMAGES_OFFSET
        + PARALLAX_BANK_COUNT * PARALLAX_BANK_SIZE
    )
    if len(payload) != expected_size:
        fail(
            f"PARALLAX has invalid compiled-asset size {len(payload)}; "
            f"expected {expected_size}"
        )
    header = struct.unpack_from("<4sBBBBHHHH", payload)
    expected_header = (
        b"A13C", 1, PARALLAX_LAYER_COUNT, PARALLAX_ROW_BYTES,
        PARALLAX_BANK_COUNT, 560, PARALLAX_SOURCE_ROWS,
        PARALLAX_DIRECTORY_OFFSET, PARALLAX_BANK_IMAGES_OFFSET,
    )
    if header != expected_header:
        fail(f"PARALLAX header is {header!r}, expected {expected_header!r}")

    entry_count = PARALLAX_LAYER_COUNT * PARALLAX_SOURCE_ROWS
    directory_end = PARALLAX_DIRECTORY_OFFSET + entry_count * 3
    if any(payload[directory_end:PARALLAX_BANK_IMAGES_OFFSET]):
        fail("PARALLAX directory padding is not zero")

    locations = tuple(
        struct.unpack_from("<BH", payload, PARALLAX_DIRECTORY_OFFSET + index * 3)
        for index in range(entry_count)
    )
    previous_bank = 0
    previous_end = 0
    allowed_two_byte = {0xA9, 0x85, 0x14, 0x04, 0xA5, 0x29, 0x09}
    zp_operands = {0x85, 0x14, 0x04, 0xA5}
    for index, (bank, address) in enumerate(locations):
        if not 1 <= bank <= PARALLAX_PROGRAM_BANK_COUNT \
                or not PARALLAX_BANK_LOAD <= address < 0xA000:
            fail(
                f"PARALLAX routine {index} has invalid bank/address "
                f"{bank}:${address:04X}"
            )
        if bank == previous_bank:
            if address != previous_end:
                fail(
                    f"PARALLAX routine {index} starts at ${address:04X}; "
                    f"previous routine ended at ${previous_end:04X}"
                )
        else:
            if bank != previous_bank + 1 or address != PARALLAX_BANK_LOAD:
                fail(
                    f"PARALLAX routine {index} starts a noncontiguous bank "
                    f"{bank}:${address:04X}"
                )
            previous_bank = bank

        position = (
            PARALLAX_BANK_IMAGES_OFFSET
            + (bank - 1) * PARALLAX_BANK_SIZE
            + address - PARALLAX_BANK_LOAD
        )
        bank_end = PARALLAX_BANK_IMAGES_OFFSET + bank * PARALLAX_BANK_SIZE
        while position < bank_end:
            opcode = payload[position]
            position += 1
            if opcode == 0x60:
                break
            if opcode not in allowed_two_byte or position >= bank_end:
                fail(
                    f"PARALLAX routine {index} contains invalid opcode "
                    f"${opcode:02X}"
                )
            operand = payload[position]
            position += 1
            if opcode in zp_operands and not 0xA0 <= operand <= 0xEF:
                fail(
                    f"PARALLAX routine {index} accesses invalid zero page "
                    f"${operand:02X}"
                )
        else:
            fail(f"PARALLAX routine {index} crosses its bank boundary")
        previous_end = PARALLAX_BANK_LOAD + (
            position
            - PARALLAX_BANK_IMAGES_OFFSET
            - (bank - 1) * PARALLAX_BANK_SIZE
        )
    if previous_bank != PARALLAX_PROGRAM_BANK_COUNT:
        fail(
            f"PARALLAX uses {previous_bank} routine banks, "
            f"expected {PARALLAX_PROGRAM_BANK_COUNT}"
        )

    ship_offset = (
        PARALLAX_BANK_IMAGES_OFFSET
        + PARALLAX_PROGRAM_BANK_COUNT * PARALLAX_BANK_SIZE
    )
    if payload[ship_offset:ship_offset + PARALLAX_BANK_SIZE] != ship_bank:
        fail("PARALLAX bank 6 does not match the exact compiled SHIP bank")

    layers: list[ParallaxLayer] = []
    try:
        for layer_index, filename in enumerate(PARALLAX_SOURCE_FILES):
            source_path = GAME_DIR / "assets" / filename
            rows = tuple(
                pack_parallax_row(
                    source_path, row_number, rgba, layer_index == 0
                )
                for row_number, rgba in enumerate(read_rgba_png(source_path))
            )
            layers.append(rows)
    except ParallaxAssetError as error:
        fail(f"invalid canonical parallax source: {error}")

    digest = hashlib.sha256(payload).hexdigest()
    return tuple(layers), digest


def compose_parallax_row(layers: ParallaxLayers, phases: tuple[int, ...],
                          woven_y: int) -> bytes:
    composed = bytearray(PARALLAX_ROW_BYTES)
    for layer_index, (layer, phase) in enumerate(zip(layers, phases)):
        source_row = (woven_y - phase // 20) % PARALLAX_SOURCE_ROWS
        data, opacity = layer[source_row]
        if layer_index == 0:
            composed[:] = data
        else:
            for byte_index in range(PARALLAX_ROW_BYTES):
                composed[byte_index] = (
                    (composed[byte_index] & (opacity[byte_index] ^ 0x7F))
                    | data[byte_index]
                )
    return bytes(composed)


def captured_parallax_row(planes: dict[str, bytes], native_y: int,
                           field: int) -> bytes:
    page_number = field + 1
    page = 0x2000 if field == 0 else 0x4000
    offset = hgr_address(native_y, page) - page
    aux = planes[f"aux page {page_number}"]
    main = planes[f"main page {page_number}"]
    return bytes(
        value & 0x7F
        for x in range(40)
        for value in (aux[offset + x], main[offset + x])
    )


def assert_parallax_background(planes: dict[str, bytes], phases: tuple[int, ...],
                               layers: ParallaxLayers) -> None:
    if any(phase >= PARALLAX_PHASE_MODULUS for phase in phases):
        fail(f"parallax phase outside 1/20-pixel range: {phases}")
    for native_y in BACKGROUND_TEST_ROWS:
        for field in (0, 1):
            woven_y = native_y * 2 + field
            expected = compose_parallax_row(layers, phases, woven_y)
            actual = captured_parallax_row(planes, native_y, field)
            if actual != expected:
                difference = next(
                    index for index, pair in enumerate(zip(actual, expected))
                    if pair[0] != pair[1]
                )
                source_rows = tuple(
                    (woven_y - phase // 20) % PARALLAX_SOURCE_ROWS
                    for phase in phases
                )
                fail(
                    f"parallax mismatch at woven row {woven_y}, byte {difference}: "
                    f"actual=${actual[difference]:02X} "
                    f"expected=${expected[difference]:02X} "
                    f"source_rows={source_rows} phases={phases}"
                )


def assert_player_ship(planes: dict[str, bytes], mailbox: bytes,
                       layers: ParallaxLayers,
                       variants: ShipVariants) -> None:
    group_x = mailbox[11]
    frame = mailbox[MB_SHIP_FRAME]
    phases = parallax_phases(mailbox)
    if group_x > 72 or frame >= SHIP_FRAME_COUNT:
        fail(f"invalid published ship position/frame: x={group_x} frame={frame}")
    variant = variants[frame][group_x & 3]

    for source_y in range(SHIP_HEIGHT):
        woven_y = SHIP_WOVEN_TOP + source_y
        native_y = woven_y >> 1
        field = woven_y & 1
        background = bytearray(compose_parallax_row(layers, phases, woven_y))
        row_offset = source_y * 16
        for local_group in range(8):
            keep = variant[row_offset + local_group * 2]
            data = variant[row_offset + local_group * 2 + 1]
            destination_group = group_x + local_group
            background[destination_group] = (
                (background[destination_group] & keep) | data
            )
        actual = captured_parallax_row(planes, native_y, field)
        expected_span = bytes(background[group_x:group_x + 8])
        actual_span = actual[group_x:group_x + 8]
        if actual_span != expected_span:
            difference = next(
                index for index, pair in enumerate(zip(actual_span, expected_span))
                if pair[0] != pair[1]
            )
            fail(
                f"ship frame {frame} mismatch at source row {source_y}, "
                f"group {difference}: actual=${actual_span[difference]:02X} "
                f"expected=${expected_span[difference]:02X}"
            )


def exercise(client: Client, timeout: float,
             layers: ParallaxLayers,
             ship_variants: ShipVariants) -> dict[str, object]:
    status = client.get_status()
    if status.platform_id != PLATFORM_APPLE_IIE_ENHANCED:
        fail(f"wrong platform {status.platform_id}; expected enhanced Apple //e")

    mailbox = wait_for(
        lambda: matching_mailbox(client, lambda m: m[:4] == b"A13I"),
        timeout,
        "the A13I mailbox after SmartPort boot",
    )
    assert isinstance(mailbox, bytes)

    expected = {
        "video mode": (mailbox[4], 1),
        "RamWorks banks": (mailbox[5], 128),
        "reported speed": (mailbox[12], 33),
        "audio feature flags": (mailbox[13], 7),
        "game state": (mailbox[15], 1),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            fail(f"{label} is {actual}, expected {wanted}; mailbox={mailbox.hex()}")
    if not REPLAY_FIRST_BANK <= mailbox[17] < 128:
        fail(
            "RamWorks replay entered a parallax/display bank: "
            f"mailbox={mailbox.hex()}"
        )
    shooter_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: m[MB_ENEMY_BULLET_ACTIVE]
                      and m[MB_ENEMY_BULLET_SOURCE] < 24,
        ),
        2.0,
        "an enemy shot from a published live source",
    )
    assert isinstance(shooter_box, bytes)
    shooter = shooter_box[MB_ENEMY_BULLET_SOURCE]
    alive_byte = shooter_box[MB_ENEMY_ALIVE + (shooter >> 3)]
    if not alive_byte & (1 << (shooter & 7)):
        fail(f"enemy shot source {shooter} was not alive at launch")

    # The boot weave is published before the four-VBL render cadence starts.
    # Begin motion sampling with the first scheduled commit so every interval
    # below is an integral number of 15 Hz (four-VBL) publications.
    wait_for(
        lambda: matching_mailbox(client, lambda m: parallax_phases(m)[0] != 0),
        2.0,
        "the first scheduled parallax commit",
    )
    first_visual_box, first_planes = capture_committed_dhgri(client)
    first_phases = parallax_phases(first_visual_box)
    first_publication = first_visual_box[MB_PARALLAX_COMMITS]
    assert_parallax_background(first_planes, first_phases, layers)
    assert_player_ship(first_planes, first_visual_box, layers, ship_variants)

    wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: 8 <= (
                (m[MB_PARALLAX_COMMITS] - first_publication) & 0xFF
            ) < 128,
        ),
        2.0,
        "eight subsequent parallax publications",
    )
    second_visual_box, second_planes = capture_committed_dhgri(client)
    second_phases = parallax_phases(second_visual_box)
    phase_deltas = tuple(
        (new - old) % PARALLAX_PHASE_MODULUS
        for old, new in zip(first_phases, second_phases)
    )
    publication_frames = (
        frame_number(second_visual_box) - frame_number(first_visual_box)
    ) & 0xFFFF
    publication_count = (
        second_visual_box[MB_PARALLAX_COMMITS]
        - first_visual_box[MB_PARALLAX_COMMITS]
    ) & 0xFF
    expected_deltas = tuple(
        (publication_count * 4 * speed) % PARALLAX_PHASE_MODULUS
        for speed in PARALLAX_SPEEDS
    )
    expected_frames = publication_count * 4
    if not publication_count or phase_deltas != expected_deltas \
            or abs(publication_frames - expected_frames) > 2:
        fail(
            "parallax publications did not remain on the four-VBL grid with "
            f"three fractional speeds: commits={publication_count} "
            f"frames={publication_frames} "
            f"deltas={phase_deltas} expected={expected_deltas}"
        )
    assert_parallax_background(second_planes, second_phases, layers)

    speech_values: set[int] = set()
    speech_completions = 0
    music_steps: set[int] = {mailbox[MB_MUSIC_STEP]}
    lead_notes: set[int] = {mailbox[MB_LEAD_NOTE]}
    bass_notes: set[int] = {mailbox[MB_BASS_NOTE]}
    mixer_values: set[int] = {mailbox[MB_AY_MIXER]}
    first_music_loop = mailbox[MB_MUSIC_LOOPS]
    speech_deadline = time.monotonic() + 0.8
    while time.monotonic() < speech_deadline:
        speech_box = read_mailbox(client)
        speech_values.add(speech_box[14])
        speech_completions = max(speech_completions, speech_box[18])
        music_steps.add(speech_box[MB_MUSIC_STEP])
        lead_notes.add(speech_box[MB_LEAD_NOTE])
        bass_notes.add(speech_box[MB_BASS_NOTE])
        mixer_values.add(speech_box[MB_AY_MIXER])
        time.sleep(0.02)
    if not any(value not in (0x00, 0xFF) for value in speech_values):
        fail(f"SSI-263 speech scheduler did not publish a phoneme: {speech_values}")
    if speech_completions == 0:
        fail("SSI-263 did not deliver a VIA CA1 phoneme-completion event")
    if len(music_steps) < 2 or len(lead_notes) < 2:
        fail(
            "continuous AY score did not advance while speech played: "
            f"steps={music_steps} lead={lead_notes} bass={bass_notes}"
        )
    if any(value == 0x3F or value & 0x03 for value in mixer_values):
        fail(f"music channels A/B were disabled during speech: mixers={mixer_values}")

    # Compare paired live CPU-cycle and guest-frame snapshots over a long
    # guest interval. Approximately 556,272 cycles per NTSC frame proves the
    # fixed 33.3 MHz rational clock independently of host load; wall cadence
    # separately catches a renderer that starves the 60 Hz main loop.
    cadence_box_start = read_mailbox(client)
    cadence_cycle_start = cpu_cycle(client)
    cadence_time_start = time.monotonic()
    cadence_box_end = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((frame_number(m) - frame_number(cadence_box_start))
                       & 0xFFFF) >= 120,
        ),
        3.5,
        "120 VBL-driven game frames",
    )
    assert isinstance(cadence_box_end, bytes)
    cadence_cycle_end = cpu_cycle(client)
    cadence_elapsed = time.monotonic() - cadence_time_start
    cadence_frames = (
        frame_number(cadence_box_end) - frame_number(cadence_box_start)
    ) & 0xFFFF
    cadence_cycles_per_frame = (
        (cadence_cycle_end - cadence_cycle_start) / cadence_frames
    )
    cadence_hz = cadence_frames / cadence_elapsed
    if not 550_000 <= cadence_cycles_per_frame <= 562_000:
        fail(
            "Appletini did not run at its fixed 33.3 MHz ratio: "
            f"{cadence_cycles_per_frame:.1f} CPU cycles/VBL"
        )
    if not 52.0 <= cadence_hz <= 68.0:
        fail(
            "VBL main loop did not sustain its 60 Hz cadence: "
            f"{cadence_frames} frames in {cadence_elapsed:.3f}s "
            f"({cadence_hz:.2f} Hz)"
        )

    music_loop_box: bytes | None = None
    music_deadline = time.monotonic() + 8.0
    while time.monotonic() < music_deadline:
        music_box = read_mailbox(client)
        music_steps.add(music_box[MB_MUSIC_STEP])
        lead_notes.add(music_box[MB_LEAD_NOTE])
        bass_notes.add(music_box[MB_BASS_NOTE])
        mixer_values.add(music_box[MB_AY_MIXER])
        if music_box[MB_MUSIC_LOOPS] != first_music_loop \
                and len(music_steps) >= 8 and len(bass_notes) >= 4:
            music_loop_box = music_box
            break
        time.sleep(0.02)
    if music_loop_box is None:
        fail(
            "continuous score did not complete a varied loop: "
            f"steps={music_steps} lead={lead_notes} bass={bass_notes}"
        )
    if any(value == 0x3F or value & 0x03 for value in mixer_values):
        fail(f"music channels A/B were disabled during the loop: mixers={mixer_values}")

    # Make reset observable: perturb player state first, then require R to put
    # it back. The other public values already match a fresh game at boot.
    client.key_down(SDL_SCANCODE_RIGHT)
    try:
        wait_for(
            lambda: matching_mailbox(client, lambda m: m[11] > 36),
            2.0,
            "pre-reset held-arrow movement",
        )
    finally:
        client.key_up(SDL_SCANCODE_RIGHT)
    client.type_text("r", delay_s=0, hold_s=0.04)
    reset_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: m[8] == 0 and m[9] == 3 and m[10] == 24 and m[11] == 36,
        ),
        2.0,
        "game reset",
    )
    assert isinstance(reset_box, bytes)

    start_frame = frame_number(reset_box)
    client.key_down(SDL_SCANCODE_RIGHT)
    try:
        moved_box = wait_for(
            lambda: matching_mailbox(
                client,
                lambda m: m[11] >= 40 and m[MB_SHIP_FRAME] in (4, 5),
            ),
            2.0,
            "held Right-arrow movement",
        )
    finally:
        client.key_up(SDL_SCANCODE_RIGHT)
    assert isinstance(moved_box, bytes)
    release_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((frame_number(m) - frame_number(moved_box)) & 0xFFFF) >= 4,
        ),
        1.0,
        "Right-arrow release",
    )
    assert isinstance(release_box, bytes)
    stopped_x = release_box[11]
    if stopped_x >= 72:
        fail("Right-arrow release test reached the movement boundary")
    stable_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((frame_number(m) - frame_number(release_box)) & 0xFFFF) >= 8,
        ),
        1.0,
        "post-release movement interval",
    )
    assert isinstance(stable_box, bytes)
    if stable_box[11] != stopped_x or stable_box[MB_SHIP_FRAME] not in (0, 1):
        fail(
            "ship did not return to a stationary neutral pose after "
            f"Right-arrow key-up: x {stopped_x}->{stable_box[11]} "
            f"frame={stable_box[MB_SHIP_FRAME]}"
        )

    client.key_down(SDL_SCANCODE_LEFT)
    try:
        left_box = wait_for(
            lambda: matching_mailbox(
                client,
                lambda m: m[11] <= stopped_x - 3
                          and m[MB_SHIP_FRAME] in (2, 3),
            ),
            2.0,
            "held Left-arrow movement",
        )
    finally:
        client.key_up(SDL_SCANCODE_LEFT)
    assert isinstance(left_box, bytes)
    left_release_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((frame_number(m) - frame_number(left_box)) & 0xFFFF) >= 4,
        ),
        1.0,
        "Left-arrow release",
    )
    assert isinstance(left_release_box, bytes)
    stopped_left_x = left_release_box[11]
    left_stable_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((frame_number(m) - frame_number(left_release_box)) & 0xFFFF) >= 8,
        ),
        1.0,
        "post-left-release movement interval",
    )
    assert isinstance(left_stable_box, bytes)
    if left_stable_box[11] != stopped_left_x \
            or left_stable_box[MB_SHIP_FRAME] not in (0, 1):
        fail(
            "ship did not return to a stationary neutral pose after "
            f"Left-arrow key-up: x {stopped_left_x}->{left_stable_box[11]} "
            f"frame={left_stable_box[MB_SHIP_FRAME]}"
        )

    # A zero-hold tap may be released before the guest's next 30 Hz game tick;
    # it still must queue one shot from the keyboard strobe.
    client.tap_key(SDL_SCANCODE_SPACE, hold_s=0)
    tap_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[16] >= 1 and m[19] >= 1),
        1.0,
        "one queued bullet from a quick Space tap",
    )
    assert isinstance(tap_box, bytes)
    fire_burst_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[MB_SHIP_FRAME] == 6),
        1.0,
        "the ship's muzzle-burst frame",
    )
    assert isinstance(fire_burst_box, bytes)
    fire_dissipate_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[MB_SHIP_FRAME] == 7),
        1.0,
        "the ship's dissipating-fire frame",
    )
    assert isinstance(fire_dissipate_box, bytes)

    # One KEYEVENT down with no host repeat events must sustain autofire via
    # the Apple //e AKD level until the corresponding key-up.
    music_events_before_hold = tap_box[MB_MUSIC_EVENTS]
    client.key_down(SDL_SCANCODE_SPACE)
    try:
        held_music_box = wait_for(
            lambda: matching_mailbox(
                client,
                lambda m: m[MB_EFFECT_KIND] == 1
                          and ((m[MB_MUSIC_EVENTS] - music_events_before_hold) & 0xFF) >= 1
                          and (m[MB_AY_MIXER] & 0x03) == 0,
            ),
            1.5,
            "music advancement during held-fire effects",
        )
        assert isinstance(held_music_box, bytes)
        bullet_box = wait_for(
            lambda: matching_mailbox(client, lambda m: m[16] >= 3 and m[19] >= 3),
            2.0,
            "three simultaneous bullets from held-space autofire",
        )
    finally:
        client.key_up(SDL_SCANCODE_SPACE)
    assert isinstance(bullet_box, bytes)
    time.sleep(0.35)
    released_box = read_mailbox(client)
    if released_box[19] != bullet_box[19]:
        fail(f"held-space autofire continued after key-up: "
             f"{bullet_box[19]} -> {released_box[19]} shots")
    if released_box[MB_AY_MIXER] == 0x3F or released_box[MB_AY_MIXER] & 0x03:
        fail(f"music did not survive effect release: mixer=${released_box[MB_AY_MIXER]:02X}")

    replay_at_start = bullet_box[17]
    if replay_at_start < REPLAY_FIRST_BANK:
        fail(f"replay used reserved RamWorks bank {replay_at_start}")
    replay_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[17] != replay_at_start),
        2.0,
        "RamWorks replay-bank rotation",
    )
    assert isinstance(replay_box, bytes)
    if replay_box[17] < REPLAY_FIRST_BANK:
        fail(f"replay rotated into reserved RamWorks bank {replay_box[17]}")
    if frame_number(replay_box) == start_frame:
        fail("game frame counter did not advance")

    wanted_marker = bytes((0xC1, 0xB2, 0xCC, 0xE9, 0x01))
    marker = wait_for(
        lambda: matching_memory(client, 0x4078, wanted_marker),
        1.0,
        "a committed A2Li DHGRi frame",
    )
    assert isinstance(marker, bytes)

    final_visual_box, planes = capture_committed_dhgri(client)
    # Video-7 MIX selector bits are metadata, not pixels. Count only the low
    # seven DHGR data bits so a selector-only background cannot satisfy the
    # plane-density check.
    nonzero = {
        name: sum((value & 0x7F) != 0 for value in data)
        for name, data in planes.items()
    }
    sparse = {name: count for name, count in nonzero.items() if count < 100}
    if sparse:
        fail(f"DHGRi plane data is unexpectedly sparse: {sparse}")
    if planes["main page 1"] == planes["main page 2"]:
        fail("DHGRi main fields are identical")
    if planes["aux page 1"] == planes["aux page 2"]:
        fail("DHGRi auxiliary fields are identical")
    field_differences = {
        "main": sum(a != b for a, b in zip(planes["main page 1"], planes["main page 2"])),
        "aux": sum(a != b for a, b in zip(planes["aux page 1"], planes["aux page 2"])),
    }
    if min(field_differences.values()) < 20:
        fail(f"DHGRi fields do not carry enough distinct detail: {field_differences}")

    # Video-7 state 10 interprets bit 7 of the interleaved AUX/MAIN stream as
    # an 8+8+8+4-dot monochrome/color selector. Every byte in the gameplay
    # rows is color-selected, on both pages and in both planes, so moving art
    # cannot expose a monochrome seam at an odd-byte boundary.
    for name, data in planes.items():
        for y in range(20, 180):
            offset = hgr_address(y, 0x2000 if "page 1" in name else 0x4000)
            offset -= 0x2000 if "page 1" in name else 0x4000
            row = data[offset:offset + 40]
            if len(row) != 40 or any((value & 0x80) == 0 for value in row):
                fail(f"{name} row {y} does not fully select Video-7 color")

    # The static border deliberately overwrites every byte, so its exact
    # values also prove that non-text writes preserve the selector bit.
    for page, suffix in ((0x2000, "page 1"), (0x4000, "page 2")):
        offset = hgr_address(178, page) - page
        if planes[f"aux {suffix}"][offset:offset + 40] != bytes((0xD5,)) * 40:
            fail(f"aux {suffix} color border is damaged")
        if planes[f"main {suffix}"][offset:offset + 40] != bytes((0xAA,)) * 40:
            fail(f"main {suffix} color border is damaged")

    # HUD, title, and footer occupy dedicated rows. Keeping all four planes'
    # selector bits clear makes their glyphs monochrome white without turning
    # the colored playfield monochrome.
    text_rows = (*range(2, 9), *range(10, 17), *range(181, 188))
    for name, data in planes.items():
        page = 0x2000 if "page 1" in name else 0x4000
        for y in text_rows:
            offset = hgr_address(y, page) - page
            row = data[offset:offset + 40]
            if any(value & 0x80 for value in row):
                fail(f"{name} text row {y} incorrectly selects Video-7 color")

    # The 18 half-column title occupies slots 31..48, leaving exactly 31
    # half-columns on either side. Verify both edge glyphs plus the blank
    # guards and internal space so a hard-coded alignment regression is
    # visible in memory as well as in the screenshot.
    expected_title_a = bytes((0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11))
    expected_title_n = bytes((0x11, 0x13, 0x15, 0x19, 0x11, 0x11, 0x11))
    for page, suffix in ((0x2000, "page 1"), (0x4000, "page 2")):
        def title_column(half_x: int) -> bytes:
            plane = "aux" if (half_x & 1) == 0 else "main"
            return bytes(
                planes[f"{plane} {suffix}"][
                    hgr_address(10 + row, page) - page + (half_x >> 1)
                ]
                for row in range(7)
            )

        if title_column(31) != expected_title_a \
                or title_column(48) != expected_title_n \
                or any(title_column(guard) != bytes(7) for guard in (30, 40, 49)):
            fail(f"{suffix} APPLETINI INVASION title is not centered")

    # The font table is stored conventionally with bit 4 at the left, but an
    # Apple II graphics byte displays bit 0 at the left. SCORE's asymmetric S
    # is a compact regression check that the game reverses those five bits.
    expected_s = bytes((0x1E, 0x01, 0x01, 0x0E, 0x10, 0x10, 0x0F))
    for page in (0x2000, 0x4000):
        actual_s = bytes(
            client.read_mem(MEM_MAIN_RAW, hgr_address(2 + row, page), 1)[0]
            for row in range(7)
        )
        if actual_s != expected_s:
            fail(f"page ${page:04X} SCORE glyph is mirrored or damaged: {actual_s.hex()}")

    final_box = read_mailbox(client)
    return {
        "platform": status.platform_id,
        "mailbox": final_box.hex(),
        "frames": (start_frame, frame_number(final_box)),
        "player_x": moved_box[11],
        "ship_frames": (
            moved_box[MB_SHIP_FRAME], left_box[MB_SHIP_FRAME],
            fire_burst_box[MB_SHIP_FRAME], fire_dissipate_box[MB_SHIP_FRAME],
        ),
        "enemy_shooter": shooter,
        "player_bullets": bullet_box[16],
        "shots_fired": bullet_box[19],
        "speech": sorted(speech_values),
        "speech_completions": speech_completions,
        "parallax_phases": parallax_phases(final_visual_box),
        "parallax_deltas": phase_deltas,
        "music_steps": sorted(music_steps),
        "music_loop": music_loop_box[MB_MUSIC_LOOPS],
        "mixer_values": sorted(mixer_values),
        "replay_banks": (replay_at_start, replay_box[17]),
        "nonzero": nonzero,
        "field_differences": field_differences,
        "cadence": (
            cadence_cycles_per_frame, cadence_frames, cadence_elapsed,
            cadence_hz,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--parallax", type=Path, default=PARALLAX_PATH)
    parser.add_argument("--ship", type=Path, default=SHIP_PATH)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep-log", action="store_true")
    args = parser.parse_args()

    disk = args.disk.resolve()
    config = args.config.resolve()
    emulator = args.emulator.resolve()
    parallax = args.parallax.resolve()
    ship = args.ship.resolve()
    for path, description in ((disk, "SmartPort disk"), (config, "system config"),
                              (emulator, "GSSquared executable"),
                              (parallax, "PARALLAX asset"),
                              (ship, "SHIP asset")):
        if not path.is_file():
            fail(f"missing {description}: {path}")
    if disk.stat().st_size < 800 * 1024 or disk.stat().st_size % 512:
        fail(f"SmartPort image has invalid size: {disk.stat().st_size}")
    root_files = prodos_root_files(disk.read_bytes())
    if root_files.get("PRODOS", (None,))[0] != 0xFF:
        fail(f"SmartPort image has no ProDOS SYS kernel: {root_files}")
    if root_files.get("INVASION.SYSTEM") != (0xFF, 0x2000):
        fail(f"INVASION.SYSTEM is not a direct-boot $2000 SYS file: {root_files}")
    if root_files.get("PARALLAX") != (0x06, 0x2000):
        fail(f"PARALLAX is not a SmartPort-loaded $2000 BIN file: {root_files}")
    obsolete = {"BASIC.SYSTEM", "STARTUP", "INVASION"} & root_files.keys()
    if obsolete:
        fail(f"SmartPort image still contains a BASIC launcher: {sorted(obsolete)}")

    config_text = config.read_text()
    if 'card = "diskII"' in config_text or 'card = "diskii"' in config_text:
        fail("showcase config must not contain a Disk II controller")
    if 'slot = 7\ncard = "appletini"' not in config_text:
        fail("showcase config must put Appletini in slot 7")
    if 'slot = 4\ncard = "mockingboard"' not in config_text:
        fail("showcase config must put Mockingboard in slot 4")

    ship_variants, ship_bank, ship_sha256 = load_ship(ship)
    layers, parallax_sha256 = load_parallax(parallax, ship_bank)

    socket_path = Path(tempfile.gettempdir()) / f"gs2-appletini-invasion-{os.getpid()}.sock"
    log_file = tempfile.NamedTemporaryFile(
        prefix="gs2-appletini-invasion-", suffix=".log", delete=False,
    )
    log_path = Path(log_file.name)
    process: subprocess.Popen[bytes] | None = None
    client = Client()
    passed = False
    exit_error: str | None = None
    try:
        process = subprocess.Popen(
            (
                str(emulator), str(config), f"-ds7d1={disk}",
                "--debug", str(socket_path), "--no-quit-confirm",
            ),
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        connect_debug(client, socket_path, process, args.timeout)
        result = exercise(client, args.timeout, layers, ship_variants)
        print("PASS Appletini Invasion")
        print(f"  PARALLAX sha256={parallax_sha256}")
        print(f"  SHIP sha256={ship_sha256}")
        print(f"  platform={result['platform']} mailbox={result['mailbox']}")
        print(f"  frames={result['frames']} player_x={result['player_x']} "
              f"simultaneous_bullets={result['player_bullets']} "
              f"shots_fired={result['shots_fired']}")
        print(f"  ship frames={result['ship_frames']} "
              f"enemy shooter={result['enemy_shooter']}")
        print(f"  speech={result['speech']} completions={result['speech_completions']} "
              f"replay_banks={result['replay_banks']}")
        print(f"  parallax phases={result['parallax_phases']} "
              f"sample deltas={result['parallax_deltas']}")
        print(f"  music steps={result['music_steps']} loop={result['music_loop']} "
              f"mixers={result['mixer_values']}")
        print(f"  DHGRi nonzero bytes={result['nonzero']}")
        print(f"  DHGRi field differences={result['field_differences']}")
        cycles_per_frame, cadence_frames, cadence_elapsed, cadence_hz = result["cadence"]
        print(f"  cadence={cycles_per_frame:.1f} CPU cycles/VBL, "
              f"{cadence_frames} VBLs/{cadence_elapsed:.3f}s "
              f"({cadence_hz:.2f} Hz)")
        passed = True
    finally:
        try:
            client.quit()
        except (OSError, RuntimeError, ProtocolError):
            pass
        client.close()
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if passed and process.returncode != 0:
                passed = False
                exit_error = f"GSSquared exited with status {process.returncode}"
        log_file.close()
        if socket_path.exists():
            socket_path.unlink()
        if passed and not args.keep_log:
            log_path.unlink(missing_ok=True)
        else:
            print(f"GSSquared log: {log_path}", file=sys.stderr)
    if exit_error is not None:
        fail(exit_error)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
