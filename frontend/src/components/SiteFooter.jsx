import { ExternalLink } from 'lucide-react'
import { friendLinks } from '../config/friendLinks'

const footerTabIds = new Set(['dashboard', 'kichu-rank', 'memes', 'videos', 'meme-materials', 'up-trends'])

export default function SiteFooter({ tabGroups, activeTab, onNavigate }) {
  const navigation = tabGroups.flatMap((group) => group.tabs).filter((tab) => footerTabIds.has(tab.id))

  return (
    <footer role="contentinfo" className="mt-auto border-t border-haze-400/20 bg-void-900/40 px-4 pb-7 pt-9 md:px-8 md:pb-8 md:pt-10">
      <div className="mx-auto max-w-[1400px]">
        <div className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-10">
          <div className="sm:col-span-2 lg:col-span-2">
            <div className="flex items-center gap-3">
              <span aria-hidden="true" className="flex h-9 w-9 items-center justify-center gap-[2px] rounded-xl bg-gradient-to-br from-bili-default via-neon-violet to-neon-cyan shadow-glow-pink">
                <span className="h-2 w-[3px] rounded-full bg-white/95" />
                <span className="h-4 w-[3px] rounded-full bg-white" />
                <span className="h-3 w-[3px] rounded-full bg-white/95" />
              </span>
              <p className="text-sm font-bold tracking-tight text-haze-50">GuichuHub</p>
            </div>
            <p className="mt-4 max-w-sm text-sm leading-6 text-haze-300">
              发现鬼畜热点，追踪内容趋势，收藏下一次创作的灵感。
            </p>
            <p className="mt-2 text-xs text-haze-300">个人技术小站 · 鬼畜看板</p>
          </div>

          <nav aria-label="站内导航">
            <h2 className="mb-3 text-xs font-semibold tracking-wide text-haze-100">站内导航</h2>
            <ul className="grid grid-cols-2 gap-x-3 gap-y-1">
              {navigation.map((tab) => (
                <li key={tab.id}>
                  <button
                    type="button"
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                    onClick={() => onNavigate(tab.id)}
                    className="min-h-11 text-left text-sm text-haze-300 transition-colors hover:text-bili-default focus-visible:text-bili-default"
                  >
                    {tab.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <div>
            <h2 className="mb-3 text-xs font-semibold tracking-wide text-haze-100">友情链接</h2>
            <ul className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-1">
              {friendLinks.map(({ name, href }) => (
                <li key={href}>
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-11 items-center gap-1.5 text-sm text-haze-300 transition-colors hover:text-bili-default focus-visible:text-bili-default"
                  >
                    <span>{name}</span>
                    <ExternalLink size={12} aria-hidden="true" className="shrink-0 opacity-60" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-8 flex flex-col gap-3 border-t border-haze-400/20 pt-5 text-xs text-haze-300 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <p>© {new Date().getFullYear()} GuichuHub. 保留所有权利。</p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer"
               className="inline-flex min-h-11 items-center text-haze-300 transition-colors hover:text-bili-default focus-visible:text-bili-default">
              苏ICP备2026075438号-1
            </a>
            <span>公安联网备案审核中</span>
          </div>
        </div>
      </div>
    </footer>
  )
}
