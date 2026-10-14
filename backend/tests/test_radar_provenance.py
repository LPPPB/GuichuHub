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


def test_newlist_placeholder_remains_estimated_after_detail_failure(monkeypatch):
    from collectors import bilibili
    placeholder = dict(bvid='BVnew', tid=216, pubdate=1,
        stat=dict(view=0, like=0, coin=0, favorite=0, share=0, reply=0, danmaku=0))
    monkeypatch.setattr(bilibili, 'fetch_newlist_region', lambda **_: [placeholder])
    monkeypatch.setattr(bilibili, 'fetch_video_detail', lambda _: None)
    monkeypatch.setattr(bilibili, '_online_pacing', lambda: None)
    row = bilibili.fetch_kichu_newest()[0]
    bilibili._enrich_with_stats([row])
    assert row['metrics_source'] == 'estimated'
    assert row.get('observed_at') is None


def test_partial_detail_revokes_a_previously_trusted_row():
    video = dict(bvid='BVtest', pub_date=1, metrics_source='bilibili_stat', observed_at=100,
                 views=10, likes=2, coins=1, favorites=1, shares=1, comments=1, danmaku=1)
    _apply_real_stat(video, {'stat': {'view': 1000}})
    assert video['metrics_source'] != 'bilibili_stat'
    assert video.get('observed_at') is None

