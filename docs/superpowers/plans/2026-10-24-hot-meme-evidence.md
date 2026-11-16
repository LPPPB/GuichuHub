# Hot Meme Evidence Implementation Plan

> Execute inline with TDD, followed by an independent review.

**Goal:** Require at least two independent videos per hot meme.
**Spec:** docs/superpowers/specs/2026-10-24-hot-meme-evidence-design.md.
**Files:** backend/collectors/bilibili.py; backend/tests/test_hot_meme_evidence.py; existing hot-meme and noise regression fixtures.

- [x] Add regressions for a single viral seed, repeated BV/title/tag hits, two different videos, plain-title evidence in both input orders, and ASCII word boundaries.
- [x] Observe expected failures (7 failed, 2 passed), then collect candidates first and aggregate distinct videos second; require video_count >= 2 while retaining the existing views threshold.
- [x] Update existing positive filter fixtures to provide two independent videos. Negative filter fixtures also have two videos so the count gate does not mask filtering regressions.
- [x] Run the related suite (129 passed, 10 database-dependent deselected), compare the material function to c7ee395, and independently review the isolated patch (56 tests passed, no actionable findings). Commit locally; do not deploy.

## Boundaries

Docker engine is unavailable, so database-dependent and full-suite validation remain incomplete. No production effect is claimed. No semantic disambiguation, English tag alias normalization, or merging of metadata from duplicate BV copies is added; existing first-copy BV dedup behavior is retained.
