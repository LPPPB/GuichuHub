import { BookmarkPlus, Bookmark, Music, Play, Pause } from 'lucide-react'
import { usePlayer } from '../utils/player'
import { proxyImage } from '../utils/image'

export default function SongCard({
  song, index, trendColor, formatNumber,
  onFavorite, isFavorited, staggerDelay = 0,
}) {
  const player = usePlayer()
  const isCurrent = player.currentBvid === song.bvid && player.isOpen

  const handlePlay = (e) => {
    e.preventDefault(); e.stopPropagation()
    isCurrent ? player.closePlayer() : player.openPlayer({
      bvid: song.bvid, title: song.name, cover: song.cover, type: 'song',
    })
  }

  const chipCls = (label) => {
    const L = (label || '').trim()
    if (/爆|热|涨/.test(L)) return 'kb-chip kb-chip--pink'
    if (/崛起|爆发/.test(L)) return 'kb-chip kb-chip--rose'
    if (/凉|跌/.test(L)) return 'kb-chip kb-chip--cyan'
    return 'kb-chip kb-chip--ghost'
  }

  return (
    <div
      className={
        'kb-stagger group flex items-center gap-3 md:gap-4 px-3 md:px-4 py-3 rounded-2xl ' +
        'transition-all duration-200 cursor-pointer ' +
        (isCurrent
          ? 'bg-primary-50 shadow-[inset_0_0_0_1px_rgba(var(--bili-default),0.15)]'
          : 'hover:bg-white/5')
      }
      style={{ animationDelay: `${staggerDelay}ms` }}
      onClick={handlePlay}
    >
      {/* Top 排名 */}
      <div className="shrink-0 w-8 text-center">
        <span className={
          'kb-rank ' +
          (index === 0 ? 'kb-rank--1'
           : index === 1 ? 'kb-rank--2'
           : index === 2 ? 'kb-rank--3'
           : 'kb-rank--n')
        }>{index + 1}</span>
      </div>

      {/* 封面 */}
      <div className={
        'relative shrink-0 w-14 h-14 rounded-xl overflow-hidden ' +
        'bg-gradient-to-br from-bili-default via-neon-violet to-neon-cyan ' +
        'shadow-glow-pink flex items-center justify-center cursor-pointer group/cover'
      } onClick={handlePlay}>
        {song.cover ? (
          <img src={proxyImage(song.cover)} alt={song.name}
               className="w-full h-full object-cover group-hover/cover:scale-[1.05] duration-500" />
        ) : (
          <Music className="text-white/90 drop-shadow" size={20} />
        )}
        <div className={
          'absolute inset-0 flex items-center justify-center transition-all ' +
          (isCurrent ? 'bg-black/40' : 'bg-black/0 group-hover/cover:bg-black/25')
        }>
          {isCurrent ? (
            <div className="px-2.5 py-1.5 rounded-xl bg-white/90 backdrop-blur shadow-glow-pink">
              <div className="kb-eq" aria-hidden><span /><span /><span /></div>
            </div>
          ) : (
            <div className="w-9 h-9 rounded-full flex items-center justify-center bg-white/95
                            scale-75 opacity-0 group-hover/cover:scale-100 group-hover/cover:opacity-100
                            transition-all duration-300 shadow-glow-pink">
              <Play className="text-primary-500 translate-x-[1px]" size={15} />
            </div>
          )}
        </div>
        {isCurrent && (
          <div className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-primary-400" />
        )}
      </div>

      {/* 信息 */}
      <div className="flex-1 min-w-0" onClick={handlePlay}>
        <h4 className={
          'font-semibold text-[0.92rem] truncate leading-snug ' +
          (isCurrent ? 'text-primary-500' : 'text-haze-50 group-hover:text-primary-500') +
          ' transition-colors'
        }>{song.name}</h4>
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          <span className="text-xs text-haze-400 truncate max-w-[140px]">{song.author}</span>
          <span className={chipCls(song.trend_label)}>{song.trend_label}</span>
          {isCurrent && (
            <span className="text-[11px] font-medium text-primary-500 inline-flex items-center gap-1">
              <span className="w-1 h-1 rounded-full bg-primary-500 animate-pulse-dot" />
              NOW PLAYING
            </span>
          )}
        </div>
      </div>

      {/* 播放量 */}
      <div className="hidden sm:block text-right shrink-0 w-24 px-2">
        <p className="kb-num text-xs tabular-nums">{formatNumber(song.plays)}</p>
        <p className="text-[10.5px] text-haze-500 mt-0.5">播放</p>
      </div>

      {/* 收藏 */}
      <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
        <button onClick={onFavorite} title="收藏BGM"
                className={'kb-icon-btn ' +
                  (isFavorited ? '!text-primary-500 !bg-primary-50' : '')}>
          {isFavorited ? <Bookmark size={16} fill="currentColor" /> : <BookmarkPlus size={16} />}
        </button>
      </div>
    </div>
  )
}
