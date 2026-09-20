# 安全边界

- Caddy 是唯一公网服务；Production Compose 仅发布 80/443。
- API 与 Worker 使用不同入口。API 不启动 scheduler；Worker 是后台采集与定时任务的唯一执行者。
- 写操作口令以 Docker secret 文件只提供给 API，启动日志不输出其值。
- 采集 Cookie 位于仓库外的 `/srv/kichu/private`：API 只读且代码级禁止写入，Worker 才能写入。管理员发起的采集凭证变更通过 PostgreSQL `auth` schema 的持久队列交给 Worker。
- PostgreSQL 是业务、认证、dashboard、tracked-UP 和管理员可编辑词表的唯一运行态事实源。API/Worker 不运行 DDL，不打开 SQLite，不回写 JSON 状态。
- 备份服务使用 `pg_dump --format=custom`，记录 SHA-256 和发布元数据，并使用 `pg_restore --list` 校验。
- 不提交 `.env`、密钥、Cookie、PostgreSQL 数据目录、离线 SQLite/JSON 快照、日志、备份、虚拟环境或 node_modules。

`core` Docker 网络为 internal。Worker 另接 egress 网络用于采集；不要为了便利向 API 或数据库暴露端口。对象存储、监控和云侧 IAM 都是外部 ops 适配项，不属于应用核心。
