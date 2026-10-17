import { Play, Trophy } from 'lucide-react'
import { proxyImage } from '../utils/image'
import { videoRate } from '../utils/videoCardMeta'
import './DashboardRanking.css'

export default function DashboardRanking({ videos = [], formatNumber, onViewAll }) {
  return (
    <section className="kb-card dashboard-ranking" aria-labelledby="dashboard-ranking-title">
      <div className="inner">
        <header className="dashboard-ranking-header">
          <div className="dashboard-ranking-heading">
            <Trophy size={19} aria-hidden="true" />
            <h2 id="dashboard-ranking-title">鬼畜区排行榜</h2>
            <span className="dashboard-ranking-label">Top 5</span>
          </div>
          <button type="button" onClick={onViewAll} className="dashboard-ranking-more">查看全部 →</button>
        </header>
        {videos.length ? (
          <ol className="dashboard-ranking-list">
            {videos.slice(0, 5).map((video, index) => {
              const url = video.url || `https://www.bilibili.com/video/${video.bvid}`
              return (
                <li key={video.bvid || index} className="dashboard-ranking-row">
                  <span className={`dashboard-ranking-number ${index < 3 ? 'dashboard-ranking-number--top' : ''}`} aria-hidden="true">{index + 1}</span>
                  <a className="dashboard-ranking-cover" href={url} target="_blank" rel="noopener noreferrer" aria-label={`在 B 站播放：${video.title}`}>
                    <Play size={18} aria-hidden="true" />
                    {video.cover && <img src={proxyImage(video.cover)} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true }} />}
                  </a>
                  <div className="dashboard-ranking-info">
                    <h3><a href={url} target="_blank" rel="noopener noreferrer" title={video.title}>{video.title}</a></h3>
                    <p title={video.author || '未知作者'}>{video.author || '未知作者'}</p>
                  </div>
                  <dl className="dashboard-ranking-metrics">
                    <div><dt>播放量</dt><dd>{video.views == null ? '—' : formatNumber(video.views)}</dd></div>
                    <div><dt>播赞率</dt><dd>{videoRate(video.likes, video.views)}</dd></div>
                  </dl>
                </li>
              )
            })}
          </ol>
        ) : <p className="dashboard-ranking-empty">暂无鬼畜区排行数据</p>}
      </div>
    </section>
  )
}
