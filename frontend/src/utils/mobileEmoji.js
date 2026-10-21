// Emoji -> icon helper (all screen sizes).
//
// Colour emoji clash with the Tap&Go look, so this swaps them in place: an element that
// holds a single emoji becomes the matching Material icon (monochrome, takes the text
// colour); an emoji inside a sentence becomes a plain ✓ / ✕ / ! or is dropped. Text is
// edited in place (no nodes are added or removed) so React's own updates keep working, and
// the observer re-applies the swap whenever React rewrites a string.
const PHONE = 'all'
const EMOJI = /(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}️)(?:‍\p{Extended_Pictographic}️?)*/gu

const ICONS = {
  '💳': 'credit_card', '🎫': 'confirmation_number', '🛡': 'shield', '🏦': 'account_balance',
  '💸': 'payments', '📍': 'location_on', '📞': 'call', '📄': 'description', '📎': 'attach_file',
  '🎯': 'target', '⚡': 'bolt', '🎓': 'school', '💡': 'lightbulb', '🔄': 'sync', '🔒': 'lock',
  '🔓': 'lock_open', '🚖': 'local_taxi', '✅': 'check_circle', '❌': 'cancel', '⚠': 'warning',
  '⏳': 'hourglass_top', '📱': 'smartphone', '🔷': 'diamond', '⏰': 'alarm', '📦': 'inventory_2', '👋': 'waving_hand',
}
const INLINE = { '✅': '✓', '❌': '✕', '⚠': '!' }
// Keycap emoji (1️⃣) become a plain "1." in the text colour.
const KEYCAP = /([0-9#*])\uFE0F?\u20E3/g
const base = (emoji) => emoji.replace(/️/g, '')

const converted = new Map() // text node -> original text

// An icon sits on white, yellow or black: black ink on the first two, white ink on black.
function tone(el) {
  for (let e = el; e; e = e.parentElement) {
    const m = getComputedStyle(e).backgroundColor.match(/[\d.]+/g)
    if (m && (m.length < 4 || Number(m[3]) > 0.5)) {
      return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255 < 0.4 ? 'dark' : 'light'
    }
  }
  return 'light'
}

function convert(node) {
  const original = node.nodeValue
  if (!original) return
  const parent = node.parentElement
  if (!parent || ['SCRIPT', 'STYLE', 'TEXTAREA'].includes(parent.tagName)) return
  const text = original.replace(KEYCAP, '$1.')
  if (!EMOJI.test(text)) {
    EMOJI.lastIndex = 0
    if (text !== original) {
      converted.set(node, original)
      node.nodeValue = text
    }
    return
  }
  EMOJI.lastIndex = 0
  const only = text.trim().match(EMOJI)
  EMOJI.lastIndex = 0
  const icon = only && only.length === 1 && only[0] === text.trim() ? ICONS[base(only[0])] : null
  converted.set(node, original)
  if (icon && parent.childNodes.length === 1) {
    node.nodeValue = icon
    parent.dataset.tgIcon = tone(parent)
    return
  }
  node.nodeValue = text.replace(EMOJI, (m) => INLINE[base(m)] ?? '')
}

function sweep(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n)
  nodes.forEach(convert)
}

function restore() {
  converted.forEach((original, node) => {
    node.nodeValue = original
    node.parentElement?.removeAttribute('data-tg-icon')
  })
  converted.clear()
}

export function startMobileEmoji() {
  if (typeof window === 'undefined' || !window.matchMedia || !window.Intl) return
  try { new RegExp('\\p{Emoji_Presentation}', 'u') } catch { return }
  const query = window.matchMedia(PHONE)
  let observer = null
  const run = (records) => {
    if (!records) return sweep(document.body)
    observer.disconnect()
    records.forEach((r) => {
      if (r.type === 'characterData') convert(r.target)
      else r.addedNodes.forEach((n) => (n.nodeType === 3 ? convert(n) : n.nodeType === 1 && sweep(n)))
    })
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
  }
  const sync = () => {
    if (query.matches && !observer) {
      observer = new MutationObserver(run)
      sweep(document.body)
      observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    } else if (!query.matches && observer) {
      observer.disconnect()
      observer = null
      restore()
    }
  }
  query.addEventListener?.('change', sync)
  sync()
}
