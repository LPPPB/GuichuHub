import { Bookmark, Eye, Sparkles } from 'lucide-react'

// 用 B 站风格的硬币和点赞轮廓，保留文字标签以便辨认和朗读。
function BiliCoinIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="treasure-metric-icon">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
    <path d="M9 7.5v9m6-9v9M9 8.4h4.1a2 2 0 0 1 0 4H9m0 0h4.5a2 2 0 0 1 0 4H9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

function BiliLikeIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="treasure-metric-icon">
    <path d="M8.5 10.2 11.7 4a1.5 1.5 0 0 1 2.8.7v4h4.2a2 2 0 0 1 1.9 2.5l-2 7.2a2 2 0 0 1-1.9 1.5H8.5V10.2ZM4 10h4.5v10H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
}

function Metric({ icon, label, value }) {
  return <span className="treasure-metric" title={`${label} ${value}`}>
    {icon}<span className="treasure-metric-label">{label}</span><strong>{value}</strong>
  </span>
}

export default function InteractionQualityCard({ video, rank, formatNumber, delay = 0 }) {
  const score = video.engagement_score
  const ratio = value => `${Number(value || 0).toFixed(2)}%`

  return <a href={`https://www.bilibili.com/video/${video.bvid}`} target="_blank" rel="noopener noreferrer"
            className="treasure-card kb-stagger group" style={{ animationDelay: `${delay}ms` }}>
    <span className="treasure-rank" aria-label={`第 ${rank} 名`}>{String(rank).padStart(2, '0')}</span>
    <div className="treasure-main">
      <div className="treasure-title-row">
        <h3 className="treasure-title">{video.title}</h3>
        {video.is_treasure && <span className="treasure-badge" title="播放低于中位且投币率高于中位"><Sparkles size={12} />宝藏</span>}
      </div>
      <div className="treasure-byline">
        <span>{video.author || '未知UP'}</span><span className="treasure-dot" aria-hidden="true" />
        <span>{video.tname || '鬼畜视频'}</span><span className="treasure-dot" aria-hidden="true" />
        <span className="treasure-views"><Eye size={13} aria-hidden="true" />{formatNumber(video.views)} 播放</span>
      </div>
      <div className="treasure-metrics">
        <Metric icon={<BiliCoinIcon />} label="投币" value={ratio(video.coin_ratio)} />
        <Metric icon={<BiliLikeIcon />} label="点赞" value={ratio(video.like_ratio)} />
        <Metric icon={<Bookmark size={16} aria-hidden="true" />} label="收藏" value={ratio(video.fav_ratio)} />
      </div>
    </div>
    <div className={`treasure-score ${score == null ? 'treasure-score--pending' : ''}`}
         title={video.score_reason || '六项互动行为的同龄样本综合相对分'}>
      <span>互动相对分</span>
      <strong>{score == null ? '待评分' : Number(score).toFixed(2)}</strong>
      {score != null && <small>/ 100</small>}
    </div>
  </a>
}
