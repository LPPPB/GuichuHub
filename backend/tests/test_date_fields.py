
from collectors.bilibili import fetch_ranking, KICHU_TID

data = fetch_ranking(tid=KICHU_TID, day=3)
if data:
    print('=== 排行榜原始数据字段 ===')
    v = data[0]
    for k in sorted(v.keys()):
        val = v[k]
        if isinstance(val, str) and len(val) > 50:
            val = val[:50] + '...'
        print(f'  {k}: {val}')
    print()
    print('=== 前3条视频的日期相关字段 ===')
    for i, v in enumerate(data[:3]):
        print(f'{i+1}. {v.get("title", "")[:40]}')
        print(f'   create: {v.get("create")}')
        print(f'   pubdate: {v.get("pubdate")}')
        print(f'   senddate: {v.get("senddate")}')
