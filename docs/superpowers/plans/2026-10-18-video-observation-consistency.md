# Video observation consistency implementation plan

**Goal:** Fix stale card statistics and audit adjacent video displays.

**Architecture:** Overlay one complete, verified observation on each response row without changing stored ranking snapshots or scores. Use the same batched observation contexts as radar; preserve newer manual snapshots. Refresh expanded charts when the card observation changes.

**Constraints:** Preserve existing uncommitted work, runtime data and credentials. No production deployment. Keep ranking order and historical score semantics.

1. Reproduce card/curve divergence at dashboard and list API boundaries, including material candidates. Cover zero counts, partial/unverified/future observations, newer manual data, shared videos across lists and cache invalidation.
2. Overlay all seven count fields plus source/time atomically; reuse batched contexts and preserve section-specific ranking fields. Add a visible statistics timestamp.
3. Test and fix chart refresh on video/observation change, request races, missing interaction fields and true zero interaction.
4. Run backend/frontend suites, production build and desktop/mobile browser checks. Record adjacent audit findings and verification limits.
