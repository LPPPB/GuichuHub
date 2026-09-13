// ECharts 集中注册（全项目唯一真源）
// 各图表组件只 import 本文件即可使用图表，禁止再各自 echarts.use() 重复注册。
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

// 按需注册：新增图表类型（Pie/Scatter/Heatmap 等）时在此追加
// 用 SVG 渲染器：矢量输出，网页放大后不模糊
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  SVGRenderer,
])

export default echarts
