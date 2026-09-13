
from collectors.bilibili import get_kichu_videos

videos = get_kichu_videos()
print(f'共获取 {len(videos)} 条视频')
for i, v in enumerate(videos[:5]):
    print(f'{i+1}. {v["title"][:50]}')
    print(f'   播放:{v["views"]}  UP:{v["author"]}')
    print(f'   bvid:{v["bvid"]}  时长:{v["duration"]}秒')
