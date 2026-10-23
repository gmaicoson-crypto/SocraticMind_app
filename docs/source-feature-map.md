# M0 功能动作核对

核对日期：2026-10-22。依据固定提交 `4a20228e630168113e9e09a66de83699545fa82c` 的 Git 对象，未使用上游工作区中的未提交内容。路径相对于源仓库；完整源版本见[基线审查](reference-audit.md)。本清单补充[产品范围](product-scope.md)，不代表原生功能已经实现。

## 用户动作与目标页面

| 功能 | 核对的动作 / 源位置 | 原生落点与验收补充 |
| --- | --- | --- |
| P01 账号 | `api/auth.ts`：send-code、register、表单 login、reset-password；`views/Login.vue`、`auth/ForgotPasswordModal.vue` | Auth：注册 / 验证码 / 登录 / 找回；错误、倒计时及失效处理，邮箱通过 username 提交登录 |
| P02 会话与历史 | `api/chat.ts`、`dialogue/DialogueHistoryPanel.vue`、`api/sessionTitles.ts`：新会话、切换、标题请求 / 查询 / 重命名、删会话、批量删消息、会话 AI 头像上传 / 清除、建议 | Chat + History：上述动作单独可验收；普通 / 节点聊天共用消息与输入；不能漏掉会话头像和消息选择删除 |
| P03 流恢复 | `api/chat.ts`、`composables/useChatStream.ts`：POST 流、请求 ID、停止、状态查询；`backend/routers/chat.py`：regenerate 参数与恢复状态 | ChatRequestCoordinator：断网与显式停止分开；重生成作用于契约允许的最近问题，不能模拟为重复发送 |
| P04 引导 | `api/agent.ts`、`agent/OnboardingForm.vue`、`PlanPreview.vue`：目标、领域、成果类型、熟悉度、每日分钟、时区、可选诊断、回答、修改、确认、取消 / 重试 | Onboarding：表单、诊断、预览、恢复；绑定服务端 run / version / request_id |
| P05 主题与计划 | `api/topic.ts`、`api/plans.ts`、`navigation/TopicManager.vue`：推荐主题、主题切换 / 重命名 / 删除、节点搜索、今日计划、主题计划、重排 | Learning / Plans：保留推荐和搜索入口；删除确认与后端归档后的统计一致 |
| P06 图谱学习 | `KnowledgeGraph.vue`、`graph/ThreeGraphCanvas.vue`、`composables/useTopicDialogue.ts`：图例、节点状态、选中节点 / 主题、适配视口、节点对话 | Graph：原生 2D、缩放 / 平移 / 适配 / 详情和节点列表；复用同一学习状态，不搬 Web 3D 运行时 |
| P07 评估掌握 | `api/agent.ts`、`agent/NodeMasteryControls.vue`、`AssessmentResult.vue`：开始评估、逐题回答、结果、自报掌握、撤销掌握 | Assessment：共享 AgentStep 展示；掌握规则、后续节点解锁与事务留在 backend |
| P08 记忆 | `api/memories.ts`、`profile/AgentMemorySection.vue`：筛选、创建、编辑、删除 | Memories：按用户 / 主题归属展示，提交后刷新权威结果 |
| P09 来源 | `dialogue/MessageSources.vue`、`api/chat.ts`、`types/webSearch.ts`：联网阶段、引用与来源；附件 chunk 获取 | MessageSources：来源绑定消息、允许外链；附件来源打开对应片段；无源客户端手动联网开关 |
| P10 附件 | `api/attachments.ts`：capabilities、上传、批量状态、retry、accept-text-coverage、delete、content / preview / chunks | Attachments：除上传预览外，还需部分解析覆盖确认和重试；确认必须携带 revision，不能绕过源解析状态 |
| P11 资料 | `api/auth.ts`、`profile/EditProfileModal.vue`：用户名 / 简介 / 目标 / AI 风格、预设 / 随机 / 上传头像、改密码、退出、密码 + 确认串删除账号 | Profile：明确包含登录后的修改密码；头像资源独立承接；清理会话、笔记、草稿、附件及凭证 |
| P12 模型 | `api/models.ts`、`dialogue/ModelSelector.vue`、`models/ModelEditorModal.vue`：环境 / 自定义分组、选择、添加、编辑、删除 | Models：编辑时空 api_key 表示保持原密钥；新增需提供密钥；不回显旧密钥；删除后处理当前选择 |
| P13 统计 | `api/progress.ts`、`views/profile/*`、`composables/useStudyTimer.ts`、`utils/dailyGoal.ts`：打卡 / 连续天数、统计、热力图、成就、每日目标与本地活跃计时 | Progress：区分服务端统计和本地分钟，移动端只对前台活跃学习计时，不把后台停留当学习；不声称本地分钟跨端同步 |
| P14 笔记 | `notes/MarkdownEditor.vue`：编辑 / 并排 / 预览、语法帮助、字符数、Markdown 导出、本地保存 | Notes：小屏支持编辑 / 预览切换，足够宽时并排；文本持久化按账号 / 主题隔离，不沿用源全局键 |
| P14 画布 | `notes/CanvasSketch.vue`：画笔、橡皮、颜色、粗细 1—8、缩放 0.5—3 / 重置、清空、PNG 下载 | Canvas：原生触控、颜色 / 粗细、缩放重置、清空确认、PNG 分享；增加本地恢复以满足本项目交付标准 |
| P15 体验 | `stores/ui.ts`、`components/ui/*`、导航与对话组件：主题、消息反馈、空态和交互状态 | 两端各自 DesignSystem；移动键盘、返回、无障碍、生命周期是新增平台适配 |
| P16 本地支持 | 本项目新增交付职责 | 本地服务连接与版本、运行 / 更新说明、反馈 / 错误信息；不要求外部上架或 TestFlight |

## 核对结论

本次补充的容易漏迁项：会话 AI 头像、消息选择删除、主题推荐与节点搜索、附件部分解析覆盖确认、登录后修改密码、模型编辑保留密钥、本地每日目标计时、笔记帮助和画布各项工具。它们属于原范围细化，继续归入现有 P 编号。

固定源基线依赖前端提供预设头像；本仓库现已从相同版本迁入受控产品资源，由 backend 的 /avatars 提供，来源见 backend/assets/upstream-manifest.json。源 Markdown / Canvas 依赖浏览器 API，需复用操作语义而非直接执行源组件。

历史正文使用 limit / offset；源文档没有保证任意模型都支持图片或任意扫描文件都有 OCR。文件能力、错误与确认行为以服务端返回为准，不把界面入口等同于能力可用。

M0-01 的功能动作核对已形成清单；后续每个 P 项实现时，还需引用具体 API / schema 和相关测试证明完成。M0-02 的品牌 / 系统范围已获用户确认，设备验证仍待实际运行条件。
