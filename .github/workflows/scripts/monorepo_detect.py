#!/usr/bin/env python3
"""Read ci/modules.yaml and a changed-files list; write detect booleans to GITHUB_OUTPUT."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required")


def changed_ids(cfg: dict, files: list[str]) -> set[str]:
    hit: set[str] = set()
    for name, patterns in (cfg.get("detect_paths") or {}).items():
        for pattern in patterns:
            prefix = pattern[:-3] if pattern.endswith("/**") else pattern.rstrip("*")
            for raw in files:
                norm = raw.replace("\\", "/")
                if pattern.endswith("/**") and norm.startswith(prefix):
                    hit.add(name)
                    break
                if norm == pattern or norm.startswith(str(pattern).rstrip("/") + "/"):
                    hit.add(name)
                    break
    return hit


def main() -> int:
    cfg = yaml.safe_load(Path(os.environ.get("MODULES_FILE", "ci/modules.yaml")).read_text(encoding="utf-8"))
    files = [
        line.strip()
        for line in Path(os.environ["CHANGED_FILES"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hit = changed_ids(cfg, files)
    image_hit = bool(hit & {"backend", "ui", "build-task-consumer", "api-linter-service", "agents-backend"})
    e2e_needed = bool(hit & {
        "backend", "ui", "build-task-consumer", "api-linter-service", "agents-backend",
        "postman", "ui-tests", "helm-compose", "commons-go",
    })
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        for key in ("backend", "ui", "api-linter-service", "agents-backend", "commons-go"):
            fh.write(f"{key.replace('-', '_')}={'true' if key in hit else 'false'}\n")
        fh.write(f"build_task_consumer={'true' if 'build-task-consumer' in hit else 'false'}\n")
        fh.write(f"any_image={'true' if image_hit else 'false'}\n")
        fh.write(f"e2e_needed={'true' if e2e_needed else 'false'}\n")
        fh.write(f"changed_ids={json.dumps(sorted(hit))}\n")
    print("changed:", sorted(hit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
