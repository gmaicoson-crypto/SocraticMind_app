# 会话标题与删除接口

更新：2026-10-23，属于 M2-02 / P02 的接口子任务。backend 和双端核心适配已验证；尚未接入原生操作状态、确认窗口或应用容器，不能据此标记会话管理完成。实际测试结果见[实施状态](execution-status.md)。

## 复用与改动

核对固定源 `4a20228e630168113e9e09a66de83699545fa82c` 的 `frontend/src/api/sessionTitles.ts`、`frontend/src/api/chat.ts` 和本仓库后端后，保留已有标题队列、手动命名事务、消息 / 会话删除及账号过滤。双端复用 HTTPTransport、历史标识校验及 JSON 协议处理，不增加网络库或数据库迁移，也不复制 Vue 状态。

原重命名路径将 session_id 放入 URL，且要求标题记录已存在。新增 JSON 入口将标识作为正文传递，支持含 `/ ? & # +` 和 Unicode 的 ID；没有标题记录但存在当前用户聊天消息的历史，也可直接手动命名。新建记录复用 schedule_title 的唯一键 / savepoint 处理，在同一事务内转为 manual、清除租约和重试，不解析模型配置或调用模型。用于确认归属的查询只读取最新聊天消息的 mode，不加载消息正文。

收益是保持删除及标题状态的同一后端所有者，避免客户端依赖 AI 标题成功才能重命名。取舍是新增一个兼容入口与双端适配，服务端需先升级；跨进程 MySQL 写入竞争仍需后续验证，不能把隔离 SQLite 测试当成完整并发保证。

## 三方契约

以下端点均使用当前账号的 Bearer 凭证；共享样例位于 [chat-actions.json](../contracts/fixtures/chat-actions.json)。

| 操作 | 请求 | 成功结果与边界 |
| --- | --- | --- |
| 查询标题 | GET `/api/chat/session-titles?ids=<session_id>` | 本批适配一次读取一个 ID，返回零或一项；拒绝重复项和不匹配 ID。列表继续使用已有摘要中的标题，避免逐行请求 |
| 手动命名 | PUT `/api/chat/session-titles`，JSON `session_id`、`title` | title 去首尾空白后为 1—40 个 Unicode 码点；返回同一 ID、规范化标题和 manual 状态。没有本账号标题或聊天消息时返回 404 |
| 删除会话 | DELETE `/api/chat/session`，JSON `session_id` | 非负整数 deleted，重复删除可返回 0；复用服务端原有整体清理范围 |
| 删除消息 | DELETE `/api/chat/messages`，JSON `ids` | 双端限制 1—100 个不同正整数 ID；deleted 为非负整数且不大于提交数量。只删除当前用户拥有的消息 |

标题响应仍包含 session_id、可空 title、status 和 retry_pending。状态仅接受 pending / running / ready / manual / failed；ready / manual 必须有非空标题，retry_pending 必须是真正的布尔值，且只有 failed 可为 true。删除数量不接受数字字符串、布尔值或负数。校验失败不合成成功结果。

会话标识不超过 100 个 Unicode 码点。双端写入口拒绝首尾空白标识，防止后端规范化后写到另一个标识；读取通过现有 URL 编码器传递。写请求沿用传输层不自动重放的规则，网络失败不会直接报告“已删除”。

## 兼容与删除后的恢复

旧 PUT `/api/chat/session-titles/{session_id}`、POST 标题请求和 GET 查询保持原行为与 schema。新入口只新增一个 OpenAPI operation 和 RenameSessionRequest，路径总数仍为 58。旧客户端可以继续访问更新后的后端；新客户端使用旧后端时，PUT 可能返回 405，适配器保留错误，不自动回退到无法保证不透明标识的旧 URL。

标题 worker 已领取任务时，手动命名清除其租约；迟到的 AI 结果不能覆盖 manual。当前契约测试覆盖这一顺序，但未验证多进程数据库竞争。

整段会话删除会移除请求记录，之后 GET 请求状态可能返回 404；部分消息删除可能留下失效请求并返回 409。404 仍表示客户端尚未确认结果，不能当成生成完成。已有恢复 / 取消链继续使用原 request_id，取消可建立中断标记，删除前的旧生成任务不能再次写回。操作界面接入时仍需阻止本机发送 / 重生成和删除交叉执行。

## 增量验证与继续实现

actions-provider、actions-fixtures、actions-android / ios 已登记精确路径和消费者；提供方或共享 JSON 改动触发后端动作、标题、关联删除生命周期、schema 及双端契约。回环 HTTP fixture 改动扩展到使用该 fixture 的账号 / 网络 / 历史 / 发送集合，不执行全量测试或应用打包。

本批覆盖特殊字符 ID、空标题历史、模型不可用时手动命名、归属过滤、重复删除、删除后的旧任务、迟到 AI 标题、Unicode 长度，以及双端 401 / 404 / 405 / 503 和无效响应处理。HTTP 错误的双端证据来自合成回环服务器，后端业务证据来自隔离测试库；不是双端应用连接真实后端的端到端证据。

下一步在既有 SessionStore、ChatLibrary 和 ChatTurn 所有者上接入操作状态：账号 revision 约束结果；重命名成功使旧摘要读取失效；删除确认后使旧历史读取失效；同一时刻只允许一项修改与发送任务；失败保留可重试意图。双端共享同一验收标准，再实现标题编辑、会话删除和消息选择删除界面。自动标题状态刷新、头像、建议和设备验收继续按 P02 推进。

行数审查：test_impact.py 536 行，达到测试预警值但低于 800 行硬上限；仍围绕影响映射和 runner 的显式选择边界，新增动作场景复用同一测试工厂。后续扩展领域时按映射 / runner / Git 范围拆分测试组织，本批不提高上限或增加豁免。其余变化源码低于预警值。
