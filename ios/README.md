# iOS 原生工程

显示名 SocraticMind，bundle identifier com.gmaicoson.socraticmind，最低 iOS 17。SocraticMind.xcodeproj 已接入 SwiftUI 账号页面与应用会话；Packages/MindCore 包含 HTTP / SSE、账号协议、表单、会话和 Keychain 适配。

## 核心定向测试

在仓库根目录运行：

```bash
swift test --package-path ios/Packages/MindCore --filter SSEContractTests
```

此命令编译 Swift 包与主机测试，不运行 SwiftUI 应用、不生成 IPA。样例直接从 contracts/fixtures 读取，需要完整仓库；没有外部 Swift 包依赖，因此当前不伪造 Package.resolved。

## 应用工程

用 Xcode 打开 SocraticMind.xcodeproj。工程不包含个人 Development Team 或证书；本轮已获准并完成模拟器账号主流程验证，使用本地 ad hoc 签名。真机需要按实际 Apple Account / Personal Team 条件设置并记录限制，不要求现在购买会员。

工程结构由 project.yml 维护，使用固定 XcodeGen 再生成并审查差异：

```bash
.venv/bin/python scripts/dev/bootstrap_tools.py xcodegen
.tools/xcodegen-2.46.0/xcodegen/bin/xcodegen generate --spec ios/project.yml
```

以上命令从仓库根运行，仅生成工程文件。共享 scheme 已纳入版本管理；应用与 SocraticMindUITests 已在 iOS 26.5 模拟器编译运行。后续模拟器验证、archive / IPA 构建及上传继续独立触发；命令和范围见 [原生验证](../docs/native-auth-verification.md)。

格式与静态规则分别见 .swiftformat / .swiftlint.yml，版本及命令见 [工具链](../docs/toolchain.md)。未知 SSE 扩展保留，不能把 DONE、断流或未知状态当作业务成功。HTTP / POST SSE 已接入，见 [传输说明](../docs/network-transport.md)；聊天与学习导航尚未实现。

Debug 默认连接 `http://127.0.0.1:8765/`，Release 无本地默认地址。MindCore/Authentication 的 AuthAPI 使用同一个 HTTPTransport；契约、会话、原生表单与剩余设备边界见 [账号实施](../docs/auth-implementation.md)。

MindCore/Chat 提供会话摘要 / 分页 API 和 ChatLibraryModel，复用 HTTPTransport 与 SessionStore。SwiftUI 已接线列表、历史和退出清理，XcodeGen 已登记页面；本批应用未重新编译 / 运行，主机测试不验证 UI。进度、定向入口及 Markdown / 发送待办见[会话读取核心](../docs/chat-history-implementation.md)。
