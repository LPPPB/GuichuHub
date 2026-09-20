"""弹幕升温榜：批次归一化、缺批容错、新词与公共过滤。"""
import pytest

import storage.db as db


@pytest.fixture
def rising_db(postgres_runtime):
    return postgres_runtime


def _batch(ts, counts):
    db.record_words([{'word': word, 'count': count} for word, count in counts.items()], ts)


def test_rising_uses_per_batch_rate_not_raw_window_sum(rising_db):
    # 基准批次总量差异很大，但“哈基米”的份额稳定；不能因为总量变化判成升温。
    _batch(100, {'哈基米': 10, '背景词甲': 90})
    _batch(200, {'哈基米': 20, '背景词甲': 180})
    _batch(300, {'哈基米': 10, '背景词甲': 90})
    _batch(400, {'哈基米': 20, '背景词甲': 180})
    result = db.get_rising_words(recent_batches=2, base_batches=2)
    assert '哈基米' not in [item['word'] for item in result]


def test_rising_filters_generic_words_and_keeps_real_growth(rising_db):
    _batch(100, {'哈基米': 5, '其实': 30, '背景词甲': 100})
    _batch(200, {'哈基米': 5, '其实': 30, '背景词甲': 100})
    _batch(300, {'哈基米': 30, '其实': 80, '背景词甲': 100})
    _batch(400, {'哈基米': 35, '其实': 90, '背景词甲': 100})
    result = db.get_rising_words(recent_batches=2, base_batches=2)
    words = [item['word'] for item in result]
    assert '哈基米' in words
    assert '其实' not in words


def test_new_word_requires_both_recent_batches(rising_db):
    _batch(100, {'背景词甲': 100})
    _batch(200, {'背景词甲': 100})
    _batch(300, {'新梗词': 20, '背景词甲': 100})
    _batch(400, {'新梗词': 25, '背景词甲': 100})
    result = db.get_rising_words(recent_batches=2, base_batches=2)
    item = next(row for row in result if row['word'] == '新梗词')
    assert item['is_new'] is True


def test_meta_reports_batch_coverage(rising_db):
    _batch(100, {'哈基米': 5})
    _batch(200, {'哈基米': 10})
    data, meta = db.get_rising_words(recent_batches=2, base_batches=2, return_meta=True)
    assert meta['recent_batch_count'] == 2
    assert meta['base_batch_count'] == 0
    assert meta['sufficient'] is False
    assert data == []
