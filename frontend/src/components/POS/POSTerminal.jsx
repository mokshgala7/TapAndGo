/**
 * POSTerminal.jsx
 * Browser-based POS terminal simulation for Tap&Go.
 *
 * Screen flow:
 *   ENTER_FARE  →  SELECT_METHOD  →  QR_SCREEN  →  SUCCESS / FAILED
 *
 * QR Screen behaviour:
 *   - Creates a 120-second server-side payment request for the authenticated driver.
 *   - Generates and displays a QR code from the returned payment URL.
 *   - Counts down from 02:00. Auto-refreshes with a NEW request when expired.
 *   - Polls /api/qr/{token}/status every 2.5 s for payment completion.
 *   - Stops rotation and shows SUCCESS once the backend confirms payment.
 *   - Driver can cancel at any time (calls /api/qr/{token}/cancel).
 *
 * Security:
 *   - All amounts and driver associations are validated server-side.
 *   - Payment URL contains only the opaque token, no sensitive data.
 *   - Uses the authenticated driver bearer token for every API call.
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import QRCode from 'qrcode'
import './POSTerminal.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'
const QR_EXPIRY_SECONDS = 120
const POLL_INTERVAL_MS = 2500

function getToken() {
  try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' }
}

function authHeaders(extra = {}) {
  const tok = getToken()
  return tok ? { ...extra, Authorization: `Bearer ${tok}` } : extra
}

/** Format seconds as MM:SS */
function fmtCountdown(s) {
  const m = Math.floor(Math.max(0, s) / 60)
  const sec = Math.max(0, s) % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

const KEYPAD = ['1','2','3','4','5','6','7','8','9','C','0','DEL']

export default function POSTerminal({ driver, onClose }) {
  // ── Screen ───────────────────────────────────────────────────────────────
  // 'fare' | 'method' | 'qr' | 'success' | 'failed'
  const [screen, setScreen] = useState('fare')

  // ── Fare entry ───────────────────────────────────────────────────────────
  const [fareInput, setFareInput] = useState('')
  const [fareError, setFareError] = useState('')

  // ── QR payment state ─────────────────────────────────────────────────────
  const [qrRequest, setQrRequest]   = useState(null)   // {token, amount, expires_at, ...}
  const [qrDataUrl, setQrDataUrl]   = useState('')
  const [payStatus, setPayStatus]   = useState('Pending')  // Pending|Completed|Expired|Failed|Cancelled
  const [countdown, setCountdown]   = useState(QR_EXPIRY_SECONDS)
  const [successTxn, setSuccessTxn] = useState(null)
  const [qrLoading, setQrLoading]   = useState(false)
  const [qrError, setQrError]       = useState('')

  // ── Refs for cleanup ─────────────────────────────────────────────────────
  const pollTimerRef    = useRef(null)
  const countdownRef    = useRef(null)
  const rotateRef       = useRef(null)      // timer for next QR generation
  const mountedRef      = useRef(true)
  const activeTokenRef  = useRef(null)      // currently displayed token
  const generatingRef   = useRef(false)     // prevents overlapping creates

  // Clean up all timers on unmount
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearAllTimers()
    }
  }, [])

  function clearAllTimers() {
    if (pollTimerRef.current)    clearInterval(pollTimerRef.current)
    if (countdownRef.current)    clearInterval(countdownRef.current)
    if (rotateRef.current)       clearTimeout(rotateRef.current)
    pollTimerRef.current = null
    countdownRef.current = null
    rotateRef.current    = null
  }

  // ── Fare entry logic ─────────────────────────────────────────────────────
  function handleKey(key) {
    setFareError('')
    if (key === 'C') { setFareInput(''); return }
    if (key === 'DEL') { setFareInput(prev => prev.slice(0, -1)); return }
    if (key === '.') {
      if (fareInput.includes('.')) return
      setFareInput(prev => (prev === '' ? '0.' : prev + '.'))
      return
    }
    // Prevent more than 2 decimal places
    const dot = fareInput.indexOf('.')
    if (dot !== -1 && fareInput.length - dot > 2) return
    // Prevent leading zeros
    if (fareInput === '0' && key !== '.') { setFareInput(key); return }
    // Limit total length
    if (fareInput.replace('.', '').length >= 7) return
    setFareInput(prev => prev + key)
  }

  function validateFare() {
    const n = parseFloat(fareInput)
    if (!fareInput || isNaN(n)) { setFareError('Please enter a valid amount.'); return false }
    if (n <= 0) { setFareError('Amount must be greater than ₹0.'); return false }
    if (n > 50000) { setFareError('Amount cannot exceed ₹50,000.'); return false }
    const parts = fareInput.split('.')
    if (parts[1] && parts[1].length > 2) { setFareError('At most 2 decimal places allowed.'); return false }
    return true
  }

  function handleContinue() {
    if (validateFare()) setScreen('method')
  }

  // ── QR creation ──────────────────────────────────────────────────────────
  const createQRRequest = useCallback(async (fareAmount) => {
    if (generatingRef.current) return
    generatingRef.current = true
    setQrLoading(true)
    setQrError('')

    try {
      const res = await fetch(`${API_BASE}/api/qr/create-request`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ amount: fareAmount }),
      })
      const data = await res.json()

      if (!mountedRef.current) return
      if (!res.ok || !data.success) {
        setQrError(data.detail || data.message || 'Could not create payment request.')
        setQrLoading(false)
        generatingRef.current = false
        return
      }

      // Generate QR code from the payment URL
      // Use LAN-accessible URL so phones on the same WiFi can open it
      const paymentUrl = buildPaymentUrl(data.token)
      const canvas = document.createElement('canvas')
      await QRCode.toCanvas(canvas, paymentUrl, {
        width: 176,
        margin: 1,
        color: { dark: '#141210', light: '#ffffff' },
        errorCorrectionLevel: 'M',
      })
      const dataUrl = canvas.toDataURL()

      if (!mountedRef.current) return

      // Cancel any previous token on the server
      if (activeTokenRef.current && activeTokenRef.current !== data.token) {
        cancelQRSilently(activeTokenRef.current).catch(() => {})
      }

      activeTokenRef.current = data.token
      setQrRequest(data)
      setQrDataUrl(dataUrl)
      setPayStatus('Pending')
      setCountdown(QR_EXPIRY_SECONDS)
      setQrLoading(false)
      generatingRef.current = false

      // Start countdown and polling
      startCountdown(data.token, fareAmount)
      startPolling(data.token)

    } catch (err) {
      if (!mountedRef.current) return
      setQrError('Network error. Please try again.')
      setQrLoading(false)
      generatingRef.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  /** Build the URL passengers scan — points to this frontend's QR confirm page */
  function buildPaymentUrl(token) {
    // Use same origin so phone on LAN with the LAN IP works too
    const origin = window.location.origin
    return `${origin}/#/pay?token=${encodeURIComponent(token)}`
  }

  /** Cancel a QR request silently (fire-and-forget, best effort) */
  async function cancelQRSilently(token) {
    try {
      await fetch(`${API_BASE}/api/qr/${encodeURIComponent(token)}/cancel`, {
        method: 'POST',
        headers: authHeaders(),
      })
    } catch { /* ignore */ }
  }

  // ── Countdown timer ───────────────────────────────────────────────────────
  function startCountdown(token, fareAmount) {
    if (countdownRef.current) clearInterval(countdownRef.current)
    let remaining = QR_EXPIRY_SECONDS

    countdownRef.current = setInterval(() => {
      if (!mountedRef.current) { clearInterval(countdownRef.current); return }
      remaining -= 1
      setCountdown(remaining)

      if (remaining <= 0) {
        clearInterval(countdownRef.current)
        countdownRef.current = null
        // Auto-rotate: generate a new QR for the same amount
        if (mountedRef.current && payStatus !== 'Completed') {
          setPayStatus(s => s === 'Pending' || s === 'Expired' ? 'Expired' : s)
          if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null }
          // Small delay so the "Expired" state is visible before refresh
          rotateRef.current = setTimeout(() => {
            if (!mountedRef.current) return
            setQrError('')
            createQRRequest(fareAmount)
          }, 1800)
        }
      }
    }, 1000)
  }

  // ── Status polling ────────────────────────────────────────────────────────
  function startPolling(token) {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current)

    pollTimerRef.current = setInterval(async () => {
      if (!mountedRef.current) { clearInterval(pollTimerRef.current); return }
      // Don't poll if this token is no longer the active one
      if (activeTokenRef.current !== token) { clearInterval(pollTimerRef.current); return }

      try {
        const res = await fetch(
          `${API_BASE}/api/qr/${encodeURIComponent(token)}/status`,
          { headers: authHeaders() }
        )
        const data = await res.json()
        if (!mountedRef.current || activeTokenRef.current !== token) return

        const status = data.status || 'Pending'
        setPayStatus(status)

        if (status === 'Completed') {
          clearAllTimers()
          setSuccessTxn({
            reference: data.transaction_reference || '—',
            amount: data.amount,
          })
          setScreen('success')
        } else if (status === 'Expired' || status === 'Cancelled' || status === 'Failed') {
          clearInterval(pollTimerRef.current)
          pollTimerRef.current = null
        }
      } catch { /* network hiccup — retry next interval */ }
    }, POLL_INTERVAL_MS)
  }

  // ── Select QR method ──────────────────────────────────────────────────────
  function handleSelectQR() {
    const fare = parseFloat(fareInput)
    clearAllTimers()
    generatingRef.current = false
    setQrRequest(null)
    setQrDataUrl('')
    setPayStatus('Pending')
    setSuccessTxn(null)
    setQrError('')
    setScreen('qr')
    createQRRequest(fare)
  }

  // ── Cancel QR and go back ─────────────────────────────────────────────────
  function handleCancelQR() {
    clearAllTimers()
    if (activeTokenRef.current) {
      cancelQRSilently(activeTokenRef.current)
      activeTokenRef.current = null
    }
    generatingRef.current = false
    setQrRequest(null)
    setQrDataUrl('')
    setPayStatus('Pending')
    setQrError('')
    setScreen('method')
  }

  // ── Close terminal ────────────────────────────────────────────────────────
  function handleClose() {
    clearAllTimers()
    if (activeTokenRef.current && payStatus === 'Pending') {
      cancelQRSilently(activeTokenRef.current)
    }
    activeTokenRef.current = null
    onClose?.()
  }

  // ── Derived values ────────────────────────────────────────────────────────
  const fareDisplay = fareInput || '0.00'
  const fareNum = parseFloat(fareInput) || 0
  const pct = (countdown / QR_EXPIRY_SECONDS) * 100
  const isUrgent = countdown <= 20
  const driverInitials = (driver?.name || 'DR').split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="pos-overlay" onClick={e => { if (e.target === e.currentTarget) handleClose() }}>
      <div className="pos-terminal" role="dialog" aria-modal="true" aria-label="POS Payment Terminal">

        {/* Header */}
        <div className="pos-header">
          <span className="pos-brand">Tap<span>&</span>Go</span>
          <span className="pos-badge">POS TERMINAL</span>
          <button className="pos-close-btn" onClick={handleClose} aria-label="Close POS terminal">✕</button>
        </div>

        {/* Driver identity strip */}
        <div className="pos-driver-strip">
          <div className="pos-driver-avatar">{driverInitials}</div>
          <span>
            <strong style={{ color: '#1e1b16' }}>{driver?.name || 'Driver'}</strong>
            <span style={{ color: '#6b6458', marginLeft: 6 }}>· Active Terminal</span>
          </span>
        </div>

        {/* Body */}
        <div className="pos-body">

          {/* ─ Screen: ENTER FARE ─ */}
          {screen === 'fare' && (
            <>
              <div className="pos-fare-display">
                <div className="pos-fare-label">Enter Fare Amount</div>
                <div className={`pos-fare-amount ${!fareInput ? 'empty-amount' : ''}`}>
                  <span className="pos-currency">₹</span>
                  <span>{fareInput || '0.00'}</span>
                </div>
                <div className="pos-fare-error">{fareError}</div>
              </div>

              <div className="pos-keypad">
                {KEYPAD.map(k => (
                  <button
                    key={k}
                    className={`pos-key${k === 'C' ? ' pos-key-clear' : k === 'DEL' ? ' pos-key-del' : ''}`}
                    onClick={() => handleKey(k)}
                    aria-label={k === 'DEL' ? 'Delete last digit' : k === 'C' ? 'Clear' : k}
                  >
                    {k === 'DEL' ? '⌫' : k}
                  </button>
                ))}
              </div>

              <button
                className="pos-continue-btn"
                onClick={handleContinue}
                disabled={!fareInput || fareNum <= 0}
                id="pos-continue-btn"
              >
                Continue → ₹{fareNum > 0 ? fareNum.toFixed(2) : '0.00'}
              </button>
            </>
          )}

          {/* ─ Screen: SELECT METHOD ─ */}
          {screen === 'method' && (
            <>
              <div className="pos-method-title">Payment Method</div>
              <div className="pos-method-amount">₹{fareNum.toFixed(2)}</div>

              <div className="pos-method-grid">
                <button
                  className="pos-method-btn method-qr"
                  onClick={handleSelectQR}
                  id="pos-select-qr-btn"
                  aria-label="Select QR payment"
                >
                  <span className="method-icon">📱</span>
                  <span className="method-label">QR Payment</span>
                  <span className="method-sub">Passenger scans QR</span>
                </button>

                <button
                  className="pos-method-btn method-nfc"
                  disabled
                  aria-label="NFC tap payment (hardware not connected)"
                  title="Physical NFC hardware required"
                >
                  <span className="method-icon">🔷</span>
                  <span className="method-label">Tap &amp; NFC</span>
                  <span className="method-sub">Hardware not connected</span>
                </button>
              </div>

              <div className="pos-nfc-notice">
                NFC card payments require the physical DWIN terminal (ESP32). Integration pending.
              </div>

              <button
                className="pos-back-btn"
                onClick={() => setScreen('fare')}
                style={{ marginTop: 12 }}
              >
                ← Back to fare entry
              </button>
            </>
          )}

          {/* ─ Screen: QR PAYMENT ─ */}
          {screen === 'qr' && (
            <div className="pos-qr-screen">
              <div className="pos-qr-meta" style={{ width: '100%' }}>
                <div className="pos-qr-label">Scan to Pay</div>
                <div className="pos-qr-amount">₹{fareNum.toFixed(2)}</div>
                <div className="pos-qr-driver">{driver?.name || 'Driver'}</div>
              </div>

              {/* Status badge */}
              {payStatus === 'Pending' && (
                <div className="pos-status-badge status-pending">
                  <span className="pos-spinner" />
                  Waiting for payment…
                </div>
              )}
              {payStatus === 'Expired' && (
                <div className="pos-status-badge status-expired">⏰ QR Expired — refreshing…</div>
              )}
              {payStatus === 'Failed' && (
                <div className="pos-status-badge status-failed">✕ Payment Failed — try again</div>
              )}
              {payStatus === 'Cancelled' && (
                <div className="pos-status-badge status-cancelled">Payment Cancelled</div>
              )}

              {/* QR code display */}
              {qrLoading ? (
                <div className="pos-loading">
                  <span className="pos-spinner" />
                  Generating secure QR…
                </div>
              ) : qrError ? (
                <div className="pos-loading" style={{ color: '#c8372d' }}>
                  ⚠ {qrError}
                  <br />
                  <button
                    className="pos-continue-btn"
                    style={{ marginTop: 10, fontSize: 13 }}
                    onClick={() => { setQrError(''); createQRRequest(fareNum) }}
                  >
                    Retry
                  </button>
                </div>
              ) : qrDataUrl ? (
                <div className="pos-qr-box" aria-label="QR code for payment">
                  <img src={qrDataUrl} alt="Payment QR code" width={176} height={176} />
                </div>
              ) : null}

              {/* Countdown */}
              {!qrLoading && !qrError && qrRequest && (
                <>
                  <div className={`pos-countdown ${isUrgent ? 'urgent' : ''}`}
                    style={{ color: isUrgent ? '#c8372d' : '#1e1b16' }}
                    aria-label={`${countdown} seconds remaining`}
                  >
                    {fmtCountdown(countdown)}
                  </div>
                  <div className="pos-countdown-bar-wrap" style={{ width: '100%' }}>
                    <div
                      className={`pos-countdown-bar ${isUrgent ? 'bar-urgent' : ''}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </>
              )}

              {/* Cancel button */}
              <button
                className="pos-back-btn"
                onClick={handleCancelQR}
                id="pos-cancel-qr-btn"
              >
                ✕ Cancel QR Payment
              </button>
            </div>
          )}

          {/* ─ Screen: SUCCESS ─ */}
          {screen === 'success' && (
            <div className="pos-success-screen">
              <span className="pos-success-icon">✅</span>
              <div style={{ fontSize: 14, fontWeight: 800, color: '#177a47', marginBottom: 4 }}>
                PAYMENT SUCCESSFUL
              </div>
              <div className="pos-success-amount">₹{(successTxn?.amount ?? fareNum).toFixed(2)}</div>
              {successTxn?.reference && (
                <div className="pos-success-ref">{successTxn.reference}</div>
              )}
              <div className="pos-success-msg">
                {driver?.name} has been credited ₹{(successTxn?.amount ?? fareNum).toFixed(2)}
              </div>

              <button
                className="pos-continue-btn"
                onClick={() => {
                  setScreen('fare')
                  setFareInput('')
                  setQrRequest(null)
                  setQrDataUrl('')
                  setPayStatus('Pending')
                  setSuccessTxn(null)
                  activeTokenRef.current = null
                }}
              >
                New Payment
              </button>
              <button className="pos-back-btn" onClick={handleClose} style={{ marginTop: 10 }}>
                Close Terminal
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
