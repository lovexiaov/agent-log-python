"""Tiny demo: bootstrap + manual logs + child + redact + crash handler.

Run with:  python3 example/main.py
Output JSONL lands at <tmp>/agent-log/agent-log.jsonl (printed at the end).
"""

import os
import sys
import tempfile

# Make the agentlog package importable when run directly as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentlog import AgentLog, LoggingConfig
from agentlog.coretypes import install_crash_handler


def main():
    export_dir = os.path.join(tempfile.gettempdir(), "agent-log-demo")
    config = LoggingConfig(
        service="demo-app",
        env="dev",
        level="debug",
        redact_enabled=True,
        redact_paths=["custom_secret"],
        export_directory=export_dir,
    )
    AgentLog.bootstrap(config=config)

    # Appending extra sensitive keys (append-only; defaults always kept)
    AgentLog.redact(["custom_secret"])

    # Manual logs (agent_auto=False, respect min level)
    AgentLog.info("Application started", category="app", payload={"host": "demo.local"})
    AgentLog.warn("Low disk space", category="system", payload={"free_mb": 128})
    AgentLog.debug("Cache warmed", payload={"entries": 42})

    # Child logger: merges scope context, never mutates parent
    child = AgentLog.child({"user_id": "u-1234", "subsystem": "billing"})
    child.info("Invoice generated", payload={"invoice_id": "INV-9"})

    # Sensitive data is auto-masked at the logger layer
    AgentLog.error("Login failed", payload={"password": "hunter2", "custom_secret": "topsecret"})

    # Automatic instrumentation: uncaught exceptions become agent_auto crash events
    install_crash_handler()

    print("Export path:", AgentLog.export_path())

    # 默认不触发崩溃演示，使示例在 CI 中以退出码 0 正常结束（防退化）。
    # 想演示 crash handler 捕获未捕获异常时，运行：
    #   AGENTLOG_DEMO_CRASH=1 python3 example/main.py
    if os.environ.get("AGENTLOG_DEMO_CRASH") == "1":
        # sys.excepthook 会在进程退出前写入一条 crash 事件。
        raise RuntimeError("something went wrong in the billing pipeline")


if __name__ == "__main__":
    main()
