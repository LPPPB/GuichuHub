"""Synthetic public-video responses. No network, credentials or private data."""
from copy import deepcopy

NOW = 1_790_000_000
BVIDS = ['BV1uaWA6HESq', 'BV1wQp96mEs7', 'BV1vsp96NErZ']


def raw_video(bvid=BVIDS[0], **overrides):
    result = dict(bvid=bvid, aid=123, cid=456, title='合成鬼畜作品', tid=219,
                  tname='旧分类', tidv2=2063, tnamev2='鬼畜综合', pid_v2=1007,
                  pid_name_v2='鬼畜', pubdate=NOW-3600, duration=60, pic='',
                  owner=dict(mid=100, name='测试作者', face=''),
                  stat=dict(view=10000, like=500, coin=100, favorite=100,
                            share=100, reply=100, danmaku=100))
    result.update(deepcopy(overrides))
    return result


def rank_response(items):
    return {'code': 0, 'data': {'list': deepcopy(items)}}
