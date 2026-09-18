# -*- coding: utf-8 -*-
"""回测模块单元测试。

验证：
- spearman 秩相关（单调=1.0、反单调=-1.0、并列平均秩、n<2 兜底）
- run_backtest 在"完美预测"数据下 spearman=1.0、命中率=1.0、分桶单调、排名全 same
- 窗口内无后续观测的视频计入 n_unverified 且不参与评估
- min_views 过滤（太冷视频不参与增速评估）
- list_scored_batches 返回带分批次；get_dev_stats 返回 schema 版本与抓取残留
不依赖真实网络与真实 DB（monkeypatch 到临时 SQLite，模式同 test_calendar_dedup）。
"""
import pytest

import storage.db as db
from analytics import backtest


@pytest.fixture
def bt_db(postgres_runtime):
    return postgres_runtime


def _seed(bt_db, ts):
    """写入一批"完美预测"数据：分越高 → 后续播放增量越大（增速单调）。

    6 个视频，T 时刻 views 相同（10000），后续 views = 10000 + score*100，
    增速与分完全正相关。另加 1 个无后续观测（unverified）与 1 个超冷视频（<100）。
    """
    repository = bt_db.business
    scores = [90, 80, 70, 60, 50, 40]
    for i, score in enumerate(scores, start=1):
        bvid = f'BT{i}'
        repository.register_up(9000 + i, f'UP{i}')
        repository.record_video({
            'bvid': bvid, 'title': f'测试视频{i}', 'mid': 9000 + i,
            'first_seen': ts, 'views': 10000, 'potential_score': float(score),
        }, ts=ts, source='test')
        later_views = 10000 + score * 100
        repository.record_observation(bvid, ts + 2 * 3600, {'views': later_views})
    # 无后续观测：只看得到 T 时刻，应计入 n_unverified
    repository.register_up(9999, 'UP_DEAD')
    repository.record_video({
        'bvid': 'BT_DEAD', 'title': '无后续观测', 'mid': 9999,
        'first_seen': ts, 'views': 5000, 'potential_score': 45.0,
    }, ts=ts, source='test')
    # 超冷视频：views < 100，应被 min_views 过滤
    repository.register_up(9998, 'UP_COLD')
    repository.record_video({
        'bvid': 'BT_COLD', 'title': '超冷视频', 'mid': 9998,
        'first_seen': ts, 'views': 50, 'potential_score': 85.0,
    }, ts=ts, source='test')
    repository.record_observation('BT_COLD', ts + 2 * 3600, {'views': 200})
    return ts


# ─── spearman 秩相关 ───

def test_spearman_perfect_positive():
    assert backtest.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0


def test_spearman_perfect_negative():
    assert backtest.spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0


def test_spearman_ties_average_rank():
    # [10,20,20,30] -> 秩 [1,2.5,2.5,4]；与 [1,3,2,4] 的 Pearson 即 Spearman
    r = backtest.spearman([10, 20, 20, 30], [1, 3, 2, 4])
    # 2.5 与 2.5 并列、其余一致，应显著接近 1
    assert r > 0.9


def test_spearman_too_small():
    assert backtest.spearman([1], [2]) == 0.0
    assert backtest.spearman([], []) == 0.0


def test_spearman_zero_variance():
    assert backtest.spearman([5, 5, 5], [1, 2, 3]) == 0.0


# ─── run_backtest 主流程 ───

def test_run_backtest_perfect_prediction(bt_db):
    """完美预测：spearman=1.0、命中率=1.0、分桶平均增速单调递增、排名全 same"""
    ts = 1700000000
    _seed(bt_db, ts)
    res = backtest.run_backtest(ts, window_hours=48, top_n=2)

    assert res['meta']['n_scored'] == 8            # 6 + DEAD + COLD
    assert res['meta']['n_verified'] == 6          # 6 个正常视频
    assert res['meta']['n_unverified'] == 1        # BT_DEAD 无后续观测

    assert res['metrics']['spearman'] == pytest.approx(1.0, abs=0.001)
    assert res['metrics']['hit_rate_delta'] == pytest.approx(1.0)
    assert res['metrics']['hit_rate_growth'] == pytest.approx(1.0)
    # 排名完全一致 → 全部 same
    assert res['metrics']['rank_up'] == 0
    assert res['metrics']['rank_down'] == 0
    assert res['metrics']['rank_same'] == 2

    # 分桶：平均增速随分桶严格递增（等频 5 桶，6 个 → 2/1/1/1/1）
    buckets = res['buckets']
    growths = [b['avg_growth'] for b in buckets]
    assert all(growths[i] < growths[i + 1] for i in range(len(growths) - 1)), '分桶平均增速应单调递增'

    # 对照表按当时排名排序，含标题/作者
    table = res['table']
    assert table[0]['bvid'] == 'BT1' and table[0]['title'] == '测试视频1'
    assert table[0]['author'] == 'UP1'
    assert table[0]['rank_at_T'] == 1
    assert table[0]['views_delta'] == 9000
    assert table[-1]['bvid'] == 'BT6'

    # 散点：6 个点，score 与 growth_rate 正相关
    scatter = res['scatter']
    assert len(scatter) == 6
    assert all(s['growth_rate'] > 0 for s in scatter)


def test_run_backtest_no_later_obs(bt_db):
    """窗口内无后续观测：只报 unverified，不参与评估，不抛异常"""
    ts = 1701000000
    bt_db.business.register_up(8001, 'U1')
    bt_db.business.record_video({
        'bvid': 'NO1', 'title': '仅一次观测', 'mid': 8001, 'first_seen': ts,
        'views': 10000, 'potential_score': 60.0,
    }, ts=ts, source='test')

    res = backtest.run_backtest(ts, window_hours=24)
    assert res['meta']['n_scored'] == 1
    assert res['meta']['n_verified'] == 0
    assert res['meta']['n_unverified'] == 1
    assert res['table'] == []
    # 无有效样本 → spearman 兜底 0.0
    assert res['metrics']['spearman'] == 0.0


def test_run_backtest_handles_ts_without_batch(bt_db):
    """批次不存在：返回空结果而非报错"""
    res = backtest.run_backtest(987654321, window_hours=48)
    assert res['meta']['n_scored'] == 0
    assert res['table'] == []


# ─── 批次列表 / 数据体检 ───

def test_list_scored_batches(bt_db):
    ts = 1702000000
    bt_db.business.record_video({
        'bvid': 'B1', 'title': 'v', 'mid': 7001, 'first_seen': ts,
        'views': 10000, 'potential_score': 55.0,
    }, ts=ts, source='test')
    bt_db.business.record_video({
        'bvid': 'B2', 'title': 'v2', 'mid': 7001, 'first_seen': ts + 1,
        'views': 10000, 'potential_score': None,
    }, ts=ts + 1, source='test')

    batches = backtest.list_scored_batches()
    assert any(b['ts'] == ts for b in batches), '有分的批次应出现在列表'
    assert not any(b['ts'] == ts + 1 for b in batches), '无分批次不应出现'
    b = next(b for b in batches if b['ts'] == ts)
    assert b['count'] == 1
    assert 'time' in b


def test_get_dev_stats(bt_db):
    ts = 1703000000
    bt_db.business.begin_crawl_run('test', ts)
    run_id = bt_db.business.begin_crawl_run('test', ts - 3600)
    bt_db.business.finish_crawl_run(run_id, 'success', {}, ts - 3500)

    stats = backtest.get_dev_stats()
    assert stats['alembic_revision'] == '0001_postgresql_v3_baseline'
    assert stats['schema_version'] == 11  # legacy API compatibility for V1–V11 baseline
    assert stats['crawl_runs'].get('running') == 1
    assert stats['crawl_runs'].get('success') == 1
    assert len(stats['stale_running']) == 1
    assert stats['stale_running'][0]['trigger'] == 'test'
    assert stats['videos'] == 0
