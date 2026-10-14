import { useState, useEffect, useRef } from 'react'
import { api } from '../utils/api'
import { X, RefreshCw, CheckCircle, QrCode, Info } from 'lucide-react'

/**
 * B站扫码登录弹窗（双模式）：
 *   mode='identity'（默认）→ 身份登录，全员开放。登录自己的B站账号，
 *     凭证只落服务器会话表（浏览器仅持 session token），不碰采集 Cookie。
 *     成功后回调 onLoginSuccess(user, is_admin)。
 *   mode='collect' → 采集账号登录，管理员专属。扫码凭证写入服务器
 *     bilibili_cookie.json（爬虫专用）。成功后回调 onLoginSuccess()。
 */
export default function BilibiliLogin({ onClose, onLoginSuccess, mode = 'identity' }) {
  const isCollect = mode === 'collect'
  const [qrcodeUrl, setQrcodeUrl] = useState('')
  const [qrcodeKey, setQrcodeKey] = useState('')
  const [status, setStatus] = useState('loading')
  const [message, setMessage] = useState('正在生成二维码...')
  const [userInfo, setUserInfo] = useState(null)
  const pollRef = useRef(null)
  const expiredRef = useRef(false)
  const closeRef = useRef(null)

  const generateQr = async () => {
    setStatus('loading')
    setMessage('正在生成二维码...')
    setQrcodeUrl('')
    setUserInfo(null)
    expiredRef.current = false

    // identity → /api/bili-auth/qrcode；collect → /api/bili-auth/collect-login（管理员专属）
    const res = isCollect ? await api.collectLogin() : await api.getQrcode()
    if (res.success) {
      setQrcodeUrl(res.qrcode_image || res.url)
      setQrcodeKey(res.qrcode_key)
      setStatus('waiting')
      setMessage('请使用B站APP扫描二维码')
      startPolling(res.qrcode_key)
    } else {
      setStatus('error')
      setMessage(res.message || '生成二维码失败')
    }
  }

  const startPolling = (key) => {
    if (pollRef.current) clearInterval(pollRef.current)

    pollRef.current = setInterval(async () => {
      if (expiredRef.current) return

      const res = isCollect ? await api.collectCheck(key) : await api.checkLogin(key)
      if (res.success) {
        clearInterval(pollRef.current)
        pollRef.current = null
        setStatus('success')
        setMessage(isCollect ? '采集账号登录成功！' : '登录成功！')
        if (res.user) setUserInfo(res.user)
        setTimeout(() => {
          onLoginSuccess(res.user || null, res.is_admin)
          onClose()
        }, 1000)
      } else if (res.status === 'scanned') {
        setStatus('scanned')
        setMessage('已扫码，请在手机上确认登录')
      } else if (res.status === 'expired') {
        clearInterval(pollRef.current)
        pollRef.current = null
        setStatus('expired')
        setMessage('二维码已过期，请刷新')
        expiredRef.current = true
      }
    }, 2000)
  }

  useEffect(() => {
    closeRef.current?.focus()
    generateQr()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl p-8 max-w-sm w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-bold text-slate-800">
            {isCollect ? '采集账号登录' : 'B站账号登录'}
          </h2>
          <button ref={closeRef} aria-label="关闭登录" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100">
            <X size={20} />
          </button>
        </div>

        {status === 'success' ? (
          <div className="flex flex-col items-center py-8">
            <CheckCircle className="text-green-500 mb-4" size={56} />
            <p className="text-lg font-medium text-slate-800">
              {isCollect ? '采集账号已登录' : (userInfo?.name ? `${userInfo.name}，登录成功` : '登录成功')}
            </p>
            <p className="text-sm text-slate-500 mt-1">
              {isCollect ? '服务器爬虫将使用此账号采集数据' : '正在同步你的身份...'}
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center">
            <div className="relative w-64 h-64 bg-slate-50 rounded-xl border-2 border-slate-200 flex items-center justify-center overflow-hidden">
              {qrcodeUrl ? (
                <img
                  src={qrcodeUrl}
                  alt="B站登录二维码"
                  className={`w-full h-full ${status === 'expired' ? 'opacity-30' : ''}`}
                />
              ) : (
                <div className="flex flex-col items-center text-slate-400">
                  <QrCode size={48} className="mb-2" />
                  <span className="text-sm">生成中...</span>
                </div>
              )}

              {status === 'scanned' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/90">
                  <CheckCircle className="text-green-500 mb-2" size={40} />
                  <span className="text-sm text-slate-600">已扫码</span>
                  <span className="text-xs text-slate-500 mt-1">请在手机上确认</span>
                </div>
              )}

              {status === 'expired' && (
                <button
                  onClick={generateQr}
                  className="absolute inset-0 flex flex-col items-center justify-center bg-white/90 text-primary-500 hover:text-primary-600"
                >
                  <RefreshCw size={32} className="mb-2" />
                  <span className="text-sm font-medium">点击刷新二维码</span>
                </button>
              )}
            </div>

            <p className="text-sm text-slate-500 mt-4 text-center">{message}</p>
            <p className="text-xs text-slate-400 mt-2">打开B站APP → 我的 → 扫一扫</p>
            <p className="flex items-center gap-1.5 text-[11px] text-slate-400 mt-3 px-3 py-2 bg-slate-50 rounded-lg text-center leading-relaxed">
              <Info size={13} className="shrink-0" />
              {isCollect
                ? '扫码凭证将写入服务器采集 Cookie 文件（管理员操作）'
                : '登录仅用于身份识别；账号凭证只保存在服务器，不会写入浏览器'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
