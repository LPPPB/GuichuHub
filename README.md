# 鬼畜热度看板 V3

V3 是一个单仓库的 React/Vite + Flask + PostgreSQL 应用。生产环境由 Caddy、Frontend、API、Worker 与 PostgreSQL 组成；只有 Caddy 对外提供 80/443。

Git 只保存源码、测试、配置模板和部署定义。生产配置、Docker secrets、PostgreSQL 数据目录、Cookie、日志与备份必须保存在检出目录之外；本地开发使用被 Git 忽略的独立 `runtime/dev`。

PostgreSQL 是业务、认证、dashboard、收藏、tracked-UP 和管理员可编辑词表的唯一运行态事实源。仓库内的词表 JSON 仅是只读发布默认值，API/Worker 不会回写它们；SQLite/JSON 快照仅用于显式的一次性离线导入。

## 本地开发

从仓库根目录运行：

```powershell
pwsh -NoProfile -File ops/dev/dev.ps1 -Action up
```

需要 PowerShell 7 和本机 Docker Linux 引擎。入口自动生成本地专用凭据、构建镜像、启动 PostgreSQL、执行迁移并检查 API readiness。页面：<http://127.0.0.1:5174>。前端保存后热更新，API 使用开发重载，Worker 修改后显式重启。完整命令、数据边界及 Git/CI 流程见 [本地开发指南](docs/development.md)。

`config/development.example.env` 仅供直接运行后端进程时复制到被忽略的本地 `.env`；Compose 开发模式不读取它。生产部署见 [部署指南](docs/deployment.md)、[备份与恢复](docs/backup-restore.md) 和 [安全边界](docs/security.md)。

## 发布原则

发布使用经过验证的 Git tag。服务器检出该 tag、先创建 PostgreSQL 自定义格式备份、执行明确的 migration 服务，再用 Compose 重建服务；不要上传整个本地项目，也不要把运行数据提交到 Git。首次切换遵循 [PostgreSQL 切换 Runbook](docs/postgresql-cutover.md)。
