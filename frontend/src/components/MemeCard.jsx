import { BookmarkPlus, Bookmark, TrendingUp } from 'lucide-react'

export default function MemeCard({
  meme, index, trendColor, formatNumber,
  onFavorite, isFavorited, maxHeat = 100, staggerDelay = 0,
}) {
  const heatPct = maxHeat > 0 ? Math.min(100, (Number(meme.heat) || 0) / maxHeat * 100) : 0

  const chipCls = (label) => {
    const L = (label || '').trim()
    if (/爆|爆发|飙升/.test(L)) return 'kb-chip kb-chip--rose'
    if (/热|崛起|上升|涨/.test(L)) return 'kb-chip kb-chip--pink'
    if (/稳|持平/.test(L)) return 'kb-chip kb-chip--ghost'
    if (/凉|跌|下降/.test(L)) return 'kb-chip kb-chip--cyan'
    return 'kb-chip kb-chip--ghost'
  }

  return (
    <article className="kb-card kb-stagger p-4 md:p-[1.1rem]"
             style={{ animationDelay: `${staggerDelay}ms` }}>
      <div className="inner">
        <div className="flex items-start justify-between mb-3.5">
          <div className="flex items-start gap-3">
            <span className={
              'kb-rank ' +
              (index === 0 ? 'kb-rank--1'
               : index === 1 ? 'kb-rank--2'
               : index === 2 ? 'kb-rank--3'
               : 'kb-rank--n')
            }>{index + 1}</span>
            <div className="min-w-0">
              <h3 className="font-bold text-haze-50 text-[1.02rem]">{meme.keyword}</h3>
              <div className="mt-1.5">
                <span className={chipCls(meme.trend_label)}>{meme.trend_label}</span>
              </div>
            </div>
          </div>
          <button onClick={onFavorite} title="收藏热梗"
                  className={'kb-icon-btn shrink-0 ' +
                    (isFavorited ? '!text-primary-500 !bg-primary-50 opacity-100'
                                 : 'opacity-0 group-hover:opacity-100')}>
            {isFavorited ? <Bookmark size={17} fill="currentColor" /> : <BookmarkPlus size={17} />}
          </button>
        </div>

        {/* 热度条 */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="inline-flex items-center gap-1 text-haze-300">
              <TrendingUp size={13} className="text-neon-rose" />
              热度
            </span>
            <span className="kb-num text-neon-rose">{formatNumber(meme.heat)}</span>
          </div>
          <div className="relative w-full h-2 rounded-full bg-white/5 overflow-hidden">
            <div className="h-full rounded-full transition-all duration-700 ease-out
                            bg-gradient-to-r from-neon-pink via-neon-rose to-neon-amber
                            shadow-glow-pink"
                 style={{ width: `${heatPct}%` }} />
          </div>
        </div>

        {/* 相关视频 */}
        {meme.related_videos && meme.related_videos.length > 0 && (
          <div className="mt-4 pt-3.5 border-t border-white/5">
            <p className="text-[11px] uppercase tracking-wider text-haze-400 mb-2">· Related ·</p>
            <ul className="space-y-1">
              {meme.related_videos.slice(0, 2).map((v, i) => {
                const t = typeof v === 'string' ? v : v.title
                return (
                  <li key={i} className="text-xs text-haze-300 truncate flex gap-2" title={t}>
                    <span className="text-haze-500 shrink-0">›</span>
                    <span className="truncate">{t}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </article>
  )
}
