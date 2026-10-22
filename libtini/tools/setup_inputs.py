#!/usr/bin/env python3
"""Install the separately distributed ProDOS input once; builds stay offline."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / "tools/prodos-input.json").read_text())
    destination = ROOT / lock["path"]
    if destination.exists():
        data = destination.read_bytes()
    else:
        print("Installing", lock["version"], "from", lock["release"])
        with urllib.request.urlopen(lock["url"], timeout=60) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != lock["sha256"]:
        raise SystemExit("ProDOS input SHA-256 mismatch: " + digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(destination.relative_to(ROOT), digest)


if __name__ == "__main__":
    main()
