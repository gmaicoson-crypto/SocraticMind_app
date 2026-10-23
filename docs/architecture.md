# 技术选型与项目结构

决策日期：2026-10-12。用户已确定 Android 使用 Kotlin + Jetpack Compose、iOS 使用 Swift + SwiftUI，双端同步开发；backend 从原项目复用并在本仓库维护，可独立调整。已进入工程实施，完成情况以 [实施状态](execution-status.md) 为准，以下结构包含当前实现及后续规划。

2026-10-22 用户进一步确认当前本地开发、不上线；完整功能范围保留。本文维护技术边界；阶段与功能完成条件见[交付总计划](delivery-plan.md)，部署、安装更新及维护见[交付验收](release-acceptance.md)。

## 已确定的架构方向

一个仓库管理 Android、iOS 两个独立原生应用和 backend 服务。两端各自维护 UI、状态与网络实现，共享后端、接口契约、脱敏样例、功能验收规范和设计资源。初期不增加 Kotlin Multiplatform 或其他跨语言运行时。

原生 UI 有利于直接控制键盘、导航、无障碍和生命周期，也便于按平台测量性能；代价是客户端功能需要两套实现和两端验收。复用发生在同一平台内的组件与基础设施，以及跨平台的规格和数据，Vue / Pinia / DOM 代码不作为可直接运行的原生组件。

后端统一负责账号、AI 调用、主题图谱、计划、评估、掌握规则、学习记忆、对话持久化和附件解析。客户端不复制数据库迁移、模型编排或掌握判定算法。

## 后端技术与维护方案

backend 以原仓库 `master` 的固定提交 `4a20228e630168113e9e09a66de83699545fa82c` 为初始来源。迁入后，本仓库是移动项目后端的维护主源；原仓库作为上游参考，后续允许业务、接口和存储结构分化。不要求两个仓库内容永久一致，也不自动同步代码。

| 层次 | 延续方案 | 维护边界 |
| --- | --- | --- |
| API / 数据校验 | Python、FastAPI、Pydantic | 保留既有路由 / schema 职责；公开协议变更联动双端 |
| 业务 / AI | services、agent 状态机、OpenAI 兼容调用、提示词 | 学习规则和幂等机制留在服务端，不在手机重复实现 |
| 数据库 | SQLAlchemy、MySQL、Alembic | 本仓库维护迁移链；版本和依赖在 M1 验证并锁定 |
| 附件 | 现有存储、解析、worker 与能力检查 | 原件、派生内容和任务状态同属本后端；运行环境需另行验证 |
| 质量工具 | Ruff、pytest、HTTPX / TestClient | 复用已有测试；仅执行修改与关联用例 |
| 配置 | 复用配置结构与脱敏 env 示例 | 独立开发 / 测试 / 生产配置；不携带原项目密钥或数据库 |

先保留上游目录和已有业务边界，避免迁入时同时大规模重构。新增能力优先扩展已有 services、schemas、routers；出现真实职责冲突时再拆模块。优点是便于核对来源与定位回归，代价是短期沿用部分上游结构和依赖，需要逐项清理而非整体重写。

本次迁入包括后端代码、关联测试、完整 Alembic 历史、必要提示词 / 资源、依赖文件、许可证和所依赖的根级工具配置；在 `backend/UPSTREAM.md` 记录源地址 / SHA / 路径映射 / 本地差异，原始许可证保存为 `backend/LICENSE.upstream`。后端和来源记录已迁入；细节见实际文件。上游根 pyproject 的 Ruff 配置要显式迁入或合并，不能只复制目录后假设配置仍有效。

本仓库 backend 默认使用独立数据库、附件卷和部署配置。复用源代码不等于共享原产品账号或学习数据；如以后要迁移旧数据或接入原 Web，必须单独设计数据迁移和兼容方案。两份可分化的迁移链不能在未协调时共同管理同一个数据库。

格式、文件规模与迁入基线统一遵循 [代码质量规则](code-quality.md)；聊天、Agent、附件等具体拆分见 [核心模块规划](core-modules.md)。首次迁入不强行把全部历史大文件拆到上限以内。

## Android 技术方案

| 层次 | 规划选型 | 目的与取舍 |
| --- | --- | --- |
| 界面 | Kotlin、Jetpack Compose、Material 3 | 原生声明式界面；品牌颜色和间距从源设计提炼 |
| 导航 | 单 Activity、Navigation Compose | 页面栈和参数显式定义，不自研路由框架 |
| 状态 | ViewModel、Coroutines、StateFlow、单向数据流 | 不可变 UiState 与事件分离，按生命周期收集 |
| 数据层 | Repository + DTO / Domain model 映射 | 页面不直接访问网络，协议变化集中处理 |
| REST / SSE | 已采用 OkHttp、kotlinx.serialization 与独立 SSE 解码；暂未引入 Retrofit | 同一个传输供账号 / 历史复用，流按块读取；每个领域适配器声明字段 |
| 依赖组装 | 构造器注入、AppContainer | 测试可替换 repository；初期不添加 DI 编译插件 |
| 本地数据 | DataStore 存偏好；Room 存结构化缓存 / 草稿；私有文件目录存附件 | Room 在需要查询时引入；区分持久数据和可清理缓存 |
| 凭证 | Keystore 管理密钥，AES-GCM 加密 Token 后存应用私有空间 | Keystore 不是任意字符串仓库；处理密钥失效和备份恢复 |
| 文件 / 图片 | 系统 Photo Picker / 文件选择器、ContentResolver | 使用 URI 流；图片缓存库在头像阶段评估 |
| 工具 / 测试 | Gradle Kotlin DSL、Version Catalog、ktlint、Android Lint、JUnit、coroutines-test、MockWebServer | 固定兼容版本，按模块和测试类定向验证 |

Repository、ViewModel、单向数据流参考 [Android 架构建议](https://developer.android.com/topic/architecture/recommendations)。Keystore 管理密码学密钥，凭证通过受其保护的加密存储保存。[Keystore 文档](https://developer.android.com/privacy-and-security/keystore)

## iOS 技术方案

| 层次 | 规划选型 | 目的与取舍 |
| --- | --- | --- |
| 界面 | Swift、SwiftUI | 原生视图；少数系统能力通过薄封装接入 UIKit |
| 导航 | NavigationStack、TabView、类型化路由状态 | App 组合页面，功能视图不操纵全局导航单例 |
| 状态 | 主线程隔离的 presentation model、Swift Concurrency；Observation 优先 | UI 状态由 MainActor 管理；网络和解析不占主线程；Observation 需 iOS 17+ |
| 数据层 | Repository protocol、Codable DTO、领域模型 | 与 Android 使用同一后端语义，不强求两端类结构逐行相同 |
| REST / SSE | URLSession、async/await、bytes(for:)、独立 SSE 解析器 | 构造带 JSON 请求体和鉴权头的 URLRequest，不能依赖仅 GET 的流封装 |
| 依赖组装 | 构造器注入、AppContainer | 显式作用域与 mock，不引入大型状态框架 |
| 本地数据 | UserDefaults 存偏好；Core Data 存结构化缓存 / 草稿；沙盒文件存附件 | 按需求引入持久层，存储模型不直接充当 DTO |
| 凭证 | Keychain | 根据使用场景选择可访问性；退出和注销显式删除 |
| 文件 / 图片 | PhotosPicker、fileImporter、系统分享、Quick Look | 处理 security-scoped URL、权限失败、临时文件清理 |
| 工具 / 测试 | Xcode、Swift Package Manager、SwiftFormat、SwiftLint；Swift Testing、必要的 XCTest / XCUITest | 纯逻辑包主机测试，应用 UI 另做模拟器和设备验证 |

参考 [SwiftUI 模型数据管理](https://developer.apple.com/documentation/swiftui/managing-model-data-in-your-app) 和 [URLSession](https://developer.apple.com/documentation/foundation/urlsession)。

已确认最低 Android 8.0（minSdk 26）、iOS 17，开发标识 com.gmaicoson.socraticmind。采用 Observation；targetSdk、工具链与依赖在 M1 核实并固定。真实设备范围仍待验证。

## 仓库与模块结构

以下为目标目录，已实现部分以仓库和实施状态为准。只建立能隔离平台依赖或确有复用价值的模块；feature 初期按目录组织，规模增长后再模块化。

当前 Android 已有纯 JVM core:network、core:auth、core:chat；iOS 对应 MindCore/Networking、Authentication、Chat。下面的 model / data / designsystem 仍是可按实际复用拆分的目标位置，未为目录完整性创建空模块。历史接口与拆分证据见[会话读取核心](chat-history-implementation.md)。

```text
SoraticMind_app/
├── android/
│   ├── app/                       # Application、Activity、导航、依赖组装
│   │   └── src/main/.../feature/   # screen、ViewModel、局部组件
│   ├── core/
│   │   ├── model/                 # 纯 Kotlin/JVM 模型、repository 接口
│   │   ├── network/               # Kotlin/JVM DTO、REST、SSE、API 实现
│   │   ├── data/                  # Android repository、Room、凭证、文件
│   │   └── designsystem/          # Compose 主题和跨功能组件
│   ├── gradle/libs.versions.toml
│   ├── gradle/wrapper/
│   └── settings.gradle.kts
├── ios/
│   ├── SocraticMind.xcodeproj/     # App target、共享 scheme、测试计划
│   ├── SocraticMind/
│   │   ├── App/                   # 入口、路由、依赖组装
│   │   ├── Features/              # screen、presentation model、局部组件
│   │   ├── DesignSystem/          # SwiftUI 主题和跨功能组件
│   │   └── Platform/              # Keychain、Core Data、文件、生命周期
│   ├── Packages/MindCore/         # 本地 Swift 包，无 UIKit / SwiftUI 依赖
│   │   ├── Sources/              # Models、Repositories、Networking、SSE
│   │   └── Tests/                # Swift Testing、共享样例加载
│   ├── SocraticMindTests/
│   └── SocraticMindUITests/
├── backend/                      # 从上游固定版本迁入，在本仓库维护
│   ├── main.py                   # FastAPI 入口与生命周期
│   ├── core/                     # 配置、认证、数据库、公共能力
│   ├── routers/                  # API 路由
│   ├── schemas/                  # 请求 / 响应与结构化模型
│   ├── models/                   # SQLAlchemy 模型
│   ├── services/                 # 学习、聊天、附件等业务服务
│   ├── ai/                       # 模型调用与提示词
│   ├── alembic/versions/          # 保留上游历史，追加本地迁移
│   ├── tests/                    # 复用的测试与后续定向回归
│   ├── scripts/                  # 运行诊断等后端工具
│   ├── requirements.txt          # M1 核实兼容性后固定依赖
│   ├── requirements-dev.txt
│   ├── .env.example              # 无真实凭据的配置示例
│   ├── UPSTREAM.md               # 来源、迁入范围、本地差异记录
│   └── LICENSE.upstream          # 保留上游许可证和版权声明
├── contracts/
│   ├── openapi/                  # 脱敏快照、来源版本与兼容说明
│   ├── sse/                      # 事件规范、分片、错误、取消与终态样例
│   └── fixtures/                 # 两种语言使用相同输入和期望输出
├── design/                       # 色彩、间距、图标源、交互规范
├── docs/
│   └── releases/                 # 未来各内测版本的脱敏验收、兼容与交接记录
├── ops/                          # 后续部署清单、配置模板、备份恢复入口；不含真实凭据
├── scripts/
│   ├── ci/                      # 差异检测和影响范围工具，M1 再实现
│   └── quality/                 # 格式调度、规模 / 依赖检查，M1 再实现
└── .github/workflows/            # M1 再启用质量校验，打包单独手动触发
```

两端功能目录对应：Auth、Learning、Onboarding、Plans、Chat、Assessments、Memories、Attachments、Notes、Progress、Profile；Android 使用小写包名。

Android 由 app 组装 core:data 与 core:designsystem；data 依赖 network / model，network 依赖 model，designsystem 不依赖 network，model 不依赖 Android UI。iOS 为 `App / Features → MindCore 接口`，Platform 实现由 App 注入。跨功能通过 repository 或显式回调协作，不读取其他功能的私有状态。

domain use case 只在跨 repository 编排或多处复用时新增。页面区分 UI、状态编排和数据访问，不机械增加转发层。共享基础模块会扩大相关测试范围，这是复用的验证成本。

核心拆分先在文件 / 目录层完成，出现复用或编译隔离需求再增加模块。文件行数以 [质量文档](code-quality.md) 为唯一数值来源；即使未超限，混合职责和循环依赖仍需处理。拆分不应增加重复网络请求、数据库事务或多个消息状态来源。

## 复用边界与组件设计

| 内容 | 跨端复用 | 平台内复用 |
| --- | --- | --- |
| 后端与协议 | FastAPI、OpenAPI、错误码、SSE 事件与恢复规则 | 集中封装 HTTP、认证和错误处理 |
| 测试 | 相同 JSON / SSE fixtures 与期望状态 | Kotlin、Swift 分别实现解析与契约测试 |
| UI / 设计 | 品牌资源、文案、交互语义、设计 token | 两端各自提供 MessageItem、MarkdownContent、AttachmentCard、SourceReference |
| 学习流程 | 服务端 Agent run、评估和计划契约 | 各端复用 AgentStep、PlanPreview、AssessmentResult |
| 平台能力 | 行为规范，不共享语言实现 | CredentialStore、DraftStore、FileGateway、Clock、生命周期接口可替换 |

普通聊天与节点聊天在各端共用消息列表和输入组件，模式通过参数表达。基础组件先检查系统组件和本平台已有实现；组件不内置全局账号、请求或数据库。

Vue、Pinia、marked / DOMPurify、Three.js、HTML Canvas 仅作行为参考，不迁入原生运行路径。Markdown 已选固定 CommonMark Java / Swift Markdown，投影为纯核心模型，再交给 Compose / SwiftUI；不执行 HTML / 脚本，外链限制协议。支持范围、解析预算、账号缓存与尚未验证的宿主行为见[消息展示](message-rendering.md)，不把主机核心通过等同于完整 Web 语法或设备渲染验收。

## 图谱、笔记与移动交互

图谱首选原生 2D Canvas / Path：复用节点、边、状态与后端坐标语义，先实现平移、缩放、选中和详情，提供可访问的节点列表。3D 视觉与动效不作为首个闭环要求；若需完全还原 Three.js 效果，单独评估，不默认内嵌网页。缓存布局结果，拖拽时不重算全部节点。

主导航建议「学习 / 对话 / 我的」。学习进入计划、主题、图谱；节点对话复用 Chat；笔记从学习或对话进入。平板后续通过相同状态层扩为双栏。

- Android 处理返回键、进程重建、IME inset 与生命周期收集；iOS 处理返回手势、scenePhase、键盘、安全区和 Dynamic Type。无障碍状态不用颜色单独表达。
- 异步加载凭证后再决定认证路由。失效时重新登录，保留合适的非敏感草稿；当前后端没有已确认的 refresh 契约。
- 笔记、草稿和缓存按用户 / 主题隔离，有版本迁移策略。退出 / 注销清理对应数据，必要时先允许导出；双端本地数据库不必具有相同 schema。
- 笔记首期为本地 Markdown 编辑 / 预览与系统分享，画布分别原生实现。跨端笔记同步需新增后端契约，不能把账号共用等同于笔记已经同步。
- 服务端是学习和会话状态的权威来源。离线可查看有标记的缓存和编辑草稿，AI、评估及掌握提交不做隐式离线重放。

## SSE 与请求恢复

1. 原生 HTTP 发起带 Bearer 和 JSON 请求体的 `POST /api/chat/stream`；登录仍按现有 OAuth2 表单字段提交，不改成未经确认的 JSON 登录。
2. 发起前持久化 request_id、session_id 等恢复标识；两端遵循同一幂等语义，网络层不自动重发非幂等生成请求。
3. Kotlin / Swift 分别增量解码 UTF-8 和 SSE，覆盖跨字节中文、CRLF、空行、错误、结束标记、来源事件和未知扩展字段。解析离开主线程，合并 UI 更新。
4. 不承诺后台持续生成或收流。回前台先查状态，再读历史正文，按消息 ID 去重；处理中有限退避查询，失败提供显式重试入口。
5. 用户停止时调用服务端取消接口；关闭本地连接不等于服务端停止。取消调用失败保留待确认状态，恢复网络后核实。
6. 杀进程后依据持久标识恢复；重新生成使用 regenerate 契约，不与原请求重放混用。现有接口没有已确认的逐 token 断点续传。

## 性能与工具链基线

以下为待实测初始目标，不是已达到指标。M1 固定中档 Android 和支持范围内的较旧 iPhone，记录系统、刷新率、构建模式和样例。

| 场景 | 策略 | 初始验证目标 |
| --- | --- | --- |
| 500 条历史、20 KB 流消息 | LazyColumn / SwiftUI 懒加载容器、稳定 ID、分页、50—100 ms 批量刷新活动消息 | 输入与滚动可操作，不反复解析整个列表 |
| Markdown | 非主线程解析、稳定内容缓存、按需代码高亮 | 无持续主线程卡顿，用 Android tracing / Instruments 定位 |
| 100 / 300 节点图谱 | 缓存布局、视口裁剪、后台停绘 | 100 节点主场景目标接近 60 fps；300 节点测上限与降级 |
| 冷启动 | 最小初始化、延迟打开数据库和重型编辑器 | 固定设备本地首屏可交互目标 2 秒内，不计 AI 等待 |
| 生命周期 / 附件 | 20 次进出页面观察内存；流式文件 IO、限并发、图片下采样 | 无持续内存增长，不保留多份大文件 |

Android 记录 JDK / Gradle / AGP / Kotlin / Compose / SDK 兼容矩阵，提交 Wrapper、Version Catalog、依赖锁与校验元数据；iOS 固定 Xcode / Swift / SDK，提交共享 scheme、测试计划和 Package.resolved。具体版本在 M1 核实后锁定，结果记录到工具链清单。

## 后端演进、迁移与联调

客户端和后端可以在同一个 PR 调整，但后端与 App 分别部署和发布。笔记同步、refresh token、推送登记后续可在本仓库 backend 扩展，仍是新增功能，不在本轮实现。不承诺永久兼容原仓库 Web；若将来接入原 Web，再明确支持范围。需要兼容的是本项目支持期内已发布的 Android / iOS 客户端。

后端路由、响应 schema 与服务实际行为是 API 的事实来源，contracts 保存可审阅的快照和双方约定。接口修改同时更新后端测试、相关契约与客户端消费方；CI 重新导出 OpenAPI 检查漂移，SSE 事件和错误行为另有样例 / 测试。不能只改快照文件就视为完成接口修改。

Alembic 历史在迁入时完整保留，已有 revision 不重写；本地 schema 变化追加 revision 并检查单一有效 head。对变化迁移验证空库完整升级和支持的前一版本升级，数据库使用一次性 MySQL。源码分化后，不直接套用上游新增 migration，需检查本地模型与 revision 冲突并调整。

生产迁移与部署是独立操作：采用先扩展字段 / 双版本兼容、再切换客户端、最后移除旧结构的策略；准备备份、数据校验和失败恢复步骤。删除列或不可逆变更不能假设执行 downgrade 就能恢复数据。普通 PR CI 只改隔离测试库，不连接生产库。

M1 从迁入的 backend 归档脱敏 OpenAPI 和 SSE 样例，记录本地服务版本、源 SHA、字段可空性、错误结构、时区和分页规则。REST 可评估生成 DTO，SSE 语义另写契约。客户端版本更新不能要求两端与后端永远同时上线。

原生 HTTP 不受浏览器 CORS 机制约束，无需为 App 增加 WebView Origin；迁入时保留原有 CORS 能力，允许来源按本项目环境配置。联调验证 HTTPS / ATS / Android 网络安全配置、SSE 代理缓冲和超时、附件大小、授权下载、跨端并发及错误码。M1 规划本地 backend + 独立测试数据库联调入口；已迁入服务并完成隔离 MySQL 启动验证；持久本地联调入口在 M1-06 完成。

客户端配置仅包含公开环境和 API base，数据库与服务端模型密钥不下发。用户自定义模型密钥只按后端契约提交，不进入本地持久缓存或日志。
