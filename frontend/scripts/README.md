# 榜单布局回归测试

在 `frontend` 目录安装依赖后执行：

```sh
npm ci
npx playwright-core install chromium
npm run test:layout
```

测试构建真实前端，使用合成 API 数据，在 1920、1280、900、390 和 320px
宽度下打开鬼畜榜和潜力榜，检查内容没有收缩、没有横向溢出，以及雷达图
是否按卡片可用宽度显示。仪表盘不应渲染雷达图。

同时检查长标题/作者信息、阶段标签单行、播放量粉色、操作按钮不越界且
触控高度至少 44px，以及展开/收起观测趋势不会跳转视频页面。

测试不启动本地 HTTP 服务，全部浏览器请求由测试拦截，不访问生产网站。
移除 `App.jsx` 内容容器上的 `w-full` 会使桌面宽度断言失败。

已有 Edge 时可用 `LAYOUT_BROWSER_CHANNEL=msedge`，或通过
`LAYOUT_BROWSER_PATH` 指定 Chromium 浏览器路径。
设置 `LAYOUT_SCREENSHOT_DIR` 可保存各尺寸的测试截图。

## Sitemap 自动生成

执行 `npm run build` 会依次打包、预渲染首页、扫描 `dist/` 中的 HTML，
自动生成 `dist/sitemap.xml`。Docker 构建也运行同一个命令，无需额外服务、
新依赖或手工上传 XML。`npm run test:seo` 会完成构建并检查最终 XML 和首页。
构建后可用 `npm run sitemap` 单独重新生成。

只收录实际生成、canonical 与访问路径一致且没有 noindex 或 HTML 跳转的页面。
域名取自首页的 HTTPS canonical。首页 canonical 缺失、错误或禁止索引时使构建失败，
不覆盖已有 Sitemap。普通验证文件、指向首页的重复页面、外站 canonical 不收录。
没有可靠的内容更新时间时省略可选的 lastmod，不用打包时间代替。

目前只生成首页一条记录，现有 React 页签没有独立地址。今后若实现 `/rankings/`，
应先让预渲染输出 `dist/rankings/index.html` 并声明自己的 canonical；生成器即可
自动收录它。仅增加一个按钮、页签或 SPA 路由但没有对应静态 HTML，不会凭空加入。
开发服务器不提供这个构建产物，应在打包后的预览或生产环境检查 `/sitemap.xml`。
