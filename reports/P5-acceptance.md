# P5 验收报告：工具注册与更新审查

结论：**PASS**。报告补录于 2026-10-21；依据断点前已完成的正式验收证据，
不把补录时间当成重新运行时间。实际运行完成时间为 2026-10-21 01:00:15（Asia/Shanghai）。

## 完成情况

- Gate0 检查工具来源、名称/说明、Schema、能力与注册权限，输出 ALLOW/BLOCK/REVIEW。
- ToolRegistry 限制容量，绑定完整元数据与 ToolBinding 安全配置摘要，处理审批、TTL、
  同名冲突、版本更新及撤销。返回事件与内部记录隔离，避免嵌套 Schema 被篡改。
- Gate1/GuardedExecutor 的 registry 严格模式重验当前准入与注册代次；更新、过期、
  未批准及撤销工具不能执行。最终短租约绑定本次核销和 handler 选择。
- 注册审计复用脱敏 SQLite 存储；仅获准绑定进入工具集合。

主要文件：`src/agentguard/gates/gate0.py`、`detectors/registration.py`、
`registry/tools.py`、`gates/gate1.py`、`executor/guarded.py`、`audit/store.py`、
`tests/p5/`、`docs/gate0.md`，以及公共导出、版本和阶段验收入口。
未修改 P2 wire 协议，SDK 默认运行依赖仍仅 Pydantic。

## 命令与真实结果

工作目录为项目根目录，Windows、Python 3.13.9，普通安装 SDK 0.5.0。

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe scripts/check_phase.py P5
```

正式入口实际依次执行：`python -m pip check`、`python -m ruff check .`、
`python -m ruff format --check .`、以下 Python 测试及 Web 测试/构建。
这里的 python 均指上述仓库 `.venv\Scripts\python.exe`。

```powershell
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2 or p3 or p4 or p5' --basetemp=.cache/pytest-P5 --junitxml=D:\Projects\Work\competition3\reports\generated\P5-python-junit.xml
npm.cmd --prefix apps/web run test
npm.cmd --prefix apps/web run build
```

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 | 34 | 0 | 0 | 0 |
| P1 | 57 | 0 | 0 | 0 |
| P2 | 126 | 0 | 0 | 0 |
| P3（含加固） | 186 | 0 | 0 | 0 |
| P4 | 47 | 0 | 0 | 0 |
| P5 | 29 | 0 | 0 | 0 |
| Web | 2 | 0 | 0 | 0 |
| 合计 | 481 | 0 | 0 | 0 |

六个正式步骤退出码均为 0。准确 argv/cwd、耗时和日志见
`reports/generated/P5-results.json`；测试证据为同目录 P5-python-junit.xml、
P5-web-junit.xml。开发回归早期 258 项通过不是最终验收数量。
本报告没有补做人工浏览器或外部服务验证。

## 安全不变量与限制

已验证硬权限拒绝、BLOCK/未批准 REVIEW 零执行、预算、防重放、撤权/版本更新竞态、
Gate2 原始/安全结果隔离及审计脱敏，旧阶段无回归。真实 DeepSeek 与所有 Benchmark
在本阶段均 NOT_RUN；没有把 Fake 结果当成外部成绩。

静态元数据不能证明第三方代码安全。注册表为单实例单进程、无持久化，TTL 到期后需可信
后端重新注册。`registry=None` 的 P3 兼容配置不宣称 Gate0 保护；P6 必须走严格模式。
本阶段没有 Adapter 或演示 Agent 端到端保护，不能将 SDK 测试扩展成该声明。

必要测试全部通过，满足进入 P6 的条件；根据用户连续授权继续 P6，P6 后停止。
