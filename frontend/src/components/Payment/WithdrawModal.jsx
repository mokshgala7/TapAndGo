import React, { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

// Session token for authenticated API calls (stored by AuthContext at login).
const authHeaders = (extra = {}) => {
  let token = ''
  try { token = sessionStorage.getItem('tapgo_token') || '' } catch { /* storage unavailable */ }
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

export function WithdrawModal({ user, balance, onClose, onSuccess }) {
  const [step, setStep] = useState(1) // 1: Enter amount & request OTP, 2: Enter OTP & confirm
  const [amount, setAmount] = useState(100)
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [targetDestination, setTargetDestination] = useState('')

  const hasBank = Boolean(user?.bank_account_number)
  const hasUpi = Boolean(user?.bank_upi_id)

  const handleRequestOTP = async (e) => {
    e?.preventDefault()
    const numAmount = Number(amount)
    if (!numAmount || numAmount <= 0) {
      setError('Please enter a valid withdrawal amount.')
      return
    }
    if (numAmount > balance) {
      setError(`Insufficient wallet balance. Available balance: ₹${balance.toFixed(2)}`)
      return
    }
    if (!hasBank && !hasUpi) {
      setError('No saved withdrawal destination. Please add bank account or UPI details in your Profile first.')
      return
    }

    setLoading(true)
    setError('')

    try {
      const res = await fetch(`${API_BASE}/api/wallet/withdraw/request-otp`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          user_id: user.id,
          amount: numAmount,
        }),
      })

      const data = await res.json()

      if (res.ok && data.success) {
        setStep(2)
        setTargetDestination(
          hasBank
            ? `Bank Account (ending in XXXX ${user?.bank_account_number ? user.bank_account_number.slice(-4) : '****'})`
            : `UPI ID (${user?.bank_upi_id || ''})`
        )
        setSuccessMessage(`Security OTP sent to ${user.email}. Enter code below to confirm.`)
      } else {
        setError(data.detail || data.message || 'Failed to request OTP.')
      }
    } catch {
      setError('Backend service unavailable.')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmWithdrawal = async (e) => {
    e?.preventDefault()
    if (!otp || otp.trim().length < 4) {
      setError('Please enter the 6-digit OTP code sent to your email.')
      return
    }

    setLoading(true)
    setError('')

    try {
      const res = await fetch(`${API_BASE}/api/wallet/withdraw`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          user_id: user.id,
          amount: Number(amount),
          otp: otp.trim(),
          idempotency_key: (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`),
        }),
      })

      const data = await res.json()

      if (res.ok && data.success) {
        setSuccessMessage(data.message)
        await onSuccess?.()
        setTimeout(() => {
          onClose?.()
        }, 1500)
      } else {
        setError(data.detail || data.message || 'Withdrawal failed.')
      }
    } catch {
      setError('Backend service unavailable.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4 animate-fade-in">
      <div className="w-full max-w-md bg-white rounded-[22px] shadow-2xl overflow-hidden border border-slate-900">
        {/* Header */}
        <div className="bg-yellow-400 text-slate-900 p-5 flex items-center justify-between border-b border-slate-900/15">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-slate-900 text-yellow-400 flex items-center justify-center font-bold text-sm">
              🏦
            </span>
            <div>
              <h3 className="font-display font-extrabold text-lg tracking-[-0.02em]">Withdraw Funds</h3>
              <p className="text-xs text-[#5e4a10]">Bank Transfer / UPI Payout</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={loading}
            className="text-slate-900 hover:text-slate-600 transition-colors p-1 text-lg font-bold"
          >
            ✕
          </button>
        </div>

        <div className="p-6 space-y-5">
          {error && (
            <div className="p-3.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
              <span className="text-base">⚠️</span>
              <span>{error}</span>
            </div>
          )}

          {successMessage && (
            <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center gap-2">
              <span className="text-base">✅</span>
              <span>{successMessage}</span>
            </div>
          )}

          {step === 1 && (
            <form onSubmit={handleRequestOTP} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Available Wallet Balance
                </label>
                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 font-extrabold text-xl">
                  ₹{balance.toFixed(2)}
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Registered Destination
                </label>
                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 text-xs font-medium space-y-1">
                  {hasBank && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">Bank Account:</span>
                      <span className="font-bold">XXXX XXXX {user?.bank_account_number ? user.bank_account_number.slice(-4) : '****'}</span>
                    </div>
                  )}
                  {hasUpi && (
                    <div className="flex justify-between">
                      <span className="text-slate-500">UPI ID:</span>
                      <span className="font-bold">{user.bank_upi_id}</span>
                    </div>
                  )}
                  {!hasBank && !hasUpi && (
                    <div className="text-amber-700 font-bold">No registered bank/UPI details in profile.</div>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Withdrawal Amount (₹)
                </label>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 font-bold text-base">
                    ₹
                  </span>
                  <input
                    type="number"
                    min="1"
                    max={balance}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="Enter withdrawal amount"
                    required
                    disabled={loading}
                    className="w-full pl-8 pr-4 py-3 rounded-xl border border-slate-300 focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10 font-bold text-lg text-slate-900 outline-none transition-all"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || !hasBank && !hasUpi}
                className="w-full py-3.5 rounded-[14px] bg-yellow-400 hover:bg-yellow-500 text-slate-900 font-extrabold text-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <span className="inline-block w-4 h-4 border-2 border-slate-900 border-t-transparent rounded-full animate-spin"></span>
                    Sending Security OTP...
                  </>
                ) : (
                  <>
                    <span>Send Email Security OTP</span>
                    <span>→</span>
                  </>
                )}
              </button>
            </form>
          )}

          {step === 2 && (
            <form onSubmit={handleConfirmWithdrawal} className="space-y-4">
              <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200 text-xs space-y-1">
                <div className="flex justify-between text-slate-600">
                  <span>Withdrawal Amount:</span>
                  <strong className="text-slate-900 font-bold">₹{Number(amount).toFixed(2)}</strong>
                </div>
                <div className="flex justify-between text-slate-600">
                  <span>Destination:</span>
                  <strong className="text-slate-900 font-bold">{targetDestination}</strong>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Enter 6-Digit Email OTP
                </label>
                <input
                  type="text"
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  placeholder="••••••"
                  required
                  disabled={loading}
                  className="w-full text-center tracking-[0.5em] font-mono text-2xl py-3 rounded-xl border border-slate-300 focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10 text-slate-900 outline-none transition-all"
                />
                <p className="text-[11px] text-slate-500 mt-1 text-center">
                  OTP sent to <span className="font-bold">{user?.email || 'your email'}</span>. Valid for 5 minutes.
                </p>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  disabled={loading}
                  className="w-1/3 py-3 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold text-xs transition-all"
                >
                  ← Back
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-2/3 py-3 rounded-[14px] bg-yellow-400 hover:bg-yellow-500 text-slate-900 font-extrabold text-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  {loading ? (
                    <>
                      <span className="inline-block w-4 h-4 border-2 border-slate-900 border-t-transparent rounded-full animate-spin"></span>
                      Verifying...
                    </>
                  ) : (
                    <span>Confirm Withdrawal</span>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

export default WithdrawModal
