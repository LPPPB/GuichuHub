"""Business time-series and calendar queue persistence."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from html import unescape

from sqlalchemy import BigInteger, and_, case, cast, create_engine, distinct, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from storage.models import calendar_backfill_job_items, calendar_backfill_jobs, calendar_video_authors, calendar_videos, crawl_runs, up_card_cache, up_observations, ups, video_observations, video_snapshot_documents, video_tags, videos, word_observations

CN_TZ = timezone(timedelta(hours=8))


class BusinessRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    @classmethod
    def from_url(cls, url: str) -> "BusinessRepository":
        engine = create_engine(url, pool_pre_ping=True)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    def record_video(self, video: dict, ts: int | None = None, source: str | None = None) -> None:
        bvid = video.get("bvid")
        if not bvid:
            return
        row = {
            "bvid": bvid, "mid": video.get("mid"),
            "title": unescape(video.get("title") or "")[:200],
            "tid": video.get("tid"), "tname": video.get("tname"), "pub_date": video.get("pub_date"),
            "duration": video.get("duration"), "first_seen": video["first_seen"],
            "source": source or video.get("source"),
            "observe_tier": video.get("observe_tier", "hot"),
            "pic": video.get("cover") or video.get("pic"),
        }
        with self._sessions.begin() as session:
            existing_source = session.execute(select(videos.c.source).where(
                videos.c.bvid == bvid,
            ).with_for_update()).scalar_one_or_none()
            sources = set(filter(None, (existing_source or "").split(",")))
            sources.update(filter(None, (row["source"] or "").split(",")))
            if sources:
                row["source"] = ",".join(sorted(sources))
            session.execute(insert(videos).values(**row).on_conflict_do_update(
                index_elements=[videos.c.bvid],
                set_={
                    key: value for key, value in row.items()
                    if key not in {"bvid", "first_seen"} and value is not None
                },
            ))
            if ts is not None:
                metrics = {
                    "bvid": bvid, "ts": ts,
                    "views": video.get("views"), "likes": video.get("likes"),
                    "coins": video.get("coins"), "favorites": video.get("favorites"),
                    "shares": video.get("shares"), "comments": video.get("comments"),
                    "danmaku": video.get("danmaku"),
                    "online_count": video.get("online_count_raw", video.get("online_count")),
                    "online_precision": video.get("online_precision"),
                    "potential_score": video.get("potential_score"),
                }
                session.execute(insert(video_observations).values(**metrics).on_conflict_do_update(
                    index_elements=[video_observations.c.bvid, video_observations.c.ts],
                    set_={key: value for key, value in metrics.items() if key not in {"bvid", "ts"}},
                ))
                for tag in {str(value or "").strip() for value in (video.get("tags") or [])} - {""}:
                    session.execute(insert(video_tags).values(
                        bvid=bvid, tag=tag, ts=ts,
                    ).on_conflict_do_update(
                        index_elements=[video_tags.c.bvid, video_tags.c.tag],
                        set_={"ts": ts},
                    ))

    def record_observation(self, bvid: str, ts: int, metrics: dict) -> None:
        row = {"bvid": bvid, "ts": ts, "views": metrics.get("views"), "likes": metrics.get("likes")}
        statement = insert(video_observations).values(**row).on_conflict_do_update(
            index_elements=[video_observations.c.bvid, video_observations.c.ts], set_=row
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def scored_batches(self) -> list[dict]:
        """Return historical score batches without exposing query primitives."""
        with self._sessions() as session:
            rows = session.execute(select(
                video_observations.c.ts,
                func.count().label("count"),
            ).where(
                video_observations.c.potential_score.is_not(None),
                video_observations.c.views.is_not(None),
            ).group_by(video_observations.c.ts).order_by(
                video_observations.c.ts.desc(),
            )).mappings()
            return [dict(row) for row in rows]

    def backtest_rows(self, ts: int, end_ts: int, min_views: int) -> dict:
        """Return one scored batch plus its last observation in the review window."""
        with self._sessions() as session:
            base_rows = session.execute(select(
                video_observations.c.bvid,
                video_observations.c.views,
                video_observations.c.potential_score,
                videos.c.title,
                ups.c.name.label("author"),
            ).join(
                videos, videos.c.bvid == video_observations.c.bvid,
            ).outerjoin(
                ups, ups.c.mid == videos.c.mid,
            ).where(
                video_observations.c.ts == ts,
                video_observations.c.potential_score.is_not(None),
                video_observations.c.views.is_not(None),
            )).mappings().all()
            eligible = [row for row in base_rows if row["views"] >= min_views]
            if not eligible:
                return {"scored_count": len(base_rows), "unverified": 0, "rows": []}
            bvids = [row["bvid"] for row in eligible]
            later_rows = session.execute(select(
                video_observations.c.bvid,
                video_observations.c.views,
                video_observations.c.ts,
            ).where(
                video_observations.c.bvid.in_(bvids),
                video_observations.c.ts > ts,
                video_observations.c.ts <= end_ts,
                video_observations.c.views.is_not(None),
            ).order_by(
                video_observations.c.bvid,
                video_observations.c.ts.desc(),
            )).mappings()
            latest = {}
            for row in later_rows:
                latest.setdefault(row["bvid"], row["views"])
        verified = []
        for row in eligible:
            later_views = latest.get(row["bvid"])
            if later_views is None:
                continue
            verified.append({**dict(row), "later_views": later_views})
        return {
            "scored_count": len(base_rows),
            "unverified": len(eligible) - len(verified),
            "rows": verified,
        }

    def development_stats(self) -> dict:
        """Return the operator dashboard's PostgreSQL health summary."""
        with self._sessions() as session:
            revision = session.execute(text(
                "SELECT version_num FROM app.alembic_version"
            )).scalar_one_or_none()
            runs = dict(session.execute(select(
                crawl_runs.c.status, func.count().label("count"),
            ).group_by(crawl_runs.c.status)).all())
            stale = session.execute(select(
                crawl_runs.c.id, crawl_runs.c.started_at, crawl_runs.c.trigger_source,
            ).where(crawl_runs.c.status == "running").order_by(
                crawl_runs.c.started_at.desc(),
            ).limit(20)).mappings().all()
            observation_counts = session.execute(select(
                func.count(distinct(video_observations.c.ts)).label("batches"),
                func.count().label("rows"),
            )).mappings().one()
            return {
                "alembic_revision": revision,
                # Baseline 0001 replaces the historical public V1–V11 schema marker.
                "schema_version": 11,
                "crawl_runs": runs,
                "stale_running": [dict(row) for row in stale],
                "video_obs_batches": observation_counts["batches"],
                "video_obs_rows": observation_counts["rows"],
                "videos": session.execute(select(func.count()).select_from(videos)).scalar_one(),
                "ups": session.execute(select(func.count()).select_from(ups)).scalar_one(),
            }

    def latest_video_observation_ts(self) -> int | None:
        with self._sessions() as session:
            result = session.execute(select(func.max(video_observations.c.ts))).scalar_one()
            return int(result) if result is not None else None

    def interaction_quality_rows(self, ts: int, tids: list[int], min_views: int,
                                 max_views: int) -> list[dict]:
        query = select(
            video_observations.c.bvid, video_observations.c.views, video_observations.c.likes,
            video_observations.c.coins, video_observations.c.favorites,
            video_observations.c.shares, video_observations.c.comments,
            video_observations.c.danmaku, video_observations.c.online_count,
            videos.c.title, videos.c.mid, videos.c.tname, videos.c.pub_date,
            ups.c.name.label("author"),
        ).join(videos, videos.c.bvid == video_observations.c.bvid).outerjoin(
            ups, videos.c.mid == ups.c.mid,
        ).where(
            video_observations.c.ts == ts,
            videos.c.tid.in_(tids),
            video_observations.c.views.between(min_views, max_views),
        )
        with self._sessions() as session:
            return [dict(row) for row in session.execute(query).mappings()]

    def follower_growth(self, days: int, limit: int) -> list[dict]:
        follower_count = cast(up_observations.c.payload["follower_count"].astext, BigInteger)
        with self._sessions() as session:
            latest_ts = session.execute(select(func.max(up_observations.c.ts))).scalar_one()
            if latest_ts is None:
                return []
            since = int(latest_ts) - days * 86400
            previous_ts = session.execute(select(func.min(up_observations.c.ts)).where(
                up_observations.c.ts >= since, follower_count > 0,
            )).scalar_one()
            if previous_ts is None:
                return []
            rows = session.execute(select(
                up_observations.c.mid, ups.c.name, ups.c.face, up_observations.c.ts,
                follower_count.label("follower_count"),
            ).outerjoin(ups, ups.c.mid == up_observations.c.mid).where(
                up_observations.c.ts.in_((int(previous_ts), int(latest_ts))),
            )).mappings().all()
        by_mid = {}
        for row in rows:
            by_mid.setdefault(row["mid"], {})[row["ts"]] = row["follower_count"]
        items = []
        for mid, counts in by_mid.items():
            if int(latest_ts) not in counts or int(previous_ts) not in counts:
                continue
            before = int(counts[int(previous_ts)] or 0)
            current = int(counts[int(latest_ts)] or 0)
            growth = current - before
            profile = next(row for row in rows if row["mid"] == mid)
            items.append({
                "mid": mid, "name": profile["name"] or "", "face": profile["face"] or "",
                "follower_before": before, "follower_now": current, "growth": growth,
                "growth_rate": round(growth / before * 100, 2) if before > 0 else 0.0,
                "start_ts": int(previous_ts), "end_ts": int(latest_ts),
            })
        return sorted(items, key=lambda item: item["growth"], reverse=True)[:limit]

    def tag_heat_rows(self, tids: list[int], min_count: int) -> list[dict]:
        latest = select(
            video_observations.c.bvid,
            func.max(video_observations.c.ts).label("ts"),
        ).group_by(video_observations.c.bvid).subquery()
        query = select(
            video_tags.c.tag,
            func.count(distinct(video_tags.c.bvid)).label("cnt"),
            func.avg(video_observations.c.views).label("avg_views"),
            func.avg(video_observations.c.likes).label("avg_likes"),
            func.avg(video_observations.c.coins).label("avg_coins"),
            func.avg(video_observations.c.favorites).label("avg_favs"),
        ).join(videos, videos.c.bvid == video_tags.c.bvid).join(
            latest, latest.c.bvid == video_tags.c.bvid,
        ).join(video_observations, and_(
            video_observations.c.bvid == latest.c.bvid,
            video_observations.c.ts == latest.c.ts,
        )).where(videos.c.tid.in_(tids)).group_by(video_tags.c.tag).having(
            func.count(distinct(video_tags.c.bvid)) >= min_count,
        )
        with self._sessions() as session:
            return [dict(row) for row in session.execute(query).mappings()]

    def mark_candidates_hot(self, bvids: list[str]) -> None:
        if not bvids:
            return
        with self._sessions.begin() as session:
            session.execute(videos.update().where(videos.c.bvid.in_(bvids)).values(observe_tier="hot"))

    def refresh_observe_tiers(self, now: int) -> int:
        day14 = now - 14 * 86400
        day60 = now - 60 * 86400
        ranked = select(
            video_observations.c.bvid,
            video_observations.c.views,
            func.row_number().over(
                partition_by=video_observations.c.bvid,
                order_by=video_observations.c.ts.desc(),
            ).label("rank"),
        ).join(videos, videos.c.bvid == video_observations.c.bvid).where(
            videos.c.pub_date <= day60,
        ).subquery()
        with self._sessions.begin() as session:
            session.execute(videos.update().where(videos.c.pub_date > day14).values(observe_tier="hot"))
            session.execute(videos.update().where(
                videos.c.pub_date <= day14, videos.c.pub_date > day60,
            ).values(observe_tier="warm"))
            session.execute(videos.update().where(videos.c.pub_date <= day60).values(observe_tier="warm"))
            observations = session.execute(select(
                ranked.c.bvid, ranked.c.views, ranked.c.rank,
            ).where(ranked.c.rank <= 2).order_by(ranked.c.bvid, ranked.c.rank)).mappings()
            latest_by_video = {}
            for row in observations:
                latest_by_video.setdefault(row["bvid"], []).append(row["views"])
            cold_bvids = [
                bvid for bvid, values in latest_by_video.items()
                if len(values) >= 2 and values[0] is not None and values[1] is not None
                and values[0] - values[1] < 500
            ]
            if cold_bvids:
                session.execute(videos.update().where(videos.c.bvid.in_(cold_bvids)).values(
                    observe_tier="cold",
                ))
            return len(cold_bvids)

    def observation_targets(self, now: int, hot_limit: int = 500) -> list[str]:
        latest = select(
            video_observations.c.bvid,
            func.max(video_observations.c.ts).label("latest_ts"),
        ).group_by(video_observations.c.bvid).subquery()
        with self._sessions() as session:
            hot = session.execute(select(videos.c.bvid).where(
                videos.c.observe_tier == "hot",
            ).order_by(videos.c.first_seen.desc()).limit(hot_limit)).scalars().all()
            warm = session.execute(select(videos.c.bvid).outerjoin(
                latest, latest.c.bvid == videos.c.bvid,
            ).where(
                videos.c.observe_tier == "warm",
                func.coalesce(latest.c.latest_ts, 0) < now - 20 * 3600,
            ).limit(2000)).scalars().all()
            return [*hot, *warm]

    def bursting_videos(self, window_hours: float, threshold: float, limit: int,
                        now: int, tids: list[int]) -> list[dict]:
        lookback = now - 48 * 3600
        query = select(
            videos.c.bvid, videos.c.title, videos.c.tid, videos.c.tname,
            videos.c.pub_date, videos.c.mid, videos.c.pic, ups.c.name.label("owner_name"),
            video_observations.c.ts, video_observations.c.views,
        ).join(video_observations, videos.c.bvid == video_observations.c.bvid).outerjoin(
            ups, videos.c.mid == ups.c.mid,
        ).where(
            videos.c.observe_tier == "hot", videos.c.tid.in_(tids),
            video_observations.c.ts >= lookback, video_observations.c.views.is_not(None),
        ).order_by(videos.c.bvid, video_observations.c.ts)
        with self._sessions() as session:
            rows = session.execute(query).mappings().all()

        by_bvid: dict[str, list[dict]] = defaultdict(list)
        metadata = {}
        for row in rows:
            bvid = row["bvid"]
            by_bvid[bvid].append({"ts": row["ts"], "views": row["views"]})
            metadata.setdefault(bvid, {
                "bvid": bvid, "title": unescape(row["title"] or ""), "pic": row["pic"],
                "owner": {"name": row["owner_name"]} if row["owner_name"] else None,
                "tid": row["tid"], "pubdate": row["pub_date"],
            })

        window_seconds = window_hours * 3600
        results = []
        for bvid, points in by_bvid.items():
            if len(points) < 2:
                continue
            latest = points[-1]
            win1_start = next(
                (point for point in points if point["ts"] >= latest["ts"] - window_seconds), None,
            )
            if not win1_start or win1_start["ts"] >= latest["ts"]:
                continue
            dt1 = (latest["ts"] - win1_start["ts"]) / 3600.0
            if dt1 <= 0:
                continue
            speed1 = (latest["views"] - win1_start["views"]) / dt1
            if speed1 <= 0:
                continue

            win2_start = next(
                (point for point in points if point["ts"] >= win1_start["ts"] - window_seconds), None,
            )
            speed2 = None
            bursting = False
            if win2_start and win2_start["ts"] < win1_start["ts"]:
                dt2 = (win1_start["ts"] - win2_start["ts"]) / 3600.0
                if dt2 > 0:
                    speed2 = (win1_start["views"] - win2_start["views"]) / dt2
                    bursting = speed2 > 0 and speed1 >= speed2 * threshold
            spark = [point["views"] for point in points]
            if len(spark) > 12:
                step = (len(spark) - 1) / 11.0
                spark = [spark[int(round(index * step))] for index in range(12)]
            results.append({
                **metadata[bvid], "views": latest["views"], "speed": round(speed1, 1),
                "prev_speed": round(speed2, 1) if speed2 is not None and speed2 > 0 else None,
                "speed_ratio": round(speed1 / speed2, 2) if speed2 and speed2 > 0 else None,
                "is_bursting": bursting, "latest_ts": latest["ts"],
                "obs_count": len(points), "spark": spark,
            })
        results.sort(key=lambda item: item["speed"], reverse=True)
        return results[:limit]

    def video_trend(self, bvid: str, start_ts: int) -> list[dict]:
        with self._sessions() as session:
            rows = session.execute(
                select(
                    video_observations.c.ts, video_observations.c.views, video_observations.c.likes,
                )
                .where(video_observations.c.bvid == bvid, video_observations.c.ts >= start_ts)
                .order_by(video_observations.c.ts)
            ).mappings()
            return [dict(row) for row in rows]

    def video_observation_trend(self, bvid: str, start_ts: int) -> list[dict]:
        columns = (
            video_observations.c.ts, video_observations.c.views, video_observations.c.likes,
            video_observations.c.coins, video_observations.c.favorites,
            video_observations.c.shares, video_observations.c.comments,
            video_observations.c.danmaku, video_observations.c.online_count,
            video_observations.c.online_precision, video_observations.c.potential_score,
        )
        with self._sessions() as session:
            rows = session.execute(
                select(*columns)
                .where(video_observations.c.bvid == bvid, video_observations.c.ts >= start_ts)
                .order_by(video_observations.c.ts)
            ).mappings()
            return [dict(row) for row in rows]

    def begin_crawl_run(self, trigger: str, started_at: int) -> int:
        with self._sessions.begin() as session:
            return session.execute(insert(crawl_runs).values(
                started_at=started_at, status="running", trigger_source=trigger, stats={}
            ).returning(crawl_runs.c.id)).scalar_one()

    def finish_crawl_run(self, run_id: int, status: str, stats: dict, finished_at: int) -> None:
        with self._sessions.begin() as session:
            session.execute(crawl_runs.update().where(crawl_runs.c.id == run_id).values(
                status=status, stats=stats, finished_at=finished_at
            ))

    def record_words(self, words: list[dict], ts: int, scope: str) -> None:
        rows = [{"word": word["word"], "count": word["count"], "ts": ts, "scope": scope} for word in words if word.get("word")]
        if not rows:
            return
        with self._sessions.begin() as session:
            session.execute(insert(word_observations).values(rows).on_conflict_do_update(
                index_elements=[word_observations.c.word, word_observations.c.ts, word_observations.c.scope],
                set_={"count": insert(word_observations).excluded.count},
            ))

    def word_rows(self, ts: int) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(word_observations.c.word, word_observations.c.count, word_observations.c.scope)
                .where(word_observations.c.ts == ts).order_by(word_observations.c.word)
            ).mappings()]

    def rising_word_batch_totals(self, limit: int) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(word_observations.c.ts, func.sum(word_observations.c.count).label("total_count"))
                .where(word_observations.c.scope == "danmaku")
                .group_by(word_observations.c.ts)
                .order_by(word_observations.c.ts.desc())
                .limit(limit)
            ).mappings()]

    def rising_word_observations(self, timestamps: list[int]) -> list[dict]:
        if not timestamps:
            return []
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(word_observations.c.word, word_observations.c.ts, word_observations.c.count)
                .where(word_observations.c.scope == "danmaku", word_observations.c.ts.in_(timestamps))
            ).mappings()]

    def crawl_run(self, run_id: int) -> dict:
        with self._sessions() as session:
            row = session.execute(select(crawl_runs.c.status, crawl_runs.c.stats).where(crawl_runs.c.id == run_id)).mappings().one()
            return dict(row)

    def upsert_snapshot_document(self, ts: int, field: str, payload: list | dict) -> int:
        item_count = len(payload) if isinstance(payload, list) else 1
        with self._sessions.begin() as session:
            session.execute(insert(video_snapshot_documents).values(
                ts=ts, field=field, payload=payload, item_count=item_count
            ).on_conflict_do_update(
                index_elements=[video_snapshot_documents.c.ts, video_snapshot_documents.c.field],
                set_={"payload": payload, "item_count": item_count},
            ))
        return item_count

    def snapshot_document(self, ts: int, field: str) -> dict:
        with self._sessions() as session:
            return dict(session.execute(
                select(video_snapshot_documents.c.payload, video_snapshot_documents.c.item_count)
                .where(video_snapshot_documents.c.ts == ts, video_snapshot_documents.c.field == field)
            ).mappings().one())

    def snapshot_fields(self, ts: int, fields: tuple[str, ...]) -> dict:
        with self._sessions() as session:
            return {
                row["field"]: row["payload"]
                for row in session.execute(
                    select(video_snapshot_documents.c.field, video_snapshot_documents.c.payload)
                    .where(video_snapshot_documents.c.ts == ts,
                           video_snapshot_documents.c.field.in_(fields))
                ).mappings()
            }

    def snapshot_documents_between(self, fields: tuple[str, ...], start_ts: int, end_ts: int) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(video_snapshot_documents.c.ts, video_snapshot_documents.c.field,
                       video_snapshot_documents.c.payload)
                .where(video_snapshot_documents.c.field.in_(fields),
                       video_snapshot_documents.c.ts.between(start_ts, end_ts))
                .order_by(video_snapshot_documents.c.ts, video_snapshot_documents.c.field)
            ).mappings()]

    def latest_snapshot_ts(self, fields: tuple[str, ...]) -> int | None:
        with self._sessions() as session:
            return session.execute(
                select(func.max(video_snapshot_documents.c.ts))
                .where(video_snapshot_documents.c.field.in_(fields))
            ).scalar_one()

    def upsert_snapshot_batch(self, ts: int, fields: dict[str, list | dict]) -> int:
        rows = [
            {"ts": ts, "field": field, "payload": payload,
             "item_count": len(payload) if isinstance(payload, list) else 1}
            for field, payload in fields.items()
        ]
        with self._sessions.begin() as session:
            for row in rows:
                session.execute(insert(video_snapshot_documents).values(**row).on_conflict_do_update(
                    index_elements=[video_snapshot_documents.c.ts, video_snapshot_documents.c.field],
                    set_={"payload": row["payload"], "item_count": row["item_count"]},
                ))
        return len(rows)

    def upsert_up_observations(
        self, ts: int, observations: list[dict], play_ranking: list[dict] | None = None,
        active_ranking: list[dict] | None = None,
    ) -> int:
        rows = [row for row in observations if row.get("mid") is not None]
        play_rank = {row.get("mid"): index for index, row in enumerate(play_ranking or [], 1)}
        activity_rank = {row.get("mid"): index for index, row in enumerate(active_ranking or [], 1)}
        with self._sessions.begin() as session:
            for row in rows:
                session.execute(insert(ups).values(
                    mid=row["mid"], name=row.get("name"), face=row.get("face"), tracked=False
                ).on_conflict_do_nothing(index_elements=[ups.c.mid]))
                payload = dict(row)
                if play_ranking is not None:
                    payload["play_rank"] = play_rank.get(row["mid"], 0)
                if active_ranking is not None:
                    payload["activity_rank"] = activity_rank.get(row["mid"], 0)
                session.execute(insert(up_observations).values(
                    mid=row["mid"], ts=ts, payload=payload
                ).on_conflict_do_update(
                    index_elements=[up_observations.c.mid, up_observations.c.ts], set_={"payload": payload}
                ))
        return len(rows)

    def up_observation(self, mid: int, ts: int) -> dict:
        with self._sessions() as session:
            return dict(session.execute(
                select(up_observations.c.mid, up_observations.c.payload)
                .where(up_observations.c.mid == mid, up_observations.c.ts == ts)
            ).mappings().one())

    def latest_up_observation_ts(self) -> int | None:
        with self._sessions() as session:
            return session.execute(select(func.max(up_observations.c.ts))).scalar_one()

    def up_observation_rows(self, ts: int) -> list[dict]:
        with self._sessions() as session:
            return [dict(row) for row in session.execute(
                select(up_observations.c.mid, up_observations.c.payload,
                       ups.c.name, ups.c.face)
                .outerjoin(ups, ups.c.mid == up_observations.c.mid)
                .where(up_observations.c.ts == ts)
            ).mappings()]

    def write_up_card_cache(self, mid: int, card: dict, fetched_at: int) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(up_card_cache).values(
                mid=mid, payload=card, fetched_at=fetched_at,
            ).on_conflict_do_update(
                index_elements=[up_card_cache.c.mid],
                set_={"payload": card, "fetched_at": fetched_at},
            ))

    def up_card_cache(self, mid: int) -> dict | None:
        with self._sessions() as session:
            row = session.execute(
                select(up_card_cache.c.payload).where(up_card_cache.c.mid == mid)
            ).mappings().first()
            return row["payload"] if row else None

    def read_up_card_cache(self, mid: int, now: int, ttl: int) -> dict | None:
        with self._sessions() as session:
            row = session.execute(
                select(up_card_cache.c.payload, up_card_cache.c.fetched_at)
                .where(up_card_cache.c.mid == mid)
            ).mappings().first()
            if row is None or now - row["fetched_at"] > ttl:
                return None
            return row["payload"]

    def upsert_calendar_videos(self, rows: list[dict], authors: set[tuple[str, int]], fetched: int, now: int) -> dict:
        """Persist a normalized calendar batch and its complete author relation."""
        bvids = [row["bvid"] for row in rows]
        with self._sessions.begin() as session:
            existing = {
                row["bvid"]: dict(row)
                for row in session.execute(
                    select(calendar_videos.c.bvid, calendar_videos.c.pub_date,
                           calendar_videos.c.views, calendar_videos.c.title)
                    .where(calendar_videos.c.bvid.in_(bvids))
                    .order_by(calendar_videos.c.bvid, calendar_videos.c.views.desc())
                ).mappings()
            }
            inserted = updated = unchanged = 0
            for row in rows:
                old = existing.get(row["bvid"])
                if old is None:
                    inserted += 1
                elif (old["pub_date"] == row["pub_date"] and old["views"] == row["views"]
                      and (old["title"] or "") == row["title"]):
                    unchanged += 1
                else:
                    updated += 1

            for bvid, mid in authors:
                session.execute(insert(ups).values(mid=mid, tracked=False).on_conflict_do_nothing(
                    index_elements=[ups.c.mid]
                ))
            for row in rows:
                session.execute(insert(videos).values(
                    bvid=row["bvid"], mid=row["mid"], title=row["title"],
                    pub_date=row["pub_date"], first_seen=now, source="calendar"
                ).on_conflict_do_nothing(index_elements=[videos.c.bvid]))
                session.execute(insert(calendar_videos).values(
                    **row, fetched_at=now, last_seen_at=now, missing_count=0, status="active"
                ).on_conflict_do_update(
                    index_elements=[calendar_videos.c.bvid, calendar_videos.c.mid],
                    set_={
                        "pub_date": row["pub_date"], "pub_date_str": row["pub_date_str"],
                        "views": func.greatest(calendar_videos.c.views, row["views"]),
                        "title": row["title"], "fetched_at": now, "last_seen_at": now,
                        "missing_count": 0, "status": "active",
                    },
                ))
            session.execute(insert(calendar_video_authors).values([
                {"bvid": bvid, "mid": mid, "last_seen_at": now,
                 "missing_count": 0, "status": "active"}
                for bvid, mid in authors
            ]).on_conflict_do_update(
                index_elements=[calendar_video_authors.c.bvid, calendar_video_authors.c.mid],
                set_={"last_seen_at": now, "missing_count": 0, "status": "active"},
            ))
        return {
            "fetched": fetched, "valid": len(rows), "inserted": inserted,
            "updated": updated, "unchanged": unchanged, "invalid": fetched - len(authors),
        }

    def calendar_video(self, bvid: str, mid: int) -> dict:
        with self._sessions() as session:
            return dict(session.execute(
                select(calendar_videos.c.views, calendar_videos.c.pub_date_str)
                .where(calendar_videos.c.bvid == bvid, calendar_videos.c.mid == mid)
            ).mappings().one())

    @staticmethod
    def _calendar_author_filter(query, mids: list[int] | None):
        if mids is None:
            return query
        active_videos = select(calendar_video_authors.c.bvid).where(
            calendar_video_authors.c.status == "active",
            calendar_video_authors.c.mid.in_(mids),
        )
        return query.where(calendar_videos.c.bvid.in_(active_videos))

    def calendar_data(self, year_start: int, year_end: int, mids: list[int] | None) -> dict:
        if mids == []:
            return {}
        query = select(calendar_videos.c.pub_date, calendar_videos.c.views).where(
            calendar_videos.c.pub_date.between(year_start, year_end),
            calendar_videos.c.status == "active",
        )
        with self._sessions() as session:
            rows = session.execute(self._calendar_author_filter(query, mids)).mappings()
            result = {}
            for row in rows:
                day = datetime.fromtimestamp(row["pub_date"], CN_TZ).date().isoformat()
                value = result.setdefault(day, {"count": 0, "views": 0})
                value["count"] += 1
                value["views"] += int(row["views"] or 0)
            return result

    def calendar_freshness(self, mids: list[int] | None, year_start: int | None = None, year_end: int | None = None) -> int | None:
        if mids == []:
            return None
        query = select(func.max(calendar_videos.c.fetched_at)).where(
            calendar_videos.c.status == "active",
        )
        if year_start is not None and year_end is not None:
            query = query.where(calendar_videos.c.pub_date >= year_start,
                                calendar_videos.c.pub_date < year_end)
        with self._sessions() as session:
            result = session.execute(self._calendar_author_filter(query, mids)).scalar_one()
            return int(result) if result else None

    def calendar_recent_series(self, mids: list[int] | None, days: int) -> list[dict]:
        days = max(1, min(int(days or 60), 366))
        today = datetime.now(CN_TZ).date()
        start_date = today - timedelta(days=days - 1)
        start_ts = int(datetime.combine(start_date, datetime.min.time(), tzinfo=CN_TZ).timestamp())
        end_ts = int(datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=CN_TZ).timestamp())
        aggregate = {}
        if mids != []:
            query = select(calendar_videos.c.pub_date, calendar_videos.c.views).where(
                calendar_videos.c.pub_date >= start_ts,
                calendar_videos.c.pub_date < end_ts,
                calendar_videos.c.status == "active",
            )
            with self._sessions() as session:
                for row in session.execute(self._calendar_author_filter(query, mids)).mappings():
                    day = datetime.fromtimestamp(row["pub_date"], CN_TZ).date().isoformat()
                    value = aggregate.setdefault(day, {"count": 0, "views": 0})
                    value["count"] += 1
                    value["views"] += int(row["views"] or 0)
        return [
            {"date": (start_date + timedelta(days=offset)).isoformat(),
             **aggregate.get((start_date + timedelta(days=offset)).isoformat(), {"count": 0, "views": 0})}
            for offset in range(days)
        ]

    def calendar_day_videos(self, date_str: str, mids: list[int] | None, limit: int) -> list[dict]:
        if mids == []:
            return []
        query = select(
            calendar_videos.c.bvid, calendar_videos.c.mid, calendar_videos.c.title,
            calendar_videos.c.views, calendar_videos.c.pub_date, calendar_videos.c.fetched_at,
        ).where(calendar_videos.c.status == "active")
        if len(date_str) == 10:
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=CN_TZ)
            except ValueError:
                return []
            query = query.where(
                calendar_videos.c.pub_date >= int(day.timestamp()),
                calendar_videos.c.pub_date < int((day + timedelta(days=1)).timestamp()),
            )
        elif len(date_str) == 5:
            query = query.where(calendar_videos.c.pub_date_str == date_str)
        else:
            return []
        query = self._calendar_author_filter(query, mids).order_by(
            calendar_videos.c.views.desc(), calendar_videos.c.bvid,
        ).limit(limit)
        with self._sessions() as session:
            return [dict(row) for row in session.execute(query).mappings()]

    def publish_habits(self, mids: list[int] | None, days: int, now: int) -> dict:
        days = int(days)
        if mids == []:
            return {
                "hourly": [], "weekly": [],
                "meta": {"days": days, "video_count": 0, "fetched_at": None,
                         "latest_pub_date": None},
            }
        since = now - days * 86400
        query = select(
            calendar_videos.c.bvid,
            func.max(calendar_videos.c.pub_date).label("pub_date"),
            func.max(calendar_videos.c.views).label("views"),
            func.max(calendar_videos.c.fetched_at).label("fetched_at"),
        ).where(
            calendar_videos.c.pub_date >= since,
            calendar_videos.c.status == "active",
        ).group_by(calendar_videos.c.bvid)
        query = self._calendar_author_filter(query, mids)
        with self._sessions() as session:
            values = list(session.execute(query).mappings())
        hourly, weekly = {}, {}
        for row in values:
            local_time = datetime.fromtimestamp(row["pub_date"], CN_TZ)
            hour = local_time.hour
            weekday = local_time.weekday()
            hourly.setdefault(hour, []).append(int(row["views"] or 0))
            weekly.setdefault(weekday, []).append(int(row["views"] or 0))
        return {
            "hourly": [
                {"hour": hour, "count": len(views), "avg_views": int(sum(views) / len(views))}
                for hour, views in sorted(hourly.items())
            ],
            "weekly": [
                {"weekday": weekday, "count": len(views), "avg_views": int(sum(views) / len(views))}
                for weekday, views in sorted(weekly.items())
            ],
            "meta": {
                "days": days, "video_count": len(values),
                "fetched_at": max((int(row["fetched_at"]) for row in values if row["fetched_at"]), default=None),
                "latest_pub_date": max((int(row["pub_date"]) for row in values), default=None),
            },
        }

    def up_names(self, mids: list[int]) -> dict[int, str]:
        if not mids:
            return {}
        with self._sessions() as session:
            return {
                int(row["mid"]): row["name"]
                for row in session.execute(
                    select(ups.c.mid, ups.c.name).where(ups.c.mid.in_(mids))
                ).mappings()
            }

    def register_up(self, mid: int, name: str = "", face: str = "") -> None:
        with self._sessions.begin() as session:
            session.execute(insert(ups).values(
                mid=mid, name=name or "", face=face or "", tracked=True,
            ).on_conflict_do_update(
                index_elements=[ups.c.mid],
                set_={"name": name or "", "face": face or "", "tracked": True},
            ))

    def reconcile_calendar_author(self, mid: int, year_start: int, year_end: int,
                                  seen_bvids: set[str], missing_threshold: int) -> dict:
        seen = {str(value) for value in seen_bvids if value}
        with self._sessions.begin() as session:
            rows = session.execute(
                select(calendar_video_authors.c.bvid, calendar_video_authors.c.missing_count)
                .join(calendar_videos, calendar_videos.c.bvid == calendar_video_authors.c.bvid)
                .where(
                    calendar_video_authors.c.mid == int(mid),
                    calendar_videos.c.pub_date >= year_start,
                    calendar_videos.c.pub_date < year_end,
                )
                .with_for_update(of=calendar_video_authors)
            ).mappings().all()
            missing = [row for row in rows if row["bvid"] not in seen]
            restored = sum(1 for row in rows if row["bvid"] in seen and row["missing_count"] > 0)
            for row in missing:
                count = int(row["missing_count"] or 0) + 1
                session.execute(calendar_video_authors.update().where(
                    calendar_video_authors.c.bvid == row["bvid"],
                    calendar_video_authors.c.mid == int(mid),
                ).values(missing_count=count,
                         status="unavailable" if count >= missing_threshold else "active"))
            if seen:
                session.execute(calendar_video_authors.update().where(
                    calendar_video_authors.c.mid == int(mid),
                    calendar_video_authors.c.bvid.in_(seen),
                ).values(missing_count=0, status="active"))
            unavailable = sum(
                1 for row in missing
                if int(row["missing_count"] or 0) + 1 >= missing_threshold
            )
            return {
                "checked": len(rows), "missing": len(missing),
                "unavailable": unavailable, "restored": restored,
            }

    def enqueue_calendar_items(self, job_id: str, mids: list[int]) -> None:
        with self._sessions.begin() as session:
            session.execute(insert(calendar_backfill_jobs).values(
                id=job_id, mode="test", status="queued", payload={}, created_at=0, updated_at=0
            ).on_conflict_do_nothing(index_elements=[calendar_backfill_jobs.c.id]))
            session.execute(insert(calendar_backfill_job_items).values([
                {"job_id": job_id, "mid": mid, "status": "queued", "payload": {}} for mid in mids
            ]).on_conflict_do_nothing(index_elements=[calendar_backfill_job_items.c.job_id, calendar_backfill_job_items.c.mid]))

    def claim_calendar_item(self, worker_id: str) -> dict | None:
        with self._sessions.begin() as session:
            item = session.execute(
                select(calendar_backfill_job_items)
                .where(calendar_backfill_job_items.c.status == "queued")
                .order_by(calendar_backfill_job_items.c.job_id, calendar_backfill_job_items.c.mid)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).mappings().first()
            if item is None:
                return None
            session.execute(
                calendar_backfill_job_items.update()
                .where(calendar_backfill_job_items.c.job_id == item["job_id"], calendar_backfill_job_items.c.mid == item["mid"])
                .values(status="running", worker_id=worker_id)
            )
            return {"job_id": item["job_id"], "mid": item["mid"], "worker_id": worker_id}

    def _calendar_job(self, session, job_id: str, include_items: bool = True) -> dict | None:
        job = session.execute(select(calendar_backfill_jobs).where(
            calendar_backfill_jobs.c.id == job_id,
        )).mappings().first()
        if job is None:
            return None
        result = dict(job["payload"] or {})
        for key, default in (
            ("total_ups", 0), ("processed_ups", 0), ("succeeded_ups", 0),
            ("empty_ups", 0), ("failed_ups", 0), ("partial_ups", 0),
            ("total_videos", 0),
        ):
            result.setdefault(key, default)
        total = int(result["total_ups"] or 0)
        result["progress_percent"] = (
            round(int(result["processed_ups"] or 0) * 100 / total) if total else 100
        )
        result.update({
            "id": job["id"], "mode": job["mode"], "status": job["status"],
            "created_at": job["created_at"], "updated_at": job["updated_at"],
        })
        if include_items:
            items = []
            for item in session.execute(select(calendar_backfill_job_items).where(
                calendar_backfill_job_items.c.job_id == job_id,
            ).order_by(calendar_backfill_job_items.c.mid)).mappings():
                value = dict(item["payload"] or {})
                value.update({"mid": item["mid"], "status": item["status"]})
                items.append(value)
            result["items"] = items
        return result

    def calendar_job(self, job_id: str, include_items: bool = True) -> dict | None:
        with self._sessions() as session:
            return self._calendar_job(session, job_id, include_items=include_items)

    def active_calendar_job(self) -> dict | None:
        with self._sessions() as session:
            job_id = session.execute(
                select(calendar_backfill_jobs.c.id)
                .where(calendar_backfill_jobs.c.status.in_(("running", "queued")))
                .order_by(
                    case((calendar_backfill_jobs.c.status == "running", 0), else_=1),
                    calendar_backfill_jobs.c.created_at,
                )
                .limit(1)
            ).scalar_one_or_none()
            return self._calendar_job(session, job_id) if job_id else None

    def enqueue_calendar_job(self, mode: str, entries: list[dict], now: int, **payload) -> tuple[dict, bool]:
        """Create one PostgreSQL-backed calendar job and its row-locked items."""
        job_id = uuid.uuid4().hex[:16]
        status = "queued" if entries else "succeeded"
        payload = dict(payload)
        dedupe_key = payload.get("dedupe_key")
        dedupe_window = max(0, int(payload.pop("dedupe_window_seconds", 0)))
        payload.update({
            "total_ups": len(entries), "processed_ups": 0, "succeeded_ups": 0,
            "empty_ups": 0, "failed_ups": 0, "partial_ups": 0, "total_videos": 0,
            "finished_at": now if not entries else None, "error_summary": "",
        })
        with self._sessions.begin() as session:
            if dedupe_key:
                session.execute(select(func.pg_advisory_xact_lock(func.hashtext(dedupe_key))))
                duplicate_id = session.execute(
                    select(calendar_backfill_jobs.c.id)
                    .where(
                        calendar_backfill_jobs.c.payload["dedupe_key"].astext == dedupe_key,
                        or_(
                            calendar_backfill_jobs.c.status.in_(("queued", "running")),
                            calendar_backfill_jobs.c.created_at >= now - dedupe_window,
                        ),
                    )
                    .order_by(calendar_backfill_jobs.c.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if duplicate_id:
                    return self._calendar_job(session, duplicate_id), False
            session.execute(insert(calendar_backfill_jobs).values(
                id=job_id, mode=mode, status=status, payload=payload,
                created_at=now, updated_at=now,
            ))
            if entries:
                session.execute(insert(calendar_backfill_job_items).values([
                    {"job_id": job_id, "mid": int(entry["mid"]), "status": "queued",
                     "payload": {
                         "name": entry.get("name") or f"UID:{entry['mid']}",
                         "pages": 0, "videos": 0, "attempts": 0,
                         "error_code": "", "error_message": "",
                         "started_at": None, "finished_at": None,
                     }}
                    for entry in entries
                ]))
            return self._calendar_job(session, job_id), True

    def claim_calendar_job(self, worker_id: str, now: int, lease_seconds: int) -> dict | None:
        """Claim a queued job using SKIP LOCKED so competing Workers do not collide."""
        with self._sessions.begin() as session:
            session.execute(calendar_backfill_jobs.update().where(
                calendar_backfill_jobs.c.status == "running",
                calendar_backfill_jobs.c.lease_until < now,
            ).values(status="queued", worker_id=None, lease_until=None, updated_at=now))
            job = session.execute(select(calendar_backfill_jobs.c.id).where(
                calendar_backfill_jobs.c.status == "queued",
                calendar_backfill_jobs.c.mode != "test",
            ).order_by(calendar_backfill_jobs.c.created_at).with_for_update(skip_locked=True).limit(1)).scalar_one_or_none()
            if job is None:
                return None
            session.execute(calendar_backfill_jobs.update().where(
                calendar_backfill_jobs.c.id == job,
            ).values(status="running", worker_id=worker_id, lease_until=now + lease_seconds, updated_at=now))
            stored = session.execute(select(calendar_backfill_jobs.c.payload).where(
                calendar_backfill_jobs.c.id == job,
            ).with_for_update()).scalar_one()
            payload = dict(stored or {})
            payload.setdefault("started_at", now)
            session.execute(calendar_backfill_jobs.update().where(
                calendar_backfill_jobs.c.id == job,
            ).values(payload=payload))
            return self._calendar_job(session, job)

    @staticmethod
    def _refresh_calendar_job_progress(session, job_id: str, now: int) -> None:
        items = session.execute(select(
            calendar_backfill_job_items.c.status, calendar_backfill_job_items.c.payload,
        ).where(calendar_backfill_job_items.c.job_id == job_id)).mappings().all()
        statuses = [item["status"] for item in items]
        stored = session.execute(select(calendar_backfill_jobs.c.payload).where(
            calendar_backfill_jobs.c.id == job_id,
        ).with_for_update()).scalar_one()
        payload = dict(stored or {})
        payload.update({
            "total_ups": len(items),
            "processed_ups": sum(status not in ("queued", "running") for status in statuses),
            "succeeded_ups": sum(status in ("success", "empty") for status in statuses),
            "empty_ups": statuses.count("empty"),
            "failed_ups": statuses.count("failed"),
            "partial_ups": statuses.count("partial"),
            "total_videos": sum(int((item["payload"] or {}).get("videos") or 0) for item in items),
        })
        session.execute(calendar_backfill_jobs.update().where(
            calendar_backfill_jobs.c.id == job_id,
        ).values(payload=payload, updated_at=now))

    def update_calendar_job_item(self, job_id: str, event: dict, worker_id: str, now: int, lease_seconds: int) -> None:
        with self._sessions.begin() as session:
            item = session.execute(select(calendar_backfill_job_items).where(
                calendar_backfill_job_items.c.job_id == job_id,
                calendar_backfill_job_items.c.mid == int(event["mid"]),
            ).with_for_update()).mappings().one()
            payload = dict(item["payload"])
            payload.update({
                "pages": int(event.get("pages") or 0),
                "videos": int(event.get("videos") or 0),
                "attempts": int(event.get("attempts") or 0),
                "error_code": event.get("error_code") or "",
                "error_message": (event.get("error_message") or "")[:500],
            })
            status = event.get("status", "running")
            payload.setdefault("started_at", now)
            if status != "running":
                payload["finished_at"] = now
            session.execute(calendar_backfill_job_items.update().where(
                calendar_backfill_job_items.c.job_id == job_id, calendar_backfill_job_items.c.mid == item["mid"],
            ).values(status=status, worker_id=worker_id, payload=payload))
            session.execute(calendar_backfill_jobs.update().where(calendar_backfill_jobs.c.id == job_id).values(
                worker_id=worker_id, lease_until=now + lease_seconds, updated_at=now,
            ))
            self._refresh_calendar_job_progress(session, job_id, now)

    def finish_calendar_job(self, job_id: str, status: str, now: int, error_summary: str = "") -> None:
        with self._sessions.begin() as session:
            job = session.execute(select(calendar_backfill_jobs.c.payload).where(
                calendar_backfill_jobs.c.id == job_id,
            ).with_for_update()).mappings().one()
            payload = dict(job["payload"])
            payload.update({"error_summary": error_summary[:1000], "finished_at": now})
            session.execute(calendar_backfill_jobs.update().where(calendar_backfill_jobs.c.id == job_id).values(
                status=status, payload=payload, updated_at=now, lease_until=None, worker_id=None,
            ))

    def fail_calendar_job_items(self, job_id: str, code: str, message: str, now: int) -> None:
        with self._sessions.begin() as session:
            for item in session.execute(select(calendar_backfill_job_items).where(
                calendar_backfill_job_items.c.job_id == job_id,
                calendar_backfill_job_items.c.status.in_(("queued", "running")),
            ).with_for_update()).mappings():
                payload = dict(item["payload"])
                payload.update({
                    "error_code": code, "error_message": message[:500], "attempts": 1,
                    "started_at": payload.get("started_at") or now, "finished_at": now,
                })
                session.execute(calendar_backfill_job_items.update().where(
                    calendar_backfill_job_items.c.job_id == job_id, calendar_backfill_job_items.c.mid == item["mid"],
                ).values(status="failed", payload=payload))
            self._refresh_calendar_job_progress(session, job_id, now)
