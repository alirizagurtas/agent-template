# AGENTS.md

## Mandatory rules

1. Never use an f-string literal directly in `raise`. Assign the message to a
   variable, then raise the project-specific exception.
2. Never expose `Any` in a function signature, including test helpers. Narrow
   untyped loader results at their boundary with `cast(object, ...)` and
   `isinstance` checks.
3. Before checking keys of an object-valued dictionary, cast it to
   `dict[object, object]`. Do not inspect keys directly on an untyped mapping.
4. Do not use `set().union(*generator)`. Initialize `set[T]` and call `update`
   in a plain loop.
5. Do not return `argparse.Namespace` or access its attributes without a
   direct cast. Parse arguments into typed primitive values.
6. Test scripts through a separate process; never dynamically import them with
   `importlib.util`.
7. In `src/` and `scripts/`, define every numeric comparison value as a
   module-level `UPPER_SNAKE_CASE` constant, including `len()` comparisons.
8. Keep every function at eight or fewer branches and six or fewer returns.
   Extract named single-responsibility helpers before implementation.
9. Keep imports standard-library, third-party, then local, alphabetized within
   each group. Do not retain unused imports.
10. Write separate tests for independent requirements. Do not combine more
    than two unrelated scenarios in a single test.
11. Boolean function parameters must be keyword-only. Never pass a positional
    boolean.
12. Raise a module-specific exception rather than a built-in general-purpose
    exception.
13. Never use bare `except` or `except Exception`. Catch concrete exception
    types only.

## General rules

- Do not hardcode project, package, or source/test paths. Read them from
  `project_structure.yaml`.
- Keep changes within the requested implementation and test files. Do not
  modify dependencies, tooling, or unrelated files unless explicitly asked.
- Keep repository content in English, using UTF-8 file I/O.

## Validation order

After changing Python code, run these commands in order:

```bash
uv run --locked ruff check --fix <changed-files>
uv run --locked ruff format <changed-files>
uv run --locked poe test-target <path-or-node-id>
uv run --locked poe check
```

Run `uv run --locked poe test-integration` only when the change affects an
integration boundary. Do not alter the default `poe check` workflow.

## Project structure index

`project_structure.yaml` is the source of truth for a domain's path, tests,
and direct domain dependencies. Read it before scanning the repository for
those facts. It does not replace reading source code when behavior or APIs are
needed.

When source domains, indexed tests, or inter-domain imports change, run:

```bash
uv run --locked poe sync-project-structure
```

Run it before the final quality gate. Never edit `domains` by hand; the sync
script owns that field. The `version`, `package`, and `paths` fields remain
manually maintained configuration.
