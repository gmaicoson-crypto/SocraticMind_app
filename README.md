# SocraticMind Mobile

基于 [SocraticMind](https://github.com/gmaicoson-crypto/SocraticMind) 的 Android / iOS 移动客户端，两个平台同步采用原生开发；仓库同时包含基于原项目固定版本复用、在这里维护的 FastAPI 后端。

当前目标：完成 Android / iOS 原生 App 和配套后端，以本地开发和验证为当前交付范围。用户没有 Apple 开发者账号，不要求上线；云部署与 TestFlight 不作为前置条件。

当前推进 M1 工程与 M2 账号 / 会话阶段：已迁入固定版本后端，建立双端共享契约、网络、会话、凭证存储和账号表单。此前账号阶段经明确授权构建了 Android Debug APK 和 iOS 模拟器应用，账号主流程已连接独立本地服务验证。实际结果和待验项见 [实施状态](docs/execution-status.md)，后端入口见 [backend 说明](backend/README.md)。没有生成 IPA 或发布，远端 CI 尚未运行。持久服务入口见 [本地开发](docs/local-development.md)，定向原生验证见 [验证指南](docs/native-auth-verification.md)。

## 成品交付规划

1. [交付总计划](docs/delivery-plan.md)：成品定义、M0—M5 阶段、依赖、资源决策和排期方式。
2. [产品范围与功能验收](docs/product-scope.md)：16 项必交功能、明确限制、共用用户场景与双端完成标准。
3. [实施任务清单](docs/implementation-backlog.md)：每项工作的前置、负责角色、复用内容和关闭证据。
4. [本地交付与运行验收](docs/release-acceptance.md)：本地运行、安装升级、设备证据、备份恢复和维护交接。

推进顺序：M0 决策与条件 → M1 工程和风险验证 → M2 可靠对话 → M3 学习闭环 → M4 完整功能 → M5 持续内测交付。M2 / M3 是中间成果；只有双端功能、运行服务和维护交接均达到要求才算成品。

## 工程依据

1. [开发前决策](docs/pre-development-plan.md)：已确认技术路线、复用原则和进入工程实施的前置条件。
2. [源项目事实与复用清单](docs/reference-audit.md)：固定参考版本，区分已存在能力和需要新增的能力。
3. [技术选型与项目结构](docs/architecture.md)：Android / iOS / backend 同仓结构、技术选型与复用边界。
4. [CI、测试与协作规范](docs/ci-and-collaboration.md)：客户端与后端增量验证、契约联动、迁移检查和手动构建约束。
5. [代码格式与规模规则](docs/code-quality.md)：三端格式检查、行数限制、迁入基线和例外。
6. [核心功能拆分](docs/core-modules.md)：聊天、Agent、图谱、附件等职责边界与复用方式。
7. [开发约定](AGENTS.md)：后续每次修改均需遵循。

## 仓库状态

| 项目 | 当前状态 |
| --- | --- |
| 本地目录 | `SoraticMind_app`，保留用户指定拼写 |
| 产品名称 | SocraticMind（已确认） |
| 远端 | `https://github.com/gmaicoson-crypto/SoraticMind_App.git` |
| 本地工作分支 | `chore/gy/mobile-planning`；基础提交 `ebbe07f`，后续按已验证批次提交 |
| 远端访问 | 用户确认是私有仓库，后续补齐 SSH 访问；目前未同步 |
| 已确定客户端方案 | Android：Kotlin + Jetpack Compose；iOS：Swift + SwiftUI |
| 已确定后端方案 | 已从固定版本迁入 backend，在本仓库维护并允许独立调整 |
| 已确定交付目标 | 完整双端功能、本地后端与开发交接；安装验证按设备条件及明确构建要求执行 |
| 文档版本管理 | docs 已纳入 Git，与实现及证据同步维护 |

核查本地 Git 配置：

```bash
git status --short --branch
git remote -v
```

SSH 配置完成后的连接与同步步骤见 [协作规范](docs/ci-and-collaboration.md)。开发标识为 `com.gmaicoson.socraticmind`，最低 Android 8.0 / iOS 17；运行与验证命令随工程实际结果补充。

## 开发入口

- [Android 工程与定向测试](android/README.md)。
- [iOS 工程与 Swift 包测试](ios/README.md)。
- [后端安装与隔离验证](backend/README.md)。
- [工具版本、格式与行数检查](docs/toolchain.md)。

已验证的安装包提供登录、注册、找回与退出，登录后仍是账号页。工作区源码现已接入会话列表、选择、分页历史、刷新与失败重试，但这批页面尚未重新编译或运行；完整功能按阶段继续实现，模拟器账号验证不等于成品交付。

M2-02 进行中：[会话读取核心](docs/chat-history-implementation.md)包含后端分页、双端读取、账号隔离与分页合并状态。Markdown、输入与发送、标题 / 删除 / 头像 / 建议等动作继续实现；本批未生成安装包。开发与 commit 已按[协作规范](docs/ci-and-collaboration.md)分到两个会话。
