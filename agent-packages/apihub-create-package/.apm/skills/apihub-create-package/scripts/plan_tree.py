#!/usr/bin/env python3
"""Plan an APIHUB group/package hierarchy from a local directory tree.

    python3 plan_tree.py <root-dir> <parent-id> [--out DIR] [--alias PATH=ALIAS]...
    python3 plan_tree.py <root-dir> <parent-id> [same flags] --status

The root directory itself is not a node — only what is inside it. Every folder
below it becomes one node, classified by what it contains:

    only subfolders  -> group
    only files       -> package
    both             -> conflict (blocks the run; nothing is created)
    neither          -> skip     (noted, not an error)

Writes <out>/plan.tsv (creatable nodes only, parents before children) and one
<out>/body-<idx>.json per node, so the JSON escaping of a folder name happens
here rather than in a shell string. Prints the table a human confirms before
anything is created.

Re-run with --status to fold <out>/status.tsv (written by check_ids.sh) into a
status column. The walk is deterministic, so the same arguments reproduce the
same plan — and if they do not, the id sets no longer match and the run stops
rather than showing a table that does not describe what would be created.
Repeat every --alias override on the --status run for that reason.

Exit codes:
  0  the plan is creatable — every node is new or an existing node of the same kind
  1  something needs a human: a mixed-content folder, an alias that cannot be
     derived, or (with --status) a kind conflict, a redirect, or a stale check
  2  cannot run as given: bad arguments, no such directory, an --alias path that
     matches no folder, or a folder name containing a tab or newline
"""

import argparse
import glob
import json
import os
import re
import sys

# Kinds this skill creates. workspace and dashboard are deliberately absent.
KINDS = ("group", "package")


def die(message):
    """Exit 2 — cannot run as given. Kept distinct from 1, which means a human
    has to decide something about an otherwise well-formed plan."""
    sys.stderr.write(message + "\n")
    raise SystemExit(2)


def derive_alias(name):
    """Collapse anything outside [a-zA-Z0-9_-] to '-', trim.

    The character class is already URL-safe and excludes '.', which would
    otherwise read as a level separator in the packageId the server computes.

    Case is left alone. The server accepts any URL-safe alias, so folding it
    buys nothing and loses something: a folder named BACKEND would derive
    'backend', whose id then fails to match an existing MYWS.BACKEND on the
    existence check and reads as 'new'. It also matches how an explicit
    --alias is treated, which is sent exactly as typed.
    """
    alias = re.sub(r"[^a-zA-Z0-9_-]+", "-", name)
    return alias.strip("-")


def disambiguate(alias, taken):
    """Return an unused sibling alias, appending -2, -3, ... deterministically.

    Two folders under one parent that derive the same alias would compute the
    same packageId, so one would silently reuse the other. Suffix instead — the
    preview shows the result either way.
    """
    if alias not in taken:
        return alias
    n = 2
    while True:
        candidate = "%s-%d" % (alias, n)
        if candidate not in taken:
            return candidate
        n += 1


def scan(dirpath):
    """Split one directory into (subdirs, files, hidden, symlinked-dirs).

    Dot-entries are ignored: a stray .DS_Store or .git would otherwise turn every
    leaf folder into a mixed-content conflict. Directory symlinks are not
    followed, which keeps the walk finite. Both are counted so the notes can name
    what was left out.
    """
    subdirs, files, hidden, links = [], [], [], []
    for entry in sorted(os.scandir(dirpath), key=lambda e: e.name):
        if entry.name.startswith("."):
            hidden.append(entry.name)
        elif entry.is_symlink() and os.path.isdir(entry.path):
            links.append(entry.name)
        elif entry.is_dir(follow_symlinks=False):
            subdirs.append(entry)
        else:
            files.append(entry.name)
    return subdirs, files, hidden, links


class Node(object):
    def __init__(self, depth, relpath, name, kind):
        self.depth = depth
        self.relpath = relpath
        self.name = name
        self.kind = kind            # group | package | conflict | skip
        self.idx = 0                # 1-based, matches body-<idx>.json; 0 when not creatable
        self.alias = ""
        self.package_id = ""
        self.parent_id = ""
        self.status = ""
        self.note = ""

    @property
    def creatable(self):
        return self.kind in KINDS


def note_ignored(notes, where, hidden, links):
    if hidden:
        notes.append("ignored %d hidden entr%s in %s: %s"
                     % (len(hidden), "y" if len(hidden) == 1 else "ies",
                        where, ", ".join(hidden)))
    if links:
        notes.append("did not follow %d directory symlink(s) in %s: %s"
                     % (len(links), where, ", ".join(links)))


def walk(root, parent_id, overrides, notes):
    """Depth-first, parents before children, siblings in name order."""
    nodes = []

    def descend(dirpath, rel_prefix, parent, depth):
        subdirs = scan(dirpath)[0]
        siblings = []
        for entry in subdirs:
            relpath = "%s/%s" % (rel_prefix, entry.name) if rel_prefix else entry.name
            if "\t" in entry.name or "\n" in entry.name:
                die("folder name contains a tab or newline, which cannot be planned: %r" % relpath)
            sub, subfiles, hidden, links = scan(entry.path)
            note_ignored(notes, relpath, hidden, links)
            if sub and subfiles:
                kind = "conflict"
            elif sub:
                kind = "group"
            elif subfiles:
                kind = "package"
            else:
                kind = "skip"
            siblings.append((Node(depth, relpath, entry.name, kind), entry))

        assign_aliases([n for n, _ in siblings], parent, overrides, notes)

        for node, entry in siblings:
            nodes.append(node)
            if node.kind == "group":
                descend(entry.path, node.relpath, node.package_id, depth + 1)

    note_ignored(notes, "the root directory", *scan(root)[2:])
    descend(root, "", parent_id, 1)

    idx = 0
    for node in nodes:
        if node.creatable and node.package_id:
            idx += 1
            node.idx = idx
    return nodes


def assign_aliases(siblings, parent_id, overrides, notes):
    """Overrides first, verbatim; derived aliases then avoid what is taken.

    An override is sent exactly as the user typed it — the server decides whether
    an alias is legal, and quietly repairing one here would create something
    other than what was asked for. Two overrides that collide are reported, not
    resolved, for the same reason.
    """
    taken = set()
    for node in siblings:
        override = overrides.get(node.relpath)
        if override is None:
            continue
        node.alias = override
        node.note = "alias overridden"
        if not node.creatable:
            continue
        if override in taken:
            node.note = "duplicate alias"
            notes.append("two overrides give the same alias %r under %s: %s"
                         % (override, parent_id, node.relpath))
        taken.add(override)

    for node in siblings:
        if node.alias or not node.creatable:
            continue
        derived = derive_alias(node.name)
        if not derived:
            node.note = "no alias can be derived"
            notes.append("no alias can be derived from %r — pass --alias %s=<alias>"
                         % (node.relpath, node.relpath))
            continue
        node.alias = disambiguate(derived, taken)
        if node.alias != derived:
            node.note = "alias collision"
        taken.add(node.alias)

    for node in siblings:
        node.parent_id = parent_id
        if node.creatable and node.alias:
            node.package_id = "%s.%s" % (parent_id, node.alias)


def read_status(path):
    """packageId -> (http, kind) from check_ids.sh output."""
    status = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0]:
                status[parts[0]] = (parts[1], parts[2])
    return status


def apply_status(nodes, parent_id, status, notes):
    """Fold the existence check into each node. Returns True when work is blocked."""
    planned = set(n.package_id for n in nodes if n.creatable and n.package_id)
    checked = set(status) - {parent_id}
    if planned != checked:
        notes.append(
            "the existence check does not match this plan — %d id(s) unchecked, "
            "%d checked id(s) no longer planned. Re-run check_ids.sh before creating anything."
            % (len(planned - checked), len(checked - planned))
        )
        return True

    blocked = False
    http, kind = status.get(parent_id, ("", ""))
    if http == "200" and kind in ("workspace", "group"):
        notes.append("parent %s exists (%s)" % (parent_id, kind))
    elif http == "200":
        notes.append("parent %s is a %s — confirm the target before creating anything under it"
                     % (parent_id, kind or "node of an unexpected kind"))
        blocked = True
    elif http == "404":
        notes.append("parent %s does not exist — every id below it is computed from it" % parent_id)
        blocked = True
    elif http == "301":
        notes.append("parent %s redirects elsewhere; it was renamed or moved" % parent_id)
        blocked = True
    else:
        notes.append("parent %s could not be checked (HTTP %s)" % (parent_id, http or "no response"))
        blocked = True

    for node in nodes:
        if not node.creatable or not node.package_id:
            continue
        http, kind = status.get(node.package_id, ("", ""))
        if http == "404":
            node.status = "new"
        elif http == "200" and kind == node.kind:
            node.status = "reuse"
        elif http == "200":
            node.status = "conflict"
            node.note = "exists as %s" % (kind or "another kind")
            blocked = True
        elif http == "301":
            node.status = "moved"
            node.note = "id redirects elsewhere"
            blocked = True
        else:
            node.status = "unknown"
            node.note = "HTTP %s" % (http or "no response")
            blocked = True
    return blocked


def render(nodes, parent_id, with_status):
    """One Markdown row per node, always.

    Nothing here collapses, groups or abbreviates rows. The table is the gate the
    user confirms, and a row folded into a range or a comma-separated list stops
    showing the packageId and status that make confirmation mean anything.

    Markdown is the only format because the only reader is the user, and the
    table reaches them through an agent relaying this output into a chat. An
    aligned plain-text table survives that trip only inside a code fence, and one
    that arrives misaligned invites the reformatting-by-hand this table exists to
    prevent.

    parentId is not a column: packageId is parentId plus the alias, so every row
    already carries its parent.
    """
    headers = ["#", "path", "kind", "name", "alias", "packageId"]
    if with_status:
        headers.append("status")
    # The note column is dead width on a plan where nothing needs one.
    noted = any(node.note for node in nodes)
    if noted:
        headers.append("note")

    rows = []
    for node in nodes:
        # Markdown collapses leading spaces, so the tree shape rides in the full
        # relative path rather than in indentation.
        row = [
            str(node.idx) if node.idx else "-",
            node.relpath,
            node.kind,
            node.name,
            node.alias,
            node.package_id,
        ]
        if with_status:
            row.append(node.status)
        if noted:
            row.append(node.note)
        rows.append(row)

    def cell(text):
        return text.replace("|", "\\|") or " "

    out = ["target parent: `%s`" % parent_id, ""]
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join("---" for _ in headers) + "|")
    out.extend("| " + " | ".join(cell(c) for c in r) + " |" for r in rows)
    return "\n".join(out)


def write_plan(nodes, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(out_dir, "body-*.json")):
        os.remove(stale)

    plan_path = os.path.join(out_dir, "plan.tsv")
    count = 0
    with open(plan_path, "w", encoding="utf-8", newline="\n") as fh:
        for node in nodes:
            if not node.idx:
                continue
            count += 1
            fh.write("\t".join([
                str(node.idx), str(node.depth), node.kind, node.alias,
                node.package_id, node.parent_id, node.name, node.relpath,
            ]) + "\n")
            body = {
                "parentId": node.parent_id,
                "kind": node.kind,
                "name": node.name,
                "alias": node.alias,
            }
            body_path = os.path.join(out_dir, "body-%d.json" % node.idx)
            with open(body_path, "w", encoding="utf-8", newline="\n") as bf:
                json.dump(body, bf, ensure_ascii=False, indent=2)
                bf.write("\n")
    return count


def parse_overrides(values):
    overrides = {}
    for value in values:
        if "=" not in value:
            die("--alias wants <relative-path>=<alias>, got: %s" % value)
        path, alias = value.split("=", 1)
        path = path.replace("\\", "/").strip("/")
        if not path or not alias:
            die("--alias wants <relative-path>=<alias>, got: %s" % value)
        overrides[path] = alias
    return overrides


def main():
    parser = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    parser.add_argument("root")
    parser.add_argument("parent_id")
    parser.add_argument("--out", default="apihub-plan")
    parser.add_argument("--alias", action="append", default=[],
                        help="<relative-path>=<alias>, repeatable; sent to the server as typed")
    parser.add_argument("--status", action="store_true",
                        help="fold <out>/status.tsv into a status column")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        die("not a directory: %s" % args.root)
    if not args.parent_id or "/" in args.parent_id:
        die("parent id looks wrong: %r — expected something like MYWS or MYWS.GROUP"
                         % args.parent_id)

    overrides = parse_overrides(args.alias)
    notes = []
    nodes = walk(args.root, args.parent_id, overrides, notes)

    unmatched = set(overrides) - set(n.relpath for n in nodes)
    if unmatched:
        die("--alias path matches no folder: %s" % ", ".join(sorted(unmatched)))

    blocked = False
    for node in nodes:
        if node.kind == "conflict":
            notes.append("%s holds both files and subfolders — it is either a group or a package, "
                         "not both" % node.relpath)
            blocked = True
        elif node.kind == "skip":
            notes.append("%s is empty — nothing to create" % node.relpath)
        elif not node.alias:
            blocked = True
        elif node.note == "duplicate alias":
            blocked = True

    if args.status:
        status_path = os.path.join(args.out, "status.tsv")
        if not os.path.isfile(status_path):
            die("no existence check yet: %s — run check_ids.sh first" % status_path)
        if apply_status(nodes, args.parent_id, read_status(status_path), notes):
            blocked = True

    count = write_plan(nodes, args.out)
    print(render(nodes, args.parent_id, args.status))
    if notes:
        print("")
        for note in notes:
            print("- %s" % note)
    print("")
    print("%d node(s) to create, written to %s" % (count, os.path.join(args.out, "plan.tsv")))
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
