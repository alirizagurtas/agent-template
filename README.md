# Agent Template

A minimal Python project template for coding-agent tasks with strict typing,
focused validation, and a generated project-structure index.

## Validation

```bash
uv run --locked poe test-target <path_or_node_id>
uv run --locked poe check
```

`project_structure.yaml` records source domains, their tests, and inter-domain
dependencies. Update it through `uv run --locked poe sync-project-structure`.

## Harness

`scripts/run_harness.sh` runs an identical coding prompt repeatedly against a
clean Git baseline and writes structured reports to `harness_runs/`. It is
optional and is not part of `poe check`.

```bash
uv run --locked poe run-harness <prompt-file> HEAD "uv run --locked poe check" 5
```

The harness uses `git reset --hard` and `git clean -fd` between runs. Use it
only with a committed baseline and a repository whose tracked contents may be
discarded.
