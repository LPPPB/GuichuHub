"""Pure review calculations. Stored evidence and publications remain immutable."""
from copy import deepcopy
from utils.meme_aliases import normalize_meme_key, normalize_meme_name, load_meme_aliases
from utils.scorer import calc_meme_heat, get_trend_label
from config import HOT_MEME_VIEWS_MIN

BOARDS = ('hot_memes', 'meme_materials')
LIMITS = {'hot_memes': 30, 'meme_materials': 10}


def validate_dictionary(records):
    terms, ids = {}, set()
    for record in records:
        identifier = record.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('invalid or duplicate identity')
        ids.add(identifier)
        if not isinstance(record.get('aliases'), list):
            raise ValueError('invalid aliases')
        for term in [record.get('name'), *record['aliases']]:
            if not isinstance(term, str) or not normalize_meme_key(term) or len(term) > 200:
                raise ValueError('invalid alias')
            key = normalize_meme_key(term)
            if key in terms and terms[key] != identifier:
                raise ValueError('alias conflict: ' + term)
            terms[key] = identifier
    return terms


def dictionary_index(records):
    if isinstance(records, dict):
        return records
    return {normalize_meme_key(term): (record['id'],record['name'])
            for record in records for term in [record['name'],*record['aliases']]}


def resolve(word, records):
    lookup = dictionary_index(records)
    key = normalize_meme_key(word)
    return lookup[key] if key in lookup else load_meme_aliases().resolve(word)


def blocked_ids(blocked, records):
    lookup = dictionary_index(records)
    return {resolve(word, lookup)[0] for word in blocked}


def rank_evidence(board, evidence, records, blocked, songs=(), seeds=(), *, all_candidates=False):
    validate_dictionary(records)
    lookup = dictionary_index(records)
    groups = {}
    excluded = blocked_ids(blocked, lookup)
    for hit in evidence:
        identifier, name = resolve(hit['raw_term'], lookup)
        if identifier in excluded:
            continue
        group = groups.setdefault(identifier, dict(name=name, terms=set(), videos={}, tags=set(),
                                                   titles=set(), seed_ranks={}))
        group['terms'].add(hit['raw_term'])
        bv = hit['bvid']
        row = deepcopy(hit['video'])
        # Prefer the newest observation for duplicate BV evidence, never add metrics twice.
        old = group['videos'].get(bv)
        if old is None or (row.get('observed_at') or 0) > (old.get('observed_at') or 0):
            group['videos'][bv] = row
        group['tags' if hit['source'] == 'tag' else 'titles'].add(bv)
        rank = hit.get('seed_search_rank')
        if rank is not None:
            ranks = group['seed_ranks']
            ranks[bv] = min(rank, ranks.get(bv, rank))
    seed_ids = {resolve(s, lookup)[0] for s in seeds}
    selected_sources = {}
    if board == 'meme_materials' and not all_candidates:
        tagged = sorted((id for id, g in groups.items() if len(g['tags']) >= 2),
                        key=lambda id: (-len(groups[id]['tags']), groups[id]['name']))
        tagged_bvids = {bv for id in tagged for bv in groups[id]['tags']}
        titled = sorted((id for id, g in groups.items() if len(g['titles']) >= 3 or id in seed_ids),
                        key=lambda id: (id not in seed_ids, -len(groups[id]['titles']), groups[id]['name']))
        assigned, selected = set(), {}
        for id, source in [(id, 'tags') for id in tagged] + [(id, 'titles') for id in titled]:
            if id in selected:
                continue
            bvs = groups[id][source] - assigned
            if len(bvs) < (1 if source == 'titles' and id in seed_ids else 2):
                continue
            if source == 'tags' and id in seed_ids:
                bvs |= (groups[id]['titles'] & groups[id]['seed_ranks'].keys()) - tagged_bvids - assigned
            selected[id] = dict(groups[id], videos={bv: groups[id]['videos'][bv] for bv in bvs})
            selected_sources[id] = source
            assigned.update(bvs)
            if len(selected) == LIMITS[board]:
                break
        groups = selected
    entries = []
    for identifier, group in groups.items():
        ranks = group['seed_ranks'] if board == 'meme_materials' and identifier in seed_ids else {}
        videos = sorted(group['videos'].values(),
                        key=lambda v: (ranks.get(v['bvid'], float('inf')), -(v.get('views') or 0), v['bvid']))
        views = sum(v.get('views') or 0 for v in videos)
        aliases = set(group['terms'])
        for record in records:
            if record['id'] == identifier:
                aliases.update(record['aliases'])
        aliases = sorted(a for a in aliases if normalize_meme_key(a) != normalize_meme_key(group['name']))
        common = dict(meme_id=identifier, aliases=aliases, video_count=len(videos), total_views=views)
        if board == 'hot_memes':
            if not all_candidates and (len(videos) < 2 or views <= HOT_MEME_VIEWS_MIN):
                continue
            engagement = sum(sum(v.get(k) or 0 for k in ('likes', 'coins', 'favorites', 'shares')) for v in videos)
            trend = round(sum(v.get('trend_score') or 0 for v in videos) / len(videos), 1)
            entries.append(dict(common, keyword=group['name'], total_engagement=engagement,
                heat=calc_meme_heat(views, len(videos), engagement), trend_score=trend,
                trend_label=get_trend_label(trend), related_videos=videos[:5]))
        else:
            tagged = selected_sources.get(identifier) == 'tags' if not all_candidates else len(group['tags']) >= 2
            if not all_candidates and not tagged and len(group['titles']) < (1 if identifier in seed_ids else 3):
                continue
            related_songs = [s for s in songs if any(t.casefold() in s.get('name', '').casefold()
                              for t in group['terms'])][:5]
            entries.append(dict(common, name=group['name'], related_videos=videos[:10],
                related_songs=deepcopy(related_songs), heat=views + len(related_songs)*100000,
                description='相关视频: ' + ' / '.join(v.get('title', '')[:20] for v in videos[:3]),
                evidence_source='tag' if tagged else 'title'))
    entries.sort(key=lambda row: (0 if board == 'hot_memes' or row['evidence_source'] == 'tag' else 1,
                                  -row['heat'], row['meme_id']))
    return entries if all_candidates else entries[:LIMITS[board]]


def apply_adjustments(board, rows, records, adjustments, blocked, now, candidates=()):
    excluded = blocked_ids(blocked, records)
    items = {r['meme_id']: deepcopy(r) for r in rows if r['meme_id'] not in excluded}
    available = {r['meme_id']: r for r in candidates}
    positions, seen, reserved = {}, set(), set()
    for adjustment in adjustments:
        if adjustment['board'] != board or now >= adjustment['expires_at']:
            continue
        identifier = adjustment['meme_id']
        if identifier in seen:
            raise ValueError('duplicate adjustment')
        seen.add(identifier)
        if identifier in excluded:
            continue
        action = adjustment['action']
        if action == 'hide':
            items.pop(identifier, None)
            continue
        if action == 'add' and identifier not in items:
            if identifier in available:
                items[identifier] = deepcopy(available[identifier])
            else:
                record = next((r for r in records if r['id'] == identifier), None)
                if record is None:
                    raise ValueError('unknown identity')
                items[identifier] = dict(meme_id=identifier, **{
                    'keyword' if board == 'hot_memes' else 'name': record['name']},
                    aliases=record['aliases'], heat=None, total_views=None, video_count=None,
                    related_videos=[], related_songs=[], trend_label='人工收录')
            items[identifier]['manual'] = True
        if action not in ('add', 'position'):
            raise ValueError('invalid adjustment action')
        position = adjustment.get('position')
        if position is not None:
            if type(position) is not int or not 1 <= position <= LIMITS[board]:
                raise ValueError('invalid position')
            if position in reserved:
                raise ValueError('position conflict')
            reserved.add(position)
            if identifier in items:
                positions[position] = identifier
                items[identifier]['manual_position'] = position
    queue = [r for key, r in items.items() if key not in positions.values()]
    # A manual addition reserves a slot even when the automatic result is full.
    queue.sort(key=lambda row: not row.get('manual', False))
    result = []
    for position in range(1, LIMITS[board]+1):
        if position in positions:
            result.append(items[positions[position]])
        elif queue:
            result.append(queue.pop(0))
    return result
