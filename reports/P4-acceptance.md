# P4 验收报告

结论：**PASS**。北京时间 2026-10-21；机器时间 2026-10-20T16:40:32.335381+00:00。
按用户连续执行 P4–P6 的授权，P4 通过后继续 P5；未提前实现 Gate0/Adapter。

完成：SDK 0.4.0 的 Gate2.after_tool、RuleResultDetector、Redactor、ResultHandler 和
HandledResult。正常、异常、未执行、非法/超限工具输出都能进入结果处理；BLOCK 只返回
固定错误，SANITIZE 只返回明确替换内容。原始与安全事件是独立副本，安全来源固定标记。
审计记录真实 Gate2 动作与白名单原因，不存结果正文。P2 协议和 SDK 依赖保持不变。

新增文件：detectors/results.py、redactor.py、gates/gate2.py、executor/results.py、
tests/p4/conftest.py、test_results.py、docs/gate2.md；修改对应公共导出、审计、版本、
验收器与文档。P0 导出断言随合法 P4 实现更新，未删除或跳过已有安全测试。

实际命令（cwd 项目根目录，Python 3.13.9 / Windows）：

```powershell
.\.venv\Scripts\python.exe -m ruff check . --fix
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps .
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv\Scripts\python.exe -m pytest tests/p4 --basetemp=.cache/pytest-P4-dev --tb=short --junitxml=reports/generated/P4-dev-junit.xml
.\.venv\Scripts\python.exe scripts/check_phase.py P4
```

正式脚本实际执行 pip check、ruff check .、ruff format --check .、pytest -m
`p0 or p1 or p2 or p3 or p4`（basetemp=.cache/pytest-P4，JUnit=P4-python-junit.xml），
以及 apps/web 的 npm run test/build。完整 argv/cwd/退出码见 reports/generated/P4-results.json。

| 范围 | 通过 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| P0–P3 Python 回归 | 403 | 0 | 0 | 0 |
| P4 新增行为/安全测试 | 47 | 0 | 0 | 0 |
| 前端回归 | 2 | 0 | 0 | 0 |
| 合计 | 452 | 0 | 0 | 0 |

pip/静态检查/格式/构建全通过，56 个 Python 文件格式通过。首轮 47 项为 46 通过、
1 失败：否定外发建议被误报，已用限定的否定短语处理修复，原失败测试保留并全量通过。
JSON 编码字符串也会解码检查，不能靠外层字符串隐藏角色伪装；无效插件/关联/替换内容
或审计故障均不会回退原文。实际本地工具结果与工具异常均经过 Gate2 的测试已执行。

人工复核：SDK 静态与安装隔离导入检查通过，框架不进入 SDK 核心；P1 尚未接入，
P3 原始 execute.value 不宣称可直接返回模型。仅 ResultHandler.safe_event 为安全返回通道。
规则检测不是完整语义防护，存在误报/漏报；敏感内容模式和显式后端 secrets 不是通用
秘密识别保证。Gate2 不能撤销副作用，raw_event 仅可由可信后端访问，不能直接落日志。
本阶段未做 UI 验证、真实 DeepSeek 或 Benchmark；external_runs 均 NOT_RUN。
这些是实际离线规则/工具行为测试，不是真实模型安全效果或 Benchmark 成绩。

P4 范围无阻塞遗留问题，依授权继续 P5。未提交或推送代码。
