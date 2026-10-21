// Downloadable Tap&Go account statement (A4 PDF), built in the browser from the
// wallet history the dashboard already loaded. Loaded on demand (dynamic import)
// so the PDF library never slows down the first page load.
import { jsPDF } from 'jspdf'
import { autoTable } from 'jspdf-autotable'
import figtreeRegularUrl from '../assets/fonts/statement/Figtree-Regular.ttf?url'
import figtreeSemiBoldUrl from '../assets/fonts/statement/Figtree-SemiBold.ttf?url'
import figtreeBoldUrl from '../assets/fonts/statement/Figtree-Bold.ttf?url'
import bricolageUrl from '../assets/fonts/statement/BricolageGrotesque-ExtraBold.ttf?url'

const INK = [30, 27, 22]
const INK_SOFT = [107, 100, 88]
const YELLOW = [253, 211, 77]
const YELLOW_DEEP = [245, 190, 36]
const BUTTER = [255, 243, 196]
const ON_YELLOW_SOFT = [94, 74, 16]
const HAIRLINE = [234, 228, 218]
const CANVAS = [246, 243, 238]
const GREEN = [23, 122, 71]
const RED = [200, 55, 45]

const money = (value) =>
  `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const day = (d) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
const time = (d) => d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })

async function toBase64(url) {
  const buffer = await (await fetch(url)).arrayBuffer()
  let binary = ''
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

async function addFonts(doc) {
  const fonts = [
    ['Figtree-Regular.ttf', figtreeRegularUrl, 'Figtree', 'normal'],
    ['Figtree-SemiBold.ttf', figtreeSemiBoldUrl, 'FigtreeSemi', 'normal'],
    ['Figtree-Bold.ttf', figtreeBoldUrl, 'Figtree', 'bold'],
    ['BricolageGrotesque-ExtraBold.ttf', bricolageUrl, 'Bricolage', 'normal'],
  ]
  const data = await Promise.all(fonts.map(([, url]) => toBase64(url)))
  fonts.forEach(([file, , family, style], i) => {
    doc.addFileToVFS(file, data[i])
    doc.addFont(file, family, style)
  })
}

const isDone = (status) => ['completed', 'success'].includes(String(status || '').toLowerCase())

const methodLabel = (raw) => {
  const m = String(raw || '').trim()
  if (!m) return '—'
  if (m.length <= 3) return m.toUpperCase()
  return m.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
}

/** One statement row from a backend wallet transaction (or a dashboard item that wraps one in `raw`). */
function toRow(item, role) {
  const t = item?.raw || item || {}
  const when = t.created_at ? new Date(t.created_at) : t.timestamp ? new Date(t.timestamp) : null
  const credit = Boolean(t.is_credit)
  const description = t.description || ''
  const other = role === 'driver' ? t.passenger : t.driver
  const extra = [description, other && !description.includes(other) ? `${credit ? 'From' : 'To'} ${other}` : '']
    .filter(Boolean)
    .join(' · ')
  return {
    when: when && !Number.isNaN(when.getTime()) ? when : null,
    title: t.type || (credit ? 'Wallet credit' : 'Payment'),
    extra,
    reference: t.reference || (t.id != null ? String(t.id) : '—'),
    method: methodLabel(t.payment_method),
    amount: Math.abs(Number(t.amount || 0)),
    credit,
    status: t.status || 'Completed',
    done: isDone(t.status || 'Completed'),
    balance: t.balance_after,
  }
}

function wordmark(doc, x, y, size) {
  doc.setFont('Bricolage', 'normal')
  doc.setFontSize(size)
  doc.setTextColor(...INK)
  doc.text('Tap', x, y)
  const w1 = doc.getTextWidth('Tap')
  doc.setTextColor(...YELLOW_DEEP)
  doc.text('&', x + w1, y)
  doc.setTextColor(...INK)
  doc.text('Go', x + w1 + doc.getTextWidth('&'), y)
}

/**
 * Builds and downloads the statement.
 * @param {{ holderName: string, email?: string, role: 'passenger'|'driver', balance: number, transactions: object[] }} input
 */
export async function downloadStatementPdf({ holderName, email, role, balance, transactions }) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  await addFonts(doc)
  const W = doc.internal.pageSize.getWidth()
  const H = doc.internal.pageSize.getHeight()
  const M = 36
  const now = new Date()

  const rows = (transactions || [])
    .map((t) => toRow(t, role))
    .sort((a, b) => (b.when?.getTime() || 0) - (a.when?.getTime() || 0))
  const moneyIn = rows.filter((r) => r.done && r.credit).reduce((s, r) => s + r.amount, 0)
  const moneyOut = rows.filter((r) => r.done && !r.credit).reduce((s, r) => s + r.amount, 0)
  const dates = rows.map((r) => r.when).filter(Boolean).sort((a, b) => a - b)
  const period = dates.length ? `${day(dates[0])} – ${day(dates[dates.length - 1])}` : '—'

  // ── Masthead ──────────────────────────────────────────────
  let y = 74
  wordmark(doc, M, y, 30)
  doc.setFont('Figtree', 'bold')
  doc.setFontSize(6.8)
  doc.setTextColor(...INK_SOFT)
  doc.setCharSpace(1.6)
  doc.text('SMART PAYMENTS. EVERY RIDE.', M, y + 14)
  doc.setCharSpace(0)
  doc.setFont('Bricolage', 'normal')
  doc.setFontSize(17)
  doc.setTextColor(...INK)
  doc.text('Account statement', W - M, y - 4, { align: 'right' })
  doc.setFont('Figtree', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(...INK_SOFT)
  doc.text(`Generated ${day(now)}, ${time(now)}`, W - M, y + 10, { align: 'right' })
  y += 26
  doc.setFillColor(...INK)
  doc.rect(M, y, W - 2 * M, 2, 'F')

  // ── Account details ───────────────────────────────────────
  y += 26
  const details = [
    ['ACCOUNT HOLDER', holderName || '—', 0],
    ['EMAIL', email || '—', 0.23],
    ['ACCOUNT TYPE', role === 'driver' ? 'Driver' : 'Passenger', 0.52],
    ['STATEMENT PERIOD', period, 0.66],
  ]
  details.forEach(([label, value, at], i) => {
    const x = M + (W - 2 * M) * at
    const nextAt = i < details.length - 1 ? details[i + 1][2] : 1
    const maxWidth = (W - 2 * M) * (nextAt - at) - 8
    doc.setFont('Figtree', 'bold')
    doc.setFontSize(7)
    doc.setTextColor(...INK_SOFT)
    doc.setCharSpace(1.1)
    doc.text(label, x, y)
    doc.setCharSpace(0)
    doc.setFont('FigtreeSemi', 'normal')
    doc.setFontSize(10.5)
    doc.setTextColor(...INK)
    doc.text(String(value), x, y + 14, { maxWidth })
  })

  // ── Summary boxes ─────────────────────────────────────────
  y += 34
  const gap = 8
  const boxW = (W - 2 * M - 3 * gap) / 4
  const boxes = [
    ['CURRENT BALANCE', money(balance), YELLOW, INK],
    ['MONEY IN', money(moneyIn), null, GREEN],
    ['MONEY OUT', money(moneyOut), null, INK],
    ['TRANSACTIONS', String(rows.length), null, INK],
  ]
  boxes.forEach(([label, value, fill, valueColor], i) => {
    const x = M + i * (boxW + gap)
    if (fill) {
      doc.setFillColor(...fill)
      doc.roundedRect(x, y, boxW, 52, 9, 9, 'F')
    } else {
      doc.setDrawColor(...HAIRLINE)
      doc.setLineWidth(0.8)
      doc.roundedRect(x, y, boxW, 52, 9, 9, 'S')
    }
    doc.setFont('Figtree', 'bold')
    doc.setFontSize(6.8)
    doc.setTextColor(...(fill ? ON_YELLOW_SOFT : INK_SOFT))
    doc.setCharSpace(1)
    doc.text(label, x + 12, y + 17)
    doc.setCharSpace(0)
    doc.setFont('Bricolage', 'normal')
    doc.setFontSize(14.5)
    doc.setTextColor(...valueColor)
    doc.text(value, x + 12, y + 38)
  })

  // ── Note ──────────────────────────────────────────────────
  y += 60
  doc.setFillColor(...BUTTER)
  doc.roundedRect(M, y, W - 2 * M, 30, 8, 8, 'F')
  doc.setFont('Figtree', 'normal')
  doc.setFontSize(7.4)
  doc.setTextColor(...ON_YELLOW_SOFT)
  doc.text(
    'Amounts are in Indian Rupees (₹). Money in and money out count completed transactions only. Balance is your wallet balance right after each transaction, as recorded by Tap&Go.',
    M + 12,
    y + 12,
    { maxWidth: W - 2 * M - 24 },
  )

  // ── Transactions ──────────────────────────────────────────
  y += 52
  doc.setFont('Bricolage', 'normal')
  doc.setFontSize(13)
  doc.setTextColor(...INK)
  doc.text('Transactions', M, y)
  y += 8

  if (!rows.length) {
    doc.setFillColor(...BUTTER)
    doc.roundedRect(M, y, W - 2 * M, 40, 9, 9, 'F')
    doc.setFont('Figtree', 'normal')
    doc.setFontSize(9.5)
    doc.setTextColor(...ON_YELLOW_SOFT)
    doc.text('No transactions yet.', M + 16, y + 24)
  } else {
    autoTable(doc, {
      startY: y,
      margin: { left: M, right: M, top: 64, bottom: 52 },
      head: [['DATE', 'DETAILS', 'REFERENCE', 'METHOD', 'AMOUNT', 'BALANCE']],
      body: rows.map((r) => [
        r.when ? `${day(r.when)}\n${time(r.when)}` : '—',
        [r.title, r.extra, r.done ? '' : r.status.toUpperCase()].filter(Boolean).join('\n'),
        r.reference,
        r.method,
        `${r.credit ? '+' : '−'}${money(r.amount)}`,
        r.balance == null ? '—' : money(r.balance),
      ]),
      theme: 'plain',
      rowPageBreak: 'avoid',
      styles: { font: 'Figtree', fontStyle: 'normal', fontSize: 7.5, textColor: INK_SOFT, cellPadding: 6, valign: 'top', overflow: 'linebreak' },
      headStyles: { fillColor: YELLOW, textColor: INK, font: 'Figtree', fontStyle: 'bold', fontSize: 6.8, valign: 'middle' },
      bodyStyles: { lineColor: HAIRLINE, lineWidth: { bottom: 0.6 } },
      alternateRowStyles: { fillColor: CANVAS },
      columnStyles: {
        0: { cellWidth: 62 },
        1: { cellWidth: 'auto' },
        2: { cellWidth: 80 },
        3: { cellWidth: 58 },
        4: { cellWidth: 68, halign: 'right' },
        5: { cellWidth: 62, halign: 'right' },
      },
      didParseCell: (data) => {
        if (data.section === 'head') {
          if (data.column.index >= 4) data.cell.styles.halign = 'right'
          return
        }
        if (data.column.index === 4) {
          const r = rows[data.row.index]
          data.cell.styles.fontStyle = 'bold'
          data.cell.styles.fontSize = 8.6
          data.cell.styles.textColor = !r.done ? INK_SOFT : r.credit ? GREEN : INK
        }
      },
      // Date and details: first line darker and bolder, the rest soft; a failed status in red.
      willDrawCell: (data) => {
        if (data.section !== 'body' || data.column.index > 1) return
        data.cell.__lines = data.cell.text
        data.cell.text = []
      },
      didDrawCell: (data) => {
        const lines = data.cell.__lines
        if (!lines) return
        const r = rows[data.row.index]
        const x = data.cell.x + data.cell.padding('left')
        let ly = data.cell.y + data.cell.padding('top')
        const lineH = 7.5 * 1.15
        lines.forEach((line, i) => {
          const isStatus = data.column.index === 1 && !r.done && line === r.status.toUpperCase()
          if (i === 0) {
            doc.setFont('FigtreeSemi', 'normal')
            doc.setTextColor(...INK)
          } else if (isStatus) {
            doc.setFont('Figtree', 'bold')
            doc.setTextColor(...RED)
          } else {
            doc.setFont('Figtree', 'normal')
            doc.setTextColor(...INK_SOFT)
          }
          doc.setFontSize(i === 0 ? 8.2 : 7.4)
          doc.text(line, x, ly, { baseline: 'top' })
          ly += lineH
        })
      },
    })
  }

  // ── Every page: yellow strip, running header (page 2+), footer ──
  const pages = doc.internal.getNumberOfPages()
  for (let p = 1; p <= pages; p += 1) {
    doc.setPage(p)
    doc.setFillColor(...YELLOW)
    doc.rect(0, 0, W, 7, 'F')
    if (p > 1) {
      wordmark(doc, M, 46, 13)
      doc.setFont('Figtree', 'normal')
      doc.setFontSize(8)
      doc.setTextColor(...INK_SOFT)
      doc.text(`Account statement · ${holderName || ''}`, W - M, 46, { align: 'right' })
    }
    doc.setDrawColor(...HAIRLINE)
    doc.setLineWidth(0.8)
    doc.line(M, H - 40, W - M, H - 40)
    doc.setFont('Figtree', 'normal')
    doc.setFontSize(7.4)
    doc.setTextColor(...INK_SOFT)
    doc.text('Tap&Go · tapandgosupport@gmail.com · thetapandgo.in', M, H - 26)
    doc.setFont('FigtreeSemi', 'normal')
    doc.text(`Page ${p} of ${pages}`, W - M, H - 26, { align: 'right' })
  }

  doc.setProperties({ title: 'Tap&Go account statement', author: 'Tap&Go' })
  const stamp = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-')
  doc.save(`TapGo-statement-${stamp}.pdf`)
}
