# Chat SSE 与恢复约定

提供方：`backend/routers/chat.py`。传输为带 Bearer、JSON 请求体的 `POST /api/chat/stream`，成功流响应 `text/event-stream`。客户端不能使用仅支持 GET 的 EventSource，也不能先读完响应再展示。

## 帧与终态

每帧为 `data: <JSON>\n\n`；最终控制帧为 `data: [DONE]\n\n`。客户端需要增量 UTF-8 解码，兼容 CRLF、多行 data、注释 / 未知字段和任意字节切分。不能依赖 HTTP chunk 恰好等于一个字符或一帧。

| 数据结构 | 含义 |
| --- | --- |
| `msg_ids: {user, ai}` | 服务端持久消息 ID，收到后与本地占位消息关联 |
| `text: "..."` | 当前 AI 消息增量文本 |
| `request_state: {status}` | 请求终态，为 complete、failed、interrupted；状态查询还会返回 generating。用户停止结果为 interrupted，错误码 USER_CANCELLED |
| `error: {code, message, retryable}` | 流内错误，保留已有部分文本，是否允许重试由语义决定 |
| `type: context_compacting / context_ready` | 上下文准备状态，不作为可见回答正文 |
| `type: web_status / web_warning / web_sources` | 联网状态与引用，可能与文本穿插，来源随最终事件更新 |
| `type: attachment_context_preparing / ...` | 附件准备状态，未知扩展类型应保留兼容性 |
| `[DONE]` | 流已结束，不等于业务成功；成功由 request_state / 状态查询确认 |

共享样例只含选定的核心消息帧；真实提供方可穿插准备和来源帧。样例中的中文、ID 和错误内容均为合成测试数据。消费者测试应对每个字节边界切分相同 UTF-8 输入，不能维护不同语言各自修改的副本。

## 停止、断流与重试

1. 发送前保存稳定 request_id、session_id 和请求归属；同一请求的网络重试不得生成新 ID 后自动重发。
2. 用户停止调用 `POST /api/chat/cancel`，携带 session_id 和 request_id。关闭本地连接只是传输结束，不能声称后端已停止。
3. 断网 / 返回前台 / 重启后调用 `GET /api/chat/requests/{request_id}`，根据状态及 msg_ids 拉取历史；该响应没有字节偏移，不是 token 续传接口。
4. 处理中有限退避查询；已结束则使用历史中的权威内容。缺少 `[DONE]` 时不能把当前部分文本当作完整答案。
5. 重新生成使用 regenerate_message_id 和新操作对应的 request_id，服从服务端最近问题和会话约束；不是原请求静默重放。
6. run 版本冲突、鉴权失败、已删除请求分别处理；取消失败需要向用户说明并重新核实服务端状态。

正常与流内失败的核心帧由 `backend/tests/contracts/test_chat_stream_contract.py` 验证。取消、幂等和恢复继续复用 `tests/p0/test_chat_lifecycle.py` 中的定向用例；设备和真实网络证据单独记录。

## 原生消费者实现

Android core/network 和 Swift MindCore 的 SSEDecoder 复用数据帧标准处理 BOM、CR / LF / CRLF、data 多行与空白分派；不实现浏览器 EventSource 的自动重连。没有完整空行分隔的尾事件在 EOF 丢弃，由上层查询服务端状态。[WHATWG SSE 规则](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation)

项目额外采用严格 UTF-8 错误策略：遇到非法编码或超限终止该解析器，后续由请求恢复处理，不静默替换字符。默认单行最多 64 KiB、一个事件累计行内容最多 256 KiB（计入字段 / 注释，不计行分隔）；明确限制可配置。传输层后续应按小块读取，不能先读完整响应。

framing、chat-streams 和 invalid-chat-events 三份共享样例已由两端核心测试消费。未知事件保留原始载荷，未知 request_state 保留其字符串但不推定成功；DONE 仅表示流控制结束。后续网络层和请求状态机仍需验证认证、超时、取消、断网与恢复。
