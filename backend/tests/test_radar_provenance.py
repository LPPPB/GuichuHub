from collectors.bilibili import _apply_real_stat, _build_video_dict


def test_estimated_counts_keep_provenance_after_private_marker_is_removed():
    video = _build_video_dict(dict(bvid='BVtest', views=1000, pub_date=1,
                                  likes=1, coins=1, favorites=1, shares=1,
                                  comments=1, danmaku=1), stats_estimated=True)
    video.pop('_stats_estimated')
    assert video['metrics_source'] == 'estimated'


def test_complete_detail_marks_real_counts_and_sample_time():
    video = {'bvid': 'BVtest', 'pub_date': 1, 'metrics_source': 'estimated'}
    stat = dict(view=1000, like=10, coin=3, favorite=2, share=1, reply=4, danmaku=5)
    _apply_real_stat(video, {'stat': stat})
    assert video['metrics_source'] == 'bilibili_stat'
    assert video['observed_at'] > 0


def test_partial_detail_cannot_certify_mixed_real_and_estimated_counts():
    video = {'bvid': 'BVtest', 'pub_date': 1, 'metrics_source': 'estimated', 'likes': 99}
    _apply_real_stat(video, {'stat': {'view': 1000}})
    assert video['metrics_source'] == 'estimated'

