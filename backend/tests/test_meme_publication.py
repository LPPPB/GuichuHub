import pytest
from storage.repositories.meme_review import MemeReviewRepository
from services.meme_publication import MemePublicationService, ReviewConflict


def board(word='华强买瓜'):
    return {'complete': True, 'evidence_complete': True, 'cards': [{'keyword': word, 'meme_id': 'auto:'+word, 'heat': 10}],
            'evidence': [], 'seeds': [], 'songs': []}


def service(runtime):
    return MemePublicationService(MemeReviewRepository(runtime.sessions), blocked_loader=lambda: [])


def test_publish_survives_next_crawl_expires_without_crawl_and_retry_does_not_extend(postgres_runtime):
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': board()}, 100)
    proposal = {'adjustments': [{'board': 'hot_memes', 'meme_id': 'auto:华强买瓜', 'action': 'hide'}]}
    preview = svc.preview(proposal, 110)
    first = svc.publish('admin', 'request-one', proposal, preview['token'], 110)
    assert svc.read_current(111)['boards']['hot_memes'] == []
    svc.ingest('two', {'hot_memes': board()}, 200)
    assert svc.read_current(201)['boards']['hot_memes'] == []
    assert svc.publish('admin', 'request-one', proposal, preview['token'], 300) == first
    assert svc.read_current(86510)['boards']['hot_memes'][0]['keyword'] == '华强买瓜'


def test_preview_rejects_new_run_and_successful_empty_replaces_failed_result(postgres_runtime):
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': board()}, 100)
    preview = svc.preview({}, 101)
    svc.ingest('two', {'hot_memes': {'complete': False}}, 102)
    with pytest.raises(ReviewConflict):
        svc.publish('admin', 'request-two', {}, preview['token'], 103)
    assert len(svc.read_current(103)['boards']['hot_memes']) == 1
    svc.ingest('three', {'hot_memes': dict(board(), cards=[])}, 104)
    assert svc.read_current(104)['boards']['hot_memes'] == []


def test_stopwords_change_invalidates_preview(postgres_runtime):
    blocked = []
    svc = MemePublicationService(MemeReviewRepository(postgres_runtime.sessions), blocked_loader=lambda: blocked)
    svc.ingest('one', {'hot_memes': board()}, 100)
    preview = svc.preview({}, 101)
    blocked.append('华强买瓜')
    with pytest.raises(ReviewConflict):
        svc.publish('admin', 'request-three', {}, preview['token'], 102)
    assert svc.read_current(102)['boards']['hot_memes'] == []


def test_draft_cas_and_undo_preserves_original_expiry(postgres_runtime):
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': board()}, 100)
    proposal = {'adjustments': [{'board': 'hot_memes', 'meme_id': 'auto:华强买瓜', 'action': 'hide'}]}
    saved = svc.save_draft('admin', proposal, 0, 110)
    with pytest.raises(ReviewConflict):
        svc.save_draft('admin', {}, 0, 111)
    assert saved['revision'] == 1
    svc.publish('admin', 'first', proposal, svc.preview(proposal, 110)['token'], 110)
    svc.publish('admin', 'second', proposal, svc.preview(proposal, 200)['token'], 200)
    token = svc.undo_preview('second', 210)['token']
    svc.undo('admin', 'undo-second', 'second', token, 210)
    assert svc.read_current(86510)['boards']['hot_memes']


def test_cleanup_protects_latest_good_and_rollback_dependencies(postgres_runtime):
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': board()}, 100)
    svc.ingest('two', {'hot_memes': board()}, 200)
    svc.ingest('three', {'hot_memes': {'complete': False}}, 300)
    svc.save_draft('admin', {}, 0, 400)
    counts = svc.cleanup_preview(100*86400)
    assert counts['eligible']['runs'] == 0
    assert counts['eligible']['drafts'] == 1
    assert counts['mode'] == 'dry_run'
    assert svc.cleanup_batch(100*86400)['deleted'] == 0


def test_concurrent_publish_allows_only_one_preview_and_seed_save_has_cas(postgres_runtime):
    from concurrent.futures import ThreadPoolExecutor
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': board()}, 100)
    token = svc.preview({}, 101)['token']
    def publish(id):
        try:
            svc.publish('admin', id, {}, token, 102)
            return 'published'
        except ReviewConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(publish, ['first', 'second'])) == ['conflict', 'published']
    def seeds(word):
        try:
            svc.save_seeds([word], {}, 0, 103)
            return 'saved'
        except ReviewConflict:
            return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(seeds, ['甲', '乙'])) == ['conflict', 'saved']


def test_merge_undo_preserves_history_and_search_strings(postgres_runtime):
    from sqlalchemy import select
    from storage.models import meme_review_publications
    from tests.test_meme_review_domain import hit
    svc = service(postgres_runtime)
    evidence = [hit('甲号梗', 'BV1'), hit('乙号梗', 'BV1'), hit('乙号梗', 'BV2')]
    svc.ingest('one', {'hot_memes': dict(board(), evidence=evidence)}, 100)
    original = svc.read_current(100)
    svc.save_seeds(['甲号梗', '乙号梗'], {}, 0, 101)
    proposal = {'dictionary': [{'action':'merge', 'source':'auto:甲号梗', 'target':'auto:乙号梗'}]}
    preview = svc.preview(proposal, 102)
    assert preview['boards']['hot_memes'][0]['video_count'] == 2
    published = svc.publish('admin', 'merge-one', proposal, preview['token'], 102)
    assert published['redirects']['auto:甲号梗'] == 'auto:乙号梗'
    assert svc.seed_snapshot()['words'] == ['甲号梗', '乙号梗']
    with postgres_runtime.sessions() as session:
        assert session.execute(select(meme_review_publications.c.payload).where(
            meme_review_publications.c.id == original['id'])).scalar_one() == original
    token = svc.undo_preview('merge-one', 103)['token']
    svc.undo('admin', 'undo-merge', 'merge-one', token, 103)
    assert not svc.read_current(103)['redirects']


def test_rename_keeps_old_evidence_attached_to_stable_identity(postgres_runtime):
    from tests.test_meme_review_domain import hit
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': dict(board(), evidence=[hit('旧梗名', 'BV1'), hit('旧梗名', 'BV2')])}, 100)
    proposal = {'dictionary': [dict(action='edit', id='auto:旧梗名', name='新梗名', aliases=[])]}
    preview = svc.preview(proposal, 101)
    assert preview['boards']['hot_memes'][0]['keyword'] == '新梗名'
    assert preview['boards']['hot_memes'][0]['meme_id'] == 'auto:旧梗名'


def test_split_release_alias_does_not_silently_remerge_on_next_crawl(postgres_runtime):
    from tests.test_meme_review_domain import hit
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes': dict(board(), evidence=[hit('哈基米', 'BV1'), hit('Hachimi', 'BV2')])}, 100)
    records = svc.overview('admin', 100)['dictionary']
    record = next(r for r in records if r['name'] == '哈基米')
    proposal = {'dictionary': [dict(action='edit', id=record['id'], name=record['name'],
                                    aliases=[a for a in record['aliases'] if a != 'Hachimi']),
                              dict(action='register', name='Hachimi', aliases=[])]}
    preview = svc.preview(proposal, 101)
    svc.publish('admin', 'split', proposal, preview['token'], 101)
    svc.ingest('two', {'hot_memes': dict(board(), evidence=[hit('Hachimi','BV2'),hit('Hachimi','BV3')])},102)
    assert svc.read_current(102)['boards']['hot_memes'][0]['keyword'] == 'Hachimi'


def test_draft_revision_never_reuses_deleted_generation(postgres_runtime):
    svc = service(postgres_runtime)
    svc.save_draft('admin', {}, 0, 100)
    svc.publish('admin', 'publish-draft', {}, svc.preview({}, 100)['token'], 100)
    current = svc.overview('admin', 101)
    saved = svc.save_draft('admin', {}, current['draft_revision'], 101)
    assert saved['revision'] > 1
    with pytest.raises(ReviewConflict):
        svc.save_draft('admin', {'adjustments': []}, 1, 102)


def test_reregister_after_merge_gets_a_distinct_id_without_old_redirect(postgres_runtime):
    svc = service(postgres_runtime)
    def publish(id, proposal, now):
        return svc.publish('admin', id, proposal, svc.preview(proposal, now)['token'], now)
    publish('register', {'dictionary':[dict(action='register',name='Alpha',aliases=[]),
                                        dict(action='register',name='Beta',aliases=[])]}, 100)
    records = svc.overview('admin',100)['dictionary']
    a,b = [next(r for r in records if r['name']==name) for name in ('Alpha','Beta')]
    publish('merge', {'dictionary':[dict(action='merge',source=a['id'],target=b['id'])]}, 101)
    result = publish('split', {'dictionary':[dict(action='edit',id=b['id'],name='Beta',aliases=[]),
                                           dict(action='register',name='Alpha',aliases=[])]}, 102)
    new = next(r for r in svc.overview('admin',102)['dictionary'] if r['name']=='Alpha')
    assert new['id'] != a['id']
    assert new['id'] not in result['redirects']


def test_mark_reviewed_does_not_destroy_latest_dictionary_undo(postgres_runtime):
    svc = service(postgres_runtime)
    proposal = {'dictionary': [dict(action='register', name='Alpha', aliases=[])]}
    svc.publish('admin','register',proposal,svc.preview(proposal,100)['token'],100)
    svc.publish('admin','mark',{},svc.preview({},101)['token'],101)
    assert svc.overview('admin',101)['last_manual'] == 'register'
    assert svc.undo_preview('register',102)['token']


def test_expired_draft_can_be_replaced_using_current_monotonic_version(postgres_runtime):
    svc = service(postgres_runtime)
    svc.save_draft('admin', {}, 0, 100)
    overview = svc.overview('admin', 15*86400)
    assert overview['draft'] is None and overview['draft_revision'] == 1
    assert svc.save_draft('admin', {}, overview['draft_revision'], 15*86400)['revision'] == 2


def test_board_undo_keeps_other_board_changes_and_original_expiry(postgres_runtime):
    svc = service(postgres_runtime)
    svc.ingest('one', {'hot_memes':board(), 'meme_materials':dict(board(),cards=[dict(name='华强买瓜')])}, 100)
    proposal = {'adjustments':[dict(board=b,meme_id='auto:华强买瓜',action='hide') for b in ('hot_memes','meme_materials')]}
    svc.publish('admin','two-boards',proposal,svc.preview(proposal,101)['token'],101)
    preview = svc.undo_preview('two-boards',102,board='hot_memes')
    svc.undo('admin','undo-hot','two-boards',preview['token'],102,board='hot_memes')
    current = svc.read_current(102)
    assert len(current['boards']['hot_memes']) == 1
    assert current['boards']['meme_materials'] == []
    assert svc.read_current(86501)['boards']['meme_materials']


def test_manual_bv_links_require_registered_video_and_never_invent_observations(postgres_runtime):
    from sqlalchemy import insert
    from storage.models import videos
    svc = service(postgres_runtime)
    register = {'dictionary':[dict(action='register',name='Alpha',aliases=[])]}
    svc.publish('admin','register',register,svc.preview(register,100)['token'],100)
    record = next(r for r in svc.overview('admin',100)['dictionary'] if r['name']=='Alpha')
    proposal = {'adjustments':[dict(board='hot_memes',meme_id=record['id'],action='add',bvids=['BV1234567890'])]}
    with pytest.raises(ValueError,match='video'):
        svc.preview(proposal,101)
    with postgres_runtime.sessions.begin() as session:
        session.execute(insert(videos).values(bvid='BV1234567890',title='可验证的视频',first_seen=100))
    preview = svc.preview(proposal,101)
    item = preview['boards']['hot_memes'][0]
    assert item['related_videos'][0]['bvid'] == 'BV1234567890'
    assert item['heat'] is None and item['total_views'] is None


def test_legacy_cards_are_visible_but_cannot_be_recomputed_from_truncated_evidence(postgres_runtime):
    svc = service(postgres_runtime)
    postgres_runtime.state.save_dashboard(dict(hot_memes=[dict(keyword='旧梗',heat=10)],meme_materials=[dict(name='旧梗')]),100)
    original = svc.read_current(101)
    assert original['boards']['hot_memes'][0]['keyword'] == '旧梗'
    assert original['sources']['hot_memes'].startswith('legacy:')
    proposal = {'dictionary':[dict(action='register',name='新梗',aliases=[])]}
    with pytest.raises(ValueError,match='complete evidence'):
        svc.preview(proposal,102)
    svc.ingest('failed',{'hot_memes':dict(complete=False)},103)
    assert svc.read_current(103)['boards']['hot_memes'][0]['keyword'] == '旧梗'
