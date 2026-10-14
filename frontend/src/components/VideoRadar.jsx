import { useEffect, useId, useMemo, useRef, useState } from 'react'
import RadarDetails, { observationTime } from './RadarDetails'

const SIZE = 164
const CENTER = 82
const RADIUS = 52
const DURATION = 620

function polarPoint(index, total, radius) {
  const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total
  return [
    CENTER + Math.cos(angle) * radius,
    CENTER + Math.sin(angle) * radius,
  ]
}

function pointText(points) {
  return points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
}

function axisTooltip(axis, v2 = false) {
  if (v2) return `${axis.label}：${axis.score == null ? axis.reason || '暂无可信观测' : `${axis.score}分`}`
  if (axis.status !== 'available') return `${axis.label}：暂无实时观测`
  if (axis.id === 'reach' || axis.id === 'live') return `${axis.label}：${Number(axis.raw || 0).toLocaleString()}`
  if (axis.id === 'momentum') return `${axis.label}：${axis.score}`
  return `${axis.label}：${(Number(axis.raw || 0) * 100).toFixed(2)}%`
}

export default function VideoRadar({ radar, delay = 0, className = '' }) {
  const rootRef = useRef(null)
  const frameRef = useRef(null)
  const instanceId = useId().replace(/:/g, '')
  const gradientId = `video-radar-fill-${instanceId}`
  const descriptionId = `video-radar-description-${instanceId}`
  const [active, setActive] = useState(false)
  const [progress, setProgress] = useState(0)
  const [selected, setSelected] = useState(null)
  const axes = radar?.axes || []
  const v2 = radar?.algorithm_version === 'radar-v2'

  useEffect(() => {
    if (!selected) return undefined
    const outside = event => { if (!rootRef.current?.contains(event.target)) setSelected(null) }
    const escape = event => { if (event.key === 'Escape') setSelected(null) }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [selected])

  const reducedMotion = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    const node = rootRef.current
    if (!node || !axes.length) return undefined
    if (reducedMotion || typeof IntersectionObserver === 'undefined') {
      setActive(true)
      return undefined
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      setActive(true)
      observer.disconnect()
    }, { threshold: 0.2 })
    observer.observe(node)
    return () => observer.disconnect()
  }, [axes.length, reducedMotion])

  useEffect(() => {
    if (!active) return undefined
    if (reducedMotion) {
      setProgress(1)
      return undefined
    }
    let startedAt = null
    const timeout = window.setTimeout(() => {
      const animate = (timestamp) => {
        if (startedAt == null) startedAt = timestamp
        const elapsed = Math.min(1, (timestamp - startedAt) / DURATION)
        setProgress(1 - (1 - elapsed) ** 3)
        if (elapsed < 1) frameRef.current = window.requestAnimationFrame(animate)
      }
      frameRef.current = window.requestAnimationFrame(animate)
    }, Math.min(Math.max(0, delay), 350))
    return () => {
      window.clearTimeout(timeout)
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current)
    }
  }, [active, delay, reducedMotion])

  const { grid, spokes, outerPoints, dataPoints, dataPath, hasIncompleteData, labels } = useMemo(() => {
    const total = axes.length || 6
    const outer = Array.from({ length: total }, (_, index) => polarPoint(index, total, RADIUS))
    const data = axes.map((axis, index) => {
      if (axis.status !== 'available' || axis.score == null) return null
      const amount = axis.score / 100
      return polarPoint(index, total, RADIUS * amount * progress)
    })
    let nextPointStartsSegment = true
    const path = data.reduce((result, point) => {
      if (!point) {
        nextPointStartsSegment = true
        return result
      }
      const [x, y] = point
      const command = nextPointStartsSegment ? 'M' : 'L'
      nextPointStartsSegment = false
      return `${result}${command}${x.toFixed(2)},${y.toFixed(2)}`
    }, '')
    return {
      grid: (v2 ? [0.25, 0.5, 0.75, 1] : [1 / 2, 1]).map(level => pointText(outer.map(([x, y]) => [
        CENTER + (x - CENTER) * level,
        CENTER + (y - CENTER) * level,
      ]))),
      spokes: outer.map(point => [CENTER, CENTER, point[0], point[1]]),
      outerPoints: outer,
      dataPoints: data,
      dataPath: path,
      hasIncompleteData: data.some(point => point == null),
      labels: axes.map((axis, index) => ({ axis, point: polarPoint(index, total, RADIUS + 16) })),
    }
  }, [axes, progress, v2])

  if (!axes.length) return null

  const axisSummary = axes.map(axis => axisTooltip(axis, v2)).join('；')
  const selectedAxis = axes.find(axis => axis.id === selected?.id)

  return (
    <div ref={rootRef} className={`relative w-[164px] shrink-0 select-none ${v2 ? 'video-radar-v2' : 'h-[164px]'} ${className}`}
      onMouseLeave={() => setSelected(current => current?.pinned ? current : null)}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="视频数据雷达图" aria-describedby={descriptionId} className="w-full h-[164px] overflow-visible">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgb(var(--neon-rose))" stopOpacity="0.28" />
            <stop offset="100%" stopColor="rgb(var(--neon-pink))" stopOpacity="0.08" />
          </linearGradient>
        </defs>
        {grid.map((points, index) => (
          <polygon key={index} points={points} fill="none" stroke="currentColor" strokeWidth="0.8" className="text-haze-400/15" />
        ))}
        {v2 && [25, 50, 75, 100].map((value, index) => (
          <text key={value} x={CENTER + 4} y={CENTER - RADIUS * (index + 1) / 4 + 4}
            className="fill-haze-500" fontSize="8">{value}</text>
        ))}
        {spokes.map(([x1, y1, x2, y2], index) => (
          <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeWidth="0.8" className="text-haze-400/15" />
        ))}
        {hasIncompleteData ? (
          <path data-testid="radar-data-line" d={dataPath} fill="none" stroke="rgb(var(--neon-rose))" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <polygon data-testid="radar-data-polygon" points={pointText(dataPoints)} fill={`url(#${gradientId})`} stroke="rgb(var(--neon-rose))" strokeWidth="1.6" strokeLinejoin="round" />
        )}
        {labels.map(({ axis, point: [x, y] }) => (
          <text key={axis.id} x={x} y={y} textAnchor="middle" dominantBaseline="middle" className={axis.status === 'available' ? 'fill-haze-300' : 'fill-haze-500'} fontSize="9.5">
            {axis.label}
          </text>
        ))}
        {dataPoints.map((point, index) => {
          const axis = axes[index]
          const unavailable = axis.status !== 'available' || axis.score == null
          const [x, y] = point || outerPoints[index]
          return (
            <g key={axis.id}>
              <title>{axisTooltip(axis, v2)}</title>
              {unavailable ? (
                <>
                  <circle cx={x} cy={y} r="4" fill="rgb(var(--void-800))" stroke="rgb(var(--haze-500))" strokeWidth="1.2" opacity="0.9" />
                  <path d={`M${x - 1.6},${y - 1.6}L${x + 1.6},${y + 1.6}M${x + 1.6},${y - 1.6}L${x - 1.6},${y + 1.6}`} stroke="rgb(var(--haze-500))" strokeWidth="1" strokeLinecap="round" />
                </>
              ) : (
                <circle cx={x} cy={y} r="2.6" fill="rgb(var(--neon-rose))" />
              )}
              <circle cx={x} cy={y} r="9" fill="transparent" pointerEvents="all" />
            </g>
          )
        })}
      </svg>
      {v2 && labels.map(({ axis, point: [x, y] }) => <button key={axis.id} type="button"
        className="video-radar-hit" style={{ left: `${x / SIZE * 100}%`, top: `${y}px` }}
        aria-label={`${axis.label}详情`} aria-expanded={selected?.id === axis.id}
        aria-controls={`${descriptionId}-detail`}
        onMouseEnter={() => setSelected(current => current?.pinned ? current : { id: axis.id, pinned: false })}
        onClick={() => setSelected(current => current?.id === axis.id && current.pinned ? null : { id: axis.id, pinned: true })} />)}
      {v2 && <p className="text-center text-[9px] leading-4 text-haze-400 mt-1"><span>相对站内观测样本</span><br />观测 {observationTime(radar.observed_at)}</p>}
      {v2 && selectedAxis && <div id={`${descriptionId}-detail`} className="video-radar-detail"
        role="dialog" aria-label={selectedAxis.label}>
        <RadarDetails axis={selectedAxis} radar={radar} />
        <button type="button" onClick={() => setSelected(null)} className="text-bili-default mt-2">关闭详情</button>
      </div>}
      <span id={descriptionId} className="sr-only">{axisSummary}</span>
    </div>
  )
}
