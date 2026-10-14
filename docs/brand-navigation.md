# 全站品牌与响应式导航

日常源码入口为 `F:\作业工程库\GuichuHub`。本次只修改前端，不涉及数据库、账号凭据、抓取任务或生产部署。

## 布局

- 顶部品牌栏在所有页面保持可见，复用已有 `/favicon.svg` 声波 Logo 和 GuichuHub 名称；桌面显示简短站点说明。
- 1024px 及以上使用 64px 品牌栏和 232px 常驻侧栏；侧栏导航可独立滚动，底部保留主题、收藏和账号操作。
- 小于 1024px 使用 56px 品牌栏和左侧抽屉，菜单按钮位于品牌栏内。
- 手机／平板首页在品牌栏下显示鬼畜榜、热梗、潜力视频、梗素材库四个快捷入口。
- 抽屉支持选页关闭、遮罩关闭、Esc、Tab 焦点循环、背景 inert 与滚动锁定。跨到桌面时自动关闭并恢复焦点。
- 原有访客／会员／管理员权限和品牌五连点入口保留。
- 沿用既有主题变量，适配安全区域和减少动态效果偏好。

## 验证

```powershell
docker compose -p guichuhub-local -f compose.dev.yml --env-file runtime/dev/compose.env exec -T frontend npm test -- --maxWorkers=2
docker compose -p guichuhub-local -f compose.dev.yml --env-file runtime/dev/compose.env exec -T frontend npm run build
```

在前端目录中执行浏览器检查；本机使用 Edge 时设置环境变量，CI 默认使用已安装的 Chromium：

```powershell
$env:LAYOUT_BROWSER_CHANNEL='msedge'
node scripts/verify-navigation-layout.mjs
$env:LAYOUT_COLOR_SCHEME='light'
node scripts/verify-ranking-layout.mjs
$env:LAYOUT_COLOR_SCHEME='dark'
node scripts/verify-ranking-layout.mjs
```

导航检查覆盖 320、390、768、1024、1440px 的明暗主题、首屏品牌、四入口同排、抽屉、键盘、跨断点、登录转场、吸顶及横向溢出。仅使用生产构建和合成 API 响应，不请求本地或生产数据。设置 `LAYOUT_SCREENSHOT_DIR` 可保存 390px／1440px 预览，预览内容是测试数据。

旧悬浮岛、折叠圆扣以及 Sidebar 源码正则断言已替换为组件行为和浏览器布局检查；其他主题、页面、数据与权限检查保留。
