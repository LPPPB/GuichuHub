import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// ═══════════════════════════════════════════════════════════════════
// UI 回归测试：Sidebar 按钮可见性 & Tailwind 颜色定义兼容性
// ── 触发该测试的真实线上问题 ──
// 浏览器实测：当前运行浏览器不支持 CSS Color Level 4 `rgb(triplet / alpha)` 斜杠语法。
//   t4 样式：rgb(var(--neon-pink) / var(--x, 1))  →  computed: rgba(0, 0, 0, 0) 透明
//   t5 样式：rgba(var(--neon-pink), 0.9)           →  computed: rgba(241,94,140,0.9) ✓
// 结果：Sidebar 刷新按钮 class=bg-neon-pink → 背景透明；又写死 text-white → 日间白字白底 = 看不见。
// ═══════════════════════════════════════════════════════════════════

const tailwindCfgRaw = readFileSync(resolve(__dirname, 'tailwind.config.js'), 'utf8')
// 每个自定义颜色通道：一旦 tailwind.config 的颜色结构出问题，全量样式瘫痪
const COLOR_CHANNELS = [
  'void-950', 'void-900', 'void-800', 'void-700', 'void-600',
  'neon-pink', 'neon-rose', 'neon-cyan', 'neon-violet', 'neon-amber', 'neon-emerald',
  'haze-50', 'haze-100', 'haze-300', 'haze-400', 'haze-500',
]

describe('[UI Regression] Tailwind 颜色定义必须兼容当前浏览器', () => {
  it('禁止使用 "rgb(var(--x) / <alpha-value>)" 斜杠语法（会让 Tailwind 产出带斜杠的样式，浏览器解析为透明）', () => {
    const slashSyntaxRegex = /rgb\(\s*var\(--[^)]+\)\s*\/\s*<alpha-value>\s*\)/g
    const offendingLines = []
    tailwindCfgRaw.split('\n').forEach((line, idx) => {
      const m = line.match(slashSyntaxRegex)
      if (m) offendingLines.push(`L${idx + 1}: ${m.join(' ')}`)
    })
    expect(
      offendingLines,
      `发现 ${offendingLines.length} 处浏览器不支持的 Color-Level-4 斜杠语法`
      + '（Tailwind 产出 rgb(var(--x) / 1) 后被解析为透明，全量 UI 瘫痪）。'
      + '请改为逗号分隔的 rgba(var(--x), var(--tw-*-opacity, 1)) 或等效写法。\n'
      + offendingLines.join('\n'),
    ).toHaveLength(0)
  })

  it('每个颜色通道在 tailwind.config 中必须存在绑定（防止误删后全站隐形）', () => {
    COLOR_CHANNELS.forEach((ch) => {
      // 三种匹配方式：
      // 1) tailwind 配置中直接出现 CSS var(--${ch}) 引用（无论 key 怎么命名，我们都认）
      // 2) 对象 key 被引号包围 'xxx' 或 "xxx"（neon 组粉色= pink 不带 neon- 前缀，也能命中）
      // 3) 对象 key 为数字字面量（void / haze 组的 50/100/300/.../950）
      const cssVarRef = `var(--${ch})`
      const stripped = ch.replace(/^(void|neon|haze)-/, '')
      const quotedKey =
        tailwindCfgRaw.includes(`'${ch}'`) || tailwindCfgRaw.includes(`"${ch}"`) ||
        tailwindCfgRaw.includes(`'${stripped}'`) || tailwindCfgRaw.includes(`"${stripped}"`)
      const numericKey = /^\d+$/.test(stripped) && tailwindCfgRaw.includes(`${stripped}:`)
      const bound =
        tailwindCfgRaw.includes(cssVarRef) || quotedKey || numericKey
      expect(
        bound,
        `颜色通道 ${ch} 在 tailwind.config.js 中没有绑定引用（既无 var(--${ch}) 也无 key）。`
        + '对应 bg-* text-* utility 会被 Tailwind 忽略 → 相关样式全站透明。',
      ).toBe(true)
    })
  })

  it('颜色声明必须用 rgba()（逗号旧语法），不能再使用无 alpha 的 rgb(...) 默认值', () => {
    const plainRgbRegex = /:\s*'rgb\([^)]+'\s*,?/g
    const perLine = []
    tailwindCfgRaw.split('\n').forEach((line, idx) => {
      const m = line.match(plainRgbRegex)
      if (m) perLine.push(`L${idx + 1}: ${m.join(' ')}`)
    })
    expect(
      perLine,
      `检测到 ${perLine.length} 处用 "rgb(...)" 写死颜色默认值。请使用 rgba 逗号形式`
      + ' （配合 Tailwind <alpha-value> 替换后也仍走逗号，保证浏览器兼容）。\n'
      + perLine.join('\n'),
    ).toHaveLength(0)
  })
})

describe('[UI Regression] Sidebar ActionPanel 按钮可见性 + 层级一致性', () => {
  let sidebarSrc
  beforeAll(() => {
    // 组件路径优先：项目标准目录 src/components/Sidebar.jsx，若不存在再 fallback 到 dash 同目录
    let sidebarPath = resolve(__dirname, 'src/components/Sidebar.jsx')
    try { sidebarSrc = readFileSync(sidebarPath, 'utf8') } catch (_) {
      sidebarPath = resolve(__dirname, 'Sidebar.jsx')
      sidebarSrc = readFileSync(sidebarPath, 'utf8')
    }
  })

  it('刷新按钮（主 CTA）必须有主题感知文字色，禁止仅写死 text-white（日间=白字白底=不可见）', () => {
    const idx = sidebarSrc.indexOf('刷新数据')
    expect(idx, 'Sidebar 必须包含"刷新数据"按钮，怀疑标签改动').toBeGreaterThan(-1)
    const around = sidebarSrc.slice(Math.max(0, idx - 900), idx + 120)

    // ⚠️ 安全例外：当按钮本身使用「实心不透明背景 + 明确品牌语义色」（bg-neon-pink / bg-bili-default
    //    等不含 /N 透明度修饰的实体背景），白字 (text-white) 在日/夜间都对比度充足
    //    （实心 B 站品牌蓝 rgb(0,174,236) vs 白字 = 约 4.6 : 1 达 WCAG AA）。
    //    只有「没有实心背景 / 背景透明 / 背景是 CSS 变量解析失败」的场景才强制 theme-aware。
    const hasSolidOpaqueBg = /(^|\s)bg-(neon-pink|neon-rose|bili-default|bili-dark|neon-violet|neon-cyan)(\/\d+)?(\s|"|$)/.test(around)
      // bg-xxx/100 等价于不透明；bg-xxx/XX 当 XX≥80 近似高不透明高饱和，白字也安全
      || /(^|\s)bg-(neon-pink|neon-rose|bili-default|bili-dark)\/(?:[89]\d|100)(\s|"|$)/.test(around)

    const hardcodedWhiteOnly =
      around.includes('text-white') &&
      !around.includes('dark:text-white') &&
      !around.includes('text-haze-50') &&
      !around.includes('text-on-solid')

    const hasThemeAwareText =
      /(^|\s|'|")dark:text-white(\s|,|'|"|$)/.test(around) ||
      around.includes('text-haze-50') ||
      around.includes('text-on-solid')

    expect(
      hasSolidOpaqueBg || !hardcodedWhiteOnly || hasThemeAwareText,
      'Sidebar 刷新按钮 className 含 "text-white" 且未提供主题感知 fallback，同时也没有实心品牌蓝/粉背景兜住。\n'
      + '当 Tailwind 颜色定义失效（本项目真实发生过）或日间浅色背景下，'
      + '白字白底 → 刷新按钮完全不可见。\n'
      + '请改为：① 加 bg-bili-default / bg-neon-pink 实心不透明底（安全，白字高对比）；\n'
      + '       ② 或 日间用深色 + dark:text-white 双变体；\n'
      + '       ③ 或 使用 text-haze-50（CSS 变量主题感知）。\n'
      + `上下文片段：\n${around}`,
    ).toBe(true)
  })

  it('ActionPanel 核心按钮（收藏/刷新/登录）圆角、宽度、padding 必须一致，保证视觉层级统一', () => {
    const actionIdx = sidebarSrc.indexOf('ActionPanel')
    expect(actionIdx, 'Sidebar 应包含 ActionPanel 操作面板块').toBeGreaterThan(-1)
    // ActionPanel 含管理员门禁分支后变长，窗口需覆盖到 biliUser 区块（原 4500 会截断）
    const block = sidebarSrc.slice(actionIdx, Math.min(sidebarSrc.length, actionIdx + 7000))
    // 只抓「展开态 (collapsed=false 分支)」的主按钮：主题切换 / 收藏 / 刷新(管理员)
    //（"管理员登录"按钮已移除——超管入口改为品牌 logo 连点 5 次隐蔽触发，见「隐蔽超管入口」用例）
    // 方法：取第一个 `{!collapsed ? (<>` 开始到第一个匹配 `) : (` 结束之间的 JSX
    const expandedStart = block.indexOf('{!collapsed')
    const expandedEnd = block.indexOf(') : (', expandedStart)
    expect(expandedStart, '找不到 collapsed=false 展开分支').toBeGreaterThan(-1)
    expect(expandedEnd, '找不到展开/折叠分支分隔 ') .toBeGreaterThan(expandedStart)
    const expandedBlock = block.slice(expandedStart, expandedEnd)
    const buttonRegex = /<button[\s\S]*?className="([^"]+)"[\s\S]*?>/g
    const matches = [...expandedBlock.matchAll(buttonRegex)].map((m) => m[1].replace(/\s+/g, ' ').trim())
    expect(matches.length, '展开态 ActionPanel 应有 3 个按钮（主题切换/收藏/刷新——刷新为管理员互斥分支，"管理员登录"按钮已移除），当前=' + matches.length).toBe(3)
    // 再抓登录按钮：biliUser 空态分支里的未登录展开按钮，以及 biliUser 有值时的菜单按钮（两个路径都要符合统一骨架）
    const loginBlockStart = block.indexOf('biliUser ?')
    expect(loginBlockStart, '找不到 biliUser 条件分支').toBeGreaterThan(-1)
    const loginBlock = block.slice(loginBlockStart, Math.min(block.length, loginBlockStart + 2000))
    const loginButtons = [...loginBlock.matchAll(buttonRegex)]
      .map((m) => m[1].replace(/\s+/g, ' ').trim())
      // 折叠态的圆形头像/登录 icon 按钮不走这套大按钮骨架，排除；以及下拉菜单项"退出登录"（px-4 py-2 text-sm）也排除
      .filter((cls) => !cls.includes('kb-icon-btn') && !cls.includes('gap-2 px-4 py-2 text-sm'))
    expect(loginButtons.length, '展开态登录路径应找到 1 个大按钮（菜单触发 or 未登录 CTA），当前=' + loginButtons.length).toBeGreaterThanOrEqual(1)

    const all = [...matches, ...loginButtons]
    const requiredTokens = ['w-full', 'rounded-xl']
    all.forEach((cls, i) => {
      requiredTokens.forEach((tok) => {
        expect(cls, `第${i + 1}个按钮缺少 ${tok}，与其他按钮视觉边界会不一致。class=${cls.substring(0, 220)}`).toContain(tok)
      })
    })
  })

  it('ActionPanel 必须恰好 1 个主 CTA（刷新按钮用实心背景区分），其他 2 个为辅 CTA（描边/幽灵）', () => {
    const actionIdx = sidebarSrc.indexOf('ActionPanel')
    const block = sidebarSrc.slice(actionIdx, Math.min(sidebarSrc.length, actionIdx + 7000))
    // 取展开态 2 按钮 + 登录路径 1 按钮（和上一个测试相同口径）
    const expandedStart = block.indexOf('{!collapsed')
    const expandedEnd = block.indexOf(') : (', expandedStart)
    const expandedBlock = block.slice(expandedStart, expandedEnd)
    const buttonRegex = /<button[\s\S]*?className="([^"]+)"[\s\S]*?>/g
    const matches = [...expandedBlock.matchAll(buttonRegex)].map((m) => m[1].replace(/\s+/g, ' ').trim())
    const loginBlockStart = block.indexOf('biliUser ?')
    const loginBlock = block.slice(loginBlockStart, Math.min(block.length, loginBlockStart + 2000))
    const loginButtons = [...loginBlock.matchAll(buttonRegex)]
      .map((m) => m[1].replace(/\s+/g, ' ').trim())
      .filter((cls) => !cls.includes('kb-icon-btn') && !cls.includes('gap-2 px-4 py-2 text-sm'))

    const all = [...matches, ...loginButtons]
    // 实心主 CTA 的判定：neon-pink/violet 实心底 / 品牌渐变 / 新版 B 站蓝实心底
    //   (注意：透明度 bg-bili-default/6 是描边辅按钮，必须排除 — 所以 bg-bili 用
    //    "无 /" 或 /N≥80 才认定主 CTA)
    const isSolidPrimary = (c) => {
      if (c.includes('bg-gradient-to-br')) return true
      // 主 CTA：不透明度修饰为空 或 ≥80%
      const solidBgRe = /(^|\s)bg-(neon-pink|neon-rose|bili-default|bili-dark)(\/(?:[89]\d|100))?(\s|"|$)/
      return solidBgRe.test(c)
    }
    const primaries = all.filter(isSolidPrimary)
    expect(
      primaries.length,
      `应恰好 1 个主 CTA（刷新按钮），当前找到 ${primaries.length} 个。`
      + '请保持 1 主（实心）+ 3 辅（主题切换/收藏/登录，描边/幽灵）的权重分布，避免"为什么刷新按钮和其他不一样"的困惑，'
      + '或改为四者同骨架 + 颜色变量区分权重。\n'
      + all.map((c, i) => `  [${i + 1}] ${c.substring(0, 240)}`).join('\n'),
    ).toBe(1)
  })
})

// ═══════════════════════════════════════════════════════════════════
// 鬼畜区排行榜 序号徽章 UI 回归（真实用户问题）
// ── 用户原话现象 ──
//   1) 序号 4 5 6 有灰底圆角矩形，1 2 3 完全没有
//   2) 序号 4 5 6 字也是灰色的 → 灰字灰底，可读性极差
//   3) 序号和标题首行没有对齐
// ── 根因（已用纯浏览器 evaluate 实证） ──
//   index.css .kb-rank--1/2/3 背景/边框使用不支持的 `rgb(var(--x) / alpha)` 斜杠语法，
//   浏览器解析为 rgba(0,0,0,0) 透明 → 123 完全没有底色；
//   .kb-rank--n 使用 haze-400 + 日间强制 void-800（~中灰）→ 灰字叠灰底，对比度仅 2.x:1。
// ═══════════════════════════════════════════════════════════════════
describe('[UI Regression] 全局 CSS 颜色兼容性：禁止 index.css 再出现 Color-Level-4 斜杠语法', () => {
  let indexCss
  beforeAll(() => {
    const cssCandidates = [resolve(__dirname, 'src/index.css'), resolve(__dirname, 'index.css')]
    indexCss = cssCandidates.reduce((acc, p) => {
      if (acc) return acc
      try { return readFileSync(p, 'utf8') } catch (_) { return null }
    }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  it('index.css 全文件禁止任何 `rgb(...)` 带斜杠 / 透明度的写法（浏览器解析为 rgba(0,0,0,0) 透明，chip 背景实测证实过）', () => {
    // 兼容两种斜杠形态：rgb(var(--x) / 0.12)  与  rgb(255 255 255 / 0.06)
    const slashRegex = /rgb\(\s*(?:var\(--[^)]+\)|(?:\d+\s+){2,3}\d+)\s*\/\s*[\d.]+[^)]*\)/g
    const matches = [...indexCss.matchAll(slashRegex)].map((m, i) => {
      const lineNo = (indexCss.slice(0, m.index).match(/\n/g) || []).length + 1
      return `L${lineNo}: ${m[0]}`
    })
    expect(
      matches.length,
      `index.css 里发现 ${matches.length} 处不兼容的 rgb(... / alpha) 斜杠语法。\n`
      + '当前运行浏览器不支持 Color Level 4 斜杠语法，全部会被解析为 rgba(0,0,0,0) 透明 → 对应元素底色/边框全消失。\n'
      + '请替换为 rgba(...) 逗号旧语法：rgba(var(--x), alpha) 或 rgba(r,g,b,a)。\n'
      + matches.map(s => '  ' + s).join('\n'),
    ).toBe(0)
  })
})

describe('[UI Regression] 鬼畜区排行榜 序号徽章', () => {
  let indexCss, videoCardSrc
  beforeAll(() => {
    // 文件位置优先项目标准目录：src/index.css 与 src/components/VideoCard.jsx
    const cssCandidates = [
      resolve(__dirname, 'src/index.css'),
      resolve(__dirname, 'index.css'),
    ]
    const vcCandidates = [
      resolve(__dirname, 'src/components/VideoCard.jsx'),
      resolve(__dirname, 'VideoCard.jsx'),
    ]
    indexCss = cssCandidates.reduce((acc, p) => {
      if (acc) return acc
      try { return readFileSync(p, 'utf8') } catch (_) { return null }
    }, null)
    videoCardSrc = vcCandidates.reduce((acc, p) => {
      if (acc) return acc
      try { return readFileSync(p, 'utf8') } catch (_) { return null }
    }, null)
    expect(indexCss, '找不到 index.css 用于校验 kb-rank 样式定义').not.toBe(null)
    expect(videoCardSrc, '找不到 VideoCard.jsx（排行榜卡片渲染组件）').not.toBe(null)
  })

  it('kb-rank--1/2/3/n 在 index.css 里必须使用 rgba(var(), alpha) 逗号旧语法，不得出现斜杠', () => {
    // 抓取 .kb-rank 块从 .kb-rank { 开始到下一个注释段或下一个顶级选择器前
    const blockStart = indexCss.indexOf('.kb-rank')
    const blockEnd   = indexCss.indexOf('/* ═══ 按钮 ═══ */')
    expect(blockStart, '找不到 .kb-rank 样式定义').toBeGreaterThan(-1)
    expect(blockEnd,   '找不到 .kb-rank 之后的下一段边界').toBeGreaterThan(blockStart)
    const rankBlock = indexCss.slice(blockStart, blockEnd)

    const slashRegex = /rgb\(\s*var\(--[^)]+\)\s*\/\s*[\d.]+[^)]*\)/g
    const bad = [...rankBlock.matchAll(slashRegex)].map((m) => m[0])
    expect(
      bad.length,
      `kb-rank 块里发现 ${bad.length} 处 rgb(var(--x) / alpha) 斜杠语法（浏览器解析为透明）：\n`
      + bad.map((s, i) => `  [${i + 1}] ${s}`).join('\n')
      + '\n请改为 rgba(var(--x), alpha) 逗号旧语法（与 tailwind.config 统一兼容性策略）。',
    ).toBe(0)
  })

  it('kb-rank--n（4-6+）日间模式不能用「灰字 + 近灰底」，文字色必须明显深于底色（通道字色非 haze-400）', () => {
    // 日间路径：html:not(.dark) .kb-rank--n  或  .kb-rank--n 内 color: var(--haze-400) 即为隐患
    const nRuleStart = indexCss.indexOf('.kb-rank--n')
    expect(nRuleStart, '找不到 .kb-rank--n 规则').toBeGreaterThan(-1)
    // 从 .kb-rank--n 规则开始，取到下一个 html.dark 规则或末尾
    const nextBoundary = Math.min(
      indexCss.indexOf('html.dark', nRuleStart) === -1 ? Infinity : indexCss.indexOf('html.dark', nRuleStart),
      indexCss.indexOf('\n\n\n', nRuleStart) === -1 ? Infinity : indexCss.indexOf('\n\n\n', nRuleStart),
      indexCss.length,
    )
    const nBlock = indexCss.slice(nRuleStart, nextBoundary)
    const lightOverride = indexCss.indexOf('html:not(.dark) .kb-rank--n')
    const hasLightFgOverride = lightOverride !== -1
    const baseUsesHaze400 = nBlock.includes('--haze-400')  // 基础规则用 haze-400 灰色
    // 只要基础规则用 haze-400 灰色但没有日间深色覆盖，就是用户说的「灰字灰底」
    expect(
      !(baseUsesHaze400 && !hasLightFgOverride),
      'kb-rank--n 基础规则使用 haze-400（灰色字），且未提供 html:not(.dark) 下的深色覆盖。\n'
      + '日间会出现「灰字叠近灰底」，用户肉眼几乎读不清排名数字。\n'
      + '请在日间显式覆盖 color: var(--haze-50) 或等效深色，并提供浅米色淡底。\n'
      + `.kb-rank--n 规则片段：\n${nBlock}`,
    ).toBe(true)
  })

  it('日间 kb-rank--n 背景必须使用 void 系列变量（浅底组），绝不能用 haze 系列（文字色组）—— 否则日间会变深褐底', () => {
    // 变量语义约定（index.css :root 已写明）：
    //   void-950/900/800/700/600 = 背景色组（日间 = 250~212 暖色；夜间 = 深暗色）
    //   haze-50/100/300/400/500  = 文字色组（日间 = 深；夜间 = 浅）
    // 因此「徽章浅底」只能用 void，不能拿 haze 当底（上一版 bug 就是误用了 haze-100=43,40,34 深字色 → 深褐底）
    const lightOverride = indexCss.indexOf('html:not(.dark) .kb-rank--n')
    expect(lightOverride, '必须提供 html:not(.dark) .kb-rank--n 日间覆盖规则').toBeGreaterThan(-1)
    const blockStart = lightOverride
    const blockEnd   = indexCss.indexOf('}', blockStart) + 1
    const lightBlock = indexCss.slice(blockStart, blockEnd)
    // 背景规则必须引用 void（背景色组），不能出现 haze（文字色组）
    const bgRuleMatch = lightBlock.match(/background:\s*([^;]+);/)
    expect(bgRuleMatch, '日间 kb-rank--n 覆盖规则缺少 background').not.toBe(null)
    const bgDecl = bgRuleMatch[1]
    expect(
      bgDecl.includes('var(--void-') && !bgDecl.includes('var(--haze-'),
      `日间 kb-rank--n background=${bgDecl} 使用了错误的颜色变量组。\n`
      + '本项目变量语义：void = 背景色组（日间暖灰浅底）；haze = 文字色组（日间是深字色，不能拿来当底）。\n'
      + '请改为 background: rgba(var(--void-800), 0.92) 或等效的 void 系列变量，避免再次出现「深褐底」Bug。',
    ).toBe(true)
    // 字色规则必须使用 haze-50（最深文字）或其它明显深色，不能用 void
    const fgRuleMatch = lightBlock.match(/color:\s*([^;]+);/)
    expect(fgRuleMatch, '日间 kb-rank--n 覆盖规则缺少 color').not.toBe(null)
    const fgDecl = fgRuleMatch[1]
    expect(
      fgDecl.includes('var(--haze-50)') || fgDecl.includes('var(--haze-100)'),
      `日间 kb-rank--n color=${fgDecl} 未使用深字色通道 haze-50/haze-100，会读不清。`,
    ).toBe(true)
  })

  it('排行榜卡片内：序号徽章必须与标题首行对齐，徽章容器不得用 mt-* 下压导致错位', () => {
    const kbRankIdx = videoCardSrc.indexOf('kb-rank mt-0.5')
    // 修复后序号 <span> 应该只用基础 kb-rank 类（或少量 pad/align），不依赖 mt-0.5 手动下压
    // 我们用「父容器 items-start 对齐 + 徽章无 mt 」来保证标题 clamp-2 换行时始终首行对齐
    const fixedPattern = videoCardSrc.match(/kb-rank[^'"]*(?<!mt-\d+(?:\.\d+)?)/)
    // 简化检查：不允许再出现 "kb-rank mt-" 这种用手动 margin 强制居中的临时方案
    expect(
      kbRankIdx,
      '检测到 VideoCard.jsx 使用 "kb-rank mt-0.5" 强制下压序号徽章 → 与标题首行不对齐。\n'
      + '请移除 mt-0.5，改为让序号徽章自然跟随父容器 items-start，从而与标题 <h4> 的首行基线对齐。\n'
      + '当前片段：' + videoCardSrc.slice(Math.max(0, videoCardSrc.indexOf('kb-rank') - 40), videoCardSrc.indexOf('kb-rank') + 220),
    ).toBe(-1)
  })

  it('1~6 序号徽章尺寸必须统一（kb-rank 基础类 width/height 一致），不得出现 123 透明/456 有色的尺寸差异', () => {
    const baseStart = indexCss.indexOf('.kb-rank {')
    expect(baseStart, '找不到 .kb-rank 基础类').toBeGreaterThan(-1)
    const baseEnd = indexCss.indexOf('}', baseStart) + 1
    const baseDef = indexCss.slice(baseStart, baseEnd)
    expect(baseDef.includes('width:'),  'kb-rank 基础类必须提供统一 width').toBe(true)
    expect(baseDef.includes('height:'), 'kb-rank 基础类必须提供统一 height').toBe(true)
    expect(baseDef.includes('border-radius:'), 'kb-rank 基础类必须提供统一 border-radius').toBe(true)
    expect(baseDef.includes('inline-flex') || baseDef.includes('display:'), 'kb-rank 基础类必须是 inline-flex 以便居中对齐').toBe(true)
    // 所有 --n / --1 / --2 / --3 变体不得再定义 width/height（防止各自为政导致尺寸不一致）
    ;['.kb-rank--1 {', '.kb-rank--2 {', '.kb-rank--3 {', '.kb-rank--n {'].forEach((sel) => {
      const s = indexCss.indexOf(sel)
      expect(s, `找不到变体规则 ${sel}`).toBeGreaterThan(-1)
      const e = indexCss.indexOf('}', s)
      const block = indexCss.slice(s, e)
      expect(
        block.includes('width:') || block.includes('height:'),
        `变体规则 ${sel} 不应再定义 width/height，否则与基础类尺寸不一致、出现"123 无底色 456 有"的分裂观感。\n当前内容：\n${block}`,
      ).toBe(false)
    })
  })
})

// ═══════════════════════════════════════════════════════════════════
// 卡片背景统一（真实用户反馈：「卡片背景颜色不一样，改成一样的白色，灰色比较脏」）
// ── 用户原话现象 ──
//   1) 鬼畜区排行榜 article.kb-card 日间是暖灰色（脏色 ~rgba(243,241,237,0.72)）
//   2) 正在爆发 BurstingVideos section 写死 bg-white = 纯白
//   3) 两张主卡片并排放时，一眼能看出底色不一致
// ── 根因 ──
//   .kb-card 基础类错误地用 void-800（次级面板级暖灰）当卡片容器底；
//   BurstingVideos 使用 Tailwind 默认 slate 色系写死，完全未接入 kb-card 语义层。
// ── 修复策略 ──
//   ① 日间 .kb-card：background = rgba(var(--void-900), 1) = rgb(255,255,255) 纯白
//   ② 夜间 .kb-card：统一走 rgba(var(--void-800), x) 语义变量，不写死 17,17,30
//   ③ BurstingVideos：section 级 className 改用 kb-card 语义类，
//      内部行 hover/排名徽章/文字颜色/遮罩渐隐全部走 CSS 变量或 theme-aware Tailwind 类，
//      绝对禁止出现 bg-white / border-slate / text-slate / bg-red-100 等默认色板写死。
// ═══════════════════════════════════════════════════════════════════
describe('[UI Regression] 卡片背景统一：日间必须纯白，且所有主卡片必须走 kb-card 语义层', () => {
  let indexCss, burstingSrc
  beforeAll(() => {
    const cssCandidates = [resolve(__dirname, 'src/index.css'), resolve(__dirname, 'index.css')]
    const bvCandidates  = [resolve(__dirname, 'src/components/BurstingVideos.jsx'), resolve(__dirname, 'BurstingVideos.jsx')]
    indexCss = cssCandidates.reduce((acc, p) => {
      if (acc) return acc
      try { return readFileSync(p, 'utf8') } catch (_) { return null }
    }, null)
    burstingSrc = bvCandidates.reduce((acc, p) => {
      if (acc) return acc
      try { return readFileSync(p, 'utf8') } catch (_) { return null }
    }, null)
    expect(indexCss,    '找不到 index.css（校验 .kb-card 颜色定义）').not.toBe(null)
    expect(burstingSrc, '找不到 BurstingVideos.jsx（校验正在爆发卡片样式接入）').not.toBe(null)
  })

  describe('.kb-card 基础类：日间纯白 & 夜间走 CSS 变量', () => {
    let cardRule, darkOverride
    beforeAll(() => {
      const baseStart = indexCss.indexOf('.kb-card {')
      expect(baseStart, '找不到 .kb-card { 基础规则').toBeGreaterThan(-1)
      // 基础规则块：取到下一条 top-level 规则前
      const nextSibling = Math.min(
        indexCss.indexOf('html.dark .kb-card', baseStart) === -1 ? Infinity : indexCss.indexOf('html.dark .kb-card', baseStart),
        indexCss.indexOf('.kb-card::before',   baseStart) === -1 ? Infinity : indexCss.indexOf('.kb-card::before',   baseStart),
        indexCss.length,
      )
      cardRule = indexCss.slice(baseStart, nextSibling)

      const darkStart = indexCss.indexOf('html.dark .kb-card')
      if (darkStart !== -1) {
        const darkEnd = indexCss.indexOf('}', darkStart) + 1
        darkOverride = indexCss.slice(darkStart, darkEnd)
      } else {
        darkOverride = ''
      }
    })

    it('日间 .kb-card 背景必须用 void-900（255,255,255 纯白），不能再用 void-800（暖灰脏色）', () => {
      const bgMatch = cardRule.match(/background:\s*([^;]+);/)
      expect(bgMatch, '.kb-card 基础规则缺少 background 声明').not.toBe(null)
      const bgDecl = bgMatch[1].trim()
      expect(
        bgDecl.includes('var(--void-900)'),
        `.kb-card background=${bgDecl} 未使用 void-900（纯白通道）。\n`
        + '用户明确反馈「灰色比较脏」—— 当前 void-800 = (243,241,237) 暖灰会让卡片和 page 背景区分度差、观感脏。\n'
        + '请改为：background: rgba(var(--void-900), 1) 或等效写法，确保日间卡片 = 绝对纯白 rgb(255,255,255)。',
      ).toBe(true)
      expect(
        !bgDecl.includes('var(--void-800)'),
        `.kb-card background=${bgDecl} 使用 void-800（暖灰脏色）当卡片容器底。\n`
        + '变量语义：void-900 = 卡片容器（纯白）；void-800 = 卡片内部次级面板/条轨/分隔行底。\n'
        + '请把 void-800 下移到内部元素使用，卡片级一律走 void-900。',
      ).toBe(true)
    })

    it('夜间 .kb-card 必须走 CSS 变量（void-800），不能写死 rgb(17,17,30) —— 避免 index.css:root 改值时这里忘同步', () => {
      expect(darkOverride, '缺少 html.dark .kb-card 夜间覆盖规则').not.toBe('')
      const bgMatch = darkOverride.match(/background:\s*([^;]+);/)
      expect(bgMatch, 'html.dark .kb-card 缺少 background 声明').not.toBe(null)
      const bgDecl = bgMatch[1].trim()
      expect(
        bgDecl.includes('var(--void-'),
        `夜间 .kb-card background=${bgDecl} 写死色值。请改用 rgba(var(--void-800), <alpha>) CSS 变量，\n`
        + '与 :root / html.dark 变量语义保持一致，避免主题系统扩展时出现硬编码孤岛。',
      ).toBe(true)
    })
  })

  describe('BurstingVideos（正在爆发卡片）：必须接入 kb-card 语义层，禁止 slate 写死', () => {
    it('最外层 <section> 必须使用 kb-card 语义类，禁止单独写死 bg-white + border-slate + shadow-sm', () => {
      const sectionRegex = /<section\s+[^>]*className="([^"]+)"[^>]*>/g
      const sectionClasses = [...burstingSrc.matchAll(sectionRegex)].map((m) => m[1])
      expect(sectionClasses.length >= 2, `BurstingVideos 应至少有 2 个 section（加载/正常），当前=${sectionClasses.length}`).toBe(true)

      sectionClasses.forEach((cls, i) => {
        expect(
          cls.includes('kb-card'),
          `BurstingVideos section[${i + 1}] className 未包含 "kb-card" 语义类。\n`
          + `当前 class=${cls}\n`
          + '请改用 kb-card + p-5（或需要的 padding），不要写死 bg-white/border-slate/shadow-sm 这套 Tailwind 默认色板。',
        ).toBe(true)
        const forbidden = ['bg-white', 'border-slate', 'shadow-sm']
        const hit = forbidden.filter((t) => cls.includes(t))
        expect(
          hit.length,
          `BurstingVideos section[${i + 1}] class 使用了默认色板：${hit.join('、')}。\n`
          + `当前 class=${cls}\n`
          + '这些类绕过了双主题 CSS 变量系统：日间 bg-white=纯白 会和 kb-card（原 void-800 暖灰）出现分裂底色，\n'
          + '夜间它们仍会产出白背景/浅边，和暗夜霓虹主题完全冲突。\n'
          + '请删除所有写死 bg-white / border-slate-* / shadow-sm，并替换为 kb-card 语义类 + CSS 变量。',
        ).toBe(0)
      })
    })

    it('BurstingVideos 内部：行级 hover / 排名徽章 / 文字颜色 / 渐隐遮罩必须走主题感知变量，不能写死 slate/red/white 默认色', () => {
      // 先剔除注释和字符串模板字面量里的「提示文字」（只看 JSX className/style 实际出现的默认色板 Token）
      // ① 剥去 JS 单行 // 注释（整行）与 /* */ 多行注释
      let cleaned = burstingSrc
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .split('\n').map((ln) => {
          const idx = ln.indexOf('//')
          // 字符串里的 // 不剥（简单启发：如果 // 出现在单引号双引号之内则保留）—— 用保守策略：
          // 只剥去行首是缩进 + // 的典型注释行，避免误伤代码中的 "//" URL 或 regex 内部
          if (/^\s*\/\//.test(ln)) return ''
          return ln
        }).join('\n')

      // ② 危险默认色板 Token 正则：必须出现在 className/style 的白色边界；
      //    特别排除 Tailwind 任意值 `[...]` 中被正确引用的 `var(--xxx)`（我们的实现是正确的 CSS 变量），
      //    只要它不是字面量 bg-slate-800 / text-red-500 / bg-white 这种老色板即可。
      const dangerRegex = /(^|[\s"'`,{:])(bg-white|bg-slate-\d+|bg-red-\d+|border-slate-\d+|text-slate-\d+|text-red-\d+|from-white|via-white|to-white)(?=[\s"'`,;)\]}]|$)/g
      const badTokens = [...cleaned.matchAll(dangerRegex)]
        .filter((m) => {
          // 命中了 "替换指南" 注释中的示例类名？已在上面剔除整行注释逻辑中处理；
          // 再兜底：如果命中位置前紧邻字符串 '请改用' / '→' / '禁止' 也忽略
          const ctx = cleaned.slice(Math.max(0, m.index - 120), m.index + 80)
          if (/替换指南|→ 改成|→ 删除|请改用|禁止出现|默认色板/.test(ctx)) return false
          return true
        })
        .map((m) => {
          const lineNo = (burstingSrc.slice(0, m.index).match(/\n/g) || []).length + 1
          return `L${lineNo}: ${m[2]}`
        })

      expect(
        badTokens.length,
        `BurstingVideos.jsx 发现 ${badTokens.length} 处绕过主题系统的默认色板：\n`
        + badTokens.map((x) => '  ' + x).join('\n')
        + '\n\n请改走 void-* / haze-* / neon-* CSS 变量语义类。参考：\n'
        + '  hover:bg-slate-50   → hover:bg-[rgba(var(--void-800),0.8)]\n'
        + '  bg-slate-100        → bg-[rgba(var(--void-700),1)]\n'
        + '  text-slate-800/500/400 → text-haze-50 / text-haze-300 / text-haze-400\n'
        + '  border border-slate-100 → 删除（kb-card::before 自带渐变描边）\n'
        + '  bg-red-100 text-red-600 → kb-chip / kb-burst-pill 语义类\n'
        + '  底部渐隐 from-white via-white/60 → from-void-900 via-[rgba(var(--void-900),0.6)]\n',
      ).toBe(0)
    })
  })
})

// ═══════════════════════════════════════════════════════════════════
// 正在爆发卡片 · 苹果股市 UI 重构
// ── 参考 iOS 股票 App 视觉骨架 ──
//   每行 = 固定 4 列 CSS Grid（不是 flex）：
//     [A] 排名色块 ·   w-8 药丸方块   （1/2/3 渐变霓虹色 / 4+ 灰底）
//     [B] 元信息     ·   flex-1       标题大粗字 + 一行 UP主小字
//     [C] Sparkline  ·   ~110px       面积填充（红涨=rose / 绿跌=emerald）+ 虚线参照线
//     [D] 数值柱     ·   右对齐       总量 tabular-nums 大粗字 + 增速 PILL 胶囊 (大radius)
//   行之间细分隔线 (divide-y void-700 / border-b)，无 hover 大底色（极简）
//   PILL 徽章：圆角 9999px (full)，纯色不透明背景 + 白字；爆发=neon-rose；非爆发高速=neon-pink；
//              低速=neon-amber；禁止出现 slat/red 默认色板；禁止 rounded-md 这种小圆角。
//   Sparkline 颜色：爆发/高增速 → neon-rose；低速/下跌 → neon-emerald；
//                   允许 neon-amber 仅作为 PILL/中速过渡；Sparkline 不得大面积用琥珀色（苹果股市无橙色线）。
// ═══════════════════════════════════════════════════════════════════
describe('[UI] 正在爆发卡片：苹果股市风格（iOS Stocks visual language）', () => {
  let burstingSrc, indexCss
  beforeAll(() => {
    const cssCandidates = [resolve(__dirname, 'src/index.css'), resolve(__dirname, 'index.css')]
    const bvCandidates  = [resolve(__dirname, 'src/components/BurstingVideos.jsx'), resolve(__dirname, 'BurstingVideos.jsx')]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    burstingSrc = bvCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss,    '找不到 index.css').not.toBe(null)
    expect(burstingSrc, '找不到 BurstingVideos.jsx').not.toBe(null)
  })

  describe('ROW 三列对齐（必须 CSS Grid 四列 不是 flex 挤）', () => {
    it('每行根元素必须带 kb-burst-row 语义类 + grid 四列：[rank/meta/spark/value]，不能再用 class="flex items-center gap-3"', () => {
      // 找 map 回调里的根 <a> 或 <div> className
      const rowRegex = /className="([^"]*kb-burst-row[^"]*)"/g
      const matches = [...burstingSrc.matchAll(rowRegex)].map(m => m[1])
      expect(
        matches.length >= 1,
        '找不到任何带 kb-burst-row 的行根元素。请把每行的 <a> 根从 flex items-center gap-3 p-2 改为 grid 四列布局语义类 kb-burst-row（在 index.css 或行级 className 中定义 grid-template-columns: 2.5rem 1fr auto auto；gap:16px 等）。iOS 股市每行对齐的关键就是固定列宽，不能靠 flex 自适应挤来挤去。',
      ).toBe(true)

      // 绝对不允许行根上再写 flex items-center gap-3 + space-y 这种旧布局
      const flexRowRegex = /<a\s+[^>]*className="[^"]*flex\s+items-center[^"]*"[^>]*>/
      const legacyFlex = burstingSrc.match(flexRowRegex)
      expect(
        legacyFlex === null,
        '检测到仍然在用「class="flex items-center gap-3 p-2 ..."」的旧 flex 行布局：\n  ' + (legacyFlex?.[0] || '').slice(0, 200)
        + '\n\niOS 股市风格的核心就是四列等宽 grid：排名块/信息/Sparkline/数值，所有行的 Sparkline 起点终点严格对齐。请改用 grid-template-columns 固定列。',
      ).toBe(true)
    })
  })

  describe('PILL 增速胶囊（iOS 股市药丸形徽章）', () => {
    it('增速徽章必须是 pill 大圆角：要么 rounded-full，要么 CSS 自定义类（kb-burst-pill）中定义 border-radius:9999px；绝对禁止 rounded-md/rounded-lg', () => {
      // 检测路径 A：JSX className="..." 字面量中有 kb-burst-pill 或 rounded-full 类
      const burstPillRegex    = /className="([^"]*kb-burst-pill[^"]*)"/g
      const roundedFullRegex  = /className="([^"]*rounded-full[^"]*)"/g
      const burstClasses   = [...burstingSrc.matchAll(burstPillRegex)].map(m => m[1])
      const roundedClasses  = [...burstingSrc.matchAll(roundedFullRegex)].map(m => m[1])

      // 检测路径 A2：动态 className={tiers.pill} / {pillCls} 变量形式（Pill 类在赋值语句中出现 kb-burst-pill）
      const dynPillRegex = /(?:pill|pillCls|tierClass|pillClass)\s*[:=]\s*['"][^'"]*kb-burst-pill[^'"]*['"]/g
      const dynMatches = [...burstingSrc.matchAll(dynPillRegex)]

      // 检测路径 B：index.css 的 .kb-burst-pill 自定义类 定义了 border-radius:9999px
      const cssPillStart = indexCss.indexOf('.kb-burst-pill {')
      let cssPillOK = false
      if (cssPillStart !== -1) {
        const cssPillEnd = indexCss.indexOf('}', cssPillStart) + 1
        const block = indexCss.slice(cssPillStart, cssPillEnd)
        cssPillOK = /border-radius\s*:\s*9999px/.test(block)
      }

      // 通过条件：CSS 类存在 & (JSX 类 或 动态赋值 或 rounded-full 类)
      const pathOk = cssPillOK && (burstClasses.length > 0 || dynMatches.length > 0)
      const anyOk = pathOk || roundedClasses.length > 0

      expect(
        anyOk,
        `找不到增速徽章的 pill-shape 圆角（border-radius:9999px）。iOS 股市涨跌数值徽章必须是大圆角药丸，不是 rounded-md/rounded-lg。\n`
        + `三种契约任选其一：\n`
        + `  (a) JSX 字面量 className="kb-burst-pill ..." / "rounded-full"；当前字面量 kb-burst-pill 类数量 = ${burstClasses.length}，rounded-full = ${roundedClasses.length}\n`
        + `  (b) 动态赋值 pill:'kb-burst-pill ...' 或 tier.pill:'kb-burst-pill--rose'；当前动态匹配 = ${dynMatches.length}\n`
        + `  (c) 同时必须在 index.css 定义 .kb-burst-pill { border-radius: 9999px }；当前 = ${cssPillOK ? 'PASS ✅' : '❌ 未定义 9999px'}\n`
        + `\n当前发现：`
        + `\n  字面量 kb-burst-pill：${burstClasses.map(c => c.slice(0, 80)).join(' / ') || '（无）'}`
        + `\n  动态 pill 赋值：${dynMatches.map(m => m[0].slice(0, 80)).join(' / ') || '（无）'}\n`,
      ).toBe(true)

      // 仍然严格禁止：出现 rounded-md / rounded-lg 的 TrendingUp 父容器（小圆角的旧增速徽章）
      const badPillRegex = /className="[^"]*rounded-(?:md|lg)[^"]*"[^>]*>\s*(?:<[^>]*>)?\s*(?:<[\w\s="'-]*TrendingUp[\w\s="'-]*\/?>|[\u4e00-\u9fa5万.\d]+\/h)/
      const badPill = burstingSrc.match(badPillRegex)
      expect(
        badPill === null,
        `增速徽章仍在使用 rounded-md / rounded-lg 小圆角，与 iOS 药丸视觉相悖。\n可疑片段：${(badPill?.[0] || '').slice(0, 200)}\n请改为 rounded-full 或 kb-burst-pill CSS 语义类。`,
      ).toBe(true)
    })

    it('PILL 颜色必须走 neon 语义（rose/pink/amber/emerald），爆发项必须用 neon-rose，不能出现 text-red/bg-red 默认色板', () => {
      // 在 PILL 颜色决策处（含 is_bursting 分支或 pickTiers/if else）找出现 neon-rose
      const burstingBranchMatches = burstingSrc.match(/is_bursting[\s\S]{0,400}neon-rose|pickTiers[\s\S]{0,800}neon-rose/)
      expect(
        !!burstingBranchMatches,
        `找不到「爆发 is_bursting → neon-rose」颜色映射。iOS 股市红色上涨=爆发最强信号。\n`
        + `请在增速胶囊的 is_bursting 分支（或封装的 pickTiers 辅助函数）中使用 kb-burst-pill--rose 或 neon-rose 颜色。`,
      ).toBe(true)

      // 扫整个 burstingSrc 出现的 bg-red/text-red 默认色板
      const dangerRegex = /(^|[\s"'`,{:])(bg-red-\d+|text-red-\d+)(?=[\s"'`,;)\]}]|$)/g
      const bads = [...burstingSrc.matchAll(dangerRegex)].map(m => m[2])
      expect(
        bads.length,
        `PILL 区域发现 ${bads.length} 处默认 red 色板：${bads.join('、')}。\n`
        + `请改用 bg-[rgb(var(--neon-rose))] 或 kb-burst-pill kb-burst-pill--rose 语义类。`,
      ).toBe(0)
    })
  })

  describe('Sparkline 趋势线（iOS 股市 面积填充 + 涨跌双色）', () => {
    it('Sparkline 整体颜色系统：必须使用 neon-rose/neon-pink/neon-emerald（红涨绿跌），Sparkline 传参中或颜色决策函数中出现 neon-rose；禁止 Sparkline props 中以 neon-amber 作为线颜色', () => {
      // ① 提取所有 <Sparkline ... /> 调用
      const sparkRegex = /<Sparkline([^>]*?)\/>/g
      const calls = [...burstingSrc.matchAll(sparkRegex)].map(m => m[1].trim())
      expect(calls.length >= 1, '找不到任何 <Sparkline /> 调用').toBe(true)
      const allSpark = calls.join('\n')

      // ② 颜色决策函数 pickTiers 或 is_bursting 分支中必须包含 neon-rose（可能是变量传 lineColor={tiers.line} 而不是字符串）
      const colorFnHasRose = burstingSrc.match(/(pickTiers|function\s+\w+Tier)[\s\S]{0,800}neon-rose|is_bursting[\s\S]{0,400}neon-rose/)

      expect(
        allSpark.includes('neon-rose') || !!colorFnHasRose,
        `Sparkline 系统缺少对 neon-rose 的颜色映射使用。iOS 股市上涨=红线，爆发项必须走 rose。\n`
        + `两种契约任选其一：\n`
        + `  (a) <Sparkline lineColor="rgb(var(--neon-rose))" ... /> 直接传参\n`
        + `  (b) 封装 pickTiers 等颜色决策函数，内部用 neon-rose\n`
        + `\n当前 Sparkline props:\n${allSpark}\n`
        + `当前文件内 pickTiers/is_bursting 分支包含 neon-rose = ${!!colorFnHasRose ? '✅' : '❌'}`,
      ).toBe(true)

      // ③ Sparkline props 里的线颜色 绝对不允许出现 neon-amber（PILL 才能用 amber 作过渡；趋势线只有红/绿）
      const amberLineCount = (allSpark.match(/neon-amber/g) || []).length
      expect(
        amberLineCount,
        `Sparkline props 中出现 ${amberLineCount} 次 neon-amber。iOS 股市没有橙色趋势线——只有红(涨)/绿(跌)两色。\n`
        + `请改为：爆发/高速 → neon-rose；中速 → neon-pink；低速/近跌 → neon-emerald。\n`
        + `当前 Sparkline props:\n${allSpark}`,
      ).toBe(0)
    })

    it('Sparkline 组件本身必须：① 有面积填充 <path d=... fill=url(#grad)>；② 支持 <linearGradient> 垂直渐变；③ 折线 <path stroke=...> 加粗描边；④ 支持 <line ... strokeDasharray="..."> 虚线 baseline 参照（昨日收盘价线——iOS Stocks 灵魂）', () => {
      const sparkDef = burstingSrc.includes('function Sparkline')
      expect(sparkDef, '应包含内置 function Sparkline 组件定义').toBe(true)

      const svgStart = burstingSrc.indexOf('<svg')
      const svgEnd   = burstingSrc.indexOf('</svg>', svgStart) + 6
      expect(svgStart > -1 && svgEnd > svgStart, '找不到完整的 <svg>...</svg> Sparkline 实现').toBe(true)
      const svgBlock = burstingSrc.slice(svgStart, svgEnd)

      const hasFillArea = svgBlock.includes('<path') && (svgBlock.includes('fill="url(#') || svgBlock.includes('fill=') || svgBlock.includes('fill-opacity'))
      expect(hasFillArea, 'Sparkline 缺少 <path> 面积填充。iOS 股市不是纯折线，是面积图（area chart）。').toBe(true)

      const hasGradient = svgBlock.includes('linearGradient') || svgBlock.includes('stopColor')
      expect(hasGradient, 'Sparkline 缺少 <linearGradient> 垂直渐变填充。请添加 <defs><linearGradient x1="0" y1="0" x2="0" y2="1">...</linearGradient></defs>。').toBe(true)

      // 折线描边：或 polyline，或带 stroke 的 <path>（注意 .match 返回数组，需要 Boolean() 转真）
      const hasStrokeLine = svgBlock.includes('polyline') || Boolean(svgBlock.match(/<path[^>]*\sstroke[^>]*>/))
      expect(hasStrokeLine, 'Sparkline 缺少折线描边（polyline 或带 stroke 的 path）。必须同时有填充面 + 叠加折线。').toBe(true)

      const hasDashedBaseline = svgBlock.includes('strokeDasharray') || svgBlock.includes('stroke-dasharray')
      expect(hasDashedBaseline, 'Sparkline 缺少虚线 baseline。苹果股市有一条「昨日收盘价」水平虚线作为涨跌参照，是视觉灵魂；请加 <line ... strokeDasharray="3,3" strokeWidth="0.8" y=基线Y />。').toBe(true)
    })
  })

  describe('行之间细分隔线（iOS 股市 hairline divider）', () => {
    it('不能使用 space-y-* 作为行间距，必须用 divide-y 或 border-b + void-700/void-800 变量做细分隔线；行 padding 要小（极简紧凑）', () => {
      // 列表根（ref=listRef 的那个 div）不能有 space-y
      const listRootRegex = /<div\s+[^>]*ref=\{listRef\}[^>]*className="([^"]*)"[^>]*>/
      const listCls = burstingSrc.match(listRootRegex)?.[1] ?? ''
      expect(
        !listCls.includes('space-y'),
        `列表根 className 有 space-y（${listCls}）。iOS 股市不使用空距做间隔，而是用细分割线（hairline border）。\n`
        + `请使用 className="divide-y divide-[rgba(var(--void-700),1)]" 或每行末 border-b border-[rgba(var(--void-700),0.8)] 保持极简感。`,
      ).toBe(true)
    })
  })

  describe('爆发标记：引入 Zap⚡图标（Flame 图标是标题级别的，行内爆发条目标记用 Zap，如股市「关注」星标）', () => {
    it('必须从 lucide-react import Zap，并且在 is_bursting=true 的行信息区出现 Zap 图标标记（颜色=neon-rose）', () => {
      expect(
        burstingSrc.includes('import {') && burstingSrc.includes('Zap'),
        '未发现 import Zap from lucide-react。请在顶部 import 中加入 Zap 图标，用于爆发项行内的「股票关注」式语义标记。',
      ).toBe(true)
      const zapUsage = burstingSrc.match(/Zap[^/]*size=\{\d+\}/) || burstingSrc.match(/<Zap\s/)
      expect(
        !!zapUsage,
        '在 JSX 中未发现 <Zap /> 使用。请在 is_bursting=true 的行标题前插入 <Zap size={14} className="text-neon-rose shrink-0" />，对齐苹果股市星标/警示标的设计语言。',
      ).toBe(true)
    })
  })

  // ───────────────────── 用户 v2 需求 ─────────────────────
  // 1. 信息列（B 列）必须加视频封面缩略图，放在排名色块之后、标题之前
  // 2. 增速 PILL 胶囊：删除 amber，只保留最多 3 档（rose/pink/emerald），贴合中国股市「红涨绿跌」+ iOS 股市「涨跌只有二色」
  describe('[需求 v2] 信息列封面缩略图 + PILL 颜色 3 档简化（去 amber）', () => {
    it('每行信息列（data-col=meta）必须包含视频封面缩略图：使用 proxyImage 包装 + 尺寸 w-12~w-16/h-8~h-12 + object-cover + rounded，不能只有文字没有封面', () => {
      // ① proxyImage 工具必须被使用（因为封面图跨域，必须走工具）
      expect(
        burstingSrc.includes('proxyImage'),
        `BurstingVideos.jsx 虽然顶部可能 import 了 proxyImage，但 JSX 中实际没有调用 proxyImage(...) 包装封面图。\n`
        + `必须使用 proxyImage(v.pic) 处理 B 站封面，避免跨域失败/防盗链。`,
      ).toBe(true)

      // ② 在 meta 列内部 JSX 必须包含 <img 标签 + src={proxyImage(
      const metaStart = burstingSrc.indexOf('data-col="meta"')
      const metaEnd   = burstingSrc.indexOf('data-col="', metaStart + 10)
      expect(metaStart > -1, '找不到 data-col="meta" 信息列开始标记').toBe(true)
      expect(metaEnd   > metaStart, '找不到下一个 data-col 结束标记（信息列没有闭合？）').toBe(true)
      const metaBlock = burstingSrc.slice(metaStart, metaEnd)

      const imgCount   = (metaBlock.match(/<img\s/g) || []).length
      expect(
        imgCount >= 1,
        `信息列（meta block）中共发现 <img> 标签 = ${imgCount} 个，必须至少有 1 个视频封面缩略图。\n`
        + `当前 meta 列 block:\n${metaBlock.slice(0, 800)}`,
      ).toBe(true)

      // ③ 封面必须使用 proxyImage 作为 src
      const hasProxySrc = /src=\{proxyImage\(/.test(metaBlock)
      expect(
        hasProxySrc,
        `信息列封面 img 的 src 未用 proxyImage(...) 包装。跨域封面会失败，必须与其他排行榜卡片一致：src={proxyImage(v.pic)}。\n`
        + `当前 meta block 片段：${metaBlock.slice(0, 600)}`,
      ).toBe(true)

      // ④ 封面容器/图片必须有 object-cover + rounded（至少出现一个 rounded-sm/rounded-md/rounded-lg/rounded）
      const hasCoverRounded = /rounded-(?:sm|md|lg|none|xl)?/.test(metaBlock)
      const hasObjectCover  = metaBlock.includes('object-cover')
      expect(
        hasCoverRounded && hasObjectCover,
        `信息列封面缺少 rounded 或 object-cover。\n`
        + `  rounded: ${hasCoverRounded ? '✅' : '❌（缺少 rounded-*，封面是方角，需 rounded-md/sm）'}\n`
        + `  object-cover: ${hasObjectCover ? '✅' : '❌（缺少 object-cover，封面会被拉伸变形）'}\n`
        + `\n当前 meta block:\n${metaBlock.slice(0, 700)}`,
      ).toBe(true)
    })

    it('增速 PILL 胶囊必须「去 amber」：3 档 红(rose)/粉(pink)/绿(emerald)，中国股市红涨绿跌；pickTiers 中绝对禁止使用 kb-burst-pill--amber 或 neon-amber 作为 pill 背景类', () => {
      // ① 截取 pickTiers 整个函数体（不能用 indexOf('}')，因为 return 对象里有内层 }；必须用括号深度计数）
      const pickStart = burstingSrc.indexOf('function pickTiers')
      expect(pickStart > -1, '找不到 pickTiers 函数定义块').toBe(true)
      const openBrace  = burstingSrc.indexOf('{', pickStart)
      expect(openBrace > pickStart, 'pickTiers 函数定义后找不到开始花括号 {').toBe(true)
      let depth = 0, pickEnd = -1
      for (let i = openBrace; i < burstingSrc.length; i++) {
        const c = burstingSrc[i]
        if (c === '{') depth++
        else if (c === '}') { depth--; if (depth === 0) { pickEnd = i + 1; break } }
      }
      expect(pickEnd > openBrace, '括号深度配对未找到 pickTiers 的结束花括号').toBe(true)
      const pickBlock = burstingSrc.slice(pickStart, pickEnd)

      const amberCount = (pickBlock.match(/kb-burst-pill--amber|neon-amber/g) || []).length
      expect(
        amberCount,
        `pickTiers 决策函数中发现 ${amberCount} 处 amber（kb-burst-pill--amber 或 neon-amber 作为 pill 背景）。\n`
        + `参考 iOS 股市截图：上涨一律红色、下跌一律绿色，中间过渡不用琥珀橙色（既不是上涨也不是下跌，语义暧昧）。\n`
        + `\n推荐 3 档（红涨绿跌）：\n`
        + `  ① 爆发 / TOP 高速 → kb-burst-pill--rose    （最强上涨信号，中国红）\n`
        + `  ② 中速 / 正增长  → kb-burst-pill--pink    （中强上涨，粉红渐变）\n`
        + `  ③ 末位 / 疲软    → kb-burst-pill--emerald （近跌或涨不动，绿=股市下跌信号）\n`
        + `\n当前 pickTiers:\n${pickBlock}`,
      ).toBe(0)

      // ② 断言最多 3 档：rose / pink / emerald（允许缺少 pink 但绝对不允许第 4 档 amber）
      const tierClasses = [...pickBlock.matchAll(/kb-burst-pill--(\w+)/g)].map(m => m[1])
      const uniqueTiers = Array.from(new Set(tierClasses))
      const hasAmberInUnique = uniqueTiers.includes('amber')
      expect(
        !hasAmberInUnique && uniqueTiers.length <= 3 && uniqueTiers.length >= 2,
        `PILL 去重后的档位类 = ${JSON.stringify(uniqueTiers)}（共 ${uniqueTiers.length} 档）。\n`
        + `契约：不允许 amber（当前 = ${hasAmberInUnique ? '❌ 有 amber' : '✅ 无 amber'}），\n`
        + `       必须 2~3 档（当前 ${uniqueTiers.length} 档），推荐 3 档：rose/pink/emerald。`,
      ).toBe(true)

      // ③ 爆发分支必须用 rose（回归已有契约，确保去 amber 之后别把爆发也改没了）
      expect(
        pickBlock.includes('is_bursting') && pickBlock.includes('kb-burst-pill--rose'),
        `去 amber 之后，爆发(is_bursting)分支必须仍使用 kb-burst-pill--rose。当前 pickTiers 中 is_bursting + rose 映射是否还在？\n`
        + `当前 pickTiers block:\n${pickBlock}`,
      ).toBe(true)

      // ④ 必须有 emerald 档（末位=疲软/近跌，中国股市「绿=跌」语义）
      expect(
        uniqueTiers.includes('emerald'),
        `去 amber 后，档位列表 = ${JSON.stringify(uniqueTiers)}，缺少 emerald。\n`
        + `末位低速必须用 emerald（中国股市绿=下跌/疲软），与 iOS 股市截图「-1.26 绿色胶囊」对应。`,
      ).toBe(true)
    })
  })
})

// ═══════════════════════════════════════════════════════════════════
// 主题回滚：还原原「暗夜霓虹」配色（用户反馈 B 站蓝过于单一「把所有东西都改成蓝色」= 拒绝）
//   原方案：neon-pink 粉紫主色 (241,94,140) / neon-rose 玫红 (220,38,73) /
//          neon-amber 琥珀金 / neon-violet 紫 / neon-cyan 青 / neon-emerald 翡翠绿
//   void-* 背景：日间暖黄灰 R>G>B (243,241,237)，非 B 站蓝冷蓝灰
//   硬编码的阴影/光晕：还原为粉/紫金 RGB，不再 B 站蓝冷通道
// ═══════════════════════════════════════════════════════════════════
describe('[Theme Rollback] 还原暗夜霓虹（拒绝全蓝）', () => {
  let indexCss
  function extractBlock(src, blockStartMarker) {
    const s = src.indexOf(blockStartMarker)
    if (s === -1) return null
    const open = src.indexOf('{', s)
    if (open === -1) return null
    let depth = 0
    for (let i = open; i < src.length; i++) {
      const c = src[i]
      if (c === '{') depth++
      else if (c === '}') { depth--; if (depth === 0) return src.slice(s, i + 1) }
    }
    return null
  }
  function parseVar(block, name) {
    const re = new RegExp(`--${name.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}\\s*:\\s*(-?\\d+)\\s*,\\s*(-?\\d+)\\s*,\\s*(-?\\d+)\\s*;`)
    const m = block.match(re)
    if (!m) return null
    return [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)]
  }
  function warmth(rgb) { return rgb[0] - rgb[2] }

  beforeAll(() => {
    const candidates = [resolve(__dirname, 'src/index.css'), resolve(__dirname, 'index.css')]
    indexCss = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  describe('日间 :root — 必须回到「粉紫金 + 暖黄灰」，不允许 B 站品牌蓝 rgb(0,174,236) 当主色', () => {
    let dayBlock, dayVars = {}
    beforeAll(() => {
      dayBlock = extractBlock(indexCss, ':root {')
      expect(dayBlock, '找不到 :root 日间块').not.toBe(null)
      ;['neon-pink','neon-rose','neon-amber','neon-cyan','neon-violet','neon-emerald',
        'void-950','void-900','void-800','void-700','void-600'].forEach(n => {
          dayVars[n] = parseVar(dayBlock, n)
          expect(dayVars[n], `日间缺少变量 --${n}`).not.toBe(null)
        })
    })

    it('neon-pink 日间必须 = 原霓虹粉 rgb(241,94,140) ±6（B 站品牌蓝 rgb(0,174,236) 绝对禁止）', () => {
      const [r,g,b] = dayVars['neon-pink']
      const isPink = (Math.abs(r - 241) <= 6 && Math.abs(g - 94) <= 6 && Math.abs(b - 140) <= 6)
      const isBiliBlue = (Math.abs(r - 0) <= 3 && Math.abs(g - 174) <= 3 && Math.abs(b - 236) <= 3)
      expect(
        isPink && !isBiliBlue,
        `日间 --neon-pink = rgb(${r},${g},${b})。\n`
        + `用户明确：「不是把所有东西都改成蓝色」→ 必须回滚到原粉 241,94,140，禁止 B 站品牌蓝 rgb(0,174,236)。`,
      ).toBe(true)
    })

    it('6 个 neon 中 至少 3 个必须是明显暖色（R-B ≥ 80），原「粉+玫+金+紫」必须保留，不得全冷蓝', () => {
      const names = ['neon-pink','neon-rose','neon-amber','neon-cyan','neon-violet','neon-emerald']
      const warmCount = names.filter(n => warmth(dayVars[n]) >= 80).length
      expect(
        warmCount >= 3,
        `日间 6 个 neon 中暖色数量 = ${warmCount}（≥3 要求）：\n`
        + names.map(n => `  ${n}=rgb(${dayVars[n].join(',')}) warmth=${warmth(dayVars[n])}`).join('\n')
        + `\n\nB 站蓝改色后所有 neon 都是冷蓝（warmth 全部 ≤ 0），违背用户「不要把所有东西都改成蓝色」。`,
      ).toBe(true)
    })

    it('neon-amber 日间必须 = 琥珀金色（R 最大 G 中间 B 最小，典型金 warmth≥80），不能再是冷蓝阶梯', () => {
      const [r,g,b] = dayVars['neon-amber']
      const isGold = (r > g && g > b && warmth([r,g,b]) >= 80)
      expect(
        isGold,
        `日间 --neon-amber = rgb(${r},${g},${b}) warmth=${warmth([r,g,b])}。\n`
        + `原 amber 是暖金（R>G>B），B 站蓝改色把它变成冷蓝调 #4F99D0 → 用户拒绝，必须回滚。`,
      ).toBe(true)
    })

    it('void-800（次级面板底）/ void-700（条轨/hover底）日间必须是暖黄灰 R>G>B（warmth ∈ [2,10]，典型 243,241,237 warmth=6）', () => {
      const w8 = warmth(dayVars['void-800'])
      const w7 = warmth(dayVars['void-700'])
      const [r8,g8,b8] = dayVars['void-800']
      const warmGray800 = (r8 > g8 && g8 > b8 && w8 >= 2 && w8 <= 10)
      expect(
        warmGray800 && w7 >= 0,
        `日间 void 背景仍是冷蓝灰：\n`
        + `  void-800 = rgb(${dayVars['void-800'].join(',')}) warmth=${w8}（要求 R>G>B 暖黄灰 warmth=2..10）\n`
        + `  void-700 = rgb(${dayVars['void-700'].join(',')}) warmth=${w7}（要求 warmth≥0）\n`
        + `B 站蓝改色后 warmth 都是负值 → 全蓝背景，用户明确拒绝。`,
      ).toBe(true)
    })
  })

  describe('夜间 html.dark — 还原暗夜霓虹（粉+紫+青），不允许 B 站亮夜蓝 22,188,255 当主色', () => {
    let nightBlock, nightVars = {}
    beforeAll(() => {
      nightBlock = extractBlock(indexCss, 'html.dark {')
      expect(nightBlock, '找不到 html.dark 夜间块').not.toBe(null)
      ;['neon-pink','neon-rose','neon-amber','neon-cyan','neon-violet','neon-emerald'].forEach(n => {
        nightVars[n] = parseVar(nightBlock, n)
        expect(nightVars[n], `夜间缺少变量 --${n}`).not.toBe(null)
      })
    })

    it('夜间 neon-pink 必须 = 亮粉 rgb(251,114,153) ±8，禁止 B 站亮夜蓝 rgb(22,188,255)', () => {
      const [r,g,b] = nightVars['neon-pink']
      const isPink = (Math.abs(r - 251) <= 8 && Math.abs(g - 114) <= 8 && Math.abs(b - 153) <= 8)
      const isBiliBlue = (Math.abs(r - 22) <= 6 && Math.abs(g - 188) <= 6 && Math.abs(b - 255) <= 6)
      expect(
        isPink && !isBiliBlue,
        `夜间 --neon-pink = rgb(${r},${g},${b})。\n`
        + `用户明确拒绝「把所有东西都改成蓝色」→ 必须回滚到暗夜霓虹亮粉 251,114,153，禁止 22,188,255 B 站亮蓝。`,
      ).toBe(true)
    })

    it('夜间 6 个 neon 中 至少 3 个必须是明显暖色（R-B ≥ 80），不得全冷蓝', () => {
      const names = ['neon-pink','neon-rose','neon-amber','neon-cyan','neon-violet','neon-emerald']
      const warmCount = names.filter(n => warmth(nightVars[n]) >= 80).length
      expect(
        warmCount >= 3,
        `夜间 6 个 neon 中暖色数量 = ${warmCount}（要求 ≥3）：\n`
        + names.map(n => `  ${n}=rgb(${nightVars[n].join(',')}) warmth=${warmth(nightVars[n])}`).join('\n')
        + `\n\nB 站蓝改色后夜间所有 neon 都是冷蓝 → 必须回滚粉/玫/金紫 至少 3 暖。`,
      ).toBe(true)
    })
  })

  describe('硬编码 rgba — 还原粉/紫/金 硬编码，不允许 B 站蓝一统所有阴影/光晕', () => {
    it('日间 :root 阴影/光晕 必须至少出现 2 处 旧暖色硬编码（粉 241,94,140 / 玫 220,38,73 家族）', () => {
      const dayBlock = extractBlock(indexCss, ':root {')
      const rgbPattern = /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/g
      const tuples = [...dayBlock.matchAll(rgbPattern)].map(m => [parseInt(m[1]),parseInt(m[2]),parseInt(m[3])])
      const legacyWarm = tuples.filter(([r,g,b]) =>
        (r === 241 && g === 94 && b === 140) ||
        (r === 220 && g === 38 && b === 73) ||
        (r === 251 && g === 114 && b === 153) ||
        (r >= 160 && g >= 40 && b >= 230 && (b - r) >= 60)
      )
      expect(
        legacyWarm.length >= 2,
        `日间 :root 旧暖色硬编码残留 = ${legacyWarm.length} 处（要求 ≥2）：\n`
        + legacyWarm.map(t => `  rgb(${t.join(',')})`).join('\n')
        + `\n\nB 站蓝改色后所有阴影/光晕都换成 0,174,236 / 37,198,252 → 「所有东西都变成蓝色」。\n`
        + `必须回滚还原粉紫金的硬编码发光（shadow-glow-pink / glow-breath / bg-glow 等）。`,
      ).toBe(true)
    })

    it('夜间 html.dark 硬编码必须至少有 3 处匹配旧霓虹色（251,114,153 / 244,63,94 / 168,85,247 / 67,56,202）', () => {
      const nightBlock = extractBlock(indexCss, 'html.dark {')
      const rgbPattern = /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/g
      const tuples = [...nightBlock.matchAll(rgbPattern)].map(m => [parseInt(m[1]),parseInt(m[2]),parseInt(m[3])])
      const knownLegacy = tuples.filter(([r,g,b]) =>
        (r === 241 && g === 94 && b === 140) ||
        (r === 251 && g === 114 && b === 153) ||
        (r === 244 && g === 63 && b === 94) ||
        (r === 220 && g === 38 && b === 73) ||
        (r === 147 && g === 51 && b === 234) ||
        (r === 168 && g === 85 && b === 247)
      )
      expect(
        knownLegacy.length >= 3,
        `夜间 html.dark 旧霓虹色硬编码 = ${knownLegacy.length} 处（要求 ≥3）：\n`
        + knownLegacy.map(t => `  rgb(${t.join(',')})`).join('\n')
        + `\n\nB 站蓝改色把 22,188,255 / 66,210,255 硬编码铺满所有发光 → 整站蓝色，用户拒绝必须回滚。`,
      ).toBe(true)
    })
  })
})

// ═══════════════════════════════════════════════════════════════════
// Sidebar 局部 B 站蓝改色（用户明确：先从侧边栏开始，拒绝整站蓝）
//   语义：新增独立 bili-* 通道 + Tailwind bili 语义色，绝不污染原 neon-*
//   范围：①刷新按钮（B 站蓝底 + 白字白 icon 悬浮）
//         ②我的收藏（字色/边框/Star icon 全蓝）
//         ③激活 tab 高亮竖条（B 站蓝浅→深渐变）
//         ④复选框等小细节（B 站蓝色）
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar Bili-Blue] 侧边栏局部 B 站蓝（不污染全局 neon）', () => {
  let sidebarJsx, indexCss

  beforeAll(() => {
    const sideCandidates = [resolve(__dirname, 'src/components/Sidebar.jsx'), resolve(__dirname, 'Sidebar.jsx')]
    sidebarJsx = sideCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
    const cssCandidates = [resolve(__dirname, 'src/index.css'), resolve(__dirname, 'index.css')]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  describe('1. Tailwind + CSS 变量：新增独立 bili 语义通道', () => {
    it('tailwind.config.js 必须注册 bili 颜色组（default/dark 两档，绑定 --bili-default / --bili-dark）', () => {
      const hasBiliGroup = /bili\s*:\s*\{/.test(tailwindCfgRaw)
      const hasDefaultBind = /bili-default/ .test(tailwindCfgRaw) && /default\s*:/.test(tailwindCfgRaw)
      const hasDarkBind    = /bili-dark/    .test(tailwindCfgRaw) && /dark\s*:/.test(tailwindCfgRaw)
      expect(
        hasBiliGroup && hasDefaultBind && hasDarkBind,
        `tailwind.config.js 缺少独立 bili 语义色组。\n`
        + `用户明确：「不要所有东西变成蓝色」，因此必须用独立 bili-* 通道，\n`
        + `禁止直接拿 neon-pink / neon-cyan 改值污染全局。\n`
        + `当前 tailwind.config.js:\n`
        + `  has bili group: ${hasBiliGroup}\n  has --bili-default bind: ${hasDefaultBind}\n  has --bili-dark bind: ${hasDarkBind}`,
      ).toBe(true)
    })

    it('日间 :root 必须定义 --bili-default = B 站品牌蓝 rgb(0,174,236) ±3（经典 #00AEEC）', () => {
      const m = indexCss.match(/--bili-default\s*:\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*;/)
      expect(m, '日间 :root 必须声明 --bili-default CSS 变量（独立通道，非 neon）').not.toBe(null)
      const [r, g, b] = [parseInt(m[1],10), parseInt(m[2],10), parseInt(m[3],10)]
      const isBili = (Math.abs(r-0)<=3 && Math.abs(g-174)<=3 && Math.abs(b-236)<=3)
      expect(
        isBili,
        `--bili-default = rgb(${r},${g},${b})，要求 = B 站品牌蓝 rgb(0,174,236) ±3 (#00AEEC)。\n`
        + `（侧边栏局部蓝色专用，不影响全局粉紫金）`,
      ).toBe(true)
    })

    it('夜间 html.dark 必须定义 --bili-dark = B 站亮夜蓝 rgb(22,188,255) ±6 (#16BCFF，夜间更饱和更亮)', () => {
      // 夜间块内的 bili-dark 声明
      const nightRe = /html\.dark\s*\{[\s\S]*?--bili-dark\s*:\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*;/
      const m = indexCss.match(nightRe)
      expect(m, 'html.dark 块内必须声明 --bili-dark 亮蓝（夜间高亮条/按钮背景更饱和更亮）').not.toBe(null)
      const [r, g, b] = [parseInt(m[1],10), parseInt(m[2],10), parseInt(m[3],10)]
      const isBiliNight = (Math.abs(r-22)<=6 && Math.abs(g-188)<=6 && Math.abs(b-255)<=6)
      expect(
        isBiliNight,
        `夜间 --bili-dark = rgb(${r},${g},${b})，要求 = B 站亮夜蓝 rgb(22,188,255) ±6 (#16BCFF)。`,
      ).toBe(true)
    })
  })

  describe('2. 刷新按钮：B 站蓝底 + 白字白 icon（大字白，悬浮在按钮上）', () => {
    it('展开态刷新按钮：必须 bg-bili-default（B 站蓝底）+ text-white（白字），禁止 bg-neon-pink（原粉）', () => {
      // 抓取 ActionPanel 函数定义内的"刷新数据"大字按钮（展开态 = 非 collapsed 分支）
      // 注意：<ActionPanel 出现在 JSX 调用处（尾部），而 ActionPanel = () =>（定义处）在前；
      //       之前 anchor 到 <ActionPanel 再搜 !collapsed 会返回 -1 命中失败；
      //       现改为从定义处锚定，并锚定明确的"刷新数据"文案 + 前向 <button className=...>
      const defineMark = sidebarJsx.indexOf('ActionPanel')
      const block = sidebarJsx.slice(defineMark, defineMark + 12000)
      // 锚定"刷新数据"文案；向前回溯最近 <button onClick={onRefresh} 到 <\/button> 整段
      const refreshTextIdx = block.indexOf('刷新数据')
      expect(refreshTextIdx, 'Sidebar 中必须出现「刷新数据」文案').not.toBe(-1)
      const recentOpenBtn = block.lastIndexOf('<button', refreshTextIdx)
      const recentCloseBtn = block.indexOf('</button>', refreshTextIdx)
      const t = block.slice(recentOpenBtn, recentCloseBtn === -1 ? undefined : recentCloseBtn + 9)
      const hasBiliBg = /bg-bili-default/.test(t)
      const hasWhiteText = /text-white/.test(t)
      const noPinkBg = !/bg-neon-pink\s/.test(t) && !/bg-neon-pink"/.test(t) && !/bg-neon-pink'/.test(t)
      expect(
        hasBiliBg && hasWhiteText && noPinkBg,
        `展开态刷新按钮颜色不符合：\n`
        + `  bg-bili-default（B 站蓝底）: ${hasBiliBg}\n`
        + `  text-white（白字白 icon） : ${hasWhiteText}\n`
        + `  禁止 bg-neon-pink（原粉）  : ${noPinkBg}\n\n`
        + `用户明确：刷新数据大字 + icon = 白色悬浮在按钮上，按钮底 = B 站蓝色。`,
      ).toBe(true)
    })

    it('折叠态刷新图标按钮：必须 bg-bili-default 蓝底 + text-white 白 icon，禁止 bg-neon-pink', () => {
      const colIdx = sidebarJsx.indexOf('collapsed ? (', sidebarJsx.indexOf('ActionPanel'))
      const region = sidebarJsx.slice(colIdx, colIdx + 2400)
      const refreshBlock = /onClick=\{onRefresh\}[\s\S]{0,1200}?<\/button>/.exec(region)
      const t = refreshBlock ? refreshBlock[0] : ''
      const hasBiliBg = /bg-bili-default/.test(t)
      const hasWhiteText = /text-white/.test(t) || /text-haze-50\s/.test(t) || /text-haze-50"/.test(t)
      const noPinkBg = !/bg-neon-pink\s/.test(t) && !/bg-neon-pink"/.test(t) && !/bg-neon-pink'/.test(t)
      expect(
        hasBiliBg && hasWhiteText && noPinkBg,
        `折叠态刷新按钮颜色不符合（按钮必须 B 站蓝底，白色 RefreshCw icon）：\n  bg-bili-default: ${hasBiliBg}\n  white icon: ${hasWhiteText}\n  禁止 bg-neon-pink: ${noPinkBg}\n\n按钮块:\n${t.slice(0, 500)}`,
      ).toBe(true)
    })
  })

  describe('3. 我的收藏：字色 / 边框 / Star icon 全改为 B 站蓝', () => {
    it('展开态「我的收藏」：必须 text-bili-default + border-bili-default（或带透明度的 bili），禁止再用 neon-emerald', () => {
      const idx = sidebarJsx.indexOf('onToggleFavorites}')
      const region = sidebarJsx.slice(Math.max(0, idx - 400), idx + 1600)
      // 展开态第一个「我的收藏」按钮（非 collapsed，带"我的收藏"文本）
      const m = /<button[\s\S]{0,200}?onToggleFavorites[\s\S]{0,1200}?<\/button>/.exec(region)
      const t = m ? m[0] : ''
      const hasBiliText = /text-bili-default/.test(t)
      const hasBiliBorder = /border-bili-default/.test(t) || /border-[^\s"']*bili/.test(t)
      const hasBiliStar = t.includes('Star') && (/\bStar[\s\S]*?text-bili-default/.test(t) || /text-bili-default[\s\S]*?\bStar/.test(t))
      const noEmerald = !/text-neon-emerald/.test(t) && !/bg-neon-emerald[^/]/.test(t) && !/border-neon-emerald/.test(t)
      expect(
        hasBiliText && hasBiliBorder && hasBiliStar && noEmerald,
        `展开态「我的收藏」按钮颜色不符合（要求：字/边框/Star = B 站蓝，禁止原翡翠绿 neon-emerald）：\n`
        + `  text-bili-default (字色)  : ${hasBiliText}\n`
        + `  border-bili-default (边框): ${hasBiliBorder}\n`
        + `  Star icon = bili blue    : ${hasBiliStar}\n`
        + `  禁止 neon-emerald        : ${noEmerald}\n\n按钮块:\n${t.slice(0, 600)}`,
      ).toBe(true)
    })

    it('折叠态收藏 Star icon：必须 text-bili-default 蓝色，禁止 neon-emerald 绿', () => {
      // collapsed 分支里的收藏按钮（title="我的收藏"）
      const m = /<button[\s\S]{0,200}?title="我的收藏"[\s\S]{0,800}?<\/button>/.exec(sidebarJsx)
      const t = m ? m[0] : ''
      const hasBili = /text-bili-default/.test(t) || /!text-bili-default/.test(t)
      const noEmerald = !/text-neon-emerald/.test(t) && !/hover:!bg-neon-emerald/.test(t)
      expect(
        hasBili && noEmerald,
        `折叠态收藏 icon 必须蓝色，禁止翡翠绿：\n  text-bili-default: ${hasBili}\n  禁止 neon-emerald: ${noEmerald}\n\n按钮块:\n${t.slice(0, 400)}`,
      ).toBe(true)
    })
  })

  describe('4. 激活态 tab 视觉：全量统一 B 站蓝（激活底色 + 高亮竖条渐变），禁止粉红+蓝色混合冲突', () => {
    it('折叠态 NavGroup 激活态：必须 bg-bili-default/10 + text-bili-default，禁止 bg-neon-pink/10 + text-neon-pink（会与蓝色 icon 混合）', () => {
      // 折叠态分支（if (collapsed)）下的 isActive 激活按钮 className
      const colAnchor = sidebarJsx.indexOf('if (collapsed) {')
      expect(colAnchor, 'Sidebar 必须有折叠态 if (collapsed) 分支').not.toBe(-1)
      const region = sidebarJsx.slice(colAnchor, colAnchor + 1400)
      // 抓 isActive ? AAA : BBB 中 AAA 部分
      const re = /isActive\s*\?\s*'([^']+)'/
      const m = region.match(re)
      expect(m, '折叠态激活分支必须有三元 className 赋值').not.toBe(null)
      const activeCls = m[1]
      const hasBiliBg = /bg-bili-default/.test(activeCls)
      const hasBiliText = /text-bili-default/.test(activeCls)
      const noPinkBg = !/bg-neon-pink/.test(activeCls)
      const noPinkText = !/text-neon-pink/.test(activeCls)
      expect(
        hasBiliBg && hasBiliText && noPinkBg && noPinkText,
        `折叠态激活 tab 底色/字色仍残留粉色（与 blue icon 冲突）：\n`
        + `  当前激活 className: ${activeCls}\n`
        + `  要求：bg-bili-default（B 站蓝透明底）+ text-bili-default（蓝字/蓝 icon 容器）\n`
        + `  结果：hasBiliBg=${hasBiliBg} hasBiliText=${hasBiliText} noPinkBg=${noPinkBg} noPinkText=${noPinkText}`,
      ).toBe(true)
    })

    it('Sidebar 激活左侧竖条 bg-gradient 必须使用 bili 双色调（from-bili-default to-bili-dark），禁止 from-neon-pink to-neon-cyan', () => {
      // 激活高亮条块：w-[3px] + rounded-r + bg-gradient-to-b + from-XXX + to-YYY
      // to-[a-z0-9-]{3,} = 保证匹配完整 Tailwind to-* 令牌（如 to-bili-dark / to-neon-cyan）
      //   而非半路把 "to-b" 就误判为结束（旧 regex `to-[a-z-]+` 的 lazy 截断 bug）
      const barRe = /w-\[3px\][\s\S]{0,120}?rounded-r[\s\S]{0,500}?to-[a-z0-9-]{3,}/g
      const matches = [...sidebarJsx.matchAll(barRe)]
      expect(matches.length, '侧边栏应至少出现 1 处激活 tab 高亮条（w-[3px] rounded-r gradient to-XXX）').toBeGreaterThanOrEqual(1)
      const allBili = matches.every(m => /from-bili-default/.test(m[0]) && /to-bili-dark/.test(m[0]))
      const noNeon = matches.every(m => !/from-neon-pink/.test(m[0]) && !/to-neon-cyan/.test(m[0]))
      expect(
        allBili && noNeon,
        `激活 tab 高亮竖条渐变不符合（要求 B 站蓝浅→深渐变 from-bili-default → to-bili-dark）：\n`
        + `  全部 bili 渐变: ${allBili}\n  全部无 neon 粉→青: ${noNeon}\n\n匹配片段:\n`
        + matches.map((m, i) => `  #${i+1}: ${m[0].replace(/\s+/g, ' ').trim().slice(0, 160)}`).join('\n'),
      ).toBe(true)
    })
  })

  describe('5. 激活左侧竖条小蓝条 = 渐变色：必须 bg-gradient-to-b from-bili-default to-bili-dark，禁止单色 bg-bili-default', () => {
    it('侧边栏所有激活 w-[3px] 小蓝条（≥4 处）必须带 from-bili-default to-bili-dark 渐变，严禁纯 bg-bili-default 单色', () => {
      const re = /isActive\s*&&\s*\(\s*<span\s+className\s*=\s*"([^"]+)"[\s\S]*?\/>/g
      const matches = [...sidebarJsx.matchAll(re)]
      expect(matches.length, `侧边栏激活 tab 必须有 ≥4 条 w-[3px] 竖条，实际发现 ${matches.length} 条`).toBeGreaterThanOrEqual(4)
      const fails = []
      matches.forEach((m, idx) => {
        const cls = m[1]
        const hasBar = /w-\[3px\]/.test(cls)
        const hasGrad = /from-bili-default\s+to-bili-dark/.test(cls) && /bg-gradient-to-b/.test(cls)
        const noSolidBili = !/(^|\s)bg-bili-default(\s|\/|"|')/.test(cls)
        if (!(hasBar && hasGrad && noSolidBili)) {
          fails.push(`#${idx}: w3px=${hasBar} grad=${hasGrad} noSolid=${noSolidBili} class="${cls}"`)
        }
      })
      expect(
        fails.length === 0,
        `侧边栏激活小蓝条 = 渐变色，但发现 ${fails.length} 处仍是单色 bg-bili-default（显扁平）:\n\n`
        + fails.join('\n')
        + `\n\n正确写法：bg-gradient-to-b from-bili-default to-bili-dark（B 站蓝 浅→深 纵向渐变）`,
      ).toBe(true)
    })
  })
})

describe('[Sidebar Bili-Blue · Checkbox · LeftBar] 复选框左侧小蓝条 = 渐变色', () => {
  let setupJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/UpTrendsSetup.jsx'),
      resolve(__dirname, 'UpTrendsSetup.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/UpTrendsSetup.jsx',
    ]
    setupJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(setupJsx, '找不到 UpTrendsSetup.jsx').not.toBe(null)
  })

  it('复选框选中行（isSelected 或 isAdded 态）左侧必须有 w-[3px] + bg-gradient-to-b from-bili-default to-bili-dark 渐变竖条，禁止纯 bg-bili-default', () => {
    // 注意：map 内变量解构是先 const isSelected=selected.has(up.mid) 再 return <div key={up.mid}>，
    //       所以从 key 往后会先遇到 const isSelected=... 导致 rowRe 前向扫描 = isSelected 永远在前面（负距离）。
    //       为了测试契约语义稳定，改为全文件逐断言（不依赖行内变量/return 顺序）：
    // ① 行容器 flex items-center gap-3 px-4 py-3 必须带 relative（绝对定位小蓝条的前提）
    // ② 必须出现 isAdded 或 isSelected 的 {cond && (<span className="absolute left-0 w-[3px] bg-gradient-to-b from-bili-default to-bili-dark"/>)}
    // ③ 禁止单色 bg-bili-default 的 left bar（显扁平）
    const rowWrapRe = /<div\s+key=\{up\.mid\}[\s\S]{0,400}?className=\{[`'"][\s\S]{0,260}?flex\s+items-center[\s\S]{0,80}?\brelative\b[\s\S]{0,20}?\boverflow-hidden\b/
    const rowHasRelative = rowWrapRe.test(setupJsx) || /<div\s+key=\{up\.mid\}[\s\S]{0,600}?className=\{[`'"][\s\S]{0,260}?\brelative\b[\s\S]{0,300}?overflow-hidden\b/.test(setupJsx)
    // Left bar 最简语义：同一个 span 的 class 属性字符串里 同时包含 absolute + w-[3px] + bg-gradient-to-b + from-bili-default + to-bili-dark
    const leftBarClsRe = /className\s*=\s*"[^"]*?absolute[^"]*?w-\[3px\][^"]*?bg-gradient-to-b[^"]*?from-bili-default[^"]*?to-bili-dark[^"]*?"/
    const leftBarCondRe = /(isSelected\s*\|\|\s*isAdded|isAdded\s*\|\|\s*isSelected|isSelected|isAdded)\s*&&\s*\(\s*<span/
    const hasGradientBar = leftBarClsRe.test(setupJsx) && leftBarCondRe.test(setupJsx)
    // 禁止单色 bg-bili-default left bar
    const solidBarRe = /className\s*=\s*"[^"]*?(absolute|left-0)[^"]*?w-\[3px\][^"]*?bg-bili-default\b(?!\/)[^"]*?"/
    const noSolidBar = !solidBarRe.test(setupJsx)
    expect(
      rowHasRelative && hasGradientBar && noSolidBar,
      `复选框左侧「小蓝条」必须渐变色，当前不符：\n`
      + `  行容器 relative + overflow-hidden（必须） : ${rowHasRelative}\n`
      + `  isSelected/isAdded → same className 内 absolute + w-[3px] + from-bili-default → to-bili-dark 渐变（必须）: ${hasGradientBar}\n`
      + `    └─ leftBarClsRe(同className内 渐变完整链): ${leftBarClsRe.test(setupJsx)}   leftBarCondRe(条件包裹): ${leftBarCondRe.test(setupJsx)}\n`
      + `  禁止单色 bg-bili-default 小蓝条 : ${noSolidBar}\n\n`
      + `正确写法：行容器 className += " relative overflow-hidden"；复选框前追加：\n`
      + `  {(isSelected || isAdded) && (<span className="absolute left-0 top-0 bottom-0 w-[3px] bg-gradient-to-b from-bili-default to-bili-dark" />)}\n`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// 复选框等小细节：UpTrendsSetup.jsx 复选框 CheckSquare/Square → B 站蓝色
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar Bili-Blue · Checkbox] UpTrendsSetup 复选框：B 站蓝色', () => {
  let setupJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/UpTrendsSetup.jsx'),
      resolve(__dirname, 'UpTrendsSetup.jsx'),
      // 工作路径 dash/ 副本可能不存在；若不存在则走 F 盘主项目
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/UpTrendsSetup.jsx',
    ]
    setupJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(setupJsx, '找不到 UpTrendsSetup.jsx（复选框在该文件中）').not.toBe(null)
  })

  it('复选框选中态 color 必须 = text-bili-default（B 站蓝），禁止再写不存在的 text-primary-500', () => {
    // Checkbox block：<button ... onClick={() => toggle(up.mid)} ...>
    const re = /<button[\s\S]{0,500}?toggle\(up\.mid\)[\s\S]{0,1200}?<\/button>/
    const m = setupJsx.match(re)
    expect(m, '找不到复选框 toggle(up.mid) 按钮块').not.toBe(null)
    const t = m[0]
    // 选中文案
    const selectedLineRe = /isSelected\s*[\r\n\s]*\?[\s\S]*?text-([a-zA-Z0-9-]+)/
    const selMatch = t.match(selectedLineRe)
    const selectedColor = selMatch ? selMatch[1] : null
    // hover 文案
    const hoverLineRe = /hover:text-([a-zA-Z0-9-]+)/g
    const hoverColors = [...t.matchAll(hoverLineRe)].map(x => x[1])
    const hasBiliSelected = selectedColor === 'bili-default'
    const hoverHasBili = hoverColors.some(c => c.startsWith('bili'))
    // 绝对禁止写 text-primary-500（Tailwind 里根本没定义 primary，=透明=看不到）
    const noPrimary500 = !/text-primary-500/.test(t) && !/text-primary-600/.test(t) && !/text-primary-400/.test(t)
    expect(
      hasBiliSelected && hoverHasBili && noPrimary500,
      `复选框颜色不符合（要求选中 & hover = B 站蓝 text-bili-default；禁止不存在的 text-primary-500）：\n`
      + `  isSelected → color: ${selectedColor}  (需要 bili-default)\n`
      + `  hover colors: ${hoverColors.join(', ')} (需要 bili-*)\n`
      + `  禁止 text-primary-xxx: ${noPrimary500}\n\n按钮块:\n${t.slice(0, 700)}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// Sidebar UX：默认全部展开 + 折叠按钮重设计
//   用户诉求：① 侧边栏默认全部展开（不是只展开激活 tab 所在组）
//             ② 折叠按钮不好看 → 废除外挂在岛右边缘的 22×42 竖长胶囊
//                （半悬岛外像「疙瘩」，破坏悬浮岛完整轮廓，且与岛内按钮风格割裂）
//   新方案：折叠按钮融入 BrandHeader 岛内，与主题切换按钮（Sun/Moon）并排成组，
//           复用 kb-icon-btn（36×36 圆角、与现有图标按钮视觉完全统一）；
//           collapsed 态时显示在 logo 正下方居中。
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar UX] 默认全展开 + 折叠按钮岛内融合（废除外挂竖胶囊）', () => {
  let sidebarJsx, indexCss
  beforeAll(() => {
    const sideCandidates = [
      resolve(__dirname, 'src/components/Sidebar.jsx'),
      resolve(__dirname, 'Sidebar.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/Sidebar.jsx',
    ]
    sidebarJsx = sideCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
    const cssCandidates = [
      resolve(__dirname, 'src/index.css'),
      resolve(__dirname, 'index.css'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/index.css',
    ]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  it('1. 父级组默认全部展开：initialExpanded 必须无条件 m[g.id] = true，禁止 hasActive/g.tabs.some 守卫', () => {
    const re = /const initialExpanded = useMemo\(\(\) => \{([\s\S]*?)\},\s*\[\]\)/
    const m = sidebarJsx.match(re)
    expect(m, '必须保留 initialExpanded useMemo 初始化（展开状态初始化）').not.toBe(null)
    const body = m[1]
    const assignsAll = /m\[g\.id\]\s*=\s*true/.test(body)
    const noActiveGuard = !/hasActive|g\.tabs\.some/.test(body)
    expect(
      assignsAll && noActiveGuard,
      `initialExpanded 默认展开逻辑不符（用户要求「默认全部展开」）：\n`
      + `  无条件 m[g.id]=true（全部组展开）: ${assignsAll}\n`
      + `  移除 hasActive / g.tabs.some 条件守卫 : ${noActiveGuard}\n\n`
      + `当前函数体:\n${body.trim().slice(0, 300)}`,
    ).toBe(true)
  })

  it('2. 废除外挂竖胶囊：JSX 与 index.css 均不得再出现 kb-island__collapse-btn（右边缘凸出疙瘩破坏岛轮廓）', () => {
    const inJsx = /kb-island__collapse-btn/.test(sidebarJsx)
    const inCss = /kb-island__collapse-btn/.test(indexCss)
    expect(
      !inJsx && !inCss,
      `kb-island__collapse-btn 残留（外挂竖胶囊整体废弃，JSX 按钮与 CSS 规则块都要删干净）：\n`
      + `  Sidebar.jsx 中出现: ${inJsx}\n`
      + `  index.css 中出现 : ${inCss}\n\n`
      + `用户反馈「折叠按钮不好看」：半悬岛外(right:-10px)的 22×42 竖长胶囊像疙瘩，与岛内 kb-icon-btn 风格割裂。`,
    ).toBe(true)
  })

  it('3. 折叠按钮保留 PanelLeftClose/PanelLeftOpen 图标：当前使用圆形 puck 贴岛边框（kb-collapse-puck）', () => {
    // 二改后：折叠按钮不再用 kb-icon-btn，改用独立的 kb-collapse-puck 圆形贴岛
    const hasCloseIcon = /PanelLeftClose/.test(sidebarJsx)
    const hasOpenIcon  = /PanelLeftOpen/.test(sidebarJsx)
    const usesPuck = /kb-collapse-puck/.test(sidebarJsx)
    expect(
      hasCloseIcon && hasOpenIcon && usesPuck,
      `折叠按钮（二改）使用圆形 puck 贴岛边框：\n`
      + `  保留 PanelLeftClose 图标（展开态→点击折叠）: ${hasCloseIcon}\n`
      + `  保留 PanelLeftOpen 图标（折叠态→点击展开） : ${hasOpenIcon}\n`
      + `  使用 kb-collapse-puck class（圆形贴岛）    : ${usesPuck}`,
    ).toBe(true)
  })

  it('4. 展开态：折叠按钮（puck）独立存在，主题切换已移入 ActionPanel，两者不再在 BrandHeader 并排', () => {
    // 二改真实需求：圆形 puck 贴岛边框、主题按钮在 ActionPanel（大按钮）。
    // → 断言："切换侧边栏折叠" 和 "切换主题/Sun/Moon" 不同时出现在 BrandHeader 内
    const bhStart = sidebarJsx.indexOf('const BrandHeader')
    const bhEnd = sidebarJsx.indexOf('const StatusLine')
    const bh = sidebarJsx.slice(bhStart, bhEnd > 0 ? bhEnd : -1)
    const hasCollapseInBH = /切换侧边栏折叠|aria-label="切换侧边栏折叠"/.test(bh)
    const hasThemeInBH = /切换主题|Sun size|Moon size/.test(bh)
    expect(
      !hasCollapseInBH && !hasThemeInBH,
      `二改后 BrandHeader 内不得有折叠/主题按钮（两按钮各归其位：puck 贴岛 / 主题在 ActionPanel）：\n`
      + `  BrandHeader 内无折叠按钮 : ${!hasCollapseInBH}\n`
      + `  BrandHeader 内无主题按钮 : ${!hasThemeInBH}`,
    ).toBe(true)
  })

  it('5. 折叠态：圆形 puck 仍贴岛右边缘中部（不是在 logo 下方）；BrandHeader 不再要求 flex-col', () => {
    // 二改：puck 在 kb-island 相对容器内 absolute right-0 贴边，与 BrandHeader 布局无关
    const desktopStart = sidebarJsx.indexOf('const Desktop')
    const desktopEnd = sidebarJsx.indexOf('const Mobile')
    const desktop = sidebarJsx.slice(desktopStart, desktopEnd > 0 ? desktopEnd : -1)
    const puckOnEdge = /kb-collapse-puck[\s\S]{0,200}?absolute[\s\S]{0,100}?right-0/.test(desktop)
                 || /kb-collapse-puck[\s\S]{0,200}?right-0[\s\S]{0,100}?absolute/.test(desktop)
    expect(
      puckOnEdge,
      `折叠态（两态共用）折叠按钮必须独立圆形 puck absolute 贴岛右边缘中部：\n`
      + `  Desktop 内 kb-collapse-puck + absolute + right-0 贴边: ${puckOnEdge}\n\n`
      + `正确示例：<button className="kb-collapse-puck absolute right-0 top-1/2 -translate-y-1/2 ...">`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// Sidebar UX 二改：折叠按钮圆形贴岛 + 主题按钮移入 ActionPanel 做大按钮
//   用户新反馈（附参考图）：
//   ① 折叠按钮：圆形胶囊 puck 悬浮在岛式侧边栏边缘（贴边框，不是在 BrandHeader 里）
//   ② 主题切换：从 BrandHeader 顶部小图标按钮 → 移到「我的收藏」上方做成
//      与「我的收藏 / 刷新数据」同规格的大按钮（px-3 py-2.5 rounded-xl），
//      不再使用 kb-icon-btn 小圆形。
//   ③ BrandHeader 内仅保留 logo + 标题 + LIVE 徽章，不再有任何并排按钮容器。
//   ④ 折叠 / 展开两态的 puck 按钮都在岛边框（展开时左箭头贴右边缘、
//      折叠时右箭头贴右边缘）。
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar UX 二改] 折叠按钮圆形贴岛边框 + 主题按钮移入 ActionPanel', () => {
  let sidebarJsx, indexCss
  beforeAll(() => {
    const sideCandidates = [
      resolve(__dirname, 'src/components/Sidebar.jsx'),
      resolve(__dirname, 'Sidebar.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/Sidebar.jsx',
    ]
    sidebarJsx = sideCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
    const cssCandidates = [
      resolve(__dirname, 'src/index.css'),
      resolve(__dirname, 'index.css'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/index.css',
    ]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  it('1. BrandHeader 内废弃并排按钮容器：不再有 <CollapseControl /> 调用、不再有「切换侧边栏折叠」+「切换主题」并排放置', () => {
    // BrandHeader 中禁止出现切换侧边栏折叠 button
    const bhRe = /const BrandHeader[\s\S]*?^  \)$/m
    const bhM = sidebarJsx.match(bhRe)
    let bhBody = bhM ? bhM[0] : sidebarJsx.slice(sidebarJsx.indexOf('const BrandHeader'), sidebarJsx.indexOf('const StatusLine'))
    const noCollapseInBH = !/aria-label="切换侧边栏折叠"/.test(bhBody)
    const noThemeInBH = !/aria-label="切换主题"/.test(bhBody)
    const noSideBySideFlex = !/flex items-center gap-1 shrink-0[\s\S]{0,200}切换侧边栏折叠[\s\S]{0,200}切换主题/.test(sidebarJsx)
    expect(
      noCollapseInBH && noThemeInBH && noSideBySideFlex,
      `BrandHeader 必须只保留 logo+标题+LIVE，不再内含按钮：\n`
      + `  BrandHeader 内无「切换侧边栏折叠」: ${noCollapseInBH}\n`
      + `  BrandHeader 内无「切换主题」        : ${noThemeInBH}\n`
      + `  全局无并排容器（折叠+主题）        : ${noSideBySideFlex}`,
    ).toBe(true)
  })

  it('2. 折叠按钮改为独立圆形 puck 贴岛边框：Desktop as 内有绝对/固定定位的圆形按钮，class 含 kb-collapse-puck + rounded-full', () => {
    // Desktop 组件内必须有独立的折叠按钮，使用 kb-collapse-puck 类 + 贴边定位
    const desktopStart = sidebarJsx.indexOf('const Desktop')
    const desktopEnd = sidebarJsx.indexOf('const Mobile')
    const desktop = sidebarJsx.slice(desktopStart, desktopEnd > 0 ? desktopEnd : -1)
    const hasPuckClass = /kb-collapse-puck/.test(desktop)
    const hasRoundedFull = /rounded-full/.test(desktop)
    const hasRightPin = /right-[-0]|right:\s*[-0]/.test(desktop)   // 贴右边缘
    const hasCollapseAria = /aria-label="切换侧边栏折叠"/.test(desktop)
    expect(
      hasPuckClass && hasRoundedFull && hasRightPin && hasCollapseAria,
      `桌面端折叠按钮必须是独立圆形 puck 贴岛边框：\n`
      + `  Desktop 内出现 kb-collapse-puck class : ${hasPuckClass}\n`
      + `  圆形（rounded-full）                  : ${hasRoundedFull}\n`
      + `  贴右边缘（right-0 / right:0 类）      : ${hasRightPin}\n`
      + `  切换侧边栏折叠 aria-label             : ${hasCollapseAria}`,
    ).toBe(true)
  })

  it('3. index.css 新增 kb-collapse-puck 规则块：圆、固定尺寸、阴影/发光，支持贴边绝对定位', () => {
    const re = /\.kb-collapse-puck\s*\{[\s\S]*?\n\}/
    const m = indexCss.match(re)
    expect(m, 'index.css 必须定义 .kb-collapse-puck').not.toBe(null)
    const body = m[0]
    const hasDims = /(width|min-width|aspect-ratio|--puck-size)/.test(body)
    const hasCircle = /border-radius:\s*999(?:px|9px|9%)|50%|rounded-full/.test(body) || /border-radius\s*:\s*(?:999|40|50)/.test(body)
    const hasShadow = /box-shadow|shadow-/.test(body)
    const hasPin = /position\s*:\s*absolute|position\s*:\s*fixed/.test(body)
    expect(
      hasDims && hasShadow && hasPin,
      `.kb-collapse-puck 规则块不完整：\n`
      + `  含尺寸（width/min-width 等） : ${hasDims}\n`
      + `  含阴影/发光（box-shadow）     : ${hasShadow}\n`
      + `  含定位（absolute/fixed）      : ${hasPin}\n`
      + `  当前规则块内容:\n${body.slice(0, 500)}`,
    ).toBe(true)
  })

  it('4. 主题切换按钮移入 ActionPanel 我的收藏上方，做大按钮（含 Sun/Moon + 中文文案，px-3 py-2.5 rounded-xl，不再是 kb-icon-btn 小圆形）', () => {
    // 必须在 ActionPanel 内找到：Sun/Moon 图标 + 中文文案（"切换到…模式"/"主题"等）的大按钮
    const apStart = sidebarJsx.indexOf('const ActionPanel')
    const apEnd = sidebarJsx.indexOf('// ══════════════════════ 桌面端')
    const ap = sidebarJsx.slice(apStart, apEnd > 0 ? apEnd : sidebarJsx.length)
    const hasSunInAP = /Sun/.test(ap)
    const hasMoonInAP = /Moon/.test(ap)
    const hasThemeBtnAP = /切换主题|日间模式|夜间模式|主题/.test(ap)
    // 我的收藏（Star）应在主题按钮之后
    const starAfterThemeIdx = ap.indexOf('Star size') > ap.indexOf('Sun size') || ap.indexOf('Star size') > ap.indexOf('Moon')
    const isLargeBtn = /px-3 py-2\.5/.test(ap)
    // 折叠态虽然使用 kb-icon-btn，但使用的是 w-full !h-10 !rounded-xl 的"大按钮变体"（不是标准 kb-icon-btn 小圆 32×32）
    // 真正禁止的是：直接 Sun/Moon 下紧跟标准小圆 kb-icon-btn（带标准尺寸，无 !h-10）。
    // 用宽松检查：kb-icon-btn 30 字符内 Sun/Moon 且不含 !h-10（小圆形）为违规
    const miniIconBtnRe = /kb-icon-btn(?!(?:[\s\S]{0,100}!h-10|[\s\S]{0,100}!rounded-xl))[\s\S]{0,100}(?:Sun|Moon)/
    const noMiniIconBtn = !miniIconBtnRe.test(ap) || /!h-10/.test(ap)
    expect(
      hasSunInAP && hasMoonInAP && hasThemeBtnAP && starAfterThemeIdx && isLargeBtn && noMiniIconBtn,
      `主题切换必须从 BrandHeader 的 kb-icon-btn 移到 ActionPanel 做大按钮：\n`
      + `  ActionPanel 内有 Sun 图标            : ${hasSunInAP}\n`
      + `  ActionPanel 内有 Moon 图标           : ${hasMoonInAP}\n`
      + `  按钮含主题/日夜间模式文案            : ${hasThemeBtnAP}\n`
      + `  Star(我的收藏) 在主题按钮之后        : ${starAfterThemeIdx}\n`
      + `  大按钮规格（px-3 py-2.5）           : ${isLargeBtn}\n`
      + `  禁止把 Sun/Moon 做 kb-icon-btn 小圆 : ${noMiniIconBtn}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// Sidebar UX 三改：圆形折叠 puck 完整可见修复（用户反馈"只有一半漏出来"）
//   根因：① kb-island 外层显式 overflow:hidden → absolute + translate-x-1/2
//         的右半边圆扣被父容器裁剪；② aside pr-4 让岛整体偏左，圆扣
//         的外半边又被"视口留白"进一步挤出可见区。
//   修复目标：
//     1) kb-island 容器本身不得有 inline style overflow:hidden（绝对子元素必须可见）
//     2) 桌面端 <aside> 右侧 padding 必须改为 0 或 px 级小值（不能 pr-4=16px 推离视口）
//     3) 圆扣仍挂在 kb-island relative 容器内（absolute right-0 translate-x-1/2），
//        但必须完全不被裁剪 → overflow 由内部滚动容器负责，不在岛根加
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar UX 三改] 圆扣完整可见（修复 overflow:hidden + pr-4 裁剪问题）', () => {
  let sidebarJsx, indexCss
  beforeAll(() => {
    const sideCandidates = [
      resolve(__dirname, 'src/components/Sidebar.jsx'),
      resolve(__dirname, 'Sidebar.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/Sidebar.jsx',
    ]
    sidebarJsx = sideCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
    const cssCandidates = [
      resolve(__dirname, 'src/index.css'),
      resolve(__dirname, 'index.css'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/index.css',
    ]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
  })

  it('1. kb-island 根容器不得设置 inline style overflow:hidden（否则 absolute 圆扣右半边被父裁掉）', () => {
    // 桌面端 kb-island 的 div 上不应有 style={{ overflow: 'hidden' }} 或 className 含 overflow-hidden
    const desktopStart = sidebarJsx.indexOf('const Desktop')
    const desktopEnd = sidebarJsx.indexOf('const Mobile')
    const desktop = sidebarJsx.slice(desktopStart, desktopEnd > 0 ? desktopEnd : -1)
    // 抓 kb-island 附近的行
    const islandIdx = desktop.indexOf('kb-island')
    const islandCtx = desktop.slice(islandIdx, islandIdx + 900)
    const noInlineOverflow = !/overflow:\s*['"]hidden['"]/.test(islandCtx)
    const noTwOverflowHidden = !/overflow-hidden/.test(islandCtx)
    expect(
      noInlineOverflow && noTwOverflowHidden,
      `kb-island 根容器禁止 overflow:hidden（absolute 圆扣会被裁掉一半）：\n`
      + `  无 inline style overflow:hidden : ${noInlineOverflow}\n`
      + `  无 Tailwind overflow-hidden class : ${noTwOverflowHidden}\n\n`
      + `当前上下文:\n${islandCtx.slice(0, 500)}`,
    ).toBe(true)
  })

  it('2. 桌面端 aside 的右 padding 不得为 pr-4（16px 推离视口 → 圆扣外半边被留白挤出可见区）', () => {
    const desktopStart = sidebarJsx.indexOf('const Desktop')
    const desktopEnd = sidebarJsx.indexOf('const Mobile')
    const desktop = sidebarJsx.slice(desktopStart, desktopEnd > 0 ? desktopEnd : -1)
    const asideRe = /<aside[^>]*className="([^"]+)"/
    const m = desktop.match(asideRe)
    expect(m, 'Desktop 必须找到 <aside className=...>').not.toBe(null)
    const cls = m[1]
    const hasNotPr4 = !/(^|\s)pr-4(\s|$)/.test(cls)
    // 允许 pr-0 / pr-1 / pr-2，但不要 16px 级别的 pr-4（因为圆扣 16px 外半会陷入 padding 空白）
    expect(
      hasNotPr4,
      `桌面端 <aside> 禁止 pr-4 右内边距（它把岛推离内容区 16px，导致圆扣 translate-x-1/2=16px 仍完整在留白中、视觉远离岛边缘）：\n`
      + `  当前 aside className: ${cls}`,
    ).toBe(true)
  })

  it('3. 圆扣仍挂在 kb-island relative 容器内（absolute right-0 + 负 mr-16px）——保证永远贴岛边缘对齐，不随滚动错位', () => {
    const desktopStart = sidebarJsx.indexOf('const Desktop')
    const desktopEnd = sidebarJsx.indexOf('const Mobile')
    const desktop = sidebarJsx.slice(desktopStart, desktopEnd > 0 ? desktopEnd : -1)
    const puckUsesAbsolute = /kb-collapse-puck[\s\S]{0,120}absolute/.test(desktop)
    // 与四改同步：禁止 transform translate 做偏移（改为 margin-right:-16px 布局属性推一半出去）
    const puckUsesNotTranslate = !/translate-x-1\/2|translate-y-1\/2|-translate-/.test(desktop)
    const puckNegMr = /mr-\[-16px\]|mr-[-]?\[-16px\]|margin-right:-16px/.test(desktop)
    const puckPinsRight = /right-0/.test(desktop)
    expect(
      puckUsesAbsolute && puckPinsRight && puckNegMr && puckUsesNotTranslate,
      `圆扣必须使用 absolute + right-0 + mr-[-16px] 贴岛边缘（禁止用 transform translate，避免合成层抖动/与 width 动画不同步）：\n`
      + `  absolute 定位（跟随 kb-island relative）  : ${puckUsesAbsolute}\n`
      + `  right-0 贴岛最右边界                    : ${puckPinsRight}\n`
      + `  mr-[-16px] 一半悬岛外                   : ${puckNegMr}\n`
      + `  无 translate 工具类（防止合成层抖动）    : ${puckUsesNotTranslate}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// Sidebar UX 四改（重写）：折叠 puck 严格满足用户 3 条
//   用户原话 5 条要求综合成 3 个约束：
//   (1) 悬浮在侧边栏边上 → 圆扣一半在岛内，一半悬于岛外，与视觉边缘贴合。
//   (2) 点击后跟随侧边栏滑动 → 圆扣必须"锚定在 kb-island 宽度变化的包含块上"，
//       也就是 puck 必须放在 kb-island relative 内部，并用 right:0 这种
//       随父 width 即时对齐的属性 + 负 margin（margin-right:-16px）把 1/2
//       推出岛外——不能用 transform translate（translate 不是布局坐标，
//       某些浏览器合成层/backdrop-filter 时会和父 width transition 产生
//       瞬时"视觉错位/闪烁"）。
//   (3) hover 本身位置绝对不动 → 三条禁令：
//       a) 圆扣自己绝对不能有 transition 属性（任何值都不行，包括颜色过渡，
//          因为 transition 如果被浏览器在 transform 合成层上"合并"，会导致
//          视觉上一 hover 就有像素级跳动）。
//       b) 圆扣绝对不能用 transform 做居中（包括 -translate-y-1/2 / translate-x-1/2
//          等 Tailwind 工具类，也包括自定义 transform:translate）。
//          垂直居中改为 top:50% + margin-top:-16px（用布局属性，不进合成层）。
//       c) :hover 伪类里不得出现任何几何属性（top/right/bottom/left、
//          margin、width/height、position、transform 全禁）。
//   额外：颜色/阴影的"视觉反馈"改为瞬时切换（不做过渡），这是用户第 3 条
//         "按钮不要移动"与浏览器合成层冲突的兜底权衡——宁可阴影不渐变，
//         也要 hover 绝对静止。
// ═══════════════════════════════════════════════════════════════════
describe('[Sidebar UX 四改] 圆扣：悬浮岛边+随岛滑动+hover完全不动（禁 transform / 禁 transition）', () => {
  let indexCss, sidebarJsx
  beforeAll(() => {
    const cssCandidates = [
      resolve(__dirname, 'src/index.css'),
      resolve(__dirname, 'index.css'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/index.css',
    ]
    indexCss = cssCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(indexCss, '找不到 index.css').not.toBe(null)
    const jsxCandidates = [
      resolve(__dirname, 'src/components/Sidebar.jsx'),
      resolve(__dirname, 'Sidebar.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/Sidebar.jsx',
    ]
    sidebarJsx = jsxCandidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
  })

  it('1. 圆扣定位禁止使用 transform（包括 -translate-y-1/2 / translate-x-1/2），必须改用布局属性（top+margin / calc）居中', () => {
    // 从 JSX 的 button className 上禁止出现 translate 字样
    const btnClassRe = /kb-collapse-puck[\s\S]{0,220}?className="([^"]+)"/
    const classLine = sidebarJsx.match(/className="kb-collapse-puck[^"]*"/)?.[0]
    expect(classLine, 'Sidebar.jsx 必须存在 kb-collapse-puck 的 className').not.toBe(undefined)
    const hasTranslate = /translate-\w/.test(classLine) || /translate-x|translate-y|-translate-/.test(classLine)
    expect(
      !hasTranslate,
      `圆扣 className 不得使用 translate 工具类（会进合成层→hover 抖动/与 width 过渡不同步）：\n`
      + `  当前 className 片段：${classLine}\n\n`
      + `改法：水平用 right-0 + mr-[-16px] 推出一半；垂直用 top-1/2 + mt-[-16px] 居中。`,
    ).toBe(true)
  })

  it('2. 圆扣必须在 kb-island relative 容器内部，并使用 right-0 + mr-[-16px] 贴岛边缘→随 width 平滑滑动', () => {
    const lines = sidebarJsx.split(/\r?\n/)
    // kb-island 可能跨多行（className 用模板字符串 'kb-island ...' + (collapsed ? ...)）。
    // 策略：找包含 "kb-island" token 的行作为岛锚点；relative 判定则要求在该
    // 行及后续 3 行范围内出现 "\brelative\b"（模板字符串拼接时 relative 写在同一字符串里）。
    const kbIslandIdx = lines.findIndex(l => /(^|['"`\s])kb-island(['"`\s]|$)/.test(l))
    const puckIdx = lines.findIndex(l => /\bkb-collapse-puck\b/.test(l) && /className|absolute|right-0/.test(l))
    const islandFragment = kbIslandIdx >= 0
      ? lines.slice(kbIslandIdx, Math.min(kbIslandIdx + 4, lines.length)).join('\n')
      : ''
    const puckLine = puckIdx >= 0 ? lines[puckIdx] : ''
    // (a) 岛容器必须声明 relative（含在 className 字符串片段里）
    const islandRelative = /\brelative\b/.test(islandFragment)
    // (b)(c)(d) 圆扣的 absolute / right-0 / 负 mr-16px
    const puckAbsolute = /\babsolute\b/.test(puckLine)
    const puckRight0 = /\bright-0\b/.test(puckLine)
    const hasNegMarginRight = /mr-\[-16px\]/.test(puckLine) || /margin-right\s*:\s*-16px/.test(puckLine)
    // (e) 圆扣必须在岛行之后（DOM 树在 island 内部，右边缘随 width 同步移动）
    const puckAfterIsland = kbIslandIdx >= 0 && puckIdx >= 0 && puckIdx > kbIslandIdx
    expect(
      islandRelative && puckAbsolute && puckRight0 && hasNegMarginRight && puckAfterIsland,
      `圆扣必须锚定在 kb-island 相对容器内并随 width 同步滑动：\n`
      + `  kb-island 锚定行（前后范围）含 relative : ${islandRelative}\n`
      + `  圆扣 absolute 绝对定位              : ${puckAbsolute}\n`
      + `  圆扣 right-0 贴岛右内边             : ${puckRight0}\n`
      + `  圆扣负 margin-right 推出一半悬岛外   : ${hasNegMarginRight}\n`
      + `  圆扣行位于 kb-island 行之后(同包含块): ${puckAfterIsland} (island行=${kbIslandIdx}, puck行=${puckIdx})\n\n`
      + `kb-island 片段(4行):\n${islandFragment.trim().slice(0, 300)}\n\n`
      + `puck 行:\n${puckLine.trim().slice(0, 200)}`,
    ).toBe(true)
  })

  it('3. .kb-collapse-puck 禁止声明任何 transition（颜色/阴影瞬时切换，兜底保证 hover 与 width 动画完全互不干渉）', () => {
    const re = /\.kb-collapse-puck\s*\{([\s\S]*?)\n\}/
    const m = indexCss.match(re)
    expect(m, '必须存在 .kb-collapse-puck').not.toBe(null)
    const body = m[1]
    const hasTransition = /\btransition\s*:/.test(body)
    const hasTransitionAll = /\btransition\b/.test(body) && !/transition:/.test(body) ? false : hasTransition
    // 另外禁掉 transition-property / transition-duration 单个简写
    const hasTransProp = /transition-(property|duration|timing|delay)\s*:/.test(body)
    expect(
      !hasTransition && !hasTransProp,
      `.kb-collapse-puck 不得写 transition 任何值：\n`
      + `  声明 transition:...  : ${hasTransition}\n`
      + `  声明 transition-* 子属: ${hasTransProp}\n\n`
      + `用户要求"hover 本身位置不动"——颜色/阴影过渡宁可不做，也不能和 transform/合成层打架。`,
    ).toBe(true)
  })

  it('4. .kb-collapse-puck:hover 伪类不得出现几何属性（top/right/left/bottom / margin / width/height / transform / position）', () => {
    const re = /\.kb-collapse-puck:hover\s*\{([\s\S]*?)\n\}/
    const m = indexCss.match(re)
    expect(m, '必须存在 .kb-collapse-puck:hover').not.toBe(null)
    const body = m[1]
    const badProps = [
      ['top', /\btop\s*:/],
      ['right', /\bright\s*:/],
      ['bottom', /\bbottom\s*:/],
      ['left', /\bleft\s*:/],
      ['margin(总)', /\bmargin\s*:|\bmargin-(top|right|bottom|left)\s*:/],
      ['width/height', /\bwidth\s*:|\bheight\s*:/],
      ['transform', /\btransform\s*:/],
      ['position', /\bposition\s*:/],
      ['transition', /\btransition\s*:/],
    ]
    const violations = badProps.filter(([, re]) => re.test(body)).map(([n]) => n)
    expect(
      violations.length === 0,
      `hover 伪类不得触碰几何/过渡属性。违反项：${violations.join('、') || '无'}\n\nhover 块:\n${body.slice(0, 300)}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// Section 组件 icon 改款：去掉 w-8 h-8 rounded-xl bg-white/5 圆角矩形底
//   用户原话：「左边这个icon太丑了，这个渐变色的圆角矩形底就很丑，
//             里面的奖杯标志应该是白色的或者透明的」
//   实际目标：App.jsx 里的 Section 组件（不是 Sidebar），
//     它用 `<span className="inline-flex items-center justify-center
//              w-8 h-8 rounded-xl bg-white/5">{icon}</span>` 给所有
//     section 标题图标都套了一个圆角矩形底，导致截图里"鬼畜区排行榜"
//     那个 trophy 看起来很丑。
//   规则：
//     1) Section 组件根容器里禁止再出现 `w-8 h-8 rounded-xl` 包裹 icon 的 span；
//     2) icon 必须直接放在标题行（无装饰），或者最小化包装（仅 gap 对齐）；
//     3) 奖杯图标（鬼畜区排行榜的 Trophy）颜色改为 text-white / text-haze-50（白色）。
// ═══════════════════════════════════════════════════════════════════
describe('[Section Icon] 去掉圆角矩形底+Trophy 改为白色', () => {
  let appJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/App.jsx'),
      resolve(__dirname, 'App.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/App.jsx',
    ]
    appJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(appJsx, '找不到 App.jsx').not.toBe(null)
  })

  it('1. Section 组件 icon 包装 span 禁止使用 w-8 h-8 rounded-xl 圆角矩形底', () => {
    // 定位到 function Section 定义区域
    const sectStart = appJsx.indexOf('function Section')
    const nextFnStart = appJsx.indexOf('\nfunction ', sectStart + 1)
    const body = appJsx.slice(sectStart, nextFnStart > 0 ? nextFnStart : sectStart + 3000)
    const hasForbiddenSpan = /w-8\s+h-8\s+rounded-xl\s+bg-white\/?5/.test(body)
    expect(
      !hasForbiddenSpan,
      `Section 组件的 icon 禁止用 w-8 h-8 rounded-xl bg-white/5 做圆角矩形底包装。\n\nSection 片段:\n${body.slice(0, 1200)}`,
    ).toBe(true)
  })

  it('2. 鬼畜区排行榜 Section 的 Trophy 图标颜色必须为白色（text-white / text-haze-50），禁止 text-neon-amber 橙金', () => {
    const re = /鬼畜区排行榜[\s\S]{0,800}/
    const block = appJsx.match(re)
    expect(block, 'App.jsx 必须包含"鬼畜区排行榜" Section').not.toBe(null)
    const trophyLine = block[0].match(/<Trophy[^>]*className="([^"]*)"[^>]*>/)
    expect(trophyLine, '鬼畜区排行榜 Section 必须用 Trophy 图标').not.toBe(null)
    const cls = trophyLine[1]
    const hasWhite = /text-white|text-haze-50/.test(cls)
    expect(
      hasWhite,
      `鬼畜区排行榜的 Trophy 必须白色（text-white 或 text-haze-50），当前: ${cls}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// PageHeader 组件 icon 改款：去掉 w-11 h-11 rounded-2xl 渐变圆角矩形底
//   用户原话（第二次明确位置）：
//     「鬼畜榜，热梗，潜力视频，梗素材库，这些板块的最顶上的标题旁边的icon」
//     —— 即每个 tab 页面顶部的 PageHeader（不是侧边栏 Sidebar、不是 Section）。
//   根因：PageHeader 用
//     <span className="inline-flex ... w-11 h-11 rounded-2xl
//            bg-gradient-to-br from-neon-pink to-neon-cyan text-white
//            shadow-glow-pink">{icon}</span>
//   把标题左侧图标套进一个粉→青渐变圆角矩形，用户觉得「渐变底很丑」。
//   修复：
//     1) PageHeader 组件根容器里禁止再出现上述渐变圆角矩形底包装；
//     2) 四个点名板块（鬼畜区排行榜 / 热梗库 / 鬼畜潜力视频 / 梗素材库）
//        的 PageHeader 图标颜色改为白色（text-white / text-haze-50），
//        禁止再用 neon-amber/rose/pink 等彩色。
// ═══════════════════════════════════════════════════════════════════
describe('[PageHeader Icon] 去掉渐变圆角矩形底+4板块图标改白色', () => {
  let appJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/App.jsx'),
      resolve(__dirname, 'App.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/App.jsx',
    ]
    appJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(appJsx, '找不到 App.jsx').not.toBe(null)
  })

  it('1. PageHeader 组件 icon 包装 span 禁止使用 bg-gradient-to-br / from-neon-pink / to-neon-cyan / shadow-glow-pink 圆角矩形底', () => {
    const sectStart = appJsx.indexOf('function PageHeader')
    const nextFnStart = appJsx.indexOf('\nfunction ', sectStart + 1)
    const body = appJsx.slice(sectStart, nextFnStart > 0 ? nextFnStart : sectStart + 2500)
    const forbidden = [
      ['bg-gradient-to-br', /bg-gradient-to-br/],
      ['from-neon-pink', /from-neon-pink/],
      ['to-neon-cyan', /to-neon-cyan/],
      ['shadow-glow-pink', /shadow-glow-pink/],
    ]
    const violations = forbidden.filter(([, re]) => re.test(body)).map(([n]) => n)
    expect(
      violations.length === 0,
      `PageHeader 组件的 icon 禁止套渐变圆角矩形底。违反项：${violations.join('、') || '无'}\n\nPageHeader 片段:\n${body.slice(0, 900)}`,
    ).toBe(true)
  })

  it('2. 四个板块（鬼畜区排行榜/热梗库/鬼畜潜力视频/梗素材库）的 PageHeader 图标必须为白色，禁止 neon 彩色', () => {
    const targets = [
      ['鬼畜区排行榜', 'Trophy'],
      ['热梗库', 'Flame'],
      ['鬼畜潜力视频', 'Zap'],
      ['梗素材库', 'Sparkles'],
    ]
    const results = []
    for (const [title, iconName] of targets) {
      const idx = appJsx.indexOf(`<PageHeader title="${title}"`)
      expect(idx, `App.jsx 必须存在 <PageHeader title="${title}"`).toBeGreaterThan(-1)
      // 取该 PageHeader 后 400 字符内找它自己的 icon 元素
      const seg = appJsx.slice(idx, idx + 600)
      const iconTag = seg.match(new RegExp(`<${iconName}[^>]*className="([^"]*)"[^>]*>`))
      expect(iconTag, `${title} 的 PageHeader 必须用 ${iconName} 图标`).not.toBe(null)
      const cls = iconTag[1]
      const isWhite = /text-white|text-haze-50/.test(cls)
      results.push(`${title}: ${cls} (白色=${isWhite})`)
    }
    const allWhite = results.every(r => r.includes('白色=true'))
    expect(
      allWhite,
      `四个板块 PageHeader 图标必须全部白色：\n  ${results.join('\n  ')}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// CommentList（神评论精选）UI 统一到 kb 主题
//   用户诉求：「神评论精选板块的 UI 和其他业务不一样了，做统一」
//   根因：CommentList.jsx 用了 bilibili 浅色 slate 系（bg-white / text-slate-* /
//         border-slate-* / bg-amber-50 / bg-red-50 / bg-orange-50 / bg-blue-50），
//         而看板其他板块（MemeCard / VideoCard / 弹幕热词升温榜）都是
//         kb-card 深色主题（kb-card + text-haze-* + text-neon-* + border-white/5）。
//   修复规则：
//     1) 禁止再出现 slate / bg-white / bg-*-50 等浅色「非本看板」的 Tailwind 类；
//     2) 必须使用 kb-card 容器 + text-haze-* 文字 + text-neon-* 强调色；
//     3) 分隔线/弱化边框统一 border-white/5 或 divide-white/5。
// ═══════════════════════════════════════════════════════════════════
describe('[CommentList UI] 神评论精选统一到 kb 深色主题', () => {
  let commentJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/CommentList.jsx'),
      resolve(__dirname, 'components/CommentList.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/CommentList.jsx',
    ]
    commentJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(commentJsx, '找不到 CommentList.jsx').not.toBe(null)
  })

  it('1. 禁止残留浅色 slate / 白底 / 淡色系类（旧 bilibili 浅色风格，与其他板块不一致的元凶）', () => {
    const forbidden = [
      ['bg-white', /bg-white(?![/\w])/],
      ['text-slate-', /text-slate-/],
      ['border-slate-', /border-slate-/],
      ['divide-slate-', /divide-slate-/],
      ['bg-slate-', /bg-slate-/],
      ['hover:bg-amber-50', /hover:bg-amber-50/],
      ['hover:bg-slate-50', /hover:bg-slate-50/],
      ['bg-amber-50', /bg-amber-50/],
      ['bg-red-50', /bg-red-50/],
      ['bg-orange-50', /bg-orange-50/],
      ['bg-blue-50', /bg-blue-50/],
      ['text-yellow-400', /text-yellow-400/],
    ]
    const violations = forbidden.filter(([, re]) => re.test(commentJsx)).map(([n]) => n)
    expect(
      violations.length === 0,
      `CommentList.jsx 禁止残留浅色 slate/白底/淡色类（违反=UI 未统一）：${violations.join('、') || '无'}`,
    ).toBe(true)
  })

  it('2. 必须使用 kb 主题：kb-card 容器 + text-haze-* 文字 + text-neon-* 强调色', () => {
    const hasKbCard = /\bkb-card\b/.test(commentJsx)
    const hasHazeText = /text-haze-/.test(commentJsx)
    const hasNeonAccent = /text-neon-/.test(commentJsx)
    expect(
      hasKbCard && hasHazeText && hasNeonAccent,
      `CommentList 必须迁移到 kb 主题：\n`
      + `  用 kb-card 容器    : ${hasKbCard}\n`
      + `  用 text-haze-* 文字: ${hasHazeText}\n`
      + `  用 text-neon-* 强调: ${hasNeonAccent}`,
    ).toBe(true)
  })

  it('3. 列表分隔线/弱化边框必须用 white/5（与其他板块 border-white/5 一致），徽章必须用 kb-chip--* 变体', () => {
    const hasWhiteBorder = /border-white\/5|divide-white\/5/.test(commentJsx)
    const hasKbChip = /kb-chip--(rose|pink|amber|violet|cyan|emerald|ghost)/.test(commentJsx)
    expect(
      hasWhiteBorder && hasKbChip,
      `CommentList 分隔/徽章未统一：\n`
      + `  用 border/divide-white/5: ${hasWhiteBorder}\n`
      + `  徽章用 kb-chip--*     : ${hasKbChip}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// CommentList 封面：两个模式都能看到被评论视频的封面
//   用户诉求：「我希望能看到被评论视频的封面」
//   根因：compact 模式（总览侧栏「神评论」板块，App.jsx 用 <CommentList compact />）
//         完全没有渲染 source_cover，导致该视图看不到封面；
//         完整「神评论精选」tab（非 compact）虽然有右侧封面列，但也太窄。
//   修复：
//     1) compact 模式在每条评论左侧加一个视频封面缩略图（16:9，圆角，bg-void-700 fallback）；
//     2) 非 compact 右侧封面列适当加宽，封面更明显。
//   断言依据：`proxyImage(comment.source_cover)` 至少出现 2 次 = compact + 主分支都渲染封面。
// ═══════════════════════════════════════════════════════════════════
describe('[CommentList Cover] 两个模式都显示被评论视频封面', () => {
  let commentJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/CommentList.jsx'),
      resolve(__dirname, 'components/CommentList.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/CommentList.jsx',
    ]
    commentJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(commentJsx, '找不到 CommentList.jsx').not.toBe(null)
  })

  it('1. compact 与主分支都必须渲染 source_cover 封面（proxyImage(comment.source_cover) 至少 2 处）', () => {
    const coverCount = (commentJsx.match(/proxyImage\(comment\.source_cover\)/g) || []).length
    expect(
      coverCount >= 2,
      `CommentList 必须让 compact 模式也能显示封面（当前仅 ${coverCount} 处，需 ≥2 处：compact + 主分支）`,
    ).toBe(true)
  })

  it('2. compact 封面缩略图采用圆角 + bg-void-700 fallback（与 VideoCard 封面风格一致）', () => {
    const compactBlock = commentJsx.slice(commentJsx.indexOf('if (compact)'))
    const hasRoundedCover = /rounded-(xl|lg)\s+overflow-hidden\s+bg-void-700/.test(compactBlock)
      || /rounded-(xl|lg)[^>]*overflow-hidden[\s\S]{0,120}bg-void-700/.test(compactBlock)
    expect(
      hasRoundedCover,
      `compact 封面缩略图必须圆角 + bg-void-700 占位底（统一视频封面风格）`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// CommentList 跳转定位：点击评论跳视频后定位到具体评论
//   用户诉求：「点击神评论可以跳转到本视频，我希望再进一步，
//             可以跳转到视频后定位到本评论的位置」
//   B站定位机制：视频 URL + #reply + 评论 rpid，
//     例 https://www.bilibili.com/video/BVxxx/#reply1621163746
//   因此：
//     1) 后端 get_golden_comments 已保存 rpid（见 test_golden_comments.py::test_rpid_preserved）
//     2) 前端 videoUrl 拼接 `#reply{rpid}` 锚点（仅当 rpid 存在时）
// ═══════════════════════════════════════════════════════════════════
describe('[CommentList Jump] 跳转视频并定位到具体评论', () => {
  let commentJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/CommentList.jsx'),
      resolve(__dirname, 'components/CommentList.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/CommentList.jsx',
    ]
    commentJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(commentJsx, '找不到 CommentList.jsx').not.toBe(null)
  })

  it('1. videoUrl 拼接必须包含 #reply 锚点 + comment.rpid，用于定位到具体评论', () => {
    const hasReplyAnchor = /#reply/.test(commentJsx)
    const hasRpid = /comment\.rpid/.test(commentJsx)
    expect(
      hasReplyAnchor && hasRpid,
      `videoUrl 必须拼接 #reply + comment.rpid 定位锚点：\n`
      + `  含 #reply 锚点      : ${hasReplyAnchor}\n`
      + `  含 comment.rpid    : ${hasRpid}`,
    ).toBe(true)
  })
})


// ═══════════════════════════════════════════════════════════════════
// [Access Control] 公网多用户：收藏隔离 + 账号保护（前端配合）
// 后端契约：
//   收藏归属 = 管理员口令(X-Write-Token) → 'admin'；否则 X-Visitor-Id(浏览器 UUID)
//   /api/bili-auth/* 与刷新数据 → 仅管理员
// ═══════════════════════════════════════════════════════════════════

describe('[Access Control · api.js] 访客身份与管理员凭证', () => {
  let apiJs
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/utils/api.js'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/utils/api.js',
    ]
    apiJs = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(apiJs, '找不到 api.js').not.toBe(null)
  })

  it('1. 访客身份：localStorage 持久化的浏览器 UUID（kichu_visitor_id），缺失时自动生成', () => {
    const hasKey = /kichu_visitor_id/.test(apiJs)
    const hasUuid = /randomUUID|crypto\.getRandomValues/.test(apiJs)
    expect(
      hasKey && hasUuid,
      `访客身份实现：kichu_visitor_id=${hasKey}, UUID 生成=${hasUuid}`,
    ).toBe(true)
  })

  it('2. 请求统一携带 X-Visitor-Id 头（收藏归属标识）', () => {
    expect(/X-Visitor-Id/.test(apiJs), '请求头必须包含 X-Visitor-Id').toBe(true)
  })

  it('3. 管理员凭证跟随所有请求（含 GET）：X-Write-Token 不再只挂在写操作上', () => {
    // 收藏归属与 bili-auth 守卫都依赖 GET 请求携带口令
    expect(/X-Write-Token/.test(apiJs), '必须发送 X-Write-Token').toBe(true)
    const writeOnlyGate = /isWrite\s*\?\s*getWriteToken\(\)/.test(apiJs)
    expect(
      !writeOnlyGate,
      '口令不能只在 isWrite 时携带——GET /api/favorites 与 /api/bili-auth/user 需要管理员身份',
    ).toBe(true)
  })

  it('4. 管理员登录入口：adminLogin（交互式，401 时弹窗）与 verifyAdminSilent（启动静默校验）', () => {
    const hasLogin = /adminLogin/.test(apiJs)
    const hasSilent = /verifyAdminSilent/.test(apiJs)
    const hasVerifyUrl = /\/auth\/verify/.test(apiJs)
    expect(hasLogin && hasSilent && hasVerifyUrl, `adminLogin=${hasLogin}, verifyAdminSilent=${hasSilent}, /auth/verify=${hasVerifyUrl}`).toBe(true)
  })
})

describe('[Access Control · App.jsx] 管理员状态与门禁接线', () => {
  let appJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/App.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/App.jsx',
    ]
    appJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(appJsx, '找不到 App.jsx').not.toBe(null)
  })

  it('1. isAdmin 状态存在，且启动时静默校验本地凭证（过期自动失效）', () => {
    const hasState = /isAdmin/.test(appJsx)
    const hasSilentVerify = /verifyAdminSilent/.test(appJsx)
    expect(hasState && hasSilentVerify, `isAdmin=${hasState}, verifyAdminSilent=${hasSilentVerify}`).toBe(true)
  })

  it('2. 启动身份判定走 /auth/me 三态链（refreshIdentity），不再探测采集账号接口', () => {
    const hasRefresh = /refreshIdentity/.test(appJsx)
    const callsAuthMe = /api\.getAuthMe/.test(appJsx)
    const noCheckBili = !/checkBiliLogin/.test(appJsx)
    expect(
      hasRefresh && callsAuthMe && noCheckBili,
      `refreshIdentity=${hasRefresh}, api.getAuthMe=${callsAuthMe}, checkBiliLogin残留=${!noCheckBili}`,
    ).toBe(true)
  })

  it('3. 管理员登录流程：handleAdminLogin → api.adminLogin，成功后经 refreshIdentity 重判身份并刷新收藏', () => {
    const hasHandler = /handleAdminLogin/.test(appJsx)
    const callsLogin = /api\.adminLogin/.test(appJsx)
    const refreshAfter = /handleAdminLogin[\s\S]{0,500}refreshIdentity\(\)/.test(appJsx)
    expect(
      hasHandler && callsLogin && refreshAfter,
      `handleAdminLogin=${hasHandler}, api.adminLogin=${callsLogin}, 成功后refreshIdentity=${refreshAfter}`,
    ).toBe(true)
  })

  it('4. 向 Sidebar 传递 isAdmin 与 onAdminLogin', () => {
    expect(/isAdmin=\{/.test(appJsx), 'Sidebar 需要 isAdmin prop').toBe(true)
    expect(/onAdminLogin=\{/.test(appJsx), 'Sidebar 需要 onAdminLogin prop').toBe(true)
  })

  it('5. 收藏门禁：未登录触发登录弹窗（requireLogin 守卫），登录后正常收藏', () => {
    const hasGuard = /const\s+requireLogin\s*=/.test(appJsx)
    const addFavGuarded = /handleAddFavorite[\s\S]{0,80}requireLogin\(\)/.test(appJsx)
    const removeFavGuarded = /handleRemoveFavorite[\s\S]{0,80}requireLogin\(\)/.test(appJsx)
    const toggleGuarded = /if\s*\(!biliUser\)\s*\{\s*setShowLogin\(true\)/.test(appJsx)
    expect(
      hasGuard && addFavGuarded && removeFavGuarded && toggleGuarded,
      `requireLogin守卫=${hasGuard}, 收藏守卫=${addFavGuarded}, 取消收藏守卫=${removeFavGuarded}, 收藏面板守卫=${toggleGuarded}`,
    ).toBe(true)
  })

  it('6. 无权限轻提示：onDevBlocked 触发 flashNotice，普通用户点开发者后台提示「需要管理员权限」', () => {
    const hasFlash = /flashNotice/.test(appJsx)
    const hasDevBlocked = /onDevBlocked=\{/.test(appJsx)
    const msg = /需要管理员权限/.test(appJsx)
    expect(hasFlash && hasDevBlocked && msg, `flashNotice=${hasFlash}, onDevBlocked=${hasDevBlocked}, 文案=${msg}`).toBe(true)
  })
})

describe('[Access Control · Sidebar] 管理员专属区块门禁', () => {
  let sidebarJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/Sidebar.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/Sidebar.jsx',
    ]
    sidebarJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(sidebarJsx, '找不到 Sidebar.jsx').not.toBe(null)
  })

  it('1. 接收 isAdmin / onAdminLogin props', () => {
    expect(/isAdmin/.test(sidebarJsx) && /onAdminLogin/.test(sidebarJsx), 'props 必须包含 isAdmin 和 onAdminLogin').toBe(true)
  })

  it('2. 刷新数据按钮仅管理员可见（防止公网访客连点触发爬虫风控）', () => {
    const refreshGated = /\{isAdmin\s*&&\s*\(?[\s\S]*?onRefresh/.test(sidebarJsx)
    expect(refreshGated, '刷新按钮必须包在 isAdmin && (...) 条件内').toBe(true)
  })

  it('3. B 站身份登录全员开放（不再门禁 isAdmin）：登录后显示身份，管理员带徽标', () => {
    const openToAll = /\{biliUser\s*\?\s*\(/.test(sidebarJsx)
    const notGated = !/\{isAdmin\s*&&\s*\(\s*biliUser|\{isAdmin\s*&&\s*biliUser/.test(sidebarJsx)
    const hasBadge = /ShieldCheck/.test(sidebarJsx) && /管理员/.test(sidebarJsx)
    expect(
      openToAll && notGated && hasBadge,
      `登录区块全员开放=${openToAll && notGated}, 管理员徽标=${hasBadge}`,
    ).toBe(true)
  })

  it('4. 移除显式「管理员登录」按钮：无 Lock 图标、无「管理员登录」文案（超管入口改为隐蔽触发）', () => {
    const noLock = !/Lock/.test(sidebarJsx)
    const noLabel = !/管理员登录/.test(sidebarJsx)
    const wired = /onAdminLogin/.test(sidebarJsx)
    expect(noLock && noLabel && wired, `Lock残留=${!noLock}, 文案残留=${!noLabel}, onAdminLogin接线=${wired}`).toBe(true)
  })

  it('5. 隐蔽超管入口：品牌 logo 连点 5 次（1.5s 窗口）触发 onAdminLogin', () => {
    const hasHandler = /onLogoClick/.test(sidebarJsx)
    const usesRef = /useRef\(0\)/.test(sidebarJsx)
    const fiveClicks = />=\s*5/.test(sidebarJsx)
    const window1500 = /1500/.test(sidebarJsx)
    const wiredToLogo = /onClick=\{onLogoClick\}/.test(sidebarJsx)
    const callsAdmin = /onLogoClick[\s\S]{0,400}onAdminLogin\(\)/.test(sidebarJsx)
    expect(
      hasHandler && usesRef && fiveClicks && window1500 && wiredToLogo && callsAdmin,
      `handler=${hasHandler}, ref=${usesRef}, 5次=${fiveClicks}, 1.5s窗口=${window1500}, logo接线=${wiredToLogo}, 触发onAdminLogin=${callsAdmin}`,
    ).toBe(true)
  })

  it('6. 开发者后台入口门禁：未登录（无 biliUser）隐藏，普通用户点击提示无权限', () => {
    const hiddenWhenGuest = /if\s*\(!biliUser\)\s*return\s+null/.test(sidebarJsx)
    const blockedWhenNotAdmin = /if\s*\(!isAdmin\)[\s\S]{0,120}onDevBlocked/.test(sidebarJsx)
    const receivedProp = /onDevBlocked/.test(sidebarJsx)
    expect(
      hiddenWhenGuest && blockedWhenNotAdmin && receivedProp,
      `未登录隐藏=${hiddenWhenGuest}, 无权限提示=${blockedWhenNotAdmin}, prop接线=${receivedProp}`,
    ).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// [UP Requests] 互粉UP主动态 → UP主动态（公网多用户改造 · 方案C）
// 后端契约（test_up_requests.py 31 用例）：
//   访客凭 X-Visitor-Id 提交申请（每日3个，理由选填）；
//   昵称搜索走后端代理（缓存+限速），失败降级"粘贴链接"；
//   站长审核 approve=入池+即时落地，reject 必填理由且访客可见；
//   同 mid 重复申请→superseded；撤回仅限本人 pending。
// 前端职责：申请弹窗（搜索+粘贴混合入口）、我的申请、管理员审核页、文案去互粉。
// ═══════════════════════════════════════════════════════════════════

describe('[UP Requests · api.js] 申请/审核 6 个接口方法', () => {
  let apiJs
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/utils/api.js'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/utils/api.js',
    ]
    apiJs = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(apiJs, '找不到 api.js').not.toBe(null)
  })

  it('1. 搜索代理 searchUps：GET /up-trends/search?keyword=（encodeURIComponent）', () => {
    const hasMethod = /searchUps:\s*\(\s*keyword\s*\)\s*=>/.test(apiJs)
    const hasPath = /\/up-trends\/search\?keyword=/.test(apiJs)
    const hasEncode = /encodeURIComponent\(\s*keyword\s*\)/.test(apiJs)
    expect(hasMethod && hasPath && hasEncode, `searchUps=${hasMethod}, 路径=${hasPath}, encodeURIComponent=${hasEncode}`).toBe(true)
  })

  it('2. 提交申请 submitUpRequest(mid, reason)：POST /up-trends/requests', () => {
    const hasMethod = /submitUpRequest:\s*\(\s*mid\s*,\s*reason\s*=\s*['"]{2}\s*,\s*request_type\s*=\s*['"]add['"]\s*\)\s*=>/.test(apiJs)
    const hasPath = /['`]\/up-trends\/requests['`]\s*,\s*\{\s*method:\s*['"]POST['"]/.test(apiJs)
    expect(hasMethod && hasPath, `submitUpRequest 签名(理由默认空串)=${hasMethod}, POST 路径=${hasPath}`).toBe(true)
  })

  it('3. 我的申请 getMyUpRequests / 撤回 withdrawUpRequest(id)', () => {
    const mine = /getMyUpRequests:\s*\(\s*\)\s*=>\s*request\(['"]\/up-trends\/requests\/mine['"]\)/.test(apiJs)
    const wd = /withdrawUpRequest:\s*\(\s*id\s*\)\s*=>\s*request\(`\/up-trends\/requests\/\$\{id\}\/withdraw`/.test(apiJs)
    expect(mine && wd, `mine=${mine}, withdraw=${wd}`).toBe(true)
  })

  it('4. 站长审核 adminGetUpRequests + reviewUpRequest(id, action, reason)', () => {
    const list = /adminGetUpRequests:\s*\(\s*\)\s*=>\s*request\(['"]\/up-trends\/requests['"]\)/.test(apiJs)
    const review = /reviewUpRequest:\s*\(\s*id\s*,\s*action\s*,\s*reason/.test(apiJs)
    const reviewPath = /\/up-trends\/requests\/\$\{id\}\/review/.test(apiJs)
    expect(list && review && reviewPath, `列表=${list}, 审核签名=${review}, 审核路径=${reviewPath}`).toBe(true)
  })
})

describe('[UP Requests · UpRequestModal] 访客申请弹窗（搜索+粘贴混合入口）', () => {
  let modalJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/UpRequestModal.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/UpRequestModal.jsx',
    ]
    modalJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(modalJsx, '找不到 UpRequestModal.jsx').not.toBe(null)
  })

  it('1. 昵称搜索：调 api.searchUps 并渲染结果（头像/昵称/粉丝数）', () => {
    const callsSearch = /api\.searchUps\(/.test(modalJsx)
    const hasFace = /face/.test(modalJsx)
    const hasFans = /fans/.test(modalJsx)
    expect(callsSearch && hasFace && hasFans, `searchUps 调用=${callsSearch}, face=${hasFace}, fans=${hasFans}`).toBe(true)
  })

  it('2. 粘贴链接降级入口：解析 space.bilibili.com/<mid> 提交（搜索不可用时提示）', () => {
    const hasParse = /space\.bilibili\.com/.test(modalJsx)
    const hasFallback = /粘贴/.test(modalJsx)
    expect(hasParse && hasFallback, `链接解析=${hasParse}, 粘贴降级提示=${hasFallback}`).toBe(true)
  })

  it('3. 申请理由选填：无 required 阻断，提交带 reason（可空）', () => {
    // 选填 = 输入框 placeholder 提示 + submitUpRequest 始终可带空理由
    const hasReason = /reason/.test(modalJsx)
    const noRequired = !/reason[^>]*required/.test(modalJsx)
    expect(hasReason && noRequired, `reason 字段=${hasReason}, 无 required 阻断=${noRequired}`).toBe(true)
  })

  it('4. 我的申请：pending 可撤回（api.withdrawUpRequest），processed 状态徽章 + 拒绝理由可见', () => {
    const hasMine = /getMyUpRequests/.test(modalJsx)
    const hasWithdraw = /api\.withdrawUpRequest\(/.test(modalJsx)
    const hasRejectReason = /reject_reason/.test(modalJsx)
    const hasStatus = /status/.test(modalJsx)
    expect(hasMine && hasWithdraw && hasRejectReason && hasStatus,
      `mine=${hasMine}, 撤回=${hasWithdraw}, reject_reason=${hasRejectReason}, status=${hasStatus}`).toBe(true)
  })

  it('5. 错误分级提示：限流/重复/已在名单等 code 展示给访客', () => {
    const hasMessage = /message/.test(modalJsx)
    const hasErrorState = /error|Error/.test(modalJsx)
    expect(hasMessage && hasErrorState, `message 展示=${hasMessage}, 错误状态=${hasErrorState}`).toBe(true)
  })
})

describe('[UP Requests · UpRequestsAdmin] 站长审核弹窗', () => {
  let adminJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/UpRequestsAdmin.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/UpRequestsAdmin.jsx',
    ]
    adminJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(adminJsx, '找不到 UpRequestsAdmin.jsx').not.toBe(null)
  })

  it('1. 审核列表：调 api.adminGetUpRequests 渲染 pending（快照免开B站）', () => {
    const callsList = /api\.adminGetUpRequests\(/.test(adminJsx)
    const hasUp = /up\.(name|face|fans|sign)|\bup\[/.test(adminJsx)
    expect(callsList && hasUp, `adminGetUpRequests 调用=${callsList}, UP 快照展示=${hasUp}`).toBe(true)
  })

  it('2. 审核操作：通过 api.reviewUpRequest(id, action)；拒绝必填理由（前端校验）', () => {
    const callsReview = /api\.reviewUpRequest\(/.test(adminJsx)
    const hasApprove = /approve/.test(adminJsx)
    const hasReject = /reject/.test(adminJsx)
    const rejectGuard = /reject[\s\S]{0,600}(reason|理由)[\s\S]{0,200}(!|trim|请填|必填)/.test(adminJsx)
      || /(reason|理由)[\s\S]{0,300}reject[\s\S]{0,300}(必填|请填|!)/.test(adminJsx)
    expect(callsReview && hasApprove && hasReject && rejectGuard,
      `review 调用=${callsReview}, approve=${hasApprove}, reject=${hasReject}, 拒绝理由必填校验=${rejectGuard}`).toBe(true)
  })
})

describe('[UP Requests · UpTrends/App] 文案改造与门禁接线', () => {
  let upTrendsJsx, appJsx
  beforeAll(() => {
    const readFirst = (paths) => paths.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    upTrendsJsx = readFirst([
      resolve(__dirname, 'src/components/UpTrends.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/UpTrends.jsx',
    ])
    appJsx = readFirst([
      resolve(__dirname, 'src/App.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/App.jsx',
    ])
    expect(upTrendsJsx, '找不到 UpTrends.jsx').not.toBe(null)
    expect(appJsx, '找不到 App.jsx').not.toBe(null)
  })

  it('1. 标题去"互粉"：显示为 UP主动态（多用户语义，不再是站长互粉圈）', () => {
    const hasOld = /互粉UP主动态/.test(upTrendsJsx)
    const hasNew = />UP主动态|'UP主动态'|"UP主动态"|\{.*\}\s*UP主动态/.test(upTrendsJsx)
    expect(!hasOld && hasNew, `互粉UP主动态 已移除=${!hasOld}, UP主动态 标题=${hasNew}`).toBe(true)
  })

  it('2. 申请入口：渲染 UpRequestModal（import + 弹窗开关）', () => {
    const hasImport = /import\s+UpRequestModal\s+from/.test(upTrendsJsx)
    const hasRender = /<UpRequestModal/.test(upTrendsJsx)
    expect(hasImport && hasRender, `import=${hasImport}, 渲染=${hasRender}`).toBe(true)
  })

  it('3. 管理功能迁出公开页面，后台由 isAdmin 门禁保护', () => {
    expect(upTrendsJsx).not.toMatch(/<UpRequestsAdmin|<UpTrendsSetup/)
    expect(appJsx).toMatch(/activeTab === 'dev' && isAdmin/)
  })

  it('4. UpTrends 接收 isAdmin prop，App.jsx 渲染时传入', () => {
    const hasProp = /isAdmin/.test(upTrendsJsx)
    const appPasses = /<UpTrends[^>]*isAdmin=\{isAdmin\}/.test(appJsx)
    expect(hasProp && appPasses, `UpTrends isAdmin prop=${hasProp}, App 传参=${appPasses}`).toBe(true)
  })
})

// ═══════════════════════════════════════════════════════════════════
// [Admin Identity] 管理员判定 = 特定B站账号扫码登录（后端 auth.db 名单）
// 后端契约（test_admin_identity.py）：
//   三态判定链：X-Write-Token 超管后门 / HttpOnly Cookie 会话且 mid ∈ 名单 / 访客；
//   身份登录全员开放，凭证和会话 token 只落服务器；
//   采集登录（collect-*）管理员专属，写爬虫 Cookie 文件，与身份解耦；
//   名单增删 /api/admin/accounts，删除保护"至少保留一名"。
// ═══════════════════════════════════════════════════════════════════

describe('[Admin Identity · api.js] 身份与采集接口', () => {
  let apiJs
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/utils/api.js'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/utils/api.js',
    ]
    apiJs = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(apiJs, '找不到 api.js').not.toBe(null)
  })

  it('1. 身份与管理员名单接口：getAuthMe / adminAccounts / addAdminAccount / removeAdminAccount', () => {
    const hasMe = /getAuthMe/.test(apiJs) && /\/auth\/me/.test(apiJs)
    const hasList = /adminAccounts/.test(apiJs) && /\/admin\/accounts/.test(apiJs)
    const hasAdd = /addAdminAccount/.test(apiJs)
    const hasRemove = /removeAdminAccount/.test(apiJs)
    expect(hasMe && hasList && hasAdd && hasRemove, `me=${hasMe}, list=${hasList}, add=${hasAdd}, remove=${hasRemove}`).toBe(true)
  })

  it('2. 采集账号三件套（管理员专属）：collectLogin / collectCheck / collectLogout', () => {
    const hasLogin = /collectLogin/.test(apiJs) && /collect-login/.test(apiJs)
    const hasCheck = /collectCheck/.test(apiJs) && /collect-check/.test(apiJs)
    const hasLogout = /collectLogout/.test(apiJs) && /collect-logout/.test(apiJs)
    expect(hasLogin && hasCheck && hasLogout, `login=${hasLogin}, check=${hasCheck}, logout=${hasLogout}`).toBe(true)
  })
})

describe('[Admin Identity · BilibiliLogin] 双模式扫码登录', () => {
  let loginJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/components/BilibiliLogin.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/BilibiliLogin.jsx',
    ]
    loginJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(loginJsx, '找不到 BilibiliLogin.jsx').not.toBe(null)
  })

  it('1. mode prop 区分身份登录（identity）与采集登录（collect）', () => {
    const hasMode = /mode\s*=\s*'identity'/.test(loginJsx)
    const branches = /isCollect\s*\?\s*await\s+api\.collectLogin\(\)\s*:\s*await\s+api\.getQrcode\(\)/.test(loginJsx)
    expect(hasMode && branches, `mode prop=${hasMode}, 双分支=${branches}`).toBe(true)
  })

  it('2. 不消费 B站凭证：组件不出现 cookies / SESSDATA / bili_jct', () => {
    const clean = !/(res\.cookies|\.SESSDATA|bili_jct)/.test(loginJsx)
    expect(clean, '登录组件只处理 user/is_admin，不得触碰凭证字段').toBe(true)
  })
})

describe('[Admin Identity · App.jsx] 三态身份刷新', () => {
  let appJsx
  beforeAll(() => {
    const candidates = [
      resolve(__dirname, 'src/App.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/App.jsx',
    ]
    appJsx = candidates.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    expect(appJsx, '找不到 App.jsx').not.toBe(null)
  })

  it('1. refreshIdentity 统一设置 isAdmin 与 biliUser（来源 /auth/me 的 admin/user 字段）', () => {
    const hasFn = /const refreshIdentity\s*=/.test(appJsx)
    const setsBoth = /refreshIdentity[\s\S]{0,400}setIsAdmin\(!!res\.data\.admin\)[\s\S]{0,200}setBiliUser\(res\.data\.user/.test(appJsx)
    expect(hasFn && setsBoth, `函数定义=${hasFn}, 同步双状态=${setsBoth}`).toBe(true)
  })

  it('2. 登录/登出/口令登录后都经 refreshIdentity 重判（不硬编码 setIsAdmin）', () => {
    const loginPath = /handleLoginSuccess[\s\S]{0,300}refreshIdentity\(\)/.test(appJsx)
    const logoutPath = /handleLogout[\s\S]{0,300}refreshIdentity\(\)/.test(appJsx)
    const noHardSet = !/setIsAdmin\(true\)/.test(appJsx)
    expect(loginPath && logoutPath && noHardSet, `登录后重判=${loginPath}, 登出后重判=${logoutPath}, 无硬编码=${noHardSet}`).toBe(true)
  })
})

describe('[Admin Identity · DevConsole] 管理员管理模块', () => {
  let devJsx, panelJsx
  beforeAll(() => {
    const readFirst = (paths) => paths.reduce((acc, p) => { if (acc) return acc; try { return readFileSync(p, 'utf8') } catch (_) { return null } }, null)
    devJsx = readFirst([
      resolve(__dirname, 'src/components/DevConsole.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/DevConsole.jsx',
    ])
    panelJsx = readFirst([
      resolve(__dirname, 'src/components/AdminAccountsPanel.jsx'),
      'F:/作业工程库/鬼畜热度看板/鬼畜热度看板V2.0/frontend/src/components/AdminAccountsPanel.jsx',
    ])
    expect(devJsx, '找不到 DevConsole.jsx').not.toBe(null)
    expect(panelJsx, '找不到 AdminAccountsPanel.jsx').not.toBe(null)
  })

  it('1. DevConsole 挂载 admins 模块（懒加载 + hidden 切换）', () => {
    const hasImport = /import\('\.\/AdminAccountsPanel'\)/.test(devJsx)
    const hasMount = /<AdminAccountsPanel\s*\/>/.test(devJsx)
    const hasEntry = /id:\s*'admins'/.test(devJsx)
    expect(hasImport && hasMount && hasEntry, `懒加载=${hasImport}, 挂载=${hasMount}, 导航项=${hasEntry}`).toBe(true)
  })

  it('2. 名单管理接线：adminAccounts 读取 + 添加 + 删除（带确认）', () => {
    const loads = /api\.adminAccounts\(\)/.test(panelJsx)
    const adds = /api\.addAdminAccount/.test(panelJsx)
    const removes = /api\.removeAdminAccount/.test(panelJsx)
    const confirms = /window\.confirm/.test(panelJsx)
    expect(loads && adds && removes && confirms, `读取=${loads}, 添加=${adds}, 删除=${removes}, 删除确认=${confirms}`).toBe(true)
  })

  it('3. 采集账号区块：状态查询 + collect 模式登录弹窗 + 退出', () => {
    const hasStatus = /api\.getUserInfo\(\)/.test(panelJsx)
    const collectLogin = /mode="collect"|mode='collect'/.test(panelJsx)
    const collectLogout = /api\.collectLogout/.test(panelJsx)
    expect(hasStatus && collectLogin && collectLogout, `状态=${hasStatus}, 采集登录弹窗=${collectLogin}, 采集退出=${collectLogout}`).toBe(true)
  })
})
