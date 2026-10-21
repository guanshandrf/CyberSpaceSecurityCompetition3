# P7 验收：聊天界面与逐调用安全审计

结论：**PASS**。Windows / Python 3.13.9，SDK 0.6.0 未修改。
正式入口：696 Python + 19 Web = **715 passed，0 failed/errors/skipped**。
原 P6 的 667 Python + 2 Web 共 669 项按 classname/name 核对，全部保留且通过。

## 实现及边界

- `apps/web/src/App.vue`、`client.js`、`style.css`、`main.js`：Vue 3/Element Plus 聊天页，
  会话列表、逐节点 SSE、工具进度、错误、多调用审核卡片、Gate0/1/2、原因/策略、风险/耗时。
  审计开关只控制显示，不进入 API 请求；页面拒绝连接无 Guard 基线。
- `apps/api/src/agentguard_demo/history.py`、`protected.py`：装饰原 SQLiteAudit，另存安全
  展示历史。审计字段白名单化，模型标识 HMAC 别名化；未知策略/原因归类，参数不入审计。
  聊天展示文本再经公共 Redactor 脱敏，失败不回退原文。注册生命周期记录与调用 trace 分开。
- `api.py`、`service.py`：安全历史/审计分页、会话列表、相同持久事件的 SSE 和 JSON 接口；
  同会话展示流串行化；非同源 POST 和非本地 Host 拒绝。重启后旧会话只读，不重建执行预算。
- `tests/p7/test_history_api.py` 新增 29 项实际后端测试；Chat/client 单测及 P7.e2e.test.js
  合计新增 17 项 Web 测试。端到端实际运行 Vue/jsdom、FastAPI TestClient、LangGraph、SDK、
  沙箱文件、SQLite、SSE，覆盖单轮双工具、隐藏审计仍拒绝、恶意结果、脱敏、HTML 文本及刷新。
- `scripts/check_phase.py`、pytest marker、Vite 配置扩展正式入口至 P7。旧 P0 组件移至
  P0Shell.vue，原两项挂载/网络拒绝断言原样保留；未授权阶段拒绝测试顺延为 P8。
  P1 依赖边界测试仅允许 protected.py 使用公共 Redactor，基线无 SDK 的隔离测试仍通过。
- 更新 README、API README、架构/契约/威胁模型、docs/web-chat.md 和 E2E 说明。
  P2 公共协议和 SDK 27 个源码文件均未修改，源码与已安装 SDK 逐文件一致。

## 本轮新增问题复查与修复

1. 首次正式验收 Web 生产构建失败：CSS `@import` 指向 Element Plus 的 css.mjs，PostCSS
   把 JavaScript 当 CSS。改为 main.js 的 JavaScript 样式导入，生产构建和最后正式入口通过。
   首次真实 FAIL 结果及构建日志保存在 P7-first-formal-results.json / P7-first-formal-web-build.log。
2. 复查发现分页 after 无上限，超过 SQLite 有符号整数范围可能抛 OverflowError。新增
   `le=2**63-1`，增加 after=9223372036854775808 的实际 API 回归，验证返回 422。
3. 开发中 E2E 的 import.meta.url 被 jsdom 转为 HTTP URL，已改为 Vite 配置提供仓库路径。
   新并发测试最初把 Gate0 生命周期 trace 计入两轮会话 trace，已纠正测试预期并同时断言
   两项 Gate0 注册记录，未删除任何已有安全测试。相关开发失败日志保留。

复查覆盖审计投影失败默认拒绝、策略/标识脱敏、并发会话隔离、同会话序列、分页、重启、
DNS rebinding Host、跨源请求及 SDK 依赖方向。已知新增问题均修复；未声称完成外部安全审计。

## 命令与真实结果

工作目录均为 D:\Projects\Work\competition3；所有缓存与临时项目文件位于仓库内。

```powershell
New-Item -ItemType Directory -Force .cache/p7-install-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/p7-install-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps apps/api
.\.venv\Scripts\python.exe -m ruff format apps/api/src/agentguard_demo/api.py tests/p7/test_history_api.py
.\.venv\Scripts\python.exe scripts/check_phase.py P7
git diff --check
```

最后正式六步：pip check、ruff check .、ruff format --check .、Python 全量、Web 测试、
Web 生产构建均退出 0。Python 子命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2 or p3 or p4 or p5 or p6 or p7' --basetemp=.cache/pytest-P7 --junitxml=D:\Projects\Work\competition3\reports\generated\P7-python-junit.xml
```

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 | 34 | 0 | 0 | 0 |
| P1 | 57 | 0 | 0 | 0 |
| P2 | 126 | 0 | 0 | 0 |
| P3 | 186 | 0 | 0 | 0 |
| P4 | 47 | 0 | 0 | 0 |
| P5 | 29 | 0 | 0 | 0 |
| P6 | 188 | 0 | 0 | 0 |
| P7 Python | 29 | 0 | 0 | 0 |
| Web（含最小 E2E） | 19 | 0 | 0 | 0 |
| 合计 | 715 | 0 | 0 | 0 |

纯 SDK 环境未安装 LangGraph、langchain_core、FastAPI、演示包，隔离导入断言及 pip check
均退出 0；运行下列重叠核心回归为 **530 passed、0 failed/errors/skipped、14 deselected**。
这 14 项框架测试已在主环境全部执行通过，未跳过或从正式验收移除。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.cache\p6-security-sdk-venv\Scripts\python.exe -I -c "import importlib.util as u; import agentguard.contracts, agentguard.gates, agentguard.executor, agentguard.registry, agentguard.adapters; absent={x:u.find_spec(x) is None for x in ['langgraph','langchain_core','fastapi','agentguard_demo']}; assert all(absent.values()); print(absent)"
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pip check
.\.cache\p6-security-sdk-venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/security tests/p2 tests/p3 tests/p4 tests/p5 tests/p6/test_result_intents.py tests/p6/test_negation_scope.py tests/p6/test_contrast_advice.py -k 'not mixed_content_is_checked_before_real_graph_model_receives_it and not malformed_tool_calls_traverse_actual_langgraph_nodes and not contrast_and_advice_are_checked_before_graph_model' --basetemp=.cache/pytest-P7-sdk -o cache_dir=.cache/pytest-cache-P7-sdk --junitxml=reports/generated/P7-sdk-junit.xml
```

在 apps/web 子进程实际执行 npm.cmd run test、npm.cmd run build。产物 CSS 45.43 kB、
JS 142.93 kB（未 gzip）。另通过本地真实 TCP 的 Vite→Uvicorn 代理执行正常 SSE、三 Gate、
历史一致性、拒绝写入零文件副作用和跨源 403，证据 P7-http-smoke.json；它未验证浏览器布局。
默认 helper 失败时经工具审批运行相同仓库内命令，未扩大文件权限或访问父目录。

证据：reports/generated/P7-results.json、Python/Web JUnit、六步日志、P7-sdk-junit.xml/.log、
P7-review-results.json、P7-http-smoke.json、P7-diff-check.log 和开发日志。
关键证据另复制到 reports/evidence/P7，供 Git 备份；常规 generated 目录继续忽略。

## 限制与下一步

Gate1 硬拒绝、BLOCK/未批准 REVIEW 零副作用、权限/预算/防重放、Gate2 原文隔离、SDK 独立
测试均通过。started 只是准入意图，后置故障可能已产生副作用；未知状态不显示为未执行。

真实浏览器工具两次因 sandbox helper 启动失败，**浏览器视觉 QA 未验证**；最小 E2E 是
jsdom/ASGI，不冒充浏览器渲染。真实 HTTP 冒烟不证明所有 TCP 分块/断连时序。脱敏是有限
规则，私人文本仍需用户控制。没有认证、多租户隔离、历史保留/删除策略或远程部署保证；
只供本地单用户实验，重启历史只读，执行器/Provider 预算仍为单进程。

本阶段真实 DeepSeek、外部模型与 Benchmark 均 NOT_RUN。P8 已获后续真实实验授权，但
不能把该授权写为 P7 已运行。用户最新授权覆盖：P7 新问题修复和验收 → GitHub 备份 →
继续 P8、P9；本报告完成后按该顺序执行，不提前宣称后续阶段完成。
