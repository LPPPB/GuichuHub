const firstDefined = (...values) => values.find((value) => value !== null && value !== undefined)

export function buildUpTrendsNarrative(summary = {}, formatNumber = String) {
  const upCount = Number(summary.total_ups || 0)
  const videoCount = Number(firstDefined(summary.pool_total_videos, summary.total_videos, 0))
  const totalViews = Number(firstDefined(summary.pool_total_views, summary.total_views, 0))
  const averageViews = Number(firstDefined(summary.pool_avg_views_per_video, summary.avg_views_per_video, 0))

  const detailParts = []
  if (videoCount > 0) detailParts.push(`共收录 ${formatNumber(videoCount)} 部视频`)
  if (totalViews > 0) detailParts.push(`累计播放 ${formatNumber(totalViews)}`)
  if (averageViews > 0) detailParts.push(`单条平均 ${formatNumber(averageViews)}`)

  return {
    eyebrow: 'CREATOR PULSE · 近 7 天全量观测',
    headline: `${formatNumber(upCount)} 位 UP 主正在形成最近 7 天的创作脉搏`,
    detail: detailParts.length > 0
      ? detailParts.join(' · ')
      : '持续追踪公开动态，新的投稿与播放变化会在下次分析后更新',
  }
}
