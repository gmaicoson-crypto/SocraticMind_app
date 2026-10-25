# 会话头像

更新：2026-10-25。双端头像传输、本地选择、状态与删除联动已通过核心验证；本批加入有界图片加载、系统照片选择及原生页面接线。Swift ImageIO 在 macOS 主机完成真实格式处理验证，Android 解码与双端选择器 / 页面仍未编译或上机；头像功能与 P02 未完成验收。

## 复用与职责

固定参考版本 `4a20228e630168113e9e09a66de83699545fa82c` 已提供会话头像上传 / 清除、每模式 6 个 AI 预设及客户端本地选择记录。本批复用本仓库 backend 的对应路由和已迁入的资源，没有修改后端生产代码、依赖、数据库迁移或 OpenAPI。

| 职责 | 实现 | 复用与取舍 |
| --- | --- | --- |
| 有限网络请求 | HTTPTransport 与 MultipartUpload | 复用连接、错误和取消处理；上传增加一个受限文件体，不另建头像网络客户端 |
| 头像协议 | ChatAvatarApi / ChatAvatarAPI | 上传 / 清除使用现有鉴权 API，读取使用同服务公开资源路径；不管理页面或账号凭证 |
| 资源与选择 | ChatAvatarModels | 验证预设及上传路径、所属账号和会话；Swift 对会话 ID 使用 UTF-8 字节键 |
| 本地选择记录 | FileChatAvatarStore | 每账号 / 服务地址隔离，原子写入，比较旧值后更新；不保存图片、令牌或聊天正文 |
| 选择状态 | ChatAvatarController / ChatAvatarModel | 复用账号 revision、历史目标及发送协调器的修改占用，管理保存失败与迟到结果；不复制历史状态 |
| 文件 IO | AccountFileStorage | 从已有 FileChatTurnJournal 提取有界读写；两类记录各自保留序列化、锁及冲突规则 |
| 图片工作 | AvatarImageLoader / AvatarImagePolicy / AvatarImageCodec | 复用头像网关及平台解码能力，统一预算、共享请求与缓存；解码和文件读取离开 UI 线程 |
| 原生呈现 | AvatarImage / AvatarImageView 与 ChatAvatarControls | 列表、会话头、AI 消息及选择器复用同平台组件；页面不直接下载或保存凭证 |

共享文件 IO 减少重复的临时文件、同步和读回校验代码；代价是修改时必须同时验证头像与聊天恢复。已有恢复记录仍使用原路径、4096 字节上限及 schema 1 / 2，新增头像记录使用独立命名空间，不重写现有恢复文件。

## 上传与读取边界

- 上传为 POST `/api/chat/avatar`，字段为 UTF-8 session_id 与单个 file；清除为 DELETE 同一路径，JSON 中保留完整 session_id。清除返回非负数量，重复清除允许返回 0。
- 复用后端 5 MiB 图片大小限制，支持 PNG、JPEG、GIF、WebP。MultipartUpload 保存参数快照；文件名由适配器固定为 avatar 加格式后缀，不上传原文件名。字段名称、文件名与 MIME 不允许注入头部语法。
- 通用上传体限制为一个文件、最多 16 个小文本字段，字段正文合计最多 16 KiB；JSON、表单和 multipart 互斥，GET 不接受这些请求体。
- 返回的上传路径必须符合后端生成规则，且账号 ID 与会话 ID 的 UTF-8 SHA-256 前 24 位匹配。拒绝外部 URL、路径穿越、未知预设和不属于当前上传目标的结果。
- 图片读取只解析同一配置服务的受控路径，最多读取 5 MiB，要求非空及允许的图片 MIME；拒绝重定向。公开头像请求不携带 Bearer 或 Cookie，和现有后端公开静态资源语义一致，不声称图片具有鉴权保护。
- 已知 Content-Length 超限时提前失败；缺失长度的流仍逐块检查实际字节数。取消读取会关闭请求；有限请求继续使用原有 30 秒配置。
- 上传不增加自动重试或后台补发。测试覆盖服务端读完请求后断开连接的单次发送，但不保证服务端未执行失败请求，也不提供跨设备恰好一次写入。

传输层只验证类型、路径和字节预算；新增图片层进一步读取真实图片尺寸、限制像素并解码。MIME 合法不等于可渲染；失败时组件使用模式默认头像，再失败显示占位，不修改用户已保存的选择。

## 恢复头像选择

头像选择使用 schema 1，记录 owner_id 和由 session_id / path 组成的列表。每个账号最多 1000 条记录、序列化文件最多 512 KiB；超限直接失败，不静默丢弃已有选择。空缺选择由上层使用对应模式的默认头像。

会话 ID 保持原始 UTF-8 字节，不按视觉相似性合并。例如 `café` 与 `cafe\u0301` 在 Swift 的 String 相等比较中可相等，在后端哈希中却不同。Swift 的 ChatAvatarChoices 用 Data 键查询；持久文件使用记录列表，避免 JSON 对象解码时先合并键。两端拒绝重复 ID、未知 schema、账号不符、非法路径及过大 / 损坏记录，修改失败不会用空数据覆盖损坏文件。

replace 操作在同一 repository 的锁 / actor 内核对 expected 旧选择，再写入新值或移除；两个竞争调用只有匹配旧值者成功。该比较不是登录 revision、跨进程锁或服务端事务。头像状态另按账号 revision 隔离任务，并处理上传已成功但本地保存失败、上传响应丢失和旧图片清理失败。

每个服务地址保持一个应用级 store 实例。Android 已接 noBackupFilesDir；iOS 已接 Application Support，写入辅助保留排除备份和首次解锁后的文件保护设置。宿主源码已接线，设备行为尚未验证。退出时清空内存、取消任务，磁盘选择保留供同账号重新登录恢复；其他账号读取自己的记录。账号删除的完整清理链仍属于 P11 后续工作。

## 选择状态与失败恢复

每次打开选择器绑定账号 revision、当前会话目标和独立标识。后续系统选择器返回时必须携带原标识；重新打开或切换会话后，旧结果失效。尚未产生消息的新会话也可选择头像。读取记录失败时禁止修改并提供显式重新读取，避免空数据覆盖损坏记录。Swift 查询、删除和预览继续使用会话 ID 的 UTF-8 字节。

上传、预设和恢复默认复用 ChatTurn 的修改占用，与发送、改名和删除互斥。一次执行一个头像操作；账号变更取消任务并丢弃迟到结果。

- 上传成功后保存资源路径；上传结果未确认时保留原选择并提示旧文件可能已被服务端替换，不自动重传。
- 保存失败时保留新选择作为内存预览。重试先读回记录，若已等于新值则确认完成，否则继续比较旧值后更新；不会再次上传。冲突不覆盖其他选择，用户可放弃待保存项并重新读取磁盘。
- 待保存项存在时可继续聊天，但须先处理它才能进行另一项头像选择。放弃仅丢弃内存预览，不触发远端操作。
- 选择预设先保存本地记录，再尽力清理该会话旧上传文件；恢复默认移除本地选择。远端清理失败保留已保存的选择并提示，不自动重试。
- ChatActions 在服务端确认删除会话后调用清理接口，保留原有修改占用，使未完成的头像读取失效，并仅移除对应会话记录。不会根据当前分页缺少摘要推断删除。磁盘清理失败保留会话删除成功结果并单独提示，磁盘可能仍留有该条头像元数据。

状态保留与保存重试减少重复上传及额外 IO；代价是需要独立呈现未保存状态。待保存项仅在内存，进程终止后不能恢复尚未保存的新路径。现有后端没有查询每会话当前头像的接口，也没有请求代次或条件删除协议；本机占用和取消不能保证已发出的服务端写入被撤销，跨设备及退出后重新登录时的远端竞争仍需后续核对。核心测试不提供恰好一次或服务端事务保证。

## 图片、缓存与系统选择

| 边界 | 当前值与行为 |
| --- | --- |
| 选择原图 | 实际读取最多 20 MiB；逐块读取，不能仅信任提供方文件长度 |
| 原图尺寸 | 任一边不超过 16384 像素，总像素不超过 64 × 1024 × 1024；先检查再解码 |
| 显示 / 上传 | 显示最长边 256、上传最长边 512，不放大小图；保留比例并按方向信息旋转 |
| 上传格式 | 解码首帧后编码静态 PNG，移除原图位置、拍摄时间等元数据，最终仍受 5 MiB 传输上限约束 |
| 图片缓存 | 每个账号 revision / 服务实例最多 32 张、8 MiB 解码成本；按最近使用顺序淘汰 |
| 工作队列 | 每个加载器最多 64 个不同资源请求，最多 2 路同时下载 / 解码；相同资源共享任务 |

缓存预算只约束加载器持有的图像，不代表整个进程内存上限；可见组件仍可能引用已淘汰的图像。图片不额外写磁盘。退出或账号变更换用新加载器，立即清空旧缓存并让等待者返回取消；不响应取消的迟到解码不能重新填充旧缓存。一个组件取消等待不会中断另一组件共享的请求。失败不自动重放；后续显式加载可重试。

Android 复用现有 Activity Compose 的 PickVisualMedia，系统不支持时由其回退到文件选择；只接收选中内容的 URI，不新增全图库权限。ContentResolver 读取在 IO 工作线程，取消时关闭流和取消正在打开的提供方；BitmapFactory 先读取尺寸再按采样比例解码，ExifInterface 提供方向，显示解码在 Default 工作线程。最低系统、HEIC 支持差异和不同照片提供方尚待设备验证。[系统照片选择文档](https://developer.android.com/training/data-storage/shared/photo-picker)、[BitmapFactory.Options](https://developer.android.com/reference/android/graphics/BitmapFactory.Options)、[ExifInterface](https://developer.android.com/reference/android/media/ExifInterface)。

iOS 使用 PhotosPicker 与 FileRepresentation，在导入回调有效期内消费临时文件，避免先把无限制原图读入 Data。独立工作任务使用 ImageIO 生成有界、已变换方向的缩略图，并转为 8 位 sRGB 位图；上传重新编码时不复制原文件属性，系统可写入新图像的尺寸 / 色彩字段。当前允许 PNG、JPEG、GIF、WebP、HEIC / HEIF；不支持或损坏输入显示错误。[PhotosPicker](https://developer.apple.com/documentation/photosui/photospicker)、[FileRepresentation](https://developer.apple.com/documentation/coretransferable/filerepresentation)、[方向变换](https://developer.apple.com/documentation/imageio/kcgimagesourcecreatethumbnailwithtransform)。

选择弹窗提供每模式 6 个预设、照片、恢复默认和保存失败后的重试 / 放弃。照片结果绑定原选择器标识，过期结果交给现有状态机拒绝；处理图片期间禁止重复选择。会话列表、头部及 AI 消息复用圆形头像组件。压缩、缓存和共享请求减少 IO 与内存占用，代价是原始尺寸、动画及 HDR 信息不保留，当前没有裁剪编辑器或图片磁盘缓存。

## 定向证据与剩余工作

共享样例 `contracts/fixtures/chat-avatar.json` 使用合成账号、特殊字符会话 ID 和生成的 1 像素 PNG。双端 API 测试覆盖 multipart 的 Unicode / 二进制 / 参数快照、所属目标、错误、MIME、大小、取消和不重放；存储测试覆盖重启、账号 / 地址 / 命名空间隔离、比较更新、容量、损坏记录、IO 失败及 Unicode ID。

后端新增两项契约将相同样例与真实路由、公开静态资源和预设目录对照。调用路径为 Native API → 回环 HTTP fixture，以及 FastAPI 路由 → 隔离文件目录；本地存储测试直接使用临时目录。它们支持核心协议和持久性结论，不支持相册选择、图片显示或真实生命周期结论。完整结果及本机日志位置见[实施状态](execution-status.md)。

复现提供方：在 backend 目录运行 `../.venv/bin/python -m pytest tests/contracts/test_chat_avatar_contract.py tests/p0/test_chat_avatars.py tests/p0/test_avatar_presets.py::test_preset_paths_match_public_assets`。Swift 核心在仓库根目录运行 `swift test --package-path ios/Packages/MindCore --force-resolved-versions --filter 'ChatAvatarAPIContractTests|FileChatAvatarStoreTests|FileChatTurnJournalTests'`。Android 通过既有 `scripts.ci.run_checks.android_tests` 明确选择同名 API / 存储 / 恢复 JVM 类，执行器先校验任务图。

增量映射登记头像提供方、共享样例、模型、接口、存储、状态与公共文件 IO；公共模块及宿主变化扩展到实际消费者。状态新增 Android 15 项、Swift 16 项测试，覆盖选择器失效、空会话、上传快照、操作互斥、读写失败、保存确认、账号切换、当前 / 迟到 401、删除及旧读取、Unicode ID 和路径归属。状态测试使用合成网关与存储，不包含相册或图片解码。Swift 额外控制账号快照读取的返回时点，验证旧账号快照返回后仍会复核任务代次，保留新账号选择与新上传的忙碌状态。

本批新增 Android 图片策略 4 项 / 加载器 7 项，Swift 图片处理 7 项 / 加载器 7 项。覆盖大小与像素预算、共享请求、等待者取消、双路并发、队列上限、LRU / 字节淘汰、失败不重放及关闭后的迟到结果。Swift 使用合成 PNG / JPEG / GIF / HEIC 与已迁入的 WebP 预设，验证方向、首帧、尺寸及原图隐私元数据移除；这些结果不能替代 iPhone 验证。Android JVM 只验证平台无关策略和调度，不声明 BitmapFactory 已运行。

预警审查：ChatLibraryScreen 284 行仍负责同一会话页的组合、账号门控与导航，图片解码、选择弹窗、状态和文件 IO 已分离；暂保留短列表行与标题布局以免增加仅转发参数的层。影响图测试按头像职责移至 test_avatar_image_impact.py，原 test_impact.py 从 773 行减为 735 行，仍低于 800 行硬上限；后续新增功能测试继续按职责独立。已有 ChatAvatarController 314 行保留同一状态拥有者，本批未改。无新增例外或限额提高。

下一步在独立获准构建时定向验证照片取消 / 重选、账号切换、旋转、损坏大图、默认回退、保存重试、滚动性能及最低系统；当前已安装的账号应用不包含本批代码。完整上下文重生成及后续模型设置继续按计划实施。P02、M2 与成品目标均未完成。
