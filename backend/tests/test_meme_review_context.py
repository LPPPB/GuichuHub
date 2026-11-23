from collectors.meme_review_context import capture_meme_round, record_source
from collectors import bilibili


def test_seed_snapshot_is_frozen_during_round_and_successful_empty_is_explicit(monkeypatch):
    monkeypatch.setattr('services.meme_publication.get_meme_review_service', lambda: None)
    seed = ['甲号梗']
    monkeypatch.setattr('storage.runtime_settings.load_runtime_setting', lambda name, default: list(seed))
    @capture_meme_round
    def crawl():
        seed[:] = ['乙号梗']
        assert bilibili.load_meme_seed_words() == ['甲号梗']
        record_source('https://api.bilibili.com/x/web-interface/popular', {'code':0,'data':{'list':[]}})
        return {'hot_memes':[], 'meme_materials':[], '_meme_review_evidence':{'hot_memes':[], 'meme_materials':[]}}
    result = crawl()['_meme_review']
    assert result['boards']['hot_memes']['complete'] is True
    assert result['context']['seeds'] == ['甲号梗']
    assert bilibili.load_meme_seed_words() == ['乙号梗']


def test_failed_source_never_publishes_empty_as_complete(monkeypatch):
    monkeypatch.setattr('services.meme_publication.get_meme_review_service', lambda: None)
    @capture_meme_round
    def crawl():
        record_source('https://api.bilibili.com/x/web-interface/popular', None)
        return {'hot_memes':[], 'meme_materials':[], '_meme_review_evidence':{}}
    assert crawl()['_meme_review']['boards']['hot_memes']['complete'] is False


def test_budget_caps_are_normal_completion_and_seed_failure_is_board_specific():
    from types import SimpleNamespace
    from collectors.meme_review_context import source_health
    context = SimpleNamespace(events=[
        dict(kind='discovery', key=('popular_page',1),outcome='success'),
        dict(kind='tags', key=('tags','BV1'),outcome='success'),
        dict(kind='tags', key=('tags','BV65'),outcome='budget'),
        dict(kind='detail', key=('detail','BV161'),outcome='budget'),
        dict(kind='discovery', key=('seed_search_page','梗',22,'totalrank',1),outcome='error')])
    assert source_health(context, board='hot_memes') is True
    assert source_health(context, board='meme_materials') is False
    context.events[-1]['outcome'] = 'success'
    assert source_health(context, board='meme_materials') is True
    context.events.append(dict(kind='discovery', key=('search_page','鬼畜',22,'totalrank',1),outcome='error'))
    assert source_health(context, board='hot_memes') is False


def test_malformed_success_does_not_publish_empty_as_complete(monkeypatch):
    monkeypatch.setattr('services.meme_publication.get_meme_review_service', lambda: None)
    @capture_meme_round
    def crawl():
        record_source('https://api.bilibili.com/x/web-interface/popular', {'code':0,'data':{}})
        return {'hot_memes':[], 'meme_materials':[], '_meme_review_evidence':{}}
    assert crawl()['_meme_review']['boards']['hot_memes']['complete'] is False


def test_shadow_dictionary_edit_does_not_change_legacy_public_result(monkeypatch):
    from types import SimpleNamespace
    from tests.test_hot_meme_evidence import video
    record = dict(id='meme_demo', name='长长的新主名', aliases=['华强买瓜'])
    svc = SimpleNamespace(seed_snapshot=lambda: dict(words=[],version=1),
                          dictionary_snapshot=lambda: dict(dictionary=[record],dictionary_version=1))
    monkeypatch.setattr('services.meme_publication.get_meme_review_service', lambda: svc)
    @capture_meme_round
    def crawl():
        evidence=[]
        cards=bilibili.get_hot_memes([video('BV1',tags=['华强买瓜']),video('BV2',tags=['华强买瓜'])],[],[],[],evidence=evidence)
        return dict(hot_memes=cards,meme_materials=[],_meme_review_evidence={'hot_memes':evidence})
    result = crawl()
    assert result['hot_memes'][0]['keyword'] == '华强买瓜'
