# Worker 任务边界修复发布记录

日期：2026-10-03，北京时间。实施目录：`F:/作业工程库/guichuhub-worker-task-fix`，分支：`codex/worker-task-boundaries`，基线：`cdbaeca`。

## 发布门槛

必须先通过后端全量测试、前端全量测试/构建、Compose 渲染与单一 Alembic head 检查。执行一次独立只读审查，重要发现通过失败测试再修复；不能以构建成功代替业务验收。

只允许发布 Git 中的已验证提交。当前任务没有新的 GitHub 推送授权，因此若发布采用 Git bundle，只将修复提交传到用户已授权的腾讯云服务器；不推送共享分支、不创建新 PR。服务器保留旧提交与镜像，运行态不在仓库内，不整目录上传。

## 维护顺序

1. 核验 `/srv/guichuhub` 的 Git 身份和容器镜像。生产配置只使用 `/srv/kichu/config/production.env`；Cookie、URL secret、Token 不输出、不下载。
2. 记录启用名单摘要、现存观测/快照/日历数量和最新批次；确认没有运行中的 UP/日历任务。仅在准备好镜像后暂停 API/Worker 写者，不停止 PostgreSQL。
3. 使用现有维护 backup 服务生成 PostgreSQL custom dump、SHA-256 和 manifest。验证校验和、catalog，并以 migration 角色在新建 `kichu_restore_drill_*` 临时库恢复；核验 revision、行数及应用仓库读取。失败立即停止迁移，保留日志和备份。
4. 仅以维护 migrate 服务显式升级到 `0003_up_analysis_jobs`。核验 API 新表 SELECT/INSERT，不能 UPDATE/DELETE 或写视频快照/日历结果；Worker 有新表 UPDATE。
5. 仅启动新 API、Worker、Frontend；不启动 Caddy、不绑定公网网站端口。管理仍通过现有 SSH 私有入口。
6. 私有网页提交一次 UP 观测并验证任务终态、名单不变、UP 批次及六类快照；网页提交一次最近七天日历回填并验证真实终态。旧失败任务不批量重试、不重写历史。

## 回退边界

迁移前可恢复旧镜像；迁移后旧代码严格 readiness head 不匹配，不能声称简单镜像回退可用。失败时保留新数据与日志，优先前向修复。数据库恢复覆盖、downgrade、名单修改和公网开放均需另行授权。

## 当前核验

发布前服务器代码 `cdbaeca` / `v3.0.1`，schema `0002_recovery_and_identity`。观察名单 204 位，其中 139 位启用；名单 MD5 `72ede6e2f36784623b3de3154c25d5c0`。

最新核心批次 epoch `1790951601`：139 条 UP 观测，六类快照为 `all_videos/content_types/hot_videos/keyword_cloud/pool_summary/timeline`。历史计数：UP 观测 17141，快照文档 737，日历视频 9485；日历活动任务 0。

旧镜像：API `sha256:2f1ef51d630410a3f039d5ec9f8781a158db827518cdd58dad5a7bd3cde842bd`；Worker `sha256:dae410a1cc0e5f8cd669568629763fcdf2a2f852bfa79afeb0a915b6a83d89c0`；Frontend `sha256:37d3df8f93f1c21dc3f789b418652c88ea789e0806f86e1ad62b68d877f12f91`。

发布和真实业务验收尚未完成；后续结果必须补充在本节，不能将以上基线当作新版本验收。

最终本地验证：后端 **623 passed**，前端 **174 passed**，生产构建通过；开发/生产 Compose 配置渲染通过，Alembic 单 head 为 `0003_up_analysis_jobs`。隔离真实页面覆盖所有分析状态、重进恢复与断线重连；390×844 视口无新增横向溢出。保留现有 ECharts 大包警告和既有依赖审计问题，不在此修复中升级依赖。

## 审查修复与裁定

一次 fresh-context 独立审查发现四项重要问题：数据库等待期间租约过期、真实采集器失败被转换为零值、日历逐 UP 异常原文被保存、重试页缺少 429 秒数与 409 接管。均先补失败测试，再在同一修复 pass 中处理。

轻微项暂缓：`crawl_jobs.py` 注释仍描述已删除的内存锁，实际逻辑已使用数据库队列。

实施裁定：使用本机 Git Bash 运行技能脚本；脚本受沙箱限制时通过正常审批运行；同秒批次分配单调时间，极快重复提交可能领先数秒；清理测试装配残留避免用虚构数据库地址；已删除内存实现的 GC/锁测试改为持久历史测试；日历范围键在仓库统一计算；Worker 可用性沿用 120 秒心跳阈值而非独立消费者健康探针；三次连续轮询失败使用 1/2 秒退避后停止，不增加第四次；完整观测严格传播采集失败，而其他卡片旧降级语义保留；fresh clock 在合成 epoch 测试中注入，生产使用实时钟；日历未知错误归一为安全提示，精确原因只在日志中；日历原有消费者租约机制不在本次做全面 fencing 重构；服务器结果仍须以实际备份恢复和网页/数据库证据判断。
