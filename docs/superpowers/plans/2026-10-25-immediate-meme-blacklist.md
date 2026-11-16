# 黑名单立即生效 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 保存黑名单后即刻过滤已有热梗与梗素材。
**Architecture:** 共享只读可见性过滤器，在响应缓存之后应用；规则版本通知现有浏览器轮询，公开页请求校验新快照。
**Tech Stack:** Flask, PostgreSQL, React, Vitest, Node HTTP.
**Spec:** docs/superpowers/specs/2026-10-25-immediate-meme-blacklist-design.md

## Global Constraints
- 不删除快照、收藏、数据库或凭证；不部署 PR22。
- 整词与已配置别名匹配，不按子串扩大屏蔽。
- 保存失败不得显示成功或通知刷新。

## Review Focus
- 另一 API 进程保存规则后，已预热的响应缓存仍需立即过滤。
- 种子词与别名不能绕过明确停用；撤销后原始数据可恢复。
- 全部屏蔽时公开页必须发布空列表，不能保留旧榜。
- 当前浏览器保存成功立即重载；其他浏览器 15 秒轮询感知版本。
- 公开页更新失败不能继续返回可能含禁词的旧页。

### Task 1: API 读取过滤与规则优先级
Files: backend/services/meme_visibility.py, backend/app.py, backend/collectors/bilibili.py, backend/services/public_pages.py, backend/tests/test_meme_visibility.py
Interface: filter_meme_sections(data: dict) -> dict（不修改输入）.
- [x] 写失败测试，覆盖缓存/跨进程版本、别名/种子、撤销、空榜与保存响应。
- [x] 运行 pytest tests/test_meme_visibility.py --no-cov，确认行为失败。
- [x] 实现过滤、状态规则版本、保存文案、公开投影空榜。
- [x] 执行该测试和相邻热梗/公开页回归。

### Task 2: 浏览器与公开页立即更新
Files: frontend/src/App.jsx, frontend/src/components/DevPanel.jsx, frontend/public-pages/http.mjs, corresponding tests.
Interface: window event kichu:word-rules-changed；status.meme_rules_version.
- [x] 写失败测试：成功/失败保存事件、页面即时更新、公开请求刷新与失败关闭。
- [x] 运行定向 Vitest 和 node --test public-pages/http.test.mjs，确认失败。
- [x] 实现通知、版本轮询和公开页响应前刷新，更新后台生效说明。
- [x] 运行前后端完整测试和构建，独立审查，提交可审查变更并准备生产增量范围。
