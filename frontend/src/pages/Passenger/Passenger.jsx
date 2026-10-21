import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import jsQR from 'jsqr'
import { useNavigate } from '../../routes/navigation.jsx'
import { useAuth, resolveFileUrl, hasValidBankDetails, getDocumentDisplayName, isValidUpi } from '../../context/AuthContext.jsx'
import { useWallet } from '../../context/WalletContext.jsx'
import { useDarkMode } from '../../hooks/useDarkMode.js'
import { RANGE_OPTIONS, formatRelativeTime, vehicleLabel } from './format.js'
import RazorpayAddMoneyModal from '../../components/Payment/RazorpayAddMoneyModal.jsx'
import WithdrawModal from '../../components/Payment/WithdrawModal.jsx'
import NFCCardOrderModal from '../../components/NFC/NFCCardOrderModal.jsx'
import NFCOrderHistoryModal from '../../components/NFC/NFCOrderHistoryModal.jsx'
import DocumentViewerModal from '../../components/Common/DocumentViewerModal.jsx'
import DocumentUploadModal from '../../components/Common/DocumentUploadModal.jsx'
import BankModal from '../../components/Payment/BankModal.jsx'
import './Passenger.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'
function getToken() { try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' } }

const Icon = ({ children, className = '' }) => (
  <span className={`material-symbols-outlined ${className}`} aria-hidden="true">
    {children}
  </span>
)

const QUICK_AMOUNTS = [100, 200, 500, 1000]

// DEMO_TRIP: only used for the "Simulate Scan" camera-unavailable fallback
// button. The real QR path never uses this constant.
const DEMO_TRIP = {
  driver: 'Ramesh Kumar',
  vehicleType: 'Auto',
  vehicleNumber: 'DL 3C AB 4521',
  fare: 58,
}

function PassengerDocCard({ title, path, type = 'Document', userName, onPreview }) {
  const { user } = useAuth()
  const nameToUse = (userName || user?.name || '').trim() || 'User'
  const displayName = getDocumentDisplayName(nameToUse, title)
  const fileUrl = resolveFileUrl(path)
  const cleanPath = (path ? path.split('?')[0].split('#')[0] : '').toLowerCase()
  const isImage = path && (
    cleanPath.endsWith('.png') ||
    cleanPath.endsWith('.jpg') ||
    cleanPath.endsWith('.jpeg') ||
    cleanPath.endsWith('.webp') ||
    cleanPath.endsWith('.gif') ||
    path.startsWith('data:image')
  )

  const handleOpen = (e) => {
    if (onPreview && path) {
      e.preventDefault()
      onPreview({ title, path, type, displayName, userName: nameToUse })
    }
  }

  return (
    <div
      style={{
        background: 'var(--card)',
        border: '1px solid var(--line)',
        borderRadius: 16,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minWidth: 0,
        boxSizing: 'border-box',
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: 'var(--muted)' }}>
            {title}
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 800,
              padding: '2px 8px',
              borderRadius: 99,
              background: path ? 'rgba(23, 122, 71, 0.12)' : 'rgba(253, 211, 77, 0.14)',
              color: path ? '#177a47' : 'var(--yellow)',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            {path ? 'Verified' : 'Missing'}
          </span>
        </div>

        {path ? (
          <div
            style={{
              marginTop: 10,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              minWidth: 0,
              cursor: onPreview ? 'pointer' : 'default',
            }}
            onClick={handleOpen}
          >
            {isImage ? (
              <img
                src={fileUrl}
                alt={title}
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 8,
                  objectFit: 'cover',
                  border: '1px solid var(--line)',
                  flexShrink: 0,
                  background: '#f0ece4',
                }}
              />
            ) : (
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 8,
                  background: '#f0ece4',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <Icon className="text-gray-500">description</Icon>
              </div>
            )}
            <div style={{ minWidth: 0, flex: 1 }}>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: 'var(--text)',
                  display: 'block',
                  wordBreak: 'break-word',
                  lineHeight: 1.35,
                  maxWidth: '100%',
                }}
                title={displayName}
              >
                {displayName}
              </span>
              <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginTop: 3 }}>
                {isImage ? 'Image Document' : 'Document'}
              </span>
            </div>
          </div>
        ) : (
          <span style={{ display: 'block', marginTop: 8, fontSize: 14, fontWeight: 700, color: 'var(--muted)' }}>
            Not uploaded
          </span>
        )}
      </div>

      {path && (
        <a
          href={fileUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleOpen}
          style={{
            marginTop: 12,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            minHeight: 44,
            padding: '10px 14px',
            fontSize: 13,
            fontWeight: 800,
            color: 'var(--text)',
            background: 'var(--bg)',
            border: '1px solid var(--line)',
            borderRadius: 8,
            textDecoration: 'none',
            cursor: 'pointer',
            boxSizing: 'border-box',
            width: '100%',
          }}
        >
          <Icon style={{ fontSize: 17 }}>visibility</Icon> View {type}
        </a>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════════
   SupportTicketModal — Create a new support ticket from the passenger dashboard
   ═══════════════════════════════════════════════════════════════════════════ */
function SupportTicketModal({ user, onClose }) {
  const [form, setFormState] = useState({ name: user?.name || '', email: user?.email || '', phone: user?.phone || '', category: 'technical', priority: 'medium', subject: '', message: '' })
  const set = (k, v) => setFormState(f => ({ ...f, [k]: v }))
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
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#1e1b16', fontSize: 22, cursor: 'pointer', lineHeight: 1 }}>✕</button>
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
                <label key={key} style={{ fontSize: 12, fontWeight: 700, color: '#3a352e' }}>{lbl}<input type={type} value={form[key]} onChange={e => set(key, e.target.value)} placeholder={ph} required style={{ display: 'block', width: '100%', marginTop: 4, padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13, boxSizing: 'border-box' }} /></label>
              ))}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#3a352e' }}>Category
                  <select value={form.category} onChange={e => set('category', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13 }}>
                    <option value="billing">Billing</option><option value="technical">Technical</option><option value="nfc_card">NFC Card</option><option value="account">Account</option><option value="other">Other</option>
                  </select></label>
                <label style={{ fontSize: 12, fontWeight: 700, color: '#3a352e' }}>Priority
                  <select value={form.priority} onChange={e => set('priority', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13 }}>
                    <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option>
                  </select></label>
              </div>
              <label style={{ fontSize: 12, fontWeight: 700, color: '#3a352e' }}>Message
                <textarea value={form.message} onChange={e => set('message', e.target.value)} required rows={4} placeholder="Describe your issue in detail…" style={{ display: 'block', width: '100%', marginTop: 4, padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13, resize: 'vertical', boxSizing: 'border-box' }} /></label>
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

/* ═══════════════════════════════════════════════════════════════════════════
   NFCSecurityModal — Block / Unblock / Report Lost / Request Replacement
   ═══════════════════════════════════════════════════════════════════════════ */
function NFCSecurityModal({ user, onClose }) {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showReplacement, setShowReplacement] = useState(false)
  const [replForm, setReplForm] = useState({ recipient_name: user?.name || '', phone: user?.phone || '', address_line1: '', area: '', city: user?.city || '', state: '', pincode: '' })
  const setRepl = (k, v) => setReplForm(f => ({ ...f, [k]: v }))

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const res = await fetch(`${API_BASE}/api/nfc/my`, { headers: { Authorization: `Bearer ${getToken()}` } })
      const data = await res.json()
      setCards(data.cards || [])
    } catch { setError('Could not load card data.') } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const card = cards[0]  // most recent card

  const doAction = async (path, body = null) => {
    setActionLoading(true); setError(''); setSuccess('')
    try {
      const res = await fetch(`${API_BASE}/api/nfc/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: body ? JSON.stringify(body) : undefined,
      })
      const data = await res.json()
      if (res.ok && data.success) { setSuccess(data.message); await load() }
      else setError(data.detail || 'Action failed.')
    } catch { setError('Service unavailable.') } finally { setActionLoading(false) }
  }

  const handleReplacement = async (e) => {
    e.preventDefault()
    await doAction('my/request-replacement', { ...replForm, card_type: card?.card_type || 'standard_nfc' })
    setShowReplacement(false)
  }

  const STATUS_COLOR = { active: '#2e9560', blocked: '#d6503f', lost: '#f5be24', replaced: '#a39b8e' }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(30,27,22,0.5)', backdropFilter: 'blur(6px)', padding: 16 }}>
      <div style={{ width: '100%', maxWidth: 420, background: '#fff', borderRadius: 20, boxShadow: '0 24px 60px rgba(30,27,22,0.25)', overflow: 'hidden' }}>
        <div style={{ background: '#fdd34d', padding: '18px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div><div style={{ color: '#1e1b16', fontWeight: 800, fontSize: 16 }}>💳 NFC Card Security</div><div style={{ color: '#5e4a10', fontSize: 12 }}>Manage your physical NFC card</div></div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#1e1b16', fontSize: 22, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ padding: '20px', maxHeight: '70vh', overflowY: 'auto' }}>
          {error && <div style={{ padding: '10px 12px', background: '#fdf2f0', border: '1px solid #f1a79d', borderRadius: 10, color: '#c8372d', fontSize: 13, marginBottom: 12 }}>{error}</div>}
          {success && <div style={{ padding: '10px 12px', background: '#eef8f2', border: '1px solid #8fcfa8', borderRadius: 10, color: '#177a47', fontSize: 13, marginBottom: 12 }}>✅ {success}</div>}
          {loading ? <p style={{ textAlign: 'center', color: '#6b6458' }}>Loading card data…</p> : !card ? (
            <p style={{ textAlign: 'center', color: '#6b6458', padding: '20px 0' }}>No NFC card issued to your account yet.<br />Order one from the Home screen.</p>
          ) : (
            <div>
              <div style={{ background: '#fbf9f5', borderRadius: 14, padding: '16px', marginBottom: 16, border: '1px solid #eae4da' }}>
                <div style={{ fontSize: 12, color: '#6b6458', marginBottom: 4 }}>Card Reference</div>
                <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 15, color: '#141210' }}>{card.card_reference}</div>
                <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ padding: '3px 12px', borderRadius: 20, fontSize: 12, fontWeight: 700, background: (STATUS_COLOR[card.status] || '#a39b8e') + '22', color: STATUS_COLOR[card.status] || '#a39b8e' }}>{card.status.toUpperCase()}</span>
                  <span style={{ fontSize: 12, color: '#6b6458' }}>{card.card_type}</span>
                </div>
                {card.blocked_reason && <div style={{ marginTop: 8, fontSize: 12, color: '#6b6458' }}>Reason: {card.blocked_reason}</div>}
              </div>

              {card.status === 'replaced' && <p style={{ fontSize: 13, color: '#6b6458', textAlign: 'center' }}>This card has been replaced. Check your NFC Card History for the new order.</p>}

              {showReplacement ? (
                <form onSubmit={handleReplacement} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ fontWeight: 700, color: '#141210', marginBottom: 4 }}>Replacement Delivery Address</div>
                  {[['Recipient Name', 'recipient_name'], ['Phone', 'phone'], ['Address Line 1', 'address_line1'], ['Area / Locality', 'area'], ['City', 'city'], ['State', 'state'], ['Pincode', 'pincode']].map(([lbl, key]) => (
                    <input key={key} placeholder={lbl} value={replForm[key]} required onChange={e => setRepl(key, e.target.value)}
                      style={{ padding: '9px 12px', borderRadius: 10, border: '1px solid #eae4da', fontSize: 13 }} />
                  ))}
                  <button type="submit" disabled={actionLoading} style={{ padding: 12, background: '#141210', color: '#fdd34d', border: 'none', borderRadius: 10, fontWeight: 700, cursor: 'pointer' }}>
                    {actionLoading ? 'Submitting…' : 'Submit Replacement Request'}
                  </button>
                  <button type="button" onClick={() => setShowReplacement(false)} style={{ padding: 10, background: '#f0ece4', border: 'none', borderRadius: 10, fontWeight: 600, cursor: 'pointer' }}>Cancel</button>
                </form>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {card.status === 'active' && (
                    <><button onClick={() => { if (window.confirm('Block your NFC card? You can unblock it anytime.')) doAction('my/block', { reason: 'Blocked by user from app' }) }} disabled={actionLoading}
                        style={{ padding: 12, background: '#fdf2f0', border: '1px solid #f1a79d', borderRadius: 10, color: '#c8372d', fontWeight: 700, cursor: 'pointer' }}>🔒 Block Card</button>
                      <button onClick={() => { if (window.confirm('Report card as lost? This cannot be undone.')) doAction('my/report-lost') }} disabled={actionLoading}
                        style={{ padding: 12, background: '#fffbeb', border: '1px solid #fdd34d', borderRadius: 10, color: '#6b4d05', fontWeight: 700, cursor: 'pointer' }}>⚠️ Report Lost</button></>
                  )}
                  {card.status === 'blocked' && (
                    <><button onClick={() => doAction('my/unblock')} disabled={actionLoading}
                        style={{ padding: 12, background: '#eef8f2', border: '1px solid #8fcfa8', borderRadius: 10, color: '#177a47', fontWeight: 700, cursor: 'pointer' }}>🔓 Unblock Card</button>
                      <button onClick={() => { if (window.confirm('Report card as lost? This cannot be undone.')) doAction('my/report-lost') }} disabled={actionLoading}
                        style={{ padding: 12, background: '#fffbeb', border: '1px solid #fdd34d', borderRadius: 10, color: '#6b4d05', fontWeight: 700, cursor: 'pointer' }}>⚠️ Report Lost</button></>
                  )}
                  {card.status === 'lost' && (
                    <button onClick={() => setShowReplacement(true)} disabled={actionLoading}
                      style={{ padding: 12, background: '#141210', color: '#fdd34d', border: 'none', borderRadius: 10, fontWeight: 700, cursor: 'pointer' }}>📦 Request Replacement Card</button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Passenger() {
  const navigate = useNavigate()
  const { user, logout, saveProfileToDb, requestAdminAccess, refreshProfile } = useAuth()
  const { balance, isFrozen, transactions, addMoney, withdraw, payFare, refreshWallet } = useWallet()

  const [tab, setTabState] = useState(() => {
    return sessionStorage.getItem('passenger_tab') || 'home'
  })

  const setTab = (newTab) => {
    setTabState(newTab)
    try {
      sessionStorage.setItem('passenger_tab', newTab)
    } catch {
      // Ignore storage error
    }
  }
  const [notice, setNotice] = useState('')
  const [dark, setDark] = useDarkMode()
  const [notifications, setNotifications] = useState(true)
  const [range, setRange] = useState('1M')
  const [amountInput, setAmountInput] = useState('')
  const [editing, setEditing] = useState(false)
  const [requestingBank, setRequestingBank] = useState(false)
  const [requestingDoc, setRequestingDoc] = useState(false)
  const [requestingPhone, setRequestingPhone] = useState(false)

  // Razorpay & Withdrawal Modal State
  const [showRazorpayModal, setShowRazorpayModal] = useState(false)
  const [showWithdrawModal, setShowWithdrawModal] = useState(false)

  // NFC Card Order Modal State
  const [showNFCOrderModal, setShowNFCOrderModal] = useState(false)
  const [showNFCHistoryModal, setShowNFCHistoryModal] = useState(false)
  // New: Support Ticket and NFC Security Modal
  const [showSupportModal, setShowSupportModal] = useState(false)
  const [showNFCSecurityModal, setShowNFCSecurityModal] = useState(false)
  const [previewDoc, setPreviewDoc] = useState(null)
  const [showBankModal, setShowBankModal] = useState(false)
  const [showDocUploadModal, setShowDocUploadModal] = useState(false)

  const [bankForm, setBankForm] = useState({
    bank_account_holder: user?.bank_account_holder || '',
    bank_account_number: user?.bank_account_number || '',
    bank_ifsc: user?.bank_ifsc || '',
    bank_upi_id: user?.bank_upi_id || '',
  })
  const [savingBank, setSavingBank] = useState(false)
  const [bankError, setBankError] = useState('')

  useEffect(() => {
    if (user) {
      setBankForm({
        bank_account_holder: user.bank_account_holder || '',
        bank_account_number: user.bank_account_number || '',
        bank_ifsc: user.bank_ifsc || '',
        bank_upi_id: user.bank_upi_id || '',
      })
    }
  }, [user?.bank_account_holder, user?.bank_account_number, user?.bank_ifsc, user?.bank_upi_id])

  const [form, setForm] = useState({
    name: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    emergency_contact_name: '',
    emergency_contact_phone: '',
    bank_account_holder: '',
    bank_account_number: '',
    bank_ifsc: '',
    bank_upi_id: '',
  })

  const handleUseExistingDetails = () => {
    if (user) {
      setForm({
        name: user.name || '',
        email: user.email || '',
        phone: user.phone || '',
        address: user.address || '',
        city: user.city || '',
        emergency_contact_name: user.emergency_contact_name || '',
        emergency_contact_phone: user.emergency_contact_phone || '',
        bank_account_holder: user.bank_account_holder || '',
        bank_account_number: user.bank_account_number || '',
        bank_ifsc: user.bank_ifsc || '',
        bank_upi_id: user.bank_upi_id || '',
      })
    }
  }

  useEffect(() => {
    if (user?.id) {
      refreshProfile()
    }
  }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const video = useRef(null)
  const canvasRef = useRef(null)
  const stream = useRef(null)
  const rafRef = useRef(null)
  const [cameraError, setCameraError] = useState('')

  // QR payment confirmation state
  const [qrScanResult, setQrScanResult]     = useState(null)   // parsed token string
  const [qrPaymentInfo, setQrPaymentInfo]   = useState(null)   // {driver_name, amount, expires_at, ...}
  const [qrConfirmStep, setQrConfirmStep]   = useState('idle') // idle | loading | confirm | paying | success | error
  const [qrConfirmError, setQrConfirmError] = useState('')
  const [qrConfirmResult, setQrConfirmResult] = useState(null) // {reference, amount}
  const qrScanLockRef = useRef(false)   // prevents duplicate scans of the same frame

  const stopScanner = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
  }

  useEffect(() => {
    if (!user) navigate('/login')
  }, [user, navigate])

  useEffect(() => () => stopScanner(), []) // eslint-disable-line react-hooks/exhaustive-deps

  const flash = (message) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 3200)
  }

  const goHome = () => navigate('/')

  const tickScan = () => {
    const v = video.current
    const canvas = canvasRef.current
    if (v && canvas && v.readyState === v.HAVE_ENOUGH_DATA) {
      canvas.width = v.videoWidth
      canvas.height = v.videoHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(v, 0, 0, canvas.width, canvas.height)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const code = jsQR(imageData.data, imageData.width, imageData.height)
      if (code && code.data && !qrScanLockRef.current) {
        qrScanLockRef.current = true
        handleQrCodeScanned(code.data)
        return   // stop rAF loop; it will restart if scan is dismissed
      }
    }
    rafRef.current = requestAnimationFrame(tickScan)
  }

  /**
   * Called with the raw QR string.
   * Validates it belongs to Tap&Go, extracts the token, and fetches details.
   */
  const handleQrCodeScanned = async (raw) => {
    stopScanner()

    // Validate format: tapgo://pay?token=<TOKEN> or http(s)://.../#/pay?token=<TOKEN>
    let token = null
    try {
      if (raw.startsWith('tapgo://pay?')) {
        token = new URLSearchParams(raw.replace('tapgo://pay?', '')).get('token')
      } else {
        const u = new URL(raw)
        const hash = u.hash // e.g. #/pay?token=...
        const search = hash.includes('?') ? hash.slice(hash.indexOf('?')) : ''
        token = new URLSearchParams(search).get('token')
      }
    } catch { /* not a URL */ }

    if (!token) {
      // Not a Tap&Go QR — ignore and restart scanner
      flash('Not a Tap&Go QR code. Please scan the driver’s terminal.')
      qrScanLockRef.current = false
      rafRef.current = requestAnimationFrame(tickScan)
      return
    }

    setQrScanResult(token)
    setQrConfirmStep('loading')
    setQrConfirmError('')

    try {
      const res = await fetch(
        `${API_BASE}/api/qr/${encodeURIComponent(token)}`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      )
      const data = await res.json()

      if (!res.ok || !data.success) {
        setQrConfirmStep('error')
        setQrConfirmError(data.detail || 'Could not load payment details. QR may be expired.')
        return
      }
      setQrPaymentInfo(data.payment)
      setQrConfirmStep('confirm')
    } catch {
      setQrConfirmStep('error')
      setQrConfirmError('Network error. Please try again.')
    }
  }

  /**
   * Passenger explicitly confirms payment.
   */
  const handleConfirmQrPayment = async () => {
    if (!qrScanResult || qrConfirmStep === 'paying') return
    setQrConfirmStep('paying')
    setQrConfirmError('')

    // Idempotency key: token + passenger id to survive retries
    const idempotencyKey = `qr-${qrScanResult.slice(0, 20)}-${user?.id || 0}`

    try {
      const res = await fetch(
        `${API_BASE}/api/qr/${encodeURIComponent(qrScanResult)}/confirm`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
          body: JSON.stringify({ idempotency_key: idempotencyKey }),
        }
      )
      const data = await res.json()

      if (res.ok && data.success) {
        setQrConfirmResult({
          reference: data.transaction?.reference || '—',
          amount: data.transaction?.amount ?? qrPaymentInfo?.amount,
        })
        setQrConfirmStep('success')
        await refreshWallet?.()
      } else {
        setQrConfirmStep('error')
        setQrConfirmError(data.detail || 'Payment failed. Please try again.')
      }
    } catch {
      setQrConfirmStep('error')
      setQrConfirmError('Network error. Please try again.')
    }
  }

  const dismissQrConfirm = () => {
    setQrScanResult(null)
    setQrPaymentInfo(null)
    setQrConfirmStep('idle')
    setQrConfirmError('')
    setQrConfirmResult(null)
    qrScanLockRef.current = false
    if (tab === 'scan') {
      // Restart scanner
      openScanner()
    }
  }

  const openScanner = async () => {
    setTab('scan')
    setCameraError('')
    qrScanLockRef.current = false
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      })
      if (video.current) {
        video.current.srcObject = stream.current
        await video.current.play()
      }
      rafRef.current = requestAnimationFrame(tickScan)
    } catch {
      setCameraError('Camera permission is needed to scan a QR code.')
    }
  }

  const backFromScanner = () => {
    stopScanner()
    setTab('home')
  }

  /** Legacy fallback: camera unavailable */
  const completeQrPayment = async () => {
    stopScanner()
    flash('Camera unavailable. In a real session, scan the QR with your phone camera.')
    setTab('home')
  }

  const handleTapToPay = () => {
    flash('Tap your card on the driver\u2019s machine to pay.')
  }

  const handleAddMoney = async (amount) => {
    if (!amount || amount <= 0) {
      flash('Please enter a valid top-up amount.')
      return
    }
    const res = await addMoney(amount)
    if (res.success) {
      setAmountInput('')
      flash(res.message || `₹${amount} added to your wallet.`)
    } else {
      flash(res.message || 'Top-up failed.')
    }
  }

  const handleWithdrawSubmit = async (e) => {
    e.preventDefault()
    const num = Number(withdrawAmount)
    if (!num || num <= 0) {
      flash('Enter a valid amount to withdraw.')
      return
    }
    if (num > balance) {
      flash(`Cannot withdraw more than available balance (₹${balance.toFixed(2)}).`)
      return
    }
    if (!hasValidBankDetails(user)) {
      flash('Please save your bank details in Profile first.')
      return
    }
    if (isFrozen) {
      flash('Your wallet is frozen. Withdrawals are disabled.')
      return
    }

    setWithdrawLoading(true)
    const res = await withdraw(num)
    setWithdrawLoading(false)

    if (res.success) {
      setShowWithdrawModal(false)
      setWithdrawAmount('')
      flash(res.message || 'Withdrawal to bank account successful.')
    } else {
      flash(res.message || 'Withdrawal failed.')
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/')
  }

  const rangeMsValue = RANGE_OPTIONS.find((r) => r.key === range)?.ms ?? Infinity
  const filteredTxns = useMemo(
    () => transactions.filter((t) => Date.now() - t.timestamp <= rangeMsValue),
    [transactions, rangeMsValue],
  )

  if (!user) return null
  const recentTxns = transactions.slice(0, 4)
  const initials = (user?.name || 'Passenger')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  const renderTxnRow = (t) => {
    const isCredit = t.raw ? t.raw.is_credit : (t.is_credit !== undefined ? t.is_credit : t.fare < 0)
    const typeText = t.raw ? t.raw.type : (t.type || (isCredit ? 'Deposit' : 'Trip Payment'))
    const descText = t.raw ? t.raw.description : (t.description || (isCredit ? `₹${Math.abs(t.amount || t.fare).toFixed(2)} credited to wallet` : `₹${Math.abs(t.amount || t.fare).toFixed(2)} paid to ${t.driver || 'Driver'}`))
    const balAfter = t.raw ? t.raw.balance_after : (t.balance_after !== undefined ? t.balance_after : null)
    const methodText = t.raw ? t.raw.payment_method : (t.method || t.payment_method || 'WALLET')
    const refText = t.raw ? t.raw.reference : (t.reference || t.id)
    const dateText = t.raw && t.raw.created_at ? new Date(t.raw.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : formatRelativeTime(t.timestamp)

    return (
      <article className="ride" key={t.id || t.reference} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6, padding: '14px 16px', marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <b style={{ fontSize: 15, color: 'var(--text)' }}>{typeText}</b>
            <span style={{ fontSize: 11, fontWeight: 700, marginLeft: 8, padding: '2px 8px', borderRadius: 99, background: isCredit ? '#e2f3e8' : '#fce8e5', color: isCredit ? '#177a47' : '#a52b23' }}>
              {isCredit ? 'CREDIT' : 'DEBIT'}
            </span>
          </div>
          <strong className={isCredit ? 'credit' : ''} style={{ fontSize: 16, color: isCredit ? '#177a47' : 'var(--text)' }}>
            {isCredit ? '+' : '-'}₹{Math.abs(t.amount || t.fare).toFixed(2)}
          </strong>
        </div>

        <div style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 600 }}>
          {descText}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4, pt: 6, borderTop: '1px dashed var(--line)', fontSize: 12 }}>
          <span style={{ fontWeight: 700, color: 'var(--text)' }}>
            Available balance: ₹{balAfter !== null && balAfter !== undefined ? Number(balAfter).toFixed(2) : balance.toFixed(2)}
          </span>
          <span className="muted" style={{ fontSize: 11 }}>
            {refText} &middot; {methodText} &middot; {dateText}
          </span>
        </div>
      </article>
    )
  }

  const home = (
    <>
      <p className="eyebrow">Welcome back</p>
      <h1>Hi, {(user?.name || 'Passenger').split(' ')[0]} 👋</h1>
      <p className="muted">Choose a quick, cashless way to pay your driver.</p>

      <div className="payments">
        <button onClick={handleTapToPay}>
          <Icon>contactless</Icon>
          <b>Tap &amp; Pay</b>
          <small>Tap your card at the driver&apos;s machine</small>
        </button>
        <button onClick={openScanner}>
          <Icon>qr_code_scanner</Icon>
          <b>Scan QR</b>
          <small>Scan your driver&apos;s QR code</small>
        </button>
      </div>

      <div className="wallet-note" style={{ marginBottom: 20 }}>
        <b>
          Wallet balance: ₹{balance.toFixed(2)}{' '}
          <span className="muted" style={{ fontWeight: 500, fontSize: 14 }}>
            · protected by real-time fraud detection
          </span>
        </b>
      </div>

      {!hasValidBankDetails(user) && (
        <div
          className="bank-alert-card"
          style={{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderLeft: '6px solid var(--yellow)',
            borderRadius: 16,
            padding: '16px 20px',
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>🏦</span>
              <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Payout &amp; Refund Setup</span>
            </div>
            <h3 style={{ margin: '2px 0 4px', fontSize: 16, fontWeight: 800, color: 'var(--text, #1e1b16)' }}>Add Your Bank Details</h3>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--muted, #6b6458)' }}>
              Link your bank account and UPI ID to enable seamless refunds and cashouts.
            </p>
          </div>
          <button
            type="button"
            className="primary"
            onClick={() => setShowBankModal(true)}
            style={{
              background: '#FDD34D',
              color: '#1e1b16',
              fontWeight: 800,
              fontSize: 13,
              padding: '12px 22px',
              borderRadius: 12,
              border: 'none',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>Add Bank Details</span>
            <span>&rarr;</span>
          </button>
        </div>
      )}

      {/* NFC Card Ordering Banner */}
      <div style={{
        background: '#fdd34d',
        borderRadius: 18,
        border: 0,
        padding: '20px 24px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 20,
        flexWrap: 'wrap',
        gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{
            width: 46,
            height: 46,
            borderRadius: 12,
            background: '#1e1b16',
            color: '#fdd34d',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            flexShrink: 0,
          }}>💳</div>
          <div>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#5e4a10', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Transit Hardware</span>
            <h3 style={{ margin: '2px 0 4px', fontSize: 19, fontWeight: 800, color: '#1e1b16' }}>Get Your Tap&amp;Go NFC Card</h3>
            <p style={{ margin: 0, fontSize: 13, color: '#5e4a10' }}>Physical NFC smart card (₹50) with location-based shipping</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            onClick={() => setShowNFCHistoryModal(true)}
            style={{
              padding: '10px 18px',
              borderRadius: 12,
              background: '#ffffff',
              border: '1px solid rgba(30, 27, 22, 0.14)',
              color: '#1e1b16',
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            My Orders
          </button>
          <button
            type="button"
            onClick={() => setShowNFCOrderModal(true)}
            style={{
              padding: '10px 20px',
              borderRadius: 12,
              background: '#1e1b16',
              color: '#fdd34d',
              fontSize: 13,
              fontWeight: 800,
              border: 0,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            Order Card (₹50)
          </button>
        </div>
      </div>

      {/* Support & NFC Security Quick Actions */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 24 }}>
        <button
          onClick={() => setShowSupportModal(true)}
          style={{
            padding: '16px 18px',
            background: 'var(--card)',
            borderRadius: 16,
            border: '1px solid var(--line)',
            color: 'var(--text)',
            textAlign: 'left',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            transition: 'all 0.2s ease',
          }}
        >
          <div style={{
            width: 42,
            height: 42,
            borderRadius: 12,
            background: 'var(--yellow)',
            color: '#1e1b16',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            flexShrink: 0,
          }}>🎫</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--text)' }}>Contact Support</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>Submit a ticket</div>
          </div>
        </button>

        <button
          onClick={() => setShowNFCSecurityModal(true)}
          style={{
            padding: '16px 18px',
            background: 'var(--card)',
            borderRadius: 16,
            border: '1px solid var(--line)',
            color: 'var(--text)',
            textAlign: 'left',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            transition: 'all 0.2s ease',
          }}
        >
          <div style={{
            width: 42,
            height: 42,
            borderRadius: 12,
            background: 'var(--yellow)',
            color: '#1e1b16',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            flexShrink: 0,
          }}>🛡️</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, color: 'var(--text)' }}>NFC Card Security</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>Block / report lost</div>
          </div>
        </button>
      </div>

      <h2>Transaction History</h2>
      {transactions.length > 0 ? (
        transactions.slice(0, 5).map(renderTxnRow)
      ) : (
        <p className="muted" style={{ padding: '20px 0', textAlign: 'center' }}>No transactions yet.</p>
      )}
    </>
  )

  const activity = (
    <>
      <h1>Activity</h1>
      <p className="muted">All your rides and wallet transactions</p>
      <div className="ranges">
        {RANGE_OPTIONS.map((option) => (
          <button
            key={option.key}
            className={range === option.key ? 'active' : ''}
            onClick={() => setRange(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {filteredTxns.length ? filteredTxns.map(renderTxnRow) : <p className="muted">No transactions in this range yet.</p>}
    </>
  )

  const wallet = (
    <>
      <h1>My Wallet</h1>
      <p className="muted">Add money or withdraw your Tap&amp;Go balance to bank.</p>
      
      {isFrozen && (
        <div style={{ background: '#fce8e5', border: '1px solid #f1a79d', color: '#a52b23', padding: '12px 16px', borderRadius: 12, marginBottom: 16, fontWeight: 700, fontSize: 14 }}>
          ⚠️ Your wallet is frozen by an administrator. Adding funds and withdrawals are currently disabled.
        </div>
      )}

      <div className="wallet-grid" style={{ marginTop: 20 }}>
        <div className="wallet">
          <span>
            Tap<span>&amp;</span>Go Wallet
          </span>
          <small>Available balance</small>
          <b>₹{balance.toFixed(2)}</b>
          <div className="wallet-actions">
            <button
              className="primary"
              onClick={() => {
                if (isFrozen) {
                  flash('Your wallet is frozen. Adding funds is disabled.')
                  return
                }
                setShowRazorpayModal(true)
              }}
              disabled={isFrozen}
            >
              + Add Money
            </button>
            <button
              className="secondary-btn"
              onClick={() => {
                if (isFrozen) {
                  flash('Your wallet is frozen. Withdrawals are disabled.')
                  return
                }
                setShowWithdrawModal(true)
              }}
            >
              Withdraw to Bank
            </button>
            <button
              className="secondary-btn"
              onClick={() => setShowNFCOrderModal(true)}
              style={{
                background: 'transparent',
                color: '#1e1b16',
                border: '1.5px solid #1e1b16',
                fontWeight: 800,
                transition: 'all 0.2s ease',
              }}
            >
              Order NFC Card (₹50)
            </button>
          </div>
        </div>

        <div className="wallet-note">
          <b>Add money</b>
          <p className="muted" style={{ margin: '0 0 14px' }}>
            Instant wallet top-up backed by MySQL database.
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            {QUICK_AMOUNTS.map((value) => (
              <button
                key={value}
                onClick={() => setAmountInput(String(value))}
                style={{
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  padding: '8px 14px',
                  background: amountInput === String(value) ? 'var(--yellow)' : 'var(--card)',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                ₹{value}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <input
              type="number"
              min="1"
              placeholder="Custom amount"
              value={amountInput}
              onChange={(e) => setAmountInput(e.target.value)}
              style={{
                flex: 1,
                border: '1px solid var(--line)',
                borderRadius: 10,
                padding: '10px 14px',
                background: 'var(--bg)',
                color: 'var(--text)',
                fontSize: 16,
              }}
            />
            <button
              className="primary"
              onClick={() => {
                setShowRazorpayModal(true)
              }}
              disabled={isFrozen}
            >
              Add Funds
            </button>
          </div>
        </div>
      </div>

      {/* Tap&Go Gateway-Neutral Payment Architecture Guide */}
      <div style={{
        marginTop: 28,
        borderRadius: 20,
        background: 'var(--card)',
        border: '1px solid var(--line)',
        padding: '24px 28px',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 20 }}>
          <div style={{
            width: 46,
            height: 46,
            borderRadius: 12,
            background: '#fdd34d',
            color: '#1e1b16',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            flexShrink: 0,
          }}>💳</div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                padding: '3px 12px',
                borderRadius: 20,
                background: 'var(--yellow)',
                border: 0,
                color: '#1e1b16',
                fontSize: 10,
                fontWeight: 900,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
              }}>PAYMENT ARCHITECTURE</span>
            </div>
            <h3 style={{ margin: '4px 0 4px', fontSize: 20, fontWeight: 800, color: 'var(--text)' }}>
              Tap&amp;Go Wallet Payment Workflow
            </h3>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)', lineHeight: 1.5 }}>
              External payment gateways fund the wallet. Normal ride payments move directly from passenger wallet to driver wallet.
            </p>
          </div>
        </div>

        {/* Brand Accent Divider */}
        <div style={{ height: 2, background: 'var(--text)', marginBottom: 20 }} />

        {/* Steps Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 14,
        }}>
          {[
            ['1️⃣ Add Money', 'Payment Gateway → Tap&Go Wallet', 'Fund your passenger wallet using any supported payment gateway.'],
            ['2️⃣ Pay for Ride', 'Passenger Wallet → Driver Wallet', 'Tap NFC card or scan QR. Fares transfer instantly between wallets.'],
            ['3️⃣ Driver Payout', 'Tap&Go Wallet → Supported Withdrawal', 'Drivers withdraw earned wallet funds to their linked account.'],
          ].map(([title, subtitle, desc]) => (
            <div key={title} style={{
              padding: '16px 18px',
              borderRadius: 14,
              border: '1px solid var(--line)',
              background: 'var(--bg)',
              transition: 'all 0.2s ease',
            }}>
              <div style={{ fontWeight: 800, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>{title}</div>
              <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{subtitle}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>

      <h2>Recent transactions</h2>
      {recentTxns.map(renderTxnRow)}
    </>
  )


  const hasBank = hasValidBankDetails(user)
  const isBankApproved = user?.bank_request_status === 'approved'
  const isBankPending = user?.bank_request_status === 'requested'
  const isBankLocked = hasBank && !isBankApproved

  const handleSaveBankDetails = async (e) => {
    e?.preventDefault()
    setBankError('')

    const holder = (bankForm.bank_account_holder !== undefined && bankForm.bank_account_holder !== null && bankForm.bank_account_holder !== '' ? bankForm.bank_account_holder : (user?.bank_account_holder || '')).trim()
    const number = (bankForm.bank_account_number !== undefined && bankForm.bank_account_number !== null && bankForm.bank_account_number !== '' ? bankForm.bank_account_number : (user?.bank_account_number || '')).trim()
    const ifsc = (bankForm.bank_ifsc !== undefined && bankForm.bank_ifsc !== null && bankForm.bank_ifsc !== '' ? bankForm.bank_ifsc : (user?.bank_ifsc || '')).trim().toUpperCase()
    const upi = (bankForm.bank_upi_id !== undefined && bankForm.bank_upi_id !== null && bankForm.bank_upi_id !== '' ? bankForm.bank_upi_id : (user?.bank_upi_id || '')).trim()

    if (!holder) {
      setBankError('Account Holder Name is required.')
      return
    }
    if (holder.length < 2) {
      setBankError('Please enter a valid Account Holder Name.')
      return
    }
    if (!number) {
      setBankError('Bank Account Number is required.')
      return
    }
    if (!/^\d{8,20}$/.test(number)) {
      setBankError('Enter a valid Bank Account Number (8-20 digits).')
      return
    }
    if (!ifsc) {
      setBankError('IFSC Code is required.')
      return
    }
    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc)) {
      setBankError('Enter a valid 11-character IFSC code (e.g. SBIN0001234).')
      return
    }
    if (!upi) {
      setBankError('UPI ID is required.')
      return
    }
    if (!isValidUpi(upi)) {
      setBankError('Enter a valid UPI ID (e.g. name@upi).')
      return
    }

    setSavingBank(true)
    try {
      const payload = {
        bank_account_holder: holder,
        bank_account_number: number,
        bank_ifsc: ifsc,
        bank_upi_id: upi,
      }
      const res = await saveProfileToDb(payload)
      setSavingBank(false)
      if (res.success) {
        await refreshProfile()
        flash('Bank details updated successfully.')
      } else {
        setBankError(res.message || 'Failed to update bank details.')
      }
    } catch {
      setSavingBank(false)
      setBankError('Failed to connect to server. Please try again.')
    }
  }

  const saveProfile = async () => {
    const payload = {
      name: form.name?.trim() ? form.name.trim() : user?.name,
      email: form.email?.trim() ? form.email.trim() : user?.email,
      address: form.address?.trim() ? form.address.trim() : user?.address,
      city: form.city?.trim() ? form.city.trim() : user?.city,
      emergency_contact_name: form.emergency_contact_name?.trim() ? form.emergency_contact_name.trim() : user?.emergency_contact_name,
      emergency_contact_phone: form.emergency_contact_phone?.trim() ? form.emergency_contact_phone.trim() : user?.emergency_contact_phone,
    }

    // Include phone if permission was approved and field was edited
    if (user?.phone_request_status === 'approved' && form.phone && form.phone.trim() !== user?.phone) {
      payload.phone = form.phone.trim()
    }

    // Include bank details if bank was never locked OR permission is approved
    const canEditBank = !isBankLocked || isBankApproved
    if (canEditBank) {
      const bh = bankForm.bank_account_holder?.trim() || form.bank_account_holder?.trim()
      const bn = bankForm.bank_account_number?.trim() || form.bank_account_number?.trim()
      const bi = (bankForm.bank_ifsc?.trim() || form.bank_ifsc?.trim() || '').toUpperCase()
      const bu = bankForm.bank_upi_id?.trim() || form.bank_upi_id?.trim()
      if (bh) payload.bank_account_holder = bh
      if (bn) payload.bank_account_number = bn
      if (bi) payload.bank_ifsc = bi
      if (bu) {
        if (!isValidUpi(bu)) {
          flash('Enter a valid UPI ID (e.g. name@upi).')
          return
        }
        payload.bank_upi_id = bu
      }
    }

    const res = await saveProfileToDb(payload)
    if (res.success) {
      await refreshProfile()
      setEditing(false)
      setForm({
        name: user?.name || '',
        email: user?.email || '',
        phone: user?.phone || '',
        address: user?.address || '',
        city: user?.city || '',
        emergency_contact_name: user?.emergency_contact_name || '',
        emergency_contact_phone: user?.emergency_contact_phone || '',
        bank_account_holder: user?.bank_account_holder || '',
        bank_account_number: user?.bank_account_number || '',
        bank_ifsc: user?.bank_ifsc || '',
        bank_upi_id: user?.bank_upi_id || '',
      })
      flash('Profile updated successfully.')
    } else {
      flash(res.message || 'Failed to save profile.')
    }
  }

  const handleToggleEdit = () => {
    if (editing) {
      saveProfile()
    } else {
      // Pre-fill form with existing user data so partial edits work cleanly
      setForm({
        name: user?.name || '',
        email: user?.email || '',
        phone: user?.phone || '',
        address: user?.address || '',
        city: user?.city || '',
        emergency_contact_name: user?.emergency_contact_name || '',
        emergency_contact_phone: user?.emergency_contact_phone || '',
        bank_account_holder: user?.bank_account_holder || '',
        bank_account_number: user?.bank_account_number || '',
        bank_ifsc: user?.bank_ifsc || '',
        bank_upi_id: user?.bank_upi_id || '',
      })
      setEditing(true)
    }
  }

  const handleAdminPhoneRequest = async () => {
    setRequestingPhone(true)
    const res = await requestAdminAccess('phone')
    setRequestingPhone(false)
    if (res.success) flash('Admin access requested for phone number change.')
    else flash(res.message || 'Request failed.')
  }

  const handleAdminBankRequest = async () => {
    setRequestingBank(true)
    const res = await requestAdminAccess('bank')
    setRequestingBank(false)
    if (res.success) flash('Admin access requested for bank details change.')
    else flash(res.message || 'Request failed.')
  }

  const handleAdminDocRequest = async () => {
    setRequestingDoc(true)
    const res = await requestAdminAccess('documents')
    setRequestingDoc(false)
    if (res.success) flash('Admin access requested for document edit.')
    else flash(res.message || 'Request failed.')
  }

  const profile = (
    <>
      <div className="profile">
        {user?.photoUrl ? (
          <img
            src={user.photoUrl}
            alt=""
            style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover' }}
          />
        ) : (
          <b>{initials}</b>
        )}
        <div>
          <h1>{user?.name || 'Passenger'}</h1>
          <span>Passenger · Tap&amp;Go Account</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 28, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Personal &amp; Contact</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {editing && (
            <>
              <button
                type="button"
                className="secondary-btn"
                style={{ padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer', background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 8 }}
                onClick={handleUseExistingDetails}
              >
                Use existing details
              </button>
              <button
                type="button"
                className="secondary-btn"
                style={{ padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer', background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 8 }}
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </>
          )}
          <button className="back" onClick={handleToggleEdit}>
            {editing ? 'Save changes' : 'Edit details'}
          </button>
        </div>
      </div>

      <div className="field-grid">
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Full Name</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Enter full name" autoComplete="off" /> : <span className="field-value">{user?.name || '—'}</span>}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Mobile Number</span>
            <span className={`field-tag ${user?.phone_request_status === 'approved' ? 'editable' : 'readonly'}`}>
              {user?.phone_request_status === 'approved' ? 'Editable (Approved)' : 'Read-only (Taken from DB)'}
            </span>
          </div>
          {editing && user?.phone_request_status === 'approved' ? (
            <input
              value={form.phone}
              onChange={(e) => setForm(f => ({ ...f, phone: e.target.value }))}
              placeholder="10-digit mobile number"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.phone || '—'}</span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Email</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.email} onChange={(e) => setForm(f => ({ ...f, email: e.target.value }))} placeholder="Enter email address" autoComplete="off" /> : <span className="field-value">{user?.email || '—'}</span>}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Address</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.address} onChange={(e) => setForm(f => ({ ...f, address: e.target.value }))} placeholder="Enter address" autoComplete="off" /> : <span className="field-value">{user?.address || '—'}</span>}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">City</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.city} onChange={(e) => setForm(f => ({ ...f, city: e.target.value }))} placeholder="Enter city" autoComplete="off" /> : <span className="field-value">{user?.city || '—'}</span>}
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        {user?.phone_request_status === 'requested' ? (
          <p className="muted" style={{ fontWeight: 700, color: '#8a6400', margin: '6px 0 0' }}>
            ⏳ Phone number change request submitted to Admin. Awaiting authorization.
          </p>
        ) : user?.phone_request_status === 'approved' ? (
          <p style={{ fontWeight: 700, color: '#177a47', margin: '6px 0 0' }}>
            ✅ Admin approval granted! Click &quot;Edit details&quot; above to change your phone number.
          </p>
        ) : (
          <div>
            {user?.phone_request_status === 'rejected' && (
              <p style={{ fontWeight: 700, color: '#a52b23', margin: '6px 0 6px' }}>
                ❌ Your previous phone change request was rejected by Admin.
              </p>
            )}
            <button
              className="secondary-btn"
              style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)' }}
              disabled={requestingPhone}
              onClick={handleAdminPhoneRequest}
            >
              {requestingPhone ? 'Sending Request...' : 'Request Admin Access to Change Phone Number'}
            </button>
          </div>
        )}
      </div>

      <h2>Emergency Contact</h2>
      <div className="field-grid">
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Contact Name</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.emergency_contact_name} onChange={(e) => setForm(f => ({ ...f, emergency_contact_name: e.target.value }))} placeholder="Parent / Spouse Name" autoComplete="off" /> : <span className="field-value">{user?.emergency_contact_name || '—'}</span>}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Contact Phone</span>
            <span className="field-tag editable">Editable</span>
          </div>
          {editing ? <input value={form.emergency_contact_phone} onChange={(e) => setForm(f => ({ ...f, emergency_contact_phone: e.target.value }))} placeholder="10-digit mobile" autoComplete="off" /> : <span className="field-value">{user?.emergency_contact_phone || '—'}</span>}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 28, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Bank &amp; Refund Details</h2>
        {!hasBank ? (
          <button
            type="button"
            className="secondary-btn"
            style={{
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: 800,
              color: '#1e1b16',
              background: '#FDD34D',
              border: 'none',
              borderRadius: 10,
              cursor: 'pointer',
            }}
            onClick={() => setShowBankModal(true)}
          >
            Add Bank Details
          </button>
        ) : isBankApproved ? (
          <span className="field-tag editable" style={{ background: '#e2f3e8', color: '#177a47' }}>
            Admin Approval Granted
          </span>
        ) : isBankPending ? (
          <span className="field-tag readonly" style={{ background: '#FFF3C4', color: '#8a6400' }}>
            Request Pending Admin Review
          </span>
        ) : user?.bank_request_status === 'rejected' ? (
          <span className="field-tag readonly" style={{ background: '#fce8e5', color: '#a52b23' }}>
            Request Rejected
          </span>
        ) : (
          <span className="field-tag readonly">
            Locked
          </span>
        )}
      </div>

      <div className="field-grid">
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Account Holder</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_account_holder}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_account_holder: e.target.value }))
              }}
              placeholder="Account Holder Name"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_account_holder || '—'}</span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Account Number</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_account_number}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_account_number: e.target.value }))
              }}
              placeholder="Bank Account Number"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">
              {user?.bank_account_number
                ? user.bank_account_number.length > 4
                  ? `XXXX XXXX ${user.bank_account_number.slice(-4)}`
                  : user.bank_account_number
                : '—'}
            </span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">IFSC Code</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_ifsc}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_ifsc: e.target.value.toUpperCase() }))
              }}
              placeholder="IFSC Code (e.g. SBIN0001234)"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_ifsc || '—'}</span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">UPI ID</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_upi_id}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_upi_id: e.target.value }))
              }}
              placeholder="name@upi"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_upi_id || '—'}</span>
          )}
        </div>
      </div>

      {bankError && (
        <div style={{ marginTop: 10, padding: '10px 14px', borderRadius: 10, background: '#fce8e5', color: '#a52b23', fontSize: 13, fontWeight: 600 }}>
          ⚠️ {bankError}
        </div>
      )}

      {hasBank && (
        <div style={{ marginTop: 12 }}>
          {isBankPending ? (
            <p className="muted" style={{ fontWeight: 700, color: '#8a6400', margin: 0 }}>
              ⏳ Bank change request pending admin approval
            </p>
          ) : isBankApproved ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
              <p style={{ fontWeight: 700, color: '#177a47', margin: 0 }}>
                ✓ Admin approval granted
              </p>
              <div>
                <button
                  type="button"
                  className="primary-btn"
                  style={{
                    padding: '10px 24px',
                    fontSize: 14,
                    fontWeight: 800,
                    borderRadius: 10,
                    cursor: savingBank ? 'not-allowed' : 'pointer',
                    opacity: savingBank ? 0.7 : 1,
                  }}
                  disabled={savingBank}
                  onClick={handleSaveBankDetails}
                >
                  {savingBank ? 'Saving Bank Details...' : 'Save Bank Details'}
                </button>
              </div>
            </div>
          ) : (
            <div>
              {user?.bank_request_status === 'rejected' && (
                <p style={{ fontWeight: 700, color: '#a52b23', marginBottom: 6 }}>
                  ❌ Your previous bank edit request was rejected by Admin.
                </p>
              )}
              <button
                type="button"
                className="secondary-btn"
                style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)', marginTop: 4 }}
                disabled={requestingBank}
                onClick={handleAdminBankRequest}
              >
                {requestingBank ? 'Sending Request...' : 'Request Bank Details Change'}
              </button>
            </div>
          )}
        </div>
      )}

      <h2>Uploaded Verification Documents</h2>
      <div className="field-grid">
        <PassengerDocCard title="Profile Photo" path={user?.profile_photo} type="Image" userName={user?.name} onPreview={setPreviewDoc} />
        <PassengerDocCard title="Govt ID / Aadhaar / PAN" path={user?.id_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />
        <PassengerDocCard title="Digital Signature" path={user?.signature_document} type="Signature" userName={user?.name} onPreview={setPreviewDoc} />
        {user?.rc_document && <PassengerDocCard title="RC Book Document" path={user?.rc_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />}
        {user?.licence_document && <PassengerDocCard title="Driving Licence Document" path={user?.licence_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />}
        {user?.insurance_document && <PassengerDocCard title="Insurance Document" path={user?.insurance_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />}
      </div>

      <div style={{ marginTop: 12 }}>
        {user?.doc_request_status === 'requested' ? (
          <p className="muted" style={{ fontWeight: 700, color: '#8a6400' }}>
            ⏳ Document edit request submitted to Admin. Awaiting authorization.
          </p>
        ) : user?.doc_request_status === 'approved' ? (
          <div>
            <p style={{ fontWeight: 700, color: '#177a47', marginBottom: 8 }}>
              ✅ Admin approval granted! You can now upload replacement documents.
            </p>
            <button
              className="secondary-btn"
              style={{ color: '#1e1b16', background: '#FDD34D', border: 'none', fontWeight: 700, borderRadius: 8, padding: '8px 16px', cursor: 'pointer' }}
              onClick={() => setShowDocUploadModal(true)}
            >
              Upload Replacement Document
            </button>
          </div>
        ) : (
          <div>
            {user?.doc_request_status === 'rejected' && (
              <p style={{ fontWeight: 700, color: '#a52b23', marginBottom: 6 }}>
                ❌ Your previous document edit request was rejected by Admin.
              </p>
            )}
            <button
              className="secondary-btn"
              style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)', marginTop: 8 }}
              disabled={requestingDoc}
              onClick={handleAdminDocRequest}
            >
              {requestingDoc ? 'Sending Request...' : 'Request Admin Access to Edit Documents'}
            </button>
          </div>
        )}
      </div>

      <h2>Account Status</h2>
      <div className="field-grid">
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Passenger ID</span>
            <span className="field-tag readonly">Read-only</span>
          </div>
          <span className="field-value">T&amp;G-{user?.id || '—'}</span>
        </div>
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Registration Date</span>
            <span className="field-tag readonly">Read-only</span>
          </div>
          <span className="field-value">
            {user?.created_at
              ? new Date(user.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
              : 'Jul 2026'}
          </span>
        </div>
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Aadhaar Status</span>
            <span className="field-tag readonly">Read-only</span>
          </div>
          <span className="field-value">
            {user?.aadhaar ? `Verified (XXXX XXXX ${user.aadhaar.slice(-4)})` : 'Pending'}
          </span>
        </div>
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">PAN Card</span>
            <span className="field-tag readonly">Read-only</span>
          </div>
          <span className="field-value">{user?.pan || '—'}</span>
        </div>
      </div>

      <h2>Settings</h2>
      <div className="setting">
        <span>
          Notifications
          <small>Ride and payment updates</small>
        </span>
        <button className={notifications ? 'switch on' : 'switch'} onClick={() => setNotifications(!notifications)}>
          <i />
        </button>
      </div>
      <div className="setting">
        <span>
          Dark mode
          <small>Use the darker interface</small>
        </span>
        <button className={dark ? 'switch on' : 'switch'} onClick={() => setDark(!dark)}>
          <i />
        </button>
      </div>

      <button className="signout" onClick={handleLogout}>
        <Icon>logout</Icon>
        Sign Out
      </button>
    </>
  )

  const scan = (
    <>
      <button className="back" onClick={backFromScanner}>
        ← Back to home
      </button>
      <h1>Scan QR code</h1>
      <p className="muted">Point your camera at the driver&apos;s Tap&amp;Go QR code.</p>
      <div className="camera">
        {cameraError ? (
          <div className="hint">{cameraError}</div>
        ) : (
          <video ref={video} autoPlay playsInline muted />
        )}
        <canvas ref={canvasRef} style={{ display: 'none' }} />
        <div className="frame" />
      </div>
      {cameraError && (
        <div style={{ fontSize: 13, color: 'var(--muted)', textAlign: 'center', padding: '8px 0 4px' }}>
          Camera unavailable &mdash; use your phone to scan the QR displayed on the driver’s terminal.
        </div>
      )}

      {/* QR confirmation modal — shown after a successful scan */}
      {qrConfirmStep !== 'idle' && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 300,
          background: 'rgba(30,27,22,0.55)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div style={{
            width: '100%', maxWidth: 380,
            background: '#ffffff', borderRadius: 20,
            border: '1.5px solid #1e1b16',
            boxShadow: '0 24px 60px rgba(30,27,22,0.3)',
            overflow: 'hidden',
          }}>
            {/* Modal header */}
            <div style={{ background: '#fdd34d', borderBottom: '1.5px solid #1e1b16', padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 900, color: '#1e1b16', fontSize: 15 }}>Tap<span style={{ color: '#8a6400' }}>&amp;</span>Go Pay</span>
              {qrConfirmStep !== 'paying' && (
                <button onClick={dismissQrConfirm} style={{ background: 'none', border: 'none', color: '#1e1b16', fontSize: 18, cursor: 'pointer' }}>✕</button>
              )}
            </div>

            <div style={{ padding: '20px 20px 24px', textAlign: 'center' }}>

              {/* Loading */}
              {qrConfirmStep === 'loading' && (
                <div style={{ color: '#6b6458', fontSize: 14, padding: '20px 0' }}>
                  <div style={{ display: 'inline-block', width: 24, height: 24, border: '3px solid #f0ece4', borderTopColor: '#1e1b16', borderRadius: '50%', animation: 'spin 0.7s linear infinite', marginBottom: 10 }} />
                  <div>Loading payment details…</div>
                </div>
              )}

              {/* Confirm */}
              {qrConfirmStep === 'confirm' && qrPaymentInfo && (
                <>
                  <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#6b6458', marginBottom: 6 }}>Confirm Payment</div>
                  <div style={{ fontFamily: 'var(--tg-font-display)', fontSize: 44, fontWeight: 800, color: '#1e1b16', letterSpacing: '-0.03em', marginBottom: 4 }}>
                    ₹{Number(qrPaymentInfo.amount).toFixed(2)}
                  </div>
                  <div style={{ fontSize: 14, color: '#6b6458', marginBottom: 4 }}>to <strong style={{ color: '#1e1b16' }}>{qrPaymentInfo.driver_name}</strong></div>
                  {qrPaymentInfo.remaining_seconds > 0 && (
                    <div style={{ fontSize: 12, color: '#6b6458', marginBottom: 16 }}>QR valid for {qrPaymentInfo.remaining_seconds}s</div>
                  )}
                  <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                    <button
                      onClick={dismissQrConfirm}
                      style={{ flex: 1, padding: '13px', background: '#ffffff', border: '1.5px solid #dcd4c6', borderRadius: 12, color: '#1e1b16', fontWeight: 700, cursor: 'pointer', fontSize: 14 }}
                    >Cancel</button>
                    <button
                      id="qr-confirm-pay-btn"
                      onClick={handleConfirmQrPayment}
                      style={{ flex: 2, padding: '13px', background: '#fdd34d', border: 0, borderRadius: 12, color: '#141210', fontWeight: 800, cursor: 'pointer', fontSize: 15 }}
                    >
                      Pay ₹{Number(qrPaymentInfo.amount).toFixed(2)}
                    </button>
                  </div>
                </>
              )}

              {/* Paying */}
              {qrConfirmStep === 'paying' && (
                <div style={{ color: '#6b6458', fontSize: 14, padding: '20px 0' }}>
                  <div style={{ display: 'inline-block', width: 24, height: 24, border: '3px solid #f0ece4', borderTopColor: '#1e1b16', borderRadius: '50%', animation: 'spin 0.7s linear infinite', marginBottom: 10 }} />
                  <div>Processing payment…</div>
                </div>
              )}

              {/* Success */}
              {qrConfirmStep === 'success' && qrConfirmResult && (
                <>
                  <div style={{ fontSize: 52, marginBottom: 8 }}>✅</div>
                  <div style={{ fontSize: 16, fontWeight: 900, color: '#177a47', marginBottom: 4 }}>Payment Successful!</div>
                  <div style={{ fontFamily: 'var(--tg-font-display)', fontSize: 36, fontWeight: 800, color: '#1e1b16', letterSpacing: '-0.03em', marginBottom: 4 }}>₹{Number(qrConfirmResult.amount).toFixed(2)}</div>
                  <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#4e483f', background: '#f0ece4', padding: '4px 12px', borderRadius: 6, marginBottom: 18 }}>{qrConfirmResult.reference}</div>
                  <button
                    onClick={() => { dismissQrConfirm(); setTab('home') }}
                    style={{ width: '100%', padding: '13px', background: '#fdd34d', border: 0, borderRadius: 12, color: '#141210', fontWeight: 800, cursor: 'pointer', fontSize: 15 }}
                  >Done</button>
                </>
              )}

              {/* Error */}
              {qrConfirmStep === 'error' && (
                <>
                  <div style={{ fontSize: 42, marginBottom: 8 }}>⚠️</div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: '#c8372d', marginBottom: 8 }}>Payment Failed</div>
                  <div style={{ fontSize: 13, color: '#6b6458', marginBottom: 18 }}>{qrConfirmError}</div>
                  <button
                    onClick={dismissQrConfirm}
                    style={{ width: '100%', padding: '13px', background: '#ffffff', border: '1.5px solid #1e1b16', borderRadius: 12, color: '#1e1b16', fontWeight: 700, cursor: 'pointer', fontSize: 14 }}
                  >Try Again</button>
                </>
              )}

            </div>
          </div>
        </div>
      )}
    </>
  )

  const screen =
    tab === 'activity' ? activity : tab === 'wallet' ? wallet : tab === 'profile' ? profile : tab === 'scan' ? scan : home

  return (
    <div className="passenger">
      <header>
        <button className="logo" onClick={goHome} aria-label="Tap&Go home">
          Tap<span>&amp;</span>Go
        </button>
        <div className="header-actions">
          <button className="icon-btn" onClick={() => setTab('profile')} aria-label="Profile">
            {user?.photoUrl ? (
              <img
                src={user.photoUrl}
                alt=""
                style={{ width: 39, height: 39, borderRadius: '50%', objectFit: 'cover' }}
              />
            ) : (
              <span className="user">{initials}</span>
            )}
          </button>
        </div>
      </header>

      <main>{screen}</main>





      {showRazorpayModal && (
        <RazorpayAddMoneyModal
          user={user}
          onClose={() => setShowRazorpayModal(false)}
          onSuccess={async (newBalance) => {
            setShowRazorpayModal(false)
            flash(`Wallet credited successfully! Current Balance: ₹${Number(newBalance || 0).toFixed(2)}`)
            await refreshWallet?.(newBalance)
          }}
          onFailure={(errMsg) => {
            setShowRazorpayModal(false)
            if (errMsg) flash(errMsg)
          }}
        />
      )}

      {showWithdrawModal && (
        <WithdrawModal
          user={user}
          balance={balance}
          onClose={() => setShowWithdrawModal(false)}
          onSuccess={async () => {
            flash('Withdrawal request submitted successfully.')
            await refreshWallet?.()
          }}
        />
      )}

      {showNFCOrderModal && (
        <NFCCardOrderModal
          user={user}
          onClose={() => setShowNFCOrderModal(false)}
          onOrderSuccess={() => {
            flash('NFC Card order created!')
          }}
        />
      )}

      {showNFCHistoryModal && (
        <NFCOrderHistoryModal
          user={user}
          onClose={() => setShowNFCHistoryModal(false)}
          onOrderAgain={() => setShowNFCOrderModal(true)}
        />
      )}

      {showSupportModal && (
        <SupportTicketModal user={user} onClose={() => setShowSupportModal(false)} />
      )}

      {showNFCSecurityModal && (
        <NFCSecurityModal user={user} onClose={() => setShowNFCSecurityModal(false)} />
      )}

      {previewDoc && (
        <DocumentViewerModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}

      {showBankModal && (
        <BankModal
          onClose={() => setShowBankModal(false)}
          flash={flash}
          title="Bank & Refund Details"
        />
      )}

      {showDocUploadModal && (
        <DocumentUploadModal
          accountType="passenger"
          onClose={() => setShowDocUploadModal(false)}
          flash={flash}
        />
      )}

      {notice && <div className="toast">✓ {notice}</div>}

      <nav>
        {[
          ['home', 'home', 'Home'],
          ['activity', 'receipt_long', 'Activity'],
          ['wallet', 'account_balance_wallet', 'Wallet'],
          ['profile', 'person', 'Profile'],
        ].map(([key, icon, label]) => (
          <button className={tab === key ? 'active' : ''} onClick={() => setTab(key)} key={key}>
            <Icon>{icon}</Icon>
            {label}
          </button>
        ))}
      </nav>
    </div>
  )
}

export default Passenger
