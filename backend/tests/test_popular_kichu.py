"""Manual upstream inspection; importing never performs HTTP."""

def main():

    from collectors.bilibili import fetch_popular_multi, KICHU_TID
    from datetime import datetime

    videos = fetch_popular_multi(pages=5, ps=50)
    print(f'全站热门共获取 {len(videos)} 条视频')

    kichu_videos = []
    for v in videos:
        tid = v.get('tid', 0)
        tname = v.get('tname', '')
        if tid == KICHU_TID or (tname and ('鬼畜' in tname or '人力' in tname or '音MAD' in tname)):
            kichu_videos.append(v)

    print(f'其中鬼畜区视频 {len(kichu_videos)} 条')
    print()
    print('=== 前10条鬼畜视频 ===')
    for i, v in enumerate(kichu_videos[:10]):
        title = v.get('title', '')
        views = v.get('stat', {}).get('view', 0)
        pubdate = v.get('pubdate', 0)
        tname = v.get('tname', '')
        date_str = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%d') if pubdate else '未知'
        print(f'{i+1}. {title[:50]}')
        print(f'   播放:{views}  分区:{tname}  发布日期:{date_str}')


if __name__ == "__main__":
    main()
