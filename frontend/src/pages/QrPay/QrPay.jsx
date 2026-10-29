import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '../../routes/navigation.jsx'
import { useAuth } from '../../context/AuthContext.jsx'
import { useWallet } from '../../context/WalletContext.jsx'
import RazorpayAddMoneyModal from '../../components/Payment/RazorpayAddMoneyModal.jsx'
import {
  clearPendingQrToken,
  getPendingQrToken,
  readQrTokenFromLocation,
  setPendingQrToken,
} from '../../utils/qrLink.js'
import { DriverAvatar, VehicleArt } from './QrPayArt.jsx'
import './QrPay.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

function sessionToken() {
  try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' }
}

// One key per page load: double taps and retries replay the same payment instead of charging twice.
function newIdempotencyKey() {
  const c = globalThis.crypto
  if (c?.randomUUID) return c.randomUUID()
  const bytes = new Uint8Array(16)
  c.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const rupees = (n) =>
  `₹${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const clock = (secs) => {
  const s = Math.max(0, Math.floor(secs))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// phase: loading | ready | paying | otp | success | insufficient | expired | paid | cancelled |
//        invalid | failed | busy | network | wrongrole
// otp: the payment needs the 6-digit code emailed to the passenger. It is entered ONLY on the driver's POS; this page
//      just waits (polling my-status) and can cancel. Money has not moved yet.
const OTP_POLL_MS = 2000
const END_COPY = {
  expired: { icon: '⏱', title: 'This QR code has expired', body: 'Ask the driver to show a new code and scan it again.' },
  paid: { icon: '✓', title: 'Already paid', body: 'This fare has already been paid. Nothing more is needed.' },
  cancelled: { icon: '✕', title: 'Cancelled by the driver', body: 'The driver cancelled this payment request. You have not been charged.' },
  invalid: { icon: '?', title: 'Invalid link', body: 'This payment link is not valid. Please scan the code on the driver’s terminal again.' },
  failed: { icon: '!', title: 'Payment could not be completed', body: 'You have not been charged. Ask the driver for a new code.' },
}

function QrPay() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { refreshWallet } = useWallet()

  const [token] = useState(() => readQrTokenFromLocation() || getPendingQrToken())
  const [phase, setPhase] = useState('loading')
  const [info, setInfo] = useState(null)
  const [balance, setBalance] = useState(0)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [message, setMessage] = useState('')
  const [result, setResult] = useState(null)
  const [showTopUp, setShowTopUp] = useState(false)
  const [otp, setOtp] = useState(null) // { challenge_id, email_hint, attempts_left, resends_left }
  const [otpLeft, setOtpLeft] = useState(0)
  const otpDeadline = useRef(0)
  const [photoBroken, setPhotoBroken] = useState({ driver: false, vehicle: false })

  const idempotencyKey = useRef(null)
  if (idempotencyKey.current === null) idempotencyKey.current = newIdempotencyKey()
  const deadline = useRef(0) // performance.now() value at which the request expires
  const payingRef = useRef(false)
  const phaseRef = useRef('loading')
  const setPhaseBoth = useCallback((next) => {
    phaseRef.current = next
    setPhase(next)
  }, [])

  // Applies a challenge view from the server (otp_required / otp_invalid / resend) to the OTP step.
  const showChallenge = useCallback((c, err = '') => {
    const secs = Number(c.expires_in_seconds ?? 0)
    if (c.expires_in_seconds != null) otpDeadline.current = performance.now() + secs * 1000
    setOtp((prev) => ({ ...(prev || {}), ...c }))
    setOtpLeft(Math.ceil((otpDeadline.current - performance.now()) / 1000))
    setMessage(err)
    setPhaseBoth('otp')
  }, [setPhaseBoth])

  const authHeaders = () => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken()}` })

  const backToLogin = useCallback(() => {
    if (token) setPendingQrToken(token)
    try {
      sessionStorage.setItem('tapgo_registration_notice', 'Log in to complete your payment.')
    } catch { /* optional hint */ }
    navigate('/login')
  }, [navigate, token])

  const applyGone = useCallback((status) => {
    const map = { Expired: 'expired', Completed: 'paid', Cancelled: 'cancelled', Failed: 'failed', Processing: 'busy' }
    if (status === 'AwaitingOtp') return setPhaseBoth('busy')
    setPhaseBoth(map[status] || 'failed')
  }, [setPhaseBoth])

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/qr/${encodeURIComponent(token)}`, { headers: authHeaders() })
      if (res.status === 401) return backToLogin()
      const data = await res.json().catch(() => ({}))
      if (res.status === 404) return setPhaseBoth('invalid')
      if (res.status === 403) {
        setMessage(data.detail || '')
        return setPhaseBoth('wrongrole')
      }
      if (res.status === 410) return applyGone(data.status)
      if (!res.ok || !data.success) {
        setMessage(data.detail || 'Could not load this payment.')
        return setPhaseBoth('network')
      }
      const p = data.payment
      if (p.status === 'AwaitingOtp' && data.otp) {
        // The page was reopened mid-verification: resume the OTP step.
        setInfo(p)
        setBalance(Number(p.wallet_balance || 0))
        return showChallenge(data.otp)
      }
      deadline.current = performance.now() + Number(p.seconds_remaining ?? p.remaining_seconds ?? 0) * 1000
      setInfo(p)
      setBalance(Number(p.wallet_balance || 0))
      setSecondsLeft(Number(p.seconds_remaining ?? p.remaining_seconds ?? 0))
      setPhaseBoth('ready')
    } catch {
      setMessage('Could not reach the server. Check your connection and try again.')
      setPhaseBoth('network')
    }
  }, [token, backToLogin, applyGone, setPhaseBoth, showChallenge])

  const reload = () => {
    setPhaseBoth('loading')
    load()
  }

  const isDriver = (user?.account_type || user?.role) === 'driver'

  // Gate on sign-in, then load the payment once. The token stays stored across the login detour.
  useEffect(() => {
    if (!token) return
    setPendingQrToken(token)
    if (!user) return backToLogin()
    if (isDriver) return
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user?.id])

  // Live countdown driven by the server's seconds_remaining (immune to a wrong phone clock).
  useEffect(() => {
    if (!['ready', 'insufficient', 'paying', 'retry'].includes(phase)) return undefined
    const tick = () => {
      const left = Math.max(0, Math.ceil((deadline.current - performance.now()) / 1000))
      setSecondsLeft(left)
      // A payment already in flight decides its own outcome; only idle screens flip to expired.
      if (left === 0 && phaseRef.current !== 'paying') setPhaseBoth('expired')
    }
    tick()
    const id = window.setInterval(tick, 500)
    return () => window.clearInterval(id)
  }, [phase, setPhaseBoth])

  // Waiting for the code to be entered on the POS: countdown, and poll the payment until it succeeds or fails.
  useEffect(() => {
    if (phase !== 'otp') return undefined
    const tick = () => setOtpLeft(Math.max(0, Math.ceil((otpDeadline.current - performance.now()) / 1000)))
    tick()
    const clockId = window.setInterval(tick, 500)
    let stopped = false
    const poll = async () => {
      if (stopped || phaseRef.current !== 'otp') return
      try {
        const res = await fetch(`${API_BASE}/api/qr/${encodeURIComponent(token)}/my-status`, { headers: authHeaders() })
        if (res.status === 401) return backToLogin()
        const data = await res.json().catch(() => ({}))
        if (stopped || phaseRef.current !== 'otp') return
        if (res.ok && data.status === 'Completed') {
          const newBalance = Number(data.wallet_balance ?? 0)
          setBalance(newBalance)
          setResult({ amount: Number(data.amount ?? info?.amount), driver: info?.driver_name || 'the driver',
                      reference: data.reference, balance: newBalance })
          setPhaseBoth('success')
          refreshWallet?.()
          return
        }
        if (res.ok && data.status === 'Failed') {
          setMessage(data.message || 'The payment could not be completed. You have not been charged.')
          setPhaseBoth('failed')
          return
        }
        if (res.ok && data.status === 'AwaitingOtp' && data.otp) {
          if (data.otp.expires_in_seconds != null) otpDeadline.current = performance.now() + Number(data.otp.expires_in_seconds) * 1000
          setOtp((prev) => ({ ...(prev || {}), ...data.otp }))
        }
      } catch { /* offline for a moment: keep waiting, the POS decides the outcome */ }
    }
    const pollId = window.setInterval(poll, OTP_POLL_MS)
    return () => { stopped = true; window.clearInterval(clockId); window.clearInterval(pollId) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, token])

  // Success / OTP step shared by the confirm response.
  const applyOutcome = useCallback((res, data) => {
    if (res.ok && data.success) {
      const newBalance = Number(data.wallet?.balance ?? 0)
      setBalance(newBalance)
      setResult({
        amount: Number(data.transaction?.amount ?? info?.amount),
        driver: data.transaction?.driver_name || info?.driver_name || 'the driver',
        reference: data.transaction?.reference,
        balance: newBalance,
      })
      setPhaseBoth('success')
      refreshWallet?.()
      return true
    }
    if (data.status === 'otp_required') {
      showChallenge(data)
      return true
    }
    return false
  }, [info, refreshWallet, setPhaseBoth, showChallenge])

  const cancelOtp = async () => {
    try {
      await fetch(`${API_BASE}/api/qr/${encodeURIComponent(token)}/cancel-otp`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ challenge_id: otp.challenge_id }),
      })
    } catch { /* the code expires on its own; nothing was charged */ }
    setMessage('You cancelled this payment. You have not been charged.')
    setPhaseBoth('failed')
  }

  const payNow = useCallback(async () => {
    if (payingRef.current) return
    payingRef.current = true
    setPhaseBoth('paying')
    setMessage('')
    try {
      const res = await fetch(`${API_BASE}/api/qr/${encodeURIComponent(token)}/confirm`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ idempotency_key: idempotencyKey.current }),
      })
      if (res.status === 401) return backToLogin()
      const data = await res.json().catch(() => ({}))

      if (applyOutcome(res, data)) {
        // success or OTP step handled
      } else if (data.code === 'insufficient_balance') {
        setBalance(Number(data.balance || 0))
        setPhaseBoth('insufficient')
      } else if (res.status === 410) {
        applyGone(data.status)
      } else if (res.status === 404) {
        setPhaseBoth('invalid')
      } else if (res.status === 409) {
        setPhaseBoth('busy')
      } else {
        setMessage(data.detail || 'Payment failed.')
        setPhaseBoth('failed')
      }
    } catch {
      // The request may or may not have reached the server. Retrying with the same key is safe.
      setMessage('Could not reach the server. Your payment may not have gone through; tap Retry to check safely.')
      setPhaseBoth('retry')
    } finally {
      payingRef.current = false
    }
  }, [token, applyGone, applyOutcome, backToLogin, setPhaseBoth])

  const finish = () => {
    clearPendingQrToken()
    navigate('/passenger')
  }

  const switchAccount = async () => {
    await logout()
    if (token) setPendingQrToken(token)
    navigate('/login')
  }

  const short = info && balance < Number(info.amount)

  // Missing token / driver account are known from props alone, so they need no effect or state.
  const shown = !token ? 'invalid' : isDriver ? 'wrongrole' : phase

  let body
  if (shown === 'loading') {
    body = <p className="qrpay-note">Loading payment…</p>
  } else if (shown === 'success' && result) {
    body = (
      <>
        <div className="qrpay-icon qrpay-ok" aria-hidden="true">✓</div>
        <h1 className="qrpay-title">Payment successful</h1>
        <p className="qrpay-amount">{rupees(result.amount)}</p>
        <dl className="qrpay-rows">
          <div><dt>Paid to</dt><dd>{result.driver}</dd></div>
          <div><dt>New wallet balance</dt><dd>{rupees(result.balance)}</dd></div>
          {result.reference && <div><dt>Reference</dt><dd>{result.reference}</dd></div>}
        </dl>
        <button type="button" className="qrpay-btn" onClick={finish}>Done</button>
      </>
    )
  } else if (END_COPY[shown]) {
    const c = END_COPY[shown]
    body = (
      <>
        <div className={`qrpay-icon ${shown === 'paid' ? 'qrpay-ok' : 'qrpay-bad'}`} aria-hidden="true">{c.icon}</div>
        <h1 className="qrpay-title">{c.title}</h1>
        <p className="qrpay-note">{shown === 'failed' && message ? message : c.body}</p>
        <button type="button" className="qrpay-btn" onClick={finish}>Back to my wallet</button>
      </>
    )
  } else if (shown === 'otp' && otp && info) {
    const expired = otpLeft === 0
    body = (
      <div className="qp-wait" role="status" aria-live="polite">
        <div className="qp-pulse" aria-hidden="true"><span className="qp-pulse-dot" /></div>
        <p className="qrpay-label">Verify your payment</p>
        <h1 className="qrpay-driver">{rupees(info.amount)} to {info.driver_name}</h1>
        <p className="qrpay-note">
          A code was sent to your email <strong>{otp.email_hint || ''}</strong>.<br />
          <strong>Enter it on the driver&rsquo;s POS screen.</strong>
        </p>
        {message && <div className="qrpay-warn" role="alert">{message}</div>}
        <dl className="qrpay-rows">
          <div><dt>Code expires in</dt><dd className="qrpay-timer">{clock(otpLeft)}</dd></div>
          <div><dt>Attempts left</dt><dd>{otp.attempts_left ?? 3}</dd></div>
        </dl>
        <p className="qrpay-note qp-small">
          {expired ? 'The code has expired. This payment will be cancelled.' : 'Nothing is charged until the driver enters the correct code. This page updates by itself.'}
        </p>
        <button type="button" className="qrpay-link" onClick={cancelOtp}>Cancel payment</button>
      </div>
    )
  } else if (shown === 'wrongrole') {
    body = (
      <>
        <div className="qrpay-icon qrpay-bad" aria-hidden="true">!</div>
        <h1 className="qrpay-title">Passenger account needed</h1>
        <p className="qrpay-note">You are signed in with a driver account. Sign in with a passenger account to pay this fare.</p>
        <button type="button" className="qrpay-btn" onClick={switchAccount}>Sign in as a passenger</button>
      </>
    )
  } else if (shown === 'busy') {
    body = (
      <>
        <h1 className="qrpay-title">Payment is being processed</h1>
        <p className="qrpay-note">Please wait a moment, then check again. You will not be charged twice.</p>
        <button type="button" className="qrpay-btn" onClick={reload}>Check again</button>
      </>
    )
  } else if (shown === 'network') {
    body = (
      <>
        <h1 className="qrpay-title">Connection problem</h1>
        <p className="qrpay-note">{message}</p>
        <button type="button" className="qrpay-btn" onClick={reload}>Try again</button>
      </>
    )
  } else if (info) {
    // ready | paying | insufficient | retry
    const paying = shown === 'paying'
    const driverPhoto = info.driver_photo_url && !photoBroken.driver ? info.driver_photo_url : null
    const vehiclePhoto = info.vehicle_photo_url && !photoBroken.vehicle ? info.vehicle_photo_url : null
    const vehicleName = [info.vehicle_type, info.vehicle_registration].filter(Boolean).join(' ')
    body = (
      <>
        <div className="qp-driver-row">
          <div className="qp-avatar-wrap">
            {driverPhoto ? (
              <img className="qp-avatar-photo" src={driverPhoto} alt={`Photo of ${info.driver_name}`} width="88" height="88"
                   decoding="async" onError={() => setPhotoBroken((p) => ({ ...p, driver: true }))} />
            ) : (
              <DriverAvatar label={`Cartoon avatar of ${info.driver_name}`} />
            )}
          </div>
          <div className="qp-driver-text">
            <p className="qrpay-label">You are paying</p>
            <h1 className="qp-driver-name">{info.driver_name}</h1>
          </div>
        </div>

        <figure className="qp-vehicle">
          {vehiclePhoto ? (
            <img className="qp-vehicle-photo" src={vehiclePhoto} alt={vehicleName ? `Vehicle: ${vehicleName}` : 'Driver’s vehicle'}
                 width="640" height="360" decoding="async" loading="lazy"
                 onError={() => setPhotoBroken((p) => ({ ...p, vehicle: true }))} />
          ) : (
            <VehicleArt type={info.vehicle_type} label={vehicleName ? `Vehicle: ${vehicleName}` : 'Vehicle illustration'} />
          )}
          <figcaption className="qp-vehicle-cap">
            <span className="qp-plate">{info.vehicle_registration || 'Number not set'}</span>
            <span className="qp-vtype">{info.vehicle_type || 'Vehicle'}</span>
          </figcaption>
        </figure>

        <div className="qp-fare">
          <span className="qp-fare-label">Fare to pay</span>
          <span className="qp-fare-amount">{rupees(info.amount)}</span>
        </div>

        <dl className="qrpay-rows">
          <div><dt>Your wallet balance</dt><dd className={short ? 'qrpay-low' : ''}>{rupees(balance)}</dd></div>
          <div><dt>Time left</dt><dd className="qrpay-timer">{clock(secondsLeft)}</dd></div>
        </dl>

        {(shown === 'insufficient' || short) && (
          <div className="qrpay-warn" role="alert">
            <strong>Insufficient balance.</strong> You need {rupees(Number(info.amount) - balance)} more to pay this fare.
          </div>
        )}
        {shown === 'retry' && <div className="qrpay-warn" role="alert">{message}</div>}

        {(shown === 'insufficient' || short) && (
          <button type="button" className="qrpay-btn" onClick={() => setShowTopUp(true)}>Add Money</button>
        )}
        {!(shown === 'insufficient' || short) && (
          <button type="button" className="qrpay-btn" onClick={payNow} disabled={paying}>
            {paying ? 'Paying…' : shown === 'retry' ? `Retry ${rupees(info.amount)}` : `Pay Now ${rupees(info.amount)}`}
          </button>
        )}
        <button type="button" className="qrpay-link" onClick={finish} disabled={paying}>Cancel</button>
      </>
    )
  } else {
    body = <p className="qrpay-note">Loading payment…</p>
  }

  return (
    <div className="qrpay-page">
      <div className="qrpay-card">
        <div className="qrpay-brand">Tap&amp;Go</div>
        {body}
      </div>

      {showTopUp && (
        <RazorpayAddMoneyModal
          user={user}
          onClose={() => setShowTopUp(false)}
          onSuccess={(newBalance) => {
            setShowTopUp(false)
            const next = Number(newBalance)
            if (newBalance != null && Number.isFinite(next)) {
              setBalance(next)
              if (phaseRef.current === 'insufficient') setPhaseBoth('ready')
            } else {
              load() // balance unknown: reload the payment, which also returns the fresh balance
            }
            refreshWallet?.()
          }}
          onFailure={() => setShowTopUp(false)}
        />
      )}
    </div>
  )
}

export default QrPay
