import React, { useState, useEffect } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

// Session token for authenticated API calls (stored by AuthContext at login).
const authHeaders = (extra = {}) => {
  let token = ''
  try { token = sessionStorage.getItem('tapgo_token') || '' } catch { /* storage unavailable */ }
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

export function NFCOrderHistoryModal({ user, onClose, onOrderAgain }) {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user?.id) return
    setLoading(true)
    fetch(`${API_BASE}/api/card-order/user/${user.id}`, { headers: authHeaders() })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setOrders(data.orders || [])
        } else {
          setError(data.message || 'Could not load order history.')
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [user?.id])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 600, width: '100%', maxHeight: '85vh', overflowY: 'auto' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 20, fontWeight: 900 }}>NFC Card Orders</h3>
            <p className="muted" style={{ margin: '2px 0 0', fontSize: 13 }}>
              Your physical NFC transit card order history
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              border: 0,
              background: 'var(--bg, #fbf9f5)',
              color: 'var(--text, #1e1b16)',
              borderRadius: '50%',
              width: 32,
              height: 32,
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              fontWeight: 800,
            }}
          >
            ✕
          </button>
        </div>

        {error && (
          <div style={{ background: '#fce8e5', color: '#a52b23', padding: '10px 14px', borderRadius: 10, marginBottom: 14, fontSize: 13, fontWeight: 700 }}>
            ⚠️ {error}
          </div>
        )}

        {loading ? (
          <p className="muted" style={{ padding: '30px 0', textAlign: 'center' }}>Loading orders...</p>
        ) : orders.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--bg, #fbf9f5)', borderRadius: 14, border: '1px dashed var(--line)' }}>
            <span className="material-symbols-outlined" style={{ fontSize: 40, color: 'var(--muted)', marginBottom: 8 }}>credit_card</span>
            <p style={{ margin: 0, fontWeight: 700, color: 'var(--text)' }}>No NFC card orders yet.</p>
            <p className="muted" style={{ margin: '4px 0 16px', fontSize: 13 }}>Get your physical Tap&amp;Go NFC card for cashless transit.</p>
            <button
              type="button"
              className="primary"
              onClick={() => {
                onClose()
                onOrderAgain?.()
              }}
              style={{ padding: '10px 20px', borderRadius: 10, fontWeight: 800 }}
            >
              Order NFC Card (₹50)
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {orders.map((o) => (
              <div
                key={o.id || o.order_reference}
                style={{ background: 'var(--card, #fff)', border: '1px solid var(--line, #eae4da)', borderRadius: 14, padding: 16 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div>
                    <strong style={{ fontSize: 15, color: 'var(--text)', display: 'block' }}>{o.order_reference}</strong>
                    <span className="muted" style={{ fontSize: 11 }}>
                      {o.created_at ? new Date(o.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <strong style={{ fontSize: 16, color: '#177a47', display: 'block' }}>₹{o.total_amount.toFixed(2)}</strong>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end', marginTop: 4 }}>
                      <span style={{
                        fontSize: 10,
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        padding: '2px 8px',
                        borderRadius: 99,
                        background: o.order_status === 'delivered' ? '#e2f3e8' : '#fffbeb',
                        color: o.order_status === 'delivered' ? '#177a47' : '#8a6400'
                      }}>
                        {o.order_status.replace('_', ' ')}
                      </span>
                      <span style={{
                        fontSize: 10,
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        padding: '2px 8px',
                        borderRadius: 99,
                        background: '#fff2c5',
                        color: '#8a6400'
                      }}>
                        {o.payment_status === 'simulated' ? 'SIMULATED' : o.payment_status}
                      </span>
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: 12, color: 'var(--muted)', pt: 6, borderTop: '1px dashed var(--line)', marginTop: 8, paddingTop: 8, display: 'flex', justifyContent: 'space-between' }}>
                  <span>NFC Card: ₹{o.card_price.toFixed(2)} + Shipping ({o.delivery_tier.toUpperCase()}): ₹{o.delivery_charge.toFixed(2)}</span>
                  <span>{o.city}, {o.state}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="modal-actions" style={{ marginTop: 20 }}>
          <button
            type="button"
            className="secondary-btn"
            onClick={onClose}
            style={{ width: '100%', padding: '12px', borderRadius: 10, fontWeight: 700 }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default NFCOrderHistoryModal
