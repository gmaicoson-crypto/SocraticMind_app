# M2-02 会话读取核心

状态：2026-10-23 已实现 backend 分页投影、双端读取适配、按账号归属的分页状态及原生页面接线。本批页面没有重新编译 / 运行；账号阶段的已安装应用保持原状态，不能从核心测试推定聊天功能已可用。

## 复用与职责

固定上游的 api/chat.ts 通过全账号 messages 还原会话，node history 最多返回最早 50 条。移动端新建后台摘要与游标读取端点，避免手机为了列会话加载完整正文。鉴权、数据库、可见性、附件与来源投影继续复用；兼容行为见 [契约](../contracts/compatibility/chat-history.md)。

| 位置 | 当前责任 | 保留的边界 |
| --- | --- | --- |
| backend/schemas/chat_history.py | 原 HistoryResponse 与新增页 / 摘要 schema | 原 schema 未变；不加入 AI 编排 |
| backend/services/chat_history.py | 可见性、来源 / 附件投影、摘要与固定上界查询 | 原事务 / 生成生命周期不移动；不逐条查标题 |
| backend/routers/chat_history.py | 参数、鉴权依赖、分页输入验证 | 通过 chat.router 接入；原路径保留 |
| Android core:chat | DTO、游标检查、ChatHistoryApi 与 ChatLibraryController | 复用 core:network / core:auth，仍为纯 JVM |
| Swift MindCore/Chat | Codable / Sendable 数据、ChatHistoryAPI 与 ChatLibraryModel | 复用 HTTPTransport / SessionStore；Combine 状态，无 SwiftUI / UIKit |
| Android chatui / iOS Chat | 列表、历史原文、刷新 / 加载 / 重试与退出入口 | 两种页共用分页控件；页面不接触 Token 或字节流 |

API 适配器不保存 Token。功能状态通过已有 SessionStore.authenticated 调用，发送前检查账号 ID / revision，完成时再次检查账号和请求序号。退出先同步清空列表、选择和消息并取消请求；账号观察更新再绑定新的状态。页面还比较当前账号与状态归属，避免两个观察流在不同帧交付时显示旧账号数据。没有第二份凭证存储；草稿尚未实现。

双端正文保持原值，结构化 message_type、metadata 和附件保留，便于节点聊天 / 来源组件继续复用。时间先保留服务端原字符串；后续展示需要明确 UTC / 本地时区，不把无时区日期直接按设备时区解释。

收益是接口可独立验证、列表载荷有界、两端消费同样数据；成本是维护两种原生适配，且新增端点需要先更新服务。当前不把物理拆文件当作完整 Chat 路由重构：原 chat.py 从 1275 收紧为 1216 行，历史上限同步下调，流编排仍待按职责拆分。

## 页状态、生命周期与取舍

- 列表和历史各自保留 loaded、loading、failure、items 和 nextCursor。首次失败不显示为“空历史”；追加或刷新失败保留已有内容，重试保持原操作。重复点击同类加载不并发发请求，刷新可以取消尚未返回的追加页。
- 加载更多按稳定 ID 去重，保留已加载的更新版本；刷新替换窗口。切换会话即清空旧历史，关闭会话或功能容器取消任务。测试用不响应取消的网络替身验证迟到成功和错误不会重新写入状态。
- UI 使用 Compose LazyColumn / SwiftUI List 与稳定消息 ID，默认每次只请求 30 项，不自动读完整历史。消息在核心保留服务端倒序，展示时转为时间正序；首次进入定位到最近消息，加载更早页的滚动锚点仍需设备验证。[Compose 列表文档](https://developer.android.com/develop/ui/compose/lists)
- 已加载页保留在当前账号的内存中，更多页面只随用户操作请求。还没有磁盘缓存、分页淘汰或重进程恢复选中会话；大历史的内存、布局和响应上限须继续测量。共享页逻辑减少双份重试实现，代价是需要维护取消和账号边界用例。
- 正文暂按原文显示，附件只显示数量；没有把这些状态当作 Markdown、受保护附件预览、结构化学习消息或发送已实现。原账号流程的设备结果也不能覆盖本批页面改动。

## 定向验证

```bash
# 仓库根：提供方与新读取协议
cd backend
../.venv/bin/python -m pytest tests/contracts/test_chat_history_contract.py

# android 目录：先审查任务图，仅 JVM / JAR
./gradlew :core:chat:test --tests com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest --dry-run
./gradlew :core:chat:test --tests com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest
./gradlew :core:chat:test --tests com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest

# 仓库根：Swift 主机包；不运行应用宿主
swift test --package-path ios/Packages/MindCore --filter ChatHistoryAPIContractTests
swift test --package-path ios/Packages/MindCore --filter ChatLibraryModelTests

# 仓库根：自有一次性 MySQL，不连接已运行的开发库
.venv/bin/python scripts/dev/verify_backend_mysql.py --test test_mysql_history_window_and_unicode_projection
```

命令按注释所在目录分别执行，不是连续执行的一段 shell。实际完整关联集合、结果和剩余边界见 [实施状态](execution-status.md)。本批应用依赖与容器变化由映射增加同平台网络 / 账号相关集合；没有修改后端，未运行后端业务或 MySQL。没有全量测试、应用打包或设备测试。

## 接下来仍属于 M2-02 的工作

1. 为已接线的列表、选择、历史分页与失败重试安排独立宿主验证；补齐新建会话 / 草稿、返回定位及重进程恢复。核心的账号隔离通过不等于设备和所有功能缓存已经隔离。
2. 复用 MessageItem、Markdown、Composer；验证长正文、代码块、表格、滚动定位、键盘与无障碍，不把数据类解码当成渲染通过。
3. 对齐上游标题请求 / 查询 / 重命名、会话与消息删除、会话头像、风格与建议；头像上传复用后续平台文件适配，不复制 Web 存储。
4. M2-03 / M2-04 接入稳定请求 ID、SSE、停止、重生成和中断恢复。显示欢迎语不算服务器消息，失败 / 不确定提交不自动重放。

真实模型、真机、中文 / emoji 密码和其他账号遗留验收项继续保留。当前子任务不关闭 M1、M2 或成品交付。
