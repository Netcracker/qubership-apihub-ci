# APIHub Agent Skills — Central Store

Central store of [APM](https://microsoft.github.io/apm/) (Agent Package Manager) **generic**
skills and instruction rules for APIHub Go repositories. One authored source is projected
onto Cursor, Claude Code, Copilot, and other harnesses via `apm install`.

**Repository-specific** packages (e.g. backend-only skills) belong in the consumer repository under
its own `agent-packages/` folder — not here.

## Catalog

| Package | Path | Scope | Summary | Key dependencies |
|---------|------|-------|---------|------------------|
| `apihub-go-developer` | `skills/apihub-go-developer/` | generic | Go backend workflow (layers, conventions, API-first, CI) | — |
| `apihub-go-self-review` | `skills/apihub-go-self-review/` | generic | Post-implementation self-review checklist | — |
| `github-ticket-implementation-planner` | `skills/github-ticket-implementation-planner/` | generic | Plan from GitHub issue; post approved plan as comment | — |
| `apihub-skill-author` | `skills/apihub-skill-author/` | generic | How to add new skills/rules to this store | — |
| `common-conventions` | `instructions/common-conventions/` | generic | Always-on rules (clarify before coding) | — |
| `go-conventions` | `instructions/go-conventions/` | generic | Go error handling, constants, SQL, migrations, OpenAPI, CI linters | — |

## How to consume

1. Add dependencies to the consumer repository root `apm.yml`:

```yaml
name: my-service
version: 0.0.0
dependencies:
  apm:
    - Netcracker/qubership-apihub-ci/agent-packages/skills/apihub-go-developer
    - Netcracker/qubership-apihub-ci/agent-packages/instructions/go-conventions
```

Use the `#branch` suffix only while a store change is still on a feature branch (e.g.
`#apm_migration`). After merge, omit the suffix to track the default branch.

For **repo-specific** skills, add local paths alongside CI dependencies (see
`qubership-apihub-backend/agent-packages/` for an example).

2. Install and deploy:

```bash
apm install --target cursor,claude --legacy-skill-paths
```

3. Commit `apm.yml`, `apm.lock.yaml`, repo-local `agent-packages/` sources, and deployed
   `.cursor/` / `.claude/` harness trees. Gitignore only `apm_modules/`.

Skills are auto-discovered by each harness after install — no `AGENTS.md` registration
required.

## How to add a new skill or rule

Use the **`apihub-skill-author`** skill (install it from this store or read
`skills/apihub-skill-author/SKILL.md` directly). In short:

1. **Generic** → add under this store (`apihub-go-*`, `go-conventions/`).
2. **Single-repo specific** → add under `<consumer-repo>/agent-packages/` and reference with
   a relative path in that repo's `apm.yml`.
3. Scaffold a HYBRID skill bundle (`SKILL.md` + `apm.yml`) or an instruction package
   (`.apm/instructions/*.instructions.md` + `apm.yml`).
4. Declare transitive deps on generic CI packages where needed.
5. Run `apm pack` in the package directory; fix all warnings.
6. Update this catalog table (CI store only).

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
