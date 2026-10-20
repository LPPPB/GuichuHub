import { X } from 'lucide-react'

// Safe fallback only; this component never requests or polls a QR code.
export default function BilibiliLogin({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="retired-login-title"
        className="bg-white rounded-2xl p-8 max-w-sm w-full mx-4"
        onClick={event => event.stopPropagation()}>
        <div className="flex items-center justify-between gap-4">
          <h2 id="retired-login-title" className="text-xl font-bold text-slate-800">B站登录已下线</h2>
          <button type="button" aria-label="关闭登录" onClick={onClose}><X size={20} /></button>
        </div>
        <p className="mt-4 text-sm text-slate-500">后续将接入官方授权，当前无需扫描二维码。</p>
      </div>
    </div>
  )
}
