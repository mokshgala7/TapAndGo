import { useCallback, useEffect, useState } from 'react'
import SupportTicketModal from './SupportTicketModal.jsx'
import { useLiveRefresh } from '../../hooks/useLiveRefresh.js'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'
function getToken() { try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' } }

const STATUS_COLORS = { open: '#c8372d', in_progress: '#9a5b00', resolved: '#177a47', closed: '#6b6458' }
const STATUS_LABELS = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' }
const when = (value) => (value ? new Date(value).toLocaleString() : '')

/* The signed-in user's support tickets (GET /api/support/my): subject, status, admin reply and date.
   `compose` adds a "New ticket" button that opens the same form the passenger dashboard uses.
   Change `refreshKey` to reload the list (e.g. after another form submitted a ticket). */
export default function MyTickets({ user, compose = false, refreshKey = 0 }) {
  const [tickets, setTickets] = useState(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(null)
  const [showForm, setShowForm] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/support/my`, { headers: { Authorization: `Bearer ${getToken()}` } })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Could not load your tickets.')
      setTickets(data.tickets || []); setError('')
    } catch (err) { setError(err.message || 'Could not load your tickets.') }
  }, [])
  useEffect(() => { load() }, [load, refreshKey])
  useLiveRefresh(load)   // an administrator's reply appears without a reload

  return (
    <section style={{ margin: '8px 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>My Tickets</h2>
        {compose && (
          <button onClick={() => setShowForm(true)} style={{ padding: '9px 14px', background: '#141210', color: '#fdd34d', border: 'none', borderRadius: 10, fontWeight: 700, fontSize: 13, cursor: 'pointer' }}>
            + New ticket
          </button>
        )}
      </div>
      {error && <p style={{ color: '#c8372d', fontSize: 13 }}>{error}</p>}
      {tickets === null && !error && <p style={{ color: '#6b6458', fontSize: 13 }}>Loading your tickets…</p>}
      {tickets && !tickets.length && <p style={{ color: '#6b6458', fontSize: 13 }}>You have not raised any support tickets yet.</p>}
      <div style={{ display: 'grid', gap: 10 }}>
        {(tickets || []).map((t) => (
          <article key={t.id} style={{ background: 'var(--card, #fff)', border: '1px solid var(--line, #eae4da)', borderRadius: 14, padding: '14px 16px' }}>
            <button onClick={() => setOpen(open === t.id ? null : t.id)} aria-expanded={open === t.id}
              style={{ all: 'unset', cursor: 'pointer', display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: 10, boxSizing: 'border-box' }}>
              <span style={{ minWidth: 0 }}>
                <strong style={{ display: 'block', fontSize: 14, overflowWrap: 'anywhere' }}>#{t.id} · {t.subject}</strong>
                <small style={{ color: '#6b6458' }}>{when(t.created_at)}</small>
              </span>
              <span style={{ flexShrink: 0, padding: '3px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700, background: `${STATUS_COLORS[t.status] || '#a39b8e'}22`, color: STATUS_COLORS[t.status] || '#a39b8e' }}>
                {STATUS_LABELS[t.status] || t.status}
              </span>
            </button>
            {open === t.id && (
              <div style={{ marginTop: 12, fontSize: 13, lineHeight: 1.6 }}>
                <p style={{ margin: '0 0 10px', whiteSpace: 'pre-wrap' }}>{t.message}</p>
                {t.admin_reply ? (
                  <div style={{ background: '#eef8f2', borderLeft: '3px solid #2e9560', borderRadius: '0 10px 10px 0', padding: '10px 14px', color: '#1e1b16' }}>
                    <small style={{ display: 'block', fontWeight: 700, color: '#177a47', textTransform: 'uppercase' }}>Reply from Tap&amp;Go{t.replied_at ? ` · ${when(t.replied_at)}` : ''}</small>
                    <span style={{ whiteSpace: 'pre-wrap' }}>{t.admin_reply}</span>
                  </div>
                ) : <small style={{ color: '#6b6458' }}>No reply yet. We usually respond within 24 hours.</small>}
              </div>
            )}
          </article>
        ))}
      </div>
      {showForm && <SupportTicketModal user={user} onClose={() => setShowForm(false)} onSubmitted={load} />}
    </section>
  )
}
