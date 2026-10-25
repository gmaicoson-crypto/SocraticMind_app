# 回答错误与模型用量

M2-05，2026-10-25。合成样例见 [chat-feedback.json](../fixtures/chat-feedback.json)。这是可选字段扩展；既有 SSE 核心帧、请求 ID、取消和恢复语义不变，不要求客户端与后端同时更新。

## 单次回答用量

`GET /api/chat/requests/{request_id}` 增加可空 `usage`；历史回答的 `metadata.usage` 在有效时存在。已保存用量的取消响应也带 `usage`，其余取消响应维持旧形状。失败重生成可能不出现在可见历史中，但该请求的状态接口仍返回自己的用量。

三个字段为 `prompt_tokens`、`completion_tokens`、`total_tokens`，必须全部是 0…9007199254740991 的整数，且前两者之和等于 total。布尔、浮点、负数、超界、缺项和不一致报告均视为未知；多余字段丢弃。有效零值与未知不同。一次调用的最后一份完整报告为准，不累加重复回调；最后报告无效时保留未知。

计数仅覆盖这次回答的模型调用，不包括标题、摘要、联网、附件处理等其他调用，也不等于账户余额、费用或额度。缺失报告不填零、不估算。官方流协议允许在启用 include_usage 时返回用量，但中断可能收不到最后报告，见 [Chat Completions](https://platform.openai.com/docs/api-reference/chat/object?lang=ruby)。其他兼容服务是否提供同样语义仍须真实配置验证。

## 错误与状态

| 场景 | code | 终态 | retryable |
| --- | --- | --- | --- |
| 调用或流等待超时 | AI_TIMEOUT | interrupted | true |
| 模型请求频率受限 | AI_RATE_LIMITED | failed | true |
| 模型账户额度不足 | AI_QUOTA_EXCEEDED | failed | false |
| 模型凭据或访问权限失败 | AI_PROVIDER_AUTH_FAILED | failed | false |
| 模型拒绝请求 | AI_REQUEST_REJECTED | failed | false |
| 模型连接错误 | AI_CONNECTION_FAILED | failed | true |
| 模型服务 5xx | AI_PROVIDER_UNAVAILABLE | failed | true |

SDK 的 429 仅在结构化 code 为 insufficient_quota / quota_exceeded 时归为额度不足；不从任意错误正文猜测。使用 [OpenAI Python SDK 的错误类型](https://github.com/openai/openai-python)，同时兼容本仓库固定 2.33.0 在流读取中抛出的 HTTPX 异常。服务内部已有 ApiError / ChatStreamError 维持原 SSE 消息；恢复与重放按持久化 code 返回安全描述。

`AI_OUTPUT_LIMIT` 表示输出长度限制，与账户额度不足分开。未知错误采用固定通用提示。SDK 的错误正文、连接地址和密钥不返回客户端、不写入消息元数据；日志保留错误类型和 code。`retryable` 仅表示可由用户决定重试，不触发自动重新 POST。以状态接口确认终态；收到 error 或 DONE 不能单独证明完整回答。

## 持久化与边界

复用 ChatMessage.metadata_json，无迁移。采集器按生成尝试隔离，锁内拷贝并在终结时封存，晚到工作线程不能改变已封存报告。数据库写入仍由 lifecycle 持有；取消后的最后检查点须匹配账号、token、上下文版本且没有更新轮次。MySQL 对更新轮次采用当前加锁读取，避免旧事务快照绕过检查。

用量随最终状态保存，不额外发送 SSE 事件。取消确认早于最后回写时可能暂时读到未知；刷新历史或状态后才可取得已保存报告。旧后端没有新字段仍合法。后端合成提供方与现有原生消费者已验证；专门的原生展示与真实服务、设备验证分阶段补充。
