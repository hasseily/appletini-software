"""The game's 13 songs for SONGS.1 (tools/native/pldisk.py): the WAD's MUS
lumps converted to AY song files by mus2ay.py, in upstream's song order
(mus.UPSTREAM_SONGS)."""

from typing import List, Tuple

from sound import mus, mus2ay


def have_wad() -> bool:
    return mus.WAD_PATH.exists()


def songs(wad_path=mus.WAD_PATH) -> List[Tuple[str, bytes]]:
    """(name, song file) of the 13 songs, converted from the WAD now."""
    wad = mus.Wad.open(wad_path)
    instruments = mus2ay.load_instruments(wad)
    return [(name, mus2ay.convert(wad.song(name), instruments)[0].to_bytes())
            for name in mus.UPSTREAM_SONGS]
