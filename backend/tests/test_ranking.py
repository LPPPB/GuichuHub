"""Manual network probe; importing this module never runs it."""

def main():

    import requests
    from collectors.bilibili import fetch_ranking, KICHU_TID, MUSIC_TID

    print('=== 测试鬼畜区排行榜 (rid=119) ===')
    data = fetch_ranking(tid=119, day=3)
    print(f'返回视频数: {len(data)}')
    if data:
        for i, v in enumerate(data[:5]):
            title = v.get('title', '')
            play = v.get('play', 0)
            bvid = v.get('bvid', '')
            author = v.get('author', '')
            pubdate = v.get('pubdate', 0)
            print(f'  {i+1}. {title[:60]}')
            print(f'     播放:{play}  UP:{author}  bvid:{bvid}  pubdate:{pubdate}')
    else:
        print('  无数据')

    print()
    print('=== 测试音乐区排行榜 (rid=3) ===')
    data = fetch_ranking(tid=3, day=3)
    print(f'返回视频数: {len(data)}')
    if data:
        for i, v in enumerate(data[:3]):
            title = v.get('title', '')
            play = v.get('play', 0)
            bvid = v.get('bvid', '')
            print(f'  {i+1}. {title[:60]}  播放:{play}  bvid:{bvid}')
    else:
        print('  无数据')


if __name__ == "__main__":
    main()
