import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react'

// ─── Mock ECharts 模块（jsdom 无 canvas，避免真实渲染）───
// 导出需与 src/lib/echarts.js 注册列表保持一致（charts/components/renderers），
// vitest v4 对 mock 未返回的命名导出严格校验，缺一个即报 "No X export"。
vi.mock('echarts/core', () => ({ use: vi.fn() }))
vi.mock('echarts/charts', () => ({ LineChart: {}, BarChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, TooltipComponent: {}, LegendComponent: {} }))
vi.mock('echarts/renderers', () => ({ SVGRenderer: {} }))
vi.mock('echarts-for-react', () => ({
  // 透传 series 数量，便于断言指标叠加效果
  default: (props) => (
    <div
      data-testid="echarts"
      data-series-count={props.option?.series?.length ?? 0}
      data-series={JSON.stringify(props.option?.series ?? [])}
    />
  ),
}))

vi.mock('../utils/api', () => ({
  api: {
    getVideoObsTrend: vi.fn(),
  },
}))

import ObsTrendChart from './ObsTrendChart'
import { api } from '../utils/api'

// 4 个观测点，第 3 个 online_count=null（模拟抓取失败，验证断点处理）
const mockPoints = [
  { ts: 1700000000, views: 1000, likes: 50, coins: 10, favorites: 20, shares: 5, comments: 30, danmaku: 40, online_count: 100, potential_score: 60 },
  { ts: 1700001800, views: 2000, likes: 80, coins: 20, favorites: 40, shares: 10, comments: 50, danmaku: 60, online_count: 150, potential_score: 65 },
  { ts: 1700003600, views: 3500, likes: 120, coins: 30, favorites: 60, shares: 15, comments: 70, danmaku: 80, online_count: null, potential_score: 70 },
  { ts: 1700005400, views: 5000, likes: 150, coins: 40, favorites: 80, shares: 20, comments: 90, danmaku: 100, online_count: 200, potential_score: 75 },
]

describe('ObsTrendChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('挂载时以 bvid 和 hours=48 调用 API', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx411c7mD" />)
    expect(api.getVideoObsTrend).toHaveBeenCalledWith('BV1xx411c7mD', 48)
    // 等待异步加载完成，避免 setState 在测试外触发 act() 警告
    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })
  })

  it('加载中显示 loading 状态', async () => {
    api.getVideoObsTrend.mockReturnValue(new Promise(() => {}))  // 永不 resolve
    render(<ObsTrendChart bvid="BV1xx" />)
    expect(screen.getByText('加载观测数据...')).toBeInTheDocument()
  })

  it('正常数据渲染 ECharts 和三个指标按钮，默认播放量单线', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })

    // 三个指标按钮
    expect(screen.getByText('播放量')).toBeInTheDocument()
    expect(screen.getByText('同接')).toBeInTheDocument()
    expect(screen.getByText('互动率')).toBeInTheDocument()

    // 观测点数提示
    expect(screen.getByText(/近 48 小时观测.*4 个点/)).toBeInTheDocument()

    // 默认仅播放量 → 1 条线
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('1')
  })

  it('观测点不足 3 个时显示"数据积累中"且不渲染图表', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints.slice(0, 2), count: 2 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByText(/数据积累中/)).toBeInTheDocument()
    })
    expect(screen.getByText(/当前 2 个观测点/)).toBeInTheDocument()
    expect(screen.queryByTestId('echarts')).not.toBeInTheDocument()
  })

  it('API reject 时显示错误信息', async () => {
    api.getVideoObsTrend.mockRejectedValue(new Error('网络错误'))
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByText('网络错误')).toBeInTheDocument()
    })
  })

  it('success:false 时显示后端返回的错误信息', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: false, message: '视频不存在' })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByText('视频不存在')).toBeInTheDocument()
    })
  })

  it('点击"同接"按钮叠加显示双指标', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('1')

    fireEvent.click(screen.getByText('同接'))
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('2')
  })

  it('点击"互动率"叠加第三条线', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('同接'))
    fireEvent.click(screen.getByText('互动率'))
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('3')
  })

  it('再次点击已选指标取消该线', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })

    // 取消播放量 → 0 条线
    fireEvent.click(screen.getByText('播放量'))
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('0')
  })

  it('同一 bvid 不重复加载（loadedRef 防重）', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    const { rerender } = render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(api.getVideoObsTrend).toHaveBeenCalledTimes(1)
    })

    rerender(<ObsTrendChart bvid="BV1xx" />)
    expect(api.getVideoObsTrend).toHaveBeenCalledTimes(1)
  })

  it('含 online_count=null 的数据点也能正常渲染', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints, count: 4 } })
    render(<ObsTrendChart bvid="BV1xx" />)

    await waitFor(() => {
      expect(screen.getByTestId('echarts')).toBeInTheDocument()
    })

    // 切换到同接（含 null 点），渲染不崩溃
    fireEvent.click(screen.getByText('同接'))
    expect(screen.getByTestId('echarts').dataset.seriesCount).toBe('2')
  })

  it('refreshes the curve when the same video receives a newer statistics observation', async () => {
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints } })
    const { rerender } = render(<ObsTrendChart bvid="BVsame" observedAt={1700000000} />)
    await screen.findByTestId('echarts')
    api.getVideoObsTrend.mockResolvedValue({ success: true, data: { points: mockPoints.map(p => ({ ...p, views: 245764 })) } })
    rerender(<ObsTrendChart bvid="BVsame" observedAt={1700001800} />)
    await waitFor(() => {
      const series = JSON.parse(screen.getByTestId('echarts').dataset.series)
      expect(series[0].data.at(-1)[1]).toBe(245764)
    })
  })

  it('switches videos and ignores the previous video request finishing late', async () => {
    let finishOld
    api.getVideoObsTrend.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce({ success: true, data: { points: mockPoints.map(p => ({ ...p, views: 9999 })) } })
    const { rerender } = render(<ObsTrendChart bvid="BVold" />)
    rerender(<ObsTrendChart bvid="BVnew" />)
    await screen.findByTestId('echarts')
    await act(async () => { finishOld({ success: true, data: { points: mockPoints } }) })
    await waitFor(() => {
      const series = JSON.parse(screen.getByTestId('echarts').dataset.series)
      expect(series[0].data.at(-1)[1]).toBe(9999)
    })
  })

  it('plots zero interaction as zero and leaves incomplete or invalid interaction points missing', () => {
    const zero = { ts: 1700000000, views: 1000, likes: 0, coins: 0, favorites: 0, shares: 0 }
    const points = [zero, { ...zero, ts: zero.ts+1, likes: 1, shares: null },
      { ...zero, ts: zero.ts+2, views: 0 }, { ...zero, ts: zero.ts+3, coins: -1 },
      { ...zero, ts: zero.ts+4, likes: 100, shares: 10 }]
    render(<ObsTrendChart points={points} />)
    fireEvent.click(screen.getByText('互动率'))
    const series = JSON.parse(screen.getByTestId('echarts').dataset.series)
    expect(series.find(s => s.name === '互动率').data.map(p => p[1])).toEqual([0, null, null, null, 11])
  })
})
