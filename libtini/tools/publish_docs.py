#!/usr/bin/env python3
"""Copy the HTML reference in docs/ to a web site folder.

Links inside docs/ become absolute paths under --base, without .html, for a
host that serves clean URLs. Links to other repository files become GitHub
links. Example, for appletini.org/libtini:

  python tools/publish_docs.py ../../appletini-one-website/public/libtini --base /libtini --home /
"""
import argparse
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REPOSITORY = ROOT.parent
GITHUB = "https://github.com/hasseily/appletini-software"
LINK = re.compile(r'\b(href|src)="([^"]*)"')
BRAND = '<a class="brand" href="'


def site_url(target, base):
    """The published URL of a file inside docs/."""
    path = target.relative_to(DOCS).as_posix()
    if path.endswith(".html"):
        path = path[:-len(".html")]
        if path == "index":
            path = ""
        elif path.endswith("/index"):
            path = path[:-len("/index")]
    return base.rstrip("/") + ("/" + path if path else "") or "/"


def github_url(target, branch):
    kind = "tree" if target.is_dir() else "blob"
    return "%s/%s/%s/%s" % (GITHUB, kind, branch, target.relative_to(REPOSITORY).as_posix())


def rewrite(page, text, base, branch):
    def replace(match):
        attribute, value = match.groups()
        if not value or value.startswith("#") or re.match(r"[a-z][a-z0-9+.-]*:", value, re.I):
            return match.group(0)
        path, _, fragment = value.partition("#")
        target = (page.parent / path).resolve()
        if target.is_relative_to(DOCS):
            url = site_url(target, base)
        elif target.is_relative_to(REPOSITORY) and target.exists():
            url = github_url(target, branch)
        else:
            raise SystemExit("%s: link leaves the repository: %s" % (page.relative_to(ROOT), value))
        return '%s="%s%s"' % (attribute, url, "#" + fragment if fragment else "")
    return LINK.sub(replace, text)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destination", type=Path, help="the site folder for the reference")
    parser.add_argument("--base", default="/libtini", help="URL path of the destination folder")
    parser.add_argument("--home", help="URL of the site home; adds a link under the libtini name")
    parser.add_argument("--branch", default="main", help="GitHub branch for links to other files")
    args = parser.parse_args()
    if not args.base.startswith("/"):
        raise SystemExit("--base must be an absolute URL path, such as /libtini")
    destination = args.destination.resolve()
    if destination.is_relative_to(ROOT):
        raise SystemExit("The destination must be outside libtini")
    if destination.exists() and any(destination.iterdir()):
        # Replace only an earlier copy of this reference.
        if not (destination / "index.html").is_file() or not (destination / "assets/site.js").is_file():
            raise SystemExit("Destination is not empty and is not a libtini reference: " + str(destination))
        shutil.rmtree(destination)
    pages = 0
    for source in sorted(DOCS.rglob("*")):
        if not source.is_file():
            continue
        target = destination / source.relative_to(DOCS)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix != ".html":
            shutil.copyfile(source, target)
            continue
        text = rewrite(source, source.read_text(encoding="utf-8"), args.base, args.branch)
        if args.home:
            start = text.index(BRAND)
            end = text.index("</a>", start) + len("</a>")
            text = text[:end] + '<a class="brand-sub" href="%s">appletini.org</a>' % args.home + text[end:]
        target.write_bytes(text.encode("utf-8"))
        pages += 1
    print("%d pages to %s, served at %s" % (pages, destination, args.base))


if __name__ == "__main__":
    main()
