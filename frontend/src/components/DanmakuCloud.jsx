import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { EyeOff, X, SlidersHorizontal, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import { computeSpiralPositions } from '../utils/wordCloud'
import { useResizableHeight } from '../utils/useResizableHeight'

const COLORS = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308',
  '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  '#6366f1', '#8b5cf6', '#a855f7', '#ec4899',
]

function loadBlocked() {
  try {
    return JSON.parse(localStorage.getItem('danmaku_blocked') || '[]')
  } catch { return [] }
}

function saveBlocked(list) {
  localStorage.setItem('danmaku_blocked', JSON.stringify(list))
}

export default function DanmakuCloud({ words = [], large = false }) {
  const [blocked, setBlocked] = useState(loadBlocked)
  const [showManager, setShowManager] = useState(false)
  const [hoveredWord, setHoveredWord] = useState(null)
  const [hoveredRect, setHoveredRect] = useState(null)  // 词相对 viewport 的位置，用于在 viewport 层级渲染悬浮窗（不受 scale 影响）
  const hideTimer = useRef(null)
  const viewportRef = useRef(null)
  const containerRef = useRef(null)
  // 往下拉调整词云显示面积（只有 large 模式渲染 resizer）
  const { height: viewportH, startResize } = useResizableHeight(
    large ? 380 : 220,
    containerRef,
    viewportRef
  )

  // ── Zoom & pan ──
  const [scale, setScale] = useState(0.5)   // conservative default, auto-fits on mount
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef(null)

  // Delayed hide: 400ms grace period so user can move mouse to popup button
  const cancelHide = useCallback(() => {
    if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null }
  }, [])
  const scheduleHide = useCallback(() => {
    cancelHide()
    // 400ms grace period：给用户足够时间从词汇移动到悬浮窗的"屏蔽"按钮
    hideTimer.current = setTimeout(() => { setHoveredWord(null); setHoveredRect(null) }, 400)
  }, [cancelHide])
  const showWord = useCallback((word, element) => {
    cancelHide()
    // 用 span 获取精确的文字位置（而非外层 div），避免 div 的 line-height 导致悬浮窗离字太远
    const span = element?.querySelector?.('span') || element
    if (span && viewportRef.current) {
      const rect = span.getBoundingClientRect()
      const vpRect = viewportRef.current.getBoundingClientRect()
      setHoveredRect({
        left: rect.left - vpRect.left,
        top: rect.top - vpRect.top,
        width: rect.width,
        height: rect.height,
      })
    }
    setHoveredWord(word)
  }, [cancelHide])

  // Filter out blocked words
  const visible = useMemo(() => {
    const blockedSet = new Set(blocked)
    return words.filter(w => !blockedSet.has(w.word))
  }, [words, blocked])

  // Sort by count descending → most frequent placed at center by spiral algo
  const sorted = useMemo(() => {
    return [...visible].sort((a, b) => b.count - a.count)
  }, [visible])

  const maxCount = useMemo(() => {
    return Math.max(...sorted.map(w => w.count), 1)
  }, [sorted])

  // Font size: power curve for stronger differentiation between ranks
  const getFontSize = (count) => {
    const ratio = Math.pow(count / maxCount, 1.4)
    const base = large ? 14 : 11
    const range = large ? 54 : 38
    return base + ratio * range
  }

  const getOpacity = (count) => {
    return 0.55 + Math.pow(count / maxCount, 1.2) * 0.45
  }

  // Spiral layout: center = highest frequency
  const { positions, bbox } = useMemo(() => {
    if (sorted.length === 0) return { positions: [], bbox: { w: 0, h: 0, minX: 0, minY: 0 } }
    return computeSpiralPositions(
      sorted.map(w => ({ word: w.word, count: w.count })),
      getFontSize,
    )
  }, [sorted, maxCount])

  const cloudW = bbox.w + 80
  const cloudH = bbox.h + 80
  const offX = -bbox.minX + 40
  const offY = -bbox.minY + 40

  // ── Auto-fit scale ──
  // Estimate available viewport width so the cloud fits without scrolling.
  // Small mode: sidebar column ≈ 320px; large mode: full tab ≈ 1060px.
  // targetH 跟随 viewportH，这样往下拉扩大面积时词云自动放大填满新空间
  const autoScale = useMemo(() => {
    if (cloudW === 0) return 1
    const targetW = large ? 1040 : 320
    const targetH = viewportH
    const sW = (targetW - 24) / cloudW
    const sH = (targetH - 24) / cloudH
    return Math.min(sW, sH, 1)
  }, [cloudW, cloudH, large, viewportH])

  // Apply auto-scale on first mount / when cloud dimensions change
  useEffect(() => {
    if (cloudW > 0) {
      setScale(autoScale)
      setOffset({ x: 0, y: 0 })
    }
  }, [autoScale])

  // ── Zoom ──
  const clampScale = (s) => Math.max(0.15, Math.min(3, s))

  const zoomIn = () => setScale(s => clampScale(s * 1.25))
  const zoomOut = () => setScale(s => clampScale(s / 1.25))
  const zoomReset = () => {
    setScale(autoScale)
    setOffset({ x: 0, y: 0 })
  }

  // Wheel zoom toward cursor
  // 用 ref 保存最新 scale，避免 useEffect 依赖 scale 导致反复绑定/解绑
  const scaleRef = useRef(scale)
  useEffect(() => { scaleRef.current = scale }, [scale])

  // 手动绑定非被动 wheel 监听器：React 的 onWheel 在 Chrome 中默认 passive，
  // e.preventDefault() 不生效会导致页面跟着滚动。必须用 passive:false 才能阻止。
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return

    const onWheel = (e) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const cx = mx - rect.width / 2
      const cy = my - rect.height / 2

      const currentScale = scaleRef.current
      const factor = e.deltaY > 0 ? 0.9 : 1.1
      const newScale = Math.max(0.15, Math.min(3, currentScale * factor))
      const ratio = newScale / currentScale

      setOffset(prev => ({
        x: cx - ratio * (cx - prev.x),
        y: cy - ratio * (cy - prev.y),
      }))
      setScale(newScale)
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // ── Drag ──
  const handleMouseDown = useCallback((e) => {
    // Only start drag on background, not on word or popup
    if (e.target.closest('[data-word]')) return
    e.preventDefault()
    setDragging(true)
    dragStart.current = { x: e.clientX - offset.x, y: e.clientY - offset.y }
  }, [offset])

  const handleMouseMove = useCallback((e) => {
    if (!dragging || !dragStart.current) return
    setOffset({
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y,
    })
  }, [dragging])

  const handleMouseUp = useCallback(() => {
    setDragging(false)
    dragStart.current = null
  }, [])

  // ── Blocking ──
  const blockWord = (word) => {
    const next = [...blocked, word]
    setBlocked(next)
    saveBlocked(next)
    setHoveredWord(null)
  }

  const unblockWord = (word) => {
    const next = blocked.filter(w => w !== word)
    setBlocked(next)
    saveBlocked(next)
  }

  const unblockAll = () => {
    setBlocked([])
    saveBlocked([])
  }

  return (
    <div ref={containerRef} className={`bg-white rounded-xl border border-slate-200 overflow-hidden ${large ? 'min-h-[420px]' : ''} relative`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-100 gap-2">
        <span className="text-xs text-slate-400 flex-shrink-0">
          {visible.length} 词{blocked.length > 0 && ` · 屏蔽${blocked.length}`}
        </span>

        {/* Zoom controls */}
        <div className="flex items-center gap-0.5 flex-shrink-0">
          <button
            onClick={zoomOut} title="缩小"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          ><ZoomOut size={14} /></button>
          <span className="text-[10px] text-slate-400 w-10 text-center tabular-nums select-none">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={zoomIn} title="放大"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          ><ZoomIn size={14} /></button>
          <button
            onClick={zoomReset} title="重置"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors ml-0.5"
          ><RotateCcw size={13} /></button>
        </div>

        <button
          onClick={() => setShowManager(!showManager)}
          className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors flex-shrink-0 ${
            showManager || blocked.length > 0
              ? 'bg-amber-100 text-amber-700'
              : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100'
          }`}
        >
          <SlidersHorizontal size={12} />
          屏蔽管理
        </button>
      </div>

      {/* Blocked words manager */}
      {showManager && (
        <div className="mx-4 mt-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-slate-600">
              已屏蔽词汇 ({blocked.length})
            </span>
            {blocked.length > 0 && (
              <button onClick={unblockAll} className="text-xs text-red-500 hover:text-red-600">
                全部清空
              </button>
            )}
          </div>
          {blocked.length === 0 ? (
            <p className="text-xs text-slate-400">暂无屏蔽词，悬停词汇即可屏蔽</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {blocked.map(word => (
                <span key={word} className="inline-flex items-center gap-1 px-2 py-0.5 bg-white border border-slate-200 rounded text-xs text-slate-500 group">
                  <EyeOff size={10} className="text-slate-300" />
                  {word}
                  <button
                    onClick={() => unblockWord(word)}
                    className="ml-0.5 p-0.5 rounded hover:bg-red-50 hover:text-red-500 transition-colors"
                    title="取消屏蔽"
                  ><X size={10} /></button>
                </span>
              ))}
            </div>
          )}
          <p className="text-[10px] text-slate-400 mt-2">鼠标悬停任意词汇即可快速屏蔽</p>
        </div>
      )}

      {/* ── Viewport: fixed height, overflow hidden, handles zoom + pan ── */}
      <div
        ref={viewportRef}
        className="relative overflow-hidden select-none"
        style={{
          height: `${viewportH}px`,
          cursor: dragging ? 'grabbing' : 'grab',
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {sorted.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-slate-400 text-sm">
              {words.length === 0 ? '暂无数据' : '所有词汇已被屏蔽'}
            </p>
          </div>
        ) : (
          /* Anchor at viewport center — cloud translates & scales from there */
          <div style={{ position: 'absolute', left: '50%', top: '50%', width: 0, height: 0 }}>
            <div
              style={{
                position: 'absolute',
                width: `${cloudW}px`,
                height: `${cloudH}px`,
                transform: `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
              }}
            >
              {sorted.map((item, idx) => {
                const pos = positions[idx]
                if (!pos) return null

                const color = COLORS[idx % COLORS.length]
                const opacity = getOpacity(item.count)
                const isHovered = hoveredWord === item.word

                return (
                  <div
                    key={item.word}
                    data-word={item.word}
                    className="inline-block"
                    style={{
                      position: 'absolute',
                      left: `${offX + pos.x}px`,
                      top: `${offY + pos.y}px`,
                      transform: 'translate(-50%, -50%)',
                      zIndex: isHovered ? 10 : 0,
                    }}
                    onMouseEnter={(e) => showWord(item.word, e.currentTarget)}
                    onMouseLeave={scheduleHide}
                  >
                    <span
                      className="inline-block font-bold select-none cursor-pointer rounded px-1.5 py-0.5"
                      style={{
                        fontSize: `${pos.fontSize}px`,
                        color,
                        opacity: isHovered ? 1 : opacity,
                        transition: 'opacity 150ms',
                        whiteSpace: 'nowrap',
                      }}
                      title={`${item.word}: ${item.count} 次`}
                    >
                      {item.word}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Hover popup - 在 viewport 层级渲染，不受词云 scale/zoom 影响，大小始终固定 */}
        {hoveredWord && hoveredRect && (() => {
          const item = sorted.find(w => w.word === hoveredWord)
          if (!item) return null
          // 词太靠上时悬浮窗显示在下方，避免被 viewport overflow:hidden 裁剪导致看不到/点不到
          const showBelow = hoveredRect.top < 50
          const top = showBelow ? hoveredRect.top + hoveredRect.height : hoveredRect.top
          const transform = showBelow
            ? 'translate(-50%, 4px)'
            : 'translate(-50%, calc(-100% - 4px))'
          return (
            <div
              className="absolute z-30"
              style={{
                left: `${hoveredRect.left + hoveredRect.width / 2}px`,
                top: `${top}px`,
                transform,
              }}
              onMouseEnter={cancelHide}
              onMouseLeave={scheduleHide}
            >
              {showBelow && <div className="w-2 h-2 bg-slate-800 rotate-45 mx-auto -mb-1" />}
              <div className="bg-slate-800 text-white rounded-lg shadow-lg px-3 py-1.5 text-xs whitespace-nowrap flex items-center gap-2">
                <span>出现 {item.count} 次</span>
                <button
                  onClick={(e) => { e.stopPropagation(); blockWord(item.word) }}
                  className="flex items-center gap-1 px-1.5 py-0.5 bg-white/20 rounded hover:bg-white/30 transition-colors"
                >
                  <EyeOff size={10} />
                  屏蔽
                </button>
              </div>
              {!showBelow && <div className="w-2 h-2 bg-slate-800 rotate-45 mx-auto -mt-0.5" />}
            </div>
          )
        })()}
      </div>

      {/* 往下拉调整词云面积 - 只有 large 模式，最小=默认高度，最大=整个边框1:1 */}
      {large && (
        <div
          className="group flex items-center justify-center h-2 cursor-row-resize bg-slate-50 hover:bg-slate-100 transition-colors border-t border-slate-100"
          onMouseDown={startResize}
          title="往下拖动可扩大词云显示面积"
        >
          <div className="w-10 h-0.5 bg-slate-300 group-hover:bg-primary-400 rounded-full transition-colors" />
        </div>
      )}
    </div>
  )
}
