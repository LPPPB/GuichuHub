# 本地开发

主分支 `main` 是统一开发基线。Windows 固定源码入口为 `F:\作业工程库\GuichuHub`，旧 V2、审计副本、旧 V3 和任务工作区保留。新功能从更新后的 `main` 建立短期分支，通过 PR 和 CI 合并。

## 启动与停止

安装 PowerShell 7、Git 和 Docker Desktop，启动 Linux 引擎。从仓库根目录运行：

```powershell
pwsh -NoProfile -File ops/dev/dev.ps1 -Action up
```

入口固定使用 Compose 项目名 `guichuhub-local`，先构建镜像，等待数据库健康，显式执行 Alembic 迁移，再启动服务并等待 API readiness。首次构建需要联网下载依赖。默认端口必须空闲：

| 服务 | 地址 |
| --- | --- |
| 前端 | http://127.0.0.1:5174 |
| API readiness | http://127.0.0.1:5000/api/health/ready |
| PostgreSQL | 127.0.0.1:5432 |

`dev-ingress` 代理这三个回环端口，并转发 Vite WebSocket。API、前端和 PostgreSQL 保持在 `core` 内部网络；API 出站仍经原有白名单代理。这样也兼容不会为内部网络单独发布端口的 Docker 引擎。

其他命令：

```powershell
pwsh -NoProfile -File ops/dev/dev.ps1 -Action init
pwsh -NoProfile -File ops/dev/dev.ps1 -Action status
pwsh -NoProfile -File ops/dev/dev.ps1 -Action logs
pwsh -NoProfile -File ops/dev/dev.ps1 -Action restart-worker
pwsh -NoProfile -File ops/dev/dev.ps1 -Action down
```

`init` 可在引擎未启动时准备配置。重复初始化复用现有凭据；凭据缺失一部分、角色 URL 不匹配或已有数据库却缺少凭据时停止，避免覆盖旧文件。`down` 停止并移除本项目容器，保留数据库、Cookie、日志和依赖卷。再次 `up` 继续使用现有开发数据。

仅允许本机 npipe/unix Docker 上下文。`KICHU_DEV_SECRETS_DIR`、`KICHU_DEV_BACKEND_DEPS`、`KICHU_DEV_FRONTEND_DEPS` 如已在当前进程环境设置，入口会拒绝执行；请清除覆盖项后重试。使用统一入口管理容器，避免直接 Compose 命令遗漏生成的依赖卷设置。

## 独立数据

所有开发运行态在被 Git 忽略的 `runtime/dev`：

| 路径 | 内容 |
| --- | --- |
| `secrets/` | 五个独立随机角色密码、三个匹配的数据库 URL；UTF-8 无 BOM |
| `postgres/` | 本项目 PostgreSQL 数据 |
| `private/` | 本地登录产生的 Cookie |
| `logs/` | 本地日志 |
| `compose.env` | 根据锁文件生成的依赖缓存标识，不含凭据 |

开发库从空库初始化，Worker 启动后按应用既有逻辑采集公开数据。生产和旧版本的数据库、账号、Cookie、配置均不自动导入。私有登录通过本地页面单独完成。备份时必须将数据库与匹配凭据一并妥善保存；不要把运行目录加入 Git。

## 保存代码后的行为

| 改动 | 更新方式 |
| --- | --- |
| React / CSS | 源码绑定挂载，Vite HMR；Windows 使用轮询监听 |
| Flask API Python 源码 | 源码绑定挂载，Flask `--debug` 自动重载 |
| Worker Python 源码 | `-Action restart-worker` |
| Node / Python 依赖 | 用包管理器更新锁文件后重新 `-Action up` |
| Dockerfile / 系统依赖 | 重新 `-Action up` |
| 数据库结构 | 添加 Alembic 迁移后 `-Action up` 显式执行 |

锁文件内容变化会选择新的命名依赖卷，避免重建镜像后仍挂载旧 `node_modules` / `.venv`。旧缓存卷保留，数据库路径不变。Shell 脚本通过 `.gitattributes` 保持 LF，保证 Windows 检出后可在 Linux 容器执行。开发重载仅用于回环地址上的本地环境。

## 测试与提交

在本地开发栈启动后，可使用容器内的 Node 22 环境运行前端验证：

```powershell
docker compose -p guichuhub-local -f compose.dev.yml --env-file runtime/dev/compose.env exec -T frontend npm test -- --maxWorkers=2
docker compose -p guichuhub-local -f compose.dev.yml --env-file runtime/dev/compose.env exec -T frontend npm run build
node --test ops/dev/dev.test.mjs
```

最后一条需要本机 Node 22 或更新兼容版本。后端测试使用独立测试环境与临时测试数据库，按 CI 执行 `uv run --extra dev pytest -q --no-cov`；API 开发镜像只装运行依赖。测试不可指向生产库或日常开发库。

GitHub Actions 对 push / PR 自动执行：后端测试及 PostgreSQL/Compose/镜像检查；前端 Node 22 锁定依赖安装、完整 Vitest、生产构建、浅色及深色五种屏宽的布局和雷达交互；Windows 下验证开发初始化的凭据与数据保护。

开始任务前确认工作区干净，再执行：

```powershell
git switch main
git pull --ff-only
git switch -c feat/describe-change
```

编辑、查看本地效果、先验证回归测试失败再修复。提交时只暂存本次改动，检查差异中没有运行数据或凭据：

```powershell
git diff
git add -- <本次实际修改的文件>
git diff --cached
git commit -m "feat: describe the change"
git push -u origin feat/describe-change
```

在 GitHub 创建 PR，CI 与审查通过后合并 `main`，再同步本地。保存源码、容器重载、commit、push 是不同动作，不会互相自动代替。生产发布另用经过验证的 tag 或不可变镜像，遵循 [部署指南](deployment.md) 的备份、显式迁移与健康检查。
