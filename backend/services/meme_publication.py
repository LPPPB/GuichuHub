"""Atomic review publications. All writers acquire the singleton before documents."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from storage.models import (meme_review_state as states, meme_review_runs as runs,
    meme_review_publications as publications, meme_review_operations as operations,
    meme_review_drafts as drafts, dashboard_state, videos)
from services.meme_review import BOARDS, resolve, validate_dictionary, rank_evidence, apply_adjustments, dictionary_index


class ReviewConflict(ValueError):
    pass


class ReviewUnavailable(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


class MemePublicationService:
    def __init__(self, repository, blocked_loader=None):
        self.repo = repository
        self.blocked_loader = blocked_loader

    def _blocked(self, session):
        if self.blocked_loader is not None:
            return sorted(self.blocked_loader())
        from utils.release_word_rules import MEME_STOPWORDS
        # Lock the same persisted rule row used by rule-editor writes.
        rules = session.execute(select(dashboard_state.c.payload).where(
            dashboard_state.c.name == 'meme_stopwords').with_for_update()).scalar_one_or_none()
        return sorted({w for words in (rules or MEME_STOPWORDS).values() for w in words})

    def _state(self, row):
        state = row['payload']
        if 'dictionary' not in state:
            from utils import meme_aliases
            state['dictionary'] = json.loads(Path(meme_aliases.__file__).with_suffix('.json').read_text(encoding='utf-8'))['memes']
        for key, default in dict(dictionary_version=0, adjustments=[], latest={}, redirects={}, reviewed={}, draft_revisions={}, last_boards={}).items():
            state.setdefault(key, deepcopy(default))
        return state

    def _save(self, session, row, now):
        row['revision'] += 1
        session.execute(states.update().where(states.c.id == 1).values(
            payload=row['payload'], revision=row['revision'], updated_at=now))

    def _bootstrap(self, session, state, now):
        if state.get('last_run') or state['latest']:
            return
        legacy = session.execute(select(dashboard_state).where(dashboard_state.c.name == 'current')).mappings().first()
        if legacy is None:
            return
        boards = {board: dict(complete=False, evidence_complete=False, source_status='legacy_incomplete',
                              cards=legacy['payload'][board],evidence=[])
                  for board in BOARDS if isinstance(legacy['payload'].get(board),list) and legacy['payload'][board]}
        if not boards:
            return
        identifier = 'legacy:'+str(legacy['version'])
        session.execute(insert(runs).values(id=identifier,finished_at=legacy['updated_at'],boards=boards,
            context=dict(legacy=True)).on_conflict_do_nothing(index_elements=[runs.c.id]))
        state['latest'].update({board: identifier for board in boards})
        state['last_run'] = identifier
        for board, source in boards.items():
            for card in source['cards']:
                name = card.get('keyword') or card.get('name')
                if name:
                    id, canonical = resolve(name,state['dictionary'])
                    if not any(r['id'] == id for r in state['dictionary']):
                        state['dictionary'].append(dict(id=id,name=canonical,aliases=[]))

    def _token(self, row, proposal, blocked, now):
        active = [a for a in row['payload']['adjustments'] if a['expires_at'] > now]
        return digest([row['revision'], proposal, blocked, active])

    def _proposal(self, state, proposal, now):
        if not isinstance(proposal, dict) or set(proposal) - {'dictionary', 'adjustments'}:
            raise ValueError('invalid proposal')
        state = deepcopy(state)
        records = state['dictionary']
        edits = proposal.get('dictionary', [])
        changes = proposal.get('adjustments', [])
        if not isinstance(edits, list) or not isinstance(changes, list) or len(edits) + len(changes) > 200:
            raise ValueError('too many or invalid operations')
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError('invalid dictionary operation')
            action = edit.get('action')
            if action == 'register':
                record = dict(id='meme_' + digest([edit, state['dictionary_version']])[:24], name=edit['name'], aliases=edit.get('aliases', []))
                if any(r['id'] == record['id'] for r in records):
                    raise ValueError('identity already exists')
                records.append(record)
            elif action == 'merge':
                source, target = edit['source'], edit['target']
                if source == target:
                    raise ValueError('cannot merge identity into itself')
                src = next((r for r in records if r['id'] == source), None)
                dst = next((r for r in records if r['id'] == target), None)
                if not src or not dst:
                    raise ValueError('unknown merge identity')
                dst['aliases'] = sorted(set(dst['aliases'] + src['aliases'] + [src['name']]))
                records.remove(src)
                state['redirects'][source] = target
                for old, redirected in list(state['redirects'].items()):
                    if redirected == source:
                        state['redirects'][old] = target
                for adjustment in state['adjustments']:
                    if adjustment['meme_id'] == source:
                        adjustment['meme_id'] = target
            elif action == 'edit':
                record = next((r for r in records if r['id'] == edit['id']), None)
                if record is None:
                    raise ValueError('unknown identity')
                aliases = list(edit.get('aliases', []))
                if edit['name'] != record['name'] and record['name'] not in aliases:
                    aliases.append(record['name'])
                record.update(name=edit['name'], aliases=aliases)
            else:
                raise ValueError('invalid dictionary operation')
        validate_dictionary(records)
        if edits:
            state['dictionary_version'] += 1
        pending = set()
        for edit in changes:
            if not isinstance(edit, dict):
                raise ValueError('invalid adjustment')
            board, identifier = edit['board'], edit['meme_id']
            if board not in BOARDS:
                raise ValueError('invalid board')
            key = (board, identifier)
            if key in pending:
                raise ValueError('duplicate adjustment')
            pending.add(key)
            state['adjustments'] = [a for a in state['adjustments'] if (a['board'], a['meme_id']) != key]
            if edit['action'] != 'revoke':
                if edit['action'] not in ('hide', 'add', 'position'):
                    raise ValueError('invalid adjustment action')
                bvids = edit.get('bvids', [])
                if not isinstance(bvids, list) or len(bvids) > 20 or any(not isinstance(bv, str) or not re.fullmatch(r'BV[A-Za-z0-9]{10}',bv) for bv in bvids):
                    raise ValueError('invalid video identifiers')
                state['adjustments'].append(dict(board=board, meme_id=identifier, action=edit['action'],
                    position=edit.get('position'), bvids=list(dict.fromkeys(bvids)), starts_at=now, expires_at=now+86400))
        return state

    def _render(self, session, state, now, blocked, *, include_base=False):
        boards, candidates, times = {}, {}, {}
        base_boards = {}
        for board in BOARDS:
            run_id = state['latest'].get(board)
            run = session.execute(select(runs).where(runs.c.id == run_id)).mappings().first() if run_id else None
            source = (run['boards'].get(board) or {}) if run else {}
            times[board] = run['finished_at'] if run else None
            evidence = source.get('evidence', [])
            records = state['dictionary']
            lookup = dictionary_index(records)
            if state['dictionary_version'] and run and not source.get('evidence_complete'):
                raise ValueError('complete evidence required for dictionary recalculation')
            candidates[board] = rank_evidence(board, evidence, records, blocked,
                source.get('songs', []), source.get('seeds', []), all_candidates=True)
            if state['dictionary_version']:
                rows = rank_evidence(board, evidence, records, blocked,
                    source.get('songs', []), source.get('seeds', []))
            else:
                rows = deepcopy(source.get('cards', []))
                for card in rows:
                    label = 'keyword' if board == 'hot_memes' else 'name'
                    identifier, name = resolve(card.get(label) or '', lookup)
                    card['meme_id'] = identifier
                    card['aliases'] = [a for a in card.get('aliases', []) if a != name]
            if include_base:
                base_boards[board] = [
                    {key: item[key] for key in ('meme_id', 'keyword', 'name', 'heat', 'video_count') if key in item}
                    for item in apply_adjustments(board, rows, records, [], blocked, now)
                ]
            boards[board] = apply_adjustments(board, rows, records, state['adjustments'], blocked, now, candidates[board])
            for adjustment in state['adjustments']:
                if adjustment['board'] != board or adjustment['action'] != 'add' or now >= adjustment['expires_at'] or not adjustment.get('bvids'):
                    continue
                bvids = adjustment['bvids']
                metadata = {v['bvid']: v for v in session.execute(select(videos).where(videos.c.bvid.in_(bvids))).mappings()}
                if set(bvids)-set(metadata):
                    raise ValueError('video is not in the collected catalog; wait for collection before linking it')
                item = next((r for r in boards[board] if r['meme_id'] == adjustment['meme_id']), None)
                if item is None:
                    continue
                linked = []
                for bv in bvids:
                    if not any(v['bvid'] == bv for v in item['related_videos']):
                        v = metadata[bv]
                        linked.append(dict(bvid=bv,title=v['title'],cover=v['pic'],duration=v['duration'],
                                           author='',views=None,manual=True))
                if linked:
                    item['related_videos'] = (item['related_videos']+linked)[:20]
                    item.update(heat=None,total_views=None,video_count=None,manual=True,trend_label='人工收录')
        expiry = min((a['expires_at'] for a in state['adjustments'] if a['expires_at'] > now), default=None)
        return dict(boards=boards, sources=deepcopy(state['latest']), source_times=times,
                    dictionary_version=state['dictionary_version'], expires_at=expiry,
                    rules_hash=digest(blocked), candidates=candidates, redirects=deepcopy(state['redirects']),
                    **({'base_boards': base_boards} if include_base else {}))

    def _write_publication(self, session, state, result, now):
        result = deepcopy(result)
        result.pop('candidates', None)
        identifier = uuid4().hex
        result.update(id=identifier, created_at=now)
        if state.get('current'):
            session.execute(publications.update().where(publications.c.id == state['current']).values(superseded_at=now))
        session.execute(insert(publications).values(id=identifier, created_at=now,
            expires_at=result['expires_at'], payload=result))
        state['current'] = identifier
        return result

    def ingest(self, run_id, boards, now, context=None):
        with self.repo.locked(now) as (session, row):
            if session.execute(select(runs.c.id).where(runs.c.id == str(run_id))).first():
                return
            state = self._state(row)
            self._bootstrap(session,state,now)
            lookup = dictionary_index(state['dictionary'])
            session.execute(insert(runs).values(id=str(run_id), finished_at=now, boards=boards, context=context or {}))
            for board, source in boards.items():
                if board not in BOARDS:
                    raise ValueError('invalid board')
                if source.get('complete') is True:
                    state['latest'][board] = str(run_id)
                terms = [h['raw_term'] for h in source.get('evidence', [])]
                terms += [c.get('keyword') or c.get('name') for c in source.get('cards', [])]
                for term in terms:
                    if not term:
                        continue
                    identifier, name = resolve(term, lookup)
                    record = next((r for r in state['dictionary'] if r['id'] == identifier), None)
                    if record is None:
                        record = dict(id=identifier, name=name, aliases=[])
                        state['dictionary'].append(record)
                    if term != name and term not in record['aliases']:
                        record['aliases'].append(term)
                    from utils.meme_aliases import normalize_meme_key
                    lookup[normalize_meme_key(term)] = (identifier,name)
            state['last_run'] = str(run_id)
            self._write_publication(session, state, self._render(session, state, now, self._blocked(session)), now)
            self._save(session, row, now)

    def preview(self, proposal, now):
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            blocked = self._blocked(session)
            proposed = self._proposal(state, proposal, now)
            return dict(self._render(session, proposed, now, blocked),
                        dictionary=proposed['dictionary'],
                        token=self._token(row, proposal, blocked, now), revision=row['revision'])

    def publish(self, owner, request_id, proposal, token, now):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
            raise ValueError('invalid request id')
        with self.repo.locked(now) as (session, row):
            previous = session.execute(select(operations).where(operations.c.id == request_id)).mappings().first()
            request_hash = digest([owner, proposal])
            if previous:
                if previous['payload'].get('request_hash') != request_hash:
                    raise ReviewConflict('request id reused')
                return previous['payload']['result']
            state = self._state(row)
            blocked = self._blocked(session)
            if token != self._token(row, proposal, blocked, now):
                raise ReviewConflict('preview expired; refresh before publishing')
            updated = self._proposal(state, proposal, now)
            result = self._write_publication(session, updated, self._render(session, updated, now, blocked), now)
            updated['reviewed'][owner] = state.get('last_run')
            if proposal.get('dictionary') or proposal.get('adjustments'):
                updated['last_manual'] = request_id
            if proposal.get('dictionary'):
                updated['last_dictionary'] = request_id
            for edit in proposal.get('adjustments', []):
                updated['last_boards'][edit['board']] = request_id
            session.execute(insert(operations).values(id=request_id, owner=owner, created_at=now,
                retain_until=None if proposal.get('dictionary') else now+86400+90*86400,
                payload=dict(request_hash=request_hash, proposal=proposal, before=deepcopy(state),
                             after_dictionary=deepcopy(updated['dictionary']),
                             after_adjustments=deepcopy(updated['adjustments']), result=result)))
            draft = session.execute(select(drafts).where(drafts.c.owner == owner)).mappings().first()
            if draft and draft['payload'].get('proposal') == proposal:
                updated['draft_revisions'][owner] = max(updated['draft_revisions'].get(owner,0),draft['revision'])+1
                session.execute(drafts.delete().where(drafts.c.owner == owner))
            row['payload'] = updated
            self._save(session, row, now)
            return result

    def read_current(self, now):
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            self._bootstrap(session,state,now)
            current = session.execute(select(publications).where(publications.c.id == state.get('current'))).mappings().first()
            blocked = self._blocked(session)
            if current and (current['expires_at'] is None or now < current['expires_at']) and current['payload']['rules_hash'] == digest(blocked):
                return current['payload']
            result = self._write_publication(session, state, self._render(session, state, now, blocked), now)
            self._save(session, row, now)
            return result

    def save_draft(self, owner, proposal, expected_revision, now):
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            self._proposal(state, proposal, now)
            prior = session.execute(select(drafts).where(drafts.c.owner == owner)).mappings().first()
            revision = state['draft_revisions'].get(owner, prior['revision'] if prior else 0)
            if expected_revision != revision:
                raise ReviewConflict('draft changed in another window')
            payload = dict(proposal=proposal, bases=deepcopy(state['latest']), state_revision=row['revision'])
            value = dict(owner=owner, revision=revision+1, edited_at=now, payload=payload)
            session.execute(insert(drafts).values(**value).on_conflict_do_update(
                index_elements=[drafts.c.owner], set_=value))
            state['draft_revisions'][owner] = revision+1
            # A draft change must not invalidate another administrator's publication preview.
            session.execute(states.update().where(states.c.id == 1).values(payload=state))
            return value

    def overview(self, owner, now):
        current = self.read_current(now)
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            draft = session.execute(select(drafts).where(drafts.c.owner == owner)).mappings().first()
            result = self._render(session, state, now, self._blocked(session), include_base=True)
            run = session.execute(select(runs).where(runs.c.id == state.get('last_run'))).mappings().first()
            recent = [dict(id=r['id'],finished_at=r['finished_at'],boards={b:dict(
                complete=v.get('complete') is True, evidence_complete=v.get('evidence_complete') is True,
                count=len(v.get('cards',[]))) for b,v in r['boards'].items()})
                      for r in session.execute(select(runs).order_by(runs.c.finished_at.desc(),runs.c.id).limit(14)).mappings()]
            overlap = {}
            lookup = dictionary_index(state['dictionary'])
            for source in (run['boards'].values() if run else []):
                for hit in source.get('evidence', []):
                    identifier, _ = resolve(hit['raw_term'], lookup)
                    overlap.setdefault(identifier, set()).add(hit['bvid'])
            pool = sorted(overlap, key=lambda identifier: -len(overlap[identifier]))[:60]
            suspected = [dict(source=a, target=b, shared=len(overlap[a] & overlap[b]))
                         for i, a in enumerate(pool) for b in pool[i+1:]
                         if len(overlap[a] & overlap[b]) >= 2
                         and len(overlap[a] & overlap[b])/min(len(overlap[a]),len(overlap[b])) >= .8][:20]
            return dict(current=current, preview=result, revision=row['revision'],
                draft_revision=state['draft_revisions'].get(owner, draft['revision'] if draft else 0),
                suspected_aliases=suspected,
                dictionary=state['dictionary'], redirects=state['redirects'],
                adjustments=state['adjustments'], last_manual=state.get('last_manual'),
                last_boards=state['last_boards'], last_dictionary=state.get('last_dictionary'),
                recent_runs=recent,
                last_run=state.get('last_run'), reviewed_run=state['reviewed'].get(owner),
                needs_review=state.get('last_run') != state['reviewed'].get(owner),
                source_status={b: v.get('source_status', 'complete' if v.get('complete') else 'incomplete')
                               for b, v in (run['boards'] if run else {}).items()},
                draft=dict(draft) if draft and now < draft['edited_at']+14*86400 else None)

    def _undo_state(self, session, state, operation, board=None):
        if board not in (None, 'dictionary', *BOARDS):
            raise ValueError('invalid undo scope')
        latest = (state.get('last_dictionary') if board == 'dictionary' else state['last_boards'].get(board)) if board else state.get('last_manual')
        if latest != operation:
            raise ReviewConflict('only the latest manual operation can be undone; use an explicit correction')
        saved = session.execute(select(operations).where(operations.c.id == operation)).mappings().first()
        if saved is None or 'before' not in saved['payload']:
            raise ReviewConflict('undo is no longer available')
        before = saved['payload']['before']
        result = deepcopy(state)
        # Keep current crawl bases, but never renew the old adjustments' expiry.
        if board in BOARDS:
            if state['dictionary_version'] != saved['payload']['result']['dictionary_version']:
                raise ReviewConflict('dictionary changed; correct the board adjustments explicitly')
            result['adjustments'] = [a for a in result['adjustments'] if a['board'] != board] + [
                deepcopy(a) for a in before['adjustments'] if a['board'] == board]
        else:
            if board == 'dictionary' and state['adjustments'] != saved['payload'].get('after_adjustments', []):
                raise ReviewConflict('adjustments changed after dictionary edit; split or reassign explicitly')
            result['adjustments'] = deepcopy(before['adjustments'])
        if board not in BOARDS and saved['payload']['proposal'].get('dictionary'):
            # Preserve identities discovered by later crawls, unless they conflict.
            old = deepcopy(before['dictionary'])
            identifiers = {r['id'] for r in old}
            old += [r for r in state['dictionary'] if r['id'] not in identifiers
                    and r['id'] not in {d['id'] for d in saved['payload'].get('after_dictionary', [])}]
            validate_dictionary(old)
            result['dictionary'] = old
            result['redirects'] = deepcopy(before['redirects'])
            result['dictionary_version'] += 1
        return result

    def undo_preview(self, operation, now, board=None):
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            updated = self._undo_state(session, state, operation, board)
            blocked = self._blocked(session)
            return dict(self._render(session, updated, now, blocked),
                        token=self._token(row, {'undo': operation, 'board': board}, blocked, now))

    def undo(self, owner, request_id, operation, token, now, board=None):
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            prior = session.execute(select(operations).where(operations.c.id == request_id)).mappings().first()
            fingerprint = digest([owner, {'undo': operation, 'board': board}])
            if prior:
                if prior['payload'].get('request_hash') != fingerprint:
                    raise ReviewConflict('request id reused')
                return prior['payload']['result']
            blocked = self._blocked(session)
            if token != self._token(row, {'undo': operation, 'board': board}, blocked, now):
                raise ReviewConflict('undo preview expired')
            updated = self._undo_state(session, state, operation, board)
            result = self._write_publication(session, updated, self._render(session, updated, now, blocked), now)
            # Undo is itself a durable correction; do not allow undo/redo chains.
            updated['last_manual'] = None
            if board in BOARDS:
                updated['last_boards'].pop(board, None)
            elif board == 'dictionary':
                updated['last_dictionary'] = None
            else:
                updated['last_boards'] = {}
                updated['last_dictionary'] = None
            session.execute(insert(operations).values(id=request_id, owner=owner, created_at=now,
                retain_until=None, payload=dict(request_hash=fingerprint, undo=operation, board=board, result=result)))
            row['payload'] = updated
            self._save(session, row, now)
            return result

    def _cleanup_candidates(self, session, state, now):
        published = session.execute(select(publications).order_by(publications.c.created_at.desc(), publications.c.id)).mappings().all()
        keep = {p['id'] for p in published[:3]} | {state.get('current')}
        eligible_publications = [p['id'] for p in published if p['id'] not in keep
                                and p['superseded_at'] is not None and now >= p['superseded_at']+90*86400]
        protected_runs = set(state['latest'].values()) | {state.get('last_run')}
        for p in published:
            if p['id'] not in eligible_publications:
                protected_runs.update(p['payload']['sources'].values())
        draft_rows = session.execute(select(drafts)).mappings().all()
        for d in draft_rows:
            if now < d['edited_at']+14*86400:
                protected_runs.update(d['payload']['bases'].values())
        protected_operations = set(state['last_boards'].values()) | {state.get('last_manual'), state.get('last_dictionary')}
        for op in session.execute(select(operations).where(operations.c.id.in_(protected_operations-{None})) ).mappings():
            protected_runs.update(op['payload'].get('before', {}).get('latest', {}).values())
        eligible_runs = [r.id for r in session.execute(select(runs.c.id, runs.c.finished_at))
                         if r.id not in protected_runs and now >= r.finished_at+30*86400]
        return dict(runs=eligible_runs, publications=eligible_publications,
            drafts=[d['owner'] for d in draft_rows if now >= d['edited_at']+14*86400],
            operations=[op.id for op in session.execute(select(operations.c.id, operations.c.retain_until))
                        if op.id not in protected_operations and op.retain_until is not None and now >= op.retain_until]), protected_runs

    def cleanup_preview(self, now):
        with self.repo.locked(now) as (session, row):
            eligible, protected = self._cleanup_candidates(session, self._state(row), now)
            return dict(mode='dry_run', eligible={k: len(v) for k, v in eligible.items()},
                        protected_runs=len(protected-{None}), retention_days=dict(drafts=14, runs=30, history=90),
                        last_result=row['payload'].get('cleanup'))

    def cleanup_batch(self, now, limit=100, *, enabled=False):
        if not enabled:
            return dict(self.cleanup_preview(now), deleted=0)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('invalid cleanup batch size')
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            eligible, _ = self._cleanup_candidates(session, state, now)
            deleted = 0
            for name, table, key in [('drafts', drafts, drafts.c.owner), ('publications', publications, publications.c.id),
                                     ('operations', operations, operations.c.id), ('runs', runs, runs.c.id)]:
                ids = eligible[name][:limit-deleted]
                if ids:
                    deleted += session.execute(table.delete().where(key.in_(ids))).rowcount
            state['cleanup'] = dict(at=now, deleted=deleted, status='success')
            self._save(session, row, now)
            return dict(mode='delete', deleted=deleted)

    def seed_snapshot(self):
        from collectors.bilibili import _DEFAULT_MEME_SEED_WORDS
        with self.repo.sessions() as session:
            rows = {r['name']: r for r in session.execute(select(dashboard_state).where(
                dashboard_state.c.name.in_(['meme_seed_words', 'meme_seed_links']))).mappings()}
            seed = rows.get('meme_seed_words')
            row = session.execute(select(states.c.payload).where(states.c.id == 1)).scalar_one_or_none() or {}
            records = self._state(dict(payload=row))['dictionary']
            blocked = self._blocked(session)
            from services.meme_review import blocked_ids
            excluded = blocked_ids(blocked,records)
            blocked_names = sorted(set(blocked) | {term for r in records if r['id'] in excluded for term in [r['name'],*r['aliases']]})
            return dict(words=seed['payload'] if seed else list(_DEFAULT_MEME_SEED_WORDS),
                        version=seed['version'] if seed else 0,
                        links=rows.get('meme_seed_links', {}).get('payload', {}),
                        configured=seed is not None, blocked_names=blocked_names)

    def dictionary_snapshot(self):
        with self.repo.locked(0) as (_, row):
            state = self._state(row)
            return {key: deepcopy(state[key]) for key in ('dictionary', 'dictionary_version')}

    def evidence(self, board, identifier, offset=0):
        if board not in BOARDS or not 0 <= offset <= 100000:
            raise ValueError('invalid evidence query')
        with self.repo.locked(0) as (session, row):
            state = self._state(row)
            run = session.execute(select(runs).where(runs.c.id == state['latest'].get(board))).mappings().first()
            lookup = dictionary_index(state['dictionary'])
            matches = [hit for hit in (run['boards'][board].get('evidence', []) if run else [])
                       if resolve(hit['raw_term'], lookup)[0] == identifier]
            return dict(items=matches[offset:offset+100], total=len(matches), offset=offset,
                        next_offset=offset+100 if len(matches)>offset+100 else None)

    def save_seeds(self, words, links, expected_version, now):
        from utils.meme_aliases import normalize_meme_key
        if not isinstance(words, list) or len(words) > 200 or any(not isinstance(w, str) or not w.strip() or len(w) > 100 for w in words):
            raise ValueError('invalid seed words')
        cleaned = list(dict((normalize_meme_key(w), w.strip()) for w in words).values())
        if links is not None and (not isinstance(links, dict) or set(links)-set(cleaned)):
            raise ValueError('invalid seed links')
        with self.repo.locked(now) as (session, row):
            state = self._state(row)
            if links and any(id not in ({r['id'] for r in state['dictionary']} | set(state['redirects'])) for id in links.values()):
                raise ValueError('unknown seed identity')
            seed = session.execute(select(dashboard_state).where(
                dashboard_state.c.name == 'meme_seed_words').with_for_update()).mappings().first()
            version = seed['version'] if seed else 0
            if type(expected_version) is not int or version != expected_version:
                raise ReviewConflict('seed settings changed; reload before saving')
            if links is None:
                old = session.execute(select(dashboard_state.c.payload).where(
                    dashboard_state.c.name == 'meme_seed_links')).scalar_one_or_none() or {}
                links = {w: id for w, id in old.items() if w in cleaned}
            for name, payload in [('meme_seed_words', cleaned), ('meme_seed_links', links)]:
                session.execute(insert(dashboard_state).values(name=name, payload=payload, version=version+1,
                    updated_at=now).on_conflict_do_update(index_elements=[dashboard_state.c.name],
                        set_=dict(payload=payload, version=version+1, updated_at=now)))
            return dict(words=cleaned, links=links, version=version+1, effective='next_crawl')


_service = None


def configure_meme_review(sessions):
    global _service
    from storage.repositories.meme_review import MemeReviewRepository
    _service = MemePublicationService(MemeReviewRepository(sessions)) if sessions else None


def get_meme_review_service():
    if _service is None:
        raise RuntimeError('review storage is not configured')
    return _service


def public_review_data(data, now=None):
    import os
    import time
    if os.environ.get('MEME_REVIEW_MODE', 'shadow') != 'active':
        return data
    from sqlalchemy.exc import SQLAlchemyError
    try:
        result = get_meme_review_service().read_current(int(time.time()) if now is None else now)
    except (SQLAlchemyError, ValueError, RuntimeError) as error:
        raise ReviewUnavailable('review publication temporarily unavailable') from error
    if any(board not in result['sources'] for board in BOARDS):
        raise ReviewUnavailable('review publication awaits complete source evidence')
    return dict(data, **result['boards'], meme_publication={k: result[k] for k in
        ('id', 'expires_at', 'source_times', 'dictionary_version', 'redirects')})
