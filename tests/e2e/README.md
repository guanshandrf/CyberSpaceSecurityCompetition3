# P7 最小端到端验证

入口：`python scripts/check_phase.py P7`（包含 Web 测试），也可在根目录运行
`npm.cmd --prefix apps/web run test`。仓库 `.venv` 需安装 SDK、演示包和测试依赖。

`apps/web/src/P7.e2e.test.js` 在 jsdom 挂载真实 Vue App，通过 `p7_bridge.py` 的 NDJSON
桥调用真实 FastAPI TestClient。它实际运行 LangGraph、受控执行器、沙箱文件、SQLite 和
SSE，覆盖正常读取、越界拒绝、隐藏审计仍保护、恶意结果阻断、脱敏、HTML 文本显示、
单轮双工具关联及刷新后的历史恢复。桥进程阻止普通网络连接，仅标准库 socketpair IPC 例外。
使用隔离 `.cache/p7-e2e-*`，不读取真实凭据，不联网调用模型。

这不是实际浏览器布局或真实 TCP 分块验证；不得据此声称浏览器视觉 QA 已通过。

