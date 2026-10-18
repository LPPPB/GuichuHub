# Video observation consistency audit — 2026-10-18

## Confirmed cause

Read-only public API checks at the start of the investigation confirmed the scheduled dashboard snapshot last changed at 2026-10-17 03:45:06 (Beijing time). The two reported cards returned 89,427 and 324,473 views, equal to their first observation points. Their 2026-10-18 16:00 observations had reached 245,764 and 2,067,135 views.

The lightweight observer writes time-series rows without updating dashboard state. The API previously decorated snapshot rows with current radar/online information but left views and interaction counts unchanged. This mixed different observation times in one card.

## Fixed paths

- Dashboard ranking, potential videos and material candidates, plus their standalone list APIs: overlay all seven count fields and their source/time from one complete verified observation. Preserve section-specific order, scores and metadata; never mutate persisted snapshots.
- Reject incomplete, negative, non-finite, unverified and future observations. Preserve newer manual snapshots and real zeros. Existing repository batching avoids per-card queries.
- Card: show count observation time separately from publication and online time.
- Open page: status exposes observation/baseline revision. Existing polling reloads silently on revision, snapshot/source or minute change. Late older requests cannot overwrite a newer response. Expanded curves follow the card observation timestamp.
- Trend interaction rate: true zero stays zero; incomplete/invalid points remain missing and are not connected across gaps.
- Legacy radar: its live-attention axis now consumes the same online observation as the badge, including zero, stale and unavailable states.

## Adjacent findings and retained semantics

| Area | Evidence and boundary |
| --- | --- |
| BGM | `get_hot_songs` builds `plays` from full-crawl views and drops detailed observation provenance. These remain batch snapshots. Safely making them live requires carrying source/time through this conversion first. |
| Meme aggregates | `total_views`, heat and membership come from the full discovery batch; related videos are truncated to ten in the payload. Recomputing totals from only displayed/observed members would silently change the sample and is intentionally avoided. |
| Historical curves | The time-series API preserves raw observations, including legacy/partial rows. Card counts deliberately use the latest complete verified row; under invalid or legacy input these can have different latest valid times. No historical rows are deleted, rewritten or silently certified. |
| Observation cadence | Ranking/potential IDs are forced into lightweight coverage. Material/BGM videos may follow hot/warm/cold cadence. This patch uses the latest valid data already collected; it does not change collection quotas or ranking rules. |
| UP analysis/calendar | These use their own persisted analysis/backfill batches, not the dashboard card snapshot. Their batch semantics remain unchanged. Favorites are saved content, not a live-statistics view. |
| Full-crawl health | The old snapshot was verified, but no production Worker logs or private database were accessed. The reason the full snapshot had not advanced is not established by this patch. |

## Verification

Failing regressions were observed before the fixes: six API routes retained stale counts, true-zero overwrite failed, four component cases failed, the browser retained 24.6万 after a new observation, three legacy radar cases used cached 999 instead of the online observation, and status lacked observation revision.

Baseline: backend 675 passed; frontend 175 passed. Fix verification: backend `pytest -q --no-cov` 693 passed; frontend `npm test -- --maxWorkers=2` 187 passed after rebasing onto remote main `e99c019` (179 passed before that rebase); full production/SEO build passed. The backend tree is byte-for-byte unchanged by the rebase. Existing ranking layout checks passed at 1920/1280/900/390/320px. Browser verification uses built assets and synthetic responses at 1440px and 390px, with real cards and ECharts; it never accesses production.

Independent read-only review found no remaining important regression; its independent API suite passed 18 cases. Production deployment and production visual QA are outside this local fix. Main-checkout edits, production data, credentials and ranking rules are preserved.
