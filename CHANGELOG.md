# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/); this project adheres to
Schema v1 (frozen 2026-11-02).

## [1.0.0] - 2026-11-07

### Added
- Language-neutral `AgentLog` Python logging framework, stdlib-only (zero dependencies).
- `Logger` with `emit`, `child` (immutable parent), `set_level`, `redact` (append-only).
- Hand-rolled JSON serializer + minimal parser (`agentlog/json.py`) so the wire
  format top-level key set is guaranteed closed.
- Six levels (`trace|debug|info|warn|error|critical`); `warning` is a read-only
  alias normalized to `warn`; never written.
- Schema v1 wire format: required + optional top-level keys, `additionalProperties:false`.
- `Redactor` with default sensitive keys (password/token/authorization/cookie/secret/…),
  case-insensitive + separator-insensitive matching, dotted-path tail matching,
  free-text `key=value` / `Authorization: Bearer` masking, recursive dict/list masking.
- Sinks: `FileSink` (JSONL to `<export_directory>/agent-log.jsonl`) and `MemorySink` (tests).
- `LoggingConfig.from_json` (hand-rolled parser) with documented defaults + override.
- `install_crash_handler()` auto-instrumentation via `sys.excepthook` → `record_auto("crash", …)`.
- C7 `SchemaTests` validating every emitted line against Schema v1.
- Build/test tooling: `pyproject.toml`, CI (`actions/setup-python` 3.11 + unittest), docs, LICENSE (MIT).
