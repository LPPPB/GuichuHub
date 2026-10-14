# GuichuHub

**面向 Bilibili 鬼畜创作的趋势与素材看板。**

GuichuHub 汇集鬼畜榜单、热梗、潜力视频、BGM 与互动信息，帮助创作者观察内容变化、寻找选材线索，也方便爱好者浏览近期热点。

项目原名「鬼畜热度看板 V3 / Bilibili-kichiku-dashboard」，现统一使用 **GuichuHub**。代码仓库地址为 `https://github.com/LPPPB/GuichuHub`。

[访问网站](https://guichuhub.cn) · [版本发布](https://github.com/LPPPB/GuichuHub/releases) · [本地开发](docs/development.md) · [部署指南](docs/deployment.md) · [问题反馈](https://github.com/LPPPB/GuichuHub/issues)

[![Backend CI](https://github.com/LPPPB/GuichuHub/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/LPPPB/GuichuHub/actions/workflows/backend.yml)
[![Frontend CI](https://github.com/LPPPB/GuichuHub/actions/workflows/frontend.yml/badge.svg?branch=main)](https://github.com/LPPPB/GuichuHub/actions/workflows/frontend.yml)

## 可以做什么

| 方向 | 功能 |
| --- | --- |
| 内容趋势 | 鬼畜区排行榜、热梗与关联视频、潜力视频及爆发观察 |
| 创作资源 | 梗素材库、热歌 BGM、素材发掘与视频预览 |
| 互动洞察 | 弹幕词云、热词升温榜、高赞评论与互动质量指标 |
| UP 主动态 | 关注 UP 主，查看近期投稿趋势、发布日历与发布习惯 |
| 视频比较 | 视频指标雷达图，辅助观察不同互动维度 |
| 使用体验 | Bilibili 扫码登录、账号收藏、浅色与深色主题、响应式布局 |

趋势、热度和潜力分数基于采集批次及项目计算规则，用于辅助观察。它们不代表 Bilibili 官方榜单，也不能保证作品后续表现；部分分析需要积累历史数据。

## 快速开始

Windows 本地开发需要 Git、PowerShell 7 和运行 Linux 引擎的 Docker Desktop。先确认本机 `5174`、`5000`、`5432` 端口空闲。

```powershell
git clone https://github.com/LPPPB/GuichuHub.git
cd GuichuHub
pwsh -NoProfile -File ops/dev/dev.ps1 -Action up
```

开发入口会生成本地专用凭据、构建镜像、启动 PostgreSQL、显式执行迁移并检查 API readiness。首次构建需要联网下载依赖。

| 入口 | 地址 |
| --- | --- |
| 前端页面 | http://127.0.0.1:5174 |
| API 就绪检查 | http://127.0.0.1:5000/api/health/ready |

查看状态或停止开发栈：

```powershell
pwsh -NoProfile -File ops/dev/dev.ps1 -Action status
pwsh -NoProfile -File ops/dev/dev.ps1 -Action down
```

React/CSS 保存后热更新，API 源码使用开发重载；Worker 修改后执行 `-Action restart-worker`。停止开发栈会保留开发数据。完整说明见 [本地开发指南](docs/development.md)。

此快速开始适用于当前主分支；历史 Release 请使用对应标签内的文档。

## 技术与服务结构

| 层级 | 技术与职责 |
| --- | --- |
| 前端 | React、Vite、Tailwind CSS、ECharts |
| API | Flask，提供查询、认证和管理接口 |
| Worker | 独立采集进程，执行定时采集及后台任务 |
| 持久化 | PostgreSQL 16，使用 Alembic 显式迁移 |
| 部署 | Docker Compose；生产环境由 Caddy 提供 HTTPS 入口 |

API 与 Worker 分开运行。PostgreSQL 是业务、认证、看板、收藏、关注 UP 主和管理员可编辑词表的唯一运行态事实源。仓库内词表 JSON 仅作为只读发布默认值；SQLite/JSON 快照只用于显式的一次性离线导入。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [本地开发](docs/development.md) | 开发栈、源码重载、验证命令与 Git/CI 流程 |
| [部署指南](docs/deployment.md) | 生产环境目录、服务构建、迁移与健康检查 |
| [备份与恢复](docs/backup-restore.md) | PostgreSQL 备份、恢复与演练 |
| [安全边界](docs/security.md) | 认证、密钥、运行数据与服务权限 |
| [API 出站边界](docs/api-egress.md) | API 出站代理与网络限制 |
| [V2 到 V3 数据迁移](docs/migration-v2-to-v3.md) | 显式离线导入流程 |
| [PostgreSQL 切换 Runbook](docs/postgresql-cutover.md) | 数据库切换与验证步骤 |

## 开发与发布

新改动通过短期分支和 Pull Request 提交。GitHub Actions 执行后端及 PostgreSQL 集成验证、前端测试与构建、布局和雷达交互检查，以及 Windows 开发初始化验证。具体命令见 [开发指南](docs/development.md)。

生产部署使用经过验证的 Git tag 或不可变镜像；更新前备份数据库，显式执行迁移，再检查服务 readiness。历史发布记录见 [Releases](https://github.com/LPPPB/GuichuHub/releases)。

Git 只保存源码、测试、配置模板与部署定义。生产配置、Docker secrets、数据库、Cookie、日志和备份保存在检出目录之外；本地开发使用被 Git 忽略的独立 `runtime/dev`。开发入口不会自动导入生产或旧版本的数据与账号。

如遇问题，请在 [Issues](https://github.com/LPPPB/GuichuHub/issues) 中说明复现步骤、版本和经过脱敏的错误信息；功能想法可在 [Discussions](https://github.com/LPPPB/GuichuHub/discussions) 交流。
