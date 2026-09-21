import { useState, lazy, Suspense } from 'react'
import { BookmarkPlus, Bookmark, Eye, MessageSquare, Subtitles, Play, ExternalLink, Users, ThumbsUp, Share2, TrendingUp, Sparkles } from 'lucide-react'
import { proxyImage } from '../utils/image'
import VideoRadar from './VideoRadar'

const ObsTrendChart = lazy(() => import('./ObsTrendChart'))
const AiSummary   = lazy(() => import('./AiSummary'))

export default function VideoCard({
  video, index, trendColor, formatNumber,
  onFavorite, isFavorited, staggerDelay = 0,
}) {
  const [expanded, setExpanded]       = useState(false)
  const [showAiSummary, setShowAiSum] = useState(false)
  const videoUrl = video.url || `https://www.bilibili.com/video/${video.bvid}`

  const fmtDur = (sec) => {
    if (!sec) return '--:--'
    const m = Math.floor(sec / 60), s = sec % 60
    return `${m}:${String(s).padStart(2, '0')}`
  }
  const rate = (n, d) => (!n || !d ? '0.0' : ((n / d) * 100).toFixed(1))

  const chipCls = (label) => {
    const L = (label || '').trim()
    if (/爆|爆发|飙/.test(L)) return 'kb-chip kb-chip--rose'
    if (/热|涨|上升|崛起/.test(L)) return 'kb-chip kb-chip--pink'
    if (/稳|持平/.test(L)) return 'kb-chip kb-chip--ghost'
    if (/凉|跌|下降/.test(L)) return 'kb-chip kb-chip--cyan'
    return 'kb-chip kb-chip--ghost'
  }

  return (
    <article className="kb-card kb-stagger p-4 md:p-5"
             style={{ animationDelay: `${staggerDelay}ms` }}>
      <div className="inner">
        <a href={videoUrl} target="_blank" rel="noopener noreferrer" className="block group">
          <div className="flex flex-col sm:flex-row gap-4 md:gap-5">
            {/* 封面 */}
            <div className="relative w-[144px] h-[86px] md:w-44 md:h-24 shrink-0
                            rounded-xl overflow-hidden bg-void-700 group/cover">
              {video.cover ? (
                <img src={proxyImage(video.cover)} alt={video.title}
                     className="w-full h-full object-cover group-hover/cover:scale-[1.05] duration-500" />
              ) : null}
              <div className="absolute inset-0 flex items-center justify-center
                              bg-black/0 group-hover/cover:bg-black/30 transition-colors duration-300">
                <div className="w-11 h-11 rounded-full flex items-center justify-center
                                bg-white/90 backdrop-blur scale-75 opacity-0
                                group-hover/cover:scale-100 group-hover/cover:opacity-100
                                transition-all duration-300 shadow-glow-pink">
                  <Play className="text-primary-500 translate-x-[1px]" size={20} />
                </div>
              </div>
              <div className="absolute bottom-1.5 right-1.5 px-1.5 py-[2px] rounded-md
                              text-[10.5px] font-medium tabular-nums
                              bg-black/70 text-haze-50 backdrop-blur-[1px]">
                {fmtDur(video.duration)}
              </div>
            </div>

            {/* 信息 */}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2.5 min-w-0">
                  {index != null && (
                    <span className={
                      'kb-rank shrink-0 ' +
                      (index === 0 ? 'kb-rank--1'
                       : index === 1 ? 'kb-rank--2'
                       : index === 2 ? 'kb-rank--3'
                       : 'kb-rank--n')
                    }>{index + 1}</span>
                  )}
                  <h4 className="font-semibold text-haze-50 text-[0.95rem] leading-snug line-clamp-2 pt-[2px]
                                 group-hover:text-primary-500 transition-colors">
                    {video.title}
                  </h4>
                </div>
                <span className={chipCls(video.trend_label)}>{video.trend_label}</span>
              </div>

              <p className="text-xs text-haze-400 mt-1.5">
                UP主 · <span className="text-haze-300">{video.author}</span>
              </p>

              {video.description && (
                <p className="text-xs text-haze-300 mt-2 line-clamp-2">{video.description}</p>
              )}

              {/* 潜力/素材标签 */}
              <div className="flex flex-wrap gap-1.5 mt-3">
                {video.potential_score != null && (
                  <span className="kb-chip kb-chip--rose">
                    潜力 · {video.potential_reason || '潜力素材'}
                    <span className="font-semibold ml-0.5 kb-num">{video.potential_score}</span>
                  </span>
                )}
                {video.material_score != null && (
                  <span className="kb-chip kb-chip--cyan">
                    素材 · {video.material_reason || '素材价值'}
                    <span className="font-semibold ml-0.5 kb-num">{video.material_score}</span>
                  </span>
                )}
              </div>

              {/* 指标行 */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3.5 text-xs">
                <span className="flex items-center gap-1 text-haze-300">
                  <Eye size={13} /> 播放
                  <span className="kb-num ml-0.5">{formatNumber(video.views)}</span>
                </span>
                <span className="flex items-center gap-1 text-neon-cyan">
                  <Subtitles size={13} /> 弹幕
                  <span className="kb-num ml-0.5">{formatNumber(video.danmaku)}</span>
                </span>
                <span className="flex items-center gap-1 text-neon-emerald">
                  <MessageSquare size={13} /> 评论
                  <span className="kb-num ml-0.5">{formatNumber(video.comments)}</span>
                </span>
                {video.online_count > 0 && (
                  <span className="flex items-center gap-1 text-neon-rose">
                    <Users size={13} />
                    {video.online_display ? `${video.online_display} 正在看` : `${formatNumber(video.online_count)} 正在看`}
                    {video.online_circuit_skipped && <span className="text-[10px] text-neon-rose/50">(历史)</span>}
                  </span>
                )}
                {video.likes > 0 && (
                  <span className="flex items-center gap-1 text-haze-300">
                    <ThumbsUp size={13} /> 播赞
                    <span className="kb-num ml-0.5">{rate(video.likes, video.views)}%</span>
                  </span>
                )}
                {video.shares > 0 && (
                  <span className="flex items-center gap-1 text-haze-300">
                    <Share2 size={13} /> 播转
                    <span className="kb-num ml-0.5">{rate(video.shares, video.views)}%</span>
                  </span>
                )}
              </div>
            </div>

            {video.radar && (
              <div className="hidden lg:flex lg:w-[125px] lg:h-[125px] xl:w-[164px] xl:h-[164px] items-center justify-center shrink-0">
                <VideoRadar
                  radar={video.radar}
                  potentialScore={video.potential_score}
                  delay={staggerDelay}
                  className="origin-top-left scale-[0.76] xl:scale-100"
                />
              </div>
            )}

            {/* 右侧工具列 */}
            <div className="hidden sm:flex flex-col gap-1 shrink-0 -mr-1"
                 onClick={(e) => { e.preventDefault(); e.stopPropagation() }}>
              <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); onFavorite && onFavorite() }}
                      title="收藏"
                      className={'kb-icon-btn ' + (isFavorited ? '!text-primary-500 !bg-primary-50' : '')}>
                {isFavorited ? <Bookmark size={17} fill="currentColor" /> : <BookmarkPlus size={17} />}
              </button>
              <button onClick={(e) => { e.stopPropagation(); e.preventDefault(); window.open(videoUrl, '_blank') }}
                      title="在 B 站打开" className="kb-icon-btn">
                <ExternalLink size={17} />
              </button>
              <button onClick={(e) => { e.stopPropagation(); e.preventDefault(); setShowAiSum(s => !s) }}
                      title="AI 总结"
                      className={'kb-icon-btn ' + (showAiSummary ? '!text-neon-violet !bg-neon-violet/10' : '')}>
                <Sparkles size={17} />
              </button>
              <button onClick={(e) => { e.stopPropagation(); e.preventDefault(); setExpanded(e => !e) }}
                      title="观测趋势"
                      className={'kb-icon-btn ' + (expanded ? '!text-neon-cyan !bg-neon-cyan/10' : '')}>
                <TrendingUp size={17} />
              </button>
            </div>
          </div>
        </a>

        {video.radar && (
          <div className="lg:hidden flex justify-center mt-3 pt-3 border-t border-white/5">
            <VideoRadar radar={video.radar} potentialScore={video.potential_score} delay={staggerDelay} />
          </div>
        )}

        {expanded && (
          <div onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
               className="mt-4 pt-4 border-t border-white/5">
            <Suspense fallback={
              <div className="flex items-center justify-center py-8 text-xs text-haze-400">
                <div className="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin mr-2" />
                加载趋势图表…
              </div>
            }>
              <ObsTrendChart bvid={video.bvid} />
            </Suspense>
          </div>
        )}
        {showAiSummary && (
          <div onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
               className="mt-4 pt-4 border-t border-white/5">
            <Suspense fallback={
              <div className="flex items-center py-3 text-xs text-haze-400">
                <div className="w-4 h-4 border-2 border-neon-violet border-t-transparent rounded-full animate-spin mr-2" />
                AI 总结加载中…
              </div>
            }>
              <AiSummary bvid={video.bvid} />
            </Suspense>
          </div>
        )}

        {/* 移动端工具条 */}
        <div className="sm:hidden flex justify-between items-center mt-3 pt-3 border-t border-white/5">
          <div className="flex items-center gap-0.5">
            <button onClick={onFavorite}
                    className={'kb-icon-btn ' + (isFavorited ? '!text-primary-500 !bg-primary-50' : '')} title="收藏">
              {isFavorited ? <Bookmark size={16} fill="currentColor" /> : <BookmarkPlus size={16} />}
            </button>
            <button onClick={() => window.open(videoUrl, '_blank')} className="kb-icon-btn" title="在B站打开">
              <ExternalLink size={16} />
            </button>
          </div>
          <div className="flex items-center gap-0.5">
            <button onClick={() => setShowAiSum(s => !s)}
                    className={'kb-icon-btn ' + (showAiSummary ? '!text-neon-violet !bg-neon-violet/10' : '')} title="AI总结">
              <Sparkles size={16} />
            </button>
            <button onClick={() => setExpanded(e => !e)}
                    className={'kb-icon-btn ' + (expanded ? '!text-neon-cyan !bg-neon-cyan/10' : '')} title="趋势">
              <TrendingUp size={16} />
            </button>
          </div>
        </div>
      </div>
    </article>
  )
}
