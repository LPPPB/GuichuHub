import json
import os
from datetime import datetime, timezone, timedelta

# 中国时区：显式 UTC+8，不依赖系统本地时区
CN_TZ = timezone(timedelta(hours=8))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

def get_db_path():
    return os.path.join(DATA_DIR, 'inspiration_db.json')

def init_db():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    db_path = get_db_path()
    if not os.path.exists(db_path):
        initial_data = {
            'hot_memes': [],
            'hot_songs': [],
            'hot_videos': [],
            'danmaku_words': [],
            'comments_gold': [],
            'favorites': [],
            'last_updated': None
        }
        save_data(initial_data)

def load_data():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        init_db()
    with open(db_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_data(data):
    db_path = get_db_path()
    data['last_updated'] = datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    with open(db_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_favorite(item_type, item, owner=None):
    data = load_data()
    item['id'] = f"{item_type}_{int(datetime.now(CN_TZ).timestamp())}"
    item['type'] = item_type
    item['saved_at'] = datetime.now(CN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    item['tags'] = item.get('tags', [])
    item['notes'] = item.get('notes', '')
    item['owner'] = owner
    data['favorites'].append(item)
    save_data(data)
    return item

def remove_favorite(item_id, owner=None):
    """删除收藏（带归属校验）。返回是否真正删除（False = 不存在或不属于该 owner）。"""
    data = load_data()
    before = len(data['favorites'])
    data['favorites'] = [
        f for f in data['favorites']
        if not (f['id'] == item_id and f.get('owner') == owner)
    ]
    removed = before > len(data['favorites'])
    if removed:
        save_data(data)
    return removed

def update_favorite(item_id, tags=None, notes=None, owner=None):
    data = load_data()
    for fav in data['favorites']:
        if fav['id'] == item_id and fav.get('owner') == owner:
            if tags is not None:
                fav['tags'] = tags
            if notes is not None:
                fav['notes'] = notes
            save_data(data)
            return fav
    return None

def get_favorites(item_type=None, tag=None, owner=None):
    data = load_data()
    favs = data['favorites']
    # 归属过滤：无 owner 时不返回任何收藏（fail-closed，防止跨用户泄露）
    favs = [f for f in favs if f.get('owner') == owner]
    if item_type:
        favs = [f for f in favs if f['type'] == item_type]
    if tag:
        favs = [f for f in favs if tag in f.get('tags', [])]
    return favs

def migrate_legacy_favorites(mid):
    """存量收藏迁移：把无主收藏 + 旧的写口令归属('admin')收藏，认领给首个登录的 B站管理员 mid。

    幂等。仅由「B站管理员会话」触发（普通登录用户不触发，防抢认站长旧收藏）。
    返回认领条数。
    """
    target = str(mid)
    data = load_data()
    claimed = 0
    for fav in data['favorites']:
        owner = fav.get('owner')
        if owner is None or owner == 'admin':
            fav['owner'] = target
            claimed += 1
    if claimed:
        save_data(data)
    return claimed
