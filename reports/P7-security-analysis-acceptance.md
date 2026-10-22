# P7 安全日志详细分析报告验收

日期：2026-10-22。结论：**PASS**。

本轮为用户明确要求的可解释性展示增强，不新增检测能力或实验阶段，不改变总体架构。
原有会话删除和 P8 增强实验改动保持，SDK / Gate / Executor / P2 公共协议未修改。

## 完成内容

在每个可展开的安全日志内增加“详细分析报告”：

1. 分析结论：区分未执行、待审批、已执行、执行异常、返回内容阻断/替换、执行状态未知。
2. 风险与判定依据：按授权资源、调用合法性、预算重放、审批上下文、工具注册、返回注入、敏感信息、检查故障及策略限制分类；每类关联实际证据编号。
3. 防护链覆盖：Gate0/1/2 的记录数量、证据状态与覆盖说明。关联注册生命周期不冒充当前重新审核。
4. 可追溯证据：阶段、判定、时间、原因码中文解释、trace/call 脱敏标识。
5. 待核实事项与建议：由实际原因码生成，不把权限拒绝等同于恶意攻击，不建议绕过执行器。

报告纯前端确定性整理，复用原有脱敏字段，无额外网络/API/模型请求，不读取原始参数、
工具结果或 findings。无工具调用的轮次也有报告，明确普通文本不属于逐调用工具检查。
风险显示所列记录最高发现等级；无等级显示未评分，不编造综合风险分或攻击成功概率。
耗时仅为本次可用记录的范围与条数，排除关联注册记录，不累加可能重叠的阶段耗时。

## 安全行为验证

- Gate1 BLOCK / REVIEW 未执行，与其安全错误结果的 Gate2 ALLOW 保持区分。
- Gate2 BLOCK 仍保留工具已执行事实，明确不能撤销先前副作用。
- 后续防重放拒绝不能掩盖先前执行；混合执行/拒绝记录要求核实，不宣称零副作用。
- Gate1 started、单独 Gate2 ALLOW 或本轮结束均不被推断为已执行。
- 工具执行异常不会因安全错误结果通过 Gate2 而变成正常任务成功。
- 缺失 Gate 记录、异常中断、未公开策略均明确提示证据不足。
- 单元测试验证原始敏感字段不被报告消费；原有 Vue 文本渲染/XSS、安全展示和隐藏审计不影响 Guard 的测试继续保留并通过。

## 修改文件

- `apps/web/src/securityAnalysis.js`：证据归纳、结论、风险解释与建议。
- `apps/web/src/SecurityAnalysis.vue`：可展开的报告组件。
- `apps/web/src/App.vue`、`style.css`：日志内嵌和样式。
- `apps/web/src/securityAnalysis.test.js`：11 项证据判定/敏感字段/计时回归。
- `apps/web/src/Chat.test.js`：1 项集成展示与零额外请求测试。
- `apps/web/src/P7.e2e.test.js`：扩展原真实 ASGI/LangGraph/SDK/SQLite/jsdom 端到端断言。
- `docs/web-chat.md`：报告语义与能力边界。

## 实际验收

根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/check_phase.py P9
git diff --check
git diff --name-only -- src/agentguard
```

| 项目 | 真实结果 |
| --- | --- |
| P0–P9 Python 回归 | 782 passed，0 failed / errors / skipped |
| Web 测试（原31项 + 新12项） | 43 passed，0 failed / errors / skipped |
| Ruff check / format | PASS / PASS |
| pip check | PASS |
| Web build | PASS |
| 补丁空白检查 | PASS |
| SDK 修改检查 | 无输出，未修改 |
| 真实 DeepSeek / Benchmark | NOT_RUN，本轮无需运行 |

正式入口子命令、实际时间与日志已归档：`reports/evidence/P7-security-analysis/`。
本轮全量验收首次执行即通过，未删改原有安全预期以获取通过。

## 使用与局限

前端开发服务继续在端口 5173，刷新后展开安全日志，再展开“详细分析报告”。
无需重启后端、不影响当前会话与预算；本轮未发起真实模型调用，未提交或推送代码。

自动化端到端为 jsdom/ASGI，非真实浏览器布局验收。报告增强可解释性，不提升底层
检测器的召回率或证明整体防护效果；不具备原始参数和独立逐子检查记录时不推断这些细节。
当前规则命中不是通用语义识别证据，工具注册静态元数据不是代码安全证明，正常文本回复
也不是工具安全判定的覆盖对象。保留已知边界，不将报告用作新的执行授权。
