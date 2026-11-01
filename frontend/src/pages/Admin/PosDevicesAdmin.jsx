import { useEffect, useState } from 'react'
import { adminRequest } from './api.js'
import { Empty, LoadState } from './adminUi.jsx'
import { date, number } from './adminFormat.js'

export default function PosDevicesAdmin({ adminId }) {
  const [result, setResult] = useState({ items: [], total: 0 })
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [form, setForm] = useState({ device_id: '', label: '', vehicle_ref: '', driver_id: '' })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    const params = new URLSearchParams()
    if (status) params.set('status', status)
    if (search.trim()) params.set('search', search.trim())
    setLoading(true)
    adminRequest(`/pos-devices${params.toString() ? `?${params}` : ''}`, adminId)
      .then((data) => { setResult(data || { items: [], total: 0 }); setError('') })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [adminId, status])

  const send = async (path, method, body, done) => {
    setError(''); setNotice('')
    try { await adminRequest(path, adminId, { method, body: body ? JSON.stringify(body) : undefined }); setNotice(done); load(); return true }
    catch (err) { setError(err.message); return false }
  }

  const register = async (event) => {
    event.preventDefault()
    const body = { device_id: form.device_id.trim() }
    if (form.label.trim()) body.label = form.label.trim()
    if (form.vehicle_ref.trim()) body.vehicle_ref = form.vehicle_ref.trim()
    if (form.driver_id.trim()) body.driver_id = Number(form.driver_id)
    if (await send('/pos-devices', 'POST', body, `Device ${body.device_id} registered.`)) setForm({ device_id: '', label: '', vehicle_ref: '', driver_id: '' })
  }

  const assign = (device) => {
    const value = window.prompt(`Driver user ID for ${device.device_id} (leave empty to unassign):`, device.driver_id || '')
    if (value === null) return
    const trimmed = value.trim()
    if (trimmed && !/^\d+$/.test(trimmed)) { setError('The driver ID must be a number (see Driver Management).'); return }
    send(`/pos-devices/${device.id}/assign`, 'POST', { driver_id: trimmed ? Number(trimmed) : null }, trimmed ? `Driver assigned to ${device.device_id}.` : `Driver unassigned from ${device.device_id}.`)
  }

  const assignVehicle = (device) => {
    const value = window.prompt(`Vehicle (registration or label) for ${device.device_id} (leave empty to unassign):`, device.vehicle_ref || '')
    if (value === null) return
    send(`/pos-devices/${device.id}/assign`, 'POST', { vehicle_ref: value.trim() || null }, `Vehicle updated for ${device.device_id}.`)
  }

  const toggle = (device) => {
    const disabling = device.status === 'active'
    if (disabling && !window.confirm(`Disable ${device.device_id}? It is rejected only when device enforcement is switched on for the server.`)) return
    send(`/pos-devices/${device.id}/${disabling ? 'disable' : 'enable'}`, 'POST', null, `${device.device_id} ${disabling ? 'disabled' : 'enabled'}.`)
  }

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value })
  const rows = result.items || []
  return (
    <section className="admin-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Payment terminals</span>
          <h2>POS Devices</h2>
          <p>Register terminals, assign them to a driver and vehicle, and disable a lost or faulty device.</p>
        </div>
      </div>

      <form className="table-controls" onSubmit={register}>
        <input value={form.device_id} onChange={set('device_id')} placeholder="Device ID (e.g. POS-001)" required style={{ maxWidth: 190 }} />
        <input value={form.label} onChange={set('label')} placeholder="Label (optional)" style={{ maxWidth: 190 }} />
        <input value={form.vehicle_ref} onChange={set('vehicle_ref')} placeholder="Vehicle (optional)" style={{ maxWidth: 170 }} />
        <input type="number" min="1" value={form.driver_id} onChange={set('driver_id')} placeholder="Driver ID (optional)" style={{ maxWidth: 170 }} />
        <button className="primary-button" type="submit">Register device</button>
      </form>

      {notice && <p style={{ color: '#1f7a45', fontSize: 13, fontWeight: 700 }}>{notice}</p>}
      <div className="table-controls">
        <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && load()} placeholder="Search device ID, label or vehicle" />
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Device status">
          <option value="">All devices</option><option value="active">Active</option><option value="disabled">Disabled</option>
        </select>
        <button className="secondary-button" onClick={load}>Search</button>
        <span className="record-count">{number(result.total)} devices</span>
      </div>
      <LoadState error={error}>
        {loading ? <Empty text="Loading POS devices…" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Device</th><th>Status</th><th>Driver</th><th>Vehicle</th><th>Last seen</th><th>Firmware</th><th>Battery</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.length ? rows.map((device) => (
                  <tr key={device.id}>
                    <td><strong>{device.device_id}</strong>{device.label && <small style={{ display: 'block' }}>{device.label}</small>}</td>
                    <td><span className={`status status-${device.status === 'disabled' ? 'suspended' : 'active'}`}>{device.status}</span></td>
                    <td>{device.driver_name ? <>{device.driver_name}<small style={{ display: 'block' }}>#{device.driver_id}</small></> : '—'}</td>
                    <td>{device.vehicle_ref || '—'}</td>
                    <td>{device.last_seen_at ? date(device.last_seen_at) : 'Never'}</td>
                    <td>{device.firmware_version || '—'}</td>
                    <td>{device.battery_pct == null ? '—' : `${device.battery_pct}%`}</td>
                    <td className="actions">
                      <button onClick={() => assign(device)}>{device.driver_id ? 'Change driver' : 'Assign driver'}</button>
                      <button onClick={() => assignVehicle(device)}>Vehicle</button>
                      <button onClick={() => toggle(device)}>{device.status === 'active' ? 'Disable' : 'Enable'}</button>
                    </td>
                  </tr>
                )) : <tr><td colSpan="8"><Empty text="No POS devices registered yet." /></td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </section>
  )
}
