# 聊天模型选择与回答提示修复

结论：**PASS（本轮功能/离线验收）**。2026-10-22，Windows/Python3.13.9。
不修改P2协议或SDK架构，不进入新阶段。P8完整原生评测和先前视觉验证缺口继续保留。

问题原因：启动的是FakeChatModel，普通输入按设计回显，不是真实问答。页面仅在空欢迎页
注明Fake，已有会话中没有常驻模型信息，也没有模型选择入口；空文本或预算错误容易被理解为
未显示回答。截图中“Fake 第2轮：你好”已实际渲染，不是这条回复丢失。

修改：

- App.vue/client.js/style.css：顶部模型选择、Fake常驻说明、每轮模型标识、空回答说明、
  模型/预算错误中文反馈；真实模型需费用确认后新建会话，创建本身不调用模型。
- api.py/settings.py/service.py：后端默认关闭的enable_model_selection开关；GET /models只
  返回允许模型/可用状态/预算，POST /sessions只接受严格枚举provider。每会话固定模型，
  所有模型/新会话复用同一服务及预算锁，客户端不能传Key/端点/权限/Guard开关。
- .env.example/docs/web-chat.md：新增后端配置说明；真实.env未修改，Key仅由后端显式读取。
- tests/p7/test_model_selection.py：8项安全/行为测试；ModelSelection.test.js：5项UI测试。
  普通测试/验收入口显式禁用模型选择，防止继承操作环境。

真实执行命令（均在仓库根目录）：

```powershell
New-Item -ItemType Directory -Force .cache/task-temp | Out-Null
$env:TEMP=(Join-Path (Get-Location) '.cache/task-temp')
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pip --isolated install --no-index --no-build-isolation --no-deps apps/api
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests/p7/test_model_selection.py -q --basetemp=.cache/pytest-model-selection --junitxml=reports/generated/model-selection-new.xml
npm.cmd --prefix apps/web run test
.\.venv\Scripts\python.exe scripts/check_phase.py P9
```

新增后端8通过/0失败/跳过；累计 **748 Python+24 Web=772通过，0失败/错误/跳过**。
pip check、Ruff静态/格式、Web生产构建全部通过。原740项Python逐用例比对完整保留。
深度模型响应测试使用明确标记的httpx.MockTransport，不能冒充真实DeepSeek调用成功。

实际运行：仅重启本任务API，Vite继续提供HMR；开启模型选择并从根.env安全读取Key，默认
保持Fake。真实HTTP验证前端/api/models、/api/health、创建Fake会话和一次Fake聊天，均成功。
后端报告fake/deepseek均available，Guard为enabled。available表示后端配置齐备，不能证明
当前Key有效性或外网连通。本轮发起的真实API请求为0，既有P8 18/20请求账本未变。

当前交互预算：进程共享16次，单会话8次，每次输出256token；工具后的模型续答和失败也计数。
网页选择真实模型并发送消息会计费；切换模型/新建会话不能恢复预算。重启后进程预算重置的
既有限制仍存在，本地界面没有生产认证，也不是账户级费用保证。

证据：reports/evidence/model-selection；真实浏览器视觉检查未执行，不用jsdom冒充。
本轮未自动提交/推送代码，运行服务保持开启供用户操作。
