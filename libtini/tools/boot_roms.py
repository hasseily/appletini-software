"""Shared boot inputs for browser builds and benchmarks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "build-inputs/native-roms"
FILES = ("Apple2e_Enhanced.rom", "smartport_a2retronet_style_c700.mem",
         "smartport_a2retronet_style_c800.mem", "provenance.json", "README.md",
         "NOTICES.txt", ".gitattributes")


def add_arguments(parser):
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument("--boot-roms", type=Path, default=DEFAULT, metavar="DIR",
                        help="boot through the //e and slot-7 ROMs in DIR "
                             "(default: libtini/build-inputs/native-roms)")
    launch.add_argument("--direct-launch", action="store_const", const=None,
                        dest="boot_roms", help="use the ProDOS MLI stand-in without ROM boot")
