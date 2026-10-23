# 双端 HTTP 与 SSE 传输

本层复用已有 SSEDecoder 和 ChatEventDecoder，只负责 URL、HTTP、字节接收、边界检查与取消。业务会话负责请求 ID、停止接口、历史恢复和账号范围；页面不直接解析网络流。

| 项目 | Android | iOS |
| --- | --- | --- |
| 依赖 | OkHttp 5.4.0、Okio 3.18.1、Coroutines 1.10.2 | Foundation URLSession.AsyncBytes |
| 有限请求 | suspend，默认最大响应 1 MiB | async，默认最大响应 1 MiB |
| SSE | 冷 Flow，单订阅对应一个 POST；队列上限 32 个事件 | async 回调，逐事件 await，消费完成后继续读取 |
| 生命周期 | 读取复用连接池；写请求连接空闲即释放，共用调度器；关闭时取消任务并清理两个池 | 应用范围 ephemeral session，关闭时 invalidateAndCancel |
| 超时 | 连接 10 秒，读空闲 90 秒，有限请求总时限 30 秒 | 有限请求等待 30 秒，流等待 90 秒，资源总时限 300 秒 |

接口支持 JSON 与表单，登录表单保留中文、加号和特殊字符。服务端标准错误、FastAPI detail 字符串和 422 校验数组转换为明确的 HTTPFailure；422 只读取 msg，不回显 input。未知格式使用通用 HTTP 提示。HTTP 失败、错误媒体类型、超大响应、非法 SSE 和提前 EOF 均不伪装为成功。

APIEndpoint 默认 HTTPS，开发 HTTP 需明确列出允许主机。禁止 URL 中的凭证、query / fragment，业务查询参数单独编码；相对路径保留 base 前缀并拒绝越界形式。两端拒绝自动跟随重定向，Android 禁用连接失败后的自动重试。没有在传输层自动刷新凭证或重发 POST。

Android 原生账号验证暴露了旧空闲连接读取响应头时的 EOF。当前写请求使用独立的零空闲连接池，GET 保留池复用；避免通过自动重放注册、重置或生成请求恢复连接。代价是串行写操作增加建连 / TLS 开销，后续只有在请求具有可验证幂等性或能证明未发出时再评估重试优化。网络仍可能在提交后中断，因此页面保留“操作可能已完成”的提示。[OkHttp 连接失败与重试说明](https://github.com/lysine-dev/okhttp/blob/main/okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt)

SSE 收到 DONE 结束传输，但不据此认定业务成功。错误终态仍以 request_state 和 error 事件为准。没有 DONE 的 EOF 报断流，已收到的文本由上层保留；后续应查询服务端状态和历史，不直接再生成一次。

取消订阅 / Swift Task 会关闭正在读取的连接。断开连接与服务端取消是两件事：用户按停止时，上层还必须调用后端 cancel 并核实终态。Flow 重复收集会再次发起请求，因此后续会话协调器必须持有唯一生成任务，不由多个 UI 观察者分别 collect。

此设计减少 UI 与 IO 耦合，并限制单事件和队列内存；代价是两端分别维护传输实现，且平台超时行为不同。两端持续消费同一组协议样例和本地服务器，设备网络 / 后台策略另验。参考 [OkHttp](https://lysine.dev/okhttp/)、[URLSession AsyncBytes](https://developer.apple.com/documentation/foundation/urlsession/asyncbytes)、[Kotlin 可取消挂起](https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/suspend-cancellable-coroutine.html)。

## 定向验证

仓库根执行 Swift 包测试；Android 命令从 android 目录执行，并配置 JDK 21：

```bash
swift test --package-path ios/Packages/MindCore --filter HTTPTransportTests
```

```bash
./gradlew :core:network:test --tests com.gmaicoson.socraticmind.network.HttpTransportTest
```

测试启动自己拥有的 Python 标准库回环服务器，端口自动分配，结束时清理。没有用户数据库、模型调用或 APK / IPA。每端 8 项测试验证 Unicode / 表单、正常和中断终态、服务端完成前收到首段、截断、等待中取消、错误 / 重定向、大小 / MIME 限制、URL 路径与查询编码。平台底层可能合并 TCP 写入；每个 UTF-8 切点由独立 SSE 契约测试覆盖，不能用一次 socket 测试声称穷举网络分片。

尚未覆盖：App 宿主网络权限、ATS / Android 开发 HTTP 配置、后台恢复、真实代理、文件上传下载和实际模型。以上边界不会由这些主机测试自动补齐。
