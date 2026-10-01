import { useEffect, useId, useMemo, useRef, useState } from 'react'

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

function axisTooltip(axis) {
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
  const axes = radar?.axes || []

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
      grid: [1 / 2, 1].map(level => pointText(outer.map(([x, y]) => [
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
  }, [axes, progress])

  if (!axes.length) return null

  const axisSummary = axes.map(axisTooltip).join('；')

  return (
    <div ref={rootRef} className={`relative w-[164px] h-[164px] shrink-0 select-none ${className}`}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="视频数据雷达图" aria-describedby={descriptionId} className="w-full h-full overflow-visible">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgb(var(--neon-rose))" stopOpacity="0.28" />
            <stop offset="100%" stopColor="rgb(var(--neon-pink))" stopOpacity="0.08" />
          </linearGradient>
        </defs>
        {grid.map((points, index) => (
          <polygon key={index} points={points} fill="none" stroke="currentColor" strokeWidth="0.8" className="text-haze-400/15" />
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
              <title>{axisTooltip(axis)}</title>
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
      <span id={descriptionId} className="sr-only">{axisSummary}</span>
    </div>
  )
}
