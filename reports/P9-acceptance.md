# P9 异构接入、工程加固与交付验收

结论：**PASS（P9 工程范围）**。2026-10-22，Windows/Python3.13.9，正式入口P0–P9
**759 passed（740 Python+19 Web），0 failed/errors/skipped**。P8仍为PARTIAL，不能因此
将项目全部验收标记为通过；详见final-acceptance.md。用户已授权连续完成全部后续工程。

## 完成内容与位置

- src/agentguard/adapters/simple.py：SafeReply（25行）、SimpleAdapter（33行）、metadata副本
  tools（92行）、撤权（104行）、Gate0续期（115行）、事件标准化（141行）、invoke（167行）、
  精确事件审批重试execute（175行）、只回传Gate2安全结果（184行）、非法调用拒绝审计（194行）。
  不引入框架/Provider/Benchmark依赖。
- examples/simple_agent.py：与LangGraph不同的有界纯Python循环，确定性模型替代，实际执行
  ToolRegistry→GuardedExecutor→ResultHandler和SQLite；不复制Gate/Policy/Detector规则。
- tests/p9/conftest.py、test_simple.py：29项新增测试，覆盖合法/非法工具、权限、REVIEW零副作用、
  注入BLOCK/敏感字段SANITIZE、工具/插件/审计异常、并发重放/预算/容量、审批到期/拒绝/精确
  重试、注册过期/续期失败/撤销、摘要变化及检测期间撤权。
- scripts/stress_simple.py：真实本地SQLite压力探针，1/8线程，无害原工具基线，重放/预算断言。
- scripts/check_phase.py、pyproject.toml、apps/web/vite.config.js：P9累计验收；未授权阶段拒绝
  测试由P9迁至不存在的P10，没有删除或削弱旧安全测试。
- tests/integration/test_installation.py：隔离导入simple，额外禁止agentguard_bench；
  tests/unit/test_package.py保留父包不急切导入框架约束。
- SDK版本0.9.0；API可选guard和独立评测包同步约束。P2契约源码相对P7备份完全未变。
- README、docs/simple-agent.md、deployment.md、architecture.md、threat-model.md补充交付说明。

## 实际命令与结果

全部命令工作目录 D:\Projects\Work\competition3。安装显式设置仓库TEMP/TMP；没有输出或修改真实Key。
普通测试禁网/移除凭据，P9没有真实API或Benchmark请求。

```powershell
New-Item -ItemType Directory -Force .cache/task-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/task-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . apps/api .\benchmarks
.\.venv\Scripts\python.exe scripts/check_phase.py P9
```

六步全PASS：pip check、ruff check .、ruff format --check .、累计Python pytest、Web npm
run test和npm run build。精确子命令、退出码与耗时见evidence/P9/P9-results.json。
P8原有711项Python逐标识比对全部保留通过，新增29项。28个SDK源码文件逐字节匹配.venv
实际安装文件，没有通过PYTHONPATH偷偷替换已安装包。

新增测试单独运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/p9 -q --basetemp=.cache/pytest-p9-first --junitxml=reports/generated/P9-new-first.xml
.\.venv\Scripts\python.exe -m pytest tests/p9 -q --basetemp=.cache/pytest-p9-second --junitxml=reports/generated/P9-new-final.xml
```

首轮24通过/1失败（当时25项）：新增断言误以为撤销续期返回空值，注册表实际按协议返回
BLOCK RegistrationResult。修正为验证全BLOCK、Gate0不重跑、不可暴露/执行，没有放宽安全
要求。又增加4项故障/摘要/预算测试后29通过、0失败/跳过。初始Ruff的未使用变量和闭包
绑定问题已修复；最终全量静态/格式检查通过。首轮失败JUnit保留，未用新结果覆盖。

全新纯SDK环境：

```powershell
.\.venv\Scripts\python.exe -m venv .cache/p9-clean-sdk
.\.cache\p9-clean-sdk\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p9-clean-sdk\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p9-clean-sdk\Scripts\python.exe -m pip check
.\.cache\p9-clean-sdk\Scripts\python.exe -m pytest tests/unit tests/integration tests/security tests/p2 tests/p3 tests/p4 tests/p5 tests/p6/test_result_intents.py tests/p6/test_negation_scope.py tests/p6/test_contrast_advice.py tests/p9 -q -k 'not mixed_content_is_checked_before_real_graph_model_receives_it and not malformed_tool_calls_traverse_actual_langgraph_nodes and not contrast_and_advice_are_checked_before_graph_model' --basetemp=.cache/pytest-p9-clean --junitxml=reports/generated/P9-clean-sdk-junit.xml
.\.cache\p9-clean-sdk\Scripts\python.exe examples/simple_agent.py
```

**559 passed，0 failed/errors/skipped，14 deselected**。14项需要框架的用例仅在纯SDK环境
不选取，已在主环境740项全部执行。确认langgraph、langchain_core、fastapi、agentguard_demo、
agentguard_bench均未安装；SDK运行依赖只有pydantic2.12.4。使用现有匹配平台wheels缓存，
不声称空机器零网络首装。SDK普通安装与独立演示通过。

## 实际性能及接入成本

```powershell
.\.venv\Scripts\python.exe examples/simple_agent.py
.\.venv\Scripts\python.exe scripts/stress_simple.py --calls 200
```

主环境及干净SDK环境均实际执行1次工具并输出Hello AgentGuard。最终压力探针：

| 模式 | 执行数 | 耗时 | 调用/秒 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| 原echo函数 | 200 | 0.0000248s | 不作SDK能力指标 | 未采样 | 未采样 |
| SDK+SQLite，1线程 | 200 | 4.764s | 41.98 | 23.97ms | 24.11ms |
| SDK+SQLite，8线程 | 200 | 4.938s | 40.50 | 170.01ms | 337.98ms |

两组额外重放和新ID超预算均拒绝。短echo、同会话、SQLite写审计场景下8线程没有吞吐收益，
排队延迟上升；不是生产SLA或三Gate纯算法开销。首轮脚本也完成，随后为修正闭包绑定及
原函数基线调用方式重跑；上表和证据为最终真实值。没有外部API或虚构性能阈值。

接入需定义Binding/Schema/后端权限、替换工具列表、路由所有调用到invoke、只回送safe_event，
并管理会话/审批/续期。原工具引用不能同时暴露。成本有可运行示例，不宣称任意框架零改造。

## 安全不变量及限制

保持Gate1拒绝优先、权限/Schema/预算/防重放、BLOCK/未批准REVIEW零副作用；检测锁外后最终
原子复核。Gate2不回退原文；注册到期不自动放行，撤销不能通过续期复活。本轮不修改规则、
总体架构或P2公共契约。

仅覆盖接管的同步工具；Gate2不能撤销副作用。任意Python执行、原始引用、框架托管工具、
恶意本机进程、跨进程/重启预算和重放、生产认证不覆盖。其他系统/Python版本未实测。
P7真实浏览器视觉检查仍NOT_RUN，不用jsdom冒充；P8原生MSB/τ³全任务仍待验。
本任务预览进程已核对命令行/父PID后停止。证据在reports/evidence/P9。
P8一次pip使用系统Temp偏差已在P8报告披露，后续均显式使用仓库临时目录，不抹去历史偏差。
