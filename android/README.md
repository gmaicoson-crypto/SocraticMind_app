# Android 原生工程

显示名 SocraticMind，applicationId com.gmaicoson.socraticmind，minSdk 26，compile / targetSdk 36。app 已接入 Compose 账号页面、应用会话与 Keystore 适配；core/network、core/auth 和 core/chat 是纯 JVM 核心。完整用户功能仍按 M2—M4 实现。

## 核心定向测试

使用 JDK 21，在本目录运行：

```bash
./gradlew :core:network:test --tests com.gmaicoson.socraticmind.network.SseContractTest --dry-run
./gradlew :core:network:test --tests com.gmaicoson.socraticmind.network.SseContractTest
```

先核对任务图，仅包含 JVM 编译、JAR 和测试；若未来依赖新增打包任务，停止并调整测试边界。不要把命令替换成 build、assemble、connectedCheck 或全项目 test。APK 构建只在用户明确要求后执行。

本机 JDK 位于 Android Studio.app/Contents/jbr/Contents/Home；设置自己的 JAVA_HOME，不能把本机路径写入可提交配置。SDK 用 ANDROID_HOME 或被忽略的 local.properties 指定。

## 维护

Gradle Wrapper 带发行包摘要，依赖版本集中在 gradle/libs.versions.toml。版本锁与校验元数据随实际解析补齐，不能把尚未解析的应用依赖写成已经编译验证。工具证据见 [工具链](../docs/toolchain.md)。

core/network 读取仓库根 contracts/fixtures，不复制平台专用样例。JSON 字段 / SSE 变化需同步 backend 提供方与 Swift 消费者。未知扩展事件保留，业务终态由上层状态机和服务端查询确认。

Debug 默认连接 `http://10.0.2.2:8765/`，可用 `-Psocraticmind.apiUrl=...` 覆盖；Release 无本地默认地址，默认禁止明文网络。应用已在 API 36 模拟器运行账号流程，最低系统、真机与完整学习业务另验。

HTTP / POST SSE 已接入纯 JVM 网络核心，验证范围与取消语义见 [传输说明](../docs/network-transport.md)。本地服务入口见 [本地开发](../docs/local-development.md)。独立 `uitests` 模块通过真实页面验证账号行为，只有明确获准构建后才执行，命令见 [原生验证](../docs/native-auth-verification.md)。

账号接口位于独立 core:auth，依赖 core:network；共享测试服务器通过 network 的 testFixtures 复用。接口、会话与表单均有明确的主机测试集合，凭证实际写入 / 恢复 / 清理另由模拟器验证，见 [账号实施](../docs/auth-implementation.md)。

core:chat 复用 network 传输、testFixtures 和 auth 会话，提供会话摘要 / 分页读取、ChatLibraryController 与 Markdown 核心。app 已接线列表、历史、消息组件和退出清理；这些页面尚未重新构建 / 运行。契约与定向入口见[会话读取核心](../docs/chat-history-implementation.md)和[消息展示](../docs/message-rendering.md)；[发送 / 停止 / 恢复](../docs/chat-turn-implementation.md)已接线，主机核心通过，原生页面仍待构建与设备验证。
