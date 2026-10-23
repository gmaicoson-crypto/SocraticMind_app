# CI、测试与协作规范

状态：M1 实施中的检查方案。后端已迁入并完成首批定向验证，工作流实际运行情况见 [实施状态](execution-status.md)。后续仅测试修改及相关范围；APK 只在用户明确要求构建时生成。

当前目标为完整双端功能和本地开发交接，阶段和工作项见[交付计划](delivery-plan.md)与[实施任务](implementation-backlog.md)。CI 规则适用于这些任务，但质量汇总本身不代表成品验收。

## 与交付阶段衔接

| 阶段 | 自动检查范围 | 需要独立记录的证据 |
| --- | --- | --- |
| M1 | 来源迁入涉及的后端 / 迁移、工具规则、双端核心和契约 | 工程运行、设备技术验证、实际 CI 触发；不凭 YAML 存在宣布完成 |
| M2—M4 | 对应任务修改及其消费者；契约 / 共享逻辑扩大到相关三方 | 产品 P 编号与 J 场景、两端设备、性能和外部依赖小样联调 |
| M5 | 候选变更及升级 / 兼容影响范围，保留有效阶段证据 | 签名包与安装升级、运行环境、恢复演练、分发有效期和维护交接 |

最终验收检查证据覆盖，不自动执行全量测试。变更使相关证据失效时按映射补测；未运行的设备、性能、邮件 / 模型真实联调不能算作自动检查通过。记录源 SHA、客户端构建号、backend / migration 版本及脱敏报告，未来维护在 docs/releases 中。完整标准见[交付验收](release-acceptance.md)。

ops 中的部署模板或运行配置变化，按依赖映射触发受影响的配置校验、启动 / 健康、SSE 代理、附件或隔离迁移检查；文档类交接记录只做文档校验。CI 不读取 beta 环境密钥，不在运行库执行恢复或迁移。

## 格式与结构质量门禁

完整规则见 [代码质量规划](code-quality.md)，职责和依赖方向见 [核心拆分规划](core-modules.md)。本节包含目标工作流与当前实现边界。已有本地增量检查、显式测试映射及 quality.yml；GitHub 实际执行、完整架构边界检查仍待完成。

变化代码先按语言批量格式检查和 lint，再按统一物理行数检查文件规模，并验证相关依赖边界；之后运行受影响测试。CI 不自动修复、暂存、提交或推送。格式不通过时不能用格式化前的行数宣布结构合格。

新增 quality/structure job 在 Linux 运行，只分析变化手写代码、相关依赖和必要的基线 / 例外记录；语言工具在各自 job 运行。达到预警值报告但不单独阻断，超过硬上限且无有效基线 / 例外、禁止依赖、配置异常或检查器错误均失败，汇总 job 传播结果。

本地 fix 仅处理显式文件，不自动扩至全仓；CI 的 PR / push 文件集合与测试影响映射复用同一基线。格式与规模配置变化时检测受影响范围；新增配置不能默默抬高门槛或把新代码列为历史债务。

M1 应验证检查器对上限边界、删除 / 重命名、部分暂存、生成物、失效例外和历史基线收紧的处理。报告记录旧 / 新行数、分类、限制与理由，未运行工具必须显式说明，不凭文件存在报告通过。

## 检查、测试与打包边界

单元测试通常需要编译被测代码；编译测试类 / 测试可执行文件不等于生成 APK 或 IPA。必须检查实际任务依赖，不根据命令名称猜测有无打包。

| 类型 | Android | iOS | 未来默认触发方式 |
| --- | --- | --- | --- |
| 文档 / 契约静态校验 | 链接、JSON / SSE 样例、版本记录 | 同一份规格 | PR 自动，仅变化及相关范围 |
| 代码静态检查 | 变化 Kotlin 的 ktlint、相关模块 Android Lint | 变化 Swift 的 SwiftFormat / SwiftLint | PR 自动，明确格式检查不等于编译 |
| 核心逻辑单测 | 纯 JVM JUnit、coroutines-test、MockWebServer | macOS 上 MindCore 的 Swift Testing / XCTest、mock transport | PR 自动，限定类 / 用例；无安装包 |
| 平台相关本地单测 | 核实任务图后的相关模块 JVM 测试 | 无法主机运行的 iOS API 用例需模拟器宿主 | Android 可自动；iOS 纳入手动原生验证 |
| UI / 生命周期 / 权限 | Compose 仪器测试需要设备及应用 / 测试 APK | XCUITest / iOS app-hosted 测试需模拟器应用 | 独立手动，Android 必须有明确 APK 构建要求 |
| 签名打包与发布 | APK / AAB | archive / IPA | 独立手动构建；商店发布另行触发 |

iOS 的模拟器 `xcodebuild test` 会编译测试和应用宿主，虽然不导出 IPA，也不能描述为“不构建”。本项目先将模拟器应用验证列为独立手动任务；纯 Swift 包主机测试自动运行。由此造成的 SwiftUI、设备 API 和 UI 覆盖缺口必须在 PR 中说明，后续有运行条件时补齐，不以核心测试通过代表完整应用可运行。

Android 官方区分主机本地测试与设备测试；Apple 支持选择特定测试运行。[Android 测试](https://developer.android.com/training/testing)、[Apple 测试运行](https://developer.apple.com/documentation/xcode/running-tests-and-interpreting-results)

后端自动校验采用变化 Python 文件的 Ruff format / lint、明确文件或 node ID 的 pytest、契约检查，以及按影响触发的隔离 MySQL 测试。导入后端不代表获得部署或生产数据库迁移授权；只可对明确隔离的临时实例执行验证，不操作原产品数据库。

## 工作流与执行环境

仅规划以下工作流职责，M1 工程建立后才创建 YAML 与脚本。

| 任务 | 环境 | 内容 |
| --- | --- | --- |
| quality / changes | Linux | 校验 diff 基线、列出文件、解析依赖与测试映射 |
| quality / structure | Linux | 变化文件行数、迁入基线、例外有效性与相关依赖边界 |
| quality / docs-contracts | Linux | 变化文档、脱敏 OpenAPI、SSE 和 fixtures 格式检查 |
| quality / backend | Linux、固定 Python | 变化 Python 的 Ruff format / lint、相关 pytest、后端启动配置与运行行为验证 |
| quality / contract-drift | Linux、固定 Python | 后端可执行代码 / 配置或契约快照变化时导出 OpenAPI 比对，检测相关 SSE / 错误语义变化 |
| quality / backend-db | Linux、一次性 MySQL | schema / migration / SQL 行为受影响时做相关集成测试、迁移链与升级验证 |
| quality / android | Linux、固定 JDK / SDK / Gradle Wrapper | 变化代码格式检查、相关模块 lint、相关 JVM 单测 |
| quality / ios-core | 固定 macOS / Xcode / Swift | 变化 Swift 静态检查、MindCore 相关主机测试 |
| quality / summary | 汇总 | 始终报告本次所需任务状态、执行范围和未覆盖能力 |
| native-validation | 手动、选定 SHA / 平台 / 用例 | Android 设备和 iOS 模拟器 / 真机定向验证；如生成 APK 须明确构建要求 |
| package-mobile | 手动、选定 SHA / 平台 / 环境 | APK / AAB 或 archive / IPA；不自动上架 |
| deploy-backend | 后续独立手动发布流程 | 指定服务版本与目标环境，迁移、健康检查和恢复步骤分开记录；普通 PR 不部署 |

`quality.yml` 顶层不以 paths 跳过整个工作流，通过内部任务判断受影响平台；分支保护绑定稳定的汇总检查名。客户端仅内部 UI 变更时只启动相关平台；backend 内部变更且契约 / 行为不受影响时不启动客户端任务。contracts 或后端公开行为变化联动后端与双端相关测试。纯文档不安装三个工程的依赖。

不能只根据 contracts 是否有文件变化判断客户端影响：backend 的路由、schema、鉴权、错误、SSE、序列化与会话行为变化均进入接口影响检测。OpenAPI 无差异也不等于业务行为兼容，仍需用路径映射与行为契约覆盖。共享基础服务影响多个消费者时扩大相关集合并说明理由。

汇总检查传播失败、非预期取消和未映射变更；预期无需执行的平台可明确标记跳过，不将未运行测试计入通过数。质量汇总成功只代表当前自动检查范围，不代表设备验收或可发布。

## 增量范围计算

1. PR 使用可验证 base / head 的 merge-base 差异；push 使用 before 到 after；首次 push 用空树，不能引用不存在的 HEAD~1。
2. 使用能处理空格、删除和重命名的文件列表；删除文件也按原路径寻找受影响测试。
3. 在 M1 建立版本化影响映射，记录功能目录、Gradle 模块 / Swift targets / Python 模块与路由、直接与反向依赖、pytest 用例、迁移链、共享 fixture 消费者。
4. Kotlin / Swift / Python 文件变化先选所属功能，再扩大到直接和间接使用其公开接口的相关测试；不简单把“文件未变化”当作测试无关。
5. contracts 下只影响某接口的修改，触发后端提供方及双端该接口的相关业务测试；共享鉴权、错误协议变化扩至其消费者，可能覆盖多个功能，说明原因。
6. Gradle / Xcode / Package.resolved / Python 依赖与配置文件变更触发对应工程兼容性和受影响依赖消费者测试。无法确定影响时要求补充范围，不能默认全量，也不能无测试通过。
7. 业务变更没有映射、期望测试未被发现、过滤后为零用例时，使检查失败。文档无业务测试是显式允许的情况。

源仓库的差异检查、Ruff 配置和 pytest 用例可复用并适配本仓库；不照搬上游固定测试集合。Node / pnpm、Vitest 和 Web build 不作为本仓库原生客户端的依赖。增量脚本未来可以用标准库 Python 实现，无需为文档引入前端运行时。

## 后端校验与契约联动

| 变化范围 | 后端检查 | 客户端联动 |
| --- | --- | --- |
| 仅 backend 文档 | 文档和链接 | 无 |
| 内部服务实现，公开行为不变 | 相关单测 / 集成测试、OpenAPI 漂移检查 | 无；需有范围依据，不能仅凭开发者声称不变 |
| routers / schemas / 鉴权 / 序列化 | 相关接口、用户隔离、错误与兼容测试 | 两端对应消费者 |
| Chat / SSE / 幂等 / 取消 / 恢复 | 状态机、事件顺序与终态、断流相关用例 | 两端 SSE 和会话恢复测试 |
| models / alembic / 数据库访问 | 相关 MySQL 集成、revision / 升级测试 | 返回值或语义变化时联动 |
| 依赖 / core / 配置 | 启动配置、涉及依赖的消费者与契约检查 | 协议或行为受影响时联动 |
| 附件解析 / worker | 相关解析、隔离、超时、状态与清理用例 | 上传、解析状态、来源语义变化时联动 |

Python 工具链基于迁入依赖先做兼容验证再固定，不根据源 README 的最低版本直接安装。本地与 CI 使用独立虚拟环境。Ruff 格式规则从上游根 pyproject 核实迁入；lint 规则按增量策略启用。首次来源核对、格式规范化和业务变更分开审阅，按质量文档建立旧文件规模基线；日常不做全仓格式整改。

pytest 选择明确文件 / node ID 或经验证的标记集合，不调用无范围的根目录 pytest，不直接照搬全部 tests/p0。测试发现为零或相关用例缺失时失败；映射无法确定时先补充，不自动运行全量测试。backend 改动不自动触发 APK 构建。

FastAPI 的 OpenAPI 由本仓库应用导出，经稳定化处理与 contracts/openapi 比对；使用隔离测试配置并替换外部依赖，避免导入 / lifespan 触发真实 AI、worker 或业务数据库连接。仅 schema 导出不能代替启动健康测试；启动测试另在受控 mock 或临时数据库中执行。[FastAPI OpenAPI](https://fastapi.tiangolo.com/how-to/extending-openapi/)、[FastAPI 测试](https://fastapi.tiangolo.com/tutorial/testing/)

SSE、错误码、幂等与恢复语义使用后端提供方测试和 Kotlin / Swift 消费者测试共享样例。后端修改必须更新对应契约和样例；不能只更新快照掩盖破坏性变更。必要的流式传输测试使用本机临时服务、固定假模型和超时，内存 TestClient 的缓冲结果不作为真实网络逐块到达的证明。

接口演进优先添加可选字段，保留支持期内旧客户端能力；破坏性变更需明确新旧协议并存、弃用和发布顺序。PR 写明后端、Android、iOS 的影响和最低兼容范围，同一个提交不等于同时上线。

## 数据库与后端集成测试

源测试包含 SQLite，适合复用其中纯业务场景，但不能证明 MySQL 的锁、JSON、索引或迁移行为正确。变化涉及上述行为时启动固定版本的一次性 MySQL，使用测试库、合成数据和独立临时附件目录，不连接原项目或生产数据库。

迁移变化时检查 revision 连续性与单一有效 head，验证空库升级到目标版本、支持的前一版本升级、代表性数据保留和迁移后服务启动。空库初始化可执行完整迁移链，这是相关迁移验证，并非全量业务测试。已有 revision 不改写；不对未知库执行 stamp；已分化上游迁移不能直接叠加。[Alembic 迁移说明](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

支持 downgrade 的新增迁移验证其回退行为；不可逆迁移记录备份恢复 / 向前修复方案，不能用通过一个 downgrade 测试替代恢复演练。CI 仅验证隔离库，发布时的生产迁移另行执行。

附件解析如依赖 LibreOffice、字体、Bubblewrap 等运行环境，只在相关 job 提供固定 Linux 环境；相关验证不能因缺少组件静默跳过并记成功。普通后端用例使用受控 mock，解析专项测试使用脱敏小样例，无真实 LLM、邮件或搜索请求。

## 定向测试执行方式

以下是未来的命令模式说明，不是当前可执行入口；模块、类名、scheme 和测试 ID 必须以 M1 实际生成并发现的结果为准。

- Android 纯 JVM 模块执行对应 `test` task 并使用 `--tests` 选择已确认的测试类或方法；Android library 的本地测试可能使用 `testDebugUnitTest`。首次接入与 Gradle 配置变化时检查 task graph，确认不依赖安装包任务。
- 不直接调用根 `test`、`check`、`build` 或无范围任务；lint 允许分析相关模块及依赖，不能声称是严格单文件类型校验。
- iOS MindCore 采用 `swift test --filter` 执行相关主机测试；通过 SwiftPM 可编译、运行包内测试，但不验证 iOS 应用 target。[SwiftPM 文档](https://docs.swift.org/main/documentation/packagemanagerdocs/)
- 手动应用验证使用已提交的共享 scheme 和限定 test plan / `-only-testing`，选择固定模拟器 / 真机；不以 `test-without-building` 绕过缺少匹配测试产物的问题。
- 同一 fixtures 由 backend pytest、Gradle test resources 与 SwiftPM test resources 加载，原生资源通过受控准备步骤引入，记录来源摘要并验证三方使用相同内容，禁止人工维护多份无关联样例。准备过程在 M1 设计并验证，不在本轮新增脚本。
- 测试均使用固定 mock，不访问生产账号、生产数据库或真实付费模型。HTTP 层验证表单登录、鉴权、错误响应、POST SSE；基础库单测不需要真实手机。

## 测试影响映射

| 变化区域 | 必须覆盖的相关验证 |
| --- | --- |
| Auth / CredentialStore | 登录、凭证读取、401、退出、路由状态、跨账号隔离 |
| Chat / SSE | UTF-8 分片、CRLF / 事件分界、错误与终态、取消失败、恢复、重复提交与消息去重 |
| Markdown / MessageItem | 代码块、表格、来源与安全外链、长消息；布局另列 UI 验证 |
| Onboarding / Agent | run 版本、恢复、确认、取消、失败重试、结构化消息 |
| Plans / Learning | 时区边界、重排、节点状态、进入节点问答；图谱手势另列设备验证 |
| Assessments / Memories | 掌握撤销、评估提交和恢复、CRUD、错误 |
| Attachments / FileGateway | 限制、上传取消、解析失败、受保护预览；真实权限和选择器另列设备验证 |
| Notes / 本地存储 | 防抖落盘、版本迁移、账号隔离、导出与恢复 |
| contracts / 共享 fixture | 后端提供方与双端消费者的解码、错误、兼容性与期望结果 |
| backend 服务 / schema / migration | 相关 pytest、API / SSE 契约、按影响触发的 MySQL 与升级验证 |
| 格式 / 行数 / 依赖检查器及规则 | 相关工具规则样例、检查器边界用例、受影响代码集合；不自动运行全量业务测试 |
| 生命周期 / 原生配置 | 核心逻辑可 mock；杀进程、后台、键盘与权限行为另做双端设备验收 |

后端复用并适配源 pytest；客户端复用源测试的业务场景和断言意图，在 Kotlin / Swift 中分别实现；不直接运行 Vue Test Utils 用例。新增缺陷优先补有意义的回归用例，文档调整不为凑数编写测试。

## 构建与发布约束

默认质量流水线不得调用 `assembleDebug`、`bundleRelease`、`connectedAndroidTest`、Managed Device tests 或其他会生成 APK 的任务；即便产物只用于测试，也需要用户明确要求构建。任务名称为 test 不代表必然没有打包依赖。

`native-validation.yml` 和 `package-mobile.yml` 只计划使用 workflow_dispatch；定义入口不等于获得本次执行授权。用户指定的平台、提交与产物范围必须被遵守，构建和商店发布分开。iOS archive / IPA 同样保留为明确触发的独立步骤。

## CI 可靠性与成本

只授予必要权限（质量校验默认 contents: read）；Action 固定完整 SHA 并标版本。PR 检查不注入签名凭证，不使用高权限 pull_request_target 执行未审查代码。[GitHub 官方说明](https://docs.github.com/en/actions/reference/security/secure-use)

Android 缓存按 OS / JDK / Gradle / 依赖锁区分，iOS 按 macOS / Xcode / Swift / Package.resolved 区分；不缓存凭证或用户数据。Python 缓存按 OS / Python / 依赖文件摘要区分，MySQL 测试实例不跨任务复用。三个工程分别保留失败报告；共享 fixtures 的摘要随报告输出。

同一 PR 取消旧任务，每个 job 有超时。macOS 仅在 iOS、共享契约或后端公开行为影响 iOS 时启动，控制原生双端 CI 成本。工程工具版本明确锁定，避免 runner 升级后静默漂移。

远端接通后建议经 PR 合并到 main，以稳定质量检查作为门槛；人工评审要求按协作人数设置。私有仓库保护能力届时核实，本轮未修改 GitHub 设置。

## Git 与 SSH 后续操作

目前本地已经初始化在 `chore/gy/mobile-planning`，`origin` 使用用户提供的 HTTPS 地址。目标是私有仓库，当前凭据访问返回 `Repository not found`；用户表示稍后补齐 SSH，因此本轮未 push，也没有创建 GitHub 仓库。

配置好 SSH 后，按顺序核查。`ssh -T` 成功认证时 GitHub 也可能返回非零退出码，应查看提示是否为预期账号。

```bash
ssh -T git@github.com
git remote set-url origin git@github.com:gmaicoson-crypto/SoraticMind_App.git
git ls-remote --symref origin HEAD
git fetch origin
git branch -r
```

如果远端已有 README 或提交，先比较历史并选择基于远端分支承接本地文档；不强推、不自动覆盖、不盲目合并无关历史。若远端确实为空，审阅本地文件后可首次提交并推送：

```bash
git add README.md AGENTS.md .gitignore .editorconfig docs
git diff --cached --check
git diff --cached
git commit -m "docs: 初始化移动端开发规划与协作规范"
git push -u origin chore/gy/mobile-planning
```

空远端的首个分支可能成为默认分支；远端接通后再单独建立 / 配置长期主分支，不把规划分支永久当主分支。上述是未来操作说明，本轮未执行 commit 或 push。

分支使用 `<type>/gy/<topic>`，如 `feat/gy/mobile-shell`、`fix/gy/chat-resume`。提交采用英文类型与中文描述，如 `feat: 新增双端登录与会话恢复`。

每个 PR 说明具体行为变化、复用内容、职责拆分与超限说明、格式校验、性能影响、三方影响、契约 / 数据迁移 / 发布顺序、定向测试和未验证事项；不把未执行的检查标为通过。

## 当前已接入的入口与限制

- scripts.quality.changed_files 复用 Git 的 NUL 分隔路径；本地合并索引、工作区及未忽略新文件，PR 用 merge-base，push 用 before / after，初次提交用显式初始范围。不会修改索引。
- scripts.ci.impact 根据 impact-map.json 选择命名测试集合，并沿 depends_on 扩展到消费者；报告保留输入、原因和需独立验证的项目。未知业务文件、未映射的测试 / 改名目标直接失败，需要本次改动补映射。
- 首次固定后端迁入使用已审查的 import-baseline 明列集合。这个特殊集合仅适用于初始范围中的 upstream-manifest 路径；它不代表全部旧功能已覆盖，后续未映射的旧服务修改仍会失败。
- scripts.ci.check_structure 检查相关文本 / JSON / TOML / 文档链接及规模。scripts.ci.run_checks 按平台执行变化文件格式 / lint 和明确测试选择，检查零用例与结果文件；Swift Testing 的独立 XML 报告也验证每个选中的 suite / method。
- Android 执行器先检查 dry-run 图仅包含已登记的纯 JVM network / auth 模块，拒绝打包 / 设备任务；Swift 只使用 MindCore 包。新增模块必须更新执行器和映射，不能通过把任务改成通用 build 绕开限制。
- MySQL job 使用本次 workflow 的临时服务容器与共享 Unix socket，没有映射宿主 TCP 端口；用例创建并删除随机测试库。持久本地服务的进程生命周期仍在本机单独验证，不把服务容器结果当作本地启动器结果。

当前 .github/workflows/quality.yml 有稳定的 quality / summary，始终传播所需任务的失败、异常取消和非预期跳过。纯文档只运行范围 / 结构，不安装三方运行依赖。Actions commit、MySQL 镜像摘要及 Python / JDK / Xcode 选择已固定；CI 不部署、不打包、不自动提交，也不注入模型或签名凭证。[工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)

本地已完成选择器边界测试、语言门禁与执行器接线；actionlint 静态通过。尚未连接私有远端并推送，所以没有 GitHub CI 成功链接。依赖映射目前覆盖迁入基线和已开发网络 / 账号接口 / 会话 / 凭证存储 / 环境核心，不是自动推导所有业务依赖的工具；新增业务或变更公共行为时继续维护精确规则，不能依赖初始集合长期绕过相关测试。

session-android / session-ios 选择会话竞态测试；credential-storage-android / credential-storage-ios 选择同平台存储与会话测试。接口或网络变更沿依赖扩展到这些消费者；单独修改存储不运行另一平台或后端业务。平台适配的设备缺口保留在 manual 输出中，纯 JVM / Swift 包成功不会关闭这些缺口。

auth-form-android / auth-form-ios 已映射可复用表单状态与账号容器的相关核心测试；native-configuration 校验 Debug / Release 网络配置。native-auth-ui-tests 在默认 CI 只校验合成验证码读取器和变化文件；原生 UI 流程保持明确授权后的本地入口，见 [原生账号验证](native-auth-verification.md)。`android/uitests` 独立于应用进程，使杀进程恢复测试可以真正重启 app；iOS 使用独立 XCUITest target。当前未创建或运行远端 native-validation 工作流。

history-provider / history-android / history-ios 映射新的分页契约、双端 API 适配和共享无效响应；history-mysql 选择一次性 MySQL 投影用例。Android 执行器仅新增 core:chat 到 JVM 允许列表，继续先检查任务图并拒绝 app、package 或设备任务。未知 chat 业务文件仍必须补充测试映射。当前 chat.py 同时包含旧流业务，修改此文件会联动原流 / 生命周期消费者；后续按职责拆开后再缩小映射，不能省略受影响检查来减少次数。

三个 JVM 核心 test 任务已将 contracts/fixtures 的 JSON 与 scripts/contracts 的 Python fixture 声明为输入；样例 / 服务脚本变化时不能使用旧的 UP-TO-DATE 测试结果。仍按影响映射传递明确测试类，声明输入不扩大为根 test 或应用打包。
