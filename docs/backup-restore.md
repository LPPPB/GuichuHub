# SQLite 备份与恢复

生产备份服务使用 SQLite `Connection.backup`，为业务库和认证库分别生成 `business_*.db`、`auth_*.db`，并执行 `quick_check`。它不复制运行中的数据库文件，不删除源数据，也不会自动上传到对象存储。

当前维护备份只覆盖这两个 SQLite 库；它**不**包含 `data/state/inspiration_db.json`。该 JSON 含有可变应用状态，不能把 SQLite 快照误认为完整运行态恢复点。

## 创建备份

从检出根目录执行：

```bash
docker compose --env-file /srv/kichu/config/production.env \
  -f compose.prod.yml --profile maintenance run --rm backup
```

备份保存在 `/srv/kichu/backups`。可选的异地上传必须是独立主机脚本，保留本地副本，并只通过 S3-compatible endpoint、bucket、prefix、region 与受保护凭据文件配置。

## 恢复演练

恢复先在副本上验证，不替换任何线上文件：

```bash
sqlite3 /srv/kichu/backups/business_<timestamp>.db 'pragma integrity_check;'
sqlite3 /srv/kichu/backups/auth_<timestamp>.db 'pragma integrity_check;'
```

两条命令都必须输出 `ok`。如需真正恢复：停止 API 和 Worker，另行备份现有 `data/db` 和 `data/auth`，经人工确认后仅替换对应数据库文件，再启动服务并检查 `/api/health`。恢复业务库与认证库必须使用同一备份批次；不要自动恢复，也不要把恢复文件提交到 Git。

如需完整保留 JSON 状态，在单独维护窗口停止 API 与 Worker 后，将 `data/state` 复制到带时间戳、受保护的本地快照目录；恢复该状态也必须在两服务停止时人工确认后进行。该额外快照可由云无关的主机脚本上传到 S3-compatible 存储，但不应替代本地 SQLite 快照。
