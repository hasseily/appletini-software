#!/usr/bin/env python3
"""Build libtini, its SDK programs, every game manifest and local ProDOS disks.

Uses cc65 2.19. A game is a games/*/game.json or examples/*/game.json
manifest; docs/GAMES.md describes the format. --game NAME builds the library
and that game alone.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from disk import build_image, read_root_files, validate_image
import music

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
OBJECT_EPOCH = 1792454400  # 2026-10-20 00:00 UTC, not the build clock.
SDK_PROGRAMS = ("libtini", "audio_demo", "test_target", "test_graphics", "test_audio", "test_storage")
GAME_KEYS = {"name", "title", "sources", "assembly", "config", "cflags", "generate", "disk", "private"}
STEP_KEYS = {"command", "inputs", "outputs"}
DISK_KEYS = {"volume", "system", "blocks", "files"}
FILE_KEYS = {"name", "path", "program", "type", "aux"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv):
    print("+", subprocess.list2cmdline([str(x) for x in argv]), flush=True)
    subprocess.run([str(x) for x in argv], cwd=ROOT, check=True)


def installed_tools(home):
    if home:
        base = Path(home).expanduser().resolve()
    else:
        executable = shutil.which("cc65")
        if not executable:
            raise SystemExit("Install cc65 2.19; pass --cc65-home or put its bin on PATH")
        base = Path(executable).resolve().parent.parent
    suffix = ".exe" if os.name == "nt" else ""
    tools = {name: base / "bin" / (name + suffix)
             for name in ("cc65", "ca65", "ld65", "ar65")}
    tools["runtime"] = base / "lib/none.lib"
    for path in tools.values():
        if not path.is_file():
            raise SystemExit("Incomplete installed cc65 SDK: " + str(path))
    versions = {}
    for name in ("cc65", "ca65", "ld65", "ar65"):
        result = subprocess.run([str(tools[name]), "V" if name == "ar65" else "--version"],
                                capture_output=True, text=True, check=True)
        version = (result.stdout + result.stderr).strip()
        if not re.fullmatch(name + r" V2\.19", version):
            raise SystemExit("Expected " + name + " V2.19, got " + version)
        versions[name] = version
    return base, tools, versions


def rel(path):
    return path.relative_to(ROOT).as_posix()


def normalize_object(path):
    """Fix ca65 2.19's informational translation timestamp, not target data.

    ca65 2.19 has no SOURCE_DATE_EPOCH support. Its OPT_DATETIME is a ULEB128
    number in the option section of object format 17. Validate that section
    rather than blindly patching byte offsets inside code or relocations.
    See cc65 V2.19 src/{ca65/options.c,common/objdefs.h,common/optdefs.h}.
    """
    data = bytearray(path.read_bytes())
    if len(data) < 96 or data[:4] != b"Uzna" or u16_object(data, 4) != 17:
        raise SystemExit("Unexpected ca65 object format: " + str(path))
    offset, size = struct.unpack_from("<II", data, 8)
    end = offset + size
    if offset < 96 or size < 1 or end > len(data):
        raise SystemExit("Invalid ca65 object option section")

    def readvar(position):
        result, shift = 0, 0
        while position < end and shift < 35:
            value = data[position]
            position += 1
            result |= (value & 127) << shift
            if not value & 128:
                return result, position
            shift += 7
        raise SystemExit("Invalid ca65 object option")

    count, offset = readvar(offset)
    if count > size // 2:
        raise SystemExit("Invalid ca65 object option count")
    changed = 0
    for _ in range(count):
        if offset >= end:
            raise SystemExit("Truncated ca65 object option")
        kind = data[offset]
        offset += 1
        start = offset
        _, offset = readvar(offset)
        if kind == 0x40:  # OPT_DATETIME; never a target section.
            epoch = OBJECT_EPOCH
            encoded = bytearray()
            while epoch >= 128:
                encoded.append((epoch & 127) | 128)
                epoch >>= 7
            encoded.append(epoch)
            if len(encoded) != offset - start:
                raise SystemExit("Unexpected ca65 timestamp width")
            data[start:offset] = encoded
            changed += 1
    if changed != 1 or offset != end:
        raise SystemExit("Missing or malformed ca65 translation timestamp")
    path.write_bytes(data)
    os.utime(path, (OBJECT_EPOCH, OBJECT_EPOCH))


def u16_object(data, offset):
    return int.from_bytes(data[offset:offset + 2], "little")


def assemble(source, object_file, sdk, tools):
    object_file.parent.mkdir(parents=True, exist_ok=True)
    # ca65 stores a source-file timestamp even without line debug information.
    # Stage a normal copy under build/, never alter the source's timestamps.
    staged = BUILD / "asm" / (object_file.stem + ".s")
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(source.read_bytes())
    os.utime(staged, (OBJECT_EPOCH, OBJECT_EPOCH))
    run([tools["ca65"], "--cpu", "65c02", "-t", "none",
         "-I", sdk / "asminc", "-I", "src/target", "-o", rel(object_file), rel(staged)])
    normalize_object(object_file)


def compile_c(source, object_file, sdk, tools, private=False, includes=(), flags=()):
    """includes are extra header directories; cc65 already searches the source's."""
    assembly = object_file.with_suffix(".s")
    object_file.parent.mkdir(parents=True, exist_ok=True)
    run([tools["cc65"], "-t", "none", "--cpu", "65c02", "--standard", "c99", "-O", *flags,
         "-I", sdk / "include", "-I", "include", "-I", "src", "-I", rel(BUILD),
         *(item for path in includes for item in ("-I", rel(path))),
         "-D", "TI_PRIVATE_TRANSPORT=" + str(int(private)), "-o", rel(assembly), rel(source)])
    assemble(assembly, object_file, sdk, tools)


def read_labels(path):
    """Every symbol in an ld65 VICE label file, including memory area bounds."""
    labels = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "al":
            labels[parts[2].lstrip(".")] = int(parts[1], 16)
    return labels


def layout_summary(map_file, labels):
    """Parse ld65's final segment table for a compact machine-checkable report.

    The application region ends at the layout's memory end or stack bottom.
    Low constants are allowed in its readable low range, NEARBSS in its near
    arena, and nothing else outside the region.
    """
    top = min(labels["_ti_memory_end"], labels["_ti_stack_bottom"])
    low = labels["_ti_readable_low_start"], labels["_ti_readable_low_end"]
    near = labels["_ti_near_start"], labels["_ti_near_end"]
    segments = []
    active = False
    for line in map_file.read_text().splitlines():
        if line.startswith("Segment list:"):
            active = True
            continue
        if active and line.startswith("Exports list"):
            break
        match = re.fullmatch(r"([A-Za-z0-9_]+)\s+([0-9A-Fa-f]{6})\s+([0-9A-Fa-f]{6})\s+([0-9A-Fa-f]{6})\s+[0-9A-Fa-f]+", line.strip())
        if active and match:
            name, start, end, size = match.groups()
            start, end, size = int(start, 16), int(end, 16), int(size, 16)
            low_constant = name in ("RODATA", "AMEMCODE", "LOWCODE") and low[0] <= start <= end < low[1]
            if name == "NEARBSS":
                if size and not near[0] <= start <= end < near[1]:
                    raise SystemExit("NEARBSS outside the near arena")
            elif size and name != "ZEROPAGE" and not low_constant and not (0x2000 <= start <= end < top):
                raise SystemExit("Linked segment outside application region: " + name)
            if name == "ZEROPAGE" and size and not (0x80 <= start <= end < 0xA0):
                raise SystemExit("Linked zero page outside reservation")
            segments.append({"name": name, "start": start, "end": end, "size": size})
    if not any(segment["name"] == "STARTUP" and segment["start"] == 0x2000
               for segment in segments):
        raise SystemExit("Missing raw SYS entry at $2000")
    return segments


def memory_report(labels):
    """Used and free bytes of every linker memory area that defines its bounds."""
    areas = []
    for name, start in labels.items():
        match = re.fullmatch(r"__([A-Z0-9_]+)_START__", name)
        if not match:
            continue
        area = match.group(1)
        size, last = labels.get("__" + area + "_SIZE__"), labels.get("__" + area + "_LAST__")
        if size is None or last is None:
            continue
        areas.append({"area": area, "start": start, "size": size,
                      "used": last - start, "free": start + size - last})
    return sorted(areas, key=lambda area: area["start"])


def memory_line(stem, areas):
    return stem + " memory: " + "; ".join(
        "{} ${:04X}-${:04X} {} free".format(area["area"], area["start"],
                                            area["start"] + area["size"] - 1, area["free"])
        for area in areas if area["area"] != "ZP")


def link(argv, stem):
    """Run ld65 and turn a memory overflow into a one-line summary."""
    print("+", subprocess.list2cmdline([str(x) for x in argv]), flush=True)
    result = subprocess.run([str(x) for x in argv], cwd=ROOT, capture_output=True,
                            encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout)
    sys.stdout.write(result.stderr)
    if result.returncode:
        overflows = re.findall(r"[Ss]egment\W+(\w+)\W+overflows memory area\W+(\w+)\W+by (\d+) bytes?",
                               result.stdout + result.stderr)
        if overflows:
            raise SystemExit(stem + " does not fit: " + "; ".join(
                "segment {} needs {} more bytes in memory area {}".format(segment, count, area)
                for segment, area, count in overflows))
        raise subprocess.CalledProcessError(result.returncode, argv)


def expand(text, game):
    return (text.replace("{root}", ROOT.as_posix()).replace("{game}", game["dir"].as_posix())
            .replace("{build}", BUILD.as_posix()))


def resolve(text, game):
    """A manifest path: placeholders expanded, otherwise relative to the game."""
    path = Path(expand(text, game))
    return (path if path.is_absolute() else game["dir"] / path).resolve()


def files_under(paths):
    for path in paths:
        if path.is_dir():
            yield from sorted(item for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            yield path
        else:
            raise SystemExit("Missing manifest input: " + str(path))


def strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def load_games():
    """Every game manifest, checked before anything is built."""
    games = {}
    for path in sorted([*ROOT.glob("examples/*/game.json"), *ROOT.glob("games/*/game.json")]):
        where = rel(path)
        try:
            game = json.loads(path.read_text())
        except json.JSONDecodeError as error:
            raise SystemExit(where + ": " + str(error)) from None
        if not isinstance(game, dict) or set(game) - GAME_KEYS:
            raise SystemExit(where + ": unknown keys " + ", ".join(sorted(set(game) - GAME_KEYS)))
        name = game.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,14}", name):
            raise SystemExit(where + ": name must be 1-15 lowercase letters, digits or _")
        if name in SDK_PROGRAMS or name in games:
            raise SystemExit(where + ": name " + name + " is already used")
        if not strings(game.get("sources")) or not game["sources"]:
            raise SystemExit(where + ": sources must list the C files, main first")
        for key in ("assembly", "cflags"):
            if not strings(game.get(key, [])):
                raise SystemExit(where + ": " + key + " must be a list of strings")
        if not isinstance(game.get("config", ""), str):
            raise SystemExit(where + ": config must be a path")
        if not isinstance(game.get("private", True), bool):
            raise SystemExit(where + ": private must be true or false")
        for step in game.get("generate", []):
            if not isinstance(step, dict) or set(step) - STEP_KEYS or not strings(step.get("command")) \
                    or not step["command"] or not all(strings(step.get(key, [])) for key in ("inputs", "outputs")):
                raise SystemExit(where + ": generate steps need a command list and optional inputs and outputs")
        disk = game.get("disk")
        if disk is not None:
            if not isinstance(disk, dict) or set(disk) - DISK_KEYS:
                raise SystemExit(where + ": disk keys are volume, system, blocks and files")
            for item in disk.get("files", []):
                if not isinstance(item, dict) or set(item) - FILE_KEYS or "name" not in item \
                        or ("path" in item and "program" in item):
                    raise SystemExit(where + ": each disk file has a name and at most one of path or program")
        game["dir"] = path.parent
        game["manifest"] = path
        games[name] = game
    return games


def main():
    global BUILD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc65-home", default=os.environ.get("CC65_HOME"))
    parser.add_argument("--test-target", action="store_true",
                        help="also link tests/target_tests.c into build/test_target.system")
    parser.add_argument("--no-disk", action="store_true", help="link only, without the installed ProDOS input")
    parser.add_argument("--prodos-image", type=Path, help="separately installed exact ProDOS 2.4.3 .po input")
    parser.add_argument("--private", action="store_true", help="include optional, probed AMEM transport")
    parser.add_argument("--build-dir", type=Path, default=Path("build"),
                        help="repo-local output directory; e.g. build/private for a separate optional build")
    parser.add_argument("--game", help="build the library and only this game manifest's program and disk")
    args = parser.parse_args()
    BUILD = (ROOT / args.build_dir).resolve()
    if not BUILD.is_relative_to(ROOT) or BUILD == ROOT:
        raise SystemExit("Build output must be a directory inside this project")
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer required; reference build uses 3.12.0")
    games = load_games()
    if args.game and args.game not in games:
        raise SystemExit("Unknown game " + args.game + "; manifests define: " + ", ".join(sorted(games)))
    selected = [games[args.game]] if args.game else list(games.values())
    # A game with "private": false has no optional-AMEM variant.
    if args.private:
        if args.game and not games[args.game].get("private", True):
            raise SystemExit(args.game + " has no optional-AMEM build; its manifest sets private to false")
        selected = [game for game in selected if game.get("private", True)]
    sdk, tools, versions = installed_tools(args.cc65_home)
    BUILD.mkdir(parents=True, exist_ok=True)
    inputs = []
    objects = []
    generated = []
    for game in selected:
        inputs.append(game["manifest"])
        for step in game.get("generate", []):
            command = [expand(item, game) for item in step["command"]]
            run([sys.executable, *command] if command[0].endswith(".py") else command)
            inputs.extend(files_under(resolve(item, game) for item in step.get("inputs", [])))
            generated.extend(resolve(item, game) for item in step.get("outputs", []))
    if (ROOT / "assets/music.json").exists():
        run([sys.executable, ROOT / "tools/music.py", ROOT / "assets/music.json",
             "--output", BUILD / "audio_music.h", "--symbol", "ti_demo_music",
             "--report", BUILD / "audio_music.json"])
        inputs.extend((ROOT / "assets/music.json", ROOT / "tools/music.py"))
        generated.extend((BUILD / "audio_music.h", BUILD / "audio_music.json"))
    if (ROOT / "assets/speech.json").exists():
        run([sys.executable, ROOT / "tools/speech.py", ROOT / "assets/speech.json",
             "--output", BUILD / "audio_speech.h", "--symbol", "ti_demo_speech"])
        inputs.extend((ROOT / "assets/speech.json", ROOT / "tools/speech.py"))
        generated.append(BUILD / "audio_speech.h")
    songs = ROOT / "tests/audio_songs.json"
    if args.test_target and songs.exists():
        # The audio target's pattern songs, also compiled by tests/audio_validate.py.
        header = "".join(music.compile_song(document, symbol)[0]
                         for symbol, document in json.loads(songs.read_text()).items())
        (BUILD / "audio_song.h").write_text(header)
        inputs.extend((songs, ROOT / "tools/music.py"))
        generated.append(BUILD / "audio_song.h")
    for source in sorted((ROOT / "src").glob("*.c")):
        if source.name == "diag.c":
            continue
        obj = BUILD / "obj" / (source.stem + ".o")
        compile_c(source, obj, sdk, tools, args.private)
        inputs.append(source)
        objects.append(obj)
    for source in sorted((ROOT / "src/target").glob("*.s")):
        if source.name == "startup.s":
            continue
        obj = BUILD / "obj/target" / ("target_" + source.stem + ".o")
        assemble(source, obj, sdk, tools)
        inputs.append(source)
        objects.append(obj)
    if args.private:
        source = ROOT / "src/optional/amem_transport.s"
        obj = BUILD / "obj/optional_amem_transport.o"
        assemble(source, obj, sdk, tools)
        inputs.append(source); objects.append(obj)
    archive = BUILD / "libtini.lib"
    # ar65's r preserves absent modules, so replace the generated archive first.
    archive.unlink(missing_ok=True)
    run([tools["ar65"], "r", rel(archive), *map(rel, objects)])
    startup_source = ROOT / "src/target/startup.s"
    startup = BUILD / "obj/target/startup.o"
    assemble(startup_source, startup, sdk, tools)
    inputs.append(startup_source)
    layouts = {}
    memory = {}
    outputs = [archive]

    def link_program(source, stem, extra_asm=(), extra_c=(), config="cfg/libtini.cfg",
                     includes=(), flags=()):
        obj = BUILD / "obj" / (stem + ".o")
        compile_c(source, obj, sdk, tools, args.private, includes, flags)
        inputs.append(source)
        extras = []
        for c_source in extra_c:
            extra = BUILD / "obj" / (stem + "_" + c_source.stem + ".o")
            compile_c(c_source, extra, sdk, tools, args.private, includes, flags)
            inputs.append(c_source)
            extras.append(extra)
        for assembly_source in extra_asm:
            extra = BUILD / "obj" / (assembly_source.stem + ".o")
            assemble(assembly_source, extra, sdk, tools)
            inputs.append(assembly_source)
            extras.append(extra)
        program = BUILD / (stem + ".system")
        map_file, labels_file, debug = (BUILD / (stem + suffix) for suffix in (".map", ".lbl", ".dbg"))
        link([tools["ld65"], "-C", config, "-o", rel(program),
              "-m", rel(map_file), "-Ln", rel(labels_file), "--dbgfile", rel(debug),
              rel(startup), rel(obj), *map(rel, extras), rel(archive), tools["runtime"]], stem)
        labels = read_labels(labels_file)
        layouts[stem] = layout_summary(map_file, labels)
        memory[stem] = memory_report(labels)
        outputs.extend((program, map_file, labels_file, debug))
        return program

    def build_game(game):
        directory = game["dir"]
        sources = [directory / item for item in game["sources"]]
        assembly = [directory / item for item in game.get("assembly", [])]
        config = ROOT / game.get("config", "cfg/libtini.cfg")
        for path in (*sources, *assembly, config):
            if not path.is_file():
                raise SystemExit(rel(game["manifest"]) + ": missing " + str(path))
        # Python caches are not sources; the release export omits them too.
        inputs.extend(path for path in directory.rglob("*") if path.is_file() and
                      "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"))
        return link_program(sources[0], game["name"], extra_c=sources[1:], extra_asm=assembly,
                            config=rel(config), includes=[directory], flags=game.get("cflags", []))

    diagnostic = link_program(ROOT / "src/diag.c", "libtini")
    programs = {"libtini": diagnostic}
    wanted = {item["program"] for game in selected
              for item in (game.get("disk") or {}).get("files", []) if "program" in item}
    if (ROOT / "examples/audio_demo.c").exists() and (not args.game or "audio_demo" in wanted):
        programs["audio_demo"] = link_program(ROOT / "examples/audio_demo.c", "audio_demo")
    for game in selected:
        programs[game["name"]] = build_game(game)
    if args.test_target:
        source = ROOT / "tests/target_tests.c"
        if not source.exists():
            source = ROOT / "tests/test_target.c"
        link_program(source, "test_target", sorted((ROOT / "tests").glob("target_helpers.s")))
        for filename, stem in (("graphics_target.c", "test_graphics"), ("audio_target.c", "test_audio"),
                               ("storage_target.c", "test_storage")):
            source = ROOT / "tests" / filename
            if source.exists(): link_program(source, stem)
    prodos = None
    if not args.no_disk:
        lock_path = ROOT / "tools/prodos-input.json"
        lock = json.loads(lock_path.read_text())
        image_path = args.prodos_image.resolve() if args.prodos_image else ROOT / lock["path"]
        if not image_path.exists():
            raise SystemExit("Install the ProDOS input first: python tools/setup_inputs.py")
        if sha(image_path) != lock["sha256"]:
            raise SystemExit("Installed ProDOS image differs from tools/prodos-input.json")
        image = build_image(image_path.read_bytes(), diagnostic.read_bytes())
        image_out = BUILD / "libtini.po"
        image_out.write_bytes(image)
        validate_image(image)
        files = read_root_files(image)
        prodos = {"version": lock["version"], "input_sha256": sha(image_path),
                  "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                            for name, data in files.items()}}
        outputs.append(image_out)
        if "audio_demo" in programs:
            demo_disk = build_image(image_path.read_bytes(), programs["audio_demo"].read_bytes(),
                                    "AUDIO.SYSTEM", volume="AUDIO")
            validate_image(demo_disk)
            (BUILD / "audio_demo.po").write_bytes(demo_disk)
            outputs.append(BUILD / "audio_demo.po")
        for game in selected:
            disk = game.get("disk")
            if disk is None:
                continue
            name = game["name"]
            extra_files = []
            for item in disk.get("files", []):
                if "program" in item:
                    if item["program"] not in programs:
                        raise SystemExit(rel(game["manifest"]) + ": no program " + item["program"])
                    data, kind, aux = programs[item["program"]].read_bytes(), 0xFF, 0x2000
                elif "path" in item:
                    data, kind, aux = resolve(item["path"], game).read_bytes(), 0x06, 0
                else:
                    data, kind, aux = b"", 0x06, 0
                extra_files.append((item["name"], data, item.get("type", kind), item.get("aux", aux)))
            game_disk = build_image(image_path.read_bytes(), programs[name].read_bytes(),
                                    disk.get("system", name.upper() + ".SYSTEM"), files=extra_files,
                                    total=disk.get("blocks", 1600), volume=disk.get("volume", name.upper()),
                                    max_program_bytes=0x9F00)
            validate_image(game_disk)
            game_image = BUILD / (name + ".po")
            game_image.write_bytes(game_disk)
            outputs.append(game_image)
    inputs.extend(sorted((ROOT / "include").rglob("*.h")))
    inputs.extend(sorted((ROOT / "src").glob("*.h")))
    inputs.extend(sorted((ROOT / "cfg").glob("*.cfg")))
    inputs.extend(ROOT / item for item in ("tools/build.py", "tools/disk.py", "tools/prodos-input.json"))
    (BUILD / "layout.json").write_text(json.dumps(layouts, indent=2) + "\n")
    (BUILD / "memory.json").write_text(json.dumps(memory, indent=2) + "\n")
    outputs.extend((BUILD / "layout.json", BUILD / "memory.json"))
    outputs.extend(path for path in generated if path.exists())
    manifest = {
        "profile": "65C02, " + ("optional probed AMEM" if args.private else "CPU-only, private transport compiled out"),
        "firmware_validation_baseline": {
            "release": "F1.3.1",
            "commit": "8af06741f3b9454b6bc226b7d55f69cc09097ccf",
            "board_tested": False,
        },
        "python": ".".join(map(str, sys.version_info[:3])),
        "tools": {name: {"version": versions.get(name), "sha256": sha(path)}
                  for name, path in tools.items()},
        "sdk_headers": {path.relative_to(sdk).as_posix(): sha(path)
                        for directory in ("include", "asminc")
                        for path in sorted((sdk / directory).rglob("*")) if path.is_file()},
        "inputs": {rel(path): sha(path) for path in sorted(set(inputs))},
        "outputs": {rel(path): {"bytes": path.stat().st_size, "sha256": sha(path)} for path in outputs},
        "prodos": prodos,
    }
    (BUILD / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for game in selected:
        print(memory_line(game["name"], memory[game["name"]]))
    built = ["libtini", *(["audio demo"] if "audio_demo" in programs else []),
             *(game.get("title", game["name"]) for game in selected)]
    print("Built " + (", ".join(built[:-1]) + " and " + built[-1] if len(built) > 1 else built[0])
          + " (" + ("optional AMEM" if args.private else "CPU-only") + "); checked all layouts and "
          + ("ProDOS disks" if prodos else "link outputs"))
    print("Manifest: " + rel(BUILD / "manifest.json"))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit("Build stopped: tool returned " + str(error.returncode)) from None
