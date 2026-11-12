#!/usr/bin/env python3
"""Build the shareable zip of the local dashboard.

    python3 tools/make_pack.py            writes ../Economic-Machine-Monitor-Local.zip

The zip holds everything needed to run it on another computer: start files, the bot, the page,
the latest data, the tests and the guides. Git history and caches are left out.
"""
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "Economic-Machine-Monitor-Local.zip"
TOP = "Economic-Machine-Monitor"
SKIP_DIRS = {".git", "__pycache__", ".claude", ".github"}
SKIP_FILES = {".DS_Store", ".gitignore"}
EXECUTABLE = {".command", ".py"}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    files = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and not (set(p.relative_to(ROOT).parts[:-1]) & SKIP_DIRS)
             and p.name not in SKIP_FILES and p.suffix != ".pyc"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(f"{TOP}/{p.relative_to(ROOT).as_posix()}", time.localtime(p.stat().st_mtime)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if p.suffix in EXECUTABLE else 0o644) << 16   # keep the Mac start file double-clickable
            z.writestr(info, p.read_bytes())
    print(f"{out}  ·  {len(files)} files  ·  {out.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
