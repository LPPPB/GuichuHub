# PostgreSQL 备份与恢复

生产备份服务使用 `pg_dump --format=custom` 生成单一 PostgreSQL dump。每份备份附带 SHA-256、Git tag、镜像 digest、Alembic revision 与 UTC 时间戳 manifest，并以 `pg_restore --list` 验证。它不删除源数据或旧备份，也不会自动上传到对象存储。

PostgreSQL 是业务、认证、dashboard、收藏和 tracked-UP 状态的唯一事实源；不需要额外 JSON 运行态备份。

## 创建备份

从检出根目录执行：

```bash
docker compose --env-file /srv/kichu/config/production.env \
  -f compose.prod.yml --profile maintenance run --rm backup
```

备份保存在 `/srv/kichu/backups`。恢复演练必须恢复到名称以 `kichu_restore_drill_` 开头的全新临时数据库，并验证 Alembic revision 与应用可读性；绝不覆盖生产数据库。

## 恢复演练

恢复先在全新临时数据库验证，不替换线上数据库：

```bash
python ops/backup/restore_drill.py --database-url-file /run/secrets/migration_database_url \
  --dump /srv/kichu/backups/kichu_postgres_<timestamp>.dump \
  --temporary-database kichu_restore_drill_20260916
```

若恢复演练失败，保留 dump、manifest 与日志，不要自动恢复。若必须实际恢复：停止写入服务，创建新的发布前备份，经人工确认后用维护窗口恢复整个数据库，并检查 `/api/health/ready` 与 Worker heartbeat。优先前向修复，禁止自动 downgrade。
