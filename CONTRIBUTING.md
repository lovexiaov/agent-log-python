# Contributing to AgentLog (Python)

Thanks for contributing! This package is **standard-library only** — no third-party
dependencies are allowed.

## Prerequisites

- Python 3.8+ (CI runs on 3.11).
- No `pip install` of runtime/test dependencies. The JSON serializer, parser,
  redactor, and sinks are all hand-rolled.

## Build / Test

```bash
# Compile-check the package
python3 -m py_compile agentlog/*.py

# Run the full test suite (C7 SchemaTests included)
python3 -m unittest discover -s tests -v
```

All tests must be GREEN before a PR is merged.

## Lint

If `ruff` is available:

```bash
ruff check .
```

Otherwise `python3 -m py_compile` is sufficient. A `.editorconfig` enforces
4-space indentation for Python.

## Contract rules (do not break)

1. The wire format MUST validate against `docs/schema/log-event.schema.json`. No
   extra top-level keys (`additionalProperties: false`).
2. The 6 levels are `trace|debug|info|warn|error|critical`. Never write `warning`.
3. Non-reserved fields go into `payload`. Map camelCase → snake_case only at the
   serialization boundary.
4. Redaction is enforced at the logger layer. Default sensitive keys are
   append-only and can never be removed.
5. `child()` returns a NEW logger; it must not mutate the parent.

## CI

`.github/workflows/ci.yml` sets up Python 3.11 and runs the unittest suite.
