#!/usr/bin/env python3
"""Print the file entries of a zip archive, one per line, for use as config.files[].fileId."""

import sys
import zipfile

if len(sys.argv) != 2:
    raise SystemExit("usage: list_zip.py <archive.zip>")

# Directory entries end in a slash and are filtered out: the backend ignores
# them inside the archive but rejects one listed as a fileId.
for name in zipfile.ZipFile(sys.argv[1]).namelist():
    if not name.endswith("/"):
        print(name)
