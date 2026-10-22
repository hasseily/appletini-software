"""Read-only worktree fingerprint: capture before reference use, compare after.

This is an audit utility, never a build input or dependency on another checkout.
Ignored build products and .git internals are outside the fingerprint. Submodule
gitlinks and HEAD are recorded; accessible submodule worktrees are hashed too.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def git(root, *args):
    return subprocess.check_output(["git", "-c", "submodule.recurse=false", "-C", str(root), *args])


def snapshot(root):
    paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
    files = {}
    for raw in paths:
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root / name
        if path.is_file():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir():
            # Avoid .git metadata even for an initialized submodule.
            for child in sorted(path.rglob("*")):
                if child.is_file() and ".git" not in child.relative_to(path).parts:
                    files[child.relative_to(root).as_posix()] = hashlib.sha256(child.read_bytes()).hexdigest()
        else:
            files[name] = "missing"
    return {
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "branch": git(root, "branch", "--show-current").decode().strip(),
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=all").decode(),
        "index": hashlib.sha256(git(root, "ls-files", "--stage", "-z")).hexdigest(),
        "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("record", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = snapshot(args.root.resolve())
    if args.check:
        previous = json.loads(args.record.read_text())
        if previous != current:
            changed = sorted(k for k in previous["files"].keys() | current["files"].keys()
                             if previous["files"].get(k) != current["files"].get(k))
            raise SystemExit("Reference changed: " + repr(changed) + "; inspect HEAD/index/status too")
        print("Reference unchanged:", current["head"], len(current["files"]), "files")
    else:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print("Recorded reference:", current["head"], len(current["files"]), "files")


if __name__ == "__main__":
    main()
