import {formatVideoPublishTime} from '../utils/videoCardMeta'

export default function RankingSource({meta}) {
  const official=meta?.source==='bilibili_official_ranking_v2'
  const independent=meta?.source==='independent_discovery'
  const source=official?'哔哩哔哩官方榜':independent?'独立发现 · 本批相对评分':
    meta?.source==='legacy_custom'?'旧版自定义规则':'来源未知 · 旧规则数据'
  const fetched=formatVideoPublishTime(meta?.fetched_at)
  const failed=meta?.last_attempt && meta.last_attempt.outcome!=='success'
  return <p className="text-xs text-haze-400 leading-relaxed mb-3" aria-label="榜单来源">
    <span>{source}</span>
    {fetched && <span> · 抓取于 {fetched.text}（北京时间）</span>}
    {meta?.status==='unavailable' && <span> · {official?'暂无官方榜数据':'暂无潜力榜数据'}</span>}
    {failed && <span> · 更新失败{meta?.status==='available'?'，保留上次成功结果':''}</span>}
    {meta?.historical ? <span> · 历史榜单</span> : meta?.stale && <span> · 榜单已过期</span>}
  </p>
}
