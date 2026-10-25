# 已固定的开发工具链

更新：2026-10-23。本文件记录可复现配置及实际验证边界，当前只面向本地开发。固定兼容组合而非自动追随最新版，升级时定向检查消费者。

| 范围 | 版本 / 配置 | 实际边界 |
| --- | --- | --- |
| Python | 3.12.14，requirements-lock.txt | 本地安装与 pip check 已通过；Linux 待验 |
| Ruff | 0.16.9，E4 / E7 / E9 / F | 格式与基础 lint 已检查迁入文件及新增 Python |
| JDK | Android Studio JBR 21.0.10，目标字节码 17 | JAVA_HOME 使用本机路径，不提交绝对安装路径 |
| Android | Gradle 8.13、AGP 8.13.2、Kotlin / Compose compiler 2.3.20 | JVM 定向测试及获准的 Debug 应用 / UI 测试 APK 编译通过 |
| Android SDK | min 26、compile / target 36 | 已有本机 SDK，最低设备行为待验 |
| Compose / Activity / Lifecycle | BOM 2025.12.01、activity-compose 1.12.2、lifecycle 2.9.4 | 应用已编译并安装到 API 36 模拟器；最低系统与真机另验 |
| Kotlin JSON / JUnit | kotlinx.serialization 1.9.0、JUnit 5.10.1 | network / auth 核心消费，无跨语言运行时 |
| Android HTTP / 协程 | OkHttp 5.4.0、Okio 3.18.1、Coroutines 1.10.2 | 固定兼容 compileSDK 36 的 AAR，显式约束 Okio；严格锁及 SHA-256 校验下编译与相关测试通过 |
| Markdown | CommonMark Java 0.31.0 + tables / strikethrough / task-list-items；Swift Markdown / swift-cmark 0.9.0 | 共享语义与缓存核心通过；9 个 Maven 文件摘要核对，Gradle / SwiftPM / Xcode 锁定；应用宿主与最低设备待验 |
| ktlint | 1.8.0 | Compose 注解函数允许平台命名风格；其余命名规则保留 |
| Xcode / Swift | 27.1（27A9275）/ 6.4；Swift language 6，SPM tools 6.0 | 纯包及模拟器宿主已编译；本机 iOS 26.5 runtime，使用本地 ad hoc 签名 |
| SwiftFormat / SwiftLint | 0.64.0 / 0.65.1 | 前者负责排版，后者只启用不冲突的正确性规则 |
| XcodeGen | 2.46.0 | 由 ios/project.yml 生成并提交工程 / scheme |
| MySQL | 8.4.11 | 临时 socket 验证和独立持久环境已建立；不是系统已有数据库 |
| 原生 UI 测试 | Android runner 1.7.0 / ext-junit 1.3.0 / UI Automator 2.3.0；Xcode 自带 XCUITest | 仅在明确获准构建后执行所选用例，不进入默认质量 CI |

本次应用编译发现 OkHttp 5.5.x 的 Android AAR 要求 compileSDK 37，因此固定到 5.4.0，保留既定 API 36 工程组合。新增 AAPT2 与 UI 测试依赖已按官方 Google Maven / Maven Central 逐项核对摘要，未禁用依赖校验。模拟器 Keychain 需要应用标识相关签名信息；使用 `CODE_SIGN_IDENTITY=-` 的本地 ad hoc 签名，不设置 `CODE_SIGNING_ALLOWED=NO`，无需付费账号或 IPA。

AGP 8.13.2 支持 Kotlin 2.3、要求 Gradle 8.13，支持到 API 36.1；Kotlin 2.3.20 的兼容范围覆盖此组合。[Android 官方兼容表](https://developer.android.com/build/releases/agp-8-13-0-release-notes)、[Kotlin Gradle 兼容表](https://kotlinlang.org/docs/gradle-configure-project.html)

Compose compiler 随 Kotlin 插件使用同版本；Compose UI 通过独立 BOM 固定。[Compose 编译插件说明](https://developer.android.com/jetpack/androidx/releases/compose-kotlin)

## 本地工具安装

仓库根执行所需工具，下载到忽略的 .tools，不修改全局 Homebrew：

```bash
.venv/bin/python scripts/dev/bootstrap_tools.py ktlint swiftformat swiftlint xcodegen
```

版本、官方发布 URL 与 SHA-256 固定在 scripts/tool-versions.json。下载先校验摘要再解压，拒绝越界和符号链接；当前 Swift 工具下载针对 macOS，Linux CI 只使用适用工具，不误用 macOS 二进制。

语言检查输入明确的变化文件列表：ktlint 使用 .tools/ktlint-1.8.0/ktlint；SwiftFormat 带 --lint --config ios/.swiftformat；SwiftLint 使用 lint --strict --config ios/.swiftlint.yml；Python 使用 .venv/bin/ruff format --check 和 ruff check。禁止用全仓 fix 代替变化文件检查。

## 规模检查

```bash
.venv/bin/python scripts/quality/check_file_sizes.py path/to/changed.py
```

也可用 --files-from 传入 JSON 路径数组。已有 Git 历史时必须传 --base，比较基线与登记上限较小值；初始未提交仓库允许没有 base。只检查显式文件，但会验证全部历史登记是否过期、删除或应收紧。达到预警记录职责审查，超限失败；历史 migration 另核对原始字节。

范围与语言检查已接入，仓库根目录执行：

```bash
.venv/bin/python -m scripts.quality.changed_files --output .tools/changed-scope.json
.venv/bin/python -m scripts.quality.check_changed --scope .tools/changed-scope.json
.venv/bin/python -m scripts.ci.impact --scope .tools/changed-scope.json --output .tools/check-plan.json
```

前两条只检查变化文件；也可给 check_changed 指定 --files。当前未有 Git 提交时，收集范围会包含全部未忽略的新文件，不能把它误认为某一次功能修改；功能修改后继续显式选择文件及关联测试。

影响计划按 scripts/ci/impact-map.json 列出明确测试与消费者，不会自动执行它们。选定平台后由 scripts.ci.run_checks 执行；详见 [CI 说明](ci-and-collaboration.md)。格式配置变化会记录并扩展到受影响语言文件；没有自动修复或暂存。

完整架构依赖分析与新增例外管理尚待完成。GitHub workflow 已编写并通过 actionlint 1.7.12 静态检查，未远端运行。现有工具不能描述成完整成品验收。

生成文件来源登记在 scripts/quality/generated-files.json；登记本身不代表免审，源码文件中的 generated 注释也不能豁免行数。

Gradle SHA-256 校验元数据已针对当前已解析配置生成，首次信任来自固定版本的本地缓存与官方仓库依赖；不宣称验证了所有未来构建变体。新增依赖需要人工审阅来源和摘要变化，不能用自动更新元数据绕过校验失败。

Markdown 的双端固定依赖、许可证、SwiftPM / Xcode 两份锁及受限解析见[消息展示](message-rendering.md)。Swift CI 使用 `--force-resolved-versions`；Xcode 依赖图已用锁定 pins 单独解析成功，该动作没有编译或生成模拟器应用。后续授权的应用构建仍需保留锁定版本约束并验证平台行为。

## CI 工具与本机差异

quality.yml 的 GitHub Actions 固定完整 commit SHA；MySQL 服务固定 8.4.11 容器摘要。Python 固定 3.12.14，Android JDK 使用 Temurin 21.0.10。Swift job 选择 macos-26 上的 Xcode 26.6，包的语言版本保持 Swift 6；当前本机为 Xcode 27.1，两者验证结果分别记录。runner 不提供约定 Xcode 时应失败并重新审阅配置，不能悄悄切换 default。[GitHub runner 软件清单](https://github.com/actions/runner-images/blob/main/images/macos/macos-26-arm64-Readme.md)

本地工作流静态检查使用下载摘要已校验的 actionlint 1.7.12（Darwin arm64 归档 SHA-256 为 aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f）。该辅助检查器未加入日常语言 bootstrap；工作流实际运行仍待远端就绪。


## 普通聊天发送的定向集合

新增 ChatTurn API、状态与 FileChatTurnJournal 使用现有 JDK / Foundation / CryptoKit 和传输依赖，没有新版本或锁文件变更。`turn-provider` / `turn-fixtures` / `turn-api-*` / `turn-state-*` 在影响映射中登记明确路径、账号 / 历史依赖和测试选择；共享回环服务器变化扩展实际使用它的双端消费者。新建源码仍必须登记映射，不能由通配规则自动跳过。

当前提供方 10 项、工具 58 项，Android 12 类 87 项有效报告、Swift 13 suite 91 项通过；实际执行与缓存复用边界见[实施状态](execution-status.md)。变化源码通过固定格式 / lint；306 行发送协调器和 503 行影响映射测试达到预警，职责审查见[发送实施](chat-turn-implementation.md)，无硬上限突破或新豁免。XcodeGen 只登记组件，没有应用编译或安装；平台文件保护、备份和生命周期仍属独立原生验证。

## 普通文字重生成的定向集合

重生成资格与状态测试加入既有 turn-state 双端组；提供方增加 2 项既有生命周期选择。共享发送 fixture 及回环服务器变化扩展已登记的 HTTP、账号、历史、Markdown 与发送消费者，仍为显式类 / suite，没有全量测试或应用构建。最终结果和历史临时行的修正见[实施状态](execution-status.md)。schema 1 / 2 兼容和请求 ID 去重由主机测试覆盖，设备生命周期与原生 UI 单独验收。

## 标题与删除接口的定向集合

actions-provider / actions-fixtures / actions-android / actions-ios 登记后端、共享样例与双端适配。标题路由变化选择既有标题测试及关联删除生命周期；新增 PUT 进入 OpenAPI 快照，保留旧 operation / schema。通用回环 fixture 变化扩展已登记 HTTP、账号、历史和发送消费者，最终 Android 12 类 92 项、Swift 12 suite 89 项、后端 23 项及工具 57 项通过，证据见[实施状态](execution-status.md)。

接口检查点没有新增依赖或数据库迁移；当时 Kotlin 2、Swift 2、Python 6 个变化源码通过固定工具，适配器尚未注入应用容器。后续状态接线见下节；Swift 包与 Android JVM 通过不能代替操作界面编译、删除确认或设备验证。

## 标题与删除操作的定向集合

actions-state-android / ios 纳入操作状态、宿主注入与确认 / 多选页面；共享动作类型关联账号、历史和发送集合。独立消息列表仍关联原有 Markdown / 历史 / 发送消费者。最终 Android 9 类 77 项有效报告、Swift 12 suite 90 项及工具 64 项通过，执行与缓存边界见[实施状态](execution-status.md)。

ios-project 将生成的宿主工程登记与 Swift 包依赖拆开：登记改动校验当前 Swift 源文件、唯一文件名和本地 MindCore 引用，同时运行配置 / 包锁检查；新增同名宿主文件需先扩展为按 target 检查。Package.swift、Package.resolved 和 project.yml 变化仍扩展依赖消费者。未经明确授权，静态登记不会触发应用构建。

本批固定工具覆盖 Kotlin 13、Swift 13、Python 2 个变化文件；391 / 301 行发送协调器与 598 行影响测试的预警结论见[动作实施](chat-actions-implementation.md)。没有新的工具版本、依赖锁或例外。

## 自动标题更新的增量验证

2026-10-24：双端公共 URL / HTTP 入口支持重复查询参数，用于批量读取标题；因此按显式映射扩展账号、历史、发送及标题接口消费者。每批最多 100 个 ID、每周期最多 8 次读取，历史状态测试新增可见性与迟到结果验证。没有新增依赖、应用构建或远端执行。

初次 Android 16 类 122 项、Swift 16 suite 119 项通过；补齐旧会话优先读取后，相关 7 类 / suite 分别得到 73 / 72 项有效结果。分批合并为 Android 123、Swift 120 项，详见[实施状态](execution-status.md)。后端 24 项、工具 60 项通过；变化 Kotlin 13、Swift 13、Python 3 个文件的固定格式 / lint 通过。两个行数预警的职责审查见[自动标题更新](chat-title-refresh.md)，未提高上限。

## 上下文建议的增量验证

2026-10-24：suggestions-provider / suggestions-fixtures / suggestions-api-* / suggestions-state-* 登记后端、共享数据、双端接口、状态和宿主接线。复用现有重复查询参数与发送流程，无新依赖、锁变更或数据库迁移；共享回环服务改变后扩展已登记消费者，未运行全量测试。

最终 Android 18 类 138 项、Swift 18 suite 135 项、backend 16 项与工具 66 项通过，原始报告按本批保存；Kotlin 13、Swift 12、Python 4 个变化文件通过固定格式 / lint。XcodeGen 仅生成组件登记，原生交互仍需另行授权构建。三个行数预警及缓存预算见[上下文建议](chat-suggestions-implementation.md)，执行证据与限制见[实施状态](execution-status.md)。

## 会话头像核心的增量验证

2026-10-25：avatar-provider / avatar-fixtures / avatar-models-* / avatar-api-* / avatar-store-* 与 account-files-* 登记明确消费者。公共 HTTP 增加 multipart 和有界资源读取，原子 IO 同时供头像记录和聊天恢复使用；变化时扩展相应消费者，不执行全量测试。没有新增依赖、锁、迁移或宿主工程登记。

扩展集合 Android 142 项、Swift 139 项通过；补齐 Unicode ID 字节隔离后，双端相关各 13 项通过，按类合并为 Android 143、Swift 140 项有效结果。后端 10 项、工具 63 项通过；Kotlin 10、Swift 11、Python 4 个变化文件的固定格式 / lint 通过。报告复用及原始证据见[实施状态](execution-status.md)，文件预警和未接线范围见[会话头像](chat-avatar-implementation.md)。
