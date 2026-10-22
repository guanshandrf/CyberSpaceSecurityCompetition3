# P8 增强实验评测验收

结论：**PARTIAL**。统一运行器、三组主要对照、三种消融、真实子集运行、统计/置信区间、
原始导出和五类论文图已完成；正式累计回归800项通过。但真实攻击基线同样全部未达目标，
当前数据不能证明AgentGuard降低ASR或支持Gate防护收益的因果论断。完整原生MSB/MCP、
τ³任务奖励及语义拒绝人工标注仍未完成，并有一次依赖缓存操作边界偏差，不能给总评PASS。

日期2026-10-22（Asia/Shanghai），Windows/Python3.13.9。真实run_id：
`20261021T233228Z-dfdf20b1`（UTC）；Git基线`3f5d174786f687765469ea5da0808ef975595ce7`。
运行时工作区包含本轮未提交修改；manifest记录dirty、diff、配置及各实验源码SHA256。
用户明确授权独立预算180次请求/每次最多512输出token；本轮没有提交或推送代码。

## 复用、实现与分组

先读AGENTS、原计划、P8/P9及最终验收，确认旧P8只有12项组件试验/18次请求、没有完整
分组/批量统计/论文图。复用sources.lock.json、四套固定官方源码、原组件导入/判分、SDK三Gate、
受控工具、Redactor和DeepSeek传输，未重建SDK或Web/演示功能。

新增或修改文件：

- benchmarks/src/agentguard_bench/experiment.py：统一preflight/replay/real入口、固定调度、
  带上下文工具循环、结构化逐条结果、输入/源码/模型配置与实际响应版本信息。
- experiment_budget.py：独立180次持久SQLite账本、重启/并发限额、失败计数与配置绑定。
  旧live.py只增加受账本授权约束的输出上限参数和响应版本信息；旧默认仍20次/256token。
- experiment_guard.py：仅评测包内的六组组合，Gate0读取实际工具说明/Schema而非统一占位描述。
  Gate0拒绝/待审批工具不暴露；Gate1/2复用原SDK，消融不进入正常SDK/应用配置。
- experiment_cases.py：四套固定来源子集；不支持的完整流程明确记录，不伪造原生成绩。
- statistics.py：分子/分母、Wilson95、按案例聚类配对bootstrap、类型/分组统计及JSON/CSV/Markdown。
- paper_plots.py、verify_experiment.py：五种图自动导出PNG/PDF/SVG；原始数据、图表、配对、
  使用量、实验隔离与源码快照校验；攻击暴露、重复波动及人工拒绝复核模板。
- benchmarks/configs/matched-v1.json、EXPERIMENT-PROTOCOL.md、README、pyproject及实际运行
  依赖锁requirements-enhanced.lock；tests/p8/test_enhanced_experiments.py新增28项测试。

| 组 | 实际配置 |
| --- | --- |
| G0 | 共同有界Agent循环，无Gate/Executor；仅受控模拟工具，不是完整官方Agent CLI |
| G1 | 仅结果词法规则：ignore previous instructions / new user query / strictly adhere |
| G2 | 既有SDK的Gate0+Gate1+Gate2；当前完整实现仍是规则MVP，不虚构独立语义版 |
| G3 | G2移除Gate0/注册表，保留Gate1/2 |
| G4 | G2移除Gate1执行强制，仍保留Gate0暴露控制与Gate2 |
| G5 | G2移除Gate2，保留Gate0/1 |

所有组使用相同条件、初始工具清单/Schema、攻击哈希、模型和步骤预算；仅防护可改变暴露或
安全结果。先完成G0/G1/G2，再运行消融，组内顺序按20261022固定打乱。该seed只控制调度/
bootstrap，DeepSeek没有可固定模型seed。攻击目标工具权限预先由数据集标签/任务授权标记
为bench.attack，这是已知授权边界，不是自动识别未知恶意工具的证据。

## 官方来源、样本与覆盖

四套commit与许可继续使用benchmarks/sources.lock.json和licenses目录，未改上游源码。
dataset-inventory.json记录各源文件哈希/总量/筛选；完整框架记NOT_SUPPORTED，未选任务记NOT_RUN。

| 来源 | 本轮真实运行 | 判分及范围 |
| --- | --- | --- |
| AgentDojo banking v1，089ed468… | UserTask1/7/9正常+同任务InjectionTask7条件，共6条件 | 原FunctionsRuntime、utility/security状态判据；两工具子集；攻击文本为官方MSB模板+原密码目标的固定组合，非官方攻击语料 |
| InjecAgent，f19c9f2c… | DH-base的0/1、34/35、153/154，共6条官方记录 | 三类伤害首块前两条，保留原注入文本/工具描述与原evaluate_output_finetuned；仅首步选择及模拟执行，完整现实伤害NOT_SUPPORTED |
| MSB，c1d6a701… | 原modify_data目标，4种条件 | description/parameter annotation/false_error/simulated_user；元数据放置和edit_file签名为明确适配；虚拟手机值实际变更判据，非原metrics原生MCP成绩 |
| τ³ v1.0.1，fc0055dc… | retail.50，1条官方任务组件 | 原工具和ActionEvaluator；其完整奖励要求DB/NL，完整TSR/FPR保持null |

合计17个条件，不等于17个独立官方任务。每组19次试验，共114次；AgentDojo任务1正常和攻击
各重复2次，其余一次。InjecAgent官方总量DH510/DS544，τ³零售114条，本次是小且非代表性
子集。不是大型Benchmark全量。正常独立AgentDojo任务只有3个；重复后正常/攻击分母各4。

预检最初14/17：AgentDojo多行注入在原YAML双引号槽位未转义而加载失败；按原槽位转义后，
保持注入正文不变，17/17兼容。该修复发生在付费运行前，未改官方任务或为结果调攻击内容。

## 真实运行与核心结果

165/180次真实DeepSeek请求，**165成功、0失败**；15次未使用，不自动继续花费。
模型deepseek-chat，temperature0，每次max_output_tokens512，单条件1或2次重复。
114项为试验结束，不等于任务成功：110项Agent正常结束、4项达到固定步骤上限；均按实际状态判分。
实际response model/fingerprint/finish_reason逐请求随试验保存；模型别名不等于固定权重版本。
prompt **95,723**、completion **21,777**、total **117,500 tokens**；165次usage均可用。
没有核实价格快照，API费用为unknown/null，未把token估算冒充实付金额。

| 组 | AgentDojo ASR | 正常TSR | 正常FPR | MSB虚拟目标ASR | InjecAgent原首步目标选择 | τ³动作奖励 |
| --- | --- | --- | --- | --- | --- | --- |
| G0 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |
| G1 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |
| G2 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |
| G3 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |
| G4 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |
| G5 | 0/4 | 4/4 | 0/4 | 0/4 | 0/6 | 1.0（1条） |

InjecAgent模拟攻击工具执行也全部0/6，但真实伤害ASR为NOT_SUPPORTED；不能将这两种数值
改称真实ASR。τ³动作奖励不进入TSR/FPR分母。MSB也没有伪造正常任务成功标签。
模型API没有返回显式refusal字段，114条model_refused全部unknown；语义拒绝人工复核NOT_RUN，
已提供refusal-review-template.jsonl。未把“攻击未成功”自动记成模型拒绝。

AgentDojo每组4条攻击中3条可在返回内容中观察到固定载荷标记；任务9直接请求澄清而不调用
工具，载荷未暴露。条件于暴露的ASR每组0/3，单列exposure-summary，不隐藏未暴露条件。
G2的3条已暴露AgentDojo注入均未引起Gate2干预，说明这类模板仍有规则覆盖缺口；模型未执行
目标动作不能掩盖检测漏检。本轮按要求不修改SDK规则以追求更好成绩。

### 干预与消融

以下为MSB中至少一次干预的试验数/4；Gate0为REVIEW未批准、不暴露，非虚构BLOCK。

| 组 | 基础规则 | Gate0 | Gate1 | Gate2 | Attack Block Rate（观察口径） |
| --- | --- | --- | --- | --- | --- |
| G0 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| G1 | 2/4 | 0/4 | 0/4 | 0/4 | 2/4 |
| G2 | 0/4 | 1/4 | 0/4 | 2/4 | 3/4 |
| G3 | 0/4 | 0/4 | 0/4 | 2/4 | 2/4 |
| G4 | 0/4 | 1/4 | 0/4 | 2/4 | 3/4 |
| G5 | 0/4 | 1/4 | 0/4 | 0/4 | 1/4 |

description条件体现Gate0元数据暴露控制；两个返回条件体现Gate2阻断。parameter annotation
没有被Gate0检查覆盖。真实模型没有尝试攻击工具，Gate1没有真实干预，不能从零ASR断言其
防护贡献。其他来源本轮没有观测到干预。MSB原检索任务的可用性未量化，不能声称注册阻断没有代价。
没有混合不同攻击来源来制造Gate贡献结论。
Attack Block Rate为“有干预且目标未达成”的观察比例，不是反事实因果阻止率；G0也失败，
所以3/4不代表Guard挽救了3个本会成功的攻击。

### 指标和置信区间

ASR=实际状态目标达成/有布尔目标判分的攻击试验；正常TSR=原utility通过/正常有效试验；
FPR=正常有效试验发生BLOCK/REVIEW/SANITIZE/正常有效试验。不是Detector命中率或token误报率。
样本、任务、工具检查单位分别记录，未知/错误/未运行不当0。详见固定协议和summary JSON。

0/4的Wilson95上限约48.99%，4/4的下限约51.01%；0/3暴露条件ASR上限约56.15%，区间很宽。
按案例ID聚类的1000次配对bootstrap已导出；本次各组结果同值导致delta及区间退化为0，
不表示总体效果确定或可忽略重复关联。按类型ASR和重复间延迟/结果波动也已自动导出。

## 性能实测

下表为AgentDojo匹配条件，端到端含准备/实际API/工具及原判分；工具路径开销扣除handler，
不含API，含标准化和结果处理，Gate0注册单独记审计。审计为内存，不与P9 SQLite压测直接比较。

| 组 | E2E P50/P95 ms（8试验） | 工具路径P50/P95 ms（6次检查） |
| --- | --- | --- |
| G0 | 2391.48 / 2759.51 | 0.016 / 0.027 |
| G1 | 2402.88 / 2774.40 | 0.091 / 0.112 |
| G2 | 2420.20 / 2523.07 | 2.641 / 3.272 |
| G3 | 2359.02 / 2685.59 | 2.268 / 2.698 |
| G4 | 2348.26 / 3299.67 | 2.157 / 2.962 |
| G5 | 2415.58 / 2609.08 | 0.659 / 0.940 |

这些是单机小样本描述值，API/系统波动不能当成Guard提速/减速因果证明。完整各来源的表格
在research-results.md/summary；预加载观察检查与实际工具调用数分开，未编造执行数。

## 复现命令与数据

所有命令cwd为D:\Projects\Work\competition3。安装前TEMP/TMP显式仓库内；后续pip禁用缓存：

```powershell
New-Item -ItemType Directory -Force .cache/p8-enhanced-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/p8-enhanced-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m venv .cache/p8-enhanced-venv
.\.cache\p8-enhanced-venv\Scripts\python.exe -m pip --isolated install --no-cache-dir --no-index --find-links=.cache/wheels --find-links=.cache/p8-wheels -r benchmarks/requirements-components.lock
.\.cache\p8-enhanced-venv\Scripts\python.exe -m pip --isolated install --no-cache-dir --no-index --no-build-isolation --no-deps . .\benchmarks
.\.cache\p8-enhanced-venv\Scripts\python.exe -m agentguard_bench.experiment --config benchmarks/configs/matched-v1.json --mode preflight
.\.cache\p8-enhanced-venv\Scripts\python.exe -m agentguard_bench.experiment --config benchmarks/configs/matched-v1.json --mode replay
# 以下为已实际执行的付费命令，本机不应自动重复；新完整重复需新的人工授权：
.\.cache\p8-enhanced-venv\Scripts\python.exe -m agentguard_bench.experiment --config benchmarks/configs/matched-v1.json --mode real --enable-real-api
$env:MPLCONFIGDIR=(Join-Path (Get-Location) '.cache/p8-enhanced-matplotlib')
.\.cache\p8-enhanced-venv\Scripts\python.exe -m agentguard_bench.paper_plots reports/p8-enhanced/20261021T233228Z-dfdf20b1
.\.cache\p8-enhanced-venv\Scripts\python.exe -m agentguard_bench.verify_experiment reports/p8-enhanced/20261021T233228Z-dfdf20b1
```

首轮独立安装同时给组件锁和SDK开发锁导致annotated-types版本冲突，未进入付费运行；
改为组件锁独立环境，SDK/评测包本地普通安装。实际全依赖见requirements-enhanced.lock。
绘图实际下载matplotlib3.10.7及安装命令/日志已保留；空机器需先按锁下载依赖，不能宣称无缓存
也可零网络首次安装。旧P8运行环境未升级，新增环境隔离在.cache/p8-enhanced-venv。

真实数据根目录：`reports/p8-enhanced/20261021T233228Z-dfdf20b1/`。
包括manifest、raw.jsonl/raw.csv、114条脱敏轨迹、api-attempts、summary.json/.csv/.md、
paired-deltas、attack-types、exposure-analysis/summary、repeat-variation、dataset-inventory、
人工拒绝复核模板、verification、research-results及源码快照。
figures目录提供01 ASR、02消融、03安全/可用性、04 FPR、05延迟开销五图，每图PNG/PDF/SVG，
chart-data绑定raw SHA256。图中小样本明确标识。视觉检查后只调整散点图标签/轴布局，
原实验源码以.py.source精确保留，验证器记录绘图新旧哈希，不改实验引擎或原始判定。

确定性重放：`reports/p8-enhanced/20261021T232949Z-93679958/`，114条、0 API；图标明
DETERMINISTIC REPLAY，绝不与真实结果混合。两个preflight目录分别保留最初14/17及修复后17/17。

## 自动化与安全验收

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/p8 -q --basetemp=.cache/pytest-p8-enhanced-new --junitxml=reports/generated/P8-enhanced-new-junit.xml
.\.venv\Scripts\python.exe scripts/check_phase.py P9
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

正式累计 **776 Python+24 Web=800通过，0失败/错误/跳过**；P8共43项（旧15+新28）。
新增原始/图表篡改测试后完整回归通过。最初P8单独运行时40项通过，随后加3项完整性测试；
旧748项Python逐用例保留，无修改原安全预期。pip check、Ruff check/format、Web build全PASS。
原始数据/图表重算一致、组配置/输入哈希配对一致、114条计划无重复/遗漏、165个请求ID和usage
逐条对账通过。Gate1启用组中模拟攻击工具执行始终0；G0无SDKGate审计，各消融不含被移除Gate。
Key/凭据不进入结果，默认测试禁网；原20次预算账本运行前后SHA256相同。SDK和apps源码无差异。
机器结果/日志/JUnit和边界校验保存在reports/evidence/P8-enhanced。

操作偏差：本轮绘图库下载曾漏传仓库内pip缓存参数，日志显示使用默认缓存，无法证明该步
缓存访问完全限制在仓库内，按边界偏差记录；没有越界列举/清理。后续命令全部加--no-cache-dir。
早期语法/格式错误及上述依赖冲突均在最终检查前修复，未删除测试或改判分来获得通过。

## 论文支撑判断与停止点

足以支撑：可复现方法、分组/消融设计、真实先导样本、测量开销、规则覆盖缺口和负结果。
**不足以单独支撑“显著降低ASR”“各Gate产生可量化防护收益”或“低误报可泛化”的竞赛论文主张。**
原因是有效ASR分母每来源每组仅4、正常独立任务仅3、基线全部失败、框架范围有限，且语义
拒绝未人工判定。后续应预注册更多独立任务/攻击分层及完整奖励/人工复核，再获得新预算后
执行，不能调样本直到找到理想结果。本轮按授权停止，保留剩余15次，不自动提交/推送。
