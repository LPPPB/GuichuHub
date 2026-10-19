from utils.radar_v2 import build_video_radar, build_online_observation
from services.video_statistics import with_observed_statistics


class RadarService:
    def __init__(self, repository):
        self.repository = repository

    def decorate(self, videos, now):
        ids = list(dict.fromkeys(v.get('bvid') for v in videos if isinstance(v, dict) and v.get('bvid')))
        baseline = self.repository.load_active_baseline(now) if self.repository and ids else None
        contexts = self.repository.video_contexts(ids, now) if self.repository and ids else {}
        result = []
        for video in videos:
            if not isinstance(video, dict):
                result.append(video)
                continue
            context = contexts.get(video.get('bvid'), {})
            result.append({**with_observed_statistics(video, context.get('latest'), now),
                           'radar': build_video_radar(context, baseline, now),
                           'online_observation': build_online_observation(context, now)})
        return result
