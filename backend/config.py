"""鬼畜热度看板 V2.0 — 全局配置

集中管理算法参数，方便后续调优。
修改后需重启后端生效。

V2 变更：运维参数 .env 化（python-dotenv），算法参数保留默认值但允许 env 覆盖。
"""

import os
import secrets

from dotenv import load_dotenv
from runtime_paths import RuntimePaths

# 读 .env，不强制存在（Docker 环境用 env_file 注入）
load_dotenv()


# ==================== 运维参数（必须 .env 化）====================

# 运行时路径通过 KICHU_* 环境变量注入；未配置时仅回退到本地开发目录。
RUNTIME_PATHS = RuntimePaths.from_environment(os.environ)
DATA_DIR = str(RUNTIME_PATHS.cookie_file.parent)

# 后端端口
BACKEND_PORT = int(os.getenv('BACKEND_PORT', '5000'))


# ==================== 潜力视频评分参数 ====================

# ── 同接补正机制 ──
# 同接数（当前在线观看人数）是播放量一阶导数的近似，反映视频当下的传播动能：
#   同接指数 0   = 此刻没人看 → 视频已停滞 → 播放量涨不动 → 动能不足
#   同接指数 100 = 千人同看   → 视频正在爆发 → 播放量即将飞跃 → 动能强劲
# 虽是抓取瞬间的静态快照，但能在一定程度上反映动态增长趋势。
#
# 核心用比值（同接/播放量）衡量，而非绝对同接数——因为：
#   · 1万播放 + 100同接（1%）= 起飞期，动能强劲
#   · 1万播放 + 50同接（0.5%）= 有热度，仍在增长
#   · 200万播放 + 50同接（0.0025%）= 衰退期，播放量基本定型
#   · 200万播放 + 500同接（0.025%）= 大视频长尾余温（瘦死骆驼比马大），
#     也可能是编辑推荐吃上推流（官方认可，质量高）——但比值低说明已过峰值，
#     对"潜力视频"榜单而言不再是增长股，理应让位给小而热的起飞股

# 同接率满分线：同接/播放量达到此值时同接指数 = 100（满分）
# 0.01 = 1%（鬼畜区实战经验：1万播放同接100就非常棒了）
ONLINE_TARGET_RATE = float(os.getenv('ONLINE_TARGET_RATE', '0.01'))

# 同接最小有效数：低于此值视为噪声（UP主自检/偶发点击），不计传播动能
# 例：6K播放+1同接不应得满分，1个在线观众不足以判断传播状态
ONLINE_MIN_SIGNIFICANT = int(os.getenv('ONLINE_MIN_SIGNIFICANT', '5'))

# 同接指数曲线幂次：控制同接率到分数的映射弧度
# 1.0 = 线性（0.5%得50分）；0.7 = 中段更敏感（0.5%得62分），更贴合"不少了"的体感
# 幂次越小，中段越敏感，但低比值区也会被抬升（0.01%在线性=1分，0.7次方=4分）
ONLINE_CURVE_POWER = float(os.getenv('ONLINE_CURVE_POWER', '0.7'))

# 同接乘数基底：同接指数为 0 时的乘数（< 1.0 = 动能不足降权）
ONLINE_FACTOR_BASE = float(os.getenv('ONLINE_FACTOR_BASE', '0.8'))

# 同接乘数权重：同接指数每满 100 分在此基底上追加的幅度
# 最终乘数 = ONLINE_FACTOR_BASE + ONLINE_FACTOR_WEIGHT × (同接指数 / 100)
# 例：0.8 + 0.4 × 1.0 = 1.2（同接满分时 ×1.2 动能加成）
ONLINE_FACTOR_WEIGHT = float(os.getenv('ONLINE_FACTOR_WEIGHT', '0.4'))

# "正在热播"理由标签触发阈值（0-100 分），仅用于前端展示标签
ONLINE_INDEX_THRESHOLD = int(os.getenv('ONLINE_INDEX_THRESHOLD', '50'))

# 同接抓取熔断（L3 降级）：连续失败达到阈值即停止发起同接请求（防风控升级），
# 冷却到期后自动进入半开探测，成功即恢复。-412 风控错误不计累计、直接熔断。
ONLINE_BREAK_THRESHOLD = int(os.getenv('ONLINE_BREAK_THRESHOLD', '3'))
ONLINE_BREAK_COOLDOWN = int(os.getenv('ONLINE_BREAK_COOLDOWN', '1800'))  # 30 分钟

# 半开探测配额：冷却到期后放行的探测请求数，连续成功达到此值才真正恢复闭合。
# 防"放行 1 次成功即全量恢复 → 风控未除 → 立刻再熔断"的恢复-再熔断抖动。
ONLINE_BREAK_HALF_OPEN_LIMIT = int(os.getenv('ONLINE_BREAK_HALF_OPEN_LIMIT', '3'))


# ==================== 告警通知（邮件）====================
# 同接熔断等异常事件邮件告警。未配置 SMTP（host/to 为空）时静默跳过（仅日志，不阻断主流程）。
ALERT_SMTP_HOST = os.getenv('ALERT_SMTP_HOST', '')
ALERT_SMTP_PORT = int(os.getenv('ALERT_SMTP_PORT', '465'))  # 465=SSL；587=STARTTLS
ALERT_SMTP_USER = os.getenv('ALERT_SMTP_USER', '')
ALERT_SMTP_PASS = os.getenv('ALERT_SMTP_PASS', '')
ALERT_MAIL_TO = os.getenv('ALERT_MAIL_TO', '')


# ==================== 潜力视频候选门槛 ====================

# 播放量上限：超过此值视为"已经火了"，不再是潜力视频，剔除出候选池
# UP主判断：鬼畜区 100 万播放即已出圈（2026-07-26 由 250 万下调）
POTENTIAL_VIEWS_MAX = int(os.getenv('POTENTIAL_VIEWS_MAX', '1000000'))

# 潜力视频候选门槛（is_potential_candidate / _filter_potential_candidates 兜底基线）
POTENTIAL_VIEWS_MIN = int(os.getenv('POTENTIAL_VIEWS_MIN', '1500'))      # 播放下限：低于此视为噪声
POTENTIAL_ENGAGEMENT_MIN = int(os.getenv('POTENTIAL_ENGAGEMENT_MIN', '10'))  # 互动质量下限
POTENTIAL_AGE_DAYS = int(os.getenv('POTENTIAL_AGE_DAYS', '21'))          # 时效窗口（天）

# 素材发掘候选门槛（is_material_candidate）
MATERIAL_VIEWS_MIN = int(os.getenv('MATERIAL_VIEWS_MIN', '3000'))        # 播放下限（素材越火二创受众越大）
MATERIAL_AGE_DAYS = int(os.getenv('MATERIAL_AGE_DAYS', '60'))            # 时效窗口（二创周期更长）

# 热梗榜门槛：关键词聚合后总播放量下限（低于此不算"热梗"）
HOT_MEME_VIEWS_MIN = int(os.getenv('HOT_MEME_VIEWS_MIN', '300000'))


# ==================== 分区常量（全项目唯一真源） ====================
# 历史教训：分区集合曾在 bilibili.py / scorer.py / db.py 三处各写一份且相互漂移，
# 导致喵星人(218)/野生动物(221)被当鬼畜加分、爆发榜 SQL 与采集口径不一致。
# 2026-08-01 统一收口到本文件，所有模块一律 from config import，禁止再硬编码。

# 鬼畜区子分区（B站搜索 API typeid 实测，2026-07-31 复审）：
#   22=鬼畜调教  26=音MAD  126=人力VOCALOID  216=鬼畜剧场
# 已剔除的历史错配分区：
#   119（鬼畜父分区，搜索返回子分区值，视频 tid 不会是 119，仅作评分/爆发榜兜底见下）
#   127（现为"教程演示"，非鬼畜）/ 218（现为"喵星人"，非鬼畜）/ 221（野生动物，非鬼畜）
#   217（动物圈，非鬼畜）
KICHU_TIDS = {22, 26, 126, 216}

# 含鬼畜父分区的评分/查询集合：119 是历史遗留的父分区ID，老数据/部分接口仍可能返回，
# 在"评分加分"与"爆发榜 SQL"这类需要兼容存量数据的场景使用；采集过滤一律用 KICHU_TIDS。
KICHU_TIDS_WITH_PARENT = KICHU_TIDS | {119}

# 音乐区（含子分区）：主分区 3
# 子分区（B站官方分区表，2023-09 复审，与 biliscope VIDEO_TYPE_MAP 一致）：
#   28 原创音乐  29 音乐现场  30 VOCALOID·UTAU  31 翻唱
#   59 演奏  130 音乐综合  193 MV  243 乐评盘点  244 音乐教学
# 已剔除的历史错配：194（电音，2022 旧分区已下线，现不属音乐区）
MUSIC_TID = 3
MUSIC_TIDS = {3, 28, 29, 30, 31, 59, 130, 193, 243, 244}

# 搞笑区：即生活区(160)下的"搞笑"子分区 138（无独立二级子分区）
# 已剔除的历史错配：139-144（官方已不存在的幽灵分区）、145（欧美电影，属电影区非搞笑）
FUNNY_TID = 138
FUNNY_TIDS = {138}


# ==================== 调度参数 ====================

# 全量抓取时段（24小时制，逗号分隔；凌晨 3 点 + 下午 15 点双频，避开 B 站白天高峰）
CRAWL_HOURS = os.getenv('CRAWL_HOURS', '3,15')

# UP 主动态分析调度时刻（24小时制，逗号分隔，复用 CRAWL_HOURS 模式）
# 默认每天 4 次（04:30/10:30/16:30/22:30），错开全量抓取窗口：
#   04:30/16:30 紧跟 04:00/16:00 全量后半小时；10:30/22:30 落在两全量窗口中间。
# 提升 up_obs 时效性（播放量排行榜/总播放量数据延迟从 24h 降至 6h）。
# 旧键 UP_TRENDS_HOUR（单值 int）向后兼容：未配 UP_TRENDS_HOURS 时回退读取。
_up_trends_hours_raw = os.getenv('UP_TRENDS_HOURS') or os.getenv('UP_TRENDS_HOUR', '4,10,16,22')
UP_TRENDS_HOURS = _up_trends_hours_raw
UP_TRENDS_MINUTE = int(os.getenv('UP_TRENDS_MINUTE', '30'))

# 发布日历独立调度：与热门内容全量抓取解耦，但由持久化任务队列串行消费。
# 高频窗口负责发现新投稿；30 天窗口每天更新近期播放量；完整年份扫描每周做软对账。
CALENDAR_START_YEAR = int(os.getenv('CALENDAR_START_YEAR', '2026'))
CALENDAR_RECENT_HOURS = os.getenv('CALENDAR_RECENT_HOURS', '0,6,12,18')
CALENDAR_RECENT_MINUTE = int(os.getenv('CALENDAR_RECENT_MINUTE', '10'))
CALENDAR_DAILY_HOUR = int(os.getenv('CALENDAR_DAILY_HOUR', '1'))
CALENDAR_DAILY_MINUTE = int(os.getenv('CALENDAR_DAILY_MINUTE', '20'))
CALENDAR_WEEKLY_DAY = os.getenv('CALENDAR_WEEKLY_DAY', 'sun')
CALENDAR_WEEKLY_HOUR = int(os.getenv('CALENDAR_WEEKLY_HOUR', '0'))
CALENDAR_WEEKLY_MINUTE = int(os.getenv('CALENDAR_WEEKLY_MINUTE', '40'))

# hot tier 观测上限（控成本：200 视频 × 2 API × 0.3s ≈ 2 分钟）
OBSERVE_HOT_LIMIT = int(os.getenv('OBSERVE_HOT_LIMIT', '200'))

# 失败重试：任务失败后延迟 N 分钟重试，最多 M 次
RETRY_DELAY_MINUTES = int(os.getenv('RETRY_DELAY_MINUTES', '15'))
RETRY_MAX_ATTEMPTS = int(os.getenv('RETRY_MAX_ATTEMPTS', '2'))

# 412 限流指数退避基数（秒）：1.5 → 3 → 6 → 跳过
RETRY_BACKOFF_BASE = float(os.getenv('RETRY_BACKOFF_BASE', '1.5'))


# ==================== 写操作访问口令 ====================
# 局域网共享时防止他人随意触发写接口（抓取/改配置/删收藏等）。
# 优先级：环境变量 KICHU_WRITE_TOKEN > KICHU_WRITE_TOKEN_FILE > 本地开发 token 文件。

def get_write_token():
    env_token = os.getenv('KICHU_WRITE_TOKEN')
    if env_token:
        return env_token.strip()
    token_file = os.getenv('KICHU_WRITE_TOKEN_FILE') or os.path.join(DATA_DIR, 'api_token.txt')
    if os.path.exists(token_file):
        with open(token_file, 'r', encoding='utf-8') as f:
            t = f.read().strip()
            if t:
                return t
    os.makedirs(os.path.dirname(token_file) or '.', exist_ok=True)
    t = secrets.token_hex(16)
    with open(token_file, 'w', encoding='utf-8') as f:
        f.write(t)
    return t
