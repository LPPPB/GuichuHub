// ECharts 薄包装组件：统一容器/渲染配置，各图表组件只需传 option。
// 用法：<EChart option={option} height={200} />
// 模块注册统一在 lib/echarts.js 完成（本文件副作用导入保证注册先于渲染）。
import { useEffect, useRef, useState } from 'react'
import PublicChartSummary from '../publicPages/PublicChartSummary'
import ReactECharts from 'echarts-for-react'
import '../lib/echarts'

export default function EChart({ option, height = 200, fill = false, className = '', onEvents }) {
  const chartRef = useRef(null)
  const wrapRef = useRef(null)
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  // 容器尺寸变化时自动 resize：echarts-for-react 只监听 window resize，
  // 无法感知父容器宽高动画（如 StatCard Size Morph 展开），否则图表会停留在
  // 初始化时的小宽度，右侧留白。用 ResizeObserver + rAF 防抖跟随容器变化。
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap || typeof ResizeObserver === 'undefined') return
    let raf = 0
    const resize = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const inst = chartRef.current?.getEchartsInstance?.()
        if (inst && typeof inst.resize === 'function') {
          // 传入显式尺寸，避免 echarts-for-react 的内部 size-sensor 在
          // 父级 morph 的首帧把图表锁死在其最小内容尺寸。
          const { width, height } = wrap.getBoundingClientRect()
          inst.resize({ width: Math.round(width), height: Math.round(height) })
        }
      })
    }
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)
    // 展开卡的父级尺寸由 Framer Motion 连续改变。某些浏览器下，
    // ReactECharts 的内部 size-sensor 会在动画第一帧以极小尺寸初始化，
    // 却不会再触发自身的 window resize 监听；在动画起点和稳定后各补一次。
    resize()
    const settleTimers = [80, 320, 700].map((delay) => setTimeout(resize, delay))
    return () => {
      cancelAnimationFrame(raf)
      settleTimers.forEach(clearTimeout)
      ro.disconnect()
    }
  }, [])

  if (!option) return null
  // fill 模式：父容器为 flex 时弹性铺满剩余空间（SVG 随容器尺寸变化自动 resize），
  // 避免 height 固定像素与父容器实际高度不一致导致 SVG 与 div 尺寸错位
  const wrapStyle = fill
    // `flex: 1` 算出的高度不会让子元素的 `height: 100%` 一定获得
    // 可解析的百分比高度；显式继承父面板高度，避免展开态 SVG 在 89×6px
    // 的初始尺寸上渲染后一直不再铺开。
    ? { flex: '1 1 0%', minHeight: 0, width: '100%', height: '100%' }
    : { width: '100%', height }
  return (
    <div ref={wrapRef} style={wrapStyle}>
      {!mounted ? <PublicChartSummary items={(Array.isArray(option.series) ? option.series : [option.series]).flatMap(series => {
        if (!series || !Array.isArray(series.data)) return []
        const x = Array.isArray(option.xAxis) ? option.xAxis[0] : option.xAxis
        const y = Array.isArray(option.yAxis) ? option.yAxis[0] : option.yAxis
        const labels = y?.type === 'category' ? y.data : x?.data
        return series.data.slice(0, 20).map((point,index) => ({
          label: String(point?.name ?? labels?.[index] ?? series.name ?? index + 1),
          value: typeof point === 'number' || typeof point === 'string' ? point : typeof point?.value === 'number' ? point.value : null,
        }))
      })} /> : <ReactECharts
        ref={chartRef}
        option={option}
        style={{ height: '100%', width: '100%' }}
        opts={{ renderer: 'svg' }}
        // 尺寸由上面的 ResizeObserver 统一管理；默认 size-sensor 在父级
        // 尺寸动画中会读到中间态并覆盖正确尺寸。
        autoResize={false}
        notMerge
        onEvents={onEvents}
        className={className}
      />}
    </div>
  )
}
