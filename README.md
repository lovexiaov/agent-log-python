# AgentLog — Python

Language-neutral, structured logging framework for Python. Emits **Schema v1** JSONL
conforming to [`docs/schema/log-event.schema.json`](docs/schema/log-event.schema.json)
— identical to the Kotlin (`agent-log-android`), Swift (`agent-log-macos`),
TypeScript (`agent-log-web`) and Java/Go siblings.

**Zero dependencies.** Standard library only. The wire-format serializer is
hand-rolled, so the top-level key set is guaranteed closed (`additionalProperties: false`).

## Quickstart

```python
from agentlog import AgentLog, LoggingConfig

# Bootstrap once (defaults: service="app", level="info", redact on, export to <tmp>/agent-log)
AgentLog.bootstrap(config_json='{"service": "my-app", "level": "debug"}')

AgentLog.info("hello world", payload={"host": "example.com"})
AgentLog.warn("low disk", category="system", payload={"free_mb": 128})
AgentLog.error("boom", payload={"password": "hunter2"})  # password auto-masked

# Child logger — merges scope, never mutates the parent
child = AgentLog.child({"user_id": "u-1", "subsystem": "billing"})
child.info("invoice created", payload={"invoice_id": "INV-9"})

# Append-only redaction paths
AgentLog.redact(["my_secret"])

print("Export:", AgentLog.export_path())
```

## API

Module-level facade (`agentlog`):

| Method | Description |
| --- | --- |
| `bootstrap(config=None, config_json=None, sink=None)` | Initialize the singleton logger. |
| `info/warn/error/debug/trace/critical(message, category="app", trace_id=None, payload=None)` | Manual log (`agent_auto=False`). |
| `record_auto(event_type, message, category="auto", trace_id=None, payload=None)` | Auto-instrumented log (`agent_auto=True`, always written). |
| `child(context)` | New logger merging scope fields (parent unchanged). |
| `set_level(level)` | Set minimum output level. |
| `redact(paths)` | Append sensitive key paths (defaults can't be removed). |
| `export_path()` | Path of the emitted JSONL file. |

### Levels

`trace | debug | info | warn | error | critical` (6, lowercase). `warning` is a
read-only alias that is **never written** — it normalizes to `warn` on read.

### Wire format (Schema v1.3)

Required top-level keys: `ts, level, service, event_type, session_id, agent_auto, message`.
Optional: `subsystem, category, env, release, user_id, trace_id, span_id, payload`. No other keys allowed.

`release` (v1.3) is a **config-level** identifier (`LoggingConfig(release="1.4.2")` or
`{"release": "1.4.2"}` in the config JSON) stamped on every event by the logger — semver,
git sha or build number, ≤128 chars, no format validation. Omit it and the key is not written;
when present it becomes `service.version` in the OTLP resource.

Crash / hang payloads follow the v1.3 vocabulary: `exception` (type name),
`exception_message`, `stack` (single string) and `mechanism`
(`uncaught | handled | reported`).
Manual logs use `event_type="log"`; auto events use `network_request | db_query | crash | hang | screen_view | ui_interaction`.

`span_id` (v1.1) is 16 lowercase hex chars (8 bytes), the same shape as the W3C
`traceparent` span-id. Bind it on a child logger so every event emitted inside an
operation shares one span — and, when exported to OTLP, one `spanId`:

```python
span = AgentLog.child({"trace_id": "0123…", "span_id": "a1b2c3d4e5f60718"})
span.info("invoice generated")              # -> span_id: a1b2c3d4e5f60718
span.record_auto("network_request", "GET /orders -> 200", payload={...})
```

A malformed `span_id` is dropped (never written), so a bad value can't produce a
schema-violating line; exporters then derive one deterministically.

### Configuration (`LoggingConfig.from_json`)

| Key | Default | Notes |
| --- | --- | --- |
| `service` | `"app"` | Required, non-empty. |
| `env` | — | dev/staging/prod. |
| `level` | `"info"` | Min level (write side; `warning`→`warn`). |
| `redact_enabled` | `true` | Master toggle. |
| `redact_paths` | `[]` | Append to default sensitive keys. |
| `export_directory` | `<tmp>/agent-log` | Output dir for `agent-log.jsonl`. |

### Automatic instrumentation

Two opt-in helpers are provided (the package stays standard-library only —
`requests` is a soft dependency, so `instrument_requests` is a no-op when it is
not installed):

```python
from agentlog import install_crash_handler, instrument_requests

install_crash_handler()   # sys.excepthook -> record_auto("crash", ...) with stack
instrument_requests()     # monkey-patch requests.Session.send -> network_request
```

- `install_crash_handler()` — installs a `sys.excepthook` that records uncaught
  exceptions as `crash` auto-events (with `thread` / `exception` / `stack`);
  `uninstall_crash_handler()` restores the previous hook.
- `instrument_requests()` — patches `requests.Session.send` (idempotent) so every
  HTTP call emits a `network_request` auto-event. For clients other than
  `requests` (e.g. `urllib`), call `record_network_request(...)` directly.

Crash handlers, signal handlers, or a context-manager can be plugged in; any of
them should call `record_auto(...)` so the event carries `agent_auto: true`.

### OTLP export (OpenTelemetry)

`agentlog.otlp` translates already-emitted Schema v1 events into **OTLP/JSON**,
so they can be shipped to any OpenTelemetry-compatible backend (Jaeger, Tempo,
Loki, Grafana, Datadog …) without changing the wire format.

```python
from agentlog import OTLPSink, to_otlp_json
from agentlog.otlp import to_otlp

sink = OTLPSink(extra_resource={"service.version": "1.3.0"})
AgentLog.bootstrap(config=config, sink=sink)

AgentLog.info("checkout started", payload={"cart_size": 3})
record_network_request("GET", "https://api.example.com/orders", 200, 14)  # -> CLIENT span

batch = sink.drain()                       # or: to_otlp(jsonl_lines)
logs_body = to_otlp_json(batch["logs"])    # POST to <collector>/v1/logs
traces_body = to_otlp_json(batch["traces"])# POST to <collector>/v1/traces
```

The posting itself is one call — `agentlog.otlp_http.OTLPExporter` handles
one-signal-per-request, skipping empty signals, and the OTLP retry policy:

```python
from agentlog import OTLPExporter

exporter = OTLPExporter("http://localhost:4318")   # OTLP/HTTP default
exporter.export(batch)                             # or exporter.export_sink(sink)
```

`2xx` succeeds; `408`/`429`/`5xx` and transport errors retry with exponential
backoff (100 ms base, doubling, capped at 64×); other `4xx` fail fast because a
malformed or unauthorised payload will not fix itself. Defaults: 2 retries, 10 s
timeout.

> The exporter is a transport, not a queue (no batching timer, no disk buffer,
> no backpressure). In production point it at a local Collector.

Mapping contract (details in `docs/logging-framework/OTLP-MAPPING.md`):

| agent-log | OTLP |
| --- | --- |
| every event | one `LogRecord` |
| `level` | `severityNumber` 1/5/9/13/17/21 (`critical` → `FATAL`) |
| `service` / `env` / `session_id` | resource `service.name` / `deployment.environment` / `session.id` |
| `trace_id` | `traceId` (32-hex; opaque values hashed deterministically) |
| `span_id` | `spanId` (used verbatim when valid; derived only when absent) |
| `event_type` / `agent_auto` / `subsystem` / `category` | attributes `agent.event.type` / `agent.auto` / `agent.subsystem` / `agent.category` |
| `user_id` | `enduser.id` |
| `payload.*` | `payload.<key>` attributes (ints as strings per proto3 JSON) |
| `network_request` | + `SPAN_KIND_CLIENT` span (`http.request.method`, `url.full`, `http.response.status_code`) |
| `db_query` | + `SPAN_KIND_CLIENT` span (`db.system`, `db.operation`, `db.statement`) |
| `crash` / `hang` | LogRecord + `exception.type` / `exception.message` / `exception.stacktrace` |

Ids are **deterministic**: an event's own `span_id` (Schema v1.1) is used verbatim;
otherwise ids are SHA-256 derived, so re-exporting the same event yields the same
`traceId`/`spanId` and retries stay idempotent.

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

All tests use the standard library (`unittest`); no `pytest` required.

## Repository layout

```
agentlog/   core implementation (stdlib only)
tests/      unittest suites incl. C7 SchemaTests
docs/       INTERFACE.md + Schema v1 (copied verbatim from ai-dev-spec)
example/    tiny runnable demo
```
