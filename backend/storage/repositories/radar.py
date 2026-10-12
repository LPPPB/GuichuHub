"""Batch observation reads; baseline persistence is owned by the Worker."""
from collections import defaultdict

from sqlalchemy import and_, select
from storage.models import videos, video_observations as obs
from config import KICHU_TIDS_WITH_PARENT

COUNTS = ('views', 'likes', 'coins', 'favorites', 'shares', 'comments', 'danmaku')


class RadarRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    def _latest(self, cutoff_ts, bvids=None):
        conditions = [obs.c.metrics_source == 'bilibili_stat',
                      obs.c.observed_at.between(cutoff_ts-30*86400, cutoff_ts)]
        conditions.extend(obs.c[name] >= 0 for name in COUNTS)
        if bvids is not None:
            conditions.append(obs.c.bvid.in_(bvids))
        return select(obs).where(*conditions).distinct(obs.c.bvid).order_by(
            obs.c.bvid, obs.c.observed_at.desc(), obs.c.ts.desc()).subquery()

    def video_contexts(self, bvids, now):
        if not bvids:
            return {}
        latest = self._latest(now, bvids)
        contexts = {}
        with self._sessions() as session:
            rows = session.execute(select(videos, *[
                latest.c[name].label('obs_'+name) for name in obs.c.keys()
            ]).outerjoin(latest, latest.c.bvid == videos.c.bvid).where(
                videos.c.bvid.in_(bvids))).mappings()
            for row in rows:
                metadata = {c.name: row[c.name] for c in videos.columns}
                contexts[row['bvid']] = {**metadata, 'latest': (
                    {name: row['obs_'+name] for name in obs.c.keys()}
                    if row['obs_bvid'] else None), 'history': [], 'online': None}
            history = session.execute(select(obs).where(
                obs.c.bvid.in_(bvids), obs.c.metrics_source == 'bilibili_stat',
                obs.c.observed_at.between(now-8*3600, now), obs.c.views >= 0,
            ).order_by(obs.c.observed_at, obs.c.ts)).mappings()
            for row in history:
                if row['bvid'] in contexts:
                    contexts[row['bvid']]['history'].append(dict(row))
            online = session.execute(select(obs).where(
                obs.c.bvid.in_(bvids), obs.c.online_count >= 0,
                obs.c.online_observed_at.between(now-30*86400, now),
            ).distinct(obs.c.bvid).order_by(obs.c.bvid,
                obs.c.online_observed_at.desc(), obs.c.ts.desc())).mappings()
            for row in online:
                if row['bvid'] in contexts:
                    contexts[row['bvid']]['online'] = dict(row)
        return contexts

    def reference_contexts(self, cutoff_ts, lookback_days=30):
        latest = self._latest(cutoff_ts)
        contexts = {}
        with self._sessions() as session:
            rows = session.execute(select(videos, *[
                latest.c[name].label('obs_'+name) for name in obs.c.keys()
            ]).join(latest, latest.c.bvid == videos.c.bvid).where(
                videos.c.tid.in_(KICHU_TIDS_WITH_PARENT),
                latest.c.observed_at >= cutoff_ts-lookback_days*86400,
            )).mappings()
            for row in rows:
                contexts[row['bvid']] = {
                    **{c.name: row[c.name] for c in videos.columns},
                    'latest': {name: row['obs_'+name] for name in obs.c.keys()},
                    'history': [], 'online': None}
            if contexts:
                history = session.execute(select(obs).where(
                    obs.c.bvid.in_(list(contexts)), obs.c.metrics_source == 'bilibili_stat',
                    obs.c.observed_at.between(cutoff_ts-lookback_days*86400-7*3600, cutoff_ts),
                    obs.c.views >= 0,
                ).order_by(obs.c.observed_at, obs.c.ts)).mappings()
                for row in history:
                    contexts[row['bvid']]['history'].append(dict(row))
        return list(contexts.values())
