# 移动项目后端

本目录从 SocraticMind 固定版本迁入，在本仓库独立维护。来源、许可证与本地差异见 [UPSTREAM.md](UPSTREAM.md)；[原始说明](README.upstream.md)保留用于溯源，其中的 Web 操作、旧文档链接和环境命令不作为本项目入口。

## 安装依赖

在仓库根目录使用 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
.venv/bin/python -m pip check
```

requirements.txt / requirements-dev.txt 保留上游声明，requirements-lock.txt 固定此次验证的直接和间接依赖。当前锁在 macOS / Python 3.12.14 验证；Linux CI 兼容仍待实际运行。

## 定向验证

基础配置、模型、迁移守卫和错误处理：

```bash
cd backend
../.venv/bin/python -m pytest tests/p0/test_config.py tests/p0/test_models.py tests/p0/test_migrations.py tests/p0/test_errors.py
```

从仓库根目录验证 MySQL 和契约：

```bash
.venv/bin/python scripts/dev/verify_backend_mysql.py
.venv/bin/python scripts/contracts/export_openapi.py --check
```

MySQL 验证需要 mysqld 8.4；脚本创建独立临时数据目录、禁用网络监听，验证后删除自己的实例。它不连接已有数据库，也不是用于保存学习数据的开发服务。可用重复的 --test 参数限定其三个明确测试中的相关项。

## 本地联调条件

已建立独立持久 MySQL、附件 / 头像目录与启动入口。在仓库根目录执行：

```bash
.venv/bin/python -m scripts.dev.local_backend init
.venv/bin/python -m scripts.dev.local_backend doctor
.venv/bin/python -m scripts.dev.local_backend run
```

完整说明见 [本地开发](../docs/local-development.md)。配置使用忽略的 local-data/backend/.env，稳定密钥由同目录 identity.json 保存；不使用源项目数据库或密钥。按 Ctrl+C 停止本次服务并保留数据。

未配置 SMTP 时上游只记录开发验证码；此入口将其写入私有 logs/backend.log。真实模型、搜索与邮件尚未联调；不将 mock 测试解释为外部服务可用。

## 当前验证边界

基础、相关 lint 回归、契约 / 生命周期和三个隔离 MySQL 场景共 63 项不同用例已通过，详细范围见 [实施状态](../docs/execution-status.md)。未执行全量测试。

另外已验证头像路径及本地注册 / 上传 / 重启保留数据。32 个预设头像按固定上游来源迁入 assets/avatars 并由 /avatars 提供。仍有上游依赖弃用警告和 8 个已登记历史大文件，具体见 UPSTREAM。原生功能 UI、实际模型质量与设备行为尚未完成，当前不是成品交付。
