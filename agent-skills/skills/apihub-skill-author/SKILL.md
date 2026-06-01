---
name: apihub-skill-author
description: Walks through adding a new skill or instruction rule to the central APIHub agent-skills store in qubership-apihub-ci. Use when creating, extending, or publishing agent skills and rules for APIHub repositories.
---

# APIHub Skill Author

Guide for contributing to the central store at `qubership-apihub-ci/agent-skills/`.

## 1. Decide scope and placement

| Content type | Generic (any Go repo) | Repo-specific (backend, etc.) |
|--------------|----------------------|-------------------------------|
| **Skill** (workflow checklist) | `agent-skills/skills/apihub-go-*` | `agent-skills/skills/apihub-backend-*` |
| **Instruction** (always-on / glob rule) | `agent-skills/instructions/go-conventions/` or `common-conventions/` | `agent-skills/instructions/backend-conventions/` |

- Generic content belongs in `apihub-go-*` packages; repo-specific content depends on them via `apm.yml`.
- Name new skills `apihub-<topic>` (lowercase, hyphens).

## 2. Scaffold a skill bundle (HYBRID)

Create a directory under `agent-skills/skills/<name>/`:

```text
<name>/
  SKILL.md          # required — frontmatter: name, description
  apm.yml           # required — name, version, description, dependencies
  reference.md      # optional
  scripts/          # optional
```

**SKILL.md frontmatter** (agent runtime reads this):

```yaml
---
name: my-skill-name
description: One paragraph describing when the agent should use this skill.
---
```

**apm.yml** (human-facing metadata + deps):

```yaml
name: my-skill-name
version: 0.1.0
description: Short tagline for apm view/search (under ~80 chars)
dependencies:
  apm:
    - Netcracker/qubership-apihub-ci/agent-skills/skills/apihub-go-developer
```

Omit `dependencies` for fully standalone skills. Pin `#branch` only during active migration work.

## 3. Scaffold an instruction package

Create `agent-skills/instructions/<group>/`:

```text
<group>/
  apm.yml
  .apm/instructions/
    my-rule.instructions.md
```

**Instruction frontmatter:**

```yaml
---
description: One-line summary of the rule
applyTo: "**/*.go"
---
```

- Map old Cursor `globs:` to `applyTo:` (comma-separated for multiple globs).
- Omit `applyTo` only for rules that should apply unconditionally (always-on).
- Body is Markdown below the frontmatter.

## 4. Declare transitive dependencies

Repo-specific skills should depend on generic ones:

```yaml
dependencies:
  apm:
    - Netcracker/qubership-apihub-ci/agent-skills/skills/apihub-go-developer
```

Consumers install the specific package; generic deps resolve transitively.

## 5. Validate

From the package directory:

```bash
apm pack
```

Fix all warnings (missing `description`, frontmatter issues, etc.).

## 6. Update the catalog

Add a row to `agent-skills/README.md` (package | path | scope | summary | deps).

Link the catalog from `qubership-apihub-ci/README.md` if this is a new top-level section.

## 7. Consumer rollout

Consumers add the dependency to root `apm.yml` and run:

```bash
apm install --target cursor,claude --legacy-skill-paths
```

Commit `apm.yml` + `apm.lock.yaml` only; deployed `.cursor/` and `.claude/` dirs are gitignored.

## Checklist before opening PR

- [ ] Generic vs specific placement is correct.
- [ ] Both `SKILL.md` and `apm.yml` descriptions populated (skills).
- [ ] `apm pack` passes without warnings.
- [ ] `agent-skills/README.md` catalog updated.
- [ ] Relative links in skills assume deploy path `.cursor/skills/<name>/`.
