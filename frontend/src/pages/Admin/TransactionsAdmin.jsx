import { useEffect, useState } from 'react'
import { adminRequest, adminAuthHeaders, API_BASE } from './api.js'
import { Badge, Empty, LoadState } from './adminUi.jsx'
import { date, money, number } from './adminFormat.js'

const EMPTY_FILTERS = { search: '', status: '', payment_method: '', from_date: '', to_date: '', passenger_id: '', driver_id: '' }

const queryString = (filters, extra = {}) => {
  const params = new URLSearchParams()
  Object.entries({ ...filters, ...extra }).forEach(([key, value]) => { if (String(value).trim()) params.set(key, String(value).trim()) })
  const text = params.toString()
  return text ? `?${text}` : ''
}

export default function TransactionsAdmin({ adminId }) {
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [result, setResult] = useState({ items: [], total: 0, page_size: 20 })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    adminRequest(`/transactions${queryString(applied, { page })}`, adminId)
      .then((data) => { setResult(data || { items: [], total: 0, page_size: 20 }); setError('') })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [adminId, applied, page])

  const set = (key) => (event) => setDraft({ ...draft, [key]: event.target.value })
  const apply = (event) => { event?.preventDefault(); setPage(1); setApplied(draft) }
  const clear = () => { setDraft(EMPTY_FILTERS); setPage(1); setApplied(EMPTY_FILTERS) }

  const exportCsv = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/admin/transactions/export${queryString(applied)}`, { headers: adminAuthHeaders() })
      if (!response.ok) throw new Error('Could not export transactions.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a'); link.href = url; link.download = 'tapgo-transactions.csv'; link.click(); URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) }
  }

  const rows = result.items || []
  const pages = Math.max(1, Math.ceil((result.total || 0) / (result.page_size || 20)))
  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Live operational records</span>
          <h2>Transactions</h2>
          <p>Filter by date, passenger, driver or status. The CSV export applies the same filters.</p>
        </div>
        <button className="primary-button" onClick={exportCsv}>Export CSV</button>
      </div>
      <form className="table-controls" onSubmit={apply}>
        <input value={draft.search} onChange={set('search')} placeholder="Search by reference" />
        <select value={draft.status} onChange={set('status')} aria-label="Status">
          <option value="">All statuses</option><option value="completed">Completed</option><option value="pending">Pending</option>
          <option value="failed">Failed</option><option value="approved">Approved</option><option value="cancelled">Cancelled</option>
        </select>
        <label style={{ display: 'grid', gap: 2, fontSize: 11 }}>From<input type="date" value={draft.from_date} onChange={set('from_date')} /></label>
        <label style={{ display: 'grid', gap: 2, fontSize: 11 }}>To<input type="date" value={draft.to_date} onChange={set('to_date')} /></label>
        <input type="number" min="1" value={draft.passenger_id} onChange={set('passenger_id')} placeholder="Passenger ID" style={{ maxWidth: 130 }} />
        <input type="number" min="1" value={draft.driver_id} onChange={set('driver_id')} placeholder="Driver ID" style={{ maxWidth: 130 }} />
        <button className="secondary-button" type="submit">Apply</button>
        <button className="secondary-button" type="button" onClick={clear}>Clear</button>
        <span className="record-count">{number(result.total)} transactions</span>
      </form>
      <LoadState error={error}>
        {loading ? <Empty text="Loading live records…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Reference</th><th>Passenger</th><th>Driver</th><th>Vehicle</th><th>Type</th><th>Method</th><th>Amount</th><th>Balance after</th><th>Status</th><th>Date</th></tr></thead>
              <tbody>
                {rows.length ? rows.map((row) => (
                  <tr key={row.id}>
                    <td><code style={{ fontSize: 11 }}>{row.reference}</code></td>
                    <td>{row.passenger || '—'}</td>
                    <td>{row.driver || '—'}</td>
                    <td>{row.vehicle_type || row.vehicle_registration ? <>{row.vehicle_type || '—'}<br /><small>{row.vehicle_registration || ''}</small></> : '—'}</td>
                    <td style={{ fontSize: 12 }}>{(row.transaction_type || '—').replaceAll('_', ' ')}</td>
                    <td>{row.payment_method}</td>
                    <td><strong>{money(row.amount)}</strong></td>
                    <td>{row.balance_after == null ? '—' : money(row.balance_after)}</td>
                    <td><Badge value={row.status} />{row.failure_reason && <small style={{ display: 'block', color: '#a52b23' }}>{row.failure_reason}</small>}</td>
                    <td>{date(row.created_at)}</td>
                  </tr>
                )) : <tr><td colSpan="10"><Empty /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
      {pages > 1 && (
        <div className="table-controls" style={{ marginTop: 14 }}>
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="record-count" style={{ marginLeft: 0 }}>Page {page} of {pages}</span>
          <button className="secondary-button" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </section>
  )
}
