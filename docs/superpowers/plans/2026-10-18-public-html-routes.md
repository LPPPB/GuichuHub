# GuichuHub Public Routes and HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 九个公开栏目拥有可分享网址，并在公开持久化内容变化后提供包含真实正文的初始 HTML，保留现有交互。

**Architecture:** API 通过内部只读接口导出经过逐层允许列表筛选的公开持久化数据。独立 Node 服务复用生产 React SSR bundle，每 60 秒检测内容变化并原子发布缓存文档；Nginx 提供静态资源并只代理已定义的页面。浏览器从同一公开数据 hydration，随后增强交互。

**Tech Stack:** React 18、Vite、Node 22、Vitest/Testing Library、Flask/Python、pytest、Nginx、Docker Compose；不新增客户端路由依赖。

**Spec:** `docs/superpowers/specs/2026-10-18-public-html-routes-design.md`

## Global Constraints

- 工作区 `F:/作业工程库/GuichuHub开发工作区/guichuhub-public-html`，分支 `codex/public-html-routes-20261018`，基线 `e99c019aa83ee903ce866a1a318c52441f4d4962`。
- 当前会话由主代理逐阶段实现，最后独立审查；沿用用户已选执行方式。
- 不改采集规则，不合并或启用 PR #22，不调整生产数据，不部署。
- 保留现有布局、图表、移动抽屉、账户及收藏交互；普通访客与搜索引擎获取相同 HTML，不按 User-Agent 分流。
- 检查周期 60 秒，单次内部请求超时 10 秒，同一时刻只运行一个生成周期。
- 公开子页采用无尾斜杠路径；未知路径返回真实 404；未产生成功页面且数据源不可用时返回 503、Retry-After、X-Robots-Tag: noindex。
- 不使用手动 LIVE 缓存发布页面，不把全局 last_updated 当作分板块成功采集时间；故障保留成功内容与时间。
- 新增专用 public_pages_cache 卷；不挂载数据库、私密目录、凭据或既有业务卷；不执行 docker compose down -v。
- 完整 SEO 文案、sitemap 扩展与 IndexNow 留待后续；本阶段补齐页面标题、主标题及自指 canonical。

## Review Focus

- 浏览器带已有主题、屏蔽词、登录信息访问深链接：首次树仍与 SSR 一致，随后恢复个人设置（任务 4、6）。
- 同一次轮询中部分板块失败、部分成功：成功页可更新，失败页及首页相应摘要保留旧内容和时间（任务 2、5）。
- 页面生成进程在写文件或切换批次时崩溃：重启只读取完整、已提交的缓存（任务 5）。
- Nginx 与页面服务版本不同或旧磁盘缓存仍在：拒绝不匹配资产组合，用兼容数据重建（任务 7）。
- 编码路径、重复斜杠、HEAD/条件请求及查询参数：只对真实栏目返回正文，不产生软 404、开放重定向或重复缓存（任务 1、7）。

## 文件与契约

新增文件按职责分组；不拆分无关大型组件。产品文件和测试由各任务明确列出。

- `frontend/src/routing/publicRoutes.js`：九条路径、tab、标题、canonical 映射与纯路径匹配。
- `frontend/src/routing/usePublicNavigation.js`、`PublicLink.jsx`：History API、原生链接行为与私有 tab 隔离。
- `backend/services/public_pages.py`：公开字段清洗、来源读取和内容摘要；`backend/app.py` 只增加薄路由。
- `frontend/src/publicPages/contract.js`：浏览器与生成器共用启动数据校验。
- `frontend/src/publicPages/ssr-entry.jsx`、`bootstrap.js`：完整 SSR 文档及浏览器启动解析。
- `frontend/public-pages/{publisher,cache,http,server}.mjs`：轮询、持久化、HTTP 和启动装配；生产运行不依赖 Vite server。
- `frontend/scripts/build-public-pages.mjs`：构建 SSR、资产摘要及供 Nginx 使用的路由配置片段。
- `compose.public-pages-test.yml`、`ops/public-pages-test/`：只有合成数据 API、生成器、前端的隔离验收环境。

内部导出版本 1：`{schema_version: 1, sections: {[tabId]: Section}}`。`Section` 为 `{status: 'ready'|'empty'|'unavailable', content_version: string|null, source_updated_at: number|null, data: object}`；时间为 Unix 秒。`unavailable` 不覆盖成功数据；`empty` 仅由明确有效的空结果产生。当前 legacy 含混空数组一律 unavailable。

启动数据版本 1：`{schema_version: 1, build_id: string, tab_id: string, sections: object, confirmed_at: object, render_year: number}`。section 与导出契约一致；confirmed_at 记录内容版本首次被确认的 Unix 秒；render_year 固定本次渲染页脚年份。不同路由仅嵌入其正文实际需要的公开栏目，首页使用已成功发布的摘要集合。

## Task 1: 九个网址与原生导航

**Files:** 新增 `frontend/src/routing/publicRoutes.js`、`usePublicNavigation.js`、`PublicLink.jsx`、`publicRoutes.test.js`、`PublicLink.test.jsx`；修改 `frontend/src/App.jsx`、`components/SidebarContent.jsx`、`MobileDrawerContent.jsx`、`Sidebar.jsx`、`SiteFooter.jsx` 及受影响导航测试。

**Interfaces:** `PUBLIC_ROUTES` 提供九个 `{tabId,path,title}`；`resolvePublicPath(pathname)` 返回 `{kind:'page',route}`、`{kind:'redirect',location}` 或 `{kind:'not-found'}`。`usePublicNavigation(initialTab)` 返回 `{activeTab,navigate}`；`PublicLink({tabId,onNavigate,...anchorProps})` 生成真实 href。

- [ ] 写失败测试：九条映射与设计表逐项相等；`/rankings/kichu/` 规范到 `/rankings/kichu`；未知、编码分隔符和重复斜杠不被当成首页。保留 query 仅作浏览器导航，不参与缓存或 canonical。
- [ ] 写交互断言：普通点击改变 pathname 与栏目；popstate 恢复栏目；Ctrl/Cmd/Shift、中键及 target=_blank 不 preventDefault；dev 不出现在公开映射，私有 tab 选择不向 history 写入公开 URL。

```js
expect(resolvePublicPath('/rankings/kichu').route.tabId).toBe('kichu-rank')
expect(resolvePublicPath('/rankings/kichu/')).toEqual({kind: 'redirect', location: '/rankings/kichu'})
expect(resolvePublicPath('/unknown').kind).toBe('not-found')
```

- [ ] 在 frontend 执行 `npm test -- src/routing`，确认是新功能缺失导致失败。
- [ ] 实现上述纯函数和 hook；将公开导航按钮换为同类名链接，保留分组及账户操作按钮。首页“查看全部”、登录后/注销后的导航也走 navigate。
- [ ] 重跑新测试及 `npm test -- src/App.dashboard.test.jsx src/App.footer.test.jsx src/components/Sidebar.test.jsx`；只调整因语义从 button 改为 link 的断言，不删除交互断言。通过后提交 `feat: add public section URLs and native navigation`。

## Task 2: 只读公开数据导出

**Files:** 新增 `backend/services/public_pages.py`、`backend/tests/test_public_pages.py`、`test_public_pages_api.py`；修改 `backend/app.py`。

**Interfaces:** `build_public_sections(dashboard: dict, up_analysis: dict|None) -> dict` 是不修改输入的纯函数；`load_public_pages() -> dict` 分别捕获 dashboard 与 UP 读层异常。新增 GET/HEAD `/internal/public-pages`，只调用该适配器；响应带 schema_version。

- [ ] 先写失败测试：匿名、访客 Cookie、管理员头获得同一公开字段；在原始记录的顶层及嵌套层放入 cookie、token、申请理由和任务对象，导出中均不存在。mock LIVE 读取、采集/分析写函数，断言调用次数 0。
- [ ] 写稳定性断言：仅全局 last_updated 改变不改变板块 content_version；UP 版本可独立变化；输入完全未变；某一来源抛异常时其他来源仍 ready；旧式空列表标为 unavailable，不伪造有效空。

```python
assert first['sections']['memes']['content_version'] == changed_clock['sections']['memes']['content_version']
assert exported['sections']['videos']['status'] == 'unavailable'  # legacy 空数组
assert 'cookie' not in json.dumps(exported)
assert live_reader.call_count == writer.call_count == 0
```

- [ ] 在 backend 执行 `python -m pytest tests/test_public_pages.py tests/test_public_pages_api.py -q`，先确认失败，再实现适配器。测试使用本工作区测试虚拟环境；API fixture 若需要 PostgreSQL，只使用已有一次性测试容器机制。
- [ ] 对每类记录用显式字段字典构造输出：视频字段取现有卡片公开字段；热梗 keyword/heat/trend_label/related_videos；素材 name/description/aliases/video_count/total_views/related_videos；BGM 沿用现有公开卡片字段；评论只取展示内容与作品来源。嵌套视频重复使用同一 sanitizer，不复制未知属性。
- [ ] 设定边界：每栏目最多 200 行、每项关联视频最多 20 个；标题/名称 500 字符、说明/评论 4000 字符、其他字符串 1000 字符，嵌套最大 6 层，导出总量上限 2 MiB。非有限数值、非法类型和无效 bvid 丢弃或置 null；封面仅允许现有 B 站图片 HTTPS 域名。超出整体上限返回失败，不截断 JSON。
- [ ] 先输出 kichu-rank、memes、videos 三类契约；其余栏目暂为 unavailable。新测试通过后提交 `feat: export bounded public page snapshots`。

## Task 3: 三个优先栏目的生产 SSR 构建

**Files:** 新增 `frontend/src/publicPages/contract.js`、`ssr-entry.jsx`、`bootstrap.js`、`ssr.test.jsx`、`frontend/scripts/build-public-pages.mjs`；修改 `frontend/src/App.jsx`、`frontend/vite.config.js`、`frontend/package.json`。

**Interfaces:** `validateBootstrap(value)` 返回经过验证的启动数据或 null；`serializeBootstrap(value)` 安全序列化。`renderPublicPage({route,bootstrap,template}) -> Promise<string>` 用 React 完成渲染再返回完整 HTML。生产构建导出该函数与静态资产 build_id。

- [ ] 写失败测试：三个栏目各自 HTML 包含样本标题、作者或热梗名；每页一个对应 h1、自指 canonical、正确 title 和可抓取站内链接；没有调用收藏、身份或网络 API。
- [ ] 写注入测试：`</script><script>...`、`<`、U+2028/U+2029 在启动 JSON 中安全转义，解析回原值；超大/错误版本 bootstrap 被拒绝；数据与实际 SSR 标题一致。

```js
expect(document.querySelectorAll('h1')).toHaveLength(1)
expect(document.querySelector('link[rel="canonical"]').href).toBe('https://guichuhub.cn/rankings/kichu')
expect(document.body.textContent).toContain('合成鬼畜榜作品')
expect(JSON.parse(serializeBootstrap(payload))).toEqual(payload)
expect(serializeBootstrap(payload)).not.toContain('</script>')
```

- [ ] 运行 `npm test -- src/publicPages/ssr.test.jsx` 确认失败，再让 App 接收 initialTab/initialData/initialAux；已有无参数 App 调用继续可用。
- [ ] 以生产 SSR build 生成可直接被 Node import 的 bundle，模板使用客户端构建资产；在首页构建预渲染前保存原始空 root 模板，运行时只替换该模板，不能嵌套旧首页壳。需要懒组件时用 React stream 等待 allReady，10 秒未完成视为渲染失败，不发布 Suspense 加载页。保留现有构建首页静态壳供开发/无数据构建检查，运行服务不将其当作成功数据页。
- [ ] 重跑测试及 `npm run build`，直接 import 构建产物渲染合成数据验证不依赖 Vite。通过后提交 `feat: render public ranking content from production SSR bundle`。

## Task 4: 同一数据 hydration 与失败保留

**Files:** 修改 `frontend/src/main.jsx`、`App.jsx`、`components/Sidebar.jsx`、`DanmakuCloud.jsx`、`SiteFooter.jsx`；新增 `frontend/src/publicPages/hydration.test.jsx`。

**Interfaces:** `readBootstrap(document)` 返回有效启动数据或 null；有有效数据时 hydrateRoot，无数据的开发静态壳使用 createRoot。App 首次树仅依赖 bootstrap 与确定性默认值，随后 effect 恢复主题、身份与本地偏好。

- [ ] 写失败测试：SSR 后预置 light 主题、屏蔽词、mock 登录与窄屏，再 hydrate；spy onRecoverableError，无 hydration 错误，初始列表不消失；公开数据刷新失败仍保留列表与时间。
- [ ] 写断言：有效快照启动不先进入 loading；后续 fetch 不清空已有数据；收藏及身份只来自客户端请求，不出现在 SSR JSON；跨年份固定 render_year 避免页脚时间不匹配。

```js
expect(onRecoverableError).not.toHaveBeenCalled()
expect(screen.getByRole('link', {name: '合成鬼畜榜作品'})).toBeVisible()
expect(document.querySelector('#public-page-bootstrap').textContent).not.toContain('private-favorite')
```

- [ ] `npm test -- src/publicPages/hydration.test.jsx` 先失败；实现 bootstrap 读取、初始状态与 mounted 后增强。对 window/document/localStorage 仅做必要 SSR 适配，不改视觉类名。
- [ ] 新测试和既有 App/导航测试通过后提交 `feat: hydrate public pages without clearing snapshot content`。

## Task 5: 持久缓存、周期发布与故障恢复

**Files:** 新增 `frontend/public-pages/publisher.mjs`、`cache.mjs`、`publisher.test.mjs`、`cache.test.mjs`；修改 `frontend/vitest.config.js` 排除仅由 node:test 执行的 `public-pages/**`，保留 Vitest 默认排除规则。

**Interfaces:** `createPublisher({fetchSections,renderPage,cache,clock,buildId})` 返回 `{refresh(),snapshot()}`；refresh 返回 changedPaths/retainedPaths/failures。`createDiskCache({directory,buildId})` 返回异步 `load()`、`commitBatch(batch)`。snapshot 为仅完整提交的 Map(path -> {html,etag,bootstrap})。

- [ ] 用 Node 内置测试写失败用例：相同内容版本不调用 renderPage、不更改 confirmed_at；新版本在 60 秒周期内更新；UP 可独立更新；10 秒超时及并发 refresh 仅保留一个有效周期。
- [ ] 写故障用例：一次来源失败保留该页和首页对应摘要；成功页正常更新；一批候选的任一渲染失败则该批保留旧版；其他独立批可发布。empty 与 unavailable 行为不同。
- [ ] 写恢复用例：rename/磁盘写故障、半写临时文件、无提交标志批次、恶意缓存路径均不被 load；新进程恢复最后一次完整发布；旧 build_id 文档不直接提供，可用兼容启动数据重新渲染。

```js
assert.equal((await publisher.refresh()).changedPaths.length, 0) // 相同内容的第二次 refresh
assert.equal(publisher.snapshot().get('/rankings/kichu').etag, lastSuccess.etag) // 来源失败
assert.equal((await restartedCache.load()).get('/rankings/kichu').html, lastSuccess.html)
```

- [ ] 执行 `node --test public-pages/publisher.test.mjs public-pages/cache.test.mjs`，确认失败；实现单循环、AbortSignal 超时及固定下一周期重试。磁盘每批使用唯一 generation 子目录、完整文件写入及 manifest 后，原子替换 CURRENT 指针；只有提交指针成功后切换内存 Map，不自动删除历史目录。
- [ ] 全部用例通过后提交 `feat: publish public HTML with persistent failure-safe cache`。

## Task 6: 其余六页与公开图表摘要

**Files:** 修改 `backend/services/public_pages.py`、相关测试、`frontend/src/App.jsx`、`components/UpTrends.jsx`、`DanmakuCloud.jsx`、图表所在组件；新增 `frontend/src/publicPages/PublicChartSummary.jsx`、`allPages.test.jsx`。

**Interfaces:** UpTrends 接收 `initialPublicAnalysis`；其首次 ready 状态及 SSR 正文来自同一公开分析快照。PublicChartSummary 接收允许公开的 labels/values，生成可见文本列表，图表在 mounted 后增强。

- [ ] 写失败测试：九页逐一含各自样本正文；UP lazy 等待后出现公开作者和投稿，不是 checking/setup/loading；BGM、素材、评论有名称、解释或来源作品；图表关闭 JS 仍有对应公开统计文本。
- [ ] 扩展任务 2 的字段允许列表到所有栏目；为 UP/雷达/词云等实际使用的嵌套字段单独定义投影，新增字段必须带“私有同名/未知字段不泄漏”测试，不改原始公开 API 行为。
- [ ] 验证 UP 无分析不触发名单配置或任务启动；主题、词云屏蔽等 hydration 后恢复；页面不出现隐藏给爬虫的另一套列表。

```js
expect(upDocument.body.textContent).toContain('合成公开作者')
expect(upDocument.body.textContent).toContain('合成公开投稿')
expect(upDocument.body.textContent).not.toContain('private-request-reason')
```

- [ ] 执行 `npm test -- src/publicPages src/components/UpTrends.surface.test.jsx src/components/UpTrends.jobs.test.jsx` 和任务 2 后端测试；通过后提交 `feat: expose all public sections in initial HTML`。

## Task 7: 精确 HTTP 路由与容器接线

**Files:** 新增 `frontend/public-pages/http.mjs`、`server.mjs`、`http.test.mjs`、`frontend/docker/check-public-pages-build.sh`；修改 `frontend/Dockerfile`、`frontend/nginx.conf`、`frontend/scripts/build-public-pages.mjs`、`compose.prod.yml`、`ops/caddy/Caddyfile`、`backend/tests/test_compose_security.py`；新增 `backend/tests/test_public_page_deployment.py`。

**Interfaces:** `createPublicPageHandler({publisher,buildId})` 处理 GET/HEAD 精确栏目，`/health/live` 仅本服务内部探活；`/__public-pages/build` 返回非敏感 build_id 供 Nginx 启动脚本核对。生产服务监听 8081，不发布宿主端口，只加入 core 网络，用户为非 root。

- [ ] 写 HTTP 失败测试：九页 200/text-html/UTF-8/ETag/no-cache；HEAD 无 body；匹配 If-None-Match 返回 304；规范尾斜杠 308；未知路径 404；查询字符串不生成新快照；方法不支持返回 405；无缓存返回 503/Retry-After=60/noindex。
- [ ] 写部署失败测试：公开页面服务不含 secrets、业务卷、外部端口和 egress；只有专用 cache 卷可写；Caddy/Nginx 拒绝 `/internal/`；Nginx 无首页兜底；图标与哈希资产缓存策略保留。

```js
assert.equal((await fetch(base + '/unknown')).status, 404)
assert.equal((await fetch(base + '/', {method: 'HEAD'})).headers.get('content-type'), 'text/html; charset=utf-8')
assert.equal((await fetch(base + '/', {headers: {'If-None-Match': etag}})).status, 304)
```

- [ ] 运行上述 Node/pytest 测试先确认失败；实现 Node HTTP 层、非重叠定时器与优雅关闭。backend Dockerfile 无新增 Node。frontend Dockerfile 保留 builder，命名现有 Nginx 为 frontend 目标，新增 public-pages 目标；两个目标复制同一构建阶段产物。
- [ ] 路由配置从任务 1 的表生成 include；代理无尾斜杠页面、308 规范化尾斜杠、其余路径 404。生成器与 Nginx 启动前检查资产 build_id，一方不匹配不得宣告页面服务 ready。静态资源仍由 Nginx 提供。
- [ ] 专用缓存卷仅挂入生成器；镜像固定 UID 可写该卷，启动脚本不遍历或修改任何其他卷。HTTP、Compose 安全测试通过后提交 `feat: serve cached public pages through nginx`。

## Task 8: 隔离验收、回归与独立审查

**Files:** 新增 `compose.public-pages-test.yml`、`ops/public-pages-test/fake_api.py`、`fixtures.json`、`frontend/scripts/verify-public-pages.mjs`、`docs/operations/public-pages-validation.md`；按需更新现有 SEO/布局检查使其验证实际运行页面，不能弱化断言。

**Interfaces:** `verify-public-pages.mjs <base-url>` 从合成 fixture 断言九页标题/链接/状态，不读取生产数据；假 API 内部测试控制可以更新内容、切断 dashboard 或 UP，不能出现在生产镜像或 Compose。

- [ ] 先写并运行验收器，证明缺少页面服务时失败；启动唯一项目名 `guichuhub-public-pages-test` 的测试 Compose，只绑定 127.0.0.1 的独立端口，不使用既有 runtime、数据库或凭据。
- [ ] HTTP 验收九页、404/308/503/304/HEAD、内部前缀拒绝、图标 MIME/缓存、资产匹配；更新合成数据后 120 秒内出现新正文，失败及进程重启保留旧成功内容。旧构建缓存兼容重建也需实测。

```js
assert.equal(verifiedPublicPages.length, 9)
assert.equal((await fetch(base + '/internal/public-pages')).status, 404)
assert.ok(updatedAt - fixtureChangedAt <= 120_000)
```

- [ ] 使用可用浏览器工具在 JS 禁用与启用环境分别查看九页。验证深链接刷新、前进后退、新窗口、移动抽屉、主题与 mock 账户；至少保留 1440 和 390 像素截图，其余 1920/1280/900/320 进行溢出检查。
- [ ] 顺序运行 frontend `npm test`、`npm run build`、相关 SEO/布局检查；backend `python -m pytest -q` 使用隔离 PostgreSQL。构建和布局不可并行修改同一 dist。只有环境错误有证据时才按需重试；不把未运行的检查记为通过。
- [ ] 记录红绿测试、HTTP、浏览器、限制与回滚命令。最终 `git diff --check`、检查工作区只含本任务变更；提交 `test: validate public HTML and navigation end to end`。
- [ ] 按既定方式派发一次完整分支独立审查，提供基线、HEAD、设计、测试证据与生产边界。发现问题先写失败回归，再最小修复并重跑相关检查；记录剩余阻塞，不自行合并、部署或启用新采集规则。

## 覆盖自检与交付

路由/原生导航对应任务 1；数据边界与更新时间对应 2、5；生产 SSR 与脚本转义对应 3；hydration/个人偏好对应 4；持久缓存/失败回退对应 5；其余栏目及 UP 独立数据对应 6；HTTP/资产/Compose 对应 7；无 JS、浏览器、回归和独立审查对应 8。Review Focus 五项均已分配明确测试。

计划审阅后才进入产品实现。最终报告明确列出已实现页面、实际通过的检查、提交及未部署状态。生产切换另行核对现场、备份和旧镜像，恢复旧 API/前端配置即可回滚，不迁移业务数据库、不删除缓存卷。
