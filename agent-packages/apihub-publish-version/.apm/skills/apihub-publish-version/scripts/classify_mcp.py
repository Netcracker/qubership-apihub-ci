#!/usr/bin/env python3
"""Print one line per MCP contract document, and nothing for anything else.

Reads either loose files or the entries inside an archive:

    classify_mcp.py initialize.json tools.json orders-api.yaml
    classify_mcp.py --zip sources.zip

Use --zip whenever the user supplied a ready-made archive: its entries are not
files on disk, so naming them as paths would find nothing.

Mirrors detectMcpDocumentType from qubership-apihub-api-processor
(src/apitypes/mcp/mcp.parser.ts) — same checks, same order. Printing only the
classification keeps source file contents out of the agent's context.

Output on stdout: <name>\ttab\t<kind>\ttab\t<detail>, one line per MCP document.
Anything unreadable is reported on stderr, so a file that cannot be opened is
never mistaken for a file that simply is not an MCP document.
"""

import json
import sys
import zipfile


def detect(d):
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("result"), dict):          # unwrap JSON-RPC envelope
        d = d["result"]
    if isinstance(d.get("capabilities"), dict) and isinstance(d.get("serverInfo"), dict):
        caps = ", ".join(sorted(d["capabilities"]))
        return "mcp-init", "server=%s  declares=%s" % (d["serverInfo"].get("name", ""), caps)
    for key, kind in (("tools", "mcp-tools"),
                      ("resources", "mcp-resources"),
                      ("prompts", "mcp-prompts")):
        if isinstance(d.get(key), list):
            names = [e.get("name") or e.get("uri") or "?"
                     for e in d[key][:5] if isinstance(e, dict)]
            return kind, ", ".join(names)
    return None


def report(name, raw):
    try:
        d = json.loads(raw)
    except Exception as exc:
        print("cannot parse %s: %s" % (name, exc), file=sys.stderr)
        return
    r = detect(d)
    if r:
        print("%s\t%s\t%s" % (name, r[0], r[1]))


def is_json(name):
    return name.lower().endswith(".json")


args = sys.argv[1:]

if args[:1] == ["--zip"]:
    if len(args) != 2:
        raise SystemExit("usage: classify_mcp.py --zip <archive.zip>")
    try:
        archive = zipfile.ZipFile(args[1])
    except Exception as exc:
        raise SystemExit("cannot open archive %s: %s" % (args[1], exc))
    with archive as z:
        for entry in z.namelist():
            if entry.endswith("/") or not is_json(entry):
                continue
            report(entry, z.read(entry))
elif args:
    for path in args:
        if not is_json(path):
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            # Loud, because silence here reads as "not an MCP document" and the
            # missing mcpEndpoint would only surface as a failed build later.
            print("cannot read %s: %s" % (path, exc), file=sys.stderr)
            continue
        report(path, raw)
else:
    raise SystemExit("usage: classify_mcp.py <file.json>... | --zip <archive.zip>")
