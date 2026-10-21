import React, { useState, useEffect, useRef } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

function getToken() {
  try { return sessionStorage.getItem('tapgo_token') || '' } catch { return '' }
}

function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (window.Razorpay) { resolve(true); return }
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => resolve(true)
    script.onerror = () => resolve(false)
    document.body.appendChild(script)
  })
}

export function RazorpayAddMoneyModal({ user, onClose, onSuccess, onFailure }) {
  const [step, setStep] = useState(1)   // 1: amount + request OTP,  2: enter OTP + proceed
  const [amount, setAmount] = useState(250)
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [statusMessage, setStatusMessage] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const isProcessingPaymentRef = useRef(false)

  const PRESET_AMOUNTS = [100, 250, 500, 1000]

  // Cooldown ticker
  useEffect(() => {
    if (cooldown <= 0) return
    const t = setTimeout(() => setCooldown(c => Math.max(0, c - 1)), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  /* ── Step 1: Request OTP ─────────────────────────────────────────── */
  const handleRequestOTP = async (e) => {
    e?.preventDefault()
    const numAmount = Number(amount)
    if (!numAmount || numAmount < 1) { setError('Please enter a valid amount of at least ₹1.00'); return }
    setLoading(true); setError(''); setStatusMessage('')
    try {
      const res = await fetch(`${API_BASE}/api/payment/topup/request-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ amount: numAmount }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setCooldown(60)
        setStep(2)
        setStatusMessage(`OTP sent to ${user?.email || 'your email'}. Valid for 5 minutes.`)
      } else {
        setError(data.detail || data.message || 'Failed to send OTP.')
      }
    } catch {
      setError('Service unavailable. Please try again.')
    } finally { setLoading(false) }
  }

  /* ── Step 2: Verify OTP → Razorpay checkout ─────────────────────── */
  const handleInitiatePayment = async (e) => {
    e?.preventDefault()
    const numAmount = Number(amount)
    if (!otp || otp.trim().length < 6) { setError('Please enter the 6-digit OTP sent to your email.'); return }
    if (!numAmount || numAmount < 1) { setError('Invalid amount.'); return }

    setLoading(true); setError(''); setStatusMessage('Loading Razorpay secure payment gateway...')

    const resScript = await loadRazorpayScript()
    if (!resScript) {
      setError('Failed to load Razorpay. Please check your internet connection.')
      setLoading(false); setStatusMessage(''); return
    }

    try {
      setStatusMessage('Creating secure payment order...')
      const orderRes = await fetch(`${API_BASE}/api/payment/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ amount: numAmount, otp: otp.trim() }),
      })
      const orderData = await orderRes.json()
      if (!orderRes.ok || !orderData.success) throw new Error(orderData.detail || 'Failed to create payment order.')

      const { order_id, amount: paiseAmount, currency, key_id } = orderData
      const publicKey = key_id && key_id !== 'rzp_test_placeholder'
        ? key_id : (import.meta.env.VITE_RAZORPAY_KEY_ID || 'rzp_test_placeholder')

      setStatusMessage('Opening Razorpay checkout...')

      const options = {
        key: publicKey,
        amount: paiseAmount,
        currency: currency || 'INR',
        name: 'Tap & Go',
        description: `Wallet Top-up (₹${numAmount.toFixed(2)})`,
        order_id,
        prefill: { name: user.name || '', email: user.email || '', contact: user.phone || '' },
        theme: { color: '#141210' },
        modal: {
          ondismiss: () => {
            setLoading(false)
            setStatusMessage('')
            setError('Payment checkout cancelled.')
            if (onFailure) {
              setTimeout(() => {
                onFailure('Payment checkout cancelled.')
              }, 800)
            }
          },
        },
        handler: async (response) => {
          if (isProcessingPaymentRef.current) return
          isProcessingPaymentRef.current = true
          setStatusMessage('Verifying payment signature with server...')
          try {
            // Only a real checkout result can be verified; nothing is invented here.
            if (!response.razorpay_payment_id || !response.razorpay_signature) {
              throw new Error('Payment could not be confirmed. If money was debited, it will be reconciled automatically.')
            }
            // The server credits the amount of the order it created; it ignores any amount sent here.
            const verifyRes = await fetch(`${API_BASE}/api/payment/verify-payment`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id || order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
                payment_method: response.method || response.payment_method || undefined,
              }),
            })
            const verifyData = await verifyRes.json()
            if (verifyRes.ok && verifyData.success) {
              setStatusMessage('Payment verified! Crediting wallet...')
              try {
                await onSuccess?.(verifyData.balance)
              } catch (sErr) {
                console.error('onSuccess callback error:', sErr)
              }
              onClose?.()
            } else {
              isProcessingPaymentRef.current = false
              throw new Error(verifyData.detail || verifyData.message || 'Payment verification failed.')
            }
          } catch (vErr) {
            isProcessingPaymentRef.current = false
            setError(vErr.message || 'Verification failed.')
            setLoading(false)
            setStatusMessage('')
            if (onFailure) {
              setTimeout(() => {
                onFailure(vErr.message || 'Payment verification failed.')
              }, 1200)
            }
          }
        },
      }

      const rzp = new window.Razorpay(options)
      rzp.on('payment.failed', (resp) => {
        const failReason = resp.error?.description || 'Payment failed. Please try again.'
        setError(failReason)
        setLoading(false)
        setStatusMessage('')
        if (onFailure) {
          setTimeout(() => {
            onFailure(failReason)
          }, 1200)
        }
      })
      rzp.open()
    } catch (err) {
      setError(err.message || 'Could not launch payment.')
      setLoading(false)
      setStatusMessage('')
    }
  }

  /* ── Render ──────────────────────────────────────────────────────── */
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 animate-fade-in">
      <div className="w-full max-w-md bg-white rounded-[22px] shadow-2xl overflow-hidden border border-slate-900">
        {/* Header */}
        <div className="bg-yellow-400 text-slate-900 p-5 flex items-center justify-between border-b border-slate-900/15">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-slate-900 text-yellow-400 flex items-center justify-center font-bold text-sm">₹</span>
            <div>
              <h3 className="font-display font-extrabold text-lg tracking-[-0.02em]">Add Money to Wallet</h3>
              <p className="text-xs text-[#5e4a10]">
                {step === 1 ? 'Step 1 of 2 — Select Amount' : 'Step 2 of 2 — Verify OTP'}
              </p>
            </div>
          </div>
          <button onClick={onClose} disabled={loading} className="text-slate-900 hover:text-slate-600 transition-colors p-1 text-lg font-bold">✕</button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5">
          {error && (
            <div className="p-3.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
              <span className="text-base">⚠️</span><span>{error}</span>
            </div>
          )}
          {statusMessage && !error && step === 2 && (
            <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center gap-2">
              <span>✅</span><span>{statusMessage}</span>
            </div>
          )}
          {loading && !error && (
            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs font-semibold flex items-center gap-2">
              <span className="inline-block w-4 h-4 border-2 border-slate-800 border-t-transparent rounded-full animate-spin"></span>
              <span>Please wait...</span>
            </div>
          )}

          {/* Step 1 — Amount + Request OTP */}
          {step === 1 && (
            <form onSubmit={handleRequestOTP} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">Select or Enter Amount (₹)</label>
                <div className="grid grid-cols-4 gap-2 mb-3">
                  {PRESET_AMOUNTS.map((amt) => (
                    <button key={amt} type="button" onClick={() => setAmount(amt)}
                      className={`py-2 text-xs font-bold rounded-xl border transition-all ${amount === amt ? 'bg-slate-900 text-yellow-400 border-slate-900 shadow' : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'}`}>
                      +₹{amt}
                    </button>
                  ))}
                </div>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 font-bold text-base">₹</span>
                  <input type="number" min="1" step="1" value={amount} onChange={(e) => setAmount(e.target.value)}
                    placeholder="Enter amount" disabled={loading}
                    className="w-full pl-8 pr-4 py-3 rounded-xl border border-slate-300 focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10 font-bold text-lg text-slate-900 outline-none transition-all" />
                </div>
              </div>

              <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-200 text-xs text-slate-600 space-y-1">
                <div className="flex justify-between"><span>Top-up Amount:</span><strong className="text-slate-900">₹{Number(amount || 0).toFixed(2)}</strong></div>
                <div className="flex justify-between border-t border-slate-200 pt-1.5 font-bold text-slate-900 text-sm"><span>Total Payable:</span><span>₹{Number(amount || 0).toFixed(2)}</span></div>
              </div>

              <button type="submit" disabled={loading}
                className="w-full py-3.5 rounded-[14px] bg-yellow-400 hover:bg-yellow-500 text-slate-900 font-extrabold text-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50">
                {loading ? <><span className="inline-block w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin"></span> Sending OTP...</>
                  : <><span>Send Security OTP</span><span>→</span></>}
              </button>
              <p className="text-[11px] text-center text-slate-400">🔒 A 6-digit OTP will be sent to your registered email</p>
            </form>
          )}

          {/* Step 2 — Enter OTP + Proceed to Checkout */}
          {step === 2 && (
            <form onSubmit={handleInitiatePayment} className="space-y-4">
              <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200 text-xs space-y-1">
                <div className="flex justify-between text-slate-600"><span>Top-up Amount:</span><strong className="text-slate-900">₹{Number(amount).toFixed(2)}</strong></div>
              </div>
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">Enter 6-Digit Email OTP</label>
                <input type="text" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                  placeholder="••••••" required disabled={loading}
                  className="w-full text-center tracking-[0.5em] font-mono text-2xl py-3 rounded-xl border border-slate-300 focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10 text-slate-900 outline-none transition-all" />
                <p className="text-[11px] text-slate-500 mt-1 text-center">
                  OTP sent to <span className="font-bold">{user?.email || 'your email'}</span>. Valid for 5 minutes.
                </p>
              </div>

              <div className="flex gap-2">
                <button type="button" onClick={() => { setStep(1); setOtp(''); setError(''); setStatusMessage('') }} disabled={loading}
                  className="w-1/3 py-3 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold text-xs transition-all">
                  ← Back
                </button>
                <button type="submit" disabled={loading}
                  className="w-2/3 py-3.5 rounded-[14px] bg-yellow-400 hover:bg-yellow-500 text-slate-900 font-extrabold text-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50">
                  {loading ? <><span className="inline-block w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin"></span> Processing...</>
                    : <><span>Proceed to Secure Checkout</span><span>→</span></>}
                </button>
              </div>

              {cooldown > 0
                ? <p className="text-[11px] text-center text-slate-400">Resend OTP in {cooldown}s</p>
                : <button type="button" onClick={() => { setStep(1); setOtp(''); setError(''); setStatusMessage('') }}
                    className="w-full text-[11px] text-slate-500 hover:text-slate-700 underline">
                    ← Change amount or resend OTP
                  </button>
              }
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

export default RazorpayAddMoneyModal
