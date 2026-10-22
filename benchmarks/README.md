# AgentGuard P8 独立评测组件

此目录与 SDK 分包。仅支持 AgentDojo、InjecAgent、MCP Security Bench（MSB）、τ³-bench。
官方来源/固定 commit 见 sources.lock.json，MIT 原文见 licenses/。
已实现四项的选定案例/官方判分组件接入，不宣称完整原生 CLI 或全量榜单复现。

## 普通离线测试

根目录已有 SDK 和开发依赖后，用仓库内 TEMP/TMP 安装本地包：

```powershell
New-Item -ItemType Directory -Force .cache/bench-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/bench-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .\benchmarks
.\.venv\Scripts\python.exe scripts/check_phase.py P8
```

普通测试不下载数据、不要求 Key、不调用模型。SDK 自身不依赖此包或任何评测框架。
组件运行时为另一独立环境，实际 Windows/Python 3.13 锁见 requirements-components.lock。
不得把这些依赖装进 SDK 默认运行依赖；冷环境需先准备依赖缓存。

## 明确启用的下载和官方组件验证

```powershell
.\.venv\Scripts\python.exe scripts/fetch_benchmarks.py --enable-download
.\.venv\Scripts\python.exe -m venv .cache/p8-venv
.\.cache\p8-venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/p8-wheels --find-links=.cache/wheels -r benchmarks/requirements-components.lock
.\.cache\p8-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps . .\benchmarks
.\.cache\p8-venv\Scripts\python.exe scripts/check_benchmark_components.py
```

探针只验证案例/原函数/受控执行兼容性，使用明确标为 fixture 的模型，**不是 Benchmark
或真实 API 成绩**。组件加载器跳过完整上游 package __init__ 的急切 Provider/Runner 导入，
只执行选定原始模块，不伪造依赖或替换判分。InjecAgent 与 MSB 判分从固定源码提取原始
函数 AST，排除模块级 API 客户端和 CLI，函数体原样执行。τ³ 禁用 dotenv 向上搜索。

## 真实实验（有费用，默认关闭）

本轮授权最多 20 次 DeepSeek 尝试，每次最多 256 输出 token；真实已使用 18 次。
持久账本固定为 `.cache/p8-live/budget.sqlite`，失败也计数、重启不重置，不得为重跑删除它。
读取显式根目录 .env 或环境中的 Key，不向上搜索、不输出 Key；不自动重试，不跟随认证
重定向，输入每次最多 32,000 字节，单次超时 30 秒。

```powershell
.\.cache\p8-venv\Scripts\python.exe scripts/run_benchmarks.py --enable-real-api --enable-benchmarks
```

**不要把上条命令当无成本回归命令**。本轮已完成，无需再跑；新授权需重新审定预算政策，
不能擅自通过另建账本扩大本轮上限。统计重算用 scripts/summarize_benchmark_run.py，不发 API。

保存原始判分、脱敏轨迹、工具计数、Guard 审计、延迟、API usage 和 SHA。results.json
保留最初 last-response usage；results-derived.json/.csv 用实际账本和试验边界汇总所有
请求，不覆盖原文件或修改判分。费用缺乏已验证价格快照，记 null。

## 覆盖与限制

- AgentDojo：banking v1 UserTask7 / InjectionTask7，原始内存环境、FunctionsRuntime、
  utility/security；固定自定义注入，不是完整默认 Suite 或原生 AgentPipeline CLI。
- InjecAgent：dh_base.json 第 0 条、官方 finetuned 首步 judge；开放对象在两个模式都
  收紧为 SDK 闭合子集。攻击工具只模拟，官方工具选择成功与实际副作用分开。
- MSB：真正官方 dongsenzhang/MSB 的 false_error/modify_data 模板和 metrics.check_result；
  虚拟工具及日志适配，**原生 MCP 传输/完整服务器未运行**。不混用其他同名小型探针库。
- τ³：官方 v1.0.1 retail.50，原 RetailDB/工具/ActionEvaluator；**完整 DB/NL/user-simulator
  reward 未运行，动作奖励不能称作任务成功率**。

baseline/full 和单 Gate 消融样本很小，不能推导总体 ASR、显著性或通用语义能力。
模型拒绝与 Guard 拦截分开记录；未判定的语义拒绝为 null，不冒充 0。
完整 SDK 仍是规则 MVP，没有另造“语义完整版”。详见 reports/P8-acceptance.md。



## P8 增强实验（2026-10-22）

统一入口 `python -m agentguard_bench.experiment --config benchmarks/configs/matched-v1.json`。
默认仅preflight；`--mode replay`为确定性重放；真实调用必须额外传`--mode real --enable-real-api`。
完整固定协议/指标/分母/范围见 [EXPERIMENT-PROTOCOL.md](EXPERIMENT-PROTOCOL.md)。

本轮真实子集114项试验、六组匹配、165次DeepSeek请求，未超过新授权180次/每次512输出token。
17个样本条件不是17条完全独立官方任务：AgentDojo为3个用户任务的正常/攻击条件，InjecAgent为
6条官方DH记录，MSB为1个原目标的4种明确适配，tau为1个官方动作组件。完整MSB/MCP与tau奖励
未支持，不能当全量原生成绩。所有攻击基线同样未达目标，不能宣称Guard降低ASR。

真实结果位于 `reports/p8-enhanced/20261021T233228Z-dfdf20b1`；重放与预检在其他run目录，mode明确
分开。raw.jsonl/CSV、summary、配置/源码哈希、暴露分析、验证记录和5类PNG/PDF/SVG图均保留。
重新汇总/生成图：`python -m agentguard_bench.paper_plots reports/p8-enhanced/20261021T233228Z-dfdf20b1`；
校验：`python -m agentguard_bench.verify_experiment reports/p8-enhanced/20261021T233228Z-dfdf20b1`。
绘图前将MPLCONFIGDIR设为仓库内.cache目录；独立环境实际依赖锁为requirements-enhanced.lock。

本机独立账本 `.cache/p8-enhanced-live/budget.sqlite` 已用165/180，不要删除或重置。
原P8的20次账本哈希未变。不自动使用剩余15次，也不自动提交/推送。
本轮下载绘图库曾遗漏仓库内pip缓存参数，操作边界偏差已在验收报告披露，后续使用--no-cache-dir。
最终结论与局限见 `reports/P8-enhanced-acceptance.md`，不能由工程测试通过推断研究有效性。
