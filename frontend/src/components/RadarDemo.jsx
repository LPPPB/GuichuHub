import { useEffect, useId, useRef, useState } from 'react'
import { RotateCcw, Play, Radar } from 'lucide-react'
import VideoRadar from './VideoRadar'
import { makeRadarDemo, RADAR_DEMO_PRESETS } from './radarDemoSamples'

export default function RadarDemo() {
  const [presetId, setPresetId] = useState('balanced')
  const [radar, setRadar] = useState(makeRadarDemo)
  const [replay, setReplay] = useState(0)
  const [modified, setModified] = useState(false)
  const [previewSize, setPreviewSize] = useState(164)
  const previewRef = useRef(null)
  const id = useId()
  const preset = RADAR_DEMO_PRESETS.find(item => item.id === presetId)
  const available = radar.axes.filter(axis => axis.score != null && axis.status === 'available').length

  useEffect(() => {
    const node = previewRef.current
    const measure = () => setPreviewSize(Math.max(164, Math.min(280, node.clientWidth - 32)))
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const selectPreset = nextId => {
    setPresetId(nextId)
    setRadar(makeRadarDemo(nextId))
    setModified(false)
    setReplay(value => value + 1)
  }
  const changeScore = (axisId, score) => {
    setModified(true)
    setRadar(current => ({ ...current, axes: current.axes.map(axis => axis.id !== axisId ? axis : {
      ...axis, score, components: axis.components.map(component => ({ ...component, score })),
    }) }))
  }

  return <section className="radar-demo rounded-xl border border-slate-200 bg-white p-4 sm:p-5" aria-labelledby={`${id}-title`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 id={`${id}-title`} className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Radar size={17} className="text-primary-500" />视频雷达图</h3>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">样例 3/3 · radar-v2</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">切换样例观察轮廓，点击图上维度查看详情。这里始终展示雷达图，方便手机端预览。</p>
      </div>
      <span className="rounded-full bg-primary-50 px-2.5 py-1 text-[11px] font-medium text-primary-600">合成数据 · 不写入观测</span>
    </div>

    <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="雷达图样例场景">
      {RADAR_DEMO_PRESETS.map(item => <button key={item.id} type="button" aria-pressed={presetId === item.id}
        onClick={() => selectPreset(item.id)} className={`min-h-11 rounded-lg border px-3 text-xs transition-colors ${presetId === item.id ?
          'border-primary-500 bg-primary-50 font-semibold text-primary-600' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
        {item.label}
      </button>)}
    </div>
    <p className="mt-3 text-xs leading-5 text-slate-600" role="status">{preset.description}{modified && ' 当前已手动调整轮廓。'}</p>

    <div className="mt-4 grid min-w-0 gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
      <div ref={previewRef} className="radar-demo-preview rounded-xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-haze-400">
          <span>轮廓预览</span><span>{available}/6 维可用</span>
        </div>
        <div className="flex min-h-[240px] items-center justify-center py-5">
          <VideoRadar key={replay} radar={radar} size={previewSize} className="radar-demo-chart" />
        </div>
        <p className="text-center text-[11px] leading-5 text-haze-400">复用榜单图表 · 中心不显示总分<br />进入视野展开；减少动态效果时直接显示终态</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <button type="button" onClick={() => setReplay(value => value + 1)} className="flex min-h-11 items-center gap-1.5 rounded-lg bg-primary-500 px-3 text-xs font-medium text-white hover:bg-primary-600"><Play size={14} />重播展开动画</button>
          <button type="button" onClick={() => selectPreset(presetId)} className="flex min-h-11 items-center gap-1.5 rounded-lg border border-slate-300 px-3 text-xs text-haze-300"><RotateCcw size={14} />重置样例</button>
        </div>
      </div>

      <div className="min-w-0 rounded-xl border border-slate-200 p-3 sm:p-4">
        <h4 className="text-xs font-semibold text-slate-700">六维分数试调</h4>
        <p className="mt-1 text-[11px] leading-5 text-slate-500">拖动滑块查看 0–100 分的形状变化；缺失维度保留缺口。</p>
        <div className="mt-2 divide-y divide-slate-100">
          {radar.axes.map(axis => <div key={axis.id} className="py-2.5">
            <div className="flex items-center justify-between gap-2 text-xs">
              <label htmlFor={`${id}-${axis.id}`} className="font-medium text-slate-700">{axis.label}</label>
              <output htmlFor={`${id}-${axis.id}`} className={axis.score == null ? 'text-slate-500' : 'font-semibold tabular-nums text-primary-600'}>{axis.score == null ? '—' : `${axis.score} 分`}</output>
            </div>
            <input id={`${id}-${axis.id}`} type="range" min="0" max="100" step="1" value={axis.score ?? 0}
              disabled={axis.score == null} aria-describedby={axis.reason ? `${id}-${axis.id}-reason` : undefined}
              onChange={event => changeScore(axis.id, Number(event.target.value))}
              className="radar-demo-slider mt-1 block min-h-7 w-full cursor-pointer accent-primary-500 disabled:cursor-not-allowed disabled:opacity-30" />
            {axis.reason && <p id={`${id}-${axis.id}-reason`} className="text-[11px] text-slate-500">{axis.reason}</p>}
          </div>)}
        </div>
      </div>
    </div>

    <div className="mt-4 grid gap-2 text-xs leading-5 text-slate-600 sm:grid-cols-3">
      <p className="rounded-lg bg-slate-50 p-3"><span className="font-semibold text-rose-500">闭合填色</span><br />六项都有分数时连接为完整轮廓，含真实零分。</p>
      <p className="rounded-lg bg-slate-50 p-3"><span className="font-semibold text-slate-700">断线与叉号</span><br />缺失、样本不足或过期时不补零，点维度查看原因。</p>
      <p className="rounded-lg bg-slate-50 p-3"><span className="font-semibold text-primary-600">维度详情</span><br />展示合成原始量、子指标、参考样本和观测时间。</p>
    </div>
    <p className="mt-3 text-[11px] leading-5 text-slate-500">所有原始量、参考样本与分数均为演示数据，分数直接注入，不用于验证归一化公式。滑块只调整演示分数，不重算原始指标或生产基线。</p>
  </section>
}
