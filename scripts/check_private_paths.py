#!/usr/bin/env python3
"""Fails when the tree holds a real person's home directory: a path that tells who wrote it.

    python3 scripts/check_private_paths.py [ROOT]      (default: the repository this script belongs to)

Prints `file:line: text` for each hit and exits 1; prints nothing and exits 0 when the tree is clean.
Standard library only; the same on Linux, macOS and Windows (the CI runs it on all three).

What counts:
  /home/<name>/                       Linux (lowercase names, as the grep this replaced)
  <drive>:\\Users\\<name>\\ or /      Windows, in any spelling (also doubled backslashes, as in JSON)
  /mnt/<drive>/Users/<name>/          the same profile seen from WSL
  /Users/<name>/                      macOS
What does not: the system profiles (Public, Default, Default User, All Users, Shared, Guest), a placeholder
(<you>, %USERNAME%, $env...), `..` or `.` standing where a name would, a word that only ends in a letter and a
colon before /users (`GET:/users/42`, `https://users/x`), and any directory that is not under Users.
Left alone: .git, vendor (third-party text, pinned by skills/vendor/LOCK), caches, and binary files. Text in
UTF-16 (a byte-order mark first, as Windows tools write it) is read as text.
"""
import os
import re
import sys

SKIP_DIRS = {".git", "vendor", "__pycache__", "node_modules", ".agenfk", ".claude"}
SYSTEM = r"(?:public|default|default user|all users|shared|guest)"
NOT_A_NAME = r"(?!\.+[\\/]|\.+$)"                 # `..` is a path segment, not a person
NAME_START = r"[^\\/<>{}$%*\"'`\s]"                # a name that starts like this is a placeholder, not a person
PATTERNS = [
    re.compile(r"/home/[a-z]+/"),
    re.compile(r"(?<![A-Za-z0-9])[a-z]:[\\/]+users[\\/]+(?!" + SYSTEM + r"(?:[\\/]|$))" + NOT_A_NAME
               + NAME_START + r"[^\\/]*(?:[\\/]|$)", re.I),
    re.compile(r"/mnt/[a-z]/users/(?!" + SYSTEM + r"(?:/|$))" + NOT_A_NAME + NAME_START + r"[^/]*(?:/|$)", re.I),
    # a name starts with a letter here; not after `:/`, which is the second slash of `https://users/...`
    re.compile(r"(?<![A-Za-z0-9_.~:-])(?<!:/)/users/(?!" + SYSTEM + r"(?:/|$))[A-Za-z][^/\s<>{}$%*\"'`]*/", re.I),
]


def read_text(data):
    """The text of a file, or None when it is binary (fonts, images)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if b"\0" in data:
        return None
    return data.decode("utf-8", "replace")


def scan(root):
    hits = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            path = os.path.join(folder, name)
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            text = read_text(data)
            if text is None:
                continue
            for number, line in enumerate(text.split("\n"), 1):      # the same line numbers as grep and editors
                if any(p.search(line) for p in PATTERNS):
                    hits.append(f"{os.path.relpath(path, root)}:{number}: {line.strip()[:200]}")
    return hits


def main(argv):
    root = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hits = scan(root)
    for hit in hits:
        print(hit)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
