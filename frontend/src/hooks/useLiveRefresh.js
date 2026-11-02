import { useEffect, useRef } from 'react'

// Runs `callback` every `intervalMs` while the browser tab is visible, and again straight away when the user comes
// back to the tab. Used so that what an administrator does (approve a withdrawal, unlock an edit, reply to a ticket,
// freeze a wallet) shows up on the user's screen without a reload.
export function useLiveRefresh(callback, enabled = true, intervalMs = 20000) {
  const latest = useRef(callback)
  useEffect(() => { latest.current = callback })
  useEffect(() => {
    if (!enabled) return undefined
    const tick = () => { if (document.visibilityState === 'visible') latest.current?.() }
    const timer = setInterval(tick, intervalMs)
    document.addEventListener('visibilitychange', tick)
    window.addEventListener('focus', tick)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
      window.removeEventListener('focus', tick)
    }
  }, [enabled, intervalMs])
}
