import { useState, useCallback, useRef, useEffect } from 'react'

let globalPlayerState = {
  isOpen: false,
  isPlaying: false,
  currentBvid: null,
  currentTitle: '',
  currentCover: '',
  currentType: 'video',
  currentTime: 0,
  duration: 0,
}

const listeners = new Set()

function notify() {
  listeners.forEach((fn) => fn(globalPlayerState))
}

export function setPlayerState(partial) {
  globalPlayerState = { ...globalPlayerState, ...partial }
  notify()
}

export function togglePlay() {
  globalPlayerState = { ...globalPlayerState, isPlaying: !globalPlayerState.isPlaying }
  notify()
}

export function openPlayer({ bvid, title, cover, type = 'video' }) {
  if (globalPlayerState.isOpen && globalPlayerState.currentBvid === bvid) {
    return
  }
  globalPlayerState = {
    isOpen: true,
    isPlaying: true,
    currentBvid: bvid,
    currentTitle: title,
    currentCover: cover,
    currentType: type,
    currentTime: 0,
    duration: 0,
  }
  notify()
}

export function toggleOrOpen({ bvid, title, cover, type = 'video' }) {
  if (globalPlayerState.isOpen && globalPlayerState.currentBvid === bvid) {
    closePlayer()
  } else {
    openPlayer({ bvid, title, cover, type })
  }
}

export function closePlayer() {
  globalPlayerState = {
    ...globalPlayerState,
    isOpen: false,
    isPlaying: false,
  }
  notify()
}

export function usePlayer() {
  const [state, setState] = useState(globalPlayerState)

  useEffect(() => {
    const listener = (newState) => setState(newState)
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, [])

  const open = useCallback((opts) => openPlayer(opts), [])
  const close = useCallback(() => closePlayer(), [])
  const toggle = useCallback(() => togglePlay(), [])
  const toggleOpen = useCallback((opts) => toggleOrOpen(opts), [])

  return {
    ...state,
    openPlayer: open,
    closePlayer: close,
    togglePlay: toggle,
    toggleOrOpen: toggleOpen,
  }
}
