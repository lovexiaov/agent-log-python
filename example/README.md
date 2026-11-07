# Python 示例演示

演示 [agent-log-python](../README.md)（仅标准库，`unittest` 测试，无第三方依赖）的端到端用法，对应契约能力：

- `bootstrap` + `LoggingConfig`（service / env / level / redact）
- 6 档级别：`trace / debug / info / warn / error / critical`
- `child`：合并作用域上下文，返回新 logger，父级不变
- `redact`：默认敏感键不可关闭，可追加自定义键
- `install_crash_handler`：未捕获异常被记为 `crash` 事件（`agent_auto=true`）

## 运行

在仓库根目录执行：

```bash
python3 example/main.py
```

JSONL 落盘于临时目录的 `agent-log-demo/agent-log.jsonl`，程序结束前会打印该路径。

> 注意：示例末尾会主动抛 `RuntimeError` 以演示 crash 自动埋点，进程将以非 0 退出码结束，属预期行为。
