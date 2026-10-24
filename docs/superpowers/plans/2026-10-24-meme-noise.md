# Meme Noise Filtering Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks inline; perform one fresh branch review at completion.

**Goal:** Remove obvious non-meme words from both derived lists without raising collection thresholds.

**Architecture:** Share conservative common-word and malformed-token checks between the two aggregators. Retain the hot-meme tag gate without introducing its name restrictions into materials. Limit suffix extraction to intact title segments.

**Tech Stack:** Python, jieba, pytest.

**Spec:** docs/superpowers/specs/2026-10-24-meme-noise-design.md (approved in chat).

## Global Constraints

- Isolated branch from verified origin/main e5435d3; preserve unrelated changes.
- Do not write runtime configuration, databases or deploy; keep thresholds and seed exemptions.
- Match ordinary noise as whole terms; preserve complete valid names.

## Review Focus

- Database overrides must not bypass mandatory common noise checks.
- Two-character seed terms must survive existing allowlist restrictions in materials.
- Names containing ordinary noise substrings must remain eligible.
- Punctuation-heavy titles must not yield fragments.
- Same BV must not inflate counts; retain existing hot-meme dedup behavior.

### Task 1: Shared obvious-noise filtering

**Files:** backend/collectors/bilibili.py; new backend/utils/meme_filters.py; new backend/tests/test_meme_noise.py.

**Interfaces:** A pure is_meme_noise(word, allowed_words=...) predicate for mandatory exact noise/format rules; collector helper combines runtime stopwords, optional legacy tag rules, and seed handling.

- [x] Add parameterized aggregate tests for live noise (计划/自己/AI/DJ/经典/神曲/魔性/一首/音乐推荐/音乐电台), valid names and seed overrides.
- [x] Run new tests; confirm aggregate assertions fail, then implement common predicate and reuse before counting/assigning videos.
- [x] Run related material, hot-meme, tag, stopword, word-rule and generation tests: 120 passed, 10 database-dependent deselected; full suite fixture blocked because Docker engine is absent.

### Task 2: Intact title keyword extraction

**Files:** backend/utils/scorer.py; backend/tests/test_meme_noise.py.

**Interfaces:** Keep extract_keywords_from_title(title) -> list[str].

- [x] Add regression for 《代号：神不言》UFSH2026参会实机技术演示&实机特别影像: reject 《代号：神.
- [x] Assert intact bracketed/suffix names still extract, including 面筋哥 and 生命线の小曲; reject unclosed delimiters from raw tags through aggregate tests.
- [x] Confirm failing tests, restrict suffix pattern boundaries and malformed-token filtering, then rerun related suite.
- [x] Save sampled before/after filter report; run appropriate checks, request independent review and fix findings before committing verified changes.

## Review and verification outcome

Two independent P2 findings were reproduced with 7 failing tests and fixed: avoid tag-only name restrictions for materials; cover ASCII square/curly delimiters. Original material greedy-assignment tests remain unchanged. This repair does not attempt unrestricted semantic meme recognition or alter existing material duplicate-input behavior.

The current public sample's candidate gate rejects 8/8 existing material labels and 3/13 hot-meme labels. This is a gate replay on displayed labels, not a regenerated source pool or an online rollout. Public sample and detailed report are retained under the user's GuichuHub资料/审查 directory. No runtime configuration or stored snapshot was changed.
