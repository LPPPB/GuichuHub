import { useEffect, useRef, useState } from 'react'
import { X, Trash2, Tag, FileText, Edit3, Check, Flame, Music, Video } from 'lucide-react'
import { api } from '../utils/api'

export default function FavoritesPanel({ favorites, onClose, onRemove, formatNumber, onRefresh }) {
  const closeRef = useRef(null)
  useEffect(() => { closeRef.current?.focus() }, [])
  const [activeType, setActiveType] = useState('all')
  const [editingId, setEditingId] = useState(null)
  const [editTags, setEditTags] = useState('')
  const [editNotes, setEditNotes] = useState('')

  const filtered = activeType === 'all'
    ? favorites
    : favorites.filter(f => f.type === activeType)

  const typeLabels = {
    all: '全部',
    meme: '热梗',
    song: '热歌',
    video: '视频',
  }

  const typeIcons = {
    meme: Flame,
    song: Music,
    video: Video,
  }

  const typeColors = {
    meme: 'text-orange-500 bg-orange-50',
    song: 'text-purple-500 bg-purple-50',
    video: 'text-primary-600 bg-primary-50',
  }

  const startEdit = (fav) => {
    setEditingId(fav.id)
    setEditTags((fav.tags || []).join(', '))
    setEditNotes(fav.notes || '')
  }

  const saveEdit = async (id) => {
    await api.updateFavorite(id, {
      tags: editTags.split(',').map(t => t.trim()).filter(Boolean),
      notes: editNotes,
    })
    setEditingId(null)
    onRefresh()
  }

  const getItemTitle = (fav) => {
    return fav.keyword || fav.name || fav.title || '未命名'
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <div className="relative w-full max-w-md bg-white h-full shadow-2xl flex flex-col">
        <div className="p-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800">我的收藏夹</h2>
          <button
            ref={closeRef}
            aria-label="关闭收藏夹"
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-4 border-b border-slate-200 flex gap-2">
          {Object.entries(typeLabels).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setActiveType(key)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                activeType === key
                  ? 'bg-primary-500 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {label}
              <span className="ml-1 opacity-70">
                ({key === 'all' ? favorites.length : favorites.filter(f => f.type === key).length})
              </span>
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400">
              <FileText size={48} className="mb-3 opacity-50" />
              <p>还没有收藏内容</p>
              <p className="text-sm mt-1">看到好的灵感点收藏吧~</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {filtered.map((fav) => {
                const Icon = typeIcons[fav.type] || FileText
                const isEditing = editingId === fav.id
                return (
                  <div key={fav.id} className="p-4 hover:bg-slate-50 transition-colors">
                    <div className="flex items-start gap-3">
                      <div className={`p-2 rounded-lg ${typeColors[fav.type] || 'bg-slate-50 text-slate-500'}`}>
                        <Icon size={18} />
                      </div>

                      <div className="flex-1 min-w-0">
                        <h4 className="font-semibold text-slate-800 truncate">
                          {getItemTitle(fav)}
                        </h4>
                        <p className="text-xs text-slate-500 mt-0.5">
                          收藏于 {fav.saved_at}
                        </p>

                        {fav.tags && fav.tags.length > 0 && !isEditing && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {fav.tags.map((tag, i) => (
                              <span
                                key={i}
                                className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}

                        {fav.notes && !isEditing && (
                          <p className="text-sm text-slate-600 mt-2 bg-yellow-50 p-2 rounded-lg">
                            {fav.notes}
                          </p>
                        )}

                        {isEditing && (
                          <div className="mt-3 space-y-2">
                            <div>
                              <label className="text-xs text-slate-500 flex items-center gap-1 mb-1">
                                <Tag size={12} /> 标签（逗号分隔）
                              </label>
                              <input
                                type="text"
                                value={editTags}
                                onChange={(e) => setEditTags(e.target.value)}
                                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                                placeholder="例如：可以做鬼畜, 先观察"
                              />
                            </div>
                            <div>
                              <label className="text-xs text-slate-500 flex items-center gap-1 mb-1">
                                <FileText size={12} /> 创作笔记
                              </label>
                              <textarea
                                value={editNotes}
                                onChange={(e) => setEditNotes(e.target.value)}
                                rows={3}
                                className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 resize-none"
                                placeholder="记录一下灵感..."
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="flex flex-col gap-1">
                        {isEditing ? (
                          <button
                            onClick={() => saveEdit(fav.id)}
                            className="p-2 text-green-500 hover:bg-green-50 rounded-lg transition-colors"
                            title="保存"
                          >
                            <Check size={16} />
                          </button>
                        ) : (
                          <button
                            onClick={() => startEdit(fav)}
                            className="p-2 text-slate-400 hover:text-primary-500 hover:bg-primary-50 rounded-lg transition-colors"
                            title="编辑"
                          >
                            <Edit3 size={16} />
                          </button>
                        )}
                        <button
                          onClick={() => onRemove(fav.id)}
                          className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                          title="删除"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
