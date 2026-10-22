# P7 交互补充验收：会话删除与详细安全审核

日期：2026-10-22。结论：**PASS**。仅演示 API / Web 的用户授权修改，不进入新阶段。
原有 P8 增强实验代码与数据保持原状；本轮未提交或推送代码，未调用真实模型或 Benchmark。

## 交付

- 会话列表增加独立删除按钮及二次确认。删除当前会话后选择剩余会话，最后一个删除后清空页面；删除失败不移除会话。
- DELETE 接口事务删除展示历史和会话行，关闭内存会话；独立 SDK 审计、已创建工具文件保留，共享模型预算不重置。
- 忙会话拒绝删除（409），删除后的旧排队请求不执行，跨源 DELETE 拒绝。归档会话也可删除，重启后不会重新出现在列表。
- 审核卡片补充 Gate 作用、阶段、原因/策略中文说明、时间、风险、可用耗时和实际执行含义。Gate0 生命周期不冒充每轮检查，未测量耗时不显示为实测零延迟。
- 没有工具调用的轮次明确说明没有逐调用审核；缺失记录不推定放行。Gate2 阻断不冒充工具未执行，也不宣称能撤销副作用。
- 复用既有脱敏审计字段，不新增原始参数、敏感 findings 或密钥。SDK、Gate、Executor、P2 公共协议未修改。

## 文件

- `apps/api/src/agentguard_demo/{api,history,service}.py`：删除接口、事务、同源约束及关闭状态。
- `apps/web/src/{App.vue,client.js,style.css,auditDetails.js}`：删除交互及审核解释。
- `tests/p7/test_session_deletion.py`：6 项删除/安全回归。
- `apps/web/src/{Chat.test.js,client.test.js,P7.e2e.test.js}`：7 项新增组件/传输测试，并扩展原 ASGI/jsdom 端到端测试至真实删除接口。
- `docs/web-chat.md`：删除范围与审核展示边界。

## 实际命令与结果

所有命令从项目根目录执行；临时目录和缓存均在仓库内。

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api tests/p7
.\.venv\Scripts\python.exe -m ruff format --check apps/api tests/p7
.\.venv\Scripts\python.exe -m ruff check tests/p7/test_session_deletion.py --fix
.\.venv\Scripts\python.exe -m ruff format tests/p7/test_session_deletion.py
$env:TEMP=(Join-Path (Get-Location) '.cache/phase-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-cache-dir --no-index --no-build-isolation --no-deps ./apps/api
.\.venv\Scripts\python.exe scripts/check_phase.py P9
```

首次静态检查发现新增测试的导入/格式问题，已格式化修正。首次正式验收 Python 782 通过，
Web 27 通过/2 失败（新增无工具审核卡影响原有工具卡计数；新增断言的样例实际含 Gate2，
不应期待缺失提示）。修复分类及新增样例后，保留原安全断言，补充测试并重新全量执行：

| 检查 | 真实最终结果 |
| --- | --- |
| P0–P9 Python 全量回归 | 782 passed，0 failed，0 errors，0 skipped |
| Web 全量测试（含真实 ASGI/LangGraph/SQLite/jsdom E2E） | 31 passed，0 failed，0 errors，0 skipped |
| Ruff check / format | PASS / PASS |
| pip check | PASS |
| Web 生产构建 | PASS |
| DeepSeek / Benchmark | NOT_RUN（本轮不需要） |

正式入口实际执行的全部子命令、时间、JUnit 计数见 `reports/generated/P9-results.json`；
日志和 XML 同目录。前轮未修改的 776 项 Python / 24 项 Web 测试继续保留。
本轮结果、日志和 JUnit 另存 `reports/evidence/P7-interaction-update/`，避免后续运行覆盖证据。

## 运行环境验证与限制

已更新本地后端；Vite 继续使用原端口 5173。重启桥接脚本位于忽略目录
`.cache/p7-ui-update/start.py`，仅明确加载根目录 `.env`，未读取/打印 Key。
保留重启前公开 `/models` 返回的已用共享预算 2 次。旧会话历史保留为只读，不重建旧执行权限。

经真实本地 Vite 代理创建一个空白 Fake 会话并 DELETE：204；随后 GET history：404。
防护仍 enabled/protected，DeepSeek 选项可用，共享预算仍已用 2 次，未产生模型请求。
本地 HTTP 冒烟记录：`.cache/p7-ui-update/http-smoke.json`。

当前自动化 E2E 为 jsdom/ASGI，不等同于真实浏览器视觉验收或 DeepSeek 实验。
删除为展示层逻辑删除，不擦除独立安全审计、工具文件或保证磁盘介质清除；
本地演示仍无身份认证。审核解释只说明已有记录，不能证明未记录的子检查或规则的通用检测能力。
