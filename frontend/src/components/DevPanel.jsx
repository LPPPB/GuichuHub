import { useState, useEffect } from 'react'
import { api } from '../utils/api'
import {
  X, Plus, Save, Loader2, AlertTriangle,
  Layers, ListChecks, Filter, MessageSquare, Info,
  LayoutDashboard, BookOpen, FlaskConical, CheckCircle2, Clock3, Search,
} from 'lucide-react'

// 简单词表编辑器：chips + 输入框（品牌词/活动词/放行名单/弹幕词共用）
// extra：可选前置说明（如"二字词默认拦截"规则条）
function ListEditor({ title, desc, items, input, onInput, onAdd, onRemove, placeholder, extra }) {
  return (
    <div className="bg-white rounded-lg p-3 border border-slate-200">
      {extra}
      <h3 className="text-xs font-bold text-slate-700 mb-1">
        {title}
        <span className="text-slate-500 font-normal ml-1">({items.length})</span>
      </h3>
      {desc && <p className="text-[11px] text-slate-500 mb-2">{desc}</p>}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {items.map((w) => (
          <span
            key={w}
            className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs group"
          >
            {w}
            <button
              onClick={() => onRemove(w)}
              title={`删除 "${w}"`}
              className="text-slate-500 hover:text-red-500 transition-colors"
            >
              <X size={11} />
            </button>
          </span>
        ))}
        {items.length === 0 && <span className="text-xs text-slate-500">（空）</span>}
      </div>
      <div className="flex gap-1.5">
        <input
          value={input}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onAdd()
          }}
          placeholder={placeholder}
          className="flex-1 min-w-0 bg-slate-100 border border-slate-300 rounded px-2 py-1 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
        />
        <button
          onClick={onAdd}
          title="添加"
          className="flex items-center justify-center w-7 h-7 bg-slate-100 hover:bg-slate-200 rounded text-slate-700 transition-colors"
        >
          <Plus size={13} />
        </button>
      </div>
    </div>
  )
}

// 词库定位说明条：每份词库顶部解释"管什么 + 怎么匹配"
function InfoBar({ icon: Icon, title, items }) {
  return (
    <div className="flex items-start gap-2 bg-slate-100 border border-slate-200 rounded-lg px-3 py-2 text-xs text-slate-600">
      <Icon size={14} className="text-slate-400 mt-0.5 shrink-0" />
      <div>
        <span className="font-semibold text-slate-700">{title}</span>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
          {items.map((t, i) => (
            <span key={i} className="text-slate-500">· {t}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// 开发者模式：词表配置（梗素材库停用词 + 种子热梗词 + 标签过滤 + 弹幕热词）
export default function DevPanel() {
  const [tab, setTab] = useState('overview')
  const [overview, setOverview] = useState(null)
  const [commonQuery, setCommonQuery] = useState('')
  const [testText, setTestText] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  // 梗素材库停用词表（分类结构）
  const [categories, setCategories] = useState(null)
  const [inputs, setInputs] = useState({})
  // 种子热梗词（列表）
  const [seedWords, setSeedWords] = useState([])
  const [seedInput, setSeedInput] = useState('')
  // 标签过滤词表（is_useless_tag 共享）
  const [tagFilters, setTagFilters] = useState(null)
  const [tagInputs, setTagInputs] = useState({})
  const [adInput, setAdInput] = useState('')
  const [actInput, setActInput] = useState('')
  const [twoInput, setTwoInput] = useState('')
  // 弹幕热词过滤词表（filter_danmaku_words 共享）
  const [danmakuFilters, setDanmakuFilters] = useState(null)
  const [dmAllowInput, setDmAllowInput] = useState('')
  const [dmExactInput, setDmExactInput] = useState('')
  const [dmSubstrInput, setDmSubstrInput] = useState('')

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    load()
  }, [])

  const load = async () => {
    setLoading(true)
    setMsg(null)
    try {
      const [sw, sd, tf, df] = await Promise.all([
        api.getMemeStopwords(),
        api.getMemeSeedWords(),
        api.getTagFilters(),
        api.getDanmakuFilters(),
      ])
      api.getWordRulesOverview().then((res) => {
        if (res.success) setOverview(res.data || null)
      }).catch(() => {})
      if (sw.success && sw.data) {
        setCategories(sw.data.categories || {})
        setInputs({})
      } else {
        setMsg({ type: 'error', text: sw.message || '停用词表加载失败' })
      }
      if (sd.success && sd.data) {
        setSeedWords(sd.data.words || [])
      } else {
        setMsg({ type: 'error', text: sd.message || '种子热梗词加载失败' })
      }
      if (tf.success && tf.data) {
        setTagFilters({
          categories: tf.data.categories || {},
          ad_keywords: tf.data.ad_keywords || [],
          activity_keywords: tf.data.activity_keywords || [],
          allowed_two_char: tf.data.allowed_two_char || [],
        })
        setTagInputs({})
      } else {
        setMsg({ type: 'error', text: tf.message || '标签过滤词表加载失败' })
      }
      if (df.success && df.data) {
        setDanmakuFilters({
          allowed_exact: df.data.allowed_exact || [],
          bad_exact: df.data.bad_exact || [],
          bad_substr: df.data.bad_substr || [],
        })
      } else {
        setMsg({ type: 'error', text: df.message || '弹幕热词过滤词表加载失败' })
      }
    } catch (e) {
      setMsg({ type: 'error', text: '配置加载失败' })
    }
    setLoading(false)
  }

  // ── 停用词表操作 ──
  const addWord = (cat) => {
    const val = (inputs[cat] || '').trim()
    if (!val) return
    const words = (categories[cat] || []).slice()
    val.split(/[\s,，、]+/).forEach((w) => {
      if (w && !words.includes(w)) words.push(w)
    })
    setCategories({ ...categories, [cat]: words })
    setInputs({ ...inputs, [cat]: '' })
  }

  const removeWord = (cat, word) => {
    setCategories({ ...categories, [cat]: categories[cat].filter((w) => w !== word) })
  }

  // ── 种子热梗词操作 ──
  const addSeedWord = () => {
    const val = seedInput.trim()
    if (!val) return
    const words = seedWords.slice()
    val.split(/[\s,，、]+/).forEach((w) => {
      if (w && !words.includes(w)) words.push(w)
    })
    setSeedWords(words)
    setSeedInput('')
  }

  const removeSeedWord = (word) => {
    setSeedWords(seedWords.filter((w) => w !== word))
  }

  // ── 标签过滤词表操作 ──
  const addTagCatWord = (cat) => {
    const val = (tagInputs[cat] || '').trim()
    if (!val || !tagFilters) return
    const words = (tagFilters.categories[cat] || []).slice()
    val.split(/[\s,，、]+/).forEach((w) => {
      if (w && !words.includes(w)) words.push(w)
    })
    setTagFilters({ ...tagFilters, categories: { ...tagFilters.categories, [cat]: words } })
    setTagInputs({ ...tagInputs, [cat]: '' })
  }

  const removeTagCatWord = (cat, word) => {
    if (!tagFilters) return
    setTagFilters({
      ...tagFilters,
      categories: {
        ...tagFilters.categories,
        [cat]: tagFilters.categories[cat].filter((w) => w !== word),
      },
    })
  }

  const addTagListWord = (key, val) => {
    if (!val.trim() || !tagFilters) return
    const items = (tagFilters[key] || []).slice()
    val.split(/[\s,，、]+/).forEach((w) => {
      if (w && !items.includes(w)) items.push(w)
    })
    setTagFilters({ ...tagFilters, [key]: items })
  }

  const removeTagListWord = (key, word) => {
    if (!tagFilters) return
    setTagFilters({ ...tagFilters, [key]: tagFilters[key].filter((w) => w !== word) })
  }

  // ── 弹幕热词过滤词表操作 ──
  const addDanmakuListWord = (key, val) => {
    if (!val.trim() || !danmakuFilters) return
    const items = (danmakuFilters[key] || []).slice()
    val.split(/[\s,，、]+/).forEach((w) => {
      if (w && !items.includes(w)) items.push(w)
    })
    setDanmakuFilters({ ...danmakuFilters, [key]: items })
  }

  const removeDanmakuListWord = (key, word) => {
    if (!danmakuFilters) return
    setDanmakuFilters({ ...danmakuFilters, [key]: danmakuFilters[key].filter((w) => w !== word) })
  }

  const save = async () => {
    setSaving(true)
    setMsg(null)
    let savedRes = null
    try {
      if (tab === 'stopwords') {
        savedRes = await api.saveMemeStopwords(categories)
      } else if (tab === 'seedwords') {
        savedRes = await api.saveMemeSeedWords(seedWords)
      } else if (tab === 'tagfilters') {
        savedRes = await api.saveTagFilters(tagFilters)
      } else {
        savedRes = await api.saveDanmakuFilters(danmakuFilters)
      }
      setMsg({
        type: savedRes.success ? 'ok' : 'error',
        text: savedRes.message || (savedRes.success ? '保存成功' : '保存失败'),
      })
    } catch (e) {
      setMsg({ type: 'error', text: '保存失败' })
    }
    setSaving(false)
    if (savedRes?.success) {
      api.getWordRulesOverview().then((next) => {
        if (next.success) setOverview(next.data || null)
      }).catch(() => {})
    }
  }

  const runRuleTest = async () => {
    if (!testText.trim()) return
    setTesting(true)
    setMsg(null)
    try {
      const res = await api.testWordRules(testText.trim())
      if (res.success) setTestResult(res.data)
      else setMsg({ type: 'error', text: res.message || '规则测试失败' })
    } catch (_) {
      setMsg({ type: 'error', text: '规则测试失败' })
    }
    setTesting(false)
  }

  const total = categories
    ? Object.values(categories).reduce((s, v) => s + v.length, 0)
    : 0
  const tagTotal = tagFilters
    ? Object.values(tagFilters.categories).reduce((s, v) => s + v.length, 0) +
      (tagFilters.ad_keywords || []).length +
      (tagFilters.activity_keywords || []).length +
      (tagFilters.allowed_two_char || []).length
    : 0
  const dmTotal = danmakuFilters
    ? (danmakuFilters.allowed_exact || []).length + (danmakuFilters.bad_exact || []).length + (danmakuFilters.bad_substr || []).length
    : 0

  const editableTab = ['stopwords', 'seedwords', 'tagfilters', 'danmaku'].includes(tab)
  const effectText = {
    stopwords: '下次全量抓取生效',
    seedwords: '下次全量抓取生效',
    tagfilters: '标签热度立即生效；素材结果下次抓取更新',
    danmaku: '词云与升温榜立即生效',
  }[tab]
  const filteredCommon = (overview?.common_stopwords || []).filter((word) =>
    !commonQuery.trim() || word.toLowerCase().includes(commonQuery.trim().toLowerCase())
  )

  return (
    <div className="text-slate-800">
      <div className="max-w-7xl mx-auto px-4 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-bold flex items-center gap-2">
              开发者模式 · 词汇规则中心
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              一套公共底座 + 三个榜单场景规则；每条规则都能查到作用范围、命中方式和生效时间。
            </p>
          </div>
          <div className="flex items-center gap-2">
            {msg && (
              <span
                className={`text-xs px-2 py-1 rounded flex items-center gap-1 ${
                  msg.type === 'ok'
                    ? 'bg-green-50 text-green-600'
                    : 'bg-red-50 text-red-600'
                }`}
              >
                {msg.type === 'error' && <AlertTriangle size={12} />}
                {msg.text}
              </span>
            )}
            {editableTab && (
              <div className="flex items-center gap-2">
                <span className="hidden xl:inline text-[11px] text-slate-500">{effectText}</span>
                <button
                  onClick={save}
                  disabled={saving || loading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  保存规则
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 信息架构：理解规则 → 编辑场景 → 验证结果；种子词归入采集策略。 */}
        <div className="flex flex-wrap items-center gap-1.5 mb-3 rounded-xl border border-slate-200 bg-white p-2">
          <button
            onClick={() => { setTab('overview'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === 'overview' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            <LayoutDashboard size={13} />规则总览
          </button>
          <button
            onClick={() => { setTab('common'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === 'common' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            <BookOpen size={13} />公共规则（{overview?.counts?.common || 0}）
          </button>
          <span className="mx-1 h-5 w-px bg-slate-200" />
          <span className="px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">榜单规则</span>
          <button
            onClick={() => { setTab('stopwords'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === 'stopwords'
                ? 'bg-primary-500 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <Layers size={13} />
            素材/热梗（{total}）
          </button>
          <button
            onClick={() => { setTab('tagfilters'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === 'tagfilters'
                ? 'bg-primary-500 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <Filter size={13} />
            标签热度（{tagTotal}）
          </button>
          <button
            onClick={() => { setTab('danmaku'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === 'danmaku'
                ? 'bg-primary-500 text-white'
                : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <MessageSquare size={13} />
            弹幕热词（{dmTotal}）
          </button>
          <span className="mx-1 h-5 w-px bg-slate-200" />
          <span className="px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">采集策略</span>
          <button
            onClick={() => { setTab('seedwords'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === 'seedwords' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-100'
            }`}
          >
            <ListChecks size={13} />采集种子词（{seedWords.length}）
          </button>
          <button
            onClick={() => { setTab('test'); setMsg(null) }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === 'test' ? 'bg-primary-500 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            <FlaskConical size={13} />规则测试台
          </button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-4">
            <Loader2 size={16} className="animate-spin" /> 加载中...
          </div>
        ) : tab === 'overview' ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              {[
                ['公共停用词', overview?.counts?.common || 0, '所有分词场景的基础层', BookOpen],
                ['素材规则', total, '素材候选与热梗库', Layers],
                ['标签规则', tagTotal, '鬼畜标签热度与标题词', Filter],
                ['弹幕规则', dmTotal, '词云与升温榜', MessageSquare],
                ['采集种子词', seedWords.length, '主动搜索，不是过滤', ListChecks],
              ].map(([name, count, desc, Icon]) => (
                <div key={name} className="rounded-xl border border-slate-200 bg-white p-3">
                  <div className="flex items-center justify-between">
                    <Icon size={15} className="text-primary-500" />
                    <span className="text-lg font-bold tabular-nums text-slate-800">{count}</span>
                  </div>
                  <p className="mt-2 text-xs font-semibold text-slate-700">{name}</p>
                  <p className="mt-0.5 text-[11px] text-slate-500">{desc}</p>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] gap-3">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-bold text-slate-800">统一判定顺序</h3>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  {['格式清洗', '场景白名单', '公共停用词', '广告/活动污染词', '榜单专属规则'].map((step, index) => (
                    <div key={step} className="flex items-center gap-2">
                      <span className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-slate-700">{index + 1}. {step}</span>
                      {index < 4 && <span className="text-slate-300">→</span>}
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[11px] leading-5 text-slate-500">
                  白名单只覆盖普通停用规则；空文本、URL 等强制无效内容仍会被清除。榜单生产与“规则测试台”共用同一判定入口。
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-bold text-slate-800">保存后何时生效</h3>
                <div className="mt-2 space-y-2">
                  {Object.entries(overview?.effects || {}).map(([key, text]) => (
                    <div key={key} className="flex items-start gap-2 text-xs">
                      {text.includes('立即') ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-green-500" /> : <Clock3 size={14} className="mt-0.5 shrink-0 text-amber-500" />}
                      <span className="w-16 font-medium text-slate-700">{{ common: '公共规则', meme: '素材规则', tag: '标签规则', danmaku: '弹幕规则', seed: '种子词' }[key]}</span>
                      <span className="text-slate-500">{text}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : tab === 'common' ? (
          <div className="space-y-3">
            <InfoBar
              icon={BookOpen}
              title="公共停用词（系统底座）"
              items={['所有真实弹幕分词统一使用', '以精确匹配为主', '榜单专属白名单可放行数字梗等例外']}
            />
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-xs font-bold text-slate-700">系统内置公共词</h3>
                  <p className="mt-0.5 text-[11px] text-slate-500">公共底座只读，避免误删影响所有榜单；场景差异请到对应榜单规则中配置。</p>
                </div>
                <div className="relative w-56">
                  <Search size={13} className="absolute left-2.5 top-2 text-slate-400" />
                  <input value={commonQuery} onChange={(e) => setCommonQuery(e.target.value)} placeholder="搜索公共词"
                         className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-xs outline-none focus:border-primary-300" />
                </div>
              </div>
              <div className="max-h-[48vh] overflow-y-auto pr-1">
                <div className="flex flex-wrap gap-1.5">
                  {filteredCommon.map((word) => <span key={word} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">{word}</span>)}
                  {filteredCommon.length === 0 && <span className="text-xs text-slate-400">没有匹配的公共词</span>}
                </div>
              </div>
            </div>
          </div>
        ) : tab === 'test' ? (
          <div className="space-y-3">
            <InfoBar
              icon={FlaskConical}
              title="规则测试台"
              items={['使用生产环境同一判定入口', '支持空格/逗号一次测试多个词', '不会修改任何配置或榜单数据']}
            />
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex gap-2">
                <input value={testText} onChange={(e) => setTestText(e.target.value)}
                       onKeyDown={(e) => { if (e.key === 'Enter') runRuleTest() }}
                       placeholder="输入词语，例如：其实 好听 哈基米 666 美团外卖"
                       className="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-primary-300" />
                <button onClick={runRuleTest} disabled={testing || !testText.trim()}
                        className="flex items-center gap-1.5 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                  {testing ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}测试规则
                </button>
              </div>
              {testResult?.tokens?.length > 0 && (
                <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr><th className="px-3 py-2">词语</th><th className="px-3 py-2">素材/热梗</th><th className="px-3 py-2">标签热度</th><th className="px-3 py-2">弹幕热词</th></tr>
                    </thead>
                    <tbody>
                      {testResult.tokens.map((token) => (
                        <tr key={token.word} className="border-t border-slate-100">
                          <td className="px-3 py-2 font-semibold text-slate-800">{token.word}</td>
                          {['meme', 'tag', 'danmaku'].map((scope) => {
                            const result = token.scopes[scope]
                            return <td key={scope} className="px-3 py-2">
                              <span className={`mr-2 rounded px-1.5 py-0.5 font-medium ${result.accepted ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'}`}>{result.accepted ? '保留' : '过滤'}</span>
                              <span className="text-slate-500">{result.category}{result.matched ? ` · 命中“${result.matched}”` : ''}</span>
                            </td>
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : tab === 'stopwords' ? (
          <div className="space-y-3">
            <InfoBar
              icon={Layers}
              title="梗素材库停用词"
              items={[
                '管：梗素材库候选词、热梗库关键词',
                '匹配：整词命中即剔除',
                '和"标签过滤"互不影响，但这里的词同时作用于热梗库',
              ]}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 max-h-[50vh] overflow-y-auto pr-1">
              {categories &&
                Object.entries(categories).map(([cat, words]) => (
                  <div
                    key={cat}
                    className="bg-white rounded-lg p-3 border border-slate-200"
                  >
                    <h3 className="text-xs font-bold text-slate-700 mb-2">
                      {cat}
                      <span className="text-slate-500 font-normal ml-1">
                        ({words.length})
                      </span>
                    </h3>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {words.map((w) => (
                        <span
                          key={w}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs group"
                        >
                          {w}
                          <button
                            onClick={() => removeWord(cat, w)}
                            title={`删除 "${w}"`}
                            className="text-slate-500 hover:text-red-500 transition-colors"
                          >
                            <X size={11} />
                          </button>
                        </span>
                      ))}
                      {words.length === 0 && (
                        <span className="text-xs text-slate-500">（空）</span>
                      )}
                    </div>
                    <div className="flex gap-1.5">
                      <input
                        value={inputs[cat] || ''}
                        onChange={(e) => setInputs({ ...inputs, [cat]: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') addWord(cat)
                        }}
                        placeholder="添加词（支持空格/逗号分隔多个）"
                        className="flex-1 min-w-0 bg-slate-100 border border-slate-300 rounded px-2 py-1 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
                      />
                      <button
                        onClick={() => addWord(cat)}
                        title="添加"
                        className="flex items-center justify-center w-7 h-7 bg-slate-100 hover:bg-slate-200 rounded text-slate-700 transition-colors"
                      >
                        <Plus size={13} />
                      </button>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        ) : tab === 'seedwords' ? (
          <div className="space-y-3">
            <InfoBar
              icon={ListChecks}
              title="种子热梗词"
              items={[
                '管：抓取时主动搜索的热梗词（不是过滤）',
                '保证哈基米/叮咚鸡等常驻热梗不被"频次≥3"门槛过滤',
                '优先级最高，即使被停用词表误伤也保留',
              ]}
            />
            <div className="bg-white rounded-lg p-3 border border-slate-200 max-h-[50vh] overflow-y-auto pr-1">
              <div className="flex flex-wrap gap-1.5 mb-3">
                {seedWords.map((w) => (
                  <span
                    key={w}
                    className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs group"
                  >
                    {w}
                    <button
                      onClick={() => removeSeedWord(w)}
                      title={`删除 "${w}"`}
                      className="text-slate-500 hover:text-red-500 transition-colors"
                    >
                      <X size={11} />
                    </button>
                  </span>
                ))}
                {seedWords.length === 0 && (
                  <span className="text-xs text-slate-500">（空，退化为纯自动发现）</span>
                )}
              </div>
              <div className="flex gap-1.5">
                <input
                  value={seedInput}
                  onChange={(e) => setSeedInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') addSeedWord()
                  }}
                  placeholder="添加热梗词（如：电棍 / 只因）"
                  className="flex-1 min-w-0 bg-slate-100 border border-slate-300 rounded px-2 py-1 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
                />
                <button
                  onClick={addSeedWord}
                  title="添加"
                  className="flex items-center justify-center w-7 h-7 bg-slate-100 hover:bg-slate-200 rounded text-slate-700 transition-colors"
                >
                  <Plus size={13} />
                </button>
              </div>
            </div>
          </div>
        ) : tab === 'tagfilters' ? (
          <div className="space-y-3">
            <InfoBar
              icon={Filter}
              title="标签过滤"
              items={[
                '管：视频标签/标题提取的关键词（热梗、弹幕提取共用）',
                '品牌/活动词按子串匹配，分类词按整词匹配',
                '正好 2 个字的词默认拦截，需加入"二字词放行名单"',
              ]}
            />
            {/* 品牌 / 活动（子串匹配） */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <ListEditor
                title="广告品牌（子串）"
                desc="标签里包含品牌名即剔除，可只填品牌（如：友望）"
                items={tagFilters?.ad_keywords || []}
                input={adInput}
                onInput={setAdInput}
                onAdd={() => { addTagListWord('ad_keywords', adInput); setAdInput('') }}
                onRemove={(w) => removeTagListWord('ad_keywords', w)}
                placeholder="添加品牌（如：友望）"
              />
              <ListEditor
                title="活动词（子串）"
                desc="企划/比赛/期数等时效标签，包含即剔除"
                items={tagFilters?.activity_keywords || []}
                input={actInput}
                onInput={setActInput}
                onAdd={() => { addTagListWord('activity_keywords', actInput); setActInput('') }}
                onRemove={(w) => removeTagListWord('activity_keywords', w)}
                placeholder="添加活动词（如：企划）"
              />
            </div>

            {/* 二字词规则：默认拦截 + 放行名单 */}
            <ListEditor
              title="二字词放行名单"
              desc="正好 2 个字的标签默认是干扰（如“阳光”“彩虹”），只有放行名单里的才保留"
              items={tagFilters?.allowed_two_char || []}
              input={twoInput}
              onInput={setTwoInput}
              onAdd={() => { addTagListWord('allowed_two_char', twoInput); setTwoInput('') }}
              onRemove={(w) => removeTagListWord('allowed_two_char', w)}
              placeholder="添加二字梗（如：大狗/坤坤）"
              extra={
                <div className="flex items-start gap-1.5 bg-amber-50 border border-amber-200 rounded-md px-2 py-1.5 mb-2">
                  <Info size={13} className="text-amber-500 mt-0.5 shrink-0" />
                  <p className="text-[11px] text-amber-700">
                    <b>二字词默认拦截</b>：长度正好 2 个字的标签（如"阳光""彩虹"）默认视为干扰被过滤，
                    避免泛词混入；只有加入放行名单才会保留（如 大狗/坤坤/甲亢）。
                  </p>
                </div>
              }
            />

            {/* 分类停用词表（整词匹配） */}
            <div>
              <h3 className="text-xs font-bold text-slate-700 mb-1">
                分类停用词表（整词）
                <span className="text-slate-500 font-normal ml-1">
                  （{tagFilters ? Object.values(tagFilters.categories).reduce((s, v) => s + v.length, 0) : 0}）
                </span>
              </h3>
              <p className="text-[11px] text-slate-500 mb-2">
                整词精确命中即剔除（如"鬼畜""瑞幸""视频"），与上方品牌/活动子串匹配互补。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 max-h-[38vh] overflow-y-auto pr-1">
                {tagFilters &&
                  Object.entries(tagFilters.categories).map(([cat, words]) => (
                    <div key={cat} className="bg-white rounded-lg p-3 border border-slate-200">
                      <h4 className="text-xs font-bold text-slate-700 mb-2">
                        {cat}
                        <span className="text-slate-500 font-normal ml-1">
                          ({words.length})
                        </span>
                      </h4>
                      <div className="flex flex-wrap gap-1.5 mb-2">
                        {words.map((w) => (
                          <span
                            key={w}
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs group"
                          >
                            {w}
                            <button
                              onClick={() => removeTagCatWord(cat, w)}
                              title={`删除 "${w}"`}
                              className="text-slate-500 hover:text-red-500 transition-colors"
                            >
                              <X size={11} />
                            </button>
                          </span>
                        ))}
                        {words.length === 0 && (
                          <span className="text-xs text-slate-500">（空）</span>
                        )}
                      </div>
                      <div className="flex gap-1.5">
                        <input
                          value={tagInputs[cat] || ''}
                          onChange={(e) => setTagInputs({ ...tagInputs, [cat]: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') addTagCatWord(cat)
                          }}
                          placeholder="添加词（空格/逗号分隔）"
                          className="flex-1 min-w-0 bg-slate-100 border border-slate-300 rounded px-2 py-1 text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:border-slate-400"
                        />
                        <button
                          onClick={() => addTagCatWord(cat)}
                          title="添加"
                          className="flex items-center justify-center w-7 h-7 bg-slate-100 hover:bg-slate-200 rounded text-slate-700 transition-colors"
                        >
                          <Plus size={13} />
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <InfoBar
              icon={MessageSquare}
              title="弹幕热词过滤"
              items={[
                '管：弹幕词云与弹幕热词升温榜',
                '先经过公共停用词，再应用这里的白名单/黑名单',
                '保存后立即清除缓存并影响已有观测结果',
              ]}
            />
            <ListEditor
              title="弹幕白名单（优先放行）"
              desc="用于 233/666 等数字梗或被公共规则误伤的弹幕词；只影响弹幕场景"
              items={danmakuFilters?.allowed_exact || []}
              input={dmAllowInput}
              onInput={setDmAllowInput}
              onAdd={() => { addDanmakuListWord('allowed_exact', dmAllowInput); setDmAllowInput('') }}
              onRemove={(w) => removeDanmakuListWord('allowed_exact', w)}
              placeholder="添加放行词（如：666）"
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <ListEditor
                title="精确匹配"
                desc="整词命中即剔除（如：美团/星巴克/必剪创作）"
                items={danmakuFilters?.bad_exact || []}
                input={dmExactInput}
                onInput={setDmExactInput}
                onAdd={() => { addDanmakuListWord('bad_exact', dmExactInput); setDmExactInput('') }}
                onRemove={(w) => removeDanmakuListWord('bad_exact', w)}
                placeholder="添加精确词（如：美团）"
              />
              <ListEditor
                title="子串匹配"
                desc="包含即剔除，可只填品牌/活动名（如：途虎）"
                items={danmakuFilters?.bad_substr || []}
                input={dmSubstrInput}
                onInput={setDmSubstrInput}
                onAdd={() => { addDanmakuListWord('bad_substr', dmSubstrInput); setDmSubstrInput('') }}
                onRemove={(w) => removeDanmakuListWord('bad_substr', w)}
                placeholder="添加子串词（如：途虎）"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
