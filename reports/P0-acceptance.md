# P0 验收报告

- 阶段编号：P0 — 项目骨架、接口文档与验收基础。
- 日期：2026-10-19（Asia/Shanghai）；正式检查完成于 18:21:21。
- 结论：**PASS，仅限 P0**。未进入 P1，也未实现其他阶段的运行时能力。
- 自动化测试：**通过 36 / 失败 0 / 错误 0 / 跳过 0**。
- 机器结果：`reports/generated/P0-results.json`；本次时间戳
  `2026-10-19T10:21:21.284044+00:00`。

## 目标与完成情况

| P0 要求 | 交付与验证 |
| --- | --- |
| 可安装 Python 包 | src 布局的 agentguard 0.0.0；实际构建 wheel 并普通安装到全新 .venv，不依赖源目录 PYTHONPATH |
| 空 Vue 工程 | Vue 3 / Vite / Element Plus 占位页；实际挂载组件并生产构建；无聊天、工具调用或审计业务 |
| 依赖锁定 | requirements-dev.lock 锁定 14 项直接/传递/构建依赖；npm package-lock.json 锁定前端依赖及 integrity |
| 环境示例 | .env.example 无密钥，声明 future fake/offline 默认意图；尚无 Provider 或配置加载器 |
| 技术文档 | 架构图、运行顺序、依赖边界、契约字段草案、威胁模型、四项 Benchmark 接入假设和门槛 |
| 测试与本地检查 | Ruff、pytest、Vitest；check_phase.py P0 为本地 make check 等价入口，输出 JSON/JUnit/步骤日志 |
| 离线与阶段约束 | 无 Key 执行；测试网络拦截、隔离临时目录、凭据环境清理；P1 参数被拒绝且不执行检查 |

## 仓库初始状态与改动文件

开始时仅有 `AGENTS.md` 和 `AgentGuard_Codex_分阶段实施与验收计划.md`，无代码、文档、
测试环境和本地 `.git` 目录。未向父目录查找 Git 或项目配置，未初始化 Git 或自动提交。
上述两个现有文件本轮未修改。没有可执行的旧阶段回归用例。

新增文件按用途列出：

- 根目录：`README.md`、`pyproject.toml`、`requirements-dev.lock`、`.gitignore`、`.env.example`。
- SDK：`src/agentguard/__init__.py` 及 `contracts/core/gates/detectors/policies/executor/adapters/audit`
  各目录的 `__init__.py`；只有版本信息与说明性 docstring。
- 应用：`apps/api/README.md`；`apps/web/package.json`、`package-lock.json`、`index.html`、
  `vite.config.js`、`src/main.js`、`src/App.vue`、`src/App.test.js`、`src/test-setup.js`。
- 说明：`configs/README.md`、`fixtures/README.md`、`benchmarks/README.md`、`tests/e2e/README.md`。
- 文档：`docs/architecture.md`、`docs/contracts.md`、`docs/threat-model.md`、`docs/evaluation-plan.md`。
- 测试：`tests/conftest.py`、`tests/unit/test_package.py`、`tests/unit/test_phase_runner.py`、
  `tests/integration/test_installation.py`、`tests/security/test_boundaries.py`。
- 验收：`scripts/check_phase.py`、本报告；实际运行产物位于 `reports/generated/`。

`.venv/`、`.cache/`、构建产物、包元数据和 generated 日志为本地生成文件，默认忽略。

## 执行环境与准确命令

工作目录除特别说明外均为 `D:\Projects\Work\competition3`，PowerShell，Windows AMD64。
Python 3.13.9，pip 25.2（新建虚拟环境内），pytest 8.4.2，Ruff 0.12.0，Pydantic 2.12.4；
Node.js 24.15.0，npm 11.12.1，Vue 3.5.44，Element Plus 2.14.7，Vite 7.3.7，Vitest 4.1.12。
`.venv/pyvenv.cfg` 的 `include-system-site-packages = false`，没有继承全局 Anaconda 包。

成功的环境准备与正式验收命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated download --index-url https://pypi.org/simple --disable-pip-version-check --no-cache-dir --only-binary=:all: --dest .cache/wheels pydantic_core==2.41.5 --retries 0 --timeout 20 -v
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated download --index-url https://pypi.org/simple --disable-pip-version-check --no-cache-dir --only-binary=:all: --no-deps --use-deprecated=legacy-resolver --dest .cache/wheels -r requirements-dev.lock --retries 0 --timeout 20
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated install --no-index --find-links=.cache/wheels -r requirements-dev.lock
.\.venv\Scripts\python.exe -X utf8 -m pip --isolated install --no-index --no-build-isolation --no-deps .
npm.cmd --prefix apps/web ci --offline --cache .cache/npm --no-audit --no-fund
.\.venv\Scripts\python.exe scripts/check_phase.py P0
```

前端首次生成锁文件时，在 `D:\Projects\Work\competition3\apps\web` 执行：

```powershell
npm.cmd install --save-exact vue@3 element-plus@2 --cache D:\Projects\Work\competition3\.cache\npm --no-audit --no-fund
npm.cmd install --save-dev --save-exact vite@7 @vitejs/plugin-vue@6 vitest@4 jsdom@27 @vue/test-utils@2 --cache D:\Projects\Work\competition3\.cache\npm --no-audit --no-fund
```

正式阶段脚本实际执行以下六个步骤（完整 argv、cwd、耗时保存在 JSON 中）：

```powershell
# cwd: D:\Projects\Work\competition3
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pip check
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m ruff format --check .
D:\Projects\Work\competition3\.venv\Scripts\python.exe -m pytest -m p0 --basetemp=.cache/pytest --junitxml=D:\Projects\Work\competition3\reports\generated\P0-python-junit.xml
# cwd: D:\Projects\Work\competition3\apps\web
& 'C:\Program Files\nodejs\npm.cmd' run test
& 'C:\Program Files\nodejs\npm.cmd' run build
```

脚本清除凭据相关环境变量、PYTHONPATH 和外部 PYTEST_ADDOPTS，关闭 pytest 第三方插件
自动加载，设置 fake/真实 API 关闭/Benchmark 关闭/基线关闭和 npm offline。测试未要求
`.env` 或 DeepSeek Key；依赖安装完成后的正式检查在网络受限沙箱内成功执行。

## 真实测试结果

| 检查 | 通过 | 失败 | 错误 | 跳过 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 包元数据、模块占位、锁定依赖与无 Key 默认（unit/test_package） | 12 | 0 | 0 | 0 | PASS |
| 已安装 SDK 在 -I 子进程中禁止框架导入（integration） | 1 | 0 | 0 | 0 | PASS |
| SDK 源码依赖边界、离线网络拦截、环境示例（security） | 12 | 0 | 0 | 0 | PASS |
| 验收器退出码、JUnit 统计、凭据清理和阶段拒绝（unit/test_phase_runner） | 9 | 0 | 0 | 0 | PASS |
| Vue/Element Plus 实际挂载与网络拦截（Vitest） | 2 | 0 | 0 | 0 | PASS |
| 合计 | **36** | **0** | **0** | **0** | **PASS** |

另外 `pip check`、`ruff check .`、`ruff format --check .`、`npm run build` 均退出 0；
这些命令不额外计作测试用例。生产构建生成 HTML、8.84 kB CSS、81.16 kB JS。
前端依赖从锁文件重新 `npm ci --offline` 安装成功，Python 锁定依赖及本项目包也从
本地 wheel/源码以 `--no-index` 安装成功。

验收器测试中退出码 7 的子进程和合成 JUnit 是专门的失败路径/统计解析测试，
不是项目功能失败，也不是 DeepSeek 或 Benchmark 实验数据。

## 发现的问题与修复记录

1. 首次 `python -m ruff check .` 报 3 条 E501，`python -m ruff format --check .`
   报 7 个文件需格式化。执行 `python -m ruff format .`，并手工拆分隔离子进程代码中的
   长行。再次检查和正式验收均通过；没有删除测试或降低规则。
2. 首次 pip/npm 网络下载因沙箱权限失败（WinError 10013 / EACCES）。通过工具权限流程
   获准后联网下载，所有缓存与安装目标位于仓库内。没有为此运行真实模型或评测。
3. 初始 pip 索引请求报 `pydantic-core==2.41.5` 无可用版本；指定官方 PyPI 后成功取得
   对应 cp313 Windows wheel，未改动锁定版本。批量现代解析器的元数据请求较慢，主动
   中止该次下载，使用上文直接 wheel 下载命令完成全部锁定依赖。没有用全局包代替安装。
4. 全局 `pip show` 的初始环境诊断遇到 GBK 编码异常；后续使用 UTF-8 和
   importlib.metadata 读取版本。此诊断异常不属于正式测试统计。

## 人工核对与安全不变量

- 已核对四份技术文档与根计划：Gate 0 注册、Gate 1 执行前、Gate 2 返回 LLM 前；
  文档明确 Gate 2 不能撤销已发生副作用。
- 安装包默认运行依赖只有 Pydantic；测试禁止框架导入时仍能导入 SDK 全部预留模块。
  Core 无 Web/Agent/Benchmark 导入，也不反向依赖 Adapter。
- 没有 Pydantic 事件模型、Provider、Fake LLM、Agent、FastAPI 路由、工具、Gate、Executor、
  审计或评测适配器实现；没有提前开展 P1/P2 或更后阶段。
- `.env.example` 密钥为空；忽略规则覆盖 `.env`、`.env.*` 并保留示例；没有创建真实凭据。
- 可信权限、拒绝优先、零副作用、审批和结果脱敏等**运行时安全不变量：未验证**，
  因对应组件尚未实现。P0 只验证架构/测试隔离约束，不能把它们写成安全防护已经通过。
- 未进行浏览器人工视觉验收或 API/E2E 业务验证；本阶段是空应用，已通过 DOM 挂载与构建。

## 未验证能力、风险与遗留问题

| 项目 | 状态与原因 |
| --- | --- |
| DeepSeek 真实 API | **未运行/未验证**；P0 无 Provider，本轮未授权真实模型调用 |
| AgentDojo / InjecAgent / MSB / τ³-bench | **均未接入、未下载、未运行**；仅有接入计划，无成绩 |
| Gate/Executor/权限/审批/预算/审计 | 未实现、未验证；对应后续阶段，不能宣称保护任何真实工具 |
| Python 3.11/3.12、Linux/macOS | 未实测；本次验证为 Windows + Python 3.13.9 |
| 无缓存的全新机器离线安装 | 不支持；首次获取依赖需要网络，之后可用同平台缓存离线重建 |
| Python 依赖完整性 | 当前是精确版本锁，没有哈希锁；供应链风险未被消除 |
| 测试隔离范围 | socket/fetch 等测试拦截不构成 OS 恶意代码沙箱；不承诺阻止任意原生代码/子进程网络 |
| Git 管理 | 根目录无 .git；未访问父目录查找 Git，不产生提交/标签 |

P0 范围内无阻塞遗留问题；其 PASS 不延伸到任何真实模型成绩或运行时安全能力。
原始 JSON/JUnit/日志保留在本地 `reports/generated/`，重新执行验收会覆盖这些生成文件。

## 停止点

本轮在 P0 完成后停止。等待用户检查报告并明确授权“进入 P1”，才可开展 P1；
本报告不构成后续阶段的授权。
