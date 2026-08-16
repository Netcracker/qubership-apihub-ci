# APIHUB publish reference

Companion to `SKILL.md`: the build config fields, the shell commands for each step, and the recipe
for rendering a backend error. `SKILL.md` holds the workflow and the rules — this file holds the
detail you need once you are already executing a step.

## Environment

Every command below needs `bash`, `curl` and Python 3, and nothing else. Python covers only three
jobs — building the sources zip, listing its entries, and classifying MCP documents. Everything
else is shell builtins. Two tools are deliberately avoided: `zip` and `unzip`, which Git for
Windows does not bundle, and a hardcoded `python3`, which the python.org installer does not
provide — it gives `python` and `py -3`. The config file is parsed with builtins for the same
reason: nothing has to be assumed about which text utilities a given Git for Windows install
carries.

On Windows the commands run in Git Bash (or WSL, where everything is plain Linux). Git Bash also
supplies `curl.exe`. PowerShell is not a substitute: its `curl` is an alias for `Invoke-WebRequest`
with unrelated flags, and none of the shell syntax below is valid there.

`SKILL.md` step 0 resolves two values before any work begins: the Python interpreter name and
`SKILL_DIR`. Both must be substituted **literally** into every command below — the shell does not
persist between tool calls, so assigning either to a variable in one call does not carry to the
next. Snippets here are written as `python3` and `$SKILL_DIR`; if the probe reported `python` or
`py -3`, use that instead.

Resolve `SKILL_DIR` to the directory containing this skill's `SKILL.md`, and **write it with
forward slashes** — a Windows-style `C:\Users\…` breaks inside a double-quoted bash string, where
the backslashes are escapes. Do not assume the current working directory is the skill directory.

### Bundled scripts

The helpers live beside `SKILL.md` and are invoked as files, never pasted inline:

| Script | Purpose |
| ------ | ------- |
| `scripts/apihub_env.sh` | Shared prelude — **sourced**, sets `base`, `cred`, `hdr`, `tok`. |
| `scripts/zip_sources.py` | Build `sources.zip` from the named files. |
| `scripts/list_zip.py` | Print an archive's file entries for `config.files[].fileId`. |
| `scripts/classify_mcp.py` | Print one line per MCP contract document, from loose files or `--zip`. |
| `scripts/poll_build.sh` | Poll a publish to a terminal status, or until the window elapses. |

Do not rewrite a script, and do not re-implement one inline. They encode the entry-name and
detection rules the backend enforces; an adapted copy is how `fileId` bugs get made.

One Git Bash rule the commands below already follow, and any command you improvise should too:

**Never pass a value that merely looks like a path as an argument to `curl` or `python`.** Git Bash
rewrites POSIX-looking arguments before handing them to a native `.exe`. For a real filesystem path
this is correct and wanted — `/c/Users/…` arrives as `C:/Users/…`, which is why passing
`$SKILL_DIR` and the source filenames as arguments is safe. For a value that is not a path it is
destructive: `/mcp/support` would arrive as `C:/Program Files/Git/mcp/support`. Nothing here needs
to pass one (an `mcpEndpoint` only ever travels inside the config file), but `MSYS_NO_PATHCONV=1`
is the escape hatch if you find a case that does.

## Configuration

Two files in the user's home directory. `$HOME` resolves the same way on macOS, Linux and Git Bash
on Windows, so one path serves all three — with `$USERPROFILE` as the fallback, because a Git Bash
that reads no startup file may have no `HOME` at all, while Windows puts `USERPROFILE` in every
process environment:

- `$HOME/.apihub/config` — non-secret settings, one `key=value` per line, no spaces around `=` and
  no quotes:

  ```text
  url=https://apihub.example.com
  ```

- `$HOME/.apihub/pat` — the personal access token on the first line, or `$HOME/.apihub/api-key` for
  a package-scoped API key. Which file exists decides which header is sent, so nothing has to be
  inferred from the value itself.

Shell state does not survive between tool calls, so each command loads what it needs itself. Every
command below opens by sourcing the shared prelude:

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"
```

It sets `base` (the URL, trailing slash removed), `cred`, `hdr` and `tok`. **Source it, do not
execute it** — an executed copy sets those variables in a subshell that dies immediately. On an
unusable configuration it prints which file is at fault and exits `2`, which ends the calling
command; that is intended, and it is the `2` in the polling exit codes below.

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
`-H "$hdr: $tok"` and never anywhere else.

Read what is configured without exposing anything:

```bash
apihub="${HOME:-$USERPROFILE}/.apihub"
cat "$apihub/config" 2>/dev/null || echo "no config file"
ls -l "$apihub/pat" "$apihub/api-key" 2>/dev/null
```

The config file holds no secrets, so printing it is fine. `ls -l` reports the credential files by
name and mode without reading them.

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

## Build config

```json
{
  "packageId": "MYWS.BACKEND",
  "version": "2026.1",
  "previousVersion": "2025.4",
  "status": "draft",
  "buildType": "build",
  "refs": [],
  "metadata": { "versionLabels": ["release-candidate"] },
  "files": [
    { "fileId": "orders-api.yaml", "labels": [], "publish": true },
    { "fileId": "orders-api-internal.yaml", "labels": [], "publish": true },
    { "fileId": "Billing API.yaml", "labels": [], "publish": true },
    {
      "fileId": "initialize.json",
      "labels": [],
      "publish": true,
      "metadata": { "mcpEndpoint": "/mcp/support" }
    },
    {
      "fileId": "tools.json",
      "labels": [],
      "publish": true,
      "metadata": { "mcpEndpoint": "/mcp/support" }
    }
  ]
}
```

### Field notes

- `buildType` is `"build"` for a version publish.
- `status` is `draft` or `release`.
- `previousVersion` is optional and drives the changelog. Use `""` when the user named no
  predecessor.
- `previousVersionPackageId` is only for a predecessor that lives in a *different* package. It must
  not equal `packageId`.
- `refs` is `[]` for a package publish. It carries dashboard references, which are out of scope for
  this skill. Because it is empty, the `resolveRefs` and `resolveConflicts` form values have nothing
  to act on — omit them.
- `metadata.versionLabels` is a list of free-form labels.
- `files[].publish` defaults to `true` and `labels` may be `[]`. As the example shows, a `fileId` may
  contain spaces — that is legal and must be preserved.
- `files[].metadata` is a free-form map. `mcpEndpoint` lives inside it — see below.
- `createdBy` is set by the backend from the caller's identity. Do not send it.
- Never send `migrationBuild`, `noChangeLog`, or `publishedAt`. They are migration-only and are
  rejected outright. Omit `publishId` too; the backend generates it.
- Only packages and dashboards accept a publish. Publishing to a group or a workspace is rejected.

## Assembling the zip

Build the archive from the files the user named. Run the command from the directory those relative
paths are relative to, quote every path, and pass the paths explicitly:

```bash
python3 "$SKILL_DIR/scripts/zip_sources.py" sources.zip \
  "orders-api.yaml" "orders-api-internal.yaml" "Billing API.yaml"
```

Passing each path explicitly is what makes the entry names usable as `fileId` values: zipping a
directory would prefix every entry with that directory, and flattening would drop the leading path
segments. The script's two guards hold the same shape on Windows: separators are normalised to `/`,
and an absolute or drive-qualified path is refused rather than written as a `C:/…` entry.

Then list the archive — the one built above, or one the user supplied — and use the entry names as
`config.files[].fileId`. Directory entries are filtered out, because the backend ignores them
inside the archive but rejects one listed as a `fileId`:

```bash
python3 "$SKILL_DIR/scripts/list_zip.py" sources.zip
```

## MCP contract documents

An MCP document needs `metadata.mcpEndpoint` on its `files[]` entry. Three rules govern it:

- **It is required.** The builder throws without it and the build fails, so the version never
  appears. The backend re-checks the build result and rejects it with code `1603`.
- **It must be a relative path starting with a single `/`** — `/mcp`, `/mcp/support`. An absolute
  URL is rejected, and so is a leading `//`. Note that APIHUB's own published `APIHUB_API.yaml`
  documents `mcpEndpoint: "https://api.example.com/mcp"` as its example; that value does not work.
  Trust this rule over that spec.
- **Exactly one init document is required per endpoint.** An endpoint that publishes tools, prompts
  or resources without an init fails the build. The other three kinds are each optional, though an
  init declaring a capability with no matching entities produces a warning.

The endpoint is not decoration: it is slugified into every `mcpEntityId` as
`{endpoint}-{kind}-{name}`, so `/mcp/test` yields `mcp-test-tool-find_customer` while `/test`
yields `test-tool-find_customer`. Change it and every entity is renamed, which breaks the changelog
against the predecessor. Because the id is scoped by endpoint, the same tool name under two
different endpoints is legal.

### Classifying documents

The builder detects MCP documents from their **JSON shape**, never their filename: `capabilities`
plus `serverInfo` means init, a `tools` array means tools, `resources` means resources, `prompts`
means prompts. Only the `.json` extension matters, and a JSON-RPC envelope is unwrapped first. So
`tools.json` is a human convention the backend never reads, and a document called anything at all
can be an MCP contract.

`scripts/classify_mcp.py` prints one line per MCP document and nothing for anything else,
so no file contents reach your context however large the sources are.

It reads documents from either place, and which form you use is decided by step 2:

```bash
# Archive you built: the entries are also files on disk.
python3 "$SKILL_DIR/scripts/classify_mcp.py" initialize.json tools.json orders-api.yaml

# Archive the user supplied: its entries are not on disk, so read inside it.
python3 "$SKILL_DIR/scripts/classify_mcp.py" --zip sources.zip
```

`--zip` classifies every `.json` entry in the archive, nested paths included, without extracting
anything. Picking the wrong form is the mistake to avoid: naming archive entries as paths finds
nothing on disk, and "found nothing" must never be read as "there are no MCP documents" — that
would omit `metadata.mcpEndpoint` and fail the build long after the `202`.

The script keeps those two cases apart for you. Classifications go to **stdout**, one line per
document; anything it could not open or parse goes to **stderr** as `cannot read …` or
`cannot parse …`. So an empty stdout means "no MCP documents" only when stderr is empty too, and a
run of `cannot read` lines means you passed paths for an archive that wanted `--zip`.

Each stdout line is `<name>`, tab, kind (`mcp-init`, `mcp-tools`, `mcp-resources`, `mcp-prompts`),
tab, detail — the server name and declared capabilities for an init, or the first few entity names
otherwise. Non-JSON files and JSON that is not an MCP document print nothing, which is correct.

It is a translation of the builder's logic, not the builder itself, so treat its output as a
proposal. If the user says a document is an MCP contract and the script did not flag it, attach the
endpoint anyway.

### Asking about several endpoints

With one init, ask for a single endpoint and apply it to every MCP document, naming the files so a
miss can be corrected. With two or more inits there are two or more servers, and nothing in a tools
or resources document says which one it belongs to — no path, no server name. Do not guess. Print
what the classifier found, including the entity names, which is what lets a human assign at a
glance, and ask for one line back:

```text
2 MCP servers detected (2 init documents):

  A  init-a.json   server "customer-support"  declares: tools, resources
  B  init-b.json   server "billing"           declares: tools

Unassigned:
  1  tools-a.json       mcp-tools      find_customer, list_support_cases, create_support_case
  2  resources-a.json   mcp-resources  getting_started, case_priority_policy
  3  tools-b.json       mcp-tools      get_invoice, refund

Endpoint for A and B, and which files go to each?
e.g.  A=/mcp/support 1,2   B=/mcp/billing 3
```

## Publishing

Write the build config to a file first, so no JSON has to survive shell quoting:

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"
pkg="MYWS.BACKEND"

curl -sS -o response.json -w '%{http_code}\n' -X POST \
  "$base/api/v2/packages/$pkg/publish" \
  -H "$hdr: $tok" \
  -F "config=<build-config.json" \
  -F "sources=@sources.zip"
```

Substitute the real `packageId` into the `pkg=` line; like every other shell variable here it is
gone by the next tool call.

`config=<file` sends the file *contents* as a plain form field, which is what the backend expects;
`config=@file` would send it as a file part instead. `sources=@sources.zip` is a genuine file
upload.

A `202` writes `{"publishId": "..."}` into `response.json`. Anything else is a failure — render it
with the recipe below and stop.

## Rendering a backend error

An APIHUB error body looks like this — a real rejection for a `fileId` that no zip entry matches:

```json
{
  "status": 400,
  "code": "1610",
  "message": "Files with fileIds '$fileIds' not found in '$location'",
  "params": { "fileIds": ["not-in-zip.yaml"], "location": "sources" }
}
```

`message` is a template and `params` holds the values, so substitute each `$key` before showing it
to the user. Otherwise the user reads a message with placeholders in it and has to do the
substitution in their head.

Read the body and render it yourself — no script:

```bash
cat response.json
```

Then apply this recipe:

1. Substitute each `$key` in `message` with `params[key]`. Join a **list** value with `, ` —
   `fileIds` above is a list.
2. Print `status`, then `code` when present, then `: `, then the substituted message.
3. Append `debug` on its own line when present.
4. Leave any `$placeholder` with no matching `param` exactly as it is. A `message` may carry no
   `params` at all; a partially-populated error is still worth showing.

The example above renders as:

```text
400 1610: Files with fileIds 'not-in-zip.yaml' not found in 'sources'
```

`code` is an opaque numeric identifier, not a symbolic name, so it is worth printing for a bug
report but never worth branching on.

Report the rendered line as-is and stop. The message is the server's current rule, and arguing with
it client-side is how the two drift apart.

## Polling

```bash
. "$SKILL_DIR/scripts/apihub_env.sh"
pkg="MYWS.BACKEND"; pub="<publishId from the 202>"

curl -sS "$base/api/v2/packages/$pkg/publish/$pub/status" \
  -H "$hdr: $tok"
```

The response carries a `status` of `none`, `running`, `complete`, or `error`, plus a `message` when
the status is `error`.

Two separate limits govern the wait:

- **The build's budget** — a large publish runs for **30 minutes or more**. Wait at least that long
  overall.
- **A single command's budget** — your own command timeout is far shorter (often 2 minutes, rarely
  more than 10), so one invocation cannot cover the build. Run the loop in **windows** and repeat
  it.

`scripts/poll_build.sh` polls for its window, then hands control back. Pass the ids as arguments
and keep the window comfortably below your command timeout:

```bash
bash "$SKILL_DIR/scripts/poll_build.sh" "MYWS.BACKEND" "<publishId from the 202>" 240
```

The window defaults to 240 seconds when omitted. Read the exit code:

- **`0`** — terminal status reached. Stop polling and report it.
- **`1`** — the status request itself failed: a `404` for a `publishId` that does not exist, a `401`
  for a credential that has expired mid-build. Render `status.json` with the error recipe above and
  stop; repeating the window will not help.
- **`2`** — it cannot run as given: bad arguments, or no `url=` or credential file. The message says
  which; fix that and run the command again.
- **`3`** — the window elapsed and the build is still going. Run the **exact same command** again.
  Nothing is lost between windows; the publish is server-side and the `publishId` stays valid.

Run it unchanged each window. Because the exit code is a contract the loop's internals implement —
the backoff, the `rm -f`, the whitelist below — an edited copy can report a status the code no
longer means.

The HTTP code is checked separately from the body because `status` carries two different things: the
build status on a `200`, and the numeric HTTP status on a failure. `{"status":404,"message":"build
not found"}` would otherwise read as a status that is merely not `complete` yet, and the loop would
keep polling a build that will never exist. The status match is a closed whitelist of the four build
statuses for the same reason: that `404` body matches none of them and falls through to
`unreadable`.

Reading the status needs no interpreter — `${body//[[:space:]]/}` strips every space, tab and
newline first, so the match holds whether or not the server pretty-prints. Backoff doubles from 2s
to a 30s ceiling: a five-second build is noticed in five seconds, and a thirty-minute one costs
about sixty requests.

The timestamps it prints let you report how long the build has been running once it has spanned
several windows; track the total elapsed time yourself across them. A connection that never answered
reports `000`, which is treated as transient: it prints `unreadable` and the loop polls again, since
one blip over sixty requests is not a reason to abandon a running build.

What to tell the user for each status — and why `none` and `running` mean opposite things once the
wait has run long — is in `SKILL.md` step 6.
