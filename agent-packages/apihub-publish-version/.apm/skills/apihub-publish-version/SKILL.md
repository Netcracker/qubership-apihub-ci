---
name: apihub-publish-version
description: Publish a version of an APIHub package over the REST API — assemble the build config and sources zip, POST the publish request, then poll the build to completion. Use whenever the user wants to publish, upload, or release API specifications (OpenAPI, Swagger, AsyncAPI, GraphQL) or contracts (DDL, MCP) to a Qubership APIHub instance, even if they never name the REST API.
---

# Publishing an API version to APIHub

Publish one version of one APIHub **package** from the source files the user names — API
specifications, DDL, MCP contracts, or anything else APIHub accepts as a document.

Publishing is asynchronous. The `POST` queues a build, an external builder picks it up, and you
poll for the result. A `202` means the request was accepted, not that the version exists — only a
`complete` status means that.

Field-by-field build config notes, ready-to-adapt curl commands, and the error-rendering recipe
live in [reference.md](reference.md). Read it once you start assembling the request.

## Scope

In scope: publishing a package version from source files.

Out of scope: dashboards (`config.refs[]`), CSV publish (`/publish/withOperationsGroup`), and
operation-group publish. If the user asks for one of these, say plainly that this skill does not
cover it and stop. Guessing at a payload for an endpoint whose contract you cannot check either
fails after a slow round-trip or, worse, creates a half-built version somebody then has to delete.

## Environment

The commands need `bash`, `curl` and Python 3, and nothing else — in particular not `zip` or
`unzip`. Python covers only three jobs: building the sources zip, listing its entries, and
classifying MCP documents. On Windows run everything in Git Bash (or WSL); PowerShell will not do,
because its `curl` is a different command.

The helpers are bundled beside this file in `scripts/`, and are invoked as files. Do not paste
their contents inline and do not re-implement one — they encode the entry-name and detection rules
the backend enforces.

Step 0 resolves the two values every later command needs: the Python interpreter name (`python3` is
not the right name on every platform) and `SKILL_DIR` (the directory holding this file). The shell
does not persist between tool calls, so both have to be substituted **literally** into each command
rather than exported. Write `SKILL_DIR` with forward slashes — a Windows-style `C:\Users\…` breaks
inside a double-quoted bash string.

## Do not pre-check what the publish request already checks

The backend validates the entire request before it creates a build, and its errors name exactly
what is wrong. A wrong base URL fails to connect. A bad token returns `401`. A bad `packageId`,
version name, status, previous version, or archive returns a specific `4xx` naming the offending field.

So do not re-implement any of that client-side: no "does this package exist" probe, no version-name
regex, no check that the previous version is real. Each such check costs a round-trip, creates a second
source of truth that drifts from the server's, and can wrongly block a legitimate publish — some
rules (release-version patterns, permissions, allowed statuses) depend on server configuration you
cannot observe from here. Send the request and render whatever comes back.

The one exception is resolving a package *name* to a `packageId`. That is search, not validation:
without it you have nothing to put in the URL.

## Inputs

**Configuration.** A value the user states in the conversation wins; otherwise it comes from two
files in the user's home directory — `$HOME`, or `$USERPROFILE` where a Git Bash has no `HOME`.
There is no environment-variable fallback for the settings themselves: a variable exported in the
user's terminal never reaches this agent's shell.

- `$HOME/.apihub/config` — non-secret settings, one `key=value` per line: `url=` for the APIHub
  base URL. Write this file for the user on request.
- `$HOME/.apihub/pat` — the personal access token, sent as the `X-Personal-Access-Token` header;
  or `$HOME/.apihub/api-key`, sent as `api-key`. Prefer the PAT, which attributes the published
  version to the real user rather than to the key. Read the file inside the command that needs it,
  and nowhere else: never write a credential file, never print or copy its contents, and never
  place a credential under the repository — a token that reaches git history cannot be taken back.

If `url=` is missing, ask the user to create `$HOME/.apihub/config` containing
`url=https://apihub.example.com`, or offer to write it once they give you the URL. If neither
credential file exists, ask the user to create `$HOME/.apihub/pat` with the token as its only line,
and to `chmod 600` it on macOS or Linux — on Windows say nothing about the mode, where Git Bash's
`chmod` often changes nothing and the profile directory's own ACL is what restricts access. Never
ask for a token in the chat. A PAT is created in the APIHub UI or via
`POST /api/v1/personalAccessToken`; a package-scoped API key via
`POST /api/v4/packages/{packageId}/apiKeys`. The commands that load these files are in
[reference.md](reference.md).

**Base URL.** If the user pastes a full portal URL, use the scheme and host only and ignore the
path — portal paths and API coordinates are not the same thing, and a silent mis-parse publishes to
the wrong place. Require `https` unless the user explicitly asks for a local `http` instance. Never
substitute a different host.

**Sources.** The user supplies either the specification files to publish or a ready-made `.zip`
containing them. Publish only what the user names. Never scan the working directory for candidates
and never add a file the user did not list — an unrequested file becomes a published API document
that is then visible to everyone reading the version.

**Coordinates.** `packageId` (or a package name), `version` and `status` come from the user and are used exactly as given.
If the user names no `previousVersion`, publish without one.

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
- **`scripts: MISSING`** — `SKILL_DIR` is wrong. Fix it before going on; every later command depends
  on it.
- **No `python:` line** — Python 3 is absent. Stop and give the user the install command for their
  platform. Do not guess an interpreter and do not carry on without one.
- **Any other name than `python3`** — use that name in every later command.

### 1. Resolve the package, only if needed

First work out what the user actually gave you. An APIHub `packageId` is a dotted path of identifier
segments — `MYWS.BACKEND`, `WS.GROUP.MYSERVICE` — with no spaces. If the value matches that shape,
it is already an id: use it and do not search.

Otherwise search **once**:

```text
GET {base}/api/v2/packages?textFilter=<name>&kind=package&limit=20&showAllDescendants=true
```

URL-encode the name if it contains spaces. Keep the search bounded — one call, a small limit, no
pagination loop, and do not pull a large result set into context. Show the user the candidates with
their ids and ask which one to publish to. Confirm
the resolved `packageId` **even when exactly one package matches**: publishing to the wrong package
is the one expensive mistake in this flow, and a single match is not proof of the right match. If
the search returns nothing, say so and stop rather than widening the filter.

Package identity and MCP endpoints (step 3) are the only two things you ask about. Everything else
the user stated is used as given — do not read the version, status, or file list back for
confirmation.

### 2. Assemble the sources

Zip exactly the files the user named, then read `config.files[]` off the archive listing, so every
`fileId` is an entry path. If the user supplied a ready-made `.zip`, list that instead of repacking
it.

The archive filename must end in `.zip`; the backend rejects any other name. Quote paths in shell
commands so names containing spaces or brackets survive, and never rename or sanitise a file.

Use `scripts/zip_sources.py` to build the archive and `scripts/list_zip.py` to read its entries.
See [reference.md](reference.md) for both invocations and the build config fields.

### 3. Classify MCP documents and resolve their endpoints

Every MCP contract document needs `metadata.mcpEndpoint` on its `files[]` entry. It is required —
the build fails without it — and it is not cosmetic: the endpoint is slugified into every
`mcpEntityId`, so a wrong value silently renames every tool, prompt and resource and breaks the
changelog against the previous version.

Run `scripts/classify_mcp.py` over the `.json` entries. It prints one line per
MCP document and nothing for anything else, so file contents never enter your context — which
matters because specifications are large and none of that text helps you here.

**Match the invocation to where the documents actually are.** If you built the archive in step 2,
the entries are also files on disk, so pass them as paths. If the user supplied a ready-made `.zip`,
they are *not* on disk — pass `--zip` and let the script read inside the archive. See
[reference.md](reference.md) for both forms.

Read stdout and stderr as two different answers. There are no MCP documents only when stdout is
empty **and** stderr is empty **and** the user has not called any file an MCP contract — then skip
the rest of this step. A `cannot read` or `cannot parse` line on stderr means the opposite: the
documents are there and you have not classified them, usually because you passed paths for an
archive that wanted `--zip`. Resolve that before going on; an MCP document that reaches the publish
unclassified has no `metadata.mcpEndpoint`, and the build fails long after the `202`.

Then count the `mcp-init` lines. Exactly one init is required per endpoint, so **the init count is
the endpoint count**.

- *One init* (or zero inits alongside other MCP documents) — ask for a single endpoint and apply it
  to every MCP document. Name the files you will attach it to, so the user can add one you missed.
- *Two or more inits* — print the decision table from [reference.md](reference.md) and ask the user
  to assign each document to an endpoint.

Ask for the endpoint as a relative path beginning with `/`, such as `/mcp/support`. Never invent
one, and never infer it from a filename or directory: the builder detects MCP documents by their
JSON shape and attaches no meaning whatsoever to what they are called.

Add `metadata.mcpEndpoint` to each MCP entry. Leave every other `files[]` entry untouched.

### 4. Publish

```text
POST {base}/api/v2/packages/{packageId}/publish
```

`multipart/form-data` with exactly two parts: `config` (the JSON build config as a form field) and
`sources` (the zip). A `202` returns `{"publishId": "..."}`.

Send nothing else. `resolveRefs` and `resolveConflicts` act only on `config.refs[]`, which is empty
for a package publish, so they are inert here — and they govern **package references**, the
dashboard-to-package-version graph, not `$ref` resolution inside OpenAPI documents, which the builder
handles by itself. `clientBuild` and `builderId` belong to the browser-based build path, and
`dependencies` to chained builds. Do not offer any of them to the user, and do not accept them if
asked.

### 5. Render any failure, do not interpret it

This applies to every request in this flow, not only the publish. Stop on failure — never retry with
altered parameters to make a request pass, because a publish that only succeeded after you quietly
changed the version, the status, or the file list is a wrong publish, not a recovered one.
Distinguish three cases:

- **Connection failure, or a response that is not APIHub** — the base URL is wrong. Say so and stop.
  Do not try other hosts, ports, or path prefixes.
- **`401`** — the credential is invalid, expired, or revoked. Say which file it came from, never its
  contents.
- **Any other `4xx` or `5xx`** — the body is `{status, code, message, params, debug}`, where
  `message` is a template with `$placeholders` and `params` holds their values. Substitute each
  `$key` from `params` into `message`, show the result, and append `debug` when present. `code` is
  an opaque numeric identifier, so do not branch on it — the substituted message is already a
  complete and current explanation, which is why this skill carries no error table of its own. A
  hand-maintained one would drift from the server. Recipe and worked example in
  [reference.md](reference.md).

### 6. Poll to completion

```text
GET {base}/api/v2/packages/{packageId}/publish/{publishId}/status
```

Poll with backoff until the status is `complete` or `error`. Be prepared to wait **30 minutes or
more** — a large publish genuinely takes that long, and a build that is still `running` has not
failed. Your own command timeout is much shorter than the build, so poll in repeated windows rather
than one long-running call. Use `scripts/poll_build.sh`, which is written for exactly that and
signals with its exit code whether it finished or merely ran out of window; re-run it unchanged for
each window. Its arguments and exit codes are in [reference.md](reference.md).

Report the statuses honestly:

- `none` — queued; no builder has taken it yet. If it is still `none` when you stop, report that no
  builder appears to be processing the queue on this instance. Do not keep waiting silently and do
  not report success.
- `running` — a builder has it. Keep polling. If it is still `running` when you reach the time you
  were willing to wait, say how long it has been running and ask the user whether to keep waiting.
  Do not call this a failure and do not abandon it silently — the build is alive.
- `complete` — done. Give the user the version link:
  `{base}/portal/packages/{packageId}/{version}`.
- `error` — report the `message` field verbatim. Content errors inside the documents surface here
  rather than at publish time, so a clean `202` says nothing about the outcome. This is also where
  MCP failures land: a missing or malformed `metadata.mcpEndpoint`, or an endpoint with entities but
  no init. A failed publish is a failure, not a partial success.

## Safety rules

- Never publish to a `packageId` that came from a search without the user confirming it.
- Never publish a file the user did not name.
- Never invent or guess an `mcpEndpoint`, and never infer one from a filename or directory — it
  becomes part of every `mcpEntityId`.
- Never print or copy a credential, and never write one to a file.
- Never fall back to a different APIHub host, `packageId`, or version than the user gave or approved.
- On failure, show the rendered backend error and stop.
