import { ThumbsUp, Quote, ExternalLink, MessageSquare, MapPin, BadgeCheck, Heart } from 'lucide-react'
import { proxyImage } from '../utils/image'

export default function CommentList({ comments = [], formatNumber, compact = false }) {
  return (
    <div className="kb-card overflow-hidden">
      <div className="inner">
        {comments.length === 0 ? (
          <div className="p-6 text-center text-haze-400">暂无数据</div>
        ) : (
          <div className="divide-y divide-white/5">
            {comments.map((comment, idx) => {
              const videoUrl = comment.source_bvid
                ? `https://www.bilibili.com/video/${comment.source_bvid}/${comment.rpid ? `#reply${comment.rpid}` : ''}`
                : null

              // compact 模式（总览侧栏）：左侧封面缩略图 + 评论内容，密度低但保留封面
              if (compact) {
                const cover = (
                  <div className="relative shrink-0 w-20 h-[45px] rounded-lg overflow-hidden bg-void-700 mt-0.5">
                    {comment.source_cover && (
                      <img
                        src={proxyImage(comment.source_cover)}
                        alt={comment.source_video || ''}
                        className="w-full h-full object-cover"
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                    )}
                  </div>
                )
                return (
                  <div key={`${comment.source_bvid}-${idx}`}>
                    {videoUrl ? (
                      <a
                        href={videoUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex gap-3 p-4 hover:bg-white/5 transition-colors group cursor-pointer"
                        title={`点击跳转到原视频：${comment.source_video || ''}`}
                      >
                        {cover}
                        <div className="flex-1 min-w-0">
                          <CommentContent comment={comment} formatNumber={formatNumber} link compact />
                        </div>
                      </a>
                    ) : (
                      <div className="flex gap-3 p-4 hover:bg-white/5 transition-colors">
                        {cover}
                        <div className="flex-1 min-w-0">
                          <CommentContent comment={comment} formatNumber={formatNumber} compact />
                        </div>
                      </div>
                    )}
                  </div>
                )
              }

              return (
                <div key={`${comment.source_bvid}-${idx}`} className="flex">
                  {/* Left: Comment content */}
                  <div className="flex-1 min-w-0">
                    {videoUrl ? (
                      <a
                        href={videoUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block p-4 hover:bg-white/5 transition-colors group cursor-pointer h-full"
                        title={`点击跳转到原视频：${comment.source_video || ''}`}
                      >
                        <CommentContent comment={comment} formatNumber={formatNumber} link />
                      </a>
                    ) : (
                      <div className="p-4 hover:bg-white/5 transition-colors h-full">
                        <CommentContent comment={comment} formatNumber={formatNumber} />
                      </div>
                    )}
                  </div>

                  {/* Right: Video cover + title */}
                  {comment.source_cover && (
                    <div className="flex-shrink-0 w-40 p-4 border-l border-white/5 bg-white/[0.02] flex flex-col items-center gap-1.5">
                      <img
                        src={proxyImage(comment.source_cover)}
                        alt={comment.source_video || ''}
                        className="w-full aspect-video object-cover rounded-md bg-white/10"
                        onError={(e) => { e.target.style.display = 'none' }}
                      />
                      {comment.source_video && (
                        <p className="text-[10px] text-haze-400 text-center leading-tight line-clamp-2">
                          {comment.source_video}
                        </p>
                      )}
                      {videoUrl && (
                        <a
                          href={videoUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-primary-500 hover:text-primary-600 flex items-center gap-0.5 mt-auto"
                        >
                          去观看 <ExternalLink size={9} />
                        </a>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function CommentContent({ comment, formatNumber, link, compact = false }) {
  return (
    <div className="flex gap-3">
      <Quote className="text-neon-amber flex-shrink-0 mt-1" size={18} />
      <div className="flex-1 min-w-0">
        {/* 徽章行：官方热门 + UP主觉得很赞 */}
        {(comment.is_hot || comment.up_liked) && (
          <div className="flex items-center gap-1.5 mb-1.5">
            {comment.is_hot && (
              <span className="kb-chip kb-chip--rose">
                <BadgeCheck size={10} />
                官方热门
              </span>
            )}
            {comment.up_liked && (
              <span className="kb-chip kb-chip--amber">
                <Heart size={10} />
                UP主觉得很赞
              </span>
            )}
          </div>
        )}

        {/* 评论正文（表情渲染） */}
        <p className={`text-haze-100 leading-relaxed ${link ? 'group-hover:text-haze-50' : ''}`}>
          <CommentMessage message={comment.content} emotes={comment.emotes} />
        </p>

        {/* 元信息行：头像 + 昵称 + 等级 + IP属地 + 时间 */}
        <div className="flex items-center gap-2 mt-2 text-xs text-haze-400">
          {(comment.author_avatar || comment.author) && (
            <span className="flex items-center gap-1.5 min-w-0">
              {comment.author_avatar && (
                <img
                  src={proxyImage(comment.author_avatar)}
                  alt={comment.author || '用户'}
                  className="w-5 h-5 rounded-full bg-white/10 flex-shrink-0"
                  onError={(e) => { e.target.style.display = 'none' }}
                />
              )}
              <span className="font-medium text-haze-300 truncate max-w-[140px]">
                {comment.author}
              </span>
              {comment.author_level > 0 && !compact && (
                <span className="inline-flex items-center text-[9px] px-1.5 py-px rounded bg-white/5 text-neon-cyan border border-white/10 flex-shrink-0">
                  LV{comment.author_level}
                </span>
              )}
            </span>
          )}
          {comment.location && (
            <span className="flex items-center gap-0.5 text-haze-500 flex-shrink-0">
              <MapPin size={10} />
              {comment.location.replace('IP属地：', '')}
            </span>
          )}
          {comment.time > 0 && (
            <span className="flex-shrink-0 text-haze-500">{formatRelativeTime(comment.time)}</span>
          )}
        </div>

        {/* 互动数据 + 来源 */}
        <div className="flex items-center gap-3 mt-1.5 text-xs text-haze-400">
          <span className="flex items-center gap-1 flex-shrink-0">
            <ThumbsUp size={12} />
            {formatNumber(comment.likes)}
          </span>
          {comment.replies > 0 && (
            <span className="flex items-center gap-1 flex-shrink-0">
              <MessageSquare size={12} />
              {formatNumber(comment.replies)} 回复
            </span>
          )}
          {link && comment.source_video && (
            <span className="text-neon-cyan group-hover:text-primary-500 truncate flex items-center gap-1 min-w-0">
              {comment.source_video}
              <ExternalLink size={10} className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * 渲染评论正文，把 [表情] 文本替换为 emote 图片（借鉴 biliscope drawHotComment）。
 * message 按表情文本分割，非表情部分为纯文本，表情部分渲染 <img>。
 */
function CommentMessage({ message = '', emotes = {} }) {
  if (!message) return null
  const keys = Object.keys(emotes || {})
  if (keys.length === 0) return message

  // 转义特殊字符后按表情文本分割
  const regexStr = keys.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  if (!regexStr) return message

  const parts = message.split(new RegExp(`(${regexStr})`))
  return (
    <>
      {parts.map((part, i) => {
        if (emotes[part]) {
          return (
            <img
              key={i}
              src={proxyImage(emotes[part])}
              alt={part}
              className="inline-block w-4 h-4 align-middle mx-0.5"
            />
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return ''
  const diff = Math.floor(Date.now() / 1000) - timestamp
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 172800) return '昨天'
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`
  const d = new Date(timestamp * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
