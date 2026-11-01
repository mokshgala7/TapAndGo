import { useEffect, useState } from 'react'
import { adminRequest } from './api.js'
import { Badge, Empty, LoadState } from './adminUi.jsx'
import { date, number } from './adminFormat.js'

const FILTERS = [['', 'All statuses'], ['pending', 'Pending'], ['approved', 'Approved'], ['rejected', 'Rejected']]
const BANK_LABELS = {
  bank_account_holder: 'Account holder', bank_account_number: 'Account number', bank_ifsc: 'IFSC', bank_upi_id: 'UPI ID',
}

// A stored value is plain text (phone) or a JSON object (bank details); turn both into [label, text] rows.
function toRows(raw) {
  if (raw === null || raw === undefined || raw === '') return []
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return Object.entries(parsed).map(([key, value]) => [BANK_LABELS[key] || key.replaceAll('_', ' '), value === null || value === undefined || value === '' ? '' : String(value)])
    }
  } catch { /* plain text */ }
  return [['Value', String(raw)]]
}

function Comparison({ request }) {
  // "Before" is what was recorded with the request, else what the user has on file right now.
  const before = toRows(request.previous_value ?? request.current_value)
  const after = toRows(request.new_value)
  if (!before.length && !after.length) return <small style={{ color: '#6b6458' }}>Permission request — no new value submitted yet.</small>
  const labels = [...new Set([...before.map(([k]) => k), ...after.map(([k]) => k)])]
  const lookup = (rows, label) => rows.find(([k]) => k === label)?.[1]
  return (
    <table style={{ fontSize: 12, minWidth: 260 }}>
      <thead><tr><th></th><th>Before</th><th>After</th></tr></thead>
      <tbody>
        {labels.map((label) => {
          const prev = lookup(before, label); const next = lookup(after, label)
          const changed = next !== undefined && next !== (prev ?? '')
          return (
            <tr key={label}>
              <td><b>{label}</b></td>
              <td>{prev || '—'}</td>
              <td style={changed ? { color: '#177a47', fontWeight: 700 } : undefined}>{next === undefined ? '—' : (next || '—')}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default function EditRequestsAdmin({ adminId }) {
  const [status, setStatus] = useState('')
  const [result, setResult] = useState({ items: [], total: 0 })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    adminRequest(`/edit-requests${status ? `?status=${status}` : ''}`, adminId)
      .then((data) => { setResult(data || { items: [], total: 0 }); setError('') })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [adminId, status])

  const review = async (row, action) => {
    let reason
    if (action === 'reject') {
      reason = window.prompt('Reason for rejecting (optional, shown to admins):')
      if (reason === null) return
    }
    try {
      await adminRequest(`/edit-requests/${row.id}/review`, adminId, { method: 'POST', body: JSON.stringify({ action, ...(reason && reason.trim() ? { reason: reason.trim() } : {}) }) })
      load()
    } catch (err) { setError(err.message) }
  }

  const rows = result.items || []
  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Profile change approvals</span>
          <h2>Edit Requests</h2>
          <p>Review phone, bank and document change requests. Full values are shown to administrators only.</p>
        </div>
      </div>
      <div className="table-controls">
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Request status">
          {FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <button className="secondary-button" onClick={load}>Refresh</button>
        <span className="record-count">{number(result.total)} requests</span>
      </div>
      <LoadState error={error}>
        {loading ? <Empty text="Loading edit requests…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Requester</th><th>Field</th><th>Reason</th><th>Before → After</th><th>Status</th><th>Requested</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.length ? rows.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.user_name}</strong><br /><small>{row.user_email}</small><br /><small style={{ textTransform: 'capitalize' }}>{row.account_type}</small></td>
                    <td>{row.request_type}</td>
                    <td style={{ fontSize: 12, minWidth: 160 }}>{row.reason || '—'}</td>
                    <td><Comparison request={row} /></td>
                    <td>
                      <Badge value={row.status} />
                      {row.admin_note && <small style={{ display: 'block', marginTop: 6, color: '#a52b23' }}>Reason: {row.admin_note}</small>}
                    </td>
                    <td>{date(row.created_at)}{row.reviewed_at && <small style={{ display: 'block' }}>Reviewed {date(row.reviewed_at)}</small>}</td>
                    <td className="actions">
                      {row.status === 'pending' && <><button onClick={() => review(row, 'approve')}>Approve</button><button onClick={() => review(row, 'reject')}>Reject</button></>}
                    </td>
                  </tr>
                )) : <tr><td colSpan="7"><Empty text="No edit requests found." /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  )
}
