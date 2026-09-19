# PostgreSQL 备份与恢复

生产备份服务使用 `pg_dump --format=custom` 生成单一 PostgreSQL dump。每份备份附带 SHA-256、Git tag、镜像 digest、Alembic revision 与 UTC 时间戳 manifest，并以 `pg_restore --list` 验证。`KICHU_GIT_TAG` 与 `KICHU_IMAGE_DIGEST` 必须是已验证的发布身份；缺失或 `unknown` 会让备份在写入 dump 前失败。它不删除源数据或旧备份，也不会自动上传到对象存储。

PostgreSQL 是业务、认证、dashboard、收藏、tracked-UP 和管理员可编辑词表的唯一事实源；不需要额外 SQLite 或可变 JSON 运行态备份。

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
PYTHONPATH=backend uv run --directory backend python ../ops/backup/restore_drill.py \
  --database-url-file /srv/kichu/secrets/migration_database_url \
  --provisioner-database-url-file /srv/kichu/secrets/restore_drill_provisioner_url \
  --dump /srv/kichu/backups/kichu_postgres_<timestamp>.dump \
  --manifest /srv/kichu/backups/kichu_postgres_<timestamp>.dump.manifest.json \
  --temporary-database kichu_restore_drill_20260916
```

`migration_database_url` 只恢复 schema/data，仍是唯一拥有 DDL 权限的应用角色。`restore_drill_provisioner_url` 是检出目录外、仅人工恢复演练使用的受保护凭据，且只负责创建和删除该次以 `kichu_restore_drill_` 开头的临时库；它不挂载到 API、Worker、migrate 或 backup 服务。演练先校验 dump SHA-256，再恢复，并核验 manifest 记录的 Alembic revision 与通过 PostgreSQL state repository 的应用可读查询。失败时会清理已创建的临时库，但保留 dump、manifest 与日志。

若恢复演练失败，保留 dump、manifest 与日志，不要自动恢复。若必须实际恢复：停止写入服务，创建新的发布前备份，经人工确认后用维护窗口恢复整个数据库，并检查 `/api/health/ready` 与 Worker heartbeat。优先前向修复，禁止自动 downgrade。
