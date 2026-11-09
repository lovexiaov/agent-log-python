# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/); this project adheres to
Schema v1 (frozen 2026-11-02).

## [Unreleased]

Schema v1.3（向后兼容增量）。

### Added

- 顶层可选 `release`：`Config(release="1.4.2")` 配置后在 emit 时统一盖章到**每条**事件
  （含自动埋点与崩溃事件），不校验格式、仅限非空且 ≤128 字符；未配置则不写该键。
- OTLP：`release` 映射为 resource 的 `service.version`。

### Changed（异常 payload 标准词表）

- 未捕获异常 / 崩溃事件统一按标准词表写 `payload`：`exception`（类型名）、
  `exception_message`（原始消息）、`stack`（单字符串）、`mechanism`
  （`uncaught` / `handled` / `reported`）。`install_crash_handler()` 的 payload 由 `thread` + 标准键组成。
- OTLP 适配器读取侧继续兼容历史键（`message` / `stacktrace` / `trace`），老日志
  映射行为不变。

### Docs

- 与 `ai-dev-spec` 的 Schema v1.3 / `INTERFACE.md` §4「异常与版本」对齐；
  说明框架只产出数据，不做上报 / APM 集成 / 崩溃落盘。

## [1.2.0] - 2026-11-07

### Changed（Schema v1.2，破坏性）

- `trace_id` 收紧为 **32 位小写 hex**（8 字节，与 OTLP `traceId` / W3C traceparent
  trace-id 同构）。大写自动归一；非法值在序列化边界**丢弃该字段、事件照写**，与
  `span_id` 策略一致。适配器不再对非 hex 值做 `sha256("agentlog:trace:"+raw)` 派生。
  发布时尚无生产使用方（Schema v1.2 描述内已注明）。
- session id 默认生成值改为 32 位小写 hex：`trace_id = session_id` 这个最自然的
  绑定永远合法。

### Added

- `newTraceId()`：生成 Schema 合法的 trace id（uuid4 去横线）。

### Docs

- README 自动埋点小节补上 `instrument_requests()`（patch `requests` 库 → `network_request`）
  与 `uninstall_crash_handler()`；线格式版本标注更正为 Schema v1.2。

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
- OTLP export adapter (`agentlog/otlp.py`): Schema v1 events → OTLP/JSON — one
  `LogRecord` per event plus a `SPAN_KIND_CLIENT` span for `network_request`
  (HTTP semconv) and `db_query` (Database semconv); deterministic trace/span ids;
  `OTLPSink` buffers events for `/v1/logs` + `/v1/traces` POSTs. Stdlib only.
- OTLP/HTTP exporter (`agentlog/otlp_http.py`): `OTLPExporter` puts those batches
  on the wire (one signal per request, empty signals skipped). Retries `408`/`429`/`5xx`
  and transport errors with exponential backoff; fails fast on other `4xx`;
  injectable `sleep` for deterministic tests.
- `EventType.DB_QUERY` (`"db_query"`) added for parity with the Go/Java SDKs.
- Schema v1.1: optional top-level `span_id` (16 lowercase hex chars, same shape as
  the W3C `traceparent` span-id). Bind it via `child({"span_id": …})` so all events
  of one operation share a span; malformed values are dropped instead of written.
- `db_query` payload vocabulary unified across SDKs: the SQL text is now `statement`
  (Go wrote `query`, Java `sql`); legacy keys are still accepted on read.
- C7 `SchemaTests` validating every emitted line against Schema v1.
- Build/test tooling: `pyproject.toml`, CI (`actions/setup-python` 3.11 + unittest), docs, LICENSE (MIT).

### Fixed
- `extra_resource` no longer duplicates resource attributes: keys agent-log owns
  (`service.name`, `session.id`, …) are skipped instead of appended, so the spec
  rule "agent-log's own fields win on conflict" actually holds. Previously the
  extra value came last and backends resolved the duplicate in its favour.
