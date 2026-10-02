# Worker Task Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复“刷新动态”和日历回填的执行边界，让网页只提交持久化任务，由 Worker 执行并准确报告结果。

**Architecture:** PostgreSQL 保存分析作业、互斥、租约和进度；Worker 唯一执行采集。UP 观测、6 类快照和 finalizing 状态原子提交，关联日历通过分析作业 ID 幂等提交。现有 API 保持兼容，页面从数据库恢复任务进度。

**Tech Stack:** Python >=3.12、Flask、SQLAlchemy 2.x、Alembic、PostgreSQL 16、React 18、Vitest、pytest；不增加运行服务或依赖。

**Spec:** `docs/superpowers/specs/2026-10-03-worker-task-boundaries-design.md`（2026-10-03 用户已批准）

## Global Constraints

- 在 `F:/作业工程库/guichuhub-worker-task-fix` 的 `codex/worker-task-boundaries` 实施；不修改原本地项目和 Docker 部署副本。
- 不修改观察名单，不开放公网网站，不复制或展示 Cookie/Token；不删除或重写既有观测批次。
- 不更换采集供应商，不调整现有每日四次 UP 观测时间，不新增 Redis/Celery 等服务。
- 状态为 `queued`、`running`、`finalizing`、`succeeded`、`partial`、`failed`；前三种为活动状态，后三种为终态。
- 租约 120 秒，独立心跳每 20 秒续约；任务最多领取 3 次；批次时间首次领取固定并在恢复时复用。
- API 在新任务表上仅有 SELECT/INSERT；只以 migration 角色执行 DDL 和必要的新表授权。
- 连续提交同一种回填范围至少间隔 60 秒，活动作业仍直接复用；不自动对全部历史失败作业补跑。
- 保留 `/api/up-trends/refresh`、`/api/up-trends/progress` 和 `task_id`、`total`、`current`、`current_up`、`eta_seconds`、`done` 字段。
- 所有任务历史保留；原始异常只进受保护日志，HTTP 不暴露 URL、SQL 参数或凭据。
- 测试数据库只能使用现有 fixture 创建的 `kichu_test_<uuid>` 临时库；不得把服务器生产 URL 注入 pytest。
- 每项先运行失败测试、最小实现、通过测试，再按明确文件清单提交；依赖安装使用已有 lockfile。
- 本机 Docker 引擎目前不可用；实施时先恢复测试环境，只创建测试容器，不启动、停止或重建用户现有 Compose 项目。环境失败不能冒充代码回归失败。

## Review Focus

1. Worker 租约在核心提交前过期：旧 token 不能提交任何观测数据（任务 2）。
2. finalizing 中断且日历已入队：恢复只关联原日历，不重新采集（任务 3、4）。
3. 手动与定时同时提交：跨数据库连接只存在一个活动分析作业（任务 2、5）。
4. 失败回填的显式重试遇到冷却时间：保留失败历史，返回 429 和明确等待时间，活动作业优先复用（任务 4）。
5. 页面刷新、网络中断或任务不存在：恢复持久化进度或结束加载并保留上次可用数据（任务 6）。

---

## 文件边界与共享类型

- 新建 `backend/storage/repositories/analysis_jobs.py`：作业持久化、领取、fencing、原子提交，不执行网络请求。
- 新建 `backend/jobs/up_analysis_worker.py`：分析消费者、独立续租、采集和 finalizing 恢复。
- 修改 `backend/jobs/up_trends_jobs.py`：删除内存任务字典和采集线程，仅保留兼容提交/查询入口。
- 修改 `backend/storage/models.py`、新增 `backend/alembic/versions/0003_up_analysis_jobs.py`：新增表、索引、权限；不改已有迁移。
- 修改 `backend/storage/repositories/business.py`：提取同会话写入助手，并修正现有日历去重；不全面重构大文件。
- 修改 `backend/storage/runtime.py`、`backend/tests/conftest.py`：无连接/DDL 的装配与测试清理。
- 修改 `backend/worker_entrypoint.py`、`backend/jobs/crawl_jobs.py`：唯一消费者入口，定时仅入队。
- 修改 `backend/jobs/calendar_jobs.py`、`backend/app.py`：纯提交、受控重试及兼容 HTTP。
- 修改 `frontend/src/components/UpTrends.jsx`、必要时 `frontend/src/utils/api.js`：持久化进度接管与可靠轮询。
- `Job` 为 dict，字段：`id: str`（UUID）、`status: str`、`requested_by: str`、`roster: list[dict]`、`progress: dict`、`result_summary: dict`、`error: dict | None`、`created_at/started_at/updated_at/finished_at: int | None`、`worker_id: str | None`、`lease_until: int | None`、`fencing_token/attempts: int`、`batch_ts: int | None`。
- `Claim` 使用同一 Job 结构；所有消费者写入显式传递 `job_id, worker_id, token, now`。丢失租约抛 `LostAnalysisLease`，调用方不得再次以旧 token 写入。
- `progress` 保留 total/current/current_up/eta_seconds；`result_summary` 仅保存行数、批次时间、calendar_job_id 和安全 warnings，不复制完整分析结果。

### Task 1: 增量任务表与最小权限

**Files:** 修改 `backend/storage/models.py`、`backend/tests/test_alembic.py`；新建 `backend/alembic/versions/0003_up_analysis_jobs.py`、`backend/tests/test_analysis_job_permissions.py`。

**Interfaces:** 产生 SQLAlchemy Table `up_analysis_jobs`，revision `0003_up_analysis_jobs`，父 revision 使用当前 0002 文件的实际 revision ID。活动状态部分唯一索引、状态 CHECK、JSONB 名单/进度/摘要；时间用整秒整数，与现有仓库一致。没有 API UPDATE/DELETE grant。

- [ ] 写失败测试：空库升级、0002 增量升级、单 head、真实测试角色权限；延用现有 Alembic fixture，仅在临时库内建立角色。
  ```python
  assert heads == ['0003_up_analysis_jobs']
  assert previous_observation_count == observation_count_after_upgrade
  assert api_permissions == {'select': True, 'insert': True, 'update': False, 'delete': False}
  assert worker_permissions['update'] is True
  assert api_can_insert_video_snapshots is False
  assert api_can_insert_calendar_videos is False
  ```
- [ ] 在 backend 执行 `uv run --extra dev pytest tests/test_alembic.py tests/test_analysis_job_permissions.py --no-cov`；确认失败原因是新增表/版本/授权缺失。
- [ ] 实现表与仅新增迁移；条件授权兼容测试环境角色不存在；按现有迁移习惯处理 downgrade，但发布流程禁止自动 downgrade。
- [ ] 重跑上述测试并验证已有 schema 与数据不受影响。
- [ ] 仅提交本任务四个文件：`feat: add durable UP analysis job schema`。

### Task 2: 作业互斥、租约与原子核心保存

**Files:** 新建 `backend/storage/repositories/analysis_jobs.py`、`backend/tests/test_analysis_job_repository.py`；修改 `backend/storage/repositories/business.py`、`backend/storage/runtime.py`、`backend/tests/conftest.py`、`backend/tests/test_postgres_runtime.py`。

**Interfaces:** `AnalysisJobRepository(sessions, business)`，方法：`enqueue(roster: list[dict], requested_by: str, now: int) -> tuple[dict, bool]`、`get(job_id: str) -> dict | None`、`active() -> dict | None`、`claim(worker_id: str, now: int, lease_seconds: int = 120) -> dict | None`、`renew(job_id: str, worker_id: str, token: int, now: int) -> bool`、`update_progress(job_id: str, worker_id: str, token: int, now: int, progress: dict) -> None`、`commit_core(job_id: str, worker_id: str, token: int, now: int, result: dict) -> dict`、`finish(job_id: str, worker_id: str, token: int, now: int, status: str, summary: dict, error: dict | None = None) -> None`。模块提供 `configure_analysis_repository(repository) -> None`、`get_analysis_repository() -> AnalysisJobRepository | None`；runtime 新增 `analysis_jobs` 成员。

业务仓库提取 `_write_up_observations(session, ts, observations, play_ranking, active_ranking) -> int` 和 `_write_snapshot_batch(session, ts, fields) -> int`，旧公开方法复用它们并保持现有返回值。`commit_core` 在同一事务内锁定、验证租约、写入两类数据并进入 finalizing。

- [ ] 建立 `analysis_repo` fixture 从 `postgres_runtime.analysis_jobs` 获取；编写并实际运行失败测试：两个独立连接并发 enqueue、重新装配后可读、超期 claim、更换 token、第三次耗尽、空名单拒绝、核心第二类写入失败回滚。
  ```python
  assert len({job['id'] for job, _ in concurrent_results}) == 1
  assert sum(created for _, created in concurrent_results) == 1
  assert recovered['fencing_token'] > first_claim['fencing_token']
  assert recovered['batch_ts'] == first_claim['batch_ts']
  assert core_counts_after_injected_failure == core_counts_before
  assert committed['status'] == 'finalizing'
  assert committed['result_summary']['video_obs_snapshot_fields'] == 6
  ```
- [ ] 执行 `uv run --extra dev pytest tests/test_analysis_job_repository.py tests/test_postgres_runtime.py --no-cov`，记录由缺失接口造成的失败。
- [ ] 使用固定资源名的事务 advisory lock 串行提交，部分唯一索引兜底；领取使用行锁与条件校验。旧 token、过期 lease、终态写入均拒绝；所有变更在短事务内，网络采集不持锁。首次 claim 固定 batch_ts；领取超过 3 次置 failed 并保留已有数据/摘要。
- [ ] 补充提交前刚过期的测试，断言 `LostAnalysisLease` 且没有任何新批次行；跑上述测试和 `tests/test_business_repository.py` 全通过。
- [ ] 提交明确文件清单：`feat: persist fenced analysis jobs and atomic observation batches`。

### Task 3: Worker 消费与 finalizing 恢复

**Files:** 新建 `backend/jobs/up_analysis_worker.py`、`backend/tests/test_up_analysis_worker.py`；修改 `backend/jobs/up_trends_jobs.py`、`backend/jobs/crawl_jobs.py`、`backend/worker_entrypoint.py`、`backend/tests/test_entrypoint_separation.py`。

**Interfaces:** `start_analysis(enabled_ups: list[dict], requested_by: str = 'system') -> str | None` 保持新建返回 ID、busy 返回 None；`get_running_task_id() -> str | None`、`get_progress(task_id: str) -> dict | None` 查询数据库。新增 `ensure_analysis_worker() -> None`、`run_analysis_once(worker_id: str) -> bool`；消费者轮询 2 秒、续租独立线程每 20 秒并可停止。分析 collector 沿用 `analyze_tracked_ups_with_progress(enabled_ups, progress_cb)`，只有 Worker 调用。

- [ ] 写并运行失败测试：提交不启动 Thread、不调用 collector；Worker 启动仅一次；mock collector 的进度写入数据库；核心写入错误 failed；后续日历提交异常 partial；不同实例恢复 finalizing 不调用 collector。
  ```python
  assert collector_calls_after_submit == []
  assert analysis_consumer_start_count == 1
  assert core_failure['status'] == 'failed' and core_failure['done'] is True
  assert calendar_failure['status'] == 'partial'
  assert recovered_calendar_id == original_calendar_id
  assert collector_calls_during_finalizing_recovery == []
  ```
- [ ] 执行 `uv run --extra dev pytest tests/test_up_analysis_worker.py tests/test_entrypoint_separation.py --no-cov` 并确认业务缺陷导致失败。
- [ ] 替换内存适配层，Worker 显式装配消费者；定时提交传 `requested_by=f'system:{trigger}'`。running 采集与 finalizing 恢复分支分离，丢 lease 停止提交。错误映射为固定 code/message，禁止返回 str(exception)。核心保存后提交 days=7 日历，使用 `analysis:<job_id>` 恒定去重键，成功只表示分析保存且后续已入队，不表示日历完成。
- [ ] 用可控制 Event/时钟的测试阻塞 collector 超过一个心跳周期，证明续租不依赖进度回调；消费者退出清理续租线程。重跑本任务测试通过。
- [ ] 提交：`fix: run durable UP analysis exclusively in worker`。

### Task 4: 日历纯提交与受控重试

**Files:** 修改 `backend/jobs/calendar_jobs.py`、`backend/storage/repositories/business.py`、`backend/app.py`、`backend/tests/test_calendar_api.py`、`backend/tests/test_calendar_reliability.py`、`backend/tests/test_calendar_dedup.py`；新建 `backend/tests/test_calendar_submission_boundaries.py`。

**Interfaces:** `enqueue_calendar_job` 保持原参数，添加 `parent_job_id: str | None = None, dedupe_forever: bool = False, cooldown_seconds: int = 0`；仓库沿用 **payload 参数。`CalendarSubmissionCooldown(retry_after: int)` 表示冷却；新增 `enqueue_manual_calendar_job(...) -> tuple[dict, bool]` 为管理员提交设置标准范围键（mode/days/year/排序 mids）和 60 秒冷却。`retry_calendar_job` 返回原 tuple，重试只选 failed/partial items 并传 parent_job_id。

- [ ] 写失败测试且不再用空实现掩盖隐式启动：将 `ensure_calendar_worker` 替换成调用即失败的 spy，覆盖网页回填、名单基线提交、分析后续与定时入队。测试 failed/partial 不挡新提交、成功窗口复用、相同分析 ID 永久复用、重试父任务保留和 60 秒冷却。
  ```python
  assert consumer_start_calls == []
  assert retry['id'] != failed['id'] and retry['parent_job_id'] == failed['id']
  assert get_calendar_job(failed['id'])['status'] == 'failed'
  assert followup_again['id'] == followup['id']
  assert too_soon.status_code == 429 and too_soon.json['retry_after'] > 0
  assert active_again['id'] == active['id']
  ```
- [ ] 执行 `uv run --extra dev pytest tests/test_calendar_submission_boundaries.py tests/test_calendar_api.py tests/test_calendar_dedup.py tests/test_calendar_reliability.py --no-cov` 确認失败。
- [ ] 删除 enqueue 隐式启动，唯一启动位置留在 Worker。数据库范围锁内依次检查恒定分析键、活动作业、成功时间窗口、管理员冷却、新建；failed/partial 仅参与冷却而不被当成功复用。retry 关联父任务，活动重试返回 409 + busy + job_id；无可重试项保持既有友好错误。HTTP 429 包含 Retry-After 和安全提示。
- [ ] 固定 now 测试相隔 59/60 秒、乱序重复 mids 同范围、两个连接同时提交；跑本任务测试与 `tests/test_calendar_backfill.py` 全通过。
- [ ] 提交：`fix: isolate calendar submission and allow controlled retries`。

### Task 5: API 兼容、授权与可恢复状态

**Files:** 修改 `backend/app.py`；新建 `backend/tests/test_up_analysis_api.py`；必要时修改现有依赖内存任务的测试（先通过 rg 精确定位，只调整本次行为断言）。

**Interfaces:** refresh 首次成功保持原 HTTP 状态与 task_id/total；busy 为 409 + busy/task_id。progress 在原 data 内增加 status、error、warnings、calendar_job_id、worker_unavailable；done 仅终态为真。配置检查原响应增加 active_task_id。使用现有 worker heartbeat 读接口标记 Worker 不可用，不虚构进度，也不据此擅自失败任务。结果保持现有 analysis 数据库读路径；不新增完整结果 JSON。

- [ ] 写并运行失败测试：管理员提交，访客拒绝；API 使用真实 API 测试角色提交而不需要结果表写权限；active/check/progress 跨装配保持一致；缺失 task_id 400、未知任务 404；空名单 400；敏感异常不泄漏。
  ```python
  assert busy.status_code == 409 and busy.json['task_id'] == first.json['task_id']
  assert check.json['active_task_id'] == first.json['task_id']
  assert progress.json['data']['status'] == 'queued'
  assert progress.json['data']['done'] is False
  assert secret_marker not in failed_response.get_data(as_text=True)
  assert unauthorized.status_code in (401, 403)
  ```
- [ ] 执行 `uv run --extra dev pytest tests/test_up_analysis_api.py tests/test_analysis_job_permissions.py --no-cov`，确认目标接口缺失/行为失败。
- [ ] 更新路由使用持久化提交、actor 与安全状态，保持管理员鉴权；task ID 校验不得把非法 UUID 变成 500。保留所有已有 JSON 字段语义，仅新增明确状态。
- [ ] 重跑测试通过，并在仅测试数据库的 Flask client 中验证两次提交不触发采集、定时提交复用同 ID。
- [ ] 提交：`fix: expose recoverable analysis task state through API`。

### Task 6: 页面接管与明确失败反馈

**Files:** 修改 `frontend/src/components/UpTrends.jsx`、必要时 `frontend/src/utils/api.js`；新建 `frontend/src/components/UpTrends.jobs.test.jsx`；保留并运行 `frontend/src/components/UpTrends.surface.test.jsx`、`frontend/src/utils/api.test.js`。

**Interfaces:** queued/running/finalizing 轮询 800ms；成功/partial 通过 `api.upTrendsAnalysis()` 读取已保存结果，不依赖 progress.result。partial 显示已保存与后续失败提醒；failed 保留旧数据。初始化 check.active_task_id 与 HTTP 409 接管同一作业。

- [ ] 用现有 Testing Library mocking 风格与 fake timers 写并运行失败测试：各状态、刷新页面接管、409、unknown task、网络失败和卸载取消轮询；记录原数据可见、状态文案与调用次数。
  ```javascript
  expect(screen.getByText('等待 Worker 执行')).toBeVisible()
  expect(screen.getByText('观测已保存，日历任务提交失败')).toBeVisible()
  expect(screen.getByText('上次可用数据')).toBeVisible()
  expect(api.upTrendsProgress).toHaveBeenCalledWith(activeTaskId)
  expect(progressCallsAfterUnmount).toBe(progressCallsAtUnmount)
  ```
- [ ] 在 frontend 执行 `npm test -- src/components/UpTrends.jobs.test.jsx`，确认现有页面状态行为失败。
- [ ] 实现状态分支与可取消轮询，不改变图表布局。网络失败指数退避 1/2/4 秒、最多连续 3 次后结束刷新并提示重新连接；任务不存在立即结束刷新。Worker 不可用显示等待/警告并停止自动轮询，提供重新连接按钮，不能显示无期限“启动中”。旧响应用轮询 generation/ref 拒绝，卸载清除 timer。
- [ ] 执行 `npm test -- src/components/UpTrends.jobs.test.jsx src/components/UpTrends.surface.test.jsx src/utils/api.test.js` 和 `npm run build` 全通过；在临时本地预览中交互验证队列、成功、partial、失败、重进页面和窄屏；不调用生产抓取作视觉测试。
- [ ] 提交：`fix: resume UP task progress and show partial failures`。

### Task 7: 全量验证与受保护发布验收

**Files:** 新建 `docs/operations/worker-task-boundary-release.md`；必要时修改 `.github/workflows/backend.yml` 使已新增测试自然纳入现有 suite，不引入生产凭据；更新本计划勾选状态。

**Interfaces:** 发布文档记录目标提交、镜像身份、迁移 head、私有管理入口、停写/备份/恢复验证和业务验收证据。发布不执行数据库 downgrade/恢复覆盖。

- [ ] 全量运行：backend `uv run --extra dev pytest --no-cov`；frontend `npm test`、`npm run build`；检查 Alembic 单 head 和生产 Compose 配置渲染（测试仅使用既有 ci-test release identity 占位值）。保留失败原始证据，修复回归再运行，不用跳过测试作为成功。
- [ ] 对照设计逐条自审并做一次全分支独立审查；如选择代理执行按技能分任务审查，若选择直接执行只在末尾审查。修复审查项、重跑受影响测试，再提交文档及验收记录。
- [ ] 发布前核验服务器代码/镜像、正在执行任务、DB revision、观察名单、最新观测和日历状态。等待任务结束；在明确维护窗口停止 API/Worker 写者，完成受保护 PostgreSQL custom dump 并在独立临时库恢复验证。若无法验证备份，停止发布并报告原因。
- [ ] 只发布核验后的修复提交/镜像，migration 角色显式升级到 0003，重启新 API/Worker；不开放公网入口，不把生产 URL 写入日志/仓库。迁移后失败优先前向修复，不自动回退数据库。
- [ ] 私有页面点击一次刷新，核验实际 Worker 执行、139 位启用名单不变、批次 UP 记录与 6 类快照一致；提交一次近 7 天日历任务并核验终态和实际数据。若实时名单基线变化，先解释差异，不能机械以 139 为预期覆盖名单。
- [ ] 记录实际测试数量、提交、迁移和网页/数据库证据后才报告“修复并部署”；如果只完成本地，明确未部署。

## 自审与执行选择

本计划覆盖设计第 1–9 节；5 项 Review Focus 均落到对应失败测试。共享接口集中定义，后续任务沿用；不添加并行认证/持久化系统。真实角色与 PostgreSQL 验证不可用 mock 替代，服务器验收不能由构建成功替代。

推荐直接执行（Native）：队列、事务、租约和 API 的接口紧密相关，由同一执行者逐项落实更利于保持一致；末尾再做独立审查。另一选项为分任务代理执行（Subagent-driven），每项有独立实现与审查，消耗更多上下文。

状态：实施计划已编写并自审，等待用户审核及执行方式选择；尚未修改产品代码或发布。
