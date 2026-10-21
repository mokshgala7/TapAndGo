import { useEffect, useRef } from 'react'
import './ScrollCar.css'

/*
 * A Tap&Go taxi that drives along a road on the left edge of the screen as
 * you scroll: its position follows how far down the page (or the main
 * scrolling pane) you are, and it turns to face the way you are scrolling. Purely decorative: it ignores the
 * pointer and is hidden from screen readers.
 */
function ScrollCar() {
  const carRef = useRef(null)

  useEffect(() => {
    const car = carRef.current
    if (!car) return undefined
    const page = document.scrollingElement || document.documentElement
    // Follows whichever large area is scrolling: the page itself, or a main
    // pane that scrolls on its own (the sign-up form, dashboards).
    let source = page
    let lastY = page.scrollTop
    let frame = 0
    let idleTimer = 0

    const update = (moved) => {
      frame = 0
      const y = source.scrollTop
      const max = Math.max(1, source.scrollHeight - source.clientHeight)
      const progress = Math.min(1, Math.max(0, y / max))
      if (y > lastY + 0.5) car.dataset.dir = 'down'
      else if (y < lastY - 0.5) car.dataset.dir = 'up'
      lastY = y
      car.style.setProperty('--tg-car-progress', progress.toFixed(4))
      if (moved) {
        car.classList.add('is-driving')
        window.clearTimeout(idleTimer)
        // keep the little wobble going while the taxi glides to its spot
        idleTimer = window.setTimeout(() => car.classList.remove('is-driving'), 1200)
      }
    }

    const onScroll = (event) => {
      const target = event.target === document || event.target === window ? page : event.target
      if (!(target instanceof Element)) return
      const isPage = target === page || target === document.body
      // ignore small scrolling lists and carousels
      if (!isPage && target.clientHeight < window.innerHeight * 0.5) return
      const next = isPage ? page : target
      if (next !== source) {
        source = next
        lastY = source.scrollTop
      }
      if (!frame) frame = window.requestAnimationFrame(() => update(true))
    }
    const onLayout = () => {
      if (!source.isConnected) {
        source = page
        lastY = page.scrollTop
      }
      if (!frame) frame = window.requestAnimationFrame(() => update(false))
    }
    const onRoute = () => {
      source = page
      lastY = page.scrollTop
      onLayout()
    }

    update(false)
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    window.addEventListener('resize', onLayout)
    window.addEventListener('hashchange', onRoute)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(onLayout)
    observer?.observe(document.body)

    return () => {
      document.removeEventListener('scroll', onScroll, { capture: true })
      window.removeEventListener('resize', onLayout)
      window.removeEventListener('hashchange', onRoute)
      observer?.disconnect()
      window.cancelAnimationFrame(frame)
      window.clearTimeout(idleTimer)
    }
  }, [])

  return (
    <div className="tg-scroll-road" aria-hidden="true">
      <div ref={carRef} className="tg-scroll-car" data-dir="down">
        <div className="tg-scroll-car-body">
          <svg viewBox="0 0 28 50" width="28" height="50">
            {/* wheels */}
            <rect x="1" y="9" width="4" height="9" rx="2" fill="#1e1b16" />
            <rect x="23" y="9" width="4" height="9" rx="2" fill="#1e1b16" />
            <rect x="1" y="33" width="4" height="9" rx="2" fill="#1e1b16" />
            <rect x="23" y="33" width="4" height="9" rx="2" fill="#1e1b16" />
            {/* body */}
            <rect x="3.5" y="2.5" width="21" height="45" rx="8" fill="#fdd34d" stroke="#1e1b16" strokeWidth="2.2" />
            {/* windscreen, roof sign, rear window */}
            <path d="M7.5 13.5 Q14 10 20.5 13.5 L19.5 18 Q14 16.4 8.5 18 Z" fill="#1e1b16" />
            <rect x="9" y="22" width="10" height="6" rx="1.6" fill="#1e1b16" />
            <rect x="10.6" y="23.6" width="6.8" height="2.8" rx="0.8" fill="#fdd34d" />
            <path d="M8.5 36 Q14 37.8 19.5 36 L20.3 39.8 Q14 42.4 7.7 39.8 Z" fill="#1e1b16" opacity="0.85" />
            {/* headlights and tail lights */}
            <circle cx="8.6" cy="5.8" r="1.7" fill="#ffffff" />
            <circle cx="19.4" cy="5.8" r="1.7" fill="#ffffff" />
            <rect x="6.6" y="44" width="3.6" height="1.8" rx="0.9" fill="#c8372d" />
            <rect x="17.8" y="44" width="3.6" height="1.8" rx="0.9" fill="#c8372d" />
          </svg>
        </div>
      </div>
    </div>
  )
}

export default ScrollCar
