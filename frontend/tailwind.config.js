/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"PingFang SC"', '"HarmonyOS Sans SC"', '"Noto Sans SC"',
          '"Hiragino Sans GB"', '"Microsoft YaHei"',
          'system-ui', 'sans-serif'
        ],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        // 所有颜色用 CSS 变量驱动，日/夜模式只换变量值
        // ⚠️ 必须使用「rgba(triplet, alpha) 逗号旧语法」：项目运行浏览器对
        //    CSS Color Level 4 斜杠语法 rgb(T / A) 解析为透明（已纯浏览器环境实锤）
        //    rgba(var(--x), <alpha-value>) 同时兼容「无修饰符」「bg-xxx/10 /xx 修饰符」两种产出
        void: {
          950: 'rgba(var(--void-950), <alpha-value>)',
          900: 'rgba(var(--void-900), <alpha-value>)',
          800: 'rgba(var(--void-800), <alpha-value>)',
          700: 'rgba(var(--void-700), <alpha-value>)',
          600: 'rgba(var(--void-600), <alpha-value>)',
        },
        neon: {
          pink:   'rgba(var(--neon-pink),   <alpha-value>)',
          cyan:   'rgba(var(--neon-cyan),   <alpha-value>)',
          violet: 'rgba(var(--neon-violet), <alpha-value>)',
          amber:  'rgba(var(--neon-amber),  <alpha-value>)',
          rose:   'rgba(var(--neon-rose),   <alpha-value>)',
          emerald:'rgba(var(--neon-emerald),<alpha-value>)',
        },
        haze: {
          50:  'rgba(var(--haze-50),  <alpha-value>)',
          100: 'rgba(var(--haze-100), <alpha-value>)',
          300: 'rgba(var(--haze-300), <alpha-value>)',
          400: 'rgba(var(--haze-400), <alpha-value>)',
          500: 'rgba(var(--haze-500), <alpha-value>)',
        },
        // B 站品牌主色
        bili: {
          default: 'rgba(var(--bili-default), <alpha-value>)',   /* 品牌蓝 B 站 LOGO #00AEEC / 夜间 #00A1DB */
          dark:    'rgba(var(--bili-dark),    <alpha-value>)',
        },
        // 全站主操作色：统一由 B 站蓝驱动。
        primary: {
          50:  'rgba(var(--bili-default), 0.08)',
          100: 'rgba(var(--bili-default), 0.16)',
          200: 'rgba(var(--bili-default), 0.28)',
          300: 'rgba(var(--bili-default), 0.52)',
          400: 'rgba(var(--bili-default), 0.78)',
          500: 'rgba(var(--bili-default), 1)',
          600: 'rgba(var(--bili-dark), 1)',
          700: 'rgba(var(--bili-dark), 1)',
        },
      },
      boxShadow: {
        'card':       'var(--shadow-card)',
        'card-hover': 'var(--shadow-card-hover)',
        'glow-pink':   'var(--shadow-glow-pink)',
        'glow-cyan':   'var(--shadow-glow-cyan)',
        'glow-violet': 'var(--shadow-glow-violet)',
        'glow-rose':   'var(--shadow-glow-rose)',
        'btn-pink': 'var(--shadow-btn-pink)',
      },
      borderRadius: { 'xl2': '1rem' },
      keyframes: {
        // 终态必须是 transform:'none' 而非 'translateY(0)'：
        // 'translateY(0)' 虽视觉无位移，但属于非 none 的 transform，配合 both/forwards
        // 填充模式会永久钉在元素上，使该容器成为所有 position:fixed 后代的包含块
        // → 页面内弹窗改按文档盒（而非视口）居中。'none' 不创建包含块。
        'stagger-in': { '0%': { opacity:'0', transform:'translateY(10px)' }, '100%': { opacity:'1', transform:'none' } },
        'pulse-dot':  { '0%,100%': { opacity:'1', transform:'scale(1)' }, '50%': { opacity:'.4', transform:'scale(0.8)' } },
        'equalizer':  { '0%,100%': { transform:'scaleY(0.3)' }, '50%': { transform:'scaleY(1)' } },
        'glow-breath':{ '0%,100%': { boxShadow:'var(--glow-breath-1)' }, '50%': { boxShadow:'var(--glow-breath-2)' } },
      },
      animation: {
        'stagger-in': 'stagger-in 480ms cubic-bezier(.2,.7,.2,1) both',
        'pulse-dot':  'pulse-dot 1.8s ease-in-out infinite',
        'glow-breath': 'glow-breath 3s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
