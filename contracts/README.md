# 三方接口契约

来源：本仓库 backend，初始上游为 `4a20228e630168113e9e09a66de83699545fa82c`。这里保存协议与合成样例，不存业务实现或真实用户数据。

## 文件与校验

- [OpenAPI](openapi/socraticmind.json)：由 FastAPI 实际应用导出，字段、必填、鉴权和响应声明以此为准。
- [SSE 约定](sse/README.md)：流格式、请求 ID、终态、停止和恢复。
- [流样例](fixtures/chat-streams.json)：后端提供方测试验证的核心帧，之后由 Kotlin / Swift 消费者使用同一文件。
- [分页历史](compatibility/chat-history.md)：新增会话摘要 / 单会话消息端点、固定 ID 上界、共享样例及旧接口兼容边界。

在仓库根使用 `.venv/bin/python scripts/contracts/export_openapi.py --check` 校验快照。接口有意改变时，先评审后端和消费者影响，再省略 `--check` 重新导出。导出使用临时工作目录、合成配置、内存 SQLite URL，禁止网络连接且不启动应用 lifespan / workers；不能据此认为服务健康测试已通过。

## 必须保留的接口语义

| 项目 | 约定 |
| --- | --- |
| 登录 | `POST /api/auth/login` 使用 application/x-www-form-urlencoded；username 字段放邮箱，非 JSON 登录 |
| 鉴权 | Bearer Token；过期重新登录，源基线无 refresh token 路由 |
| 用户失效 | 无效 Token 通常 401；Token 指向已删除用户可能 404，要区分认证检查失败与普通资源 404 |
| REST 错误 | 兼容 `code / message / retryable` 与 FastAPI `detail` 字符串 / 验证错误数组；不能假设所有路由统一错误格式 |
| 历史 | 旧接口保留 limit / offset；移动端使用新增 sessions / session-messages 的固定上界与 before_id，合并按服务端 ID 去重 |
| 时间 | 计划接口使用显式 IANA timezone；服务端记录与本地日期显示分开处理 |
| 附件 | capabilities 决定类型 / 额度；partial coverage 确认携带 revision，正文与预览需要鉴权 |
| 账号数据 | backend 是学习 / 会话权威；本地笔记和计时不因账号共用而自动同步 |

OpenAPI 不能证明 SSE 的 HTTP 分块时序、业务幂等或旧版本兼容。样例的提供方测试使用缓冲 TestClient 验证事件内容及顺序；真实网络逐块到达、断流和原生生命周期在 M1-05 / M2 另行验证。

接口变更需更新后端提供方、相关样例和双端消费者的定向测试。账号、流格式与分页历史已有双端核心消费者及明确测试集合，其他功能按阶段接入，不能将导出成功等同于全部业务或设备契约通过。

账号的合成契约样例见 fixtures/auth.json；提供方使用后端真实路由的隔离测试，双端通过共享回环 fixture 校验请求与响应。此证据不等于设备登录完成，详见 [账号实施](../docs/auth-implementation.md)。
