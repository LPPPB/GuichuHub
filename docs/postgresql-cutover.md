# PostgreSQL 首次切换 Runbook

本流程只针对已验证的 V3 发布。不要在本流程中访问未明确提供的数据库、快照或备份；SQLite 和 JSON 快照仅作为只读归档与一次性离线导入输入。

## 首次切换

1. 进入维护窗口，停止 API 与 Worker，确认没有写入请求。
2. 创建并验证业务 SQLite、认证 SQLite、`inspiration_db.json`、`tracked_ups.json` 的一致快照；保留原文件、`-wal`、`-shm`，不要删除或就地转换。
3. 将四个快照复制到受保护的离线目录，记录 SHA-256；启动一个空 PostgreSQL 16 实例，其数据目录必须在 Git 检出目录外。
4. 为 PostgreSQL 超级用户、API、Worker、migration、backup 角色各创建独立 Docker secret；URL 文件只可由相应服务读取。
5. 执行一次性维护 migration：`docker compose --env-file /srv/kichu/config/production.env -f compose.prod.yml --profile maintenance run --rm migrate`。
6. 用明确传入的四个离线快照执行 `backend/scripts/import_sqlite_snapshot.py`，并将 reconciliation report 写到受保护目录。
7. 审核报告：所有实体源/目标行数、关键主键、最新观测时间、管理员、会话、credential handoff、收藏、tracked UP 和 dashboard state 必须有效；`valid` 必须为 `true`。
8. 将运行配置切换到 PostgreSQL URL Docker secrets；API、Worker 均不得有 SQLite/JSON 状态挂载。
9. 再运行 migrate 服务；它应无 DDL 操作且确认 revision 等于唯一 Alembic head。
10. 启动 PostgreSQL、API、Worker、Frontend、Caddy；检查 `/api/health/live`、`/api/health/ready`、Worker heartbeat、核心 API 与日志。
11. 将四份 SQLite/JSON 快照以只读方式至少保存 **90 天**。切换后不再将其作为运行态存储。

## 后续数据库发布

1. 代码、SQLAlchemy model、唯一 Alembic revision、必要的可恢复 backfill 与测试必须一起提交。
2. CI 必须检查单 head、空库升级、旧快照导入、健康检查、完整后端测试及 Compose config。
3. 创建并验证 PostgreSQL 自定义格式备份。
4. 停止写入服务。
5. 执行 `alembic upgrade head`，只使用 migration 角色。
6. 如有需要，运行可恢复 backfill；它将进度保存在 `app.backfill_progress`。
7. 启动新版本并检查 readiness、heartbeat 和关键业务 API。
8. 故障优先前向修复，**禁止自动 downgrade**。只有经确认的维护窗口才能从发布前 PostgreSQL 备份恢复。

## 禁止事项

- 不要自动导入生产数据库或扫描默认的 SQLite/JSON 路径。
- 不要删除旧备份、SQLite WAL 文件或真实数据。
- 不要让 API/Worker 自动运行 Alembic、DDL 或 downgrade。
