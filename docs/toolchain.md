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

随后接入 avatar-state-*：修改状态只选择本平台状态测试；接口 / 存储 / 会话操作变化扩展对应状态消费者，宿主接线保留账号、历史、发送、建议与删除的相关验证。状态批次有效结果为 Android 107、Swift 120、工具 64 项，新增状态测试 Android 15、Swift 16 项。清理旧读取的修正仅复跑相关 Swift suite；Android 失败的相关集合修复测试等待后复验通过。头像页面和图片解码尚未接入，主机测试不替代原生构建或设备验收。


## 头像图片与选择界面的增量验证

2026-10-25：avatar-images-* 与 avatar-ui-* 显式登记图片策略、加载器、解码器及原生组件；头像接口 / 状态变化扩展同平台图片消费者，宿主页继续关联账号、历史、发送和 Markdown 的已登记集合。Swift 图片测试读取已迁入的 WebP 预设，资源变化也选择其解码消费者。影响图头像测试独立到 test_avatar_image_impact.py，减少原文件职责与行数；未放宽未知核心路径检查。

受影响集合有效结果为 Android 14 类 126 项、Swift 14 suite 129 项、工具 72 项；最后只补验改变了断言的 Kotlin 加载器 7 项及 Swift 图片处理 7 项，统计按类覆盖，不重复计数。变化 Kotlin 14、Swift 15、Python 2 个文件通过固定格式 / lint，两个行数预警已有职责审查。没有新工具、依赖或锁变更；XcodeGen 只登记源文件，宿主编译 / 系统照片选择和设备图片解码仍待授权验证。执行与缓存边界见[实施状态](execution-status.md)。


## 完整上下文重生成的提供方验证

2026-10-25：turn-provider 新增 chat_regeneration 服务、完整上下文契约及共享样例路径。路由与生命周期变化按已登记依赖扩展消费者，新增映射回归确保三类输入均选择真实提供方与双端 wire 测试。没有改变执行器、工具版本、依赖或锁。

后端首轮 104 项、补验新契约 19 项，按文件覆盖为 107 项有效结果；Android 22 类 190 项、Swift 22 suite 177 项、工具 68 项及临时 MySQL 历史投影 1 项通过。OpenAPI 58 路径一致；5 个变化 Python 文件通过固定格式 / lint。历史 lifecycle 上限从 864 下调至 806，新模块 112 行；历史路由与 753 行影响图的职责审查见[上下文实现](chat-regeneration-context.md)。该次仅提供后端与兼容性证据，新增原生上下文请求的接入与验证见下节。

## 完整上下文重生成的双端验证

2026-10-25：ChatRequestContext 精确登记到各自 turn-api 组；新的 ChatRegenerationContextTest(s) 登记到 turn-state，继续受共享提供方 / fixture 反向依赖选择。回环服务精确核对六种重生成请求；状态交接使用已有异步替身，不把旧 fixture 的固定会话状态当作新场景的服务端结果。

Android 12 类 99 项、Swift 12 suite 103 项和工具 69 项通过；Kotlin 6、Swift 6、Python 3 个变化文件固定格式 / lint 通过。消费者扩展有精确列表断言，初轮遗漏新增测试类的预期已修正；工具版本、依赖和锁均未改变。三个行数预警的审查、原始日志与 XML 见[实施状态](execution-status.md)。本批不运行 backend / MySQL 或应用构建；宿主与设备验收仍单独安排。

## 基础模型选择的提供方验证

2026-10-25：model-provider 显式登记目录路由、运行时模型解析、用户模型加载、共享样例与提供方测试；模型变化扩展发送、建议和 OpenAPI 消费者。新 ChatRequest schema 继续关联 chat-provider。模型映射回归单独放到 test_model_selection_impact.py，既有影响图文件不增行。

后端 123 项、Android 23 类 197 项、Swift 23 suite 184 项、工具 72 项及隔离 MySQL 历史投影 1 项通过；OpenAPI 58 路径一致，Python 4 个变化文件固定格式 / lint 通过。路由历史上限随职责拆分从 1216 降至 1169，未提高豁免。原生目录与选择尚未实现，本次消费者测试只证明兼容性；边界见[模型选择实施](model-selection-implementation.md)。

## 基础模型选择的双端验证

2026-10-25：model-api、model-state、model-send 按平台登记目录类型 / 网络、选择 / 宿主接线及发送 / 建议联动，model-fixtures 关联双方消费者。ChatTurnRequest 和建议请求共用 ID 校验；共享 HTTP fixture 变化扩展相关传输与消费者，仍只执行命名集合。模型配置存在不代表真实调用可用，用户选择稍后配置服务。

Android 27 类 200 项、Swift 27 suite 201 项、工具 81 项通过；15 个 Kotlin、15 个 Swift、6 个 Python 变化文件固定格式 / lint、结构与行数检查通过。XcodeGen 2.46.0 只登记新增选择器。旧影响图按职责拆为 394 行通用文件和 455 行聊天领域文件，原 41 个方法没有删除 / 重复，新模型影响测试仍独立。初轮测试和消费者预期问题及修复证据保留在 `.tools/model-selection-native-*`，行数预警结论见[实施状态](execution-status.md)。没有后端行为改动，不重复提供方 / MySQL 测试；宿主与设备验证、真实模型 / 超时 / 限额 / 用量仍待完成。


## 回答反馈的提供方验证

2026-10-25：feedback-provider 显式覆盖安全模型错误、有界用量、消息元数据及取消检查点；feedback-mysql 校验 MySQL 的报告 JSON 与更新轮次保护。共享实现变化扩展相关 SSE / 历史 / turn 消费者及其依赖，纯协议文件不无故选中数据库集合；测试选择仍限定具体文件 / 节点。

后端 212 项、Android JVM 26 类 213 项、Swift macOS 包 26 suite 200 项、工具 78 项通过；OpenAPI 58 路径一致。MySQL 的五项定向集合首轮四项通过，新用例发现旧快照问题后修复并单独通过，生命周期八项随之补验。Python 15 个变化文件格式 / lint、结构和行数检查通过；历史路由 / lifecycle 上限下降为 1146 / 803。失败与最终报告见 `.tools/chat-feedback-provider-*`，真实服务及原生反馈展示另验，未构建或部署应用。


## 双端回答反馈验证

2026-10-25：feedback-model / feedback-contract / feedback-state 按平台登记归一类型、状态 / 历史 / 取消消费者、终态投影和消息控件。ChatTurnOutcome 关联原 turn-state 集合，错误 / 用量提供方变化扩展两端反馈消费者；纯原生修改不选择 backend / MySQL。

Android 29 类 209 项、Swift 29 suite 210 项、工具 86 项通过。双端各新增九项反馈测试，覆盖共享样例、未知 / 零用量、脱敏展示、旧历史缺码、终态优先和失败重生成。Kotlin 九、Swift 十二、Python 六个变化文件格式 / lint 通过；Android 控制器与 Swift 状态模型分别下降至 433 / 331 行。原始 JSON 数字类型和超大可选用量回归补齐后，公共回环 fixture 的字节响应变化按图扩展相关 HTTP / 账号消费者；后端未改动。原生页面只新增 XcodeGen 登记，宿主编译与设备仍待验；具体范围、初轮警告及最终日志见 `.tools/chat-feedback-native-r2-*` 和[实施状态](execution-status.md)。

## 新主题恢复提供方验证

2026-10-25：onboarding-provider 覆盖 run 存储、创建仲裁、路由、schema、评估及共享恢复样例，扩展旧 SSE / 历史消费者；onboarding-mysql 列出四个多连接测试方法，共五个场景。MySQL harness 的变化同时保留原有五项；修改的聊天边界测试文件单独登记，不由测试目录通配扩成全量。

r2 最终后端 118、工具 85、Swift 主机包 11、隔离 MySQL 十项通过。Android JVM 两类 25 项首轮通过；r2 未修改其代码 / 输入，命名 Gradle 任务为 UP-TO-DATE，原始报告保留。十三个 Python 文件格式 / lint、变化文件规模和 OpenAPI 58 路径通过。历史 orchestrator / assessments 上限下调至 688 / 528，路由 310 行预警已审查。

首轮两项旧测试失败均在未改基线 `c7d5ed8` 复现，修正旧图样例与 ORM 缓存断言并保留无效图保护用例，相关两文件十六项补验通过。r1 审查未通过：提交后快照可能吸收取消版本、历史 null 会让新增投影抛错。r2 修正后补充 after_commit 的真实 MySQL 成功 / 失败回写保护及三种旧字段 HTTP 回归，重新运行明确的受影响集合。初次失败、探针和修复证据不删除，最终结果见 `.tools/onboarding-provider-r2-results.json`。没有应用构建、设备测试或真实模型调用。

## 双端学习协议验证

2026-10-28：onboarding-android / onboarding-ios 显式登记独立学习类型、请求和测试；onboarding-native-fixture 只选择双端请求消费者，提供方状态样例仍保留 backend / MySQL 关联。json-scalar-ios 关联学习、用量及历史消费者。执行器新增 learning 纯 JVM 模块白名单，仍先 dry-run 检查实际任务图，拒绝 assemble、未知模块及应用打包任务。

Android 31 类 237 项、Swift 28 suite 209 项、工具 89 项通过；新学习测试各七项。Kotlin 七、Swift 七、Python 六个变化文件通过固定格式 / lint，无行数预警。公共回环 fixture、Android settings 和 Swift 共享数字判断按反向依赖扩展命名集合；初轮精确列表补齐新消费者后通过，没有删除断言或放宽未知路径检查。最终原始报告见 `.tools/onboarding-native-reports/`，过程与失败记录使用 `.tools/onboarding-native-*`。

新 Android 模块仅复用已有 Kotlin / serialization / coroutines / JUnit 版本并生成独立 lockfile；无工具升级、后端行为修改或新模型依赖。纯包测试不覆盖原生宿主、页面、恢复日志或生命周期；未运行应用构建，后续边界见[实施状态](execution-status.md)。

## 未知创建取消验证

2026-10-28：onboarding-provider 纳入新的取消契约与合成取消样例；onboarding-cancel-mysql 显式登记四个方法、五个参数化场景。原 MySQL 恢复文件单独变化仍只选自己的四个方法；新文件单独变化只选新的四个方法，提供方变化同时覆盖两组。harness 增加命名登记后，既有迁移、生命周期、历史与用量数据库检查也按依赖保留。

后端 128、隔离 MySQL 15、工具 90 项通过；现有 Android 三类 32 项、Swift 三 suite 18 项通过。八个变化 Python 文件固定格式 / lint 通过，orchestrator 历史上限下调到 676，路由 323 行预警已有职责审查。OpenAPI 59 路径与提供方一致；无工具版本、依赖锁或数据库 schema 变化。原始报告封存于 `.tools/onboarding-cancel-reports/`；新的取消路径仍待原生消费者接入，不以兼容集合代表功能完成。
