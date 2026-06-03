# APIHub Agent Skills — Central Store

Central store of [APM](https://microsoft.github.io/apm/) (Agent Package Manager) **generic**
skills and instruction rules for APIHub Go repositories. One authored source is projected
onto Cursor, Claude Code, Copilot, and other harnesses via `apm install`.

Packages follow the [apm-authoring](https://github.com/Netcracker/qubership-ai-packages/tree/main/agent-packages/apm-authoring)
layout: each package lives at `agent-packages/<package-name>/` with primitives under `.apm/`.

**Repository-specific** packages (e.g. backend-only skills) belong in the consumer repository under
its own `agent-packages/` folder — not here.

## Authoring

This repository installs `apm-authoring` as a **devDependency** (see root `apm.yml`).
When editing anything under `agent-packages/`, the agent loads upstream authoring conventions
automatically after `apm install --dev` and `apm compile`.

To add or change packages, follow [apm-authoring](https://github.com/Netcracker/qubership-ai-packages/tree/main/agent-packages/apm-authoring)
— do not hand-maintain deployed harness files in this store.

## Catalog

| Package | Path | Scope | Summary |
|---------|------|-------|---------|
| `apihub-go-developer` | `apihub-go-developer/` | generic | Go backend workflow (layers, conventions, API-first, CI) |
| `apihub-go-self-review` | `apihub-go-self-review/` | generic | Post-implementation self-review checklist |
| `github-ticket-implementation-planner` | `github-ticket-implementation-planner/` | generic | Plan from GitHub issue; post approved plan as comment |
| `development-conventions` | `development-conventions/` | generic | Clarification workflow and CI super-linter / link-checker rules |
| `go-conventions` | `go-conventions/` | generic | Go error handling, constants, SQL, migrations, OpenAPI |

## How to consume

1. Add dependencies to the consumer repository root `apm.yml`:

```yaml
name: my-service
version: 0.0.0
dependencies:
  apm:
    - Netcracker/qubership-apihub-ci/agent-packages/apihub-go-developer
    - Netcracker/qubership-apihub-ci/agent-packages/go-conventions
```

Use the `#branch` suffix only while a store change is still on a feature branch (e.g.
`#apm_migration`). After merge, omit the suffix to track the default branch.

For **repo-specific** skills, add local paths alongside CI dependencies (see
`qubership-apihub-backend/agent-packages/` for an example).

2. Install and deploy:

```bash
apm install --target cursor,claude --legacy-skill-paths
```

3. Commit `apm.yml`, repo-local `agent-packages/` sources, and deployed `.cursor/` / `.claude/`
   harness trees. Gitignore only `apm_modules/`.

Skills are auto-discovered by each harness after install — no manual `AGENTS.md` skill
registration required.

## How to add a new skill or rule

1. Install [apm-authoring](https://github.com/Netcracker/qubership-ai-packages/tree/main/agent-packages/apm-authoring)
   as a devDependency in this repo (already configured) or read its skill when authoring.
2. **Generic** content → new folder under `agent-packages/<name>/` with `.apm/` layout.
3. **Single-repo specific** → add under `<consumer-repo>/agent-packages/` and reference with
   a relative path in that repo's `apm.yml`.
4. Every skill needs a paired `*.instructions.md` trigger; instruction-only packages need no skill.
5. Run `apm pack` in the package directory; fix all warnings.
6. Update this catalog table.

## Branch and update policy

Consumers track the store's default branch (no tag pin). Each `apm install` resolves the
latest commit and records the SHA in `apm.lock.yaml`. Re-run `apm install` to pick up store
changes.

## Validation

From any package directory:

```bash
apm pack
```

All packages in this store must pass without warnings before merge.

From the repository root (dev tooling):

```bash
apm install --dev
apm compile
```
