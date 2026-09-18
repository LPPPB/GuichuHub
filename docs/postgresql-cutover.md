# PostgreSQL 首次切换 Runbook

本流程只针对已验证的 V3 发布。不要在本流程中访问未明确提供的数据库、快照或备份；SQLite 和 JSON 快照仅作为只读归档与一次性离线导入输入。

## 首次切换

1. 进入维护窗口，停止 API 与 Worker，确认没有写入请求。
2. 创建并验证两份 SQLite 一致快照（业务库、认证库）。必须停止写者并使用 SQLite backup API，不得只复制主文件；保留原文件、`-wal`、`-shm`，不要删除或就地转换。
3. 生成两份明确的 JSON 快照：`tracked_ups.json` 和一个 dashboard envelope。后者必须含 `dashboard` 以及 `runtime_settings`（`danmaku_filters`、`meme_stopwords`、`meme_seed_words`、`tag_filters`）；从旧 dashboard/词表文件离线、无损地合并，不让导入器扫描或猜测路径。
4. 将这四份快照复制到受保护的离线目录，记录 SHA-256；启动一个空 PostgreSQL 16 实例（数据目录在 Git 检出外），并为 API、Worker、migration、backup 创建独立的 PostgreSQL URL secret。
5. 执行一次性维护 migration：`docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml --profile maintenance run --rm migrate`。
6. 从 `backend` 目录用 migration 角色执行离线导入：`uv run python scripts/import_sqlite_snapshot.py --business-sqlite <business.sqlite> --auth-sqlite <auth.sqlite> --dashboard-json <dashboard-envelope.json> --tracked-ups-json <tracked_ups.json> --database-url-file <migration-url-file> --report <reconciliation.json>`。这四个输入必须由操作员显式指定且只读。
7. 审核 reconciliation report：所有实体行数、关键主键、最新观测时间、管理员、会话、credential handoff、收藏、tracked UP、dashboard 以及四类 runtime settings 都必须一致，`valid` 必须为 `true`。
8. 将 API/Worker 切换到 PostgreSQL URL secrets，确认没有 SQLite/可变 JSON 状态挂载；再运行 migrate，它应是无 DDL 的 no-op 且 revision 等于唯一 Alembic head。
9. 启动 PostgreSQL、API、Worker、Frontend、Caddy；检查 `/api/health/live`、`/api/health/ready`、Worker heartbeat、核心 API 与日志。
10. 将四份 SQLite/JSON 快照、SHA-256 和 reconciliation report 设为只读并保存至少 **90 天**。这是现有的较长部署保留策略；切换后不再将它们作为运行态存储。

## 后续数据库发布

1. 代码、SQLAlchemy model、唯一 Alembic revision、必要的可恢复 backfill 与测试必须一起提交。
2. CI 必须检查单 head、空库升级、旧快照导入、健康检查、完整后端测试及 Compose config。
3. 创建并验证 PostgreSQL 自定义格式备份。
4. 停止写入服务。
5. 执行 `alembic upgrade head`，只使用 migration 角色。
6. 如有需要，运行可恢复 backfill；它将进度保存在 `app.backfill_progress`。
7. 启动新版本并检查 readiness、heartbeat 和关键业务 API。
8. 故障优先前向修复，**禁止自动 downgrade**。只有经确认的维护窗口才能从发布前 PostgreSQL 备份恢复。

## 备份与恢复命令

- 创建并验证 PostgreSQL 备份：`docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml --profile maintenance run --rm backup`。
- 恢复演练只能指向新建的 `kichu_restore_drill_` 数据库：`python ops/backup/restore_drill.py --database-url-file <migration-url-file> --dump <backup.dump> --temporary-database kichu_restore_drill_<timestamp>`。
- 恢复演练失败时保留 dump、manifest 与日志，不得自动覆盖生产库或 downgrade。

## 禁止事项

- 不要自动导入生产数据库或扫描默认的 SQLite/JSON 路径。
- 不要删除旧备份、SQLite WAL 文件或真实数据。
- 不要让 API/Worker 自动运行 Alembic、DDL 或 downgrade。
