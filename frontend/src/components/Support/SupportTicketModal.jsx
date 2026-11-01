import { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'
function getToken() { try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' } }

const FIELD = { display: 'block', width: '100%', marginTop: 4, padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13, boxSizing: 'border-box' }
const LABEL = { fontSize: 12, fontWeight: 700, color: '#3a352e' }

/* Same form and look as the passenger "Contact Support" modal; posts to the existing POST /api/support/. */
export default function SupportTicketModal({ user, onClose, onSubmitted }) {
  const [form, setFormState] = useState({ name: user?.name || '', email: user?.email || '', phone: user?.phone || '', category: 'technical', priority: 'medium', subject: '', message: '' })
  const set = (k, v) => setFormState((f) => ({ ...f, [k]: v }))
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.subject.trim() || !form.message.trim()) { setError('Subject and message are required.'); return }
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API_BASE}/api/support/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify(form),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setSuccess(`Ticket #${data.ticket.id} submitted! We will reply to your email shortly.`)
        onSubmitted?.(data.ticket)
      } else {
        setError(data.detail || 'Failed to submit ticket.')
      }
    } catch { setError('Service unavailable. Please try again.') } finally { setLoading(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(30,27,22,0.5)', backdropFilter: 'blur(6px)', padding: 16 }}>
      <div style={{ width: '100%', maxWidth: 440, background: '#fff', borderRadius: 20, boxShadow: '0 24px 60px rgba(30,27,22,0.25)', overflow: 'hidden' }}>
        <div style={{ background: '#fdd34d', padding: '18px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div><div style={{ color: '#1e1b16', fontWeight: 800, fontSize: 16 }}>🎫 Contact Support</div><div style={{ color: '#5e4a10', fontSize: 12 }}>We reply within 24 hours</div></div>
          <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', color: '#1e1b16', fontSize: 22, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ padding: '20px 20px 24px', maxHeight: '70vh', overflowY: 'auto' }}>
          {success ? (
            <div style={{ textAlign: 'center', padding: '24px 0' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
              <p style={{ fontWeight: 700, color: '#177a47', marginBottom: 8 }}>{success}</p>
              <button onClick={onClose} style={{ marginTop: 16, padding: '10px 24px', background: '#141210', color: '#fdd34d', border: 'none', borderRadius: 10, fontWeight: 700, cursor: 'pointer' }}>Close</button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {error && <div style={{ padding: '10px 12px', background: '#fdf2f0', border: '1px solid #f1a79d', borderRadius: 10, color: '#c8372d', fontSize: 13 }}>{error}</div>}
              {[['Subject', 'subject', 'text', 'Brief summary of your issue'], ['Your Name', 'name', 'text', ''], ['Email', 'email', 'email', ''], ['Phone', 'phone', 'tel', '']].map(([lbl, key, type, ph]) => (
                <label key={key} style={LABEL}>{lbl}<input type={type} value={form[key]} onChange={(e) => set(key, e.target.value)} placeholder={ph} required style={FIELD} /></label>
              ))}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={LABEL}>Category
                  <select value={form.category} onChange={(e) => set('category', e.target.value)} style={FIELD}>
                    <option value="billing">Billing</option><option value="technical">Technical</option><option value="nfc_card">NFC Card</option><option value="account">Account</option><option value="other">Other</option>
                  </select></label>
                <label style={LABEL}>Priority
                  <select value={form.priority} onChange={(e) => set('priority', e.target.value)} style={FIELD}>
                    <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option>
                  </select></label>
              </div>
              <label style={LABEL}>Message
                <textarea value={form.message} onChange={(e) => set('message', e.target.value)} required rows={4} placeholder="Describe your issue in detail…" style={{ ...FIELD, resize: 'vertical' }} /></label>
              <button type="submit" disabled={loading} style={{ padding: '12px', background: '#141210', color: '#fdd34d', border: 'none', borderRadius: 10, fontWeight: 700, fontSize: 14, cursor: 'pointer', opacity: loading ? 0.6 : 1 }}>
                {loading ? 'Submitting…' : 'Submit Support Ticket'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
