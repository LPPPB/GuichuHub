# 榜单布局回归测试

在 `frontend` 目录安装依赖后执行：

```sh
npm ci
npx playwright-core install chromium
npm run test:layout
```

测试构建真实前端，使用合成 API 数据，在 1920、1280、900 和 390px
宽度下打开鬼畜榜和潜力榜，检查内容没有收缩、没有横向溢出，以及雷达图
是否按卡片可用宽度显示。仪表盘不应渲染雷达图。

测试不启动本地 HTTP 服务，全部浏览器请求由测试拦截，不访问生产网站。
移除 `App.jsx` 内容容器上的 `w-full` 会使桌面宽度断言失败。

已有 Edge 时可用 `LAYOUT_BROWSER_CHANNEL=msedge`，或通过
`LAYOUT_BROWSER_PATH` 指定 Chromium 浏览器路径。
设置 `LAYOUT_SCREENSHOT_DIR` 可保存各尺寸的测试截图。
