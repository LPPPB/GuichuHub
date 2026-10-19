// Only synthetic display fixtures. Scores are supplied, not calculated from a production baseline.
export const RADAR_DEMO_PRESETS = [
  { id: 'balanced', label: '均衡表现', description: '六项指标均有观测，形成完整的填色轮廓。', scores: [68, 72, 61, 65, 58, 70] },
  { id: 'reach', label: '播放突出', description: '播放规模较高，但互动和分享并未同步突出。', scores: [96, 39, 28, 46, 31, 82] },
  { id: 'engagement', label: '互动突出', description: '播放规模中等，观众认可、收藏和讨论更活跃。', scores: [43, 91, 85, 88, 76, 54] },
  { id: 'missing', label: '样本不足', description: '收藏维度缺少参考样本，近期增速缺少有效窗口；缺失轴断开，不当作零分。', scores: [68, 72, null, 65, 58, null] },
  { id: 'stale', label: '观测过期', description: '近期增速的观测已过期，轮廓保留缺口，并可查看具体原因。', scores: [68, 72, 61, 65, 58, null] },
  { id: 'zero', label: '真实零分', description: '近期增速已观测且分数为 0，节点落在中心，仍构成完整轮廓。', scores: [68, 72, 61, 65, 58, 0] },
]

const DIMENSIONS = [
  { id: 'reach', label: '播放规模', unit: '次', metrics: [['views', '播放', 224000]] },
  { id: 'approval', label: '观众认可', unit: '次/千播放', metrics: [['likes_rate', '点赞', 43], ['coins_rate', '投币', 2]] },
  { id: 'retention', label: '收藏倾向', unit: '次/千播放', metrics: [['favorites_rate', '收藏', 7.5]] },
  { id: 'discussion', label: '讨论活跃', unit: '次/千播放', metrics: [['comments_rate', '评论', 5], ['danmaku_rate', '弹幕', 8]] },
  { id: 'sharing', label: '分享倾向', unit: '次/千播放', metrics: [['shares_rate', '分享', 3.2]] },
  { id: 'growth', label: '近期增速', unit: '播放/小时', metrics: [['growth_rate', '播放增速', 1800]] },
]

export function makeRadarDemo(presetId = 'balanced') {
  const preset = RADAR_DEMO_PRESETS.find(item => item.id === presetId) || RADAR_DEMO_PRESETS[0]
  return {
    algorithm_version: 'radar-v2', baseline_version: 'radar-v2-demo-synthetic',
    observed_at: Date.UTC(2026, 9, 18, 2, 0) / 1000,
    axes: DIMENSIONS.map((dimension, index) => {
      const score = preset.scores[index]
      const status = score != null ? 'available' : preset.id === 'stale' ? 'stale' :
        dimension.id === 'growth' ? 'insufficient_window' : 'insufficient_baseline'
      const reason = status === 'stale' ? '观测已过期' : status === 'insufficient_window' ?
        '缺少有效增速观测窗口' : status === 'insufficient_baseline' ? '参考样本不足' : null
      return {
        id: dimension.id, label: dimension.label, unit: dimension.unit,
        score, raw: score == null ? null : dimension.id === 'growth' && score === 0 ? 0 : dimension.metrics[0][2],
        status, reason,
        ...(dimension.id === 'growth' && score != null ? { window_hours: 6, growth_views: score === 0 ? 0 : 10800 } : {}),
        components: dimension.metrics.map(([id, label, raw]) => ({ id, label,
          raw: score == null ? null : dimension.id === 'growth' && score === 0 ? 0 : raw,
          score, reason, reference: { count: status === 'insufficient_baseline' ? 12 : 240, age_min_days: 0, age_max_days: 7 },
        })),
      }
    }),
  }
}
