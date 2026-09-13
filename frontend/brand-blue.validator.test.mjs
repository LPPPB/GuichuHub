import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const read = (file) => readFileSync(join(root, file), 'utf8')

describe('B 站蓝全站交互主色', () => {
  const tailwind = read('tailwind.config.js')
  const css = read('src/index.css')
  const devPanel = read('src/components/DevPanel.jsx')
  const upTrends = read('src/components/UpTrends.jsx')

  it('primary 色阶必须绑定独立 bili 通道，不能回退到数据语义粉', () => {
    const primaryBlock = tailwind.match(/primary:\s*\{([\s\S]*?)\n\s*\}/)?.[1] || ''
    expect(primaryBlock).toContain("500: 'rgba(var(--bili-default), 1)'")
    expect(primaryBlock).toContain("600: 'rgba(var(--bili-dark), 1)'")
    expect(primaryBlock).not.toContain('--neon-pink')
  })

  it('键盘焦点和通用图标按钮使用品牌蓝', () => {
    expect(css).toMatch(/:focus-visible\s*\{[^}]*--bili-default/s)
    expect(css).toMatch(/\.kb-icon-btn:hover\s*\{[^}]*--bili-default/s)
  })

  it('开发者后台和 UP 主动态的选中操作使用 primary 主色', () => {
    expect(devPanel).toContain("bg-primary-500 text-white")
    expect(upTrends).toContain("view === 'analysis' ? 'bg-primary-500 text-white'")
    expect(upTrends).toContain('bg-primary-500 text-white rounded-lg')
  })
})
