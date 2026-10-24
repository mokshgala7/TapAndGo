import { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react'
import { useAuth } from './AuthContext.jsx'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

// Session token for authenticated API calls (stored by AuthContext at login).
const authHeaders = (extra = {}) => {
  let token = ''
  try { token = sessionStorage.getItem('tapgo_token') || '' } catch { /* storage unavailable */ }
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}

const WalletContext = createContext(null)

export function WalletProvider({ children }) {
  const { user } = useAuth()
  const [balance, setBalance] = useState(0)
  const [isFrozen, setIsFrozen] = useState(false)
  const [transactions, setTransactions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchWallet = useCallback(async (optimisticBalance) => {
    if (typeof optimisticBalance === 'number' && !isNaN(optimisticBalance)) {
      setBalance(optimisticBalance)
    }
    if (!user?.id) {
      setBalance(0)
      setIsFrozen(false)
      setTransactions([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const [wRes, tRes] = await Promise.all([
        fetch(`${API_BASE}/api/wallet/${user.id}`, { headers: authHeaders() }),
        fetch(`${API_BASE}/api/wallet/${user.id}/transactions`, { headers: authHeaders() }),
      ])
      const wData = await wRes.json().catch(() => ({}))
      const tData = await tRes.json().catch(() => ({}))

      if (wRes.ok && wData.success && wData.wallet) {
        setBalance(wData.wallet.balance)
        setIsFrozen(Boolean(wData.wallet.is_frozen))
      }
      if (tRes.ok && tData.success && Array.isArray(tData.transactions)) {
        // Keep the backend's labels: it knows the transaction type and the driver's name.
        const formatted = tData.transactions.map((t) => {
          const kind = t.transaction_type === 'ride_payment' || t.type === 'Ride Payment' || t.type === 'Ride Payment Received' ? 'ride'
            : t.transaction_type === 'withdrawal' || t.payment_method === 'BANK_TRANSFER' ? 'withdraw'
            : 'topup'
          return {
            id: t.reference || `TXN-${t.id}`,
            driver: kind === 'ride' ? (t.driver || 'Driver') : kind === 'withdraw' ? 'Withdrawal to Bank' : t.type || 'Wallet Top-up',
            vehicleType: kind,
            vehicleNumber: null,
            fare: t.is_credit ? -t.amount : t.amount,
            route: kind === 'ride' ? 'Ride payment' : kind === 'withdraw' ? 'Bank Transfer' : t.type || 'Wallet Top-up',
            method: t.payment_method,
            timestamp: t.timestamp || Date.now(),
            status: t.status,
            isDemo: Boolean(t.is_synthetic),
            raw: t,
          }
        })
        setTransactions(formatted)
      } else {
        // Do not show stale or empty history as if it were real: surface the failure.
        setError(tRes.status === 401 || tRes.status === 403
          ? 'Your session has expired. Please log in again to see your transactions.'
          : (tData && tData.detail) || 'Could not load your transactions. Please try again.')
      }
    } catch (err) {
      setError('Could not sync wallet with database.')
    } finally {
      setLoading(false)
    }
  }, [user?.id])

  useEffect(() => {
    fetchWallet()
  }, [fetchWallet])

  const addMoney = async (amount) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    try {
      const res = await fetch(`${API_BASE}/api/wallet/topup`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ user_id: user.id, amount, payment_method: import.meta.env.VITE_PAYMENT_METHOD || 'payment_gateway' }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        await fetchWallet()
        return { success: true, message: data.message }
      } else {
        return { success: false, message: data.detail || 'Failed to add money.' }
      }
    } catch {
      return { success: false, message: 'Backend unavailable.' }
    }
  }

  const withdraw = async (amount) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    try {
      const res = await fetch(`${API_BASE}/api/wallet/withdraw`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ user_id: user.id, amount }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        await fetchWallet()
        return { success: true, message: data.message }
      } else {
        return { success: false, message: data.detail || 'Withdrawal failed.' }
      }
    } catch {
      return { success: false, message: 'Backend unavailable.' }
    }
  }

  const payFare = async ({ driver, driver_id, vehicleType, vehicleNumber, fare, method }) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    // The server only pays a verified driver; it no longer picks one for you.
    if (!driver_id) return { success: false, message: 'Paying by QR needs a verified driver, which is not available yet.' }
    try {
      const res = await fetch(`${API_BASE}/api/wallet/pay`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          passenger_id: user.id,
          driver_id,
          fare,
          payment_method: method || 'QR',
          idempotency_key: (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`),
        }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        await fetchWallet()
        return { success: true, fare, driver: driver || 'Driver', txn: data.transaction }
      } else {
        return { success: false, message: data.detail || 'Payment failed.' }
      }
    } catch {
      return { success: false, message: 'Backend unavailable.' }
    }
  }

  const value = useMemo(
    () => ({ balance, isFrozen, transactions, loading, error, addMoney, withdraw, payFare, refreshWallet: fetchWallet }),
    [balance, isFrozen, transactions, loading, error, fetchWallet],
  )

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
}

export function useWallet() {
  const ctx = useContext(WalletContext)
  if (!ctx) throw new Error('useWallet must be used inside a WalletProvider')
  return ctx
}
