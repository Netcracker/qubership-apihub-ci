#!/usr/bin/env python3
"""Zip the named source files, preserving each path as its archive entry name."""

import os
import sys
import zipfile

if len(sys.argv) < 3:
    raise SystemExit("usage: zip_sources.py <out.zip> <file>...")

out, files = sys.argv[1], sys.argv[2:]

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        entry = f.replace(os.sep, "/")
        if entry.startswith("/") or ":" in entry.split("/")[0]:
            raise SystemExit(
                "absolute path %r — run from the directory the fileIds are relative to" % f
            )
        z.write(f, entry)
