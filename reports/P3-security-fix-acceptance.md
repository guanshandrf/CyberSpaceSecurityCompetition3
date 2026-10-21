# P3 安全审计修复验收报告

结论：**PASS**。日期：2026-10-20（Asia/Shanghai）。范围严格限定为三个 P3 审计问题。
正式验收时间：2026-10-20T13:16:57.861820+00:00（北京时间 21:16）。

三个问题均已修复。原有正式入口 `scripts/check_phase.py P3` 实际完成 P0–P3 全量回归：
**403 Python + 2 Web = 405 passed，0 failed、0 errors、0 skipped**；Ruff lint/format、
pip check、前端生产构建均通过。新建纯 SDK 环境为 346 passed、57 P1 deselected，
0 failed/errors/skipped，属于上述测试子集，不重复计数。

本轮没有进入 P4，没有开发 Gate 0/Gate 2，没有修改 P2 协议，没有新增运行依赖，
没有调用真实 DeepSeek 或 Benchmark，没有提交或推送代码。

## 1. 起始检查与边界

工作目录：`D:\Projects\Work\competition3`。读取根 AGENTS.md、阶段实施计划、P3 原验收
报告及 architecture/contracts/threat-model/gate1 文档和相关源码后，先公布修复方案。
原仓库已有未提交 P2/P3 变更，main 相对 origin/main ahead 2。本轮保留这些工作，没有重置。

默认沙箱进程因 setup refresh 错误无法启动，仓库命令经工具批准运行。没有修改 ACL、
扩大项目文件访问边界或向父目录寻找配置/文件；新增快照、虚拟环境和 fixtures 都在仓库内。
没有读取、修改或输出真实 Key；普通测试继续移除凭据环境变量并拒绝常见 socket/DNS。

修复前 SDK 源码已保存到 `.cache/p3-security-before/agentguard`；对应源文件哈希在
`reports/generated/P3-security-before-source.json`。该快照实际用于修复前复测，未从 Git
HEAD 推断或伪造旧版本，因为本次 P3 尚未提交。

## 2. 三个问题的根因与修复

### 问题 1：待审批无限累积与线性 Token 查询

根因：旧 `_pending` 没有容量约束；仅在同一调用重试时检查 TTL，没有回收其他过期记录；
REVIEW 不消费工具执行预算，无法借工具预算限制创建量；approve 通过遍历 values 查 Token。

关键修改位置：

| 文件/行号 | 作用 |
| --- | --- |
| src/agentguard/executor/guarded.py:60 | 新增可配置容量、会话配额、创建窗口限流与参数验证 |
| src/agentguard/executor/guarded.py:142 | 同步移除审批记录、Token 索引与会话容量 |
| src/agentguard/executor/guarded.py:149 | 按到期顺序回收，清理窗口时间队列 |
| src/agentguard/executor/guarded.py:161 | 后端可显式调用的空闲清理入口 |
| src/agentguard/executor/guarded.py:166 | Token 直接索引与安全审批状态变更 |
| src/agentguard/executor/guarded.py:209 | 原子执行容量/创建频率检查与记录创建 |

配置默认值：max_pending_approvals=1024；max_pending_per_session 默认 min(64, 全局上限)；
max_approval_creations=256；approval_window=60 秒；原 approval_ttl=300 秒保持。
容量与创建频率不能由模型控制，必须由可信后端配置。非法数值、bool、非有限时间均拒绝。

实现采用 OrderedDict 按固定 TTL 的插入顺序保存记录，Token→调用键字典提供 O(1) 查询。
execute/approve 自动清理过期记录，cleanup_expired_approvals 可由后端在空闲期调用；
无后台线程。回收 k 条记录为 O(k)，无过期项时不扫描整表。两个索引和会话计数同步更新，
消费审批后立即释放容量，不保留会无限增长的过期 Token 墓碑。

全局/会话容量满时 BLOCK approval.capacity，滑动窗口满时 BLOCK approval.rate_limited。
待审批、审批中、批准未消费和拒绝记录均计入容量；重复同一待审批调用不新增记录或再次
消耗创建限额。REVIEW 仍不消费工具执行预算，并且没有真实工具副作用。

approve 使用 pending→approving→approved/denied 状态，先释放全局锁再写审计。写入失败
恢复为未批准；写入期间到期会回收并拒绝。执行意图审计之后再次检查 TTL，防止审批在
审计期间到期仍执行。旧 Token 即使已回收也不能批准新记录；已执行 ID 的重放账本不回收。

### 问题 2：慢检测器占用全局锁

根因：旧 execute 在 `_lock` 内调用 Gate1.before_tool，包含自定义检测器、策略分析、
路径检查和审计 I/O，导致一个慢会话阻塞其他无关会话。

关键修改位置：

| 文件/行号 | 作用 |
| --- | --- |
| src/agentguard/executor/guarded.py:36 | 每会话最终提交锁与上下文修订号 |
| src/agentguard/executor/guarded.py:127 | 可信后端 update_context 发布当前权限/撤权 |
| src/agentguard/executor/guarded.py:203 | 预算与双 ID 防重放检查 |
| src/agentguard/executor/guarded.py:238 | 检测后的最新权限/路径/审批重验及原子核销 |
| src/agentguard/executor/guarded.py:288 | 锁外运行 Gate1.before_tool，再进入最终准入 |

检测器和策略执行时不持有全局锁或会话锁。全局锁只保护字典、计数、限流队列和最终核销；
不调用插件、文件系统或审计。每会话锁仅串行化最终检查/审计，不阻塞无关会话的分析。
同步 handler 在所有执行器锁外运行。

锁外分析结束后，执行器重做 Gate1.prepare，检查最新硬权限、任务、资源、参数、路径和
上下文预算，再检查审批指纹/状态、执行账本和预算。在执行意图审计成功之后，最终全局
临界区再次检查上下文修订号、审批 TTL/状态、预算与已用调用/事件 ID，原子核销后才执行。

P2 SecurityContext 为不可变快照，不会自动监听外部权限数据库。因此本轮在实施前说明
必要性后，新增**执行器层**后端专用 update_context(context)，没有修改 P2 的字段或
Detector/Policy/Gate Protocol。入口只接受 from_backend 构造的同会话同用户上下文，
发布当前声明并递增内部修订号；旧调用传入的旧上下文不能覆盖已发布权限。
若分析期间声明变化，硬检查拒绝优先；即使硬检查仍通过，修订不一致也 BLOCK
context.changed，必须重新分析，不能复用旧决策。

撤权与最终核销有明确先后关系：撤权在先则阻断；核销在先的已开始调用不能撤销副作用。
后端必须调用更新入口发布撤权，只替换业务代码中的局部变量无法通知执行器。

### 问题 3：Windows 保留设备名覆盖不全

根因：旧列表只有 CON/PRN/AUX/NUL 与 ASCII COM1–9/LPT1–9；未覆盖 CONIN$/CONOUT$、
Windows 特殊识别的上标数字 ¹/²/³，也未处理设备主名与扩展名之间的尾空格。

关键位置：`src/agentguard/policies/binding.py:18` 补齐列表；`:69` 在取扩展名前的主名后
去除尾空格、转大写比较。整段路径的尾点/空格、控制字符、ADS、盘符/UNC、遍历等原有
限制保持；所有路径段均在任何 `_check_node`/resolve 之前完成词法拒绝。

同一规则在不同平台启用，不依赖当前 OS 是否允许创建这些名称。没有禁用文件操作，
COM10.txt、LPT0.txt、CONIN-file.txt、myCOM¹.txt 等普通文件仍实际读写成功。
原符号链接/reparse/Junction/硬链接和资源根隔离逻辑未放宽，原有实际链接测试仍执行。

## 3. 实际修改的文件

本轮仅修改以下三个 SDK 源文件：executor/guarded.py、policies/binding.py、audit/store.py。
audit/store.py:29 为新阻断原因加入白名单（approval.capacity、approval.rate_limited、
context.changed），没有增加敏感字段或输出原始内容。

新增 `tests/p3/test_security_fixes.py`，69 项用例。关键测试入口：

- :24、:41：批量及同/跨会话并发容量。
- :58、:77、:91、:133：到期回收、Token 失效、自动清理、创建频率与实际累积复现。
- :119：禁止 values 扫描，验证索引查询；不以不稳定的耗时阈值冒充复杂度证明。
- :166、:183、:204：审批审计失败、审计期间到期、审批中状态零副作用。
- :248：慢 Detector/Policy 等待屏障时，独立会话真实完成工具读取。
- :299、:320、:335：检测/审计期间撤权及旧上下文无法恢复权限。
- :353、:375：8 个线程同时完成分析后的重放/预算、BLOCK/REVIEW 零副作用。
- :411、:445、:462、:469：设备名词法前置拒绝、名称变体、真实普通文件 I/O、Windows 分类。

更新 docs/gate1.md、docs/threat-model.md、README.md，说明新增配置、锁、撤权入口、
到期回收和真实验证范围；新增本报告。未修改或删除已有测试，也未修改 P3 正式验收器。
SDK 版本保持 0.3.0，依赖和 P2 契约保持不变。

源文件 SHA-256 对比在 `reports/generated/P3-security-source-delta.json` 中确认：
本轮只有上述三个 SDK 文件变化，全部 P2 contracts 源文件与修复前字节一致。

## 4. 修复前后复现对比

同一最终 69 项回归先在仓库内保存的原始 SDK 上运行，再在修复后的已安装 SDK 上运行：

| 问题分组 | 修复前通过/失败 | 修复后通过/失败 | 错误/跳过（前后） |
| --- | ---: | ---: | ---: |
| 审批容量/回收/索引/状态 | 1 / 19 | 20 / 0 | 0 / 0 |
| 锁范围、撤权、并发重验 | 1 / 12 | 13 / 0 | 0 / 0 |
| 设备名、变体与正常文件 | 6 / 30 | 36 / 0 | 0 / 0 |
| **合计** | **8 / 61** | **69 / 0** | **0 / 0** |

这些是回归用例数，不是 61 个不同漏洞。修复前部分失败是新限额参数/撤权方法不存在；
其他行为复现包括：12 次跨 TTL 的 REVIEW 仍留下 12 条记录（修复后只剩最后 1 条）、
approve 触发 values 扫描、慢检测器/策略导致独立会话超时、设备别名进入文件系统检查，
以及执行意图审计期间到期仍能执行。缺失接口和行为失败均如实保留，未包装成已通过。

最早的 33 项探索性测试为 6 passed/27 failed；扩充为 65 项后旧源码为 7 passed/58 failed；
最终 69 项如上。修复后 P3 开发回归依次为 150、182、186 passed，均无失败/跳过。
开发 Ruff 曾发现长行，已正常格式化拆分，未禁用规则。最终全量结果如下。

## 5. 正式全量结果

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0 Python | 34 | 0 | 0 | 0 |
| P1 Python | 57 | 0 | 0 | 0 |
| P2 Python | 126 | 0 | 0 | 0 |
| 原有 P3 Python | 117 | 0 | 0 | 0 |
| 本轮新增 P3 加固 | 69 | 0 | 0 | 0 |
| 既有 Web 测试 | 2 | 0 | 0 | 0 |
| **合计** | **405** | **0** | **0** | **0** |

Ruff lint/format、pip check、npm build 全通过，50 个 Python 文件格式检查通过。
纯 SDK 全新安装测试为 346 passed、57 P1 deselected、0 failed/errors/skipped；
不是跳过，也不重复计入 405。没有 FastAPI/LangGraph/LangChain/演示包安装于该环境。

机器证据（均在本仓库 reports/generated，默认忽略）：

- P3-security-before-source.json、P3-security-source-delta.json：原始源哈希与修改核对。
- P3-security-before-complete-junit.xml / .log：最终修复前复现。
- P3-security-dev-junit.xml：186 项 P3 开发回归。
- P3-results.json、P3-python-junit.xml、P3-web-junit.xml 和六步 P3-*.log：正式入口结果。
- P3-security-fix-results.json：本轮正式结果副本，避免与历史 P3 报告的统计混淆。
- P3-security-sdk-junit.xml：纯 SDK 346 项验证。
- P3-security-fix-comparison.json：从真实 JUnit 提取的三个问题前后统计。

## 6. 完整测试命令

所有顶层命令 cwd 均为项目根目录；PowerShell。环境为 Windows AMD64、Python 3.13.9、
Pydantic 2.12.4、pytest 8.4.2、Ruff 0.12.0，沿用既有锁及仓库 wheel 缓存，无新增下载。

修复前复现（源码快照保留在 .cache，不会导入修复后的 SDK）：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -c "import sys,pathlib; sys.path.insert(0,str(pathlib.Path('.cache/p3-security-before').resolve())); import agentguard,pytest; assert pathlib.Path(agentguard.__file__).is_relative_to(pathlib.Path('.cache/p3-security-before').resolve()); raise SystemExit(pytest.main(['tests/p3/test_security_fixes.py','--basetemp=.cache/pytest-P3-security-before-complete','--tb=short','--junitxml=reports/generated/P3-security-before-complete-junit.xml']))" > reports/generated/P3-security-before-complete.log
```

该 pytest 实际返回失败并产生 61 failures，不是正式验收失败被忽略；其用途是证明旧代码问题。
随后重新安装修复后包并运行全部 P3 开发回归：

```powershell
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.venv\Scripts\python.exe -m pytest tests/p3 --basetemp=.cache/pytest-P3-security-dev --tb=short --junitxml=reports/generated/P3-security-dev-junit.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts/check_phase.py P3
```

原有正式入口实际执行六步（全部返回 0）：

```powershell
# cwd: D:\Projects\Work\competition3
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pip check
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff format --check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pytest -m 'p0 or p1 or p2 or p3' --basetemp=.cache/pytest-P3 --junitxml=D:\Projects\Work\competition3\reports\generated\P3-python-junit.xml
# cwd: D:\Projects\Work\competition3\apps\web
& 'C:\Program Files\nodejs\npm.cmd' run test
& 'C:\Program Files\nodejs\npm.cmd' run build
```

全新纯 SDK 环境的真实安装与验证：

```powershell
.\.venv\Scripts\python.exe -m venv .cache/p3-security-sdk-venv
.\.cache\p3-security-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.cache\p3-security-sdk-venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
.\.cache\p3-security-sdk-venv\Scripts\python.exe -I -c "import importlib.util; import agentguard; from agentguard.executor import GuardedExecutor; assert agentguard.__version__=='0.3.0'; assert all(importlib.util.find_spec(n) is None for n in ['fastapi','langgraph','langchain_core','agentguard_demo']); print('Independent fresh SDK installation: PASS')"
.\.cache\p3-security-sdk-venv\Scripts\python.exe -m pip check
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.cache\p3-security-sdk-venv\Scripts\python.exe -m pytest -m 'p0 or p2 or p3' --basetemp=.cache/pytest-P3-security-sdk --junitxml=reports/generated/P3-security-sdk-junit.xml
```

另执行 `git -c core.safecrlf=false diff --check`，通过，无空白错误。没有执行 Git 提交/推送。

## 7. 真实环境验证与未验证项

已实际验证：真实线程与同步屏障、真实 SQLite 写入、Windows 仓库内公共普通文件读写、
原有真实硬链接和 Junction fixtures。慢 Detector/Policy 是可控测试插件，不是真实模型；
计时/屏障验证并发性质，不声称吞吐量 Benchmark。

设备名词法用例用“若触及文件系统即失败”的测试探针证明前置拒绝，未把探针当作真实
Win32 文件打开实验。Windows Python 3.13 的 os.path.isreserved 分类实际执行，且普通
名称在真实 Windows 文件系统读写成功。**未打开 CONIN$/COM¹ 等设备句柄，也未验证
所有 Windows 内核别名/编码行为**；不能把这些词法/分类测试写成完整设备文件系统实验。
非 Windows、Python 3.11/3.12 未实测；新增 Windows 分类测试只适用于当前 Windows 环境，
本次确实执行，跳过数为 0。

真实 DeepSeek、外部 Benchmark：均 NOT_RUN，本轮无调用和额度消耗，无模型安全效果或
Benchmark 成绩声明。未改动真实 API Key。

## 8. 已解决事项与遗留风险

已解决：审批记录及 Token 索引受数量约束，到期可回收、创建可限流；Token 查询不扫描表；
慢检测器/策略不持有执行器锁；最终状态与撤权重验保留；Windows 指定特殊设备名和变体
在词法阶段拒绝；所有原有安全测试保留且通过。拒绝优先、零副作用、预算、防重放不变量
无回归，本轮验收范围内没有未修复的审计问题或关键失败。

剩余限制：

- 单实例单进程保证，重启/多 worker 不共享状态，无分布式 exactly-once 或事务恢复。
- 审批已可回收；会话与已执行 ID 账本仍保留防重放历史，需要后续可信会话生命周期管理。
  后端必须控制会话创建、线程/请求并发、日志保留及限额配置。SDK 不是完整服务层 DoS 防护。
- 没有后台清理线程：空闲记录可保留至下一请求或显式 cleanup，但内存始终受配置容量约束。
- 回收后不保留无限审批墓碑；同一未执行调用如重发，仍须通过最新 Gate，若 REVIEW 则
  重新生成未批准 Token，旧批准不继承。已执行调用的双 ID 防重放仍保留。
- 撤权须由后端显式 update_context；无法自动监听外部权限源。已原子核销的在途执行
  不能撤回。before_tool 仍仅为无副作用建议，真正保护以 execute 最终检查为准。
- 同会话最终审计/路径检查仍串行，SQLite 或主机资源可造成正常排队；这不等同于检测器
  持有全局锁，执行器不提供不可信插件的资源隔离或强制超时。
- 文件系统外部 TOCTOU、工具忽略路径参数、任意 Python 代码绕过仍不在 SDK 承诺内。
  原工具仍须 OS 保护/安全句柄等自身防护；未声称完整 Windows 设备语义覆盖。
- Gate 0/2、Adapter 和结果内容防护仍未实施，P1 基线尚未接入；不把本次 P3 加固扩展为
  全框架、真实模型或生产部署防护声明。原始结果不能据此视为可安全交给 LLM。

## 9. P4 条件与停止点

三个审计问题均关闭，P0–P3 正式回归和独立安装通过，P3 范围内没有阻塞项；
**从本次验收结果看，满足提交用户审阅并由用户确认是否进入 P4 的条件。**
这不是 P4 授权。本轮到此停止，等待用户审阅，不进入 P4，不自动提交或推送代码。
