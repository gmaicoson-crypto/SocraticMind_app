# 源项目事实与复用清单

调研日期：2026-10-12（America/Los_Angeles）。本轮只读调研源代码，没有运行源服务、调用真实模型、访问业务数据库或修改源仓库。

当前客户端路线已确定为 Kotlin + Jetpack Compose 与 Swift + SwiftUI。下表保留源项目事实。后端代码计划迁入本仓库 backend 并独立维护；协议、规格和测试场景作为迁入基线，原生 UI 与客户端状态分别实现。本轮未实际复制后端。

## 参考基线

- 仓库：[gmaicoson-crypto/SocraticMind](https://github.com/gmaicoson-crypto/SocraticMind)。
- 默认分支：`master`，固定提交：`4a20228e630168113e9e09a66de83699545fa82c`。
- 提交标题：`feat(dialogue): 接入附件标题与上下文建议并完善失败恢复`。
- 同时存在 `main` 分支，调研时为 `3bdd876a836f30ccddb26f4b0f0826027cbbe1db`；不能默认它与 `master` 相同。
- 调研通过 Git 获取成功；公开网页访问返回 404，不代表 Git 中不存在该仓库。
- `LICENSE` 为 MIT，版权声明为 `Copyright (c) 2026 gmaicoson-crypto`。后续迁入代码时保留许可证及来源；本轮未复制业务代码，也未替新项目指定许可证。

下面链接均固定到参考提交，防止上游变更使结论失去对应依据。

## 证据、结论与实施方向

| 证据 | 已核实结论 | 移动端实施方向 |
| --- | --- | --- |
| [frontend/package.json](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/package.json) | Vue 3、TypeScript、Vite、Pinia、Vue Router、Axios、Three.js，测试使用 Vitest / Vue Test Utils | 将类型与状态语义转为 Kotlin / Swift 模型，复用测试场景；不迁入 TS 运行时代码 |
| [backend/main.py](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/backend/main.py) 与 [backend/README.md](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/backend/README.md) | FastAPI API、SQLAlchemy / Alembic、服务端 AI 编排 | 迁入本仓库 backend，由两端 App 使用；迁移和模型调用由这里维护，不默认与原 Web 共用部署 |
| [api/chat.ts](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/api/chat.ts) | 使用 POST + Bearer + fetch 读取 SSE，不是简单 GET EventSource | 提取事件契约与样例；Kotlin / Swift 分别实现原生流解析、取消与恢复 |
| [routers/chat.py](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/backend/routers/chat.py) | 存在请求状态、取消和历史消息接口 | 以 request_id、服务端状态和历史记录恢复；不承诺逐 token 断点续传 |
| [api/index.ts](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/api/index.ts) 与 [utils/token.ts](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/utils/token.ts) | Token 存 localStorage / sessionStorage；401 使用 window.location 跳转 | 改为安全存储接口、会话状态和路由事件；不可原样迁入 |
| [routers/auth.py](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/backend/routers/auth.py) | 登录使用 OAuth2 表单，邮箱传 username；未发现 refresh 路由 | 首版过期后重新登录，保留非敏感草稿；不虚构自动续期 |
| [KnowledgeGraph.vue](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/components/KnowledgeGraph.vue) | 当前主图谱渲染组件是 ThreeGraphCanvas；README 仍写 Vue Flow / Dagre | 复用图谱数据与状态；两端采用原生 2D 渲染，不直接迁入 Three.js |
| [MarkdownEditor.vue](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/components/notes/MarkdownEditor.vue) | 笔记存 `sm_markdown_content` 本地键，使用浏览器下载 | App 需要账号隔离的存储与原生分享；跨端同步是新增后端需求 |
| [CanvasSketch.vue](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/frontend/src/components/notes/CanvasSketch.vue) | HTML Canvas 绘图，使用链接下载 PNG | 参考工具与交互语义，两端分别实现原生绘制、触控和导出 |
| [.github/workflows/ci.yml](https://github.com/gmaicoson-crypto/SocraticMind/blob/4a20228e630168113e9e09a66de83699545fa82c/.github/workflows/ci.yml) | 已有 PR 差异检测、增量格式检查、固定学习流程测试和 Web build | 复用差异检测思路，升级为受影响模块映射；适配后端 Ruff / pytest 和迁移验证，不添加自动 APK 构建 |

## 功能迁移矩阵

“阶段”只表示顺序，不表示永久删除后续功能。每个阶段都覆盖 Android / iOS。

| 功能 | 复用的协议 / 规格 | 原生端实现 | 计划阶段 |
| --- | --- | --- | --- |
| 登录、注册、验证码、找回密码 | auth API、校验语义 | 软键盘、安全存储、会话失效 | M2 |
| 新主题目标、诊断、计划预览 | agent API、run 状态、结构化类型 | 分步全屏流程、离开后恢复 | M3 |
| 今日计划、重排、主题管理 | plans / topic API 与状态语义 | 列表、时区、底部导航 | M3 |
| 知识图谱与节点状态 | 节点数据、图例、服务端解锁规则 | 手势、节点详情、列表替代视图 | M3 |
| 普通 / 苏格拉底聊天、风格、建议 | chat API、消息结构、Markdown 格式与展示规则 | 长列表、键盘、流式增量刷新 | M2—M3 |
| 请求恢复、停止、重新生成、历史标题 | request_id、状态查询、取消与标题 API | 前后台切换、弱网、重进程恢复 | M2—M3 |
| 联网引用 | web 事件、来源类型与展示语义 | 可点击引用、外链打开；沿用服务端自动策略 | M3 |
| 图片 / Word / PDF / PPT 附件 | 附件 API、解析状态、引用 | 系统文件选择、上传进度、权限失败、预览 | M4 |
| 评估、掌握 / 撤销、学习记忆 | 评估与记忆 API、状态和测试 | 小屏表单、恢复与操作反馈 | M3 |
| 打卡、统计、热力图、成就 | progress API、统计定义和测试场景 | 小屏布局、动画降级、时区边界 | M4 |
| 个人资料、头像、模型配置、注销 | user / llm API | 系统图片选择、确认操作、清理本地数据 | M2—M4 |
| Markdown 笔记、画布 | Markdown 文本格式、编辑 / 绘制交互规格 | 本地持久化、账号隔离、系统分享 | M4 |
| 深浅主题与品牌 | 品牌色彩 / 间距规格、图标和资源 | 系统主题、字号、无障碍、双端安全区 | M1—M4 |

## 基线 API 对接约束

以下是源提交的已知契约，迁入初期沿用；后续由本仓库 backend 与 contracts 共同记录变化，不要求永久与上游一致。

1. 新主题入口为 `POST /api/agent/onboarding`。旧 `POST /api/topics/generate` 已废弃，不作为新客户端入口。
2. Agent run 的回答、确认、重试、取消和版本处理沿用现有契约；掌握状态由服务端计算。
3. Chat 创建请求携带稳定的 `request_id`，历史由服务端管理，客户端不拼接整段历史上传。
4. `GET /api/chat/requests/{request_id}` 查询状态，消息正文从历史接口取得。不能把它当成可恢复字节偏移的流端点。
5. 断网、进后台与用户点击“停止”语义不同；停止同时调用服务端取消接口，网络断开先做状态恢复，不能立即重复生成。
6. 附件范围、大小、类型、解析能力以 capabilities 和后端错误为准。移动端不解析 Office，也不把附件暴露到公开目录。
7. 现有历史支持 `limit/offset`，没有证据证明支持游标分页；客户端先适配真实接口，再单独提后端改进。
8. 模型密钥与 AI 供应商调用留在服务端。用户自定义密钥通过既有后端模型配置接口提交，不写入日志或本地持久缓存。

## 复用方法

建立来源清单，记录源 SHA、对应接口 / 行为、目标 backend / Kotlin / Swift 路径、转换理由和关联测试。先按清单迁入后端基线并核对相关测试 / 迁移，再从本仓库后端归档 API / SSE 契约和脱敏样例，分别实现 DTO、网络、状态与原生组件。复用算法思想时验证输入输出和边界条件，不假设 TS 代码能够跨语言直接复用。

后端按固定提交迁入，在本仓库常规维护，不使用 Git 子模块或上游目录的运行时链接。保留来源与许可证，记录后续修复引入或拒绝的理由；不自动覆盖本地差异。contracts 统一维护后端提供方与 Android / iOS 消费者的样例和验收语义。初期不引入跨语言共享框架，成本是三方需持续做契约一致性验证。

后续迁入清单：backend 运行代码、完整 Alembic 历史、pytest 与 fixtures、提示词 / 必要资源、运行诊断脚本、依赖与脱敏配置示例。还需核实后端依赖的根级 pyproject / 工具配置和相对路径；不迁入 Web 前端、.env、虚拟环境、数据库快照、上传附件或真实账号数据。

新增核查证据：源 `backend/requirements-dev.txt` 提供 Ruff，格式配置在仓库根 `pyproject.toml`；`backend/tests/conftest.py` 和 `backend/tests/p0/test_migrations.py` 使用 SQLite。由此确定：工具配置需随迁入承接，SQLite 测试不能作为 MySQL 行为的全部验收。相关数据库变更的 MySQL 校验见 [CI 方案](ci-and-collaboration.md)。

同一源提交的物理行数抽查发现 routers/chat.py 为 1,275 行、services/chat_lifecycle.py 为 864 行、services/agent/orchestrator.py 为 856 行。迁入时保留来源并登记格式规范化后的规模基线，后续分职责减少，不能直接把新文件限制强加到整批旧代码。规则见 [代码质量规划](code-quality.md)，拆分步骤见 [核心模块规划](core-modules.md)。
