---
name: apihub-skill-author
description: Walks through adding a new skill or instruction rule to the APIHub agent-skills store or a consumer repository. Use when creating, extending, or publishing agent skills and rules for APIHub repositories.
---

# APIHub Skill Author

Guide for contributing agent skills and rules in the APIHub ecosystem.

## 1. Decide scope and placement

| Content type | Generic (shared across Go repos) | Repo-specific (one service) |
|--------------|----------------------------------|------------------------------|
| **Skill** (workflow checklist) | `qubership-apihub-ci/agent-skills/skills/apihub-go-*` | `<repo>/agent-skills/skills/<name>/` |
| **Instruction** (glob rule) | `qubership-apihub-ci/.../go-conventions/` or `common-conventions/` | `<repo>/agent-skills/instructions/<group>/` |

- **Generic** content goes in the CI central store; consumers add a Git dependency in `apm.yml`.
- **Repo-specific** content stays in that repository's `agent-skills/` folder and is referenced
  with a relative path (e.g. `./agent-skills/skills/my-skill`).
- Repo-specific skills should depend on generic CI packages via `apm.yml` `dependencies`.
- Name shared skills `apihub-<topic>` (lowercase, hyphens).

## 2. Scaffold a skill bundle (HYBRID)

Create a directory under the chosen `agent-skills/skills/<name>/`:

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

Repo-specific skills should depend on generic CI packages:

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

## 6. Update documentation

- **CI store packages:** add a row to `qubership-apihub-ci/agent-skills/README.md`.
- **Repo-local packages:** add a row to `<repo>/agent-skills/README.md`.

## 7. Consumer rollout

Add dependencies to root `apm.yml` (Git refs for CI store, `./agent-skills/...` for local)
and run:

```bash
apm install --target cursor,claude --legacy-skill-paths
```

Commit `apm.yml` + `apm.lock.yaml`; gitignore deployed `.cursor/` / `.claude/` dirs.
Commit repo-local `agent-skills/` sources.

## Checklist before opening PR

- [ ] Generic vs repo-specific placement is correct.
- [ ] Both `SKILL.md` and `apm.yml` descriptions populated (skills).
- [ ] `apm pack` passes without warnings.
- [ ] Relevant catalog readme updated.
- [ ] Relative links in skills assume deploy path `.cursor/skills/<name>/`.
