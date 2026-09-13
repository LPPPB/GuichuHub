import { useState, useEffect } from 'react'
import { Sparkles, Clock, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { api } from '../utils/api'

export default function AiSummary({ bvid }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [outlineExpanded, setOutlineExpanded] = useState(false)

  useEffect(() => {
    if (!bvid) return
    let cancelled = false
    setLoading(true)
    setError(null)

    api.getVideoConclusion(bvid).then((res) => {
      if (cancelled) return
      if (res.success && res.data && res.data.summary) {
        setData(res.data)
      } else {
        setError(res.message || '暂无 AI 总结')
      }
    }).catch((e) => {
      if (!cancelled) setError('请求失败')
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })

    return () => { cancelled = true }
  }, [bvid])

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-3 text-sm text-slate-400">
        <div className="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
        AI 总结加载中...
      </div>
    )
  }

  if (error) {
    return (
      <div className="py-3 text-sm text-slate-400 flex items-center gap-2">
        <Sparkles size={14} className="text-slate-300" />
        {error}
      </div>
    )
  }

  if (!data || !data.summary) {
    return (
      <div className="py-3 text-sm text-slate-400 flex items-center gap-2">
        <Sparkles size={14} className="text-slate-300" />
        暂无 AI 总结
      </div>
    )
  }

  const outline = data.outline || []

  return (
    <div className="text-sm text-slate-700">
      {/* 摘要文本 */}
      <div className="flex items-start gap-2">
        <Sparkles size={16} className="text-purple-500 mt-0.5 flex-shrink-0" />
        <p className="leading-relaxed">{data.summary}</p>
      </div>

      {/* 大纲（折叠） */}
      {outline.length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setOutlineExpanded(!outlineExpanded)}
            className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-700 transition-colors"
          >
            {outlineExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {outlineExpanded ? '收起大纲' : `展开大纲（${outline.length} 章）`}
          </button>

          {outlineExpanded && (
            <div className="mt-2 space-y-2 pl-6 border-l-2 border-purple-100">
              {outline.map((section, i) => (
                <div key={i} className="text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-purple-600 font-medium">{section.title}</span>
                    {section.timestamp != null && (
                      <a
                        href={`https://www.bilibili.com/video/${bvid}?t=${section.timestamp}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-slate-400 hover:text-purple-500 transition-colors"
                        title="跳转到该时间点"
                      >
                        <Clock size={11} />
                        {formatTime(section.timestamp)}
                        <ExternalLink size={10} />
                      </a>
                    )}
                  </div>
                  {section.part_outline && section.part_outline.length > 0 && (
                    <div className="mt-1 space-y-0.5">
                      {section.part_outline.map((part, j) => (
                        <div key={j} className="flex items-baseline gap-2 text-slate-500">
                          <span className="w-1 h-1 rounded-full bg-slate-300 flex-shrink-0 mt-1.5" />
                          <span>{part.content}</span>
                          {part.timestamp != null && (
                            <a
                              href={`https://www.bilibili.com/video/${bvid}?t=${part.timestamp}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-slate-400 hover:text-purple-500 transition-colors flex-shrink-0"
                              title="跳转到该时间点"
                            >
                              <Clock size={10} />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function formatTime(seconds) {
  if (seconds == null) return ''
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}