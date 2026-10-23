# 分阶段实施状态

更新：2026-10-24。长期目标仍为完成双端原生成品功能；本文件记录当前真实进度，不以计划表代替完成证据。

## 本次用户确认

- 按交付计划进入工程实施，不再停留在仅规划阶段。
- 显示名 SocraticMind，开发包名 / bundle identifier 使用 `com.gmaicoson.socraticmind`。
- 最低 Android 8.0（API 26）、iOS 17；最终分发标识未登记。
- 用户没有 Apple 开发者账号，当前要求本地开发、不上线。后端、联调、数据及恢复在本地完成；TestFlight、云部署、商店及外部内测不是当前完成前置条件。
- 保留 P01—P16 完整功能和双端验收。没有真实模型配置、设备或构建条件的结果仍标记未验证，不用演示模式冒充成品。
- 继续遵守明确要求后才构建 APK / IPA 的约定；不会因长期目标自动构建或发布。
- 账号验证阶段用户已明确允许 Android Debug APK、iOS 模拟器应用及登录 / 注册 / 找回 / 退出 / 恢复的本地验证；使用合成账号，不生成 IPA、不上传或发布。授权不自动扩展到后续功能构建。

本节是对原交付计划的执行修订。M5 调整为本地可运行、可安装 / 验证和可维护的交接；后续如要求上线，再恢复对应部署、账号和分发条件。应用功能、兼容、数据隔离与恢复标准不降低。

## 当前任务

| 任务 | 状态 | 已有证据 / 剩余工作 |
| --- | --- | --- |
| M0-01 | 动作核对完成 | [源功能映射](source-feature-map.md)；具体功能尚未实现 |
| M0-02 | 部分完成 | 名称、开发标识、最低系统已确认；Android API 36 / iOS 26.5 模拟器应用已运行，真机及最低系统待验 |
| M0-03 | 部分完成 | 本地实施已授权、docs 纳入版本管理；无需购买云服务；Git 私有远端访问和真实模型配置尚待落实 |
| M1-01 | 后端基线已验证 | 已迁入后端、测试、迁移与许可证，[来源清单](../backend/upstream-manifest.json)保存 174 个原始文件哈希；依赖锁定、格式 / lint、定向基础及隔离 MySQL 迁移 / 启动已验证；细节见下表 |
| M1-02 | 部分完成 | 当前导出 58 个 API 路径，新增标题 JSON 更新操作并保留旧入口；提供方 SSE 样例与恢复用例通过；Kotlin / Swift 原生消费者共享样例通过；双端回环 HTTP 传输已验证；真实服务 / 设备联调另验 |
| M1-03 | 部分完成 | 双端应用已编译、安装并接入账号页面；完整设计规范、业务导航与组件仍待完成 |
| M1-04 | 部分完成 | 变化文件格式 / lint、行数门禁、Git 范围和显式影响映射已接入；workflow 静态校验通过，远端运行及完整依赖边界检查待完成 |
| M1-05 | 部分完成 | POST HTTP / SSE、Markdown 解析 / 缓存的双端主机验证通过；图谱及设备交互验证待完成 |
| M1-06 | 部分完成 | 持久独立本地服务、注册 / 上传 / 重启保留数据已验证；外部模型、搜索、邮件和备份恢复仍待验证 |
| M2-01 | 原生账号流程已联调，继续验收 | 后端 + 双端账号契约、会话及表单核心通过；两端注册 / 登录 / 找回 / 退出 / 重启恢复流程通过，键盘补充回归结果见末节；真机和完整账号隔离待验 |
| M2-02 | 会话与消息核心通过，页面待宿主验证 | 有界摘要 / 历史、分页状态、Markdown、标题 / 删除和上下文建议核心已验证；列表 / 消息 / 确认 / 多选、自动标题与建议页面已接线；头像和宿主验收继续实施 |
| M2-03 | 普通发送与重生成核心通过，页面待验 | 稳定请求 ID、发送 / 停止、普通文字重生成及历史替换已接线；完整上下文和宿主验证待完成 |
| M2-04 | 恢复核心部分完成 | 无正文恢复标识、只读核对、取消未确认与账号迟到结果已测；设备进程终止 / 前后台 / 网络切换待验 |
| M2-05—M4 | 未开始 | 真实模型、学习闭环与完整功能继续按任务推进 |
| M5 | 未开始 | 按本地交付修订执行；不以缺少商店账号阻塞本地实现 |

## 已核实开发环境

| 工具 | 当前证据 | 用途与限制 |
| --- | --- | --- |
| Python | Homebrew 提供 Python 3.12；本仓库已创建隔离 .venv | 安装源锁定依赖，避免修改系统 Python |
| Java | Android Studio JBR 21.0.10 | 使用明确 JAVA_HOME；系统 java_home 暂未登记此 JDK |
| Android SDK | 已安装 android-36 / 36.1，build-tools 包含 36.0.0 等 | API 36 Debug 应用 / UI 测试包构建并运行；最低设备待验 |
| Xcode / Swift | Xcode 27.1（27A9275）、Swift 6.4 | Swift 包和 iOS 26.5 模拟器应用已验证；未构建 IPA |
| MySQL | 本机 mysqld 8.4.11 可用 | 独立临时验证与持久本地环境均使用本仓库拥有的进程 / 目录，不触碰既有服务 |
| 源仓库 | 本机包含固定 SHA；远端 master 已有更新 | 仍从已审查固定版本迁入，不修改源工作区 |

## 变化与验证记录

本次迁入排除源 `backend/uploads/` 中的用户数据。来源哈希在任何格式 / 本地修复之前记录；13 个历史 migration 保持原文。没有复制原 `.env`、数据库或 Web 运行时代码。

后续按本轮明确授权构建了 Debug APK 和 iOS 模拟器应用。没有调用真实模型、构建 IPA、部署远端、运行全量测试、提交或推送。以下记录按检查点保留历史边界，当前结果见末节。

## 首批后端验证

均使用本仓库 .venv / Python 3.12.14；pytest 从 backend 目录执行。

| 范围 | 明确选择 | 结果 |
| --- | --- | --- |
| 基础 | tests/p0/test_config.py、test_models.py、test_migrations.py、test_errors.py | 22 通过 |
| lint 关联 | test_user_llm_api.py、test_plans_queries.py、test_agent_orchestrator.py、test_web_chat.py；test_chat_summaries.py 的 test_running_job_waits_for_lease_and_recovers_after_process_restart；test_attachments.py 的 test_docx_order_nested_tables_pptx_notes、test_pdf_range_confirmation_and_scan_failure、test_upload_idempotency_scope_and_download | 30 通过 |
| 隔离 MySQL | scripts/dev/verify_backend_mysql.py 选择的空库迁移、前一 revision 升级保留数据、真实 lifespan / health | 3 个不同用例通过；升级用例修复 fixture 后单独重跑 |
| 契约 / 恢复 | tests/contracts 的 4 个用例；test_chat_lifecycle.py 的 test_request_replay_and_fingerprint、test_expired_same_request_replay_returns_interrupted、test_cancel_before_begin_is_durable_and_prevents_generation、test_failed_regeneration_preserves_answer_success_replaces_and_invalidates | 8 通过 |
| 格式 / lint | 137 个非历史 Python 文件 Ruff format；150 个 Python 文件 Ruff lint | 通过，新增工具脚本另按变化检查 |
| 依赖 | requirements-lock.txt 安装解析与 pip check | 通过；Linux 兼容未验证 |

共 63 项不同用例，不是全量测试。继承的 Pydantic / SQLAlchemy 弃用警告未隐去。真实模型、网络分片、客户端、应用运行和设备均不在这些结果覆盖范围。

## 双端核心与质量工具验证

本次新增代码先核对原后端事件格式及已有共享样例，再把字节帧、聊天事件语义和应用壳分离。两端复用同一组 contracts/fixtures，不引入 Vue 或跨语言框架。优点是解析可独立验证、界面可继续复用该核心；代价是保留两种语言实现，需要持续做契约一致性检查。

| 范围 | 实际检查 | 结果与限制 |
| --- | --- | --- |
| Android JVM | :core:network:test --tests com.gmaicoson.socraticmind.network.SseContractTest；先 dry-run 核对任务图 | 21 用例通过，0 跳过 / 失败；仅 JVM / JAR，没有 APK |
| Swift 核心 | swift test --package-path ios/Packages/MindCore --filter SSEContractTests | 7 用例通过；主机包，不是应用宿主 |
| 跨端样例 | 7 组有效线格式 / 业务样例，每个 UTF-8 字节切点及逐字节输入；10 种错误 JSON 载荷 | 中文、emoji、BOM、CRLF、CR、多行 data、未知字段、截断、大小限制和错误终态通过 |
| 原生静态 | 固定 ktlint、SwiftFormat --lint、SwiftLint --strict | 新增 Kotlin / Swift 文件通过；最初 Compose 命名及 120 列排版问题已修复 |
| 工程识别 | XcodeGen 生成；xcodebuild -list | 应用 target、共享 scheme 和本地 MindCore 可识别；未运行 SwiftUI |
| 依赖 | Android network 核心及 app debugRuntimeClasspath 明确解析 | 对应锁文件与 SHA-256 元数据已保存，启用校验后的核心定向测试再次通过；不代表应用编译通过 |
| 规模规则 | scripts.quality.tests.test_file_rules | 15 用例通过，包含阈值、行尾、中文、历史原文、缩减 / 到期、路径、改名与伪生成物 |
| 初始代码规模 | 对本次 172 个新增 / 迁入源码文件显式检查 | 152 通过，20 项预警已有来源 / 职责登记，其中 8 项历史基线；无未登记超限 |
| 来源与文档 | 174 个源哈希逐项比对固定 Git 对象；13 个历史 revision 原文；21 份维护文档链接 / 行尾 | 通过；保留的 README.upstream 作为原始材料，不把旧项目链接伪装为本地文档 |

Android 首次核心编译发现 Java 21 与 Kotlin 17 目标字节码不一致；已显式统一为 17，修复后同一相关测试类通过。第一次生成依赖校验元数据因远端收集耗时中断，随后以离线的核心 testRuntimeClasspath 和 app debugRuntimeClasspath 解析成功生成 SHA-256 元数据；仅覆盖实际解析范围，后续新增配置或应用构建依赖仍需审阅补齐。没有绕过 JVM 校验或修改 Android 最低版本。

该检查点累计 106 个不同的已通过定向用例：backend 63 + Android 21 + Swift 7 + 规模检查 15。没有执行全量测试。框架 / 设备、真实网络与模型质量未被这些主机测试覆盖。

后续检查点见下节。远端访问、设备与真实模型条件仅影响相应验证，独立本地工作继续推进；不把开发壳或主机测试标为成品。

## 本地环境、真实传输与增量 CI 检查点

复用原 FastAPI / Alembic，新增本仓库专用的持久环境启动器。上传头像新增可配置存储路径，默认行为保留；固定上游的 32 个产品头像单独迁入并提供 /avatars，不迁入用户上传或 Web 运行时。优点是本地重启后数据可继续使用；限制是当前只监听回环接口，备份恢复和真机网络尚未验收。

两端真实传输继续复用 SSE 解析器，通过同一个标准库 HTTP fixture 验证。Android 使用 OkHttp / Coroutines，iOS 使用 URLSession.AsyncBytes；界面和会话恢复状态仍由后续功能层维护。取舍见 [传输说明](network-transport.md)。

| 范围 | 实际验证 | 结果 |
| --- | --- | --- |
| 本地环境边界 | scripts.dev.tests.test_local_environment | 6 项通过；身份稳定、权限、互斥、未知目录、父进程配置隔离、状态地址 |
| 本地持久生命周期 | scripts.dev.tests.test_local_backend_lifecycle | 1 项真实 HTTP 用例通过：验证码、中文注册、资料 / 头像 / 主题、停止重启、旧 JWT 和数据保留；预设 WebP 可读取 |
| 后端配置 / 头像 | test_config.py 与 test_avatar_presets.py | 12 项选择中 11 项首次通过；缺少源预设资源导致 1 项失败，补齐资源后只重跑该项通过；其中新增不同用例为头像 4 项 |
| MySQL 与契约关联 | 复用 mysql_runtime 后的 3 项隔离 MySQL；export_openapi.py --check | 3 通过，56 路径快照一致；无真实模型 |
| Android HTTP | HttpTransportTest | 8 项通过；核心依赖变更同时回归 SseContractTest 21 项通过；Callback 参数名警告修正后定向复验 |
| Swift HTTP | HTTPTransportTests | 8 项通过；共享包编译及原 SSEContractTests 7 项相关回归通过 |
| Git 文件范围 | scripts.quality.tests.test_changed_files | 7 项通过；未提交初始仓库、索引 / 工作区、Unicode / 换行文件名、改名、指定提交与无效 base |
| CI 选择与报告 | scripts.ci.tests.test_impact | 15 项不同用例通过；未知改动失败、反向消费者、初次 push、PR merge-base、格式配置扩展、零用例 / 报告缺项拦截 |
| 工作流静态 | actionlint 1.7.12 | quality.yml 通过；未提交 / 推送，因此 GitHub job 尚未执行 |
| 执行器接线 | Python 指定工具用例、Android HttpTransportTest、Swift 单个 endpoint 用例 | 本机选定入口通过；Android 检查实际任务图仅包含 JVM 模块；Swift 最初报告路径不匹配，识别 Swift Testing 分报告后该单项与报告检查通过 |
| 变化文件格式与规模 | 本批 Python / Kotlin / Swift 文件逐批检查；初始结构汇总 | 无未登记超限；20 项上游预警保留原职责登记，新增生产文件未达到预警 |

该检查点累计 155 个不同通过用例：backend 67、Android 29、Swift 15、文件规模 15、Git 范围 7、本地环境 7、CI 规则 15。重复回归和执行器接线验证不重复计数；这些是定向选择，不是全量测试。

[本地启动](local-development.md)可用，默认环境已完成 init / doctor / run / status 后正常停止，持久数据保留。真实模型未配置；没有调用付费模型、发送真实邮件、生成 APK / IPA、修改 Git 索引、提交、推送或部署。

工作流已定义 Python、Android JVM、Swift 包、隔离 MySQL 和稳定汇总检查。首次迁入采用明列基线集合；后续未映射的旧业务或新增业务改动会失败，需要在同一改动中补充准确的测试选择。映射不是静态依赖分析器，完整架构边界门禁仍未完成。CI 的 Linux 依赖、容器 socket 和 Xcode 26.6 runner 需要远端实际运行，不能由本机 Xcode 27.1 结果推定已通过。

下一步继续 M1 的展示 / 导航与平台能力验证，并在不依赖设备构建的部分推进账号和对话核心。阶段退出与最终交付仍需完整功能、真实模型及设备证据。

## M2-01 账号接口子任务

在 M1 的主机网络验证具备输入后先行实现可独立验证的账号接口，不据此关闭 M1 的远端 / 设备待验项。复用原生传输与现有 auth 路由，新增 core:auth / MindCore Authentication；没有改写后端注册或密码业务。[实现说明](auth-implementation.md)记录字段、复用边界与下一步会话任务。

| 范围 | 选择 | 结果 |
| --- | --- | --- |
| 后端提供方 | tests/contracts/test_auth_contract.py | 3 项通过；真实路由、隔离 SQLite、密码哈希 / JWT，邮件和限流命中替换；11 条上游弃用警告保留 |
| Android 消费者 | core:auth AuthApiContractTest | 3 项通过；共享 HTTP fixture；严格依赖校验下通过新 CI 执行器复验，未生成 APK |
| Swift 消费者 | AuthAPIContractTests | 3 项通过；CI 执行器识别全部选定 suite 和 Swift Testing XML |
| 复用 fixture 关联 | HttpTransportTest / HTTPTransportTests | 各 8 项相关回归通过；没有扩大到全量测试 |
| 增量映射 | scripts.ci.tests.test_impact | 增加账号联动 / 未映射会话文件拦截，累计 17 项通过；格式 / lint 和新增代码规模通过 |

当前累计 166 个不同的已通过定向用例：backend 70、Android 32、Swift 18、文件规模 15、Git 范围 7、本地环境 7、CI 规则 17。重复回归不重复计数。

此检查点账号接口尚未接入原生页面；会话与凭证存储的后续结果见下一节。没有真实模型联调、安装包、设备运行或远端 CI 证据，目标仍未完成。

## M2-01 会话核心与存储适配检查点

2026-10-23：复用 AuthAPI / HTTPTransport，实现双端 SessionStore 和 TokenVault 接口，加入恢复验证、过期清理、重复提交保护、取消检查与账号 revision。平台存储与核心状态分开，便于定向验证竞态和存储错误；代价是应用容器还须接线，并按 revision 取消功能任务和清理缓存。范围、失败行为与平台限制见 [账号实现](auth-implementation.md)。

| 范围 | 明确选择 | 结果与限制 |
| --- | --- | --- |
| Android 会话 | core:auth SessionStoreTest | 17 项通过；包括 profile 401 / 404、网络保留凭证、旧结果 / 旧 401 隔离、重复提交、取消、读写和清理失败 |
| Swift 会话 | SessionStoreTests | 16 个 test 通过，其中失效 profile 参数化覆盖 401 / 404 两个 case；其余场景与 Android 对齐 |
| Android 加密核心 | EncryptedTokenVaultTest | 6 项通过；真实 JCE AES-GCM、不同 nonce、AAD 后端隔离、损坏 / 缺失密钥、清理失败与大小限制；平台 IO 为合成替身 |
| iOS 存储适配 | KeychainTokenVaultTests | 5 项通过；Keychain 范围 / 属性、更新、删除、锁定 / 失败和坏数据；使用 FakeKeychainClient，没有写入系统钥匙串 |
| HTTP 基址与账号接口关联 | HttpTransportTest / HTTPTransportTests、AuthApiContractTest / AuthAPIContractTests | HTTP 各 9 项、账号各 3 项通过；新增基址范围用例各 1 项，覆盖默认端口、大小写、scheme、port、prefix |
| 增量映射 | scripts.ci.tests.test_impact | 累计 19 项通过；新增同平台存储 / 会话选择和 Android 适配设备缺口检查 |
| CI 执行器 | 新增会话 / 存储 selectors | Android 23 项、Swift 21 个 test 通过并核对结果报告；Android dry-run 仅含已登记 JVM 模块，未生成 APK |
| 格式 / lint / 规模 | 本批明确的 23 个文件，其中 Kotlin / Gradle 11、Swift 10、Python 1 | 通过，无新增行数预警；配置 JSON 另做结构检查 |
| 应用依赖 | app debugRuntimeClasspath | 严格依赖锁 / 校验下解析成功，core:auth 已加入；不是应用编译或运行 |

复查时补上 Android 在非协作请求返回后的取消检查，并让存储错误统一返回 storage，避免页面误报断网；相关用例及 CI 执行器复验通过。没有重跑无关后端或全量业务测试。

累计 214 个不同的已通过定向用例：backend 70、Android 56、Swift 40、文件规模 15、Git 范围 7、本地环境 7、CI 规则 19。Swift 按测试框架报告的 test 计数，参数化分支另注明；重复执行不重复计数。

当前 Android Keystore / AtomicFile 适配已写入 app，iOS Keychain 适配已在主机包编译；两端入口仍为开发壳，尚未创建实际应用会话容器。下一项是登录 / 注册 / 找回表单及容器接线，再按明确构建要求验证宿主与设备。没有修改原后端业务、访问个人钥匙串、构建 APK / IPA、提交、推送或部署；M1 / M2 阶段及成品目标仍未完成。

## M2-01 原生账号页面与本地构建检查点

2026-10-23：本轮明确获得双端本地构建与账号验证授权。Android / iOS 复用现有 AuthAPI、SessionStore、TokenVault 与后端路由，增加应用容器和登录 / 注册 / 找回表单。没有改写后端账号业务或迁入 Web 界面。当前登录后仍只是账号及退出入口，聊天和学习功能尚未接入。

| 范围 | 明确选择 | 结果与证据 |
| --- | --- | --- |
| Android 相关核心 | HttpTransportTest 10、SseContractTest 21、AuthApiContractTest 3、AuthFormControllerTest 7 | 选择的 41 项通过；后一次表单测试只选择该类，未调用根 test / build |
| Swift 相关核心 | HTTPTransportTests 9、AuthFormModelTests 7 | 16 项通过；表单共享样例、重复提交、取消、错误和倒计时覆盖独立于 UI |
| 增量规则 / 配置 / 读取器 | test_impact 22、test_native_configuration 2、test_auth_ui_fixture 3 | 27 项通过；包含 Debug / Release 网络配置、手动设备门禁、新账号不重用旧验证码 |
| Android 构建 | app:assembleDebug、uitests:assembleDebug | 严格依赖锁及 SHA-256 校验下成功；API 36 模拟器安装成功 |
| Android 原生账号 | AuthFlowTest.registerRestoreLogoutLoginAndReset | 1 项完整流程通过，74.809 秒；`.tools/android-auth-uitest-12.log` 明确报告 `OK (1 test)` |
| iOS 构建 / 原生账号 | SocraticMindUITests/AuthFlowTests 的两个明确用例 | 最终 `.tools/ios-auth-verified.xcresult`：2 项通过、0 失败；输入 / 显隐 / 下一项 / 替换 22.450 秒，完整账号流程 115.645 秒 |
| 格式 / lint / 规模 | 本批 67 个明确文件，Python 5、Kotlin / Gradle 19、Swift 14 | 固定语言工具与结构检查通过，0 行数预警；不是全仓格式化 |

原生完整流程通过真实页面连接专用 FastAPI / MySQL：错误验证码、注册、进程重启恢复、退出后重启仍退出、错误密码、重新登录、找回、旧密码失效、新密码登录、再次恢复及退出。验证了应用自身 Android Keystore / iOS Keychain 的实际写入、读取和删除；没有读取其他应用凭证。测试使用合成账号及本地 DEV 验证码，保留真实限流，没有 SMTP、模型或真实用户数据。

修复与取舍：Android 旧空闲连接导致写请求读取响应头 EOF，写请求改用零空闲连接池，读取保留池复用，不自动重放 POST，代价是串行写操作增加建连开销。iOS 复用 AuthTextInput 明确应用新密码整次编辑，保留密码内容类型，使用弱引用输入组管理键盘焦点；增加一层 UIKit 桥接，后续需持续验证系统输入能力。验证码测试按服务确认发码后的时刻等待真实 60 秒，读取器每轮分配新账号。依赖兼容、模拟器 ad hoc 签名及命令详见 [工具链](toolchain.md)和 [原生验证](native-auth-verification.md)。

本地产物为 `android/app/build/outputs/apk/debug/app-debug.apk` 和 `.tools/ios-derived/Build/Products/Debug-iphonesimulator/SocraticMind.app`；截图、日志、结果包和合成数据库均留在 Git 忽略目录。最终 iOS 测试使用新的独立环境，之前的数据保留；没有在用例中途重置后端限流。没有生成 IPA、上传、发布、提交或推送，远端 CI 仍未执行。

剩余边界：真机、最低系统、锁屏、重装 / 备份恢复、完整账号切换隔离、中文 / emoji 密码输入、密码管理器及系统自动生成密码、无障碍和触摸 / 软键盘细节待验。中文 / emoji 的 XCUITest 输入补充尝试未得到预期字符，未计入通过。M1 / M2 阶段和成品仍未完成；下一项继续普通聊天、会话与分页历史及复用消息组件，同时保留这些账号待验项。

## M2-02 会话摘要与分页读取检查点

2026-10-23：已核对固定源的 chat.ts / sessionTitles.ts / useChatSessions.ts。原客户端依靠全账号 messages 重建会话，节点 history 只返回最早 50 条；本仓库新增 `/api/chat/sessions` 和 `/api/chat/session-messages`，用固定消息 ID 上界和 before_id 分页。双端增加纯核心读取适配，复用原 HTTPTransport，完整消息保留 metadata / attachments。详见[会话核心](chat-history-implementation.md)和[兼容契约](../contracts/compatibility/chat-history.md)。

收益：客户端无需为了列会话下载全部正文，列表只读取短预览和当前标题；同一可见性 / 来源投影供新旧路由复用。取舍：维护两个新端点和双端适配，客户端需先配套新版服务；上界不冻结标题、内容、删除或重生成状态，功能层仍须按账号及稳定 ID 去重 / 刷新。列表聚合的大数据 SQL 和设备性能尚未测量，不声称固定页大小意味着固定数据库开销。

| 范围 | 明确选择与结果 | 证据 / 限制 |
| --- | --- | --- |
| 新历史提供方 | test_chat_history_contract 18 项通过 | 包含共享样例、账号 / 模式隔离、插入删除间翻页、65 条消息、旧接口顺序、重生成可见性、输入校验、鉴权及短预览查询 |
| 后端相关集合 | 按影响映射选定的 45 项 pytest 通过 | 包含上述 18 项、相关来源 / 附件、流 / 生命周期、schema / models / migrations；`.tools/chat-history-ci-python.log`，不是全部 backend 测试 |
| MySQL | 新增历史投影 1 项、受启动器改动影响的迁移 / lifespan 3 项分别通过 | `.tools/chat-history-mysql.log` 与 `.tools/chat-history-mysql-harness.log`；8.4.11 独立临时 socket / 库，已清理，不操作持久开发库 |
| Android 核心 | 明确 7 个类共 68 项通过，其中新 ChatHistoryApiContractTest 4 项 | `.tools/chat-history-ci-android-final.log`；core:network / auth / chat 实际 test 任务执行，严格锁与 SHA-256 校验，无 APK 任务 |
| Swift 核心 | 明确 7 个 suite 共 51 项通过，其中新 ChatHistoryAPIContractTests 4 项 | `.tools/chat-history-ci-ios.log`；主机包，不是 iOS 应用 / UI 验证 |
| 共享无效页 | 两端各自覆盖相同 19 个场景 | 错序、重复、越界、游标不前进、会话 / 模式串用、错误 JSON 类型等被拒绝，不将 401 转为空历史 |
| 增量 / 质量工具 | test_impact 25、test_changed_files 7、test_file_rules 15，共 47 项通过 | 新增三方历史影响映射、MySQL 选择、JVM 允许边界与打包拦截；远端 CI 仍未运行 |
| OpenAPI | 58 路径快照匹配；原有 56 路径与旧 schema 比对均无变化 | `.tools/chat-history-compatibility.json`；没有数据库 migration 或 SSE 写入协议变更 |

第一次接线检查发现 Gradle 未将共享 Python fixture / JSON 声明为任务输入，已有网络测试可能被判为 UP-TO-DATE。三个 JVM 核心模块已补齐输入声明；修改后重跑受影响的明确选择，最终 68 项报告零失败 / 跳过。首次 Swift 新测试因遗漏 throwing initializer 的 try 编译失败，修正测试表达式后相关核心与执行器验证通过。以上子批次和回归不重复累加为“新用例”。

格式、lint、结构和行数检查覆盖本次 42 个明确文件；新增生产文件均低于预警值。唯一预警是已有 chat.py：抽出历史 schema / 投影后从 1275 减至 1216 行，登记上限已同步收紧，剩余流编排归 M2-03 继续拆分。源哈希 / 13 个历史 revision 保持原记录，不以移动代码隐藏大文件债务。

本检查点没有新建 APK / IPA 或 iOS 模拟器应用，没有调用真实模型、全量测试、提交、推送或部署。前一账号阶段的安装包仍只覆盖账号功能。下一步接入按账号清理的会话 / 历史状态、原生列表与消息组件，再完成标题、删除、头像、建议等原有动作；M2-02、M1 / M2 阶段及成品目标仍未完成。

## M2-02 会话状态与原生页面接线检查点

2026-10-23：先将前述已验证基础提交为 `ebbe07f`，随后按用户要求建立专用提交会话，开发与 commit 分工见[协作规范](ci-and-collaboration.md)。本批继续复用 SessionStore / HTTPTransport / ChatHistoryAPI，增加双端会话列表与消息页的同一状态所有者。退出立即清空，账号 revision、请求序号和取消一起阻止旧结果回填；刷新替换窗口，追加按稳定 ID 去重且不覆盖较新摘要。API / 后端 / 数据库没有变化。

Compose 与 SwiftUI 已接线账号容器、列表、选择、历史原文、加载更多、刷新、失败重试和退出。两种页复用 HistoryPageState 与分页控件，列表使用稳定 ID；页面不读取 Token。优点是页面和并发逻辑可独立迭代，代价是双端仍须分别验证生命周期和布局。控制器的读取流程保持同一状态 / 任务所有者，没有为缩短方法拆出多层转发；全部新增源码低于文件预警值。

| 范围 | 明确选择与结果 | 证据 / 限制 |
| --- | --- | --- |
| Android 新状态 | ChatLibraryControllerTest 9 项，相关 ChatHistoryApiContractTest 4 项实际执行通过 | `.tools/chat-library-android-core.log`；真实 SessionStore + 合成非协作请求，验证旧成功 / 错误、账号切换、当前 / 旧 401、关闭和分页重试 |
| Android 映射集合 | 8 个类对应 77 项零失败 / 跳过报告 | `.tools/chat-library-ci-android.log` 与 `.tools/chat-library-android-results.json`；本批首次运行 chat 的 13 项，其余 64 项核心输入未变，Gradle 复用先前有效报告；后续执行器检查全部 UP-TO-DATE，未伪称重新执行 77 项 |
| Swift 映射集合 | 8 个 suite 共 60 项通过，其中 ChatLibraryModelTests 新增 9 项 | `.tools/chat-library-ci-ios.log`；包括账号、会话、存储、网络 / SSE 及历史核心，未执行 SwiftUI 应用 |
| 增量与规模工具 | test_impact 27、test_changed_files 7、test_file_rules 15，共 49 项通过 | `.tools/chat-library-ci-python.log`；新增状态消费者和容器双向影响覆盖，其他平台 / 后端未误选 |
| 格式 / lint / 行数 | 变化 Kotlin / Gradle 13、Swift 10、Python 1 个文件通过 | `.tools/chat-library-quality.json`；0 文件行数预警，JSON / 文档另作结构检查 |
| 工程配置 | XcodeGen 重新登记两个页面文件；app debugRuntimeClasspath 严格锁 / SHA-256 下解析通过 | `.tools/chat-library-app-dependencies.log`；没有新增外部依赖、应用编译或打包任务 |

本批没有运行后端业务 / MySQL、全量测试、应用宿主构建、模拟器 / 真机、真实模型或远端 CI。消息先显示原文，附件仅显示数量；Markdown、代码块 / 表格、输入 / 发送、新建草稿、标题 / 删除 / 头像 / 建议及流恢复仍未完成。会话选择当前只保存在内存，重进程恢复与分页内存淘汰尚未实现。

新的页面编译、滚动锚点、系统返回、导航、动态字体 / 无障碍、长消息和完整设备账号隔离均待后续独立授权构建后验证。账号阶段的现有安装包不会自动包含本批代码。下一步继续消息展示和输入 / 会话动作；M1 / M2 及成品目标保持未完成。

## M2-02 Markdown 核心与原生消息组件检查点

2026-10-23：上一批会话状态已由专用提交会话提交为 `1d69abc`。本批复用原历史 / 账号状态和平台文字能力，采用 CommonMark Java 0.31.0、Swift Markdown / swift-cmark 0.9.0 解析，再投影为双端纯核心模型。原生消息组件已接入历史页，包含基础 Markdown、代码复制、表格横向滚动、安全外链和完整原文复制。范围、与上游的差异及预算取舍见[消息展示](message-rendering.md)。后端、API、SSE、数据库均未改变。

解析离开 UI 线程；账号页面持有有界内存缓存，退出清理并拒绝迟到结果；超限消息完整保留原文。收益是同平台消息组件可供后续节点聊天复用、复杂内容不会无界进入语法投影，代价是双端新增依赖和适配、部分长内容退回文字，以及实际布局 / 剪贴板 / 外链仍需宿主验证。

| 范围 | 明确选择与结果 | 证据 / 限制 |
| --- | --- | --- |
| 新消息核心 | 两端 MarkdownContract / MarkdownRenderer 各 8 项通过 | 21 组共享语义、26 组 URL 策略、7 类超限保留；缓存命中 / 淘汰、UTF-8 成本、清理 / 取消后迟到、独立范围及后台执行 |
| Android 关联集合 | 10 个明确 JVM 类，85 项实际执行通过，0 跳过 / 失败 | `.tools/markdown-ci-android.log` 与 `.tools/markdown-android-results.json`；依赖锁与共享 fixture 变化扩展已登记的 network / auth / chat 消费者，三个 test 任务均执行，无 APK 任务 |
| Swift 关联集合 | 10 个明确 suite，68 项通过 | `.tools/markdown-ci-ios.log`；使用锁定解析版本，主机包编译与运行，不是 SwiftUI 应用 |
| 工具与配置 | 58 项通过 | `.tools/markdown-ci-python.log`；影响映射 31、依赖锁 / 许可一致性 2、账号 UI fixture 读取器 3、Git 范围 7、文件规则 15；uitests 锁变化仅触发读取器核心，不运行设备测试 |
| 格式 / lint / 行数 | 变化 Kotlin / Gradle 13、Swift 13、Python 3 个文件通过；无行数预警 | `.tools/markdown-quality.json`；文档 / JSON / 工程另做结构与差异检查，未全仓格式化 |
| 依赖 / 工程 | 新增 9 个 Maven JAR / POM 摘要逐项核对；Gradle 严格锁运行成功；XcodeGen 生成、Xcode 固定版本依赖解析成功 | `.tools/markdown-maven-verification.json`、`.tools/markdown-xcode-resolve-strict.log`；SwiftPM 与 Xcode 同一组 pins，许可证原文留档；不是应用编译或安装 |

首轮共享样例发现两库对 HTML 块末尾换行不同，Android 投影已统一并复验；Swift 表格额外检查行宽与列对齐数量一致，覆盖空格 / 缺失单元格。新增代码按模型、解析、链接、缓存、行内展示及块展示拆职责，全部低于预警值，没有调整行数例外。

本批没有运行后端业务 / MySQL、全量测试、应用宿主构建、模拟器 / 真机、真实模型、远端 CI 或发布。代码语法着色、裸 URL 自动链接、来源引用和受保护附件预览尚未实现；原生文字选择 / 复制、外链交接、长消息布局、最低系统、动态字体、账号切换与滚动锚点仍待验证。账号阶段安装包不包含本批变化。继续实施输入 / 会话动作与可靠流式发送，M1 / M2 和成品目标保持未完成。


## M2-03 / M2-04 普通发送、停止与恢复检查点

2026-10-23：Markdown 批次已由专用提交会话提交为 `c04630a`。本批复用原后端稳定请求 ID、SSE、持久取消和请求状态接口，以及本仓库有界历史 API、SessionStore 和原生消息组件；没有修改 backend 业务、OpenAPI 或数据库，也没有新增外部依赖。实现、状态边界和取舍见[普通聊天发送与恢复](chat-turn-implementation.md)。

双端已接入新建会话目标、内存输入、发送、停止、只读核对和恢复文件。先保存无正文标识再 POST；断线 / DONE / 404 不直接代表完成或允许自动重发。终态读取精确消息 ID，合并前使旧历史请求失效；历史确认接收结果后才开放下一次发送。清理记录失败时仍保留已确认消息交接，覆盖“删除已生效但清理报错”的情况。UI 临时预览使用最多 32 行纯文本，完整已接收内容可复制；终态复用 Markdown。优点是减少重复生成与状态丢失，代价是未确认时保守阻止新发送，以及生成中暂时没有富文本排版。

| 范围 | 定向结果 | 证据 / 限制 |
| --- | --- | --- |
| 新核心 | 两端各 API 5、状态 12、文件存储 4 项；历史各新增 2 项 | 共享输入 / Unicode、8 个无效状态、6 个取消响应；另含故障、竞态、迟到结果和完成交接；不是 UI 测试 |
| Android 关联集合 | 12 个明确 JVM 类共 87 项零失败 / 跳过报告 | `.tools/chat-turn-ci-android.log` 首轮 86 项三个 test 任务实际执行；补充清理故障后 `.tools/chat-turn-final-android.log` 执行 chat 的 44 项，43 项未受后续修改影响的 auth / network 复用有效报告；无 APK 任务 |
| Swift 关联集合 | 13 个明确 suite，91 项通过 | `.tools/chat-turn-final-ios.log`；锁定依赖的主机包，没有 SwiftUI 应用编译 / 安装 |
| 后端提供方 | 5 项新契约及 5 项明确生命周期用例，共 10 项通过 | `.tools/chat-turn-ci-python.log`；FastAPI + 隔离 SQLite + 替身模型，取消先于到达、已完成 / 中断取消、精确查询邻居及重放；没有外部服务或 MySQL 操作 |
| 工具回归 | 58 项通过 | 同上：影响映射 34、依赖锁 / 许可 2、Git 范围 7、文件规则 15；共享输入变化显式扩展消费者，没有全量测试 |
| 质量与工程 | 变化 Kotlin 19、Swift 19、Python 4 个文件格式 / lint 通过；XcodeGen 登记新输入组件 | `.tools/chat-turn-final-quality.json`、`.tools/chat-turn-final-structure.log`、`.tools/chat-turn-xcodegen.log`；2 项行数预警已审查，不增加例外或抬高限额 |

两次本地执行修正了新代码的格式问题，以及首次直接运行 pytest 时模块搜索路径缺失；改用仓库执行器的 Python module 入口后提供方验证通过。影响映射测试中原有固定预期因新增消费者而失败，已按真实依赖更新并新增 3 个边界用例，不减少测试范围来规避失败。主机测试结果没有被当作原生页面运行结果。

本批不生成 APK / IPA / iOS 模拟器应用，不调用真实模型，不运行设备测试或远端 CI，不 push。原账号安装包不包含这些源码。文件保护、备份排除、断电、真机进程终止与前后台 / 网络切换，输入法、滚动跟随、动态字体、无障碍和实际 A/B 隔离仍待定向验证。持续损坏恢复文件的用户修复界面、重生成、标题 / 删除 / 头像 / 建议和真实模型配置继续实施；M1、M2、P03 与成品目标均未关闭。

## M2-03 普通文字重生成检查点

2026-10-23：发送批次已提交为 `96e70ee`。双端新增最后一问的普通文字回答重生成，复用既有发送 / 停止 / 恢复协调器，保留草稿和原回答；成功后按稳定 ID 替换，失败或停止清理本次临时行。后端及固定上游行为已核对，backend 本批仅新增契约测试。上下文资格、schema 兼容与取舍见[发送实施](chat-turn-implementation.md)。

| 范围 | 定向结果 | 证据及实际执行边界 |
| --- | --- | --- |
| Android | 13 个明确 JVM 类合计 96 项零失败 / 跳过 | `.tools/chat-regeneration-android.log` 首轮三个 test 任务执行；后续状态修正执行 chat，auth / network 43 项复用未受后续修改影响的报告。最终 API 类 6 项单独执行于 `.tools/chat-regeneration-api-final.log`，其他类结果见 `.tools/chat-regeneration-android-final.log`；聚合明细 `.tools/chat-regeneration-android-results.json` |
| Swift | 13 个明确 suite，Swift Testing 报告 93 项通过 | `.tools/chat-regeneration-ios-final.log`；锁定依赖的主机包。未选 SSE 独立解析 suite，网络层后续消费者按回环 fixture 影响扩展 |
| 提供方 | 9 项发送 / 重生成契约及 7 项既有生命周期用例，共 16 项通过 | `.tools/chat-regeneration-provider-final.log` 和同名 provider XML；FastAPI + 隔离 SQLite + 替身模型，覆盖生成中 / 完成 / 失败 / 中断可见性、只复用原问题和旧问题拒绝 |
| 工具 | 56 项通过 | `.tools/chat-regeneration-tools.log` 从 `.tools/chat-regeneration-python-final.log` 的 unittest 成功段提取；影响映射 34、Git 范围 7、文件规则 15。本批未改依赖锁，未重复运行锁 / 许可检查 |
| 质量 | 变化 Kotlin 10、Swift 10、Python 4 个文件格式 / lint 通过 | `.tools/chat-regeneration-quality.json`；结构 / 差异检查和最终影响清单见 `.tools/chat-regeneration-structure.log`、`.tools/chat-regeneration-plan.json` |

验证中修正了固定测试数量断言、对“生成中历史会返回临时回答”和旧问题拒绝 HTTP 400 的测试假设，并据实际提供方行为补齐双端筛选 / 缓存清理。另发现新增 Kotlin wire 测试表达式返回异常对象，JUnit 没有发现该方法；显式返回 Unit 后，逐方法核对 API 类 6 项实际执行，不把先前仅 5 项的报告作为新用例通过证据。

行数预警：ChatTurnController 360 行，重生成仍复用同一账号状态、任务序号及持久化顺序；新增资格判断、历史投影和文件 IO 各有独立职责，未把同一状态拆成互相调用的控制器。test_impact.py 521 行，增加已登记消费者的精确预期；维持原上限，后续按映射 / runner / Git 范围组织拆分。均低于硬上限，无新豁免。

原生按钮、草稿保留、历史刷新、滚动和进程恢复尚未重新编译 / 上机。本批无 APK / IPA / 模拟器应用构建、真实模型、外部部署、全量测试、远端 CI 或 push。附件 / 引用 / 概览重生成、会话标题 / 删除 / 头像 / 建议、损坏记录修复及真实模型继续按计划实施；P03、M2 和成品验收均保持未完成。

## M2-02 标题与删除接口检查点

2026-10-23：复用既有标题服务、删除路由和双端 HTTPTransport，新增标题 / 删除核心适配和共享合成样例。手动命名增加 JSON 入口，支持特殊字符会话 ID 和没有自动标题的旧聊天；旧路由、schema 与删除流程保留。实现目的、取舍、升级顺序和接线边界见[标题与删除接口](chat-actions-implementation.md)。本批还没有操作状态或原生界面。

| 范围 | 明确选择与结果 | 证据 / 限制 |
| --- | --- | --- |
| Android | 12 个类、92 项通过，动作契约类 4 项实际执行 | `.tools/chat-actions-android-final.log` 与 `.tools/chat-actions-android-results.json`；core:auth / network / chat 的 test 均实际执行，无 APK 任务 |
| Swift | 12 个 suite、89 项通过，动作契约 suite 4 项 | `.tools/chat-actions-ios-final.log`；锁定依赖的主机包，无 iOS 应用编译 |
| 后端 | 动作契约 7、已有标题 11、删除生命周期 2、OpenAPI 3，共 23 项通过 | `.tools/chat-actions-python-final.log`、`.tools/chat-actions-provider.xml`；FastAPI + 隔离 SQLite，模型替身，无真实模型或 MySQL 运行库操作 |
| 工具 | 影响映射 35、Git 范围 7、文件规则 15，共 57 项通过 | 同一 Python 日志的 unittest 段；已登记动作端点、三方样例和新增消费者，未扩大为全部业务测试 |
| 兼容与质量 | 58 路径快照一致；旧 operation / schema 保持原值；Kotlin 2、Swift 2、Python 6 个变化文件格式 / lint 通过 | `.tools/chat-actions-compatibility.json`、`.tools/chat-actions-quality.json`、`.tools/chat-actions-structure.log`；精确范围见同名 scope / plan JSON |

检查修正了新增消费者后的工具断言，以及“整段会话删除后查询返回 409”的错误预期：当前服务移除整段请求记录后返回 404，部分消息删除才可能返回 409。新增验证继续确认同一 request_id 的取消标记与旧 writer 失效，客户端保留原有保守恢复语义。原有路由模块导入产生 5 条 Pydantic 弃用警告，未在此动作子任务中改动无关模块。

test_impact.py 从 521 增至 536 行触发职责复查，结论见动作实施文档；未超硬上限、未提高限制或增加例外。没有迁移、依赖或工作流发布配置变化。共享 HTTP fixture 的相关消费者按映射扩展，重复执行不累计为新用例。

下一步接入按账号隔离的操作状态与双端确认 / 编辑 / 消息选择界面，并验证迟到历史和发送竞争。P02、M2 与成品均保持未完成。此前账号阶段的安装包不包含本批代码；新的应用构建与原生验证仍待独立授权，本批未执行构建、外部部署、全量测试、远端 CI 或 push。

## M2-02 原生标题与删除操作检查点

2026-10-24：在接口提交 `53c1f17` 上复用 SessionStore、ChatLibrary、ChatTurn 与 MessageContent，接入双端会话管理菜单、标题编辑、整段删除确认和最多 100 条消息的选择删除。新增操作状态负责有限写入，发送协调器拥有互斥占用；旧读取和旧账号响应不能覆盖成功结果或释放新占用。目的、取舍及失败边界见[动作实施](chat-actions-implementation.md)。

| 范围 | 明确选择与结果 | 证据 / 限制 |
| --- | --- | --- |
| Android | 9 类、77 项有效报告，新增动作状态 10 项 | `.tools/chat-management-android-final.log`、`.tools/chat-management-android-results.json`；core:chat 的 53 项最终实际执行，auth 24 项在前一次 `.tools/chat-management-android.log` 执行通过后缓存复用 |
| Swift | 12 个 suite、90 项通过，新增动作状态 10 项 | `.tools/chat-management-ios-final.log`、`.tools/chat-management-ios-results.xml`；旧账号结果同时覆盖成功及迟到 401 两个参数分支，测试框架按 test 计数 |
| 工具 | 64 项通过 | `.tools/chat-management-python-final.log`：影响映射 37、原生配置 / 登记 3、包锁 2、Git 范围 7、文件规则 15；本批 backend / 契约 / 数据库未改，不重复运行后端集合 |
| 工程 / 质量 | 变化 Kotlin 13、Swift 13、Python 2 个文件格式 / lint 通过，结构和差异检查通过 | `.tools/chat-management-quality.json`、`.tools/chat-management-structure.log`；XcodeGen 仅登记两个宿主源码文件，未编译应用 |

新增状态用例覆盖：确认前不写、重复点击、Unicode 标题上限、发送 / 修改互斥、尚未交接的发送结果、旧占用释放、删除后旧读取、部分删除保留草稿、失败显式重试、账号退出后重新登录的迟到成功 / 401、当前 401、选择上限与刷新后再次核对 ID。首次账号切换测试直接在已登录状态下再次登录，触发已有 busy 规则；已改为退出再登录，与应用实际流程一致。

首次检查发现 Xcode 工程文件通配规则把源码登记变化扩展到 16 个 Swift suite，现已拆出 ios-project：校验宿主源码登记、当前本地 MindCore 引用及配置 / 包锁，Swift 核心最终仅选择 12 个相关 suite。依赖 manifest / 锁文件变化仍扩展已登记消费者；新增原生源码仍必须登记影响映射。静态登记检查不代表完整 Xcode 配置或 UI 验收。

预警审查：ChatTurnController 391 行、ChatTurnModel 301 行保持同一发送状态和修改占用所有者；test_impact.py 598 行保留明确消费者及 runner 回归。均低于硬上限，未提高限制或登记例外。最后的界面复查补充了 Android 选择控件的朗读标签，以及 iOS 列表按钮的独立点击样式；相关文件重新运行格式 / lint，未把它们描述成设备测试通过。

操作界面尚未重新编译或运行；没有构建 APK / IPA / iOS 模拟器应用，没有真实模型、外部部署或 push。自动标题有界轮询、会话头像、建议和设备验收继续实施；本机互斥不等于服务端超时写入被取消，跨设备竞争与进程重启后的核对仍待验。P02、M2 和 P01—P16 成品目标均保持未完成。

## 2026-10-24 自动标题批量更新检查点

双端已接入[自动标题更新](chat-title-refresh.md)：复用现有标题 worker、GET 接口、公共传输和 SessionStore，ChatLibrary 维护独立标题读取通道。每批最多 100 个不同会话，每周期最多 8 次；后续只保留仍在生成或等待服务端重试的项。可见性关闭、账号变更、摘要刷新及修改成功使旧任务失效，迟到结果不能覆盖手动标题或恢复已删除行。

当前打开的旧会话优先读取，即使刷新后的最新一页不包含它；只更新页头，不把旧摘要插回新页。缺失标题不触发补建任务。网络失败、生成失败和预算耗尽保留历史并提示刷新。Android Lifecycle / SwiftUI scenePhase 接线已写入源码，尚未运行应用验证。

| 范围 | 执行结果 |
| --- | --- |
| Android 初次受影响集合 | 16 类 122 项通过；公共 URL 重复参数影响账号、历史、发送及标题接口消费者，页面变更保留已有 Markdown / 状态验证 |
| Android 旧会话补充后的相关集合 | 7 类 73 项有效报告；chat 56 项最终实际执行，SessionStore 17 项使用有效 UP-TO-DATE 报告；与初次集合按测试类合并为 16 类 123 项，零失败 / 跳过 |
| Swift 初次受影响集合 | 16 suite、119 项通过；XML 119 项 |
| Swift 旧会话补充后的相关集合 | 7 suite、72 项通过；与初次集合按 suite / 用例合并为 120 项，零失败 / 跳过 |
| 新增状态验证 | 双端各 11 个测试方法；旧账号覆盖成功 / 401 分支，包含预算、候选上限、后台取消、改名 / 删除 / 新摘要迟到保护及当前旧会话 |
| 后端与工具 | 后端动作 / 标题 / 两项删除生命周期 / OpenAPI 共 24 项；影响映射 38、Git 范围 7、文件规则 15，共 60 项；OpenAPI 58 路径保持一致 |
| 格式与规模 | 变化 Kotlin 13、Swift 13、Python 3 个文件的固定格式 / lint 通过；ChatLibraryController 357 行、test_impact.py 632 行预警已记录职责审查，无超硬上限或新增豁免 |

旧会话补测最初在读取仍标为 loading 时请求第二次刷新，测试等待了不会重复发出的请求；补充等待首次历史完成后，相关集合复跑通过。没有通过移除断言或增加超时掩盖问题。

本机证据在忽略目录 .tools/title-refresh-*，包括初次 / 最终日志、原始 Swift XML、Android 分批 / 合并报告、变化范围和质量报告。没有新 APK、IPA、模拟器应用、真实模型调用或远端 CI；设备前后台、最低系统和完整 P02 仍待验。上下文建议、头像、完整上下文重生成、模型设置及后续学习功能继续按计划实现，M2 与成品均未完成。

## 2026-10-24 上下文建议检查点

双端已接入[上下文建议](chat-suggestions-implementation.md)：复用现有建议路由、有限 HTTP 传输、账号 / 历史状态和单次持久发送。新会话本地话题、已有会话自动建议、显式换一批、来源标签和已有草稿确认已写入原生入口。建议状态独立于历史及发送状态；上下文只记录最近相关消息的摘要，AI 结果按 30 项 / 64 KiB 正文预算缓存在内存中，退出清理。

| 范围 | 执行结果与证据 |
| --- | --- |
| Android | 18 个明确 JVM 类 138 项零失败 / 跳过；auth / chat / network 三个 test 任务本次实际执行；`.tools/suggestions-android-final.log` 与 `suggestions-reports/TEST-*.xml` |
| Swift | 18 个明确 suite 135 项零失败 / 跳过；Swift Testing 原始 XML 与日志保存在 `.tools/suggestions-reports/ci-swift-swift-testing.xml`、`suggestions-ios-final.log` |
| 新增建议测试 | 双端各 API 3 项、状态 12 项；账号迟到用例包含成功 / 401 分支，验证取消确认后的排除项、重复确认单次发送、缓存与上下文隔离 |
| backend | 新增建议契约 2、已有建议 11、OpenAPI 3，共 16 项通过；合成账号 / 模型与隔离 SQLite；5 条已有依赖弃用警告，未改变生产后端 |
| 工具 | 66 项通过：影响映射 39、原生配置 3、包解析 2、Git 范围 7、文件规则 15；OpenAPI 58 路径一致；`.tools/suggestions-python-final.log` |
| 质量与规模 | 变化 Kotlin 13、Swift 12、Python 4 个文件通过固定格式 / lint；423 / 318 行发送协调器及 678 行影响测试的职责审查见功能文档，低于硬上限，无新增豁免 |

共享回环 HTTP 服务变更扩大了已登记接口消费者的验证范围；原生容器接线同时选择相关账号、状态、存储与 Markdown 集合。计划与统计见 `.tools/suggestions-plan.json`、`suggestions-results.json`。XcodeGen 已登记新增组件，只生成宿主工程，没有编译应用。

验证过程中修正了 Swift 测试替身的 actor 隔离编译问题、影响映射测试编辑时的缩进错误，并补测取消草稿确认后显式刷新仍携带已显示项；最终集合全部通过。没有执行全量测试、新 APK / IPA / 模拟器应用构建、真实模型调用、远端 CI 或 push。建议 UI、真实生命周期、模型质量与节点页面仍待验；头像、完整上下文重生成、模型设置及后续学习功能继续实施，M2 与成品保持未完成。
