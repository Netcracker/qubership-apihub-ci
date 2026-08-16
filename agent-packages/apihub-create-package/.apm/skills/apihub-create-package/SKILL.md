---
name: apihub-create-package
description: Create groups and packages in APIHUB over the REST API — one node at a time, or a whole hierarchy inferred from a local directory tree and previewed before anything is created. Use whenever the user wants to create, add, or set up packages, groups, or a package structure in an APIHUB workspace. Reach for it when there is nothing to publish a version into yet.
---

# Creating packages and groups in APIHUB

Create the nodes an APIHUB tree is made of. A **group** holds other nodes; a **package** holds
published versions. Both are created by the same request, and both live under a parent that already
exists.

There is no ID field anywhere in this flow. The server computes `packageId = parentId + "." + alias`,
so a node's full id is knowable before it is created — which is what makes the whole plan previewable
and re-running safe.

Request shapes, the alias rules, ready-to-adapt curl commands, and the error-rendering recipe live in
[reference.md](reference.md). Read it once you start assembling a request.

## Scope

In scope: creating `group` and `package` nodes under a workspace, or under a group, that already
exists.

Out of scope. Say plainly that this skill does not cover it, and stop:

- **Creating a workspace.** It needs sysadm privileges, and who owns a workspace is a product
  decision rather than a step in a script. The user names an existing workspace as the root.
- **Dashboards** (`kind=dashboard`).
- **Publishing** into a package once it exists. That is the `apihub-publish-version` skill's job, and
  this one stops the moment the nodes are there. Say so and hand over rather than improvising a
  publish.

## Environment

The commands need `bash` and `curl`. Creating a hierarchy also needs Python 3, which does the tree
walk and writes each request body — creating a single node does not, so skip the interpreter probe
when the user asked for one group. On Windows run everything in Git Bash (or WSL); PowerShell will
not do, because its `curl` is a different command.

The helpers are bundled beside this file in `scripts/`, and are invoked as files. Do not paste their
contents inline and do not re-implement one — they encode the classification, alias and
descendant-skipping rules that make a partly-failed run resumable.

Step 0 resolves the two values every later command needs: the Python interpreter name (`python3` is
not the right name on every platform) and `SKILL_DIR` (the directory holding this file). The shell
does not persist between tool calls, so both have to be substituted **literally** into each command
rather than exported. Write `SKILL_DIR` with forward slashes — a Windows-style `C:\Users\…` breaks
inside a double-quoted bash string.

## Do not pre-check what the create request already checks

The backend validates the entire create request, and its errors name exactly what is wrong. A wrong
base URL fails to connect. A bad token returns `401`. A missing parent, an alias that is already
taken, an alias containing a character that would need percent-encoding, a caller without rights on
the parent — each returns a specific `4xx` naming the offending field.

So do not re-implement any of that here: no alias regex beyond the one used to *derive* an alias from
a folder name, no permission probe, no "can I create under this parent" dry call. Each such check
costs a round-trip, creates a second source of truth that drifts from the server's, and can wrongly
block a legitimate create — some rules depend on server configuration you cannot observe from here.
Send the request and render whatever comes back.

The existence checks in steps 1 and 3 are not exceptions to this. They answer a question the create
request cannot: *does this node already exist, so should we reuse it instead of creating it?* That is
what makes a re-run after a partial failure safe. Checking the parent first is the same question asked
where it is cheapest — it is not a permission probe, and permission is never checked, because a
successful create inherits its grants from the parent and there is no role step afterwards.

## Inputs

**Configuration.** A value the user states in the conversation wins; otherwise it comes from two
files in the user's home directory — `$HOME`, or `$USERPROFILE` where a Git Bash has no `HOME`.
There is no environment-variable fallback for the settings themselves: a variable exported in the
user's terminal never reaches this agent's shell.

- `$HOME/.apihub/config` — non-secret settings, one `key=value` per line: `url=` for the APIHUB base
  URL. Write this file for the user on request.
- `$HOME/.apihub/pat` — the personal access token, sent as the `X-Personal-Access-Token` header; or
  `$HOME/.apihub/api-key`, sent as `api-key`. Prefer the PAT, which attributes the created nodes to
  the real user rather than to the key. Read the file inside the command that needs it, and nowhere
  else: never write a credential file, never print or copy its contents, and never place a credential
  under the repository — a token that reaches git history cannot be taken back.

If either file is missing, tell the user exactly what to create and stop. Never ask for a token in
the chat. The wording to show them, and the `chmod 600` advice that applies on macOS and Linux only,
are in [reference.md](reference.md).

**Base URL.** If the user pastes a full portal URL, use the scheme and host only and ignore the path
— portal paths and API coordinates are not the same thing, and a silent mis-parse creates packages in
the wrong place. Require `https` unless the user explicitly asks for a local `http` instance. Never
substitute a different host.

**The target parent.** An existing workspace, or workspace plus group, given as an id like `MYWS` or
`MYWS.BACKEND`. Every id in the plan is computed from it, so if the user has not named one, ask —
there is nothing to guess from, and a plan built on the wrong root is fifty wrong nodes rather than
one.

**Names and aliases.** A `name` is free text shown in the UI. An `alias` is the id segment. When the
user gives an alias, send it exactly as typed; when you derive one from a folder name, follow the
rule in [reference.md](reference.md) and show the result in the preview so it can be overridden.

## Workflow

### 0. Preflight

Run this first, before asking the user anything and before touching any file.

```bash
command -v curl >/dev/null 2>&1 && echo "curl: ok" || echo "curl: MISSING"
[ -d "$SKILL_DIR/scripts" ] && echo "scripts: ok" || echo "scripts: MISSING at $SKILL_DIR"
for c in python3 python "py -3"; do
  $c -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" 2>/dev/null && { echo "python: $c"; break; }
done
```

Substitute the resolved `SKILL_DIR` into that command literally, as into every command afterwards.

- **`curl: MISSING`** — stop and give the user the install command for their platform. On Windows
  that is Git for Windows, which carries the `bash` these commands already run in as well as `curl`.
- **`scripts: MISSING`** — `SKILL_DIR` is wrong. Fix it before going on.
- **No `python:` line** — Python 3 is absent. A single-node create still works; a hierarchy does not,
  so stop and give the user the install command rather than walking the tree by hand.
- **Any other name than `python3`** — use that name in every later command.

### 1. Establish what to create, and under what

Two shapes come up, and they differ only in how the plan is built:

- **One node** — the user names a kind, a name, and a parent ("a new group BILLING under MYWS"). The
  plan is a single row you write yourself.
- **A hierarchy from a directory** — the user points at a local root directory. The directory itself
  does **not** become a node; only what is inside it does.

Then check the target parent, before building anything:

```bash
bash "$SKILL_DIR/scripts/check_ids.sh" --parent MYWS
```

This is the first request of the flow because every id in the plan is `parentId + "." + alias`. A
parent that is missing, has moved, or is itself a package makes the whole plan void — and finding that
out now costs one `GET`, where finding it out later costs a tree walk, a request body per folder, and
one `GET` per node, all of them discarded.

A non-zero exit means stop and tell the user what came back. Do not walk the tree "to show them
anyway": a plan under a parent that does not exist is a list of ids that cannot be created, and
presenting it invites them to confirm something impossible. If the parent turns out to be a package,
say so plainly — nodes live under a workspace or a group. If it does not exist at all, name it and
remember that creating a workspace is out of scope.

### 2. Build the plan

For a directory tree, `scripts/plan_tree.py` walks it and classifies every folder by what it holds:
only subfolders → `group`, only files → `package`, both → a conflict that stops the run, neither →
skipped. It derives each alias, resolves sibling collisions, computes every id, and writes one
request body per node so a folder name with a quote or a space reaches the server intact. Invocation
and the alias rule are in [reference.md](reference.md).

The classification is purely structural — *any* file counts, whatever its extension. A folder of
`.md` notes is as much a package as a folder of OpenAPI documents, because what a package may hold is
the publish step's business, not this one's.

For a single node, the plan is one line: kind, name, alias, and the id you get by joining the parent
and the alias with a `.`.

### 3. Check what already exists

`scripts/check_ids.sh` given the plan directory records what came back for every planned id. A `200`
whose `kind` matches means reuse, a `404` means new, and anything else — a kind that differs, a `301`
from a node that was renamed, a `401` — is something a human has to resolve.

It asks about the target parent a second time here. That one repeated `GET` is what lets the record
stand on its own, so the create step reads a single file rather than trusting that an earlier command
it cannot see was run against the same instance.

Because ids are computable, this needs no search and no pagination. It is also what makes step 5
restartable: after a partial failure, everything already created reads back as `reuse`.

### 4. Show the plan, then get explicit confirmation

Print the whole plan as one table before creating anything. Re-running `plan_tree.py` with `--status`
folds the existence check in and emits the Markdown table to show the user:

```bash
python3 "$SKILL_DIR/scripts/plan_tree.py" ./specs MYWS --out apihub-plan --status
```

| # | path | kind | name | alias | packageId | status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | archive | package | archive | archive | MYWS.archive | new |
| 2 | backend | group | backend | backend | MYWS.backend | reuse |
| 3 | backend/Billing API | package | Billing API | billing-api | MYWS.backend.billing-api | new |
| 4 | backend/orders | package | orders | orders | MYWS.backend.orders | new |
| - | empty | skip | empty | | | |

**Pass that output through unchanged.** It is tempting to compress a large plan — to fold fifty
sibling packages into `4-18  package  add-info, add-tags-name, …`, or to draw the tree with `├─` and
`└─` characters. Both destroy the thing the table is for: a folded row no longer shows the
`packageId` and `status` of each node, so a user confirming it is approving a summary rather than the
work. A hundred-row table is the honest size of a hundred-node request, and the user can scroll it.

The same goes for re-typing it in your own layout. Every hand-copied table is a chance to drop a row
or mistype an id, and the user then confirms something the script never planned.

Show the notes underneath it too — the empty folders that were skipped, the hidden entries that were
ignored, the sibling collisions that were suffixed. They are how the user notices that a folder they
cared about is missing from the plan.

Offer to override any individual alias. Then stop and wait for a clear yes. **Do not create anything
the user has not seen in this table**, and do not proceed at all while any of these is unresolved:

- a folder holding **both files and subfolders** — it is either a group or a package and nothing here
  can tell which, so ask rather than guess;
- an id that exists with a **different kind**;
- an id that answers **`301`** — it was renamed or moved, so every child id computed from it is
  wrong;
- an existence check that **could not be read** at all.

### 5. Create, top-down

Only after explicit confirmation. `scripts/create_plan.sh` walks the confirmed plan in order, so a
group always exists before its children, and reuses whatever the check found rather than re-creating
it.

When a create fails, its descendants are skipped — their parent does not exist — while unrelated
branches carry on, because one bad node should not block fifty good ones elsewhere in the tree.
Nothing is ever retried with an altered alias or parent.

A single node needs no script; the `POST` is in [reference.md](reference.md).

### 6. Report what happened

One summary: created, reused, skipped (the empty folders), and failed — each failure with its
rendered error. Link the target parent so the user can see the result, and link individual created
packages when there are few enough to be worth listing.

Build every such link from the node's `kind` — the portal has a separate route per kind, and
`/portal/packages/` is not a safe default for all of them. The three forms, and why a wrong one
cannot be caught by fetching it, are in [reference.md](reference.md).

Say plainly that a re-run only redoes the failed branch, because everything already created reads
back as `reuse`. That is the whole point of the existence check, and it turns "23 of 50 created" from
a mess into a resumable job.

## Rendering a failure

This applies to every request in this flow. Stop on failure — never retry with altered parameters to
make a request pass, because a node that only appeared after you quietly changed its alias or its
parent is a wrong node, not a recovered one. Distinguish three cases:

- **Connection failure, or a response that is not APIHUB** — the base URL is wrong. Say so and stop.
  Do not try other hosts, ports, or path prefixes.
- **`401`** — the credential is invalid, expired, or revoked. Say which file it came from, never its
  contents.
- **Any other `4xx` or `5xx`** — the body is `{status, code, message, params, debug}`, where
  `message` is a template with `$placeholders` and `params` holds their values. Substitute each `$key`
  from `params` into `message`, show the result, and append `debug` when present. If a placeholder
  does not resolve, show the raw body instead of a half-filled sentence — that mismatch is a backend
  defect, and the raw body is both the honest answer and what a bug report needs. `code` is an opaque
  identifier, so do not branch on it — the substituted message is already a complete and current
  explanation, which is why this skill carries no error table of its own. A hand-maintained one would
  drift from the server. Recipe and three real examples in [reference.md](reference.md).

## Safety rules

- Never create a `workspace` or a `dashboard`.
- Never create anything the user has not seen and confirmed in the preview table.
- Never abbreviate that table — no folded row ranges, no comma-separated node lists, no box-drawing
  tree characters. Show the rows the script emitted, all of them.
- Never auto-fix and retry a failed create with an altered alias or parent.
- Never guess on a folder holding both files and subfolders, or on an id that exists with a different
  kind — stop and ask.
- Never print or copy a credential, and never write one to a file.
- Never fall back to a different APIHUB host or parent than the user gave or approved.
- On failure, show the rendered backend error and stop.
