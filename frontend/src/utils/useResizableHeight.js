import { useState, useRef, useEffect, useCallback } from 'react'

/**
 * 往下拉调整高度的 hook（只往下拉，不能往上拉）。
 *
 * 约束：
 *   - 最小高度 = defaultH（当前默认状态，不能往上拉）
 *   - 最大高度 = 整个容器 1:1（容器宽度 - 非 viewport 部分高度）
 *   - 只改变下方高度，左右和上面不动
 *
 * @param {number} defaultH - 默认高度（最小高度）
 * @param {React.RefObject} containerRef - 整个边框容器的 ref（用于计算 1:1 最大高度）
 * @param {React.RefObject} viewportRef - viewport 区域的 ref（用于计算非 viewport 部分高度）
 * @returns {{ height, startResize, resizing, resetHeight, extraHeight }}
 */
export function useResizableHeight(defaultH, containerRef, viewportRef) {
  const [extraHeight, setExtraHeight] = useState(0)
  const [resizing, setResizing] = useState(false)
  // 拖拽起点 + 拖拽时计算的几何信息（避免每次 mousemove 都读 DOM）
  const resizeStart = useRef({ y: 0, h: 0, nonViewportH: 0, maxContainerW: 0 })

  const startResize = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    const container = containerRef.current
    const viewport = viewportRef.current
    let nonViewportH = 0
    let maxContainerW = defaultH
    if (container && viewport) {
      const cRect = container.getBoundingClientRect()
      const vRect = viewport.getBoundingClientRect()
      // 非 viewport 部分（header + toolbar + resizer 等）= 容器总高 - viewport 高
      nonViewportH = cRect.height - vRect.height
      // 1:1 = 整个容器高度 = 容器宽度
      maxContainerW = cRect.width
    }
    setResizing(true)
    resizeStart.current = { y: e.clientY, h: extraHeight, nonViewportH, maxContainerW }
  }, [extraHeight, containerRef, viewportRef, defaultH])

  useEffect(() => {
    if (!resizing) return
    const onMove = (e) => {
      const delta = e.clientY - resizeStart.current.y
      const newH = resizeStart.current.h + delta
      // 最大 viewport 高度 = 容器宽度(1:1) - 非 viewport 部分
      const maxViewportH = resizeStart.current.maxContainerW - resizeStart.current.nonViewportH
      const maxExtra = Math.max(0, maxViewportH - defaultH)
      // 只往下拉：最小 0（默认高度），最大 maxExtra（1:1）
      const clamped = Math.max(0, Math.min(newH, maxExtra))
      setExtraHeight(clamped)
    }
    const onUp = () => setResizing(false)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [resizing, defaultH])

  const resetHeight = useCallback(() => setExtraHeight(0), [])

  return {
    height: defaultH + extraHeight,
    startResize,
    resizing,
    resetHeight,
    extraHeight,
  }
}
