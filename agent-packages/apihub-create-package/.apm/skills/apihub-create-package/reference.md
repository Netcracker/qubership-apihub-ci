# APIHUB create-package reference

Companion to `SKILL.md`: the request shapes, the alias rules, the shell commands for each step, and
the recipe for rendering a backend error. `SKILL.md` holds the workflow and the rules — this file
holds the detail you need once you are already executing a step.

## Environment

Every command below needs `bash` and `curl`. The hierarchy commands also need Python 3, which does
the tree walk and writes each request body; a single-node create needs no interpreter at all. Two
tools are deliberately avoided: a hardcoded `python3`, which the python.org installer does not
provide — it gives `python` and `py -3` — and any assumption about which text utilities a given Git
for Windows install carries, which is why the config file is parsed with shell builtins.

On Windows the commands run in Git Bash (or WSL, where everything is plain Linux). Git Bash also
supplies `curl.exe`. PowerShell is not a substitute: its `curl` is an alias for `Invoke-WebRequest`
with unrelated flags, and none of the shell syntax below is valid there.

`SKILL.md` step 0 resolves two values before any work begins: the Python interpreter name and
`SKILL_DIR`. Both must be substituted **literally** into every command below — the shell does not
persist between tool calls, so assigning either to a variable in one call does not carry to the next.
Snippets here are written as `python3` and `$SKILL_DIR`; if the probe reported `python` or `py -3`,
use that instead.

Resolve `SKILL_DIR` to the directory containing this skill's `SKILL.md`, and **write it with forward
slashes** — a Windows-style `C:\Users\…` breaks inside a double-quoted bash string, where the
backslashes are escapes. Do not assume the current working directory is the skill directory.

### Bundled scripts

The helpers live beside `SKILL.md` and are invoked as files, never pasted inline:

| Script | Purpose |
| ------ | ------- |
| `scripts/apihub_env.sh` | Shared prelude — **sourced**, sets `base`, `cred`, `hdr`, `tok`. |
| `scripts/plan_tree.py` | Walk a directory, classify every folder, derive aliases, write the plan. |
| `scripts/check_ids.sh` | GET the parent alone, or the parent and every planned id. |
| `scripts/create_plan.sh` | Create a confirmed plan top-down, reusing what already exists. |

Do not rewrite a script, and do not re-implement one inline. `plan_tree.py` in particular writes each
request body as a file so a folder name containing a quote, a backslash or a non-ASCII character
reaches the server intact; rebuilding that JSON in a shell string is how `name` bugs get made.

One Git Bash rule the commands below already follow, and any command you improvise should too:

**Never pass a value that merely looks like a path as an argument to `curl` or `python`.** Git Bash
rewrites POSIX-looking arguments before handing them to a native `.exe`. For a real filesystem path
this is correct and wanted — `/c/Users/…` arrives as `C:/Users/…`, which is why passing `$SKILL_DIR`
and the root directory as arguments is safe. For a value that is not a path it is destructive:
`/MYWS` would arrive as `C:/Program Files/Git/MYWS`. Nothing here needs to pass one (a parent id
never starts with `/`), but `MSYS_NO_PATHCONV=1` is the escape hatch if you find a case that does.

## Configuration

Two files in the user's home directory. `$HOME` resolves the same way on macOS, Linux and Git Bash on
Windows, so one path serves all three — with `$USERPROFILE` as the fallback, because a Git Bash that
reads no startup file may have no `HOME` at all, while Windows puts `USERPROFILE` in every process
environment:

- `$HOME/.apihub/config` — non-secret settings, one `key=value` per line, no spaces around `=` and no
  quotes:

  ```text
  url=https://apihub.example.com
  ```

- `$HOME/.apihub/pat` — the personal access token on the first line, or `$HOME/.apihub/api-key` for a
  package-scoped API key. Which file exists decides which header is sent, so nothing has to be
  inferred from the value itself, and the PAT wins when both exist. Ask the user for a PAT rather
  than an API key: it attributes the work to the real user instead of to a key.

Shell state does not survive between tool calls, so each command loads what it needs itself. Every
command below opens by sourcing the shared prelude:

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"
```

It sets `base` (the URL, trailing slash removed), `cred`, `hdr` and `tok`. **Source it, do not execute
it** — an executed copy sets those variables in a subshell that dies immediately. On an unusable
configuration it prints which file is at fault and exits `2`, which ends the calling command; that is
intended, and it is the `2` in the exit codes below.

It parses with builtins only, so no assumption is made about which text utilities the platform
carries. Four details in it are load-bearing rather than defensive:

- `[ -f "$apihub/config" ]` reports a missing config file as itself, instead of the misleading
  `no url= in …` that a bare read would produce.
- `${v%$'\r'}` and `${tok%$'\r'}` strip the carriage return a Windows editor leaves on every line.
  Left in place it travels into the URL and into the header, where it produces a malformed request
  rather than an obvious error.
- `|| [ -n "$k" ]` keeps the last line when the file ends without a newline, which is otherwise
  dropped silently.
- `[ -n "$tok" ]` catches an empty credential file, which would otherwise reach the server as a
  blank header and come back as a `401` blamed on the token.

The token lives only in `$tok`, unexported, for the length of one command. Pass it as
`-H "$hdr: $tok"` and never anywhere else. Never write a credential file yourself, and never place
one under the repository — a token that reaches git history cannot be taken back.

Read what is configured without exposing anything:

```bash
apihub="${HOME:-$USERPROFILE}/.apihub"
cat "$apihub/config" 2>/dev/null || echo "no config file"
ls -l "$apihub/pat" "$apihub/api-key" 2>/dev/null
```

The config file holds no secrets, so printing it is fine. `ls -l` reports the credential files by name
and mode without reading them.

Create the config file when the user asks, using only a URL they gave you. `>` replaces the whole
file, so read an existing one first and rewrite every line worth keeping:

```bash
apihub="${HOME:-$USERPROFILE}/.apihub"
mkdir -p "$apihub"
printf 'url=%s\n' "https://apihub.example.com" > "$apihub/config"
```

The credential file is the user's to write. When either file is missing, show them this:

```text
Create $HOME/.apihub/config with your APIHUB base URL:

    url=https://apihub.example.com

Create $HOME/.apihub/pat containing only your personal access token.
On macOS or Linux, restrict it:

    chmod 600 $HOME/.apihub/pat
```

If the user offers the token in the chat instead, ask them to write it to the file themselves.

A PAT is created in the APIHUB UI or via `POST /api/v1/personalAccessToken`; a package-scoped API
key via `POST /api/v4/packages/{packageId}/apiKeys`.

### File mode

`chmod 600` keeps other unprivileged accounts out of the token. It restrains nothing that already
runs as the user, so do not describe it as more than that.

On Windows, do not report a mode at all. Git Bash's `chmod` frequently changes nothing while `ls -l`
still prints a plausible mode, so checking it would confirm a restriction that was never applied.
The profile directory's ACL already excludes other non-administrator accounts. Only if the user asks
for an explicit restriction, this sets one from a Command Prompt:

```text
icacls "%USERPROFILE%\.apihub\pat" /inheritance:r /grant:r "%USERNAME%:R"
```

## The create request

```text
POST {base}/api/v2/packages
```

```json
{
  "parentId": "MYWS.BACKEND",
  "kind": "group",
  "name": "Billing",
  "alias": "billing"
}
```

- `parentId` is **required**. It is the workspace or group the node is created under.
- `kind` is `group` or `package` here. The endpoint also accepts `workspace` and `dashboard`; this
  skill creates neither.
- `name` is free text shown in the UI. It may contain spaces, punctuation and non-ASCII characters.
- `alias` is the id segment. It must be URL-safe **as typed** — no character that would need
  percent-encoding — and must not contain a `.`, which reads as a level separator.
- `description` is optional.
- There is **no ID field**. The server computes `packageId = parentId + "." + alias`, so the example
  above creates `MYWS.BACKEND.billing`.

Nothing else happens after a successful create. Permission is inherited from the parent's existing
grants, so there is no role or member step to follow up with.

## Checking whether a node exists

```text
GET {base}/api/v2/packages/{packageId}
```

- `200` — it exists; the body carries its `kind`, which is what distinguishes reuse from a conflict.
- `404` — it does not exist.
- `301` — the id now redirects elsewhere: the node was renamed or moved. This is not "it exists"; any
  child id computed from it is wrong, so stop and ask.

Because a node's id is always `parentId + "." + alias`, the expected id is computable and fetched
directly. There is no search step and no pagination.

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"
pkg="MYWS.BACKEND.billing"

curl -sS -o response.json -w '%{http_code}\n' \
  "$base/api/v2/packages/$pkg" \
  -H "$hdr: $tok"
```

Do not add `-L`. Following the redirect would turn a `301` into a `200` for a *different* node and
report it as the one you asked about.

## Creating one node by hand

Write the body to a file first, so no JSON has to survive shell quoting:

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"

curl -sS -o response.json -w '%{http_code}\n' -X POST \
  "$base/api/v2/packages" \
  -H "$hdr: $tok" \
  -H "Content-Type: application/json" \
  --data-binary @body.json
```

A `2xx` means the node exists. Anything else is a failure — render it with the recipe below and stop.

## Checking the target parent first

```bash
bash "$SKILL_DIR/scripts/check_ids.sh" --parent MYWS
```

Run this before planning anything. Every id in a plan is `parentId + "." + alias`, so a parent that
is missing, has moved, or is itself a package makes the whole plan void — and one `GET` says so
before a tree is walked, a request body is written per folder, and one `GET` per node is spent on ids
that could never have been created.

It prints `<http> <kind> <parentId>`, then a line naming the problem when there is one.

- **`0`** — the parent exists and is a workspace or a group.
- **`1`** — it does not exist, it redirects, it is a package or dashboard, or it could not be
  checked. Stop and tell the user what came back. When the server sent a body it is in `parent.json`;
  a `000` means nothing answered at all, and the message names the URL to check.
- **`2`** — cannot run as given: bad arguments, or no `url=` / no credential.

A missing parent is worth reading twice before reporting it. Creating a workspace is out of scope for
this skill, so "the workspace does not exist" is the end of the road here, not a step to improvise
past.

## Planning a hierarchy from a directory

```bash
python3 "$SKILL_DIR/scripts/plan_tree.py" ./specs MYWS --out apihub-plan
```

The first argument is the local root directory, the second the target parent id. **The root directory
is not turned into a node** — only what is inside it. `--out` defaults to `apihub-plan` in the current
directory and holds every file the later steps read.

Each folder is classified by what it contains, recursively:

| Contents | Result |
| -------- | ------ |
| Only subfolders | `group` |
| Only files | `package` |
| Both files and subfolders | `conflict` — the run stops, nothing is created |
| Neither | skipped, noted, not an error |

The rule is purely structural: any file counts, whatever its extension. Which file types are
publishable specifications is the publish step's business, not this one's.

Dot-entries are ignored and directory symlinks are not followed, both counted in the printed notes. A
stray `.DS_Store` would otherwise turn every leaf folder into a mixed-content conflict.

### Deriving an alias

Applied only where the user has not given one:

1. Replace runs of characters outside `[a-zA-Z0-9_-]` with a single `-`.
2. Trim leading and trailing `-`.

`Billing API` becomes `Billing-API`; `Very Long Folder Name Here` becomes
`Very-Long-Folder-Name-Here`.

Case is preserved. The server's only rule is that an alias be URL-safe as typed, and upper-case ASCII
is, so folding the case would buy nothing and lose the match against nodes that already exist under
an upper-case id — a folder named `BACKEND` would derive `backend`, and `MYWS.backend` is a different
node from `MYWS.BACKEND`.

When two sibling folders under the same parent derive the same alias they would compute the same
`packageId`, so one would silently reuse the other. The second is suffixed `-2`, the third `-3`, and
so on, deterministically. The preview shows the result either way.

Override any of it, repeatably, with a path relative to the root:

```bash
python3 "$SKILL_DIR/scripts/plan_tree.py" ./specs MYWS \
  --alias "backend/Billing API=billing" \
  --alias "legacy=old"
```

An override is sent to the server exactly as typed — no character replacement. An override path that
matches no folder is an error rather than a no-op, because a typo that quietly did nothing would leave
the user believing an alias was changed when it was not.

### Rendering the plan

The table is Markdown, and that is the only format. Its one reader is the user, and it reaches them
through an agent relaying this output into a chat — an aligned plain-text table survives that trip
only inside a code fence, and one that arrives misaligned invites exactly the hand-reformatting the
table exists to prevent.

The `path` column carries the full relative path, since Markdown collapses the leading spaces that
would otherwise show nesting. There is no `parentId` column: `packageId` is `parentId` plus the
alias, so every row already carries its parent.

One row per node, always. Nothing groups, folds or abbreviates, and a plan of a hundred folders
prints a hundred rows.

That constraint survives into how you relay the table, and it is tempting to break. Compressing a
large plan — folding fifty sibling packages into `4-18  package  add-info, add-tags-name, …`, or
drawing the tree with `├─` and `└─` characters — destroys the thing the table is for: a folded row
no longer shows the `packageId` and `status` of each node, so a user confirming it is approving a
summary rather than the work. A hundred-row table is the honest size of a hundred-node request, and
the user can scroll it. The same goes for re-typing it in your own layout; every hand-copied table
is a chance to drop a row or mistype an id, and the user then confirms something the script never
planned.

A folder whose name yields an empty alias (nothing but punctuation) stops the run and asks for an
`--alias`. Guessing a name for it would create something nobody chose.

Exit codes:

- **`0`** — the plan is creatable.
- **`1`** — something needs a human: a mixed-content folder, an alias that cannot be derived, or, with
  `--status`, a kind conflict, a redirect, or a stale check.
- **`2`** — cannot run as given: bad arguments, no such directory, an `--alias` path that matches no
  folder, or a folder name containing a tab or newline.

### What lands in the plan directory

| File | Written by | Contents |
| ---- | ---------- | -------- |
| `plan.tsv` | `plan_tree.py` | One row per creatable node, parents before children. |
| `body-<n>.json` | `plan_tree.py` | The request body for node `<n>`, `<n>` matching the table. |
| `status.tsv` | `check_ids.sh` | `packageId`, HTTP code, `kind` for the parent and every node. |
| `get-<n>.json` | `check_ids.sh` | Kept only when an existence check answered something unusable. |
| `error-<n>.json` | `create_plan.sh` | The backend's response for a node that failed to create. |

## Checking and creating a planned hierarchy

```bash
bash "$SKILL_DIR/scripts/check_ids.sh" apihub-plan
```

It GETs the target parent and then every planned id, writes `status.tsv`, and prints
`<http> <kind> <packageId>` per node as it goes.

The parent is asked about again even though `--parent` already covered it. That repeated `GET` is
deliberate: `status.tsv` is the single file `create_plan.sh` reads, and a record that omitted the
parent would force it to trust that an earlier command it cannot see was run, against the same
instance, since the last change.

Exit codes:

- **`0`** — every id answered `200` or `404`. Render the plan and get confirmation.
- **`1`** — at least one id answered something else. When the server sent a body it is in
  `get-<n>.json` — render it and stop. A `301` and a dead connection carry no body, so there the
  printed status line is the whole answer.
- **`2`** — cannot run as given: bad arguments, no plan, or no `url=` / no credential.

Fold the result back into the table:

```bash
python3 "$SKILL_DIR/scripts/plan_tree.py" ./specs MYWS --status
```

Repeat every `--alias` override on this run. The walk is deterministic, so the same arguments
reproduce the same plan — and when they do not, the id sets no longer match `status.tsv` and the
script stops rather than showing a table that does not describe what would be created. That guard is
what stops a forgotten override from being confirmed as one thing and created as another.

Once the user has confirmed the table:

```bash
bash "$SKILL_DIR/scripts/create_plan.sh" apihub-plan
```

It refuses to start while `status.tsv` reports anything unresolved — a kind conflict, a redirect, an
unreadable check, a parent that is not a workspace or group — because the preview is the only thing
standing between a tree walk and fifty nodes nobody asked for.

Then it walks the plan in order, so a group always exists before its children. A node the check found
is reused rather than re-created. A node that fails takes its descendants with it, while unrelated
branches carry on. It prints one line per node and a tally:

```text
created  MYWS.very-long
failed   MYWS.backend (HTTP 400, body in apihub-plan/error-2.json)
blocked  MYWS.backend.billing-ap
blocked  MYWS.backend.orders
created  MYWS.collide-on

created 2, reused 0, failed 1, blocked by a failed parent 2
```

Exit codes:

- **`0`** — every node was created or reused.
- **`1`** — at least one node failed. Render its `error-<n>.json`, fix the cause, and re-run the whole
  sequence. Re-running is safe: the existence check turns everything already created into `reuse`, so
  only the failed branch is retried.
- **`2`** — cannot run as given: bad arguments, no plan, an unresolved existence check, or no `url=` /
  no credential.

## Portal links

The portal routes by kind, so a link is assembled from the node's `kind` and its **full** id:

| kind | URL |
| ---- | --- |
| `workspace` | `{base}/portal/workspaces/{packageId}` |
| `group` | `{base}/portal/groups/{packageId}` |
| `package` | `{base}/portal/packages/{packageId}` |

The id is always the complete dotted path — `SKILL.contracts.billing-ap`, never the trailing alias by
itself. That is the id the server computed, and the only one the portal resolves.

Two things make `/portal/packages/` a tempting and wrong default for every kind. The API's own
coordinates *are* uniform — `GET /api/v2/packages/{id}` serves workspaces, groups and packages alike
— so the portal looks like it should match, and it does not. And the portal is a single-page app: it
answers `200` with the same document for every path, including invented ones, because the routing
happens in the browser. So a wrong link cannot be detected by requesting it. It fails only in the
user's browser, after the run has already been reported as a success — which is the whole reason this
table exists rather than a rule of thumb.

## Rendering a backend error

An APIHUB error body is `{status, code, message, params, debug}`, where `message` is a template and
`params` holds the values. Three real rejections from this endpoint, each a different shape:

```json
{"status":409,"code":"1701","message":"Alias '$id' is already reserved. Please use another alias.","params":{"id":"SKILL.contracts"}}
```

```json
{"status":400,"code":"500","message":"Alias contains forbidden chars (not url-safe)"}
```

```json
{"status":404,"code":"22","message":"Package with packageId = $packageId not found","params":{"parentId":"SKILL.no-such-group"}}
```

The third is a backend defect rather than a shape to design around — its template and its params name
different keys — but it is a real response, so the recipe below has to survive meeting one.

Substitute each `$key` before showing it to the user. Otherwise the user reads a message with
placeholders in it and has to do the substitution in their head.

Read the body and render it yourself — no script:

```bash
cat response.json
```

Then apply this recipe:

1. Substitute each `$key` in `message` with `params[key]`. Join a **list** value with `, `.
2. If every placeholder resolved, print `status`, then `code` when present, then `: `, then the
   substituted message, and append `debug` on its own line when present. A `message` carrying no
   placeholders at all is already complete — the second example is.
3. If any `$placeholder` is still unresolved, stop rendering and **show the raw body exactly as it
   arrived**. The template and `params` disagreeing is a backend defect, not a shape to accommodate:
   the third example names `$packageId` while its params carry `parentId`. Do not guess that one was
   meant to fill the other, and do not quietly print a message with a placeholder still in it — the
   raw body is both the honest answer and what a bug report against the backend needs.

The first two render as:

```text
409 1701: Alias 'SKILL.contracts' is already reserved. Please use another alias.
400 500: Alias contains forbidden chars (not url-safe)
```

The third renders as itself, verbatim, with a line saying the server sent a message it did not supply
the values for.

`code` is an opaque identifier, not a symbolic name. The `500` above belongs to a `400` response and
the `22` to a `404`, so the resemblance to HTTP status numbers is a coincidence worth distrusting.
Print it for a bug report; never branch on it.

Report the rendered line — or the raw body, where it would not render — as-is, and stop. The message
is the server's current rule, and arguing with it client-side is how the two drift apart.
