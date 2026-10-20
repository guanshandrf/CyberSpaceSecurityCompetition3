# 配置占位

P1 使用根目录 `.env.example` 和演示包 DemoSettings；显式 `uvicorn --env-file .env`
加载本地配置，默认 Fake 且无 Guard 基线关闭。Provider 不接受客户端配置，真实 API
另需开关/密钥及调用上限；详见 `apps/api/README.md`。SDK 尚无运行时配置加载器。
权限必须由可信后端构造；模型文本不能作为授权来源。真实 API、Benchmark 和
无 Guard 基线均需在对应阶段实现显式启用与默认关闭机制。

