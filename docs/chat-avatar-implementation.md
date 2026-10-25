# 会话头像

更新：2026-10-25。当前完成双端头像传输、资源校验与本地选择记录的核心实现。头像选择状态、系统图片选择器、缩略图、页面和应用容器尚未接入；本批不代表头像功能或 P02 验收完成。

## 复用与职责

固定参考版本 `4a20228e630168113e9e09a66de83699545fa82c` 已提供会话头像上传 / 清除、每模式 6 个 AI 预设及客户端本地选择记录。本批复用本仓库 backend 的对应路由和已迁入的资源，没有修改后端生产代码、依赖、数据库迁移或 OpenAPI。

| 职责 | 实现 | 复用与取舍 |
| --- | --- | --- |
| 有限网络请求 | HTTPTransport 与 MultipartUpload | 复用连接、错误和取消处理；上传增加一个受限文件体，不另建头像网络客户端 |
| 头像协议 | ChatAvatarApi / ChatAvatarAPI | 上传 / 清除使用现有鉴权 API，读取使用同服务公开资源路径；不管理页面或账号凭证 |
| 资源与选择 | ChatAvatarModels | 验证预设及上传路径、所属账号和会话；Swift 对会话 ID 使用 UTF-8 字节键 |
| 本地选择记录 | FileChatAvatarStore | 每账号 / 服务地址隔离，原子写入，比较旧值后更新；不保存图片、令牌或聊天正文 |
| 文件 IO | AccountFileStorage | 从已有 FileChatTurnJournal 提取有界读写；两类记录各自保留序列化、锁及冲突规则 |

共享文件 IO 减少重复的临时文件、同步和读回校验代码；代价是修改时必须同时验证头像与聊天恢复。已有恢复记录仍使用原路径、4096 字节上限及 schema 1 / 2，新增头像记录使用独立命名空间，不重写现有恢复文件。

## 上传与读取边界

- 上传为 POST `/api/chat/avatar`，字段为 UTF-8 session_id 与单个 file；清除为 DELETE 同一路径，JSON 中保留完整 session_id。清除返回非负数量，重复清除允许返回 0。
- 复用后端 5 MiB 图片大小限制，支持 PNG、JPEG、GIF、WebP。MultipartUpload 保存参数快照；文件名由适配器固定为 avatar 加格式后缀，不上传原文件名。字段名称、文件名与 MIME 不允许注入头部语法。
- 通用上传体限制为一个文件、最多 16 个小文本字段，字段正文合计最多 16 KiB；JSON、表单和 multipart 互斥，GET 不接受这些请求体。
- 返回的上传路径必须符合后端生成规则，且账号 ID 与会话 ID 的 UTF-8 SHA-256 前 24 位匹配。拒绝外部 URL、路径穿越、未知预设和不属于当前上传目标的结果。
- 图片读取只解析同一配置服务的受控路径，最多读取 5 MiB，要求非空及允许的图片 MIME；拒绝重定向。公开头像请求不携带 Bearer 或 Cookie，和现有后端公开静态资源语义一致，不声称图片具有鉴权保护。
- 已知 Content-Length 超限时提前失败；缺失长度的流仍逐块检查实际字节数。取消读取会关闭请求；有限请求继续使用原有 30 秒配置。
- 上传不增加自动重试或后台补发。测试覆盖服务端读完请求后断开连接的单次发送，但不保证服务端未执行失败请求，也不提供跨设备恰好一次写入。

本层验证类型、路径和字节预算，不进行图片解码或像素数量校验。后续选择器需验证真实图片、处理系统格式并有界生成缩略图；不能把 MIME 合法等同于可渲染图片。

## 恢复头像选择

头像选择使用 schema 1，记录 owner_id 和由 session_id / path 组成的列表。每个账号最多 1000 条记录、序列化文件最多 512 KiB；超限直接失败，不静默丢弃已有选择。空缺选择由上层使用对应模式的默认头像。

会话 ID 保持原始 UTF-8 字节，不按视觉相似性合并。例如 `café` 与 `cafe\u0301` 在 Swift 的 String 相等比较中可相等，在后端哈希中却不同。Swift 的 ChatAvatarChoices 用 Data 键查询；持久文件使用记录列表，避免 JSON 对象解码时先合并键。两端拒绝重复 ID、未知 schema、账号不符、非法路径及过大 / 损坏记录，修改失败不会用空数据覆盖损坏文件。

replace 操作在同一 repository 的锁 / actor 内核对 expected 旧选择，再写入新值或移除；两个竞争调用只有匹配旧值者成功。该比较不是登录 revision、跨进程锁或服务端事务。后续头像状态仍需按账号 revision 隔离任务，并处理上传已经成功但本地保存失败、上传响应丢失和旧图片清理失败。

每个服务地址保持一个应用级 store 实例，宿主需传入私有且排除备份的目录。Android 沿用 noBackupFilesDir 的接线约定；iOS 写入辅助保留排除备份和首次解锁后的文件保护设置，但本批未接入头像宿主实例或验证设备行为。clear 只清理指定账号的头像选择；退出 / 重登保留策略、会话删除联动和账号删除清理在状态接线阶段完成。

## 定向证据与剩余工作

共享样例 `contracts/fixtures/chat-avatar.json` 使用合成账号、特殊字符会话 ID 和生成的 1 像素 PNG。双端 API 测试覆盖 multipart 的 Unicode / 二进制 / 参数快照、所属目标、错误、MIME、大小、取消和不重放；存储测试覆盖重启、账号 / 地址 / 命名空间隔离、比较更新、容量、损坏记录、IO 失败及 Unicode ID。

后端新增两项契约将相同样例与真实路由、公开静态资源和预设目录对照。调用路径为 Native API → 回环 HTTP fixture，以及 FastAPI 路由 → 隔离文件目录；本地存储测试直接使用临时目录。它们支持核心协议和持久性结论，不支持相册选择、图片显示或真实生命周期结论。完整结果及本机日志位置见[实施状态](execution-status.md)。

复现提供方：在 backend 目录运行 `../.venv/bin/python -m pytest tests/contracts/test_chat_avatar_contract.py tests/p0/test_chat_avatars.py tests/p0/test_avatar_presets.py::test_preset_paths_match_public_assets`。Swift 核心在仓库根目录运行 `swift test --package-path ios/Packages/MindCore --force-resolved-versions --filter 'ChatAvatarAPIContractTests|FileChatAvatarStoreTests|FileChatTurnJournalTests'`。Android 通过既有 `scripts.ci.run_checks.android_tests` 明确选择同名 API / 存储 / 恢复 JVM 类，执行器先校验任务图。

增量映射登记头像提供方、共享样例、模型、接口、存储与公共文件 IO；公共传输和原子 IO 的变化扩展到实际消费者。test_impact.py 728 行达到测试预警，仍聚焦显式影响图和执行器边界，低于 800 行硬上限；未增加例外或提高上限，后续独立规则应按职责分组维护。

下一步接入头像选择状态、预设 / 上传 / 恢复默认操作、同平台图片组件与系统选择器，并验证账号切换和未确认写入。之后在独立获准构建时完成双端图片、权限、键盘、前后台和最低系统验收。P02、M2 与成品目标均未完成。
