#!/usr/bin/env python3
"""Compile authored English words/overrides to SSI-263 phrases and number IDs.

This deliberately small vocabulary rejects unknown words. Preview prints the
phoneme sequence and estimated duration; it does not impersonate SSI audio.
"""
import argparse
import json
from pathlib import Path
import re

PHONEMES = {
    "PA":0x00, "IY":0x01, "Y":0x03, "AY":0x05, "IH":0x07,
    "EH":0x0A, "AE":0x0C, "AA":0x0F, "AO":0x10, "OW":0x11,
    "OY":0x12, "UW":0x14, "UH":0x18, "ER":0x1C, "R":0x1D,
    "L":0x20, "W":0x23, "B":0x24, "D":0x25, "G":0x26,
    "P":0x27, "T":0x28, "K":0x29, "CH":0x2A, "J":0x2B,
    "TH":0x2C, "DH":0x2D, "Z":0x2F, "S":0x30, "ZH":0x31,
    "SH":0x32, "V":0x33, "F":0x34, "HH":0x35, "M":0x37,
    "N":0x38, "NG":0x39,
}
_WORDS = {
    "ZERO":"Z IY R OW", "ONE":"W UH N", "TWO":"T UW", "THREE":"TH R IY",
    "FOUR":"F AO R", "FIVE":"F AY V", "SIX":"S IH K S", "SEVEN":"S EH V UH N",
    "EIGHT":"AY T", "NINE":"N AY N", "TEN":"T EH N", "ELEVEN":"IH L EH V UH N",
    "TWELVE":"T W EH L V", "THIRTEEN":"TH ER T IY N", "FOURTEEN":"F AO R T IY N",
    "FIFTEEN":"F IH F T IY N", "SIXTEEN":"S IH K S T IY N", "SEVENTEEN":"S EH V UH N T IY N",
    "EIGHTEEN":"AY T IY N", "NINETEEN":"N AY N T IY N", "TWENTY":"T W EH N T IY",
    "THIRTY":"TH ER T IY", "FORTY":"F AO R T IY", "FIFTY":"F IH F T IY",
    "SIXTY":"S IH K S T IY", "SEVENTY":"S EH V UH N T IY", "EIGHTY":"AY T IY",
    "NINETY":"N AY N T IY", "HUNDRED":"HH UH N D R EH D", "THOUSAND":"TH AW Z UH N D",
    "READY":"R EH D IY", "WELCOME":"W EH L K UH M", "EXTRA":"EH K S T R UH",
    "LIFE":"L AY F", "GAME":"K AY M", "OVER":"OW V ER", "PUMP":"P UH M P",
    "FIRST":"F ER S T", "KEEP":"K IY P", "THE":"DH UH", "RELAY":"R IY L AY",
    "ALIVE":"UH L AY V", "EXCHANGE":"EH K S CH AY N J", "THEN":"DH EH N",
    "TOWER":"T AO ER", "HOLD":"HH OW L D", "TRAM":"T R AE M", "SIGNAL":"S IH G N UH L",
    "OPEN":"OW P UH N", "LOCK":"L AA K", "GATE":"G AY T", "POWER":"P AO ER",
    "BATTERY":"B AE T ER IY", "YARD":"Y AA R D", "LIFT":"L IH F T", "LIGHT":"L AY T",
    "PRISM":"P R IH Z UH M", "RETURNS":"R IH T ER N Z", "FINAL":"F AY N UH L",
    "END":"EH N D", "CITY":"S IH T IY", "SCORE":"S K AO R", "RESTORED":"R IH S T AO R D",
    "ECHO":"EH K OW", "ECHOES":"EH K OW Z", "RECORD":"R IH K AO R D",
    "AND":"AE N D", "YOU":"Y UW", "TO":"T UW", "IS":"IH Z", "IN":"IH N",
    "AT":"AE T", "A":"UH", "ALL":"AO L", "LAST":"L AE S T", "STOP":"S T AA P",
    "GO":"G OW", "HOME":"HH OW M", "GOOD":"G UH D", "WORK":"W ER K",
}
# AW is intentionally a shared broad vowel approximation on this small table.
PHONEMES["AW"] = 0x10
LEXICON = {word: value.split() for word, value in _WORDS.items()}
NUMBER_WORDS = list(_WORDS)[:30]
VOWELS = {"IY","AY","IH","EH","AE","AA","AO","OW","OY","UW","UH","ER","AW"}
STOPS = {"B","D","G","P","T","K","PA"}


def number_words(value):
    if not isinstance(value, int) or not 0 <= value <= 9999:
        raise ValueError("numbers must be in 0..9999")
    result = []
    if value >= 1000:
        result += [NUMBER_WORDS[value // 1000], "THOUSAND"]
        value %= 1000
    if value >= 100:
        result += [NUMBER_WORDS[value // 100], "HUNDRED"]
        value %= 100
    if value >= 20:
        result += [NUMBER_WORDS[18 + value // 10]]
        if value % 10:
            result += [NUMBER_WORDS[value % 10]]
    elif value or not result:
        result += [NUMBER_WORDS[value]]
    return result


def compile_text(text, overrides=None):
    lexicon = dict(LEXICON)
    for word, phones in (overrides or {}).items():
        if isinstance(phones, str): phones = phones.split()
        if not phones or any(phone not in PHONEMES for phone in phones):
            raise ValueError("invalid pronunciation for " + word)
        lexicon[word.upper()] = phones
    tokens = re.findall(r"[A-Z]+|[0-9]+|[^\sA-Z0-9]", text.upper())
    words = []
    for token in tokens:
        if token.isdecimal(): words.extend(number_words(int(token)))
        elif token.isalpha(): words.append(token)
        elif token not in ".,!?;:-'": raise ValueError("unsupported text character " + token)
    phones = []
    for word in words:
        if word not in lexicon:
            raise ValueError("unknown word " + word + "; add a pronunciations override")
        if phones: phones.append("PA")
        phones.extend(lexicon[word])
    if not phones: raise ValueError("empty phrase")
    data = [PHONEMES[p] | (0 if p in VOWELS else 128 if p in STOPS else 64) for p in phones]
    if len(data) > 255: raise ValueError("phrase exceeds 255 phonemes")
    return data, phones


def compile_manifest(manifest, symbol="ti_speech_assets", include_numbers=True):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol): raise ValueError("invalid C symbol")
    phrases = manifest.get("phrases", {})
    if not isinstance(phrases, dict) or not phrases: raise ValueError("phrases must be a nonempty object")
    maximum = 225 if include_numbers else 255
    if len(phrases) > maximum: raise ValueError("too many authored phrases")
    records = []
    for name, text in phrases.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name): raise ValueError("invalid phrase identifier " + name)
        data, phones = compile_text(text, manifest.get("pronunciations"))
        records.append((name, text, data, phones))
    for i, word in enumerate(NUMBER_WORDS if include_numbers else []):
        data, phones = compile_text(word, manifest.get("pronunciations"))
        records.append(("TI_NUMBER_" + str(i), word, data, phones))
    lines = ["/* Generated by tools/speech.py; edit the JSON source. */", "#include \"libtini/audio.h\""]
    for i, (name, _, data, _) in enumerate(records):
        if not name.startswith("TI_NUMBER_"): lines.append(f"#define {name} {i}")
        lines.append(f"static const uint8_t {symbol}_p{i}[] = {{" + ",".join(map(str,data)) + "};")
    lines.append(f"static const ti_phrase {symbol}_phrases[] = {{")
    lines.extend(f"    {{{symbol}_p{i},{len(record[2])}}}," for i, record in enumerate(records))
    lines.append("};")
    if include_numbers:
        lines.append(f"static const uint8_t {symbol}_numbers[] = {{" +
                     ",".join(str(len(phrases)+i) for i in range(30)) + "};")
    numeric = symbol + "_numbers" if include_numbers else "0"
    lines.append(f"static const ti_speech_bank {symbol} = {{{symbol}_phrases,{len(records)},{numeric}}};")
    return "\n".join(lines) + "\n", records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--symbol", default="ti_speech_assets")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--no-numbers", action="store_true", help="omit runtime number vocabulary from this phrase bank")
    args = parser.parse_args()
    output, records = compile_manifest(json.loads(args.manifest.read_text()), args.symbol, not args.no_numbers)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(output)
    if args.preview:
        for name, text, data, phones in records:
            estimated = sum(96 if not code & 192 else 72 if code & 192 == 64 else 48 for code in data)
            print(f"{name}: {text}\n  {' '.join(phones)} ({len(data)} bytes, about {estimated} ms at rate 10)")
    if not args.output and not args.preview: parser.error("choose --output or --preview")


if __name__ == "__main__":
    main()
