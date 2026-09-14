#!/usr/bin/env python3
"""Boot the actual disk and exercise folders/slideshows via GSSquared's debugger."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import build_fatdog_magic_disk as build
from prodos import create_folder, raw_files, verify_allocation, entries, entry_name, word

DEMO = Path(__file__).resolve().parents[1]


def symbols():
    return {name: int(value, 16) for name, value in re.findall(
        r"^\s*(\w+)\s*=\s*\$([0-9a-f]+)",
        (DEMO / "build/magic.sym").read_text(), re.M | re.I)}


def save_hgr(page, path):
    """Lossless monochrome rendering of the emulator's live HGR framebuffer."""
    from PIL import Image
    image = Image.new("RGB", (280, 192))
    pixels = image.load()
    for y in range(192):
        offset = (y & 7) * 1024 + ((y >> 3) & 7) * 128 + (y >> 6) * 40
        for x in range(280):
            pixels[x, y] = (255, 255, 255) if page[offset + x // 7] & (1 << (x % 7)) else (0, 0, 0)
    image.resize((840, 576), Image.Resampling.NEAREST).save(path)


def make_fixture(source, output):
    """Change the disk AFTER compilation: exercise discovery, not generated tables."""
    shutil.copyfile(source, output)
    create_folder(output, "Empty")
    create_folder(output, "Second.Set")
    images = list(raw_files(DEMO / "assets/fgr2.po").items())
    for name, payload in images[:2]:
        build.ac("-p", output, "SECOND.SET/" + name, "BIN", "0x4000", data=payload)
    # Must ignore wrong length and wrong type.
    build.ac("-p", output, "SECOND.SET/SHORT", "BIN", "0x4000", data=b"x" * 512)
    build.ac("-p", output, "SECOND.SET/LONG", "BIN", "0x4000", data=b"x" * 24576)
    build.ac("-p", output, "SECOND.SET/TEXT", "TXT", "0", data=b"x" * 8192)
    for i in range(12):
        create_folder(output, f"Folder.{i:02}")
    create_folder(output, "HGRi")
    create_folder(output, "DHGRi")
    build.ac("-p", output, "STANDARD.HGR/EXTRA", "BIN", "0x4000", data=images[0][1])
    # Put EXTRA at the high end of the expanded volume. Its runtime read below
    # proves 16-bit block addressing, not just the original 800K area.
    disk = bytearray(output.read_bytes())
    folder = next(e for _, e in entries(disk) if entry_name(e) == "STANDARD.HGR")
    extra = next(e for _, e in entries(disk, word(folder, 17)) if entry_name(e) == "EXTRA")
    assert extra[0] >> 4 == 2
    index, bitmap, total = word(extra, 17) * 512, word(disk, 0x427) * 512, word(disk, 0x429)
    for i in range(16):
        old = disk[index + i] | disk[index + 256 + i] << 8
        new = total - 16 + i
        assert disk[bitmap + new // 8] & (0x80 >> (new & 7))
        disk[new * 512:(new + 1) * 512] = disk[old * 512:(old + 1) * 512]
        disk[bitmap + new // 8] &= ~(0x80 >> (new & 7))
        disk[bitmap + old // 8] |= 0x80 >> (old & 7)
        disk[index + i], disk[index + 256 + i] = new & 255, new >> 8
    output.write_bytes(disk)
    verify_allocation(output)
    return images[:2]


def exercise(args, disk, platform, fixture=False, formats=None):
    from gs2debug import Client, BP_KIND_EXEC, MEM_MAIN_RAW, MEM_MEGAII_RAW
    if os.name == "nt":
        from gs2_windows_client import Client
    sym = symbols()
    # IIgs runs this SYS in fast bank 00; only video is shadowed into Mega II.
    domain = MEM_MAIN_RAW
    video_domain = MEM_MEGAII_RAW if platform == 5 else MEM_MAIN_RAW
    prefix = f"{'formats' if formats else 'folders' if fixture else 'magic'}-p{platform}"
    output = DEMO / "validation"
    output.mkdir(exist_ok=True)
    # AF_UNIX paths have a short limit on Windows.
    socket_path = Path(tempfile.gettempdir()) / f"fgr-{os.getpid()}-{platform}.sock"
    socket_path.unlink(missing_ok=True)
    log = (output / f"{prefix}.log").open("wb")
    command = [str(args.emulator), "-p", str(platform),
               f"-ds{5 if platform == 5 else 7}d1={disk}",
               "--debug", str(socket_path), "--no-quit-confirm"]
    if args.appletini:
        config = output / f"appletini-p{platform}.gs2"
        machine = "apple2gs" if platform == 5 else "apple2e_enhanced"
        scanner = "apple2gs" if platform == 5 else "apple2e"
        config.write_text(f'gs2_version = 1\nname = "FATDOG MAGIC formats"\n'
                          f'id = "ac598a20-ea59-48cb-988c-463606fa03a{platform}"\n'
                          f'platform = "{machine}"\nscanner = "{scanner}"\n'
                          '[[cards]]\nslot = 7\ncard = "appletini"\n')
        command = [str(args.emulator), str(config), f"-ds7d1={disk}",
                   "--debug", str(socket_path), "--no-quit-confirm"]
    env = dict(os.environ)
    env["PATH"] = str(args.emulator.parent) + os.pathsep + env.get("PATH", "")
    process = subprocess.Popen(command, cwd=args.gssquared_root, stdout=log,
                               stderr=subprocess.STDOUT, env=env)
    c = Client()
    checks = []

    def byte(name):
        return c.read_mem(domain, sym[name], 1)[0]

    def run_to(label, key=None, timeout=35):
        c.bp_clear_all()
        stop = c.bp_set(kind=BP_KIND_EXEC, address=sym[label])
        error = c.bp_set(kind=BP_KIND_EXEC, address=sym["fatal"])
        # Arrow navigation must never enter the full-screen clear/draw routine.
        repaint = (c.bp_set(kind=BP_KIND_EXEC, address=sym["ui_begin"])
                   if label == "menu_wait" and key in (79, 80, 81, 82) else None)
        if key is not None:
            c.tap_key(key)
        c.continue_()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = c.wait_stopped(timeout=max(0.1, deadline - time.monotonic()))
            if repaint is not None and event.bp_id == repaint:
                raise AssertionError("Menu navigation redrew the whole screen")
            if event.bp_id == error:
                details = {name: c.read_mem(domain, sym[name], size).hex() for name, size in
                           (("capture_available", 1), ("open_params", 6), ("read_params", 8),
                            ("palette_page", 1), ("catalog_saved", 1))}
                details["stack"] = c.read_mem(domain, 0x100, 64).hex()
                raise AssertionError(f"Viewer load error: {c.get_regs().hex()} {details}")
            if event.bp_id == stop:
                return
        raise TimeoutError(label)

    def shown():
        return c.read_mem(video_domain, 0x2000, 8192)

    def check_picture(index, payload):
        assert byte("screen_state") == 2
        assert byte("image_index") == index
        assert shown() == payload, f"Displayed page differs, image {index}"

    def check_name(table, index, expected):
        record = c.read_mem(domain, sym[table] + index * 16, 16)
        assert record[1:record[0] + 1].decode("ascii") == expected, record.hex()

    try:
        deadline = time.monotonic() + 20
        while not socket_path.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError(f"No debugger socket: {output / (prefix + '.log')}")
            time.sleep(0.1)
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Emulator exited: {output / (prefix + '.log')}")
            try:
                c.connect(str(socket_path))
                c.hello()
                break
            except OSError:
                c.close()
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        # The debugger starts before the machine is constructed; breakpoints
        # installed then can disappear when the frontend creates the CPU.
        signature = (DEMO / "build/MAGIC.SYSTEM").read_bytes()[:32]
        deadline = time.monotonic() + 35
        while c.read_mem(domain, 0xA000, 32) != signature or byte("screen_state") != 1:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Boot: {c.get_regs().hex()}")
            time.sleep(0.1)
        run_to("menu_wait")
        assert byte("screen_state") == 1
        assert byte("folder_count") == (3 if formats else 18 if fixture else 2)
        check_name("folder_names", 0, "STANDARD.HGR")
        check_name("folder_labels", 0, "Standard HGR")
        if not formats:
            check_name("folder_labels", 1, "Brooks SHR-3200")
        # Verify the requested literal credits and their one-column left move.
        font = (DEMO / "assets/font7x8.bin").read_bytes()
        screen = shown()
        for band, text in ((20, "Conversions by FATDOG - Code by RIKKLES"),
                           (21, "Original artwork by its creators.")):
            for row in range(8):
                y = band * 8 + row
                offset = (y & 7) * 1024 + ((y >> 3) & 7) * 128 + (y >> 6) * 40
                assert screen[offset] == 0
                assert screen[offset + 1:offset + 1 + len(text)] == bytes(
                    font[(ord(ch) - 32) * 8 + row] for ch in text), "Credit text/position"
        save_hgr(shown(), output / f"{prefix}-menu.png")
        checks.append("Cold boot to HGR folder menu; disk names and mixed case discovered")

        if formats:
            run_to("menu_wait", 81)
            run_to("wait_picture", 40)
            assert byte("image_count") == len(formats)
            run_to("wait_picture", 44)

            def check_banks(record):
                name, payload, fmt = record
                assert byte("current_format") == fmt, name
                main = c.read_mem(domain, 0x2000, 32768)
                aux = c.read_mem(domain, 0x12000, 32768)
                if fmt == 0:
                    assert aux == payload[:32768], f"{name}: AUX SHR field"
                    if len(payload) > 32768:
                        assert main[:len(payload) - 32768] == payload[32768:], f"{name}: MAIN SHR payload"
                    else:
                        assert main[0x7DF8:0x7E00] == bytes(8), f"{name}: stale second-field metadata"
                elif fmt in (1, 2):
                    assert main[:len(payload)] == payload, f"{name}: HGR main pages"
                else:
                    assert aux[:8192] == payload[:8192], f"{name}: DHGR aux page 1"
                    assert main[:8192] == payload[8192:16384], f"{name}: DHGR main page 1"
                    if fmt == 4:
                        assert aux[8192:16384] == payload[16384:24576], f"{name}: DHGR aux page 2"
                        assert main[8192:16384] == payload[24576:32768], f"{name}: DHGR main page 2"
                if fmt in (1, 3):
                    assert main[0x207C] == 0, f"{name}: stale A2Li mode"
                if fmt:
                    switches = c.read_mem(0, 0xC01A, 6)
                    assert [b >> 7 for b in switches[:4]] == [0, 0, 0, 1], f"{name}: TEXT/MIXED/PAGE2/HIRES"
                    assert bool(switches[5] & 128) == (fmt in (3, 4)), f"{name}: 80COL"
                if platform == 5 or args.appletini:
                    assert bool(c.read_mem(0, 0xC029, 1)[0] & 128) == (fmt == 0), f"{name}: SHR switch"
                assert byte("paused") == 1

            for i, record in enumerate(formats):
                if i:
                    run_to("wait_picture", 79)
                assert byte("image_index") == i
                check_banks(record)
                # Menu/help share image memory: every type must reload cleanly.
                run_to("help_wait", 11)
                assert byte("screen_state") == 3
                run_to("wait_picture", 40)
                check_banks(record)
            run_to("menu_wait", 41)
            run_to("menu_wait", 81)
            run_to("wait_picture", 40)
            assert byte("cur_video7") == 2 and byte("current_format") == 4
            run_to("menu_wait", 41)
            run_to("menu_wait", 82)
            run_to("wait_picture", 40)
            assert byte("cur_video7") == 0
            run_to("menu_wait", 41)
            checks.append("All demo bank layouts verified byte-for-byte, including HGRi/DHGRi, SHR4, PAL256, 3200 and temporal pairs")
            checks.append("Every format survives help/reload; mixed-format transitions; Video-7 MIX folder and reset")
        elif fixture:
            # Up wraps to the final folder beyond the first screen.
            run_to("menu_wait", 82)
            assert byte("selected") == 17 and byte("folder_top") == 6
            check_name("folder_labels", 16, "HGRi")
            check_name("folder_labels", 17, "DHGRi")
            save_hgr(shown(), output / f"{prefix}-scroll.png")
            run_to("menu_wait", 81)
            assert byte("selected") == 0 and byte("folder_top") == 0
            initial_menu = shown()
            for key in (81, 82):
                for _ in range(18):
                    run_to("menu_wait", key)
                assert byte("selected") == 0 and byte("folder_top") == 0
                assert shown() == initial_menu, "Incremental scrolling left stale menu pixels"
            checks.append("Incremental arrow navigation avoids full redraw; scrolls and wraps both ways with identical final pixels")
            run_to("menu_wait", 81)
            run_to("menu_wait", 81)  # Skip the bundled Brooks folder.
            run_to("notice_wait", 40)
            assert byte("image_count") == 0 and byte("screen_state") == 4
            save_hgr(shown(), output / f"{prefix}-empty.png")
            run_to("menu_wait", 41)
            run_to("menu_wait", 81)
            run_to("wait_picture", 40)
            assert byte("image_count") == 2
            payloads = list(raw_files(DEMO / "assets/fgr2.po").values())[:2]
            check_picture(0, payloads[0])
            run_to("wait_picture", 80)
            check_picture(1, payloads[1])
            run_to("wait_picture", 79)
            check_picture(0, payloads[0])
            run_to("menu_wait", 41)
            assert byte("selected") == 3
            run_to("menu_wait", 82)
            run_to("menu_wait", 82)
            run_to("menu_wait", 82)
            run_to("wait_picture", 40)
            assert byte("image_count") == 33
            run_to("wait_picture", 80)
            check_picture(32, payloads[0])
            run_to("menu_wait", 41)
            checks.append("Post-build folders, scrolling/wrap, empty folder, file filtering, isolated slideshow, reads through volume block 65534")
        else:
            run_to("wait_picture", 40)
            assert byte("image_count") == 32
            images = [payload for name, payload in raw_files(disk).items() if name.startswith("STANDARD.HGR/")]
            check_picture(0, images[0])
            # Pause before walking every image, crossing all three directory blocks.
            run_to("wait_picture", 44)
            assert byte("paused") == 1
            for i in range(1, 32):
                run_to("wait_picture", 79)
                check_picture(i, images[i])
                assert byte("paused") == 1
            run_to("wait_picture", 79)
            check_picture(0, images[0])
            run_to("wait_picture", 80)
            check_picture(31, images[31])
            run_to("wait_picture", 21)   # R
            check_picture(0, images[0])
            run_to("help_wait", 11)      # H
            assert byte("screen_state") == 3
            save_hgr(shown(), output / f"{prefix}-help.png")
            run_to("wait_picture", 40)
            check_picture(0, images[0])
            assert byte("paused") == 1
            # Wait a real 480-frame interval in the emulated machine.
            run_to("wait_picture", 44)
            assert int.from_bytes(c.read_mem(domain, sym["ticks"], 2), "little") == 480
            start_cycles = int.from_bytes(c.get_regs()[:8], "little")
            start_time = time.monotonic()
            run_to("load_image", timeout=20)
            elapsed_seconds = time.monotonic() - start_time
            elapsed = int.from_bytes(c.get_regs()[:8], "little") - start_cycles
            assert byte("image_index") == 1
            # Appletini starts at 33.3 MHz, but IIgs I/O slows individual cycles.
            # Its VBL interval is measured by elapsed time, independently of CPU speed.
            if args.appletini:
                assert 7 < elapsed_seconds < 12, elapsed_seconds
            else:
                assert 7_500_000 < elapsed < (24_000_000 if platform == 5 else 9_500_000), elapsed
            run_to("wait_picture")
            check_picture(1, images[1])
            run_to("help_wait", 11)
            run_to("menu_wait", 41)
            assert byte("screen_state") == 1
            run_to("wait_picture", 40)
            check_picture(0, images[0])
            run_to("menu_wait", 41)
            checks.append("All 32 displayed images byte-identical; next/previous wrap; R; pause survives navigation")
            checks.append(f"HGR help reloads intact image; automatic advance after {elapsed} CPU cycles / {elapsed_seconds:.2f} seconds; Esc returns to menu")
            run_to("menu_wait", 81)
            run_to("wait_picture", 40)
            assert byte("image_count") == 20
            run_to("wait_picture", 44)
            brooks_images = [(None, name, payload) for name, payload in raw_files(disk).items()
                             if name.startswith("BROOKS.SHR.3200/")]

            def check_brooks(index):
                payload = brooks_images[index][2]
                assert byte("image_index") == index and byte("current_format") == 0
                assert byte("paused") == 1
                assert c.read_mem(domain, 0x12000, 32768) == payload[:32768], "Brooks AUX field"
                if len(payload) == 39168:
                    assert c.read_mem(domain, 0x2000, 6400) == payload[32768:], "Brooks MAIN palettes"
                else:
                    assert c.read_mem(domain, 0x2000, 32768) == payload[39168:71936], "Brooks MAIN field"
                    first_bank = payload[0x7DF9] == 1
                    first_addr = int.from_bytes(payload[0x7DFA:0x7DFC], "little")
                    second_bank = payload[39168 + 0x7DF9] == 1
                    second_addr = int.from_bytes(payload[39168 + 0x7DFA:39168 + 0x7DFC], "little")
                    assert c.read_mem(domain, first_bank * 65536 + first_addr, 6400) == payload[32768:39168], "Brooks first palettes"
                    assert c.read_mem(domain, second_bank * 65536 + second_addr, 6400) == (payload[71936:] if len(payload) == 78336 else payload[32768:39168]), "Brooks second palettes"
                if platform == 5 or args.appletini:
                    assert c.read_mem(0, 0xC029, 1)[0] & 128
                assert not c.read_mem(0, 0xC01C, 1)[0] & 128, "PAGE1 stays selected"

            for i, (_, _, payload) in enumerate(brooks_images):
                if i:
                    run_to("wait_picture", 79)
                check_brooks(i)
                if i == 0 or len(payload) == 78336:
                    run_to("help_wait", 11)
                    run_to("wait_picture", 40)
                    check_brooks(i)
            run_to("wait_picture", 79)
            check_brooks(0)
            run_to("wait_picture", 80)
            check_brooks(19)
            run_to("wait_picture", 21)
            check_brooks(0)
            run_to("menu_wait", 41)
            run_to("menu_wait", 82)
            run_to("wait_picture", 40)
            check_picture(0, images[0])
            run_to("menu_wait", 41)
            checks.append("All 20 Brooks images and line palettes verified byte-for-byte; help/reload, wrap, R and return to HGR")
        run_to("quit", 41)
        c.bp_clear_all()
        c.continue_()
        deadline = time.monotonic() + 5
        while True:
            lines = c.video_text().as_lines()
            if any("BASIC" in line.upper() or "FATDOG" in line.upper() for line in lines):
                break
            if time.monotonic() >= deadline:
                raise AssertionError(f"ProDOS quit screen: {lines}")
            time.sleep(0.1)
        checks.append("Esc from menu exits to ProDOS")
        return {"platform": platform, "disk_sha256": build.digest(disk.read_bytes()), "checks": checks}
    finally:
        try:
            c.quit()
        except Exception:
            pass
        c.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
        socket_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gssquared-root", type=Path,
                        default=Path(os.environ.get("GSSQUARED_ROOT", str(DEMO.parents[2] / "gssquared"))))
    parser.add_argument("--emulator", type=Path)
    parser.add_argument("--image", type=Path, default=DEMO / "dist/FATDOG_MAGIC.po")
    parser.add_argument("--platform", type=int, choices=(3, 5), action="append")
    parser.add_argument("--skip-fixture", action="store_true")
    parser.add_argument("--formats-from", type=Path,
                        help="appletini-software checkout or Appletini demo project/assets "
                             "(legacy appletini-one also supported); test real demo images "
                             "on a separate disk")
    parser.add_argument("--formats-only", action="store_true")
    parser.add_argument("--appletini", action="store_true",
                        help="use a GSSquared build with Appletini video/card support")
    args = parser.parse_args()
    args.gssquared_root = args.gssquared_root.resolve()
    args.emulator = (args.emulator or args.gssquared_root / "build/GSSquared.exe").resolve()
    sys.path.insert(0, str(args.gssquared_root / "clients/python/src"))
    disk = args.image.resolve()
    results = []
    if not args.formats_only:
        for platform in args.platform or (3, 5):
            results.append(exercise(args, disk, platform))
            print(f"PASS: FATDOG MAGIC, 32 HGR + 20 Brooks images, platform {platform}", flush=True)
    if not args.skip_fixture and not args.formats_only:
        fixture = DEMO / "validation/folders.po"
        make_fixture(disk, fixture)
        results.append(exercise(args, fixture, 3, fixture=True))
        print("PASS: post-build folder discovery and filtering", flush=True)
    if args.formats_from:
        from format_fixture import make_format_fixture
        fixture = DEMO / "validation/formats.po"
        formats = make_format_fixture(args.formats_from, disk, fixture)
        for platform in args.platform or (3, 5):
            results.append(exercise(args, fixture, platform, formats=formats))
            print(f"PASS: all demo image layouts, platform {platform}", flush=True)
    assert results, "No tests selected; --formats-only requires --formats-from"
    report = {"result": "PASS", "emulator": str(args.emulator), "appletini": args.appletini,
              "viewer_sha256": build.digest((DEMO / "build/MAGIC.SYSTEM").read_bytes()),
              "runs": results, "physical_hardware_tested": False}
    (DEMO / "validation/runtime.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
