// @vitest-environment node
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import * as echarts from 'echarts'
import { JSDOM } from 'jsdom'

// The DOM wrapper needs a browser. Capture its input, then render that exact
// option through the real SVG engine (including its label collision layout).
const boundary = vi.hoisted(() => ({ option: null }))
vi.mock('./EChart', () => ({ default: ({ option }) => { boundary.option = option; return null } }))
vi.mock('../utils/api', () => ({ api: {} }))
import { KichuRatioCard, ActiveUpCard } from './TrendCharts'

const batches = Array.from({ length: 20 }, (_, index) => ({
  created_at: 1790000000 + index * 86400,
  analysis: { summary: {
    total_ups: 10, active_up_count: 5,
    total_videos: 1000, kichu_video_count: index === 19 ? 421 : 554,
  } },
}))

function cardOption(Component, data = batches) {
  boundary.option = null
  renderToStaticMarkup(<Component batches={data} />)
  return boundary.option
}

function labels(chart) {
  const doc = new JSDOM(chart.renderToSVGString(), { contentType: 'image/svg+xml' }).window.document
  return [...doc.querySelectorAll('text')].filter(node => node.style.fontWeight === '600').map(node => ({
    text: node.textContent, color: node.getAttribute('fill'),
  }))
}

function svgChart(option, width = 740) {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width, height: 200 })
  chart.setOption({ ...option, animation: false })
  return chart
}

describe('鬼畜视频占比显示回归', () => {
  it('折线、数字、面积渐变统一蓝色，不再残留粉色', () => {
    const option = cardOption(KichuRatioCard)
    const chart = svgChart(option)
    try {
      expect(labels(chart).length).toBeGreaterThan(0)
      expect(labels(chart).every(label => label.color === '#00AEEC')).toBe(true)
      const svg = chart.renderToSVGString()
      expect(svg).toContain('stop-color="rgb(0,174,236)"')
      expect(svg).not.toContain('#be185d')
    } finally { chart.dispose() }
  })

  it('窄屏减少拥挤标签，保留最新值，拉宽后恢复更多标签', () => {
    const chart = svgChart(cardOption(KichuRatioCard), 1400)
    try {
      const wide = labels(chart)
      chart.resize({ width: 280, height: 200 })
      const narrow = labels(chart)
      expect(narrow.length).toBeLessThan(wide.length)
      expect(narrow.some(label => label.text === '42.1%')).toBe(true)
      chart.resize({ width: 1400, height: 200 })
      expect(labels(chart).length).toBe(wide.length)
    } finally { chart.dispose() }
  })

  it('最新点与历史点同高度且互相挤占时仍优先保留最新值', () => {
    const sameLevel = batches.map(batch => ({ ...batch,
      analysis: { summary: { ...batch.analysis.summary, kichu_video_count: 554 } },
    }))
    const chart = svgChart(cardOption(KichuRatioCard, sameLevel), 180)
    try {
      const lastX = chart.convertToPixel({ xAxisIndex: 0 }, 19)
      const doc = new JSDOM(chart.renderToSVGString(), { contentType: 'image/svg+xml' }).window.document
      const visible = [...doc.querySelectorAll('text')].filter(node => node.style.fontWeight === '600')
      expect(visible.length).toBeLessThan(20)
      expect(visible.some(node => node.textContent === '55.4%' &&
        Math.abs(Number(node.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]) - lastX) < 0.01)).toBe(true)
    } finally { chart.dispose() }
  })

  it('相邻点高低交错时也为浏览器实际字体高度留出避让空间', () => {
    const ratios = [55.2,55.4,59.4,59.3,62,54,53.5,45.8,45.8,45.8,48.1,52.9,55.3,53.1,46.3,47.2,49,42,41.5,41]
    const data = batches.map((batch, index) => ({ ...batch,
      analysis: { summary: { ...batch.analysis.summary, kichu_video_count: ratios[index] * 10 } },
    }))
    const chart = svgChart(cardOption(KichuRatioCard, data), 326)
    try {
      const doc = new JSDOM(chart.renderToSVGString(), { contentType: 'image/svg+xml' }).window.document
      const boxes = [...doc.querySelectorAll('text')].filter(node => node.style.fontWeight === '600').map(node => {
        const [, x, y] = node.getAttribute('transform').match(/translate\(([-\d.]+) ([-\d.]+)\)/)
        // Measured browser bounds for this 11px bold font: 15px tall;
        // decimal percentages <=35.5px wide, integer percentages <=25.6px.
        return { x: Number(x), y: Number(y), width: node.textContent.includes('.') ? 35.5 : 25.6 }
      })
      const overlaps = boxes.flatMap((a, i) => boxes.slice(i + 1).filter(b =>
        Math.abs(a.x - b.x) < (a.width + b.width) / 2 && Math.abs(a.y - b.y) < 15))
      expect(overlaps).toEqual([])
    } finally { chart.dispose() }
  })

  it('避让不丢失历史数据或悬停明细，也不改变活跃UP图', () => {
    const option = cardOption(KichuRatioCard)
    expect(option.series[0].data).toHaveLength(20)
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('55.4%')
    expect(option.tooltip.formatter([{ dataIndex: 0 }])).toContain('554 / 1000')
    expect(cardOption(ActiveUpCard).series[0].labelLayout).toBeUndefined()
  })
})
