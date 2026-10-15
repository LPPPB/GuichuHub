import requests
import random
import time
import re
import os
import html
from datetime import datetime, timezone, timedelta
from config import (
    POTENTIAL_VIEWS_MAX, POTENTIAL_VIEWS_MIN,
    POTENTIAL_ENGAGEMENT_MIN, POTENTIAL_AGE_DAYS,
    HOT_MEME_VIEWS_MIN,
    ONLINE_BREAK_THRESHOLD, ONLINE_BREAK_COOLDOWN, ONLINE_BREAK_HALF_OPEN_LIMIT,
    KICHU_TIDS,          # 鬼畜子分区（唯一真源 config.py，禁止本地再定义）
    KICHU_TIDS_WITH_PARENT,  # 含父分区 119 的评分/查询集合
    MUSIC_TID, MUSIC_TIDS,
    FUNNY_TID, FUNNY_TIDS,
)
from utils.scorer import (
    calc_trend_score,
    get_trend_label,
    calc_meme_heat,
    extract_keywords_from_title,
    is_potential_candidate,
    score_potential_batch,
    get_potential_reason,
    calc_engagement_quality,
    is_material_candidate,
    score_material_batch,
    get_material_reason,
)
from storage.db import get_video_obs_trend  # 同接跨轮平滑（L2）读取 video_obs 历史序列
from storage.runtime_settings import RUNTIME_SETTING_CACHE_REFRESH_SECONDS

_monotonic = time.monotonic

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
]

# 鬼畜调教分区ID（历史遗留单分区常量，仅测试/搜索用；分区集合以 config.KICHU_TIDS 为唯一真源）
# 鬼畜区子分区：22=鬼畜调教  26=音MAD  126=人力VOCALOID  216=鬼畜剧场
# 已移除的历史错配：119(父分区)/127(教程)/217(动物圈)/218(喵星人)/221(野生动物)
KICHU_TID = 22

# 中国时区：B站API返回的时间字符串均为北京时间。
# 全项目统一：存储用 Unix 时间戳，解析显式 UTC+8——
# naive datetime.timestamp() 会按系统本地时区解释，模式A分发到其他时区会出错
CN_TZ = timezone(timedelta(hours=8))

# ── 梗素材库停用词表（PostgreSQL 覆盖 + 随版本发布的默认词表）──
# 内置兜底会在下方用完整的发布词表替换。
_FALLBACK_MEME_STOPWORDS = {
    '通用制作词': ['鬼畜', '视频', '音乐', '歌曲', '制作', '剪辑', '合集', '原创',
                 '系列', '教程', '完整', '高清', '版本', '混音', '调教', '人力', '剧场'],
    '虚词/代词/量词': ['什么', '怎么', '这个', '那个', '一个', '一些', '一种', '真的',
                    '可以', '应该', '可能', '时候', '这么', '那么', '只是', '还是',
                    '就是', '不过', '然后', '其实', '已经'],
}

from utils.release_word_rules import MEME_SEED_WORDS, MEME_STOPWORDS, TAG_FILTERS

_FALLBACK_MEME_STOPWORDS = {
    key: list(values) for key, values in MEME_STOPWORDS.items()
}


def load_meme_stopwords():
    """读取 PostgreSQL 覆盖值；未配置时使用随版本发布的内置兜底。"""
    from storage.runtime_settings import load_runtime_setting
    categories = load_runtime_setting('meme_stopwords', _FALLBACK_MEME_STOPWORDS)
    cleaned = {}
    if isinstance(categories, dict):
        for key, values in categories.items():
            if isinstance(values, list):
                words = [str(word) for word in values if isinstance(word, str) and word.strip()]
                if words:
                    cleaned[key] = words
    return cleaned or {key: list(values) for key, values in _FALLBACK_MEME_STOPWORDS.items()}


def save_meme_stopwords(categories):
    """保存梗素材库停用词表到 PostgreSQL。"""
    from storage.runtime_settings import save_runtime_setting
    cleaned = {key: list(values) for key, values in categories.items() if values}
    save_runtime_setting('meme_stopwords', cleaned)


# ── 梗素材库种子热梗词（PostgreSQL 覆盖 + 随版本发布的默认词表）──
# 背景：梗素材库靠 4 路采集（鬼畜/音乐/搞笑/全站热门）的候选池自动发现高频词，
# 但那些搜索词全是制作/类型词（鬼畜/音MAD/洗脑/魔性等），从不按热梗词搜索，
# 导致哈基米/叮咚鸡等常驻热梗在候选池中频次不足 3 被过滤。这里按种子词主动
# 搜索补足候选池，保证热梗能进入梗素材库（见 fetch_meme_seed_videos）。
_DEFAULT_MEME_SEED_WORDS = list(MEME_SEED_WORDS)


def load_meme_seed_words():
    """读取 PostgreSQL 种子词覆盖值，未配置时使用版本默认值。"""
    from storage.runtime_settings import load_runtime_setting
    words = load_runtime_setting('meme_seed_words', _DEFAULT_MEME_SEED_WORDS)
    return [str(word).strip() for word in words if isinstance(word, str) and word.strip()]


def save_meme_seed_words(words):
    """保存梗素材库种子热梗词列表到 PostgreSQL。"""
    from storage.runtime_settings import save_runtime_setting
    cleaned = [str(w).strip() for w in words if isinstance(w, str) and str(w).strip()]
    save_runtime_setting('meme_seed_words', cleaned)

def get_headers():
    """构造请求头，自动注入登录态 Cookie。

    Cookie 来源：collectors.bilibili_auth.get_cookie_str() 读取本地 cookie 文件。
    - 已登录：注入 SESSDATA 等，享受登录用户限流阈值（约 5-10 倍游客）
    - 未登录/过期：get_cookie_str() 返回 None，降级为游客模式，不报错

    函数内 import bilibili_auth 避免循环依赖（collectors/__init__.py 加载
    bilibili 时会触发链式加载，懒加载确保 bilibili_auth 不被提前引用）。
    """
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://www.bilibili.com/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }
    try:
        from collectors.bilibili_auth import get_cookie_str
        cookie_str = get_cookie_str()
        if cookie_str:
            headers['Cookie'] = cookie_str
    except Exception:
        pass  # 模块加载失败或未登录时降级为游客模式
    return headers


def safe_get(url, params=None, max_retries=2, return_error_code=False):
    for i in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=get_headers(), params=params, timeout=10)
            # 412 限流：记录日志但不立即抛出，走重试逻辑
            if resp.status_code == 412:
                from logger import get_logger
                get_logger(__name__).warning(f'[412限流] {url} (重试 {i+1}/{max_retries+1})')
                if i < max_retries:
                    time.sleep(1.5 * (2 ** i))  # 指数退避 1.5s → 3s
                    continue
                # 重试耗尽：-412 是风控信号。return_error_code=True 时返回
                # {'code': -412} 让调用方区分风控与普通失败（同接熔断需立即熔断）。
                if return_error_code:
                    return {'code': -412}
                break
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') == 0:
                return data
            time.sleep(0.5)
        except Exception as e:
            if i < max_retries:
                time.sleep(1)
            else:
                print(f'请求失败 {url}: {e}')
    return None

def _normalize_url(url):
    """补全协议相对URL，如 //host/path → https://host/path"""
    if url and url.startswith('//'):
        return 'https:' + url
    return url

def fetch_popular(ps=50, pn=1):
    url = 'https://api.bilibili.com/x/web-interface/popular'
    data = safe_get(url, params={'ps': ps, 'pn': pn})
    if data:
        return data['data']['list']
    return []

def fetch_ranking(tid=0, day=3):
    url = 'https://api.bilibili.com/x/web-interface/ranking/region'
    data = safe_get(url, params={'rid': tid, 'day': day})
    if data and isinstance(data.get('data'), list):
        return data['data']
    return []

def fetch_ranking_v2(rid=0):
    """全站排行榜（ranking/v2）。

    本函数保留旧的列表返回契约，默认 rid=0 用于独立发现。
    新版官方鬼畜榜 rid=1007 的保序解析、状态及失败处理由 official_ranking 模块负责。
    字段结构与 popular feed 一致（stat/owner/pubdate/tid/tname/pic），可直接用 parse_video_item 解析。
    """
    url = 'https://api.bilibili.com/x/web-interface/ranking/v2'
    data = safe_get(url, params={'rid': rid})
    if data and data.get('data') and isinstance(data['data'].get('list'), list):
        return data['data']['list']
    return []


def fetch_newlist_region(rid, ps=20, pn=1):
    """分区最新发布（x/web-interface/newlist）。

    背景：潜力榜三源（热门feed/关键词搜索/全站榜）全是"找已热门"的逻辑，
    刚发布的低播放视频（同接可能很高）三条路都覆盖不到。newlist 是 web 端
    分区页"最新"排序使用的接口，返回按发布时间的视频列表，用于补足
    "低播放高同接"新视频的发现盲区。

    限制（实测 2026-08-07）：
    - 仅一级分区（rid=119 鬼畜）有效；子分区（rid=22 等）返回空列表
    - 只支持 1 页（pn>1 与 pn=1 完全重复），ps 最大 20
    - 排序为"发布时间+推荐"混合，非严格 ctime 降序，但整体是最近发布的
    - stat 全为 0（刚发布无统计），需调用方补抓真实互动数据
    - 可能混入非目标分区视频，需按 tid 过滤

    字段结构与 popular feed 一致，可直接用 parse_video_item 解析。
    """
    url = 'https://api.bilibili.com/x/web-interface/newlist'
    data = safe_get(url, params={'rid': rid, 'type': 0, 'pn': pn, 'ps': ps})
    if data and data.get('data') and isinstance(data['data'].get('archives'), list):
        return data['data']['archives']
    return []


def fetch_kichu_newest(limit=20):
    """鬼畜区最新发布视频（发现源4：补足低播放高同接新视频盲区）。

    从 newlist rid=119（鬼畜一级分区）取最新发布，按 KICHU_TIDS 过滤后
    用 parse_video_item 解析。newlist stat 全为 0，统一打 _stats_estimated
    标记，由 _filter_potential_candidates 入口补抓真实互动数据后走正常门槛。

    返回：video dict 列表（仅含 tid∈KICHU_TIDS，上限 limit 条）。
    """
    collected = []
    seen = set()
    for v in fetch_newlist_region(rid=119):
        bvid = v.get('bvid', '')
        if not bvid or bvid in seen:
            continue
        real_tid = _to_int_tid(v.get('tid') or v.get('typeid') or 0)
        if real_tid not in KICHU_TIDS:
            continue
        seen.add(bvid)
        item = parse_video_item(v, with_tags=False)
        item['_stats_estimated'] = True  # newlist stat 全 0，需补抓
        item['metrics_source'] = 'estimated'
        item.pop('observed_at', None)
        collected.append(item)
        if len(collected) >= limit:
            break
    return collected

def fetch_search_videos(tid, page=1, ps=20, keyword='', order='pubdate'):
    """搜索指定分区的视频。order: pubdate(最新) / click(播放) / scores(综合)"""
    url = 'https://api.bilibili.com/x/web-interface/search/type'
    params = {
        'search_type': 'video',
        'keyword': keyword,
        'order': order,
        'duration': 0,
        'tids': tid,
        'page': page,
        'ps': ps,
    }
    data = safe_get(url, params)
    if data and data.get('data') and data['data'].get('result'):
        return data['data']['result']
    return []

def fetch_search_videos_by_keyword(keyword, tid, pages=2, ps=20, order='pubdate'):
    """多页搜索指定关键词+分区的视频"""
    all_videos = []
    seen = set()
    for pn in range(1, pages + 1):
        results = fetch_search_videos(tid, page=pn, ps=ps, keyword=keyword, order=order)
        if not results:
            break
        for v in results:
            bvid = v.get('bvid', '')
            if bvid and bvid not in seen:
                seen.add(bvid)
                all_videos.append(v)
        time.sleep(0.6)
    return all_videos

def fetch_meme_seed_videos():
    """按种子热梗词主动搜索鬼畜区，补充梗素材库候选池。

    背景：梗素材库候选池来自 4 路采集（鬼畜/音乐/搞笑/全站热门），但那些搜索词
    全是制作/类型词（鬼畜/音MAD/洗脑/魔性等），从不按热梗词搜索，导致哈基米/
    叮咚鸡等常驻热梗在候选池中频次不足 3 被过滤。这里按种子词主动搜索补足。

    返回：parse_region_rank_item 解析后的视频 dict 列表（已按 KICHU_TIDS 过滤分区）。
    种子词来自 PostgreSQL 可变覆盖；未覆盖时使用随版本发布的只读默认词表。
    """
    seed_words = load_meme_seed_words()
    if not seed_words:
        return []
    collected = []
    seen = set()
    for kw in seed_words:
        try:
            # 按播放量排序（click），优先收录播放高的热梗作品
            results = fetch_search_videos_by_keyword(kw, tid=22, pages=2, ps=20, order='click')
        except Exception as e:
            print(f'  种子词"{kw}"搜索失败: {e}')
            continue
        added = 0
        for video in results:
            bvid = video.get('bvid', '')
            if not bvid or bvid in seen:
                continue
            # 搜索 tid 参数不严格（关键词命中即可），按视频真实分区过滤
            real_tid_raw = video.get('typeid') or video.get('tid') or 0
            try:
                real_tid = int(real_tid_raw) if real_tid_raw else 0
            except (ValueError, TypeError):
                real_tid = 0
            if real_tid not in KICHU_TIDS:
                continue
            seen.add(bvid)
            collected.append(parse_region_rank_item(video, tid=real_tid))
            added += 1
        print(f'  梗种子词"{kw}": +{added} 条（搜索返回 {len(results)} 条）')
    print(f'梗素材种子词搜索合计: {len(collected)} 条')
    return collected

def fetch_video_tags(bvid):
    url = 'https://api.bilibili.com/x/tag/archive/tags'
    data = safe_get(url, params={'bvid': bvid})
    if data and data.get('data'):
        return [t['tag_name'] for t in data['data']]
    return []

def fetch_video_detail(bvid):
    url = 'https://api.bilibili.com/x/web-interface/view'
    data = safe_get(url, params={'bvid': bvid})
    if data and data.get('data'):
        return data['data']
    return None


def fetch_video_conclusion(bvid, cid=None, up_mid=None):
    """获取视频 AI 总结（B站官方 AI 生成的摘要 + 大纲）。

    需要 WBI 签名（已由 safe_get_with_wbi 自动处理）。
    依赖 cid 和 up_mid，未提供时自动从 fetch_video_detail 获取。

    返回 dict 结构（成功时包含 data.model_result.summary / data.model_result.outline）：
    {
        'success': True,
        'summary': 'AI 生成的视频总结文本...',
        'outline': [
            {'title': '章节标题', 'timestamp': 120, 'part_outline': [...]},
            ...
        ]
    }
    失败时返回 {'success': False, 'message': '...'}。
    """
    try:
        from collectors.bilibili_auth import safe_get_with_wbi

        if not cid or not up_mid:
            detail = fetch_video_detail(bvid)
            if not detail:
                return {'success': False, 'message': '获取视频详情失败'}
            cid = cid or detail.get('cid')
            up_mid = up_mid or detail.get('owner', {}).get('mid')

        if not cid or not up_mid:
            return {'success': False, 'message': '无法获取 cid 或 up_mid'}

        data = safe_get_with_wbi(
            'https://api.bilibili.com/x/web-interface/view/conclusion/get',
            {'bvid': bvid, 'cid': cid, 'up_mid': up_mid}
        )

        if data is None:
            return {'success': False, 'message': '请求失败（无Cookie/网络异常）'}
        if isinstance(data, dict) and data.get('error') == 'cookie_expired':
            return {'success': False, 'message': 'Cookie已过期，请重新登录'}
        if data.get('code') != 0 or not data.get('data'):
            return {'success': False, 'message': f'API返回错误: {data.get("message", "未知")}'}

        # B站 AI 总结接口内部有嵌套 code：0=有总结，1=该视频无总结
        inner_code = data['data'].get('code', 1)
        if inner_code != 0:
            return {'success': False, 'message': '该视频暂无 AI 总结'}

        model_result = data['data'].get('model_result', {})
        summary = model_result.get('summary', '')
        outline = model_result.get('outline', [])

        return {
            'success': True,
            'summary': summary,
            'outline': outline,
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


# ── 同接抓取熔断（L3 降级）────────────────────────────────
# 单点同接请求被 B 站风控拦截（-412）时，继续逐条请求会加剧风控。
# 熔断策略：连续失败自动停止发起同接请求（降级为历史平滑值回退），
# 冷却到期后自动进入半开探测，连续成功达到配额才恢复闭合；任一次
# 探测失败立即重熔（刷新冷却）。与评分层批内中性化（L1）联动：
# 熔断期 raw 全为 None → 批内失败率 >50% → 评分自动中性。
# 三态：闭合(fails<阈值) / 打开(冷却中，全部跳过) / 半开(冷却到期，放行探测)。
_ONLINE_BREAKER = {'fails': 0, 'open_ts': 0, 'probes': 0, 'probe_ok': 0}


# ── 熔断状态历史（内存环形缓冲，重启清空——与熔断器本身生命周期一致）──
# 每次状态变化记录一条 {ts, state, fails}，供 /api/status 趋势图实时展示。
_ONLINE_BREAKER_TREND = []
_ONLINE_BREAKER_TREND_MAX = 100


def _breaker_trend_record(action, fails):
    """记录熔断状态变化到环形缓冲（action: open/closed/reopen）。"""
    t = _ONLINE_BREAKER_TREND
    t.append({'ts': int(time.time()), 'state': action, 'fails': fails})
    if len(t) > _ONLINE_BREAKER_TREND_MAX:
        del t[:len(t) - _ONLINE_BREAKER_TREND_MAX]


def get_online_breaker_trend(limit=50):
    """返回最近熔断状态历史（供 /api/status 趋势图）。"""
    return list(_ONLINE_BREAKER_TREND)[-limit:]


def _breaker_event(action):
    """熔断状态变化事件：日志 + 趋势记录 + 邮件告警（open/reopen 发、closed 重置）。"""
    b = _ONLINE_BREAKER
    from logger import get_logger
    get_logger(__name__).warning(
        f'[同接熔断] {action}: fails={b["fails"]} probes={b["probes"]} '
        f'probe_ok={b["probe_ok"]} cooldown={ONLINE_BREAK_COOLDOWN}s')
    _breaker_trend_record(action, b['fails'])
    from utils.alerter import send_breaker_alert, reset_breaker_alert
    if action in ('open', 'reopen'):
        send_breaker_alert(action, b['fails'])
    elif action == 'closed':
        reset_breaker_alert()


def _online_breaker_open():
    """熔断是否处于打开状态（调用方应跳过同接请求）。
    三态判定：闭合 → False；打开（冷却中）→ True；
    半开（冷却到期）→ 放行探测直到配额用尽（probes >= HALF_OPEN_LIMIT 防呆，正常不可达）。"""
    b = _ONLINE_BREAKER
    if b['fails'] < ONLINE_BREAK_THRESHOLD:
        return False  # 闭合
    if time.time() - b['open_ts'] <= ONLINE_BREAK_COOLDOWN:
        return True   # 打开：冷却中，全部跳过
    # 半开：冷却已到期，放行探测（配额由 _online_breaker_record 累计）
    return b['probes'] >= ONLINE_BREAK_HALF_OPEN_LIMIT


def _online_breaker_record(success, blocked=False):
    """记录一次同接请求结果。blocked=True 表示 -412 风控（立即熔断）。
    闭合态：成功清零；失败累计达阈值 → 打开并开始冷却。
    半开态：成功累计 probe_ok，连续达标配额恢复闭合；任一次失败立即重熔。"""
    b = _ONLINE_BREAKER
    if b['fails'] < ONLINE_BREAK_THRESHOLD:
        if success:
            b['fails'] = 0
        else:
            b['fails'] = ONLINE_BREAK_THRESHOLD if blocked else b['fails'] + 1
            if b['fails'] >= ONLINE_BREAK_THRESHOLD:
                b['open_ts'] = time.time()  # 记录打开时刻，开始冷却
                _breaker_event('open')
        return
    # 半开态（fails >= 阈值且冷却已过，正被放行探测）
    if success:
        b['probes'] += 1
        b['probe_ok'] += 1
        if b['probe_ok'] >= ONLINE_BREAK_HALF_OPEN_LIMIT:
            b.update({'fails': 0, 'probes': 0, 'probe_ok': 0})
            _breaker_event('closed')
    else:
        b.update({'fails': ONLINE_BREAK_THRESHOLD, 'probes': 0, 'probe_ok': 0,
                  'open_ts': time.time()})
        _breaker_event('reopen')


def _online_pacing():
    """同接/详情请求节流：随机 0.2~0.5s 抖动，降低被风控模式识别定位的概率。"""
    time.sleep(random.uniform(0.2, 0.5))


def parse_online_count(raw):
    """解析 B 站同接 total 字段（展示字符串）为 (数值, 精度标记, 原始字符串)。

    B 站 /x/player/online/total 的 total 是前端展示字符串而非精确数字：
    - <1000：精确数字，如 "952" → (952, 'exact', '952')
    - 1000~9999：千位向下取整 + 加号，如 "1000+"（真实值 1000~1999）
      → (1000, 'k_plus', '1000+')
    - >=1万：万为单位一位小数（B 站 toFixed(1) 四舍五入），如 "1.1万"
      （真实值约 11000±500）→ (11000, 'w', '1.1万')
    无法解析（B 站改格式/异常值）→ (None, None, None)，调用方按"未知"处理：
    请求本身已成功，不应计入熔断失败（格式问题非风控信号），值缺失由
    评分层 L1 批内中性化兜底。
    """
    if raw is None:
        return None, None, None
    s = str(raw).strip()
    if not s:
        return None, None, None
    # 万为单位（容忍 + 后缀防御）："1.1万" / "1万"
    m = re.match(r'^(\d+(?:\.\d+)?)万\+?$', s)
    if m:
        value = int(round(float(m.group(1)) * 10000))
        return value, 'w', s
    # 千位向下取整 +："1000+" / "2000+"
    m = re.match(r'^(\d+)\+$', s)
    if m:
        return int(m.group(1)), 'k_plus', s
    # 纯数字（精确）："952"
    m = re.match(r'^(\d+)$', s)
    if m:
        return int(m.group(1)), 'exact', s
    return None, None, None


def fetch_online_count(bvid, cid=None):
    """获取视频当前同时在线观看人数（同接）。

    A2 语义：value 返回 None = 未知（抓取失败/无cid）；返回 0 = 实测为零。
    调用方不得把失败当 0 处理（0 会拉低同接分析，None 表示无信息）。
    返回 (value, precision, display) 三元组：
    - value：解析后的数值（评分/平滑/落库用），未知为 None
    - precision：'exact' | 'k_plus' | 'w'（精度标记，供前端展示）
    - display：API 原始展示字符串（如 "1000+" / "1.1万"），前端如实展示
    L3：请求结果自动计入熔断器，-412 风控立即熔断。
    """
    if not cid:
        detail = fetch_video_detail(bvid)
        if not detail:
            return None, None, None
        cid = detail.get('cid')
    if not cid:
        return None, None, None

    url = 'https://api.bilibili.com/x/player/online/total'
    try:
        data = safe_get(url, params={'bvid': bvid, 'cid': cid}, return_error_code=True)
        if data is None:
            # 网络失败/重试耗尽（非 -412）：按普通失败累计（L3 阈值熔断）
            _online_breaker_record(False)
            return None, None, None
        if data.get('code') == 0:
            # B 站 total 是展示字符串：<1000 精确数字，"1000+" 千位取整、"1.1万" 万位取整。
            # 统一走 parse_online_count 解析为数值+精度标记。
            # 修复前 re.match(r'^(\d+)') 只取开头数字："1000+" 解析成 1000 尚可，
            # "1.1万" 会被解析成 1（严重低估 1.1 万倍）；"1.5万" → 1 同理。
            # 解析失败（B 站改格式）返回 (None,...)：请求已成功不计熔断失败——
            # 一批格式异常走评分 L1 整轮中性化兜底，不会误触发风控熔断。
            value, precision, display = parse_online_count((data.get('data') or {}).get('total'))
            _online_breaker_record(True)
            return value, precision, display
        # 仅 -412 会走到这里（safe_get return_error_code 只对 -412 返回 code 字典）
        _online_breaker_record(False, blocked=True)
        print('  [同接] 检测到 -412 风控，触发熔断')
    except Exception as e:
        _online_breaker_record(False)
        print(f'  获取同接失败 {bvid}: {e}')
    return None, None, None


def fetch_comments(aid, ps=20, sort=2):
    url = 'https://api.bilibili.com/x/v2/reply/main'
    data = safe_get(url, params={'oid': aid, 'type': 1, 'ps': ps, 'sort': sort})
    if data and data.get('data') and data['data'].get('replies'):
        return data['data']['replies']
    return []

# ────────────── parse 共享 helper ──────────────
# parse_region_rank_item(搜索/排行榜 API)与 parse_video_item(popular feed/ranking v2)
# 产出同构 dict,但时长/时间/分区/估算逻辑各自实现。提取以下 helper 统一字段映射,
# 由 test_bilibili_parse.py 保证 100% 等价。

def _strip_em(text):
    """去除搜索 API 返回的 <em class="keyword"> 高亮标签，并反转义 HTML 实体（&amp; → &、&quot; → " 等）。"""
    if not text:
        return ''
    return html.unescape(text.replace('<em class="keyword">', '').replace('</em>', ''))


def _parse_duration(raw):
    """时长解析为秒。

    支持格式:
    - 整数(已为秒,popular feed): 240
    - 字符串 'm:ss'(搜索/排行榜 API): '3:45' → 225
    - 字符串 'h:m:ss': '1:02:03' → 3723
    - 空/无效: 0
    """
    if not raw:
        return 0
    if isinstance(raw, int):
        return raw
    s = str(raw)
    if ':' not in s:
        try:
            return int(s)
        except (ValueError, TypeError):
            return 0
    parts = s.split(':')
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, TypeError):
        return 0
    return 0


def _parse_pubdate(pubdate, create_time=''):
    """发布时间解析为 Unix 时间戳。

    优先级:
    1. pubdate 为有效 Unix 时间戳(>1000000000,即 2001 年后)直接使用(搜索/popular API)
    2. create_time 字符串('YYYY-MM-DD HH:MM'[:SS],排行榜 API)按北京时间 CN_TZ 解析
    3. 否则返回 0

    显式按 UTC+8 解析,不依赖系统本地时区——naive datetime.timestamp() 会按系统
    本地时区解释,分发到其他时区会出错。
    """
    if pubdate and isinstance(pubdate, int) and pubdate > 1000000000:
        return pubdate
    if create_time:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                dt = datetime.strptime(create_time, fmt).replace(tzinfo=CN_TZ)
                return int(dt.timestamp())
            except ValueError:
                continue
    return 0


def _to_int_tid(raw):
    """typeid/tid 原始值转 int。

    搜索 API 的 typeid 是字符串(如 '22'),需统一转 int 才能与 KICHU_TIDS 等
    整数集合正确比较,否则 '22' not in {22, 26, ...} 永远为 True 会误杀全部结果。
    """
    try:
        return int(raw) if raw else 0
    except (ValueError, TypeError):
        return 0


def _build_video_dict(fields, pts=None, stats_estimated=False):
    """统一构建视频 dict。

    fields 为各 API 已提取的归一化字段(bvid/aid/title/description/cover/author/mid/
    tid/tname/views/danmaku/comments/likes/coins/favorites/shares/tags/duration/pub_date),
    本函数负责:截断 description 至 300、计算 trend_score/trend_label、
    拼 url,并按需追加 pts(排行榜)/_stats_estimated(估算标记)。
    """
    result = dict(fields)
    result['metrics_source'] = 'estimated' if stats_estimated else fields.get('metrics_source', 'legacy_unknown')
    result['description'] = (fields.get('description') or '')[:300]
    result['url'] = f'https://www.bilibili.com/video/{fields["bvid"]}'
    trend_score = calc_trend_score(
        fields['views'], fields['likes'], fields['coins'], fields['favorites'],
        fields['shares'], fields['comments'], fields['danmaku'], fields['pub_date'])
    result['trend_score'] = trend_score
    result['trend_label'] = get_trend_label(trend_score)
    if pts is not None:
        result['pts'] = pts
    if stats_estimated:
        result['_stats_estimated'] = True
    return result


# ────────────── parse 函数 ──────────────

def parse_region_rank_item(video, tid=None):
    # tid 参数保留向后兼容(外部调用仍传 tid=22 等),但不再用作 fallback——
    # 分区未知视频应让调用方过滤丢弃,而非伪装成目标分区(曾导致野生动物视频混入鬼畜榜)。
    title = _strip_em(video.get('title', ''))
    bvid = video.get('bvid', '')
    desc = _strip_em(video.get('description', '') or '')
    play = video.get('play', 0)
    # 排行榜/搜索 API 不返回 likes/shares,按 5%/1% 估算通过初筛,
    # 候选过滤后会通过 web-interface/view 补抓真实数据(见 run_all_crawlers)
    likes_est = int(play * 0.05)
    shares_est = int(play * 0.01)

    # 优先用视频真实分区:typeid(搜索 API) > tid(popular feed),均转 int。
    # 不用传入 tid 作 fallback:typeid/tid 都缺失时设 0,让调用方最终过滤丢弃。
    real_tid = _to_int_tid(video.get('typeid') or video.get('tid') or 0)

    # tags:搜索 API 是逗号字符串;排行榜 API 无 tag 字段,需单独请求
    tags = []
    search_tag = video.get('tag', '')
    if search_tag and isinstance(search_tag, str):
        tags = [t.strip() for t in search_tag.split(',') if t.strip()]
    elif bvid:
        tags = fetch_video_tags(bvid)
        time.sleep(0.3)

    fields = {
        'bvid': bvid,
        'aid': video.get('aid', ''),
        'title': title,
        'description': desc,
        'cover': _normalize_url(video.get('pic', '')),
        'author': video.get('author', ''),
        'author_avatar': _normalize_url(video.get('upic', '') or ''),
        'mid': video.get('mid', 0),
        'tid': real_tid,
        'tname': video.get('typename', ''),
        'views': play,
        'danmaku': video.get('video_review', 0),
        'comments': video.get('review', 0),
        'likes': likes_est,
        'coins': video.get('coins', 0),
        'favorites': video.get('favorites', 0),
        'shares': shares_est,
        'tags': tags,
        'duration': _parse_duration(video.get('duration', '0:00')),
        'pub_date': _parse_pubdate(video.get('pubdate', 0), video.get('create', '')),
    }
    return _build_video_dict(fields, pts=video.get('pts', 0), stats_estimated=True)

def parse_video_item(video, with_tags=False):
    stat = video.get('stat', {}) or {}
    owner = video.get('owner', {}) or {}
    title = _strip_em(video.get('title', ''))
    bvid = video.get('bvid', '')
    desc = video.get('description', '') or video.get('desc', '') or ''

    # tid 字段优先(popular feed),回退 typeid(搜索 API),统一转 int
    tid = _to_int_tid(video.get('tid', 0) or video.get('typeid', 0))

    # tags:with_tags 时单独请求;否则用 tag 逗号字符串
    tags = []
    if with_tags and bvid:
        tags = fetch_video_tags(bvid)
        time.sleep(0.3)
    elif video.get('tag'):
        tags = video.get('tag', '').split(',')

    fields = {
        'bvid': bvid,
        'aid': video.get('aid', ''),
        'title': title,
        'description': desc,
        'cover': _normalize_url(video.get('pic', '') or video.get('cover', '')),
        'author': owner.get('name', '') or video.get('author', ''),
        'author_avatar': _normalize_url(owner.get('face', '') or video.get('upic', '') or ''),
        'mid': owner.get('mid', 0) if owner else 0,
        'tid': tid,
        'tname': video.get('tname', ''),
        'views': stat.get('view', 0),
        'danmaku': stat.get('danmaku', 0),
        'comments': stat.get('reply', 0),
        'likes': stat.get('like', 0),
        'coins': stat.get('coin', 0),
        'favorites': stat.get('favorite', 0),
        'shares': stat.get('share', 0),
        'tags': tags,
        'duration': _parse_duration(video.get('duration', 0)),
        'pub_date': _parse_pubdate(video.get('pubdate', 0) or video.get('senddate', 0)),
    }
    if all(stat.get(key) is not None for key in ('view', 'like', 'coin', 'favorite', 'share', 'reply', 'danmaku')):
        fields.update(metrics_source='bilibili_stat', observed_at=int(time.time()))
    return _build_video_dict(fields)

def fetch_popular_multi(pages=3, ps=50):
    all_videos = []
    seen = set()
    for pn in range(1, pages + 1):
        videos = fetch_popular(ps=ps, pn=pn)
        for v in videos:
            bvid = v.get('bvid', '')
            if bvid and bvid not in seen:
                seen.add(bvid)
                all_videos.append(v)
        time.sleep(0.8)
    return all_videos

def _collect_by_category(name, tid, tname_keywords, search_queries, popular_pages,
                         fresh_days=None, max_results=30, kichu_filter=False,
                         target_tids=None):
    """通用分区视频采集:popular feed + 搜索 + ranking 三源。

    三源去重后按 views 降序,取 max_results 条。
    kichu_filter=True 启用鬼畜区专属逻辑:
      - popular feed 按 tid ∈ KICHU_TIDS 集合过滤(多分区),with_tags=True
      - 搜索结果 typeid int 转换 + KICHU_TIDS 过滤 + 一年老视频过滤
      - ranking 用全站榜 v2(fetch_ranking_v2)+ tid 集合过滤
      - 返回前防御性过滤(tid ∉ KICHU_TIDS 丢弃)
    kichu_filter=False(单分区,music/funny 用):
      - popular feed 按 tid == tid 或 tname 含关键词,with_tags=False
      - 搜索结果直接 parse(无 typeid 二次过滤)
      - ranking 用旧 ranking/region API(fetch_ranking)
      - fresh_days 时效过滤(仅保留 N 天内视频)
      - 传入 target_tids 时,三源均按该分区集合二次过滤(防搜索 API 跨分区混入)
    """
    print(f'正在抓取{name}热门视频...')
    collected = []
    seen_bvids = set()

    # ── 源1: popular feed ──
    all_popular = fetch_popular_multi(pages=popular_pages, ps=50)
    for video in all_popular:
        if kichu_filter:
            # 鬼畜区:严格按 tid 集合过滤(tname 关键词匹配可能误收其他分区)
            if video.get('tid', 0) not in KICHU_TIDS:
                continue
        else:
            # 单分区:tid 匹配或 tname 含关键词;若指定 target_tids 则按集合过滤
            vtid = video.get('tid', 0)
            vtname = video.get('tname', '')
            if target_tids:
                if vtid not in target_tids:
                    continue
            elif vtid != tid and not (vtname and any(kw in vtname for kw in tname_keywords)):
                continue
        bvid = video.get('bvid', '')
        if bvid and bvid not in seen_bvids:
            seen_bvids.add(bvid)
            collected.append(parse_video_item(video, with_tags=kichu_filter))

    # ── 源2: 关键词搜索(每个关键词搜对应子分区) ──
    search_pages = 2 if kichu_filter else 1
    for kw, search_tid in search_queries:
        try:
            results = fetch_search_videos_by_keyword(kw, tid=search_tid, pages=search_pages, ps=20)
            added = 0
            typeid_filtered = 0
            year_filtered = 0
            for video in results:
                bvid = video.get('bvid', '')
                if kichu_filter:
                    # 搜索API的tid参数过滤不严格(关键词命中即可,会返回其他分区视频),
                    # 按视频真实分区(typeid)二次过滤。注:搜索API返回的typeid是字符串(如'22'),
                    # 需转int才能与KICHU_TIDS整数集合比较,否则 '22' not in {22,...} 永远为True。
                    # typeid 为空的视频无法确认分区,直接丢弃(宁可错杀不漏)。
                    real_tid_raw = video.get('typeid') or video.get('tid') or 0
                    try:
                        real_tid = int(real_tid_raw) if real_tid_raw else 0
                    except (ValueError, TypeError):
                        real_tid = 0
                    if not real_tid or real_tid not in KICHU_TIDS:
                        typeid_filtered += 1
                        continue
                    if bvid and bvid not in seen_bvids:
                        seen_bvids.add(bvid)
                        parsed = parse_region_rank_item(video, tid=real_tid)
                        # 过滤掉一年以上的老视频
                        if parsed['pub_date'] > 0:
                            one_year_ago = int(time.time()) - 365 * 86400
                            if parsed['pub_date'] < one_year_ago:
                                year_filtered += 1
                                continue
                        collected.append(parsed)
                        added += 1
                else:
                    # 单分区(非鬼畜):搜索API的tid参数同样不严格(关键词命中即可),
                    # 传入 target_tids 时按视频真实 typeid 二次过滤,防跨分区(如动物圈)混入
                    if target_tids:
                        real_tid_raw = video.get('typeid') or video.get('tid') or 0
                        try:
                            real_tid = int(real_tid_raw) if real_tid_raw else 0
                        except (ValueError, TypeError):
                            real_tid = 0
                        if not real_tid or real_tid not in target_tids:
                            typeid_filtered += 1
                            continue
                    if bvid and bvid not in seen_bvids:
                        seen_bvids.add(bvid)
                        collected.append(parse_region_rank_item(video, tid=real_tid if target_tids else search_tid))
                        added += 1
            if kichu_filter:
                print(f'  搜索"{kw}"(tid={search_tid}): 返回{len(results)}条, typeid过滤{typeid_filtered}, 年份过滤{year_filtered}, 新增{added}')
            else:
                print(f'  搜索"{kw}": 返回{len(results)}条, typeid过滤{typeid_filtered}, 新增{added}')
            time.sleep(1 if kichu_filter else 0.8)  # 搜索API限流间隔
        except Exception as e:
            print(f'  搜索关键词"{kw}"失败: {e}')

    # ── 源3: ranking ──
    try:
        if kichu_filter:
            # 鬼畜区:全站榜 v2(ranking/region 子分区榜已废弃返回陈旧数据)
            # 从 ranking/v2?rid=0 全站榜过滤 tid ∈ KICHU_TIDS 的视频
            ranking_all = fetch_ranking_v2(rid=0)
            added = 0
            for video in ranking_all:
                if video.get('tid', 0) not in KICHU_TIDS:
                    continue
                bvid = video.get('bvid', '')
                if bvid and bvid not in seen_bvids:
                    seen_bvids.add(bvid)
                    collected.append(parse_video_item(video, with_tags=False))
                    added += 1
            print(f'  全站榜过滤鬼畜区: +{added} 条（全站榜共 {len(ranking_all)}）')
        else:
            # 单分区:旧 ranking/region API
            ranking = fetch_ranking(tid=tid, day=3)
            for video in ranking:
                bvid = video.get('bvid', '')
                if bvid and bvid not in seen_bvids:
                    seen_bvids.add(bvid)
                    collected.append(parse_region_rank_item(video, tid=tid))
            print(f'  排行榜: +{len(ranking)} 条')
    except Exception as e:
        print(f'  排行榜抓取失败: {e}')

    # ── 时效过滤(单分区:music/funny 仅保留 fresh_days 天内) ──
    if fresh_days and not kichu_filter:
        now_ts = time.time()
        before = len(collected)
        collected = [v for v in collected
                     if v.get('pub_date', 0) > 0 and (now_ts - v['pub_date']) <= fresh_days * 86400]
        print(f'{name}抓到 {before} 条，时效过滤后 {len(collected)} 条（{fresh_days}天内）')
    else:
        print(f'{name}抓到 {len(collected)} 条视频（popular + 搜索 + 排行榜）')

    # 按 views 降序
    collected.sort(key=lambda x: x['views'], reverse=True)

    # ── 防御性过滤(鬼畜区:不管来自哪个源,tid ∉ KICHU_TIDS 一律丢弃;非鬼畜指定了 target_tids 同理) ──
    filter_tids = KICHU_TIDS if kichu_filter else (target_tids or None)
    if filter_tids:
        before = len(collected)
        collected = [v for v in collected if v.get('tid') in filter_tids]
        if len(collected) < before:
            print(f'  防御性过滤: 丢弃 {before - len(collected)} 条非目标分区视频')

    return collected[:max_results]


def get_kichu_videos():
    """鬼畜区热门视频:4 子分区(22/26/126/216)三源采集 + 四层防御过滤。"""
    return _collect_by_category(
        name='鬼畜区', tid=22, tname_keywords=[],  # kichu_filter=True 时按 KICHU_TIDS 集合过滤,tname 不用
        search_queries=[
            ('鬼畜', 22),       # 鬼畜调教
            ('音MAD', 26),      # 音MAD
            ('人力', 126),      # 人力VOCALOID
            ('鬼畜', 216),      # 鬼畜剧场
        ],
        popular_pages=15,       # 鬼畜区扩大 popular feed 覆盖
        kichu_filter=True,
        max_results=30,
    )

def get_music_videos():
    """音乐区热门视频:单分区三源采集 + 60 天时效过滤(素材发掘窗口)。

    target_tids=MUSIC_TIDS：搜索源按真实 typeid 二次过滤，防止关键词命中
    (洗脑/魔性/神曲…)时跨分区混入动物圈/鬼畜等其他分区视频。
    """
    return _collect_by_category(
        name='音乐区', tid=MUSIC_TID,
        tname_keywords=['音乐', '演奏', '翻唱', 'MV'],
        search_queries=[(kw, MUSIC_TID) for kw in
                        ['洗脑', '翻唱', 'BGM', '魔性', '空耳', '神曲', 'RAP']],
        popular_pages=3,
        fresh_days=60,
        max_results=30,
        target_tids=MUSIC_TIDS,
    )

def get_funny_videos():
    """搞笑区热门视频:单分区三源采集 + 60 天时效过滤(素材发掘窗口)。

    target_tids=FUNNY_TIDS：搜索源按真实 typeid 二次过滤，防跨分区混入。
    """
    return _collect_by_category(
        name='搞笑区', tid=FUNNY_TID,
        tname_keywords=['搞笑'],
        search_queries=[(kw, FUNNY_TID) for kw in
                        ['名场面', '洗脑', '鬼畜', '魔性', '整活', '空耳', '恶搞']],
        popular_pages=3,
        fresh_days=60,
        max_results=30,
        target_tids=FUNNY_TIDS,
    )

def get_popular_videos():
    print('正在抓取全站热门视频...')
    all_popular = fetch_popular_multi(pages=4)
    results = []
    for video in all_popular:
        parsed = parse_video_item(video, with_tags=False)
        # 分区硬约束：全站热门覆盖全站各分区，喵星人(218)/野生动物(221)/搞笑(138)等
        # 非鬼畜视频标题碰巧含高权重词时会误伤，必须按鬼畜分区过滤
        if parsed['tid'] not in KICHU_TIDS:
            continue
        results.append(parsed)
    print(f'全站热门中筛选出 {len(results)} 条鬼畜潜力视频')
    return results[:50]

# ==================== 共享关键词过滤 ====================
# 词表真源：PostgreSQL 中的管理员覆盖；未覆盖时使用随版本发布的默认词表。
# 结构：categories=精确匹配停用词表(分类)、ad_keywords=子串匹配广告品牌、
#       activity_keywords=子串匹配活动词、allowed_two_char=二字梗白名单。
# 内置兜底会在下方用完整的发布词表替换。
_FALLBACK_TAG_FILTERS = {
    'categories': {
        # —— 鬼畜平台/分区相关 ——
        '鬼畜平台/分区': [
            '鬼畜', '鬼畜调教', '鬼畜剧场', '鬼畜明星', '鬼畜UP',
            '鬼畜星探企划', '鬼畜星探计划', '鬼畜星探', '星探企划', '星探计划',
            '音MAD', '人力VOCALOID', '人力vocaloid', 'VOCALOID',
            '鬼畜配音', '鬼畜剪辑', '鬼畜素材', '鬼畜区',
        ],
        # —— 通用分区 / 大类 ——
        '通用分区/大类': [
            '搞笑', '搞笑视频', '沙雕', '沙雕日常', '生活记录',
            '音乐', '翻唱', '演奏', 'MV', '原创音乐', '音乐现场',
            '娱乐', '综艺', '明星',
            '知识', '科技', '数码', '生活', '美食', '动物圈',
            '舞蹈', '游戏', '动画', '番剧', '国创', '影视', '纪录片',
            '电影', '电视剧', '时尚', '资讯',
            '视频', '高清', '完整版', '合集', '剪辑', '制作', '教程',
            '原创', '英语', '数学', '物理', '化学', '语文',
            '科幻', '微电影', '脑洞', 'AIGC', 'AI剧情大片',
        ],
        # —— 泛化评价词（太通用，无区分度） ——
        '泛化评价词': [
            '名场面', '洗脑', '魔性', '空耳', '调音', 'RAP', '踩点', '混剪',
            '全明星', '经典语录', '高能', '前方高能',
            '抽象', '离谱', '可爱', '牛逼', '牛批', '666', 'yyds', '绝绝子',
            '高燃', '燃', '泪目', '治愈', '温馨', '爆笑', '好活',
            '整活', '绝活', '神作', '神级', '顶级', '炸裂',
            '恶搞', '玩梗',
        ],
        # —— 年份 / 时效 ——
        '年份/时效': ['2025', '2026', '2024', '2023', '2022', '2021', '新番', '年度'],
        # —— B站平台词 ——
        'B站平台词': [
            '哔哩哔哩', 'bilibili', 'B站', 'b站',
            'UP主', 'up主', 'UP', 'up', '投稿', '自制', '转载',
            '点赞', '投币', '收藏', '转发', '关注', '三连',
            '必剪', '必剪创作',
        ],
        # —— B站官方活动 ——
        'B站官方活动': [
            'bilibili新星计划', '新星计划', '创作激励',
            '鬼畜星探企划', '鬼畜星探计划', '鬼畜星探',
            'AI全民制作人', '致予新世界', 'updream',
        ],
        # —— 泛化日常/生活词 ——
        '泛化日常/生活词': [
            '挑战', 'vlog', 'Vlog', 'VLOG', '日常',
            '开箱', '测评', '评测', '体验', '分享',
            '童年', '90后', '80后', '00后', '70后',
            '剧终', '结局', '开场', '开头', '结尾',
        ],
        # —— 游戏（太泛化） ——
        '游戏（太泛化）': [
            '游戏', '手游', '网游', '电竞',
            '原神', '王者荣耀', '英雄联盟', 'LOL',
            '和平精英', '吃鸡', '鸣潮', '战双', '明日方舟',
            '崩坏星穹铁道', '星穹铁道', '崩铁',
            '景元', '爻光', '饮月', '黄泉', '花火',
        ],
        # —— 广告 / 品牌 / 电商平台 ——
        '广告/品牌/电商平台': [
            '美团', '美团外卖', '饿了么', '饿了吗',
            '转转', '闲鱼', '爱回收', '爱回收严选', '严选', '网易严选',
            '京东', '淘宝', '拼多多', '天猫', '支付宝', '微信',
            '抖音', '快手', '小红书', '微博',
            '广告', '赞助', '恰饭', '推广', '合作', '品牌', '商单', '代言',
            '外卖', '快递', '购物', '电商', '二手',
            '骑手', '外卖员', '快递员',
        ],
        # —— 其他泛化/干扰 ——
        '其他泛化/干扰': [
            '艺术创想', '盗梦空间',
            '拼好歌', '诗歌剧',
            '大张伟', '尼尔叔叔',
            '内个', 'speed',
            '世界杯终局之战', '复仇者',
            '马林巴', '少女A',
            '智斗',
        ],
        # —— 更多常见广告品牌（补充） ——
        '更多常见广告品牌': [
            '瑞幸', '星巴克', '麦当劳', '肯德基', '必胜客',
            '奈雪', '喜茶', '茶百道', '蜜雪冰城', '古茗',
            '可口可乐', '百事可乐', '农夫山泉', '元气森林',
            '华为', '小米', 'OPPO', 'vivo', '一加', '荣耀', '三星', '苹果',
            '索尼', '联想', '戴尔', '华硕', '惠普', '微星',
            '英特尔', 'AMD', 'NVIDIA', '英伟达',
            '比亚迪', '特斯拉', '蔚来', '小鹏', '理想汽车',
            '滴滴', '哈啰', '曹操出行',
            '支付宝', '微信支付', '花呗', '借呗', '白条',
            '得物', '毒', '识货',
            'Keep', 'keep', '咕咚',
            '携程', '去哪儿', '飞猪', '同程',
            '链家', '贝壳', '自如',
            'Boss直聘', '猎聘', '智联招聘', '前程无忧',
            '新东方', '好未来', '作业帮', '猿辅导',
            '丁香医生', '好大夫', '微医',
            '途虎', '途虎养车', '天猫养车',
            '货拉拉', '快狗打车', '运满满',
            '贝壳找房', '安居客', '房天下',
            '什么值得买', '慢慢买', '比价',
        ],
        # —— 更多 B站活动 / 平台功能 ——
        '更多B站活动/平台功能': [
            '新星计划', '创作激励', '星火计划', '星火企划',
            'bilibili新星', '必剪创作',
            '充电', '发电', '电池', '充能',
            '直播', '直播间', '首播', '首秀',
        ],
        # —— 竞品/其他平台 ——
        '竞品/其他平台': [
            'ChiliChili', 'chilichili', '油管', 'YouTube', 'youtube',
            'TikTok', 'tiktok', '抖音', '快手', '小红书',
        ],
        # —— 短数字/字母干扰 ——
        '短数字/字母干扰': ['AI', 'ai', 'Ai'],
        # —— 泛化的人称/角色 ——
        '泛化的人称/角色': [
            '同学', '老师', '老板', '朋友', '家人',
            '男孩', '女孩', '男生', '女生', '男人', '女人',
        ],
    },
    # 广告品牌关键词（子串匹配，命中即过滤）
    'ad_keywords': [
        '外卖', '爱回收', '严选', '转转', '闲鱼',
        '美团', '饿了么', '京东', '淘宝', '拼多多', '天猫',
        '广告', '赞助', '恰饭', '推广', '商单', '代言',
        '品牌', '合作',
        '瑞幸', '星巴克', '麦当劳', '肯德基', '必胜客',
        '奈雪', '喜茶', '蜜雪冰城',
        '华为', '小米', 'OPPO', 'vivo', '荣耀', '三星', '苹果',
        '索尼', '联想', '戴尔', '华硕',
        '英特尔', 'AMD', 'NVIDIA', '英伟达',
        '比亚迪', '特斯拉', '蔚来', '小鹏', '理想',
        '滴滴', '哈啰',
        '得物', '识货',
        'Keep', 'keep',
        '携程', '去哪儿', '飞猪',
        '链家', '贝壳', '自如',
        'Boss直聘', '猎聘', '智联',
        '新东方', '作业帮', '猿辅导',
        '货拉拉',
        '途虎',
        '友望',
    ],
    # B站活动 / 平台活动关键词（子串匹配）
    'activity_keywords': [
        '企划', '计划', '活动', '大赛', '比赛', '评选',
        '星探', '星火',
        '第几期', '第X期',
        '第一期', '第二期', '第三期', '第四期', '第五期',
        '第六期', '第七期', '第八期', '第九期', '第十期',
        '新星', '创作激励', '充电',
    ],
    # 二字梗白名单：具有明确梗含义、区分度高的词放行
    'allowed_two_char': [
        '叮咚', '哈基', '阳光', '彩虹', '小白', '甲亢',
        '大狗', '小狗', '汪汪', '越狱',
        '杰哥', '阿伟', '坤坤', '彬彬',
    ],
}

_FALLBACK_TAG_FILTERS = {
    'categories': {key: list(values) for key, values in TAG_FILTERS['categories'].items()},
    'ad_keywords': list(TAG_FILTERS['ad_keywords']),
    'activity_keywords': list(TAG_FILTERS['activity_keywords']),
    'allowed_two_char': list(TAG_FILTERS['allowed_two_char']),
}


def load_tag_filters():
    """读取标签过滤词表配置，返回:
    {'categories': {分类: [词]}, 'ad_keywords': [...], 'activity_keywords': [...], 'allowed_two_char': [...]}
    未配置 PostgreSQL 覆盖值时降级为内置兜底。
    """
    from storage.runtime_settings import load_runtime_setting
    fallback = {
        'categories': {k: list(v) for k, v in _FALLBACK_TAG_FILTERS['categories'].items()},
        'ad_keywords': list(_FALLBACK_TAG_FILTERS['ad_keywords']),
        'activity_keywords': list(_FALLBACK_TAG_FILTERS['activity_keywords']),
        'allowed_two_char': list(_FALLBACK_TAG_FILTERS['allowed_two_char']),
    }
    data = load_runtime_setting('tag_filters', fallback)
    categories = data.get('categories') if isinstance(data, dict) else None
    ad = data.get('ad_keywords') if isinstance(data, dict) else None
    act = data.get('activity_keywords') if isinstance(data, dict) else None
    two = data.get('allowed_two_char') if isinstance(data, dict) else None
    if not isinstance(categories, dict) or not all(isinstance(value, list) for value in (ad, act, two)):
        return fallback
    cleaned_categories = {
        key: [str(word) for word in values if isinstance(word, str) and word.strip()]
        for key, values in categories.items() if isinstance(values, list)
    }
    return {
        'categories': {key: values for key, values in cleaned_categories.items() if values},
        'ad_keywords': [str(word) for word in ad if isinstance(word, str) and word.strip()],
        'activity_keywords': [str(word) for word in act if isinstance(word, str) and word.strip()],
        'allowed_two_char': [str(word) for word in two if isinstance(word, str) and word.strip()],
    }


def save_tag_filters(filters):
    """保存标签过滤词表到 PostgreSQL。"""
    from storage.runtime_settings import save_runtime_setting
    save_runtime_setting('tag_filters', {
        'categories': {key: list(values) for key, values in filters['categories'].items()},
        'ad_keywords': list(filters['ad_keywords']),
        'activity_keywords': list(filters['activity_keywords']),
        'allowed_two_char': list(filters['allowed_two_char']),
    })
    _invalidate_tag_filters()


# is_useless_tag 高频调用。本进程保存时立即失效；其他 API/Worker 进程
# 通过 PostgreSQL revision 在有限窗口内发现更新。
_TAG_FILTERS_CACHE = None
_TAG_FILTERS_CACHE_VERSION = None
_TAG_FILTERS_CACHE_CHECKED_AT = None


def _get_tag_filters():
    """读取预处理后的过滤词表（带模块级缓存）。"""
    from storage.runtime_settings import runtime_setting_version

    global _TAG_FILTERS_CACHE, _TAG_FILTERS_CACHE_VERSION
    global _TAG_FILTERS_CACHE_CHECKED_AT
    now = _monotonic()
    refresh_due = (
        _TAG_FILTERS_CACHE_CHECKED_AT is None
        or now - _TAG_FILTERS_CACHE_CHECKED_AT >= RUNTIME_SETTING_CACHE_REFRESH_SECONDS
    )
    version = _TAG_FILTERS_CACHE_VERSION
    if _TAG_FILTERS_CACHE is None or refresh_due:
        version = runtime_setting_version('tag_filters')
        _TAG_FILTERS_CACHE_CHECKED_AT = now
    if _TAG_FILTERS_CACHE is None or version != _TAG_FILTERS_CACHE_VERSION:
        raw = load_tag_filters()
        stop_set = set()
        for words in raw['categories'].values():
            stop_set.update(str(w).lower() for w in words)
        _TAG_FILTERS_CACHE = {
            'stop_set': stop_set,
            'ad_keywords': raw['ad_keywords'],
            'activity_keywords': raw['activity_keywords'],
            'allowed_two_char': set(raw['allowed_two_char']),
        }
        _TAG_FILTERS_CACHE_VERSION = version
    return _TAG_FILTERS_CACHE


def _invalidate_tag_filters():
    """配置保存后失效缓存，下次 is_useless_tag 调用重新加载。"""
    global _TAG_FILTERS_CACHE, _TAG_FILTERS_CACHE_VERSION
    global _TAG_FILTERS_CACHE_CHECKED_AT
    _TAG_FILTERS_CACHE = None
    _TAG_FILTERS_CACHE_VERSION = None
    _TAG_FILTERS_CACHE_CHECKED_AT = None


def explain_tag_rule(kw):
    """解释标签/标题候选词为何保留或过滤，作为标签场景的唯一判定入口。"""
    from utils.stopwords import STOPWORDS

    if not kw or len(kw) < 2 or len(kw) > 10:
        return {'accepted': False, 'layer': 'format', 'category': '长度需为 2–10 个字符', 'match': 'format'}

    kw_lower = kw.lower().strip()
    filters = _get_tag_filters()

    # 场景白名单优先于公共/分类停用词，解决“阳光”等词同时存在于通用词典时的误伤。
    if len(kw) == 2 and kw in filters['allowed_two_char']:
        return {'accepted': True, 'layer': 'tag_allow', 'category': '二字词放行名单', 'match': 'exact'}

    # 1. 精确匹配停用词表（分类展开，大小写不敏感）
    if kw_lower in filters['stop_set']:
        return {'accepted': False, 'layer': 'tag', 'category': '标签分类停用词', 'match': 'exact'}

    # 1.5 公共虚词：三字以上的“为什么/就是说”等不会再绕过二字规则进入榜单。
    if kw_lower in {w.lower() for w in STOPWORDS}:
        return {'accepted': False, 'layer': 'common', 'category': '公共停用词', 'match': 'exact'}

    # 2. 子串匹配广告品牌
    for ad in filters['ad_keywords']:
        if ad.lower() in kw_lower:
            return {'accepted': False, 'layer': 'global_noise', 'category': '广告/品牌',
                    'match': 'substring', 'matched': ad}

    # 3. 子串匹配活动关键词
    for act in filters['activity_keywords']:
        if act.lower() in kw_lower:
            return {'accepted': False, 'layer': 'global_noise', 'category': '活动词',
                    'match': 'substring', 'matched': act}

    # 4. 纯英文/数字，长度 ≤ 5（如 "AI", "2024", "speed"）
    if re.search(r'^[a-zA-Z0-9\s]+$', kw) and len(kw) <= 5:
        return {'accepted': False, 'layer': 'format', 'category': '短英文/数字', 'match': 'format'}

    # 5. 以"第"开头的期号格式
    if re.search(r'^第.+[期话季集部]$', kw):
        return {'accepted': False, 'layer': 'format', 'category': '期号格式', 'match': 'regex'}

    # 6. 包含四位数年份
    if re.search(r'\d{4}', kw):
        return {'accepted': False, 'layer': 'format', 'category': '年份', 'match': 'regex'}

    # 7. 中文数字 + 期/话/季/集
    if re.search(r'第[一二三四五六七八九十百千]+[期话季集]', kw):
        return {'accepted': False, 'layer': 'format', 'category': '期号格式', 'match': 'regex'}

    # 8. 包含活动/比赛相关词
    if re.search(r'企划|计划|大赛|活动|评选|比赛|招募|征集', kw):
        return {'accepted': False, 'layer': 'global_noise', 'category': '活动词', 'match': 'regex'}

    # 9. 二字模糊词进一步收紧 — 只有明确是梗/素材的词才放行（白名单可配置）
    if len(kw) == 2:
        if kw not in filters['allowed_two_char']:
            return {'accepted': False, 'layer': 'tag', 'category': '二字词未在放行名单', 'match': 'length'}

    # 10. 明确包含广告/赞助/推广字样
    if re.search(r'广告|赞助|恰饭|推广|商单|代言', kw):
        return {'accepted': False, 'layer': 'global_noise', 'category': '广告表达', 'match': 'regex'}

    # 11. "大/小/老/新…哥/姐" 模式（人称/角色泛称）
    if re.search(r'^(大|小|老|新|旧|真|假|好|坏|强|弱|牛|菜|神|鬼|魔).{0,3}(哥|姐|叔|姨|弟|妹|人)$', kw):
        return {'accepted': False, 'layer': 'tag', 'category': '泛化人称', 'match': 'regex'}

    return {'accepted': True, 'layer': 'none', 'category': '未命中过滤规则', 'match': None}


def is_useless_tag(kw):
    """兼容旧调用；实际判定统一由 ``explain_tag_rule`` 完成。"""
    return not explain_tag_rule(kw)['accepted']

# ==================== 以上为共享关键词过滤 ====================

def get_hot_memes(kichu_videos, music_videos, funny_videos, popular_videos):
    print('正在提取热梗...')
    all_videos = kichu_videos + music_videos + funny_videos + popular_videos
    meme_dict = {}

    # 停用词表来自 PostgreSQL 可变覆盖；未覆盖时使用随版本发布的只读默认词表。
    # 种子热梗词豁免：显式声明要收录的梗优先级最高，即使被停用词表误伤也强制保留
    # （与 get_meme_materials 的 seed_words 语义一致，避免两边配置行为打架）。
    stopwords = set()
    for words in load_meme_stopwords().values():
        stopwords.update(words)
    seed_words = set(load_meme_seed_words())

    for video in all_videos:
        title = video['title']
        tags = video.get('tags', [])
        extracted = extract_keywords_from_title(title)

        all_keywords = list(set(extracted + tags))

        for kw in all_keywords:
            if is_useless_tag(kw):
                continue
            # 命中梗素材库停用词表 → 剔除（种子热梗词豁免）
            if kw in stopwords and kw not in seed_words:
                continue

            if kw not in meme_dict:
                meme_dict[kw] = {
                    'keyword': kw,
                    'related_videos': [],
                    'video_count': 0,
                    'total_views': 0,
                    'total_engagement': 0,
                    'trend_avg_score': 0,
                }

            entry = meme_dict[kw]
            entry['video_count'] += 1
            entry['total_views'] += video['views']
            entry['total_engagement'] += video['likes'] + video['coins'] + video['favorites'] + video['shares']
            entry['trend_avg_score'] += video['trend_score']

            if len(entry['related_videos']) < 5:
                entry['related_videos'].append({
                    'title': video['title'],
                    'bvid': video['bvid'],
                    'author': video['author'],
                    'views': video['views'],
                })

    results = []
    for kw, entry in meme_dict.items():
        # 热梗门槛：至少 1 个视频且聚合总播放量达标（阈值 config.HOT_MEME_VIEWS_MIN 可调）
        if entry['video_count'] >= 1 and entry['total_views'] > HOT_MEME_VIEWS_MIN:
            entry['trend_score'] = round(entry['trend_avg_score'] / entry['video_count'], 1)
            entry['trend_label'] = get_trend_label(entry['trend_score'])
            entry['heat'] = calc_meme_heat(entry['total_views'], entry['video_count'], entry['total_engagement'])
            del entry['trend_avg_score']
            results.append(entry)

    results.sort(key=lambda x: x['heat'], reverse=True)

    filtered = []
    seen_keywords = set()
    for r in results:
        kw = r['keyword'].lower()
        is_duplicate = False
        for seen in seen_keywords:
            if kw in seen or seen in kw:
                is_duplicate = True
                break
        if not is_duplicate:
            seen_keywords.add(kw)
            filtered.append(r)

    print(f'提取出 {len(filtered)} 个热梗')
    return filtered[:30]

def get_hot_songs(music_videos, kichu_videos):
    print('正在整理热门BGM...')
    # 只保留音乐区视频：搜索API会返回跨分区结果。白名单式按 MUSIC_TIDS 分区集合过滤
    # （比"仅排除鬼畜"更严格：任何非音乐分区——动物圈/生活等——都不应出现在BGM榜；
    #  分区集合统一来自 config.py，避免本地硬编码漂移）
    all_videos = [v for v in music_videos if v.get('tid') in MUSIC_TIDS]
    results = []
    seen = set()

    for video in all_videos:
        name = video['title']
        if name in seen:
            continue
        seen.add(name)

        results.append({
            'name': name,
            'author': video['author'],
            'cover': video['cover'],
            'bvid': video['bvid'],
            'url': video['url'],
            'plays': video['views'],
            'danmaku': video['danmaku'],
            'likes': video['likes'],
            'coins': video['coins'],
            'trend_score': video['trend_score'],
            'trend_label': video['trend_label'],
            'tags': video.get('tags', []),
            'duration': video['duration'],
        })

    results.sort(key=lambda x: x['plays'], reverse=True)
    print(f'整理出 {len(results)} 首热门BGM')
    return results[:25]

# 梗素材库已改为自动发现高频词（见 get_meme_materials），不再使用硬编码种子。
# 旧版 meme_material_seeds 已移除：硬编码种子需人工维护且易过时（8个种子5个失效），
# 改用 jieba 提取标题高频词 + 贪心去重聚合，自动跟上当前热点。

def get_meme_materials(all_videos, hot_songs, seed_words=None):
    """自动发现高频词并聚合为梗素材。

    设计：用 jieba 提取视频标题高频词，按词聚合相关视频，取 TOP 10 作为当前热门梗素材。
    优点：自动跟上热点，无需人工维护种子列表。
    去重：贪心策略——按频次降序处理，每个视频只分配给第一个匹配的高频词，避免重复展示。

    seed_words: 种子热梗词列表（如 哈基米/叮咚鸡/大狗叫）。候选池来自 4 路制作类词搜索，
    常驻热梗可能在候选池中频次不足 3 被过滤，这里按种子词直接统计（标题含该词即计入，
    不依赖 jieba 分词），确保热梗不丢。
    """
    print(f'正在整理梗素材库... (待分析视频 {len(all_videos)} 条, BGM {len(hot_songs)} 首, 种子词 {len(seed_words or [])} 个)')

    import jieba
    from collections import Counter
    from utils.stopwords import ensure_kichu_dict

    ensure_kichu_dict()  # 加载鬼畜梗自定义词典（哈基米等整词，幂等）

    # 停用词表来自 PostgreSQL 可变覆盖；未覆盖时使用随版本发布的只读默认词表。
    # 与种子不同，停用词表是"排除已知非梗词"，不需要随热点更新
    stopwords = set()
    for words in load_meme_stopwords().values():
        stopwords.update(words)

    # 种子热梗词：即使被停用词表误伤也强制保留（显式声明要收录的梗优先级最高）
    seed_words = [w for w in (seed_words or []) if w and w.strip()]

    # 1. 提取标题高频词，记录每个词命中的视频
    word_videos = {}  # word -> [video, ...]
    word_counter = Counter()
    for video in all_videos:
        title = video.get('title', '')
        seen_in_title = set()

        # 种子词：标题含该词即计入（不依赖 jieba 分词，词典缺词也不会被拆碎）
        for w in seed_words:
            if w in title:
                seen_in_title.add(w)

        words = jieba.cut(title, HMM=False)  # 精确模式，配合自定义词典整词匹配，避免 HMM 碎片
        for w in words:
            w = w.strip()
            if (len(w) >= 2 and
                    w not in stopwords and
                    not w.isdigit() and
                    not w.startswith('【')):
                seen_in_title.add(w)
        for w in seen_in_title:
            word_counter[w] += 1
            if w not in word_videos:
                word_videos[w] = []
            word_videos[w].append(video)

    # 2. 过滤高频词：普通词频次≥3 入选；种子热梗词放宽到 ≥1（主动声明要收录的梗，不因频次不足丢失）
    candidates = [(w, c) for w, c in word_counter.most_common()
                  if c >= 3 or w in seed_words]
    # 种子词优先分配：排到候选最前，保证其视频不被高频词（如"空耳"）先抢走
    seed_candidates = [c for c in candidates if c[0] in seed_words]
    auto_candidates = [c for c in candidates if c[0] not in seed_words]
    candidates = seed_candidates + auto_candidates
    print(f'  提取到 {len(candidates)} 个候选词(普通词≥3次, 种子词≥1次, 种子词优先)')

    # 3. 贪心去重：按频次降序处理，每个视频只分配给第一个匹配的高频词
    #    避免同一视频在多个梗下重复出现（如"哈基米"视频不会被重复归到"空耳"）
    assigned_bvids = set()
    results = []
    for word, cnt in candidates:
        related_videos = [v for v in word_videos[word]
                          if v.get('bvid') not in assigned_bvids]
        # 展示下限：普通词需去重后≥2条；种子词放宽到≥1条（显式声明要收录的热梗）
        min_videos = 1 if word in seed_words else 2
        if len(related_videos) < min_videos:
            continue  # 去重后视频不足，不作为梗素材
        for v in related_videos:
            bvid = v.get('bvid')
            if bvid:
                assigned_bvids.add(bvid)

        related_videos.sort(key=lambda x: x.get('views', 0), reverse=True)
        total_views = sum(v.get('views', 0) for v in related_videos)

        # 匹配 BGM（词出现在歌名里）
        related_songs = [s for s in hot_songs
                         if word.lower() in s.get('name', '').lower()][:5]

        # 自动生成描述：用 TOP3 视频标题拼接，代替人工 description
        top_titles = [v['title'][:20] for v in related_videos[:3]]
        desc = '相关视频: ' + ' / '.join(top_titles)

        results.append({
            'name': word,
            'description': desc,
            'aliases': [word],
            'related_videos': [
                {
                    'title': v['title'],
                    'bvid': v['bvid'],
                    'author': v.get('author', ''),
                    'cover': v.get('cover', ''),
                    'views': v.get('views', 0),
                    'duration': v.get('duration', 0),
                }
                for v in related_videos[:10]
            ],
            'related_songs': related_songs,
            'total_views': total_views,
            'video_count': len(related_videos),
            'heat': total_views + len(related_songs) * 100000,
        })

        if len(results) >= 10:
            break

    results.sort(key=lambda x: x['heat'], reverse=True)
    print(f'整理出 {len(results)} 个梗素材')
    for r in results:
        print(f'  {r["name"]}: {r["video_count"]}条视频, 热度{r["heat"]}')
    return results

DANMAKU_FALLBACK_WORDS = [
    # 弹幕热词回退词库:get_real_danmaku_words 抓不到弹幕时,用此词库扫描标题/标签/简介。
    # 已剔除与 STOP_TAGS 重叠的 17 个泛化评价词(名场面/离谱/魔性/洗脑/调音/空耳/鬼畜/
    # 高能/前方高能/666/泪目/好活/整活/yyds/绝绝子/三连/神作)——这些词太通用、无区分度,
    # 在 is_useless_tag 中已被列为停用词,不应再作为热词展示(由 test_danmaku_words_no_stop_tags_overlap 锁定)。
    # 经典弹幕
    '哈哈哈哈', '绝了', '神', '经典', '爷青回',
    '循环', '好家伙', '人才', '厉害', '卧槽',
    '有内味了', '快乐源泉', '下饭',
    '燃起来了', '爷青结', '有生之年', 'DNA动了', '妙啊',
    '骚', '秀', '魔鬼', '神仙', '大佬', '太强了',
    '我好了', '双厨狂喜', '梦幻联动', 'awsl',
    '破防了', '真实', '扎心', '人间真实', '我不李姐',
    '格局', '赢麻了', '麻了', '麻中麻', '蚌埠住了',
    '就这', '就这水平', '就这就这', '不会吧不会吧',
    '有一说一', '讲个笑话', '不是我说', '讲道理',
    '我的天', '我的妈呀', '吓死我了',
    '给我整不会了', 'yysy', 'u1s1',
    '听我说谢谢你', '退退退', '真的会谢', '栓Q',
    '尊嘟假嘟', '硬控', '爽', '舒服了', '舒适',
    '卡点卡的刚刚好', '极度舒适', '丝滑', '纵享丝滑',
    # 新增词库
    '开口跪', '惊艳', '震撼', '头皮发麻', '鸡皮疙瘩',
    '上头', '出不去了', '再来亿遍', '停不下来', '无限循环',
    '太魔性了', '笑死', '笑不活了', '肚子疼', '笑喷了',
    '你是魔鬼吗', '什么鬼', '我是谁我在哪', '害怕', '细思极恐',
    '注入灵魂', '灵魂', '精髓', '点睛之笔', '神来之笔',
    '要素过多', '要素察觉', '要素满载', '要素溢出',
    '文艺复兴', '考古', '时代的眼泪', '童年回忆', '回忆杀',
    '建议改成', '禁止好活', '禁止套娃', '禁止',
    '世界线收束', '因果律', '预言家', '刀了',
    '你币没了', '下次一定', '已三连',
    '合影', '留名', '到此一游', '见证历史',
    '高能预警', '弹幕护体', '弹幕掩护', '非战斗人员撤离',
    '名场面打卡', '亿点点', '终于等到你', '每日一遍',
    '阴间', '阴间调音', '阴乐', '阳间', '阳间调音',
    '百万填词', '百万调音', '百万特效', '百万剪辑',
    '神仙UP主', '人才UP主', '关注了', '宝藏UP主',
    '全文背诵', '刻进DNA', 'DNA错乱', 'DNA打结',
    '这谁顶得住', '心脏受不了', '放过我的耳朵',
    '镇站之宝', '必看', '经典永流传',
]

def get_danmaku_hot_words(all_videos):
    print('正在分析弹幕热词...')

    word_list = DANMAKU_FALLBACK_WORDS

    word_freq = {w: 0 for w in word_list}

    for video in all_videos:
        title = video.get('title', '')
        tags = video.get('tags', [])
        desc = video.get('description', '')
        text = f"{title} {' '.join(tags)} {desc}"

        for word in word_list:
            if word in text:
                word_freq[word] += max(1, int(video.get('views', 0) / 100000))

    tag_freq = {}
    for video in all_videos:
        for tag in video.get('tags', []):
            if tag and len(tag) >= 2:
                tag_freq[tag] = tag_freq.get(tag, 0) + max(1, int(video.get('views', 0) / 500000))

    # 用共享的 is_useless_tag 过滤掉广告/活动/平台等干扰标签
    for tag, count in tag_freq.items():
        if not is_useless_tag(tag) and tag not in word_freq:
            word_freq[tag] = count

    result = [{'word': w, 'count': c} for w, c in sorted(word_freq.items(), key=lambda x: x[1], reverse=True) if c > 0]
    print(f'分析出 {len(result)} 个弹幕热词')
    return result[:100]


def fetch_danmaku_xml(cid):
    """通过 XML API 获取视频弹幕文本列表（近期弹幕，第一段6分钟）。

    B站弹幕有两个API：
    - x/v2/dm/web/seg.so: protobuf 格式，需额外依赖，返回全量分段弹幕
    - comment.bilibili.com/{cid}.xml: XML 格式，Python 内置库即可解析，返回第一段

    对于"热词云"场景，近期弹幕已足够，用 XML API 更轻量。
    """
    url = f'https://comment.bilibili.com/{cid}.xml'
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(url, headers=get_headers(), timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        danmaku_list = []
        for d in root.findall('d'):
            text = d.text
            if text and text.strip():
                danmaku_list.append(text.strip())
        return danmaku_list
    except Exception as e:
        print(f'  弹幕抓取失败 cid={cid}: {e}')
        return []


def get_real_danmaku_words(videos):
    """抓取真实弹幕并用 jieba 分词统计词频，返回热词列表。

    相比 get_danmaku_hot_words（预定义词库匹配标题），本函数直接抓取视频弹幕，
    用真实弹幕文本分词统计，能发现预定义词库之外的热词。
    弹幕量不足时自动回退到预定义词库模式。
    """
    import jieba
    from collections import Counter
    import re
    from utils.stopwords import (
        STOPWORDS, WORD_PATTERN, DANMAKU_NUMERIC_ALLOWLIST,
        clean_danmaku_text, ensure_kichu_dict,
    )

    ensure_kichu_dict()  # 加载鬼畜梗自定义词典（哈基米等整词，幂等）

    print('正在抓取真实弹幕并分词...')

    # 去重（按bvid），收集需要抓取的视频
    seen_bvids = set()
    video_cids = []
    need_detail = []

    for v in videos:
        bvid = v.get('bvid', '')
        if not bvid or bvid in seen_bvids:
            continue
        seen_bvids.add(bvid)

        cid = v.get('cid')
        if cid:
            video_cids.append((v, cid))
        else:
            need_detail.append(v)

    # 为缺少 cid 的视频补抓
    if need_detail:
        print(f'  补抓 {len(need_detail)} 个视频的cid...')
        for v in need_detail:
            detail = fetch_video_detail(v['bvid'])
            if detail:
                cid = detail.get('cid')
                if cid:
                    v['cid'] = cid
                    video_cids.append((v, cid))
            time.sleep(0.3)

    # 抓取弹幕
    all_danmaku = []
    print(f'  抓取 {len(video_cids)} 个视频的弹幕...')
    for i, (v, cid) in enumerate(video_cids):
        danmaku_list = fetch_danmaku_xml(cid)
        # 同一视频内完全相同的刷屏弹幕最多计 3 次，保留“共同刷梗”的信号，
        # 但避免复制粘贴把一个普通词直接推到榜首。
        repeated = Counter()
        for raw_text in danmaku_list:
            normalized = re.sub(r'\s+', ' ', clean_danmaku_text(raw_text)).strip()
            if not normalized or repeated[normalized] >= 3:
                continue
            repeated[normalized] += 1
            all_danmaku.append(normalized)
        if (i + 1) % 10 == 0:
            print(f'    进度: {i+1}/{len(video_cids)}, 累计 {len(all_danmaku)} 条弹幕')
        time.sleep(0.3)

    print(f'  共抓取 {len(all_danmaku)} 条弹幕')

    if not all_danmaku:
        print('  [警告] 未抓到弹幕，回退到预定义词库模式')
        return get_danmaku_hot_words(videos)

    # jieba 分词 + 词频统计
    # 只保留中文和字母数字组合（≥2字），过滤纯标点/emoji/单字。
    # 纯数字默认剔除，233/666 等弹幕约定数字走显式白名单。
    # 大小写不敏感统计（AI=ai），但显示时优先保留含大写字母的形式
    word_counter = Counter()
    display_forms = {}  # 小写key → 显示形式（优先保留含大写字母的原始形式）
    for text in all_danmaku:
        for w in jieba.cut(text, HMM=False):  # 精确模式，与项目其他词云保持一致，避免 HMM 碎片
            w = w.strip()
            if len(w) < 2 or not WORD_PATTERN.match(w):
                continue
            w_lower = w.lower()
            if w_lower in STOPWORDS:
                continue
            if w.isdigit() and w not in DANMAKU_NUMERIC_ALLOWLIST:
                continue
            word_counter[w_lower] += 1
            # 优先保留含大写字母的形式（如 "AI" 优于 "ai"）
            if w_lower not in display_forms:
                display_forms[w_lower] = w
            elif w != w_lower and display_forms[w_lower] == w_lower:
                display_forms[w_lower] = w

    result = [{'word': display_forms.get(w, w), 'count': c}
              for w, c in word_counter.most_common(200)]
    print(f'  分词统计出 {len(result)} 个热词（Top: {[r["word"] for r in result[:5]]}）')
    return result[:100]

def get_golden_comments(top_videos):
    """神评论精选：从热门视频抓取高价值评论。

    改进（2026-08-01，借鉴 biliscope 热评策略）：
    - 覆盖前 15 个视频（原 8 个），每视频抓 20 条评论（原 10）
    - 官方热门识别：attr 位标记 bit27(0x8000000)=热门 + up_action.like=UP主觉得很赞
      （biliscope 用的 attr==32768 已过时，实测 B站 改用位标记）
    - 提取头像/等级/IP属地/表情映射，前端展示信息密度提升
    - 综合评分：点赞 + 回复数×3 + UP主点赞×200 + 官方热门×500，
      不是纯按点赞排序，兼顾互动质量
    - 每个视频精选 TOP2 后再全局排序去重，覆盖更广来源
    """
    print('正在抓取热门评论...')
    all_comments = []

    for video in top_videos[:15]:
        aid = video.get('aid')
        if not aid:
            continue
        replies = fetch_comments(aid, ps=20)
        if replies:
            video_candidates = []
            for reply in replies[:20]:
                content = reply.get('content', {})
                message = (content.get('message', '') or '').strip()
                like = reply.get('like', 0) or 0
                rcount = reply.get('rcount', 0) or 0
                member = reply.get('member', {}) or {}

                # 过滤：纯图片评论（无文本）、过短、低赞
                if not message or len(message) < 4 or like < 3:
                    continue

                # 官方热门标记：attr 位标记 bit27（0x8000000）
                attr = reply.get('attr', 0) or 0
                is_hot = bool(attr & 0x8000000)
                # UP主觉得很赞：up_action.like 最可靠
                up_liked = bool((reply.get('up_action') or {}).get('like'))

                # 表情映射：{ '[吃瓜]': 'https://...png' }，前端渲染 emote 图
                emotes = {}
                for key, val in (content.get('emote') or {}).items():
                    url = (val or {}).get('url', '')
                    if url:
                        emotes[key] = url

                video_candidates.append({
                    'content': message[:200],
                    'likes': like,
                    'replies': rcount,
                    'author': member.get('uname', ''),
                    'author_mid': member.get('mid', ''),
                    'author_avatar': member.get('avatar', ''),
                    'author_level': (member.get('level_info') or {}).get('current_level', 0),
                    'up_liked': up_liked,
                    'is_hot': is_hot,
                    'location': (reply.get('reply_control') or {}).get('location', ''),
                    'emotes': emotes,
                    'time': reply.get('ctime', 0),
                    'source_video': video['title'],
                    'source_bvid': video['bvid'],
                    'source_cover': video.get('cover', ''),
                    'rpid': reply.get('rpid', 0),
                })
            # 每视频精选 TOP2（官方热门/UP主点赞优先，其次综合分）
            video_candidates.sort(key=lambda x: (
                x['is_hot'], x['up_liked'],
                x['likes'] + x['replies'] * 3
            ), reverse=True)
            all_comments.extend(video_candidates[:2])
        time.sleep(0.5)

    # 全局综合评分：点赞 + 回复×3 + UP主点赞×200 + 官方热门×500
    for c in all_comments:
        c['score'] = (c['likes'] + c['replies'] * 3
                      + (200 if c['up_liked'] else 0)
                      + (500 if c['is_hot'] else 0))
    all_comments.sort(key=lambda x: x['score'], reverse=True)

    # 去重：同一作者同一内容只保留一条（跨视频重复）
    seen = set()
    unique = []
    for c in all_comments:
        key = (c['author'], c['content'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    print(f'抓取到 {len(unique)} 条热门评论（官方热评 {sum(1 for c in unique if c["is_hot"])} 条）')
    return unique[:20]

# ────────────── run_all_crawlers 子函数 ──────────────
# 从原 205 行 run_all_crawlers 拆出:去重 / 潜力候选过滤 / 同接+stat 补抓 / 素材发掘,
# 主函数仅保留编排,职责单一,便于阅读与测试。

def _deduplicate_by_bvid(videos):
    """按 bvid 去重,保留首次出现的副本(各采集源内部已去重,此处防跨源重复)。"""
    seen = set()
    unique = []
    for v in videos:
        bvid = v.get('bvid')
        if not bvid or bvid in seen:
            continue
        seen.add(bvid)
        unique.append(v)
    return unique


def _passes_relaxed_filter(v, step, now):
    """单条视频是否通过兜底放宽门槛(播放下限 / 上限不放宽 / 互动·时效按 step)。"""
    views = int(v.get('views') or 0)
    engagement = calc_engagement_quality(v)
    pub = v.get('pub_date') or 0
    return (
        POTENTIAL_VIEWS_MIN <= views <= step['views_max']
        and engagement >= step['engagement_min']
        and pub > 0
        and (now - pub) <= step['age_days'] * 86400
    )


def _filter_potential_candidates(unique_potential, now):
    """严格过滤潜力候选;候选不足 10 条时逐步放宽互动/时效门槛。

    播放上限 POTENTIAL_VIEWS_MAX 不放宽——超过即"已经火了"(UP主规则),
    即使兜底也不应让已火视频混进潜力榜。
    播放下限 POTENTIAL_VIEWS_MIN 同样不放宽——低于即噪声,放宽只会引入低质视频。

    返回 (candidates, applied_relaxation):applied_relaxation 为 None 表示严格过滤通过,
    非 None 表示命中的兜底参数(用于日志)。
    """
    # 分区硬约束：潜力榜只收鬼畜分区作品。候选池来源包括全站热门/搞笑区等，
    # 喵星人(218)/野生动物(221)/搞笑(138)等非鬼畜视频不得入选。
    unique_potential = [v for v in unique_potential if v.get('tid') in KICHU_TIDS]

    # 最新发布源（fetch_kichu_newest，newlist 接口）stat 全为 0（views=0），
    # 会被播放下限 POTENTIAL_VIEWS_MIN 误杀，先补抓真实互动数据再走门槛。
    # 只补抓 views=0 的估算视频（搜索源 views 为真实值，走 _enrich_with_stats 补抓）。
    est_zero = [v for v in unique_potential
                if v.get('_stats_estimated') and not int(v.get('views') or 0)]
    if est_zero:
        print(f'正在为 {len(est_zero)} 个最新发布视频补抓真实互动数据...')
        for v in est_zero:
            detail = fetch_video_detail(v['bvid'])
            _online_pacing()
            if detail:
                _apply_real_stat(v, detail)
            v.pop('_stats_estimated', None)

    candidates = [v for v in unique_potential if is_potential_candidate(v, now)]
    if len(candidates) >= 10:
        return candidates, None

    # 兜底放宽阶梯：基准与 config.POTENTIAL_* 严格门槛一致，逐级放宽互动/时效。
    # 播放上限与下限均不放宽（理由见 docstring）。
    relaxation_steps = [
        {'views_max': POTENTIAL_VIEWS_MAX,
         'engagement_min': POTENTIAL_ENGAGEMENT_MIN, 'age_days': POTENTIAL_AGE_DAYS},
        {'views_max': POTENTIAL_VIEWS_MAX, 'engagement_min': 5, 'age_days': POTENTIAL_AGE_DAYS},
        {'views_max': POTENTIAL_VIEWS_MAX, 'engagement_min': 3, 'age_days': POTENTIAL_AGE_DAYS},
        {'views_max': POTENTIAL_VIEWS_MAX, 'engagement_min': 0, 'age_days': 30},
    ]
    for step in relaxation_steps:
        candidates = [v for v in unique_potential if _passes_relaxed_filter(v, step, now)]
        if len(candidates) >= 10:
            return candidates, step
    return candidates, relaxation_steps[-1]


def _apply_video_metadata(v, detail):
    """Reuse an already fetched detail response; do not add per-card profile requests."""
    avatar = (detail.get('owner') or {}).get('face')
    if avatar:
        v['author_avatar'] = _normalize_url(avatar)
    if detail.get('tname'):
        v['tname'] = detail['tname']
    if detail.get('pubdate'):
        published = _parse_pubdate(detail['pubdate'])
        if published:
            v['pub_date'] = published


def _apply_real_stat(v, detail):
    """用 web-interface/view 返回的真实 stat 覆盖估算互动数据,并重算 trend_score/label。

    排行榜/搜索 API 不返回 likes/shares,parse 时按 5%/1% 估算通过初筛,
    此处用真实 stat 覆盖。views/coins/favorites/danmaku/comments 优先用真实值,
    缺失时回退原值(避免 detail 字段缺失导致归零)。
    """
    _apply_video_metadata(v, detail)
    stat = detail.get('stat', {})
    if all(stat.get(key) is not None for key in ('view', 'like', 'coin', 'favorite', 'share', 'reply', 'danmaku')):
        v.update(metrics_source='bilibili_stat', observed_at=int(time.time()))
    elif v.get('metrics_source') == 'bilibili_stat':
        # Partial replacement mixes sampling times; it cannot certify a whole row.
        v['metrics_source'] = 'legacy_unknown'
        v.pop('observed_at', None)
    v['views'] = stat.get('view', v.get('views', 0))
    v['likes'] = stat.get('like', v.get('likes', 0))
    v['coins'] = stat.get('coin', v.get('coins', 0))
    v['favorites'] = stat.get('favorite', v.get('favorites', 0))
    v['shares'] = stat.get('share', v.get('shares', 0))
    v['danmaku'] = stat.get('danmaku', v.get('danmaku', 0))
    v['comments'] = stat.get('reply', v.get('comments', 0))
    v['trend_score'] = calc_trend_score(
        v['views'], v['likes'], v['coins'], v['favorites'],
        v['shares'], v['comments'], v['danmaku'], v.get('pub_date', 0)
    )
    v['trend_label'] = get_trend_label(v['trend_score'])


def _online_weights(n):
    """同接滑动窗口权重：按时间从旧到新，最新观测占比最大。
    1 轮 → [1.0]；2 轮 → [0.4, 0.6]；3 轮 → [0.2, 0.3, 0.5]（最新 0.5）。"""
    if n <= 1:
        return [1.0]
    if n == 2:
        return [0.4, 0.6]
    return [0.2, 0.3, 0.5]


def _smooth_online(bvid, current, hours=48, history_limit=2):
    """跨轮同接滑动加权平均（L2）：本轮 ×0.5 + 最近历史观测 ×0.3/×0.2。

    - 本轮失败（current=None）时回退用历史值（缺失轮跳过，不拉低不抬高）
    - 历史全无/全失败 → 返回 current（退化为单点，冷启动可接受）
    基于 video_obs 历史序列，消除"单时刻瞬时采样"的时段性抖动。
    """
    history = get_video_obs_trend(bvid, hours=hours)
    series = [h['online_count'] for h in history
              if h.get('online_count') is not None]
    recent = series[-history_limit:]
    if current is not None:
        recent = recent + [current]
    if not recent:
        return current
    weights = _online_weights(len(recent))
    total = sum(w * c for w, c in zip(weights, recent))
    wsum = sum(weights)
    return round(total / wsum) if wsum else current


def _enrich_with_stats(candidates):
    """为候选视频抓取同接,并用真实 stat 覆盖估算互动数据。

    就地修改 candidates:注入 online_count/cid,对 _stats_estimated 视频覆盖 stat 并重算
    trend,最后清理所有估算标记(fetch_video_detail 失败的保留估算值但移除标记)。
    A2 语义:online_count=None 表示未知(抓取失败/无cid),不是 0。
    L2 语义:online_count 存跨轮滑动加权平均(评分用,抗单点失真);
            online_count_raw 存本轮实测值(供 video_obs 落库,避免平滑值再被平滑)。
    """
    est_count = sum(1 for v in candidates if v.get('_stats_estimated'))
    print(f'正在为 {len(candidates)} 个候选视频抓取同接（其中 {est_count} 个需补抓真实互动数据）...')
    for v in candidates:
        detail = fetch_video_detail(v['bvid'])
        _online_pacing()
        if not detail:
            v['online_count'] = None  # A2: 抓取失败=未知(NULL)，不是0
            continue
        # 用 detail 的 cid 获取同接(避免 fetch_online_count 内部重复请求 detail)
        _apply_video_metadata(v, detail)
        cid = detail.get('cid')
        if cid:
            v['cid'] = cid
            if _online_breaker_open():
                # L3 熔断中：不再发起同接请求（防风控升级），raw 置 None → 平滑回退历史
                raw_online = None
                v['online_circuit_skipped'] = True
                online_display, online_precision = None, None
            else:
                raw_online, online_precision, online_display = fetch_online_count(v['bvid'], cid)
                _online_pacing()
        else:
            raw_online = None
            online_display, online_precision = None, None
        v['online_count_raw'] = raw_online  # 本轮实测值，落库用（不污染历史序列）
        v['online_count'] = _smooth_online(v['bvid'], raw_online)  # 平滑值，评分用
        # 精度/原始展示透传前端：<1000 精确数字，"1000+"/"1.1万" 如实展示
        # （精度由 B 站源头决定，前端显示原始字符串比显示解析数字更诚实）
        if online_display is not None:
            v['online_display'] = online_display
            v['online_precision'] = online_precision
            v['online_observed_at'] = int(time.time())
        # 排行榜/搜索视频:用真实 stat 覆盖估算值
        if v.get('_stats_estimated'):
            _apply_real_stat(v, detail)
            v.pop('_stats_estimated', None)
    # 清理可能残留的估算标记
    for v in candidates:
        v.pop('_stats_estimated', None)


def _filter_material_candidates(music_videos, funny_videos, now):
    """鬼畜素材发掘(板块2):从音乐/搞笑区找二创潜力素材。

    与潜力视频不同:找"能被二创成鬼畜的非鬼畜视频",原素材热度正向
    (越火受众越大) + 传播性,不用同接,时效窗口 60 天。返回按 material_score 降序的 Top 20。
    """
    material_unique = _deduplicate_by_bvid(music_videos + funny_videos)
    material_candidates = [v for v in material_unique if is_material_candidate(v, now)]

    # 为未补全真实互动数据的素材候选补抓 stat(潜力视频流程已补的会复用,不重复请求)
    est_mat = sum(1 for v in material_candidates if v.get('_stats_estimated'))
    if est_mat > 0:
        print(f'正在为 {est_mat}/{len(material_candidates)} 个素材候选补抓真实互动数据...')
        for v in material_candidates:
            if not v.get('_stats_estimated'):
                continue
            detail = fetch_video_detail(v['bvid'])
            time.sleep(0.3)
            if detail:
                _apply_real_stat(v, detail)
            v.pop('_stats_estimated', None)

    # 补抓后真实播放可能低于门槛,重新过滤一次
    material_candidates = [v for v in material_candidates if is_material_candidate(v, now)]

    score_material_batch(material_candidates, now)
    for v in material_candidates:
        v['material_reason'] = get_material_reason(v, now)

    material_candidates.sort(key=lambda x: x['material_score'], reverse=True)
    material_candidates = material_candidates[:20]
    print(f'  - 素材发掘: {len(material_candidates)} 条 / 候选池 {len(material_unique)}')
    return material_candidates


def run_all_crawlers():
    print('=' * 60)
    print('开始执行爬虫任务...')
    start_time = time.time()

    kichu_videos = get_kichu_videos()
    time.sleep(0.5)
    # 最新发布源（newlist）：补足"低播放高同接"新视频发现盲区——刚发布的视频
    # 播放量低，热门feed/关键词搜索/全站榜三条路都覆盖不到。只进候选池，
    # 不并入 kichu_videos（避免 0 播放视频污染热门榜/热梗统计）。
    kichu_newest = fetch_kichu_newest()
    time.sleep(0.5)
    music_videos = get_music_videos()
    time.sleep(0.5)
    funny_videos = get_funny_videos()
    time.sleep(0.5)
    popular_videos = get_popular_videos()
    time.sleep(0.5)

    # 全局去重(各路内部已去重,但跨源可能重复)
    unique_potential = _deduplicate_by_bvid(
        kichu_videos + kichu_newest + music_videos + funny_videos + popular_videos)
    now = time.time()

    # ── 鬼畜潜力视频:综合潜力指数排序 ──
    candidates, applied_relaxation = _filter_potential_candidates(unique_potential, now)
    _enrich_with_stats(candidates)
    # 超播放上限的"已火"视频：不进潜力榜（候选过滤），但已有历史观测数据（video_obs
    # 存在有效同接观测）的仍用候选池批内边界外推潜力分并写入——供 kichu_rank 等展示，
    # 避免卡片分数为空。同接填历史平滑值并打 online_circuit_skipped（前端显示"(历史)"）；
    # online_count_raw 显式置 None，避免 record_video 把历史值当本轮实测二次平滑落库。
    over_cap = []
    for v in unique_potential:
        if v.get('tid') not in KICHU_TIDS:
            continue
        if int(v.get('views') or 0) <= POTENTIAL_VIEWS_MAX:
            continue
        obs_online = _smooth_online(v['bvid'], None)
        if obs_online is None:
            continue  # 无有效观测数据，无法外推，保持原样（分数仍为空）
        v['online_count'] = obs_online
        v['online_count_raw'] = None
        v['online_circuit_skipped'] = True
        over_cap.append(v)
    # 批量计算潜力指数(批内归一,需看到整个候选池)和理由
    score_potential_batch(candidates, now, extra=over_cap)
    for v in candidates:
        v['potential_reason'] = get_potential_reason(v, now)
    for v in over_cap:
        v['potential_reason'] = get_potential_reason(v, now)
    candidates.sort(key=lambda x: x['potential_score'], reverse=True)
    hot_videos = candidates[:30]

    # ── 鬼畜素材发掘(板块2):从音乐/搞笑区找二创潜力素材 ──
    material_candidates = _filter_material_candidates(music_videos, funny_videos, now)

    # ── 其他板块 ──
    hot_memes = get_hot_memes(kichu_videos, music_videos, funny_videos, popular_videos)
    hot_songs = get_hot_songs(music_videos, kichu_videos)
    # 梗素材库: 4 路候选池都是制作/类型词搜索,常驻热梗(哈基米/叮咚鸡等)频次不足易被过滤,
    # 按种子热梗词主动搜索鬼畜区补足候选池,保证热梗不丢
    meme_seed_videos = fetch_meme_seed_videos()
    meme_materials = get_meme_materials(
        unique_potential + meme_seed_videos, hot_songs, seed_words=load_meme_seed_words())
    # 真实弹幕热词:抓取鬼畜榜+潜力视频+素材发掘的弹幕,jieba分词统计
    danmaku_words = get_real_danmaku_words(kichu_videos[:20] + hot_videos[:30] + material_candidates[:20])
    golden_comments = get_golden_comments(kichu_videos[:10])

    elapsed = round(time.time() - start_time, 2)
    print(f'爬虫任务完成，总耗时 {elapsed} 秒')
    relax_info = f'（兜底: {applied_relaxation}）' if applied_relaxation else ''
    print(f'  - 鬼畜潜力视频: {len(hot_videos)} 条 / 候选池 {len(unique_potential)} {relax_info}')
    print(f'  - 素材发掘: {len(material_candidates)} 条')
    print(f'  - 热梗: {len(hot_memes)} 个')
    print(f'  - 热门BGM: {len(hot_songs)} 首')
    print(f'  - 梗素材: {len(meme_materials)} 个')
    print(f'  - 弹幕热词: {len(danmaku_words)} 个')
    print(f'  - 神评论: {len(golden_comments)} 条')
    print('=' * 60)

    # C13: 全部发现过的视频（含各板块落选者）登记入 PostgreSQL 维度表，
    # 保留"曾被过滤但后来爆发"的假阴性分析能力。
    # _source 标记首个发现源；app.py 落库后移除，不写入 JSON 缓存
    all_found = {}
    for source, vlist in (('kichu', kichu_videos), ('kichu_new', kichu_newest),
                          ('music', music_videos), ('funny', funny_videos),
                          ('popular', popular_videos), ('meme_seed', meme_seed_videos)):
        for v in vlist:
            bvid = v.get('bvid')
            if bvid and bvid not in all_found:
                v['_source'] = source
                all_found[bvid] = v

    return {
        'kichu_rank': kichu_videos[:20],
        'hot_memes': hot_memes,
        'hot_songs': hot_songs,
        'meme_materials': meme_materials,
        'hot_videos': hot_videos,
        'material_candidates': material_candidates,
        'danmaku_words': danmaku_words,
        'comments_gold': golden_comments,
        '_all_videos': list(all_found.values()),
    }
