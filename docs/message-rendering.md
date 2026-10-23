# 原生消息与 Markdown 展示

状态：M2-02 实施中。双端解析 / 缓存核心已有主机测试，Compose / SwiftUI 消息组件已接入历史页；本批未构建或运行应用。整体证据见[实施状态](execution-status.md)，设备验证仍单独触发。

## 复用与职责

先核对固定上游 `4a20228e630168113e9e09a66de83699545fa82c` 的 messageMarkdown.ts、InlineMarkdown.vue 与 webSearch.ts，复用其文字、代码复制和 HTTP/HTTPS 外链语义。没有迁入 marked / DOMPurify 或 WebView。历史页继续复用 ChatLibrary 状态、稳定消息 ID、账号 revision 和分页控件；后端、API、SSE 与数据库本批无变更。

| 职责 | Android | iOS |
| --- | --- | --- |
| 语法解析 | CommonMark Java 0.31.0 + tables / strikethrough / task-list-items | Swift Markdown 0.9.0 + swift-cmark 0.9.0 |
| 可测试投影 | core:chat/markdown 的文档、块、行内样式与链接策略 | MindCore/Chat/Markdown 中同义模型 |
| 解析调度 / 缓存 | MarkdownRenderer，后台协程，最多 2 个解析工作 | MarkdownRenderer actor + 独立串行解析 worker |
| 原生展示 | app/messageui：MessageContent、MarkdownInline、MarkdownBlocks、MessageCopyButton | Messages 中相应 SwiftUI View |

解析库处理语法，项目适配层只投影文字 / 样式 / 块和安全链接，页面不遍历库 AST。两端消费同一份[共享样例](../contracts/fixtures/message-markdown.json)，通过预期语义校验差异。这样普通和节点聊天可复用消息组件，代价是新增固定版本依赖、双端适配维护和宿主兼容验证。节点聊天尚未接入，不声称第二个场景已经验收。

## 当前展示规则

- 支持标题、粗体 / 斜体 / 删除线、行内代码、软 / 硬换行、引用、嵌套及有序列表、只读任务标记、分隔线、围栏 / 缩进代码、基础 GFM 表格。
- Markdown 链接、引用式链接和尖括号链接只允许绝对 HTTP/HTTPS；拒绝账号密码、控制字符、非法转义、反斜杠与其他协议。Android 复用已有 OkHttp URL 解析，iOS 使用 Foundation；点击前再次校验，并交给系统打开。裸网址暂按文字显示，邮件和相对链接不可点击。
- HTML 标签始终是文字，Markdown 图片显示带替代文字的占位，不发起图片请求。超链接不会携带后端令牌或按后端基址补全。代码语言标签仅作文字，不参与 HTML / 类名生成。
- “复制原文”复制完整消息原始字符串；“复制代码”复制解析器的代码正文，保留缩进 / 空行，但遵循 CommonMark 的换行规范化和块尾换行。iOS 显式复制使用本机剪贴板选项。实际系统复制反馈、选择和打开链接尚待设备验证。
- 表格列可横向滚动，默认显示表头加 20 行，按需增加 20 行；正文默认 24 个块，按需增加 24 块。代码区域限制可见高度并允许滚动。深层缩进和引用标记在视觉上封顶，核心仍保留真实层级。
- 不自动改写中文引号附近的强调分隔符，避免引入零宽字符改变复制结果。当前没有语法着色、公式、脚注、来源引用按钮、受保护附件预览或结构化学习卡片；`[[source:sN]]` 保留为文字，不能误认为 P09 已完成。

## 性能与生命周期

每个账号页面拥有独立 renderer，无全局 / 磁盘消息缓存。最多保留 32 条、合计 1 MiB 原文 UTF-8 成本的最近使用记录；这个成本是缓存策略参数，不是总堆内存上限。单条超过缓存预算仍可读取，但不保留解析缓存。页面销毁清理；账号 revision 重建页面；清理序号与取消检查阻止旧解析回填或重新缓存。

在调用解析库之前限制 128 KiB UTF-8、1024 行、256 个潜在嵌套标记（`* - > [ ] _ ~`）和单行 64 个竖线。库投影再限制 4096 节点、深度 32、512 块、单个合并文字 / 代码 16 KiB、32 列 / 2048 表格单元格。预检查有意保守，代码中的符号也计数，换取进入递归库之前可控的输入规模。

超过任一预算时完整原文按 Unicode scalar 边界分段显示，不截掉尾部；代价是失去富文本排版，段边界不保证完整字素簇。没有用主机测试耗时推导设备帧率，也没有宣称解决所有长历史内存问题。流式增量渲染的节流和滚动锚点随发送 / SSE 阶段继续实现。

## 定向验证入口

先运行变化文件格式 / lint，再按影响计划执行：

```bash
# 仓库根；JAVA_HOME 指向已约定的 JDK 21。仅 JVM，不生成 APK。
android/gradlew -p android :core:chat:test --tests com.gmaicoson.socraticmind.chat.MarkdownContractTest --tests com.gmaicoson.socraticmind.chat.MarkdownRendererTest

# 仓库根；只编译 Swift 包与选中的主机测试。
swift test --package-path ios/Packages/MindCore --force-resolved-versions --filter 'MarkdownContractTests|MarkdownRendererTests'
```

共享样例覆盖 21 组语义、26 组链接策略；两端另验 7 类超限保留，以及缓存命中 / 淘汰、UTF-8 成本、取消、清理后迟到结果、独立范围与后台执行。CI 为这些文件登记精确路径，未知核心文件必须补映射；页面变化增加其会话状态关联集合，依赖变化扩展受影响平台全部已登记消费者，仍不执行全仓测试。

应用宿主待验：双端编译、最低系统、字体缩放 / 无障碍、代码选择与复制、链接交接、表格 / 代码滚动、首屏滚动定位、超长内容和账号切换。已有账号阶段 APK / 模拟器 App 不包含这些变化。

## 依赖来源与复现

版本、源 revision 与原文许可证摘要见[依赖记录](third-party/markdown-dependencies.json)。[CommonMark Java](https://github.com/commonmark/commonmark-java/tree/commonmark-parent-0.31.0) 使用 BSD 2-Clause；[Swift Markdown](https://github.com/swiftlang/swift-markdown/tree/0.9.0) 的 Apache 2.0 / Swift 例外全文和 [swift-cmark](https://github.com/swiftlang/swift-cmark/tree/0.9.0) 的多来源许可原文均保留在 third-party。未来实际交付安装包时须包含相应第三方说明，不能把仓库留档当作已完成应用内展示。

Gradle 的 9 个新增 commonmark JAR / POM 摘要已与 Maven Central 下载逐项比对，保留原校验项，不禁用校验。Okio 显式约束回已有 3.18.1。CommonMark 的 Java 集合工厂调用依赖 Android D8 的[标准回移支持](https://r8.googlesource.com/r8/+/1fd327c7f4ff84a6db5533503d52dc07fa4d81d6/src/main/java/com/android/tools/r8/ir/desugar/BackportedMethodRewriter.java)；本批只完成 JVM 验证，最低 Android 26 仍待实际运行。

SwiftPM 的 Package.resolved 由解析生成；Xcode 工作区的锁文件镜像同一组审阅后的 pins，随后 `-resolvePackageDependencies -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates` 验证通过，仅解析、不构建。CI 强制使用锁定版本，并检查两份 pins、固定直接版本和许可证摘要一致；改依赖时同步审阅这些文件。两端原生交互分别采用 [Compose 链接](https://developer.android.com/develop/ui/compose/text/user-interactions)、[Compose 剪贴板](https://developer.android.com/develop/ui/compose/touch-input/copy-and-paste)和 [SwiftUI OpenURLAction](https://developer.apple.com/documentation/swiftui/openurlaction)。
