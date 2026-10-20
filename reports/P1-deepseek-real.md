# P1 真实 DeepSeek 补充验收

- 日期：2026-10-20 11:29:51（Asia/Shanghai）。
- P1 实现提交：`811d95985ef346075fff8eecd5dc8fc3b0a71eb5`。
- 结论：**PASS**，仅为一次真实模型只读工具调用冒烟，不代表 Benchmark 成绩或 Guard 防护。
- 命令：在仓库根目录执行
  `.\.cache\p1-verify313\Scripts\python.exe scripts/check_deepseek.py --enable-real-api`。

Key 来自进程环境，未写入聊天、命令行参数、仓库文件或日志；没有创建 `.env`。
使用普通 HTTPX HTTPS transport 和 DeepSeekChatModel，未使用 Fake/MockTransport。
TestClient 仅承载本地 FastAPI；模型请求真实发送到
`https://api.deepseek.com/chat/completions`，模型为 `deepseek-chat`。

| 检查 | 实际结果 |
| --- | --- |
| 请求数/硬上限 | 2 / 2，禁用重试，每次输出上限 128 tokens，超时 15 秒 |
| HTTP 状态 | 200、200 |
| 工具调用 | 恰好一次 read_file，调用和结果 tool_call_id 一致 |
| 数据来源 | 本仓库 `.cache/deepseek-real-smoke/` 隔离目录中新建的公开随机标记 |
| 读结果/最终回复 | 均与公开样例一致；未保存模型原始回复或请求正文 |
| 写操作 | 未创建笔记 |
| API usage 第一次 | prompt=386，completion=39，total=425 |
| API usage 第二次 | prompt=463，completion=16，total=479 |
| 合计 | prompt=849，completion=55，total=904；费用未计算 |

脱敏结构化证据位于 `reports/generated/P1-deepseek-real.json`。常规离线阶段检查仍不会
调用真实模型；真实运行脚本必须传显式开关。本次只有一条正常样例，未验证真实异常、
并发、其他模型或任意工具兼容性；模型主动拒绝和 Guard 阻断都不是本次测量目标。
首轮命令因新脚本 lint 问题停止，未调用 API；修正导入顺序和长行后实际运行仅这两次请求。

本记录补充 2026-10-19 的 P1 离线报告，历史报告中的“真实 API 未运行”描述其当时状态。
四项 Benchmark 仍未接入、未下载、未运行。P1 实现和真实冒烟通过后，按用户明确授权进入 P2。
