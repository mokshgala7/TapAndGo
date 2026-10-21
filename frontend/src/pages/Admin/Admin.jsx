import { Component, useEffect, useState } from 'react'
import { Link, useNavigate } from '../../routes/navigation.jsx'
import { adminRequest, adminAuthHeaders, API_BASE, fileUrl } from './api.js'
import DatabaseViewer from './database/DatabaseViewer.jsx'
import './admin.css'

class AdminErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, errorInfo) {
    console.error('Admin shell error caught:', error, errorInfo)
  }
  render() {
    if (this.state.hasError) {
      return (
        <section className="admin-section" style={{ padding: '30px' }}>
          <div style={{ padding: '24px', background: '#fff', borderRadius: '12px', border: '1px solid #fed7aa' }}>
            <h3 style={{ color: '#c2410c', margin: '0 0 8px' }}>Unable to load view</h3>
            <p style={{ color: '#6b6458', margin: '0 0 16px', fontSize: '14px' }}>
              {this.state.error?.message || 'An error occurred while loading this section.'}
            </p>
            <button className="primary-button" onClick={() => this.setState({ hasError: false, error: null })}>
              Reload section
            </button>
          </div>
        </section>
      )
    }
    return this.props.children
  }
}

const navigation = [
  ['dashboard', 'Overview', '▦'], ['drivers', 'Driver Management', '♙'], ['passengers', 'Passenger Management', '♟'],
  ['nfc-orders', 'NFC Card Orders', '💳'], ['documents', 'Driver Documents', '▤'], ['requests', 'Edit Requests', '✓'],
  ['transactions', 'Transactions', '⇄'], ['wallets', 'Wallets', '◉'], ['fraud', 'Fraud Centre', '⚑'],
  ['withdrawals', 'Withdrawal Requests', '💸'], ['support', 'Support Tickets', '🎫'],
  ['logs', 'Activity Logs', '◷'], ['settings', 'Settings', '⚙'], ['database', 'Database Viewer', '▤'],
]
const resourceConfig = {
  documents: ['Driver Documents', '/documents'], requests: ['Edit Requests', '/edit-requests'], transactions: ['Transactions', '/transactions'],
  wallets: ['Wallet Management', '/wallets'], fraud: ['Fraud Management', '/fraud-alerts'], logs: ['Activity Logs', '/activity-logs'],
}

const number = (value) => new Intl.NumberFormat('en-IN').format(value || 0)
const money = (value) => `₹${new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0)}`
const date = (value) => value ? new Date(value).toLocaleString() : '—'

function LoadState({ error, children }) { return error ? <p className="admin-error">{error}</p> : children }
function Badge({ value }) { return <span className={`status status-${String(value || 'unknown').toLowerCase()}`}>{value || 'unknown'}</span> }
function Empty({ text = 'No live records yet.' }) { return <div className="empty-state">{text}</div> }

function AdminLogin({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)
  const submit = async (event) => {
    event.preventDefault(); setError(''); setWorking(true)
    try { onLogin(await adminRequest('/login', null, { method: 'POST', body: JSON.stringify({ email: email.trim(), password }) })) }
    catch (loginError) { setError(loginError.message) }
    finally { setWorking(false) }
  }
  return (
    <main className="admin-login">
      <section className="admin-login-card">
        <div className="admin-mark">T&G</div>
        <span className="eyebrow">Tap&Go control centre</span>
        <h1>Administrator sign in</h1>
        <p>Sign in to access the administrator control centre.</p>
        <form onSubmit={submit}>
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••" required />
          </label>
          {error && <p className="admin-error">{error}</p>}
          <button className="primary-button" disabled={working}>
            {working ? 'Signing in…' : 'Sign in securely'}
          </button>
          <div style={{ marginTop: '16px', textAlign: 'center' }}>
            <Link to="/login" style={{ color: 'var(--admin-muted)', textDecoration: 'underline', fontSize: '13px' }}>
              ← Return to User Login
            </Link>
          </div>
        </form>
      </section>
    </main>
  )
}

function Dashboard({ adminId }) {
  const [stats, setStats] = useState(null); const [error, setError] = useState('')
  useEffect(() => { adminRequest('/dashboard', adminId).then(setStats).catch((err) => setError(err.message)) }, [adminId])
  const cards = stats && [
    ['Total Drivers', stats.total_drivers, 'Driver accounts'], ['Active Drivers', stats.active_drivers, `${stats.pending_drivers} pending approval`], ['Suspended Drivers', stats.suspended_drivers, 'Restricted accounts'],
    ['Total Passengers', stats.total_passengers, `${stats.active_passengers} active`], ['Transactions', stats.total_transactions, `${stats.today_transactions} today`], ['Wallet Balance', money(stats.wallet_balance), 'Across live wallets'],
    ['Revenue', money(stats.revenue), 'Completed transactions'], ['Fraud Alerts', stats.fraud_alerts, 'Awaiting review'], ['Edit Requests', stats.pending_edit_requests, 'Awaiting action'],
  ]
  return <section className="admin-section"><div className="section-heading"><div><span className="eyebrow">Operations at a glance</span><h2>Dashboard Overview</h2><p>Live counts from the Tap&Go backend database.</p></div></div><LoadState error={error}>{!stats ? <Empty text="Loading live operations…" /> : <div className="metric-grid">{cards.map(([label, value, hint]) => <article className="metric-card" key={label}><div className="metric-icon">◈</div><p>{label}</p><strong>{typeof value === 'number' ? number(value) : value}</strong><small>{hint}</small></article>)}</div>}</LoadState></section>
}

function UserDirectory({ adminId, type }) {
  const [result, setResult] = useState({ items: [] }); const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [error, setError] = useState(''); const [detail, setDetail] = useState(null)
  const load = () => adminRequest(`/users?account_type=${type}&search=${encodeURIComponent(search)}${status ? `&status=${status}` : ''}`, adminId).then(setResult).catch((err) => setError(err.message))
  useEffect(() => { load() }, [adminId, type, status, search])
  const action = async (userId, actionName) => { if (actionName === 'delete' && !window.confirm('Delete this account and its wallet record?')) return; try { await adminRequest(`/users/${userId}/action`, adminId, { method: 'POST', body: JSON.stringify({ action: actionName }) }); load(); if (detail?.id === userId) setDetail(null) } catch (err) { setError(err.message) } }
  const open = async (id) => { try { setDetail(await adminRequest(`/users/${id}`, adminId)) } catch (err) { setError(err.message) } }
  const plural = type === 'driver' ? 'Drivers' : 'Passengers'
  return <section className="admin-section"><div className="section-heading"><div><span className="eyebrow">Live account directory</span><h2>{plural}</h2><p>Search, inspect, approve, suspend, edit, or remove live accounts.</p></div></div><div className="table-controls"><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && load()} placeholder={`Search ${plural.toLowerCase()} by name, email or phone`} /><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All states</option><option value="active">Active</option><option value="pending">Pending</option><option value="suspended">Suspended</option><option value="rejected">Rejected</option></select><button className="secondary-button" onClick={load}>Search</button></div><LoadState error={error}><div className="table-wrap"><table><thead><tr><th>Person</th><th>Phone</th><th>City</th><th>Wallet</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>{result.items?.length ? result.items.map((user) => <tr key={user.id}><td><button className="table-link" onClick={() => open(user.id)}>{user.name}<small>{user.email}</small></button></td><td>{user.phone}</td><td>{user.city || '—'}</td><td>{money(user.wallet_balance)}</td><td><Badge value={user.status} /></td><td>{date(user.created_at)}</td><td className="actions"><button onClick={() => action(user.id, user.status === 'suspended' ? 'activate' : 'suspend')}>{user.status === 'suspended' ? 'Activate' : 'Suspend'}</button>{type === 'driver' && user.status === 'pending' && <button onClick={() => action(user.id, 'approve')}>Approve</button>}<button onClick={() => action(user.id, 'delete')}>Delete</button></td></tr>) : <tr><td colSpan="7"><Empty /></td></tr>}</tbody></table></div></LoadState>{detail && <UserModal data={detail} adminId={adminId} onClose={() => setDetail(null)} onAction={action} onSaved={() => { load(); open(detail.id) }} />}</section>
}

function UserModal({ data, adminId, onClose, onAction, onSaved }) {
  const [editing, setEditing] = useState(false); const [draft, setDraft] = useState({ name: data.name || '', email: data.email || '', city: data.city || '', address: data.address || '' }); const [error, setError] = useState('')
  const save = async () => { try { await adminRequest(`/users/${data.id}`, adminId, { method: 'PUT', body: JSON.stringify(draft) }); setEditing(false); onSaved() } catch (err) { setError(err.message) } }
  return <div className="modal-backdrop" role="presentation"><article className="profile-modal" role="dialog" aria-modal="true"><button className="modal-close" onClick={onClose}>×</button><span className="eyebrow">{data.account_type} profile</span><h2>{data.name}</h2>{error && <p className="admin-error">{error}</p>}<div className="profile-grid">{editing ? <><label>Name<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label>Email<input value={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.value })} /></label><label>City<input value={draft.city} onChange={(event) => setDraft({ ...draft, city: event.target.value })} /></label><label>Address<input value={draft.address} onChange={(event) => setDraft({ ...draft, address: event.target.value })} /></label></> : <><p><b>Email</b>{data.email}</p><p><b>Phone</b>{data.phone}</p><p><b>Wallet balance</b>{money(data.wallet_balance)}</p><p><b>Wallet status</b>{data.wallet_frozen ? 'Frozen' : 'Available'}</p><p><b>QR identifier</b>{data.qr_identifier || 'Not issued'}</p><p><b>NFC identifier</b>{data.nfc_identifier || 'Not issued'}</p></>}</div><h3>Uploaded documents</h3>{data.documents?.length ? <ul className="document-list">{data.documents.map((document) => <li key={document.id}><span>{document.type}</span><a href={fileUrl(document.file_path)} target="_blank" rel="noreferrer">Open</a></li>)}</ul> : <Empty text="No uploaded documents." />}<h3>Recent transactions</h3>{data.transactions?.length ? <div className="modal-transactions">{data.transactions.map((transaction) => <p key={transaction.id}>{transaction.reference} <b>{money(transaction.amount)}</b> <Badge value={transaction.status} /></p>)}</div> : <Empty text="No transactions recorded." />}<div className="modal-actions">{editing ? <button className="primary-button" onClick={save}>Save changes</button> : <button className="secondary-button" onClick={() => setEditing(true)}>Edit profile</button>}<button className="secondary-button" onClick={() => onAction(data.id, data.status === 'suspended' ? 'activate' : 'suspend')}>{data.status === 'suspended' ? 'Activate account' : 'Suspend account'}</button></div></article></div>
}

function SimpleResource({ adminId, kind }) {
  const config = resourceConfig[kind] || ['Operational Records', '/activity-logs']
  const [result, setResult] = useState({ items: [] }); const [error, setError] = useState(''); const [search, setSearch] = useState(''); const [loading, setLoading] = useState(true)
  const load = () => {
    setLoading(true)
    adminRequest(`${config[1]}${search && ['documents', 'transactions', 'wallets'].includes(kind) ? `?search=${encodeURIComponent(search)}` : ''}`, adminId)
      .then((data) => {
        setResult(data && typeof data === 'object' ? data : { items: [] })
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }
  useEffect(() => { load() }, [adminId, kind, search])
  const act = async (id, path, body) => { try { await adminRequest(path, adminId, { method: 'POST', body: JSON.stringify(body) }); load() } catch (err) { setError(err.message) } }
  const exportCsv = async () => { try { const response = await fetch(`${API_BASE}/api/admin/transactions/export`, { headers: adminAuthHeaders() }); if (!response.ok) throw new Error('Could not export transactions.'); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'tapgo-transactions.csv'; link.click(); URL.revokeObjectURL(url) } catch (err) { setError(err.message) } }
  const rows = result.items || []; const columns = Object.keys(rows[0] || {}).filter((column) => !['proof_path', 'file_path', 'user_id', 'transaction_id'].includes(column))
  return <section className="admin-section"><div className="section-heading"><div><span className="eyebrow">Live operational records</span><h2>{config[0]}</h2><p>{kind === 'documents' ? 'All uploaded files, generated dynamically from database fields.' : kind === 'fraud' ? 'Risk alerts ready for AI-generated signals.' : 'Search and act on records stored in MySQL.'}</p></div>{kind === 'transactions' && <button className="primary-button" onClick={exportCsv}>Export CSV</button>}</div>{['documents', 'transactions', 'wallets'].includes(kind) && <div className="table-controls"><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && load()} placeholder="Search live records" /><button className="secondary-button" onClick={load}>Search</button></div>}<LoadState error={error}>{loading ? <Empty text="Loading live records…" /> : <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll('_', ' ')}</th>)}<th>Actions</th></tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={row.id || index}>{columns.map((column) => <td key={column}>{typeof row[column] === 'boolean' ? (row[column] ? 'Yes' : 'No') : column.includes('amount') || column === 'balance' ? money(row[column]) : /_at$/.test(column) ? date(row[column]) : row[column] || '—'}</td>)}<td className="actions">{kind === 'documents' && row.file_path && <a href={fileUrl(row.file_path)} target="_blank" rel="noreferrer">Open</a>}{kind === 'requests' && row.status === 'pending' && <><button onClick={() => act(row.id, `/edit-requests/${row.id}/review`, { action: 'approve' })}>Approve</button><button onClick={() => act(row.id, `/edit-requests/${row.id}/review`, { action: 'reject' })}>Reject</button></>}{kind === 'wallets' && <button onClick={() => act(row.id, `/wallets/${row.id}`, { frozen: !row.is_frozen })}>{row.is_frozen ? 'Unfreeze' : 'Freeze'}</button>}{kind === 'fraud' && row.status === 'open' && <><button onClick={() => act(row.id, `/fraud-alerts/${row.id}/review`, { action: 'safe' })}>Mark safe</button><button onClick={() => act(row.id, `/fraud-alerts/${row.id}/review`, { action: 'block' })}>Block</button><button onClick={() => act(row.id, `/fraud-alerts/${row.id}/review`, { action: 'freeze' })}>Freeze</button></>}</td></tr>) : <tr><td colSpan={Math.max(columns.length + 1, 1)}><Empty /></td></tr>}</tbody></table></div>}</LoadState></section>
}

function Settings({ adminId }) {
  const [items, setItems] = useState([])
  const [projectName, setProjectName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    adminRequest('/settings', adminId)
      .then((data) => {
        setItems(data?.items || [])
        setProjectName((data?.items || []).find((item) => item.key === 'project_name')?.value || '')
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }

  useEffect(() => { load() }, [adminId])

  const save = async () => {
    try {
      await adminRequest('/settings/project_name', adminId, { method: 'PUT', body: JSON.stringify({ value: projectName }) })
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="admin-section narrow-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Configuration</span>
          <h2>Settings</h2>
          <p>Project configuration is stored in MySQL and ready for future controls.</p>
        </div>
      </div>
      <LoadState error={error}>
        {loading ? (
          <Empty text="Loading settings…" />
        ) : (
          <div>
            <label>
              Project name
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Tap&Go" />
            </label>
            <button className="primary-button" onClick={save}>Save project name</button>
            <h3>Saved settings</h3>
            {items.length ? (
              <ul className="settings-list">
                {items.map((item) => (
                  <li key={item.key}>
                    <b>{item.key}</b>
                    <span>{item.value || '—'}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty text="No additional settings saved." />
            )}
          </div>
        )}
      </LoadState>
    </section>
  )
}

function NFCOrdersAdmin({ adminId }) {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    adminRequest('/card-order/admin/all', adminId)
      .then((data) => {
        setOrders(data?.orders || [])
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }

  useEffect(() => { load() }, [adminId])

  const updateStatus = async (orderId, newStatus) => {
    try {
      await adminRequest(`/card-order/admin/${orderId}/status`, adminId, {
        method: 'PATCH',
        body: JSON.stringify({ order_status: newStatus }),
      })
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Physical transit cards</span>
          <h2>NFC Card Orders</h2>
          <p>Inspect, update status, and manage physical NFC card shipments.</p>
        </div>
      </div>

      <LoadState error={error}>
        {loading ? (
          <Empty text="Loading NFC card orders…" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Order Ref</th>
                  <th>Recipient</th>
                  <th>Delivery Address</th>
                  <th>Tier</th>
                  <th>Breakdown</th>
                  <th>Total</th>
                  <th>Order Status</th>
                  <th>Payment</th>
                  <th>Date</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {orders.length ? (
                  orders.map((o) => (
                    <tr key={o.id}>
                      <td><strong>{o.order_reference}</strong>{o.is_demo && <small style={{ display: 'block', color: '#8a6400', fontWeight: 700 }}>DEMO</small>}</td>
                      <td>{o.recipient_name}<br /><small>{o.phone}</small></td>
                      <td>{o.address_line1}, {o.area}, {o.city}, {o.state} – {o.pincode}</td>
                      <td><span style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase' }}>{o.delivery_tier}</span></td>
                      <td>Card: {money(o.card_price)} + Ship: {money(o.delivery_charge)}</td>
                      <td><strong>{money(o.total_amount)}</strong></td>
                      <td><Badge value={o.order_status} /></td>
                      <td>
                        {o.is_demo || o.payment_status === 'simulated' ? (
                          <span style={{ fontSize: 10, fontWeight: 800, padding: '3px 8px', borderRadius: 99, background: '#fff3c4', color: '#8a6400', border: '1px solid #ffe082', display: 'inline-block' }}>
                            DEMO / SIMULATED
                          </span>
                        ) : (
                          <Badge value={o.payment_status} />
                        )}
                      </td>
                      <td>{date(o.created_at)}</td>
                      <td className="actions">
                        <select
                          value={o.order_status}
                          onChange={(e) => updateStatus(o.id, e.target.value)}
                          style={{ padding: '4px 6px', fontSize: 11, borderRadius: 6 }}
                        >
                          <option value="processing">Processing</option>
                          <option value="dispatched">Dispatched</option>
                          <option value="delivered">Delivered</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan="10"><Empty text="No NFC card orders recorded yet." /></td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  )
}

function WithdrawalRequestsAdmin({ adminId }) {
  const [result, setResult] = useState({ items: [] })
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionMsg, setActionMsg] = useState('')

  const load = () => {
    setLoading(true)
    adminRequest(`/withdrawal-requests${filter ? `?status=${filter}` : ''}`, adminId)
      .then((data) => { setResult(data || { items: [] }); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }
  useEffect(() => { load() }, [adminId, filter])

  const act = async (id, action) => {
    const confirmMsg = action === 'reject' ? 'Reject this withdrawal and restore the user\'s balance?' : action === 'pay' ? 'Mark this withdrawal as paid out?' : 'Approve this withdrawal?'
    if (!window.confirm(confirmMsg)) return
    const note = action === 'reject' ? window.prompt('Optional rejection reason (leave blank to skip):') : null
    try {
      setActionMsg('')
      const body = action === 'reject' ? JSON.stringify({ admin_note: note || null }) : undefined
      await adminRequest(`/withdrawal-requests/${id}/${action}`, adminId, { method: 'PATCH', body })
      setActionMsg(`Withdrawal #${id} ${action}d successfully.`)
      load()
    } catch (err) { setError(err.message) }
  }

  const STATUS_COLORS = { pending: '#9a5b00', approved: '#8a6400', paid: '#177a47', rejected: '#c8372d' }
  return (
    <section className="admin-section">
      <div className="section-heading">
        <div><span className="eyebrow">Wallet Withdrawals</span><h2>Withdrawal Request Management</h2><p>Approve, mark as paid, or reject user withdrawal requests. Balance is reserved at submission and reversed on rejection.</p></div>
      </div>
      <div className="table-controls">
        <select value={filter} onChange={(e) => { setFilter(e.target.value) }} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #eae4da' }}>
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="paid">Paid</option>
          <option value="rejected">Rejected</option>
        </select>
        <button className="secondary-button" onClick={load}>Refresh</button>
      </div>
      {actionMsg && <p style={{ color: '#2e9560', fontWeight: 600, marginBottom: 12 }}>{actionMsg}</p>}
      <LoadState error={error}>
        {loading ? <Empty text="Loading withdrawal requests…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>User ID</th><th>Reference</th><th>Amount</th><th>Destination</th><th>Status</th><th>Note</th><th>Submitted</th><th>Actions</th></tr></thead>
              <tbody>
                {result.items?.length ? result.items.map((w) => (
                  <tr key={w.id}>
                    <td>{w.id}</td>
                    <td>{w.user_id}</td>
                    <td><code style={{ fontSize: 11 }}>{w.reference}</code></td>
                    <td><strong>{money(w.amount)}</strong></td>
                    <td style={{ fontSize: 12 }}>{w.destination_desc}</td>
                    <td><span style={{ padding: '2px 10px', borderRadius: 20, fontSize: 11, fontWeight: 700, background: (STATUS_COLORS[w.status] || '#a39b8e') + '22', color: STATUS_COLORS[w.status] || '#a39b8e' }}>{w.status}</span></td>
                    <td style={{ fontSize: 12, color: '#6b6458' }}>{w.admin_note || '—'}</td>
                    <td>{date(w.created_at)}</td>
                    <td className="actions">
                      {w.status === 'pending' && <><button onClick={() => act(w.id, 'approve')}>Approve</button><button onClick={() => act(w.id, 'reject')}>Reject</button></>}
                      {w.status === 'approved' && <button onClick={() => act(w.id, 'pay')}>Mark Paid</button>}
                      {(w.status === 'paid' || w.status === 'rejected') && <span style={{ color: '#a39b8e', fontSize: 12 }}>{w.status === 'paid' ? '✓ Paid' : '✗ Rejected'}</span>}
                    </td>
                  </tr>
                )) : <tr><td colSpan="9"><Empty text="No withdrawal requests found." /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  )
}

function SupportTicketsAdmin({ adminId }) {
  const [result, setResult] = useState({ items: [] })
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [replyText, setReplyText] = useState('')
  const [newStatus, setNewStatus] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    adminRequest(`/support/admin/all${filter ? `?ticket_status=${filter}` : ''}`, adminId)
      .then((data) => { setResult(data || { items: [] }); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }
  useEffect(() => { load() }, [adminId, filter])

  const sendReply = async () => {
    if (!replyText.trim()) return
    setSaving(true)
    try {
      await adminRequest(`/support/admin/${selected.id}/reply`, adminId, { method: 'PATCH', body: JSON.stringify({ admin_reply: replyText, status: newStatus || undefined }) })
      setSelected(null); setReplyText(''); setNewStatus('')
      load()
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }

  const updateStatus = async (id, status) => {
    try { await adminRequest(`/support/admin/${id}/status`, adminId, { method: 'PATCH', body: JSON.stringify({ status }) }); load() }
    catch (err) { setError(err.message) }
  }

  const PRIORITY_COLORS = { urgent: '#c8372d', high: '#9a5b00', medium: '#8a6400', low: '#177a47' }
  const STATUS_COLORS = { open: '#c8372d', in_progress: '#9a5b00', resolved: '#177a47', closed: '#6b6458' }

  return (
    <section className="admin-section">
      <div className="section-heading">
        <div><span className="eyebrow">Customer Support</span><h2>Support Tickets</h2><p>View, reply to, and resolve user support tickets. Email notifications sent on reply.</p></div>
      </div>
      <div className="table-controls">
        <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #eae4da' }}>
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
        <button className="secondary-button" onClick={load}>Refresh</button>
      </div>
      <LoadState error={error}>
        {loading ? <Empty text="Loading support tickets…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>User</th><th>Category</th><th>Priority</th><th>Subject</th><th>Status</th><th>Submitted</th><th>Actions</th></tr></thead>
              <tbody>
                {result.items?.length ? result.items.map((t) => (
                  <tr key={t.id}>
                    <td>#{t.id}</td>
                    <td><span style={{ fontSize: 12 }}>{t.name}<br /><small style={{ color: '#6b6458' }}>{t.email}</small></span></td>
                    <td style={{ fontSize: 12 }}>{t.category}</td>
                    <td><span style={{ padding: '2px 8px', borderRadius: 20, fontSize: 11, fontWeight: 700, background: (PRIORITY_COLORS[t.priority] || '#a39b8e') + '22', color: PRIORITY_COLORS[t.priority] || '#a39b8e' }}>{t.priority}</span></td>
                    <td style={{ fontSize: 12, maxWidth: 200 }}>{t.subject}</td>
                    <td><span style={{ padding: '2px 8px', borderRadius: 20, fontSize: 11, fontWeight: 700, background: (STATUS_COLORS[t.status] || '#a39b8e') + '22', color: STATUS_COLORS[t.status] || '#a39b8e' }}>{t.status}</span></td>
                    <td style={{ fontSize: 12 }}>{date(t.created_at)}</td>
                    <td className="actions">
                      <button onClick={() => { setSelected(t); setReplyText(t.admin_reply || ''); setNewStatus(t.status) }}>Reply</button>
                      {t.status !== 'closed' && <button onClick={() => updateStatus(t.id, 'closed')}>Close</button>}
                      {t.status === 'open' && <button onClick={() => updateStatus(t.id, 'in_progress')}>In Progress</button>}
                    </td>
                  </tr>
                )) : <tr><td colSpan="8"><Empty text="No support tickets found." /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>

      {selected && (
        <div className="modal-backdrop" role="presentation">
          <article className="profile-modal" role="dialog" style={{ maxWidth: 520 }}>
            <button className="modal-close" onClick={() => { setSelected(null); setReplyText(''); setNewStatus('') }}>×</button>
            <span className="eyebrow">Ticket #{selected.id} · {selected.category}</span>
            <h2 style={{ fontSize: 18 }}>{selected.subject}</h2>
            <div style={{ background: '#fbf9f5', borderRadius: 10, padding: '14px 16px', marginBottom: 16, fontSize: 13 }}>
              <p style={{ margin: '0 0 8px', color: '#6b6458' }}><b>From:</b> {selected.name} ({selected.email})</p>
              <p style={{ margin: 0, color: '#2a2723', lineHeight: 1.6 }}>{selected.message}</p>
            </div>
            {selected.admin_reply && (
              <div style={{ background: '#eef8f2', borderLeft: '3px solid #2e9560', borderRadius: '0 10px 10px 0', padding: '12px 16px', marginBottom: 16, fontSize: 13 }}>
                <p style={{ margin: '0 0 4px', fontSize: 11, fontWeight: 700, color: '#177a47', textTransform: 'uppercase' }}>Previous Reply</p>
                <p style={{ margin: 0 }}>{selected.admin_reply}</p>
              </div>
            )}
            <label style={{ display: 'block', marginBottom: 8, fontWeight: 700, fontSize: 12 }}>Reply</label>
            <textarea value={replyText} onChange={(e) => setReplyText(e.target.value)} rows={4}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13, resize: 'vertical', marginBottom: 12 }}
              placeholder="Type your reply here…" />
            <label style={{ display: 'block', marginBottom: 8, fontWeight: 700, fontSize: 12 }}>Update Status</label>
            <select value={newStatus} onChange={(e) => setNewStatus(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13, marginBottom: 16 }}>
              <option value="open">Open</option>
              <option value="in_progress">In Progress</option>
              <option value="resolved">Resolved</option>
              <option value="closed">Closed</option>
            </select>
            <div className="modal-actions">
              <button className="primary-button" onClick={sendReply} disabled={saving}>{saving ? 'Sending…' : 'Send Reply'}</button>
              <button className="secondary-button" onClick={() => { setSelected(null); setReplyText(''); setNewStatus('') }}>Cancel</button>
            </div>
          </article>
        </div>
      )}
    </section>
  )
}

function AdminShell({ admin, onLogout }) {
  const [page, setPageState] = useState(() => sessionStorage.getItem('admin_page') || 'dashboard')
  const setPage = (newPage) => {
    setPageState(newPage)
    try { sessionStorage.setItem('admin_page', newPage) } catch {}
  }
  const render = () => {
    const props = { adminId: admin.id }
    if (page === 'dashboard') return <Dashboard {...props} />
    if (page === 'drivers' || page === 'passengers') return <UserDirectory {...props} type={page === 'drivers' ? 'driver' : 'passenger'} />
    if (page === 'nfc-orders') return <NFCOrdersAdmin {...props} />
    if (page === 'database') return <DatabaseViewer {...props} />
    if (page === 'settings') return <Settings {...props} />
    if (page === 'withdrawals') return <WithdrawalRequestsAdmin {...props} />
    if (page === 'support') return <SupportTicketsAdmin {...props} />
    return <SimpleResource {...props} kind={page} />
  }
  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <span>T&G</span>
          <div>
            <b>Tap &amp; Go</b>
            <small>ADMIN CONSOLE</small>
          </div>
        </div>
        <nav>
          {navigation.map(([id, label, icon]) => (
            <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>
              <i>{icon}</i>{label}
            </button>
          ))}
        </nav>
        <button className="logout-button" onClick={onLogout}>
          ⇥ Sign out
        </button>
      </aside>
      <main className="admin-content">
        <header className="admin-topbar">
          <div>
            <span className="eyebrow">Signed in as</span>
            <strong>{admin.name}</strong>
          </div>
          <span className="admin-avatar">{admin.name ? admin.name.charAt(0) : 'A'}</span>
        </header>
        <AdminErrorBoundary key={page}>
          {render()}
        </AdminErrorBoundary>
      </main>
    </div>
  )
}

function Admin() {
  const navigate = useNavigate()
  const [admin, setAdminState] = useState(() => {
    try {
      const raw = sessionStorage.getItem('tapgo_admin_session')
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  })

  const setAdmin = (adminData) => {
    setAdminState(adminData)
    try {
      if (adminData) sessionStorage.setItem('tapgo_admin_session', JSON.stringify(adminData))
      else sessionStorage.removeItem('tapgo_admin_session')
    } catch {}
  }

  if (!admin) return <AdminLogin onLogin={(result) => setAdmin(result.admin)} />
  return <AdminShell admin={admin} onLogout={() => { adminRequest('/logout', admin.id, { method: 'POST' }).catch(() => {}); setAdmin(null); try { sessionStorage.clear() } catch {} navigate('/') }} />
}

export default Admin
