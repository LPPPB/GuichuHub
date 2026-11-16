# Hot Meme Alias Implementation Plan

> Execute inline with superpowers:executing-plans and TDD; request an independent branch review.

**Goal:** Aggregate known and cosmetic aliases before applying the two-video gate.
**Architecture:** Pure normalization and validated release alias index, integrated only with get_hot_memes; retain bounded identity/evidence fields in the public projection.
**Tech Stack:** Python standard library, versioned JSON, pytest.
**Spec:** docs/superpowers/specs/2026-10-25-hot-meme-aliases-design.md.

## Global Constraints

Keep raw titles, BV deduplication, existing views gate, scoring and material behavior. No fuzzy semantic merge, runtime data writes, deployment or new dependencies.

## Review Focus

Conflicting aliases; English word separators; punctuation and malformed terms; normalized stopwords/seed identity; one BV matching several aliases; unknown-name stability; bounded public evidence.

### Task 1: Alias identity and aggregation

Files: backend/utils/meme_aliases.py (new), backend/utils/meme_aliases.json (new), backend/collectors/bilibili.py, backend/tests/test_hot_meme_aliases.py (new).

- [x] Add aggregate regressions for format and known aliases, no double counting, unknown discovery, and independent containing names; run and observe failure.
- [x] Add pure normalization/config validation cases, then implement normalize_meme_name/key, MemeAliasIndex.resolve and read-only release loading.
- [x] Group candidates by identity before the evidence gate, preserve original titles and matched keyword forms, remove substring dedup, run related tests.

### Task 2: Public identity/evidence contract

Files: backend/services/public_pages.py, backend/tests/test_public_pages.py.

- [x] Add failing public projection tests for meme_id/aliases/related matched keywords, limits and private-field exclusion.
- [x] Add explicit bounded projections, run related tests, verify unchanged material AST, and independently review before the local commit.

## Review outcome

The independent reviewer reported four P2 issues: alias-aware tag stopwords, operator preview disagreement, Unicode word boundaries and loss of original title match spelling. Eight failing regressions reproduced these and the new span-mapping behavior; all were fixed in one pass. Final related suite including the API startup boundary check: 173 passed, 10 database-dependent deselected. Source spans handle compatibility/casefold expansions and cross-character composition. Aggregation and preview share a hot-meme-specific decision path, preserving the general material rule.

Full-suite execution remains blocked at the Docker/PostgreSQL fixture. Live runtime settings, production persistence and deployment are not verified; no runtime state or history was rewritten.
