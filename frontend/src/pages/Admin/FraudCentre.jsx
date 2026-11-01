import { useEffect, useState } from 'react'
import { adminRequest } from './api.js'
import { Badge, Empty, LoadState } from './adminUi.jsx'
import { date, money, number } from './adminFormat.js'

const FILTERS = [['open', 'Open (flagged)'], ['reviewed', 'Reviewed'], ['safe', 'Marked safe'], ['blocked', 'Blocked'], ['all', 'All']]

export default function FraudCentre({ adminId }) {
  const [status, setStatus] = useState('open')
  const [result, setResult] = useState({ items: [], total: 0 })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    adminRequest(`/fraud-alerts?status=${status}`, adminId)
      .then((data) => { setResult(data || { items: [], total: 0 }); setError('') })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [adminId, status])

  const review = async (id, action) => {
    const labels = { safe: 'Mark this alert as safe?', block: 'Suspend this user?', freeze: 'Freeze this user\'s wallet?' }
    if (!window.confirm(labels[action])) return
    try { await adminRequest(`/fraud-alerts/${id}/review`, adminId, { method: 'POST', body: JSON.stringify({ action }) }); load() }
    catch (err) { setError(err.message) }
  }

  const rows = result.items || []
  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Risk review</span>
          <h2>Fraud Centre</h2>
          <p>Payments the fraud model flagged. Mark an alert safe, suspend the user, or freeze their wallet.</p>
        </div>
      </div>
      <div className="table-controls">
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Alert status">
          {FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button className="secondary-button" onClick={load}>Refresh</button>
        <span className="record-count">{number(result.total)} alerts</span>
      </div>
      <LoadState error={error}>
        {loading ? <Empty text="Loading fraud alerts…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>User</th><th>Amount</th><th>Reason</th><th>Risk score</th><th>Status</th><th>Time</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.length ? rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.user_name || (row.user_id ? `User #${row.user_id}` : '—')}</td>
                    <td>{row.amount == null ? '—' : money(row.amount)}</td>
                    <td style={{ fontSize: 12, minWidth: 220 }}>{row.reason || '—'}</td>
                    <td><strong>{row.risk_score}</strong>/100</td>
                    <td><Badge value={row.status} /></td>
                    <td>{date(row.created_at)}</td>
                    <td className="actions">
                      {row.status === 'open' && <>
                        <button onClick={() => review(row.id, 'safe')}>Mark safe</button>
                        <button onClick={() => review(row.id, 'block')}>Block user</button>
                        <button onClick={() => review(row.id, 'freeze')}>Freeze wallet</button>
                      </>}
                    </td>
                  </tr>
                )) : <tr><td colSpan="7"><Empty text={status === 'open' ? 'No flagged payments awaiting review.' : 'No alerts match this filter.'} /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  )
}
