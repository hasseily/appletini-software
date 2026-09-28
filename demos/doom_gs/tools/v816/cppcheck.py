#!/usr/bin/env python3
"""Cross-check of tools/v816/cpp.py against "clang -E".

Usage:  python3 tools/v816/cppcheck.py

For each source of the default build, the output of cpp.py must equal
the output of

    clang -E -P -x assembler-with-cpp [-I ...] [-D ...] file

apart from white space: runs of blanks count as one blank, and empty
lines do not count. clang is a check here, not a part of the build; the
port's own preprocessor is the one that is used.

In assembler-with-cpp mode clang leaves "#" and "##" alone outside
#define bodies and does not take "$" as a part of an identifier, which
is what cpp.py does. The exit status is 1 when a file differs, 2 when
there is no clang.
"""

import difflib
import re
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v816 import cpp, frontend  # noqa: E402


class ClangError(Exception):
    """clang did not preprocess the file."""


def clang_path():
    """The path of clang, or None when there is none."""
    return shutil.which('clang')


def normalise(text):
    """The lines of `text` that are not empty, with each run of white
    space as one blank and none at the ends."""
    lines = (re.sub(r'\s+', ' ', line).strip() for line in text.split('\n'))
    return [line for line in lines if line]


def clang_output(source, clang):
    """What clang makes of the frontend.Source `source`."""
    command = [clang, '-E', '-P', '-x', 'assembler-with-cpp']
    for directory in source.include_paths:
        command += ['-I', str(directory)]
    for name, value in source.defines.items():
        command += ['-D', '%s=%s' % (name, value)]
    result = subprocess.run(
        command + [str(source.path)], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True,
        errors='surrogateescape')
    if result.returncode:
        raise ClangError(result.stderr)
    return result.stdout


def differences(source, clang):
    """The lines of a unified diff from clang's output to that of
    cpp.py; empty when they agree."""
    preprocessor = cpp.Preprocessor(source.include_paths, source.defines)
    ours = normalise(cpp.render(preprocessor.process_file(source.path)))
    theirs = normalise(clang_output(source, clang))
    return list(difflib.unified_diff(theirs, ours, 'clang', 'cpp.py',
                                     lineterm='', n=0))


def main():
    clang = clang_path()
    if clang is None:
        print('cppcheck: there is no clang on this machine',
              file=sys.stderr)
        return 2
    different = 0
    sources = frontend.sources()
    for source in sources:
        diff = differences(source, clang)
        if diff:
            different += 1
            print('%s: differs' % source.path.name)
            print('\n'.join(diff[:20]))
    print('%d of %d files equal' % (len(sources) - different, len(sources)))
    return 1 if different else 0


if __name__ == '__main__':
    sys.exit(main())
