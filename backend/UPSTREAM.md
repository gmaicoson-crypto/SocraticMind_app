# 后端来源与本地维护

迁入日期：2026-10-22。来源为 [SocraticMind](https://github.com/gmaicoson-crypto/SocraticMind)，固定提交 `4a20228e630168113e9e09a66de83699545fa82c`。这是规划审查的基线；没有切换到上游当前最新提交。

从本机源仓库的该 Git 对象导出，未复制工作区未提交内容或环境文件。来源迁入首先保存原始字节校验，后续格式与本地行为调整分别记录。当前仓库是移动后端维护主源，不自动与上游同步。

## 迁入清单

- 172 个 backend 文件：运行代码、测试、13 个历史 Alembic revision、提示词、配置样例、依赖和运行说明。
- 根 `pyproject.toml` 的 Ruff 配置。
- 根 MIT 许可证保存为 [LICENSE.upstream](LICENSE.upstream)，保留原版权声明。
- [upstream-manifest.json](upstream-manifest.json)记录上述 174 个文件的来源路径、目标路径与原始 SHA-256。原始哈希不会随着本地修改更新。

没有迁入 `backend/uploads/`。源提交中这个目录含已跟踪的用户上传头像，不属于源码或测试资产。未迁入 Web 前端、真实 `.env`、用户数据库、虚拟环境或源仓库 Git 历史。

另外从相同固定提交迁入 32 个预设头像资源（20 个用户头像、12 个 AI 头像），保存为 backend/assets/avatars。它们来自 frontend/public/avatars；没有迁入 Web 运行时代码。独立 [资源来源清单](assets/upstream-manifest.json)保留逐文件来源、SHA-256 和字节数，不改写原 174 项源码清单。backend 新增 /avatars 静态挂载，继续兼容原有相对路径；不使用用户上传头像替代产品资源。

## 本地变更记录

| 变更 | 目的与范围 | 实际证据 |
| --- | --- | --- |
| Python 3.12、Ruff 0.16.9；显式 E4 / E7 / E9 / F lint 规则 | 上游只运行格式检查；新增基础正确性门禁，避免升级 Ruff 时默认规则漂移 | 137 个非历史 Python 文件格式检查、150 个 Python 文件 lint 通过 |
| 13 个历史 migration 不格式化 | 保留原始历史语义与字节 | 来源 SHA-256 一致 |
| 6 个未使用 import 删除 | auth 模型接口、附件 parser、plans 及相关测试的 F401 清理 | 30 项相关定向回归通过 |
| check_attachment_runtime.py 导入位置与启动命令 | 第三方导入提前；确需 cwd 初始化的应用导入精确标注 E402 理由 | format / lint 通过；未运行真实附件能力诊断 |
| test_chat_summaries.py 的回调 lambda 改 def | 消除 E731，保持回调行为 | 对应租约恢复用例通过；首次登记前从 835 增至 838 行，显式记录这 3 行初始适配 |
| requirements-lock.txt | 固定已解析的运行与开发依赖；保留源声明用于比对 | Python 3.12.14 安装成功，pip check 通过；Linux 待验 |
| README 保留为 README.upstream.md | 新入口反映本仓库实际命令，避免旧 Web / 文档说明混淆 | manifest 仅改目标路径，原哈希保持 |
| 原生 EditorConfig 与运行数据忽略 | Kotlin / Swift 4 空格，阻止上传、私有附件及缓存进入源码 | 配置已生效；原生 formatter 结果独立记录 |
| AVATAR_STORAGE_DIR 与私有本地启动器 | 上传头像和数据库 / 附件一起持久保存；未设置时保留源默认路径 | 注册、头像上传、主题及 JWT 重启后保留的真实 HTTP 用例通过 |
| 预设头像资源与 /avatars 挂载 | 原生客户端不依赖 Web 服务即可读取原路径 | 头像路径用例和本地 HTTP WebP 响应通过 |
| 会话摘要与按会话游标历史 | 新增两个只读端点；提取新旧路由共用的可见性 / 来源投影，不改变原写入和事务 | 18 项提供方分页用例、相关来源 / 附件回归、隔离 MySQL 和双端消费者通过；旧 56 路径 / schema 比对无变更，见[契约](../contracts/compatibility/chat-history.md) |

来源清单中的 normalized_sha256 是最初格式规范化快照，不随着后续本地修改更新。原始 source_sha256 始终指向固定源提交；以上 lint 修复单独审阅，不伪称只有格式变化。

## 文件规模与验证

8 个历史超限文件已在 [逐文件基线](../scripts/quality/file-size-baseline.json)登记来源、上限、负责方、拆分任务与 2026-12-21 复查日期；另有 [预警职责检查](../docs/import-size-review.json)。后续不得增长，减少时下调；本地规模门禁已验证，远端执行情况见实施状态。

63 项不同定向用例通过：基础 22、lint 相关回归 30、MySQL 3、契约与生命周期 8。MySQL 升级用例首次因测试数据缺少 avatar_url 失败，补齐后仅重跑该用例通过；其余两个先前已通过，没有为得到整批绿灯重复无关测试。范围与命令见 [实施状态](../docs/execution-status.md)。

测试仍报告上游 Pydantic Config 与 SQLAlchemy declarative_base 弃用提示（测试组汇总为 5 条），留待相关依赖适配。没有执行全量测试、真实 AI / 搜索 / 邮件、APK / IPA、外部部署或原数据库操作。持久开发环境另有本地 HTTP / 重启验证；这些证据不代表全部业务与原生行为已完成。
