import { useId, useState, lazy, Suspense } from 'react'
import { BookmarkPlus, Bookmark, Eye, MessageSquare, Subtitles, Play, Users, TrendingUp, Sparkles, UserRound, ChevronUp } from 'lucide-react'
import { proxyImage } from '../utils/image'
import { formatVideoPublishTime, videoRate } from '../utils/videoCardMeta'
import VideoRadar from './VideoRadar'
import { observationTime } from './RadarDetails'
import './ContentLabels.css'

const ObsTrendChart = lazy(() => import('./ObsTrendChart'))
const AiSummary = lazy(() => import('./AiSummary'))

export default function VideoCard({ video, index, displayRank, formatNumber, onFavorite, isFavorited, staggerDelay = 0, showRadar = false, variant = 'full' }) {
  const rank=Number.isInteger(displayRank) && displayRank>0 ? displayRank : index!=null ? index+1 : null
  const [expanded, setExpanded] = useState(false)
  const [showAiSummary, setShowAiSum] = useState(false)
  const [showPortrait, setShowPortrait] = useState(false)
  const [failedAvatar, setFailedAvatar] = useState(null)
  const panelId = useId()
  const videoUrl = video.url || `https://www.bilibili.com/video/${video.bvid}`
  const avatar = video.author_avatar || ''
  const published = formatVideoPublishTime(video.pub_date)
  const statisticsTime = formatVideoPublishTime(video.observed_at)
  const historical = Boolean(video.online_circuit_skipped || video.online_count_raw === null)
  const hasOnline = video.online_count != null && Number.isFinite(Number(video.online_count)) && Number(video.online_count) >= 0
  const online = video.online_display || (hasOnline ? formatNumber(video.online_count) : '')
  const duration = Number(video.duration)
  const durationText = duration > 0 ? `${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}` : '--:--'
  const label = (video.trend_label || '').trim()
  const statusClass = /爆|飙/.test(label) ? 'kb-label--rose' : /热|涨|上升|崛起/.test(label) ? 'kb-label--pink' : /凉|跌|下降/.test(label) ? 'kb-label--cyan' : ''
  const hasRadar = showRadar && Boolean(video.radar)
  const observedOnline = video.online_observation
  const isV2 = video.radar?.algorithm_version === 'radar-v2'
  const isDashboard = variant === 'dashboard'
  const reasons = (
    <div className="video-card-reasons">
      {video.potential_score != null && <span className="kb-label kb-label--rose">潜力 <b>{video.potential_score}</b><span>· {video.potential_reason || '综合潜力'}</span></span>}
      {video.material_score != null && <span className="kb-label kb-label--cyan">素材 <b>{video.material_score}</b><span>· {video.material_reason || '素材价值'}</span></span>}
    </div>
  )
  const trendButton = (
    <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} aria-controls={`${panelId}-trend`} className="video-card-action video-card-action--primary">
      {expanded ? <ChevronUp size={18} /> : <TrendingUp size={18} />}<span>{expanded ? '收起趋势' : '观测趋势'}</span>
    </button>
  )

  return (
    <article className={`kb-card kb-stagger kb-video-card video-card${isDashboard ? ' video-card--dashboard' : ''}`} style={{ animationDelay: `${staggerDelay}ms` }}>
      <div className="inner">
        <div className={`video-card-layout ${hasRadar ? 'video-card-layout--radar' : ''}`}>
          <a href={videoUrl} target="_blank" rel="noopener noreferrer" className="video-card-cover" aria-label={`在 B 站播放：${video.title}`}>
            {video.cover && <img src={proxyImage(video.cover)} alt="" loading="lazy" />}
            <span className="video-card-play"><Play size={24} fill="currentColor" /></span>
            <span className="video-card-duration">{durationText}</span>
          </a>

          <div className="video-card-heading">
            <div className="video-card-title-row">
              {rank != null && <span className={`kb-rank shrink-0 ${rank <= 3 ? `kb-rank--${rank}` : 'kb-rank--n'}`}>{rank}</span>}
              <h4><a href={videoUrl} target="_blank" rel="noopener noreferrer" title={video.title}>{video.title}</a></h4>
            </div>
            {label && <span className={`kb-label kb-label--status video-card-status ${statusClass}`}>{label}</span>}
          </div>

          <div className="video-card-meta">
            <span className="video-card-author" title={video.author || '未知作者'}>
              <span className="video-card-avatar">
                {avatar && failedAvatar !== avatar
                  ? <img src={proxyImage(avatar)} alt="" loading="lazy" onError={() => setFailedAvatar(avatar)} />
                  : <UserRound size={14} aria-hidden="true" />}
              </span>
              <span>{video.author || '未知作者'}</span>
            </span>
            {published && <time dateTime={published.iso} title="发布时间（北京时间）">{published.text}</time>}
            {video.tname && <span className="video-card-category" title={video.tname}>{video.tname}</span>}
          </div>

          {video.description && video.description.trim() !== '-' && (
            <p className="video-card-description">{video.description}</p>
          )}

          <div className="video-card-metrics">
            <div className="video-card-primary-metrics">
              <div className="video-card-views"><span><Eye size={14} />播放量</span><strong>{video.views == null ? '—' : formatNumber(video.views)}</strong></div>
              <div className="video-card-rate"><span>播赞率</span><strong>{videoRate(video.likes, video.views)}</strong></div>
              <div className="video-card-rate"><span>播转率</span><strong>{videoRate(video.shares, video.views)}</strong></div>
            </div>
            <div className="video-card-secondary-metrics">
              <span><Subtitles size={14} />弹幕 <b>{video.danmaku == null ? '—' : formatNumber(video.danmaku)}</b></span>
              <span><MessageSquare size={14} />评论 <b>{video.comments == null ? '—' : formatNumber(video.comments)}</b></span>
              {statisticsTime && <span>数据观测 <time aria-label="统计观测时间" dateTime={statisticsTime.iso}
                title="统计观测时间（北京时间）">{statisticsTime.text}</time></span>}
              {observedOnline ? <span className={observedOnline.status === 'available' ? 'video-card-online' : ''}>
                <Users size={14} />{observedOnline.status === 'unavailable' ? '在看暂缺' :
                  `${observedOnline.status === 'stale' ? '历史在看' : '在看观测'} ${observedOnline.display}人`}
                {observedOnline.observed_at != null && <time title={`${observationTime(observedOnline.observed_at, true)}（北京时间）`}
                  dateTime={new Date(observedOnline.observed_at * 1000).toISOString()}>· {observationTime(observedOnline.observed_at)}</time>}
              </span> : hasOnline && <span className={historical ? '' : 'video-card-online'}><Users size={14} />{historical ? `最近观测 ${online}人` : `${online}人正在看`}</span>}
            </div>
          </div>

          {hasRadar && <div className="kb-video-radar-slot"><VideoRadar radar={video.radar} delay={staggerDelay} /></div>}
          {isDashboard && reasons}
          {isDashboard && <div className="video-card-inline-action">{trendButton}</div>}
        </div>

        {!isDashboard && <div className="video-card-footer">
          {reasons}
          <div className="video-card-actions">
            {hasRadar && isV2 && <button type="button" className="video-card-action video-card-radar-toggle"
              onClick={() => setShowPortrait(value => !value)} aria-expanded={showPortrait} aria-controls={`${panelId}-portrait`}>
              <TrendingUp size={17} /><span>{showPortrait ? '收起表现' : '视频表现'}</span>
            </button>}
            <button type="button" onClick={onFavorite} aria-pressed={Boolean(isFavorited)} className="video-card-action">
              {isFavorited ? <Bookmark size={17} fill="currentColor" /> : <BookmarkPlus size={17} />}<span>{isFavorited ? '已收藏' : '收藏'}</span>
            </button>
            <button type="button" onClick={() => setShowAiSum(value => !value)} aria-expanded={showAiSummary} aria-controls={`${panelId}-summary`} className="video-card-action">
              <Sparkles size={17} /><span>AI 总结</span>
            </button>
            {trendButton}
          </div>
        </div>}

        {showPortrait && <div id={`${panelId}-portrait`} className="video-card-panel video-card-mobile-portrait">
          <div className="flex justify-center py-3"><VideoRadar radar={video.radar} /></div>
        </div>}
        {expanded && <div id={`${panelId}-trend`} className="video-card-panel">
          <Suspense fallback={<p className="text-xs text-haze-400 py-6">加载趋势图表…</p>}><ObsTrendChart bvid={video.bvid} observedAt={video.observed_at} /></Suspense>
        </div>}
        {showAiSummary && <div id={`${panelId}-summary`} className="video-card-panel">
          <Suspense fallback={<p className="text-xs text-haze-400 py-6">AI 总结加载中…</p>}><AiSummary bvid={video.bvid} /></Suspense>
        </div>}
      </div>
    </article>
  )
}
