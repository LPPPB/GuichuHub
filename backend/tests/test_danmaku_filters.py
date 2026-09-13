"""弹幕热词二次过滤（analytics/filters.py）配置化单元测试。

覆盖：
- filter_danmaku_words 基本行为：精确匹配剔除 / 子串匹配剔除 / 弹幕用语保留
- 词表配置化：结构完整 / save-load 闭环 / 缓存失效即时生效 / 损坏与缺失兜底
不依赖真实网络与真实配置（monkeypatch 到临时文件）。
"""
import json

import analytics.filters as filters


def _words(*ws):
    return [{'word': w, 'count': 100} for w in ws]


# ────────────── filter_danmaku_words 基本行为 ──────────────

def _use_filters(monkeypatch, bad_exact, bad_substr):
    """注入独立词表，行为测试不依赖真实配置文件内容（配置可被开发者后台改）"""
    monkeypatch.setattr(filters, '_get_danmaku_filters', lambda: {
        'bad_exact': {w.lower() for w in bad_exact},
        'bad_substr': [s.lower() for s in bad_substr],
    })


def test_filter_removes_exact_bad_words(monkeypatch):
    """精确匹配：广告品牌/平台词整词剔除"""
    _use_filters(monkeypatch, ['美团', '瑞幸'], ['途虎'])
    out = filters.filter_danmaku_words(_words('美团', '瑞幸', '哈基米'))
    assert [w['word'] for w in out] == ['哈基米']


def test_filter_removes_substr_bad_words(monkeypatch):
    """子串匹配：包含品牌/活动名的词剔除（如 途虎养车）"""
    _use_filters(monkeypatch, ['美团'], ['途虎'])
    out = filters.filter_danmaku_words(_words('途虎养车', '哈基米'))
    assert [w['word'] for w in out] == ['哈基米']


def test_filter_keeps_danmaku_terms(monkeypatch):
    """弹幕用语不被误杀：鬼畜/神/离谱等保留"""
    _use_filters(monkeypatch, ['美团'], ['途虎'])
    out = filters.filter_danmaku_words(_words('鬼畜', '神', '离谱', '绝绝子'))
    assert len(out) == 4


# ────────────── 词表配置化（danmaku_filters.json） ──────────────

def test_danmaku_filters_load_structure():
    """真实配置结构完整：bad_exact/bad_substr 均为非空字符串列表
    （不断言具体词，词表可在开发者后台编辑，删词不应挂测试）"""
    data = filters.load_danmaku_filters()
    assert data['bad_exact'], '精确词表不应为空'
    assert data['bad_substr'], '子串词表不应为空'
    assert all(isinstance(w, str) and w.strip() for w in data['bad_exact'])
    assert all(isinstance(w, str) and w.strip() for w in data['bad_substr'])


def test_danmaku_filters_save_roundtrip(monkeypatch, tmp_path):
    """save 后 load 应一致（配置化读写闭环）"""
    f = tmp_path / 'danmaku_filters.json'
    monkeypatch.setattr(filters, '_DANMAKU_FILTERS_PATH', str(f))
    data = {'allowed_exact': ['666'], 'bad_exact': ['测试词'], 'bad_substr': ['测试子串']}
    filters.save_danmaku_filters(data)
    assert filters.load_danmaku_filters() == data


def test_danmaku_filters_cache_invalidated_on_save(monkeypatch, tmp_path):
    """save 后缓存失效：filter_danmaku_words 立即用新配置，无需重启后端"""
    f = tmp_path / 'danmaku_filters.json'
    monkeypatch.setattr(filters, '_DANMAKU_FILTERS_PATH', str(f))
    # 初始：不挡"新广告词"
    filters.save_danmaku_filters({'allowed_exact': ['666'], 'bad_exact': ['美团'], 'bad_substr': ['途虎']})
    assert [w['word'] for w in filters.filter_danmaku_words(_words('新广告词'))] == ['新广告词']
    # 保存新精确词 → 立即生效
    filters.save_danmaku_filters({'allowed_exact': ['666'], 'bad_exact': ['美团', '新广告词'], 'bad_substr': ['途虎']})
    assert filters.filter_danmaku_words(_words('新广告词')) == []
    # 保存新子串词 → 立即生效
    filters.save_danmaku_filters({'allowed_exact': ['666'], 'bad_exact': ['美团'], 'bad_substr': ['途虎', '新子串']})
    assert filters.filter_danmaku_words(_words('新子串xx')) == []


def test_danmaku_filters_fallback_on_corrupt_file(monkeypatch, tmp_path):
    """配置文件损坏 → 降级内置兜底（过滤行为不退化）"""
    f = tmp_path / 'danmaku_filters.json'
    f.write_text('{broken json', encoding='utf-8')
    monkeypatch.setattr(filters, '_DANMAKU_FILTERS_PATH', str(f))
    filters._invalidate_danmaku_filters()
    data = filters.load_danmaku_filters()
    assert '美团' in data['bad_exact']
    assert '途虎' in data['bad_substr']


def test_danmaku_filters_fallback_on_missing_file(monkeypatch, tmp_path):
    """配置文件缺失 → 降级内置兜底"""
    f = tmp_path / 'nope.json'
    monkeypatch.setattr(filters, '_DANMAKU_FILTERS_PATH', str(f))
    filters._invalidate_danmaku_filters()
    data = filters.load_danmaku_filters()
    assert '瑞幸' in data['bad_exact']
    assert '星探' in data['bad_substr']


def test_danmaku_filters_save_writes_valid_json(monkeypatch, tmp_path):
    """保存产物是合法 JSON 且保留 version 字段"""
    f = tmp_path / 'danmaku_filters.json'
    monkeypatch.setattr(filters, '_DANMAKU_FILTERS_PATH', str(f))
    filters.save_danmaku_filters({'bad_exact': ['甲'], 'bad_substr': ['乙']})
    raw = json.loads(f.read_text(encoding='utf-8'))
    assert raw['version'] == 1
    assert raw['bad_exact'] == ['甲']
    assert raw['bad_substr'] == ['乙']


def test_common_stopwords_and_numeric_policy(monkeypatch):
    """公共口语统一过滤；纯数字默认过滤，弹幕数字梗白名单放行。"""
    _use_filters(monkeypatch, [], [])
    out = filters.filter_danmaku_words(_words('其实', '好听', '10', '666', '哈基米'))
    assert [w['word'] for w in out] == ['666', '哈基米']
