import { useState, useEffect } from 'react'
import { usePlayer } from '../utils/player'
import { X, Volume2, VolumeX, ExternalLink, Maximize2, Minimize2 } from 'lucide-react'

export default function MiniPlayer() {
  const player = usePlayer()
  const [isMuted, setIsMuted] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)

  if (!player.isOpen || !player.currentBvid) {
    return null
  }

  const embedUrl = `https://player.bilibili.com/player.html?bvid=${player.currentBvid}&autoplay=1&muted=${isMuted ? 1 : 0}&danmaku=1&high_quality=1`

  return (
    <div className="fixed bottom-6 right-6 z-50 shadow-2xl rounded-xl overflow-hidden bg-white border border-slate-200 transition-all duration-300"
      style={{ width: isExpanded ? '560px' : '320px' }}>
      <div className="relative">
        <div
          className="w-full bg-black"
          style={{ aspectRatio: '16/9' }}
          key={player.currentBvid}
        >
          <iframe
            src={embedUrl}
            title={player.currentTitle}
            className="w-full h-full"
            frameBorder="0"
            allow="autoplay; fullscreen; encrypted-media"
            allowFullScreen
          />
        </div>

        <div className="absolute top-2 right-2 flex gap-1">
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 bg-black/60 hover:bg-black/80 text-white rounded-md transition-colors"
            title={isExpanded ? '缩小' : '放大'}
          >
            {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button
            onClick={() => setIsMuted(!isMuted)}
            className="p-1.5 bg-black/60 hover:bg-black/80 text-white rounded-md transition-colors"
            title={isMuted ? '取消静音' : '静音'}
          >
            {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          <button
            onClick={player.closePlayer}
            className="p-1.5 bg-black/60 hover:bg-red-600 text-white rounded-md transition-colors"
            title="关闭（停止播放）"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="p-3 bg-white">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-slate-800 text-sm line-clamp-2">
              {player.currentTitle}
            </h4>
            <p className="text-xs text-slate-500 mt-1">
              {player.currentType === 'song' ? '🎵 BGM' : '🎬 视频预览'}
            </p>
          </div>

          <a
            href={`https://www.bilibili.com/video/${player.currentBvid}`}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 text-slate-400 hover:text-primary-500 hover:bg-primary-50 rounded-lg transition-colors flex-shrink-0"
            title="在B站打开"
          >
            <ExternalLink size={16} />
          </a>
        </div>

        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>点击 × 关闭即可停止</span>
          <span className="text-purple-600 font-medium">
            播放中
          </span>
        </div>
      </div>
    </div>
  )
}
