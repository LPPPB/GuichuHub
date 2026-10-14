"""Batch observation reads; baseline persistence is owned by the Worker."""
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from storage.models import videos, video_observations as obs, radar_baselines, dashboard_state
from config import KICHU_TIDS_WITH_PARENT

COUNTS = ('views', 'likes', 'coins', 'favorites', 'shares', 'comments', 'danmaku')


class RadarRepository:
    def __init__(self, session_factory):
        self._sessions = session_factory

    def reference_observation_targets(self, now, limit=240):
        """Stable, bounded collection coverage; old counts select targets only.

        The existing hot quota is shared by several sections. Keep enough ghost
        videos under repeated observation for the 200-sample growth reference.
        Collection does not certify the old rows or change observation tiers.
        """
        limit = max(0, min(int(limit), 240))
        if not limit:
            return []
        latest = select(obs.c.bvid, obs.c.views).join(
            videos, videos.c.bvid == obs.c.bvid).where(
                videos.c.tid.in_(KICHU_TIDS_WITH_PARENT),
                videos.c.pub_date.between(1, now),
                obs.c.ts.between(now-30*86400, now),
            ).distinct(obs.c.bvid).order_by(obs.c.bvid, obs.c.ts.desc()).subquery()
        with self._sessions() as session:
            return list(session.execute(select(latest.c.bvid).where(
                latest.c.views >= 1500).order_by(
                func.md5(latest.c.bvid), latest.c.bvid).limit(limit)).scalars())

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
                obs.c.observed_at.between(now-7*3600-5400, now), obs.c.views >= 0,
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

    def load_active_baseline(self, now):
        with self._sessions() as session:
            return session.execute(select(radar_baselines.c.payload).where(
                radar_baselines.c.cutoff_ts <= now, radar_baselines.c.valid_until > now,
                radar_baselines.c.algorithm_version == 'radar-v2',
            ).order_by(radar_baselines.c.cutoff_ts.desc()).limit(1)).scalar_one_or_none()

    def revision(self):
        with self._sessions() as session:
            rows = session.execute(select(dashboard_state).where(
                dashboard_state.c.name.in_(('radar.observations', 'radar.baseline')))).mappings()
            state = {r['name']: r for r in rows}
        return (state.get('radar.observations', {}).get('version', 0),
                state.get('radar.baseline', {}).get('payload', {}).get('version'))

    @staticmethod
    def _advance(session, name, payload, now):
        session.execute(insert(dashboard_state).values(name=name, payload=payload, version=1,
            updated_at=now).on_conflict_do_update(index_elements=[dashboard_state.c.name],
            set_={'payload': payload, 'version': dashboard_state.c.version+1, 'updated_at': now}))

    def touch_observations(self, now):
        with self._sessions.begin() as session:
            self._advance(session, 'radar.observations', {}, now)

    def publish_baseline(self, baseline, now):
        with self._sessions.begin() as session:
            session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended('radar-baseline', 0))))
            active = session.execute(select(radar_baselines.c.version).where(
                radar_baselines.c.valid_until > now, radar_baselines.c.cutoff_ts <= now,
            ).limit(1)).scalar_one_or_none()
            if active:
                return False
            created = session.execute(insert(radar_baselines).values(
                version=baseline['version'], algorithm_version=baseline['algorithm_version'],
                cutoff_ts=baseline['cutoff_ts'], valid_until=baseline['valid_until'],
                payload=baseline, created_at=now,
            ).on_conflict_do_nothing().returning(radar_baselines.c.version)).scalar_one_or_none()
            if not created:
                return False
            self._advance(session, 'radar.baseline', {'version': created}, now)
            return True


_radar_repository = None


def configure_radar_repository(repository):
    global _radar_repository
    _radar_repository = repository


def get_radar_repository():
    return _radar_repository
