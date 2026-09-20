# V2 到 V3 迁移

V2 原目录及其审计副本保持本地、不可推送。V3 采用新的 Git 根历史，不导入 V2 的运行态文件或历史 blob。

迁移时只使用操作员明确指定的离线快照。在停机窗口用 SQLite backup API 创建并验证业务库、认证库的一致副本；将旧 dashboard 和可编辑的弹幕/梗/标签词表无损合并为 dashboard envelope，再与 `tracked_ups.json` 一起交给一次性导入器。V3 不会自动扫描 V2 路径，也不会把这些副本挂载为运行态存储。

Cookie、token、日志、浏览器会话和旧备份不自动迁移；采集 Cookie 应通过 V3 的受控登录流程重新建立。导入后 PostgreSQL 是唯一事实源，源快照只读保留至少 90 天，完整操作顺序见 [PostgreSQL 首次切换 Runbook](postgresql-cutover.md)。

切换前保留 V2 可运行副本和 V3 PostgreSQL 备份。切换后验证 liveness/readiness、Worker heartbeat、看板数据与管理员登录。故障优先前向修复；禁止自动数据库 downgrade，任何恢复都需独立确认和维护窗口。
