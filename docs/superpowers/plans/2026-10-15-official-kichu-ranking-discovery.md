# GuichuHub Official Ranking and Independent Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 鬼畜榜遵循官方顺序，潜力榜保留独立发现和真实统计筛选，并通过有预算的旁路验证安全切换。

**Architecture:** 单独采集并保存官方榜快照；多源发现和补全共享一轮网络结果，生成独立新版潜力快照。PostgreSQL 保存当前快照、尝试和待补集合，统一读取器向旧数组接口投影；跨进程采集锁和版本校验保护发布，保留旧规则结果供旁路和回滚。

**Tech Stack:** Python >=3.12、Flask、requests、APScheduler 3.x、SQLAlchemy 2.x、psycopg 3、PostgreSQL 16；React 18、Vite、Vitest、Playwright Core；pytest、uv、npm。

**Spec:** [已评审设计规格](../specs/2026-10-15-official-kichu-ranking-discovery-design.md)。执行者先读规格再读本计划，本文不授权生产发布。

## Global Constraints

- 工作区：`F:/作业工程库/GuichuHub开发工作区/guichuhub-favicon-seo`；分支：`codex/official-rank-discovery-design-20261015`；产品基准：`ae99d79`，规格提交：`db7d62d`。实施前核验远端是否前进，保留已有文档和主目录状态；有冲突先解决设计适配，不能重置用户改动。
- 官方源固定 `ranking/v2?rid=1007&type=all`；保存完整列表、展示最多 20、首页前三；顺序等于上游位置，不受分类或潜力门槛裁剪。
- `COLLECTION_RULES_MODE=legacy/shadow/official`，默认 `shadow`；API 和 Worker 生效模式一致。两类新结果都先旁路，旧公开结果及旧内部字段保留。
- 潜力硬门槛默认 `[1500,1000000]` 播放、互动质量至少 10、21 天内且不在未来；不自动放宽；完整真实核心统计先补齐再筛选。保留评分权重和批内 Min-Max、`None ≠ 0`、熔断及历史平滑。
- 新父分区 1007 优先；父分区缺失才使用已核验 `{2063:1007}`；全无新字段才回退旧白名单。保留旧 `tid`，不更新历史分类/参考 SQL 来伪造覆盖。
- 每轮：热门 15 页、鬼畜搜索 16 页、音乐/搞笑各 7 页、种子合计 8 页、全站榜和新投稿各 1 次，发现总闸 60；候选/待补各最多 400，详情/潜力同接各 160，标签 64；失败和成功均缓存去重。逻辑请求与 HTTP 尝试分别计数。
- 新官方任务只在 Worker，每小时北京时间 `:05/:35`；超过 60 分钟标过期，超过 24 小时明确历史榜；单次最多 2 次 HTTP 尝试，412/429/-352 不紧密重试；锁忙最多延后 5 分钟一次。
- PostgreSQL JSONB 追加当前状态，无新表、DDL、migration、历史重算或回填；API 不新增采集写权限，UP/日历流程不重构。
- 不改生产 SQLite/WAL/SHM、卷、环境文件、Cookie/Token、敏感文件和无关服务；不执行 `docker compose down -v`，不上传整个目录。
- 每个产品任务必须完成失败测试、最小实现、通过测试、独立提交；下文命令是未来执行步骤，本计划交付不宣称已跑过。

## Review Focus

- 数字字段包含 `null`、负数、布尔、NaN 或非法字符串：未知应保留未知，不能变成有效零统计；任务 1、6 测试。
- HTTP 200 返回 HTML、标量或错误 JSON：不能覆盖官方快照，重试总次数不能叠加成四次；任务 2 测试。
- 采集连接断开后连接池重连、异常退出再归还：旧执行者不能发布，池内不能遗留会话锁；任务 3、4 测试。
- 两次尝试在同一秒开始且旧结果迟到：新的成功快照/最近尝试不能被旧结果覆盖；任务 4 测试。
- 同一 BV 跨源携带不同时间的部分统计、并被两套规则共用：不能拼成假完整数据，不能互相覆盖分数或重复计热梗；任务 5、6、7 测试。

## 文件与依赖地图

| 文件 | 职责 | 任务 |
| --- | --- | --- |
| `backend/services/collection_contracts.py`（新） | 分类、真实统计组、策略及结果类型；无网络/数据库副作用 | 1 |
| `backend/collectors/official_ranking.py`（新） | 官方榜请求、保序解析和响应校验 | 2 |
| `backend/jobs/collection_lock.py`（新） | PostgreSQL 会话采集锁及持锁连接生命周期 | 3 |
| `backend/storage/repositories/collection_state.py`（新） | 官方/潜力当前快照、尝试、待补的专用发布 | 4 |
| `backend/storage/repositories/state.py`、`backend/storage/runtime.py`、`backend/storage/database.py`、`backend/storage/cache.py` | 持锁连接事务适配、依赖注入、版本及字段保护 | 3、4、7 |
| `backend/collectors/collection_context.py`（新） | 一轮请求缓存、预算、逻辑/HTTP 计数 | 5 |
| `backend/collectors/discovery.py`（新） | 来源采样、合并、待补轮询和派生样本 | 5 |
| `backend/services/potential_selection.py`（新） | 真实补全后的严格潜力筛选和评分 | 6 |
| `backend/collectors/bilibili.py`、`backend/collectors/__init__.py` | 沿用低层能力，接入共享上下文、双结果及派生去重，不做全文件重写 | 2、5、7 |
| `backend/jobs/official_ranking_jobs.py`（新）、`backend/jobs/crawl_jobs.py`、`backend/jobs/scheduler.py`、`backend/worker_entrypoint.py` | 官方周期、startup、全量/实时/观测互斥与登记 | 8 |
| `backend/services/collection_views.py`（新）、`backend/app.py` | 统一 API 投影、缓存和快照元信息 | 9 |
| `backend/config.py`、`.env.example`、`compose.dev.yml`、`compose.prod.yml` | 策略配置和 API/Worker 同值传递；仅修改仓库模板 | 1、8 |
| `frontend/src/App.jsx`、`frontend/src/components/VideoCard.jsx`、`frontend/src/components/RankingSource.jsx`（新） | 来源/时间/失败提示和显式名次，不更换布局 | 10 |
| `backend/tests/collection_samples.py`（新）、各任务测试文件 | 固定脱敏样本与结果/副作用断言 | 1—11 |
| `frontend/scripts/verify-ranking-layout.mjs`、`.github/workflows/backend.yml`、`docs/collection-rules-rollout.md`（新） | 离线验收、CI 和发布/回滚清单 | 11 |

依赖顺序：1 → 2/3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11。2 与 3 接口独立，可顺序执行，无需为节省时间自动并行派发。

## 验证环境和测试隔离

后端命令在 `backend/` 执行，统一前缀 `uv run --extra dev pytest --no-cov -q`；前端命令在 `frontend/` 执行。使用仓库锁文件，按需 `uv sync --extra dev --frozen`、`npm ci`，不更换版本或引入依赖。

数据库测试只用 `tests/conftest.py` 中的 `postgres_runtime/clean_postgres_data`：fixture 启动专属 `postgres:16-alpine`、随机本机端口、临时测试库。其 TRUNCATE/DROP/stop 仅作用于该测试 fixture 创建的资源；禁止将生产 URL、用户现有开发数据库或 Compose 数据卷接入 fixture。Docker 不可用时保留该项未验证状态，不能将 mock 结果写成真实 PostgreSQL 通过。

实施首次基线使用明确文件清单：

```powershell
uv run --extra dev pytest --no-cov -q tests/test_bilibili_collect.py tests/test_bilibili_parse.py tests/test_batch_scorer.py tests/test_radar_provenance.py tests/test_online_breaker.py
```

先确认这些文件无导入时联网。任务 1 处理已知手动脚本，任务 11 审核其他测试收集路径后才运行受控广泛回归，不直接将现有全库 pytest 当安全基线。基线失败先区分环境与已有失败，记录证据，不静默重写期望。

## Task 1：建立纯契约、策略和不联网的固定样本

**Files:** Create `backend/services/collection_contracts.py`、`backend/tests/collection_samples.py`、`backend/tests/test_collection_contracts.py`；Modify `backend/config.py`、`backend/tests/test_kichu_rank.py`、`backend/tests/test_ranking.py`。

**Interfaces:**
- `normalize_category(raw: dict) -> dict | None`：从原始 `tidv2/tnamev2/pid_v2/pid_name_v2` 生成 `category_v2={tid,tname,pid,pid_name}`。
- `classify_kichu(video: dict) -> Literal['eligible','ineligible','unknown']`：读取归一分类，规则按规格。
- `core_stat_sample(raw: dict, *, endpoint: str, observed_at: int) -> StatSample | None`：接收带 `stat` 的原始对象，返回完整组；`StatSample` 包含归一核心指标 `metrics`、`endpoint`、`observed_at`。
- `load_collection_policy(env: Mapping[str,str]) -> CollectionPolicy` 位于 `config.py`；冻结策略包含 mode、规格全部预算、门槛、刷新与过期值。
- 契约定义 `OfficialFetchResult(snapshot:dict|None, attempt:dict)`、`DiscoveryResult(lanes:dict, derived:dict, pending:list, attempt:dict)`、`PotentialResult(snapshot:dict|None, pending:list, attempt:dict)`；后续任务沿用这些字段。lanes固定键为 `official/latest/search/newest/popular`，derived固定键为 `kichu/music/funny/popular`，每个值都是归一视频列表。
- 样本助手 `raw_video(bvid: str, **overrides) -> dict` 与 `rank_response(items: list[dict]) -> dict` 使用合成标题、固定时间、完整 stat；不得包含 Cookie/真实用户私密信息。

- [ ] **Step 1 — 写失败测试。** `test_collection_contracts.py` 中断言：
  - `test_category_v2_parent_wins`：旧 `tid=219` + 新父 1007 为 eligible；旧 22 + 新父 1009 为 ineligible；仅子 2063 为 eligible；未知新子为 unknown；无新字段旧 22 为 eligible。
  - `test_complete_stats_preserve_zero_and_reject_invalid`：七项真实零值返回组；逐项缺失、负数、布尔、NaN、`'bad'` 返回 None；数字整数字符串允许归一，旧估算字段不能构成组。
  - `test_policy_defaults_and_limits`：默认 shadow、400/160/64/60、刷新 1800 秒/过期 3600 秒；未知模式、负预算、ordinary observe limit<50 在新版模式拒绝。
  ```python
  # test_category_v2_parent_wins
  assert classify_kichu({'tid': 219, 'category_v2': {'pid': 1007}}) == 'eligible'
  assert classify_kichu({'tid': 22, 'category_v2': {'pid': 1009}}) == 'ineligible'
  assert classify_kichu({'tid': 22, 'category_v2': {'tid': 9999}}) == 'unknown'
  ```
- [ ] **Step 2 — 运行该文件，确认上述新行为失败。** 命令前缀加 `tests/test_collection_contracts.py`；期望缺少新契约或断言失败，不能由网络/数据库错误代替。
- [ ] **Step 3 — 实现纯函数、冻结策略和助手；手动采集脚本改为 `main()` + `if __name__ == '__main__'`，消除导入副作用。** 不改手动脚本的业务含义；不安装产品新依赖。增加试图调用 HTTP 就失败的收集验证，确保导入这两个脚本时请求次数为 0。
- [ ] **Step 4 — 同命令通过，再执行上述明确基线。** 期望新断言全部通过、两脚本收集零 HTTP；现有通过基线无新增失败。
- [ ] **Step 5 — 仅暂存本任务文件，提交 `feat: define collection contracts and safe test fixtures`。** 后续各任务也仅暂存 Files 中实际变更文件，避免 `git add .`。

## Task 2：新增保序官方榜采集器

**Files:** Create `backend/collectors/official_ranking.py`、`backend/tests/test_official_ranking.py`；Modify `backend/collectors/bilibili.py` 的过时接口注释，保持旧函数默认调用兼容。

**Interfaces:** Consumes 任务 1 类型/归一函数；Produces `fetch_official_ranking(*, request_get: Callable, headers: dict, now: Callable, pause: Callable, attempt_id: str) -> OfficialFetchResult`。生产请求函数由任务 8 注入；此任务不启动任何采集任务。

- [ ] **Step 1 — 写失败测试。** `test_order_is_source_position_not_views` 使用三条有效 BV，播放 `[1,3000000,100]`，旧 tid `[219,138,216]`，断言输出 BV 顺序不变、`official_rank=[1,2,3]`、请求只有 `rid=1007,type=all`。参数化覆盖空榜、93/100 条、前 20 内缺失/重复、20 外少量缺失、有效比例<90%、缺可选字段、错误 code。
  ```python
  # test_order_is_source_position_not_views: result 为注入固定响应的调用结果
  assert [v['bvid'] for v in result.snapshot['items']] == input_bvids
  assert [v['official_rank'] for v in result.snapshot['items']] == [1, 2, 3]
  assert requested_params == {'rid': 1007, 'type': 'all'}
  ```
- [ ] **Step 2 — 运行 `tests/test_official_ranking.py`，确认新采集契约失败。** 新模块尚未接到 Worker，不用实时网络证明失败。
- [ ] **Step 3 — 实现受控请求与解析。** timeout=10 秒，重试只针对超时/连接/5xx，最多两次 HTTP 尝试；412/429/-352/认证失败不立即再试；HTTP 200 HTML、非对象 JSON、`data/list` 类型错误标 invalid。保留 source_count、原始名次、异常位置和真实指标时间；不为每条补详情/标签。
- [ ] **Step 4 — 同文件通过。** `test_http_200_html_does_not_become_empty_success` 和 `test_retry_budget_is_total_two` 断言 error/invalid 与 empty 分开、实际 HTTP 次数≤2、未隐式叠加 `safe_get` 重试；未知指标不估算。
- [ ] **Step 5 — 提交 `feat: collect current official kichu ranking in source order`。**

## Task 3：实现跨进程采集锁和连接生命周期

**Files:** Create `backend/jobs/collection_lock.py`、`backend/tests/test_collection_lock.py`；Modify `backend/storage/runtime.py`、`backend/tests/conftest.py` 的新依赖清理。

**Interfaces:** `CollectionLock(engine)`；`try_acquire(*, trigger: str) -> CollectionGuard | None`。`CollectionGuard` 提供 `connection`、`assert_held() -> None`、`release() -> None` 以及 `publication_connection()` 短事务上下文；`CollectionLockLost` 为稳定异常。新增 configure/get provider，runtime 显式安装，fixture 收尾卸载。

- [ ] **Step 1 — 写失败测试。** 两个独立引擎连接争用固定键 `0x4748434F4C4C0001`：第一连接拿到、第二返回 None；第一释放后第二可拿到。检查 `release` 重复调用安全、异常后连接池无遗留锁、网络阶段连接不保持数据库事务。
  ```python
  # test_two_sessions_exclude_each_other: first/second 为两个独立连接工厂的锁对象
  guard = first.try_acquire(trigger='official')
  assert guard is not None
  assert second.try_acquire(trigger='manual') is None
  assert not guard.connection.in_transaction()
  ```
- [ ] **Step 2 — 运行 `tests/test_collection_lock.py`，确认新锁测试失败。** 使用专属临时 PostgreSQL，不用现有服务做锁实验。
- [ ] **Step 3 — 实现会话级锁。** 非阻塞 `pg_try_advisory_lock`；领取后提交短事务，长网络阶段不持有事务。记录驱动连接身份，失联后该 guard 永久失效，不自动换连接/重新领取继续发布；异常时释放或丢弃失效连接，不能把带锁连接归还池。
- [ ] **Step 4 — 同文件通过。** `test_disconnected_guard_cannot_publish_on_reconnected_pool` 断言旧 guard 抛 CollectionLockLost、不能用新连接提交；`test_exception_returns_unlocked_connection` 在真实池上证明下一执行者可拿锁。
- [ ] **Step 5 — 提交 `fix: coordinate collection across API and worker processes`。** 此时尚未替换旧入口，待任务 8 一次接齐。

## Task 4：专用快照发布、元信息登记和原子回退

**Files:** Create `backend/storage/repositories/collection_state.py`、`backend/tests/test_collection_state.py`；Modify `backend/storage/repositories/state.py`、`backend/storage/repositories/business.py`、`backend/storage/runtime.py`、`backend/storage/cache.py`、`backend/storage/database.py`。

**Interfaces:** `CollectionStateRepository(state, business)`；`publish_official(result: OfficialFetchResult, *, guard: CollectionGuard) -> dict`；`publish_generation(data: dict, result: PotentialResult, *, guard: CollectionGuard, mode: str) -> dict`。`StateRepository.update_dashboard(..., connection=None)` 支持沿用持锁连接的短事务，旧调用默认不变。新增 `BusinessRepository.register_video_metadata(video: dict, *, new_tier: str) -> None`：不写观测、不重置已有 first_seen/tier。普通 `persist_data` 拒绝更新专用快照键。

- [ ] **Step 1 — 写失败测试。** 成功完整快照和尝试整体可见；错误/空榜仅改尝试，不改旧成功时间/编号；无旧官方时不使用旧 `kichu_rank`；普通全量状态合并不能注入专用字段。新 BV 登记后没有观测，旧 BV first_seen/tier 不变；登记失败不发布。
  ```python
  # test_failed_attempt_preserves_success: before/after 为失败发布前后的持久payload
  assert after['official_kichu_snapshot'] == before['official_kichu_snapshot']
  assert after['last_updated'] == before['last_updated']
  assert after['official_kichu_attempt']['outcome'] == 'error'
  assert after_version > before_version
  ```
- [ ] **Step 2 — 运行 `tests/test_collection_state.py tests/test_state_repository.py tests/test_business_repository.py`，确认新断言失败并保留旧行为基线。
- [ ] **Step 3 — 实现字段分组发布。** 官方和潜力的成功、失败更新分别处理，不套用逐字段真值合并；错误状态写入只推进状态版本，不修改内容 last_updated。成功空潜力榜可以覆盖旧新版潜力榜。元信息登记可先完成，最终快照必须在 guard 持有连接的短事务中行锁提交。
  - 同秒尝试的顺序具体化为：尝试额外记录 `started_at_ns`，比较 `(started_at, started_at_ns, attempt_id)`；秒级 `started_at` 继续供展示。成功快照和最近尝试分别比较，旧失败不能覆盖新成功，旧成功不能覆盖新成功。
  - 新版状态键为 `official_kichu_snapshot/official_kichu_attempt/potential_v2_snapshot/potential_v2_attempt/potential_pending`；普通合并只允许旧板块与已知兼容字段。
- [ ] **Step 4 — 同文件通过。** 增加 `test_same_second_late_result_cannot_overwrite_new_success`、`test_failure_state_bumps_version_not_content_time`、`test_lost_guard_leaves_snapshot_unchanged`；证明跨进程缓存版本刷新，未知同接没有伪造观测。
- [ ] **Step 5 — 提交 `feat: publish source-specific collection snapshots atomically`。**

## Task 5：共享请求、独立来源配额和有界待补池

**Files:** Create `backend/collectors/collection_context.py`、`backend/collectors/discovery.py`、`backend/tests/test_discovery_budget.py`；Modify `backend/collectors/bilibili.py` 的低层请求与源适配。

**Interfaces:** `RoundContext(policy: CollectionPolicy, *, loaders: Mapping, now: int)`；`fetch_once(kind: str, key: tuple, loader: Callable) -> object` 缓存成功及失败；`record_http_attempt(kind: str) -> None`、`summary() -> dict`。`discover_candidates(*, context: RoundContext, official_snapshot: dict|None, pending: list[dict], now: int) -> DiscoveryResult`。loaders 明确提供 popular_page/search_page/all_ranking/newest/detail/tags/online，各结果包含 success/error/invalid，成功空列表不等于失败。

- [ ] **Step 1 — 写失败测试。** 高播放样本先占旧 Top30，另有低播放合格作品在第 31+位，断言后者进入候选；同 BV 跨三源仅一候选且 sources 全保留。最新/综合搜索都调用；热门 15 页在其他分类复用；种子≥10 个时总页数仍≤8。
  ```python
  # test_candidate_beyond_legacy_top30_survives: discovery 来自固定的40条输入
  candidates = [v for lane in discovery.lanes.values() for v in lane]
  assert low_view_bvid in {v['bvid'] for v in candidates}
  assert len({v['bvid'] for v in candidates}) <= 400
  assert context.summary()['logical']['discovery'] <= 60
  ```
- [ ] **Step 2 — 运行 `tests/test_discovery_budget.py`，确认旧截断/重复请求无法通过新断言。
- [ ] **Step 3 — 实现公平采样。** 来源配额官方100/最新100/综合100/新投稿20/热门等80；来源内按发布时间降序+BVID，跨来源轮询，空余名额回流；未知日期进入待补而非隐式判老。搜索明确使用 `order=pubdate` 和 `order=totalrank`，不把搜索参数 rid 套成1007。低层 HTTP 发起处记实际尝试，覆盖 `safe_get` 和弹幕 XML 的直接 `requests.get`；`summary()` 以 `logical/http_attempts/cache_hits/skipped` 分组并按kind计数。缓存键含 URL/参数身份，不能仅按 BV 缓存不同接口。
  - 不拼接来自不同采样时点的部分指标组；取更新的完整组，来源仍合并。
  - 按规格上界保存 pending，重试在原来源配额内；过龄只退出当前集合，不删除视频/历史。全量任务级重试创建新 context 和尝试身份，防止上一轮失败缓存永久滞留。
- [ ] **Step 4 — 同文件通过。** `test_partial_stats_from_two_sources_do_not_form_real_sample`、`test_failed_request_is_not_repeated_in_same_round`、`test_pending_is_bounded_and_expiry_does_not_delete_history`、全部预算边界测试通过；日志计数能区分逻辑调用和实际 HTTP。
- [ ] **Step 5 — 提交 `feat: discover independent candidates with shared request budgets`。**

## Task 6：真实统计补全后严格筛选和独立评分

**Files:** Create `backend/services/potential_selection.py`、`backend/tests/test_potential_selection.py`；Modify `backend/utils/scorer.py` 仅在真实门槛、未来日期保护等必需位置；保留既有权重函数。

**Interfaces:** `generate_potential(discovery: DiscoveryResult, *, context: RoundContext, now: int, history: Callable) -> PotentialResult`。history 复用既有 `_smooth_online` 语义；snapshot 包含 items/meta，空合格结果也有 snapshot；整体失败才为 None。

- [ ] **Step 1 — 写失败测试。** 估算赞/转发不能入榜；详情把播放改到1000001、互动低于10或分类改非鬼畜后剔除；恰好1500/1000000且互动10/龄期21天可进入；未来/无日期、缺核心统计不进榜；不足10条不放宽。
  ```python
  # test_real_detail_over_cap_is_rejected: 补全前播放为10000，详情为1000001
  assert result.snapshot is not None
  assert result.snapshot['items'] == []
  assert result.snapshot['meta']['rules_version'] == 'strict-real-stats-v1'
  # test_short_list_does_not_relax: 只有三条严格合格输入
  assert len(short_result.snapshot['items']) == 3
  ```
- [ ] **Step 2 — 运行 `tests/test_potential_selection.py`，确认当前“先筛后补”或缺少新实现导致断言失败。
- [ ] **Step 3 — 实现补全→最终门槛→同接→评分。** 复用≤1800秒的完整官方统计；旧/缺失统计在160详情预算内补齐，否则进入pending。新投稿和最新搜索各保留最多20详情名额，其他轮询；合格后才抓同接，失败保持None和历史平滑来源。
  - 只让最终合格候选进入现有 `score_potential_batch`；extra 不参与归一和榜单。并列以发布时间降序+BVID；最多30。meta 记录实际门槛、strict-real-stats-v1、批内算法标识、数量和来源缺失；不重算旧分数。
- [ ] **Step 4 — 新测试及 `tests/test_batch_scorer.py tests/test_potential_score_fix.py tests/test_radar_provenance.py tests/test_online_breaker.py` 通过。** 覆盖 stale stat、完整真实零值、全源失败保留/成功无人合格清空的差别、部分源失败可标partial、None与0同接、extra不改变归一边界。
- [ ] **Step 5 — 提交 `fix: qualify potential videos using final real statistics`。**

## Task 7：双规则编排、派生样本和历史写入保护

**Files:** Modify `backend/collectors/bilibili.py`、`backend/collectors/__init__.py`、`backend/jobs/crawl_jobs.py`、`backend/storage/cache.py`；Create `backend/tests/test_collection_generation.py`；Extend `backend/tests/test_bilibili_meme.py`、`backend/tests/test_bilibili_collect.py`。

**Interfaces:** `run_all_crawlers(*, context=None, official_snapshot=None, pending=None, mode=None) -> dict` 保留无参兼容；输出旧字段、`potential_v2_snapshot/potential_v2_attempt/potential_pending`、`_all_videos`、`_collection_summary`。生产 wiring 由任务8提供 context；不在该函数网络刷新官方榜。

- [ ] **Step 1 — 写失败测试。** shadow 同时生成旧公开结果和新版潜力快照，两个副本不串分；新版结果不覆盖旧 hot_videos；official 候选上百条不让派生标签/弹幕/评论数量倍增。原播放排序/最多30测试仅约束兼容旧榜，不约束候选发现。
  ```python
  # test_shadow_keeps_legacy_public_results_and_new_snapshot
  assert generation['hot_videos'] == expected_legacy
  assert generation['potential_v2_snapshot']['items'] == expected_strict
  assert generation['hot_videos'][0] is not generation['potential_v2_snapshot']['items'][0]
  assert context.summary()['logical']['tags'] <= 64
  ```
- [ ] **Step 2 — 运行 `tests/test_collection_generation.py tests/test_bilibili_collect.py tests/test_bilibili_meme.py`，确认新编排断言失败。
- [ ] **Step 3 — 接入上下文和独立生成器，保留旧规则计算副本。** 兼容旧榜/派生鬼畜样本取发现播放Top30；热梗/BGM按BV去重；弹幕20+30+20、评论10。所有标签/详情/同接都走同轮缓存。`_all_videos` 合并来源，未完成真实核心统计的记录仅登记元信息，不把估算字段写观测。
  - shadow 不把新版潜力分写入旧公开观测；official 才把新版分写对应批次，`_all_videos` 的分数必须显式从当前公开规则副本选择，不能由首条去重决定。官方独有且不在展示/潜力名单的作品登记为warm，写真实统计时也不能由 `record_video` 默认hot重置既有分级。记录规则版本到当前快照和crawl summary，不改历史schema。实时结果与持久结果分开处理，临时数据不写历史。
- [ ] **Step 4 — 同文件通过，再执行 `tests/test_hot_meme_filters.py tests/test_golden_comments.py tests/test_potential_videos.py`。** 断言同BV热梗只贡献一次、实际网络调用不等于双份、官方失败不关闭独立潜力发现、原素材分类和历史None语义保留。
- [ ] **Step 5 — 提交 `refactor: separate ranking discovery and derived collection inputs`。**

## Task 8：接入 Worker 调度、startup、共享锁与观测预算

**Files:** Create `backend/jobs/official_ranking_jobs.py`、`backend/tests/test_official_ranking_jobs.py`；Modify `backend/jobs/crawl_jobs.py`、`backend/jobs/scheduler.py`、`backend/worker_entrypoint.py`、`backend/app.py` 的刷新入口、`.env.example`、`compose.dev.yml`、`compose.prod.yml`；Extend `backend/tests/test_scheduler.py`、`backend/tests/test_entrypoint_separation.py`。

**Interfaces:** `run_official_ranking_job(trigger: str='scheduled') -> dict`；`refresh_official_if_due(*, now: int) -> dict`；`select_observation_targets(visible: list[str], tiered: list[str], *, limit: int) -> list[str]`。刷新线程显式传 `guard`，`_crawl_job_locked/_crawl_job_live` 接受该参数，不能在另一个线程或连接重新拿锁后伪装原guard。

- [ ] **Step 1 — 写失败测试。** shadow/official 注册 `:05/:35`、Asia/Shanghai、max_instances=1/coalesce；legacy不注册。startup无快照/超过1800秒才抓，真实时间不足不抓。API手动、全量、观测和官方争同一锁；忙碌时仍保留原409/跳过行为。
  ```python
  # test_official_schedule_is_independent: jobs 来自现有FakeScheduler记录
  job = next(j for j in jobs if j['id'] == 'official_kichu_rank')
  assert job['minute'] == '5,35'
  assert job['max_instances'] == 1 and job['coalesce'] is True
  assert str(scheduler.timezone) == 'Asia/Shanghai'
  ```
- [ ] **Step 2 — 运行 `tests/test_official_ranking_jobs.py tests/test_scheduler.py tests/test_entrypoint_separation.py`，确认新调度和互斥断言失败。
- [ ] **Step 3 — 一次性接齐入口。** Worker安装依赖后先执行到期官方预热，再启动原全量startup；官方任务只登记元信息并发布快照。全量和实时注入同轮context/旧官方快照；API刷新只移交其已拿guard，不新增官方HTTP。忙碌重试用调度器date job、固定ID去重、最多5分钟后一次，不用长sleep/新线程循环。
  - 观测先放可见官方20/潜力30，去重后在总limit=200内补tier目标；radar reference单列且不抓同接。配置模板向API/Worker传同一mode，不读取或修改本机/生产真实env与secret；不改其他服务、卷、网络和端口。
- [ ] **Step 4 — 同文件及 `tests/test_compose_security.py tests/test_postgres_runtime.py` 通过。** 断言startup无假观测、登记失败不发布、锁丢失停止发布、普通目标不超过limit、100条官方不触发100次补全；新增mode下API仍无官方写入调用。
- [ ] **Step 5 — 提交 `feat: schedule lightweight official ranking refreshes safely`。**

## Task 9：统一两个接口与实时缓存的榜单视图

**Files:** Create `backend/services/collection_views.py`、`backend/tests/test_collection_views.py`、`backend/tests/test_collection_api.py`；Modify `backend/app.py`、`backend/jobs/crawl_jobs.py` 的有效观测榜读取；Extend `backend/tests/test_radar_api.py`。

**Interfaces:** `select_collection_views(persisted: dict, *, live: dict|None, mode: str, now: int) -> dict` 返回 `kichu_rank/kichu_rank_meta/hot_videos/potential_meta` 四字段深拷贝投影。live为现有TTL包装对象，不能直接覆盖持久官方快照；公共接口沿用原数组契约。

- [ ] **Step 1 — 写失败测试。** 同一persisted下Dashboard和独立接口的BV顺序/snapshot_id完全相同；存在更老实时缓存时仍显示更新的持久官方榜；无官方快照不拿legacy填充。元信息携带source/成功时间/最近尝试，3600秒边界、24小时历史提示各有断言。
  ```python
  # test_dashboard_and_rank_route_share_snapshot
  dashboard = client.get('/api/dashboard').json['data']
  rank = client.get('/api/kichu-rank').json
  assert [v['bvid'] for v in dashboard['kichu_rank']] == [v['bvid'] for v in rank['data']]
  assert dashboard['kichu_rank_meta']['snapshot_id'] == rank['meta']['snapshot_id']
  ```
- [ ] **Step 2 — 运行 `tests/test_collection_views.py tests/test_collection_api.py tests/test_radar_api.py`，确认原路由分流行为失败。
- [ ] **Step 3 — 接统一读取器。** Dashboard新增并列meta、独立接口顶层meta；新版潜力只选更新且成功的完整临时snapshot，否则持久同规则snapshot。cache key含持久状态version、临时缓存身份、mode、分钟桶及既有radar revision；保持其余板块选择和认证不变。
- [ ] **Step 4 — 同文件通过。** radar装饰后源快照无变化；API换进程仍读相同官方快照；shadow/legacy显示legacy_custom及旧潜力规则，official失败只回同源；观测取同一公共有效榜单。HTTP200结构正常与meta不可用明确区分。
- [ ] **Step 5 — 提交 `fix: serve consistent source-aware ranking snapshots`。**

## Task 10：最小页面语义与独立展示名次

**Files:** Create `frontend/src/components/RankingSource.jsx`、`frontend/src/components/RankingSource.test.jsx`、`frontend/src/App.rankings.test.jsx`；Modify `frontend/src/App.jsx`、`frontend/src/components/VideoCard.jsx`、`frontend/src/components/VideoCard.test.jsx`。

**Interfaces:** `VideoCard({video,index,displayRank,...})` 显式displayRank只由官方上下文传入；其他场景沿用index。`RankingSource({meta})` 渲染来源、北京时间抓取时间、失败/过期/历史或不可用状态，旧数据缺meta时显示未知/旧规则，不猜测官方。

- [ ] **Step 1 — 写失败测试。** 同一BV在官方卡片传displayRank=7、潜力卡片index=0，分别显示7和1；搜索/收藏不因video携带official_rank显示名次。首页和榜单页都显示“哔哩哔哩官方榜”，抓取时间不冒充官方更新时间。
  ```jsx
  // same video keeps its independent ranking context
  const { container } = render(<>
    <VideoCard video={video} index={0} displayRank={7} formatNumber={String} />
    <VideoCard video={video} index={0} formatNumber={String} />
  </>)
  expect([...container.querySelectorAll('.kb-rank')].map(n => n.textContent)).toEqual(['7', '1'])
  ```
- [ ] **Step 2 — 运行 `npm test -- src/components/VideoCard.test.jsx src/components/RankingSource.test.jsx src/App.rankings.test.jsx`，确认缺少显式名次/来源时失败。
- [ ] **Step 3 — 增加语义必要UI。** 第一名样式由实际displayRank决定；状态文案覆盖“更新失败”“历史榜单”“暂无官方榜数据”，失败时仍保留可用旧榜。潜力说明为本批相对评分；保留卡片结构、导航、收藏动作、响应式和现有SEO内容，优先复用现有文字样式。
- [ ] **Step 4 — 同文件及 `npm test -- --maxWorkers=2`、`npm run build` 通过。** 不因缺meta、空列表或同BV双榜崩溃；所有已有交互和SEO构建脚本仍成功。
- [ ] **Step 5 — 提交 `feat: display official rank provenance without changing layout`。**

## Task 11：端到端回归、旁路报告与可执行发布清单

**Files:** Create `backend/tests/test_collection_end_to_end.py`、`backend/scripts/verify_collection_source.py`、`docs/collection-rules-rollout.md`；Modify `frontend/scripts/verify-ranking-layout.mjs`、`.github/workflows/backend.yml`；必要的收集隔离只改 `backend/tests/conftest.py` 和对应手动脚本入口。

**Interfaces:** `verify_collection_source.py --output <path>`，入口 `main(argv: list[str]|None=None) -> int`，对官方源执行一次逻辑采集（最多两次HTTP尝试）并输出脱敏结果/顺序摘要，不连接应用数据库、不读取Cookie文件、不触发完整爬虫；使用固定公开User-Agent/Referer，不调用会注入Cookie的 `get_headers()`；失败非零退出，不输出headers。影子比较写入现有crawl summary，包含规则、覆盖、淘汰、请求和耗时，不新增通知/自动化。

- [ ] **Step 1 — 写失败端到端测试。** 临时PG+固定HTTP响应贯通shadow→official→上游失败→legacy回滚，验证同源回退、旧字段、全量任务不能覆盖官方快照、启动新增BV可观测且没有假点；切换前后历史记录不改。布局脚本加入1440宽度和官方/潜力共享BV、失败/历史来源样本，保留390及原宽度。
  ```python
  # test_failure_after_cutover_keeps_official_snapshot: 上游失败后查询公共投影
  assert failed_view['kichu_rank_meta']['snapshot_id'] == successful_snapshot_id
  assert failed_view['kichu_rank_meta']['last_attempt']['outcome'] == 'error'
  assert failed_view['kichu_rank_meta']['source'] == 'bilibili_official_ranking_v2'
  assert historical_observations_after == historical_observations_before
  ```
- [ ] **Step 2 — 运行 `tests/test_collection_end_to_end.py` 与 `npm run test:layout`，确认新增契约断言失败后再补集成缺口。** 图像路径使用本工作区临时输出，不覆盖用户图像；浏览器缺失应记录环境限制，不能声称视觉验收通过。
- [ ] **Step 3 — 完成CI、只读验证脚本和发布清单。** CI显式排除手动联网入口并保证测试收集无HTTP；fixture只清理自己创建的临时PG。发布清单写明：核验目标提交/镜像/实际部署配置→验证备份和旧版本→仅发布受影响API/Worker/前端→shadow连续24小时且覆盖两个全量周期→至少两个有效官方快照与失败回退验证→人工确认后切official；不足则延长观察。
  - 清单包含健康HTTP、两榜接口元信息/顺序、真实浏览器与Worker检查、mode及镜像回滚；不包含数据库恢复覆盖、downgrade、生产env自动覆盖或删除命令。
- [ ] **Step 4 — 完成下列验证并记录真实结果。**
  - 明确单元/集成回归清单覆盖任务1—9及既有采集/评分/缓存/调度/radar/权限测试；审核收集安全后运行广泛回归，CI不能仅保留新测试掩盖旧失败。
  - `npm test -- --maxWorkers=2`、`npm run test:seo`、`npm run test:layout`；实际查看390px/1440px截图或浏览器，两榜排名/状态准确且无布局回归。
  - 使用仅含临时合成配置的Compose渲染验证，检查仅预期mode透传变化；禁止输出真实生产环境变量。`git diff --check`，确认无schema/secret/runtime产物。
  - `uv run python scripts/verify_collection_source.py --output <本工作区临时结果路径>` 只执行一次受控上游验证；与同一保存响应核对顺序，不能用不同时间响应要求完全一致。受网络权限/风控限制时明确记未验证，不换网络出口绕过。
- [ ] **Step 5 — 提交 `test: verify collection rollout and rollback contracts`。** 输出各阶段提交、验证命令/结果、剩余限制和待授权部署清单；取得计划约定的独立代码审查，修复有效问题后复验受影响项。未实际发布时只能报告代码完成，不能报告线上切换成功。

## 规格覆盖与停止条件

| 规格要求 | 所属任务 |
| --- | --- |
| 意图、口径、分类与保序 | 1、2、6、10 |
| 原子状态、空榜/失败/迟到回退 | 3、4、9 |
| 来源配额、真实补全、待补和预算 | 5、6 |
| 派生样本、去重、历史和观测 | 4、7、8 |
| Worker调度、网络失败、API/缓存 | 2、3、8、9 |
| 最小UI、三模式、旁路/回滚 | 7、9、10、11 |
| 确定性回归、受控联网、发布保护 | 1—11 |

停止并报告具体缺口的情况：必须增加schema/权限、现有源无法满足已承诺的独立发现、基线出现无法解释的失败、生产数据/配置写入未授权、测试只能连接真实业务库。不能以赶进度为由去掉同源回退、门槛或数据保护。

## 执行交接

本计划提交后由用户评审并选择执行方式。推荐在当前会话逐任务执行（Native）：任务共用候选、快照和互斥接口，顺序实现可减少接口偏差，最后安排一次独立整分支审查。另一种方式为每任务独立子代理实现和审查，评审更密集但上下文成本更高。

执行方式尚未选择；当前没有产品代码/测试执行结果或生产部署。计划通过且方式选定后，按相应技能开始任务1。
