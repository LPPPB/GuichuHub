# SQLite 备份与恢复

生产备份服务使用 SQLite `Connection.backup`，为业务库和认证库分别生成 `business_*.db`、`auth_*.db`，并执行 `quick_check`。它不复制运行中的数据库文件，不删除源数据，也不会自动上传到对象存储。

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
