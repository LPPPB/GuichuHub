import { Trophy } from 'lucide-react'
import VideoCard from './VideoCard'
import './DashboardRanking.css'

export default function DashboardRanking({ videos = [], formatNumber, onViewAll }) {
  return (
    <section className="dashboard-ranking" aria-labelledby="dashboard-ranking-title">
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
            {videos.slice(0, 5).map((video, index) => (
              <li key={video.bvid || index}>
                <VideoCard video={video} index={index} formatNumber={formatNumber} variant="dashboard" staggerDelay={index * 40} />
              </li>
            ))}
          </ol>
        ) : <p className="dashboard-ranking-empty">暂无鬼畜区排行数据</p>}
      </div>
    </section>
  )
}
