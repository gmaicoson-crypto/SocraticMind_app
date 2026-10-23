# 账号接口、会话与凭证存储

更新：2026-10-23。M2-01 已接入双端账号页面、应用会话容器和平台凭证存储，并完成一轮真实本地后端的原生账号流程验证；真机、最低系统和完整账号隔离仍待验收。复用 backend/routers/auth.py 的业务行为和双端 HTTPTransport；没有重写注册、验证码、密码校验或默认学习主题规则。

| 用户动作 | 当前后端接口 | 双端适配 |
| --- | --- | --- |
| 邮箱登录 | POST /api/auth/login | 表单 username 提交邮箱，password 原样编码，不使用 JSON 登录 |
| 注册 | POST /api/auth/register | JSON username / email / password / code，返回账号资料和 bearer token |
| 获取验证码 | POST /api/auth/send-code | purpose 明确区分 register / reset，显示服务端 message |
| 找回密码 | POST /api/auth/reset-password | JSON email / code / new_password，完成后使用新密码登录 |
| 验证当前账号 | GET /api/auth/me | bearer 鉴权，401 保留为明确 HTTPFailure；不在接口层猜测刷新流程 |

Android 使用独立 core:auth 模块，依赖 core:network；iOS 在 MindCore/Authentication 中保持相同职责。AuthUser 与 AuthGrant 是手写协议模型，读取所需字段并忽略未知新增字段；用户 ID 必须为正数，凭证不能空白或带换行，token_type 必须为 bearer。凭证对象的普通字符串描述做脱敏，不放入页面可观察状态；这不代替日志审查。

输入仅规范化邮箱、用户名和验证码的首尾空白；密码保留原文。可复用 AuthFormController / AuthFormModel 处理必填、邮箱格式、密码确认、等待、取消和重复提交；最终强度 / 用户名规则由后端决定。表单接收标准错误及 FastAPI 422 msg，不回显校验 input。这样避免客户端复制第二套账号业务规则；代价是仍需联机完成最终验证。

验证码冷却按规范化邮箱和单调时钟记录，register / reset 共用 60 秒限制，开始发送时即保留等待窗口。失败或切换页面不允许通过重复点击绕过；服务端仍是限流权威。密码与验证码只在内存表单中保存，模式切换清理敏感字段，账号 revision 变化清理表单；状态字符串描述脱敏。

## 契约证据

[auth.json](../contracts/fixtures/auth.json)仅包含合成账号、密码和 token，不是任何环境的真实凭证。

- 后端 3 项用例执行真实路由、隔离 SQLite、密码哈希和 JWT 校验；验证注册 / 登录 / me 字段、重复注册无额外用户或主题、错误凭证、reset 专用验证码、旧密码失效和新密码可登录。邮件发送与限流命中被替换，这组结果不覆盖真实邮件或限流策略。
- Android 和 Swift 各 3 项用例通过共享回环 HTTP fixture 验证所有账号请求、大小写 / 首尾空白处理、Unicode / 加号密码、401 以及错误身份 / 凭证拒绝。
- Android 的 HTTP fixture 启动器迁到 network 的 testFixtures，账号与网络测试共用；不会将测试服务器代码带入应用运行时。
- CI 映射联动后端与双端账号消费者；会话和存储已注册独立测试集合，未来新增业务文件仍须补充映射，不能由接口用例代替。

后端提供方和双端 HTTP 消费者分别验证同一份样例，表单另共享 auth-form.json 的输入样例。主机测试和原生页面连接独立后端的结果分别记录；命令及边界见 [原生账号验证](native-auth-verification.md)和 [实施状态](execution-status.md)。

## 会话只有一个持有者

每个后端只创建一个 SessionStore。Android 用 Mutex / StateFlow，Swift 用 actor / AsyncStream；网络等待不占用存储临界区。观察状态包含账号与 revision，不包含 token；登录或恢复验证完成之前不能调用 authenticated。这样可以复用统一的身份边界，代价是功能层必须显式处理等待、恢复失败和清理失败，不能把所有失败简化成“未登录”。

| 情况 | 当前处理 | 后续页面责任 |
| --- | --- | --- |
| 启动无凭证 | 转 SignedOut，不调用 me | 展示登录入口 |
| 启动有凭证 | Restoring，me 成功后 SignedIn | 验证期间不展示旧账号内容 |
| me 返回 401 / 已删除账号的 404 | 清理凭证，转过期状态 | 重新登录提示 |
| 网络错误 | 保留凭证，Unavailable 可重试恢复 | 重试或明确清理后改用其他账号；不自动重新注册 |
| 凭证读取失败 | storage 错误，可重试恢复 | 区分系统存储暂不可用与断网 |
| 登录保存失败 | 尝试清除可能部分写入的数据，返回 storage 错误 | 提示登录未完成；注册可能已在后端成功，可改用登录 |
| 退出清理失败 | 立即失效内存凭证，保留不可登录的失败状态 | 重试清理，不能显示退出完成 |
| 当前鉴权调用 401 | 清理当前会话；普通资源 404 不退出 | 恢复登录流程 |
| 旧账号请求晚返回 | revision 不符时丢弃成功结果或旧 401 | 同样以 revision 绑定页面、缓存和任务 |

取消后的请求即使返回结果，也不提交登录 / 恢复状态或交付鉴权结果；取消不等于撤销已到达后端的注册或重置操作。写入失败后的补偿清理和明确退出不会因调用方取消而被截断。

SessionStore 不持有全部功能请求，也不代替功能任务取消。当前 app 容器拥有账号任务，在会话变化时清理表单，退出时取消未完成表单任务；后续功能仍须按 revision 取消旧任务、清理缓存和核对发布结果，SSE 逐事件更新也遵循这条规则。Swift 状态流只缓冲最新状态，消费者不能依赖一定观察到中间 Clearing / SignedOut，必须比较 revision。

## 安全存储与平台边界

凭证范围来自已验证的 API 基址，包含 scheme、host、port 和路径前缀；规范化默认端口、域名大小写和根路径。不同后端不共用 token，切换地址时应先处理当前会话。不会保存账号密码，不将 token 放入普通偏好配置或源码；单条凭证上限 16 KiB。

| 平台 | 实现 | 已验证与未验证 |
| --- | --- | --- |
| Android | core:auth 的 EncryptedTokenVault 使用 AES-256-GCM、随机 IV 和绑定后端范围的 AAD；app 的 KeystoreTokenVault 用 AndroidKeyStore 保存密钥、noBackupFilesDir / AtomicFile 保存密文 | JVM 核心及 API 36 模拟器中写入、重启恢复、退出清理通过；真机硬件保护、锁屏与备份另验 |
| iOS | KeychainTokenVault 使用 generic password，固定 service + 后端范围摘要 account，WhenUnlockedThisDeviceOnly，不同步 iCloud | FakeKeychainClient 验证错误分支；iOS 26.5 应用写入自己的 Keychain、重启恢复、退出清理通过；锁屏 / 真机另验 |

Android Keystore 操作经 SessionStore 的 IO dispatcher 执行；Swift 同步 Keychain 操作经会话 actor 执行，不放在 View 的 body 中。读取损坏密文不会生成替代密钥或偷偷清空账号；清理失败不会报告成功，两端均无明文降级。平台能力和性能仍需设备测量，不声称所有 Android 设备都具有相同硬件保护。[Android Keystore 官方说明](https://developer.android.com/privacy-and-security/keystore)

iOS 选择解锁时可读且不迁移到其他设备的存储属性，适合前台会话恢复；不能据此声称卸载必然删除钥匙串。实际重装、备份恢复和锁屏行为保留设备验收项。[Keychain 官方说明](https://developer.apple.com/documentation/security/adding-a-password-to-the-keychain)、[可访问性属性](https://developer.apple.com/documentation/security/ksecattraccessiblewhenunlockedthisdeviceonly)

## 待完成的账号流程

当前后端没有 refresh 或 logout 撤销接口。客户端退出清理本机凭证与账号状态，不可描述为“服务端已撤销全部设备登录”。当前重置密码也没有 token 版本撤销逻辑；后续如实现全端退出或密码变更后撤销，应作为后端协议和迁移变更处理。安全存储失败、退出期间登录返回、旧请求 401 清掉新账号等竞态需要独立用例，不能只补页面。

双端已复用字段组件接入登录 / 注册 / 找回，AppGraph / AppViewModel 和 AppModel 负责应用范围服务与会话任务。iOS 新密码输入使用一份 AuthTextInput 桥接处理平台替换行为；收益是保留安全输入和稳定内容，代价是需要单独验证焦点、选择区、自动填充和系统版本。

当前登录后页面仅显示账号和退出入口，学习业务未接入。真机、最低系统、账号内容隔离、锁屏、失效页设备场景和完整无障碍仍未关闭；M1 / M2 阶段及成品目标均未完成。
