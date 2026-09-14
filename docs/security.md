# 安全边界

- Caddy 是唯一公网服务；Production Compose 仅发布 80/443。
- API 与 Worker 使用不同入口。API 不启动 scheduler；Worker 是后台采集与定时任务的唯一执行者。
- 写操作口令以 Docker secret 文件只提供给 API，启动日志不输出其值。
- 采集 Cookie 位于 `data/private`：API 只读且代码级禁止写入，Worker 才能写入。管理员登录后的采集凭证变更经 auth.db 持久队列交给 Worker。
- `data/state/inspiration_db.json` 由 API 与 Worker 共享；每次读改写使用跨进程锁与临时文件原子替换。
- 两个 SQLite 库使用 WAL；备份服务以只读 URI 调用 SQLite backup API，并校验每个快照。
- 不提交 `.env`、密钥、Cookie、SQLite/WAL/SHM、日志、备份、虚拟环境或 node_modules。

`core` Docker 网络为 internal。Worker 另接 egress 网络用于采集；不要为了便利向 API 或数据库暴露端口。对象存储、监控和云侧 IAM 都是外部 ops 适配项，不属于应用核心。
