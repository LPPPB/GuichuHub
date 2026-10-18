# Favicon 与首页 SEO 整改

## 实测基线与范围

2026-10-15 通过现有 SSH 身份只读核实腾讯云服务器 `/srv/guichuhub`，生产提交及远端 HEAD 均为 `261a1e9f8840ba89d9d69c373d6155ccb4c9072f`。本地主仓库为 `F:/作业工程库/GuichuHub`；旧 V3 目录有未提交改动且落后，未参与本次修改。

- 公网首页 200，但原始 HTML 的 `#root` 为空；默认总览组件没有 H1，只有其他页签的 PageHeader 有 H1。
- `/favicon.ico` 404；`/favicon.svg` 200、`image/svg+xml`，却有一年且 immutable 的缓存策略。源码只声明 SVG。由此确认资源兼容缺口，但不能据此证明 Bing 图标缺失的全部原因。
- title、description、canonical、robots.txt、sitemap.xml 已存在。站点使用内部状态切换页签，未提供各页签独立 URL。
- 现状为 Caddy HTTPS → Nginx 8080 → React；`/api/` 由 Caddy 转发。生产有 PostgreSQL、API、Worker 等服务，本次全部不改。没有读取 Cookie、口令或环境文件正文。

## 最小修复及预渲染决策

1. 复用原有 `favicon.svg` 生成 ICO（16/32/48）、96px PNG、180px touch icon；维护命令为 `npm run icons`，需要 Playwright 可用的本机 Chrome，可设置 `LAYOUT_BROWSER_CHANNEL=chrome`。图片提交入库，生产构建无需浏览器。
2. 在 HTML head 声明 ICO、PNG、SVG 和 touch icon。Nginx 明确 ICO MIME，图标及普通固定文件缓存一小时并要求过期再验证；仅 Vite 带内容 hash 的 `/assets/` 长期 immutable。首页 no-cache，所有静态资源缺失返回 404。
3. 总览增加对辅助技术可读的 `sr-only` H1 与准确说明，不改变现有视觉布局，切换其他页签后使用其原有 H1。
4. 仅用 CSR 添加 H1 仍无法解决“初始 HTML 无 H1”。因此 `npm run build` 在 Vite 输出后，用 React `renderToString` 生成同一个 App 的公开加载外壳，包含 H1、导航、页脚；所有访客和爬虫收到同一 HTML。保留既有 `createRoot` 挂载，客户端接管后照常请求实时数据。没有按 User-Agent 分流，也没有预抓取身份、API 或保存热榜快照。
5. 完善 title、description 和 WebSite JSON-LD（名称、URL、语言），不虚构搜索 URL 或 SearchAction。保留站点验证标签。现有 canonical 正确，robots 允许页面及图标、屏蔽 API；sitemap 只列真实首页，因此保留。默认允许索引，无需冗余 robots meta。

这改善公开首页身份与结构的可抓取性，不代表所有实时排行条目均已静态索引。只有未来确实需要独立内容页收录时，才评估带真实 URL 的静态生成或 SSR，避免扩大本次整改。

依据：[JavaScript SEO 基础](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)、[搜索图标指南](https://developers.google.com/search/docs/appearance/favicon-in-search)。这些是 Google 的指南，不作为 Bing 特有规格或展示保证。

## 验证

- 修改前基线 17 文件 / 173 项测试通过；新增三项回归先失败（缺少图标声明、首页 H1、真实 ICO/PNG），修复后完整前端 18 文件 / 176 项通过。
- `npm run test:seo`：生产构建及无需 JavaScript 的 HTML 检查通过，检查 H1、metadata、JSON-LD、图标、robots、sitemap 与原有站点验证标签。
- 原颜色测试以第一个“鬼畜区排行榜”文字为起点，新说明使其误匹配；定位条件收窄为原 Section，不放宽颜色断言。
- `LAYOUT_BROWSER_CHANNEL=chrome node scripts/verify-navigation-layout.mjs`：319/320/390/768/1024/1046/1440px × 明暗主题，共 14 个场景通过，检查导航、焦点、滚动与无横向溢出。
- 现有 ECharts 大包及测试工具弃用提示仍存在，本次没有扩大范围升级依赖。

## 发布与回滚约束

发布前重新核对生产 HEAD、干净的受跟踪文件、前端镜像、Compose/Caddy/环境文件校验和、备份任务及最近备份时间；保留当前前端镜像标签。只构建并替换 `frontend`，使用原生产 Compose 和原环境文件执行 `up -d --no-deps --no-build frontend`。不迁移数据库，不更改卷、Cookie、环境变量或其他服务，不使用 `down -v`。

切换前先以不接入生产网络、不挂载运行数据、只监听本机随机端口的候选前端容器验证 Nginx 配置及 HTTP 行为。切换失败立即恢复保留的旧镜像和原源码提交，再检查首页及健康接口。发布前后比较 API、Worker、PostgreSQL、Caddy、egress 容器 ID、镜像与启动时间，确认未变。

发布后检查 `/`、ICO/SVG/PNG/touch icon、robots、sitemap 的状态、类型、缓存、文件签名/校验和，以及无需 JS 的 H1/JSON-LD、普通访客和 Bingbot HTML 一致性、条件请求与健康接口。仅 HTTP 检查不等于线上浏览器视觉验收。

Bing Webmaster Tools 的 URL 检查/实时测试应重新抓取首页，并提交 `https://guichuhub.cn/sitemap.xml`。搜索结果图标和历史 H1 报告需要 Bing 重新抓取、处理和更新缓存，无法承诺立即出现或固定生效时间。未使用站点管理账号提交请求。
