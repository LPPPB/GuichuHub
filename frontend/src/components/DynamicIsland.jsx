import { createContext, useContext, useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'

// ════════════════════════════════════════════════════════════════════
// 灵动岛式展开动画（Dynamic Island）通用组件
//
// 核心原理：framer-motion 共享布局动画（layoutId）——锚点与浮层用同一
// layoutId，打开/关闭时自动做 FLIP 过渡，元素从原位置弹性"弹"成浮层。
//
// 用法（三步）：
//   <IslandProvider>
//     <div onClick={() => openIsland('key')}>触发元素（卡片）</div>
//     <IslandAnchor id="key">动画起点（如迷你图）</IslandAnchor>
//     <IslandOverlay id="key" className="w-full max-w-2xl p-5">
//       浮层大图内容
//     </IslandOverlay>
//   </IslandProvider>
//
// 关闭方式：Esc / 点击毛玻璃遮罩 / 浮层内部调用 useIsland().closeIsland()
// ════════════════════════════════════════════════════════════════════

// spring 曲线：苹果原生手感，带回弹 overshoot
const SPRING = { type: 'spring', stiffness: 240, damping: 28 }

const IslandContext = createContext(null)

export function IslandProvider({ children }) {
  const [openId, setOpenId] = useState(null)
  const openIsland = useCallback((id) => setOpenId(id), [])
  const closeIsland = useCallback(() => setOpenId(null), [])
  return (
    <IslandContext.Provider value={{ openId, openIsland, closeIsland }}>
      {children}
    </IslandContext.Provider>
  )
}

export function useIsland() {
  return useContext(IslandContext)
}

// ── 动画锚点 ──────────────────────────────────────────────────────────
// 放在触发元素内部（通常是迷你图/缩略区域），浮层打开/关闭时从它缩放
export function IslandAnchor({ id, className = '', children }) {
  return (
    <motion.div layoutId={`island-${id}`} className={className} transition={SPRING}>
      {children}
    </motion.div>
  )
}

// ── 浮层 ──────────────────────────────────────────────────────────────
// 与锚点共享 layoutId：从锚点位置弹性展开到屏幕中央，毛玻璃遮罩淡入
export function IslandOverlay({ id, className = '', children }) {
  const { openId, closeIsland } = useIsland()
  const isOpen = openId === id

  // Esc 关闭
  useEffect(() => {
    if (!isOpen) return
    const handler = (e) => { if (e.key === 'Escape') closeIsland() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, closeIsland])

  // Portal 到 document.body：浮层的 fixed 定位脱离页面动画容器的 transform 包含块，
  // 始终相对视口居中（framer-motion 共享布局动画不受 Portal 影响，仍正常做 FLIP 过渡）
  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          {/* 毛玻璃遮罩（点击关闭） */}
          <motion.div
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]"
            onClick={closeIsland}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          {/* 大图卡片：与锚点共享 layoutId → 从原位置弹性"弹"到中央 */}
          <motion.div
            layoutId={`island-${id}`}
            className={`relative bg-white rounded-2xl shadow-2xl ${className}`}
            transition={SPRING}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )
}
