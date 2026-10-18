import PublicLink from '../routing/PublicLink'
import { ExternalLink } from 'lucide-react'
import { friendLinks } from '../config/friendLinks'
import './SiteFooter.css'

const footerTabIds = new Set(['dashboard', 'kichu-rank', 'memes', 'videos', 'meme-materials', 'up-trends'])

export default function SiteFooter({ tabGroups, activeTab, onNavigate, renderYear }) {
  const navigation = tabGroups.flatMap((group) => group.tabs).filter((tab) => footerTabIds.has(tab.id))

  return (
    <footer role="contentinfo" className="site-footer mt-auto">
      <div className="site-footer__inner">
        <div className="site-footer__top">
          <div className="site-footer__brand">
            <div className="flex items-center gap-3">
              <span aria-hidden="true" className="site-footer__mark flex items-center justify-center gap-[2px] rounded-xl bg-gradient-to-br from-bili-default via-neon-violet to-neon-cyan">
                <span className="h-2 w-[3px] rounded-full bg-white/95" />
                <span className="h-4 w-[3px] rounded-full bg-white" />
                <span className="h-3 w-[3px] rounded-full bg-white/95" />
              </span>
              <p className="site-footer__name">GuichuHub</p>
            </div>
            <p className="site-footer__description">
              发现鬼畜热点，追踪创作趋势。
            </p>
            <span aria-hidden="true" className="site-footer__accent" />
          </div>

          <nav aria-label="站内导航">
            <h2 className="site-footer__heading">探索内容</h2>
            <ul className="site-footer__links">
              {navigation.map((tab) => (
                <li key={tab.id}>
                  <PublicLink
                    tabId={tab.id} onNavigate={onNavigate}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                    className="site-footer__link"
                  >
                    {tab.label}
                  </PublicLink>
                </li>
              ))}
            </ul>
          </nav>

          <div>
            <h2 className="site-footer__heading">友情链接</h2>
            <ul className="site-footer__links">
              {friendLinks.map(({ name, href }) => (
                <li key={href}>
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="site-footer__link site-footer__external"
                  >
                    <span>{name}</span>
                    <ExternalLink size={12} aria-hidden="true" className="site-footer__external-icon" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="site-footer__bottom">
          <p>© {renderYear ?? new Date().getFullYear()} GuichuHub</p>
          <div className="site-footer__filings">
            <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer"
               className="site-footer__link">
              苏ICP备2026075438号-1
            </a>
            <a href="https://beian.mps.gov.cn/#/query/webSearch?code=41010502008078" target="_blank" rel="noopener noreferrer"
               className="site-footer__link site-footer__filing">
              <img src="/images/public-security-filing.png" width="16" height="18" alt="" />
              <span>豫公网安备41010502008078号</span>
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}
