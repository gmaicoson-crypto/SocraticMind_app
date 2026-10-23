# 本地后端启动与数据保存

当前入口面向单人本机开发，复用本仓库 FastAPI、Alembic 和 MySQL。数据库、头像、附件与稳定密钥保存在忽略的 `local-data/backend/`；临时测试使用另外的目录，不会重置学习数据。没有配置模型时可以验证注册和资料等能力，AI 功能保持不可用，不返回假答案。

## 首次启动

先按 [backend 说明](../backend/README.md)安装 Python 3.12 依赖，并确保 `mysqld` 8.4 在 PATH 中。仓库根目录执行：

```bash
.venv/bin/python -m scripts.dev.local_backend init
.venv/bin/python -m scripts.dev.local_backend doctor
.venv/bin/python -m scripts.dev.local_backend run
```

默认监听 `http://127.0.0.1:8765`。终端显示 Ready 后可在另一个终端执行：

```bash
.venv/bin/python -m scripts.dev.local_backend status
```

在运行终端按 Ctrl+C 停止本次启动的后端和 MySQL，数据保留。再次 run 会检查配置、启动专用 MySQL、将本项目数据库迁移到 head 并启动服务。不会操作系统中其他 MySQL 服务。版本升级前的备份 / 恢复流程尚待 M5 完成，因此不能把这个启动器当作已验证的生产运维方案。

可在各命令后加 `--directory /absolute/private/path` 使用独立目录，或给 init / run 指定 `--mysqld /absolute/path/mysqld`。目录必须属于当前用户且权限为 700；拒绝接管已有不明数据。MySQL Unix socket 路径较长时换用更短的私有目录。run 支持 `--port 8766`，端口冲突会报错，不连接碰巧占用该端口的其他服务。

## 模型和本地验证码

模型、邮件和搜索配置写在 `local-data/backend/.env`，字段格式参考 [配置样例](../backend/.env.example)。启动器不继承终端里其他项目的数据库、模型和邮件变量；DATABASE_URL、SECRET_KEY 与存储目录由这个本地环境持有。

`doctor` 只显示配置是否可解析及是否配置模型，不打印配置值，也不调用外部服务。`models_configured: true` 不等于服务商可达或模型已验证。当前实际环境尚无真实模型，真实对话验收仍待完成。

未配置 SMTP 时，验证码沿用源后端的开发行为，写入 `local-data/backend/logs/backend.log`；仅用于本机调试。日志目录私有且已被 Git 忽略。后端日志按 5 MiB 轮转，保留 2 份；迁移日志位于同目录，MySQL 日志位于数据根目录。分享问题时先脱敏，不上传整个数据目录。

`identity.json` 保存稳定的本地密钥，重启不会重建；删除或替换它会影响既有 JWT 和用户模型密钥解密。没有自动重置数据命令。后续备份必须同时考虑数据库、附件、上传头像和密钥，不能只复制一个数据库文件。

## 客户端访问边界

当前服务只监听本机回环接口。iOS 模拟器可以使用本机地址；Android 官方模拟器的宿主访问使用 `10.0.2.2`，需配合开发环境地址白名单和平台网络配置。真机网络接入及相关配置仍待设备阶段验证，不把电脑上的 localhost 当作手机地址。参考 [Android 模拟器网络](https://developer.android.com/studio/run/emulator-networking-address)。

HTTP 仅用于明确的开发地址。双端网络核心默认要求 HTTPS，重定向不会自动携带凭证或重放变更请求。当前没有公网监听、外部部署或云账号要求。

双端账号页面已接入本地服务：Android Debug 默认 `http://10.0.2.2:8765/`，iOS Debug 默认 `http://127.0.0.1:8765/`。Release 不提供本地默认地址，缺少有效 HTTPS 配置时明确报配置错误。Android 的 HTTP 白名单只存在于 debug 资源，iOS 只在 Debug plist 放行 localhost / 127.0.0.1。

应用与核心测试分开运行。APK / iOS 模拟器应用的构建、安装及账号流程验证见 [原生账号验证](native-auth-verification.md)，需要当次明确构建授权；日常格式校验和纯核心测试不产生安装包。iOS 模拟器使用本地 ad hoc 签名即可验证应用私有 Keychain，无需付费开发者账号；真机签名条件另行核实。

## 已有证据

- 独立真实 HTTP 测试完成发送开发验证码、中文用户注册、获取凭证、上传头像、创建主题、停止并重启；旧凭证、资料、主题和头像均保留。
- 32 个固定上游预设头像已通过 backend 的 `/avatars` 提供；测试确认返回 WebP，用户上传仍使用独立存储目录。
- 6 项环境边界测试覆盖稳定身份、目录权限、互斥锁、拒绝未知数据、隔离父进程配置和状态查询地址检查。
- MySQL 的空库迁移、前一 revision 升级保留数据、lifespan / health 三项在临时独立实例通过。

这些证据不覆盖断电恢复、备份恢复、真实模型 / 邮件 / 搜索、设备行为或全部业务。详细结果见 [实施状态](execution-status.md)。
