import time

from utils.scorer import (
    is_potential_candidate,
    get_potential_reason,
    calc_engagement_quality,
    calc_online_index,
)


def _video(views=10_000, hours_ago=12,
           likes=None, coins=50, favorites=30, shares=10, comments=20, danmaku=40,
           online_count=0):
    # 默认点赞按 5% 估算，保持测试简洁
    likes = likes if likes is not None else max(1, int(views * 0.05))
    return {
        'bvid': f'BV{views}{int(time.time())}',
        'views': views,
        'likes': likes,
        'coins': coins,
        'favorites': favorites,
        'shares': shares,
        'comments': comments,
        'danmaku': danmaku,
        'online_count': online_count,
        'pub_date': int(time.time() - hours_ago * 3600),
    }


def test_engagement_quality_share_weight():
    # 同样的总互动数，转发权重应让 share 为主的视频得分更高
    likes_video = _video(views=10_000, likes=300, shares=10)
    share_video = _video(views=10_000, likes=100, shares=80)
    likes_score = calc_engagement_quality(likes_video)
    share_score = calc_engagement_quality(share_video)
    assert share_score > likes_score, f'share-weighted should win: {share_score} vs {likes_score}'
    print(f'[OK] 转发高权重生效: 播转 {share_score} > 播赞 {likes_score}')


def test_online_index():
    # 同接率 1% 应接近满分
    hot = _video(views=100_000, online_count=1000)
    cold = _video(views=100_000, online_count=10)
    hot_score = calc_online_index(hot)
    cold_score = calc_online_index(cold)
    assert hot_score >= 95, f'expected near 100 for 1% online rate, got {hot_score}'
    assert cold_score <= 5, f'expected near 0 for 0.01% online rate, got {cold_score}'
    print(f'[OK] 同接指数: 热 {hot_score}, 冷 {cold_score}')


def test_viral_video_filtered_out():
    v = _video(views=5_000_000, hours_ago=72)
    assert not is_potential_candidate(v), '5M views video should be filtered out'
    print('[OK] 500万播放已爆视频被过滤')


def test_too_obscure_filtered_out():
    v = _video(views=500, hours_ago=6)
    assert not is_potential_candidate(v), '500 views video should be filtered out'
    print('[OK] 500播放冷门视频被过滤')


def test_low_engagement_filtered_out():
    v = _video(views=10_000, hours_ago=6,
               likes=0, coins=0, favorites=0, shares=0, comments=0, danmaku=0)
    assert not is_potential_candidate(v), 'zero engagement video should be filtered out'
    print('[OK] 零互动视频被过滤')


def test_reason_badges():
    online_hot = _video(views=100_000, hours_ago=10, online_count=800)
    assert get_potential_reason(online_hot) == '正在热播'

    high_engagement = _video(views=10_000, hours_ago=10, likes=800, shares=300)
    assert get_potential_reason(high_engagement) == '互动爆款'

    new_hot = _video(views=50_000, hours_ago=10, likes=100, shares=10)
    assert get_potential_reason(new_hot) == '新发高潜'

    niche = _video(views=30_000, hours_ago=120, likes=200, shares=10)
    assert get_potential_reason(niche) == '小众宝藏'

    generic = _video(views=200_000, hours_ago=120, likes=200, shares=10)
    assert get_potential_reason(generic) == '综合潜力'
    print('[OK] 理由标签生成正确')


if __name__ == '__main__':
    test_engagement_quality_share_weight()
    test_online_index()
    test_viral_video_filtered_out()
    test_too_obscure_filtered_out()
    test_low_engagement_filtered_out()
    test_reason_badges()
    print('\n[PASS] 所有潜力视频测试通过')
