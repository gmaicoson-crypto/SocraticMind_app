# M2-02 会话读取核心

状态：2026-10-23 已实现 backend 分页投影和双端读取适配，未接入原生页面。账号阶段的已安装应用保持原状态，不能从核心测试推定聊天功能已可用。

## 复用与职责

固定上游的 api/chat.ts 通过全账号 messages 还原会话，node history 最多返回最早 50 条。移动端新建后台摘要与游标读取端点，避免手机为了列会话加载完整正文。鉴权、数据库、可见性、附件与来源投影继续复用；兼容行为见 [契约](../contracts/compatibility/chat-history.md)。

| 位置 | 当前责任 | 保留的边界 |
| --- | --- | --- |
| backend/schemas/chat_history.py | 原 HistoryResponse 与新增页 / 摘要 schema | 原 schema 未变；不加入 AI 编排 |
| backend/services/chat_history.py | 可见性、来源 / 附件投影、摘要与固定上界查询 | 原事务 / 生成生命周期不移动；不逐条查标题 |
| backend/routers/chat_history.py | 参数、鉴权依赖、分页输入验证 | 通过 chat.router 接入；原路径保留 |
| Android core:chat | 纯 JVM DTO、游标检查与 ChatHistoryApi | 只依赖已存在 core:network 和语言库；无新增 Android / UI 依赖 |
| Swift MindCore/Chat | 对齐的 Codable / Sendable 数据与 ChatHistoryAPI | 继续使用 HTTPTransport；无 SwiftUI / UIKit |

API 适配器不保存 Token。应用接线时通过已有 SessionStore.authenticated 调用，由会话 revision 阻止迟到结果写入其他账号；功能状态仍必须自行取消任务、清空分页 / 草稿和按稳定 ID 合并。此处没有预建无人使用的通用缓存或第二套会话管理。

双端正文保持原值，结构化 message_type、metadata 和附件保留，便于节点聊天 / 来源组件继续复用。时间先保留服务端原字符串；后续展示需要明确 UTC / 本地时区，不把无时区日期直接按设备时区解释。

收益是接口可独立验证、列表载荷有界、两端消费同样数据；成本是维护两种原生适配，且新增端点需要先更新服务。当前不把物理拆文件当作完整 Chat 路由重构：原 chat.py 从 1275 收紧为 1216 行，历史上限同步下调，流编排仍待按职责拆分。

## 定向验证

```bash
# 仓库根：提供方与新读取协议
cd backend
../.venv/bin/python -m pytest tests/contracts/test_chat_history_contract.py

# android 目录：先审查任务图，仅 JVM / JAR
./gradlew :core:chat:test --tests com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest --dry-run
./gradlew :core:chat:test --tests com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest

# 仓库根：Swift 主机包；不运行应用宿主
swift test --package-path ios/Packages/MindCore --filter ChatHistoryAPIContractTests

# 仓库根：自有一次性 MySQL，不连接已运行的开发库
.venv/bin/python scripts/dev/verify_backend_mysql.py --test test_mysql_history_window_and_unicode_projection
```

命令按注释所在目录分别执行，不是连续执行的一段 shell。实际完整关联集合、结果和剩余边界见 [实施状态](execution-status.md)。HTTP fixture 与 Gradle 注册发生变化，所以增量映射还选择已有传输与账号消费者；未调用全量测试、应用打包或设备测试。

## 接下来仍属于 M2-02 的工作

1. 应用层接线会话列表、选择 / 新建、历史分页与失败重试；按账号清理、迟到请求隔离、刷新和去重由同一状态所有者负责。
2. 复用 MessageItem、Markdown、Composer；验证长正文、代码块、表格、滚动定位、键盘与无障碍，不把数据类解码当成渲染通过。
3. 对齐上游标题请求 / 查询 / 重命名、会话与消息删除、会话头像、风格与建议；头像上传复用后续平台文件适配，不复制 Web 存储。
4. M2-03 / M2-04 接入稳定请求 ID、SSE、停止、重生成和中断恢复。显示欢迎语不算服务器消息，失败 / 不确定提交不自动重放。

真实模型、真机、中文 / emoji 密码和其他账号遗留验收项继续保留。当前子任务不关闭 M1、M2 或成品交付。
